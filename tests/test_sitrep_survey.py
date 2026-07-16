"""Tests for ``core/companion/scripts/sitrep_survey.py``.

Sysop-original — Phase 40 (Doc-Work: git trailer ingest + lifecycle
classification). No gdp counterpart; all tests in this file are Phase 48
originals.

Scope. The pure helpers, the main classification states, and — as of
Phase 82 — the two multi-source cross-check functions the Phase 48 pass
deferred. Each turned out to isolate a single subprocess boundary behind a
small ``_git`` / ``_commits_ahead_of_main`` mock rather than the deep
fixture stack the deferral feared:

- ``_find_discrepancies`` — locks × worktrees × index × branch list, all
  five discrepancy kinds plus their negatives; one mocked branch-list
  ``_git`` shell-out, real ``Path.is_dir()`` for stale-lock detection.
- ``_classify_review_batches`` — the batch lifecycle states + flag
  truncation; ``_git`` rev-parse and ``_commits_ahead_of_main`` mocked.

Surface covered:

- ``_parse_lock_file`` — YAML happy path + non-mapping / malformed defenses.
- ``_finalize_worktree`` — porcelain dict → Worktree, main-vs-secondary.
- ``_read_locks`` / ``_read_review_batches`` / ``_read_index`` — boundary
  parsers against on-disk fixtures.
- ``_extract_doc_work_trailers`` — last-paragraph extraction, multiple IDs,
  case-insensitive key, body without trailers.
- ``_is_task_shaped_branch`` — prefix coverage including review branches.
- ``_derive_task_id_from_branch`` — explicit `branch:` match + suffix
  fallback + miss.
- ``_phase40_fallback`` — pre-cutoff subject heuristic.
- ``_classify_task`` — the four real states: planning / ready for
  /review-close (with Doc-Work trailer) / in progress (no trailer) /
  stale (lock age).
- ``_find_discrepancies`` — stale lock, orphan worktree, index-drift
  (worktree + index-scan), orphan branch, and the skip/negative paths.
- ``_classify_review_batches`` — terminal-status skip, pending
  (flagged / unflagged / truncated), claimed-no-branch, empty,
  ready-for-/review-close, in-progress (partial / zero-trailer), and
  both has_branch signals (worktree membership + rev-parse).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import yaml

import sitrep_survey as ss


# === _parse_lock_file ======================================================


def test_parse_lock_file_returns_yaml_dict(tmp_path):
    p = tmp_path / "FEAT-1.lock"
    p.write_text("task_id: FEAT-1\nbranch: feat/1\n", encoding="utf-8")
    assert ss._parse_lock_file(p) == {"task_id": "FEAT-1", "branch": "feat/1"}


def test_parse_lock_file_returns_empty_dict_for_non_mapping_yaml(tmp_path):
    p = tmp_path / "bad.lock"
    p.write_text("- item1\n- item2\n", encoding="utf-8")  # YAML list, not mapping
    assert ss._parse_lock_file(p) == {}


def test_parse_lock_file_returns_empty_dict_on_yaml_error(tmp_path):
    p = tmp_path / "broken.lock"
    p.write_text(":\n  bad: [\n", encoding="utf-8")
    assert ss._parse_lock_file(p) == {}


def test_parse_lock_file_returns_empty_dict_on_oserror(tmp_path):
    p = tmp_path / "nope.lock"  # never created
    assert ss._parse_lock_file(p) == {}


# === _read_locks ===========================================================


def test_read_locks_returns_empty_when_no_locks_dir(tmp_path):
    assert ss._read_locks(tmp_path) == []


def test_read_locks_skips_gitkeep_and_returns_one_lock_per_file(tmp_path):
    locks_dir = tmp_path / ".locks"
    locks_dir.mkdir()
    (locks_dir / ".gitkeep").write_text("", encoding="utf-8")
    (locks_dir / "FEAT-1.lock").write_text(
        "task_id: FEAT-1\nbranch: feat/1\nworkspace: /tmp/wf\n", encoding="utf-8"
    )
    (locks_dir / "FEAT-2.lock").write_text(
        "task_id: FEAT-2\nbranch: feat/2\n", encoding="utf-8"
    )
    locks = ss._read_locks(tmp_path)
    assert len(locks) == 2
    ids = sorted(l.task_id for l in locks)
    assert ids == ["FEAT-1", "FEAT-2"]
    by_id = {l.task_id: l for l in locks}
    assert by_id["FEAT-1"].branch == "feat/1"
    assert by_id["FEAT-1"].workspace == "/tmp/wf"


def test_read_locks_falls_back_to_filename_stem_when_task_id_missing(tmp_path):
    locks_dir = tmp_path / ".locks"
    locks_dir.mkdir()
    (locks_dir / "FEAT-X.lock").write_text("branch: feat/x\n", encoding="utf-8")
    locks = ss._read_locks(tmp_path)
    assert len(locks) == 1
    assert locks[0].task_id == "FEAT-X"


# === _finalize_worktree ====================================================


def test_finalize_worktree_marks_main_when_path_matches(tmp_path):
    main_root = tmp_path
    d = {"path": str(main_root), "branch": "main", "head": "abc"}
    w = ss._finalize_worktree(d, main_root)
    assert w.is_main is True
    assert w.branch == "main"


def test_finalize_worktree_marks_non_main_for_other_paths(tmp_path):
    secondary = tmp_path / "wt"
    secondary.mkdir()
    d = {"path": str(secondary), "branch": "feat/1", "head": "def"}
    w = ss._finalize_worktree(d, tmp_path)
    assert w.is_main is False
    assert w.branch == "feat/1"


# === _read_review_batches ==================================================


def test_read_review_batches_extracts_batch_with_metadata(tmp_path):
    md = (
        "intro\n"
        "### Batch 7 — Helper rename `In Progress`\n"
        "> **Branch:** `review/2026-05-20`\n"
        "> **Flag:** unsafe shell usage detected\n"
        "\n"
        "- [ ] **TASK-001**: ok\n"
        "- [/] **TASK-002**: in progress\n"
        "- [x] **TASK-003**: done\n"
    )
    (tmp_path / "review_tasks.md").write_text(md, encoding="utf-8")
    batches = ss._read_review_batches(tmp_path)
    assert len(batches) == 1
    b = batches[0]
    assert b["number"] == 7
    assert b["title"] == "Helper rename"
    assert b["status"] == "In Progress"
    assert b["branch"] == "review/2026-05-20"
    assert b["flag_reason"] == "unsafe shell usage detected"
    assert [t["id"] for t in b["tasks"]] == ["TASK-001", "TASK-002", "TASK-003"]
    assert [t["checkbox"] for t in b["tasks"]] == [" ", "/", "x"]


def test_read_review_batches_returns_empty_when_file_missing(tmp_path):
    assert ss._read_review_batches(tmp_path) == []


# === _read_index ===========================================================


def test_read_index_returns_id_keyed_dict(tmp_path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    index = {
        "schema_version": 1,
        "tasks": [
            {"id": "FEAT-1", "title": "First", "status": "open"},
            {"id": "FEAT-2", "title": "Second", "status": "in_progress"},
        ],
    }
    with open(tasks_dir / "index.yml", "w", encoding="utf-8") as f:
        yaml.safe_dump(index, f, sort_keys=False)
    out = ss._read_index(tmp_path)
    assert set(out.keys()) == {"FEAT-1", "FEAT-2"}
    assert out["FEAT-2"]["status"] == "in_progress"


def test_read_index_returns_empty_when_missing(tmp_path):
    assert ss._read_index(tmp_path) == {}


def test_read_index_silent_on_yaml_error(tmp_path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "index.yml").write_text(":\n  bad: [\n", encoding="utf-8")
    assert ss._read_index(tmp_path) == {}


# === _extract_doc_work_trailers ============================================


def test_extract_doc_work_trailers_finds_id_in_last_paragraph():
    body = (
        "Subject body paragraph 1.\n"
        "More prose.\n"
        "\n"
        "Doc-Work: FEAT-0123\n"
        "Signed-off-by: x\n"
    )
    assert ss._extract_doc_work_trailers(body) == ["FEAT-0123"]


def test_extract_doc_work_trailers_collects_multiple_ids():
    body = (
        "Intro.\n"
        "\n"
        "Doc-Work: FEAT-01\n"
        "Doc-Work: TECH-02\n"
    )
    assert ss._extract_doc_work_trailers(body) == ["FEAT-01", "TECH-02"]


def test_extract_doc_work_trailers_ignores_pre_last_paragraph_trailers():
    """Per `git interpret-trailers --parse` semantics: trailers must live in the
    LAST paragraph. A `Doc-Work:` in a body section above is body prose, not a
    trailer."""
    body = (
        "Intro.\n"
        "Doc-Work: FEAT-01\n"
        "\n"
        "Final paragraph without a trailer.\n"
    )
    assert ss._extract_doc_work_trailers(body) == []


def test_extract_doc_work_trailers_is_case_insensitive_on_key():
    body = "Body.\n\nDOC-WORK: FEAT-42\n"
    assert ss._extract_doc_work_trailers(body) == ["FEAT-42"]


def test_extract_doc_work_trailers_skips_malformed_id():
    body = "Body.\n\nDoc-Work: notanid\n"
    assert ss._extract_doc_work_trailers(body) == []


def test_extract_doc_work_trailers_empty_body_returns_empty():
    assert ss._extract_doc_work_trailers("") == []


# === _is_task_shaped_branch ================================================


def test_is_task_shaped_branch_accepts_task_prefixes():
    for b in ("task/feat-1", "feat/0001-ui", "tech/refactor", "fix/null-deref",
              "bug/123", "data/ingest", "ux/login"):
        assert ss._is_task_shaped_branch(b), f"{b} should match"


def test_is_task_shaped_branch_accepts_review_prefixes():
    assert ss._is_task_shaped_branch("review/2026-05-20") is True
    assert ss._is_task_shaped_branch("batch/42") is True


def test_is_task_shaped_branch_rejects_unrelated():
    for b in ("main", "master", "release/1.0", "hotfix/x", "wip-feature"):
        assert not ss._is_task_shaped_branch(b), f"{b} should not match"


# === _derive_task_id_from_branch ===========================================


def test_derive_task_id_matches_explicit_branch_field():
    index = {
        "FEAT-1": {"branch": "feat/0001-ui"},
        "FEAT-2": {"branch": "feat/0002"},
    }
    assert ss._derive_task_id_from_branch("feat/0001-ui", index) == "FEAT-1"


def test_derive_task_id_falls_back_to_uppercase_suffix():
    """`tech/tech-foo` → `TECH-FOO` when index entry lacks an explicit branch."""
    index = {"TECH-FOO": {"title": "x"}}
    assert ss._derive_task_id_from_branch("tech/tech-foo", index) == "TECH-FOO"


def test_derive_task_id_returns_none_on_miss():
    assert ss._derive_task_id_from_branch("feat/unknown", {}) is None


def test_derive_task_id_returns_none_for_branch_without_slash():
    assert ss._derive_task_id_from_branch("main", {"FEAT-1": {}}) is None


# === _phase40_fallback =====================================================


def _commit(subject_task_id: str | None, author_date: datetime) -> ss.Commit:
    return ss.Commit(
        sha="abc", subject="x", author_date=author_date,
        doc_work_ids=[], subject_task_id=subject_task_id,
    )


def test_phase40_fallback_returns_true_for_pre_cutoff_subject_match():
    cutoff = datetime(2026, 5, 23, tzinfo=timezone.utc)
    commits = [_commit("FEAT-1", datetime(2026, 5, 1, tzinfo=timezone.utc))]
    assert ss._phase40_fallback(commits, "FEAT-1", cutoff) is True


def test_phase40_fallback_false_for_post_cutoff_commit():
    """Post-Phase-40 commits must use trailer, not subject."""
    cutoff = datetime(2026, 5, 23, tzinfo=timezone.utc)
    commits = [_commit("FEAT-1", datetime(2026, 6, 1, tzinfo=timezone.utc))]
    assert ss._phase40_fallback(commits, "FEAT-1", cutoff) is False


def test_phase40_fallback_false_for_different_task_id():
    cutoff = datetime(2026, 5, 23, tzinfo=timezone.utc)
    commits = [_commit("FEAT-99", datetime(2026, 5, 1, tzinfo=timezone.utc))]
    assert ss._phase40_fallback(commits, "FEAT-1", cutoff) is False


def test_phase40_fallback_false_for_empty_task_id():
    cutoff = datetime(2026, 5, 23, tzinfo=timezone.utc)
    commits = [_commit("FEAT-1", datetime(2026, 5, 1, tzinfo=timezone.utc))]
    assert ss._phase40_fallback(commits, "", cutoff) is False


# === _classify_task ========================================================


_CUTOFF = datetime(2026, 5, 23, tzinfo=timezone.utc)


def _lock(task_id: str = "FEAT-1", started: str = "") -> ss.Lock:
    return ss.Lock(
        task_id=task_id, path=Path(f".locks/{task_id}.lock"),
        status="active", branch=f"feat/{task_id.lower()}",
        workspace="/tmp/wt", started=started,
    )


def _wt(branch: str = "feat/feat-1", path: str = "/tmp/wt") -> ss.Worktree:
    return ss.Worktree(path=Path(path), branch=branch, head="abc", is_main=False)


def test_classify_task_planning_when_no_commits_ahead():
    ts = ss._classify_task(
        task_id="FEAT-1",
        lock=_lock(),
        worktree=_wt(),
        branch="feat/feat-1",
        index_entry={"status": "in_progress"},
        commits=[],
        unpushed=0,
        dirty=False,
        stale_days=7,
        phase40_cutoff=_CUTOFF,
    )
    assert ts.state == "planning"
    assert "continue planning" in ts.next_action.lower() or "reviewer-executor" in ts.next_action


def test_classify_task_ready_for_review_close_with_doc_work_trailer():
    commit = ss.Commit(
        sha="abc", subject="feat: do thing",
        author_date=datetime(2026, 5, 25, tzinfo=timezone.utc),
        doc_work_ids=["FEAT-1"], subject_task_id=None,
    )
    ts = ss._classify_task(
        task_id="FEAT-1",
        lock=_lock(),
        worktree=_wt(),
        branch="feat/feat-1",
        index_entry={"status": "in_progress"},
        commits=[commit],
        unpushed=0,
        dirty=False,
        stale_days=7,
        phase40_cutoff=_CUTOFF,
    )
    assert ts.state == "ready for /review-close"
    assert ts.next_action == "/review-close FEAT-1"
    assert ts.doc_work_ids == ["FEAT-1"]


def test_classify_task_doc_work_done_unpushed_when_trailer_but_unpushed():
    commit = ss.Commit(
        sha="abc", subject="feat: x",
        author_date=datetime(2026, 5, 25, tzinfo=timezone.utc),
        doc_work_ids=["FEAT-1"], subject_task_id=None,
    )
    ts = ss._classify_task(
        task_id="FEAT-1", lock=_lock(), worktree=_wt(), branch="feat/feat-1",
        index_entry={"status": "in_progress"}, commits=[commit],
        unpushed=2, dirty=False, stale_days=7, phase40_cutoff=_CUTOFF,
    )
    assert ts.state == "doc-work done, unpushed"
    assert "2 unpushed" in ts.next_action


def test_classify_task_in_progress_when_commits_but_no_trailer():
    """Post-cutoff commits without a Doc-Work trailer → still in progress."""
    commit = ss.Commit(
        sha="abc", subject="feat: x",
        author_date=datetime(2026, 5, 25, tzinfo=timezone.utc),
        doc_work_ids=[], subject_task_id=None,
    )
    ts = ss._classify_task(
        task_id="FEAT-1", lock=_lock(), worktree=_wt(), branch="feat/feat-1",
        index_entry={"status": "in_progress"}, commits=[commit],
        unpushed=1, dirty=True, stale_days=7, phase40_cutoff=_CUTOFF,
    )
    assert ts.state == "in progress"
    assert any("uncommitted" in n for n in ts.notes)


def test_classify_task_phase40_fallback_marks_with_tilde():
    """Pre-cutoff subject-match commit → ready-for-/review-close with `~` marker."""
    commit = ss.Commit(
        sha="abc", subject="feat: do thing (FEAT-1)",
        author_date=datetime(2026, 5, 1, tzinfo=timezone.utc),  # before cutoff
        doc_work_ids=[], subject_task_id="FEAT-1",
    )
    ts = ss._classify_task(
        task_id="FEAT-1", lock=_lock(), worktree=_wt(), branch="feat/feat-1",
        index_entry={"status": "in_progress"}, commits=[commit],
        unpushed=0, dirty=False, stale_days=7, phase40_cutoff=_CUTOFF,
    )
    assert ts.state == "ready for /review-close"
    assert ts.state_marker == "~"
    assert any("pre-Phase-40" in n for n in ts.notes)


def test_classify_task_stale_when_lock_old_and_no_commits():
    """Lock older than stale_days + no commits → state=stale."""
    old_started = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    ts = ss._classify_task(
        task_id="FEAT-1",
        lock=_lock(started=old_started),
        worktree=_wt(),
        branch="feat/feat-1",
        index_entry={"status": "in_progress"},
        commits=[],
        unpushed=0,
        dirty=False,
        stale_days=7,
        phase40_cutoff=_CUTOFF,
    )
    assert ts.state == "stale"
    assert "investigate" in ts.next_action


def test_classify_task_branchless_claim():
    """Lock present but no branch yet → claimed, no branch."""
    ts = ss._classify_task(
        task_id="FEAT-1", lock=_lock(), worktree=None, branch="",
        index_entry={"status": "in_progress"}, commits=[],
        unpushed=0, dirty=False, stale_days=7, phase40_cutoff=_CUTOFF,
    )
    assert ts.state == "claimed, no branch"
    assert ts.has_lock is True


# === _recommended_next: P7 roadmap-depth routing (Phase 73) =================


def _survey(open_ids=None, tasks=None, review_batches=None):
    """Minimal Survey for exercising _recommended_next. `review_batches` was
    added in Phase 105 so the P2/P4 batch priorities (unreachable while it was
    hardcoded `[]`) can be exercised; existing P7/P8 callers pass only open IDs."""
    return ss.Survey(
        timestamp=datetime(2026, 7, 6, tzinfo=timezone.utc),
        main_root=Path("/tmp/repo"),
        head_short="abc1234",
        tasks=tasks or [],
        review_batches=review_batches or [],
        discrepancies=[],
        stale_days=7,
        open_roadmap_ids=list(open_ids or []),
    )


def test_p7_deep_queue_recommends_roadmap():
    """> one /auto-build batch of open tasks → /roadmap (strategize first)."""
    rec = ss._recommended_next(_survey(["FEAT-1", "FEAT-2", "FEAT-3", "FEAT-4", "FEAT-5"]))
    assert rec is not None
    assert rec.command == "/roadmap"
    # read-only strategy view — no fan-out, so no /clear nudge (unlike /auto-build)
    assert rec.clear_nudge is False
    assert "5 open roadmap" in rec.reason
    assert rec.detail_lines == ["open: FEAT-1, FEAT-2, FEAT-3, +2 more"]


def test_p7_shallow_queue_recommends_auto_build():
    """1–4 open tasks (fits one batch) → /auto-build, with the /clear nudge."""
    rec = ss._recommended_next(_survey(["FEAT-1", "FEAT-2", "FEAT-3", "FEAT-4"]))
    assert rec is not None
    assert rec.command == "/auto-build"
    assert rec.clear_nudge is True
    assert rec.detail_lines == ["open: FEAT-1, FEAT-2, FEAT-3, +1 more"]


def test_p7_boundary_exactly_one_batch_is_auto_build():
    """Exactly _AUTO_BUILD_MAX_BATCH tasks still fits one batch → /auto-build."""
    ids = [f"FEAT-{i}" for i in range(ss._AUTO_BUILD_MAX_BATCH)]
    assert ss._recommended_next(_survey(ids)).command == "/auto-build"


def test_p7_boundary_one_over_batch_is_roadmap():
    """One more than a batch tips into strategize-first → /roadmap."""
    ids = [f"FEAT-{i}" for i in range(ss._AUTO_BUILD_MAX_BATCH + 1)]
    assert ss._recommended_next(_survey(ids)).command == "/roadmap"


def test_p7_single_open_task_is_auto_build():
    """A single claimable task routes straight to /auto-build."""
    rec = ss._recommended_next(_survey(["FEAT-1"]))
    assert rec.command == "/auto-build"
    assert rec.detail_lines == ["open: FEAT-1"]


def test_p8_idle_returns_none():
    """No active work and no open roadmap tasks → None (idle)."""
    assert ss._recommended_next(_survey([])) is None


def test_p7_does_not_fire_when_active_work_exists():
    """An in-progress task (P5) wins over a deep roadmap — P7 only fires when
    nothing is active, so /roadmap routing can never mask live work."""
    commit = ss.Commit(
        sha="abc", subject="feat: x",
        author_date=datetime(2026, 5, 25, tzinfo=timezone.utc),
        doc_work_ids=[], subject_task_id=None,
    )
    in_progress = ss._classify_task(
        task_id="FEAT-1", lock=_lock(), worktree=_wt(), branch="feat/feat-1",
        index_entry={"status": "in_progress"}, commits=[commit],
        unpushed=1, dirty=True, stale_days=7, phase40_cutoff=_CUTOFF,
    )
    deep = ["FEAT-2", "FEAT-3", "FEAT-4", "FEAT-5", "FEAT-6", "FEAT-7"]
    rec = ss._recommended_next(_survey(deep, tasks=[in_progress]))
    assert rec is not None
    assert rec.command.startswith("continue work on FEAT-1")


# === _recommended_next: P1–P4, P6 + cascade precedence (Phase 105) ==========
#
# The `_survey` helper hardcoded `review_batches=[]` and existing tests only
# crafted P5/P7/P8 inputs, so five of the eight cold-resume routing priorities
# (P1–P4, P6) and the whole first-match-wins cascade were unreachable. These
# build tasks/batches directly and assert both the per-priority routing and the
# precedence between adjacent priorities. `_recommended_next` is a pure function
# over dataclasses — no mocking.


def _task(task_id, state, **kw):
    return ss.TaskState(task_id=task_id, state=state, **kw)


def _batch(**overrides):
    """A ReviewBatchState with sane defaults (12 required fields, only `notes`
    defaulted on the dataclass)."""
    defaults = dict(
        batch_number=1, title="Batch 1", md_status="Pending",
        branch="review/batch-1", has_lock=False, has_branch=False,
        has_flag=False, flag_reason="", total_tasks=1, doc_worked_tasks=0,
        state="pending (not claimed)", next_action="",
    )
    defaults.update(overrides)
    return ss.ReviewBatchState(**defaults)


def test_p1_ready_task_routes_review_close():
    rec = ss._recommended_next(_survey(tasks=[_task("FEAT-1", "ready for /review-close")]))
    assert rec.command == "/review-close FEAT-1"


def test_p1_multiple_ready_tasks_note_more_queued():
    rec = ss._recommended_next(_survey(tasks=[
        _task("FEAT-1", "ready for /review-close"),
        _task("FEAT-2", "ready for /review-close"),
    ]))
    assert rec.command == "/review-close FEAT-1"
    assert "(1 more queued)" in rec.reason


def test_p2_ready_batch_routes_review_close():
    rec = ss._recommended_next(_survey(review_batches=[
        _batch(batch_number=3, total_tasks=5, state="ready for /review-close"),
    ]))
    assert rec.command == "/review-close (batch 3)"
    assert "all 5 tasks" in rec.reason


def test_p3_unpushed_task_routes_review_close():
    rec = ss._recommended_next(_survey(tasks=[_task("FEAT-2", "doc-work done, unpushed")]))
    assert rec.command == "/review-close FEAT-2"
    assert "unpushed" in rec.reason


def test_p4_untagged_pending_batch_routes_triage():
    rec = ss._recommended_next(_survey(review_batches=[
        _batch(batch_number=2, state="pending (not claimed)", has_flag=False),
    ]))
    assert rec.command == "/triage"
    assert rec.detail_lines == ["untriaged: batch 2"]


def test_p4_all_flagged_pending_batches_route_auto_judge():
    rec = ss._recommended_next(_survey(review_batches=[
        _batch(state="pending (not claimed)", has_flag=True, flag_reason="needs judgment"),
    ]))
    assert rec.command == "/auto-judge"
    assert rec.clear_nudge is True


def test_p6_planning_task_routes_resume_planning():
    rec = ss._recommended_next(_survey(tasks=[_task("FEAT-9", "planning")]))
    assert rec.command == "resume planning for FEAT-9"


# ── cascade precedence (first match wins) ──

def test_p1_task_wins_over_p2_batch():
    rec = ss._recommended_next(_survey(
        tasks=[_task("FEAT-1", "ready for /review-close")],
        review_batches=[_batch(batch_number=3, state="ready for /review-close")],
    ))
    assert rec.command == "/review-close FEAT-1"  # task form, not "(batch 3)"


def test_p2_batch_wins_over_p3_unpushed():
    rec = ss._recommended_next(_survey(
        tasks=[_task("FEAT-2", "doc-work done, unpushed")],
        review_batches=[_batch(batch_number=3, state="ready for /review-close")],
    ))
    assert rec.command == "/review-close (batch 3)"


def test_p4_pending_batch_wins_over_p5_in_progress():
    rec = ss._recommended_next(_survey(
        tasks=[_task("FEAT-5", "in progress")],
        review_batches=[_batch(state="pending (not claimed)", has_flag=False)],
    ))
    assert rec.command == "/triage"


def test_p5_in_progress_wins_over_p6_planning():
    rec = ss._recommended_next(_survey(tasks=[
        _task("FEAT-5", "in progress"),
        _task("FEAT-9", "planning"),
    ]))
    assert rec.command.startswith("continue work on FEAT-5")


def test_p6_planning_wins_over_p7_roadmap():
    rec = ss._recommended_next(_survey(
        ["A", "B", "C", "D", "E"],  # deep roadmap that would otherwise fire P7
        tasks=[_task("FEAT-9", "planning")],
    ))
    assert rec.command == "resume planning for FEAT-9"


# === _find_discrepancies (Phase 82) ========================================
#
# One subprocess boundary: `_git(["branch", "--list", ...])`. Everything else
# is pure logic over Lock/Worktree/index plus a real `Path.is_dir()` for the
# stale-lock check, so only `_git` is mocked and workspace existence is driven
# with real `tmp_path` dirs.


def _dlock(task_id, branch="", workspace="", path=None):
    return ss.Lock(
        task_id=task_id,
        path=path or Path(f".locks/{task_id}.lock"),
        status="active",
        branch=branch,
        workspace=workspace,
    )


def _dwt(branch, path="/tmp/wt", is_main=False):
    return ss.Worktree(path=Path(path), branch=branch, head="abc", is_main=is_main)


def _run_discrepancies(
    *,
    locks=(),
    worktrees=(),
    index=None,
    branches=(),
    main_root=Path("/tmp/repo"),
):
    """Invoke `_find_discrepancies` with the branch-list `_git` shell-out mocked
    to return `branches`. Phase 85 dropped the previously-dead `classified` /
    `stale_days` params from the signature (they only fed an unread `by_id`);
    this helper no longer forwards them."""

    def fake_git(args, cwd=None, check=False):
        if args[:2] == ["branch", "--list"]:
            return "\n".join(branches)
        return ""

    with mock.patch.object(ss, "_git", side_effect=fake_git):
        return ss._find_discrepancies(
            list(locks), list(worktrees), index or {}, main_root
        )


def test_discrepancy_stale_lock_when_workspace_missing(tmp_path):
    gone = tmp_path / "gone"  # never created
    ds = _run_discrepancies(locks=[_dlock("FEAT-1", workspace=str(gone))])
    assert len(ds) == 1
    assert ds[0].kind == "stale lock"
    assert "FEAT-1" in ds[0].detail
    assert str(gone) in ds[0].detail


def test_discrepancy_no_stale_lock_when_workspace_exists_or_empty(tmp_path):
    """An existing workspace is healthy; an empty `workspace:` field is skipped
    outright (the `if not l.workspace: continue` guard)."""
    ds = _run_discrepancies(
        locks=[
            _dlock("FEAT-1", workspace=str(tmp_path)),  # exists
            _dlock("FEAT-2", workspace=""),  # unset → skipped
        ]
    )
    assert ds == []


def test_discrepancy_orphan_worktree_no_lock_no_index():
    """A non-main worktree whose branch resolves to no lock and no index entry."""
    ds = _run_discrepancies(
        worktrees=[_dwt("feat/9999-orphan", path="/tmp/orphan")],
        branches=["feat/9999-orphan"],  # in a worktree → orphan-branch loop skips it
    )
    assert len(ds) == 1
    assert ds[0].kind == "orphan worktree"
    assert "feat/9999-orphan" in ds[0].detail


def test_discrepancy_worktree_index_drift_when_in_index_without_lock():
    """Worktree branch resolves to a known index task but no lock backs it.
    Isolated with a non-`in_progress` status so the later index-scan loop
    (which only fires on `in_progress`) does not also emit."""
    ds = _run_discrepancies(
        worktrees=[_dwt("feat/feat-5")],
        index={"FEAT-5": {"branch": "feat/feat-5", "status": "open"}},
        branches=["feat/feat-5"],
    )
    assert len(ds) == 1
    assert ds[0].kind == "index drift (in_progress without lock)"
    assert "FEAT-5" in ds[0].detail
    assert "/tmp/wt" in ds[0].detail  # worktree-path detail, not the index-scan detail


def test_discrepancy_worktree_and_branch_with_matching_lock_are_clean():
    """A worktree + branch both backed by a lock on the same branch produce
    nothing: covers the worktree-loop `l.branch == w.branch` skip and the
    orphan-branch-loop `wt_branches` skip (the branch-list `b in wt_branches`
    short-circuits before the lock check — that path is tested separately)."""
    ds = _run_discrepancies(
        locks=[_dlock("FEAT-1", branch="feat/feat-1")],  # empty workspace → no stale
        worktrees=[_dwt("feat/feat-1")],
        branches=["feat/feat-1"],
    )
    assert ds == []


def test_discrepancy_orphan_branch_no_lock_no_worktree_no_index():
    ds = _run_discrepancies(branches=["tech/tech-orphan"])
    assert len(ds) == 1
    assert ds[0].kind == "orphan branch"
    assert "tech/tech-orphan" in ds[0].detail


def test_discrepancy_orphan_branch_skips_non_task_shaped_and_indexed():
    """`main` / `release/*` are not task-shaped; a task-shaped branch that
    resolves into the index is not orphaned."""
    ds = _run_discrepancies(
        branches=["main", "release/1.0", "feat/feat-1"],
        index={"FEAT-1": {"status": "done"}},  # not in_progress → no index-scan drift
    )
    assert ds == []


def test_discrepancy_orphan_branch_skips_when_branch_has_lock():
    """A task-shaped branch NOT in any worktree but backed by a lock is not
    orphaned — the orphan-branch-loop `l.branch == b` skip (line 662), distinct
    from the earlier `b in wt_branches` short-circuit."""
    ds = _run_discrepancies(
        branches=["tech/tech-1"],
        locks=[_dlock("TECH-1", branch="tech/tech-1")],  # empty workspace → no stale
    )
    assert ds == []


def test_discrepancy_index_scan_drift_in_progress_without_lock():
    """`index.yml` status=in_progress with no lock drifts; the same status *with*
    a lock does not (folded negative via FEAT-10)."""
    ds = _run_discrepancies(
        locks=[_dlock("FEAT-10")],  # empty workspace/branch → only affects lock_ids
        index={
            "FEAT-9": {"status": "in_progress"},  # no lock → drift
            "FEAT-10": {"status": "in_progress"},  # locked → clean
        },
    )
    assert len(ds) == 1
    assert ds[0].kind == "index drift (in_progress without lock)"
    assert "FEAT-9" in ds[0].detail
    assert "tasks/index.yml" in ds[0].detail
    assert "FEAT-10" not in ds[0].detail


def test_discrepancy_empty_inputs_returns_empty():
    assert _run_discrepancies() == []


# === _classify_review_batches (Phase 82) ===================================
#
# Two boundaries: `_git(["rev-parse", "--verify", ...])` for branch existence
# and `_commits_ahead_of_main` for the Doc-Work trailer tally. Both mocked;
# `branch_exists` drives the rev-parse path, `commits_by_branch` the trailers.


def _dbatch(number=1, title="T", status="In Progress", branch="review/x",
            flag_reason="", task_ids=()):
    return {
        "number": number,
        "title": title,
        "status": status,
        "branch": branch,
        "flag_reason": flag_reason,
        "tasks": [{"id": tid, "checkbox": " "} for tid in task_ids],
    }


def _dw_commit(doc_work_ids):
    return ss.Commit(
        sha="abc",
        subject="x",
        author_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        doc_work_ids=list(doc_work_ids),
        subject_task_id=None,
    )


def _run_batches(
    batches,
    *,
    locks=(),
    worktrees=(),
    branch_exists=False,
    commits_by_branch=None,
    main_root=Path("/tmp/repo"),
):
    cbb = commits_by_branch or {}

    def fake_git(args, cwd=None, check=False):
        if args[:2] == ["rev-parse", "--verify"]:
            return "deadbeef" if branch_exists else ""
        return ""

    def fake_commits(branch, root):
        return cbb.get(branch, [])

    with mock.patch.object(ss, "_git", side_effect=fake_git), mock.patch.object(
        ss, "_commits_ahead_of_main", side_effect=fake_commits
    ):
        return ss._classify_review_batches(
            list(batches), list(locks), list(worktrees), main_root
        )


def test_batch_skips_terminal_status():
    """Anything not Pending / In Progress is filtered out entirely."""
    out = _run_batches([_dbatch(status="Done"), _dbatch(number=2, status="Blocked")])
    assert out == []


def test_batch_pending_flagged_routes_to_auto_judge():
    out = _run_batches(
        [_dbatch(status="Pending", branch="review/p", flag_reason="unsafe shell usage")]
    )
    assert len(out) == 1
    b = out[0]
    assert b.state == "pending (not claimed)"
    assert b.has_flag is True
    assert "/auto-judge will pick this up" in b.next_action
    assert "unsafe shell usage" in b.next_action


def test_batch_pending_unflagged_routes_to_triage():
    out = _run_batches([_dbatch(status="Pending", branch="review/p", flag_reason="")])
    assert out[0].state == "pending (not claimed)"
    assert out[0].has_flag is False
    assert "/triage will classify" in out[0].next_action


def test_batch_pending_flag_reason_truncated_at_55():
    long = _run_batches(
        [_dbatch(status="Pending", branch="review/l", flag_reason="y" * 60)]
    )[0]
    assert long.next_action.endswith("…")
    assert "y" * 56 not in long.next_action  # cut at 55, not 56

    exact = _run_batches(
        [_dbatch(status="Pending", branch="review/e", flag_reason="x" * 55)]
    )[0]
    assert not exact.next_action.endswith("…")  # exactly 55 → no ellipsis

    # rstrip: when char 55 is whitespace the ellipsis must not be space-prefixed
    ws = _run_batches(
        [_dbatch(status="Pending", branch="review/w",
                 flag_reason="z" * 54 + " " + "z" * 10)]
    )[0]
    assert ("z" * 54 + "…") in ws.next_action
    assert " …" not in ws.next_action


def test_batch_pending_but_claimed_falls_through_has_lock():
    """A Pending batch already backed by a lock is NOT 'pending (not claimed)':
    has_lock=True skips the pending branch and falls through to the branch/commit
    states (here: no branch yet → claimed, no branch)."""
    out = _run_batches(
        [_dbatch(status="Pending", branch="review/cl", task_ids=["TASK-1"])],
        locks=[_dlock("REV", branch="review/cl")],
        branch_exists=False,
    )
    assert out[0].has_lock is True
    assert out[0].state != "pending (not claimed)"
    assert out[0].state == "claimed, no branch"


def test_batch_claimed_no_branch():
    """In Progress but the branch was never created (no worktree, rev-parse miss)."""
    out = _run_batches(
        [_dbatch(status="In Progress", branch="review/nb", task_ids=["TASK-1"])],
        branch_exists=False,
    )
    assert out[0].state == "claimed, no branch"
    assert out[0].has_branch is False
    assert "not created" in out[0].next_action


def test_batch_empty_when_branch_exists_but_no_tasks():
    out = _run_batches(
        [_dbatch(status="In Progress", branch="review/em", task_ids=[])],
        branch_exists=True,
    )
    assert out[0].state == "empty batch"
    assert out[0].total_tasks == 0


def test_batch_ready_for_review_close_via_worktree_membership():
    """has_branch satisfied by worktree membership (not rev-parse); every task
    carries a Doc-Work trailer → ready."""
    out = _run_batches(
        [_dbatch(branch="review/rc", task_ids=["TASK-1", "TASK-2"])],
        worktrees=[_dwt("review/rc")],
        commits_by_branch={"review/rc": [_dw_commit(["TASK-1", "TASK-2"])]},
    )
    b = out[0]
    assert b.has_branch is True
    assert b.state == "ready for /review-close"
    assert b.doc_worked_tasks == 2
    assert b.next_action == "/review-close (batch 1)"


def test_batch_in_progress_partial_trailers():
    """`done` counts only trailers for tasks *in this batch*. The commit carries a
    stray `TASK-99` trailer absent from the batch — if `done` counted every
    branch trailer instead of the `batch_task_ids & all_dw_ids` intersection it
    would read 2, flip to `done == total`, and report 'ready' instead."""
    out = _run_batches(
        [_dbatch(branch="review/pp", task_ids=["TASK-1", "TASK-2"])],
        worktrees=[_dwt("review/pp")],
        commits_by_branch={"review/pp": [_dw_commit(["TASK-1", "TASK-99"])]},
    )
    b = out[0]
    assert b.state == "in progress"
    assert b.doc_worked_tasks == 1  # not 2 — TASK-99 is filtered out
    assert "1 of 2" in b.next_action


def test_batch_in_progress_zero_trailers_via_rev_parse_branch():
    """has_branch satisfied by the rev-parse fallback (branch exists but is not a
    worktree); no task has a trailer yet → the 0-of-N message."""
    out = _run_batches(
        [_dbatch(branch="review/zt", task_ids=["TASK-1", "TASK-2"])],
        branch_exists=True,
        commits_by_branch={"review/zt": [_dw_commit([])]},
    )
    b = out[0]
    assert b.has_branch is True
    assert b.state == "in progress"
    assert b.doc_worked_tasks == 0
    assert "0 of 2" in b.next_action
