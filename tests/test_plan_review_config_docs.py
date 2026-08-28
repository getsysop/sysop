"""`## Plan review` is a shipped consumer knob. Pin that it stays documented.

**Why this module exists, and it is not "documentation hygiene".** `## Plan
review` shipped with Phase 171 as tier 2 of `_shared/plan-review-preference.md`'s
resolution order, and until Phase 238 it appeared in **neither**
`docs/configuration.md` nor `WORKFLOW.md` § 6.1 — the two places the shipped docs
tell a consumer to look for exactly this. A consumer could not configure it
without reading the skill source. Nothing was red, because nothing looked.

Worse, `configuration.md` opened with a *count* ("Four are pure configuration")
that a reader uses to know whether the table is complete, and the count was
maintained by hand. It was wrong for 67 phases. So the check below derives the
count from the table rather than asserting a number: a fifth knob added without
a fifth row reddens, and so does a row added without moving the count.

Scope, stated so it is not over-read: this proves the knob is *described* in the
two places that promise to describe it, and that the count and the table agree.
It does not prove the description is correct — that is what the round is for.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _prose_guard_helpers import normalize, states  # noqa: E402

CONFIG_DOC = REPO_ROOT / "docs/configuration.md"
WORKFLOW = REPO_ROOT / "core/companion/docs/WORKFLOW.md"
PARTIAL = REPO_ROOT / "core/skills/_shared/plan-review-preference.md"

_WORD_TO_INT = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _section_6_1() -> str:
    """WORKFLOW.md § 6.1, sliced by its OWN heading pair.

    Not `_prose_guard_helpers.section()`: that helper slices to the next
    same-or-higher heading and is fence-blind, and § 6.1's body is mostly fenced
    `markdown` templates whose content lines are literal `## Merge policy`,
    `## Plan review` and so on. It therefore returns the first ~40 lines and every
    check over the rest passes vacuously. Found by writing this module.
    """
    text = WORKFLOW.read_text(encoding="utf-8").split("\n")
    start = next(i for i, ln in enumerate(text)
                 if ln.startswith("### 6.1 What CLAUDE.md should contain"))
    end = next(i for i in range(start + 1, len(text)) if text[i].startswith("### 6.2"))
    return "\n".join(text[start:end])


def test_the_section_slice_reaches_the_templates():
    """Non-vacuity for the slice above -- the failure it replaces was silent.

    Named templates, not a count: a count both under-specifies (three would pass
    on any three) and breaks whenever § 6.1 gains a legitimate fourth. These two
    bracket the span -- the upstream-repo template is near the top of the
    section and the merge-policy one is the last thing in it -- so a slice that
    stops early cannot satisfy both.
    """
    s = _section_6_1()
    for name in ("`## Sysop upstream repo` template", "`## Merge policy` template"):
        assert f"**{name}**" in s, (
            f"§ 6.1 slice does not reach {name!r} -- it is truncating, and every "
            f"check over the rest of the section is passing vacuously")


def _plan_review_row(s61: str) -> str:
    """The § 6.1 row, matched tolerantly and failing with a MESSAGE.

    `next(... startswith("| `## Plan review`"))` raised an uncaught
    StopIteration on a table-cell padding change -- a legal reformat any
    markdown formatter produces -- so the failure arrived as an error with no
    explanation rather than as an assertion. Two of the round's negative
    controls died here.
    """
    for ln in s61.split("\n"):
        if re.match(r"^\|\s*`##\s+Plan review`\s*\|", ln):
            return ln
    raise AssertionError(
        "WORKFLOW.md § 6.1 has no `## Plan review` table row (checked tolerantly "
        "for cell padding)")


def _config_table_rows() -> list[str]:
    """The `| ``## X`` | effect |` rows of configuration.md's knob table."""
    text = CONFIG_DOC.read_text(encoding="utf-8")
    # Scoped to the table that FOLLOWS the count sentence, not to every table on
    # the page -- configuration.md carries several. Widening the cell regex
    # without scoping the region swept in the overlay-files table too.
    anchor = re.search(r"are\s+pure\s+configuration", text, re.I)
    assert anchor, "configuration.md no longer states a pure-configuration count"
    region, started = [], False
    for line in text[anchor.end():].split("\n"):
        if line.startswith("|"):
            started = True
            region.append(line)
        elif started:
            break
    rows = []
    for line in region:
        # Match ANY first cell, then require the backticked `## X` shape. The
        # earlier regex skipped a row it could not parse, so a sixth knob written
        # `| **## Plan retention** |` left the stated count consistent with the
        # PARSER while the page listed one more knob than it claimed -- the exact
        # failure this module says it fixed. A malformed row is now a finding.
        m = re.match(r"^\|\s*([^|]+?)\s*\|", line)
        # Header detection by SHAPE, not by the literal word "Section": renaming
        # the column made every row parse as MALFORMED. A header is the row
        # immediately followed by the `|---` separator, so skip any row whose
        # first cell carries no backticked `## `.
        cell0 = m.group(1).strip()
        if not m or line.startswith("|---") or (
                "`" not in cell0 and "##" not in cell0 and len(cell0.split()) <= 3):
            continue
        cell = m.group(1).strip()
        inner = re.match(r"^`(##\s[^`]+)`$", cell)
        rows.append(inner.group(1).strip() if inner else "MALFORMED:" + cell)
    return rows


def test_the_knob_table_is_not_empty():
    """Non-vacuity: every check below passes over an empty table."""
    rows = _config_table_rows()
    assert len(rows) >= 4, f"the configuration.md knob table did not parse: {rows}"


def test_every_knob_row_is_well_formed():
    """A row the parser cannot read is a row the derived count cannot see."""
    bad = [r for r in _config_table_rows() if r.startswith("MALFORMED:")]
    assert not bad, (
        f"docs/configuration.md has knob rows the parser cannot read, so the derived "
        f"count silently excludes them: {bad}")


def test_the_knob_roster_matches_the_other_shipped_surface():
    """Cross-checked against WORKFLOW.md § 6.1 rather than asserted alone.

    The count check proves the sentence agrees with the PARSED ROWS; it proves
    nothing about the rows being the real knobs. The round swapped `## Merge
    policy` out for a fictitious one and stayed green. Two independently
    maintained surfaces have to agree.
    """
    page = {r for r in _config_table_rows() if not r.startswith("MALFORMED:")}
    s61 = _section_6_1()
    in_workflow = set(re.findall(r"^\|\s*`(##\s[^`]+)`\s*\|", s61, re.M))
    missing = page - in_workflow
    assert not missing, (
        f"docs/configuration.md lists knobs WORKFLOW.md § 6.1 does not: {sorted(missing)} -- "
        f"one of the two is describing a section no skill reads")
    for known in ("## Merge policy", "## Plan review", "## Sysop upstream repo",
                  "## Post-deploy verification", "## Pending documentation routing"):
        assert known in page, f"{known} dropped out of the configuration page's table"


def test_plan_review_is_in_the_configuration_page_table():
    rows = _config_table_rows()
    assert "## Plan review" in rows, (
        "`## Plan review` is a shipped consumer knob read by /claim-task Step 6 and it is "
        f"absent from docs/configuration.md's table. Rows found: {rows}"
    )


def test_the_stated_count_is_derived_from_the_table_not_asserted():
    """The count was 'Four' against five knobs for 67 phases. Derive it."""
    text = normalize(CONFIG_DOC.read_text(encoding="utf-8"))
    m = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b"
                  r"(?:\s+\w+){0,3}?\s+are\s+pure\s+configuration", text, re.I)
    assert m, ("docs/configuration.md no longer states how many pure-configuration sections "
               "there are -- the sentence is what tells a reader the table is complete")
    stated = _WORD_TO_INT[m.group(1).lower()]
    actual = len(_config_table_rows())
    assert stated == actual, (
        f"docs/configuration.md says {m.group(1)!r} pure-configuration sections and its table "
        f"has {actual} rows. A hand-maintained count is how `## Plan review` stayed invisible."
    )


def test_workflow_6_1_carries_both_the_row_and_the_template():
    """`configuration.md` promises 'Templates are in WORKFLOW.md § 6.1'. Hold it."""
    s61 = _section_6_1()
    assert re.search(r"^\|\s*`## Plan review`\s*\|", s61, re.M), (
        "WORKFLOW.md § 6.1's CLAUDE.md-section table has no `## Plan review` row")
    assert "**`## Plan review` template**" in s61, (
        "WORKFLOW.md § 6.1 has no `## Plan review` template, while configuration.md tells "
        "the reader templates live there")


def test_the_documented_values_are_the_ones_the_partial_resolves():
    """A doc naming a value the skill does not accept sends the consumer to
    configure something that silently falls through to the prompt."""
    # NOT normalized: `normalize()` strips backticks, so every `\`always\`` check
    # would pass on the bare word appearing anywhere in the prose.
    partial = PARTIAL.read_text(encoding="utf-8")
    for value in ("always", "never", "ask"):
        assert f"`{value}`" in partial, (
            f"the partial no longer resolves `{value}` -- the docs name it as a legal value")
    s61 = _section_6_1()
    row = _plan_review_row(s61)
    # Anchored to the VALUES CLAUSE, not the row. The row goes on to spell each
    # value again in its `always` -> option A mapping, so a whole-row membership
    # test passes while the enumeration that tells a consumer what is legal has
    # lost one -- the incidental-hit failure, found by the author-side battery
    # walking a mutation that dropped `ask` from the enumeration alone.
    m = re.search(r"\*\(optional[^)]*\)\*\s*(.+?)\.\s*Tells", row)
    assert m, ("WORKFLOW.md § 6.1's `## Plan review` row no longer opens with an "
               "enumeration of its legal values before 'Tells'")
    clause = m.group(1)
    for value in ("always", "never", "ask"):
        assert f"`{value}`" in clause, (
            f"WORKFLOW.md § 6.1's row enumerates {clause!r}, which omits the legal "
            f"value {value!r} -- a consumer reading only the enumeration cannot "
            f"discover it")


def test_all_three_surfaces_record_that_option_c_has_no_config_value():
    """C releases the claim, so a project defaulting to it never implements.
    Said in all three places, because a reader who meets only one of them and
    tries `plan-only` gets a silent fall-through to the prompt."""
    for path in (CONFIG_DOC, WORKFLOW, PARTIAL):
        text = path.read_text(encoding="utf-8")
        if path is CONFIG_DOC:
            # The landing table is deliberately terse: it names the per-run flag
            # rather than repeating the rationale.
            assert "--plan-only" in text, (
                "docs/configuration.md's Plan review row no longer names --plan-only, so a "
                "reader has no way to discover option C from the config page at all")
            continue
        assert states(text, "no config value for option C") or \
            states(text, "no value for option C"), (
            f"{path.name} no longer records that option C has no tier-2 config value")


def test_the_partial_and_the_docs_agree_on_who_the_flag_outranks():
    """Tier 1 beats tier 2. A doc that says otherwise makes `--plan-only` look
    overridable by config, which is the ordering the batch rejection depends on."""
    partial = normalize(PARTIAL.read_text(encoding="utf-8"))
    assert re.search(r"never prompt when tier 1 or tier 2 resolves", partial, re.I), (
        "the partial lost its never-prompt rule")
    s61 = _section_6_1()
    row = _plan_review_row(s61)
    assert "override it per run" in row, (
        "WORKFLOW.md § 6.1's row no longer says the flags override the config -- Step 1's "
        "--plan-only batch rejection exists precisely because tier 1 skips the Step 6 offer")
