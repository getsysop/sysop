"""Tests for ``core/companion/scripts/next_task.py`` — deterministic /next-task resolver.

Ported from gdp's ``tests/test_next_task.py`` (41 functions, 697 lines).
gdp baseline confirmed passing 2026-05-27 (`pytest -v` returned 41 passed,
0 skipped, 0 xfail).

Generalization adjustments versus gdp (recorded for the PORT_LOG):
- gdp's `sys.path.insert` and `APP_ENV` setdefault dropped — Sysop's
  pyproject.toml `[tool.pytest.ini_options] pythonpath` provides import
  resolution; the script under test does not read APP_ENV.
- ``test_infer_batch_user_action_detects_keyword`` — gdp asserts
  ``firebase`` ∈ ``_USER_ACTION_KEYWORDS``. Sysop's Phase 45a port
  stripped gdp-specific keywords (stripe dashboard, firebase, cloud sql
  proxy, vertex ai). Test rewritten to assert ``console`` + ``dashboard``,
  both still in Sysop's keyword tuple.
- Body section keys are taken from the file as Sysop's `next_task.py`
  reads them (lowercased); the gdp comment about ``validate_tasks.py``
  line numbers is preserved as historical context, even though the line
  numbers diverge from Sysop's source.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

import next_task as nt


def _build_repo(tmp_path: Path, index_yaml: str, bodies: dict[str, str]) -> Path:
    """Construct a synthetic repo layout under ``tmp_path``."""
    tasks_dir = tmp_path / "tasks"
    open_dir = tasks_dir / "open"
    open_dir.mkdir(parents=True)
    (tmp_path / ".locks").mkdir()
    (tmp_path / ".locks" / ".gitkeep").write_text("", encoding="utf-8")
    (tasks_dir / "index.yml").write_text(index_yaml, encoding="utf-8")
    for name, body in bodies.items():
        (open_dir / name).write_text(body, encoding="utf-8")
    (tmp_path / "review_tasks.md").write_text("", encoding="utf-8")
    return tmp_path


_BASE_INDEX = """\
schema_version: 2

phases:
  - number: 5
    title: "Done phase"
    status: done
    current_focus: false
  - number: 6
    title: "Active phase"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-EASY
    title: "Easy task"
    phase: 6
    status: open
    effort: Low
    blast_radius: single-file
    user_action: false
    body: open/FEAT-EASY.md

  - id: FEAT-MEDIUM
    title: "Medium task"
    phase: 6
    status: open
    effort: Medium
    blast_radius: single-module
    user_action: false
    body: open/FEAT-MEDIUM.md

  - id: TECH-HARD
    title: "Hard task"
    phase: 6
    status: open
    effort: High
    blast_radius: cross-module
    user_action: false
    body: open/TECH-HARD.md

  - id: FEAT-USER
    title: "Needs the human"
    phase: 6
    status: open
    effort: Low
    blast_radius: single-file
    user_action: true
    body: open/FEAT-USER.md

  - id: FEAT-DONE
    title: "Done task"
    phase: 5
    status: done
    completed_date: "2026-01-01"
    body: open/FEAT-DONE.md
"""

_BASE_BODIES = {
    "FEAT-EASY.md": "# FEAT-EASY\n\n## Context\nEasy context.\n\n## Requirements\n1. Do thing.\n",
    "FEAT-MEDIUM.md": "# FEAT-MEDIUM\n\n## Context\nMedium context.\n",
    "TECH-HARD.md": "# TECH-HARD\n\n## Context\nHard.\n",
    "FEAT-USER.md": (
        "# FEAT-USER\n\n## Context\nUser ctx.\n\n## User ops (do these first)\n"
        "Login to console.\n"
    ),
    "FEAT-DONE.md": "# FEAT-DONE\n\nDone body.\n",
}


# ── load_index + schema_version ───────────────────────────────────────────


def test_load_index_round_trip(tmp_path: Path) -> None:
    repo = _build_repo(tmp_path, _BASE_INDEX, _BASE_BODIES)
    data = nt.load_index(repo / "tasks" / "index.yml")
    assert data["schema_version"] == 2
    assert len(data["tasks"]) == 5


def test_load_index_missing_file_exits_1(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        nt.load_index(tmp_path / "does-not-exist.yml")
    assert exc.value.code == 1


def test_load_index_yaml_error_exits_1(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yml"
    bad.write_text("schema_version: 2\n  bad: : : :\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        nt.load_index(bad)
    assert exc.value.code == 1


def test_assert_schema_version_accepts_v1_and_v2() -> None:
    nt._assert_schema_version({"schema_version": 1})
    nt._assert_schema_version({"schema_version": 2})


def test_assert_schema_version_rejects_v0(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        nt._assert_schema_version({"schema_version": 0})
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "older than supported minimum" in err


def test_assert_schema_version_rejects_missing(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        nt._assert_schema_version({})
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "schema_version" in err


def test_assert_schema_version_rejects_bool() -> None:
    with pytest.raises(SystemExit) as exc:
        nt._assert_schema_version({"schema_version": True})
    assert exc.value.code == 1


# ── find_focus_phase ──────────────────────────────────────────────────────


def test_find_focus_phase_happy_path() -> None:
    data = {
        "phases": [
            {"number": 1, "current_focus": False},
            {"number": 2, "current_focus": True},
        ]
    }
    p = nt.find_focus_phase(data)
    assert p["number"] == 2


def test_find_focus_phase_zero_focus_exits_1() -> None:
    with pytest.raises(SystemExit) as exc:
        nt.find_focus_phase({"phases": [{"number": 1, "current_focus": False}]})
    assert exc.value.code == 1


def test_find_focus_phase_two_focus_exits_1() -> None:
    with pytest.raises(SystemExit) as exc:
        nt.find_focus_phase(
            {
                "phases": [
                    {"number": 1, "current_focus": True},
                    {"number": 2, "current_focus": True},
                ]
            }
        )
    assert exc.value.code == 1


# ── pick_next_task ────────────────────────────────────────────────────────


def _load_base(tmp_path: Path) -> dict:
    repo = _build_repo(tmp_path, _BASE_INDEX, _BASE_BODIES)
    return nt.load_index(repo / "tasks" / "index.yml")


def test_pick_next_task_prefers_low_effort_agent(tmp_path: Path) -> None:
    data = _load_base(tmp_path)
    selected, user_pool = nt.pick_next_task(data, locks=set(), focus_phase_number=6)
    assert selected is not None
    assert selected["id"] == "FEAT-EASY"
    assert [t["id"] for t in user_pool] == ["FEAT-USER"]


def test_pick_next_task_skips_locked(tmp_path: Path) -> None:
    data = _load_base(tmp_path)
    selected, _ = nt.pick_next_task(data, locks={"FEAT-EASY"}, focus_phase_number=6)
    assert selected is not None
    assert selected["id"] == "FEAT-MEDIUM"


def test_pick_next_task_skips_blocked_by_dep(tmp_path: Path) -> None:
    index = _BASE_INDEX.replace(
        "  - id: FEAT-EASY\n    title: \"Easy task\"\n    phase: 6\n    status: open\n",
        "  - id: FEAT-EASY\n    title: \"Easy task\"\n    phase: 6\n    status: open\n"
        "    depends_on: [FEAT-MEDIUM]\n",
    )
    repo = _build_repo(tmp_path, index, _BASE_BODIES)
    data = nt.load_index(repo / "tasks" / "index.yml")
    selected, _ = nt.pick_next_task(data, locks=set(), focus_phase_number=6)
    assert selected is not None
    assert selected["id"] == "FEAT-MEDIUM"


def test_pick_next_task_skips_on_hold(tmp_path: Path) -> None:
    index = _BASE_INDEX.replace(
        "  - id: FEAT-EASY\n    title: \"Easy task\"\n    phase: 6\n    status: open\n",
        "  - id: FEAT-EASY\n    title: \"Easy task\"\n    phase: 6\n    status: open\n"
        "    on_hold_until: \"2030-01-01\"\n",
    )
    repo = _build_repo(tmp_path, index, _BASE_BODIES)
    data = nt.load_index(repo / "tasks" / "index.yml")
    selected, _ = nt.pick_next_task(data, locks=set(), focus_phase_number=6)
    assert selected is not None
    assert selected["id"] == "FEAT-MEDIUM"


def test_pick_next_task_returns_none_when_no_agent(tmp_path: Path) -> None:
    data = _load_base(tmp_path)
    locks = {"FEAT-EASY", "FEAT-MEDIUM", "TECH-HARD"}
    selected, user_pool = nt.pick_next_task(data, locks=locks, focus_phase_number=6)
    assert selected is None
    assert [t["id"] for t in user_pool] == ["FEAT-USER"]


def test_pick_next_task_filters_to_focus_phase(tmp_path: Path) -> None:
    data = _load_base(tmp_path)
    selected, user_pool = nt.pick_next_task(data, locks=set(), focus_phase_number=5)
    assert selected is None
    assert user_pool == []


def test_pick_next_task_tie_break_by_id(tmp_path: Path) -> None:
    index = _BASE_INDEX.replace(
        "    effort: Medium",
        "    effort: Low",
        1,
    )
    repo = _build_repo(tmp_path, index, _BASE_BODIES)
    data = nt.load_index(repo / "tasks" / "index.yml")
    selected, _ = nt.pick_next_task(data, locks=set(), focus_phase_number=6)
    assert selected is not None
    assert selected["id"] == "FEAT-EASY"


# ── pick_next_task: unblocker-first ordering (Phase 74) ────────────────────
#
# pick_next_task reads only the parsed dict, so these unit tests build the
# index in memory (mirrors test_find_focus_phase_happy_path) — no on-disk
# fixture needed, which keeps the dependency graphs legible.


def _phase6_data(tasks: list[dict]) -> dict:
    """Minimal in-memory index: one focus phase (6) + the given task list."""
    return {
        "schema_version": 2,
        "phases": [{"number": 6, "current_focus": True}],
        "tasks": tasks,
    }


def _t(
    tid: str,
    effort: str = "Low",
    *,
    phase: int = 6,
    status: str = "open",
    depends_on: list[str] | None = None,
    user_action: bool = False,
) -> dict:
    t: dict = {
        "id": tid,
        "phase": phase,
        "status": status,
        "effort": effort,
        "blast_radius": "single-file",
        "user_action": user_action,
    }
    if depends_on is not None:
        t["depends_on"] = depends_on
    return t


def test_pick_next_task_unblocker_outranks_lower_effort() -> None:
    # TECH-HARD unblocks two open same-phase tasks; FEAT-EASY (Low) unblocks
    # nothing. Unblocker-first must pick TECH-HARD despite its higher effort.
    data = _phase6_data(
        [
            _t("TECH-HARD", "High"),
            _t("FEAT-EASY", "Low"),
            _t("DEP-1", "Low", depends_on=["TECH-HARD"]),
            _t("DEP-2", "Low", depends_on=["TECH-HARD"]),
        ]
    )
    selected, _ = nt.pick_next_task(data, locks=set(), focus_phase_number=6)
    assert selected is not None
    assert selected["id"] == "TECH-HARD"


def test_pick_next_task_unlock_tie_breaks_by_effort() -> None:
    # Both unblock exactly one dependent → effort breaks the tie (Low < Medium).
    data = _phase6_data(
        [
            _t("FEAT-MED", "Medium"),
            _t("FEAT-EASY", "Low"),
            _t("DEP-M", "Low", depends_on=["FEAT-MED"]),
            _t("DEP-E", "Low", depends_on=["FEAT-EASY"]),
        ]
    )
    selected, _ = nt.pick_next_task(data, locks=set(), focus_phase_number=6)
    assert selected is not None
    assert selected["id"] == "FEAT-EASY"


def test_pick_next_task_unlock_tie_breaks_by_id() -> None:
    # Equal unlock_count AND equal effort → id breaks the tie (TECH-A < TECH-B).
    data = _phase6_data(
        [
            _t("TECH-B", "Low"),
            _t("TECH-A", "Low"),
            _t("DEP-B", "Low", depends_on=["TECH-B"]),
            _t("DEP-A", "Low", depends_on=["TECH-A"]),
        ]
    )
    selected, _ = nt.pick_next_task(data, locks=set(), focus_phase_number=6)
    assert selected is not None
    assert selected["id"] == "TECH-A"


def test_pick_next_task_unlock_counts_open_dependents_only() -> None:
    # A deferred dependent must NOT count toward unlock_count — so TECH-HARD
    # stays at 0 unlocks and the Low-effort FEAT-EASY wins on effort.
    data = _phase6_data(
        [
            _t("TECH-HARD", "High"),
            _t("FEAT-EASY", "Low"),
            _t("DEP-DEFERRED", "Low", status="deferred", depends_on=["TECH-HARD"]),
        ]
    )
    selected, _ = nt.pick_next_task(data, locks=set(), focus_phase_number=6)
    assert selected is not None
    assert selected["id"] == "FEAT-EASY"


def test_pick_next_task_unlock_counts_same_phase_dependents_only() -> None:
    # A dependent in a different phase must NOT count — TECH-HARD stays at 0
    # unlocks and Low-effort FEAT-EASY wins.
    data = _phase6_data(
        [
            _t("TECH-HARD", "High"),
            _t("FEAT-EASY", "Low"),
            _t("DEP-OTHER-PHASE", "Low", phase=7, depends_on=["TECH-HARD"]),
        ]
    )
    selected, _ = nt.pick_next_task(data, locks=set(), focus_phase_number=6)
    assert selected is not None
    assert selected["id"] == "FEAT-EASY"


def test_pick_next_task_unlock_counts_dependent_still_blocked_by_other_deps() -> None:
    # "Simple direct count" design decision: a dependent that is ALSO blocked by
    # a second, unmet dep still counts toward this task's unlock_count (no graph
    # walk to check whether unblocking THIS task would actually free it). So
    # TECH-HARD — whose only dependent (DEP-MULTI) is also blocked by the parked
    # BLOCKER-X — still outranks the Low-effort leaf. A "sole-remaining-blocker"
    # implementation would leave TECH-HARD at 0 unlocks and pick FEAT-EASY.
    data = _phase6_data(
        [
            _t("TECH-HARD", "High"),
            _t("FEAT-EASY", "Low"),
            _t("BLOCKER-X", "Low", status="deferred"),
            _t("DEP-MULTI", "Low", depends_on=["TECH-HARD", "BLOCKER-X"]),
        ]
    )
    selected, _ = nt.pick_next_task(data, locks=set(), focus_phase_number=6)
    assert selected is not None
    assert selected["id"] == "TECH-HARD"


def test_pick_next_task_user_action_pool_is_unblocker_sorted() -> None:
    # The user_action fallback list is unblocker-first too: FEAT-U2 unblocks a
    # dependent, FEAT-U1 does not → FEAT-U2 leads the returned pool.
    data = _phase6_data(
        [
            _t("FEAT-U1", "Low", user_action=True),
            _t("FEAT-U2", "Low", user_action=True),
            _t("DEP-U2", "Low", depends_on=["FEAT-U2"]),
        ]
    )
    selected, user_pool = nt.pick_next_task(data, locks=set(), focus_phase_number=6)
    assert selected is None  # both agent-executable candidates are user_action
    assert [t["id"] for t in user_pool] == ["FEAT-U2", "FEAT-U1"]


# ── pick_next_task: --avoid-inflight collision ranking (Phase 103, Leg A) ──
#
# overlap_fn is injected here (a plain tid->rank callable), so these tests lock
# the *ranking* contract without any git repo or scope_overlap import — the
# primitive itself is covered by tests/test_scope_overlap.py. The main() wiring
# that builds the real overlap_fn is hand-verified on a scratch repo (Phase 74
# precedent for the heredoc-adjacent surfaces).


def test_pick_next_task_avoid_inflight_likely_prefers_clear_task() -> None:
    # Two Low leaves, equal unlock (0). FEAT-A has a LIKELY (exact-path) overlap
    # (rank 2), FEAT-B is clear (0). Default order (id tie-break) picks FEAT-A;
    # --avoid-inflight must flip to FEAT-B because `likely` is the primary key.
    data = _phase6_data([_t("FEAT-A", "Low"), _t("FEAT-B", "Low")])
    default_sel, _ = nt.pick_next_task(data, locks=set(), focus_phase_number=6)
    assert default_sel is not None and default_sel["id"] == "FEAT-A"
    sel, _ = nt.pick_next_task(
        data, locks=set(), focus_phase_number=6,
        overlap_fn=lambda tid: 2 if tid == "FEAT-A" else 0,
    )
    assert sel is not None and sel["id"] == "FEAT-B"


def test_pick_next_task_avoid_inflight_likely_outranks_unblocker() -> None:
    # The deliberate asymmetry vs /auto-build: under the explicit flag, a LIKELY
    # (exact-path) overlap is PRIMARY — it beats even a foundational unblocker.
    # TECH-HARD unblocks two (unlock=2) but collides likely (rank 2); FEAT-EASY
    # is clear. Default picks the unblocker; the flag picks the clear leaf.
    data = _phase6_data(
        [
            _t("TECH-HARD", "High"),
            _t("FEAT-EASY", "Low"),
            _t("DEP-1", "Low", depends_on=["TECH-HARD"]),
            _t("DEP-2", "Low", depends_on=["TECH-HARD"]),
        ]
    )
    default_sel, _ = nt.pick_next_task(data, locks=set(), focus_phase_number=6)
    assert default_sel is not None and default_sel["id"] == "TECH-HARD"
    sel, _ = nt.pick_next_task(
        data, locks=set(), focus_phase_number=6,
        overlap_fn=lambda tid: 2 if tid == "TECH-HARD" else 0,
    )
    assert sel is not None and sel["id"] == "FEAT-EASY"


def test_pick_next_task_avoid_inflight_possible_does_not_bury_unblocker() -> None:
    # The two-tier refinement: a POSSIBLE (same-dir/glob) overlap is only a
    # SECONDARY nudge — a weak guess must not bury a foundational task. TECH-HARD
    # unblocks two (unlock=2) with a `possible` overlap (rank 1); FEAT-EASY is a
    # clear leaf (unlock 0). The unblocker still wins — a naive "all overlap is
    # primary" implementation would wrongly pick FEAT-EASY here.
    data = _phase6_data(
        [
            _t("TECH-HARD", "High"),
            _t("FEAT-EASY", "Low"),
            _t("DEP-1", "Low", depends_on=["TECH-HARD"]),
            _t("DEP-2", "Low", depends_on=["TECH-HARD"]),
        ]
    )
    sel, _ = nt.pick_next_task(
        data, locks=set(), focus_phase_number=6,
        overlap_fn=lambda tid: 1 if tid == "TECH-HARD" else 0,
    )
    assert sel is not None and sel["id"] == "TECH-HARD"


def test_pick_next_task_avoid_inflight_clear_beats_possible_at_equal_unlock() -> None:
    # `possible` still nudges as a secondary tie-break: at equal unlock (0), a
    # clear task beats a possible-overlap one. FEAT-A possible (rank 1), FEAT-B
    # clear — FEAT-B wins despite the id tie-break favoring FEAT-A by default.
    data = _phase6_data([_t("FEAT-A", "Low"), _t("FEAT-B", "Low")])
    sel, _ = nt.pick_next_task(
        data, locks=set(), focus_phase_number=6,
        overlap_fn=lambda tid: 1 if tid == "FEAT-A" else 0,
    )
    assert sel is not None and sel["id"] == "FEAT-B"


def test_pick_next_task_avoid_inflight_uniform_tier_falls_through_to_unblocker() -> None:
    # When every candidate sits in the same overlap tier (all `likely`, rank 2),
    # the collision key is constant and the base unblocker-first key decides:
    # TECH-HARD (unlock=2) leads the clear-of-unlocks leaf.
    data = _phase6_data(
        [
            _t("TECH-HARD", "High"),
            _t("FEAT-EASY", "Low"),
            _t("DEP-1", "Low", depends_on=["TECH-HARD"]),
            _t("DEP-2", "Low", depends_on=["TECH-HARD"]),
        ]
    )
    sel, _ = nt.pick_next_task(
        data, locks=set(), focus_phase_number=6, overlap_fn=lambda tid: 2
    )
    assert sel is not None and sel["id"] == "TECH-HARD"


def test_pick_next_task_no_overlap_fn_is_inert() -> None:
    # overlap_fn=None (the default, and every path but the flag) must produce the
    # exact default ordering, so the pre-existing selection tests stay
    # authoritative — the collision code is dormant unless the flag opts in.
    data = _phase6_data([_t("FEAT-A", "Low"), _t("FEAT-B", "Low")])
    sel_none, _ = nt.pick_next_task(
        data, locks=set(), focus_phase_number=6, overlap_fn=None
    )
    sel_default, _ = nt.pick_next_task(data, locks=set(), focus_phase_number=6)
    assert sel_none is not None and sel_default is not None
    assert sel_none["id"] == sel_default["id"] == "FEAT-A"


def test_format_task_output_renders_overlap_note() -> None:
    task = {
        "id": "FEAT-X", "title": "T", "effort": "Low",
        "body": "open/x.md", "user_action": False,
    }
    out = nt.format_task_output(
        task, body_sections={}, remaining_agent=1, remaining_batches=0,
        overlap_note="⚠ likely conflict with TECH-B at /review-close — shared: a.py",
    )
    assert "**In-flight overlap:** ⚠ likely conflict with TECH-B" in out


def test_format_task_output_omits_overlap_note_when_empty() -> None:
    # No note → no field, so the default (no --avoid-inflight) output is unchanged.
    task = {
        "id": "FEAT-X", "title": "T", "effort": "Low",
        "body": "open/x.md", "user_action": False,
    }
    out = nt.format_task_output(
        task, body_sections={}, remaining_agent=1, remaining_batches=0
    )
    assert "In-flight overlap" not in out


# ── Review batch parsing ──────────────────────────────────────────────────


_REVIEW_FIXTURE = textwrap.dedent(
    """\
    # Code Review Tasks

    ## Legend

    Filler legend section.

    ### Batch 100 — Backend Hardening `Pending`

    > **Branch:** `fix/batch-100-backend-hardening`
    > **Scope:** `<api module>/server.py`, `<api module>/tools.py`
    > **Verify:** `APP_ENV=test pytest tests/test_server.py`

    - [ ] **TASK-9001**: Sanitize log in get_user 🔴
    - [ ] **TASK-9002**: Add Query bounds 🟡
    - [x] **TASK-9003**: Already fixed earlier 🟢

    ---

    ### Batch 101 — Frontend Refinement `Pending`

    > **Branch:** `fix/batch-101-frontend`
    > **Scope:** `<frontend>/app/components/`
    > **Verify:** `cd <frontend> && npm run test`

    - [ ] **TASK-9101**: Add aria-label to icon button 🟢
    - [ ] **TASK-9102**: Wrap fetch in useAbortableFetch 🟡

    ---

    ### Batch 102 — Closed Already `Complete`

    > **Branch:** `fix/batch-102-closed`
    > **Verify:** `APP_ENV=test pytest tests/test_misc.py`

    - [x] **TASK-9201**: Done 🟢
    """
)


def test_parse_review_batches_extracts_three_blocks() -> None:
    out = nt.parse_review_batches(_REVIEW_FIXTURE)
    assert [b["number"] for b in out] == [100, 101, 102]
    assert [b["status"] for b in out] == ["Pending", "Pending", "Complete"]


def test_parse_review_batches_captures_fields() -> None:
    out = nt.parse_review_batches(_REVIEW_FIXTURE)
    b100 = out[0]
    assert b100["title"] == "Backend Hardening"
    assert b100["branch"] == "fix/batch-100-backend-hardening"
    assert b100["scope"] == "`<api module>/server.py`, `<api module>/tools.py`"
    assert b100["verify"] == "APP_ENV=test pytest tests/test_server.py"
    assert b100["open_count"] == 2
    assert b100["severity"] == {"high": 1, "medium": 1, "low": 1}
    assert {t["task_id"] for t in b100["tasks"]} == {"TASK-9001", "TASK-9002", "TASK-9003"}


def test_parse_review_batches_handles_empty_input() -> None:
    assert nt.parse_review_batches("") == []
    out = nt.parse_review_batches("### Batch abc — Bad `Pending`\n")
    assert out == []


def test_pick_next_batch_skips_locked_and_returns_pending() -> None:
    batches = nt.parse_review_batches(_REVIEW_FIXTURE)
    next_b, total = nt.pick_next_batch(batches, locks={"BATCH-100"})
    assert next_b is not None
    assert next_b["number"] == 101
    assert total == 2


def test_pick_next_batch_returns_none_when_all_locked() -> None:
    batches = nt.parse_review_batches(_REVIEW_FIXTURE)
    next_b, total = nt.pick_next_batch(batches, locks={"BATCH-100", "BATCH-101"})
    assert next_b is None
    assert total == 2


def test_estimate_batch_effort_rubric() -> None:
    low = {"tasks": [{"task_id": "T1"}], "severity": {"low": 1, "medium": 0, "high": 0}}
    assert nt.estimate_batch_effort(low) == "Low"
    med = {"tasks": [{}] * 3, "severity": {"low": 0, "medium": 3, "high": 0}}
    assert nt.estimate_batch_effort(med) == "Medium"
    high = {"tasks": [{}], "severity": {"low": 0, "medium": 0, "high": 1}}
    assert nt.estimate_batch_effort(high) == "Medium"
    big = {"tasks": [{}] * 6, "severity": {"low": 6, "medium": 0, "high": 0}}
    assert nt.estimate_batch_effort(big) == "High"


def test_infer_batch_user_action_detects_keyword() -> None:
    """Diverged from gdp in Phase 45a: dropped gdp-specific keywords (firebase,
    stripe dashboard, cloud sql proxy, vertex ai). Test re-anchored on
    ``console`` + ``dashboard``, both retained in Sysop's keyword tuple.
    """
    b = {
        "verify": "APP_ENV=test pytest tests/test_x.py",
        "tasks": [
            {"task_id": "T1", "rest": "Update settings in the admin dashboard"},
            {"task_id": "T2", "rest": "Fix the bug"},
        ],
    }
    needs, reasons = nt.infer_batch_user_action(b)
    assert needs is True
    reason_blob = " | ".join(reasons)
    assert "dashboard" in reason_blob


def test_infer_batch_user_action_clean_batch() -> None:
    b = {
        "verify": "APP_ENV=test pytest tests/test_x.py",
        "tasks": [{"task_id": "T1", "rest": "Tighten a regex"}],
    }
    needs, reasons = nt.infer_batch_user_action(b)
    assert needs is False
    assert reasons == []


# ── Body section extraction + path containment ───────────────────────────


def test_extract_body_sections_dual_prefix(tmp_path: Path) -> None:
    """Both ``body: open/X.md`` and ``body: tasks/open/X.md`` must resolve."""
    repo = _build_repo(tmp_path, _BASE_INDEX, _BASE_BODIES)
    tasks_dir = repo / "tasks"

    sections_short = nt.extract_body_sections(
        "open/FEAT-EASY.md", base_tasks_dir=tasks_dir, project_root=repo
    )
    sections_long = nt.extract_body_sections(
        "tasks/open/FEAT-EASY.md", base_tasks_dir=tasks_dir, project_root=repo
    )
    assert "context" in sections_short
    assert "context" in sections_long
    assert sections_short == sections_long
    assert sections_short["context"] == "Easy context."
    assert sections_short["requirements"] == "1. Do thing."


def test_extract_body_sections_path_containment(tmp_path: Path) -> None:
    repo = _build_repo(tmp_path, _BASE_INDEX, _BASE_BODIES)
    tasks_dir = repo / "tasks"
    with pytest.raises(SystemExit) as exc:
        nt.extract_body_sections(
            "../../etc/passwd", base_tasks_dir=tasks_dir, project_root=repo
        )
    assert exc.value.code == 1


def test_extract_body_sections_user_ops(tmp_path: Path) -> None:
    repo = _build_repo(tmp_path, _BASE_INDEX, _BASE_BODIES)
    tasks_dir = repo / "tasks"
    out = nt.extract_body_sections(
        "open/FEAT-USER.md", base_tasks_dir=tasks_dir, project_root=repo
    )
    assert any("user ops" in k for k in out)
    user_ops_key = next(k for k in out if "user ops" in k)
    assert "Login to console." in out[user_ops_key]


def test_extract_body_sections_missing_file_returns_empty(tmp_path: Path) -> None:
    repo = _build_repo(tmp_path, _BASE_INDEX, _BASE_BODIES)
    tasks_dir = repo / "tasks"
    out = nt.extract_body_sections(
        "open/DOES-NOT-EXIST.md", base_tasks_dir=tasks_dir, project_root=repo
    )
    assert out == {}


# ── Output formatting (smoke / shape) ────────────────────────────────────


def test_format_task_output_shape(tmp_path: Path) -> None:
    data = _load_base(tmp_path)
    selected, _ = nt.pick_next_task(data, locks=set(), focus_phase_number=6)
    assert selected is not None
    out = nt.format_task_output(
        selected,
        body_sections={"context": "ctx", "requirements": "1. r"},
        remaining_agent=2,
        remaining_batches=0,
    )
    assert out.startswith("## Next Task\n")
    assert "### FEAT-EASY — Easy task" in out
    assert "**Effort:** Low" in out
    assert "**User action required:** No" in out
    assert "**Depends on:** None" in out
    assert "ctx" in out
    assert "1. r" in out
    assert "Suggested branch name:" in out
    assert "/claim-task FEAT-EASY" in out
    assert "Remaining in focus phase: 2 open agent-executable task(s), 0 review batch(es)" in out


def test_format_task_output_with_user_action(tmp_path: Path) -> None:
    data = _load_base(tmp_path)
    user_task = next(t for t in data["tasks"] if t["id"] == "FEAT-USER")
    out = nt.format_task_output(
        user_task,
        body_sections={
            "context": "User ctx.",
            "user ops (do these first)": "Login to console.",
        },
        remaining_agent=0,
        remaining_batches=0,
    )
    assert "**User action required:** Yes" in out
    assert "Login to console." in out


def test_format_batch_output_shape() -> None:
    batches = nt.parse_review_batches(_REVIEW_FIXTURE)
    out = nt.format_batch_output(batches[0], remaining_agent=3, remaining_batches=1)
    assert "### Review Batch 100 — Backend Hardening" in out
    assert "**Effort estimate:** Medium" in out
    assert "**Tasks:** 2 open" in out
    assert "[ ] **TASK-9001**" in out
    assert "[x] **TASK-9003**" in out
    assert "/claim-task 100" in out


def test_format_user_action_fallback() -> None:
    user_pool = [
        {"id": "FEAT-USER", "title": "Needs the human", "effort": "Low"},
    ]
    out = nt.format_user_action_fallback(user_pool, remaining_batches=0)
    assert "drained" in out
    assert "FEAT-USER" in out
    assert "Needs the human" in out
    assert "Low" in out


# ── Branch suggestion helpers ────────────────────────────────────────────


def test_default_branch_prefix() -> None:
    assert nt._default_branch_prefix("FEAT-FOO") == "feat/"
    assert nt._default_branch_prefix("FIX-FOO") == "fix/"
    assert nt._default_branch_prefix("TECH-FOO") == "tech/"
    assert nt._default_branch_prefix("DATA-FOO") == "tech/"


def test_slugify_for_branch() -> None:
    assert nt._slugify_for_branch("FEAT-WATERMARK") == "feat-watermark"
    assert nt._slugify_for_branch("TECH_FOO-BAR") == "tech-foo-bar"


# ── End-to-end: main() with synthetic repo ───────────────────────────────


def _patch_repo(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    """Repoint the module-level paths at the synthetic repo for one test."""
    tasks_dir = repo / "tasks"
    monkeypatch.setattr(nt, "_REPO_ROOT", repo)
    monkeypatch.setattr(nt, "_TASKS_DIR", tasks_dir)
    monkeypatch.setattr(nt, "_INDEX_PATH", tasks_dir / "index.yml")
    monkeypatch.setattr(nt, "_REVIEW_PATH", repo / "review_tasks.md")


def test_main_default_mode_picks_easy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _build_repo(tmp_path, _BASE_INDEX, _BASE_BODIES)
    _patch_repo(monkeypatch, repo)
    rc = nt.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "FEAT-EASY" in out
    assert "**Effort:** Low" in out


def test_main_review_mode_no_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _build_repo(tmp_path, _BASE_INDEX, _BASE_BODIES)
    _patch_repo(monkeypatch, repo)
    rc = nt.main(["--review"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip() == "No pending review batches."


def test_main_review_mode_surfaces_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _build_repo(tmp_path, _BASE_INDEX, _BASE_BODIES)
    (repo / "review_tasks.md").write_text(_REVIEW_FIXTURE, encoding="utf-8")
    _patch_repo(monkeypatch, repo)
    rc = nt.main(["--review"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Review Batch 100" in out
    assert "Backend Hardening" in out


def test_main_default_mode_falls_back_to_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _build_repo(tmp_path, _BASE_INDEX, _BASE_BODIES)
    (repo / "review_tasks.md").write_text(_REVIEW_FIXTURE, encoding="utf-8")
    locks_dir = repo / ".locks"
    for tid in ("FEAT-EASY", "FEAT-MEDIUM", "TECH-HARD"):
        (locks_dir / f"{tid}.lock").write_text("", encoding="utf-8")
    _patch_repo(monkeypatch, repo)

    rc = nt.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Review Batch 100" in out or "drained" in out


_EMPTY_FOCUS_INDEX = (
    "schema_version: 2\n"
    "phases:\n"
    "  - number: 1\n"
    "    title: \"Active\"\n"
    "    status: in_progress\n"
    "    current_focus: true\n"
    "tasks: []\n"
)


_NO_FOCUS_INDEX = (
    "schema_version: 2\n"
    "phases:\n"
    "  - number: 1\n"
    "    title: \"Not focused\"\n"
    "    status: in_progress\n"
    "    current_focus: false\n"
    "tasks: []\n"
)


def test_main_default_mode_no_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _build_repo(tmp_path, _EMPTY_FOCUS_INDEX, {})
    _patch_repo(monkeypatch, repo)
    rc = nt.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "No open tasks found" in out


def test_main_aborts_on_zero_focus(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _build_repo(tmp_path, _NO_FOCUS_INDEX, {})
    _patch_repo(monkeypatch, repo)
    with pytest.raises(SystemExit) as exc:
        nt.main([])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "exactly one phase" in err
