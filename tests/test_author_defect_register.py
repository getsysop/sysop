"""The promotion rule, enforced (Phase 221).

`tools/AUTHOR_DEFECT_REGISTER.md` exists because 60 rounds of `ROUND_YIELD_LEDGER.md`
show the review round working as a detector: of 42 author batteries that reported
every mutation killed, 40 were falsified by an independent lens, 2 had no lens to
check them, and none survived one.

What the ledger CANNOT show is whether the author is learning. An earlier draft of
the register claimed it could, on a survivor trend across three phase windows; its
own round withdrew that as unnormalised, and `tests/test_ledger_stats.py` now pins
every number the register cites to `tools/ledger_stats.py` so the next such claim
is checkable by someone other than its author.

The register's rule is:

    Prose is a one-shot. A class written down and then observed again is
    evidence the prose failed. On recurrence it gets MECHANIZED or DROPPED —
    it does not get written a second time.

**This module is what makes that a rule rather than advice.** A rule about
promoting prose to code, left in prose, would be the joke telling itself.

The failure mode it guards is specific and observed: in Phase 220 the citation
guard caught what it covered and could not see a bare `` `:881` `` citation. Both
instances were fixed by hand and **the guard was never widened** — not by 220, and
not by 221 either. A mechanism gap treated as an attention problem is how a class
survives its own fix.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTER = REPO_ROOT / "tools/AUTHOR_DEFECT_REGISTER.md"

# A row is `| class | first seen | recurrences | mechanized at | enforcement | status |`.
# `Mechanized at` was added by this phase's own round: without it the register
# structurally could not tell a pre-mechanization recurrence from a post-one, which
# is the single distinction its thesis depends on.
_ROW = re.compile(
    r"(?m)^\|(?!\s*(?:Class\b|-))([^|]+)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|\s*$")


# `tools/` is stripped by the public mirror (`tools/make_public_mirror.sh`), and
# `tests/` ships. A module that reads a mirror-excluded file without skipping
# reddens the required `pytest` check on a tree nobody can fix from the mirror —
# `tests/test_registry_drift.py` states the rule and eleven modules follow it.
# This one did not, and its own round caught it: because `_rows()` is called
# inside a `parametrize` decorator, the failure was a COLLECTION error, which
# aborts the whole run rather than failing one test.
def _register() -> str:
    if not REGISTER.exists():
        pytest.skip("tools/AUTHOR_DEFECT_REGISTER.md is maintainer-side and mirror-excluded")
    return REGISTER.read_text(encoding="utf-8")


def _classes_table(text: str) -> str:
    """Only the `## Classes` table. The file holds two other tables — the
    lesson-form evidence table and (eventually) `## Retired` — and sweeping the
    whole file would score their rows as classes."""
    start = text.index("## Classes")
    end = text.index("## Retired", start)
    return text[start:end]


def _rows():
    return [
        {
            "cls": m.group(1).strip(),
            "first": m.group(2).strip(),
            "recur": m.group(3).strip(),
            "mech_at": m.group(4).strip(),
            "enforce": m.group(5).strip(),
            "status": m.group(6).strip(),
        }
        for m in _ROW.finditer(_classes_table(REGISTER.read_text(encoding="utf-8")))
    ] if REGISTER.exists() else []   # must never raise: evaluated at COLLECTION


def _rows_or_skip():
    """`_rows()` returns `[]` on a mirror tree so the `parametrize` decorator
    cannot raise at collection. Every test BODY must skip instead, or an empty
    register reads as a clean one — the vacuity failure this module exists to
    prevent, arriving through its own mirror guard."""
    if not REGISTER.exists():
        pytest.skip("tools/AUTHOR_DEFECT_REGISTER.md is maintainer-side and mirror-excluded")
    return _rows()


def _recurrence_count(cell: str) -> int:
    """Phases cited in the recurrences cell. `—` is zero.

    Counts CITATIONS, not instances: `220 (×2 in-phase)` is one recurrence,
    because the register measures whether a lesson survives a phase boundary.
    That is the register's stated counting rule, restated here so the two cannot
    drift apart silently."""
    if not cell or cell.strip() in {"—", "-", ""}:
        return 0
    if "of the" in cell:            # the prose form used by the all-killed row
        m = re.search(r"(\d+)\s+of the", cell)
        return int(m.group(1)) if m else 0
    return len(re.findall(r"\b\d{3}\b", cell))


def test_the_register_parses_and_is_not_empty():
    rows = _rows_or_skip()
    assert len(rows) >= 8, f"only {len(rows)} class rows parsed — the table shape has drifted"
    for r in rows:
        assert r["cls"], r
        assert r["status"], r


def test_a_prose_only_class_that_has_recurred_twice_must_be_mechanized():
    """**The promotion rule.** Two recurrences is the trigger: one is bad luck,
    two is evidence the prose is not doing the work.

    The fix is NOT to write the lesson again. Either an enforcement path appears
    in the `Enforcement` column, or the row moves to `## Retired` with a reason
    for dropping it. A row may also carry an explicit stated exception — see
    `test_a_stated_exception_must_say_why` — for classes whose mechanization is
    the round itself."""
    offenders = []
    for r in _rows_or_skip():
        if "prose-only" not in r["status"].lower():
            continue
        if "see note" in r["status"].lower():        # explicit, justified exception
            continue
        n = _recurrence_count(r["recur"])
        if n >= 2:
            offenders.append(f"{r['cls']!r}: {n} recurrences ({r['recur']}) and still prose-only")
    assert not offenders, (
        "these classes have recurred twice or more and are still prose-only. The "
        "register's rule is that a recurrence means the prose failed — mechanize "
        "them or retire them with a reason. Writing the lesson again is the one "
        "response the data says does not work:\n  " + "\n  ".join(offenders)
    )


def test_a_stated_exception_must_say_why():
    """An exception is legitimate — the all-killed class is one, because
    mechanizing it means running an independent battery, which IS the round. But
    it must carry its reasoning, or `see note` becomes a way to silence the rule
    rather than an argument against it."""
    text = _register()
    for r in _rows_or_skip():
        if "see note" not in r["status"].lower():
            continue
        m = re.search(r"see note\s*(\d+)", r["status"], re.I)
        assert m, f"{r['cls']!r} claims an exception without naming a note"
        # Both heading forms the file actually uses: `**Note 1.**` and
        # `**Note 3 — <title>**`. Pinning only the first made a legitimate
        # titled note look absent.
        pat = re.compile(rf"\*\*Note {m.group(1)}\s*(?:\.|—|-)")
        assert pat.search(text), (
            f"{r['cls']!r} cites note {m.group(1)} but the register has no such note"
        )


def test_a_mechanized_class_names_a_path_that_exists():
    """A guard that names a file which is not there is the shape this whole
    register is about. Checks the paths, not the prose around them."""
    missing = []
    for r in _rows_or_skip():
        for path in re.findall(r"`(tests/[\w/]+\.py|core/[\w/.\-]+\.md|tools/[\w/]+\.py)", r["enforce"]):
            if not (REPO_ROOT / path).exists():
                missing.append(f"{r['cls']!r} names {path}, which does not exist")
    assert not missing, "\n  ".join(missing)


def test_the_rule_is_stated_in_the_register_itself():
    """The register is read by a human deciding what to do with a finding; the
    rule has to be in the file, not only in this test."""
    text = _register()
    assert "mechanized or dropped" in text.lower()
    assert "one-shot" in text.lower()


def test_the_register_records_what_it_cannot_tell_you():
    """The confound is real: classes get a test when a test is CHEAP, so
    mechanized-vs-prose is not a randomized comparison. A register that
    presented its counts as causal would be overclaiming in exactly the way its
    own rows describe."""
    text = _register()
    assert "What this register cannot tell you" in text
    assert "not random" in text or "confound" in text.lower()


def test_the_promotion_target_is_not_claude_md():
    """Promoting to `CLAUDE.md` is the move this register replaces — it is
    always-loaded and Phase 116 shrank it for exactly this reason. Stated in the
    file so a future session does not reach for it by reflex."""
    text = _register()
    assert "CLAUDE.md" in text
    assert "always-loaded" in text or "always loaded" in text


@pytest.mark.parametrize("row", _rows(), ids=lambda r: r["cls"][:40])
def test_every_class_is_either_mechanized_partial_prose_only_or_retired(row):
    # `regressed` is the fifth disposition, added when the round found a class
    # that was mechanized at 187 and abandoned by 217. Omitting it here would
    # make the promotion check silently skip the register's most important row.
    ok = ("mechanized", "prose-only", "partial", "retired", "regressed")
    assert any(k in row["status"].lower() for k in ok), (
        f"{row['cls']!r} has status {row['status']!r}, which is none of {ok} — "
        f"an unclassifiable status makes the promotion check silently skip it"
    )


def _phases(cell: str) -> list[int]:
    return [int(x) for x in re.findall(r"\b(\d{3})\b", cell or "")]


def test_a_mechanized_class_that_keeps_recurring_is_not_silently_ok():
    """**The arm the first cut did not have, and could never have had.**

    The promotion check fires only on rows whose status contains `prose-only`.
    So a class that WAS mechanized and kept recurring anyway tripped nothing —
    the instrument was built so it could not detect "mechanization didn't work",
    which is the one outcome that would falsify the register's own thesis.

    Found by this phase's round, against a real row: the anchor rule shipped in
    `tools/mutation_battery.py` at Phase 187 with tests behind it, and phases
    217-220 hand-rolled it in throwaway scripts instead of importing it. That is
    a mechanized lesson being abandoned, and the register's first cut recorded it
    as evidence that mechanized lessons transfer.

    A recurrence AFTER the mechanizing phase is not automatically a failure — a
    guard can have a real coverage gap, which the citation and Python-floor rows
    both document. What it must not be is INVISIBLE. The row has to say so, in
    its status."""
    offenders = []
    for r in _rows_or_skip():
        mech = _phases(r["mech_at"])
        if not mech:
            continue
        after = [p for p in _phases(r["recur"]) if p > min(mech)]
        if not after:
            continue
        acknowledged = any(
            k in r["status"].lower()
            for k in ("regressed", "partial", "gap", "does not reach", "only")
        )
        if not acknowledged:
            offenders.append(
                f"{r['cls']!r} was mechanized at {min(mech)} and recurred at {after}, "
                f"but its status {r['status']!r} does not say the guard fell short"
            )
    assert not offenders, (
        "a class that keeps recurring after it was mechanized is the one outcome "
        "that would falsify this register's thesis — it must never be invisible "
        "to the instrument:\n  " + "\n  ".join(offenders)
    )


def test_the_recurring_after_mechanization_check_is_not_vacuous():
    """It must actually have rows to score. If `Mechanized at` is ever emptied or
    renamed, the check above passes over nothing and this register goes back to
    being unable to see its own counterexample."""
    with_mech = [r for r in _rows_or_skip() if _phases(r["mech_at"])]
    assert len(with_mech) >= 4, (
        f"only {len(with_mech)} rows carry a Mechanized-at phase — the column has "
        f"drifted and the post-mechanization check is scoring nothing"
    )
    recurred_after = [
        r for r in with_mech
        if any(p > min(_phases(r["mech_at"])) for p in _phases(r["recur"]))
    ]
    assert recurred_after, (
        "no row records a recurrence after its mechanizing phase — either the "
        "register has been cleaned of its own counterexamples, or the extraction "
        "is broken. Both make this check decorative."
    )
