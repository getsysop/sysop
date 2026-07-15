"""Tests for ``core/companion/scripts/archive_review_tasks.py``.

Sysop-original. No gdp counterpart; all tests in this file are Phase 48
originals.

Surface covered:

- ``_atomic_write_text`` — tmp + replace round-trip.
- ``parse_archivable_batches`` — round/batch boundaries, mixed-status
  rounds, ``all_merged`` flag, task counting, ``---`` separator handling,
  trailing-batch close.
- ``build_archive_block`` — `<details>` summary, separator placement
  between multiple rounds, trailing blank-line stripping.
- ``build_grand_total_row`` — batch-range derivation.
- ``update_archive_total`` — total math; missing row → ``(None, None)``.
- ``find_archive_insertion_point`` — header lookup.
- ``update_review_tasks`` — full-round vs partial-round removal, archive
  reference update, grand-total preservation of deferred TASK suffix.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

import archive_review_tasks as art


# === _atomic_write_text ====================================================


def test_atomic_write_text_writes_and_cleans_up_tmp(tmp_path):
    target = tmp_path / "out.txt"
    art._atomic_write_text(str(target), "hello\n")
    assert target.read_text(encoding="utf-8") == "hello\n"
    assert not (tmp_path / "out.txt.tmp").exists()


def test_atomic_write_text_overwrites_existing(tmp_path):
    target = tmp_path / "out.txt"
    target.write_text("old", encoding="utf-8")
    art._atomic_write_text(str(target), "new")
    assert target.read_text(encoding="utf-8") == "new"


# === parse_archivable_batches ==============================================


def _split(text: str) -> list[str]:
    return text.splitlines()


def test_parse_archivable_batches_collects_merged_batch():
    text = (
        "## Round 5 — 2026-05-01\n"
        "\n"
        "### Batch 100 — Helper rename `Merged`\n"
        "> **Branch:** `review/100`\n"
        "\n"
        "- [x] **TASK-001**: done\n"
        "- [x] **TASK-002**: done\n"
    )
    rounds = art.parse_archivable_batches(_split(text))
    assert len(rounds) == 1
    r = rounds[0]
    assert r["header"] == "## Round 5 — 2026-05-01"
    assert r["all_merged"] is True
    assert len(r["batches"]) == 1
    assert r["batches"][0]["task_count"] == 2


def test_parse_archivable_batches_handles_complete_status():
    """``Complete`` is treated equivalently to ``Merged``."""
    text = (
        "## Round 6\n"
        "\n"
        "### Batch 101 — Docs `Complete`\n"
        "\n"
        "- [x] **TASK-010**: done\n"
    )
    rounds = art.parse_archivable_batches(_split(text))
    assert len(rounds) == 1
    assert rounds[0]["batches"][0]["task_count"] == 1


def test_parse_archivable_batches_skips_pending_batches():
    """Mixed-status round: only merged batches collected; all_merged is False."""
    text = (
        "## Round 7\n"
        "\n"
        "### Batch 200 — Done `Merged`\n"
        "- [x] **TASK-100**: ok\n"
        "\n"
        "### Batch 201 — Pending `Pending`\n"
        "- [ ] **TASK-101**: nope\n"
    )
    rounds = art.parse_archivable_batches(_split(text))
    assert len(rounds) == 1
    r = rounds[0]
    assert r["all_merged"] is False
    assert len(r["batches"]) == 1
    assert "Batch 200" in r["batches"][0]["lines"][0]


def test_parse_archivable_batches_treats_dashed_separator_as_batch_close():
    text = (
        "## Round 8\n"
        "\n"
        "### Batch 300 — A `Merged`\n"
        "- [x] **TASK-200**: ok\n"
        "\n"
        "---\n"
        "\n"
        "### Batch 301 — B `Merged`\n"
        "- [x] **TASK-201**: ok\n"
    )
    rounds = art.parse_archivable_batches(_split(text))
    assert len(rounds) == 1
    assert len(rounds[0]["batches"]) == 2
    # The `---` row must not show up inside batch contents
    for b in rounds[0]["batches"]:
        assert all(line.strip() != "---" for line in b["lines"])


def test_parse_archivable_batches_closes_trailing_round_without_statistics():
    """A file that ends in a batch (no ``## Statistics``) must still close."""
    text = (
        "## Round 9\n"
        "### Batch 400 — Trailing `Merged`\n"
        "- [x] **TASK-400**: done\n"
    )
    rounds = art.parse_archivable_batches(_split(text))
    assert len(rounds) == 1
    assert rounds[0]["batches"][0]["task_count"] == 1


def test_parse_archivable_batches_closes_round_on_statistics_header():
    """A `## Statistics` header ends the current round; non-batch line is
    not treated as another round."""
    text = (
        "## Round 10\n"
        "### Batch 500 — One `Merged`\n"
        "- [x] **TASK-500**: ok\n"
        "## Statistics\n"
        "etc\n"
    )
    rounds = art.parse_archivable_batches(_split(text))
    assert len(rounds) == 1
    assert rounds[0]["end_line"] is not None
    # `## Statistics` itself must not appear inside the batch
    for b in rounds[0]["batches"]:
        assert all("Statistics" not in line for line in b["lines"])


def test_parse_archivable_batches_returns_empty_when_no_merged():
    text = (
        "## Round 11\n"
        "### Batch 600 — Still in flight `Pending`\n"
        "- [ ] **TASK-600**: nope\n"
    )
    assert art.parse_archivable_batches(_split(text)) == []


# === build_archive_block ===================================================


def test_build_archive_block_emits_details_summary_per_round():
    rounds = [{
        "header": "## Round 12 — 2026-05-02",
        "batches": [{
            "lines": ["### Batch 700 — X `Merged`", "- [x] **TASK-700**: a", ""],
            "task_count": 1,
        }],
    }]
    block = art.build_archive_block(rounds)
    assert "## Round 12 — 2026-05-02" in block
    assert "<details>" in block
    assert "</details>" in block
    assert "<summary>1/1 tasks completed</summary>" in block


def test_build_archive_block_inserts_separator_between_multiple_rounds():
    rounds = [
        {
            "header": "## Round A",
            "batches": [{
                "lines": ["### Batch 1 — A `Merged`", "- [x] **TASK-1**: ok"],
                "task_count": 1,
            }],
        },
        {
            "header": "## Round B",
            "batches": [{
                "lines": ["### Batch 2 — B `Merged`", "- [x] **TASK-2**: ok"],
                "task_count": 1,
            }],
        },
    ]
    block = art.build_archive_block(rounds)
    # Find the `---` separator between the two rounds
    a_idx = block.index("## Round A")
    b_idx = block.index("## Round B")
    assert a_idx < b_idx
    # Between A and B there must be exactly one `---` separator
    sep_indices = [i for i in range(a_idx, b_idx) if block[i] == "---"]
    assert sep_indices == [b_idx - 2]  # separator immediately precedes blank + B


def test_build_archive_block_strips_trailing_blank_lines_per_batch():
    rounds = [{
        "header": "## Round 13",
        "batches": [{
            "lines": [
                "### Batch 800 — X `Merged`",
                "- [x] **TASK-800**: ok",
                "",
                "",
                "",
            ],
            "task_count": 1,
        }],
    }]
    block = art.build_archive_block(rounds)
    # Find the batch start, ensure no run of >=2 blank lines inside
    start = block.index("### Batch 800 — X `Merged`")
    # The two lines following the batch should be: the task, then a single ""
    assert block[start + 1] == "- [x] **TASK-800**: ok"
    assert block[start + 2] == ""
    # The next line should be `</details>`, not another blank
    assert block[start + 3] == "</details>"


# === build_grand_total_row =================================================


def test_build_grand_total_row_renders_batch_range():
    rounds = [{
        "header": "## Round 14 — 2026-05-03",
        "batches": [
            {"lines": ["### Batch 50 — A `Merged`"], "task_count": 3},
            {"lines": ["### Batch 52 — B `Merged`"], "task_count": 1},
        ],
    }]
    rows = art.build_grand_total_row(rounds)
    assert len(rows) == 1
    assert "Round 14 (Batches 50-52)" in rows[0]
    assert "| 4 | 4 | 0 | Complete |" in rows[0]


def test_build_grand_total_row_falls_back_when_no_batch_numbers():
    rounds = [{
        "header": "## Round 15",
        "batches": [{"lines": ["No batch number here"], "task_count": 0}],
    }]
    rows = art.build_grand_total_row(rounds)
    assert rows[0].startswith("| Round 15 |")


# === update_archive_total ==================================================


def test_update_archive_total_bumps_totals():
    lines = [
        "| Some row    | 5    | 5    | 0   |     |",
        "| **Archive Total** | **100** | **95** | **5** |  |",
        "Other content",
    ]
    old, new = art.update_archive_total(lines, 10)
    assert old == 100
    assert new == 110
    assert "**110**" in lines[1]
    assert "**105**" in lines[1]
    # Deferred preserved
    assert "**5**" in lines[1]


def test_update_archive_total_returns_none_when_row_absent():
    lines = ["No archive total here"]
    assert art.update_archive_total(lines, 10) == (None, None)


# === find_archive_insertion_point ==========================================


def test_find_archive_insertion_point_returns_header_index():
    lines = ["intro", "", "## Grand Total (Archived)", "rest"]
    assert art.find_archive_insertion_point(lines) == 2


def test_find_archive_insertion_point_returns_none_when_missing():
    lines = ["nothing here", "or here"]
    assert art.find_archive_insertion_point(lines) is None


# === update_review_tasks ===================================================


def test_update_review_tasks_removes_full_round_lines():
    """`all_merged: True` → entire round range removed."""
    review = (
        "header\n"
        "## Round 99 — TO REMOVE\n"
        "### Batch 1 — gone `Merged`\n"
        "- [x] **TASK-1**: ok\n"
        "tail\n"
    )
    lines = review.splitlines()
    rounds = [{
        "header": "## Round 99 — TO REMOVE",
        "batches": [{
            "lines": ["### Batch 1 — gone `Merged`", "- [x] **TASK-1**: ok"],
            "task_count": 1,
            "start_line": 2,
            "end_line": 4,
        }],
        "start_line": 1,
        "end_line": 4,
        "all_merged": True,
    }]
    updated = art.update_review_tasks(lines, rounds, 100, 1, [1])
    joined = "\n".join(updated)
    assert "Round 99" not in joined
    assert "Batch 1" not in joined
    assert "header" in joined
    assert "tail" in joined


def test_update_review_tasks_removes_only_merged_batch_in_partial_round():
    """`all_merged: False` → only individual batch ranges removed."""
    review_lines = [
        "## Round 100",                        # 0
        "### Batch 2 — done `Merged`",         # 1
        "- [x] **TASK-2**: ok",                # 2
        "### Batch 3 — open `Pending`",        # 3
        "- [ ] **TASK-3**: nope",              # 4
    ]
    rounds = [{
        "header": "## Round 100",
        "batches": [{
            "lines": review_lines[1:3],
            "task_count": 1,
            "start_line": 1,
            "end_line": 3,
        }],
        "start_line": 0,
        "end_line": 5,
        "all_merged": False,
    }]
    updated = art.update_review_tasks(list(review_lines), rounds, 50, 1, [2])
    joined = "\n".join(updated)
    assert "Round 100" in joined         # round header preserved
    assert "Batch 2" not in joined        # merged batch gone
    assert "Batch 3" in joined            # pending batch preserved


def test_update_review_tasks_rewrites_archive_reference():
    review = (
        "> **Archive:** Rounds 1–5 (Batches 1–10) (50 tasks) are in "
        "[review_tasks_archive.md](review_tasks_archive.md).\n"
        "## Round 6 — TO REMOVE\n"
        "### Batch 11 — done `Merged`\n"
        "- [x] **TASK-X**: ok\n"
    )
    lines = review.splitlines()
    rounds = [{
        "header": "## Round 6 — TO REMOVE",
        "batches": [{
            "lines": ["### Batch 11 — done `Merged`", "- [x] **TASK-X**: ok"],
            "task_count": 1,
            "start_line": 2,
            "end_line": 4,
        }],
        "start_line": 1,
        "end_line": 4,
        "all_merged": True,
    }]
    updated = art.update_review_tasks(lines, rounds, 51, 1, [1, 11])
    archive_line = next(line for line in updated if "**Archive:**" in line)
    assert "Rounds 1–6" in archive_line
    assert "Batches 1–11" in archive_line
    assert "(51 tasks)" in archive_line


def test_update_review_tasks_preserves_deferred_task_suffix_on_grand_total():
    """Grand-total rewrite must preserve a trailing ``(TASK-184)`` suffix."""
    review = (
        "> **Grand Total (all rounds):** 100 tasks — 90 done, 8 open, "
        "2 deferred (TASK-184, TASK-200).\n"
        "tail\n"
    )
    lines = review.splitlines()
    updated = art.update_review_tasks(lines, [], 90, 0, [])
    gt = next(line for line in updated if "Grand Total" in line)
    assert "100 tasks" in gt
    assert "(TASK-184, TASK-200)" in gt


# === Convention fire ledger — archival integration (Phase 67, Tier 2) ========


_LEDGER_FIXTURE = (
    "# Code Review Tasks\n"
    "\n"
    "> **Archive:** Rounds 1–4 (Batches 1–20) (200 tasks) are in "
    "[review_tasks_archive.md](review_tasks_archive.md).\n"
    "\n"
    "> **Grand Total (all rounds):** 210 tasks — 205 done, 5 open, 0 deferred.\n"
    "\n"
    "## Round 5 (2026-06-26) — Code Quality Review\n"
    "\n"
    "### Batch 21 — Helper rename `Merged`\n"
    "> **Branch:** `review/21`\n"
    "\n"
    "- [x] **TASK-201**: done\n"
    "- [x] **TASK-202**: done\n"
    "\n"
    "## Statistics\n"
    "\n"
    "| Round | Tasks |\n"
    "|-------|-------|\n"
    "| 5 | 2 |\n"
    "\n"
    "## Convention fire ledger\n"
    "\n"
    "> Per-rule stale-verdicts from review-round triage (Step 2b).\n"
    "\n"
    "| Round | Rule ID | Mechanism | Verdict | Why (the change event) |\n"
    "|-------|---------|-----------|---------|------------------------|\n"
    "| 5 | `sql-fstring` | checks.yml | stale | param'd-query migration mooted it |\n"
)


def test_archive_leaves_convention_fire_ledger_in_place():
    """Phase 67 (Tier 2): the ``## Convention fire ledger`` section sits
    *outside* every ``## Round`` block, so a fully-merged round archiving away
    must neither move nor drop it. Locks the Step 5e / Step 9b placement
    contract — the ledger is the demotion gate's durable record, and silently
    archiving it away (``build_archive_block`` only copies header + batches)
    or deleting it with the round range would be data loss.

    Uses the realistic bottom-of-file layout: ``## Round`` → ``## Statistics``
    → ``## Convention fire ledger``, so the round range stops at the first
    following ``## `` section and both trailing sections survive.
    """
    lines = _LEDGER_FIXTURE.splitlines()
    rounds = art.parse_archivable_batches(lines)

    # The merged round is archivable, and its range stops AT the first ``## ``
    # section after it (``## Statistics``) — so neither Statistics nor the
    # ledger below it is ever inside the removed range.
    assert len(rounds) == 1
    r = rounds[0]
    assert r["all_merged"] is True
    assert r["end_line"] == lines.index("## Statistics")

    # Neither trailing section is carried into the archive block (build copies
    # only the round header + batch line-ranges), while the batch content IS.
    archive_block = "\n".join(art.build_archive_block(rounds))
    assert "Convention fire ledger" not in archive_block
    assert "## Statistics" not in archive_block
    assert "TASK-201" in archive_block

    # After the rewrite, the ledger header AND its rows (and the Statistics
    # section) survive in review_tasks.md, and the archived round is gone.
    updated = "\n".join(art.update_review_tasks(lines, rounds, 202, 2, [21]))
    assert "## Convention fire ledger" in updated
    assert "`sql-fstring`" in updated
    assert "## Statistics" in updated
    assert "## Round 5" not in updated
    assert "TASK-201" not in updated


# === _atomic_write_pair (Phase 108) ========================================


def test_atomic_write_pair_writes_both_and_cleans_up_tmp(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    art._atomic_write_pair(str(a), "alpha\n", str(b), "beta\n")
    assert a.read_text(encoding="utf-8") == "alpha\n"
    assert b.read_text(encoding="utf-8") == "beta\n"
    # Both tmp files were renamed away, not left behind.
    assert not (tmp_path / "a.txt.tmp").exists()
    assert not (tmp_path / "b.txt.tmp").exists()


def test_atomic_write_pair_overwrites_existing(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("old-a", encoding="utf-8")
    b.write_text("old-b", encoding="utf-8")
    art._atomic_write_pair(str(a), "new-a", str(b), "new-b")
    assert a.read_text(encoding="utf-8") == "new-a"
    assert b.read_text(encoding="utf-8") == "new-b"


def test_atomic_write_pair_cleans_up_tmp_on_replace_failure(tmp_path, monkeypatch):
    """If os.replace fails, both originals stay intact AND no `.tmp` is
    orphaned — an untracked `review_tasks*.md.tmp` at the repo root would
    otherwise trip /review-close Step 1a dirty-classification."""
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("old-a", encoding="utf-8")
    b.write_text("old-b", encoding="utf-8")

    def _boom(*_args, **_kw):
        raise OSError("replace failed")

    monkeypatch.setattr(art.os, "replace", _boom)
    with pytest.raises(OSError):
        art._atomic_write_pair(str(a), "new-a", str(b), "new-b")

    # Neither replace succeeded, so both originals are untouched...
    assert a.read_text(encoding="utf-8") == "old-a"
    assert b.read_text(encoding="utf-8") == "old-b"
    # ...and both staged tmp files were cleaned up, not orphaned.
    assert not (tmp_path / "a.txt.tmp").exists()
    assert not (tmp_path / "b.txt.tmp").exists()


# === repo-root path resolution (Phase 108) =================================


def test_review_and_archive_files_resolve_to_repo_root_not_cwd():
    """Paths anchor to <repo-root>/ (the parent of scripts/), never the
    caller's CWD — a bare relative path would open against whatever dir the
    invoker happened to be in (a worktree subdir, etc.)."""
    root = Path(str(art.__file__)).resolve().parent.parent
    assert os.path.isabs(art.REVIEW_FILE)
    assert os.path.isabs(art.ARCHIVE_FILE)
    assert art.REVIEW_FILE == str(root / "review_tasks.md")
    assert art.ARCHIVE_FILE == str(root / "review_tasks_archive.md")


# === update_archive_total — defensive parsing (Phase 108) ==================


def test_update_archive_total_skips_row_with_too_few_cells(capsys):
    """A hand-edited row with <5 pipe-delimited cells must not IndexError on
    parts[4]; it returns (None, None) with a warning and leaves the row.

    Row has 4 split-parts ('', ' **Archive Total** ', ' 100 ', ' 95') — the
    deferred cell (parts[4]) is missing, which the un-guarded code would
    index into.
    """
    lines = ["| **Archive Total** | 100 | 95"]
    assert art.update_archive_total(lines, 10) == (None, None)
    assert lines[0] == "| **Archive Total** | 100 | 95"  # untouched
    assert "expected >=5" in capsys.readouterr().err


def test_update_archive_total_skips_row_with_nonnumeric_cells(capsys):
    """A row with enough cells but a non-numeric total must not AttributeError
    on re.search(...).group(); it returns (None, None) with a warning."""
    lines = ["| **Archive Total** | **N/A** | **95** | **5** | |"]
    assert art.update_archive_total(lines, 10) == (None, None)
    assert "**N/A**" in lines[0]  # untouched
    assert "missing numeric cells" in capsys.readouterr().err


# === main() — end-to-end archive via _atomic_write_pair (Phase 108) ========


def _archive_scratch(tmp_path, monkeypatch, rebuild=lambda: None):
    """Set up a scratch review/archive pair + wire main()'s globals, argv,
    input(), and the shadow-index rebuild. Returns (review_path, archive_path).
    """
    review = tmp_path / "review_tasks.md"
    archive = tmp_path / "review_tasks_archive.md"
    review.write_text(
        "# Code Review Tasks\n"
        "\n"
        "> **Archive:** Rounds 1–4 (Batches 1–20) (200 tasks) are in "
        "[review_tasks_archive.md](review_tasks_archive.md).\n"
        "\n"
        "> **Grand Total (all rounds):** 202 tasks — 202 done, 0 open, "
        "0 deferred.\n"
        "\n"
        "## Round 5 (2026-07-15) — Code Quality Review\n"
        "\n"
        "### Batch 21 — Helper rename `Merged`\n"
        "> **Branch:** `review/21`\n"
        "\n"
        "- [x] **TASK-201**: done\n"
        "- [x] **TASK-202**: done\n"
        "\n"
        "## Statistics\n"
        "\n"
        "text\n",
        encoding="utf-8",
    )
    archive.write_text(
        "# Review Tasks Archive\n"
        "\n"
        "## Grand Total (Archived)\n"
        "\n"
        "| Round | Total | Done | Deferred | Status |\n"
        "|-------|-------|------|----------|--------|\n"
        "| **Archive Total** | **200** | **200** | **0** | |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(art, "REVIEW_FILE", str(review))
    monkeypatch.setattr(art, "ARCHIVE_FILE", str(archive))
    monkeypatch.setattr(sys, "argv", ["archive_review_tasks.py"])
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    import review_index
    monkeypatch.setattr(review_index, "rebuild_index", rebuild)
    return review, archive


def test_main_archives_round_via_atomic_pair(tmp_path, monkeypatch):
    """A fully-merged round moves out of review_tasks.md into
    review_tasks_archive.md via _atomic_write_pair, leaving no .tmp files.
    Locks the Phase-108 main() reorder + pair write."""
    review, archive = _archive_scratch(tmp_path, monkeypatch)

    art.main()

    review_after = review.read_text(encoding="utf-8")
    archive_after = archive.read_text(encoding="utf-8")
    # Round moved OUT of review...
    assert "## Round 5" not in review_after
    assert "TASK-201" not in review_after
    assert "## Statistics" in review_after       # trailing section preserved
    # ...and INTO the archive, with the Archive Total bumped by 2 tasks.
    assert "TASK-201" in archive_after
    assert "Batch 21" in archive_after
    assert "**202**" in archive_after
    # No leftover tmp files from the atomic pair.
    assert not (tmp_path / "review_tasks.md.tmp").exists()
    assert not (tmp_path / "review_tasks_archive.md.tmp").exists()


def test_main_rebuild_failure_is_non_fatal(tmp_path, monkeypatch, capsys):
    """A rebuild_index() failure runs AFTER the durable writes, so it must
    degrade to a printed note — never a traceback that makes a successful
    archive look failed. (Regression guard: a narrowed `except ImportError`
    would let a review_index FileNotFoundError crash the run.)"""
    def _boom():
        raise FileNotFoundError("review_tasks.md not where review_index looked")

    review, archive = _archive_scratch(tmp_path, monkeypatch, rebuild=_boom)

    art.main()  # must NOT raise

    # The atomic writes still landed despite the post-write rebuild blowing up.
    assert "TASK-201" in archive.read_text(encoding="utf-8")
    assert "## Round 5" not in review.read_text(encoding="utf-8")
    # And the failure is reported (not silent), not raised.
    assert "Non-fatal: index rebuild failed" in capsys.readouterr().out


def test_main_malformed_archive_total_degrades_without_none_in_file(
    tmp_path, monkeypatch, capsys
):
    """A malformed Archive Total row must not crash main() (the defensive
    guard) AND must not write a literal '(None tasks)' into review_tasks.md —
    the prior count is preserved while the rounds/batches range still advances."""
    review = tmp_path / "review_tasks.md"
    archive = tmp_path / "review_tasks_archive.md"
    review.write_text(
        "# Code Review Tasks\n\n"
        "> **Archive:** Rounds 1–4 (Batches 1–20) (200 tasks) are in "
        "[review_tasks_archive.md](review_tasks_archive.md).\n\n"
        "## Round 5 (2026-07-15) — Code Quality Review\n\n"
        "### Batch 21 — Helper rename `Merged`\n\n"
        "- [x] **TASK-201**: done\n\n"
        "## Statistics\n\ntext\n",
        encoding="utf-8",
    )
    # Archive Total row has enough cells but a non-numeric total → the
    # update_archive_total numeric guard returns (None, None) without crashing.
    archive.write_text(
        "# Review Tasks Archive\n\n## Grand Total (Archived)\n\n"
        "| Round | Total | Done | Deferred | Status |\n"
        "|-------|-------|------|----------|--------|\n"
        "| **Archive Total** | **N/A** | **oops** | **?** | |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(art, "REVIEW_FILE", str(review))
    monkeypatch.setattr(art, "ARCHIVE_FILE", str(archive))
    monkeypatch.setattr(sys, "argv", ["archive_review_tasks.py"])
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    import review_index
    monkeypatch.setattr(review_index, "rebuild_index", lambda: None)

    art.main()  # must NOT raise despite the malformed total row

    review_after = review.read_text(encoding="utf-8")
    # The round is still archived (a malformed TOTAL doesn't block archival)...
    assert "TASK-201" in archive.read_text(encoding="utf-8")
    assert "## Round 5" not in review_after
    # ...and the archive-reference line preserves the prior count, never "None".
    ref = next(ln for ln in review_after.splitlines() if "**Archive:**" in ln)
    assert "None" not in ref
    assert "(200 tasks)" in ref
    # The malformed row was reported on stderr.
    assert "missing numeric cells" in capsys.readouterr().err
