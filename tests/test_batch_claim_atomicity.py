"""Phase 256 — the claim path's writes after `claim_batch`, and the near-miss
population that was narrower than the class it named.

`Q-382` and `Q-375`.

**The `Q-382` tests all call the real script with a fixture and assert on what
it DID** — exit codes, files on disk, tracker contents, lock bytes — for the
reason `test_batch_status_gate.py` states at length: a guard that string-matches
the fix survives the fix being deleted.

**Three deliberate exceptions, named because an earlier draft of this docstring
said "none matches source text" and that was false of seven methods.** The
`Q-375` classes call the parsers in-process (they are pure functions over lines,
and a subprocess would add nothing); two methods assert on the compiled patterns
directly, to state that a population did NOT move; and
`test_the_workflow_rule_this_depends_on_is_still_shipped` reads `WORKFLOW.md` and
asserts two substrings, which is its whole job.

## `Q-382` — three reproduced states, one decide-then-write fix

Phase 254 closed `Q-378` by making `claim_batch` refuse before writing. The
branch/worktree/lock writes *below* that call were out of its scope, so a claim
could still half-succeed at exit 0:

* **(a)** the worktree gate was `[[ -d "$WORKTREE_DIR" ]]`, and a directory is
  not a worktree — any directory at that path made the claim skip
  `git worktree add` and write the lock anyway, at exit 0, advertising a
  `workspace:` that is not a repository.
* **(b)** a `Pending` batch carrying a lock adopted it verbatim. The
  already-claimed announcement fires only on the `In Progress` arm, so a lock
  naming another branch and workspace was taken over in silence.
* **(c)** `review_tasks.md` **untracked** defeated the precondition — `git diff`
  and `git diff --cached` are both blind to an untracked file — so the rewrite
  landed, the commit failed on a pathspec matching nothing, and the rollback
  (`git checkout --`, `|| true`) could not restore a file git had never seen.
  The run ended printing "the claim was rolled back, nothing was claimed" over a
  tracker left flipped to `In Progress`.

**Two corrections to the filing, both established by running it.** The filing
said `--release` *guarantees* state (a)'s orphan directory. It does not: plain
`--release`, `--release --force` over a dirty worktree, and
`cleanup_worktrees.sh --clean` all remove the directory, and a failed
`git worktree add` never creates one (it aborts at 128, before the lock). What
*does* produce it is a worktree that has lost its `.git` — and checking that
turned up a defect nobody filed, covered by `TestReleaseRecoversABrokenWorktree`
below: such a batch was **unreleasable by any shipped command**, because
`git worktree remove` and `--force` both refuse it, so the lock was never
removed and `next_task.py` skips a locked batch forever. That is the exact harm
`--release` exists to prevent, reached through the front door.

## `Q-375` — the detector widens, the boundary twin does not

The filing proposed widening `_BATCH_HEADER_ANY_RE` across its four copies, and
called the leading-space shape "the sharpest of the five" on the grounds that
`_FENCE_OPEN_RE` already encodes `^ {0,3}`. **That is refuted by
`WORKFLOW.md` § 4 line 624**, which ships the two-space indent as the ratified
way to write a batch header no reader parses — chosen over a fence because
Phase 208 measured fence-based separation false-firing on 98.2% of opener
positions, and stated for all six readers by name. Column 0 is the contract that
makes the escape hatch work.

So the split is by what each shape IS:

    boundary twin  (unchanged)  ^###\\s+Batch\\s+\\d+\\b
    near-miss      (widened)    ^#{2,4}\\s*Batch\\s+\\d+\\b   (IGNORECASE)

`TestTheBoundaryTwinStaysAtColumnZero` is the guard against a future phase
making the filing's change. One of its methods drives the real parser end to
end; the other three assert on the patterns, deliberately — the claim being
pinned is that a population did not widen, and there is no behaviour to observe
when nothing changed. (An earlier draft of that class's docstring claimed all
four were end-to-end.)
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
BATCH_WORK = SCRIPTS / "batch_work.sh"

sys.path.insert(0, str(SCRIPTS))
import review_index as ri  # noqa: E402
import archive_review_tasks as art  # noqa: E402


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


def _tasks(batches):
    """Same shape as `test_batch_status_gate._tasks` — the metadata block is a
    blockquote and the script refuses a batch without a `Branch:` line."""
    out = ["# Review Tasks", ""]
    for n, status in batches:
        out += [
            f"### Batch {n} — Batch {n} title `{status}`",
            "",
            f"> **Branch:** `review/batch-{n}`",
            f"> **Scope:** scope-{n}",
            f"> **Verify:** pytest -k batch{n}",
            "",
            f"- [ ] **TASK-{n:04d}**: task for batch {n}",
            "",
        ]
    return "\n".join(out) + "\n"


def _repo(root, batches=((1, "Pending"),)):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "review_tasks.md").write_text(_tasks(list(batches)))
    (root / "README.md").write_text("# seed\n")
    sd = root / "sysop" / "scripts"
    sd.mkdir(parents=True)
    for name in ("batch_work.sh", "close_batch.sh", "_log.py", "_git_lib.sh",
                 "review_index.py", "cleanup_worktrees.sh"):
        src = SCRIPTS / name
        if src.exists():
            shutil.copy(src, sd / name)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _bw(repo, *args):
    return subprocess.run(["bash", str(BATCH_WORK), *args],
                          cwd=str(repo), capture_output=True, text=True)


def _lock(repo, n):
    return repo / "sysop" / "runtime" / "locks" / f"BATCH-{n}.lock"


def _wt(repo, n):
    return repo.parent / f"{repo.name}-batch-{n}"


def _status_of(repo, n):
    for line in (repo / "review_tasks.md").read_text().splitlines():
        if line.startswith(f"### Batch {n} "):
            return line.rsplit("`", 2)[-2]
    raise AssertionError(f"no header for batch {n}")


def _head_status(repo, n):
    """The status as COMMITTED, which is the half a rollback has to restore."""
    blob = _git(repo, "show", "HEAD:review_tasks.md").stdout
    for line in blob.splitlines():
        if line.startswith(f"### Batch {n} "):
            return line.rsplit("`", 2)[-2]
    raise AssertionError(f"no committed header for batch {n}")


# ══════════════════════════════════════════════════════════════════════
# Q-382 (a) — a directory is not a worktree
# ══════════════════════════════════════════════════════════════════════

class TestAPlainDirectoryAtTheWorktreePath:

    def test_the_claim_refuses_and_writes_nothing(self, tmp_path):
        repo = _repo(tmp_path / "proj")
        _wt(repo, 1).mkdir()
        before = _git(repo, "rev-parse", "HEAD").stdout.strip()

        r = _bw(repo, "1")

        assert r.returncode != 0, "a claim over a non-worktree directory must refuse"
        assert not _lock(repo, 1).exists(), (
            "the lock is the harm: it makes the batch read as claimed"
        )
        assert _status_of(repo, 1) == "Pending", "the tracker was flipped anyway"
        assert _head_status(repo, 1) == "Pending"
        assert _git(repo, "rev-parse", "HEAD").stdout.strip() == before, (
            "the status flip was committed before the refusal"
        )
        assert "review/batch-1" not in _git(
            repo, "branch", "--format=%(refname:short)").stdout.split()

    def test_a_real_worktree_at_the_path_still_proceeds(self, tmp_path):
        """The refusal must not swallow the resume it looks like.

        Without this the fix could be `[[ -e ]] && exit 1`, which refuses the
        documented re-run of an in-flight batch — the case /auto-fix and
        /auto-judge drive in a loop.
        """
        repo = _repo(tmp_path / "proj")
        assert _bw(repo, "1").returncode == 0
        assert (_wt(repo, 1) / ".git").exists()

        r = _bw(repo, "1")

        assert r.returncode == 0, r.stderr
        assert _status_of(repo, 1) == "In Progress"

    def test_an_empty_dot_git_inside_an_outer_repo_is_not_this_worktree(self, tmp_path):
        """The toplevel comparison, and the state that makes it load-bearing.

        `-e "$p/.git"` alone is not enough and neither is `rev-parse`
        succeeding. An **empty `.git` directory** — what an interrupted
        `git worktree add` or a half-deleted worktree leaves — passes the
        existence test, and `rev-parse --show-toplevel` then WALKS UP and
        answers with the enclosing repository's root. Measured:

            -e .git:  yes
            toplevel: <outer repo>     ← not the path
            -ef:      NO

        Without the `-ef` comparison the predicate returns true, the claim
        skips `git worktree add`, writes the lock, and points `workspace:` at a
        directory belonging to a different repository. The batch worktree lives
        at `../<project>-batch-<N>`, so an outer repo above the primary is an
        ordinary layout, not a contrived one.

        This phase's battery found it: `M02` survived the first cut, and the
        first replacement test used a symlink into another checkout — which has
        no `.git` of its own, so it refused under BOTH spellings and measured
        nothing. The probe is what separated a live hole from a no-op.
        """
        outer = tmp_path / "outer"
        subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q",
                        str(outer)], check=True, capture_output=True)
        repo = _repo(outer / "proj")
        wt = _wt(repo, 1)
        wt.mkdir()
        (wt / ".git").mkdir()           # empty: exists, but names no repository

        r = _bw(repo, "1")

        assert r.returncode != 0, (
            "an empty .git inside an outer repo is not this batch's worktree"
        )
        assert not _lock(repo, 1).exists()
        assert _status_of(repo, 1) == "Pending"
        assert _head_status(repo, 1) == "Pending"

    def test_a_DANGLING_symlink_at_the_worktree_path_is_refused(self, tmp_path):
        """`-e` FOLLOWS the link, so a dangling one is invisible to it — while
        `git worktree add` lstats and refuses, which put the failure back below
        the commit: measured at exit 128 with the status already committed
        `In Progress`. `-L` is what sees the link itself.

        Found by this phase's round.
        """
        repo = _repo(tmp_path / "proj")
        _wt(repo, 1).symlink_to(tmp_path / "nowhere")
        assert not _wt(repo, 1).exists()          # -e is false: it follows
        assert _wt(repo, 1).is_symlink()          # -L is true: it does not

        r = _bw(repo, "1")

        assert r.returncode != 0
        assert _status_of(repo, 1) == "Pending"
        assert _head_status(repo, 1) == "Pending"
        assert not _lock(repo, 1).exists()

    def test_the_refusal_names_the_path_and_a_command(self, tmp_path):
        repo = _repo(tmp_path / "proj")
        _wt(repo, 1).mkdir()
        r = _bw(repo, "1")
        assert str(_wt(repo, 1).resolve().name) in r.stderr
        assert "not a git worktree" in r.stderr


# ══════════════════════════════════════════════════════════════════════
# Q-382 (b) — a Pending batch that already holds a lock
# ══════════════════════════════════════════════════════════════════════

class TestAPendingBatchThatAlreadyHoldsALock:

    FOREIGN = (
        "task_id: BATCH-1\nstatus: in_progress\nagent: someone-else\n"
        "branch: feat/SOMEONE-ELSE\nworkspace: /tmp/not-mine\n"
        "started: 2026-01-01T00:00:00Z\n"
    )

    def _seed(self, repo):
        d = repo / "sysop" / "runtime" / "locks"
        d.mkdir(parents=True, exist_ok=True)
        (d / "BATCH-1.lock").write_text(self.FOREIGN)

    def test_the_claim_refuses_rather_than_adopting_it(self, tmp_path):
        repo = _repo(tmp_path / "proj")
        self._seed(repo)

        r = _bw(repo, "1")

        assert r.returncode != 0
        assert _lock(repo, 1).read_text() == self.FOREIGN, (
            "the foreign lock was rewritten or taken over"
        )
        assert _status_of(repo, 1) == "Pending"
        assert _head_status(repo, 1) == "Pending"

    def test_the_refusal_shows_whose_claim_it_is(self, tmp_path):
        """A refusal that does not name the holder cannot be acted on."""
        repo = _repo(tmp_path / "proj")
        self._seed(repo)
        r = _bw(repo, "1")
        assert "feat/SOMEONE-ELSE" in r.stderr
        assert "--release 1" in r.stderr

    def test_an_in_progress_batch_with_a_lock_still_resumes(self, tmp_path):
        """The scope that makes the refusal safe.

        `write_batch_lock` is idempotent because `batch_work.sh <N>` is
        re-runnable — /auto-fix and /auto-judge call it in a loop. The
        re-runnable case is `In Progress` + lock and it keeps its Phase 191
        announcement. Only `Pending` + lock refuses. If this test goes red the
        refusal has been widened into a new abort in three skills' fan-out.
        """
        repo = _repo(tmp_path / "proj")
        assert _bw(repo, "1").returncode == 0
        stamp = _lock(repo, 1).read_text()

        r = _bw(repo, "1")

        assert r.returncode == 0, r.stderr
        assert "already claimed" in r.stdout
        assert _lock(repo, 1).read_text() == stamp, (
            "the resume overwrote the lock it was announcing"
        )


# ══════════════════════════════════════════════════════════════════════
# Q-382 (c) — an untracked tracker defeats the rollback
# ══════════════════════════════════════════════════════════════════════

class TestAnUntrackedReviewTasksFile:

    def _untrack(self, repo):
        _git(repo, "rm", "--cached", "-q", "review_tasks.md")
        _git(repo, "commit", "-qm", "untrack")

    def test_the_claim_refuses_before_rewriting_the_tracker(self, tmp_path):
        repo = _repo(tmp_path / "proj")
        self._untrack(repo)
        before = (repo / "review_tasks.md").read_text()

        r = _bw(repo, "1")

        assert r.returncode != 0
        assert (repo / "review_tasks.md").read_text() == before, (
            "the tracker was rewritten and could not be restored"
        )
        assert _status_of(repo, 1) == "Pending"
        assert not _lock(repo, 1).exists()

    def test_it_does_not_claim_success_over_a_flipped_tracker(self, tmp_path):
        """The precise shape of the bug: the message and the disk disagreed.

        Before the fix this printed "the claim was rolled back, nothing was
        claimed" with the tracker reading `In Progress`.
        """
        repo = _repo(tmp_path / "proj")
        self._untrack(repo)

        r = _bw(repo, "1")

        said_rolled_back = "rolled back" in r.stderr
        flipped = _status_of(repo, 1) != "Pending"
        assert not (said_rolled_back and flipped), (
            "reported a rollback over a tracker that stayed flipped"
        )
        assert "not tracked" in r.stderr

    def test_a_tracked_but_dirty_tracker_still_gets_its_own_message(self, tmp_path):
        """Two states, two remedies. One message covering both names neither."""
        repo = _repo(tmp_path / "proj")
        (repo / "review_tasks.md").write_text(
            (repo / "review_tasks.md").read_text() + "\nstray edit\n")

        r = _bw(repo, "1")

        assert r.returncode != 0
        assert "uncommitted changes" in r.stderr
        assert "not tracked" not in r.stderr


# ══════════════════════════════════════════════════════════════════════
# Q-382 (d) — the tempfile the round could not force
# ══════════════════════════════════════════════════════════════════════

class TestTheRewriteTempfileIsNotAFixedPath:

    def test_no_fixed_tmp_survives_a_claim_or_a_release(self, tmp_path):
        repo = _repo(tmp_path / "proj")
        _bw(repo, "1")
        _bw(repo, "--release", "1")
        strays = sorted(p.name for p in repo.iterdir() if p.name.endswith(".tmp"))
        assert strays == [], f"tempfiles orphaned beside the tracker: {strays}"

    def test_a_claim_is_unaffected_by_an_obstruction_at_the_OLD_fixed_path(self, tmp_path):
        """Deterministic stand-in for a race nothing can force.

        **The window is NOT unforceable, and an earlier draft of this docstring
        said it was.** This phase's round forced it on its first attempt: two
        backgrounded claims on different batches in one repo produce a stranded
        batch in about half of trials (measured 4 of 8 post-fix, and the round
        measured 6 of 10 PRE-fix — the class is pre-existing and the PID
        qualification does not touch it). See `Q-387`, filed § High.

        What this test therefore covers is narrower than the race: the property
        the fix actually changes, which is that the rewrite no longer goes
        through `review_tasks.md.tmp`. Putting an unwritable obstruction at that
        exact path makes the pre-fix code fail and leaves the fix untouched, so
        it kills a revert without asserting anything about source text — but it
        is not evidence that concurrent claims are safe, and nothing here is.

        Found by this phase's own battery (`T01` survived the first cut: the
        orphan-sweep test passes under both spellings, because the fixed path
        cleaned up after itself too).
        """
        repo = _repo(tmp_path / "proj")
        (repo / "review_tasks.md.tmp").mkdir()      # `>` cannot write to a dir

        r = _bw(repo, "1")

        assert r.returncode == 0, r.stderr
        assert _status_of(repo, 1) == "In Progress"
        assert _lock(repo, 1).is_file()

    def test_a_release_is_unaffected_by_an_obstruction_at_the_OLD_fixed_path(self, tmp_path):
        """`--release` carried the identical fixed path; the filing named only
        the claim site (`T02`)."""
        repo = _repo(tmp_path / "proj")
        assert _bw(repo, "1").returncode == 0
        (repo / "review_tasks.md.tmp").mkdir()

        r = _bw(repo, "--release", "1")

        assert r.returncode == 0, r.stderr
        assert _status_of(repo, 1) == "Pending"
        assert not _lock(repo, 1).exists()

    def test_the_tracker_keeps_its_mode_across_a_claim(self, tmp_path):
        """`mktemp` would have been the obvious uniquifier and it creates at
        0600, which `mv` then carries onto the file every reader opens."""
        repo = _repo(tmp_path / "proj")
        before = (repo / "review_tasks.md").stat().st_mode
        assert _bw(repo, "1").returncode == 0
        assert (repo / "review_tasks.md").stat().st_mode == before


# ══════════════════════════════════════════════════════════════════════
# Found in passing — a batch nothing could release
# ══════════════════════════════════════════════════════════════════════

class TestReleaseRecoversABrokenWorktree:
    """Not in the filing. `git worktree remove` refuses a registered worktree
    whose `.git` is gone — "validation failed" — and so does `--force`, so both
    arms exited 1 with "Nothing was released — the claim is intact." The lock
    was never removed, the remedy the message offered was the one that had just
    failed, and `next_task.py` skips a locked batch forever.
    """

    def _break(self, repo):
        wt = _wt(repo, 1)
        assert _bw(repo, "1").returncode == 0
        shutil.rmtree(wt)
        wt.mkdir()
        return wt

    def test_an_empty_leftover_is_pruned_and_removed(self, tmp_path):
        repo = _repo(tmp_path / "proj")
        wt = self._break(repo)

        r = _bw(repo, "--release", "1")

        assert r.returncode == 0, r.stderr
        assert not _lock(repo, 1).exists(), "the lock outlived the release"
        assert _status_of(repo, 1) == "Pending"
        assert not wt.exists()

    def test_the_batch_is_claimable_again_afterwards(self, tmp_path):
        """The whole point: recovery has to reach a state a claim accepts."""
        repo = _repo(tmp_path / "proj")
        self._break(repo)
        assert _bw(repo, "--release", "1").returncode == 0

        r = _bw(repo, "1")

        assert r.returncode == 0, r.stderr
        assert (_wt(repo, 1) / ".git").exists()

    def test_a_leftover_holding_files_is_released_but_not_deleted(self, tmp_path):
        """`prune` clears the registration; the directory is an operator's data.

        The claim-side refusal names it rather than this arm deleting it.
        """
        repo = _repo(tmp_path / "proj")
        wt = self._break(repo)
        (wt / "operator.txt").write_text("mine\n")

        r = _bw(repo, "--release", "1")

        assert r.returncode == 0, r.stderr
        assert not _lock(repo, 1).exists()
        assert (wt / "operator.txt").read_text() == "mine\n", (
            "release deleted a file it did not create"
        )
        assert _bw(repo, "1").returncode != 0, (
            "and the claim must still refuse while that directory sits there"
        )

    def test_it_does_not_deregister_a_BYSTANDER_worktree(self, tmp_path):
        """The first cut of this arm ran a bare `git worktree prune`, and that
        is data loss: prune takes no target and de-registers EVERY prunable
        worktree in the repository.

        Measured by this phase's round — a bystander worktree that had merely
        been moved aside lost its admin directory, and with it its index, HEAD
        and reflog. `git worktree repair` could not recover it.
        """
        repo = _repo(tmp_path / "proj")
        _git(repo, "branch", "feature/mine")
        mine = tmp_path / "mine"
        _git(repo, "worktree", "add", "-q", str(mine), "feature/mine")
        admin = repo / ".git" / "worktrees" / "mine"
        assert admin.is_dir()
        shutil.move(str(mine), str(tmp_path / "mine-moved"))   # an ordinary rename
        self._break(repo)

        assert _bw(repo, "--release", "1").returncode == 0

        assert admin.is_dir(), "the bystander's administrative record was destroyed"
        shutil.move(str(tmp_path / "mine-moved"), str(mine))
        st = subprocess.run(["git", "-C", str(mine), "status"],
                            capture_output=True, text=True)
        assert st.returncode == 0, f"the bystander no longer works: {st.stderr}"

    def test_a_SECOND_broken_batch_still_reaches_the_recovery_arm(self, tmp_path):
        """The same defect from the other side, and the sharper case.

        A repo-global prune de-registers the OTHER broken batch too, so its own
        `--release` then takes the "No worktree holds" branch, reports success
        at exit 0, and leaves the orphan directory the claim-side refusal
        rejects — this arm manufacturing the very state it exists to clear, for
        every batch but the first.
        """
        repo = _repo(tmp_path / "proj", [(1, "Pending"), (2, "Pending")])
        for n in (1, 2):
            assert _bw(repo, str(n)).returncode == 0
        for n in (1, 2):
            shutil.rmtree(_wt(repo, n))
            _wt(repo, n).mkdir()

        assert _bw(repo, "--release", "1").returncode == 0
        r = _bw(repo, "--release", "2")

        assert r.returncode == 0, r.stderr
        assert not _wt(repo, 2).exists(), (
            "batch 2's orphan survived — its registration was pruned as collateral, "
            "so its release never reached the recovery arm"
        )
        assert not _lock(repo, 2).exists()
        assert _bw(repo, "2").returncode == 0, "and batch 2 must be claimable again"

    def test_recovery_works_from_a_SUBDIRECTORY(self, tmp_path):
        """`git rev-parse --git-common-dir` answers relative to the CWD.

        Left relative, the admin-record scan looks under `.git/worktrees` and
        finds it only when the caller stands at the repo root — so the recovery
        silently did nothing from anywhere else, while still reporting success.
        The CWD-relative class, at a fourth site. Found by this phase's second
        battery (`P06`).
        """
        repo = _repo(tmp_path / "proj")
        wt = self._break(repo)
        sub = repo / "sysop" / "scripts"

        r = subprocess.run(["bash", str(BATCH_WORK), "--release", "1"],
                           cwd=str(sub), capture_output=True, text=True)

        assert r.returncode == 0, r.stderr
        assert not _lock(repo, 1).exists()
        assert not wt.exists(), "the leftover survived — the scan found no record"
        reg = _git(repo, "worktree", "list", "--porcelain").stdout
        assert "proj-batch-1" not in reg, "the stale registration survived"

    def test_a_DIRECTORY_at_the_lock_path_refuses_BEFORE_the_commit(self, tmp_path):
        """The second battery asked whether `-f` should be `-e`; the answer was
        neither alone.

        A directory there is not a claim, so the "already holds a lock" message
        is wrong for it — but it is still fatal, because `write_batch_lock`
        fails on it *after* `claim_batch` has committed the flip. Measured
        before the fix: exit 1 with the status committed `In Progress` and a raw
        `Is a directory` redirection error. Two states, two messages, both
        refusing above the commit.
        """
        repo = _repo(tmp_path / "proj")
        locks = repo / "sysop" / "runtime" / "locks"
        locks.mkdir(parents=True, exist_ok=True)
        (locks / "BATCH-1.lock").mkdir()

        r = _bw(repo, "1")

        assert r.returncode != 0
        assert "not a regular file" in r.stderr, (
            "refused, but with the wrong diagnosis:\n" + r.stderr)
        assert "already holds a lock" not in r.stderr
        assert _status_of(repo, 1) == "Pending"
        assert _head_status(repo, 1) == "Pending", (
            "the status flip was committed before the refusal"
        )

    def test_a_healthy_worktree_is_still_removed_normally(self, tmp_path):
        """The recovery arm must not capture the ordinary release."""
        repo = _repo(tmp_path / "proj")
        assert _bw(repo, "1").returncode == 0

        r = _bw(repo, "--release", "1")

        assert r.returncode == 0, r.stderr
        assert not _wt(repo, 1).exists()
        assert not _lock(repo, 1).exists()


# ══════════════════════════════════════════════════════════════════════
# Q-375 — the near-miss population, and the boundary that did not move
# ══════════════════════════════════════════════════════════════════════

WIDENED = [
    "## Batch 4 — Title `Pending`",
    "#### Batch 4 — Title `Pending`",
    "###Batch 4 — Title `Pending`",
    "### BATCH 4 — Title `Pending`",
]


def _tracker_with(line):
    return (
        "# Review Tasks\n\n"
        "### Batch 1 — Real `Pending`\n\n"
        "> **Branch:** `review/batch-1`\n\n"
        "- [ ] **TASK-0001**: a\n\n"
        f"{line}\n\n"
        "- [ ] **TASK-0002**: b\n\n"
        "## Statistics\n"
    ).splitlines()


class TestTheNearMissDetectorReachesTheWholeClass:

    @pytest.mark.parametrize("line", WIDENED)
    def test_each_widened_shape_is_now_reported(self, line):
        hits = ri.near_miss_batch_headers(_tracker_with(line))
        assert [h[2] for h in hits] == [line]

    @pytest.mark.parametrize("line", WIDENED)
    def test_both_twins_agree_on_the_widened_shapes(self, line):
        lines = _tracker_with(line)
        assert [h[0] for h in art.near_miss_batch_headers(lines)] == \
               [h[0] for h in ri.near_miss_batch_headers(lines)]

    @pytest.mark.parametrize("line", WIDENED)
    def test_the_number_is_recovered_from_each(self, line):
        """`describe_near_misses` reports the line; callers route on the number,
        and a `None` here would silently degrade the report."""
        hits = ri.near_miss_batch_headers(_tracker_with(line))
        assert hits[0][1] == "4"

    @pytest.mark.parametrize("line", WIDENED)
    def test_a_widened_shape_inside_a_fence_is_still_excluded(self, line):
        lines = (
            "# Review Tasks\n\n"
            "### Batch 1 — Real `Pending`\n\n"
            "> **Branch:** `review/batch-1`\n\n"
            f"```\n{line}\n```\n\n"
            "## Statistics\n"
        ).splitlines()
        assert ri.near_miss_batch_headers(lines) == []
        assert art.near_miss_batch_headers(lines) == []


class TestTheArchiverGateIsNarrowerThanTheReport:
    """`Q-375` widened a population that feeds a HARD whole-run refusal.

    `archive_review_tasks.py` calls `near_miss_batch_headers` and `sys.exit(1)`s
    on any hit. Feeding the widened population straight in was wrong twice:
    the refusal's stated harm ("VISIBLE to its batch counter, so archiving would
    relocate the batches around it") is true only of a line the BOUNDARY twin
    matches, and the four added shapes bound nothing — and it made an ordinary
    prose heading a hard blocker. Found by this phase's round.
    """

    ARCHIVER = SCRIPTS / "archive_review_tasks.py"

    def _tracker(self, tail):
        return (
            "# Review Tasks\n\n## Round 1\n\n"
            "### Batch 1 — Real `Merged`\n\n> **Branch:** `review/batch-1`\n\n"
            "- [x] **TASK-0001**: a\n\n" + tail
        )

    def _archive(self, tmp_path, tail):
        repo = _repo(tmp_path / "proj")
        shutil.copy(self.ARCHIVER, repo / "sysop/scripts/archive_review_tasks.py")
        (repo / "review_tasks.md").write_text(self._tracker(tail))
        return subprocess.run(
            [sys.executable, str(repo / "sysop/scripts/archive_review_tasks.py")],
            cwd=str(repo), capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=60)

    def test_an_operator_prose_heading_does_not_block_archiving(self, tmp_path):
        r = self._archive(tmp_path, "## Batch 1 retrospective\n\nnotes here\n")
        assert r.returncode == 0, (
            "a prose heading became a hard whole-run blocker:\n" + r.stderr)
        assert "WARNING" in r.stderr, "it should still be reported, just not fatal"
        assert "refusing to archive" not in r.stderr

    def test_a_widened_shape_warns_and_says_it_is_not_blocking(self, tmp_path):
        r = self._archive(tmp_path, "## Batch 4 — Title `Pending`\n\n- [ ] **T**: c\n")
        assert r.returncode == 0, r.stderr
        assert "bound nothing" in r.stderr
        assert "NOT blocked" in r.stderr

    def test_the_refusal_lists_only_the_lines_it_is_refusing_over(self, tmp_path):
        """A message that names lines it is not gating on sends the operator to
        fix the wrong thing. Found by this phase's second battery (`G05`): the
        gate can be scoped while the report is not, and rc plus a substring
        cannot tell the difference.
        """
        r = self._archive(
            tmp_path,
            "### Batch 2 - ascii hyphen `Pending`\n\n- [ ] **T**: b\n\n"
            "## Batch 9 — bounds nothing `Pending`\n\n- [ ] **T**: c\n")
        assert r.returncode == 1, r.stderr
        block = r.stderr.split("refusing to archive", 1)[1]
        block = block.split("Fix the header(s)", 1)[0]
        assert "ascii hyphen" in block, "the bounding line must be named"
        assert "bounds nothing" not in block, (
            "the refusal named a line it is not refusing over:\n" + block)
        assert "has 1 batch header(s)" in r.stderr, (
            "the count must match the gated set, not the whole population")

    def test_a_near_miss_that_really_BOUNDS_still_refuses(self, tmp_path):
        """The refusal must survive the narrowing — this is the case its
        message describes, and the one that truncates a predecessor."""
        r = self._archive(
            tmp_path, "### Batch 2 - ascii hyphen `Pending`\n\n- [ ] **T**: b\n")
        assert r.returncode == 1, (
            "the real near-miss stopped being refused:\n" + r.stderr)
        assert "refusing to archive" in r.stderr
        assert "VISIBLE to its batch counter" in r.stderr


class TestTheBoundaryTwinStaysAtColumnZero:
    """The guard against a future phase making `Q-375`'s proposed change.

    `WORKFLOW.md` § 4 line 624 ships the two-space indent as the sanctioned way
    to write a batch header no reader parses.

    `test_an_indented_example_does_not_end_the_batch_above_it` asserts the
    escape hatch still WORKS, through the real parser. The other three assert on
    the compiled patterns, which is the honest shape for them: what is being
    pinned is that a population did NOT widen, and a population that did not
    move produces no behaviour to observe. An earlier draft of this docstring
    claimed all four were end-to-end; the round caught it.
    """

    @pytest.mark.parametrize("line", WIDENED)
    def test_a_widened_shape_is_reported_but_does_not_bound(self, line):
        """Reported and not a boundary: the two patterns answer different
        questions, and collapsing them is what the filing proposed."""
        lines = _tracker_with(line)
        assert ri.near_miss_batch_headers(lines), "should be reported"
        assert not ri._BATCH_HEADER_ANY_RE.match(line), "must not bound"

    def test_an_indented_example_is_invisible_to_every_reader(self):
        indented = "  ### Batch 9 — indented example `Pending`"
        lines = _tracker_with(indented)
        assert ri.near_miss_batch_headers(lines) == [], (
            "reporting the documented escape hatch is over-reporting"
        )
        assert art.near_miss_batch_headers(lines) == []
        assert not ri._BATCH_HEADER_ANY_RE.match(indented)
        assert not art.ANY_BATCH_HEADER_RE.match(indented)
        assert not art.H3_HEADER_RE.match(indented)

    def test_an_indented_example_does_not_end_the_batch_above_it(self, tmp_path):
        """The consumer-visible half, run through the real parser.

        If the twin is widened, the indented example becomes a boundary and the
        tasks below it stop belonging to Batch 1 — silently, on every consumer
        tracker whose author followed the shipped rule.
        """
        # `_repo_root()` walks up from the SCRIPT's location, not the CWD, so
        # this has to drive the vendored copy inside a fixture repo — which is
        # also how a consumer runs it.
        repo = _repo(tmp_path / "proj")
        tracker = repo / "review_tasks.md"
        tracker.write_text("\n".join(_tracker_with(
            "  ### Batch 9 — indented example `Pending`")) + "\n")
        r = subprocess.run(
            [sys.executable, str(repo / "sysop/scripts/review_index.py"),
             "--rebuild"], cwd=str(repo), capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        r = subprocess.run(
            [sys.executable, str(repo / "sysop/scripts/review_index.py"),
             "--range", "1"], cwd=str(repo), capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        start, end = (int(x) for x in r.stdout.split("\t")[:2])
        body = tracker.read_text().splitlines()[start - 1:end]
        assert any("TASK-0002" in ln for ln in body), (
            "the indented example ended Batch 1 — the escape hatch is broken"
        )

    def test_the_workflow_rule_this_depends_on_is_still_shipped(self):
        """A behavioural guard cannot see its own premise being deleted.

        If this fails, `WORKFLOW.md` no longer promises column-0-only matching
        and the tests above are defending a rule that no longer exists — decide
        the contract before re-pointing them.
        """
        text = (REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md").read_text()
        assert "Indent the example by two spaces" in text
        assert "matched at **column 0 only**" in text
