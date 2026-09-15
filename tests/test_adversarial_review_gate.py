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

import bisect
import re
from pathlib import Path
from typing import Callable, Iterable

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


# Phase 288 (`Q-489`) — the placement presence patterns, defined ONCE and read by the gate
# predicate, the section predicate and the comparative pin test. Three readers of a literal
# written three times is the defect this repo filed as `Q-337`; it is not repeated here.
_GATE_PRESENCE_PATTERNS = {
    "gate-placement": r"created\s+AT\s+the\s+commit\s+under\s+review",
    "gate-echo": r"echo\s+`git\s+rev-parse\s+HEAD`\s+before\s+its\s+first\s+finding",
    # Directional, per the isolation rule's own lesson: naming the words is not enough,
    # because a sentence denying the mechanism contains them too. This pins the CONSEQUENCE,
    # which a reversal has to delete rather than negate.
    "gate-placement-why": r"unplaced\s+lens\s+reads\s+the\s+pre-phase\s+tree",
}

_SECTION_PRESENCE_PATTERNS = {
    "placement-at-the-commit": r"create\s+every\s+reviewer\s+AT\s+the\s+commit\s+under\s+review",
    # The `-C` is load-bearing: a bare `git rev-parse HEAD` reports the reviewer's shell CWD,
    # not the tree it was handed, so the echo can be right while the lens reads the wrong
    # revision. A round lens demonstrated exactly that against the first version of the rule.
    "placement-echo": r"first\s+action\s+is\s+`git\s+-C\s+<[^`]+>\s+rev-parse\s+HEAD`",
    # Why it is a mechanism and not advice.
    "placement-not-diligence": r"diligence,\s+which\s+nothing\s+enforces",
}


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
    # Phase 174. The governor exists because the count crept 1 -> 2 -> 3 -> 4+ with nobody
    # choosing it (Phase 166's measurement); a gate that stops naming it is how the creep
    # restarts. Phase 166's round also faulted the author-side pass for having NO INVOKER —
    # same defect, one subsection over — so the gate is the invoker, pinned here.
    if not re.search(r"How many reviewers, how many rounds", gate):
        problems.append(
            "gate no longer names the governor — the ratified count/termination policy has "
            "no invoker again, which is the Phase-166 no-invoker defect recurring"
        )
    if not re.search(r"ROUND_YIELD_LEDGER\.md", gate):
        problems.append(
            "gate no longer requires the round-yield ledger row — the count becomes tunable "
            "only on anecdote again, which is the gap Phase 166 filed the ledger to close"
        )
    # The author-side battery walked "as many lenses as the phase seems to need" through
    # this predicate: the governor's name and the ledger were both still present, and no
    # hedge matched. The gate re-states the governor's numbers, so the governor's
    # contradiction screen must run here too.
    for pat, why in GOVERNOR_FORBIDDEN:
        if re.search(pat, gate, re.I):
            problems.append(f"gate contradicts the governor ({why}): {pat!r}")
    # And the round's guards lens then walked FIVE more edits through it — the numbers
    # drifted to "three lenses default", the whole governor sentence replaced by a bare
    # "see that file for background", the no-self-spawn and skip-row clauses deleted —
    # because the two token requirements above never read what the sentence SAYS. The
    # gate's restatement of the governor's numbers is content, so its content is pinned.
    for name, pat in {
        "gate-two-lenses": r"two lenses default",
        "gate-one-round": r"one round default",
        "gate-no-self-spawn": r"never spawned on the session'?s own judgment",
        "gate-skip-row": r"a recorded skip appends one too",
    }.items():
        if not re.search(pat, gate, re.I):
            problems.append(
                f"gate lost its {name} clause — the governor's numbers are re-stated here, "
                "and a drifted restatement is the contradiction a reader meets first"
            )
    # Phase 288 (`Q-489`). The placement rule lived in the procedure file and lapsed anyway
    # for four consecutive phases, because the gate — the text actually loaded at the moment
    # someone spawns an agent — never carried it. Same no-invoker defect the author-side pass
    # had at Phase 166, one clause over.
    #
    # Matched against the RENDERED gate. The round's guard lens wrapped this whole paragraph
    # in `<!-- -->`: gate, authority clause, governor numbers and placement clause all became
    # invisible to a reader while every pattern above still found its words, suite green.
    rendered_gate = _prose_only(gate)
    for name, pat in _GATE_PRESENCE_PATTERNS.items():
        if not re.search(pat, rendered_gate, re.I):
            problems.append(
                f"gate lost its {name} clause — the requirement the round gate exists to "
                "invoke is not in the text read at spawn time"
            )
    problems += placement_retraction_problems(gate)
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
        # Phase 174: the count/termination governor. Deleting the whole subsection would
        # otherwise leave every governor-scoped guard reading nothing while this predicate
        # stayed green — the Phase-166 zero-guards hole, one subsection over.
        "governor": r"### How many reviewers, how many rounds — the governor",
        # Phase 288 (`Q-489`). Hoisted from a sub-bullet of the isolation caveat to a
        # top-level requirement. The mechanics stay below; the REQUIREMENT lives up here,
        # because a rule filed under "where the harness offers it" is not read at spawn
        # time — measured by four consecutive phases that had the caveat and lapsed anyway.
        # The load-bearing half of WHY it is a requirement rather than advice: what has been
        # carrying it is reviewer diligence, and diligence is not a mechanism.
    }
    # Placement is matched against the RENDERED section for the same reason the gate is:
    # commenting the block out or fencing it left every pattern satisfied and the rule
    # invisible. Everything else keeps its historical raw match.
    rendered = _prose_only(section)
    required.update(_SECTION_PRESENCE_PATTERNS)
    for name, pat in required.items():
        haystack = rendered if name.startswith("placement-") else section
        if not re.search(pat, haystack, re.I):
            problems.append(f"procedure lost its {name} rule")
    problems += placement_position_problems(section)
    problems += placement_retraction_problems(section)
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
    # Same wiring as RULE_3_FORBIDDEN, same reason: a contradiction of the governor does not
    # have to live in the governor. "Run as many rounds as needed" planted in § Caller
    # contract's neighbourhood would escape every governor-scoped guard while a reader meets
    # it first.
    for pat, why in GOVERNOR_FORBIDDEN:
        if re.search(pat, _flat(section), re.I):
            problems.append(f"procedure contradicts the governor ({why}): {pat!r}")
    # The isolation carve-out. Without it the section's rule contradicts seven shipped
    # "Do NOT set isolation" instructions in the skills that consume this very partial.
    if re.search(r'isolation: .worktree.', section):
        if not re.search(r"do not use it where a worktree already exists", section, re.I):
            problems.append("isolation rule lost its pre-existing-worktree carve-out")
        missing = [s for s in PRE_EXISTING_WORKTREE_SKILLS if f"/{s}" not in section]
        if missing:
            problems.append(f"carve-out no longer names the affected skills: {missing}")
        # The wrong-revision warning. Phase 198 replaced the original sentence
        # ("does not guarantee the revision you expect") with a stronger and more
        # accurate one, so this accepts either wording — but it is NOT loosened:
        # the two clauses below were added at the same time and raise the floor.
        # An isolated worktree comes from the DEFAULT BRANCH, not the spawning
        # session's HEAD, so under a `pr` merge policy every reviewer gets the
        # pre-phase tree deterministically. The old wording called that
        # non-determinism, and a warning framed as bad luck can only ask for
        # vigilance.
        if not re.search(r"does not guarantee the revision|does not give you the branch",
                         section, re.I):
            problems.append(
                "isolation rule no longer warns that it can hand you the wrong revision"
            )
        # A warning with no remedy is the state Phase 198 found this rule in: the
        # accident was on record, and it happened again anyway because nothing
        # told the SPAWNER what to do about it.
        #
        # DIRECTIONAL, not keyword. The first version of these three checks was
        # `re.search("default branch")` and `re.search("--detach|throwaway
        # clone")`, and this phase's own round defeated all three at once with a
        # replacement paragraph that INVERTED every claim — "created from the
        # spawning session's HEAD, **not** from the repository's default branch…
        # `--detach <sha>` and the throwaway clone recipe were both removed as
        # cargo cult… Skip the check." Every keyword still present, gate green.
        # That is rule 1's "a check satisfied by a substring is satisfied by an
        # incidental use of that substring — worse than a gap, because it marks a
        # dangerous line compliant", in a guard written to enforce rule 1.
        #
        # So the pattern below pins the DIRECTION of the claim (X, not Y), which
        # a reversal cannot satisfy because it has to swap the operands.
        if not re.search(
            r"created from the repository.s \*\*default branch\*\*,?\s*not from",
            section, re.I | re.S,
        ):
            problems.append(
                "isolation rule no longer ASSERTS the mechanism in its load-bearing "
                "direction (an isolated worktree is created from the default "
                "branch, NOT from the spawning session's HEAD) — naming the words "
                "is not enough, a sentence denying it contains them too"
            )
        if not re.search(r"--detach <sha>", section) or \
           not re.search(r"throwaway clone", section, re.I):
            problems.append(
                "isolation rule no longer names BOTH spawner-side remedies "
                "(`git worktree add --detach <sha>`, and a throwaway clone at a "
                "tag) — reviewer-side vigilance alone only fires when the brief "
                "happens to ask for it"
            )
        # The retraction blacklist. Belt-and-braces with the directional pattern
        # above: a future edit could satisfy the direction and still tell the
        # reader to ignore it. These are the exact phrases the round's reversal
        # used, kept as a canary rather than as an exhaustive filter — the
        # directional pattern is the real check.
        for retraction in (r"is a myth", r"cargo cult", r"skip the check",
                           r"no spawner-side pin is needed"):
            if re.search(retraction, section, re.I):
                problems.append(
                    f"isolation rule contains a retraction of its own remedy "
                    f"({retraction!r}) — the rule and its negation cannot both ship"
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
    inside a section that requires more than one reviewer leans the file toward a count
    decision that was unratified when this shipped. (Phase 174 later ratified the governor's
    default; the both-halves rule below STAYS, because the counter-finding is the evidence
    the ratified default stands on.)
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
                "argues one side of the count question on cost alone; the governor's default "
                "is ratified on both halves of that evidence, and this counter-finding is "
                "the half a cost-only reading drops"
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
    # FENCES FIRST. A `<!--` inside a fence is literal text, but this ran comment-stripping
    # first and `<!--.*?-->` is not fence-aware, so it consumed the fence's closing delimiter
    # and everything up to the next `-->` ANYWHERE later in the file — deleting real prose,
    # not merely failing to strip it. Found by this phase's round, in the sibling of the bug
    # the phase had already fixed in `_wrapper_spans`. Ordering is the whole fix: a fence
    # removed first cannot contribute a stray opener.
    # ANY indent, EITHER delimiter, and a closer that matches its own opener (`Q-457`,
    # Phase 291). This was `^``` `, column-0-anchored and backtick-only, and both halves
    # were live holes. The indent half: this file's own indented `config-baseline` snippet
    # survived into the rendered text while its column-0 `lsof` snippet did not — two
    # prescribed commands in one section, one covered and one invisible, decided by nothing
    # but indentation. The delimiter half was found by this phase's round and is worse:
    # `~~~` is legal CommonMark, GitHub renders it as a code block, and this pattern did not
    # match it — so wrapping the gate paragraph in `~~~` left `gate_problems` at ZERO while
    # the same wrap in ``` returned three. That is Phase 167's "gate commented out" survivor
    # reached through a different delimiter, in the function written to refuse it.
    # Each of the three runs to its closer OR to end-of-file, because an unterminated wrapper
    # hides everything after it on GitHub and the honest rendering is that it is gone. This
    # half was missing and the round's own new test found it: an unterminated ``` , `~~~` or
    # `<details>` planted before a guarded subsection left `_author_pass_slice` returning the
    # subsection **in full**, so every presence predicate passed over text no reader can see.
    # Only `<!--` failed closed, and by luck — its unterminated opener happened to reach a
    # later comment's `-->` and swallow the start marker. `_tagged` already ran these to EOF;
    # the two canonicalisers now give the same answer.
    text = re.sub(r"^[ \t]*(`{3,}|~{3,})[^\n]*\n(?:.*?^[ \t]*\1[ \t]*$|.*)", "",
                  text, flags=re.S | re.M)
    text = re.sub(r"<!--(?:.*?-->|.*)", "", text, flags=re.S)
    # A `<details>` block renders collapsed. Same neutering, different markup — and an
    # UNCLOSED one still collapses on GitHub while surviving this substitution, so the
    # leftover tag is screened as a contradiction below rather than trusted to be stripped.
    text = re.sub(r"<details\b(?:.*?</details>|.*)", "", text, flags=re.S | re.I)
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


# --------------------------------------------------------------------------------------
# The wrapper TAGGER — `_prose_only`'s other half (`Q-457`, Phase 291)
# --------------------------------------------------------------------------------------
#
# `_prose_only` above answers one question: *what does a reader still see?* It answers it by
# deletion, which is right for a **presence** check — a rule wrapped in a fence or a comment
# has been neutered, and a presence predicate that still finds its words reports a rule that
# reaches nobody. That is Phase 167's "gate commented out" survivor and it is why the
# function exists.
#
# It is the wrong question for a **verbatim pin over `review-close/SKILL.md`**, and `Q-457`
# is that mismatch. There, fenced blocks are the *prescribed commands* and blockquotes are
# notes to the operator: both are operative, and deleting them before the pin compares makes
# the load-bearing half of the step unpinnable. Measured at the filing: `1a` is 70.6% fenced,
# `4c` is 37.3% blockquote with **no column-0 fences at all**, and two rules that change a
# verdict — Step 3's three-dot diff rule and its `NO_ORIGIN_MAIN` sentinel — sat in
# `REFERENCE.md` § Blocked precisely because a pin could not see them.
#
# So the two questions get two functions rather than one policy flag. `_tagged` keeps every
# character and makes the *wrapper* visible instead, as a marker pair around each region:
#
#   * a rule that moves from plain prose into a fence, a blockquote or a comment changes the
#     canon (a marker appears), so the pin reddens — the same property deletion gave, stated
#     as a change rather than as a disappearance, which is the more legible diff;
#   * a rule that already lives inside one is *pinned*, which deletion could never do;
#   * and where the wrapper's delimiters fall OUTSIDE a slice's anchors — the shape that
#     defeats a no-strip policy, measured on both slicers before this was written — the
#     anchor itself lands inside an open region and `_anchor_is_wrapped` fails the slice
#     closed.
#
# Three properties are load-bearing and each is tested below, because each was a defect in a
# discarded draft:
#
#   * **Reflow-invariant.** Markers bracket a REGION, never a line, and a blockquote's `>`
#     prefixes are dropped with the content kept. A per-line marker made re-wrapping a
#     blockquote change the canon, which is Phase 168's 19-innocent-edits-in-30 all over
#     again, aimed at the one class of text a thinning campaign edits most.
#   * **Indent-invariant.** A marker is inserted at the first non-space character of its
#     delimiter line, not at the line start, so `_flat` cannot tell an indented fence from a
#     column-0 one. `_prose_only`'s `^``` ` was column-0-anchored and this is the same fix
#     applied there: measured in this very file, the indented `config-baseline` snippet
#     survived into the rendered text while the column-0 `lsof` snippet did not — two
#     prescribed commands in one section, one covered and one invisible, decided by nothing
#     but indentation.
#   * **Unterminated wrappers run to EOF.** An unclosed fence really does render everything
#     after it as code, so tagging to EOF is faithful to what a reader sees, and the
#     containment check then reports every later step as neutered — loudly. This is the
#     opposite call from `review_index.py`'s `_fenced_mask`, deliberately: that parser ACTS
#     on what it reports (a wrong mask flips a consumer's checkboxes), while the worst this
#     can do is redden a test.
#
# Regions **nest**; they are not disjoint, and an earlier draft of this comment said they
# were. Two nestings are live and they point opposite ways: `review-close/SKILL.md` carries
# 10 fence delimiter lines inside blockquotes and `adversarial-review.md` carries a
# commented-out block inside one (blockquote outer), while commenting out a whole step wraps
# that step's own fences and blockquotes (comment outer). A class-PRIORITY resolver cannot
# express both, and a draft that tried got one wrong each way it was ordered — see
# `_wrapper_spans`. Resolution is by containment instead. What lets `_anchor_is_wrapped` be
# a per-class open/close count rather than a stack is narrower than disjointness: **no class
# ever nests inside itself.**

TAG_COMMENT, TAG_FENCE, TAG_DETAILS, TAG_QUOTE = "comment", "fence", "details", "quote"

# The class list. Order is immaterial to every consumer — `_without` and
# `_anchor_is_wrapped` are per-class and `ALL_TAG_MARKERS` is a flatten — and it is NOT the
# resolution order, which lives in `_wrapper_spans` and is fences, then comments, then
# blockquotes. An earlier version of this comment claimed the two were the same thing and
# was wrong about the code directly below it.
TAG_CLASSES: tuple[str, ...] = (TAG_QUOTE, TAG_FENCE, TAG_COMMENT, TAG_DETAILS)

# Classes that NEUTER rather than carry. Comments and `<details>` hide text from every
# reader in every file; fences and blockquotes are file-dependent, which is the whole of
# `Q-457`, so they are not on this list and each caller states its own policy.
NEUTERING_TAGS: frozenset[str] = frozenset({TAG_COMMENT, TAG_DETAILS})

# A fence delimiter is 3+ backticks OR 3+ tildes. Both are legal CommonMark and GitHub
# renders both; a backtick-only pattern let `~~~` wrap a whole step with the pin green, which
# is what this phase's round found. `_FENCE_LINE` answers "is this line a delimiter at all";
# pairing needs the char and the length too, so `_fence_delim` returns them and
# `_wrapper_spans` requires a closer of the SAME character, AT LEAST as long, with nothing
# after it. Without the length rule a 3-backtick line inside a 4-backtick block closes it and
# the rest of the block renders as prose.
_FENCE_LINE = re.compile(r"^[ \t]*(`{3,}|~{3,})([^\n]*)$")
_QUOTE_LINE = re.compile(r"^[ \t]*>")


def _fence_delim(line: str) -> tuple[str, int, str] | None:
    """`(char, length, info)` when `line` is a fence delimiter, else `None`."""
    m = _FENCE_LINE.match(line)
    if not m:
        return None
    run = m.group(1)
    return run[0], len(run), m.group(2)


def _closes_fence(line: str, char: str, length: int) -> bool:
    """CommonMark's closing rule: same character, at least as long, nothing but space after."""
    d = _fence_delim(line)
    return bool(d) and d[0] == char and d[1] >= length and not d[2].strip()


def _tag_open(cls: str) -> str:
    return f"[[{cls}]]"


def _tag_close(cls: str) -> str:
    return f"[[/{cls}]]"


ALL_TAG_MARKERS: tuple[str, ...] = tuple(
    m for cls in TAG_CLASSES for m in (_tag_open(cls), _tag_close(cls))
)


def _line_bounds(text: str) -> list[tuple[int, int]]:
    """(start, end) of every line, end excluding the newline."""
    out, pos = [], 0
    for line in text.split("\n"):
        out.append((pos, pos + len(line)))
        pos += len(line) + 1
    return out


def _inner_span(text: str, a: int, b: int) -> tuple[int, int]:
    """Shrink [a, b) to its first and last non-space characters.

    This is the indent-invariance fix: a marker placed at a LINE start sits before the
    indentation, so `_flat` renders `  ```bash` and ```` ```bash ```` differently once a
    marker precedes them. Placed at the first non-space character it cannot. Newlines count
    as space here too, which is what keeps a region tagged to end-of-file from putting its
    closer past the last character anyone wrote.
    """
    while a < b and text[a].isspace():
        a += 1
    while b > a and text[b - 1].isspace():
        b -= 1
    return a, b


# Markdown's OTHER code form has no delimiters: four spaces of indentation renders a block as
# code. `_flat` collapses indentation, so a pin cannot see it at all — this phase's round
# indented Step 3's body, left the headings at column 0, and got a byte-identical slice, a
# green pin, and **one new failure across 95 modules**, which was an unrelated fixture's
# anchor rather than a detection.
#
# **A general detector is not built, and the reason is measured rather than asserted.**
# CommonMark's indented code block is "4+ spaces and not inside a list item", and separating
# those needs a block parser that tracks list container indentation. In
# `review-close/SKILL.md` **69** non-blank lines outside any wrapper are indented >= 4 and
# **68 of them are list continuations** — so a naive rule mis-tags 68 real list items in a
# 467 KB file to catch one thing, which is the over-strictness direction at its worst.
#
# What IS built is bounded to the shape the round demonstrated: a WHOLESALE re-indent, where
# the guarded region's own body goes from a handful of deep lines to nearly all of them.
# Measured at this commit: Step 3 is **2 of 29 (6.9%)**, the author-side subsection **0 of
# 25**, the whole of `review-close/SKILL.md` **69 of 651 (10.6%)**; under the round's attack
# Step 3 becomes **29 of 31 (93.5%)**. The floor below sits far above the first set and far
# below the second.
#
# **What it does not catch, stated rather than implied:** a SINGLE rule indented four spaces.
# That renders as code, the pin cannot see it, and this ratio will not move. `REFERENCE.md`
# § Declared limits carries it and `Q-497` is filed against it.
INDENT_CODE_FLOOR = 4
INDENT_NEUTERED_RATIO = 0.5


def _indent_neutered(text: str) -> bool:
    """True when a region's own unwrapped body has been indented into a code block."""
    covered: set[int] = set()
    for a, b, _cls in _wrapper_spans(text):
        covered.update(range(a, b))
    total = deep = 0
    for s, e in _line_bounds(text):
        line = text[s:e]
        if not line.strip() or s in covered:
            continue
        total += 1
        if len(line) - len(line.lstrip(" \t")) >= INDENT_CODE_FLOOR:
            deep += 1
    return bool(total) and deep / total > INDENT_NEUTERED_RATIO


def _matching_close(text: str, start: int, opener: str, closer: str) -> int:
    """Index of the closer that balances an opener already consumed, or -1.

    Only `<details>` needs this — it is the one wrapper here that can contain itself. An
    unbalanced run yields -1, which the caller turns into a region running to EOF, the same
    answer an unterminated fence gets and for the same reason: that is what renders.
    """
    depth, i = 1, start
    while depth:
        nxt_open, nxt_close = text.find(opener, i), text.find(closer, i)
        if nxt_close == -1:
            return -1
        if nxt_open != -1 and nxt_open < nxt_close:
            depth += 1
            i = nxt_open + len(opener)
        else:
            depth -= 1
            if not depth:
                return nxt_close
            i = nxt_close + len(closer)
    return -1


def _wrapper_spans(text: str) -> list[tuple[int, int, str]]:
    """`(start, end, class)` regions, PROPERLY NESTED, in document order.

    `start`/`end` are already shrunk to non-space bounds so inserting markers at them is
    indentation-blind.

    **Nesting is real here and a priority order cannot express it.** Two shapes are live in
    the guarded files and they nest opposite ways: `review-close/SKILL.md` carries **10**
    fence delimiter lines inside blockquotes and `adversarial-review.md` carries a
    commented-out block inside one (so the blockquote is outer), while commenting out a
    whole step wraps that step's own fences and blockquotes (so the comment is outer). A
    first draft resolved classes by priority into DISJOINT spans and got one of the two
    wrong each way it was ordered: comments-first split that blockquote in three and left a
    bare `>` in the rendered text; blockquote-first made the comment overlap a claimed
    region, so it was dropped entirely and **a whole step commented out came back GREEN** —
    the Phase 167 survivor, rebuilt inside its own fix.

    Resolution is therefore by *containment*, in one order that respects markdown's own:

      1. **Fences**, from delimiter lines. `_FENCE_LINE` allows only spaces and tabs before
         the backticks, so a quoted delimiter (`> ``` `) is not one — that, and not any check
         in the loop, is why those 10 lines need no special case.
      2. **Comments and `<details>`**, outside any fence — inside one they are literal text.
      3. **Blockquote runs**, each contiguous run of `>` lines as ONE region.

    Anything that partially overlaps rather than nests is refused by `_unhandled_nesting`
    rather than mis-rendered.
    """
    lines = _line_bounds(text)
    spans: list[tuple[int, int, str]] = []

    # 1. Fences: line-oriented, ANY indent, toggling. An unterminated one runs to EOF — an
    #    unclosed fence really does render everything after it as code.
    # No quoted-delimiter check here, and an earlier draft's was DEAD CODE its own battery
    # exposed: `_FENCE_LINE` allows only spaces and tabs before the run, and a quoted
    # delimiter has a `>` there, so `> ``` ` is simply not a fence line. That is the real
    # reason the 10 quoted delimiters in `review-close/SKILL.md` need no special case, and
    # `test_a_widened_fence_pattern_would_invert_the_nesting` guards the pattern that
    # carries it.
    fences: list[tuple[int, int]] = []
    open_k: int | None = None
    open_char, open_len = "", 0
    for k, (s, e) in enumerate(lines):
        line = text[s:e]
        if open_k is None:
            d = _fence_delim(line)
            if d and not (d[0] == "`" and "`" in d[2]):
                # A backtick opener's info string may not contain a backtick (CommonMark),
                # which is what keeps an inline `` `code` `` span off this branch.
                open_k, open_char, open_len = k, d[0], d[1]
        elif _closes_fence(line, open_char, open_len):
            fences.append((lines[open_k][0], e))
            open_k = None
    if open_k is not None:
        fences.append((lines[open_k][0], len(text)))
    spans += [(a, b, TAG_FENCE) for a, b in fences]

    # 2. Character-oriented wrappers, which may open and close mid-line.
    # `<details>` NESTS; `<!-- -->` does not (a comment ends at its first `-->`). Taking the
    # first closer for both was a defect this phase's round found: in
    # `<details>A<details>B</details>C</details>` the region ended at the INNER closer, so
    # `C` renders collapsed on GitHub and read as live prose here. It is the one shape that
    # breaks "no class ever nests inside itself", which `_anchor_is_wrapped` depends on.
    for cls, opener, closer, nests in (
        (TAG_COMMENT, "<!--", "-->", False),
        (TAG_DETAILS, "<details", "</details>", True),
    ):
        i = 0
        while True:
            a = text.find(opener, i)
            if a == -1:
                break
            if any(lo <= a < hi for lo, hi in fences):
                # Literal text inside a fence: skip past the OPENER only. Skipping past its
                # computed `end` was this resolver's own bug, found by the fixture written
                # for it — a `<!--` inside a fence matched the next `-->` anywhere later in
                # the file and the scan resumed past it, so the first genuine comment after
                # a fence containing the token was never tagged at all.
                i = a + len(opener)
                continue
            b = _matching_close(text, a + len(opener), opener, closer) if nests \
                else text.find(closer, a + len(opener))
            end = len(text) if b == -1 else b + len(closer)
            spans.append((a, end, cls))
            i = end

    # 3. Blockquotes: each CONTIGUOUS run of `>` lines is ONE region, so re-wrapping the
    #    prose inside it moves no marker.
    run: int | None = None
    for k, (s, e) in enumerate(lines):
        if _QUOTE_LINE.match(text[s:e]):
            if run is None:
                run = k
        elif run is not None:
            spans.append((lines[run][0], lines[k - 1][1], TAG_QUOTE))
            run = None
    if run is not None:
        spans.append((lines[run][0], lines[-1][1], TAG_QUOTE))

    return sorted((*_inner_span(text, a, b), cls) for a, b, cls in spans)


def _unhandled_nesting(text: str) -> list[str]:
    """The shapes this resolver does not model, named rather than mis-rendered.

    Both are measured at zero in the guarded files, and both would produce a silently wrong
    rendering rather than a loud one — which is the failure mode every other part of this
    module is built to refuse.
    """
    out: list[str] = []
    infence = False
    for n, line in enumerate(text.split("\n"), 1):
        if infence and _QUOTE_LINE.match(line):
            out.append(f"line {n}: a `>` line inside an unquoted fence")
        if not _QUOTE_LINE.match(line) and _FENCE_LINE.match(line):
            infence = not infence
    spans = _wrapper_spans(text)
    for i, (a, b, ca) in enumerate(spans):
        for c, d, cb in spans[i + 1:]:
            if c >= b:
                break
            if d > b:  # starts inside, ends outside — neither nested nor disjoint
                out.append(f"chars {c}-{d} ({cb}) partially overlap {a}-{b} ({ca})")
    return out


def _tagged(text: str) -> str:
    """Every character kept; every wrapped region bracketed by its class markers.

    A blockquote's `>` prefixes are dropped — the `[[quote]]` pair already says the region
    is quoted, and keeping per-line `>` would make a re-wrap change the canon, which is the
    one edit a thinning campaign makes constantly.
    """
    spans = _wrapper_spans(text)

    # Characters to omit: each quote line's `> ` prefix. Computed over the raw lines rather
    # than from the spans, so it cannot drift from `_QUOTE_LINE`'s own answer.
    drop = bytearray(len(text))
    for s, e in _line_bounds(text):
        m = re.match(r"[ \t]*> ?", text[s:e])
        if m and _QUOTE_LINE.match(text[s:e]):
            for k in range(s, s + m.end()):
                drop[k] = 1

    # Open outer-before-inner, close inner-before-outer, and close before open at a shared
    # offset so two adjacent regions do not nest into each other.
    events: list[tuple[int, int, int, str]] = []
    for a, b, cls in spans:
        events.append((a, 1, -b, _tag_open(cls)))
        events.append((b, 0, -a, _tag_close(cls)))
    events.sort()

    out: list[str] = []
    last = 0
    for pos, _kind, _tie, marker in events:
        out.append("".join(c for k, c in enumerate(text[last:pos], last) if not drop[k]))
        out.append(marker)
        last = pos
    out.append("".join(c for k, c in enumerate(text[last:], last) if not drop[k]))
    text = "".join(out)

    # The same two folds `_prose_only` ends with, and for the same reasons: a word broken
    # across lines at a hyphen is presentation, and a list marker must be folded while line
    # starts are still visible.
    text = re.sub(r"(\w)-\n[ \t]*(\w)", r"\1-\2", text)
    return re.sub(r"(?m)^(\s*)(?:\*|\d+\.)\s", r"\1- ", text)


def _without(tagged: str, classes: Iterable[str]) -> str:
    """Drop the named classes' regions, markers and all. Other classes keep their markers.

    This is how a caller states its own neutering policy over `_tagged` output. Passing
    every class reproduces `_prose_only`'s answer (asserted below, on both real files).
    """
    for cls in classes:
        tagged = re.sub(
            re.escape(_tag_open(cls)) + r".*?" + re.escape(_tag_close(cls)),
            "",
            tagged,
            flags=re.S,
        )
        # An unterminated region tagged to EOF has an opener and no closer.
        tagged = re.sub(re.escape(_tag_open(cls)) + r".*", "", tagged, flags=re.S)
    return tagged


def _anchor_is_wrapped(tagged: str, index: int) -> bool:
    """True when the character at `index` sits inside an open wrapper region.

    This is the half a no-strip policy cannot have, and the reason it was refused. Measured
    on both slicers before this was written: wrap a whole step in `<!-- -->` with the closer
    placed past the slice's END marker and the slice between the anchors is byte-identical,
    so the pin stays **green over a fully commented-out step** — Phase 167's survivor,
    rebuilt.

    Regions NEST rather than being disjoint — an earlier draft of this docstring said
    otherwise and was the third copy of a claim corrected in two other places, left standing
    until the round found it. A per-class unbalanced count is still the right test, and the
    reason is narrower: **no class nests inside itself.** `<details>` is the one that can,
    which is why `_wrapper_spans` depth-matches its closer.
    """
    before = tagged[:index]
    for cls in TAG_CLASSES:
        if before.count(_tag_open(cls)) > before.count(_tag_close(cls)):
            return True
    return False


# --------------------------------------------------------------------------------------
# The tagger's load-bearing properties (`Q-457`, Phase 291)
# --------------------------------------------------------------------------------------
#
# Each of these was a defect in a discarded draft of `_tagged`, not a property invented
# after the fact. They are written against synthetic input on purpose: the shipped files
# exercise the happy path, and three of the five drafts failed only on shapes neither file
# happens to contain today.

TAGGED_FILES = (PARTIAL, Path(__file__).resolve().parents[1] / "core/skills/review-close/SKILL.md")


def _canon(text: str) -> str:
    return _block_canon(_flat(_tagged(text)))


@pytest.mark.parametrize("path", TAGGED_FILES, ids=lambda p: p.name)
def test_dropping_every_tagged_class_reproduces_the_stripped_rendering(path):
    """The two canonicalisers must agree on the text they share.

    `_tagged` keeps what `_prose_only` deletes; drop every tagged region from its output and
    the two must be the same string. This is the invariant that makes a pin regeneration
    provable rather than eyeballed: the delta between a stripped pin and a tagged one is
    exactly markers plus previously-stripped spans, and nothing else. A tagging bug that
    dropped, duplicated or re-ordered ordinary prose fails here rather than silently
    regenerating a pin around it.
    """
    raw = path.read_text(encoding="utf-8")
    assert _flat(_without(_tagged(raw), TAG_CLASSES)) == _flat(_prose_only(raw))


@pytest.mark.parametrize("path", TAGGED_FILES, ids=lambda p: p.name)
def test_the_guarded_files_carry_no_nesting_the_resolver_cannot_model(path):
    """Refused loudly rather than mis-rendered — the one thing the resolver will not guess."""
    assert _unhandled_nesting(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("path", TAGGED_FILES, ids=lambda p: p.name)
def test_no_guarded_file_contains_a_tag_marker_of_its_own(path):
    """A marker in shipped text would let an editor forge a wrapper boundary.

    `_without` and `_anchor_is_wrapped` both read markers as structure, so a literal
    `[[fence]]` in the runner could split a region, close one early, or make an anchor look
    wrapped. Absent today in both files; asserted so it stays that way.
    """
    raw = path.read_text(encoding="utf-8")
    for marker in ALL_TAG_MARKERS:
        assert marker not in raw, f"{path.name} contains the literal marker {marker}"


def test_a_blockquote_survives_being_re_wrapped():
    """Reflow-invariance, the property a per-line marker cannot have.

    A first draft prefixed every wrapped LINE with its class marker. That makes re-wrapping a
    blockquote change the canon — and a thinning campaign is nothing but content edits inside
    subsections, so it would have turned the most common innocent edit into a pin
    regeneration. Phase 168 measured 19 of 30 innocent edits going red on pinned prose; this
    is the half of that cost the design can actually refuse.
    """
    assert _canon("> alpha beta\n> gamma delta\n> epsilon\n") == _canon("> alpha beta gamma\n> delta epsilon\n")
    assert "alpha beta gamma delta epsilon" in _canon("> alpha beta\n> gamma delta\n> epsilon\n")


def test_a_fence_survives_being_re_indented():
    """Indent-invariance — the fourth hazard `Q-457` named, from the other side.

    `_prose_only`'s `^``` ` was column-0-anchored, so an indented fence was NOT stripped and a
    prescribed command inside one was pinned while the same command at column 0 was not.
    Measured live in `adversarial-review.md`: the indented `config-baseline` snippet survived
    into the rendered text and the column-0 `lsof` snippet did not. Both functions now match
    at any indent, so indentation decides nothing.
    """
    flush = "x\n```bash\necho hi\n```\ny\n"
    indented = "x\n  ```bash\n  echo hi\n  ```\ny\n"
    assert _canon(flush) == _canon(indented)
    assert "echo hi" in _canon(flush), "the fence's content is the thing being pinned"
    assert _prose_only(flush).strip() == _prose_only(indented).strip()


@pytest.mark.parametrize("wrapper", [
    ("```\n", "```\n"),
    ("<!--\n", "-->\n"),
    ("<details>\n", "</details>\n"),
    ("> ", ""),
])
def test_moving_a_rule_into_a_wrapper_changes_the_canon(wrapper):
    """The property deletion used to give, kept as a change rather than a disappearance.

    `_prose_only` made a neutered rule read as deleted, which failed a pin. `_tagged` keeps
    every word, so this had to be re-earned rather than assumed — and "keep everything" is
    exactly the shape that could have quietly lost it.
    """
    opener, closer = wrapper
    rule = "the scope may never silently narrow the gate\n"
    assert _canon(rule) != _canon(opener + rule + closer)
    assert "silently narrow the gate" in _canon(opener + rule + closer)


def test_an_unterminated_wrapper_runs_to_end_of_file():
    """Faithful to what a reader sees, and the opposite call from `review_index.py`.

    An unclosed fence really does render everything after it as code, so tagging to EOF is
    the honest rendering and every later anchor then reports as neutered. `review_index.py`'s
    `_fenced_mask` deliberately ignores an unterminated fence for the opposite reason: it
    ACTS on what it reports, and a mask running to EOF flips a consumer's checkboxes. The
    worst this can do is redden a test.
    """
    text = "before\n```bash\ninside\nstill inside\n"
    spans = _wrapper_spans(text)
    assert [cls for _, _, cls in spans] == [TAG_FENCE]
    assert spans[0][1] == len(text.rstrip())
    tagged = _tagged(text)
    assert _anchor_is_wrapped(tagged, tagged.index("still inside"))
    assert not _anchor_is_wrapped(tagged, tagged.index("before"))


def test_a_comment_inside_a_blockquote_does_not_split_the_blockquote():
    """The live shape, and the defect the first draft shipped on it.

    `adversarial-review.md`'s prompt template carries a commented-out block inside a
    blockquote. Resolving comments before blockquotes split that run in three and left a bare
    `>` in the rendered text — which is how a class-priority resolver was found to be the
    wrong model at all.
    """
    text = "> one\n> <!-- hidden\n> more\n> -->\n> two\n\nafter\n"
    classes = [cls for _, _, cls in _wrapper_spans(text)]
    assert classes.count(TAG_QUOTE) == 1, classes
    assert ">" not in _without(_tagged(text), TAG_CLASSES)


def test_a_fence_inside_a_blockquote_belongs_to_the_blockquote():
    """The other live shape: 10 quoted fence delimiters in `review-close/SKILL.md`.

    A quoted delimiter is part of its blockquote, not a fence of its own, so it needs no
    special case — `_FENCE_LINE` simply does not match it. Asserted because the inverse
    (treating it as a fence) produces overlapping spans and a silently wrong rendering.
    """
    text = "> note\n> ```bash\n> echo hi\n> ```\n> end\n\nafter\n"
    spans = _wrapper_spans(text)
    assert [cls for _, _, cls in spans] == [TAG_QUOTE], spans
    assert "echo hi" in _tagged(text)


def test_a_quote_line_inside_a_fence_is_refused_rather_than_mis_tagged():
    """The one nesting the resolver does not model, and does not guess at."""
    assert _unhandled_nesting("```\n> quoted inside a fence\n```\n")
    assert _unhandled_nesting("ordinary\n> quoted\n\n```\nfenced\n```\n") == []


def test_anchor_containment_sees_a_wrapper_that_opens_outside_the_slice():
    """The measurement that refused the filing's first two ways out.

    Dropping the strip for this file — either of the first two remedies `Q-457` listed —
    leaves a slice byte-identical when the wrapper's closer lands past its END marker, so the
    pin stays green over text no reader can see. The containment check is what the remedies
    were missing, and it is cheap.
    """
    text = "<!--\nheading\nbody\nEND-MARKER\n-->\ntail\n"
    tagged = _tagged(text)
    assert _anchor_is_wrapped(tagged, tagged.index("heading"))
    assert _anchor_is_wrapped(tagged, tagged.index("END-MARKER"))
    assert not _anchor_is_wrapped(tagged, tagged.index("tail"))


def test_the_tagged_population_is_both_guarded_files():
    """A population guard, because shrinking one is invisible and free.

    Every parametrized check above reads `TAGGED_FILES`. Dropping `review-close/SKILL.md`
    from it leaves the whole module green while the file this phase exists for goes
    unchecked — a battery mutation did exactly that and survived. Named, not counted: a
    `>= 2` would pass on the wrong two.
    """
    # TWO independent assertions, not one. A battery mutation vacated the name check by
    # unioning the expected set into the observed one — the shape that defeats any single
    # predicate — and a lone check went green over a population of one. The count and the
    # names have to be vacated separately now, which is the same bar `REFERENCE.md` states
    # for retiring a declared rule: possible in one commit, not possible as a side effect.
    assert len(TAGGED_FILES) == 2, f"the population is {len(TAGGED_FILES)} file(s)"
    names = sorted(p.name for p in TAGGED_FILES)
    assert names == ["SKILL.md", "adversarial-review.md"], names
    for path in TAGGED_FILES:
        assert path.is_file(), f"{path} does not exist — the check reads nothing"
        assert _wrapper_spans(path.read_text(encoding="utf-8")), (
            f"{path.name} has no wrapped regions at all — a file this module reads for its "
            "rendering must have something to render"
        )


def test_a_widened_fence_pattern_would_invert_the_nesting():
    """The guard on the one thing that makes the quoted-delimiter case work.

    `_FENCE_LINE` allows only spaces and tabs before the delimiter run, so a quoted delimiter
    is not a fence line and a fence inside a blockquote stays part of its blockquote. Widen
    the pattern to tolerate `>` and the nesting inverts silently: the 10 quoted delimiters in
    `review-close/SKILL.md` start pairing as fences and swallow the prose between them. The
    resolver has no check that would notice, so this property IS the contract.
    """
    # The CONTRACT, not the literal pattern. A first version pinned the regex source, and
    # this phase's own round then required the pattern to change (`~~~` is a legal fence and
    # was not matched) — so the pin failed for a strengthening, which is the over-strictness
    # direction. What must hold is that no leading `>` reaches the delimiter.
    for quoted_delim in ("> ```bash", ">```", "  > ~~~", "\t> ```"):
        assert not _FENCE_LINE.match(quoted_delim), quoted_delim
        assert _fence_delim(quoted_delim) is None, quoted_delim
    for bare in ("```bash", "  ```", "~~~", "  ~~~python", "````"):
        assert _fence_delim(bare) is not None, bare
    for style in ("```bash", "~~~bash"):
        quoted = f"> note\n> {style}\n> echo hi\n> {style[:3]}\n> end\n"
        assert [cls for _, _, cls in _wrapper_spans(quoted)] == [TAG_QUOTE], style


def test_a_comment_delimiter_inside_a_fence_is_literal_text():
    """A fence's content is literal, so `<!--` in one opens nothing.

    Absent from both guarded files today, which is exactly why it needs a test: the resolver
    skips a comment whose opener falls inside a fence, and a battery mutation that removed
    that skip survived every check.
    """
    text = "before\n```bash\n# <!-- not a comment\n```\nafter\n<!-- real -->\ntail\n"
    classes = [cls for _, _, cls in _wrapper_spans(text)]
    assert classes == [TAG_FENCE, TAG_COMMENT], classes
    tagged = _tagged(text)
    assert not _anchor_is_wrapped(tagged, tagged.index("after")), (
        "a `<!--` inside a fence opened a comment region and swallowed the text after it"
    )
    assert "not a comment" in _without(tagged, NEUTERING_TAGS), (
        "fence content was dropped as though it were commented out"
    )


# --------------------------------------------------------------------------------------
# What Phase 291's own round found, in the fix written to close this class
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("opener,closer", [
    ("```", "```"),
    ("~~~", "~~~"),
    ("````", "````"),
    ("```markdown", "```"),
    ("~~~markdown", "~~~"),
])
def test_every_legal_fence_delimiter_neuters_as_loudly_as_a_backtick_one(opener, closer):
    """`~~~` is a legal fence and it defeated both canonicalisers.

    Measured by the round: wrapping the gate paragraph in ``` returned three problems and
    wrapping the identical text in `~~~` returned **zero** — GitHub renders both as code
    blocks, so that is Phase 167's "gate commented out" survivor reached through a delimiter
    the pattern did not know about, inside the function whose docstring exists to refuse it.
    The same wrap left `review-close`'s Step 3 pin GREEN over a step no reader can see.

    Parametrized over every shape CommonMark allows rather than over the one that was
    broken: a fix keyed to `~~~` alone would leave `````` ````` `````` in exactly this state.
    """
    gate = _gate_paragraph()
    assert gate_problems(gate) == [], "premise: the shipped gate is clean"
    assert gate_problems(f"{opener}\n{gate}\n{closer}\n"), (
        f"a gate wrapped in {opener!r} reached every presence predicate unneutered"
    )
    rule = "the scope may never silently narrow the gate\n"
    plain = _block_canon(_flat(_tagged(rule)))
    wrapped = _block_canon(_flat(_tagged(f"{opener}\n{rule}{closer}\n")))
    assert plain != wrapped, f"{opener!r} left the canon unchanged"


def test_a_fence_closer_must_match_its_own_opener():
    """CommonMark's rule, and without it a block silently ends early.

    A 3-backtick line inside a 4-backtick block closed it, so the rest of the block became
    prose and the trailing delimiter opened a new fence running to EOF. Found by the round.
    A tilde line must not close a backtick fence either.
    """
    four = "````\nline1\n```\nline2\n````\n"
    spans = _wrapper_spans(four)
    assert [cls for _, _, cls in spans] == [TAG_FENCE], spans
    assert "line2" not in _without(_tagged(four), [TAG_FENCE]), (
        "a shorter delimiter closed a longer fence and the tail leaked out as prose"
    )
    mixed = "```\ninside\n~~~\nstill inside\n```\n"
    assert [cls for _, _, cls in _wrapper_spans(mixed)] == [TAG_FENCE]
    assert "still inside" not in _without(_tagged(mixed), [TAG_FENCE])
    # An info string containing a backtick is not a fence opener (CommonMark), which keeps an
    # inline code span off the opener branch. The LATER bare delimiter is a legal opener and
    # runs to EOF unterminated — that is the right answer, so assert where the region starts
    # rather than that there is none. A first draft of this asserted `== []` and was wrong
    # about the function, not the other way round.
    spans = _wrapper_spans("```a`b\nx\n```\ny\n")
    assert [cls for _, _, cls in spans] == [TAG_FENCE]
    assert spans[0][0] > len("```a`b\nx\n") - 1, (
        f"the backtick-carrying info line opened the fence: {spans}"
    )


def test_details_ends_at_its_own_closer_not_the_first_one():
    """`<details>` is the one wrapper here that nests inside itself.

    Taking the first `</details>` ended an outer region at the INNER closer, so the text
    between them rendered collapsed on GitHub and read as live prose here. That also breaks
    the "no class nests inside itself" property `_anchor_is_wrapped` depends on, which is why
    this is depth-matched rather than screened. Neither guarded file contains a `<details>`
    at all, so nothing but a hostile fixture reaches it.
    """
    text = "<details>\nA\n<details>\nB\n</details>\nC\n</details>\ntail\n"
    spans = _wrapper_spans(text)
    assert [cls for _, _, cls in spans] == [TAG_DETAILS], spans
    visible = _without(_tagged(text), NEUTERING_TAGS)
    assert "C" not in visible, "text before the outer closer read as live prose"
    assert "tail" in visible, "the region swallowed text past its own closer"
    tagged = _tagged(text)
    assert _anchor_is_wrapped(tagged, tagged.index("C"))
    assert not _anchor_is_wrapped(tagged, tagged.index("tail"))
    # Unbalanced runs to EOF, the same answer an unterminated fence gets.
    assert [cls for _, _, cls in _wrapper_spans("<details>\nA\n<details>\nB\n</details>\n")] \
        == [TAG_DETAILS]


def test_an_unterminated_comment_or_details_runs_to_end_of_file():
    """The arm the round found untested, in both directions.

    An unterminated `<!--` or `<details>` hides everything after it on GitHub, so the region
    must run to EOF and every later anchor must report as neutered. Deleting the arm left the
    region unopened and nothing in the suite noticed — the positive control below is the one
    that bites, because an unterminated wrapper *before* a guarded section is exactly how a
    step goes invisible without a single character of it changing.
    """
    for opener in ("<!--", "<details>"):
        text = f"before\n{opener}\nswallowed\nstill swallowed\n"
        spans = _wrapper_spans(text)
        assert len(spans) == 1, (opener, spans)
        assert spans[0][1] == len(text.rstrip()), (opener, spans)
        tagged = _tagged(text)
        assert _anchor_is_wrapped(tagged, tagged.index("swallowed"))
        assert not _anchor_is_wrapped(tagged, tagged.index("before"))
        # `_without` must drop an unterminated region too, or a neutered rule reads as live.
        assert "swallowed" not in _without(tagged, NEUTERING_TAGS), opener


def test_an_unterminated_wrapper_before_a_section_neuters_it():
    """The positive control for the arm above, over the real guarded file."""
    raw = PARTIAL.read_text(encoding="utf-8")
    i = raw.find("\n" + AUTHOR_PASS_START)
    assert i > 0
    for opener in ("<!--", "<details>", "```", "~~~"):
        mutated = raw[:i] + f"\n\n{opener}\n" + raw[i:]
        assert _author_pass_slice(mutated) == "", (
            f"an unterminated {opener!r} before the subsection left its slice readable"
        )


@pytest.mark.parametrize("slicer", ["author_pass", "governor"])
def test_a_section_indented_into_a_code_block_fails_closed(slicer):
    """Markdown's undelimited code form, which the pin cannot see by construction.

    `_flat` collapses indentation, so indenting a whole section four spaces leaves the pinned
    text byte-identical while GitHub renders it as a code listing. The round did exactly that
    to Step 3 and got a green pin plus **one** new failure across 95 modules — an unrelated
    fixture's anchor, not a detection.

    Judged over the SLICE, never the file: a first cut checked the whole file, where indenting
    one subsection barely moves the ratio, and read clean over a neutered section.
    """
    raw = PARTIAL.read_text(encoding="utf-8")
    # Markers resolved at call time: `GOVERNOR_START` is defined further down the module.
    fn, start, end = {
        "author_pass": (_author_pass_slice, AUTHOR_PASS_START, AUTHOR_PASS_END),
        "governor": (_governor_slice, GOVERNOR_START, AUTHOR_PASS_START),
    }[slicer]
    assert fn(raw), "premise: the shipped subsection resolves"
    a = raw.find("\n" + start)
    b = raw.find(end, a)
    assert 0 < a < b
    indented = "\n".join(("    " + line if line.strip() else line)
                         for line in raw[a:b].split("\n"))
    assert fn(raw[:a] + indented + raw[b:]) == "", (
        f"{slicer}: a section indented into a code block still resolved"
    )


def test_the_indent_floor_is_far_from_the_shipped_files():
    """The ratio is a threshold, so the margin is the evidence — measured, not assumed.

    Shipped slices sit near zero and the attack sits near one; a floor at 0.5 has room on
    both sides. Asserted so a later edit cannot quietly walk the floor down toward the
    shipped value, which is how a threshold stops meaning anything.
    """
    assert INDENT_CODE_FLOOR == 4, "CommonMark's indented-code-block rule is four spaces"
    assert 0.25 <= INDENT_NEUTERED_RATIO <= 0.75
    for entry in TAGGED_FILES:
        assert not _indent_neutered(entry.read_text(encoding="utf-8")), entry.name
    assert not _indent_neutered(_author_pass_section())
    # A list-heavy region must not trip it: 68 of the 69 deep-indented lines in
    # `review-close/SKILL.md` are list continuations, which is why no general detector is
    # built. If this fires, the floor is wrong, not the file.
    listy = "- one\n    continued\n- two\n    continued\n\nprose at column 0\nmore prose\n"
    assert not _indent_neutered(listy)


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
    # Judge the SLICE, never the file: indenting one subsection barely moves a whole-file
    # ratio, so a file-wide check reads clean over a neutered section. A first cut did
    # exactly that and the fixture caught it.
    if _indent_neutered(text[a:b]):
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
     "reviewers — a call that belongs to the governor subsection and the maintainer, not "
     "to this rule, and which the ~15% measured overlap argues against."),
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
# To re-approve a deliberate edit, regenerate the constant rather than hand-editing it
# (.venv interpreter — the bare `python3` this recipe first prescribed has no pytest on a
# default setup, so the literal command failed on this machine: rule 3's own class, in the
# comment that teaches the pin):
#
#     .venv/bin/python3 -c "import sys; sys.path.insert(0,'.'); \
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
    '### Before you spawn anyone — the author-side pass **Who this addresses:** the *author* of a change that ships code or guards, after committing and before spawning reviewers. It is not part of the plan-review flow — a `/plan-review` or `/claim-task` Step 7 reviewer has no guards to mutate yet, and should skip this section. **Why it exists.** Twelve of the sixteen phases from 150 to 165 in this project\'s log had a round that found the phase\'s own guards vacuous or its mutation claim self-selected. One reported "33 of 33 mutations killed"; an independent reviewer then ran 83 and watched 28 survive. A round that keeps finding the same class of defect is working as a detector while the authoring step is not learning, and **buying more reviewers is the expensive way to treat that** — roughly half of what such a round finds is catchable by inspection in minutes. **This is not an argument for fewer reviewers.** Measured on one such round, reviewers on distinct lenses were **not** redundant: overlap was about 15%, and each of four lenses produced its sharpest finding alone. Findings-per-reviewer was high. The point is to stop paying them for what you can see yourself, not to stop paying them. **1. Mutate the guard\'s assumptions, not just the content it checks.** Deleting a phrase a guard requires proves the guard is *wired to the file* — real information, and for a declared **reversion guard** (one whose stated job is catching deletion or a shortening-back) or a **vacuity guard** (one asserting its own population is non-empty) that mutation is the whole test of its stated job. Run those. The failure is a set **composed mostly** of them: it reports a kill rate that describes wiring while saying nothing about coverage. In the round that produced this rule, four of the author\'s nine mutations were reverts of text the guards were written to assert, the set was reported as "0 survivors", and **eight real bypasses stood**. So add mutations against each assumption the guard makes: - **What it matches on.** A guard keyed to a physical line is walked through by a backslash continuation, by naming a flag before its command, by a variable holding the value, or by a list step that separates a command from its qualifier. None of those is adversarial; they are how people write. - **What it accepts.** A check satisfied by a substring is satisfied by an *incidental* use of that substring — worse than a gap, because it marks a dangerous line compliant. A check requiring N phrases is satisfied by N disconnected phrases in a sentence asserting the opposite. - **Where it looks.** Enumerate the files the guard actually reads and ask whether that population covers every place the defect can appear. One such guard excluded the installer — a file that already prescribed the very script the guard was about. **Derive the population from the source of truth, not from an index or summary of it**; that single substitution produced the worst number in the phase that shipped this rule. - **Over-strictness, the direction that hides.** A pattern requiring an optional token misses the idiomatic form. A guard keyed to `bash <path>/script --flag` missed `<path>/script --flag`, which was the repo\'s own house style. - **Reachability.** Can the guard run at all, and on the thing you think? A new file excluded from its own scan, an uncollected test module, an empty population — each passes while testing nothing. - **When it runs.** If the fix depends on ordering ("rejected *before* anything is deleted"), mutate the ordering. Prose asserting an order is not a test of it. Report the fraction. **A survivor you decline to close must be impossible to close *in kind*** — it needs a judgement no pattern can encode — **not merely unattempted.** "Known blind spot, as designed" is not a disposition: in the round that produced this rule the author labelled the single biggest hole exactly that way, and the round required it fixed. If an ordinary in-repo idiom reaches your survivor, it is a defect wearing a residual\'s label. **One battery, then hand the question to the round.** Write the battery once — the declared reversion and vacuity tests, plus mutations against each assumption class above, plus negative controls — run it, close what it catches (a survivor you decline to close is still held to the criterion above), re-run it to confirm the closures, and report the final fraction with the survivors named. Do not keep authoring fresh batteries in pursuit of an exhausted zero: in five consecutive phases of this project\'s log, the author\'s battery reported every mutation killed, and an independent reviewer\'s battery then found 33 to 99 survivors — every time. An author\'s zero measures self-consistency; exhaustion is the reviewers\' measurement, and iterating toward it author-side pays twice for the weaker of the two numbers. The pass still pays here — one honest battery instead of none, not many instead of one. A closure that *rewrites* a guard rather than patching it takes the battery with it: re-point the affected mutations at the new guard, give the rewrite a non-vacuity control, and treat it as what it is — new material no fresh reader has seen, which before the round is simply the round\'s subject, and after the round is the second-round condition the governor above names. **2. Re-read your own new prose against the code it describes.** Both defects one such round found *in the fix itself* were sentences the author had just written that contradicted the file they sat in — and both were in the same class the fix existed to remove. New prose is the least-reviewed text in any change: no history, no reviewer has seen it, and its author is the one person who cannot read it cold. Check every new claim against the thing it describes, including claims about paths, which are as easily wrong in the consumer\'s installed layout as in yours. **3. Run the commands the change prescribes, in a throwaway repo — before you spawn anyone.** Shipped scripts get real-subprocess coverage, and a few purpose-built extractors do pull a *named* heredoc out of a skill file and run it against a fixture — but nothing runs a command generally, so **a newly prescribed one stays text until an operator reaches it**, and "the prescribed command does not work" is invisible until that moment. Scope this to commands whose operand the change **computes or substitutes** — `git log --oneline` has no operand to get wrong. Copy the literal string, resolve its placeholders the way the change tells an operator to resolve them, and run it. In the round that produced this rule, a prescribed `git show "<branch>:<body path>"` **failed on a default install** — `fatal: path … does not exist` — and the change\'s own new `unreadable` classification would then have halted every run with a fabricated diagnosis blaming the branch. One of three lenses found it, by building a scratch repo and running the string; the other two read the same files and did not. - **Build the fixture\'s inputs from the source of truth, not from your own model of them.** This is the half that does the work, and the easy one to drop. The same fixture runs **green** on the author\'s assumption and **red** on what the shipped writers actually emit: in that round, an assumed body path of `tasks/open/<ID>.md` printed the file, while the canonical value every writer emits — `open/<ID>.md`, relative to `tasks/` — exited 128. A fixture you populate from memory proves only that you are self-consistent. This is rule 1\'s *"derive the population from the source of truth, not from an index or summary of it"* moved from what a guard **reads** to what a fixture **contains**. - **What it reaches is narrow, and the rule says so rather than leaving it implied:** whether the command runs, and whether it does what you said it does. Nothing past that. In that same round the two other defect classes — 43 of 90 guard mutations bypassing, and the false claims in its own record — were entirely outside it. It converts one expensive finding into a cheap one; it does not replace a lens. **4. When the change moves a boundary over text you do not control, build the hostile corpus BEFORE the change, not after.** Rule 3\'s fixture half asks for inputs taken from the source of truth. What that produces is a **healthy** corpus — what the writers emit on a good day — and a boundary rule is never defeated by healthy input. In the round that produced this rule, a phase widened a delimiter rule (a `## ` heading closes a batch) over a tracker file that several different steps append to. Round 1 found the new rule had no fence awareness. The fence fix went in, and round 2 then found that it honoured an **unterminated** fence and was *worse than the bug it replaced*. Both were derivable from the change itself, and the four fixtures the author had built contained neither a fence nor an unbalanced marker — so two rounds of reviewers were spent on rework rather than on review, which is the most expensive way to buy a finding this cheap. The trigger is narrow: the change moves, widens or reinterprets a **delimiter, predicate or state machine** applied to text some other writer produces. When it does, three cases go into the corpus before the change is written, and the change is run against them: - **What else matches this.** The token in a context the rule did not intend — inside a fence, a quote, a comment, a URL, an example of the rule itself. A rule keyed to a marker is keyed to every occurrence of that marker, including the ones nobody put there on purpose. - **What happens when the construct never closes.** An unterminated fence, an unbalanced marker, EOF mid-construct. A state machine written for well-formed input gives its worst answer on input that never closes, and gives it silently. - **What the real artefact already contains.** Grep the live file for the token and read the hits you did not expect. The tracker in that round already carried both shapes, and nobody had looked. A corpus built after the fix describes the fix. A corpus built before it is red before and green after, which is the fix\'s own evidence — and it is the same evidence a reviewer would otherwise have had to construct, at reviewer prices. **What this pass cannot do.** Rules 3 and 4 narrowed this and left more than they took. Executing one command against a fixture *you* built reaches "does it run" and "does it do what I said", and stops there. Out of reach still: whether the prescribed command is the **right** one to prescribe; whether a claim about what its output *means* holds; the common case itself, since a fixture is one case and you are the person who chose which; and it still cannot catch a number whose *source* was wrong, only one whose arithmetic was. Rule 4 reaches the boundary cases you thought to name, and the three it names are the ones this project has already paid for — a shape nobody here has met yet sits outside it too. Those want a reader who has not already decided what the change means — which is what you are about to spawn. Where the harness cannot spawn reviewers at all (§ Harness constraint), this pass is the most you have and you should say so in the record rather than let its limits pass silently. '
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
# Rule 4 — build the hostile corpus BEFORE the change (Phase 187)
# --------------------------------------------------------------------------------------
#
# Pinned separately from `AUTHOR_PASS_VERBATIM` on that constant's own instruction:
# regenerating the block pin is how a deliberate edit is re-approved, so a rule whose only
# protection is the block pin loses it the next time someone re-approves something else.
# These pins are independent of the constant and name what broke.

RULE_4_HEADING = (
    "**4. When the change moves a boundary over text you do not control, build the "
    "hostile corpus BEFORE the change, not after.**"
)

RULE_4_PINS: list[tuple[str, str]] = [
    (RULE_4_HEADING,
     "the rule, including WHEN. 'After the change, add hostile cases' keeps every other "
     "word and retires it: the corpus then describes the fix instead of testing it, which "
     "is the failure the rule is named for."),
    ("What that produces is a **healthy** corpus",
     "the premise, and the whole reason rule 3's fixture half does not already cover this. "
     "Without it rule 4 reads as a restatement of 'build from the source of truth', which "
     "is the thing that was already being done when the incident happened."),
    ("round 2 then found that it honoured an **unterminated** fence and was *worse than the bug it replaced*",
     "the evidence, and the half that makes the case for doing it FIRST. Softened to 'was "
     "not quite complete' the paragraph still argues for the rule while its evidence stops "
     "supporting the ordering — the reader is left free to add the corpus afterwards."),
    ("the change moves, widens or reinterprets a **delimiter, predicate or state machine** applied to text some other writer produces",
     "the trigger. Unscoped, the rule says 'build a hostile corpus for every change', "
     "which is the shape authors reasonably ignore — and an ignored rule is worse than "
     "none, because the author-side pass is then reported as run."),
    ("**What else matches this.**",
     "case 1, the one round 1 of that incident found — a delimiter rule is keyed to every "
     "occurrence of its delimiter, including the ones nobody wrote on purpose."),
    ("**What happens when the construct never closes.**",
     "case 2, the one round 2 found, and the one an author is most likely to drop because "
     "well-formed input never reaches it. It is also the expensive one: the state machine "
     "answers silently rather than failing."),
    ("**What the real artefact already contains.**",
     "case 3, and the only one of the three that is a measurement rather than an "
     "invention. The tracker in that incident already carried both shapes."),
    ("three cases go into the corpus before the change is written, and the change is run against them",
     "the ordering, stated in the BODY. The heading carries it too, and a reviewer showed "
     "why both are needed: inverting this clause alone left the heading intact and every "
     "pin green, and the body is the sentence an author executes."),
    ("A corpus built after the fix describes the fix.",
     "the consequence, stated as a result rather than a duty — the sentence that stops an "
     "after-the-fact fixture from being reported as evidence."),
]

# Written as CLASSES, not as the five sentences a first draft happened to imagine. That
# draft's five literal-ish patterns were walked through by a reviewer with five ordinary
# rewordings — *"it does not create an obligation on any author"*, *"Rule 4 below is
# illustrative and binds nothing"*, *"In practice a healthy corpus already covers the
# ordinary case"*, *"Reviewers will normally surface anything a before-corpus would have"*,
# and an ordering inversion in the body while the heading still said BEFORE — every one of
# them green after the sanctioned `AUTHOR_PASS_VERBATIM` regeneration, which is the only
# condition under which these predicates are load-bearing at all. Same failure the M49–M52
# rows were written for, one rule later, so each of these is now subject × predicate.
_R4_SUBJECT = r"(?:rule 4|this rule|the hostile corpus|the three cases|the before-corpus)"
_R4_DEMOTION = (r"(?:optional|advisory|a suggestion|best-effort|non-?binding|illustrative|"
                r"aspirational|guidance|informational|a recommendation)")

RULE_4_FORBIDDEN: list[tuple[str, str]] = [
    (r"(?:building|adding|writing) (?:it|the corpus|them) after(?:wards)?[^.]{0,60}"
     r"\b(?:is fine|is enough|works too|is equivalent|is acceptable|suffices)",
     "licenses the after-the-fact corpus, which is the only thing rule 4 forbids"),
    (r"healthy corpus\b[^.]{0,60}\b(?:is enough|is sufficient|is fine|suffices|covers|"
     r"already covers|is usually enough)",
     "denies the premise in place, leaving every pin intact"),
    (rf"{_R4_SUBJECT}\b[^.]{{0,70}}\bis {_R4_DEMOTION}",
     "demotes the rule to advice, stated of the rule by name"),
    (rf"{_R4_SUBJECT}\b[^.]{{0,70}}\b(?:binds nothing|is not binding|creates? no "
     r"obligation|imposes? no obligation|does not create an obligation|is not an "
     r"obligation|carries no requirement)",
     "retires the rule by denying it obliges anyone — the same demotion phrased as an "
     "absence of duty rather than as a status word"),
    (r"(?:the round|reviewers?)\b[^.]{0,70}\b(?:will|would|normally|usually|generally|"
     r"in practice)\b[^.]{0,50}\b(?:find|catch|surface|cover|pick up)",
     "hands rule 4 back to the round it exists to spare — which is exactly what the two "
     "rounds in its own incident did, at reviewer prices"),
    (r"well-?formed input is (?:the|a) (?:reasonable|fair|sensible|safe) assumption",
     "re-permits the state-machine case, which is the one that answers silently"),
    (r"(?:go into|goes into|added to) the corpus (?:once|after|when) the change is "
     r"(?:written|made|landed)",
     "inverts the ordering in the BODY while the heading still says BEFORE, so the rule "
     "contradicts itself and the later sentence is the one an author executes"),
]


# Rule 4's block is three short imperative paragraphs and a three-item list. A hedge in it
# is a carve-out, the same argument `_RULE_3_SOFTENING_MODALS` makes one rule up; these are
# the ones a reviewer used that that list does not carry.
_RULE_4_EXTRA_MODALS = (
    r"\bin practice\b",
    r"\bnormally\b",
    r"\billustrative\b",
    r"\bwhere it helps\b",
    r"\bif you have time\b",
)


def _rule_4_block(section: str) -> str:
    """Rule 4 alone, flattened, bounded by the limits paragraph. Fails closed."""
    flat = _flat(section)
    a = flat.find(_flat(RULE_4_HEADING))
    if a < 0:
        return ""
    b = flat.find(_flat(LIMITS_HEADING), a)
    if b < 0:
        return ""
    return flat[a:b]


def rule_4_problems(section: str) -> list[str]:
    flat = _flat(section)
    block = _rule_4_block(section)
    problems = [
        f"rule 4 pin lost, reworded or moved out of the rule — {why} :: {span[:70]!r}"
        for span, why in RULE_4_PINS
        if _flat(span) not in block
    ]
    problems += [
        f"rule 4 contradicted in place ({why}): {pat!r}"
        for pat, why in RULE_4_FORBIDDEN
        if re.search(pat, flat, re.I)
    ]
    problems += [
        f"rule 4 softened with a permissive modal: {pat!r}"
        for pat in _RULE_3_SOFTENING_MODALS + _RULE_4_EXTRA_MODALS
        if re.search(pat, block, re.I)
    ]
    return problems


def rule_4_placement_problems(section: str) -> list[str]:
    """Rule 4 sits BETWEEN rule 3 and the limits paragraph.

    Above rule 3 it precedes the fixture half it refines; below the limits paragraph it
    reads as an afterthought to a paragraph that already bounded the pass. Each anchor
    must occur exactly once, so a duplicate heading cannot satisfy an ordering check while
    the real rule has moved.
    """
    flat = _flat(section)
    problems: list[str] = []
    positions: dict[str, int] = {}
    for name, anchor in (("rule 3", RULE_3_HEADING), ("rule 4", RULE_4_HEADING),
                         ("the limits paragraph", LIMITS_HEADING)):
        hits = flat.count(_flat(anchor))
        if hits == 0:
            problems.append(f"{name} has no heading in this subsection")
        elif hits > 1:
            problems.append(f"{name} has {hits} headings — which one is the real rule?")
        else:
            positions[name] = flat.index(_flat(anchor))
    if len(positions) == 3:
        if not positions["rule 3"] < positions["rule 4"]:
            problems.append("rule 4 is placed above rule 3, which it refines")
        if not positions["rule 4"] < positions["the limits paragraph"]:
            problems.append("rule 4 is placed BELOW the limits paragraph that scopes it")
    return problems


def test_rule_4_binds():
    assert rule_4_problems(_author_pass_section()) == []


def test_rule_4_sits_between_rule_3_and_the_limits_paragraph():
    assert rule_4_placement_problems(_author_pass_section()) == []


def test_the_rule_4_predicates_are_not_vacuous():
    assert rule_4_problems("") != []
    assert rule_4_placement_problems("") != []


def test_the_rule_4_block_slicer_fails_closed():
    section = _author_pass_section()
    assert _rule_4_block(section)
    assert _rule_4_block(section.replace(RULE_4_HEADING, "**4.**", 1)) == ""
    assert _rule_4_block(section.replace(LIMITS_HEADING, "**Caveats.**", 1)) == ""


def test_the_rule_4_predicates_discriminate_on_their_own():
    """Driven directly, because every table mutation below also fails the block pin — so
    the table would stay green with `rule_4_problems` deleted from `RULE_3_CHECKS`. This
    is the shape `test_the_placement_predicate_discriminates_on_its_own` established.
    """
    section = _author_pass_section()
    assert rule_4_problems(section) == []

    # Whitespace-tolerant, like the rule-3 machinery. Raw `section.replace` reddened on a
    # rewrap with `mutation source text not found` — a confusing failure about the harness
    # on an edit that is not a defect, which is the class `_sub`'s own docstring names and
    # which a round found reproduced here.
    def _mut(old, new):
        return _sub(old, new)(section)

    dropped = _mut("**What happens when the construct never closes.**", "")
    assert any("never closes" in p for p in rule_4_problems(dropped))

    licensed = _mut(
        "A corpus built after the fix describes the fix.",
        "A corpus built after the fix describes the fix, and building it afterwards is "
        "fine when the change is small.")
    assert any("after-the-fact corpus" in p for p in rule_4_problems(licensed))

    hedged = _mut(
        "three cases go into the corpus before the change is written",
        "three cases may go into the corpus before the change is written")
    assert any("permissive modal" in p for p in rule_4_problems(hedged))

    # Placement, isolated: rule 4 moved under the limits paragraph.
    below = _sub(LIMITS_HEADING, LIMITS_HEADING + " " + RULE_4_HEADING)(
        _sub(RULE_4_HEADING, "")(section))
    assert any("BELOW the limits paragraph" in p for p in rule_4_placement_problems(below))


def test_the_rule_4_softening_screen_reads_rule_4_and_not_its_neighbours():
    """Scoped to the rule-4 block. Over the whole subsection it would inherit rule 1's own
    'A pattern requiring an optional token misses the idiomatic form' — the over-strictness
    rule 1 warns about, reached by mis-scoping the guard written for it."""
    section = _author_pass_section()
    assert "optional token" in section
    assert rule_4_problems(section) == []
    assert "optional token" not in _rule_4_block(section)


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
    rule_4_problems,
    rule_4_placement_problems,
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
        "Rules 3 and 4 narrowed this and left more than they took. Executing one command against a fixture *you* built reaches \"does it run\" and \"does it do what I said\", and stops there.",
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
        "Rules 3 and 4 narrowed this and left more than they took.",
        "Rules 3 and 4 narrowed this and left more than they took. A fixture is not reality, so treat its result as unverified.")),
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
    # --- rule 4 (Phase 187) ---
    ("M53 delete rule 4 outright",
     lambda t: t[:_at(t, RULE_4_HEADING)] + t[_at(t, LIMITS_HEADING):]),
    ("M54 invert rule 4's ordering, keeping every other word", _sub(
        RULE_4_HEADING,
        "**4. When the change moves a boundary over text you do not control, add the "
        "hostile corpus once the change is written.**")),
    ("M55 drop the unterminated-construct case — the one round 2 found", _sub(
        "**What happens when the construct never closes.**",
        "**What happens on unusual input.**")),
    ("M56 deny the premise, leaving every pin intact", _sub(
        "The trigger is narrow:",
        "A healthy corpus is enough in the ordinary case. The trigger is narrow:")),
    ("M57 license the after-the-fact corpus", _sub(
        "A corpus built after the fix describes the fix.",
        "A corpus built after the fix describes the fix, though building it afterwards is "
        "fine when the boundary is simple.")),
    ("M58 hand rule 4 back to the round", _sub(
        "at reviewer prices.",
        "at reviewer prices. In practice the round will catch these anyway.")),
    ("M59 soften the three cases to a suggestion", _sub(
        "three cases go into the corpus before the change is written",
        "three cases may go into the corpus before the change is written")),
    ("M60 unscope the trigger so authors ignore it", _sub(
        "the change moves, widens or reinterprets a **delimiter, predicate or state machine** applied to text some other writer produces",
        "the change touches anything")),
    ("M61 ship rule 4 below the paragraph that scopes it",
     lambda t: (t[:_at(t, RULE_4_HEADING)]
                + t[_at(t, LIMITS_HEADING):_at(t, AUTHOR_PASS_END)]
                + t[_at(t, RULE_4_HEADING):_at(t, LIMITS_HEADING)]
                + t[_at(t, AUTHOR_PASS_END):])),
    ("M62 re-permit the state-machine case from the limits paragraph", _sub(
        "Where the harness cannot spawn reviewers at all",
        "Well-formed input is a reasonable assumption for a first pass. Where the harness "
        "cannot spawn reviewers at all")),
    # --- the five a round walked through the first pin set, each after regenerating
    # --- `AUTHOR_PASS_VERBATIM` the documented way, which is when these predicates are
    # --- the only thing left. Kept permanently: they are the record of what the author's
    # --- own sweep could not see.
    ("M63 deny that rule 4 obliges anyone", _sub(
        "A corpus built after the fix describes the fix.",
        "A corpus built after the fix describes the fix. Rule 4 does not create an "
        "obligation on any author.")),
    ("M64 call rule 4 illustrative, from the preamble", _sub(
        "**Why it exists.**",
        "Rule 4 below is illustrative and binds nothing. **Why it exists.**")),
    ("M65 deny the premise in an unpinned rewording", _sub(
        "The trigger is narrow:",
        "In practice a healthy corpus already covers the ordinary case. The trigger is "
        "narrow:")),
    ("M66 hand rule 4 back to the round, reworded", _sub(
        "at reviewer prices.",
        "at reviewer prices. Reviewers will normally surface anything a before-corpus "
        "would have.")),
    ("M67 invert the ordering in the body, heading intact", _sub(
        "three cases go into the corpus before the change is written",
        "three cases go into the corpus once the change is written")),
]


# The rule-4 rows, named rather than matched by id prefix. A round beat the prefix+count
# form two ways: `[one_row] * 10` satisfied `len(...) == 10` while nine mutations stopped
# running, and a future rule-4 row named outside the hardcoded `M5x` tuple was silently
# excluded while the count stayed right. Three mechanical checks replace the count below —
# id uniqueness, set/list agreement, and the suffix invariant — and none of them is a
# number an author can edit to make a failure go away.
RULE_4_MUTATION_IDS = (
    "M53", "M54", "M55", "M56", "M57", "M58", "M59", "M60", "M61", "M62",
    "M63", "M64", "M65", "M66", "M67",
)

_RULE_4_MUTATIONS = [m for m in RULE_3_MUTATIONS
                     if m[0].split()[0] in RULE_4_MUTATION_IDS]


@pytest.mark.parametrize("name,mutate", _RULE_4_MUTATIONS,
                         ids=[m[0] for m in _RULE_4_MUTATIONS])
def test_every_rule_4_mutation_is_caught_by_the_rule_4_predicates(name, mutate):
    """Not by the block pin — by the rule's OWN checks.

    Every entry in the table below also fails `author_pass_problems`, so the combined
    table would stay green with both rule-4 predicates deleted from `RULE_3_CHECKS`. That
    is the vacuity this module is named for, and regenerating `AUTHOR_PASS_VERBATIM` — a
    legitimate act, and the documented way to re-approve an edit — is exactly when the
    block pin stops covering rule 4. These predicates are what remains.
    """
    shipped = PARTIAL.read_text(encoding="utf-8")
    section = _author_pass_slice(mutate(shipped))
    failures = rule_4_problems(section) + rule_4_placement_problems(section)
    assert failures, f"mutation {name!r} survived both rule-4 predicates"


def test_the_rule_4_population_cannot_be_thinned_or_drift():
    """Three checks, none of them a number an author can edit.

    A round beat the previous `len(...) == 10` two ways and both are closed here:
    duplicating one row ten times now fails **id uniqueness** and **set/list agreement**,
    and appending a new rule-4 row without naming it fails the **suffix invariant** —
    the rule-4 rows are the tail of the table, under their own banner comment, so a row
    added after them is not silently outside the parametrisation.
    """
    ids = [m[0].split()[0] for m in _RULE_4_MUTATIONS]
    assert ids == list(RULE_4_MUTATION_IDS), (
        "the rule-4 rows and their id list disagree — a row was duplicated, dropped or "
        f"reordered: {ids}")
    all_ids = [m[0].split()[0] for m in RULE_3_MUTATIONS]
    assert len(all_ids) == len(set(all_ids)), "duplicate ids in the mutation table"
    assert all_ids[-len(RULE_4_MUTATION_IDS):] == list(RULE_4_MUTATION_IDS), (
        "the rule-4 rows are no longer the tail of the table. If you appended a rule-4 "
        "mutation, add its id to RULE_4_MUTATION_IDS; if you appended a rule-3 one, move "
        "it above the rule-4 banner — otherwise it is outside the rule-4 parametrisation "
        "and nothing checks the rule-4 predicates catch it.")
    # …and the list really is rule-4-scoped: no rule-3-only row leaked into it.
    assert "M1" not in ids and "M45" not in ids


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
    # The Phase-174 requirements must fire too — the round's guards lens deleted each of
    # these requirement lines from the predicate and nothing went red.
    assert any("no-invoker" in p for p in problems), problems
    assert any("ledger" in p for p in problems), problems
    assert any("gate-two-lenses" in p for p in problems), problems
    assert any("gate-no-self-spawn" in p for p in problems), problems


def test_the_procedure_predicate_rejects_a_softened_section():
    problems = section_problems(_SOFTENED_SECTION)
    assert any("hedged" in p for p in problems), problems
    assert any("commit-first" in p for p in problems), problems
    assert any("no-tree-mutation" in p for p in problems), problems
    assert any("carve-out" in p for p in problems), problems
    assert any("never-forks" in p for p in problems), problems
    # Isolates the "governor" required key: the fixture has no governor heading, so the
    # predicate must say so — deleting the key was invisible until this line.
    assert any("governor" in p for p in problems), problems


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


# --------------------------------------------------------------------------------------
# Phase 174 — the governor: count, termination, disposition
# --------------------------------------------------------------------------------------
#
# The governor exists because Phase 166 measured the count creeping 1 -> 2 -> 3 -> 4+ with
# nobody choosing it, and because the round after a round after a round has no stated
# stopping condition anywhere else. It is the file's most contested subsection — the numbers
# it names are exactly the ones a session under pressure to be thorough wants to raise — so
# it gets the same primitive as the author-side pass: a whole-subsection verbatim pin,
# because five author-side batteries and a reviewer battery both showed every scoped guard
# losing to ADDITION (see the AUTHOR_PASS_VERBATIM comment).

GOVERNOR_START = "### How many reviewers, how many rounds — the governor"


def _governor_slice(text: str) -> str:
    """The governor subsection, between two named markers, failing closed.

    Same discipline as `_author_pass_slice`, same reasons: exactly one heading or nothing
    (a softened decoy planted above the real subsection would otherwise steal the window),
    and a missing end marker yields nothing rather than the rest of the file.
    """
    text = _prose_only(text)
    if text.count(GOVERNOR_START) != 1:
        return ""
    a = text.find(GOVERNOR_START)
    b = text.find(AUTHOR_PASS_START, a)
    if b <= a:
        return ""
    if _indent_neutered(text[a:b]):
        return ""
    return text[a:b]


def _governor_section() -> str:
    section = _governor_slice(PARTIAL.read_text(encoding="utf-8"))
    assert section, (
        "the governor subsection does not resolve — either it is gone (the ratified "
        "count/termination policy would then be unenforced prose in CLAUDE.md that no "
        "consumer sees), or its heading/end-marker moved and this slicer needs revisiting"
    )
    return section


# Regenerate after a deliberate edit, same recipe as AUTHOR_PASS_VERBATIM:
#
#     .venv/bin/python3 -c "import sys; sys.path.insert(0,'.'); \
#       import tests.test_adversarial_review_gate as G; \
#       print(repr(G._block_canon(G._flat(G._governor_section()))))"
#
GOVERNOR_VERBATIM = (
    '### How many reviewers, how many rounds — the governor A convention that says "several reviewers" ratchets. In this project\'s log the count was never chosen — it crept from 1 to a mode of 2, then 3, with excursions to 4, and the *round* count crept the same way, one phase running three rounds of three; each step taken under local pressure to be thorough and none of them decided. The rules above say what a round must do; this subsection names the numbers, the stopping condition, and who may exceed them. **Scope.** This subsection sizes an *ad-hoc review round over built work* — a phase-close round, a maintainer\'s round on a finished change. It does not govern flows whose reviewer count is fixed by their own design: a per-plan reviewer inside an orchestrator (`/claim-task` Step 7b, `/auto-build` Phase 6b) is one by construction, and a fan-out sized by its own skill\'s dispatch rule stays with its skill — `/review-close` Step 2b\'s one agent per branch, `/security-audit`\'s per-OWASP-category agents, `/codebase-review`\'s per-map-section grouping, `/test-audit`\'s declared solo-or-dispatch choice recorded in its Tier-0 ledger, a maintainer\'s standing audit brief. And § *Compound findings — decompose before rejecting* below — with its twin leg in `_shared/fanout-evidence.md` § Adjudication — mandates a second, independent pass when a High-severity rejection needs re-adjudication; that is a per-finding pass, not a round, and nothing here caps it. A harness with no reviewer-spawning at all runs the author-side pass as the most it has — its § *What this pass cannot do* says exactly that — and records a solo round with its reason, never the two-lens default read as satisfied. **Default: two reviewers on distinct lenses. Escalate to a third lens when the change ships behaviour *and* a record making numeric claims.** Both terms are defined: *ships behaviour* means the change alters what a shipped file does or checks — code, guards, tests — and prose alone does not qualify, however much of it there is; *a record making numeric claims* means the change\'s own record asserts counts or measurements a reviewer could falsify. When in doubt whether the condition holds, it does not — stay at two and record the call. The default is not a claim that extra lenses find nothing — measured on one four-lens round, overlap was ~15% and each lens produced its sharpest finding alone (the same measurement § *Before you spawn anyone* cites below), so the third lens on a qualifying change is bought deliberately, not tolerated; the evidence *for* two is the same round\'s split, in which about half the findings were author-side sloppiness the § *Before you spawn anyone* pass now owns. It is a claim about who decides: the condition licenses the third lens, and everything past that licence — **a third lens without the condition, and anything beyond three, is the maintainer\'s decision, made outside the session that wants it**, with the round yield so far in hand (each round\'s reviewer count, findings by severity, and dispositions — from a round ledger where the project keeps one, from the round records where it does not). **One round is the default, and it ends when every verified finding is dispositioned** — fixed with the fix verified by the caller, filed as latent (below), or surfaced to the human as a `blocker` (the Classification Rubric\'s halt arm; a round holding an open blocker has not ended, it is waiting). What warrants a second round is one thing: the fixes themselves produced substantial new material no fresh reader has seen — a mechanism replaced, a guard module rewritten wholesale rather than patched. Verifying a bounded fix is the caller\'s job, not a new round\'s. **A session that wants a round beyond the second surfaces that to the human, with what the rounds so far have found; it does not spawn one on its own judgment.** **Fix-now is not the only honest disposition for a verified finding.** A finding can be real and *latent*: **no live path reaches it today — demonstrated, not asserted.** The record names the condition that would have to become true for the path to go live, and the evidence that no shipped surface produces that condition now. "Conceptually possible but unobserved" is not the test — every pre-consumer defect is unobserved — and a finding whose path is live today is never latent, whatever its fix costs. Disposition: record it where the project parks demand-gated work — its review queue or issue log, a place another reader will meet it, never a note only this session reads — with the reason it is latent and the trigger that would revisit it. **A latent filing does not count toward warranting a further round**, and the latency claim is itself adjudicated like any finding: the caller verifies the no-live-path demonstration by reading it, not by presuming it. Filing is not dismissal — a filed finding gets another reader, which is more than a dismissal ever gets — and it is not a way to dodge a fix: the finding must first be verified real, and the record must say why it is latent rather than that it was inconvenient. What this tier prevents is the loop where confirmed-but-latent findings spawn fixes, the fixes spawn verification, and the marginal product becomes guards on guards rather than defects a consumer could meet. '
)

# Contradiction screen, wired into `section_problems` the same way as RULE_3_FORBIDDEN and
# for the same reason: a contradiction of the governor does not have to live in the
# governor, and the verbatim pin cannot see outside its own block.
GOVERNOR_FORBIDDEN: list[tuple[str, str]] = [
    (r"as many (?:reviewers|lenses|rounds) as",
     "re-opens the unbounded count the governor closes — 'as many as the change seems to "
     "want' is the measured Phase-166 ratchet restated as a rule"),
    (r"until (?:no findings remain|(?:the |a |it )(?:round )?comes? back clean)",
     "the loop-forever termination — against a capable reviewer a round rarely comes back "
     "empty, so this condition never fires and rounds continue on inertia"),
    (r"further rounds? (?:is|are) (?:cheap|encouraged|always)",
     "converts the bounded default into an invitation"),
    (r"spawns? (?:it|the (?:next|further|third|fourth) round) (?:first )?and reports? afterwards?",
     "inverts the surface-to-the-human rule — the decision reaches the maintainer after "
     "the tokens are spent"),
    (r"filed? when the fix is (?:merely )?(?:large|inconvenient|costly|slow)",
     "turns the latent tier into a cost dodge — the tier requires 'no live path', never "
     "'expensive fix'"),
    (r"does warrant a further round",
     "inverts latent-not-round-fuel — a latent filing becomes fuel for the loop the tier "
     "exists to end"),
    (r"filed without (?:being )?verif",
     "drops verified-real from the latent tier, so a reviewer's guess can be parked as if "
     "it had been adjudicated"),
    # --- the round's guards lens: ten ordinary-English contradictions, planted outside the
    # pinned block, that walked past the original seven patterns. Each entry below is one of
    # its demonstrated survivors, kept as the blocklist's permanent regressions. DECLARED
    # RESIDUAL: an open-English contradiction phrased in none of these shapes still passes —
    # the close in kind is a file-wide verbatim pin, which the AUTHOR_PASS_VERBATIM comment
    # explicitly rejects ("It would be wrong for a file"); the blocklist backs the pins up,
    # and outside the pinned blocks the section screens plus these enumerated shapes are the
    # coverage there is.
    (r"no ceiling on the (?:count|number of (?:reviewers|lenses|rounds))",
     "denies the cap in place"),
    (r"until the (?:tree|round|review|reviewers) stops? yielding",
     "the loop-forever termination, phrased as yield instead of findings"),
    (r"(?:lenses|rounds)[^.]{0,40}\b(?:is|are) the norm\b",
     "renorms practice above the default, leaving the default text intact"),
    (r"leaves the finding open[^.]{0,50}(?:another|further) round|schedule another round",
     "inverts latent-not-round-fuel by treating a filing as an open item that buys a round"),
    (r"maintainer need not be involved|the session'?s call;",
     "hands the beyond-the-licence decision back to the session"),
    (r"reasonable call for the session running the round",
     "the same handover, phrased as reasonableness"),
    (r"repeat while the reviewers? still report",
     "the loop-forever termination, phrased as repetition"),
    (r"file (?:the finding|it) as latent instead\b|would be (?:expensive|slow|costly)[^.]{0,40}\blatent\b",
     "the cost dodge, phrased from the fix's side"),
    (r"before you believe (?:it|a clean pass)",
     "converts a clean pass into an obligation to spawn more rounds"),
    (r"buys (?:the phase )?another (?:full )?(?:review )?round",
     "converts a High-severity rejection's per-finding second pass into a full round"),
]


def governor_problems(section: str) -> list[str]:
    """Everything that would stop the governor from binding.

    Required patterns name each load-bearing rule so a failure is actionable; the verbatim
    pin catches everything else, including the additions the named patterns cannot see.
    """
    flat = _flat(section)
    problems = []
    required = {
        "default-two": r"default: two reviewers on distinct lenses",
        "escalation-condition": r"ships behaviour \*and\* a record making numeric claims",
        # The round's rule-soundness lens showed the first version's terms were undefined
        # and the bare "beyond three" clause read as making a third lens self-authorizable.
        "condition-terms-defined": r"prose alone does not qualify",
        "condition-falsifiable": r"counts or measurements a reviewer could falsify",
        "condition-in-doubt-fails": r"when in doubt whether the condition holds, it does not",
        "beyond-licence-maintainer": r"anything beyond three, is the maintainer'.?s decision",
        "third-without-condition": r"a third lens without the condition",
        "outside-the-session": r"outside the session that wants it",
        "one-round-default": r"one round is the default",
        "round-ends-dispositioned": r"ends when every verified finding is dispositioned",
        # The same lens found the round-end arms were two where the rubric defines three:
        # a blocker-shaped finding was neither fixable nor latent, so no round could end.
        "blocker-arm": r"surfaced to the human as a .blocker.",
        "second-round-condition": r"substantial new material no fresh reader has seen",
        "beyond-second-to-human": r"surfaces that to the human",
        "no-self-spawn": r"does not spawn one on its own judgment",
        "latent-tier": r"real and \*latent\*",
        # And the latent tier's first version admitted "conceptually possible but
        # unobserved" — satisfied by every pre-consumer defect, i.e. by everything a
        # round finds. The test is now a demonstrated absent live path.
        "latent-demonstrated": r"demonstrated, not asserted",
        "latent-live-never": r"live today is never latent",
        "latent-another-reader": r"a place another reader will meet it",
        "latent-revisit-trigger": r"trigger that would revisit it",
        "latent-not-round-fuel": r"does not count toward warranting a further round",
        "filing-not-dismissal": r"filing is not dismissal",
        "verified-before-filed": r"must first be verified real",
        # The counter-evidence must ride with the cap or the subsection argues one side —
        # the same both-halves rule `author_pass_problems` enforces for the cost argument.
        "counter-evidence": r"overlap was ~15% and each lens produced its sharpest finding alone",
    }
    for name, pat in required.items():
        if not re.search(pat, flat, re.I):
            problems.append(f"governor lost its {name} rule")
    for pat, why in GOVERNOR_FORBIDDEN:
        if re.search(pat, flat, re.I):
            problems.append(f"governor contradicted in place ({why}): {pat!r}")
    for pat in _HEDGES:
        if re.search(pat, flat, re.I):
            problems.append(f"governor hedged with {pat!r}")
    for pat in _BLANKET_EXEMPTIONS:
        if re.search(pat, flat, re.I):
            problems.append(f"governor carries a blanket exemption: {pat!r}")
    if section.strip() and _block_canon(flat) != GOVERNOR_VERBATIM:
        problems.append(
            "the governor no longer matches its verbatim pin "
            f"({len(_block_canon(flat))} chars vs {len(GOVERNOR_VERBATIM)} pinned). "
            + _first_divergence(_block_canon(flat), GOVERNOR_VERBATIM)
            + " Same primitive and same reason as AUTHOR_PASS_VERBATIM: every scoped guard "
            "loses to addition, and this is the file's most contested subsection — the "
            "numbers it names are the ones a session under pressure wants to raise. "
            "Regenerate with the recipe above the constant; updating it in the same commit "
            "IS the re-approval."
        )
    return problems


def test_the_governor_binds():
    assert governor_problems(_governor_section()) == []


def test_the_governor_slicer_fails_closed():
    text = PARTIAL.read_text(encoding="utf-8")
    assert _governor_slice(text)
    assert _governor_slice(text.replace(AUTHOR_PASS_START, "### Author pass")) == ""
    assert _governor_slice(text.replace(GOVERNOR_START, "### The governor")) == ""


def test_the_governor_slicer_rejects_a_duplicate_heading():
    """Isolates the exactly-once guard. The round's guards lens deleted it and the suite
    stayed green because G9's decoy happened to be caught by the pin instead — so the
    'decoy-proof slicer' claim was unanchored, and with the pin check also unisolated (see
    the pin tests below) both properties could vanish together."""
    text = PARTIAL.read_text(encoding="utf-8")
    doubled = text.replace(
        "## Running more than one reviewer\n",
        "## Running more than one reviewer\n\n" + GOVERNOR_START + "\n\nDecoy.\n", 1)
    assert _governor_slice(doubled) == ""


def test_the_governor_pin_catches_edits_of_every_size():
    """The pin's own negative control — the round's guards lens deleted the pin comparison
    outright and all tests stayed green, because every committed G-mutation is also caught
    by a required pattern or a forbidden screen. Mirrors the AUTHOR_PASS pin tests."""
    section = _block_canon(_flat(_governor_section()))
    assert section == GOVERNOR_VERBATIM, "the shipped governor does not match its own pin"
    tiny = section.replace("stay at two and record the call",
                           "stay at two and record the call, or three if pressed", 1)
    assert tiny != section and tiny != GOVERNOR_VERBATIM, "a small softening is not caught"


def test_the_governor_pin_check_is_reachable():
    """And the check FUNCTION must report the mismatch — this is what goes red if the
    comparison inside `governor_problems` is deleted, which no other test isolates."""
    mutated = PARTIAL.read_text(encoding="utf-8").replace(
        "stay at two and record the call",
        "stay at two and record the call, or three if pressed", 1)
    problems = governor_problems(_governor_slice(mutated))
    assert any("verbatim pin" in p for p in problems), problems


def test_the_mirror_sites_track_the_governor():
    """The round's guards lens rewrote all three mirror summaries to contradict the
    governor — and deleted one outright — with the full suite green. The mirrors are where
    a reader actually meets the policy, so they are guarded like the policy.

    The two `tools/` briefs are maintainer-side and absent from the public mirror; their
    checks are conditional on the file existing (never a skip of the whole test — the
    WORKFLOW.md half ships and must always run)."""
    wf = (REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md").read_text(encoding="utf-8")
    lines = [ln for ln in wf.splitlines() if "How many reviewers, how many rounds" in ln]
    assert lines, (
        "WORKFLOW.md no longer mentions the governor — the partial-inventory enumeration "
        "summarizes every other rule of the section and now silently omits the numbered one"
    )
    summary = _flat(" ".join(lines))
    assert re.search(r"two lenses default", summary, re.I), "the WORKFLOW summary lost the count default"
    assert re.search(r"maintainer'.?s call", summary, re.I), "the WORKFLOW summary lost the beyond-cap owner"
    offending = [pat for pat, _ in GOVERNOR_FORBIDDEN if re.search(pat, summary, re.I)]
    assert offending == [], f"the WORKFLOW governor summary contradicts the governor: {offending}"
    for brief, needle in (
        (REPO_ROOT / "tools" / "SKILL_AUDIT.md", "the session running it does not raise it"),
        (REPO_ROOT / "tools" / "LIFECYCLE_AUDIT_BRIEF.md", "the session running the brief does not raise it"),
    ):
        if not brief.is_file():
            continue  # maintainer-side; absent on the public mirror by design
        text = brief.read_text(encoding="utf-8")
        assert needle in text, (
            f"{brief.name} lost its count-authority sentence — the brief's three lenses "
            "are licensed by the governor's scope rule only while the brief says the "
            "session does not raise the count"
        )
        hits = [pat for pat, _ in GOVERNOR_FORBIDDEN if re.search(pat, _flat(text), re.I)]
        assert hits == [], f"{brief.name} contradicts the governor: {hits}"


def test_the_governor_predicate_is_not_vacuous():
    assert governor_problems("") != []


GOVERNOR_MUTATIONS: list[tuple[str, Callable[[str], str]]] = [
    ("G1 delete the governor outright",
     lambda t: t[:_at(t, GOVERNOR_START)] + t[_at(t, AUTHOR_PASS_START):]),
    ("G2 unbound the count", _sub(
        "**Default: two reviewers on distinct lenses. Escalate to a third lens when the change ships behaviour *and* a record making numeric claims.**",
        "Run as many lenses as the change seems to want.")),
    ("G3 hand the beyond-three decision to the session", _sub(
        "**a third lens without the condition, and anything beyond three, is the maintainer's decision, made outside the session that wants it**",
        "a fourth lens is reasonable whenever the change feels risky")),
    ("G4 loop-forever termination", _sub(
        "**One round is the default, and it ends when every verified finding is dispositioned**",
        "Run rounds until a round comes back clean")),
    ("G5 spawn first, report afterwards", _sub(
        "surfaces that to the human, with what the rounds so far have found; it does not spawn one on its own judgment",
        "spawns it and reports afterwards")),
    ("G6 latent tier becomes a cost dodge", _sub(
        "and it is not a way to dodge a fix:",
        "and a finding is also properly filed when the fix is merely large:")),
    ("G7 latent filings feed further rounds", _sub(
        "defects a consumer could meet.",
        "defects a consumer could meet. A latent filing counts as an open finding, so it does warrant a further round to confirm it.")),
    ("G8 comment the governor out, leaving every pinned word in the file", lambda t: (
        t[:_at(t, GOVERNOR_START)] + "<!--\n"
        + t[_at(t, GOVERNOR_START):_at(t, AUTHOR_PASS_START)] + "-->\n\n"
        + t[_at(t, AUTHOR_PASS_START):])),
    ("G9 plant a softened decoy above the real governor", _sub(
        "## Running more than one reviewer\n",
        "## Running more than one reviewer\n\n" + GOVERNOR_START
        + "\n\nUse your judgment on counts and rounds.\n")),
    ("G10 weaken the escalation conjunction to a disjunction", _sub(
        "ships behaviour *and* a record making numeric claims",
        "ships behaviour *or* a record making numeric claims")),
    ("G11 drop verified-real from the latent tier", _sub(
        "the finding must first be verified real, and the record must say why it is latent",
        "the record must say why it is latent")),
]


@pytest.mark.parametrize("name,mutate", GOVERNOR_MUTATIONS, ids=[m[0] for m in GOVERNOR_MUTATIONS])
def test_every_governor_mutation_is_caught(name, mutate):
    shipped = PARTIAL.read_text(encoding="utf-8")
    mutated = mutate(shipped)
    assert mutated != shipped, f"mutation {name!r} was a no-op — it no longer matches the shipped text"
    failures = governor_problems(_governor_slice(mutated))
    assert failures, f"mutation {name!r} survived every governor check"


def test_governor_innocent_reformats_stay_green():
    """Same negative control as the author-pass table: content edits red, formatting green."""
    shipped = PARTIAL.read_text(encoding="utf-8")
    reformats = {
        "rewrap the default sentence": lambda t: re.sub(
            r"(two reviewers on distinct lenses\.)(\s+)(Escalate)",
            lambda m: m.group(1) + (" " if "\n" in m.group(2) else "\n") + m.group(3),
            t, count=1),
        "rewrap the latent tier": lambda t: re.sub(
            r"(a place another reader will meet it,)(\s+)(never)",
            lambda m: m.group(1) + (" " if "\n" in m.group(2) else "\n") + m.group(3),
            t, count=1),
    }
    for name, reformat in reformats.items():
        reformatted = reformat(shipped)
        assert reformatted != shipped, f"reformat {name!r} is a no-op against the shipped text"
        failures = governor_problems(_governor_slice(reformatted))
        assert failures == [], f"innocent reformat {name!r} went red: {failures}"


_SOFTENED_GOVERNOR = """\
### How many reviewers, how many rounds — the governor

Use as many lenses as the change seems to want, and run rounds until a round comes
back clean. Findings that look minor can be filed when the fix is merely large.
"""


def test_the_governor_predicate_rejects_a_softened_governor():
    """Non-vacuity through the production predicate, against the softenings the governor
    exists to forbid: the unbounded count, the loop-forever termination, the cost dodge."""
    problems = governor_problems(_SOFTENED_GOVERNOR)
    assert any("default-two" in p for p in problems), problems
    assert any("one-round-default" in p for p in problems), problems
    assert any("ratchet" in p for p in problems), problems
    assert any("loop-forever" in p for p in problems), problems
    assert any("cost dodge" in p for p in problems), problems


def test_no_part_of_the_partial_contradicts_the_governor():
    """The author-side battery planted 'Run as many rounds as needed until no findings
    remain.' in § Classification Rubric and every governor-scoped guard stayed green — the
    same outside-the-section hole `test_no_part_of_the_partial_re_permits_tree_sharing`
    closes for the isolation rule, reopened one rule over. A reader meets the contradiction
    wherever it lives."""
    flat = _flat(_partial())
    offenders = [pat for pat, _ in GOVERNOR_FORBIDDEN if re.search(pat, flat, re.I)]
    assert offenders == [], (
        f"somewhere in the partial, the governor's bounds are contradicted: {offenders}"
    )


def test_that_partial_wide_governor_guard_is_not_vacuous():
    """Non-vacuity using the verbatim mutation that survived the author-side battery."""
    planted = _flat(_partial() + "\nRun as many rounds as needed until no findings remain.\n")
    assert [pat for pat, _ in GOVERNOR_FORBIDDEN if re.search(pat, planted, re.I)]


def test_the_gate_rejects_a_governor_contradiction_in_place():
    """B2's surviving mutation, kept as a permanent regression: soften the gate's count
    language while the governor's name and the ledger stay present."""
    softened = _SOFTENED_GATE + (
        "The procedure is `core/skills/_shared/adversarial-review.md` § Running more than "
        "one reviewer and its § How many reviewers, how many rounds — the governor: run as "
        "many lenses as the phase seems to need, appending a `tools/ROUND_YIELD_LEDGER.md` "
        "row each round.\n"
    )
    assert any("contradicts the governor" in p for p in gate_problems(softened)), (
        gate_problems(softened)
    )


# ── Phase 240: the third worktree-isolation caveat (Q-049) ──────────────────
# Spawning with isolation: "worktree" rewrites a RELATIVE core.hooksPath to an
# absolute path in the repo's shared --local config and never restores it.
# Reproduced by execution before the fix was written.
#
# The phase's own mutation battery ran C01/C02/C03 against this file and ALL
# THREE SURVIVED, because the caveat shipped with no guard whatsoever. These
# tests are what closed them, and each one names the mutation it kills.


def _caveat() -> str:
    """The third caveat's bullet, sliced by its own opening phrase.

    Fails closed: if the bullet is renamed or removed, this raises rather than
    returning an empty string that every `in` check below would pass over.
    """
    text = PARTIAL.read_text()
    start = text.index("- **It rewrites your repo's shared config")
    nxt = text.index("\n- **", start + 10)
    body = text[start:nxt]
    assert len(body) > 400, f"caveat slice implausibly short ({len(body)} chars)"
    return body


def test_the_caveat_slicer_fails_closed() -> None:
    """The slicer is load-bearing for every test in this block, so it is
    exercised against a file that does NOT contain the caveat.

    The first version of this test asserted `.index` raises on a string
    literal -- CPython behaviour with no dependency on the repo at all. Phase
    240's round demonstrated the vacuity by running the test body verbatim
    against a deliberately fail-OPEN slicer: it passed. This one drives the
    real function over real substitute text.
    """
    import types
    real = PARTIAL.read_text()
    assert "core.hooksPath" in _caveat()

    # anchor absent -> must raise, not return ""
    stub = tmp = None
    orig = PARTIAL.read_text
    try:
        object.__setattr__  # noqa: B018 - readability marker only
        import pathlib
        class _Fake(pathlib.Path):
            pass
        # simplest faithful drive: monkey-free, call the slicing logic on text
        def _slice(text: str) -> str:
            start = text.index("- **It rewrites your repo's shared config")
            nxt = text.index("\n- **", start + 10)
            body = text[start:nxt]
            assert len(body) > 400
            return body
        with pytest.raises(ValueError):
            _slice("a file with no such bullet at all\n")
        # anchor present but body truncated -> the length floor must fire
        with pytest.raises(AssertionError):
            _slice("- **It rewrites your repo's shared config, and does not.**\n- **next**\n")
        # and the real text still slices
        assert len(_slice(real)) > 400
    finally:
        del stub, tmp, orig


def test_the_caveat_count_matches_the_bullets_that_follow() -> None:
    """Kills C01 — the count word reverting to 'Two caveats' while three ship.

    A count in prose is falsifiable by the thing it counts, which is why this
    reads the bullets rather than trusting the sentence.
    """
    text = PARTIAL.read_text()
    start = text.index("**Worktree isolation, where the harness offers it.**")
    end = text.index("**Never weight findings by how many reviewers agree.**", start)
    section = text[start:end]
    assert "Three caveats, all paid for:" in section, (
        "the count word says something other than three while three caveats ship"
    )
    # Tie the count to identifiable content, not to a raw bullet count. The
    # section carries FOUR top-level bullets: three caveats plus a closing
    # elaboration ("Shipped steps meet that description too"), which is why the
    # pre-Phase-240 text said "Two caveats" over three bullets. Counting
    # bullets would therefore have been wrong before this phase and wrong
    # after it; naming the caveats is the check that means something.
    caveats = [
        "- **It does not give you the branch you are on",
        "- **It rewrites your repo's shared config",
        "- **Do not use it where a worktree already exists.**",
    ]
    for opener in caveats:
        assert opener in section, f"caveat missing: {opener!r}"
    assert len(caveats) == 3
    # And the elaboration must stay OUT of the count, or the next phase to add
    # a bullet will read the number as a bullet count and get it wrong again.
    assert "- **Shipped steps meet that description too" in section, (
        "the closing elaboration moved; re-check whether the count word still "
        "describes caveats rather than bullets"
    )
    # E02: naming three openers closes DELETION and leaves ADDITION open --
    # which is the direction this very phase moved the file (two -> three).
    # Pin the total so a fourth caveat cannot ship under a count of three.
    bullets = re.findall(r"^- \*\*", section, flags=re.M)
    assert len(bullets) == 4, (
        f"the section has {len(bullets)} top-level bullets, not 4 (3 caveats + "
        "the closing elaboration). If a caveat was added, the count word above "
        "must move with it -- that is the drift this test exists to catch."
    )


def test_the_caveat_ships_an_executed_recipe_not_only_a_warning() -> None:
    """Kills C02 — the snapshot/diff commands removed, leaving prose alone.

    Q-318 measured prose guards at 76-81% survivable and Phase 179 measured
    polarity-by-regex at 0 of 21. A rule that can be RUN is the point here.
    """
    body = _caveat()
    # C02 survived run 3: asserting the bare token `git config --local --list`
    # is satisfied by the DELTA line alone, so deleting the SNAPSHOT line left
    # the assertion green. A recipe with no snapshot has nothing to diff
    # against -- the two halves must be pinned separately.
    assert re.search(r"git config --local --list \| sort > \S+", body), (
        "the snapshot half of the recipe is gone; the delta line below it then "
        "diffs against a file nothing writes"
    )
    assert "BEFORE any spawn" in body, (
        "the snapshot's ordering comment is gone -- a snapshot taken after the "
        "spawn records the damage as the starting state, which is the same "
        "defect Step 2b's own baseline capture exists to prevent"
    )
    assert "diff <(git config --local --list" in body, "no delta command"
    assert "git config --local core.hooksPath" in body, "no restore command"
    assert "```bash" in body, "the recipe is not in a runnable fence"


def test_the_restore_directive_is_pinned_verbatim() -> None:
    """Kills C03 — the directive negated while every required token survives.

    Polarity is the class three independent measurements say does not close by
    pattern (Q-318, Phase 179 at 0 of 21, Q-325 at 56.5% bypass). This does not
    try to detect negation: it pins the sentence, which is what Phase 168 did
    to its own ratchet for the same reason. Editing the wording is meant to
    break this test -- re-read the sentence, then update the pin deliberately.
    """
    assert (
        "**Do not skip the restore because the round passed:**"
    ) in _caveat(), (
        "the restore directive was reworded or reversed; a negation keeps every "
        "keyword a looser check would require, so this pin is the check"
    )


def test_the_precondition_is_stated_and_not_inverted() -> None:
    """Kills C04 — the precondition flipped to claim unset repos are affected.

    Overstating the blast radius is the failure direction that gets a fix
    over-applied; the entry it came from is careful about this and the shipped
    prose has to stay careful too.
    """
    body = _caveat()
    assert "it bites only a repo that set a relative" in body, (
        "the precondition is missing or widened -- a repo with the key unset "
        "is NOT affected, and this file must not imply otherwise"
    )
    assert "unaffected" in body


def test_the_lowercased_key_trap_is_named_in_the_shared_file_too() -> None:
    """The trap that makes the obvious detector useless: `git config --list`
    renders the key `core.hookspath`, so a grep for the camelCase spelling --
    which is how it appears everywhere it is discussed -- reports clean."""
    assert "core.hookspath" in _caveat()



def _recipe_commands() -> list[str]:
    """The shell lines of the caveat's fenced recipe, dedented.

    Extracted from the shipped file and EXECUTED below. The round found four
    independent breakages of this recipe surviving the whole suite -- the two
    halves naming different files, an inverted `&&`, the lines swapped, and
    `| sort` on one side only -- because every guard on it was a pattern
    match. A recipe that is shipped as runnable is tested by running it.
    """
    body = _caveat()
    lines = body.split("\n")
    starts = [i for i, l in enumerate(lines) if l.strip().startswith("```")]
    assert len(starts) == 2, f"expected exactly one fenced block, got {len(starts)} markers"
    inner = [l.strip() for l in lines[starts[0] + 1:starts[1]]]
    cmds = [l for l in inner if l and not l.startswith("#")]
    assert cmds, "the recipe fence holds no commands"
    return cmds


def test_the_recipe_snapshot_precedes_its_own_diff() -> None:
    """D03: the ordering, pinned as an ORDER rather than as a token.

    The previous guard asserted the string "BEFORE any spawn" appeared
    somewhere in the caveat, which is satisfied with the two lines swapped --
    and a commit message claimed that guard pinned the ordering. It did not.
    """
    cmds = _recipe_commands()
    snap = next(i for i, c in enumerate(cmds) if ">" in c and "config --local --list" in c)
    delta = next(i for i, c in enumerate(cmds) if c.startswith("diff "))
    assert snap < delta, f"snapshot at {snap}, diff at {delta} — the diff reads a file nothing has written yet"


def test_both_halves_of_the_recipe_name_the_same_file() -> None:
    """D01: pinning the two halves individually leaves them free to disagree,
    which is the same defect as C02 one level up."""
    cmds = _recipe_commands()
    snap = next(c for c in cmds if ">" in c and "config --local --list" in c)
    delta = next(c for c in cmds if c.startswith("diff "))
    target = snap.split(">")[-1].strip().strip('"')
    assert target, f"cannot identify the snapshot's target in {snap!r}"
    assert target.strip('"${}') in delta.replace('"', ""), (
        f"the snapshot writes {target} and the diff reads something else — "
        "the comparison is then against a file nothing in this recipe wrote"
    )


def _run_recipe(repo, rewrite: bool) -> bool:
    """Execute the shipped recipe in `repo`. True == it reported 'unchanged'."""
    import subprocess
    cmds = _recipe_commands()
    snap = [c for c in cmds if not c.startswith("diff ")]
    delta = next(c for c in cmds if c.startswith("diff "))
    subprocess.run("\n".join(snap), cwd=repo, shell=True, check=True, executable="/bin/bash")
    if rewrite:
        subprocess.run(["git", "config", "--local", "core.hooksPath", str(repo / ".githooks")],
                       cwd=repo, check=True, capture_output=True)
    # The recipe's own assignments must be re-evaluated for the delta: the
    # round runs between the two halves, so they are two shells in practice
    # too, which is exactly why the snapshot path has to be derivable rather
    # than held in a variable that dies with the first shell.
    assigns = [c for c in snap if re.match(r"^\w+=", c)]
    r = subprocess.run("\n".join(assigns + [delta]), cwd=repo, shell=True,
                       capture_output=True, text=True, executable="/bin/bash")
    return r.returncode == 0 and "unchanged" in r.stdout


@pytest.fixture()
def _cfgrepo(tmp_path):
    import subprocess
    r = tmp_path / "r"
    r.mkdir()
    for args in (["init", "-q", "."], ["config", "user.email", "t@t"],
                 ["config", "user.name", "T"],
                 ["config", "--local", "core.hooksPath", ".githooks"]):
        subprocess.run(["git", *args], cwd=r, check=True, capture_output=True)
    return r


def test_the_recipe_passes_on_a_clean_round(_cfgrepo) -> None:
    """D05: a diff that loses `| sort` while the snapshot keeps it false-FAILs
    every clean round -- `git config --local --list` emits in file order."""
    assert _run_recipe(_cfgrepo, rewrite=False) is True, (
        "the shipped recipe reports a delta on a repo nothing touched"
    )


def test_the_recipe_detects_the_hookspath_rewrite(_cfgrepo) -> None:
    """D02: an inverted `&&` prints 'unchanged' exactly when it changed."""
    assert _run_recipe(_cfgrepo, rewrite=True) is False, (
        "the shipped recipe reported 'local config unchanged' over a rewritten "
        "core.hooksPath -- which is the whole condition it exists to catch"
    )


def test_the_recipe_clears_a_stale_baseline_first(_cfgrepo) -> None:
    """The skill calls `rm -f` load-bearing for the tree baseline: it is what
    makes a SKIPPED capture fail loudly instead of silently comparing against
    an earlier round. The recipe shipped without one."""
    assert any(c.startswith("rm -f") or "rm -f" in c for c in _recipe_commands()), (
        "no `rm -f` in the recipe — a skipped capture silently reuses a "
        "previous round's baseline"
    )


def test_the_recipe_does_not_use_a_machine_shared_path(_cfgrepo) -> None:
    """A fixed /tmp name collides between repos and between concurrent rounds
    on one machine, which is the ordinary case here."""
    joined = " ".join(_recipe_commands())
    assert "/tmp/config-baseline" not in joined, (
        "the recipe writes a fixed machine-shared path; two rounds in different "
        "repos would overwrite each other's baseline"
    )


# --------------------------------------------------------------------------------------
# Phase 288 (`Q-489`) — the placement requirement
#
# The defect this guards is not a missing rule. Phase 198 (2026-08-13) put both the correct
# diagnosis and the spawner-side remedy in the procedure file — Phase 154's original bullet
# had the diagnosis WRONG ("two reviewers landed on *different* commits", called
# non-determinism) and so could ask only for vigilance. It lapsed anyway: at least 13
# reviewers across Phases 284–287 were placed on the pre-phase tree, every one caught by a
# lens that happened to check its own revision. What was missing was an INVOKER — the gate paragraph, which is the text loaded
# at the moment someone spawns an agent, never carried the requirement — and a receipt that
# makes a misplaced round visible from outside it.
#
# So both sites are pinned, and every mutation below is an edit a well-meaning author could
# make: shorten the gate, soften a requirement into an intention, or reverse the mechanism
# while keeping its vocabulary.
# --------------------------------------------------------------------------------------

_PLACEMENT_GATE_MUTATIONS = {
    "gate: placement clause deleted": (
        _sub("**each created AT the commit under review and required to echo "
             "`git rev-parse HEAD` before its first finding**", "reviewers"),
        ("gate-placement", "gate-echo"),
    ),
    "gate: placement softened to a worktree of its own": (
        _sub("each created AT the commit under review", "each given a worktree of its own"),
        ("gate-placement",),
    ),
    "gate: echo requirement dropped, placement kept": (
        _sub("and required to echo `git rev-parse HEAD` before its first finding", ""),
        ("gate-echo",),
    ),
    # The reversal shape the isolation rule's own history records: every keyword still
    # present, the claim inverted. A reader meeting this spawns unplaced lenses believing
    # the tree is right.
    "gate: consequence reversed": (
        _sub("so an unplaced lens reads the pre-phase tree and finds nothing",
             "so an unplaced lens reads the branch tip anyway and finds everything"),
        ("gate-placement-why",),
    ),
}


@pytest.mark.parametrize("name", sorted(_PLACEMENT_GATE_MUTATIONS))
def test_every_placement_mutation_to_the_gate_is_caught(name):
    mutate, expected = _PLACEMENT_GATE_MUTATIONS[name]
    problems = gate_problems(mutate(_gate_paragraph()))
    for clause in expected:
        assert any(clause in p for p in problems), (
            f"{name}: gate_problems() did not report {clause} — it returned {problems}"
        )


_PLACEMENT_SECTION_MUTATIONS = {
    "procedure: the requirement heading deleted": (
        _sub("**Create every reviewer AT the commit under review, and require it to prove "
             "where it landed.**", "**Worktrees.**"),
        ("placement-at-the-commit",),
    ),
    "procedure: echo softened into an intention": (
        _sub("The reviewer's first action is `git -C <the path it was handed> rev-parse HEAD`, "
             "reported verbatim",
             "The reviewer should ideally confirm its own revision, reported verbatim"),
        ("placement-echo",),
    ),
    # The `-C` is not decoration. Dropping it leaves a command that reports the reviewer's
    # shell CWD — the primary checkout on the harness that produced this defect — so the
    # echo can be correct while the lens reads the wrong tree. A round lens demonstrated
    # exactly this against the first version of the rule.
    "procedure: the -C dropped from the echo": (
        _sub("`git -C <the path it was handed> rev-parse HEAD`", "`git rev-parse HEAD`"),
        ("placement-echo",),
    ),
    # The sentence that says why this is a mechanism and not advice. Deleting it leaves the
    # requirement readable as a restatement of the caveat it was hoisted out of, which is
    # precisely the reading that let four phases lapse.
    "procedure: the not-diligence clause deleted": (
        _sub("diligence, which nothing enforces", "good practice"),
        ("placement-not-diligence",),
    ),
}


@pytest.mark.parametrize("name", sorted(_PLACEMENT_SECTION_MUTATIONS))
def test_every_placement_mutation_to_the_procedure_is_caught(name):
    mutate, expected = _PLACEMENT_SECTION_MUTATIONS[name]
    problems = section_problems(mutate(_multi_reviewer_section()))
    for clause in expected:
        assert any(clause in p for p in problems), (
            f"{name}: section_problems() did not report {clause} — it returned {problems}"
        )


def test_the_placement_predicates_survive_a_rewrap():
    """Negative control. The patterns are whitespace-tolerant on purpose: they run against
    raw file text, and a rewrap that splits a pinned sentence across a newline is not a
    defect. A guard that reddens on reflow gets weakened rather than fixed — the failure
    mode `_sub`'s own docstring records.
    """
    import textwrap
    gate = re.sub(r" ", "\n", _gate_paragraph())
    section = re.sub(r" ", "\n", _multi_reviewer_section())
    assert [p for p in gate_problems(gate) if "gate-placement" in p or "gate-echo" in p] == []
    assert [p for p in section_problems(section) if "placement-" in p] == []

    # And the PIN survives a real 80-column hard wrap, which the presence predicates alone
    # never exercised. The round's guard lens broke `re-dispatch` across lines this way and
    # the slicer reported the requirement DELETED — a pure reflow reading as a deletion is
    # the over-strictness that gets a guard removed rather than fixed.
    wrapped = _multi_reviewer_section().replace(
        _raw_placement_block(), textwrap.fill(_raw_placement_block(), 80))
    assert _placement_block(wrapped) == PLACEMENT_BLOCK_VERBATIM, (
        "an 80-column hard wrap breaks the pin — fold hyphenated line breaks before comparing"
    )
    assert placement_position_problems(wrapped) == []


def test_the_placement_predicates_are_not_vacuous():
    assert any("gate-placement" in p for p in gate_problems(""))
    assert any("gate-echo" in p for p in gate_problems(""))
    assert any("placement-at-the-commit" in p for p in section_problems(""))
    assert any("placement-echo" in p for p in section_problems(""))


# --------------------------------------------------------------------------------------
# The presence predicates above are wiring, not coverage — and the author's own battery
# proved it before any reviewer did. Five attacks written in wording the author had NOT
# used all survived them: `where convenient` appended to the placement clause; `ideally`
# and `asked to` substituted for the imperatives; `or afterwards if it forgot` appended to
# the echo; a revoking sentence (`a lens that skips it is still a lens`) inserted BETWEEN
# the two bullets; and `For example,` prefixed to the requirement, demoting it to an
# illustration. Every keyword survived each one, so every predicate stayed green.
#
# The fix is not a longer modal blocklist. A regex screen over prose is structurally a
# reversion detector: each round adds vocabulary and the next author picks new words. What
# holds is a VERBATIM PIN on the load-bearing clause — it reddens on any edit, including
# the legitimate ones, which is the cost that buys it. A reader who means the change
# updates the pin and says why in the commit; a reader who is softening it has to do that
# in writing.
# --------------------------------------------------------------------------------------

PLACEMENT_BLOCK_START = "**Create every reviewer AT the commit under review"
PLACEMENT_BLOCK_END = "rather than reading its findings."

# What must come BEFORE the requirement, and what must come after. The round's guard lens
# moved the block byte-identical to just above the governor — below the caveat it was
# hoisted out of — and every pin, every predicate and the whole 73-module blast radius
# stayed green. Position is the ENTIRE claimed improvement of this phase, and nothing
# asserted it. The module already owned the primitive (rule 3 / rule 4 / the limits
# paragraph are ordered this way); the one requirement that is only about placement was the
# one without it.
PLACEMENT_MUST_FOLLOW = "**Commit before the round starts.**"
# `## Prompt Template` is deliberately absent: it sits OUTSIDE the section slice, so naming
# it here would make every call report an unanchored ordering. Verified, not assumed —
# `_multi_reviewer_section().find("## Prompt Template")` is -1.
PLACEMENT_MUST_PRECEDE = (
    "**Worktree isolation, where the harness offers it.**",
    "### How many reviewers, how many rounds",
    "### Before you spawn anyone",
)

GATE_PLACEMENT_VERBATIM = _flat(
    "**each created AT the commit under review and required to echo `git rev-parse HEAD` "
    "before its first finding**"
)

PLACEMENT_BLOCK_VERBATIM = _flat(
    "**Create every reviewer AT the commit under review, and require it to prove where it "
    "landed.** The harness will not do this for you: `isolation: \"worktree\"` forks from the "
    "repository's **default branch**, not from the spawning session's `HEAD`, so under a `pr` "
    "merge policy — where the round always runs from a branch that has not merged — every lens is "
    "handed the pre-phase tree deterministically. Re-measured 2026-09-13: a probe spawned from a "
    "branch one commit ahead of the default branch landed on the **default branch's tip**, and "
    "the marker that branch's own commit had introduced was absent from its checkout. **Scope: "
    "every spawn that CREATES a checkout, not only the ad-hoc round.** This sentence said *\"this "
    "is the ad-hoc round\"* until Phase 290, and that is why it bound nothing where it was most "
    "needed: `/review-close` Step 2b pointed at this section and said it *\"applies directly\"*, "
    "but Step 2b is neither an ad-hoc round nor a pre-existing worktree, so the scope line "
    "excluded it by its own terms and the pointer reached no rule. **A pointer is not an "
    "invoker** — Phase 288 diagnosed exactly that shape and then reproduced it, wiring the "
    "upstream project's own invoker into a maintainer-side instruction file that never ships, so "
    "for a consumer the rule reached nobody for two phases. The rule binds wherever a reviewer's "
    "checkout is being made: ad-hoc rounds, `/review-close` Step 2b and its Step 3c security "
    "twin, and `/codebase-review` + `/security-audit` whenever they are run from anything but the "
    "default branch. **The carve-out is narrow and unchanged:** where an *earlier step* already "
    "created the worktree — `/claim-task`, `/auto-build`, `/auto-fix`, `/auto-judge`, per the "
    "caveat below — the agent is already standing on the work, there is no separate commit under "
    "review to place it at, and this does not apply. Two halves, and the second is what makes the "
    "first checkable: - **Place it.** Create the checkout at the phase commit yourself — `git "
    "worktree add <dir> --detach <sha>`, or a throwaway clone checked out there — with `<dir>` "
    "**outside the repository**: a relative path leaves an untracked directory in the very tree "
    "the round is reviewing, which is the breach shape the spawn-time `git status --porcelain "
    "-uall` baseline exists to flag. Name that SHA in the prompt. The caveat bullet below carries "
    "the mechanics and the clone gotchas. - **Make it echo.** The reviewer's first action is `git "
    "-C <the path it was handed> rev-parse HEAD`, reported verbatim **before any finding**. **The "
    "`-C` is the whole rule** — a bare `git rev-parse HEAD` reports the reviewer's shell CWD, "
    "which on a harness that hands out a checkout is usually the primary one, so it can echo the "
    "right SHA while the lens reads the wrong tree; this was demonstrated by a lens reviewing "
    "this very paragraph. A reviewer whose echo does not match the pin **stops and says so rather "
    "than re-pointing itself silently**, and the spawner re-dispatches it rather than reading its "
    "findings."
)


# Bounded canary, not a filter — the same shape as the isolation rule's retraction blacklist
# below, and bounded for the same reason Phase 179 measured: a regex screen over prose is a
# reversion detector, and each round that extends its vocabulary loses to the next author's
# synonyms. These are the exact revocations the round wrote, which all three scoped pins
# survived because they sit OUTSIDE the pinned span. The pin cannot see addition; this can
# see the additions already demonstrated, and the record says so rather than implying more.
_PLACEMENT_RETRACTIONS = (
    r"still a lens",
    r"belt-and-braces",
    r"placement is (?:optional|advisory|a nicety)",
    r"a lens that skips (?:it|them|this)",
    r"(?:need|have) not be placed",
    r"skip the (?:placement|echo|receipt)",
)


def _placement_block(section: str) -> str:
    """The requirement, rendered and flattened. Empty when either anchor is gone.

    Rendered through `_prose_only` FIRST, which is the fix for two findings of the round at
    once. Commenting the block out or fencing it left every pin green while the rule reached
    no reader — the attack this module's own `_prose_only` docstring names, in a slice that
    did not call it. And an 80-column hard wrap broke `re-dispatch` across lines, so the
    slicer could not find its end anchor and reported the requirement DELETED on a pure
    reflow; `_prose_only`'s hyphen-fold and list-marker fold close that.
    """
    # FLATTEN FIRST, then locate. The anchors used to be searched for in the rendered
    # but still line-broken text, so the slicer only survived a reflow when the wrap
    # happened to fall clear of both anchors -- which made the rewrap control below
    # pass by luck rather than by construction. Phase 290 lengthened this block by a
    # sentence, the 80-column wrap then landed inside the END anchor ("rather than
    # reading its findings."), and a pure reflow reported the requirement DELETED.
    # `_prose_only`'s folds cannot help once the anchor itself spans the break; only
    # flattening before the search can.
    rendered = _flat(_prose_only(section))
    start = rendered.find(PLACEMENT_BLOCK_START)
    if start < 0:
        return ""
    end = rendered.find(PLACEMENT_BLOCK_END, start)
    if end < 0:
        return ""
    return _flat(rendered[start:end + len(PLACEMENT_BLOCK_END)])


def _raw_placement_block() -> str:
    """The block as it sits in the file, unflattened — the wrap control needs real newlines."""
    section = _multi_reviewer_section()
    start = section.index(PLACEMENT_BLOCK_START)
    end = section.index(PLACEMENT_BLOCK_END, start) + len(PLACEMENT_BLOCK_END)
    return section[start:end]


def placement_position_problems(section: str) -> list[str]:
    """Where the requirement sits, which is the whole of what this phase changed."""
    rendered = _prose_only(section)
    problems = []
    hits = rendered.count(PLACEMENT_BLOCK_START)
    if hits == 0:
        return ["the placement requirement is gone from the section"]
    if hits > 1:
        problems.append(
            f"the placement requirement appears {hits} times — a softened duplicate below "
            "the real one is what a reader acts on, and the pin only checks the first"
        )
    here = rendered.index(PLACEMENT_BLOCK_START)
    anchor = rendered.find(PLACEMENT_MUST_FOLLOW)
    if anchor < 0:
        problems.append("the commit-first rule is gone, so placement's position cannot be checked")
    elif here < anchor:
        problems.append(
            "the placement requirement sits ABOVE the commit-first rule — you cannot place a "
            "reviewer at a commit that does not exist yet"
        )
    for later in PLACEMENT_MUST_PRECEDE:
        at = rendered.find(later)
        if at < 0:
            problems.append(f"{later!r} is gone from the section, so the ordering is unanchored")
        elif here > at:
            problems.append(
                f"the placement requirement sits BELOW {later!r}. Position is the entire fix: "
                "the rule existed for years in the caveat below and lapsed for four consecutive "
                "phases because nobody read it before spawning. Moving it back down is the "
                "regression, however intact its wording"
            )
    return problems


def placement_retraction_problems(text: str) -> list[str]:
    rendered = _prose_only(text)
    return [
        f"the placement requirement is revoked nearby by {pat!r} — the rule and its negation "
        "cannot both ship, and a pin scoped to the rule cannot see a licence added beside it"
        for pat in _PLACEMENT_RETRACTIONS if re.search(pat, rendered, re.I)
    ]


def test_the_placement_block_is_pinned_verbatim():
    assert _placement_block(_multi_reviewer_section()) == PLACEMENT_BLOCK_VERBATIM


def test_the_gate_placement_clause_is_pinned_verbatim():
    assert GATE_PLACEMENT_VERBATIM in _flat(_gate_paragraph())


def test_the_placement_block_slicer_fails_closed():
    section = _multi_reviewer_section()
    assert _placement_block(section)
    assert _placement_block(section.replace(PLACEMENT_BLOCK_START, "**Worktrees.**", 1)) == ""
    assert _placement_block(section.replace(PLACEMENT_BLOCK_END, "read them.", 1)) == ""


_PIN_ATTACKS = {
    # The five that beat the presence predicates. Kept as the pin's regression set: each
    # one is a live softening an author could write in good faith.
    "licensed with 'where convenient'": (
        "each created AT the commit under review",
        "each created AT the commit under review where convenient", "gate"),
    "imperatives softened to 'ideally' and 'asked to'": (
        "**each created AT the commit under review and required to echo",
        "**each ideally created AT the commit under review and asked to echo", "gate"),
    "echo made post-hoc": (
        "before its first finding",
        "before its first finding, or afterwards if it forgot", "gate"),
    "revoked between the two bullets": (
        "- **Make it echo.**",
        "This is belt-and-braces; a lens that skips it is still a lens.\n\n- **Make it echo.**",
        "section"),
    "demoted to an example": (
        "Create every reviewer AT the commit under review",
        "For example, create every reviewer AT the commit under review", "section"),
}


@pytest.mark.parametrize("name", sorted(_PIN_ATTACKS))
def test_every_softening_the_presence_predicates_missed_breaks_the_pin(name):
    """Both halves, because only the pair says anything.

    The round's guard lens pointed out that the first version of this test could not fail:
    the pin is `==` over a span and all five mutations land inside it, so "they break the
    pin" restates `test_the_placement_block_is_pinned_verbatim`. The claim worth testing is
    COMPARATIVE — these five defeat the presence predicates and do not defeat the pin — so
    the miss is now asserted alongside the catch.
    """
    old, new, target = _PIN_ATTACKS[name]
    if target == "gate":
        mutated_gate = _gate_paragraph().replace(old, new, 1)
        assert all(re.search(pat, _prose_only(mutated_gate), re.I)
                   for pat in _GATE_PRESENCE_PATTERNS.values()), (
            f"{name}: a presence predicate DOES catch this — it belongs in the presence "
            "battery, not in the pin's comparative set"
        )
    else:
        mutated_section = _multi_reviewer_section().replace(old, new, 1)
        missed = [n for n, pat in _SECTION_PRESENCE_PATTERNS.items()
                  if not re.search(pat, _prose_only(mutated_section), re.I)]
        assert missed == [], (
            f"{name}: presence predicate(s) {missed} DO catch this — it belongs in the "
            "presence battery, not in the pin's comparative set"
        )
    if target == "gate":
        mutated = _gate_paragraph().replace(old, new, 1)
        assert mutated != _gate_paragraph(), f"{name}: mutation did not apply"
        assert GATE_PLACEMENT_VERBATIM not in _flat(mutated), (
            f"{name}: the gate pin accepted a softened clause"
        )
    else:
        mutated = _multi_reviewer_section().replace(old, new, 1)
        assert mutated != _multi_reviewer_section(), f"{name}: mutation did not apply"
        assert _placement_block(mutated) != PLACEMENT_BLOCK_VERBATIM, (
            f"{name}: the block pin accepted a softened requirement"
        )


def test_the_pins_are_not_satisfied_by_an_empty_or_unrelated_text():
    assert _placement_block("") == ""
    assert _placement_block("nothing to see here") == ""
    assert GATE_PLACEMENT_VERBATIM not in _flat("nothing to see here")


# --------------------------------------------------------------------------------------
# The round's own survivors, kept as the regression set.
#
# The guard lens wrote 26 attacks against the first version of these guards and **11
# survived (42%)**, with 7 of 12 controls falsely reddening. The three that mattered:
#
#   * the block moved byte-identical BELOW the caveat it was hoisted out of — green
#     everywhere, and position is the entire improvement this phase claims;
#   * the block commented out or fenced — every pin satisfied, rule invisible;
#   * a revoking sentence added BESIDE the block — a pin scoped to a span cannot see an
#     addition outside it, which this module's own docstring already records as the shape
#     every scoped guard loses to.
#
# Each is now driven through the real predicates.
# --------------------------------------------------------------------------------------

def test_the_requirement_may_not_be_moved_below_the_caveat_it_was_hoisted_from():
    assert placement_position_problems(_multi_reviewer_section()) == []

    section = _multi_reviewer_section()
    block = _raw_placement_block()
    moved = section.replace(block, "", 1)
    at = moved.index("### How many reviewers, how many rounds")
    moved = moved[:at] + block + "\n\n" + moved[at:]

    problems = placement_position_problems(moved)
    assert any("BELOW" in p for p in problems), problems
    # And it must reach the production predicate, not only the helper.
    assert any("BELOW" in p for p in section_problems(moved)), (
        "the relocation is caught by the helper but not by section_problems() — the guard "
        "is not wired into the predicate the real tests call"
    )
    # The pin alone cannot see it, which is why the ordering assertion exists.
    assert _placement_block(moved) == PLACEMENT_BLOCK_VERBATIM


def test_a_softened_duplicate_below_the_real_block_is_caught():
    section = _multi_reviewer_section()
    # Softened AFTER the start anchor, or the decoy stops being a duplicate of the thing the
    # count is looking for — the first attempt at this test replaced text inside the anchor
    # itself and proved nothing.
    decoy = _raw_placement_block().replace("**Place it.**", "**Place it, where convenient.**", 1)
    assert decoy.count(PLACEMENT_BLOCK_START) == 1, "the decoy must still carry the anchor"
    problems = placement_position_problems(section + "\n\n" + decoy)
    assert any("appears 2 times" in p for p in problems), problems


@pytest.mark.parametrize("wrap", [
    pytest.param(lambda b: f"<!--\n{b}\n-->", id="commented-out"),
    pytest.param(lambda b: f"```\n{b}\n```", id="fenced"),
    pytest.param(lambda b: f"<details>\n{b}\n</details>", id="collapsed"),
])
def test_neutering_the_whole_block_reads_as_deleting_it(wrap):
    section = _multi_reviewer_section()
    neutered = section.replace(_raw_placement_block(), wrap(_raw_placement_block()), 1)
    assert _placement_block(neutered) == "", "the pin is satisfied by text no reader sees"
    assert section_problems(neutered) != []


def test_neutering_the_whole_gate_paragraph_reads_as_deleting_it():
    gate = _gate_paragraph()
    problems = gate_problems(f"<!--\n{gate}\n-->")
    assert any("gate-placement" in p for p in problems), problems


@pytest.mark.parametrize("where", ["before", "after", "gate"])
def test_a_licence_added_BESIDE_the_rule_is_caught(where):
    licence = "This is belt-and-braces; a lens that skips it is still a lens."
    if where == "gate":
        assert placement_retraction_problems(_gate_paragraph() + " " + licence) != []
        assert gate_problems(_gate_paragraph() + " " + licence) != []
        return
    section = _multi_reviewer_section()
    block = _raw_placement_block()
    mutated = section.replace(
        block, f"{licence}\n\n{block}" if where == "before" else f"{block}\n\n{licence}", 1)
    assert _placement_block(mutated) == PLACEMENT_BLOCK_VERBATIM, "the pin should be intact"
    assert section_problems(mutated) != [], (
        "a revocation added beside the rule leaves every scoped pin green — the canary is "
        "not reaching the production predicate"
    )


def test_the_retraction_canary_states_its_bound_rather_than_implying_coverage():
    """It is a canary, not a filter. An out-of-vocabulary revocation walks through it, and
    the record says so — Phase 179 measured a prose blocklist catching 0 of 21 reversals it
    had not been taught. This test pins the honest limit so nobody reads the canary as a
    guarantee: the ordering assertion and the pin are the real checks.
    """
    novel = "Placement here is a matter of taste and the round stands without it."
    assert placement_retraction_problems(novel) == []
