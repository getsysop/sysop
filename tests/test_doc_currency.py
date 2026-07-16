"""Doc-currency guard — public stat sites must track PHASE_LOG.md.

Promoted from a recurring review finding: Phase 109.1 fixed a stale phase
count on the landing page, and by Phase 116 the same drift class had
re-accreted across README.md and docs/index.html (caught by a zero-context
cold-read exercise, Phase 117). Second recurrence -> deterministic check,
per the workflow's own promotion semantics.

PHASE_LOG.md is the anchor because it is the canonical public history and
is present in every distribution of the repo (the other place phases are
indexed is not).

Two tiers, on purpose:
- README.md and docs/index.html are current-state surfaces — their phase
  count must equal the max phase in PHASE_LOG.md.
- docs/workflow.html is a dated snapshot ("as of Phase N"), refreshed by
  deliberate currency passes (Phases 86, 109) — its own phase stamps must
  agree with each other and never run ahead of PHASE_LOG.md, but may lag.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read(rel):
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _max_phase():
    nums = [int(n) for n in re.findall(r"^## Phase (\d+)", _read("PHASE_LOG.md"), re.M)]
    assert nums, "PHASE_LOG.md has no '## Phase N' headings"
    return max(nums)


def test_readme_phase_count_is_current():
    hits = re.findall(r"(\d+) phases", _read("README.md"))
    assert len(hits) == 1, f"expected exactly one 'N phases' claim in README.md, found {hits}"
    assert int(hits[0]) == _max_phase(), (
        f"README.md claims {hits[0]} phases; PHASE_LOG.md is at {_max_phase()}"
    )


def test_index_phase_tile_is_current():
    m = re.search(
        r'<div class="num">(\d+)</div><div class="lbl">Documented phases</div>',
        _read("docs/index.html"),
    )
    assert m, "landing-page 'Documented phases' stat tile not found"
    assert int(m.group(1)) == _max_phase(), (
        f"docs/index.html tile says {m.group(1)}; PHASE_LOG.md is at {_max_phase()}"
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
    assert sites <= {n for n in range(_max_phase() + 1)}, (
        f"monograph claims Phase {max(sites)}, ahead of PHASE_LOG.md ({_max_phase()})"
    )
