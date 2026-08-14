"""Drift guards for Phase 200's Step 4c claims (Q-189 + Q-194).

Why this file exists, stated plainly: Phase 200's own author-side battery
scored **17% (4 killed / 23)**, and every one of its sixteen *prose*
mutations survived. The phase's substance is prose in a skill file, and
prose had no guard at all -- so a later edit could restore any of the
defects this phase removed and the suite would stay green.

Two deliberate limits, so these are not over-trusted:

* A presence check is satisfied by the phrase, not by its force. A later
  sentence can contradict an earlier one and every assertion here still
  passes -- the known class filed as Q-203. Where a reversal has a
  characteristic *inverting* phrase, this file asserts that phrase's
  ABSENCE as well, which is the only cheap purchase on laundering.
* These guard the record of a decision, not the behaviour. The behavioural
  half lives in test_step4a_shared_file_behaviour.py (the cherry-pick
  shapes) and test_step2b_baseline_delta.py (the baseline/delta sequence).

The absence assertions below are **whole-file** and deliberately admit no
exception, not even prose *about* the banned string. Two of them went red on
their first run against explanatory sentences this same phase had written
("Saying X is what the previous version did", "never `grep -c`") -- and the
sentences were reworded rather than the guards loosened. The rule that buys:
grepping this file for a retired falsehood returns zero hits, so a reader
cannot find the old wording and mistake it for current guidance. If you need
to discuss one of these strings, describe it instead of quoting it.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = (REPO / "core/skills/review-close/SKILL.md").read_text()
SHARED = (REPO / "core/skills/_shared/adversarial-review.md").read_text()
WORKFLOW = (REPO / "core/companion/docs/WORKFLOW.md").read_text()
GUIDE = (REPO / "core/companion/docs/WORKFLOW_GUIDE.md").read_text()


# --------------------------------------------------------------------------
# Q-189 -- the gate
# --------------------------------------------------------------------------

def test_the_containment_test_is_not_claimed_valid_for_every_landed_branch() -> None:
    """The shipped falsehood this phase removed. Reversal guard.

    The old text asserted the count is 0 "for every branch that landed under
    either policy -- verified in all three shapes". It is not: a cherry-pick
    scores non-zero with its content fully applied.
    """
    assert "`0` for every branch that landed" not in SKILL, (
        "the pre-Phase-200 falsehood is back at Step 4c step 1b -- a cherry-picked "
        "branch scores non-zero, so the count is 0 only for a rebase-then-ff-merge"
    )
    assert "verified in all three shapes" not in SKILL, (
        "the 'all three shapes' claim is back, and no test builds an integration "
        "branch or a cherry-pick against this filter"
    )


def test_the_cherry_pick_fallback_is_prescribed() -> None:
    assert 'git cherry HEAD "<branch from frontmatter>"' in SKILL, (
        "Step 4c step 1b lost its git cherry fallback -- rev-list alone cannot "
        "separate a cherry-picked branch from an unmerged one (both score non-zero)"
    )


def test_the_fallback_uses_wc_l_and_never_grep_dash_c() -> None:
    """`grep -c` exits 1 when the count is 0 -- and 0 is the PASS value.

    Prescribed as `grep -c`, the good outcome returns a failing status,
    aborts under `set -e`, and never fires the right side of an `&&`.
    """
    assert "grep '^+' | wc -l" in SKILL, "the fallback must count with `grep | wc -l`"
    assert "grep -c '^+'" not in SKILL, (
        "`grep -c '^+'` is back: it exits 1 on a zero count, which is this "
        "test's pass value, so the exit status is inverted on the good outcome"
    )


def test_the_fallback_verdict_is_ask_not_skip() -> None:
    assert "**ask, not skip**" in SKILL, (
        "the fallback's verdict was softened -- a branch whose content is "
        "applied must be reported, not silently skipped"
    )
    assert "Treat that as a skip" not in SKILL


def test_the_ref_must_be_resolved_before_the_fallback_is_read() -> None:
    """A `fatal:` leaves the pipeline printing 0 -- this test's *merged* answer.

    Without the rev-parse ahead of it, a deleted branch reads as "content is
    in the merge target" and its doc gets routed, its task flipped to done
    and its lock dropped: the exact loss step 1b exists to prevent.
    """
    i_verify = SKILL.find('git rev-parse --verify "<branch from frontmatter>^{commit}"')
    i_cherry = SKILL.find('git cherry HEAD "<branch from frontmatter>"')
    assert i_verify != -1, "the ref-resolution check ahead of the fallback is gone"
    assert i_verify < i_cherry, (
        "the rev-parse guard must come BEFORE the git cherry fallback; an "
        "unresolvable ref makes the pipeline print 0, which reads as merged"
    )


def test_the_patch_id_limit_on_the_fallback_is_stated() -> None:
    """git cherry false-reports after a conflict-resolved pick. Say so."""
    assert "conflict resolution changes the patch" in SKILL, (
        "the fallback's limit is unstated -- a conflict-resolved pick changes "
        "the patch-id, so git cherry reports an applied commit as unapplied"
    )


def test_held_back_docs_have_a_report_slot_that_assumes_no_4a_skip() -> None:
    # Scoped to the Step 8 report template. A whole-file check passes on the
    # prose mention at step 1b ("Use the `Held-back docs:` line in Step 8's
    # template") even after the template block itself is deleted -- a substring
    # guard satisfied by an incidental use, found by mutation.
    report = SKILL[SKILL.index("## Step 8: Report"):]
    assert "Held-back docs:" in report, (
        "Step 8's TEMPLATE lost the held-back-docs block; the older instruction "
        "reports each one 'beside its 4a-SKIP entry', which does not exist when "
        "a cherry-picked branch merged fine"
    )
    assert "WITHOUT a 4a-SKIP" in report


def test_the_workflow_docs_carry_the_cherry_pick_caveat() -> None:
    """Both doc surfaces describe this filter; neither may describe it as absolute."""
    for name, text in (("WORKFLOW.md", WORKFLOW), ("WORKFLOW_GUIDE.md", GUIDE)):
        window = text.split("rev-list --count")[1][:1200]
        assert "not by itself a verdict" in window or "only means" in window, (
            f"{name} states the containment count as a verdict. Checking merely "
            "for the word 'cherry' nearby is not enough -- a mutation deleted the "
            "caveat sentence and left a later 'git cherry' mention standing"
        )
        assert "git cherry" in window, f"{name} lost the fallback command"


# --------------------------------------------------------------------------
# Q-194 -- the staging arm
# --------------------------------------------------------------------------

def test_neither_site_claims_the_prompt_rule_is_sufficient() -> None:
    """The overclaim, at BOTH sites -- the skill and the doctrine that mints it.

    Phase 200 fixed review-close and found adversarial-review.md carrying the
    identical sentence. Guarding one and not the other is how the class comes
    back: the shared file governs every review round in the repo.
    """
    for name, text in (("review-close/SKILL.md", SKILL),
                       ("_shared/adversarial-review.md", SHARED)):
        assert "portable floor** and is sufficient" not in text, (
            f"{name} asserts the prompt do-not-mutate rule is sufficient; it has "
            "been measured failing twice and is contained only by isolation"
        )
        assert "are the portable form and are sufficient" not in text, (
            f"{name} asserts sufficiency in the shared file's phrasing"
        )


def test_the_agent_prompt_forbids_creating_files_not_only_editing_them() -> None:
    """The dominant breach shape, and the one no `git diff` gate can see."""
    import re as _re
    # Matched by meaning, not by one spelling. Keyed to the literal "Do NOT",
    # this guard false-killed a behaviour-preserving reword to "Never" in the
    # phase's own battery -- over-strictness, the direction that hides.
    assert _re.search(r"(Do NOT|Never|Do not) create new files", SKILL), (
        "the Step 2b agent prompt no longer forbids file CREATION -- 'no edits "
        "to tracked files' is read as licence to add untracked ones, which are "
        "invisible to every git diff gate in this skill"
    )
    assert "not even untracked ones" in SKILL, (
        "the prohibition no longer names untracked files, which is the whole point"
    )


def test_the_no_isolation_harness_is_not_told_to_skip_the_assertion() -> None:
    """`none of this applies` switched the block off for the only harness needing it."""
    assert "none of this applies" not in SKILL, (
        "the 'none of this applies' escape is back -- it disables the primary-tree "
        "assertion for exactly the no-isolation harness that has no other backstop"
    )
    assert "the third one matters MORE, not less" in SKILL


def test_the_amend_site_warns_about_laundering_a_foreign_edit() -> None:
    assert "this is the step that launders a foreign edit in" in SKILL, (
        "the --amend site lost its warning; an unread `git commit --amend "
        "--no-edit` folds a stray Step-2b edit into the consolidation commit"
    )


def test_the_baseline_rationale_does_not_claim_self_reporting() -> None:
    """A false rationale this phase shipped and then had to correct.

    `>` creates the file before `git status` runs, so a baseline at a tracked
    path appears in BOTH readings and cancels in the delta. It never reports
    itself, in either location.
    """
    assert "so it cannot report itself" not in SKILL
    assert "report itself as the agents' mutation" not in SKILL, (
        "the false self-reporting rationale is back -- the real reason for "
        "sysop/runtime/ is that a tracked-path artefact pollutes the operator's "
        "own git status and is reachable by a later git add"
    )


def test_the_shared_doctrine_states_the_floor_is_not_sufficient() -> None:
    """A positive marker, because absence checks alone miss a reworded reversal.

    A mutation that replaced the corrected sentence with a differently-punctuated
    "are sufficient." slipped past every `not in` assertion above -- the banned
    phrasings are finite and the ways to reassert a claim are not. Requiring the
    corrective clause to be PRESENT closes that: the reversal has to delete it.
    """
    assert "not the same as sufficient" in SHARED, (
        "_shared/adversarial-review.md no longer says the portable floor is not "
        "sufficient -- this is the doctrine site, and it governs every review "
        "round in the repo including the ones that check for this defect"
    )
    assert "measured failing on two separate instruction texts" in SHARED, (
        "the evidence for the claim is gone; without it the sentence is an "
        "assertion rather than a measurement"
    )


def test_the_delta_result_is_blocking_not_advisory() -> None:
    """Laundering guard: keep the check, strip its force."""
    assert "do not carry it into Step 3b" in SKILL, (
        "the delta's verdict was made advisory -- a check whose result may be "
        "carried forward is not a gate, and this one exists to stop a foreign "
        "edit reaching Step 4c's consolidation commit"
    )
    # Scoped to the assertion block. A whole-file ban on "informational only"
    # is wrong: the Step 4c routing table legitimately calls its Roadmap column
    # informational, and two pre-existing uses would have made this guard red
    # on arrival. Derive the population, do not assume it.
    i = SKILL.index("A **third-command** difference")
    region = SKILL[i:i + 1200]
    assert "informational only" not in region, (
        "the delta's result was downgraded to informational inside the "
        "assertion block itself"
    )


def test_the_step6_note_still_says_a_cherry_pick_breaks_the_filter() -> None:
    """Laundering guard on the :1360 addition -- keep the words, invert the force."""
    assert "breaks the filter the same way a squash would" in SKILL, (
        "the Step 6 parenthetical was re-scoped to exclude cherry-pick, which "
        "restores the exemption reading that made the filing think this site "
        "was wrong in the first place"
    )
    assert "close enough to an ff-merge" not in SKILL


def test_the_behaviour_guards_docstring_does_not_reclaim_three_shapes() -> None:
    """The test file's own scope claim is part of the record it pins."""
    behaviour = (REPO / "tests/test_step4a_shared_file_behaviour.py").read_text()
    assert "does NOT for a cherry-pick" in behaviour, (
        "the module docstring reverted to claiming all three merge shapes -- "
        "that claim is what let the original falsehood ship pinned by a guard "
        "that never built two of them"
    )
    assert "in all three merge shapes." not in behaviour


def test_every_primary_worktree_fanout_sends_the_containment_rule() -> None:
    """Population guard -- derived from the source of truth, not from a list.

    Phase 200's round found the rule existed in exactly ONE of the skills that
    fan sub-agents into the user's primary worktree, while a sentence in
    `_shared/adversarial-review.md` waived the requirement for the others on
    the grounds that the rules "apply whether or not their prompts repeat
    them". A rule that is not in the prompt is not sent. This guard exists so
    the population cannot silently shrink back to one.
    """
    fanouts = ["review-close", "codebase-review", "security-audit"]
    missing = []
    for skill in fanouts:
        text = (REPO / f"core/skills/{skill}/SKILL.md").read_text()
        if "create new files" not in text or "Do NOT mutate repository state" not in text:
            missing.append(skill)
    assert not missing, (
        f"these fan-outs spawn agents into the primary worktree without the "
        f"containment rule in their prompts: {missing}. The prompt is the only "
        "constraint a no-isolation harness has, and it is already known to be "
        "insufficient -- absent entirely, there is nothing at all."
    )


def test_the_shared_file_does_not_waive_the_rule_for_other_fanouts() -> None:
    """The waiver was load-bearing in the wrong direction; keep it retired."""
    assert "whether or not their prompts repeat them" not in SHARED, (
        "the waiver is back -- it tells a reader that /codebase-review and "
        "/security-audit are covered by rules that are not in their prompts"
    )


def test_the_cherry_pick_discriminators_use_strict_inequalities() -> None:
    """Closes the one survivor the author-side battery left at 91%.

    A test can be defanged without deleting it: `_unapplied(...) > 0` becomes
    `>= 0` and the assertion is vacuous while still reading like a check. That
    mutation survived a 22-row battery because nothing looks at the operator.

    The governor's rule is that a survivor you decline to close must need a
    judgement no pattern can encode -- this one does not, so it is closed
    rather than filed as a residual.
    """
    behaviour = (REPO / "tests/test_step4a_shared_file_behaviour.py").read_text()
    for call, why in (
        ('_unapplied(repo, "HEAD", "feat/never")',
         "the never-merged control -- if this goes vacuous the fallback would "
         "consolidate genuinely unmerged work"),
        ('_unapplied(repo, "HEAD", "feat/conflict")',
         "the conflict-resolved-pick limit"),
        ('_count(repo, "feat/picked", "^HEAD")',
         "the cherry-pick's non-zero ancestry score, the whole premise of Q-189"),
    ):
        assert f"assert {call} > 0" in behaviour, (
            f"{call} is no longer asserted with a strict `> 0`: {why}. "
            "A `>= 0` here is always true and the test becomes decorative."
        )
    assert '_unapplied(repo, "HEAD", "feat/picked") == 0' in behaviour, (
        "the applied-branch assertion must be an exact 0 -- a `>= 0` or `< 1` "
        "would pass on a fallback that reports everything as unapplied"
    )


def test_the_fallback_is_framed_as_required_not_optional() -> None:
    """The last survivor of the author-side battery at 95%.

    The verdict guard above checks for "ask, not skip" -- but that phrase sits
    in a LATER sentence, so a mutation that keeps the command and rewrites the
    imperative ("A non-zero count is authoritative. Optionally, for curiosity,
    you may also run:") survives it. Keeping the words and stripping their
    force is the laundering shape this repo keeps re-learning, and it needs
    the framing pinned separately from the verdict.
    """
    assert "do not trust a non-zero count on its own" in SKILL, (
        "the fallback was reframed as optional. The command surviving in the "
        "file is not the point -- an operator who reads a non-zero count as "
        "authoritative never runs it, which is the pre-Phase-200 behaviour"
    )
    assert "Fall back before you skip" in SKILL
    for optional in ("Optionally", "for curiosity", "you may also run"):
        assert optional not in SKILL[SKILL.index("do not trust a non-zero count"):][:1500], (
            f"the fallback is hedged with {optional!r} -- it is required, not advisory"
        )
