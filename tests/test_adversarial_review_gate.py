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
from typing import Callable

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
    # Scoped to a reviewer-ish subject. Bare `usually enough` fired on "a scratch `git init`
    # is usually enough of a fixture" — an innocent clarifying example, gone red by a guard
    # written about reviewer COUNT. Over-strictness is rule 1's own "direction that hides",
    # and a guard that reddens on innocent prose is what trains people to weaken it.
    r"(?:reviewer|round|lens|pass)s? (?:is|are) usually enough",
    r"where practical",
    r"if time (?:permits|allows)",
    r"at your discretion",
    r"rounds are (?:optional|encouraged)",
    # Phase 166's round appended two ordinary paraphrases of "one reviewer is fine" to the
    # guarded section and section_problems() returned [] both times, while the docstring
    # above claimed these guards test binding rather than words. Cost-framed softenings are
    # the live risk now that the section carries a cost argument at all.
    r"a single reviewer is (?:often|usually|generally) (?:the right call|enough|fine)",
    r"one reviewer (?:suffices|is enough|is sufficient)",
    r"add a second (?:reviewer )?only when",
    r"(?:recommendations|suggestions) you may weigh against",
    r"weigh against the (?:token )?(?:spend|cost)",
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
    # Scanned over the WHOLE multi-reviewer section, not just the author-side subsection.
    # A round planted `Docs-only phases are exempt from the author-side pass below.` two
    # lines ABOVE the `###` heading: `are exempt` is in `_BLANKET_EXEMPTIONS`, but that list
    # was applied only inside the subsection, and this predicate applied only `_HEDGES`. A
    # reader meets the exemption before the rule it exempts them from.
    for pat in _BLANKET_EXEMPTIONS:
        if re.search(pat, section, re.I):
            problems.append(f"procedure carries a blanket exemption: {pat!r}")
    for pat, why in RULE_3_FORBIDDEN:
        if re.search(pat, _flat(section), re.I):
            problems.append(f"procedure contradicts the author-side pass ({why}): {pat!r}")
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


def author_pass_problems(section: str) -> list[str]:
    """Everything that would stop the author-side pass from being followable.

    Phase 166 shipped this subsection with ZERO guards — deleting all ~3.2k characters left
    the suite green, in the one file that has a purpose-built guard module for it. Its own
    round found four defects in the rule text itself, and each assertion below is one of
    them: an exclusive "mutate assumptions NOT content" reading condemns the reversion and
    vacuity guards whose revert IS their test (this repo ships ~97 drift guards); an
    unbounded "name the survivors you decline to close" licensed the biggest hole of the
    preceding round to ship as "known blind spot, as designed"; the population rule is the
    one whose absence produced that phase's own worst number; and a one-sided cost argument
    inside a section that requires several reviewers leans the file toward a decision the
    phase declared unratified.
    """
    # Flattened before matching. These patterns are Phase 166's and none is line-anchored,
    # but they ran against raw text — so reflowing the limits paragraph split
    # "cannot catch a number whose *source* was wrong" across a newline and the guard
    # reported the rule GONE. Reddening on a reflow is rule 1's "direction that hides", and
    # this phase's round reproduced it. Flattening loses nothing and costs a false failure.
    section = _flat(section)
    problems = []
    required = {
        # Split deliberately: an alternation here let a mutation delete the addressee
        # header while "the *author*" still satisfied it — the "what it accepts" class,
        # in the guard that ships the rule naming that class.
        "role-binding-header": r"who this addresses",
        "role-binding-addressee": r"the \*author\*",
        "plan-time-exclusion": r"not part of the plan-review flow",
        "reversion-guard-carve-out": r"reversion guard",
        "vacuity-guard-carve-out": r"vacuity guard",
        "composed-mostly-not-only": r"composed \*\*mostly\*\*|composed mostly",
        "population-from-source-of-truth": r"source of truth, not from an index",
        "over-strictness-class": r"over-strictness",
        "reachability-class": r"reachability",
        "residual-criterion": r"impossible to close \*in kind\*|impossible to close in kind",
        "residual-not-unattempted": r"not merely unattempted",
        "reread-own-prose": r"re-read your own new prose",
        # Two entries, not an alternation: the first version was `cannot do|cannot catch`
        # and deleting the heading left the body clause satisfying it. Third instance of
        # the same over-permissive-alternation defect in this predicate, all three found
        # by mutating it rather than by reading it.
        "limits-heading": r"what this pass cannot do",
        "limits-source-vs-arithmetic": r"cannot catch a number whose \*source\* was wrong",
    }
    for name, pat in required.items():
        if not re.search(pat, section, re.I):
            problems.append(f"author-side pass lost its {name} rule")
    # The counter-evidence must ship with the cost argument or the file argues one side of a
    # decision its own record says belongs to the maintainer.
    if re.search(r"expensive way to treat that|stop paying reviewers", section, re.I):
        if not re.search(r"not an argument for fewer reviewers", section, re.I):
            problems.append(
                "cost argument ships without the counter-finding — the measured overlap was "
                "~15% and each lens produced its sharpest finding alone, so the section now "
                "leans toward an unratified reviewer-count decision"
            )
    for pat in _HEDGES:
        if re.search(pat, section, re.I):
            problems.append(f"author-side pass hedged with {pat!r}")
    return problems


# --------------------------------------------------------------------------------------
# The real files must have no problems
# --------------------------------------------------------------------------------------

def test_the_gate_binds():
    assert gate_problems(_gate_paragraph()) == []


def test_the_procedure_binds():
    assert section_problems(_multi_reviewer_section()) == []


AUTHOR_PASS_START = "### Before you spawn anyone"
AUTHOR_PASS_END = "\n## Prompt Template"


def _prose_only(text: str) -> str:
    """Commented-out or fenced text is not shipped prose.

    The prose analogue of `test_review_close_record_revision.py`'s executable-line
    discipline, run in the opposite direction. Wrapping this subsection in `<!-- -->` — or
    in a ``` fence, so it renders as a quoted example rather than an instruction — leaves
    every pinned word present in the file and every pin green while the rule reaches no
    reader. That is verbatim the "gate commented out" survivor Phase 167's round
    demonstrated, one file over. Stripping both first makes a neutered rule read as a
    deleted one, which is what it is.
    """
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"^```.*?^```", "", text, flags=re.S | re.M)
    # A `<details>` block renders collapsed. Same neutering, different markup — and an
    # UNCLOSED one still collapses on GitHub while surviving this substitution, so the
    # leftover tag is screened as a contradiction below rather than trusted to be stripped.
    text = re.sub(r"<details\b.*?</details>", "", text, flags=re.S | re.I)
    # Blockquote too, and here it is not merely neutering: in THIS file `>` marks text to be
    # copied verbatim into a reviewer's prompt (§ Prompt Template). A blockquoted rule has
    # not been softened, it has been re-addressed — to the reviewer whose existence the rule
    # is meant to make cheaper.
    text = re.sub(r"^\s*>.*$", "", text, flags=re.M)
    # Rejoin a word broken across lines at a hyphen. Wrappers do this by default, and it is
    # presentation: hard-wrapping the subsection to 80 columns split `purpose-built` and
    # `plan-review`, which flattened to `purpose- built` and reported a pin lost and a rule
    # gone. Word chars are required on both sides, so a `\n- ` list marker never matches.
    text = re.sub(r"(\w)-\n[ \t]*(\w)", r"\1-\2", text)
    # Fold list markers to `-` while line starts are still visible. Doing it after flattening
    # cannot distinguish an ordered marker from a sentence ending in a number — "exited 128.
    # This is rule 1's…" would fold mid-prose and corrupt the comparison.
    return re.sub(r"(?m)^(\s*)(?:\*|\d+\.)\s", r"\1- ", text)


def _author_pass_slice(text: str) -> str:
    """The subsection, between two NAMED markers, failing closed when either is missing.

    The first version searched for the next `\\n## ` and fell back to end-of-file when it
    found none — the fail-open shape Phase 167's round measured one file over, where a
    renamed downstream heading silently widened a 7,890-character window to 96,821 and let
    content from anywhere later satisfy an in-section assertion. Here the same widening
    would let the Prompt Template's nine review dimensions stand in for a rule of this
    subsection. Empty is the honest answer to a restructured file: every check that reads
    the slice then fails loudly instead of passing quietly.
    """
    text = _prose_only(text)
    # Exactly one, or fail closed. `find` takes the FIRST match, so a softened decoy planted
    # under the same heading anywhere above the real subsection becomes the text every check
    # reads while the real rule sits outside the window untouched — rule 1's "where it looks"
    # class, aimed at the slicer instead of at a guard's file population.
    if text.count(AUTHOR_PASS_START) != 1:
        return ""
    a = text.find(AUTHOR_PASS_START)
    b = text.find(AUTHOR_PASS_END, a)
    if b <= a:
        return ""
    return text[a:b]


def _author_pass_section() -> str:
    section = _author_pass_slice(PARTIAL.read_text(encoding="utf-8"))
    assert section, (
        "the author-side pass subsection does not resolve — either it is gone (it shipped "
        "unguarded once and deleting it left the whole suite green, which is the hole this "
        "module exists to close) or `## Prompt Template` was renamed and this slicer needs "
        "revisiting"
    )
    return section


def test_the_author_side_pass_binds():
    assert author_pass_problems(_author_pass_section()) == []


def test_the_author_pass_slicer_fails_closed():
    """A missing end marker must yield nothing, not the rest of the file."""
    text = PARTIAL.read_text(encoding="utf-8")
    assert _author_pass_slice(text)
    assert _author_pass_slice(text.replace("## Prompt Template", "## Reviewer Prompt")) == ""
    assert _author_pass_slice(text.replace(AUTHOR_PASS_START, "### Author-side pass")) == ""


# --------------------------------------------------------------------------------------
# Phase 168 — rule 3: run the commands the change prescribes
# --------------------------------------------------------------------------------------
#
# The primitive here is deliberately NOT the token-presence style used above. Phase 167's
# round ran 90 mutations against a module written that way and 43 were genuine bypasses,
# because a line in these files is routinely a 700-character paragraph — so "N phrases in a
# sentence asserting the opposite" walks straight through. Load-bearing sentences are pinned
# **verbatim, whitespace-normalised**: rewrapping, reflowing and re-indenting pass; changing
# the words does not. `FORBIDDEN` backs the pins up for the reversals that could survive by
# quoting a pin inside a negation — a blocklist, incomplete by construction, not a
# replacement for the pins.

RULE_3_HEADING = "**3. Run the commands the change prescribes, in a throwaway repo — before you spawn anyone.**"
LIMITS_HEADING = "**What this pass cannot do.**"


def _flat(text: str) -> str:
    """Whitespace-collapsed, so a pin survives rewrapping and re-indentation while any
    change to the words themselves still fails it."""
    return re.sub(r"\s+", " ", text)


RULE_3_PINS: list[tuple[str, str]] = [
    # (verbatim span, why it is load-bearing)
    (RULE_3_HEADING,
     "the rule itself, including WHEN it runs. Moving it after the round — 'once your "
     "reviewers report, check the commands' — keeps every other word and retires the rule, "
     "since the finding it exists to make cheap has already been paid for by a reviewer."),
    ("nothing runs a command generally, so **a newly prescribed one stays text until an operator reaches it**",
     "the antecedent of the pinned conclusion below, and the accurate form of it. The first "
     "version claimed a fenced command is read as text 'by every mechanism that guards it' — "
     "false, and the round caught it: `test_review_close_smoke_gate.py`, "
     "`test_review_close_close_heredoc.py`, `test_batch_claim_kinds.py` and "
     "`test_round_markers.py` each extract a NAMED heredoc from a skill file and run it "
     "against a fixture. The claim that survives is 'no general runner', not 'no runner'."),
    ('"the prescribed command does not work" is invisible until that moment',
     "the reason the rule cannot be delegated to the suite. Replaced with 'skill prose is "
     "covered by the suite like everything else' the conclusion still stood, unsupported and "
     "preceded by a false claim — the shorter half of a pinned sentence is where a reversal "
     "fits."),
    ("Scope this to commands whose operand the change **computes or substitutes**",
     "the bound. Unscoped, the rule says 'run every command in the diff', which is the shape "
     "authors reasonably ignore — and an ignored rule is worse than none, because the "
     "author-side pass is then reported as run."),
    ("Copy the literal string, resolve its placeholders the way the change tells an operator to resolve them, and run it.",
     "`literal string` is the whole instruction. Running your own paraphrase of the command "
     "reproduces the assumption under test — the quoting defect Phase 167 shipped was "
     "invisible to anything but the literal text."),
    ("**Build the fixture's inputs from the source of truth, not from your own model of them.**",
     "half (ii). It is the half that does the work and the one that is easy to drop, so it "
     "gets its own pin rather than riding on the paragraph above it."),
    ("The same fixture runs **green** on the author's assumption and **red** on what the shipped writers actually emit",
     "the mechanism that makes half (ii) more than a platitude: the two inputs disagree in "
     "verdict, not in detail. Without it 'use the source of truth' reads as advice about "
     "rigour rather than a statement that the other fixture passes."),
    ("This is the half that does the work, and the easy one to drop.",
     "the pairing. Rewritten to 'a separate practice, useful on its own' both halves stay "
     "on the page and stop being one rule — which is the shipped-and-useless form, since "
     "half (i) alone certifies the author's assumption instead of testing it."),
    ("**What it reaches is narrow, and the rule says so rather than leaving it implied:**",
     "the honest limit's lead-in, pinned apart from its content: swapping only the lead-in to "
     "'What it reaches is broad' left the content clause intact and inverted the bullet."),
    ("43 of 90 guard mutations bypassing, and the false claims in its own record",
     "the counter-evidence. Deflating '43 of 90' to '3 of 90' leaves a rule that reads the "
     "same and argues the opposite — factual drift in shipped prose, which no other check "
     "here reaches. The clause carries no count of the false claims on purpose: the round "
     "found that Phase 167's section HEADS three and its body corrects five, so any number "
     "here inherits a contradiction from its source."),
    ("A fixture you populate from memory proves only that you are self-consistent.",
     "the consequence, and the sentence that stops a green run from being reported as "
     "evidence. This is the failure the rule is for, stated as a result rather than a duty."),
    ("moved from what a guard **reads** to what a fixture **contains**",
     "ties half (ii) to rule 1's population rule. Severing it re-opens the question of why "
     "the fixture half is not just rule 1 again, and the answer is that it is the same "
     "substitution one layer over."),
    ("whether the command runs, and whether it does what you said it does. Nothing past that.",
     "the honest limit, stated INSIDE the rule. An unlimited rule 3 is read as a substitute "
     "for a lens, which is the misreading that would cost more than the rule saves."),
    # No terminal period: appending a cross-reference after this clause is innocent, and
    # pinning the period reddened exactly that edit in an author-side battery. The
    # permissive-frame reversal it opens ("it does not replace a lens, though it can") is
    # covered by `RULE_3_FORBIDDEN` instead, which is where a contradiction belongs.
    ("It converts one expensive finding into a cheap one; it does not replace a lens",
     "the not-a-substitute clause. Deleting it turns this rule into an argument for fewer "
     "reviewers — a decision this file's own record says is the maintainer's, not the "
     "section's, and which the ~15% measured overlap argues against."),
    ("**failed on a default install**",
     "the incident's verdict. Flipped to 'worked on a default install' the paragraph still "
     "reads as an argument for the rule while its evidence now says the rule was "
     "unnecessary — a false claim in shipped prose, which is the class rule 2 covers and "
     "the class Phase 167's round found three of in its own record."),
    ("by building a scratch repo and running the string",
     "the mechanism, and the whole contrast with the two lenses that read the same files. "
     "Softened to 'by reading the string carefully' the sentence argues against rule 3 "
     "while sitting inside it."),
    # --- the limits paragraph, which rule 3 falsified and therefore had to re-scope ---
    ('Executing one command against a fixture *you* built reaches "does it run" and "does it do what I said", and stops there.',
     "the re-scoped claim. Its predecessor read 'It never executes the change against real "
     "state' and named 'a prescribed command that fails on the operator's own machine' as "
     "out of reach — false the moment rule 3 shipped directly above it. A rule that "
     "falsifies the sentence beneath it is the exact class this file exists to prevent."),
    ("the common case itself, since a fixture is one case and you are the person who chose which",
     "the residue that survives rule 3, and the reason the limits paragraph was re-scoped "
     "rather than deleted. A fixture cannot tell you it is unrepresentative."),
    ("it still cannot catch a number whose *source* was wrong, only one whose arithmetic was",
     "carried through the re-scope unchanged; the pass never reached it and still does not"),
]

# Contradiction screen. Pins catch DELETION and REWORDING; they are blind to ADDITION, and
# an author-side battery proved it — four softenings added *alongside* an intact pin set
# walked through every pin. So these are patterns, not literal phrases, and they cover the
# classes rather than the four sentences: re-denying execution in any paraphrase (the
# precondition, defeated by wording), demoting the rule to advice, licensing the assumed
# fixture, and thresholding by size or change-class. A blocklist is incomplete by
# construction — it backs the pins up, it does not replace them.
RULE_3_FORBIDDEN: list[tuple[str, str]] = [
    (r"(?:never|does not|doesn't|do not|cannot)\s+(?:execute|run)s?\b[^.]{0,60}real state",
     "re-denies execution — the sentence rule 3 falsified, in any wording. The pass now "
     "does execute, in a fixture, and a paragraph saying otherwise sits directly beneath it"),
    (r"never executes the change",
     "the same denial, phrased without the words 'real state'"),
    (r"recommendations?,? (?:and )?not (?:a )?requirements?|advisory, not (?:a )?(?:rule|requirement)",
     "demotes the rule to advice in place, leaving every pin intact"),
    # Subject-anchored but not adjacency-anchored: `rule 3 is advisory` was the pattern, and
    # `Rule 3 of the author-side pass below is advisory` walked past it.
    (r"rule 3\b[^.]{0,60}\bis (?:optional|advisory|a suggestion|best-effort|non-?binding)",
     "the same demotion, stated of the rule by name"),
    (r"either (?:input|fixture|shape) is (?:fine|acceptable|enough|good enough)",
     "licenses the assumed fixture that half (ii) exists to reject"),
    (r"in practice the two (?:agree|match|are the same)",
     "asserts the disagreement half (ii) is built on does not occur — the claim Phase 167's "
     "fixture disproved by exiting 128"),
    (r"(?:your|the author's)(?: own)? (?:model|assumption)[^.]{0,40}\bis (?:a |an )?(?:fine|acceptable|adequate|reliable)",
     "the same licence, phrased as a property of the author's model"),
    (r"skip (?:this|rule 3|it) (?:for|on|unless|when)",
     "a standing exemption at rule scope — the gate above forbids exactly this shape"),
    (r"optional (?:for|on|when|unless|in)\b",
     "the same exemption phrased as a licence rather than an instruction. Generalising the "
     "screen from literal phrases to classes dropped this one, and the committed table "
     "caught the loss — 'optional for prose-only changes' is a change-class carve-out, and "
     "docs-only is precisely where an unchallenged claim ships"),
    (r"no need to run it yourself",
     "hands rule 3 back to the reviewers it exists to spare"),
    (r"reviewers? (?:normally |usually |will |generally )?re-?runs?",
     "defers the rule to the round, which is where the finding stops being cheap"),
    (r"equivalent to (?:running|executing)|as good as (?:running|executing)",
     "asserts reading the command is equivalent to running it — the belief rule 3 exists "
     "to refute, and it can be planted in rule 2 where rule 3's own pins do not look"),
    (r"not (?:rule 3|this rule)'?s?\b",
     "severs half (ii) from the rule it belongs to, leaving both halves present and unpaired"),
    (r"<details\b|<summary\b",
     "collapses the rule behind a disclosure widget. A closed block is stripped before "
     "slicing; this catches the unclosed form, which still renders collapsed"),
    (r"(?:can|could|does|will) replace a lens",
     "reverses the not-a-substitute clause in a permissive frame, which the pin no longer "
     "covers now that it ends before the terminal period"),
]

# Permissive modals, scanned over the RULE-3 BLOCK ONLY. Pins catch deletion and rewording;
# the screen above catches the reversals someone has already demonstrated. Neither reaches a
# softening nobody has written yet, and a second author-side battery produced seven of those
# against an intact pin set — so this closes the class structurally instead of by enumeration:
# the block is four short imperative paragraphs, and a modal in it is a carve-out.
#
# Scoped to the block on purpose. Over the whole subsection it would false-positive on rule
# 1's own prose — "A pattern requiring an optional token misses the idiomatic form" — which
# is the over-strictness rule 1 itself warns about, reached by mis-scoping the guard for it.
_RULE_3_SOFTENING_MODALS = (
    r"\bmay\b",
    r"\bcan skip\b",
    r"\bneed not\b",
    r"\bunless\b",
    r"\bonly when\b",
    r"\boptional\b",
    r"\bconsider (?:running|doing|building)\b",
    r"\bhistorical\b",
    r"\bsuperseded\b",
    r"\bdeprecated\b",
    r"\bapplies to\b[^.]{0,60}\bonly\b",
    r"\bwhen the (?:setup )?cost\b",
    # Status demotion — a sentence whose subject is the rule and whose predicate is a
    # not-really-in-force word. Written as a class (any of these subjects × any of these
    # statuses) rather than as the three sentences a battery happened to produce, because
    # the enumerated form is what reported 5/12 against them.
    r"(?:rule 3|this rule|the fixture half|half \(ii\)|its result)\b[^.]{0,70}"
    r"\b(?:aspirational|unverified|provisional|experimental|non-?binding|not yet|"
    r"under evaluation|informational|advisory)\b",
    r"\b(?:aspirational|provisional|experimental|non-?binding|under evaluation)\b",
    r"\brarely (?:needed|necessary|worth)\b",
    r"\bnot an instruction\b",
    r"\bnot required by\b",
)

# Verbatim pin over the WHOLE author-side-pass subsection.
#
# To re-approve a deliberate edit, regenerate the constant rather than hand-editing it:
#
#     python3 -c "import sys; sys.path.insert(0,'.'); \
#       import tests.test_adversarial_review_gate as G; \
#       print(repr(G._block_canon(G._flat(G._author_pass_section()))))"
#
# Paste the output below. The diff then carries the prose change and its re-approval
# together, which is the whole mechanism — the cost is a large constant in the diff, and
# that cost is why this guard is scoped to one subsection and not to the file.
#
# This replaced a growth ratchet (a character ceiling with ~1% slack), and the round killed
# that ratchet with two demonstrations. `Skip it if rushed.` is 19 characters and fits under
# the slack: 74 passed. And the slack is not even the floor — deleting 110 characters of
# UNPINNED prose frees exactly enough budget to buy a 139-character softening asserting that
# "a careful read of the command discharges this step just as well … and the fixture is then
# redundant", which is the belief rule 3 exists to refute: 74 passed. A ceiling bounds the
# block's SIZE, and the free space where a contradiction lives is the block's size minus its
# pins — so a length-neutral swap was always going to walk through. The author's own table
# never probed below the slack, because all three of its addition entries added 38+ characters.
#
# So the residue is pinned rather than budgeted. Any edit to the block — added sentence,
# deleted sentence, swapped sentence, relocated sentence — fails until this constant is
# updated in the same commit, which puts the rule change and its re-approval in one diff.
# Normalised for whitespace and list markers, so rewrapping, reflowing, re-indenting and a
# `-`/`*` swap still pass. The cost is real and is the point: wording this rule is now a
# deliberate act, which for a rule that ships to consumers is the correct default.
AUTHOR_PASS_VERBATIM = (
    '### Before you spawn anyone — the author-side pass **Who this addresses:** the *author* of a change that ships code or guards, after committing and before spawning reviewers. It is not part of the plan-review flow — a `/plan-review` or `/claim-task` Step 7 reviewer has no guards to mutate yet, and should skip this section. **Why it exists.** Twelve of the sixteen phases from 150 to 165 in this project\'s log had a round that found the phase\'s own guards vacuous or its mutation claim self-selected. One reported "33 of 33 mutations killed"; an independent reviewer then ran 83 and watched 28 survive. A round that keeps finding the same class of defect is working as a detector while the authoring step is not learning, and **buying more reviewers is the expensive way to treat that** — roughly half of what such a round finds is catchable by inspection in minutes. **This is not an argument for fewer reviewers.** Measured on one such round, reviewers on distinct lenses were **not** redundant: overlap was about 15%, and each of four lenses produced its sharpest finding alone. Findings-per-reviewer was high. The point is to stop paying them for what you can see yourself, not to stop paying them. **1. Mutate the guard\'s assumptions, not just the content it checks.** Deleting a phrase a guard requires proves the guard is *wired to the file* — real information, and for a declared **reversion guard** (one whose stated job is catching deletion or a shortening-back) or a **vacuity guard** (one asserting its own population is non-empty) that mutation is the whole test of its stated job. Run those. The failure is a set **composed mostly** of them: it reports a kill rate that describes wiring while saying nothing about coverage. In the round that produced this rule, four of the author\'s nine mutations were reverts of text the guards were written to assert, the set was reported as "0 survivors", and **eight real bypasses stood**. So add mutations against each assumption the guard makes: - **What it matches on.** A guard keyed to a physical line is walked through by a backslash continuation, by naming a flag before its command, by a variable holding the value, or by a list step that separates a command from its qualifier. None of those is adversarial; they are how people write. - **What it accepts.** A check satisfied by a substring is satisfied by an *incidental* use of that substring — worse than a gap, because it marks a dangerous line compliant. A check requiring N phrases is satisfied by N disconnected phrases in a sentence asserting the opposite. - **Where it looks.** Enumerate the files the guard actually reads and ask whether that population covers every place the defect can appear. One such guard excluded the installer — a file that already prescribed the very script the guard was about. **Derive the population from the source of truth, not from an index or summary of it**; that single substitution produced the worst number in the phase that shipped this rule. - **Over-strictness, the direction that hides.** A pattern requiring an optional token misses the idiomatic form. A guard keyed to `bash <path>/script --flag` missed `<path>/script --flag`, which was the repo\'s own house style. - **Reachability.** Can the guard run at all, and on the thing you think? A new file excluded from its own scan, an uncollected test module, an empty population — each passes while testing nothing. - **When it runs.** If the fix depends on ordering ("rejected *before* anything is deleted"), mutate the ordering. Prose asserting an order is not a test of it. Report the fraction. **A survivor you decline to close must be impossible to close *in kind*** — it needs a judgement no pattern can encode — **not merely unattempted.** "Known blind spot, as designed" is not a disposition: in the round that produced this rule the author labelled the single biggest hole exactly that way, and the round required it fixed. If an ordinary in-repo idiom reaches your survivor, it is a defect wearing a residual\'s label. **2. Re-read your own new prose against the code it describes.** Both defects one such round found *in the fix itself* were sentences the author had just written that contradicted the file they sat in — and both were in the same class the fix existed to remove. New prose is the least-reviewed text in any change: no history, no reviewer has seen it, and its author is the one person who cannot read it cold. Check every new claim against the thing it describes, including claims about paths, which are as easily wrong in the consumer\'s installed layout as in yours. **3. Run the commands the change prescribes, in a throwaway repo — before you spawn anyone.** Shipped scripts get real-subprocess coverage, and a few purpose-built extractors do pull a *named* heredoc out of a skill file and run it against a fixture — but nothing runs a command generally, so **a newly prescribed one stays text until an operator reaches it**, and "the prescribed command does not work" is invisible until that moment. Scope this to commands whose operand the change **computes or substitutes** — `git log --oneline` has no operand to get wrong. Copy the literal string, resolve its placeholders the way the change tells an operator to resolve them, and run it. In the round that produced this rule, a prescribed `git show "<branch>:<body path>"` **failed on a default install** — `fatal: path … does not exist` — and the change\'s own new `unreadable` classification would then have halted every run with a fabricated diagnosis blaming the branch. One of three lenses found it, by building a scratch repo and running the string; the other two read the same files and did not. - **Build the fixture\'s inputs from the source of truth, not from your own model of them.** This is the half that does the work, and the easy one to drop. The same fixture runs **green** on the author\'s assumption and **red** on what the shipped writers actually emit: in that round, an assumed body path of `tasks/open/<ID>.md` printed the file, while the canonical value every writer emits — `open/<ID>.md`, relative to `tasks/` — exited 128. A fixture you populate from memory proves only that you are self-consistent. This is rule 1\'s *"derive the population from the source of truth, not from an index or summary of it"* moved from what a guard **reads** to what a fixture **contains**. - **What it reaches is narrow, and the rule says so rather than leaving it implied:** whether the command runs, and whether it does what you said it does. Nothing past that. In that same round the two other defect classes — 43 of 90 guard mutations bypassing, and the false claims in its own record — were entirely outside it. It converts one expensive finding into a cheap one; it does not replace a lens. **What this pass cannot do.** Rule 3 narrowed this and left more than it took. Executing one command against a fixture *you* built reaches "does it run" and "does it do what I said", and stops there. Out of reach still: whether the prescribed command is the **right** one to prescribe; whether a claim about what its output *means* holds; the common case itself, since a fixture is one case and you are the person who chose which; and it still cannot catch a number whose *source* was wrong, only one whose arithmetic was. Those want a reader who has not already decided what the change means — which is what you are about to spawn. Where the harness cannot spawn reviewers at all (§ Harness constraint), this pass is the most you have and you should say so in the record rather than let its limits pass silently. '
)


def _block_canon(block_flat: str) -> str:
    """Whitespace already collapsed by `_flat`; also fold the list marker.

    A `-` -> `*` bullet swap is a reformat, and reddening on one is the brittleness Phase
    167 paid 15 innocent failures to learn about. After flattening, a bullet marker is a
    ` * ` run with spaces on both sides, which emphasis (`*word*`) never produces.
    """
    return block_flat.replace(" * ", " - ")


def _first_divergence(got: str, want: str) -> str:
    """Where the block stops matching its pin, so the failure is actionable rather than
    just 'something changed in 3,000 characters'."""
    n = min(len(got), len(want))
    i = next((k for k in range(n) if got[k] != want[k]), n)
    return f"First divergence at char {i}: pinned ...{want[i:i + 90]!r} / found ...{got[i:i + 90]!r}."


def _rule_3_block(section: str) -> str:
    """Rule 3 and the limits paragraph that scopes it, flattened. Fails closed.

    The window runs to the END of the subsection, not to the limits heading. Two of the
    demotions a battery produced ("the fixture half is aspirational", "treat its result as
    unverified") sat *in* the limits paragraph, which is precisely where a demotion looks
    most at home — and a screen bounded at that heading could not see either.

    It stops at the subsection boundary rather than scanning the whole partial because rules
    1 and 2 legitimately use this vocabulary — "A pattern requiring an optional token misses
    the idiomatic form" is rule 1's own text. Scanning wider would redden the section that
    warns about over-strictness, for the sentence that warns about it.
    """
    flat = _flat(section)
    a = flat.find(_flat(RULE_3_HEADING))
    if a < 0:
        return ""
    if _flat(LIMITS_HEADING) not in flat[a:]:
        return ""
    return flat[a:]


def rule_3_problems(section: str) -> list[str]:
    """Everything that would stop rule 3 from binding, pinned rather than token-matched."""
    flat = _flat(section)
    # Pins resolve against the BLOCK, not the whole subsection. Matched section-wide, a
    # pinned sentence could be MOVED out of rule 3 into rule 2 and still satisfy its own
    # pin — the round demonstrated it, and the only thing that went red was an unrelated
    # mutation entry, naming the wrong defect. The contradiction screens below stay
    # section-wide on purpose: a contradiction planted beside the rule still contradicts it.
    block = _rule_3_block(section)
    problems = [
        f"rule 3 pin lost, reworded or moved out of the rule — {why} :: {span[:70]!r}"
        for span, why in RULE_3_PINS
        if _flat(span) not in block
    ]
    problems += [
        f"rule 3 contradicted in place ({why}): {pat!r}"
        for pat, why in RULE_3_FORBIDDEN
        if re.search(pat, flat, re.I)
    ]
    # The gate's blanket-exemption vocabulary, applied one layer down. It was previously
    # scanned over `CLAUDE.md`'s gate only, so "phases under ~50 lines are exempt" was
    # blocked at the gate and free to reappear inside the procedure the gate points at.
    problems += [
        f"rule 3 carries a blanket exemption: {pat!r}"
        for pat in _BLANKET_EXEMPTIONS
        if re.search(pat, flat, re.I)
    ]
    if section.strip() and _block_canon(flat) != AUTHOR_PASS_VERBATIM:
        problems.append(
            "the author-side pass no longer matches its verbatim pin "
            f"({len(_block_canon(flat))} chars vs {len(AUTHOR_PASS_VERBATIM)} pinned). "
            + _first_divergence(_block_canon(flat), AUTHOR_PASS_VERBATIM)
            + " Five author-side batteries put 34 softenings through an intact pin set and "
            "every one was an ADDED sentence; a character ceiling then let a 19-character one "
            "through, and a length-neutral shrink-and-add bought a 139-character one. The "
            "window is the WHOLE subsection because a round then planted four carve-outs in "
            "the preamble ABOVE rule 3 — a docs-only exemption, a redefinition of *source of "
            "truth*, a denial that the rule order carries any requirement, a licence to "
            "paraphrase the command — each invisible to a rule-3-scoped guard while governing "
            "how rule 3 reads. Updating this constant in the same commit IS the re-approval; "
            "pin a load-bearing new sentence separately so the message names it next time."
        )
    if not block and _flat(RULE_3_HEADING) in flat:
        problems.append(
            "rule 3's block does not resolve — the limits paragraph that bounds it is gone, "
            "so the softening screen below is reading nothing"
        )
    problems += [
        f"rule 3 softened with a permissive modal: {pat!r}"
        for pat in _RULE_3_SOFTENING_MODALS
        if re.search(pat, block, re.I)
    ]
    return problems


def rule_3_placement_problems(section: str) -> list[str]:
    """The precondition, mechanised.

    Rule 3 must sit BETWEEN rule 2 and the limits paragraph. Placed after the limits
    paragraph it reads as an afterthought to a paragraph that denies it; placed before rule
    2 it separates rule 2 from the limits it shares. Anchors are the verbatim headings, and
    each must occur exactly once — a duplicate heading planted on the far side of the limits
    paragraph would otherwise satisfy an index-based ordering check while the real rule was
    moved or removed.
    """
    flat = _flat(section)
    problems: list[str] = []
    anchors = {
        "rule 2": "**2. Re-read your own new prose against the code it describes.**",
        "rule 3": RULE_3_HEADING,
        "the limits paragraph": LIMITS_HEADING,
    }
    positions: dict[str, int] = {}
    for name, anchor in anchors.items():
        hits = flat.count(_flat(anchor))
        if hits == 0:
            problems.append(f"{name} has no heading in this subsection")
        elif hits > 1:
            problems.append(f"{name} has {hits} headings — which one is the real rule?")
        else:
            positions[name] = flat.index(_flat(anchor))
    if len(positions) == 3:
        if not positions["rule 2"] < positions["rule 3"]:
            problems.append("rule 3 is placed above rule 2")
        if not positions["rule 3"] < positions["the limits paragraph"]:
            problems.append(
                "rule 3 is placed BELOW the limits paragraph — the paragraph that scopes "
                "what the pass cannot reach now precedes the rule that changed it, so a "
                "reader meets the limits before the capability they describe"
            )
    return problems


def test_rule_3_binds():
    assert rule_3_problems(_author_pass_section()) == []


def test_rule_3_sits_between_rule_2_and_the_limits_paragraph():
    assert rule_3_placement_problems(_author_pass_section()) == []


def test_both_halves_of_rule_3_ship_or_neither_does():
    """Half (i) without half (ii) is the shipped-and-useless form.

    Phase 167's fixture, built from the author's assumption, ran green — so a rule that says
    only 'run the command' certifies the assumption instead of testing it. Asserted as a
    conditional so the pairing is what binds, not the presence of two paragraphs.
    """
    section = _author_pass_section()
    has_run_half = _flat(RULE_3_HEADING) in _flat(section)
    has_fixture_half = _flat(
        "**Build the fixture's inputs from the source of truth, not from your own model of them.**"
    ) in _flat(section)
    assert has_run_half == has_fixture_half, (
        "rule 3 ships with only one of its two halves — running a command against inputs you "
        "invented tests only that you are self-consistent, which is the result Phase 167's "
        "own fixture would have produced"
    )


def test_rule_3_predicate_is_not_vacuous():
    assert rule_3_problems("") != []
    assert rule_3_placement_problems("") != []


def test_contradictions_planted_ABOVE_the_subsection_are_screened():
    """The window has an outside, and a reader meets it first.

    A round planted three sentences two lines above the `###` heading, where every
    subsection-scoped guard is blind. `are exempt` was already in `_BLANKET_EXEMPTIONS` but
    that list ran only inside the subsection, and this predicate applied only `_HEDGES`.
    """
    head = "## Running more than one reviewer\n\n"
    for planted in (
        "Docs-only phases are exempt from the author-side pass below.",
        "Rule 3 of the author-side pass below is advisory.",
        "This pass never executes the change against real state.",
    ):
        assert section_problems(head + planted), f"planted above the subsection, unflagged: {planted!r}"


def test_the_placement_predicate_discriminates_on_its_own():
    """It is the precondition made mechanical, and no mutation isolates it — every table
    entry that reorders the rules also breaks the verbatim pin, so the table would stay
    green with this predicate deleted from `RULE_3_CHECKS`. Exercised directly instead."""
    section = _author_pass_section()
    assert rule_3_placement_problems(section) == []
    below = section.replace(RULE_3_HEADING, "", 1).replace(
        LIMITS_HEADING, LIMITS_HEADING + " " + RULE_3_HEADING, 1)
    assert any("BELOW the limits paragraph" in p for p in rule_3_placement_problems(below))
    twice = section.replace(LIMITS_HEADING, RULE_3_HEADING + " " + LIMITS_HEADING, 1)
    assert any("headings" in p for p in rule_3_placement_problems(twice))


def test_the_block_slicer_fails_closed():
    """Its docstring claims it; nothing proved it. Replacing the guard with `pass` left the
    whole module green, which is this suite's own definition of a vacuous claim."""
    section = _author_pass_section()
    assert _rule_3_block(section)
    assert _rule_3_block(section.replace(LIMITS_HEADING, "**Caveats.**", 1)) == ""
    assert _rule_3_block(section.replace(RULE_3_HEADING, "**3.**", 1)) == ""


def test_the_block_pin_catches_edits_of_every_size():
    """The negative control the character ceiling never had.

    The mutation table could not measure the ceiling: all three of its addition entries added
    38+ characters, so the table only ever demonstrated that the guard fires ABOVE its slack.
    The round then walked a 19-character softening underneath it, and bought a 139-character
    one by deleting unpinned prose first. These four probe both sizes and both directions
    directly, which is the same reason `test_review_close_record_revision.py` gives its
    spec-population check a control of its own.
    """
    section = _block_canon(_flat(_author_pass_section()))
    assert section == AUTHOR_PASS_VERBATIM, "the shipped subsection does not match its own pin"
    tiny = section.replace("does not replace a lens", "does not replace a lens. Skip it if rushed", 1)
    assert tiny != section and tiny != AUTHOR_PASS_VERBATIM, "the 19-char softening is not caught"
    # Length-neutral: delete unpinned prose, spend the budget on a contradiction.
    freed = section.replace(
        "Those want a reader who has not already decided what the change means — which is what you are about to spawn. ", "", 1)
    assert freed != section, "the unpinned sentence the round used as budget is gone; re-derive this control"
    swapped = freed.replace("does not replace a lens",
                            "does not replace a lens, though a careful read discharges it too", 1)
    assert swapped != AUTHOR_PASS_VERBATIM, "a length-neutral swap is not caught"
    # And the preamble, which a rule-3-scoped window could not see at all.
    preamble = section.replace("**Why it exists.**",
                               "Rule 3 does not bind a docs-only change. **Why it exists.**", 1)
    assert preamble != AUTHOR_PASS_VERBATIM, "a carve-out planted above rule 3 is not caught"
    # Bullets are folded mid-text, which is where they occur once the block is flattened —
    # the block opens with rule 3's heading, never with a list marker.
    assert _block_canon(_flat("x\n- a\n- b")) == _block_canon(_flat("x\n* a\n* b")), (
        "the list-marker fold is broken, so a `-`/`*` reformat would redden the block pin"
    )


# --------------------------------------------------------------------------------------
# Non-vacuity — mutations applied to the WHOLE partial, then re-sliced
# --------------------------------------------------------------------------------------
#
# Mutating the file rather than the section is deliberate: it is the only way a structural
# mutation (renaming the end marker, reordering the blocks) is reachable at all, and a
# section-scoped table cannot see the class Phase 167's round found by widening a window.

RULE_3_CHECKS: list[Callable[[str], list[str]]] = [
    rule_3_problems,
    rule_3_placement_problems,
    author_pass_problems,
]


def _at(text: str, anchor: str) -> int:
    """Start offset of `anchor`, tolerant of rewrapping and of the list marker.

    The structural mutations below slice the file by raw offsets. Anchored on exact text
    they broke on edits that are not defects: swapping a `-` bullet for `*` raised a bare
    `ValueError` out of six of them, and reflowing the subsection broke seven. That is the
    harness reddening on a reformat — the brittleness Phase 167 recorded as what trains
    people to weaken guards, reproduced here by this phase's own round.
    """
    i = text.find(anchor)
    if i >= 0:
        return i
    m = re.search(r"[-*]?\s*" + r"\s+".join(re.escape(w) for w in anchor.split()), text)
    assert m, f"mutation anchor not found: {anchor[:60]!r}"
    return m.start()


def _sub(old: str, new: str) -> Callable[[str], str]:
    """Whitespace-tolerant anchor.

    The exact-match form is the fast path and normally the one taken. The fallback exists
    because the anchors are raw file text while the checks they feed are whitespace-
    normalised: rewrapping a pinned sentence left every production check green and turned
    the suite red anyway, with `mutation source text not found` — a confusing failure about
    the harness, on an edit that is not a defect. Demonstrated by this phase's own round.
    """
    def go(text: str) -> str:
        if old in text:
            return text.replace(old, new, 1)
        m = re.search(r"\s+".join(re.escape(w) for w in old.split()), text)
        assert m, f"mutation source text not found: {old[:60]!r}"
        return text[:m.start()] + new + text[m.end():]
    return go


def _swap_rule_3_and_limits(text: str) -> str:
    """Ship the rule, but under the paragraph that scopes it — the precondition, inverted."""
    start = _at(text, RULE_3_HEADING)
    mid = _at(text, LIMITS_HEADING)
    end = text.index(AUTHOR_PASS_END, mid)
    return text[:start] + text[mid:end] + text[start:mid] + text[end:]


RULE_3_MUTATIONS: list[tuple[str, Callable[[str], str]]] = [
    ("M1 delete rule 3 outright",
     lambda t: t[:_at(t, RULE_3_HEADING)] + t[_at(t, LIMITS_HEADING):]),
    ("M2 ship rule 3 below the paragraph that scopes it", _swap_rule_3_and_limits),
    ("M3 restore the sentence rule 3 falsified", _sub(
        "Rule 3 narrowed this and left more than it took. Executing one command against a fixture *you* built reaches \"does it run\" and \"does it do what I said\", and stops there.",
        "It never executes the change against real state, and that is where the findings you most need come from.")),
    ("M4 drop half (ii), keep half (i)", lambda t: t[:_at(t, "**Build the fixture's inputs from the source of truth")] + t[_at(
        t, "**What it reaches is narrow"):]),
    ("M5 soften the literal-string instruction to a paraphrase", _sub(
        "Copy the literal string, resolve its placeholders the way the change tells an operator to resolve them, and run it.",
        "Run an equivalent command that exercises the same behaviour.")),
    ("M6 unbound the scope so the rule is reasonably ignored", _sub(
        "Scope this to commands whose operand the change **computes or substitutes** — `git log --oneline` has no operand to get wrong.",
        "Do this for every command the diff touches.")),
    ("M7 drop the honest limit inside the rule", _sub(
        "whether the command runs, and whether it does what you said it does. Nothing past that.",
        "quite a lot, in practice.")),
    ("M8 let rule 3 read as a substitute for a lens", _sub(
        "It converts one expensive finding into a cheap one; it does not replace a lens.",
        "It converts an expensive finding into a cheap one.")),
    ("M9 invert half (ii) while keeping its heading", _sub(
        "A fixture you populate from memory proves only that you are self-consistent.",
        "Where the writers are consistent, your own model of the inputs is a fine source.")),
    ("M10 delete the green/red mechanism, leaving half (ii) a platitude", _sub(
        "The same fixture runs **green** on the author's assumption and **red** on what the shipped writers actually emit",
        "Prefer accurate inputs")),
    ("M11 defer the rule until after the round", _sub(
        RULE_3_HEADING,
        "**3. Run the commands the change prescribes, in a throwaway repo — after the round, once the reviewers have reported.**")),
    ("M12 sever the tie to rule 1's population rule", _sub(
        "moved from what a guard **reads** to what a fixture **contains**", "restated for fixtures")),
    ("M13 drop the no-runner rationale", _sub(
        '"the prescribed command does not work" is invisible until that moment',
        "commands deserve a second look.")),
    ("M14 exempt prose-only changes in place", _sub(
        "Scope this to commands whose operand",
        "This is optional for prose-only changes. Scope this to commands whose operand")),
    ("M15 hand the rule back to the reviewers", _sub(
        "One of three lenses found it, by building a scratch repo and running the string;",
        "A reviewer will find it if it matters, so no need to run it yourself.")),
    ("M16 plant a second rule-3 heading below the limits paragraph", _sub(
        "Where the harness cannot spawn reviewers at all",
        RULE_3_HEADING + " Where the harness cannot spawn reviewers at all")),
    ("M17 rename the section end marker to widen the window", _sub(
        "## Prompt Template", "## Reviewer Prompt Template")),
    ("M18 blank the partial", lambda t: ""),
    # ---- the author-side battery's four survivors, kept as permanent regressions ----
    # Every one of these leaves the pin set fully intact and ADDS a contradicting sentence.
    # They are the measurement that turned `RULE_3_FORBIDDEN` from five literal phrases into
    # a screen over the four classes; without them the pins alone reported 16/20.
    ("M19 re-permit the assumed fixture alongside an intact half (ii)", _sub(
        "A fixture you populate from memory proves only that you are self-consistent.",
        "A fixture you populate from memory proves only that you are self-consistent. In practice the two agree, so either input is fine.")),
    ("M20 re-deny execution by paraphrase rather than by restoring the old sentence", _sub(
        "Where the harness cannot spawn reviewers at all",
        "This pass does not run anything against real state. Where the harness cannot spawn reviewers at all")),
    ("M21 demote rule 3 to a recommendation in place", _sub(
        RULE_3_HEADING, RULE_3_HEADING + " (a recommendation, not a requirement.)")),
    ("M22 threshold rule 3 by change size", _sub(
        "Scope this to commands", "Skip this for changes under ~50 lines. Scope this to commands")),
    # ---- a second battery's survivors: additive softenings, pin set fully intact ----
    # These are why the screen gained a modal pass over the rule-3 block and why commented
    # prose is stripped before slicing. Enumeration alone reported 5/12 against them.
    ("M23 comment the whole rule out, leaving every pinned word in the file", lambda t: (
        t[:_at(t, RULE_3_HEADING)] + "<!--\n"
        + t[_at(t, RULE_3_HEADING):_at(t, LIMITS_HEADING)] + "-->\n\n"
        + t[_at(t, LIMITS_HEADING):])),
    ("M24 carve out commands the author judges simple", _sub(
        "Copy the literal string",
        "You may skip the throwaway repo when the command looks simple. Copy the literal string")),
    ("M25 scope the rule to one skill family", _sub(
        "Scope this to commands whose operand",
        "This applies to lifecycle skills only. Scope this to commands whose operand")),
    ("M26 mark the rule historical", _sub(
        RULE_3_HEADING, RULE_3_HEADING + " *(historical — superseded; retained for the record.)*")),
    ("M27 assert reviewers re-run the commands anyway", _sub(
        "the other two read the same files and did not.",
        "the other two read the same files and did not; reviewers normally re-run these anyway.")),
    ("M28 contradict rule 3 from inside rule 2, where its pins do not look", _sub(
        "Check every new claim against the thing it describes",
        "Reading a command carefully is equivalent to running it. Check every new claim against the thing it describes")),
    ("M29 sever half (ii) from the rule it belongs to", _sub(
        "**Build the fixture's inputs from the source of truth, not from your own model of them.**",
        "**Build the fixture's inputs from the source of truth, not from your own model of them.** (This bullet concerns guard populations, not rule 3's fixtures.)")),
    ("M30 downgrade `run it` to `consider running it`", _sub(
        "and run it. In the round", "and consider running it. In the round")),
    # ---- a third battery's survivors ----
    # Two structural (a fenced rule renders as an example, a decoy heading steals the
    # slicer's window), two demotions phrased without a modal, two edits to the incident
    # evidence, and one that argued against the rule from inside it.
    ("M31 fence the rule so it renders as a quoted example", lambda t: (
        t[:_at(t, RULE_3_HEADING)] + "```\n"
        + t[_at(t, RULE_3_HEADING):_at(t, LIMITS_HEADING)] + "```\n\n"
        + t[_at(t, LIMITS_HEADING):])),
    ("M32 plant a softened decoy subsection above the real one", _sub(
        "## Running more than one reviewer\n",
        "## Running more than one reviewer\n\n" + AUTHOR_PASS_START
        + " — the author-side pass\n\nGive your guards a quick look before spawning.\n")),
    ("M33 call half (ii) aspirational, from the limits paragraph", _sub(
        "Where the harness cannot spawn reviewers at all",
        "The fixture half is aspirational in practice. Where the harness cannot spawn reviewers at all")),
    ("M34 mark rule 3's result unverified", _sub(
        "Rule 3 narrowed this and left more than it took.",
        "Rule 3 narrowed this and left more than it took. A fixture is not reality, so treat its result as unverified.")),
    ("M35 declare the rule not yet binding", _sub(
        "the other two read the same files and did not.",
        "the other two read the same files and did not. This rule is under evaluation and not yet binding.")),
    ("M36 argue against the rule from inside it", _sub(
        "by building a scratch repo and running the string", "by reading the string carefully")),
    ("M37 flip the incident's verdict", _sub(
        "**failed on a default install**", "**worked on a default install**")),
    # ---- a fourth battery's survivors ----
    # In this file `>` marks prompt text, so blockquoting re-addresses the rule rather than
    # softening it; the rest are a factual deflation, two demotions, and two inversions that
    # left the pinned clause intact and changed the sentence around it.
    ("M38 blockquote the rule, re-addressing it to the reviewer's prompt", lambda t: (
        lambda a, b: t[:a] + "\n".join("> " + ln for ln in t[a:b].splitlines()) + "\n\n" + t[b:])(
        _at(t, RULE_3_HEADING), _at(t, LIMITS_HEADING))),
    ("M39 deflate the rule's own counter-evidence", _sub(
        "43 of 90 guard mutations bypassing, and the false claims in its own record",
        "3 of 90 guard mutations bypassing, and one false claim in its own record")),
    ("M40 argue from the limits paragraph that the round is now rarely needed", _sub(
        "Where the harness cannot spawn reviewers at all",
        "With rule 3 in place a round is rarely needed. Where the harness cannot spawn reviewers at all")),
    ("M41 recast the rule as a record of past practice", _sub(
        "the other two read the same files and did not.",
        "the other two read the same files and did not. This records what one phase did; it is not an instruction.")),
    ("M42 assert the two halves are independent practices", _sub(
        "This is the half that does the work, and the easy one to drop.",
        "This is a separate practice, useful on its own and not required by the half above.")),
    ("M43 invert the honest-limit bullet by swapping only its lead-in", _sub(
        # No leading `- `: the list marker is presentation, and pinning it made a `-`->`*`
        # reformat go red for no semantic reason — Phase 167 recorded that exact lesson one
        # file over, and this phase's round reproduced it here.
        "**What it reaches is narrow, and the rule says so rather than leaving it implied:**",
        "**What it reaches is broad:**")),
    # ---- a fifth battery: four families of ADDITION, which is what the ratchet is for ----
    # This battery caught 4 of 14 before the ratchet and 14 of 14 after. The four kept here
    # are the families, not the instances: neutering by markup, supersession, redefinition of
    # a term the rule depends on, and an appended escape clause carrying no modal at all.
    ("M44 collapse the rule inside a <details> block", lambda t: (
        t[:_at(t, RULE_3_HEADING)] + "<details><summary>Rule 3</summary>\n\n"
        + t[_at(t, RULE_3_HEADING):_at(t, LIMITS_HEADING)] + "</details>\n\n"
        + t[_at(t, LIMITS_HEADING):])),
    ("M45 add a rule 4 that supersedes rule 3", _sub(
        "\n**What this pass cannot do.**",
        "\n**4. Where rule 3 is impractical, a careful read of the command discharges it.**\n\n**What this pass cannot do.**")),
    ("M46 redefine the source of truth as the plan you approved", _sub(
        "A fixture you populate from memory proves only that you are self-consistent.",
        "A fixture you populate from memory proves only that you are self-consistent. The source of truth for this purpose is the plan you approved.")),
    ("M47 append an escape clause carrying no modal", _sub(
        "before you spawn anyone.**", "before you spawn anyone.** Or after, if that is more convenient.")),
    # ---- a sixth battery's only survivor: a pin-coverage gap, not a new family ----
    # ---- the tests lens: carve-outs planted in the PREAMBLE, above rule 3 ----
    # Eight of eight survived a rule-3-scoped guard. They never touch rule 3 and they govern
    # how it reads, which is why the verbatim pin's window is the whole subsection now.
    ("M49 docs-only carve-out in the preamble", _sub(
        "**Why it exists.**", "Rule 3 does not bind a docs-only change. **Why it exists.**")),
    ("M50 redefine `source of truth` in the preamble", _sub(
        "**Why it exists.**",
        "Throughout this subsection, *source of truth* means the author's best current understanding of the shipped behaviour. **Why it exists.**")),
    ("M51 deny that the rule order carries a requirement", _sub(
        "**Why it exists.**", "The order of the three rules carries no requirement. **Why it exists.**")),
    ("M52 license a paraphrase of the command, from the preamble", _sub(
        "**Why it exists.**",
        "Where the literal string is awkward to run, a close paraphrase of it is fine. **Why it exists.**")),
    ("M48 reverse the no-runner rationale, leaving its conclusion pinned and unsupported", _sub(
        "nothing runs a command generally, so **a newly prescribed one stays text until an operator reaches it**",
        "skill prose is covered by the suite like everything else")),
]


@pytest.mark.parametrize("name,mutate", RULE_3_MUTATIONS, ids=[m[0] for m in RULE_3_MUTATIONS])
def test_every_rule_3_mutation_is_caught(name, mutate):
    shipped = PARTIAL.read_text(encoding="utf-8")
    mutated = mutate(shipped)
    assert mutated != shipped, f"mutation {name!r} was a no-op — it no longer matches the shipped text"
    section = _author_pass_slice(mutated)
    failures = [f for check in RULE_3_CHECKS for f in check(section)]
    assert failures, f"mutation {name!r} survived every check"


def test_innocent_reformats_stay_green():
    """The other direction. A guard that reddens on rewrapping trains people to weaken it —
    15 innocent edits went red in the module Phase 167's round disqualified, which is how the
    verbatim-but-whitespace-normalised primitive was arrived at."""
    shipped = PARTIAL.read_text(encoding="utf-8")
    # Toggles, not fixed substitutions. Written as "add two spaces" / "`-` becomes `*`" they
    # were no-ops the moment the shipped file already carried that formatting — so applying
    # the very reformat this test blesses turned it red with `is a no-op`, a false failure
    # about the harness on an edit that is not a defect. Each of these changes the text
    # whatever form it is currently in.
    reformats = {
        "rewrap the rule across a line break": lambda t: re.sub(
            r"(Copy the literal string,)(\s+)(resolve)",
            lambda m: m.group(1) + (" " if "\n" in m.group(2) else "\n") + m.group(3),
            t, count=1),
        "re-indent the bullets": lambda t: re.sub(
            r"(?m)^([ \t]*)([-*] \*\*Build the fixture's inputs)", r" \1\2", t, count=1),
        "switch the bullet marker": lambda t: re.sub(
            r"(?m)^([ \t]*)([-*])( \*\*What it reaches is narrow)",
            lambda m: m.group(1) + ("-" if m.group(2) == "*" else "*") + m.group(3),
            t, count=1),
    }
    for name, reformat in reformats.items():
        reformatted = reformat(shipped)
        # A no-op reformat passes this test while proving nothing — the vacuity class this
        # module is named for, reached through its own negative control.
        assert reformatted != shipped, f"reformat {name!r} is a no-op against the shipped text"
        section = _author_pass_slice(reformatted)
        failures = [f for check in RULE_3_CHECKS for f in check(section)]
        assert failures == [], f"innocent reformat {name!r} went red: {failures}"


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


# --- Phase 162: model diversity is a review dimension --------------------------
#
# Provenance: a consumer's cutover to a new frontier model surfaced a wave of real
# defects in text that had passed same-model review repeatedly. Author and reviewer
# sharing a model share a tolerance profile, so the class is invisible to the round
# by construction. These guards pin the rule into the *shipped* partial — the same
# mistake Phase 154 fixed for the never-forks rule, which had lived only in the
# maintainer's CLAUDE.md where no consumer ever saw it.

_MODEL_UPGRADE_IS_A_REVIEW_EVENT = (
    r"model upgrade is itself a review event",
    r"frontier model ships",
    r"tolerance profile",
)


def test_model_upgrade_is_a_review_event_ships_to_consumers():
    section = _multi_reviewer_section()
    missing = [p for p in _MODEL_UPGRADE_IS_A_REVIEW_EVENT if not re.search(p, section, re.I)]
    assert missing == [], (
        "the shipped multi-reviewer procedure no longer tells consumers that a model "
        f"cutover is a re-read trigger: {missing}"
    )


def test_cross_model_reviewer_rule_stays_portable():
    """It must be conditional on the harness, never a hard requirement.

    A consumer may have exactly one model available. The portable requirement is fresh
    context; a different model only sharpens it. A rule stated unconditionally here
    would be unsatisfiable for those consumers — the exact shape Phase 154's own round
    retired when it killed a universal-isolation rule that contradicted seven shipped
    sites.
    """
    section = _multi_reviewer_section()
    assert re.search(r"different model", section, re.I), "the cross-model rule is gone"
    conditional = re.search(
        r"[Ww]here the harness offers more than one model", section
    )
    assert conditional, "the cross-model rule lost its harness-conditional framing"
    assert re.search(r"[Nn]ever \*?assume\*? it", section), (
        "the rule no longer warns against assuming a second model is available"
    )


def test_compound_findings_heading_resolves_for_its_citers():
    """Three shipped files cite `§ Compound findings`; it must be a real heading.

    Until Phase 162 the rule was a bolded paragraph inside `## Classification Rubric`,
    so a reader that grepped for the cited heading found nothing — and three of those
    citations sit on rules the review skills mark mandatory at the fan-out merge.
    """
    assert re.search(r"^#{2,4}\s*Compound findings", _partial(), re.M), (
        "`Compound findings` is not an addressable heading, but shipped files cite it as one"
    )
    repo_root = REPO_ROOT / "core" / "skills"
    citers = [
        p for p in repo_root.rglob("*.md")
        if "adversarial-review.md` § Compound findings" in p.read_text(encoding="utf-8")
    ]
    assert len(citers) >= 3, f"expected the known citers to still cite it, found {citers}"


def test_that_model_diversity_guard_is_not_vacuous():
    """Non-vacuity twin, added by Phase 162's own round.

    Every other predicate constant in this module has one; the Phase-162 addition
    shipped without. Emptying the tuple made `missing == []` and the guard passed —
    vacuous by this suite's own standard, in the phase whose subject is guards that
    assert nothing.
    """
    assert _MODEL_UPGRADE_IS_A_REVIEW_EVENT, "the predicate is empty — the guard asserts nothing"
    planted = "reviewers should ideally differ in some way"
    assert [p for p in _MODEL_UPGRADE_IS_A_REVIEW_EVENT if not re.search(p, planted, re.I)]


_SOFTENED_AUTHOR_PASS = """\
### Before you spawn anyone — the author-side pass

Mutate the guard's assumptions, not the content it checks. A mutation set that only reverts
the text a guard asserts proves nothing, so skip those. Consider what the guard matches on.
Name the survivors you are choosing not to close. More reviewers is the expensive way to
treat this, so stop paying reviewers for what you can see yourself.
"""


def test_the_author_pass_predicate_rejects_the_defects_its_round_found():
    """Non-vacuity through the production predicate.

    The fixture is Phase 166's shipped-then-corrected text: exclusive "not the content it
    checks" with no reversion/vacuity carve-out, an unbounded residual licence, no role
    binding, no population rule, and the cost argument without its counter-finding. Its own
    round found every one of those, and this asserts the predicate still does.
    """
    problems = author_pass_problems(_SOFTENED_AUTHOR_PASS)
    assert any("reversion-guard-carve-out" in p for p in problems), problems
    assert any("vacuity-guard-carve-out" in p for p in problems), problems
    assert any("residual-criterion" in p for p in problems), problems
    assert any("role-binding" in p for p in problems), problems
    assert any("population-from-source-of-truth" in p for p in problems), problems
    assert any("counter-finding" in p for p in problems), problems


def test_the_hedge_list_catches_cost_framed_softenings():
    """The paraphrases Phase 166's round walked through the section with, verbatim."""
    for softening in (
        "Given the cost, a single reviewer is often the right call; add a second only "
        "when the change is large.",
        "One reviewer suffices for most changes; the rules above are recommendations you "
        "may weigh against the token spend.",
    ):
        assert section_problems(
            "## Running more than one reviewer\n\n" + softening
        ), f"a cost-framed softening passed unflagged: {softening!r}"
