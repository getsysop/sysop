"""A park with work is its own state, and every state has an arm (Phase 252).

`Q-362`: `/sitrep`'s park probe was gated on a 0-commit claim, on the premise
that a park is "by construction the state where nothing has been produced".
Two shipped park sites refute it — `planner-integrity.md` = `VIOLATED` is
DEFINED as the planner having committed, and an executor `STATUS: BLOCKED`
parks after the executor ran — and Phase 248's round reproduced the result: a
marker beside one commit reported `in progress — continue work`. The rule now
has three arms, identical on both classifier paths:

* 0 commits + park evidence → `parked` / `awaiting approval` (unchanged);
* commits, and the park is the LATEST event → `parked, work in progress`;
* commits NEWER than the park → the claim resumed; its ordinary state, with
  the marker named in `notes`.

The third arm exists because a `--resume` never removes a marker (the close
does, and `batch_work.sh --release` does for a batch — `claim-task/SKILL.md`
§ *What cleans it up*), so between a `--resume` and the close a live claim
carries a marker beside its new commits.

`Q-363`: a parked batch whose branch was deleted classified `claimed, no
branch` (that arm precedes the park arm on purpose), its park notes were
dropped, and the state had NO arm in `_recommended_next` or `_suggested_order`
— it vanished from both routing surfaces. Three more states were orphaned the
same way (`stale`, `empty batch`, batch `in progress`), so the guard here
covers the CLASS: every state either classifier can emit is driven through
both tables, with the state set derived from the source and no allowlist.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
SURVEY = SCRIPTS / "sitrep_survey.py"
SITREP_SKILL = REPO_ROOT / "core/skills/sitrep/SKILL.md"
ROADMAP_SKILL = REPO_ROOT / "core/skills/roadmap/SKILL.md"

sys.path.insert(0, str(SCRIPTS))
import sitrep_survey as ss  # noqa: E402

T0 = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
CUTOFF = datetime(2020, 1, 1, tzinfo=timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _commit(when=T0, doc_work_ids=(), subject="work"):
    return ss.Commit(sha="a" * 7, subject=subject, author_date=when,
                     doc_work_ids=list(doc_work_ids), subject_task_id=None)


def _touch(path, when):
    os.utime(path, (when.timestamp(), when.timestamp()))


def _park(root, claim_id, when, run_id="20260830T110000Z-abcd1234"):
    """A park marker written at `when`. The RUN_ID in the name is the run's
    START (deliberately earlier than any commit here): it is NOT the park time,
    which is why the discriminator reads mtime."""
    d = root / "sysop/runtime/parked"
    d.mkdir(parents=True, exist_ok=True)
    m = d / f"{claim_id}__{run_id}.md"
    m.write_text("reason: waiting on a decision\n")
    _touch(m, when)
    return m


def _blocked_run(root, claim_id, when, run_id="20260830T110000Z-abcd1234"):
    """The marker-less arm: a run whose classification.md reads BLOCKED."""
    d = root / "sysop/runtime/claim" / claim_id / run_id
    d.mkdir(parents=True, exist_ok=True)
    f = d / "classification.md"
    f.write_text('```yaml\n{"verdict": "BLOCKED"}\n```\n')
    _touch(f, when)
    return f


def _proceed_run(root, claim_id, run_id="20260830T110000Z-abcd1234"):
    d = root / "sysop/runtime/claim" / claim_id / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "classification.md").write_text('```yaml\n{"verdict": "PROCEED"}\n```\n')
    return d


def _lock(task_id="FEAT-1", branch="task/feat-1"):
    return ss.Lock(task_id=task_id, path=Path(f"/tmp/locks/{task_id}.lock"),
                   branch=branch, started="")


def _task(root, commits, *, lock=None, branch="task/feat-1", task_id="FEAT-1",
          unpushed=0, pending_doc=None):
    return ss._classify_task(
        task_id=task_id, lock=lock or _lock(task_id, branch), worktree=None,
        branch=branch, index_entry=None, commits=list(commits), unpushed=unpushed,
        dirty=False, stale_days=7, phase40_cutoff=CUTOFF, pending_doc=pending_doc,
        main_root=root,
    )


def _batch_dict(number=7, status="In Progress", branch="review/batch-7", tasks=None):
    return {
        "number": number, "title": f"Batch {number}", "status": status,
        "branch": branch, "flag_reason": "", "triaged_date": "2026-08-30",
        "triaged_verdict": "auto", "triaged_tasks": [],
        "tasks": tasks if tasks is not None else [
            {"id": "TASK-601", "checkbox": " "}, {"id": "TASK-602", "checkbox": " "},
        ],
    }


def _batch(root, commits, *, has_branch=True, locked=True, number=7, tasks=None):
    locks = [ss.Lock(task_id=f"BATCH-{number}", path=Path("/tmp/l"),
                     branch=f"review/batch-{number}", started="")] if locked else []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "_git", lambda *a, **k: "abc123" if has_branch else "")
        mp.setattr(ss, "_commits_ahead_of_main", lambda *a, **k: list(commits))
        return ss._classify_review_batches(
            [_batch_dict(number=number, tasks=tasks)], locks, [], root
        )[0]


def _survey(tasks=(), batches=()):
    return ss.Survey(
        timestamp=T0, main_root=Path("/tmp/x"), head_short="abc1234", stale_days=7,
        tasks=list(tasks), review_batches=list(batches), discrepancies=[],
        open_roadmap_ids=[],
    )


# ─────────────────────────────────────────────────────────────────────────────
# `Q-362` — the three-way rule, both paths
# ─────────────────────────────────────────────────────────────────────────────

class TestParkWithWorkOnTheTaskPath:
    def test_a_park_newer_than_the_commits_is_parked_with_work(self, tmp_path):
        _park(tmp_path, "FEAT-1", T0 + timedelta(hours=1))
        ts = _task(tmp_path, [_commit(T0)])
        assert ts.state == ss._PARKED_WIP_STATE, ts.state
        assert ts.commits_ahead == 1
        assert any("park marker on disk" in n for n in ts.notes), ts.notes
        assert any("1 commit(s) ahead" in n for n in ts.notes), ts.notes
        # No run directory in this fixture, so the action names the marker.
        assert "FEAT-1__" in ts.next_action, ts.next_action

    def test_a_park_older_than_the_newest_commit_is_resumed(self, tmp_path):
        _park(tmp_path, "FEAT-1", T0 - timedelta(hours=1))
        ts = _task(tmp_path, [_commit(T0)])
        assert ts.state == "in progress", ts.state
        assert any("predates the newest commit" in n for n in ts.notes), ts.notes

    def test_the_newest_commit_decides_not_the_oldest(self, tmp_path):
        """Two commits straddling the park: the newer one is after it, so the
        claim resumed. A discriminator reading `commits[0]` (oldest first in
        git-log order is not guaranteed) would get this wrong."""
        _park(tmp_path, "FEAT-1", T0)
        ts = _task(tmp_path, [_commit(T0 - timedelta(hours=2)), _commit(T0 + timedelta(hours=2))])
        assert ts.state == "in progress", ts.state
        ts = _task(tmp_path, [_commit(T0 + timedelta(hours=2)), _commit(T0 - timedelta(hours=2))])
        assert ts.state == "in progress", ts.state

    def test_an_equal_timestamp_keeps_the_park(self, tmp_path):
        """`newest > parked_at`, strictly: same second → the park stands."""
        _park(tmp_path, "FEAT-1", T0)
        ts = _task(tmp_path, [_commit(T0)])
        assert ts.state == ss._PARKED_WIP_STATE, ts.state

    def test_a_run_that_started_after_the_commit_keeps_the_park_whatever_the_mtime(self, tmp_path):
        """Round finding (execute lens): a restored `sysop/runtime/` (cp -p,
        rsync -a) can put a marker's mtime BEFORE the commit it parked on; the
        stamp in its name is the run's start, and a run that started after
        the newest commit cannot have parked before it. The later of the two
        dates the park."""
        _park(tmp_path, "FEAT-1", T0 - timedelta(hours=2),
              run_id=(T0 + timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ") + "-abcd1234")
        ts = _task(tmp_path, [_commit(T0)])
        assert ts.state == ss._PARKED_WIP_STATE, ts.state
        # …and the name stamp alone (an /auto-build marker, no hex suffix).
        for m in (tmp_path / "sysop/runtime/parked").iterdir():
            m.unlink()
        _park(tmp_path, "FEAT-1", T0 - timedelta(hours=2),
              run_id=(T0 + timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ"))
        ts = _task(tmp_path, [_commit(T0)])
        assert ts.state == ss._PARKED_WIP_STATE, ts.state

    def test_every_marker_is_dated_not_just_the_newest_named(self, tmp_path):
        """Names sort by run start; a re-park of an OLDER run is a newer event
        with an older name. The newest-named marker written before the commit
        and an older-named one written after it: the park is the latest event."""
        old_run = (T0 - timedelta(days=1)).strftime("%Y%m%dT%H%M%SZ") + "-aaaa0000"
        new_run = (T0 - timedelta(hours=3)).strftime("%Y%m%dT%H%M%SZ") + "-bbbb0000"
        _park(tmp_path, "FEAT-1", T0 - timedelta(hours=2), run_id=new_run)
        _park(tmp_path, "FEAT-1", T0 + timedelta(hours=1), run_id=old_run)
        ts = _task(tmp_path, [_commit(T0)])
        assert ts.state == ss._PARKED_WIP_STATE, ts.state

    def test_an_unreadable_park_time_keeps_the_park(self, tmp_path, monkeypatch):
        """Cannot tell → the conservative reading, never `in progress`."""
        _park(tmp_path, "FEAT-1", T0 - timedelta(days=1))
        monkeypatch.setattr(ss, "_park_evidence_time", lambda *a, **k: None)
        ts = _task(tmp_path, [_commit(T0)])
        assert ts.state == ss._PARKED_WIP_STATE, ts.state

    def test_the_marker_less_blocked_verdict_is_ordered_by_classification_md(self, tmp_path):
        _blocked_run(tmp_path, "FEAT-1", T0 + timedelta(hours=1))
        ts = _task(tmp_path, [_commit(T0)])
        assert ts.state == ss._PARKED_WIP_STATE, ts.state
        assert any("no park marker is on disk" in n for n in ts.notes), ts.notes
        _blocked_run(tmp_path, "FEAT-1", T0 - timedelta(hours=1))
        ts = _task(tmp_path, [_commit(T0)])
        assert ts.state == "in progress", ts.state

    def test_a_park_with_work_outranks_every_commit_shape_state(self, tmp_path):
        """Doc-Work trailer, pushed, pending-doc present: `ready for
        /review-close` on every other reading — and parked after all of it."""
        _park(tmp_path, "FEAT-1", T0 + timedelta(hours=1))
        ts = _task(tmp_path, [_commit(T0, doc_work_ids=["FEAT-1"])],
                   pending_doc=tmp_path / "pending.md")
        assert ts.state == ss._PARKED_WIP_STATE, ts.state
        # …and with NO pending-doc, which is the `code committed, docs pending`
        # shape: the arm precedes THAT arm too (round finding, guards lens: the
        # parked-wip arm moved below it stayed green because the one test
        # above passes `pending_doc`).
        ts = _task(tmp_path, [_commit(T0, doc_work_ids=["FEAT-1"])])
        assert ts.state == ss._PARKED_WIP_STATE, ts.state
        # …and the unpushed shape.
        ts = _task(tmp_path, [_commit(T0, doc_work_ids=["FEAT-1"])], unpushed=1,
                   pending_doc=tmp_path / "pending.md")
        assert ts.state == ss._PARKED_WIP_STATE, ts.state

    def test_a_resumed_claim_reaches_its_ordinary_commit_shape_state(self, tmp_path):
        _park(tmp_path, "FEAT-1", T0 - timedelta(hours=1))
        ts = _task(tmp_path, [_commit(T0, doc_work_ids=["FEAT-1"])],
                   pending_doc=tmp_path / "pending.md")
        assert ts.state == "ready for /review-close", ts.state
        assert any("predates the newest commit" in n for n in ts.notes), ts.notes

    def test_zero_commits_with_a_park_is_still_plain_parked(self, tmp_path):
        _park(tmp_path, "FEAT-1", T0)
        ts = _task(tmp_path, [])
        assert ts.state == ss._PARKED_STATE, ts.state

    def test_awaiting_approval_beside_commits_is_in_progress_with_the_gate_noted(self, tmp_path):
        """PROCEED, no outcome.md, and commits: the executor has run, so the
        gate was answered — the state says so rather than reporting a gate
        nobody is standing at."""
        _proceed_run(tmp_path, "FEAT-1")
        ts = _task(tmp_path, [_commit(T0)])
        assert ts.state == "in progress", ts.state
        assert any("Step 7d's gate was answered" in n for n in ts.notes), ts.notes
        ts = _task(tmp_path, [])
        assert ts.state == ss._AWAITING_STATE
        # With a trailer the commit shape wins, and the note must not contradict
        # the state printed beside it (round finding, claims lens: it used to
        # say "treated as in progress" next to `code committed, docs pending`).
        ts = _task(tmp_path, [_commit(T0, doc_work_ids=["FEAT-1"])])
        assert ts.state == "code committed, docs pending", ts.state
        note = next(n for n in ts.notes if "Step 7d's gate was answered" in n)
        assert "in progress" not in note, note

    def test_a_park_with_work_is_not_stale_however_old_the_lock(self, tmp_path):
        old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat().replace("+00:00", "Z")
        _park(tmp_path, "FEAT-1", T0 + timedelta(hours=1))
        lock = ss.Lock(task_id="FEAT-1", path=tmp_path / "l.lock", branch="task/feat-1", started=old)
        ts = _task(tmp_path, [_commit(T0)], lock=lock)
        assert ts.state == ss._PARKED_WIP_STATE, ts.state
        assert "rm " not in ts.next_action


class TestParkWithWorkOnTheBatchPath:
    def test_a_park_newer_than_the_commits_is_parked_with_work(self, tmp_path):
        _park(tmp_path, "BATCH-7", T0 + timedelta(hours=1))
        rb = _batch(tmp_path, [_commit(T0)])
        assert rb.state == ss._PARKED_WIP_STATE, rb.state
        assert any("park marker on disk" in n for n in rb.notes), rb.notes
        assert any("park is the latest event" in n for n in rb.notes), rb.notes

    def test_a_park_older_than_the_newest_commit_is_resumed(self, tmp_path):
        _park(tmp_path, "BATCH-7", T0 - timedelta(hours=1))
        rb = _batch(tmp_path, [_commit(T0)])
        assert rb.state == "in progress", rb.state
        assert any("predates the newest commit" in n for n in rb.notes), rb.notes

    def test_a_park_with_work_outranks_ready_for_review_close(self, tmp_path):
        _park(tmp_path, "BATCH-7", T0 + timedelta(hours=1))
        rb = _batch(tmp_path, [_commit(T0, doc_work_ids=["TASK-601", "TASK-602"])])
        assert rb.state == ss._PARKED_WIP_STATE, rb.state
        assert rb.doc_worked_tasks == 2

    def test_a_resumed_batch_with_every_trailer_is_ready(self, tmp_path):
        _park(tmp_path, "BATCH-7", T0 - timedelta(hours=1))
        rb = _batch(tmp_path, [_commit(T0, doc_work_ids=["TASK-601", "TASK-602"])])
        assert rb.state == "ready for /review-close", rb.state
        assert any("predates the newest commit" in n for n in rb.notes), rb.notes

    def test_an_unlocked_batch_is_never_probed(self, tmp_path):
        _park(tmp_path, "BATCH-7", T0 + timedelta(hours=1))
        rb = _batch(tmp_path, [_commit(T0)], locked=False)
        assert rb.state == "in progress", rb.state
        assert not rb.notes

    def test_empty_batch_still_precedes_the_park_with_work_arm(self, tmp_path):
        _park(tmp_path, "BATCH-7", T0 + timedelta(hours=1))
        rb = _batch(tmp_path, [_commit(T0)], tasks=[])
        assert rb.state == "empty batch", rb.state

    def test_awaiting_approval_beside_commits_is_in_progress(self, tmp_path):
        _proceed_run(tmp_path, "BATCH-7")
        rb = _batch(tmp_path, [_commit(T0)])
        assert rb.state == "in progress", rb.state
        assert any("Step 7d's gate was answered" in n for n in rb.notes), rb.notes


def test_both_paths_agree_on_every_arm_of_the_rule(tmp_path):
    """The invariant `Q-362` was held back for: a one-sided widening makes
    the two classifiers disagree. Same evidence, same commit shape, same
    answer — driven, not asserted from the code's comments."""
    cases = []
    for label, park_at, commits in (
        ("park after work", T0 + timedelta(hours=1), [_commit(T0)]),
        ("park before work", T0 - timedelta(hours=1), [_commit(T0)]),
        ("park, no work", T0, []),
        ("no park, work", None, [_commit(T0)]),
    ):
        root = tmp_path / label.replace(" ", "_").replace(",", "")
        root.mkdir()
        if park_at is not None:
            _park(root, "FEAT-1", park_at)
            _park(root, "BATCH-7", park_at)
        t = _task(root, commits).state
        b = _batch(root, commits).state
        cases.append((label, t, b))
    disagreements = [(l, t, b) for l, t, b in cases if t != b and not (t, b) == ("planning", "in progress")]
    # `planning` (task, 0 commits, no park) has no batch twin: an unparked
    # locked batch with 0 commits reads `in progress` (0 of N trailers). That
    # is a pre-existing vocabulary difference, not a park-rule disagreement.
    assert not disagreements, disagreements
    assert [c[1] for c in cases][:2] == [ss._PARKED_WIP_STATE, "in progress"]


# ─────────────────────────────────────────────────────────────────────────────
# `Q-363` — the branchless arm keeps its evidence and has an arm
# ─────────────────────────────────────────────────────────────────────────────

class TestClaimedNoBranch:
    def test_a_parked_batch_with_a_deleted_branch_is_routed_with_its_evidence(self, tmp_path):
        """The filed reproduction, end to end: park marker + lock + no branch
        → `claimed, no branch`, notes carry the marker, and BOTH surfaces name
        the batch."""
        _park(tmp_path, "BATCH-7", T0)
        rb = _batch(tmp_path, [], has_branch=False)
        assert rb.state == "claimed, no branch", rb.state
        assert any("park marker on disk" in n for n in rb.notes), rb.notes
        assert "batch_work.sh --release 7" in rb.next_action, rb.next_action
        # `--release` reaps the batch's markers, so the prescribed order is
        # read first, then release (round finding, execute lens).
        assert rb.next_action.index("read the park marker") < rb.next_action.index("--release 7")
        assert "--release removes it" in rb.next_action

        rec = ss._recommended_next(_survey(batches=[rb]))
        assert rec is not None, "the batch dropped off RECOMMENDED NEXT"
        assert "Batch 7" in rec.reason and "does not exist" in rec.reason, rec.reason
        assert rec.command == rb.next_action
        assert rec.detail_lines == rb.notes, "the park evidence did not reach the detail lines"

        order = ss._suggested_order(_survey(batches=[rb]))
        assert any(line.startswith("Batch 7 holds a lock but no branch") for line in order), order

    def test_a_branchless_task_is_routed_with_its_evidence(self, tmp_path):
        _park(tmp_path, "FEAT-1", T0)
        ts = _task(tmp_path, [], branch="")
        assert ts.state == "claimed, no branch"
        assert any("park marker on disk" in n for n in ts.notes), ts.notes
        assert "claim_task.sh --release FEAT-1" in ts.next_action
        rec = ss._recommended_next(_survey(tasks=[ts]))
        assert rec is not None and "FEAT-1" in rec.reason and rec.detail_lines == ts.notes
        order = ss._suggested_order(_survey(tasks=[ts]))
        assert any(line.startswith("FEAT-1 holds a lock but no branch") for line in order), order

    def test_the_branchless_arm_still_precedes_the_park_arms(self, tmp_path):
        """The ordering `Q-363` says is deliberate: the branchless diagnosis
        wins, and the fix was an arm, not a re-order."""
        _park(tmp_path, "BATCH-7", T0 + timedelta(hours=1))
        rb = _batch(tmp_path, [_commit(T0)], has_branch=False)
        assert rb.state == "claimed, no branch", rb.state


# ─────────────────────────────────────────────────────────────────────────────
# The class: every state either classifier emits has an arm in BOTH tables
# ─────────────────────────────────────────────────────────────────────────────

import ast


def _module_tree():
    return ast.parse(SURVEY.read_text(encoding="utf-8"))


def _module_str_consts(tree):
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            out[node.targets[0].id] = node.value.value
    return out


def _fn(tree, name):
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name), None)
    assert fn is not None, name
    return fn


def _resolve_state_expr(expr, consts, where):
    """Every string a `state` expression can evaluate to. Constants, module
    string constants, and both branches of a ternary resolve; anything else —
    a call, an attribute, a local, arithmetic — fails LOUDLY, because a value
    this guard cannot see is a state that ships unrouted."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return {expr.value}
    if isinstance(expr, ast.Name) and expr.id in consts:
        return {consts[expr.id]}
    if isinstance(expr, ast.IfExp):
        return _resolve_state_expr(expr.body, consts, where) | _resolve_state_expr(expr.orelse, consts, where)
    raise AssertionError(
        f"{where}: `state` is assigned from {ast.dump(expr)[:80]}, which this guard "
        f"cannot resolve to a string — route the state through a literal or a "
        f"module constant so it cannot ship unrouted"
    )


def _stall_states(tree):
    """`_claim_stall`'s returns, first tuple element, resolved the same way."""
    consts = _module_str_consts(tree)
    out = set()
    for node in ast.walk(_fn(tree, "_claim_stall")):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple) and node.value.elts:
            out |= _resolve_state_expr(node.value.elts[0], consts, "_claim_stall return")
    out.discard("")
    assert out, "_claim_stall returns no state — the extraction moved"
    return out


def _emitted_states(fn_name):
    """Every value `state` can hold at the end of `fn_name`, by walking the
    function's AST: every `Assign`/`AnnAssign`/`AugAssign` whose target is the
    name `state` — including a `state` element of a tuple target — resolved
    through `_resolve_state_expr`, with `stall_state` resolved through
    `_claim_stall`'s own returns.

    An AST walk, not a regex (round finding, guards lens): `state="phantom"`,
    `state, next_action = "phantom", "x"`, `state = _phantom()` and a ternary
    all walked through the regex form of this derivation with the suite green.
    """
    tree = _module_tree()
    consts = _module_str_consts(tree)
    stall = None
    states = set()
    for node in ast.walk(_fn(tree, fn_name)):
        if isinstance(node, ast.Assign):
            pairs = []
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "state":
                    pairs.append(node.value)
                elif isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple) \
                        and len(target.elts) == len(node.value.elts):
                    for t, v in zip(target.elts, node.value.elts):
                        if isinstance(t, ast.Name) and t.id == "state":
                            pairs.append(v)
                elif isinstance(target, ast.Tuple) and any(
                        isinstance(t, ast.Name) and t.id == "state" for t in target.elts):
                    raise AssertionError(f"{fn_name}: `state` unpacked from a non-tuple value")
            for value in pairs:
                if isinstance(value, ast.Name) and value.id == "stall_state":
                    stall = stall or _stall_states(tree)
                    states |= stall
                else:
                    states |= _resolve_state_expr(value, consts, fn_name)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and \
                isinstance(node.target, ast.Name) and node.target.id == "state":
            raise AssertionError(f"{fn_name}: `state` assigned by {type(node).__name__}")
    states.discard("unknown")
    assert states, f"{fn_name} assigns no state — the extraction moved"
    return states


def _task_states():
    return _emitted_states("_classify_task")


def _batch_states():
    return _emitted_states("_classify_review_batches")


def _module_consts(src):
    return _module_str_consts(ast.parse(src))


def test_the_state_derivations_are_not_vacuous():
    t, b = _task_states(), _batch_states()
    assert len(t) >= 9, sorted(t)
    assert len(b) >= 8, sorted(b)
    assert ss._PARKED_WIP_STATE in t and ss._PARKED_WIP_STATE in b
    assert "claimed, no branch" in t and "claimed, no branch" in b
    assert "stale" in t and "empty batch" in b


@pytest.mark.parametrize("state", sorted(_task_states()))
def test_every_task_state_is_routed_by_both_tables(state):
    t = ss.TaskState(task_id="T-1", state=state, next_action="do the thing",
                     notes=["evidence"], commits_ahead=1)
    rec = ss._recommended_next(_survey(tasks=[t]))
    assert rec is not None, f"task state {state!r} has no arm in _recommended_next"
    assert "T-1" in rec.reason or "T-1" in rec.command, (state, rec)
    order = ss._suggested_order(_survey(tasks=[t]))
    assert any("T-1" in line for line in order), (
        f"task state {state!r} has no arm in _suggested_order: {order}"
    )


@pytest.mark.parametrize("state", sorted(_batch_states()))
def test_every_batch_state_is_routed_by_both_tables(state):
    rb = ss.ReviewBatchState(
        batch_number=7, title="Batch 7", md_status="In Progress", branch="review/batch-7",
        has_lock=True, has_branch=True, has_flag=False, flag_reason="", total_tasks=2,
        doc_worked_tasks=1, state=state, next_action="do the thing", notes=["evidence"],
        has_triage_record=True, triaged_verdict="auto",
    )
    rec = ss._recommended_next(_survey(batches=[rb]))
    assert rec is not None, f"batch state {state!r} has no arm in _recommended_next"
    # P4's arms aggregate ("1 auto batch(es) ready") and name no number; every
    # other batch arm names the batch. The ordered list always does.
    if state != "pending (not claimed)":
        assert "7" in rec.reason or "7" in rec.command, (state, rec)
    order = ss._suggested_order(_survey(batches=[rb]))
    assert any("batch 7" in line.lower() for line in order), (
        f"batch state {state!r} has no arm in _suggested_order: {order}"
    )


def test_the_structural_wiring_matches_the_behavioural_guard():
    """The second, independent extraction: each state's literal (or constant)
    appears as a `.state ==` predicate in BOTH function bodies, keyed to the
    right collection. Wiring is not content — the behavioural tests above are
    the guard; this catches an arm that fires on the wrong list."""
    src = SURVEY.read_text(encoding="utf-8")
    consts = _module_consts(src)
    by_value = {v: k for k, v in consts.items()}

    def body(name, nxt):
        a = src.index(f"def {name}(")
        return src[a:src.index(f"\ndef {nxt}(", a)]

    rec_body = body("_recommended_next", "_suggested_order")
    ord_body = body("_suggested_order", "render_json")
    problems = []
    for state in _task_states():
        preds = {f't.state == "{state}"', f'ts.state == "{state}"'}
        if state in by_value:
            preds |= {f"t.state == {by_value[state]}", f"ts.state == {by_value[state]}"}
        if not any(p in rec_body for p in preds):
            problems.append(f"task {state!r} not keyed to s.tasks in _recommended_next")
        if not any(p in ord_body for p in preds):
            problems.append(f"task {state!r} not keyed to s.tasks in _suggested_order")
    for state in _batch_states():
        preds = {f'rb.state == "{state}"'}
        if state in by_value:
            preds.add(f"rb.state == {by_value[state]}")
        if not any(p in rec_body for p in preds):
            problems.append(f"batch {state!r} not keyed to s.review_batches in _recommended_next")
        if not any(p in ord_body for p in preds):
            problems.append(f"batch {state!r} not keyed to s.review_batches in _suggested_order")
    assert not problems, "\n".join(problems)


# ─────────────────────────────────────────────────────────────────────────────
# Rank, rendering, and the consumer-facing surfaces
# ─────────────────────────────────────────────────────────────────────────────

def test_a_park_with_work_outranks_a_plain_park_and_sits_below_in_progress():
    wip = ss.TaskState(task_id="W-1", state=ss._PARKED_WIP_STATE, next_action="w", commits_ahead=2)
    parked = ss.TaskState(task_id="P-1", state=ss._PARKED_STATE, next_action="p")
    live = ss.TaskState(task_id="L-1", state="in progress", next_action="l", commits_ahead=1)
    rec = ss._recommended_next(_survey(tasks=[parked, wip]))
    assert rec is not None and "W-1" in rec.reason, rec
    assert "2 commit(s)" in rec.reason, rec.reason
    rec = ss._recommended_next(_survey(tasks=[wip, live]))
    assert rec is not None and "L-1" in rec.reason, rec
    order = ss._suggested_order(_survey(tasks=[parked, wip, live]))
    idx = {tid: next(i for i, line in enumerate(order) if tid in line)
           for tid in ("L-1", "W-1", "P-1")}
    assert idx["L-1"] < idx["W-1"] < idx["P-1"], order
    assert "is parked with work in progress" in order[idx["W-1"]]


def test_the_diagnostics_sit_below_the_stalls_and_stale_below_planning():
    """Round finding (guards lens): the branchless task arm hoisted above the
    stall block, and the stale arm hoisted above planning, both stayed green —
    the docs' row order asserted the cascade and no two-task test did."""
    parked = ss.TaskState(task_id="P-1", state=ss._PARKED_STATE, next_action="p")
    branchless = ss.TaskState(task_id="B-1", state="claimed, no branch", next_action="b")
    planning = ss.TaskState(task_id="N-1", state="planning", next_action="n")
    stale = ss.TaskState(task_id="S-1", state="stale", next_action="s")
    rec = ss._recommended_next(_survey(tasks=[branchless, parked]))
    assert rec is not None and "P-1" in rec.reason, rec
    rec = ss._recommended_next(_survey(tasks=[stale, planning]))
    assert rec is not None and "N-1" in rec.reason, rec
    order = ss._suggested_order(_survey(tasks=[stale, planning, branchless, parked]))
    idx = {tid: next(i for i, line in enumerate(order) if tid in line) for tid in ("P-1", "B-1", "N-1", "S-1")}
    assert idx["P-1"] < idx["B-1"] < idx["N-1"] < idx["S-1"], order


def _cascade_state_sequence():
    """The order in which `_recommended_next` tests task/batch states, from
    its source: the sequence of `.state ==` predicates, resolved."""
    src = SURVEY.read_text(encoding="utf-8")
    a = src.index("def _recommended_next(")
    body = src[a:src.index("\ndef _suggested_order(", a)]
    consts = _module_consts(src)
    out = []
    for kind, tok in re.findall(r'\b(t|rb)\.state == ("[^"]+"|[A-Za-z_][A-Za-z0-9_]*)', body):
        val = tok.strip('"') if tok.startswith('"') else consts[tok]
        out.append(("review batch" if kind == "rb" else "task", val))
    return out


def test_the_routing_table_order_is_the_cascade_order():
    """Rows in the routing table appear in the order the cascade tests them,
    and the priority labels are monotonic — derived from `_recommended_next`,
    so a row moved to the wrong priority, or two labels swapped, reddens
    (round finding, guards lens: label swaps and row swaps survived)."""
    skill = SITREP_SKILL.read_text(encoding="utf-8")
    t0 = skill.index("## Recommendation routing rules")
    rows = [ln for ln in skill[t0:skill.index("## Classification states", t0)].splitlines()
            if ln.startswith("|") and not ln.startswith("| Priority") and not ln.startswith("| ---")]
    labels = [ln.strip().strip("|").split("|")[0].strip() for ln in rows]
    def key(lbl):
        m = re.match(r"(\d+)([a-z]?)", lbl); return (int(m.group(1)), m.group(2))
    assert labels == sorted(labels, key=key), labels
    # STRICTLY increasing: two rows sharing a label passed the sorted() check
    # (reviewer survivor D09a — 6a relabelled 6b beside the real 6b).
    assert len(set(labels)) == len(labels), [l for l in labels if labels.count(l) > 1]
    # every cascade predicate on a classifier state has a row, in cascade order
    seq = [(k, v) for k, v in _cascade_state_sequence() if v]
    # Two batch states the table describes in words rather than by the state
    # string: row 2 ("all tasks Doc-Work'd") and rows 4a–4d ("Pending unclaimed
    # batches"). Every other row names the state in backticks and its kind.
    described = {
        ("review batch", "ready for /review-close"): "Doc-Work'd",
        ("review batch", "pending (not claimed)"): "Pending unclaimed batches",
    }
    positions = []
    for kind, state in seq:
        phrase = described.get((kind, state))
        if phrase:
            hit = next((i for i, ln in enumerate(rows) if phrase in ln), None)
        else:
            hit = next((i for i, ln in enumerate(rows) if f"`{state}`" in ln and
                        (("review batch" in ln.lower()) == (kind == "review batch"))), None)
        assert hit is not None, f"no routing row for {kind} {state!r}"
        positions.append(hit)
    assert positions == sorted(positions), list(zip(seq, positions))


def test_no_claim_state_row_routes_to_a_drainer_and_batch_rows_name_the_batch_tool():
    """Round finding (guards lens): the drainer check covered only the park and
    branchless rows, and the batch branchless row could name `claim_task.sh`."""
    skill = SITREP_SKILL.read_text(encoding="utf-8")
    t0 = skill.index("## Recommendation routing rules")
    rows = [ln for ln in skill[t0:skill.index("## Classification states", t0)].splitlines()
            if ln.startswith("| 5") or ln.startswith("| 6")]
    for ln in rows:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        prio, state, rec, _n = cells
        if prio.startswith("6"):
            assert "/auto-fix" not in rec and "/auto-judge" not in rec and "/auto-build" not in rec, ln
        if "claimed, no branch" in state:
            if "review batch" in state:
                assert "batch_work.sh --release <N>" in rec, ln
            else:
                assert "claim_task.sh --release <ID>" in rec, ln


def test_the_library_has_its_section_8_4_row():
    """`_git_lib.sh` is exempt from the row REQUIREMENT as a private helper, and
    the exemption's own comment says it has a row — so the row is pinned here
    (round finding: the row deleted stayed green)."""
    wf = (REPO_ROOT / "core/companion/docs/WORKFLOW.md").read_text(encoding="utf-8")
    assert re.search(r"^\| `_git_lib\.sh` \|", wf, re.M), "WORKFLOW.md § 8.4 lost the _git_lib.sh row"


def test_a_batch_in_progress_ranks_below_a_task_in_progress_and_above_the_stalls():
    live_task = ss.TaskState(task_id="L-1", state="in progress", next_action="l", commits_ahead=1)
    live_batch = ss.ReviewBatchState(
        batch_number=3, title="B", md_status="In Progress", branch="review/batch-3",
        has_lock=True, has_branch=True, has_flag=False, flag_reason="", total_tasks=4,
        doc_worked_tasks=1, state="in progress", next_action="n",
    )
    parked = ss.TaskState(task_id="P-1", state=ss._PARKED_STATE, next_action="p")
    rec = ss._recommended_next(_survey(tasks=[live_task, parked], batches=[live_batch]))
    assert rec is not None and "L-1" in rec.reason
    rec = ss._recommended_next(_survey(tasks=[parked], batches=[live_batch]))
    assert rec is not None and "Batch 3" in rec.reason and "1 of 4" in rec.reason, rec


def test_the_json_contract_is_additive_for_the_new_state(tmp_path):
    _park(tmp_path, "BATCH-7", T0 + timedelta(hours=1))
    rb = _batch(tmp_path, [_commit(T0)])
    payload = json.loads(ss.render_json(_survey(batches=[rb])))
    row = payload["review_batches"][0]
    assert row["state"] == ss._PARKED_WIP_STATE
    assert any("park marker on disk" in n for n in row["notes"])
    assert set(row) == {
        "batch_number", "title", "md_status", "branch", "has_lock", "has_branch",
        "has_flag", "flag_reason", "has_triage_record", "triaged_verdict",
        "triaged_tasks", "total_tasks", "doc_worked_tasks", "state",
        "next_action", "notes",
    }, sorted(row)


def test_the_human_readable_report_prints_the_evidence(tmp_path):
    _park(tmp_path, "FEAT-1", T0 + timedelta(hours=1))
    ts = _task(tmp_path, [_commit(T0)])
    text = ss.render_text(_survey(tasks=[ts]))
    assert ss._PARKED_WIP_STATE in text
    assert "park marker on disk" in text
    assert "park is the latest event" in text


def test_the_routing_table_has_positional_rows_for_the_new_states():
    """Modelled on `test_every_stall_batch_state_has_a_routing_row`: a row
    whose State cell names the state AND the right claim kind, at priority
    6 for the stalls and diagnostics, 5b for the batch in-progress twin."""
    skill = SITREP_SKILL.read_text(encoding="utf-8")
    t0 = skill.index("## Recommendation routing rules")
    rows = [ln for ln in skill[t0:skill.index("## Classification states", t0)].splitlines()
            if ln.startswith("|")]

    def find(kind, state):
        hits = [ln for ln in rows if kind in ln and f"`{state}`" in ln]
        assert hits, f"no routing row for {kind} {state!r}"
        return [c.strip() for c in hits[0].strip().strip("|").split("|")]

    for kind in ("task", "review batch"):
        for state in (ss._PARKED_WIP_STATE, "claimed, no branch"):
            prio, _st, rec, _n = find(kind, state)
            assert prio.startswith("6"), (kind, state, prio)
            if state == ss._PARKED_WIP_STATE:
                assert "park marker" in rec.lower() and "committed" in rec.lower(), rec
                assert "/auto-fix" not in rec and "/auto-judge" not in rec
            else:
                assert "--release" in rec, rec
    prio, *_ = find("review batch", "empty batch"); assert prio.startswith("6")
    prio, *_ = find("task", "stale"); assert prio.startswith("6")
    prio, _st, rec, _n = find("review batch", "in progress")
    assert prio == "5b" and "/document-work" in rec, (prio, rec)
    # …and the park-with-work rows outrank the plain park rows.
    order = [ln for ln in rows if "`parked" in ln]
    assert f"`{ss._PARKED_WIP_STATE}`" in order[0] and "task" in order[0].lower()


def test_the_roadmap_enum_and_actuators_name_the_new_states():
    text = ROADMAP_SKILL.read_text(encoding="utf-8")
    enum_line = next(ln for ln in text.splitlines() if ln.startswith("- **`state`**"))
    # The ENUM LIST, not the line: the line also carries the prose that
    # explains the new state, so a presence check on the line survived the
    # state being dropped from the list (author-side battery, M48).
    m = re.search(r"one of ((?:`[^`]+`(?:, )?)+)", enum_line)
    assert m, enum_line
    listed = set(re.findall(r"`([^`]+)`", m.group(1)))
    assert ss._PARKED_WIP_STATE in listed, sorted(listed)
    assert "claimed, no branch" in listed
    t0 = text.index("**Batch actuators, and the grammar is load-bearing:**")
    table = text[t0:text.index("\n\n", t0 + 60)]
    for state in (ss._PARKED_WIP_STATE, "claimed, no branch"):
        row = next((ln for ln in table.splitlines() if ln.startswith(f"| `{state}`")), None)
        assert row, f"no actuator row for {state!r}"
        assert "no actuator" in row, row
        assert "/auto-fix" not in row and "/auto-judge" not in row


def test_workflow_md_no_longer_claims_the_park_predicate_is_roadmap_only():
    text = (REPO_ROOT / "core/companion/docs/WORKFLOW.md").read_text(encoding="utf-8")
    assert "a parked *review batch* is still invisible to it" not in text
    assert ss._PARKED_WIP_STATE in text
