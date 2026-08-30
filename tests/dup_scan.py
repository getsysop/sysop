"""Duplicate-region detection for the phase log — Phase 245.

WHY THIS IS NOT A GREP. `Q-322` was filed, amended twice, retracted in full and
amended again, and every one of those passes used a `grep`-over-headings to
describe a pasted region. Headings are the wrong instrument twice over:

* **They cannot find the start.** The paste this module exists to prevent began
  mid-way through another phase's entry, at no heading at all: its first
  duplicated `## Phase ` heading is **151** lines further on. Every
  heading-anchored derivation therefore put the boundary in the wrong place, and
  the remedy the entry carried to the end would have left **145** lines of the
  duplicate behind while deleting unique content past the last duplicated
  heading. (Those two numbers are different distances and an earlier draft of
  this docstring conflated them: 145 is what the prescribed cut leaves behind,
  151 is how late a heading grep lands.)
* **They can be absent entirely.** A pasted region that happens to contain no
  `## Phase ` line is invisible to a heading check and perfectly visible here.

So the heading check below is kept as the cheap, legible gate, and the region
scan is the one that is actually load-bearing. Both are asserted; neither is a
substitute for the other, which is the whole finding.

The scan is a windowed-hash sweep grown to maximal runs, in both directions.

COST, stated honestly because an earlier draft of this line overclaimed it. On
ordinary prose it is near-linear: a window already covered by a discovered run
is skipped, so a large duplicated region costs one growth rather than one per
window. On *periodic* input it degrades to quadratic — 2,000 identical lines
take ~1s, 6,000 take ~13s — because the `covered` set marks one pair per growth
when the runs sit adjacent. Not reachable from a hand-written phase log (the
real file scans in 0.01s, and the 37,712-line pre-excision file in 0.02s), but
the claim "O(n) in the common case" was doing more work than the evidence.

WHAT THIS DOES NOT CATCH, so nobody reads the gate as broader than it is: it
finds **byte-identical** runs. A re-paste that is then edited — even one changed
line per 30 — splits into sub-runs below the threshold and is invisible here.
That is a deliberate scope, not an oversight: the defect this exists to prevent
was a mechanical paste, and near-duplicate detection is a different instrument
with a false-positive profile this gate does not want.
"""

from __future__ import annotations

import collections
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PHASE_LOG = REPO_ROOT / "PHASE_LOG.md"

#: A run shorter than this is not a "pasted region" — prose legitimately repeats
#: short passages (a quoted rule, a table header). 30 lines of byte-identical
#: text is not a coincidence in a hand-written log.
MIN_RUN = 30

HEADING_PREFIX = "## Phase "


def phase_log_lines() -> list[str]:
    return PHASE_LOG.read_text(encoding="utf-8").splitlines()


def duplicate_heading_lines(
    lines: list[str], prefix: str = HEADING_PREFIX
) -> dict[str, list[int]]:
    """Heading lines appearing more than once, mapped to their 1-indexed lines."""
    seen: dict[str, list[int]] = collections.defaultdict(list)
    for number, line in enumerate(lines, 1):
        if line.startswith(prefix):
            seen[line].append(number)
    return {line: at for line, at in seen.items() if len(at) > 1}


def maximal_duplicate_runs(
    lines: list[str], min_run: int = MIN_RUN
) -> list[tuple[int, int, int, int]]:
    """Every maximal pair of identical, non-overlapping runs of >= ``min_run``.

    Returns 1-indexed ``(a_start, a_end, b_start, b_end)`` tuples with
    ``a_start < b_start``, longest first. Empty means the text contains no
    duplicated block of that size.
    """
    if min_run < 1:
        raise ValueError(f"min_run must be >= 1, got {min_run}")
    n = len(lines)
    if n < min_run * 2:
        return []

    windows: dict[int, list[int]] = collections.defaultdict(list)
    for i in range(n - min_run + 1):
        windows[hash(tuple(lines[i : i + min_run]))].append(i)

    runs: set[tuple[int, int, int, int]] = set()
    covered: set[tuple[int, int]] = set()

    for starts in windows.values():
        # Pure optimization: a singleton yields no pairs below anyway. Kept for
        # cost, not for correctness — the battery's `RG08` row confirms removing
        # it changes no output, which is why that row is scored as a control.
        if len(starts) < 2:
            continue
        for idx, i in enumerate(starts):
            for j in starts[idx + 1 :]:
                if (i, j) in covered:
                    continue
                # Confirm the hash was not a collision before paying for growth.
                if lines[i : i + min_run] != lines[j : j + min_run]:
                    continue
                # BACKWARD GROWTH IS LOAD-BEARING, and this phase twice concluded
                # otherwise. The author's battery removed it and saw no change; a
                # reviewer's brute force over 600 random documents found no MISSED
                # run start and confirmed "dead code". Both asked whether a start
                # is lost. Neither asked whether a NON-MAXIMAL run is gained, and
                # that is what the loop prevents:
                #
                #   ["D","E","F","Z1","A","B","C","D","E","F","Z2","A","B","C","D","E","F"]
                #   min_run=3, without backward growth, yields (8,10,15,17) — a
                #   strict sub-run of the true maximal pair (5,10,12,17).
                #
                # `covered` only suppresses a shifted window-pair when the run's
                # true-start bucket is processed first; bucket order is
                # first-occurrence order, so any window whose content also occurs
                # EARLIER in the file inverts it. Without this loop the docstring's
                # "every maximal pair" is simply false, and three adjacent copies
                # of a region report 8 runs instead of 2.
                back = 0
                while (
                    i - back - 1 >= 0
                    and lines[i - back - 1] == lines[j - back - 1]
                ):
                    back += 1
                fwd = 0
                while (
                    j + min_run + fwd < n
                    and i + min_run + fwd < j - back
                    and lines[i + min_run + fwd] == lines[j + min_run + fwd]
                ):
                    fwd += 1
                a0, a1 = i - back, i + min_run + fwd - 1
                b0, b1 = j - back, j + min_run + fwd - 1
                if b0 <= a1:  # overlapping runs are a periodic passage, not a paste
                    continue
                for step in range(a1 - a0 + 1 - min_run + 1):
                    covered.add((a0 + step, b0 + step))
                runs.add((a0 + 1, a1 + 1, b0 + 1, b1 + 1))

    return sorted(runs, key=lambda r: (-(r[1] - r[0]), r[0]))
