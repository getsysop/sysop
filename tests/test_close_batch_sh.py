"""Integration tests for core/companion/scripts/close_batch.sh (Phase 84).

`close_batch.sh` marks merged review batches `Merged` in review_tasks.md and
commits. These tests drive the real script against a scratch repo with a hand-
authored review_tasks.md (and NO scripts/review_index.py, which forces the
pure-grep fallback — the more fragile code). They lock: the guard ordering
(review_tasks.md existence fires before arg parsing), the per-batch skip verdicts
(not-found / already-merged / bad-status), `--dry-run` leaving the file and git
history untouched, the real close mutation + commit, and the two BeanRider
invariants — commit-failure aborts loudly with exit 1 (ISSUE-0015) and a
missing `Grand Total` line does not abort under pipefail (ISSUE-0044).
"""
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core/companion/scripts/close_batch.sh"

# em-dash (U+2014) between number and title, backtick-quoted status at EOL —
# the exact shape close_batch.sh's status regex and range grep expect.
BASE_TASKS = """\
# Review Tasks

### Batch 1 — First batch `Pending`

- [ ] task one
- [ ] task two

### Batch 2 — Second batch `Merged`

- [x] done task

### Batch 3 — Third batch `Weird`

- [ ] task x
"""


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root, tasks: "str | None" = BASE_TASKS):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")  # ignore a contributor's global signing
    if tasks is not None:
        (root / "review_tasks.md").write_text(tasks)
    (root / "README.md").write_text("# seed\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run(cwd, *args):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True,
    )


def _head(repo):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                          capture_output=True, text=True).stdout.strip()


class TestGuards:
    def test_not_a_git_repo_exits_1(self, tmp_path):
        r = _run(tmp_path, "1")
        assert r.returncode == 1
        assert "Not inside a git repository" in r.stderr

    def test_missing_review_tasks_exits_1(self, tmp_path):
        repo = _repo(tmp_path / "repo", tasks=None)
        r = _run(repo, "1")
        assert r.returncode == 1
        assert "review_tasks.md not found" in r.stderr

    def test_unknown_argument_exits_1(self, tmp_path):
        # The review_tasks.md existence check fires BEFORE arg parsing.
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "--bogus", "1")
        assert r.returncode == 1
        assert "Unknown argument: --bogus" in r.stderr

    def test_no_batch_numbers_exits_1(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "--dry-run")
        assert r.returncode == 1
        assert "No batch numbers provided" in r.stderr


class TestSkips:
    def test_batch_not_found_skips(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "99")
        assert r.returncode == 0, r.stderr
        assert "99:not-found" in r.stdout

    def test_already_merged_skips(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "2")
        assert r.returncode == 0, r.stderr
        assert "Already Merged" in r.stdout
        assert "2:already-merged" in r.stdout

    def test_bad_status_skips(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "3")
        assert r.returncode == 0, r.stderr
        assert "Unrecognized batch status" in r.stdout
        assert "3:bad-status" in r.stdout


class TestDryRun:
    def test_dry_run_previews_without_touching_file_or_history(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        tasks_before = (repo / "review_tasks.md").read_text()
        head_before = _head(repo)
        r = _run(repo, "--dry-run", "1")
        assert r.returncode == 0, r.stderr
        assert "'Pending' → 'Merged'" in r.stdout
        assert "2 tasks → [x]" in r.stdout
        assert "(dry-run mode — no changes made)" in r.stdout
        assert "close-batch commit present: 0" in r.stdout
        # File byte-identical, no commit made.
        assert (repo / "review_tasks.md").read_text() == tasks_before
        assert _head(repo) == head_before


class TestRealClose:
    def test_real_close_mutates_and_commits(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        head_before = _head(repo)
        r = _run(repo, "1")
        assert r.returncode == 0, r.stderr
        assert "Marked as Merged (2 tasks closed)" in r.stdout
        assert "Closed: 1" in r.stdout
        assert "close-batch commit present: 1" in r.stdout
        text = (repo / "review_tasks.md").read_text()
        assert "### Batch 1 — First batch `Merged`" in text
        assert "- [x] task one" in text
        assert "- [x] task two" in text
        # Batches 2 and 3 untouched.
        assert "### Batch 3 — Third batch `Weird`" in text
        # A new commit landed with the expected subject.
        assert _head(repo) != head_before
        subj = subprocess.run(["git", "log", "-1", "--pretty=%s"], cwd=str(repo),
                              capture_output=True, text=True).stdout.strip()
        assert subj == "docs: close Batch 1"

    def test_no_tmp_residue_after_close(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        _run(repo, "1")
        assert not (repo / "review_tasks.md.tmp").exists()


class TestBranchVerification:
    def test_deleted_branch_is_assumed_merged(self, tmp_path):
        # A batch WITH branch metadata whose branch no longer exists as a local
        # or remote ref → "already deleted (assumed merged)" → proceeds.
        tasks = (
            "# Review Tasks\n\n"
            "### Batch 5 — Ghost batch `Review Ready`\n\n"
            "> **Branch:** `feat/ghost`\n\n"
            "- [ ] one task\n"
        )
        repo = _repo(tmp_path / "repo", tasks=tasks)
        r = _run(repo, "5")
        assert r.returncode == 0, r.stderr
        assert "already deleted (assumed merged)" in r.stdout
        assert "Closed: 5" in r.stdout


class TestMergeVerification:
    """A batch whose branch exists but is NOT an ancestor of main is refused
    without --force, and accepted (as a cherry-pick) with it."""

    _CHERRY = (
        "# Review Tasks\n\n"
        "### Batch 7 — Cherry batch `Review Ready`\n\n"
        "> **Branch:** `feat/cherry`\n\n"
        "- [ ] one task\n"
    )

    def _repo_with_unmerged_branch(self, tmp_path):
        repo = _repo(tmp_path / "repo", tasks=self._CHERRY)
        # feat/cherry gets a commit main doesn't have → not an ancestor of main.
        _git(repo, "checkout", "-q", "-b", "feat/cherry")
        (repo / "x.txt").write_text("x\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "cherry commit")
        _git(repo, "checkout", "-q", "main")
        return repo

    def test_unmerged_branch_skips_without_force(self, tmp_path):
        repo = self._repo_with_unmerged_branch(tmp_path)
        r = _run(repo, "7")
        assert r.returncode == 0, r.stderr
        assert "NOT merged into main" in r.stdout
        assert "7:unmerged" in r.stdout
        # Skipped → file untouched.
        assert "`Review Ready`" in (repo / "review_tasks.md").read_text()

    def test_force_accepts_unmerged_branch(self, tmp_path):
        repo = self._repo_with_unmerged_branch(tmp_path)
        r = _run(repo, "--force", "7")
        assert r.returncode == 0, r.stderr
        assert "accepting cherry-pick" in r.stdout
        assert "Closed: 7" in r.stdout
        assert "### Batch 7 — Cherry batch `Merged`" in (repo / "review_tasks.md").read_text()


class TestCommitFailureAbort:
    """BeanRider ISSUE-0015: a failing commit must abort loudly with exit 1,
    never silently proceed leaving review_tasks.md modified-but-uncommitted."""

    def test_commit_failure_exits_1(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        hooks_dir = repo / ".git" / "hooks"
        # Pin hooksPath to this repo's .git/hooks so a contributor's global
        # core.hooksPath can't neutralize the failing hook this test relies on.
        _git(repo, "config", "core.hooksPath", str(hooks_dir))
        hook = hooks_dir / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        r = _run(repo, "1")
        assert r.returncode == 1
        assert "git commit failed" in r.stderr
        assert "staged but uncommitted" in r.stderr
        # The edits are staged (present in the index) but not committed.
        staged = subprocess.run(["git", "diff", "--cached", "--name-only"],
                                cwd=str(repo), capture_output=True, text=True).stdout
        assert "review_tasks.md" in staged


class TestGrandTotal:
    def test_missing_grand_total_line_does_not_abort(self, tmp_path):
        # A Statistics block without a `Grand Total` row must not trip pipefail.
        tasks = BASE_TASKS + "\n## Statistics\n\n(no grand total row here)\n"
        repo = _repo(tmp_path / "repo", tasks=tasks)
        r = _run(repo, "1")
        assert r.returncode == 0, r.stderr
        assert "Marked as Merged" in r.stdout

    def test_grand_total_counts_are_adjusted(self, tmp_path):
        tasks = BASE_TASKS + "\n## Statistics\n\n**Grand Total** — 5 done, 10 open\n"
        repo = _repo(tmp_path / "repo", tasks=tasks)
        r = _run(repo, "1")
        assert r.returncode == 0, r.stderr
        text = (repo / "review_tasks.md").read_text()
        # 2 tasks closed → 5+2 done, 10-2 open.
        assert "7 done, 8 open" in text
