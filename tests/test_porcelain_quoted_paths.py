"""`git status --porcelain` C-quotes a path that holds a space, a `"`, a backslash, a control
character or a non-ASCII byte (`?? "sp ace"`), so a site that takes `line[3:]` as the path hands
the ignored-symlink check a name that is not on disk. The link then reads as live work: a
worktree with nothing but its tooling links reads dirty, a landed claim reads not landed.

Each site reads `status --porcelain -z` instead, where no name is quoted and a rename or copy
is two NUL fields, `XY <new>` then `<old>`. This module drives the sites in
`close_state.py worktrees`, `sitrep_survey.py` (`_worktree_dirty`, `_live_work_past`) and
`feature_branch.py landed` over one fixture: a linked claim worktree whose untracked links point
at the primary's ignored `.venv/`, named so `status` quotes them. `clone_sync.py`'s site is
tested beside its other cases in `test_review_close_clone_sync.py`.

Three properties per site: the quoted links are not live work; a real untracked file with the
same kind of name still is; and a staged rename is one change, not two (the old-path field is
consumed, not read as an entry of its own).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import sitrep_survey as ss  # noqa: E402

_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k == "GIT_EXEC_PATH"}
_ENV.update({"GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"})

# Each needs quoting in `status --porcelain` under git's default `core.quotePath`; the space and
# the double quote are quoted under `core.quotePath=false` too. Valid UTF-8 only: APFS refuses
# a name that is not.
QUOTED_NAMES = ["sp ace", "café", 'quo"te']


def _g(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd), env=_ENV, capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


@pytest.fixture
def claim(tmp_path):
    """A primary that ignores `.venv/`, an `origin` it has pushed to, and a linked worktree on
    `feat`, cut at `main`'s tip and named by a lock, with a held doc stamped `held_since:`."""
    origin = tmp_path / "origin.git"
    _g(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    main = tmp_path / "proj"
    main.mkdir()
    _g(main, "init", "-q", "-b", "main")
    for k, v in (("user.name", "t"), ("user.email", "t@t"), ("commit.gpgsign", "false")):
        _g(main, "config", k, v)
    (main / ".gitignore").write_text(".venv/\nsysop/runtime/\n")
    (main / "tracked.txt").write_text("tracked\n")
    _g(main, "add", "-A")
    _g(main, "commit", "-qm", "seed")
    _g(main, "remote", "add", "origin", str(origin))
    _g(main, "push", "-q", "origin", "main")
    (main / ".venv").mkdir()
    wt = tmp_path / "wt-feat"
    _g(main, "worktree", "add", "-q", "-b", "feat", str(wt))
    locks = main / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    (locks / "T-1.lock").write_text(f"task_id: T-1\nbranch: feat\nworkspace: {wt}\n")
    docs = main / "sysop" / "runtime" / "pending-docs"
    docs.mkdir(parents=True)
    (docs / "feat.md").write_text("---\nbranch: feat\nheld_since: 2026-11-01\n---\n\nheld\n")
    return main, wt


def _links(main: Path, wt: Path) -> None:
    for name in QUOTED_NAMES:
        (wt / name).symlink_to(main / ".venv")


def _quoted(wt: Path) -> None:
    """The fixture's premise: plain `status --porcelain` quotes every one of the names."""
    out = _g(wt, "status", "--porcelain")
    for name in QUOTED_NAMES:
        assert f"?? {name}\n" not in out + "\n" and "?? \"" in out, out


# ── close_state.py worktrees (/review-close Step 1a) ─────────────────────────

def _worktrees(main: Path) -> str:
    r = subprocess.run([sys.executable, str(SCRIPTS / "close_state.py"), "worktrees", "main"],
                       cwd=str(main), env=_ENV, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    rows = [ln for ln in r.stdout.splitlines() if " feat  (" in ln]
    assert len(rows) == 1, r.stdout
    return rows[0]


def test_close_state_reads_quoted_ignored_links_as_no_pending_change(claim):
    main, wt = claim
    _links(main, wt)
    _quoted(wt)
    assert _worktrees(main).startswith("MERGED   feat"), _worktrees(main)


@pytest.mark.parametrize("name", QUOTED_NAMES)
def test_close_state_still_counts_a_real_file_with_a_quoted_name(claim, name):
    main, wt = claim
    _links(main, wt)
    (wt / f"{name}.txt").write_text("work\n")
    assert _worktrees(main).endswith("— 1 pending changes"), _worktrees(main)


def test_close_state_counts_a_staged_rename_once(claim):
    """Under `-z` a rename is `R  <new>` then `<old>`: the old path is not a second change."""
    main, wt = claim
    _g(wt, "mv", "tracked.txt", "re named.txt")
    assert _worktrees(main).endswith("— 1 pending changes"), _worktrees(main)
    _links(main, wt)
    assert _worktrees(main).endswith("— 1 pending changes"), _worktrees(main)
    (wt / "x.txt").write_text("x\n")
    assert _worktrees(main).endswith("— 2 pending changes"), _worktrees(main)


# ── sitrep_survey.py ─────────────────────────────────────────────────────────

def _lock(main: Path, wt: Path) -> "ss.Lock":
    return ss.Lock(task_id="T-1", path=main / "sysop/runtime/locks/T-1.lock", branch="feat",
                   workspace=str(wt))


def test_sitrep_worktree_dirty_reads_quoted_ignored_links_as_clean(claim):
    main, wt = claim
    _links(main, wt)
    _quoted(wt)
    assert ss._worktree_dirty(wt, main) is False


@pytest.mark.parametrize("name", QUOTED_NAMES)
def test_sitrep_worktree_dirty_still_reads_a_real_file_with_a_quoted_name(claim, name):
    main, wt = claim
    _links(main, wt)
    (wt / f"{name}.txt").write_text("work\n")
    assert ss._worktree_dirty(wt, main) is True


def test_sitrep_worktree_dirty_reads_a_staged_rename(claim):
    main, wt = claim
    _links(main, wt)
    _g(wt, "mv", "tracked.txt", "re named.txt")
    assert ss._worktree_dirty(wt, main) is True


def test_sitrep_live_work_past_reads_quoted_ignored_links_as_no_work(claim):
    """The lock's workspace is on the branch and its tip is inside the container: only the
    status read can say there is live work."""
    main, wt = claim
    _links(main, wt)
    _quoted(wt)
    tip = _g(main, "rev-parse", "refs/heads/feat")
    assert ss._live_work_past(main, "feat", _lock(main, wt), None, False, [tip]) is False


@pytest.mark.parametrize("name", QUOTED_NAMES)
def test_sitrep_live_work_past_still_reads_a_real_file_with_a_quoted_name(claim, name):
    main, wt = claim
    _links(main, wt)
    (wt / f"{name}.txt").write_text("work\n")
    tip = _g(main, "rev-parse", "refs/heads/feat")
    assert ss._live_work_past(main, "feat", _lock(main, wt), None, False, [tip]) is True


# ── feature_branch.py landed (/review-close Step 2a step 0b) ─────────────────

def _landed(main: Path) -> str:
    r = subprocess.run([sys.executable, str(SCRIPTS / "feature_branch.py"), "landed", "feat", "main"],
                       cwd=str(main), env=_ENV, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout.strip()


def test_landed_reads_quoted_ignored_links_as_no_uncommitted_work(claim):
    main, wt = claim
    _links(main, wt)
    _quoted(wt)
    assert _landed(main) == "LANDED: in main — held doc feat.md"


@pytest.mark.parametrize("name", QUOTED_NAMES)
def test_landed_still_refuses_a_real_file_with_a_quoted_name(claim, name):
    main, wt = claim
    _links(main, wt)
    (wt / f"{name}.txt").write_text("work\n")
    assert _landed(main) == f"NOT LANDED — workspace {wt} has uncommitted work on it"


def test_landed_still_refuses_a_staged_rename(claim):
    main, wt = claim
    _links(main, wt)
    _g(wt, "mv", "tracked.txt", "re named.txt")
    assert _landed(main) == f"NOT LANDED — workspace {wt} has uncommitted work on it"


# ── close_state.py strip-links (/review-close Step 3b) ───────────────────────

def test_strip_links_does_not_read_a_renames_old_path_as_an_untracked_entry(claim):
    """Under `-z` a rename is two fields, `R  <new>` then `<old>`. An old path named
    `?? sl` read as an entry of its own is the untracked name `sl`, and a TRACKED link of that
    name to an ignored target would be stripped as tooling. (Phase 476's battery, A08.)"""
    main, wt = claim
    (wt / "sl").symlink_to(main / ".venv")
    (wt / "?? sl").write_text("x\n")
    _g(wt, "add", "sl", "?? sl")
    _g(wt, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "tracked link")
    _g(wt, "mv", "?? sl", "moved")
    assert "?? sl" in subprocess.run(["git", "status", "--porcelain", "-z"], cwd=str(wt), env=_ENV,
                                     capture_output=True, text=True).stdout.split("\0")
    r = subprocess.run([sys.executable, str(SCRIPTS / "close_state.py"), "strip-links", str(wt)],
                       cwd=str(main), env=_ENV, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "REMOVED LINK" not in r.stdout, r.stdout
    assert (wt / "sl").is_symlink()


# ── status.showUntrackedFiles=no hides no work (Phase 476's round, lens 1) ───
# `close_state.py worktrees` has passed `--untracked-files=normal` since Phase 421; the other
# readers ran a bare status, so a consumer's `status.showUntrackedFiles=no` read a real
# untracked file as no work at all.

def _hidden_untracked(wt: Path) -> None:
    _g(wt, "config", "status.showUntrackedFiles", "no")
    (wt / "work.txt").write_text("work\n")
    assert "work.txt" not in _g(wt, "status", "--porcelain"), "the config does not hide it"


def test_close_state_sees_untracked_work_the_config_hides(claim):
    main, wt = claim
    _hidden_untracked(wt)
    assert _worktrees(main).endswith("— 1 pending changes"), _worktrees(main)


def test_sitrep_worktree_dirty_sees_untracked_work_the_config_hides(claim):
    main, wt = claim
    _hidden_untracked(wt)
    assert ss._worktree_dirty(wt, main) is True


def test_sitrep_live_work_past_sees_untracked_work_the_config_hides(claim):
    main, wt = claim
    _hidden_untracked(wt)
    tip = _g(main, "rev-parse", "refs/heads/feat")
    assert ss._live_work_past(main, "feat", _lock(main, wt), None, False, [tip]) is True


def test_landed_sees_untracked_work_the_config_hides(claim):
    main, wt = claim
    _hidden_untracked(wt)
    assert _landed(main) == f"NOT LANDED — workspace {wt} has uncommitted work on it"


def test_close_state_counts_a_worktree_side_rename_once(claim):
    """`git add -N` on a moved file gives a rename in the Y column (` R <new>` then `<old>`):
    its old path is consumed too, not only an index-side `R ` (Phase 476's round, lens 2)."""
    main, wt = claim
    (wt / "tracked.txt").rename(wt / "moved.txt")
    _g(wt, "add", "-N", "moved.txt")
    raw = subprocess.run(["git", "status", "--porcelain", "-z"], cwd=str(wt), env=_ENV,
                         capture_output=True, text=True).stdout
    assert raw.startswith(" R "), f"the fixture makes no worktree-side rename: {raw!r}"
    assert _worktrees(main).endswith("— 1 pending changes"), _worktrees(main)


def test_sitrep_worktree_dirty_reads_a_worktree_without_its_git_link_as_dirty(claim):
    """With the `.git` link gone, git walks up and reports an enclosing repository's status
    (here none, so a clean read): /sitrep read it clean where Step 1a reads it DIRTY (Phase
    476's round, lens 1)."""
    main, wt = claim
    (wt / ".git").unlink()
    assert ss._worktree_dirty(wt, main) is True
