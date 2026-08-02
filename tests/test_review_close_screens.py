"""The screens for Phase 175's two claim classes, rebuilt after their first version failed.

`test_review_close_escape_and_skip_claims.py` ships the *pins* — verbatim sentences and
derived facts about the shipped hook. This module ships the *screens*: the checks meant to
catch a defect reintroduced in wording nobody has seen yet. The first version of those
screens was a closed list of English verbs plus a closed list of limiters, and Phase 175's
guards lens took it apart: **20 of 31 mutations survived**, both defect classes were
reintroducible at their original sites in wording an ordinary editor would produce
(`can't` → `won't`; "the merged-tree pass" for "4a-post"; the promise in passive voice),
and **4 of 9 legitimate rewrites went red**, two of them sentences that are *true of the
shipped hook*. A screen that is wrong in both directions at once is not a screen.

What replaced it, and why each layer exists — every one of these is a survivor from that
battery, kept as a named case below so the shape cannot come back unnoticed:

1. **A forbidden-verb zone in the two paragraphs where the promise is false.** The old
   design asked "is this sentence backed?" and excused it if *any* backticked span in it
   matched the hook — so a false `gh pr` promise laundered itself by mentioning
   `git push origin main` in the same breath. In the two paragraphs whose whole subject is
   a command the hook does **not** match, no positive coverage verb is legitimate at all,
   in any voice or tense. A blanket ban over a small area beats a clever test over a large
   one.

2. **Paragraph scope, not sentence scope, everywhere else.** Sentence scope is what
   punished the true sentences: a sound promise whose backing command sits in the *next*
   sentence went red, and so did an accurate description of the hook's own venv-prefixed
   output. Paragraphs are the unit an editor actually moves.

3. **A pinned mention census.** Any *new* paragraph anywhere in the shipped corpus that
   talks about this hook trips the count and has to be classified deliberately. This is the
   `check_no_fourth_code_extension_list` shape the merged-tree module already uses: the
   guard cannot know whether a claim nobody has written yet is true, so it makes writing
   one a review event.

4. **Predicate-scoped harmlessness screening.** The old regex fired on `doc-only … never`
   regardless of what followed, so it reddened *"A doc-only cycle never bypasses this
   gate"* — prose strengthening the very rule it guards — while missing `won't regress`,
   `docs-only`, and the plural. It now keys on the claim's object (regress / break /
   affect / reach), which is the part that makes such a sentence false.

5. **Negation that attaches.** A 60-character window let a relative clause supply the
   negation for a verb it did not negate (*"`4a-post`, whose surface gate cannot arm
   anything, inherits item 4's skip"*). The lead is now truncated at the nearest clause
   boundary, so a negation in a different clause does not count.

6. **The gate's synonyms, and its fenced instructions.** The screen keyed on the literal
   `4a-post` while the file calls it "the merged-tree pass" throughout, and it stripped
   fenced blocks — where a `#` comment is an instruction a literal executor reads.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEW_CLOSE = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"
SKILLS_DIR = REPO_ROOT / "core" / "skills"
DOCS = REPO_ROOT / "core" / "companion" / "docs"
WORKFLOW = DOCS / "WORKFLOW.md"
WORKFLOW_GUIDE = DOCS / "WORKFLOW_GUIDE.md"


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _text() -> str:
    return REVIEW_CLOSE.read_text(encoding="utf-8")


def _paragraphs(text: str) -> list[str]:
    return [_flat(p) for p in re.split(r"\n\s*\n", text) if p.strip()]


def _fence_comment_lines(text: str) -> list[str]:
    """`#` comments inside fenced blocks.

    Prose screens strip fences, because a report template holds `skipped` as a slot rather
    than an assertion. But a comment inside a fenced block of this skill is an instruction
    an executor reads, and a survivor planted one there: `# On a doc-only assembled diff,
    4a-post inherits item 4's skip`. Invisible to every guard.
    """
    out = []
    for block in re.findall(r"```.*?```", text, flags=re.S):
        out.extend(_flat(ln) for ln in block.splitlines() if ln.lstrip().startswith("#"))
    return out


def _prose_only(text: str) -> str:
    return re.sub(r"```.*?```", " ", text, flags=re.S)


# ===========================================================================
# Layer 1 — the two paragraphs where any positive coverage claim is false
# ===========================================================================

# Identified by a stable phrase each paragraph must keep (pinned in the sibling module),
# not by line number.
FALSE_SITE_ANCHORS = {
    "Step 3b's mkdir/cp collect": "Deliberate non-entries.",
    "Step 4d's denied `gh pr`": "If a `gh pr` command is silently denied",
}

# Any verb by which a hook could be said to supply guidance. Deliberately broad: inside
# these two paragraphs there is no true sentence that needs one.
COVERAGE_VERB_RE = re.compile(
    r"\b(?:surfaces?|surfacing|surfaced|shows?|prints?|emits?|provides?|supplies|"
    r"relays|rescues?|hands\s+you|fires\s+on|covers?|will\s+surface|is\s+surfaced)\b",
    re.I,
)
# ...except where the sentence is denying it. These paragraphs must be free to say what
# the hook does NOT do, and to name the three shapes it does cover elsewhere.
DENIAL_RE = re.compile(
    r"\bno\s+hook\b|\bnothing\b|\bnot\b|\bnever\b|matches?\s+only|emits\s+nothing|"
    r"\bonly\b|falls?\s+through|no\s+match",
    re.I,
)


def _paragraph_with(text: str, anchor: str) -> str:
    for para in _paragraphs(text):
        if anchor in para:
            return para
    raise AssertionError(f"anchor vanished from the shipped skill: {anchor!r}")


def positive_coverage_claims_in_false_sites(text: str) -> dict[str, list[str]]:
    """Sentences in the two false-site paragraphs that assert the hook supplies guidance.

    A sentence qualifies only if it carries a coverage verb and no denial. This is the
    layer that survived nothing in the first version: passive voice ("is surfaced by"),
    synonyms ("shows", "prints"), a claim split across two sentences, and a claim laundered
    by an incidental `git push origin main` span all walked past a backed-promise test.
    """
    out: dict[str, list[str]] = {}
    for label, anchor in FALSE_SITE_ANCHORS.items():
        para = _paragraph_with(text, anchor)
        bad = [
            s for s in re.split(r"(?<=\.)\s+", para)
            if COVERAGE_VERB_RE.search(s) and not DENIAL_RE.search(s)
        ]
        if bad:
            out[label] = bad
    return out


def test_neither_false_site_claims_the_hook_helps():
    offenders = positive_coverage_claims_in_false_sites(_text())
    assert not offenders, f"a hook-coverage claim is back where the hook matches nothing: {offenders}"


# Layer 2 — `gh` is the uncovered family that matters, and it can be promised from inside a
# *sound* paragraph, which neither the false-site zone nor the census would see. The hook is
# git-only by construction, so a `gh` command named next to a coverage verb is always wrong.
GH_COMMAND_RE = re.compile(r"`!?\s*gh\s+[a-z]", re.I)


def gh_coverage_claims(text: str) -> list[str]:
    bad = []
    for para in _paragraphs(_prose_only(text)):
        if not HOOK_MENTION_RE.search(para):
            continue
        for sentence in re.split(r"(?<=\.)\s+", para):
            if (GH_COMMAND_RE.search(sentence)
                    and COVERAGE_VERB_RE.search(sentence)
                    and not DENIAL_RE.search(sentence)):
                bad.append(sentence)
    return bad


def test_no_hook_paragraph_promises_coverage_for_a_gh_command():
    corpus = sorted(SKILLS_DIR.glob("*/SKILL.md")) + [WORKFLOW, WORKFLOW_GUIDE]
    offenders = {p.relative_to(REPO_ROOT).as_posix(): c
                 for p in corpus if (c := gh_coverage_claims(p.read_text(encoding="utf-8")))}
    assert not offenders, f"`gh` coverage promised where the hook is git-only: {offenders}"


def test_the_gh_screen_reds_on_a_promise_planted_in_a_sound_paragraph():
    """Known-positive: the shape neither the false-site zone nor the census can see."""
    assert gh_coverage_claims(
        "The Phase 36 `PermissionDenied` hook fires here, and it surfaces the "
        "`! gh pr merge 12 --squash` escape for you."
    )
    assert not gh_coverage_claims(
        "The Phase 36 `PermissionDenied` hook matches three git shapes only, so a denied "
        "`gh pr merge` surfaces nothing at all."
    )


# ===========================================================================
# Layer 3 — the mention census
# ===========================================================================

HOOK_MENTION_RE = re.compile(r"PermissionDenied|Phase 36 hook", re.I)

# Paragraph counts, per file. A new paragraph discussing this hook has to be classified by
# a human before it ships: the guard cannot judge a claim nobody has written yet.
EXPECTED_HOOK_PARAGRAPHS = {
    "core/skills/review-close/SKILL.md": 6,
    "core/companion/docs/WORKFLOW.md": 3,
}


def hook_paragraph_census() -> dict[str, int]:
    census: dict[str, int] = {}
    targets = sorted(SKILLS_DIR.glob("*/SKILL.md")) + [WORKFLOW, WORKFLOW_GUIDE]
    for path in targets:
        n = sum(1 for p in _paragraphs(path.read_text(encoding="utf-8")) if HOOK_MENTION_RE.search(p))
        if n:
            census[path.relative_to(REPO_ROOT).as_posix()] = n
    return census


def test_the_hook_mention_census_is_unchanged():
    """Adding a paragraph about this hook anywhere in the shipped corpus is a review event.

    The first version scanned `core/skills/*/SKILL.md` only, so the spec — the file the
    module itself calls the authoritative description — could carry an unbacked promise
    with nothing red. WORKFLOW_GUIDE.md is in the population at zero, deliberately: it
    currently says nothing about the hook, and the census notices if it starts.
    """
    assert hook_paragraph_census() == EXPECTED_HOOK_PARAGRAPHS


# ===========================================================================
# Layer 4/5/6 — the doc-only harmlessness and merged-gate screens
# ===========================================================================

# Keyed on the claim's OBJECT. The first version fired on `doc-only … never` whatever
# followed, reddening "A doc-only cycle never bypasses this gate" — prose that strengthens
# the rule — while missing `won't regress`, `docs-only` and the plural.
HARMLESSNESS_CLAIM_RE = re.compile(
    r"docs?-only\s+(?:diff|change|cycle|branch)s?\b[^.]{0,60}?"
    r"\b(?:can't|cannot|can\s+not|could\s+not|will\s+not|won't|never|no\s+longer|"
    r"is\s+incoherent|pins?\s+little|nothing)\b[^.]{0,40}?"
    r"\b(?:regress|break|affect|reach|touch|invalidate|behaviou?r\s+to\s+pin)",
    re.I,
)

# The gate has synonyms; the first screen knew only its name.
MERGED_GATE_RE = re.compile(r"4a-post|merged-tree\s+(?:gate|pass)", re.I)
INHERIT_VERB_RE = re.compile(r"\b(?:inherits?|inheriting|skips?|skipped|bypass(?:es|ed)?)\b", re.I)
NEGATION_RE = re.compile(r"\b(?:not|never|no|cannot|nothing)\b", re.I)
PREDICATION_WINDOW = 90


def harmlessness_claims(text: str) -> list[str]:
    """Sentences asserting a doc-only diff cannot regress/break/reach something."""
    flat = _prose_only(text)
    return [s for s in re.split(r"(?<=\.)\s+", _flat(flat)) if HARMLESSNESS_CLAIM_RE.search(s)]


def merged_gate_skip_claims(text: str) -> list[str]:
    """Claims that the merged-tree gate inherits the skip, without an attaching negation.

    Two survivors shaped this. One named the gate "the merged-tree pass" and walked past a
    screen keyed to `4a-post`. The other supplied its negation from a *different clause* —
    "`4a-post`, whose surface gate cannot arm anything on such a diff, inherits item 4's
    skip" — which a 60-character window happily accepted, so the lead is now truncated at
    the nearest clause boundary.
    """
    bad = []
    candidates = re.split(r"(?<=\.)\s+", _flat(_prose_only(text))) + _fence_comment_lines(text)
    for sentence in candidates:
        for mention in MERGED_GATE_RE.finditer(sentence):
            window = sentence[mention.end() : mention.end() + PREDICATION_WINDOW]
            verb = INHERIT_VERB_RE.search(window)
            if not verb:
                continue
            verb_at = mention.end() + verb.start()
            lead = sentence[:verb_at]
            lead = re.split(r"[,;:]", lead)[-1]  # negation must be in the verb's own clause
            if not NEGATION_RE.search(lead):
                bad.append(sentence)
                break
    return bad


def test_no_shipped_prose_claims_a_doc_only_diff_is_harmless():
    corpus = {p.relative_to(REPO_ROOT).as_posix(): p.read_text(encoding="utf-8")
              for p in sorted(SKILLS_DIR.glob("*/SKILL.md")) + [WORKFLOW, WORKFLOW_GUIDE]}
    offenders = {k: c for k, v in corpus.items() if (c := harmlessness_claims(v))}
    assert not offenders, f"harmlessness claims: {offenders}"


def test_nothing_says_the_merged_tree_gate_inherits_the_skip():
    offenders = merged_gate_skip_claims(_text())
    assert not offenders, f"the non-inheritance is contradicted: {offenders}"


# The screen that caught the round's live contradiction: Step 3's scope paragraph said
# item 3's surface gate and item 4's doc-only skip "both read the list this prints", under
# a heading scoped to *each pass*. It never names `4a-post`, so the gate screen could not
# see it. Scope the skip by its own name instead.
SKIP_BY_NAME_RE = re.compile(r"item 4'?s doc-only skip", re.I)
THIS_PASS_ONLY_RE = re.compile(
    r"this pass only|does not apply here|does not inherit|never inherits", re.I
)


def unscoped_item_four_references(text: str) -> list[str]:
    """Sentences naming item 4's doc-only skip without saying which pass owns it."""
    return [
        s for s in re.split(r"(?<=\.)\s+", _flat(_prose_only(text)))
        if SKIP_BY_NAME_RE.search(s) and not THIS_PASS_ONLY_RE.search(s)
    ]


def test_every_reference_to_item_4s_skip_says_which_pass_owns_it():
    offenders = unscoped_item_four_references(_text())
    assert not offenders, f"item 4's skip is named without being scoped to Step 3: {offenders}"


def test_the_scope_screen_reds_on_the_sentence_that_shipped():
    """Known-positive: the exact sentence the round found live, which no other guard saw."""
    assert unscoped_item_four_references(
        "**Each pass scopes itself to its own tree, with one command.** Item 3's surface "
        "gate and item 4's doc-only skip both read the list this prints:"
    )
    assert not unscoped_item_four_references(
        "Item 3's surface gate reads the list at both passes; item 4's doc-only skip reads "
        "it at this pass only, because `4a-post` does not inherit it."
    )


# Two more shapes the rebuilt screens still let through on their first run, both aimed at
# the *description* of coverage rather than at a specific command.
STEP_NUMBER_SCOPE_RE = re.compile(r"\bin\s+Steps?\s*\d", re.I)
GENERIC_OBJECT_RE = re.compile(
    r"\b(?:any|every|all|each)\s+(?:close-critical\s+)?(?:command|denial|invocation|call)s?\b"
    r"|\bany\s+denied\b|\bwhatever\s+is\s+denied\b",
    re.I,
)


def scope_by_step_number_claims(text: str) -> list[str]:
    """Coverage described as a step range instead of the matcher set.

    This is the shape the phase identified as the *origin* of the false `gh pr` claim —
    Step 4d runs `gh pr` under `pr` policy, so "the git patterns in Steps 4c/4d/6" reads as
    a promise about it. The first screen pinned one literal wording of that sentence and a
    survivor dropped a single adjective to evade it.
    """
    bad = []
    for para in _paragraphs(_prose_only(text)):
        if not HOOK_MENTION_RE.search(para):
            continue
        bad += [s for s in re.split(r"(?<=\.)\s+", para)
                if STEP_NUMBER_SCOPE_RE.search(s) and COVERAGE_VERB_RE.search(s)]
    return bad


def generic_coverage_claims(text: str) -> list[str]:
    """Coverage claimed over an open-ended class of commands.

    The hook matches three shapes. Any sentence promising it handles "any close-critical
    command" or "every denial" is false whatever else the paragraph says — and a survivor
    planted exactly that in the spec, where the census could not see it because it joined
    an existing paragraph.
    """
    bad = []
    for para in _paragraphs(_prose_only(text)):
        if not HOOK_MENTION_RE.search(para):
            continue
        bad += [s for s in re.split(r"(?<=\.)\s+", para)
                if GENERIC_OBJECT_RE.search(s) and COVERAGE_VERB_RE.search(s)
                and not DENIAL_RE.search(s)]
    return bad


def _hook_corpus() -> dict[str, str]:
    return {p.relative_to(REPO_ROOT).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(SKILLS_DIR.glob("*/SKILL.md")) + [WORKFLOW, WORKFLOW_GUIDE]}


def test_no_shipped_prose_scopes_hook_coverage_by_step_number():
    offenders = {k: c for k, v in _hook_corpus().items() if (c := scope_by_step_number_claims(v))}
    assert not offenders, f"coverage described by step range again: {offenders}"


def test_no_shipped_prose_claims_open_ended_hook_coverage():
    offenders = {k: c for k, v in _hook_corpus().items() if (c := generic_coverage_claims(v))}
    assert not offenders, f"open-ended hook coverage promised: {offenders}"


def test_the_two_description_screens_red_on_their_survivors():
    assert scope_by_step_number_claims(
        "The `PermissionDenied` hook covers the git patterns in Steps 4c/4d/6."
    )
    assert generic_coverage_claims(
        "When any close-critical command is denied mid-cycle, though, the Phase 36 "
        "`PermissionDenied` hook surfaces the `!`-escape form to relay."
    )
    # ...and stay quiet on the shipped forms, which name the matcher set.
    assert not scope_by_step_number_claims(
        "Phase 36's `PermissionDenied` hook surfaces guidance for exactly three shapes."
    )
    assert not generic_coverage_claims(
        "The `PermissionDenied` hook matches three git shapes only, so any other denied "
        "command surfaces nothing."
    )


def test_the_spec_keeps_the_second_conjunct_by_name():
    """A survivor kept the pinned substring `Skipped for a doc-only diff` while dropping the
    conjunct that makes the sentence true, and evaded the verbatim-string screen."""
    line = next(ln for ln in WORKFLOW.read_text(encoding="utf-8").splitlines()
                if "Skipped for a doc-only diff" in ln)
    assert "## Prevention Conventions" in line, (
        "WORKFLOW.md's Step 2b gloss dropped its second conjunct — the extension test alone "
        "silences conventions that govern non-code files"
    )


# ===========================================================================
# The battery, kept — every case below is a mutation that SURVIVED the first
# version of these screens, or a legitimate rewrite that wrongly went red.
# ===========================================================================

MUST_CATCH_FALSE_SITE = {
    "S1 laundered by an incidental covered span": (
        "**Deliberate non-entries.** For a denied `gh pr merge`, the hook surfaces the "
        "`!`-escape exactly as it does for `git push origin main`."
    ),
    "S2a passive voice": (
        "**Deliberate non-entries.** In current builds the `!`-escape form is surfaced "
        "automatically by the Phase 36 `PermissionDenied` hook for this denial as well."
    ),
    "S2b synonym verb": (
        "**Deliberate non-entries.** On recent installs the Phase 36 hook now also shows "
        "the ready-made `!`-escape for denied `gh pr` commands."
    ),
    "S2c split across two sentences": (
        "**Deliberate non-entries.** The Phase 36 hook does fire on this class of denial "
        "too. Follow the guidance it relays and continue."
    ),
    "S4 branch-context laundering": (
        "**Deliberate non-entries.** If the executor's `git commit` inside the worktree is "
        "denied, the Phase 36 `PermissionDenied` hook surfaces the `!`-escape to relay."
    ),
    "S5 step-number hedge without the pinned adjective": (
        "**Deliberate non-entries.** The hook covers the git patterns in Steps 4c/4d/6."
    ),
}

MUST_CATCH_HARMLESSNESS = {
    "S7a can't -> won't": "In the common case this is also safe: a doc-only diff won't regress code-level lint or typecheck.",
    "S7b docs-only spelling": "A docs-only diff cannot regress code-level lint or typecheck, after all.",
    "S7c plural": "Doc-only diffs never regress the build.",
    "S13 British spelling of the 2d rationale": "A test decision over a doc-only change pins little — there is no behaviour to pin.",
    "the original": "This skip applies to both sections — a doc-only diff can't regress code-level lint/typecheck.",
}

MUST_CATCH_MERGED_GATE = {
    "S8 the gate's synonym": "The merged-tree pass inherits this skip as well — a docs cycle that skipped here skips there too.",
    "S9 negation in a different clause": "Note that `4a-post`, whose surface gate cannot arm anything on such a diff, inherits item 4's skip in that spirit.",
    "S14 a fenced instruction comment": "# On a doc-only assembled diff, 4a-post inherits item 4's skip: echo SKIP and go to 4b",
    "the plain form": "In practice `4a-post` inherits Step 3's doc-only skip, so a docs cycle runs no verification at all.",
}

MUST_NOT_RED = {
    # Lens 1's NC-A3 was a rewrite of the SOUND push site, not of a false-site paragraph —
    # the first draft of this fixture put it in the wrong zone. Under the new design there
    # is no sentence-level backed-promise test for it to red, which is the fix.
    "NC-A3 backing command one sentence away, at a sound site": (
        "…the Phase 36 hook surfaces the ready-made escape command. Type "
        "`! git push origin main` at the next prompt."
    ),
    "NC-A5 a TRUE description of the hook's venv variant": (
        "When a `.venv/` exists the hook surfaces the "
        "`! PATH=.venv/bin:$PATH git push origin main` variant as well."
    ),
    "NC-B2 prose that strengthens the gate": "A doc-only cycle never bypasses this gate.",
    "NC-B3 the shipped negated form": "`4a-post` is never skipped because Step 3 was.",
    "NC-B4 the shipped non-inheritance": "`4a-post` therefore does not inherit this skip.",
    "NC-B5 the shipped positive statement": "a diff that is doc-only by this test can regress lint, typecheck and build directly",
    "NC-B6 the shipped scoping sentence": "no diff-shape heuristic skips a list the consumer declared.",
}


@pytest.mark.parametrize("label", sorted(MUST_CATCH_FALSE_SITE))
def test_false_site_screen_catches_every_survivor(label):
    text = "# x\n\n" + MUST_CATCH_FALSE_SITE[label] + "\n\n**If a `gh pr` command is silently denied** nothing happens.\n"
    assert positive_coverage_claims_in_false_sites(text), f"{label} still walks past the screen"


@pytest.mark.parametrize("label", sorted(MUST_CATCH_HARMLESSNESS))
def test_harmlessness_screen_catches_every_survivor(label):
    assert harmlessness_claims(MUST_CATCH_HARMLESSNESS[label]), f"{label} still walks past the screen"


@pytest.mark.parametrize("label", sorted(MUST_CATCH_MERGED_GATE))
def test_merged_gate_screen_catches_every_survivor(label):
    probe = MUST_CATCH_MERGED_GATE[label]
    if probe.startswith("#"):
        probe = "```bash\n" + probe + "\n```"
    assert merged_gate_skip_claims(probe), f"{label} still walks past the screen"


@pytest.mark.parametrize("label", sorted(MUST_NOT_RED))
def test_no_screen_punishes_correct_prose(label):
    probe = MUST_NOT_RED[label]
    assert not harmlessness_claims(probe), f"{label} reddened the harmlessness screen"
    assert not merged_gate_skip_claims(probe), f"{label} reddened the merged-gate screen"
    if "Deliberate non-entries." in probe:
        assert not positive_coverage_claims_in_false_sites(probe), (
            f"{label} reddened the false-site screen — it is a true sentence"
        )
