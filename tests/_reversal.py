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
fourth copy, so it built this instead. **`Q-367` is not closed by this file** — its
remaining scope is the two existing in-module copies adopting it, which is a refactor
of guards this phase does not otherwise touch, and doing it here would put a rewrite
of three unrelated modules inside a phase about `/claim-task` and `/review-close`.

**Deliberately narrow, and the narrowness is the point.** A step legitimately says
"advisory" when it is *citing* a refused alternative, so each caller passes the exempt
phrases it actually ships. A guard that flags its own shipped text gets deleted by the
first operator who hits it.
"""

# Kept in sync with the in-module copies by intent, not by machinery — see `Q-367`.
# The last two entries were added by Phase 249, each justified by a mutation that
# walked through the pins without them: a disposition list gaining "reporting a single
# combined waiver count is acceptable", and a fixed predicate gaining "either form is
# acceptable". Both preserve every pinned string.
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
    # `will do` is DELIBERATELY ABSENT here, and the two in-module copies still carry it.
    # It is a bare English bigram with no softening signal, and the round measured it
    # false-alarming on a sentence that REINFORCES the shipped rule ("whoever runs the
    # close will do so from the primary in most cases, but not all — hence the identity
    # test"). A guard that reddens on prose defending the rule is the shape that teaches
    # the next author to delete it. The divergence is recorded in `Q-367` rather than
    # silently introduced.
    "in practice",
    "is acceptable",
    "are acceptable",
)


def assert_no_reversal(step: str, name: str, exempt=()) -> None:
    """Fail if reversal vocabulary appears in *step* outside the exempt spans.

    `exempt` holds the phrases the step ships on purpose — a refused alternative it
    names, a disposition it explicitly grants. Everything else reads as a softening
    added next to a pinned phrase. A stale exemption is itself an assertion failure:
    an exemption that no longer matches anything silently widens what this permits.

    **`in practice` is kept and it WILL false-alarm.** The round wrote two reinforcing
    sentences containing it and both reddened. It stays because it is the highest-signal
    entry on this list -- it closed this phase's own surviving mutation -- and the remedy
    for a legitimate use is `exempt=`, in the same commit, with the reason. A cost paid
    knowingly, not an oversight.
    """
    haystack = step
    for phrase in exempt:
        assert phrase in step, (
            f"{name}: exemption {phrase!r} is not in the step — a stale exemption "
            f"silently widens what this guard permits"
        )
        haystack = haystack.replace(phrase, "")
    hits = [v for v in REVERSAL_VOCAB if v in haystack.lower()]
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
