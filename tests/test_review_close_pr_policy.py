"""Phase 151 — `/review-close` Step 4's `pr` path: PR-state authority (#208) and PR reuse (#204).

Both fixes are prose in `core/skills/review-close/SKILL.md`, so the coverage here is drift
guards — but written to fail on the *semantics*, not on a paraphrase. Each guard names the
property that would break if the prose regressed, and the module ends with a set of
"the old wording must not come back" assertions, because both defects were wordings that
read as correct.

**#208 — a `fatal:` after a SUCCESSFUL merge.** `gh pr merge --delete-branch` deletes the
*local* branch too, so after the remote squash lands `gh` switches to the base branch and
tries to fast-forward it. In the **integration-branch shape** that cannot succeed: Step 4-pre
cherry-picked every local-only `main` commit onto the integration branch, so those commits
exist twice at different SHAs and `origin/<default branch>` is not a descendant of local `main`. Step 4d-1
used to key the stuck-PR branch on "`gh pr merge` refuses", which reads that expected `fatal:`
as a failed merge and skips all cleanup after a merge that already landed.

Both adversarial reviewers independently caught that the first draft of this fix asserted
"diverged by construction" as a *universal* — false for the PR-reuse shape the same phase
added, whose condition 3 requires `origin/<default branch>..<default branch>` to be empty and where gh's fast-forward
therefore succeeds. The guards below assert the claims are stated **per shape**; a universal
in either direction is the regression.

**#204 — no branch for "the approved branch already has an open PR."** Followed literally,
Step 4-pre cut a second integration branch, opened a second PR on identical content, re-ran
the whole required-check suite, and orphaned the first PR.

#204's incidental note ("`gh` already fast-forwards local `main`, so Step 6's reset is a
no-op") is neither adopted nor flatly rejected. It is true of the shape its reporter was in
(they had `origin/<default branch> == main` — the reuse shape) and false of #208's shape. Step 6 keeps the
reset unconditionally (it is a no-op where the note holds and load-bearing where it does not)
and states the reason per shape rather than picking a winner.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests import shape_lib as S

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _section(start: str, end: str) -> str:
    text = _text()
    a = text.index(start)
    b = text.index(end, a)
    return text[a:b]


def _live_command_lines(text: str) -> list[str]:
    """Executable bash lines — delegated to the shared structural extractor.

    This used to be a local copy that treated any backticked line as prose. That was a
    per-line opt-out (a trailing comment disabled the guard) and is replaced by
    `shape_lib.live_command_lines`, which keys on ``` fences instead. Kept as a thin alias
    so the tests below read the same.
    """
    return S.live_command_lines(text)


# --------------------------------------------------------------------------------------
# #208 — PR state is the verdict, not the command's exit status or stderr
# --------------------------------------------------------------------------------------

def test_step4d_gates_on_pr_state_after_the_merge():
    """A `gh pr view --json state` probe must run AFTER `gh pr merge`, as its own command."""
    block = _section("#### `pr` policy", "##### 4d-1.")
    merge_at = block.index('gh pr merge "<PR>" --squash --delete-branch')
    state_at = block.index('gh pr view "<PR>" --json state,mergedAt')   # search from 0,
    # NOT from merge_at — str.index(sub, start) can never return < start, which would make
    # the ordering assertion below unfailable.
    assert state_at > merge_at, "the state probe must follow the merge, not precede it"


def test_step4d_documents_the_expected_fatal_from_delete_branch():
    block = _section("#### `pr` policy", "##### 4d-1.")
    assert "fatal: Not possible to fast-forward, aborting." in block
    for phrase in ("does NOT mean the merge failed", "benign"):
        assert phrase in block, f"Step 4d no longer explains the benign fatal: missing {phrase!r}"


def test_the_divergence_claim_is_scoped_by_shape_never_stated_as_universal():
    """The falsehood both reviewers caught. `pr` policy does NOT always diverge.

    Reuse condition 3 requires `git rev-list origin/<default branch>..<default branch>` to be empty, so under the
    PR-reuse shape local `main` is an ancestor of `origin/<default branch>` and gh's post-merge
    fast-forward succeeds — no `fatal:` at all. Any wording that attaches "diverged by
    construction" / "always fails" to `pr` policy as a whole is wrong.
    """
    text = _text()
    assert "In the integration-branch shape that fast-forward cannot succeed" in text
    assert "In the PR-reuse shape it does *not* fire" in text
    for universal in (
        "Under `pr` policy local `main` has **diverged by construction**",
        "under `pr` policy, **fails** at it",
        "its fast-forward of local `main` *always* fails",
    ):
        assert universal not in text, f"the unscoped divergence claim is back: {universal!r}"


def test_step4d1_trigger_keys_on_state_not_on_the_command_refusing():
    """The regression that mattered: the stuck-PR branch must not key on `gh pr merge`."""
    block = _section("##### 4d-1.", "## Step 5:")
    assert "The trigger is PR state, never the merge command's exit status or stderr." in block
    assert "or `gh pr merge` refuses" not in block, (
        "4d-1 still triggers on the merge command refusing — that reads the expected "
        "post-merge `fatal:` as a failed merge and skips Step 6 after a successful close"
    )
    assert "Do **not** key this branch on `gh pr merge`" in block


def test_confirmed_merge_no_longer_accepts_a_zero_exit_as_equivalent_to_merged():
    block = _section("##### 4d-1.", "## Step 5:")
    assert "`gh pr merge` exits 0 / `gh pr view` shows `state: MERGED`" not in block, (
        "the disjunction is back — exit status is not co-equal evidence with PR state"
    )
    assert "whatever the merge command's exit status or stderr said" in block


def test_step6_reset_is_stated_per_shape_and_still_always_run():
    """The reset runs in both shapes; only its *reason* differs. See the module docstring."""
    block = _section("## Step 6: Clean Up", "**`direct` policy — per-branch cleanup.**")
    assert "git reset --hard origin/<default branch>" in block
    assert "Run the `git reset --hard origin/<default branch>` in both shapes" in block
    assert "here the reset is load-bearing" in block          # integration-branch shape
    # PR-reuse shape. Phase 219's round measured the old "harmless no-op" claim FALSE for
    # the widened condition 3: a merge-updated branch takes the reuse shape while local
    # `main` still holds unpushed commits, so gh's fast-forward fails the same way and the
    # reset MOVES main. The reset is load-bearing in both shapes now, and the guard pins
    # the correction rather than the claim it replaced.
    assert "the reset **moves**" in block
    assert "here the reset is a harmless no-op" not in block, (
        "the measured-false no-op claim is back — it is what an operator hitting the "
        "DIRTY gate in reuse shape would rely on to conclude nothing is at stake"
    )
    assert "right about that cycle and wrong as a general rule" in block


# --------------------------------------------------------------------------------------
# #204 — the PR-reuse shape
# --------------------------------------------------------------------------------------

def test_step4pre_probes_for_an_existing_pr_before_cutting_a_branch():
    block = _section("### 4-pre.", "### 4a.")
    probe_at = block.index(
        'gh pr list --head "<approved branch name>" --base <default branch> --state open'
    )
    cut_at = block.index('git checkout -b "$INTEGRATION_BRANCH" origin/<default branch>')
    assert probe_at < cut_at, (
        "the reuse probe must run BEFORE the integration branch is cut — probing after it "
        "has already been created is the second-PR bug"
    )


def test_reuse_requires_all_five_conditions():
    """Each condition guards a distinct way reuse would be wrong; none is decorative."""
    block = _section("### 4-pre.", "### 4a.")
    for fragment in (
        "**exactly one** branch is still approved **after Step 3b**",  # 1: 2d/3b can demote
        "non-draft, same-repository** PR whose base is `main`",        # 2: fork/draft PRs
        # 3: nothing to sweep THAT THE BRANCH DOES NOT ALREADY HAVE. Phase 219 widened
        # this: the unqualified form rejected the case its own rationale was void for —
        # a commit already an ancestor of the branch needs no sweep, because merging the
        # branch lands it. Measured on a merge-updated branch: unqualified 1, `--not` 0.
        "no local-only `main` commits that the branch does not already contain",
        "**not behind** its remote counterpart",                       # 4: stale head
        "not behind `origin/<default branch>`",                                    # 5: stale base
    ):
        assert fragment in block, f"reuse condition missing: {fragment!r}"
    # The widening has to be stated honestly in BOTH directions, or a reader assumes it
    # covers every "already an ancestor" case. It does not: a branch updated by
    # `git rebase main` is then behind its own remote, so condition 4 rejects it whatever
    # condition 3 says (measured 1). Pin the disclosure, not just the widening.
    assert "inert for a rebase-updated one" in block, (
        "condition 3 no longer states the case its widening does NOT reach. A widening "
        "that reads as universal when it is not is worse than the narrow form it replaced"
    )
    # The probe still computes all four quantities; Phase 153 runs the commands BARE and
    # reads the values off stdout rather than capturing them into `$PR_NUMBER` /
    # `$LOCAL_ONLY` / `$BEHIND_REMOTE` / `$BEHIND_MAIN`, because an allow-rule does not
    # match past a variable assignment. So pin the probe commands, not the variable names —
    # asserting on the names would re-pin the shape this phase removed.
    #
    # Phase 169: the branch operand is now a substituted `<approved branch name>` literal,
    # not `$APPROVED_BRANCH`. These four strings were the *previous* spelling and pinning
    # them had ratcheted the bug in place — the variable was assigned in an earlier fenced
    # block, so all three branch operands expanded EMPTY on every run. `git fetch origin ""`
    # exits 0 silently and `git rev-list --count "..origin/<default branch>"` answers `HEAD..origin/<default branch>`,
    # so condition 4 printed nothing, `:694` read that as "conditions unmet", and the whole
    # reuse shape was unreachable. Pinning the literal form is what keeps it reachable.
    for probe in (
        'gh pr list --head "<approved branch name>" --base <default branch> --state open',       # 1 + 2
        'git rev-list --count origin/<default branch>..<default branch> --not "<approved branch name>"',     # 3
        'git rev-list --count "<approved branch name>..origin/<approved branch name>"',  # 4
        'git rev-list --count "<approved branch name>..origin/<default branch>"',                # 5
    ):
        assert probe in block, f"reuse probe no longer computes: {probe!r}"
    # …and the unqualified form must be GONE, not merely joined. It is a strict PREFIX of
    # the widened one, so the membership assert above passes against either — this is the
    # only check that can tell them apart. Line-anchored, because that prefix appears
    # inside the widened command by construction.
    bare = [
        ln for ln in block.splitlines()
        if ln.strip() == "git rev-list --count origin/<default branch>..<default branch>"
        or ln.strip() == "git rev-list origin/<default branch>..<default branch>"
    ]
    assert not bare, (
        "Step 4-pre still runs the UNQUALIFIED condition-3 count as a complete command: "
        f"{bare!r}. That is the form that rejected the safe case; leaving both ships two "
        "readings and lets the agent pick the wrong one."
    )
    # And the operands must never go back to being variables: the value is set in an
    # earlier block, so a `$APPROVED_BRANCH` here is empty by construction.
    assert "$APPROVED_BRANCH" not in block.replace("`$APPROVED_BRANCH`", ""), (
        "a Step 4-pre command reads $APPROVED_BRANCH again — it is assigned in an earlier "
        "fenced block, so it expands empty; write the branch name out as a literal"
    )


def test_reuse_probe_rejects_fork_and_ambiguous_prs():
    """`gh pr list --head` cannot be scoped to an owner, and GitHub allows several open PRs
    to share a head-branch NAME across forks — so an unfiltered `.[0]` can select a third
    party's PR and squash-merge their code to `main` while reporting this run as merged."""
    block = _section("### 4-pre.", "### 4a.")
    assert "isCrossRepository == false" in block
    assert "isDraft == false" in block
    assert "if length == 1 then .[0] else empty end" in block, (
        "the probe no longer demands exactly one candidate — `.[0]` on an ambiguous list "
        "is the fork-PR hazard"
    )
    assert "--match-head-commit" in _text()


def test_reuse_shape_is_honest_about_how_often_it_fires():
    """#204 calls this "the normal end state"; the precondition usually is not met."""
    block = _section("### 4-pre.", "### 4a.")
    assert "How often this actually fires" in block


def test_the_fall_through_is_not_described_as_free():
    """`Q-265`. The note used to say *"falling through is never wrong, just wasteful"*.

    Measured false, end to end on a real remote: a published branch at `0 0` against
    `origin/<branch>` comes out of the fall-through **1 behind, 2 ahead** with a rewritten
    tip, and Rule C forbids the force-push that would reconcile it. The sentence was a
    licence to stop thinking at exactly the point where the damage happens, so this guard
    asserts it is GONE — not that a correction has been appended beside it. A rule and its
    contradiction shipping together is worse than either alone, because the agent picks.
    """
    block = _section("### 4-pre.", "### 4a.")
    flat = " ".join(block.split())
    assert "Falling through is never wrong" not in flat, (
        "the measured-false 'falling through is never wrong, just wasteful' claim is back "
        "in Step 4-pre"
    )
    assert "Falling through is not free" in flat
    # Direction, not presence: the correction is worthless if its two measured endpoints
    # can be swapped or softened. Both must be stated, and the harm must be attributed to
    # the PUBLISHED branch rather than to branches in general.
    assert "1 behind, 2 ahead" in flat, (
        "the fall-through note no longer carries the measurement it rests on"
    )
    assert "published" in flat.lower()
    assert "closes it as *unmerged*" in flat, (
        "the note must say what becomes of the branch's own PR. It has already been wrong "
        "here once: the first version said the PR stays open and a human closes it, and "
        "Step 6 deletes its head branch three steps later, which closes it as unmerged"
    )
    assert "--no-ff" in flat, (
        "the note points at Step 4a's remedy; if that is no longer a `--no-ff` merge the "
        "sentence is describing a mechanism that does not ship"
    )


def test_rule_a_guard_covers_the_reuse_shape_without_becoming_tautological():
    """The reused branch has no `merge/review-close-*` pattern to match, so the assert has
    to use the literal Step 2a branch name — and must still never re-read it from HEAD."""
    block = _section("> **HARD RULE — branch guard.**", "> **Value persistence")
    assert "PR-reuse shape" in block
    assert "literal branch name Step 2a approved" in block
    assert "Never re-derive it with `git rev-parse --abbrev-ref HEAD`" in block
    assert "must come from somewhere **other than `HEAD`**" in block


def test_step4a_is_skipped_under_reuse():
    block = _section("### 4a. Merge Approved Feature Branches", "### 4b.")
    assert "Skip this step entirely under the Step 4-pre PR-reuse shape" in block


def test_step4b_force_rationale_covers_both_shapes():
    block = _section("### 4b. Close Merged Batches", "### 4c.")
    # Phase 233 (`Q-020`) retired the mandate: the gate targeted the literal
    # `main` while the merge lands in HEAD, so it rejected every correctly-merged
    # `pr` branch, and the remedy — mandate `--force` — also silenced the
    # cherry-pick detection. What this test pins is unchanged in PURPOSE: the
    # rationale must cover BOTH Step 4-pre shapes and must name the actual gate.
    # COVERAGE of both shapes, not the word "both". The rationale used to say
    # "in *both* Step 4-pre shapes" when it mandated `--force` for both; after the
    # round they differ (strict containment passes the integration shape and
    # refuses reuse), so pinning that phrase would force the prose back to a claim
    # execution refutes. The two named-shape assertions below test the real
    # requirement — a reader on either shape must find their case.
    assert "Step 4-pre" in block, "the rationale no longer references the two shapes at all"
    assert "git merge-base --is-ancestor" in block, (
        "the rationale should name the actual gate it describes"
    )
    assert "PR-reuse shape:*" in block and "Integration-branch shape:*" in block, (
        "both shapes must be named explicitly, not merged into one claim"
    )
    assert "no longer need `--force` for the ancestry reason" in block, (
        "Step 4b must not go back to mandating --force for BOTH shapes: a blanket "
        "mandate is the disarm `Q-020` is filed about"
    )
    # ...and it must not overcorrect either. The round reproduced a false ACCEPT
    # from plain ancestry (HEAD sitting at the batch tip), so the gate requires
    # STRICT containment and the PR-reuse shape — where HEAD *is* the branch —
    # genuinely still needs the escape. Saying otherwise strands that operator.
    assert "reuse still needs" in block and "`--force`" in block, (
        "Step 4b claims the reuse shape needs no --force; strict containment "
        "refuses it, so that instruction would fail on the reuse path"
    )
    assert "cherry-pick" in block, (
        "--force's one legitimate use must survive the mandate's retirement"
    )


def test_step4d_reuse_path_never_opens_a_second_pr():
    """The whole point of #204: reuse must merge the PR the probe found, not create one."""
    block = _section("#### `pr` policy", "##### 4d-1.")
    reuse_block = block[block.index("*PR-reuse shape:*"):block.index("**Step 2 —")]
    assert "no `gh pr create`" in reuse_block
    assert "gh pr create --base" not in reuse_block, (
        "the reuse path still invokes gh pr create — that is the second-PR bug"
    )
    # The integration-branch shape, by contrast, must still create one.
    assert "gh pr create --base <default branch> --head" in block[:block.index("*PR-reuse shape:*")]


def test_step6_tolerates_the_absent_integration_branch_under_reuse():
    block = _section("## Step 6: Clean Up", "## Step 7:")
    assert "Integration-branch shape only — then drop the integration branch." in block
    assert "Do not run that line at all in the PR-reuse shape" in block, (
        "the skip must be an instruction, not a comment buried inside the bash block"
    )
    assert "PR-reuse shape both of the above are usually already done for you" in block


# --------------------------------------------------------------------------------------
# Permission surface
# --------------------------------------------------------------------------------------

def test_reuse_probe_verb_is_declared_and_already_seeded():
    """`gh pr list` is new to this skill's `pr` set — and unlike the five verbs upstream
    #205/#210 flagged, it genuinely ships in the installer's allow-list, so declaring it as
    required does not add a fresh-install hard stop."""
    import json
    assert "- `Bash(gh pr list:*)`" in _text()
    settings = json.loads(
        (REPO_ROOT / "core" / "companion" / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    assert "Bash(gh pr list:*)" in settings["permissions"]["allow"]


def test_step4c_doc_staging_requires_the_wildcard_not_literal_paths():
    """Step 4c's shared-doc staging is covered by `Bash(git add:*)`, never by a
    per-path rule.

    Phase 151 shipped these verbs as an explicit non-entry because the installer
    seeded only `git add tasks/index.yml` / `git add review_tasks.md`, and
    requiring a shared-doc path would stop every consumer at Step 0 on a fresh
    install — the failure shape upstream #205 reports. Phase 152 closed that by
    seeding the wildcard instead: the pre-flight now *requires* it, and the
    literal-path rules stay banned for the original reason (`changelog.md` and
    `UI_Iterations.md` are consumer-authored names Sysop does not own, so no
    enumeration can be complete).
    """
    text = _text()
    preflight = text.split("## Step 1:")[0]
    assert "- `Bash(git add:*)`" in preflight, (
        "Step 4c's shared-doc staging lost its required rule"
    )
    assert "Step 4c step 7's shared-doc staging" in preflight, (
        "the doc-staging verbs are not disclosed in the permission pre-flight"
    )
    for verb in ("- `Bash(git add PROJECT_STATUS.md)`", "- `Bash(git add changelog.md)`",
                 "- `Bash(git add UI_Iterations.md)`"):
        assert verb not in text, f"{verb} became a hard requirement — fresh installs will halt"


# --------------------------------------------------------------------------------------
# #203 — the Step 4c staging fix, prose half (the behavioural half lives in
# tests/test_review_close_close_heredoc.py)
# --------------------------------------------------------------------------------------

def test_step4c_names_a_staging_command_and_verifies_the_commit():
    block = _section("### 4c. Consolidate Pending Documentation", "### 4d. Land on `main`")
    assert "**Stage, then commit**" in block
    assert "git add PROJECT_STATUS.md" in block
    assert "One `git add` per file, never one command listing them all." in block
    assert "git log -1 --pretty=%s | grep -q '^docs: consolidate documentation'" in block


def test_step4c_index_membership_check_is_conditional():
    """#203's proposed assertion was unconditional and would false-fail whenever no
    pending-doc carried `roadmap_ids` — `tasks/index.yml` is then legitimately untouched."""
    block = _section("### 4c. Consolidate Pending Documentation", "### 4d. Land on `main`")
    assert "if this run closed at least one `roadmap_ids` entry" in block
    assert "Skip that second check when no pending-doc carried `roadmap_ids`" in block


def test_step4c_warns_that_dash_A_does_not_help():
    block = _section("### 4c. Consolidate Pending Documentation", "### 4d. Land on `main`")
    assert "`-A` does **not** change this" in block


# --------------------------------------------------------------------------------------
# Findings from this phase's own adversarial pass
# --------------------------------------------------------------------------------------

def test_step4d_rederives_the_pr_number_and_stops_on_an_empty_one():
    """The HIGH Phase 151's own fix introduced, and the shape Phase 153 replaced it with.

    Splitting Step 4d into two blocks made the PR handle cross a step boundary, and
    variables do not persist. An empty one does not fail loudly: `gh` falls back to
    resolving the current branch, so `gh pr merge ""` merges, `--delete-branch` moves HEAD
    to `main`, and the verdict probe then finds no PR for `main` — reporting a stuck PR and
    skipping Step 6 after a merge that landed. #208 reintroduced by its own fix.

    Phase 151 guarded that with `test -n "$PR_REF" ||`. Phase 153 removed the variable
    instead: the probe runs bare, the number is written out as a literal `<PR>` at each
    use, and the stop is prose. The ordering property is unchanged and still pinned — the
    re-derivation and its stop must both precede the first `gh` call that would otherwise
    resolve the current branch by guessing.
    """
    block = _section("**Step 2 — wait for checks", "##### 4d-1.")
    lines = block.splitlines()

    def _line_index(prefix: str, *, live: bool) -> int:
        """LINE-ANCHORED, restoring the parent's hardening.

        The parent used this helper with the comment *"a guard that has been commented out
        is not a guard. (An earlier draft searched the whole block, and survived a mutation
        that merely prefixed it with `#`.)"* The Phase-153 rewrite reverted to
        `block.index(...)`, and the adversarial pass immediately reproduced the exact
        mutation: commenting out the re-derivation probe passed clean. `live=True` requires
        the line to be an actual command, not a comment quoting one.
        """
        for i, line in enumerate(lines):
            s = line.lstrip()
            if not s.startswith(prefix):
                continue
            if live and line.lstrip().startswith("#"):
                continue
            return i
        raise AssertionError(f"no {'live ' if live else ''}line starting with {prefix!r}")

    rederive_at = _line_index('gh pr list --head "$(git rev-parse --abbrev-ref HEAD)"', live=True)
    stop_at = _line_index("**If that prints nothing, STOP**", live=False)
    checks_at = _line_index('gh pr checks "<PR>"', live=True)
    assert rederive_at < stop_at < checks_at, (
        "the re-derivation and its empty-result stop must both precede the first gh call "
        f"that would otherwise silently resolve the current branch "
        f"(rederive={rederive_at} stop={stop_at} checks={checks_at})"
    )
    # The stop must say WHY, or a later edit quietly downgrades it to a warning — the
    # whole hazard is that an empty operand looks harmless.
    assert "does **not** reject an empty operand" in block


def test_the_pr_operand_is_quoted_at_every_gh_call_site():
    """Unquoted, `<PR>` is a redirection to bash — not a placeholder.

    `gh pr merge <PR> --squash --delete-branch` parses as `gh pr merge --delete-branch`
    reading stdin from a file named `PR`, so the operand vanishes and gh falls back to the
    current branch's PR: the precise silent-wrong-merge the stop above exists to prevent,
    reached by a route the stop cannot see. Quoted, an unsubstituted placeholder instead
    produces a loud `no pull requests found for branch "<PR>"`. The quotes are the
    enforcement mechanism, which is why they get their own guard.
    """
    unquoted = [
        ln for ln in _live_command_lines(_text())
        if re.search(r"gh pr \w+ <PR>", ln)
    ]
    assert unquoted == [], "unquoted <PR> operand — bash reads it as a redirection:\n" + "\n".join(unquoted)

    quoted = [ln for ln in _live_command_lines(_text()) if 'gh pr' in ln and '"<PR>"' in ln]
    assert len(quoted) >= 4, f"expected the four Step 4d gh calls to use \"<PR>\", found {quoted}"


def test_no_pr_handle_is_ever_held_in_a_variable():
    """Drift guard for the Phase 153 reshape, in both directions.

    `$PR_REF` / `$PR_NUMBER` crossing a step boundary is the #208-by-its-own-fix hazard,
    and capturing `gh` output into *any* variable additionally costs the invocation its
    allow-rule match (a rule does not match past an assignment), so `dontAsk` auto-denies
    it after Step 0 has just vouched for the rule. Both are re-accretion risks because the
    capture form is the more natural thing to write.
    """
    # Any variable used as a `gh` operand, not just the two names Phase 151 happened to
    # use — `$PR`, `$PRNUM` and a handle set from `git`/`jq` are the same hazard.
    offenders = [
        line for line in _live_command_lines(_text())
        if re.search(r"gh\s+pr\s+\w+\s+\"?\$\w+", line) or S.GH_CAPTURE_RE.search(line)
    ]
    assert offenders == [], (
        "a PR handle is being held in a variable, or gh output captured into one, again "
        "— run gh bare and write the number out as a quoted literal:\n" + "\n".join(offenders)
    )


def test_that_pr_handle_guard_is_not_vacuous():
    """Non-vacuity across variable names, plus proof that the prose which *quotes* the
    retired forms (which the skill does on purpose, to explain the reshape) is correctly
    not counted as a live command."""
    retired = (
        "```bash\n"
        'PR_REF="$(gh pr create --base <default branch> --head "$INTEGRATION_BRANCH" \\\n'
        'PR_NUMBER="$(gh pr list --head "$APPROVED_BRANCH" --base <default branch> --state open \\\n'
        'gh pr merge "$PR_REF" --squash --delete-branch\n'
        "gh pr merge $PR --squash\n"
        'gh pr view "$PRNUM" --json state\n'
        "```"
    )
    live = _live_command_lines(retired)
    caught = [
        ln for ln in live
        if re.search(r"gh\s+pr\s+\w+\s+\"?\$\w+", ln) or S.GH_CAPTURE_RE.search(ln)
    ]
    assert len(caught) == 5, f"guard missed a spelling: caught {caught}"

    prose = (
        "Step 4-pre and Step 4d capture `gh` output into variables "
        '(`PR_NUMBER="$(gh pr list …)"`, `PR_REF="$(gh pr create …)"`).\n'
        '> an unre-exported `$PR_REF` means `gh pr merge ""` merges the wrong PR\n'
    )
    assert _live_command_lines(prose) == []


def test_the_gh_empty_operand_hazard_survives_in_the_persistence_note():
    """The reshape removed the variable; it must not remove the *reason*.

    A future author who does not know `gh` resolves an empty operand by guessing is one
    edit away from reintroducing the capture. The note is where that knowledge lives.
    """
    block = _section("> **Value persistence", "### 4a.")
    assert "falls back to resolving the current branch's PR" in block
    assert "written out and quoted at every use site" in block, (
        "the note no longer says the cross-block values are *quoted* literals — the quoting "
        "is the enforcement (unquoted is a bash redirection; unsubstituted-but-quoted "
        "fails loud)"
    )
    # Phase 169: the note also has to keep saying WHERE the boundary is. Its predecessor
    # scoped itself to "Steps 4a-4d" and told the reader to re-export per step, which
    # prescribed nothing for the six Step 4-pre sites that were actually broken — and a
    # Phase-164 sweep then cited it as the warrant for excluding them.
    # NOT a bare `"fenced block" in block` token check: the round rewrote this note to say
    # a variable within a step is fine, kept that token, and stayed green. The note is
    # ~3.3 KB, which is the same "token appeared somewhere in a long paragraph" shape
    # Phase 167's round found 43 of 90 mutations walking through. Pin the sentence.
    assert " ".join(
        "Nothing survives from one fenced block to the next, *including two blocks under "
        "the same heading*".split()
    ) in " ".join(block.split()), (
        "the note no longer states the block-granular persistence rule; a step-granular "
        "reading is what licensed the six phantom Step 4-pre sites"
    )


def test_4d1_gives_the_reuse_shape_its_own_recovery():
    """The idempotency argument ("the next run cuts a NEW integration branch") is false
    under reuse — there is no new branch. Re-running is still safe, for different reasons,
    and it cannot clear a red check on its own."""
    block = _section("##### 4d-1.", "## Step 5:")
    assert "In the PR-reuse shape the recovery is different" in block
    assert "the sentence above does not apply" in block
    assert "idempotent" in block and "self-healing" in block


def test_step4c_staging_note_covers_the_rotation_path():
    """The changelog (`CHANGELOG.md`, Phase 222/Q-279) is written by the §6 rotation regardless of entry type, so keying its
    staging off the routing table alone drops the rotation's own edits."""
    block = _section("### 4c. Consolidate Pending Documentation", "### 4d. Land on `main`")
    assert "Do not stage `CHANGELOG.md` from the routing table alone" in block
    assert "regardless of entry type" in block


def test_step4c_does_not_overstate_what_the_failed_add_does():
    """The first draft inherited #203's "fails *worse* than doing nothing" wording. False:
    `git mv` already staged both halves, so the aborted add is a no-op on the index."""
    text = _text()
    assert "fails *worse* than doing nothing" not in text
    assert "It leaves the index exactly as it was" in text


def test_heredoc_guards_the_index_write_and_the_archive_directory():
    """Both are code, exercised in tests/test_review_close_close_heredoc.py; guarded here
    so the SKILL.md source they are extracted from keeps them."""
    block = _section("### 4c. Consolidate Pending Documentation", "### 4d. Land on `main`")
    assert "Path(dst).parent.mkdir(parents=True, exist_ok=True)" in block
    assert "if closed:" in block


def test_main_push_guard_covers_the_reuse_shape():
    """SKILL.md's HARD RULE delegates to `_shared/main-push-guard.md`; a reader who follows
    the delegation must not find a table that contradicts the reuse shape."""
    raw = (REPO_ROOT / "core" / "skills" / "_shared" / "main-push-guard.md").read_text(
        encoding="utf-8"
    )
    guard = " ".join(raw.split())   # the file hard-wraps; assert on semantics, not line breaks
    assert "PR-reuse shape" in guard
    assert "When there is no pattern to match" in guard
    assert "the expected value must originate somewhere **other than `HEAD`**" in guard
    assert "or any branch a squash PR will write it from" in guard   # Rule C heading
    # The reuse rows really are in the site table, not just narrated in prose.
    assert guard.count("PR-reuse shape) |") == 2
