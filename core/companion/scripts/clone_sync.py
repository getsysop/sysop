#!/usr/bin/env python3
"""clone_sync.py — `/review-close` Step 1-pre: bring `--clone` claims' commits across.

    python3 sysop/scripts/clone_sync.py <default-branch> {apply|dry-run}

Run from the main checkout's top level, before anything else in the close. For each
lock that records a `--clone` workspace, moves this repository's branch fast-forward
only to the clone's tip (or `origin`'s when the clone or its branch is gone) and prints
one line per branch plus a `CLONE SYNC:` summary.

The skill text is the contract: `/review-close` Step 1-pre says what each line and each
exit code means and what the close does with it. This file was that step's heredoc
until Phase 386 (`Q-409` P3), moved verbatim.
"""
import os, subprocess, sys
from pathlib import Path
default, mode = sys.argv[1], sys.argv[2]
if not default.strip() or default.startswith("<") or mode not in ("apply", "dry-run"):
    print("ERROR: substitute the default branch, and apply or dry-run"); sys.exit(3)
env = dict((k, v) for k, v in os.environ.items()
       if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"))
def git(*a, where=".", timeout=None):
    try:
        r = subprocess.run(["git", "-C", str(where), *a], capture_output=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    return r.returncode, os.fsdecode(r.stdout).strip(), os.fsdecode(r.stderr).strip()
def last(err, rc):
    return (err.splitlines() or [f"exit {rc}"])[-1]
def common(where):
    rc, out, _ = git("rev-parse", "--git-common-dir", where=where)
    return os.path.realpath(os.path.join(str(where), out)) if rc == 0 and out else None
def is_top(where):
    rc, out, _ = git("rev-parse", "--show-toplevel", where=where)
    try:
        return rc == 0 and bool(out) and os.path.samefile(out, where)
    except OSError:
        return False
def identity(where):
    r = subprocess.run(["bash", "-c", 'source "$GIT_LIB" && origin_identity "$CLONE_DIR"'],
                       capture_output=True, env=dict(env, GIT_LIB=LIB, CLONE_DIR=str(where)))
    return os.fsdecode(r.stdout).strip() if r.returncode == 0 else None
def rev(ref, where="."):
    rc, out, _ = git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", where=where)
    return out if rc == 0 else ""
def holds(where, older, newer):
    return git("merge-base", "--is-ancestor", older, newer, where=where)[0] == 0
rc, gd, err = git("rev-parse", "--absolute-git-dir")
ours_common = common(".")
LIB = os.path.join("sysop", "scripts", "_git_lib.sh")
if rc or os.path.realpath(gd) != ours_common or not Path(LIB).is_file():
    print("ERROR: run this from the main checkout's top level"); sys.exit(3)
repo = Path.cwd().resolve()
our_id = identity(".")
if not our_id:
    print("CLONE SYNC: no origin remote, so no --clone workspace can exist"); sys.exit(0)
PRIVATE = "refs/sysop/clone-sync/"
for ref in git("for-each-ref", "--format=%(refname)", PRIVATE)[1].splitlines():
    git("update-ref", "-d", ref)        # left by an interrupted run
checked_out, cur = {}, None
for line in git("worktree", "list", "--porcelain")[1].splitlines():
    if line.startswith("worktree "):
        cur = line[len("worktree "):]
    elif line.startswith("branch refs/heads/"):
        checked_out[line[len("branch refs/heads/"):]] = cur

claimed, gone = {}, {}
locks = repo / "sysop" / "runtime" / "locks"
for lk in sorted(locks.glob("*.lock")) if locks.is_dir() else []:
    if not lk.is_file():
        continue
    try:
        text = lk.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"ERROR: cannot read {lk}: {exc}"); sys.exit(4)
    f = {}
    for line in text.splitlines():
        k, sep, v = line.partition(":")
        if sep and k not in f:
            f[k] = v.strip()
    b, w = f.get("branch") or "", f.get("workspace") or ""
    if not b or not w or b == default:
        continue
    ws = (Path(w) if Path(w).is_absolute() else repo / w).resolve()
    if ws.is_dir() and is_top(ws):
        if common(ws) != ours_common:
            claimed.setdefault(b, set()).add(ws)
    elif f.get("mode", "clone") == "clone":
        gone.setdefault(b, ws)

counts = {}
def say(word, b, where, text):
    counts[word] = counts.get(word, 0) + 1
    print(f"{word:<8} {b}  ({where})  — {text}", flush=True)

def holders(ws, b, theirs):
    """The clone's worktrees to read: on <b>, rebasing or bisecting <b>, or detached at or past its tip."""
    out, cur = [], None
    for line in git("worktree", "list", "--porcelain", where=ws)[1].splitlines() + [""]:
        if line.startswith("worktree "):
            cur = dict(path=line[len("worktree "):])
        elif cur is not None and line.startswith("branch "):
            cur["branch"] = line[len("branch "):]
        elif cur is not None and line.startswith("HEAD "):
            cur["head"] = line[len("HEAD "):]
        elif not line and cur is not None:
            w, head = cur["path"], cur.get("head", "")
            if not os.path.isdir(w):
                pass
            elif cur.get("branch") == f"refs/heads/{b}":
                out.append((w, None))
            elif "branch" not in cur:
                names = []
                for n in ("rebase-merge/head-name", "rebase-apply/head-name", "BISECT_START"):
                    try:
                        names.append(Path(w, git("rev-parse", "--git-path", n, where=w)[1]).read_text(
                            encoding="utf-8", errors="replace").strip())
                    except OSError:
                        pass
                if f"refs/heads/{b}" in names or b in names:
                    out.append((w, None))
                elif head and holds(w, theirs, head):
                    out.append((w, head if head != theirs else None))
            cur = None
    return out

def noise(where, entry):
    """An untracked symlink whose target this repository ignores."""
    p = os.path.join(where, entry)
    if not os.path.islink(p):
        return False
    target = os.path.normpath(os.path.join(os.path.dirname(p), os.readlink(p)))
    return git("check-ignore", "-q", target)[0] == 0

def unsettled(ws, b, theirs):
    for w, detached in holders(ws, b, theirs):
        busy = [n for n in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD",
                            "REVERT_HEAD", "BISECT_LOG", "sequencer")
                if os.path.exists(os.path.join(w, git("rev-parse", "--git-path", n, where=w)[1]))]
        if busy:
            return "DIRTY", f"an operation is in progress in {w} ({busy[0]})"
        rc, st, err = git("status", "--porcelain", where=w)
        if rc:
            return "REFUSED", f"git status failed in {w}: {err}"
        st = [ln for ln in st.splitlines() if not (ln.startswith("?? ") and noise(w, ln[3:]))]
        if st:
            return "DIRTY", f"{len(st)} pending changes in {w}"
        if detached:
            return "DIRTY", f"a detached HEAD in {w} continues {b} past {theirs[:12]}"
    return None

def land(b, where, theirs, src):
    """Fast-forward refs/heads/<b> to <theirs>, whose objects are already here."""
    ours = rev(f"refs/heads/{b}")
    if theirs == ours:
        say("CURRENT", b, where, f"already at {ours[:12]}"); return
    if ours and not holds(".", ours, theirs):
        if src == "origin" and holds(".", theirs, ours):
            say("CURRENT", b, where, f"this repository's {ours[:12]} already holds origin's {theirs[:12]}")
        else:
            say("REFUSED", b, where, f"not a fast-forward: this repository's {ours[:12]} has commits "
                                     f"{theirs[:12]} lacks")
        return
    n = git("rev-list", "--count", f"{ours}..{theirs}" if ours else theirs)[1]
    if b in checked_out:
        say("REFUSED", b, where, f"{b} is checked out at {checked_out[b]}"); return
    rc, _, err = git("update-ref", "-m", "review-close Step 1-pre", f"refs/heads/{b}", theirs,
                     ours or "0" * len(theirs))
    if rc:
        say("REFUSED", b, where, f"{b} moved while it was read: {last(err, rc)}"); return
    say("SYNCED", b, where, f"{ours[:12] or 'absent'} -> {theirs[:12]}, {n} commits")

def from_origin(b, where, why):
    rc, out, err = git("ls-remote", "--heads", "origin", f"refs/heads/{b}", timeout=120)
    if rc:
        say("REFUSED", b, where, f"{why}, and origin could not be read: {last(err, rc)}"); return
    # A pattern matches as `*/refs/heads/<b>`, so keep only the line naming the branch itself.
    out = next((ln.split()[0] for ln in out.splitlines()
                if ln.split()[1:2] == [f"refs/heads/{b}"]), "")
    if not out:
        say("GONE" if why.startswith("the clone is") else "NO BRANCH", b, where,
            f"{why}, and origin has no {b} either"); return
    tip, ours = out, rev(f"refs/heads/{b}")
    where = f"origin, because {why}"
    if mode == "dry-run":
        if tip == ours or (ours and git("cat-file", "-e", tip)[0] == 0 and holds(".", tip, ours)):
            say("CURRENT", b, where, f"this repository's {ours[:12]} holds origin's {tip[:12]}")
        else:
            say("WOULD SYNC", b, where, f"origin's {b} is at {tip[:12]}; a dry run does not fetch, "
                                        f"so whether it fast-forwards {ours[:12] or 'absent'} is unchecked")
        return
    rc, _, err = git("fetch", "--no-tags", "--no-recurse-submodules", "--quiet", "origin",
                     f"+refs/heads/{b}:{PRIVATE}{b}", timeout=600)
    if rc:
        say("REFUSED", b, where, f"origin could not be fetched: {last(err, rc)}")
    else:
        land(b, where, rev(f"{PRIVATE}{b}"), "origin")
    git("update-ref", "-d", f"{PRIVATE}{b}")

for b in sorted(set(claimed) | set(gone)):
    if len(claimed.get(b, ())) > 1:
        say("REFUSED", b, ", ".join(sorted(map(str, claimed[b]))),
            "two locks record clones for this branch"); continue
    if b not in claimed:
        from_origin(b, gone[b], "the clone is missing or is not a repository"); continue
    ws = next(iter(claimed[b]))
    if identity(ws) != our_id:
        say("REFUSED", b, ws, "its origin is not this repository's origin"); continue
    theirs = rev(f"refs/heads/{b}", ws)
    if not theirs:
        from_origin(b, ws, f"the clone has no {b}"); continue
    why = unsettled(ws, b, theirs)
    if why:
        say(why[0], b, ws, why[1]); continue
    if mode == "dry-run":
        ours = rev(f"refs/heads/{b}")
        if theirs == ours:
            say("CURRENT", b, ws, f"already at {ours[:12]}")
        elif ours and not holds(ws, ours, theirs):
            say("REFUSED", b, ws, f"not a fast-forward: this repository's {ours[:12]} has commits "
                                  f"{theirs[:12]} lacks")
        else:
            n = git("rev-list", "--count", f"{ours}..{theirs}" if ours else theirs, where=ws)[1]
            say("WOULD SYNC", b, ws, f"{ours[:12] or 'absent'} -> {theirs[:12]}, {n} commits")
        continue
    rc, _, err = git("fetch", "--no-tags", "--no-recurse-submodules", "--quiet", str(ws),
                     f"+{theirs}:{PRIVATE}{b}", timeout=600)
    if rc:
        say("REFUSED", b, ws, f"could not read the clone: {last(err, rc)}")
    else:
        land(b, ws, rev(f"{PRIVATE}{b}"), str(ws))
    git("update-ref", "-d", f"{PRIVATE}{b}")

summary = ", ".join(f"{k.lower()} {v}" for k, v in sorted(counts.items()))
print(f"CLONE SYNC: {sum(counts.values())} line(s)" + (f" — {summary}" if summary else ""))
