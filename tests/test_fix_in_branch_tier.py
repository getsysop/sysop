"""Drift guards for the fix-in-branch tier (Phase 276, `Q-410` + brief section G).

The tier is one rule stated in three prompt bodies, recorded by one new task-body
heading, and enforced at one gate. Every one of those five places can be edited
independently, and section G's whole argument is that the *bound* is the design:
    "Dropped in the name of throughput, tier 1 becomes a source of defects rather
     than a sink for tasks."
So these guards are aimed at the bound, not at the prose around it. A guard that
only checks the heading exists would go green on a tier that had quietly lost its
never-list, which is the exact failure mode section G names.

Two deliberate negative guards live here as well:

* `test_validator_gains_no_also_fixed_invariant` pins a *decision not to build*.
  The brief costed a warn-only validator invariant on the Phase 58b precedent;
  Phase 234 had already retired that precedent, and `tasks/schema.md` argues
  against reviving it for both of the reasons that apply to `## Also fixed` at
  once. A future author reading only the brief would add it back. This fails when
  they do.
* `test_also_fixed_arm_is_not_silenced_by_the_doc_only_skip` pins the one thing
  the arm gets wrong if it is written carelessly: Step 2d's doc-only skip would
  otherwise silence it on precisely the branches most likely to carry a tier-1
  doc fix.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from _reversal import assert_no_reversal, slice_between

REPO_ROOT = Path(__file__).resolve().parent.parent

CLAIM = REPO_ROOT / "core" / "skills" / "claim-task" / "SKILL.md"
BUILD = REPO_ROOT / "core" / "skills" / "auto-build" / "SKILL.md"
DOCWORK = REPO_ROOT / "core" / "skills" / "document-work" / "SKILL.md"
CLOSE = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"
JUDGE = REPO_ROOT / "core" / "skills" / "auto-judge" / "SKILL.md"
FIX = REPO_ROOT / "core" / "skills" / "auto-fix" / "SKILL.md"
SCHEMA = REPO_ROOT / "core" / "companion" / "tasks" / "schema.md"
VALIDATOR = REPO_ROOT / "core" / "companion" / "scripts" / "validate_tasks.py"
BASELINE = REPO_ROOT / "tools" / "FIX_IN_BRANCH_BASELINE.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

# The three sites an executor actually reads. document-work is here because it is
# also invoked directly, outside either executor, and it is the site that *decides*
# to file -- Step 3b only verifies that an already-named follow-up exists.
TIER_SITES = [
    pytest.param(CLAIM, id="claim-task"),
    pytest.param(BUILD, id="auto-build"),
    pytest.param(DOCWORK, id="document-work"),
]


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")

def live_prose(text: str, start: str, end: str, name: str) -> str:
    """A slice with fenced blocks and blockquotes REMOVED.

    Phase 280's round walked twelve mutations through `needle in slice` checks, and
    the two cheapest did not touch the live text at all: gut the rules, then park
    every pinned needle in a `> **Superseded drafting note**` blockquote, or inside a
    ```text fence labelled "a rule this step does NOT follow". Both are legal Markdown
    that a reader plainly does not execute, and both left every pin green.

    So a needle only counts where an executing reader would actually meet it.
    """
    block = slice_between(text, start, end, name)
    out, fenced = [], False
    for ln in block.split("\n"):
        s = ln.strip()
        if s.startswith("```") or s.startswith("~~~"):
            fenced = not fenced
            continue
        if fenced or s.startswith(">"):
            continue
        out.append(ln)
    return "\n".join(out)



def require_maintainer_side(p: Path) -> str:
    """Read a mirror-excluded file, or skip.

    `CLAUDE.md`, `tools/FIX_IN_BRANCH_BASELINE.md` and `tools/baselines/` are all
    stripped from the public snapshot (`tools/` never ships). On that tree these
    files are absent through no fault of anyone who can see it, and the snapshot
    runs the same required `pytest` check -- so a hard read here reddens a repo
    nobody can fix from. Per tests/test_mirror_skip_discipline.py's rule, skip.
    """
    if not p.is_file():
        pytest.skip(f"{p.name} is mirror-excluded and absent on this tree")
    return p.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# The bound itself
# --------------------------------------------------------------------------

# Every conjunct of tier 1. Section G states these as a conjunction ("when *all*
# of these hold"), so losing any one of them widens the tier -- which is why they
# are pinned individually rather than as one blob of prose.
TIER_1_CONJUNCTS = {
    "same module": r"file or module th\w+ (?:task|work) already touches",
    "mechanical or doc/test/config": r"mechanical, or a doc, test, or convention-config correction",
    "gated or tested": r"existing gate already covers it, or you add the test that does",
    "small": r"on the order of 20 lines",
    "few per branch": r"no more than a few per branch",
    "not an unverified meaning claim": r"not a claim about what the code means that you have not verified",
}

# The categories excluded at any size. Section G calls these "Never in tier 1
# regardless of size" -- a size-based reading of them is the failure this pins.
NEVER_LIST = ["migration", "prompt", "auth", "money-path", "security", "production"]


@pytest.mark.parametrize("path", TIER_SITES)
@pytest.mark.parametrize("label,pattern", sorted(TIER_1_CONJUNCTS.items()))
def test_tier_1_keeps_every_conjunct(path: Path, label: str, pattern: str) -> None:
    """Tier 1 is a conjunction; dropping one conjunct silently widens it."""
    assert re.search(pattern, read(path)), (
        f"{path.name} no longer states the tier-1 conjunct {label!r} "
        f"(pattern {pattern!r}). Tier 1 is licensed only when ALL conjuncts hold; "
        "removing one widens the tier, which brief section G names as the way tier 1 "
        "becomes a source of defects rather than a sink for tasks."
    )


@pytest.mark.parametrize("path", TIER_SITES)
def test_never_list_is_stated_and_is_not_size_qualified(path: Path) -> None:
    """The never-list excludes by category, not by size."""
    text = read(path)
    # Bounded by the SENTENCE, not by a character window. The round measured 109
    # characters of slack past the last required category in the first cut and used it
    # to append "-- unless the change is a typo or a comment." inside the window.
    m = re.search(
        r"\*\*Never tier 1, at any size:\*\*(.*?writes to production[^.]*\.)", text, re.S
    )
    assert m, (
        f"{path.name} lost the never-tier-1 list, or its 'at any size' qualifier. "
        "These categories are excluded by category rather than by size -- a small, "
        "correct fix to a migration or an auth path is still a task."
    )
    clause = m.group(1).lower()
    missing = [c for c in NEVER_LIST if c not in clause]
    assert not missing, f"{path.name}: never-list lost {missing}"
    # An exception appended to the list is the same defect as deleting a category.
    # Phrases, not bare tokens. A first cut listed "except" and false-killed
    # document-work's legitimate "the one further exception to the do-not-modify rule",
    # which is about a different rule entirely -- over-strictness is a defect too, and
    # a guard that reddens on correct prose is the shape that teaches the next author
    # to delete it.
    for escape in ("unless the", "though a one-line", "except when", "use judgment", "is fine"):
        assert escape not in clause, (
            f"{path.name}: the never-list carries an escape clause ({escape!r}). These "
            "categories are excluded by CATEGORY, not by size or judgment -- a correct "
            "one-line fix to a migration is still a task."
        )


@pytest.mark.parametrize("path", TIER_SITES)
def test_all_three_tiers_are_present_and_ordered(path: Path) -> None:
    """Filing is tier 3. A site that lost tiers 1-2 has filing as the default again."""
    text = read(path)
    fix_at = text.find("**Fix it in this branch**")
    extend_at = text.find("**Extend an existing open task**")
    file_at = text.find("**File a new task**")
    assert -1 not in (fix_at, extend_at, file_at), (
        f"{path.name} is missing one of the three tiers "
        f"(fix={fix_at}, extend={extend_at}, file={file_at})."
    )
    assert fix_at < extend_at < file_at, (
        f"{path.name}: tiers are out of order. They are an ordered fallthrough -- "
        "'take the first that fits' -- so order is the rule, not presentation."
    )
    # Position order alone is not enough: a renumbered list marker ("9." for tier 2)
    # leaves every position intact while telling the reader a different sequence.
    # The executor reads this prompt as text, so the visible numbering is the rule
    # it follows. Found by this phase's own mutation battery (M05 survived without
    # this half).
    markers = [
        text[text.rfind("\n", 0, at) + 1:at].strip()
        for at in (fix_at, extend_at, file_at)
    ]
    # DECIDED, not accidental: the markdown `1. / 1. / 1.` auto-numbering idiom is
    # rejected here even though every renderer displays 1-2-3. These files are read as
    # RAW TEXT by the agent that has to obey them -- nothing renders them first -- so
    # three literal `1.`s state three first-choices. The round flagged this as a
    # possible false-kill and asked for it to be a decision; this is the decision.
    assert markers == ["1.", "2.", "3."], (
        f"{path.name}: the three tiers are positioned correctly but numbered "
        f"{markers!r}. An executor reads the numeral, not the byte offset."
    )


# The tier block's own bounds, per site: (start anchor, end anchor). Sliced rather
# than read whole, because every assertion below is about THIS rule and a file-wide
# read is what let a mutation satisfy a guard from an unrelated mention elsewhere.
TIER_BLOCKS = {
    "claim-task": (CLAIM, "Three tiers; take the first that fits.", "\n3. **Persist the `## Test decision`**"),
    # Re-anchored by Phase 277 from "\n4. **Post-fix convention verification**" to the
    # record item it now precedes. Phase 277 inserted `3-record` between the tier block
    # and item 4, so the old anchor silently widened this slice to cover an item that is
    # not the tier -- exactly what slicing exists to prevent, and the reversal screens
    # below would then have been reading prose they were never scoped to. This also makes
    # the two executor sites parallel: claim-task's anchor is already its record item.
    "auto-build": (BUILD, "Three tiers; take the first that fits.", "\n3‑record. **Persist the `## Test decision`**"),
    "document-work": (DOCWORK, "Three tiers; take the first that fits.", "\nTiers 1 and 2 put no"),
}


def tier_block(name: str) -> str:
    path, start, end = TIER_BLOCKS[name]
    return slice_between(read(path), start, end, f"{name} tier block")


@pytest.mark.parametrize("name", sorted(TIER_BLOCKS))
def test_the_tier_block_carries_no_reversal_vocabulary(name: str) -> None:
    """The layer that presence checks cannot replace.

    Wired here by the round, which wrote 64 mutations against the first cut of this
    module and watched 51 survive. Roughly twenty of those were one move: leave every
    string the guards grep for byte-perfect, and add a sentence beside it that cancels
    it -- "In practice these bounds are advisory", "For most follow-ups filing remains
    the right first move", "filing is never wrong". A presence check cannot see that
    by construction. Step 2d has carried this layer since Phase 249 and the round's
    equivalent mutation there was killed; the three files an executor actually reads
    had none.

    `extra` holds softenings specific to THIS rule -- a reversal of the tier that
    would be noise in any other step.
    """
    block = tier_block(name)
    assert_no_reversal(
        block,
        f"{name} tier block",
        extra=(
            "filing is never wrong",
            "prefer this one",
            "use judgment",
            "rough guide",
            "counts as verification",
            "leave it alone",
            "whichever fits best",
            "if you like",
            "the diff speaks for itself",
            "anywhere convenient",
            "remains the right first move",
            "in the ordinary case, file",
            "file first",
            "a quick skim",
            "always safe",
            "whenever you are unsure",
            "would consider adjacent",
            "take 1 —",
            # Phase 278. The bar decays by WIDENING as readily as by deletion: a fifth
            # "legal answer" phrased as judgment accepts every follow-up and leaves
            # each pinned answer byte-perfect. The author-side battery walked the
            # first cut of the bar with exactly this.
            "at your discretion",
            "anything you judge",
            "worth filing",
            "if it seems important",
            "may go to",
            "you may still file",
        ),
    )


@pytest.mark.parametrize("name", sorted(TIER_BLOCKS))
def test_the_tie_break_favours_filing(name: str) -> None:
    """Between tiers 1 and 2, take 2. Inverting one digit inverts the safety margin."""
    block = tier_block(name)
    assert "When you are between tiers 1 and 2, take 2" in block, (
        f"{name}: the tie-break no longer favours the safer tier. `take 1` resolves every "
        "borderline case into an in-branch fix, which is precisely the drift section G "
        "says turns tier 1 into a source of defects."
    )


@pytest.mark.parametrize(
    "path,start,end,name",
    [
        pytest.param(CLAIM, "- Do **NOT** flip `status:` fields", "- Do **NOT** push to origin",
                     "claim-task filing demotion", id="claim-task"),
        pytest.param(BUILD, "- ADDING a new task entry", "\n\n", "auto-build filing demotion", id="auto-build"),
        pytest.param(DOCWORK, "**Before filing one, take the tiers in order**",
                     "\n1. **Fix it in this branch**", "document-work filing demotion", id="document-work"),
    ],
)
def test_the_filing_demotion_is_not_re_softened(path: Path, start: str, end: str, name: str) -> None:
    """The demotion sentence sits OUTSIDE the tier block and needed its own layer.

    The round appended "For most follow-ups filing remains the right first move" and
    "In the ordinary case, file." to these sentences. Both restore filing as the
    default -- the exact behaviour `Q-410` was filed against -- while every guard over
    the tier block itself stayed green, because the sentence is not in that block.
    """
    block = slice_between(read(path), start, end, name)
    assert_no_reversal(
        block, name,
        extra=("remains the right first move", "in the ordinary case, file",
               "file first", "filing is never wrong", "usually the right"),
    )


@pytest.mark.parametrize("name", sorted(TIER_BLOCKS))
def test_tier_1_is_a_conjunction(name: str) -> None:
    """`all` is the single word the whole tier rests on, and no other pattern held it.

    The round's sharpest mutation: `when **all** of these hold` -> `when **any** of
    these hold`. Six conjuncts become six independent licences -- "it is small" alone
    would authorise an unverified meaning claim in a migration. Every one of this
    module's conjunct patterns stayed green, because each pins its own clause and none
    pinned the quantifier joining them.
    """
    block = tier_block(name)
    assert "when **all** of these hold" in block, (
        f"{name}: tier 1 is no longer stated as a conjunction. It is licensed only when "
        "ALL conjuncts hold; `any` turns each bound into an independent permission and "
        "guts the rule while leaving every conjunct guard green."
    )
    assert "**any** of these hold" not in block, f"{name}: tier 1 reads as a disjunction"


@pytest.mark.parametrize("name", sorted(TIER_BLOCKS))
def test_the_bound_is_the_design_paragraph_survives(name: str) -> None:
    """Section G's argument, deletable from two of three sites with the suite green."""
    block = tier_block(name)
    assert "The bound is the design, not a formality." in block, (
        f"{name}: the paragraph carrying the tier's whole rationale is gone. It is the "
        "text this module's own docstring quotes as the reason these guards exist, and "
        "the round deleted it from two sites without reddening anything."
    )
    assert "source of defects rather than a sink for tasks" in block, (
        f"{name}: the consequence clause is gone -- the half that says what happens when "
        "the bound is dropped for throughput."
    )


@pytest.mark.parametrize("name", sorted(TIER_BLOCKS))
def test_the_selection_rule_is_first_match_not_best_match(name: str) -> None:
    """Order is enforced by position, numeral AND selection rule.

    The round found a third way past the first two: leave positions and numerals
    intact and change `take the first that fits` to `take whichever fits best`, or
    append `When two tiers both fit, prefer this one` inside tier 3. Both tell the
    executor the opposite sequence with the structural guards green.
    """
    block = tier_block(name)
    assert "take the first that fits" in block, (
        f"{name}: the tiers are no longer a first-match fallthrough. `whichever fits "
        "best` makes the ordering advisory while leaving the 1./2./3. markers intact."
    )


@pytest.mark.parametrize("name", sorted(TIER_BLOCKS))
def test_tier_1_records_under_also_fixed(name: str) -> None:
    """A tier-1 fix with no record is indistinguishable from unplanned scope.

    Read inside the tier block. File-wide, this was satisfied by an incidental
    mention elsewhere in the same file -- which is how the round renamed the heading
    to `## Adjacent fixes` in document-work's tier text and stayed green, and how the
    collapsed spans in claim-task's item 3 passed unnoticed.
    """
    path = TIER_BLOCKS[name][0]
    block = tier_block(name)
    assert "`## Also fixed`" in block, (
        f"{path.name} no longer tells the executor to record the fix under "
        "`## Also fixed`. Without the record, /review-close Step 2a sees a diff hunk "
        "the task body does not explain -- correctly a finding."
    )


@pytest.mark.parametrize(
    "path,ordering_site",
    [
        pytest.param(CLAIM, "Sequence item 3's body write", id="claim-task"),
        pytest.param(BUILD, "Sequence item 3b's tier 1", id="auto-build"),
    ],
)
def test_the_placement_rule_names_both_neighbouring_headings(path: Path, ordering_site: str) -> None:
    """The ordering clause must survive, spans intact.

    Phase 276 shipped this sentence into claim-task with three backtick spans EATEN
    by an unquoted heredoc -- `## Also fixed`, `## Test decision` and `## Plan` each
    began with `#`, so the shell ran them as command substitutions, `#` opened a
    comment, and each returned empty. The executor was left being told to "write ␣"
    and to place it "after ␣ and before any ␣ section". The Phase 188 class, at the
    one site the whole tier hangs off.

    `test_tier_1_records_under_also_fixed` was GREEN over it, because item 2b's
    surviving mention of the heading satisfied it. That guard proves wiring; this one
    proves the sentence. Keyed to the ordering clause specifically, since that is what
    the eaten spans destroyed and what no other guard reads.
    """
    text = read(path)
    assert "`## Test decision`" in text and "`## Plan`" in text, (
        f"{path.name}: the ordering clause at {ordering_site} no longer names both "
        "neighbouring headings with their backticks intact. If you edited this file "
        "through an UNQUOTED heredoc, check for eaten spans -- a `#`-leading backtick "
        "span becomes a command substitution and then a comment, and vanishes silently."
    )
    m = re.search(r"placed after [^.]*?`## Test decision`[^.]*?`## Plan` section", text)
    assert m, (
        f"{path.name}: the placement rule no longer reads 'placed after … "
        "`## Test decision` … before any `## Plan` section'. The order is load-bearing: "
        "the plan section is a fenced block that can quote either heading, so a "
        "first-match heading reader must meet the real section first."
    )


@pytest.mark.parametrize("path", TIER_SITES)
def test_the_gate_weakening_backstop_is_present(path: Path) -> None:
    """Tier 1's own predicate is self-satisfying for a gate-disarming edit.

    "An existing gate already covers it" is satisfied BY the disarming change when the
    change is what stops the gate firing -- so narrowing a semgrep rule, adding a
    checks.yml exclusion, widening an allowlist or lowering a numeric bound qualified
    for tier 1 AND self-certified. This repo has shipped that failure twice already
    (Phase 196's ignore list that ate the test tree; Phase 205's escape hatch that
    nullified the check). The backstop is stated as a property of the CHANGE rather
    than a file list, because an enumeration rots.
    """
    text = read(path)
    assert "weaken, disarm, narrow or delete a gate" in text, (
        f"{path.name} lost the gate-weakening backstop. Without it, tier 1 admits an "
        "edit that disarms the very gate its own predicate points at."
    )
    assert "satisfied by the disarming edit itself" in text, (
        f"{path.name} states the backstop but not the reason it is needed. The reason "
        "is the load-bearing part: a reader who does not see WHY tier 1's predicate is "
        "self-satisfying here will treat the backstop as belt-and-braces and drop it."
    )


# --------------------------------------------------------------------------
# Filing is no longer the default at the sites that used to say it was
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path,marker",
    [
        pytest.param(CLAIM, "it is **tier 3**, not the default", id="claim-task"),
        pytest.param(BUILD, "**tier 3**, not the default", id="auto-build"),
        pytest.param(DOCWORK, "filing is tier 3, not the default", id="document-work"),
    ],
)
def test_filing_is_demoted_to_tier_3(path: Path, marker: str) -> None:
    """Each site's pre-existing 'filing IS allowed and expected' now routes via the tiers."""
    assert marker in read(path), (
        f"{path.name} lost the sentence demoting filing to tier 3. The shipped text "
        "before Phase 276 read 'IS allowed and expected', which makes filing the "
        "default -- the exact behaviour Q-410 was filed against."
    )


def test_document_work_step_3b_is_named_as_a_tier_3_gate() -> None:
    """Step 3b cannot see a tier-1 fix, and must not be relied on as if it could."""
    text = read(DOCWORK)
    assert "that gate is a tier-3 gate" in text, (
        "document-work no longer states that Step 3b is a tier-3 gate. Step 3b fires "
        "on <PREFIX>-<NAME> tokens in pending-docs prose; tiers 1 and 2 emit none, so "
        "a reader who takes it as the backstop for in-branch fixes is wrong by "
        "construction."
    )


# --------------------------------------------------------------------------
# The schema
# --------------------------------------------------------------------------

def test_also_fixed_is_declared_in_the_body_layout() -> None:
    assert re.search(r"^## Also fixed$", read(SCHEMA), re.M), (
        "tasks/schema.md no longer declares `## Also fixed` in the per-task body layout."
    )


def test_also_fixed_is_ordered_before_plan() -> None:
    """Same hazard `## Test decision` is ordered around: a fence can quote the heading."""
    text = read(SCHEMA)
    fence = re.search(r"```markdown\n# FEAT-EXAMPLE\n(.*?)```", text, re.S)
    assert fence, "the per-task body layout fence moved or changed shape"
    body = fence.group(1)
    also = body.find("## Also fixed")
    plan = body.find("## Plan")
    assert also != -1 and plan != -1, (also, plan)
    assert also < plan, (
        "`## Also fixed` must be ordered BEFORE `## Plan` in the body layout. The "
        "plan section is a fenced block that can quote either heading, so a "
        "first-match heading reader has to meet the real section first -- the same "
        "reason `## Test decision` sits where it does."
    )


def test_the_schema_section_carries_no_reversal_vocabulary() -> None:
    """The copy a body author reads, guarded like the executors' copies.

    The round turned "match this heading by **search, not equality**" into "by exact
    equality" -- inverting the one requirement the pre-existing `(PR N)` headings make
    non-negotiable -- and appended "a warn-only version is still worth building and
    should be added" directly to the paragraph refusing the validator invariant. Both
    survived: every guard here read the executors' files or a fixed phrase.
    """
    section = slice_between(read(SCHEMA), "### Also fixed", "### User ops", "schema Also fixed section")
    assert "**search, not equality**" in section, (
        "tasks/schema.md no longer requires a search match. `## Also fixed (PR 1)` is a "
        "real heading in a live corpus; equality misses it silently."
    )
    assert_no_reversal(
        section, "schema § Also fixed",
        extra=("still worth building", "should be added", "exact equality",
               "enforced nowhere", "may look", "nowhere automatically"),
    )


def test_schema_states_both_reasons_for_no_invariant() -> None:
    """One reason alone would not settle it; the section is refused for both."""
    text = read(SCHEMA)
    m = re.search(
        r"\*\*The validator does not check this, and will not\*\*, for both of the reasons(.{0,900})",
        text, re.S,
    )
    assert m, "tasks/schema.md lost the paragraph refusing an `## Also fixed` invariant"
    body = m.group(1)
    assert "inside the worktree" in body, "lost the branch-visibility reason"
    assert "optional by design" in body, "lost the optionality reason"


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------

def test_review_close_carries_the_also_fixed_arm() -> None:
    assert "The `## Also fixed` arm" in read(CLOSE), (
        "/review-close lost the `## Also fixed` arm. Step 2d is the only gate that "
        "reads the branch tip, so it is the only place the record can be checked at all."
    )


@pytest.mark.parametrize(
    "label,needle",
    [
        ("paths are in the diff", "Every path a line names is in the diff"),
        ("never-list is checked", "No line names a never-tier-1 path"),
        ("count is bounded", "The count is small"),
    ],
)
def test_also_fixed_arm_checks_all_three_things(label: str, needle: str) -> None:
    assert needle in read(CLOSE), (
        f"the `## Also fixed` arm lost its {label!r} check. A record nobody verifies "
        "against the diff is a record that can assert a fix that never happened."
    )


def test_also_fixed_arm_treats_absence_as_normal() -> None:
    """The opposite of the test-decision arm above it, and easy to get backwards."""
    text = read(CLOSE)
    assert "Absence is never a finding here" in text, (
        "the `## Also fixed` arm no longer states that absence is not a finding. The "
        "section is optional; most branches carry no adjacent fix. Carrying the "
        "test-decision arm's `missing` halt across would fire on nearly every branch."
    )


def test_also_fixed_arm_is_not_silenced_by_the_doc_only_skip() -> None:
    """The skip is scoped to test-decision verification, and must stay scoped."""
    text = read(CLOSE)
    assert "including a task item 0\n       skipped" in text.replace("\n", "\n       ") or "including a task item 0 skipped" in text, (
        "the `## Also fixed` arm no longer overrides Step 2d's doc-only skip. That "
        "skip exists because a docs branch carrying `no test because Z` needs no test "
        "hunt; applied to this arm it would silence it on exactly the branches most "
        "likely to carry a tier-1 fix, since a doc correction is the archetypal one."
    )


def test_the_arm_names_the_pattern_it_actually_matches_on() -> None:
    """Writer and reader can drift apart with every prose guard green.

    The round renamed the heading in document-work's tier text to `## Adjacent fixes`
    and renamed the arm's pattern to `adjacent\\s+fixes`, independently, and nothing
    reddened: one guard pinned the arm's LABEL, another pinned the prose ABOUT the
    match. Neither read the regex the arm tells a reviewer to use.
    """
    arm = slice_between(read(CLOSE), "**2\u2011also. The `## Also fixed` arm", "**3. On a clean match", "2-also arm")
    assert r"`also\s+fixed`" in arm, (
        "the `## Also fixed` arm no longer names the pattern `also\\s+fixed`. If the "
        "arm's pattern and the heading the executors are told to write drift apart, "
        "the arm reads every branch as carrying no record -- and its absence branch is "
        "silent by design, so the drift never surfaces."
    )


def test_the_arm_matches_the_heading_by_search_not_equality() -> None:
    """`## Also fixed (PR 1)` is a real heading in a live consumer corpus.

    Found by this phase's author-side rule-4 pass, which greps the real artefact
    rather than a fixture: gdp-query-system carried eight of these headings across
    seven bodies before the rule existed, two of them with a `(PR N)` suffix. An
    arm written to compare the heading for equality would silently miss those.
    """
    text = read(CLOSE)
    assert "**search, not an equality test**" in text, (
        "the `## Also fixed` arm no longer states that the heading match is a search. "
        "A live consumer corpus carries `## Also fixed (PR 1)`; equality misses it, and "
        "the arm's absence branch is silent, so the miss would never surface."
    )


def test_the_arm_judges_against_the_bound_in_force_not_todays() -> None:
    """A changing convention is judged as of the claim, and the false carve-out stays gone.

    An earlier draft granted a waiver on the ground that the heading "predated any
    rule". The round showed that backwards: the consumer's own copy of this tier
    landed two days before its first `## Also fixed`, so every existing section was
    written under a bound. The waiver's effect would have been a SECOND silencer on
    an arm whose other branch is already silent by design.
    """
    text = read(CLOSE)
    assert "Judge a section against the bound in force when its branch was claimed" in text, (
        "the `## Also fixed` arm lost its as-of-claim rule for a changing convention."
    )
    assert "A section that predates this rule is not a finding." not in text, (
        "the false pre-rule carve-out is back. Its stated ground -- that the heading "
        "predated any rule -- was refuted by timestamps: the tier reached the consumer "
        "two days before the first heading appeared there."
    )


def test_schema_refuses_the_corroboration_reading_of_the_eight_headings() -> None:
    """The eight pre-existing headings are the rule's output, not evidence for it.

    The next reader meets the same eight headings and makes the same inference this
    phase made -- that a convention emerged independently and therefore had demand.
    The timestamps say otherwise: the tier reached that consumer's CLAUDE.md two days
    before its first heading appeared. The schema has to say so, or the false reading
    regenerates from the same data.
    """
    text = read(SCHEMA)
    assert "already in use before it was written down here" in text, (
        "tasks/schema.md no longer records that `## Also fixed` was in use before this "
        "section declared it. That fact is what makes the search-not-equality rule "
        "non-arbitrary."
    )
    assert "not independent corroboration and must not be read as any" in text, (
        "tasks/schema.md no longer refuses the corroboration reading of the eight "
        "pre-existing headings. Phase 276 made exactly that inference and shipped it "
        "as 'the strongest evidence the design is right'; the round refuted it with "
        "one timestamp query. Without this sentence the next reader repeats it."
    )


def test_the_arm_carries_no_reversal_vocabulary() -> None:
    """Every check in the arm can be preserved verbatim and cancelled by the next sentence.

    The round wrote eleven such mutations against the arm and all eleven survived: the
    doc-only override kept its needle while the following sentence said the skip DOES
    carry; check 1 kept its wording and became "informational"; the halt became "noted
    for Step 8 and does not join item 3's halt". Step 2d as a whole has carried this
    layer since Phase 249 -- but the arm is sliced out of it here so the failure names
    the arm rather than the step.
    """
    arm = slice_between(read(CLOSE), "**2\u2011also. The `## Also fixed` arm", "**3. On a clean match", "2-also arm")
    assert_no_reversal(
        arm,
        "review-close 2-also arm",
        exempt=(
            "The section is optional by design (`tasks/schema.md` § *Also fixed*)",
        ),
        extra=(
            "informational",
            "does not join item 3's halt",
            "prompt for judgment",
            "do not raise a finding",
            "when time allows",
            "carries here too",
            "fold it into the test-decision totals",
            "prefer \"waive\" over \"hold for fix\"",
            "apply checks 2 and 3 to every section regardless",
            "in spirit",
            "unless the diff shows hunks",
            "raise it as `missing`",
            # Phase 280. Its battery kept every pinned needle in check 3 and added
            # "judging each section's alone is equally valid" beside it -- restoring
            # the per-section reading that undercounts the section-G number.
            "equally valid",
        ),
    )


def test_the_schema_never_list_is_complete() -> None:
    """The list a consumer reads when authoring a body, guarded like the executors'.

    NEVER_LIST was checked only in the three skill files. The round gutted
    `tasks/schema.md`'s own never-list to two categories with nothing red -- and that
    is the copy a human authoring a task body actually reads.
    """
    text = read(SCHEMA)
    m = re.search(r"\*\*What may never go in it,\*\* at any size:(.*?)\n\n", text, re.S)
    assert m, "tasks/schema.md lost its `What may never go in it` never-list"
    clause = m.group(1).lower()
    missing = [c for c in NEVER_LIST if c not in clause]
    assert not missing, (
        f"tasks/schema.md's never-list lost {missing}. This is the copy a body author "
        "reads; the executors' three copies are guarded separately and cannot cover it."
    )
    assert "outside the tier by category, not by size" in text, (
        "tasks/schema.md no longer says the never-list excludes by CATEGORY. Without "
        "that, a correct one-line fix to a migration reads as admissible."
    )


@pytest.mark.parametrize(
    "path,start,end,name",
    [
        pytest.param(JUDGE, "**This is narrower than the fix-in-branch tier",
                     "</if>", "auto-judge reconciliation", id="auto-judge"),
        pytest.param(FIX, "These limits are **tighter than the fix-in-branch tier",
                     "**Report format**", "auto-fix reconciliation", id="auto-fix"),
    ],
)
def test_the_reconciliation_clauses_are_not_reversed(path: Path, start: str, end: str, name: str) -> None:
    """Both clauses say the shipped limit stays NARROWER. One sentence flips that.

    The round appended "Where the two could both apply, the tier wins" to auto-judge --
    flatly contradicting the shipped sentence two clauses later -- and turned auto-fix's
    "Do not read the tier as widening this scan" into "Read the tier as widening this
    scan where the fix is mechanical". Both left the guarded needles intact.
    """
    block = slice_between(read(path), start, end, name)
    assert_no_reversal(
        block, name,
        extra=("the tier wins", "as widening this scan where", "tier takes precedence"),
    )


def test_step_8_tallies_the_arm_separately() -> None:
    assert "Tally the `## Also fixed` arm separately" in read(CLOSE), (
        "Step 8 no longer tallies the arm. It is the tier's measurement surface as "
        "well as its gate: without the tally, a close where no branch carried the "
        "section reads identically to a close where nobody looked."
    )


# --------------------------------------------------------------------------
# The decision not to build a validator invariant
# --------------------------------------------------------------------------

def test_validator_gains_no_also_fixed_invariant(tmp_path: Path) -> None:
    """Pins a decision, not code -- and pins it on BEHAVIOUR, not on source text.

    Phase 58b shipped a warn-only body-heading invariant; Phase 234 retired it for
    reading the filesystem while the record lives on the branch. `## Also fixed`
    inherits that defect AND is optional, so a presence check cannot tell failure from
    the normal case either. An author following the brief rather than the tree would
    add it back.

    The first cut of this guard grepped the source for `also[_\\s-]*fixed`. The round
    defeated it with the shape a careful author is MOST likely to write -- a copy of
    this file's own live `_MANUAL_SMOKE_HEADING_RE` idiom, where `also` and `fixed` are
    separated by `\\s+` inside a regex literal and the character class never matches.
    Two more bypasses followed (a `[Aa]lso[ ]+fixed` class, implicit string
    concatenation). Grepping for an implementation is guessing at its spelling; running
    it is not. So: build a body with no `## Also fixed`, validate it, and assert
    nothing warns about the heading. Any implementation that warns on absence fails,
    however it is spelled.
    """
    import subprocess

    # Fixture shape taken from tests/test_validate_tasks.py::_VALID_INDEX -- the source
    # of truth for what this validator accepts -- not from my model of it. A fixture
    # built from memory proves only that the author is self-consistent, and the first
    # cut of this test used one: it produced four schema ERRORS and validated nothing.
    tasks = tmp_path / "tasks"
    (tasks / "open").mkdir(parents=True)
    (tasks / "open" / "FEAT-NO-ALSO.md").write_text(
        "# FEAT-NO-ALSO\n\n## Context\nNo adjacent fix was made on this branch.\n",
        encoding="utf-8",
    )
    (tasks / "index.yml").write_text(
        "schema_version: 1\n\n"
        "phases:\n"
        "  - number: 1\n"
        '    title: "Active phase"\n'
        "    status: in_progress\n"
        "    current_focus: true\n\n"
        "tasks:\n"
        "  - id: FEAT-NO-ALSO\n"
        '    title: "A task whose branch fixed nothing extra"\n'
        "    phase: 1\n"
        "    status: open\n"
        "    effort: Low\n"
        "    user_action: false\n"
        "    depends_on: []\n"
        "    surfaced_by: []\n"
        "    body: tasks/open/FEAT-NO-ALSO.md\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--path", str(tasks)],
        capture_output=True, text=True,
    )
    out = r.stdout + r.stderr

    # The fixture must be VALID, or this test asserts nothing about warnings.
    assert "0 errors" in out, (
        "the fixture no longer validates, so the warning assertion below is vacuous. "
        f"Rebuild it from tests/test_validate_tasks.py::_VALID_INDEX.\n{out}"
    )
    # Assert on the COUNT, not on wording. The round defeated a wording assertion with
    # a warning that said "body lacks the adjacent-fix heading" -- true to the defect,
    # and containing neither "also" nor "fixed". A count cannot be spelled around.
    assert "0 warnings" in out, (        f"validator output was:\n{r.stdout}\n{r.stderr}"
    )


# --------------------------------------------------------------------------
# Reconciliation with the two shipped scope-limit rules
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path,needle,why",
    [
        pytest.param(
            JUDGE, "This is narrower than the fix-in-branch tier and stays narrower on purpose.",
            "an architectural task's blast radius is the thing under review",
            id="auto-judge",
        ),
        pytest.param(
            FIX, "tighter than the fix-in-branch tier",
            "a sibling scan admits only the convention already being enforced",
            id="auto-fix",
        ),
    ],
)
def test_scope_limit_rules_state_their_relation_to_the_tier(path: Path, needle: str, why: str) -> None:
    """Two shipped rules restrict scope; without this, a reader gets two unrelated rules."""
    assert needle in read(path), (
        f"{path.name} no longer states how its scope limit relates to the "
        f"fix-in-branch tier ({why}). Both rules are live and one is narrower; a "
        "reader who meets them separately has no way to know which governs."
    )


# --------------------------------------------------------------------------
# The authoritative spec, which described the sequences this rule changed
# --------------------------------------------------------------------------

WORKFLOW = REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md"
GUIDE = REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW_GUIDE.md"


@pytest.mark.parametrize(
    "path,needle,why",
    [
        pytest.param(
            WORKFLOW, "fix-in-branch tier",
            "step 10 enumerates the Step 7e executor sequence and gained item 2b",
            id="workflow-executor",
        ),
        pytest.param(
            WORKFLOW, "`2\u2011also` arm",
            "the Step 2d bullet enumerates that step's verifications and gained an arm",
            id="workflow-2also",
        ),
        pytest.param(
            GUIDE, "Fix it in the branch before you file it.",
            "the guide's 'Record the test decision' section is the human-readable twin",
            id="guide",
        ),
    ],
)
def test_the_workflow_spec_describes_the_tier(path: Path, needle: str, why: str) -> None:
    """CLAUDE.md calls WORKFLOW.md the authoritative spec; it has to know about this.

    Found by the round, which derived the population from the tree instead of from
    this module's own TIER_SITES list. Both files enumerate, step by step, the two
    sequences this rule changed, and neither mentioned it. The repo has a standing
    class for exactly this -- Phase 145 backfilled § 8.4 for the same reason, and
    Phase 161 found three retired behaviours still documented as live.
    """
    assert needle in read(path), f"{path.name} does not describe the tier: {why}"


# --------------------------------------------------------------------------
# Sysop's own adoption, and the measurement
# --------------------------------------------------------------------------

def test_claude_md_carries_the_sysop_side_rule() -> None:
    """Shipping the skills does not change this repo; it closes phases inline."""
    text = require_maintainer_side(CLAUDE_MD)
    assert "**Fix-in-branch before filing (Phase 276).**" in text, (
        "CLAUDE.md lost the Sysop-side stanza. Sysop closes phases inline rather than "
        "through /claim-task + /review-close, so the shipped skill change does not "
        "apply here -- this stanza is the only thing that does."
    )
    m = re.search(r"\*\*Fix-in-branch before filing \(Phase 276\)\.\*\*(.*?)\n- \*\*", text, re.S)
    assert m, "the stanza's bounds could not be isolated"
    clause = m.group(1).lower()
    for cat in ("migration", "prompt", "security", "production", "weaken, disarm"):
        assert cat in clause, f"the Sysop-side never-list lost {cat!r}"
    assert "when *all* hold" in clause or "when *all* hold:" in m.group(1), (
        "CLAUDE.md's tier 1 is no longer a conjunction. `any` turns each bound into an "
        "independent licence."
    )
    assert_no_reversal(
        m.group(1), "CLAUDE.md fix-in-branch stanza",
        extra=("is a guideline", "fix what it sees", "when *any* hold"),
    )
    assert "phase_log.md" in clause, (
        "the stanza no longer names PHASE_LOG.md as the `## Also fixed` equivalent, "
        "which is the only in-repo record a Sysop phase's in-branch fix gets."
    )


def test_baseline_record_exists_and_states_the_tripwire() -> None:
    text = require_maintainer_side(BASELINE)
    assert "tripwire" in text.lower()
    assert "do not restate the gdp figures as sysop figures" in text.lower(), (
        "tools/FIX_IN_BRANCH_BASELINE.md lost the warning against restating GDP's "
        "numbers as Sysop's. The two denominators are different populations, and the "
        "brief's own review record caught an earlier revision doing exactly this."
    )


@pytest.mark.parametrize(
    "script",
    ["fix_in_branch_baseline_sysop.py", "fix_in_branch_baseline_consumer.py"],
)
def test_baseline_scripts_are_importable(script: str) -> None:
    """Section G says measure again after. A script that no longer parses cannot."""
    path = REPO_ROOT / "tools" / "baselines" / script
    if not path.is_file():
        pytest.skip(f"{script} lives under mirror-excluded tools/ and is absent here")
    r = subprocess.run(
        [sys.executable, "-c", f"compile(open({str(path)!r}).read(), {script!r}, 'exec')"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"{script} does not compile:\n{r.stderr}"


# --------------------------------------------------------------------------
# The filing bar -- `Q-410`'s other half (Phase 278)
# --------------------------------------------------------------------------
#
# Phase 276 shipped the three-tier fallthrough and left tier 3 filing
# unconditionally. `Q-410` asked for two things and only one arrived: a
# follow-up reaching tier 3 must NAME WHAT IT BLOCKS, or go to a ledger rather
# than the queue. These guards are aimed at the two ways that bar decays into
# nothing -- the naming test losing its legal answers (so nothing can satisfy
# it and everything is filed anyway, or so much satisfies it that it binds
# nothing), and the exemption list losing the entry that keeps defects out of
# the ledger.

ADDTASK = REPO_ROOT / "core" / "skills" / "add-task" / "SKILL.md"
TASKS_README = REPO_ROOT / "core" / "companion" / "tasks" / "README.md"
INSTALLER = REPO_ROOT / "install.sh"

# What a tier-3 filing may name. Four legal answers, and each one is a
# different project shape: a project mid-phase, a project with a plan, a
# project with declared gates, and a project whose queue is its own plan. Lose
# one and the bar refuses a shape of project it was written to serve -- which
# is how a bar gets deleted rather than fixed.
BAR_LEGAL_ANSWERS = {
    "the current phase": "`current_focus: true`",
    "a planned phase": "a named `planned` phase",
    "a declared gate": "a gate the project declares",
    "an open task's acceptance": "an open task whose stated acceptance this stops",
}

# Filed whatever the naming test says. The last entry is the load-bearing one:
# without it a bar that reads "name what it blocks" sends an unfilable BUG to a
# ledger, which is strictly worse than the unbounded filing it replaced.
#
# **Pinned as one contiguous run, not as four independent substrings**, and that
# is the author-side battery's doing: M10 deleted `a `user_action`;` from the
# exemption list and SURVIVED, because tier 3's own shipped line already reads
# "needs a `user_action`" a sentence earlier. A per-entry `in` check was marking
# a list with a hole in it compliant -- the "satisfied by an incidental use of
# that substring" failure the author-side pass names.
BAR_EXEMPTION_RUN = (
    "a design question or a call that is the human's; "
    "a `user_action`; "
    "a production write; "
    "and a defect in shipped behaviour **you can state as a falsifiable failure** — the input, "
    "the expected result, the actual one — or a security finding"
)
BAR_EXEMPTIONS = {
    "design question": "a design question or a call that is the human's",
    "user_action": "; a `user_action`; ",
    "production write": "a production write",
    "defect or security": "a defect in shipped behaviour **you can state as a falsifiable failure**",
}


@pytest.mark.parametrize("name", sorted(TIER_BLOCKS))
def test_the_filing_bar_lives_inside_the_reversal_screened_block(name: str) -> None:
    """The bar has to sit in the slice, not merely in the file.

    Every negative guard in this module reads `tier_block(name)`. A bar that
    drifts out of that slice -- moved below the record item, hoisted above the
    tier list -- keeps every presence check green while losing the reversal
    layer entirely, and the reversal layer is the one a mutation walks through.
    Assert the containment directly rather than trusting the placement.
    """
    assert "name what the filing blocks" in tier_block(name), (
        f"{name}: the tier-3 filing bar is outside the reversal-screened tier "
        "block. Presence checks still pass; nothing screens it for softening."
    )


@pytest.mark.parametrize("name", sorted(TIER_BLOCKS))
@pytest.mark.parametrize("label,needle", sorted(BAR_LEGAL_ANSWERS.items()))
def test_the_bar_keeps_every_legal_answer(name: str, label: str, needle: str) -> None:
    """Four ways to satisfy the naming test, one per project shape."""
    assert needle in tier_block(name), (
        f"{name}: the filing bar no longer accepts {label!r} as a thing a "
        f"follow-up can name ({needle!r} is gone). A bar whose only legal answer "
        "is the current phase refuses every project that plans further ahead "
        "than one phase, and a refused bar gets deleted rather than widened."
    )


@pytest.mark.parametrize("name", sorted(TIER_BLOCKS))
def test_the_exemption_list_is_intact_as_one_run(name: str) -> None:
    """The whole list, contiguously -- see BAR_EXEMPTION_RUN for why."""
    block = tier_block(name)
    assert BAR_EXEMPTION_RUN in block, (
        f"{name}: the exemption list is no longer intact. It is pinned as one run "
        "because three of its four entries appear elsewhere in the same block, so a "
        "deletion from the list leaves every per-entry substring check green."
    )
    # ...and the run must TERMINATE. A contiguous-run pin forbids holes and says
    # nothing about additions, so appending "; and anything the agent considers
    # material" leaves every pinned string byte-perfect and exempts everything.
    # Found by the round's independent battery (its M10); the author's battery
    # probed only the deletion direction.
    tail = block.split(BAR_EXEMPTION_RUN, 1)[1][:2]
    assert tail.startswith("."), (
        f"{name}: the exemption list no longer ends where it is pinned to end — the "
        f"run is followed by {tail!r}, not a full stop. A fifth exemption appended "
        "here satisfies every existing assertion and makes the bar non-binding."
    )


@pytest.mark.parametrize("name", sorted(TIER_BLOCKS))
@pytest.mark.parametrize("label,needle", sorted(BAR_EXEMPTIONS.items()))
def test_the_bar_keeps_every_exemption(name: str, label: str, needle: str) -> None:
    """Losing `defect or security` is the mutation that makes this bar harmful.

    Kept alongside the contiguous-run check above so a failure NAMES the entry
    that went missing rather than reporting the whole list as changed.
    """
    assert needle in tier_block(name), (
        f"{name}: the filing bar lost its {label!r} exemption. Each of the four "
        "is its own justification for a queue entry regardless of what it blocks; "
        "the last one especially -- a queue that cannot hold a bug because nobody "
        "has scheduled the bug is not a queue."
    )


@pytest.mark.parametrize("name", sorted(TIER_BLOCKS))
def test_the_bar_names_the_ledger_as_the_alternative(name: str) -> None:
    """A bar with no destination is a bar that silently discards."""
    block = tier_block(name)
    assert "**Everything else goes to `tasks/notes.md`**" in block, (
        f"{name}: the filing bar no longer names where a refused follow-up goes, or "
        "names it without the imperative. A bare mention is satisfied by a sentence "
        "saying a note MAY be written, and an optional ledger beside a mandatory bar "
        "is a bar that discards -- the opposite of what a ledger is for."
    )
    assert "A note is not a silent drop" in block, (
        f"{name}: the bar lost the sentence requiring the agent to SAY it wrote a "
        "note. A ledger nobody is told about is indistinguishable from a drop, and "
        "the human is the only one who can promote the line."
    )


@pytest.mark.parametrize("name", sorted(TIER_BLOCKS))
def test_the_bar_warns_that_a_note_has_no_task_id(name: str) -> None:
    """The interaction that turns this bar into a hard failure if left unstated.

    `/document-work` Step 3b hard-fails when a `<PREFIX>-<NAME>` token in the
    pending-docs prose resolves to no entry in `index.yml`. A note carries no
    id, so an agent that routes a finding to the ledger AND writes an id-shaped
    token for it into the docs has built a gate failure out of a bar that was
    supposed to cost nothing. Stated at every site because the docs prose can be
    written from any of them.
    """
    block = tier_block(name)
    assert "a note carries no task id" in block, (
        f"{name}: the bar no longer warns that a note has no id to cite. "
        "Step 3b hard-fails on a token that resolves to nothing."
    )
    assert "`/document-work` Step 3b hard-fails" in block, (
        f"{name}: the bar no longer names the gate it interacts with. Pinned as the "
        "whole clause, not a bare `Step 3b`: that substring occurs twice in "
        "document-work's own tier block (the second is pre-existing prose about what "
        "Step 3b verifies), so a bare check passes there with the warning deleted."
    )


def test_the_bar_does_not_replace_the_three_shipped_tier_3_reasons() -> None:
    """The bar is ADDITIVE. Tier 3's original text is the fallthrough it qualifies.

    The cheapest wrong edit here is to rewrite tier 3 as the bar -- which drops
    "only past both" and turns an ordered fallthrough into a standalone filing
    rule that no longer requires tiers 1 and 2 to have been tried.
    """
    for name in sorted(TIER_BLOCKS):
        block = tier_block(name)
        assert "**File a new task** only past both" in block, (
            f"{name}: tier 3 lost 'only past both'. The bar qualifies the "
            "fallthrough; it does not replace it."
        )


# The record item at each executor, sliced. The positive half of the containment the
# phase asserted only negatively: it pinned that the TIER block names no write path and
# left "the record item performs the write" to a file-wide read, which is satisfied by
# the sentence sitting anywhere in the file.
RECORD_ITEMS = {
    CLAIM: ("3. **Persist the `## Test decision`**", "\n4. **Post-fix convention verification \u2014 BOTH maps**"),
    BUILD: ("3\u2011record. **Persist the `## Test decision`**", "\n4. **Post-fix convention verification**"),
}


def record_item_of(path: Path) -> str:
    start, end = RECORD_ITEMS[path]
    return slice_between(read(path), start, end, f"{path.name} record item")


@pytest.mark.parametrize("path", [pytest.param(CLAIM, id="claim-task"), pytest.param(BUILD, id="auto-build")])
def test_the_executor_sites_write_the_ledger_into_the_worktree(path: Path) -> None:
    """Same defect as `Q-322`, one file over -- and the write is delegated.

    A note written into the main checkout is on no branch, so it never reaches
    the PR and it dirties the primary tree, which `/review-close` Step 2a then
    classifies as `dirty` and auto-SKIPs on.

    **Why it lives in the record item and not beside the tier that decides it.**
    Phase 277 pinned that `auto-build`'s tier block names no body write path at
    all (`test_the_record_item_states_why_it_is_one_write_not_two`), because two
    independent writes invert the schema order for `## Also fixed`. That pin
    caught the first cut of this change, which put the ledger path in the tier
    block. The ledger is a *different* file with no ordering relationship to
    those sections, so the inversion argument does not apply to it -- but the
    structural reason does: the record item is the step that owns worktree
    paths, so every record write belongs there and the tier decides routing only.
    """
    item = record_item_of(path)
    assert "`<WORKTREE_PATH>/tasks/notes.md`" in item, (
        f"{path.name}: the ledger append no longer names the worktree copy INSIDE the "
        "record item. A main-checkout write is on no branch -- and a file-wide check "
        "here passed with the sentence moved to an HTML comment near Step 1, which is "
        "how the round's battery walked the first version of this guard."
    )
    assert "append those lines to" in item, (
        f"{path.name}: the record item no longer performs the ledger append, so the "
        "tier can route a finding to a file nothing writes."
    )


@pytest.mark.parametrize("name", ["claim-task", "auto-build"])
def test_the_tier_block_delegates_the_ledger_write(name: str) -> None:
    """The containment Phase 277's pin requires, asserted for this write too.

    If the path drifts back into the tier block, Phase 277's guard reddens on
    `auto-build` -- but `claim-task` has no equivalent pin, so on that site the
    drift would be silent. Assert the delegation at both.
    """
    block = tier_block(name)
    assert "<WORKTREE_PATH>" not in block, (
        f"{name}: the tier block names a write path again. Routing is decided here; "
        "writing belongs to the record item, which owns the worktree paths."
    )
    assert "the record item's write, not this item's" in block, (
        f"{name}: the tier block no longer says who performs the ledger append. A "
        "bare destination with no writer is a finding routed to a file nothing writes."
    )


def test_document_work_routes_the_note_but_does_not_write_it() -> None:
    """A decision the round forced, pinned so it is not "finished" back into a write.

    The first cut made `/document-work` the ledger's third writer. It cannot be:
    the skill states no working directory and makes no commit after Step 2, so the
    write lands in an undetermined tree with nothing to carry it -- in a worktree it
    dirties the branch and Step 1a then classifies it `dirty`, skipping the whole
    close; in the main checkout it is on no branch. It routes instead, and prints
    the line for a human when it is invoked outside an executor.
    """
    text = read(DOCWORK)
    assert "**You route the note; you do not write it.**" in text, (
        "/document-work is writing the ledger again. It has no defined tree and no "
        "commit after Step 2, so the write is lost or it skips the close."
    )
    assert "with two exceptions, both named below" in text, (
        "document-work's do-not-modify exception count no longer matches its carve-outs "
        "(filing a body, `## Also fixed`). An overcount reads as a licence it does not grant."
    )
    assert "print the exact line in your final message" in text, (
        "/document-work no longer surfaces the note when invoked directly. Routing with "
        "no destination and no output is a silent drop."
    )


# The population question, asked of the bar rather than of the tier. Phase 178's
# round found `WORKFLOW_GUIDE.md` -- a third restatement shipped to consumers --
# untouched by a change that had edited every skill body. Both spec surfaces
# describe the executor sequence step by step; a bar absent from them is a bar a
# reader of the spec does not know exists, and the spec is what CLAUDE.md calls
# authoritative.
@pytest.mark.parametrize(
    "path,needle,why",
    [
        pytest.param(WORKFLOW, "must name what it blocks",
                     "the authoritative spec enumerates the Step 7e sequence", id="workflow"),
        pytest.param(WORKFLOW, "`tasks/notes.md` ledger",
                     "the spec names the tier's destination for a refused follow-up", id="workflow-ledger"),
        pytest.param(GUIDE, "**name what the new task blocks**",
                     "the guide is the human-readable twin shipped to consumers", id="guide"),
        pytest.param(GUIDE, "`tasks/notes.md`",
                     "the guide names the ledger a consumer will otherwise never meet", id="guide-ledger"),
    ],
)
def test_the_spec_surfaces_describe_the_filing_bar(path: Path, needle: str, why: str) -> None:
    assert needle in read(path), (
        f"{path.name} does not describe the tier-3 filing bar: {why}. The three skill "
        "bodies are not the whole population -- these two restate the same sequence to "
        "readers who never open a SKILL.md."
    )


# --------------------------------------------------------------------------
# The ledger itself
# --------------------------------------------------------------------------

def test_the_readme_documents_the_ledger() -> None:
    text = read(TASKS_README)
    assert "## The notes ledger (`notes.md`)" in text, (
        "tasks/README.md lost the ledger's section. It is the only shipped "
        "documentation of the file's shape, and three skill bodies point at it "
        "by name -- a dangling pointer into a managed path."
    )


def test_the_readme_states_why_the_flat_shape_is_load_bearing() -> None:
    """Structure in this file makes the prescribed conflict resolution corrupting.

    Every branch appends here, so conflicts are deterministic rather than rare.
    A flat list of independent lines is the one shape where keeping both sides is
    correct. `tasks/index.yml` is the counter-example in the same repo: the same
    resolution on an indented list splits an entry across two hunks and validates
    green. If the README stops saying WHY, the next author adds sub-bullets.
    """
    text = ledger_section()
    assert "the flatness is load-bearing" in text, (
        "tasks/README.md no longer states that the ledger's flat shape is what "
        "makes union-on-conflict a safe resolution."
    )
    assert "Make sure the file ends in a newline before you append" in text, (
        "the ledger lost its trailing-newline rule. `>>` onto a file whose last line "
        "has no newline joins two notes into one line -- and one-line-per-note is the "
        "property the union resolution, the dedup read and the promotion delete all "
        "rest on. Found surviving by the author-side battery's own re-run (M52)."
    )
    assert "No nesting, no sub-bullets, no sections." in text, (
        "the shape rule lost its explicit prohibition. 'Flat' as an adjective is "
        "advice; the prohibition is the rule."
    )


def ledger_section() -> str:
    """The ledger's own section, sliced.

    File-wide reads are why M33 survived the author-side battery: the intent-layer
    section three headings up says `protection by absence` about `vision.md`, so
    deleting the ledger's own statement of the same contract left the substring
    standing and the guard green over a section that no longer said it.
    """
    return slice_between(
        read(TASKS_README),
        "## The notes ledger (`notes.md`)",
        "## Migrating from `product_roadmap.md`",
        "tasks/README.md notes-ledger section",
    )


def test_the_readme_states_the_ownership_contract() -> None:
    """Consumer-owned, seeded by nobody -- the `vision.md` / `decisions.md` shape."""
    assert "protection by absence" in ledger_section(), (
        "tasks/README.md no longer states that `notes.md` is protected from "
        "`--update` by never being created rather than by a skip-if-exists guard. "
        "A reader who assumes a guard exists will look for one that does not."
    )


def test_the_readme_states_that_promotion_is_a_human_act() -> None:
    assert "Promotion is a human act." in ledger_section(), (
        "the ledger lost its exit. A ledger with no promotion path is where "
        "findings go to die, which is the objection this bar has to answer."
    )


def test_the_installer_does_not_seed_the_ledger() -> None:
    """A decision NOT to build, pinned so a future author does not 'finish' it.

    `install.sh` seeds `tasks/index.yml` (skip-if-exists) and copies `schema.md`
    and `README.md` (managed). `notes.md` is deliberately neither. Managed would
    overwrite the consumer's accumulated notes on every `--update`; seeded would
    add a third write mode and a managed-path entry for a file whose entire
    content is consumer-authored. `/intake` already documents this exact contract
    for `vision.md` and `decisions.md`, and this is the third member of that set.
    """
    # `read`, not `require_maintainer_side`: install.sh ships (the public-release spec
    # counts identifiers in its comments in the SHIPPED tree), so the skip contract of
    # that helper does not apply and would only hide the file going missing.
    text = read(INSTALLER)
    assert "notes.md" not in text, (
        "install.sh now references the notes ledger. It must not: the file is "
        "consumer-owned and its protection from `--update` is that the installer "
        "never creates it. Seeding it makes an accumulating file installer-touched "
        "for the first time, and a managed path would overwrite real notes."
    )


# --------------------------------------------------------------------------
# The readers, and the conflict the ledger causes
# --------------------------------------------------------------------------

def test_add_task_dedups_against_the_ledger() -> None:
    """Without this the ledger is write-only and the same finding lands twice."""
    text = read(ADDTASK)
    assert "**Search `tasks/notes.md` too, tolerating its absence**" in text, (
        "/add-task Step 2 no longer dedups against the ledger. It is the only "
        "reader the ledger has; without it a note is invisible to the one skill "
        "that could turn it into a task."
    )


def test_add_task_promotion_removes_the_promoted_line() -> None:
    """One finding, one record. A promoted note left behind is a second record."""
    text = read(ADDTASK)
    assert "delete that line from `notes.md` in the same run" in text, (
        "/add-task no longer deletes a promoted note. The finding then exists as "
        "both a task and a note, and the two drift -- which is the duplicate-record "
        "shape the dedup step exists to prevent."
    )
    assert "The one write outside that rule is deleting a promoted line" in text, (
        "/add-task's `## What this skill never does` still claims capture-only "
        "appends without carving out the promotion delete, so its own boundary "
        "section forbids the write Step 2 now prescribes."
    )


def test_review_close_counts_three_shared_append_files() -> None:
    """Three files, and the lead sentence must not contradict the third's bullet.

    The first cut changed the count and left the lead reading "Never resolve
    **either** by stripping the markers and keeping both sides" -- an absolute
    prohibition, two paragraphs above a bullet saying the union IS the resolution
    for this one file. An agent reading top-down aborts on the only file where the
    union is required.
    """
    text = read(CLOSE)
    assert "Three tracked files are appended to across branches" in text, (
        "/review-close no longer counts three shared append files, or has gone back to "
        "the `by *every* branch` framing -- which is false of `tasks/notes.md`: only a "
        "branch that wrote a note appends to it."
    )
    assert "`tasks/notes.md` is the one exception" in " ".join(text.split()), (
        "the lead sentence's never-union rule no longer carves out the ledger, so the "
        "section contradicts its own third bullet."
    )


def ledger_bullet() -> str:
    """The ledger's own bullet in `/review-close`'s shared-append-files section.

    Sliced, not read file-wide, and the reason is that a file-wide version of the
    check below shipped and was walked in the same session that wrote it:
    `byte-identical` occurs three times in `review-close/SKILL.md`, one of them at
    `:1729` predating this phase entirely, so deleting the ledger's own trap left
    the assertion green. Third instance of that class in one phase.
    """
    return slice_between(
        read(CLOSE),
        "- **`tasks/notes.md`** — the notes ledger",
        "**Resolve `tasks/index.yml` from the merge stages, structurally.**",
        "review-close notes-ledger bullet",
    )


def test_the_ledger_resolution_states_its_own_precondition() -> None:
    """'Keep both sides' is safe HERE and corrupting one bullet above.

    The section's opening rule is *never* resolve by stripping markers and
    keeping both sides. The ledger is the exception, so the exception has to
    carry the property that makes it one and the stop condition for when that
    property no longer holds -- otherwise it reads as a blanket relaxation of
    the rule stated three paragraphs earlier.
    """
    bullet = ledger_bullet()
    assert "**This is the one of the three where keeping both sides IS the resolution**" in bullet, (
        "/review-close no longer marks the ledger as the exception to its own "
        "never-keep-both-sides rule."
    )
    assert "**Two properties make the union safe, and BOTH must hold" in bullet, (
        "the ledger's union resolution no longer states its preconditions."
    )
    assert "Neither side DELETED a line" in bullet, (
        "the union rule lost its DELETE arm -- the one this workflow creates itself. "
        "`/add-task` Step 2 promotes a note by removing its line; union that against "
        "another branch's append and the promoted note comes back, duplicating a filed "
        "task. A delete leaves the file perfectly flat, so the flatness check cannot "
        "see it. Reproduced, not reasoned."
    )
    assert "git show :1:tasks/notes.md" in bullet, (
        "the delete check is stated without the commands that perform it. A precondition "
        "an operator cannot check is a precondition nobody checks."
    )
    assert "`|||||||`" in bullet and "byte-identical" in bullet, (
        "the union rule lost one of its two measured traps: the diff3 fourth marker "
        "(which reinjects the base section, and with it a promoted note), or the "
        "identical-line collapse that produces no conflict for anyone to resolve."
    )


def test_claude_md_carries_the_sysop_side_bar() -> None:
    """Sysop closes phases inline, so the shipped skills do not bind it."""
    text = require_maintainer_side(CLAUDE_MD)
    m = re.search(r"\*\*Fix-in-branch before filing \(Phase 276\)\.\*\*(.*?)\n- \*\*", text, re.S)
    assert m, "the stanza's bounds could not be isolated"
    clause = m.group(1)
    assert "name what it blocks" in clause, (
        "CLAUDE.md's tier 3 files unconditionally again. The shipped skills carry "
        "the bar; this stanza is the only thing that applies it to this repo, and "
        "shipping a filing rule this repo does not follow is the asymmetry the "
        "stanza exists to close."
    )
    assert "**Everything else goes to `REVIEW_CHECKLIST.md` § *Notes***" in clause, (
        "the Sysop-side bar no longer names its ledger. Consumers get "
        "`tasks/notes.md`; this repo has no `tasks/` queue, so § Notes is the "
        "local equivalent and a bar with no destination discards."
    )
    assert "outside this bar as it is outside the tier" in clause, (
        "the stanza lost the carve-out for a round's findings about a phase's own "
        "record. Those name no repo path, can never be tier 1, and can rarely name "
        "a gate -- a bar that catches them would route this repo's most valuable "
        "filings into a ledger."
    )


def test_the_sysop_notes_section_exists_and_is_last() -> None:
    """Placement is load-bearing: the derive commands bound § Low with § Proposed."""
    text = require_maintainer_side(REPO_ROOT / "REVIEW_CHECKLIST.md")
    assert "## Notes — recorded, not queued" in text, (
        "REVIEW_CHECKLIST.md lost § Notes, which CLAUDE.md's stanza names as the "
        "Sysop-side ledger."
    )
    headings = re.findall(r"^## .*$", text, re.M)
    assert headings[-1].startswith("## Notes"), (
        "§ Notes is no longer the last section. The documented derive commands "
        f"slice § Low as `/^## Low/,/^## Proposed/`; the current order is {headings!r}. "
        "A § Notes above § Proposed silently changes what those counts report."
    )


# --------------------------------------------------------------------------
# The population the first cut of these guards missed
# --------------------------------------------------------------------------
#
# Every finding below came from the round's independent battery, which derived the
# population from the tree rather than from this module's own site list and found
# 37 of 73 mutations surviving. The shape is always the same: the rule is stated at
# N places and asserted at one.

def sysop_notes_section() -> str:
    """`REVIEW_CHECKLIST.md` § Notes -- the ledger THIS repo actually uses."""
    text = require_maintainer_side(REPO_ROOT / "REVIEW_CHECKLIST.md")
    return text[text.index("## Notes — recorded, not queued"):]


def test_the_sysop_ledger_states_its_own_shape_rule() -> None:
    """Wholly unguarded in the first cut: reversing it to "nest freely" went green."""
    section = sysop_notes_section()
    assert "Flat lines only, no nesting." in section, (
        "REVIEW_CHECKLIST.md § Notes lost its shape rule. The flat shape is what makes "
        "the union-on-conflict resolution safe; this is the ledger this repo writes to, "
        "and it had no guard at all until the round wrote a mutation that deleted it."
    )
    assert "delete the line in the same commit" in section, (
        "§ Notes lost its promotion rule, so a promoted note stays as a second record."
    )


def test_there_is_exactly_one_sysop_notes_section() -> None:
    """A last-heading check does not stop a SECOND section being added earlier.

    The round's battery inserted a duplicate § Notes inside the `## Low` -> `## Proposed`
    sed range while renaming the EOF one, and passed both the exact-string check and the
    `headings[-1]` check. Two ledgers is worse than none: half the notes are invisible to
    the derive commands and half are counted as § Low entries.
    """
    text = require_maintainer_side(REPO_ROOT / "REVIEW_CHECKLIST.md")
    n = len(re.findall(r"^## Notes\b", text, re.M))
    assert n == 1, (
        f"REVIEW_CHECKLIST.md has {n} `## Notes` sections, expected exactly 1. A second "
        "one above `## Proposed` is counted by the documented § Low derive command."
    )


def test_the_readme_example_obeys_the_shape_it_prescribes() -> None:
    """The example is what an agent copies; the prohibition is what it skims.

    The round nested the shipped example two lines below `No nesting, no sub-bullets,
    no sections.` and every guard stayed green.
    """
    section = ledger_section()
    fence = section.split("```", 2)
    assert len(fence) >= 3, "the ledger section no longer carries a shipped example"
    body = [ln for ln in fence[1].splitlines() if ln.strip()]
    assert body, "the ledger example is empty"
    for ln in body:
        assert ln.startswith("- "), (
            f"the ledger's shipped example is no longer flat: {ln!r} is indented or is "
            "not a top-level list item. An agent copies the example, not the prohibition "
            "above it."
        )


def test_the_readme_restatement_of_the_bar_stays_complete() -> None:
    """`tasks/README.md` restates the whole bar -- a surface no guard read.

    The round dropped the defect/security exemption there, and inverted the naming
    test there, with the suite green both times. It is shipped consumer documentation
    of the same rule, so it is part of the population.
    """
    section = ledger_section()
    for needle, why in [
        ("names what it blocks", "the naming test"),
        ("`current_focus: true`", "the current-phase answer"),
        ("a named `planned` phase", "the planned-phase answer"),
        ("a gate the project declares", "the declared-gate answer"),
        ("stated acceptance", "the open-task answer"),
        ("a `user_action`", "the user_action exemption"),
        ("a production write", "the production-write exemption"),
        ("a defect in shipped behaviour", "the defect exemption"),
        ("security finding", "the security exemption"),
    ]: 
        assert needle in section, (
            f"tasks/README.md's restatement of the filing bar lost {why} ({needle!r}). "
            "It is shipped documentation of the rule and diverging from the skill "
            "bodies is how a consumer ends up following a different bar."
        )


def test_the_readme_skills_table_lists_every_ledger_writer() -> None:
    """The round deleted the `/auto-build` row this phase added, with the suite green."""
    text = read(TASKS_README)
    table = slice_between(text, "## How skills use it", "## Rules", "tasks/README.md skills table")
    for skill in ("`/auto-build`", "`/claim-task <ID>`", "`/add-task`", "`/document-work`"):
        assert skill in table, (
            f"tasks/README.md's skills table no longer lists {skill}. A missing writer "
            "reads as a skill that does not touch the queue, which is how the "
            "`/auto-build` gap this phase closed arose in the first place."
        )


def test_the_ledger_bullet_carries_no_reversal_vocabulary() -> None:
    """The union licence is the most dangerous prose this phase shipped.

    It is the ONE place in `/review-close` that permits a resolution the section
    otherwise forbids absolutely, and it sits beside `tasks/index.yml`, where the
    same resolution corrupts silently and validates green. The round softened it
    (*"or simply take whichever side is longer if the difference looks cosmetic"*)
    and extended the licence to `review_tasks.md` -- both with every pinned string
    intact, because the bullet had presence checks and no screen.
    """
    bullet = ledger_bullet()
    assert "review_tasks.md" not in bullet, (
        "the ledger's union licence now names `review_tasks.md`. That file is an "
        "indented structure -- extending the licence to it is exactly the corruption "
        "the section exists to prevent."
    )
    assert_no_reversal(
        bullet, "review-close notes-ledger bullet",
        extra=(
            "whichever side is longer",
            "looks cosmetic",
            "if the difference",
            "keep both sides anyway",
            "usually safe",
            "as it is for",
            "no need to check",
            "you can skip the",
        ),
    )


def test_the_ledger_section_carries_no_reversal_vocabulary() -> None:
    """`tasks/README.md` had presence checks and no screen either.

    The round kept `**No nesting, no sub-bullets, no sections.**` byte-perfect and
    added *"A single short sub-bullet is fine when one sentence will not hold the
    finding."* beside it. The prohibition and its cancellation coexisted, green.
    """
    assert_no_reversal(
        ledger_section(), "tasks/README.md notes-ledger section",
        extra=(
            "sub-bullet is fine",
            "nest freely",
            "is fine when",
            "if one sentence",
            "structure is fine",
            "a little structure",
            "may optionally name",
            "whenever the finding seems",
            "worth a queue entry",
        ),
    )


def test_the_stranded_probe_excludes_the_ledger() -> None:
    """The F2 fix, guarded -- it shipped without one and the battery walked it out.

    `/claim-task` Step 8's stranded-body probe is `git diff --name-only HEAD --
    tasks/` in the MAIN checkout, and `/add-task` -- which never commits -- deletes a
    line from `tasks/notes.md` there when it promotes a note. Without the exclusion
    that promotion reports `STRANDED`, whose disposition tells the human an executor
    wrote body edits to the wrong tree and **skips the auto-mode chain**. Reproduced
    against the shipped probe by the round; reproduced again after the fix, both
    directions (promotion clean, a real stranded body still reported).
    """
    text = read(CLAIM)
    assert '"--", "tasks/"],' in text, (
        "/claim-task Step 8's stranded probe no longer diffs exactly `tasks/`. "
        "`test_claim_task_step7_contracts.py` pins that pathspec because anything "
        "narrower stops seeing a stranded body -- this phase's FIRST fix for the "
        "false-STRANDED bug added `:(exclude)tasks/notes.md` there and was caught by it."
    )
    assert 'bodies = [p for p in changed if p != "tasks/notes.md"]' in text, (
        "the probe no longer partitions the ledger out of the STRANDED verdict. An "
        "/add-task promotion then reports STRANDED and the auto-mode chain stops, with "
        "a disposition that is false in all three of its claims for a note."
    )
    assert "NOTES PENDING" in text, (
        "the ledger's own arm is gone, so an uncommitted note is either a false halt or "
        "a silence. It still needs committing; it is just not stranded."
    )
    assert "partitioned out of the verdict, and the pathspec is deliberately NOT narrowed" in text, (
        "the partition lost the reason it is a partition rather than an exclusion, which "
        "is the half that stops a future author 'simplifying' it back into the pathspec."
    )


def test_no_other_shared_append_file_gains_the_union_licence() -> None:
    """The licence must not spread to the two files where the union corrupts.

    `ledger_bullet()` screens the ledger's own bullet. The round showed the licence
    can be granted from the NEIGHBOURING bullet instead -- `review_tasks.md` gaining
    "resolvable by union as `tasks/notes.md` is" sits outside that slice and passed
    everything. So the screen is applied to the whole section, minus the one bullet
    that legitimately carries it.
    """
    section = slice_between(
        read(CLOSE),
        "#### Sysop-written shared append files",
        "**Resolve `tasks/index.yml` from the merge stages, structurally.**",
        "review-close shared-append-files section",
    )
    outside = section.replace(ledger_bullet(), "")
    for phrase in ("union", "keeping both sides IS", "keep both sides"):
        assert phrase not in outside, (
            f"the union licence has spread outside the ledger's bullet ({phrase!r}). "
            "`tasks/index.yml` and `review_tasks.md` are indented structures -- for them "
            "that resolution splits an entry across hunks and validates green, which is "
            "the corruption this whole section exists to prevent."
        )


# --------------------------------------------------------------------------
# The tally counts EVERY section, not the first (`Q-464` half 2, Phase 280)
#
# The defect was in the reader, never the writer: `/claim-task`'s option-C
# writer re-emits a two-section body with both sections intact, and Step 2d
# then took the first match. `## Also fixed` lines per branch is one of the
# three numbers section G judges the tier on, and a first-match reader moves
# it DOWN -- the direction that reads as the tier behaving.
#
# The fixture below is not invented. It is the heading order of the one live
# two-section body in the consumer corpus as of 2026-09-10
# (`tasks/open/FEAT-PRICING-LAUNCH-OFFER.md`), reduced to its shape: the
# `(PR 1)` section comes FIRST and its whole content is an explicit `_(none)_`
# marker, an unrelated `## Filed (PR 1)` section sits between the two, and the
# `(PR 0)` section that carries the actual fix entries comes SECOND. Measured
# against that file, a first-match reader reports 0 lines where the body
# carries 2 -- a 100% undercount on the only body in the corpus that can
# produce one. Two closes have already read that body at a branch tip; they
# did not under-report because the arm did not exist yet (Phase 276). Being
# in `open/` proves nothing either way -- a multi-PR task stays there across
# closes. Next exposure is PR 2 of 4.
# --------------------------------------------------------------------------

# The live body's shape, reduced. Heading ORDER is the load-bearing part.
_TWO_SECTION_BODY = """# FEAT-EXAMPLE

## Test decision (PR 0, 2026-09-08)

- test `tests/test_a.py::test_one` proves the thing.

## Also fixed (PR 1)

_(none)_ — every edit is in the plan's scope; the extraction and the helper are
in-scope design items, not adjacent fixes. Money-path files carry no tier-1 fix by rule.

## Filed (PR 1)

_(none)_ — no adjacent defect surfaced that was not already owned by an open task.

## Also fixed (PR 0)

- `src/thing.py::compute` docstring — its enumeration of roles was stale; corrected
  during the in-scope sweep. Doc-only correction, no test gate.
- `docs/configuration.md` — the row named a default the resolver stopped using.

## Plan

```markdown
The reviewed plan, verbatim. It discusses this very rule, so it quotes the heading:

## Also fixed
- a fabricated line naming `never/touched.py`, which is INSIDE a fence.
```
"""

# ATX indented by up to 3 spaces is still a heading; 4+ is a code block.
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*)$")
# A setext underline: `===` is depth 1, `---` is depth 2. It applies to the line ABOVE.
_SETEXT = re.compile(r"^ {0,3}(=+|-+)\s*$")
_ALSO = re.compile(r"also\s+fixed", re.I)


def _fence_spans(lines: list[str]) -> list[bool]:
    """True for every line inside a fence, tracked the way Step 8's `fence_mark` is.

    A closer uses the same character, is at least as long as the opener, AND carries
    no info string. The first cut of this helper dropped the last clause -- the same
    omission the arm's prose carried -- and it reported a live consumer body as ending
    inside a fence when its fences are balanced: a ```json line nested inside a ```
    fence was read as that fence's closer, inverting the model from there on.

    The round corrected the attribution this docstring used to carry, and **Phase 281
    then made the corrected version stale too** -- which is why this paragraph now names
    no line numbers. The rule is NOT in `fence_mark`, which still only reports that a
    line IS a marker. It used to live inline in `strip_sections`' caller and nowhere
    else, which is what `Q-468` reported; Phase 281 closed that by giving BOTH walkers a
    `fence_closes` predicate, so Step 8 now carries it too. The shape is pinned
    structurally by `tests/test_fence_closer_structure.py` rather than by a line
    citation, because the round walked a substring pin from both the caller and the
    definition.
    """
    inside = [False] * len(lines)
    marker = ""
    for i, ln in enumerate(lines):
        s = ln.strip()
        m = re.match(r"^(`{3,}|~{3,})", s)
        closes = bool(
            m and m.group(1)[0] == marker[:1]
            and len(m.group(1)) >= len(marker)
            and not s.strip(m.group(1)[0])      # no info string
        ) if marker else False
        if not marker and m:
            marker = m.group(1)
            inside[i] = True
            continue
        if marker:
            inside[i] = True
            if closes:
                marker = ""
    return inside


def _heading(lines: list[str], i: int, fenced: list[bool]) -> "tuple[int, str] | None":
    """`(depth, text)` if line *i* is a heading, else None. ATX or setext.

    Both non-ATX shapes were found by the round, and both fail in the OVER-counting
    direction: a terminator model anchored to a column-0 `#` misses them, the section
    over-runs into the next one, and the tally reports the next section's entries too.
    """
    if fenced[i]:
        return None
    m = _HEADING.match(lines[i])
    if m:
        return len(m.group(1)), m.group(2)
    # setext: this line is text and the NEXT line underlines it.
    if i + 1 < len(lines) and not fenced[i + 1] and lines[i].strip():
        u = _SETEXT.match(lines[i + 1])
        if u and not _HEADING.match(lines[i]):
            return (1 if u.group(1)[0] == "=" else 2), lines[i].strip()
    return None


def _is_setext_underline(lines: list[str], i: int, fenced: list[bool]) -> bool:
    """True if line *i* is the underline of a setext heading on line i-1."""
    return (
        i > 0
        and not fenced[i]
        and bool(_SETEXT.match(lines[i]))
        and bool(lines[i - 1].strip())
        and not _HEADING.match(lines[i - 1])
    )


def _sections(body: str, first_only: bool) -> list[list[str]]:
    """Every `also fixed` section outside a fence, or just the first (the defect)."""
    lines = body.split("\n")
    fenced = _fence_spans(lines)
    out: list[list[str]] = []
    for i in range(len(lines)):
        h = _heading(lines, i, fenced)
        if not h or not _ALSO.search(h[1]):
            continue
        depth = h[0]
        start = i + 2 if _is_setext_underline(lines, i + 1, fenced) else i + 1
        content: list[str] = []
        for k in range(start, len(lines)):
            if _is_setext_underline(lines, k, fenced):
                continue          # consumed with its text line below
            nh = _heading(lines, k, fenced)
            if nh and nh[0] <= depth:
                break
            content.append(lines[k])
        out.append(content)
        if first_only:
            break
    return out


def _unterminated(body: str) -> bool:
    """True if the body ends inside a fence -- the shape the arm must REPORT, not guess."""
    lines = body.split("\n")
    marker = ""
    for ln in lines:
        s = ln.strip()
        m = re.match(r"^(`{3,}|~{3,})", s)
        if not marker:
            if m:
                marker = m.group(1)
            continue
        if m and m.group(1)[0] == marker[0] and len(m.group(1)) >= len(marker) \
                and not s.strip(m.group(1)[0]):
            marker = ""
    return bool(marker)


# A top-level list item: `-`, `*`, `+` or `1.`, at column 0..3. NOT a continuation
# line and NOT a nested sub-item -- both belong to the entry above them.
_ITEM = re.compile(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])\s+\S")


def _fix_lines(content: list[str]) -> int:
    """A line is a TOP-LEVEL list item, per the arm's own rule.

    The first cut of this helper was `ln.startswith("- ")`, which disagreed with
    the shipped prose two ways at once on the phase's own live-derived fixture:
    it missed `*`/`+`/numbered entries entirely (an UNDERCOUNT, the direction the
    arm exists to close) and the prose, read literally as "physical line", would
    have over-counted wrapped entries by 2x.

    "Top-level" is relative to the FIRST item in the section, not to column 0: a
    sub-item indented under a column-0 parent sits at indent 2, which any fixed
    `^ {0,3}` test accepts. Continuation lines and nested sub-items belong to the
    entry above them.
    """
    base = None
    n = 0
    for ln in content:
        m = _ITEM.match(ln)
        if not m:
            continue
        indent = len(ln) - len(ln.lstrip())
        if base is None:
            base = indent
        if indent <= base:
            n += 1
    return n


def _tally(body: str, first_only: bool) -> int:
    return sum(_fix_lines(c) for c in _sections(body, first_only))


def test_the_fixture_actually_discriminates() -> None:
    """The anti-vacuity clause, and it is the reason this pair of tests is worth anything.

    Phase 279 shipped a guard that asserted a PROPERTY a quarter of its subject
    satisfied exactly as well as the whole, and nothing would ever have reported
    the difference. So before asserting that the all-sections tally is right, assert
    that a first-match tally is WRONG on this body -- otherwise both counters agree,
    the fixture proves nothing, and the guard below is green over a reverted rule.
    """
    first = _tally(_TWO_SECTION_BODY, first_only=True)
    every = _tally(_TWO_SECTION_BODY, first_only=False)
    assert first != every, (
        "the fixture no longer discriminates: a first-match reader and an "
        "all-sections reader return the same tally over it, so neither guard below "
        "can fail and the rule they exist to pin is unpinned."
    )
    assert (first, every) == (0, 2), (
        f"the live body's measured shape was first-match=0, all-sections=2; this "
        f"fixture now gives {first} and {every}. If the fixture changed on purpose, "
        f"re-derive both numbers and say where from."
    )


def test_the_none_marker_section_contributes_zero_not_its_prose() -> None:
    """The over-count direction, which corrupts the same section-G number.

    The live `(PR 1)` section's whole content is `_(none)_` plus two lines of prose
    explaining why. Counting prose lines would report 3 where the author recorded
    none -- and the tally would then read as the tier doing MORE than it did.
    """
    sections = _sections(_TWO_SECTION_BODY, first_only=False)
    assert len(sections) == 2, f"expected 2 sections in the fixture, got {len(sections)}"
    assert _fix_lines(sections[0]) == 0, (
        "the `_(none)_` section is being counted as carrying fix entries. A line is a "
        "fix entry; an author who considered the question and recorded nothing "
        "contributes zero, not the length of their explanation."
    )
    assert _fix_lines(sections[1]) == 2, "the second section's two fix entries were lost"


def test_the_fenced_quotation_is_counted_by_neither_reader() -> None:
    """The `## Plan` fence quotes the heading, and the arm forbids reading it.

    This is the arm's worst outcome rather than a miscount: a fence-blind reader
    finds a heading that is a QUOTATION, reads the line under it as a record, and
    raises a check-1 finding against `never/touched.py` -- a path the branch
    legitimately never touched. A fabricated finding.
    """
    for content in _sections(_TWO_SECTION_BODY, first_only=False):
        assert not any("never/touched.py" in ln for ln in content), (
            "a fenced `## Also fixed` inside the `## Plan` section was read as a real "
            "section. The plan is held verbatim in a fence and a plan discussing this "
            "rule quotes the heading."
        )


def test_a_subheading_inside_a_section_does_not_terminate_it() -> None:
    """Same-or-shallower, which is the terminator the arm now states.

    The baseline file's own Sysop-side instrument already terminates this way, and
    for the same stated reason: the undercount is the direction that corrupts this
    measurement, so a `####` sub-heading has to stay INSIDE its section.
    """
    body = (
        "## Also fixed\n"
        "- `a.py` — one.\n"
        "\n"
        "#### A sub-heading the author added\n"
        "- `b.py` — two.\n"
        "\n"
        "## Plan\n"
        "- not a fix entry.\n"
    )
    sections = _sections(body, first_only=False)
    assert len(sections) == 1
    assert _fix_lines(sections[0]) == 2, (
        "a `####` sub-heading terminated its parent section, so the entries below it "
        "were lost. The terminator is same-or-shallower depth."
    )


@pytest.mark.parametrize(
    "label,needle",
    [
        ("iterate every section", "Find **every** section under a heading matching"),
        ("do not stop at the first", "do not stop at the first match"),
        ("the terminator is stated", "ends at the next heading of the **same or shallower** depth"),
        ("the checks run over each section", "Run all three over each section you found"),
        ("the bound is judged on the sum", "**Judge the summed count**"),
        ("the tally sums", "sums every section found"),
        ("a two-section branch counts once", "still counts once in the first field"),
        ("a `_(none)_` section is zero", "contributes **zero**"),
    ],
)
def test_the_arm_iterates_rather_than_taking_the_first_match(label: str, needle: str) -> None:
    """`Q-464` half 2. Each needle is a separate way to restore the undercount.

    Reads LIVE PROSE, not the raw slice: the round gutted every rule here and parked
    all eight needles in a superseded-draft blockquote, then in a labelled fence, and
    both passed. A needle in text a reader does not execute disposes of nothing.
    """
    arm = live_prose(
        read(CLOSE),
        "**2‑also. The `## Also fixed` arm",
        "### 2e. Claim-Artifact Report",
        "2-also arm through item 4",
    )
    assert needle in arm, (
        f"the `## Also fixed` arm lost its {label!r} rule. A first-match reader "
        "undercounts `## Also fixed` lines per branch -- one of the three numbers "
        "section G judges the tier on -- in the direction that reads as the tier "
        "staying inside its bound."
    )


def test_the_step_8_template_says_all_sections() -> None:
    """The template is the line a human actually reads; the prose above it is not.

    Guarded separately because the two can drift: Phase 280 found the prose and the
    template BOTH saying "the section", and fixing only one would leave the operator
    filling in a field whose own text still asks for a single section's count.
    """
    # The round: this asserted the string was somewhere in a 3,000-line file, so
    # reverting the template and parking the phrase in a fence elsewhere passed. Read
    # the template LINE.
    lines = [l for l in read(CLOSE).split("\n") if l.startswith("Also fixed:")]
    assert len(lines) == 1, (
        f"expected exactly one `Also fixed:` report-template line, found {len(lines)}. "
        "Two would let a reader fill in whichever they met first."
    )
    assert "N lines total across ALL its sections" in lines[0], (
        "the Step 8 `Also fixed:` template no longer says the line count spans every "
        f"section. The template is what an operator fills in. Line is: {lines[0]!r}"
    )
    assert "N branches carrying a section" in lines[0], (
        "the template's branch field changed. `N sections found` would restore the "
        "denominator inflation the arm's item 4 exists to prevent."
    )


def test_a_nested_info_string_fence_is_not_read_as_a_closer() -> None:
    """The omission that inverts the fence model, and it fabricates rather than drops.

    Derived from a live consumer body (`tasks/open/FIX-DRAFTER-JSON-PREAMBLE.md`), which
    nests a ```json line inside a ``` fence -- one body in 912, scanned. A reader that
    accepts an info-string line as a closer believes it has LEFT the fence while still
    inside it, and then reads the fence's own remaining lines as real sections. That is
    the fabricated-finding direction, which the arm calls its worst outcome.

    The round refuted this test's original docstring, which said the shipped Step 8
    verifier already carried the rule. At the time it did not -- it closed a fence on
    any same-char marker of sufficient length, info string or not -- and that was filed
    as `Q-468` and **closed by Phase 281**, which gave both of /claim-task's walkers a
    shared `fence_closes` predicate. What survives unchanged is this arm's reason for
    stating the rule itself rather than pointing at another skill: a rule held by
    pointing at someone else's code moves when that code does, which is exactly what
    happened to the two line numbers this paragraph used to carry.
    """
    body = "\n".join([
        "## Context",
        "",
        "```",
        "a fenced example that itself shows a json block:",
        "```json",
        '{"k": 1}',
        "```",                      # <- the REAL closer of the outer fence
        "",
        "## Also fixed",
        "- `src/real.py` — a genuine entry, outside every fence.",
        "",
    ])
    sections = _sections(body, first_only=False)
    assert len(sections) == 1, (
        f"expected exactly 1 real section, got {len(sections)}. An info-string line "
        "read as a closer inverts the model and changes which headings are visible."
    )
    assert _fix_lines(sections[0]) == 1
    assert any("src/real.py" in ln for ln in sections[0])


def test_the_arm_states_the_info_string_clause() -> None:
    """Pinned in the prose, because the prose is what an agent executes here.

    There is no shipped code for this arm -- a human or an agent reads the paragraph
    and builds the parser. A fence rule stated three-quarters correctly produces a
    parser that is wrong on real input, which is exactly what happened when this
    phase's own helper was written from the paragraph as it stood.
    """
    arm = live_prose(
        read(CLOSE),
        "**2‑also. The `## Also fixed` arm",
        "**3. On a clean match",
        "2-also arm",
    )
    assert "carrying no info string" in arm, (
        "the `## Also fixed` arm's fence rule no longer says a closer carries no info "
        "string. Without it a nested ```json line reads as a closer, the reader believes "
        "it has left the fence, and the fence's own contents are reported as a record."
    )


def test_the_tally_paragraph_carries_no_reversal_vocabulary() -> None:
    """Item 4 sits OUTSIDE the arm's reversal slice, and the battery proved it matters.

    `test_the_arm_carries_no_reversal_vocabulary` ends at "**3. On a clean match", so
    the tally paragraph -- where the two summing rules actually live -- had pins and no
    reversal layer. Phase 280's author-side battery walked two mutations through it:
    both kept every pinned needle and added a sentence beside it licensing the
    first-match count ("judging each section's alone is equally valid", "reporting the
    first section's count alone is acceptable when the others are short"). That is
    verbatim the move that walked 38 of 53 mutations through Phase 247's first guards.

    Scoped to its own slice rather than widening the arm's, so a failure names the
    tally rather than the whole step.
    """
    tally = slice_between(
        read(CLOSE),
        "**4. Record outcomes for Step 8.**",
        "### 2e. Claim-Artifact Report",
        "Step 2d item 4 (the tally)",
    )
    assert_no_reversal(
        tally,
        "review-close Step 2d item 4",
        extra=(
            # Both from this phase's own battery. Neither is generic enough for
            # REVERSAL_VOCAB -- they soften THIS rule and would be noise elsewhere.
            "equally valid",
            # `where convenient` was here and the round showed it a genuine false red --
            # it hits ordinary formatting prose ("where convenient, keep the three
            # numbers on one line"). `equally valid` already kills the mutation it was
            # added for, so it is dropped rather than kept with an exemption.
            "the first section's count alone",
            "fold it into the `Test decisions:` line",
        ),
    )


# --------------------------------------------------------------------------
# What the round forced in (Phase 280, lens 1)
# --------------------------------------------------------------------------

def test_a_setext_heading_terminates_a_section() -> None:
    """`Plan` underlined by `---` is a real H2 and the first model could not see it.

    Over-count direction: the section over-ran into `## Plan` and the tally reported
    the plan's bullets as fix entries -- the same section-G number, pushed the other
    way, which is precisely what item 4 argues corrupts the ratio.
    """
    body = "## Also fixed\n- `a.py` — one.\n\nPlan\n----\n- not a fix entry.\n- nor this.\n"
    sections = _sections(body, first_only=False)
    assert len(sections) == 1
    assert _fix_lines(sections[0]) == 1, (
        "a setext `Plan` heading did not terminate the section, so the plan's own "
        "bullets were counted as fix entries."
    )


def test_an_indented_atx_heading_terminates_a_section() -> None:
    """CommonMark allows up to three spaces of indentation; four makes a code block."""
    body = "## Also fixed\n- `a.py` — one.\n\n   ## Plan\n- not a fix entry.\n"
    sections = _sections(body, first_only=False)
    assert _fix_lines(sections[0]) == 1, (
        "an ATX heading indented by three spaces was not recognised, so the section "
        "over-ran. Four or more spaces WOULD be a code block; three is a heading."
    )


@pytest.mark.parametrize("marker,label", [
    ("-", "dash"), ("*", "star"), ("+", "plus"), ("1.", "numbered"),
])
def test_every_list_marker_counts_as_a_fix_entry(marker: str, label: str) -> None:
    """`- ` only was an UNDERCOUNT, the direction this arm exists to close.

    A section written with `*` bullets carries real entries; a reader that knows only
    `-` tallies it as zero and the branch reads as having fixed nothing.
    """
    body = f"## Also fixed\n{marker} `a.py` — one.\n{marker} `b.py` — two.\n\n## Plan\n"
    assert _tally(body, first_only=False) == 2, f"{label} bullets were not counted"


def test_a_wrapped_entry_counts_once_not_per_physical_line() -> None:
    """The over-count the literal reading of "a line" produces on real input.

    The live corpus wraps entries across three and four physical lines. Counting
    physical lines reports 2x on the phase's own fixture.
    """
    body = (
        "## Also fixed\n"
        "- `src/thing.py::compute` docstring — its enumeration of roles was stale;\n"
        "  corrected during the in-scope sweep. Doc-only correction, no test gate,\n"
        "  verified by reading the five call sites.\n"
        "  - a nested sub-item, which belongs to the entry above it.\n"
        "\n## Plan\n"
    )
    assert _tally(body, first_only=False) == 1, (
        "a wrapped entry with a nested sub-item counted as more than one fix."
    )


def test_an_unterminated_fence_is_detectable_rather_than_guessed() -> None:
    """The shape the arm must REPORT. Silence here picks the worst answer by default.

    A reader that stays inside to EOF loses every real section and says nothing,
    because the arm's absence branch is silent by design. /claim-task Step 8 detects
    the same condition and prints a NOTE; the arm now says to surface it.
    """
    body = "## Plan\n\n```\nan example that never closes\n\n## Also fixed\n- `a.py` — real.\n"
    assert _unterminated(body), "the unterminated fence was not detected"
    assert _tally(body, first_only=False) == 0, (
        "control: a fence-tracking reader DOES lose the entries here -- which is why "
        "the arm must report the condition instead of returning a silent zero."
    )
    ok = "## Also fixed\n- `a.py` — real.\n\n## Plan\n\n```\nclosed\n```\n"
    assert not _unterminated(ok), "false positive on a balanced body"


@pytest.mark.parametrize("label,needle,end", [
    ("states the fence rule itself",
     "A fence opens on ``` or `~~~` and closes on a marker using the **same character**", "**3. On a clean match"),
    # Both rows below were re-pointed by Phase 281, when `Q-468` closed. They used to
    # pin two FACTS about the tree at the time -- that Step 8's walker had no
    # info-string check, and that `claim-task/SKILL.md:1395` was the one shipped site
    # carrying the rule. Phase 281 made both false by fixing Step 8, so pinning them
    # verbatim would have forced the arm to keep asserting something untrue. What the
    # reviewer actually forced in was the DURABLE half of each -- do not hold this rule
    # by pointing at another skill, and do name where the rule lives -- so that is what
    # is pinned now. This is a re-point, not a softening: a fix that deleted either
    # sentence outright still reddens.
    ("retracts the Step 8 pointer",
     "a rule held only by pointing at another skill's code moves when that code does",
     "**3. On a clean match"),
    ("names where the rule lives",
     "delegate the closer decision to one `fence_closes` predicate per block",
     "**3. On a clean match"),
    ("reports an unterminated fence", "unbalanced fences in", "**3. On a clean match"),
    ("covers setext and indented ATX", "a line of text underlined by `===`", "**3. On a clean match"),
    # The count rule lives in item 4, which is PAST the arm's slice end. Sliced to 2e
    # instead of widening the arm's own slice, so a failure still names where it looked.
    ("counts items, not physical lines",
     "**A line is a list ITEM, not a physical line**", "### 2e. Claim-Artifact Report"),
    ("accepts every list marker", "`-`, `*`, `+`, or `1.`", "### 2e. Claim-Artifact Report"),
])
def test_the_arm_carries_what_the_round_forced_in(label: str, needle: str, end: str) -> None:
    arm = live_prose(
        read(CLOSE),
        "**2‑also. The `## Also fixed` arm",
        end,
        "2-also arm",
    )
    assert needle in arm, (
        f"the `## Also fixed` arm lost its {label!r} rule. Every one of these was "
        "forced in by an independent reviewer that executed the arm's instructions "
        "rather than reading them; each has a demonstrated wrong answer behind it."
    )


def test_the_arm_no_longer_claims_step_8_gets_fences_right() -> None:
    """The false claim this phase shipped, pinned so it cannot come back.

    The first cut said "the shipped `fence_mark` gets it right; only this summary of
    it was short". Both halves were false: the rule is not in `fence_mark`, and Step
    8's walker does not carry it anywhere. The claim was the phase's stated reason for
    not fixing a real defect in a shipped gate.
    """
    text = read(CLOSE)
    assert "the shipped `fence_mark` gets it right" not in text, (
        "the refuted claim is back. `fence_mark` reports only that a line IS a marker; "
        "the closer decision -- same character, at least as long, AND no info string -- "
        "lives in `fence_closes`, one copy per shipped block, pinned structurally by "
        "tests/test_fence_closer_structure.py. This was `Q-468`, closed by Phase 281."
    )
    assert "Track fences the way `/claim-task`'s Step 8 verifier does" not in text, (
        "the arm points at Step 8's fence model again. Following it reproduces the "
        "info-string defect this arm exists to avoid."
    )


def test_the_disposition_bullets_carry_no_reversal_vocabulary() -> None:
    """The un-guarded window the round found BETWEEN the two reversal slices.

    `test_the_arm_carries_no_reversal_vocabulary` ends at `**3. On a clean match`;
    `test_the_tally_paragraph_carries_no_reversal_vocabulary` starts at `**4. Record
    outcomes`. Item 3 and the five disposition bullets sit between them, covered by
    neither -- and the round's M03 landed exactly there: every pin intact, plus "the
    sections are duplicates of one another in every case observed, so counting the
    first alone is the reading to use". That sentence reverses the whole arm from a
    position no guard was looking at.
    """
    block = slice_between(
        read(CLOSE),
        "**3. On a clean match",
        "**4. Record outcomes for Step 8.**",
        "Step 2d item 3 + the disposition bullets",
    )
    assert_no_reversal(
        block,
        "review-close Step 2d item 3 + dispositions",
        exempt=(
            # Shipped text: the fourth disposition exists precisely to say nothing was owed.
            "The branch stays approved and **nothing is waived**",
        ),
        extra=(
            "duplicates of one another",
            "counting the first alone",
            "the first section alone",
            "a first-match reading",
            "either reading serves",
        ),
    )


_ARM_REPUDIATION = (
    "is overstated", "that was wrong", "was too strict", "no longer holds",
    "remains the right instruction", "superseded", "that claim is",
)


@pytest.mark.parametrize("label,needle", [
    ("do not hold the rule by pointing at another skill",
     "a rule held only by pointing at another skill's code moves when that code does"),
    ("name where the rule lives",
     "delegate the closer decision to one `fence_closes` predicate per block"),
])
def test_the_re_pointed_rows_are_not_quoted_only_to_be_repudiated(label: str, needle: str) -> None:
    """Round lens 1, MEDIUM 3 — the companion to the presence rows above.

    Phase 281 re-pointed two of those rows onto the durable half of each rule and recorded
    that as "a re-point, not a softening". The lens then walked both by keeping the needles
    and inverting the sentence around them: *"That remains the right instruction, and the
    claim that «a rule held only by pointing at another skill's code moves when that code
    does» is overstated — follow Step 8's walker, which is authoritative."* Both needles
    present; deleting one outright was the only mutation killed.

    Substring presence is a **reversion** guard: it proves the text is wired to the file,
    not that the file asserts it. This row reads the sentence the needle sits in, which is
    where the reversal lives. Same fix as `/auto-build`'s verdict arm, same round.
    """
    arm = live_prose(read(CLOSE), "**2‑also. The `## Also fixed` arm", "**3. On a clean match",
                     "2-also arm")
    i = arm.index(needle)
    start = max(arm.rfind(". ", 0, i), arm.rfind("\n\n", 0, i)) + 1
    end = arm.find(". ", i + len(needle))
    sentence = arm[start:end if end != -1 else len(arm)].lower()
    found = [v for v in _ARM_REPUDIATION if v in sentence]
    assert not found, (
        f"the `## Also fixed` arm still contains the {label!r} needle, but the sentence "
        f"carrying it repudiates it ({found!r}):\n\n  {sentence.strip()[:400]}\n\n"
        "A rule quoted only to be overturned is not a rule."
    )
