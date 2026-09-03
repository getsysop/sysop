"""The reversal layer, in one place — the shared home `Q-367` asks for.

**Why this module exists.** Phase 247's round ran 94 independent mutations against
that phase's first guards and **53 survived; 38 of the 53 were one move**: keep every
string the guard greps for, and add a sentence next to it that reverses the meaning.
A presence check cannot see that by construction — `"not on the flags" in step` is
satisfied forever by a step whose next sentence says *match on the flags*.

Skills in this repo do not decay by deletion; they decay by softening. Phase 168's
19-character weakening, Phase 179's shipped-remedy-unreachable, Phase 190's column
false for four of six rows — all this shape. So each bounded step gets a **negative**
assertion: the vocabulary of reversal must not appear inside its slice.

**Why it is a module rather than a fourth copy.** Phase 248's round filed `Q-367`:
three modules had re-implemented this check inline (two defining `assert_no_reversal`,
one open-coding the same vocabulary), which is the duplicate-then-diverge
shape `Q-256` recorded for the Pass-1a token list, and two of the copies had already
drifted apart. Phase 249 needed the check for two more steps and would have made a
fourth copy, so it built this instead. **Phase 253 closed `Q-367`**: the three in-module
copies now import this, and the vocabulary below is the shared list plus the generic entries the Step 4b
copy carried and the others lacked, measured against every caller's shipped text
before it was merged (a caller that
false-alarms on its own shipped prose gets deleted by the first operator who hits it).

**Two kinds of vocabulary, and the split is deliberate.** `REVERSAL_VOCAB` holds the
*generic* softeners — phrasings that read as a licence in any bounded step. A phrasing
that softens one specific step (*"leave the flag off"* is a reversal of Step 4b and
noise anywhere else) is passed by that caller as `extra=`, so it never reddens a step
it was not written about. The Step 4b guard carried both kinds in one list before
this split; the round that filed `Q-367` walked through it with the generic entries
the precedent module had and Step 4b's copy had dropped.

**Deliberately narrow, and the narrowness is the point.** A step legitimately says
"advisory" when it is *citing* a refused alternative, so each caller passes the exempt
phrases it actually ships. A guard that flags its own shipped text gets deleted by the
first operator who hits it.

**What this layer is not.** Phase 249's round wrote 25 out-of-vocabulary softenings
against two freshly wired steps and all 25 survived; Phase 179 measured
polarity-by-string-matching at 0 of 21 before abandoning it. The value here is that the
phrasings this project has already been burned by cannot recur silently. It is not a
general closure, and a longer list is not the remedy (`Q-374`).
"""

# The generic softeners. Every entry is here because a mutation walked through a guard
# without it: the first eleven from Phase 247's round, `in practice` and the two
# `acceptable` forms from Phase 249's, and the block after them from Phase 248's round
# against Step 4b (*"in practice you can leave the flag off"*, *"no action is needed"*),
# which the Step 4b guard alone carried until Phase 253 merged the copies.
REVERSAL_VOCAB = (
    "is advisory",
    "are advisory",
    "advisory only",
    "and continue the close",
    "the close proceeds",
    "the close is not held",
    "skip this step entirely",
    "skip here too",
    "does not second-guess",
    "may be summarised",
    "may be summarized",
    # `will do` is DELIBERATELY ABSENT here. Two in-module copies carried it until Phase
    # 253 retired them in favour of this module; it is a bare English bigram with no
    # softening signal, and Phase 249's round measured it false-alarming on a sentence
    # that REINFORCES the shipped rule ("whoever runs the close will do so from the
    # primary in most cases, but not all — hence the identity test"). A guard that
    # reddens on prose defending the rule is the shape that teaches the next author to
    # delete it. Phase 253 measured the cost of dropping it before dropping it: none of
    # the 102 reconstructed reviewer mutations from Phase 248's round contains the
    # bigram, so no kill in that battery depended on it. The divergence is recorded in
    # `Q-367`'s archive entry rather than silently introduced.
    "in practice",
    "is acceptable",
    "are acceptable",
    # Promoted from the Step 4b guard's private list by Phase 253 (Phase 248's round
    # wrote the bypasses these close). Generic: each reads as a licence in any step.
    "in day-to-day use",
    "no action is needed",
    "not needed",
    "is optional",
    "are optional",
    "you can leave",
)


def assert_no_reversal(step: str, name: str, exempt=(), extra=()) -> None:
    """Fail if reversal vocabulary appears in *step* outside the exempt spans.

    `exempt` holds the phrases the step ships on purpose — a refused alternative it
    names, a disposition it explicitly grants. Everything else reads as a softening
    added next to a pinned phrase. A stale exemption is itself an assertion failure:
    an exemption that no longer matches anything silently widens what this permits.

    **Each exemption must occur exactly once.** `str.replace` strips EVERY occurrence,
    so a second copy of an exempted phrase would carve a second hole the exemption was
    never granted for — Phase 248's round defeated the first cut of the Step 4b layer
    by writing a reversal AROUND an exempted span. The Step 4b guard adopted
    `count == 1` in response; when Phase 253 merged the copies it kept the stricter
    rule for every caller rather than the `in` check the two older copies had.

    `extra` holds the step-specific reversal phrasings this caller adds to the generic
    list — softenings of *this* step that would be noise anywhere else.

    **`in practice` is kept and it WILL false-alarm.** The round wrote two reinforcing
    sentences containing it and both reddened. It stays because it is the highest-signal
    entry on this list -- it closed Phase 249's own surviving mutation -- and the remedy
    for a legitimate use is `exempt=`, in the same commit, with the reason. A cost paid
    knowingly, not an oversight.
    """
    haystack = step
    for phrase in exempt:
        n = step.count(phrase)
        assert n == 1, (
            f"{name}: exemption {phrase!r} occurs {n} times in the step (expected exactly "
            f"1) — a stale exemption silently widens what this guard permits, and a "
            f"duplicated one carves a second hole the exemption was never granted for"
        )
        haystack = haystack.replace(phrase, "")
    low = haystack.lower()
    hits = [v for v in (*REVERSAL_VOCAB, *extra) if v.lower() in low]
    assert not hits, (
        f"{name}: reversal vocabulary {hits} appears in the step outside its declared "
        f"exemptions. Every greppable string the pins hold can be preserved while the "
        f"sentence beside it says the opposite; that is how 38 of 53 mutations walked "
        f"through the first version of these guards. If the new wording is deliberate, "
        f"add it to `exempt=` in the same commit and say why."
    )


def slice_between(text: str, start: str, end: str, name: str) -> str:
    """The text from *start* up to *end*, failing closed if either anchor moves.

    A slice that silently returns "" when its end marker is renamed makes every
    negative assertion over it vacuously true — Phase 248's `test_slice_fails_closed`
    exists for exactly that, and this helper carries the same property so a caller
    cannot reintroduce it.
    """
    i = text.find(start)
    assert i >= 0, f"{name}: start anchor {start!r} not found"
    j = text.find(end, i + len(start))
    assert j > i, f"{name}: end anchor {end!r} not found after the start anchor"
    return text[i:j]
