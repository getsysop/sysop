"""Phase 222 (Q-275) — `/review-close` Step 2b's conventions paste, written once.

The `## Prevention Conventions` section was pasted identically into every
convention-reviewer prompt — 53,456 characters in the reference consumer, ~174k tokens
of the same text on a 13-agent close. The fix mirrors the diff's own paste-or-retrieve
threshold: at or below 10,000 characters the paste stays (the dominant small-project
path, no new failure mode); above it the orchestrator writes the section ONCE to
`sysop/runtime/2b-conventions.md` and every agent reads that same copy.

The tension the shipped prose itself stated — "nothing today pins that the orchestrator
and the agents agree on WHICH text is routed against" — is resolved by authorship, and
these tests pin the three load-bearing halves of that: the orchestrator's copy is the
authority, an agent must never fall back to its own worktree's `CLAUDE.md` (a branch
that edits the conventions would hand each reviewer a different taxonomy), and a
missing file fails closed rather than into an assumed taxonomy.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"


def _step2b() -> str:
    text = SKILL.read_text(encoding="utf-8")
    a = text.index("### 2b. Prevention Convention Check")
    b = text.index("### 2c.", a)
    return text[a:b]


def test_the_threshold_and_the_write_once_mechanism_exist():
    block = _step2b()
    flat = " ".join(block.split())
    assert "10,000 characters" in flat, (
        "Step 2b lost the conventions paste-or-write-once threshold (Q-275)"
    )
    assert "rm -f sysop/runtime/2b-conventions.md" in flat, (
        "the write-once file lost its rm-f-first loud-failure discipline — a run that "
        "skips the write would hand agents the previous close's conventions"
    )
    # ARMS BOUND TO BEHAVIOUR, not needles anywhere (round survivor CP-1 swapped the
    # arms with every needle intact): below-the-threshold must paste, above must
    # write once — the binding the diff threshold's own guard has had all along.
    assert re.search(r"[Aa]t or below 10,000, paste it into every prompt", flat), (
        "the below-threshold arm no longer pastes — the arms may be swapped (CP-1)"
    )
    assert re.search(r"Above 10,000, write it ONCE", flat), (
        "the above-threshold arm no longer writes once — the arms may be swapped (CP-1)"
    )


def test_the_threshold_number_is_the_same_number_everywhere():
    """Round survivor CP-4: the headline said 10,000 while an operative arm said 100,
    and only one of the two was pinned. Parse every threshold-position number in the
    paragraph and assert they are all equal."""
    block = _step2b()
    # Scope to the conventions paragraph — the same step carries the separate
    # 1,000-line DIFF threshold, which is test_review_close_2b_prompt's subject.
    a = block.index("Paste or write-once")
    b = block.index("Paste or retrieve", a)
    flat = " ".join(block[a:b].split())
    numbers = [
        n.rstrip(",")
        for n in re.findall(r"(?:threshold is|[Aa]t or below|Above) ([\d,]+)", flat)
    ]
    assert len(numbers) >= 3, f"expected >=3 threshold-position numbers, got {numbers}"
    assert len(set(numbers)) == 1, (
        f"the conventions threshold diverges between its statement sites: {numbers}"
    )


def test_the_write_rm_and_prompt_paths_are_one_path():
    """Round survivor CP-3: the write target drifted to a different basename while
    the rm and the prompt kept the old one — every large close would then STOP on a
    missing file. Extract every runtime conventions path in the block; one path."""
    block = _step2b()
    paths = set(re.findall(r"sysop/runtime/[\w-]*conventions[\w-]*\.md", block))
    assert paths == {"sysop/runtime/2b-conventions.md"}, (
        f"the rm / write / prompt conventions paths diverged: {sorted(paths)}"
    )


def test_the_agent_arm_pins_authority_and_fails_closed():
    block = _step2b()
    flat = " ".join(block.split())
    assert "Do NOT substitute your own worktree's CLAUDE.md" in flat, (
        "the prompt no longer pins WHICH text agents route against — each worktree "
        "checks out its branch's CLAUDE.md, so reviewers could diverge silently"
    )
    # The WHOLE fail-closed sentence, verbatim and whitespace-normalized, ending at
    # its period — the round's CP-2 turned "STOP" into a sentence prefix ("STOP only
    # if a second read also fails; otherwise fall back…") and the prefix check
    # stayed green. A continuation now changes the sentence and fails here.
    assert (
        "If the file is missing or empty, STOP and report exactly that instead of "
        "reviewing — a review against an assumed taxonomy is worse than no review."
    ) in flat, (
        "the fail-closed sentence was altered — if the reword was deliberate, update "
        "this pin in the same commit (Phase 168 precedent)"
    )
    for fail_open in ("otherwise fall back", "only if a second read"):
        assert fail_open not in flat, (
            f"the STOP arm carries a fail-open continuation ({fail_open!r})"
        )


def test_the_verbatim_requirement_survives_in_both_arms():
    """The original rule — every subsection, unfiltered — must hold whichever arm
    runs; the dedup must not become a licence to pre-filter."""
    block = _step2b()
    assert "do not pre-filter or rename subsections" in block
    assert "verbatim, every subsection, unfiltered" in block
