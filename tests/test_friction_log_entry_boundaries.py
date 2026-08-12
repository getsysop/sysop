"""The friction log's entry boundary — both id kinds, and fences are not headings.

`/report-issues` read entry blocks as "each begins `## ISSUE-NNNN — …`" and the
file contained **zero** occurrences of "good", so a `## GOOD-NNNN — …  [good]`
heading was not a boundary and the win's body was absorbed by the preceding bug.
Observed, not theorised: upstream issue #360's body carries all of `GOOD-0026`
and #364's carries `GOOD-0027`. Three costs — a win published under consent
given for a bug; no `**Shared:** <url>` line written, so the next `/share-wins`
run posts it again and the anti-double-post backstop cannot see this path; and
the filed-side `**Filed:**` backstop records nothing either.

The exclusion was one-directional: `/share-wins` has scoped `ISSUE-NNNN` out
since it shipped — verified, the clause is in its creating commit `aff195b`
(Phase 107) — with no reciprocal clause. That, plus upstream #264, is why this is
a **boundary rule** in both skills rather than a third point fix.

**#264 was read from the upstream issue, not from the queue's one-line summary of
it, and the difference changed the fix.** The checklist logs it as "a wrap-induced
fence swallowed three entries" and marks it unverified. The body gives the
mechanism: a wrapped list item put ```` ```plan ```` at **column 3**, which
CommonMark reads as a fence opener with an info string, and the 119 lines it
opened absorbed the rest of `ISSUE-0024`, the whole of `ISSUE-0023` and the head
of `ISSUE-0022` — taking the file from 36 fence-opener-eligible lines (balanced)
to 39. A fence rule that recognised only column-0 openers would have shipped
without catching the one instance it was written for, so the shipped rule states
the three-space allowance and the parity signal, and `FENCE` below is
`^ {0,3}```` rather than the `^\\s*` a first pass reaches for.

**The executable half is the part worth trusting here.** These are prose
instructions to an agent and no test can prove one obeys them — so rather than
only matching sentences, the tests below extract the installer's real seeding
heredoc, run it through `bash` so the expansion is the shipped one, and apply a
reference implementation of the boundary rule to the artefact a consumer
actually gets.

**One claim this module corrected in its own phase's prose.** The first draft of
the shipped rule said the seeded templates are "written in the entry grammar",
and running this fixture showed they are not: the headings read `## ISSUE-NNNN`
with `NNNN` a literal placeholder, so a digit-anchored id read already excludes
them and only a bare-prefix read reaches them. The rule now states both defences
for what each actually does — digits exclude the templates, and the fence rule is
what catches a *real* entry (upstream #264, a wrap-induced fence). Had the guard
only matched sentences, the overstatement would have shipped.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "install.sh"
SKILLS = REPO_ROOT / "core" / "skills"

READERS = ("report-issues", "share-wins")

# The shipped rule: an entry id is the kind plus DIGITS. The seed's template
# headings carry the literal placeholder `NNNN`, so this pattern excludes them —
# which is the first of the rule's three defences.
ENTRY_HEADING = re.compile(r"^## (ISSUE|GOOD)-(\d+)\b")
# The pre-fix reading the retired instruction also permitted: the bare prefix.
PREFIX_HEADING = re.compile(r"^## (ISSUE|GOOD)-")
# CommonMark: a fence opener may carry up to THREE spaces of indentation; four makes
# it an indented code block instead. `^\\s*` is wrong in the permissive direction and
# column-0-only is wrong in the direction that actually bit — upstream #264 put
# ```plan at column 3 inside a wrapped list item.
FENCE = re.compile(r"^ {0,3}```")


# ── the reference boundary parser (what the shipped rule says, in code) ──────


def split_entries(text, fence_aware=True):
    """Return [(id, body_lines)] under the shipped boundary rule.

    An entry begins at a column-0 `## ` heading whose text starts with an entry
    id, and ends at the line before the next such heading, the next column-0
    `## ` heading of any kind, or EOF. With ``fence_aware=False`` this is the
    pre-fix reading, kept so the defect can be reproduced rather than asserted.
    """
    entries, cur, in_fence = [], None, False
    for line in text.splitlines():
        if fence_aware and FENCE.match(line):
            in_fence = not in_fence
            if cur:
                cur[1].append(line)
            continue
        if not in_fence and line.startswith("## "):
            m = ENTRY_HEADING.match(line)
            if cur:
                entries.append(cur)
                cur = None
            if m:
                cur = (f"{m.group(1)}-{m.group(2)}", [])
            continue
        if cur:
            cur[1].append(line)
    if cur:
        entries.append(cur)
    return entries


def unterminated_fence(text):
    return sum(1 for ln in text.splitlines() if FENCE.match(ln)) % 2 == 1


# ── the real seeded artefact, expanded by bash ──────────────────────────────


def _seed_heredoc_script():
    """Extract `seed_friction_log`'s `cat > … <<EOF … EOF` block verbatim.

    Taken from the installer rather than restated here — a fixture built from
    the author's model of the seed proves only that the author is
    self-consistent (`_shared/adversarial-review.md` § *Before you spawn anyone*
    rule 3).
    """
    lines = INSTALL_SH.read_text(encoding="utf-8").splitlines()
    fn = next(i for i, ln in enumerate(lines) if ln.startswith("seed_friction_log()"))
    start = next(i for i in range(fn, len(lines)) if lines[i].strip().endswith("<<EOF"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].rstrip() == "EOF")
    return lines[start:end + 1]


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    dst = tmp_path_factory.mktemp("seed") / "SYSOP_ISSUES.md"
    block = _seed_heredoc_script()
    script = "\n".join(['consumer="demo-consumer"', f'dst="{dst}"', *block])
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    text = dst.read_text(encoding="utf-8")
    assert text.strip(), "the extracted seed heredoc produced an empty file"
    return text


def test_the_seed_ships_two_fenced_template_headings_and_no_entry(seeded):
    """The rule's stated justification, checked against the artefact it describes.

    Both skills assert three things about the seed: the template headings sit
    inside fences, they are *above* every real entry, and their number is the
    literal placeholder `NNNN` rather than digits. All three are what make the
    two defences independent, and all three are checked here rather than trusted —
    a claim about a shipped artefact is exactly the kind Phase 192's round spent
    its second lens falsifying.
    """
    fenced_prefix, fenced_digits, in_fence = [], [], False
    for ln in seeded.splitlines():
        if FENCE.match(ln):
            in_fence = not in_fence
            continue
        if in_fence and PREFIX_HEADING.match(ln):
            fenced_prefix.append(ln)
            if ENTRY_HEADING.match(ln):
                fenced_digits.append(ln)
    assert len(fenced_prefix) == 2, fenced_prefix
    assert {PREFIX_HEADING.match(ln).group(1) for ln in fenced_prefix} == {
        "ISSUE", "GOOD"}, fenced_prefix
    # The digit rule alone already excludes them: `NNNN` is not a number.
    assert fenced_digits == [], fenced_digits
    assert not unterminated_fence(seeded), "the seed itself has an unbalanced fence"


def test_a_prefix_reader_finds_the_template_where_a_digit_reader_does_not(seeded):
    """The two readings the retired instruction permitted, on the shipped bytes.

    A fresh install has filed nothing, so the honest answer is zero entries. The
    bare-prefix reading finds the template instead — and the template's `Status:`
    line is the whole menu (`Open / Prompt-ready / …`), which routes to the
    skill's "unclear status — treat as eligible? (y/n)" prompt rather than to a
    skip. That an instruction admitted both answers is the ambiguity the rule
    replaces; which of the two an agent picked was never stated.
    """
    prefix_hits = [ln for ln in seeded.splitlines() if PREFIX_HEADING.match(ln)]
    digit_hits = [ln for ln in seeded.splitlines() if ENTRY_HEADING.match(ln)]
    assert len(prefix_hits) == 2, prefix_hits
    assert digit_hits == [], digit_hits


def test_the_boundary_rule_finds_no_entries_in_a_freshly_seeded_file(seeded):
    """…and the shipped rule gives the right answer on the same bytes."""
    assert split_entries(seeded) == []


def test_a_fence_blind_parse_mis_splits_an_entry_that_quotes_a_heading(seeded):
    """#264's class, and the reason the fence rule is not redundant with the digits.

    A filed entry routinely quotes the log's own shapes in a repro snippet, and a
    quoted heading carries **digits** — so the digit rule cannot help here, and
    fence-blind the quoted line ends the entry early and adopts its tail. This is
    the only defence that reaches a real entry rather than a template.
    """
    log = seeded + (
        "\n## ISSUE-0050 — quoting a heading in a repro (2026-08-06)\n\n"
        "**Status:** Open\n\n### What happened\nThe log looked like:\n\n"
        "```markdown\n## ISSUE-0099 — not a real entry (2026-08-06)\n```\n\n"
        "BUG_TAIL_MARKER\n"
    )
    blind = split_entries(log, fence_aware=False)
    aware = split_entries(log, fence_aware=True)
    assert [e[0] for e in blind] == ["ISSUE-0050", "ISSUE-0099"], blind
    assert [e[0] for e in aware] == ["ISSUE-0050"], aware
    assert "BUG_TAIL_MARKER" in "\n".join(aware[0][1])
    assert "BUG_TAIL_MARKER" not in "\n".join(blind[0][1])


def test_a_win_after_a_bug_is_its_own_entry_not_the_bug_s_body(seeded):
    """#360 and #364, reproduced end to end and fixed.

    The bug body must not contain a single line of the win, in either direction —
    that containment is what "published under consent given for a bug" means.
    """
    log = seeded + (
        "\n## ISSUE-0042 — close_batch refused the lock (2026-08-05)\n\n"
        "**Status:** Open\n\n### What happened\nBUG_BODY_MARKER\n\n"
        "**Environment**\nsysop @ abc123\n\n"
        "## GOOD-0026 — close_batch said exactly why (2026-08-05)  [good]\n\n"
        "**Status:** Good — keep\n\n### What worked\nWIN_BODY_MARKER\n"
    )
    got = split_entries(log)
    assert [e[0] for e in got] == ["ISSUE-0042", "GOOD-0026"], got
    bug_body = "\n".join(got[0][1])
    win_body = "\n".join(got[1][1])
    assert "BUG_BODY_MARKER" in bug_body
    assert "WIN_BODY_MARKER" not in bug_body, "the win was absorbed into the bug"
    assert "WIN_BODY_MARKER" in win_body
    assert "BUG_BODY_MARKER" not in win_body
    # The bug keeps its own trailing block — the swallow used to wedge the win
    # between the bug's prose and this.
    assert "**Environment**" in bug_body


def test_a_three_space_indented_fence_is_a_fence(seeded):
    """#264's exact mechanism, read from the upstream issue rather than the filing.

    A wrapped list item put ```` ```plan ```` at column 3. CommonMark reads that as a
    fence opener with an info string, so 119 lines became one block and absorbed the
    rest of one entry, the whole of the next and the head of a third. A rule that
    only recognises column-0 fences gives the wrong answer here, and a rule keyed to
    `^\\s*` would swallow a genuine four-space indented code block instead.
    """
    log = seeded + (
        "\n## ISSUE-0024 — a wrapped list item (2026-08-06)\n\n**Status:** Open\n\n"
        "### Proposed fix\n\n"
        "1. **Step 6a** — in addition to emitting the fenced\n"
        "   ```plan block, instruct the agent to `Write` its plan to\n"
        "   somewhere durable.\n\n"
        "## ISSUE-0023 — swallowed whole (2026-08-05)\n\n**Status:** Open\n\nSWALLOWED\n"
    )
    assert unterminated_fence(log), "the column-3 opener must count as a fence"
    got = split_entries(log)
    assert [e[0] for e in got] == ["ISSUE-0024"], got
    assert "SWALLOWED" in "\n".join(got[0][1]), "the later entry was absorbed"
    # Four spaces is an indented code block, not a fence — the rule must not
    # over-reach in that direction or an ordinary snippet disables structure.
    four = seeded + (
        "\n## ISSUE-0025 — a four-space snippet (2026-08-06)\n\n**Status:** Open\n\n"
        "    ```\n    not a fence opener\n\n"
        "## ISSUE-0026 — still its own entry (2026-08-06)\n\n**Status:** Open\n\nKEPT\n"
    )
    assert not unterminated_fence(four)
    ids = [e[0] for e in split_entries(four)]
    assert ids == ["ISSUE-0025", "ISSUE-0026"], ids


@pytest.mark.parametrize("skill", READERS)
def test_the_fence_bullet_states_the_three_space_allowance_and_its_instance(skill):
    """The clause without which the fence rule does not catch #264 — on its own bullet.

    Asserted per-bullet, not per-block: the block carries `#264` twice (the fence
    rule and the parity signal), so a block-scoped check passes when either one is
    deleted. That is how D09 survived the first run of this phase's battery.
    """
    bullet = _one_bullet(skill, "fenced block")
    assert "indented up to three spaces" in bullet, bullet
    assert "#264" in bullet, bullet
    assert "column 3" in bullet, bullet


@pytest.mark.parametrize("skill", READERS)
def test_the_unterminated_bullet_keeps_a_checkable_signal(skill):
    """"Report it" needs a mechanism, or it is an instruction with no method.

    The parity count is the cheap one and it is what #264 actually exhibited
    (36 balanced → 39 unbalanced), so the remedy names it rather than leaving the
    reader to invent a parser.
    """
    bullet = _one_bullet(skill, "unterminated fence")
    assert "fence-opener-eligible" in bullet, bullet
    assert "odd number" in bullet.lower(), bullet


@pytest.mark.parametrize("skill", READERS)
def test_the_three_bullets_are_the_three_declared_defences(skill):
    """Non-vacuity for the per-bullet helper, and a count the prose states.

    The paragraph says "Three rules keep that honest"; if a bullet is dropped, that
    sentence becomes false and every per-bullet assertion above silently stops
    covering something.
    """
    heads = list(_boundary_bullets(skill))
    assert len(heads) == 3, heads
    assert "Three rules keep that honest" in _block(skill, "**Entry boundaries")
    assert any("digits" in h for h in heads), heads
    assert any("fenced block" in h for h in heads), heads
    assert any("unterminated fence" in h for h in heads), heads


def test_an_unterminated_fence_is_detectable_rather_than_silent(seeded):
    """Phase 181's round: a fence fix that honours an unterminated fence is
    *worse* than the bug it replaced, because structure dies to EOF silently.

    The rule requires reporting it; this asserts the condition is decidable from
    the file alone, which is what makes "say so and stop" implementable.
    """
    broken = seeded + (
        "\n## ISSUE-0043 — a wrapped fence (2026-08-06)\n\n"
        "**Status:** Open\n\n```\nunclosed\n"
        "\n## GOOD-0027 — swallowed (2026-08-06)  [good]\n\n**Status:** Good — keep\n"
    )
    assert unterminated_fence(broken)
    # And the swallow it causes is real, which is why detection is the remedy.
    got = split_entries(broken)
    assert [e[0] for e in got] == ["ISSUE-0043"], got


# ── the prose contract, scoped to the block that carries it ─────────────────


def _block(skill, anchor):
    """The anchored paragraph plus its bullet list, and **nothing after it**.

    Two earlier versions were wrong in the same direction. The first ended at the
    next line starting `## ` **or** `**`, with the operator-precedence bug that
    implies. The second widened until any line that was not a bullet, blank or
    indented — which for `share-wins` ran 37 lines, past the rule into the Classify
    paragraph *and* the Status table. Lens 3 used that slack twice: once to launder
    a needle in from an unrelated line while deleting it from the rule (survivor),
    and once to make an ordinary added bullet count as a boundary bullet (false
    kill). A slice that is wrong by seven lines is wrong in both directions.

    So: the paragraph runs to the first blank line, then the bullet list runs while
    lines are bullets or their indented continuations, and the block stops at the
    first line that is neither.
    """
    lines = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8").splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.startswith(anchor)]
    assert len(starts) == 1, f"{skill}: {anchor!r} appears {len(starts)} times"
    i = starts[0]

    # The anchored paragraph: up to (not including) the blank line that ends it.
    while i < len(lines) and lines[i].strip():
        i += 1
    para_end = i
    # Then, optionally, one bullet list — contiguous, stopping at the first blank.
    # A blank-tolerant version let an arbitrarily distant bullet rejoin the list:
    # lens 3's C11 added an ordinary bullet six lines below the rule, twenty lines
    # away, and the bullet count went to four. The bullets in these files are
    # contiguous (continuations are indented, never blank-separated), so the blank
    # line is the terminator and nothing past it belongs to the rule.
    j = i + 1 if i < len(lines) else i
    while j < len(lines) and (lines[j].startswith("- ") or lines[j].startswith("  ")):
        j += 1
    block = lines[starts[0]:max(para_end, j)]
    assert block, f"{skill}: empty block at {anchor!r}"
    return "\n".join(block)


def _boundary_bullets(skill):
    """The Entry-boundaries block's bullets, keyed by their bold head.

    Per-bullet is the granularity the rules live at: "which bullet a phrase sits
    in" is precisely what a file- or block-scoped check cannot see.
    """
    block = _block(skill, "**Entry boundaries").splitlines()
    bullets, cur = {}, None
    for ln in block:
        if ln.startswith("- "):
            head = ln[2:].split("**")[1] if "**" in ln else ln[2:]
            cur = head
            bullets[cur] = ln
        elif cur is not None and (ln.startswith("  ") or ln.strip() == ""):
            bullets[cur] += "\n" + ln
        elif cur is not None:
            cur = None
    assert len(bullets) == 3, f"{skill}: expected 3 boundary bullets, got {list(bullets)}"
    return bullets


def _one_bullet(skill, needle):
    hits = [text for head, text in _boundary_bullets(skill).items() if needle in head]
    assert len(hits) == 1, f"{skill}: bullets whose head carries {needle!r}: {len(hits)}"
    return hits[0]


@pytest.mark.parametrize("skill", READERS)
def test_both_readers_state_the_boundary_rule_over_both_id_kinds(skill):
    """A boundary rule naming one id kind is the defect, restated."""
    block = _block(skill, "**Entry boundaries")
    flat = " ".join(block.split())
    # **The rule sentence, not the paragraph it sits in.** Lens 3 deleted the
    # end-of-file arm from the rule and added "An entry that is last in the file
    # simply runs on until end-of-file." two sentences later; a paragraph-scoped
    # `"end-of-file" in block` was satisfied by the addition. So the sentence is
    # sliced out and all three arms are required inside it.
    m = re.search(r"An entry begins at a\b(.*?)(?:\. |$)", flat)
    assert m, flat[:300]
    sentence = m.group(0)
    # Split at the sentence's own hinge: the start clause and the end clause make
    # different claims and each must carry its own. Lens 3's C01 widened the START
    # clause to "`## ` heading at any indentation" — a heading indented inside a
    # list item then begins an entry — and the `column-0` needle was still satisfied
    # by the END clause three arms later. Whole-sentence scoping was not enough;
    # this is the same laundering as C26b, one level down.
    assert " and ends at " in sentence, sentence
    begins, ends = sentence.split(" and ends at ", 1)
    assert "`ISSUE-NNNN` **or** `GOOD-NNNN`" in begins, begins
    assert "column-0 `## ` heading" in begins, (
        f"{skill}: the START clause no longer requires column 0: {begins}")
    assert "at any indentation" not in begins, begins
    for arm in ("the next such heading",
                "the next column-0 `## ` heading of any kind",
                "end-of-file"):
        assert arm in ends, f"{skill}: the end clause lost its {arm!r} arm: {ends}"


@pytest.mark.parametrize("skill", READERS)
def test_both_readers_anchor_the_id_on_digits(skill):
    """The defence that excludes the seeded templates without needing the fence rule.

    Two independent defences is the design; a guard that only pinned the fence
    rule would let this one be dropped as redundant, and it is not — it is what
    makes the template safe even in a file whose fences a consumer removed.
    """
    block = _block(skill, "**Entry boundaries")
    assert "The number is digits" in block, block
    assert "literal\n  placeholder" in block or "literal placeholder" in block, block


@pytest.mark.parametrize("skill", READERS)
def test_both_readers_are_fence_aware_and_refuse_to_assume_a_fence_closes(skill):
    """Forbid the licence, don't require the phrase.

    "Assume it closes at EOF" is the one-sentence edit that reintroduces the
    worse-than-the-bug behaviour, and it leaves every other assertion here green.
    """
    block = _block(skill, "**Entry boundaries").lower()
    assert "inside a fenced block is neither a boundary nor an entry" in block
    assert "unterminated fence is reported, never assumed shut" in block
    for licence in ("assume it closes", "treat it as closed", "close it at eof",
                    "ignore the fence"):
        assert licence not in block, f"{skill}: fence rule licenses {licence!r}"


def test_report_issues_excludes_wins_but_keeps_them_as_boundaries():
    """The half that actually fixes the swallow.

    An exclusion clause that only says "ignore them" leaves the boundary bug
    exactly where it was — the body still gets absorbed, it just is not called a
    win while it happens.
    """
    block = _block("report-issues", "**Wins are out of scope here")
    assert "still boundaries" in block, block
    assert "ends the entry above it" in block, block
    assert "/share-wins" in block, block
    assert "GOOD-0026" in block and "GOOD-0027" in block, block


def test_share_wins_keeps_the_reciprocal_clause():
    """The exclusion is now two-directional; it was one-directional, and that
    asymmetry is what the filing identified as the defect."""
    text = (SKILLS / "share-wins" / "SKILL.md").read_text(encoding="utf-8")
    assert "Friction (`ISSUE-NNNN`) entries are out of scope here" in text
    assert "**They are still boundaries**" in text


def test_the_seed_routes_wins_to_the_skill_that_transports_them():
    """The shipped seed used to name `/report-issues` for `[good]` entries.

    That is the instruction the consumer reads *inside the file itself*, so it
    was not merely stale — it told an agent to do the thing this phase forbids.
    Same shape as #367 one phase earlier: the documented value was an input.
    """
    lines = _seed_heredoc_script()
    start = next(i for i, ln in enumerate(lines) if "Positive signal counts too" in ln)
    end = next(i for i in range(start + 1, len(lines)) if lines[i].rstrip() == ">")
    positive = "\n".join(lines[start:end])
    assert "/share-wins" in positive, positive
    assert "/report-issues" in positive, "the seed must say which skill does NOT"
    assert re.search(r"\*\*not\*\*.{0,60}report-issues", positive, re.S), positive


def test_the_population_of_readers_is_derived_and_complete():
    """Every skill that classifies friction-log entries carries the rule.

    Derived from the tree, not from this module's constant: a third reader that
    ships without the boundary rule fails here rather than inheriting the bug.
    """
    classifiers = sorted(
        p.parent.name for p in SKILLS.glob("*/SKILL.md")
        if "SYSOP_ISSUES.md" in (t := p.read_text(encoding="utf-8"))
        and re.search(r"Classify (?:each|every|all)", t)
    )
    assert classifiers == sorted(READERS), classifiers
    for skill in classifiers:
        assert "**Entry boundaries" in (SKILLS / skill / "SKILL.md").read_text(
            encoding="utf-8"
        ), skill


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))


def test_report_issues_states_the_loop_mode_gap_it_routes_into():
    """Found by this phase's round: loop mode ships this reader and not `/share-wins`.

    `install.sh` puts `report-issues` in the loop skill set and `share-wins` in the
    excluded set, and does not seed the friction log in loop mode at all — so the
    wins clause pointed a loop consumer at a command they do not have. The rule does
    not change (still never file a win as a bug); what was missing is saying that
    the alternative is absent, so the entry is not left looking handled.

    Phase 192's round found the same class in its own new prose ("/sitrep and
    self_check.sh will both report this") — loop mode is the funnel default, so a
    sentence true only of a full install is false where most readers are.
    """
    text = (SKILLS / "report-issues" / "SKILL.md").read_text(encoding="utf-8")
    i = text.index("**Wins are out of scope here")
    clause = text[i:i + 2600]
    # Whitespace-normalised, because this is wrapped markdown: asserting a phrase
    # that happens to sit on one line today is a guard that reflow breaks. The same
    # brittleness took a mutation anchor stale mid-round and made this phase's own
    # "no stale anchors" claim false between the run and the write-up.
    flat = " ".join(clause.split())
    assert "/share-wins is not installed in loop mode" in flat, flat[:400]
    # The **antecedent**, not just the report line. Found by this phase's battery:
    # neutering the paragraph's binding sentence while leaving the example report
    # line intact kept every earlier assertion green, so the rule could lose its
    # reason and keep its illustration.
    assert "Loop mode installs this skill and **not** `/share-wins`" in flat, flat[:600]
    assert "does not seed the friction log at all" in flat, flat[:600]
    # …and it must not turn into a licence to file the win as a bug instead.
    lowered = flat.lower()
    for licence in ("file it as a bug instead", "treat it as friction",
                    "route it through this skill"):
        assert licence not in lowered, licence

    installer = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    assert "share-wins" in installer, "sanity: the installer still knows the skill"


def test_the_loop_mode_membership_the_caveat_rests_on_is_real():
    """Derived from the installer, not asserted — the caveat is only true while this is.

    If a future release ships `/share-wins` in loop mode, the caveat becomes a false
    claim in shipped prose and this is what says so.
    """
    loop_test = (REPO_ROOT / "tests" / "test_install_loop_mode.py").read_text(
        encoding="utf-8")
    i = loop_test.index("LOOP_SKILLS")
    window = loop_test[i:i + 900]
    assert '"report-issues"' in window, window[:400]
    j = loop_test.index("EXCLUDED_SKILLS")
    assert '"share-wins"' in loop_test[j:j + 900], loop_test[j:j + 400]


# ── closures for lens 3's boundary survivors ─────────────────────────────────


@pytest.mark.parametrize("skill", READERS)
def test_no_clause_contradicts_the_rule_it_sits_beside(skill):
    """Lens 3 added contradicting sentences that left every needle intact.

    C02 put "In this skill only an `ISSUE-NNNN` heading starts an entry; a
    `GOOD-NNNN` heading is body text" *inside* the boundary rule — the #360 defect
    restored as an explicit instruction. C05 kept "indented up to three spaces" and
    added "though in practice counting column-0 openers alone is sufficient" — the
    reading the record says would have missed the one instance the rule exists for.
    Neither is reachable by requiring a phrase; both are reachable by forbidding the
    contradiction.
    """
    flat = " ".join(_block(skill, "**Entry boundaries").split()).lower()
    for contradiction in (
        "only an `issue-nnnn` heading starts",
        "is body text",
        "column-0 openers alone is sufficient",
        "column-0 openers alone are sufficient",
        "in practice counting column-0",
        "read past it as if the fence were absent",
        "as if the fence were absent",
    ):
        assert contradiction not in flat, (
            f"{skill}: a clause contradicting the boundary rule ({contradiction!r})")


@pytest.mark.parametrize("skill", READERS)
def test_the_parity_bullet_keeps_the_counts_that_make_it_checkable(skill):
    """"An odd number" without #264's figures is a claim with no worked case.

    Lens 3 kept both needles and dropped "36 … to 39", which is the only thing
    telling a reader the signal was ever observed rather than reasoned about.
    """
    bullet = " ".join(_one_bullet(skill, "unterminated fence").split())
    assert "36" in bullet and "39" in bullet, bullet
    assert "#264" in bullet, bullet


@pytest.mark.parametrize("skill", READERS)
def test_the_fence_bullet_keeps_the_claim_that_makes_it_a_second_defence(skill):
    """"*above* every real entry" is what makes the templates unreachable.

    Without it the bullet asserts only that the templates are fenced, and the
    independence of the two defences — the record's own argument — stops holding.
    """
    bullet = " ".join(_one_bullet(skill, "fenced block").split())
    assert "above* every real entry" in bullet, bullet
    assert "Entries below. Newest first." in bullet, bullet


def test_the_seed_keeps_the_marker_the_fence_bullet_cites(seeded):
    """C21 dropped the `<!-- Entries below --> ` marker the rule points at.

    The rule says entries live below that marker "where it survives" — a claim
    about the shipped artefact, so it is checked against the artefact.
    """
    assert "<!-- Entries below. Newest first. -->" in seeded, seeded[-400:]


def test_the_seed_does_not_re_permit_the_bug_transport_for_wins(seeded):
    """C07 restored the root cause while the `**not** … report-issues` regex matched.

    The seed's routing sentence is the one instruction a consumer reads *inside the
    file*, and the earlier check only required `**not**` within 60 characters of
    `report-issues` — which "**not** as a bug, though `/report-issues` will batch
    them" satisfies. So the permission is forbidden directly.
    """
    flat = " ".join(seeded.split())
    i = flat.index("Positive signal counts too")
    para = flat[i:i + 700]
    assert "/share-wins" in para, para
    for permission in ("report-issues` will batch", "report-issues` can batch",
                       "rather not run two skills", "report-issues` also"):
        assert permission not in para, f"the seed re-permits the bug transport: {permission!r}"
    # …and the one mention of the bug transport must be inside a negation.
    for m in re.finditer(r"report-issues", para):
        preceding = para[max(0, m.start() - 40):m.start()].lower()
        assert "not" in preceding, (
            f"an un-negated /report-issues in the seed's wins paragraph: "
            f"{para[max(0, m.start() - 80):m.start() + 60]!r}")


def test_the_wins_exclusion_is_an_instruction_not_a_preference():
    """C06/C08/C23 softened "never file it" and "still boundaries" to judgment calls.

    The clause's whole value is that it removes a judgment: a win is never filed as
    a bug, and its heading always ends the entry above. Softening words are what
    turn a rule back into advice, so they are forbidden on the clause.
    """
    text = (SKILLS / "report-issues" / "SKILL.md").read_text(encoding="utf-8")
    i = text.index("**Wins are out of scope here")
    flat = " ".join(text[i:i + 1400].split())
    assert "never file it" in flat, flat[:300]
    assert "ends the entry above it" in flat, flat[:300]
    assert "But its heading **ends the entry above it**" in flat, flat[:400]
    for softener in ("usually", "generally", "prefer not to", "in most cases",
                     "as a rule of thumb", "you may still", "if it seems",
                     "is a judgment call", "judgment call", "keep them together",
                     "need not end", "not itself content to file"):
        assert softener not in flat.lower(), f"the wins clause was softened ({softener!r})"

    wins = (SKILLS / "share-wins" / "SKILL.md").read_text(encoding="utf-8")
    j = wins.index("Friction (`ISSUE-NNNN`) entries are out of scope here")
    wflat = " ".join(wins[j:j + 900].split())
    assert "**They are still boundaries**" in wflat, wflat[:300]
    assert "heading ends the win above it" in wflat, wflat[:400]
    for softener in ("usually", "generally", "advisory", "in most cases", "you may",
                     "in principle", "need not end", "clearly belong together"):
        assert softener not in wflat.lower(), (
            f"share-wins' reciprocal clause was softened ({softener!r})")
