"""Shared helpers for prose drift guards (Phase 235's round, guards lens).

**Why this exists.** Phase 235 shipped a set of guards over shipped prose, every one of
them shaped `assert "<literal>" in <whole file>`. An independent reviewer ran 64 mutations
against them and **41 survived (64%)**, against the author's reported 17/17. The survivors
were not exotic. They were four mechanical properties of that shape:

1. **A substring survives inside its own negation.** `assert "gate the WORK, not the merge"
   in mirror` passes on *"It is NOT the case that those steps gate the WORK, not the
   merge."* — which is the retired claim, restored, with the guard green.
2. **A substring is satisfied by an incidental hit elsewhere in the file.** `assert "waive"
   in body` passes with the whole rationale deleted, because `review-close/SKILL.md` uses
   "waive"/"waived"/"waiver" twelve times for unrelated reasons.
3. **A section slice keyed to the next `## ` swallows every deeper heading between.** The
   `### User ops` "section" was 6,382 characters and contained all of `### Solo`, so a
   phrase planted in one satisfied a guard about the other.
4. **A population filtered by suffix silently omits shipped files.** Extensionless git
   hooks, `.fragment` and `.example` files are shipped and were outside the sweep.

`states()` and `section()` close 1–3. The sweep's population fix closes 4 at its call site.
"""
from __future__ import annotations

import re
import unicodedata

# Markers that turn a statement into its opposite. Checked only within the sentence
# carrying the phrase, so an unrelated "not" elsewhere in the paragraph is not a false kill.
_NEGATORS = (
    "not the case", "is false", "it is false", "no longer", "not true",
    "retired", "ignore any claim", "do not read", "never actually",
    "is wrong", "was wrong", "incorrect", "disregard", "except that",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n\n")


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def states(haystack: str, phrase: str) -> bool:
    """True when `haystack` ASSERTS `phrase` — present, and not inside a negation.

    The sentence carrying the phrase must not also carry a negator, and must not negate
    the phrase directly ("It is NOT the case that <phrase>"). A file that mentions the
    phrase only to retire it does not count as stating it.
    """
    if phrase not in haystack:
        return False
    for sentence in _sentences(haystack):
        if phrase not in sentence:
            continue
        low = sentence.lower()
        before = low[: low.index(phrase.lower())] if phrase.lower() in low else low
        if any(n in low for n in _NEGATORS):
            continue
        # "is not a restatement" is an assertion; " NOT <phrase>" immediately before is not.
        if re.search(r"\b(?:not|n't|never)\b[^.]{0,40}$", before):
            continue
        return True
    return False


def section(text: str, heading: str) -> str:
    """The body of `heading`, ending at the next heading of the SAME OR HIGHER level.

    `heading` is the full markdown heading line, e.g. `### Solo`. Raises AssertionError
    (never ValueError) with a message naming the problem, and requires the heading to be
    unique — a decoy duplicate earlier in the file silently redirected the original guard.
    """
    level = len(heading) - len(heading.lstrip("#"))
    marker = "\n" + heading + "\n"
    count = text.count(marker)
    assert count == 1, f"expected exactly one {heading!r} heading, found {count}"
    start = text.index(marker)
    rest = text[start + len(marker):]
    # any heading at level <= this one closes the section
    closer = re.compile(r"^#{1,%d} \S" % level, re.MULTILINE)
    m = closer.search(rest)
    return heading + "\n" + (rest[: m.start()] if m else rest)


def normalize(text: str) -> str:
    """Fold the variations a per-line literal regex misses: unicode dashes, `_`/`*`
    emphasis, and hard-wrapped lines. Used by the retired-claim sweep."""
    text = unicodedata.normalize("NFKC", text)
    for dash in ("‐", "‑", "‒", "–", "—", "−"):
        text = text.replace(dash, "-")
    text = re.sub(r"[*_`]+", "", text)
    return re.sub(r"\s+", " ", text)
