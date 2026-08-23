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


def test_the_all_killed_headline_matches_the_derivation():
    """**The register's one load-bearing number.** Its prose says N batteries
    claimed all-killed and M were falsified; if the ledger no longer says that,
    the prose is stale and must move, not be re-argued."""
    m, text = _mod(), _register()
    a = m.all_killed_audit()
    quote = re.search(
        r"\*\*(\d+) author batteries reported every mutation killed\.\s*(\d+) were falsified"
        r".{0,80}?the other (\d+) had no independent battery",
        text, re.S,
    )
    assert quote, "the register's all-killed sentence no longer parses — keep it derivable"
    claims, falsified, unknown = (int(g) for g in quote.groups())
    assert (claims, falsified, unknown) == (a["claims"], a["falsified"], a["unknown"]), (
        f"register says {claims}/{falsified}/{unknown}; ledger derives "
        f"{a['claims']}/{a['falsified']}/{a['unknown']}"
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
