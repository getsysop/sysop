"""`/auto-fix` and `/auto-judge` accept a batch selector, and it can only narrow (#365).

Before this, both siblings took a concurrency integer and nothing else, so the
batch set was always whatever Step 1's index pass selected. Three costs, all
reported from a 38-batch queue: no cohorts, no resume-from after a rate-limit
death mid-`--merge`, and an all-or-nothing 38-batch Opus commitment.
`/auto-build` has had explicit selection since Phase 97 (`SUBSET_IDS`); the
siblings had none.

**Why the grammar is a flag and not a positional, which is the part a later
simplification will want to undo.** `/auto-build`'s positional grammar works
because its token classes are structurally disjoint — a bare integer is the
count, `^[A-Z]`-shaped tokens are task IDs. Both siblings already spend the bare
integer on the concurrency cap, so `/auto-fix 563` cannot be read as a batch
number without making the same token mean two things. The tests below pin the
rationale on the line that carries the flag, because a rationale that lives only
in a phase log is not available to the person editing the skill.

Guard shape follows Phase 192's round, which inverted a shipped contract in
every direction it tried with every asserted phrase still present: assertions
are scoped to the block carrying the rule, the never-override rule is checked by
**forbidding a licence** rather than requiring a phrase, and placement is
asserted by line index — a narrowing rule stated after the lane split narrows
nothing.

The honest limit: these steps are instructions to an agent, so no test here
proves an agent obeys the selector. What is checked is that the rule is stated,
stated where it is read, and not quietly licensed away.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = REPO_ROOT / "core" / "skills"

# Derived, not asserted: the selector's population is the two skills whose
# Step 0 takes a concurrency integer and whose Step 1 selects a batch pool.
# `/auto-build` is deliberately excluded — it has its own positional grammar.
SIBLINGS = ("auto-fix", "auto-judge")

FLAG = "--batches"
# A prefix, not an exact title: retitling the section (lens 3's B11) broke
# nine assertions at once while the content was untouched.
SECTION_1D_PREFIX = "### 1d."
SECTION_1C = "### 1c. Tracker size is advisory, never a stop"
STEP_1 = "## Step 1: Read Queue"


def _lines(skill):
    return (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8").splitlines()


def _only(lines, pred, what, skill):
    hits = [i for i, ln in enumerate(lines) if pred(ln)]
    assert len(hits) == 1, f"{skill}: expected exactly one {what}, got {hits}"
    return hits[0]


def _block_1d(skill):
    """The 1d section's own lines — from its heading to the next heading."""
    lines = _lines(skill)
    start = _only(lines, lambda ln: ln.strip().startswith(SECTION_1D_PREFIX), "1d heading", skill)
    end = next(
        (i for i in range(start + 1, len(lines))
         if lines[i].startswith("## ") or lines[i].startswith("### ")),
        len(lines),
    )
    assert end > start + 3, f"{skill}: 1d section is empty"
    return lines[start:end]


@pytest.mark.parametrize("skill", SIBLINGS)
def test_the_flag_is_declared_where_arguments_are_parsed_and_in_the_hint(skill):
    """A flag documented in one place only is half-shipped.

    `argument-hint` is what the harness shows at the prompt; Step 0 is what the
    agent parses. Either alone leaves an operator who cannot discover the
    capability, or an agent that does not implement the one advertised.
    """
    lines = _lines(skill)
    hint = _only(lines, lambda ln: ln.startswith("argument-hint:"), "argument-hint",
                 skill)
    assert FLAG in lines[hint], lines[hint]

    step0 = _only(lines, lambda ln: ln.strip() == "## Step 0: Parse Arguments",
                  "Step 0 heading", skill)
    nxt = next(i for i in range(step0 + 1, len(lines)) if lines[i].startswith("## "))
    bullet = [i for i in range(step0, nxt)
              if lines[i].strip().startswith(f"- **`{FLAG}")]
    assert len(bullet) == 1, f"{skill}: {FLAG} bullet in Step 0: {bullet}"

    # The bullet's head must be the SAME spelling the hint advertises, and must
    # declare the flag live. Found by this phase's own battery: rewriting the head
    # to ``- **`--batches` (reserved)**`` left every other assertion here green,
    # so Step 0 could advertise an unimplemented flag while Step 1d went on
    # describing how it narrows.
    head = lines[bullet[0]].strip()
    assert head.startswith(f"- **`{FLAG} <selector>`** →"), head
    for licence in ("reserved", "not yet", "planned", "unimplemented", "future"):
        assert licence not in head.lower(), (
            f"{skill}: the {FLAG} bullet declares the flag as {licence!r}: {head}"
        )


@pytest.mark.parametrize("skill", SIBLINGS)
def test_the_flag_states_why_it_is_not_a_positional(skill):
    """The rationale lives on the flag, not in a phase log nobody re-reads.

    Without it the obvious "simplification" is to accept a bare number for
    symmetry with `/auto-build` — which collides head-on with the concurrency
    cap this skill has taken positionally since it shipped.
    """
    lines = _lines(skill)
    bullet = lines[_only(lines, lambda ln: ln.strip().startswith(f"- **`{FLAG}"),
                         f"{FLAG} bullet", skill)]
    assert "concurrency cap" in bullet, bullet
    assert re.search(r"flag rather than a bare argument", bullet), bullet


@pytest.mark.parametrize("skill", SIBLINGS)
def test_the_narrowing_is_stated_before_the_lane_split_that_consumes_it(skill):
    """1d must sit inside Step 1, after 1c, and above Step 4b.

    A narrowing rule stated after the lane split narrows nothing — the same
    relocation defeat Phase 192's round ran on a routing rule moved 350 lines
    off the step that routes on it. This also pins that 1c stays the last thing
    a size-ceiling reader meets before the new section, which
    `test_flag_contract.py` independently requires.
    """
    lines = _lines(skill)
    step1 = _only(lines, lambda ln: ln.strip() == STEP_1, "Step 1 heading", skill)
    c = _only(lines, lambda ln: ln.strip() == SECTION_1C, "1c heading", skill)
    d = _only(lines, lambda ln: ln.strip().startswith(SECTION_1D_PREFIX), "1d heading", skill)
    lane = _only(lines, lambda ln: ln.startswith("### 4b."), "Step 4b heading", skill)
    assert step1 < c < d < lane, (step1, c, d, lane)


@pytest.mark.parametrize("skill", SIBLINGS)
def test_the_selector_narrows_and_is_licensed_to_do_nothing_else(skill):
    """Intersection, plus a forbidden-licence check rather than a phrase check.

    `/auto-build`'s equivalent invariant is stated at `auto-build:59` — "never a
    bypass". The failure this guards is not the word going missing; it is a
    sentence beside it that gives the selector authority to include a batch the
    pool rejected.
    """
    block = _block_1d(skill)
    text = "\n".join(block)
    assert "by intersection" in text, text
    assert re.search(r"never (grow|override)", text), text
    lowered = text.lower()
    for licence in ("overrides the", "even if the status", "regardless of status",
                    "bypass the pool", "force the batch", "include it anyway"):
        assert licence not in lowered, f"{skill}: 1d licenses an override ({licence!r})"


@pytest.mark.parametrize("skill", SIBLINGS)
def test_a_narrowed_run_reports_what_it_left_out(skill):
    """Selected-only reporting is how a 6-batch run reads as a 38-batch one.

    Two distinct populations must be printed: pool batches the selector dropped,
    and requested numbers that never reached the pool (with a reason each) —
    `/auto-build`'s `EXCLUDED <id> <reason>` discipline, which exists because a
    silently dropped request is indistinguishable from one that ran.
    """
    block = _block_1d(skill)
    text = "\n".join(block)
    # Backtick-tolerant: the label is output-template prose, and quoting the
    # flag in it is an ordinary edit (lens 3's B20 false kill).
    flat = text.replace("`", "")
    assert "Excluded by --batches:" in flat, text
    assert "Requested but not in the pool:" in flat, text
    assert re.search(r"never silently dropped", text), text


@pytest.mark.parametrize("skill", SIBLINGS)
def test_an_empty_selection_does_not_read_as_an_empty_queue(skill):
    """The two states have opposite remedies and the same default message.

    "No batches to process" tells an operator the queue is clear; if the real
    cause is a selector that matched nothing, the work is sitting right there.
    """
    block = _block_1d(skill)
    text = "\n".join(block)
    assert re.search(r"intersection is empty", text), text
    assert re.search(r"do \*\*not\*\* fall through", text), text


def test_both_siblings_state_the_two_rules_in_the_same_words():
    """The rules are shared; only the pool-specific reasons may differ.

    These two skills already carry byte-identical lane-split and index-pass
    blocks pinned by `test_overlap_contract.py` and `test_flag_contract.py`,
    for the reason this asserts: a rule that drifts between them becomes two
    rules, and the weaker one wins wherever it is read.
    """
    shared = [
        "**The selector narrows; it never overrides.**",
        "**Report what was excluded, not only what was selected.**",
    ]
    blocks = {s: "\n".join(_block_1d(s)) for s in SIBLINGS}
    for sentence in shared:
        for skill, text in blocks.items():
            assert sentence in text, f"{skill} is missing: {sentence!r}"
    # …and the paragraph carrying each is identical, not merely present.
    for sentence in shared:
        paras = {
            skill: next(ln for ln in text.splitlines() if sentence in ln)
            for skill, text in blocks.items()
        }
        assert len(set(paras.values())) == 1, paras


def test_the_population_is_the_two_skills_that_lacked_a_selector():
    """Non-vacuity, derived from the tree rather than from this file's constant.

    Every skill whose Step 0 parses a concurrency cap must carry the selector;
    if a third such skill ever ships, this fails rather than silently covering
    two of three.
    """
    with_cap = sorted(
        p.parent.name for p in SKILLS.glob("*/SKILL.md")
        if re.search(r"\u2192 (?:the )?concurrency cap", p.read_text(encoding="utf-8"))
    )
    assert with_cap == sorted(SIBLINGS), with_cap


def test_the_resume_path_names_the_command_that_actually_works():
    """Found by this phase's round, by running the command the prose prescribes.

    `batch_work.sh --release <N>` **exits 1** when the batch carries any `- [x]`
    task, and a `--merge` run killed part-way through is exactly what produces one.
    The script states the ownership boundary itself — "/review-close owns a batch
    that has results; --release owns one that does not" — so a recovery paragraph
    naming only `--release` dead-ends on the dominant case.
    """
    text = (SKILLS / "auto-judge" / "SKILL.md").read_text(encoding="utf-8")
    para = next(ln for ln in text.splitlines() if "Resuming a killed run" in ln)
    assert "--release <N>" in para, para
    assert "exits 1" in para, para
    assert "- [x]" in para, para
    assert "/review-close" in para, para
    assert "--release --force <N>" in para, para


def test_the_release_refusal_the_prose_describes_is_the_one_in_the_script():
    """…and the script still refuses for the reason quoted, so the advice stays true.

    Asserted against `batch_work.sh` rather than restated, because the whole defect
    was a paragraph describing a command's behaviour from the author's model of it.
    """
    script = (REPO_ROOT / "core" / "companion" / "scripts" / "batch_work.sh").read_text(
        encoding="utf-8")
    assert "completed task(s) marked [x]" in script
    assert "--force to release anyway" in script
    flat = " ".join(script.split())
    assert "/review-close owns a batch that has # results; --release owns one that " \
        "does not." in flat, [s for s in flat.split(". ") if "--release owns" in s]


# ── closures for lens 3's selector survivors ─────────────────────────────────


_NARROW_RULE = "**The selector narrows; it never overrides.**"
_REPORT_RULE = "**Report what was excluded, not only what was selected.**"


@pytest.mark.parametrize("skill", SIBLINGS)
def test_the_two_rule_paragraphs_are_pinned_whole(skill):
    """Pin the paragraph, not a phrase inside it.

    Lens 3 kept `**The selector narrows; it never overrides.**` verbatim and
    *appended* a sentence granting the opposite — "A batch named explicitly is
    admitted even when 1a passed it over" — then did it again by unioning the
    missing requests in after the intersection. A phrase-level check cannot see a
    sentence added beside the phrase, so the whole paragraph is the unit.
    """
    block = "\n".join(_block_1d(skill))
    for rule in (_NARROW_RULE, _REPORT_RULE):
        para = next((p for p in block.split("\n\n") if rule in p), None)
        assert para is not None, f"{skill}: missing rule paragraph {rule!r}"
        flat = " ".join(para.split())
        # Exactly two sentences: the rule and its reason. A third is where the
        # override arrives.
        assert flat.count(". ") <= 3, (
            f"{skill}: the {rule!r} paragraph has grown extra sentences, which is "
            f"how an override gets added beside an intact rule: {flat}"
        )


@pytest.mark.parametrize("skill", SIBLINGS)
def test_the_selector_never_supplies_the_pool(skill):
    """1d must not be re-specified as selector-first anywhere in the block.

    Lens 3's B08 left the narrowing paragraph intact and re-specified the step
    above it: "read the batches it names straight out of `review_tasks.md` and use
    them as the pool, replacing 1a's selection". That is the same bypass arriving
    from a different sentence.
    """
    flat = " ".join("\n".join(_block_1d(skill)).split()).lower()
    for shape in ("as the pool", "replacing 1a", "instead of 1a", "union",
                  "add any requested", "admitted even", "straight out of"):
        assert shape not in flat, f"{skill}: 1d re-specifies the pool ({shape!r})"


@pytest.mark.parametrize("skill", SIBLINGS)
def test_an_empty_selection_arm_is_negated_not_merely_mentioned(skill):
    """Polarity, not presence — the A04 technique applied to the fail-safe.

    Lens 3 inverted this arm while keeping both required phrases, by moving the
    negation into a parenthetical about a "retired draft": "…fall through to the
    'no batches' message below … (An earlier draft said to do **not** fall
    through…)". Both needles present, instruction reversed.
    """
    flat = " ".join("\n".join(_block_1d(skill)).split())
    i = flat.index("intersection is empty")
    sentence = flat[i:flat.index(". ", i) + 1] if ". " in flat[i:] else flat[i:]
    assert "stop and print" in sentence, sentence
    for m in re.finditer(r"fall through", flat):
        preceding = flat[max(0, m.start() - 22):m.start()].lower()
        assert "not" in preceding, (
            f"{skill}: an un-negated 'fall through' at {m.start()}: "
            f"{flat[max(0, m.start() - 70):m.start() + 40]!r}"
        )


@pytest.mark.parametrize("skill", SIBLINGS)
def test_the_flag_bullet_declares_what_it_does_in_the_canonical_words(skill):
    """The bullet's body, not just its head (lens 3's B03 by synonym).

    The head-shape check closed `(reserved)`; B03 moved the hedge into the body —
    "accepted and currently a documented no-op; it will narrow this run…" — which
    the head check cannot see. The operative clause is pinned instead.
    """
    lines = _lines(skill)
    bullet = lines[_only(lines, lambda ln: ln.strip().startswith(f"- **`{FLAG}"),
                         f"{FLAG} bullet", skill)]
    head, _, body = bullet.partition("→")
    assert body.lstrip().startswith("narrow this run to the named batches."), body
    for hedge in ("no-op", "will narrow", "not implemented", "once implemented"):
        assert hedge not in body.lower(), f"{skill}: the bullet hedges ({hedge!r})"


@pytest.mark.parametrize("skill", SIBLINGS)
def test_the_selector_grammar_and_its_failure_mode_are_both_stated(skill):
    """Ranges inclusive, malformed selectors stop, and no positional alias.

    Three separate survivors: B14 flipped ranges to exclusive of `<hi>` (silently
    dropping the last batch of every range), B07 made a malformed range select
    nothing instead of stopping, and B22 re-added a bare positional alias the
    bullet's own rationale forbids.
    """
    block = " ".join("\n".join(_block_1d(skill)).split())
    lines = _lines(skill)
    bullet = lines[_only(lines, lambda ln: ln.strip().startswith(f"- **`{FLAG}"),
                         f"{FLAG} bullet", skill)]
    assert "inclusive" in block, block
    assert "exclusive" not in block, block
    assert "malformed selector" in block and "stop and say so" in block, block
    for alias in ("bare `b", "positional alias", "also accepted as a batch"):
        assert alias not in bullet, f"{skill}: a positional alias reappeared ({alias!r})"


@pytest.mark.parametrize("skill", SIBLINGS)
def test_step_0_states_where_the_selector_is_applied(skill):
    """B17 relocated the application point to after the lane split, in Step 0's prose.

    The section-order test pins where 1d *sits*; nothing pinned where Step 0 *says*
    it is applied, and an operator reading Step 0 gets the wrong answer while every
    placement assertion stays green.
    """
    lines = _lines(skill)
    bullet = lines[_only(lines, lambda ln: ln.strip().startswith(f"- **`{FLAG}"),
                         f"{FLAG} bullet", skill)]
    assert "Applied at Step 1d" in bullet, bullet
    assert "before Step 4's lane split" in bullet, bullet


def test_neither_sibling_prescribes_a_release_flag_that_does_not_exist():
    """`close_batch.sh --release` has never existed; `batch_work.sh` owns it.

    The phase's own first draft had this defect, the record says so, and lens 3
    reinstated it — with nothing red. A prescribed command that does not exist is
    the class rule 3 of the author-side pass exists for.
    """
    for skill in SIBLINGS:
        text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "close_batch.sh --release" not in text, skill
    script = (REPO_ROOT / "core" / "companion" / "scripts" / "close_batch.sh").read_text(
        encoding="utf-8")
    assert "--release" not in script.replace(
        "# lock here is unremovable by every other path (`--release` refuses a", ""), (
        "close_batch.sh grew a --release flag; the skills' prose needs revisiting")


@pytest.mark.parametrize("skill", SIBLINGS)
def test_all_three_report_lines_are_required_and_none_is_optional(skill):
    """B18 deleted the `Selected:` line; B05 declared the other two optional.

    The three lines answer three different questions — what ran, what the selector
    dropped from the pool, and what was asked for and never in the pool. Any one of
    them missing turns a narrowed run back into a report that looks like a full one.
    """
    block = "\n".join(_block_1d(skill))
    flat = " ".join(block.replace("`", "").split())
    for line in ("Selected:", "Excluded by --batches:", "Requested but not in the pool:"):
        assert line in flat, f"{skill}: the 1d report block lost {line!r}"
    for licence in ("on its own is enough", "the other two lines", "detail you can leave out",
                    "for a routine narrowing"):
        assert licence not in flat.lower(), (
            f"{skill}: the exclusion report was downgraded to optional ({licence!r})")


@pytest.mark.parametrize("skill", SIBLINGS)
def test_the_range_grammar_is_inclusive_where_it_is_declared(skill):
    """B14 flipped the Step 0 bullet to exclusive while 1d still said inclusive.

    Two statements of one grammar, disagreeing — and the guard only read 1d. An
    off-by-one that silently drops the last batch of every range is exactly the kind
    of defect a second, unchecked statement of the same rule produces.
    """
    lines = _lines(skill)
    bullet = lines[_only(lines, lambda ln: ln.strip().startswith(f"- **`{FLAG}"),
                         f"{FLAG} bullet", skill)]
    block = "\n".join(_block_1d(skill))
    for where, text in (("Step 0 bullet", bullet), ("1d", block)):
        assert "inclusive" in text, f"{skill}: {where} does not declare ranges inclusive"
        assert "exclusive" not in text, f"{skill}: {where} declares ranges exclusive"


def test_each_sibling_names_the_other_as_the_owner_of_the_batches_it_skips():
    """B06 swapped the two skills' pool-side reasons, so each cited its own lane.

    The reason line is what an operator reads when a requested batch is missing; if
    it names the wrong skill they run the wrong command next, and the two files are
    near-identical so the swap is invisible to any check that is not per-skill.
    """
    expected = {
        "auto-fix": ("has a Flag: line (belongs to /auto-judge)", "/auto-fix"),
        "auto-judge": ("no Flag: line (belongs to /auto-fix)", "/auto-judge"),
    }
    for skill, (reason, own) in expected.items():
        block = " ".join("\n".join(_block_1d(skill)).replace("`", "").split())
        assert reason in block, f"{skill}: expected the reason {reason!r}"
        assert f"belongs to {own})" not in block, (
            f"{skill}: its own reason line points back at itself — the sibling "
            "reasons have been swapped")
