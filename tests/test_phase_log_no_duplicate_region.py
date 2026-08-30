"""`PHASE_LOG.md` may not carry the same text twice — Phase 245, closing `Q-322`.

WHAT HAPPENED, BECAUSE THE SHAPE OF IT DICTATES THE SHAPE OF THIS GUARD.

An ordinary phase commit pasted a 15,599-line region of the phase log back into
the file. Nothing noticed for five phases. The file ships as the public
provenance record, so every reader saw sixty-three phases twice, and a decision
about the file's growth was being taken against a denominator inflated by 32%.

It was filed, then amended, then amended again, then RETRACTED IN FULL, then
amended once more — five passes, each of which derived the boundaries with a
`grep` over `## Phase ` headings, and every one of them got the boundaries
wrong in the same direction. The remedy the entry still carried when this phase
opened would have:

* left 145 lines of the duplicate in place, because the paste began mid-way
  through an earlier entry, at no heading at all — the first duplicated
  `## Phase ` heading is 151 lines into the run; and
* deleted 53 lines of unique content past the last duplicated heading — a
  phase's only suite figure, its declared-survivor rationale, and the file's
  only reference to two filed defects.

So this module asserts two things, and the second is the load-bearing one:

1. **No `## Phase ` heading line appears twice.** Cheap, legible, and what a
   reader would check by hand. It would have caught THIS paste (the region held
   66 duplicated headings) but not its boundaries, and not a paste containing no
   heading at all.
2. **No contiguous run of >= 30 lines appears twice.** This is the instrument
   that produced the true boundaries. It costs 0.02s on the real file.

Both are asserted because neither implies the other, and the five failed
derivations are the argument for keeping the expensive one.
"""

from __future__ import annotations

import pytest

from tests.dup_scan import (
    HEADING_PREFIX,
    MIN_RUN,
    duplicate_heading_lines,
    maximal_duplicate_runs,
    phase_log_lines,
)


# --------------------------------------------------------------------------
# The gates
# --------------------------------------------------------------------------


def test_no_phase_heading_line_appears_twice():
    lines = phase_log_lines()
    dupes = duplicate_heading_lines(lines)
    assert not dupes, (
        f"{len(dupes)} phase heading line(s) appear more than once in PHASE_LOG.md. "
        "A phase entry is written once. Sample: "
        + "; ".join(f"{at} -> {line[:70]!r}" for line, at in list(dupes.items())[:3])
    )


def test_no_contiguous_region_is_duplicated():
    lines = phase_log_lines()
    runs = maximal_duplicate_runs(lines)
    assert not runs, (
        f"PHASE_LOG.md contains {len(runs)} duplicated region(s) of >= {MIN_RUN} lines. "
        "Longest: "
        + "; ".join(
            f"lines {a0}-{a1} repeat at {b0}-{b1} ({a1 - a0 + 1} lines)"
            for a0, a1, b0, b1 in runs[:3]
        )
    )


def test_the_scan_is_not_vacuous():
    """A gate that passes because it read nothing is not a gate.

    `Q-322`'s own history includes a check that reported clean because its
    regex matched a vocabulary the file does not use.
    """
    lines = phase_log_lines()
    # Use the CONSTANT, not a copy of its value. The round's guards lens showed
    # this test passing with `HEADING_PREFIX` mutated to "#### Phase " while its
    # own failure message says "check the prefix" — it could not see the thing
    # it names.
    headings = [line for line in lines if line.startswith(HEADING_PREFIX)]
    assert len(lines) > 10_000, f"phase log unexpectedly short: {len(lines)} lines"
    assert len(headings) > 200, (
        f"only {len(headings)} headings match {HEADING_PREFIX!r} — check the prefix"
    )


# --------------------------------------------------------------------------
# Non-vacuity: each gate must fire on a planted defect
# --------------------------------------------------------------------------


def _block(tag: str, count: int) -> list[str]:
    return [f"{tag} line {i}" for i in range(count)]


def test_the_heading_check_fires_on_a_planted_duplicate():
    doc = ["## Phase 1 (x)", "body"] + _block("a", 5) + ["## Phase 1 (x)", "body"]
    assert duplicate_heading_lines(doc)


def test_the_region_check_fires_on_a_planted_paste():
    region = _block("r", 35)  # literal, not MIN_RUN: see the battery note
    doc = _block("head", 3) + region + _block("mid", 4) + region + _block("tail", 3)
    runs = maximal_duplicate_runs(doc)
    assert len(runs) == 1
    a0, a1, b0, _ = runs[0]
    assert a1 - a0 + 1 == len(region)
    assert a0 == 4 and b0 == 4 + len(region) + 4


def test_the_region_check_sees_a_paste_containing_no_heading():
    """The case the heading gate is structurally blind to.

    A pasted region need not contain a `## Phase ` line. The heading check
    reports clean; the region check must not.
    """
    region = _block("noheading", 32)  # literal on purpose
    doc = ["## Phase 9 (only one)"] + region + _block("mid", 3) + region
    assert not duplicate_heading_lines(doc), "fixture must not duplicate a heading"
    assert maximal_duplicate_runs(doc), "region check missed a heading-free paste"


def test_the_region_check_reports_the_true_start_not_the_first_duplicated_heading():
    """The exact defect that made five derivations of `Q-322` wrong.

    The paste begins inside the PREVIOUS entry, so the first duplicated heading
    sits well after the true start. Anchoring on that heading — which is what
    every `grep`-based derivation did — puts the boundary too late and leaves
    the head of the duplicate behind.
    """
    lead_in = _block("prev-entry-tail", 12)  # inside the previous entry
    region = lead_in + ["## Phase 42 (dup)"] + _block("body", 30)  # literal on purpose
    doc = _block("front", 6) + region + _block("unique-middle", 5) + region

    runs = maximal_duplicate_runs(doc)
    assert len(runs) == 1
    a0, a1, _, _ = runs[0]

    true_start = 6 + 1
    first_dup_heading = min(duplicate_heading_lines(doc)["## Phase 42 (dup)"])

    assert a0 == true_start, f"true start {true_start}, detector said {a0}"
    assert first_dup_heading == true_start + len(lead_in)
    assert a0 < first_dup_heading, (
        "the regression this pins: the run starts before its first duplicated "
        "heading, so a heading-anchored cut leaves "
        f"{first_dup_heading - a0} lines of the duplicate behind"
    )
    assert a1 - a0 + 1 == len(region)


# --------------------------------------------------------------------------
# Over-strictness: the region check must not cry paste at ordinary prose
# --------------------------------------------------------------------------


@pytest.mark.parametrize("repeat_len", [1, 5, MIN_RUN - 1])
def test_a_short_repeated_passage_is_not_reported(repeat_len):
    passage = _block("quoted", repeat_len)
    doc = _block("a", 40) + passage + _block("b", 40) + passage + _block("c", 40)
    assert not maximal_duplicate_runs(doc)


def test_separators_between_unique_prose_are_not_reported():
    """The realistic shape: `---` and blank lines recur, the prose between them does not.

    Note what is NOT claimed here. A perfectly periodic document — say
    ``["", "---", ""] * 200`` — really does contain two identical disjoint
    halves, and this detector reports it. That is the correct answer to the
    question asked, not a false positive; it simply is not a shape a
    hand-written phase log takes. The property that matters is this one.
    """
    doc = []
    for i in range(200):
        doc += ["", "---", "", f"unique paragraph {i}"]
    assert not maximal_duplicate_runs(doc)


def test_no_reported_run_overlaps_its_own_pair():
    """The invariant the overlap filter exists to enforce.

    Added because the battery's `RG06` row — deleting that filter — SURVIVED the
    first run. Every fixture in this module used disjoint copies, so nothing
    exercised the filter at all. A periodic passage is the shape that does: the
    window at offset 0 and the window at offset 1 are identical and overlap.
    """
    doc = ["same"] * 100
    runs = maximal_duplicate_runs(doc)
    assert runs, "fixture should still yield the disjoint halves"
    for a0, a1, b0, _ in runs:
        assert b0 > a1, f"run ({a0},{a1}) overlaps its pair starting at {b0}"


def test_two_distinct_pastes_are_both_reported():
    """The `covered` skip must not eat every run after the first.

    Added because the battery's `RG07` row — widening that skip to swallow all
    pairs — SURVIVED. Every fixture had exactly ONE duplicated region, so a
    mutation that discards all runs past the first was indistinguishable from
    correct behaviour.
    """
    first = _block("first", 35)
    second = _block("second", 40)
    doc = (
        first + _block("x", 6) + first + _block("y", 6)
        + second + _block("z", 6) + second
    )
    runs = maximal_duplicate_runs(doc)
    assert len(runs) == 2, f"expected both pastes, got {runs}"
    assert {a1 - a0 + 1 for a0, a1, _, _ in runs} == {35, 40}


def test_a_region_pasted_three_times_still_reports_the_adjacent_pair():
    """Forward growth must stop before the second copy, not run through it.

    Added because the battery's `RG09` row — deleting that stop condition —
    SURVIVED two runs. It is not inert: on a triple paste, growth from copy 1
    runs through copy 2 into copy 3, and the overlap filter then discards the
    whole pair, so the copy-1/copy-2 relationship disappears from the report. A
    cut driven by that report would not know where the middle copy was.
    """
    block = _block("t", 35)
    doc = block * 3
    runs = maximal_duplicate_runs(doc)
    assert (1, 35, 36, 70) in runs, (
        "the first two copies must be reported as a pair; got "
        f"{sorted(runs)[:4]}"
    )


def test_the_real_file_has_no_near_miss_hiding_under_the_threshold():
    """If a run of 20-29 lines existed, the threshold would be load-bearing.

    Recording that it is not: the real file's longest repeat is far below the
    threshold, so `MIN_RUN` is not the thing keeping this suite green.
    """
    lines = phase_log_lines()
    assert not maximal_duplicate_runs(lines, min_run=20)


# --------------------------------------------------------------------------
# Findings from the adversarial round's guards lens (23 mutations, 15 survived
# against the author battery's 16/16). Each test below closes a named survivor.
# --------------------------------------------------------------------------


def test_the_detector_finds_a_duplicate_planted_into_the_REAL_file():
    """The flagship hole: size-conditional inertness.

    Both gates above assert EMPTINESS, and every fixture in this module is under
    200 lines. So a detector that goes inert only on large inputs — `if n > 2000:
    return []` — passes every one of them AND both real-file gates, forever. The
    author's claim that "the fixtures distinguish an inert detector" held only
    for *unconditional* inertness.

    This plants a duplicate into the real file's lines IN MEMORY (the record is
    never written to) and requires the detector to find it at full scale.
    """
    lines = phase_log_lines()
    assert len(lines) > 5_000, "fixture assumes a large real file"
    victim = lines[1_000:1_060]
    planted = lines + victim
    runs = maximal_duplicate_runs(planted)
    assert runs, (
        "the detector found nothing after a 60-line block from the real file was "
        "appended to it — it is inert at real-file scale even though every small "
        "fixture passes"
    )
    assert any(a1 - a0 + 1 >= 60 for a0, a1, _, _ in runs)


def test_the_threshold_is_pinned_exactly_at_its_documented_value():
    """`MIN_RUN` could drift anywhere in [5, 32] with the suite green.

    The real-file gate is green for min_run in [5, 59] (nothing repeats), and the
    fixtures pinned only an upper bound. A 30- or 31-line paste would have been
    missed by a silently-widened threshold. These two fixtures pin it from both
    sides: exactly MIN_RUN lines must be found, exactly MIN_RUN-1 must not.
    """
    assert MIN_RUN == 30, "the fixtures below encode this value deliberately"
    at = _block("at", MIN_RUN)
    under = _block("under", MIN_RUN - 1)
    assert maximal_duplicate_runs(_block("a", 40) + at + _block("b", 40) + at)
    assert not maximal_duplicate_runs(
        _block("a", 40) + under + _block("b", 40) + under
    )


def test_reported_runs_are_maximal():
    """Restoring backward growth, and the claim two passes got wrong.

    The author's battery removed the backward-growth loop and saw no change; a
    reviewer's brute force over 600 documents found no MISSED start and called
    it dead code. Both asked whether a start is lost. Neither asked whether a
    NON-MAXIMAL run is gained, which is what the loop actually prevents.
    """
    doc = ["D", "E", "F", "Z1", "A", "B", "C", "D", "E", "F",
           "Z2", "A", "B", "C", "D", "E", "F"]
    runs = maximal_duplicate_runs(doc, min_run=3)
    assert (8, 10, 15, 17) not in runs, (
        "(8,10,15,17) is a strict sub-run of the maximal pair (5,10,12,17); "
        "reporting it violates this function's documented contract"
    )
    assert (5, 10, 12, 17) in runs
    # Three adjacent copies must collapse to two maximal pairs, not eight.
    assert len(maximal_duplicate_runs(_block("t", 35) * 3)) == 2


def test_runs_are_ordered_longest_first():
    """Nothing read the ordering, so the sort key was entirely unasserted —
    and the failure messages above say "Longest:" while printing whatever
    order the sort produced."""
    doc = (_block("short", 31) + _block("x", 5) + _block("short", 31)
           + _block("y", 5) + _block("long", 60) + _block("z", 5)
           + _block("long", 60))
    runs = maximal_duplicate_runs(doc)
    lengths = [a1 - a0 + 1 for a0, a1, _, _ in runs]
    assert lengths == sorted(lengths, reverse=True), lengths
    assert lengths[0] == 60


def test_a_duplicate_heading_on_the_final_line_is_seen():
    """`enumerate(lines[:-1], 1)` survived — the last line was invisible."""
    doc = ["## Phase 7 (x)", "body", "filler", "## Phase 7 (x)"]
    assert duplicate_heading_lines(doc), "a duplicate on the final line was missed"


def test_a_repeated_non_phase_heading_is_not_counted():
    """Over-acceptance: `HEADING_PREFIX = "## "` survived, because the real file
    happens to contain no duplicated non-phase `## ` heading. The scope is now
    pinned in the widening direction too."""
    doc = ["## Reading notes", "a", "## Reading notes", "b"]
    assert not duplicate_heading_lines(doc)
    assert duplicate_heading_lines(doc, prefix="## ")
