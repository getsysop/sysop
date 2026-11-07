"""_doc_drift.py — how far a branch has moved past a pending doc's `branch_tip:`.

Private shared helper (underscore-prefixed — imported, never run). `/review-close` Step 3b's
collect (`pending_doc_collect.py`) and `/sitrep`'s survey (`sitrep_survey.py`) both import it,
so the close and the survey give one verdict on a doc: the survey must never call a doc stale
that the close collects, or current that the close refuses.

`measure(tip, branch, where)` counts the commits on `refs/heads/<branch>` the doc does not
describe. When `tip` is an ancestor of the branch that is `tip..branch`. When it is not, the
branch was rewritten after the doc was stamped (a close rebases every branch it merges), and the
doc's own commits are paired with their copies by `git patch-id --stable`, as one run in order;
the count is the commits after that run. A pairing that cannot be proven counts by ancestry, as before, so
this only ever turns that count's refusal into a pass.

`covering(...)` reads a branch's docs as a set: an older doc a close is holding (`held_since:`)
is covered by a later doc in its own `<stem>--<n>.md` family when the branch is an ancestor of
that doc's tip, in the older doc's repository.

Every git call runs in `where` with git's discovery variables stripped, so `where` decides the
repository, and with a timeout. None of them runs a program the repository's config names: no
external diff, textconv filter or signature check.
"""
from __future__ import annotations

import os
import re
import subprocess

_STRIP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")
_FAMILY = re.compile(r"(.+)--(\d+)\.md\Z")


def _git(where, *args, stdin: bytes | None = None, timeout: int = 10):
    """`(exit code, stdout bytes)`, or None when git could not be run or timed out."""
    try:
        r = subprocess.run(["git", "-C", str(where), *args], capture_output=True,
                           timeout=timeout, input=stdin,
                           env={k: v for k, v in os.environ.items() if k not in _STRIP})
    except (OSError, subprocess.SubprocessError):
        return None
    return r.returncode, r.stdout


def _counted(base: str, ref: str, where, how: str):
    """`(count, log, how)` over `base..ref`, or None when it does not resolve."""
    r = _git(where, "rev-list", "--count", f"{base}..{ref}")
    if r is None or r[0] != 0 or not r[1].strip().isdigit():
        return None
    n = int(r[1])
    if not n:
        return 0, "", ""
    lg = _git(where, "log", "--oneline", "--no-decorate", "--no-show-signature", f"{base}..{ref}")
    log = lg[1].decode("utf-8", "replace").strip() if lg is not None and lg[0] == 0 else ""
    return n, log, how


def _patch_ids(where, *rng: str):
    """`{commit: patch-id}` over `rng`, merges skipped, or None. The pass reads every diff in
    the range, so it gets a longer timeout than a single lookup."""
    out = _git(where, "log", "-p", "--no-merges", "--no-color", "--no-ext-diff", "--no-textconv",
               "--no-show-signature", "--format=commit %H", *rng, timeout=60)
    if out is None or out[0] != 0:
        return None
    r = _git(where, "patch-id", "--stable", stdin=out[1], timeout=60)
    if r is None or r[0] != 0:
        return None
    ids = {}
    for line in r[1].decode("ascii", "replace").splitlines():
        pid, _, commit = line.partition(" ")
        ids[commit.strip()] = pid
    return ids


_MERGED_PR_HEADS = "refs/sysop/merged-pr-heads/"


def _merge_target(branch: str, where):
    """`(refs that are the merge target, None)`, or `(None, why)` when it cannot be named.

    The default branch, from `default_branch.sh` (the shipped resolver beside this file, so the
    one every lifecycle script uses), and its copy on the one remote that resolver reads:
    `origin`, or the only remote when there is exactly one. Another remote's `main` (a deploy
    target, a teammate's fork) holds work that never reached the merge target. A default that
    is the measured branch itself names no target at all."""
    try:
        d = subprocess.run(["bash", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 "default_branch.sh"), str(where)],
                           capture_output=True, text=True, timeout=10,
                           env={k: v for k, v in os.environ.items() if k not in _STRIP})
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"default_branch.sh could not run ({type(e).__name__})"
    name = d.stdout.strip() if d.returncode == 0 else ""
    if not name:
        said = next((ln.strip() for ln in d.stderr.splitlines() if ln.strip()), "no answer")
        return None, f"default_branch.sh named no default branch ({said})"
    if name == branch:
        return None, f"the default branch resolves to {branch!r} itself"
    refs = [f"refs/heads/{name}"]
    remotes = _git(where, "remote")
    names = remotes[1].decode("utf-8", "replace").split() if remotes and not remotes[0] else []
    origin_head = _git(where, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    remote = ("origin" if "origin" in names or (origin_head is not None and origin_head[0] == 0)
              else names[0] if len(names) == 1 else "")
    if remote:
        refs.append(f"refs/remotes/{remote}/{name}")
    return refs, None


def _shared(commit: str, branch: str, where):
    """None when the merge target holds `commit`, else why it is not shown to: a `pr` close's
    recorded head under `refs/sysop/merged-pr-heads/` (which holds an integration branch that
    was squash-merged and deleted), or one of `_merge_target`'s refs. An allowlist, because a
    denylist of the branch's own refs misses every other copy of it: a backup branch, a tag, a
    prefetch ref, a push under another name, a remote whose name holds a `/`."""
    r = _git(where, "for-each-ref", "--contains", commit, "--format=%(refname)")
    if r is None or r[0] != 0:
        return "its refs could not be listed"
    holders = r[1].decode("utf-8", "replace").split()
    if any(ref.startswith(_MERGED_PR_HEADS) for ref in holders):
        return None
    allowed, why = _merge_target(branch, where)
    if allowed is None:
        return f"the merge target could not be named: {why}"
    if any(ref in allowed for ref in holders):
        return None
    return "are not the merge target's"


def _paired(tip: str, ref: str, branch: str, where):
    """The rewritten branch's count, or a string saying why the pairing is not proven.

    The doc's commits (`ref..tip`, oldest first) must appear on the branch's first-parent
    chain (`tip..ref`) as one contiguous run of the same patches in the same order, exactly
    once: that is what a rebase writes. The drift is every commit after the run. Matching
    patches one at a time would let a commit after the doc that re-applies one of the doc's
    own patches (a change reverted, then made again) stand in for its copy. Every commit
    below the run must be the merge target's (`_shared`): otherwise work inserted under the
    doc's commits, as `rebase -i` or `pull --rebase` can leave it, would read as history."""
    unread = "its commits or their patches could not be read"
    merges = _git(where, "rev-list", "--merges", f"{ref}..{tip}")
    mine = _git(where, "rev-list", "--topo-order", "--reverse", f"{ref}..{tip}")
    chain = _git(where, "rev-list", "--topo-order", "--reverse", "--first-parent", f"{tip}..{ref}")
    orig = _patch_ids(where, f"{ref}..{tip}")
    cand = _patch_ids(where, "--first-parent", f"{tip}..{ref}")
    if (merges is None or mine is None or chain is None or orig is None or cand is None
            or merges[0] or mine[0] or chain[0]):
        return unread
    if merges[1].strip():
        return "the doc's side holds a merge commit, which has no patch to pair"
    run = [orig.get(c) for c in mine[1].decode("ascii", "replace").split()]
    if not run or None in run:
        return "a commit on the doc's side has no patch (an empty commit)"
    commits = chain[1].decode("ascii", "replace").split()
    seq = [cand.get(c) for c in commits]
    k = len(run)
    starts = [i for i in range(len(seq) - k + 1) if seq[i:i + k] == run]
    if len(starts) != 1:
        return ("the branch holds no copy of the doc's commits as one run, in order"
                if not starts else "the branch holds the doc's commits more than once")
    if starts[0]:
        base = commits[starts[0] - 1]
        why = _shared(base, branch, where)
        if why == "are not the merge target's":
            return (f"the commits under its copied run, up to {base[:12]}, are not the merge "
                    f"target's, so they may be work the doc does not describe")
        if why:
            return (f"whether the commits under its copied run, up to {base[:12]}, are shared "
                    f"history is unknown: {why}")
    else:   # the run starts at the fork point
        mb = _git(where, "merge-base", tip, ref)
        if mb is None or mb[0] != 0 or not mb[1].strip():
            return unread
        base = mb[1].decode("ascii", "replace").strip()
    top = commits[starts[0] + k - 1]
    counted = _counted(top, ref, where, f"; rewritten since, counted from its copy {top[:12]}")
    if counted is None:
        return unread
    return counted + (top, base)


def _measure(tip: str, branch: str, where):
    """`measure`, plus where the doc's work ends on the branch (`top`: the tip itself, the end
    of its paired run, or None after a fallback) and, for a paired run, the commit under it
    (`base`; None otherwise)."""
    ref = f"refs/heads/{branch}"
    anc = _git(where, "merge-base", "--is-ancestor", tip, ref)
    if anc is None or anc[0] not in (0, 1):
        return None
    how = ""
    if anc[0] == 1:
        paired = _paired(tip, ref, branch, where)
        if not isinstance(paired, str):
            return paired
        how = f"; rewritten since, and {paired}"
    counted = _counted(tip, ref, where, how)
    return None if counted is None else counted + (tip if anc[0] == 0 else None, None)


def measure(tip: str, branch: str, where):
    """`(count, log, how)` for the commits on `branch` the doc stamped at `tip` does not
    describe — 0 means current — or None when `tip` or the branch does not resolve in
    `where`. `tip` must already be validated as an object name: it reaches git as a revision."""
    m = _measure(tip, branch, where)
    return None if m is None else m[:3]


def family(name: str) -> tuple[str, int]:
    """`feat-x--2.md` → `('feat-x', 2)`; `feat-x.md` → `('feat-x', 0)`."""
    m = _FAMILY.match(name)
    return (m.group(1), int(m.group(2))) if m else (name[:-3] if name.endswith(".md") else name, 0)


def covering(name: str, tip: str, frontmatter, current, branch: str, where):
    """The `(name, tip)` in `current` that covers the stale doc `name`, stamped at `tip`, or None.

    `current` lists the docs for `branch` measured current. Only a doc a close is holding
    (`held_since:` in `frontmatter`) is covered, and only by a later doc in its own
    `<stem>--<n>.md` family: the pair `pending_doc_hold.py guard` writes on purpose. Any other
    stale doc's summary would route as written, which is what the staleness gate refuses.

    The newer doc covers when every commit after the older doc's work is one it describes:
    the branch is an ancestor of its tip, or, when a close has rebased the branch since, it
    is current by its paired run and each of those commits is in that run or in the newer
    doc's own history. Both are measured in `where`, the stale doc's repository: a `--clone`
    workspace's tip need not exist in the main checkout, and a tip that does not resolve
    covers nothing."""
    if not (isinstance(frontmatter, dict) and frontmatter.get("held_since")):
        return None
    fam, n = family(name)
    mine = None
    for cname, ctip in current:
        cfam, cn = family(cname)
        if cfam != fam or cn <= n:
            continue
        r = _git(where, "rev-list", "--count", f"{ctip}..refs/heads/{branch}")
        if r is not None and r[0] == 0 and r[1].strip() == b"0":
            return cname, ctip
        theirs = _measure(ctip, branch, where)
        if theirs is None or theirs[0] != 0 or theirs[4] is None:
            continue
        mine = mine or _measure(tip, branch, where)
        if mine is None or mine[3] is None:
            continue
        # The older doc's drift is `mine[3]..ref`. What lies outside the newer doc's run
        # (`theirs[4]..ref`) is `mine[3]..theirs[4]`; none of it may be missing from its history.
        outside = _git(where, "rev-list", "--count", f"{mine[3]}..{theirs[4]}", f"^{ctip}")
        if outside is not None and outside[0] == 0 and outside[1].strip() == b"0":
            return cname, ctip
    return None
