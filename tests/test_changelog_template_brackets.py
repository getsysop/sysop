"""Phase 489 (`Q-751`, `wade-cms/sysop` #949): Step 4c's changelog and §6 templates write no
square brackets.

The rotation template was `- [<ID(s)>: ]<summary> (<original date>)`: an optional segment in
square brackets inside a code span that also holds literal markdown (`- `). Three GDP closes read
it literally and wrote `- [TASK-ID: ]summary` into the changelog. The §6 line
(`[<ID(s)> Complete:]`) and the bugfix row (`[<ID(s)> — ]`) had the same notation, and so did a
restatement in the rotation's MOVE rule. Each now spells out both shapes, so a literal
substitution of a template's placeholders is a correct line.

The templates are read from the skill, not restated here: every one-line code span in Step 4c
item 4 that holds a `<placeholder>` and starts like a §6 line (`<date>:`) or a changelog bullet
(`- `) is rendered and checked. Item 4's raw text, and every code span of the skill with its line
breaks joined, are scanned for a bracketed segment holding a placeholder or an id. Out of reach: a
bracket holding neither, outside the rendered population, and other optional notations (`{…}`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from skill_runner_text import text_of

REPO = Path(__file__).resolve().parent.parent
SKILL = text_of(REPO / "core" / "skills" / "review-close" / "SKILL.md")
FLAT = " ".join(SKILL.split())

# Step 4c item 4, where every changelog and §6 writer sits.
ITEM4 = SKILL[SKILL.index("**PROJECT_STATUS.md §6**"):SKILL.index("5. **Check what the writes above did")]

# GDP's own detector for the leaked shape, from the issue.
LEAKED = re.compile(r"^- \[[A-Z][A-Z0-9-]+: \]")

SUBS = {"<ID(s)>": "FEAT-12", "<summary>": "Search reads the new index",
        "<original date>": "2026-10-01", "<date>": "2026-10-01", "<Short Title>": "Index read",
        "<N>": "5", "<batch or branch list>": "batch 7"}


def _templates() -> list[str]:
    """Every code span in item 4 that holds a placeholder and writes a §6 or changelog line."""
    spans = re.findall(r"`([^`\n]+)`", ITEM4)
    return sorted({s for s in spans if "<" in s and re.match(r"(- |<date>:)", s)})


def _render(template: str) -> str:
    for k, v in SUBS.items():
        template = template.replace(k, v)
    return template


def test_the_population_is_the_writers():
    found = _templates()
    for expected in ("<date>: <ID(s)> Complete: <summary>", "<date>: <summary>",
                     "- <ID(s)>: <summary> (<original date>)", "- <summary> (<original date>)",
                     "- **<ID(s)> — <Short Title>**: <summary> (<date>)", "- **<Short Title>**: <summary> (<date>)"):
        assert expected in found, (expected, found)


# A bracketed segment holding a placeholder or an id: an optional segment in this notation.
# Literal brackets (`## [x.y.z] - <date>`, a `[good]` tag) hold neither.
OPTIONAL = re.compile(r"\[[^\]\[`]*(?:<|\bID)[^\]\[`]*\]")


def test_no_code_span_in_the_skill_brackets_a_placeholder():
    assert "these templates write no square brackets" in ITEM4
    for span in re.findall(r"`([^`\n]+)`", SKILL):
        assert not OPTIONAL.search(span), span
    # A span wrapped over a line break (CommonMark joins it), a fenced or plain-text template, and
    # a bracket that straddles backticks: item 4's raw text, and the skill's spans with lines joined.
    assert not OPTIONAL.search(ITEM4.replace("`", "")), "a bracketed placeholder in Step 4c item 4"
    for span in re.findall(r"`([^`]+)`", FLAT):
        assert not OPTIONAL.search(span), span
    for shape in ("- [<ID(s)>: ]<s>", "<date>: [ID Complete:] <s>", "- **[<ID> — ]<T>**"):
        assert OPTIONAL.search(shape), shape
    for literal in ("## [x.y.z] - <date>", "## GOOD-NNNN — <title> (<date>)  [good]"):
        assert not OPTIONAL.search(literal), literal


@pytest.mark.parametrize("template", _templates())
def test_a_literal_rendering_is_a_clean_line(template):
    line = _render(template)
    assert "[" not in line and "]" not in line and "<" not in line, line
    assert not LEAKED.match(line), line


@pytest.mark.parametrize("with_ids, without_ids", [
    ("`<date>: <ID(s)> Complete: <summary>`", "`<date>: <summary>` when the doc names no task ids"),
    ("`- <ID(s)>: <summary> (<original date>)`", "`- <summary> (<original date>)` when the line names no task ids"),
    ("Generate entry `- **<ID(s)> — <Short Title>**: <summary> (<date>)`", "`- **<Short Title>**: <summary> (<date>)` when it names none"),
    ("in the bugfix write's `- **<ID(s)> — <Short Title>**: <summary> (<date>)` shape",
     "`- **<Short Title>**: <summary> (<date>)` for an entry naming no task ids"),
])
def test_each_writer_spells_out_both_shapes(with_ids, without_ids):
    """The contract's pair is what a Consolidation-clause bullet with no ids reads."""
    i = FLAT.index(with_ids)
    assert FLAT.index(without_ids, i) - i < 200, "the no-ids shape must sit beside the with-ids one"
