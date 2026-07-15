"""Integration tests for core/companion/scripts/batch_work.sh (Phase 84).

`batch_work.sh` lists review batches and creates an isolated worktree for one.
With NO scripts/review_index.py present these tests exercise the inline
`_parse_batches_fallback` bash regex (the fragile code) directly. They lock:
the guard ordering (review_tasks.md before arg handling), the arg guards
(missing / non-integer / not-found / no-Branch-metadata), the `--list` /
`--list-all` parse + Complete-filtering, and the auto-build graceful skip when
off `main` (which must not abort — the worktree is still created).
"""
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core/companion/scripts/batch_work.sh"

# em-dash header + `> **Branch:**` metadata line — the shape the fallback
# parser's regexes require.
TWO_BATCHES = """\
# Review Tasks

### Batch 1 — First batch `Pending`

> **Branch:** `feat/one`

- [ ] a

### Batch 2 — Second batch `Complete`

> **Branch:** `feat/two`

- [x] b
"""


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root, tasks: "str | None" = TWO_BATCHES):
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


def _run(cwd, *args, env=None):
    import os
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True, env=e,
    )


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

    def test_missing_batch_number_exits_1(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo)
        assert r.returncode == 1
        assert "Usage: batch_work.sh" in r.stderr

    def test_non_integer_batch_exits_1(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "abc")
        assert r.returncode == 1
        assert "must be a positive integer" in r.stderr

    def test_batch_not_found_exits_1(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "99")
        assert r.returncode == 1
        assert "Batch 99 not found" in r.stderr

    def test_no_branch_metadata_exits_1(self, tmp_path):
        tasks = "# Review Tasks\n\n### Batch 3 — No branch batch `Pending`\n\n- [ ] x\n"
        repo = _repo(tmp_path / "repo", tasks=tasks)
        r = _run(repo, "3")
        assert r.returncode == 1
        assert "has no Branch: metadata" in r.stderr


class TestList:
    def test_list_shows_pending_hides_complete(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "--list")
        assert r.returncode == 0, r.stderr
        assert "First batch" in r.stdout       # Pending → shown
        assert "Second batch" not in r.stdout  # Complete → hidden

    def test_list_all_shows_complete_too(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "--list-all")
        assert r.returncode == 0, r.stderr
        assert "First batch" in r.stdout
        assert "Second batch" in r.stdout
        assert "Complete" in r.stdout

    def test_list_empty_when_only_complete(self, tmp_path):
        tasks = (
            "# Review Tasks\n\n"
            "### Batch 9 — Done batch `Complete`\n\n"
            "> **Branch:** `feat/done`\n\n"
            "- [x] x\n"
        )
        repo = _repo(tmp_path / "repo", tasks=tasks)
        r = _run(repo, "--list")
        assert r.returncode == 0, r.stderr
        assert "No batches found" in r.stdout


class TestClaimOnMain:
    def test_claims_pending_batch_on_main_and_commits(self, tmp_path):
        # The auto-build happy path: on main + clean review_tasks.md + a
        # reachable origin, a Pending batch is marked In Progress and committed
        # before the worktree is created. The batch here is the file's LAST
        # section (no trailing `##`), so this also locks the L182 grep guard —
        # without it, claim_batch aborts (set -e) before claiming.
        tasks = (
            "# Review Tasks\n\n"
            "### Batch 1 — Only batch `Pending`\n\n"
            "> **Branch:** `feat/one`\n\n"
            "- [ ] a\n"
        )
        repo = _repo(tmp_path / "repo", tasks=tasks)
        bare = tmp_path / "origin.git"
        subprocess.run(["git", "init", "--bare", "-q", str(bare)],
                       check=True, capture_output=True)
        _git(repo, "remote", "add", "origin", str(bare))
        _git(repo, "push", "-q", "origin", "main")
        r = _run(repo, "1", env={"WORKTREE_PREFIX": "bw"})
        assert r.returncode == 0, r.stderr
        assert "Claimed Batch 1 on main" in r.stdout
        # The claim was committed on main…
        subj = subprocess.run(["git", "log", "-1", "--pretty=%s"], cwd=str(repo),
                              capture_output=True, text=True).stdout.strip()
        assert subj == "docs: claim Batch 1"
        # …the batch flipped Pending → In Progress…
        assert "`In Progress`" in (repo / "review_tasks.md").read_text()
        # …and the worktree was still created.
        assert (tmp_path / "bw-batch-1").is_dir()

    def test_dirty_review_tasks_skips_claim(self, tmp_path):
        # Same on-main + reachable-origin setup as the happy path, but with an
        # *unstaged* edit to review_tasks.md → the claim is skipped (no commit,
        # status stays Pending) while the worktree is still created. Unstaged
        # (not staged) so removing the leading `!` from the guard's first clause
        # is the clean mutation that reddens this.
        tasks = (
            "# Review Tasks\n\n"
            "### Batch 1 — Only batch `Pending`\n\n"
            "> **Branch:** `feat/one`\n\n"
            "- [ ] a\n"
        )
        repo = _repo(tmp_path / "repo", tasks=tasks)
        bare = tmp_path / "origin.git"
        subprocess.run(["git", "init", "--bare", "-q", str(bare)],
                       check=True, capture_output=True)
        _git(repo, "remote", "add", "origin", str(bare))
        _git(repo, "push", "-q", "origin", "main")
        # Dirty review_tasks.md, unstaged.
        with open(repo / "review_tasks.md", "a") as fh:
            fh.write("\n<!-- local uncommitted edit -->\n")

        r = _run(repo, "1", env={"WORKTREE_PREFIX": "bw"})
        assert r.returncode == 0, r.stderr
        assert "review_tasks.md has uncommitted changes" in r.stderr
        # No claim commit was made…
        subj = subprocess.run(["git", "log", "-1", "--pretty=%s"], cwd=str(repo),
                              capture_output=True, text=True).stdout.strip()
        assert subj != "docs: claim Batch 1"
        assert subj == "seed"
        # …the batch stayed Pending (never flipped to In Progress)…
        body = (repo / "review_tasks.md").read_text()
        assert "`Pending`" in body
        assert "`In Progress`" not in body
        # …and the worktree was still created (the skip is graceful).
        assert (tmp_path / "bw-batch-1").is_dir()


class TestWorktreeCreation:
    def test_off_main_skips_claim_but_still_creates_worktree(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        _git(repo, "checkout", "-q", "-b", "other")  # not on main
        r = _run(repo, "1", env={"WORKTREE_PREFIX": "bw"})
        assert r.returncode == 0, r.stderr
        # Auto-build skips gracefully (never aborts) when off main — the notice
        # goes to stderr…
        assert "Not on main" in r.stderr
        assert "Skipping batch claim" in r.stderr
        # …and the worktree is still created.
        assert "Created worktree" in r.stdout
        wt = tmp_path / "bw-batch-1"
        assert wt.is_dir(), f"worktree not created at {wt}"
        head = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"],
                              cwd=str(wt), capture_output=True, text=True)
        assert head.stdout.strip() == "feat/one"
