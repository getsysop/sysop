"""Integration tests for core/companion/scripts/claim_task.sh (Phase 84).

`claim_task.sh` creates an isolated workspace (worktree / branch / clone) for a
task and optionally writes a `.locks/<TASK_ID>.lock`. These tests drive the
real script against scratch git repos and lock: the arg/flag guards (which fire
before the git check), the already-locked refusal (never overwrite a live
lock), the lock-body schema (a populated `expires:` — the anti-malformed-lock
invariant), the `--branch` and default worktree happy paths, and the Phase-32
canonical-lock-location invariant (a lock created from inside a worktree lands
under the *main* repo's `.locks/`, resolved via `git rev-parse --git-common-dir`).
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core/companion/scripts/claim_task.sh"
VALIDATE = REPO_ROOT / "core/companion/scripts/validate_tasks.py"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root, commit=True):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")  # ignore a contributor's global signing
    if commit:
        (root / "README.md").write_text("# seed\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", "seed")
    return root


def _run(cwd, *args, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True, env=e,
    )


def _py3_bin(tmp_path):
    """A bin dir whose `python3` is this test's interpreter — guaranteed PyYAML.

    `claim_task.sh --release` invokes bare `python3` for the index.yml flip; the
    system `python3` on PATH may or may not carry PyYAML, so we pin it to
    `sys.executable` (the pytest interpreter, which has PyYAML — the rest of the
    suite needs it) to make the happy-path flip deterministic across machines.
    """
    b = tmp_path / "pybin"
    b.mkdir(exist_ok=True)
    shim = b / "python3"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    shim.chmod(0o755)
    return b


def _no_yaml_py3_bin(tmp_path):
    """A bin dir whose `python3` always fails — forces the pre-flight degradation
    (the `python3 -c "import yaml"` probe returns non-zero)."""
    b = tmp_path / "pybad"
    b.mkdir(exist_ok=True)
    shim = b / "python3"
    shim.write_text("#!/bin/sh\nexit 1\n")
    shim.chmod(0o755)
    return b


def _path_env(py_bin):
    """PATH with *py_bin* prepended so the subprocess `python3` resolves there."""
    return {"PATH": f"{py_bin}:{os.environ['PATH']}"}


# A schema-valid single-task index whose only task is in_progress — round-trips
# to a *validator-consistent* open state after --release (no lock/status desync).
_VALID_INDEX_INPROGRESS = """\
schema_version: 1

phases:
  - number: 1
    title: "Active phase"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-LOCKED
    title: "Task currently in progress"
    phase: 1
    status: in_progress
    effort: Medium
    user_action: false
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-LOCKED.md
"""


class TestRelease:
    """`--release` reverses a claim: worktree removal + index.yml status flip
    (in_progress → open, PyYAML round-trip) + lock release, ordered so any early
    exit leaves a validator-consistent state."""

    def _setup_claimed(self, tmp_path, status="in_progress"):
        """A repo with FEAT-X claimed: index at *status*, plus a real lock +
        worktree from the claim script (which is pure bash — needs no python)."""
        repo = _repo(tmp_path / "repo")
        tasks = repo / "tasks"
        tasks.mkdir()
        (tasks / "index.yml").write_text(
            "schema_version: 1\ntasks:\n"
            f"  - id: FEAT-X\n    status: {status}\n",
            encoding="utf-8",
        )
        r = _run(repo, "--lock", "FEAT-X", "feat/x", env={"WORKTREE_PREFIX": "wt"})
        assert r.returncode == 0, r.stderr
        assert (tmp_path / "wt-feat-x").is_dir()
        assert (repo / ".locks" / "FEAT-X.lock").is_file()
        return repo

    def test_full_reversal(self, tmp_path):
        py = _py3_bin(tmp_path)
        repo = self._setup_claimed(tmp_path)
        wt = tmp_path / "wt-feat-x"
        r = _run(repo, "--release", "FEAT-X", env=_path_env(py))
        assert r.returncode == 0, r.stderr + r.stdout
        assert not wt.exists(), "worktree not removed"
        assert not (repo / ".locks" / "FEAT-X.lock").exists(), "lock not removed"
        idx = (repo / "tasks" / "index.yml").read_text()
        assert "status: open" in idx
        assert "in_progress" not in idx
        # Branch is kept by default (a claim leaves it; so does un-claim).
        _git(repo, "show-ref", "--verify", "refs/heads/feat/x")

    def test_delete_branch_flag(self, tmp_path):
        py = _py3_bin(tmp_path)
        repo = self._setup_claimed(tmp_path)
        r = _run(repo, "--release", "--delete-branch", "FEAT-X", env=_path_env(py))
        assert r.returncode == 0, r.stderr
        got = subprocess.run(["git", "show-ref", "--verify", "refs/heads/feat/x"],
                             cwd=str(repo), capture_output=True)
        assert got.returncode != 0, "branch should be deleted with --delete-branch"

    def test_unlocked_task_refuses_and_mutates_nothing(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        tasks = repo / "tasks"
        tasks.mkdir()
        (tasks / "index.yml").write_text(
            "schema_version: 1\ntasks:\n  - id: FEAT-X\n    status: open\n")
        # No lock exists → refuses before any python (no PATH shim needed).
        r = _run(repo, "--release", "FEAT-X")
        assert r.returncode == 1
        assert "not locked" in r.stderr
        assert "status: open" in (tasks / "index.yml").read_text()

    def test_never_removes_main_worktree(self, tmp_path):
        # Crown-jewel safety (mirrors cleanup_worktrees.sh, Phase 84): a lock
        # whose recorded workspace IS the main repo must not delete it — but the
        # lock + status are still cleaned up.
        py = _py3_bin(tmp_path)
        repo = _repo(tmp_path / "repo")
        tasks = repo / "tasks"
        tasks.mkdir()
        (tasks / "index.yml").write_text(
            "schema_version: 1\ntasks:\n  - id: FEAT-X\n    status: in_progress\n")
        locks = repo / ".locks"
        locks.mkdir()
        (locks / "FEAT-X.lock").write_text(
            f"task_id: FEAT-X\nstatus: in_progress\nbranch: feat/x\nworkspace: {repo}\n")
        r = _run(repo, "--release", "FEAT-X", env=_path_env(py))
        assert r.returncode == 0, r.stderr
        assert "refusing to remove" in r.stdout
        assert (repo / "README.md").exists(), "main worktree was damaged"
        assert not (locks / "FEAT-X.lock").exists(), "lock should still be released"
        assert "status: open" in (tasks / "index.yml").read_text()

    def test_dirty_worktree_aborts_intact_then_force_succeeds(self, tmp_path):
        py = _py3_bin(tmp_path)
        repo = self._setup_claimed(tmp_path)
        wt = tmp_path / "wt-feat-x"
        (wt / "README.md").write_text("uncommitted change\n")  # dirty a tracked file
        # Without --force: git refuses; the whole claim must survive untouched.
        r = _run(repo, "--release", "FEAT-X", env=_path_env(py))
        assert r.returncode == 1
        assert wt.is_dir(), "worktree removed despite dirty state"
        assert (repo / ".locks" / "FEAT-X.lock").is_file(), "lock cleared on abort"
        assert "status: in_progress" in (repo / "tasks" / "index.yml").read_text()
        # With --force: the reversal completes.
        r2 = _run(repo, "--release", "--force", "FEAT-X", env=_path_env(py))
        assert r2.returncode == 0, r2.stderr
        assert not wt.exists()
        assert not (repo / ".locks" / "FEAT-X.lock").exists()
        assert "status: open" in (repo / "tasks" / "index.yml").read_text()

    def test_refuses_when_run_from_inside_the_worktree(self, tmp_path):
        py = _py3_bin(tmp_path)
        repo = self._setup_claimed(tmp_path)
        wt = tmp_path / "wt-feat-x"
        r = _run(wt, "--release", "FEAT-X", env=_path_env(py))  # cwd = the worktree
        assert r.returncode == 1
        assert "inside the worktree" in r.stderr
        assert wt.is_dir(), "worktree removed from under the caller"
        assert (repo / ".locks" / "FEAT-X.lock").is_file()
        assert "status: in_progress" in (repo / "tasks" / "index.yml").read_text()

    def test_no_pyyaml_degrades_without_mutating(self, tmp_path):
        # index.yml present but python3 can't import yaml → print the manual
        # reversal and touch nothing (removing the lock alone would desync).
        repo = self._setup_claimed(tmp_path)
        wt = tmp_path / "wt-feat-x"
        bad = _no_yaml_py3_bin(tmp_path)
        r = _run(repo, "--release", "FEAT-X", env=_path_env(bad))
        assert r.returncode == 1
        assert "PyYAML" in r.stderr
        assert wt.is_dir()
        assert (repo / ".locks" / "FEAT-X.lock").is_file()
        assert "status: in_progress" in (repo / "tasks" / "index.yml").read_text()

    def test_no_index_still_releases_worktree_and_lock(self, tmp_path):
        # A lock/branch-only claim, or a consumer with no queue: no flip to do,
        # but the worktree + lock are still released.
        py = _py3_bin(tmp_path)
        repo = _repo(tmp_path / "repo")
        r0 = _run(repo, "--lock", "FEAT-X", "feat/x", env={"WORKTREE_PREFIX": "wt"})
        assert r0.returncode == 0, r0.stderr
        wt = tmp_path / "wt-feat-x"
        r = _run(repo, "--release", "FEAT-X", env=_path_env(py))
        assert r.returncode == 0, r.stderr
        assert not wt.exists()
        assert not (repo / ".locks" / "FEAT-X.lock").exists()

    def test_already_open_clears_stale_lock(self, tmp_path):
        # index says open but a lock lingers (a stale claim): --release clears it.
        py = _py3_bin(tmp_path)
        repo = _repo(tmp_path / "repo")
        tasks = repo / "tasks"
        tasks.mkdir()
        (tasks / "index.yml").write_text(
            "schema_version: 1\ntasks:\n  - id: FEAT-X\n    status: open\n")
        locks = repo / ".locks"
        locks.mkdir()
        (locks / "FEAT-X.lock").write_text(
            "task_id: FEAT-X\nstatus: in_progress\nbranch: feat/x\nworkspace: \n")
        r = _run(repo, "--release", "FEAT-X", env=_path_env(py))
        assert r.returncode == 0, r.stderr
        assert "already open" in r.stdout
        assert not (locks / "FEAT-X.lock").exists(), "stale lock not cleared"

    def test_does_not_clobber_done_task(self, tmp_path):
        # Data-integrity guard: a lock lingering on a completed task is cleared,
        # but the task must NOT be revived to open. A future refactor of the flip
        # to an unconditional t["status"]="open" would revive done work — this
        # test reddens on that regression.
        py = _py3_bin(tmp_path)
        repo = _repo(tmp_path / "repo")
        tasks = repo / "tasks"
        tasks.mkdir()
        (tasks / "index.yml").write_text(
            "schema_version: 1\ntasks:\n  - id: FEAT-X\n    status: done\n")
        locks = repo / ".locks"
        locks.mkdir()
        (locks / "FEAT-X.lock").write_text(
            "task_id: FEAT-X\nstatus: in_progress\nbranch: feat/x\nworkspace: \n")
        r = _run(repo, "--release", "FEAT-X", env=_path_env(py))
        assert r.returncode == 0, r.stderr
        assert "not in_progress" in r.stdout
        assert "status: done" in (tasks / "index.yml").read_text(), "done task was clobbered"
        assert not (locks / "FEAT-X.lock").exists(), "stale lock not cleared"

    def test_task_not_in_index_still_clears_lock(self, tmp_path):
        py = _py3_bin(tmp_path)
        repo = _repo(tmp_path / "repo")
        tasks = repo / "tasks"
        tasks.mkdir()
        (tasks / "index.yml").write_text(
            "schema_version: 1\ntasks:\n  - id: OTHER\n    status: open\n")
        locks = repo / ".locks"
        locks.mkdir()
        (locks / "FEAT-X.lock").write_text(
            "task_id: FEAT-X\nstatus: in_progress\nbranch: feat/x\nworkspace: \n")
        r = _run(repo, "--release", "FEAT-X", env=_path_env(py))
        assert r.returncode == 0, r.stderr
        assert "not found" in r.stdout
        assert not (locks / "FEAT-X.lock").exists()

    def test_trailing_flag_after_id_errors_and_mutates_nothing(self, tmp_path):
        repo = self._setup_claimed(tmp_path)
        r = _run(repo, "--release", "FEAT-X", "--force")  # flag AFTER the id
        assert r.returncode == 1
        assert "before <TASK_ID>" in r.stderr
        assert (tmp_path / "wt-feat-x").is_dir(), "worktree touched despite the guard"
        assert (repo / ".locks" / "FEAT-X.lock").is_file()

    def test_leaves_validator_consistent_state(self, tmp_path):
        # The core no-desync proof: after --release, validate_tasks.py is clean.
        py = _py3_bin(tmp_path)
        repo = _repo(tmp_path / "repo")
        tasks = repo / "tasks"
        (tasks / "open").mkdir(parents=True)
        (tasks / "index.yml").write_text(_VALID_INDEX_INPROGRESS, encoding="utf-8")
        (tasks / "open" / "FEAT-LOCKED.md").write_text(
            "# FEAT-LOCKED\n\n## Context\nx\n", encoding="utf-8")
        (repo / "scripts").mkdir(exist_ok=True)
        shutil.copy(VALIDATE, repo / "scripts" / "validate_tasks.py")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "tasks")
        r0 = _run(repo, "--lock", "FEAT-LOCKED", "feat/locked", env={"WORKTREE_PREFIX": "wt"})
        assert r0.returncode == 0, r0.stderr
        r = _run(repo, "--release", "FEAT-LOCKED", env=_path_env(py))
        assert r.returncode == 0, r.stderr + r.stdout
        assert "Queue validates." in r.stdout, r.stdout


class TestArgGuards:
    """Flag/arg validation precedes the git-repo check — needs no repo."""

    def test_unknown_flag_exits_1(self, tmp_path):
        r = _run(tmp_path, "--bogus", "T-1", "feat/x")
        assert r.returncode == 1
        assert "Unknown flag: --bogus" in r.stderr

    def test_no_args_prints_usage_exits_1(self, tmp_path):
        r = _run(tmp_path)
        assert r.returncode == 1
        assert "Usage: claim_task.sh" in r.stderr

    def test_missing_branch_name_exits_1(self, tmp_path):
        r = _run(tmp_path, "T-1")
        assert r.returncode == 1
        assert "Usage: claim_task.sh" in r.stderr

    def test_not_a_git_repo_exits_1(self, tmp_path):
        # Args present, but cwd is not a git repo.
        non_git = tmp_path / "plain"
        non_git.mkdir()
        r = _run(non_git, "T-1", "feat/x")
        assert r.returncode == 1
        assert "Not inside a git repository" in r.stderr


class TestLockRefusal:
    def test_already_locked_refuses(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        locks = repo / ".locks"
        locks.mkdir()
        (locks / "T-1.lock").write_text(
            "task_id: T-1\nstatus: in_progress\nagent: someone-else\nbranch: feat/held\n"
        )
        r = _run(repo, "--lock", "T-1", "feat/x")
        assert r.returncode == 1
        assert "Task T-1 is already locked" in r.stdout
        # The existing lock body is echoed so the operator sees who holds it.
        assert "agent: someone-else" in r.stdout
        # No branch was created — the refusal fires before any mutation.
        got = subprocess.run(["git", "show-ref", "--verify", "refs/heads/feat/x"],
                             cwd=str(repo), capture_output=True)
        assert got.returncode != 0, "branch was created despite the lock refusal"


class TestBranchMode:
    def test_branch_mode_creates_branch_and_warns(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "--branch", "T-1", "feat/x", "Agent-7")
        assert r.returncode == 0, r.stderr
        assert "Created branch 'feat/x'" in r.stdout
        assert "no filesystem isolation" in r.stdout
        _git(repo, "show-ref", "--verify", "refs/heads/feat/x")  # raises if absent

    def test_existing_branch_is_idempotent(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        _git(repo, "branch", "feat/x")
        r = _run(repo, "--branch", "T-1", "feat/x")
        assert r.returncode == 0, r.stderr
        assert "already exists" in r.stdout


class TestLockSchema:
    def test_lock_body_has_populated_expires(self, tmp_path):
        # --branch --lock writes a lock without a worktree (the cheap seam).
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "--branch", "--lock", "T-1", "feat/x", "Agent-7")
        assert r.returncode == 0, r.stderr
        lock = (repo / ".locks" / "T-1.lock").read_text()
        assert "status: in_progress" in lock
        assert "agent: Agent-7" in lock
        assert "branch: feat/x" in lock
        assert "mode: branch" in lock
        # The anti-malformed-lock invariant: expires is a real ISO-8601 stamp,
        # never blank (downstream validators treat a blank expires as malformed).
        m = re.search(r"^expires: (.+)$", lock, re.MULTILINE)
        assert m, "no expires line"
        assert re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", m.group(1)), \
            f"expires not ISO-8601: {m.group(1)!r}"


class TestWorktreeMode:
    def test_default_worktree_mode_creates_worktree(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "T-2", "feat/y", env={"WORKTREE_PREFIX": "wt"})
        assert r.returncode == 0, r.stderr
        assert "Created worktree" in r.stdout
        wt = tmp_path / "wt-t-2"  # ../<prefix>-<task-lowercased>
        assert wt.is_dir(), f"worktree not created at {wt}"
        head = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"],
                              cwd=str(wt), capture_output=True, text=True)
        assert head.stdout.strip() == "feat/y"

    def test_lock_from_worktree_lands_in_main_repo(self, tmp_path):
        # Phase 32 canonical-location invariant: a lock created while cwd is a
        # linked worktree resolves .locks/ under the MAIN repo via
        # git-common-dir — not under the worktree.
        main = _repo(tmp_path / "main")
        wt = tmp_path / "wt"
        _git(main, "worktree", "add", "-q", "-b", "feat/w", str(wt))
        r = _run(wt, "--branch", "--lock", "T-3", "feat/z")
        assert r.returncode == 0, r.stderr
        assert (main / ".locks" / "T-3.lock").is_file(), "lock did not land in main repo"
        assert not (wt / ".locks" / "T-3.lock").exists(), "lock leaked into the worktree"
