"""`/review-close` Step 6 releases the batch locks Step 4b kept under `pr` policy (`Q-749`).

Under `pr` policy Step 4b runs `close_batch.sh` on the merge target, not on the default
branch in the main checkout, so the script keeps each batch's `BATCH-<N>.lock`, park
marker and claim directory (the deferral is deliberate: releasing before the PR merges
would let `/next-task` re-offer the batch). Nothing ran the release afterwards: `--land`'s
`landed` removes only the kept roadmap locks, and a later close passes only the batches it
merged. `steps/6-pr-gate.md` now re-runs `close_batch.sh` from the default branch once the
re-sync holds the merge, passing only batches the tracker there reads `Merged`.

1. Behaviour: the deferral in both Step 4-pre shapes, the squash, then the re-run from the
   default branch with the batch branches already deleted.
2. Why the step filters on `Merged` first: a batch the default branch still reads
   `Pending` whose branch is gone is flipped and committed by the same command.
3. The step text: the read, the filter, the order after the re-sync, the commit check,
   and the `--land` carrier.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _prose_guard_helpers import normalize  # noqa: E402
from skill_runner_text import text_of  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
CLOSE_BATCH = REPO_ROOT / "core/companion/scripts/close_batch.sh"
SKILL = REPO_ROOT / "core/skills/review-close/SKILL.md"
GATE = REPO_ROOT / "core/skills/review-close/steps/6-pr-gate.md"
LAND = REPO_ROOT / "core/skills/review-close/steps/request-review-land.md"

TRACKER = """\
# Review Tasks

### Batch 1 — First batch `Pending`
> **Branch:** `batch/1`

- [ ] task one
"""


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True).stdout.strip()


def _repo(root: Path) -> Path:
    root.mkdir(parents=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        _git(root, "config", k, v)
    (root / ".gitignore").write_text("sysop/runtime/\n")
    (root / "review_tasks.md").write_text(TRACKER)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    _git(root, "checkout", "-q", "-b", "batch/1")
    (root / "work.txt").write_text("work\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "batch 1 work")
    _git(root, "checkout", "-q", "main")
    return root


def _claim(root: Path) -> list[Path]:
    """The three things a batch claim leaves in the main checkout."""
    rt = root / "sysop/runtime"
    lock = rt / "locks/BATCH-1.lock"
    marker = rt / "parked/BATCH-1__RUN1.md"
    plan = rt / "claim/BATCH-1/RUN1/plan.md"
    for p in (lock, marker, plan):
        p.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(f"task_id: BATCH-1\nbranch: batch/1\nworkspace: {root}/gone-wt\n")
    marker.write_text("park\n")
    plan.write_text("plan\n")
    return [lock, marker, plan.parent.parent]


def _close_batch(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(CLOSE_BATCH), *args], cwd=str(cwd),
                          capture_output=True, text=True)


def _squash_into_main(root: Path, tip: str) -> None:
    """The PR's squash merge, as the reset to `origin/<default branch>` leaves it."""
    _git(root, "checkout", "-q", "main")
    _git(root, "merge", "-q", "--squash", tip)
    _git(root, "commit", "-qm", "squash (#1)")
    for branch in {tip, "batch/1"}:
        _git(root, "branch", "-D", branch)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Behaviour
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("shape", ["integration", "reuse"])
def test_step6_rerun_from_main_releases_what_step_4b_kept(tmp_path, shape):
    root = _repo(tmp_path / shape)
    kept = _claim(root)
    if shape == "integration":
        tip = "merge/review-close-X"
        _git(root, "checkout", "-q", "-b", tip)
        _git(root, "merge", "-q", "--ff-only", "batch/1")
        r = _close_batch(root, "--merge-target", tip, "1")
    else:  # PR-reuse: the approved branch is the merge target, and needs --force
        tip = "batch/1"
        _git(root, "checkout", "-q", tip)
        r = _close_batch(root, "--force", "--merge-target", tip, "1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Locks kept, and the claim artifacts with them" in r.stdout, r.stdout
    assert all(p.exists() for p in kept), "Step 4b released before the merge"

    _squash_into_main(root, tip)
    head = _git(root, "rev-parse", "HEAD")
    r = _close_batch(root, "--merge-target", "main", "1")

    assert r.returncode == 0, r.stdout + r.stderr
    assert "Already Merged. Skipping." in r.stdout, r.stdout
    assert "close-batch commit present: 0" in r.stdout, r.stdout
    assert [p for p in kept if p.exists()] == [], r.stdout
    assert _git(root, "rev-parse", "HEAD") == head
    assert _git(root, "status", "--porcelain") == ""


def test_the_deferral_names_step_6_and_the_command(tmp_path):
    root = _repo(tmp_path / "r")
    _claim(root)
    _git(root, "checkout", "-q", "-b", "merge/review-close-X")
    _git(root, "merge", "-q", "--ff-only", "batch/1")
    r = _close_batch(root, "--merge-target", "merge/review-close-X", "1")
    assert r.returncode == 0, r.stderr
    assert "/review-close Step 6 does it" in r.stdout, r.stdout
    assert "bash sysop/scripts/close_batch.sh --merge-target main 1" in r.stdout, r.stdout
    assert "released by the next close run" not in r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# 2. Why the step reads the tracker first
# ─────────────────────────────────────────────────────────────────────────────
def test_a_pending_batch_whose_branch_is_gone_is_committed_on_main(tmp_path):
    """The hazard the `Merged` filter exists for. `close_batch.sh` takes a deleted
    branch as merged, so passing a batch the default branch still reads `Pending`
    flips it and commits on local main, which under `pr` no push follows. If this
    stops reproducing, the filter is still harmless; the test says why it is there."""
    root = _repo(tmp_path / "r")
    _claim(root)
    _git(root, "branch", "-D", "batch/1")
    head = _git(root, "rev-parse", "HEAD")
    r = _close_batch(root, "--merge-target", "main", "1")
    assert r.returncode == 0, r.stderr
    assert "close-batch commit present: 1" in r.stdout, r.stdout
    assert _git(root, "rev-parse", "HEAD") != head


@pytest.mark.parametrize("status", ["Complete", "Ready for Review"])
def test_a_finished_status_other_than_merged_is_released_with_no_commit(tmp_path, status):
    """Step 4b's set can hold a `Complete` or `Ready for Review` batch (a `--force`
    follow-up claim whose branch this close merged). The script releases those with no
    flip and no branch check, so the step passes them with `Merged`."""
    root = _repo(tmp_path / "r")
    (root / "review_tasks.md").write_text(TRACKER.replace("`Pending`", f"`{status}`"))
    _git(root, "commit", "-qam", "finished")
    kept = _claim(root)
    _git(root, "branch", "-D", "batch/1")
    head = _git(root, "rev-parse", "HEAD")
    r = _close_batch(root, "--merge-target", "main", "1")
    assert r.returncode == 0, r.stderr
    assert f"is '{status}' — no flip to make." in r.stdout, r.stdout
    assert "close-batch commit present: 0" in r.stdout, r.stdout
    assert [p for p in kept if p.exists()] == []
    assert _git(root, "rev-parse", "HEAD") == head


def test_a_batch_claimed_again_after_step_4b_is_released_by_the_bare_command(tmp_path):
    """Why the step reads the worktrees (Phase 494's round, lens A): under `pr` the default
    branch reads the batch `In Progress` until the PR merges, so `batch_work.sh` can resume
    it in a new worktree, keeping the lock. After the squash the tracker reads `Merged`, and
    the command alone deletes that live claim's lock and plan."""
    root = _repo(tmp_path / "r")
    kept = _claim(root)
    _git(root, "checkout", "-q", "-b", "merge/review-close-X")
    _git(root, "merge", "-q", "--ff-only", "batch/1")
    assert _close_batch(root, "--merge-target", "merge/review-close-X", "1").returncode == 0
    _git(root, "checkout", "-q", "main")
    live = tmp_path / "live-batch-1"
    _git(root, "worktree", "add", "-q", str(live), "batch/1")
    _git(root, "merge", "-q", "--squash", "merge/review-close-X")
    _git(root, "commit", "-qm", "squash (#1)")
    porcelain = _git(root, "worktree", "list", "--porcelain")
    assert "branch refs/heads/batch/1" in porcelain  # what the step's filter reads
    r = _close_batch(root, "--merge-target", "main", "1")
    assert r.returncode == 0, r.stderr
    assert not kept[0].exists() and live.is_dir()


# ─────────────────────────────────────────────────────────────────────────────
# 3. The step text
# ─────────────────────────────────────────────────────────────────────────────
def _has(haystack: str, needle: str) -> bool:
    """`normalize` folds emphasis and backticks out, so the needle is folded the same way."""
    return normalize(needle) in normalize(haystack)


def _release() -> str:
    text = GATE.read_text(encoding="utf-8")
    i = text.index("**Then release the batch locks Step 4b kept, in both shapes.**")
    return text[i:]


def test_the_release_follows_the_resync():
    text = GATE.read_text(encoding="utf-8")
    reset = text.index("git reset --hard origin/<default branch>\n  ```")
    assert text.index("**Then release the batch locks Step 4b kept") > reset
    # The rebase exit continues "with the cleanup below it", which includes the release.
    assert "after it, skip the reset and continue with the cleanup below it" in text


def test_the_release_reads_the_tracker_and_the_worktrees_and_filters_on_both():
    rel = _release()
    read = rel.index("python3 sysop/scripts/review_index.py --list\n")
    wts = rel.index("git worktree list --porcelain\n")
    run = rel.index('bash sysop/scripts/close_batch.sh --merge-target "<default branch>"')
    assert read < run and wts < run
    assert _has(rel, "Pass below only the set's batches whose `--list` row reads `Merged`, "
                     "`Complete` or `Ready for Review` in its status column (the third; `Review "
                     "Ready` is live, not finished), and "
                     "whose branch (the fourth column) is on no `branch refs/heads/<branch>` "
                     "line of the worktree list.")
    assert _has(rel, "**Leave out any other**")
    assert _has(rel, "has a live worktree at <path>; release it with close_batch.sh <N>")
    assert _has(rel, "On a non-zero exit or a `WARNING:` line from either read, pass no batch")


def test_the_release_checks_it_made_no_commit():
    rel = _release()
    assert _has(rel, "**Its last line must read `close-batch commit present: 0`.**")
    assert _has(rel, "If it reads `1`, the script committed on local `<default branch>`: stop")
    assert _has(rel, "Do not push that commit")


def test_land_carries_the_batch_set_and_step_6_reads_it():
    land = LAND.read_text(encoding="utf-8")
    assert _has(land, "`Batches:` (the batch numbers Step 4b passed to `close_batch.sh`, or `(none)`)")
    rel = _release()
    assert _has(rel, "Under `--land`, the set is `report.md`'s `Batches:` line under `## Step 6`")
    # A hand-off sealed before the line existed releases nothing: its Step 8 `Batches:`
    # row can hold task counts, which would read as batch numbers (Phase 494's round).
    assert _has(rel, "**A `report.md` with no `Batches:` line releases nothing here:**")
    assert "Step 8 `Batches:` row" not in rel


def test_step_8_reports_the_released_batch_locks():
    assert _has(_release(), "Add each `BATCH-<N>` whose lock it removed to Step 8's `Locks cleaned:` row.")
    assert _has(text_of(SKILL), "Locks cleaned: <the `LOCKS_REMOVED` ids Step 4c printed, and each "
                                "`BATCH-<N>` Step 6 released>")
