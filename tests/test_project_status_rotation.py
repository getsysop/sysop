"""`/review-close` Step 4c's §6 write must not out-scale its own rotation (#364).

The defect: `:1017` writes one PROJECT_STATUS §6 entry **per pending-doc** — a
number that scales with branch count — while the rotation below it truncates to
a **constant**. With 6 pre-existing entries and 8 pending-docs, 6 + 8 = 14
rotates to 6, discarding all 6 pre-existing entries *and 2 of the 8 just
written*, in the commit that wrote them — the shape `/auto-fix` and `/auto-judge`
produce, i.e. Sysop's own workflows.

**The condition, corrected in-round.** The filing said this "reproduces whenever
`pre_existing + docs > 8` and `docs > 2`", and this module's first draft repeated
it. It is false on 22 of the 49 `(pre_existing, docs)` pairs up to 9, all in the
over-claiming direction: the run's entries go in newest-first, so rotation reaches
them only after consuming every pre-existing entry, which needs `docs > keep` —
`docs > 6`, not 2. `test_the_stated_reproduction_condition_matches_the_rotation_it_describes`
now simulates the rotation over the whole grid and compares it against the
condition the shipped prose states, so the next author cannot carry a filed number
here either.

**These are prose guards on an agent-executed step, and Phase 192's round is why
they are shaped the way they are.** That round inverted a shipped contract in
every direction it tried — lanes swapped, an exception carved out of a fail-safe
default, the rule relocated 350 lines from the step that routes on it — with
every asserted phrase still present, because every check was `needle in text`.
So: the arithmetic invariant is asserted by **parsing both numbers out of the
shipped text and comparing them** rather than by pinning either spelling; each
rule assertion is scoped to the block that carries the rule; the licence check
forbids an exception rather than requiring a phrase; and ordering is asserted by
line index, because "consolidate, then rotate" is the half that makes the
arithmetic hold.

What no test here can do — stated because a green suite is not compliance — is
prove an agent obeys the clause. `PROJECT_STATUS.md` is consumer-authored,
Sysop ships no template for it, and Step 4c has no runnable extract: the whole
step is instructions. What is executable is the relationship between the two
numbers, and that is what fails when either drifts.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"

STEP_4C = "### 4c. Consolidate Pending Documentation"
STEP_4D = "### 4d. Land on `main`"

_NUM = r"(\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
_MORE_THAN = r"more than " + _NUM

CONSOLIDATION_ANCHOR = "**Consolidation clause"
ROTATION_ANCHOR = "**Rotation check**"


def _lines():
    return SKILL.read_text(encoding="utf-8").splitlines()


def _step_4c_bounds(lines):
    starts = [i for i, ln in enumerate(lines) if ln.strip().startswith(STEP_4C)]
    ends = [i for i, ln in enumerate(lines) if ln.strip().startswith(STEP_4D)]
    assert len(starts) == 1, f"Step 4c heading appears {len(starts)} times"
    assert ends and ends[0] > starts[0], "Step 4d heading not found after 4c"
    return starts[0], ends[0]


def _one_line_starting_with(lines, prefix, lo, hi):
    """The rule itself, not a later paragraph that cites it by name.

    `**Consolidation clause` appears twice in Step 4c on purpose — once as the
    rule and once in the staging note that depends on it — so a `needle in text`
    match cannot tell the rule from a reference to it. That distinction is the
    whole point of scoping an assertion to the line carrying the rule.
    """
    hits = [i for i in range(lo, hi) if lines[i].strip().startswith(prefix)]
    assert len(hits) == 1, (
        f"expected exactly one line starting with {prefix!r} inside Step 4c, got {hits}"
    )
    return hits[0]


@pytest.fixture(scope="module")
def step4c():
    lines = _lines()
    lo, hi = _step_4c_bounds(lines)
    return lines, lo, hi


# ── the arithmetic invariant ────────────────────────────────────────────────


_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}


def _as_int(token):
    """Digits or an English number word — both are ordinary ways to write a rule.

    Lens 3's A15 spelled the threshold "more than four" and reddened two tests: a
    guard that fails on a correct edit teaches the next maintainer to weaken it,
    which is worse than the gap it was protecting.
    """
    return int(token) if token.isdigit() else _WORDS[token.lower()]


def _only_number(line, pattern, what):
    """Exactly one match, because `re.search` takes the FIRST one.

    Lens 3 defeated the previous version twice by prepending a decoy: a clause
    reading "never leaves more than 6 entries standing" ahead of the real
    "**If `<N>` is more than 12**", and "only 6 remain visible in §6" ahead of the
    real "until only 2 remain". Both times the guard read 6, reported `kept >= cap`
    satisfied, and the shipped rule discarded entries the run had just written. A
    rule's own number must be the only one its pattern can find on that line.
    """
    hits = re.findall(pattern, line)
    assert len(hits) == 1, (
        f"{what}: expected exactly one {pattern!r} on the rule's line, found "
        f"{hits} — a second number of the same shape makes the first one a decoy"
    )
    return _as_int(hits[0])


def _rule(step4c):
    """The shipped rotation, parsed into the parameters that decide its behaviour.

    Numbers alone are not the rule: **which end rotates** and **where new entries
    are inserted** decide whether a close can discard its own work, and neither was
    asserted anywhere before this round. Lens 3 turned "rotate the oldest" into
    "rotate the newest" with `kept >= cap` still true and the suite green — #364
    reopened in its worst form, since the entries the close just wrote become the
    first thing removed.
    """
    lines, lo, hi = step4c
    cap_line = _logical_clause(lines, lo, hi)
    rot_line = lines[_one_line_starting_with(lines, ROTATION_ANCHOR, lo, hi)]
    write_line = lines[_one_line_starting_with(lines, "**PROJECT_STATUS.md §6**", lo, hi)]

    cap = _only_number(cap_line, _MORE_THAN, "consolidation cap")
    trigger = _only_number(rot_line, _MORE_THAN + r" entries", "rotation trigger")
    keep = _only_number(rot_line, r"only " + _NUM + r" remain", "retained count")

    # Direction and insertion point, asserted rather than assumed.
    assert "rotate the oldest entries" in rot_line, (
        f"the rotation must name the end it removes from: {rot_line!r}"
    )
    assert "rotate the newest" not in rot_line, rot_line
    assert "Insert at the TOP of Section 6" in write_line, write_line
    assert "changelog.md" in rot_line, ("the rotation must name where entries go, or "
                                       "the staging note guards nothing: " + rot_line)
    return cap, trigger, keep


def test_a_close_can_never_rotate_out_an_entry_it_just_wrote(step4c):
    """The whole of #364, simulated from the parsed rule rather than asserted.

    This replaces a `kept >= cap` comparison that three separate mutations walked
    through — two by decoy number, one by reversing the rotation direction the
    comparison never looked at. Here the parameters are read off the shipped text,
    including direction and insertion point, and the model is run over the grid.
    """
    cap, trigger, keep = _rule(step4c)
    losses = [
        (pre, docs)
        for pre in range(0, 15)
        for docs in range(1, 15)
        if _loses_own_entry(pre, min(docs, 1 if docs > cap else docs), trigger, keep)
    ]
    assert losses == [], (
        f"with cap={cap}, trigger={trigger}, keep={keep} a close still discards "
        f"entries it wrote, at (pre_existing, docs) = {losses[:6]}"
    )


def test_the_rotation_keeps_at_least_as_many_as_one_run_may_write(step4c):
    """`kept >= cap`, read off the shipped text — the whole of #364 in one line.

    A run contributes at most `cap` entries (above `cap` the consolidation clause
    collapses them to one), and the rotation keeps the `kept` newest. So an entry
    this run wrote survives its own close **iff** `kept >= cap`. Today that is
    6 >= 4. Raising the cap past 6, or lowering the retained count below the cap,
    re-opens the defect — and neither edit has to touch a phrase any other test
    here pins.
    """
    cap, _trigger, kept = _rule(step4c)
    assert cap >= 1, cap
    assert kept >= cap, (
        f"a close may write {cap} §6 entries but the rotation keeps only {kept} "
        "— the run would rotate out entries it just wrote (#364)"
    )


def test_the_consolidation_clause_binds_the_per_branch_write(step4c):
    """It must say what NOT to do, not merely mention consolidating.

    An earlier draft of this fix that only *added* a consolidated-entry option,
    leaving the per-branch write unconditional, is satisfied by any check that
    looks for the word "consolidate" — and changes nothing.
    """
    lines, lo, hi = step4c
    clause = _logical_clause(lines, lo, hi)
    assert re.search(r"\bdo not write the per-branch entries\b", clause, re.I), clause
    # The antecedent, not just the consequent: the instruction is conditional on
    # a count the step actually has.
    assert re.search(r"\bIf\b.{0,40}\b" + _MORE_THAN + r"\b", clause), clause
    # **Polarity, not presence.** Lens 3 inverted the conditional by *adding* a
    # second, un-negated copy — "write the per-branch entries above as usual;
    # otherwise do not write the per-branch entries above" — which satisfies both
    # assertions above while telling the agent to do the opposite. So every
    # occurrence of the phrase must be negated, not just one of them.
    occurrences = [m.start() for m in re.finditer(
        r"write the per-branch entries", clause, re.I)]
    assert occurrences, clause
    for start in occurrences:
        preceding = clause[max(0, start - 8):start].lower()
        assert preceding.endswith("do not "), (
            "an un-negated 'write the per-branch entries' at offset "
            f"{start} inverts the clause: {clause[max(0, start - 60):start + 60]!r}"
        )


def test_the_consolidation_clause_carves_out_no_exception(step4c):
    """Forbid a licence rather than require a phrase (Phase 192's round).

    The cheapest way to disarm a fail-safe is to leave every asserted phrase in
    place and add "unless the entries are short" beside it.
    """
    lines, lo, hi = step4c
    clause = _logical_clause(lines, lo, hi).lower()
    for licence in ("unless", "except when", "optional", "if you prefer",
                    "at your discretion", "may skip", "is enough",
                    "need not apply", "need not", "keeping them separate",
                    "is preferable"):
        assert licence not in clause, (
            f"the consolidation clause carries a licence ({licence!r}): {lines[i]!r}"
        )


def test_consolidation_is_stated_before_the_rotation_it_bounds(step4c):
    """Order is the reason the arithmetic holds: collapse first, then truncate.

    Stated after the rotation, the clause describes a truncation that has already
    happened — the same relocation defeat Phase 192's round ran on a routing rule
    moved 350 lines off the step that routes on it.
    """
    lines, lo, hi = step4c
    write = _one_line_starting_with(lines, "**PROJECT_STATUS.md §6**", lo, hi)
    cap = _one_line_starting_with(lines, CONSOLIDATION_ANCHOR, lo, hi)
    rot = _one_line_starting_with(lines, ROTATION_ANCHOR, lo, hi)
    assert write < cap < rot, (
        f"expected per-branch write ({write}) < consolidation ({cap}) < "
        f"rotation ({rot}) inside Step 4c"
    )


# ── the two downstream sites that must not fall out of step ─────────────────


def test_the_staging_note_names_both_writers_of_changelog(step4c):
    """`changelog.md` now has three writers; staging it off the routing table
    alone drops whichever one ran.

    The pre-existing guard (`test_review_close_pr_policy.py`) pins the rotation
    half. This one pins that the consolidation half was added to the same note
    rather than left for the next reader to discover from a lost file.
    """
    lines, lo, hi = step4c
    note = [ln for ln in lines[lo:hi]
            if "Do not stage `changelog.md` from the routing table alone" in ln]
    assert len(note) == 1, note
    text = note[0]
    assert "Rotation check" in text, text
    assert "Consolidation clause" in text, text
    assert "regardless of entry type" in text, text


def test_the_run_reports_what_it_rotated_out(step4c):
    """A truncation nothing announces is how this defect survived unnoticed.

    Step 8's report said `<N> new entries` and never how many left, so the run
    that discarded six entries and the run that discarded none printed the same
    line.
    """
    lines = _lines()
    hits = [ln for ln in lines if "PROJECT_STATUS.md §6:" in ln]
    assert len(hits) == 1, hits
    assert "rotated out" in hits[0], hits[0]


def test_the_rotation_rule_tells_the_run_to_report_the_count(step4c):
    """…and the instruction to report it sits on the rule, not only in Step 8.

    A report template line with no step telling anyone to fill it is a field that
    gets written `unreported` — the #367 shape, one phase earlier.
    """
    lines, lo, hi = step4c
    i = _one_line_starting_with(lines, ROTATION_ANCHOR, lo, hi)
    assert re.search(r"report the count you rotated", lines[i], re.I), lines[i]


# ── the condition the prose states, checked against the rotation it describes ──


def _loses_own_entry(pre_existing, docs, trigger, keep):
    """Simulate the shipped rule: insert `docs` newest-first, truncate to `keep`."""
    total = pre_existing + docs
    if total <= trigger:
        return False
    return (total - keep) > pre_existing


def test_the_stated_reproduction_condition_matches_the_rotation_it_describes(step4c):
    """The prose's own `docs > N` claim, executed rather than trusted.

    Found by this phase's round. The filing said the defect "reproduces whenever
    `pre_existing + docs > 8` and `docs > 2`", the clause's first draft repeated it,
    and it is false on 22 of the 49 `(pre_existing, docs)` pairs up to 9 — every one
    in the over-claiming direction. The run's entries are inserted newest-first, so
    rotation reaches them only after consuming every pre-existing entry: it removes
    `total - keep`, which exceeds `pre_existing` exactly when `docs > keep`.

    This is the guard that would have caught the phase carrying a filed number
    instead of deriving it, so it derives all three numbers from the shipped text
    and compares the stated condition against the simulation over the whole grid.
    """
    lines, lo, hi = step4c
    _cap, trigger, keep = _rule(step4c)

    why = "\n".join(lines[lo:hi])
    m = re.search(r"`pre_existing \+ docs > (\d+)`\s*\*\*and `docs > (\d+)`\*\*", why)
    assert m, "the clause states no reproduction condition to check"
    stated_trigger, stated_docs = int(m.group(1)), int(m.group(2))

    assert stated_trigger == trigger, (stated_trigger, trigger)
    assert stated_docs == keep, (
        f"the clause says the run loses its own entries when docs > {stated_docs}, "
        f"but the rotation keeps {keep}, so the boundary is docs > {keep}"
    )

    # …and the stated condition agrees with the simulation on every pair.
    for pre in range(0, 12):
        for docs in range(1, 12):
            stated = (pre + docs > stated_trigger) and (docs > stated_docs)
            actual = _loses_own_entry(pre, docs, trigger, keep)
            assert stated == actual, (pre, docs, stated, actual)


def test_the_cap_does_not_claim_to_be_forced_by_the_arithmetic(step4c):
    """Any cap <= the retained count closes self-loss, so 4 is a judgement.

    Stating a readability choice as an arithmetic necessity is the kind of claim a
    reviewer falsifies in one line, and the clause now says which half is which.
    """
    why = "\n".join(step4c[0][step4c[1]:step4c[2]])
    assert "is not required by the defect" in why, why
    assert "readability" in why, why
    assert re.search(r"cap must never exceed the retained count", why), why


# ── closures for lens 3's review-close survivors ─────────────────────────────


def test_the_clause_keeps_the_content_the_defect_removed(step4c):
    """Three survivors were silent content loss, not softening.

    A12 stopped routing per-branch detail anywhere (the consolidated §6 line then
    points at nothing); A17 counted every pending-doc rather than the merged-only
    set from 1b (so an unmerged branch inflates the count that decides the
    consolidation); A18 dropped the branch list from the consolidated entry, which
    is the provenance the entry exists to carry.
    """
    lines, lo, hi = step4c
    clause = _logical_clause(lines, lo, hi)
    # The routing INSTRUCTION, not the word: the consolidated entry's own template
    # names `changelog.md` too, so a line-level check was satisfied while the
    # instruction that puts anything there was deleted (lens 3's A12 — silent loss).
    assert "route **every** entry's detail to `changelog.md`" in clause, (
        f"the clause no longer routes per-branch detail anywhere: {clause}")
    assert "merged-only set from step 1b" in clause, clause
    assert "batch or branch list" in clause, ("the consolidated entry must name the "
                                             f"branches: {clause}")


def test_the_rotation_report_survives_as_a_countable_field(step4c):
    """A10/A11: the report field lost its count, and the instruction was negated.

    A10 kept the words "rotated out" as prose while dropping `<N>`, so the run
    reports a truncation without saying how big it was — the exact blindness that
    let #364 run unnoticed. A11 prefixed the instruction with "You need not", which
    the previous regex matched happily.
    """
    lines = _lines()
    field = next(ln for ln in lines if "PROJECT_STATUS.md §6:" in ln)
    assert re.search(r"<N> rotated out", field), field

    lo, hi = _step_4c_bounds(lines)
    rot = lines[_one_line_starting_with(lines, ROTATION_ANCHOR, lo, hi)]
    for m in re.finditer(r"[Rr]eport the count you rotated", rot):
        preceding = rot[max(0, m.start() - 30):m.start()].lower()
        for negation in ("need not", "no need to", "optional", "may skip"):
            assert negation not in preceding, (
                f"the report instruction is negated: {rot[max(0, m.start() - 60):]!r}")


def test_the_staging_note_is_not_contradicted_beside_itself(step4c):
    """A09 kept all three needles and appended a clause undoing them.

    "…staging from the table alone is sufficient" sits next to the rule saying it is
    not. Forbidding the contradiction is the only reading a presence check cannot
    give.
    """
    lines, lo, hi = step4c
    note = next(ln for ln in lines[lo:hi]
                if "Do not stage `changelog.md` from the routing table alone" in ln)
    flat = " ".join(note.split()).lower()
    for contradiction in ("table alone is sufficient", "table alone suffices",
                          "is enough on its own", "need not stage"):
        assert contradiction not in flat, f"the staging note contradicts itself: {note}"


# ── the clause is pinned verbatim (Phase 168's precedent) ────────────────────

def _logical_clause(lines, lo, hi):
    """The consolidation clause including its wrapped continuation lines."""
    i = _one_line_starting_with(lines, CONSOLIDATION_ANCHOR, lo, hi)
    j = i + 1
    while j < len(lines) and lines[j].strip():
        j += 1
    return " ".join(" ".join(lines[i:j]).split())


def _canon(s):
    """Collapse whitespace and normalise number words, then compare."""
    out = " ".join(s.split())
    for word, digit in _WORDS.items():
        out = re.sub(rf"\b{word}\b", str(digit), out, flags=re.I)
    return out


_CLAUSE_OPERATIVE = (
    "**Consolidation clause — a wide close writes ONE §6 entry, not one per branch.** Count the pending-docs this run is routing (the merged-only set from step 1b, the same `<N>` the commit subject carries). **If `<N>` is more than 4**, do not write the per-branch entries above. Write a single one-line entry instead — `<date>: <N> branches merged in one close: <batch or branch list> — per-branch detail in changelog.md` — and route **every** entry's detail to `changelog.md` as a bullet under today's date heading, whatever its `type`."
)


def test_the_consolidation_clause_is_pinned_verbatim(step4c):
    """The last survivor: a licence inserted MID-clause, in arbitrary English.

    Lens 3 spliced "Where the per-branch summaries are short, keeping them separate
    is preferable and this clause need not apply." into the middle of the rule. Every
    blacklist here is synonym-bypassable — Phase 179 abandoned
    polarity-by-string-matching at 0/21 and Phase 180 declared the softening class a
    residual — so for a rule this short the answer is the one Phase 168 used when its
    own ratchet was killed by a 19-character softening: **pin the line verbatim.**

    The cost is real and is the point: rewording this clause now takes a deliberate
    edit here too. That is what a ratified rule should cost, and it is cheaper than a
    blacklist that grows by one entry per reviewer.
    """
    lines, lo, hi = step4c
    # The **logical** line, not the physical one: markdown wraps, and a reflow that
    # moves the tail onto a second line changes nothing about the rule. Reading only
    # the anchored line made a reflow look like a deleted tail.
    i = _one_line_starting_with(lines, CONSOLIDATION_ANCHOR, lo, hi)
    j = i + 1
    while j < len(lines) and lines[j].strip():
        j += 1
    logical = " ".join(" ".join(lines[i:j]).split())
    # **Only the operative sentences are pinned.** The clause ends with a rationale
    # tail ("Then §6 reads as one update …"), and pinning that too reddened four
    # negative controls across two batteries for pure rewording — the
    # over-strictness the governor says to weigh as heavily as a miss. The tail is
    # left free and covered by the licence check below instead.
    # Cut on the OPERATIVE side's last words, not on the tail's first words: the
    # tail is free to be reworded, so anchoring the boundary in it made the pin fail
    # on exactly the edits unpinning the tail was meant to allow.
    end = "whatever its `type`."
    assert end in logical, (
        "the clause lost its routing sentence, which is the operative half's last "
        f"instruction: {logical}")
    actual = logical[:logical.index(end) + len(end)].strip()
    # **Tolerant of the two things that are not the rule**, because a pin that
    # reddens on a reflow is the over-strictness the governor says to count as
    # seriously as a miss. Whitespace is collapsed (a soft line break is not a
    # change) and an English number word reads as its digit ("more than four" ==
    # "more than 4"). Everything else — including an inserted sentence — fails.
    if _canon(actual) == _canon(_CLAUSE_OPERATIVE):
        return
    assert False, (
        "the consolidation clause's OPERATIVE half was reworded. If that was "
        "deliberate, update _CLAUSE_OPERATIVE in this test in the same commit — the "
        "pin exists because "
        "every licence blacklist protecting this rule was walked through by one "
        "synonym.\n\n"
        f"  shipped:  {actual}\n\n  pinned:   {_CLAUSE_OPERATIVE.strip()}"
    )
