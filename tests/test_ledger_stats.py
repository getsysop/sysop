"""Every number the register cites is derived, not asserted (Phase 221).

`tools/AUTHOR_DEFECT_REGISTER.md` names *"population asserted rather than
derived"* as a recurring author-defect class — and its own first draft committed
it, in its own headline, in the commit that filed the class. Two statistics were
quoted from a one-off extraction that was never committed: a survivor trend
(`36 → 21 → 28`) and an all-killed falsification rate (`20 of 26`). Neither
reproduced. The trend's extraction silently read the DENOMINATOR out of every
"N of M surviving" cell, and `20 of 26` could not be reproduced by any detector,
by the author or by the reviewing lens.

**The lesson is not "check numbers more carefully".** That is the prose response
the register exists to forbid. The lesson is that a number quoted from an
uncommitted extraction cannot be checked by anyone, ever — so the extraction is
now `tools/ledger_stats.py`, and this module fails when the register's prose and
that module disagree.

`tools/` is mirror-excluded (`tools/make_public_mirror.sh`, pinned by
`tests/test_mirror_leak_gate.py`), so these skip rather than fail where the
module is absent — the same accommodation `tests/test_skill_audit_refs.py` makes.
"""
import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "ledger_stats.py"
REGISTER = REPO_ROOT / "tools" / "AUTHOR_DEFECT_REGISTER.md"


def _mod():
    if not SCRIPT.exists():
        pytest.skip("tools/ledger_stats.py is maintainer-side and mirror-excluded")
    spec = importlib.util.spec_from_file_location("ledger_stats", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _register() -> str:
    if not REGISTER.exists():
        pytest.skip("register is maintainer-side and mirror-excluded")
    return REGISTER.read_text(encoding="utf-8")


def test_the_ledger_parses_and_every_row_is_the_right_width():
    """A row of the wrong width means a column has shifted, and every positional
    read is silently wrong from there down."""
    m = _mod()
    assert not m.malformed_rows(), (
        f"ledger rows with the wrong cell count: {m.malformed_rows()}"
    )
    assert len(m.phase_rows()) >= 55, "the phase-row extraction has drifted"


LEDGER_MD = REPO_ROOT / "tools" / "ROUND_YIELD_LEDGER.md"


def _ledger_md() -> str:
    if not LEDGER_MD.exists():
        pytest.skip("ledger is maintainer-side and mirror-excluded")
    return LEDGER_MD.read_text(encoding="utf-8")


# Every site that states the all-killed headline, and the shape it states it in.
# `Q-303` (Phase 231) filed this as the guard-pins-one-site-while-the-claim-lives-
# at-three class: the register's line-14 sentence was pinned, the register's class
# table and the ledger's reading note were not, and both were five stale — on the
# one instrument whose stated purpose is that no number in it is asserted. Phase 239
# found them eight and eleven stale. Each entry names its file, a regex whose groups
# are (claims, falsified, unknown) in that order, and the key it is missing when a
# group is absent.
HEADLINE_SITES = [
    ("AUTHOR_DEFECT_REGISTER.md — the load-bearing sentence", _register,
     r"\*\*(\d+) author batteries reported every mutation killed\. (\d+) were falsified"
     r".{0,80}?the other (\d+) had no independent battery"),
    ("AUTHOR_DEFECT_REGISTER.md — the class table's Recurrence cell", _register,
     r"\b(\d+) of the (\d+) recorded claims \((\d+) unknown, 0 intact\)"),
    ("ROUND_YIELD_LEDGER.md — the reading note", _ledger_md,
     r"\*\*(\d+) author batteries reported every mutation killed, (\d+) "
     r"were falsified by an independent lens, (\d+) had no lens"),
]


def _flat(s: str) -> str:
    """Whitespace-insensitive haystack.

    The battery's N02 control — reflowing the ledger's reading note across a
    different line break — was a FALSE KILL against the first version of these
    patterns, which spelled the wrap with `\\s+` in some gaps and a literal space
    in others. A markdown reflow is an ordinary edit; a guard that reddens on it
    is the over-strictness direction rule 1 calls the one that hides. Flatten
    once here instead of threading `\\s+` through every pattern.
    """
    return re.sub(r"\s+", " ", s)


@pytest.mark.parametrize("label,reader,pattern",
                         HEADLINE_SITES, ids=[s[0] for s in HEADLINE_SITES])
def test_every_stated_all_killed_headline_matches_the_derivation(label, reader, pattern):
    """**The instruments' one load-bearing number, at every site that states it.**

    If the ledger no longer derives what a site says, the prose is stale and must
    move — not be re-argued. Parametrized rather than looped so a stale site names
    itself instead of hiding behind whichever one fails first.
    """
    a = _mod().all_killed_audit()
    quote = re.search(pattern, _flat(reader()))
    assert quote, (
        f"{label}: the headline no longer parses. Keep it derivable — an unparseable "
        "site is an unguarded one, which is exactly how Q-303's two sites drifted."
    )
    g = [int(x) for x in quote.groups()]
    # The class-table cell reads "<falsified> of the <claims> recorded claims";
    # the two prose sites read "<claims> ... <falsified> ...". Normalize on the key.
    claims, falsified, unknown = (g[1], g[0], g[2]) if "class table" in label else tuple(g)
    assert (claims, falsified, unknown) == (a["claims"], a["falsified"], a["unknown"]), (
        f"{label} says {claims}/{falsified}/{unknown}; ledger_stats.py derives "
        f"{a['claims']}/{a['falsified']}/{a['unknown']}"
    )


def test_no_unregistered_site_states_the_headline():
    """Population control — the half `Q-303` said was missing.

    Widening the guard to three sites fixes three sites; it does not stop a
    *fourth* being written next to them and drifting the same way. So count the
    headline's own vocabulary across both instruments and require the total to
    equal what HEADLINE_SITES covers. A new statement reddens here and has to be
    registered above, which is the only version of this guard that closes the
    class rather than its current instances.
    """
    both = _flat(_register() + "\n" + _ledger_md())
    prose = len(re.findall(r"author batteries reported every mutation killed", both))
    table = len(re.findall(r"of the \d+ recorded claims", both))
    assert (prose, table) == (2, 1), (
        f"the all-killed headline is stated at {prose} prose sites and {table} table "
        f"sites; HEADLINE_SITES covers 2 and 1. A new site must be added to that list "
        "or it will drift unguarded — that is Q-303 verbatim."
    )


def test_the_headline_names_its_population_as_phases_not_rounds():
    """The digits can be right while the population noun is wrong.

    The ledger's reading note said *"Across 60 rounds"* until Phase 239. Two things
    were wrong and only one was a number: `all_killed_audit` runs over
    `phase_rows()`, and the ledger also holds non-phase rounds (triage bundles,
    mirror pushes) which are real rounds and not phases. `phase_rows`'s own
    docstring exists to name that conflation, and Phase 229's round retired it as a
    HIGH — then it came straight back, because every guard here counted digits.

    Battery row B06 restored the retired phrasing *with correct digits* and survived
    everything above. This is the assertion that kills it.
    """
    m, flat = _mod(), _flat(_ledger_md())
    n = len(m.phase_rows())
    assert f"Across {n} numbered phases:" in flat, (
        f"the ledger's reading note does not state its population as "
        f"'Across {n} numbered phases'. Digits alone are not the claim: the audit's "
        "population is phase_rows(), and calling that a count of *rounds* is the "
        "conflation Phase 229's round retired and B06 reinstated."
    )
    assert "Across 60 rounds" not in flat, (
        "the retired 'Across N rounds' phrasing is back in the ledger note"
    )


def test_the_registers_population_line_is_derived():
    """`Q-297`'s actual remedy, which Phase 239 first skipped.

    The filing said the fix was to *"derive the sentence's two figures the way the
    guarded ones are derived, **or extend the guard to cover the population line
    so it cannot drift again**"* — and the phase fixed the digits, archived the
    item resolved, and left the sentence unguarded. Lens 3 then re-staled it to
    `Q-297`'s exact pre-fix text with the whole suite green.

    It was also still wrong in kind. `78` is the count of **numbered phases**; the
    ledger holds **92 rounds**, the rest being triage bundles and mirror pushes —
    real rounds, not phases. Calling 78 a count of *rounds* is the conflation this
    same phase retired one file over, at the ledger's reading note.
    """
    m = _mod()
    rounds, phases = len(m.rows()), len(m.phase_rows())
    flat = _flat(_register())
    assert f"records {rounds} rounds, {phases} of them numbered phases" in flat, (
        f"the register's population line does not state the derived figures "
        f"({rounds} rounds, {phases} numbered phases). This is the one sentence "
        "Q-297 was filed about, and it drifted before precisely because nothing "
        "read it."
    )
    assert f"{phases} numbered phase rounds" not in flat, (
        f"the register calls {phases} a count of *rounds*; it is the count of "
        "numbered phases, and the ledger holds more rounds than phases"
    )


def test_the_claim_that_none_survived_is_still_true():
    """The register states flatly that no author battery survived an independent
    one. That is the strongest sentence in the file and the first that would go
    stale — a single intact row falsifies it."""
    a = _mod().all_killed_audit()
    assert a["intact"] == 0, (
        f"these all-killed batteries were NOT falsified: {a['intact_phases']} — "
        f"the register's 'Not one survived' must be corrected, not left standing"
    )
    assert a["claims"] == a["falsified"] + a["unknown"] + a["intact"]


def test_the_audit_is_not_vacuous():
    """If either detector stops matching, the audit reports a comfortable zero
    and every assertion above passes over an empty set."""
    a = _mod().all_killed_audit()
    assert a["claims"] >= 20, f"only {a['claims']} all-killed claims detected — extraction broke"
    assert a["falsified"] >= 20, f"only {a['falsified']} falsified — the survivor detector broke"


@pytest.mark.parametrize(
    "pattern,cited",
    [
        (r"anchor", "177"),
        (r"red baseline|already red", "179"),
    ],
)
def test_class_first_seen_dates_are_the_dates_the_ledger_gives(pattern, cited):
    """The first draft dated three classes 30–40 phases late, each to where the
    author happened to notice it. These two are derivable, so they are pinned."""
    m = _mod()
    seen = m.class_first_seen(pattern)
    assert seen, f"pattern {pattern!r} matches no ledger row — the class table cannot be checked"
    assert seen[0] == cited, (
        f"register cites first-seen {cited} for {pattern!r}; ledger's earliest row is {seen[0]}"
    )
    assert cited in _register(), f"{cited} is no longer cited in the register"


def test_the_withdrawn_trend_has_not_come_back():
    """**The specific regression this phase is guarding.** The survivor trend was
    withdrawn because it is unnormalised and its extraction was wrong in one
    direction. The cheap failure is a future session reinstating it with the
    arithmetic patched up — which fixes the digits and keeps the confound."""
    text = _register()
    assert "36 (161" not in text and "36 → 21" not in text, (
        "the withdrawn survivor trend is back in the register. It was not withdrawn "
        "for being miscounted; it was withdrawn because survivor COUNT is "
        "unnormalised over an author-chosen battery size. Recomputing it does not "
        "fix that."
    )
    assert "withdrawn" in text.lower()


def test_the_register_says_its_dates_are_lower_bounds():
    """`First seen` reads as a discovery date and is not one — the ledger starts
    at 161 and holds only what a round wrote down. Left implicit, the table
    invites exactly the over-dating its first draft committed."""
    text = _register()
    assert "lower bound" in text.lower()
    assert "159a" in text, (
        "the case-sensitivity row's out-of-window citation is gone — that row is the "
        "worked example of a date the ledger alone cannot supply"
    )
