"""Guard: the claude-security no-overlap claim is never stated unscoped.

Why this guard exists, in the workflow's own terms:

Phase 144 shipped "the head-to-head measured zero overlap between the two
tools' findings" at three sites, stated flatly — no n, no codebase. Phase 145
had to go back and rescope all three, because everything around that sentence
was carefully hedged and the one unscoped claim was the outlier against the
honest-limits discipline Phases 98/140/141 exist to enforce. Nothing pinned
the fix, so the next author to restate the claim inherited nothing.

Phase 146 propagated the claim to two *public* surfaces (the monograph and the
loop-mode page) as part of giving the ingest a public home. That is the second
occurrence of a claim-scoping defect in the same claim -> promote it to a
deterministic check, which is the same promotion rule the loop applies to
review findings.

The check is deliberately keyed on the *claim*, not on one phrasing: the five
sites word it two different ways already ("zero overlapping findings" in the
shipped skill/spec/parser, "did not overlap at all" in the two public pages),
so a phrase-exact guard would have silently missed the sites this phase added.

Two scope calls, stated rather than left implicit:

1. Consumer-facing surfaces only (`core/`, `docs/`, `README.md`). `PHASE_LOG.md`
   and `REVIEW_CHECKLIST.md` restate the claim as project history, not as a
   claim made to a reader, and they carry their own scoping prose already.
2. The completeness leg asserts an *exact* site set. A sixth site is a
   deliberate call — it must be added here, which is what forces the author to
   look at the scoping rule rather than inherit it silently.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The claim itself, in either of the two phrasings that ship today.
CLAIM = re.compile(r"zero overlapping findings|did not overlap at all", re.I)

# The load-bearing disclaimer Phase 145 added. Non-negotiable at every site.
NOT_GENERAL = re.compile(r"not a general property", re.I)

# At least one concrete scoping detail must accompany the disclaimer, so the
# reader learns *how* narrow the run was, not merely that it was narrow.
SCOPE_DETAIL = re.compile(
    r"one run|one head-to-head|single production codebase|single codebase"
    r"|one pinned commit|one commit|one codebase",
    re.I,
)

# Every consumer-facing file that makes the claim. Exact set on purpose.
CLAIM_SITES = {
    "core/skills/security-audit/SKILL.md",
    "core/companion/docs/WORKFLOW.md",
    "core/companion/scripts/ingest_security_report.py",
    "docs/workflow.html",
    "docs/loop-mode.md",
}

# Where a consumer-facing claim could live. Excludes the history files by design.
SCAN_ROOTS = ("core", "docs")
SCAN_FILES = ("README.md",)
SCAN_SUFFIXES = {".md", ".html", ".py", ".yml", ".yaml", ".sh"}

# How far from the claim the scoping may sit. Generous enough to span a
# sentence boundary and a wrapped docstring, tight enough that scoping prose
# from an unrelated neighbouring paragraph cannot satisfy it.
WINDOW = 700


def _read(rel):
    return (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _candidate_files():
    seen = []
    for root in SCAN_ROOTS:
        for p in sorted((REPO_ROOT / root).rglob("*")):
            if p.is_file() and p.suffix in SCAN_SUFFIXES:
                seen.append(p.relative_to(REPO_ROOT).as_posix())
    for f in SCAN_FILES:
        if (REPO_ROOT / f).is_file():
            seen.append(f)
    return seen


def _claim_windows(text):
    """Whitespace-normalized text around each claim occurrence."""
    out = []
    for m in CLAIM.finditer(text):
        chunk = text[max(0, m.start() - WINDOW): m.end() + WINDOW]
        out.append(" ".join(chunk.split()))
    return out


def test_every_claim_site_carries_the_not_a_general_property_disclaimer():
    for rel in sorted(CLAIM_SITES):
        windows = _claim_windows(_read(rel))
        assert windows, (
            f"{rel} is listed as a no-overlap claim site but the claim is no "
            "longer there — if the claim was removed, drop it from "
            "CLAIM_SITES; the guard must never protect a dead invariant"
        )
        for i, w in enumerate(windows):
            assert NOT_GENERAL.search(w), (
                f"{rel} (claim occurrence {i + 1}) states the claude-security "
                "no-overlap result without 'not a general property' nearby. "
                "Phase 145 rescoped this exact claim at three sites for this "
                f"reason. Context: ...{w[:320]}..."
            )


def test_every_claim_site_states_a_concrete_scope():
    for rel in sorted(CLAIM_SITES):
        for i, w in enumerate(_claim_windows(_read(rel))):
            assert SCOPE_DETAIL.search(w), (
                f"{rel} (claim occurrence {i + 1}) disclaims generality but "
                "never says how narrow the run was. State the n: one "
                "head-to-head, a single production codebase, one pinned "
                f"commit. Context: ...{w[:320]}..."
            )


def test_no_unlisted_consumer_facing_site_makes_the_claim():
    found = {rel for rel in _candidate_files() if CLAIM.search(_read(rel))}
    unlisted = found - CLAIM_SITES
    assert not unlisted, (
        f"new consumer-facing site(s) restate the no-overlap claim: "
        f"{sorted(unlisted)}. Add them to CLAIM_SITES so the scoping rule is "
        "a deliberate call at each site rather than something a new surface "
        "inherits by accident"
    )
    missing = CLAIM_SITES - found
    assert not missing, (
        f"CLAIM_SITES lists site(s) that no longer make the claim: "
        f"{sorted(missing)} — prune the list rather than leaving a dead entry"
    )


def test_the_ingest_has_a_public_surface():
    """Leg (b) of Phase 146: the announce's Beat 1 hook needs a page to land on.

    The monograph is the deep-read surface; loop-mode.md is where the
    post-Phase-132 funnel actually sends a newcomer, and loop mode ships the
    parser plus both of its allow-rules. Losing either in a future doc rewrite
    would silently re-open the gap Phase 146 was filed to close.
    """
    for rel in ("docs/workflow.html", "docs/loop-mode.md"):
        text = _read(rel)
        assert "claude-security" in text, (
            f"{rel} no longer mentions the claude-security ingest — Phase 146 "
            "added it as the ingest's public surface (the announce hooks on "
            "the plugin and needs somewhere to land)"
        )
        assert "[reported]" in text, (
            f"{rel} mentions the ingest without its provenance tag; ingested "
            "findings are never promoted to [verified] and the public surface "
            "should not imply otherwise"
        )
