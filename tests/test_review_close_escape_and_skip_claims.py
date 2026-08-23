"""Two claims `/review-close` made that were not true of the tree — Phase 175.

Wave 2 items 8 and 9 (`tools/FIX_WAVE_BRIEF.md`). Both are recovery/skip claims, and both
failed the same way: the *shape* of the claim was checkable against a shipped artefact, and
nothing checked it.

**Class A — the `PermissionDenied` hook over-promise.** Two sites told the reader the Phase
36 hook would surface an `!`-escape for a command the hook has no matcher for: a denied
`mkdir`/`cp` at Step 3b's pending-docs collect, and a denied `gh pr` at Step 4d — the latter
on the `pr`-policy mainline, which is every protected-`main` consumer. The hook iterates
exactly three matchers and returns 0 with no output otherwise, so the promised rescue never
arrives and the step stalls with no guidance. A third site described the coverage *by step
number* ("the well-known git patterns in Steps 4c/4d/6"), which is how the `gh pr` claim
looked plausible: Step 4d under `pr` runs `gh pr`.

The guard here does not describe the hook — it **executes** it. `hook_matches()` calls the
shipped matchers, so the population of covered commands is derived from the source of truth
rather than from a list in this file that would drift the moment a matcher changed.

**Class B — the doc-only skip's false rationale.** `/review-close` skips gates when a diff
touches no *code-extension* file. The licence written for that skip was "a doc-only diff
can't regress code-level lint/typecheck", and it is false twice over: the same extension
test classifies `pyproject.toml`, `tsconfig.json`, `.eslintrc.json`, lockfiles, CI workflows
and semgrep rules as documentation — so such a diff can regress lint and build *directly* —
and `### Always` is a full test suite, which can assert on prose. The clause was inherited
at five sites. The one that mattered is `4a-post`, "the gate whose green means something":
its own ran-nothing guard is conditioned on *"while the list still contains a code file"*,
vacuously false on a doc-only diff, so the doc-only skip was the single route through the
merged-tree gate that executes zero commands and reports green unchallenged.

Guard shapes here follow the house rules paid for by Phases 167–174: assert the **property**
rather than the site, pin corrected sentences rather than assert a token appears, derive
populations instead of counting them, and carry negative controls so a guard that punishes
ordinary rewriting shows up as the defect it is.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest import mock

import pytest

import permission_denied_hook as pdh

REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEW_CLOSE = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"
SKILLS_DIR = REPO_ROOT / "core" / "skills"
WORKFLOW = REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md"
GETTING_STARTED = REPO_ROOT / "docs" / "getting-started.md"


def _text() -> str:
    return REVIEW_CLOSE.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Whitespace-normalised, so reflowing a paragraph never reds a pin."""
    return re.sub(r"\s+", " ", text)


# ===========================================================================
# Class A — the hook's coverage, derived by executing the shipped matchers
# ===========================================================================

# A backticked span, optionally carrying the `!`-escape prefix the prose quotes it with.
def hook_matches(command: str) -> bool:
    """True iff the SHIPPED hook would emit guidance for ``command``.

    The oracle is the hook itself — `_match_protected_commit` needs a branch, so the
    protected-branch answer is supplied rather than shelling out to git. Deriving the
    covered set this way means a matcher added or removed upstream re-scopes every
    assertion in this module without an edit here.
    """
    stripped = pdh._strip_cd_prefix(command.lstrip("! ").strip())
    cwd = str(REPO_ROOT)
    if pdh._match_protected_push(stripped, cwd) is not None:
        return True
    if pdh._match_destructive_push(stripped, cwd) is not None:
        return True
    with mock.patch.object(pdh, "_current_branch", return_value="main"):
        return pdh._match_protected_commit(stripped, cwd) is not None



def test_the_hook_oracle_agrees_with_the_shipped_matcher_set():
    """Vacuity control for every assertion below: if `hook_matches` said no to everything,
    the whole class-A guard would pass by describing an empty world."""
    assert hook_matches("git push origin main")
    assert hook_matches("! git push origin main")
    assert hook_matches("git push origin --delete feat/x")
    assert hook_matches("git commit -m 'x'")
    assert not hook_matches("gh pr merge 123 --squash")
    assert not hook_matches("mkdir -p sysop/runtime/pending-docs && cp a b")
    assert not hook_matches("cp a b")
    assert not hook_matches("pytest tests/")


def test_the_shipped_matcher_loop_is_the_three_this_module_assumes():
    """Derived from the source, not asserted here: if a fourth matcher is wired in, the
    prose limiters that say "exactly three" become false and this fails loudly."""
    source = (REPO_ROOT / "core" / "companion" / "scripts" / "permission_denied_hook.py").read_text()
    loop = re.search(r"for matcher in \(([^)]*)\)", source)
    assert loop, "the hook's matcher loop moved — re-derive this module's oracle"
    matchers = {m.strip() for m in loop.group(1).split(",") if m.strip()}
    assert matchers == {
        "_match_protected_push",
        "_match_destructive_push",
        "_match_protected_commit",
    }, f"matcher set changed to {matchers}; every 'exactly three' claim in the corpus is now stale"


def test_the_two_corrected_sites_say_what_happens_instead():
    """Removing a false promise is only half the fix — a denial with no guidance and no
    instruction is the same stall wearing a shorter sentence."""
    flat = _flat(_text())
    assert "nothing rescues it automatically — ask the user for the escape yourself" in flat, (
        "Step 3b's collect no longer states its own recovery"
    )
    assert "no hook will surface the escape for you — construct and relay it yourself" in flat, (
        "the `gh pr` site no longer states its own recovery"
    )
    assert "This is the `pr`-policy mainline, not an edge case" in flat, (
        "the `gh pr` site no longer says the gap is on the dominant path"
    )


def test_the_hedge_names_patterns_not_step_numbers():
    """The laundering route: describing coverage as "the git patterns in Steps 4c/4d/6" is
    true under `direct` and reads as a promise about `gh pr` under `pr`, because Step 4d
    runs `gh pr` there."""
    flat = _flat(_text())
    assert "well-known git patterns in Steps" not in flat, (
        "coverage is described by step number again — the shape that made `gh pr` plausible"
    )
    assert "surfaces guidance for exactly three shapes" in flat


def test_the_spec_records_the_gh_gap_where_the_hook_is_described():
    """WORKFLOW.md § 8.2a is the authoritative description; the skill drifted from it once
    and the spec said nothing about `gh` either way."""
    flat = _flat(WORKFLOW.read_text(encoding="utf-8"))
    assert "Nor is `gh`, and that gap sits on the dominant path" in flat
    assert "never as the steps that use them" in flat


# ===========================================================================
# Class B — the doc-only skip, and the gate that must not inherit it
# ===========================================================================

FALSE_RATIONALES = {
    "Step 3's lint/typecheck licence": "a doc-only diff can't regress code-level lint/typecheck",
    "Step 2d's no-behaviour claim": "there is no behavior to pin",
    "Step 3c's incoherence claim": "A smoke gate over a doc-only change is incoherent — but only a doc-only",
    "4a-post's inheritance": "applying item 3's surface gate and item 4's doc-only skip",
    "the spec's bare 2b claim": "Skipped for a doc-only diff, which has no code-convention surface",
}


def _slice_4a_post(text: str) -> str:
    start = text.index("### 4a-post. Verify the Merged Tree")
    return text[start : text.index("### 4b. Close Merged Batches", start)]


@pytest.mark.parametrize("label", sorted(FALSE_RATIONALES))
def test_the_false_rationale_stays_retired(label):
    corpus = _flat(_text()) + "\n" + _flat(WORKFLOW.read_text(encoding="utf-8"))
    assert FALSE_RATIONALES[label] not in corpus, f"{label} is back"


# The five strings above are reversion guards: they catch the sentences that shipped, and
# nothing else. Two author-side mutations walked straight past them — a *new* doc-only skip
# added elsewhere in the file carrying its own bare harmlessness claim, and a contradiction
# of the non-inheritance planted outside the `4a-post` slice. Both are the "where it looks"
# class, and the closure is the one Phase 174 paid for: screen the claim *shape*,
# file-wide, rather than the sentence, section-scoped.



# The *screens* for both classes now live in `test_review_close_screens.py`.
# Their first version — a closed verb list, a closed limiter list, and an
# any-covered-span excusal — let 20 of 31 mutations through and reddened 4 of 9
# legitimate rewrites, so it was replaced rather than patched. What stays here is
# what that failure did NOT touch: verbatim pins, and facts derived by executing
# the shipped hook.

def test_the_merged_tree_gate_does_not_inherit_the_doc_only_skip():
    """The site that mattered. `4a-post` is the gate the skill calls the one "whose green
    means something", and its own ran-nothing rule is conditioned on the list containing a
    code file — vacuously false on a doc-only diff. Inheriting item 4 there is the single
    path through the merged-tree gate that runs zero commands and reports green."""
    post = _flat(_slice_4a_post(_text()))
    assert "Item 4's doc-only skip does not apply here." in post
    assert "still runs a consumer-declared list" in post
    assert "doc-only skip to *this* list" not in post, "item 4 is propagated into 4a-post again"


def test_the_merged_tree_gate_can_report_having_run_nothing():
    """A skip the report cannot express is a skip reported as a run. The template offered
    only `ran on <merge target>` or `not reached`, so a doc-only skip at this gate was
    rendered to the human as a completed verification."""
    flat = _flat(_text())
    # Pinned as the SET of arms, not as one string ending in `>`. Phase 219 added a
    # fourth arm (`TIMEOUT:`) and the old form broke on the moved terminator — an
    # over-strict pin that punished extending the very enumeration it protects.
    for arm in ("ran on <merge target>: N commands", "ran nothing: why",
                "not reached: why", "TIMEOUT: <command>"):
        assert arm in flat, (
            f"Step 8's 4a-post arm can no longer express {arm!r} — a state the report "
            "cannot express is a state reported as something else"
        )
    post = _flat(_slice_4a_post(_text()))
    assert "reports rather than stops" in post, (
        "the zero-commands-on-a-doc-only-diff case has no stated disposition — the risk is "
        "an always-halt regression in the other direction"
    )
    assert "Under `NO_ORIGIN_MAIN` neither of those two predicates is evaluable" in post, (
        "both dispositions key on the changed-file list's contents, and under NO_ORIGIN_MAIN "
        "there is no list — so a zero-command gate there has no stated outcome at all"
    )


def test_step_3s_skip_states_the_licence_it_actually_has():
    """The licence is that Step 3's green is not a verdict — not that documentation is
    harmless. The difference is the whole class: it is what stops the clause propagating."""
    flat = _flat(_text())
    assert "The licence for this skip is the pass, not the diff" in flat
    assert "`4a-post` therefore does not inherit this skip" in flat


def test_the_config_is_documentation_claim_stays_quantified():
    """`vite.config.ts` and `.eslintrc.js` are `.ts`/`.js` — code by this very test. The
    round caught the first version asserting the extension list calls *every* file a build
    consumes documentation, which is the overreach direction of a true finding."""
    flat = _flat(_text())
    assert "classifies as documentation a great many files" in flat, (
        "the absolute quantifier is back — the claim is true of many such files, not all"
    )
    assert "not *every* such file" in flat


def test_the_merged_tree_gate_is_told_to_count_what_it_ran():
    """Step 8's template offers `ran on <target>: N commands`, and the round found nothing
    instructing anyone to produce N — a report field with no producer."""
    assert "**Count what you actually executed and report the number**" in _flat(_text())


def test_step_3s_skip_never_cancels_an_armed_surface():
    """Item 3 arms a command per surface present in the changed-file list; three of its four
    bullets can fire on a diff item 4 calls doc-only — `Cargo.toml` is named by item 3 *by
    name* while `.toml` is absent from the code-file set. Item 4 cancelling those is a
    contradiction inside one numbered list."""
    flat = _flat(_text())
    assert "It also never cancels a command item 3 armed." in flat
    assert "which item 3 names *by name* while `.toml` is absent from the code set above" in flat


def test_the_two_narrowed_skips_carry_a_second_conjunct():
    """Step 2b's skip was already conjunctive and is why it was sound. Step 2d's and Step
    3c's were not: the extension test alone decided them."""
    flat = _flat(_text())
    assert "**and** *that task's* recorded decision is a `no-test`" in flat, (
        "Step 2d skips on extensions alone again"
    )
    assert "A record that names a test is verified whatever the extensions say" in flat
    assert "The two conjuncts have different granularity, and the skip takes the narrower one." in flat, (
        "Step 2d's per-branch diff test and per-task record are conflated again — a branch "
        "claiming two tasks would silence the one whose record names a test"
    )
    assert "no signal → proceed to Step 3b; any signal → run the gate" in flat, (
        "Step 3c's skip can overrule an explicit `manual_smoke: true` again"
    )


def test_the_narrowed_skips_state_when_they_run_relative_to_their_own_inputs():
    """A conjunct about a fact the gate has not gathered yet is not a conjunct.

    Both narrowings introduce a dependency on a *later* numbered step — Step 2d's on the
    record classification, Step 3c's on signal detection — and prose asserting a condition
    is not a statement about when it is evaluated. Step 2d's step 0 shipped for one commit
    referencing "the branch's recorded decision" while step 1 is what reads it; caught
    author-side by mutating the ordering rather than the wording.
    """
    flat = _flat(_text())
    assert "Resolve step 1's read before deciding this" in flat, (
        "Step 2d's skip no longer says its conjunct needs step 1's classification first"
    )
    assert "does not earn the skip" in flat, (
        "`unreadable`/`missing` can be read as satisfying Step 2d's `no-test` conjunct"
    )
    assert "Run step 1's detection first, on every cycle, and let it decide." in flat, (
        "Step 3c's skip no longer orders detection ahead of the extension test"
    )
    assert "residual rather than operative" in flat, (
        "Step 3c again instructs computing per-branch diffs for a rule that, with detection "
        "first, cannot change any outcome"
    )
    assert "Nothing spares one" in flat, (
        "Step 2d's branch-tip note claims the doc-only skip spares a `missing` record — it "
        "does not, since `missing` is not the `no-test` the skip's second conjunct requires"
    )


def test_always_states_where_unconditional_binds():
    """`### Always` is defined as running "unconditionally" thirteen lines above the item
    that made it conditional. Downstream surfaces repeat the unconditional promise to
    consumers, so the definition has to say which gate keeps it."""
    flat = _flat(_text())
    assert '"Unconditionally" is a promise about `4a-post`' in flat


def test_the_consumer_guide_scopes_the_unconditional_promise_too():
    """`WORKFLOW_GUIDE.md` is the human-readable variant, and the first version of this
    module's corpus omitted it — so the phase's record claimed to have made its "runs
    unconditionally on every review pass" sentence true while leaving it untouched. The
    Guide defines "pass" as *each* of the two runs, which is exactly what makes the bare
    sentence false: the pre-merge pass drops the list on the dominant cycle.
    """
    guide = _flat((REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW_GUIDE.md").read_text(encoding="utf-8"))
    assert '**"Always" binds on the authoritative pass**' in guide, (
        "the Guide promises `### Always` runs unconditionally on every pass again"
    )
    assert "run unconditionally on every review pass" not in guide, (
        "the unscoped promise is back in the consumer-facing guide"
    )


def test_the_public_promise_and_the_mechanism_that_keeps_it_move_together():
    """`docs/getting-started.md` tells a consumer a suite under `### Always` runs "on the
    merged tree on every merge". That is a claim about `4a-post`. If the non-inheritance is
    ever removed, this public sentence becomes false — so the two are pinned as one."""
    promise = "runs it on the merged tree on every merge"
    assert promise in _flat(GETTING_STARTED.read_text(encoding="utf-8")), (
        "the public promise moved; re-resolve it against docs/getting-started.md"
    )
    assert "Item 4's doc-only skip does not apply here." in _flat(_slice_4a_post(_text())), (
        f"the public docs promise {promise!r} while the merged-tree gate can skip itself"
    )


def test_config_only_is_named_as_an_extension_claim_not_a_consequence_claim():
    """The same false premise, one layer down: the `no-test` adjudication lists "config-only"
    as a rationale that holds, and config is behaviour a project checks."""
    flat = _flat(_text())
    assert 'name a file\'s extension, not its consequence' in flat
