"""Tests for ``core/companion/scripts/backfill_completed_dates.py``.

Sysop-original (migration helper). No gdp counterpart; all tests in
this file are Phase 48 originals.

Surface covered:

- ``_sanitize_log`` — control-character/ANSI stripping + length cap.
- ``find_completion_date`` — git-log boundary mocked at the subprocess
  layer (bold-form match, backtick-form fallback, no-match, git failure).
- ``main`` — happy path (writes inferred dates), ``--dry-run`` (no write),
  ``--id-pattern`` filter, missing index → exit 1.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import yaml

import backfill_completed_dates as bcd


# === _sanitize_log =========================================================


def test_sanitize_log_strips_ansi_and_control_chars():
    assert bcd._sanitize_log("\x1b[31merror\x1b[0m") == "error"
    assert bcd._sanitize_log("a\x01b\x07c") == "abc"


def test_sanitize_log_replaces_newlines_and_nulls():
    assert bcd._sanitize_log("line 1\nline 2\rline 3\x00end") == "line 1 line 2 line 3 end"


def test_sanitize_log_truncates_above_max_len():
    long = "x" * 600
    out = bcd._sanitize_log(long, max_len=500)
    assert len(out) == 503  # 500 chars + "..."
    assert out.endswith("...")


# === find_completion_date ==================================================


def test_find_completion_date_matches_bold_form_on_first_pattern():
    """`[x] **TASK-ID` shape is tried first."""
    fake = subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout="abc1234 2026-05-01\ndef5678 2026-06-02\n",
        stderr="",
    )
    with mock.patch.object(bcd.subprocess, "run", return_value=fake) as m:
        date = bcd.find_completion_date("FEAT-0001", "product_roadmap.md")
    assert date == "2026-05-01"
    # First pattern tried = bold-form
    needle_arg = m.call_args.args[0]
    assert "[x] **FEAT-0001" in needle_arg


def test_find_completion_date_falls_back_to_backtick_form():
    """If bold-form produces empty output, the backtick-form is tried next."""
    empty = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    hit = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="xyz9999 2026-07-15\n", stderr="",
    )
    with mock.patch.object(bcd.subprocess, "run", side_effect=[empty, hit]) as m:
        date = bcd.find_completion_date("BUG-0042", "ROADMAP.md")
    assert date == "2026-07-15"
    # Confirm two subprocess invocations + that the second searched backticks
    assert m.call_count == 2
    second_needle = m.call_args_list[1].args[0]
    assert "`BUG-0042`" in second_needle


def test_find_completion_date_returns_none_when_no_match():
    empty = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with mock.patch.object(bcd.subprocess, "run", return_value=empty):
        assert bcd.find_completion_date("FEAT-9999", "product_roadmap.md") is None


def test_find_completion_date_skips_pattern_on_git_failure(capsys):
    """If subprocess raises, the helper logs and tries the next pattern."""
    def _raise_then_hit(*a, **kw):
        if not hasattr(_raise_then_hit, "_called"):
            _raise_then_hit._called = True
            raise subprocess.SubprocessError("git crashed")
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout="cafe1234 2026-08-09\n", stderr="",
        )
    with mock.patch.object(bcd.subprocess, "run", side_effect=_raise_then_hit):
        date = bcd.find_completion_date("FEAT-0005", "product_roadmap.md")
    assert date == "2026-08-09"
    captured = capsys.readouterr()
    assert "WARN: git log failed" in captured.err


# === main() — integration ==================================================


_INDEX_FIXTURE = {
    "schema_version": 1,
    "phases": [
        {"number": 1, "title": "Phase 1", "status": "done"},
    ],
    "tasks": [
        {
            "id": "FEAT-0001",
            "title": "Old done task without date",
            "phase": 1,
            "status": "done",
            "effort": "Medium",
            "user_action": False,
            "depends_on": [],
            "surfaced_by": [],
        },
        {
            "id": "FEAT-0002",
            "title": "Done task that already has a date",
            "phase": 1,
            "status": "done",
            "completed_date": "2026-05-15",
            "effort": "Low",
            "user_action": False,
            "depends_on": [],
            "surfaced_by": [],
        },
        {
            "id": "BUG-0001",
            "title": "Open task — must be ignored",
            "phase": 1,
            "status": "open",
            "effort": "Low",
            "user_action": False,
            "depends_on": [],
            "surfaced_by": [],
        },
    ],
}


def _write_index(tmp_path: Path) -> Path:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    index = tasks_dir / "index.yml"
    with open(index, "w", encoding="utf-8") as f:
        yaml.safe_dump(_INDEX_FIXTURE, f, sort_keys=False)
    return index


def test_main_writes_completed_date_for_needs_backfill(tmp_path, capsys):
    index = _write_index(tmp_path)
    with mock.patch.object(bcd, "find_completion_date", return_value="2026-04-01"):
        rc = bcd.main(["--index", str(index)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Found 1 done task(s) without completed_date" in captured.out
    assert "FEAT-0001: 2026-04-01" in captured.out
    # Persisted to disk
    written = yaml.safe_load(index.read_text())
    by_id = {t["id"]: t for t in written["tasks"]}
    assert by_id["FEAT-0001"]["completed_date"] == "2026-04-01"
    # Already-dated task untouched
    assert by_id["FEAT-0002"]["completed_date"] == "2026-05-15"
    # Open task still open
    assert by_id["BUG-0001"]["status"] == "open"


def test_main_dry_run_does_not_write(tmp_path, capsys):
    index = _write_index(tmp_path)
    pre = index.read_text()
    with mock.patch.object(bcd, "find_completion_date", return_value="2026-03-03"):
        rc = bcd.main(["--index", str(index), "--dry-run"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "--dry-run: not writing" in captured.out
    assert index.read_text() == pre


def test_main_id_pattern_filters_eligible_tasks(tmp_path, capsys):
    """``--id-pattern`` restricts which IDs are considered."""
    # Add a second backfill candidate the pattern would exclude
    fixture = {
        **_INDEX_FIXTURE,
        "tasks": _INDEX_FIXTURE["tasks"] + [
            {
                "id": "TECH-0001",
                "title": "Another done task without date",
                "phase": 1,
                "status": "done",
                "effort": "Low",
                "user_action": False,
                "depends_on": [],
                "surfaced_by": [],
            },
        ],
    }
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    index = tasks_dir / "index.yml"
    with open(index, "w", encoding="utf-8") as f:
        yaml.safe_dump(fixture, f, sort_keys=False)

    calls = []
    def _fake_lookup(tid: str, src: str):
        calls.append(tid)
        return "2026-04-04"

    with mock.patch.object(bcd, "find_completion_date", side_effect=_fake_lookup):
        rc = bcd.main(["--index", str(index), "--id-pattern", r"^FEAT-"])
    assert rc == 0
    # Only FEAT-prefixed candidate was queried
    assert calls == ["FEAT-0001"]
    written = yaml.safe_load(index.read_text())
    by_id = {t["id"]: t for t in written["tasks"]}
    assert by_id["FEAT-0001"]["completed_date"] == "2026-04-04"
    assert "completed_date" not in by_id["TECH-0001"]


def test_main_reports_skipped_tasks_without_match(tmp_path, capsys):
    """find_completion_date → None leaves completed_date absent and reports as skipped."""
    index = _write_index(tmp_path)
    with mock.patch.object(bcd, "find_completion_date", return_value=None):
        rc = bcd.main(["--index", str(index)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "no match in git history" in captured.out
    assert "Skipped (no match): 1" in captured.out
    written = yaml.safe_load(index.read_text())
    by_id = {t["id"]: t for t in written["tasks"]}
    assert "completed_date" not in by_id["FEAT-0001"]


def test_main_returns_zero_when_no_tasks_need_backfill(tmp_path, capsys):
    fixture = {
        "schema_version": 1,
        "phases": [{"number": 1, "title": "P1", "status": "done"}],
        "tasks": [
            {
                "id": "FEAT-0010", "title": "All dated", "phase": 1,
                "status": "done", "completed_date": "2026-05-15",
                "effort": "Low", "user_action": False,
                "depends_on": [], "surfaced_by": [],
            },
        ],
    }
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    index = tasks_dir / "index.yml"
    with open(index, "w", encoding="utf-8") as f:
        yaml.safe_dump(fixture, f, sort_keys=False)
    with mock.patch.object(bcd, "find_completion_date") as m:
        rc = bcd.main(["--index", str(index)])
    assert rc == 0
    m.assert_not_called()
    captured = capsys.readouterr()
    assert "Found 0 done task(s) without completed_date" in captured.out


def test_main_missing_index_exits_1(tmp_path, capsys):
    rc = bcd.main(["--index", str(tmp_path / "nonexistent.yml")])
    assert rc == 1
    captured = capsys.readouterr()
    assert "ERROR: index not found" in captured.err


def test_main_unreadable_index_exits_1(tmp_path, capsys):
    index = tmp_path / "bad.yml"
    index.write_text(":\n  not valid: [\n", encoding="utf-8")  # malformed YAML
    rc = bcd.main(["--index", str(index)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "ERROR: cannot read" in captured.err


# === atomic write durability (Phase 108) ===================================


def test_main_write_leaves_no_tmp_file(tmp_path):
    """A successful write renames the tmp away — no `<index>.tmp` remains."""
    index = _write_index(tmp_path)
    with mock.patch.object(bcd, "find_completion_date", return_value="2026-04-01"):
        rc = bcd.main(["--index", str(index)])
    assert rc == 0
    assert not (index.parent / "index.yml.tmp").exists()


def test_main_write_failure_leaves_original_intact_and_cleans_tmp(tmp_path, capsys):
    """If the os.replace step fails mid-write, the atomic pattern leaves the
    original index untouched (no truncation) and cleans up the tmp file."""
    index = _write_index(tmp_path)
    original = index.read_text(encoding="utf-8")
    with mock.patch.object(bcd, "find_completion_date", return_value="2026-04-01"), \
         mock.patch.object(bcd.os, "replace", side_effect=OSError("disk full")):
        rc = bcd.main(["--index", str(index)])
    assert rc == 1
    # The staged write went to a tmp file that os.replace never swapped in, so
    # the original is byte-for-byte intact.
    assert index.read_text(encoding="utf-8") == original
    # Best-effort cleanup removed the tmp.
    assert not (index.parent / "index.yml.tmp").exists()
    assert "ERROR: cannot write" in capsys.readouterr().err


def test_main_reads_invalid_utf8_without_crashing(tmp_path, capsys):
    """`errors="replace"` on the read tolerates a stray non-UTF-8 byte in the
    index rather than raising an uncaught UnicodeDecodeError."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    index = tasks_dir / "index.yml"
    # Valid YAML whose title scalar carries a raw 0xFF byte (never valid UTF-8).
    index.write_bytes(
        b"schema_version: 1\n"
        b"phases:\n"
        b"- {number: 1, title: P1, status: done}\n"
        b"tasks:\n"
        b"- id: FEAT-0001\n"
        b'  title: "bad\xff byte"\n'
        b"  phase: 1\n"
        b"  status: done\n"
    )
    with mock.patch.object(bcd, "find_completion_date", return_value=None):
        rc = bcd.main(["--index", str(index)])
    # The read decoded with replacement instead of raising; the run finished.
    assert rc == 0
    assert "Found 1 done task(s) without completed_date" in capsys.readouterr().out
