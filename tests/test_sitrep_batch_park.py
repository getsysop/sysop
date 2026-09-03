"""A parked review batch is visible to `/sitrep` (Phase 248, `Q-317`).

`_claim_stall` was always claim-kind agnostic *as a function* — it treats
`BATCH-<N>` as an ordinary claim id, and the runtime paths agree, since both
claim kinds key their artifacts by `<CLAIM_ID>` (`sysop/runtime/parked/
<CLAIM_ID>__<RUN_ID>.md`, `sysop/runtime/claim/<CLAIM_ID>/`). What it had was
exactly one call site, `_classify_task`, which `run_survey`'s lock loop never
reaches for a batch: it `continue`s on the `BATCH-`/`TASK-` prefix first.

So a `/claim-task` Step-7c park of a review batch — the case
`tools/CLAIM_TASK_ORCHESTRATOR_SPEC.md` calls *"exactly the case internal
tracker #220 reported"* — classified as `in progress — continue work; 0 of N
tasks have Doc-Work trailers yet`. Identical to a claim that had not started:
the two states produced the same evidence, which is the whole defect.

These tests drive `_classify_review_batches` and `_recommended_next` against a
real on-disk park, rather than calling `_claim_stall` directly. Phase 237's
guard called the helper directly and so could not see that the path around it
was inert — Phase 155's failure mode reproduced inside a test that invoked
Phase 155 by name, which is what `Q-317` was filed out of.
"""
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

import sitrep_survey as ss

REPO_ROOT = Path(__file__).resolve().parents[1]

_TASKS = """\
# Review Tasks

### Batch 1 — First batch `Pending`

> **Branch:** `review/batch-1`

- [ ] **TASK-601**: task one
"""


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root, tasks):
    """A scratch repo carrying `review_tasks.md`. Local to this module: no test
    module here imports a sibling, and pytest's rootdir does not put `tests/` on
    `sys.path`."""
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


def _batch(number=7, status="Pending", branch="review/batch-7", tasks=None):
    return {
        "number": number,
        "title": f"Batch {number}",
        "status": status,
        "branch": branch,
        "flag_reason": "",
        "triaged_date": "2026-08-30",
        "triaged_verdict": "auto",
        "triaged_tasks": [],
        "tasks": tasks if tasks is not None else [
            {"id": "TASK-601", "checkbox": " "},
            {"id": "TASK-602", "checkbox": " "},
        ],
    }


def _lock(branch="review/batch-7", task_id="BATCH-7"):
    return ss.Lock(
        path=Path(f"/tmp/locks/{task_id}.lock"),
        task_id=task_id,
        branch=branch,
        started="2026-08-30T12:00:00Z",
        raw={},
    )


def _classify(tmp_path, batches, locks, *, has_branch=True, commits=None):
    """Drive the real classifier with git stubbed and a real `tmp_path` root."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "_git", lambda *a, **k: "abc123" if has_branch else "")
        mp.setattr(ss, "_commits_ahead_of_main", lambda *a, **k: commits or [])
        return ss._classify_review_batches(batches, locks, [], tmp_path)


def _park(tmp_path, claim_id="BATCH-7", run_id="20260830T120000Z-abcd1234"):
    d = tmp_path / "sysop/runtime/parked"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{claim_id}__{run_id}.md").write_text("reason: waiting on a decision\n")


def _run_dir(tmp_path, claim_id="BATCH-7",
             run_id="20260830T120000Z-abcd1234", verdict=None, outcome=False):
    d = tmp_path / "sysop/runtime/claim" / claim_id / run_id
    d.mkdir(parents=True, exist_ok=True)
    if verdict is not None:
        (d / "classification.md").write_text(f"verdict: {verdict}\n")
    if outcome:
        (d / "outcome.md").write_text("done\n")
    return d


# ─────────────────────────────────────────────────────────────────────────────
# The defect
# ─────────────────────────────────────────────────────────────────────────────

def test_a_parked_batch_is_not_reported_as_in_progress(tmp_path):
    """**The filed defect.** The park marker is on disk under the batch's own
    claim id, and the batch reported ordinary unstarted work."""
    _park(tmp_path)
    out = _classify(tmp_path, [_batch()], [_lock()])

    assert len(out) == 1
    assert out[0].state == ss._PARKED_STATE, (
        f"a parked batch classified as {out[0].state!r} — the state a claim that "
        f"never started also produces.\nnext_action={out[0].next_action!r}"
    )
    assert "0 of 2 tasks have Doc-Work trailers" not in out[0].next_action


def test_the_park_evidence_reaches_the_notes(tmp_path):
    """The state alone is not actionable — the marker filename is the evidence,
    and `notes` is the field `--json` already ships it in."""
    _park(tmp_path)
    out = _classify(tmp_path, [_batch()], [_lock()])
    assert any("park marker on disk" in n for n in out[0].notes), out[0].notes
    assert any("BATCH-7__" in n for n in out[0].notes), out[0].notes


def test_the_resume_command_names_the_batch_claim_id(tmp_path):
    """`/claim-task` accepts `BATCH-<N>` (its Step 0 routing table), and the run
    directory is keyed by `<CLAIM_ID>`. A `--resume` line naming anything else
    would be an instruction that does not run."""
    _park(tmp_path)
    _run_dir(tmp_path, verdict="BLOCKED")
    out = _classify(tmp_path, [_batch()], [_lock()])
    assert "/claim-task BATCH-7 --resume 20260830T120000Z-abcd1234" in out[0].next_action, (
        out[0].next_action
    )


def test_a_blocked_verdict_with_no_marker_is_still_a_park(tmp_path):
    """The second arm of the probe, on the batch path: the park is real, the
    marker is not, and the report says which."""
    _run_dir(tmp_path, verdict="BLOCKED")
    out = _classify(tmp_path, [_batch()], [_lock()])
    assert out[0].state == ss._PARKED_STATE, out[0].state
    assert any("no park marker is on disk" in n for n in out[0].notes), out[0].notes


def test_an_unanswered_step_7d_gate_is_awaiting_approval(tmp_path):
    _run_dir(tmp_path, verdict="PROCEED")
    out = _classify(tmp_path, [_batch()], [_lock()])
    assert out[0].state == ss._AWAITING_STATE, out[0].state
    assert "approve or revise the plan" in out[0].next_action


def test_an_answered_gate_is_not_awaiting_approval(tmp_path):
    """The negative control for the arm above: once `outcome.md` exists the gate
    was answered and the batch is ordinary in-progress work again."""
    _run_dir(tmp_path, verdict="PROCEED", outcome=True)
    out = _classify(tmp_path, [_batch()], [_lock()])
    assert out[0].state not in (ss._PARKED_STATE, ss._AWAITING_STATE), out[0].state


# ─────────────────────────────────────────────────────────────────────────────
# The probe does not fire where it should not
# ─────────────────────────────────────────────────────────────────────────────

def test_an_ordinary_unstarted_batch_is_unchanged(tmp_path):
    """**The polarity that matters.** Absence of artifacts is never read as a
    park — `_claim_stall` returns `("", "", [])` with no positive evidence, and
    the pre-existing arms must be exactly as they were."""
    out = _classify(tmp_path, [_batch()], [_lock()])
    assert out[0].state == "in progress"
    assert "0 of 2 tasks have Doc-Work trailers yet" in out[0].next_action


def test_an_unclaimed_pending_batch_is_still_pending_not_claimed(tmp_path):
    """A stray marker must not promote an unclaimed batch into a park: the probe
    is gated on the batch holding a lock."""
    _park(tmp_path)
    out = _classify(tmp_path, [_batch()], [])
    assert out[0].state == "pending (not claimed)", out[0].state


def _commit(when, doc_work_ids=()):
    return ss.Commit(sha="a" * 7, subject="work", author_date=when,
                     doc_work_ids=list(doc_work_ids), subject_task_id=None)


def _touch(path, when):
    import os
    ts = when.timestamp()
    os.utime(path, (ts, ts))


def test_a_batch_that_parked_after_producing_commits_is_parked_with_work(tmp_path):
    """`Q-362`. This test used to assert `in progress` for a marker beside one
    commit, on the premise that "a claim that has produced commits is moving".
    Two shipped park sites refute the premise (`planner-integrity.md` =
    `VIOLATED` is DEFINED as the planner having committed; an executor
    `STATUS: BLOCKED` parks after the executor ran), and Phase 248's round
    reproduced the result this pin protected: a parked batch reporting
    `in progress — continue work`. The park is the LATEST event here — the
    marker is newer than the commit — so the batch is parked, with work."""
    _park(tmp_path)
    marker = next((tmp_path / "sysop/runtime/parked").iterdir())
    _touch(marker, datetime(2026, 8, 30, 13, 0, tzinfo=timezone.utc))
    commits = [_commit(datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc))]
    out = _classify(tmp_path, [_batch()], [_lock()], commits=commits)
    assert out[0].state == ss._PARKED_WIP_STATE, out[0].state
    assert any("park marker on disk" in n for n in out[0].notes), out[0].notes
    assert any("park is the latest event" in n for n in out[0].notes), out[0].notes
    # No run directory in this fixture (an `/auto-build`-shaped park), so the
    # action names the marker rather than a `--resume` that could not work.
    assert "BATCH-7__" in out[0].next_action, out[0].next_action


def test_a_batch_that_resumed_after_a_park_is_not_parked(tmp_path):
    """The refinement the old pin was protecting, kept: a `--resume` never
    removes a park marker (the close does, and `--release` does), so between a
    `--resume` and the close a live batch carries a marker beside its NEW commits. The commit is newer than the
    marker → the batch resumed → its ordinary state, with the marker noted so
    the evidence is not dropped."""
    _park(tmp_path)
    marker = next((tmp_path / "sysop/runtime/parked").iterdir())
    _touch(marker, datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc))
    commits = [_commit(datetime(2026, 8, 30, 13, 0, tzinfo=timezone.utc))]
    out = _classify(tmp_path, [_batch()], [_lock()], commits=commits)
    assert out[0].state == "in progress", out[0].state
    assert any("predates the newest commit" in n for n in out[0].notes), out[0].notes


def test_a_park_with_work_outranks_ready_for_review_close(tmp_path):
    """A park is a human decision pending; the trailer state of the commits it
    parked on does not answer it. Every task Doc-Work'd AND a park newer than
    the last commit → parked with work, not ready."""
    _park(tmp_path)
    marker = next((tmp_path / "sysop/runtime/parked").iterdir())
    _touch(marker, datetime(2026, 8, 30, 13, 0, tzinfo=timezone.utc))
    commits = [_commit(datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
                       doc_work_ids=["TASK-601", "TASK-602"])]
    out = _classify(tmp_path, [_batch()], [_lock()], commits=commits)
    assert out[0].state == ss._PARKED_WIP_STATE, out[0].state


def test_an_empty_batch_still_reports_empty(tmp_path):
    """Arm ordering: `empty batch` is a structural problem worth naming, and it
    is checked before the stall arm."""
    _park(tmp_path)
    out = _classify(tmp_path, [_batch(tasks=[])], [_lock()])
    assert out[0].state == "empty batch", out[0].state


def test_a_branchless_claim_still_reports_branchless(tmp_path):
    """Arm ordering (`Q-363`): the branchless diagnosis wins — and since Phase
    252 the park evidence rides along in `notes` instead of being dropped, and
    the `next_action` names the release path."""
    _park(tmp_path)
    out = _classify(tmp_path, [_batch()], [_lock()], has_branch=False)
    assert out[0].state == "claimed, no branch", out[0].state
    assert any("park marker on disk" in n for n in out[0].notes), out[0].notes
    assert "--release 7" in out[0].next_action, out[0].next_action


def test_the_marker_must_match_this_batchs_claim_id(tmp_path):
    """A park on BATCH-9 says nothing about BATCH-7. Guards the argument passed
    to the probe: `f"BATCH-{b['number']}"`, not some other id."""
    _park(tmp_path, claim_id="BATCH-9")
    out = _classify(tmp_path, [_batch(number=7)], [_lock()])
    assert out[0].state == "in progress", out[0].state


# ─────────────────────────────────────────────────────────────────────────────
# Both consumers, because one without the other makes the report contradict itself
# ─────────────────────────────────────────────────────────────────────────────

def _survey(batches):
    return ss.Survey(
        timestamp=datetime(2026, 8, 31, tzinfo=timezone.utc),
        main_root=Path("/tmp/x"),
        head_short="abc1234",
        stale_days=7,
        tasks=[],
        review_batches=batches,
        discrepancies=[],
        open_roadmap_ids=[],
    )


@pytest.mark.parametrize("state,phrase", [
    (ss._PARKED_STATE, "is parked and is waiting on a human decision"),
    (ss._AWAITING_STATE, "waiting on your approval"),
])
def test_recommended_next_routes_the_batch_states(tmp_path, state, phrase):
    _park(tmp_path) if state == ss._PARKED_STATE else _run_dir(tmp_path, verdict="PROCEED")
    out = _classify(tmp_path, [_batch()], [_lock()])
    assert out[0].state == state, out[0].state

    rec = ss._recommended_next(_survey(out))
    assert rec is not None, "no recommendation for a stalled batch"
    assert phrase in rec.reason, rec.reason
    assert "Batch 7" in rec.reason, rec.reason
    assert rec.command == out[0].next_action
    assert rec.detail_lines == out[0].notes


@pytest.mark.parametrize("state,phrase", [
    (ss._PARKED_STATE, "Batch 7 is parked —"),
    (ss._AWAITING_STATE, "Batch 7 awaits your approval —"),
])
def test_suggested_order_lists_the_batch_states(tmp_path, state, phrase):
    """`Q-019`'s round: a state wired into `_recommended_next` and not into
    `_suggested_order` drops out of the ordered list entirely, and the report
    then contradicts itself three lines apart."""
    _park(tmp_path) if state == ss._PARKED_STATE else _run_dir(tmp_path, verdict="PROCEED")
    out = _classify(tmp_path, [_batch()], [_lock()])
    order = ss._suggested_order(_survey(out))
    assert any(phrase in line for line in order), order


def test_the_json_contract_is_additive(tmp_path):
    """The `/roadmap --json` question the filing raised, answered by execution:
    no new keys, no reshape — the two states are new values of the existing
    `review_batches[].state`, with evidence in the existing `notes`."""
    import json

    _park(tmp_path)
    out = _classify(tmp_path, [_batch()], [_lock()])
    payload = json.loads(ss.render_json(_survey(out)))
    rb = payload["review_batches"][0]
    assert rb["state"] == ss._PARKED_STATE
    assert any("park marker on disk" in n for n in rb["notes"])
    # The key set is exactly what it was — this is the assertion that would
    # catch a reshape smuggled in beside the new value.
    assert set(rb) == {
        "batch_number", "title", "md_status", "branch", "has_lock", "has_branch",
        "has_flag", "flag_reason", "has_triage_record", "triaged_verdict",
        "triaged_tasks", "total_tasks", "doc_worked_tasks", "state",
        "next_action", "notes",
    }, sorted(rb)


def test_an_in_progress_batch_without_a_lock_is_not_probed(tmp_path):
    """**Battery survivor `SS-1`, closed.**

    `test_an_unclaimed_pending_batch_is_still_pending_not_claimed` looked like it
    covered the `has_lock` half of the probe's gate and did not: with `has_lock`
    dropped from the gate, a **Pending** batch takes the `pending (not claimed)`
    arm first and returns before the stall arm is ever reached, so that test
    passes against a gate with the condition removed.

    An **In Progress** batch with no lock is the shape that reaches the stall arm.
    A lock is what makes a claim a claim; without one there is no run to resume
    and no claim to park, so a stray marker must not manufacture one.
    """
    _park(tmp_path)
    out = _classify(tmp_path, [_batch(status="In Progress")], [])
    assert out[0].state not in (ss._PARKED_STATE, ss._AWAITING_STATE), (
        f"an unlocked batch was classified {out[0].state!r} from a marker alone"
    )
    assert out[0].state == "in progress", out[0].state


def test_releasing_a_batch_reaps_its_park_markers(tmp_path):
    """**Round finding (execute lens), MEDIUM — a regression this phase's own
    change made live.**

    `close_batch.sh`'s `remove_claim_artifacts()` reaps a batch's park markers,
    but only when a close LANDS ON `main`. `batch_work.sh --release` — the
    batch's own un-claim — had no reference to `parked/` at all, so a released
    batch kept its marker forever.

    That was inert while `/sitrep` could not see batch parks. Now it is a false
    report in both directions: after release-and-reclaim a fresh claim with zero
    commits reads `parked` and points at an abandoned run; between the two it
    reads `pending (not claimed)` with the marker still on disk.

    Asserted against the real script, not by reading it.
    """
    repo = _repo(tmp_path / "repo", _TASKS)
    script = REPO_ROOT / "core/companion/scripts/batch_work.sh"
    dest = repo / "sysop/scripts"
    dest.mkdir(parents=True)
    for name in ("batch_work.sh", "review_index.py", "_git_lib.sh"):
        src = REPO_ROOT / "core/companion/scripts" / name
        if src.is_file():
            shutil.copy(src, dest / name)

    marker_dir = repo / "sysop/runtime/parked"
    marker_dir.mkdir(parents=True)
    marker = marker_dir / "BATCH-1__20260801T090000Z-11111111.md"
    marker.write_text("reason: abandoned\n")
    locks = repo / "sysop/runtime/locks"
    locks.mkdir(parents=True)
    (locks / "BATCH-1.lock").write_text(
        "task_id: BATCH-1\nbranch: review/batch-1\nstarted: 2026-08-01T09:00:00Z\n"
    )

    r = subprocess.run(["bash", str(script), "--release", "--force", "1"],
                       cwd=str(repo), capture_output=True, text=True)

    assert not marker.exists(), (
        "batch_work.sh --release left a park marker on disk; the next claim of "
        f"this batch will report `parked` against an abandoned run.\n"
        f"stdout={r.stdout}\nstderr={r.stderr}"
    )
    assert "Removed park marker" in r.stdout, r.stdout


def test_the_in_progress_release_path_reaps_markers_too(tmp_path):
    """**Battery survivor `RND-5`, closed — a guard covering 1 of 2 sites.**

    `--release` has TWO exits that drop the lock: a short one for a batch already
    `Pending` (clear the lock only) and the full reversal for `In Progress` /
    `Review Ready`. The first test above uses a `Pending` fixture and reaches only
    the short path, so a mutation removing the call from the *other* one survived
    with the guards green. That is this phase's own named class — a fix, or a
    guard, landing at N-1 of N sites — reproduced inside the round's fix.
    """
    repo = _repo(tmp_path / "repo", _TASKS.replace("`Pending`", "`In Progress`"))
    dest = repo / "sysop/scripts"
    dest.mkdir(parents=True)
    for name in ("batch_work.sh", "review_index.py", "_git_lib.sh"):
        src = REPO_ROOT / "core/companion/scripts" / name
        if src.is_file():
            shutil.copy(src, dest / name)

    marker_dir = repo / "sysop/runtime/parked"
    marker_dir.mkdir(parents=True)
    marker = marker_dir / "BATCH-1__20260801T090000Z-11111111.md"
    marker.write_text("reason: abandoned\n")
    locks = repo / "sysop/runtime/locks"
    locks.mkdir(parents=True)
    (locks / "BATCH-1.lock").write_text(
        "task_id: BATCH-1\nbranch: review/batch-1\nstarted: 2026-08-01T09:00:00Z\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "in progress")

    r = subprocess.run(["bash", str(dest / "batch_work.sh"), "--release", "--force", "1"],
                       cwd=str(repo), capture_output=True, text=True)

    assert not marker.exists(), (
        "the In Progress release path left a park marker on disk\n"
        f"stdout={r.stdout}\nstderr={r.stderr}"
    )


def test_releasing_a_batch_with_no_marker_says_so(tmp_path):
    """The removal path reports either way — a path that is silent when the file
    is absent cannot be told from one that never ran. Same rule its
    `remove_batch_lock` neighbour states in its own header."""
    repo = _repo(tmp_path / "repo", _TASKS)
    dest = repo / "sysop/scripts"
    dest.mkdir(parents=True)
    for name in ("batch_work.sh", "review_index.py", "_git_lib.sh"):
        src = REPO_ROOT / "core/companion/scripts" / name
        if src.is_file():
            shutil.copy(src, dest / name)
    locks = repo / "sysop/runtime/locks"
    locks.mkdir(parents=True)
    (locks / "BATCH-1.lock").write_text("task_id: BATCH-1\nbranch: review/batch-1\n")

    r = subprocess.run(["bash", str(dest / "batch_work.sh"), "--release", "--force", "1"],
                       cwd=str(repo), capture_output=True, text=True)
    assert "No park markers for Batch 1" in r.stdout, r.stdout


def test_the_park_evidence_reaches_the_human_readable_report(tmp_path):
    """**Round finding (guards lens), MEDIUM — the fifth surface.**

    The task block in `render_text` prints its notes; the review-batch block did
    not. So a parked batch's evidence reached `--json`, `_recommended_next` and
    `_suggested_order` and never the report a human actually reads — and it was
    dropped entirely whenever any higher-priority item won the cascade.

    The lost line is the whole message in the marker-less arm, and
    `_recommended_next`'s own reason string points at it: *"see the detail line
    for what the evidence is."* There was no detail line. Four surfaces were
    counted; this is the one that was missed — the same counting error
    `_suggested_order`'s comment records for the first cut of `Q-019`.
    """
    _run_dir(tmp_path, verdict="BLOCKED")
    out = _classify(tmp_path, [_batch()], [_lock()])
    assert out[0].state == ss._PARKED_STATE

    # A HIGHER-PRIORITY item must be present, and this is the whole test. Without
    # it the note reaches the output through `_recommended_next`'s `detail_lines`
    # — the batch wins the cascade — so the assertion passes against a
    # `render_text` that prints no batch notes at all. Measured: the first cut of
    # this test survived `for note in []` in the batch loop.
    #
    # That is the wrong-occurrence class this phase has now hit three times: in
    # `/roadmap`'s enum line, in `Q-308`'s alias spellings, and here in the guard
    # written to close a round finding about it.
    busy = ss.TaskState(
        task_id="TECH-0009", state="in progress", state_marker="",
        branch="task/nine", worktree="", commits_ahead=3, unpushed=0,
        has_lock=True, has_index_entry=True, index_status="in_progress",
        dirty=False, doc_work_ids=[], pending_doc=False,
        next_action="continue work", notes=[],
    )
    survey = ss.Survey(
        timestamp=datetime(2026, 8, 31, tzinfo=timezone.utc),
        main_root=Path("/tmp/x"), head_short="abc1234", stale_days=7,
        tasks=[busy], review_batches=out, discrepancies=[], open_roadmap_ids=[],
    )
    rec = ss._recommended_next(survey)
    assert rec is None or "Batch 7" not in rec.reason, (
        "fixture is wrong: the batch still wins the cascade, so its note reaches "
        "the report through `detail_lines` and this test proves nothing about "
        f"the REVIEW BATCHES block. reason={rec.reason if rec else None!r}"
    )

    text = ss.render_text(survey)
    assert "no park marker is on disk" in text, (
        "the batch's park evidence never reaches the human-readable report\n" + text
    )


def test_two_parked_batches_do_not_share_one_notes_list(tmp_path):
    """**Round finding (guards lens), MEDIUM — a real aliasing bug shape, and the
    reason it was invisible.**

    Every test in this module classified exactly ONE batch, so hoisting
    `notes = []` out of the per-batch loop — which aliases every batch's evidence
    onto one list — survived the whole suite. With two batches, batch 8 reported
    batch 7's park marker as its own.
    """
    _park(tmp_path, claim_id="BATCH-7")
    out = _classify(
        tmp_path,
        [_batch(number=7, branch="review/batch-7"),
         _batch(number=8, branch="review/batch-8")],
        [_lock(branch="review/batch-7", task_id="BATCH-7"),
         _lock(branch="review/batch-8", task_id="BATCH-8")],
    )
    by_num = {rb.batch_number: rb for rb in out}
    assert by_num[7].state == ss._PARKED_STATE, by_num[7].state
    assert by_num[8].state != ss._PARKED_STATE, by_num[8].state
    assert by_num[8].notes == [], (
        f"batch 8 inherited batch 7's evidence: {by_num[8].notes}"
    )


def test_the_batch_stall_states_rank_below_their_task_twins(tmp_path):
    """**Round findings (guards lens) B24/B25, closed.** The cascade's ORDER was
    unguarded for the new states: ranking them above their task twins, or above
    priority 4 (`/triage` on an untriaged queue), both survived. Either makes the
    shipped `6c`/`6d` ordinals false, and the routing-table guard checks
    membership, never position.
    """
    _park(tmp_path)
    batches = _classify(tmp_path, [_batch()], [_lock()])
    assert batches[0].state == ss._PARKED_STATE

    parked_task = ss.TaskState(
        task_id="TECH-0001", state=ss._PARKED_STATE, state_marker="",
        branch="task/one", worktree="", commits_ahead=0, unpushed=0,
        has_lock=True, has_index_entry=True, index_status="in_progress",
        dirty=False, doc_work_ids=[], pending_doc=False,
        next_action="read the task's park marker", notes=[],
    )
    survey = ss.Survey(
        timestamp=datetime(2026, 8, 31, tzinfo=timezone.utc),
        main_root=Path("/tmp/x"), head_short="abc1234", stale_days=7,
        tasks=[parked_task], review_batches=batches,
        discrepancies=[], open_roadmap_ids=[],
    )
    rec = ss._recommended_next(survey)
    assert rec is not None
    assert "TECH-0001" in rec.reason, (
        "a parked BATCH outranked a parked TASK; the shipped routing table puts "
        f"the task rows at 6a/6b and the batch rows at 6c/6d.\nreason={rec.reason}"
    )
