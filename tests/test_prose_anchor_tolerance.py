"""Phase 292 — `Q-495`: a rendering-identical reformat must not redden a guard.

Phase 291 ran four no-meaning-change reformats of `review-close/SKILL.md` against the
guards over it. Three went red, and in two of the three the failing assertion was a
shipped test's MUTATION ANCHOR rather than a rule: the row pins the pre-mutation text as
a literal, so re-wrapping that text staled the anchor while every rule it protects stayed
intact. The suite reddened, and the fix each time was to re-type a literal in a test —
a re-approval with no review in it, which is the failure `Q-458` names.

**Why the anchors stayed raw when the assertions did not.** Eleven modules already flatten
the whole file and search the flattened copy, which is tolerant in exactly the way this
needs. What flattening destroys is the OFFSET — a position in the flattened string names
nothing in the file — so a guard that has to EDIT the text could not use it. Every
mutation table must plant its mutation in the real file before the checks run, so every
mutation table stayed on raw `str.replace`. `anchor()` closes that: it is tolerant AND it
returns a span in the original text, so the tolerant read and the edit are one operation.

Everything here is synthetic on purpose. Phase 291's round found two arms of its own
canonicaliser deletable in silence because every fixture exercised them only through the
shipped files, where an unrelated property happened to cover them.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests"))

from _prose_guard_helpers import anchor, carries, locate, rewrapped, swap  # noqa: E402

SKILL = REPO_ROOT / "core/skills/review-close/SKILL.md"

SENTENCE = "A scope you could not compute must never silently narrow the gate."


# --------------------------------------------------------------------------------------
# What the anchor must ABSORB — the reformats that change no meaning
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("layout,why", [
    ("A scope you could not compute\nmust never silently narrow the gate.", "re-wrapped"),
    ("A scope you could not compute\n    must never silently narrow the gate.", "re-indented"),
    ("A scope you could not\ncompute must never\nsilently narrow the gate.", "wrapped narrow"),
    ("A scope  you   could not compute must never silently narrow the gate.", "re-spaced"),
    ("A\nscope\nyou\ncould\nnot\ncompute\nmust\nnever\nsilently\nnarrow\nthe\ngate.", "one word per line"),
    ("A scope you could not compute\tmust never silently narrow the gate.", "tab"),
])
def test_the_anchor_absorbs_a_layout_change(layout, why):
    assert carries(layout, SENTENCE), f"{why}: a rendering-identical reformat went red"


def test_the_anchor_is_found_where_a_raw_literal_is_not():
    """The defect, in one assertion: same text, same words, only the layout moved."""
    reformatted = SENTENCE.replace(" must", "\n  must")
    assert SENTENCE not in reformatted, "the control did not actually stale the raw literal"
    assert carries(reformatted, SENTENCE)


# --------------------------------------------------------------------------------------
# What the anchor must REFUSE — every one of these is a real edit, not a reflow
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("edited,why", [
    ("A scope you could not compute must silently narrow the gate.", "a word deleted"),
    ("A scope you could not compute may never silently narrow the gate.", "a word changed"),
    ("A scope you could not compute must never silently narrow the `gate`.", "backticks added"),
    ("A scope you could not compute must never silently narrow the gate!", "punctuation changed"),
    ("A scope you could not compute must never silently widen the gate.", "the claim inverted"),
])
def test_the_anchor_refuses_a_change_to_the_WORDS(edited, why):
    assert not carries(edited, SENTENCE), f"{why}: a real edit read as a reflow"


def test_a_blank_line_is_not_absorbed():
    """`\\s+` would match a blank line, which lets an anchor span a paragraph boundary and
    join two unrelated sentences. A re-wrap never inserts one — that would split the
    paragraph and change the rendering — so refusing it costs no tolerance."""
    assert not carries("A scope you could not compute\n\nmust never silently narrow the gate.",
                       SENTENCE)


def test_a_blockquote_prefix_is_not_absorbed():
    """A DECLARED LIMIT, pinned so that widening it has to be deliberate.

    Reflowing inside a blockquote inserts `\\n> `, so the anchor goes red on a reformat
    that changed no meaning — a real cost. It is paid on purpose: the tolerance that
    would absorb it is "a `>` after a line break", and that same tolerance lets an anchor
    match a rule someone has WRAPPED in a blockquote, which is Phase 167's neutered-rule
    survivor reintroduced through the matcher. No site measured by `Q-495` needs it.
    """
    assert not carries("> A scope you could not compute\n> must never silently narrow the gate.",
                       SENTENCE)


def test_a_list_marker_is_not_folded():
    """`4.` -> `*` drops an ordinal from an ordered procedure, which is an edit. An anchor
    that spans a list marker wants narrowing to the sentence, not a fuzzier marker class —
    that is the fix applied at `Q-495`'s third control site."""
    assert carries("4. **If the diff is doc-only**", "4. **If the diff is doc-only**")
    assert not carries("* **If the diff is doc-only**", "4. **If the diff is doc-only**")


# --------------------------------------------------------------------------------------
# locate() and swap()
# --------------------------------------------------------------------------------------

def test_locate_returns_a_span_in_the_ORIGINAL_text():
    """The property `_flat` cannot provide, and the reason mutation tables stayed raw."""
    doc = "before\nA scope you could not compute\nmust never silently narrow the gate.\nafter"
    m = locate(doc, SENTENCE)
    assert doc[m.start():m.end()].split() == SENTENCE.split()
    assert doc[:m.start()].endswith("before\n")


def test_locate_raises_AssertionError_naming_the_phrase_not_a_bare_ValueError():
    """`str.index` raises ValueError with nothing but "substring not found", which is what
    several of these sites did — and it makes a staled anchor read as a broken test."""
    with pytest.raises(AssertionError) as exc:
        locate("nothing like it here", SENTENCE)
    assert "narrow the gate" in str(exc.value)


def test_swap_edits_the_reformatted_text_in_the_right_place():
    doc = "keep\nA scope you could not\ncompute must never silently narrow the gate.\nkeep too"
    out = swap(doc, SENTENCE, "REPLACED")
    assert out == "keep\nREPLACED\nkeep too"


def test_an_ambiguous_anchor_is_REFUSED_rather_than_resolved_by_position():
    """`str.replace(old, new, 1)` silently takes the first of however many sites match,
    and tolerance ENLARGES that set — so the quiet failure mode this closes is a mutation
    named for one step landing on another and still reporting a kill.

    Measured on the shipped file: `"   " + SCOPE_COMMAND` matches ONE site raw and TWO
    tolerantly, because the three-space indent that had been separating 4a-post's copy of
    the command from Step 3's is exactly the whitespace a re-indent moves.
    """
    doc = f"{SENTENCE} and again {SENTENCE}"
    with pytest.raises(AssertionError) as exc:
        swap(doc, SENTENCE, "X")
    assert "AMBIGUOUS" in str(exc.value) and "2 sites" in str(exc.value)


def test_after_names_the_region_that_disambiguates():
    doc = f"## One\n{SENTENCE}\n\n## Two\n{SENTENCE}\n"
    assert swap(doc, SENTENCE, "X", after="## Two") == f"## One\n{SENTENCE}\n\n## Two\nX\n"


def test_after_narrows_the_START_only_and_says_so_when_that_is_not_enough():
    """A declared limit. `after=` moves where the search begins, so it isolates a site
    that is the LAST match, not one in the middle — `after="## One"` here still sees both.
    It is not widened to a start/end pair because no site measured by `Q-495` needs one,
    and Phase 291's round deleted a helper arm for having no caller. The refusal is loud,
    so the day a site does need it, it asks rather than silently taking the first."""
    doc = f"## One\n{SENTENCE}\n\n## Two\n{SENTENCE}\n"
    with pytest.raises(AssertionError) as exc:
        swap(doc, SENTENCE, "X", after="## One")
    assert "AMBIGUOUS" in str(exc.value)


def test_a_boundary_whitespace_run_does_not_eat_the_newline_before_it():
    """The defect this found in its own first cut: `"   " + COMMAND` anchors a fenced
    command by its indent, a leading soft-break also matched the newline ENDING the fence
    opener, and `swap()` replacing that span deleted the newline — joining the command
    onto the ``` line and corrupting the fence the anchor existed to pin. It turned two of
    `test_review_close_merged_tree_gate.py`'s legitimate-rewrite controls red, reporting
    the scope command "missing, corrupted, or not in a bash fence", which it then was."""
    doc = "```bash\n   git status --porcelain\n```\n"
    out = swap(doc, "   git status --porcelain", "   git status --short")
    assert out == "```bash\n   git status --short\n```\n"
    assert out.count("\n") == doc.count("\n"), "a line break was consumed by the anchor"


def test_swap_agrees_with_str_replace_when_nothing_has_been_reformatted():
    doc = f"lead-in {SENTENCE} tail"
    assert swap(doc, SENTENCE, "X") == doc.replace(SENTENCE, "X", 1)


def test_swap_fails_loud_when_the_source_text_is_really_gone():
    with pytest.raises(AssertionError):
        swap("A scope you could not compute must never WIDEN the gate.", SENTENCE, "X")


def test_an_empty_phrase_is_refused_rather_than_matching_everything():
    for empty in ("", "   ", "\n\t "):
        with pytest.raises(ValueError):
            anchor(empty)


def test_regex_metacharacters_in_the_phrase_are_literal():
    """These anchors are full of backticks, `**`, `(` and `.` — a phrase is text, not a
    pattern, and must never be read as one."""
    doc = "run `git diff --name-only origin/<default branch>...HEAD` (a three-dot diff)"
    assert carries(doc, "origin/<default branch>...HEAD` (a three-dot diff)")
    assert not carries("run git diff XXXHEAD (a three-dot diff)",
                       "origin/<default branch>...HEAD` (a three-dot diff)")


# --------------------------------------------------------------------------------------
# The instrument itself — rewrapped()
# --------------------------------------------------------------------------------------

def test_rewrapped_moves_only_whitespace_on_the_shipped_file():
    """The invariant is asserted inside `rewrapped()`, so this pins that the assertion is
    reached on a real document rather than only on fixtures."""
    src = SKILL.read_text(encoding="utf-8")
    out = rewrapped(src)
    assert out != src
    assert re.sub(r"\s+", " ", src) == re.sub(r"\s+", " ", out)


@pytest.mark.parametrize("block,why", [
    ("```bash\ngit status --porcelain\ngit diff --name-only\n```", "a fenced block"),
    ("~~~\nnot a backtick fence\nwith two lines\n~~~", "a tilde fence"),
    ("## Step 4: Merge & Land on Main", "a heading"),
    ("| a | b |\n| - | - |\n| 1 | 2 |", "a table"),
    ("> a quoted note that runs on\n> across two lines", "a blockquote"),
    ("<!--\na comment with words\n-->", "an HTML comment"),
    ("    an indented code line\n    and a second one", "indented code"),
])
def test_rewrapped_leaves_non_prose_blocks_byte_identical(block, why):
    doc = f"Some prose before it.\n\n{block}\n\nSome prose after it.\n"
    out = rewrapped(doc)
    assert block in out, f"{why} was reformatted; only prose may move"


def test_rewrapped_actually_reformats_prose():
    doc = "One two three four five six seven.\n"
    assert rewrapped(doc).count("\n") > doc.count("\n")


def test_rewrapped_never_lets_a_word_open_a_new_block():
    """At width 1 every word starts a line, so a word that is also a block opener would
    silently become a list item or a heading — a rendering change, not a reflow."""
    doc = "the flag - a dash - and 1. a number and > a caret and # a hash here\n"
    out = rewrapped(doc)
    for line in out.split("\n"):
        assert not re.match(r"^(?:[-+*]\s|\d{1,9}[.)]\s|>|#{1,6}\s)", line), line


def test_rewrapped_does_not_split_an_angle_bracket_link_destination():
    """The one inline construct a whitespace re-wrap can actually break.

    `[text](<a b.md>)` is legal CommonMark, its destination may carry spaces, and a line
    break inside it is not allowed — so this is the case the protection exists for. The
    first cut protected `](url)` and autolinks instead, both of which exclude whitespace
    by construction and therefore can never be split; the author-side battery found that
    by mutating the protection away and watching nothing fail.
    """
    doc = "see [the workflow](<./docs/a file.md>) for the whole procedure here\n"
    assert "](<./docs/a file.md>)" in rewrapped(doc)
    # and the ordinary form still survives, because it has no whitespace to split on
    assert "](./docs/WORKFLOW.md)" in rewrapped("see [it](./docs/WORKFLOW.md) here now\n")


def test_rewrapped_fails_loud_if_its_transform_ever_changes_more_than_whitespace():
    """The invariant must FIRE, not merely be present. Mutating the assertion away left
    every other test green, because they all check the property from outside on input the
    transform handles correctly — so nothing exercised the assertion itself."""
    import _prose_guard_helpers as H
    real = H._kinds
    try:
        # a classifier that calls a fenced line prose makes the transform eat a delimiter
        H._kinds = lambda lines: [("prose", "") for _ in lines]
        with pytest.raises(AssertionError, match="more than whitespace"):
            H.rewrapped("intro line\n\n```bash\ngit status\n```\n")
    finally:
        H._kinds = real


def test_locate_says_NOT_FOUND_and_AMBIGUOUS_differently():
    """Both raise AssertionError and both name the phrase, so a test that only checks the
    phrase cannot tell them apart — which is how mutating the not-found arm away survived
    this module's first battery: the ambiguity arm below it raised instead, with a message
    that still contained the phrase."""
    with pytest.raises(AssertionError) as missing:
        locate("nothing like it here", SENTENCE)
    with pytest.raises(AssertionError) as ambiguous:
        locate(f"{SENTENCE} and again {SENTENCE}", SENTENCE)
    assert "not found" in str(missing.value) and "AMBIGUOUS" not in str(missing.value)
    assert "AMBIGUOUS" in str(ambiguous.value) and "not found" not in str(ambiguous.value)


def test_rewrapped_is_the_enumerator_it_claims_to_be():
    """Anti-vacuity: on the shipped file it must stale raw literals in real numbers, or
    every survival guard built on it passes for the wrong reason."""
    src = SKILL.read_text(encoding="utf-8")
    out = rewrapped(src)
    sample = [ln.strip() for ln in src.split("\n")
              if len(ln.strip()) > 60 and " " in ln.strip() and not ln.startswith((" ", "`", "|", ">", "#"))]
    assert len(sample) > 100, "the shipped file no longer has enough prose to measure"
    staled = [s for s in sample if s not in out]
    assert len(staled) > len(sample) * 0.5, (
        f"only {len(staled)} of {len(sample)} raw prose literals went stale — the "
        "instrument is not reformatting enough to enumerate anything"
    )
    assert all(carries(out, s) for s in staled), (
        "a tolerant anchor failed on text where only whitespace moved"
    )


# --------------------------------------------------------------------------------------
# Leading and trailing whitespace in the PHRASE is a requirement, not decoration
# --------------------------------------------------------------------------------------

def test_leading_whitespace_in_the_phrase_stays_a_requirement():
    """Several mutation anchors are `"   " + COMMAND` and the indentation is doing work:
    it targets the FENCED occurrence rather than a prose cross-reference to the same
    command, and `_sub` replaces the first occurrence it finds. Stripping the phrase
    would have slid those mutations onto the prose mention — which is the failure the
    module's own `R1` comment records having been bitten by once already."""
    fenced = "Run it before Step 4b.\n\n```bash\n   git status --porcelain\n```\n"
    assert carries(fenced, "   git status --porcelain")
    # the same command named inline, with no whitespace in front of it, must NOT match
    assert not carries("Run `git status --porcelain` first.", "   git status --porcelain")


def test_leading_whitespace_no_longer_pins_the_WIDTH_of_the_indent():
    """The half that has to move: which whitespace, not whether there is any."""
    assert carries("```bash\n     git status --porcelain\n```", "   git status --porcelain")
    assert carries("```bash\n\tgit status --porcelain\n```", "   git status --porcelain")


def test_trailing_whitespace_in_the_phrase_stays_a_requirement():
    assert carries("### 4b. Close Merged Batches\n\ntext", "### 4b. Close Merged Batches\n")
    assert not carries("### 4b. Close Merged Batches!", "### 4b. Close Merged Batches\n")


# --------------------------------------------------------------------------------------
# The hostile corpus (author-side rule 4)
#
# `anchor()` and `rewrapped()` are a predicate and a state machine applied to markdown
# that other writers produce, which is exactly the trigger. Phase 291's round reached the
# Phase 167 survivor through `~~~`, through a 3-backtick line "closing" a 4-backtick
# block, and through `<details>` nested in itself — three shapes inside the fix written to
# close that survivor, past an author battery that had attacked the fence pattern twice.
# None of those is hypothetical here: `rewrapped()` decides what is prose, and prose is
# the only thing it is allowed to touch, so every one of them is a way to reformat a code
# block by mistake.
# --------------------------------------------------------------------------------------

def test_an_UNTERMINATED_fence_runs_to_EOF_and_nothing_after_it_is_reformatted():
    """An unclosed fence really does render everything after it as code. Treating the
    remainder as prose would re-wrap a code block — the state machine's worst answer,
    given silently. `review-close/SKILL.md` is balanced today; this is the shape nobody
    has met yet."""
    doc = "Prose before it.\n\n```bash\ngit status --porcelain\n\nthis looks like prose but is code\n"
    out = rewrapped(doc)
    tail = doc[doc.index("```bash"):]
    assert out.endswith(tail), "text after an unclosed fence was re-wrapped"


def test_a_tilde_fence_is_a_fence():
    """`~~~` is a legal CommonMark fence, and Phase 291's round got the neutered-rule
    survivor back through precisely this gap in a sibling canonicaliser."""
    doc = "Lead in here.\n\n~~~\nnot prose at all, several words wide\n~~~\n\nTrailing prose here.\n"
    assert "not prose at all, several words wide\n" in rewrapped(doc)


def test_a_shorter_delimiter_does_not_close_a_longer_fence():
    """CommonMark: a closer must be at least as long as its opener. Taking the 3-backtick
    line as the close leaves the rest of the block read as prose."""
    doc = "Intro line.\n\n````\ninside the block\n```\nstill inside the block\n````\n\nOut here now.\n"
    out = rewrapped(doc)
    assert "still inside the block\n" in out
    assert "inside the block\n" in out


def test_a_backtick_opener_whose_info_string_holds_a_backtick_is_not_a_fence():
    """CommonMark forbids it, and reading it as a fence would silently swallow the
    document from there on."""
    doc = "```bash `inline` \nordinary prose that must still be re-wrapped here\n"
    assert rewrapped(doc).count("\n") > doc.count("\n")


def test_an_html_comment_and_a_details_block_are_left_alone():
    for block in ("<!--\na commented-out rule with several words\n-->",
                  "<details>\n<summary>open me</summary>\nhidden text with several words\n</details>"):
        doc = f"Before it here.\n\n{block}\n\nAfter it here.\n"
        assert block in rewrapped(doc), block[:20]


def test_a_paragraph_abutting_a_fence_with_no_blank_line_is_still_bounded_by_it():
    doc = "some prose words right here\n```bash\ngit status\n```\nmore prose words right here\n"
    out = rewrapped(doc)
    assert "```bash\ngit status\n```\n" in out


def test_rewrapped_is_idempotent():
    """At width 1 there is nothing left to move, so a second pass must be a no-op. A
    transform that keeps changing its own output is not a normal form and the survival
    guards built on it would be comparing against a moving target."""
    src = SKILL.read_text(encoding="utf-8")
    once = rewrapped(src)
    assert rewrapped(once) == once


@pytest.mark.parametrize("doc", ["", "\n", "   ", "no trailing newline", "\n\n\n"])
def test_rewrapped_survives_degenerate_documents(doc):
    out = rewrapped(doc)
    assert re.sub(r"\s+", " ", out) == re.sub(r"\s+", " ", doc)


def test_a_phrase_that_appears_in_BOTH_a_fence_and_prose_is_ambiguous_not_silently_first():
    """Rule 4's first case — the token in a context the rule did not intend. This is the
    shape that bit for real: the scope command appears in Step 3's fence and again in
    4a-post's, and the indent that told them apart is what a re-indent moves."""
    doc = "```bash\ngit diff --name-only origin/main...HEAD\n```\n\nLater, run `git diff --name-only origin/main...HEAD` again.\n"
    with pytest.raises(AssertionError) as exc:
        locate(doc, "git diff --name-only origin/main...HEAD")
    assert "AMBIGUOUS" in str(exc.value)


def test_a_non_breaking_space_is_absorbed_like_any_other_whitespace():
    """Pinned as behaviour rather than left as an accident. `\\s` is Unicode-aware, so a
    NBSP swapped in for a space matches. That is a widening — the two characters render
    differently — but it is the harmless direction (an anchor keeps matching text a human
    reads the same), and `review-close/SKILL.md` contains none today."""
    assert carries("gate nothing and skip nothing", "gate nothing and skip nothing")


def test_a_blank_line_CLOSES_an_html_block_so_later_prose_is_still_prose():
    """The first cut of the HTML-block fix latched `in_html` on permanently, because the
    continuation arm was tested before the blank-line arm — so every paragraph after the
    document's first `<details>` silently stopped being prose. `review-close/SKILL.md`
    has no `<details>` today, which is exactly why this had to be a fixture."""
    doc = ("Before it here.\n\n<details>\n<summary>open me</summary>\nhidden words here\n"
           "</details>\n\nAfter this the prose must still be re-wrapped.\n")
    out = rewrapped(doc)
    assert "\n<details>\n<summary>open me</summary>\nhidden words here\n</details>\n" in out
    assert "After\nthis\nthe\nprose" in out, "prose after the HTML block was not re-wrapped"


# --------------------------------------------------------------------------------------
# `any_bullet` — the list-item anchor
# --------------------------------------------------------------------------------------

BULLET = "- `Bash(git add:*)`"


def test_any_bullet_absorbs_the_marker_character():
    """CommonMark's three unordered markers are interchangeable, so a formatter that
    normalises one to another changes no rendering. Sixteen guards across eight modules
    pinned `- ` and reddened on a uniform swap — among them a guard about SPAWN
    PARAMETERS and one about a REQUIRED permission rule, neither about bullets."""
    for marker in ("-", "+", "*"):
        assert carries(f"preamble\n{marker} `Bash(git add:*)`\n", BULLET, any_bullet=True)


def test_any_bullet_still_requires_a_LIST_ITEM_and_tightens_it_to_a_line_start():
    """Folding WHICH character is not the same as dropping the requirement. The plain `in`
    these sites used could be satisfied mid-sentence; this cannot."""
    assert not carries("see the rule - `Bash(git add:*)` inline", BULLET, any_bullet=True)
    assert not carries("1. `Bash(git add:*)`", BULLET, any_bullet=True), "ordered marker"
    assert not carries("`Bash(git add:*)`", BULLET, any_bullet=True), "no marker at all"


def test_any_bullet_still_fails_when_the_bullet_is_CHANGED_or_gone():
    assert not carries("- `Bash(git rm:*)`", BULLET, any_bullet=True)
    assert not carries("- `Bash(git add)`", BULLET, any_bullet=True)
    assert not carries("preamble only, no list here at all", BULLET, any_bullet=True)


def test_any_bullet_absorbs_a_rewrap_of_the_item_body():
    assert carries("* `Bash(git\n  add:*)`", BULLET, any_bullet=True)


def test_any_bullet_refuses_a_phrase_that_opens_no_list_item():
    """Loud rather than silently ignoring the flag — a caller passing it has asserted the
    phrase is a list item, and if it is not, the anchor they get is not the one they think."""
    with pytest.raises(ValueError):
        carries("anything", "no marker in front of this", any_bullet=True)


def test_any_bullet_holds_the_token_separator_parity():
    """A regression pin for this phase's own first cut: dropping the marker token alone
    shifted every separator into a token slot, and the pattern stopped matching ANYTHING —
    silently, because a guard that finds nothing looks exactly like a guard whose subject
    was deleted."""
    assert carries("- one two three four", "- one two three four", any_bullet=True)
    assert carries("-   one   two", "- one two", any_bullet=True)


def test_a_whitespace_only_phrase_is_refused_by_anchor_and_kept_literal_by_callers():
    """`"\\n\\n"` is a real end marker — "the next blank line" — and several slices use it.
    Tolerance is meaningless for a phrase that IS whitespace, so `anchor()` refuses it and
    the callers that accept literal anchors fall back to a plain find. Found by running
    the conversion: a parametrized slice in `test_fix_in_branch_tier.py` passes exactly
    that, and the first cut turned it into a `ValueError` from inside the helper."""
    import _reversal
    with pytest.raises(ValueError):
        anchor("\n\n")
    doc = "opening line\n\nsecond paragraph"
    assert _reversal.slice_between(doc, "opening", "\n\n", "probe") == "opening line"


def test_a_TRAILING_space_in_the_phrase_absorbs_a_line_break():
    """The asymmetry with the leading case, and why it is not symmetric.

    A trailing space is the ordinary gap before the next word, and a re-wrap turns
    exactly that gap into a line break. Requiring horizontal whitespace there put the
    defect back: a mutation anchored on a sentence ending `cause.** ` stopped matching
    the moment the sentence after it moved down a line. A LEADING horizontal run means
    something else — indentation — and stays in kind, because the newline it must not
    consume is the fence opener's, which is not part of the phrase at all.
    """
    assert carries("the likelier cause.**\nBefore anything else", "cause.** ")
    assert carries("the likelier cause.** Before anything else", "cause.** ")
    # still a requirement that SOMETHING separates it from the next word
    assert not carries("the likelier cause.**Before", "cause.** ")


def test_the_trailing_boundary_does_not_swallow_the_NEXT_line_s_indentation():
    """The leading-boundary corruption arriving from the other end, found by this phase's
    round on a live mutation row.

    A phrase ending in a newline used to match that newline PLUS whatever indentation
    began the following line, so `swap()` replacing the span de-indented what came after
    it — in the real case, a fence closer. The trailing boundary is therefore matched
    minimally: one line break, or one space, and never the indentation beyond it.
    """
    doc = "```bash\n  git reset --hard origin/main\n  ```\n"
    out = swap(doc, "  git reset --hard origin/main\n", "  git status\n")
    assert out == "```bash\n  git status\n  ```\n", out
    assert "\n  ```" in out, "the fence closer lost its indentation"


def test_the_trailing_boundary_still_absorbs_a_line_break_for_a_space():
    """It must stay minimal WITHOUT losing the tolerance it exists for."""
    assert carries("the likelier cause.**\nBefore anything else", "cause.** ")
    assert carries("the likelier cause.** Before anything else", "cause.** ")
    assert not carries("the likelier cause.**Before", "cause.** ")


def test_a_BAN_must_stay_broader_than_a_REQUIREMENT():
    """`any_bullet` is right for a requirement and wrong for a ban.

    It pins the item to a line start and does not absorb `>`, so applying it to a
    prohibition stops the prohibition seeing a banned rule parked in a blockquote or
    mid-sentence — both of which the plain literal it replaced did catch. Phase 292's
    round found exactly that in three bans in `test_review_close_pr_policy.py`.
    """
    banned = "- `Bash(git add PROJECT_STATUS.md)`"
    for hiding_place in ("- `Bash(git add PROJECT_STATUS.md)`",
                         "> - `Bash(git add PROJECT_STATUS.md)`",
                         "see - `Bash(git add PROJECT_STATUS.md)` here",
                         "- `Bash(git add\n  PROJECT_STATUS.md)`"):
        assert carries(hiding_place, banned), f"a ban would miss: {hiding_place!r}"
    # and the narrow form really is narrower — this is why it is not used for bans
    assert not carries("> - `Bash(git add PROJECT_STATUS.md)`", banned, any_bullet=True)


@pytest.mark.parametrize("phrase,doc", [
    ("- `Bash(git add:*)`",     "preamble\n- `Bash(git add:*)`\n"),
    ("  - `Bash(git add:*)`",   "preamble\n  - `Bash(git add:*)`\n"),
    ("    - `Bash(git add:*)`", "preamble\n    - `Bash(git add:*)`\n"),
])
def test_any_bullet_accepts_an_INDENTED_list_item(phrase, doc):
    """These skills are full of nested bullets, and `any_bullet` refused every one of them
    with "the phrase opens no list item" — `re.split` puts the whitespace run at index 1
    and the marker at index 2, and the code took index 1. No fixture caught it because
    every `any_bullet` fixture was flush-left. Found by this phase's round."""
    assert carries(doc, phrase, any_bullet=True)


def test_any_bullet_still_refuses_a_phrase_with_indentation_but_no_marker():
    with pytest.raises(ValueError):
        carries("anything", "  no marker here at all", any_bullet=True)
