"""Guards for the `Q-409` campaign's two transform tools — the things that WRITE.

`tools/reader_census.py` measures and has its own module; these two change the shipped tree:

* `tools/phase295_split.py` applies one transform-1 delete or one transform-4 split, and
  enforces the word-subset check that separates a faithful split from a laundering one.
* `tools/phase295_precondition_b.py` measures transform 4's precondition (b) by deleting a
  block and running the reader modules.

**Why they need a test module at all, and why it is this one.** `tools/` has no shipped runner,
so a maintainer-side script's only route into CI is a module that imports it — the reason
`tests/test_reader_census.py` exists, restated here for the write side. Phase 298 added both
mechanisms below (transform 1, and the markdown spellings of the pointer line) and neither had a
guard; a refusal nothing exercises is a refusal that stops refusing the first time someone
simplifies it.

**`tools/` is stripped from the public mirror**, where this suite is a required check, so the
module loads lazily and stands down when the script is absent — `tests/test_reader_census.py`'s
accommodation, for its reason.

What these assert, in order of what they are worth:

1. **The pointer exclusion stays closed.** It is the ONE hole in the word-subset check, and the
   check is the only mechanism separating a faithful split from a reversal. A loose "any line
   naming `REFERENCE.md`" reading would let a replacement carry arbitrary new vocabulary on that
   line, which is the loophole the constant's own comment is written against.
2. **The word-subset check still fails a paraphrase.** Its declared blind spots (a reversal built
   from the block's own words, a softening by deletion, and numbers) are not the claim; catching
   an introduced word is, and that is what is pinned.
3. **Transform 1 refuses a `mixed` block.** Deleting a `mixed` block whole takes its binding rule
   with it — § 10's laundering direction performed in one command instead of two.
4. **A measurement over an empty candidate set is an error, not a clean run.** Zero candidates is
   a misspelled section far more often than an empty one, and a scan that finds nothing must not
   report what a scan that found nothing to look at reports.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _case_pins import (  # noqa: E402
    case_pin_problems,
    parametrize_shape_problems,
    unpinned_list_problems,
)

REPO = Path(__file__).resolve().parent.parent
SPLIT = REPO / "tools" / "phase295_split.py"
PRECOND = REPO / "tools" / "phase295_precondition_b.py"
LOCK_RATES = REPO / "tools" / "phase298_lock_rates.py"

pytestmark = pytest.mark.skipif(
    not (SPLIT.exists() and PRECOND.exists() and LOCK_RATES.exists()),
    reason="the campaign's transform tools are maintainer-side and mirror-excluded",
)

if SPLIT.exists():
    sys.path.insert(0, str(REPO / "tools"))
    from phase295_split import (  # noqa: E402
        POINTER,
        delete_block_spans,
        word_subset,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. The pointer exclusion

#: Every spelling the campaign has authorised, and nothing else. The comment form is Phase 295's
#: (a `comment-run` block inside a heredoc); the two markdown forms are Phase 298's, because `#`
#: at the head of a markdown line is a HEADING and § 4c is the first section whose candidates are
#: `prose` and `blockquote` blocks.
POINTER_ACCEPTS = (
    "# See REFERENCE.md, section Step 3b — provenance.",
    "   # See REFERENCE.md, section Step 4c — provenance.",
    "See `REFERENCE.md` § *Step 4c — provenance*.",
    "   > See `REFERENCE.md` § *Step 4c — provenance*.",
    # Hyphenated step ids. `4-pre` is a live section of this very skill and `4a-post` is named
    # throughout it; the class was `[0-9a-z]+` and refused both, so every prose replacement in
    # either would have failed the word-subset check on the pointer's own vocabulary.
    "# See REFERENCE.md, section Step 4-pre — provenance.",
    "See `REFERENCE.md` § *Step 4a-post — provenance*.",
    # § 2b's spellings, added by Phase 299's round (guards lens). That section's twelve candidates
    # are `blockquote`, `prose` and `listitem` — zero `comment-run` — so every pointer it ships is
    # markdown-form, and one of them is a five-space-indented continuation line inside a list
    # item. Both are accepted by `POINTER` at runtime and neither was exercised by a case here,
    # which is a roster that certifies less than the tree relies on.
    "   See `REFERENCE.md` § *Step 2b — provenance*.",
    "> See `REFERENCE.md` § *Step 2b — provenance*.",
    "     See `REFERENCE.md` § *Step 2b — provenance*.",
)

#: The shapes that MUST NOT be excluded. Each one is a way the hole could widen: content sharing
#: the line, a bare mention, a different destination, or a sentence wearing the pointer's words.
POINTER_REFUSES = (
    "Blah blah. See `REFERENCE.md` § *Step 4c — provenance*.",
    "See `REFERENCE.md` § *Step 4c — provenance*. And also note this.",
    "# See REFERENCE.md for the reasoning behind all of this.",
    "See `REFERENCE.md`.",
    "> the argument for this lives in `REFERENCE.md`",
    "# See OTHER.md, section Step 4c — provenance.",
    # The comment arm's LEADING side, and both arms' step-id slot. Phase 298 closed the
    # destination asymmetry and left these three: its round widened `#\s*See` to `#.*See`,
    # `section Step [0-9a-z]+` to `.+`, and `\*Step [0-9a-z]+` to `.+`, and every case here
    # stayed green. Each admits a line carrying arbitrary content past the word-subset check.
    "# the ceiling does not apply anyway. See REFERENCE.md, section Step 4c — provenance.",
    "# See REFERENCE.md, section Step 4c and skip the merge check — provenance.",
    "See `REFERENCE.md` § *Step 4c and skip the merge check — provenance*.",
    "> See `REFERENCE.md` § *Step 4c and skip the merge check — provenance*.",
    # The destination, in the MARKDOWN forms. A first version of this list pinned a wrong
    # destination only in the comment spelling, and this phase's own battery walked straight
    # through it: widening the markdown arm to `See `[A-Z]+.md`` left every case here green.
    "See `OTHER.md` § *Step 4c — provenance*.",
    "> See `SPEC.md` § *Step 4c — provenance*.",
)


def pointer_population_problems(accepts, refuses) -> list[str]:
    """The two pointer lists' size and shape, as a predicate a control can drive."""
    problems = []
    if len(accepts) != 9:
        problems.append(f"POINTER_ACCEPTS has {len(accepts)} rows, pinned at 9")
    if len(refuses) != 12:
        problems.append(f"POINTER_REFUSES has {len(refuses)} rows, pinned at 12")
    # Every authorised spelling the campaign has, present by shape rather than by count alone.
    if not any(ln.lstrip().startswith("#") for ln in accepts):
        problems.append("the comment form is gone")
    if not any("§ *Step" in ln and not ln.lstrip().startswith((">", "#")) for ln in accepts):
        problems.append("the prose form is gone")
    if not any(ln.lstrip().startswith(">") for ln in accepts):
        problems.append("the blockquote form is gone")
    return problems


def test_the_pointer_populations_are_not_empty():
    """Both lists parametrize a test, so emptying either leaves its test collecting NOTHING and
    the suite exiting 0.

    Phase 298's round did exactly that — `@pytest.mark.parametrize("line", [])` on the refusal
    list removed eight rows and the run reported green. The author guarded this class twice in
    the same phase (`assert mixed, "…would pass by not running"`, `assert named, "…the guard
    finds nothing"`) and not here, in the list its own module docstring ranks first.

    Counts, not just non-emptiness: a list trimmed to one element is still non-empty and still
    guards almost nothing. **Exact since Phase 327** (`Q-592` line 24): the floors were `>= 4` and
    `>= 8` against 9 and 12 rows, so five and four rows could leave with this green, and the lists'
    comments tie each group of rows to the widening it kills. Adding a row means raising the
    number in the same commit. What a count still cannot see is a row rewritten in place.
    """
    assert pointer_population_problems(POINTER_ACCEPTS, POINTER_REFUSES) == []


def test_the_pointer_population_bars_are_driven():
    """The control the counts lacked: one row removed from either list must report. Phase 327's
    battery loosened `== 12` back to `>= 8` with no row removed and nothing noticed, because
    the bar was an inline assert no control could feed a shorter list."""
    assert pointer_population_problems(POINTER_ACCEPTS[:-1], POINTER_REFUSES)
    assert pointer_population_problems(POINTER_ACCEPTS, POINTER_REFUSES[:-1])
    # And one ADDED, so the pin stays exact in both directions (the round loosened `!=` to `<`).
    assert pointer_population_problems(POINTER_ACCEPTS + POINTER_ACCEPTS[:1], POINTER_REFUSES)
    assert pointer_population_problems(POINTER_ACCEPTS, POINTER_REFUSES + POINTER_REFUSES[:1])
    # Each form removed with the row COUNT kept, so the count arm cannot answer for the form
    # arm — the battery's one survivor on the first cut of this control.
    for form, is_form in (
        ("comment", lambda ln: ln.lstrip().startswith("#")),
        ("prose", lambda ln: "§ *Step" in ln and not ln.lstrip().startswith((">", "#"))),
        ("blockquote", lambda ln: ln.lstrip().startswith(">")),
    ):
        kept = [ln for ln in POINTER_ACCEPTS if not is_form(ln)]
        padded = kept + [kept[0]] * (len(POINTER_ACCEPTS) - len(kept))
        assert pointer_population_problems(padded, POINTER_REFUSES) == [f"the {form} form is gone"], form


#: How many parametrized controls this module carries. Exact, not a floor: the predecessor's
#: `checked >= 4` equalled the population, so it could see a control deleted but not a new one
#: that later left. Six since Phase 327 added the tamper and per-entry controls below.
_PARAMETRIZE_DECORATOR_COUNT = 6

#: The inline case rows that may not leave this module, keyed by the test they control. Every
#: row of every inline list: each is the only row killing some widening of the arm it drives.
#: Format and semantics are `tests/_case_pins.py`'s, the same as `tests/test_reader_census.py`.
_CASE_PINS = {
    # Transform 1's predicate has four arms and one positive control below; each refused state
    # is its own arm. A whole-row pin, because the rows are single-argname strings and a column
    # projection would index a CHARACTER (the shape `_case_pins.py` refuses).
    "test_transform_1_refuses_every_state_that_is_not_editor": (None, ("mixed", "runner", "none")),
    # Neither mode and both modes are separate refusals. Column 0 only: column 1 is prose.
    "test_transform_1_and_4_are_mutually_exclusive_and_one_is_required": (0, (
        ("--key", "deadbeefdeadbeef"),
        ("--key", "deadbeefdeadbeef", "--delete", "--replacement", "/dev/null"),
    )),
    # The pin's own control: each find/replace pair is one tamper the pins must see. Columns
    # 0 and 1; column 2 is prose.
    "test_the_case_pin_actually_bites": ((0, 1), (
        ('\n@pytest.mark.parametrize("state", ["mixed", "runner", "none"])\n',
         '\n@pytest.mark.parametrize("state", ["mixed", "runner"])\n'),
        ('\n    (("--key", "deadbeefdeadbeef"), "neither mode"),\n', "\n"),
        ('\n@pytest.mark.parametrize("args, why", [\n',
         '\n@pytest.mark.skip(reason="tampered", rows=[\n'),
        ("\ndef test_transform_1_refuses_every_state_that_is_not_editor(state):",
         "\ndef test_transform_1_refuses_every_state_that_is_not_editor_RENAMED(state):"),
    )),
}


def pin_guard_problems(source: str, pins: dict) -> list[str]:
    """The whole pin guard as one function, so a control drives what the guard runs.
    Phase 327's round removed the partition from the guard alone and nothing noticed."""
    return (case_pin_problems(source, pins) + unpinned_list_problems(source, pins)
            + parametrize_shape_problems(source, _PARAMETRIZE_DECORATOR_COUNT, globals()))


def test_no_parametrized_case_list_here_can_be_silently_emptied():
    """What the DECORATOR receives, which is not what the constants say.

    A first version of the guard above read `POINTER_ACCEPTS` and `POINTER_REFUSES` and asserted
    they were populated. The round's mutation never touched them: it replaced the decorator's
    argument with `[]`, so the constants stayed full, the guard stayed green, and twelve rows
    stopped running. **Checking the constant is not checking the parametrization.**

    **Phase 327 (`Q-592` line 24) replaced the count with content.** This guard asserted
    `len(cases.elts) >= 2` over its two inline lists — the check `Q-518` measured as a bypass in
    `tests/test_reader_census.py`, which ported its guard FROM this module and was hardened while
    this source was not. Now each inline row is pinned by value (`case_pin_problems`), every
    inline list must carry a pin (`unpinned_list_problems`), and the decorator count is exact
    (`parametrize_shape_problems`), all from `tests/_case_pins.py`.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    problems = pin_guard_problems(source, _CASE_PINS)
    assert not problems, "\n\n".join(problems)


@pytest.mark.parametrize("find, replace, why", [
    # Every find opens on a real newline, which this list's own source spells as the two
    # characters `\n`, so no row can match itself — the census module's anchoring rule.
    ('\n@pytest.mark.parametrize("state", ["mixed", "runner", "none"])\n',
     '\n@pytest.mark.parametrize("state", ["mixed", "runner"])\n',
     "the no-verdict row deleted — the majority population's arm"),
    ('\n    (("--key", "deadbeefdeadbeef"), "neither mode"),\n', "\n",
     "the neither-mode row deleted"),
    ('\n@pytest.mark.parametrize("args, why", [\n',
     '\n@pytest.mark.skip(reason="tampered", rows=[\n',
     "a pinned control's parametrize swapped for a skip that keeps its rows in the source"),
    ("\ndef test_transform_1_refuses_every_state_that_is_not_editor(state):",
     "\ndef test_transform_1_refuses_every_state_that_is_not_editor_RENAMED(state):",
     "a pinned control renamed"),
])
def test_the_case_pin_actually_bites(find, replace, why):
    """The control, driving the real predicates over a tampered copy of this module's source."""
    body = Path(__file__).read_text(encoding="utf-8")
    assert body.count(find) == 1, f"the injection point for {why!r} is not unique"
    tampered = body.replace(find, replace)
    assert pin_guard_problems(tampered, _CASE_PINS), f"the pins did not see {why}"


#: A module constant because `parametrize_shape_problems` sizes a named list and refuses a call.
_PINNED_TESTS = sorted(_CASE_PINS)


def test_the_composite_drives_its_shape_term():
    """Round 2 deleted `parametrize_shape_problems` from `pin_guard_problems` with the module
    green: the tamper rows drive the content term and the per-entry control the partition, and
    nothing drove the third. A NAME-driven control added (count off by one, no inline rows) and a
    name-driven list sliced to nothing each reach that term alone."""
    source = Path(__file__).read_text(encoding="utf-8")
    added = source + '\n@pytest.mark.parametrize("x", _PINNED_TESTS)\ndef test_extra(x): pass\n'
    assert pin_guard_problems(added, _CASE_PINS), "an extra control went uncounted"
    # Anchored on REAL newlines, which this literal spells `\\n`, so it cannot match itself.
    anchor = '\n@pytest.mark.parametrize("dropped", _PINNED_TESTS)\ndef test_a_deleted'
    assert source.count(anchor) == 1, "re-anchor this control"
    sliced = source.replace(anchor, anchor.replace("_PINNED_TESTS)", "_PINNED_TESTS[:0])"))
    assert pin_guard_problems(sliced, _CASE_PINS), "a sliced control list went unseen"
    # And the per-entry control's population is the whole pin table, not a prefix of it.
    assert _PINNED_TESTS == sorted(_CASE_PINS)


@pytest.mark.parametrize("dropped", _PINNED_TESTS)
def test_a_deleted_pin_entry_is_seen_even_with_its_rows_gone(dropped):
    """Any one entry removed from `_CASE_PINS` must report through the guard itself."""
    fewer = {k: v for k, v in _CASE_PINS.items() if k != dropped}
    problems = pin_guard_problems(Path(__file__).read_text(encoding="utf-8"), fewer)
    assert any(p.startswith(f"{dropped}:") for p in problems), (
        f"deleting the {dropped!r} pin entry went unseen")


@pytest.mark.parametrize("line", POINTER_ACCEPTS)
def test_the_pointer_exclusion_accepts_every_authorised_spelling(line):
    assert POINTER.match(line), (
        f"{line!r} is an authorised pointer line and is no longer excluded — a split using it "
        f"would fail the word-subset check on the pointer's own vocabulary"
    )


@pytest.mark.parametrize("line", POINTER_REFUSES)
def test_the_pointer_exclusion_refuses_everything_else(line):
    assert not POINTER.match(line), (
        f"{line!r} is excluded from the word-subset check. The exclusion is ONE line of fixed "
        f"shape; anything looser lets a replacement smuggle new vocabulary past the only "
        f"mechanism that separates a faithful split from a laundering one."
    )


def test_exactly_one_pointer_line_is_allowed():
    """Not zero, and not two. § 9.1 says `one such line per replacement` and means it.

    Zero matters as much as two: `word_subset` returning ok on a pointerless replacement would
    let a split relocate content with nothing in the runner naming where it went.
    """
    old = "the runner keeps the rule and this keeps the argument"
    ptr = "See `REFERENCE.md` § *Step 4c — provenance*."
    assert word_subset(old, f"the runner keeps the rule\n{ptr}")[0]
    assert not word_subset(old, "the runner keeps the rule")[0], "zero pointer lines passed"
    assert not word_subset(old, f"the runner keeps the rule\n{ptr}\n{ptr}")[0], "two passed"


# ─────────────────────────────────────────────────────────────────────────────
# 2. The word-subset check itself


def test_the_word_subset_check_catches_an_introduced_word():
    """The paraphrase class — the one thing this check actually reaches.

    Its blind spots are declared in the module and are not tested here because they are not
    claims: a reversal assembled from the block's own vocabulary passes, and so does a softening
    by pure deletion. What must not happen is the check going quiet on the class it does cover.
    """
    # SYNTHETIC, and that is load-bearing. A first version used § 2b's real sentence — the one
    # § 9.1's laundering table cites — and Phase 298's round measured the consequence: a test
    # fixture that quotes skill prose verbatim BECOMES a unique reader-module literal, so the
    # lock-rate scan counted a 704-character § 2b block as anchored by this file and nothing
    # else, moving that section's published rate 71.9% -> 74.6%. The campaign's own guards must
    # not mint anchors on the text the campaign has still to relocate.
    old = "say so and KEEP GOING, do not halt"
    ptr = "See `REFERENCE.md` § *Step 4c — provenance*."
    ok, introduced, _ = word_subset(old, f"note it and proceed as you judge best\n{ptr}")
    assert not ok
    assert introduced == ["as", "best", "it", "judge", "note", "proceed", "you"], introduced


def test_an_introduced_NUMBER_is_caught_even_though_a_reused_one_is_not():
    """The tokenizer's digit class, which is load-bearing and was pinned by nothing.

    `_WORD` is `[A-Za-z0-9_]+`. The module DECLARES that a number the block already carries is
    free vocabulary — that blind spot is stated and is not a finding. What is not declared, and
    what nothing held, is the other half: a number the block does NOT carry is caught, and
    dropping `0-9` from the class silently ends that. Phase 298's round mutated it to
    `[A-Za-z_]+` and the whole module stayed green.
    """
    old = "The gate fires at Phase 201 and exits 4."
    ptr = "See `REFERENCE.md` § *Step 4c — provenance*."
    ok, introduced, _ = word_subset(old, f"The gate fires at Phase 999 and exits 4.\n{ptr}")
    assert not ok and introduced == ["999"], introduced
    # And the declared blind spot, asserted as a LIMIT so nobody reads the line above as more
    # than it is: a number the block already carries passes.
    ok2, _, _ = word_subset(old, f"The gate fires at Phase 4 and exits 201.\n{ptr}")
    assert ok2, "a reused number should pass — this is the module's declared blind spot"


def test_the_comparison_is_case_folded():
    """`words()` lowercases, and dropping that is a STRICTNESS change nothing held.

    Without it a replacement that merely recapitalises a word it kept — sentence case at a new
    line break, which is the single most ordinary thing a re-author does — scores that word as
    introduced and the split is refused. Phase 298's round dropped `.lower()` and the module
    stayed green, so the check could have become unusable on a legal replacement with nothing
    saying so.
    """
    ptr = "See `REFERENCE.md` § *Step 4c — provenance*."
    ok, introduced, _ = word_subset("the runner keeps the rule",
                                    f"The runner keeps the rule\n{ptr}")
    assert ok, f"a recapitalised word scored as introduced: {introduced}"


def test_the_pointer_lines_own_words_do_not_leak_into_the_comparison():
    """The exclusion drops the pointer LINE, not merely its match — otherwise `provenance`,
    `section` and the step id would silently become free vocabulary for the whole replacement."""
    old = "hold the doc and report it"
    ptr = "See `REFERENCE.md` § *Step 4c — provenance*."
    ok, introduced, _ = word_subset(old, f"hold the doc, report its provenance\n{ptr}")
    assert not ok and "provenance" in introduced, introduced


# ─────────────────────────────────────────────────────────────────────────────
# 3. Transform 1's refusals, driven as a subprocess so the CLI contract is what is tested


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *args],
                          cwd=REPO, capture_output=True, text=True)


def _live_keys():
    """One census sha per verdict state, resolved from the tree rather than hard-coded.

    A hard-coded sha goes stale the first time the campaign edits that block, and the test then
    passes by failing for the wrong reason.
    """
    sys.path.insert(0, str(REPO / "tools"))
    import json as _json

    import reader_census as rc
    verdicts = _json.loads(
        (REPO / "tools/reader_census/review-close.json").read_text(encoding="utf-8"))
    blocks = rc.census("review-close")["blocks"]
    out = {}
    for b in blocks:
        v = (verdicts.get(b.sha) or {}).get("verdict") or "none"
        out.setdefault(v, b.sha)
    return out


@pytest.mark.parametrize("state", ["mixed", "runner", "none"])
def test_transform_1_refuses_every_state_that_is_not_editor(state):
    """Transform 1's predicate has FOUR arms and its first version pinned one.

    `editor` passes; `mixed`, `runner` and *no verdict at all* must each be refused. A first
    version asserted only the `mixed` refusal, and Phase 298's round walked three widenings
    through it — `("editor", "runner")`, a `("mixed",)` blocklist, and `.get("verdict",
    "editor")`. The last is the one that matters: **1,039 of 1,592 distinct shas carry no
    verdict**, so the unpinned branch governed the majority of the file, and with it applied the
    tool offered to delete the skill's own YAML frontmatter.

    A `mixed` block deleted whole takes its binding rule with it; a `runner` block is not the
    campaign's population at all; and a block with no verdict is one nobody has read.
    """
    keys = _live_keys()
    sha = keys.get(state)
    assert sha, f"no block in state {state!r} — this case would pass by not running. {sorted(keys)}"

    proc = _run(SPLIT, "--key", sha, "--delete")
    assert proc.returncode == 1, f"{state} {sha}: {proc.returncode}\n{proc.stdout}{proc.stderr}"
    assert "not `editor`" in proc.stderr, proc.stderr


def test_transform_1_accepts_an_editor_block():
    """The positive arm. Without it, a predicate that refuses EVERYTHING passes every case above
    — the vacuity direction a refusal-only parametrization cannot see."""
    sha = _live_keys().get("editor")
    assert sha, "no `editor` block left in review-close — transform 1's population is empty"
    proc = _run(SPLIT, "--key", sha, "--delete")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "transform 1" in proc.stdout, proc.stdout


def test_the_no_verdict_population_is_the_majority_so_its_arm_is_not_a_corner():
    """The measurement that makes the `none` case above worth its line rather than tidy.

    Stated as an inequality, not a count: a count goes stale on the campaign's next commit, and
    the claim being pinned is that the unverdicted population is LARGE — which is why leaving its
    arm untested was a hole rather than an omission.
    """
    keys_by_state = {}
    sys.path.insert(0, str(REPO / "tools"))
    import json as _json

    import reader_census as rc
    verdicts = _json.loads(
        (REPO / "tools/reader_census/review-close.json").read_text(encoding="utf-8"))
    shas = {b.sha for b in rc.census("review-close")["blocks"]}
    unverdicted = shas - set(verdicts)
    assert len(unverdicted) > len(shas) / 2, (
        f"{len(unverdicted):,} of {len(shas):,} distinct shas carry no verdict; the `none` arm "
        f"was pinned because that branch governs most of the file")


@pytest.mark.parametrize("args, why", [
    (("--key", "deadbeefdeadbeef"), "neither mode"),
    (("--key", "deadbeefdeadbeef", "--delete", "--replacement", "/dev/null"), "both modes"),
])
def test_transform_1_and_4_are_mutually_exclusive_and_one_is_required(args, why):
    """Passing neither took the split path with an empty replacement and reported a
    100%-thinned split — a transform printing a number for work it did not do."""
    proc = _run(SPLIT, *args)
    assert proc.returncode == 2, f"{why}: {proc.returncode}\n{proc.stdout}{proc.stderr}"
    assert "exactly one of --delete" in proc.stderr, proc.stderr


# ─────────────────────────────────────────────────────────────────────────────
# 3b. The span arithmetic transform 1 asserts before it writes


class _FakeBlock:
    """The two fields `delete_block_spans` reads. 1-based inclusive line span, as the census
    emits — the off-by-one here is the whole point of the check under test."""

    def __init__(self, start: int, end: int, text: str):
        self.start, self.end, self.text = start, end, text


def test_the_span_delete_accounts_for_exactly_what_it_removed():
    original = "keep one\nBLOCK a\nBLOCK b\nkeep two\n"
    block = _FakeBlock(2, 3, "BLOCK a\nBLOCK b")
    mutated, problem = delete_block_spans(original, [block])
    assert problem is None, problem
    assert mutated == "keep one\nkeep two\n"


def test_a_span_that_overreaches_is_visible_in_the_arithmetic():
    """The defect the check exists for, handed to it.

    In the live tool this comparison is unreachable — a correct census always makes the two
    agree — so neutering it goes unnoticed, which is what this phase's own battery measured.
    A block whose recorded span is one line too wide removes a line it does not account for,
    and `got` exceeds `expect` by exactly that line.
    """
    original = "keep one\nBLOCK a\nBLOCK b\nkeep two\n"
    overreaching = _FakeBlock(2, 4, "BLOCK a\nBLOCK b")
    _, problem = delete_block_spans(original, [overreaching])
    assert problem, "an over-wide span reported as accounted-for"
    assert "do not account" in problem, problem


def test_descending_order_is_what_keeps_two_spans_from_shifting_each_other():
    """Two blocks deleted in one call. Ascending order would make the second span stale."""
    original = "a\nB1\nc\nB2\ne\n"
    blocks = [_FakeBlock(2, 2, "B1"), _FakeBlock(4, 4, "B2")]
    mutated, problem = delete_block_spans(original, blocks)
    assert mutated == "a\nc\ne\n", mutated
    assert problem is None, problem


# ─────────────────────────────────────────────────────────────────────────────
# 4. The precondition-(b) measurement's empty-population refusal


def test_an_unknown_section_is_an_error_and_names_the_known_ones():
    proc = _run(PRECOND, "--section", "no-such-step", "--list")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "known sections" in proc.stderr, proc.stderr
    assert "## Step 3b: Prepare Worktrees for Merge" in proc.stderr, proc.stderr


def test_an_unknown_verdict_is_refused_rather_than_measured_as_empty():
    proc = _run(PRECOND, "--section", "4c", "--verdicts", "bogus", "--list")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "unknown verdicts" in proc.stderr, proc.stderr


# ─────────────────────────────────────────────────────────────────────────────
# 5. The lock-rate instrument — the third tool, which had no tests at all
#
# Phase 298's round: this module covered the two tools that WRITE and left the one whose
# output is published as a nine-cell table in the spec, and whose docstring carried the
# stability claim that same round falsified.


def test_the_lock_rate_tool_runs_and_its_headline_matches_its_own_computation():
    """The headline is a claim ABOUT the rows above it, so the two must not be able to disagree.

    Asserted by parsing the tool's own output rather than by recomputing the rates here — a
    control that does its own arithmetic re-asserts its own mutation, which is the shape this
    repo has now caught in three separate guards.
    """
    proc = _run(LOCK_RATES)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    orders = re.findall(r">=\s*\d+:\s*(\S+ < \S+ < \S+)", proc.stdout)
    assert len(orders) >= 3, f"expected one ranking line per threshold:\n{proc.stdout}"
    says_stable = "ranking is STABLE" in proc.stdout
    assert says_stable == (len(set(orders)) == 1), (
        f"the headline says {'STABLE' if says_stable else 'NOT stable'} while the rankings are "
        f"{orders} — the headline is a claim about the rows and cannot contradict them")


def test_a_thinned_section_is_named_whether_or_not_the_ranking_is_stable():
    """The warning must NOT be gated on instability, and a first version gated it.

    A thinned section sorts UPWARD, so once every threshold agrees on the wrong order the
    headline reads `STABLE` and a gated warning never prints — which is the state this tool
    reached the moment a fixture fix moved one rate, in the same session. **A ranking that is
    stable because one member is a remnant is worse than an unstable one: it looks like
    evidence.** So the check is on the rows, not on the headline.
    """
    proc = _run(LOCK_RATES)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rates = [float(m) for m in re.findall(r"\s(\d+\.\d)%", proc.stdout)]
    assert rates, f"no rates parsed:\n{proc.stdout}"
    if max(rates) > 95:
        assert "ALREADY THINNED" in proc.stdout, (
            "a section reads >95% locked and the tool did not name it as thinned — the ranking "
            "is then presented as an ordering input when it is not:\n" + proc.stdout)
    else:
        assert "ALREADY THINNED" not in proc.stdout, (
            "the tool called a section thinned with every rate under 95%:\n" + proc.stdout)


def test_the_lock_rate_tool_refuses_a_threshold_that_measures_nothing():
    proc = _run(LOCK_RATES, "--min", "30")
    assert proc.returncode == 0 and "3b" in proc.stdout, proc.stdout
    bad = _run(LOCK_RATES, "--min", "not-a-number")
    assert bad.returncode == 2, bad.stdout + bad.stderr


def test_every_copy_of_the_campaign_section_map_agrees():
    """The campaign's section map exists in THREE places, and this guard named two.

    `SECTIONS` in the precondition-(b) tool, `SECTIONS` in the lock-rate tool, and
    `_CAMPAIGN_SECTIONS` in the census guards. A fork means a phase measures one section and
    reports another's figures, which is not a failure any single side can see.

    Phase 298's round found the third copy uncovered — and it is the one that produced the
    threshold table published in `tools/CONTEXT_THINNING_SPEC.md` § 8.2, which is exactly the
    failure this guard's own docstring describes. The phase's own battery row was scoped the same
    way, to "the two copies", so the battery could not see it either.
    """
    from phase295_precondition_b import SECTIONS as PRECOND  # noqa: E402
    from phase298_lock_rates import SECTIONS as LOCK_RATES  # noqa: E402

    from test_reader_census import _CAMPAIGN_SECTIONS  # noqa: E402
    copies = {
        "phase295_precondition_b.SECTIONS": PRECOND,
        "phase298_lock_rates.SECTIONS": LOCK_RATES,
        "test_reader_census._CAMPAIGN_SECTIONS": _CAMPAIGN_SECTIONS,
    }
    # The MEMBERSHIP is asserted, not just the agreement. Phase 300's round dropped
    # `phase298_lock_rates` out of `copies` and the guard stayed green over the two that were
    # left — a fork check that only compares the copies it is handed cannot notice one going
    # unhanded, which is this guard's own docstring incident (Phase 298's round found the third
    # copy uncovered) arriving through the call site instead of the roster.
    assert set(copies) == {
        "phase295_precondition_b.SECTIONS",
        "phase298_lock_rates.SECTIONS",
        "test_reader_census._CAMPAIGN_SECTIONS",
    }, f"a copy left the comparison: {sorted(copies)}"
    problems = section_map_problems(copies, _CAMPAIGN_SECTIONS)
    assert not problems, "\n".join(problems)


def section_map_problems(copies: dict, reference: dict) -> list[str]:
    """The fork check as a predicate its control can DRIVE.

    Phase 300's round neutered the inline version two ways with the whole suite green —
    `distinct = {}`, and dropping a copy out of `copies` before the comparison. Every mutation to
    the map's SUBJECT was killed, so the guard looked strong; nothing was exercising the guard
    itself. That is the shape `editor_mass_problems` in the sibling module carries a paragraph
    about, made again here.
    """
    problems = []
    empty = sorted(n for n, m in copies.items() if not m)
    if empty:
        problems.append(f"a copy of the section map is empty: {empty}")
    distinct = {n: m for n, m in copies.items() if m != reference}
    if distinct:
        problems.append("the campaign's section map has forked:\n"
                        + "\n".join(f"  {n}: {m}" for n, m in copies.items()))
    return problems
