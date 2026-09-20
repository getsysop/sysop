"""The mirror-currency block is a DATED record, never a present-tense claim.

Phase 118's demotion pattern, applied one file over: retire the rule, keep a regression
guard. `tests/test_doc_currency.py` does the same for a phase count on the landing page
and for a suite total in `docs/history.md`'s terminal bullet.

WHAT WENT WRONG. `REVIEW_CHECKLIST.md` § *Before announce* carried a stack of eleven
per-cut blocks. Its live member read *"Mirror currency: CURRENT through Phase 274"* — a
present-tense assertion that nothing re-derives. Four cuts shipped after it (283, 289,
296, 302), none of their records mentioned the block, and `grep -rn 'CURRENT through'
tests/` returned nothing: no gate read the string. Phase 310 collapsed the stack to one
dated line and archived the rest.

WHAT THIS BUYS, STATED NARROWLY. The rotting sentence cannot come back. It does **not**
check that the mirrors are current, and nothing here should be read as claiming it does.
Two designs that would have claimed it were refuted BEFORE being built:

  * Deriving "the newest cut" from `PHASE_LOG.md` prose. The obvious marker, `sysop-tester`,
    appears in **24** phase entries — most of them not cuts — and is **absent** from
    Phase 296, which is one. Wrong in both directions.
  * A recency gate. `tests/test_doc_currency.py:264` already declined that class for
    `docs/history.md`, in a comment that is the handoff: every shape of it was either
    flaky (it fails on a quiet fortnight) or circular (it derives "current" from the file
    it is checking). The objection holds here verbatim.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKLIST = "REVIEW_CHECKLIST.md"


@pytest.fixture(autouse=True)
def _source_repo_only():
    """`REVIEW_CHECKLIST.md` is stripped from the public mirror, and every gate in
    this module reads it. Without this skip the module raises `FileNotFoundError`
    on the sterilized tree, and the public snapshot PR's required `pytest` check
    goes red at the one irreversible step of a cut.

    **Measured, not anticipated.** Phase 320's pre-cut dry run of runbook step 4
    produced `3 failed, 6711 passed, 707 skipped` inside the built tree, all three
    from this module, all `FileNotFoundError: … /REVIEW_CHECKLIST.md`. This module
    shipped in Phase 310's own record-tail commit and no cut ran between then and
    Phase 320, which is why it reached a cut unexercised — the same gap Phase 310
    hit with `test_prose_guard_section.py`.

    Autouse and module-wide, matching the idiom in
    `tests/test_phase_log_citation_targets.py`: a test added here later inherits the
    skip rather than having to remember it. The same limit applies and is stated
    rather than implied — **a fixture runs at setup, not at collection**, so a future
    test whose `parametrize` decorator reads the checklist would error the whole
    module before this runs. Nothing here does that today.

    `pytest.mark.skipif` is the tidier spelling and is refused for the same reason
    the sibling module refuses it: `tests/test_mirror_skip_discipline.py` asserts on
    the literal `pytest.skip`. That is a fact about the guard's substring test
    (`Q-357`), not a virtue of fixtures.
    """
    if not (REPO_ROOT / CHECKLIST).is_file():
        pytest.skip(
            f"{CHECKLIST} is absent, so this is the sterilized public mirror rather "
            "than the source repo. This module's subject — the dated mirror-currency "
            "line in § Before announce — does not ship, so the ratchet applies only "
            "in the source repo"
        )

# The shape that rots: a currency claim in the PRESENT TENSE. Matched case-insensitively
# and across a line break, because the original wrapped mid-phrase ("Mirror\ncurrency:").
ROTTING_CLAIM = re.compile(r"CURRENT\s+through\s+Phase\s+\d+", re.I)


def _section() -> str:
    """§ *Before announce* only. Scoped rather than whole-file: the archive pointer and
    any later prose quoting the retired shape are not the thing being ratcheted, and a
    whole-file check would forbid this module's own subject being named there."""
    text = (REPO_ROOT / CHECKLIST).read_text(encoding="utf-8")
    start = text.index("\n## Before announce")
    nxt = text.index("\n## ", start + 1)
    return text[start:nxt]


def test_the_section_is_still_where_this_guard_looks():
    """Vacuity control. A rename or a reflow that moved the heading would make every
    assertion below pass over an empty string — the decorative-guard shape this repo
    keeps finding in its own checks."""
    body = _section()
    assert len(body) > 500, f"§ Before announce is {len(body)} chars; the anchor has moved"
    assert "most recent cut" in body, (
        "§ Before announce no longer names a most-recent cut, so this guard's subject "
        "is gone. Re-point it rather than deleting it."
    )


def test_the_detector_would_actually_fire():
    """Non-vacuity of the PATTERN, against a synthetic string rather than the live file.
    Keyed on the live text, a copy edit could silently empty this. The literal below is
    the sentence that stood in this section for four cuts."""
    assert ROTTING_CLAIM.search(
        "Mirror currency: CURRENT through Phase 274 — both mirrors carry the record tail"
    ), "the detector no longer matches the very sentence it was written to refuse"
    # And across the wrap the original actually had.
    assert ROTTING_CLAIM.search("**Mirror\ncurrency: CURRENT through Phase 274 —**")


def test_before_announce_states_no_present_tense_currency_claim():
    hits = ROTTING_CLAIM.findall(_section())
    assert not hits, (
        f"§ {CHECKLIST} *Before announce* has re-grown a present-tense currency claim "
        f"{hits}. That sentence is false the week after it is written and nothing "
        f"re-derives it — it went stale for four cuts (283, 289, 296, 302) before "
        f"Phase 310 retired it. Say which cut happened and when, and point at that "
        f"phase's record for the evidence."
    )


def test_the_dated_record_names_a_cut_and_a_date():
    """The other half: retiring the rotting claim must not leave the section saying
    nothing. A reader needs the last cut and when it was, which is a fact that cannot
    go stale because it is in the past tense."""
    body = _section()
    assert re.search(r"most recent cut was Phase \d+, \d{4}-\d{2}-\d{2}", body), (
        "§ Before announce no longer states which cut was most recent and when. The "
        "point of retiring the present-tense claim was to keep the fact and drop the "
        "tense, not to drop both."
    )
