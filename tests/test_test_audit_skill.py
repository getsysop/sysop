"""Drift guards for `/test-audit` (Phase 137).

Two legs of the 2026-07-19 cross-harness-comparison item, both filed against
`core/skills/test-audit/SKILL.md`:

- (a) The skill's Step 1 read-list omitted `security_map.md`, yet the rubric it
  applies (`_shared/test-assessment-rubric.md`) ranks a `security_map.md`-flagged
  surface as a top-tier Tier-1 target. The skill applied a rubric that cited a
  signal it never opened — Tier-1 "audit hardest" ordering was miscalibrated by
  construction. These tests pin the read back in AND lock the rubric↔skill
  dependency so it cannot silently re-drift.
- (b) The read-only-guard blockquote overclaimed: `disallowed-tools` frontmatter
  only fires when Claude Code *invokes* the skill, not under path-based
  invocation ("read this SKILL.md and follow it" — the only option on non-Claude
  harnesses). The old unconditional wording is guarded out and the caveat pinned.
"""

from pathlib import Path

_SKILLS = Path(__file__).resolve().parent.parent / "core" / "skills"
_SHARED = _SKILLS / "_shared"

_TEST_AUDIT = (_SKILLS / "test-audit" / "SKILL.md").read_text(encoding="utf-8")
_RUBRIC = (_SHARED / "test-assessment-rubric.md").read_text(encoding="utf-8")

# Distinctive item-3 anchor — the security_map read added to Step 1's read-list.
_READLIST_ANCHOR = 'the *second* "audit this hardest" signal'


def test_rubric_depends_on_security_map():
    """Sanity: the dependency the (a) fix restores actually exists. If the rubric
    ever stops citing security_map.md, the read below is no longer load-bearing
    and this whole guard should be revisited (fail loudly rather than silently
    protect a dead invariant)."""
    assert "security_map.md" in _RUBRIC, (
        "rubric no longer cites security_map.md — the /test-audit read it drove "
        "may no longer be load-bearing; revisit test_test_audit_reads_security_map"
    )


def test_test_audit_reads_security_map():
    """(a) The skill must read security_map.md — the signal its own rubric ranks
    top-tier for Tier-1 'audit hardest' ordering. This is the exact drift the
    cross-harness reference cell caught (2026-07-19): a rubric depending on a
    file the skill never opened."""
    assert _READLIST_ANCHOR in _TEST_AUDIT, (
        "test-audit lost the security_map.md read-list item (Step 1) — its Tier-1 "
        "ranking again depends on a signal it never opens"
    )
    assert ".claude/security_map.md" in _TEST_AUDIT
    # The read must be actually consumed downstream, not a dead read: folded into
    # Step 2 scoping and named in Step 4 ranking (parallel to the crown-jewel signal).
    assert "surfaces `security_map.md` flags" in _TEST_AUDIT, (
        "security_map read is not consumed in Step 2 candidate scoping"
    )
    assert "`security_map.md`-flagged surface ranks high" in _TEST_AUDIT, (
        "security_map is not named as a severity signal in Step 4 ranking"
    )


def test_security_map_readlist_item_is_not_a_false_placeholder_premise():
    """(a), adversarial-review catch: the shipped map is half-concrete (maps are
    never installer-substituted, Phase 55/120) — pack sections stay placeholder,
    core workflow-meta sections ship concrete. The item must not claim the whole
    file 'carries placeholder globs', the Phase-120 false-premise trap."""
    assert "half-concrete" in _TEST_AUDIT
    assert "maps are never installer-substituted" in _TEST_AUDIT
    # And the rubric's negative discipline must still govern the concrete sections,
    # so infra/config/meta don't auto-become Tier-1 test candidates.
    assert "don't become test candidates just because the map lists them" in _TEST_AUDIT


def test_readonly_guard_prose_is_not_overclaimed():
    """(b) The guard blockquote must not claim the frontmatter unconditionally
    'removes the file-write tools while this skill is active' — it fires only on
    skill *invocation*, never under path-based 'read SKILL.md and follow it'."""
    assert "removes the file-write tools while this skill is active" not in _TEST_AUDIT, (
        "the overclaimed unconditional read-only-guard wording is back"
    )
    assert "only when the harness activates the skill" in _TEST_AUDIT
    assert "path-based invocation" in _TEST_AUDIT
