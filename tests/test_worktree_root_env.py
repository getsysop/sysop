"""Phase 262 (GDP brief § E): `WORKTREE_ROOT` relocates the workspace parent.

`claim_task.sh` built the workspace at `${REPO_ROOT}/../<prefix>-<task>`, with
`WORKTREE_PREFIX` naming only the leaf. A sandboxed harness (Codex) is given a
writable-path allow-list, and that construction forced the list to include the
repo's whole parent directory — every sibling checkout with it. `WORKTREE_ROOT`
names the parent instead.

**The brief said "every reader of the worktree path must honour it" and was
wrong about its own extent** — the same class as `Q-397` (one named site, six
real) but in the other direction. **All four of its named readers already work at
any location.** (An earlier version of this docstring said "three of the four",
reaching three by not opening the fourth name — `/review-close` Step 1a, which is
handed `git worktree list --porcelain` — and substituting `--release`, which the
brief never named.) The two carriers:

  * `cleanup_worktrees.sh` and `/sitrep` arm (i) call `git worktree list
    --porcelain`, which reports a linked worktree's absolute path wherever it
    sits. Unconditional.
  * `/sitrep` arm (ii), `scope_overlap.py` and `claim_task.sh --release` read
    the lock's `workspace:`, which records the absolute path the variable
    produced — but only when a lock exists, i.e. under `--lock`. Not a
    regression this adds: without `--lock` there is no lock to read whatever
    the path.

What is left is the sibling-glob fallbacks (`/sitrep` arm (iii), review-close's
`_prefix` glob). They cannot see a relocated root, exactly as they already
cannot see a `WORKTREE_PREFIX` exported by another session. Their residue is
narrower than it looks and is documented at each site rather than papered over:
a linked worktree is found via the porcelain listing regardless of location, so
the unreachable combination is relocated + `--clone` + no `--lock`.

These tests drive the real script. The two refusals are the point: a root that
does not exist and a root inside the repository are both fail-closed, because
the first is usually a typo and the second puts untracked content in the main
checkout that the cleanup paths would then sweep.
"""
import os
import subprocess
from pathlib import Path

import pytest

from test_claim_task_sh import SCRIPT, _git, _path_env, _py3_bin, _repo, _run

# Phase 264 moved the four `WORKTREE_ROOT` guards into the shared library so
# `batch_work.sh` could reuse them (`Q-407`). The source-reading guards below
# follow them; the behavioural ones still drive `claim_task.sh` end to end,
# which is what proves the caller is still wired to the validator.
LIB = SCRIPT.parent / "_git_lib.sh"

INDEX = "tasks:\n  T-0001:\n    status: open\n  T-0002:\n    status: open\n"
BODY = "---\nid: {tid}\nstatus: open\n---\nbody\n"


def _seeded(tmp_path, name="repo"):
    """A repo with a schema-valid index, so the claim reaches the worktree step."""
    root = _repo(tmp_path / name)
    (root / "tasks" / "open").mkdir(parents=True)
    (root / "tasks" / "index.yml").write_text(INDEX)
    for tid in ("T-0001", "T-0002"):
        (root / "tasks" / "open" / f"{tid}.md").write_text(BODY.format(tid=tid))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "tasks")
    return root


def _claimed_worktrees(root):
    """Absolute paths git itself reports, minus the main checkout."""
    out = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=str(root),
                         capture_output=True, text=True, check=True).stdout
    paths = [Path(l.split(" ", 1)[1]).resolve()
             for l in out.splitlines() if l.startswith("worktree ")]
    return [p for p in paths if p != root.resolve()]


def test_unset_worktree_root_keeps_the_historical_sibling_path(tmp_path):
    """The default is byte-identical to every prior release: `../<repo>-<task>`."""
    root = _seeded(tmp_path)
    r = _run(root, "T-0001", "feat/t1", env=_path_env(_py3_bin(tmp_path)))
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "repo-t-0001").is_dir(), r.stdout
    assert _claimed_worktrees(root) == [(tmp_path / "repo-t-0001").resolve()]


def test_worktree_root_relocates_the_parent_and_git_still_finds_it(tmp_path):
    """The whole point, and the reason most readers need no change.

    Asserting `git worktree list` sees it is not decoration — it is the carrier
    that makes `cleanup_worktrees.sh` and `/sitrep` arm (i) location-agnostic
    for free. If this assertion ever fails, those two silently stop finding
    relocated workspaces and the docstring above becomes false.
    """
    root = _seeded(tmp_path)
    elsewhere = tmp_path / "declared-writable"
    elsewhere.mkdir()
    r = _run(root, "T-0001", "feat/t1",
             env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(elsewhere)})
    assert r.returncode == 0, r.stderr
    assert (elsewhere / "repo-t-0001").is_dir(), r.stdout
    assert not (tmp_path / "repo-t-0001").exists(), "leaked a sibling anyway"
    assert _claimed_worktrees(root) == [(elsewhere / "repo-t-0001").resolve()]


def test_worktree_root_composes_with_worktree_prefix(tmp_path):
    """Root names the parent, prefix names the leaf — they are orthogonal.

    Written because a plausible implementation makes one override the other.
    """
    root = _seeded(tmp_path)
    elsewhere = tmp_path / "w"
    elsewhere.mkdir()
    r = _run(root, "T-0001", "feat/t1",
             env={**_path_env(_py3_bin(tmp_path)),
                  "WORKTREE_ROOT": str(elsewhere), "WORKTREE_PREFIX": "custom"})
    assert r.returncode == 0, r.stderr
    assert (elsewhere / "custom-t-0001").is_dir(), r.stdout


def test_the_lock_records_the_relocated_absolute_path(tmp_path):
    """`--lock` is what makes the lock-reading half location-agnostic.

    `/sitrep` arm (ii), `scope_overlap.py` and `--release` all read this field.
    A lock recording the *computed conventional* path rather than the one
    actually used would send all three to a directory that does not exist.
    """
    root = _seeded(tmp_path)
    elsewhere = tmp_path / "w"
    elsewhere.mkdir()
    r = _run(root, "--lock", "T-0001", "feat/t1",
             env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(elsewhere)})
    assert r.returncode == 0, r.stderr
    lock = root / "sysop" / "runtime" / "locks" / "T-0001.lock"
    assert lock.is_file(), r.stdout
    recorded = [l.split(": ", 1)[1] for l in lock.read_text().splitlines()
                if l.startswith("workspace: ")]
    assert recorded, lock.read_text()
    assert Path(recorded[0]).resolve() == (elsewhere / "repo-t-0001").resolve()


def test_a_nonexistent_worktree_root_is_refused_and_creates_nothing(tmp_path):
    """Fail closed. The script will not mkdir a path that is probably a typo —
    and having refused, it must not have created the branch or worktree either."""
    root = _seeded(tmp_path)
    missing = tmp_path / "typo"
    r = _run(root, "T-0001", "feat/t1",
             env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(missing)})
    assert r.returncode == 1
    assert "WORKTREE_ROOT" in r.stderr and "not an existing directory" in r.stderr
    assert not missing.exists(), "created the directory it refused"
    assert _claimed_worktrees(root) == []


@pytest.mark.parametrize("sub", ["inside", "nested/deep", "."])
def test_a_worktree_root_inside_the_repo_is_refused(tmp_path, sub):
    """A worktree inside the checkout is untracked content in the main tree: not
    covered by the `sysop/runtime/` gitignore set, and swept by the very cleanup
    paths meant to remove it. `.` is included because the repo root itself is
    the sharpest case and a prefix-only check that forgot the equality arm would
    pass the other two."""
    root = _seeded(tmp_path)
    target = root if sub == "." else root / sub
    target.mkdir(parents=True, exist_ok=True)
    r = _run(root, "T-0001", "feat/t1",
             env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(target)})
    assert r.returncode == 1
    assert "resolves inside the repository" in r.stderr, r.stderr
    assert _claimed_worktrees(root) == []


def test_a_sibling_directory_sharing_the_repo_name_prefix_is_not_refused(tmp_path):
    """The containment check must compare path SEGMENTS, not string prefixes.

    `<tmp>/repo-worktrees` starts with `<tmp>/repo` as a string but is not
    inside it. A `case $wr in $rr*)` without the `/` in the second arm rejects
    this legal root — the exact bug the `"$_rr_abs"|"$_rr_abs"/*` pattern
    avoids, and nothing else in this file would catch it.
    """
    root = _seeded(tmp_path)
    sibling = tmp_path / "repo-worktrees"
    sibling.mkdir()
    r = _run(root, "T-0001", "feat/t1",
             env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(sibling)})
    assert r.returncode == 0, r.stderr
    assert (sibling / "repo-t-0001").is_dir(), r.stdout


def test_a_symlinked_root_pointing_into_the_repo_is_still_refused(tmp_path):
    """`pwd -P` resolves symlinks, so the containment check cannot be walked
    around with one. Without `-P` this is the trivial bypass."""
    root = _seeded(tmp_path)
    (root / "inside").mkdir()
    link = tmp_path / "looks-outside"
    link.symlink_to(root / "inside")
    r = _run(root, "T-0001", "feat/t1",
             env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(link)})
    assert r.returncode == 1
    assert "resolves inside the repository" in r.stderr, r.stderr


# ── Phase 262's review round, lens 1 (execution) ─────────────────────────────
# Every test below is a defect the round found by RUNNING the script in a state
# the author's tests did not construct. The author's containment test ran only
# from the main checkout; three of these four could not be seen from there.


def test_the_containment_guard_holds_from_inside_a_linked_worktree(tmp_path):
    """`Q-020`/`Q-307`'s class (Phase 234), recurring in a guard written after it.

    The first cut compared `WORKTREE_ROOT` against `git rev-parse --show-toplevel`,
    which answers "which worktree am I standing in" — so from a linked worktree it
    compared against the wrong tree and ACCEPTED a root inside the main checkout,
    producing verbatim the untracked state its own message names. Claiming from a
    worktree is a prescribed invocation, so this was reachable by design.
    """
    root = _seeded(tmp_path)
    elsewhere = tmp_path / "w"
    elsewhere.mkdir()
    r = _run(root, "T-0001", "feat/t1",
             env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(elsewhere)})
    assert r.returncode == 0, r.stderr
    linked = elsewhere / "repo-t-0001"
    inside = root / "x"
    inside.mkdir()

    # The control: refused from the main checkout. If this ever passes, the test
    # below proves nothing, because both would be refusing for the same reason.
    main_side = _run(root, "T-0002", "feat/t2",
                     env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(inside)})
    assert main_side.returncode == 1
    # The finding: the same value, from the linked worktree.
    from_wt = _run(linked, "T-0002", "feat/t2",
                   env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(inside)})
    assert from_wt.returncode == 1, from_wt.stdout
    assert "resolves inside the repository" in from_wt.stderr, from_wt.stderr
    assert not any(inside.iterdir()), "created a workspace inside the main checkout"


def test_an_unwritable_root_is_refused_before_the_branch_is_created(tmp_path):
    """Left to `git worktree add`, this failed at rc=128 with a bare `fatal:`,
    an ORPHAN branch and no guidance — and it is the likeliest real failure for
    the variable's whole purpose, a sandbox declaring a path it cannot write."""
    root = _seeded(tmp_path)
    ro = tmp_path / "readonly"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        r = _run(root, "T-0001", "feat/t1",
                 env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(ro)})
        assert r.returncode == 1, f"rc={r.returncode} {r.stdout} {r.stderr}"
        assert "not writable" in r.stderr, r.stderr
        branches = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"], cwd=str(root),
            capture_output=True, text=True, check=True).stdout.split()
        assert "feat/t1" not in branches, f"orphan branch left behind: {branches}"
        assert _claimed_worktrees(root) == []
    finally:
        ro.chmod(0o700)


@pytest.mark.parametrize("value", ["nonexistent", "inside"])
def test_branch_mode_ignores_a_worktree_root_it_never_uses(tmp_path, value):
    """The guard ran before mode dispatch, so a stale root in a sandbox's
    persistent environment refused `--branch` — a mode that never reads
    `WORKTREE_DIR`. Pre-262 `--branch` was insensitive to these variables and
    must stay that way."""
    root = _seeded(tmp_path)
    target = str(tmp_path / "gone") if value == "nonexistent" else str(root)
    r = _run(root, "--branch", "T-0001", "feat/t1",
             env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": target})
    assert r.returncode == 0, r.stderr
    assert "WORKTREE_ROOT" not in r.stderr, r.stderr
    assert _claimed_worktrees(root) == [], "branch mode built a worktree"


def test_a_newline_in_the_root_is_refused(tmp_path):
    """The lock's `workspace:` is parsed line-anchored by every reader
    (`--release`'s awk, /review-close's `partition(':')`), so a two-line value
    is silently truncated and the release then reports success over an orphan."""
    root = _seeded(tmp_path)
    weird = tmp_path / "we\nird"
    weird.mkdir()
    r = _run(root, "T-0001", "feat/t1",
             env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(weird)})
    assert r.returncode == 1, f"rc={r.returncode} {r.stdout}"
    assert "newline" in r.stderr, r.stderr
    assert _claimed_worktrees(root) == []


# ── Phase 262's review round, lens 2 (guard strength) ────────────────────────
# 13 of 24 independent mutations survived the first cut of this file (54%), nine
# of them surviving the entire suite. The author's own battery reported 14/14.
# Each test below closes a NAMED survivor; the over-strictness ones matter as
# much as the permissive ones, because the legal shapes they protect are the
# shapes this feature exists to serve.


def test_clone_mode_honours_the_relocated_root(tmp_path):
    """S1. Every earlier test drove the DEFAULT mode, so `--clone` could ignore
    `WORKTREE_ROOT` entirely and stay green — while three shipped files build
    their residue argument on the premise that clone honours it (*"relocated +
    `--clone` + no `--lock` is the one combination this arm cannot resolve"*).
    That premise was load-bearing prose pinned by nothing."""
    root = _seeded(tmp_path)
    # `--clone` clones from `origin`, so the fixture needs one. A bare repo is
    # the smallest thing that satisfies it without reaching the network.
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True,
                   capture_output=True)
    _git(root, "remote", "add", "origin", str(bare))
    _git(root, "push", "-q", "origin", "main")
    elsewhere = tmp_path / "w"
    elsewhere.mkdir()
    r = _run(root, "--clone", "T-0001", "feat/t1",
             env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(elsewhere)})
    assert r.returncode == 0, r.stderr
    assert (elsewhere / "repo-t-0001").is_dir(), r.stdout
    assert not (tmp_path / "repo-t-0001").exists(), "clone leaked to the sibling path"


def test_an_empty_worktree_root_means_the_default_not_an_error(tmp_path):
    """S5. `${WORKTREE_ROOT:-}` vs `${WORKTREE_ROOT+set}` is the whole contract
    and was asserted nowhere. `FOO=${BAR}` with BAR unset is the ordinary
    CI/wrapper shape, so treating set-but-empty as "declared" hard-fails every
    claim in an environment that merely MENTIONS the variable."""
    root = _seeded(tmp_path)
    r = _run(root, "T-0001", "feat/t1",
             env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": ""})
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "repo-t-0001").is_dir(), r.stdout


def test_the_lock_records_the_CANONICAL_path(tmp_path):
    """S6. The first version of this assertion called `.resolve()` on BOTH sides
    of the comparison, normalising away the exact property `pwd -P` exists for.
    It caught a wrong path and could not catch a non-canonical one — so discarding
    the canonicalisation left the lock and `git worktree list` disagreeing about
    the same workspace, which `/sitrep` arm (ii), `scope_overlap.py` and
    `--release` all read."""
    root = _seeded(tmp_path)
    real = tmp_path / "realwt"
    real.mkdir()
    link = tmp_path / "linkwt"
    link.symlink_to(real)
    r = _run(root, "--lock", "T-0001", "feat/t1",
             env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(link)})
    assert r.returncode == 0, r.stderr
    lock = root / "sysop" / "runtime" / "locks" / "T-0001.lock"
    recorded = [l.split(": ", 1)[1] for l in lock.read_text().splitlines()
                if l.startswith("workspace: ")][0]
    # NO .resolve() on the recorded side — that is the point.
    assert recorded == str((real / "repo-t-0001").resolve()), (
        f"lock recorded {recorded!r}, which is not the canonical path git uses"
    )
    listed = _claimed_worktrees(root)
    assert listed == [Path(recorded)], (listed, recorded)


def test_the_repos_own_parent_is_a_legal_root(tmp_path):
    """S7 (over-strictness). `WORKTREE_ROOT=$(dirname <repo>)` is the explicit
    spelling of the shipped default and the first thing a consumer writes when
    adding the variable to a wrapper. Both happy-path tests used a CHILD of the
    parent, so a guard refusing the parent itself passed them all."""
    root = _seeded(tmp_path)
    r = _run(root, "T-0001", "feat/t1",
             env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "repo-t-0001").is_dir(), r.stdout


def test_a_legal_symlinked_root_is_accepted(tmp_path):
    """S8 (over-strictness). The only symlink test aimed at a symlink INTO the
    repo, so the legal direction had no case at all — and a declared writable
    path is very often a symlink, which is the shape of the sandbox this feature
    exists for."""
    root = _seeded(tmp_path)
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "declared"
    link.symlink_to(real)
    r = _run(root, "T-0001", "feat/t1",
             env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(link)})
    assert r.returncode == 0, r.stderr
    assert (real / "repo-t-0001").is_dir(), r.stdout


def test_a_regular_file_as_root_gets_the_designed_refusal(tmp_path):
    """S9. Still fail-closed either way, so the loss is diagnostic quality — but
    the guard's contract says "an existing DIRECTORY" and was asserted only
    against a path that exists as nothing. Widening `-d` to `-e` handed the
    operator bash's `cd: Not a directory` instead of the two-line message."""
    root = _seeded(tmp_path)
    afile = tmp_path / "afile"
    afile.write_text("x")
    r = _run(root, "T-0001", "feat/t1",
             env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(afile)})
    assert r.returncode == 1
    assert "not an existing directory" in r.stderr, r.stderr


def test_the_containment_case_has_no_exemption_arm():
    """S3. Phase 205's class — "the escape hatch that nullified the check". The
    parametrize covers three SHAPES of one rule and cannot see an added arm that
    exempts a path prefix. Read the guard's own `case` block: it must contain
    exactly the documented pattern and nothing else.

    Re-pointed at Phase 264, not deleted: the block moved to `_git_lib.sh` with
    the extraction, and `_wr_abs`/`_rr_abs` lost their underscores as locals of a
    function. Losing the guard to a rename would have retired the anti-exemption
    property silently, which is the class it exists for."""
    block = LIB.read_text()
    block = block[block.index('case "$wr_abs" in'):]
    block = block[:block.index("esac")]
    arms = [l.strip() for l in block.splitlines() if l.strip().endswith(")")]
    assert arms == ['"$rr_abs"|"$rr_abs"/*)'], (
        f"the containment case has arms beyond the documented one: {arms}. An "
        f"added arm is an exemption — the shape Phase 205 shipped and had to revert."
    )


def test_the_any_work_tree_arm_has_no_exemption_condition():
    """S3's twin for `Q-406`'s arm (Phase 264). Arm 2 is an `if`, not a `case`, so
    the guard above cannot see it at all — an exemption here is an appended `&&`,
    not an extra pattern. Pin the condition to exactly the two documented tests.

    Without this, the arm that carries the ratified widening is the one arm of
    the four with no structural guard, and the parametrized behavioural tests
    below cover only the shapes someone thought to enumerate.

    The scrub list is pinned WITH the condition because it is part of the
    predicate, not decoration: Phase 264's round found `GIT_CEILING_DIRECTORIES`
    switching this arm off entirely, so a future shortening of the list is an
    exemption in the same sense an appended `&&` would be."""
    text = LIB.read_text()
    start = text.index('  if owner="$(env -u GIT_DIR')
    cond = text[start:text.index("; then", start)]
    tests = [l.strip().rstrip("\\").strip() for l in cond.splitlines() if l.strip()]
    assert tests == [
        'if owner="$(env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR',
        '-u GIT_CEILING_DIRECTORIES -u GIT_DISCOVERY_ACROSS_FILESYSTEM',
        'git -C "$wr_abs" rev-parse --show-toplevel 2>/dev/null)"',
        '&& [ -n "$owner" ]',
    ], (
        f"the any-work-tree arm's condition is not the documented one: {tests}. An "
        f"added conjunct is an exemption — `Q-406`'s widening is ratified, so a "
        f"narrowing belongs in a phase that argues for it, not in a `&&`."
    )


def test_no_branch_is_created_when_any_root_guard_refuses(tmp_path):
    """S10. `test_a_nonexistent_worktree_root_is_refused_and_creates_nothing`
    SAYS in its docstring "it must not have created the branch or worktree
    either" and asserted only the worktree half. Hoisting the branch creation
    above the guard therefore survived this file entirely — it was caught by a
    Phase-84 guard in another module, not by the one whose stated property it is."""
    root = _seeded(tmp_path)
    inside = root / "inside"
    inside.mkdir()
    for label, target in (("missing", tmp_path / "gone"), ("inside", inside)):
        r = _run(root, "T-0001", f"feat/{label}",
                 env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(target)})
        assert r.returncode == 1, label
        branches = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"], cwd=str(root),
            capture_output=True, text=True, check=True).stdout.split()
        assert f"feat/{label}" not in branches, (
            f"{label}: the guard refused but the branch was already created: {branches}"
        )


def test_this_module_is_still_collected():
    """S11-S13. Deleting both new modules produced exactly ONE unrelated failure
    in the whole suite: nothing asserted they exist or how much they cover. So a
    reviewer could delete a parametrize entry, stub a body, or rename the test
    the docstring calls "the consequential" one, and the suite stayed green while
    the author's own mutations walked back in. `test_mirror_leak_gate.py` carries
    exactly this guard; neither new module did."""
    import test_worktree_root_env as mod

    tests = [n for n in dir(mod) if n.startswith("test_")]
    assert len(tests) >= 21, (
        f"this module collects {len(tests)} test functions; it had 21 when the round "
        f"closed. "
        f"A drop means a guard was renamed or removed — say which in the commit."
    )
    for required in (
        "test_the_containment_guard_holds_from_inside_a_linked_worktree",
        "test_the_lock_records_the_CANONICAL_path",
        "test_the_containment_case_has_no_exemption_arm",
        "test_no_branch_is_created_when_any_root_guard_refuses",
    ):
        assert required in tests, f"a named round-closing guard is gone: {required}"
