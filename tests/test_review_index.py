"""Tests for ``core/companion/scripts/review_index.py``.

Sysop-original. No gdp counterpart; all tests in this file are Phase 48
originals.

Surface covered:

- ``_file_sha256`` — deterministic digest over bytes.
- ``parse_review_tasks`` — header / batch / metadata / task / deferred /
  grand-total recognition; line-number accuracy; severity + checkbox maps;
  trailing-batch close.
- ``_finalize_batch`` / ``_build_summary`` — derived counts.
- ``write_index`` / ``read_index`` — atomic round-trip + missing-file
  semantics.
- ``is_stale`` / ``ensure_fresh`` / ``rebuild_index`` — staleness gating.
- ``list_batches`` / ``get_batch`` / ``get_batch_range`` — query helpers.
"""

from __future__ import annotations

import json
from pathlib import Path

import review_index as ri


# === Fixtures ==============================================================

# A canonical review_tasks.md fragment that exercises the full parser surface.
# All emojis use the source-file escape sequences the regexes match.
_TASKS_FIXTURE = """\
# Review tasks

## Round 1 — 2026-05-20

### Batch 1 — Helper rename `Pending`
> **Branch:** `review/2026-05-20-rename`
> **Scope:** `core/companion/scripts/foo.py`
> **Verify:** `pytest tests/test_foo.py -v`
> **Overlap:** none

- [ ] **TASK-0001**: Rename `_helper` to `_resolve_helper` \U0001f7e1
- [ ] **TASK-0002**: Update callers \U0001f7e2
- [x] **TASK-0003**: Update docstring \U0001f7e2

### Batch 2 — Security tightening `In Progress`
> **Branch:** `review/2026-05-20-sec`
> **Scope:** `core/companion/security_map.md`
> **Flag:** subprocess
> **OWASP:** A03

- [/] **TASK-0010**: Audit subprocess.run callsites \U0001f534
- [ ] **TASK-0011**: Add shell=False default \U0001f534

## Round 2 — 2026-05-22

### Batch 3 — Doc polish `Pending`
> **Branch:** `review/2026-05-22-docs`
> **Scope:** `README.md`
> **Verify:** none

- [ ] **TASK-0020**: Clarify install path \U0001f7e2

## Deferred

- [ ] **TASK-9001**: Future feature \U0001f7e1 — deferred to v2
- [ ] **TASK-9002**: Edge case — see ticket 123

## Statistics

**Grand Total (all rounds):** 7 tasks — 1 done, 4 open, 2 deferred
"""


def _write_tasks(tmp_path: Path) -> Path:
    tasks = tmp_path / "review_tasks.md"
    tasks.write_text(_TASKS_FIXTURE, encoding="utf-8")
    return tasks


# === _file_sha256 ==========================================================


def test_file_sha256_is_deterministic(tmp_path):
    p = tmp_path / "x.txt"
    p.write_bytes(b"hello\n")
    digest_a = ri._file_sha256(str(p))
    digest_b = ri._file_sha256(str(p))
    assert digest_a == digest_b
    assert len(digest_a) == 64  # SHA-256 hex


def test_file_sha256_changes_with_content(tmp_path):
    p = tmp_path / "x.txt"
    p.write_bytes(b"hello\n")
    a = ri._file_sha256(str(p))
    p.write_bytes(b"world\n")
    b = ri._file_sha256(str(p))
    assert a != b


# === parse_review_tasks ====================================================


def test_parse_extracts_three_batches_with_titles_and_statuses(tmp_path):
    tasks = _write_tasks(tmp_path)
    data = ri.parse_review_tasks(str(tasks))
    assert set(data["batches"].keys()) == {"1", "2", "3"}
    assert data["batches"]["1"]["title"] == "Helper rename"
    assert data["batches"]["1"]["status"] == "Pending"
    assert data["batches"]["2"]["status"] == "In Progress"
    assert data["batches"]["3"]["status"] == "Pending"


def test_parse_captures_metadata_fields(tmp_path):
    tasks = _write_tasks(tmp_path)
    data = ri.parse_review_tasks(str(tasks))
    b1 = data["batches"]["1"]
    assert b1["branch"] == "review/2026-05-20-rename"
    assert b1["scope"] == "`core/companion/scripts/foo.py`"
    assert b1["verify"] == "`pytest tests/test_foo.py -v`"
    assert b1["overlap"] == "none"
    b2 = data["batches"]["2"]
    assert b2["flag"] == "subprocess"
    assert b2["owasp"] == "A03"


def test_parse_captures_tasks_with_severity_and_checkbox(tmp_path):
    tasks = _write_tasks(tmp_path)
    data = ri.parse_review_tasks(str(tasks))
    b1_tasks = data["batches"]["1"]["tasks"]
    assert [t["id"] for t in b1_tasks] == ["TASK-0001", "TASK-0002", "TASK-0003"]
    assert b1_tasks[0]["severity"] == "medium"   # 🟡
    assert b1_tasks[1]["severity"] == "low"      # 🟢
    assert b1_tasks[0]["checkbox"] == "open"
    assert b1_tasks[2]["checkbox"] == "done"

    b2_tasks = data["batches"]["2"]["tasks"]
    assert b2_tasks[0]["checkbox"] == "in_progress"
    assert b2_tasks[0]["severity"] == "high"     # 🔴


def test_parse_assigns_one_indexed_line_numbers(tmp_path):
    tasks = _write_tasks(tmp_path)
    data = ri.parse_review_tasks(str(tasks))
    b1 = data["batches"]["1"]
    # Line 5 in the fixture: "### Batch 1 — Helper rename `Pending`"
    assert b1["line_start"] == 5
    # line_end must be set and >= line_start
    assert b1["line_end"] is not None and b1["line_end"] >= b1["line_start"]
    # First task line should fall within the batch range
    first_task = b1["tasks"][0]
    assert b1["line_start"] < first_task["line"] <= b1["line_end"]


def test_parse_extracts_deferred_tasks(tmp_path):
    tasks = _write_tasks(tmp_path)
    data = ri.parse_review_tasks(str(tasks))
    assert len(data["deferred"]) == 2
    ids = [d["id"] for d in data["deferred"]]
    assert ids == ["TASK-9001", "TASK-9002"]
    assert data["deferred"][0]["severity"] == "medium"
    assert data["deferred"][1]["severity"] == "unknown"


def test_parse_captures_grand_total(tmp_path):
    tasks = _write_tasks(tmp_path)
    data = ri.parse_review_tasks(str(tasks))
    assert data["grand_total"] == {
        "total": 7, "done": 1, "open": 4, "deferred": 2,
    }


def test_parse_records_rounds_in_order(tmp_path):
    tasks = _write_tasks(tmp_path)
    data = ri.parse_review_tasks(str(tasks))
    assert data["rounds"][0].startswith("Round 1")
    assert data["rounds"][1].startswith("Round 2")


def test_parse_closes_trailing_batch_when_no_statistics_section(tmp_path):
    """If the file ends without ``## Statistics``, the last batch still closes."""
    content = (
        "## Round 1\n"
        "### Batch 99 — Trailing `Pending`\n"
        "> **Branch:** `review/x`\n"
        "> **Scope:** `x`\n"
        "> **Verify:** `x`\n"
        "\n"
        "- [ ] **TASK-9999**: Test \U0001f7e2\n"
    )
    tasks = tmp_path / "review_tasks.md"
    tasks.write_text(content, encoding="utf-8")
    data = ri.parse_review_tasks(str(tasks))
    assert "99" in data["batches"]
    assert data["batches"]["99"]["line_end"] is not None


def test_parse_populates_summary(tmp_path):
    tasks = _write_tasks(tmp_path)
    data = ri.parse_review_tasks(str(tasks))
    s = data["summary"]
    assert s["total_batches"] == 3
    # Total tasks across batches (not deferred): 3 + 2 + 1 = 6
    assert s["total_tasks"] == 6
    assert s["by_status"]["Pending"] == 2
    assert s["by_status"]["In Progress"] == 1


def test_finalize_batch_computes_counts():
    batch = {
        "tasks": [
            {"checkbox": "open", "severity": "high"},
            {"checkbox": "done", "severity": "low"},
            {"checkbox": "in_progress", "severity": "medium"},
        ],
    }
    ri._finalize_batch(batch)
    assert batch["counts"] == {
        "total": 3, "open": 1, "in_progress": 1, "done": 1,
        "high": 1, "medium": 1, "low": 1,
    }


# === I/O round-trip + staleness ============================================


def test_write_index_then_read_index_round_trips(tmp_path):
    index_path = tmp_path / ".claude" / "review_index.json"
    payload = {"source_sha256": "abc", "batches": {"1": {"number": 1}}, "summary": {}}
    ri.write_index(payload, str(index_path))
    assert index_path.exists()
    assert ri.read_index(str(index_path)) == payload


def test_write_index_is_atomic(tmp_path):
    """write_index must not leave a ``.tmp`` file behind after success."""
    index_path = tmp_path / ".claude" / "review_index.json"
    ri.write_index({"x": 1}, str(index_path))
    assert not (tmp_path / ".claude" / "review_index.json.tmp").exists()


def test_read_index_returns_none_when_missing(tmp_path):
    assert ri.read_index(str(tmp_path / "nope.json")) is None


def test_is_stale_true_when_no_index(tmp_path):
    tasks = _write_tasks(tmp_path)
    index = tmp_path / ".claude" / "review_index.json"
    assert ri.is_stale(str(tasks), str(index)) is True


def test_is_stale_false_after_rebuild(tmp_path):
    tasks = _write_tasks(tmp_path)
    index = tmp_path / ".claude" / "review_index.json"
    ri.rebuild_index(str(tasks), str(index))
    assert ri.is_stale(str(tasks), str(index)) is False


def test_is_stale_true_after_source_mutation(tmp_path):
    tasks = _write_tasks(tmp_path)
    index = tmp_path / ".claude" / "review_index.json"
    ri.rebuild_index(str(tasks), str(index))
    tasks.write_text(_TASKS_FIXTURE + "\n# trailing change\n", encoding="utf-8")
    assert ri.is_stale(str(tasks), str(index)) is True


def test_ensure_fresh_rebuilds_when_stale(tmp_path):
    tasks = _write_tasks(tmp_path)
    index = tmp_path / ".claude" / "review_index.json"
    data = ri.ensure_fresh(str(tasks), str(index))
    assert index.exists()
    assert "batches" in data


def test_ensure_fresh_short_circuits_when_fresh(tmp_path):
    tasks = _write_tasks(tmp_path)
    index = tmp_path / ".claude" / "review_index.json"
    first = ri.ensure_fresh(str(tasks), str(index))
    written_at = index.stat().st_mtime_ns
    # No source change → second call reads cached
    second = ri.ensure_fresh(str(tasks), str(index))
    assert second["source_sha256"] == first["source_sha256"]
    assert index.stat().st_mtime_ns == written_at  # not rewritten


# === Query helpers =========================================================


def test_list_batches_emits_tab_separated_rows_in_order(tmp_path):
    tasks = _write_tasks(tmp_path)
    data = ri.parse_review_tasks(str(tasks))
    lines = ri.list_batches(data)
    # Three batches in numerical order
    assert lines[0].startswith("1\tHelper rename\tPending\t")
    assert lines[1].startswith("2\tSecurity tightening\tIn Progress\t")
    assert lines[2].startswith("3\tDoc polish\tPending\t")


def test_get_batch_returns_dict_or_none(tmp_path):
    tasks = _write_tasks(tmp_path)
    data = ri.parse_review_tasks(str(tasks))
    assert ri.get_batch(data, 2)["title"] == "Security tightening"
    assert ri.get_batch(data, 99) is None


def test_get_batch_range_returns_tuple(tmp_path):
    tasks = _write_tasks(tmp_path)
    data = ri.parse_review_tasks(str(tasks))
    r = ri.get_batch_range(data, 1)
    assert r is not None
    start, end, status, branch = r
    assert isinstance(start, int) and isinstance(end, int)
    assert start <= end
    assert status == "Pending"
    assert branch == "review/2026-05-20-rename"


def test_get_batch_range_none_for_missing(tmp_path):
    tasks = _write_tasks(tmp_path)
    data = ri.parse_review_tasks(str(tasks))
    assert ri.get_batch_range(data, 999) is None
