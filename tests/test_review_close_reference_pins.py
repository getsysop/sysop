"""The runner/reference split's authority mechanism, over `/review-close` Step 3.

Built by Phase 275 to the shape specified in `tools/CONTEXT_THINNING_SPEC.md`
(maintainer-side; never ships). Four layers, and the roster check that keeps the
declared population from shrinking as a side effect:

  (a) a whole-block verbatim pin over the step, canonicalised
  (b) contradiction screens, scoped to the step's own section
  (c) per-rule subject x predicate class predicates that survive a regeneration
  (d) a fail-closed extractor, with a test that it fails closed

The canon helpers are IMPORTED from `test_adversarial_review_gate` rather than
restated. A second copy would drift from the one whose semantics this module's
whole fence analysis depends on, and the spec's § 3.5 fork was about exactly that.

**`Q-457`, the fork, is settled here (Phase 291) and the answer is `_tagged`.**
`_prose_only` renders by DELETION, which is right for a presence check over
`_shared/adversarial-review.md` — a rule wrapped in a fence there is a quoted
example and should read as gone. It is wrong for a pin over THIS file, where
fenced blocks are the prescribed commands and blockquotes are notes to the
operator: measured at the filing, `1a` is 70.6% fenced and `4c` is 35.2%
blockquote with no column-0 fences at all, and two rules that change a verdict sat
in `REFERENCE.md` § Blocked purely because a pin could not see into a fence.
`_tagged` keeps every character and brackets the wrapper instead, so a rule inside
one is pinned while moving a rule INTO one still reddens the pin. The two ways out
the filing listed — drop the fence strip, or handle blockquotes separately — were
both refused by measurement before this was built: with the strip dropped, a
wrapper whose closer lands past the slice's END marker leaves the slice
byte-identical and the pin GREEN over a fully commented-out step. That is Phase
167's survivor, and `_anchor_is_wrapped` is what closes it.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).resolve().parent))

from _prose_guard_helpers import anchor  # noqa: E402
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "core/skills/review-close/SKILL.md"
REFERENCE = REPO_ROOT / "core/skills/review-close/REFERENCE.md"

sys.path.insert(0, str(REPO_ROOT))
from tests.test_adversarial_review_gate import (  # noqa: E402
    NEUTERING_TAGS,
    TAG_CLASSES,
    _anchor_is_wrapped,
    _block_canon,
    _first_divergence,
    _flat,
    _indent_neutered,
    _prose_only,
    _tagged,
    _unhandled_nesting,
    _without,
)

# ---------------------------------------------------------------------------------------
# Layer (d) — the extractor, fails closed on either marker
# ---------------------------------------------------------------------------------------
#
# Fails closed because the alternative is fail-OPEN widening: a renamed end marker makes a
# slicer return the rest of the file, and a pin compared against an over-wide slice either
# fails confusingly or — worse — satisfies a required-pattern check out of the extra text.
# That, not deletion, is what this layer uniquely owns: deletion is already caught by the
# required-pattern checks below, which fire on the empty string.

STEP_3_START = "## Step 3: Run Verification"
STEP_3_END = "## Step 3c"  # id only: renaming 3c's TITLE is a legal edit to another step


def _step_3_slice(text: str) -> str:
    """Step 3's section, wrapper-TAGGED. Empty if either marker is gone or neutered.

    Tagged rather than stripped (`Q-457`): the step's prescribed commands and its operator
    notes are the operative content here, so they belong inside the pin rather than deleted
    before it compares. See the module docstring.

    **The anchor check is the half a no-strip policy cannot have.** Wrap the whole step in
    `<!-- -->` or a fence with the closer placed PAST the `## Step 3c` marker and the text
    between the two anchors is byte-identical — measured on this slicer and on
    `adversarial-review.md`'s before this was written, and GREEN both times without it. With
    it, the anchor itself lands inside an open region and the slice fails closed, which is
    the same answer stripping gave and the one the pin still needs.
    """
    tagged = _tagged(text)
    i = tagged.find(STEP_3_START)
    if i == -1 or _anchor_is_wrapped(tagged, i):
        return ""
    j = tagged.find(STEP_3_END, i + len(STEP_3_START))
    if j == -1 or _anchor_is_wrapped(tagged, j):
        return ""
    # Markdown's undelimited code form, judged over THIS step rather than the file: indenting
    # one step barely moves a whole-file ratio. See `_indent_neutered`.
    if _indent_neutered(tagged[i:j]):
        return ""
    return tagged[i:j]


def _step_3_raw_slice(text: str) -> str:
    """Step 3's section as it ships — no tags, no folds — for the contradiction screens.

    **This split used to be load-bearing and is no longer, and the reason is worth stating
    rather than leaving the old sentence in place.** Until Phase 291 the pin ran over
    prose-only text, so a contradiction written into a shell comment inside a prescribed
    command block reached no screen; the author-side battery planted exactly that and it
    survived. `_tagged` keeps that text, so the screens would now see it either way.

    What keeps the raw slice is narrower and mechanical: `SCREEN_ALLOWED` is pinned to whole
    shipped SENTENCES and `_sentence_bounds` splits on `". "`, so a `[[fence]]` marker landing
    mid-sentence would silently change which text an allow-list entry has to match. The
    screens read the bytes a runner reads; the pin reads the rendering.
    """
    i = text.find(STEP_3_START)
    if i == -1:
        return ""
    j = text.find(STEP_3_END, i + len(STEP_3_START))
    if j == -1:
        return ""
    return text[i:j]


def _step_3_raw_section() -> str:
    section = _step_3_raw_slice(SKILL.read_text(encoding="utf-8"))
    assert section, "Step 3's raw section does not resolve; the slicer fails closed"
    return section


def _step_3_section() -> str:
    section = _step_3_slice(SKILL.read_text(encoding="utf-8"))
    assert section, (
        "Step 3's section does not resolve — either the step is gone, or one of "
        f"{STEP_3_START!r} / {STEP_3_END!r} was renamed and this slicer needs revisiting. "
        "It fails closed on purpose; do not widen it to 'rest of file'."
    )
    return section


def test_the_step_3_slicer_fails_closed():
    """Either marker renamed must yield nothing, not the rest of the file."""
    text = SKILL.read_text(encoding="utf-8")
    assert _step_3_slice(text)
    assert _step_3_slice(text.replace(STEP_3_START, "## Step 3: Verify")) == ""
    assert _step_3_slice(text.replace("## Step 3c", "## Step 3x")) == ""


def test_the_slicer_does_not_reach_past_its_own_step():
    """The window stops at Step 3c. A pin that swallowed 3c would redden on 3c's edits."""
    section = _step_3_section()
    assert "Manual Smoke Gate" not in section
    assert "Prepare Worktrees for Merge" not in section


# ---------------------------------------------------------------------------------------
# The roster — parsed from the SHIPPED file, pinned here as a set
# ---------------------------------------------------------------------------------------
#
# `DECLARED_IDS` is the pinned half of a three-way identity: the roster bullets in
# REFERENCE.md, the `## <id>` sections in REFERENCE.md, and this set must agree. That is
# the Phase 262 partition shape rather than a count — a widened count says nothing about
# WHICH rule left, and Phase 163's round showed a count can be widened silently and stay
# green. Removing a rule here is an edit to a pinned constant, so it cannot happen as a
# side effect of re-approving something else.

# `RC-3-7` and `RC-3-8` are the two rules `REFERENCE.md` § Blocked used to carry: both meet
# the § 2.2 bar, both change a verdict, and both live in a shell comment or a command inside
# Step 3's fenced block, so until `Q-457` was settled neither could be declared under a pin
# that deleted fenced text before comparing. They are the deliverable's own evidence — the
# fork is only closed if the rules it blocked can now be declared.
DECLARED_IDS = frozenset({
    "RC-3-1", "RC-3-2", "RC-3-3", "RC-3-4", "RC-3-5", "RC-3-6", "RC-3-7", "RC-3-8",
})

_ROSTER_BULLET = re.compile(r"^- `(RC-[0-9a-z-]+)` — ", re.M)
_SECTION_HEADING = re.compile(r"^## `(RC-[0-9a-z-]+)`\s*$", re.M)


def _roster_ids() -> set[str]:
    return set(_ROSTER_BULLET.findall(REFERENCE.read_text(encoding="utf-8")))


def _section_body(rule_id: str) -> str:
    """One rule's REFERENCE.md section body, so an empty section cannot pass as coverage."""
    text = REFERENCE.read_text(encoding="utf-8")
    m = re.search(rf"^## `{re.escape(rule_id)}`\s*$", text, re.M)
    if not m:
        return ""
    nxt = re.search(r"^## ", text[m.end():], re.M)
    return text[m.end(): m.end() + (nxt.start() if nxt else len(text))].strip()


def _section_ids() -> set[str]:
    return set(_SECTION_HEADING.findall(REFERENCE.read_text(encoding="utf-8")))


# Subject patterns: what ties a rule id to runner text without a span extractor. Each must
# match inside the pinned block, which is roster check (a).
SUBJECT_PATTERNS: dict[str, str] = {
    "RC-3-1": r"nothing here may be reported as having verified a branch",
    "RC-3-2": r"A scope you could not compute must never silently narrow the gate",
    "RC-3-3": r"A surface absent from the changed-file list is `skipped`, not `failed`",
    "RC-3-4": r'"The diff" is this pass\'s changed-file list, never the run\'s',
    "RC-3-5": r"The licence for this skip is the pass, not the diff",
    "RC-3-6": r"The item-5 stop is about the run, not about this pass",
    # Both of these resolve INSIDE the fenced command block, which is the whole point: under
    # `_prose_only` neither matched anything, and `REFERENCE.md` § Blocked said so.
    "RC-3-7": r"Three dots, always — two would\s+#?\s*render everything the base gained",
    "RC-3-8": r'git diff --name-only origin/<default branch>\.\.\.HEAD\s+\\\s+\|\| echo "NO_ORIGIN_MAIN"',
}

# The TEXT each subject pattern must resolve to, pinned beside the pattern that finds it.
#
# This phase's round retired `RC-3-7` from the runner with the suite green, in three edits:
# re-point its subject pattern at a different sentence of the same fenced block (51 literal
# characters, unique — so `test_every_subject_pattern_is_specific` passed), delete the rule,
# regenerate the block pin by the documented recipe. The roster, the `REFERENCE.md` section,
# `DECLARED_IDS` and the screen were all untouched, so nothing else noticed. **A subject
# pattern is a rule's only deletion detector, and re-pointing one looks like a pattern tweak
# rather than a retirement.**
#
# Pinning what the pattern must MATCH closes that the only way prose can be closed: the
# retirement now has to replace the rule's own words in a constant, so the diff says which
# rule left instead of showing a regex being adjusted. It does not make retirement
# impossible — `REFERENCE.md` § Declared limits says so, and now says how many edits it takes
# — it makes it legible.
SUBJECT_QUOTES: dict[str, str] = {
    "RC-3-1": "nothing here may be reported as having verified a branch",
    "RC-3-2": "A scope you could not compute must never silently narrow the gate",
    "RC-3-3": "A surface absent from the changed-file list is `skipped`, not `failed`",
    "RC-3-4": '"The diff" is this pass\'s changed-file list, never the run\'s',
    "RC-3-5": "The licence for this skip is the pass, not the diff",
    "RC-3-6": "The item-5 stop is about the run, not about this pass",
    "RC-3-7": "Three dots, always \u2014 two would # render everything the base gained",
    "RC-3-8": 'git diff --name-only origin/<default branch>...HEAD \\ || echo "NO_ORIGIN_MAIN"',
}


# ---------------------------------------------------------------------------------------
# Layer (c) — subject x predicate classes, per rule
# ---------------------------------------------------------------------------------------
#
# Composed rather than literal, because a first draft of the shipped exemplar used five
# literal patterns and a reviewer walked every one of them with an ordinary rewording, all
# green after a sanctioned regeneration. The subject half names WHICH rule is being
# demoted; the predicate half names the DEMOTION CLASS. Both halves are needed: a demotion
# with no subject is a sentence about something else, and a subject with no demotion is the
# rule itself.

_S3 = r"(?:Step 3|this pass|the pre-merge pass)"
_POST = r"(?:4a-post|the post-merge (?:pass|gate))"

# Each pattern carries a named `dem` group around the DEMOTION ITSELF. A screen that
# ignores negation is over-strict in the direction that hides: the shipped step already
# says "`4a-post` therefore does not inherit this skip" and "What does *not* license it is
# the idea that a doc-only diff is harmless" — both of which a naive screen flags, which
# would redden the step for the sentences that state the rules. So a hit requires the
# demotion to be UN-negated within its own sentence.

FORBIDDEN: list[tuple[str, str, str]] = [
    # (rule id it defends, pattern with a `dem` group, why this rewording is a demotion)
    (
        "RC-3-1",
        rf"{_S3}[^.]{{0,90}}(?P<dem>\b(?:verifies|validates|confirms)\s+"
        r"(?:the\s+|each\s+|every\s+)?(?:branch|branches|work)\b)",
        "promotes the pre-merge pass to a verdict on the work — the exact reading RC-3-1 "
        "forbids, and the one the step's output makes tempting because it runs the same "
        "command list 4a-post does.",
    ),
    (
        "RC-3-1",
        rf"(?:green|passing|success)[^.]{{0,60}}\bat {_S3}\b[^.]{{0,60}}"
        r"(?P<dem>\bmeans\b[^.]{0,60}(?:verified|safe to merge|ready))",
        "restates the verdict promotion as an inference about what green MEANS, leaving "
        "the rule's own sentence intact while the conclusion it forbids is drawn next to "
        "it.",
    ),
    (
        "RC-3-2",
        r"(?:NO_ORIGIN_MAIN|uncomputable|cannot be computed|could not be computed)"
        r"[^.]{0,90}(?P<dem>\b(?:treat|treated|treats) (?:it |the list )?as (?:an? )?empty)",
        "turns a scope that FAILED to compute into a scope that computed to nothing, which "
        "fires every narrowing at maximum on exactly the setups the runner knows least "
        "about. This is the inversion RC-3-2 exists to forbid.",
    ),
    (
        "RC-3-3",
        r"(?:surface|surfaces)[^.]{0,80}(?:absent|missing|not in the (?:changed-file )?list)"
        r"[^.]{0,60}(?P<dem>\b(?:need not|no need to|without) (?:be )?"
        r"(?:record|recorded|reporting|report))",
        "drops the recording obligation, which is the half that makes the skip authorized "
        "rather than improvised — a narrowed gate and a full gate then produce the same "
        "report.",
    ),
    (
        "RC-3-3",
        r"(?P<dem>\b(?:you may|it is fine to|acceptable to) skip a surface)[^.]{0,60}"
        r"(?:the list|changed-file list) (?:does )?touch",
        "licenses the inverse the rule closes by name: a hand-made skip of a surface the "
        "list DOES touch, which is the judgement call the surface gate replaced.",
    ),
    (
        "RC-3-4",
        rf"{_POST}[^.]{{0,80}}(?P<dem>\b(?:inherits|inherit|reuses|reuse)\b)[^.]{{0,60}}"
        rf"(?:{_S3}|the earlier|the pre-merge)?[^.]{{0,40}}(?:skip|list|diff)",
        "lets the post-merge gate decide on a pre-merge tree's contents, so the assembled "
        "diff of every merged branch goes unverified. This is the single most natural "
        "implementation error in the step, because 'the diff' reads like a property of the "
        "run.",
    ),
    (
        "RC-3-5",
        r"doc-only[^.]{0,80}(?P<dem>\b(?:is|are) "
        r"(?:harmless|safe|risk-free|inherently safe))",
        "restores the justification RC-3-5 replaces. Harmlessness is the premise that makes "
        "letting 4a-post inherit the skip look reasonable; the pass-scoped licence is what "
        "stops it.",
    ),
    (
        "RC-3-6",
        r"item.?5[^.]{0,80}(?P<dem>\b(?:only|need only|is only) "
        r"(?:reached|evaluated|considered))",
        "restores the bare sequence in which item 4 fires first and item 5 is never "
        "reached, which is how a consumer with no command list meets 'stop and ask' after "
        "every branch has been merged.",
    ),
    (
        "RC-3-7",
        r"\btwo[- ]dots?\b[^.]{0,70}(?P<dem>\b(?:is fine|are fine|suffices|is equivalent"
        r"|works too|same (?:as|thing)))",
        "licenses the two-dot form, which does not fail — it silently returns a WRONG "
        "changed-file list, rendering everything the base gained since the branch was cut as "
        "though the branch deleted it. Every narrowing decision in this step reads that list, "
        "so the corruption is upstream of the surface gate, the doc-only skip and the "
        "`Unverified surfaces:` report at once.",
    ),
    (
        "RC-3-8",
        r"(?:no origin|missing (?:remote|origin)|origin is absent)[^.]{0,70}"
        r"(?P<dem>\b(?:is fine|can be ignored|carry on|proceed normally|skip the gate))",
        "waves through the setup `RC-3-2` exists for. The sentinel is what turns 'the scope "
        "could not be computed' into a value the runner can branch on; without it the diff "
        "alone exits 128 and a runner that shrugs at the failure gates on an empty list, "
        "which fires every narrowing at maximum on exactly the consumers this skill knows "
        "least about.",
    ),
]

def _sentence_bounds(flat: str, at: int) -> tuple[int, int]:
    """The sentence containing `at`, so negation is judged in its own clause."""
    start = flat.rfind(". ", 0, at)
    start = 0 if start == -1 else start + 2
    end = flat.find(". ", at)
    end = len(flat) if end == -1 else end
    return start, end


# Sentences in the SHIPPED step that a screen legitimately matches, because they STATE the
# rule rather than demote it. Allow-listed EXACTLY.
#
# The first implementation suppressed a hit whenever a negation word appeared earlier in the
# same sentence. A round measured that heuristic and walked **8 of 8** screens through it with
# one ordinary prefix — "Never forget the reason: a doc-only diff is harmless and so the skip
# is safe." Every screen went silent on a sentence that affirms the demotion. The heuristic
# traded a handful of known false positives for a total bypass, which is the wrong trade.
#
# An allow-list cannot be walked that way, and it is self-maintaining: every entry is text
# inside the verbatim pin, so changing a shipped sentence fails layer (a) first, and
# `test_the_screen_allow_list_is_exactly_the_shipped_sentences` fails if the list drifts from
# what the screens actually match.
SCREEN_ALLOWED: tuple[str, ...] = (
    "**Each pass scopes itself to its own tree, with one command.** Item 3's surface gate reads the list this prints at **both** passes; item 4's doc-only skip reads it at **this pass only**, because `4a-post` does not inherit it: ```bash # The changed-file list for THIS pass, read off stdout",
    '**`4a-post` therefore does not inherit this skip**; see that step',
    'What does *not* license it is the idea that a doc-only diff is harmless',
)


# A fence delimiter run, folded to one token before an allow-list comparison.
#
# `SCREEN_ALLOWED[0]` is a whole shipped sentence and `_sentence_bounds` splits on `". "`, so
# the sentence it pins *contains* the block's ```` ```bash ```` delimiter. This phase's round
# measured the consequence: switching to a four-backtick fence, to `~~~`, or simply dropping
# the `bash` info string each made the entry stop matching and the screen fire — emitting
# **"RC-3-4 contradicted"** over a presentational reformat. A false positive that names a
# specific rule as violated is worse than a silent one: it sends the reader to look for a
# demotion that is not there, and the honest response to two or three of those is to stop
# believing the screen. The phase had already decoupled the allow-list from the tag MARKERS
# (that is why the screens read the raw slice) and missed the delimiter itself.
_FENCE_RUN = re.compile(r"(?:`{3,}|~{3,})\S*")


def _screen_canon(text: str) -> str:
    return _FENCE_RUN.sub("```", text)


SCREEN_ALLOWED_CANON: frozenset[str] = frozenset(_screen_canon(s) for s in SCREEN_ALLOWED)


def _screen_fires(pat: str, flat: str) -> bool:
    """True when the demotion appears in a sentence that is not one of the shipped rule
    statements."""
    for m in re.finditer(pat, flat, re.I):
        s, e = _sentence_bounds(flat, m.start())
        if _screen_canon(flat[s:e].strip()) not in SCREEN_ALLOWED_CANON:
            return True
    return False


def section_problems(section: str, raw: str | None = None) -> list[str]:
    """Layers (a)-(c) over one section. Scoped to the section, never the file.

    Section-scoped on the exemplar's own reasoning: neighbouring steps legitimately use
    this vocabulary, so a file-wide screen would redden the step that warns about a
    reading, for the sentence that warns about it.
    """
    problems: list[str] = []
    # Screens read the RAW slice: not because the pin's slice is blind any more (it is not,
    # since Phase 291), but because `SCREEN_ALLOWED` is pinned to whole shipped sentences and
    # a `[[fence]]` marker landing mid-sentence would change what those entries must match.
    flat_raw = _flat(section if raw is None else raw)

    # (a) + (d): required subject patterns. These fire on the empty string, which is what
    # actually catches deletion — layer (d) is about fail-OPEN widening, not this.
    #
    # Read over the slice with its NEUTERING regions dropped, which is this file's half of
    # the `Q-457` policy. Comments and `<details>` hide text from every reader in every file,
    # so a rule commented out must read as gone; fences and blockquotes are operative HERE
    # and stay, which is what lets a rule living in a prescribed command block be declared
    # at all. `_shared/adversarial-review.md` makes the opposite call for the same two
    # classes, and that difference IS the fork the filing named.
    visible = _flat(_without(section, NEUTERING_TAGS))
    for rule_id, pat in SUBJECT_PATTERNS.items():
        if not re.search(pat, visible):
            problems.append(f"{rule_id} lost its subject pattern from the runner")

    # (c): contradiction screens.
    for rule_id, pat, why in FORBIDDEN:
        if _screen_fires(pat, flat_raw):
            problems.append(f"{rule_id} contradicted: {why}")

    return problems


# ---------------------------------------------------------------------------------------
# Layer (a) — the whole-block verbatim pin
# ---------------------------------------------------------------------------------------
#
# To re-approve a deliberate edit, regenerate this constant rather than hand-editing it.
# Resolve the interpreter with `--git-common-dir`, NEVER `--show-toplevel`: the latter answers
# "which worktree am I standing in", which is the primary only when the runner happens to be
# standing there (Phase 234, `Q-020`/`Q-307`(b)) — and step 3 of the procedure puts you in a
# worktree, which carries no `.venv` of its own. A first draft of this comment prescribed
# `--show-toplevel` and exited 127 in exactly the case it claimed to have fixed, inside the
# module that pins the rule forbidding it.
#
#     "$(cd "$(git rev-parse --git-common-dir)/.." && pwd -P)/.venv/bin/python3" -c \
#       "import sys; sys.path.insert(0,'.'); \
#        import tests.test_review_close_reference_pins as P; \
#        print(repr(P._block_canon(P._flat(P._step_3_section()))))"
#
# Paste the output below. The diff then carries the prose change and its re-approval together,
# which is the whole mechanism. A REGENERATION IS THE RE-APPROVAL: name it in the commit
# message. Nothing enforces that — see the spec's § 6 — so it is on you.
#
# **When a regeneration is caused by the CANONICALISER rather than by the prose, prove it
# instead of reading it.** Phase 291's switch from `_prose_only` to `_tagged` moved this
# constant by 674 characters (12,666 -> 13,340) and no reviewer can eyeball a 13k literal for
# a changed word. The delta is provable in one expression, and it held exactly:
#
#     _block_canon(re.sub(r"\s+", " ", _without(NEW_PIN, TAG_CLASSES))) == OLD_PIN
#
# Dropping every tagged region from the new constant reproduced the old one **byte for
# byte**, which says the whole delta is markers plus previously-stripped spans and that no
# shipped word changed. `test_the_pin_reduces_to_the_stripped_rendering` keeps the
# file-level half of that relationship live; the constant-to-constant half is a one-time
# check a regenerating phase runs and records.
#
# Pinned VERBATIM, not by length. A first draft pinned the canonical LENGTH on the stated
# grounds that a 12.6k literal would make "every innocent reflow produce an unreadable diff".
# That was false and a round proved it in one command: `_block_canon(_flat(...))` makes reflow,
# re-indentation and a `-`/`*` bullet swap byte-identical, so a verbatim pin produces NO diff on
# an innocent edit. The length pin cost 8 of 8 length-preserving inversions surviving, including
# "Do not push with failing checks." -> "You may push with failing checks" at 32 characters each.

STEP_3_VERBATIM = (
    '## Step 3: Run Verification [[quote]]**Before you skip, weaken, or reword any rule in this step, read `REFERENCE.md` § `RC-3-1` through § `RC-3-8`.** Those eight rules are declared load-bearing and pinned by a required check: each section names what its loss would change, which is the thing this step cannot tell you while you are running it. The rest of this skill is not covered — do not read the file\'s existence as coverage of anything outside Step 3.[[/quote]] **This is the pre-merge pass, and it can only verify the tree it runs on.** `HEAD` is still `main` here — Step 3b has not removed a worktree and Step 4a has not merged anything — so no approved branch\'s files are in this working tree and its new tests do not exist yet. What this pass verifies is *this* tree: `origin/<default branch>` plus whatever local-only commits `main` already carries. It is a fail-fast on the base, and it is the last point where stopping is free. **It is not a verdict on the work, and nothing here may be reported as having verified a branch** — that verdict is `4a-post`, which re-runs the same resolved list on the merge target once the branches are merged. **Each pass scopes itself to its own tree, with one command.** Item 3\'s surface gate reads the list this prints at **both** passes; item 4\'s doc-only skip reads it at **this pass only**, because `4a-post` does not inherit it: [[fence]]```bash # The changed-file list for THIS pass, read off stdout. Three dots, always — two would # render everything the base gained since a branch was cut as though the branch deleted # it (the Step 2a note). Run from the repo root. git rev-parse --verify --quiet origin/<default branch> >/dev/null \\ && git diff --name-only origin/<default branch>...HEAD \\ || echo "NO_ORIGIN_MAIN" ```[[/fence]] On this pass `HEAD` is `main`, so the list is main\'s local-only commits — the `open → in_progress` claim flips and any Step 1b `review_tasks.md` save — and that population is exactly what this pass is entitled to verify. At `4a-post` the identical command runs on the merge target and returns the whole assembled diff. **If it prints `NO_ORIGIN_MAIN`** (no `origin`, or a remote whose default branch is not `main` — verified: the diff alone exits 128 with `fatal: ambiguous argument`), there is no changed-file list: **gate nothing and skip nothing — run the full resolved list.** A scope you could not compute must never silently narrow the gate. **An empty list is a real outcome here, and it is the one to report rather than pass over.** On a `main` already level with `origin/<default branch>` this command prints nothing, so a `### Ratchet` snippet filtering it short-circuits on every filter and the pass reports green having executed nothing at all. That is *correct* — there is nothing on this tree the base has not already seen — but "green" and "ran nothing" must not read the same, which is why Step 8\'s `Verification:` line carries the reason, not just the verdict. Now discover the project\'s verification commands. Resolve in this order — stop at the first source that produces a command list: - **`<project>/CLAUDE.md` § "Pre-merge verification"** (preferred — the project owns its command list). Two shapes are supported: - **Split sub-headings (recommended).** If the section uses `### Always` and/or `### Ratchet (changed files only)` sub-headings, run them in that order: - **`### Always`** — full-tree commands run unconditionally (build, full test suite, project-level smoke tests). Bullet list; one command per bullet. **"Unconditionally" is a promise about `4a-post`**, the gate that speaks for the work: no diff-shape heuristic skips a list the consumer declared. *This* pass does drop it on the dominant cycle (item 4 below), because its green is not a verdict — and that asymmetry is the only thing standing between the word "always" and a section the dominant cycle never runs. - **`### Ratchet (changed files only)`** — project-supplied shell snippets in a single bash code block. Each snippet is expected to filter `git diff --name-only origin/<default branch>...HEAD` to its file-type of interest and invoke lint/typecheck against only the changed files. Run the block as-is from the repo root. A snippet whose filtered changed-file list is empty short-circuits and passes — that\'s project-side logic, not a Sysop rule. Treat the snippets as project-trusted input — they run with full agent shell privileges. If you didn\'t write them yourself, read the block before running it. - **Flat list (backward compatible).** If neither sub-heading exists, treat all bullets under `## Pre-merge verification` as the `### Always` list and skip the ratchet step. - **`package.json` `scripts.verify`** (if `package.json` is at the repo root or `<frontend>/`). If at repo root, run `npm run verify`. If at `<frontend>/`, run `(cd <frontend> && npm run verify)` from the repo root. - **Auto-detect from common surfaces** — each command gated on its own surface appearing in this pass\'s changed-file list (internal tracker #206). A surface being *present* says the project has one; it does not say this run *touched* one, and running a full frontend build for a diff of Python scripts is the cost that makes skipping tempting — and the skip is then a judgement this step never authorized, so it gets made silently. - `frontend/` exists with `package.json` → `cd frontend && npm run build && npm run test` — **only if** the changed-file list contains a path under `frontend/` - `pyproject.toml` exists with `pytest` declared in `[project.optional-dependencies]` (any extra) → `python -m pytest tests/` — **only if** the list contains a Python file - `Cargo.toml` exists → `cargo test --release` — **only if** the list contains a Rust file or `Cargo.toml` - Other detectable surfaces → run the platform-native test/build command, under the same rule: only if the list contains a file that surface owns. **A surface absent from the changed-file list is `skipped`, not `failed`.** Record it on Step 8\'s `Verification:` line (`skipped frontend — not in this run\'s changed files`). That is what makes the skip *authorized* rather than improvised. It does not license the inverse: do not decide by hand to skip a surface the list does touch. **Then report every changed code file that no detected surface claimed** — Step 8\'s `Unverified surfaces:` line. Surface-gating narrows the gate, so what it cannot account for has to become visible rather than disappear; a `.sql` migration or a `.go` service in a repo whose only detected surfaces are `frontend/` and `pytest` is verified by nothing, and that was true before this gate existed too. The fix is consumer-side and is one heading away: a `## Pre-merge verification` section is **never** surface-gated, because there the consumer said what to run. - **If the diff is doc-only** (no `.py` / `.ts` / `.tsx` / `.js` / `.jsx` / `.sql` / `.sh` / `.kt` / `.swift` / `.go` / `.rs` files changed — only `.md` / `.txt` / `.yaml` config / etc.): skip verification with a one-line note (`Step 3: skipped — diff is doc-only`). **"The diff" is this pass\'s changed-file list, never the run\'s.** The two passes compute it the same way on different trees, so each decides its own skip: `4a-post` is never skipped because Step 3 was, and Step 3\'s skip is not evidence about any branch. On the common cycle this pass *does* skip — a claim flip and a `review_tasks.md` save are the whole of main\'s local-only diff — which is why the pre-merge pass costs almost nothing and why nothing may be concluded from its green. Step 4 (push) still runs. **The licence for this skip is the pass, not the diff — and that distinction is the whole of it.** Step 3 is a fail-fast on the base whose green this step\'s opening already forbids reading as a verdict, so skipping it forfeits only the fail-fast. What does *not* license it is the idea that a doc-only diff is harmless. The extension test above classifies as documentation a great many files a build actually consumes — `pyproject.toml`, `tsconfig.json`, `.eslintrc.json`, `ruff.toml`, `package.json` and its lockfile, CI workflows, semgrep rules, `checks.yml` (not *every* such file: a `vite.config.ts` or `.eslintrc.js` is `.ts`/`.js` and counts as code) — so a diff that is doc-only by this test can regress lint, typecheck and build *directly*, and `### Always` is a full test suite, which can assert on prose as readily as on code. **`4a-post` therefore does not inherit this skip**; see that step. **It also never cancels a command item 3 armed.** Item 3 gates each auto-detected command on its own surface appearing in this list, and three of its four bullets can fire on a diff this test calls doc-only: a path under `frontend/` (`package.json`, `tsconfig.json`, a stylesheet), a `Cargo.toml` — which item 3 names *by name* while `.toml` is absent from the code set above — or any other surface\'s non-code manifest (`go.mod`, `Dockerfile`, `pubspec.yaml`). Where item 3 armed a command, run it. Item 4 decides only what item 3 left unarmed, plus a consumer-declared list under items 1–2. `### Ratchet` needs no decision either way: its snippets filter the changed-file list themselves and short-circuit when the filter comes back empty, which is project-side logic rather than a Sysop skip. - **If none of the above fire and the diff touches code**: stop and ask the user what to run. Do not invent commands. Do not run `pip install` or any state-mutating command during verification — verification is read-only. **The item-5 stop is about the run, not about this pass — resolve before you skip.** Item 4 decides whether to *run* the list; it does not decide whether the list had to exist. Taken in bare sequence the two collide on the dominant path: this pass\'s diff is doc-only, item 4 fires, and item 5 is never reached — so a consumer with no `## Pre-merge verification`, no `scripts.verify` and no detectable surface sails through Step 3 and hits "stop and ask the user what to run" at `4a-post`, **after every branch has been merged**, which is the one outcome this step exists to prevent. So run item 5 against the *run*: if no source produced a command list and **any** part of this cycle touches code — this pass\'s changed-file list, or `git diff --name-only <default branch>...<branch>` for any approved branch (the same per-branch read Step 3c makes) — stop and ask **here**, whether or not item 4 skipped the run. If any command fails, report the failure and **stop**. Do not push with failing checks. Stopping *here* is free — nothing has been merged, no worktree has been removed, no lock has been dropped — so fix the failure and re-run `/review-close` from the top. (`4a-post` has a stop of its own, and it is not free in the same way; its recovery is stated there per policy.) **Venv-aware invocation** (the consumer\'s own tooling — **not** `sysop/scripts/*.py`, which resolve venv PyYAML themselves and are always invoked with a bare `python3`; see WORKFLOW.md § 6.1). If a verification command fails with `exit 127` (command not found) or `ModuleNotFoundError` and the project has a `.venv/` directory at the repo root, re-run with `.venv/bin/<cmd>` (for explicit binaries like `.venv/bin/pytest`) or `PATH=.venv/bin:$PATH <cmd>` (for shell pipelines or tools that re-exec). Same pattern as Step 4d\'s pre-push hook venv prefix. The canonical fix is consumer-side — the project\'s `<project>/CLAUDE.md § Pre-merge verification` commands should be authored with `.venv/bin/` prefixes when they depend on venv-installed tools (see WORKFLOW.md § 6.1 venv-aware-invocation paragraph) — but the prefix-on-rerun pattern unblocks the cycle when the consumer\'s command list hasn\'t been venv-ified yet. **Boy-scout escalation (ratchet consequence).** A `### Ratchet` snippet invokes the project\'s lint/typecheck tool against the changed-file list, so if a file in the diff carries pre-existing findings — warnings or type errors not introduced in this review pass — the tool will report them and the gate will fail. That\'s intentional and not a Sysop-side rule: touching a file means cleaning it. Full-tree backlog cleanups stay as separate project-side tasks (e.g. `TECH-LINT-BACKLOG-FIX`, `TECH-TYPECHECK-BACKLOG-FIX` entries in `tasks/index.yml`), so the ratchet doesn\'t impose a clean-everything-first dependency on consumers with existing backlogs. **If a verification command is silently denied** (auto-mode classifier rejects a `npm` / `pytest` / `cargo` / project-specific invocation): prompt the user to run that command themselves via `!`-shell-escape in their prompt — the same pattern Step 4d uses for protected-branch pushes. Do NOT use `AskUserQuestion`; ask for the literal `!`-prefixed command. Step 0\'s permission guard cannot anticipate every project-specific verification command. (Phase 36\'s `PermissionDenied` hook surfaces guidance for exactly three shapes — a push to `origin` of one of the two branch names the hook **hard-codes** (`main` or `master`, literally; it does not resolve the default branch), a `--delete` push of any branch, and `git commit` on a protected branch — and emits nothing for anything else, verification commands included, because their vocabulary varies too widely per consumer to enumerate. So this prose remains the load-bearing instruction here. **State the coverage as those three shapes, never as the steps that use them** — a step reference reads as a promise about everything the step runs, and Step 4d under `pr` policy runs `gh pr`, which the hook does not match.) [[quote]]**For new projects:** add a `## Pre-merge verification` section to your CLAUDE.md (template in WORKFLOW.md § 6.1) listing the exact commands this skill should run. That keeps verification deterministic across consumer projects with different stacks.[[/quote]] '
)
STEP_3_VERBATIM_LEN = len(STEP_3_VERBATIM)


def test_the_step_3_block_matches_its_pin():
    """Layer (a). Any edit to the surviving text fails until this is regenerated.

    Verbatim, whitespace- and list-marker-normalised: rewrapping, reflowing, re-indenting and
    a `-`/`*` bullet swap all pass; changing the words does not. That is the property a length
    pin cannot give — a length pin passes every length-preserving inversion, and a round
    measured 8 of 8 surviving before this was changed.
    """
    canon = _block_canon(_flat(_step_3_section()))
    if canon != STEP_3_VERBATIM:
        raise AssertionError(
            "Step 3 no longer matches its pin "
            f"({len(canon)} chars vs {len(STEP_3_VERBATIM)} pinned). "
            + _first_divergence(canon, STEP_3_VERBATIM)
            + " If the edit was deliberate, regenerate this constant in the same commit with "
            "the recipe above and say so in the commit message — that is the re-approval."
        )


def test_the_step_3_section_binds():
    assert section_problems(_step_3_section(), _step_3_raw_section()) == []


def test_the_pin_reduces_to_the_stripped_rendering():
    """The tagged pin and the stripped rendering must describe the same step.

    Drop every tagged region from the pinned constant and what is left must be exactly what
    `_prose_only` renders from the shipped file. This does not detect a prose change — layer
    (a) does that — it detects a TAGGER change: a resolver that mis-nested, swallowed a span
    or duplicated one would still let layer (a) be regenerated around itself and stay green,
    because both halves would move together. This is the half that does not move.
    """
    stripped = _block_canon(_flat(_prose_only(SKILL.read_text(encoding="utf-8"))))
    reduced = _block_canon(_flat(_without(STEP_3_VERBATIM, TAG_CLASSES)))
    assert reduced and reduced in stripped, _first_divergence(reduced, stripped[:len(reduced)])


def test_a_demotion_hidden_in_a_fence_reaches_both_layers():
    """The author-side battery's one survivor, and the `Q-457` fork above it.

    Before Phase 291 this test asserted the OPPOSITE of its first clause — that the pin's
    slice "genuinely cannot see it" — and the raw-slice screens were the only thing standing
    between a fenced demotion and a green suite. That was the fork: text inside a fence in
    THIS file is a prescribed command, not a quoted example, so a pin that cannot read it
    cannot protect the half of the step that does the work. It reaches both layers now.
    """
    fenced = "\n\n```bash\n# Step 3 verifies the branch before merging.\n```\n\n"
    mutated = SKILL.read_text(encoding="utf-8").replace(STEP_3_END, fenced + STEP_3_END, 1)
    prose, raw = _step_3_slice(mutated), _step_3_raw_slice(mutated)
    assert "verifies the branch" in _flat(prose), "the pin still cannot see into a fence"
    assert "verifies the branch" in _flat(raw)
    assert _block_canon(_flat(prose)) != STEP_3_VERBATIM, (
        "layer (a) accepted a demotion added inside a fenced block"
    )
    assert section_problems(prose, raw), "a demotion inside a fence reached no screen"


def test_a_rule_moved_into_a_fence_reddens_the_pin():
    """The property deletion used to give, kept: neutering must not read as unchanged.

    `_prose_only` made a fenced rule read as DELETED, which failed the pin. `_tagged` keeps
    the words and makes the wrapper visible instead, so the same edit fails the pin as a
    CHANGE. Either is loud; this asserts the new one actually is, because "keep everything"
    is exactly the shape that could have quietly lost it.
    """
    text = SKILL.read_text(encoding="utf-8")
    # Located with a whitespace-tolerant pattern, never retyped as a literal. The first
    # version hard-coded the sentence and asserted `count == 1`; Phase 291's negative
    # control re-wrapped that sentence across two lines and the TEST went red — a fixture
    # anchored to a snapshot rather than to the file.
    #
    # Phase 292 (`Q-495`): that fix put `\s+` at ONE gap — the one that control happened
    # to wrap at. A re-wrap breaks a raw anchor wherever the break lands, so a single
    # tolerant gap fixes one wrap width and no other; re-wrapping at 120 columns broke
    # this test again, in the module built to close the class. `anchor()` is tolerant at
    # every gap at once.
    m = anchor("A scope you could not compute must never silently narrow the gate.").search(text)
    assert m, "RC-3-2's sentence is gone from the runner — a different test owns that"
    rule = m.group(0)
    assert text.count(rule) == 1
    moved = text.replace(rule, "\n\n```\n" + rule + "\n```\n\n", 1)
    canon = _block_canon(_flat(_step_3_slice(moved)))
    assert canon != STEP_3_VERBATIM, "a rule moved into a fence left the pin green"
    assert _flat(rule) in canon, "the words should still be there — a change, not a deletion"


def test_a_rule_commented_out_loses_its_subject_pattern():
    """This file's half of the `Q-457` policy, which nothing else asserts.

    `_tagged` keeps every character, so the subject patterns would happily match a rule that
    has been commented out — a reader sees nothing and the roster reports full coverage.
    `section_problems` reads `_without(section, NEUTERING_TAGS)` for exactly that, and a
    battery mutation that dropped the `_without` call survived every other check here.

    The complement is the point of the whole phase and is asserted alongside: a rule inside a
    FENCE must still satisfy its pattern, because in this file a fence is a prescribed
    command rather than a quoted example.
    """
    text = SKILL.read_text(encoding="utf-8")
    m = anchor("A scope you could not compute must never silently narrow the gate.").search(text)
    assert m
    hidden = text.replace(m.group(0), "<!-- " + m.group(0) + " -->", 1)
    problems = section_problems(_step_3_slice(hidden), _step_3_raw_slice(hidden))
    assert any("RC-3-2 lost its subject pattern" in p for p in problems), problems

    # ...and the fenced rules keep theirs, which is what `Q-457` bought.
    for rule_id in ("RC-3-7", "RC-3-8"):
        assert not any(f"{rule_id} lost its subject pattern" in p
                       for p in section_problems(_step_3_section(), _step_3_raw_section())), (
            f"{rule_id} lives in the fenced block; the neutering policy must not drop it"
        )


def test_a_step_neutered_around_its_own_anchors_fails_closed():
    """The measurement that refused the filing's first two ways out.

    Wrap the whole step in `<!-- -->` with the closer placed PAST `## Step 3c` and the text
    between the anchors is byte-identical. Without the wrapper check that is a GREEN pin over
    a step no reader can see — Phase 167's survivor, rebuilt inside its own fix.
    """
    text = SKILL.read_text(encoding="utf-8")
    i = text.find("\n" + STEP_3_START)
    k = text.find(STEP_3_END, i) + len(STEP_3_END)
    assert i > 0 and k > i
    # Each ANCHOR separately, because the two `_anchor_is_wrapped` calls are separate lines
    # and the round showed each is individually deletable — every fixture wrapped BOTH
    # anchors, so removing either call alone was caught by nothing. A wrapper that opens
    # before the start marker and closes between the two is the case only the START check
    # sees; one that opens between them and closes past the end marker is the END check's.
    wrappers = (("comment", "<!--", "-->"), ("fence", "```markdown", "```"),
                ("tilde fence", "~~~markdown", "~~~"))
    mid = text.find("\n**Venv-aware invocation**", i)
    assert i < mid < k, "the midpoint anchor moved; re-derive it"
    for label, opener, closer in wrappers:
        for name, mutated in (
            (f"{label} spanning both anchors",
             text[:i] + f"\n\n{opener}\n" + text[i:k] + f"\n{closer}\n" + text[k:]),
            (f"{label} opening before the START anchor, closing mid-step",
             text[:i] + f"\n\n{opener}\n" + text[i:mid] + f"\n{closer}\n" + text[mid:]),
            (f"{label} opening mid-step, closing past the END marker",
             text[:mid] + f"\n\n{opener}\n" + text[mid:k] + f"\n{closer}\n" + text[k:]),
        ):
            assert _step_3_slice(mutated) == "", f"{name}: the slice survived a neutered step"


def test_the_screen_allow_list_is_exactly_the_shipped_sentences():
    """The allow-list may not grow, and may not go stale.

    It replaced a negation heuristic that a round walked through on 8 of 8 screens. An
    allow-list has the opposite failure mode — silently widening until it excuses a real
    demotion — so it is pinned to exactly the set the screens match in the shipped step.
    """
    raw = _flat(_step_3_raw_section())
    matched = []
    for _rid, pat, _why in FORBIDDEN:
        for m in re.finditer(pat, raw, re.I):
            s, e = _sentence_bounds(raw, m.start())
            sent = _screen_canon(raw[s:e].strip())
            if sent not in matched:
                matched.append(sent)
    assert set(matched) == set(SCREEN_ALLOWED_CANON), (
        "the screen allow-list has drifted from what the screens actually match.\n"
        f"matched but not allowed: {sorted(set(matched) - set(SCREEN_ALLOWED_CANON))}\n"
        f"allowed but unmatched (stale): {sorted(set(SCREEN_ALLOWED_CANON) - set(matched))}"
    )
    assert len(SCREEN_ALLOWED) <= 6, (
        "an allow-list this long is a blanket exemption; re-scope the screens instead"
    )


def test_the_required_patterns_fire_on_an_empty_section():
    """Deletion is caught here, not by the extractor's assert.

    The spec's first draft claimed an empty section passes silently and that the
    fail-closed extractor was the only thing standing between a deleted step and a green
    suite. Measured on the exemplar, that was false — 14 and 23 problems on empty input —
    and it is false here too. Layer (d) earns its place on fail-OPEN widening instead.
    """
    problems = section_problems("")
    assert len(problems) == len(SUBJECT_PATTERNS), problems
    assert all("lost its subject pattern" in p for p in problems)


# ---------------------------------------------------------------------------------------
# The roster-completeness check
# ---------------------------------------------------------------------------------------


def test_the_roster_is_a_three_way_identity():
    """Roster bullets, REFERENCE.md sections, and DECLARED_IDS must be one set.

    This is what stops the Phase 204 shape: a rule quietly leaving the population while a
    presence check that cannot see its own roster stays green. It does NOT make deletion
    impossible — three coordinated edits in one commit still land it — it makes deletion an
    edit to a PINNED CONSTANT, so it cannot happen as a side effect.
    """
    roster, sections = _roster_ids(), _section_ids()
    assert roster == DECLARED_IDS, (
        f"REFERENCE.md's roster and DECLARED_IDS disagree. "
        f"only in roster: {sorted(roster - DECLARED_IDS)}; "
        f"only pinned: {sorted(DECLARED_IDS - roster)}"
    )
    assert sections == DECLARED_IDS, (
        f"REFERENCE.md's `## <id>` sections and DECLARED_IDS disagree. "
        f"only sections: {sorted(sections - DECLARED_IDS)}; "
        f"only pinned: {sorted(DECLARED_IDS - sections)}"
    )


@pytest.mark.parametrize("rule_id", sorted(DECLARED_IDS))
def test_every_declared_rule_is_complete(rule_id):
    """The four roster checks, per declared id."""
    # (d) it has a subject pattern at all
    assert rule_id in SUBJECT_PATTERNS, f"{rule_id} has no subject pattern"

    # (a) that pattern resolves to runner text inside the pinned block — and to the SAME
    # text the roster pinned for it, so re-pointing the pattern at a different sentence is
    # an edit to the rule's own words rather than a regex tweak.
    assert rule_id in SUBJECT_QUOTES, f"{rule_id} has no pinned subject quote"
    visible = _flat(_without(_step_3_section(), NEUTERING_TAGS))
    m = re.search(SUBJECT_PATTERNS[rule_id], visible)
    assert m and m.group(0) == SUBJECT_QUOTES[rule_id], (
        f"{rule_id}'s subject pattern no longer resolves to its pinned quote.\n"
        f"  pinned : {SUBJECT_QUOTES[rule_id]!r}\n"
        f"  matched: {(m.group(0) if m else None)!r}\n"
        "If the runner's wording changed deliberately, update the quote in the same commit — "
        "that edit IS the re-approval, and it names which rule moved."
    )
    flat = _flat(_step_3_section())
    assert re.search(SUBJECT_PATTERNS[rule_id], flat), (
        f"{rule_id}'s subject pattern does not match inside the pinned block. Either the "
        "runner text changed, or the rule lives in a fenced block and cannot be declared "
        "under this mechanism — see REFERENCE.md § Blocked."
    )

    # (b) it has a REFERENCE.md section WITH CONTENT. A round deleted every section body,
    # kept the six headings, and the three-way identity was satisfied over six empty sections.
    assert rule_id in _section_ids(), f"{rule_id} has no REFERENCE.md section"
    body = _section_body(rule_id)
    assert len(body) >= 400, (
        f"{rule_id}'s REFERENCE.md section is {len(body)} chars — too short to state what the "
        "rule protects and what its loss would change, which is what declaring it requires"
    )
    assert "loss would change" in body or "widening would change" in body, (
        f"{rule_id}'s section does not state what its loss would change. That statement is the "
        "declaration bar; a section without it is a heading."
    )

    # (c) at least one forbidden predicate names it as subject
    assert any(rid == rule_id for rid, _, _ in FORBIDDEN), (
        f"{rule_id} has no contradiction screen. A rule whose only protection is the block "
        "pin loses it the next time someone regenerates the pin for something else."
    )


@pytest.mark.parametrize("rule_id", sorted(DECLARED_IDS))
def test_every_subject_pattern_is_specific(rule_id):
    """A subject pattern is the ONLY deletion detector. A weak one silently retires a rule.

    A round vacated one pattern to `r"skip"` and inverted that rule's sentence in the runner:
    the suite stayed green with the roster, the sections and DECLARED_IDS all untouched. The
    spec admits the screens are not checked for strength; it did not admit it for the subject
    patterns, which is where it bites.
    """
    pat = SUBJECT_PATTERNS[rule_id]
    literal = re.sub(r"\\(.)", r"\1", pat)
    assert len(literal) >= 40, (
        f"{rule_id}'s subject pattern is {len(literal)} chars — too short to identify a rule. "
        "A short pattern matches incidental text and keeps passing after the rule it names is "
        "reworded away."
    )
    # It must not match text that no longer contains the rule: deleting the matched span from
    # the runner has to make it fail.
    flat = _flat(_step_3_section())
    m = re.search(pat, flat)
    assert m, f"{rule_id}'s pattern does not match at all"
    assert not re.search(pat, flat[:m.start()] + flat[m.end():]), (
        f"{rule_id}'s subject pattern matches more than once, so deleting the rule leaves the "
        "detector satisfied by the other occurrence"
    )


def test_the_roster_is_not_vacuous():
    """A roster check over an empty roster is the thing it exists to prevent."""
    assert len(DECLARED_IDS) >= 6
    assert len(SUBJECT_PATTERNS) == len(DECLARED_IDS)
    assert set(SUBJECT_QUOTES) == DECLARED_IDS, (
        "every declared rule needs a pinned subject quote; a missing one restores the "
        "three-edit retirement the round demonstrated"
    )
    assert {rid for rid, _, _ in FORBIDDEN} <= DECLARED_IDS
    assert {rid for rid, _, _ in FORBIDDEN} == DECLARED_IDS, (
        "every declared rule must carry at least one screen; a partial set reads as "
        "coverage"
    )


@pytest.mark.parametrize("rule_id,pat,why", [(r, p, w) for r, p, w in FORBIDDEN])
def test_every_screen_actually_fires(rule_id, pat, why):
    """A screen that matches nothing is a comment. Each must fire on a planted violation.

    Built from the `why` text's own description of the demotion, so a screen and its
    justification cannot drift apart silently.
    """
    planted = {
        0: "Step 3 verifies the branch before anything is merged.",
        1: "A green at Step 3 means the work is verified and safe to merge.",
        2: "If it prints NO_ORIGIN_MAIN, treat it as an empty list and carry on.",
        3: "A surface absent from the changed-file list need not be recorded anywhere.",
        4: "It is fine to skip a surface the changed-file list does touch.",
        5: "4a-post inherits Step 3's skip when the pre-merge diff was doc-only.",
        6: "A doc-only diff is harmless, so the skip is safe.",
        7: "item 5 is only reached when item 4 did not fire.",
        8: "Two dots is fine here; the base rarely moves during a close.",
        9: "If there is no origin that is fine, carry on with the full list.",
    }[[i for i, (r, p, w) in enumerate(FORBIDDEN) if p == pat][0]]
    assert _screen_fires(pat, _flat(planted)), (
        f"{rule_id}'s screen does not fire on the demotion it names: {why}"
    )


# ---------------------------------------------------------------------------------------
# The regeneration procedure, executed
# ---------------------------------------------------------------------------------------


def _recipe_interpreter() -> str:
    """What the documented recipe resolves to, by the documented means.

    Falls back to the running interpreter rather than skipping: CI installs to the runner
    python and has no repo-root `.venv`, so a skip here would mean the one test that proves
    the recipe runs never runs anywhere except the maintainer's primary checkout — which is
    the single place the broken first draft happened to work.
    """
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    primary = (REPO_ROOT / common).resolve().parent
    venv = primary / ".venv/bin/python3"
    return str(venv) if venv.exists() else sys.executable


def test_the_regeneration_recipe_runs_and_round_trips():
    """Run the documented recipe against a MUTATED copy and paste the result back.

    A procedure nobody runs ships broken — this repo's record carries a runbook pass that had
    never been runnable in reading order and a prescribed line that could not run one step
    before the one being walked. Running it against the UNMUTATED tree only proves the tree
    equals itself; the mechanism's claim is that after a deliberate edit the recipe emits a
    constant that makes the suite green, so that is what is tested.
    """
    interpreter = _recipe_interpreter()
    mutated = SKILL.read_text(encoding="utf-8").replace(
        "Do not push with failing checks.",
        "Do not push with failing checks. Regeneration probe.",
        1,
    )
    assert "Regeneration probe." in mutated, "the probe anchor left Step 3"

    with tempfile.TemporaryDirectory() as td:
        scratch = Path(td) / "SKILL.md"
        scratch.write_text(mutated, encoding="utf-8")
        out = subprocess.run(
            [
                interpreter, "-c",
                "import sys,pathlib; sys.path.insert(0,%r); "
                "import tests.test_review_close_reference_pins as P; "
                "print(repr(P._block_canon(P._flat(P._step_3_slice("
                "pathlib.Path(sys.argv[1]).read_text())))))" % str(REPO_ROOT),
                str(scratch),
            ],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
    assert out.returncode == 0, f"the documented recipe does not run: {out.stderr}"

    regenerated = ast.literal_eval(out.stdout.strip())
    # It differs from the shipped pin (we mutated), and pasting it back makes the mutated
    # tree green — which is the re-approval loop the spec describes, executed.
    assert regenerated != STEP_3_VERBATIM, "the probe did not reach the pinned text"
    assert regenerated == _block_canon(_flat(_step_3_slice(mutated)))
    assert "Regeneration probe." in regenerated


def test_the_recipe_in_the_comment_is_the_one_the_test_runs():
    """The comment teaches a command; drift between it and the executed one is the class
    this module exists to catch, one level up."""
    body = Path(__file__).read_text(encoding="utf-8")
    comment = body.split("STEP_3_VERBATIM_LEN")[0]
    for fragment in (
        "import tests.test_review_close_reference_pins as P",
        "P._block_canon(P._flat(P._step_3_section()))",
    ):
        assert fragment in comment, f"the recipe comment lost {fragment!r}"
    assert "git rev-parse --git-common-dir" in comment, (
        "the recipe must resolve the interpreter with --git-common-dir: a relative "
        ".venv/bin/python3 exits 127 in a worktree, and --show-toplevel returns the WORKTREE "
        "rather than the primary checkout, so it reproduces the same 127 (Phase 234)"
    )
    # Scoped to the COMMAND lines, not the prose: the comment deliberately names
    # `--show-toplevel` to say why it is wrong, and a whole-comment ban would redden on the
    # sentence that states the rule — the over-strictness direction that hides.
    command_lines = [
        ln for ln in comment.splitlines()
        if "rev-parse" in ln and ln.lstrip().startswith("#")
        and ("$(" in ln or "python3" in ln)
    ]
    assert command_lines, "the recipe's command line vanished from the comment"
    assert not any("--show-toplevel" in ln for ln in command_lines), (
        "--show-toplevel answers 'which worktree am I standing in'. A first draft of this "
        "recipe used it and exited 127 in exactly the case it claimed to fix; this assertion "
        "exists so the defect cannot come back the way it arrived."
    )


# --- Phase 295's round: twelve shipped pointers into a heading nothing pinned ------------------

_PROVENANCE_POINTER = re.compile(r"See REFERENCE\.md, section (Step [0-9a-z]+ — provenance)\.")


def test_every_provenance_pointer_resolves_to_a_real_reference_heading():
    """A `See REFERENCE.md, section <X>` pointer must name a heading that exists.

    Filed by Phase 295's round. That phase shipped twelve of these pointers into
    `SKILL.md`, and `grep -rn "See REFERENCE.md, section" tests/` returned ZERO — the roster
    parser matches only ``^## `RC-…` ``, so `## Step 3b — provenance` was pinned by nothing.
    Renaming or deleting that heading would have dangled all twelve silently, which is § 7.6's
    "no empty sections" rule having no actuator.

    This is the cheap half — that the destination exists. It deliberately does NOT claim the
    section says anything about the block that points at it; all twelve pointers in that phase
    are identical and name one multi-subsection heading, so no pointer identifies its own
    referent. That is recorded as known debt rather than asserted here.
    """
    skill = SKILL.read_text(encoding="utf-8")
    reference = REFERENCE.read_text(encoding="utf-8")
    pointers = _PROVENANCE_POINTER.findall(skill)
    assert pointers, (
        "no provenance pointers found in SKILL.md — either the thinning campaign's pointer shape "
        "changed or this guard has lost its population"
    )
    headings = set(re.findall(r"^## (Step [0-9a-z]+ — provenance)\s*$", reference, re.M))
    dangling = sorted({p for p in pointers if p not in headings})
    assert not dangling, (
        f"{len(dangling)} provenance pointer target(s) do not exist as a `## <name>` heading in "
        f"REFERENCE.md: {dangling}. Known headings: {sorted(headings)}"
    )
