"""`/sitrep` counts a `--clone` claim's commits where they live (`Q-619`), and reads the
worktrees of the repository it was handed (`Q-119`).

`claim_task.sh --clone` creates the branch in the main checkout, pushes it and clones origin,
so the main checkout's `refs/heads/<branch>` stays at the cut point while the work lands in
the clone. The survey counted it in the main checkout, and every clone claim read `planning`,
before and after a push. These drive the real `claim_task.sh --clone --lock` and the real
survey as a subprocess.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import sitrep_survey as ss
from test_claim_clone_and_flag_order import CLAIM_TASK, _repo, _run

REPO_ROOT = Path(__file__).resolve().parents[1]
SURVEY = REPO_ROOT / "core" / "companion" / "scripts" / "sitrep_survey.py"
TASK, BRANCH = "FEAT-0001", "feat/demo"
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                          text=True, env=ENV).stdout.strip()


def _commit(where: Path, name: str, subject: str) -> str:
    (where / name).write_text(name + "\n")
    _git(where, "add", name)
    _git(where, "commit", "-qm", subject)
    return _git(where, "rev-parse", "HEAD")


def _claim(tmp_path: Path, *, unpushed_on_main: bool = True) -> tuple[Path, Path]:
    """A main checkout with a bare origin and a real `--clone --lock` claim; `(main, clone)`.

    With `unpushed_on_main`, the local default branch carries one commit origin lacks when the
    branch is cut, as a claim commit does: the branch is pushed with it, and the clone's own
    default branch never sees it."""
    main = _repo(tmp_path / "proj", task_id=TASK)
    if unpushed_on_main:
        _commit(main, "x.txt", "docs: an unpushed commit on the local default branch")
    out = _run(CLAIM_TASK, main, "--clone", "--lock", TASK, BRANCH)
    assert out.returncode == 0, out.stdout + out.stderr
    clone = main.parent / f"{main.name}-feat-0001"
    assert clone.is_dir()
    # The premise: the main checkout HAS the branch, at the cut point.
    assert _git(main, "rev-parse", f"refs/heads/{BRANCH}") == _git(main, "rev-parse", "main")
    return main, clone


def _state(main: Path) -> dict:
    r = subprocess.run([sys.executable, str(SURVEY), "--json"], cwd=str(main),
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    tasks = [t for t in json.loads(r.stdout)["tasks"] if t["task_id"] == TASK]
    assert len(tasks) == 1, r.stdout
    return {k: tasks[0][k] for k in ("state", "commits_ahead", "unpushed")}


# ── Q-619 ──────────────────────────────────────────────────────────────


def test_a_fresh_clone_claim_reads_planning(tmp_path):
    """No over-count: the unpushed commit the branch inherited from the local default branch
    is the clone's merge target's in neither repository's sense, but the main checkout's
    default branch holds it."""
    main, _clone = _claim(tmp_path)
    assert _state(main) == {"state": "planning", "commits_ahead": 0, "unpushed": 0}


def test_a_clone_claims_commits_are_counted_in_the_clone(tmp_path):
    main, clone = _claim(tmp_path)
    _commit(clone, "a.txt", "work (FEAT-0001)")
    assert _state(main) == {"state": "in progress", "commits_ahead": 1, "unpushed": 1}


def test_a_pushed_clone_claim_reads_pushed(tmp_path):
    """Pushed, and fetched into the main checkout: its local branch is still at the cut point,
    so only the clone (or the remote-tracking ref) shows the work."""
    main, clone = _claim(tmp_path)
    _commit(clone, "a.txt", "work (FEAT-0001)")
    _git(clone, "push", "-q", "origin", BRANCH)
    _git(main, "fetch", "-q", "origin")
    assert _state(main) == {"state": "in progress", "commits_ahead": 1, "unpushed": 0}


def test_with_no_local_branch_and_no_clone_the_remote_tracking_ref_is_counted(tmp_path):
    main, clone = _claim(tmp_path)
    _commit(clone, "a.txt", "work (FEAT-0001)")
    _git(clone, "push", "-q", "origin", BRANCH)
    _git(main, "fetch", "-q", "origin")
    _git(main, "branch", "-D", BRANCH)
    shutil.move(str(clone), str(tmp_path / "moved-away"))
    # Pushed by definition, so not read as "no upstream, all unpushed".
    assert _state(main) == {"state": "in progress", "commits_ahead": 1, "unpushed": 0}


def test_a_recorded_pr_head_excludes_its_commits_from_a_clone_count(tmp_path):
    """`refs/sysop/merged-pr-heads/*` exists only in the main checkout. A commit the branch
    inherited, which an earlier `pr` close squash-merged, is reachable in the main checkout
    from that close's recorded head and from neither default ref there."""
    main, _clone = _claim(tmp_path)
    inherited = _git(main, "rev-parse", "main")
    _git(main, "update-ref", "refs/sysop/merged-pr-heads/7", inherited)
    _git(main, "reset", "-q", "--hard", "origin/main")
    _commit(main, "s.txt", "squash of #7")
    _git(main, "push", "-q", "origin", "main")
    r = subprocess.run(["git", "merge-base", "--is-ancestor", inherited, "main"], cwd=str(main))
    assert r.returncode == 1, "the fixture must leave the inherited commit off the default branch"
    assert _state(main)["state"] == "planning"


def test_a_linked_worktree_is_not_counted_as_a_clone(tmp_path):
    """A linked worktree shares the main checkout's refs (and its recorded PR heads), so its
    claim stays on the main checkout's count."""
    main = _repo(tmp_path / "proj", task_id=TASK)
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "-b", BRANCH, str(wt))
    lock = ss.Lock(task_id=TASK, path=tmp_path / "x.lock", branch=BRANCH, workspace=str(wt))
    assert ss._clone_workspace(BRANCH, lock, main) is None
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(main), str(clone))
    _git(clone, "branch", BRANCH, "origin/main")
    lock.workspace = str(clone)
    assert ss._clone_workspace(BRANCH, lock, main) == clone


# ── Q-119 ──────────────────────────────────────────────────────────────


def test_read_worktrees_lists_the_repository_it_is_handed(tmp_path, monkeypatch):
    """Called in-process from inside a different repository, it listed that repository's
    worktrees and classified them against the root it was handed."""
    surveyed = _repo(tmp_path / "surveyed", origin=False)
    linked = tmp_path / "linked"
    _git(surveyed, "worktree", "add", "-q", "-b", "feat/linked", str(linked))
    elsewhere = _repo(tmp_path / "elsewhere", origin=False)
    monkeypatch.chdir(elsewhere)
    got = {(w.path.resolve(), w.branch, w.is_main) for w in ss._read_worktrees(surveyed)}
    assert got == {(surveyed.resolve(), "main", True), (linked.resolve(), "feat/linked", False)}


# ── Q-619: the clone route's edges (Phase 474's author battery) ─────────────


def test_main_prefers_its_local_branch_over_the_remote_tracking_ref(tmp_path):
    """The main route is unchanged where a local branch exists; the remote-tracking ref is a
    fallback only for a claim whose local branch is gone."""
    main, clone = _claim(tmp_path)
    _commit(clone, "a.txt", "work (FEAT-0001)")
    _git(clone, "push", "-q", "origin", BRANCH)
    _git(main, "fetch", "-q", "origin")
    assert ss._main_branch_ref(BRANCH, main) == f"refs/heads/{BRANCH}"


def test_a_clone_branch_with_no_upstream_reads_minus_one(tmp_path):
    """-1 is the caller's "no upstream: every commit ahead is unpushed" sentinel."""
    _main, clone = _claim(tmp_path)
    _commit(clone, "a.txt", "work (FEAT-0001)")
    _git(clone, "branch", "--unset-upstream", BRANCH)
    assert ss._commits_unpushed_in_clone(BRANCH, clone) == -1


def test_a_failed_liveness_read_keeps_every_commit(tmp_path, monkeypatch):
    """When git cannot say which held commits are live, none is dropped: a failure read as
    "nothing is live" would hide the claim's work."""
    main, clone = _claim(tmp_path)
    real = ss._git_lines
    calls = []

    def flaky(args, root):
        calls.append(args[0:2])
        return real(args, root) if len(calls) == 1 else None

    monkeypatch.setattr(ss, "_git_lines", flaky)
    got = ss._commits_ahead_in_clone(BRANCH, clone, main)
    assert len(calls) == 2, calls
    assert got is not None and len(got) == 1, "the inherited commit is kept when liveness fails"


def test_a_clone_without_its_remote_default_ref_still_counts(tmp_path):
    """Only the merge-target refs the clone resolves are passed to git log: one it lacks
    would make git fail, and the claim read `planning`. (A clone with no LOCAL default
    branch names no merge target at all — `default_branch.sh` refuses it, as the close
    does — and is counted in the main checkout.)"""
    main, clone = _claim(tmp_path)
    _git(clone, "update-ref", "-d", "refs/remotes/origin/main")
    _commit(clone, "a.txt", "work (FEAT-0001)")
    assert _state(main)["commits_ahead"] == 1


def test_a_workspace_that_lacks_the_branch_is_not_a_clone_route(tmp_path):
    """A lock whose workspace no longer holds the branch is counted in the main checkout."""
    main, clone = _claim(tmp_path)
    _git(clone, "checkout", "-q", "main")
    _git(clone, "branch", "-D", BRANCH)
    lock = ss.Lock(task_id=TASK, path=tmp_path / "x.lock", branch=BRANCH, workspace=str(clone))
    assert ss._clone_workspace(BRANCH, lock, main) is None


def test_a_clone_branch_whose_upstream_is_gone_reads_minus_one(tmp_path):
    """Deleted on the remote and pruned: `rev-list` against it fails, and a failed count must
    not read as "all pushed" (0). Main's `@{upstream}` fails the same way and reads -1."""
    _main, clone = _claim(tmp_path)
    _commit(clone, "a.txt", "work (FEAT-0001)")
    _git(clone, "push", "-q", "origin", BRANCH)
    _commit(clone, "b.txt", "more work (FEAT-0001)")
    _git(clone, "push", "-q", "origin", "--delete", BRANCH)
    assert ss._commits_unpushed_in_clone(BRANCH, clone) == -1


def test_a_relative_workspace_is_resolved_against_the_main_checkout(tmp_path, monkeypatch):
    """A hand-edited lock's relative `workspace:` names a path from the main checkout, wherever
    the survey runs from."""
    main, clone = _claim(tmp_path)
    rel = Path("..") / clone.name
    lock = ss.Lock(task_id=TASK, path=tmp_path / "x.lock", branch=BRANCH, workspace=str(rel))
    (main / "sub").mkdir()
    monkeypatch.chdir(main / "sub")
    assert ss._clone_workspace(BRANCH, lock, main) is not None
