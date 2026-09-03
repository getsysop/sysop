---
name: review-close
description: Senior review — review pending work, push to origin, verify staging, clean up
argument-hint: "[--dry-run]"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning inline=reasoning -->

Final gate before production. Reviews all pending work (feature branches AND unpushed main commits), pushes to origin, verifies staging, and cleans up.

## Resolve the default branch — before anything else

**Run this once, here, before the permission guard and before Step 1.** Every step below
compares against, diffs from, or pushes to the repository's default branch, and this skill
no longer assumes that name is `main`. **The permission guard immediately below is itself
one of those steps** — its required-rule list carries the placeholder, so resolving after it
would have the guard compare a placeholder against a concrete rule and hard-stop a correct
install.

```bash
bash sysop/scripts/default_branch.sh
```

It prints one bare name (`main`, `master`, `develop`, …) and exits 0, or prints nothing,
explains itself on stderr and exits 1. **On exit 1, stop** — do not fall back to `main`.
Every comparison this skill is about to make is against that name, and a close that
guesses it merges into a branch the repository may not have.

Substitute what it prints for `<default branch>` at every occurrence below.
**It is a placeholder, not a variable to set**, for two independent reasons: a Claude Code
allow rule does not match past a variable assignment, so `DEFAULT_BRANCH="$(…)"` binds no
rule and routes to the auto-mode classifier; and nothing survives from one fenced block to
the next (`WORKFLOW.md` § 8.2a *Persistence boundary*), so by Step 2 the variable would be
empty anyway. Run it bare and read the output — the same idiom Step 4-pre already uses for
`gh pr list`. See `_shared/main-push-guard.md` § Rule A, which this skill's Step 4d cites.

**The one allow rule that names the branch is seeded for you.**
`Bash(git reset --hard origin/<default branch>)` (Step 6) is an *exact-match* rule, and
`install.sh` writes it with this repository's own branch name at install time — so on a
`master` consumer the seeded rule reads `origin/master` and Step 6 binds it. An install
predating Phase 255 may still carry the hard-coded name; re-run
`sysop/scripts/sysop-update.sh`.
**Do not "fix" a non-binding rule by widening it.** `origin/:*` does not bind at all (the
`:*` form is only recognized at the *end* of a pattern), and `origin/*` admits any revision
expression after the slash — a `~50` suffix discards fifty commits of local history, and an
allow rule fully authorizes **at the permission layer** — the auto-mode classifier is a
separate, later gate that overrides allow rules for a few known-destructive shapes
(`WORKFLOW.md` § 8.2a), so what protects this grant is its narrowness, not an escalation.

**Prose below still writes `main` where it means the default branch as English** ("commits
on `main`", "local `main`"). That is a different class from the executable sites and is
deliberately outside `tests/test_skill_default_branch_literals.py`, which governs commands
rather than sentences. Where a sentence and a command appear to disagree, the command is
the instruction.

## Pre-flight: Permission Guard

Before doing anything, verify `.claude/settings.json` carries the allow-rules this skill depends on. Under `permissions.defaultMode: "dontAsk"`, a missing rule on `git merge --ff-only` or `git worktree remove` surfaces as an opaque halt mid-merge. Run the `_shared/permission-guard.md` algorithm — including its **step 3 mode check**, which skips the hard stop (but still prints the drift report) when the project declares `bypassPermissions`, where the allow-list is inert.

Read `.claude/settings.json` (and `.claude/settings.local.json` if present) and confirm `permissions.allow` satisfies every rule below:

- `Bash(git checkout:*)`
- `Bash(git fetch origin:*)` — the `_shared/main-push-guard.md` Rule B safe-push sequence fetches `origin/<default branch>` before the Step 4d push, so this is required under **both** merge policies, not just `pr`
- `Bash(git rebase:*)`
- `Bash(git rebase --abort)`
- `Bash(git -c core.editor=true rebase --continue)` — **exact match, and it has to be exact.** Step 4a's conflict route continues a rebase, and a bare `git rebase --continue` opens an editor: with none configured git falls back to `vi`, which in this harness **hangs until the tool timeout** and, when stdin is closed instead, exits 1 leaving the rebase mid-replay — a state Step 4a has no arm for. `-c core.editor=true` is the fix for the case that bites — no editor configured, or one configured through `EDITOR` — though **not** for an ambient `GIT_EDITOR`, which outranks `core.editor` and is measured to win; an autonomous close does not set one. It needs its own rule: `-c` is not one of the wrappers the Bash matcher strips, so `Bash(git rebase:*)` does **not** cover `git -c … rebase` ([permissions reference](https://code.claude.com/docs/en/permissions.md#process-wrappers)). An env-var prefix (`GIT_EDITOR=true git rebase …`) binds no allow rule either — allow rules do not match past an assignment
- `Bash(git merge --ff-only:*)`
- `Bash(git merge --no-ff:*)` — Step 4a's **published** arm. A published branch must not be rebased, so it is taken with a merge commit instead; `--ff-only` does not authorize `--no-ff` (the matcher compares literal text, and these differ from the flag onwards)
- `Bash(git worktree list:*)` — Step 1a + Step 3c's `--porcelain` worktree enumeration (the one read-only `git` form Sysop ships a rule for — see `_shared/permission-guard.md` § Notes)
- `Bash(git worktree remove:*)`
- `Bash(git branch -d:*)`
- `Bash(git push origin:*)`
- `Bash(git add:*)` — Step 4c step 7's shared-doc staging. Those are three plain, unwrapped `git add <path>` commands, which is what makes the wildcard the right shape here: the literal-path rules the template also ships (`git add tasks/index.yml`, `git add review_tasks.md`) cannot cover consumer-authored doc names like `UI_Iterations.md` or a changelog the project keeps under its own name. Note the review skills' Step 9 staging is **not** an exception any more: Phase 153 unrolled those loops into one plain `git add -A -- <path>` per path, so `Bash(git add:*)` covers them too. The shapes that still bind no rule are this skill's own runtime-set loops; see § Invocation shapes below
- `Bash(bash sysop/scripts/close_batch.sh:*)`
- `Bash(bash sysop/scripts/run_checks.sh)`
- `Bash(bash sysop/scripts/run_checks.sh:*)`
- `Bash(python3 -:*)` — Step 3c's smoke-gate detection heredoc **and** Step 4c's yaml-round-trip status flip + git mv + the `git add` of the index it rewrote (those git calls run *inside* the heredoc via `subprocess`, so they bind no Bash rule of their own). Both are single `python3 - <<` commands (literal `python3` command word, no PATH prefix or `&&` compound) so this one rule matches; venv PyYAML is resolved by an in-heredoc `sys.path` bootstrap, not a `.venv/bin/python3` invocation or an env prefix (BeanRider ISSUE-0049; Sysop Phase 126 — a `.venv/bin/python3` command word or a `VAR=… python3` prefix would each bind to no rule)
- `Bash(python3 sysop/scripts/validate_tasks.py)` — Step 4c's final-guard validator run (bare `python3`; the script self-resolves venv PyYAML via its own `sys.path` bootstrap, so this one form serves both venv-only and non-venv consumers — Sysop Phase 126)
- `Bash(python3 sysop/scripts/validate_tasks.py:*)` — same with `--quiet` / `--path`
- `Bash(python3 sysop/scripts/review_index.py:*)` — Step 4b's batch-set derivation (`--list`). Bare `python3`, for the same reason as the validator above: the script self-resolves venv PyYAML, so one form serves venv and non-venv consumers. **The command word is load-bearing** — this step prescribed `bash …review_index.py --list` until Phase 241, which binds no rule *and* cannot run: bash lexes the module's docstring as one quoted word and exits 2 with an empty stdout, indistinguishable from a batch-free cycle.

**Deliberate non-entries.** (One of them stopped being one — see the end of this paragraph.) Step 3b's pending-docs collect and its rollback used to run as `mkdir -p … && cp …` and a `for … rm -f … done` loop, which bound **no** allow-rule at all: the compound splits into `mkdir` + `cp` command words (Phase 126 matcher facts) and neither is in the seeded set, nor are `rm`, `mv` or `cmp`. **Phase 210 rebuilt both as `python3 - <<'PY'` heredocs, so they now bind `Bash(python3 -:*)`, which the 71-rule seed already carries.** The permission surface got smaller, not larger — one existing rule replaced four ruleless command words — and the change was driven by correctness rather than permissions: a provenance check is not expressible in that compound. **If some other part of this step ever *does* halt on a denial, nothing rescues it automatically — ask the user for the escape yourself.** The Phase 36 `PermissionDenied` hook matches a push to `origin` of one of the two branch names it **hard-codes** (`main` or `master` — *not* the resolved default branch, so on a consumer whose default is neither, no push matches), a `--delete` push of any branch, and `git commit` on a protected branch; a denied `mkdir` or `cp` falls through its matcher loop and it emits **nothing**, so the denial arrives with no guidance attached. Relay the literal `!`-prefixed command — **the `python3 -` heredoc as written, never the retired `mkdir -p … && cp …`**, which has no provenance check and is the form this step removed for the user to type at the next prompt, the same route Step 3 uses for a denied verification command, and never `AskUserQuestion`. Step 3b itself forbids proceeding to the worktree remove with the docs uncollected.

**Additionally, under `pr` merge policy only** (read `<project>/CLAUDE.md § Merge policy`; default is `direct` — see Step 4-pre): the PR-routed flow shells out to `gh` and a few extra git verbs. Require these too **only when the policy is `pr`** — a `direct`-policy consumer does not need them and must not be blocked for their absence:

- `Bash(git cherry-pick:*)` — Step 4-pre sweeps local-only `main` commits onto the integration branch
- `Bash(git reset --hard origin/<default branch>)` — Step 6 re-syncs local `main` after the PR squash-merges. **Substitute the resolved name before comparing:** this is an exact-match rule and `install.sh` seeds it with *this* repository's branch, so on a `master` consumer the shipped rule reads `origin/master` and comparing it against a hard-coded name would report a false miss
- `Bash(git branch -D:*)` — Step 6 deletes the integration + squash-merged feature branches
- `Bash(gh pr list:*)` — Step 4-pre's PR-reuse probe (`gh pr list --head … --base <default branch> --state open`)
- `Bash(gh pr create:*)` — open the integration PR against `main` (integration-branch shape only; the PR-reuse shape never calls it)
- `Bash(gh pr checks:*)` — wait on the PR's required checks
- `Bash(gh api:*)` — Step 4d command 4b's check-run count on the PR head (`repos/{owner}/{repo}/commits/<sha>/check-runs`), and the ruleset lookup its could-not-measure note points at. Read-only, but `gh api` can POST, so the rule is a deliberate grant rather than an inference from the verb
- `Bash(gh pr view:*)` — read the PR's merge state
- `Bash(gh pr merge:*)` — squash-merge the integration PR (non-`--auto`)

Every rule named above ships in the installer's seeded allow-list, so a consumer who ran `bash install.sh` (or `sysop-update.sh` at Phase 152 or later) satisfies this block on a fresh install under either policy. **A consumer whose skills are newer than their `settings.json` will not** — skill copies auto-update through the plugin path while the allow-list ships only through the installer, so if this block reports a rule you have never seen, run `sysop-update.sh` rather than hand-editing.

**§ Invocation shapes — keep the `pr` path rule-matchable.** A rule authorizes a *command*, not a *step*: the matcher compares against the literal text the model sends, splits on `&&`, `||`, `;`, `|`, `|&`, `&` and newlines, and requires each part to match. Until Phase 153 this skill's `pr` path defeated its own rules in three places — `PR_NUMBER="$(gh pr list …)"` and `PR_REF="$(gh pr create …)"` (a rule does not match past a variable assignment) and two `|| true` tails (`true` is not in the documented read-only set, though that set is documented as non-exhaustive, so this one is a strong inference rather than a stated fact). Those are now invoked bare, with the PR number and integration-branch name as quoted literals. **When editing Step 4-pre, 4d or 6, do not reintroduce them:** no capture into a variable, no `|| true` (use `|| echo …` — `echo` *is* in the documented read-only set), and no `for … done` around a set you could write out.

**What this block does NOT claim.** Two shapes remain and are not defects introduced here. First, this skill still iterates sets discovered at runtime, which cannot be unrolled into a static list — the shape is `while IFS= read -r`, and the bodies are read-only. **Two claims that used to sit here were false and are struck rather than trimmed, because both were cited as reasons not to look.** It named a `for … done` loop as the *Step 4a* branch pre-check: `$BRANCHES_TO_MERGE` only ever existed in **Step 1c**, and Phase 219 replaced that loop with `while IFS= read -r branch` after measuring the unquoted expansion iterate twice under bash and once under zsh. It also named a *Step 3b pending-docs strip* running `rm -f` inside a `for … done` — **Phase 210 rebuilt the pending-docs strip as a `python3 - <<'PY'` heredoc**, which the paragraph seventeen lines above this one already says, so the `for … done` it named is gone. **What is NOT gone, and the first correction of this sentence wrongly said was:** Step 3b still runs one `rm -f`, inside a `git status --porcelain | while IFS= read -r line` symlink strip. `WORKFLOW.md` names it as the only remaining `rm`-bearing loop in any skill; a sweep that reads this sentence as *"nothing in Step 3b deletes"* would be wrong, which is exactly how this paragraph gets cited as a reason not to look. Second, the reshaped `gh pr list` commands carry a `|` inside a single-quoted `--jq` argument, and whether the splitter is quote-aware is an open question the docs do not settle. So this block asserts that three *provable* defeaters are gone, not that every `pr`-path invocation is proven to bind. See `WORKFLOW.md` § 8.2a *Invocation shapes* for the full inventory. If any required rule (the always-required git set above, plus the `gh`/git set when the policy is `pr`) is unsatisfied, stop with the error message from `_shared/permission-guard.md` § Algorithm step 5 (substitute "merges approved feature branches and either pushes `main` directly or — under `pr` policy — assembles an integration branch and opens a squash-merge PR; updates `tasks/index.yml` via heredoc'd python and runs the validator as a final guard" as the one-line reason). Do not proceed — unless the guard's step 3 mode check applies.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and continue.

## Step 1: Gather State

Run these in parallel:
- `git branch -a` — all local and remote branches
- `git log --oneline origin/<default branch>..HEAD` — unpushed commits on main (if on main)
- `git branch --list | grep -v <default branch>` — local feature branches
- `git stash list` — any stashed work that might be forgotten
- `git worktree list --porcelain` — all worktrees (porcelain form is stable across git versions; consumed by Step 1a)

Identify two categories of pending work:
1. **Feature branches** — any non-main local branches (especially those marked `review_ready`)
2. **Unpushed main commits** — commits on main that are ahead of `origin/<default branch>`

### 1a. Classify Worktree State (silent-data-loss guard, BeanRider ISSUE-0016)

Branch tips are blind to uncommitted in-progress work. A `/claim-task`-ed branch where the agent did substantial worktree edits but never committed has a tip identical to a freshly-claimed branch with no work yet — Step 2a's commit-based verdict would say "no commits, reject" for both, and Step 6's cleanup would then try to remove the worktree. If a downstream codepath ever reaches for `--force` on `git worktree remove`, uncommitted work is silently destroyed. **No shipped skill does today** — no skill in this install contains `git worktree remove --force`, and the only forced removals anywhere are the opt-in `--force` arms of `claim_task.sh --release` and `batch_work.sh --release` (an earlier version of this sentence attributed such paths to `/auto-judge` and `/document-work`, which have none; corrected Phase 165, the same wrong-capability class as `/auto-build`'s "clears the lock" claim). The guard below is what keeps it that way.

For every worktree from `git worktree list --porcelain` (excluding the **primary checkout**, identified by path rather than by branch name — see the loop), classify the state by running `git -C <worktree-path> status --porcelain` and combining with the branch's commit position relative to main:

```bash
# Use --porcelain to make the worktree listing machine-parseable.
# main_root is the PRIMARY checkout. It owns the .gitignore rules the symlink
# downgrade below consults (BeanRider ISSUE-0043), and it is also the worktree this
# loop skips. Resolve it with `--git-common-dir`, never `--show-toplevel`: the latter
# answers "which worktree am I standing in", which is the primary only when the runner
# happens to be standing there (Phase 234, `Q-020`/`Q-307`(b) — the class this file was
# not swept for). `--git-common-dir` prints a CWD-relative `.git` from inside the
# primary and an absolute path from a linked worktree; `cd`-ing to its parent resolves
# both, verified from the primary root, a primary subdirectory, and a linked worktree.
main_root=$(cd "$(git rev-parse --git-common-dir)/.." && pwd -P)

# The primary is matched two ways, because neither alone covers every layout.
# `git worktree list --porcelain` lists the MAIN worktree FIRST (documented behaviour),
# and that is the only handle that survives a `--separate-git-dir` checkout, where the
# listing names the *gitdir* and `-ef` against `main_root` matches nothing — so the
# primary would be classified like a feature worktree and `git -C` would fatal inside
# the loop. `-ef` covers everything else and is the semantic test; this is the fallback.
primary_wt=$(git worktree list --porcelain \
  | awk '/^worktree /{sub(/^worktree /, ""); print; exit}')

# Is the primary ITSELF a claim workspace? `claim_task.sh --branch` sets
# `WORKSPACE_PATH="$REPO_ROOT"`, so on that mode the work-in-progress lives in the primary
# checkout and IS the paused work this guard exists to protect (BeanRider ISSUE-0016).
# Skipping the primary unconditionally would hand a half-implemented `--branch` claim to
# Step 2a as reviewable — restoring the silent-merge this step prevents, for one mode.
# The lock records `workspace:`, so ask it rather than guessing from the branch.
# One pipeline, no `for`/`done`: those are not documented command separators, so no
# allow-rule binds a loop, and Phase 210's precedent is to avoid adding one rather than
# to claim another exception for it. An exact line match is sound here because BOTH
# sides are physical paths from git -- `claim_task.sh` records `workspace: $REPO_ROOT`
# from `git rev-parse --show-toplevel`, which resolves symlinks, and `main_root` above
# is `pwd -P`. Verified: reached through a symlinked CWD, both still print the same
# physical spelling, so the `-ef` robustness a loop would buy has nothing to fix.
primary_claimed=$(grep -lxF "workspace: $main_root" \
  "$main_root"/sysop/runtime/locks/*.lock 2>/dev/null | head -1)

# Parsed with case/parameter-expansion rather than awk: a bare `$<N>` in a skill body is
# replaced by the invocation's (N+1)th argument word before bash sees it (internal tracker #360).
# The substitution is 0-based, so `$<2>` needs a THIRD argument word — and this skill's whole
# argument surface is one optional word (`argument-hint: "[--dry-run]"` above), so index 2 is
# always out of range and stays literal. The awk form was never broken here; it is avoided
# because a wider argument surface would reach it. The site that DID substitute was Step 3c's
# `$<0>` — the first word, which `--dry-run` replaces — emptying the worktree path and silently
# defeating the manual-smoke gate (BR ISSUE-0008).
git worktree list --porcelain | while IFS= read -r _line; do
  case "$_line" in
    "worktree "*)          _wt=${_line#worktree } ;;
    "branch refs/heads/"*) printf '%s\t%s\n' "$_wt" "${_line#branch refs/heads/}" ;;
  esac
done | while IFS=$'\t' read -r wt_path branch; do
  # Skip the PRIMARY checkout — by identity, never by branch name — UNLESS it is itself a
  # claim workspace. It is normally the runner's vantage rather than a feature worktree,
  # and no step in this skill removes it, so it is outside the silent-data-loss guard's
  # subject. Testing `$branch == "<default branch>"` instead misclassifies the ordinary case of a
  # feature branch checked out in the primary (a change not started through `/claim-task`):
  # one untracked file there classifies the runner's own vantage `dirty`, and Step 2a step 0
  # turns that into an automatic SKIP, excluding from Steps 3b, 4 and 6 a branch whose
  # commits already passed every gate. `-ef` compares device and inode, so a differing
  # symlink or case spelling of one directory still matches — `close_batch.sh`'s
  # `close_landed_on_main` tests primary-ness the same way for the same reason.
  # `$primary_claimed` is the `--branch`-mode carve-out: there the primary IS the workspace,
  # so its dirty state is exactly the paused work this step must not wave through.
  if [[ -z "$primary_claimed" ]] \
     && { [[ "$wt_path" -ef "$main_root" ]] || [[ "$wt_path" == "$primary_wt" ]]; }; then
    continue
  fi

  porcelain=$(git -C "$wt_path" status --porcelain)
  ahead=$(git log --oneline "<default branch>..$branch" 2>/dev/null | wc -l | tr -d ' ')

  # Downgrade non-work noise before classifying. An untracked symlink whose target
  # is gitignored in the main repo — e.g. a `.venv` symlink into the main repo's own
  # venv — is a tooling convenience, not paused work: `.venv/` is a *directory*
  # pattern, so it never matches the symlink and `git status` surfaces it as
  # `?? .venv`, which the old any-porcelain-line rule mis-read as `dirty` (forcing a
  # false SKIP + a Step 3b remove-refusal, BeanRider ISSUE-0043). Keep every other
  # line — modified tracked files, real untracked files, and any symlink whose
  # target is not provably ignored — so the silent-data-loss guard stays intact.
  significant=$(printf '%s\n' "$porcelain" | while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if [[ "$line" == '?? '* ]]; then
      # NB: name it `entry`, never `path` — `path` is a special array in zsh (tied to
      # $PATH), and these bash blocks are often executed by the agent's default shell
      # (zsh on macOS), where a bare `path=…` silently clobbers PATH and breaks the loop.
      entry=${line#'?? '}
      if [[ -L "$wt_path/$entry" ]]; then
        target=$(readlink "$wt_path/$entry")
        # Resolve a relative symlink target against the symlink's own directory so
        # check-ignore (which needs a path git can place inside the repo) can match it;
        # an absolute target is used as-is; a broken/out-of-repo one falls through empty
        # and is conservatively kept (classified dirty — never silently removed).
        case "$target" in
          /*) : ;;
          *)  target=$(cd "$wt_path/$(dirname "$entry")" 2>/dev/null && cd "$(dirname "$target")" 2>/dev/null && printf '%s/%s' "$PWD" "$(basename "$target")") ;;
        esac
        git -C "$main_root" check-ignore -q "$target" 2>/dev/null && continue
      fi
    fi
    printf '%s\n' "$line"
  done)

  if [[ -n "$significant" ]]; then
    lines=$(printf '%s\n' "$significant" | wc -l | tr -d ' ')
    echo "DIRTY    $branch  ($wt_path)  — $lines pending changes"
  elif [[ "$ahead" -gt 0 ]]; then
    echo "AHEAD    $branch  ($wt_path)  — $ahead commits ahead of main"
  else
    echo "MERGED   $branch  ($wt_path)  — tip matches main (claim-only or already merged)"
  fi
done
```

The three classes are:

- **`clean-merged`** — tip is an ancestor of main AND `git status --porcelain` is empty. Either a never-touched claim branch or an already-merged-but-not-cleaned-up branch. Safe to remove in Step 6.
- **`clean-ahead`** — tip has commits ahead of main AND `git status --porcelain` is empty. Normal review path; proceed to Step 2a's commit-based inspection.
- **`dirty`** — after the symlink downgrade above, the *significant* set (`git status --porcelain` minus the downgraded lines) is still non-empty. **Paused mid-implementation work.** Step 2a will produce an automatic SKIP verdict for this branch and Step 6 must refuse to touch the worktree. Two classes of noise are already excluded so they don't false-positive into `dirty`: gitignored `sysop/runtime/locks/` and `sysop/runtime/pending-docs/` never appear in `--porcelain` without `--ignored` (this assumes the branch's checked-out `.gitignore` carries the installer's `sysop/runtime/` append — a worktree honors only *committed* ignore rules, so a branch cut before that append was committed will show `?? sysop/runtime/` until it's rebased/merged in; the installer's migration output says to commit the append before claiming); and an untracked symlink whose target is gitignored in the main repo (a `.venv`-into-the-main-venv tooling convenience) is downgraded out of the significant set (BeanRider ISSUE-0043). Everything with reviewable content — modified tracked files, real untracked files, and any symlink whose target is not provably ignored — stays significant, so the silent-data-loss guard is unweakened.

Carry each branch's classification into Steps 2a, 3b, and 6 — they all consult it.

### 1b. Preserve Uncommitted `review_tasks.md`

Check `git status -- review_tasks.md` for uncommitted changes. Two distinct shapes can produce a dirty `review_tasks.md`: new open tasks from `/codebase-review` / `/security-audit` (single-file commit) and an in-flight archive rotation that also touches a sibling archive file (atomic two-file commit). Pick the right shape — splitting an archive rotation across two commits leaves the archive file untracked and confuses Step 4a's rebase.

**Detect the shape:**

```bash
# Is review_tasks.md dirty at all?
git status --porcelain -- review_tasks.md | grep -q . || exit 0   # nothing to do

# Compute net deletions in review_tasks.md from the working tree against HEAD.
# numstat is tab-separated (added<TAB>deleted<TAB>path), so `cut` reads it directly.
# `awk '{print $<1>+0}'` would be rewritten to `{print <second argument word>+0}` by the
# skill runner before bash saw it (internal tracker #360).
#
# awk's `+0` coerced TWO cases to a number that `cut` does not: no output at all, and a
# BINARY row, which numstat prints as `-<TAB>-`. `${…:-0}` only covers the first — `-` is
# non-empty — and the `DELETED > ADDED` test below would then die with
# `[: -: integer expected`. So non-numeric output is normalised to 0 explicitly.
ADDED=$(git diff --numstat HEAD -- review_tasks.md | cut -f1)
DELETED=$(git diff --numstat HEAD -- review_tasks.md | cut -f2)
case "$ADDED" in ''|*[!0-9]*) ADDED=0 ;; esac
case "$DELETED" in ''|*[!0-9]*) DELETED=0 ;; esac

# Is a sibling archive file dirty or untracked? Common names: review_tasks_archive.md
# at repo root, or any *_archive.md the project's archive-rotation script writes.
# Consult <project>/CLAUDE.md § Key Files for the consumer-specific path if non-default.
git status --porcelain | grep -qE '(^\?\? |^ M | M )review_tasks_archive\.md( |$)' && SIBLING_DIRTY=1 || SIBLING_DIRTY=0
```

**Branch on the result:**

- **Archive-rotation commit (atomic two-file):** if `SIBLING_DIRTY=1` AND `DELETED > ADDED` (review_tasks.md has net deletions — sections were rotated out, not added), `git add` both files together and commit with `docs: archive <round-or-batch-list> to <archive-file>`. The two files are halves of one atomic rotation and MUST land in one commit. The deletion-direction check distinguishes a rotation (net deletions in review_tasks.md, content moved to the archive) from a same-cycle scenario where new tasks were added AND the archive file was independently touched — that second case is rare and warrants manual judgment, not the atomic-rotation message shape.

- **Single-file commit (default):** otherwise, run `git add review_tasks.md && git commit -m "docs: save pending review tasks"`. This covers the canonical `/codebase-review` / `/security-audit` flow.

- **In-place rotations** (projects whose archive script moves sections within `review_tasks.md` rather than to a sibling file — e.g., to a `## Archive` heading at the bottom): `SIBLING_DIRTY=0` so the detect branch falls through to the single-file path, which is correct for that shape. The commit message will say "save pending review tasks" rather than "archive ..."; if the consumer wants the rotation message, they can either configure their archive script to write a sibling file (matching the canonical shape) or manually amend the message after Step 1b.

This **must** happen before any branch merges — Step 4a's rebase needs main's `review_tasks.md` to reflect any rotation, else feature branches cut before the rotation will conflict on stale section boundaries (see Step 1c).

### 1c. Drain Archive State Before Rebasing

If Step 1b committed an archive rotation on `main`, any feature branch cut from `main` *before* that rotation commit will hit a structural rebase conflict at Step 4a — its ancestor `review_tasks.md` still has the rotated-out sections that no longer exist on main. This step **warns** about that condition; resolution still happens at Step 4a using the updated prose there. The warning lets the agent set expectation (and choose to defer the affected branch to a separate cycle if the conflict would be expensive to resolve).

**Detection (file-based, not commit-subject-based).** Enumerate the feature branches in scope for this round (the same set Step 2a will review — non-main local branches, typically those marked `review_ready`). For each, find its merge-base with main and check whether main has touched any archive file since that base:

```bash
# Archive file pattern. Default covers the canonical review_tasks_archive.md
# at repo root. Consumers with a different archive path should set ARCHIVE_RE
# from <project>/CLAUDE.md § Key Files before running.
ARCHIVE_RE='(^|/)review_tasks_archive\.md$'

# In-scope branches: non-main local branches the agent is about to merge.
# `worktree-agent-*` are review sub-agents' isolated checkouts (Step 2b), not
# feature work — exclude them here and everywhere else branches are enumerated.
# Enumerate and iterate in ONE pipeline, `while read` rather than `for … in $VAR`.
# The previous form assigned the list to BRANCHES_TO_MERGE and looped over the
# UNQUOTED expansion. bash word-splits that on IFS; **zsh does not** — SH_WORD_SPLIT
# is off by default there, so an unquoted parameter stays one word. Measured against
# the same two branches: bash 2 iterations, zsh 1. The zsh run handed the whole
# newline-joined string to `git merge-base` as a single ref, which fatals, and the
# check then finished having evaluated nothing — no warning, no error the reader
# would connect to this block. `while IFS= read -r` iterates lines in both shells.
echo "--- Step 1c: archive-rotation pre-check"
git for-each-ref --format='%(refname:short)' refs/heads/ \
  | grep -v '^<default branch>$' | grep -v '^worktree-agent-' \
  | while IFS= read -r branch; do
      # One line per branch, so a run that enumerated NOTHING is visibly different
      # from a run that checked everything and found nothing. That difference is the
      # whole defect above: silence read as a clean result.
      echo "checked: $branch"
      base=$(git merge-base <default branch> "$branch")
      # Did main touch an archive file since this branch was cut?
      if git diff --name-only "$base..<default branch>" -- | grep -qE "$ARCHIVE_RE"; then
        echo "WARN: $branch was cut before an archive rotation on main;"
        echo "      Step 4a's rebase will likely conflict on review_tasks.md."
        echo "      Resolve per Step 4a guidance, or skip this branch this cycle."
      fi
    done
```

**No `checked:` line at all means the enumeration was empty — not that every branch passed.** Read the two apart before moving on; they were indistinguishable until Phase 219.

This is a **soft warning, not a hard gate** — informational only. The agent proceeds to Step 2 regardless; Step 4a's updated prose handles the actual conflict if it materializes. Hard-gating here would block legitimate close-outs whose conflict turns out to be trivial (single-line checkbox flip rebasing onto a slightly-shifted layout). If the warning fires repeatedly for a branch and the resolution is consistently expensive, that's project-side friction worth logging via Step 7's friction capture.

If the enumeration yields no branches (only unpushed main commits this cycle), Step 1c is a no-op — skip cleanly; you will see the `--- Step 1c` header and no `checked:` line at all. This sentence named `$BRANCHES_TO_MERGE` until Phase 219's own round caught it: the pipeline above no longer assigns that variable, so the reference was a phantom minted by the commit that removed the class.

## Step 2: Review Pending Work

### 2a. Feature Branches

For every non-main local branch — excluding any **agent worktree branch** (a branch whose registered worktree lives under `.claude/worktrees/`; on Claude Code these are named `worktree-agent-<id>`). Those are review sub-agents' scratch checkouts, not anyone's feature work; Step 2b's HARD RULE covers removing leaked ones. Do not review, approve, reject, or merge them:

0. **Worktree-state pre-check (Step 1a result).** If Step 1a classified this branch's worktree as `dirty`, the verdict is **SKIP — paused work present**. Do NOT inspect the diff and do NOT propose approve/reject — uncommitted worktree changes mean the branch is mid-implementation, not in a reviewable state. Report the dirty file count and the recommendation: *"`<N>` pending changes in `<worktree-path>`. Commit-as-WIP, stash, or leave alone — re-run `/review-close` after the user decides. This branch is excluded from Step 3b (worktree removal), Step 4 (merge), and Step 6 (cleanup) for this run."* Then continue to the next branch. A SKIP'd branch is distinct from both `approve` and `reject`: it is not merged, but its worktree, lock, and branch are all preserved untouched.

1. `git log <default branch>..<branch> --oneline` — what commits are on it
2. `git diff <default branch>...<branch> --stat` — scope of changes
3. Read the diff. Check for correctness, security issues, and alignment with the task body — path from `tasks/index.yml`'s `body:` field for each task ID the branch claims (a claim does **not** move the body, and there is no `tasks/in_progress/` directory in any shipped layout, so it stays where it was written — normally the file `tasks/open/<TASK_ID>.md`, which `body:` records canonically as `open/<TASK_ID>.md`, relative to `tasks/` — until Step 4c's archive move). Read it **at the branch tip**, per Step 2d's revision note: a branch edits its own body, and the working tree is still `main`.
4. Verdict: **approve** (merge to main) or **reject** (report reason, leave branch)

> **Three dots on every `git diff` in Step 2 — 2a, 2b and 2d (internal tracker #241).** `git diff <default branch>..<branch>` compares the two *tips*, so everything `main` gained after the branch was cut renders as though the branch **deleted** it. That is not a rare condition: `/review-close` manufactures it, because Step 1b commits `review_tasks.md` to `main` before any branch is inspected. `git diff <default branch>...<branch>` diffs against the merge-base and shows exactly what the branch contributed. A false BLOCK costs a human round-trip; a **false APPROVE** — real hunks buried under phantom deletions — is the worse direction and gets likelier the staler the branch is. **`git log <default branch>..<branch>` keeps two dots**: for `log`, two-dot already means "commits on the branch and not on `main`," which is what step 1 wants. The rule is per-command, not a blanket search-and-replace.

### 2b. Prevention Convention Check

**Targets.** One agent per **approved-or-rejected** feature branch, plus **one for the unpushed-main commits as a group** if there are any. A branch Step 2a classified **SKIP — paused work present** is *not* a target: it is not merging this run, and a `VERDICT: BLOCKED` on it would halt the close over work already declared out of scope. These calls can be parallelized — launch one agent per target simultaneously.

Each target has a **diff basis**, used identically by step 0's predicate and step 1's retrieval:

| Target | Diff basis |
|---|---|
| feature branch `<branch>` | `git diff <default branch>...<branch>` |
| unpushed-main group | `git diff origin/<default branch>...HEAD` |

If the repo has no `origin` remote, or `HEAD` is not `main`, there is no unpushed-main group — skip that target rather than running a command that will fail or silently diff something else. (Step 1's `git log --oneline origin/<default branch>..HEAD` is already qualified "if on main"; this is the same condition.)

**0. Per-target doc-only skip (internal tracker #240).** Compute the target's diff basis first. If it touches **no** code files (the same code-file set Step 3 uses — `.py` / `.ts` / `.tsx` / `.js` / `.jsx` / `.sql` / `.sh` / `.kt` / `.swift` / `.go` / `.rs`) **and** the project's conventions contain no rule that governs the file types the diff *does* touch, skip the agent for that target with a one-line note (`2b: <target> — doc-only diff, no code-convention surface`). **"The project's conventions" is THREE sources, not one section (`Q-328`).** Until Phase 241 this conjunct named `## Prevention Conventions` alone, which made the skip fire over a target governed solely by a rule living anywhere else — and Sysop's own shipped template puts convention content elsewhere, so this was not a consumer quirk. Read all three before concluding the conjunct holds:

   1. **`## Prevention Conventions` in `<project>/CLAUDE.md`**, every subsection.
   2. **The other CLAUDE.md sections that carry convention content.** `WORKFLOW.md` § 6.1's required-sections table lists **`## Testing Patterns` as its own top-level section**, beside `## Prevention Conventions` and not inside it. A consumer who followed the shipped template therefore keeps testing conventions in a section this predicate never read. Treat any required or optional section naming rules the diff's file types could violate as in scope.
   3. **The convention map** — `.claude/convention_map.project.md` (the consumer overlay `WORKFLOW.md` names as the documented home for path routing) and the shipped `convention_map.md` beneath it. This predicate was **map-blind**: the map is the one artifact that routes *globs* to conventions, which is precisely the question being asked, and it was consulted nowhere. A glob in either map matching a path this diff touches is a governing rule — **do not skip**.

   If any of the three yields a rule that could govern the touched types, spawn the agent and let it route. The skip is licensed by a *searched* absence, across all three, not by the absence of a section you happened to read. Docs-only cycles are not an edge case here — Step 7's own friction capture generates them routinely.

   **This skip is about step 3's agent and does not reach step 3b's** (`Q-352`). The two gates ask different questions of the same diff, and a diff can pass this one while failing that one: the security map routes documentation paths *by design* — the **core** map routes `.claude/skills/**/*.md`, and the llm pack routes `<prompts dir>/**/*.md` — so a target skipped here as doc-only can still match a security glob. (An earlier draft claimed `security_map.md` *"routes root operational docs to **A02**"*. It does not: the core map's five sections are shell scripts and hooks, `Dockerfile`, `.gitignore`/`.env*`, CI workflows and skill markdown, and the only A02-routed root paths among them are configuration, not documentation. Note also that the llm-pack glob is a **placeholder** until a consumer localizes it, so on a stock install `.claude/skills/**/*.md` is the concrete member carrying this argument.) Evaluate step 3b's gate on its own; a cascade would silence the security lens on exactly the diffs it was added for.

> **Check the second condition; do not assume it.** "Docs cannot violate a convention" is false often enough to be dangerous, and Sysop's own shipped maps are the counter-examples: `core/companion/convention_map.md` routes `.claude/skills/**/*.md` to five conventions including *No secrets in examples*; the beancount pack routes a per-vendor `README.md` to **"Synthetic content only: NO real account numbers, payees, amounts, addresses"** and `<ledger>.beancount` to *No PII in git-tracked ledgers*; the llm pack routes `<prompts dir>/**/*.md` to template rules. **None of those is scanner-shaped** — the beancount rule asks a reader to judge whether a digit string *looks* real, which no entropy or pattern scanner does. So the skip is licensed by the *absence of an applicable rule*, not by the file extension. Read the conventions (you need `## Prevention Conventions` for step 1 anyway; the other two sources are this predicate's alone), and if **any of the three** names documentation, config, prompts, fixtures, or committed data — in a subsection, in another CLAUDE.md section, or as a glob in either convention map — **do not skip** — spawn the agent and let it route. **The escape used to be sealed inside the one section the predicate read**, so a project whose only doc-governing rule lived in a map glob or in `## Testing Patterns` got the skip *and* the escape wrong together, from the same blind spot. Secret-scanning (`security_map.md` routes root operational docs to **A02**) is a separate expectation covered by the project's scanner, and this skip neither touches nor waives it.

Step 2a still reads the diff either way. If every target skips, Step 2b is a clean no-op; say so in one line rather than reporting nothing.

**For each remaining target:**

1. Read the **entire** convention-bearing set of `CLAUDE.md`, every subsection — **not `## Prevention Conventions` alone (`Q-342`)**. Subsection names vary by project: a web project might have `Frontend`/`Backend`/`Auth boundaries`; a data-pipeline project might have `Data integrity`/`Privacy`/`Schema evolution`; an MCP server might have `MCP server boundaries`. **The set is `## Prevention Conventions` + `## Testing Patterns`, plus any other section step 0 identified as carrying a rule the diff's file types could violate.** Those two are named because `WORKFLOW.md` § 6.1's required-sections table is what makes them rule-bearing — `## Prevention Conventions` is *"the actual convention rules"*, `## Testing Patterns` is *"test framework, fixture patterns, mock patterns"* — while `## Architecture`, `## Key Files`, `## Commands` and `## Environment Variables` describe the project rather than constrain it. **That is an illustration, not a partition of the table** — § 6.1 lists more rows than those, several of them (`## Pre-merge verification`, `## Merge policy`, `## Plan review`) operational rather than descriptive, and none convention-bearing in the sense this paste needs. **Read the two named members as the floor and step 0's answer as the rest**: the tail is a judgement, step 0 already made it, and this step consumes that answer instead of re-deriving it.

   > **This reverses a scoping Phase 241 took deliberately, and the reversal is the point.** That phase closed `Q-328`'s *skip predicate* — step 0 now reads three sources — but left this paste at one section and wrote here that the narrowing was intentional: *"what a sibling section governs is step 0's question."* It is not. Step 0 decides **whether to spawn**; step 1 decides **what the agent is given**. Splitting them that way produced an agent that runs, routes and reports honestly against a taxonomy missing the very section that kept it from being skipped — a narrower review, arrived at by a gate working exactly as written. Nobody is told a check happened that did not, which is why `Q-342` was filed § Medium and not § High; it is still the wrong answer.
   >
   > **The filing's own preferred remedy was option (c) — amend § 6.1 to make `## Testing Patterns` a subsection of `## Prevention Conventions` — and it is refused here.** It settles the template's self-consistency and fixes nothing: a consumer who already followed the shipped template has the section at top level, so the paste would keep missing it. (c) is cheap because it changes no behaviour, and that is also why it is not a fix. Option (b), driving the paste off the convention map, remains the larger reshape the filing calls *"arguably the right shape"*; it is not this phase's.
   >
   > **The filing also forbids taking this option without measuring the paste against the threshold below, so it was measured — on both real consumers, not estimated.** GDP (the reference consumer): `## Prevention Conventions` 53,456 chars, `## Testing Patterns` 3,637, widened total **57,093**. BeanRider: 3,662 + 456, widened total **4,118**. **The widening moves neither consumer across the 10,000-character threshold** — GDP was already on the write-once arm and stays there, BeanRider was already on the inline arm and stays there. The worry the filing raised, that widening *"silently moves reviewers onto an unmeasured arm"*, does not materialise on either: for BeanRider to flip, the threshold would have to fall inside a 456-character window. The tail section step 0 may add is unbounded in principle, which is why the measurement command below measures the set it actually assembled rather than these two numbers.

   Retrieve the full diff — the target's **diff basis** from the table above, three dots, per Step 2a's note. Whichever arm you take below, a two-dot diff hands the reviewer `main`'s newest content as though the branch had torn it out.

   **Paste or write-once — the conventions threshold is 10,000 characters of section text (Phase 222, Q-275).** The section is identical for every agent, so above the threshold pasting it N times is pure duplication (measured: 53,456 characters × a 13-agent close ≈ 174k tokens of the same text). Measure it, do not estimate it — the same rule as the diff threshold below, and the command matches the `Bash(python3 -:*)` idiom every other measurement here uses:

   ```bash
   # Measure the WIDENED set, not one section (`Q-342`). Add any further
   # section step 0 identified to SECTIONS before running this -- measuring a
   # narrower set than you paste is how a prompt silently lands on the wrong arm.
   python3 - <<'PY'
   import re
   SECTIONS = ["Prevention Conventions", "Testing Patterns"]
   text = open("CLAUDE.md", encoding="utf-8").read()
   total = 0
   for name in SECTIONS:
       m = re.search(rf"^## {re.escape(name)}$.*?(?=^## |\Z)", text, re.M | re.S)
       n = len(m.group(0)) if m else 0
       print(f"{n:>8}  ## {name}" + ("" if m else "   (absent)"))
       total += n
   print(f"{total:>8}  TOTAL")
   PY
   ```

   A section that is absent contributes 0 and is not an error — `## Testing Patterns` is a required section, but a consumer who has not written one has no testing conventions to route against, which is a different thing from a missing file.

   **A `TOTAL` of 0 means the CLAUDE.md paste has nothing to contribute — say so and CONTINUE, do not stop.** ⚠ **This step's first version said the opposite** (*"you must not proceed on it … a contradiction, not an answer"*), and the round's execution lens disproved it by running the measurement against **this repo's own `CLAUDE.md`**, which has neither section: Sysop is a documented consumer of itself — its `## Merge policy` section exists for exactly that — and a branch touching `install.sh` and `tests/` is not doc-only, does not skip at step 0, reaches here, and measures **0**. The rule as first written would have halted `/review-close` in the repo that ships it, and nobody had run it there.

   **The premise was wrong, not just the threshold.** Step 0 licenses the spawn from **three** sources, and the third is the convention **map** — so a project can legitimately arrive here with every rule in `.claude/convention_map.project.md` and none in `CLAUDE.md`. That is not a contradiction; it is the shape this very repo has. Report `2b: <target> — no CLAUDE.md convention sections; routing against the map alone`, hand the agent the map rather than an empty paste, and continue.

   **What a 0 does oblige is one check, because two of its causes are malformations rather than absences.** Before accepting it, confirm the sections are genuinely absent rather than unmatched: `grep -nE '^#{1,6} *(Prevention Conventions|Testing Patterns)' CLAUDE.md`. A hit the measurement scored 0 means a heading level (`###` instead of `##`, which § 6.1 makes top-level) or trailing whitespace — **a real defect in the consumer's file, and one this step should name rather than absorb.** No hit means genuine absence: the project keeps its conventions somewhere this measurement does not look, which is **the common case and not an error** — Sysop's own repo is the worked example, its rules living under `## Conventions for working in this repo`, a section § 6.1 does not name. Do not report an absence as a malformation you failed to locate. Continue either way, and say which of the two it was. **The measurement is also fence-blind and first-match-wins** — see `Q-361`; those behaviours predate this widening and change only which arm is selected, never what gets pasted.

   **At or below 10,000, paste it into every prompt as before** — the dominant small-project path keeps the behaviour in use, and a paste has no failure mode. **Above 10,000, write it ONCE and hand every agent the same copy:**

   ```bash
   rm -f sysop/runtime/2b-conventions.md
   mkdir -p sysop/runtime
   ```

   then write **every section in the set, verbatim, every subsection, unfiltered** to `sysop/runtime/2b-conventions.md` in the **primary** worktree with the `Write` tool — each under its own original `## <name>` heading, in the order above, so the agent can still cite which section a rule came from — and substitute that file's **absolute path** into each prompt's `## Project conventions` block (second arm below). The `rm -f` first is the same loud-failure discipline as the baseline capture in step 2: without it, a run that skips the write hands every agent the *previous* close's conventions, silently. The authority question this resolves is stated in the prompt arm: agents read the orchestrator's copy, **never their own worktree's `CLAUDE.md`** — each worktree checks out its *branch's* version of that file, and a branch that edits the conventions would otherwise have each reviewer routing against a different taxonomy.

   **Paste or retrieve — the threshold is 1,000 lines of `git diff` output.** Measure it, do not estimate it:

   ```bash
   # The table above gives the diff basis as a WHOLE COMMAND, so write it out — do not
   # substitute it as an argument to another `git diff`. `git diff <a whole git diff
   # command>` fatals on an ambiguous argument, `wc -l` counts the empty stdout as 0,
   # and every target then scores below the threshold: the gate reads as "paste" for a
   # 452 KB diff and says nothing. Found by executing it.
   DIFF_LINES=$(git diff <default branch>...<branch> | wc -l | tr -d ' ')          # feature branch
   DIFF_LINES=$(git diff origin/<default branch>...HEAD | wc -l | tr -d ' ')       # unpushed-main group
   ```

   - **At or below 1,000 lines:** paste the diff verbatim into the prompt's `## Diff` block, as before. The paste is cheaper than the round-trip, and the reviewer starts reading immediately.
   - **Above 1,000 lines:** paste the `--stat` summary instead (`git diff <default branch>...<branch> --stat`, or `git diff origin/<default branch>...HEAD --stat`), then the literal retrieval command on its own line — the same basis, three dots, no `--stat` — and say the hunks must be read before reviewing. Each agent runs with `isolation: "worktree"`, so it has its own checkout and can retrieve this itself.

   > **Why a threshold and not a rule either way, and where the number comes from.** Measured over **ten branch-shaped merges** — one agent's worth of work each — in one real consumer repository; `review-close: consolidate` integration commits are excluded, because an integration branch is not a single 2b target. The ten are enumerated by commit in this project's maintainer record, not by a date range: a date range is not a stable population, and the first form of this sentence used one that had already stopped selecting the ten it quoted. Their diffs were 88, 224, 272, 273, 332, 366, 641, 2141, 2376 and 13,606 lines (5 KB – 452 KB). **Seven of ten sit under 700 lines; the top three are 77 KB, 112 KB and 452 KB.** A 1,000-line cut separates that population where it actually separates — anywhere in the 641→2141 gap gives the same split — and the number is a stated choice anchored on that measurement, not a claimed optimum. Above the cut the paste dominates the prompt and, at the top of the range, crowds the conventions section the agent is being asked to route against. Below it, retrieval buys nothing and costs a tool call.
   >
   > **What this does NOT claim.** Nobody has measured whether a retrieval-only reviewer finds what a pasted-diff reviewer finds. The threshold is sized so the dominant path (7 of 10 targets) keeps the behaviour that has been in use, and only the tail — where the paste is a liability on its own terms — changes. **The duplication this step used to carry was elsewhere:** the `## Prevention Conventions` section was pasted *identically* into every agent's prompt (53,456 characters in the reference consumer), whereas each agent's diff is its own target's and is not duplicated at all. Phase 222 (Q-275) gave the conventions their own paste-or-write-once threshold — step 1 above — on the same keep-the-dominant-path logic as this one.

2. **Capture the primary-tree baseline — before any agent is spawned.** Step 3's assertion is a *delta* against this file and there is nothing to compare against if you skip it. It must run here, ahead of the spawn below; a baseline taken afterwards records the breach as though it were pre-existing and the assertion then certifies the tree clean.

   ```bash
   rm -f sysop/runtime/2b-baseline.txt sysop/runtime/2b-config-baseline.txt
   mkdir -p sysop/runtime && git config --local --list | sort > sysop/runtime/2b-config-baseline.txt
   mkdir -p sysop/runtime && git status --porcelain -uall > sysop/runtime/2b-baseline.txt
   ```

   > **The config capture runs FIRST, and the order is load-bearing.** `>` creates its
   > file before the command on that line runs, so writing the config baseline *after*
   > `git status` leaves it absent from the tree snapshot but present in the tree it is
   > later compared against — the third command then reports the step's own artefact as
   > an agent mutation, and the remedy below says to revert it. Capturing it first makes
   > it appear in the baseline and in the comparison alike, so it cancels out, which is
   > the same self-cancelling property the tree baseline already relies on. (The repeated
> `mkdir -p` is deliberate and idempotent — it keeps each capture line runnable on its
> own, and two shipped guards key on the tree capture carrying it.)
   >
   > **Two baselines, because a spawn writes to two places.** The tree snapshot catches an agent
   > that created or edited a file; the config snapshot catches the harness itself. Spawning with
   > `isolation: "worktree"` rewrites a **relative** `core.hooksPath` to an absolute path in the
   > repository's shared `--local` config and never restores it — measured, one spawn. Both
   > captures must run here, before the first spawn, for the same reason: a baseline taken after
   > the fact records the damage as the starting state.

   **`rm -f` first, and `-uall` on both ends.** The delete is what makes a *skipped* capture fail loudly on every close rather than only the first — without it the file persists between runs, and a later close that skips this step silently diffs against a previous close's tree. `-uall` is required because plain `--porcelain` collapses an untracked directory to a single `?? dir/` line, so an agent writing into a directory that was already untracked is invisible; the assertion below uses `-uall` too, and the two must match.

3. Spawn an Agent with:
   - `subagent_type: "general-purpose"`
   - `model: "opus"` (always — the **reasoning** role: adversarial convention review; do not omit, per `.claude/served_models.yml`)
   - `isolation: "worktree"` — give each agent its own checkout (internal tracker #234). Steps 2a–2d run in the user's **primary** worktree, which has a single `HEAD`; a full-tool agent that decides to compare two revisions will reach for `git checkout` unless something stops it, and in a real run one did, moving `HEAD` off the branch the close was working on. Step 4's HARD RULE already names this hazard but frames the actor as *external*; here it is this skill's own agents, spawned two steps earlier. (The reported run had an integration branch checked out at 2b, which this skill's step order does not produce — 4-pre cuts it two steps later — so read the incident as "off the expected branch", not as evidence about which branch that is. What the misplaced commit would have cost also depends on policy: Step 6 deletes a merged feature branch with a safe `git branch -d`, and force-deletes only the integration branch under `pr`.) Isolation is available here because these agents have **no** pre-existing worktree, so `_shared/adversarial-review.md` § *Running more than one reviewer* applies directly — its "do not use it where a worktree already exists" caveat is about `/claim-task`, `/auto-build`, `/auto-fix` and `/auto-judge`, which spawn into a worktree an earlier step created, not about this step. **Where the harness offers no isolation parameter, the prompt's do-not-mutate rule below is the portable floor** — all that is available, which is not the same as sufficient. Measured twice, on two different instruction texts: a consumer's 13-agent run had one agent create `tasks/open/<ID>.md` and edit `tasks/index.yml`, with several others leaving scratch scripts in the worktree root; and this repo's own pre-build pass, under a more emphatic read-only instruction, had an agent create a scratch file inside its worktree anyway. Both were contained only because the run passed `isolation: "worktree"`. So isolation is the structural hardening the floor does not provide, not a redundant extra on top of it — and a harness without it **must** expect a dirty tree and re-assert cleanliness rather than trust the prompt.
   - `description: "Convention check: <target>"`
   - `prompt`:

     ```
     You are the final convention gate before this branch merges to production.
     Review the diff below for violations of the project's conventions — EVERY
     section given to you below, not `## Prevention Conventions` alone.

     ## Target
     <branch name, or "unpushed main commits">

     ## Diff
     <full unified diff from the target's diff basis>
     — OR, when it exceeds step 1's 1,000-line DIFF paste threshold, the
     `--stat` summary followed by the exact retrieval command —
     (Merge-base-relative — this is what the branch ADDED, not a tip-to-tip
      comparison. Context you cannot see is context `main` already has; it is
      never a deletion this branch made. Do not report missing content as
      removed.)
     (If a diff is pasted above, it is everything you need and you do not have to
      retrieve anything. If only a `--stat` summary is above, run the retrieval
      command given with it and read the hunks before reviewing — a `--stat` line
      is a file list, not a review.)

     ## Time skew — the diff is a point in time; live state is not
     Live state may already reflect this branch's effects: its migrations may be
     applied, its scripts may have been run, its rows may be published. Before
     reporting that a claim in the diff is contradicted by something you just
     measured, check whether the diff itself is what changed the thing you
     measured. If it is, the claim is a point-in-time statement about the state
     the work was planned against, not an error. Say which side of the branch's
     effects your measurement was taken on. If you cannot tell which side, say so
     rather than reporting a violation.

     ## Project conventions
     <at or below the 10,000-character threshold in step 1: paste EVERY section
      in step 1's convention-bearing set from CLAUDE.md verbatim — each under its
      own original `## <name>` heading, including every subsection. Do not
      pre-filter, merge or rename sections or subsections: the headings are how
      the agent cites what it routed against.
      Above it, substitute this arm instead:>
     Read the file at <absolute path to the primary worktree's
     sysop/runtime/2b-conventions.md> IN FULL before reviewing. It holds the
     project's complete convention-bearing sections, copied verbatim by
     the orchestrator at spawn time — that copy is the authority you route
     against. Do NOT substitute your own worktree's CLAUDE.md: your checkout
     carries the branch's version of that file, not the orchestrator's read.
     If the file is missing or empty, STOP and report exactly that instead of
     reviewing — a review against an assumed taxonomy is worse than no review.

     ## Instructions
     For each changed file, scan EVERY section given to you above (pasted, or in
     the file this prompt pointed you at) — there is more than one, and a rule in
     any of them binds — and identify which section and subsection(s) apply,
     based on file path, language, and domain. A subsection applies when its bullets reference concepts the file
     touches — for example:
     - parsers/<format>.py → "Data integrity" + "Schema evolution"
     - mcp_server/tools/*.py → "MCP server boundaries"
     - frontend/components/*.tsx → "Frontend" / "UI components"
     - api/routes/*.py → "Backend" / "API endpoints"

     Section and subsection names vary by project — discover them from what you
     were given (pasted or in the file), don't assume a fixed taxonomy, and don't
     assume `## Prevention Conventions` is the only section present.

     For each changed file, list the subsections you routed it to (one line:
     `<file path> → <subsection names>`), then check each applicable bullet
     against the diff hunks.

     Return your findings in exactly this format:

     ROUTING:
     - <file path> → <section> › <subsection name(s)>
     (one line per changed file; name the SECTION as well as the subsection —
      more than one section was given to you and a bare subsection name does not
      say which taxonomy it came from)

     VERDICT: APPROVED
     (if no violations)

     OR

     VERDICT: BLOCKED
     Violations:
     - <Convention bullet name> (<section> › <subsection>) — <file>:<line> — <one-line explanation>
     (one line per violation)

     Be thorough. A missed convention ships a security hole or reliability bug to prod.
     The ROUTING block is required so the human reviewer can audit which subsections
     you considered for each file.

     Do NOT mutate repository state — no `git checkout`, `switch`, `reset`, `stash`,
     `merge`, `rebase`, `add`, or `commit`, and no edits to tracked files. A close is
     in flight; moving `HEAD` corrupts it. Everything you need is reachable without
     moving `HEAD`: read any revision's file content with `git show <sha>:<path>`
     and any revision's changes with `git diff <base>...<tip>`. Both read the object
     database and are unaffected by tree state.

     Do NOT create new files either — no scratch scripts, no notes, no probe files,
     not even untracked ones, anywhere in the repository. If you want to compute
     something, run it from a heredoc or write under `/tmp`. "No edits to tracked
     files" is not permission to add untracked ones: an untracked file is invisible
     to every `git diff` gate this skill runs, so it survives to the close and is
     attributed to nobody.
     ```

3b. **Spawn the security twin — same dispatch, the other map** (`Q-352`).

   **The gap this closes runs the whole length of the chain, not just this step.** `/claim-task` Step 5 has the *planner* read **both** maps into `## Constraints & Risks`; from there the security map is never read again before `main`. The plan reviewer is handed the plan and `_shared/adversarial-review.md`, which **routes** against neither map: dimension 6 checks that a *cited* convention was applied correctly, and dimension 8 checks that `## Constraints & Risks` carries per-file bullets citing both maps — that is **citation coverage**, an audit of the planner's own read, not a fresh routing of the diff. The security map is looked at here and never applied to what the change became. The executor's post-fix verification re-scans changed lines against `convention_map.md` **only** (fixed in the same phase; see `/claim-task` Step 7e). And step 3 above routes against the convention sources and not this one. So a branch touching a path the security map governs — an auth handler, an upload endpoint, a `<prompts dir>` template — reached `main` with no security-map read since the plan was written, and the plan's read was of the *intended* change, not of the diff that resulted.

   **A second agent, not a bigger prompt.** Phase 166 measured ~15% overlap across **four** lenses on the same diff, with each of the four reaching its sharpest finding alone; folding security into step 3's prompt is the cheap way to lose that, and it would also push the paste toward the threshold for no gain.

   ⚠ **What this reaches on a stock install is much less than the paragraph above implies, and it was measured.** Of the 16 sections in a fresh `--packs python` install's `.claude/security_map.md`, **11 carry placeholder globs** — `<api module>/routes/**/*.py`, `<auth module>/*.py`, `<payments service module>`, `<data pipeline>/*.py` and the rest. The concrete ones are `scripts/*.sh` and hooks, `Dockerfile`/`.dockerignore`, `.gitignore`/`.env*`, `.github/workflows/*.yml`, `.claude/skills/**/*.md` + `.claude/checks.yml`, and `pyrightconfig.json`. **So on an unlocalized install this gate spawns for infra and meta changes and skips application code** — including "an auth handler, an upload endpoint", the two examples the paragraph above names as the gap it closes. Run against a synthetic diff of `src/api/routes/upload.py`, `src/auth/login.py`, `src/models/user.py`, it reports `no security-map glob matches this diff`, which is the *"a map that matches nothing reads like a map nobody consulted"* shape `/security-audit` Step 2a-0 exists for. **This is the shipped map's localization debt, not a defect in this step** — the same debt Phase 203 measured at 30 of 36 sections binding nothing — and the twin becomes as sharp as the consumer's map is localized. **Say which it was.** When the gate skips every target and the map is unlocalized, report `security: skipped — N of M map sections still carry placeholder globs`, not a bare `no map match`: the first tells a consumer they have work to do, the second reads like a clean bill.

   **Gate — spawn only when the map's globs reach this target.** Run step 0's "searched absence" test against the security sources instead of the convention ones: read `.claude/security_map.project.md` (the consumer overlay) and the shipped `.claude/security_map.md` beneath it, and spawn only if some glob in either matches a path in this target's diff basis. The doc-and-glue majority of closes matches nothing and spawns nothing extra; report those as `security: <target> — no security-map glob matches this diff`. **A skip here is a searched absence and never an assumed one** — the same rule step 0 states, for the same reason: `/security-audit`'s own Step 2a-0 exists because a map that matches nothing reads exactly like a map nobody consulted.

   **Write-once, into its own file — and on a stock install that is the only reachable arm.** ⚠ **This step's first draft said *"paste or write-once, on step 1's threshold"* and told you to *"measure the two security sources the same way step 1 measures the convention set"* — which is prose with no command behind it: step 1's shipped measurement reads `CLAUDE.md` sections and has no analogue for a map file. **`Q-342`'s filing forbade widening a paste without measuring it, and this step introduced a new paste in the same edit without applying that discipline to itself.** Measured now: `.claude/security_map.md` on a fresh `--packs python` install is **12,828 characters**, above the 10,000 threshold — so the inline arm is unreachable on a stock install and the write-once arm is the live path. Measure it anyway rather than assuming (`wc -c .claude/security_map.md .claude/security_map.project.md`), because a consumer who trims the map can fall below. At or below 10,000 characters paste them into the prompt; above it, `rm -f sysop/runtime/2b-security.md` first, then write them verbatim to `sysop/runtime/2b-security.md` in the **primary** worktree and hand every agent that absolute path. **A separate file from `2b-conventions.md`, deliberately** — the two prompts are given to different agents and a shared file would let a stale write from either arm satisfy the other's freshness check.

   **Do NOT capture a second baseline.** Step 2's tree and config baselines were taken before the *first* spawn and cover every agent this step spawns as well. Re-capturing here would take the snapshot **after** step 3's agents have run, so a mutation one of them made would be recorded as the starting state and the assertion below would then certify the tree clean over it — the exact inversion step 2's own note warns about.

   Spawn one Agent per surviving target, with the same `subagent_type: "general-purpose"`, the same `model: "opus"` (the **reasoning** role), the same `isolation: "worktree"`, and `description: "Security check: <target>"`. The prompt is step 3's, with four substitutions and nothing else changed:

   - the opening line names the security map as the taxonomy: *"Review the diff below for violations of the project's security conventions — the OWASP-category rules in the security map."*
   - `## Project conventions` becomes `## Security map`, carrying the security sources (pasted, or the `sysop/runtime/2b-security.md` path) under the same missing-or-empty STOP rule.
   - the routing example lines become security-shaped (`api/routes/*.py → A01 Broken Access Control`, `<upload handler> → A03 Injection + A08 Data Integrity`), and the `ROUTING:` block reports `<file path> → <map section> (<OWASP categories>)`.
   - the violation line becomes `- <rule> (<map section> › <OWASP category>) — <file>:<line> — <one-line explanation>`.

   Everything else is carried verbatim, and the two that matter most are the do-not-mutate rule and the do-not-create-files rule: this agent has the same tools and the same measured failure modes as step 3's.

   **It carries the same `VERDICT: BLOCKED` authority, and that is an escalation stated rather than slipped in.** A security lens can now stop a close. The alternative — advisory only — was considered and refused: a gate that reports a routed security violation and merges anyway is the state this entry was filed about, one report louder. Step 4 already treats *any* `BLOCKED` as a stop, so no new disposition is needed; what is new is which agents can raise one.

4. Collect all verdicts, **from both fleets**. If **any** subagent returns `VERDICT: BLOCKED`, list every violation with its file:line citation and **stop** — do not proceed to Step 3 until violations are fixed or explicitly waived by the user. A target skipped at step 0 has **no verdict** — report it as `skipped (doc-only)`, never as `APPROVED`; an agent that was never spawned has approved nothing. **The same rule binds step 3b's gate**: a target with no security-map glob match has no security verdict, and reporting it as approved would claim a review that never ran.

5. **Record outcomes for Step 8.** Tally `<N checked, N skipped (doc-only)>` for the `Conventions:` line, and `<N checked, N skipped (no map match)>` for the `Security map:` line, in the final report. **Two tallies, because they answer different questions and one number cannot carry both** — a close where every target skipped the security twin and every target passed the convention check would otherwise read identically to one where both ran. Without them a skip is invisible in the artifact the human reads, the same gap Step 2d's `N doc-only` tally closes for test decisions.

> **HARD RULE — the agents' worktrees must be gone before Step 3b of the close** (that is **Step 3b of the *skill*, `## Step 3b: Prepare Worktrees for Merge`** — not step 3b of *this* step, which spawns the second fleet. An earlier draft of this clause said *"the manual-smoke gate"*, which is **Step 3c**; a disambiguation that names the wrong step is worse than none, and the rule below — the agents' worktrees must be gone — is about worktree preparation, not about smoke testing). **The assertion below covers BOTH fleets** — it enumerates whatever exists rather than counting what was spawned, so it needs no adjustment for the security twin, and it must run after step 4 has collected from both. Worktree isolation is not free of side effects: on Claude Code it materializes a **real worktree and a real branch** in this repository's shared namespace (observed shape: a worktree under `.claude/worktrees/` on a branch named `worktree-agent-<id>`). The harness removes them when an agent finishes and left its checkout unchanged — but an agent that wrote a scratch file, or a run that was interrupted, leaks both. **That collides directly with this skill**: Step 1c's `git for-each-ref refs/heads/` sweep, Step 2a's "every non-main local branch", and Step 1a's worktree classification all enumerate whatever exists, so a leaked agent branch is reviewed as though it were someone's feature work — it classifies `clean-merged`, Step 2a finds no commits, and Step 6 offers to delete it. Worse across sessions: a *concurrent* `/review-close` can reach `git worktree remove` on a checkout an agent is still running in.
>
> **It must be a delta, not an absolute cleanliness test — that is why step 2 above captures a baseline.** Nothing in this skill establishes that the primary worktree is clean before the agents run: Step 1a excludes it by construction (it skips the **primary checkout**, matched by path identity, as Step 6's `pr` re-sync note also states in its own words — until this phase both sites said *the worktree whose branch is `main`*, which is the same worktree only while the primary happens to be on `main`), and the only earlier primary-tree reads are both in **Step 1b** — one path-scoped (`git status --porcelain -- review_tasks.md`), one whole-tree but grepped down to `review_tasks_archive.md` — while **Step 1c reads no working tree at all** (`for-each-ref`, `merge-base`, `diff --name-only`). So nothing before the agents run establishes anything about the rest of the tree. A bare `git diff --quiet HEAD --` here would fire on any ordinary uncommitted work and SKIP a close that is fine — a false-FAIL on the dominant path, which is how a gate gets disabled by the first operator who hits it. The baseline is taken after Steps 1b and 1c because both deliberately create commits, so a Step-1 reading is stale by design.
>
> After step 4 collects the verdicts, assert all four are clean before continuing:
>
> ```bash
> git worktree list --porcelain | grep -F '/.claude/worktrees/' || echo "no agent worktrees"
> git for-each-ref --format='%(refname:short)' refs/heads/ | grep '^worktree-agent-' || echo "no agent branches"
> diff <(git status --porcelain -uall) sysop/runtime/2b-baseline.txt && echo "primary tree unchanged by 2b"
> diff <(git config --local --list | sort) sysop/runtime/2b-config-baseline.txt && echo "local config unchanged by 2b"
> ```
>
> **If the third or fourth command reports `No such file or directory`, that step-2 baseline was never captured — that is the loud failure, and it is not optional to fix.** Re-running the capture *now* cannot help: it would record whatever the agents did as the starting state. Inspect the tree by hand against `git log`, or re-run Step 2b from a known-clean point.
>
> **The baseline lives under `sysop/runtime/` because that directory is gitignored** (Phase 133's single runtime home; `install.sh`'s `ensure_runtime_gitignore` appends the entry when missing and runs unconditionally in both modes and on `--update`, so a consumer has it). **It is not there to stop the file reporting itself** — it cannot do that in either location, because `>` creates the file before `git status` runs, so it appears in the baseline *and* in the comparison and cancels out. The reason is downstream: an untracked artefact at a tracked path shows up in the operator's own `git status` for the rest of the close, and is reachable by a later `git add`. Steps 2a–2d run in the primary checkout by construction, so a plain relative path is correct here; there is no worktree to resolve through.
>
> **Use `status --porcelain`, not `git diff --quiet HEAD --`.** The dominant observed breach shape is a *new untracked* scratch file, and `git diff` cannot see one — untracked files are invisible to it and to the 4a-post and 4b gates alike, which is why the prompt rule above had to name file creation directly. `status --porcelain` lists them.
>
> Anything listed is a leak: remove the worktree (`git worktree remove <path>`) and delete the branch (`git branch -D <name>`) before Step 3b. A **third-command** difference is an agent that mutated the primary tree — inspect each line and revert or set it aside deliberately; do not carry it into Step 3b, where it becomes indistinguishable from the close's own work and rides Step 4c's consolidation commit under that commit's message. **Read the first two commands before acting on the third.** `.claude/worktrees/` is gitignored in Sysop's own repo but not in a consumer install, so a leaked agent worktree surfaces in the delta as well — that line is the leak the first command already named, and its remedy is `git worktree remove`, not "revert an edit". Only lines the first two commands did not account for are tree mutations. **Do not skip this because the harness usually cleans up** — "usually" is what makes the residue arrive on a later run, attached to nobody, in a step that force-deletes branches.
> **The fourth command's delta is usually not an agent — it is the harness, and its remedy is a restore rather than a revert.** Spawning with `isolation: "worktree"` converts a **relative** `core.hooksPath` to an absolute path in the repository's shared `--local` config and never puts it back. Both spellings name the same directory, so `main`'s hooks keep working and the close is not at risk — but every *worktree* created afterwards runs the **primary** checkout's hooks instead of its own branch's, which is the opposite of the property the relative form was chosen for. Restore it: `git config --local core.hooksPath <the original relative value>`, read from `sysop/runtime/2b-config-baseline.txt` rather than from memory. **Match on the lower-cased key.** `git config --list` renders it `core.hookspath`, so a grep for `core.hooksPath` finds nothing and reports clean — which is why this is a `diff` against a captured baseline and not a targeted probe. **A repo that sets no `core.hooksPath` sees no delta here**, so a clean fourth command is the ordinary result and is not evidence the check is inert.
>
>
> **If your harness offers no `isolation` parameter, the first two commands do not apply — but the third one matters MORE, not less.** With no isolation the agents run directly in this checkout, so the prompt's do-not-mutate rule is the only thing standing between a stray edit and the close, and it has now been measured failing twice. Run the baseline and the delta. (An honest limit, stated so the check is not over-trusted: a tight window still cannot distinguish an agent's edit from a human's edit made while the agents ran.)

### 2c. Unpushed Main Commits

If main is ahead of origin:
1. `git log --oneline origin/<default branch>..HEAD` — list the unpushed commits
2. Review each commit's changes: `git show --stat <hash>` for each
3. Verify the changes look intentional and complete (no half-finished work, no debug code left in)
4. Check that documentation is accounted for: either `docs:` prefixed commits exist (legacy) or `sysop/runtime/pending-docs/*.md` files are present (current workflow)

### 2d. Test-Decision Verification (verify the record — Phase 59, C1)

Every task claimed through `/claim-task` records a **test decision** in its body at plan time (Phase 58b): either `test <X> proves <Y>` (the regression test that pins the changed behavior) or `no test because <Z>` (the reviewable rationale for adding none). See `tasks/schema.md` § Test decision. This step **verifies that record against what the branch actually delivers**, and since Phase 234 it is the *only* thing that does: `validate_tasks.py` carried a warn-only Invariant 13 on the same fact until then, but it read the body off the working tree while this record lives on the branch, so it warned on every claimed task on every run and told you nothing. Reading the right revision is what makes this gate real. It does **not** re-judge whether a test *should* exist; that judgment is the adversarial plan reviewer's "Missing invariant tests" dimension (`_shared/adversarial-review.md` finding 7), applied at plan time. Verify the record, don't re-judge.

> **The premise sentence above is accurate about `/claim-task` and it is not the gate's reach.** Every task claimed through that skill records a test decision; **not every task on a branch under review was claimed through it.** Grepping the shipped skills: `/auto-fix` writes the record **0** times, `/auto-judge` **0**, `/auto-build` **1** — an incidental aside about clean sessions, not a write — and manual work on a hand-cut branch writes none. This step nevertheless reads the record for each task ID the branch claims, whatever produced it, so a task that was never owed a record and a task whose record is genuinely missing used to arrive at the same prompt with the same three answers. `Waive` therefore meant two different things and the Step 8 tally conflated them: the one that should be free was priced like the one that should be expensive. The fourth disposition below separates them. **The fix is the disposition, not a rewording of the premise** — narrowing the population instead would stop asking about tasks that genuinely should have carried a record, which is the gate going quiet rather than getting honest.

This is the sibling of Step 3c's manual-smoke gate — a per-task body convention, enforced here and nowhere else since Phase 234 — and reuses the same shape: a deterministic classification (like Step 1a's worktree verdict) plus an `AskUserQuestion` halt on mismatch (like Step 3c).

For each **approved** feature branch (Step 2a verdict), for each task ID it claims (path resolved exactly as in Step 2a step 3 — `tasks/index.yml`'s `body:` per claimed ID):

> **Read the record at the branch tip — not out of the working tree.** `/claim-task` *decides* the test decision at plan time, but the **executor writes it into the body during implementation, inside the worktree** (`claim-task/SKILL.md` Step 7e, Sequence item 3), so the section is committed on the feature branch and nowhere else. Step 2d runs at Step 2; nothing merges until Step 3b/4a. `HEAD` is still `main`, so the working tree's copy of the body is whatever `main` has — and for a task claimed this cycle that copy carries **no test-decision heading at all**, because every shipped body-author is told not to write one (`intake/SKILL.md:111`, `add-task/SKILL.md:63`, `onboard/SKILL.md:95`; the schema's placeholder is a template, not something a real body normally holds). Reading *that* copy therefore classifies the record `missing` for every task on every branch on every run, and each `missing` fires the halt below. **Nothing spares one** — step 0's doc-only skip does not, because a `missing` classification is not the `no-test` its second conjunct requires, so a doc-only branch halts here too. A gate that only ever reports the state of a revision it is not gating. Resolve the *path* from `main`'s `tasks/index.yml` — correct, because a claim does not move the body and Step 4c's archive move runs after this step — and read the *content* from the revision under review:
>
> ```bash
> # `body:` is canonically relative to `tasks/` — `open/<TASK-ID>.md`, NOT
> # `tasks/open/<TASK-ID>.md` (`tasks/schema.md` § body) — while `git show <rev>:<path>`
> # takes a REPO-ROOT-relative path. Resolve with the same two-branch rule all three
> # shipped readers use (validate_tasks.py, next_task.py, scope_overlap.py): prepend
> # `tasks/` unless the recorded value already starts with it. Quote the operand —
> # unquoted, `<…>` is a redirection to bash, not a placeholder (Step 6 states the same
> # rule for `git branch -D`), and an unquoted path containing a space truncates at it.
> git show "<branch>:tasks/<body as recorded>"    # canonical:   body: open/<TASK-ID>.md
> git show "<branch>:<body as recorded>"          # back-compat: body: tasks/open/<TASK-ID>.md
> ```
>
> **Getting that prefix wrong is not a cosmetic slip** — it produces `fatal: path … does not exist`, which is exactly the `unreadable` signature below, so a mis-resolved path halts the close wearing a diagnosis that blames the branch. Check the recorded `body:` value before concluding anything from **that** fatal — and read the signature first, because the advice is wrong for the others: `ambiguous argument` and `invalid object name` **cannot** be produced by a prefix mistake, so re-checking `body:` there sends you looking in the one place the fault is not. This is the object-database read Step 2b's prompt already prescribes, and it is the same revision `git diff <default branch>...<branch>` reports — both halves of this gate must come from one revision, or the comparison is between two different trees. `WORKFLOW_GUIDE.md` § Merge Process already says to read "**the branch's** `## Test decision`" back against the diff, so the branch-tip read restores the spec rather than inventing a rule; `WORKFLOW.md` § 2.8 ("each approved branch's task body") scopes *whose* body rather than *which revision*, so it is consistent with that reading without compelling it.

**0. Per-branch doc-only skip.** If this branch's diff (`git diff <default branch>...<branch>` — three dots, per Step 2a's note) touches no code files (the same code-file set Step 3 uses — `.py` / `.ts` / `.tsx` / `.js` / `.jsx` / `.sql` / `.sh` / `.kt` / `.swift` / `.go` / `.rs`), **and** *that task's* recorded decision is a `no-test`, skip verification for it with a one-line note (`2d: <branch>/<task id> — doc-only diff, no-test record`). **The two conjuncts have different granularity, and the skip takes the narrower one.** The diff test is per *branch*; the record is per *task*, and this gate iterates the tasks a branch claims. So a doc-only branch claiming two tasks skips only the task whose record is a `no-test` — the other is verified, which is the point: a record naming a test must not be silenced because a sibling task's record said none was needed. **Resolve step 1's read before deciding this** — the second conjunct is a fact about the record, so the classification has to exist before the skip can be evaluated, and reading it is one `git show` this gate runs either way. What this skip saves is step 2's verification, not the read; a step 0 that fired before the record was classified would be deciding on the extension test alone, which is the defect. An `unreadable` or `missing` classification is **not** a `no-test` and does not earn the skip — those have their own arms below. **A record that names a test is verified whatever the extensions say** — checking that the named test is present costs one read and is exactly as meaningful on a semgrep rule or a `checks.yml` entry as on a `.py` file. The extension test cannot carry this skip alone, because it calls semgrep rules, `checks.yml`, CI workflows and served-model config documentation, and a branch changes behaviour through any of them; Sysop's own `coverage-*` `blocking: true` flip (Phase 61b) had that shape. Step 2b's skip carries a second conjunct too — a different predicate (no rule in `## Prevention Conventions`, in a sibling CLAUDE.md section, or in either convention map governs the touched types), the same reason: the extension test is evidence about file names, and neither gate is about file names.

**1. Read the record.** Read the body **at the branch tip** (`git show "<branch>:<repo-root-relative body path>"`, resolved and quoted per the note above — never the working-tree copy) and find the section under a heading whose text matches `test\s+decision` (case-insensitive — `## Test decision`, `### Test Decision` both match; the pattern is defined in `tasks/schema.md` § Test decision, which is now its only home). Classify it:

- **`test-proves`** — the section names a test (the `test <X> proves <Y>` shape).
- **`no-test`** — the section states `no test because <Z>`.
- **`missing`** — no test-decision heading **at the branch tip**, or the section still holds the schema template placeholder (`<recorded at /claim-task plan time …>`).
- **`unreadable`** — `git show` did not hand you the file at the branch tip. **Four distinct outcomes land here, and the definition used to name only the first, so the other three routed nowhere at all** — each verified by execution against git 2.50.1:
  - `fatal: path '…' does not exist in '…'` — the rev resolved, the path did not. **Before believing it, re-check the `tasks/` prefix rule above — a mis-resolved path produces this identical fatal, and that is the likelier cause.** Genuinely reachable when the claim reused a pre-existing branch cut before the body file was written, since `claim_task.sh` reuses an existing branch rather than refusing.
  - `fatal: ambiguous argument '…': unknown revision or path not in the working tree.` — the **operand itself** was mangled, so neither half resolved. The `tasks/` prefix rule **cannot** produce this signature, so re-checking the prefix here is a dead end; check what mangled the operand instead. The known cause is a zsh history-modifier expansion: unbraced `"$b:tasks/…"` under zsh applies `:t` and eats the leading `t`, turning the path into `asks/…` — measured, and the shipped placeholders are braced/quoted literals precisely so this cannot arise from the skill's own text.
  - `fatal: invalid object name '…'.` — the **path** resolved but the rev did not exist. A stale or misspelled branch name, not a missing body.
  - **Exit `0` with a commit diff instead of a file — the one that is not a fatal, and the only one that can fabricate a verdict.** An operand that lost its `<rev>:` makes `git show <path>` mean `git show HEAD -- <path>`: it does **not** walk history — that correction is the round's — it shows **`HEAD`**, and exits **0** either way. Two sub-cases, and the quiet one is likelier: if `HEAD` happens to touch that path you get a commit diff whose `+` lines can contain `## Test decision` and the prose beneath it; if it does not, you get **exit 0 and no output at all**, which reads as an empty body rather than as a failed read. A reader scanning that output for the record finds one — **from the wrong revision, on `main`, not on the branch.** So do not treat exit 0 as proof you read the body: **confirm the operand you sent contained a literal `:`, and that the output is file content rather than a diff** (a `commit <sha>` header line, or lines beginning `+`/`-`/`@@`, means you read a commit). This is the fabricated-finding case the paragraph below forbids, arriving through the one door that looks like success.

  **None of the four is `missing`:** nothing has been asserted about the record either way, and reporting it as `missing` would put a fabricated finding in front of the human. Surface the branch, the path you resolved, the revision you read, and **which of the four outcomes you got** — they have different causes and the disposition used to collapse them.

**2. Verify the record against the branch diff:**

- **`test-proves` → "plan said test X — is it here?"** Confirm the diff adds or modifies a test matching X — a changed file on the project's test path (`tests/`, `*_test.py`, `*.test.ts`, `*.spec.ts`, or the project's documented test location) and, when X names a specific test/function, that name appearing in the diff. If the diff touches **no** test file at all, the record claims a test that wasn't delivered → **discrepancy**. (Record-vs-reality only: a test that is present but weak is out of scope here — that's the reviewer's coverage judgment, not this gate's.)
- **`no-test` → "plan said no-test-because-Z — does Z still hold?"** Re-read `Z` against the diff. `Z` **holds** when the diff's character still matches the stated rationale (pure rename/move, config-only, docs-only, covered by an existing named test, `manual_smoke:`-only) — **with the caveat that "config-only" and "docs-only" name a file's extension, not its consequence.** A semgrep rule, a `checks.yml` entry, a CI workflow, a lockfile pin and a lint config are all config, and each is behaviour a project checks; where the diff changes one of those, `Z` holds only if the rationale anticipated *that*, not merely that no `.py` file moved. `Z` is **stale** when the diff now carries behavior changes the rationale didn't anticipate (e.g. `Z` said "pure rename" but the diff edits logic) → **discrepancy**. This carries inherent judgment residue — acknowledged and bounded: you are matching the recorded rationale to the diff, **not** forming a fresh opinion that a test ought to exist.
- **`missing` → record absent.** This is the **first** notice, not a second one: nothing upstream warns on it any more (Phase 234 retired the validator's Invariant 13, which could not see this record at all from `main`). Treat as a discrepancy to surface.

**2‑pre. The ownership probe — before asking about a `missing` record, establish whether one was owed.** Numbered out of the list on purpose: this skill already ships a `### 2b. Prevention Convention Check` as a sibling of `### 2d`, so a sub-step called *2b* would send a reader to the wrong section. It is **one bit, per task ID, from the claim lock**:

```bash
# For a ROADMAP task id — which is what this gate iterates — `claim_task.sh` writes the
# lock, and an ordinary close removes it at Step 4c. Both halves need scoping and neither
# is a "the only": `batch_work.sh` writes `BATCH-<N>.lock` on the batch path, and
# `claim_task.sh --release`, `batch_work.sh --release` and `close_batch.sh` all remove
# locks too. `--release` is exactly why absence stays three-valued below rather than
# becoming proof — a released task legitimately has no lock and may still have been owed
# a record. Keyed by TASK ID, not by branch, so this needs none of Step 2e's branch->claim
# resolution and duplicates none of its parsing rules.
# No `cd` in this command, deliberately. `_shared/permission-guard.md` records that even
# read-only commands prompt "when `cd` into a different directory is compounded with them",
# and this is the one standalone one-liner the step asks an operator to run — a gate that
# prompts on the dominant path is a gate that gets switched off. `--git-common-dir` prints
# `.git` (or `../../.git` from a subdirectory, or an absolute path from a linked worktree)
# and the filesystem resolves the `..` in the middle, so no resolution step is needed.
ls "$(git rev-parse --git-common-dir)/../sysop/runtime/locks/<TASK_ID>.lock" >/dev/null 2>&1 \
  && echo "OWED — claimed through /claim-task" \
  || echo "CANNOT TELL — no lock on disk"
```

- **Lock present → the record was owed.** Do **not** offer *record not owed* for this task. `/claim-task` Step 7e writes the record and re-reads its own write in the worktree before committing, and the orchestrator then re-checks the same fact **at the branch tip** at Step 8 — the revision this gate reads. (Two different reads: 7e greps the worktree copy, Step 8 reads the branch. Attributing the branch-tip read to 7e, as the first draft of this sentence did, would tell a reader the worktree grep already proves what only the Step 8 arm proves.) So a missing record here is a real miss, not an unowed one, and waiving it as *not owed* would launder exactly the failure that read-back exists to surface.
- **Lock absent → cannot tell, and that is the honest answer.** `sysop/runtime/` is gitignored, so a fresh clone, a rebuilt worktree or a `--resume` after a break all legitimately carry nothing; a non-Claude harness never wrote one; and the branch may not come from `/claim-task` at all. Offer all four options and let the human decide. **Never render absence as "the orchestrator did not run"** — this is the same three-valued rule Step 2e states in full, for the same reason.

> **Why the lock and not the run directory, stated as the argument it actually is.** A *retrospective* survey cannot settle this, and an earlier version of this note claimed it had. Over 476 archived tasks in a live consumer, run-directory presence looks like a strong signal (29/29 carried the record against a 15% base rate); it is confounded (all 29 closed in one month whose base rate was already 71%) and it is useless retrospectively, because every one of the 378 tasks missing a record is in the run-directory-absent bucket. **But the same test is worse for the lock, not better**: Step 4c removes both, and among those 476 tasks **0 locks survive against 29 run directories**. So the corpus disqualifies run directories as a *retrospective* proxy — which is all `Q-368`'s retraction ever claimed — and says nothing about either artifact at gate time, where neither has been reaped yet.
>
> The real reason is **structural, and it is about the direction this signal is used in.** A lock exists for *every* `claim_task.sh` claim; a run directory exists only when the Step 7 orchestrator actually ran. The lock is therefore the **broader** signal — and this step uses it only to **withhold** the *record not owed* escape. For a withholding use, over-inclusion costs a waiver and under-inclusion lets a genuine miss be dismissed as unowed, so the broader artifact is the safe one. It is also written by a **script** rather than by an agent, so it cannot be skipped by a run that failed to follow the orchestration — which is precisely the failure `Q-369` documents.

**3. On a clean match, pass silently** (carry a `verified` note for Step 8). **On any discrepancy, missing record, or unreadable body, halt and ask** via `AskUserQuestion` (one task at a time, mirroring Step 3c). Present the recorded decision text verbatim, the task ID, **the revision you read it from**, what the diff shows, and **the ownership-probe verdict**. Options (single-select) — three always, plus a fourth only when the ownership probe said `CANNOT TELL`:

- **"Record holds — proceed"** — the human confirms the record is accurate or the rationale still applies; the branch stays approved.
- **"Hold for fix — don't merge this run"** — demote this branch from **approved** to **rejected** for this run, with the reason `test-decision record needs fixing — <detail>`. Downstream steps already handle a rejected branch correctly with no special-casing: Step 3b/Step 4 skip it (only approved branches merge), Step 6 leaves its worktree, lock, and branch intact for follow-up, and Step 8 reports it under "Remaining" with the reason. The test can then be added or the record corrected before a later `/review-close`.
- **"Waive — proceed with noted waiver"** — the branch stays approved; record a waiver (task ID + decision text) for Step 8. Use for accepted judgment calls (e.g. a stale-looking `Z` the human confirms is fine). **A waiver means the record was owed and is being let through anyway** — if it was never owed, the next option is the correct one and this one overstates what happened.
- **"Record not owed — no orchestrated plan ran"** — *offered only when the ownership probe said `CANNOT TELL`, and only on a `missing` record.* The branch stays approved and **nothing is waived**, because there was nothing to waive: the work came from `/auto-fix`, `/auto-judge`, a hand-cut branch or a manual edit, none of which write this record. Tally it separately (below). This is deliberately **not** a quieter waiver — it is the disposition that makes the tally mean something, so do not reach for it when the ownership probe said `OWED`, or when the record is merely *stale* rather than absent.

Waivers, "record holds" and "record not owed" do not block. Only "hold for fix" changes the verdict, and it does so by reusing the existing **reject** disposition — no edits to Steps 3b/4/6 are needed.

**4. Record outcomes for Step 8.** Tally per task: `verified`, `waived`, `not owed`, `held for fix` (now rejected), `unreadable`, or `skipped (doc-only)`. This drives the "Test decisions" line in the final report. **`waived` and `not owed` are counted separately and must not be merged back into one number** — that conflation is the whole reason the fourth disposition exists, and a report that sums them restores it.

If the approved-branch set is empty (only unpushed main commits this cycle), Step 2d is a no-op — unpushed main commits don't carry `/claim-task` test-decision records. Skip cleanly.

> **For new projects:** the test decision is decided by `/claim-task`'s planner at Step 7a and written into the task body by the Step 7e executor during implementation — or, on the plan-only path, by Step 7f, which has no executor to do it later (`tasks/schema.md` § Test decision). This gate reads it back — keep the `Z` in a `no test because Z` rationale concrete so "does Z still hold?" stays answerable.

### 2e. Claim-Artifact Report (report, never reject — Phase 237, part B leg 1)

`/claim-task` Step 7 is an orchestrator: it spawns a planner, an independent reviewer, and an executor, and each stage leaves a file behind. This step **reports which of those files exist for each branch under review**. It is the close-path half of a pair: `/sitrep`'s `_claim_stall` probe (Phase 237, part B leg 2) is the other. They share the report-unknown rule below, not their artifact set — this step reads five run files plus the hook envelopes, the probe reads park markers plus `classification.md` and `outcome.md`.

**It never changes a branch's disposition.** No verdict moves, no branch is rejected, nothing halts. That is a decision with an argument, not caution: a *rejecting* gate must know whether it applies, and getting that wrong is a false FAIL on work already done — which is exactly how the Phase-155 attempt died (a predicate inert on the review-batch claims it was reported for, a false FAIL on the dominant path, and 41 of 53 guard mutations surviving). A *reporting* step that mis-resolves prints "no artifacts found" beside a branch that has them: wrong, visible, and self-correcting. Sysop's settled pattern is **surface the ambiguous class, block the unambiguous one** (Phase 135 blocks `failed`, Phase 143 exits non-zero on a demonstrably-abandoned round, Phase 149 purely surfaces), and artifact absence is squarely the ambiguous class — see the rule below for why.

> **Report unknown. Never report "did not run".** Absence of these files is **not** evidence that the pipeline was skipped, and a report that says otherwise accuses honest consumers:
>
> - `sysop/runtime/` is **gitignored**, so a fresh clone, a rebuilt worktree and a `--resume` after an overnight break all legitimately carry nothing.
> - The envelope is written by the `SubagentStop` hook, which is **Claude Code only** — a Codex or other-harness consumer never produces one, however correctly the claim ran.
> - A branch may not come from `/claim-task` at all (a hotfix, an `--adopt`, a hand-cut branch).
>
> So render three-valued — **present** / **absent** / **cannot tell** — and when the claim directory itself is missing, say *no artifact directory on disk* rather than anything about what ran. The unforgeability of this artifact set is a property of *a Claude Code run inspected before its runtime dir is gone*, not of the design.

**Resolve the branch to a claim id from the lock, not from the branch name.** Branch names are not reversible: Step 3 of `/claim-task` auto-generates one from the task id, but `--branch <name>` and `tasks/index.yml`'s `branch:` field both override it, and a review batch's branch comes from `review_tasks.md`. The lock file is the reverse map that exists — it records `branch:` against its own `task_id` — and locks are still on disk at Step 2 (Step 4c removes them). A branch with no matching lock is reported as such; it is not an error.

Run this once for the whole close, passing every branch Step 2a classified — **approved and rejected alike**, since a report changes nothing and a rejected branch's artifacts are exactly what a human wants when deciding what to do with it.

```bash
# `python3` command word + positional args — a single simple command, so `Bash(python3 -:*)`
# matches. Substitute each branch name literally and QUOTED: unquoted, `<…>` is a
# redirection to bash rather than a placeholder, and the script refuses an
# unsubstituted one rather than reporting on a claim named `<branch>`.
python3 - <<'PY' "<branch 1>" "<branch 2>" "<...one argument per branch under review...>"
import json, re, subprocess, sys
from pathlib import Path

branches = [b for b in sys.argv[1:] if b.strip()]
if any("<" in b for b in branches):
    print("ERROR: placeholder not substituted: {!r}".format(branches), file=sys.stderr)
    sys.exit(2)
if not branches:
    print("2e: no branches under review — nothing to report.")
    sys.exit(0)

common = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                        capture_output=True, text=True, check=True).stdout.strip()
main_root = Path(common).resolve().parent
runtime = main_root / "sysop" / "runtime"

# branch -> [claim ids]. FIRST `branch:` line per lock wins, matching
# `claim_task.sh`'s `awk '/^branch:/{...; exit}'` — a lock's free-text `notes:`
# tail can carry a column-0 `branch:` line, and two readers of that field
# disagreeing about which one counts is worse than either rule alone.
# Ambiguity is REPORTED, not resolved: `/sitrep` has no duplicate-lock-branch
# check (its duplicate check is on batch NUMBERS), so nothing else surfaces it.
by_branch = {}
locks_dir = runtime / "locks"
if locks_dir.is_dir():
    for lf in sorted(locks_dir.glob("*.lock")):
        try:
            lines = lf.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        fields = {}
        for line in lines:
            if not line or line[0].isspace() or line.startswith(("-", "#")):
                continue
            k, sep, v = line.partition(":")
            if sep and k.strip() not in fields:
                fields[k.strip()] = v.strip()
        if fields.get("branch"):
            by_branch.setdefault(fields["branch"], []).append(
                fields.get("task_id") or lf.stem)

# The five files Step 7-pre's own resume router treats as authoritative; with
# the hook envelope(s) that is the six-artifact set. The spec's Q1 names four —
# it predates Part A, which shipped `planner-integrity.md` and `outcome.md` as
# first-class routing artifacts, so a four-item report is blind to the two files
# answering "was the plan re-gated?" and "did the executor already run?".
NAMES = ["plan.md", "planner-integrity.md", "review.md",
         "classification.md", "outcome.md"]


def verdict_of(path):
    """Parse the FENCED body. Step 7c writes `json.dumps(...)` inside a yaml
    fence, so the line on disk is `  "verdict": "PROCEED"` — a scan for a line
    beginning `verdict:` matches nothing the shipped writer produces."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "unreadable"
    # `\x60{3}` rather than a literal fence: this block lives INSIDE a markdown
    # fence, and three literal backticks here close it early — which silently
    # reshuffles every later fence pair in the file. A shipped guard
    # (`test_flag_contract.py`) caught exactly that, by then reading unrelated
    # prose as a command block.
    m = re.search(r"\x60{3}(?:yaml|json)?[^\n]*\n(.*?)\n\x60{3}", text, re.S)
    if m:
        try:
            doc = json.loads(m.group(1))
            if isinstance(doc, dict) and isinstance(doc.get("verdict"), str):
                return doc["verdict"].strip()
        except Exception:
            pass
    m = re.search(r'^[\s>*_-]*"?verdict"?:[\s*_"]*([A-Za-z_]+)',
                  text, re.MULTILINE | re.IGNORECASE)
    return m.group(1) if m else ""


for branch in branches:
    ids = by_branch.get(branch) or []
    if not ids:
        print("  {}: no lock names this branch — claim id unknown, "
              "so no artifacts were looked for".format(branch))
        continue
    if len(ids) > 1:
        print("  {}: AMBIGUOUS — {} locks name this branch ({}). Reporting none; "
              "reconcile the locks first.".format(branch, len(ids), ", ".join(ids)))
        continue
    claim_id = ids[0]
    claim_root = runtime / "claim" / claim_id
    if not claim_root.is_dir():
        print("  {} ({}): no artifact directory on disk — UNKNOWN, not "
              "'did not run' (sysop/runtime/ is gitignored)".format(branch, claim_id))
        continue
    # Per-branch containment for every filesystem call below. One unreadable
    # claim directory must not abort the whole report and take the healthy
    # branches' rows with it — that is the Phase-219 shape, and this step's own
    # three-valued rule makes an unreadable thing "cannot tell", not a crash.
    try:
        runs = sorted((q for q in claim_root.iterdir() if q.is_dir()), reverse=True)
    except OSError as exc:
        print("  {} ({}): claim directory unreadable ({}) — UNKNOWN"
              .format(branch, claim_id, exc.__class__.__name__))
        continue
    if not runs:
        print("  {} ({}): claim directory exists but holds no run — UNKNOWN"
              .format(branch, claim_id))
        continue
    run = runs[0]
    # Containment. This step only READS, so a symlinked run directory risks
    # disclosure rather than damage — but reporting an arbitrary directory's
    # contents as this claim's artifacts is a false report either way.
    try:
        if not run.resolve().is_relative_to(claim_root.resolve()):
            print("  {} ({}): newest run {} resolves outside the claim root — "
                  "skipped, not reported".format(branch, claim_id, run.name))
            continue
    except (OSError, ValueError):
        print("  {} ({}): run path could not be resolved — UNKNOWN"
              .format(branch, claim_id))
        continue
    extra = " (+{} older run(s))".format(len(runs) - 1) if len(runs) > 1 else ""
    try:
        present = [n for n in NAMES if (run / n).is_file()]
    except OSError:
        print("  {} ({}) run {}: artifacts unreadable — UNKNOWN"
              .format(branch, claim_id, run.name))
        continue
    absent = [n for n in NAMES if n not in present]
    # Both shapes Step 7-pre globs: the phased `<CLAIM_ID>.<phase>.json` the
    # build emits, and the bare `<CLAIM_ID>.json` that predates `PHASE:`.
    env_dir = runtime / "subagent-envelopes"
    try:
        envs = sorted(set(env_dir.glob(claim_id + ".*.json"))
                      | set(env_dir.glob(claim_id + ".json"))) if env_dir.is_dir() else []
        # An envelope the hook wrote but could not key lands under a different
        # name. Count those, so absence is never attributed to "the harness does
        # not write these" when one WAS written and simply failed to key.
        stray = len([q for q in env_dir.glob("*.json")
                     if q not in envs]) if env_dir.is_dir() else 0
    except OSError:
        envs, stray = [], 0
    print("  {} ({}) run {}{}".format(branch, claim_id, run.name, extra))
    print("      present: " + (", ".join(present) or "none"))
    print("      absent:  " + (", ".join(absent) or "none"))
    if envs:
        print("      hook envelopes: " + ", ".join(q.name for q in envs))
    elif stray:
        print("      hook envelopes: none matched this claim id ({} other envelope "
              "file(s) in the mailbox — check whether one failed to key)".format(stray))
    else:
        print("      hook envelopes: none on disk — Claude Code only, and transient")
    cls = run / "classification.md"
    print("      verdict: " + (verdict_of(cls) if cls.is_file()
                               else "no classification.md in this run"))
PY
```

**Read the block into the Step 8 report — the `Orchestrator artifacts:` line, not `Claim artifacts:`, which is Step 4c's removal tally — and continue.** Nothing here gates anything: a branch with every artifact absent proceeds exactly as it would have, and a branch with every artifact present is not thereby approved. If a consumer ever reports a run where the artifacts were absent, the report was ignored, and the branch merged anyway, *that* is the evidence for revisiting a blocking form — and it should be revisited here, never at `/document-work`, whose Phase-155 hard fail punished at the worst possible moment, after implementation.

## Step 3: Run Verification

**This is the pre-merge pass, and it can only verify the tree it runs on.** `HEAD` is still `main` here — Step 3b has not removed a worktree and Step 4a has not merged anything — so no approved branch's files are in this working tree and its new tests do not exist yet. What this pass verifies is *this* tree: `origin/<default branch>` plus whatever local-only commits `main` already carries. It is a fail-fast on the base, and it is the last point where stopping is free. **It is not a verdict on the work, and nothing here may be reported as having verified a branch** — that verdict is `4a-post`, which re-runs the same resolved list on the merge target once the branches are merged.

**Each pass scopes itself to its own tree, with one command.** Item 3's surface gate reads the list this prints at **both** passes; item 4's doc-only skip reads it at **this pass only**, because `4a-post` does not inherit it:

```bash
# The changed-file list for THIS pass, read off stdout. Three dots, always — two would
# render everything the base gained since a branch was cut as though the branch deleted
# it (the Step 2a note). Run from the repo root.
git rev-parse --verify --quiet origin/<default branch> >/dev/null \
  && git diff --name-only origin/<default branch>...HEAD \
  || echo "NO_ORIGIN_MAIN"
```

On this pass `HEAD` is `main`, so the list is main's local-only commits — the `open → in_progress` claim flips and any Step 1b `review_tasks.md` save — and that population is exactly what this pass is entitled to verify. At `4a-post` the identical command runs on the merge target and returns the whole assembled diff. **If it prints `NO_ORIGIN_MAIN`** (no `origin`, or a remote whose default branch is not `main` — verified: the diff alone exits 128 with `fatal: ambiguous argument`), there is no changed-file list: **gate nothing and skip nothing — run the full resolved list.** A scope you could not compute must never silently narrow the gate.

**An empty list is a real outcome here, and it is the one to report rather than pass over.** On a `main` already level with `origin/<default branch>` this command prints nothing, so a `### Ratchet` snippet filtering it short-circuits on every filter and the pass reports green having executed nothing at all. That is *correct* — there is nothing on this tree the base has not already seen — but "green" and "ran nothing" must not read the same, which is why Step 8's `Verification:` line carries the reason, not just the verdict.

Now discover the project's verification commands. Resolve in this order — stop at the first source that produces a command list:

1. **`<project>/CLAUDE.md` § "Pre-merge verification"** (preferred — the project owns its command list). Two shapes are supported:
   - **Split sub-headings (recommended).** If the section uses `### Always` and/or `### Ratchet (changed files only)` sub-headings, run them in that order:
     - **`### Always`** — full-tree commands run unconditionally (build, full test suite, project-level smoke tests). Bullet list; one command per bullet. **"Unconditionally" is a promise about `4a-post`**, the gate that speaks for the work: no diff-shape heuristic skips a list the consumer declared. *This* pass does drop it on the dominant cycle (item 4 below), because its green is not a verdict — and that asymmetry is the only thing standing between the word "always" and a section the dominant cycle never runs.
     - **`### Ratchet (changed files only)`** — project-supplied shell snippets in a single bash code block. Each snippet is expected to filter `git diff --name-only origin/<default branch>...HEAD` to its file-type of interest and invoke lint/typecheck against only the changed files. Run the block as-is from the repo root. A snippet whose filtered changed-file list is empty short-circuits and passes — that's project-side logic, not a Sysop rule. Treat the snippets as project-trusted input — they run with full agent shell privileges. If you didn't write them yourself, read the block before running it.
   - **Flat list (backward compatible).** If neither sub-heading exists, treat all bullets under `## Pre-merge verification` as the `### Always` list and skip the ratchet step.
2. **`package.json` `scripts.verify`** (if `package.json` is at the repo root or `<frontend>/`). If at repo root, run `npm run verify`. If at `<frontend>/`, run `(cd <frontend> && npm run verify)` from the repo root.
3. **Auto-detect from common surfaces** — each command gated on its own surface appearing in this pass's changed-file list (internal tracker #206). A surface being *present* says the project has one; it does not say this run *touched* one, and running a full frontend build for a diff of Python scripts is the cost that makes skipping tempting — and the skip is then a judgement this step never authorized, so it gets made silently.
   - `frontend/` exists with `package.json` → `cd frontend && npm run build && npm run test` — **only if** the changed-file list contains a path under `frontend/`
   - `pyproject.toml` exists with `pytest` declared in `[project.optional-dependencies]` (any extra) → `python -m pytest tests/` — **only if** the list contains a Python file
   - `Cargo.toml` exists → `cargo test --release` — **only if** the list contains a Rust file or `Cargo.toml`
   - Other detectable surfaces → run the platform-native test/build command, under the same rule: only if the list contains a file that surface owns.

   **A surface absent from the changed-file list is `skipped`, not `failed`.** Record it on Step 8's `Verification:` line (`skipped frontend — not in this run's changed files`). That is what makes the skip *authorized* rather than improvised. It does not license the inverse: do not decide by hand to skip a surface the list does touch.

   **Then report every changed code file that no detected surface claimed** — Step 8's `Unverified surfaces:` line. Surface-gating narrows the gate, so what it cannot account for has to become visible rather than disappear; a `.sql` migration or a `.go` service in a repo whose only detected surfaces are `frontend/` and `pytest` is verified by nothing, and that was true before this gate existed too. The fix is consumer-side and is one heading away: a `## Pre-merge verification` section is **never** surface-gated, because there the consumer said what to run.
4. **If the diff is doc-only** (no `.py` / `.ts` / `.tsx` / `.js` / `.jsx` / `.sql` / `.sh` / `.kt` / `.swift` / `.go` / `.rs` files changed — only `.md` / `.txt` / `.yaml` config / etc.): skip verification with a one-line note (`Step 3: skipped — diff is doc-only`). **"The diff" is this pass's changed-file list, never the run's.** The two passes compute it the same way on different trees, so each decides its own skip: `4a-post` is never skipped because Step 3 was, and Step 3's skip is not evidence about any branch. On the common cycle this pass *does* skip — a claim flip and a `review_tasks.md` save are the whole of main's local-only diff — which is why the pre-merge pass costs almost nothing and why nothing may be concluded from its green. Step 4 (push) still runs.

   **The licence for this skip is the pass, not the diff — and that distinction is the whole of it.** Step 3 is a fail-fast on the base whose green this step's opening already forbids reading as a verdict, so skipping it forfeits only the fail-fast. What does *not* license it is the idea that a doc-only diff is harmless. The extension test above classifies as documentation a great many files a build actually consumes — `pyproject.toml`, `tsconfig.json`, `.eslintrc.json`, `ruff.toml`, `package.json` and its lockfile, CI workflows, semgrep rules, `checks.yml` (not *every* such file: a `vite.config.ts` or `.eslintrc.js` is `.ts`/`.js` and counts as code) — so a diff that is doc-only by this test can regress lint, typecheck and build *directly*, and `### Always` is a full test suite, which can assert on prose as readily as on code. **`4a-post` therefore does not inherit this skip**; see that step.

   **It also never cancels a command item 3 armed.** Item 3 gates each auto-detected command on its own surface appearing in this list, and three of its four bullets can fire on a diff this test calls doc-only: a path under `frontend/` (`package.json`, `tsconfig.json`, a stylesheet), a `Cargo.toml` — which item 3 names *by name* while `.toml` is absent from the code set above — or any other surface's non-code manifest (`go.mod`, `Dockerfile`, `pubspec.yaml`). Where item 3 armed a command, run it. Item 4 decides only what item 3 left unarmed, plus a consumer-declared list under items 1–2. `### Ratchet` needs no decision either way: its snippets filter the changed-file list themselves and short-circuit when the filter comes back empty, which is project-side logic rather than a Sysop skip.
5. **If none of the above fire and the diff touches code**: stop and ask the user what to run. Do not invent commands. Do not run `pip install` or any state-mutating command during verification — verification is read-only.

**The item-5 stop is about the run, not about this pass — resolve before you skip.** Item 4 decides whether to *run* the list; it does not decide whether the list had to exist. Taken in bare sequence the two collide on the dominant path: this pass's diff is doc-only, item 4 fires, and item 5 is never reached — so a consumer with no `## Pre-merge verification`, no `scripts.verify` and no detectable surface sails through Step 3 and hits "stop and ask the user what to run" at `4a-post`, **after every branch has been merged**, which is the one outcome this step exists to prevent. So run item 5 against the *run*: if no source produced a command list and **any** part of this cycle touches code — this pass's changed-file list, or `git diff --name-only <default branch>...<branch>` for any approved branch (the same per-branch read Step 3c makes) — stop and ask **here**, whether or not item 4 skipped the run.

If any command fails, report the failure and **stop**. Do not push with failing checks. Stopping *here* is free — nothing has been merged, no worktree has been removed, no lock has been dropped — so fix the failure and re-run `/review-close` from the top. (`4a-post` has a stop of its own, and it is not free in the same way; its recovery is stated there per policy.)

**Venv-aware invocation** (the consumer's own tooling — **not** `sysop/scripts/*.py`, which resolve venv PyYAML themselves and are always invoked with a bare `python3`; see WORKFLOW.md § 6.1). If a verification command fails with `exit 127` (command not found) or `ModuleNotFoundError` and the project has a `.venv/` directory at the repo root, re-run with `.venv/bin/<cmd>` (for explicit binaries like `.venv/bin/pytest`) or `PATH=.venv/bin:$PATH <cmd>` (for shell pipelines or tools that re-exec). Same pattern as Step 4d's pre-push hook venv prefix. The canonical fix is consumer-side — the project's `<project>/CLAUDE.md § Pre-merge verification` commands should be authored with `.venv/bin/` prefixes when they depend on venv-installed tools (see WORKFLOW.md § 6.1 venv-aware-invocation paragraph) — but the prefix-on-rerun pattern unblocks the cycle when the consumer's command list hasn't been venv-ified yet.

**Boy-scout escalation (ratchet consequence).** A `### Ratchet` snippet invokes the project's lint/typecheck tool against the changed-file list, so if a file in the diff carries pre-existing findings — warnings or type errors not introduced in this review pass — the tool will report them and the gate will fail. That's intentional and not a Sysop-side rule: touching a file means cleaning it. Full-tree backlog cleanups stay as separate project-side tasks (e.g. `TECH-LINT-BACKLOG-FIX`, `TECH-TYPECHECK-BACKLOG-FIX` entries in `tasks/index.yml`), so the ratchet doesn't impose a clean-everything-first dependency on consumers with existing backlogs.

**If a verification command is silently denied** (auto-mode classifier rejects a `npm` / `pytest` / `cargo` / project-specific invocation): prompt the user to run that command themselves via `!`-shell-escape in their prompt — the same pattern Step 4d uses for protected-branch pushes. Do NOT use `AskUserQuestion`; ask for the literal `!`-prefixed command. Step 0's permission guard cannot anticipate every project-specific verification command. (Phase 36's `PermissionDenied` hook surfaces guidance for exactly three shapes — a push to `origin` of one of the two branch names the hook **hard-codes** (`main` or `master`, literally; it does not resolve the default branch), a `--delete` push of any branch, and `git commit` on a protected branch — and emits nothing for anything else, verification commands included, because their vocabulary varies too widely per consumer to enumerate. So this prose remains the load-bearing instruction here. **State the coverage as those three shapes, never as the steps that use them** — a step reference reads as a promise about everything the step runs, and Step 4d under `pr` policy runs `gh pr`, which the hook does not match.)

> **For new projects:** add a `## Pre-merge verification` section to your CLAUDE.md (template in WORKFLOW.md § 6.1) listing the exact commands this skill should run. That keeps verification deterministic across consumer projects with different stacks.

## Step 3c: Manual Smoke Gate (BeanRider ISSUE-0008, Phase 35)

Some features can't be verified by automated checks — UI flows that need a browser, commands with external side effects, LLM round-trips whose output a human must eyeball. The contract: a task in `tasks/index.yml` may carry `manual_smoke: true`, and/or a `sysop/runtime/pending-docs/*.md` body may contain a heading matching `manual smoke` / `smoke required` (case-insensitive). Either signal halts this step until the human runs, confirms, or waives the procedure.

**Run step 1's detection first, on every cycle, and let it decide.** A `manual_smoke: true` task or a `smoke required` heading is a human saying *ask me*, and no diff-shape test can see one: the extension list cannot tell a docs commit from a task implemented in a `docker-compose.yml`, a feature-flag `.json`, a k8s manifest or a `.env.example`, all doc-only by that list. So — **no signal → proceed to Step 3b; any signal → run the gate, whatever the diff's extensions say.**

**Skip Step 3c only when the whole *run* is doc-only — not when Step 3's pre-merge pass was.** Those are different claims, and keying the smoke gate to the second would disable it on nearly every cycle: Step 3's list is main's local-only commits, which are the claim flips and the `review_tasks.md` save, so it doc-only-skips while the approved branches carry real code. **With detection first, that rule is residual rather than operative** — a run with no signal has nothing to skip, and a run with one is not entitled to — so do not compute per-branch diffs to evaluate it. It stays stated because the coupling it forbids is the regression this step nearly shipped, not because it decides anything. A smoke gate over a change nobody flagged is incoherent — but this is the gate whose miss is a human never being asked, so the doc-only test must never overrule an explicit ask.

**The cost, stated rather than discovered:** detection now runs on cycles that previously skipped it, so step 1's heredoc executes on a docs-only close too. That is the trade — one read, against a human never being asked — and it is why the heredoc's failure modes are loud: an unsubstituted `APPROVED_BRANCHES` exits 3 and an unreachable PyYAML exits 2, both stopping the close rather than reporting no signal. PyYAML is a declared hard dependency (Phase 136), so the second is a broken install surfacing, not a new requirement.

**1. Detect signals.** The gate reads pending-docs from **main's `sysop/runtime/pending-docs/` and each approved branch's worktree** — a `/claim-task` worktree authors its pending-doc there, and it is not copied to main until Step 3b (merge time). Reading the worktrees *in place* keeps the gate honest without collecting docs early: collecting before the merge would widen the window in which main's `sysop/runtime/pending-docs/` holds a doc for work that did not land, and a branch SKIP'd at Step 3b (worktree remove-refusal, ISSUE-0016) or a whole-run halt could then leave a stray doc that a later Step 4c consolidates for unmerged work, marking its task `done` with the code never merged (BeanRider ISSUE-0050). **The old form of this sentence claimed an invariant that no longer holds and never fully did** — it read *"everything in main's `sysop/runtime/pending-docs/` belongs to a just-merged branch"*, which its own next clause then contradicted by naming two ways a stray doc gets there. Step 4c step 1b now **enforces** what this sentence used to assert, by testing each doc's branch against the merge target rather than trusting its presence; so the directory may legitimately hold a held-back doc between runs, and nothing downstream may assume otherwise. List this run's approved branches (the same set Step 3b merges), then run the heredoc from the repo root. Output is either `NO_SMOKE_REQUIRED` (proceed to Step 3b) or `SMOKE_REQUIRED: N signal(s)` followed by one `---SIGNAL---` block per signal:

> **Three detection sources, because a phrase list was one.** The gate matched two exact phrases — `manual smoke` and `smoke required` — so a pending doc headed `OPERATOR ACTION REQUIRED BEFORE MERGE`, describing a hard irreversible pre-merge step, scored `NO_SMOKE_REQUIRED` and the close proceeded without ever prompting. Unlike every other gate in this skill the failure was silent *and* terminal: nothing downstream notices the operator was not asked, and the action is by construction the one that cannot be undone after merge. The heading list is now longer, but a longer allowlist over free prose is still an allowlist, so **two of the three sources do not depend on phrasing at all**:
>
> 1. **A matching heading** in a pending doc, or in the body of a task this close covers. Widened phrase set; `## User ops (do these first)` is deliberately excluded, because `user_action: true` is a **large, routine class** whose wholesale prompting would train the operator to waive. That reason is timing-independent and is the whole of it. An earlier form of this sentence also asserted a POST-merge timing that nothing in the tree supports, retired in Phase 235 — see `tasks/schema.md` § "User ops", which carries the correction and is the only place that quotes the retired wording. A step that must happen before *merge* is `manual_smoke:`, which sources 2 and 3 below detect regardless of heading.
> 2. **`manual_smoke: true` in a pending doc's own frontmatter** — signals whatever the doc's headings say.
> 3. **`manual_smoke: true` on the `tasks/index.yml` entry** — and it now signals **even when the body carries no matching heading, no readable `body:`, or no `body:` at all.** A declaration is the ask; a missing procedure makes the ask louder, not absent.
>
> **Task linkage also has two sources, because pending-doc frontmatter alone was not one.** A task whose ID no pending doc named was invisible to source 3 — so a task that declared `manual_smoke: true` *and* authored its procedure under the sanctioned heading was still scored `NO_SMOKE_REQUIRED`. The fully compliant author was the one the gate did not protect. Linkage is now `roadmap_ids:`/`task_ids:` from a pending doc **or** a lock under `sysop/runtime/locks/` whose `branch:` is one of this run's approved branches — which is why `$APPROVED_BRANCHES` is passed to the heredoc as a second positional argument. Locks are keyed by fact, not by a document that may be absent or malformed.

```bash
# Map this run's approved branches → their worktree dirs so the gate can read
# worktree-authored pending-docs in place (BeanRider ISSUE-0050). One approved branch
# per line — the same set Step 3b will merge (rejected / SKIP'd branches are excluded:
# they are not closing this run and must not trip the gate). If no approved branch has a
# worktree this cycle (e.g. a main-only close), set this to an empty string DELIBERATELY:
# leaving the placeholder would make the gate silently scan nothing (the very ISSUE-0050
# blindness this fixes), so an unsubstituted placeholder hard-errors below.
APPROVED_BRANCHES='<approved-branch-1>
<approved-branch-2>'
case "$APPROVED_BRANCHES" in
  *'<approved-branch'*)
    echo "ERROR: substitute APPROVED_BRANCHES with this run's approved branch names (or an" \
         "explicit empty string for a main-only close) before running Step 3c." >&2
    exit 3 ;;
esac
SMOKE_WORKTREE_DIRS=""
while IFS= read -r _b; do
  [ -n "$_b" ] || continue
  # `substr($<0>,…)` would be rewritten by the skill runner: a bare `$<0>` in this file is
  # replaced by the invocation's FIRST argument word, so `/review-close --dry-run` alone
  # was enough to break this and print NO_SMOKE_REQUIRED over an unscanned worktree
  # (internal tracker #360). Parameter expansion has no such collision.
  # The `case` reads from a HEREDOC, not from a pipe inside `$( )`. bash 3.2 — which is
  # what stock macOS ships as /bin/bash — cannot parse a `case` nested inside a
  # `while` inside command substitution: it dies with `syntax error near unexpected token
  # ';;'` at parse time, so the whole Step 3c block never runs and the gate is never
  # reached. Found by executing this preamble under /bin/bash while building the Step 3b
  # sibling below (Phase 218). The heredoc form parses on 3.2 and also keeps the loop in
  # the current shell, so `_wt` survives it.
  _wt=""
  while IFS= read -r _line; do
    case "$_line" in
      "worktree "*)          _w=${_line#worktree } ;;
      "branch refs/heads/"*) [ "${_line#branch refs/heads/}" = "$_b" ] && _wt="$_w" ;;
    esac
  done <<WT_LIST
$(git worktree list --porcelain)
WT_LIST
  [ -n "$_wt" ] && SMOKE_WORKTREE_DIRS+="$_wt"$'\n'
done <<BR_LIST
$APPROVED_BRANCHES
BR_LIST

# `python3` command word + in-heredoc PyYAML bootstrap (BeanRider ISSUE-0049; Sysop
# Phase 126) so `Bash(python3 -:*)` matches as a single simple command. The worktree-dir
# list is passed as one quoted positional arg (env-var *prefixes* don't match the rule);
# the repo root is CWD (this heredoc runs from the repo root; the venv bootstrap no
# longer depends on that — it resolves the main checkout via `git rev-parse
# --git-common-dir` and falls back to CWD), so the command line carries no env prefix.
python3 - "$SMOKE_WORKTREE_DIRS" "$APPROVED_BRANCHES" <<'EOF'
import re, sys
from pathlib import Path
try:
    import yaml
except ImportError:  # PyYAML lives only in the project venv (BeanRider ISSUE-0049)
    import glob, os, subprocess
    _sites = []
    try:
        _r = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=5,
            env={_k: _v for _k, _v in os.environ.items()
                 if _k not in ("GIT_DIR", "GIT_WORK_TREE",
                               "GIT_COMMON_DIR", "GIT_INDEX_FILE")},
        )
        _g = _r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        _g = ""
    for _root in ([os.path.dirname(os.path.abspath(_g))] if _g else []) + ["."]:
        for _layout in (".venv", "venv"):
            _sites += glob.glob(os.path.join(_root, _layout, "lib/python*/site-packages"))
    sys.path[:0] = _sites
    try:
        import yaml
    except ImportError:
        print("ERROR: pyyaml not available — install in the project venv", file=sys.stderr)
        sys.exit(2)

repo = Path.cwd().resolve()
# Search each approved branch's worktree sysop/runtime/pending-docs/ AND main's (BeanRider ISSUE-0050
# — worktree-authored docs aren't copied to main until Step 3b). Worktrees FIRST: if a doc
# exists in both (a stale copy a prior halted run left in main + the fresher worktree
# original), the worktree — the authoring source of truth — must win the basename dedup
# below, so a newly-added smoke heading is never shadowed by the stale main copy.
search_dirs = []
for _d in sys.argv[1].splitlines():
    _d = _d.strip()
    if _d:
        search_dirs.append(Path(_d) / "sysop/runtime/pending-docs")

# A WORKTREE IS NOT THE ONLY WORKSPACE SHAPE, AND THIS GATE RUNS BEFORE STEP 3B.
# argv[1] is computed from `git worktree list`, which never lists a `claim_task.sh --clone`
# workspace. Step 3b's collect handles that shape — but Step 3b runs *after* this gate, so
# at this moment a clone-authored pending-doc is in neither main nor argv[1], and a doc
# headed for an irreversible pre-merge step scored NO_SMOKE_REQUIRED with nothing to say
# so. Resolve the remaining approved branches the same way Step 3b step 0 does: the lock's
# recorded workspace, then the conventional sibling directory verified by reading its HEAD.
# Additive — argv[1] still wins for any branch it already covers.
_approved = [b.strip() for b in (sys.argv[2] if len(sys.argv) > 2 else "").splitlines() if b.strip()]
_covered = {str(Path(d).resolve()) for d in sys.argv[1].splitlines() if d.strip()}

def _head_branch(d):
    dot = d / ".git"
    if dot.is_file():                       # a worktree/submodule: `gitdir: <path>`
        line = dot.read_text(encoding="utf-8", errors="replace").strip()
        if not line.startswith("gitdir:"):
            return None
        dot = Path(line[len("gitdir:"):].strip())
        if not dot.is_absolute():
            dot = (d / dot).resolve()
    head = dot / "HEAD"
    if not head.is_file():
        return None
    ref = head.read_text(encoding="utf-8", errors="replace").strip()
    return ref[len("ref: refs/heads/"):] if ref.startswith("ref: refs/heads/") else None

for _b in _approved:
    _ws = None
    _locks = repo / "sysop" / "runtime" / "locks"
    if _locks.is_dir():
        for _lk in sorted(_locks.glob("*.lock")):
            if not _lk.is_file():
                continue
            _f = {}
            for _line in _lk.read_text(encoding="utf-8", errors="replace").splitlines():
                _k, _sep, _v = _line.partition(":")
                if _sep and _k not in _f:
                    _f[_k] = _v.strip()
            if _f.get("branch") == _b and _f.get("workspace"):
                _ws = Path(_f["workspace"]); break
    if _ws is None:
        import os
        _prefix = os.environ.get("WORKTREE_PREFIX") or repo.name
        for _cand in sorted(repo.parent.glob(f"{_prefix}-*")):
            if _cand.is_dir() and _head_branch(_cand) == _b:
                _ws = _cand; break
    if _ws is None:
        continue
    try:
        _r = _ws.resolve()
    except OSError:
        continue
    if _r == repo or str(_r) in _covered:      # main's own docs are appended below
        continue
    _covered.add(str(_r))
    search_dirs.append(_ws / "sysop/runtime/pending-docs")

search_dirs.append(repo / "sysop/runtime/pending-docs")

# The heading phrase set is WIDER than the original two (`manual smoke` / `smoke
# required`), because the original was an allowlist over free prose and the gate's
# failure direction is silence: a pending doc headed `OPERATOR ACTION REQUIRED BEFORE
# MERGE` scored NO_SMOKE_REQUIRED and the close proceeded without ever asking (reported
# by a consumer). A false positive here costs one AskUserQuestion with a
# waive option; a false negative is a human never asked about an irreversible step.
# `user ops` is DELIBERATELY not in this set — `user_action: true` is a large, routine
# class, and prompting on all of it would train the operator to waive wholesale. That
# reason is timing-independent and is the whole of it (tasks/schema.md § "User ops"; an
# earlier form also claimed POST-merge timing, which nothing in the tree supports).
# A step that must precede the MERGE is `manual_smoke:`, detected by sources 2 and 3.
heading_re = re.compile(
    r'^(#{1,6})\s+.*('
    r'manual\s+smoke'
    r'|smoke\s+(?:required|test)'
    r'|manual\s+(?:verification|verify|test|check|step)'
    r'|operator\s+action'
    r'|human\s+action'
    r'|requires?\s+a\s+human'
    r'|before\s+merg(?:e|ing)'
    r'|prior\s+to\s+merg(?:e|ing)'
    r')',
    re.IGNORECASE | re.MULTILINE,
)
fm_re = re.compile('^\\ufeff?---\\n(.*?)\\n---', re.DOTALL)   # a BOM must not hide the frontmatter

def extract_sections(text):
    for m in heading_re.finditer(text):
        start, depth = m.start(), len(m.group(1))
        end = len(text)
        for nm in re.finditer(r'^(#{1,6})\s+', text[m.end():], re.MULTILINE):
            if len(nm.group(1)) <= depth:
                end = m.end() + nm.start(); break
        yield text[start:end].rstrip()

def label(md):
    # main-relative when possible; absolute for a worktree-authored doc
    try:
        return str(md.relative_to(repo))
    except ValueError:
        return str(md)

# Collect pending-docs across all search dirs; dedup by basename (first wins,
# worktrees ahead of main) so a doc present in both is counted once, preferring
# the fresher worktree copy.
pending_files = []
seen_names = set()
for pd in search_dirs:
    if not pd.is_dir():
        continue
    for md in sorted(pd.glob("*.md")):
        # Not a branch pending-doc: a fixed-name file the review skills own and delete
        # themselves. It has no `branch:` and no smoke headings, and counting it here
        # makes an empty pending-docs dir look populated. Step 4c excludes it too.
        if md.name == "convention-candidates.md":
            continue
        if md.name in seen_names:
            continue
        seen_names.add(md.name)
        pending_files.append(md)

def truthy(v):
    """`manual_smoke` is documented as a bool — but this gate runs before the merge and
    the validator's type check is warn-shaped in practice. `manual_smoke: "true"` is an
    author saying *ask me*; `is True` alone scored it NO_SMOKE_REQUIRED."""
    return v is True or (isinstance(v, str) and v.strip().lower() in {"true", "yes", "on", "1"})

def id_list(v):
    """`roadmap_ids: T-1` is a scalar, and iterating it walks its CHARACTERS — every
    linkage silently lost. Accept the scalar as a one-element list."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    if isinstance(v, (list, tuple)):
        return [x for x in v if isinstance(x, str)]
    return [str(v)]

def read_fm(md):
    """Frontmatter dict for a pending doc, or {} — parsed ONCE per file.

    `or {}` is NOT enough: safe_load on a single prose line between the delimiters
    returns a truthy `str`, and on a bare list a truthy `list`, so `.get()` below
    raised AttributeError and killed the whole close. Test the type, not truthiness.
    """
    m = fm_re.match(md.read_text(encoding="utf-8", errors="replace"))
    if not m:
        return {}
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}
    return fm if isinstance(fm, dict) else {}

signals = []

# (a) pending-doc body scan
for md in pending_files:
    # errors="replace": a pending-doc with non-UTF-8 bytes must not kill the close.
    for sec in extract_sections(md.read_text(encoding="utf-8", errors="replace")):
        signals.append((label(md), sec))

# (a2) STRUCTURAL declaration on the pending doc itself: `manual_smoke: true` in
# frontmatter signals regardless of how — or whether — the procedure is headed. This is
# the heading-independent escape for a hotfix branch with no tasks/index.yml entry; a
# declaration nobody has to phrase correctly cannot be missed by a phrase list.
for md in pending_files:
    if truthy(read_fm(md).get("manual_smoke")):
        secs = list(extract_sections(md.read_text(encoding="utf-8", errors="replace")))
        if not secs:
            signals.append((label(md), "(frontmatter `manual_smoke: true`, no procedure "
                                       "section found in this doc — ask the human what it is)"))

# (b) index.yml manual_smoke:true cross-check.
#
# TWO linkage sources, because pending-doc frontmatter alone was not one. A task can
# declare `manual_smoke: true`, author its procedure under the sanctioned heading, and
# still be scored NO_SMOKE_REQUIRED when no pending doc's roadmap_ids named it — the
# fully-compliant author was the one the gate did not protect. The lock is the second
# source: it records `branch:`, so a claimed task is linked to this run's approved
# branches by fact rather than by a doc that may be absent or malformed.
index_path = repo / "tasks" / "index.yml"
if index_path.is_file():
    try:
        idx = yaml.safe_load(index_path.read_text(encoding="utf-8", errors="replace")) or {}
    except yaml.YAMLError:
        idx = {}
    if not isinstance(idx, dict):
        idx = {}
    tasks = {t["id"]: t for t in (idx.get("tasks") or []) if isinstance(t, dict) and t.get("id")}
    smoke_ids = set()
    # source 1 — pending-doc frontmatter (Phase 23a compat shim: roadmap_ids OR task_ids)
    for md in pending_files:
        fm = read_fm(md)
        for tid in (id_list(fm.get("roadmap_ids")) or id_list(fm.get("task_ids"))):
            if truthy(tasks.get(tid, {}).get("manual_smoke")):
                smoke_ids.add(tid)
    # source 2 — locks whose `branch:` is one of THIS run's approved branches. Locks are
    # canonical under the main repo (git-common-dir), which is CWD here.
    approved = {b.strip() for b in (sys.argv[2] if len(sys.argv) > 2 else "").splitlines() if b.strip()}
    if approved:
        locks_dir = repo / "sysop" / "runtime" / "locks"
        if locks_dir.is_dir():
            for lk in sorted(locks_dir.glob("*.lock")):
                lock_branch = ""
                for line in lk.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("branch:"):
                        lock_branch = line[len("branch:"):].strip(); break
                if lock_branch and lock_branch in approved:
                    tid = lk.name[:-len(".lock")]
                    if truthy(tasks.get(tid, {}).get("manual_smoke")):
                        smoke_ids.add(tid)
    seen_lc = "\n".join(s for _, s in signals).lower()
    for tid in sorted(smoke_ids):
        body_rel = tasks[tid].get("body", "")
        src = f"tasks/index.yml § {tid}"
        # A DECLARED smoke whose body cannot be read, or carries no recognisable
        # procedure heading, is a signal — not silence. The declaration is the ask;
        # a missing procedure makes the ask louder, not absent.
        if not body_rel:
            signals.append((src, "(manual_smoke: true, but the task has no `body:` — "
                                 "ask the human what the procedure is)"))
            continue
        body_path = repo / body_rel if body_rel.startswith("tasks/") else repo / "tasks" / body_rel
        if not body_path.is_file():
            signals.append((src, f"(manual_smoke: true, but its body `{body_rel}` is not "
                                 f"readable from here — ask the human what the procedure is)"))
            continue
        found = False
        for sec in extract_sections(body_path.read_text(encoding="utf-8", errors="replace")):
            found = True
            if sec.lower() in seen_lc: continue
            signals.append((src, sec))
        if not found:
            signals.append((src, "(manual_smoke: true, but no procedure heading matched in "
                                 f"`{body_rel}` — ask the human what the procedure is)"))

if not signals:
    print("NO_SMOKE_REQUIRED")
else:
    print(f"SMOKE_REQUIRED: {len(signals)} signal(s)")
    for src, sec in signals:
        print("---SIGNAL---")
        print(f"SOURCE: {src}")
        print(sec)
EOF
```

If the output is `NO_SMOKE_REQUIRED`, continue to Step 3b. Otherwise, parse the signal blocks and proceed to step 2.

**2. For each signal, call `AskUserQuestion`.** Present the section text verbatim along with the source label. Three options (single-select):

- **"I'll drive the smoke"** — agent attempts to run the procedure using available MCP tools (chrome-devtools-mcp, playwright, project-specific CLI tooling). The agent reads the section's step list, drives it, and reports the outcome.
- **"Already ran it manually — proceed"** — human confirms they ran the smoke; record as confirmed.
- **"Skip with waiver"** — record as waived, with the source label, for Step 8's report.

Ask signals one at a time; track per-signal decisions in a structured tally (source → decision).

**3. Halt rules.**
- If the human picks "I'll drive" and the agent's attempt fails (MCP tool not available, fixture missing, command errors), **halt this run**. Do not proceed to Step 4. Surface what failed; the next `/review-close` invocation re-runs Step 3c.
- Waivers do NOT halt; they accumulate for Step 8.
- "Already ran it manually" is trusted at face value — the entire point of the gate is letting the human assert "yes, I did the thing."

**4. Record outcomes for Step 8.** The tally drives the "Manual smoke" line in the final report (e.g., `Manual smoke: 1 confirmed, 1 waived (sysop/runtime/pending-docs/feat-foo.md)`).

> **For new projects:** declare `manual_smoke: true` on `tasks/index.yml` entries whose verification needs a human (browser flow, side-effect-bearing command, LLM round-trip). Author the procedure under a `## Manual smoke required` heading in the task body file. The validator warns (not blocks) when the field is set but the heading is missing — see `tasks/schema.md § Manual smoke`.

## Step 3b: Prepare Worktrees for Merge

Feature branches created by `/claim-task` or `batch_work.sh` usually live in worktrees. Branches checked out in a worktree cannot be checked out from main, so worktrees for **approved** branches must be removed before merging.

> **A worktree is one workspace shape, not the only one — and the collect is not conditional on it (internal tracker `Q-238`).** `claim_task.sh --clone` produces a **full clone**, which `git worktree list` never lists. Until Phase 218 the pending-doc collect below was nested under *"if a worktree exists"*, so a clone workspace fell through to *"the branch is already free for checkout"*: its pending-doc was never collected, Step 4c never consolidated it, its `roadmap_ids` never flipped to `done`, and its body was never archived. Nothing was lost — the clone directory persists — and nothing said so, which is why it is a silent-incompletion defect rather than a data-loss one. **The remove is worktree-only; the collect is not.** Removal is what needs a worktree. Collecting a doc needs a *directory*.

For each approved feature branch:

**0. Locate the branch's workspace**, first hit wins, and record which shape it is. Run this from the repo root with `BRANCH` set to the branch this iteration is processing:

```bash
# `python3` command word + in-heredoc PyYAML-free stdlib only, so `Bash(python3 -:*)`
# matches as a single simple command (Phase 126). THREE quoted positional args: the
# branch this iteration is processing, `git worktree list --porcelain` output, and the
# repo's own basename prefix. Passing the worktree listing IN means this block runs no
# subprocess of its own and needs no shell loop — the two bash `for` loops an earlier
# draft used are unauthorizable (`for`/`done` are not documented command separators, so
# no allow-rule binds them), which is the same reason Step 3b's rollback became a
# heredoc. Run from the repo root.
python3 - "<branch name>" "$(git worktree list --porcelain)" "${WORKTREE_PREFIX:-$(basename "$(git rev-parse --show-toplevel)")}" <<'PY'
import sys
from pathlib import Path

branch, wt_listing, prefix = sys.argv[1], sys.argv[2], sys.argv[3]
repo = Path.cwd().resolve()

# An unsubstituted placeholder must HARD-FAIL, not quietly match nothing. A block that
# resolves no workspace is indistinguishable from a branch that legitimately has none,
# and "resolved nothing, said nothing" is the exact failure this step is being fixed for.
if branch.startswith("<") or not branch.strip():
    print("ERROR: substitute the branch name before running Step 3b step 0.", file=sys.stderr)
    sys.exit(3)

ws, shape = None, None

# (i) a worktree — the default /claim-task and batch_work.sh shape.
_w = None
for line in wt_listing.splitlines():
    if line.startswith("worktree "):
        _w = line[len("worktree "):]
    elif line == f"branch refs/heads/{branch}":
        ws, shape = Path(_w), "worktree"
        break

# (ii) the lock's RECORDED workspace. `claim_task.sh --lock` writes `mode:` and
# `workspace:` at claim time, so this is the claim's own statement of where the work
# happened — a fact, not a path guess. Locks are canonical under the main repo
# (git-common-dir), which is CWD here.
if ws is None:
    locks = repo / "sysop" / "runtime" / "locks"
    if locks.is_dir():
        for lk in sorted(locks.glob("*.lock")):
            if not lk.is_file():        # a lock that is a directory must not kill the close
                continue
            fields = {}
            for line in lk.read_text(encoding="utf-8", errors="replace").splitlines():
                k, sep, v = line.partition(":")
                if sep and k not in fields:
                    fields[k] = v.strip()
            if fields.get("branch") != branch or not fields.get("workspace"):
                continue
            cand = Path(fields["workspace"])
            # VERIFY the recorded workspace before taking it. The lock is the claim's own
            # statement, but a claim can be stale: a lock left behind by a workspace that
            # has since been deleted or moved shadowed the live one, arm (iii) never ran,
            # and the collect then aborted (exit 4) on a path that no longer exists — with
            # nothing in the disposition naming the stale lock as the cause. An unverified
            # arm must not be ordered ahead of a verified one.
            if not cand.is_dir():
                continue
            ws, shape = cand, fields.get("mode") or "recorded"
            break

# (iii) the conventional sibling directory `claim_task.sh` computes, VERIFIED rather
# than assumed: a candidate counts only if it is a git checkout whose HEAD is this
# branch. This is the arm for `--clone` without `--lock` — USE_LOCK defaults to false,
# so a lock-only fix would be inert on exactly that invocation. HEAD is read from the
# object store, not from `git`, so this block still spawns nothing.
def head_branch(d):
    dot = d / ".git"
    if dot.is_file():                       # a worktree/submodule: `gitdir: <path>`
        line = dot.read_text(encoding="utf-8", errors="replace").strip()
        if not line.startswith("gitdir:"):
            return None
        dot = Path(line[len("gitdir:"):].strip())
        if not dot.is_absolute():
            dot = (d / dot).resolve()
    head = dot / "HEAD"
    if not head.is_file():
        return None
    ref = head.read_text(encoding="utf-8", errors="replace").strip()
    return ref[len("ref: refs/heads/"):] if ref.startswith("ref: refs/heads/") else None

if ws is None:
    # Two passes. The prefixed glob first, because it is what `claim_task.sh` computes —
    # then EVERY sibling directory, because `WORKTREE_PREFIX` is read from the *claiming*
    # session's environment and recorded nowhere except a lock that `--lock` may not have
    # written. Without the second pass, a consumer who exports that variable at claim time
    # and not at close time gets `<none>` — the same silent incompletion this step exists
    # to remove. The widening is safe because the arm verifies `HEAD`: a directory only
    # counts if it is a git checkout standing on this exact branch.
    for cands in (sorted(repo.parent.glob(f"{prefix}-*")),
                  sorted(d for d in repo.parent.iterdir() if d.is_dir())):
        for cand in cands:
            if cand.resolve() == repo:
                continue
            if cand.is_dir() and head_branch(cand) == branch:
                ws, shape = cand, "discovered"
                break
        if ws is not None:
            break

# The main checkout is not a collectible workspace: `--branch` mode records
# WORKSPACE_PATH=$REPO_ROOT, and copying main's pending-docs onto themselves is at best
# a no-op and at worst a self-overwrite. Its docs are already where Step 4c looks.
# Compare RESOLVED paths — `claim_task.sh` writes `workspace:` unresolved, so it can
# contain `/../`, and on macOS the repo root reaches through `/private`.
if ws is not None:
    try:
        if ws.resolve() == repo:
            ws, shape = None, "main-checkout"
    except OSError:
        ws, shape = None, "unresolvable"

print(f"workspace={ws or '<none>'} shape={shape or '<none>'}")
PY
```

**If `WS` is empty**, there is nothing to collect and nothing to remove — the branch is already free for checkout. Say which of the two reasons applies (the `main-checkout` shape — a fixed enum value Step 0 prints verbatim, never a branch name — or no workspace found at all); they are not the same fact and a later step that has to reconstruct what happened cannot tell them apart from silence.

**1. Collect this branch's pending-docs from the workspace step 0 resolved, whatever its shape** — worktree, clone, or discovered. Step 0 *prints* `workspace=… shape=…`; it does not export them, and the heredoc below takes the path as a quoted positional argument. **Substitute the printed values by hand** — `WS` and `SHAPE` are names for the two things step 0 told you, not shell variables that survive into this block. (Every fenced block in this skill is independent: nothing set in one reaches the next.)
   a. **Collect pending-docs**: bring each `sysop/runtime/pending-docs/*.md` from the worktree into main's `sysop/runtime/pending-docs/` (these are untracked files that would be lost when the worktree is removed). **The copy is provenance-checked, because the destination is keyed by basename and a basename is not unique to a branch.**

      ```bash
      # `python3` command word + in-heredoc PyYAML bootstrap (Phase 126) so
      # `Bash(python3 -:*)` matches as a single simple command. TWO quoted positional
      # args: the worktree path and **the branch this iteration is processing** — the
      # same name step 1 above matched from `git worktree list` and item (b) passes to
      # `git worktree remove`. Run from the repo root; `live` below is relative to CWD.
      python3 - "<worktree-path>" "<branch name>" <<'PY'
      import re, shutil, sys
      from pathlib import Path
      try:
          import yaml
      except ImportError:  # PyYAML lives only in the project venv (BeanRider ISSUE-0049)
          import glob, os, subprocess
          _sites = []
          try:
              _r = subprocess.run(
                  ["git", "rev-parse", "--git-common-dir"],
                  capture_output=True, text=True, timeout=5,
                  env={_k: _v for _k, _v in os.environ.items()
                       if _k not in ("GIT_DIR", "GIT_WORK_TREE",
                                     "GIT_COMMON_DIR", "GIT_INDEX_FILE")},
              )
              _g = _r.stdout.strip()
          except (OSError, subprocess.SubprocessError):
              _g = ""
          for _root in ([os.path.dirname(os.path.abspath(_g))] if _g else []) + ["."]:
              for _layout in (".venv", "venv"):
                  _sites += glob.glob(os.path.join(_root, _layout, "lib/python*/site-packages"))
          sys.path[:0] = _sites
          import yaml

      wt      = Path(sys.argv[1])
      branch  = sys.argv[2]          # the branch this iteration is processing
      live    = Path('sysop/runtime/pending-docs')
      src_dir = wt / 'sysop' / 'runtime' / 'pending-docs'

      # `convention-candidates.md` is NOT a branch pending-doc. It is a fixed-name file
      # /codebase-review and /security-audit write, append to, and delete themselves; it
      # carries no `branch:` frontmatter and belongs to no branch. Collecting it moves a
      # live review round's candidates onto main, where Step 4c consolidates and deletes
      # them. Never collect it.
      NOT_A_BRANCH_DOC = {'convention-candidates.md'}
      fm_re = re.compile(r'^---\n(.*?)\n---', re.DOTALL)

      # A wrong or unsubstituted <worktree-path> must be LOUD. The retired `cp` form
      # exited 1 on a bad path; a bare glob over a missing dir yields nothing and would
      # exit 0 with a success-shaped report, after which (b) removes the worktree and the
      # untracked docs are gone. Step 3c hard-errors on its unsubstituted placeholder for
      # the same reason. `src_dir` is checked too, not just `wt`: an existing but WRONG
      # directory is the shape that otherwise reports success over nothing.
      if ('<worktree' in str(wt) or '<branch' in branch
              or not branch.strip() or not wt.is_dir() or not src_dir.is_dir()):
          print(f'PENDING-DOC COLLECT ABORTED: unusable worktree path or branch name '
                f'({wt}, {branch!r})')
          sys.exit(4)

      def branch_of(p):
          """This doc's `branch:`, read with the SAME parser Steps 3c and 4c use.

          Deliberately `yaml.safe_load` and not a hand-rolled line scan. A scan diverges
          from PyYAML on ordinary YAML — a folded scalar (`branch: >`) yields the literal
          `>`, duplicate keys pick the wrong one, a trailing `# comment` is kept as part
          of the value — and two different branches collapsing to one token is precisely
          the silent overwrite this step exists to prevent. A third divergent reader in a
          file that already had two is what this phase is fixing; adding one would be the
          same defect wearing the fix's name.

          None is a real answer, not an error: a doc whose provenance will not parse can
          never be shown to be the SAME branch as another, and the caller treats
          unknown-vs-anything as a collision.
          """
          try:
              m = fm_re.match(p.read_text(encoding='utf-8', errors='replace'))
          except OSError:
              return None
          if not m:
              return None
          try:
              fm = yaml.safe_load(m.group(1))
          except yaml.YAMLError:
              return None
          if not isinstance(fm, dict):
              return None
          b = fm.get('branch')
          return b.strip() if isinstance(b, str) and b.strip() else None

      docs = [p for p in sorted(src_dir.glob('*.md')) if p.name not in NOT_A_BRANCH_DOC]

      # STAGE 1 — DECIDE. Nothing is written until every doc has been checked, so there is
      # no partial state to undo. An earlier draft copied as it went and undid the copies
      # on a collision; its undo deleted files main already held, because an overwritten
      # doc was in the same "collected" list as a newly-created one. Deciding first makes
      # that class impossible rather than handled.
      collisions = []
      for src in docs:
          # Ground truth is the branch being PROCESSED, not what two docs say about each
          # other. A doc that does not claim this branch is not this branch's to collect.
          src_b = branch_of(src)
          if src_b != branch:
              collisions.append(f'{src.name} (worktree doc claims {src_b!r}, '
                                f'processing {branch!r})')
              continue
          dst = live / src.name
          if dst.exists():
              dst_b = branch_of(dst)
              # Overwrite ONLY main's own stale twin of this same branch. Any other
              # branch's record is untouchable, however this branch's doc is labelled.
              if dst_b != branch:
                  collisions.append(f'{src.name} (main copy belongs to {dst_b!r}, '
                                    f'processing {branch!r})')
      if collisions:
          for c in collisions:
              print(f'PENDING-DOC COLLISION: {c}')
          print(f'PENDING-DOC COLLISIONS: {len(collisions)} — refusing; '
                f'nothing collected, main untouched, worktree left in place')
          sys.exit(3)

      # STAGE 2 — COPY. Every doc has already been cleared.
      live.mkdir(parents=True, exist_ok=True)   # load-bearing, see below
      for src in docs:
          try:
              shutil.copy2(src, live / src.name)
          except OSError as e:
              # A broken symlink, a directory named *.md, an unreadable file. Report and
              # halt: (b) must not remove a worktree whose docs are not all on main.
              print(f'PENDING-DOC COLLECT FAILED: {src.name}: {e}')
              sys.exit(5)
          print(f'PENDING-DOC COLLECTED: {src.name}')
      for p in sorted(src_dir.glob('*.md')):
          if p.name in NOT_A_BRANCH_DOC:
              print(f'PENDING-DOC SKIPPED (not a branch doc): {p.name}')
      print('PENDING-DOC COLLISIONS: 0')
      PY
      ```

      **Why provenance and not a content comparison.** The two copies differing is *not* the signal — the overwhelmingly common collision is the **same branch collected twice** (a prior run copied the doc, then died before `git worktree remove`), where main's copy is stale by construction and the worktree must win. Step 3c states exactly that rule for its own dedup, and a byte-comparison would fire loudly on the case where overwriting is correct while staying silent on the case that matters. What matters is whether the two docs came from the **same branch**, and each doc already carries that claim in its own `branch:` field.

      **Print to stdout, and note there is no `2>/dev/null` any more.** The old form masked the dest-missing error, which is what made the failure silent; the collision lines above are the Step 8 `Pending-doc collisions:` row's only source.

      **Any non-zero exit means do NOT proceed to (b).** There are three, and they are not interchangeable:

      | exit | meaning | state of main | what to do |
      |---|---|---|---|
      | **3** | a collision — some doc does not belong to this branch | **untouched**; stage 1 writes nothing, so there is no partial work and nothing to undo | SKIP this branch (worktree, lock and branch intact). **Do not run the rollback** — it has nothing to undo. Resolve by correcting the mis-labelled doc, then re-run |
      | **4** | unusable `<worktree-path>` or `<branch name>` — a placeholder left unsubstituted, a missing directory, an empty branch | **untouched**; nothing ran | fix the invocation and re-run. Never proceed to (b) |
      | **5** | a copy failed partway through stage 2 (broken symlink, unreadable file) | **partially written** — some docs collected, the rest not | SKIP this branch and **do** run the rollback, which removes this branch's own collected copies by provenance. This is the one exit where there IS partial work |

      An earlier draft of this paragraph named only two exits and said exit 3 *"has undone its own partial work"* — language left over from the retired second design, which copied as it went. This one decides first, so on 3 there is nothing to undo; and it omitted 5, which is the only exit where the sentence would have been true.

      **Why refuse rather than preserve-and-continue.** An earlier draft of this phase moved main's copy into a `sysop/runtime/pending-docs/superseded/` subdirectory and carried on. Its own review round disqualified that: **nothing in the shipped tree reads that directory.** Step 4c step 1 is a non-recursive `ls …/*.md`, so a parked doc is never consolidated — its branch's `roadmap_ids` never flip, its body is never archived, its lock never drops — and the phase had shipped, as the steady-state result of an ordinary collision, the exact end state the rollback note below condemns. Preserving bytes where no reader looks is not preservation. Refusing keeps both records in the two places a reader already checks.

      **The `mkdir` is still load-bearing, for the original reason.** Main's `sysop/runtime/pending-docs/` often does not exist (it is gitignored — absent from any fresh clone — authored lazily by `/document-work` in the *worktree*, and removed-when-empty by Step 4c's cleanup), so a copy into a missing destination fails; the very next `git worktree remove` then deletes the gitignored pending-doc for good. For the same reason, if the collect could not run at all (e.g. a permission halt — see the pre-flight guard's deliberate-non-entry note), do **NOT** proceed to (b): removing the worktree with the docs uncollected is exactly the data loss this step exists to prevent.
   b. **ONLY WHEN `SHAPE=worktree`** — strip the non-work symlinks Step 1a downgraded, then **remove the worktree**, **never `--force`**.

      > **This gate is stated here, before the command, and item 2 below only elaborates it.** The first cut of this step put the gate 80 lines *after* this sub-item, and an operator following the steps in written order on a clone workspace did all of this: collected the doc (a), ran `git worktree remove` on a directory that is not a worktree, got `fatal: '<path>' is not a working tree` (exit 128), read *this sub-item's own* refusal prose — *"stop, surface the error, then roll back the pending-docs this branch copied in step (a)"* — rolled the doc back out of main, and downgraded the branch to SKIP. **Net result: the doc collected and then deleted, and the branch not merged** — the pre-Phase-218 end state plus a lost merge, produced by the very step that was supposed to fix it. A rule an operator reaches after the command it governs is not a gate.
      >
      > **For any other `SHAPE`, skip straight to item 2.** The removal is the only part of this step that needs a worktree, and `git worktree remove`'s failure on a clone carries **no** claim about untracked files — so it is never the ISSUE-0016 remove-refusal, and must never trigger the rollback below.
 Step 1a can now classify a worktree `clean-ahead` while a downgraded tooling symlink (an untracked `.venv`-into-the-main-venv, BeanRider ISSUE-0043) is still physically present, and that lone symlink is enough to make an *unforced* `git worktree remove` refuse (`contains modified or untracked files`). So before removing, re-apply the same downgrade rule and delete just those symlinks — removing a symlink deletes only the pointer, never its (gitignored) target, and we stay unforced, so any *real* untracked or modified file still blocks the remove:

      ```bash
      # The .gitignore owner is the PRIMARY checkout, so resolve it the way Step 1a
      # does — `--show-toplevel` would name whichever worktree the runner is standing in.
      main_root=$(cd "$(git rev-parse --git-common-dir)/.." && pwd -P)
      git -C "<worktree-path>" status --porcelain | while IFS= read -r line; do
        [[ "$line" == '?? '* ]] || continue           # untracked entries only
        entry=${line#'?? '}                           # `entry`, never `path` (zsh $PATH alias)
        [[ -L "<worktree-path>/$entry" ]] || continue # symlinks only — never a real file
        target=$(readlink "<worktree-path>/$entry")
        case "$target" in                             # same downgrade rule as Step 1a
          /*) : ;;
          *)  target=$(cd "<worktree-path>/$(dirname "$entry")" 2>/dev/null && cd "$(dirname "$target")" 2>/dev/null && printf '%s/%s' "$PWD" "$(basename "$target")") ;;
        esac
        git -C "$main_root" check-ignore -q "$target" 2>/dev/null && rm -f "<worktree-path>/$entry"
      done
      git worktree remove <worktree-path>             # unforced
      ```

      By Step 1a's classification, an `approved` branch passed through Step 2a's clean-state check, so the unforced remove should now succeed. If `git worktree remove` **still** refuses after the strip, that means the worktree carries a genuine untracked/modified file that appeared between Step 1a and now — **stop**, surface the error, then **roll back the pending-docs this branch copied in step (a)** so a later Step 4c cannot consolidate an unmerged branch's doc and mark its task `done` with the code never merged:

      ```bash
      python3 - "<worktree-path>" "<branch name>" <<'PY'
      import re, sys
      from pathlib import Path

      try:
          import yaml
      except ImportError:  # PyYAML lives only in the project venv (BeanRider ISSUE-0049)
          import glob, os, subprocess
          _sites = []
          try:
              _r = subprocess.run(
                  ["git", "rev-parse", "--git-common-dir"],
                  capture_output=True, text=True, timeout=5,
                  env={_k: _v for _k, _v in os.environ.items()
                       if _k not in ("GIT_DIR", "GIT_WORK_TREE",
                                     "GIT_COMMON_DIR", "GIT_INDEX_FILE")},
              )
              _g = _r.stdout.strip()
          except (OSError, subprocess.SubprocessError):
              _g = ""
          for _root in ([os.path.dirname(os.path.abspath(_g))] if _g else []) + ["."]:
              for _layout in (".venv", "venv"):
                  _sites += glob.glob(os.path.join(_root, _layout, "lib/python*/site-packages"))
          sys.path[:0] = _sites
          import yaml

      wt     = Path(sys.argv[1])
      branch = sys.argv[2]
      live   = Path('sysop/runtime/pending-docs')
      NOT_A_BRANCH_DOC = {'convention-candidates.md'}   # never collected, so never rolled back
      fm_re = re.compile(r'^---\n(.*?)\n---', re.DOTALL)

      if '<worktree' in str(wt) or '<branch' in branch or not branch.strip():
          print('PENDING-DOC ROLLBACK ABORTED: unusable worktree path or branch name')
          sys.exit(4)

      def branch_of(p):
          """Identical to the collect's reader — same regex, same `yaml.safe_load`.

          An earlier draft hand-rolled a line scan here while the collect used yaml, so
          the two halves of one step disagreed on 18 of 33 frontmatter shapes: the
          rollback could not undo its own collect, and reported a byte-identical doc as
          'not this branch's'. Two divergent readers twenty lines apart, in the phase
          whose subject is two divergent readers."""
          try:
              m = fm_re.match(p.read_text(encoding='utf-8', errors='replace'))
          except OSError:
              return None
          if not m:
              return None
          try:
              fm = yaml.safe_load(m.group(1))
          except yaml.YAMLError:
              return None
          if not isinstance(fm, dict):
              return None
          b = fm.get('branch')
          return b.strip() if isinstance(b, str) and b.strip() else None

      removed, left = [], []
      for src in sorted((wt / 'sysop' / 'runtime' / 'pending-docs').glob('*.md')):
          if src.name in NOT_A_BRANCH_DOC:
              continue
          dst = live / src.name
          if not dst.exists():
              continue
          # Ground truth is the branch being processed. Delete main's copy ONLY when
          # THAT copy claims this branch — the copy step (a) just made. Comparing the two
          # docs to each other is what let a worktree carrying a foreign-branch doc
          # delete another branch's only surviving record.
          if branch_of(dst) == branch:
              dst.unlink()                              # re-collected on a later run
              removed.append(src.name)
          else:
              left.append(f'{src.name} (main copy claims {branch_of(dst)!r}, processing {branch!r})')
      print('ROLLED BACK: ' + (', '.join(removed) or 'none'))
      print('LEFT ALONE (not this branch\'s): ' + (', '.join(left) or 'none'))
      PY
      ```

      > **Provenance, not basename — that distinction IS the fix.** The previous form was `rm -f sysop/runtime/pending-docs/$(basename "$f")` over the worktree's files, which deleted main's copy by name with no check that this branch ever wrote it. Measured: against a **different** branch's doc it removed a file this branch never authored, and step (a) had already overwritten it, so both records were gone while the victim's worktree was already removed. Reading `branch:` from both copies makes the rollback delete only what step (a) copied. **There is no restore half, because there is nothing to restore**: (a) now refuses a differing-branch collision outright rather than displacing anything, so a doc that is not this branch's is never touched by either step. An earlier draft of this phase parked the displaced copy under a `superseded/` subdirectory; that was withdrawn when its own review round showed the directory had **no consumer anywhere in the tree** — `ls sysop/runtime/pending-docs/*.md` is non-recursive, so Step 4c never sees a parked doc, and the branch's task would never close. Preserving bytes where no reader looks is not preservation.

      Then downgrade this branch to SKIP for this run (leave its worktree, lock, and branch intact), and continue with the next approved branch. Silent data loss is the failure mode this guard prevents (BeanRider ISSUE-0016) — the strip never touches a real file, so it cannot cause it. (The rollback matters because step (a) copies before this remove is attempted; without it, a branch SKIP'd here leaves its doc stranded in main's `sysop/runtime/pending-docs/` for the merged branches' Step 4c to consolidate.)

**2. Remove the workspace — only when `SHAPE=worktree`.** Item (b) above is the removal, and it is the one part of this step that a worktree is required for. For any other shape:

   **Step 0 emits exactly five shapes**, and every one of them is dispositioned here. (The first version of this list named `SHAPE=branch`, which step 0 can *never* emit — a `--branch` claim records the main checkout, which resolves to `main-checkout` — and omitted `recorded` and `unresolvable`, both of which it can. A disposition table that names a value the producer cannot emit, and misses two it can, is not a table.)

   - **`worktree`** — item (b) above removed it. Nothing further.
   - **`clone`**, or **`discovered`** resolving to a clone — nothing to remove. A clone is an independent repository: it holds no ref in this repo's `HEAD`-per-worktree set, so it never blocks `git checkout <branch>` from main, and `git worktree remove` on it fails. Leave the directory; the collect in item 1 is what this branch needed. Its checkout is now stale relative to the merge, which is expected and is the consumer's to clean up.
   - **`recorded`** — a lock named a workspace but no `mode:`. Treat it as `clone`: collect, do not remove. The missing `mode:` is a malformed lock, worth saying out loud in the run's report, not worth halting a close over.
   - **`main-checkout`** — nothing to remove and nothing to collect; the work was done in the main checkout and its pending-docs are already where Step 4c looks. This is what a `--branch` claim produces.
   - **`unresolvable`** — a recorded workspace whose path could not be resolved at all. Nothing to collect and nothing to remove; **say so in the report**, because it is the one shape that means a doc may exist and this run could not reach it.
   - **no workspace found** (`<none>`) — the branch is already free for checkout.

   **Do not run `git worktree remove` on a shape that is not a worktree**, and do not treat its failure as the ISSUE-0016 remove-refusal: that guard's whole meaning is "a worktree carries an uncommitted file," and a clone failing the command carries no such claim. Misreading it downgrades an otherwise clean branch to SKIP for a reason that does not exist.

For **SKIP'd** branches (Step 2a verdict, dirty worktree), do nothing here — the worktree stays.
For **rejected** branches, leave worktrees in place (cleaned up in Step 6).

## Step 4: Merge & Land on Main

### 4-pre. Determine Merge Policy & Target

How approved work reaches `main` depends on the project's **merge policy** — read it from `<project>/CLAUDE.md § Merge policy` (the same "consumer declares its shape" pattern as Step 3's `§ Pre-merge verification`). Two values; **default `direct`** when the section is absent:

- **`direct`** (default) — feature merges, batch close, and doc consolidation land on `main` locally, then `git push origin <default branch>`. Correct for any project whose `main` accepts a direct push (no required status check, no `enforce_admins`). This is the historical flow; a consumer who never configured a merge policy keeps it with zero change.
- **`pr`** — `main` is never written directly; it is written only through a squash PR. Usually that means assembling everything on a throwaway **integration branch** cut from fresh `origin/<default branch>`, pushing it, and merging it into `main` through a PR — but when a single approved branch already *has* an open PR against `main`, the close lands on that branch instead (see the reuse probe below). Required when `main` is push-protected (a required CI check and/or `enforce_admins`) — a direct push would be rejected. GitHub becomes the sole serialized writer of `main`, which also removes the race against a concurrent auto-merge (e.g. Dependabot) landing on `main` mid-close.

Determine the **merge target** for the rest of Step 4 from the policy, and hold it as a value you write out at each later use — not as a shell variable. Every later reader is in a different fenced block, and nothing survives across one (`WORKFLOW.md` § 8.2a *Persistence boundary*); Step 4a's two merge commands are the readers that matter, and an empty operand there is a `fatal:` at best.

**`direct`:** the merge target is `main`.
```bash
git checkout <default branch>
```

**`pr`:** two shapes. Almost every run assembles on a throwaway **integration branch** (the default, below). One narrow case instead **reuses the approved branch's own open PR** — probe for it first, because cutting an integration branch there opens a *second* PR for content that already has one, re-runs the whole required-check suite on identical content, and orphans the first PR.

**PR-reuse probe (run first).** Reuse the existing PR when **all five** conditions hold:

1. **exactly one** branch is still approved **after Step 3b** — not merely after Step 2a. Step 2d can demote an approved branch to rejected ("Hold for fix") and Step 3b downgrades a branch to SKIP when its worktree refuses to remove, so the Step 2a verdict is not final. Reusing a branch this run decided *not* to merge would squash-merge it to `main`;
2. that branch has exactly one open, **non-draft, same-repository** PR whose base is `main`;
3. there are **no local-only `main` commits that the branch does not already contain** (`git rev-list --count origin/<default branch>..<default branch> --not "<approved branch name>"` is `0`). The sweep is the integration branch's job for commits that live *only* on `main`; a commit the branch already carries as an ancestor needs no sweep, because merging the branch lands it. The unqualified form of this condition (`git rev-list origin/<default branch>..<default branch>` empty) rejected that case, and the rationale it gave — *"there is nowhere to put those commits on a feature branch"* — is void precisely when they are already on it. **Measured both ways** on a branch updated by `git merge <default branch>`: unqualified `1`, `--not` form `0`. **One case the widening does NOT reach, stated because a reader will otherwise assume it does:** a branch updated by `git rebase <default branch>` instead is then *behind its own remote* by the pre-rebase commits, so **condition 4** rejects it whatever this condition says — measured `1`. The widening is reachable for a merge-updated branch and inert for a rebase-updated one;
4. the local branch is **not behind** its remote counterpart — otherwise the Step 4b/4c commits would land on a branch missing work someone else pushed to the PR, and the Step 4d push would be rejected as non-fast-forward;
5. the branch is **not behind `origin/<default branch>`**. Step 4a is skipped under reuse, so nothing rebases the branch onto the live base. The integration-branch shape exists partly to run the required checks against *current* `origin/<default branch>`; this condition is what replaces that guarantee, and without it a branch-protection rule requiring up-to-date branches yields `mergeStateStatus: BEHIND` and a refused merge.

**If anything other than exactly one branch is still approved, condition 1 already fails — skip the probe entirely and go to the integration-branch shape.** Otherwise:

```bash
git fetch origin <default branch>
# Substitute the literal branch name Step 2a approved and Step 3b left approved, here and
# in each of the two blocks that follow. Do NOT read it back from HEAD: the Rule A assert
# below has to compare HEAD against a value that did not come from HEAD (see the HARD
# RULE). It is written out rather than assigned to a variable because the later blocks
# could not have read the variable anyway (`WORKFLOW.md` § 8.2a *Persistence boundary*),
# and because an assignment sharing this block would cost the `gh` call its rule match.
# `--head` cannot be scoped to an owner (`gh pr list --help`: "<owner>:<branch> syntax not
# supported"), and GitHub allows several open PRs to share a head-branch NAME across forks.
# So filter to same-repository non-drafts and demand exactly one: `.[0]` on an unfiltered
# list can select a third party's PR, and merging that would land their code on `main`
# while reporting this run's work as merged.
#
# Run it BARE and read the number off stdout. Do NOT capture it into a variable: an
# allow-rule does not match past an assignment, so `PR_NUMBER="$(gh pr list …)"` routes
# to the classifier — and is auto-denied under `dontAsk` — despite `Bash(gh pr list:*)`
# being seeded. Every later step writes the number out as a literal for the same reason
# a variable would not survive anyway: nothing carries between fenced blocks (Phase 153,
# corrected Phase 169 — the boundary is the block, not the step).
echo "--- reusable PR number (nothing printed = none, which is the normal outcome):"
gh pr list --head "<approved branch name>" --base <default branch> --state open \
  --json number,isDraft,isCrossRepository \
  --jq '[.[] | select(.isCrossRepository == false and .isDraft == false) | .number]
        | if length == 1 then .[0] else empty end'
echo "--- local-only main commits NOT already on the branch (condition 3; must be 0 to reuse):"
git rev-list --count origin/<default branch>..<default branch> --not "<approved branch name>"
```

Read both values off stdout and carry them forward as **literals**. The `echo` labels are load-bearing, not decoration: without them the two outputs are positionally ambiguous, and a *missing* first value silently shifts the second into its slot — a bare `2` reads as a PR number when it is actually the commit count with no PR found. (`echo` is in Claude Code's documented built-in read-only set, so labelling costs nothing at the permission layer.)

**If the `gh pr list` output is empty, stop here — take the integration-branch shape.** That is the normal outcome, and it is also what an ambiguous result (two candidate PRs) deliberately produces. `/claim-task` feature branches are usually local-only under `pr` policy, so most runs have no PR to reuse. Do **not** run the remaining probes in that case — `git fetch origin <branch>` on a branch that was never pushed fails with `fatal: couldn't find remote ref <branch>`, which is alarming output on the *expected* path.

Only when a PR exists are conditions 4 and 5 worth checking:

```bash
# Substitute the approved branch name — the same literal you wrote into the block above.
# `$APPROVED_BRANCH` is EMPTY here: it was assigned in an earlier fenced block, and
# nothing survives from one block to the next even inside a single step (`WORKFLOW.md`
# § 8.2a *Persistence boundary*). This is not theoretical — it is what these three lines
# did on every run until Phase 169, and on this line it was invisible: `git fetch origin ""`
# exits 0 and prints a normal-looking `* branch HEAD -> FETCH_HEAD` while refreshing no
# remote-tracking ref at all. (The comment was accurate prose on an inoperative command.)
git fetch origin "<approved branch name>"; echo "--- fetch exit (MUST be 0):  $?"
echo "--- behind remote (condition 4; must be 0):"
git rev-list --count "<approved branch name>..origin/<approved branch name>"
echo "--- behind origin/<default branch> (condition 5; must be 0):"
git rev-list --count "<approved branch name>..origin/<default branch>"
```

**If the fetch exit is not `0`, take the integration-branch shape and do not read the two counts at all.** This replaces a claim that was measured false (Phase 169's round): a failed fetch does **not** make condition 4 print nothing. `refs/remotes/origin/<branch>` survives a failed fetch for any branch this clone has ever fetched or pushed — which is every branch with an open PR, i.e. every branch that can reach this probe — so both counts resolve against **stale** refs and print `0`. `0` and `0` is exactly the answer that takes the reuse shape. Measured: with `gh` reachable over HTTPS but git transport broken (expired SSH key, agent not loaded, SSH egress blocked — the ordinary way to be here, since total network loss stops you at the `gh pr list` probe), a branch genuinely **1 behind its remote and 1 behind `origin/<default branch>`** printed `0` for both. That is a squash-merge of work this run decided not to merge, in the one direction the whole step exists to prevent. The `$?` echo is the only thing that distinguishes it, so it is not optional.

Label the counts too, for a second reason: when *no* remote-tracking ref exists (a branch never pushed), condition 4 prints nothing while condition 5 still prints `0`, so an unlabelled block emits a single `0` that reads as "both are zero". The labels make an absent value visible as an absent value.

If a count **errors** or prints nothing, the conditions are unmet — take the integration-branch shape. That is the safe direction and it is intentional: this probe fails toward the flow that always works.

If the local-only count from the first probe and **both** counts above are `0` (and conditions 1–2 held, which is why you got here), take the **PR-reuse shape**:

```bash
# Substitute the approved branch name again. No `MERGE_TARGET=` assignment here: it
# would not reach Step 4a (a later block), and Step 4a now takes the merge target as a
# literal for that reason — see the note below.
git checkout "<approved branch name>"
# The PR number the first probe printed is the PR Step 4d merges; there is no
# integration branch this run. Write it out where Step 4d needs it — it is a literal
# from here on, because nothing carries between fenced blocks.
```

**Record the merge target for Step 4a as a literal**: under this shape it is the approved branch name you just checked out.

The policy's invariant is *"`main` is written only through a squash PR"* — landing the Step 4b/4c commits on the existing PR branch and merging that PR satisfies it exactly, with one fewer branch and one fewer CI cycle. Under this shape: **Step 4a is skipped** (the merge target *is* the one approved branch — there is nothing to merge into it), Step 4d pushes that same branch name and merges the PR number this probe printed instead of running `gh pr create`, and Step 6 has no integration branch to drop. Everything else in Step 4 is unchanged.

> **How often this actually fires.** Less often than it looks. Condition 3 fails whenever `/claim-task` made its `open → in_progress` flip on `main` (Step 4d) or Step 1b committed a `review_tasks.md` save — both commit to local `main` and neither is pushed — so the common single-branch cycle still takes the integration-branch shape. The reuse shape is for the case where the claim commits were already swept by a prior close and this cycle's only local-only work rode the feature branch, or where the branch was brought up to date with `git merge <default branch>` (condition 3's `--not` form, which is what makes that case reachable at all).
>
> **Falling through is not free, and the sentence that used to say so — *"falling through is never wrong, just wasteful"* — was measured false.** Taking the reuse shape when a condition is unmet is still the worse error, so keep probing rather than assuming; but the fall-through has a cost that lands on exactly one population: **an approved branch that has already been pushed.** Step 4a rebases each approved branch onto the merge target, and on a published branch that rewrites history someone else can already see. Reproduced end to end on a real remote: a branch in sync with `origin/<branch>` (`0 0`) came out of the fall-through **1 behind, 2 ahead** with a new tip SHA, and `origin/<branch>` was no longer an ancestor of anything being merged — so any PR tracking it points at commits the close abandoned, and the close opens a *second* PR for the same content. Step 4a's **Published** arm is what removes the rewrite: it merges the branch with `--no-ff` instead of rebasing it. That does not save the branch's own PR — `main` is written by a squash, so GitHub never marks it merged, and Step 6 then deletes the head branch, which closes it as *unmerged*. Step 4a item 3 says to comment on it first, and Step 8 names it either way.

**Integration-branch shape (the default — any condition above unmet).** Cut the branch off the **live** `origin/<default branch>` (so the PR's required checks run against the current base — an auto-merged commit may have landed since this run started), then sweep any local-only `main` commits onto it. Those commits are the `open → in_progress` claim flips from `/claim-task` Step 4d & `/auto-build` Step 5.4 and any Step 1b `review_tasks.md` save/rotation — all committed on `main` locally but never pushed, so the fresh branch does not carry them yet. At close time every local-only `main` commit belongs to this cycle; if you have unrelated un-pushed `main` work, resolve it before running `/review-close` under `pr` policy.

```bash
git fetch origin <default branch>
RUN_ID="$(date -u +%Y%m%dT%H%M%S)"
INTEGRATION_BRANCH="merge/review-close-${RUN_ID}"
git checkout -b "$INTEGRATION_BRANCH" origin/<default branch>
# No `MERGE_TARGET=` here — it would not reach Step 4a, which is a later block. The
# integration branch name IS the merge target; record it and write it out there. Echo it
# so the literal you carry forward comes off stdout rather than from memory:
echo "--- merge target for Steps 4a-4d:"
echo "$INTEGRATION_BRANCH"

# Sweep local-only main commits (claim flips + Step 1b doc saves) onto the branch.
# A range, applied oldest-first by cherry-pick itself — NOT a `for … done` loop over
# `git rev-list`, which would match no allow-rule (`for`/`done` are not documented
# command separators) and so be denied under `dontAsk`, leaving the claim flips off the
# integration branch while Step 6's `git reset --hard origin/<default branch>` later discarded them
# from local `main` as well (Phase 153).
#
# RUN THIS ONLY IF the local-only count you read in the Step 4-pre probe
# (`git rev-list --count origin/<default branch>..<default branch>`) was NON-ZERO. Unlike the loop it replaces,
# an empty range is not a silent no-op — cherry-pick hard-fails with
# `error: empty commit set passed`. You already have the number; skip the line if it is 0.
#
# A conflict means origin/<default branch> advanced over the same lines (rare — Dependabot touches
# deps, not tasks/index.yml); resolve it, or `git cherry-pick --abort` and re-cut the
# branch from local `main` instead.
git cherry-pick origin/<default branch>..<default branch>
```

> **HARD RULE — branch guard.** Steps 4a–4c run in the shared **primary** worktree, which has a single `HEAD`; a concurrent local actor can move it off the branch you expect mid-flow, landing commits on the wrong branch. Apply `_shared/main-push-guard.md` **Rule A** before **every** commit in Step 4. The assert's expected value must come from somewhere **other than `HEAD`** — comparing HEAD against a HEAD-derived value is a tautology that passes even after a hijack. By policy and shape:
> - **`direct`** — assert against the literal: `test "$(git rev-parse --abbrev-ref HEAD)" = "<default branch>"`.
> - **`pr`, integration-branch shape** — assert against the fixed **pattern**, which needs no remembered name: `case "$(git rev-parse --abbrev-ref HEAD)" in merge/review-close-*) : ;; *) echo STOP; exit 1 ;; esac`. Do **not** write `test "$(...)" = "$INTEGRATION_BRANCH"` when `$INTEGRATION_BRANCH` was itself recovered from `HEAD` (see the variable-persistence note below).
> - **`pr`, PR-reuse shape** — there is no fixed pattern to match, so assert against the **literal branch name Step 2a approved**, written out: `test "$(git rev-parse --abbrev-ref HEAD)" = "<approved branch name>"`. That name comes from the Step 2a verdict, not from HEAD, so the assert stays non-tautological. Never re-derive it with `git rev-parse --abbrev-ref HEAD`.
>
> On failure, STOP and reconcile via `git reflog` (cherry-pick your stranded commits onto the expected branch) — never commit blind. Per **Rule C**, **never** force-push `main`, the integration branch, or a reused PR branch.

> **Value persistence — every cross-block value in Step 4 is a written-out literal, and none is a variable.** Nothing survives from one fenced block to the next, *including two blocks under the same heading* (`WORKFLOW.md` § 8.2a *Persistence boundary*). This note previously said the values were "referenced in Steps 4a–4d" and told you to "re-export at the top of each later step". **Phase 169 replaced both halves — the first because it was wrong for the one variable that mattered, the second because it was the wrong granularity for all three.** The scope claim held for `$MERGE_TARGET` (read in Step 4a) and `$INTEGRATION_BRANCH` (read in Step 4d); it was false for `$APPROVED_BRANCH`, which was referenced in Steps 4a–4d exactly zero times — every use was here in Step 4-pre, in the two blocks *after* the one that assigned it — so a re-export-per-step remedy prescribed nothing for the only sites that needed it, and a Phase-164 sweep then cited this note as its warrant for excluding all six. They had been expanding empty on every run. So: **the merge target, the approved branch name, the integration branch name, the PR number, and the pre-plan/pre-exec HEADs are all literals, written out and quoted at every use site.** An unsubstituted `"<PR>"` fails loudly; an unquoted `<PR>` is a bash redirection, and an *empty* `gh` operand is the silent-wrong-merge case below. Where a value has a cheap re-derivation at the point of use, prefer it — a bare `gh pr list` probe at Step 4d, `git branch --list 'merge/review-close-*'` at Step 6.
>
> **Why the PR number in particular is never a variable.** `git` rejects an empty ref operand (`git branch -D ""` → `error: branch '' not found`), but `gh` **falls back to resolving the current branch's PR**: `gh pr view ""` and `gh pr merge ""` do not error, they silently act on whatever branch is checked out. Held in a variable across shell calls, an unre-exported one meant `gh pr merge ""` merged the current branch's PR, `--delete-branch` then moved HEAD to `main`, and the verdict probe `gh pr view ""` found no PR for `main` and reported a non-`MERGED` state — a stuck-PR report, and Step 6 skipped, **after a merge that landed**. Writing the number out *removes* that failure mode rather than guarding it: there is no variable left to go empty. Step 4d still re-derives the number from a bare `gh pr list` probe and stops if it prints nothing — keep both the probe and the stop.
>
> Through Steps 4a–4c, HEAD is the merge target, so a forgotten merge-target name is always recoverable with a bare `git rev-parse --abbrev-ref HEAD` — read it off stdout and write it out, rather than capturing it, and use it only as the `git merge` / `git checkout` / `git push` operand. Do **not** feed that HEAD-recovered value into the Rule A branch-assert (the HARD RULE above): asserting HEAD against a value just read from HEAD always passes, even after a hijack. For the assert, use the fixed `merge/review-close-*` pattern (integration-branch shape) or the literal Step 2a branch name (PR-reuse shape). `$RUN_ID` is never referenced as a *variable* past Step 4-pre — Step 4d's PR title slices the run id back off `$INTEGRATION_BRANCH`, which the same block re-derives from HEAD. It does reappear as *text* in Step 6's `git branch -D "merge/review-close-<run id>"`, and by then HEAD has left the branch, so read the name back with `git branch --list 'merge/review-close-*'` rather than trying to remember it. A lost `$RUN_ID` therefore needs no recovery anywhere; a lost *branch name* has a one-command lookup.

### 4a. Merge Approved Feature Branches

**Skip this step entirely under the Step 4-pre PR-reuse shape** — the merge target *is* the one approved branch, so there is nothing to merge into it. (Rebasing that branch onto itself is a no-op that reports "up to date", but running it invites the reader to treat a self-rebase as meaningful; go straight to **`4a-post`** — **not** to Step 4b. `4a-post` is not skipped with this step: under the reuse shape it is the *only* thing that verifies the tree the PR will squash, and skipping past it would land an approved branch on a protected `main` with nothing having run against it.)

For each approved feature branch (oldest first), merge it into the **merge target** Step 4-pre determined — `main` under `direct` policy, the integration branch or the reused PR branch under `pr`. Write it out at both use sites below: Step 4-pre is a different fenced block, so `"$MERGE_TARGET"` is empty here, and `git rebase ""` is a `fatal:` that aborts the close mid-merge.
1. **Is this branch published?** Answer it *here*, before anything moves — the rebase in item 2 is what the answer changes, and a rule an operator reaches after the command it governs is not a gate.
   ```bash
   # Substitute the branch name. A printed SHA means published; no output means local-only.
   #
   # The `case` guard is not decoration. Run literally, an UNSUBSTITUTED placeholder
   # prints `(local-only)` — `git rev-parse --verify --quiet` exits non-zero and silently
   # for a ref that does not exist AND for a name you forgot to write out, so the two are
   # indistinguishable, and the second falls into the in-place rebase, which is the arm
   # that damages a published branch. Verified by running exactly this line three ways:
   # published → SHA, local-only → `(local-only)`, `<branch>` unsubstituted → `(local-only)`.
   # Exit 3, on the same reasoning as Step 3c's placeholder guard: resolved nothing and
   # said nothing is the failure this whole step is about.
   case "<branch>" in
     *"<"*) echo "UNSUBSTITUTED branch placeholder — write the branch name out. STOP."; exit 3 ;;
   esac
   git rev-parse --verify --quiet "refs/remotes/origin/<branch>" || echo "(local-only)"
   ```
   A stale remote-tracking ref (pushed once, since deleted on the remote) also prints a SHA and so takes the published arm. That is the safe direction: the published arm's only cost is one throwaway ref.
2. **Merge — rebase-then-ff when the branch is local-only, `--no-ff` when it is published.** **If either path below conflicts, go to item 4 before running anything else** — item 4 routes the conflict and nothing between here and there knows one happened. Stated at the command rather than only at item 4: in written order an operator meets the merge first, which is the shape Phase 218's round caught one step over, where the rule sat 81 lines past the command it governed.
   - **Local-only** (the common case: `/claim-task` branches are usually never pushed under `pr` policy) — rebase, then fast-forward, exactly as before:
     `git checkout <branch> && git rebase "<merge target>"`, then
     `git checkout "<merge target>" && git merge --ff-only <branch>`
   - **Published** — **do not rebase it at all.** Check out the merge target and take the branch with a merge commit:
     `git checkout "<merge target>" && git merge --no-ff -m "merge <branch> (published — not rebased)" <branch>`
     Rebasing a published branch rewrites history the remote already has: measured, a branch sitting at `0 0` against `origin/<branch>` comes out **1 behind, 2 ahead** with a new tip, after which `origin/<branch>` is an ancestor of nothing this close merges and every PR tracking it points at abandoned commits. `--no-ff` leaves `<branch>` exactly where it was — measured `0 0` after the merge — while putting its **actual commits** on the merge target.
     **`-m` is not optional.** `git merge` decides whether to open an editor from whether stdin is a terminal, so the same command is silent in one context and blocks in another; `-m` removes the question. This is the same editor hazard the non-interactive `--continue` form below exists for, in a second verb.
     **Do not "simplify" this arm back to a rebase, in place or through a throwaway ref** — both were tried, both are measured above, and both cost more than the merge commit does. **The cost, stated:** the merge target gains a merge commit instead of a linear replay. Under `pr` that costs nothing on `main` — the integration branch is squash-merged, so its internal shape is discarded. Under `direct` the merge commit lands on `main`, which is a real departure from this step's ff-only history and is the price of not rewriting a published branch.
     **Why not rebase through a throwaway ref.** That was tried and **withdrawn by this phase's own review round**, which measured what it broke: the branch's own commits never become ancestors of the merge target, so Step 4c's merged-branch filter reads `rev-list --count <branch> ^HEAD` = **2** and classifies a successfully merged branch `NOT-MERGED` — holding back its pending-doc, never flipping its task to `done`, never dropping its lock — and Step 6's `git branch -d` then **refuses** on a branch the same step forbids `-D` for. `--no-ff` scores `0` on that filter and deletes cleanly, verified side by side on one fixture.
3. **A published branch's own PR does not survive this close, and nothing in it says so out loud.** The branch's commits reach the merge target, but `main` is written by a **squash** of the merge target, so GitHub never marks that PR merged. Step 6 then deletes the branch — `git push origin --delete <branch>`, which it runs for every branch this step merged — and deleting a PR's head branch **closes that PR as unmerged**. So the end state is a closed-not-merged PR for work that did in fact ship, with no comment explaining it. **Before Step 6 runs, comment on that PR pointing at this close's integration PR**, and carry the branch and PR number to Step 8's `Superseded PRs:` row either way. (Under the Step 4-pre reuse shape none of this arises: that shape merges the branch's own PR.)
4. If the merge conflicts, **route by which file conflicted** — do not abort reflexively. A conflict in one of the **Sysop-written shared append files** below is the expected multi-branch shape, not a reason to skip: resolve it per the next section — and for `tasks/index.yml`, its `validate_tasks.py` gate must pass before you `git -c core.editor=true rebase --continue`. Abort-and-skip (`git rebase --abort`, report the conflict, downgrade the branch to **4a-SKIP** per *When a branch really is skipped* below) is for conflicts you cannot resolve confidently — genuine code overlap you are not equipped to adjudicate, or a shared-file resolution the validator rejects. **The two arms abort differently, and the published one is the gentler.** Local-only: `git rebase --abort` returns the branch to its pre-rebase tip. Published: there is no rebase to abort — `git merge --abort` restores the *merge target*, and `<branch>` was never touched at any point, so nothing about it needs undoing. Either way the branch and its lock stay intact for the next cycle.

#### Sysop-written shared append files — the conflicts this skill causes itself

Two tracked files are appended to by *every* branch as a matter of workflow, so a conflict in them is prescribed rather than exceptional. **Never resolve either by stripping the `<<<<<<<`/`=======`/`>>>>>>>` markers and keeping both sides.** For an indented list that is exactly the resolution that corrupts silently — verified by repro, not reasoned:

- **`tasks/index.yml`** — `/document-work` **requires** a branch that surfaces a follow-up to file it here: its otherwise-blanket "do NOT modify `tasks/index.yml`" rule carries one explicit carve-out, *"Filing a NEW follow-up task entry (id + body file under `tasks/open/`) IS allowed and is required when the work surfaces a follow-up that Step 3b would otherwise hard-fail on."* `/add-task` appends here too. So two branches filing follow-ups in one cycle collide deterministically — this is a conflict Sysop's own workflow prescribes, not an edge case. Git splits the entry into **two separate hunks** — the `id:` line and the `body:` line — and leaves every field the two entries share (`title` when identical, `phase`, `status`, `effort`, `blast_radius`, `user_action`, `depends_on`, `surfaced_by`) *outside* the markers as common context. Strip the markers and you get one entry holding **`id:` alone** while the next entry absorbs the whole shared field block plus a duplicate `body:` key. `yaml.safe_load` accepts it, the ids stay unique, and the damage is invisible to a diff read.
- **`review_tasks.md`** — see the paragraph below, which predates this section and still governs.

**Resolve `tasks/index.yml` from the merge stages, structurally.** Both sides are complete files in the index; only the textual splice is broken. Stage numbering is the opposite of the intuitive reading during a rebase and was confirmed by execution, not recalled — **stage 2 is the merge target you are rebasing onto, stage 3 is the commit being replayed** (the feature branch):

```bash
git show :1:tasks/index.yml > "${TMPDIR:-/tmp}/sysop-base.yml"     # merge base — what the branch started from
git show :2:tasks/index.yml > "${TMPDIR:-/tmp}/sysop-ours.yml"     # merge target — has the other branches' entries
git show :3:tasks/index.yml > "${TMPDIR:-/tmp}/sysop-theirs.yml"   # this branch — has its own changes
```

Take the merge target's file as the base and append only the entries whose `id` it does not already carry, copying each new entry's block **verbatim** from stage 3. Do not hand-retype fields and do not reorder the target's existing entries.

**Union-by-id alone is not sufficient, and both gaps lose work with the validator green.** Before you apply it, diff stage 3 against **stage 1** (the merge base — present on a content conflict) and classify what the branch actually did:

- **The branch MODIFIED an existing entry** (a retriage, a `status`/`effort`/`blast_radius` change, a `deferred` move, an `/onboard` import rewriting the backlog). Union-by-id **discards that change wholesale** — the id is already present, so stage 3's version is never applied — and the result validates clean, because the merge target's file is internally consistent on its own. Re-apply each modified entry's fields onto the base by hand, or abort and 4a-SKIP. **Do not assume this cannot happen** because `/document-work` and `/add-task` are append-only: a task whose *subject* is the backlog legitimately rewrites entries on its branch.
- **Both sides added the SAME id** — the deterministic outcome when two branches auto-number from the same base. Union-by-id keeps one and **silently annihilates the other's task**. Renumber the incoming entry to the next free id, and **resolve its body file too**: `tasks/open/<ID>.md` conflicts `add/add` in this shape, and neither `validate_tasks.py` nor the shipped `pre-commit` scans for conflict markers, so staging it commits `<<<<<<<` into the task body with every gate green. Grep the branch for references to the old id before continuing.
- **The branch edited anything outside `tasks:`** — `phases:`, `schema_version:`, a sprint note. Taking the target's file as the base drops those too. A new phase plus a task filed into it surfaces as `task 'phase' N does not match any phases[].number`; **do not "fix" that by retyping the task's `phase:`**, which validates green while discarding the phase and silently reassigning the task.

Then, **stage the resolved file and gate it**:

```bash
git add tasks/index.yml
```

**before `git -c core.editor=true rebase --continue`**:

```bash
python3 sysop/scripts/validate_tasks.py
```

**The validator run is the load-bearing half of this recipe, and its placement is the whole point.** It catches the corrupting resolution precisely — a marker-stripped union reports `task 'phase' must be int or float, got NoneType`, the same for `title` and `status`, plus an orphan body file. But Step 4c is where the validator has always first run (`### 4c` step 4's `tasks/index.yml` block, and again at the end of Step 4c), which is *after* the merge and after Step 4b's `close_batch.sh` has already committed. Running it here means a bad resolution stops the rebase instead of being discovered downstream of two commits. **Never `--continue` past a red validator.**

**Read the exit code — `1` and `2` mean different things and take different actions.** `validate_tasks.py` returns **1** for schema errors (your resolution is wrong: fix it, or abort and 4a-SKIP the branch) and **2** for environment failures — missing PyYAML, a missing `tasks/` directory, an unreadable script. A `2` says nothing about the resolution, so **do not abort on it**: fix the environment (the script self-resolves venv PyYAML via its own `sys.path` bootstrap, but a `python3` with neither will exit 2 and say so) and re-run. Aborting on a `2` discards a correct resolution and downgrades an approved branch over a missing dependency.

**What this gate does and does not cover.** It validates `tasks/index.yml` only — `validate_tasks.py` has no knowledge of `review_tasks.md` whatsoever. A `review_tasks.md` conflict is resolved by reading both sides per the paragraph below and has **no automated gate**; do not let this step's green stand in for it. (Git does enforce one thing for free: `git -c core.editor=true rebase --continue` refuses while *any* conflicted path is unresolved, so a half-resolved commit is not reachable even though the two files are documented separately.)

Write the stage extracts to `"${TMPDIR:-/tmp}"`, not the repo root — `"${TMPDIR:-/tmp}/sysop-ours.yml"` and `"${TMPDIR:-/tmp}/sysop-theirs.yml"` — and delete them when the resolution is written. Nothing in the shipped flow stages untracked files, so a repo-root scratch file is not committed; but Step 1a deliberately skips the primary checkout, so one left behind is never surfaced and persists indefinitely. `${TMPDIR:-/tmp}` is the house convention (Phase 153 — `TMPDIR` is unset on most Linux shells, so the fallback is required and a drift guard enforces it) and removes the question.

#### When a branch really is skipped at 4a

A branch you abort-and-skip here is **4a-SKIP**, and it is a *different* verdict from Step 2a's `dirty` SKIP and from `rejected`. It is approved work that did not merge, and three later steps would otherwise treat it as merged. Record the branch name in that state and carry it to **Step 8's report**; Steps 4c and 6 each key on it explicitly. Its worktree was already removed by Step 3b and its pending-doc already copied to main's `sysop/runtime/pending-docs/` — neither is rolled back here, because Step 4c's merged-branch filter is what keeps that doc out of consolidation. Leave the branch and its lock intact so the next cycle can re-run it.

Feature branches MAY modify `review_tasks.md` — typically as single-line task-checkbox flips (`[/]` → `[x]`) that rebase clean. Structural conflicts arise when the merge target has moved `review_tasks.md` between branch-cut and rebase, in two common cases: (a) another already-merged batch added a sibling `### Batch N` section, (b) the project's archive-rotation script (e.g., `archive_review_tasks.py`) rotated rounds or batches out into a sibling archive file (committed by Step 1b — and, under `pr` policy, swept onto the integration branch by Step 4-pre). Resolve by reading both sides of the conflict: keep the merge target's structure as authoritative (it reflects the post-rotation / post-other-batch layout), then re-apply the branch's intent — checkbox flips and any net-new `### Batch N` section — in the new layout. Genuine code-overlap conflicts still surface here too; treat them the same way (resolve, don't abort).

### 4a-post. Verify the Merged Tree

**This is the gate whose green means something.** Step 3 ran the same resolved list against `main`; this runs it against the tree that is about to be pushed. Each approved branch was already verified *in its own worktree, at its own tip* — `/claim-task` Step 7e (its executor prompt's Sequence, item 5) and `/auto-build`'s execution-agent sequence (Step 7's prompt template, item 4b) both run the consumer's `## Pre-merge verification` gates there, which is why each of those says `/review-close` runs project-side verification "at merge time." What has never been verified anywhere until this step is the **assembled** result: the branches merged onto the live base and onto each other.

**Placed here on purpose — after the merges, before `close_batch.sh` and before doc consolidation.** A stop at this point consumes nothing. Step 4c deletes each pending-doc **it consolidated** — by name, from the set it routed, never by glob (its cleanup step says so explicitly, and a doc it held back or quarantined survives) — after routing that content into the shared docs, and those files are **untracked** — so the routed content survives only in 4c's commit. **Under `pr` that commit is on the merge target, which a failed close abandons** (the integration branch is re-cut from `origin/<default branch>` next run), leaving the content recoverable from a discarded branch or not at all. Under `direct` the commit stays on local `main` and the recovery below keeps it, so the window is a `pr`-shape window — which is every protected-`main` consumer, and the shape this repo runs. Verifying later would verify a slightly larger tree; it would also put that window under a failing gate.

1. **Re-resolve the command list** exactly as Step 3 did — the same numbered resolution order, first source wins. Re-read it rather than carrying Step 3's result forward as a remembered value: it costs one file read, and it removes the only way this step can silently run something other than what the consumer declared.

2. **Recompute the changed-file list on *this* tree** — the same command Step 3 ran, unchanged:

   ```bash
   git rev-parse --verify --quiet origin/<default branch> >/dev/null \
     && git diff --name-only origin/<default branch>...HEAD \
     || echo "NO_ORIGIN_MAIN"
   ```

   `HEAD` is the merge target now, so this is the assembled diff: every approved branch's contribution, plus — under `pr` policy's integration-branch shape — the local-only `main` commits Step 4-pre swept on. **Under `direct` it can be a superset**, and deliberately so: Step 4-pre is a bare `git checkout <default branch>` with no fetch, so `origin/<default branch>` may be stale and the range then also covers whatever landed upstream since your last fetch. That errs toward verifying more, which is the safe direction; do not "fix" it with a fetch here, because refreshing the base mid-close is Rule B's job at Step 4d and doing it early would silently change the tree you are about to gate. It is also what makes the consumer's `### Ratchet` snippets correct for the first time — each one filters `git diff --name-only origin/<default branch>...HEAD` on its own, and only on this tree does that command name the work being shipped. `NO_ORIGIN_MAIN` here means the same thing it means at Step 3: gate nothing, skip nothing, run the full list.

   **An empty list here is not a pass — it is a contradiction, and you must stop on it.** Unlike at Step 3, an empty list at this point says the merge target holds nothing `origin/<default branch>` does not already have, while Step 4a just reported merging approved branches. Something did not land: a rebase left the branch a no-op, a `--ff-only` merge was skipped after a conflict, or `HEAD` is not the merge target you think it is. Report it and reconcile before Step 4b — do not let a gate that executed nothing report green over a close that merged nothing.

3. **Run the list**, applying item 3's surface gate to *this* list. **Item 4's doc-only skip does not apply here.** It belongs to Step 3, which is allowed it because its green is not a verdict; this gate's green *is* the verdict, and "no file in the assembled diff carries a code extension" is not evidence that the consumer's declared list is unaffected — the same extension test calls build and lint configuration, dependency manifests, CI workflows and rule files documentation, and a full test suite can assert on prose. A consumer who wrote `### Always` wrote *always*, and `docs/getting-started.md` tells them a suite listed there runs "on the merged tree on every merge". So a doc-only assembled diff **still runs a consumer-declared list** (items 1–2). What it does not run is a command item 3's surface gate left unarmed — that gate still decides the auto-detected ones — or a `### Ratchet` snippet whose own filter comes back empty.

   **If the surface gate leaves nothing to run while the list still contains a code file, that is "ran nothing", not green** — it is item 5's case arriving late (no applicable command for a code-touching diff), so stop and ask the user what to run, naming the surfaces gated out and the unclaimed files. A gate that executed zero commands must never report the same as one that executed them and passed; that equivalence is the defect this whole step exists to remove, and surface-gating is the one way this step can re-manufacture it.

   **Count what you actually executed and report the number**, on Step 8's `Verification:` line (`ran on <merge target>: 3 commands`). A bare "ran" cannot be told apart from a run that resolved a list and executed none of it, which is the equivalence this whole step exists to remove — so the count is the evidence, not a decoration.

   **Zero commands on a doc-only assembled diff is a different case, and it reports rather than stops.** A consumer with no declared list and no armed surface has nothing for this gate to run and nothing to be asked about — halting every docs cycle after the merges would be a worse defect than the one above. Report it as `ran nothing` with the reason on Step 8's `Verification:` line; **never as `ran on <merge target>`**, which is what the line's earlier vocabulary forced, having offered only "ran" or "not reached". **Under `NO_ORIGIN_MAIN` neither of those two predicates is evaluable** — there is no changed-file list to hold a code file or not — so the full resolved list runs ungated per step 2, and if that list is empty because nothing was declared and no surface was detected, report `ran nothing: no origin/<default branch>, no declared list` and continue. Do not read an uncomputable scope as either a stop or a green. Everything Step 3 says about invocation still holds and is not restated: venv-aware re-invocation on `exit 127` / `ModuleNotFoundError`, the `!`-shell-escape route for a silently-denied command (never `AskUserQuestion`), and the read-only rule — no `pip install`, no state mutation, in a verification command.

   > **A command that could not be measured is neither a pass nor a failure — say so, and stop.** Every disposition above assumes the command *ran and answered*: it exited, and the exit code means something. A command killed by the Bash tool's timeout answers nothing. It gets no exit code you can read as a verdict — the harness reports the kill, not the program's own result — so the work it was checking is **unverified**, not verified-clean and not verified-broken. Report it on Step 8's `Verification:` line as `TIMEOUT: <command>` — deliberately the same token `/auto-fix` and `/auto-judge` put in their envelopes for the same event, so the three surfaces name one state one way — and then stop per item 4, because an assembled tree with an unmeasured gate is exactly what this step exists to refuse. **Do not silently re-run with a longer timeout and report the second result as the first**; raise the timeout, re-run, and report *that* it took two attempts. **Do not classify it as a failure either:** `failed` is a claim about the code, this is a claim about the measurement, and merging on one while reporting the other is how a green gate stops meaning anything. (The one shipped precedent agrees: `run_checks`'s accounting module classes its own subprocess timeout as `failed` and says why — *"work was lost, not declined"* — but it owns that subprocess and can tell a kill from an exit. This step does not.)

3a. **Run the Sysop pre-scan on the merged tree** (`Q-353`) — the promoted checks, at the one gate that can refuse a merge:

   ```bash
   bash sysop/scripts/run_checks.sh --mode both --fail-on-blocking
   ```

   **This is a Sysop-owned gate and it is deliberately NOT a fourth entry in item 1's resolution chain.** That chain stops at the first source producing a list, so a project with a `## Pre-merge verification` section never reaches auto-detect — and a pre-scan offered as one more source would therefore be invisible to exactly the consumers who already authored that section — everyone who has been running Sysop — because `install.sh` never rewrites a consumer's `CLAUDE.md` at all: the `--update` sweep skips it explicitly as *"the consumer's, not Sysop's"*, and the installer only ever **appends** sections that are absent. (A stronger guarantee than Phase 24b's managed-path preservation, which is scoped to `scripts/*` and `scripts/hooks/*` and does not reach this file — an earlier draft cited 24b, right about the conclusion and wrong about the mechanism.) It runs **in addition to** the consumer's list, after it.

   **What it closes.** `run_checks.sh` was invoked by `/codebase-review` Step 2b and `/security-audit` Step 2b and by nothing else, so the promoted checks — the `checks.yml` registry, the semgrep rules, the LSP and coverage stages this workflow exists to accumulate — ran only at **audit** time, which is after the branch that violated one has merged. The violation then surfaced on the next audit round as a new-vs-baseline finding, post-merge, at the gate `README.md` calls "the single human merge gate". The permission rules for this command have shipped in this skill's own allow-list and in `settings.json` the whole time; nothing bound them.

   **Three dispositions, and only one is a stop:**

   - **Exit 0** — **not automatically clean, and this is the disposition most likely to be reported wrong.** `--fail-on-blocking` keys on `failed` and on new blocking findings; it does **not** key on **`degraded`** — `run_checks/accounting.py`'s third status, *"ran, but over less than its declared inputs"*, which Phase 189 decided must not block. A run in which a `blocking: true` stage saw a fraction of its inputs exits **0** with zero findings, and a zero from a degraded stage is not a real zero. Read the accounting header before reporting: `pre-scan: clean` only when no blocking check is `degraded`; otherwise `pre-scan: clean, but N blocking checks degraded — <ids>`, and continue. **Not hypothetical** — the one consumer that enforced these checks at its merge gate before this step existed wrote a wrapper *because* `run_checks.sh --mode both --fail-on-blocking` exited 0 over sixteen degraded semgrep checks.
   - **Non-zero** — read the accounting header before reporting, because `--fail-on-blocking` fails on **two different things** and Phase 135 exists to keep them apart (a third status, `degraded`, does not fail at all — see the Exit 0 arm above): a **new blocking finding** (a `blocking: true` check produced a finding not in `.claude/checks_baseline.txt`), or a **`failed` blocking stage** (the check's tool crashed, so a green gate over it would be a lie). Report which, with the check id: `pre-scan: FAILED — new blocking finding <check-id>` or `pre-scan: FAILED — blocking stage did not run: <check-id>`. Both stop, per item 4. They are not the same defect and must not be reported as one.
   - **The environment cannot run it — a fourth arm, and its absence was a real gap** (the round's execution lens reproduced three shapes). `python3` on `PATH` without PyYAML exits **2** with `ERROR: run_checks requires PyYAML`; a partial `sysop/` install where the wrapper survives but `run_checks_impl.py` does not exits **2** with `can't open file`; a missing `.claude/checks.yml` exits **1** with `Error: … not found`. **None of these produces an accounting header or a check id**, so the non-zero arm above — which tells you to read the header and name the id — has no valid report shape for them, and the step forbids fabricating one. Recognise them by the absence of the `checks: N executed / N skipped / N failed` header: report `pre-scan: could not run — <the tool's own first error line>` and **continue**. This is an environment fault, not a verdict on the work, and halting an assembled close on one is the `TIMEOUT` mistake in a different costume — *"a claim about the measurement, not about the code."* Say plainly in Step 8 that the promoted checks did not run.

   - **The script is absent** (`sysop/scripts/run_checks.sh` does not exist — a partial or pre-`sysop/`-namespace install) — report `pre-scan: skipped — sysop/scripts/run_checks.sh absent` and continue. **Never fabricate the scan or hand-roll a substitute**; a cautious agent that replaced this runner with its own grep once read **none** of a ~974-finding pre-scan, reporting **24** tasks where the reference cell reported **372** (Phase 136).

   **De-duplication — does any resolved command REACH the pre-scan, directly or through a project wrapper?** If one does, this step does not run it again: report `pre-scan: ran via the consumer's list`. **A resolved command only counts if it can actually refuse.** `run_checks.sh` **without** `--fail-on-blocking` exits 0 on any finding, so a consumer whose `### Always` lists the bare form has a scan that reports and never blocks — and `install.sh`'s own post-install footer prescribes exactly `bash sysop/scripts/run_checks.sh  # smoke-test the check registry`, so this is the form a consumer is most likely to have copied. Treat a flagless invocation as **not** de-duplicating: run this step's own gated scan anyway and report `pre-scan: consumer's list runs an ungated scan — ran the gate as well`. **Ask that question, not "does a command contain the string `run_checks.sh`".** A name match is the obvious rule and it is wrong on the live case: the one consumer that already enforced these checks at its merge gate lists `bash scripts/run_checks_gated.sh --mode both --fail-on-blocking`, a **project-owned wrapper** around `sysop/scripts/run_checks.sh` written to add the `degraded` handling the flag does not do — so a name match sees no pre-scan and runs a **second whole-tree scan on every close**, the exact double payment this rule exists to prevent. When a resolved command is a project script you cannot classify by name, read it; one `grep -l run_checks` over the resolved commands' script files answers it. **Flags never enter the decision:** a consumer who wrote `--mode quality` narrowed the scan on purpose, and re-running at `--mode both` would overrule a choice `WORKFLOW.md` § 6.1 invites them to make.

   **No doc-only skip here, and the filing that asked for one was wrong about the step it lands in.** `Q-353` proposed gating this "like Step 3's surface list so a doc-only close does not pay for a whole-tree scan". Item 3 above already refuses that reasoning for this pass, and it refuses it *harder* for a pre-scan than for a test suite: the extension test classes `checks.yml`, semgrep rule files and CI workflows as **documentation**, and those are precisely this scan's own inputs — so the one diff shape the proposed gate would skip includes every change that alters what the checks *are*. The cost is real and it is a whole-tree scan on every close; it is paid here rather than gambled.

   **`NO_ORIGIN_MAIN` does not reach this step** — also contrary to the filing, which asked for that rule to be inherited. It governs a **range**, and this scan takes none: it reads the working tree and the baseline file. There is nothing here for an uncomputable diff scope to narrow, so there is nothing to fail open.

4. **On failure, stop.** Nothing has been pushed, `close_batch.sh` has not run, and no pending-doc has been consumed. Report the failing command with its output. Recovery is per merge policy:
   - **`pr`** — the merges are on the merge target, unpushed. Fix the failure, then re-run `/review-close`: a `pr` run cuts a fresh integration branch from `origin/<default branch>` every time, so the abandoned one costs a `git branch -D` and nothing else. Under the PR-reuse shape there is no branch to abandon — the extra commits simply stay local until a later run pushes them.
   - **`direct`** — the merges are on local `main`, unpushed. **Do not `git reset --hard`**: that discards the claim flips and the merges together, and neither is recoverable from `origin`. Leave `main` as it stands. Those commits are now exactly the *unpushed main commits* category Step 1 already enumerates, so once the failure is fixed the next `/review-close` picks them up — and that run's Step 3 verifies them for real, because by then they are on its own tree.

5. **Confirm the gate left the tree clean**, before Step 4b asserts it:

   ```bash
   git diff --quiet HEAD -- && echo "CLEAN" || echo "DIRTY — verification modified tracked files"
   ```

   A formatter, a regenerated lockfile or a rewritten snapshot can leave tracked files modified. Step 4b's landing check is `git diff --quiet && git diff --cached --quiet`, so those modifications would surface there as a *close-batch commit that did not land* — a true report of the wrong cause. On `DIRTY`, resolve it project-side; do **not** fold the modifications into the close's commits. (Untracked build output is not at risk and does not trip this — `git diff` does not see it.)

   > **`DIRTY` here has a second cause this message does not name: a Step 2b agent.** The convention agents run five steps earlier and are contained only by a prompt rule and, where the harness offers it, worktree isolation — both of which have been measured failing. If Step 2b's own delta assertion was run, this cannot be the cause and the message above is right; if it was skipped, check that first, because the project-side remedy for a formatter is the wrong action for a stray agent edit and will commit it.

**Under the Step 4-pre PR-reuse shape this step still runs**, even though Step 4a was skipped there. The merge target is the approved branch and it is checked out, so step 2's command returns that branch's own diff against `origin/<default branch>` — which is exactly the tree its PR will squash.

> **This is the gate `_shared/main-push-guard.md` Rule B re-runs, and Step 3 is not.** When Rule B's rebase-first arm fires at Step 4d because `origin/<default branch>` advanced mid-run, the base underneath the merge target changed, so the verdict *this* step produced no longer describes the tree being pushed. Re-run this step. Re-running Step 3 would answer a question nobody asked: its tree is not the one that moved.

### 4b. Close Merged Batches

After all branches are merged and `4a-post` reported green, but **before** doc consolidation.

**Determine the batch set first — this step never said where `<N1> <N2> <N3>` come from.** The set is the review batches whose branches step 5 actually merged this run, and **the source is `review_tasks.md`**, read through `python3 sysop/scripts/review_index.py --list` — which prints every batch with its status and its branch, tab-separated. Intersect that branch column with the branches step 5 merged.

**The locks corroborate; they do not define the set.** `batch_work.sh` writes `sysop/runtime/locks/BATCH-<N>.lock` carrying `task_id: BATCH-<N>` and the `branch:` it claimed, and `close_batch.sh` removes it at close — so a lock is good evidence a batch is in flight, and worth cross-checking against. But **a merged batch with no lock is an ordinary state, not an anomaly**: `close_batch.sh` says so in its own words when it finds none — *"claimed before batch locks shipped, or already released"*. Deriving the set from locks alone therefore drops exactly those batches, and because the empty-set arm below then fires, the close reports `none this cycle` over a batch left `Pending` with its boxes open. That trades this step's old failure — a loud halt — for a silent false record, which is the worse direction. **Where the two disagree, `review_tasks.md` wins and the discrepancy is reported.**

Two lock shapes to be aware of when cross-checking, because both fail quietly: two locks naming the same branch both match, and a lock whose free-text `notes:` tail carries a second column-0 `branch:` line is read differently by a `grep`-style reader (first wins, or nothing) than by PyYAML (last wins). Neither is a reason to prefer locks as the source; both are reasons the corroboration step reports rather than resolves.

**Do not read `review_task_ids` for this.** It is the obvious-looking candidate in the pending-doc frontmatter and it is the wrong namespace — it holds `TASK-NNNN` ids from `review_tasks.md`, and `close_batch.sh` takes a batch number — bare, zero-padded, or the `BATCH-<N>` form, and nothing else. Verified by running it rather than reasoned about: `BATCH-1` is accepted (the prefix is stripped), while `close_batch.sh TASK-0001` is rejected at **argument parsing** — `❌ Unknown argument: TASK-0001`, exit 1 — so it never reaches a batch lookup at all. "It takes integers" is the tempting shorthand and it is wrong in the direction that matters, because it implies the `BATCH-` form fails too. Three shipped sites already say so, which is why this is a convergence and not a new rule: Step 4c's routing note (*"`review_task_ids` is documentary only and never consulted here"*), `/document-work`'s two-namespace section, and `close_batch.sh`'s own `remove_claim_artifacts()` comment (*"Step 4c has no batch-id list to iterate"*).

**The empty set is the ordinary case, not an edge case, and it has its own arm — but it must be *derived*, never inferred from absence.** A `/claim-task` single-task cycle carries no review batch at all, which is the dominant path rather than a corner of it. **Empty means `review_index.py --list` named no batch whose branch step 5 merged** — a positive reading of the authoritative file. It does **not** mean "no locks were found": that is the false-empty above, and it turns a missed batch into a clean-looking report. **And it does not mean the reader failed to run** — that is a second false-empty, arriving by a different route. `review_index.py --list` exits **0** whether it names batches or names none, so the exit code is a discriminator that stdout alone cannot be: exit `0` with no lines is a *measured-empty* set, and **any non-zero exit is a could-not-measure, never an empty set.** **Read the exit code before you read the lines.** On any non-zero exit, report it and **STOP** — do not take the empty arm below. A batch the reader could not name is left `Pending`, its task boxes open and its lock in place, while this step reports success.

**The reader now states its own verdict, and that line is what the empty arm keys on (`Q-371`).** `--list` writes one line to **stderr** on every run — `review_index --list: read review_tasks.md (<N> lines); <M> batches listed.` — because stdout is a machine format in which a batch-free tracker is legitimately zero bytes, and a run that produced zero bytes could not be told from a run that never happened. **Absence of that line is a could-not-measure, exactly like a non-zero exit.** It also closes a **second route** into the incomplete-answer state the paragraph below names: a `### Batch` header the strict pattern rejects is reported by nothing — no row, no error — so the tracker plainly declares a batch and the list is silently short. `--list` now names the file and line for each such header (balanced-fence examples excluded, since those are documentation and not tracker content), **at two levels, and the level is the disposition**. `WARNING:` when the list came back **empty** — an empty set plus a visible batch header is a false empty, so this is a could-not-measure and it halts, exactly like the duplicate-number rule below. `NOTE:` when batches *were* listed — the answer may be short, so cross-check the branches step 5 merged against the rows before continuing, but do **not** halt: a near-miss spelling is tolerated elsewhere on purpose (`close_batch.sh` closes such a batch anyway through its permissive twin), and treating it as a hard stop would make one legacy header block every future close of unrelated work.

**Exactly two exit codes are reachable from `--list`, and the enumeration matters because an earlier draft of this paragraph got it wrong.** `0` (it ran) and `1` (`review_tasks.md` not found) — plus `2` from a wrong command word, which is how this arm's own defect presented. The script's other refusal arms (`3`, `5`, `6`) sit behind `--check-duplicates`, `--check-fences` and `--check-headers`; **`--list` itself refuses nothing**, and this step does not prescribe those flags.

**So exit `0` means the reader ran — NOT that its answer is complete, and this is the third state.** `--list` keys batches by number, so a tracker declaring the same batch number twice reports **only the last**, silently, at exit `0`. Measured: a fixture with a real `Batch 7` and a duplicate `Batch 7` printed one row — the duplicate — and the real batch's branch was simply absent from the output. **The only signal is a `WARNING:` line on stderr**, which a caller reading stdout for tab-separated rows never sees. So: **capture stderr as well, and treat any `WARNING:` as a could-not-measure** — same disposition as a non-zero exit, stop and reconcile the tracker. If the dropped batch is the one step 5 merged, the intersection is empty, this step takes its empty arm, and `close_batch.sh` is never called for it — which is precisely the silent false close this arm exists to prevent, arriving at exit `0`. When the set is genuinely empty: report the one line

```
4b: no review batches this cycle
```

run nothing, and **skip the landing gate below** — go straight to Step 4c. Running the script anyway is not the escape: with no operands it exits 1 on `❌ No batch numbers provided.` and commits nothing, so an empty set has no shape in which this step succeeds. The gate looks for a `docs: close Batch …` tip that a zero-batch cycle never produces and never will, so applying it here halts a healthy close permanently, *after* step 5's merges have landed on the integration branch, which is the expensive place to stop. It also stops the compliant agent specifically: the operator who infers a no-op gets through, and the one who follows the step as written does not. Naming the did-not-run state rather than falling silent is the shape Step 2b's `N skipped (doc-only)` and `4a-post`'s `ran nothing: why` already use.

With a non-empty set:

```bash
# Substitute the merge target Step 4-pre recorded — the integration branch name
# under `pr`, the approved branch under PR-reuse, `main` under `direct`. Write it
# out as a LITERAL: Step 4-pre is a different fenced block and `"$MERGE_TARGET"`
# is empty here (`WORKFLOW.md` § 8.2a *Persistence boundary*).
bash sysop/scripts/close_batch.sh --merge-target "<merge target>" <N1> <N2> <N3>
```

This script updates `review_tasks.md` on the checked-out branch (the merge target — it resolves the repo via `git rev-parse --show-toplevel`, so it commits to whatever branch is current): sets batch headers to `Merged`, marks task checkboxes `[x]`, updates the Statistics table, and adjusts the Grand Total counts. **One exception:** a task annotated `> Failed:` anywhere in its own block keeps its checkbox and is left out of both the flip and the counts. **The block is the task line plus the indented lines under it**, because `/codebase-review` and `/security-audit` emit a two-line task (checkbox + indented `file:line` + provenance) and the annotation lands below that — the one-line reading this sentence used to state was why the protection could not fire at all — a FAIL verdict means the work was attempted and not finished, so the batch closes as "shipped, minus these" (Phase 157). Expect the per-batch line to read `(3 tasks closed, 1 failed — still open)` when that happens. One commit is created for all closed batches.

**`--merge-target` is not optional under `pr`, and `--force` is not its substitute** (Phase 248, `Q-308`). The gate asks whether the batch branch's work landed in what this close is landing. It used to answer that by INFERRING the target from `HEAD`, and that inference is unsound in both directions — **both defects were measured on fixtures built from this step's own commands, and both are now guarded by `tests/test_close_batch_merge_target.py`**:

- **It accepted work that reaches nothing.** A branch cut FROM the batch branch, with its own commits on top, strictly contains the batch branch — so the gate printed `✓ verified merged` and flipped the header, while nothing established that `HEAD` reaches `main`. On Step 4a's **local-only (`--ff-only`) arm** — the common case in that step's own words — a legitimate integration branch and that scratch branch agree on **every** ancestry column a local check could consult, first-parent reachability included. (On the **published `--no-ff`** arm first-parent does separate them; a predicate right on one of Step 4a's two arms and wrong on the other is not a gate.) That is why the repair is to state the target rather than to narrow the test.
- **It refused work that landed correctly, on the dominant path, every run.** Step 4a merges a local-only branch with `git merge --ff-only`, which moves the merge target **to the branch tip** — so the target and the branch share a SHA for the LAST branch merged, and for the ONLY branch of a single-branch cycle. Strict SHA containment skipped its arm there and `main` refused. **The two paragraphs previously here asserted the opposite** ("the gate passes with no `--force`", "measured"); the measurement behind that claim was taken on a fixture with an extra commit after the merge, which is not the shape this step produces.

So the target is now something you **state**, and `HEAD` is never read for it. Pass the literal Step 4-pre recorded. Identity between target and branch is compared by resolved **ref name**, not by SHA: after an ff-merge they legitimately share a SHA while being different refs, and standing on the unmerged branch itself they are the same ref.

**What each Step 4-pre shape passes.** The gate itself is still `git merge-base --is-ancestor <batch branch> <merge target>`; what changed is where the second operand comes from, and that identity is checked by ref name before it runs. *Integration-branch shape:* `--merge-target <integration branch>`; the gate accepts every branch Step 4a merged, ff or `--no-ff`, and you **no longer need `--force` for the ancestry reason**. *PR-reuse shape:* the merge target **is** the one approved branch, so target and branch resolve to the same ref, the target arm is withheld, and **reuse still needs `--force`** — before the PR squashes there is genuinely no ancestry evidence that the work landed, which is what Step 6 says in its own words: *"After a squash there is no ancestry-shaped containment test."* *`direct`:* the target is `main`, which is also what the script resolves on its own from `§ Merge policy`, so the flag is redundant there — pass it anyway for one shape at both policies.

> **If a batch skips with `unmerged`, that is a real verdict — read it before overriding it.** It means the batch branch is an ancestor of neither the stated merge target nor `main`, i.e. Step 4a did not merge it. Fix that rather than forcing past it. **If the script reports `merge target: UNRESOLVED`, you omitted the flag under `pr` policy** — that is not a reason to reach for `--force`, which would disarm the cherry-pick detection for every batch in the run; supply the target. The one legitimate override is below: work that reached the target by **cherry-pick** rather than merge is genuinely not an ancestor, and `--force` is its documented escape.

If any branches were cherry-picked instead of rebased+merged (e.g., because worktree removal wasn't possible), use `--force` to skip the merge-base ancestry check:

```bash
bash sysop/scripts/close_batch.sh --force --merge-target "<merge target>" <N1> <N2> <N3>
```

**Verify the close-batch commit landed before proceeding — non-empty batch set only.** The script wraps its `git commit` in explicit failure handling (Phase 33 / BeanRider ISSUE-0015), but trust-but-verify: confirm a `docs: close Batch …` commit is the new tip and the working tree is clean before continuing to Step 4c. **If the batch set was empty this gate does not apply and was already skipped above** — it asserts the result of a command this cycle correctly did not run, so reaching it with no batches is a reading error, not a failed close.

```bash
git log -1 --pretty=%s | grep -q '^docs: close Batch ' && git diff --quiet && git diff --cached --quiet
```

If the check fails **on a non-empty batch set** (no `docs: close Batch …` tip, or `review_tasks.md` is still modified/staged): the close-batch commit did NOT land. **Halt before Step 4c** — proceeding would fold the close-batch edits silently into the doc-consolidation commit instead of their own atomic commit, and ordering ("after merge but before doc consolidation") is broken. Inspect the script's stderr output (most commonly a pre-commit-hook failure — see Step 4d's venv-prefix pattern). The script's terminal `── close_batch.sh completed — close-batch commit present: N` line (Phase 43a / BeanRider ISSUE-0039) survives tail-truncation and tells you whether the script aborted silently (line absent) or completed with no commit landed (`present: 0`). Two recovery paths, in order:

1. **Re-run the script** with the same batch list. It re-attempts the commit, and **the mechanism is worth knowing, because for a long time it did not** (`Q-364`): the failed run left every requested batch reading `Merged` in the working tree, so the re-run's status check skipped each one as `already-merged` **before** reaching the commit block — which is gated on a non-empty closed set. Reproduced by blocking the commit with a failing `pre-commit` hook: the first run flipped and failed, and the re-run reported `Skipped: 1:already-merged` and `close-batch commit present: 0`. The script now asks a second question of each already-`Merged` batch — *is it `Merged` in `HEAD` too?* — and a batch that is `Merged` in the tree but not in the last commit is an **interrupted close**, not a finished one, so its commit is re-attempted and the summary reports `Commit resumed for: <N>`:
   ```bash
   bash sysop/scripts/close_batch.sh --merge-target "<merge target>" <N1> <N2> <N3> 2>&1
   ```
   Read the full output in the tool result — a missing terminal line is then unambiguously visible. **Do not pipe it through `tee`** (this step used to, into a bare `/tmp` path): `|` is a documented separator, so the tail becomes its own invocation, `tee` is not in the harness's read-only set and binds no shipped rule, and the prompt lands *after* the close has already run.

2. **If re-run still doesn't commit**, commit by hand with the canonical subject — same form the script would have used — and proceed. **Two reachable causes, and the second is by design:** the script aborts after the `git add` (the original cause, review_tasks.md staged and uncommitted); or it could not read the batch from `HEAD` at all, in which case it says so — `Could not read this batch from HEAD, so an interrupted-close resume cannot be offered` — and skips rather than guessing. That refusal is deliberate: it would otherwise land `docs: close Batch <N>` for a batch nobody closed. **A resume commits the INDEX and does not re-stage** — the failed run's own `git add` already put the flip there, so an unrelated working-tree edit made *between* the two runs stays uncommitted; if nothing is staged, the resume refuses rather than take the worktree copy. **That guarantee covers the resume path only.** An ordinary close still runs `git add -- review_tasks.md` and takes the whole file, so an unrelated edit already sitting in `review_tasks.md` when you run the script is committed with the close. That is long-standing behaviour, not changed here, and it is the reason to look at `git status` before closing on a dirty tracker.
   ```bash
   git add review_tasks.md && git commit -m "docs: close Batch <N1>, <N2>, <N3>"
   ```
   Step 4c is safe once a `docs: close Batch …` commit is the tip.

**Do NOT remove completed batches** — they will be archived during the next `/codebase-review` run.

### 4c. Consolidate Pending Documentation

After all branches are merged but **before** pushing:

1. **Scan for pending docs**: `ls sysop/runtime/pending-docs/*.md 2>/dev/null`

   > **One entry in that glob is not a pending-doc, and consolidating it destroys something.** `convention-candidates.md` is a fixed-name file `/codebase-review` and `/security-audit` write, append to each other's copy of, and delete themselves at their own Step 9; it carries no `branch:` frontmatter and belongs to no branch. **Exclude it by name** — it is the shape the "no `branch:`" rule below reads as benign, so consolidating it routes nothing (no `type`, no `roadmap_ids`) and then deletes an open review round's candidate list. Do **not** quarantine it either: `/codebase-review` Step 9 reads it back at that exact path and would silently report "no candidates". Leave it where it is. `quarantine/` is a subdirectory, so this non-recursive glob does not reach it — that is deliberate, and it is why it is a subdirectory rather than a suffixed `.md` file, which every reader of this glob would pick up as a second doc.

1b. **Drop any pending-doc whose branch did not actually merge — this gate decides task state, so it must not run on an unmerged branch's doc.** Step 3b copies each approved branch's pending-doc into main's `sysop/runtime/pending-docs/` *before* the merge is attempted (that ordering is deliberate — it is what stops `git worktree remove` from destroying the doc). So a branch that is approved, has its doc collected, and then **fails to merge at Step 4a** leaves a doc here that this step would otherwise consolidate — routing its content to the shared docs, flipping its `roadmap_ids` to `status: done`, `git mv`-ing the body to `archive/`, and dropping the task's lock and parked markers, **with the code never merged**. Step 3b's own rollback (its step 2b) covers only the case where *it* skips a branch, and says so; nothing covered a 4a-SKIP until this filter.

   For each file found in step 1, read its `branch:` frontmatter value and keep it only if that branch is contained in the merge target:

   ```bash
   git rev-list --count "<branch from frontmatter>" "^HEAD"
   ```

   **`0` means merged; any non-zero count is the branch's unmerged commits.** `HEAD` is the merge target here, and a **rebased-then-ff-merged** branch is fully contained in it, so the count is `0` for a branch that landed *that* way under either policy. **A `--no-ff`-merged branch scores `0` too** — that is Step 4a's *published* arm, added in Phase 219: its commits go onto the merge target unchanged, so `^HEAD` reaches them. Both shapes are contained. The one shape that is **not** is a rebase onto a throwaway ref, where the branch's own commits never join the target and a perfectly merged branch scores `2` — measured, and the reason that mechanism was withdrawn rather than shipped — **exercised by a test for `direct` ff-merge only**; the `pr` integration branch and PR-reuse shapes are reasoned from the same ancestry property, not built. (The previous version of this paragraph claimed all three were verified, and its drift guard asserted the same three while building one. Do not restore the stronger wording without the two missing fixtures.) **This test is valid only pre-squash.** It is an ancestry test, and a squash breaks ancestry — so it must not be reused after the PR merges (see Step 6, where an earlier draft did exactly that and shipped a check that could never pass).

   > **It is an ancestry test, so a CHERRY-PICK breaks it too — and Step 4-pre prescribes one.** An earlier version of the paragraph above said the count is `0` for *every* branch that landed under either policy. That is false, and the drift guard pinning it asserted "all three merge shapes" while building only a `direct` ff-merge. Cherry-picking rewrites commits, so the tip is not an ancestor even when the content is fully applied — measured: with the merge target diverged, a picked range of 2 commits scores `2` while `git cherry` reports `0` unapplied; a rebase-then-cherry-pick scores `1`; and an **empty** cherry-pick (content already applied, `git diff --quiet <branch> HEAD --` reporting the trees *byte-identical*) still scores `1`. Only the prescribed rebase + `merge --ff-only` scores `0`.
   >
   > **The shape that actually bites is not an operator improvisation — it is `main` itself.** Step 4-pre's `pr` policy moves local-only `main` commits onto the integration branch with `git cherry-pick origin/<default branch>..<default branch>`, and `/document-work` supports running on `main`, which writes a pending-doc whose frontmatter is `branch: main`. Step 1 above is a bare `ls`, so it picks that doc up, and this filter then classifies it `NOT-MERGED` on **every** `pr`-policy close — while its content is provably in the merge target. **It does not hide.** A cherry-pick scores `0` only in the degenerate case where it reproduces the *identical SHA*, which needs the picked commit to land on the **same parent** it originally had **and** to carry the same committer timestamp. `git cherry-pick` stamps the committer date at **pick** time, and the commits Step 4-pre sweeps are `/claim-task` Step 4d flips and Step 1b `review_tasks.md` saves made minutes to days earlier — so the timestamp condition is essentially never met on this path, and the same-parent condition alone is not enough. Measured on a realistic five-minute-old local `main` commit: `rev-list --count` `1`, `git cherry` `0` unapplied. The `0` outcome is confined to a pick made inside the same clock second as the original commit, which the close path does not produce. **Expect this on every `pr` close that has local-only `main` commits to sweep**, not occasionally. Under `pr` the cost is usually a one-cycle deferral rather than a loss, because Step 6 resets local `main` to `origin/<default branch>` and the doc consolidates on the next close — but only if there *is* a next close, and nothing reports the deferral meanwhile.
   >
   > **So do not trust a non-zero count on its own. Fall back before you skip — but resolve the ref first.** The stop-and-ask below (*"if `branch:` is absent or the ref no longer resolves"*) governs this fallback too, and it is written *after* it, so apply it *before*: `git rev-parse --verify "<branch from frontmatter>^{commit}"` must succeed. If it does not, go straight to that stop. **A `fatal: unknown commit` leaves the pipeline printing `0`**, and `0` is this test's *merged* answer — so an unresolvable branch would read as "content is in the merge target" and get its doc routed, its task flipped to `done` and its lock dropped, which is the precise loss this filter exists to prevent.
   >
   > ```bash
   > git rev-parse --verify "<branch from frontmatter>^{commit}" >/dev/null || echo "ref does not resolve — go to the stop-and-ask below, do NOT read the count"
   > git cherry HEAD "<branch from frontmatter>" | grep '^+' | wc -l
   > ```
   >
   > **Count with `grep '^+' | wc -l`, never with `grep`'s own `-c` flag.** That flag exits **1** when the count is zero — and zero is the *pass* value here — so the prescribed form would return a failing status on the good outcome, abort under `set -e`, and never fire the right-hand side of an `&&` chain. Verified: the `-c` form prints `0` and exits `1`; `grep | wc -l` prints `0` and exits `0`. This is the `|| true`-class trap `_shared/permission-guard.md` already names, in a command whose exit status is read in exactly the direction that inverts it.
   >
   > `git cherry` compares **patch-ids** rather than ancestry, so it sees through a cherry-pick: `0` unapplied commits means the content is in the merge target however it got there. Treat that as **ask, not skip** — report the branch and let the human decide, because this is the one case where the two tests disagree. **State its limit rather than trusting it blindly:** a cherry-pick that required conflict resolution changes the patch, so `git cherry` prints `+` for a commit that *is* applied (measured: `rev-list` `1`, `git cherry` `+1`, content present). Neither test is authoritative alone; a branch that fails both is genuinely unmerged, and a branch that passes either is not to be skipped silently.

   > **Quote the `^` operand. Both operands, every time.** `^HEAD` unquoted is a **negated-glob pattern** under zsh with `extended_glob` set — which oh-my-zsh and many `.zshrc` files enable, on the platform whose shell these blocks are commonly run in. It expands to *"every entry in the CWD except `HEAD`"*, git receives those as **pathspecs**, the exclusion is silently dropped, and the command exits 0 with a wrong number. Measured on a merged branch: `"^HEAD"` → `0`, bare `^HEAD` → `2`. A **merged** branch then classifies `NOT-MERGED`, so its pending-doc is never routed, its `roadmap_ids` never flip to `done`, its body never moves to `archive/`, and its lock and parked markers never drop — every close, silently. The spot-check that would catch it is the one an author is least likely to run, because an *unmerged* branch returns non-zero either way and looks correct. `WORKFLOW.md` § 8.2a names quoting as an uncovered invocation class; this is a shipped instance of it. **`NOT-MERGED` means leave the file in place and skip it entirely**: do not route it, do not touch its task IDs, do not delete it. It is re-collected on a later run once the branch is mergeable. Report each one on Step 8's report beside its 4a-SKIP entry.
   >
   > **Report it even when there is no 4a-SKIP entry to sit beside.** That instruction assumed the only way to be held back is to fail Step 4a, and the cherry-pick case above breaks the assumption: the branch merged, Step 4a recorded no skip, and Step 8's `Remaining:` block has no slot for the doc. Use the `Held-back docs:` line in Step 8's template — one row per doc, naming the branch, the count each test returned, and the reason — and never let the only trace be a smaller `<N>` in `Docs: Consolidated <N> pending-docs`, a number with nothing to compare it against.

   **If the ref no longer resolves, stop and ask — do not guess in either direction.** Step 6 is the only step that deletes feature branches and it runs *after* this one, so at this point every branch this close merged still has a local ref; a missing one is an unexplained state, not a legacy quirk.

   **If `branch:` is ABSENT, quarantine the doc and carry on — do not stop, and do not consolidate it.** Move it to `sysop/runtime/pending-docs/quarantine/<name>.md` — **create the directory first** (`mkdir -p sysop/runtime/pending-docs/quarantine`; nothing else in the tree creates it, so an `mv` alone fails on the first firing) (a subdirectory, so no `*.md` reader sees it again), report it on Step 8's `Quarantined docs:` row, and continue with the next file.

   > **This rule replaced two opposite ones, and the ambiguity was not theoretical.** Until this phase the paragraph above read, verbatim, *"If `branch:` is absent or the ref no longer resolves, stop and ask — do not guess in either direction"*, while the blockquote two lines below said a doc *"with no `branch:` at all is the one benign shape … so consolidating it is safe"* — opposite dispositions for the identical input, and the second closed with *"say which case you hit rather than silently picking"*, which concedes the ambiguity without resolving it. **Measured:** two independent fresh-context reviewers, reading this same file with no contact between them, implemented one disposition each — one halted the close, the other consolidated the doc and deleted it. That is not a reading dispute; it is a step whose behaviour on a real input depends on which sentence the agent reaches first. Quarantine is chosen over both: *stop-and-ask* turns any such file into a permanent halt on every future close (nothing else in the tree deletes a pending-doc), and *consolidate-as-benign* routes nothing and then deletes the only copy. Quarantine loses no bytes, needs no human turn, and cannot recur — the file is out of the glob the moment it moves.

   > **One way to reach that hard stop is this close's own Step 6, one run earlier.** Under `pr` policy Step 6 force-deletes (`git branch -D`) every branch Step 4a recorded as merged. A branch the operator cherry-picked is recorded merged, so it is deleted — while its pending-doc was held back here for scoring non-zero. On the next close the doc is re-collected, its `branch:` no longer resolves, and this rule fires: the close halts on a doc it created the conditions for. Under `direct` the tail is benign, because that path's safe `git branch -d` refuses on a cherry-picked branch and the ref survives. **The `git cherry` fallback above is what prevents the hold-back in the first place**; if you are reading this having already hit the stop, the doc's content is almost certainly in `main` already — verify with `git log --oneline --all --grep` on its summary before deciding, and do not consolidate on the assumption alone. (**A doc with no `branch:` at all is no longer treated as a benign legacy shape — it is quarantined, per the rule above.** This parenthesis previously said consolidating it was safe, which contradicted the stop-and-ask rule it sat beneath; both are now replaced by the single quarantine disposition. The case this parenthesis was reaching for — a *legacy-format* doc predating worktree-per-branch — is covered there too, and losing its bytes to a quarantine directory costs nothing that consolidating an unroutable doc would have preserved.)

1c. **Hold back any pending-doc naming a task whose human step is still outstanding (`Q-327`).** After 1b's merged-only filter, read each surviving doc's ids and look each one up in `tasks/index.yml`. **Read `roadmap_ids`, falling back to `task_ids`** — the same Phase-23a compat shim step 3 applies (`pending.get('roadmap_ids') or pending.get('task_ids') or []`), and it is not optional here: a legacy doc keyed on `task_ids` that this gate skipped would be routed and consolidated, and only the round-trip's defence-in-depth arm would then hold the task — which is the stranding path, reached through the gate that exists to close it. **If any of those ids has a truthy `user_action`, do not route this doc at all this run** — truthy, **not** `== true`, matching the round-trip's predicate exactly. The two gates must agree, and a malformed non-bool value is precisely where an equality test and a truthiness test diverge: an equality reading routes the doc, the round-trip then holds the task, and the doc is deleted underneath it. The heredoc records why truthiness is the right bias; this gate inherits that reasoning rather than restating it — leave the file in `sysop/runtime/pending-docs/`, exactly as 1b leaves an unmerged branch's doc, and report it under Step 8's `Held-back docs:` with the reason `user_action outstanding: <TASK_ID>`.

   **Why the WHOLE doc waits, and not just the status flip.** The first cut of this fix did the narrower thing the filing proposed — route the doc entries as normal, hold only the three mutations that assert completion — and it **stranded the task**. The path is worth writing down because nothing about it is obvious: step 6 deletes the pending-docs *this step consolidated*, a routed doc is consolidated, and the pending-doc is the **only** carrier of `roadmap_ids` into this round-trip. So the doc would be gone, the task would sit `in_progress` with its lock held and its body under `open/`, and nothing would ever close it — `clear_user_action.py` flips the flag and says so in its own output (*"status is `in_progress`, so the automated frontier … still will not pick it up"*), and a later `/review-close` has no doc naming the task. **A silent permanent stall, arriving from a fix for a silent false close.** Holding the doc keeps the carrier alive: the human performs the step, clears the flag, and the next `/review-close` consolidates the doc and closes the task through the ordinary path, with no duplicated `CHANGELOG` entry. **The doc is only half the carrier, and the other half is the branch** — the doc's `branch:` is what step 1b resolves, and Step 6 deletes merged feature branches under both policies, so a held doc whose branch was cleaned up does not resume: it **halts** the next close on step 1b's stop-and-ask. Step 6 therefore carries a HARD RULE excluding those branches; that rule and this hold are one mechanism and neither works alone.

   **The cost, stated rather than discovered later:** the code merged this run and its `PROJECT_STATUS.md` / `CHANGELOG.md` entry waits for the human step. That is the honest ordering — those files say a task is **Complete**, and it is not — but it does mean a held task's documentation lags its merge, visibly, in `Held-back docs:` on every run until the step is done.

   **Granularity is the whole doc, deliberately.** A pending-doc naming two tasks, one held and one not, holds **both**. Splitting it would mean routing half a doc and re-routing the other half later, which is the duplication this ordering exists to avoid; the conservative direction is the one that cannot write a false `Complete`. Say so in the Step 8 row — name the held task *and* the siblings waiting on it — so the operator can see the whole doc is waiting on one human step.

2. **If none found**: check merged history for `docs:` commits (backward compatibility with branches that wrote docs directly). If present, skip doc consolidation — the docs are already in the shared files.

3. **If pending-docs files found**: parse each file's YAML frontmatter and extract:
   - `branch`, `date`, `type`, `roadmap_ids`, `review_task_ids`, `summary`

   **Format detection — three arms, and the third one is not optional.** Use the same reader Step 3c already ships (`fm_re = re.compile(r'^---\n(.*?)\n---', re.DOTALL)`), not a `startswith('---')` test:

   1. **Frontmatter matches and `yaml.safe_load` returns a mapping** → parse it. The normal path.
   2. **No frontmatter match** → the legacy 5-section markdown format (`## Classification`, `## PROJECT_STATUS Entry`, etc.).
   3. **Frontmatter matches but will not parse, or parses to something that is not a mapping** → **quarantine the file and carry on.** Move it to `sysop/runtime/pending-docs/quarantine/<name>.md` — **create the directory first** (`mkdir -p sysop/runtime/pending-docs/quarantine`; nothing else in the tree creates it, so an `mv` alone fails on the first firing), report it on Step 8's `Quarantined docs:` row, and continue with the next file. Do **not** route it (it has no `type`, so the routing table does nothing), do **not** delete it (its bytes are the only record of what shipped), and do **not** leave it in place (it would be re-encountered on every future close).

   > **Why arm 3 exists, and why `startswith` is the wrong test.** A doc that starts with `---` and fails to parse takes arm 1 under the old two-way rule, where `yaml.safe_load` **raises** — and this step had no error arm at all, so the exception surfaces mid-consolidation, after Step 4a has already merged. The shapes that reach it are not exotic: an unterminated frontmatter block and a `---` used as a markdown horizontal rule both fail the frontmatter match entirely (and raise `ValueError` under a naive three-way `split('---', 2)` unpack, which is why the regex above is the prescribed reader); malformed YAML raises `ScannerError`/`ParserError`; and frontmatter that loads to a **string** rather than a mapping (a single prose line between the delimiters) is *truthy*, so the `or {}` idiom below does not catch it and `.get()` raises `AttributeError`. **Step 3c's shipped reader now handles all four by skipping** (`if not fm_m: continue`, `except yaml.YAMLError: continue`, `if not isinstance(fm, dict): continue`, and `errors="replace"` on all four reads in that heredoc) — it did NOT before this phase: a reviewer ran it and watched a non-mapping frontmatter and a non-UTF-8 doc each kill the close with a traceback at a step that runs BEFORE this one, which would have made arm 3 unreachable for those shapes — this file has carried two divergent pending-doc readers, one defensive with code and one prescriptive with none. Arm 3 is what makes them agree, except that quarantining beats Step 3c's silent skip: a skipped doc is invisible, a quarantined one is reported and its bytes are on disk.
   >
   > **`or {}` does not protect against a non-mapping — do not rely on it.** `yaml.safe_load("work in progress")` returns the truthy string `"work in progress"`, so `fm or {}` yields the string and `.get()` raises. Test `isinstance(fm, dict)` explicitly.
   <!-- Legacy format support — remove after all active worktrees are merged -->

   **Phase 23a compat shim — read every pending-doc with this fallback:**

   ```python
   roadmap_ids    = pending.get('roadmap_ids')    or pending.get('task_ids') or []
   review_task_ids = pending.get('review_task_ids') or []
   ```

   The fallback covers in-flight pending-docs authored before the `task_ids` → `roadmap_ids` rename (Phase 23a). Treat any IDs read via the fallback as `roadmap_ids` — that matches the pre-rename consumer behavior (Step 4c's heredoc was already treating them as roadmap IDs, just silently no-op'ing on the non-matches). **Removal trigger:** drop the `or pending.get('task_ids')` clause in any subsequent phase that touches Step 4c, once BeanRider has run one full `/review-close` cycle on a pending-doc authored after the 23a absorption (confirmable via `git log -p sysop/runtime/pending-docs/` or via the merged consolidation commit). Pending-docs are minutes-to-hours lived; the shim's exposure window is one absorption cycle.

4. **Route by type and write to shared docs** (single pass, no conflicts since we're on main post-merge):

   Use this routing table to determine which shared docs to update for each entry. The "Roadmap" column shows which frontmatter field drives the `tasks/index.yml` round-trip; `review_task_ids` is **documentary only** and never consulted here (review-task closure happens in Step 4b via `bash sysop/scripts/close_batch.sh`) — **nor is it consulted there**, which this sentence used to leave open: Step 4b derives its batch set from the `BATCH-*.lock` files, because these are `TASK-NNNN` ids and that script takes batch integers. Until Phase 239 neither step named a source, so the two pointed at each other.

   | Type | PROJECT_STATUS | Changelog | UI_Iterations | Roadmap (`roadmap_ids`) |
   |---|---|---|---|---|
   | feature | Yes | — | — | if populated |
   | bugfix | Yes | Yes | — | if populated |
   | ui-iteration | Yes | — | Yes | if populated |
   | infrastructure | Yes | — | — | if populated |
   | adhoc | Yes | — | — | if populated |

   The Roadmap column is **informational only** — `if populated` means the `tasks/index.yml` round-trip below runs unconditionally for every ID in `roadmap_ids`, regardless of `type`. This is intentional: the round-trip is mechanical (status flip + body move + lock/parked-marker cleanup), driven by data presence, not by type. **One condition was added by Phase 241 and it is not a type test either — it is a field test.** A task whose `user_action` is `true` is HELD: its doc entries route exactly as this table says, and the three mutations that assert completion do not run. `type` still governs nothing here; `user_action` governs whether the close may claim the task is finished. See the hold comment in the heredoc below for why the smoke gate is not a backstop for it. A pending-doc with `roadmap_ids: []` simply skips the round-trip naturally. (BeanRider ISSUE-0034: tracked-bug close-outs use `type: bugfix` with a populated `roadmap_ids: [BUG-NNNN]` and need the round-trip; the prior `—` reading would have left the BUG entry stuck `in_progress` with the body orphaned under `open/`.)

   For each entry, generate the doc content from `type` + `summary` + `roadmap_ids` + `review_task_ids` + `date`:

   **PROJECT_STATUS.md §6**: Generate a one-line entry: `<date>: [<ID(s)> Complete:] <summary>`. Pull IDs from `roadmap_ids` AND/OR `review_task_ids` — both kinds belong in the PROJECT_STATUS entry as provenance. Insert at the TOP of Section 6 "Recent Major Updates" (below the section header, above existing entries). Newest branch first.

   **Consolidation clause — a wide close writes ONE §6 entry, not one per branch.** Count the pending-docs this run is routing (the merged-only set from step 1b, the same `<N>` the commit subject carries). **If `<N>` is more than 4**, do not write the per-branch entries above. Write a single one-line entry instead — `<date>: <N> branches merged in one close: <batch or branch list> — per-branch detail in CHANGELOG.md` — and route **every** entry's detail to `CHANGELOG.md` (see § *The changelog contract* below) as a bullet under `## [Unreleased]`, classed by `type` (feature → `### Added`, bugfix → `### Fixed`, everything else → `### Changed`) with ` (<date>)` appended, whatever its `type`. Then §6 reads as one update, which is what a close of many branches is; a squash PR is one update however many branches it consolidated.

   > **Why the cap is on the writer and not on the rotation.** The write above scales with branch count and the rotation below is a **constant**, so without this clause the two invert on exactly the shape `/auto-fix` and `/auto-judge` produce (internal tracker #364): with 6 pre-existing entries and 8 pending-docs, 6 + 8 = 14 rotates down to 6 — discarding all 6 pre-existing entries **and 2 of the 8 just written**, in the commit that wrote them.
   >
   > **The condition, derived rather than restated.** The run's entries are inserted newest-first, so rotation reaches them only after it has consumed every pre-existing entry: it removes `total − 6`, which exceeds `pre_existing` exactly when **`docs > 6`** — the retained count, not the trigger. So a run loses its own entries iff `pre_existing + docs > 8` **and `docs > 6`**. The filing (and this clause's first draft) said `docs > 2`, which over-claims on 22 of the 49 `(pre_existing, docs)` pairs up to 9 — every one of them in the "says it reproduces, does not" direction. The filing's worked example was right and its general rule was not.
   >
   > **What follows for the threshold, stated so it is not read as arithmetic.** Any cap of 6 or less closes the self-loss case completely, so **4 is not required by the defect** — it is chosen for the second reason option (b) was preferred at all: eight per-branch lines in "Recent Major Updates" is not a summary of anything, and a squash PR is one update however many branches it consolidated. That half is a judgement about readability, and it is the only reason the cap is 4 rather than 6. The invariant a test can hold is the one that matters: **the cap must never exceed the retained count**, or an entry this run wrote can be rotated out by this run.
   >
   > The rejected alternative was to make the rotation skip anything dated today: that grows §6 without bound on a day with several closes, and has no answer for a §6 in which every entry is from today.

   **Rotation check**: if §6 has more than 8 entries after adding, rotate the oldest entries to `CHANGELOG.md` — each as `- <summary> (<original date>)` under `## [Unreleased]` → `### Changed` — until only 6 remain. **Report the count you rotated** in the Step 8 summary — a truncation nothing announces is how this step's scaling defect survived unnoticed.

   > **Rotation is a MOVE, and it must not re-write an entry that is already there.** A `bugfix` entry was written to §6 *and* to `CHANGELOG.md` on the close that created it (the routing table's `Yes | Yes` row). Some later close then rotates that §6 line out — into the same file the bullet already sits in — and the file ends up carrying one piece of work twice, in two formats. **So for each line you are about to rotate: search the whole of `CHANGELOG.md` for that line's summary text first** — the whole file, not one section, because the existing bullet may sit under `## [Unreleased]` from the close that wrote it or under a `## [x.y.z]` heading if `/release` has folded it since. If a bullet already carries it, the entry is already recorded — **drop the §6 line instead of copying it**, and count it as rotated all the same (the §6 slot was still reclaimed). Only lines with no existing bullet are written. The two formats differ (`<date>: [ID Complete:] <summary>` in §6 versus `- **<Title>**: <summary> (<date>)` in the changelog), so match on the **summary**, not on the whole line — a whole-line match never fires and would leave this rule inert while looking present.

   **CHANGELOG.md** (bugfix type only, **and only when the Consolidation clause did not fire**): Generate entry `- **<Short Title>**: <summary> (<date>)`. Add under `## [Unreleased]` → `### Fixed`. Create the `### Fixed` class heading — and the `## [Unreleased]` section itself, directly under the file's title block — if missing.

   > **The changelog contract — one file, one grammar, shared with `/release` (Phase 222, Q-279).** The file is `CHANGELOG.md` in [Keep a Changelog](https://keepachangelog.com) shape: a title block, then `## [Unreleased]`, then the `## [x.y.z] - <date>` version sections `/release` owns. This step writes **only** inside `## [Unreleased]`, as `- ...` bullets under the standard class headings (`### Added` / `### Changed` / `### Fixed`) in the bugfix write's `- **<Short Title>**: <summary> (<date>)` shape (rotation's `- <summary> (<original date>)` is the one exception — a rotated §6 line has no title to bold), with ` (<date>)` appended because `[Unreleased]` carries no date headings; **every writer above creates what is missing** — the class heading, the `## [Unreleased]` section (directly under the title block; on a legacy changelog with no title block, add the standard Keep-a-Changelog title block first), or the file itself — the create contract is the contract, not the bugfix row's private property; `/release` folds `[Unreleased]` into the next version section when a release is cut. Two rules keep the two writers off each other: **(a)** if the project already tracks its changelog under a different case (check `git ls-files -- ':(icase)changelog.md'` — one read-only git command, no pipe to bind a second rule — `changelog.md` and `CHANGELOG.md` are the *same file* on a case-insensitive filesystem, which is the macOS and Windows default), write to that existing tracked path rather than creating a second name; **(b)** if no changelog exists under any case, create `CHANGELOG.md` with the standard Keep-a-Changelog header — the same create contract as `/release`. The pre-222 grammar (`### YYYY-MM-DD` date headings under month headings) is retired; leave any existing date-headed entries where they are — they are history, not a format to continue.

   > **Why the second condition.** The Consolidation clause above routes **every** entry's detail to `CHANGELOG.md` on a close of more than 4 pending-docs — *including* the `bugfix` ones. Running this write as well would put **two bullets for one entry under the same class heading, in the same close**: the clause suppresses only the per-branch §6 writes "above", not this one. That is the `/auto-fix` and `/auto-judge` shape, so it is the automated path rather than an edge case. One clause fires or the other does; never both for the same entry.

   **tasks/index.yml**: For each ID in `roadmap_ids` (NOT `review_task_ids` — those are documentary, see the note above), round-trip the index through `yaml.safe_load` to set `status: done` + `completed_date: <today's ISO date>` on the entry, then `git mv` the body file from its current location under `open/` or `deferred/` to the corresponding location under `archive/` and update the entry's `body:` field. The heredoc below is prefix-agnostic — it handles both canonical (`body: open/<TASK_ID>.md`) and `tasks/`-prefixed (`body: tasks/open/<TASK_ID>.md`) shapes by locating the `open` / `deferred` path segment and swapping it for `archive`. It also tolerates pending-docs authored before Phase 23a (compat shim — see the **Phase 23a compat shim** block in step 3 above). After all IDs are processed, run the validator (`python3 sysop/scripts/validate_tasks.py` — a single command matching `Bash(python3 sysop/scripts/validate_tasks.py:*)`; Sysop Phase 126 dropped the shared `PATH` prefix this line used to ride on and gave `validate_tasks.py` its own `sys.path` PyYAML bootstrap, so bare `python3` resolves `yaml` for both venv-only and non-venv consumers — BeanRider ISSUE-0049) — if it exits non-zero, abort the close. The schema invariants for `done` status require: a valid `completed_date`, either a `body:` or an `archive_summary:`, and (ISSUE-0009) the body path must NOT contain an `open/` or `deferred/` segment (a half-migrated state where the status flip wrote but the rename silently no-op'd). Fix any failure before pushing.

   ```bash
   # `python3` command word + in-heredoc PyYAML bootstrap (BeanRider ISSUE-0049; Sysop
   # Phase 126) so `Bash(python3 -:*)` matches as a single simple command — no PATH prefix,
   # no `&&` compound, no `.venv/bin/python3` (none of which match that rule).
   python3 - <<'PY'
   import datetime, os, shutil, subprocess, sys
   try:
       import yaml
   except ImportError:  # PyYAML lives only in the project venv (BeanRider ISSUE-0049)
       import glob, os, subprocess
       _sites = []
       try:
           _r = subprocess.run(
               ["git", "rev-parse", "--git-common-dir"],
               capture_output=True, text=True, timeout=5,
               env={_k: _v for _k, _v in os.environ.items()
                    if _k not in ("GIT_DIR", "GIT_WORK_TREE",
                                  "GIT_COMMON_DIR", "GIT_INDEX_FILE")},
           )
           _g = _r.stdout.strip()
       except (OSError, subprocess.SubprocessError):
           _g = ""
       for _root in ([os.path.dirname(os.path.abspath(_g))] if _g else []) + ["."]:
           for _layout in (".venv", "venv"):
               _sites += glob.glob(os.path.join(_root, _layout, "lib/python*/site-packages"))
       sys.path[:0] = _sites
       import yaml
   from pathlib import Path
   today = datetime.date.today().isoformat()
   # Populate from this round's pending-doc roadmap_ids (with the Phase 23a
   # compat shim applied at parse time — see step 3 above).
   # review_task_ids are NOT processed here — they're documentary only.
   ids = ["<ROADMAP_ID_1>", "<ROADMAP_ID_2>"]
   p = Path('tasks/index.yml')
   d = yaml.safe_load(p.read_text(encoding='utf-8'))
   closed = []
   held = []
   for t in d.get('tasks', []):
       if t['id'] not in ids:
           continue
       # HOLD a task whose human step is still outstanding (`Q-327`). `user_action` is
       # Sysop's OWN schema field — validate_tasks.py requires it as a bool on every
       # open/in_progress task — and until Phase 241 this round-trip never read it, so a
       # merged diff alone flipped the task to `done`. Nothing upstream is a backstop:
       # Step 3c's smoke gate deliberately excludes `## User ops` from its phrase set,
       # and its waive outcome does not halt, so a waived smoke and a passed smoke are
       # indistinguishable here. `tasks/schema.md` § User ops already conceded this in
       # prose ("Nothing verifies the steps were performed"); this is the one step that
       # writes the durable state, so it is where the concession gets closed.
       # THIS IS DEFENCE IN DEPTH, not the primary gate. Step 1c above holds the
       # whole pending-doc back before any routing happens, so on the ordinary path
       # a held task's ids never reach this loop at all. This arm exists because
       # `ids` is a written-out literal an operator substitutes by HAND: 1c can be
       # skipped or mis-read, and the literal can be pasted from a previous run.
       # If a held id does arrive here, the flip must still not happen.
       # What is withheld: the status flip, the body archive move, and the
       # lock/parked-marker/claim-artifact cleanup below — all keyed on `closed`,
       # so keeping a held id OUT of that list is what withholds them.
       # NOTE the ordering consequence, because it is not obvious: reaching this arm
       # means the doc WAS routed, so its PROJECT_STATUS/CHANGELOG entries have
       # landed for a task that did not close, and the doc is about to be deleted by
       # step 6 — the stranding Step 1c exists to prevent. Report it loudly at
       # Step 8 and fix the id list; a hold HERE is an anomaly, not the normal case.
       # NOT a contradiction of clear_user_action.py (Phase 237): that clears the flag
       # EARLY so a task rejoins the frontier, and its docstring explicitly declines the
       # close path. Clearing is the human saying "done"; this is the close path
       # declining to say it on their behalf.
       # Truthiness, deliberately, NOT `is True`. `validate_tasks.py` requires a
       # bool, but that validator runs at the END of this step, so a malformed
       # index reaches here first. Measured across eight values: a bare `true`
       # holds; `false`, a missing key and an explicit `null` all close (which is
       # what a task predating the field needs); and a non-bool truthy value such
       # as the STRING `"false"` also holds. That last one is wrong-looking and is
       # the SAFE direction — holding a task that should have closed costs one
       # `clear_user_action.py`; closing one that should have held is the defect
       # this hold exists to remove. Do not tighten this to `is True`: a string
       # `"true"` would then CLOSE a task whose human step is outstanding, which
       # inverts the bias on exactly the malformed input the strictness was for.
       if t.get('user_action'):
           held.append(t['id'])
           continue
       t['status'] = 'done'
       t['completed_date'] = today
       closed.append(t['id'])
       body = t.get('body', '')
       if not body:
           continue  # no body to move (archive_summary case)
       parts = body.split('/')
       # Locate the path segment matching the task's pre-transition status
       # directory. Generalizes over open/ and deferred/ — a task may complete
       # from either. Skips bodies that live at the root of tasks/ (no swap
       # target). The segment-based match is prefix-agnostic: it works whether
       # body is stored as "open/X.md" or "tasks/open/X.md".
       swap_idx = next((i for i, seg in enumerate(parts) if seg in ('open', 'deferred')), None)
       if swap_idx is None:
           continue
       new_parts = list(parts)
       new_parts[swap_idx] = 'archive'
       new_body = '/'.join(new_parts)
       src = body if body.startswith('tasks/') else f'tasks/{body}'
       dst = new_body if new_body.startswith('tasks/') else f'tasks/{new_body}'
       # `git mv` into a directory that does not exist is fatal (`renaming … failed: No
       # such file or directory`), and with check=True that aborts the loop AFTER earlier
       # renames are already staged and BEFORE the index write below — reproducing the
       # very half-staged commit this step exists to prevent. install.sh ships
       # tasks/archive/.gitkeep, so this only bites a branch cut before that landed.
       Path(dst).parent.mkdir(parents=True, exist_ok=True)
       subprocess.run(['git', 'mv', src, dst], check=True)
       t['body'] = new_body
   # Only write when something actually closed. With `closed` empty, `d` is unchanged, and
   # writing it anyway would reserialize the whole index (stripping comments and formatting)
   # and stage that diff under the consolidation subject — on a run whose pending-docs
   # carried no roadmap_ids, where Step 7 correctly expects tasks/index.yml to be ABSENT
   # from the commit.
   if closed:
       # Atomic rewrite (Phase 201). `p.write_text` truncates in place, so an interrupted
       # write leaves a half-written index — the one file carrying every task's status.
       # `backfill_completed_dates.py` has used tempfile + os.replace since Phase 108 and is
       # the shape copied here. The three claim-side writers (claim-task Step 4a, auto-build
       # Step 5.1, claim_task.sh --release) still truncate in place via open(..., "w"); this
       # site was done first because it is the one that has already `git mv`d the bodies, so
       # a torn write there strands staged renames against an index that never recorded them.
       # Same directory, so the replace is atomic and no reader sees a partial file.
       # Scope, stated because the sibling is copied only in part: this takes the
       # tempfile + os.replace half, NOT its fsync pair — process-level interruption is
       # covered, machine-level (power loss) is not. The failure arm IS copied: a
       # surviving .tmp would sit untracked beside a tracked path for the rest of the
       # close, which is the residue hazard Step 2b names. Two properties `write_text`
       # had for free and `os.replace` does not are restored explicitly: it writes
       # THROUGH a symlink rather than replacing it, and it keeps the old file's mode.
       target = Path(os.path.realpath(p))
       tmp = target.with_suffix(target.suffix + '.tmp')
       try:
           mode = target.stat().st_mode & 0o7777
           tmp.write_text(yaml.safe_dump(d, sort_keys=False, default_flow_style=False, allow_unicode=True, width=120), encoding='utf-8')
           os.chmod(tmp, mode)
           os.replace(tmp, target)
       except BaseException:
           if tmp.exists():
               tmp.unlink()
           raise
       # Stage the rewrite here, in the same code that performed it. `git mv` above already
       # staged both halves of each body rename, but `Path.write_text` does not stage
       # anything — so without this line the index is left HALF staged, and Step 7's
       # `git commit` would record the renames while silently dropping the `status: done`
       # + `completed_date` flip under a subject claiming the consolidation happened
       # (internal tracker #203). Staging beside the write is the only form that cannot drift out
       # of sync with what was written.
       subprocess.run(['git', 'add', str(p)], check=True)
   # Working-tree cleanup, deferred until every git mv landed and the index wrote:
   # an abort mid-loop must not have already destroyed an earlier task's records
   # (the parked marker below is unrecreatable — plan + verdict, never committed).
   # Keyed on the task id, not the body shape, so archive_summary and flat-layout
   # closes — which `continue` past the move above — are still cleaned up.
   locks_removed, locks_absent, markers_removed = [], [], []
   artifacts_removed, artifacts_failed = [], []
   for tid in closed:
       # Drop the per-task lock file (BeanRider ISSUE-0035). The lock's lifecycle
       # is open → in_progress (claim_task --lock creates it) → done (here). Leaving
       # it behind clutters sysop/runtime/locks/ and confuses the "is anyone working on this?"
       # signal. `sysop/runtime/locks/` is .gitignored, so this is a working-tree-only operation
       # — no stage, no commit. `missing_ok=True` tolerates pre-Phase-32 tasks
       # whose locks already got cleaned up by hand.
       lock = Path(f'sysop/runtime/locks/{tid}.lock')
       # Record existence BEFORE the unlink. `missing_ok=True` is deliberate (see the
       # pre-Phase-32 note above) but it DISCARDS the one fact Step 8's `Locks cleaned:`
       # row asks for, so a list assembled afterwards would name tasks whose lock was
       # already gone. Removed and already-absent are reported as separate sets.
       # `exists()` alone follows symlinks, so a DANGLING lock symlink reports
       # 'already absent' while the unlink below really does remove it — a row
       # that claims to report what this code did, reporting the opposite.
       (locks_removed if (lock.exists() or lock.is_symlink()) else locks_absent).append(tid)
       lock.unlink(missing_ok=True)
       # Also drop any parked marker(s) for the task. /auto-build Phase 6d mirrors a
       # parked task's plan + verdict to the durable project-root archive
       # sysop/runtime/parked/<TASK_ID>__<TS>.md; the close path historically
       # never removed them, so markers for done tasks accumulated — the parked/ dir a
       # human lists when hunting resumable work over-reports a done task as still
       # parked. Same timing + working-tree-only semantics as the lock above (see the
       # `pr`-policy invariant note in Step 4-pre for why pre-merge death is accepted).
       # A task that never parked has no markers, and Path.glob on a missing parked/
       # dir yields nothing — both no-op cleanly.
       for marker in Path('sysop/runtime/parked').glob(f'{tid}__*.md'):
           markers_removed.append(marker.name)
           marker.unlink(missing_ok=True)
       # And the orchestrated-claim artifact set. Since Phase 171 /claim-task writes
       # sysop/runtime/claim/<CLAIM_ID>/<RUN_ID>/ (plan.md, review.md, classification.md,
       # ...) into the MAIN checkout so it outlives `git worktree remove` — and until
       # Phase 236 NOTHING removed it, for either claim kind, so it grew one directory
       # per run of every claim ever made. This is the roadmap half; the batch half is
       # `close_batch.sh`'s remove_claim_artifacts(), because `closed` is built from
       # `roadmap_ids` only and no batch id can reach this loop.
       #
       # `tid` comes from the id list this step parsed, so it is not free text — but
       # this is the one `rm -rf`-shaped operation in the close path, so it is guarded
       # rather than trusted: a `tid` that ever contained a separator or `..` would walk
       # the delete out of sysop/runtime/claim/ entirely. Resolve and re-check
       # containment before removing anything.
       claim_root = Path('sysop/runtime/claim')
       claim_dir = claim_root / tid
       try:
           inside = claim_dir.resolve().parent == claim_root.resolve()
       except OSError:
           inside = False
       # `inside` gates BOTH arms. The first cut of this block gated only the rmtree
       # and let the symlink arm run unguarded, so a `tid` of `../../../escaped_link`
       # unlinked a symlink at the repo root and REPORTED it as a claim artifact —
       # reproduced by this phase's round, against a comment claiming containment was
       # re-checked "before removing anything".
       if not inside:
           pass
       elif claim_dir.is_symlink():
           # Remove the LINK, never what it points at — the target may be anything.
           try:
               claim_dir.unlink(missing_ok=True)
               artifacts_removed.append(tid)
           except OSError as e:
               artifacts_failed.append(f'{tid} ({e.__class__.__name__})')
       elif claim_dir.is_dir():
           # NEVER let this raise. This loop's own contract, stated at its head, is that
           # an abort mid-loop must not have already destroyed an earlier task's records —
           # and every other operation here is non-raising by construction
           # (`unlink(missing_ok=True)`, `glob`). `shutil.rmtree` over a user tree is the
           # first that realistically raises, and when this phase's round made one claim
           # directory unremovable the whole heredoc exited 1 with an earlier task's
           # unrecreatable park marker already gone, a later task's lock never cleaned,
           # the index staged, and — worst — NONE of the six report rows printed, which
           # puts Step 8 straight back to supplying them from memory. Record the failure
           # and keep going; a leftover directory under a gitignored path is a tidy-up,
           # a half-done close is not.
           try:
               shutil.rmtree(claim_dir)
               artifacts_removed.append(tid)
           except OSError as e:
               artifacts_failed.append(f'{tid} ({e.__class__.__name__})')
       elif claim_dir.exists():
           # A regular file where a directory belongs. Neither arm above owns it, and
           # silently printing "never ran the pipeline" would state a specific, false
           # cause. Say what was actually found.
           artifacts_failed.append(f'{tid} (not a directory)')
   # Report what this code DID. Until Phase 219 this heredoc printed nothing at all,
   # while Step 8 asked it for three values — so the agent supplied them from its memory
   # of what it intended, which is not the same list. Two of these are not derivable
   # after the fact at all: `missing_ok=True` erases the lock distinction, and the
   # markers are gone once unlinked.
   #
   # `NOT_IN_INDEX` exists because `closed` is a strict SUBSET of `ids`: the loop above
   # skips any id with no matching `tasks/index.yml` entry, silently. Reporting `ids`
   # would over-claim; reporting `closed` alone would hide the drop. Both, or neither.
   print('CLOSED_IDS: ' + (' '.join(closed) or '(none)'))
   # `held` is subtracted here as well as `closed`. A held task IS in the index — that is
   # how its `user_action` was read — so scoring it `NOT_IN_INDEX` would report a task
   # that exists as one that does not, and send the operator looking for a missing entry
   # instead of an outstanding human step. `closed`, `held` and NOT_IN_INDEX partition
   # `ids`; no id may appear in two rows or in none.
   print('HELD_USER_ACTION: ' + (' '.join(held) or '(none)'))
   print('NOT_IN_INDEX: ' + (' '.join(t for t in ids if t not in closed and t not in held) or '(none)'))
   print('LOCKS_REMOVED: ' + (' '.join(locks_removed) or '(none)'))
   print('LOCKS_ALREADY_ABSENT: ' + (' '.join(locks_absent) or '(none)'))
   print('PARKED_MARKERS_REMOVED: ' + (' '.join(sorted(markers_removed)) or '(none)'))
   print('CLAIM_ARTIFACTS_REMOVED: ' + (' '.join(sorted(artifacts_removed)) or '(none)'))
   print('CLAIM_ARTIFACTS_FAILED: ' + (' '.join(sorted(artifacts_failed)) or '(none)'))
   PY
   # Read this BEFORE the validator line below. The heredoc rewrites `tasks/index.yml`,
   # `git add`s it, and only then cleans locks and markers — so a crash in the tail
   # (a lock path that is a directory raises PermissionError, measured) leaves the
   # index flipped and staged, the cleanup half-done, and **all five report rows
   # gone**. The validator that follows passes on the valid index and says nothing
   # about any of it, so a non-zero here is the only signal there is.
   echo "--- Step 4c heredoc exit (MUST be 0; anything else means the rows above are incomplete):  $?"
   python3 sysop/scripts/validate_tasks.py || { echo "validator rejected the index — aborting"; exit 1; }
   ```

   **UI_Iterations.md** (ui-iteration type only): Generate table row `| <name> | <date> | <summary> | <commit-hash> |`. Append to the markdown table.

   <!-- Canonical process: WORKFLOW.md §2.8 (Senior Merge & Verification) -->

   <!-- Convention promotion moved to /codebase-review and /security-audit Step 9 -->

6. **Clean up pending-docs**: Delete the pending-docs **this step consolidated** — never a bare "delete all remaining". Remove the `sysop/runtime/pending-docs/` directory only if it is now empty; leave it in place if it is not.

   > **A doc step 1b held back must survive this step, and an unqualified delete here silently destroys it.** 1b deliberately leaves any pending-doc whose branch did not merge, for re-collection on a later run. The branch's worktree is already gone (Step 3b removed it before the merge was attempted) and the doc is **untracked**, so deleting it here is unrecoverable — the exact BeanRider ISSUE-0050 class this filter exists to close, re-entered five items later. Delete by name from the set you routed, not by glob.

7. **Stage, then commit**: `docs: consolidate documentation for <N> merged branches`

   **Stage the shared docs one `git add` per file** — the heredoc already staged `tasks/index.yml` and both halves of each body rename, but the shared-doc edits above were made with the editor and are still unstaged. Add **only** the docs the routing table actually sent this run's entries to:

   ```bash
   git add PROJECT_STATUS.md                 # every type
   git add CHANGELOG.md                      # if a bugfix entry was routed there, OR if the
                                             # rotation check moved §6 entries into it
                                             # (use the project's tracked case — see § The
                                             # changelog contract)
   git add UI_Iterations.md                  # only if a ui-iteration entry was routed there
   git commit -m "docs: consolidate documentation for <N> merged branches"
   ```

   > **One `git add` per file, never one command listing them all.** `git add` is **all-or-nothing across its pathspecs**: if any pathspec matches nothing, the whole invocation aborts with `fatal: pathspec '<path>' did not match any files` and stages **none** of the others (verified). `UI_Iterations.md` is consumer-authored and frequently absent — Sysop never creates it — and `CHANGELOG.md` is absent on any close that routed nothing to it (this step creates it only when a write lands there), so a combined `git add PROJECT_STATUS.md CHANGELOG.md UI_Iterations.md` aborts on the majority of close-outs. `-A` does **not** change this: `git add -A <missing-path>` aborts identically. Separate commands mean a missing optional doc costs only its own line.
   >
   > The same property is why the instinctive `git add <old-path> <new-path>` after a `git mv` does not help: the stale pre-rename pathspec aborts the invocation, so nothing is staged by it. It leaves the index exactly as it was — `git mv` had already staged both halves — which is the trap, because it *looks* like staging was attempted and the following `git commit` still succeeds on the unchanged index.
   >
   > **Do not stage `CHANGELOG.md` from the routing table alone.** Two steps above write it without the routing table's say-so, both regardless of entry type: the **Rotation check** writes it whenever §6 exceeds 8 entries, and the **Consolidation clause** writes every entry's detail there on a close of more than 4 branches. So a run with no bugfix at all can still have written `CHANGELOG.md`, and skipping it there commits the §6 truncation — or the consolidated §6 line — without the entries whose detail it points at.

   **Then verify the commit carried everything** — Step 4b has a trust-but-verify gate for exactly this failure class and Step 4c historically had none, which is what let a rename-only commit pass as a consolidation (internal tracker #203):

   ```bash
   git log -1 --pretty=%s | grep -q '^docs: consolidate documentation' && git diff --quiet && git diff --cached --quiet
   ```

   If that fails, the tree still has unstaged or staged-but-uncommitted consolidation edits: stage the missing file(s) and `git commit --amend --no-edit` before proceeding.

   > **Read the diff before you amend — this is the step that launders a foreign edit in.** `git add` the *named* files the routing table sent this run's entries to, never `-A` and never a bare `git add .`; then `git diff --cached` and confirm every hunk is this close's own work. A stray edit from a Step 2b agent reaches here as an ordinary unstaged modification, and an unread `--amend --no-edit` folds it into a commit whose message says "consolidate documentation for N merged branches" — attributed to this close, under a subject that describes something else. If a hunk is not yours, stop and resolve it rather than amending; Step 2b's delta assertion exists to catch it four steps earlier. **Additionally, if this run closed at least one `roadmap_ids` entry** (the heredoc's `closed` list was non-empty), confirm the index flip is actually in the commit:

   ```bash
   git show --stat HEAD | grep -q 'tasks/index.yml'
   ```

   Skip that second check when no pending-doc carried `roadmap_ids` — `tasks/index.yml` is then legitimately untouched and its absence from the commit is correct, not a failure.

   **If the commit is silently denied** (auto-mode classifier rejects `git commit` on `main` — a `direct`-policy concern; under `pr` policy this commit lands on the integration branch, not `main`, so it does not hit this wall), the Phase 36 `PermissionDenied` hook surfaces the `!`-escape command and the multi-`-m`-flag rewrite recipe — follow its guidance and relay to the user. Background: the classifier extends protected-branch policy upstream from the push to its enabling commit when context implies an imminent push, so the first `docs(tasks):` commit of a cycle goes through but the Step 4c consolidation commit hits the same wall as the Step 4d push. The hook's `additionalContext` names the specific escape form; this skill stays brief on purpose to avoid drifting from the hook's authoritative phrasing.

### 4d. Land on `main`

How the assembled work reaches `main` depends on the merge policy from Step 4-pre.

#### `direct` policy

Once all merges and doc consolidation are complete (or if there were only unpushed main commits), push `main` via the **`_shared/main-push-guard.md` Rule B safe-push sequence** rather than a bare push — assert-on-`main` (Rule A) → `git fetch origin <default branch>` → rebase-first if `origin/<default branch>` advanced (an autonomous auto-merge, e.g. Dependabot) → push the exact verified tip (`git push origin "<SHA>:<default branch>"`, **never `--force`** per Rule C) → confirm `origin/<default branch>` equals the SHA you pushed. The rebase-first step also re-runs **`4a-post`** — the merged-tree gate — against the new base; not Step 3, whose tree is `main` and is not the thing that moved. The bare `git push origin <default branch>` is safe only when `origin/<default branch>` has not moved; Rule B makes that check explicit instead of assumed.

Then confirm the push succeeded.

If the push is **rejected because `main` is protected** (`! [remote rejected] main -> main (protected branch hook declined)`, a required status check, or `enforce_admins`), the project's `main` requires the PR flow: set `§ Merge policy: pr` in `<project>/CLAUDE.md` and re-run `/review-close`. This is the exact failure the `pr` policy exists to handle — do not try to force the push.

**If push is silently denied** (auto-mode classifier rejects pushing to a protected branch), the Phase 36 `PermissionDenied` hook surfaces an `!`-prefixed escape command naming **the branch it matched** — one of the two names it hard-codes, and nothing else — and a venv-prefix variant of the same when the consumer's repo has a `.venv/` directory. Relay what the hook printed; do not retype it from memory or substitute a resolved branch name into it. Follow the hook's guidance and relay to the user. The canonical consumer-side fix is unchanged: the project's `sysop/scripts/hooks/pre-push` should prepend `${REPO_ROOT}/.venv/bin` to its `PATH` at the top of the hook (see WORKFLOW.md § 6.1 venv-aware-invocation paragraph). Do **NOT** use `AskUserQuestion` — empirically the classifier does not honor its answer for protected-branch pushes and you'll burn a turn on a dead-end handshake. See WORKFLOW.md § 8.2a for the full rationale.

#### `pr` policy

`main` is written only through a PR (squash), never a direct push. After the merge target holds every feature merge + `close_batch.sh` + doc consolidation, push it and merge one PR with a normal authenticated `gh pr merge` — **no `--auto`**. (GitHub-native auto-merge is gated behind paid plans for private repos; the non-`--auto` path is what `/pr-dependabot` already standardizes on and works on Free.)

**Step 1 — assert HEAD, push, and get the PR.** This is the only part that differs between the two Step 4-pre shapes.

*Integration-branch shape:*
```bash
# 1. assert HEAD is still a review-close integration branch (Rule A, HEAD-independent: a
#    concurrent actor may have moved HEAD onto main or a feature branch). Match the fixed
#    pattern — NOT $(git rev-parse --abbrev-ref HEAD), which would tautologically pass — then
#    it is safe to (re-)derive $INTEGRATION_BRANCH from HEAD for the push/PR commands below.
case "$(git rev-parse --abbrev-ref HEAD)" in
  merge/review-close-*) INTEGRATION_BRANCH="$(git rev-parse --abbrev-ref HEAD)" ;;
  *) echo "HEAD is not a review-close integration branch (merge/review-close-*) — STOP, reconcile via git reflog"; exit 1 ;;
esac
# 2. push the integration branch (NEVER push main directly; NEVER --force, per Rule C).
#    No -u: `git push -u origin` would not match the `Bash(git push origin:*)` allow-rule
#    (the -u sits between push and origin), and upstream tracking isn't needed — `gh pr
#    create --head` works off the pushed ref and Step 6 force-deletes the branch.
git push origin "$INTEGRATION_BRANCH"
# 3. open the PR against main. Run it BARE — `gh pr create` prints the new PR's URL to
#    stdout and its last path segment is the number Step 2 needs. Do NOT capture it: an
#    allow-rule does not match past an assignment, so `PR_REF="$(gh pr create …)"` routes
#    to the classifier and is auto-denied under `dontAsk`, despite `Bash(gh pr create:*)`
#    being seeded (Phase 153). The title's run id is sliced off the branch name rather
#    than read from $RUN_ID, which was set in an earlier — separate — shell call.
gh pr create --base <default branch> --head "$INTEGRATION_BRANCH" \
  --title "review-close: consolidate ${INTEGRATION_BRANCH#merge/review-close-}" \
  --body "Automated /review-close integration PR: feature merges + batch close + doc consolidation. Squash-merges once required checks are green."
```

*PR-reuse shape:* no branch is created and no PR is opened — the Step 4b/4c commits are appended to the branch the existing PR already tracks.
```bash
# 1. assert HEAD against the LITERAL branch name Step 2a approved (Rule A). There is no
#    fixed pattern to match here, and re-reading the name from HEAD would be a tautology.
test "$(git rev-parse --abbrev-ref HEAD)" = "<approved branch name>" || { echo "HEAD is not the approved branch — STOP, reconcile via git reflog"; exit 1; }
# 2. push the new commits onto the PR's head branch (fast-forward; NEVER --force, per Rule C)
git push origin "<approved branch name>"
# 3. no `gh pr create` — Step 2 below merges the PR number the Step 4-pre probe printed.
```

**Step 2 — wait for checks, merge, then gate on PR *state*.** Identical for both shapes, except where noted.

**First, re-derive the PR number.** This block is a separate shell call from Step 1, so nothing carries over. Run the probe bare and read the number off stdout:

```bash
gh pr list --head "$(git rev-parse --abbrev-ref HEAD)" --base <default branch> --state open \
  --json number,isDraft,isCrossRepository \
  --jq '[.[] | select(.isCrossRepository == false and .isDraft == false) | .number]
        | if length == 1 then .[0] else empty end'
```

**If that prints nothing, STOP** — reconcile by hand, and do not run anything below. This is a hard gate rather than a warning because `gh` does **not** reject an empty operand: it silently resolves the current branch's PR instead (see the `gh`-empty-operand note in Step 4-pre), so a missing number does not fail, it merges the wrong thing.

Otherwise substitute the printed number for `"<PR>"` below and run the commands **as written**. It is a literal, not a variable, for the same reason the probe is bare: a captured value would not survive to the next shell call, and an assignment would cost the invocation its allow-rule match. **Keep the quotes.** Unquoted, `<PR>` is not a placeholder to bash — `<` and `>` are redirections, and **what happens then depends on position and on the filesystem**, measured: in *final* position an unsubstituted `<X>` is a bash **syntax error** (loud, nothing runs); mid-command with no file of that name it is `bash: PR: No such file or directory`, exit 1, nothing created; and mid-command **with a file named `PR` present** it does run as `gh pr merge --delete-branch` reading from that file, `gh` falling back to the current branch — while `> --squash` also **creates a file literally named `--squash`** in the working tree. So the silent-wrong-merge case is the narrow one, and it is the one the quotes exist to remove. Quoted, an unsubstituted placeholder is a *loud* failure (`no pull requests found for branch "<PR>"`) instead of a silent wrong merge — which is what makes the stop above enforceable rather than merely advisory.

```bash
# 4. wait for the PR's required checks to finish (blocks ~1–2 min). Its exit status is NOT
#    the verdict — it exits non-zero both on a failing check and on a repo with no checks
#    at all (one protected only by enforce_admins), so a bare invocation would surface a
#    red tool result on a perfectly mergeable PR and invite you to stop. The `|| echo` tail
#    is deliberate and is NOT `|| true`: `echo` IS in Claude Code's documented built-in
#    read-only set while `true` is not, so this keeps the compound authorized while
#    preserving the do-not-abort semantics the step needs (Phase 153).
gh pr checks "<PR>" --watch --fail-fast || echo "checks reported non-zero — not the verdict; continue to command 5"
# 4b. DID ANY CHECK ACTUALLY REGISTER? Command 4 cannot tell you: it exits non-zero both on a
#     failing check and on a PR that has none, so its `|| echo` tail carries a repo-with-no-checks
#     and a checks-have-not-registered-yet through to the merge identically. Count what command 4
#     was waiting on. `statusCheckRollup` is deliberately the SAME data set `gh pr checks` reads —
#     a union of CheckRun AND StatusContext — so this counts GitHub Actions and the Status API
#     alike, and resolves the PR head itself rather than making you transcribe a SHA.
gh pr view "<PR>" --json statusCheckRollup --jq '.statusCheckRollup | length'
# 5. confirm mergeability, then squash-merge (blocks until landed; deletes the remote branch)
gh pr view "<PR>" --json state,mergeStateStatus --jq '{state, mergeStateStatus}'
gh pr merge "<PR>" --squash --delete-branch
# 6. THE VERDICT. Run this as its own command, after the merge, always — the merge command's
#    exit status and stderr are NOT the verdict (see the note below). Only `state` is.
gh pr view "<PR>" --json state,mergedAt --jq '{state, mergedAt}'
```

> **Command 4b is a gate, and `0` is not a green light.** Read its number before running command 5, and route on three states, not two:
>
> - **a count ≥ 1** — checks registered and command 4 already waited for them. Proceed to command 5.
> - **the count is `0`** — **STOP. Do not run command 5.** This is *could not measure*, and it covers two different repositories that this step cannot tell apart: one with no CI configured at all, and one whose checks have simply not registered on this head yet. **Registration latency is an ordinary condition, not an incident** — measured by a consumer at roughly 30 minutes across an `opened` and a first `synchronize` event, with the checks then registering on a second `synchronize` and all passing. A repo protected by a server-side ruleset will refuse the merge anyway; one protected only by `enforce_admins`, or one where the actor holds admin bypass, will not. **The merge is the irreversible half, so the unmeasured state resolves against merging.**
> - **The probe itself errors** (network, auth, a `404` on a head SHA you mis-transcribed) — also *could not measure*. Same answer: stop.
>
> **Why this reads `statusCheckRollup` and not `commits/<sha>/check-runs`.** The REST check-runs endpoint counts **only** GitHub's Checks API. A repository whose required checks arrive through the older **Status API** — Jenkins, Buildkite, CircleCI classic, anything posting commit statuses, which is precisely what "required status checks" was built for — has `check-runs.total_count: 0` on a **fully green, fully registered** PR. Measured on a real PR head carrying one passing GitHub Actions check: `check-runs` **1**, `commits/<sha>/status` **0**, `statusCheckRollup` **1** — Sysop is the Checks-API case, and the mirror image is a consumer this gate would have blocked on every single run, with both of its stated remedies pointing the wrong way (waiting never helps, and the ruleset probe answers *yes, checks are required*). **A gate that cannot be satisfied is worse than the hole it closes.** `statusCheckRollup` is the union type — `CheckRun | StatusContext` — which is why it is the right question and why it matches command 4 rather than second-guessing it.
>
> **What to do at a `0`.** Report the PR URL and the head SHA, and hand the operator the one distinction the probe cannot make: whether the repository *has* required checks. That is a question about configuration, answered by `gh api "repos/{owner}/{repo}/rulesets"` or the branch-protection settings page — not by waiting longer. **If it answers *yes, checks are required* and the count is still `0` after command 4 returned, suspect the count before you suspect the repo**: that combination is the one shape this probe cannot produce from an honest reading, and it means the rollup and the requirement disagree. If checks are configured, re-run command 4b by hand after a few minutes; when it prints a non-zero count, resume at command 5. **`/review-close` does not need to be re-run for this, and re-running it does not help** — under the integration-branch shape a fresh run cuts a *new* branch and opens a *new* PR, whose head inherits exactly the same registration condition; under the PR-reuse shape it lands on the same PR again. Neither makes a check register.
>
> **Why there is no polling loop here.** A `while`/`sleep` retry would be the obvious shape and it is not available: `sleep` is in no seeded allow-rule and not in the harness's documented read-only set, and a loop around a runtime-discovered condition binds no rule at all (§ Invocation shapes). Re-invoking command 4's `--watch` is not a substitute either — with zero checks registered it returns *immediately*, which is the whole defect. The wait is the operator's, deliberately, and it is one re-run of one bare command.

> Here `$(git rev-parse --abbrev-ref HEAD)` is safe and non-tautological: HEAD was already asserted against a non-HEAD-derived value in Step 1 of this same block, so by this line it is *known* to be the right branch. It is a lookup key, not a guard.
>
> **PR-reuse shape only — pin the head commit.** The integration-branch shape merges a branch it just created under a unique timestamped name that nothing else writes to. A reused branch is a long-lived branch someone else may push to between your push and your merge, so pass `--match-head-commit "$(git rev-parse HEAD)"` on the merge and let it refuse rather than squash-merging content you never verified. (Requires a reasonably current `gh`; if your `gh` rejects the flag, re-read `gh pr view --json headRefOid` and compare by hand before merging.)

> **A `fatal:` from `gh pr merge --delete-branch` does NOT mean the merge failed (internal tracker #208).** `--delete-branch` deletes the **local** branch as well as the remote one, so after the remote squash lands, `gh` switches the local checkout to the base branch and tries to fast-forward it. **In the integration-branch shape that fast-forward cannot succeed:** Step 4-pre cherry-picked every local-only `main` commit onto the integration branch, so those commits exist twice at different SHAs and `origin/<default branch>` is not a descendant of local `main` after the squash. `gh` reports it as:
>
> ```
> fatal: Not possible to fast-forward, aborting.
> ! warning: not possible to fast-forward to: "main"
> ```
>
> preceded by a block of `hint: git merge --no-ff` / `hint: git rebase` noise. That is **expected, benign, post-merge local housekeeping**, not a merge failure — `gh` swallows the error and the local branch is deleted anyway. It fires for every `pr` consumer that used `/claim-task` (its `open → in_progress` flip commits to local `main`) or whose Step 1b saved `review_tasks.md`, which is nearly all of them.
>
> **In the PR-reuse shape it does *not* fire** — reuse condition 3 requires local `main` to hold nothing the approved branch does not already carry (**not**, since Phase 219, that `origin/<default branch>..<default branch>` is empty — the widened form admits a branch that was brought up to date with `git merge <default branch>`, and such a branch leaves real local-only commits on `main`), so local `main` is an ancestor of `origin/<default branch>` and `gh`'s fast-forward succeeds. Expect the message in one shape and not the other; in neither shape is it the verdict.
>
> **Run command 6 regardless of what command 5 exited with** — that is the entire point. If your shell aborts the block early, re-run the state probe on its own; the verdict is unchanged either way. Do **not** write `gh pr merge … || true`: `gh` reports genuine failures through that exit status too, and masking it buys nothing when the next command already decides the outcome.

##### 4d-1. Stuck-PR handling (report + STOP, never force-merge)

**The trigger is PR state, never the merge command's exit status or stderr.** The PR is **not merged** if the post-merge `gh pr view "<PR>" --json state` (command 6 above) reports anything other than `MERGED`. Typical causes: a required check failed (`gh pr checks` reported a failing check) or `gh pr view` shows `mergeStateStatus: BLOCKED`/`DIRTY`. **A third cause is not a stuck PR at all and is handled before the merge, not here: command 4b reported `total_count: 0`.** That is the could-not-measure state, this sub-step never sees it — by construction, since it classifies a merge that already ran — and it is the one arm of the three where nothing has landed and nothing needs unwinding. **Do not re-route a `0` into this section's recovery advice**: there is no failing check to fix, no `BLOCKED`/`DIRTY` state to rebase out of, and re-running `/review-close` inherits the condition rather than clearing it. Stop at command 4b and follow its note. Do **not** key this branch on `gh pr merge` "refusing" — under `pr` policy that command routinely prints `fatal: Not possible to fast-forward, aborting.` *after a merge that succeeded* (see the note above, internal tracker #208), and reading that as a refusal strands branches, worktrees, and `sysop/runtime/locks/` behind a close-out that actually landed. When `state` is genuinely not `MERGED`:

- **Report** the PR URL and the failing check name(s), then **STOP** — do not force-merge, do not fall back to a direct `git push origin <default branch>`, do not loop. Authority to merge belongs to the PR's required checks, not this skill.
- Leave the integration branch, the feature branches, the worktrees, and the `sysop/runtime/locks/` **in place**. **Skip Step 6 entirely** this run — its cleanup is gated on a confirmed merge (see Step 6's merge-policy gate). The human (or a follow-up `/review-close`) fixes the check and re-runs.
- Re-running is safe and idempotent **in the integration-branch shape**: the next `pr`-policy run cuts a **new** integration branch from `origin/<default branch>` and re-sweeps the same still-unpushed local-`main` commits, so nothing is double-applied. The stuck branch is left orphaned but harmless — delete it by hand (`git branch -D <branch>` + `git push origin --delete <branch>`) once its replacement merges.
- **In the PR-reuse shape the recovery is different, and the sentence above does not apply.** There is no integration branch to orphan and no new one to cut: the stuck PR is the consumer's own, still open, now carrying the Step 4b/4c commits, and a re-run's probe finds that same PR again and lands on it again. That re-run is still safe — `close_batch.sh` is idempotent (its `sed` substitutions no-op on already-`Merged` batches) and Step 4c finds no pending-docs the second time because the first run deleted them, so it skips consolidation rather than double-applying it. What it is *not* is self-healing: re-running cannot clear a red required check. Fix the check, then re-run; or if the branch has become unmergeable (`BEHIND`/`DIRTY`), rebase it onto `origin/<default branch>` and push, which makes reuse condition 5 hold again. If you would rather stop reusing it, delete nothing — just let the next run fail condition 5 or close the PR by hand, and the integration-branch shape takes over.

On a confirmed merge — `gh pr view "<PR>" --json state` reports `MERGED`, whatever the merge command's exit status or stderr said — continue to Step 5, then Step 6 cleanup.

**If a `gh pr` command is silently denied** (auto-mode classifier), **no hook will surface the escape for you — construct and relay it yourself.** The Phase 36 `PermissionDenied` hook matches three `git` shapes only (protected-branch push, `--delete` push, protected-branch commit); a `gh` command runs the matcher loop like any other and every matcher returns no match, so a denied `gh pr list` / `create` / `checks` / `view` / `merge` produces a bare denial with nothing attached. **This is the `pr`-policy mainline, not an edge case** — under `§ Merge policy: pr` every close runs through `gh pr`. Ask the user to type the literal `!`-prefixed command at the next prompt (`! gh pr merge "<PR>" --squash --delete-branch`, and so on per command), exactly as Step 3 does for a denied verification command. It is *not* the same pattern as the `direct`-policy push above: that one is hook-covered and this one is not. Do **NOT** use `AskUserQuestion`.

## Step 5: Verify Staging Deployment

If the project has a deploy-on-push pipeline (Firebase App Hosting, Vercel, Fly.io, Cloud Run + Cloud Build trigger, etc.), the post-push deploy is part of the merge gate.

1. **If a deploy pipeline is configured**, wait for the build to finish and capture its status. Use whatever CLI fits the platform (`firebase apphosting:builds:list`, `gcloud builds list`, `vercel ls`, etc.) or the platform's web console.
2. **Run any project-defined post-deploy smoke command.** Configure this in `<project>/CLAUDE.md` under a § "Post-deploy verification" section — typical shapes are a Playwright smoke test against the staging URL (`BASE_URL=<staging URL> npx playwright test ...`), a curl on a health endpoint, or a synthetic monitor check.
3. **Manually verify** the app loads and a healthcheck URL responds (`<staging URL>/<healthcheck-path>`).

**If staging is broken:** do NOT proceed to cleanup. Open a `fix/` branch immediately.

Skip this step only if the pushed changes are docs/config only with no code or schema changes, OR if the project has no deploy pipeline configured.

## Step 6: Clean Up

**Merge-policy gate (Step 4-pre).**
- **`direct` policy** — Step 4d already pushed `main`; run the cleanup below as usual.
- **`pr` policy** — run cleanup **only if Step 4d's post-merge `gh pr view --json state` reported `MERGED`.** If 4d-1 reported a stuck PR (red check / `BLOCKED`), **skip Step 6 entirely** — the feature branches, worktrees, and `sysop/runtime/locks/` must survive so the work is recoverable once the check is fixed. When the PR did merge, first re-sync local `main`, then run the `pr` per-branch cleanup below:
  ```bash
  git checkout <default branch>
  git fetch origin <default branch>
  # Gate the reset on a clean TRACKED tree. `git reset --hard` discards every
  # uncommitted modification to a tracked file in this checkout — not only the
  # pre-merge commits the note below explains. Untracked files are NOT at risk
  # (`reset --hard` leaves them), which is why this tests `git diff HEAD` and not
  # a bare `git status --porcelain`: an untracked scratch file is ordinary in a
  # live repo and would refuse every close.
  git diff --quiet HEAD -- && echo "CLEAN — safe to reset" || echo "DIRTY — STOP, see below"
  ```

  **If that printed `DIRTY`, do not run the reset.** Report the file list (`git status --porcelain --untracked-files=no`) and ask the user to commit or stash. **Resume at this gate, not at the top of the skill** — the PR has already merged by this point, so nothing before Step 6 may be repeated: re-run `git diff --quiet HEAD --`, and continue from the reset when it reports `CLEAN`. (Do not re-enter at Step 4-pre. Its PR-reuse probe requires `origin/<default branch>..<default branch>` to be empty, which is false here by construction — local `main` still carries the pre-merge commits the reset exists to discard.) **Do not stash on their behalf** — a stash this skill creates is consumed by no later step, so it converts a visible refusal into work parked where nobody looks. Two reasons the gate belongs *here* rather than at Step 1: Step 1a's `dirty` classifier never covers this checkout (it excludes the primary checkout by path identity, whatever branch that checkout holds), and Step 5's staging-deploy wait is a long idle window — exactly when a human is most likely to have edits open, so a Step 1 reading would already be stale.

  > **Narrower than the shipped convention, deliberately.** Both shipped maps name `git reset --hard` by name: `convention_map.md` § *Destructive command gating* requires it "be preceded by an explicit 'ask the user to confirm' instruction in the skill text", and `security_map.md` § *Confirmation gates on destructive operations* requires "an explicit confirmation step in the skill text". This gate confirms *conditionally* — it refuses only when the reset would actually destroy something — because the reset is either a no-op or a load-bearing re-sync (see the both-shapes note below), so an unconditional prompt would land on every close of the dominant `pr` path and buy nothing in the clean case. The conventions' purpose is met; their literal reading is not. Stated rather than silently narrowed.

  ```bash
  # local main's pre-merge commits are now inside the squash. Comment on its own
  # line: `Bash(git reset --hard origin/<default branch>)` is an exact-match rule and whether
  # the matcher strips a trailing comment is undocumented (Phase 152).
  git reset --hard origin/<default branch>
  ```

  **Integration-branch shape only — then drop the integration branch.** `$INTEGRATION_BRANCH` was set two shell calls ago and HEAD has already moved back to `main`, so do not reference it. Re-derive the name instead — the local branch still exists at this point, so it is a lookup, not a guess:
  ```bash
  git branch --list 'merge/review-close-*'
  ```
  Then delete it by its literal name, **quoted** (unquoted, `<…>` is a redirection to bash, not a placeholder):
  ```bash
  git branch -D "merge/review-close-<run id>" 2>/dev/null || echo "integration branch already deleted by gh pr merge --delete-branch"
  ```
  `gh pr merge --delete-branch` removes both the remote and (once HEAD left it) the local integration branch, so it is often already gone — hence the tolerant tail. It is `|| echo`, not `|| true`: `echo` IS in Claude Code's documented built-in read-only set while `true` is not, so the compound stays authorized. The `2>/dev/null` is fine either way — a redirection is not a command separator, so it never cost the `Bash(git branch -D:*)` match; only the `|| true` did (Phase 153).

  **Do not run that line at all in the PR-reuse shape** — there is no integration branch, and the reused branch is handled by the per-branch cleanup below.

  > **Run the `git reset --hard origin/<default branch>` in both shapes once the clean-tracked-tree gate above passes — but know why it matters in each.** `gh pr merge --delete-branch` *attempts* this re-sync itself. **Integration-branch shape:** it fails, because local `main` has diverged by construction (see Step 4d's `fatal:` note, internal tracker #208) — here the reset is load-bearing, and treating `gh` as having already done it leaves local `main` on pre-merge commits now duplicated inside the squash. **PR-reuse shape:** it succeeds, because reuse condition 3 required local `main` to hold nothing the approved branch does not already carry (**not**, since Phase 219, that `origin/<default branch>..<default branch>` is empty — the widened form admits a branch that was brought up to date with `git merge <default branch>`, and such a branch leaves real local-only commits on `main`) — here the reset was described as a harmless no-op, and Phase 219's round measured that false for the widened condition 3: with a merge-updated branch the reuse shape is taken while local `main` still holds unpushed commits, `gh`'s fast-forward fails with the same `fatal:` as the other shape, and the reset **moves** `main` rather than doing nothing. Run it; it is load-bearing in both shapes now. Internal tracker #204's incidental note ("`gh` fast-forwards `main` itself, so Step 6's reset was already a no-op") was reported from a cycle that met condition 3, so it was **right about that cycle and wrong as a general rule**; internal tracker #208, from the same reporter, is the other shape. Neither claim generalizes — which is why this step is stated per shape rather than picking a winner.

> **Lock-as-real-time-signal invariant (`pr` policy).** Step 4c removes each closed task's `sysop/runtime/locks/<TASK-ID>.lock` from disk on the integration branch, before the PR merges — so there is a brief window where, on `main`, the task is still `in_progress` (the `done` flip rides the unmerged PR) with no lock. This does **not** reopen the task for the autonomous paths: `/auto-build` and `next_task` only ever claim `status: open` tasks, so neither can pick it up. **Amended by Phase 159b — the unqualified form of this sentence ("an `in_progress` task is never claimable regardless of its lock") is no longer true.** `/claim-task` gained a third entry state, and `in_progress` + no lock is exactly its `resumable` signature — which this window manufactures for a task that is *finished*. That is why `resumable` **stops and asks** instead of continuing: an explicitly-named `/claim-task <TASK_ID>` during this window would otherwise re-claim already-reviewed work. The other visible effects are a transient `/sitrep` "in_progress without lock" drift flag and a `validate_tasks.py` Invariant 9 error during the in-flight (or stuck-PR) window, both of which clear when the PR merges and the `done` flip lands. No action needed beyond not re-claiming. The same pre-merge timing applies to the task's **parked marker(s)** (`sysop/runtime/parked/<TASK-ID>__*.md`, removed by the same Step 4c cleanup) — with one honest asymmetry: a lock is trivially recreatable (`claim_task.sh --lock`), but a marker's content (the park's plan + adversarial verdict, never committed) is not. Accepted anyway: by the time Step 4c runs, the park was already resolved — the resume that produced this close consumed the verdict — so a stuck PR needs the *code* recoverable (the integration + feature branches Step 4d-1 leaves in place), not the historical park record. A consumer who wants park history durably should copy `parked/` entries somewhere tracked before closing.

**HARD RULE — do not delete a branch whose pending-doc Step 4c step 1c held back (`Q-327`).** This applies under **both** policies below and is checked before either list is built. A `user_action` hold keeps the doc so a later run can consolidate it; that doc carries a `branch:` field, and step 1b resolves it with `git rev-list --count "<branch>" "^HEAD"`. **Delete the branch and the next close does not resume — it halts**, on step 1b's *"If the ref no longer resolves, stop and ask — do not guess in either direction"*, which is the same self-inflicted stop the cherry-pick blockquote above step 1c already describes. The carrier is the doc **and** the branch; holding one without the other converts a deliberate hold into a hard stop on every subsequent close.

So: before cleaning up, list the `branch:` values of every doc still in `sysop/runtime/pending-docs/` and **exclude those branches from both lists below**. Report them in Step 8's `Remaining:` as retained-for-a-held-doc, with the task id waiting on them, so an operator does not read them as leaked. They are deleted by the close that finally consolidates the doc — the ordinary path, one run later. This is the same principle Step 4d-1 already applies when a PR is stuck (*"Leave the integration branch, the feature branches, the worktrees, and the `sysop/runtime/locks/` in place. Skip Step 6 entirely"*): cleanup is gated on the work being finished, and a held task's work is not.

**`direct` policy — per-branch cleanup.** For each merged feature branch (worktrees already removed in Step 3b):
1. Delete the **remote** branch first: `git push origin --delete <branch>` (if it exists remotely).
2. Delete the **local** branch: `git branch -d <branch>`.

**Why this order matters (BeanRider ISSUE-0021).** Step 4a rebases the feature branch onto main, which rewrites its SHA. The local branch's tracked upstream (`refs/remotes/origin/<branch>`) still points at the *pre*-rebase commit, so `git branch -d` refuses with `not fully merged to refs/remotes/origin/<branch>, even though it is merged to HEAD` — git's safe-delete check compares against the upstream ref, not against `main`. Deleting the remote first removes the upstream pointer, so the subsequent `-d` falls back to checking against `HEAD` and succeeds. Do **not** use `-D` (force-delete) — the safe-delete refusal is correct behavior given the upstream check; the fix is to drop the upstream first, not to bypass the check.

**If `git push origin --delete <branch>` is silently denied** (BeanRider ISSUE-0033, classifier hard-codes destructive-flag protection on `--delete`/`--force` regardless of allow-rule glob), the Phase 36 `PermissionDenied` hook surfaces the `! git push origin --delete <branch>` escape command — with the venv-prefix variant when a `.venv/` directory is present. Follow the hook's guidance and relay to the user. The subsequent `git branch -d <branch>` runs in-band without classifier interference (local-only, no remote contact). Do **NOT** use `AskUserQuestion`.

**`pr` policy — per-branch cleanup** (only after the PR merged; the local-`main` re-sync and, in the integration-branch shape, the integration-branch drop are already done in the merge-policy gate above). Each **merged** feature branch reached `main` through a **squash** — in the integration-branch shape by being rebased onto the integration branch and ff-merged before that branch's PR squashed, and in the PR-reuse shape by being the PR's own head. Either way the branch is provably contained in the squash commit but is **not** an ancestor of it, so `git branch -d` would refuse with "not fully merged." Force-delete here; the content is safely in `main`:

> **`-D` is licensed by containment, and a 4a-SKIP'd branch breaks that licence — check merge status, do not iterate "approved".** This list previously read *"each **approved** feature branch"* and asserted that it *"reached `main` through a squash"*. A branch that Step 4a aborted-and-skipped is still approved, is not Step 2a `dirty`-SKIP'd, and is not rejected — so it fell through every carve-out below and was force-deleted with its work in no squash and nowhere else. Its worktree was already removed at Step 3b, so `-D` was the last reference to it. **`direct` never had this hole** because its list iterates *merged* branches and safe `-d` refuses on an unmerged one; the bypass is what removed the backstop here, which is why the guard has to be explicit rather than inherited.
>
> **Key this on the 4a-SKIP verdict Step 4a recorded, and do NOT re-derive containment here.** Iterate the branches Step 4a actually merged; a 4a-SKIP'd branch is handled by its own block below and never reaches this list. An earlier draft of this step instead prescribed `git rev-list --count <branch> ^origin/<default branch>` as a containment re-check, and **that check can never return its pass value.** `rev-list ^origin/<default branch>` *is* an ancestry test, and the paragraph above says in its own words that a squash-merged branch is "**not** an ancestor of it" — so it scores non-zero for a correctly merged branch and non-zero for a 4a-SKIP'd one alike: zero discriminating power, a permanently inert cleanup, and every clean close reported as suspect. Verified against a real squash rather than reasoned: `git branch -d` refuses, `rev-list --count` returns non-zero, `merge-base --is-ancestor` is false, and `git cherry` prints `+` on every commit because patch-ids do not survive a squash. **After a squash there is no ancestry-shaped containment test** — that is exactly what makes safe `-d` "meaningless" here, so a check built from ancestry cannot be the fix. (Step 4c's sibling filter is sound because it runs *pre-squash* against `^HEAD`, where ff-merge preserves ancestry; the equivalence an earlier draft asserted between the two sites does not hold. That clause is load-bearing and narrow: it licenses the filter **only** where an ff-merge happened. A cherry-pick is not an ff-merge and breaks the filter the same way a squash would — see Step 4c step 1b, which now carries a `git cherry` fallback for it. This sentence was never wrong about that case; it was silent about it, which read as an exemption.)

1. Delete the **local** branch: `git branch -D <branch>` (the safe `-d` check is meaningless against a squash — the branch's commits are in the merged PR).
2. Delete the **remote** branch **only if it was pushed and still exists**: `git push origin --delete <branch>`. Feature branches created by `/claim-task` are usually local-only under `pr` policy (the integration branch is the only thing pushed), so skip this when the branch has no remote tracking ref. **Record every deletion that does not succeed, here, as it happens** — branch name and the error — and carry the list to Step 8's `Remaining:` remote-branch row. That row had no producer at all until Phase 219, so it was answered from intent or left blank, and a branch left behind on the remote is exactly the thing nobody notices without a row naming it.

**Under the PR-reuse shape both of the above are usually already done for you.** The reused branch *was* the PR's head, so `gh pr merge --delete-branch` deleted it remotely, and it deletes the local branch too once `gh` has switched HEAD off it. Verify rather than assume — `git branch --list <branch>` and `git ls-remote --heads origin <branch>` — and run only the deletions that are still outstanding. A `git push origin --delete` against an already-deleted remote branch fails with `remote ref does not exist`; that is cleanup noise, not an error worth halting on.

For each **SKIP'd** branch (Step 2a verdict — Step 1a classified the worktree as `dirty`):
1. Leave the worktree, the `sysop/runtime/locks/<TASK_ID>.lock` file, and the branch fully in place — do NOT touch anything.
2. Carry the SKIP entry into Step 8's report so the user sees the paused-work list with its file count and worktree path.

For each **4a-SKIP'd** branch (approved, but Step 4a could not merge it):
1. Leave the branch and its `sysop/runtime/locks/<TASK_ID>.lock` fully in place under **both** policies — do NOT delete it, and do NOT force-delete it. Its work is in no squash and its worktree is already gone (Step 3b removed it before the merge was attempted), so the branch ref is the only thing holding the commits.
2. Its pending-doc stays in `sysop/runtime/pending-docs/` — Step 4c's merged-branch filter left it there deliberately, and the `rmdir` at the end of this step is a no-op while it is present.
3. Carry the entry into Step 8's report with the conflicting file named, so the next cycle knows what to resolve.

For each **rejected** branch that still has a worktree:
1. Leave the worktree and branch in place for future work.

**Hard guard against worktree removal in this step (BeanRider ISSUE-0016).** Step 6's flow as documented does not call `git worktree remove` — worktrees for merged branches are gone after Step 3b, and worktrees for SKIP'd / rejected branches are explicitly preserved. If a future evolution of this skill adds a worktree-cleanup pass here, that pass MUST refuse to remove any worktree Step 1a classified as `dirty` AND MUST NOT use `--force`. The current shape avoids the trap structurally; this note exists to keep it that way as the skill evolves.

Remove `sysop/runtime/pending-docs/` directory if it still exists and is empty: `rmdir sysop/runtime/pending-docs 2>/dev/null`

## Step 7: Friction Capture

Append-only, never blocks close-out. The point is the *prompt at the right moment* — while live context still has the silent-deny / shell-escape / prompt-rewrite memory intact. Retrospective capture in a `/clear`'d session doesn't work (the signal is ephemeral and dies with the conversation).

**Witness-limited:** log only friction you witnessed in THIS session. Don't fabricate. Don't extrapolate from git history. Don't include friction from prior `/clear`'d sessions even if it's still in auto-memory — that channel is unreliable for this purpose. If the user mentioned friction in conversation that you didn't observe yourself, prompt them to add it manually instead.

**Recall hooks** (use these to anchor your reflection — anything from this cycle?):

- Silent-deny classifier rejections (`auto`-mode rejected a Bash command with no UI prompt, you had to ask the user for an `!`-shell-escape)
- Parent-side prompt rewrites (you rewrote a skill's subagent prompt mid-flow because the skill's wording assumed a different project shape)
- Subagent confusion about `<project>/CLAUDE.md` subsection names (subagent couldn't find the section the parent prompt told it to look in)
- `!`-shell-escape moments (the user had to run a command themselves because the agent couldn't)
- Install-step failures (`bash sysop/scripts/run_checks.sh` errored on a hint pointing at a file that doesn't exist; `install.sh` wrote to a path that conflicted with project content)
- Skill steps that referenced files / paths / commands that don't exist in this project (Step 3 verification pointing at `frontend/` when there isn't one, Step 4 referencing a `pytest` invocation when the project uses something else)
- Anything Sysop shipped — a skill file, an installer behavior, a documented workflow step, a check rule — that didn't work as documented

**Procedure:**

1. **Find the friction log:** `sysop/SYSOP_ISSUES.md` — inside the `sysop/` vendor dir at the consumer-repo root (Phase 128; NOT under `.claude/`, and no longer at the bare repo root). If a pre-Phase-128 install left it at the root, append there instead rather than treating it as missing. If neither exists, emit one line: `note: sysop/SYSOP_ISSUES.md not present — re-run bash install.sh to seed. Skipping friction capture.` and proceed to Step 8.

2. **Decide whether to log:** if no friction occurred this cycle, **move on silently to Step 8**. Do NOT append a "no friction this cycle" placeholder — that adds noise without signal.

3. **Determine the next ISSUE number:** read the file, find the max existing `ISSUE-NNNN` number, increment by 1. If the file has no ISSUE entries yet, start at `ISSUE-0001`. If you can't parse the file (corrupted, unreadable), emit one line: `note: could not determine next ISSUE number from <the path step 1 resolved> — please file manually. Skipping friction capture.` and proceed to Step 8.

4. **Append the entry** newest-first (immediately after the `<!-- Entries below. Newest first. -->` marker, or after the `---` separator if no marker exists). Use the Template block's structure verbatim — `Status: Open`, today's date, the witnessed-symptom in `### What happened`, your diagnosis with file paths in `### Diagnosis`, a concrete proposed fix in `### Proposed fix`, a repro recipe in `### Verification`, and what unblocked the user in `### Workaround in <consumer>`.

5. **Multiple frictions:** if more than one independent friction occurred, append multiple entries with sequential numbers. Each gets its own block.

6. **If friction was resolved mid-cycle** (e.g., user manually fixed a missing permission rule): still log it. Mark `Status: Fixed in <consumer> <date>` and put the resolution in `### Diagnosis` — even resolved-in-cycle friction is signal that Sysop's seeded ruleset / templates are incomplete.

**Positive signal (`[good]`) — same moment, same reflex:** friction isn't the only signal worth catching at close-out. If something Sysop did *notably well* this cycle stood out — a guardrail that fired correctly, a clear error that unblocked you, a step that just worked under an unusual setup — capture it too, so a later change doesn't quietly "fix" it. Prompt once: *"Anything Sysop did that worked notably well and is worth protecting from a future change?"* If yes, append a `[good]` entry using the positive-signal template in the log step 1 located (`sysop/SYSOP_ISSUES.md`, or the bare-root copy if step 1 resolved there) (`## GOOD-NNNN — <title> (<date>)  [good]`, `Status: Good — keep`, a `### What worked` naming the skill / installer step / guardrail). Same witness-limited discipline — only what you observed this session, don't fabricate, don't extrapolate. No standout this cycle → say nothing and move on. This is what a tester round otherwise drops: the maintainer learns what to fix but not what to protect. (`[good]` entries are captured locally; **send them upstream with `/share-wins`** — the positive-signal sibling of `/report-issues`, which batches a round's wins into one comment on the Sysop repo's Wins discussion, per-entry consent, and flips each shared entry to `Status: Shared` so re-runs never double-post.)

This step is best-effort. If anything goes wrong (file unwritable, you're unsure which friction qualifies), prefer a single one-line note and move on rather than blocking close-out. The user can always file manually.

**Capture here, send with `/report-issues`.** This step only *captures* friction into `SYSOP_ISSUES.md` (local, project-owned). To get an entry upstream to the Sysop maintainer, the transport half is the `/report-issues` skill — it renders each `Open`/`Prompt-ready` entry as a GitHub issue, files the ones you consent to (per-entry) against the Sysop repo, and flips each filed entry to `Status: Filed to Sysop` with a `**Filed:** <url>` back-reference. That flip is why re-running `/report-issues` never double-files. Nothing here depends on it — capture stands alone — but a tester running Sysop should send periodically rather than let the log accrue unseen.

## Step 8: Report

Summarize what was done:

```
Review Complete.

Pushed:        <under `direct`: the SHA Step 4d confirmed. Under `pr`: the squash-merge
               SHA and its PR number — "<N> commits" is not a quantity that exists on
               that path, where `main` gains exactly one commit however many merged.>
Branches:      <merged list> (or "none")
Batches:       <the batch set Step 4b determined, and what it did — "closed N1, N2"
               / "none this cycle — 4b skipped" / "N closed, M failed — still open">.
               Never blank: a skipped Step 4b used to leave no trace anywhere in this
               report, so a close that silently never reached it read exactly like one
               that had no batches to close.
Docs:          Consolidated <N> pending-docs files (or "none" / "legacy docs: commits")
Manual smoke:  <N confirmed, N driven, N waived> (or "none required")
Verification:  pre-merge <ran | skipped: doc-only | skipped: no changed-file list>;
               merged-tree (4a-post) <ran on <merge target>: N commands
                                      | ran nothing: why | not reached: why
                                      | TIMEOUT: <command> — killed, so it returned no
                                        verdict. The tree is UNVERIFIED: neither passed
                                        nor failed, and never folded into "ran N commands".>
               pre-scan <clean | clean, but N blocking checks degraded — <ids>
                         | ran via the consumer's list
                         | skipped: sysop/scripts/run_checks.sh absent
                         | could not run — <tool's own first error line>
                         | FAILED — new blocking finding <check-id>
                         | FAILED — blocking stage did not run: <check-id>>
                        — 4a-post item 3a. A separate element because it is a
                        separate gate: the merged-tree element above reports the
                        CONSUMER's declared list, this one reports the promoted
                        checks, and folding them would lose which of the two refused.
               <per-surface skips, e.g. "skipped frontend — not in this run's changed files">
Unverified surfaces: <changed code files no detected surface claimed> (or "none")
Conventions:   <N checked, N skipped (doc-only)> (or "none to check") — Step 2b step 3
Security map:  <N checked, N skipped (no map match)> (or "none to check") — Step 2b
               step 3b. Its own line, never folded into `Conventions:` above: a
               cycle where every target skipped the security twin and every
               target passed the convention check would otherwise read exactly
               like one where both fleets ran and both approved.
Test decisions: <N verified, N waived, N not-owed, N held-for-fix, N unreadable, N doc-only> (or "none to verify")
Orchestrator artifacts: <Step 2e's per-branch block, verbatim> (or "none — no branch
               under review resolved to a claim"). Distinct from `Claim artifacts:`
               below, which is Step 4c's REMOVAL tally: this line is Step 2e's
               pre-merge READ. It is a report — no line here moved a verdict, and an
               `absent` row means UNKNOWN, never that a stage was skipped, because
               sysop/runtime/ is gitignored and the hook is Claude Code only.
Staging:       <verified / skipped / broken>
Superseded PRs: <branch #PR, …> (or "none") — published branches whose own PR this
               close bypassed by merging through the integration branch. Still open,
               still pointing at valid commits, no longer the path to `main`. From
               Step 4a item 4; GitHub does not close these, a human does.
Locks cleaned: <the `LOCKS_REMOVED` ids Step 4c printed> (or "none")
               <and, when non-empty, `already absent: <LOCKS_ALREADY_ABSENT ids>`>
Parked markers: <the `PARKED_MARKERS_REMOVED` filenames Step 4c printed> (or "none")
Claim artifacts: <the `CLAIM_ARTIFACTS_REMOVED` ids Step 4c printed> (or "none")
               <and, when non-empty, `could not remove: <CLAIM_ARTIFACTS_FAILED>` — a
                leftover under a gitignored path, not a failed close>
Friction:      <N entries appended to SYSOP_ISSUES.md> (or "none" / "log missing")
Signal:        <N [good] entries appended> (or "none")

Documentation written:
  ✓ PROJECT_STATUS.md §6: <N> new entries, <N> rotated out    (if any; say "consolidated" when the
                                                              consolidation clause wrote one entry for many)
  ✓ CHANGELOG.md:         <N> entries         (if any — count ALL THREE writers: the bugfix
                          routing row, the Consolidation clause, and the Rotation check. A count
                          taken from the routing table alone under-reports the other two.)
  ✓ tasks/index.yml:      <the `CLOSED_IDS` Step 4c printed>  (if any — status flipped to done, body moved to archive/)
                          <and, when non-empty, `not in index: <NOT_IN_INDEX ids>` — ids this close was
                           asked to close and could not find. Never omit this line by choosing the other row.>
                          <and, when non-empty, `held (user_action): <HELD_USER_ACTION ids>` — see Remaining.
                           These three rows PARTITION the ids this close was asked to flip; if they do not
                           add up, the heredoc did not finish and the rows above are incomplete.>
  ✓ UI_Iterations.md:     <N> rows            (if any)

Pending-doc collisions: <N> (or "none")
  - <filename> — main's copy authored by <branch>, worktree's by <branch>. NOTHING was
     collected for the worktree's branch and main's copy was not touched; the branch is
     SKIP'd with its worktree, lock and branch intact. Both docs are still where their
     authors left them. Resolve by renaming one, then re-run; until then neither
     branch's task closes.

Quarantined docs: <N> (or "none")
  - <filename> — <no `branch:` frontmatter | frontmatter would not parse: <error>>;
     moved to sysop/runtime/pending-docs/quarantine/<filename>. Not routed, not deleted.
     No task IDs flipped. Recover by fixing the frontmatter and moving it back.

Held-back docs: <N> (or "none")
  - <pending-doc filename> — branch <name>; held because <reason>. Task IDs NOT flipped to
     done; doc left in place for a later run.
     **Two reasons, and they need different evidence — do not force one into the other's fields.**
     - 1b (unmerged): add `rev-list <count>, git cherry <count> unapplied`. Non-zero is the
       reason. (A doc can be held back WITHOUT a 4a-SKIP — a cherry-picked branch, including
       the `branch: main` doc under `pr` policy, merges fine and still scores non-zero.)
     - 1c (`user_action outstanding: <TASK_ID>`): the branch MERGED, so `rev-list` is `0` and
       printing it here reads as "merged fine" beside "held" — omit it. The evidence is the
       task's flag. Add `branch retained by Step 6` so the two halves of the carrier are
       reported together.

Remaining:
  - <any SKIP'd branches — paused work; include file count + worktree path + recommendation>
  - <any 4a-SKIP'd branches — approved but did NOT merge; name the conflicting file, and say
     the branch + lock are intact, its pending-doc was held back from consolidation, and its
     task was NOT flipped to done>
  - <any rejected branches with reasons>
  - <any tasks HELD on `user_action`. **There are two arms and they are not the same event.**
     ORDINARY (Step 1c): the doc was held back before routing, so `HELD_USER_ACTION` is
     `(none)` — the ids never reach the heredoc — and the evidence is a `Held-back docs:` row
     reading `user_action outstanding: <TASK_ID>`. Say plainly what did and did not happen:
     the code merged, NOTHING was written for this task (no PROJECT_STATUS/CHANGELOG entry,
     no status flip), its body is still under `open/`, its lock is still held, and its branch
     was retained by Step 6's HARD RULE. Name the outstanding step from the body's
     `## User ops` section. ANOMALOUS (the heredoc arm): `HELD_USER_ACTION` is non-empty,
     which means Step 1c did not run or the id list was substituted by hand from a stale run.
     Report it as an anomaly — the doc WAS routed, so entries landed for a task that did not
     close, and step 6 is about to delete that doc. Fix the id list.
     Either way the task closes on a later `/review-close`, after the human performs the step
     and clears the flag with `python3 sysop/scripts/clear_user_action.py <TASK_ID>`; the
     flag-clear alone closes nothing, and `clear_user_action.py` says so in its own output.
     **The invariant to check is the ordinary arm's:** every `user_action` hold must show a
     `Held-back docs:` row AND a retained branch. A hold with neither is a stranded task —
     its carrier is gone and no later run can close it. Do NOT report these under
     "Documentation written" as closed.>
  - <any feature branches RETAINED by Step 6's held-doc rule — name the branch and the task
     waiting on it, so they are not read as leaked. They are deleted by the close that
     finally consolidates the doc.>
  - <any remote branches needing manual cleanup — the deletions Step 6 ATTEMPTED and that
     did not succeed. Step 6 must record each failure as it happens; a row assembled at
     Step 8 from memory of what Step 6 intended is how this slot stayed empty on runs
     that left branches behind.>
```

If `$ARGUMENTS` contains `--dry-run`, perform Steps 1-3 only and report what *would* be done without making changes. **`4a-post` cannot run under `--dry-run`** — it needs the merges — so report the resolved command list and say the merged-tree gate did not run. Do not let Step 3's green stand in for it; that substitution is the defect the two-pass split exists to remove.
