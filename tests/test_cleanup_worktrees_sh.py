"""Integration tests for core/companion/scripts/cleanup_worktrees.sh (Phase 84).

The script lists git worktrees (MAIN / MERGED / ACTIVE / STALE) and, under
`--clean` / `--force`, removes non-main ones. Its whole reason for existing is
safety, so the load-bearing tests lock the guards: MAIN is *never* removed
(even under `--force`); `--clean` skips ACTIVE (dirty) worktrees and uses a
non-force `git worktree remove` so it can't destroy uncommitted work; branch
deletion is the safe `-d`. Repos are initialised with `main` as the default
branch because the MERGED classification hardcodes `main`.
"""
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core/companion/scripts/cleanup_worktrees.sh"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")  # ignore a contributor's global signing
    (root / "README.md").write_text("# seed\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _add_worktree(repo, path, branch):
    _git(repo, "worktree", "add", "-q", "-b", branch, str(path))


def _run(cwd, *args):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True,
    )


class TestGuards:
    def test_not_a_git_repo_exits_1(self, tmp_path):
        r = _run(tmp_path)
        assert r.returncode == 1
        assert "Not inside a git repository" in r.stderr

    def test_unknown_action_exits_1(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "--bogus")
        assert r.returncode == 1
        assert "Unknown action: --bogus" in r.stderr
        assert "Usage: cleanup_worktrees.sh" in r.stderr


class TestList:
    def test_list_main_only(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo)  # default action = list
        assert r.returncode == 0, r.stderr
        assert "MAIN" in r.stdout
        assert "Legend:" in r.stdout


class TestCleanNoOp:
    def test_clean_with_only_main_removes_nothing(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "--clean")
        assert r.returncode == 0, r.stderr
        assert "Removed 0 worktree(s)" in r.stdout


class TestForceNeverRemovesMain:
    """The single most important invariant: MAIN is never removed."""

    def test_force_removes_secondary_but_keeps_main(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-a"
        _add_worktree(repo, wt, "feat/a")
        assert wt.is_dir()
        r = _run(repo, "--force")
        assert r.returncode == 0, r.stderr
        # Full message incl. "0 failed" — so removing the MAIN guard (git then
        # refuses to remove the primary → FAILED=1 → "1 failed", rc 1) reddens
        # this directly, not just incidentally via rc.
        assert "Force-removed 1 worktree(s), 0 failed." in r.stdout
        assert not wt.exists(), "secondary worktree was not removed"
        # The primary worktree survives, intact.
        assert repo.is_dir() and (repo / ".git").exists()
        assert (repo / "README.md").is_file()


class TestCleanSkipsActive:
    def test_clean_skips_active_worktree(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-active"
        _add_worktree(repo, wt, "feat/active")
        (wt / "scratch.txt").write_text("uncommitted work\n")  # untracked → ACTIVE
        r = _run(repo, "--clean")
        assert r.returncode == 0, r.stderr
        assert "Skipping ACTIVE" in r.stdout
        assert "skipped 1 active" in r.stdout
        # The dirty worktree — and its uncommitted file — survive.
        assert wt.is_dir()
        assert (wt / "scratch.txt").is_file()


class TestCleanRemovesMerged:
    def test_clean_removes_merged_and_deletes_branch(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-merged"
        # A clean worktree whose branch tip == main tip → ancestor of main → MERGED.
        _add_worktree(repo, wt, "feat/merged")
        r = _run(repo, "--clean")
        assert r.returncode == 0, r.stderr
        assert "Removing MERGED" in r.stdout
        assert "Removed 1 worktree(s)" in r.stdout
        assert not wt.exists()
        # Branch deleted with safe -d (it was an ancestor of main).
        got = subprocess.run(["git", "show-ref", "--verify", "refs/heads/feat/merged"],
                             cwd=str(repo), capture_output=True)
        assert got.returncode != 0, "merged branch was not deleted"


class TestForcePreservesUnmergedBranch:
    """`--force` removes the worktree but must delete its branch with the *safe*
    `-d` (L216) — so an *unmerged* branch (commits not in main) survives rather
    than being force-dropped. The existing MERGED tests can't catch a `-d`→`-D`
    refactor because for an ancestor branch `-d` and `-D` behave identically;
    only a genuinely-unmerged branch distinguishes them. `--force` (not `--clean`)
    is the reachable path: a clean-but-unmerged worktree classifies ACTIVE and
    `--clean` skips it before the branch-delete, whereas `--force` deletes every
    non-main worktree's branch regardless of class."""

    def test_force_keeps_unmerged_branch(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-unmerged"
        _add_worktree(repo, wt, "feat/unmerged")
        # A commit *inside* the worktree puts its branch tip ahead of main → not
        # an ancestor of main → `git branch -d` refuses (not fully merged).
        (wt / "work.txt").write_text("unmerged commit\n")
        _git(wt, "add", "-A")
        _git(wt, "commit", "-qm", "unmerged work")

        r = _run(repo, "--force")
        assert r.returncode == 0, r.stderr
        assert "Force-removed 1 worktree(s), 0 failed." in r.stdout
        assert not wt.exists(), "worktree was not removed"
        assert "not deleted (not fully merged)" in r.stdout
        # Load-bearing: the unmerged branch — and its commit — survive.
        # `-d`→`-D` at L216 would force-delete it and redden this.
        got = subprocess.run(["git", "show-ref", "--verify", "refs/heads/feat/unmerged"],
                             cwd=str(repo), capture_output=True)
        assert got.returncode == 0, "unmerged branch was force-deleted — commits lost"
