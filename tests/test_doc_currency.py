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



# A date in either notation the document uses: 2026-08-02 or 2026.08.02.
_DATE = r"\d{4}[.-]\d{2}[.-]\d{2}"


def _iso(d: str) -> str:
    return d.replace(".", "-")


def _colophon(text: str) -> str:
    """The colophon block. Stamp matching is scoped here so that prose elsewhere writing
    'Phase N · YYYY-MM-DD' is not swept in as a currency stamp."""
    m = re.search(r'<footer class="colophon"', text)
    if not m:
        return text
    end = text.find("</footer>", m.end())
    return text[m.start() : end if end != -1 else len(text)]


def monograph_phase_sites(text: str) -> dict[str, set[int]]:
    """Every site in the monograph that stamps a phase number.

    Phase 177 added the two masthead sites, which had never been in this guard's
    population. **What that buys is narrower than Phase 177 first claimed, and the
    correction is kept here because the overclaim is more instructive than the fix.**
    The first version of this docstring said a partial bump "is what the tree looked
    like when Phase 177 opened". It was not: at that commit all four sites read 159
    together, and the round reproduced 6 passes against that exact file. The true
    opening state was *uniformly* stale, which this guard does not catch and is not
    meant to — Phase 118 settled that the monograph is a dated snapshot allowed to lag,
    and a never-behind ratchet was deliberately not built.

    So the property here is **partial-pass detection**: a currency pass that bumps some
    stamps and misses others now fails, where before Phase 177 it could miss both
    masthead sites silently. That is a real failure mode and a smaller one than claimed.
    """
    colophon = _colophon(text)
    return {
        # Masthead: <span class="line">Issue N</span>
        "masthead issue": {
            int(n) for n in re.findall(r'<span class="line">Issue (\d+)</span>', text)
        },
        # Hero stat band. Matched by position in the stat block, not by pinning the label
        # text — the round reddened the first version by rewording "Shipped phases", which
        # is ordinary copy work.
        "hero stat": {
            int(n)
            for n in re.findall(
                r'<div class="hero-stat-fig">(\d+)</div>\s*'
                r'<div class="hero-stat-label">[^<]*[Pp]hases[^<]*</div>',
                text,
            )
        },
        # Colophon prose 'as of <em>Phase N</em> · <date>' and the colophon source list
        # '<li>Phase N · <date></li>'. SCOPED to the colophon: the first version swept the
        # whole file, so any prose writing "Phase 172 · 2026-07-31" would have reddened it.
        "colophon stamp": {
            int(n) for n in re.findall(r"Phase (\d+)(?:</em>)? · " + _DATE, colophon)
        },
    }


def monograph_date_sites(text: str) -> dict[str, set[str]]:
    """Every dated site, normalized — the masthead writes 2026.08.02, the
    colophon writes 2026-08-02, and nothing previously made them agree."""
    return {
        # Both sites accept either notation and are compared normalized — the round
        # reddened the first version for normalizing the masthead to ISO, which is a
        # legitimate edit, not drift.
        "masthead date": {
            _iso(d) for d in re.findall(r'<span class="line">(' + _DATE + r')</span>', text)
        },
        "colophon date": {
            _iso(d) for d in re.findall(r"Phase \d+(?:</em>)? · (" + _DATE + r")",
                                       _colophon(text))
        },
    }


def test_monograph_is_self_consistent_and_never_ahead():
    text = _read("docs/workflow.html")
    sites = monograph_phase_sites(text)
    for name, found in sites.items():
        assert found, f"monograph {name} site not found — this guard's anchor needs revisiting"
    numbers = set().union(*sites.values())
    assert len(numbers) == 1, (
        f"monograph phase stamps disagree: "
        f"{ {k: sorted(v) for k, v in sites.items()} } — the masthead, the hero stat "
        "and both colophon stamps must be bumped together in a currency pass"
    )
    assert max(numbers) <= _max_phase(), (
        f"monograph claims Phase {max(numbers)}, ahead of PHASE_LOG.md ({_max_phase()})"
    )


def test_monograph_dates_agree_across_notations():
    text = _read("docs/workflow.html")
    dates = monograph_date_sites(text)
    for name, found in dates.items():
        assert found, f"monograph {name} site not found — this guard's anchor needs revisiting"
    values = set().union(*dates.values())
    assert len(values) == 1, (
        f"monograph dates disagree: { {k: sorted(v) for k, v in dates.items()} } — "
        "the masthead (YYYY.MM.DD) and the colophon (YYYY-MM-DD) date the same snapshot"
    )


def test_the_currency_guard_reaches_every_stamp_site():
    """Vacuity + population control. Each site is mutated ALONE: a guard that only
    reads three of four sites stays green when the fourth drifts, which is exactly
    the state this file shipped in before Phase 177."""
    text = _read("docs/workflow.html")
    n = max(set().union(*monograph_phase_sites(text).values()))
    drift = str(n + 1)
    mutations = {
        "masthead issue": (f'<span class="line">Issue {n}</span>',
                           f'<span class="line">Issue {drift}</span>'),
        "hero stat": (f'<div class="hero-stat-fig">{n}</div>',
                      f'<div class="hero-stat-fig">{drift}</div>'),
        "colophon prose": (f"as of <em>Phase {n}</em>", f"as of <em>Phase {drift}</em>"),
        "colophon list": (f"<li>Phase {n} · ", f"<li>Phase {drift} · "),
    }
    for site, (old, new) in mutations.items():
        assert text.count(old) == 1, f"{site}: anchor {old!r} matched {text.count(old)} times"
        mutated = text.replace(old, new, 1)
        found = set().union(*monograph_phase_sites(mutated).values())
        assert found == {n, int(drift)}, (
            f"drifting the {site} alone left the guard's population unchanged "
            f"({sorted(found)}) — that site is not actually being read"
        )


def test_the_date_guard_reaches_both_notations():
    text = _read("docs/workflow.html")
    d = next(iter(set().union(*monograph_date_sites(text).values())))
    for site, (old, new) in {
        "masthead": (f'<span class="line">{d.replace("-", ".")}</span>',
                     '<span class="line">1999.01.01</span>'),
        "colophon": (f"· {d}", "· 1999-01-01"),
    }.items():
        assert old in text, f"{site}: anchor {old!r} absent"
        values = set().union(*monograph_date_sites(text.replace(old, new, 1)).values())
        assert len(values) > 1, f"drifting the {site} date alone did not disagree — it is not read"


# --- negative controls, all three from Phase 177's round -------------------------


def test_rewording_the_hero_stat_label_stays_green():
    """Round finding N7. 'Shipped phases' -> 'Phases shipped' is copy work, not drift."""
    text = _read("docs/workflow.html")
    reworded = text.replace(
        '<div class="hero-stat-label">Shipped phases</div>',
        '<div class="hero-stat-label">Phases shipped</div>', 1)
    assert reworded != text, "anchor moved; this control needs re-pointing"
    sites = monograph_phase_sites(reworded)
    assert sites["hero stat"], "rewording the label made the hero stat unreadable"
    assert len(set().union(*sites.values())) == 1


def test_normalizing_the_masthead_date_to_iso_stays_green():
    """Round finding N6. Both notations are accepted and compared normalized."""
    text = _read("docs/workflow.html")
    m = re.search(r'<span class="line">(\d{4})\.(\d{2})\.(\d{2})</span>', text)
    assert m, "no dotted masthead date; this control needs re-pointing"
    iso = text.replace(m.group(0), f'<span class="line">{m.group(1)}-{m.group(2)}-{m.group(3)}</span>', 1)
    values = set().union(*monograph_date_sites(iso).values())
    assert len(values) == 1, f"normalizing the masthead date reddened the guard: {values}"


def test_a_dated_phase_reference_in_prose_is_not_a_stamp():
    """Round finding N5. The first version swept the whole file for 'Phase N · <date>', so
    ordinary prose citing a dated phase — or a previous-snapshot line — reddened it."""
    text = _read("docs/workflow.html")
    before = monograph_phase_sites(text)["colophon stamp"]
    with_prose = text.replace(
        "</body>", "<p>The mirror push of Phase 171 · 2026-07-31 shipped it.</p></body>", 1)
    assert with_prose != text, "no </body> anchor; this control needs re-pointing"
    assert monograph_phase_sites(with_prose)["colophon stamp"] == before, (
        "a dated phase reference in body prose was counted as a currency stamp"
    )
