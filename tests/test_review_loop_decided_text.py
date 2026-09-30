"""Hash pins over the review-loop text Phase 329 decided (the `Q-606` bundle pilot).

The phase's own guards tie prose to code: a state name, a lock field, a registry
filter. Its round then walked 29 meaning-reversing edits through them, because
a substring check survives a negation, a qualifier or a contradicting sentence
beside the right one. The fix `test_fix_in_branch_tier.py` uses for the same
class is a hash over the decided span, and this module shares its normalizer,
span context and liveness check (`_pin_norm`, `_pin_span`, `_pin_liveness`). A
re-wrap or a list-marker swap keeps a hash; anchors carry no list marker, so a
swap on an anchor line keeps the slice too.

What a hash alone cannot see is checked separately: a span wrapped whole in an
HTML comment, and a span that should be live sitting inside a fence.

**A red here is not necessarily a defect.** If the edit is a deliberate change
to one of these rules, move its pin in the same commit (regenerate with
`_print_pins()`) and say so in the phase record.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from _reversal import slice_between
from test_fix_in_branch_tier import (_anchor_count, _pin_hash, _pin_liveness, _pin_norm, _pin_quoted,
                                     _pin_span)

REPO = Path(__file__).resolve().parents[1]
CR = REPO / "core" / "skills" / "codebase-review" / "SKILL.md"
SA = REPO / "core" / "skills" / "security-audit" / "SKILL.md"
CC = REPO / "core" / "skills" / "contribute-convention" / "SKILL.md"
PWT = REPO / "core" / "skills" / "_shared" / "promotion-write-target.md"
FANOUT = REPO / "core" / "skills" / "_shared" / "fanout-evidence.md"
WF = REPO / "core" / "companion" / "docs" / "WORKFLOW.md"
INSTALL_DOC = REPO / "docs" / "install-and-update.md"
MONOGRAPH = REPO / "docs" / "workflow.html"

_NEXT_BULLET = re.compile(r"\n\s*[-*+] ")

# label: (path, start, end, fenced). Starts carry no list marker. `fenced` marks a span that
# belongs inside its fence (a template); `_pin_liveness` checks it both ways.
SPANS: dict[str, tuple[Path, object, object, bool]] = {}
for _name, _path in {"codebase-review": CR, "security-audit": SA}.items():
    SPANS.update({
        f"{_name} 2b accounting": (_path, "**Read the pre-scan accounting block", "**Stale-rule capture", False),
        f"{_name} 5b reconciliation": (_path, "> **Reconciliation:**", "\n\n", True),
        f"{_name} step 6 pre-scan": (_path, "Pre-scan:  ", "\nLLM agents:", True),
        f"{_name} step 9 gate": (_path, "**Apply the cross-round survival gate", "**Cleared the gate", False),
        f"{_name} option ii": (_path, "**(ii) `.claude/semgrep/*.yaml` AST rule**", "**(iii) `sysop/scripts/hooks/pre-commit` regex**", False),
        f"{_name} option iii step 3": (_path, "On approval: append to `sysop/scripts/hooks/pre-commit`", "On skip: log the reason", False),
        f"{_name} 9b retire and demote": (_path, "`semgrep`: delete `.claude/semgrep/<rule>.yaml`", "**tighten** —", False),
        f"{_name} 9b steps 4-5": (_path, "**Emit demotion summary**", "The `.project.*` overlay paths cover", False),
    })
SPANS.update({
    "codebase-review 5b mapping": (CR, "Fill each field from the Step 3-0b row", "\n\n", False),
    "security-audit 5b mapping": (SA, "Fill each `Reconciliation:` field from the Step 3-0b row", "\n\n", False),
    "security-audit 5b own line": (SA, "**The reconciliation counts get their own line", "\n\n", False),
    "security-audit 3c trust arms": (SA, "**`trust.status` is exactly one of", "**`skipped` reports**", False),
    "security-audit step 6 ingested": (SA, "Ingested (claude-security):", "\n", True),
    "contribute-convention step 2": (CC, "## Step 2: Parse the overlay into candidate conventions", "## Step 3:", False),
    "contribute-convention step 3": (CC, "## Step 3: Discover provenance for each candidate", "## Step 4", False),
    "contribute-convention body template": (CC, "Mechanical checks (grep / semgrep), if applicable:", "\n\n", True),
    "promotion-write-target table and demotion": (PWT, "## What to write where (consumer install)", "## Why not overlay-only", False),
    "promotion-write-target why not overlay-only": (PWT, "## Why not overlay-only", "Hence the dual-write.", False),
    # Ends at the next item, not at "\n": the bullet is one line, so a re-wrap cut it short.
    "fanout-evidence pre-scan bullet": (FANOUT, "**The deterministic pre-scan does not count toward `grepped`.**", _NEXT_BULLET, False),
    "WORKFLOW 3.5 gate item": (WF, "Reviewer evaluates each candidate interactively against the **cross-round survival gate**", "For promoted candidates:", False),
    "WORKFLOW 3.5 write-target note": (WF, _pin_quoted("**Where promoted content is written"), _pin_quoted("**Why promotion runs in-session:**"), False),
    "WORKFLOW 3.5 cross-round note": (WF, _pin_quoted("**Why cross-round survival (not in-round burst):**"), "\n\n", False),
    "WORKFLOW 6.5 accounting": (WF, "**Execution accounting (the summary block).**", "```", False),
    "WORKFLOW 8.2b step 6": (WF, "Run the install pipeline — overwriting managed paths freely", "Handle drops:", False),
    "WORKFLOW 8.2c fail-closed": (WF, "**Fail-closed on shadow-reconstruction failure.**", _NEXT_BULLET, False),
    "install-and-update update mode": (INSTALL_DOC, "The underlying `--update` mode snapshots", "\n\n", False),
    "install-and-update fail-closed": (INSTALL_DOC, "**Fail-closed posture.**", "\n\n", False),
    "monograph map entry": (MONOGRAPH, "Each entry is a glob pattern and a one-line rule, plus provenance.", "</p>", False),
})

PINS = {
    # Regenerate with:  .venv/bin/python3 -c "import sys; sys.path.insert(0,'tests'); import test_review_loop_decided_text as T; T._print_pins()"
    "codebase-review 2b accounting": "aa515860563dec15",
    "codebase-review 5b reconciliation": "e1e8bd16f8563fc7",
    "codebase-review step 6 pre-scan": "7f721ed604cf16e6",
    "codebase-review step 9 gate": "1010613ab10fe3ba",
    "codebase-review option ii": "d431bfa721adef13",
    "codebase-review option iii step 3": "fc84f95e8c662dbd",
    "codebase-review 9b retire and demote": "3834cef35cce7700",
    "codebase-review 9b steps 4-5": "f7c60985604fd918",
    "security-audit 2b accounting": "3e17dfb5539c103c",
    "security-audit 5b reconciliation": "3cac4c1f1e69563c",
    "security-audit step 6 pre-scan": "decfecf67fd86e2b",
    "security-audit step 9 gate": "1010613ab10fe3ba",
    "security-audit option ii": "d431bfa721adef13",
    "security-audit option iii step 3": "fc84f95e8c662dbd",
    "security-audit 9b retire and demote": "ffeaf910e8b4b7ca",
    "security-audit 9b steps 4-5": "f49bb9e5d803e7a5",
    "codebase-review 5b mapping": "3aaa6eed58591db4",
    "security-audit 5b mapping": "bcf1282a246654c6",
    "security-audit 5b own line": "a45fffaa2b5b853e",
    "security-audit 3c trust arms": "564ac7d4a4fc3ffa",
    "security-audit step 6 ingested": "c0820d029cad71c1",
    "contribute-convention step 2": "38b38d03c5b3b048",
    "contribute-convention step 3": "85e907512ed49854",
    "contribute-convention body template": "59773a1487c5df10",
    "promotion-write-target table and demotion": "5e183f1b5e881074",
    "promotion-write-target why not overlay-only": "d41c2789591bbb13",
    "fanout-evidence pre-scan bullet": "863e77d5bcc095e0",
    "WORKFLOW 3.5 gate item": "4ef1b30d1831e026",
    "WORKFLOW 3.5 write-target note": "3341084e0ac9a792",
    "WORKFLOW 3.5 cross-round note": "ff5775e2d5683bf2",
    "WORKFLOW 6.5 accounting": "e59989d78f519947",
    "WORKFLOW 8.2b step 6": "37abadb0b9c2dd07",
    "WORKFLOW 8.2c fail-closed": "de81467ace59de53",
    "install-and-update update mode": "4cfe30206613f58e",
    "install-and-update fail-closed": "6ffeff101cc878e2",
    "monograph map entry": "ffa17d7e98e31639",
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
def test_the_decided_review_loop_text_is_pinned(label: str) -> None:
    got = _pin_hash(_span(label))
    assert label in PINS, f'{label}: no pin recorded; add "{label}": "{got}"'
    assert got == PINS[label], (
        f"{label} changed (hash {got}, pinned {PINS[label]}). Phase 329 decided this text "
        "against the code it describes. If the edit is deliberate, move the pin in the same "
        "commit and record why; if not, it is the reversal this pin exists to stop.")


@pytest.mark.parametrize("label", sorted(SPANS))
def test_every_span_start_anchor_is_unique(label: str) -> None:
    """A decoy copy of the start anchor earlier in the file would become the slice."""
    path, start, _, _ = SPANS[label]
    assert _anchor_count(path.read_text(encoding="utf-8"), start) == 1, label


@pytest.mark.parametrize("label", sorted(SPANS))
def test_every_span_is_live(label: str) -> None:
    """A hash is kept when the whole span is wrapped from outside its anchors: an HTML
    comment around it, or a fence around a span no reader should meet as a code block."""
    text, _, at = _located(label)
    problem = _pin_liveness(SPANS[label][0], text, at, SPANS[label][3])
    assert problem is None, f"{label} {problem}"




def test_every_pin_has_a_span() -> None:
    assert set(PINS) == set(SPANS), set(PINS) ^ set(SPANS)
