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

import pytest
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


def _stray_files(index):
    """Everything in the index's directory that is not the index itself.

    Asserting `not (parent / "index.yml.tmp").exists()` was the shape before
    Phase 271, and under `mkstemp` (`Q-442`) it is VACUOUS: the fixed name can
    no longer be produced, so the assertion is true whether or not a temp leaked.
    A directory census cannot go vacuous that way — it names whatever was left,
    under whatever random suffix.
    """
    return sorted(p.name for p in index.parent.iterdir() if p.name != index.name)


def test_main_write_leaves_no_tmp_file(tmp_path):
    """A successful write renames the tmp away — nothing else is left behind."""
    index = _write_index(tmp_path)
    with mock.patch.object(bcd, "find_completion_date", return_value="2026-04-01"):
        rc = bcd.main(["--index", str(index)])
    assert rc == 0
    assert _stray_files(index) == [], (
        "the mkstemp temp file survived a successful write — under a fixed name a "
        "leak self-healed on the next run, under mkstemp every run leaks a new one"
    )
    # Non-vacuity: the census must be able to SEE a stray, or the assertion above
    # is a statement about an empty search.
    (index.parent / "index.yml.decoy").write_text("x", encoding="utf-8")
    assert _stray_files(index) == ["index.yml.decoy"]


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
    # Best-effort cleanup removed the tmp — by census, not by fixed name, which
    # `mkstemp` made unobservable (`Q-442`, Phase 271).
    assert _stray_files(index) == [], (
        "os.replace failed and the mkstemp temp file was left behind"
    )
    assert "ERROR: cannot write" in capsys.readouterr().err


def test_main_non_oserror_write_failure_also_cleans_the_tmp(tmp_path):
    """The arm the conversion OWED, and the reason it is not `except OSError` alone.

    Under the pre-Phase-271 fixed name a leaked temp self-healed: the next run
    wrote `<index>.tmp` again. Under `mkstemp` it does not — every failed run
    leaks a new uniquely-named file into `tasks/`. `yaml.safe_dump` raises
    `RepresenterError`, which is not an `OSError`, so the OSError arm alone
    would not have reached it.
    """
    index = _write_index(tmp_path)
    boom = RuntimeError("representer exploded")
    with mock.patch.object(bcd, "find_completion_date", return_value="2026-04-01"), \
         mock.patch.object(bcd.yaml, "safe_dump", side_effect=boom):
        with pytest.raises(RuntimeError):
            bcd.main(["--index", str(index)])
    assert _stray_files(index) == [], (
        "a non-OSError failure leaked a mkstemp temp file — the cleanup arm is missing "
        "or no longer reaches this path"
    )


def test_a_keyboard_interrupt_also_cleans_the_tmp(tmp_path):
    """The arm must be `BaseException`, not `Exception`, and this is the only test
    that can tell them apart.

    A review battery widened `except BaseException` to `except Exception` and the
    sibling test above stayed green — because it raises `RuntimeError`, which IS
    an `Exception`. `KeyboardInterrupt` and `SystemExit` are not, and a Ctrl-C
    mid-write is exactly when a leaked temp is least likely to be noticed.
    """
    index = _write_index(tmp_path)
    with mock.patch.object(bcd, "find_completion_date", return_value="2026-04-01"), \
         mock.patch.object(bcd.yaml, "safe_dump", side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            bcd.main(["--index", str(index)])
    assert _stray_files(index) == [], (
        "a KeyboardInterrupt leaked a mkstemp temp file — the cleanup arm is narrower "
        "than BaseException"
    )


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


# ── the four elements the conversion owed (`Q-442`, Phase 271) ──────────────
#
# An independent review battery dropped `os.chmod`, `dir=`, `realpath` and
# widened `except BaseException` to `except Exception`, and ALL FOUR survived
# this module: it had no `chmod`, `st_mode` or symlink assertion anywhere. The
# phase's own record calls these elements load-bearing, so they are asserted by
# BEHAVIOUR here rather than described in a comment.

def _write_index_in(d):
    d.mkdir(parents=True, exist_ok=True)
    return _write_index(d)


def test_the_index_mode_is_carried_across_the_rewrite(tmp_path):
    """`mkstemp` creates 0600. Without the carry a 0644 index is silently
    narrowed — and git does not track the bit, so nothing downstream surfaces it."""
    index = _write_index(tmp_path)
    index.chmod(0o644)
    with mock.patch.object(bcd, "find_completion_date", return_value="2026-04-01"):
        assert bcd.main(["--index", str(index)]) == 0
    assert index.stat().st_mode & 0o777 == 0o644, (
        "the file mode was not carried across the temp file — mkstemp's 0600 won"
    )
    # A non-default mode too, so the assertion is not satisfied by a `0o644`
    # literal. **On a FRESH index**, because the second run over the same file is
    # a no-op: run 1 sets `completed_date`, so run 2 reports "Found 0 done task(s)"
    # and never writes — the 0o664 then survives because nothing touched it. A
    # review battery measured that directly; the arm asserted nothing.
    index2 = _write_index_in(tmp_path / "second")
    index2.chmod(0o664)
    with mock.patch.object(bcd, "find_completion_date", return_value="2026-04-02"):
        assert bcd.main(["--index", str(index2)]) == 0
    assert "2026-04-02" in index2.read_text(encoding="utf-8"), (
        "the second fixture was not actually rewritten, so the mode assertion below "
        "would pass over a file nothing touched"
    )
    assert index2.stat().st_mode & 0o777 == 0o664, (
        "the mode is hard-coded rather than read from the target"
    )


def test_a_symlinked_index_is_written_through_not_replaced(tmp_path):
    """`realpath`: without it `os.replace` swaps the LINK for a regular file and
    leaves the canonical target stale while the script reports success."""
    real = tmp_path / "canonical.yml"
    index = _write_index(tmp_path)
    index.rename(real)
    index.symlink_to(real)
    with mock.patch.object(bcd, "find_completion_date", return_value="2026-04-01"):
        assert bcd.main(["--index", str(index)]) == 0
    assert index.is_symlink(), "the symlink was replaced by a regular file"
    assert "2026-04-01" in real.read_text(encoding="utf-8"), (
        "the canonical target was not updated — the write went to the link"
    )


def test_the_temp_file_is_created_beside_the_target(tmp_path):
    """`dir=`: a temp in the system temp dir makes `os.replace` raise EXDEV across
    filesystems. Asserted by observing WHERE the temp is created, since the
    failure only reproduces on a real cross-device layout.

    **Through a symlink whose target lives in a DIFFERENT directory**, which is
    what makes the assertion discriminating. The first version put the link and
    its target in one directory, so `dirname(real)` and `dirname(index)` were the
    same string and a battery swapped one for the other with the test green — the
    fixture could not tell the two apart, which is the whole property.
    """
    canon_dir = tmp_path / "canonical"
    canon_dir.mkdir()
    index = _write_index(tmp_path)
    real = canon_dir / "canonical.yml"
    index.rename(real)
    index.symlink_to(real)
    seen = {}
    real_mkstemp = bcd.tempfile.mkstemp

    def spy(*a, **kw):
        seen["dir"] = kw.get("dir")
        return real_mkstemp(*a, **kw)

    with mock.patch.object(bcd, "find_completion_date", return_value="2026-04-01"), \
         mock.patch.object(bcd.tempfile, "mkstemp", side_effect=spy):
        assert bcd.main(["--index", str(index)]) == 0
    assert seen.get("dir") == str(real.parent), (
        f"mkstemp was given dir={seen.get('dir')!r}, not the RESOLVED target's own "
        f"directory ({str(real.parent)!r}) — os.replace can then cross a filesystem "
        "boundary and raise EXDEV. Note this must be the symlink TARGET's directory, "
        "not the link's."
    )
