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
