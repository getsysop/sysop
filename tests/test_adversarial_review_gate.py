"""Phase 154 — the adversarial round is a gate, and the shipped procedure says how to run it.

Two surfaces. `CLAUDE.md` carries the *gate*; `_shared/adversarial-review.md` carries the
*procedure*, and ships to consumers.

**These guards test whether the rules BIND, not whether particular words are present.** The
first draft pinned vocabulary, and its own adversarial round retired the gate with every
test green — adding "docs-only phases are exempt by default", softening rule 1 to
"Consider", declaring the section "guidance rather than requirements", and deleting the
round from the close-out step list all passed. 20 of 30 mutations survived. A guard that
green-lights a document stating the opposite of the rule is worse than no guard: it
reports the gate as protected while it is being dismantled, which is this repo's own
"a dead review looks like a clean one" thesis turned on the review step itself.

So the shape here is: two predicate functions that return a list of *problems*, run against
the real files (expect none) and against a deliberately softened document (expect the
specific problems back). The softened fixtures are the mutations that survived the first
round, verbatim — a twin that calls the production predicate cannot pass while the
predicate is neutered, which the first draft's `|| true`-style inline twins could.

Scoping is likewise load-bearing and got fixed twice: `CLAUDE.md` is 71% Phase log table
and grows every phase, so a whole-file check is eventually satisfied by a changelog row,
and the partial's other sections satisfied deletions from this one.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PARTIAL = REPO_ROOT / "core" / "skills" / "_shared" / "adversarial-review.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

# Skills that spawn agents into a worktree an earlier step already created. The procedure
# must carve these out, or its universal-sounding isolation rule contradicts them.
PRE_EXISTING_WORKTREE_SKILLS = ("claim-task", "auto-build", "auto-fix", "auto-judge")


def _partial() -> str:
    return PARTIAL.read_text(encoding="utf-8")


def _claude_md() -> str:
    """This repo's own always-loaded instructions — maintainer-side, not shipped.

    ``CLAUDE.md`` is deliberately removed from the public mirror
    (``tools/make_public_mirror.sh``), so the three tests that assert the phase-close
    gate lives in it cannot run there. Until Phase 160 they did not skip, they
    ``FileNotFoundError``-ed: the sterilized tree failed 3 tests and, since the public
    repo runs ``pytest`` as a required check, the next snapshot PR would have gone red
    on CI. It went unnoticed because Phase 154 added this file two days after the last
    cut, and nothing runs the suite against the sterilized tree except a cut.

    Skipping is correct rather than convenient — the file genuinely is not part of what
    ships, and the rest of this module (the guards over ``_shared/adversarial-review.md``,
    which *is* shipped) keeps running for consumers. The skip is explicit and states its
    reason, so it can never read as a pass.
    """
    if not CLAUDE_MD.is_file():
        pytest.skip(
            "CLAUDE.md is maintainer-side and excluded from the public mirror; "
            "the gate-placement guards only apply in the source repo"
        )
    return CLAUDE_MD.read_text(encoding="utf-8")


def _gate_paragraph() -> str:
    """The gate, sliced robustly.

    The first draft anchored on the exact bolded sentence and sliced to the next blank
    line. Three plausible copy-edits broke it: un-bolding raised a bare `ValueError`
    (losing the assertion messages that are the whole teaching mechanism), reflowing the
    gate into two paragraphs produced a false positive, and *removing* a blank line let the
    slice swallow the next paragraph and satisfy an assertion the gate no longer met.

    Anchored emphasis-insensitively on the sentence's words, and bounded by the next
    markdown heading — a stable boundary that a reflow cannot move.
    """
    text = _claude_md()
    m = re.search(r"A phase is not done until an adversarial round has run", text)
    assert m, (
        "the gate sentence is gone from CLAUDE.md entirely — a phase can now close with no "
        "adversarial round and nothing says otherwise"
    )
    start = text.rfind("\n\n", 0, m.start()) + 2
    nxt = text.find("\n## ", start)
    return text[start:nxt if nxt != -1 else len(text)]


def _multi_reviewer_section() -> str:
    text = _partial()
    m = re.search(r"^##\s+Running more than one reviewer\s*$", text, re.M)
    assert m, "the multi-reviewer section is gone — consumers are back to guessing"
    nxt = text.find("\n## ", m.end())
    return text[m.start():nxt if nxt != -1 else len(text)]


# --------------------------------------------------------------------------------------
# Predicates. Tests below run THESE against the real files and against softened fixtures,
# so a neutered predicate fails its own twin.
# --------------------------------------------------------------------------------------

# Language that converts a requirement into a preference. Matched against the gate and the
# procedure; each survived the first adversarial round as a live mutation.
_HEDGES = (
    r"consider (?:giving|assigning|running)",
    r"guidance rather than requirements",
    r"usually enough",
    r"where practical",
    r"if time (?:permits|allows)",
    r"at your discretion",
    r"rounds are (?:optional|encouraged)",
)

# Blanket escape hatches. A per-phase recorded skip is the sanctioned exit; a standing rule
# that pre-authorises skipping a whole CLASS of phase is not, because the classes people
# reach for ("docs-only", "small diff") are exactly where an unchallenged claim ships.
_BLANKET_EXEMPTIONS = (
    r"are exempt",
    r"is exempt",
    r"exempt by default",
    r"skipped unless noted",
    r"unless the change is (?:small|trivial|minor)",
    r"under ~?\d+ (?:changed )?lines are",
)


def gate_problems(gate: str) -> list[str]:
    """Everything that would stop the gate from binding."""
    problems = []
    if not re.search(r"gate, not a suggestion", gate, re.I):
        problems.append("gate no longer asserts it is a gate rather than advice")
    if not re.search(r"not a decision to bring to the human|do not ask|without asking", gate, re.I):
        problems.append(
            "gate lost the AUTHORITY clause — the documented failure was raising the round "
            "and waiting for permission, not forgetting it exists"
        )
    if not re.search(r"no standing exemptions", gate, re.I):
        problems.append("gate no longer forbids standing exemptions")
    if not re.search(r"recorded", gate, re.I):
        problems.append("skipping is no longer required to be recorded")
    if not re.search(r"_shared/adversarial-review\.md", gate):
        problems.append("gate no longer points at the procedure")
    if not re.search(r"Running more than one reviewer", gate):
        problems.append("gate no longer names the procedure's section")
    for pat in _HEDGES:
        if re.search(pat, gate, re.I):
            problems.append(f"gate hedged with {pat!r}")
    for pat in _BLANKET_EXEMPTIONS:
        if re.search(pat, gate, re.I):
            problems.append(f"gate carries a blanket exemption: {pat!r}")
    return problems


def section_problems(section: str) -> list[str]:
    """Everything that would stop the procedure from binding."""
    problems = []
    required = {
        "commit-first": r"commit before the round starts|commit before you review",
        "no-tree-mutation": r"must not mutate the working tree",
        "verify-your-revision": r"verify \*\*at the start\*\*|contains the commits under review",
        "git-show-comparison": r"git show <sha>:<path>",
        "no-consensus-weighting": r"never weight findings by how many",
        "premise-vs-conclusion": r"confirmed premise is not a confirmed conclusion",
        "distinct-lenses": r"assign each a different lens",
        "never-forks": r"never forks",
    }
    for name, pat in required.items():
        if not re.search(pat, section, re.I):
            problems.append(f"procedure lost its {name} rule")
    for pat in _HEDGES:
        if re.search(pat, section, re.I):
            problems.append(f"procedure hedged with {pat!r}")
    # The isolation carve-out. Without it the section's rule contradicts seven shipped
    # "Do NOT set isolation" instructions in the skills that consume this very partial.
    if re.search(r'isolation: .worktree.', section):
        if not re.search(r"do not use it where a worktree already exists", section, re.I):
            problems.append("isolation rule lost its pre-existing-worktree carve-out")
        missing = [s for s in PRE_EXISTING_WORKTREE_SKILLS if f"/{s}" not in section]
        if missing:
            problems.append(f"carve-out no longer names the affected skills: {missing}")
        if not re.search(r"does not guarantee the revision", section, re.I):
            problems.append(
                "isolation rule no longer warns that it can hand you the wrong revision"
            )
    return problems


# --------------------------------------------------------------------------------------
# The real files must have no problems
# --------------------------------------------------------------------------------------

def test_the_gate_binds():
    assert gate_problems(_gate_paragraph()) == []


def test_the_procedure_binds():
    assert section_problems(_multi_reviewer_section()) == []


# --------------------------------------------------------------------------------------
# ...and the predicates must reject the mutations that survived the first round
# --------------------------------------------------------------------------------------

_SOFTENED_GATE = """\
**A phase is not done until an adversarial round has run.** This is worth doing.
Phases that are docs-only, test-only, or under ~200 changed lines are exempt by default.
A standing note saying rounds are skipped unless noted satisfies this once for all phases.
"""

_SOFTENED_SECTION = """\
## Running more than one reviewer

A single reviewer is usually enough, and the rules below are guidance rather than
requirements. Consider giving reviewers their own worktree with `isolation: "worktree"`,
though a purely read-only lens usually does not need it.
"""


def test_the_gate_predicate_rejects_a_softened_gate():
    """Non-vacuity through the production predicate.

    Every line of the fixture is a mutation that SURVIVED the first adversarial round with
    all 11 tests green. If the predicate stops catching them, this test says so.
    """
    problems = gate_problems(_SOFTENED_GATE)
    assert any("advice" in p for p in problems), problems
    assert any("AUTHORITY" in p for p in problems), problems
    assert any("standing exemptions" in p for p in problems), problems
    assert any("blanket exemption" in p for p in problems), problems
    assert any("points at the procedure" in p for p in problems), problems


def test_the_procedure_predicate_rejects_a_softened_section():
    problems = section_problems(_SOFTENED_SECTION)
    assert any("hedged" in p for p in problems), problems
    assert any("commit-first" in p for p in problems), problems
    assert any("no-tree-mutation" in p for p in problems), problems
    assert any("carve-out" in p for p in problems), problems
    assert any("never-forks" in p for p in problems), problems


def test_the_predicates_are_not_trivially_permissive():
    """A predicate that returns [] for anything would pass both real-file tests."""
    assert gate_problems("") != []
    assert section_problems("") != []


# --------------------------------------------------------------------------------------
# Placement — absolute, not merely relative
# --------------------------------------------------------------------------------------

def test_the_gate_sits_in_the_instructions_not_the_changelog():
    """Proximity to the close-out steps is the stated mechanism, but relative distance
    alone is not enough: moving the close-out convention AND the gate together to the
    bottom of the file, below the 188-row Phase log table, kept them adjacent while
    destroying the property. Pin both — near the steps, and in the instruction half of the
    file rather than the table half.
    """
    text = _claude_md()
    close_out = text.index("So a phase closes by")
    gate = text.index("A phase is not done until an adversarial round has run")
    assert 0 < gate - close_out < 1200, (
        f"the gate drifted from the close-out convention ({gate - close_out} chars)"
    )
    # Anchored on the actual HEADING, not the prose mention of it in § Status — which is
    # what the first attempt matched, at offset 803, producing a confident failure about a
    # property that held. A guard that fires on the wrong anchor teaches you to disable it.
    m = re.search(r"^##\s+Phase log\s*$", text, re.M)
    assert m, "the Phase log heading is gone; this guard's anchor needs revisiting"
    phase_table = m.start()
    assert gate < phase_table, (
        "the gate is below the Phase log table — it has been moved out of the instructions "
        "and into the changelog half of the file, where nobody reads it as an instruction"
    )


def test_the_close_out_step_list_still_names_the_round():
    """Deleting the round from the enumerated steps — the steps that demonstrably DO get
    followed — retired the gate while every first-draft test stayed green."""
    text = _claude_md()
    steps = text[text.index("So a phase closes by"):][:600]
    assert re.search(r"run an adversarial round", steps, re.I), (
        "the close-out step list no longer mentions the round; the gate paragraph alone is "
        "the surface that was already demonstrated insufficient"
    )


# --------------------------------------------------------------------------------------
# Cross-file consistency
# --------------------------------------------------------------------------------------

def test_the_procedure_does_not_contradict_the_skills_that_consume_it():
    """The live version of this defect shipped: an unqualified 'give every reviewer its own
    worktree' against seven 'Do NOT set isolation' instructions in four skills."""
    section = _multi_reviewer_section()
    forbidding = []
    for skill in sorted((REPO_ROOT / "core" / "skills").rglob("SKILL.md")):
        if re.search(r'Do\s+\*{0,2}NOT\*{0,2}\s+(?:set|use)\s+`?isolation', skill.read_text(encoding="utf-8"), re.I):
            forbidding.append(skill.parent.name)
    assert forbidding, "no skill forbids isolation any more — the carve-out may be stale"
    for name in forbidding:
        assert f"/{name}" in section, (
            f"/{name} forbids `isolation: \"worktree\"` but the procedure's carve-out does "
            f"not name it — the contradiction is back"
        )


def test_the_premise_rule_cites_a_section_that_exists():
    """The first draft cited '§ Adjudication' as if it were in this file. It is in
    `fanout-evidence.md`, and it is Phase 141, not 140 — a pointer a reader following it
    inside this file could never resolve."""
    section = _multi_reviewer_section()
    assert "Classification Rubric" in section, (
        "the premise rule no longer cites its in-file twin (the compound-findings rule)"
    )
    assert re.search(r"^##\s+Classification Rubric", _partial(), re.M)
    if "Adjudication" in section:
        assert "fanout-evidence.md" in section, (
            "§ Adjudication is cited without naming the file it actually lives in"
        )
        assert re.search(r"^##\s+Adjudication", (REPO_ROOT / "core" / "skills" / "_shared"
                         / "fanout-evidence.md").read_text(encoding="utf-8"), re.M)


# Language that would re-permit the thing the procedure forbids. Scanned over the WHOLE
# partial, because a contradiction does not have to live in the section it contradicts.
_TREE_SHARING_PERMISSION = (
    r"reviewers (?:can|may) share the caller",
    r"share the caller'?s'? (?:working )?tree",
    r"no isolation\s*[—-]\s*reviewers",
    r"fine for a read-only lens",
)


def test_no_part_of_the_partial_re_permits_tree_sharing():
    """Scoping guards against dilution INSIDE a section; it does nothing about a
    contradiction planted beside it.

    This was the last survivor of the rebuild: one permissive bullet added to § Caller
    contract, six lines above the rule it contradicts, passed every scoped guard. A reader
    hits the permission first and never reaches the prohibition.
    """
    text = _partial()
    offenders = [p for p in _TREE_SHARING_PERMISSION if re.search(p, text, re.I)]
    assert offenders == [], (
        "somewhere in the partial, sharing the caller's working tree is permitted again — "
        f"which contradicts the procedure's own rule: {offenders}"
    )


def test_that_tree_sharing_guard_is_not_vacuous():
    """Non-vacuity using the verbatim mutation that survived."""
    planted = "- no isolation — reviewers share the caller tree, fine for a read-only lens"
    assert [p for p in _TREE_SHARING_PERMISSION if re.search(p, planted, re.I)]


def test_the_never_forks_rule_ships_to_consumers():
    """It lived only in the maintainer's CLAUDE.md, which no consumer ever sees, while the
    procedure that ships in both install modes had no fork warning at all."""
    assert re.search(r"never forks", _multi_reviewer_section(), re.I), (
        "the shipped procedure has no never-forks rule; consumers get the multi-reviewer "
        "section with the correlated-error trap unmarked"
    )
