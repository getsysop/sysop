"""Doc-currency guard — phase-count claims are retired from current-state surfaces.

History of this guard, in the workflow's own terms:
- Phase 109.1 fixed a stale phase count on the landing page (first occurrence).
- Phase 117: the same drift class had re-accreted across README.md and
  docs/index.html (caught by a zero-context cold-read exercise). Second
  recurrence -> promoted to a deterministic check that forced the counts
  current on every phase close.
- Phase 118: the stat itself was demoted. Two cold-read rounds showed the
  raw count is a non-signal to outsiders (round 2 readers anchored maturity
  on the release date and consumer count instead), so the number was removed
  from current-state surfaces and this check inverted into a ratchet: a
  phase count must NOT reappear on README or the landing page. That is the
  workflow's demotion pattern — retire the rule, keep a regression guard.

The monograph (docs/workflow.html) is different in kind: it is a dated
snapshot ("as of Phase N"), refreshed by deliberate currency passes
(Phases 86, 109). Its stamp dates the document rather than counting
progress, so it stays — checked for internal self-consistency and for
never running ahead of PHASE_LOG.md (the canonical public history).
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Matches a numeric phase-count claim: "117 phases", "117 documented phases",
# "117 shipped phases" — the shapes the stat appeared in before retirement.
PHASE_COUNT_CLAIM = re.compile(r"\b\d+\s+(?:documented\s+|shipped\s+)?phases\b", re.I)


def _read(rel):
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _max_phase():
    nums = [int(n) for n in re.findall(r"^## Phase (\d+)", _read("PHASE_LOG.md"), re.M)]
    assert nums, "PHASE_LOG.md has no '## Phase N' headings"
    return max(nums)


def test_readme_has_no_phase_count_claim():
    hits = PHASE_COUNT_CLAIM.findall(_read("README.md"))
    assert not hits, (
        f"README.md has re-grown a phase-count claim {hits}; the stat was "
        "retired by Phase 118 (a non-signal that drifts) — point at "
        "PHASE_LOG.md instead of counting it"
    )


def test_index_has_no_phase_count_tile():
    text = _read("docs/index.html")
    assert "Documented phases" not in text and not PHASE_COUNT_CLAIM.search(text), (
        "docs/index.html has re-grown a phase-count stat; the tile was "
        "retired by Phase 118 — the stat band is the three evidence-corpus "
        "numbers only"
    )


def test_monograph_is_self_consistent_and_never_ahead():
    text = _read("docs/workflow.html")
    hero = re.search(
        r'<div class="hero-stat-fig">(\d+)</div>\s*<div class="hero-stat-label">Shipped phases</div>',
        text,
    )
    assert hero, "monograph 'Shipped phases' hero stat not found"
    # Dated phase stamps: 'as of <em>Phase N</em> · YYYY-MM-DD' (colophon prose)
    # and '<li>Phase N · YYYY-MM-DD</li>' (colophon source list).
    stamps = re.findall(r"Phase (\d+)(?:</em>)? · \d{4}-\d{2}-\d{2}", text)
    assert stamps, "monograph has no dated 'Phase N · YYYY-MM-DD' stamps"
    sites = {int(hero.group(1))} | {int(s) for s in stamps}
    assert len(sites) == 1, (
        f"monograph phase stamps disagree with each other: {sorted(sites)} "
        "(hero stat + colophon must be bumped together in a currency pass)"
    )
    assert max(sites) <= _max_phase(), (
        f"monograph claims Phase {max(sites)}, ahead of PHASE_LOG.md ({_max_phase()})"
    )
