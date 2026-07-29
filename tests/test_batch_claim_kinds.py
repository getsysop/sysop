"""Phase 156 — a review-batch claim is a real claim: `BATCH-<N>.lock`.

**The defect this pins is a write that never existed under five readers that
assumed it did.** `next_task.py:558` skips a batch whose
`sysop/runtime/locks/BATCH-<N>.lock` is present; `sitrep_survey.py` keys its
batch classifier on `has_lock` and treats a worktree with no matching lock as
an *orphan*; `scope_overlap.py` builds its in-flight set from the same
directory; and `/claim-task` Step 2 told the agent in prose to check for the
file before claiming. Nothing had ever written one. Every reader failed **open**
— `/next-task` handing out a batch already in flight, `/sitrep` reporting a live
batch worktree as an orphan and its batch as unclaimed.

This suite lives in one file rather than split across the three script suites
because the invariant *is* cross-script: the write (`batch_work.sh`), both
removal paths (`close_batch.sh` at close, `batch_work.sh --release` on
abandonment), and the refusal that keeps the wrong script from half-reversing a
batch claim (`claim_task.sh --release`) are one mechanism. The forced ordering
is the point — **a lock write without a removal path makes every batch
permanently unclaimable after its first claim** — and a guard that cannot see
both halves cannot enforce it.

Coverage is deliberately behavioural: every test drives the real scripts as
subprocesses against a scratch git repo and asserts on the resulting files,
git history, and the readers' actual verdicts. Phase 155's guard suite failed
because it asserted that prose existed; the tests here assert that the software
does something, so deleting the mechanism cannot leave them green. The two
prose guards at the bottom cover the one surface with no runtime (the skill's
claim-ID normalisation) and are scoped to their own sections.
"""
import re
import subprocess
import sys
from pathlib import Path

import next_task

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
BATCH_WORK = SCRIPTS / "batch_work.sh"
CLOSE_BATCH = SCRIPTS / "close_batch.sh"
CLAIM_TASK = SCRIPTS / "claim_task.sh"
CLAIM_SKILL = REPO_ROOT / "core/skills/claim-task/SKILL.md"

# One Pending batch and one already-claimed batch. em-dash + backtick-quoted
# trailing status is the shape both scripts' regexes require.
TASKS = """\
# Review Tasks

### Batch 7 — Seven `Pending`

> **Branch:** `review/batch-7`

- [ ] TASK-1 one
- [ ] TASK-2 two

### Batch 8 — Eight `In Progress`

> **Branch:** `review/batch-8`

- [/] TASK-3 three

## Statistics

| Batch | Status |
|---|---|
| (Batch 7) | Pending |
| (Batch 8) | In Progress |

Grand Total — 0 done, 3 open
"""


def _git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(cwd), check=check,
                          capture_output=True, text=True)


def _repo(root, tasks=TASKS):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "review_tasks.md").write_text(tasks)
    (root / "README.md").write_text("# seed\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run(script, cwd, *args):
    return subprocess.run(["bash", str(script), *args],
                          cwd=str(cwd), capture_output=True, text=True)


def _locks(repo):
    return repo / "sysop/runtime/locks"


def _lock(repo, n):
    return _locks(repo) / f"BATCH-{n}.lock"


def _claim(repo, n=7):
    """Claim a batch and assert the claim itself succeeded."""
    r = _run(BATCH_WORK, repo, str(n))
    assert r.returncode == 0, r.stderr
    return r


def _head(repo):
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


# ---------------------------------------------------------------------------
# The write
# ---------------------------------------------------------------------------
class TestLockWrite:
    def test_claim_writes_the_batch_lock(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        assert _lock(repo, 7).is_file(), "batch_work.sh must write BATCH-<N>.lock"

    def test_lock_carries_the_fields_every_reader_parses(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        body = _lock(repo, 7).read_text()
        # task_id is what next_task.py's filter and scope_overlap key on;
        # branch is what sitrep's batch classifier keys on; workspace is what
        # scope_overlap reads the in-flight diff from.
        assert "task_id: BATCH-7" in body
        assert "branch: review/batch-7" in body
        assert re.search(r"^workspace: \S", body, re.M)
        assert re.search(r"^status: in_progress$", body, re.M)
        assert re.search(r"^expires: \d{4}-\d{2}-\d{2}T", body, re.M)

    def test_lock_carries_the_same_field_set_as_a_roadmap_lock(self, tmp_path):
        """The batch lock's value is that every existing reader parses it
        without a special case, which only holds if the field set matches what
        `claim_task.sh --lock` writes. Asserted as a set so a dropped field
        fails here rather than degrading a reader silently — `files_impacted`
        in particular is scope_overlap.py's second-choice scope source."""
        yaml = __import__("yaml")
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        keys = set(yaml.safe_load(_lock(repo, 7).read_text()))
        expected = {"task_id", "status", "agent", "branch", "mode", "workspace",
                    "started", "expires", "files_impacted", "plan_summary", "notes"}
        assert keys == expected, f"field drift vs the roadmap lock: {keys ^ expected}"

    def test_lock_is_valid_yaml(self, tmp_path):
        """scope_overlap.py parses locks as YAML — a malformed lock would drop
        the batch out of the in-flight set, which is the bug being fixed."""
        yaml = __import__("yaml")
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        data = yaml.safe_load(_lock(repo, 7).read_text())
        assert data["task_id"] == "BATCH-7"
        assert data["branch"] == "review/batch-7"

    def test_workspace_points_at_a_real_directory(self, tmp_path):
        """sitrep_survey.py reports a lock whose workspace is missing as a
        stale-lock discrepancy, so the lock must be written after the worktree."""
        yaml = __import__("yaml")
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        ws = yaml.safe_load(_lock(repo, 7).read_text())["workspace"]
        assert Path(ws).is_dir(), f"workspace {ws} does not exist"

    def test_reclaim_is_idempotent_and_leaves_the_original_lock(self, tmp_path):
        """`batch_work.sh <N>` is re-runnable on purpose (/auto-fix and
        /auto-judge call it in a loop). A second claim must not fail, and must
        not rewrite the lock — `started:` is the only record of how long the
        batch has been held, and `files_impacted:` may have been edited by hand.

        The sentinel is load-bearing: comparing the file to its own earlier
        text passes even when the lock IS rewritten, because `started:` has
        one-second resolution and a re-claim lands inside the same second. That
        false pass survived this phase's first mutation round."""
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        lock = _lock(repo, 7)
        lock.write_text(lock.read_text() + "sentinel: hand-edited\n")
        r = _run(BATCH_WORK, repo, "7")
        assert r.returncode == 0, r.stderr
        assert "sentinel: hand-edited" in lock.read_text(), (
            "a re-claim overwrote the existing lock"
        )
        assert "already present" in r.stdout

    def test_no_lock_is_left_behind_when_the_worktree_cannot_be_created(self, tmp_path):
        """Ordering invariant: the lock is written *after* the worktree, so a
        failed claim leaves nothing. A lock pointing at a workspace that was
        never created is what sitrep reports as a stale-lock discrepancy, and
        it would block the batch with no worktree to show for it."""
        repo = _repo(tmp_path / "repo")
        # Hold review/batch-7 in a worktree elsewhere, so batch_work.sh's own
        # `git worktree add` fails: a branch can only be checked out once.
        _git(repo, "branch", "review/batch-7")
        _git(repo, "worktree", "add", "-q", str(tmp_path / "held"), "review/batch-7")
        r = _run(BATCH_WORK, repo, "7")
        assert r.returncode != 0, "worktree creation should have failed"
        assert not _lock(repo, 7).exists(), (
            "a claim that could not create its worktree must not leave a lock"
        )

    def test_batch_id_forms_are_interchangeable(self, tmp_path):
        for arg in ("BATCH-7", "batch-7"):
            repo = _repo(tmp_path / f"repo-{arg}")
            r = _run(BATCH_WORK, repo, arg)
            assert r.returncode == 0, r.stderr
            assert _lock(repo, 7).is_file(), f"{arg} form did not claim batch 7"

    def test_lock_lands_in_the_main_repo_when_claimed_from_a_worktree(self, tmp_path):
        """The anchoring invariant. `git rev-parse --show-toplevel` returns the
        WORKTREE root, so a lock written against it would be invisible to every
        reader (they all resolve via --git-common-dir). Locks live under the
        main repo, always."""
        repo = _repo(tmp_path / "repo")
        _git(repo, "branch", "side")
        wt = tmp_path / "side-wt"
        _git(repo, "worktree", "add", "-q", str(wt), "side")
        r = _run(BATCH_WORK, wt, "7")
        assert r.returncode == 0, r.stderr
        assert _lock(repo, 7).is_file(), "lock must be anchored to the main repo"
        assert not (wt / "sysop/runtime/locks/BATCH-7.lock").exists()


# ---------------------------------------------------------------------------
# Removal path 1 — close
# ---------------------------------------------------------------------------
class TestCloseRemovesTheLock:
    def test_close_removes_the_lock(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        _git(repo, "worktree", "remove", "--force", str(tmp_path / "repo-batch-7"),
             check=False)
        r = _run(CLOSE_BATCH, repo, "--force", "7")
        assert r.returncode == 0, r.stderr
        assert not _lock(repo, 7).exists(), (
            "close_batch.sh must release the lock — without this every batch is "
            "permanently unclaimable after its first claim"
        )

    def test_dry_run_leaves_the_lock_alone(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        r = _run(CLOSE_BATCH, repo, "--dry-run", "--force", "7")
        assert r.returncode == 0, r.stderr
        assert _lock(repo, 7).is_file()
        assert "would remove" in r.stdout

    def test_a_skipped_batch_keeps_its_lock(self, tmp_path):
        """Only batches this run actually CLOSED may be unlocked. A batch that
        was skipped — here, because its branch is not merged — is still in
        flight, and releasing its lock would advertise it as claimable.

        The skipped batch must genuinely *hold* a lock for this to bind: an
        earlier version skipped a batch that had none, so iterating the wrong
        list was a silent no-op and the mutation survived."""
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        _claim(repo, 8)
        for n in (7, 8):
            _git(repo, "worktree", "remove", "--force",
                 str(tmp_path / f"repo-batch-{n}"), check=False)
        # batch 7's branch has no commits, so it is an ancestor of main and
        # closes. batch 8 gets one, so the merge check rejects it.
        subprocess.run(["git", "checkout", "-q", "review/batch-8"], cwd=str(repo),
                       capture_output=True)
        (repo / "extra.txt").write_text("x")
        _git(repo, "add", "extra.txt")
        _git(repo, "commit", "-qm", "unmerged work")
        subprocess.run(["git", "checkout", "-q", "main"], cwd=str(repo),
                       capture_output=True)

        r = _run(CLOSE_BATCH, repo, "7", "8")
        assert r.returncode == 0, r.stderr
        assert "unmerged" in r.stdout, "batch 8 should have been skipped"
        assert not _lock(repo, 7).exists(), "the closed batch must be unlocked"
        assert _lock(repo, 8).is_file(), "a skipped batch's lock must survive"

    def test_close_off_main_defers_the_release_instead_of_stripping_the_lock(
        self, tmp_path
    ):
        """The lock is main-repo-global; the `Merged` flip is branch-local.
        Under `pr` policy /review-close Step 4b runs this with `--force` on the
        *integration* branch, and Step 4d-1 documents that a blocked PR must
        leave `sysop/runtime/locks/` intact. Releasing there strips the lock
        while `main` still reads the batch `Pending`, and /next-task hands it to
        a second agent while the finished work sits on an unmerged branch."""
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        _git(repo, "worktree", "remove", "--force", str(tmp_path / "repo-batch-7"),
             check=False)
        _git(repo, "checkout", "-q", "-b", "merge/review-close-abc")
        r = _run(CLOSE_BATCH, repo, "--force", "7")
        assert r.returncode == 0, r.stderr
        assert "`Merged`" in (repo / "review_tasks.md").read_text()
        assert _lock(repo, 7).is_file(), (
            "a close committed off main must not release the lock"
        )
        assert "Locks kept" in r.stdout
        assert "close_batch.sh 7" in r.stdout, "must name the recovery command"

    def test_the_deferred_lock_is_released_by_a_later_close_from_main(self, tmp_path):
        """The other half of deferring: once the PR merges and `main` reads
        `Merged`, re-running from main clears it. Without this the deferral
        would trade a double-claim for a permanent leak."""
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        _git(repo, "worktree", "remove", "--force", str(tmp_path / "repo-batch-7"),
             check=False)
        _git(repo, "checkout", "-q", "-b", "merge/review-close-abc")
        _run(CLOSE_BATCH, repo, "--force", "7")
        assert _lock(repo, 7).is_file()
        _git(repo, "checkout", "-q", "main")
        _git(repo, "merge", "-q", "--no-edit", "merge/review-close-abc")
        r = _run(CLOSE_BATCH, repo, "7")
        assert r.returncode == 0, r.stderr
        assert not _lock(repo, 7).exists()

    def test_absent_lock_is_reported_not_silent(self, tmp_path):
        """A removal path that says nothing when the file is absent cannot be
        told apart from one that never ran.

        (Deleted by accident while rewriting the worktree test in this phase's
        own round-2 fixes, and caught by the second mutation pass — the exact
        self-inflicted-regression class the round exists for.)"""
        repo = _repo(tmp_path / "repo")
        r = _run(CLOSE_BATCH, repo, "--force", "7")
        assert r.returncode == 0, r.stderr
        assert "No batch lock at" in r.stdout

    def test_dry_run_from_a_worktree_reports_the_main_repo_lock_path(self, tmp_path):
        """The dry-run preview is the one lock-path consumer that still runs
        off main, so it is what pins the git-common-dir resolution: resolving
        from `--show-toplevel` would print a worktree-local path that no reader
        ever uses."""
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        _git(repo, "branch", "elsewhere")
        wt = tmp_path / "elsewhere-wt"
        _git(repo, "worktree", "add", "-q", str(wt), "elsewhere")
        r = _run(CLOSE_BATCH, wt, "--dry-run", "--force", "7")
        assert r.returncode == 0, r.stderr
        assert str(_lock(repo, 7)) in r.stdout, (
            "the preview must name the main repo's lock, not a worktree-local one"
        )
        assert _lock(repo, 7).is_file()

    def test_commit_failure_leaves_the_lock_in_place(self, tmp_path):
        """Ordering invariant: the lock is released only after the close commit
        lands, so a failed commit leaves the batch reading as still-claimed
        rather than half-closed and claimable."""
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        hooks = Path(_git(repo, "rev-parse", "--git-path", "hooks").stdout.strip())
        if not hooks.is_absolute():
            hooks = repo / hooks
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text("#!/bin/sh\nexit 1\n")
        (hooks / "pre-commit").chmod(0o755)
        r = _run(CLOSE_BATCH, repo, "--force", "7")
        assert r.returncode == 1
        assert _lock(repo, 7).is_file(), "a failed close must not release the lock"


# ---------------------------------------------------------------------------
# Removal path 2 — release
# ---------------------------------------------------------------------------
class TestRelease:
    def test_release_reverses_both_halves_of_the_claim(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        _claim(repo, 8)  # already `In Progress` in the fixture
        before = _head(repo)
        r = _run(BATCH_WORK, repo, "--release", "8")
        assert r.returncode == 0, r.stderr
        text = (repo / "review_tasks.md").read_text()
        assert "### Batch 8 — Eight `Pending`" in text
        assert "- [ ] TASK-3 three" in text, "[/] must revert to [ ]"
        assert "| (Batch 8) | Pending |" in text
        assert not _lock(repo, 8).exists()
        assert _head(repo) != before, "the release must be committed, as the claim was"
        assert not (tmp_path / "repo-batch-8").exists(), "worktree must be removed"

    def test_release_refuses_outside_the_main_checkout(self, tmp_path):
        """A worktree carries its own branch's review_tasks.md, frozen at
        branch-cut. Releasing off that copy reads a batch as Pending while main
        has it In Progress, and clears the lock on a still-claimed batch —
        found by this phase's own smoke test, before it shipped."""
        repo = _repo(tmp_path / "repo")
        _claim(repo, 8)
        wt = tmp_path / "repo-batch-8"
        r = _run(BATCH_WORK, wt, "--release", "8")
        assert r.returncode == 1
        assert "must run from the main checkout" in r.stderr
        assert _lock(repo, 8).is_file(), "nothing may be released from a worktree"
        assert "`In Progress`" in (repo / "review_tasks.md").read_text()

    def test_release_refuses_a_batch_holding_completed_work(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        _claim(repo, 8)
        p = repo / "review_tasks.md"
        p.write_text(p.read_text().replace("- [/] TASK-3", "- [x] TASK-3"))
        _git(repo, "add", "review_tasks.md")
        _git(repo, "commit", "-qm", "work")
        r = _run(BATCH_WORK, repo, "--release", "8")
        assert r.returncode == 1
        assert "completed task" in r.stderr
        assert _lock(repo, 8).is_file()

    def test_force_releases_a_batch_holding_completed_work(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        _claim(repo, 8)
        p = repo / "review_tasks.md"
        p.write_text(p.read_text().replace("- [/] TASK-3", "- [x] TASK-3"))
        _git(repo, "add", "review_tasks.md")
        _git(repo, "commit", "-qm", "work")
        r = _run(BATCH_WORK, repo, "--release", "--force", "8")
        assert r.returncode == 0, r.stderr
        assert not _lock(repo, 8).exists()

    def test_release_of_a_pending_batch_clears_the_lock_only(self, tmp_path):
        """The stranded-batch recovery. batch_work.sh skips the Pending -> In
        Progress commit when it is off main / dirty / the pull fails, so a
        Pending batch can hold a lock — and next_task.py skips a locked batch
        whatever its status says, which strands it."""
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        assert "### Batch 7 — Seven `Pending`" in (repo / "review_tasks.md").read_text()
        before = _head(repo)
        r = _run(BATCH_WORK, repo, "--release", "7")
        assert r.returncode == 0, r.stderr
        assert not _lock(repo, 7).exists()
        assert _head(repo) == before, "nothing to revert means nothing to commit"

    def test_release_refuses_a_merged_batch(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        p = repo / "review_tasks.md"
        p.write_text(p.read_text().replace("Seven `Pending`", "Seven `Merged`"))
        _git(repo, "add", "review_tasks.md")
        _git(repo, "commit", "-qm", "merged")
        r = _run(BATCH_WORK, repo, "--release", "7")
        assert r.returncode == 1
        # Not just "it refused": the catch-all for an unrecognised status also
        # refuses and echoes the status back, so asserting on `Merged` alone
        # passes even when the Merged arm is deleted. Pin the owner instead.
        assert "close_batch.sh" in r.stderr

    def test_release_rejects_a_trailing_flag(self, tmp_path):
        """Flags are consumed only before the positional, so `--release 7
        --force` would silently no-op and then abort a dirty-worktree release
        telling the operator to pass the flag they already passed."""
        repo = _repo(tmp_path / "repo")
        r = _run(BATCH_WORK, repo, "--release", "7", "--force")
        assert r.returncode == 1
        assert "Flags must come before" in r.stderr

    def test_release_of_an_unknown_batch_fails(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(BATCH_WORK, repo, "--release", "99")
        assert r.returncode == 1
        assert "not found" in r.stderr


class TestClaimTaskRefusesBatches:
    def test_claim_task_release_refuses_a_batch_id(self, tmp_path):
        """claim_task.sh owns tasks/index.yml. Releasing a batch lock there
        would leave review_tasks.md reading `In Progress` forever — the
        half-revert that strands a batch."""
        repo = _repo(tmp_path / "repo")
        _claim(repo, 8)
        r = _run(CLAIM_TASK, repo, "--release", "BATCH-8")
        assert r.returncode == 1
        assert "batch_work.sh --release 8" in r.stderr
        assert _lock(repo, 8).is_file(), "the lock must survive the refusal"


# ---------------------------------------------------------------------------
# The readers — the reason the lock exists
# ---------------------------------------------------------------------------
class TestReadersSeeTheLock:
    def test_next_task_skips_a_locked_batch(self, tmp_path):
        """next_task.py:558's in-flight filter, dead until this phase."""
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        locks = next_task.list_locks(repo)
        assert "BATCH-7" in locks, "list_locks must surface the batch lock"
        batches = [{"number": 7, "status": "Pending", "tasks": [], "severity": {}}]
        assert next_task.pick_next_batch(batches, locks)[0] is None
        assert next_task.pick_next_batch(batches, set())[0] is not None

    def test_sitrep_stops_calling_a_live_batch_worktree_an_orphan(self, tmp_path):
        """sitrep_survey.py flagged every in-flight batch worktree as an
        `orphan worktree` on every run, because no lock ever matched its branch.

        Driven as a subprocess rather than by calling `_find_discrepancies`
        directly: `_read_worktrees(main_root)` runs `git worktree list` with no
        `cwd`, so in-process it enumerates whatever repo the *test runner* sits
        in and ignores the scratch repo entirely. Benign in production (cwd is
        always inside the same repo, and `git worktree list` is repo-global),
        but it means only a real invocation can isolate this. Filed separately.
        """
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        survey = SCRIPTS / "sitrep_survey.py"

        def _report():
            return subprocess.run(
                [sys.executable, str(survey)], cwd=str(repo),
                capture_output=True, text=True,
            ).stdout

        with_lock = _report()
        stashed = _lock(repo, 7).read_text()
        _lock(repo, 7).unlink()
        without_lock = _report()
        _lock(repo, 7).write_text(stashed)

        assert "orphan worktree" in without_lock, (
            "pre-Phase-156 behaviour: with no lock the live batch worktree is "
            "reported as an orphan"
        )
        assert "orphan worktree" not in with_lock
        assert "pending (not claimed)" in without_lock
        assert "pending (not claimed)" not in with_lock


# ---------------------------------------------------------------------------
# Prose guards — the one surface with no runtime
# ---------------------------------------------------------------------------
def _skill_section(heading_prefix, text=None):
    """Return one `## `-level section of the claim-task skill, so a rule stated
    anywhere else in a 560-line file cannot keep a check green."""
    text = text if text is not None else CLAIM_SKILL.read_text(encoding="utf-8")
    m = re.search(
        rf"^## {re.escape(heading_prefix)}.*?$(.*?)(?=^## )", text, re.M | re.S
    )
    assert m, f"section '{heading_prefix}' not found in claim-task/SKILL.md"
    return m.group(1)


def claim_id_problems(text=None):
    """Step 1 must define <CLAIM_ID> for BOTH kinds, and the batch lock check
    must address it. Returns a list of problems; empty means clean."""
    problems = []
    step1 = _skill_section("Step 1", text)
    # Structure, not presence: <CLAIM_ID> is discussed in prose further down
    # Step 1, so `"<CLAIM_ID>" in step1` stays true even after the row that
    # BINDS it to the batch form is deleted. Require the binding itself.
    if not re.search(r"^\|.*<CLAIM_ID>.*BATCH-<N>.*\|", step1, re.M):
        problems.append(
            "Step 1 no longer binds <CLAIM_ID> to BATCH-<N> for the batch kind"
        )

    step2 = _skill_section("Step 2", text)
    # The *instruction* must address the lock by claim ID. A narrative mention
    # of BATCH-<N>.lock elsewhere must not satisfy this.
    if not re.search(r"sysop/runtime/locks/<CLAIM_ID>\.lock", step2):
        problems.append(
            "Step 2's lock check does not address sysop/runtime/locks/<CLAIM_ID>.lock"
        )
    if re.search(r"sysop/runtime/locks/<TASK_ID>\.lock`?\s+already exists", step2):
        problems.append(
            "Step 2's duplicate-claim check still keys on <TASK_ID>, which never "
            "matches a batch lock"
        )

    # The REVIEW-BATCH bullets are the ones this phase exists to fix, and the
    # checks above are keyed on the roadmap sentence — so reverting just the
    # batch side was invisible to them. Scope to the batch branch and require
    # both arms to address the claim ID.
    batch = step2.split("**For review batches:**", 1)
    if len(batch) != 2:
        problems.append("Step 2 no longer has a **For review batches:** branch")
    else:
        arms = batch[1]
        if re.search(r"sysop/runtime/locks/<TASK_ID>\.lock", arms):
            problems.append(
                "Step 2's review-batch lock check keys on <TASK_ID>, which never "
                "matches a batch lock"
            )
        if len(re.findall(r"sysop/runtime/locks/<CLAIM_ID>\.lock", arms)) < 2:
            problems.append(
                "Step 2's review-batch branch no longer checks "
                "sysop/runtime/locks/<CLAIM_ID>.lock on both the Pending and "
                "In Progress arms"
            )
    return problems


def forced_ordering_problems(write=None, close=None, release=None):
    """The write must not exist without both removal paths. Structural: each
    check looks for the operation, not for prose describing it."""
    problems = []
    write = write if write is not None else BATCH_WORK.read_text(encoding="utf-8")
    close = close if close is not None else CLOSE_BATCH.read_text(encoding="utf-8")
    release = release if release is not None else write

    writes_lock = re.search(r'cat > "\$lock_file"', write) is not None
    if not writes_lock:
        return problems  # no write, so nothing to require a removal for

    if not re.search(r'^\s*rm (-f )?"\$lock_file"', close, re.M):
        problems.append(
            "close_batch.sh writes no lock removal — a batch would stay locked "
            "forever after merge"
        )
    if not re.search(r'remove_batch_lock ', close):
        problems.append("close_batch.sh never calls remove_batch_lock")
    if not re.search(r'remove_batch_lock "\$REL_NUM"', release):
        problems.append("batch_work.sh --release never removes the lock")
    return problems


class TestProseGuards:
    def test_skill_is_claim_id_normalised(self):
        assert claim_id_problems() == []

    def test_guard_catches_a_step1_that_drops_the_claim_id_binding(self):
        """Deleting only the table ROW must fail — <CLAIM_ID> is still named in
        Step 1's prose, so a presence check would stay green."""
        text = CLAIM_SKILL.read_text(encoding="utf-8")
        row = "| `<CLAIM_ID>` | the task ID (`TECH-0007`) | **`BATCH-<N>`** (`BATCH-116`) |"
        assert row in text, "the binding row moved — update this twin, don't delete it"
        softened = text.replace(row, "")
        assert softened != text
        assert any("no longer binds" in p for p in claim_id_problems(softened))

    def test_guard_catches_a_step2_lock_check_keyed_on_task_id(self):
        text = CLAIM_SKILL.read_text(encoding="utf-8")
        softened = text.replace(
            "If `sysop/runtime/locks/<CLAIM_ID>.lock` already exists",
            "If `sysop/runtime/locks/<TASK_ID>.lock` already exists",
        )
        assert softened != text
        assert any("still keys on <TASK_ID>" in p for p in claim_id_problems(softened))

    def test_guard_catches_a_reverted_review_batch_lock_check(self):
        """The batch-facing bullets are the point of the phase, and the first
        version of this guard was keyed entirely on the roadmap sentence — so
        reverting exactly these two lines left it green."""
        text = CLAIM_SKILL.read_text(encoding="utf-8")
        head, _, tail = text.partition("**For review batches:**")
        softened = head + "**For review batches:**" + tail.replace(
            "sysop/runtime/locks/<CLAIM_ID>.lock",
            "sysop/runtime/locks/<TASK_ID>.lock",
        )
        assert softened != text
        problems = claim_id_problems(softened)
        assert any("review-batch lock check keys on <TASK_ID>" in p for p in problems)

    def test_guard_catches_a_dropped_pending_arm_lock_check(self):
        text = CLAIM_SKILL.read_text(encoding="utf-8")
        head, _, tail = text.partition("**For review batches:**")
        softened = head + "**For review batches:**" + tail.replace(
            "unless `sysop/runtime/locks/<CLAIM_ID>.lock` exists", "always", 1)
        assert softened != text
        assert any("both the Pending and" in p for p in claim_id_problems(softened))

    def test_forced_ordering_holds(self):
        assert forced_ordering_problems() == []

    def test_guard_catches_a_deleted_close_removal(self):
        close = CLOSE_BATCH.read_text(encoding="utf-8")
        softened = close.replace('    rm -f "$lock_file"', '    : # removed')
        assert softened != close
        assert any("no lock removal" in p for p in forced_ordering_problems(close=softened))

    def test_guard_catches_an_uncalled_close_removal(self):
        close = CLOSE_BATCH.read_text(encoding="utf-8")
        softened = close.replace("    remove_batch_lock \"$n\"", "    :")
        assert softened != close
        assert any("never calls" in p for p in forced_ordering_problems(close=softened))

    def test_guard_catches_a_deleted_release_removal(self):
        work = BATCH_WORK.read_text(encoding="utf-8")
        softened = work.replace('remove_batch_lock "$REL_NUM"', ':')
        assert softened != work
        assert any("--release never removes" in p
                   for p in forced_ordering_problems(release=softened))

    def test_guard_is_silent_when_nothing_writes_a_lock(self):
        """The predicate is conditional on the write existing — a tree that
        never writes a batch lock needs no removal path, and the guard must not
        invent a failure for it."""
        assert forced_ordering_problems(write="#!/usr/bin/env bash\n") == []


# ---------------------------------------------------------------------------
# Regressions from this phase's own adversarial round
# ---------------------------------------------------------------------------
class TestAdversarialRoundRegressions:
    """Each test here pins a defect the Phase 156 round found in the first cut.
    They are grouped so the provenance stays visible: these are not hypothetical
    edge cases, they were reproduced against the shipped scripts."""

    def test_a_merged_batch_sheds_its_lock(self, tmp_path):
        """HIGH — the strand. `batch_work.sh <N>` deliberately lets a Merged
        batch through for follow-up work and writes a lock; close_batch skipped
        already-Merged batches before reaching the removal, `--release` refuses
        a Merged batch, and `claim_task.sh --release` refuses a BATCH id and
        points back at `--release`. All three refusals routed in a circle and
        the lock became unremovable by any shipped command."""
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        _git(repo, "worktree", "remove", "--force", str(tmp_path / "repo-batch-7"),
             check=False)
        assert _run(CLOSE_BATCH, repo, "--force", "7").returncode == 0
        assert not _lock(repo, 7).exists()

        _claim(repo, 7)  # the documented follow-up re-claim, now on a Merged batch
        assert _lock(repo, 7).is_file(), "precondition: the strand is reproduced"

        r = _run(CLOSE_BATCH, repo, "7")
        assert r.returncode == 0, r.stderr
        assert "Already Merged" in r.stdout
        assert not _lock(repo, 7).exists(), (
            "a Merged batch must shed its lock even when this run closed nothing"
        )

    def test_dry_run_does_not_clear_a_merged_batch_lock(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        _git(repo, "worktree", "remove", "--force", str(tmp_path / "repo-batch-7"),
             check=False)
        _run(CLOSE_BATCH, repo, "--force", "7")
        _claim(repo, 7)
        assert _run(CLOSE_BATCH, repo, "--dry-run", "7").returncode == 0
        assert _lock(repo, 7).is_file(), "--dry-run must mutate nothing"

    def test_release_works_from_a_subdirectory_of_the_main_checkout(self, tmp_path):
        """HIGH — `git add review_tasks.md` was CWD-relative, so from
        `<repo>/sysop/scripts/` it failed `fatal: pathspec ... did not match`
        AFTER the worktree was removed: revert uncommitted, lock still present,
        worktree gone, and only a raw git error printed."""
        repo = _repo(tmp_path / "repo")
        _claim(repo, 8)
        sub = repo / "sysop" / "scripts"   # where a consumer actually invokes it
        sub.mkdir(parents=True, exist_ok=True)
        r = _run(BATCH_WORK, sub, "--release", "8")
        assert r.returncode == 0, r.stderr + r.stdout
        assert "`Pending`" in (repo / "review_tasks.md").read_text()
        assert not _lock(repo, 8).exists()
        assert _git(repo, "status", "--short").stdout.strip() == "", (
            "the release must be committed, not left in the working tree"
        )

    def test_dirty_check_fires_from_a_subdirectory(self, tmp_path):
        """HIGH sibling — the same CWD-relative pathspec silently voided the
        guard that refuses to release over uncommitted edits."""
        repo = _repo(tmp_path / "repo")
        _claim(repo, 8)
        p = repo / "review_tasks.md"
        p.write_text(p.read_text() + "\nIMPORTANT LOCAL EDIT\n")
        sub = repo / "sysop" / "scripts"
        sub.mkdir(parents=True, exist_ok=True)
        r = _run(BATCH_WORK, sub, "--release", "8")
        assert r.returncode == 1
        assert "uncommitted changes" in r.stderr
        assert "IMPORTANT LOCAL EDIT" in p.read_text()

    def test_release_does_not_sweep_unrelated_staged_files(self, tmp_path):
        """MEDIUM — `git add` + a bare `git commit` committed the whole index
        into `docs: release Batch N` (Phase 151's all-or-nothing rule)."""
        repo = _repo(tmp_path / "repo")
        _claim(repo, 8)
        (repo / ".env.local").write_text("SECRET\n")
        _git(repo, "add", ".env.local")
        r = _run(BATCH_WORK, repo, "--release", "8")
        assert r.returncode == 0, r.stderr
        files = _git(repo, "show", "--name-only", "--format=", "HEAD").stdout.split()
        assert files == ["review_tasks.md"], f"release commit swept in {files}"
        assert ".env.local" in _git(repo, "diff", "--cached", "--name-only").stdout

    def test_close_survives_a_lock_that_cannot_be_removed(self, tmp_path):
        """HIGH — the removal ran under `set -e` before the Summary and the
        terminal one-liner. A failed `rm` aborted the script *after* the close
        commit landed, so /review-close Step 4b read a successful close as a
        silent mid-flow abort."""
        import os
        if os.geteuid() == 0:
            import pytest
            pytest.skip("root ignores directory write permissions")
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        _git(repo, "worktree", "remove", "--force", str(tmp_path / "repo-batch-7"),
             check=False)
        _locks(repo).chmod(0o555)
        try:
            r = _run(CLOSE_BATCH, repo, "--force", "7")
        finally:
            _locks(repo).chmod(0o755)
        assert r.returncode == 0, r.stderr
        assert "close-batch commit present: 1" in r.stdout, (
            "the terminal receipt must survive a failed lock removal"
        )
        assert "── Summary ──" in r.stdout

    def test_release_of_an_unparseable_header_reports_instead_of_dying_silently(
        self, tmp_path
    ):
        """MEDIUM — an unguarded `grep` took the assignment's status down under
        `set -euo pipefail`, exiting 1 before its own error message could
        print. Reachable whenever review_index.py is absent and the header
        spacing is irregular: the fallback list parser accepts it, the grep
        does not."""
        tasks = TASKS.replace("### Batch 8 — Eight", "###  Batch 8 — Eight")
        repo = _repo(tmp_path / "repo", tasks=tasks)
        r = _run(BATCH_WORK, repo, "--release", "8")
        assert r.returncode == 1
        assert r.stderr.strip(), "a non-zero exit with no diagnostic is the defect"
        assert "Could not find" in r.stderr

    def test_close_accepts_the_claim_id_and_zero_padded_forms(self, tmp_path):
        """LOW — `close_batch.sh 007` reached review_index.py as batch 7 and
        closed it, then looked for BATCH-007.lock and reported "no lock" —
        closing the batch while stranding its lock. `BATCH-7` was rejected
        outright even though batch_work.sh now normalises it."""
        for arg in ("007", "BATCH-7"):
            repo = _repo(tmp_path / f"repo-{arg}")
            _claim(repo, 7)
            _git(repo, "worktree", "remove", "--force",
                 str(tmp_path / f"repo-{arg}-batch-7"), check=False)
            r = _run(CLOSE_BATCH, repo, "--force", arg)
            assert r.returncode == 0, r.stderr
            assert "`Merged`" in (repo / "review_tasks.md").read_text()
            assert not _lock(repo, 7).exists(), f"{arg} closed but stranded the lock"

    def test_a_skipped_claim_says_how_to_clear_the_lock_it_wrote(self, tmp_path):
        """MEDIUM — the status flip is best-effort and the lock is not, so a
        claim off `main` / with a dirty file / with no reachable origin leaves a
        `Pending` batch holding a lock. next_task.py then skips it forever and
        nothing tells the operator the way out."""
        repo = _repo(tmp_path / "repo")  # no origin -> the pull path fails
        r = _run(BATCH_WORK, repo, "7")
        assert r.returncode == 0, r.stderr
        assert _lock(repo, 7).is_file()
        assert "`Pending`" in (repo / "review_tasks.md").read_text()
        assert "--release 7" in r.stderr, (
            "the skip must name the command that clears the lock it just wrote"
        )


class TestRoundTwoRegressions:
    """The second adversarial pass mutated 83 sites and 28 survived. These pin
    the survivors that were real defects rather than test gaps."""

    def test_finished_statuses_shed_their_locks(self, tmp_path):
        """`Complete` and `Ready for Review` are documented lifecycle states.
        `--release` refuses a finished batch and names close_batch.sh as the
        owner of that transition — and close_batch.sh could not perform it, so
        the lock was unremovable by every supported command."""
        for status in ("Complete", "Ready for Review"):
            repo = _repo(tmp_path / f"repo-{status.replace(' ', '-')}")
            _claim(repo, 7)
            _git(repo, "worktree", "remove", "--force",
                 str(tmp_path / f"repo-{status.replace(' ', '-')}-batch-7"), check=False)
            p = repo / "review_tasks.md"
            p.write_text(p.read_text().replace("Seven `Pending`", f"Seven `{status}`"))
            _git(repo, "add", "review_tasks.md")
            _git(repo, "commit", "-qm", "finish")

            rel = _run(BATCH_WORK, repo, "--release", "7")
            assert rel.returncode == 1
            assert "close_batch.sh 7" in rel.stderr, "the pointer must be actionable"

            r = _run(CLOSE_BATCH, repo, "7")
            assert r.returncode == 0, r.stderr
            assert not _lock(repo, 7).exists(), f"{status} stranded its lock"

    def test_release_rolls_back_review_tasks_when_the_commit_fails(self, tmp_path):
        """The failure message claimed the batch 'still reads as claimed'. The
        sed had already rewritten the file, every reader reads the working tree,
        so `--list` showed it Pending — and the prescribed re-run took the
        Pending arm, cleared the lock and never committed."""
        repo = _repo(tmp_path / "repo")
        _claim(repo, 8)
        hooks = Path(_git(repo, "rev-parse", "--git-path", "hooks").stdout.strip())
        if not hooks.is_absolute():
            hooks = repo / hooks
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text("#!/bin/sh\nexit 1\n")
        (hooks / "pre-commit").chmod(0o755)
        r = _run(BATCH_WORK, repo, "--release", "8")
        assert r.returncode == 1
        assert "`In Progress`" in (repo / "review_tasks.md").read_text(), (
            "a failed release must not leave the revert on disk"
        )
        assert _lock(repo, 8).is_file()
        # scoped to the file: the fixture repo has no .gitignore, so the
        # untracked sysop/runtime/ dir would otherwise read as a dirty tree
        assert _git(repo, "status", "--short", "--", "review_tasks.md").stdout.strip() == ""

    def test_main_checkout_guard_is_what_refuses_a_worktree_release(self, tmp_path):
        """The first version of this test passed under a mutation that deleted
        the guard's `exit 1`: its rc==1 came from the downstream 'Not on main'
        check and its stderr grep matched the echo the mutation left behind.
        The batch here is `Pending` in the worktree's frozen copy and
        `In Progress` on main — the state the guard actually protects, where
        the downstream checks would let the lock-only path run."""
        repo = _repo(tmp_path / "repo")
        # The scratch repo has no origin, so claim_batch skips the status flip:
        # the branch (and its worktree) are cut while the file still reads
        # Pending. Flipping main afterwards reproduces the divergence exactly.
        _claim(repo, 7)
        wt = tmp_path / "repo-batch-7"
        p = repo / "review_tasks.md"
        p.write_text(p.read_text().replace("Seven `Pending`", "Seven `In Progress`"))
        _git(repo, "add", "review_tasks.md")
        _git(repo, "commit", "-qm", "claim by hand")
        assert "Seven `Pending`" in (wt / "review_tasks.md").read_text(), (
            "precondition: the worktree copy is frozen at Pending"
        )
        r = _run(BATCH_WORK, wt, "--release", "7")
        assert r.returncode == 1
        assert _lock(repo, 7).is_file(), "the guard must stop before any mutation"
        assert "Releasing Batch" not in r.stdout, (
            "the guard must exit before the release banner — a surviving echo "
            "is not a refusal"
        )

    def test_a_colon_bearing_batch_title_still_yields_a_parseable_lock(self, tmp_path):
        """Real Sysop batch titles carry colons ('Batch 12 — /review-close:
        staging discipline'). Interpolating the title into `plan_summary:` makes
        the lock invalid YAML; sitrep then drops it from `lock_by_branch` and
        the batch reverts to 'pending (not claimed)'. The fixtures used
        colon-free titles, so no test could see it."""
        yaml = __import__("yaml")
        tasks = TASKS.replace("Seven `Pending`",
                              "/review-close: staging discipline `Pending`")
        repo = _repo(tmp_path / "repo", tasks=tasks)
        _claim(repo, 7)
        data = yaml.safe_load(_lock(repo, 7).read_text())
        assert data["task_id"] == "BATCH-7"
        assert data["branch"] == "review/batch-7", "branch lost to a YAML break"

    def test_workspace_is_the_worktree_not_the_main_checkout(self, tmp_path):
        """`Path(ws).is_dir()` alone passes when `workspace:` points at the main
        checkout — which makes scope_overlap read main's diff as the batch's
        in-flight scope."""
        yaml = __import__("yaml")
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        ws = Path(yaml.safe_load(_lock(repo, 7).read_text())["workspace"]).resolve()
        assert ws.is_dir()
        assert ws != repo.resolve(), "workspace must not be the main checkout"
        listed = _git(repo, "worktree", "list", "--porcelain").stdout
        assert str(ws) in listed, "workspace must be a registered worktree"

    def test_release_does_not_touch_a_neighbouring_batch(self, tmp_path):
        """The header sed is line-anchored; without the anchor, releasing one
        batch flipped the next one's status too."""
        tasks = TASKS + (
            "\n### Batch 9 — Nine `In Progress`\n\n"
            "> **Branch:** `review/batch-9`\n\n- [/] TASK-9 nine\n"
        )
        repo = _repo(tmp_path / "repo", tasks=tasks)
        _claim(repo, 8)
        assert _run(BATCH_WORK, repo, "--release", "8").returncode == 0
        text = (repo / "review_tasks.md").read_text()
        assert "### Batch 9 — Nine `In Progress`" in text, "neighbour was flipped"
        assert "- [/] TASK-9 nine" in text

    def test_release_force_removes_a_dirty_worktree(self, tmp_path):
        """No test ever made a batch worktree dirty, so dropping `--force` from
        the forced remove was invisible."""
        repo = _repo(tmp_path / "repo")
        _claim(repo, 8)
        (tmp_path / "repo-batch-8" / "scratch.txt").write_text("uncommitted\n")
        assert _run(BATCH_WORK, repo, "--release", "8").returncode == 1
        r = _run(BATCH_WORK, repo, "--release", "--force", "8")
        assert r.returncode == 0, r.stderr
        assert not (tmp_path / "repo-batch-8").exists()
        assert not _lock(repo, 8).exists()

    def test_only_the_batch_prefix_normalises(self, tmp_path):
        """A looser `^[A-Za-z]+-` would make `TECH-7` claim batch 7 — the exact
        claim-kind confusion this phase removes."""
        repo = _repo(tmp_path / "repo")
        for bad in ("TECH-7", "FOO-7"):
            r = _run(BATCH_WORK, repo, bad)
            assert r.returncode == 1, f"{bad} was accepted"
            assert "positive integer" in r.stderr
        assert not _lock(repo, 7).exists()

    def test_release_does_not_prefix_match_a_longer_batch_number(self, tmp_path):
        """`grep '^### Batch 7 '` keeps the trailing space so batch 7 cannot
        resolve to batch 70's section."""
        tasks = (
            "# Review Tasks\n\n### Batch 70 — Seventy `In Progress`\n\n"
            "> **Branch:** `review/batch-70`\n\n- [/] TASK-A a\n\n"
            "### Batch 7 — Seven `In Progress`\n\n"
            "> **Branch:** `review/batch-7`\n\n- [/] TASK-B b\n"
        )
        repo = _repo(tmp_path / "repo", tasks=tasks)
        _claim(repo, 7)
        assert _run(BATCH_WORK, repo, "--release", "7").returncode == 0
        text = (repo / "review_tasks.md").read_text()
        assert "### Batch 70 — Seventy `In Progress`" in text
        assert "### Batch 7 — Seven `Pending`" in text

    def test_claim_task_refuses_every_batch_id_casing(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        _claim(repo, 8)
        for form in ("BATCH-8", "batch-8", "Batch-8"):
            r = _run(CLAIM_TASK, repo, "--release", form)
            assert r.returncode == 1, f"{form} was not refused"
            assert "batch_work.sh --release 8" in r.stderr
        assert _lock(repo, 8).is_file()

    def test_dry_run_still_reports_its_summary(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        r = _run(CLOSE_BATCH, repo, "--dry-run", "--force", "7")
        assert r.returncode == 0, r.stderr
        assert "Closed: 7" in r.stdout
        assert "dry-run mode — no changes made" in r.stdout


# ─── Phase 159b: the third Step 2 entry state ───────────────────────────────
#
# `--entry-state` carries the decision (covered behaviourally in
# test_claim_task_sh.py::TestEntryState). What has no runtime, and so needs
# prose guards, is the skill's ROUTING on its answer: Step 2 must call it,
# Step 4a must not re-refuse a resume, and Step 4d must tolerate the empty
# commit a resume produces. All three are section-scoped — a rule stated
# anywhere in a 600-line file must not keep them green.


def _skill_subsection(heading_prefix, text=None):
    """One `### `-level subsection (Step 4's parts live at that depth)."""
    text = text if text is not None else CLAIM_SKILL.read_text(encoding="utf-8")
    m = re.search(
        rf"^### {re.escape(heading_prefix)}.*?$(.*?)(?=^#{{2,3}} )", text, re.M | re.S
    )
    assert m, f"subsection '{heading_prefix}' not found in claim-task/SKILL.md"
    return m.group(1)


def entry_state_problems(text=None):
    """Returns a list of problems; empty means clean."""
    problems = []
    step2 = _skill_section("Step 2", text)

    # The INSTRUCTION, not a mention, and not a commented-out one. A bare
    # substring check here survived `# bash …claim_task.sh --entry-state` in the
    # independent mutation sweep — the prose around it kept the words alive.
    #
    # The argument must be the LITERAL <TASK_ID> placeholder, matching Step 4b.
    # A `"$TASK_ID"` shell variable does not survive between skill steps (each
    # is a separate shell call, WORKFLOW.md § 8.2a), so it would expand empty
    # and hit the script's usage guard. The first draft of this guard pinned
    # the broken form and turned red on the fix.
    if not re.search(
        r"^\s*bash\s+\S*claim_task\.sh\s+--entry-state\s+<TASK_ID>\s*$", step2, re.M
    ):
        problems.append("Step 2 no longer invokes claim_task.sh --entry-state <TASK_ID>")
    if re.search(r"claim_task\.sh\s+--entry-state\s+[\"']?\$", step2):
        problems.append(
            "Step 2 passes the id via a shell variable, which does not survive "
            "between skill steps — use the literal <TASK_ID> placeholder"
        )
    # Each token must carry a table row AND that row must route to the right
    # ACTION. Presence-only checks let every row's Do column be inverted with
    # the suite green — `held` and `closed` could both be flipped to "Continue".
    routing = {
        "claimable": r"\bcontinue\b",
        "resumable": r"\bStop and ask\b",
        "held": r"\*\*Stop\.\*\*",
        r"closed:<status>": r"\*\*Stop\.\*\*",
        "absent": r"\*\*Stop\.\*\*",
    }
    for token, action in routing.items():
        m = re.search(rf"^\|\s*`{re.escape(token)}`\s*\|(.*)$", step2, re.M)
        if not m:
            problems.append(f"Step 2 no longer routes the `{token}` entry state")
        elif not re.search(action, m.group(1), re.I):
            problems.append(
                f"Step 2's `{token}` row no longer routes to its required action "
                f"(expected /{action}/)"
            )
    # The resume state must route to skipping 4a, or the flip re-fires.
    if not re.search(r"resumable.*?(?:skip|Skip).{0,40}(?:Step )?4a", step2, re.S):
        problems.append("Step 2 does not route `resumable` to skipping Step 4a's flip")
    # The exit-code mapping is what the caller branches on; scrambling it
    # mis-routes every failure mode, and nothing pinned it.
    for code, meaning in ((2, "no index"), (3, "no python3/PyYAML"),
                          (4, "unreadable index")):
        if not re.search(rf"`{code}` {re.escape(meaning)}", step2):
            problems.append(
                f"Step 2's --entry-state exit-code contract no longer maps "
                f"`{code}` to {meaning}"
            )
    # Batch clause — claim-task/SKILL.md:64's convention, and the trap this
    # phase's brief names: silence reads as "not applicable".
    if not re.search(r"\*\*Review batches:\*\*[^\n]*--entry-state[^\n]*refus", step2):
        problems.append(
            "Step 2 lacks the **Review batches:** clause stating --entry-state "
            "refuses a BATCH id"
        )
    # Exactly one. A rewrite of this step left two near-identical copies behind
    # (one of them carrying the stale "three-way check" wording), and the twin's
    # count=1 substitution then hit the wrong one and reported the guard green.
    if len(re.findall(r"^\*\*Review batches:\*\* `--entry-state`", step2, re.M)) != 1:
        problems.append(
            "Step 2 has a duplicated (or missing) **Review batches:** "
            "--entry-state clause"
        )
    # The metadata heredoc must not re-refuse in_progress — that would make the
    # resume unreachable one guard later while looking like defence in depth.
    if re.search(r'if status != "open":', step2):
        problems.append(
            "Step 2's metadata heredoc still hard-refuses every non-open status, "
            "which re-blocks the resume path"
        )

    step4a = _skill_subsection("4a.", text)
    if not re.search(r'current\s*==\s*"in_progress"', step4a):
        problems.append("Step 4a no longer branches on an already-in_progress resume")
    # Three separate facts, because a bare /resumed/ search matched all of them
    # and so survived each being broken individually: the flag is SET, the write
    # is GATED on it, and the gate is not a constant.
    if not re.search(r"^\s*resumed\s*=\s*True\s*$", step4a, re.M):
        problems.append("Step 4a no longer sets the resume sentinel")
    if not re.search(r"^\s*if\s+resumed\s*:", step4a, re.M):
        problems.append("Step 4a no longer gates the index write on the resume sentinel")
    # It must still refuse done/deferred — the resume branch must not have been
    # widened into "accept anything". Assert the REFUSAL (the non-zero exit),
    # not the message: replacing sys.exit(1) with `pass` left the message in
    # place and this check green in the sweep.
    if not re.search(
        r"refusing to flip status[^\n]*\n\s*sys\.exit\(1\)", step4a
    ):
        problems.append("Step 4a no longer refuses a done/deferred status")
    # ...and the refusal must be REACHABLE. An independent reviewer flipped the
    # guard's condition to `current is None`, which leaves every assertion above
    # satisfied while a `done` task falls through to the else-branch and gets
    # flipped to in_progress. Pin the comparison, not just the exit.
    if not re.search(r'elif\s+current\s*!=\s*"open"\s*:', step4a):
        problems.append(
            "Step 4a's refusal no longer tests `current != \"open\"`, so a "
            "closed task can fall through to the flip"
        )
    # The fresh-claim write must actually happen. Nothing asserted this, so
    # replacing the else-branch with `pass` — no claim ever flipping status —
    # left the whole suite green.
    if not re.search(r'else\s*:\s*\n\s*t\["status"\]\s*=\s*"in_progress"', step4a):
        problems.append(
            "Step 4a's else-branch no longer performs the open → in_progress "
            "flip, so a fresh claim would never be recorded"
        )

    step4d = _skill_subsection("4d.", text)
    # Match the COMMAND, not a mention of it. The paragraph below the snippet
    # explains why the test is there and contains the literal string, so a bare
    # substring check stays green with the command deleted — the exact
    # "narrative mention keeps the gate green" failure Phase 155 shipped, which
    # this guard reproduced on its first draft.
    # The PATHSPEC is part of the mechanism, not decoration: `git diff --cached
    # --quiet -- <a-path-that-is-never-staged>` exits 0, the `||` short-circuits,
    # and the claim commit silently never happens. `[^\n]*` swallowed it, so a
    # reviewer repointed the pathspec with the suite green.
    if not re.search(
        r"git diff --cached --quiet -- tasks/index\.yml\s*\\\n\s*\|\|\s*git commit",
        step4d,
    ):
        problems.append(
            "Step 4d lost the staged-diff test on tasks/index.yml, so either a "
            "resume's empty commit aborts or the claim commit never runs"
        )
    if not re.search(r'rev-parse --abbrev-ref HEAD.*?=\s*"?main', step4d, re.S):
        problems.append("Step 4d lost main-push-guard Rule A")
    return problems


class TestEntryStateProseGuards:
    def test_skill_routes_the_entry_state(self):
        assert entry_state_problems() == []

    def test_guard_catches_a_deleted_entry_state_call(self):
        text = CLAIM_SKILL.read_text(encoding="utf-8")
        softened = text.replace(
            "bash sysop/scripts/claim_task.sh --entry-state <TASK_ID>", "", 1)
        assert softened != text
        assert any("no longer invokes" in p for p in entry_state_problems(softened))

    def test_guard_catches_the_shell_variable_invocation_form(self):
        """`$TASK_ID` does not survive between skill steps — each is a separate
        shell call (WORKFLOW.md § 8.2a). The first draft of this step shipped
        that form, and the first draft of the guard PINNED it, so writing the
        correct placeholder form turned the suite red."""
        text = CLAIM_SKILL.read_text(encoding="utf-8")
        softened = text.replace(
            "bash sysop/scripts/claim_task.sh --entry-state <TASK_ID>",
            'bash sysop/scripts/claim_task.sh --entry-state "$TASK_ID"', 1)
        assert softened != text
        problems = entry_state_problems(softened)
        assert any("shell variable" in p for p in problems)

    def test_guard_catches_a_dropped_resumable_route(self):
        """Deleting only the `resumable` table ROW. The word survives elsewhere
        in Step 2's prose, so a presence check would stay green — this is the
        Phase-155 'narrative mention keeps the gate green' trap."""
        text = CLAIM_SKILL.read_text(encoding="utf-8")
        m = re.search(r"^\| `resumable` \|.*$", text, re.M)
        assert m, "the resumable row moved — update this twin, don't delete it"
        softened = text.replace(m.group(0), "")
        assert softened != text
        assert any("`resumable` entry state" in p
                   for p in entry_state_problems(softened))

    def test_guard_catches_an_inverted_row_action(self):
        """Presence-only row checks let every Do column be inverted with the
        suite green — an independent reviewer flipped `held` and `closed` to
        'Continue' and nothing failed."""
        text = CLAIM_SKILL.read_text(encoding="utf-8")
        for token in ("held", r"closed:<status>"):
            m = re.search(rf"^\| `{re.escape(token)}` \|([^|]*)\|([^|]*)\|$", text, re.M)
            assert m, f"the `{token}` row moved — update this twin"
            softened = text.replace(
                m.group(0),
                f"| `{token}` |{m.group(1)}| Continue; Step 4 will sort it out. |")
            assert softened != text
            assert any("no longer routes to its required action" in p
                       for p in entry_state_problems(softened)), \
                f"inverting the `{token}` row's action was not caught"

    def test_guard_catches_a_dropped_review_batch_clause(self):
        text = CLAIM_SKILL.read_text(encoding="utf-8")
        softened = re.sub(
            r"\*\*Review batches:\*\* `--entry-state` \*\*refuses\*\*",
            "Note: `--entry-state` also handles", text, count=1)
        assert softened != text
        assert any("Review batches:" in p for p in entry_state_problems(softened))

    def test_guard_catches_a_reinstated_open_only_status_refusal(self):
        text = CLAIM_SKILL.read_text(encoding="utf-8")
        softened = text.replace(
            'if status not in ("open", "in_progress"):', 'if status != "open":', 1)
        assert softened != text
        assert any("re-blocks the resume path" in p for p in entry_state_problems(softened))

    def test_guard_catches_a_step4a_that_refuses_in_progress_again(self):
        text = CLAIM_SKILL.read_text(encoding="utf-8")
        softened = text.replace('if current == "in_progress":',
                                'if current == "__never__":', 1)
        assert softened != text
        assert any("already-in_progress resume" in p
                   for p in entry_state_problems(softened))

    def test_guard_catches_a_step4a_widened_to_accept_anything(self):
        """The resume branch must not become a blanket accept — done/deferred
        still has to refuse, or a closed task gets silently re-claimed."""
        text = CLAIM_SKILL.read_text(encoding="utf-8")
        softened = text.replace(
            'print(f"ERROR: refusing to flip status; current status=\'{current}\'", file=sys.stderr)',
            'pass', 1)
        assert softened != text
        assert any("no longer refuses a done/deferred" in p
                   for p in entry_state_problems(softened))

    def test_guard_catches_a_step4d_without_the_empty_commit_tolerance(self):
        text = CLAIM_SKILL.read_text(encoding="utf-8")
        softened = text.replace(
            'git diff --cached --quiet -- tasks/index.yml \\\n  || git commit',
            'git commit', 1)
        assert softened != text
        assert any("staged-diff test" in p for p in entry_state_problems(softened))
