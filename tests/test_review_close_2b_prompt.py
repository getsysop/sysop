"""Phase 218 — `/review-close` Step 2b's reviewer prompt: the live-state skew warning
(`Q-268`) and the paste/retrieve threshold (`Q-270`).

Both are prompt text, so the guards here are text guards — with one discipline the
review governor keeps having to re-learn: **a text guard that a synonym satisfies is not
a guard.** Each assertion below names the specific claim, and the negative assertions
name the specific way the fix has already been softened once in this repo's history
(a sentence relocated but left behind at its old site, so both readings ship).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"


def _body() -> str:
    return SKILL.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Whitespace-flattened, so a wrapped sentence is still findable. A line-oriented
    search cannot see a claim that wrapped, which is how a shipped falsehood survived
    three correction passes in Phase 217."""
    return re.sub(r"\s+", " ", text)


# ── Q-268: the skew warning covers live state, not only git state ──

def test_the_prompt_warns_about_live_state_skew_not_only_git_skew():
    """The only skew warning was git-shaped — merge-base semantics, phantom deletions.
    An agent that measures external state on a branch whose migration has already been
    applied reads the branch's own effects as evidence the task body is false."""
    flat = _flat(_body())
    assert "## Time skew — the diff is a point in time; live state is not" in _body()
    assert ("Live state may already reflect this branch's effects: its migrations may be "
            "applied, its scripts may have been run") in flat
    assert ("check whether the diff itself is what changed the thing you measured") in flat
    assert "Say which side of the branch's effects your measurement was taken on." in flat


def test_the_skew_warning_tells_the_agent_what_to_do_when_it_cannot_tell():
    """Without this, the rule degrades to 'be careful', which is the shape that produced
    four confident false BLOCKED findings in the reported run. The default must be
    stated, and it must be the non-blocking one.

    Presence is not enough. The round kept this sentence and appended *"That said, if the
    measurement looks wrong to you, report it as a violation anyway"* — green, and the
    stated default inverted. A rule and its contradiction shipping together is worse than
    neither, because the agent picks."""
    flat = _flat(_body())
    assert ("If you cannot tell which side, say so rather than reporting a violation."
            in flat)
    skew = flat[flat.index("## Time skew"):flat.index("## Prevention Conventions")]
    for contradiction in ("anyway", "That said", "even so", "regardless", "in doubt, report"):
        assert contradiction not in skew, (
            f"the Time skew block carries a clause that undoes its own default: "
            f"{contradiction!r}"
        )


def test_the_conventions_paste_requirement_carries_no_escape_clause():
    """Same shape: the verbatim requirement kept, and *"a condensed summary of the
    subsection headings is acceptable"* appended. Green, and the requirement gone."""
    flat = _flat(_body())
    # Re-pointed by `Q-342` (widened paste); same anchor role, new opening words.
    i = flat.index("paste EVERY section in step 1's convention-bearing set")
    window = flat[i:i + 700]
    for escape in ("condensed", "summary of the subsection", "is acceptable",
                   "abbreviated", "you may omit"):
        assert escape not in window, (
            f"the verbatim conventions requirement has an escape clause: {escape!r}"
        )


def test_the_retrieval_route_is_not_countermanded():
    """And again: the `git show` / `git diff` route kept, *"In practice do not run either
    command"* appended."""
    flat = _flat(_body())
    i = flat.index("Everything you need is reachable without moving `HEAD`")
    window = flat[i:i + 600]
    for countermand in ("do not run either", "In practice do not", "avoid running"):
        assert countermand not in window, (
            f"the retrieval route is countermanded in the same paragraph: {countermand!r}"
        )


def test_the_git_skew_warning_was_not_replaced_by_the_live_state_one():
    """Two different hazards. Adding the second by deleting the first would reopen the
    phantom-deletion class internal tracker #241 closed."""
    flat = _flat(_body())
    assert "Merge-base-relative — this is what the branch ADDED" in flat
    assert "Do not report missing content as removed." in flat


# ── Q-270: the paste/retrieve threshold, and the sentence that had to move ──

def _arm(flat: str, label: str) -> str:
    """The BODY of one threshold arm, so a guard can see which way round it is.

    Asserting the two labels are present cannot: the round swapped the two arms' bodies
    with both labels intact and every assertion here stayed green — a gate that reads
    "retrieve" for a 5 KB diff and "paste" for a 452 KB one."""
    i = flat.index(label) + len(label)
    ends = [flat.find(m, i) for m in ("- **", "> **") if flat.find(m, i) != -1]
    return flat[i:min(ends)] if ends else flat[i:i + 400]


def test_the_paste_threshold_is_stated_with_a_measured_command():
    flat = _flat(_body())
    assert "**Paste or retrieve — the threshold is 1,000 lines of `git diff` output.**" in flat
    assert "**At or below 1,000 lines:**" in flat
    assert "**Above 1,000 lines:**" in flat

    below = _arm(flat, "**At or below 1,000 lines:**")
    above = _arm(flat, "**Above 1,000 lines:**")
    assert "paste the diff verbatim" in below, below
    assert "--stat" not in below, below
    assert "--stat" in above, above
    assert "retrieval command" in above, above
    assert "paste the diff verbatim" not in above, above


def test_the_threshold_command_is_runnable_as_written():
    """The diff basis is defined in the table above as a WHOLE COMMAND. The first form
    of this block wrote `git diff <diff-basis>`, which substitutes to
    `git diff git diff main...<branch>` — `fatal: ambiguous argument`, swallowed by the
    pipe, `DIFF_LINES=0`, every target below the threshold, the gate silently inert.
    Found by executing it, and this is the assertion that would have caught it."""
    body = _body()
    assert "DIFF_LINES=$(git diff main...<branch> | wc -l | tr -d ' ')" in body
    assert "DIFF_LINES=$(git diff origin/main...HEAD | wc -l | tr -d ' ')" in body
    assert "git diff <diff-basis>" not in body, (
        "the diff basis is being substituted as an argument to `git diff` again — the "
        "table defines it as the whole command, so this expands to `git diff git diff ...`"
    )
    assert "git diff --stat <diff-basis>" not in body


def test_the_threshold_states_the_population_it_was_derived_over():
    """A number without its population is not a measurement. Phase 217's flagship
    correction was retracted for exactly this: it replaced somebody else's unsupported
    figure with one derived over a corpus set it never enumerated.

    The population must be named as an ENUMERATION, not as a date range. Phase 218's own
    round caught the first form doing exactly what this test exists to prevent: it said
    "the ten branch-shaped merges between 2026-08-18 and 2026-08-20", and by the time a
    reviewer ran that definition it selected eleven, because the consumer repo had moved.
    A date range over a live repository is not a stable population.
    """
    flat = _flat(_body())
    assert "ten branch-shaped merges" in flat
    assert "88, 224, 272, 273, 332, 366, 641, 2141, 2376 and 13,606 lines" in flat
    # ...and the summary sentence must AGREE with that list. The round changed "Seven of
    # ten" to "Nine of ten" with the list untouched and every assertion here green: a
    # guard written for "a number without its population" that cannot see the arithmetic.
    import re as _re
    m = _re.search(r"\*\*(\w+) of (\w+) sit under (\d+) lines", flat)
    assert m, "the summary sentence is gone"
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    claimed, total, cut = words[m.group(1).lower()], words[m.group(2).lower()], int(m.group(3))
    values = [88, 224, 272, 273, 332, 366, 641, 2141, 2376, 13606]
    assert total == len(values), (total, len(values))
    assert claimed == sum(1 for v in values if v < cut), (
        f"the sentence claims {claimed} of {total} under {cut}, but the list it sits "
        f"beside has {sum(1 for v in values if v < cut)}"
    )
    assert "`review-close: consolidate` integration commits are excluded" in flat
    assert "enumerated by commit in this project's maintainer record, not by a date range" in flat
    for stale in ("between 2026-08-18 and 2026-08-20", "two `review-close: consolidate`"):
        assert stale not in flat, (
            f"the unreproducible date-range population is back: {stale!r}"
        )


def test_the_threshold_states_what_it_does_not_claim():
    """Nobody measured whether a retrieval-only reviewer finds what a pasted-diff
    reviewer finds. Shipping the change without saying so would be the overclaim."""
    flat = _flat(_body())
    assert ("Nobody has measured whether a retrieval-only reviewer finds what a "
            "pasted-diff reviewer finds.") in flat
    assert "not a claimed optimum" in flat


def test_the_real_duplication_is_named_rather_than_quietly_fixed():
    """The filing said the diff is 'duplicated per agent'. It is not — Step 2b spawns one
    agent per TARGET and each gets its own target's distinct diff. What WAS duplicated
    identically N times was the conventions paste — Phase 222 (Q-275) fixed it with a
    paste-or-write-once threshold, and the note must still name the distinction where a
    reader will find it (rather than the fix silently erasing the history)."""
    flat = _flat(_body())
    assert ("the `## Prevention Conventions` section was pasted *identically* into every "
            "agent's prompt") in flat
    assert "each agent's diff is its own target's and is not duplicated at all" in flat
    assert "paste-or-write-once threshold" in flat, (
        "the note no longer points at the Q-275 fix that resolved the duplication"
    )


def test_the_everything_you_need_sentence_moved_and_did_not_stay_behind():
    """`The diff above is everything you need.` sat in the do-not-mutate paragraph, where
    it justified not needing `git checkout`. Under the retrieval arm it is false. Moving
    it means it is now conditional — and the old unconditional form must be GONE, or both
    readings ship and the agent picks whichever it likes."""
    body = _body()
    flat = _flat(body)
    assert "The diff above is everything you need. If" not in flat, (
        "the unconditional sentence is still in the do-not-mutate paragraph"
    )
    assert ("If a diff is pasted above, it is everything you need and you do not have to "
            "retrieve anything.") in flat
    assert ("If only a `--stat` summary is above, run the retrieval command given with it "
            "and read the hunks before reviewing — a `--stat` line is a file list, not a "
            "review.") in flat


def test_the_do_not_mutate_paragraph_still_gives_a_retrieval_route():
    """Removing the dangling sentence must not remove the reason the paragraph is
    survivable: an agent told not to move `HEAD` needs to be told how to read anyway."""
    flat = _flat(_body())
    assert ("Everything you need is reachable without moving `HEAD`: read any revision's "
            "file content with `git show <sha>:<path>` and any revision's changes with "
            "`git diff <base>...<tip>`.") in flat
    assert "no `git checkout`, `switch`, `reset`, `stash`," in flat


def test_the_prompt_still_pastes_the_conventions_section_verbatim():
    """The threshold is about the diff. Nothing here weakens the requirement that the
    agent routes against the project's own conventions text, unfiltered.

    Re-pointed by `Q-342` (widened paste). The requirement it guards is the same
    one and now covers more: every section in the rule-bearing set, verbatim,
    each under its own heading.
    """
    flat = _flat(_body())
    assert ("paste EVERY section in step 1's convention-bearing set from CLAUDE.md "
            "verbatim — each under its own original `## <name>` heading, including "
            "every subsection. Do not pre-filter, merge or rename sections or "
            "subsections") in flat
