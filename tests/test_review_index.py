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


# === `--list` states its own verdict (`Q-371`) ==============================
#
# The reported defect: `review_index.py --list` prints zero bytes and exits 0
# on a batch-free tracker, so the command `/review-close` Step 4b names as
# authoritative cannot distinguish *ran, found no batches* from *did not run*.
# Three states shared that silence — a genuinely empty tracker, a tracker whose
# headers the strict pattern rejects, and a run that never happened. The
# reporter had the correct verdict and could only establish it by running two
# cross-checks the skill does not prescribe.
#
# This is the repo's own § Report-and-exit integrity shape, closed for
# `claimable?` in Phase 191 and for the pre-scan taxonomy in Phase 135.

import subprocess  # noqa: E402
import sys  # noqa: E402

_SCRIPT = Path(__file__).resolve().parents[1] / "core/companion/scripts/review_index.py"


def _list(root: Path, tasks: str):
    """Drive the real script in a scratch repo.

    The script resolves `REPO_ROOT` by walking up from **its own file** to the
    nearest `.git`, not from the CWD, so it has to be copied into the scratch
    tree — running it in place would read this repo's own `review_tasks.md`.
    That is the same resolution `sysop/scripts/` gets in a real install.
    """
    import shutil

    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    scripts = root / "sysop" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_SCRIPT, scripts / _SCRIPT.name)
    (root / "review_tasks.md").write_text(tasks, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(scripts / _SCRIPT.name), "--list"],
        cwd=str(root), capture_output=True, text=True,
    )


def test_empty_tracker_states_that_it_ran(tmp_path):
    """Exit 0 and no rows is now a POSITIVE statement, not a silence."""
    r = _list(tmp_path, "# Review Tasks\n\n## Statistics\n")
    assert r.returncode == 0
    assert r.stdout == "", "stdout must stay byte-identical for machine consumers"
    assert "review_index --list: read review_tasks.md" in r.stderr
    assert "0 batches listed" in r.stderr


def test_the_verdict_names_what_it_read(tmp_path):
    """The line carries the file and its size, so a wrong-tracker read is visible.

    A run against a 4-line stub and a run against a 400-line tracker both
    printing `0 batches` are different events, and only the size distinguishes
    them without a second command.
    """
    r = _list(tmp_path, "# Review Tasks\n\n## Statistics\n")
    assert "(3 lines)" in r.stderr, r.stderr


def test_a_populated_tracker_also_states_its_count(tmp_path):
    """Not an empty-only special case — every run accounts for itself."""
    r = _list(tmp_path, _TASKS_FIXTURE)
    assert r.returncode == 0
    assert r.stdout.count("\n") == 3, r.stdout
    assert "3 batches listed" in r.stderr


def test_singular_is_not_reported_as_plural(tmp_path):
    tasks = "# Review Tasks\n\n### Batch 5 — only one `Pending`\n\n- [ ] t\n"
    r = _list(tmp_path, tasks)
    assert "1 batch listed" in r.stderr, r.stderr


def test_a_header_the_strict_pattern_rejects_is_warned_about(tmp_path):
    """The third state the exit code cannot see.

    A `### Batch` line the parser cannot read is reported by nothing: no row,
    no error, exit 0 — so the tracker plainly declares a batch and the list is
    silently short. Step 4b then takes its empty arm and the batch is never
    closed, its tasks and lock left behind, while the step reports success.
    """
    tasks = (
        "# Review Tasks\n"
        "\n"
        "###  Batch 4  — two spaces after ### `Pending`\n"
        "\n"
        "- [ ] t\n"
    )
    r = _list(tmp_path, tasks)
    assert r.returncode == 0
    assert r.stdout == ""
    assert "WARNING:" in r.stderr
    assert "review_tasks.md:3" in r.stderr
    assert "0 batches listed" in r.stderr


def test_a_batch_header_inside_a_balanced_fence_is_not_warned_about(tmp_path):
    """Documentation is not tracker content.

    `WORKFLOW.md` and this repo's own tracker both carry fenced examples of the
    header shape. Warning on them would train the operator to ignore the
    warning, which is the failure `Q-366` describes one module over.
    """
    tasks = (
        "# Review Tasks\n"
        "\n"
        "```\n"
        "###  Batch 9  — an example of the WRONG shape `Pending`\n"
        "```\n"
    )
    r = _list(tmp_path, tasks)
    assert "WARNING:" not in r.stderr, r.stderr
    assert "0 batches listed" in r.stderr


def test_a_readable_header_produces_no_warning(tmp_path):
    """Vacuity floor: the warning must not fire on the canonical shape."""
    r = _list(tmp_path, _TASKS_FIXTURE)
    assert "WARNING:" not in r.stderr, r.stderr


def test_a_near_miss_header_is_a_NOTE_when_batches_were_listed(tmp_path):
    """`WARNING:` only when the list is empty (`Q-371`, corrected by its round).

    `/review-close` Step 4b halts on any `WARNING:`. A near-miss header is a
    spelling this repo tolerates elsewhere on purpose — `close_batch.sh` closes
    such a batch anyway through the permissive twin and says so at its own site
    — so warning unconditionally turned one legacy header into a permanent halt
    on every future close of unrelated work.
    """
    tasks = (
        "# Review Tasks\n\n"
        "### Batch 3 - legacy ascii hyphen `Merged`\n\n- [x] t\n\n"
        "### Batch 5 — a good one `Pending`\n\n- [ ] t\n"
    )
    r = _list(tmp_path, tasks)
    assert r.returncode == 0
    assert "1 batch listed" in r.stderr
    assert "NOTE:" in r.stderr, r.stderr
    assert "WARNING:" not in r.stderr, r.stderr


def test_a_near_miss_header_is_a_WARNING_when_nothing_was_listed(tmp_path):
    """Zero rows plus a visible header is the unambiguous false-empty.

    Step 4b must not take its empty arm here, so this one does halt.
    """
    tasks = "# Review Tasks\n\n### Batch 3 - legacy ascii hyphen `Pending`\n\n- [ ] t\n"
    r = _list(tmp_path, tasks)
    assert r.returncode == 0
    assert r.stdout == ""
    assert "WARNING:" in r.stderr, r.stderr
    assert "0 batches listed" in r.stderr


def test_the_verdict_prints_after_the_rows_when_streams_are_merged(tmp_path):
    """`sys.stdout.flush()` before the stderr verdict is load-bearing (`Q-371`).

    `/review-close` Step 4b captures both streams (`2>&1` is how the step runs
    it), and without the flush Python's block-buffered stdout lands AFTER the
    unbuffered stderr — so the operator reads a verdict, then the rows it is
    supposed to be summarising. Removing the flush survived Phase 251's first
    guard set because every assertion was a substring test.
    """
    import shutil
    root = tmp_path
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    scripts = root / "sysop" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(_SCRIPT, scripts / _SCRIPT.name)
    (root / "review_tasks.md").write_text(_TASKS_FIXTURE, encoding="utf-8")

    merged = subprocess.run(
        f"{sys.executable} {scripts / _SCRIPT.name} --list 2>&1",
        cwd=str(root), shell=True, capture_output=True, text=True,
    ).stdout

    rows_at = merged.index("Helper rename")
    verdict_at = merged.index("review_index --list: read")
    assert rows_at < verdict_at, (
        "the verdict printed before the rows it summarises:\n" + merged
    )
