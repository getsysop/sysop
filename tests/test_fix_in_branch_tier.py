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
