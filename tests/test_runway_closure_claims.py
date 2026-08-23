"""A runway bundle cannot claim its members are resolved while they are open (Phase 221).

**This exists because the register's promotion rule fired on its own first run.**
`tools/AUTHOR_DEFECT_REGISTER.md` lists *"population asserted rather than
derived"* with three recurrences (217, 219, 220) and no enforcement, and the rule
is that a recurrence means the prose failed — mechanize or retire, never restate.
The row had been labelled "promotion candidate at next recurrence", which is the
restating move the rule forbids.

The class in general ("derive the population, do not assert it") is not
mechanizable — it is a habit, not a predicate. **This is its highest-value
concrete slice**, and it is the exact instance Phase 220 got wrong: the runway's
R3 bullet said *"All seven resolved"* while `Q-017` was partially resolved, and
`PHASE_LOG.md` and the ledger row said the same. Nothing checked it; the round
did, by hand.

What is checkable: a bundle that declares itself closed names its members, and
every named member must be ticked in `REVIEW_CHECKLIST.md` or absent from it
(moved to `REVIEW_ARCHIVE.md`). An open member and a closed claim cannot both be
true.

**Scope, stated rather than implied.** This checks the *arithmetic* of a closure
claim, not its substance — it cannot tell you whether the work was any good, only
whether the roster the bundle names agrees with the queue. That is the half that
has actually gone wrong three times.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNWAY = REPO_ROOT / "tools/ANNOUNCE_RUNWAY.md"
CHECKLIST = REPO_ROOT / "REVIEW_CHECKLIST.md"

# A closure claim: a blockquote line inside a bundle bullet asserting the bundle
# is closed, e.g. "> **CLOSED — Phase 220 (2026-08-21). Six of seven resolved..."
# **Both** closure forms the runway uses. The first cut matched only `**CLOSED —
# Phase N**`, which is the shape of the ONE bullet it was written from: across 14
# bundles that form appears once, while `✓ DONE (Phase N)` — the dominant
# convention — appears four times and was invisible. A guard derived from a single
# example is a guard that matches its example.
_CLOSED = re.compile(r"(?:CLOSED\s*—\s*Phase\s*(\d+)|✓\s*DONE\s*\(Phase\s*(\d+))", re.I)
_QID = re.compile(r"`(Q-\d+)`")


def _open_ids() -> set[str]:
    """Ids still unticked in the active queue. Ticked or absent both count as
    resolved — a resolved entry moves to the archive in the same commit (the
    Phase 56 convention), so absence is the normal end state."""
    if not CHECKLIST.exists():
        pytest.skip("REVIEW_CHECKLIST.md is maintainer-side and mirror-excluded")
    text = CHECKLIST.read_text(encoding="utf-8")
    return set(re.findall(r"^- \[ \] <!-- id: (Q-\d+) -->", text, re.MULTILINE))


def _bundle_blocks() -> list[tuple[str, str]]:
    """(bundle label, its bullet text) for every top-level bundle bullet in
    § Tracks and bundles. A bullet runs to the next top-level `- **`."""
    if not RUNWAY.exists():
        pytest.skip("tools/ANNOUNCE_RUNWAY.md is maintainer-side and mirror-excluded")
    text = RUNWAY.read_text(encoding="utf-8")
    start = text.index("## Tracks and bundles") if "## Tracks and bundles" in text else 0
    body = text[start:]
    out = []
    # `A2-doc` and `A2-announce` are LIVE bundles this pattern could not match
    # until Phase 225: the label alternation stopped at an optional lowercase
    # letter, so a hyphenated suffix failed and the bullet was invisible. Two
    # consequences, both measured on the tree: Phase 224's own
    # `> **CLOSED — Phase 224**` claim was never checked by the guard written to
    # check closure claims; and because a block runs to the NEXT matched bullet,
    # `A1b`'s block silently swallowed the struck-through `A2` bullet and
    # scored its `Q-002`/`Q-003` as A1b members.
    for m in re.finditer(r"(?m)^- \*\*([A-Z]\d[a-z]?(?:-[a-z]+)?|[A-Z]\d)\s*—", body):
        nxt = re.search(r"(?m)^- \*\*", body[m.end():])
        block = body[m.start(): m.end() + (nxt.start() if nxt else len(body) - m.end())]
        out.append((m.group(1), block))
    return out


def _roster(block: str) -> set[str]:
    """The bundle's MEMBERS, derived from how a roster is actually written.

    Two things in a bundle bullet look alike and are not: the roster, written as a
    `+`-joined chain of backticked ids, and ordinary CITATIONS in the surrounding
    prose ("that is exactly the class `Q-273` covers"). Sweeping every id scores
    the citations as unresolved members — this checker's first two runs did
    exactly that, first on R3's three out-filings and then on a cross-reference.

    So membership keys on `+` adjacency, tolerating the `~~strikethrough~~` that
    marks a resolved member (L1/R1/R2 all write their rosters that way, and the
    first cut could not see through it).

    **The single-member case is real, and the first cut asserted it was not.** Its
    docstring said "a one-member bundle has no `+` and would extract empty. No such
    bundle exists today" — while `B0` sat in the same file, one member, extracting
    empty. That is *population asserted rather than derived*: the class this module
    was written to enforce, committed in the module's own documentation. When no
    `+`-chain is present, the first backticked id is taken as the member.
    """
    roster_region = re.split(r"(?m)^\s*>", block, maxsplit=1)[0]

    def _adjacent(s: str) -> str:
        return s.replace("~~", "").strip()

    members, first = set(), None
    for m in _QID.finditer(roster_region):
        if first is None:
            first = m.group(1)
        before = _adjacent(roster_region[max(0, m.start() - 6): m.start()])
        after = _adjacent(roster_region[m.end(): m.end() + 6])
        if before.endswith("+") or after.startswith("+"):
            members.add(m.group(1))
    if not members and first is not None:
        members.add(first)
    return members


def _violations(blocks, open_ids):
    """**The predicate, extracted so the fixture tests exercise it.**

    The first cut re-implemented this logic inline inside the two "would this
    catch the defect it was written for" tests. They therefore certified a copy,
    not the thing that runs: putting `return` at the top of the real test left
    both green. A test that proves a rule works by re-deriving the rule proves
    nothing about the rule.
    """
    problems = []
    for label, block in blocks:
        m = _CLOSED.search(block)
        if not m:
            continue
        head = block[m.start(): m.start() + 400]
        excepted = set(_QID.findall(head)) if re.search(r"partial", head, re.I) else set()
        still_open = sorted((_roster(block) & set(open_ids)) - excepted)
        if still_open:
            problems.append(f"bundle {label} claims {m.group(0)!r} but these members are "
                            f"still unticked in REVIEW_CHECKLIST.md: {still_open}")
    return problems


def test_the_extraction_finds_bundles_and_a_closure_claim():
    """Non-vacuity, and it is load-bearing: the first cut passed while covering
    ONE of fourteen bundles and deriving an EMPTY roster for six of them."""
    bundles = _bundle_blocks()
    assert len(bundles) >= 12, f"only {len(bundles)} bundles parsed from the runway"
    closed = [lbl for lbl, blk in bundles if _CLOSED.search(blk)]
    assert len(closed) >= 4, (
        f"only {len(closed)} bundles carry a closure claim this guard can read ({closed}). "
        f"The runway closes bundles two ways — `**CLOSED — Phase N**` and `✓ DONE (Phase N)` "
        f"— and matching only one covered a single bullet."
    )
    empty = [lbl for lbl, blk in bundles if not _roster(blk)]
    assert not empty, (
        f"these bundles derive NO members, so a closure claim on them checks nothing: {empty}"
    )


def test_both_closure_forms_are_actually_exercised():
    """Pins the widening. If the runway is ever rewritten to one form this can be
    relaxed deliberately — but it must not lapse silently back to covering one."""
    blob = "\n".join(blk for _, blk in _bundle_blocks())
    assert re.search(r"CLOSED\s*—\s*Phase", blob, re.I), "the `CLOSED —` form is gone"
    assert re.search(r"✓\s*DONE\s*\(Phase", blob, re.I), "the `✓ DONE` form is gone"


def test_a_closed_bundle_has_no_open_members():
    """**The rule.** A bundle that says it closed, whose named members include an
    id still unticked in the active queue, is asserting a population it did not
    derive.

    A partial resolution is legitimate — `Q-017` is partially resolved and open —
    but then the claim must say so. `Six of seven resolved (Q-017 partially)`
    passes; `All seven resolved` does not."""
    problems = _violations(_bundle_blocks(), _open_ids())
    assert not problems, (
        "a closure claim and an open member cannot both be true. Either finish "
        "the entry, or say which one is partial in the claim itself:\n  "
        + "\n  ".join(problems)
    )


def test_the_check_would_catch_the_defect_it_was_written_for():
    """Phase 220's actual mistake, replayed **through the real predicate**.

    The R3 bullet said "All seven resolved" while `Q-017` sat unticked. This calls
    `_violations` rather than re-deriving it, so gutting the predicate reddens this
    test too — which the first cut did not do."""
    block = (
        "- **R3 — the batch substrate.** `Q-017` + `Q-243` + `Q-019`.\n"
        "  > **CLOSED — Phase 220 (2026-08-21). All seven resolved.** One decision settled...\n"
    )
    problems = _violations([("R3", block)], {"Q-017"})
    assert problems, "an unqualified closure claim over an open member was not flagged"
    assert "Q-017" in problems[0]


def test_the_dominant_closure_form_is_caught_too():
    """The `✓ DONE (Phase N)` form — four of the runway's five closure claims, and
    entirely invisible to the first cut."""
    block = (
        "- **X1a — the cross-skill execution defects. ✓ DONE (Phase 222, 2026-08-30).** "
        "`Q-279` + `Q-013`. All eight resolved.\n"
    )
    assert _violations([("X1a", block)], {"Q-013"}), (
        "a `✓ DONE` closure claim over an open member was not flagged"
    )


def test_a_single_member_bundle_is_not_silently_empty():
    """`B0` is one member with no `+` chain. The first cut extracted nothing for it
    and its docstring asserted no such bundle existed."""
    block = "- **B0 — the pending-doc pipeline loses work. `Q-232` (upstream #428 + #433).**\n"
    assert _roster(block) == {"Q-232"}, f"single-member roster derived {_roster(block)}"


def test_a_partial_claim_that_names_its_exception_is_allowed():
    """The other direction — the check must not force a bundle to lie in order to
    close. This is the shape Phase 220 corrected to."""
    block = (
        "- **R3 — the batch substrate.** `Q-017` + `Q-243`.\n"
        "  > **CLOSED — Phase 220. Six of seven resolved; `Q-017` partially.** ...\n"
    )
    assert not _violations([("R3", block)], {"Q-017"}), (
        "a named partial exception was not honoured"
    )


def test_the_extraction_reaches_hyphenated_bundle_labels():
    """`A2-doc` is a live bundle carrying a closure claim; it must be checked.

    The first cut's label pattern accepted `A2` and `A2b` and stopped. Both
    halves of the A2 split are hyphenated, so the bundle that Phase 224 closed
    and the bundle holding the deferred announce work were BOTH outside the
    checker — which is to say the one closure claim in the file written in the
    grammar this module parses was the one it never read.
    """
    labels = {label for label, _ in _bundle_blocks()}
    assert {"A2-doc", "A2-announce"} <= labels, (
        f"hyphenated bundle labels are still invisible to the checker: {sorted(labels)}"
    )
    # And the widening must not have swallowed neighbours into one block.
    blocks = dict(_bundle_blocks())
    assert "A2-announce" not in blocks["A2-doc"], (
        "the A2-doc block runs past its own bullet into A2-announce; a roster "
        "read from it would score the next bundle's members as its own"
    )
