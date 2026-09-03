"""Phase 167 — `/review-close` reads the revision it is actually gating.

Two defects in one skill, both fixed here, both prose:

**Step 2d read the wrong tree (Wave 1 item 5).** The Phase-59 test-decision gate resolved
the task body as a plain relative path. `/claim-task` *decides* the record at plan time but
the reviewer-executor *writes* it inside the worktree, so it is committed on the feature
branch; Step 2d runs at Step 2, and nothing merges until Step 3b/4a. So the path resolved
to `main`'s copy, which carries no test-decision heading at all — every shipped body-author
is told not to write one — and the gate classified the record `missing` for every task on
every code-touching branch, every run.

**Step 6's `git reset --hard origin/<default branch>` was ungated tree-wide (folded in per the fix-wave
brief).** Its prose explained only which *commits* it discards; it also discards every
uncommitted modification to a tracked file in the main checkout, and nothing gated it.

**This module was rewritten after its own adversarial round, which disqualified the first
version.** A reviewer ran 90 mutations against it and **43 were genuine bypasses**. The
defect was uniform: eight of nine checks asserted that a *token* appeared somewhere in a
line, and a line in this file is routinely a 700-character paragraph — so "N phrases in a
sentence asserting the opposite" walked straight through. Three demonstrated survivors,
each of which would have shipped the defect the phase exists to remove:

* `**1. Read the record.** Read the body from the working tree … Do **not** read it **at
  the branch tip** with `git show …`, and ignore the older instruction that said "never the
  working-tree copy".` — contains all three required tokens, means the reverse.
* `git diff --quiet HEAD -- && echo "DIRTY …" || echo "CLEAN — safe to reset"` — the arms
  swapped. `git diff --quiet` exits 0 when clean, so this fires `reset --hard` **exactly
  when it destroys work**. The old ordering check searched for the gate with a bare
  substring `find`, so even commenting the gate out kept it green.
* `**This is not `missing`: it is a stricter form of it, so classify it `missing` and
  continue —**` — satisfied a check whose entire job was keeping those two apart.

**So the primitive changed.** Load-bearing sentences are now **pinned verbatim, normalised
for whitespace** (`_flat`). Rewrapping a paragraph, reflowing a bullet, or changing
indentation does not break a pin; changing the *words* does. That is the deliberate
trade-off from `test_review_close_diff_basis.py`'s rule 1 — a reworded rationale fails,
because a reworded rationale is exactly what should come back here for re-approval — with
the whitespace noise that made the first version brittle removed. Commands additionally get
**executable-line discipline on both sides** of the ordering check, and a **contradiction
screen** (`FORBIDDEN`) blocks the specific reversals the round demonstrated, so a pin that
survives by being quoted inside a negation still fails.

**What this cannot do, stated rather than left implied.** No guard over prose proves
semantics. Pins convert silent drift into a deliberate re-approval; they do not stop someone
who re-approves a bad edit. The contradiction screen is a blocklist and blocklists are
incomplete by construction. `MUTATIONS` therefore carries the round's demonstrated bypasses
as permanent regression tests rather than a claim that the class is closed.

**Not every check is a pure function of the skill text.** `check_the_cited_spec_still_says_
what_is_cited` reads the two spec docs instead, on purpose: Step 2d's note *cites* them as
what it restores, so a drift there makes the shipped note false while every skill-scoped
assertion stays green. Deriving a guard's population from the source of truth rather than
from the file under test is the rule that catch came from. It has its own negative control,
because the mutation table only edits the skill and cannot reach it.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

import pytest

from _reversal import assert_no_reversal, slice_between

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"
WORKFLOW = REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md"
GUIDE = REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW_GUIDE.md"

# `None` as the end marker means "to end of file", used only for the final section. It is
# NOT a fallback for a missing marker — a *named* end marker that cannot be found fails
# closed (see `_slice`), because that is the case where the window silently widens.
SECTIONS: dict[str, tuple[str, str | None]] = {
    "2d": ("### 2d. Test-Decision Verification", "## Step 3: Run Verification"),
    "2a": ("### 2a. Feature Branches", "### 2b. Prevention Convention Check"),
    "step6": ("## Step 6: Clean Up", "**`direct` policy — per-branch cleanup.**"),
    "step8": ("## Step 8: Report", None),
}

GATE_CMD = 'git diff --quiet HEAD -- && echo "CLEAN — safe to reset" || echo "DIRTY — STOP, see below"'
RESET_CMD = "git reset --hard origin/<default branch>"


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Whitespace-collapsed. A pin then survives rewrapping, reflowing and indentation
    changes — the 15 innocent edits that broke the first version — while any change to the
    words themselves still fails it."""
    return re.sub(r"\s+", " ", text)


def _slice(text: str, key: str) -> str:
    """Section between two literal markers.

    Returns `""` when EITHER marker is missing. The first version returned `text[a:]` when
    only the end marker was absent, which silently widened the Step 2d window from 7,890 to
    96,821 characters — so renaming a downstream heading let content from anywhere later in
    the file satisfy a 2d assertion. Fail closed instead; the empty section then fails every
    check that reads it, which is what a restructured file should do.
    """
    start, end = SECTIONS[key]
    a = text.find(start)
    if a < 0:
        return ""
    if end is None:
        return text[a:]
    b = text.find(end, a)
    if b <= a:
        return ""
    return text[a:b]


def _exec_lines(section: str) -> list[str]:
    """Lines inside a ```bash fence, comments dropped. Both sides of the ordering check use
    this — the first version applied it to the reset and used a bare substring search for
    the gate, so a commented-out or prose-only gate satisfied "the gate comes first"."""
    out, in_fence = [], False
    for raw in section.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_fence = stripped != "```"
            continue
        if not in_fence or not stripped or stripped.startswith("#"):
            continue
        out.append(stripped)
    return out


# --------------------------------------------------------------------------------------
# Pins — load-bearing sentences, verbatim (whitespace-normalised)
# --------------------------------------------------------------------------------------

PINS: list[tuple[str, str, str]] = [
    # (section key, verbatim span, why it is load-bearing)
    ("2d",
     "**Read the record at the branch tip — not out of the working tree.**",
     "the note's own thesis. Rewriting this heading to 'read from the working tree; the "
     "branch-tip read is retired' inverted the whole section past the first version's checks."),
    ("2d",
     "(path resolved exactly as in Step 2a step 3",
     "`path` is load-bearing: the PATH comes from main's index, the CONTENT from the branch. "
     "Dropping the word collapses the distinction the fix is made of."),
    ("2d",
     'Read the body **at the branch tip** (`git show "<branch>:<repo-root-relative body path>"`, resolved and quoted per the note above — never the working-tree copy)',
     "the instruction that performs the read; the whole defect is which revision it names"),
    ("2d",
     # No leading `- `: the list marker is presentation, and pinning it made a `-`→`*`
     # reformat go red for no semantic reason — the over-strictness that trains people to
     # weaken guards.
     "**`unreadable`** — `git show` did not hand you the file at the branch tip",
     "the classification's opening. A round mutation relabelled it 'not reachable in any "
     "shipped flow; documentation only' and kept every other token intact."),
    ("2d",
     "Surface the branch, the path you resolved, the revision you read, and **which of "
     "the four outcomes you got**",
     "what `unreadable` actually does. Replacing it with 'do not surface it and do not halt' "
     "makes the classification inert while its other pins hold. Phase 219 added the fourth "
     "clause: the four outcomes have different causes, and the disposition used to collapse "
     "them into one — including an exit-0 read of the WRONG revision that looks like success."),
    ("2d",
     "`WORKFLOW_GUIDE.md` § Merge Process already says to read \"**the branch's** `## Test decision`\" back against the diff, so the branch-tip read restores the spec rather than inventing a rule",
     "the citation that makes this an alignment rather than a preference. It is the skill-side "
     "half of `check_the_cited_spec_still_says_what_is_cited`, which by design reads only the "
     "spec docs and so cannot see this sentence being deleted or negated."),
    ("2d",
     "carries **no test-decision heading at all**",
     "the actual pre-fix mechanism. An earlier draft said the body held the schema's template "
     "placeholder — false: intake, add-task and onboard all forbid writing the section, so the "
     "body has no heading. The round caught it contradicting this phase's own Invariant-13 filing."),
    ("2d",
     "for every task on every branch on every run",
     "the scoped claim, RE-SCOPED BY PHASE 175 and deliberately, not by weakening this pin. "
     "Phase 167 wrote 'every *code-touching* branch' because step 0's doc-only skip exited "
     "before the record was read, so doc-only branches were spared and the unqualified form "
     "was false. Phase 175 gave that skip a second conjunct — the record must classify "
     "`no-test` — which means the read now happens first and a `missing` classification does "
     "not earn the skip. Nothing is spared any more, so the unqualified claim is the true one "
     "and the narrowing is what would now be false. P6 below inverts accordingly."),
    ("2d",
     "**Nothing spares one**",
     "the half Phase 167's scoping used to carry implicitly. Stated outright because the "
     "reason it is true now lives in a different step (2d's step 0), and a reader diagnosing "
     "a mass-`missing` halt using this note would otherwise expect doc-only branches to have "
     "been spared and mis-localize the cause."),
    ("2d",
     "`body:` is canonically relative to `tasks/` — `open/<TASK-ID>.md`, NOT",
     "the path rule. Getting this wrong makes `git show` fatal on a DEFAULT install, which the "
     "`unreadable` arm then reports as a branch problem — the first version of this fix shipped "
     "exactly that, asserting `body:` was repo-root-relative when schema.md says the opposite."),
    ("2d",
     'git show "<branch>:tasks/<body as recorded>"',
     "the canonical-shape command, quoted. Unquoted, `<…>` is a bash redirection, not a placeholder."),
    ("2d",
     'git show "<branch>:<body as recorded>"',
     "the back-compat-shape command, quoted."),
    ("2d",
     "**Before believing it, re-check the `tasks/` prefix rule above — a mis-resolved path produces this identical fatal, and that is the likelier cause.**",
     "without this, the likeliest cause of the fatal is the one the reader is steered away from"),
    ("2d",
     "**None of the four is `missing`:** nothing has been asserted about the record either way, and reporting it as `missing` would put a fabricated finding in front of the human.",
     "keeps `unreadable` and `missing` apart. Collapsing them reports a fabricated finding."),
    ("2d",
     "**`missing`** — no test-decision heading **at the branch tip**",
     "the missing arm must say which revision it looked at"),
    ("2d",
     "**On any discrepancy, missing record, or unreadable body, halt and ask**",
     "the halt must cover the fourth classification, or `unreadable` is inert"),
    ("2d",
     "**the revision you read it from**",
     "the human cannot adjudicate a record without knowing which tree it came from"),
    ("2d",
     "Tally per task: `verified`, `waived`, `not owed`, `held for fix` (now rejected), `unreadable`, or `skipped (doc-only)`",
     "Step 2d's own tally"),
    # --- the fourth disposition (Phase 249). `waived` and `not owed` answer two different
    # --- questions; the whole value of the split is that the tally keeps them apart.
    ("2d",
     "**`waived` and `not owed` are counted separately and must not be merged back into one number**",
     "the anti-conflation rule. Merging them restores the exact ambiguity the disposition "
     "was added to remove, and does it while still listing four dispositions."),
    ("2d",
     "*offered only when the ownership probe said `CANNOT TELL`, and only on a `missing` record.*",
     "the scoping. Offered unconditionally, `not owed` becomes a quieter waiver available "
     "for a record that was demonstrably owed."),
    ("2d",
     "**Lock present → the record was owed.** Do **not** offer *record not owed* for this task.",
     "the one direction the lock actually decides. Without it 2b is decoration."),
    ("2d",
     "**Never render absence as \"the orchestrator did not run\"**",
     "the three-valued rule. Absence of a gitignored runtime artifact is not evidence, and "
     "a gate that reads it as evidence accuses honest consumers."),
    ("2d",
     "every one of the 378 tasks missing a record is in the run-directory-absent bucket",
     "the measurement that disqualified the run-directory detector as a RETROSPECTIVE "
     "proxy. Losing it invites the next phase to rebuild it."),
    # The round's claims lens found the first version of this note using that measurement
    # to justify the artifact that shipped. It cannot: the same test is WORSE for the lock.
    ("2d",
     "**0 locks survive against 29 run directories**",
     "the symmetric disclosure. The first version named the reap for run directories and "
     "not for locks, which let a retrospective measurement read as a reason to prefer the "
     "lock when it is evidence against it."),
    ("2d",
     "The real reason is **structural, and it is about the direction this signal is used in.**",
     "the argument that actually carries the choice. Without it the paragraph is a "
     "measurement with no conclusion attached."),
    ("2d",
     "For a withholding use, over-inclusion costs a waiver and under-inclusion lets a genuine miss be dismissed as unowed",
     "why BROADER is correct here. A future reader optimising for precision would swap in "
     "the narrower artifact and silently re-open the dismissal this step exists to block."),
    ("2a",
     "Read it **at the branch tip**, per Step 2d's revision note: a branch edits its own body, and the working tree is still `main`.",
     "the sibling site — same body, same plain-path defect, one step over"),
    ("2a",
     "there is no `tasks/in_progress/` directory in any shipped layout",
     "the false path gloss this sentence used to carry, for the status every claimed task is in"),
    ("step6",
     "Untracked files are NOT at risk",
     "the reason the gate tests `git diff HEAD` and not bare porcelain; losing it invites the "
     "over-refusal that would block every close"),
    ("step6",
     "**If that printed `DIRTY`, do not run the reset.**",
     "the refusal itself. A round mutation licensed it away in place with an `unless` clause."),
    ("step6",
     "**Resume at this gate, not at the top of the skill**",
     "the PR has already merged; re-entering earlier re-runs steps that must not repeat"),
    ("step6",
     "**Do not stash on their behalf** — a stash this skill creates is consumed by no later step",
     "a stash relocates the work instead of surfacing it. A round mutation retired the rule "
     "in place while keeping its literal text."),
    ("step6",
     "**Narrower than the shipped convention, deliberately.**",
     "both shipped maps demand a confirmation step on `git reset --hard`; the narrowing has to "
     "read as a decision, or the next auditor files it as a violation"),
    ("step6",
     "This gate confirms *conditionally* — it refuses only when the reset would actually destroy something",
     "the substance of the narrowing, not just its heading"),
    ("step6",
     "once the clean-tracked-tree gate above passes",
     "the both-shapes note; a partial revert here restores 'run the reset in both shapes' "
     "unconditionally and no other pin covers it"),
    ("step8",
     "Test decisions: <N verified, N waived, N not-owed, N held-for-fix, N unreadable, N doc-only>",
     "the report a human actually reads. The first version tallied `unreadable` in Step 2d and "
     "never added it here, while the check that claimed to cover 'Step 8's tally' read Step 2d."),
]

# Contradiction screen. A pin can in principle survive by being quoted inside a negation;
# these are the specific reversals the round demonstrated, blocked outright. A blocklist is
# incomplete by construction — it backs the pins up, it does not replace them.
FORBIDDEN: list[tuple[str, str, str]] = [
    ("2d", "read the body from the working tree", "reverses the read instruction"),
    ("2d", "classify it `missing` and continue", "collapses `unreadable` into `missing`"),
    ("2d", "is *not* a halt condition", "exempts `unreadable` from the halt"),
    ("2d", "fold it into `missing`", "collapses the classification in the tally"),
    ("2d", "count `not owed` as a waiver", "restores the conflation the split removed"),
    ("2d", "offer it whenever the record is missing", "unscopes the fourth disposition"),
    ("2d", "the run directory is the signal", "rebuilds the proxy the measurement rejected"),
    ("2a", "**not at the branch tip**", "reverses the sibling read"),
    ("step6", "stash for them", "reverses the no-stash rule"),
    ("step6", "git clean", "falsifies the untracked-files-are-safe claim in place"),
    ("step6", "does not confirm at all", "retires the narrowing rather than stating it"),
]


# --------------------------------------------------------------------------------------
# Checks — pure functions of the skill text, except where a docstring says otherwise
# --------------------------------------------------------------------------------------

def check_pinned_sentences_are_intact(text: str) -> list[str]:
    bad: list[str] = []
    for key, span, why in PINS:
        section = _flat(_slice(text, key))
        if _flat(span) not in section:
            bad.append(f"[{key}] pin lost or reworded — {why} :: {span[:70]!r}")
    return bad


def check_no_contradiction_of_a_pin(text: str) -> list[str]:
    bad: list[str] = []
    for key, phrase, why in FORBIDDEN:
        if _flat(phrase) in _flat(_slice(text, key)):
            bad.append(f"[{key}] contradicts a pinned rule ({why}): {phrase!r}")
    return bad


def check_the_gate_is_executable_correctly_armed_and_first(text: str) -> list[str]:
    """Ordering AND semantics. The arms matter: `git diff --quiet` exits 0 when CLEAN, so a
    swapped pair resets exactly when it would destroy work — pinned verbatim, both sides
    resolved from fenced command lines only."""
    section = _slice(text, "step6")
    execs = _exec_lines(section)
    bad: list[str] = []
    gate_idx = [i for i, ln in enumerate(execs) if ln.startswith("git diff --quiet")]
    reset_idx = [i for i, ln in enumerate(execs) if ln.startswith(RESET_CMD)]
    if not gate_idx:
        bad.append("Step 6 has no executable clean-tree gate (a prose mention does not count)")
    else:
        if execs[gate_idx[0]] != GATE_CMD:
            bad.append(
                "the gate line is not the pinned form — check the arm direction, "
                f"`git diff --quiet` exits 0 when CLEAN. Got: {execs[gate_idx[0]]!r}"
            )
    if not reset_idx:
        bad.append("Step 6 has no executable `git reset --hard origin/<default branch>`")
    if len(reset_idx) > 1:
        # Gating the first occurrence is worthless if a second one ships behind it. Found by
        # a post-rewrite battery: the ordering assertion alone compared first-to-first.
        bad.append(f"Step 6 has {len(reset_idx)} executable resets; only the first is gated")
    if len(gate_idx) > 1:
        bad.append(f"Step 6 has {len(gate_idx)} executable gates — which one guards the reset?")
    if gate_idx and reset_idx and gate_idx[0] > reset_idx[0]:
        bad.append("the clean-tree gate is positioned AFTER the reset it gates")
    return bad


def check_no_untracked_inclusive_porcelain_in_step6(text: str) -> list[str]:
    """Over-strictness is the direction that hides: a bare `--porcelain` refuses on any
    untracked file, which `reset --hard` never touches. Scanned over the flat section, not
    over line starts — the report command sits mid-prose, and mid-prose is exactly where the
    first version's line-anchored scan could not see it."""
    flat = _flat(_slice(text, "step6"))
    bad: list[str] = []
    for m in re.finditer(r"git status --porcelain", flat):
        tail = flat[m.end():m.end() + 24]
        if tail.startswith(" --untracked-files=no") or tail.startswith(" -uno"):
            continue
        # Allowlisted, not pattern-excluded: the gate comment names the bare form in order
        # to explain why the gate does NOT use it. The literal "a bare `" prefix is what
        # marks it as the anti-pattern being described rather than a command being
        # prescribed, so dropping that framing re-arms this check.
        if flat[max(0, m.start() - 8):m.start()] == "a bare `":
            continue
        bad.append(f"untracked-inclusive porcelain in Step 6: ...{flat[m.start():m.end() + 24]!r}")
    return bad


def check_sections_resolve(text: str) -> list[str]:
    """Reachability. Every pin is scoped to a section, so a section that fails to resolve
    would silently disarm its pins — except `_slice` fails closed, which turns that into a
    loud failure here rather than a quiet pass."""
    return [f"section {key!r} does not resolve" for key in SECTIONS if not _slice(text, key)]


def check_the_cited_spec_still_says_what_is_cited(text: str) -> list[str]:
    """Population derived from the source of truth, not from the file under test. Step 2d's
    note cites these two docs as what the branch-tip read restores; drift there makes the
    shipped note false while every skill-scoped pin stays green. `text` is deliberately
    unused — see the module docstring."""
    del text
    return _spec_failures(
        WORKFLOW.read_text(encoding="utf-8"),
        GUIDE.read_text(encoding="utf-8"),
    )


def _spec_failures(workflow: str, guide: str) -> list[str]:
    bad: list[str] = []
    if "read the branch's `## Test decision`" not in guide:
        bad.append("WORKFLOW_GUIDE.md no longer scopes the test-decision record to the branch")
    if "each approved branch's task body" not in workflow:
        bad.append("WORKFLOW.md no longer scopes the test-decision record to the branch")
    else:
        # The note cites § 2.8 by number. Resolve the heading that actually governs the
        # sentence rather than trusting the number — a section renumber would otherwise
        # leave a stale citation in shipped skill text.
        at = workflow.index("each approved branch's task body")
        heads = [h for h in re.finditer(r"^#{2,3} .*$", workflow[:at], re.M)]
        if not heads or not heads[-1].group(0).startswith("### 2.8"):
            got = heads[-1].group(0) if heads else "<none>"
            bad.append(f"the cited WORKFLOW.md § 2.8 no longer governs that sentence (got {got!r})")
    return bad


CHECKS: list[Callable[[str], list[str]]] = [
    check_pinned_sentences_are_intact,
    check_no_contradiction_of_a_pin,
    check_the_gate_is_executable_correctly_armed_and_first,
    check_no_untracked_inclusive_porcelain_in_step6,
    check_sections_resolve,
    check_the_cited_spec_still_says_what_is_cited,
]


# --------------------------------------------------------------------------------------
# The shipped tree satisfies every check
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
def test_shipped_skill_satisfies(check):
    assert check(_text()) == []


# --------------------------------------------------------------------------------------
# Non-vacuity — the round's demonstrated bypasses, kept as permanent regression tests
# --------------------------------------------------------------------------------------

def _sub(old: str, new: str) -> Callable[[str], str]:
    def go(text: str) -> str:
        assert old in text, f"mutation source text not found: {old[:60]!r}"
        return text.replace(old, new, 1)
    return go


MUTATIONS: list[tuple[str, Callable[[str], str]]] = [
    # ---- the round's survivors, every one of which passed all nine of the old checks ----
    ("R/A1 negate the read instruction while keeping its tokens", _sub(
        'Read the body **at the branch tip** (`git show "<branch>:<repo-root-relative body path>"`, resolved and quoted per the note above — never the working-tree copy)',
        'Read the body from the working tree at the plain `body:` path. Do **not** read it **at the branch tip**, and ignore the older instruction that said "never the working-tree copy"')),
    ("R/F2 swap the gate arms (resets exactly when it destroys)", _sub(
        '&& echo "CLEAN — safe to reset" || echo "DIRTY — STOP, see below"',
        '&& echo "DIRTY — STOP, see below" || echo "CLEAN — safe to reset"')),
    # Both anchor on Step 6's ARMS, not on the bare `git diff --quiet HEAD --` prefix.
    # `_sub` replaces the FIRST occurrence, and Phase 170 added a second clean-tree probe
    # earlier in the file (`4a-post` step 5, arms `CLEAN` / `DIRTY — verification modified
    # tracked files`). Both mutations silently retargeted to it and stopped reaching Step 6
    # — they survived every check while the shipped Step 6 gate sat untouched. Anchoring on
    # the arm text keeps them pinned to the one gate they are about.
    ("R/F1 comment the gate out, leave the text present", _sub(
        GATE_CMD, "# (optional) " + GATE_CMD)),
    ("R/F3 path-scope the gate to one file", _sub(
        'git diff --quiet HEAD -- && echo "CLEAN — safe to reset"',
        'git diff --quiet HEAD -- README.md && echo "CLEAN — safe to reset"')),
    ("R/F12 move the gate into a fence after the reset", lambda t: (
        t.replace("  " + GATE_CMD + "\n", "", 1)
         .replace("  git reset --hard origin/<default branch>\n", "  git reset --hard origin/<default branch>\n  " + GATE_CMD + "\n", 1))),
    ("R/C1 collapse `unreadable` into `missing`", _sub(
        "**None of the four is `missing`:** nothing has been asserted",
        "**None of the four is `missing`: each is a stricter form of it, so classify them `missing` and continue —** nothing has been asserted")),
    ("R/D1 exempt `unreadable` from the halt", _sub(
        "**On any discrepancy, missing record, or unreadable body, halt and ask**",
        "**On any discrepancy or missing record, halt and ask** (an unreadable body is *not* a halt condition — carry it as verified)")),
    ("R/D2 tally keeps the token only to fold it away", _sub(
        "`held for fix` (now rejected), `unreadable`, or `skipped (doc-only)`",
        "`held for fix` (now rejected), or `skipped (doc-only)` — do not report `unreadable` separately, fold it into `missing`")),
    ("R/E1 invert the Step 2a sibling read", _sub(
        "Read it **at the branch tip**, per Step 2d's revision note:",
        "Read it from the working tree, **not at the branch tip** — Step 2d's revision note applies to Step 2d only:")),
    ("R/F7 license the refusal away in place", _sub(
        "**If that printed `DIRTY`, do not run the reset.**",
        "**If that printed `DIRTY`, do not run the reset unless the modifications are yours and disposable, which they usually are.**")),
    ("R/F8 retire the no-stash rule in place", _sub(
        "**Do not stash on their behalf** — a stash this skill creates",
        "**Do not stash on their behalf** was the Phase 167 rule; it is retired — stash for them. A stash this skill creates")),
    ("R/F9 drop --untracked-files=no from the report command", _sub(
        "`git status --porcelain --untracked-files=no`", "`git status --porcelain`")),
    ("R/F10 partial revert of the both-shapes note", _sub(
        "in both shapes once the clean-tracked-tree gate above passes", "in both shapes")),
    ("R/F18 retire the narrowing's substance", _sub(
        "This gate confirms *conditionally* — it refuses only when the reset would actually destroy something",
        "This step does not confirm at all")),
    ("R/L1 add `git clean -fd`, falsifying the untracked claim", _sub(
        "  git reset --hard origin/<default branch>\n", "  git reset --hard origin/<default branch>\n  git clean -fd\n")),
    ("R/B3 satisfy the causal tokens with the opposite claim", _sub(
        "carries **no test-decision heading at all**",
        "remains correct for every task; the `missing` storm had another cause entirely")),
    ("R/G5 rename the section end marker to widen the window", _sub(
        "## Step 3: Run Verification", "## Step 3: Verification Run")),
    # ---- the path/quoting defects the round found in the fix itself ----
    ("P1 assert the repo-root-relative falsehood again", _sub(
        "`body:` is canonically relative to `tasks/` — `open/<TASK-ID>.md`, NOT",
        "`body:` is already repo-root-relative, so pass it through unchanged. NOT")),
    ("P2 unquote the canonical command", _sub(
        'git show "<branch>:tasks/<body as recorded>"', "git show <branch>:tasks/<body as recorded>")),
    ("P3 drop the mis-resolved-path warning from `unreadable`", _sub(
        "**Before believing it, re-check the `tasks/` prefix rule above — a mis-resolved path produces this identical fatal, and that is the likelier cause.** ", "")),
    ("P4 drop `unreadable` from the Step 8 report template", _sub(
        "N held-for-fix, N unreadable, N doc-only", "N held-for-fix, N doc-only")),
    # ---- the fourth disposition (Phase 249) ----
    ("P8 merge the two tallies back into one number", _sub(
        "**`waived` and `not owed` are counted separately and must not be merged back into one number**",
        "Report them together as a single waiver count")),
    ("P9 unscope the fourth disposition", _sub(
        "*offered only when the ownership probe said `CANNOT TELL`, and only on a `missing` record.*",
        "Offer it for any task whose record does not verify.")),
    ("P10 invert the lock arm so a demonstrably-owed record can be dismissed", _sub(
        "**Lock present → the record was owed.** Do **not** offer *record not owed* for this task.",
        "**Lock present → the orchestrator ran.** Offer *record not owed* either way.")),
    ("P11 turn absence into an assertion about what ran", _sub(
        '**Never render absence as "the orchestrator did not run"**',
        "Read a missing lock as proof the orchestrator did not run")),
    ("P12b re-assert the measurement as the reason for the choice", _sub(
        "The real reason is **structural, and it is about the direction this signal is used in.**",
        "The measurement above is therefore why the lock was chosen.")),
    ("P12c drop the 0-vs-29 symmetry disclosure", _sub(
        "and among those 476 tasks **0 locks survive against 29 run directories**", "")),
    ("P12 drop the measurement that disqualified the run-directory proxy", _sub(
        "every one of the 378 tasks missing a record is in the run-directory-absent bucket",
        "the run directory separates the two populations cleanly")),
    ("P13 drop the fourth disposition from Step 2d's tally", _sub(
        "Tally per task: `verified`, `waived`, `not owed`,",
        "Tally per task: `verified`, `waived`,")),
    ("P5 drop the resume instruction", _sub(
        "**Resume at this gate, not at the top of the skill**", "Re-run Step 6")),
    # Inverted by Phase 175: the narrowing, not the unscoped form, is now the false claim.
    # A `missing` record no longer earns step 0's skip, so doc-only branches halt here too;
    # re-adding "code-touching" would tell a reader they are spared when they are not.
    ("P6 re-narrow the claim to code-touching branches (false since Phase 175)", _sub(
        "for every task on every branch on every run",
        "for every task on every code-touching branch on every run")),
    ("P6b drop the explicit `Nothing spares one`", _sub(
        "**Nothing spares one** — step 0's doc-only skip does not, because a `missing` classification is not the `no-test` its second conjunct requires, so a doc-only branch halts here too.",
        "")),
    ("P7 restore Step 2a's false path gloss", _sub(
        "there is no `tasks/in_progress/` directory in any shipped layout",
        "the body lives under `tasks/<status>/`")),
    # ---- population ----
    ("Z blank the whole skill", lambda t: ""),
]


@pytest.mark.parametrize("name,mutate", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_every_mutation_is_caught(name, mutate):
    shipped = _text()
    mutated = mutate(shipped)
    assert mutated != shipped, f"mutation {name!r} was a no-op — it no longer matches the shipped text"
    failures = [f for check in CHECKS for f in check(mutated)]
    assert failures, f"mutation {name!r} survived every check"


class TestTheOwnershipProbeExecutes:
    """The round's gap finding: every `D-*` row in this phase's battery is a prose pin, so
    the one new mechanism with no extract-and-run coverage was the ownership probe — in a
    phase whose whole method is that prescribed commands get executed. Closed here.

    The probe is EXTRACTED from the skill so it cannot drift from what the operator runs.
    """

    @staticmethod
    def _probe_command() -> str:
        text = _text()
        start = text.index('ls "$(git rev-parse --git-common-dir)')
        end = text.index('"CANNOT TELL', start)
        end = text.index("\n", end)
        return text[start:end]

    @staticmethod
    def _repo(tmp_path, with_lock):
        import subprocess
        root = tmp_path / "r"
        root.mkdir()
        def git(*a, cwd=root):
            subprocess.run(["git", *a], cwd=str(cwd), check=True, capture_output=True)
        git("-c", "init.defaultBranch=main", "init", "-q", ".")
        git("config", "user.email", "t@t"); git("config", "user.name", "t")
        (root / "README.md").write_text("x\n", encoding="utf-8")
        git("add", "-A"); git("commit", "-qm", "base")
        if with_lock:
            locks = root / "sysop" / "runtime" / "locks"
            locks.mkdir(parents=True)
            (locks / "FIX-ALPHA.lock").write_text("task_id: FIX-ALPHA\n", encoding="utf-8")
        return root

    def _run(self, root, task_id, cwd=None):
        import subprocess
        cmd = self._probe_command().replace("<TASK_ID>", task_id)
        r = subprocess.run(["bash", "-c", cmd], cwd=str(cwd or root),
                           capture_output=True, text=True)
        return r.stdout.strip()

    def test_a_claimed_task_reads_owed(self, tmp_path):
        root = self._repo(tmp_path, with_lock=True)
        assert self._run(root, "FIX-ALPHA").startswith("OWED")

    def test_an_unclaimed_task_reads_cannot_tell(self, tmp_path):
        root = self._repo(tmp_path, with_lock=True)
        assert self._run(root, "FIX-BETA").startswith("CANNOT TELL")

    def test_an_absent_runtime_directory_reads_cannot_tell_not_an_error(self, tmp_path):
        """A fresh clone carries no `sysop/runtime/` at all. That must read as the
        three-valued 'cannot tell', never as an error and never as 'not owed'."""
        root = self._repo(tmp_path, with_lock=False)
        assert self._run(root, "FIX-ALPHA").startswith("CANNOT TELL")

    def test_the_verdict_does_not_depend_on_the_operators_directory(self, tmp_path):
        """`--git-common-dir` is CWD-relative inside the primary. A probe that resolved it
        wrongly would answer CANNOT TELL from a subdirectory and quietly offer the fourth
        disposition for a task that was demonstrably owed a record."""
        root = self._repo(tmp_path, with_lock=True)
        deep = root / "a" / "b"
        deep.mkdir(parents=True)
        assert self._run(root, "FIX-ALPHA", cwd=deep).startswith("OWED")

    def test_it_carries_no_cd_compound(self):
        """`_shared/permission-guard.md`: read-only commands still prompt when a `cd` into
        another directory is compounded with them. This is the one standalone one-liner
        Step 2d asks an operator to run, and a gate that prompts on the dominant path is a
        gate that gets switched off."""
        assert "cd " not in self._probe_command(), self._probe_command()


def test_step_2d_gains_no_reversal_vocabulary():
    """The softening class, closed generically rather than phrase by phrase.

    The contradiction screen above is a blocklist, and a blocklist is incomplete by
    construction — this phase's own battery proved it on the entry written the same
    hour: the screen holds *"offer it whenever the record is missing"*, and
    *"In practice, offer it whenever the record does not verify"* walked straight
    past it with all 42 tests green. A second mutation put *"reporting a single
    combined waiver count is acceptable"* beside the anti-conflation rule and did
    the same.

    Zero exemptions: the slice was measured clean of the whole vocabulary when this
    was wired, so anything appearing later is new and deliberate.
    """
    step = slice_between(_text(), "### 2d. Test-Decision Verification", "### 2e.", "Step 2d")
    assert_no_reversal(step, "review-close Step 2d")


def test_the_external_population_check_is_not_vacuous():
    """The mutation table only edits the skill, so it cannot reach the check whose population
    is the two spec docs. Prove that one directly instead of letting it ride."""
    assert len(_spec_failures("", "")) == 2
    assert _spec_failures("### 2.8 x\neach approved branch's task body", "") != []
    assert _spec_failures("", "read the branch's `## Test decision`") != []
    # the § number is resolved, not trusted
    assert _spec_failures(
        "### 9.9 Something Else\neach approved branch's task body",
        "read the branch's `## Test decision`",
    ) != []


def test_slice_fails_closed_on_a_missing_end_marker():
    """The first version returned the rest of the file here, widening the Step 2d window
    12x and letting content from anywhere later satisfy a 2d assertion."""
    text = _text()
    assert _slice(text, "2d")
    broken = text.replace("## Step 3: Run Verification", "## Step 3: Verification Run")
    assert _slice(broken, "2d") == ""


def test_every_pin_and_forbidden_phrase_names_a_resolvable_section():
    for key, _span, _why in PINS:
        assert key in SECTIONS, f"pin references unknown section {key!r}"
    for key, _phrase, _why in FORBIDDEN:
        assert key in SECTIONS, f"forbidden phrase references unknown section {key!r}"


def test_pins_cover_both_halves_and_every_section():
    """A table weighted to one half would report a kill rate describing half the change."""
    covered = {key for key, _s, _w in PINS}
    assert covered == set(SECTIONS), f"sections with no pin: {set(SECTIONS) - covered}"
    assert sum(1 for k, _s, _w in PINS if k in ("2d", "2a")) >= 8
    assert sum(1 for k, _s, _w in PINS if k in ("step6", "step8")) >= 8
