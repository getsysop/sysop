"""Guards + behaviour for `/sitrep`'s park and awaiting-approval states.

Phase 237, `Q-030` leg (a) / the orchestrator group's part B leg 2.

Two things live here.

**The routing-rules drift guard.** `core/skills/sitrep/SKILL.md` carries two
reference tables. The § *Classification states* one has been guarded since
Phase 220 (`test_sitrep_survey.py`); the § *Recommendation routing rules* one
was guarded by nothing, so a state could be wired into `_recommended_next`'s
cascade with no routing row and the suite stayed green. It had already happened:
`code committed, docs pending` shipped an arm in Q-019 and never got a row.
This module closes that, and finding that row absent is the first thing it did.

**The predicate's behaviour.** `_claim_stall` is the probe that stops a parked
claim and an unstarted one from producing identical evidence. Its polarity is
the whole design and is tested in both directions: positive evidence upgrades a
classification, and *absence of evidence changes nothing*. `sysop/runtime/` is
gitignored, the `SubagentStop` envelope is Claude-Code-only, and a `--resume`
onto a rebuilt worktree legitimately carries no artifacts — so an empty tree
must keep classifying as `planning`, never as "the pipeline did not run".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import sitrep_survey as ss

REPO_ROOT = Path(__file__).resolve().parents[1]
SURVEY_PY = REPO_ROOT / "core/companion/scripts/sitrep_survey.py"
SKILL_MD = REPO_ROOT / "core/skills/sitrep/SKILL.md"

ROUTING_HEADER = "| Priority | State"
STATES_HEADER = "| State | Deterministic signal |"


def _routing_table() -> str:
    """The § *Recommendation routing rules* table, sliced to itself.

    Sliced at BOTH ends deliberately. A whole-file search would be satisfied by
    the § *Classification states* table 30 lines below — the two tables share a
    vocabulary, so an unsliced guard over either one silently passes on the
    other, which is the "guard with a whole-file fallback is not a guard" shape.
    """
    text = SKILL_MD.read_text(encoding="utf-8")
    start = text.index(ROUTING_HEADER)
    end = text.index("\n\n", start)
    table = text[start:end]
    assert table.count("\n") > 8, "routing-table slice looks wrong"
    assert STATES_HEADER not in table, "slice leaked into the states table"
    return table.lower().replace("`", "")


def _recommended_next_body() -> str:
    src = SURVEY_PY.read_text(encoding="utf-8")
    start = src.index("def _recommended_next(")
    end = src.index("\ndef _suggested_order(", start)
    return src[start:end]


def _module_string_consts() -> dict[str, str]:
    src = SURVEY_PY.read_text(encoding="utf-8")
    return dict(
        re.findall(r'^([A-Za-z_][A-Za-z0-9_]*) = "([^"]*)"$', src, re.MULTILINE)
    )


def _routed_task_states() -> set[str]:
    """Task states `_recommended_next` branches on, literals and constants alike.

    Scoped to `t.state ==` on purpose. `rb.state ==` is the *batch* vocabulary,
    which the routing table describes in prose ("Any review batch with all tasks
    Doc-Work'd") rather than by state string; demanding those strings appear
    would make this guard fail on a table that is correct.
    """
    body = _recommended_next_body()
    consts = _module_string_consts()
    out: set[str] = set()
    for tok in re.findall(
        r't\.state == ([A-Za-z_][A-Za-z0-9_]*|"[^"]*")', body
    ):
        if tok.startswith('"'):
            out.add(tok.strip('"'))
            continue
        assert tok in consts, (
            f"_recommended_next branches on `{tok}`, which is not a module-level "
            f"string constant — this guard cannot resolve it, so the state would "
            f"escape the routing-table check"
        )
        out.add(consts[tok])
    return out


def _survey_with(*tasks):
    """A minimal `Survey` carrying only the task states a routing test needs."""
    from datetime import datetime, timezone

    return ss.Survey(
        timestamp=datetime(2026, 8, 27, tzinfo=timezone.utc),
        main_root=Path("/tmp/x"),
        head_short="abc1234",
        stale_days=7,
        tasks=list(tasks),
        review_batches=[],
        discrepancies=[],
        open_roadmap_ids=[],
    )


class TestRoutingTableIsGuarded:
    def test_every_routed_task_state_has_a_routing_row(self):
        routed = _routed_task_states()
        assert len(routed) >= 7, f"only {len(routed)} routed states found: {sorted(routed)}"
        table = _routing_table()
        missing = sorted(s for s in routed if s not in table)
        assert not missing, (
            "these task states are routed by _recommended_next but have no row "
            "in the /sitrep skill's routing-rules table:\n"
            + "\n".join(f"  {m}" for m in missing)
        )

    def test_the_extraction_is_not_silently_empty(self):
        """A guard whose extraction returns nothing passes vacuously.

        The states-table guard next door was shipped with a `>= 6` floor against
        a real count of 7, which tolerated the regex losing exactly one state.
        Cross-check against an independent, unanchored extraction rather than a
        floor: both methods must see the same set.
        """
        body = _recommended_next_body()
        loose = {
            t.strip('"')
            for t in re.findall(r'\.state == ([A-Za-z_][A-Za-z0-9_]*|"[^"]*")', body)
            if t.startswith('"')
        }
        consts = _module_string_consts()
        loose |= {
            consts[t]
            for t in re.findall(r'\.state == ([A-Za-z_][A-Za-z0-9_]*)', body)
            if t in consts
        }
        # `loose` sweeps `rb.state` too, so it is a superset by construction.
        assert _routed_task_states() <= loose
        assert _routed_task_states(), "anchored extraction is empty"

    def test_the_ordered_list_prints_the_right_wording_for_each_state(self):
        """**Wiring is not content.** `test_both_new_states_are_routed_and_ordered`
        asserts only that the constant *identifier* appears in
        `_suggested_order`'s body — so swapping the parked arm's printed string
        for the awaiting-approval wording, with the `if` condition untouched,
        passed. Found by this phase's round (guards lens, SV-24). A human
        reading the ordered list would have been told the wrong thing about
        which state a task is in.
        """
        parked = ss.TaskState(task_id="P-1", state=ss._PARKED_STATE,
                              next_action="do the park thing")
        awaiting = ss.TaskState(task_id="A-1", state=ss._AWAITING_STATE,
                                next_action="do the approval thing")
        survey = _survey_with(parked, awaiting)
        lines = ss._suggested_order(survey)
        park_line = [l for l in lines if l.startswith("P-1")]
        wait_line = [l for l in lines if l.startswith("A-1")]
        assert park_line and "is parked" in park_line[0], lines
        assert wait_line and "awaits your approval" in wait_line[0], lines
        assert "awaits your approval" not in park_line[0]
        assert "is parked" not in wait_line[0]

    def test_both_new_states_are_routed_and_ordered(self):
        """The Q-019 defect, one layer up: a state wired into the cascade and
        not into `_suggested_order` drops out of the ordered list entirely, and
        the report then contradicts itself three lines apart."""
        src = SURVEY_PY.read_text(encoding="utf-8")
        order_body = src[src.index("def _suggested_order(") :]
        order_body = order_body[: order_body.index("\ndef render_json(")]
        for const in ("_PARKED_STATE", "_AWAITING_STATE"):
            assert const in _recommended_next_body(), f"{const} not routed"
            assert const in order_body, f"{const} not in _suggested_order"


class TestClaimStallPolarity:
    """Absence of evidence must change nothing. This is the report-unknown rule."""

    def test_an_empty_tree_reports_no_stall(self, tmp_path):
        assert ss._claim_stall(tmp_path, "FEAT-1") == ("", "", [])

    def test_a_caller_that_cannot_probe_reports_no_stall(self):
        assert ss._claim_stall(None, "FEAT-1") == ("", "", [])

    def test_an_empty_claim_id_reports_no_stall(self, tmp_path):
        assert ss._claim_stall(tmp_path, "") == ("", "", [])

    def test_a_run_with_no_classification_reports_no_stall(self, tmp_path):
        """Mid-pipeline is not stalled. A run with a plan and a review but no
        classification routes to 7c — nobody is waiting on a human."""
        run = tmp_path / "sysop/runtime/claim/FEAT-1/20260827T120000Z-aaaaaaaa"
        run.mkdir(parents=True)
        (run / "plan.md").write_text("plan")
        (run / "review.md").write_text("review")
        assert ss._claim_stall(tmp_path, "FEAT-1") == ("", "", [])

    def test_an_executed_run_reports_no_stall(self, tmp_path):
        run = tmp_path / "sysop/runtime/claim/FEAT-1/20260827T120000Z-aaaaaaaa"
        run.mkdir(parents=True)
        (run / "classification.md").write_text("verdict: PROCEED\n")
        (run / "outcome.md").write_text("STATUS: COMPLETE")
        assert ss._claim_stall(tmp_path, "FEAT-1") == ("", "", [])


class TestClaimStallPositiveEvidence:
    def test_a_park_marker_alone_is_a_park(self, tmp_path):
        """The `/auto-build` shape: a park marker and no claim run directory at
        all. `/sitrep` was blind to this before Phase 237 and that half is a
        pre-existing gap, not one the orchestrator reshape created."""
        d = tmp_path / "sysop/runtime/parked"
        d.mkdir(parents=True)
        (d / "FEAT-1__20260827T120000Z.md").write_text("reason: needs a decision")
        state, action, notes = ss._claim_stall(tmp_path, "FEAT-1")
        assert state == "parked"
        assert "FEAT-1__20260827T120000Z.md" in action
        # No run exists, so no --resume line may be printed naming one.
        assert "--resume" not in action
        assert notes

    def test_a_marker_with_a_run_names_the_resume_line(self, tmp_path):
        d = tmp_path / "sysop/runtime/parked"
        d.mkdir(parents=True)
        (d / "FEAT-1__20260827T120000Z.md").write_text("reason: x")
        run = tmp_path / "sysop/runtime/claim/FEAT-1/20260827T120000Z-aaaaaaaa"
        run.mkdir(parents=True)
        state, action, _ = ss._claim_stall(tmp_path, "FEAT-1")
        assert state == "parked"
        assert "/claim-task FEAT-1 --resume 20260827T120000Z-aaaaaaaa" in action

    def test_blocked_without_a_marker_is_still_a_park(self, tmp_path):
        run = tmp_path / "sysop/runtime/claim/FEAT-1/20260827T120000Z-aaaaaaaa"
        run.mkdir(parents=True)
        (run / "classification.md").write_text("**verdict:** BLOCKED\n")
        state, action, notes = ss._claim_stall(tmp_path, "FEAT-1")
        assert state == "parked"
        assert "--resume 20260827T120000Z-aaaaaaaa" in action
        assert any("no park marker" in n for n in notes), notes

    def test_proceed_without_an_outcome_is_awaiting_approval(self, tmp_path):
        run = tmp_path / "sysop/runtime/claim/FEAT-1/20260827T120000Z-aaaaaaaa"
        run.mkdir(parents=True)
        (run / "classification.md").write_text("verdict: PROCEED\n")
        state, action, notes = ss._claim_stall(tmp_path, "FEAT-1")
        assert state == "awaiting approval"
        assert "--resume 20260827T120000Z-aaaaaaaa" in action
        assert any("7d" in n for n in notes), notes

    def test_a_marker_outranks_a_proceed_verdict(self, tmp_path):
        """A park marker is the louder, purpose-built signal: it carries the
        reason. Order matters, so it is pinned."""
        d = tmp_path / "sysop/runtime/parked"
        d.mkdir(parents=True)
        (d / "FEAT-1__20260827T120000Z.md").write_text("reason: x")
        run = tmp_path / "sysop/runtime/claim/FEAT-1/20260827T120000Z-aaaaaaaa"
        run.mkdir(parents=True)
        (run / "classification.md").write_text("verdict: PROCEED\n")
        assert ss._claim_stall(tmp_path, "FEAT-1")[0] == "parked"

    def test_the_probe_itself_is_claim_kind_agnostic(self, tmp_path):
        """**Scope, stated because the first version of this test overclaimed.**

        `_claim_stall` treats `BATCH-<N>` as an ordinary claim id — that is all
        this asserts. It does NOT show that `/sitrep` reports a parked batch:
        `run_survey`'s lock loop `continue`s on a `BATCH-`/`TASK-` prefix before
        `_classify_task` is ever called, so the probe is unreachable on the batch
        path and a parked batch still classifies through
        `_classify_review_batches`, which has its own vocabulary and no park
        state. Filed as `Q-317`.

        The first version called this "one code path serves both claim kinds …
        what stops this reader going batch-blind the way Phase 155's gate did"
        — while testing the helper directly and bypassing the very path that
        would have shown it batch-blind. That is Phase 155's failure mode
        reproduced inside a test invoking Phase 155 by name.
        """
        d = tmp_path / "sysop/runtime/parked"
        d.mkdir(parents=True)
        (d / "BATCH-3__20260827T120000Z.md").write_text("reason: x")
        assert ss._claim_stall(tmp_path, "BATCH-3")[0] == "parked"

    def test_the_batch_path_does_not_reach_the_probe_and_that_is_recorded(self):
        """Pins the gap so it cannot be quietly closed or quietly forgotten.

        If a later phase wires batches through, this test reddens and its owner
        re-reads `Q-317` — which is the point. A gap nothing asserts is a gap
        the next reader has to rediscover.
        """
        src = SURVEY_PY.read_text(encoding="utf-8")
        i = src.index("def run_survey(")
        body = src[i:]
        assert 'task_id.startswith("BATCH-")' in body, (
            "run_survey no longer skips BATCH- locks — if the batch path now "
            "reaches _classify_task, close Q-317 and delete this test"
        )
        # One definition + exactly one call site. A second call site is the
        # likely shape of a batch wiring, so it reddens here deliberately.
        assert src.count("_claim_stall(") == 2, (
            f"the probe has {src.count('_claim_stall(') - 1} call site(s), not "
            f"1 — re-check whether the batch path now reaches it (Q-317)"
        )

    def test_the_newest_run_wins_and_it_is_lexical_not_mtime(self, tmp_path):
        """Run ids are `<UTC stamp>-<hex>`, so lexical sort is chronological.
        Deliberately not mtime: this directory is gitignored, so a clone or a
        copy — which reset mtime — is an ordinary thing to happen to it. The
        older run is written LAST here, so an mtime-based pick would take it."""
        base = tmp_path / "sysop/runtime/claim/FEAT-1"
        new = base / "20260828T090000Z-bbbbbbbb"
        new.mkdir(parents=True)
        (new / "classification.md").write_text("verdict: PROCEED\n")
        old = base / "20260827T120000Z-aaaaaaaa"
        old.mkdir(parents=True)
        (old / "classification.md").write_text("verdict: BLOCKED\n")
        assert ss._newest_claim_run(tmp_path, "FEAT-1").name == new.name
        assert ss._claim_stall(tmp_path, "FEAT-1")[0] == "awaiting approval"

    def test_multiple_markers_report_the_count_and_name_the_newest(self, tmp_path):
        d = tmp_path / "sysop/runtime/parked"
        d.mkdir(parents=True)
        (d / "FEAT-1__20260826T120000Z.md").write_text("older")
        (d / "FEAT-1__20260828T120000Z.md").write_text("newer")
        _, action, notes = ss._claim_stall(tmp_path, "FEAT-1")
        assert "20260828T120000Z" in action
        assert any("2 park markers" in n for n in notes), notes

    def test_the_double_underscore_separator_is_load_bearing(self, tmp_path):
        """Both park writers use `<id>__<stamp>.md`. Loosening the glob to a
        single underscore survived the round's battery (SV-03) because for the
        shipped filename shape the two patterns match identically — the gap was
        that the separator was pinned nowhere. A file using ONE underscore is
        not a park marker, and this is what says so."""
        d = tmp_path / "sysop/runtime/parked"
        d.mkdir(parents=True)
        (d / "FEAT-1_20260827T120000Z.md").write_text("single underscore")
        assert ss._claim_stall(tmp_path, "FEAT-1") == ("", "", [])
        (d / "FEAT-1__20260827T120000Z.md").write_text("double underscore")
        assert ss._claim_stall(tmp_path, "FEAT-1")[0] == "parked"

    def test_another_claims_marker_is_not_this_claims_park(self, tmp_path):
        """The glob is `<id>__*`, so `FEAT-10` must not match `FEAT-1`."""
        d = tmp_path / "sysop/runtime/parked"
        d.mkdir(parents=True)
        (d / "FEAT-10__20260827T120000Z.md").write_text("reason: x")
        assert ss._claim_stall(tmp_path, "FEAT-1") == ("", "", [])


class TestVerdictParsing:
    def test_a_missing_classification_yields_no_verdict(self, tmp_path):
        assert ss._classification_verdict(tmp_path) == ""

    def test_an_unparseable_body_yields_no_verdict_not_a_default(self, tmp_path):
        """Guessing PROCEED would invent a human gate nobody is standing at;
        guessing BLOCKED would invent a park. "" is the only honest answer."""
        (tmp_path / "classification.md").write_text("no verdict line here\n")
        assert ss._classification_verdict(tmp_path) == ""

    def test_an_uppercase_label_is_tolerated(self, tmp_path):
        """`re.IGNORECASE` was doing nothing any test exercised — the value's
        char class is already `[A-Za-z_]+`, and every fixture used a lowercase
        label. Dropping the flag survived the round's battery (SV-05). If the
        flag is wanted, this is what it buys."""
        (tmp_path / "classification.md").write_text("VERDICT: PROCEED\n")
        assert ss._classification_verdict(tmp_path) == "PROCEED"

    def test_emphasis_and_blockquote_markers_are_tolerated(self, tmp_path):
        for body in (
            "verdict: PROCEED",
            "**verdict:** PROCEED",
            "> verdict: proceed",
            "- verdict: Proceed",
        ):
            (tmp_path / "classification.md").write_text(body + "\n")
            assert ss._classification_verdict(tmp_path) == "PROCEED", body


class TestClassifierIntegration:
    """`_classify_task` must reach the probe, and must not reach it too eagerly."""

    def _classify(self, tmp_path, commits, main_root):
        from datetime import datetime, timezone

        lock = ss.Lock(task_id="FEAT-1", path=tmp_path / "l.lock", started="")
        return ss._classify_task(
            task_id="FEAT-1",
            lock=lock,
            worktree=None,
            branch="task/feat-1",
            index_entry=None,
            commits=commits,
            unpushed=0,
            dirty=False,
            stale_days=7,
            phase40_cutoff=datetime(2020, 1, 1, tzinfo=timezone.utc),
            main_root=main_root,
        )

    def test_a_parked_claim_no_longer_classifies_as_planning(self, tmp_path):
        d = tmp_path / "sysop/runtime/parked"
        d.mkdir(parents=True)
        (d / "FEAT-1__20260827T120000Z.md").write_text("reason: x")
        ts = self._classify(tmp_path, [], tmp_path)
        assert ts.state == "parked"
        assert ts.notes

    def test_an_unstarted_claim_still_classifies_as_planning(self, tmp_path):
        ts = self._classify(tmp_path, [], tmp_path)
        assert ts.state == "planning"

    def test_a_direct_caller_with_no_main_root_still_classifies_as_planning(self):
        ts = self._classify(Path("/nonexistent"), [], None)
        assert ts.state == "planning"

    def test_a_park_outranks_the_stale_arm_whose_advice_is_destructive(self, tmp_path):
        """**The fix the author made and then failed to guard.**

        `_classify_task`'s stale check `return`s before the classification arms.
        A park is by construction long-lived — it is waiting on an absent human
        — so past `--stale-days` it was classified `stale`, whose `next_action`
        is *"confirm dead and rm the lock if abandoned"*: destructive advice
        about a live claim. Every other integration test here builds
        `Lock(started="")`, which short-circuits the stale check and hid it;
        this one supplies a real old timestamp, which is the whole point.

        Found by this phase's round (claims lens), and the re-run battery then
        showed the fix itself had no guard — restoring the old ordering passed
        the suite. This is that guard.
        """
        from datetime import datetime, timedelta, timezone

        d = tmp_path / "sysop/runtime/parked"
        d.mkdir(parents=True)
        (d / "FEAT-1__20260701T120000Z.md").write_text("reason: waiting on you")
        old_stamp = (
            datetime.now(timezone.utc) - timedelta(days=30)
        ).isoformat().replace("+00:00", "Z")
        lock = ss.Lock(task_id="FEAT-1", path=tmp_path / "l.lock", started=old_stamp)
        ts = ss._classify_task(
            task_id="FEAT-1", lock=lock, worktree=None, branch="task/feat-1",
            index_entry=None, commits=[], unpushed=0, dirty=False, stale_days=7,
            phase40_cutoff=datetime(2020, 1, 1, tzinfo=timezone.utc),
            main_root=tmp_path,
        )
        assert ts.state == "parked", (
            f"a 30-day-old PARKED claim classified {ts.state!r}; the stale arm "
            f"would tell the human to rm the lock of a live claim"
        )
        assert "rm " not in ts.next_action

    def test_an_unparked_stale_claim_is_still_stale(self, tmp_path):
        """The negative control for the arm above. Making a park outrank `stale`
        must not disable `stale` — that would trade one silent state for
        another, which is the failure this whole leg is about."""
        from datetime import datetime, timedelta, timezone

        old_stamp = (
            datetime.now(timezone.utc) - timedelta(days=30)
        ).isoformat().replace("+00:00", "Z")
        lock = ss.Lock(task_id="FEAT-1", path=tmp_path / "l.lock", started=old_stamp)
        ts = ss._classify_task(
            task_id="FEAT-1", lock=lock, worktree=None, branch="task/feat-1",
            index_entry=None, commits=[], unpushed=0, dirty=False, stale_days=7,
            phase40_cutoff=datetime(2020, 1, 1, tzinfo=timezone.utc),
            main_root=tmp_path,
        )
        assert ts.state == "stale"

    def test_a_claim_with_commits_never_reaches_the_probe(self, tmp_path):
        """The probe is scoped to the 0-commit arm. A claim that has built
        something is `in progress` whatever is sitting in its park archive —
        the park archive is not cleaned on resume, so a stale marker must not
        drag a live build backwards."""
        d = tmp_path / "sysop/runtime/parked"
        d.mkdir(parents=True)
        (d / "FEAT-1__20260827T120000Z.md").write_text("reason: x")
        commit = ss.Commit(
            sha="a" * 40,
            subject="feat: work",
            author_date=__import__("datetime").datetime(
                2026, 8, 27, tzinfo=__import__("datetime").timezone.utc
            ),
            doc_work_ids=[],
            subject_task_id="",
        )
        ts = self._classify(tmp_path, [commit], tmp_path)
        assert ts.state == "in progress"


# ── The round's HIGH finding, and the fixture that would have caught it ──

CLAIM_TASK_SKILL = REPO_ROOT / "core/skills/claim-task/SKILL.md"


def shipped_classification(verdict: str) -> str:
    """`classification.md` in the shape `/claim-task` Step 7c ACTUALLY writes.

    Step 7c emits `json.dumps(report, indent=2)` inside a ```yaml fence, so the
    verdict on disk is `  "verdict": "PROCEED"` — NOT a line beginning
    `verdict:`. Phase 237's first cut of `_classification_verdict` scanned for
    the latter and matched nothing the writer produces, so `awaiting approval`
    was unreachable in production while every test here passed, because every
    fixture hand-typed a flat shape nothing in the tree emits.

    Fixtures that matter must be generated in the writer's shape, not in a
    shape convenient to the reader.
    """
    return "# Classification — FEAT-1 run r\n\n```yaml\n{}\n```\n".format(
        json.dumps(
            {"claim_id": "FEAT-1", "run_id": "r", "verdict": verdict,
             "classified_by": "orchestrator", "findings": []},
            indent=2, ensure_ascii=False,
        )
    )


class TestTheReaderMatchesTheWriter:
    """The guard against the class, not just the instance."""

    def test_step_7c_still_writes_a_fenced_json_body(self):
        """If the writer changes shape, this reddens here rather than silently
        making both readers dead again."""
        text = CLAIM_TASK_SKILL.read_text()
        i = text.index("### Step 7c: Classify")
        j = text.index("### Step 7d", i)
        block = text[i:j]
        assert "json.dumps(report, indent=2" in block, (
            "Step 7c no longer writes classification.md with json.dumps — the "
            "verdict readers in sitrep_survey.py and /review-close Step 2e are "
            "written against that shape"
        )
        assert "```yaml" in block

    def test_the_reader_sees_the_shipped_writers_output(self, tmp_path):
        for verdict in ("PROCEED", "BLOCKED", "SUPERSEDED"):
            (tmp_path / "classification.md").write_text(shipped_classification(verdict))
            assert ss._classification_verdict(tmp_path) == verdict, verdict

    def test_awaiting_approval_is_reachable_from_the_shipped_format(self, tmp_path):
        """The end-to-end version: the state this leg shipped must actually be
        produced by a tree the orchestrator could really have left behind."""
        run = tmp_path / "sysop/runtime/claim/FEAT-1/20260827T120000Z-aaaaaaaa"
        run.mkdir(parents=True)
        (run / "classification.md").write_text(shipped_classification("PROCEED"))
        assert ss._claim_stall(tmp_path, "FEAT-1")[0] == "awaiting approval"

    def test_blocked_without_a_marker_is_reachable_from_the_shipped_format(self, tmp_path):
        run = tmp_path / "sysop/runtime/claim/FEAT-1/20260827T120000Z-aaaaaaaa"
        run.mkdir(parents=True)
        (run / "classification.md").write_text(shipped_classification("BLOCKED"))
        assert ss._claim_stall(tmp_path, "FEAT-1")[0] == "parked"

    def test_a_flat_verdict_line_still_works(self, tmp_path):
        """The fallback is kept, but it is the fallback — not the primary. That
        inversion was the defect."""
        (tmp_path / "classification.md").write_text("verdict: PROCEED\n")
        assert ss._classification_verdict(tmp_path) == "PROCEED"

    def test_an_unparseable_fence_yields_no_verdict(self, tmp_path):
        (tmp_path / "classification.md").write_text("# C\n\n```yaml\n{not json\n```\n")
        assert ss._classification_verdict(tmp_path) == ""

    def test_a_fence_without_a_verdict_key_yields_nothing(self, tmp_path):
        (tmp_path / "classification.md").write_text(
            "# C\n\n```yaml\n" + json.dumps({"claim_id": "x"}, indent=2) + "\n```\n"
        )
        assert ss._classification_verdict(tmp_path) == ""
