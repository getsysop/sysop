"""The round-yield ledger keeps pace with the phase log — Phase 174.

Phase 166 filed the ledger as the prerequisite for tuning the reviewer count on data;
Phase 174 instituted it. Its failure mode is quiet lapse: rows are appended by convention
at phase close, and a convention with no guard is how the reviewer count itself crept
1 -> 2 -> 3 -> 4 unchosen (Phase 166's measurement). So this module asserts the pace-keeping
mechanically: every numeric phase row CLAUDE.md's Phase log table gains from 174 onward must
have a ledger row (a recorded skip is a row too, by the ledger's own convention).

Both files are maintainer-side and excluded from the public mirror, so every test here
skips — explicitly, stating the reason — when either is absent (the Phase 160 lesson: a
sterilized-tree FileNotFoundError reads as a defect and goes red on the public CI).
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER = REPO_ROOT / "tools" / "ROUND_YIELD_LEDGER.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

# Rows before this are deliberate backfill; rows from here on are the convention binding.
LEDGER_BINDS_FROM = 174


def _ledger() -> str:
    if not LEDGER.is_file():
        pytest.skip(
            "tools/ROUND_YIELD_LEDGER.md is maintainer-side and excluded from the public "
            "mirror; the ledger guards only apply in the source repo"
        )
    return LEDGER.read_text(encoding="utf-8")


def _claude_md() -> str:
    if not CLAUDE_MD.is_file():
        pytest.skip(
            "CLAUDE.md is maintainer-side and excluded from the public mirror; the ledger "
            "pace-keeping guard only applies in the source repo"
        )
    return CLAUDE_MD.read_text(encoding="utf-8")


def ledger_phase_rows(ledger: str) -> set[int]:
    """Phase numbers with a row in the ledger's schema table.

    Scoped to the segment between the `| Phase |` header row and the next `## ` heading —
    the author-side battery satisfied an unscoped parse with a stray `| 174 |` row pasted
    into the notes, which is rule 1's "where it looks" class aimed at this parser.
    """
    m = re.search(r"(?m)^\|\s*Phase\s*\|", ledger)
    if not m:
        return set()
    end = ledger.find("\n## ", m.end())
    table = ledger[m.start():end if end != -1 else len(ledger)]
    return {int(g.group(1)) for g in re.finditer(r"(?m)^\|\s*(\d+)\s*\|", table)}


def claude_md_phase_numbers(claude_md: str) -> set[int]:
    """Numeric phases in the Phase log table (rename rows and letter-suffixed phases like
    159a are recorded prose-side; the ledger keys on the numeric rows it can parse)."""
    m = re.search(r"^##\s+Phase log\s*$", claude_md, re.M)
    assert m, "the Phase log heading is gone from CLAUDE.md; this guard's anchor needs revisiting"
    table = claude_md[m.start():]
    return {int(g.group(1)) for g in re.finditer(r"(?m)^\|\s*(\d+)\s", table)}


def missing_ledger_rows(claude_md: str, ledger: str) -> list[int]:
    phases = {n for n in claude_md_phase_numbers(claude_md) if n >= LEDGER_BINDS_FROM}
    return sorted(phases - ledger_phase_rows(ledger))


def schema_problems(ledger: str) -> list[str]:
    """Refactored to a testable function — the round's guards lens emptied the original
    test's column loop and nothing went red, the vacuity class this repo keeps re-finding."""
    problems = []
    for col in ("Author battery", "Independent battery", "Sub-agent tokens", "Filed / latent"):
        if col not in ledger:
            problems.append(f"the ledger lost its {col!r} column — the comparison it exists for is gone")
    if "every adversarial round appends one row" not in ledger:
        problems.append(
            "the ledger no longer states the appends-one-row convention as a requirement — "
            "'may append' is the lapse the pace-keeping guard cannot see from a row count"
        )
    if "a recorded skip appends a row too" not in ledger:
        problems.append(
            "the ledger no longer states the skip-rows-too convention, so a skipped round "
            "becomes indistinguishable from a lapsed ledger"
        )
    return problems


def row_problems(ledger: str) -> list[str]:
    """Rows in the binding range must be finalized — the round's guards lens emptied the
    174 row's cells (and set every cell `n/a`) with the pace-keeping guard green, because
    that guard counts rows, not content. A skip row (second cell starting `skip`) is exempt
    beyond the cell-count: its remaining cells are `n/a` by the ledger's own convention."""
    problems = []
    m = re.search(r"(?m)^\|\s*Phase\s*\|", ledger)
    if not m:
        return ["the ledger's schema table header is gone"]
    end = ledger.find("\n## ", m.end())
    table = ledger[m.start():end if end != -1 else len(ledger)]
    for row in re.finditer(r"(?m)^\|\s*(\d+)\s*\|(.*)$", table):
        n = int(row.group(1))
        if n < LEDGER_BINDS_FROM:
            continue
        cells = [c.strip() for c in row.group(2).rstrip("|").split("|")]
        if len(cells) < 7:
            problems.append(f"row {n} has {len(cells)} cells against a 7-column body")
            continue
        if cells[0].lower().startswith("skip"):
            continue
        empties = [i for i, c in enumerate(cells) if not c]
        if empties:
            problems.append(f"row {n} has empty cells at positions {empties}")
        drafts = [c for c in cells if re.search(r"\b(?:pending|provisional|tbd)\b", c, re.I)]
        if drafts:
            problems.append(f"row {n} still carries draft cells {drafts} — finalize before closing the phase")
    return problems


def test_the_ledger_has_its_schema():
    assert schema_problems(_ledger()) == []


def test_the_schema_check_is_not_vacuous():
    broken = _ledger().replace("Author battery", "Battery A").replace(
        "every adversarial round appends one row", "every adversarial round may append one row")
    problems = schema_problems(broken)
    assert any("Author battery" in p for p in problems), problems
    assert any("may append" in p for p in problems), problems


def test_binding_rows_are_finalized():
    assert row_problems(_ledger()) == []


def test_the_finalization_check_is_not_vacuous():
    ledger = _ledger()
    row = re.search(r"(?m)^\|\s*174\s*\|.*$", ledger)
    assert row, "no 174 row to exercise the check against"
    hollowed = ledger.replace(row.group(0), "| 174 | | | | | | | |", 1)
    assert any("174" in p for p in row_problems(hollowed)), row_problems(hollowed)
    drafted = ledger.replace(row.group(0), "| 174 | 3 × 1 | yes | pending | pending | pending | pending | pending |", 1)
    assert any("draft" in p for p in row_problems(drafted)), row_problems(drafted)


def test_the_backfill_is_present():
    """Deleting the 161-173 backfill would leave a schema with no evidence base."""
    rows = ledger_phase_rows(_ledger())
    missing = [n for n in range(161, 174) if n not in rows]
    assert missing == [], f"backfill rows missing from the ledger: {missing}"


def test_every_phase_from_174_has_a_ledger_row():
    missing = missing_ledger_rows(_claude_md(), _ledger())
    assert missing == [], (
        f"phases {missing} closed (they have CLAUDE.md Phase log rows) without a "
        "round-yield ledger row — append one per round, or a skip row with its reason, "
        "before closing the phase"
    )


def test_a_stray_row_outside_the_schema_table_does_not_count():
    """B6 from Phase 174's author-side battery, kept as a permanent regression."""
    ledger = _ledger()
    stripped = re.sub(r"(?m)^\|\s*174\s*\|.*\n", "", ledger)
    assert 174 not in ledger_phase_rows(stripped)
    strayed = stripped + "\n\nStray note:\n\n| 174 | not really a row |\n"
    assert 174 not in ledger_phase_rows(strayed), (
        "a phase-numbered table row pasted outside the schema table satisfies the "
        "pace-keeping guard — the parser is reading the whole file again"
    )


def test_the_pace_keeping_guard_is_not_vacuous():
    """A fabricated future phase must be reported missing — otherwise the guard passes
    because it is reading nothing."""
    claude_md = _claude_md()
    fabricated = claude_md + "\n| 9999 — fabricated | `deadbeef` | ✓ |\n"
    assert 9999 in claude_md_phase_numbers(fabricated)
    assert 9999 in missing_ledger_rows(fabricated, _ledger())
