"""Phase 169 — the persistence boundary is the fenced block, and it is now a gate.

WHAT THIS CLASS IS
------------------
A skill is markdown an agent executes. Nothing carries from one fenced block to the next,
so a `$VAR` a block does not itself assign is the empty string when the command runs. The
resulting failures are mostly *silent*, which is why 33 of them shipped:

  - `git -C "" rev-parse HEAD` does not fail — it runs in the CWD and prints a real SHA.
    So `/auto-build`'s Phase-6a integrity check, run as written, compared that against an
    empty `$PRE_PLAN_HEAD`, was always true, and parked **every task in the batch**.
  - `git fetch origin ""` exits 0 and prints a normal-looking `* branch HEAD -> FETCH_HEAD`.
    So `/review-close`'s PR-reuse probe never refreshed a ref, condition 4 printed nothing,
    the skill read that as "conditions unmet", and the entire reuse shape was unreachable
    on every run since it shipped.
  - An empty `"$SUBSET_IDS"` makes `/auto-build TECH-A TECH-B` select from the whole open
    frontier — the exact inversion of the "never silently dropped" invariant Step 1 states.

WHY THE GUARD IS SHAPED THIS WAY
--------------------------------
Three properties, each of which a previous phase shipped without and had its own round
find the guard vacuous:

1. **Zero-invariants, not baselines.** The population is empty after this phase, so the
   assertion is `== 0` rather than `<= N`. A ratchet with a number in it is a number
   somebody edits.
2. **Every non-vacuity twin calls the same production predicate the guard calls.** Neuter
   `phantom_shell_vars` and its twin fails too. A twin that re-implements the check inline
   cannot fail for any change to the real one.
3. **The escape hatch is pinned.** The cheapest way to silence this guard is not to edit
   the predicate — it is to add a name to `ENV_PROVIDED`. That set is pinned verbatim.

The record-side pins use whitespace-normalised comparison: reflowing a paragraph stays
green, changing what it says does not. Phase 167's round found eight of nine guards over
prose asserting only that a *token* appeared somewhere in a 700-character paragraph, which
43 of 90 mutations walked straight through.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests import shape_lib as S

WORKFLOW = S.REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _norm(text: str) -> str:
    """Whitespace-normalised, so a reflow is not a failure but a reword is."""
    return " ".join(text.split())


# --------------------------------------------------------------------------------------
# 1. The invariants
# --------------------------------------------------------------------------------------

def test_no_skill_reads_a_shell_variable_its_own_fenced_block_does_not_set():
    offenders = []
    for f in S.skill_files():
        for line_no, var, line in S.phantom_shell_vars(_read(f)):
            rel = f.relative_to(S.REPO_ROOT)
            offenders.append(f"{rel}:{line_no}: ${var} in `{line}`")
    assert not offenders, (
        "phantom shell variable(s) — the value is empty when the command runs, because "
        "nothing survives from one fenced block to the next. Substitute the value as a "
        "quoted literal (`\"<task id>\"`), or assign it inside this same block:\n  "
        + "\n  ".join(offenders)
    )


def test_no_skill_reads_a_shell_variable_from_an_inline_command_in_prose():
    """The half a fence-walking sweep structurally cannot see.

    `/review-close` Step 4a's merge commands are backticked list items reading a
    `$MERGE_TARGET` assigned one step earlier, and `/daily-summary` called two of its own
    shell functions the same way, from outside the block that defines them. The
    fenced-block sweeper reported 9 (file, var) pairs and none of them was one of these —
    not a miss it could have been tuned out of, a region it does not look at.
    """
    offenders = []
    for f in S.skill_files():
        for line_no, span in S.phantom_inline_commands(_read(f)):
            offenders.append(f"{f.relative_to(S.REPO_ROOT)}:{line_no}: `{span}`")
    assert not offenders, (
        "inline command(s) in prose reading a shell variable — inline code has no block "
        "to be assigned in, so the value is empty by construction. Write it out as a "
        "quoted literal:\n  " + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------------------
# 2. Non-vacuity — every twin calls the production predicate
# --------------------------------------------------------------------------------------

def test_phantom_detector_fires_on_the_shape_it_exists_to_catch():
    """The real `/auto-build` Phase-6a defect, verbatim, minus the fix."""
    sample = (
        "prose\n"
        "```bash\n"
        'NEW_HEAD=$(git -C "$WORKTREE_PATH" rev-parse HEAD)\n'
        'if [ "$NEW_HEAD" != "$PRE_PLAN_HEAD" ]; then\n'
        "  echo violation\n"
        "fi\n"
        "```\n"
    )
    found = {var for _, var, _ in S.phantom_shell_vars(sample)}
    assert "WORKTREE_PATH" in found
    assert "PRE_PLAN_HEAD" in found
    # `NEW_HEAD` is assigned in this very block, so it must NOT be reported — a detector
    # that flagged it would be unusable and would get switched off.
    assert "NEW_HEAD" not in found


def test_phantom_detector_scans_every_block_not_just_the_first():
    """A zero-invariant cannot notice a narrowed detector while the tree is legitimately
    clean, so the twins are the only positive control — and every twin here used a
    single-block sample, which left `fenced_blocks(text)[:1]` green. Round-found."""
    sample = (
        "```bash\nSAFE=1\necho \"$SAFE\"\n```\n"
        "prose\n"
        "```bash\ngit -C \"$WORKTREE_PATH\" rev-parse HEAD\n```\n"
    )
    assert {v for _, v, _ in S.phantom_shell_vars(sample)} == {"WORKTREE_PATH"}


def test_phantom_detector_exempts_no_name_by_suffix():
    """`if var.endswith('_BRANCH'): continue` was a one-line, suite-green narrowing — the
    exempt set is pinned, but a *predicate* exemption bypasses that pin entirely."""
    for name in ("APPROVED_BRANCH", "INTEGRATION_BRANCH", "BRANCH_NAME", "EXPECTED_BRANCH"):
        sample = f"```bash\ngit checkout \"${name}\"\n```\n"
        assert {v for _, v, _ in S.phantom_shell_vars(sample)} == {name}, name


def test_phantom_detector_does_not_fire_on_a_self_contained_block():
    sample = "```bash\nRUN_ID=\"$(date -u +%s)\"\necho \"$RUN_ID\"\n```\n"
    assert S.phantom_shell_vars(sample) == []


def test_phantom_detector_ignores_variables_named_only_in_comments():
    """Both directions of the comment bug the maintainer worklist records finding mid-run.

    A comment reading `# SUBSET_IDS = the …` must not count as an assignment (it hid a real
    site), and a `$VAR` inside a comment explaining the anti-pattern must not count as a
    reference (it manufactured three).
    """
    explains = "```bash\n# a `$TASK_ID` here would expand to the empty string\necho hi\n```\n"
    assert S.phantom_shell_vars(explains) == []

    fake_assign = "```bash\n# SUBSET_IDS = the space-separated list\necho \"$SUBSET_IDS\"\n```\n"
    assert {v for _, v, _ in S.phantom_shell_vars(fake_assign)} == {"SUBSET_IDS"}


def test_phantom_detector_skips_blockquoted_illustrations():
    """Several skills quote a retired shape inside a `>` block on purpose — so the *fence*
    has to be blockquoted, which is what marks the block an illustration.

    This twin originally used a plain fence with a `>`-prefixed line inside it, and so
    asserted the very bug the round found: inside an ordinary fence, a leading `>` is a
    shell redirection, not a quotation. See `test_a_redirect_on_its_own_line_is_scanned…`.
    """
    sample = "> ```bash\n> git checkout \"$RETIRED_VAR\"\n> ```\n"
    assert S.phantom_shell_vars(sample) == []


def test_inline_detector_fires_on_a_backticked_command_and_not_on_prose():
    prose = "The merge target `$MERGE_TARGET` is set in Step 4-pre.\n"
    assert S.phantom_inline_commands(prose) == []

    command = '1. `git checkout <branch> && git rebase "$MERGE_TARGET"`\n'
    assert [span for _, span in S.phantom_inline_commands(command)] == [
        'git checkout <branch> && git rebase "$MERGE_TARGET"'
    ]


def test_inline_detector_skips_fenced_regions():
    """Otherwise the two scans would double-report and the fenced one would be redundant."""
    sample = "```bash\nX=1\n```\n`git rebase \"$MERGE_TARGET\"`\n"
    assert [ln for ln, _ in S.phantom_inline_commands(sample)] == [4]


# --------------------------------------------------------------------------------------
# 3. The escape hatch
# --------------------------------------------------------------------------------------

def test_env_provided_set_is_pinned():
    """Adding a name here silences the guard for that name everywhere, in one line.

    `REPO_ROOT` is deliberately absent and must stay absent: the maintainer worklist
    skipped it, and nothing in the tree exports it (`git grep "export REPO_ROOT"` is
    empty). It is assigned locally in nine-odd shell scripts, which are ordinary scripts
    where variables persist normally. The skip was a standing hole, not a fact about the
    environment.
    """
    assert S.ENV_PROVIDED == frozenset({
        "ARGUMENTS",
        "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS",
        "CLAUDE_PROJECT_DIR",
        "GH_TOKEN", "GITHUB_TOKEN",
        "HOME", "LANG", "OLDPWD", "PATH", "PWD", "SHELL", "TMPDIR", "USER",
        "IFS", "RANDOM",
        "SSL_CERT_FILE",
        "SYSOP_SRC",
        "WORKTREE_PREFIX",
    }), (
        "ENV_PROVIDED changed. Adding a name exempts it from the phantom guard tree-wide, "
        "so justify it here: what outside the skill sets it? `REPO_ROOT` is the cautionary "
        "case — it looked environmental and is not."
    )


# --------------------------------------------------------------------------------------
# 4. The rule the fix rests on
# --------------------------------------------------------------------------------------

def test_workflow_states_the_boundary_at_block_granularity():
    """The root cause, pinned verbatim.

    Until Phase 169 § 8.2a said "skill *steps* are separate shell calls". That granularity
    is what `/review-close`'s own note inherited, and what a Phase-164 sweep then cited as
    its warrant for excluding six live sites: they were in *later blocks of the same step*,
    so a step-granular rule declared them fine. Pinned as a sentence rather than a token —
    a 19-character softening ("usually", "generally", "as a rule") would sail through a
    token check and put the licence back.
    """
    text = _norm(_read(WORKFLOW))
    assert _norm(
        "So the boundary an author may rely on is the **block**: **assume nothing "
        "survives from one fenced block to the next, even inside a single step.**"
    ) in text, "WORKFLOW.md § 8.2a no longer states the block-granular persistence rule"
    assert _norm(
        "That is deliberately a requirement on the author rather than a claim about the "
        "runner, so it holds however the harness batches"
    ) in text, (
        "the rule's framing is load-bearing: as a claim about the runner it would be an "
        "unverified mechanism assertion, which is the defect class this repo keeps shipping"
    )


# The retired claim, in any phrasing the corpus actually used. A single literal string is
# NOT enough and this phase proved it: the first draft matched only "steps are separate
# shell calls" and shipped green with three live restatements still in the tree —
# `/auto-build`'s "each step here is a separate `Bash` call", `/security-audit`'s identical
# sentence, and the maintainer worklist's "Each skill step is a separate Bash call", the
# last of them in a docstring this phase edited. Two independent reviewers found them.
_STEP_GRANULAR_RE = re.compile(
    r"\bstep\w*\b[^.\n]{0,40}?\b(?:is|are)\b[^.\n]{0,20}?separate\s+(?:`?Bash`?|shell)\s+calls?",
    re.IGNORECASE,
)


# The one shipped line that may contain the retired wording: the paragraph that retires it
# has to quote it to say what changed. Pinned as the WHOLE line — an allowlist keyed to a
# fragment would license any sentence sharing that fragment, which is how an exemption
# becomes a loophole. Same shape as `ALLOWED_TWO_DOT` in `test_review_close_diff_basis.py`.
_RETIREMENT_QUOTE = (
    '**§ Persistence boundary — the fenced block, not the step.** Until Phase 169 the '
    'sentence above ended "skill *steps* are separate shell calls", and that granularity '
    'was wrong in the direction that hides defects. A step is a `##` heading: prose, with '
    'no mechanical realization. Nothing binds the fenced blocks under one heading into a '
    'single shell call — the agent running the skill reads the prose between them and is '
    'free to split anywhere, or to interleave other tool calls. So the boundary an author '
    'may rely on is the **block**: **assume nothing survives from one fenced block to the '
    'next, even inside a single step.** That is deliberately a requirement on the author '
    'rather than a claim about the runner, so it holds however the harness batches; the '
    'strictly-safe form is to write the value out at *every* use site.'
)


def test_the_step_granular_wording_is_gone_from_shipped_content():
    """It licensed the defect, so its absence is the ratchet.

    Scoped to what ships, plus `tools/` (the worklist carried it too). The meta-repo's own
    records (`PHASE_LOG.md`, `REVIEW_ARCHIVE.md`, `CLAUDE.md`, `REVIEW_CHECKLIST.md`) quote
    superseded text by design and are not swept.
    """
    offenders = []
    roots = ((S.REPO_ROOT / "core", ("*.md",)),
             (S.REPO_ROOT / "docs", ("*.md",)),
             (S.REPO_ROOT / "tools", ("*.py",)))
    for root, patterns in roots:
        for pattern in patterns:
            for f in sorted(root.rglob(pattern)):
                for n, line in enumerate(_read(f).splitlines(), 1):
                    if _norm(line) == _norm(_RETIREMENT_QUOTE):
                        continue  # the paragraph that retires it must quote it
                    if _STEP_GRANULAR_RE.search(line):
                        offenders.append(f"{f.relative_to(S.REPO_ROOT)}:{n}: {line.strip()[:70]}")
    assert not offenders, (
        "the retired step-granular wording is back in shipped content — it is the claim "
        "that licensed six phantom sites in /review-close Step 4-pre. Say 'nothing survives "
        "from one fenced block to the next' instead:\n  " + "\n  ".join(offenders)
    )


def test_the_step_granular_guard_catches_every_phrasing_the_corpus_used():
    """A one-literal guard shipped green over three live restatements. These are the exact
    sentences that were in the tree; if the pattern stops matching any of them, the guard
    has narrowed back to what it was."""
    for phrasing in (
        "skill steps are separate shell calls, so the variable would not have survived",
        "each step here is a separate `Bash` call, so nothing you set earlier survives",
        "A WORKLIST, not a gate. Each skill step is a separate Bash call",
        "steps are separate shell calls",
    ):
        assert _STEP_GRANULAR_RE.search(phrasing), f"guard no longer catches: {phrasing!r}"
    # And it must not fire on the replacement wording, or every fixed site reads as a defect.
    for ok in (
        "nothing survives from one fenced block to the next",
        "assume nothing survives from one fenced block to the next, even inside a single step",
    ):
        assert not _STEP_GRANULAR_RE.search(ok), f"guard false-positives on: {ok!r}"


# --------------------------------------------------------------------------------------
# 5. The specific sites, so a regression names itself
# --------------------------------------------------------------------------------------

def _skill(name: str) -> str:
    return _read(S.SKILLS_DIR / name / "SKILL.md")


def test_auto_build_phase6a_check_compares_against_a_substituted_literal():
    """The worst consequence in the class: this comparison parked every task, every run."""
    text = _skill("auto-build")
    assert 'NEW_HEAD=$(git -C "<worktree path>" rev-parse HEAD)' in text
    assert 'if [ "$NEW_HEAD" != "<pre-plan head>" ]; then' in text
    assert '"$PRE_PLAN_HEAD"; then' not in text


def test_auto_build_captures_the_pre_plan_head_before_the_spawn_that_needs_it():
    """The check is only meaningful if the baseline is read first — and before Phase 169
    the skill *instructed* the capture without ever giving the command, in a paragraph
    printed after the block that consumed it."""
    text = _skill("auto-build")
    capture = text.index('git -C "<worktree path>" rev-parse HEAD\n```')
    spawn = text.index("spawn `min(N, len(batch))` plan-only agents")
    compare = text.index('if [ "$NEW_HEAD" != "<pre-plan head>" ]')
    assert capture < spawn < compare, (
        "the pre-plan HEAD capture must be prescribed before the Phase-6a spawn, which "
        "must precede the comparison"
    )


def test_auto_build_subset_ids_is_passed_as_a_substituted_literal():
    text = _skill("auto-build")
    assert "python3 - \"<subset ids>\" <<'PY'" in text
    assert 'python3 - "$SUBSET_IDS"' not in text


def test_claim_task_heredocs_take_a_substituted_task_id():
    text = _skill("claim-task")
    assert text.count("python3 - <<'PY' \"<TASK_ID>\"") == 2
    assert "python3 - <<'PY' \"$TASK_ID\"" not in text


def test_claim_task_states_the_rule_its_own_heredocs_broke():
    """The licence, pinned separately from the code.

    This sentence was already in the file, and two heredocs 35 and 156 lines below it did
    the opposite — so the rule existing is not the same as the rule binding. Inverting it
    ("you may carry it in a shell variable") was the one mutation the first draft of this
    module did not kill: the code guards above would catch the *next* `$TASK_ID`, but
    nothing caught the sentence that would invite it. Phase 165's lesson, one file over —
    a fix confined to the call sites leaves the row that licenses the belief.
    """
    text = _norm(_skill("claim-task"))
    assert _norm(
        "**Do not carry it in a shell variable:** nothing survives from one fenced block "
        "to the next, even inside a single step"
    ) in text, "/claim-task Step 2 no longer forbids carrying the task id in a variable"


def test_review_close_step4a_merge_operands_are_literals():
    text = _skill("review-close")
    # Phase 219 (`Q-265`) split items 1-2 into a published / local-only pair, because
    # rebasing a PUBLISHED branch in place rewrites history the remote already has. Both
    # arms of both commands have to stay literal — a `$` in either is the phantom-variable
    # class this module exists for, and the published arm added two new operand sites.
    for operand in (
        '`git checkout <branch> && git rebase "<merge target>"`',           # local-only rebase
        '`git checkout "<merge target>" && git merge --ff-only <branch>`',  # local-only ff
        # The published arm never rebases (the temp-ref variant was withdrawn by the
        # round: it left the branch's commits off the merge target, so Step 4c read a
        # merged branch as NOT-MERGED and Step 6's `git branch -d` refused).
        '`git checkout "<merge target>" && git merge --no-ff -m "merge <branch> (published — not rebased)" <branch>`',
    ):
        assert operand in text, f"Step 4a merge operand missing or no longer literal: {operand}"
    # Not a bare "`$MERGE_TARGET` appears nowhere" check: the surrounding prose names the
    # variable in order to explain why it is empty here, and a text search cannot tell that
    # from a live command. Ask the production predicate instead — which also means this
    # twin fails if `phantom_inline_commands` is neutered.
    assert [
        span for _, span in S.phantom_inline_commands(text) if "MERGE_TARGET" in span
    ] == []


def test_review_close_step4pre_probes_use_the_branch_name_as_a_literal():
    """Six sites in two blocks, all reading a name assigned in a third. They expanded
    empty on every run, and the failure was silent enough to survive a sweep that saw
    them and a note that was cited to excuse them."""
    text = _skill("review-close")
    for probe in (
        'git fetch origin "<approved branch name>"',
        'git rev-list --count "<approved branch name>..origin/<approved branch name>"',
        'git rev-list --count "<approved branch name>..origin/<default branch>"',
        'git checkout "<approved branch name>"',
        'gh pr list --head "<approved branch name>" --base <default branch> --state open',
    ):
        assert probe in text, f"Step 4-pre no longer runs: {probe!r}"
    assert "APPROVED_BRANCH=" not in text, (
        "the assignment is back — it cannot reach the two blocks that read it, and it "
        "costs the `gh pr list` in its own block a rule match besides"
    )


def test_main_push_guard_uses_the_repos_placeholder_idiom_and_says_so():
    """Fail-closed either way, so this is about the idiom, not a live break.

    It was excluded from a prior sweep as "a declared template" — but no sentence in the
    file declared it, and it was written in variable syntax, which is exactly what makes a
    placeholder indistinguishable from a runnable reference.
    """
    text = _read(S.SKILLS_DIR / "_shared" / "main-push-guard.md")
    assert 'test "$(git rev-parse --abbrev-ref HEAD)" = "<expected branch>" || {' in text
    assert "$EXPECTED_BRANCH" not in text
    assert _norm("**Substitute `<expected branch>` with the branch this step intends to "
                 "write** — see the table above — at both occurrences, before running it. "
                 "It is a placeholder, not a variable to set") in _norm(text), (
        "the substitution instruction is the whole point — without it this is a snippet "
        "that looks runnable"
    )


def test_the_mkdir_sites_keep_their_gate():
    """`mkdir -p` is the one converted command that does NOT fail on an unsubstituted
    placeholder — it creates a directory literally named `<worktree path>`, returns 0, and
    the Phase-6d park verdict lands there while the run reports PARKED. This phase
    introduced that (the old `$WORKTREE_PATH` form failed at filesystem root) and its own
    round caught it, so the `&&` gate is the fix and this is what holds it in place."""
    text = _skill("auto-build")
    gated = 'git -C "<worktree path>" rev-parse --show-toplevel >/dev/null && mkdir -p "<worktree path>/sysop/runtime/auto-build"'
    assert text.count(gated) == 2, (
        "both `mkdir -p` sites must stay gated on a read-only probe that fatals on an "
        "unsubstituted or missing path — an ungated `mkdir -p` silently succeeds"
    )
    for line in S.live_command_lines(text):
        # A fixed relative path (`mkdir -p sysop/runtime/parked`) has no placeholder to
        # leave unsubstituted and needs no gate; only a placeholder-bearing one does.
        if line.startswith("mkdir -p") and "<" in line:
            raise AssertionError(f"ungated placeholder mkdir in /auto-build: {line}")


def test_the_reuse_probe_surfaces_its_fetch_exit_and_says_why():
    """The stale-ref hazard on the path this phase made reachable.

    A failed fetch does NOT make condition 4 print nothing: `refs/remotes/origin/<branch>`
    survives it for any branch that has ever been fetched or pushed, so both counts resolve
    against stale refs and print `0` — the answer that takes the reuse shape. Measured with
    `gh` up and git transport down: a branch 1 behind its remote and 1 behind `origin/main`
    printed `0`/`0`. The echoed exit status is the only thing that distinguishes it.
    """
    text = _skill("review-close")
    assert 'git fetch origin "<approved branch name>"; echo "--- fetch exit (MUST be 0):  $?"' in text, (
        "the reuse probe no longer surfaces its fetch exit status — without it a broken "
        "fetch reads as two clean zeroes and squash-merges a branch this run rejected"
    )
    assert _norm(
        "**If the fetch exit is not `0`, take the integration-branch shape and do not read "
        "the two counts at all.**"
    ) in _norm(text), "the refuse-on-failed-fetch instruction is gone"
    step4pre = text[text.index("### 4-pre."):text.index("### 4a.")]
    assert "stale" in step4pre, (
        "the reason (stale remote-tracking refs still resolve) is gone; without it the "
        "instruction reads as boilerplate and the next author drops it"
    )


def test_inline_detector_derives_command_words_from_the_files_own_functions():
    """A hardcoded command-word list is an assumption about what a skill can invoke, and
    this one was wrong: `/daily-summary` defines `_days_ago`/`_date_minus`/`_day_name` in
    one block and called them from inline code outside it, where neither the functions nor
    the `$TARGET_DATE` existed. The round found it; a `git|gh|bash|python3|sh` list cannot.
    """
    sample = (
        "```bash\n"
        '_date_minus() { local d="$1"; echo "$d"; }\n'
        "```\n"
        'Then compute `_date_minus "$TARGET_DATE" 7`.\n'
    )
    assert S.shell_functions_defined_in(sample) == {"_date_minus"}
    assert [span for _, span in S.phantom_inline_commands(sample)] == [
        '_date_minus "$TARGET_DATE" 7'
    ], "the inline detector no longer derives command words from the file's own functions"
    # A function defined nowhere must NOT become a command word, or every backticked
    # identifier in prose becomes a finding.
    unknown = 'Then compute `_not_a_function "$TARGET_DATE" 7`.\n'
    assert S.phantom_inline_commands(unknown) == []


# --------------------------------------------------------------------------------------
# 6. Vacuity floors — added by Phase 169's round, which walked the guard three ways
# --------------------------------------------------------------------------------------

def test_the_scan_actually_examined_something():
    """A zero-invariant passes when the scan finds nothing — including when it looked at
    nothing. The round narrowed `skill_files()` to `glob("*/SKILL.md")` in one line,
    silencing the whole `_shared/` population with the suite green; `offenders[10:]` and
    a `fenced_blocks(text)[:1]` did the same. A floor kills that family at once."""
    files = S.skill_files()
    assert len(files) >= 33, f"skill population collapsed to {len(files)} files"
    shared = [f for f in files if f.parent.name == "_shared"]
    assert len(shared) >= 9, (
        f"the `_shared/` partials dropped out of the scan ({len(shared)} found) — they are "
        "shipped instruction text and carry the same class"
    )
    blocks = sum(len(S.fenced_blocks(_read(f))) for f in files)
    assert blocks >= 200, f"only {blocks} fenced blocks reached the scan"
    spans = sum(
        1 for f in files for _ in re.finditer(r"`[^`]+`", _read(f))
    )
    assert spans >= 1000, f"only {spans} inline spans reached the scan"


def test_a_redirect_on_its_own_line_is_scanned_not_treated_as_a_blockquote():
    """The round's headline, and the worst defect in this module's first draft.

    `fenced_blocks` blanked any fenced line starting with `>`. A shell redirection
    continued onto its own line has exactly that shape, so reverting the 31st of this
    phase's own converted sites left the entire suite green — while the maintainer
    worklist this module supersedes caught it. Blockquote-ness is now decided by the
    fence's OPENING line.
    """
    sample = (
        "```bash\n"
        'echo "PLAN_PHASE_VIOLATION" \\\n'
        '  > "$WORKTREE_PATH/sysop/runtime/auto-build/review.md"\n'
        "```\n"
    )
    assert {v for _, v, _ in S.phantom_shell_vars(sample)} == {"WORKTREE_PATH"}


def test_a_fully_blockquoted_fence_is_still_skipped_whole():
    """The other half of the same rule: a `>`-quoted fence really is an illustration.
    Several skills quote a retired shape that way, and flagging those would make the
    guard noisy enough to be switched off."""
    sample = "> ```bash\n> git checkout \"$RETIRED_VAR\"\n> ```\n"
    assert S.phantom_shell_vars(sample) == []


def test_short_and_braced_names_are_not_below_the_floor():
    """`$PR` is the value `/review-close`'s persistence note is *about* — an empty `gh`
    operand silently resolves the current branch. A three-character floor hid it."""
    for name in ("PR", "ID", "WT"):
        sample = f"```bash\ngh pr merge \"${name}\" --squash\n```\n"
        assert {v for _, v, _ in S.phantom_shell_vars(sample)} == {name}, name
    braced = "```bash\ngit checkout \"${MERGE_TARGET}\"\n```\n"
    assert {v for _, v, _ in S.phantom_shell_vars(braced)} == {"MERGE_TARGET"}
    # ...and the one string the floor existed to dodge stays exempt.
    currency = "```bash\n| TECH-X | EXECUTED | $X.XX |\n```\n"
    assert S.phantom_shell_vars(currency) == []


def test_inline_detector_covers_the_command_words_the_corpus_prescribes_in():
    """`/auto-fix` writes `mkdir -p <WORKTREE_PATH>/…` and `cd <WORKTREE_PATH> && git add -A`
    as inline list items — the same idiom `/auto-build` had wrong as `$WORKTREE_PATH`. A
    `git|gh|bash|python3|sh` list could never have seen those."""
    for span in (
        'mkdir -p "$RUN_DIR/out"',
        'rm -rf "$WORKTREE_PATH"',
        'cd "$WORKTREE_PATH" && git add -A',
        'cat "$VERDICT_FILE"',
        'pytest "$TEST_PATH" -q',
    ):
        line = f"Then run `{span}`.\n"
        assert [s for _, s in S.phantom_inline_commands(line)] == [span], span


# --------------------------------------------------------------------------------------
# 5. $ARGUMENTS never inside a fence (Phase 222, Q-013)
# --------------------------------------------------------------------------------------

def test_arguments_is_never_interpolated_into_a_fence():
    """`$ARGUMENTS` is ENV_PROVIDED for the *phantom* question — the harness really does
    supply it — but it is supplied TEXTUALLY, substituted into the skill body before
    bash parses anything. Inside a fence that makes it a command-rewrite vector: a `"`
    in the argument string closes any quoting, `;` starts a new command, and the
    unquoted form word-splits and glob-expands. Three shipped sites did this
    (`next-task`, `codebase-review`, `security-audit`); Phase 222 converted each to
    parse-then-pass — the agent substitutes recognized flags into a placeholder, and
    the raw string never reaches a command line. Prose mentions ("Parse `$ARGUMENTS`")
    are fine and are most of the corpus; fences are the class this forbids.
    """
    offenders = []
    for f in S.skill_files():
        text = f.read_text(encoding="utf-8")
        for start_line, block in S.fenced_blocks(text):
            for off, ln in enumerate(block.splitlines()):
                # `${ARGUMENTS}` too (round survivor AR-1): the braced form dodges a
                # literal substring, ENV_PROVIDED exempts the name from the phantom
                # check — and per the Phase 188 record the harness does not
                # substitute it at all, so the fence runs with silently empty args.
                if re.search(r"\$\{?ARGUMENTS\b", ln):
                    offenders.append(f"{f.parent.name}/SKILL.md:{start_line + off}: {ln.strip()[:80]}")
    assert not offenders, (
        "`$ARGUMENTS` interpolated inside a code fence — textual substitution happens "
        "before bash parses, so the argument string can rewrite the command (Q-013). "
        "Use the parse-then-pass placeholder shape instead:\n" + "\n".join(offenders)
    )
