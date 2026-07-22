"""Drift guards for Phase 139 — `<project>/CLAUDE.md` § "Map coverage exclusions"
scope disambiguation (the 2026-07-20 cross-harness comparison cell-3 item).

An external agent read `§ "Map coverage exclusions"` ambiguously: it was unclear
whether the listed paths are dropped only from the Step 2a *map-coverage audit* or
also from the Step 1 *review/scan manifest*. The two readings produce different
in-scope file counts. Phase 139 documents the NARROW reading — the section scopes
the coverage audit only; it is not a review/scan-exclusion mechanism — in both
review skills' Step 2a and in WORKFLOW.md §6.1 (the consumer-authoring schema).

A secondary note fixes a glob-matching gotcha: `dir/**/*.py` must count files
sitting directly in `dir/` (interpret `**/` as zero-or-more), so a coverage audit
does not false-flag direct-children files as unmatched.

These are string-anchor drift guards — they pin the load-bearing wording so a
future edit cannot silently re-open the ambiguity or drop the glob caveat.
"""

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SKILLS = _ROOT / "core" / "skills"

_CODEBASE = (_SKILLS / "codebase-review" / "SKILL.md").read_text(encoding="utf-8")
_SECURITY = (_SKILLS / "security-audit" / "SKILL.md").read_text(encoding="utf-8")
_WORKFLOW = (_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md").read_text(
    encoding="utf-8"
)

_REVIEW_SKILLS = {"codebase-review": _CODEBASE, "security-audit": _SECURITY}


# --- The narrow-reading scope note ships in BOTH review skills -----------------

def test_both_skills_state_the_audit_is_map_coverage_only():
    # The load-bearing clause: the exclusion list scopes the map-coverage audit,
    # not the review/scan manifest. Pinned in both skills (parallel-skill invariant).
    for name, text in _REVIEW_SKILLS.items():
        assert "map-coverage audit only" in text, (
            f"{name}: the Step 2a scope note lost its 'map-coverage audit only' "
            "clause — the narrow-reading disambiguation regressed"
        )


def test_both_skills_deny_manifest_exclusion_semantics():
    # The section must not be re-read as a review/scan-exclusion knob. Each skill
    # uses its own manifest verb.
    assert "not a review-exclusion mechanism" in _CODEBASE
    assert "not a scan-exclusion mechanism" in _SECURITY


# --- The glob-matching caveat ships in BOTH review skills ----------------------

def test_both_skills_carry_the_zero_or_more_glob_caveat():
    for name, text in _REVIEW_SKILLS.items():
        assert "zero or more" in text, (
            f"{name}: the 2a-1 glob-matching caveat (`**/` = zero or more path "
            "components) regressed — direct-children files can be false-flagged as gaps"
        )


# --- WORKFLOW.md §6.1 documents the audit-skill CLAUDE.md sections -------------

def test_workflow_documents_the_audit_skill_sections():
    for heading in (
        "## Scope mapping",
        "## Map coverage exclusions",
        "## Security-critical always-include files",
        "## High-value files for review",
    ):
        assert heading in _WORKFLOW, (
            f"WORKFLOW.md §6.1 no longer documents `{heading}` — the "
            "consumer-authoring schema for the audit-skill sections drifted"
        )


def test_workflow_states_the_narrow_exclusion_semantics():
    # The authoritative narrow-semantics statement lives at the authoring source.
    assert "does not change the review/scan manifest" in _WORKFLOW
