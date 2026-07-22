"""Drift guards for Phase 138 — two-tier fan-out attestation.

Ratified as Option 1 (commit `86b7e8a`): closes leg (c) of the 2026-07-19
`/test-audit` reference-cell item (the `[verified]`/`[reported]` provenance
marker) together with the 2026-07-20 fan-out-attestation item.

- **Tier 1 — provenance marker (universal).** Every finding in `/codebase-review`,
  `/security-audit`, and `/test-audit` carries `[verified]` / `[reported]`. Ships
  on every run, inline or fan-out. A *self-declared honesty label, not a
  machine-checked guarantee* — the prose must say so, so `[verified]` is never
  read as verification.
- **Tier 2 — evidence footer + orchestrator sampling (fan-out only).** Sub-agents
  return files-opened-vs-assigned + tool mix; the orchestrator flags a low-opened
  batch (mandatory) and samples 2–3 claims (advisory) before merging; the round
  summary carries a provenance class, never a bare %.

The single-sourced contract lives in `_shared/fanout-evidence.md`; the skills cite
it (they do not duplicate it). These are string-anchor drift guards — they pin the
load-bearing wording so a future edit cannot silently drop a leg.
"""

from pathlib import Path

_SKILLS = Path(__file__).resolve().parent.parent / "core" / "skills"
_SHARED = _SKILLS / "_shared"

_PARTIAL = (_SHARED / "fanout-evidence.md").read_text(encoding="utf-8")
_CODEBASE = (_SKILLS / "codebase-review" / "SKILL.md").read_text(encoding="utf-8")
_SECURITY = (_SKILLS / "security-audit" / "SKILL.md").read_text(encoding="utf-8")
_TEST_AUDIT = (_SKILLS / "test-audit" / "SKILL.md").read_text(encoding="utf-8")

_FANOUT_SKILLS = {"codebase-review": _CODEBASE, "security-audit": _SECURITY}
_ALL_SKILLS = {**_FANOUT_SKILLS, "test-audit": _TEST_AUDIT}

# The disclaimer that must accompany the marker everywhere it is defined, so
# `[verified]` is never over-read as machine verification.
_DISCLAIMER = "self-declared honesty label, not a machine-checked guarantee"


# --- The shared contract exists and defines both tiers -----------------------

def test_partial_exists_and_defines_tier1_marker():
    assert "# Fan-out evidence & finding provenance" in _PARTIAL
    assert "`[verified]`" in _PARTIAL and "`[reported]`" in _PARTIAL
    # The universal-floor framing and the anti-overclaim disclaimer.
    assert _DISCLAIMER in _PARTIAL, "the marker's honesty-label disclaimer is gone"


def test_partial_defines_the_evidence_footer():
    """The footer (files-opened-vs-assigned) is the load-bearing mechanism — it is
    what makes the 8-of-82 over-attestation *falsifiable*. Pin its shape."""
    assert "EVIDENCE FOOTER" in _PARTIAL
    assert "Assigned:" in _PARTIAL and "Opened:" in _PARTIAL
    assert "Tools:" in _PARTIAL
    # And the honest framing that the footer is itself self-reported.
    assert "commitment device, not a guarantee" in _PARTIAL


def test_partial_defines_merge_discipline_with_correct_teeth():
    """Cheap parts mandatory, expensive part advisory (the ratified cost guard) —
    and the teeth bound to the RIGHT leg. Asserting MANDATORY/ADVISORY appear
    *somewhere* would stay green if a regression flipped them; bind each to its leg."""
    assert "Low-opened-ratio flag — MANDATORY" in _PARTIAL
    assert "Sample re-read — ADVISORY" in _PARTIAL
    assert "Provenance class in the round summary — MANDATORY" in _PARTIAL
    assert "never a bare" in _PARTIAL
    # Sampling reads INWARD (re-opens the cited site); it is NOT the outward
    # amplification read. Guard the correction of the false "same read" claim that a
    # first-pass review talked us into — amplification greps outward for siblings and
    # never re-opens the cited file:line, so "the read you already do" verifies nothing.
    assert "reads *inward*" in _PARTIAL and "reads *outward*" in _PARTIAL
    assert "the read you already do IS the verification" not in _PARTIAL, (
        "the false 'sampling == amplification' claim is back"
    )


def test_partial_defines_the_reported_consumer_story():
    """A marker with no consumer is decoration. `[reported]` must route to a
    re-read before any fix is applied — never auto-apply blind."""
    assert "re-read the site before applying a fix to a" in _PARTIAL
    assert "never auto-apply blind" in _PARTIAL


# --- Tier 1: the marker + disclaimer land in ALL THREE skills' output ---------

def test_tier1_marker_present_in_every_skill_output():
    # Two review skills use the `[verified|reported]` slot on the finding row.
    for name, text in _FANOUT_SKILLS.items():
        assert "`[verified|reported]`" in text, f"{name} lost the Tier-1 row marker"
    # test-audit composes the marker with its existing confidence bracket, and shows
    # both provenance values (incl. the coverage-artifact [reported] lead).
    assert "[high] [verified]" in _TEST_AUDIT
    assert "[low] [reported]" in _TEST_AUDIT, (
        "test-audit must illustrate the [reported] case (a coverage-artifact lead "
        "on a module it did not open)"
    )


def test_tier1_disclaimer_present_in_every_skill():
    """`[verified]` must never be oversold as machine-verified — the disclaimer
    ships next to the marker in every skill, not only in the shared partial."""
    for name, text in _ALL_SKILLS.items():
        assert _DISCLAIMER in text, f"{name} defines the marker without the disclaimer"


def test_every_skill_cites_the_single_sourced_partial():
    for name, text in _ALL_SKILLS.items():
        assert "fanout-evidence.md" in text, f"{name} does not cite the shared contract"


# --- Tier 2: fan-out skills carry the footer/sampling wiring ------------------

def test_fanout_skills_define_the_sub_agent_return_contract():
    """Dispatch prompts say what to CHECK; the return contract says what to RETURN
    (a footer attaches to a defined return shape, not to thin air)."""
    for name, text in _FANOUT_SKILLS.items():
        assert "Sub-agent return contract" in text, f"{name} has no return contract"
        assert "evidence footer" in text, f"{name} dispatch omits the evidence footer"


def test_fanout_row_defaults_to_reported_until_orchestrator_reads():
    """The load-bearing leg both diff reviewers flagged as unstated in the first
    build: the merge blocks gave only the UPGRADE (sampled → verified) and never the
    DEFAULT, so a sub-agent's self-`[verified]` (incl. the 8-of-82 liar's) would
    launder onto the row unchallenged — the exact over-attestation this phase exists
    to stop. Pin the merge-time default and the two-layer emitter rule."""
    for name, text in _FANOUT_SKILLS.items():
        assert "Row provenance (mandatory)" in text, f"{name} states no merge-time default"
        assert "did **not** itself re-read carries `[reported]`" in text, (
            f"{name} does not default an un-re-read fan-out finding to [reported]"
        )
    # The partial states the two-layer rule: sub-agent self-declares (input); the
    # orchestrator is the emitter at merge and must not copy self-[verified] through.
    assert "the emitter changes at merge" in _PARTIAL
    assert "onto the row unchallenged" in _PARTIAL


def test_fanout_skills_audit_coverage_before_merging():
    for name, text in _FANOUT_SKILLS.items():
        assert "Low-opened-ratio flag (mandatory" in text, (
            f"{name} does not flag a hollow batch as a coverage gap"
        )
        # The provenance/coverage line in the post-scan report block.
        assert "Fan-out coverage:" in text and "Provenance:" in text, (
            f"{name} round summary lost its provenance class"
        )


# --- test-audit: Tier 1 always, Tier 2 only if it fans out -------------------

def test_test_audit_tier2_is_conditional_not_unconditional():
    """test-audit runs single-agent inline, so it gets the Tier-1 marker
    unconditionally but the fan-out footer only *if* it fans out (the `--all`
    sub-auditor case the 0b run exhibited). Guard the conditional framing so a
    future edit can't turn it into an unconditional (and false) fan-out step."""
    assert "If you fan out" in _TEST_AUDIT
    assert "§ Tier 2" in _TEST_AUDIT
    assert "the single-agent base path above has no fan-out" in _TEST_AUDIT
