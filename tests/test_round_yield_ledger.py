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


# A Phase log row label sorts on (major, minor, letter): `294` -> (294, 0, ""), `294.1` ->
# (294, 1, ""), `295a` -> (295, 0, "a"). Both suffixed shapes are live in the table (`5.1`,
# `23a`, `159a`, `287.1`, `291.1`, …) and `claude_md_phase_numbers` cannot see either, because
# its `^\|\s*(\d+)\s` needs whitespace where those have a `.` or a letter. That blindness is
# `Q-503`'s and is NOT fixed here — but it must not be allowed to WIDEN the exemption, which is
# what the first version did: with `294.1` or `295a` as the newest row, `max()` over the numeric
# set still returned 294 and kept it exempt forever. Found by this phase's round.
_LABEL_KEY = re.compile(r"^(\d+)(?:\.(\d+))?([a-z])?")


def _row_labels(claude_md: str) -> list[str]:
    """The first cell of every data row in the Phase log table."""
    m = re.search(r"^##\s+Phase log\s*$", claude_md, re.M)
    assert m, "the Phase log heading is gone from CLAUDE.md; this guard's anchor needs revisiting"
    # Bounded at the next `## ` heading, like `ledger_phase_rows` — whose comment records the
    # author-side battery defeating an unscoped parse with a stray row pasted into the notes.
    # This fails loud rather than silent (a stray row reddens several arms), but repeating an
    # unscoped slice the module's own sibling documents as battery-defeated is not worth one line.
    table = claude_md[m.start():]
    stop = table.find("\n## ", 1)
    labels = []
    for line in (table[:stop] if stop != -1 else table).split("\n"):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if not cells or not cells[0] or cells[0] == "Phase" or set(cells[0]) <= set("- :"):
            continue
        labels.append(cells[0])
    return labels


def newest_phase_number(claude_md: str) -> int | None:
    """The newest row's phase number, or **None when the newest row is a sub- or letter-phase**.

    The one row allowed no ledger row. Derived from this module's own parsers and deliberately
    not imported from `test_phase_log_currency.newest_label`, which answers a neighbouring
    question over a different one. The exemption has to name a number the guard would otherwise
    demand; two parsers that disagree either exempt a phase this one never reports (a silent
    no-op) or fail to exempt one it does (the false red this exists to remove). Same reason,
    opposite conclusion, to `Q-500`'s duplicate-then-diverge.

    Returning `None` for a suffixed newest row is the load-bearing case, not a corner: when
    `294.1` or `295a` opens, Phase 294 has closed, and its missing ledger row is a real lapse
    that must be reported. The first version returned `max()` over the numeric set and so kept
    294 exempt until the next *plain integer* phase — which is the window failing to close,
    the one property the carve-out has to have.
    """
    keys = [k for k in (_LABEL_KEY.match(l) for l in _row_labels(claude_md)) if k]
    if not keys:
        return None
    major, minor, letter = max(
        (int(m.group(1)), int(m.group(2) or 0), m.group(3) or "") for m in keys)
    return None if (minor or letter) else major


def missing_ledger_rows(claude_md: str, ledger: str) -> list[int]:
    """Phases that closed without a ledger row — the NEWEST phase excepted.

    A ledger row for phase N cannot exist until N's round has run, and Phase 288 places
    N's reviewers at N's own commit. Without this carve-out the guard is red for exactly
    the interval the round gate exists to serve: measured at Phase 293, all three lenses
    were handed `1 failed, 7026 passed` and none could baseline on green, one spending part
    of its budget establishing that the failure was designed. A reviewer that cannot tell
    "red because the phase is mid-close" from "red because the phase broke something"
    either pays to find out or learns to discount a red suite, and a round that discounts
    red is the failure the gate was built to prevent (`Q-505`).

    The window is the same one `test_phase_log_currency`'s
    `test_only_the_newest_phase_may_have_an_unresolved_commit_cell` already grants the
    Commit cell, for the same reason: the value does not exist yet. It closes the moment
    the next phase adds its own row — so a phase that closed and never appended is still
    reported, which is the guard's real job.
    """
    phases = {n for n in claude_md_phase_numbers(claude_md) if n >= LEDGER_BINDS_FROM}
    newest = newest_phase_number(claude_md)
    if newest is not None:
        phases.discard(newest)
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


# Markdown's escape for a literal pipe inside a table cell is `\|`, and a raw
# `.split("|")` counts it as a separator anyway. Phase 203's row carried one, so
# it parsed to EIGHT body cells against a seven-column body — `Filed / latent`
# and `Sub-agent tokens` were being read one column right of their headers — and
# the `< 7` floor this replaced could not see it, because 8 is not fewer than 7.
# A floor answers "did the author stop early"; the column contract needs equality.
_CELL_SPLIT = re.compile(r"(?<!\\)\|")


def _split_cells(body: str) -> list[str]:
    """Row body -> cells, splitting on unescaped pipes only.

    The trailing delimiter is stripped with the same escape-awareness: a plain
    `.rstrip("|")` on a row whose last cell legitimately ends in `\\|` would eat
    the pipe and leave a dangling backslash inside the cell.
    """
    body = re.sub(r"(?<!\\)\|\s*$", "", body)
    return [c.strip().replace("\\|", "|") for c in _CELL_SPLIT.split(body)]


def _expected_body_cells(table: str) -> int:
    """Derive the body-cell count from the ledger's OWN header row.

    Hardcoding 7 gave the column contract one end. The round grew the header to
    nine columns, left every body row at eight, and nothing went red — every row
    then reading one column left of its header, which is the identical defect
    this check exists to catch, introduced from the header side.
    """
    header = re.search(r"(?m)^\|\s*Phase\s*\|(.*)$", table)
    assert header, "the ledger's schema table header is gone"
    return len(_split_cells(header.group(1)))


def _unmarked_cell(cell: str) -> str:
    """A cell's text with CommonMark emphasis and code markers stripped.

    Emphasis is presentation, not content, and a keyword check that sees it is
    a guard keyed to formatting. The ledger's three recorded skips are all
    `**skip**`, which a bare `startswith("skip")` misses.
    """
    return cell.replace("*", "").replace("_", "").replace("`", "").strip().lower()


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
    width = _expected_body_cells(table)
    for row in re.finditer(r"(?m)^\|\s*(\d+)\s*\|(.*)$", table):
        n = int(row.group(1))
        if n < LEDGER_BINDS_FROM:
            continue
        cells = _split_cells(row.group(2))
        if len(cells) != width:
            problems.append(f"row {n} has {len(cells)} cells against a {width}-column body")
            continue
        # Markup-stripped, because the ledger's own three recorded skips all
        # spell it `**skip**` and `"**skip**".startswith("skip")` is False. No
        # NUMERIC row has recorded a skip yet, so this never fired in anger —
        # but the convention explicitly allows one ("a recorded skip appends a
        # row too"), and the first numbered phase to record one will follow the
        # three precedents already in the file and red this guard on a
        # legitimately-recorded skip. Match the word, not the emphasis.
        if _unmarked_cell(cells[0]).startswith("skip"):
            continue
        empties = [i for i, c in enumerate(cells) if not c]
        if empties:
            problems.append(f"row {n} has empty cells at positions {empties}")
        # Code spans are content, not drafting. Phase 239's row names the batch
        # status `Pending` — a legitimate quoted value — and reddened this check.
        # Rewording the row around a guard is how a guard stops meaning anything,
        # so strip code spans before looking for draft markers instead.
        drafts = [c for c in cells
                  if re.search(r"\b(?:pending|provisional|tbd)\b",
                               re.sub(r"`[^`]*`", "", c), re.I)]
        if drafts:
            problems.append(f"row {n} still carries draft cells {drafts} — finalize before closing the phase")

    # The column contract binds every data row, not only the numerically-labelled
    # ones. The ledger's own convention mints non-numeric rows ("a recorded skip
    # appends one too" — `batch-6 triage`, `mirror push 182–183`, `phase-202
    # pre-push verification`), and the round's execute lens found 24 of 54 rows
    # outside the loop above: 13 below the binding floor plus 11 non-numeric.
    # Those carry free prose and are exactly as able to hold a raw `|` as the
    # three rows this phase repaired. Cell count only — the content checks stay
    # scoped to the binding range, because a backfill row predates the convention.
    for row in re.finditer(r"(?m)^\|(?!\s*(?:Phase\b|\d+\s*\||-))([^|]*)\|(.*)$", table):
        label = row.group(1).strip()
        if not label or set(label) <= set("- :"):
            continue
        cells = _split_cells(row.group(2))
        if len(cells) != width:  # same body as a numeric row; the label is separate
            problems.append(
                f"row {label!r} has {len(cells)} cells against a {width}-column body"
            )
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
    # **Width is DERIVED, not hardcoded.** The first version wrote eight literal
    # cells; when Phase 221 added two columns the probe's own rows became
    # wrong-width, so `row_problems` reported a cell-count problem instead of the
    # one under test and the draft half silently stopped exercising anything.
    # A vacuity check that hardcodes the shape it is checking is the defect it
    # exists to catch, one level up.
    m = re.search(r"(?m)^\|\s*Phase\s*\|(.*)$", ledger)
    assert m, "the ledger's schema table header is gone"
    width = len(_split_cells(m.group(1)))
    assert width >= 7, f"header derived to {width} cells — the probe is unsound"

    hollowed = ledger.replace(row.group(0), "| 174 |" + " |" * width, 1)
    assert any("empty cells" in p and "174" in p for p in row_problems(hollowed)), \
        row_problems(hollowed)

    drafted = ledger.replace(row.group(0), "| 174 |" + " pending |" * width, 1)
    probs = row_problems(drafted)
    assert any("draft" in p for p in probs), probs
    assert not any("cells against" in p for p in probs), (
        f"the draft row is the wrong WIDTH, so this exercises the cell-count "
        f"check rather than the draft check: {probs}"
    )


def test_the_backfill_is_present():
    """Deleting the 161-173 backfill would leave a schema with no evidence base."""
    rows = ledger_phase_rows(_ledger())
    missing = [n for n in range(161, 174) if n not in rows]
    assert missing == [], f"backfill rows missing from the ledger: {missing}"


def test_every_phase_from_174_has_a_ledger_row():
    missing = missing_ledger_rows(_claude_md(), _ledger())
    assert missing == [], (
        f"phases {missing} closed without a round-yield ledger row — a LATER phase has "
        "since opened its own Phase log row, so the window in which the row could not yet "
        "exist has passed. Append one per round, or a skip row with its reason. (The "
        "newest phase is exempt while its round runs; these are not it.)"
    )


def test_the_newest_phase_is_exempt_and_only_it():
    """The carve-out `Q-505` asks for, with its own negative control.

    Two fabricated rows, neither in the ledger. The higher is the newest row in the table
    and is exempt; the lower is not newest and must still be reported. A widening of the
    exemption to "any recent phase" fails on the second assertion, and a reversion to no
    exemption at all fails on the first — the two arms bracket it from both sides.
    """
    claude_md = _claude_md()
    fabricated = claude_md + (
        "\n| 9998 — fabricated, not newest | `deadbee` | ✓ |"
        "\n| 9999 — fabricated, newest | `deadbef` | ✓ |\n"
    )
    assert {9998, 9999} <= claude_md_phase_numbers(fabricated), (
        "the fabricated rows did not parse; this control is testing nothing"
    )
    missing = missing_ledger_rows(fabricated, _ledger())
    assert 9999 not in missing, (
        "the newest phase was reported missing a ledger row — the carve-out is gone, and "
        "every phase is red at its own commit for the window its reviewers read it"
    )
    assert 9998 in missing, (
        "a phase that is NOT the newest was let through — the exemption has widened past "
        "the single row whose value cannot exist yet, and a lapsed ledger now goes unseen"
    )


def test_the_exemption_closes_when_the_next_phase_opens():
    """The window is per-phase and shuts the moment a newer row lands.

    Phase N exempt on its own; Phase N reported the instant N+1 opens. This is the arm that
    keeps the carve-out a *window* rather than a permanent hole at the end of the table —
    an exemption that never closes is indistinguishable from deleting the guard.
    """
    claude_md = _claude_md()
    alone = claude_md + "\n| 9998 — fabricated | `deadbee` | ✓ |\n"
    assert 9998 not in missing_ledger_rows(alone, _ledger())
    successor = alone + "\n| 9999 — fabricated successor | `deadbef` | ✓ |\n"
    assert 9998 in missing_ledger_rows(successor, _ledger()), (
        "a phase stayed exempt after a later phase opened its own row — the window never "
        "closes, so a phase that closed and never appended is permanently invisible"
    )


def _ledger_with_row(ledger: str, phase: int) -> str:
    """Insert a schema-table row for `phase`, INSIDE the table the parser reads.

    Appending at end-of-file would land past `## Reading notes` and be invisible —
    `test_a_stray_row_outside_the_schema_table_does_not_count` is the pin that says so, and a
    fixture built the wrong way would make the test below pass for the wrong reason.
    """
    m = re.search(r"(?m)^\|\s*Phase\s*\|.*\n\|[-:| ]+\|\n", ledger)
    assert m, "the schema table header/separator pair is gone; this fixture cannot be built"
    row = f"| {phase} | fabricated | - | - | - | - | - |\n"
    return ledger[:m.end()] + row + ledger[m.end():]


def test_the_exemption_names_the_newest_row_even_when_that_row_IS_present():
    """The case the other three arms cannot distinguish, and the author-side battery found it.

    Every arm above fabricates phases that ALL lack ledger rows, so "the newest phase" and "the
    highest phase with no ledger row" are the same number and a chaining implementation passes
    them all. It is a real difference: exempting the highest UNROWED phase excuses an older
    lapse the moment the newest phase has appended its own row — which is the ordinary state of
    this repo between phases, not a corner.

    So: 9999 newest AND rowed, 9998 older and unrowed. 9998 must be reported. A chaining
    implementation exempts 9998 instead and returns nothing.
    """
    claude_md = _claude_md() + (
        "\n| 9998 — fabricated, older, no ledger row | `deadbee` | ✓ |"
        "\n| 9999 — fabricated, newest, HAS a ledger row | `deadbef` | ✓ |\n"
    )
    ledger = _ledger_with_row(_ledger(), 9999)
    assert 9999 in ledger_phase_rows(ledger), (
        "the fabricated ledger row did not parse — the fixture is built wrong and this test "
        "would pass for the wrong reason"
    )
    missing = missing_ledger_rows(claude_md, ledger)
    assert 9998 in missing, (
        "an older phase with no ledger row was excused while the newest phase already had one — "
        "the exemption is keyed to the highest UNROWED phase rather than to the newest phase, "
        "so every lapse is forgiven one phase at a time"
    )
    assert 9999 not in missing, "the newest phase has a row and must not be reported regardless"


def test_the_window_closes_on_a_SUFFIXED_successor_too():
    """The successor shapes `test_the_exemption_closes_when_the_next_phase_opens` cannot see.

    Found by this phase's round, which measured the first version keeping 294 exempt under a
    `294.1` or `295a` successor — `[]` where it must be `[294]` — because the numeric parser
    cannot see either label and `max()` over what it CAN see still returned 294. Both shapes
    are live in the real table (`5.1`, `23a`, `159a`, `287.1`, `291.1`). Self-healing at the
    next plain integer, which is why it is a hole rather than a hemorrhage — and why the arm
    exists, since a hole that heals is exactly the kind nobody notices.
    """
    claude_md = _claude_md() + "\n| 9998 — fabricated, closed, no ledger row | `deadbee` | ✓ |\n"
    assert 9998 not in missing_ledger_rows(claude_md, _ledger()), (
        "the fixture is wrong: 9998 must start out exempt as the newest row, or the arms "
        "below prove nothing about the successor"
    )
    for successor, shape in (
        ("9998.1 — fabricated sub-phase", "sub-phase, the 287.1 / 291.1 shape"),
        ("9999a — fabricated letter phase", "letter phase, the 159a / 23a shape"),
        ("9999 — fabricated numeric", "plain integer, the control"),
    ):
        with_successor = claude_md + f"| {successor} | `deadbef` | ✓ |\n"
        assert 9998 in missing_ledger_rows(with_successor, _ledger()), (
            f"a {shape} opened above 9998 and 9998 stayed exempt — the window does not close "
            "on this successor shape, so a phase that closed and never appended is invisible "
            "until the next plain-integer phase"
        )


def test_a_suffixed_newest_row_exempts_nobody():
    """The direct statement of `newest_phase_number`'s contract.

    A sub- or letter-phase as the newest row means the integer below it has CLOSED, so nothing
    is exempt. Asserted on the function rather than through `missing_ledger_rows` so a future
    refactor cannot satisfy the arm above by some other route while the contract rots.
    """
    claude_md = _claude_md()
    assert newest_phase_number(claude_md + "\n| 9999 — numeric | `a1b2c3d` | ✓ |\n") == 9999
    for suffixed in ("9999.1 — sub-phase", "9999a — letter phase"):
        assert newest_phase_number(claude_md + f"\n| {suffixed} | `a1b2c3d` | ✓ |\n") is None, (
            f"{suffixed!r} as the newest row returned a number; it must return None, because "
            "the phase below it has closed and owes its row"
        )


def test_the_exemption_is_keyed_to_the_newest_row_not_to_a_missing_one():
    """Exempting "the highest phase with no ledger row" instead of "the highest phase"
    would walk an unbounded tail through: 294, 293, 292 … each in turn becoming the
    highest *unrowed* phase as the one above it is excused. Two unrowed rows above the
    real table's newest must yield exactly one exemption, and that is the assertion.
    """
    claude_md = _claude_md()
    fabricated = claude_md + (
        "\n| 9997 — fabricated | `deadbec` | ✓ |"
        "\n| 9998 — fabricated | `deadbee` | ✓ |"
        "\n| 9999 — fabricated | `deadbef` | ✓ |\n"
    )
    missing = missing_ledger_rows(fabricated, _ledger())
    exempted = {9997, 9998, 9999} - set(missing)
    assert exempted == {9999}, (
        f"expected exactly the newest fabricated row to be exempt, got {sorted(exempted)} "
        "— the exemption is chaining down the tail instead of naming one row"
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
    because it is reading nothing.

    It takes TWO fabricated rows since `Q-505`: the newest row is exempt by design, so a
    single `| 9999 |` would now be excused and this control would pass over a guard that
    had stopped reading. The lower row is the one under test; the higher exists only to
    stop the lower from being the newest.
    """
    claude_md = _claude_md()
    fabricated = claude_md + (
        "\n| 9998 — fabricated | `deadbee` | ✓ |"
        "\n| 9999 — fabricated successor | `deadbef` | ✓ |\n"
    )
    assert 9998 in claude_md_phase_numbers(fabricated)
    assert 9998 in missing_ledger_rows(fabricated, _ledger())


def test_no_ledger_row_is_stranded_outside_the_schema_table():
    """Every `|`-prefixed row must sit inside the table the parser reads.

    `test_a_stray_row_outside_the_schema_table_does_not_count` pins the parser against a
    row pasted *outside* the table — but it only ever asks about a NUMBERED phase, so a
    row keyed to a non-numbered round (`docs:`/`fix:` work, which the convention explicitly
    admits) could land outside and be invisible: not counted by the parser, and not caught
    by the pace-keeping guard either, because that only looks for numbered phases.

    Two rows had done exactly that by 2026-08-11 — appended past the `## Reading notes`
    heading by a `cat >>`. Both are evidence the governor is supposed to weigh, so silently
    dropping them out of the table is a real loss, not a formatting nit.
    """
    ledger = _ledger()
    header = re.search(r"(?m)^\|\s*Phase\s*\|", ledger)
    assert header, "the schema table header is gone"
    end = ledger.find("\n## ", header.end())
    table = ledger[header.start(): end if end != -1 else len(ledger)]
    inside = {l for l in table.splitlines() if l.startswith("|")}

    stranded = [
        l[:80] for l in ledger.splitlines()
        if l.startswith("|") and not re.match(r"^\|\s*(Phase|-)", l) and l not in inside
    ]
    assert stranded == [], (
        "ledger row(s) sit outside the schema table, so `ledger_phase_rows` cannot see "
        "them and the round they record is not counted as evidence:\n  "
        + "\n  ".join(stranded)
    )


# ── Phase 204: the column contract, both directions ───────────────

def test_the_cell_split_respects_the_markdown_escape():
    """`\\|` is a literal pipe inside a cell, not a column boundary."""
    assert _split_cells(" a | b \\| c | d |") == ["a", "b | c", "d"]
    # …and the trailing delimiter goes whether or not it has trailing space.
    assert _split_cells(" a | b |") == ["a", "b"]
    assert _split_cells(" a | b |  ") == ["a", "b"]
    assert _split_cells(" a | b") == ["a", "b"]


def test_a_row_with_too_many_cells_is_caught_not_only_a_short_one():
    """The floor this replaced could only see a row that stopped early.

    Phase 203's row carried an unescaped pipe and parsed to EIGHT cells against
    a seven-column body, so `Filed / latent` and `Sub-agent tokens` were read one
    column right of their headers — and `len(cells) < 7` cannot see 8. Two more
    rows (186, 194) had the mirror-image defect and had been masked the other
    way: unescaped-pipe splitting inflated their true SIX cells — 186 to nine,
    194 to seven. (An earlier draft of this docstring stated that pair reversed;
    the round caught it.) A column contract needs equality; a floor answers a
    different question.
    """
    header = "| Phase | A | B | C | D | E | F | G |\n|---|---|---|---|---|---|---|---|\n"
    seven = "| 174 | a | b | c | d | e | f | g |\n"
    assert row_problems(header + seven) == []

    eight = "| 174 | a | b | c | d | e | f | g | h |\n"
    problems = row_problems(header + eight)
    assert any("8 cells" in p for p in problems), problems

    six = "| 174 | a | b | c | d | e | f |\n"
    problems = row_problems(header + six)
    assert any("6 cells" in p for p in problems), problems


def test_an_escaped_pipe_does_not_red_a_well_formed_row():
    """Over-strictness control: the escape is legal content, not a defect."""
    header = "| Phase | A | B | C | D | E | F | G |\n|---|---|---|---|---|---|---|---|\n"
    escaped = "| 174 | a | b | c | d | e \\| still e | f | g |\n"
    assert row_problems(header + escaped) == []


def test_the_column_width_is_derived_from_the_header_not_hardcoded():
    """F9: a contract with one end is not a contract.

    Growing the header while leaving the body rows alone is the same
    read-against-the-wrong-header defect as an unescaped pipe, approached from
    the other side, and a hardcoded 7 cannot see it.
    """
    header = "| Phase | A | B | C | D | E | F | G |\n|---|---|---|---|---|---|---|---|\n"
    seven = "| 174 | a | b | c | d | e | f | g |\n"
    assert row_problems(header + seven) == []

    wider = "| Phase | A | B | C | D | E | F | G | H | I |\n|---|---|---|---|---|---|---|---|---|---|\n"
    problems = row_problems(wider + seven)
    assert any("9-column body" in p for p in problems), problems


# ---------------------------------------------------------------------------
# Controls for `row_problems`' remaining branches — `Q-214` leg (5).
#
# `row_problems` already has the Phase-204 shared-function treatment: the real
# guard and three controls all call it, so the numeric-row checks are observed.
# The filing said one branch was uncontrolled. Derived by mutation, it was
# THREE — the header-gone early return, the skip exemption, and the non-numeric
# label-row loop — each of which could be deleted outright with the module green.
#
# The skip exemption was the notable one: `tools/ROUND_YIELD_LEDGER.md` carries
# no NUMERIC skip row today, so that branch has never run in anger. But the
# ledger carries three recorded skips as LABEL rows, all spelling it `**skip**`
# — which the exemption's `startswith` could not match until this phase stripped
# the markup. These controls feed synthetic ledgers through the REAL predicate,
# which is the only shape that observes it.
# ---------------------------------------------------------------------------

_SYNTHETIC_HEADER = (
    "| Phase | Reviewers | Diff-model? | Author battery | Independent battery "
    "| Verified findings | Filed / latent | Sub-agent tokens |\n"
    "|---|---|---|---|---|---|---|---|\n"
)


def _synthetic(*rows: str) -> str:
    return _SYNTHETIC_HEADER + "".join(r + "\n" for r in rows) + "\n## Reading notes\n"



def test_the_row_checks_survive_weakening_not_just_deletion():
    """The three controls above catch a branch being DELETED. They do not catch
    it being weakened, and the round walked eight weakenings through them.

    Deletion is the easy half and the rare one: nobody deletes a check, they
    relax it — `startswith` to `in`, a truthiness test to a threshold, an
    equality to an inequality, a vocabulary to one of its words. Every row here
    is a silencing change that leaves the branch present and the module green
    under the deletion controls.

    Each case feeds a synthetic ledger through the REAL predicate and asserts
    the specific problem still appears, so a relaxed branch stops reporting and
    reds here.
    """
    # `startswith("skip")` relaxed to `"skip" in` — a row merely MENTIONING a
    # skip in its reviewers cell would then be exempted from every content check.
    mentions = "| 174 | 3 x 1 lenses, no skip taken | | | | | | |"
    assert any("empty" in p for p in row_problems(_synthetic(mentions))), (
        "a row that merely mentions 'skip' is being exempted — the exemption "
        "matches a substring instead of the cell's leading word"
    )
    # The draft vocabulary is three words, not one. Relaxing it to `pending`
    # alone silences the other two.
    for word in ("pending", "provisional", "tbd"):
        drafted = f"| 174 | 3 x 1 | yes | {word} | n/a | n/a | n/a | n/a |"
        assert any("draft" in p for p in row_problems(_synthetic(drafted))), (
            f"a row carrying the draft marker {word!r} is not reported — the "
            "draft vocabulary has been narrowed"
        )
    # `if empties:` relaxed to a threshold. ONE empty cell must report.
    one_empty = "| 174 | 3 x 1 | yes | n/a | n/a | n/a | n/a | |"
    assert any("empty" in p for p in row_problems(_synthetic(one_empty))), (
        "a row with a single empty cell is not reported — the emptiness check "
        "has acquired a threshold, and a threshold lets the first one through"
    )
    # The non-numeric cell-count check must bind in BOTH directions. A floor
    # (`< width`) cannot see a row with too many cells, which is the direction a
    # stray unescaped pipe produces — and a stray pipe is the whole reason that
    # loop exists.
    too_many = "| mirror push 182-183 | a | b | c | d | e | f | g | h |"
    assert any("mirror push" in p for p in row_problems(_synthetic(too_many))), (
        "a non-numeric row with too MANY cells is not reported — the column "
        "contract has become a floor, and a raw `|` adds cells rather than "
        "removing them"
    )
    # Same, for a numeric row.
    too_many_numeric = "| 174 | a | b | c | d | e | f | g | h |"
    assert any("174" in p for p in row_problems(_synthetic(too_many_numeric))), (
        "a numeric row with too many cells is not reported — the cell-count "
        "check has become a floor rather than an equality"
    )


def test_the_separator_and_blank_label_skip_is_load_bearing():
    """The fourth uncontrolled branch, found by the round after this phase had
    already claimed the count was three.

    `if not label or set(label) <= set("- :"): continue` suppresses two real
    false-positive classes — an alignment separator row and a blank-label
    spacer — and deleting it left the module green because no real ledger row
    exercises it. That is the same profile the skip exemption had, which this
    phase called "the notable one" and then stopped looking.
    """
    # The rows must be the WRONG width, or they satisfy the cell-count check on
    # their own merits and the branch is never load-bearing in the input. The
    # first cut of this control used full-width rows and the deletion walked
    # straight through it — the same mistake the skip control made with `n/a`
    # cells, made twice in one phase.
    for spacer in ("| :--- | ---: |", "|  |  |", "| --- : | :---: |"):
        problems = row_problems(_synthetic(spacer))
        assert problems == [], (
            "a table separator or blank spacer row is being reported as a data "
            f"row, so any nested or realigned table inside the ledger's segment "
            f"would red the guard: {problems}"
        )


def test_the_binding_floor_still_exempts_the_backfill():
    """The fifth uncontrolled branch. `if n < LEDGER_BINDS_FROM: continue`
    exempts the deliberate 161-173 backfill from the content checks; removing
    it left the module green here while reddening on the real ledger's own
    history, which is a guard that fails only once someone reruns it."""
    old_row = "| 161 | 3 x 1 | unrecorded | unrecorded | unrecorded | x | y | |"
    assert row_problems(_synthetic(old_row)) == [], (
        "a pre-174 backfill row is being held to the finalization checks — the "
        "binding floor is gone, and the backfill predates the convention"
    )
    new_row = "| 174 | 3 x 1 | unrecorded | unrecorded | unrecorded | x | y | |"
    assert any("174" in p for p in row_problems(_synthetic(new_row))), (
        "a row inside the binding range is NOT being held to the checks — the "
        "floor has swallowed the range it was supposed to open"
    )


def test_the_header_width_derivation_binds_in_both_directions():
    """`_expected_body_cells` has a control for the header being WIDENED and
    none for it being narrowed or floored. Both directions are the same defect
    — rows reading one column off their header — and the round silenced the
    narrowing half with a one-word change.
    """
    narrow_header = (
        "| Phase | Reviewers | Diff-model? | Author battery | Independent battery "
        "| Verified findings |\n|---|---|---|---|---|---|\n"
    )
    row = "| 174 | a | b | c | d | e | f | g |\n"
    problems = row_problems(narrow_header + row + "\n## Reading notes\n")
    assert any("cells against" in p for p in problems), (
        "a row wider than its own header is not reported — the width "
        "derivation has been floored, so every row reads one column off"
    )

def test_the_header_gone_branch_is_observed():
    """Deleting the early return left the module green — nothing fed it a ledger
    with no schema table, so the branch that names the worst case never ran."""
    problems = row_problems("# Round-yield ledger\n\nno table at all\n")
    assert problems, "a ledger with no schema header reports no problem at all"
    assert any("header" in p for p in problems), problems


def test_the_skip_exemption_is_observed_in_both_directions():
    """No numerically-labelled row has recorded a skip, so this never ran in anger.

    Both directions matter: a skip row must be exempt from the emptiness and
    draft checks (or a recorded skip cannot be written at all), and it must NOT
    be exempt from the cell count (or the exemption becomes a way to smuggle a
    malformed row past the column contract).
    """
    # The cells must be EMPTY, not `n/a`. An `n/a` row passes the emptiness and
    # draft checks on its own merits, so it cannot tell whether the exemption is
    # there — the first cut of this control used `n/a` and both exemption
    # mutations walked straight through it.
    # BOTH spellings. The first cut pinned only the unbolded form, which
    # cemented a spelling the ledger has never used: all three recorded skips
    # in `tools/ROUND_YIELD_LEDGER.md` are `**skip**`, and the exemption's
    # `startswith` missed every one of them. Pinning the form that happens to
    # work, while the form people actually write fails, is the guard certifying
    # its own convenience.
    for cell in ("skip — record-only mirror commit", "**skip** — author-side pass only"):
        good_skip = f"| 174 | {cell} | | | | | | |"
        assert row_problems(_synthetic(good_skip)) == [], (
            f"a skip row written {cell!r} with empty cells is being reported — "
            "the exemption no longer covers the ledger's own convention for a "
            "recorded skip. A recorded skip has nothing to put in those cells, "
            "and emphasis around the word is presentation, not content."
        )
    # The exemption is keyed to `skip`, not to any word starting with it. A row
    # that merely begins with the same letter must still be held to the content
    # checks, or the exemption becomes a prefix anyone can land on.
    near_miss = "| 174 | solo round, no second lens | | | | | | |"
    assert any("empty" in p for p in row_problems(_synthetic(near_miss))), (
        "a non-skip row with empty cells is being exempted — the skip test has "
        "been widened past the literal it is supposed to match."
    )
    short_skip = "| 174 | skip — record-only | | | |"
    short_problems = row_problems(_synthetic(short_skip))
    assert any("cells" in p for p in short_problems), (
        "a skip row with the wrong cell count is exempt from the column "
        "contract — the exemption covers content, never shape."
    )
    # Exactly one problem, not three. A malformed row is reported ONCE, for the
    # thing that is actually wrong with it; the `continue` after the cell-count
    # branch is what stops the emptiness and draft checks piling spurious
    # findings onto a row whose shape already failed. Dropping that `continue`
    # was a surviving mutation until this assertion existed.
    assert len(short_problems) == 1, (
        "a short row now reports more than its cell-count problem — the "
        f"cell-count branch stopped short-circuiting: {short_problems}"
    )


def test_the_non_numeric_row_loop_is_observed():
    """Deleting the whole loop left the module green. The ledger's convention
    mints non-numeric rows, and they hold free prose exactly as able to carry a
    raw `|` as a numeric one."""
    short_label_row = "| mirror push 182–183 | 2 × 1 | yes | n/a |"
    problems = row_problems(_synthetic(short_label_row))
    assert any("mirror push" in p for p in problems), (
        "a non-numeric row with the wrong cell count is not reported — the "
        "column contract has stopped binding every data row."
    )
    full_label_row = (
        "| mirror push 182–183 | 2 × 1 | yes | n/a | n/a | n/a | n/a | n/a |"
    )
    assert row_problems(_synthetic(full_label_row)) == [], (
        "a well-formed non-numeric row is being reported — the loop has become "
        "over-strict and the ledger's own convention no longer validates."
    )


# --------------------------------------------------------------------------------------
# Phase 288 (`Q-489`) — the placement receipt
#
# `isolation: "worktree"` forks a reviewer from the default branch, so a round run from a
# feature branch reads the PRE-PHASE tree unless the spawner places it. That happened to at
# least 13 reviewers across Phases 284–287 and cost a round outright at Phase 185. The
# procedure now requires each lens to echo `git rev-parse HEAD` before its first finding;
# this is the half that makes the omission visible from OUTSIDE the round. Inside it the
# failure is detectable — all ≥13 misplacements WERE detected from inside, by a lens that
# ran `rev-parse`, which is why a receipt the round writes about itself is worth anything.
# From outside, a misplaced round is indistinguishable from a clean one: a lens on the
# parent commit finds nothing, which reads exactly like a clean pass.
#
# So a binding row must name the commit its lenses stood on. A recorded skip is exempt:
# there are no lenses to place. The floor is a NEW one — rows 174-287 predate the
# requirement and several of them (185, 186, 187) record correct placement in prose with no
# SHA, which is why this cannot be applied retroactively without rewriting their evidence.
# --------------------------------------------------------------------------------------

PLACEMENT_BINDS_FROM = 288


def _label_phase(label: str) -> int | None:
    r"""The phase number a ledger row's label refers to, or None.

    **Not `int(label)`.** The first version selected rows with `^\|\s*(\d+)\s*\|`, and both
    round lenses showed the same hole from different directions: the ledger's own two most
    recent cut rows are labelled `274-cut` and `283-cut`, this repo shipped `159a`, `159b`
    and `287.1`, and **the very next phase after this one is the cut** — so on the file's
    established convention the first round to meet this guard would have escaped it.

    The `< 1000` bound is what keeps `inbound-sprint triage 2026-08-11` from reading as
    phase 2026. It is a heuristic and it is stated rather than hidden: a row whose label
    carries no phase number at all (a bare `mirror push`, say) is not bound by this check.
    Every row in the file today either carries one or is a recorded skip.
    """
    # `(?<!\d)…(?!\d)` rather than `\b…\b`: a word boundary needs a non-word character, so
    # `\b(\d{1,3})\b` finds nothing in `288a` — the exact label shape this repo ships
    # (`159a`, `159b`), and the one the test below caught escaping.
    m = re.search(r"(?<!\d)(\d{1,3})(?!\d)", label)
    return int(m.group(1)) if m else None


# A recorded skip is the sanctioned exit, and it is the FIRST WORD of the cell, not a word
# in it. The round's guard lens disarmed the receipt with `skip the receipt — 2 × 1 lenses
# ran, placement not recorded`: a real round, describing itself, exempted by one token. The
# file's three precedents all read `**skip** — <reason>`, so the separator is part of the
# convention and can be required.
_SKIP_CELL = re.compile(r"^skip\b\s*(?:[—–-]|$)")

# Backticked AND digit-bearing. A bare `\b[0-9a-f]{7,40}\b` matches ordinary English written
# in hex letters — `defaced`, `effaced` — and the ledger's cells are free prose, so the code
# span alone is not the discriminator the first version claimed: the round's record lens
# pointed out that `` `defaced` `` still satisfied it. Requiring a digit closes that.
#
# The residue, stated rather than hidden: an all-letter SHA prefix (p ≈ (6/16)^7 ≈ 0.14% for
# a 7-char abbreviation, vanishing for a full 40) would be refused. That is the SAFE
# direction — a loud false red on a real row, fixed by writing a longer abbreviation — not a
# silent false green.
PLACEMENT_RECEIPT = re.compile(r"`(?=[0-9a-f]{7,40}`)[0-9a-f]*\d[0-9a-f]*`")


def placement_problems(ledger: str) -> list[str]:
    # Same slice as `row_problems`, inlined the same way: both must read the SAME table, and
    # a second slicer that drifts from it would silently bind a different population.
    problems = []
    m = re.search(r"(?m)^\|\s*Phase\s*\|", ledger)
    if not m:
        return ["the ledger's schema table header is gone"]
    end = ledger.find("\n## ", m.end())
    table = ledger[m.start():end if end != -1 else len(ledger)]
    for row in re.finditer(r"(?m)^\|([^|]*)\|(.*)$", table):
        label = row.group(1).strip()
        if not label or label == "Phase" or set(label) <= set("- :"):
            continue
        n = _label_phase(label)
        if n is None or n < PLACEMENT_BINDS_FROM:
            continue
        cells = _split_cells(row.group(2))
        if not cells:
            continue
        if _SKIP_CELL.match(_unmarked_cell(cells[0])):
            continue
        # The WHOLE row, not the Reviewers cell. The first version scanned `cells[0]` only,
        # and the round's record lens showed the nearest precedents put it elsewhere: Phases
        # 285 and 286 recorded where their lenses stood in the **Diff-model** cell. A receipt
        # guard that dictates which column the receipt goes in reddens an author who follows
        # the file's own precedent — over-strictness in the direction that gets guards
        # deleted. What must be true is that the row names the commit, not where it says so.
        if not PLACEMENT_RECEIPT.search(row.group(2)):
            problems.append(
                f"row {label!r} names no commit its lenses stood on — record the "
                "SHA each lens echoed (`git rev-parse HEAD`, before its first finding). A "
                "round whose placement is unrecorded cannot be told from one that read the "
                "pre-phase tree, and that round reports no findings."
            )
    return problems


def test_binding_rows_record_where_their_lenses_stood():
    assert placement_problems(_ledger()) == []


def test_the_placement_check_is_not_vacuous():
    """Driven against a synthetic ledger, not the live one: a vacuity test that depends on
    the file's current contents stops exercising anything the moment the file changes."""
    unrecorded = _synthetic("| 999 | 2 × 1 (a / b) | no | n/a | n/a | n/a | n/a | n/a |")
    assert any("999" in p for p in placement_problems(unrecorded)), placement_problems(unrecorded)

    recorded = _synthetic(
        "| 999 | 2 × 1 (a / b), both placed at `4b8423b` | no | n/a | n/a | n/a | n/a | n/a |")
    assert placement_problems(recorded) == [], placement_problems(recorded)

    # The receipt must be a SHA in a code span, not any code span. A row that quotes a
    # filename would otherwise satisfy it.
    quoted = _synthetic(
        "| 999 | 2 × 1 (a / b), see `adversarial-review.md` | no | n/a | n/a | n/a | n/a | n/a |")
    assert any("999" in p for p in placement_problems(quoted)), placement_problems(quoted)

    # Nor by ordinary English that happens to be spelled in hex letters. The round's record
    # lens defeated the first version of this pattern with exactly this token.
    hexword = _synthetic(
        "| 999 | 2 × 1 (a / b), a `defaced` control | no | n/a | n/a | n/a | n/a | n/a |")
    assert any("999" in p for p in placement_problems(hexword)), placement_problems(hexword)

    # And the receipt may sit in ANY cell — Phases 285 and 286 recorded placement in the
    # Diff-model cell, so binding it to the Reviewers cell would red the file's own precedent.
    elsewhere = _synthetic(
        "| 999 | 2 × 1 (a / b) | no, and all lenses at `102bc22` | n/a | n/a | n/a | n/a | n/a |")
    assert placement_problems(elsewhere) == [], placement_problems(elsewhere)


def test_a_recorded_skip_is_exempt_from_the_placement_receipt():
    skipped = _synthetic("| 999 | **skip** — recorded reason | n/a | n/a | n/a | n/a | n/a | n/a |")
    assert placement_problems(skipped) == [], placement_problems(skipped)


def test_the_placement_receipt_binds_only_at_and_above_its_floor():
    below = _synthetic(f"| {PLACEMENT_BINDS_FROM - 1} | 2 × 1 (a / b) | no | n/a | n/a | n/a | n/a | n/a |")
    assert placement_problems(below) == [], placement_problems(below)
    at = _synthetic(f"| {PLACEMENT_BINDS_FROM} | 2 × 1 (a / b) | no | n/a | n/a | n/a | n/a | n/a |")
    assert placement_problems(at) != [], "the floor is off by one — it must bind AT 288"


def test_the_placement_floor_does_not_bind_the_rows_that_predate_it():
    """185, 186 and 187 record correct placement in prose and carry no SHA — 185 only after
    a first dispatch it had to discard. Applying the
    receipt retroactively would red three rows whose evidence is sound, and the repair
    would be rewriting their record to fit a guard — the tail wagging the dog."""
    ledger = _ledger()
    for n in (185, 186, 187):
        row = re.search(rf"(?m)^\|\s*{n}\s*\|.*$", ledger)
        assert row, f"no {n} row to check the floor against"
        assert not PLACEMENT_RECEIPT.search(row.group(0)), (
            f"row {n} now carries a SHA receipt — if the rows below the floor have been "
            "backfilled, lower PLACEMENT_BINDS_FROM deliberately rather than leaving the "
            "floor describing a state that no longer holds"
        )
    assert placement_problems(ledger) == []


def test_the_receipt_reaches_the_labels_the_file_actually_uses():
    """The round's two lenses found the same hole from opposite ends: a `\\d+`-only row
    selector misses `289-cut`, `288.1` and `288a` — and 289 IS the cut, so the first round
    to meet this guard would have been the first to escape it."""
    for label in ("289-cut", "288.1", "288a", "mirror push 288–289"):
        row = _synthetic(f"| {label} | 2 × 1 (a / b) | no | n/a | n/a | n/a | n/a | n/a |")
        assert any(label in p for p in placement_problems(row)), (
            f"a row labelled {label!r} escapes the receipt: {placement_problems(row)}"
        )
    # …and the bound that keeps a date from reading as a phase number.
    dated = _synthetic(
        "| inbound-sprint triage 2026-08-11 | 2 × 1 (a / b) | no | n/a | n/a | n/a | n/a | n/a |")
    assert placement_problems(dated) == [], (
        "a 2026 date is being read as a phase number, so every dated `docs:` row predating "
        "the floor now demands a receipt"
    )


def test_the_skip_exemption_is_the_first_word_and_not_a_word_in_the_cell():
    """`skip the receipt — 2 × 1 lenses ran, placement not recorded` disarmed the first
    version with one token, while describing a real round."""
    abused = _synthetic(
        "| 999 | skip the receipt — 2 × 1 lenses ran, placement not recorded "
        "| no | n/a | n/a | n/a | n/a | n/a |")
    assert any("999" in p for p in placement_problems(abused)), placement_problems(abused)
    for genuine in ("**skip** — recorded reason", "skip — recorded reason", "skip"):
        row = _synthetic(f"| 999 | {genuine} | n/a | n/a | n/a | n/a | n/a | n/a |")
        assert placement_problems(row) == [], f"{genuine!r} is the sanctioned exit and must pass"


def test_the_receipt_detects_OMISSION_and_says_so_rather_than_implying_more():
    """**The limit, pinned so it cannot quietly be forgotten.** Both round lenses landed on
    this independently: a regex receipt certifies that a SHA was *written*, not that the
    lenses stood on the right commit. A row that records the failure in full — "both lenses
    were handed the pre-phase tip `ab7c216` and neither re-detached" — satisfies it.

    That is not a defect to be regexed away; judging the claim's truth from its prose is the
    polarity-detection treadmill Phase 179 measured at 0 of 21. What this guard buys is that
    the question cannot be left UNANSWERED in the record, which is the state all four of the
    284–287 rounds were in. The answer's truth is the reader's job, and this test exists so
    that nobody reads a green suite as the stronger claim.
    """
    confessed = _synthetic(
        "| 999 | 2 × 1 (a / b), both handed the pre-phase tip `ab7c216`, neither re-detached "
        "| no | n/a | n/a | n/a | n/a | n/a |")
    assert placement_problems(confessed) == [], (
        "if this now reports, the guard has started judging the claim rather than its "
        "presence — re-read the docstring before 'fixing' it"
    )
