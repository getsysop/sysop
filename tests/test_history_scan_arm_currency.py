"""The arm list is derived from the script, never restated on trust.

`Q-300` (Phase 233) promoted the `content` and `names` arms of
`tools/scan_public_history.sh` to gating arms and did not touch the runbook
paragraph that described them.  The page then told an operator, for 32 phases,
that a red `content:` or `names:` arm was informational -- in the direction
where a real leak reads as advisory and the cut proceeds.  Nothing was red in
between, because nothing related the page to the script.

Phase 265 corrected the prose.  That alone buys one dated snapshot: its own
round mutated the corrected sentence back to the false form and every guard in
the tree stayed green (16 of 18 mutations survived).  These tests are the part
that makes the fix durable -- they derive the arm set from the script and
require every surface that restates it to agree.

Scope, stated so a later reader does not over-read it: this pins the arm COUNT
and the arm NAMES and the presence of the halt instruction.  It cannot judge
whether the surrounding prose is otherwise true.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "scan_public_history.sh"
RUNBOOK = REPO_ROOT / "tools" / "TESTER_MIRROR_RUNBOOK.md"
ACCEPTED = REPO_ROOT / "tools" / "public_history_accepted.txt"

# The one place the arm set is a fact rather than a claim: a `fail=1` next to a
# `new_<arm>` counter bump.  Anchored to leading whitespace and the counter name
# so a PROSE mention of `fail=1` in a comment cannot inflate the count -- the
# naive `grep -c 'fail=1'` returns 7 against this file's real 4.
_ARM_SITE = re.compile(r"^ +new_([a-z]+)\s*=.*fail=1", re.M)

_NUMBER_WORD = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}

# `new_msg` is the counter; `message:` is what every surface calls it.
_COUNTER_TO_PUBLIC = {"msg": "message"}


def _read(p: Path) -> str:
    if not p.exists():
        pytest.skip(f"{p.name} absent")
    return p.read_text()


def _norm(s: str) -> str:
    """Collapse whitespace runs so a phrase check survives a reflow.

    A guard keyed to a physical line is walked through by nothing more hostile
    than a line wrap -- this module's own first cut went red when a sentence it
    required was rewrapped across two lines, which is the bypass the author-side
    pass warns about, in the guard written to close it.
    """
    return " ".join(s.split())


def _arms() -> set[str]:
    return {
        _COUNTER_TO_PUBLIC.get(m, m) for m in _ARM_SITE.findall(_read(SCRIPT))
    }


def test_the_arm_derivation_is_not_vacuous():
    """The population this whole module rests on must be real and plural.

    A regex that stops matching returns an empty set, and every assertion below
    would then pass by describing nothing.  This is the control.
    """
    arms = _arms()
    assert len(arms) >= 2, (
        f"derived only {sorted(arms)} gating arms from {SCRIPT.name}. Either the "
        "script changed shape or _ARM_SITE stopped matching -- in both cases the "
        "rest of this module is measuring nothing."
    )
    assert "content" in arms and "header" in arms, (
        f"derived {sorted(arms)}; content and header are the two arms that have "
        "carried adjudications since Q-294/Q-300, so their absence means the "
        "regex broke rather than the script shrinking."
    )


def test_the_runbook_states_the_gating_arm_count_the_script_implements():
    """`All four GATE.` -- and `four` is checked against the script.

    This is the assertion that would have gone red at Phase 233 instead of
    thirty-two phases later. It also kills the softening mutation: `All four
    generally gate` does not match, because a hedge on this sentence is the
    same defect as a wrong number.
    """
    arms = _arms()
    word = _NUMBER_WORD.get(len(arms))
    assert word, f"no number word for {len(arms)} arms; extend _NUMBER_WORD"
    needle = f"All {word} GATE."
    assert needle in _norm(_read(RUNBOOK)), (
        f"{RUNBOOK.name} does not carry the exact sentence fragment {needle!r}. "
        f"{SCRIPT.name} sets fail=1 on {len(arms)} arms ({sorted(arms)}), so the "
        "runbook must say so in those words. This guard exists because the page "
        "said the opposite for 32 phases and nothing noticed."
    )


def test_the_script_header_states_the_same_count():
    """The script's own header restates the arm count too -- same exposure."""
    arms = _arms()
    word = _NUMBER_WORD[len(arms)].upper()
    assert f"{word} SEPARATE ARMS" in _norm(_read(SCRIPT)), (
        f"{SCRIPT.name}'s header no longer says {word!r} SEPARATE ARMS while its "
        f"code gates on {len(arms)}. The header said TWO for two phases past the "
        "commit that made it three."
    )


def test_every_gating_arm_is_named_in_the_runbook():
    """A count with no names lets an arm be silently swapped."""
    text = _norm(_read(RUNBOOK))
    missing = [a for a in sorted(_arms()) if f"`{a}" not in text]
    assert not missing, (
        f"{RUNBOOK.name} never names these gating arms: {missing}. An operator "
        "reading a per-commit row cannot map a red column to a remedy."
    )


def test_the_runbook_names_the_accepted_findings_file():
    """The gate is useless if the operator cannot record an adjudication.

    The runbook mentioned this file ZERO times until Phase 265, so a new
    finding stopped the cut with no documented way to clear it.
    """
    assert ACCEPTED.name in _norm(_read(RUNBOOK)), (
        f"{RUNBOOK.name} no longer names {ACCEPTED.name}, which is the only "
        "place an adjudication counts."
    )


def test_the_runbook_keeps_the_halt_instruction():
    """The one sentence that stops a cut over a real leak.

    Named explicitly because the round's sharpest surviving mutation inverted
    it to `you may proceed` with the whole suite green.
    """
    assert "**the cut stops here**" in _norm(_read(RUNBOOK)), (
        f"{RUNBOOK.name} lost the halt instruction for an unintended finding. "
        "An identity in a published commit is immutable; this sentence is the "
        "only thing on the page that tells the operator not to push past one."
    )


def test_the_inspection_block_gates_its_greps_behind_the_refusal():
    """`Q-394`: a refusing arm that does not block is not a refusal.

    The block derives `P1A` and `IDENTITY_EMAIL` from another script.  When that
    derivation fails -- wrong CWD is the ordinary way -- an empty `P1A` does not
    silence the greps, it makes them match EVERY line: ~190,000 on the content
    arm, which scrolls any warning off the screen.  So the warning has to gate
    the commands rather than precede them.

    Phase 265 shipped the first cut of this block with a bare `echo` and a
    rationale that had the failure backwards; both halves were caught by running
    it.  This pins the shape, not the wording.
    """
    text = _norm(_read(RUNBOOK))
    assert "REFUSING:" in text, (
        f"{RUNBOOK.name}'s step-5 inspection block lost its refusal message."
    )
    assert 'if [ -n "${P1A// /}" ]' in text and "else" in text, (
        "the refusal is no longer an `if`/`else` gating the greps. A bare echo "
        "followed by the commands is Q-394's defect: the operator is warned and "
        "then buried under ~190k matching lines."
    )


def test_the_runbook_says_the_arm_lists_are_not_interchangeable():
    """Filing a SHA under the wrong arm clears nothing, silently.

    `tools/scan_public_history.sh` calls `_accepted` once per arm against a
    separate list.  A maintainer who believes one entry clears a commit will
    file it once and read the still-red run as a new finding -- or worse, add it
    to whichever arm makes the run green.
    """
    assert "**not interchangeable**" in _norm(_read(RUNBOOK)), (
        f"{RUNBOOK.name} no longer states that the accepted-findings arms are "
        "not interchangeable."
    )


def test_the_runbook_states_the_per_commit_row_shape():
    """The row is counts, not lines -- and the shape names every arm in order.

    An operator who thinks the row prints findings will read `content:1` as one
    line of evidence rather than as a number needing its own investigation.
    """
    arms_in_order = ["content", "names", "header", "message"]
    # single space: _norm collapses the row's column padding
    expected = " ".join(f"{a}:N" for a in arms_in_order)
    assert expected in _norm(_read(RUNBOOK)), (
        f"{RUNBOOK.name} no longer carries the per-commit row shape "
        f"{expected!r}. Derived arms: {sorted(_arms())}."
    )


def test_the_block_derives_both_variables_rather_than_pasting_them():
    """`P1A` and `IDENTITY_EMAIL` live in another script; a paste is a phantom.

    Phase 169's class -- the filed 20 sites were 33.  Both are needed: without
    `IDENTITY_EMAIL` the content line is not the arm, it is a 19-line
    approximation of a 1-line answer.
    """
    # LIVE lines only. `"P1A=" in text` is satisfied by `# P1A=...`, which is
    # the substring-accepts-an-incidental-use bypass -- this guard's own first
    # cut had it, and a commented-out derivation is exactly the mutation that
    # leaves the operator pasting a phantom.
    live = [
        ln.strip() for ln in _read(RUNBOOK).splitlines()
        if not ln.strip().startswith("#")
    ]
    for var in ("P1A=", "IDENT="):
        assert any(ln.startswith(var) for ln in live), (
            f"{RUNBOOK.name}'s step-5 block no longer derives {var.rstrip('=')} "
            "on a live line. A pasted literal goes stale against "
            "cut_public_release.sh silently; a commented one is not a derivation."
        )


def test_the_page_states_what_an_empty_pattern_actually_does():
    """An empty ERE matches EVERY line -- the rationale for gating the greps.

    This assertion exists because the sentence was shipped backwards. If a
    later editor 'corrects' it back to "matches nothing", the reason for the
    `if` disappears and the `if` becomes an easy deletion.
    """
    text = _norm(_read(RUNBOOK))
    assert "an empty ere matches every line" in text.lower(), (
        f"{RUNBOOK.name} no longer states that an empty pattern matches every "
        "line. That fact is the whole argument for gating the greps behind the "
        "refusal rather than warning ahead of them."
    )
