"""Hash pins over the `/review-close` text Phase 330 decided (`Q-568`, `Q-528`, `Q-580`,
`Q-609`), in the shape `test_review_loop_decided_text.py` uses for Phase 329's.

The behaviour these spans describe is executed elsewhere
(`test_review_close_smoke_held_and_tip.py`, `test_prescan_merge_gate.py`). What a test
cannot execute is the prose the runner acts on: the four answer options, the halt rule
that asks transient from structural, the filing and its stop path, what gets recorded
and what never is, and the Exit 0 arm's markers. A substring check survives a negation or
a contradicting sentence beside the right one; a hash over the decided span does not. A
re-wrap or a list-marker swap keeps a hash, and anchors carry no list marker.

**A red here is not necessarily a defect.** If the edit is a deliberate change to one of
these rules, move its pin in the same commit (regenerate with `_print_pins()`) and say so
in the phase record.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from _reversal import slice_between
from test_fix_in_branch_tier import (_anchor_count, _pin_hash, _pin_liveness, _pin_norm, _pin_quoted,
                                     _pin_span)

REPO = Path(__file__).resolve().parents[1]
CLOSE = REPO / "core" / "skills" / "review-close" / "SKILL.md"
SCHEMA = REPO / "core" / "companion" / "tasks" / "schema.md"

# label: (path, start, end, fenced). Starts carry no list marker. `fenced` marks a span that
# belongs inside its fence (a template); `_pin_liveness` checks it both ways.
SPANS: dict[str, tuple[Path, object, object, bool]] = {
    "3c output contract": (CLOSE, "If the output's first line is `NO_SMOKE_REQUIRED`",
                           "**2. For each signal, call `AskUserQuestion`.**", False),
    "3c options": (CLOSE, "**2. For each signal, call `AskUserQuestion`.**", "**3. Halt rules.**", False),
    "3c halt rules": (CLOSE, "**3. Halt rules.**", "**4. Record outcomes for Step 8.** The tally", False),
    "3c record": (CLOSE, "**4. Record outcomes for Step 8.** The tally",
                  'python3 - "<the doc the KEY line names>"', False),
    "3c refusal": (CLOSE, "A `REFUSING:` line records nothing and changes nothing.",
                   "## Step 3b: Prepare Worktrees for Merge", False),
    # Round 1 (lens 2): prose this phase decided, outside every span, took a contrary rule with
    # the phase's guards green. These three spans and the widened refusal span close that for
    # the phase's own text; older Step 3c prose stays unpinned (round 2, `Q-560`'s class).
    "3c intro": (CLOSE, "Some features can't be verified by automated checks", "\n\n", False),
    "3c step-1 output": (CLOSE, "Its first line is either `NO_SMOKE_REQUIRED`", "\n\n", False),
    "3c linkage": (CLOSE, _pin_quoted("**Task linkage also has two sources"), "\n\n", False),
    "4a-post exit 0": (CLOSE, "**Exit 0** — **not automatically clean", "**Non-zero** —", False),
    "step 8 manual smoke": (CLOSE, "Manual smoke:  <N confirmed", "\nVerification:", True),
    "step 8 pre-scan": (CLOSE, "pre-scan <clean | clean, but not every check",
                        "| ran via the consumer's list", True),
    "schema skill behavior": (SCHEMA, "**Skill behavior** (`/review-close` Step 3c", "\n\n", False),
}

PINS = {
    # Regenerate with:  .venv/bin/python3 -c "import sys; sys.path.insert(0,'tests'); import test_review_close_smoke_decided_text as T; T._print_pins()"
    "3c output contract": "2dd2a14660579a39",
    "3c options": "9022a45b7926f32a",
    "3c halt rules": "74bd2d12112979b5",
    "3c record": "257fec96033c498d",
    "3c refusal": "d5d42a639763dde9",
    "3c intro": "8a9df11a5daf57a3",
    "3c step-1 output": "c59c69994350f6ba",
    "3c linkage": "04a0fa5c5e862fda",
    "4a-post exit 0": "59cb35e6d31276bc",
    "step 8 manual smoke": "4fc5300eebcf6176",
    "step 8 pre-scan": "c94d934f525d174f",
    "schema skill behavior": "a1b984728c161bff",
}


def _located(label: str) -> tuple[str, str, int]:
    path, start, end, _ = SPANS[label]
    text = path.read_text(encoding="utf-8")
    span = slice_between(text, start, end, label)
    return text, span, text.index(span)


def _span(label: str) -> str:
    """The slice, with the context `_pin_span` puts back (first-line indentation, and the
    enclosing fence's opener)."""
    text, span, at = _located(label)
    span = _pin_span(SPANS[label][0], text, at, span)
    assert len(_pin_norm(span)) > 60, f"{label}: the pinned span is nearly empty — anchors drifted"
    return span


def _print_pins() -> None:
    for label in SPANS:
        print(f'    "{label}": "{_pin_hash(_span(label))}",')


@pytest.mark.parametrize("label", sorted(SPANS))
def test_the_decided_smoke_gate_text_is_pinned(label: str) -> None:
    got = _pin_hash(_span(label))
    assert label in PINS, f'{label}: no pin recorded; add "{label}": "{got}"'
    assert got == PINS[label], (
        f"{label} changed (hash {got}, pinned {PINS[label]}). Phase 330 decided this text. "
        "If the edit is deliberate, move the pin in the same commit and record why; if not, "
        "it is the reversal this pin exists to stop.")


@pytest.mark.parametrize("label", sorted(SPANS))
def test_every_span_start_anchor_is_unique(label: str) -> None:
    path, start, _, _ = SPANS[label]
    assert _anchor_count(path.read_text(encoding="utf-8"), start) == 1, label


@pytest.mark.parametrize("label", sorted(SPANS))
def test_every_span_is_live(label: str) -> None:
    text, _, at = _located(label)
    problem = _pin_liveness(SPANS[label][0], text, at, SPANS[label][3])
    assert problem is None, f"{label} {problem}"


def test_every_pin_has_a_span() -> None:
    assert set(PINS) == set(SPANS), set(PINS) ^ set(SPANS)
