"""`batch_work.sh`: a re-attach over an uncommitted claim flip, a symlinked
tracker, and a release of a worktree the batch never made.

Each test calls the real script on a fixture repo and asserts on what it did:
exit code, the tracker on disk and at HEAD, the lock, the worktree.

* **An uncommitted claim flip (`Q-715`).** A signal while the claim commit runs
  (a pre-commit hook still going, then Ctrl-C or a closed terminal) leaves
  `review_tasks.md` flipped to `In Progress` on disk, HEAD at `Pending`, and the
  lock and worktree beside it. A re-run read `In Progress`, "resumed" at exit 0,
  and never committed the flip. The re-attach now refuses and prints the two
  ways out — commit the flip, or restore the file and `--release` — and each is
  exercised here. The signal is sent by the hook itself to its own process
  group, so the state is reached deterministically rather than by timing.
* **A symlinked tracker (`Q-389`).** Both rewrites install their result with
  `mv` over the path, which replaced a tracked symlink with a regular file and
  committed the type change at exit 0. Both now refuse before writing anything.
* **A release of a foreign worktree (`Q-390`).** `--release` removes whatever
  worktree holds the batch branch. It now removes one only at the advertised
  path or the lock's `workspace:`, and anywhere else needs `--force`.
* **An out-of-range batch number.** No `10#` arithmetic touches the operand, so
  a 20-digit number is "not found" rather than wrapped — pinned, not changed.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
SCRIPT = SCRIPTS / "batch_work.sh"

TWO_PENDING = (
    "# Review Tasks\n\n"
    "### Batch 1 — One `Pending`\n\n> **Branch:** `feat/one`\n\n- [ ] a\n\n"
    "### Batch 2 — Two `Pending`\n\n> **Branch:** `feat/two`\n\n- [ ] b\n"
)


def _git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(cwd), check=check,
                          capture_output=True, text=True)


def _repo(root, tasks=TWO_PENDING, tracker_at="review_tasks.md"):
    root.mkdir(parents=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        _git(root, "config", k, v)
    real = root / tracker_at
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_text(tasks)
    if tracker_at != "review_tasks.md":
        os.symlink(tracker_at, root / "review_tasks.md")
    sd = root / "sysop" / "scripts"
    sd.mkdir(parents=True)
    for name in ("review_index.py", "_log.py"):
        shutil.copy(SCRIPTS / name, sd / name)
    (root / ".gitignore").write_text("sysop/runtime/\n.claude/\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _bw(repo, *args, prefix="bw", session=False):
    env = dict(os.environ)
    env.pop("WORKTREE_ROOT", None)
    if prefix is None:
        env.pop("WORKTREE_PREFIX", None)
    else:
        env["WORKTREE_PREFIX"] = prefix
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=str(repo),
                          capture_output=True, text=True, env=env,
                          start_new_session=session)


def _status(text, n):
    for line in text.splitlines():
        if line.startswith(f"### Batch {n} "):
            return line.rsplit("`", 2)[1]
    return None


def _disk(repo, n):
    return _status((repo / "review_tasks.md").read_text(), n)


def _head(repo, n):
    return _status(_git(repo, "show", "HEAD:review_tasks.md").stdout, n)


def _lock(repo, n):
    return repo / "sysop" / "runtime" / "locks" / f"BATCH-{n}.lock"


def _worktrees(repo):
    return [l for l in _git(repo, "worktree", "list", "--porcelain").stdout.splitlines()
            if l.startswith("worktree ")]


def _branches(repo):
    return _git(repo, "branch", "--format=%(refname:short)").stdout.split()


def _interrupted_claim(repo, signame):
    """Claim batch 1 with a pre-commit hook that signals its own process group."""
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\nkill -{signame} 0\nsleep 5\nexit 1\n")
    hook.chmod(0o755)
    r = _bw(repo, "1", session=True)
    hook.unlink()
    return r


# ══════════════════════════════════════════════════════════════════════
# An uncommitted claim flip
# ══════════════════════════════════════════════════════════════════════


class TestAnUncommittedClaimFlip:

    @pytest.mark.parametrize("signame", ["INT", "HUP"])
    def test_the_signal_leaves_the_flip_uncommitted(self, tmp_path, signame):
        """The state the refusal is for, reached as the filing reached it."""
        repo = _repo(tmp_path / "proj")
        r = _interrupted_claim(repo, signame)
        assert r.returncode != 0, r.stdout + r.stderr
        assert _disk(repo, 1) == "In Progress"
        assert _head(repo, 1) == "Pending"
        assert _lock(repo, 1).is_file()
        assert (tmp_path / "bw-batch-1").is_dir()

    @pytest.mark.parametrize("signame", ["INT", "HUP"])
    def test_a_rerun_refuses_and_names_both_ways_out(self, tmp_path, signame):
        repo = _repo(tmp_path / "proj")
        _interrupted_claim(repo, signame)
        stamp = _lock(repo, 1).read_text()
        wts, brs, tip = _worktrees(repo), _branches(repo), _git(repo, "rev-parse", "HEAD").stdout

        r = _bw(repo, "1")

        assert r.returncode == 1, (
            "a re-run over an uncommitted flip 'resumed' — nothing on that path "
            "commits the flip, so HEAD never holds the claim\n" + r.stdout + r.stderr
        )
        assert "never committed" in r.stderr
        assert "commit -m 'docs: claim Batch 1' -- review_tasks.md" in r.stderr
        assert ("checkout -- review_tasks.md && git -C " in r.stderr
                and "diff --quiet HEAD -- review_tasks.md && bash " in r.stderr
                and "/sysop/scripts/batch_work.sh --release 1" in r.stderr)
        # Absolute: run from a subdirectory or the batch worktree, a relative
        # script path restored the file and then failed, stranding the lock.
        assert "&& bash sysop/scripts/batch_work.sh" not in r.stderr
        assert "worktree at" in r.stderr and "stay" in r.stderr
        assert "--release 1" in r.stderr
        assert "resuming" not in r.stdout, "a resume banner above a refusal"
        # Nothing written: no second lock, branch or worktree, no commit.
        assert _lock(repo, 1).read_text() == stamp
        assert _worktrees(repo) == wts
        assert _branches(repo) == brs
        assert _git(repo, "rev-parse", "HEAD").stdout == tip
        assert _disk(repo, 1) == "In Progress" and _head(repo, 1) == "Pending"

    def test_way_out_one_commit_the_flip_then_resume(self, tmp_path):
        repo = _repo(tmp_path / "proj")
        _interrupted_claim(repo, "INT")
        _git(repo, "commit", "-qm", "docs: claim Batch 1", "--", "review_tasks.md")

        r = _bw(repo, "1")

        assert r.returncode == 0, r.stderr
        assert "already claimed — resuming" in r.stdout
        assert _head(repo, 1) == "In Progress"

    def test_way_out_two_restore_release_and_reclaim(self, tmp_path):
        repo = _repo(tmp_path / "proj")
        _interrupted_claim(repo, "INT")
        _git(repo, "checkout", "--", "review_tasks.md")

        rel = _bw(repo, "--release", "1")
        assert rel.returncode == 0, rel.stderr
        assert not _lock(repo, 1).exists()

        r = _bw(repo, "1")
        assert r.returncode == 0, r.stderr
        assert "Claimed Batch 1 on main" in r.stdout
        assert _head(repo, 1) == "In Progress"
        assert _lock(repo, 1).is_file()

    def test_a_committed_claim_with_another_rows_edit_still_resumes(self, tmp_path):
        """Boundary: the refusal is about THIS batch's flip, not a dirty file."""
        repo = _repo(tmp_path / "proj")
        assert _bw(repo, "1").returncode == 0
        tracker = repo / "review_tasks.md"
        tracker.write_text(tracker.read_text().replace("- [ ] b", "- [ ] b (edited)"))

        r = _bw(repo, "1")

        assert r.returncode == 0, r.stderr
        assert "already claimed — resuming" in r.stdout

    def test_another_batchs_uncommitted_flip_does_not_block_this_one(self, tmp_path):
        """Boundary: batch 2 hand-flipped and uncommitted; batch 1 is committed."""
        repo = _repo(tmp_path / "proj")
        assert _bw(repo, "1").returncode == 0
        tracker = repo / "review_tasks.md"
        tracker.write_text(tracker.read_text().replace(
            "### Batch 2 — Two `Pending`", "### Batch 2 — Two `In Progress`"))

        assert _bw(repo, "1").returncode == 0
        r2 = _bw(repo, "2")
        assert r2.returncode == 1, r2.stdout
        assert "never committed" in r2.stderr


# ══════════════════════════════════════════════════════════════════════
# A symlinked tracker
# ══════════════════════════════════════════════════════════════════════


class TestASymlinkedTracker:

    def test_the_claim_refuses_and_leaves_the_link(self, tmp_path):
        repo = _repo(tmp_path / "proj", tracker_at="docs/review_tasks.md")

        r = _bw(repo, "1")

        assert r.returncode == 1, (
            "the claim went through a symlinked tracker\n" + r.stdout + r.stderr)
        assert "is a symlink" in r.stderr
        assert (repo / "review_tasks.md").is_symlink()
        assert _status((repo / "docs/review_tasks.md").read_text(), 1) == "Pending"
        assert not _lock(repo, 1).exists()
        assert "feat/one" not in _branches(repo)
        assert not (tmp_path / "bw-batch-1").exists()
        assert _git(repo, "log", "-1", "--pretty=%s").stdout.strip() == "seed"

    def test_the_release_refuses_before_removing_the_worktree(self, tmp_path):
        tasks = TWO_PENDING.replace("### Batch 1 — One `Pending`",
                                    "### Batch 1 — One `In Progress`")
        repo = _repo(tmp_path / "proj", tasks=tasks, tracker_at="docs/review_tasks.md")
        _git(repo, "branch", "feat/one")
        wt = tmp_path / "bw-batch-1"
        _git(repo, "worktree", "add", str(wt), "feat/one")
        _lock(repo, 1).parent.mkdir(parents=True)
        _lock(repo, 1).write_text(f"task_id: BATCH-1\nbranch: feat/one\nworkspace: {wt}\n")

        r = _bw(repo, "--release", "1")

        assert r.returncode == 1, (
            "the release went through a symlinked tracker\n" + r.stdout + r.stderr)
        assert "is a symlink" in r.stderr
        assert (repo / "review_tasks.md").is_symlink()
        assert _status((repo / "docs/review_tasks.md").read_text(), 1) == "In Progress"
        assert wt.is_dir() and _lock(repo, 1).is_file()


# ══════════════════════════════════════════════════════════════════════
# A release of a worktree the batch never made
# ══════════════════════════════════════════════════════════════════════


class TestReleaseOnlyRemovesTheBatchsWorktree:

    def _claimed_then_moved(self, tmp_path):
        """Batch 1 claimed at bw-batch-1, then its branch checked out elsewhere."""
        repo = _repo(tmp_path / "proj")
        assert _bw(repo, "1").returncode == 0
        _git(repo, "worktree", "remove", str(tmp_path / "bw-batch-1"))
        other = tmp_path / "unrelated"
        _git(repo, "worktree", "add", str(other), "feat/one")
        # Clean on purpose: a plain `git worktree remove` takes a clean tree, so
        # nothing but the path check stands between it and the removal.
        return repo, other

    def test_a_worktree_at_an_unrelated_path_is_refused(self, tmp_path):
        repo, other = self._claimed_then_moved(tmp_path)

        r = _bw(repo, "--release", "1")

        assert r.returncode == 1, (
            "the release removed a worktree the batch never made\n" + r.stdout + r.stderr)
        assert "not where this batch's worktree is" in r.stderr
        assert "--release --force 1" in r.stderr
        assert other.is_dir() and (other / ".git").exists()
        assert _lock(repo, 1).is_file()
        assert _head(repo, 1) == "In Progress"

    def test_force_removes_it(self, tmp_path):
        repo, other = self._claimed_then_moved(tmp_path)

        r = _bw(repo, "--release", "--force", "1")

        assert r.returncode == 0, r.stderr
        assert not other.exists()
        assert _head(repo, 1) == "Pending"

    def test_detaching_it_is_the_non_destructive_way_out(self, tmp_path):
        repo, other = self._claimed_then_moved(tmp_path)
        _git(other, "checkout", "-q", "--detach")

        r = _bw(repo, "--release", "1")

        assert r.returncode == 0, r.stderr
        assert other.is_dir() and (other / ".git").exists()
        assert _head(repo, 1) == "Pending"

    def test_the_lock_workspace_covers_a_claim_under_another_prefix(self, tmp_path):
        """Boundary: a release from a shell without the claim's WORKTREE_PREFIX."""
        repo = _repo(tmp_path / "proj")
        assert _bw(repo, "1", prefix="bw").returncode == 0

        r = _bw(repo, "--release", "1", prefix=None)

        assert r.returncode == 0, r.stderr
        assert not (tmp_path / "bw-batch-1").exists()
        assert _head(repo, 1) == "Pending"

    def test_the_advertised_path_covers_a_lockless_claim(self, tmp_path):
        """Boundary: no lock (a claim from before locks shipped), same prefix."""
        repo = _repo(tmp_path / "proj")
        assert _bw(repo, "1").returncode == 0
        _lock(repo, 1).unlink()

        r = _bw(repo, "--release", "1")

        assert r.returncode == 0, r.stderr
        assert not (tmp_path / "bw-batch-1").exists()


class TestAStaleRegistrationElsewhere:
    """The round's regression: the path check ran before the stale-registration
    arm, so a release whose worktree sat elsewhere and was gone (or had lost its
    `.git`) refused, where base de-registered it and released. The check now
    applies to a live worktree only."""

    def _stale(self, tmp_path, how):
        repo = _repo(tmp_path / "proj")
        assert _bw(repo, "1").returncode == 0
        _git(repo, "worktree", "remove", str(tmp_path / "bw-batch-1"))
        other = tmp_path / "foreign"
        _git(repo, "worktree", "add", str(other), "feat/one")
        if how == "gone":
            import shutil
            shutil.rmtree(other)
        else:
            (other / ".git").unlink()
            (other / "keep.txt").write_text("keep\n")
        return repo, other

    @pytest.mark.parametrize("how", ["gone", "no-dot-git"])
    def test_it_releases_without_force(self, tmp_path, how):
        repo, other = self._stale(tmp_path, how)

        r = _bw(repo, "--release", "1")

        assert r.returncode == 0, r.stdout + r.stderr
        assert "not where this batch's worktree is" not in r.stderr
        assert _head(repo, 1) == "Pending"
        assert not _lock(repo, 1).exists()
        if how == "no-dot-git":
            assert (other / "keep.txt").read_text() == "keep\n"


# ══════════════════════════════════════════════════════════════════════
# An out-of-range batch number
# ══════════════════════════════════════════════════════════════════════


class TestAnOutOfRangeBatchNumber:

    @pytest.mark.parametrize("args", [("99999999999999999999",),
                                      ("--release", "99999999999999999999"),
                                      ("1234567890123456789",)])
    def test_it_is_refused_as_close_batch_refuses_it(self, tmp_path, args):
        """`close_batch.sh`'s bound, so a claimed batch is one it can close. The
        round measured a 19-digit `### Batch` header claimed here and refused there."""
        repo = _repo(tmp_path / "proj")

        r = _bw(repo, *args)

        assert r.returncode == 1
        assert f"Batch number out of range: {args[-1]}" in r.stderr, r.stderr
        assert not (repo / "sysop" / "runtime" / "locks").exists() or \
            not any((repo / "sysop" / "runtime" / "locks").iterdir())
        assert _git(repo, "log", "-1", "--pretty=%s").stdout.strip() == "seed"
