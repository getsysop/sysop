"""`Q-645` (Phase 355): `/review-close` Step 1-pre brings a `--clone` claim's commits across.

A `--clone` workspace is its own repository, and Step 4a merges THIS repository's
`refs/heads/<branch>`, which nothing in the close moved, so the clone's work never merged.
Every test runs the shipped script `SKILL.md` prescribes (its heredoc until Phase 386), against a real repository
whose `origin` is a local bare repository, with clones made by the real `claim_task.sh`.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from skill_runner_text import text_of

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
CLOSE = REPO_ROOT / "core/skills/review-close/SKILL.md"
_ENV = {k: v for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}


def _section() -> str:
    text = text_of(CLOSE)
    start = text.index("### 1-pre. Bring `--clone` claims' commits across")
    return text[start:text.index("### 1a. Classify Worktree State", start)]


SCRIPT = SCRIPTS / "clone_sync.py"
INVOCATION = 'python3 sysop/scripts/clone_sync.py "<default branch>" "<apply or dry-run>"'


def _heredoc() -> str:
    """The program Step 1-pre runs: a shipped script since Phase 386 (`Q-409` P3)."""
    assert INVOCATION in _section(), "Step 1-pre no longer runs clone_sync.py"
    return SCRIPT.read_text()


def _g(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=_ENV)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def _ident(d: Path) -> None:
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        _g(d, "config", k, v)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    _g(root, "-c", "init.defaultBranch=main", "init", "-q")
    _ident(root)
    sd = root / "sysop" / "scripts"
    sd.mkdir(parents=True)
    for n in ("_git_lib.sh", "_log.py", "review_index.py"):
        shutil.copy(SCRIPTS / n, sd / n)
    (root / "tasks").mkdir()
    (root / "tasks" / "index.yml").write_text(
        "tasks:\n" + "".join(
            f"  - id: T-{i}\n    title: Demo\n    status: open\n    priority: high\n"
            f"    effort: S\n    blast_radius: local\n" for i in (1, 2)))
    (root / ".gitignore").write_text("sysop/runtime/\n")
    _g(root, "add", "-A")
    _g(root, "commit", "-qm", "seed")
    bare = tmp_path / "origin.git"
    _g(tmp_path, "-c", "init.defaultBranch=main", "init", "--bare", "-q", str(bare))
    _g(root, "remote", "add", "origin", str(bare))
    _g(root, "push", "-q", "origin", "main")
    return root


def _claim(root: Path, task: str, branch: str, *, lock: bool = True) -> Path:
    args = ["bash", str(SCRIPTS / "claim_task.sh"), *(["--lock"] if lock else []), "--clone",
            task, branch]
    r = subprocess.run(args, cwd=str(root), capture_output=True, text=True, env=_ENV)
    assert r.returncode == 0, r.stdout + r.stderr
    clone = root.parent / f"proj-{task.lower()}"
    assert clone.is_dir(), list(root.parent.iterdir())
    _ident(clone)
    return clone


def _commit(d: Path, name: str = "a.txt") -> str:
    (d / name).write_text(name + "\n")
    _g(d, "add", name)
    _g(d, "commit", "-qm", name)
    return _g(d, "rev-parse", "HEAD")


def _sync(root: Path, mode: str = "apply", default: str = "main", cwd: Path | None = None):
    return subprocess.run(["python3", str(SCRIPT), default, mode],
                          cwd=str(cwd or root), capture_output=True, text=True, env=_ENV)


def _tip(root: Path, branch: str) -> str:
    return _g(root, "rev-parse", f"refs/heads/{branch}")




def _line(out: str, word: str) -> str:
    hits = [ln for ln in out.splitlines() if ln.startswith(word + " ")]
    assert len(hits) == 1, out
    return hits[0]


def _summary(out: str) -> str:
    last = out.splitlines()[-1]
    assert last.startswith("CLONE SYNC: "), out
    return last


def _step(start: str, end: str) -> str:
    text = text_of(CLOSE)
    a = text.index(start)
    return text[a:text.index(end, a)]


def _step_0a() -> str:
    return _step("0a. **Clone pre-check (Step 1-pre result).**", "0b. **Landed check.**")


# ── the entry's reproduction ──────────────────────────────────────────────────

def test_the_premise_nothing_else_brings_the_clone_across(tmp_path):
    """Before the fix: the clone has the work, this repository's branch has the claim."""
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    claim = _tip(root, "feat/cl")
    work = _commit(clone)
    assert _tip(root, "feat/cl") == claim != work
    _g(root, "fetch", "-q", "origin", "feat/cl")          # Step 4-pre's only branch fetch
    assert _tip(root, "feat/cl") == claim


def test_the_reproduction_is_brought_across(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    claim = _tip(root, "feat/cl")
    work = _commit(clone)

    r = _sync(root, "dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "-> " + work[:12] in _line(r.stdout, "WOULD SYNC")
    assert _tip(root, "feat/cl") == claim, "dry-run moved the branch"

    r = _sync(root)
    assert r.returncode == 0, r.stdout + r.stderr
    line = _line(r.stdout, "SYNCED")
    assert f"{claim[:12]} -> {work[:12]}, 1 commits" in line and str(clone.name) in line
    assert _tip(root, "feat/cl") == work
    assert _summary(r.stdout) == "CLONE SYNC: 1 line(s) — synced 1"

    r = _sync(root)
    assert "already at " + work[:12] in _line(r.stdout, "CURRENT")


@pytest.mark.parametrize("where", ["branch", "default"])
def test_after_the_sync_the_ignored_file_check_reads_the_clone(tmp_path, where):
    """Phase 354's check refused every ordinary clone close (exit 3); the sync ends that,
    including for a finished clone that stepped back onto the default branch (round 1)."""
    root = _repo(tmp_path)
    shutil.copy(SCRIPTS / "ignored_refs.py", root / "sysop" / "scripts" / "ignored_refs.py")
    clone = _claim(root, "T-1", "feat/cl")
    _commit(clone)
    if where == "default":
        _g(clone, "checkout", "-q", "main")
    check = ["python3", "sysop/scripts/ignored_refs.py", str(clone), "main", "--branch", "feat/cl"]
    before = subprocess.run(check, cwd=str(root), capture_output=True, text=True, env=_ENV)
    assert before.returncode == 3 and "Step 1-pre" in before.stderr, before.stderr
    assert "SYNCED" in _sync(root).stdout
    after = subprocess.run(check, cwd=str(root), capture_output=True, text=True, env=_ENV)
    assert after.returncode == 0, after.stdout + after.stderr


def test_two_clones_are_both_brought_across(tmp_path):
    root = _repo(tmp_path)
    c1, c2 = _claim(root, "T-1", "feat/one"), _claim(root, "T-2", "feat/two")
    w1, w2 = _commit(c1), _commit(c2, "b.txt")
    assert _summary(_sync(root).stdout) == "CLONE SYNC: 2 line(s) — synced 2"
    assert (_tip(root, "feat/one"), _tip(root, "feat/two")) == (w1, w2)


def test_a_tag_named_like_the_branch_does_not_misdirect_the_fetch(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _g(root, "tag", "feat/cl", "main")
    _g(clone, "tag", "feat/cl", "main")
    work = _commit(clone)
    assert "SYNCED" in _sync(root).stdout and _tip(root, "feat/cl") == work


@pytest.mark.parametrize("first", ["A-0", "Z-0"])
def test_a_stale_lock_does_not_hide_a_live_clone(tmp_path, first):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    work = _commit(clone)
    (root / "sysop/runtime/locks" / f"{first}.lock").write_text(
        f"task_id: {first}\nbranch: feat/cl\nmode: clone\nworkspace: {tmp_path}/missing\n")
    r = _sync(root)
    assert "SYNCED" in r.stdout and "GONE" not in r.stdout and _tip(root, "feat/cl") == work, r.stdout


# ── what it refuses, and what it leaves alone ─────────────────────────────────

def test_a_divergence_is_refused_and_nothing_moves(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _commit(clone)
    _g(root, "checkout", "-q", "feat/cl")
    mine = _commit(root, "here.txt")
    _g(root, "checkout", "-q", "main")
    r = _sync(root)
    assert "not a fast-forward" in _line(r.stdout, "REFUSED"), r.stdout
    assert _tip(root, "feat/cl") == mine


def test_a_commit_the_clone_dropped_is_refused_not_passed(tmp_path):
    """Round 1: after a sync, `reset --hard HEAD~1` in the clone left the dropped commit on this
    branch, and the first cut passed it as `BEHIND`, so it would have merged."""
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _commit(clone)
    dropped = _commit(clone, "b.txt")
    assert "SYNCED" in _sync(root).stdout
    _g(clone, "reset", "-q", "--hard", "HEAD~1")
    r = _sync(root)
    assert "not a fast-forward" in _line(r.stdout, "REFUSED"), r.stdout
    assert _tip(root, "feat/cl") == dropped


def test_a_rewrite_after_a_sync_is_refused(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _commit(clone)
    assert "SYNCED" in _sync(root).stdout
    _g(clone, "commit", "-q", "--amend", "-m", "reworded")
    assert "not a fast-forward" in _line(_sync(root).stdout, "REFUSED")


@pytest.mark.parametrize("change", ["modified", "untracked", "staged"])
def test_a_dirty_clone_is_not_brought_across(tmp_path, change):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    claim = _tip(root, "feat/cl")
    _commit(clone)
    if change == "modified":
        (clone / "a.txt").write_text("changed\n")
    elif change == "untracked":
        (clone / "new.txt").write_text("x\n")
    else:
        (clone / "s.txt").write_text("x\n")
        _g(clone, "add", "s.txt")
    r = _sync(root)
    assert "1 pending changes" in _line(r.stdout, "DIRTY"), r.stdout
    assert _tip(root, "feat/cl") == claim


def test_a_clone_dirtied_after_a_sync_is_dirty_not_current(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _commit(clone)
    assert "SYNCED" in _sync(root).stdout
    (clone / "a.txt").write_text("changed\n")
    assert "pending changes" in _line(_sync(root).stdout, "DIRTY")


def test_a_clone_mid_rebase_is_dirty(tmp_path):
    """Round 1: a conflicted rebase detaches HEAD, and the first cut read dirt only on the
    branch, so it synced the pre-rebase tip with the commit the rebase was dropping."""
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    claim = _tip(root, "feat/cl")
    for i in range(3):
        (clone / "a.txt").write_text(f"{i}\n")
        _g(clone, "add", "a.txt")
        _g(clone, "commit", "-qm", f"c{i}")
    r = subprocess.run(["git", "rebase", "--onto", "HEAD~2", "HEAD~1"], cwd=str(clone),
                       capture_output=True, text=True, env=_ENV)
    assert r.returncode != 0, "the fixture's rebase was meant to stop on a conflict"
    out = _sync(root).stdout
    assert "in progress in" in _line(out, "DIRTY") and "(rebase-merge)" in _line(out, "DIRTY"), out
    assert _tip(root, "feat/cl") == claim


def test_a_clean_paused_rebase_is_dirty(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _commit(clone)
    _commit(clone, "b.txt")
    r = subprocess.run(["git", "-c", "sequence.editor=sed -i.bak s/^pick/edit/",
                        "rebase", "-i", "HEAD~1"], cwd=str(clone), capture_output=True,
                       text=True, env=_ENV)
    assert r.returncode == 0, r.stderr
    assert "in progress" in _line(_sync(root).stdout, "DIRTY")


def test_a_bisect_in_progress_is_dirty_though_the_tree_is_clean(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _commit(clone)
    _commit(clone, "b.txt")
    _g(clone, "bisect", "start", "HEAD", "HEAD~2")
    assert _g(clone, "status", "--porcelain") == ""
    assert _line(_sync(root).stdout, "DIRTY").endswith("(BISECT_LOG)")


def test_a_detached_clone_with_edits_is_dirty(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _commit(clone)
    _g(clone, "checkout", "-q", "--detach")
    (clone / "a.txt").write_text("changed\n")
    assert "pending changes" in _line(_sync(root).stdout, "DIRTY")


@pytest.mark.parametrize("marker", ["rebase-merge", "rebase-apply", "MERGE_HEAD",
                                    "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "sequencer"])
def test_every_operation_in_progress_is_dirty(tmp_path, marker):
    """Round 2: only two of the markers had a fixture; `sequencer` was missing outright, and
    a resolved multi-commit cherry-pick leaves only it behind with a clean tree."""
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    claim = _tip(root, "feat/cl")
    _commit(clone)
    path = clone / ".git" / marker
    if marker in ("rebase-merge", "rebase-apply", "sequencer"):
        path.mkdir()
    else:
        path.write_text(_g(clone, "rev-parse", "HEAD") + "\n")
    assert f"in progress in {clone} ({marker})" in _line(_sync(root).stdout, "DIRTY")
    assert _tip(root, "feat/cl") == claim


@pytest.mark.parametrize("state", ["edits", "mid-rebase"])
def test_a_worktree_of_the_clone_holding_the_branch_is_read(tmp_path, state):
    """Round 2: the checks read only the clone's root, so a linked worktree of the clone
    holding the branch synced over its edits and over a conflicted rebase."""
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    claim = _tip(root, "feat/cl")
    _g(clone, "checkout", "-q", "main")
    wt = tmp_path / "clone-wt"
    _g(clone, "worktree", "add", "-q", str(wt), "feat/cl")
    _ident(wt)
    for i in range(3):
        (wt / "a.txt").write_text(f"{i}\n")
        _g(wt, "add", "a.txt")
        _g(wt, "commit", "-qm", f"c{i}")
    if state == "edits":
        (wt / "a.txt").write_text("edit\n")
    else:
        subprocess.run(["git", "rebase", "--onto", "HEAD~2", "HEAD~1"], cwd=str(wt),
                       capture_output=True, env=_ENV)
    line = _line(_sync(root).stdout, "DIRTY")
    assert str(wt.resolve()) in line or str(wt) in line, line
    assert _tip(root, "feat/cl") == claim


def test_a_detached_head_holding_commits_the_branch_lacks_is_dirty(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _commit(clone)
    _g(clone, "checkout", "-q", "--detach")
    _commit(clone, "b.txt")
    assert "detached HEAD" in _line(_sync(root).stdout, "DIRTY")


def test_a_venv_symlink_into_this_repository_is_not_dirt(tmp_path):
    """Round 2: Step 1a's ISSUE-0043 downgrade, missing here, made a `.venv` link a SKIP."""
    root = _repo(tmp_path)
    (root / ".gitignore").write_text("sysop/runtime/\n.venv/\n")
    (root / ".venv").mkdir()
    clone = _claim(root, "T-1", "feat/cl")
    (clone / ".venv").symlink_to(root / ".venv")
    work = _commit(clone)
    assert "SYNCED" in _sync(root).stdout and _tip(root, "feat/cl") == work


def test_a_symlink_to_an_unignored_target_is_still_dirt(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    (clone / "link").symlink_to(root / "README.md" if (root / "README.md").exists() else root / "tasks")
    _commit(clone)
    assert "pending changes" in _line(_sync(root).stdout, "DIRTY")


def test_counts_are_counted(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _commit(clone)
    _commit(clone, "b.txt")
    (clone / "x.txt").write_text("x\n")
    (clone / "y.txt").write_text("y\n")
    assert "2 pending changes" in _line(_sync(root).stdout, "DIRTY")
    (clone / "x.txt").unlink()
    (clone / "y.txt").unlink()
    assert ", 2 commits" in _line(_sync(root).stdout, "SYNCED")


def test_a_branch_absent_here_is_created(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    work = _commit(clone)
    _g(root, "branch", "-q", "-D", "feat/cl")
    assert "absent -> " + work[:12] in _line(_sync(root).stdout, "SYNCED")
    assert _tip(root, "feat/cl") == work


def test_an_inherited_git_dir_does_not_redirect_it(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    work = _commit(clone)
    other = tmp_path / "elsewhere"
    _g(tmp_path, "init", "-q", str(other))
    r = subprocess.run(["python3", str(SCRIPT), "main", "apply"], cwd=str(root),
                       capture_output=True, text=True,
                       env=dict(_ENV, GIT_DIR=str(other / ".git"), GIT_WORK_TREE=str(other)))
    assert "SYNCED" in r.stdout and _tip(root, "feat/cl") == work, r.stdout + r.stderr


def test_a_status_failure_in_the_clone_is_refused(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    claim = _tip(root, "feat/cl")
    _commit(clone)
    (clone / ".git" / "index").write_bytes(b"garbage")
    assert "git status failed" in _line(_sync(root).stdout, "REFUSED")
    assert _tip(root, "feat/cl") == claim


def test_no_private_ref_is_left_behind(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _commit(clone)
    _sync(root)
    assert _g(root, "for-each-ref", "refs/sysop/") == ""


def test_a_lock_spelled_in_another_case_still_finds_the_clone(tmp_path):
    """Round 3 (both lenses): round 2 compared paths as strings, so on a case-insensitive disk a
    lock spelled differently from the directory read as a missing clone and the work stayed out."""
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    if not (clone.parent / clone.name.upper()).exists():
        pytest.skip("case-sensitive filesystem")
    work = _commit(clone)
    lock = root / "sysop/runtime/locks/T-1.lock"
    lock.write_text(lock.read_text().replace("proj-t-1", "PROJ-T-1"))
    line = _line(_sync(root).stdout, "SYNCED")
    assert "origin" not in line and _tip(root, "feat/cl") == work, line


@pytest.mark.parametrize("loss", ["deleted", "branch-dropped"])
def test_losing_the_clone_after_a_sync_keeps_the_synced_work(tmp_path, loss):
    """Round 3: nothing in a clone pushes, so after a sync origin is behind this repository;
    the first origin fallback read that as REFUSED, and its remedy's forced fetch discarded the
    synced work."""
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    work = _commit(clone)
    assert "SYNCED" in _sync(root).stdout
    if loss == "deleted":
        shutil.rmtree(clone)
    else:
        _g(clone, "checkout", "-q", "-b", "feat/next")
        _g(clone, "branch", "-q", "-D", "feat/cl")
    assert "already holds origin's" in _line(_sync(root).stdout, "CURRENT")
    assert _tip(root, "feat/cl") == work


def test_origin_diverged_from_this_repository_is_refused(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _commit(clone)
    _g(clone, "push", "-q", "origin", "feat/cl")
    shutil.rmtree(clone)
    wt = tmp_path / "wt"
    _g(root, "worktree", "add", "-q", str(wt), "feat/cl")
    _ident(wt)
    mine = _commit(wt, "here.txt")
    _g(root, "worktree", "remove", str(wt))
    assert "not a fast-forward" in _line(_sync(root).stdout, "REFUSED")
    assert _tip(root, "feat/cl") == mine


def test_an_unreachable_origin_is_refused(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    shutil.rmtree(clone)
    (tmp_path / "origin.git").rename(tmp_path / "moved.git")
    assert "origin could not be read" in _line(_sync(root).stdout, "REFUSED")


def test_an_unrelated_detached_worktree_of_the_clone_is_not_read(tmp_path):
    """Round 3: a look-around worktree at a newer default branch was a DIRTY no remedy cleared."""
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    work = _commit(clone)
    _g(clone, "fetch", "-q", "origin")
    _g(clone, "worktree", "add", "-q", "--detach", str(tmp_path / "look"), "origin/main")
    (tmp_path / "look" / "scratch.txt").write_text("x\n")
    assert "SYNCED" in _sync(root).stdout and _tip(root, "feat/cl") == work


def test_every_holder_is_read_not_only_the_first(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _commit(clone)
    _g(clone, "checkout", "-q", "--detach")
    wt = tmp_path / "clone-wt"
    _g(clone, "worktree", "add", "-q", str(wt), "feat/cl")
    (wt / "a.txt").write_text("edit\n")
    assert str(wt) in _line(_sync(root).stdout, "DIRTY")


def test_an_operation_in_progress_in_a_linked_worktree_is_read(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _commit(clone)
    _g(clone, "checkout", "-q", "main")
    wt = tmp_path / "clone-wt"
    _g(clone, "worktree", "add", "-q", str(wt), "feat/cl")
    gitdir = Path(_g(wt, "rev-parse", "--absolute-git-dir"))
    (gitdir / "sequencer").mkdir()
    assert "(sequencer)" in _line(_sync(root).stdout, "DIRTY")


def test_a_missing_worktree_of_the_clone_is_skipped(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    work = _commit(clone)
    _g(clone, "worktree", "add", "-q", "--detach", str(tmp_path / "gone-wt"), "feat/cl")
    shutil.rmtree(tmp_path / "gone-wt")
    assert "SYNCED" in _sync(root).stdout and _tip(root, "feat/cl") == work


def test_a_missing_worktree_that_held_the_branch_is_skipped(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _g(clone, "checkout", "-q", "main")
    wt = tmp_path / "clone-wt"
    _g(clone, "worktree", "add", "-q", str(wt), "feat/cl")
    _ident(wt)
    work = _commit(wt)
    shutil.rmtree(wt)
    assert "SYNCED" in _sync(root).stdout and _tip(root, "feat/cl") == work


def test_a_relative_venv_link_into_this_repository_is_not_dirt(tmp_path):
    root = _repo(tmp_path)
    (root / ".gitignore").write_text("sysop/runtime/\n.venv/\n")
    (root / ".venv").mkdir()
    clone = _claim(root, "T-1", "feat/cl")
    (clone / ".venv").symlink_to(os.path.relpath(root / ".venv", clone))
    work = _commit(clone)
    assert "SYNCED" in _sync(root).stdout and _tip(root, "feat/cl") == work


@pytest.mark.parametrize("arm", ["clone", "origin"])
def test_a_dry_run_changes_no_ref_and_writes_no_fetch_head(tmp_path, arm):
    """Round 3: the origin arm moved refs/remotes/origin/<b> and wrote FETCH_HEAD under dry-run."""
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _commit(clone)
    if arm == "origin":
        _g(clone, "push", "-q", "origin", "feat/cl")
        shutil.rmtree(clone)
    fetch_head = Path(_g(root, "rev-parse", "--absolute-git-dir")) / "FETCH_HEAD"
    if fetch_head.exists():
        fetch_head.unlink()
    refs = _g(root, "for-each-ref")
    assert "WOULD SYNC" in _sync(root, "dry-run").stdout
    assert _g(root, "for-each-ref") == refs and not fetch_head.exists()


def test_a_stale_private_ref_is_cleared(tmp_path):
    """Round 3: a leftover ref under the private namespace blocked the fetch forever."""
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    work = _commit(clone)
    _g(root, "update-ref", "refs/sysop/clone-sync/feat/cl/x", "main")
    assert "SYNCED" in _sync(root).stdout and _tip(root, "feat/cl") == work
    assert _g(root, "for-each-ref", "refs/sysop/") == ""


def test_the_origin_arm_leaves_no_private_ref(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _commit(clone)
    _g(clone, "push", "-q", "origin", "feat/cl")
    shutil.rmtree(clone)
    assert "SYNCED" in _sync(root).stdout
    assert _g(root, "for-each-ref", "refs/sysop/") == ""


def test_a_lock_naming_the_default_branch_is_ignored(tmp_path):
    root = _repo(tmp_path)
    locks = root / "sysop/runtime/locks"
    locks.mkdir(parents=True)
    (locks / "T-1.lock").write_text(f"task_id: T-1\nbranch: main\nmode: clone\nworkspace: {tmp_path}/x\n")
    assert _summary(_sync(root).stdout) == "CLONE SYNC: 0 line(s)"


def test_a_lock_without_a_mode_is_read_as_a_clone(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    lock = root / "sysop/runtime/locks/T-1.lock"
    lock.write_text("".join(ln for ln in lock.read_text().splitlines(True) if not ln.startswith("mode:")))
    shutil.rmtree(clone)
    _g(root, "push", "-q", "origin", "--delete", "feat/cl")
    assert "GONE" in _sync(root).stdout


def test_dirt_on_another_branch_of_the_clone_is_not_this_branchs(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    work = _commit(clone)
    _g(clone, "checkout", "-q", "-b", "other")
    (clone / "new.txt").write_text("x\n")
    r = _sync(root)
    assert "SYNCED" in r.stdout and _tip(root, "feat/cl") == work, r.stdout


def test_a_branch_checked_out_here_is_refused_by_git(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    claim = _tip(root, "feat/cl")
    _commit(clone)
    _g(root, "checkout", "-q", "feat/cl")
    r = _sync(root, default="main")
    assert "feat/cl is checked out at" in _line(r.stdout, "REFUSED"), r.stdout
    assert _tip(root, "feat/cl") == claim


def test_a_locked_workspace_of_another_project_is_refused(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    claim = _tip(root, "feat/cl")
    _commit(clone)
    other = tmp_path / "other.git"
    _g(tmp_path, "init", "--bare", "-q", str(other))
    _g(clone, "remote", "set-url", "origin", str(other))
    r = _sync(root)
    assert "not this repository's origin" in _line(r.stdout, "REFUSED"), r.stdout
    assert _tip(root, "feat/cl") == claim


def test_a_clone_without_the_branch_says_so(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    _g(clone, "checkout", "-q", "main")
    _g(clone, "branch", "-q", "-D", "feat/cl")
    assert "already at" in _line(_sync(root).stdout, "CURRENT")    # origin holds the claim commit
    _g(root, "push", "-q", "origin", "--delete", "feat/cl")
    assert "the clone has no feat/cl, and origin has no feat/cl either" in _line(
        _sync(root).stdout, "NO BRANCH")


def test_a_missing_clone_and_no_origin_branch_is_gone(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    shutil.rmtree(clone)
    _g(root, "push", "-q", "origin", "--delete", "feat/cl")
    r = _sync(root)
    assert "origin has no feat/cl either" in _line(r.stdout, "GONE"), r.stdout
    assert _summary(r.stdout) == "CLONE SYNC: 1 line(s) — gone 1"


def test_a_missing_clone_whose_work_was_pushed_comes_from_origin(tmp_path):
    """Round 2: the remedy 'fetch from origin and re-run' looped, because GONE never looked
    past the lock; the close now falls back to origin itself."""
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    work = _commit(clone)
    _g(clone, "push", "-q", "origin", "feat/cl")
    shutil.rmtree(clone)
    line = _line(_sync(root).stdout, "SYNCED")
    assert "origin, because the clone is missing" in line and _tip(root, "feat/cl") == work
    assert "CURRENT" in _sync(root).stdout


def test_a_clone_that_lost_its_branch_comes_from_origin(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    work = _commit(clone)
    _g(clone, "push", "-q", "origin", "feat/cl")
    _g(clone, "checkout", "-q", "main")
    _g(clone, "branch", "-q", "-D", "feat/cl")
    assert "origin, because the clone has no feat/cl" in _line(_sync(root).stdout, "SYNCED")
    assert _tip(root, "feat/cl") == work


def test_a_missing_clone_inside_another_repository_is_gone_not_foreign(tmp_path):
    """Round 2: a re-created empty directory inside an enclosing repository was read as that
    repository, and printed a false cause."""
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    shutil.rmtree(clone)
    _g(root, "push", "-q", "origin", "--delete", "feat/cl")
    _g(tmp_path, "-c", "init.defaultBranch=main", "init", "-q")
    clone.mkdir()
    assert "the clone is missing or is not a repository" in _line(_sync(root).stdout, "GONE")


def test_a_worktree_lock_with_a_missing_directory_is_not_a_clone(tmp_path):
    root = _repo(tmp_path)
    locks = root / "sysop/runtime/locks"
    locks.mkdir(parents=True)
    (locks / "T-1.lock").write_text(f"task_id: T-1\nbranch: feat/w\nmode: worktree\nworkspace: {tmp_path}/gone\n")
    assert _summary(_sync(root).stdout) == "CLONE SYNC: 0 line(s)"


def test_two_locks_recording_clones_for_one_branch_are_refused(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    other = tmp_path / "proj-copy"
    _g(tmp_path, "clone", "-q", "-b", "feat/cl", str(tmp_path / "origin.git"), str(other))
    (root / "sysop/runtime/locks/T-2.lock").write_text(
        f"task_id: T-2\nbranch: feat/cl\nmode: clone\nworkspace: {other}\n")
    _commit(clone)
    assert "two locks record clones" in _line(_sync(root).stdout, "REFUSED")


def test_an_unreadable_lock_stops_the_sync(tmp_path):
    root = _repo(tmp_path)
    _claim(root, "T-1", "feat/cl")
    lock = root / "sysop/runtime/locks/T-1.lock"
    lock.chmod(0)
    try:
        if os.access(lock, os.R_OK):
            pytest.skip("running as a user who can read a mode-000 file")
        r = _sync(root)
    finally:
        lock.chmod(0o644)
    assert r.returncode == 4 and r.stdout.startswith("ERROR: cannot read"), r.stdout + r.stderr


def test_a_lock_that_is_a_directory_is_skipped(tmp_path):
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/cl")
    (root / "sysop/runtime/locks/D.lock").mkdir()
    work = _commit(clone)
    r = _sync(root)
    assert r.returncode == 0 and _tip(root, "feat/cl") == work, r.stdout + r.stderr


# ── clones no lock names (Wade, 2026-10-04, after round 2: locks only) ────────

def test_a_clone_claimed_without_a_lock_is_not_seen(tmp_path):
    """A declared limit, not a defect: Step 1-pre reads only clones a lock records."""
    root = _repo(tmp_path)
    clone = _claim(root, "T-1", "feat/nolock", lock=False)
    claim = _tip(root, "feat/nolock")
    _commit(clone)
    assert _summary(_sync(root).stdout) == "CLONE SYNC: 0 line(s)"
    assert _tip(root, "feat/nolock") == claim


def test_a_personal_clone_of_the_project_does_not_feed_a_branch(tmp_path):
    """Round 1: an ordinary `git clone` of the same origin, on a local branch with one
    experiment commit, was fast-forwarded in."""
    root = _repo(tmp_path)
    _g(root, "branch", "release")
    _g(root, "push", "-q", "origin", "release")
    mirror = tmp_path / "zz-scratch-copy"
    _g(tmp_path, "clone", "-q", "-b", "release", str(tmp_path / "origin.git"), str(mirror))
    _ident(mirror)
    _commit(mirror, "experiment.txt")
    before = _tip(root, "release")
    assert _summary(_sync(root).stdout) == "CLONE SYNC: 0 line(s)"
    assert _tip(root, "release") == before


def test_a_worktree_claim_is_not_a_clone(tmp_path):
    root = _repo(tmp_path)
    r = subprocess.run(["bash", str(SCRIPTS / "claim_task.sh"), "--lock", "T-1", "feat/wt"],
                       cwd=str(root), capture_output=True, text=True, env=_ENV)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _summary(_sync(root).stdout) == "CLONE SYNC: 0 line(s)"


def test_no_origin_means_no_clone(tmp_path):
    root = _repo(tmp_path)
    _g(root, "remote", "remove", "origin")
    r = _sync(root)
    assert r.returncode == 0 and r.stdout.startswith("CLONE SYNC: no origin remote"), r.stdout


@pytest.mark.parametrize("default,mode", [("<default branch>", "apply"),
                                          ("main", "<apply or dry-run>"), ("", "apply")])
def test_a_placeholder_is_exit_3(tmp_path, default, mode):
    root = _repo(tmp_path)
    r = _sync(root, mode, default)
    assert r.returncode == 3 and r.stdout.startswith("ERROR: substitute"), r.stdout


def test_run_from_a_subdirectory_is_exit_3(tmp_path):
    root = _repo(tmp_path)
    r = _sync(root, cwd=root / "tasks")
    assert r.returncode == 3 and "top level" in r.stdout, r.stdout


def test_run_from_a_linked_worktree_is_exit_3(tmp_path):
    root = _repo(tmp_path)
    wt = tmp_path / "wt"
    _g(root, "worktree", "add", "-q", str(wt), "-b", "w")
    r = _sync(root, cwd=wt)
    assert r.returncode == 3 and "main checkout" in r.stdout, r.stdout


# ── the prose that consumes it ────────────────────────────────────────────────

SKIP_WORDS = ("DIRTY", "REFUSED", "NO BRANCH", "GONE")


def test_step_1_pre_runs_before_step_1s_reads():
    text = text_of(CLOSE)
    step1 = text.index("## Step 1: Gather State")
    assert step1 < text.index("### 1-pre.") < text.index("- `git branch -a`", step1)
    assert text.index("## Pre-flight: Permission Guard") < step1


def test_every_word_the_heredoc_prints_is_routed():
    words = set(re.findall(r'"([A-Z][A-Z ]{2,}[A-Z])"', _heredoc())) - {"HEAD", "ERROR"}
    assert words == set(SKIP_WORDS) | {"CURRENT", "WOULD SYNC", "SYNCED"}, words
    sec = _section()
    for w in words:
        assert f"`{w}`" in sec, w
    trigger = _step_0a().split(":", 1)[0]
    remedies = _step_0a()
    for w in SKIP_WORDS:
        assert f"`{w}`" in trigger, f"step 0a does not SKIP {w}"
        assert re.search(rf"^   - [^\n]*`{w}`[^\n]*:", remedies, re.M), f"no remedy for {w}"
    assert "**SKIP — clone not brought across**" in remedies
    assert "a dry run does not bring a clone's commits across" in remedies


def test_the_skip_reaches_steps_6_and_8():
    text = text_of(CLOSE)
    assert "Step 1a classified the worktree as `dirty`, or step 0a's clone pre-check):" in text
    assert "or, for step 0a's clone pre-check, the Step 1-pre line + its remedy>" in text
    assert "\nClone sync:    <Step 1-pre's lines" in text


def test_the_script_binds_the_seeded_rule_and_no_positional_parameter():
    sec = _section()
    assert "\n" + INVOCATION + "\n" in sec
    settings = (REPO_ROOT / "core/companion/.claude/settings.json").read_text()
    assert '"Bash(python3 sysop/scripts/clone_sync.py:*)"' in settings
    assert not re.search(r"\$\d", _heredoc()), "a bare $<N> is rewritten before bash sees it (#360)"


def test_the_reject_remedy_no_longer_fetches_from_origin():
    text = text_of(CLOSE)
    assert "push it, bring this repository's `<branch>` to that commit" not in text
    assert "then re-run the close; Step 1-pre brings the commit across." in text


# ── the decided text ──────────────────────────────────────────────────────────

from test_fix_in_branch_tier import _pin_hash, _pin_norm, _pin_program  # noqa: E402

PINS = {"1-pre": "f5018a1c56fa22b4",  # Phase 393: `begin` left the section for its own, ahead of the flag sections; Phase 390: begin names 4a-append and 4a-fix, and the close id is written at 4a and 4a-fix; Phase 386: the section plus clone_sync.py; Phase 387's round: appended fenced, so its indentation counts (Phase 380: dict(...) env-strip); Phase 388: + the `close_arms.py begin` paragraph, Phase 355's text unchanged
         "2a step 0a": "389c3c0fb0b60907"}
# Regenerate with:  .venv/bin/python3 -c "import sys; sys.path.insert(0,'tests'); import test_review_close_clone_sync as T; T._print_pins()"


def _pinned(label: str) -> str:
    # Since Phase 386 the decided program is a shipped script, so 1-pre's pin covers both.
    return {"1-pre": lambda: _section() + _pin_program(SCRIPT.read_text()), "2a step 0a": _step_0a}[label]()


def _print_pins() -> None:
    for label in PINS:
        print(f'    "{label}": "{_pin_hash(_pinned(label))}",')


@pytest.mark.parametrize("label", sorted(PINS))
def test_the_decided_text_is_pinned(label):
    sec = _pinned(label)
    assert len(_pin_norm(sec)) > 400
    got = _pin_hash(sec)
    assert got == PINS[label], (
        f"{label} changed (hash {got}, pinned {PINS[label]}). Phase 355 decided this text on "
        "Wade's answers of 2026-10-04; move the pin in the commit that edits it.")
