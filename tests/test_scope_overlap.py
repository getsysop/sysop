"""Tests for ``core/companion/scripts/scope_overlap.py`` — the scope-overlap
primitive for collision-aware claiming (Phase 102).

Structure mirrors the sibling helper suites (``test_next_task.py`` /
``test_sitrep_survey.py``): pure functions tested directly; the single git
boundary (``_worktree_changed_paths``) either mocked at ``subprocess.run`` or
injected via ``assess(..., worktree_reader=...)`` so the factual side runs
without a real repo. ``import scope_overlap`` resolves via the pyproject
``pythonpath = ["core/companion/scripts", "scripts"]`` entry.
"""

from __future__ import annotations

import json
from pathlib import Path

import scope_overlap as so


# ── Fixtures ──────────────────────────────────────────────────────────────


def _build_repo(
    tmp_path: Path,
    index_yaml: str,
    bodies: dict[str, str],
    locks: dict[str, str] | None = None,
) -> Path:
    """Synthetic repo: tasks/index.yml + open/ bodies + .locks/ files."""
    tasks_dir = tmp_path / "tasks"
    open_dir = tasks_dir / "open"
    open_dir.mkdir(parents=True)
    locks_dir = tmp_path / ".locks"
    locks_dir.mkdir()
    (locks_dir / ".gitkeep").write_text("", encoding="utf-8")
    (tasks_dir / "index.yml").write_text(index_yaml, encoding="utf-8")
    for name, body in bodies.items():
        (open_dir / name).write_text(body, encoding="utf-8")
    for name, content in (locks or {}).items():
        (locks_dir / name).write_text(content, encoding="utf-8")
    return tmp_path


def _index(tasks: str) -> str:
    return (
        "schema_version: 2\n"
        "phases:\n"
        "  - {number: 6, title: P, status: in_progress, current_focus: true}\n"
        "tasks:\n" + tasks
    )


def _task(tid: str, blast: str = "single-module", body: str | None = None) -> str:
    body = body or f"open/{tid}.md"
    return (
        f"  - {{id: {tid}, title: T, phase: 6, status: open, effort: Medium, "
        f"blast_radius: {blast}, user_action: false, body: {body}}}\n"
    )


def _lock(tid: str, workspace: str = "", files_impacted: list[str] | None = None) -> str:
    lines = [f"task_id: {tid}", "status: in_progress", f"branch: tech/{tid.lower()}"]
    if workspace:
        lines.append(f"workspace: {workspace}")
    lines.append("files_impacted:")
    for f in files_impacted or ["(update manually or via git diff --name-only main)"]:
        lines.append(f"  - {f}")
    return "\n".join(lines) + "\n"


# ── _norm_path / _looks_like_path ─────────────────────────────────────────


def test_norm_path_strips_backticks_quotes_and_leading_dotslash():
    assert so._norm_path("`./src/api/routes.py`") == "src/api/routes.py"
    assert so._norm_path('"/src/x.py"') == "src/x.py"


def test_norm_path_preserves_trailing_slash_directory_marker():
    assert so._norm_path("src/api/") == "src/api/"


def test_looks_like_path_accepts_paths_globs_dotted_names():
    assert so._looks_like_path("src/api/routes.py")
    assert so._looks_like_path("src/**/*.py")
    assert so._looks_like_path("schema.md")
    assert so._looks_like_path("src/api/")


def test_looks_like_path_rejects_prose_and_spaced_tokens():
    assert not so._looks_like_path("the router module")
    assert not so._looks_like_path("routes")  # bare word, no separator/dot/glob
    assert not so._looks_like_path(".")
    assert not so._looks_like_path("..")


def test_looks_like_path_accepts_extensionless_and_dotfile_config_names():
    # SF1: the high-collision build-config files the plain heuristic dropped.
    for name in ("Makefile", "makefile", "Dockerfile", ".env", ".gitignore", ".babelrc"):
        assert so._looks_like_path(name), name
    # still rejects a leading-dot token that isn't a known dotfile
    assert not so._looks_like_path(".notaknownfile")


# ── _extract_key_files ────────────────────────────────────────────────────


def test_extract_key_files_pulls_backtick_tokens_under_heading():
    body = (
        "# T\n\n## Context\nnope `not/here.py`\n\n"
        "## Key files\n- `src/api/routes.py`\n- `src/api/models.py`\n"
    )
    assert so._extract_key_files(body) == ["src/api/routes.py", "src/api/models.py"]


def test_extract_key_files_stops_at_next_heading():
    body = (
        "## Key files\n- `a/b.py`\n\n"
        "## Test decision\n- `should/not/leak.py`\n"
    )
    assert so._extract_key_files(body) == ["a/b.py"]


def test_extract_key_files_matches_any_heading_level():
    body = "### Key files\n- `a/b.py`\n"
    assert so._extract_key_files(body) == ["a/b.py"]


def test_extract_key_files_absent_section_returns_empty():
    assert so._extract_key_files("# T\n\n## Context\nx\n") == []


def test_extract_key_files_ignores_prose_bullets():
    body = "## Key files\n- the api router\n- `src/x.py`\n"
    assert so._extract_key_files(body) == ["src/x.py"]


def test_extract_key_files_dedupes_preserving_order():
    body = "## Key files\n- `a.py`\n- `a.py`\n- `b.py`\n"
    assert so._extract_key_files(body) == ["a.py", "b.py"]


def test_extract_key_files_picks_up_config_basenames():
    body = "## Key files\n- `Makefile`\n- `.env`\n- `src/app.py`\n"
    assert so._extract_key_files(body) == ["Makefile", ".env", "src/app.py"]


# ── _resolve_body_path / _candidate_scope (body resolution + containment) ──


def test_resolve_body_path_allows_in_tree_both_prefixes(tmp_path):
    """A legit body inside tasks/ resolves via BOTH the bare and the
    ``tasks/``-prefixed form (the two-branch rule) to the same file."""
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "open").mkdir(parents=True)
    (tasks_dir / "open" / "FEAT-X.md").write_text(
        "## Key files\n- `a.py`\n", encoding="utf-8"
    )
    bare = so._resolve_body_path("open/FEAT-X.md", tasks_dir, tmp_path)
    prefixed = so._resolve_body_path("tasks/open/FEAT-X.md", tasks_dir, tmp_path)
    assert bare is not None and bare.name == "FEAT-X.md"
    assert prefixed == bare


def test_resolve_body_path_rejects_dotdot_traversal(tmp_path):
    """A ``..`` escape out of tasks/ returns None — the advisory degrades and
    never reads the escaped file."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tmp_path / "escape.md").write_text("secret", encoding="utf-8")
    assert so._resolve_body_path("../escape.md", tasks_dir, tmp_path) is None


def test_resolve_body_path_rejects_symlink_escape(tmp_path):
    """A symlink inside tasks/ pointing OUT of the tree returns None — realpath
    resolves the link before the containment check (the guard's stated job)."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tmp_path / "outside.md").write_text("secret", encoding="utf-8")
    link = tasks_dir / "evil.md"
    link.symlink_to(tmp_path / "outside.md")
    # precondition: the link genuinely resolves outside tasks/ (else vacuous)
    assert link.resolve() == (tmp_path / "outside.md").resolve()
    assert so._resolve_body_path("evil.md", tasks_dir, tmp_path) is None


def test_candidate_scope_degrades_on_body_escape(tmp_path):
    """End-to-end: a task whose ``body:`` escapes tasks/ must not leak the
    escaped file's ## Key files into the candidate scope — it degrades to the
    blast_radius-only source, which is the whole reason the guard exists."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tmp_path / "escape.md").write_text(
        "## Key files\n- `src/secret.py`\n", encoding="utf-8"
    )
    index = {
        "tasks": [
            {"id": "FEAT-ESC", "blast_radius": "single-module", "body": "../escape.md"}
        ]
    }
    scope = so._candidate_scope("FEAT-ESC", index, tasks_dir, tmp_path)
    assert scope.paths == []                     # escaped ## Key files never read
    assert scope.source == "blast_radius_only"   # degraded, not "key_files"


# ── _grade (pure) ─────────────────────────────────────────────────────────


def test_grade_exact_match_is_likely():
    v, ev = so._grade(["src/api/routes.py"], ["src/api/routes.py"])
    assert v == "likely" and ev == ["src/api/routes.py"]


def test_grade_same_directory_is_possible():
    v, ev = so._grade(["src/api/routes.py"], ["src/api/models.py"])
    assert v == "possible" and ev == ["src/api/models.py"]


def test_grade_directory_prefix_candidate_is_possible():
    v, ev = so._grade(["src/api/"], ["src/api/routes.py"])
    assert v == "possible" and ev == ["src/api/routes.py"]


def test_grade_glob_candidate_matches_is_possible():
    v, ev = so._grade(["src/**/*.py"], ["src/api/routes.py"])
    assert v == "possible" and ev == ["src/api/routes.py"]


def test_grade_inflight_glob_matches_candidate_is_possible():
    # Mirror of the candidate-side glob branch: the *in-flight* task's declared
    # scope is itself a glob that matches the candidate's concrete path.
    v, ev = so._grade(["src/api/routes.py"], ["src/**/*.py"])
    assert v == "possible" and ev == ["src/**/*.py"]


def test_grade_disjoint_is_none():
    v, ev = so._grade(["src/api/routes.py"], ["src/db/schema.sql"])
    assert v == "none" and ev == []


def test_grade_likely_dominates_possible():
    # exact routes.py (likely) + same-dir models.py (possible) → likely, likely-only evidence
    v, ev = so._grade(
        ["src/api/routes.py"], ["src/api/routes.py", "src/api/models.py"]
    )
    assert v == "likely" and ev == ["src/api/routes.py"]


def test_grade_empty_candidate_is_none():
    assert so._grade([], ["src/api/routes.py"]) == ("none", [])


def test_grade_two_root_level_files_do_not_false_match_as_same_dir():
    # Both dirname == "" — must NOT be graded "possible" (would fire on every repo).
    v, _ = so._grade(["README.md"], ["LICENSE"])
    assert v == "none"


# ── _lock_files_impacted ──────────────────────────────────────────────────


def test_lock_files_impacted_drops_placeholder():
    raw = {"files_impacted": ["(update manually or via git diff --name-only main)"]}
    assert so._lock_files_impacted(raw) == []


def test_lock_files_impacted_keeps_real_paths():
    raw = {"files_impacted": ["src/api/routes.py", "not a path", "src/db/x.sql"]}
    assert so._lock_files_impacted(raw) == ["src/api/routes.py", "src/db/x.sql"]


def test_lock_files_impacted_trusts_declared_config_files():
    # SF1: the factual list is trusted verbatim — config files the candidate-side
    # prose heuristic would drop are KEPT here; only placeholder-shaped entries go.
    raw = {
        "files_impacted": [
            "Makefile",
            ".env",
            "src/api/routes.py",
            "(update manually or via git diff --name-only main)",
        ]
    }
    assert so._lock_files_impacted(raw) == ["Makefile", ".env", "src/api/routes.py"]


# ── _run_git_porcelain / _worktree_changed_paths (mocked subprocess) ──────


class _FakeProc:
    def __init__(self, returncode: int, stdout: str):
        self.returncode = returncode
        self.stdout = stdout


def test_run_git_porcelain_parses_rename_to_new_path(monkeypatch):
    def fake_run(cmd, **kw):
        return _FakeProc(0, " M src/a.py\nR  src/old.py -> src/new.py\n?? src/u.py\n")

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    assert so._run_git_porcelain("/ws") == ["src/a.py", "src/new.py", "src/u.py"]


def test_worktree_changed_paths_unions_committed_and_uncommitted(monkeypatch, tmp_path):
    ws = str(tmp_path)  # must be a real dir for the isdir guard

    def fake_run(cmd, **kw):
        if "diff" in cmd:  # git -C ws diff --name-only main...HEAD
            return _FakeProc(0, "src/api/routes.py\n")
        return _FakeProc(0, "?? src/api/new.py\n")  # status --porcelain

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    assert so._worktree_changed_paths(ws) == ["src/api/new.py", "src/api/routes.py"]


def test_worktree_changed_paths_falls_back_main_to_origin_main(monkeypatch, tmp_path):
    ws = str(tmp_path)
    calls: list[str] = []

    def fake_run(cmd, **kw):
        if "diff" in cmd:
            base = cmd[-1]  # e.g. "main...HEAD"
            calls.append(base)
            if base.startswith("main"):
                return _FakeProc(1, "")  # main doesn't resolve
            return _FakeProc(0, "src/x.py\n")  # origin/main resolves
        return _FakeProc(0, "")

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    assert so._worktree_changed_paths(ws) == ["src/x.py"]
    assert calls == ["main...HEAD", "origin/main...HEAD"]


def test_worktree_changed_paths_returns_empty_for_nonexistent_workspace():
    assert so._worktree_changed_paths("/no/such/workspace/xyz") == []


# ── assess (integration, injected reader) ─────────────────────────────────


def _assess(tmp_path: Path, candidate: str, reader) -> so.Assessment:
    return so.assess(
        candidate,
        index_path=tmp_path / "tasks" / "index.yml",
        base_tasks_dir=tmp_path / "tasks",
        project_root=tmp_path,
        worktree_reader=reader,
    )


def test_assess_likely_overlap_via_worktree_diff(tmp_path):
    repo = _build_repo(
        tmp_path,
        _index(_task("FEAT-CAND", "cross-module") + _task("TECH-B")),
        {
            "FEAT-CAND.md": "# FEAT-CAND\n\n## Key files\n- `src/api/routes.py`\n",
            "TECH-B.md": "# TECH-B\n\n## Key files\n- `src/other.py`\n",
        },
        {"TECH-B.lock": _lock("TECH-B", workspace="/ws/tech-b")},
    )
    a = _assess(repo, "FEAT-CAND", lambda ws: ["src/api/routes.py"] if ws == "/ws/tech-b" else [])
    assert a.max_verdict == "likely"
    assert a.in_flight_count == 1
    assert len(a.overlaps) == 1
    o = a.overlaps[0]
    assert o.task_id == "TECH-B" and o.verdict == "likely"
    assert o.evidence == ["src/api/routes.py"] and o.scope_source == "worktree_diff"


def test_assess_falls_back_to_files_impacted_when_worktree_empty(tmp_path):
    repo = _build_repo(
        tmp_path,
        _index(_task("FEAT-CAND") + _task("TECH-B")),
        {
            "FEAT-CAND.md": "# FEAT-CAND\n\n## Key files\n- `src/api/routes.py`\n",
            "TECH-B.md": "# TECH-B\n\n## Key files\n- `src/other.py`\n",
        },
        {"TECH-B.lock": _lock("TECH-B", workspace="/ws/tb", files_impacted=["src/api/routes.py"])},
    )
    a = _assess(repo, "FEAT-CAND", lambda ws: [])  # worktree diff empty
    assert a.overlaps and a.overlaps[0].scope_source == "files_impacted"
    assert a.overlaps[0].verdict == "likely"


def test_assess_falls_back_to_body_key_files_when_worktree_and_impacted_empty(tmp_path):
    repo = _build_repo(
        tmp_path,
        _index(_task("FEAT-CAND") + _task("TECH-B")),
        {
            "FEAT-CAND.md": "# FEAT-CAND\n\n## Key files\n- `src/api/routes.py`\n",
            "TECH-B.md": "# TECH-B\n\n## Key files\n- `src/api/routes.py`\n",
        },
        {"TECH-B.lock": _lock("TECH-B", workspace="/ws/tb")},  # only placeholder impacted
    )
    a = _assess(repo, "FEAT-CAND", lambda ws: [])
    assert a.overlaps and a.overlaps[0].scope_source == "key_files"
    assert a.overlaps[0].verdict == "likely"


def test_assess_skips_the_candidates_own_lock(tmp_path):
    # Defensive: even if the candidate itself is locked, it must not self-collide.
    repo = _build_repo(
        tmp_path,
        _index(_task("FEAT-CAND")),
        {"FEAT-CAND.md": "# FEAT-CAND\n\n## Key files\n- `src/api/routes.py`\n"},
        {"FEAT-CAND.lock": _lock("FEAT-CAND", workspace="/ws/cand")},
    )
    a = _assess(repo, "FEAT-CAND", lambda ws: ["src/api/routes.py"])
    assert a.in_flight_count == 0 and a.overlaps == []


def test_assess_catches_config_file_collision_end_to_end(tmp_path):
    # SF1 motivating case: a candidate whose only Key file is a build-config file
    # must still register a likely overlap when an in-flight worktree touches it.
    repo = _build_repo(
        tmp_path,
        _index(_task("FEAT-CAND") + _task("TECH-B")),
        {
            "FEAT-CAND.md": "# FEAT-CAND\n\n## Key files\n- `Makefile`\n",
            "TECH-B.md": "# TECH-B\n",
        },
        {"TECH-B.lock": _lock("TECH-B", workspace="/ws/tb")},
    )
    a = _assess(repo, "FEAT-CAND", lambda ws: ["Makefile"] if ws == "/ws/tb" else [])
    assert a.max_verdict == "likely"
    assert a.overlaps and a.overlaps[0].evidence == ["Makefile"]


def test_assess_no_locks_reports_zero_in_flight(tmp_path):
    repo = _build_repo(
        tmp_path,
        _index(_task("FEAT-CAND")),
        {"FEAT-CAND.md": "# FEAT-CAND\n\n## Key files\n- `src/api/routes.py`\n"},
    )
    a = _assess(repo, "FEAT-CAND", lambda ws: ["src/api/routes.py"])
    assert a.in_flight_count == 0 and a.max_verdict == "none"


def test_assess_missing_index_notes_and_does_not_raise(tmp_path):
    (tmp_path / ".locks").mkdir()
    a = so.assess(
        "FEAT-CAND",
        index_path=tmp_path / "nope.yml",
        base_tasks_dir=tmp_path / "tasks",
        project_root=tmp_path,
        worktree_reader=lambda ws: [],
    )
    assert a.candidate_scope_source == "none"
    assert any("index" in n for n in a.notes)


def test_assess_candidate_not_in_index_still_assesses_in_flight(tmp_path):
    repo = _build_repo(
        tmp_path,
        _index(_task("TECH-B")),
        {"TECH-B.md": "# TECH-B\n\n## Key files\n- `src/x.py`\n"},
        {"TECH-B.lock": _lock("TECH-B", workspace="/ws/tb")},
    )
    a = _assess(repo, "FEAT-MISSING", lambda ws: ["src/x.py"])
    assert a.candidate_scope_source == "none"
    assert a.in_flight_count == 1  # still counted the in-flight task
    assert a.overlaps == []  # no candidate scope → nothing to match
    assert any("not found" in n for n in a.notes)


def test_assess_broad_radius_note_fires_on_possible_not_likely(tmp_path):
    repo = _build_repo(
        tmp_path,
        _index(_task("FEAT-CAND", "architectural") + _task("TECH-B")),
        {
            "FEAT-CAND.md": "# FEAT-CAND\n\n## Key files\n- `src/api/routes.py`\n",
            "TECH-B.md": "# TECH-B\n\n## Key files\n- `x.py`\n",
        },
        {"TECH-B.lock": _lock("TECH-B", workspace="/ws/tb")},
    )
    # same-dir → possible; architectural + not-likely → broad note fires
    a = _assess(repo, "FEAT-CAND", lambda ws: ["src/api/models.py"])
    assert a.max_verdict == "possible" and a.broad_radius_note

    # exact → likely → broad note suppressed (the likely verdict already tells it)
    a2 = _assess(repo, "FEAT-CAND", lambda ws: ["src/api/routes.py"])
    assert a2.max_verdict == "likely" and not a2.broad_radius_note


def test_assess_orders_likely_before_possible(tmp_path):
    repo = _build_repo(
        tmp_path,
        _index(_task("FEAT-CAND") + _task("TECH-B") + _task("TECH-C")),
        {
            "FEAT-CAND.md": "# FEAT-CAND\n\n## Key files\n- `src/api/routes.py`\n",
            "TECH-B.md": "# TECH-B\n",
            "TECH-C.md": "# TECH-C\n",
        },
        {
            "TECH-B.lock": _lock("TECH-B", workspace="/ws/tb"),  # same-dir → possible
            "TECH-C.lock": _lock("TECH-C", workspace="/ws/tc"),  # exact → likely
        },
    )

    def reader(ws):
        return {"/ws/tb": ["src/api/models.py"], "/ws/tc": ["src/api/routes.py"]}.get(ws, [])

    a = _assess(repo, "FEAT-CAND", reader)
    assert [o.verdict for o in a.overlaps] == ["likely", "possible"]
    assert a.overlaps[0].task_id == "TECH-C"


# ── rendering ─────────────────────────────────────────────────────────────


def test_render_text_clean_when_no_inflight(tmp_path):
    repo = _build_repo(
        tmp_path,
        _index(_task("FEAT-CAND")),
        {"FEAT-CAND.md": "# FEAT-CAND\n\n## Key files\n- `a.py`\n"},
    )
    a = _assess(repo, "FEAT-CAND", lambda ws: [])
    assert "No work in flight" in so.render_text(a)


def test_render_text_warns_on_overlap(tmp_path):
    repo = _build_repo(
        tmp_path,
        _index(_task("FEAT-CAND") + _task("TECH-B")),
        {"FEAT-CAND.md": "# FEAT-CAND\n\n## Key files\n- `a.py`\n", "TECH-B.md": "# TECH-B\n"},
        {"TECH-B.lock": _lock("TECH-B", workspace="/ws/tb")},
    )
    a = _assess(repo, "FEAT-CAND", lambda ws: ["a.py"])
    text = so.render_text(a)
    assert "⚠" in text and "TECH-B" in text and "likely merge conflict" in text


def test_render_json_is_valid_and_carries_contract_keys(tmp_path):
    repo = _build_repo(
        tmp_path,
        _index(_task("FEAT-CAND") + _task("TECH-B")),
        {"FEAT-CAND.md": "# FEAT-CAND\n\n## Key files\n- `a.py`\n", "TECH-B.md": "# TECH-B\n"},
        {"TECH-B.lock": _lock("TECH-B", workspace="/ws/tb")},
    )
    a = _assess(repo, "FEAT-CAND", lambda ws: ["a.py"])
    obj = json.loads(so.render_json(a))
    assert obj["candidate"] == "FEAT-CAND"
    assert obj["max_verdict"] == "likely"
    assert obj["overlaps"][0]["task_id"] == "TECH-B"
    for key in ("candidate_scope_source", "candidate_paths", "in_flight_count", "notes"):
        assert key in obj


# ── main / CLI ────────────────────────────────────────────────────────────


def _patch_module_paths(monkeypatch, repo: Path) -> None:
    monkeypatch.setattr(so, "_REPO_ROOT", repo)
    monkeypatch.setattr(so, "_TASKS_DIR", repo / "tasks")
    monkeypatch.setattr(so, "_INDEX_PATH", repo / "tasks" / "index.yml")


def test_main_text_returns_zero(monkeypatch, capsys, tmp_path):
    repo = _build_repo(
        tmp_path,
        _index(_task("FEAT-CAND")),
        {"FEAT-CAND.md": "# FEAT-CAND\n\n## Key files\n- `a.py`\n"},
    )
    _patch_module_paths(monkeypatch, repo)
    monkeypatch.setattr(so, "_worktree_changed_paths", lambda ws: [])
    rc = so.main(["FEAT-CAND"])
    assert rc == 0
    assert "FEAT-CAND" in capsys.readouterr().out


def test_main_json_returns_zero_and_valid_json(monkeypatch, capsys, tmp_path):
    repo = _build_repo(
        tmp_path,
        _index(_task("FEAT-CAND") + _task("TECH-B")),
        {"FEAT-CAND.md": "# FEAT-CAND\n\n## Key files\n- `a.py`\n", "TECH-B.md": "# TECH-B\n"},
        {"TECH-B.lock": _lock("TECH-B", workspace="/ws/tb")},
    )
    _patch_module_paths(monkeypatch, repo)
    monkeypatch.setattr(so, "_worktree_changed_paths", lambda ws: ["a.py"])
    rc = so.main(["FEAT-CAND", "--json"])
    assert rc == 0
    obj = json.loads(capsys.readouterr().out)
    assert obj["max_verdict"] == "likely" and obj["overlaps"][0]["task_id"] == "TECH-B"


def test_main_missing_index_still_returns_zero(monkeypatch, capsys, tmp_path):
    # Advisory-non-blocking: a broken/missing index must not break the caller.
    (tmp_path / ".locks").mkdir()
    monkeypatch.setattr(so, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(so, "_TASKS_DIR", tmp_path / "tasks")
    monkeypatch.setattr(so, "_INDEX_PATH", tmp_path / "tasks" / "index.yml")
    monkeypatch.setattr(so, "_worktree_changed_paths", lambda ws: [])
    assert so.main(["FEAT-CAND"]) == 0
    capsys.readouterr()
