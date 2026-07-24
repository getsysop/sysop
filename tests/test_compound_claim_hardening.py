"""Drift guards for Phase 140 — compound-claim decomposition + review-family borrows.

Evidence base (a 2026-07 cross-model review comparison; analysis is maintainer-local):
a same-family adversarial re-check ratified every partial-refutation dismissal — the
grader refuted one clause of a compound finding and silently dropped the rest, and the
mechanism only ever fires in one direction (real → apparent false positive). What
recovered the dropped clauses was a re-adjudication constrained to trace every cited
site, fresh-context. These guards pin the countermeasure prose:

- **Classification rubric** (`_shared/adversarial-review.md`): decompose-before-reject,
  every-clause rejection rationale, the fresh-context re-adjudication for High/security
  rejections (portable framing — fresh context required, cross-family never assumed).
- **Fan-out merge** (`_shared/fanout-evidence.md` + both review skills): drops are
  clause-by-clause; the rule binds on every drop even though sampling stays advisory.
- **Review-family borrows** (ride-alongs from the official plugins' source read,
  `tools/REVIEW_FAMILY_PLUGIN_NOTES.md`): silent-failure checklist depth,
  verify-the-cited-rule, the dispatch-side do-not-report taxonomy (with its
  incremental-only scoping — losing that clause would wrongly exclude pre-existing
  issues from whole-repo rounds), name-the-regression on Tier-1 test recommendations.
"""

from pathlib import Path

_SKILLS = Path(__file__).resolve().parent.parent / "core" / "skills"
_SHARED = _SKILLS / "_shared"

_ADVERSARIAL = (_SHARED / "adversarial-review.md").read_text(encoding="utf-8")
_FANOUT = (_SHARED / "fanout-evidence.md").read_text(encoding="utf-8")
_RUBRIC = (_SHARED / "test-assessment-rubric.md").read_text(encoding="utf-8")
_CODEBASE = (_SKILLS / "codebase-review" / "SKILL.md").read_text(encoding="utf-8")
_SECURITY = (_SKILLS / "security-audit" / "SKILL.md").read_text(encoding="utf-8")

_REVIEW_SKILLS = {"codebase-review": _CODEBASE, "security-audit": _SECURITY}


# --- Classification rubric: decompose before rejecting ------------------------

def test_rubric_defines_compound_decomposition():
    assert "Compound findings — decompose before rejecting" in _ADVERSARIAL
    assert "refuting one clause does not reject the finding" in _ADVERSARIAL


def test_rubric_states_the_directional_evidence():
    """The rule's justification is directional: partial refutation only ever
    launders real findings into apparent FPs. Losing the direction invites a
    future edit to 'balance' the rule against a failure mode that doesn't exist."""
    assert (
        "only ever turns a *real* finding into an apparent false positive"
        in _ADVERSARIAL
    )


def test_rubric_requires_every_clause_in_rejection_rationale():
    assert "must name *every* clause" in _ADVERSARIAL


def test_rubric_requires_fresh_context_readjudication_portably():
    """High/security rejections get a second, independent clause-by-clause pass.
    Portability guard: fresh context is the requirement — a different model family
    sharpens it but is never assumed (bash-installer consumers may have one model)."""
    assert "re-adjudicate the rejection clause-by-clause" in _ADVERSARIAL
    assert "fresh context is the requirement" in _ADVERSARIAL


def test_rubric_second_pass_has_a_no_spawn_fallback():
    """Second-pass reviewer catch: the reviewer-executor leaf self-classifies and
    must not nest, and bash-installer consumers may not spawn at all — mandated
    'second pass or nothing' would silently no-op exactly there. The rule must
    carry the loud-record fallback so a High rejection is never silently absorbed."""
    assert "do not silently absorb the rejection" in _ADVERSARIAL
    assert "a loud per-clause record where not" in _ADVERSARIAL


def test_prompt_template_asks_reviewer_to_enumerate_clauses():
    """Decomposition starts at the finder: an unlisted clause is a clause the
    classifier can silently drop."""
    assert "enumerate each claim/site explicitly" in _ADVERSARIAL


# --- Fan-out merge: drops are clause-by-clause --------------------------------

def test_fanout_merge_decomposes_before_dropping():
    assert "Decompose compound findings before dropping" in _FANOUT
    assert "clause-by-clause" in _FANOUT
    # Binding scope: drops AND downgrades (a High→Low on one refuted clause is the
    # same laundering as a drop), even though sampling stays advisory — all halves
    # must survive, or the rule is either ignored or inflates sampling.
    assert "binds on every drop *and every downgrade*" in _FANOUT
    assert "the sampling itself stays advisory" in _FANOUT


def test_review_skills_mirror_the_clause_only_drop():
    for name, text in _REVIEW_SKILLS.items():
        assert "decomposing compound findings first" in text, (
            f"{name} merge block lost the compound-claim decomposition"
        )
        assert "refutes *that clause only*" in text, (
            f"{name} merge block can again drop a whole finding on one refuted clause"
        )
        assert "binds on every drop *and every downgrade*" in text, (
            f"{name} merge block lets a downgrade escape the clause-by-clause rule"
        )
        # Single-site multi-claim coverage: the remedy is adjudicate remaining
        # CLAUSES (site re-checks only where other sites exist) — a sites-only
        # remedy is a no-op on a one-site compound finding.
        assert "adjudicate its remaining clauses" in text, (
            f"{name} merge remedy no-ops on single-site multi-claim findings"
        )


def test_dedup_is_a_covered_drop_path():
    """Reviewer catch: Step 4 dedup skips a whole finding on a one-site fuzzy
    match — an uncovered drop path upstream of the merge discipline. Pin the
    clause-by-clause dedup rule in both skills."""
    for name, text in _REVIEW_SKILLS.items():
        assert "Compound findings dedup clause-by-clause" in text, (
            f"{name} Step 4 dedup can drop a compound finding whole again"
        )


# --- Verify-the-cited-rule (borrow 2) -----------------------------------------

def test_review_skills_verify_the_cited_rule():
    """A finding citing a convention bullet gets the bullet re-read. Rationale
    correction from the review pass: the fire ledger (5e) is fed only by
    mechanical pre-scan stale-verdicts, so a mis-cited LLM finding never reaches
    it — the true cost is a bogus task in the rule's name + corrupted round
    evidence. Pin the corrected rationale, not the disproven one."""
    for name, text in _REVIEW_SKILLS.items():
        assert "Verify the cited rule (mandatory, cheap)" in text, (
            f"{name} lost the verify-the-cited-rule merge check"
        )
        assert "files a bogus task in that rule's name" in text, (
            f"{name} lost the mis-citation cost rationale"
        )


# --- Do-not-report taxonomy at dispatch (borrow 3) ----------------------------

def test_review_skills_carry_dispatch_side_do_not_report_list():
    for name, text in _REVIEW_SKILLS.items():
        assert "Do-not-report list" in text, f"{name} dispatch has no negative list"


def test_pre_scan_suppression_keys_on_executed_checks():
    """Reviewer catch (the Phase-135 discipline): suppressing agents on a check
    that silently SKIPPED (missing scanner binary) or FAILED would create a
    coverage hole nothing reports. The suppression list must key on the
    accounting's executed set, never bare checks.yml membership."""
    for name, text in _REVIEW_SKILLS.items():
        assert "actually executed this round" in text, (
            f"{name} suppresses agents on checks.yml membership, not executed checks"
        )
        assert "never a check it reported `skipped` or `failed`" in text, (
            f"{name} lost the skipped/failed carve-out"
        )


def test_incremental_exclusion_is_actionable():
    """Reviewer catch: agents receive whole files with no hunk data, so the
    exclusion is unactionable unless the orchestrator states the round window."""
    for name, text in _REVIEW_SKILLS.items():
        assert "states the last-round date in the prompt" in text, (
            f"{name} incremental exclusion gives agents no way to know what changed"
        )


def test_pre_existing_exclusion_is_incremental_only():
    """The falsehood-shaped hazard in borrow 3: the pre-existing-issue exclusion
    imported from diff-scoped tools must stay scoped to incremental rounds —
    whole-repo rounds exist to find pre-existing issues. Pin the carve-out in both
    skills so a future edit cannot make the exclusion unconditional."""
    for name, text in _REVIEW_SKILLS.items():
        assert "On incremental rounds only" in text, (
            f"{name} pre-existing exclusion lost its incremental-only scoping"
        )
        assert "whole-repo rounds exist to find pre-existing issues" in text, (
            f"{name} lost the full-scan carve-out clause"
        )


def test_silenced_issue_flip_reports_the_suppression():
    """Respecting an in-code silence must not become blanket deference: a plainly
    wrong rationale flips the target — report the suppression itself."""
    for name, text in _REVIEW_SKILLS.items():
        assert "report the suppression as the finding" in text, (
            f"{name} lost the report-the-suppression flip"
        )


# --- Silent-failure checklist depth (borrow 1) --------------------------------

def test_codebase_review_has_silent_failure_group():
    assert "**Silent failures:**" in _CODEBASE
    for anchor in (
        "Retry exhaustion",
        "mock or stub fallback reachable in production",
        "optional-chaining",
    ):
        assert anchor in _CODEBASE, f"3a silent-failure group lost: {anchor}"


def test_adversarial_dimension_3_enriched():
    assert "retry logic that exhausts its attempts" in _ADVERSARIAL
    assert "optional-chaining / null-coalescing" in _ADVERSARIAL


def test_stale_3a_range_reference_stays_gone():
    """Phase 140 fixed the legacy '(3a–3g)' range (general checks all live in 3a);
    keep it from re-accreting via copy-paste from an old revision."""
    assert "3a–3g" not in _CODEBASE and "3a-3g" not in _CODEBASE


# --- Name-the-regression on Tier 1 (borrow 4) ---------------------------------

def test_tier1_names_the_regression():
    assert "Name the regression." in _RUBRIC
    assert "specific failure the test would catch" in _RUBRIC
    # The symmetry rationale: Tier 2b already demands named evidence; Tier 1 now too.
    assert "Tier 2b already demands named evidence" in _RUBRIC
