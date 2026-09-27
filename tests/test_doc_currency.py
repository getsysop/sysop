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
progress, so it stays — checked for internal self-consistency, for
never running ahead of PHASE_LOG.md (the canonical public history), and
for a date that does not predate the stamped phase's own heading.

NOT MECHANIZED: whether a currency pass actually ran. Every check here
reads the stamps and dates, none reads the page's content, so bumping the
stamps alone passes. That is a process fact, not a property of the file.
"""
from __future__ import annotations

import re
from pathlib import Path

from _prose_guard_helpers import _FENCE

REPO_ROOT = Path(__file__).resolve().parent.parent

# Matches a numeric phase-count claim: "117 phases", "117 documented phases",
# "117 shipped phases" — the shapes the stat appeared in before retirement.
PHASE_COUNT_CLAIM = re.compile(r"\b\d+\s+(?:documented\s+|shipped\s+)?phases\b", re.I)

_LOG_HEADING = re.compile(r"^## Phase (\d+)")
_LIST_ITEM = re.compile(r"^(\s*)(?:[-+*]|\d{1,9}[.)])\s+")


def _read(rel):
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _list_bound(lines, k, indent):
    """True when the fence opener at line K (indented INDENT) sits inside a list item: the
    nearest earlier non-blank line indented less than it is an item whose content column
    the opener reaches."""
    for line in reversed(lines[:k]):
        if not line.strip() or len(line) - len(line.lstrip()) >= indent:
            continue
        m = _LIST_ITEM.match(line)
        return bool(m) and len(m.group(0)) <= indent
    return False


def _unfenced_lines(lines):
    """The lines outside fenced code and HTML comments.

    Pairing is `_fence_state()`'s (same character, at least as long, nothing after the
    closer; no backtick in a backtick opener's info string), plus the one CommonMark rule it
    lacks: a fence opened inside a list item ends when the item does, at the first non-blank
    line indented less than the opener. Without it, `_fence_state()` pairs an unclosed
    list-item opener in PHASE_LOG.md with the next real opener and reads real phase headings
    as fenced (29 of them at Phase 330)."""
    fence = None  # (char, length, indent, list_bound)
    in_comment = False
    for k, line in enumerate(lines):
        if in_comment:
            in_comment = "-->" not in line
            continue
        m = _FENCE.match(line)
        if fence is not None:
            if fence[3] and line.strip() and len(line) - len(line.lstrip()) < fence[2]:
                fence = None  # the list item ended; this line is read afresh below
            else:
                if (m and m.group(2)[0] == fence[0] and len(m.group(2)) >= fence[1]
                        and not m.group(3).strip()):
                    fence = None
                continue
        if m and not (m.group(2)[0] == "`" and "`" in m.group(3)):
            indent = len(m.group(1))
            fence = (m.group(2)[0], len(m.group(2)), indent,
                     indent > 0 and _list_bound(lines, k, indent))
            continue
        if line.lstrip().startswith("<!--"):
            in_comment = "-->" not in line
            continue
        yield line


def _log_headings(log: str) -> list[str]:
    """PHASE_LOG.md's `## Phase N` heading lines, excluding any quoted inside a fence or
    an HTML comment."""
    return [ln for ln in _unfenced_lines(log.split("\n")) if _LOG_HEADING.match(ln)]


def _max_phase(log: str | None = None) -> int:
    log = _read("PHASE_LOG.md") if log is None else log
    nums = [int(_LOG_HEADING.match(h).group(1)) for h in _log_headings(log)]
    assert nums, "PHASE_LOG.md has no unfenced '## Phase N' headings"
    return max(nums)


def _executed_date(log: str, phase: int) -> str | None:
    """The earliest ISO date on phase PHASE's own heading line(s) — `(executed YYYY-MM-DD — …)`
    — or None when no heading for it carries one. A letter suffix (`159a`) is the same phase."""
    own = re.compile(rf"^## Phase {phase}[a-z]?(?=[\s(]|$)")
    dates = [m.group(0) for h in _log_headings(log) if own.match(h)
             for m in [re.search(r"\d{4}-\d{2}-\d{2}", h)] if m]
    return min(dates) if dates else None


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


def currency_problems(text: str, log: str) -> list[tuple[str, str]]:
    """(arm, message) for each way the phase stamps fail. Returned rather than asserted so
    the controls below can show each arm firing alone."""
    sites = monograph_phase_sites(text)
    missing = [("missing", f"monograph {name} site not found — this guard's anchor needs "
                "revisiting") for name, found in sites.items() if not found]
    if missing:
        return missing
    problems = []
    numbers = set().union(*sites.values())
    if len(numbers) != 1:
        problems.append(("disagree", (
            f"monograph phase stamps disagree: "
            f"{ {k: sorted(v) for k, v in sites.items()} } — the masthead, the hero stat "
            "and both colophon stamps must be bumped together in a currency pass")))
    ceiling = _max_phase(log)
    if max(numbers) > ceiling:
        problems.append(("ahead", f"monograph claims Phase {max(numbers)}, ahead of "
                                  f"PHASE_LOG.md ({ceiling})"))
    return problems


def date_problems(text: str, log: str) -> list[tuple[str, str]]:
    """(arm, message) for each way the dates fail: the notations disagree, or the date
    predates the stamped phase's own `## Phase N (executed YYYY-MM-DD` heading — the external
    anchor that catches both notations rolled back together."""
    dates = monograph_date_sites(text)
    missing = [("missing", f"monograph {name} site not found — this guard's anchor needs "
                "revisiting") for name, found in dates.items() if not found]
    if missing:
        return missing
    problems = []
    values = set().union(*dates.values())
    if len(values) != 1:
        problems.append(("disagree", (
            f"monograph dates disagree: { {k: sorted(v) for k, v in dates.items()} } — "
            "the masthead and the colophon date the same snapshot")))
    stamps = set().union(*monograph_phase_sites(text).values())
    if len(stamps) == 1:  # a disagreement is currency_problems' to report
        (phase,) = stamps
        executed = _executed_date(log, phase)
        if executed is None:
            problems.append(("undated", (
                f"PHASE_LOG.md has no dated heading for Phase {phase}, the stamped phase — "
                "give it `(executed YYYY-MM-DD — …)` so the monograph date has an anchor")))
        elif min(values) < executed:
            problems.append(("predates", (
                f"monograph is dated {min(values)}, before Phase {phase} was executed "
                f"({executed}) — the date was not bumped with the stamps")))
    return problems


def test_monograph_is_self_consistent_and_never_ahead():
    problems = currency_problems(_read("docs/workflow.html"), _read("PHASE_LOG.md"))
    assert not problems, [msg for _, msg in problems]


def test_monograph_dates_agree_across_notations():
    problems = date_problems(_read("docs/workflow.html"), _read("PHASE_LOG.md"))
    assert not problems, [msg for _, msg in problems]


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


# The four stamp sites and the two date sites, located by shape so the controls below
# rewrite whatever spelling the page uses rather than pinning one.
_STAMP_SITES = (
    r'(<span class="line">Issue )(\d+)(</span>)',
    r'(<div class="hero-stat-fig">)(\d+)(</div>\s*<div class="hero-stat-label">[^<]*[Pp]hases)',
    r"(as of <em>Phase )(\d+)(</em>)",
    r"(<li>Phase )(\d+)( · )",
)
_MASTHEAD_DATE = r'(<span class="line">)(' + _DATE + r")(</span>)"
_COLOPHON_DATE = r"(Phase \d+(?:</em>)? · )(" + _DATE + r")()"


def _restamp(text: str, phase: int) -> str:
    for pat in _STAMP_SITES:
        text, n = re.subn(pat, lambda m: f"{m.group(1)}{phase}{m.group(3)}", text, count=1)
        assert n == 1, f"stamp site {pat!r} not found; this control needs re-pointing"
    return text


def _redate(text: str, iso: str, *, masthead: bool = True, colophon: bool = True) -> str:
    """Every chosen date site set to ISO, each written back in the notation it already uses."""
    def put(m):
        sep = "." if "." in m.group(2) else "-"
        return m.group(1) + iso.replace("-", sep) + m.group(3)
    if masthead:
        text, n = re.subn(_MASTHEAD_DATE, put, text, count=1)
        assert n == 1, "no masthead date; this control needs re-pointing"
    if colophon:
        head, sep, tail = text.partition('<footer class="colophon"')
        assert sep, "no colophon; this control needs re-pointing"
        tail, n = re.subn(_COLOPHON_DATE, put, tail)
        assert n >= 1, "no colophon date; this control needs re-pointing"
        text = head + sep + tail
    return text


def _arms(problems):
    return sorted(arm for arm, _ in problems)


def test_each_stamp_arm_fires_alone():
    """Predicate control for currency_problems: each arm is tripped by a change to what it
    reads and nothing else, and the never-ahead boundary sits exactly at the log's ceiling."""
    text, log = _read("docs/workflow.html"), _read("PHASE_LOG.md")
    ceiling = _max_phase(log)
    assert _arms(currency_problems(_restamp(text, ceiling), log)) == []
    assert _arms(currency_problems(_restamp(text, ceiling + 1), log)) == ["ahead"]
    n = max(set().union(*monograph_phase_sites(text).values()))
    lagging = text.replace(f'<span class="line">Issue {n}</span>',
                           f'<span class="line">Issue {n - 1}</span>', 1)
    assert lagging != text, "masthead issue anchor moved; this control needs re-pointing"
    assert _arms(currency_problems(lagging, log)) == ["disagree"]
    hero = re.search(_STAMP_SITES[1], text)
    assert _arms(currency_problems(text.replace(hero.group(0), "", 1), log)) == ["missing"]


def test_each_date_arm_fires_alone():
    """Predicate control for date_problems. Rolling BOTH notations back together keeps them
    agreeing, so only the anchor to PHASE_LOG.md can see it; moving one notation forward
    past that anchor trips only the agreement arm."""
    text, log = _read("docs/workflow.html"), _read("PHASE_LOG.md")
    (phase,) = set().union(*monograph_phase_sites(text).values())
    executed = _executed_date(log, phase)
    assert executed, f"Phase {phase}'s heading carries no date; the anchor control is vacuous"
    a_year_before = f"{int(executed[:4]) - 1}{executed[4:]}"
    assert _arms(date_problems(_redate(text, executed), log)) == []
    assert _arms(date_problems(_redate(text, a_year_before), log)) == ["predates"]
    assert _arms(date_problems(_redate(text, "2999-12-31", colophon=False), log)) == ["disagree"]
    # One site rolled back alone trips both: the earliest date is what must not predate.
    assert _arms(date_problems(_redate(text, a_year_before, colophon=False), log)) == [
        "disagree", "predates"]
    undated = re.sub(rf"(?m)^(## Phase {phase}\b[^\n]*?)\d{{4}}-\d{{2}}-\d{{2}}",
                     r"\1", log)
    assert undated != log
    assert _arms(date_problems(text, undated)) == ["undated"]
    masthead = re.search(_MASTHEAD_DATE, text).group(0)
    assert _arms(date_problems(text.replace(masthead, "", 1), log)) == ["missing"]


def test_the_date_guard_reaches_both_notations():
    text = _read("docs/workflow.html")
    for site, kw in {"masthead": {"colophon": False}, "colophon": {"masthead": False}}.items():
        values = set().union(*monograph_date_sites(_redate(text, "1999-01-01", **kw)).values())
        assert len(values) > 1, f"drifting the {site} date alone did not disagree — it is not read"


# --- negative controls, all three from Phase 177's round -------------------------


def test_rewording_the_hero_stat_label_stays_green():
    """Round finding N7. Rewording the label is copy work, not drift.

    Re-pointed by Phase 320 (`Q-545`). The label was 'Shipped phases' beside a figure
    that is the phase NUMBER, not a count of phases — the sequence has holes, so the
    two differ. Relabelling to 'Phases shipped through' makes the figure honest and
    moved this control's anchor, which is exactly the outcome the assert below is for:
    the control is the reason a relabel could not be a drive-by, and re-pointing it is
    the price of the fix rather than a defect in it.
    """
    text = _read("docs/workflow.html")
    reworded = text.replace(
        '<div class="hero-stat-label">Phases shipped through</div>',
        '<div class="hero-stat-label">Phases through</div>', 1)
    assert reworded != text, "anchor moved; this control needs re-pointing"
    sites = monograph_phase_sites(reworded)
    assert sites["hero stat"], "rewording the label made the hero stat unreadable"
    assert len(set().union(*sites.values())) == 1


def test_a_hero_stat_that_only_mentions_a_phase_is_not_a_stamp():
    """The hero anchor is the plural `phases`: a neighbouring stat whose label merely says
    'phase' is a different figure and must not join the stamp population."""
    text = _read("docs/workflow.html")
    before = monograph_phase_sites(text)["hero stat"]
    planted = text.replace(
        '<div class="hero-stat-label">Skills</div>',
        '<div class="hero-stat-label">Skills per phase</div>', 1)
    assert planted != text, "no Skills stat; this control needs re-pointing"
    assert monograph_phase_sites(planted)["hero stat"] == before


def test_normalizing_the_masthead_date_to_iso_stays_green():
    """Round finding N6. Both notations are accepted and compared normalized — so switching
    the masthead's notation, in whichever direction the page now needs, stays green."""
    text = _read("docs/workflow.html")
    m = re.search(_MASTHEAD_DATE, text)
    assert m, "no masthead date; this control needs re-pointing"
    d = m.group(2)
    flipped = d.replace(".", "-") if "." in d else d.replace("-", ".")
    switched = text.replace(m.group(0), m.group(1) + flipped + m.group(3), 1)
    assert switched != text
    values = set().union(*monograph_date_sites(switched).values())
    assert len(values) == 1, f"switching the masthead date's notation reddened the guard: {values}"


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


# --- the ceiling's reader: PHASE_LOG.md quotes markdown, so it is read fence-aware ------


def test_the_log_ceiling_is_the_highest_heading():
    """Arithmetic control: the ceiling is the highest `## Phase N`, in any order, nothing added."""
    log = "# Log\n\n## Phase 7 (executed 2026-01-01)\n\n## Phase 12 — x\n\n## Phase 9\n"
    assert _max_phase(log) == 12


def test_the_executed_date_is_read_from_the_phase_s_own_heading():
    log = ("## Phase 5a (executed 2026-01-05 — x)\n\n## Phase 5b (executed 2026-01-07)\n\n"
           "## Phase 5.1 (executed 2026-01-01)\n\n## Phase 50 (executed 2025-12-01)\n\n"
           "## Phase 5's adversarial round\n\n```\n## Phase 5 (executed 2020-01-01)\n```\n\n"
           "## Phase 6 — undated\n")
    assert _executed_date(log, 5) == "2026-01-05"
    assert _executed_date(log, 6) is None


def test_the_log_ceiling_reaches_the_newest_indexed_phase():
    """The real log's ceiling is not LOWERED by its fence reading: it is at least the newest
    phase CLAUDE.md's Phase log indexes. (Skips on the public mirror, which lacks CLAUDE.md.)"""
    from test_phase_log_currency import _claude_md, newest_label, numeric_phase

    newest = numeric_phase(newest_label(_claude_md()))[0]
    assert _max_phase() >= newest, (
        f"PHASE_LOG.md's fence-aware ceiling is {_max_phase()}, below the newest indexed "
        f"phase {newest} — the fence reader is swallowing real headings"
    )


_QUOTED_FUTURE_HEADINGS = {
    "backtick fence": "```\n## Phase 999 (executed 2999-01-01)\n```\n",
    "tilde fence": "~~~markdown\n## Phase 999\n~~~\n",
    "fence with a multi-word info string": "``` quoted example\n## Phase 999\n```\n",
    "longer fence around a shorter marker": "````\n```\n## Phase 999\n```\n````\n",
    "marker line with an info string inside a fence": "```\n```text\n## Phase 999\n```\n",
    "fence indented one space, outside a list": "Prose.\n\n ```\n## Phase 999\n ```\n",
    "fence indented short of a list item's content": "* item\n ```\n## Phase 999\n ```\n",
    "HTML comment": "<!--\n## Phase 999\n-->\n",
    "a tilde line inside a backtick fence": "```\n~~~\n## Phase 999\n```\n",
}


def test_a_quoted_future_heading_does_not_raise_the_ceiling():
    log = _read("PHASE_LOG.md")
    ceiling = _max_phase(log)
    for shape, quoted in _QUOTED_FUTURE_HEADINGS.items():
        planted = log + "\n" + quoted
        assert _max_phase(planted) == ceiling, f"a {shape} raised the ceiling to 999"
    # Vacuity: the same heading unquoted DOES raise it, including after a closed fence or
    # comment, so the planting is being read and a quote does not run on past its end.
    assert _max_phase(log + "\n## Phase 999\n") == 999
    assert _max_phase(log + "\n```\nx\n```\n\n## Phase 999\n") == 999
    assert _max_phase(log + "\n<!--\nx\n-->\n\n## Phase 999\n") == 999
    assert _max_phase(log + "\n<!-- one line -->\n\n## Phase 999\n") == 999


def test_an_unclosed_list_item_opener_does_not_swallow_later_headings():
    """The trap in PHASE_LOG.md: a list item carrying a fence opener that never closes. The
    item, and so the fence, ends at the next line indented less than the opener."""
    log = _read("PHASE_LOG.md")
    ceiling = _max_phase(log)
    last = [h for h in _log_headings(log) if int(_LOG_HEADING.match(h).group(1)) == ceiling][-1]
    for opener in ("  ```python", "  ``` a wrapped sentence that begins with the marker"):
        for item in ("* an item\n", "* an item\n  continued\n\n"):
            planted = log.replace(last, f"{item}{opener}\n  body\n\n{last}", 1)
            assert planted != log
            assert _max_phase(planted) == ceiling, (
                f"{opener!r} after {item!r} swallowed Phase {ceiling}'s heading")


# --------------------------------------------------------------------------
# docs/history.md — the timeline, and the one number in it that rots.
#
# Phase 259 found this page stale in a way no citation grep sees: its terminal
# entry said "Aug 2026" in September. Nothing in `tests/` read this file at all.
#
# Its suite total is the subtler half, and the first version of this comment got
# it wrong in a way worth keeping: it called "past 4,900 tests" *several hundred
# short*, which is only true against the source suite (Phase 250's August cut
# measured 5,448) and not against the sterilized mirror the same cut measured at
# 4,983. Two populations, one sentence. The number is not false either way — it
# is a floor — so the ratchet below is not about accuracy at all. It is about the
# terminal bullet being a claim that goes stale on its own.
#
# The ratchet is Phase 118's, applied one file over. A total in a bullet that
# describes a CLOSED month is a historical fact and stays; a total in the
# TERMINAL bullet is a claim about now, and it is false the week after it is
# written. So the guard is scoped to the terminal entry rather than to the page
# — the narrower rule, and the one that does not force the history out of a
# history page.
#
# NOT MECHANIZED, and stated rather than left to be discovered: nothing here
# checks that the terminal entry names a RECENT month. Every shape of that test
# was either flaky (it fails on a quiet fortnight) or circular (it derives
# "current" from the file it is checking). The recency of this page is a
# currency-pass responsibility, and this comment is the handoff.
# --------------------------------------------------------------------------

HISTORY = "docs/history.md"

# The shapes a suite total takes. The first version required comma-grouping and
# `tests` immediately after whitespace, and its own comment claimed it handled
# `"900+ tests"` — which it did not match, and which is live on the page. A round
# also walked `6100 tests` and `4,900 automated tests` through it. Widened to
# four digits or comma-grouped, with a short qualifier allowed between.
SUITE_TOTAL_CLAIM = re.compile(
    r"\b\d[\d,]{2,}\+?(?:\s+[a-z-]+){0,2}\s+tests?\b", re.I)


def _history_bullets():
    """The timeline's top-level bullets, in order.

    The TAIL — everything after the last bullet — is appended to the final
    entry rather than dropped. A round pointed out that the page's closing
    prose is the natural home for a "current state" number and sat entirely
    outside the population, so a total moved three lines down was invisible.
    """
    out = []
    tail = []
    for line in _read(HISTORY).splitlines():
        if line.startswith("- **"):
            out.append(line)
            tail = []
        elif out and line.startswith("  "):
            out[-1] += " " + line.strip()
        elif out:
            tail.append(line.strip())
    assert out, f"{HISTORY} has no timeline bullets; this guard has gone vacuous"
    out[-1] += " " + " ".join(tail)
    return out


def test_the_history_timeline_is_still_parseable():
    """Vacuity control. A reformat that stops matching `- **` would empty the
    bullet list and make every assertion below pass over nothing — which is the
    decorative-guard shape this repo keeps finding in its own checks.
    """
    bullets = _history_bullets()
    assert len(bullets) >= 5, f"only {len(bullets)} timeline bullets found"
    # Exercised against a SYNTHETIC string, not against whatever the page happens
    # to say. Keying this on a live bullet made a copy edit to a closed month —
    # "4,900 tests" to "4,900 automated tests" — redden CI on a prose page, which
    # is the over-strict direction that gets a correct guard deleted rather than
    # fixed. A round measured that as one of three false kills.
    assert SUITE_TOTAL_CLAIM.search("the suite passed 5,973 tests"), (
        "the detector no longer matches an ordinary suite-total sentence, so the "
        "ratchet below would pass over one"
    )


def test_the_terminal_history_entry_carries_no_suite_total():
    """The number that is false the week after it is written.

    An earlier bullet may quote a total: "900+ tests by mid-July" describes a
    month that has ended and cannot become wrong. The LAST bullet is a claim
    about the present, and this page's version of it was stale by several
    hundred while the same month's cut record carried the measured figure.
    """
    last = _history_bullets()[-1]
    hit = SUITE_TOTAL_CLAIM.search(last)
    assert not hit, (
        f"the terminal entry of {HISTORY} states a suite total ({hit.group(0)!r}). "
        "That number is false the week after it is written and nothing re-derives "
        "it. Say what changed, not how many tests there are — or close the entry "
        "with a month and open a new one"
    )
