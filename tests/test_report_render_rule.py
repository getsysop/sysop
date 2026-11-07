"""`/sitrep` and `/next-task` carry one rule for rendering their script's report, byte-identical.

Both skills exist to put a script's report in front of the human. The harness shows a Bash
call's stdout to the agent, not reliably to the human, so the report reaches the human only
when the agent's reply carries it. `/sitrep` Step 2 used to justify "print verbatim" with the
opposite premise ("the human is reading the same screen as you and re-summarization adds
latency"), and an agent that believed it concluded the paste was redundant and rendered
nothing. The rule now states the true premise, puts the report first and anything of the
agent's own after it, and is carried inline at both sites (`/next-task` is a `model: haiku`
skill that must not need a second file read).

Pinned here: the paragraph is present once in each file, the two copies are identical, its
text is hash-pinned (so a reworded pair that stays identical still goes red), its load-bearing
clauses are present, and neither file carries the false premise again.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SITES = {
    "sitrep": REPO_ROOT / "core/skills/sitrep/SKILL.md",
    "next-task": REPO_ROOT / "core/skills/next-task/SKILL.md",
}
LEAD = "**Show the human the script's output.**"
# sha256 of the paragraph's text (its lines joined, no trailing newline), first 16 hex digits.
# Change it only with the rule, and only in both skills at once.
RULE_SHA16 = "dc701b69eeeb5b6f"
FALSE_PREMISE = ("same screen", "re-summarization adds latency")


def _paragraph(text: str) -> str:
    """The paragraph that opens with LEAD, up to the next blank line. Exactly one is required."""
    starts = [m.start() for m in re.finditer(re.escape(LEAD), text)]
    assert len(starts) == 1, f"expected exactly one paragraph opening {LEAD!r}, found {len(starts)}"
    start = starts[0]
    assert start == 0 or text[start - 1] == "\n", f"{LEAD!r} must open its own paragraph"
    end = text.find("\n\n", start)
    return text[start:] if end == -1 else text[start:end]


@pytest.mark.parametrize("site", sorted(SITES))
def test_each_site_carries_the_rule_once(site):
    _paragraph(SITES[site].read_text(encoding="utf-8"))


def test_the_two_copies_are_identical():
    texts = {k: _paragraph(p.read_text(encoding="utf-8")) for k, p in SITES.items()}
    assert texts["sitrep"] == texts["next-task"], (
        "the render rule differs between /sitrep and /next-task; they carry one rule, "
        "byte-identical:\n" + "\n---\n".join(f"{k}: {v}" for k, v in texts.items())
    )


def test_the_rule_text_is_pinned():
    para = _paragraph(SITES["sitrep"].read_text(encoding="utf-8"))
    got = hashlib.sha256(para.encode("utf-8")).hexdigest()[:16]
    assert got == RULE_SHA16, (
        f"the render rule's text changed (sha16 {got}, pinned {RULE_SHA16}); if the change is "
        "intended, make it in both skills and update RULE_SHA16"
    )


@pytest.mark.parametrize("clause", [
    "not reliably to the human",            # the true premise: stdout is not the human's screen
    "your reply carries it",                # so the reply must carry it
    "verbatim and complete",
    "the first thing in your reply",        # report first ...
    "any line of your own comes after it",  # ... anything of the agent's own after it
    "no summary, paraphrase or reordering",
])
def test_the_rule_keeps_its_load_bearing_clauses(clause):
    assert clause in _paragraph(SITES["sitrep"].read_text(encoding="utf-8"))


@pytest.mark.parametrize("site", sorted(SITES))
def test_no_site_carries_the_false_premise(site):
    text = SITES[site].read_text(encoding="utf-8")
    for phrase in FALSE_PREMISE:
        assert phrase not in text, f"{site}: {phrase!r} is the false premise this rule replaced"


def test_sitrep_cross_reference_still_names_a_verbatim_rule():
    """Elsewhere in /sitrep, "Step 2's print-verbatim rule stands" points at this rule."""
    text = SITES["sitrep"].read_text(encoding="utf-8")
    step2 = text.split("## Step 2: Surface the Report", 1)[1].split("\n## ", 1)[0]
    assert "Step 2's print-verbatim rule stands" in text
    assert LEAD in step2 and "verbatim" in _paragraph(step2)


def test_sitrep_closing_line_comes_after_the_report():
    """The rule puts the report first; Step 2's own closing line must not contradict it."""
    text = SITES["sitrep"].read_text(encoding="utf-8")
    step2 = text.split("## Step 2: Surface the Report", 1)[1].split("\n## ", 1)[0]
    para = _paragraph(text)
    assert step2.index(para) < step2.index("After the verbatim report, add one closing line:"), (
        "Step 2's closing line is no longer placed after the report")
    assert "Before the verbatim report" not in step2


def test_next_task_states_the_rule_before_it_runs_the_resolver():
    text = SITES["next-task"].read_text(encoding="utf-8")
    assert text.index(_paragraph(text)) < text.index("```bash\npython3 sysop/scripts/next_task.py"), (
        "/next-task's runner meets the render rule only after it has run the resolver")
