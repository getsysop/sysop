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
import re
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


# ── Phase 157: a FAIL verdict must not close the task ──────────
#
# `/auto-judge` has three verdicts; only two of them resolve a task. FIX does the
# work and DROP adjudicates the premise away, so both are legitimately `[x]` at
# merge. FAIL means the task is real and was *not* done — and until Phase 157
# `close_batch.sh` flipped it anyway, so `review_tasks.md` (the durable record of
# what a round resolved) overstated that by however many tasks failed, and the
# Grand Total drifted with it (upstream #207).
#
# The `> Dropped:` case is pinned here deliberately, not incidentally: the
# upstream report's own first fix would have stopped flipping it, which would
# contradict the three shipped sites that tell agents to leave a dropped task
# `[ ]` *precisely so this script counts it*, and would break Grand Total
# accounting. Dropped is not the bug; it must keep closing.
FAILURE_TASKS = """\
# Review Tasks

### Batch 1 — Mixed verdicts `Pending`

- [ ] **TASK-1**: fixed thing
- [ ] **TASK-2**: dropped thing
  > Dropped: premise was wrong
- [ ] **TASK-3**: failed thing
  > Failed: needs a cross-module signature change
- [/] **TASK-4**: in-progress thing

### Batch 2 — Every task failed `Pending`

- [ ] **TASK-5**: failed thing
  > Failed: out of scope for this batch

## Statistics

**Grand Total** — 5 done, 10 open
"""


class TestFailedTaskAccounting:
    def test_failed_task_keeps_its_checkbox_while_siblings_close(self, tmp_path):
        repo = _repo(tmp_path / "repo", tasks=FAILURE_TASKS)
        r = _run(repo, "1")
        assert r.returncode == 0, r.stderr
        text = (repo / "review_tasks.md").read_text()
        assert "- [x] **TASK-1**: fixed thing" in text
        assert "- [ ] **TASK-3**: failed thing" in text
        # The batch still merges — "this batch shipped, but this item didn't".
        assert "### Batch 1 — Mixed verdicts `Merged`" in text

    def test_dropped_task_is_still_closed(self, tmp_path):
        # Guards the deliberate shipped convention (auto-judge § Verdicts,
        # auto-fix Step 3, WORKFLOW.md § 2.7b): a DROP leaves `[ ]` so that THIS
        # script closes it. Anything that stops flipping it is a regression.
        repo = _repo(tmp_path / "repo", tasks=FAILURE_TASKS)
        assert _run(repo, "1").returncode == 0
        text = (repo / "review_tasks.md").read_text()
        assert "- [x] **TASK-2**: dropped thing" in text
        assert "> Dropped: premise was wrong" in text

    def test_in_progress_task_without_annotation_still_closes(self, tmp_path):
        repo = _repo(tmp_path / "repo", tasks=FAILURE_TASKS)
        assert _run(repo, "1").returncode == 0
        assert "- [x] **TASK-4**: in-progress thing" in (repo / "review_tasks.md").read_text()

    def test_failed_task_is_excluded_from_the_closed_count(self, tmp_path):
        repo = _repo(tmp_path / "repo", tasks=FAILURE_TASKS)
        r = _run(repo, "1")
        assert "Marked as Merged (3 tasks closed, 1 failed — still open)" in r.stdout

    def test_failed_task_never_reaches_the_grand_total(self, tmp_path):
        # 4 open boxes in Batch 1, but only 3 resolve → 5+3 done, 10-3 open.
        # A failed task stays counted as open, which is what makes it honest.
        repo = _repo(tmp_path / "repo", tasks=FAILURE_TASKS)
        assert _run(repo, "1").returncode == 0
        assert "8 done, 7 open" in (repo / "review_tasks.md").read_text()

    def test_batch_of_only_failed_tasks_merges_closing_nothing(self, tmp_path):
        repo = _repo(tmp_path / "repo", tasks=FAILURE_TASKS)
        r = _run(repo, "2")
        assert r.returncode == 0, r.stderr
        assert "Marked as Merged (0 tasks closed, 1 failed — still open)" in r.stdout
        text = (repo / "review_tasks.md").read_text()
        assert "### Batch 2 — Every task failed `Merged`" in text
        assert "- [ ] **TASK-5**: failed thing" in text
        # Nothing closed → the Grand Total is left exactly as it was.
        assert "5 done, 10 open" in text

    def test_dry_run_reports_the_failed_count(self, tmp_path):
        repo = _repo(tmp_path / "repo", tasks=FAILURE_TASKS)
        before = (repo / "review_tasks.md").read_text()
        r = _run(repo, "--dry-run", "1")
        assert r.returncode == 0, r.stderr
        assert "3 tasks → [x]" in r.stdout
        assert "Failed tasks: 1 left open" in r.stdout
        assert (repo / "review_tasks.md").read_text() == before

    def test_bold_failed_annotation_is_honored(self, tmp_path):
        # review_tasks.md writes its other `> **Key:**` metadata bolded, so an
        # agent drifting to `> **Failed:**` must not silently lose the task.
        tasks = FAILURE_TASKS.replace(
            "  > Failed: needs a cross-module signature change",
            "  > **Failed:** needs a cross-module signature change",
        )
        repo = _repo(tmp_path / "repo", tasks=tasks)
        r = _run(repo, "1")
        assert "Marked as Merged (3 tasks closed, 1 failed — still open)" in r.stdout
        assert "- [ ] **TASK-3**: failed thing" in (repo / "review_tasks.md").read_text()

    def test_unannotated_batch_is_unaffected(self, tmp_path):
        # The no-failures path must behave exactly as it did before Phase 157 —
        # same count, same message shape, no "failed" clause.
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "1")
        assert "Marked as Merged (2 tasks closed)." in r.stdout
        assert "failed" not in r.stdout

    def test_annotation_counts_for_the_nearest_task_in_its_block(self, tmp_path):
        # WAS `test_annotation_only_counts_for_the_line_above_it`, which asserted
        # BOTH tasks below close — and was therefore pinning the defect upstream
        # internal tracker #398 reported. Its fixture is structurally the shape
        # the shipped generators emit (bullet, indented continuation, annotation),
        # and there is no syntactic discriminator between its "prose" line and a
        # real `file:line` continuation: both are `^\s+\S`. Asserting the
        # annotation is ignored there is asserting it is ignored everywhere it
        # actually appears.
        #
        # The concern the test was written to defend is legitimate and is kept:
        # a stray annotation must not shield some ARBITRARY task further up the
        # file. What changed is the reach — nearest preceding task bullet within
        # its own block, and no further. TASK-1 owns the indented lines under it,
        # so TASK-1 is held; TASK-2 is a separate block and closes normally.
        tasks = (
            "# Review Tasks\n\n"
            "### Batch 9 — Stray annotation `Pending`\n\n"
            "- [ ] **TASK-1**: first\n"
            "  some prose about the batch\n"
            "  > Failed: attached to TASK-1, which owns this block\n"
            "- [ ] **TASK-2**: second\n"
        )
        repo = _repo(tmp_path / "repo", tasks=tasks)
        r = _run(repo, "9")
        assert r.returncode == 0, r.stderr
        assert "Marked as Merged (1 tasks closed, 1 failed — still open)." in r.stdout
        text = (repo / "review_tasks.md").read_text()
        assert "- [ ] **TASK-1**: first" in text, text
        assert "- [x] **TASK-2**: second" in text, text

    def test_the_scan_does_not_run_past_the_block_it_started_in(self, tmp_path):
        # The other half of the old test's concern, now pinned on its own: an
        # annotation separated from the task by a blank line, or sitting under a
        # LATER task, must never reach back to an earlier one.
        tasks = (
            "# Review Tasks\n\n"
            "### Batch 9 — Out of reach `Pending`\n\n"
            "- [ ] **TASK-1**: must close\n"
            "  its own continuation line\n"
            "\n"
            "- [ ] **TASK-2**: must be held\n"
            "  > Failed: belongs to TASK-2 alone\n"
        )
        repo = _repo(tmp_path / "repo", tasks=tasks)
        r = _run(repo, "9")
        assert r.returncode == 0, r.stderr
        text = (repo / "review_tasks.md").read_text()
        assert "- [x] **TASK-1**: must close" in text, text
        assert "- [ ] **TASK-2**: must be held" in text, text


class TestShortWriteGuard:
    """`pipefail` catches a stage that reports failure, not one that lies.

    Found by Phase 157's adversarial round. The rewrite became a two-process
    pipeline (`sed | awk`), so there are two chances for a stage to exit 0
    having written short — and the `mv` that follows is unrecoverable. The
    reviewer demonstrated it with an `awk` shim doing `head -2; exit 0`:
    review_tasks.md was truncated from 157 bytes to 16 and *committed*, rc=0.
    """

    def _with_lying_awk(self, tmp_path, shim_body):
        repo = _repo(tmp_path / "repo")
        binder = tmp_path / "bin"
        binder.mkdir()
        shim = binder / "awk"
        shim.write_text(shim_body)
        shim.chmod(0o755)
        import os
        env = dict(os.environ, PATH=f"{binder}:{os.environ['PATH']}")
        return repo, subprocess.run(
            ["bash", str(SCRIPT), "1"],
            cwd=str(repo), capture_output=True, text=True, env=env,
        )

    def test_truncating_awk_cannot_destroy_review_tasks(self, tmp_path):
        repo, r = self._with_lying_awk(tmp_path, "#!/bin/sh\nhead -2\nexit 0\n")
        assert r.returncode == 1, r.stdout
        assert "refusing to install it" in r.stderr
        assert (repo / "review_tasks.md").read_text() == BASE_TASKS

    def test_empty_output_cannot_destroy_review_tasks(self, tmp_path):
        repo, r = self._with_lying_awk(tmp_path, "#!/bin/sh\ncat >/dev/null\nexit 0\n")
        assert r.returncode == 1, r.stdout
        assert (repo / "review_tasks.md").read_text() == BASE_TASKS

    def test_no_close_commit_is_made_when_the_rewrite_is_rejected(self, tmp_path):
        repo, r = self._with_lying_awk(tmp_path, "#!/bin/sh\nhead -2\nexit 0\n")
        assert "close-batch commit present: 1" not in r.stdout


# ── Phase 157 round: the annotation decision must be loud ──────
#
# The adversarial round drove the real script against every shape an agent
# plausibly writes and found each of them SILENTLY closing the task, with the
# failure note left sitting underneath — the exact rendering upstream #207
# reported. `> FAILED:` mattered most: all-caps FAILED is /auto-judge's own
# vocabulary — `TASKS_FAILED:`, `FAILED —` and `Tasks Marked FAILED` — i.e.
# everywhere except the one place the read side looked. (Named by TOKEN, not
# by line: the line numbers this comment carried, `:300`/`:304`/`:360`, had
# drifted to `:385`/`:389`/`:446` and pointed at unrelated prose.)
#
# The round also found the inverse: a task whose next line quotes error output
# starting `> Failed:` was held open and dropped from the Grand Total, equally
# silently. Widening the matcher fixes the first and worsens the second, so the
# resolution is not a better regex — it is to report every decision. A dead item
# and a clean one must not produce identical evidence (Phases 135/143).

LOUD_TASKS = """\
# Review Tasks

### Batch 1 — Shapes `Pending`

- [ ] **T1**: plain, closes
- [ ] **T2**: caps annotation
  > FAILED: the vocabulary auto-judge uses elsewhere
- [ ] **T3**: no space after the marker
  >Failed: tight
- [ ] **T4**: near miss, closes but must warn
  > Fail: singular
- [ ] **T5**: dropped, closes and must NOT warn
  > Dropped: the test was failing for an unrelated reason
"""


class TestAnnotationIsLoud:
    def test_all_caps_failed_is_honoured(self, tmp_path):
        repo = _repo(tmp_path / "repo", tasks=LOUD_TASKS)
        r = _run(repo, "1")
        assert "- [ ] **T2**: caps annotation" in (repo / "review_tasks.md").read_text()
        assert r.returncode == 0, r.stderr

    def test_missing_space_after_marker_is_honoured(self, tmp_path):
        repo = _repo(tmp_path / "repo", tasks=LOUD_TASKS)
        _run(repo, "1")
        assert "- [ ] **T3**: no space after the marker" in (repo / "review_tasks.md").read_text()

    def test_every_held_task_is_named_on_stdout(self, tmp_path):
        repo = _repo(tmp_path / "repo", tasks=LOUD_TASKS)
        r = _run(repo, "1")
        assert "held open (line 6)" in r.stdout, r.stdout
        assert "held open (line 8)" in r.stdout, r.stdout
        assert "3 tasks closed, 2 failed" in r.stdout

    def test_near_miss_is_reported_not_guessed_at(self, tmp_path):
        # T4 closes — the matcher does not guess — but the run says out loud
        # that it saw an annotation-shaped line it did not act on.
        repo = _repo(tmp_path / "repo", tasks=LOUD_TASKS)
        r = _run(repo, "1")
        assert "- [x] **T4**: near miss, closes but must warn" in (repo / "review_tasks.md").read_text()
        # STDOUT, not stderr. /review-close Step 4b tells the operator to read
        # stdout, so a warning written to stderr was addressed to nobody.
        assert "looks like a failure note but was NOT recognised" in r.stdout, r.stdout
        assert "line 11" in r.stdout
        assert "Failure-note near misses not honoured: 1" in r.stdout, r.stdout

    def test_dropped_line_mentioning_failing_produces_no_noise(self, tmp_path):
        # A warning that fires on ordinary prose gets ignored, and an ignored
        # warning is the same as no warning.
        repo = _repo(tmp_path / "repo", tasks=LOUD_TASKS)
        r = _run(repo, "1")
        assert "T5" not in r.stderr, r.stderr

    def test_detached_annotation_is_reported_as_protecting_nothing(self, tmp_path):
        tasks = (
            "# Review Tasks\n\n### Batch 2 — Detached `Pending`\n\n"
            "- [ ] **T1**: blank line below\n\n"
            "  > Failed: attached to nothing\n"
        )
        repo = _repo(tmp_path / "repo", tasks=tasks)
        r = _run(repo, "2")
        assert "- [x] **T1**: blank line below" in (repo / "review_tasks.md").read_text()
        # STDOUT, not stderr — this is the warning that noticed six failed tasks
        # closing in the reported round, and it was being written to the stream
        # /review-close Step 4b never tells the operator to read.
        assert "protects nothing" in r.stdout, r.stdout
        assert "Annotations protecting nothing: 1" in r.stdout, r.stdout

    def test_in_progress_task_can_also_be_held(self, tmp_path):
        # /auto-judge says "leave the checkbox exactly as you found it", so `[/]`
        # is a first-class FAIL state. Nothing exercised it before the round.
        tasks = (
            "# Review Tasks\n\n### Batch 3 — In progress `Pending`\n\n"
            "- [/] **T1**: claimed then failed\n  > Failed: out of scope\n"
        )
        repo = _repo(tmp_path / "repo", tasks=tasks)
        r = _run(repo, "3")
        assert "- [/] **T1**: claimed then failed" in (repo / "review_tasks.md").read_text()
        assert "0 tasks closed, 1 failed" in r.stdout


class TestBlastRadius:
    """The rewrite went from line-addressed `sed` to an awk pass that reprints
    every line, so the tool's blast radius went from "the addressed lines" to
    "the whole file" — and the round found four mutations that corrupt every
    line while the suite stayed green (a prepended blank line on each close,
    all blank lines deleted, a marker appended to every closed task, trailing
    whitespace stripped file-wide).
    """

    def _closed_diff(self, tmp_path, tasks=BASE_TASKS, batch="1"):
        repo = _repo(tmp_path / "repo", tasks=tasks)
        before = (repo / "review_tasks.md").read_text().splitlines()
        _run(repo, batch)
        after = (repo / "review_tasks.md").read_text().splitlines()
        return before, after

    def test_line_count_is_preserved(self, tmp_path):
        before, after = self._closed_diff(tmp_path)
        assert len(before) == len(after), (
            "the close changed the file's line count — the rewrite must "
            "substitute, never insert or delete"
        )

    def test_only_checkbox_and_status_lines_change(self, tmp_path):
        before, after = self._closed_diff(tmp_path)
        changed = [(b, a) for b, a in zip(before, after) if b != a]
        assert changed, "nothing changed at all — the fixture is not exercising a close"
        for b, a in changed:
            assert (b.startswith("- [") and a.startswith("- [x]")) or "`" in b, (
                f"a line outside the checkbox/status shapes was rewritten:\n"
                f"  before: {b!r}\n  after:  {a!r}"
            )

    def test_blank_lines_survive_a_close(self, tmp_path):
        before, after = self._closed_diff(tmp_path)
        assert [i for i, l in enumerate(before) if l == ""] == \
               [i for i, l in enumerate(after) if l == ""]

    def test_nothing_is_appended_to_closed_task_lines(self, tmp_path):
        _, after = self._closed_diff(tmp_path)
        for line in after:
            if line.startswith("- [x]"):
                assert not line.rstrip().endswith("-->"), f"marker appended: {line!r}"
                assert line == line.rstrip(), f"trailing whitespace introduced: {line!r}"


class TestMatcherAnchoringAndNoOps:
    """Two mutations survived the first replay of the round's set; both are here.

    Neither is exotic — they are the kind of quiet defect that only shows up
    when you ask "what observable thing would change if this were wrong?"
    """

    def test_failure_note_must_start_the_line(self):
        # Dropping the `^` from is_failed makes any line CONTAINING an
        # annotation-shaped fragment hold the task above it open — so ordinary
        # prose that quotes the marker mid-sentence would silently remove a task
        # from the batch and from the Grand Total.
        import subprocess

        prog = re.search(
            r"readonly CLOSE_AWK='(.*?)'\n",
            (REPO_ROOT / "core/companion/scripts/close_batch.sh").read_text(),
            re.S,
        ).group(1)
        doc = (
            "### Batch 1 — B `Pending`\n"
            "- [ ] **T1**: a\n"
            "  the runner emits `> Failed:` as its prefix; fix that\n"
        )
        out = subprocess.run(
            ["awk", "-v", "s=1", "-v", "e=9", "-v", "mode=count", prog],
            input=doc, capture_output=True, text=True,
        ).stdout.strip()
        assert out == "1 0", (
            f"a mid-line mention held the task open (got {out!r}, want '1 0') — "
            "is_failed must be anchored to the start of the line"
        )

    def test_no_grand_total_block_when_nothing_closes(self, tmp_path):
        # `-gt 0` guards the Grand Total rewrite. Relaxing it to `-ge 0` is
        # invisible in the file (adding zero changes nothing) but produces a
        # spurious "Would update: 5 done → 5 done" and, on a real run, an extra
        # no-op atomic rewrite of review_tasks.md.
        tasks = (
            "# Review Tasks\n\n### Batch 7 — All failed `Pending`\n\n"
            "- [ ] **T1**: a\n  > Failed: x\n\n"
            "## Statistics\n\n**Grand Total** — 5 done, 10 open\n"
        )
        repo = _repo(tmp_path / "repo", tasks=tasks)
        r = _run(repo, "--dry-run", "7")
        assert r.returncode == 0, r.stderr
        assert "0 tasks → [x]" in r.stdout
        assert "Grand Total" not in r.stdout, (
            "a batch that closes nothing must not print a Grand Total update"
        )
