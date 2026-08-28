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

import re
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
    locks_dir = tmp_path / "sysop/runtime/locks"
    locks_dir.mkdir(parents=True)
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
    locks_dir = tmp_path / "sysop/runtime/locks"
    locks_dir.mkdir(parents=True)
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
        task_id=task_id, path=Path(f"sysop/runtime/locks/{task_id}.lock"),
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
    # Assert the PROPERTY, not a phrase: a task with a claim but no commits routes the
    # operator back into /claim-task's build pipeline. The previous form accepted either
    # the literal "continue planning" or "reviewer-executor" — the latter naming a shape
    # retired when /claim-task became an orchestrator, so half this assertion had become a
    # dead referent that could never fire again.
    action = ts.next_action.lower()
    assert "/claim-task" in action, f"next_action must route to the claim skill: {ts.next_action!r}"
    assert ts.task_id.lower() in action, f"next_action must name the task: {ts.next_action!r}"
    assert "reviewer-executor" not in action, (
        "next_action names a shape that no longer exists — /claim-task spawns a planner, "
        "an independent reviewer and an executor as separate agents."
    )


def test_classify_task_ready_for_review_close_with_doc_work_trailer():
    """`pending_doc` is now REQUIRED for this state (Q-019, Phase 220).

    Both this test and its unpushed twin below used to pass with the trailer
    alone, which is precisely the defect: `/claim-task` Step 7e's executor emits
    `Doc-Work:` too, so trailer-alone stopped meaning "documentation exists".
    They were asserting the bug. The trailer-without-pending-doc case they used
    to cover by accident is now covered on purpose, two tests down."""
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
        pending_doc=Path("sysop/runtime/pending-docs/feat-feat-1.md"),
    )
    assert ts.state == "ready for /review-close"
    assert ts.next_action == "/review-close FEAT-1"
    assert ts.doc_work_ids == ["FEAT-1"]
    assert ts.pending_doc is True


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
        pending_doc=Path("sysop/runtime/pending-docs/feat-feat-1.md"),
    )
    assert ts.state == "doc-work done, unpushed"
    assert "2 unpushed" in ts.next_action
    assert ts.pending_doc is True


def test_classify_task_code_committed_docs_pending_when_no_pending_doc():
    """`Q-019`: trailer present, pending-doc absent — the normal terminal state
    of `/claim-task`'s build pipeline, and the state that used to be reported as
    "ready for /review-close".

    Routing it to `/review-close` skipped Step 1b's simplify pass, Step 3 (which
    produces the pending-doc Step 4c consolidates and Step 3c reads for
    manual-smoke signals — so the close arrived with no pending-doc at all), and
    Step 3b's HARD-FAIL follow-up-stub check. `/claim-task`'s own final report
    already said "Run `/document-work` next"; the two surfaces contradicted each
    other in exactly this state."""
    commit = ss.Commit(
        sha="abc", subject="feat: do thing",
        author_date=datetime(2026, 5, 25, tzinfo=timezone.utc),
        doc_work_ids=["FEAT-1"], subject_task_id=None,
    )
    ts = ss._classify_task(
        task_id="FEAT-1", lock=_lock(), worktree=_wt(), branch="feat/feat-1",
        index_entry={"status": "in_progress"}, commits=[commit],
        unpushed=0, dirty=False, stale_days=7, phase40_cutoff=_CUTOFF,
        pending_doc=None,
    )
    assert ts.state == "code committed, docs pending"
    assert ts.next_action == "/document-work FEAT-1"
    assert ts.pending_doc is False
    # The trailer is still reported — this is not a claim that it is absent.
    assert ts.doc_work_ids == ["FEAT-1"]


def test_the_docs_pending_state_is_routed_by_the_recommendation_cascade():
    """A state with no routing arm is worse than no state: the survey would know
    the answer and not say it.

    `code committed, docs pending` is not "in progress" (P5 requires the ABSENCE
    of a trailer) and not "ready for /review-close" (P1/P3 now require a
    pending-doc), so without its own arm it falls through every tier to P7 and
    the operator is told to pick up NEW roadmap work while a finished build waits
    to be documented. Asserts the routing, not the state label."""
    commit = ss.Commit(
        sha="abc", subject="feat: do thing",
        author_date=datetime(2026, 5, 25, tzinfo=timezone.utc),
        doc_work_ids=["FEAT-1"], subject_task_id=None,
    )
    ts = ss._classify_task(
        task_id="FEAT-1", lock=_lock(), worktree=_wt(), branch="feat/feat-1",
        index_entry={"status": "in_progress"}, commits=[commit],
        unpushed=0, dirty=False, stale_days=7, phase40_cutoff=_CUTOFF,
        pending_doc=None,
    )
    survey = ss.Survey(
        timestamp=datetime(2026, 8, 21, tzinfo=timezone.utc),
        main_root=Path("/tmp/repo"),
        head_short="abc1234",
        tasks=[ts],
        review_batches=[],
        discrepancies=[],
        stale_days=7,
        # A non-empty roadmap is the point: without its own arm the docs-pending
        # state falls through to P7 and this recommends picking up FEAT-9.
        open_roadmap_ids=["FEAT-9"],
    )
    rec = ss._recommended_next(survey)
    assert rec is not None
    assert rec.command == "/document-work FEAT-1", (
        f"routed to {rec.command!r} — the docs-pending arm did not fire"
    )


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


def test_p4_untriaged_pending_batch_routes_triage():
    rec = ss._recommended_next(_survey(review_batches=[
        _batch(batch_number=2, state="pending (not claimed)", has_flag=False),
    ]))
    assert rec.command == "/triage"
    assert rec.detail_lines == ["untriaged: batch 2"]


def test_p4_all_flagged_pending_batches_route_auto_judge():
    rec = ss._recommended_next(_survey(review_batches=[
        _batch(state="pending (not claimed)", has_flag=True, flag_reason="needs judgment",
               has_triage_record=True, triaged_verdict="flag"),
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
        path=path or Path(f"sysop/runtime/locks/{task_id}.lock"),
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
            flag_reason="", task_ids=(), triaged_verdict="", triaged_date="",
            triaged_tasks=()):
    """Phase 181 added the `Triaged:` record. Callers that pass only
    `flag_reason` are modelling a *legacy* batch — a `Flag:` tag with no
    verdict behind it — which now routes to /triage rather than /auto-judge.
    Pass `triaged_verdict` to model a batch a shipped /triage run classified."""
    return {
        "number": number,
        "title": title,
        "status": status,
        "branch": branch,
        "flag_reason": flag_reason,
        "triaged_date": triaged_date or ("2026-08-03" if triaged_verdict else ""),
        "triaged_verdict": triaged_verdict,
        "triaged_tasks": list(triaged_tasks),
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
    out = _run_batches([_dbatch(
        status="Pending", branch="review/p", flag_reason="unsafe shell usage",
        triaged_verdict="flag",
    )])
    assert len(out) == 1
    b = out[0]
    assert b.state == "pending (not claimed)"
    assert b.has_flag is True
    assert "/auto-judge will pick this up" in b.next_action
    assert "unsafe shell usage" in b.next_action


def test_batch_pending_unstamped_flag_routes_to_triage():
    """Phase 181. A `Flag:` tag with no `Triaged:` record is a tag of unknown
    provenance, not a prior verdict — before this, its mere presence sent the
    batch to /auto-judge unread."""
    out = _run_batches([_dbatch(
        status="Pending", branch="review/p", flag_reason="looks judgy",
    )])
    assert out[0].has_flag is True
    assert "/triage will classify" in out[0].next_action
    assert "provenance unknown" in out[0].next_action


def test_batch_pending_unflagged_routes_to_triage():
    out = _run_batches([_dbatch(status="Pending", branch="review/p", flag_reason="")])
    assert out[0].state == "pending (not claimed)"
    assert out[0].has_flag is False
    assert "/triage will classify" in out[0].next_action


def test_batch_pending_triaged_auto_routes_to_auto_fix():
    """The verdict now has a durable home, so an all-auto batch stops reading
    as never-classified."""
    out = _run_batches([_dbatch(
        status="Pending", branch="review/p", triaged_verdict="auto",
    )])
    assert out[0].has_flag is False
    assert "/auto-fix will pick this up" in out[0].next_action


def test_batch_pending_flag_reason_truncated_at_55():
    long = _run_batches([_dbatch(
        status="Pending", branch="review/l", flag_reason="y" * 60,
        triaged_verdict="flag",
    )])[0]
    assert long.next_action.endswith("…")
    assert "y" * 56 not in long.next_action  # cut at 55, not 56

    exact = _run_batches([_dbatch(
        status="Pending", branch="review/e", flag_reason="x" * 55,
        triaged_verdict="flag",
    )])[0]
    assert not exact.next_action.endswith("…")  # exactly 55 → no ellipsis

    # rstrip: when char 55 is whitespace the ellipsis must not be space-prefixed
    ws = _run_batches([_dbatch(
        status="Pending", branch="review/w",
        flag_reason="z" * 54 + " " + "z" * 10,
        triaged_verdict="flag",
    )])[0]
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


# ── Q-019: the pending-doc workspace resolver ──────────────────────────
#
# Every test below was added because this phase's own mutation battery walked
# through the ones above it: the classification tests pass `pending_doc=None` or
# a bare Path, so they never exercise the RESOLVER that computes it.

def _pd_repo(tmp_path, branch="feat/feat-1"):
    root = tmp_path / "main"
    (root / "sysop" / "runtime" / "locks").mkdir(parents=True)
    return root


def _write_pending_doc(base: Path, branch: str) -> Path:
    d = base / "sysop" / "runtime" / "pending-docs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{branch.replace('/', '-')}.md"
    p.write_text("---\nbranch: x\n---\nbody\n")
    return p


def test_pending_doc_is_found_via_the_locks_recorded_workspace(tmp_path):
    """Battery gap D37. Arm (ii) exists because `claim_task.sh --clone`
    produces a workspace `git worktree list` never lists, so the lock's
    `workspace:` is the only record of where it is.

    The doc is placed ONLY there — not in the main checkout, not in a worktree —
    so removing arm (ii) makes it unfindable."""
    main = tmp_path / "main"
    main.mkdir()
    clone = tmp_path / "elsewhere-FEAT-1"
    clone.mkdir()
    _write_pending_doc(clone, "feat/feat-1")

    lock = ss.Lock(task_id="FEAT-1", path=main / "x.lock",
                   branch="feat/feat-1", workspace=str(clone))
    found = ss._pending_doc_for(main, "feat/feat-1", lock, None)
    assert found is not None, "arm (ii) did not resolve the clone workspace"
    # .../<clone>/sysop/runtime/pending-docs/<file>.md — four levels up.
    assert found.parents[3] == clone


def test_pending_doc_is_found_via_the_conventional_sibling_directory(tmp_path):
    """Arm (iii), and **the directory name is lower-cased**, which is the round's
    correction.

    `claim_task.sh` builds `../<prefix>-<task id LOWER-CASED>`, so the first
    version's `<repo>-<TASK_ID>` could never match on a case-sensitive
    filesystem. The fixture uses the real spelling (`main-feat-1`), so a
    regression to the verbatim id fails here rather than only on Linux.

    The arm's real job is a lock whose `workspace:` is blank or damaged — NOT
    "a claim with no lock", which was the first version's stated reason and is
    unreachable: the only caller iterates `for lock in locks`."""
    main = tmp_path / "main"
    main.mkdir()
    sibling = tmp_path / "main-feat-1"          # lower-cased, as claim_task.sh writes it
    sibling.mkdir()
    _write_pending_doc(sibling, "feat/feat-1")

    lock = ss.Lock(task_id="FEAT-1", path=main / "x.lock",
                   branch="feat/feat-1", workspace="")
    assert ss._pending_doc_for(main, "feat/feat-1", lock, None) is not None
    # **Assert the spelling the RESOLVER produced, not the filesystem.** On
    # macOS/APFS `main-FEAT-1` resolves to the lower-cased directory, so both an
    # `.exists()` check and a directory listing pass whichever spelling the code
    # computes — which is exactly why the un-lowered version survived this
    # phase's battery. The returned path keeps the spelling it was built from.
    found = ss._pending_doc_for(main, "feat/feat-1", lock, None)
    assert found is not None
    assert found.parents[3].name == "main-feat-1", (
        f"arm (iii) built {found.parents[3].name!r}; claim_task.sh lower-cases "
        f"the task id, so anything else matches nothing on Linux"
    )


def test_pending_doc_filename_sanitises_the_branch_slash(tmp_path):
    """Battery gap D38. `/document-work` Step 3 writes
    `<branch with / replaced by ->.md`. Reading the raw branch name looks for a
    file in a directory that does not exist, and returns None for every branch
    with a slash — which is every branch the workflow creates."""
    main = tmp_path / "main"
    main.mkdir()
    _write_pending_doc(main, "feat/feat-1")

    assert ss._pending_doc_for(main, "feat/feat-1", None, None) is not None
    # Non-vacuity: the un-sanitised name must NOT exist on disk, or this
    # assertion would pass either way.
    assert not (main / "sysop/runtime/pending-docs/feat/feat-1.md").exists()


def test_an_unusable_workspace_candidate_falls_through_to_the_next(tmp_path):
    """The resolver tries candidates in order and a bad one must not stop it.

    Written this way because the obvious version — assert it does not RAISE —
    proves nothing: `Path.is_file()` already swallows a NUL byte, an over-long
    path and a nonexistent parent (measured on this interpreter for all three),
    so an `except OSError` in the resolver would be unreachable and a test for
    it would pass against no handler at all. That mutation survived this phase's
    own battery, which is how the dead handler was found and removed. What is
    worth guarding is the fall-through itself."""
    main = tmp_path / "main"
    main.mkdir()
    _write_pending_doc(main, "feat/feat-1")      # only the LAST candidate has it

    lock = ss.Lock(task_id="FEAT-1", path=main / "x.lock", branch="feat/feat-1",
                   workspace="\x00not/a/valid/path")
    found = ss._pending_doc_for(main, "feat/feat-1", lock, None)
    assert found is not None, "a bad earlier candidate ended the search"
    assert found.parents[3] == main


def test_pending_doc_returns_none_with_no_branch(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    assert ss._pending_doc_for(main, "", None, None) is None


def test_pending_doc_returns_none_when_no_workspace_has_one(tmp_path):
    """The false-positive control: the resolver must not invent a doc."""
    main = tmp_path / "main"
    main.mkdir()
    assert ss._pending_doc_for(main, "feat/feat-1", None, None) is None


def test_every_state_the_classifier_emits_is_documented_in_the_skill():
    """Battery gap D40: the `/sitrep` skill's state table is what a consumer
    reads to interpret the output, and nothing tied it to the code. Phase 220
    added a state; a phase that adds the next one should not be able to ship it
    undocumented.

    Scoped at BOTH ends, and both scopings are load-bearing:

    * source side — only `_classify_task`, because `_classify_review_batches`
      emits its own vocabulary that this table does not describe (it belongs to
      `/roadmap`'s batch rows). A whole-file sweep demands the table document
      states it was never about.
    * doc side — only the state-table block, because a whole-file search passes
      on a mention in the prose two sections down, which is the "guard with a
      whole-file fallback is not a guard" shape.
    """
    root = Path(__file__).resolve().parents[1]
    src = (root / "core/companion/scripts/sitrep_survey.py").read_text()

    fn_start = src.index("def _classify_task(")
    fn_end = src.index("\ndef _phase40_fallback(", fn_start)
    body = src[fn_start:fn_end]

    emitted = set(re.findall(r'^\s+state = "([^"]+)"', body, re.MULTILINE))
    # `unknown` is the initialiser, not a classification — it is what remains if
    # no arm fires, and the table describes arms.
    emitted.discard("unknown")

    # **Phase 237: the extraction went blind and this is the repair, not a second
    # guard.** `_claim_stall` returns its state through a module constant, so
    # `_classify_task` assigns `state = stall_state` — an IDENTIFIER, which the
    # literal-only regex above cannot see. `parked` and `awaiting approval` were
    # therefore emitted, tabled, and unchecked: a guard that had silently stopped
    # covering two of the states it names. Adding a *second* states guard would
    # have been the Phase-204 shape (a roster reading as coverage); repairing the
    # one that exists is the same work with none of that.
    #
    # **Extract from the second EMITTER, not from a naming convention.** The
    # first cut of this repair required every `_<NAME>_STATE` module constant to
    # appear in the table, and a mutation renaming `_PARKED_STATE` to
    # `_PARKED_LABEL` walked straight through it: the state left the convention,
    # left the guard, and kept being emitted. So the source side is now
    # `_claim_stall`'s own `return` statements, with identifiers resolved through
    # module-level string constants whatever they are called. An identifier that
    # does not resolve fails loudly rather than dropping out.
    stall_start = src.index("def _claim_stall(")
    stall_end = src.index("\ndef _classify_task(", stall_start)
    stall_body = src[stall_start:stall_end]

    consts = dict(
        re.findall(r'^([A-Za-z_][A-Za-z0-9_]*) = "([^"]*)"$', src, re.MULTILINE)
    )
    returned = re.findall(
        r'return\s*\(?\s*\n?\s*([A-Za-z_][A-Za-z0-9_]*|"[^"]*")\s*,',
        stall_body,
    )
    assert returned, "no state-shaped returns found in _claim_stall"

    stall_states = set()
    for tok in returned:
        if tok.startswith('"'):
            stall_states.add(tok.strip('"'))
            continue
        assert tok in consts, (
            f"_claim_stall returns state `{tok}`, which is not a module-level "
            f"string constant — this guard cannot resolve it to a value, so the "
            f"state would escape the table check"
        )
        stall_states.add(consts[tok])
    # "" is the no-evidence arm: it leaves the caller's classification alone and
    # is not a state the table describes.
    stall_states.discard("")
    assert stall_states, "_claim_stall emits no states — the extraction moved"
    emitted |= stall_states

    # And pin the indirection itself. If a future arm assigns `state` from some
    # other local, this goes red rather than letting that state escape the table.
    indirect = set(re.findall(r"^\s+state = ([a-z_][a-z0-9_]*)\s*$", body, re.MULTILINE))
    assert indirect == {"stall_state"}, (
        f"unexpected identifier-fed `state =` assignments in _classify_task: "
        f"{sorted(indirect)}. Each one hides its state from this guard's literal "
        f"extraction — route it through _claim_stall, or extend this assert "
        f"deliberately."
    )

    # **Cross-check the extraction against a SECOND, independent count**, rather
    # than a floor. The first version asserted `>= 6` against a real count of 7,
    # so it tolerated the regex silently losing exactly one state — which the
    # round demonstrated by wrapping one assignment in parentheses. A floor set
    # below the truth is a vacuity check that permits the vacuity it guards.
    # A SECOND extraction, unanchored, compared as a SET. `ready for
    # /review-close` is assigned twice, so a count comparison is the wrong shape;
    # what must hold is that both methods see the same states.
    loose = set(re.findall(r'state = "([^"]+)"', body)) | stall_states
    loose.discard("unknown")
    assert emitted == loose, (
        f"the two extractions disagree — the anchored one is missing "
        f"{sorted(loose - emitted)}, so this guard is checking a subset"
    )
    assert len(emitted) >= 6, f"only {len(emitted)} states found at all"

    skill = (root / "core/skills/sitrep/SKILL.md").read_text()
    t_start = skill.index("| State | Deterministic signal |")
    t_end = skill.index("\n\n", t_start)
    table = skill[t_start:t_end].lower().replace("`", "")
    assert table.count("|") > 10, "state-table slice looks wrong"

    missing = sorted(s for s in emitted if s.lower() not in table)
    assert not missing, (
        "these states are emitted by sitrep_survey.py but absent from the "
        "/sitrep skill's state table:\n" + "\n".join(f"  {m}" for m in missing)
    )


def test_the_pending_doc_lookup_survives_a_raising_is_file(tmp_path, monkeypatch):
    """**The handler this phase deleted and its own round restored.**

    The deletion rested on a real measurement — `Path.is_file()` returns False
    for a NUL byte, an over-long path and a nonexistent parent — taken on **3.14
    only**. There `is_file()` delegates to `os.path.isfile()`, which swallows
    `(OSError, ValueError)` unconditionally. On **3.9-3.13** it goes through
    `Path.stat()` and re-raises any errno outside `_IGNORED_ERRNOS`, so an
    over-long path raises `OSError` ENAMETOOLONG. Measured: 3.9, 3.11 and 3.12
    raise; only 3.14 does not. README declares 3.9+, CI runs 3.9, and stock
    macOS 3.9 is what a consumer without a venv runs. `sitrep_survey.main()`
    catches only `KeyboardInterrupt`, so the escape takes all of `/sitrep` down.

    **Forced rather than provoked, deliberately.** A test that builds an
    over-long path passes on 3.14 for the wrong reason — the interpreter
    swallows it — so it would guard nothing on the developer's own machine and
    everything in CI. Monkeypatching `is_file` to raise tests the handler on
    every interpreter."""
    main = tmp_path / "main"
    main.mkdir()
    _write_pending_doc(main, "feat/feat-1")

    real_is_file = Path.is_file
    bad = str(tmp_path / "exploding")

    def fake_is_file(self, *a, **kw):
        if str(self).startswith(bad):
            raise OSError(63, "File name too long")
        return real_is_file(self, *a, **kw)

    monkeypatch.setattr(Path, "is_file", fake_is_file)

    lock = ss.Lock(task_id="FEAT-1", path=main / "x.lock",
                   branch="feat/feat-1", workspace=bad)
    found = ss._pending_doc_for(main, "feat/feat-1", lock, None)
    assert found is not None, "a raising candidate ended the search"
    assert found.parents[3] == main


def test_the_pending_doc_lookup_survives_a_valueerror_too(tmp_path, monkeypatch):
    """`os.path.isfile` swallows ValueError alongside OSError, and an embedded
    NUL raises ValueError rather than OSError on some interpreters. Catching
    only one of the two leaves the other live."""
    main = tmp_path / "main"
    main.mkdir()
    _write_pending_doc(main, "feat/feat-1")

    real_is_file = Path.is_file
    bad = str(tmp_path / "exploding")

    def fake_is_file(self, *a, **kw):
        if str(self).startswith(bad):
            raise ValueError("embedded null byte")
        return real_is_file(self, *a, **kw)

    monkeypatch.setattr(Path, "is_file", fake_is_file)

    lock = ss.Lock(task_id="FEAT-1", path=main / "x.lock",
                   branch="feat/feat-1", workspace=bad)
    assert ss._pending_doc_for(main, "feat/feat-1", lock, None) is not None


def _survey_with(tasks, *, roadmap=("FEAT-9",)):
    return ss.Survey(
        timestamp=datetime(2026, 8, 21, tzinfo=timezone.utc),
        main_root=Path("/tmp/repo"), head_short="abc1234",
        tasks=list(tasks), review_batches=[], discrepancies=[],
        stale_days=7, open_roadmap_ids=list(roadmap),
    )


def _p220_task(state, task_id="FEAT-1"):
    return ss.TaskState(task_id=task_id, state=state, branch=f"feat/{task_id.lower()}",
                        commits_ahead=1, pending_doc=(state != "code committed, docs pending"))


def test_the_docs_pending_state_appears_in_the_suggested_order():
    """**Round finding (HIGH): the new state was wired into 2 of 5 surfaces.**

    `_suggested_order` enumerates states by name and did not know this one, so
    the task fell out of the ordered list entirely and the "(no active Sysop
    work; pick up a new task with /next-task)" fallback fired — three lines
    below a RECOMMENDED NEXT that said `/document-work`. One report contradicting
    itself, which is the defect this phase exists to remove, applied to itself."""
    order = ss._suggested_order(_survey_with([_p220_task("code committed, docs pending")]))
    assert any("FEAT-1" in line for line in order), (
        f"the docs-pending task is absent from the suggested order: {order}"
    )
    assert any("/document-work" in line for line in order)


def test_the_suggested_order_puts_docs_pending_after_the_close_tiers():
    """The ordering claim, pinned rather than asserted in prose. `_recommended_next`
    places P4b above P5 and below the close tiers; this must agree, or the two
    halves of one report rank the same work differently."""
    order = ss._suggested_order(_survey_with([
        _p220_task("in progress", "FEAT-3"),
        _p220_task("code committed, docs pending", "FEAT-2"),
        _p220_task("ready for /review-close", "FEAT-1"),
    ]))
    idx = {tid: next(i for i, l in enumerate(order) if tid in l)
           for tid in ("FEAT-1", "FEAT-2", "FEAT-3")}
    assert idx["FEAT-1"] < idx["FEAT-2"] < idx["FEAT-3"], order


def test_the_json_render_carries_pending_doc():
    """**Round finding: `TaskState.pending_doc` was WRITE-ONLY** — three writes,
    no reader outside its own unit tests — on the surface `/sitrep`'s skill calls
    "for orchestrator consumption".

    The tree already carries this guard's twin one dataclass over
    (`test_flag_contract.py::test_json_render_carries_the_triage_record`, whose
    docstring says dropping keys from the render "is invisible to every other
    test"). It was not copied."""
    import json
    payload = json.loads(ss.render_json(_survey_with([
        _p220_task("code committed, docs pending", "FEAT-2"),
        _p220_task("ready for /review-close", "FEAT-1"),
    ])))
    by_id = {t["task_id"]: t for t in payload["tasks"]}
    assert by_id["FEAT-2"]["pending_doc"] is False
    assert by_id["FEAT-1"]["pending_doc"] is True


def test_run_survey_wires_the_resolver_to_the_classifier(tmp_path, monkeypatch):
    """**Round finding (HIGH): no test called `run_survey`**, so the ONE line
    connecting `_pending_doc_for` to `_classify_task` was unguarded in both
    directions — replacing it with `None` (every task stuck in docs-pending) or
    with a constant Path (the feature inert) both passed the whole suite.

    Drives `run_survey` with the filesystem stubbed, so it asserts the wiring
    rather than re-testing the resolver."""
    seen = {}

    def fake_resolver(main_root, branch, lock, worktree):
        seen["called"] = True
        seen["branch"] = branch
        return Path("/somewhere/pending-docs/x.md") if branch == "feat/has-doc" else None

    monkeypatch.setattr(ss, "_pending_doc_for", fake_resolver)
    monkeypatch.setattr(ss, "_resolve_main_repo_root", lambda: tmp_path)
    monkeypatch.setattr(ss, "_git", lambda *a, **k: "abc1234")
    monkeypatch.setattr(ss, "_read_worktrees", lambda root: [])
    monkeypatch.setattr(ss, "_read_index", lambda root: {"FEAT-1": {"status": "in_progress"}})
    monkeypatch.setattr(ss, "_read_review_batches", lambda root: [])
    monkeypatch.setattr(ss, "_commits_unpushed", lambda b, r: 0)
    monkeypatch.setattr(ss, "_worktree_dirty", lambda p: False)
    monkeypatch.setattr(ss, "_find_discrepancies", lambda *a, **k: [])
    monkeypatch.setattr(ss, "_open_roadmap_ids", lambda idx: [], raising=False)
    monkeypatch.setattr(ss, "_read_locks", lambda root: [
        ss.Lock(task_id="FEAT-1", path=tmp_path / "x.lock", branch="feat/no-doc",
                workspace=str(tmp_path), started="2026-08-21T10:00:00Z")])
    monkeypatch.setattr(ss, "_commits_ahead_of_main", lambda b, r: [
        ss.Commit(sha="abc", subject="feat: x",
                  author_date=datetime(2026, 8, 21, tzinfo=timezone.utc),
                  doc_work_ids=["FEAT-1"], subject_task_id=None)])

    survey = ss.run_survey()

    assert seen.get("called"), "run_survey never called the pending-doc resolver"
    assert seen["branch"] == "feat/no-doc", "the resolver got the wrong branch"
    assert survey.tasks[0].state == "code committed, docs pending"
    assert survey.tasks[0].pending_doc is False


def test_the_worktree_arm_of_the_resolver_is_exercised(tmp_path):
    """**Round finding: no test passed a non-None worktree**, so arm (i) — the
    git-listed worktree, which is the DEFAULT claim mode — had zero coverage and
    could be deleted with the suite green."""
    main = tmp_path / "main"
    main.mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    _write_pending_doc(wt, "feat/feat-1")
    worktree = ss.Worktree(path=wt, branch="feat/feat-1", head="abc", is_main=False)

    found = ss._pending_doc_for(main, "feat/feat-1", None, worktree)
    assert found is not None, "arm (i) did not resolve the git-listed worktree"
    assert found.parents[3] == wt


def test_the_worktree_arm_is_tried_before_the_main_checkout(tmp_path):
    """**Round finding: candidate ORDER was untested.** Prepending `main_root`
    let a stale doc in the main checkout shadow the live workspace's."""
    main = tmp_path / "main"
    main.mkdir()
    _write_pending_doc(main, "feat/feat-1")      # stale
    wt = tmp_path / "wt"
    wt.mkdir()
    _write_pending_doc(wt, "feat/feat-1")        # live
    worktree = ss.Worktree(path=wt, branch="feat/feat-1", head="abc", is_main=False)

    found = ss._pending_doc_for(main, "feat/feat-1", None, worktree)
    assert found.parents[3] == wt, (
        f"resolved {found} — the main checkout shadowed the live workspace"
    )


def test_recommended_next_ranks_the_close_tiers_above_docs_pending():
    """The other half of the ordering claim. `_suggested_order`'s ranking is
    pinned above; `_recommended_next`'s was not, so hoisting the P4b block above
    P1 kept the whole suite green — and the two halves of one report would then
    rank the same work differently.

    A task ready to close outranks one still needing documentation: closing
    frees a branch and a lock, documenting does not."""
    rec = ss._recommended_next(_survey_with([
        _p220_task("code committed, docs pending", "FEAT-2"),
        _p220_task("ready for /review-close", "FEAT-1"),
    ]))
    assert rec is not None
    assert "/review-close" in rec.command and "FEAT-1" in rec.command, (
        f"docs-pending outranked a closable task: {rec.command!r}"
    )


def test_recommended_next_ranks_docs_pending_above_in_progress():
    """The lower bound of the same claim: a task with a build commit and a
    trailer is further along than one still mid-build."""
    rec = ss._recommended_next(_survey_with([
        _p220_task("in progress", "FEAT-3"),
        _p220_task("code committed, docs pending", "FEAT-2"),
    ]))
    assert rec is not None
    assert "/document-work" in rec.command and "FEAT-2" in rec.command, rec.command


# === _recommended_next: the Review Ready header arm (Phase 222, Q-014) ======


def test_review_ready_batch_outranks_everything_below_p2():
    """A `Review Ready` batch never enters s.review_batches (the Pending /
    In-Progress filter), so before Phase 222 the cascade was blind to the one
    live status that waits on a human — /sitrep's table documented an arm
    nothing computed. The arm rides its own Survey field, read from the raw
    headers, so the payload contract /roadmap documents is untouched."""
    s = _survey(["FEAT-1"])  # would otherwise reach P7/P8 territory
    s.review_ready_batches = [(7, "Batch title")]
    rec = ss._recommended_next(s)
    assert rec is not None
    assert rec.command == "/review-close (batch 7)"
    assert "Review Ready" in rec.reason


def test_review_ready_arm_reads_the_raw_headers_not_the_filtered_list():
    """run_survey must populate the field from the raw batch parse — a
    filtered-list source would be vacuously empty, which is the pre-222 state."""
    raw = [
        {"number": 3, "title": "Live one", "status": "Review Ready"},
        {"number": 4, "title": "Pending one", "status": "Pending"},
        {"number": 5, "title": "Finished one", "status": "Ready for Review"},
    ]
    ready = [
        (b["number"], b.get("title", ""))
        for b in raw
        if b.get("status") == "Review Ready"
    ]
    # The comprehension above is copied from run_survey; keep them in sync.
    assert ready == [(3, "Live one")]
    src = (Path(__file__).resolve().parent.parent
           / "core" / "companion" / "scripts" / "sitrep_survey.py").read_text()
    assert 'if b.get("status") == "Review Ready"' in src, (
        "run_survey no longer derives review_ready_batches from the raw headers"
    )
    assert src.index('review_batches_raw\n            if b.get("status") == "Review Ready"') > 0
