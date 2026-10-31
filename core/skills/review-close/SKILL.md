---
name: review-close
description: Senior review — review pending work, push to origin, verify staging, clean up
argument-hint: "[--dry-run | --prepare [--headless] [--agent <name>] | --resume <run-id> [--headless] [--request-review [--agent <name> [--unattended]]] | --request-review [--agent <name>] | --land <run-id> [--unattended --agent <name> [--headless]]]"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning inline=reasoning -->

Final gate before production. Reviews all pending work (feature branches AND unpushed main commits), pushes to origin, verifies staging, and cleans up.

> **Editing this skill rather than running it?** `REFERENCE.md`, beside this file, carries the
> editor's half: what each load-bearing rule protects, what its loss or softening would change,
> and where it came from. It is not loaded with this file — open it when you are about to change
> a rule, not to run one. Running this skill needs nothing from it.

> **Run this skill in the main conversation, never through an Agent call — and run it once over the set of approved branches, not once per branch.** A run's fixed cost is the same for one branch as for six: in an attended plain run, when the set is one small branch and nothing waits on it, say so and offer to defer the close (`--prepare`, `--resume` and `--land --unattended` ask nothing).

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
from an older release may still carry the hard-coded name; re-run
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

Before doing anything, verify `.claude/settings.json` (with `.claude/settings.local.json`, if present) carries the allow-rules this skill depends on. Under `permissions.defaultMode: "dontAsk"`, a missing rule on `git merge --ff-only` or `git worktree remove` surfaces as an opaque halt mid-merge. Run the `_shared/permission-guard.md` algorithm — including its **step 3 mode check**, which skips the hard stop (but still prints the drift report) when the project declares `bypassPermissions`, where the allow-list is inert.

Read `.claude/settings.json` (and `.claude/settings.local.json` if present) and confirm `permissions.allow` satisfies every rule below:

- `Bash(git checkout:*)`
- `Bash(git fetch origin:*)` — the `_shared/main-push-guard.md` Rule B safe-push sequence fetches `origin/<default branch>` before the Step 4d push, so this is required under **both** merge policies, not just `pr`; under `pr`, Step 4d's record of the merged PR's head (`refs/pull/<PR>/head`) binds it too
- `Bash(git rebase:*)`
- `Bash(git rebase --abort)`
- `Bash(git -c core.editor=true rebase --continue)` — **exact match, and it has to be exact.** Step 4a's conflict route continues a rebase, and a bare `git rebase --continue` opens an editor: with none configured git falls back to `vi`, which in this harness **hangs until the tool timeout** and, when stdin is closed instead, exits 1 leaving the rebase mid-replay — a state Step 4a has no arm for. `-c core.editor=true` is the fix for the case that bites — no editor configured, or one configured through `EDITOR` — though **not** for an ambient `GIT_EDITOR`, which outranks `core.editor` and is measured to win; an autonomous close does not set one. It needs its own rule: `-c` is not one of the wrappers the Bash matcher strips, so `Bash(git rebase:*)` does **not** cover `git -c … rebase` ([permissions reference](https://code.claude.com/docs/en/permissions.md#process-wrappers)). An env-var prefix (`GIT_EDITOR=true git rebase …`) binds no allow rule either — allow rules do not match past an assignment
- `Bash(git merge --ff-only:*)`
- `Bash(git merge --no-ff:*)` — Step 4a's **published** arm. A published branch must not be rebased, so it is taken with a merge commit instead; `--ff-only` does not authorize `--no-ff` (the matcher compares literal text, and these differ from the flag onwards)
- `Bash(git worktree list:*)` — the `--porcelain` worktree enumerations from Step 3b on (the one read-only `git` form Sysop ships a rule for — see `_shared/permission-guard.md` § Notes); Steps 1a and 3c read the worktrees through the two scripts below
- `Bash(python3 sysop/scripts/close_state.py:*)` — Step 1a's worktree classes, Step 1b's `review_tasks.md` shape and Step 1c's archive-rotation pre-check.
- `Bash(python3 sysop/scripts/git_ro.py:*)` — Step 2a step 1's commit list, and every Step 2b reviewer's git in its pinned checkout: read-only git in a worktree of this repository, where `git -C` binds no rule.
- `Bash(python3 sysop/scripts/review_pins.py:*)` — Step 2b's conventions clear, baselines, pinned checkouts, their removal, the post-spawn check and the `core.hooksPath` restore.
- `Bash(python3 sysop/scripts/git_check.py:*)` — Step 2b's check that reviewers can run their git, and Step 2d's lock read.
- `Bash(git worktree remove:*)`
- `Bash(git branch -d:*)`
- `Bash(git push origin:*)`
- `Bash(git add:*)` — Step 4c step 7's shared-doc staging. Those are three plain, unwrapped `git add <path>` commands, which is what makes the wildcard the right shape here: the literal-path rules the template also ships (`git add tasks/index.yml`, `git add review_tasks.md`) cannot cover consumer-authored doc names like `UI_Iterations.md` or a changelog the project keeps under its own name. Note the review skills' Step 9 staging is **not** an exception any more: an earlier build unrolled those loops into one plain `git add -A -- <path>` per path, so `Bash(git add:*)` covers them too. The shapes that still bind no rule are this skill's own runtime-set loops; see § Invocation shapes below
- `Bash(bash sysop/scripts/close_batch.sh:*)`
- `Bash(bash sysop/scripts/run_checks.sh)`
- `Bash(bash sysop/scripts/run_checks.sh:*)`
- `Bash(python3 sysop/scripts/validate_tasks.py)` — Step 4c's final-guard validator run (bare `python3`; the script self-resolves venv PyYAML via its own `sys.path` bootstrap, so this one form serves both venv-only and non-venv consumers)
- `Bash(python3 sysop/scripts/validate_tasks.py:*)` — same with `--quiet` / `--path`
- `Bash(python3 sysop/scripts/review_index.py:*)` — Step 4b's batch-set derivation (`--list --merged`). Bare `python3`, for the same reason as the validator above: the script self-resolves venv PyYAML, so one form serves venv and non-venv consumers. **The command word is load-bearing** — this step once prescribed `bash …review_index.py --list`, which binds no rule *and* cannot run: bash lexes the module's docstring as one quoted word and exits 2 with an empty stdout, indistinguishable from a batch-free cycle.
- `Bash(python3 sysop/scripts/pending_doc_hold.py:*)` — Step 4c 1b's and 1c's hold test (`check`, `check --stamp`).
- `Bash(python3 sysop/scripts/ignored_refs.py:*)` — Step 2a step 3a's and Step 3b step 0b's ignored-file check.
- `Bash(python3 sysop/scripts/clone_sync.py:*)` — Step 1-pre.
- `Bash(python3 sysop/scripts/smoke_detect.py:*)` — Step 3c's smoke-gate detection.
- `Bash(python3 sysop/scripts/pending_doc_collect.py:*)` — Step 3b's pending-docs collect and its rollback.
- `Bash(python3 sysop/scripts/close_index.py:*)` — Step 4c item 4's status flip, `git mv` and the `git add` of the index it rewrote. Those git calls run *inside* the script via `subprocess`, so they bind no Bash rule of their own.
- `Bash(python3 sysop/scripts/feature_branch.py:*)` — Step 2a's landed check (step 0b) and its gitignored-file answers (step 3a).
- `Bash(python3 sysop/scripts/convention_size.py:*)` — Step 2b's convention-section measurement.
- `Bash(python3 sysop/scripts/gate_verdict.py:*)` — Step 2b's verdict lookup and record, both fleets.
- `Bash(python3 sysop/scripts/security_map_filter.py:*)` — Step 2b's security gate and the twin's map copy.
- `Bash(python3 sysop/scripts/claim_artifacts.py:*)` — Step 2e's claim-artifact report.
- `Bash(python3 sysop/scripts/workspace_locate.py:*)` — Step 3b step 0's workspace lookup.
- `Bash(python3 sysop/scripts/smoke_record.py:*)` — Step 3c's smoke-answer recorder.
- `Bash(python3 sysop/scripts/pr_head_check.py:*)` — Step 4a item 1's recorded-head check.
- `Bash(python3 sysop/scripts/close_check.py)` — Step 4c item 5's check of the shared-doc writes. Exact, because it takes no arguments.
- `Bash(python3 sysop/scripts/close_arms.py:*)` — the arm receipt: `begin` before the flag sections, 4-pre's `policy`, 4a's `conflicts`, 4a-fix's `notes`, 2a's `exited`, 2b's `exited`, 3b's `exited`, 4a's and 4a-post's `exited`, 4b's and 4c's `exited`, 3c's `exited`, 4d's `arm`, Step 6's `arm`, a step file's `loaded` and Step 8's `check`.

- `Bash(git -c core.editor=true merge --continue)` — exact match: the published arm's twin of the `rebase --continue` rule above.

**Deliberate non-entries.** (One of them stopped being one — see the end of this paragraph.) Step 3b's pending-docs collect and its rollback used to run as `mkdir -p … && cp …` and a `for … rm -f … done` loop, which bound **no** allow-rule at all: the compound splits into `mkdir` + `cp` command words and neither is in the seeded set, nor are `rm`, `mv` or `cmp`. **A later build rebuilt both as `python3 - <<'PY'` heredocs, which bound `Bash(python3 -:*)`; both are now `pending_doc_collect.py`'s subcommands, which bind its own rule above.** The permission surface got smaller, not larger — one rule replaced four ruleless command words — and the change was driven by correctness rather than permissions: a provenance check is not expressible in that compound. **If some other part of this step ever *does* halt on a denial, nothing rescues it automatically — ask the user for the escape yourself.** The `PermissionDenied` hook matches a push to `origin` of one of the two branch names it **hard-codes** (`main` or `master` — *not* the resolved default branch, so on a consumer whose default is neither, no push matches), a `--delete` push of any branch, and `git commit` on a protected branch; a denied `mkdir` or `cp` falls through its matcher loop and it emits **nothing**, so the denial arrives with no guidance attached. Relay the literal `!`-prefixed command — **the `python3 sysop/scripts/pending_doc_collect.py` command as written, never the retired `mkdir -p … && cp …`**, which has no provenance check and is the form this step removed for the user to type at the next prompt, the same route Step 3 uses for a denied verification command, and never `AskUserQuestion`. Step 3b itself forbids proceeding to the worktree remove with the docs uncollected.

**Additionally, under `pr` merge policy only** (read `<project>/CLAUDE.md § Merge policy`; default is `direct` — see Step 4-pre): the PR-routed flow shells out to `gh` and a few extra git verbs. Require these too **only when the policy is `pr`** — a `direct`-policy consumer does not need them and must not be blocked for their absence:

- `Bash(git cherry-pick:*)`
- `Bash(git merge --no-edit:*)` — Step 4-pre's base merge; neither merge rule above authorizes it (the matcher compares literal text from the flag onwards)
- `Bash(git merge --abort)` — that merge's conflict escape
- `Bash(git reset --hard origin/<default branch>)` — Step 6 re-syncs local `main` after the PR squash-merges. **Substitute the resolved name before comparing:** this is an exact-match rule and `install.sh` seeds it with *this* repository's branch, so on a `master` consumer the shipped rule reads `origin/master` and comparing it against a hard-coded name would report a false miss
- `Bash(git branch -D:*)` — Step 6 deletes the integration + squash-merged feature branches
- `Bash(gh pr list:*)` — Step 4-pre's PR-reuse probe (`gh pr list --head … --base <default branch> --state open`)
- `Bash(gh pr create:*)` — open the integration PR against `main` (integration-branch shape only; the PR-reuse shape never calls it)
- `Bash(gh pr checks:*)` — wait on the PR's required checks
- `Bash(gh api:*)` — the ruleset lookup (`repos/{owner}/{repo}/rulesets`) that Step 4d command 4b's could-not-measure note points at. Command 4b itself is `gh pr view`. It also POSTs Step 4d's waived-smoke-FAIL comment under the PR-reuse shape. Step 4d-1 reads a failing check's Actions job and its annotations with it. `gh api` can write, so the rule is a deliberate grant rather than an inference from the verb
- `Bash(gh pr view:*)` — read the PR's merge state
- `Bash(gh pr merge:*)` — squash-merge the integration PR (non-`--auto`)

Every rule named above ships in the installer's seeded allow-list, so a consumer who ran `bash install.sh` (or a current `sysop-update.sh`) satisfies this block on a fresh install under either policy. **A consumer whose skills are newer than their `settings.json` will not** — skill copies auto-update through the plugin path while the allow-list ships only through the installer, so if this block reports a rule you have never seen, run `sysop-update.sh` rather than hand-editing.

**The scripts arrive the same way, so check them too.** Before Step 1, confirm that every `sysop/scripts/` file this block's rules name exists, with `find sysop/scripts/ -maxdepth 1 -type f`. If one is missing, stop and run `sysop/scripts/sysop-update.sh`. Later in the close, a script that fails with `can't open file` is the same fault and never that step's own exit 2, even where exit 2 says to continue: stop and report it.

**§ Invocation shapes — keep the `pr` path rule-matchable.** A rule authorizes a *command*, not a *step*: the matcher compares against the literal text the model sends, splits on `&&`, `||`, `;`, `|`, `|&`, `&` and newlines, and requires each part to match. An earlier version of this skill's `pr` path defeated its own rules in three places — `PR_NUMBER="$(gh pr list …)"` and `PR_REF="$(gh pr create …)"` (a rule does not match past a variable assignment) and two `|| true` tails (`true` is not in the documented read-only set, though that set is documented as non-exhaustive, so this one is a strong inference rather than a stated fact). Those are now invoked bare, with the PR number and integration-branch name as quoted literals. **When editing Step 4-pre, 4d or 6, do not reintroduce them:** no capture into a variable, no `|| true` (use `|| echo …` — `echo` *is* in the documented read-only set), and no `for … done` around a set you could write out.

**What this block does NOT claim.** It asserts that the *provable* defeaters are gone, not that every `pr`-path invocation is proven to bind. See `WORKFLOW.md` § 8.2a *Invocation shapes* for the full inventory. If any required rule (the always-required git set above, plus the `gh`/git set when the policy is `pr`) is unsatisfied, stop with the error message from `_shared/permission-guard.md` § Algorithm step 5 (substitute "merges approved feature branches and either pushes `main` directly or — under `pr` policy — assembles an integration branch and opens a squash-merge PR; updates `tasks/index.yml` via `close_index.py` and runs the validator as a final guard" as the one-line reason). Do not proceed — unless the guard's step 3 mode check applies.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and continue.

**If `$ARGUMENTS` contains `--headless`**, this session was started with `--permission-mode dontAsk` and cannot see that for itself: tell the guard its run is headless under `dontAsk`, so its step 3b holds and step 5 prints the `dontAsk` note. Then run every command this skill prescribes exactly as written, one fenced line or block per call. Append nothing (`; echo "$?"`, `|| …`), wrap nothing in `python3 -c`, and read files with your file tools, never `cat`, `ls` or `head` chains: a call no rule covers is denied with no prompt, and in Steps 1 to 3c a denial halts the prepare; from Step 3b on, it is a stop.

## A close waiting for its second reader

**Unless `$ARGUMENTS` contains `--land`**, look for `sysop/runtime/close/*/AWAITING` and `*/STOPPED` from the main checkout's top level with `find sysop/runtime/close/ -maxdepth 2 -name AWAITING -o -maxdepth 2 -name STOPPED` (no output, or no such directory, is none; keep the trailing `/`, which follows a linked directory). If an AWAITING exists, stop: a `--request-review` close has an open PR that has not merged yet. Report the directory name as the run id and give the two ways on: `/review-close --land <run-id>` (it also finishes a PR merged by hand), or, once the PR has been closed unmerged, `python3 sysop/scripts/close_run.py abandon "<run-id>"`.

**Unless `$ARGUMENTS` contains `--land`**, if a STOPPED exists, stop: an unattended close stopped and waits for a human. Report the directory name as the run id and the file's `step` and `reason`, which names the recovery. A human clears it with `python3 sysop/scripts/close_run.py clear "<run-id>"` once the recovery is done, or before the recovery's own re-run of the close. Do not clear it and re-run a close over a branch the stopped close had merged at Step 4a: Step 4a rewrote it, so its doc reads stale and its worktree is gone; finish it on the integration branch. An unattended run never clears it.

## Open the close's arm receipt

Write `<flags>` below as the flags this invocation was given, each followed by its value, space-separated, or as an empty string when there are none: `--dry-run`, `--prepare`, `--resume <run-id>`, `--request-review`, `--land <run-id>`, `--agent <name>`, `--unattended`, `--headless`, `--skip-permission-guard`. Never paste the raw argument string: it is substituted into this file as text before bash parses it, so a `"` in it would rewrite the command. Then run, from the main checkout's top level, naming every arm this skill marks:

```bash
python3 sysop/scripts/close_arms.py begin "<flags>" 2a-ignored-refs 2b-large-diff 2b-leak 2b-no-conventions 2b-twin-spawn 3b-collect-exit 3b-rollback 3c-signals 4-pre-pr 4a-append 4a-fix 4a-post-failure 4a-post-prescan 4a-published 4b-batches 4c-check-exit 4c-unmerged 4d-direct 4d-pr 6-direct 6-pr-cleanup 6-pr-gate prepare-resume request-review-land
```

It prints `CLOSE: <close-id>`, then `ARM: prepare-resume` when the flags hold `--prepare` or `--resume`, `ARM: request-review-land` when they hold `--request-review` or `--land`, `ARM: 4d-pr` as well under `--land`, or `ARM: none`. **Load every arm it printed before you act on any of them:** read each file its stub below names and run that file's first command, then follow them; a combined mode's steps are split across the files, and the `--request-review` and `--land` file changes the resume's. Write the close id out as a literal, inside the quotes, in Steps 2a, 2b, 3b, 3c, 4-pre, 4a, 4a-fix, 4a-post, 4b, 4c, 4d, 6 and 8 and in a step file's first command: nothing carries between fenced blocks. **Exit 2**: stop and show its stderr. It names a word that is not one of those flags, a flag given twice or without its value, a flag combination this skill does not run, `--request-review`, `--land` or `--agent` without `## Merge policy` `pr`, a version mismatch to update, or a `## Merge policy` to fix.

## `--prepare` and `--resume <run-id>`

**Load this arm when `begin` printed `ARM: prepare-resume`.** Read `${CLAUDE_SKILL_DIR}/steps/prepare-resume.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=prepare-resume -->

## `--request-review` and `--land <run-id>`

Under `--land`, `begin` also printed `ARM: 4d-pr`: load `${CLAUDE_SKILL_DIR}/steps/4d-pr.md` with the arm below, writing `${CLAUDE_SKILL_DIR}` for its `<skill directory>`, and run the rest of it only where the `--land` items name its commands.

**Load this arm when `begin` printed `ARM: request-review-land`.** Read `${CLAUDE_SKILL_DIR}/steps/request-review-land.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=request-review-land -->

## Step 1: Gather State

### 1-pre. Bring `--clone` claims' commits across

**Run this first**, from the main checkout's top level, with `dry-run` under `--dry-run` and `apply` otherwise:

```bash
python3 sysop/scripts/clone_sync.py "<default branch>" "<apply or dry-run>"
```

Carry every line it prints, and its `CLONE SYNC:` summary, to Step 8's `Clone sync:`.

- `SYNCED` (`WOULD SYNC` under `dry-run`, which fetches nothing): this repository's `<branch>` moved, fast-forward only, to the clone's tip, or to `origin`'s when the clone or its branch is gone (the line names the source). `CURRENT`: nothing to bring across.
- `DIRTY`, `REFUSED`, `NO BRANCH` or `GONE`: Step 2a step 0a SKIPs the branch.

It reads only clones a lock records; a `--clone` claim made without `--lock` is not seen.

**Exit 3**: a placeholder, or not run from the main checkout's top level; fix it and re-run. **Any other non-zero exit**: stop and report the error; each line printed before it stands.

Then run these in parallel:
- `git branch -a` — all local and remote branches
- `git log --oneline origin/<default branch>..HEAD` — unpushed commits on main (if on main)
- `git branch --list | grep -v <default branch>` — local feature branches
- `git stash list` — any stashed work that might be forgotten
- `git worktree list --porcelain` — all worktrees (porcelain form is stable across git versions; consumed by Step 1a)

Identify two categories of pending work:
1. **Feature branches** — any non-main local branches (especially those marked `review_ready`)
2. **Unpushed main commits** — commits on main that are ahead of `origin/<default branch>`

### 1a. Classify Worktree State (silent-data-loss guard, BeanRider ISSUE-0016)

Branch tips are blind to uncommitted in-progress work. A `/claim-task`-ed branch where the agent did substantial worktree edits but never committed has a tip identical to a freshly-claimed branch with no work yet — Step 2a's commit-based verdict would say "no commits, reject" for both, and Step 6's cleanup would then try to remove the worktree. If a downstream codepath ever reaches for `--force` on `git worktree remove`, uncommitted work is silently destroyed. **No shipped skill does today** — no skill in this install contains `git worktree remove --force`, and the only forced removals anywhere are the opt-in `--force` arms of `claim_task.sh --release` and `batch_work.sh --release` (an earlier version of this sentence attributed such paths to `/auto-judge` and `/document-work`, which have none — the same wrong-capability class as `/auto-build`'s "clears the lock" claim). The guard below is what keeps it that way.

For every worktree on a branch (excluding the **primary checkout**, matched by path identity rather than by branch name, unless a lock names it as its workspace), classify its state from its `git status --porcelain` and its branch's commit position relative to `<default branch>`. Run, from the main checkout's top level:

```bash
python3 sysop/scripts/close_state.py worktrees "<default branch>"
```

It prints one `DIRTY`, `AHEAD` or `MERGED` line per worktree, and reads each claim worktree itself, which a `git -C` of yours could not do under `dontAsk`. **Exit 2: stop and show its output.**

The three classes are:

- **`clean-merged`** (`MERGED`) — tip has no commit that main and the recorded PR heads (`refs/sysop/merged-pr-heads/*`) lack, AND `git status --porcelain` is empty. Either a never-touched claim branch or an already-merged-but-not-cleaned-up branch. Safe to remove in Step 6.
- **`clean-ahead`** (`AHEAD`) — tip has commits ahead of main AND `git status --porcelain` is empty. Normal review path; proceed to Step 2a's commit-based inspection.
- **`dirty`** (`DIRTY`) — after the symlink downgrade at the end of this bullet, the *significant* set (`git status --porcelain` minus the downgraded lines) is still non-empty. **Paused mid-implementation work.** Step 2a will produce an automatic SKIP verdict for this branch and Step 6 must refuse to touch the worktree. Two classes of noise are already excluded so they don't false-positive into `dirty`: gitignored `sysop/runtime/locks/` and `sysop/runtime/pending-docs/` never appear in `--porcelain` without `--ignored` (this assumes the branch's checked-out `.gitignore` carries the installer's `sysop/runtime/` append — a worktree honors only *committed* ignore rules, so a branch cut before that append was committed will show `?? sysop/runtime/` until it's rebased/merged in; the installer's migration output says to commit the append before claiming); and an untracked symlink whose target is gitignored in the main repo (a `.venv`-into-the-main-venv tooling convenience) is downgraded out of the significant set (BeanRider ISSUE-0043). Everything with reviewable content — modified tracked files, real untracked files, and any symlink whose target is not provably ignored — stays significant, so the silent-data-loss guard is unweakened. A worktree whose `git status` fails prints `DIRTY` with the error as its reason, and one whose commits cannot be counted prints `AHEAD`: neither reads as `clean-merged`, the class Step 6 removes.

Carry each branch's classification into Steps 2a, 3b, and 6 — they all consult it.

### 1b. Preserve Uncommitted `review_tasks.md`

Check `git status -- review_tasks.md` for uncommitted changes. Two distinct shapes can produce a dirty `review_tasks.md`: new open tasks from `/codebase-review` / `/security-audit` (single-file commit) and an in-flight archive rotation that also touches a sibling archive file (atomic two-file commit). Pick the right shape — splitting an archive rotation across two commits leaves the archive file untracked and confuses Step 4a's rebase.

**Detect the shape**, from the main checkout's top level:

```bash
python3 sysop/scripts/close_state.py review-tasks
```

It prints `REVIEW_TASKS: clean` (nothing to do), `REVIEW_TASKS: save (+<a> -<d>)` or `REVIEW_TASKS: rotation (+<a> -<d>, review_tasks_archive.md dirty)`: a rotation is the sibling archive file dirty or untracked **and** net deletions in `review_tasks.md` against `HEAD`. The sibling is `review_tasks_archive.md` at the repository root; if `<project>/CLAUDE.md` § Key Files names another archive file, check it with `git status --porcelain -- <that file>` yourself. **Exit 2: stop and show its output.**

**Under `--dry-run`, commit nothing in this step:** report which commit below would be made, and continue.

**Branch on the result:**

- **Archive-rotation commit (atomic two-file):** on `REVIEW_TASKS: rotation` (the sibling is dirty and review_tasks.md has net deletions — sections were rotated out, not added), `git add` both files together and commit with `docs: archive <round-or-batch-list> to <archive-file>`. The two files are halves of one atomic rotation and MUST land in one commit. The deletion-direction check distinguishes a rotation (net deletions in review_tasks.md, content moved to the archive) from a same-cycle scenario where new tasks were added AND the archive file was independently touched — that second case is rare and warrants manual judgment, not the atomic-rotation message shape.

- **Single-file commit (default):** on `REVIEW_TASKS: save`, run `git add review_tasks.md && git commit -m "docs: save pending review tasks"`. This covers the canonical `/codebase-review` / `/security-audit` flow.

- **In-place rotations** (projects whose archive script moves sections within `review_tasks.md` rather than to a sibling file — e.g., to a `## Archive` heading at the bottom): no sibling file is dirty, so the script prints `save` and the single-file path runs, which is correct for that shape. The commit message will say "save pending review tasks" rather than "archive ..."; if the consumer wants the rotation message, they can either configure their archive script to write a sibling file (matching the canonical shape) or manually amend the message after Step 1b.

This **must** happen before any branch merges — Step 4a's rebase needs main's `review_tasks.md` to reflect any rotation, else feature branches cut before the rotation will conflict on stale section boundaries (see Step 1c).

### 1c. Drain Archive State Before Rebasing

If Step 1b committed an archive rotation on `main`, any feature branch cut from `main` *before* that rotation commit will hit a structural rebase conflict at Step 4a — its ancestor `review_tasks.md` still has the rotated-out sections that no longer exist on main. This step **warns** about that condition; resolution still happens at Step 4a using the updated prose there. The warning lets the agent set expectation (and choose to defer the affected branch to a separate cycle if the conflict would be expensive to resolve).

**Detection (file-based, not commit-subject-based).** Enumerate the feature branches in scope for this round (the same set Step 2a will review — non-main local branches, typically those marked `review_ready`). For each, find its merge-base with main and check whether main has touched any archive file since that base:

```bash
python3 sysop/scripts/close_state.py archive-rotation "<default branch>"
```

It prints `--- Step 1c: archive-rotation pre-check`, one `checked: <branch>` line per local branch but `<default branch>` and the review sub-agents' `worktree-agent-*` checkouts (Step 2b), and three `WARN:` lines for each branch cut before `review_tasks_archive.md` changed on `<default branch>`. The archive is `review_tasks_archive.md` anywhere in the tree; if `<project>/CLAUDE.md` § Key Files names another path, check `git diff --name-only <merge-base>..<default branch> -- <that path>` for each branch yourself. **Exit 2: stop and show its output.**

**No `checked:` line at all means the enumeration was empty — not that every branch passed.** Read the two apart before moving on; an earlier version left them indistinguishable.

This is a **soft warning, not a hard gate** — informational only. The agent proceeds to Step 2 regardless; Step 4a's updated prose handles the actual conflict if it materializes. Hard-gating here would block legitimate close-outs whose conflict turns out to be trivial (single-line checkbox flip rebasing onto a slightly-shifted layout). If the warning fires repeatedly for a branch and the resolution is consistently expensive, that's project-side friction worth logging via Step 7's friction capture.

If the enumeration yields no branches (only unpushed main commits this cycle), Step 1c is a no-op — skip cleanly; you will see the `--- Step 1c` header and no `checked:` line at all.

## Step 2: Review Pending Work

### 2a. Feature Branches

For every non-main local branch — excluding any **agent worktree branch** (a branch whose registered worktree lives under `.claude/worktrees/`; on Claude Code these are named `worktree-agent-<id>`). Those are review sub-agents' scratch checkouts, not anyone's feature work; Step 2b's HARD RULE covers removing leaked ones. Do not review, approve, reject, or merge them:

0. **Worktree-state pre-check (Step 1a result).** If Step 1a classified this branch's worktree as `dirty`, the verdict is **SKIP — paused work present**. Do NOT inspect the diff and do NOT propose approve/reject — uncommitted worktree changes mean the branch is mid-implementation, not in a reviewable state. Report the dirty file count and the recommendation: *"`<N>` pending changes in `<worktree-path>`. Commit-as-WIP, stash, or leave alone — re-run `/review-close` after the user decides. This branch is excluded from Step 3b (worktree removal), Step 4 (merge), and Step 6 (cleanup) for this run."* Then continue to the next branch. A SKIP'd branch is distinct from both `approve` and `reject`: it is not merged, but its worktree, lock, and branch are all preserved untouched.

0a. **Clone pre-check (Step 1-pre result).** If Step 1-pre printed `DIRTY`, `REFUSED`, `NO BRANCH` or `GONE` for this branch, the verdict is **SKIP — clone not brought across**: not reviewed or merged, and its clone, lock and branch are left as they are, excluded from Steps 3b, 4 and 6. Report the line and its remedy, then continue to the next branch:
   - `DIRTY`: commit, stash or discard in the worktree the line names, or finish the operation in progress; for a detached `HEAD` that continues `<branch>`, move those commits onto `<branch>` or check `<branch>` out there. Then re-run the close. A new commit makes a pending doc carrying `branch_tip:` stale: re-run `/document-work` in the clone first.
   - `REFUSED` with *not a fast-forward*: decide which history to keep. To keep the source's, run `git fetch --no-tags <clone path, or origin> +refs/heads/<branch>:refs/heads/<branch>` from the main checkout; to keep this repository's, bring the clone's `<branch>` to it, or, when the line names `origin`, push it there. Then re-run the close. Any other `REFUSED`: fix the cause the line names, then re-run.
   - `NO BRANCH` or `GONE`: neither the clone nor `origin` holds `<branch>`. If the work is elsewhere, push it to `origin`'s `<branch>` and re-run. If it reached `<default branch>` another way, or was abandoned, release the claim (`claim_task.sh --release <TASK_ID>`) and record the task's outcome by hand.

   Under `--dry-run`, a branch Step 1-pre printed `WOULD SYNC` for is not reviewed: report *not reviewed: a dry run does not bring a clone's commits across*.

0b. **Landed check.** Ask whether a previous close already landed this branch. Run it from the repo root, with the branch and the default branch written out:
   ```bash
   python3 sysop/scripts/feature_branch.py landed "<branch>" "<default branch>"
   ```
   **`LANDED: PR #<N>`** means every commit on the branch was in PR #<N>, which a previous close squash-merged, and the doc that close held is still here. The verdict is **approve — landed by PR #<N>**: skip steps 1–3, and Step 2b and Step 2d do not target it. Every later step handles it as approved; Step 4a item 1 prints `REPLAY 0`, so it is not merged again. Carry it to Step 8's `Squash provenance:` line. **`LANDED: in <ref>`** means no recorded head contains the branch but its tip is already in `<ref>`, the local default branch, and a doc naming it carries `held_since:`, which Step 4c 1c writes when a close holds a doc whose branch `HEAD` already contains. The verdict is **approve — landed in `<ref>`**, handled as one landed by a PR is, except that Step 4a item 1 prints `RECORDED HEAD: none` for it and its Step 8 line is `Branches:`, not `Squash provenance:`. **`NOT LANDED — <reason>`**: review it as steps 1–4 say. **Exit 3**: a placeholder; write the branch and the default branch out.
   See `REFERENCE.md` § *A landed branch stays approved*.

1. `python3 sysop/scripts/git_ro.py . log refs/heads/<default branch>..refs/heads/<branch> --not --glob='refs/sysop/merged-pr-heads/*' --oneline` — what commits are on it (through the read-only wrapper, because Claude Code's own read-only set refuses `--glob`), without the claim flips a recorded PR head already landed
2. `git diff <default branch>...refs/heads/<branch> --stat` — scope of changes
3. Read the diff. Check for correctness, security issues, and alignment with the task body — path from `tasks/index.yml`'s `body:` field for each task ID the branch claims (a claim does **not** move the body, and there is no `tasks/in_progress/` directory in any shipped layout, so it stays where it was written — normally the file `tasks/open/<TASK_ID>.md`, which `body:` records canonically as `open/<TASK_ID>.md`, relative to `tasks/` — until Step 4c's archive move). Read it **at the branch tip**, per Step 2d's revision note: a branch edits its own body, and the working tree is still `main`.

   **Under `--prepare`, ask nothing in step 3a below and do not run its commit-or-copy block:** record each `IGNORED-REF:` line, and the error ask after that block, as a question (*`--prepare` and `--resume <run-id>`* (`steps/prepare-resume.md`), item 2), and carry the branch on with its verdict marked `pending Q<n>`.

3a. **Gitignored files the branch reads.** Not for a branch Step 2a step 0b found landed. Find the branch's workspace: the path Step 1a or Step 1-pre printed for it, or, for a branch neither listed, the `workspace:` of the lock naming it (a `--branch` claim, whose workspace is the main checkout). With neither, or when that path is not a directory, there is nothing to list; say so and go on. Otherwise run from the repo root:
   ```bash
   python3 sysop/scripts/ignored_refs.py "<workspace>" "<default branch>" --branch "<branch>"
   ```
   **Exit 0**: go on. **Any other exit** (exit 1 lists `IGNORED-REF:` lines; any other code means the check did not run): record the arm, from the main checkout's top level, with the close id `begin` printed written out:

   ```bash
   python3 sysop/scripts/close_arms.py exited "<close-id>" 2a-ignored-refs <code>
   ```

   It prints `ARM: 2a-ignored-refs`. **Exit 2**: stop and show its stderr.

   **Load this arm when the `exited` command above printed `ARM: 2a-ignored-refs`**, once per close: a later branch's exit follows the arm already loaded. Read `${CLAUDE_SKILL_DIR}/steps/2a-ignored-refs.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`. It holds the questions about each line, the commit-or-copy block, and the ask when the check did not run.

<!-- sysop:arm=2a-ignored-refs -->
4. Verdict: **approve** (merge to main) or **reject** (report reason, leave branch)

> **Three dots on every `git diff` in Step 2 — 2a, 2b and 2d (internal tracker #241).** `git diff <default branch>..refs/heads/<branch>` compares the two *tips*, so everything `main` gained after the branch was cut renders as though the branch **deleted** it. That is not a rare condition: `/review-close` manufactures it, because Step 1b commits `review_tasks.md` to `main` before any branch is inspected. `git diff <default branch>...refs/heads/<branch>` diffs against the merge-base and shows exactly what the branch contributed. A false BLOCK costs a human round-trip; a **false APPROVE** — real hunks buried under phantom deletions — is the worse direction and gets likelier the staler the branch is. **`git log <default branch>..refs/heads/<branch>` keeps two dots**: for `log`, two-dot already means "commits on the branch and not on `main`," which is what step 1 wants. The rule is per-command, not a blanket search-and-replace.

### 2b. Prevention Convention Check

**Targets.** One agent per **approved-or-rejected** feature branch, plus **one for the unpushed-main commits as a group** if there are any. A branch Step 2a classified **SKIP** (paused work present, clone not brought across, or an ignored file unanswered) is *not* a target: it is not merging this run, and a `VERDICT: BLOCKED` on it would halt the close over work already declared out of scope. Nor is a branch Step 2a approved as landed (step 0b: **landed by PR #N** or **landed in `<ref>`**). These calls can be parallelized — launch one agent per target simultaneously.

Each target has a **diff basis**, used identically by step 0's predicate and step 1's retrieval:

| Target | Diff basis |
|---|---|
| feature branch `<branch>` | `git diff <default branch>...refs/heads/<branch>` |
| unpushed-main group | `git diff origin/<default branch>...HEAD` |

If the repo has no `origin` remote, or `HEAD` is not `main`, there is no unpushed-main group — skip that target rather than running a command that will fail or silently diff something else. (Step 1's `git log --oneline origin/<default branch>..HEAD` is already qualified "if on main"; this is the same condition.)

**0. Per-target doc-only skip (internal tracker #240).** Compute the target's diff basis first. If it touches **no** code files (the same code-file set Step 3 uses — `.py` / `.ts` / `.tsx` / `.js` / `.jsx` / `.sql` / `.sh` / `.kt` / `.swift` / `.go` / `.rs`) **and** the project's conventions contain no rule that governs the file types the diff *does* touch, skip the agent for that target with a one-line note (`2b: <target> — doc-only diff, no code-convention surface`). **"The project's conventions" is THREE sources, not one section.** An earlier version of this conjunct named `## Prevention Conventions` alone, which made the skip fire over a target governed solely by a rule living anywhere else — and Sysop's own shipped template puts convention content elsewhere, so this was not a consumer quirk. Read all three before concluding the conjunct holds:

   1. **`## Prevention Conventions` in `<project>/CLAUDE.md`**, every subsection.
   2. **The other CLAUDE.md sections that carry convention content.** `WORKFLOW.md` § 6.1's required-sections table lists **`## Testing Patterns` as its own top-level section**, beside `## Prevention Conventions` and not inside it. A consumer who followed the shipped template therefore keeps testing conventions in a section this predicate never read. Treat any required or optional section naming rules the diff's file types could violate as in scope.
   3. **The convention map** — `.claude/convention_map.project.md` (the consumer overlay `WORKFLOW.md` names as the documented home for path routing) and the shipped `convention_map.md` beneath it. This predicate was **map-blind**: the map is the one artifact that routes *globs* to conventions, which is precisely the question being asked, and it was consulted nowhere. A glob in either map matching a path this diff touches is a governing rule — **do not skip**.

   If any of the three yields a rule that could govern the touched types, spawn the agent and let it route. The skip is licensed by a *searched* absence, across all three, not by the absence of a section you happened to read. Docs-only cycles are not an edge case here — Step 7's own friction capture generates them routinely.

   **This skip is about step 3's agent and does not reach step 3b's**. The two gates ask different questions of the same diff, and a diff can pass this one while failing that one: the security map routes documentation paths *by design* — the **core** map routes `.claude/skills/**/*.md`, and the llm pack routes `<prompts dir>/**/*.md` — so a target skipped here as doc-only can still match a security glob. Evaluate step 3b's gate on its own; a cascade would silence the security lens on exactly the diffs it was added for.
   See `REFERENCE.md` § *Step 2b — provenance*.

> **Check the second condition; do not assume it.** "Docs cannot violate a convention" is false often enough to be dangerous, and Sysop's own shipped maps are the counter-examples: `core/companion/convention_map.md` routes `.claude/skills/**/*.md` to five conventions including *No secrets in examples*; the beancount pack routes a per-vendor `README.md` to **"Synthetic content only: NO real account numbers, payees, amounts, addresses"** and `<ledger>.beancount` to *No PII in git-tracked ledgers*; the llm pack routes `<prompts dir>/**/*.md` to template rules. **None of those is scanner-shaped** — the beancount rule asks a reader to judge whether a digit string *looks* real, which no entropy or pattern scanner does. So the skip is licensed by the *absence of an applicable rule*, not by the file extension. Read the conventions (you need `## Prevention Conventions` for step 1 anyway; the other two sources are this predicate's alone), and if **any of the three** names documentation, config, prompts, fixtures, or committed data — in a subsection, in another CLAUDE.md section, or as a glob in either convention map — **do not skip** — spawn the agent and let it route. Secret-scanning (`security_map.md` routes `.claude/skills/**/*.md` to **A02**) is a separate expectation covered by the project's scanner, and this skip neither touches nor waives it.
> See `REFERENCE.md` § *Step 2b — provenance*.

Step 2a still reads the diff either way. If every target skips, Step 2b is a clean no-op; say so in one line rather than reporting nothing.

**For each remaining target:**

**First, look up a recorded verdict for the target**, before step 1 reads anything for it, from the repo root, with `<target>` the branch or `unpushed-main` and the sections step 0 identified:

```bash
# The sections are step 1's whole set: add each further section step 0 identified.
python3 sysop/scripts/gate_verdict.py lookup convention "<target>" "<default branch>" "${CLAUDE_SKILL_DIR}" "Prevention Conventions" "Testing Patterns"
```

- **Exit 0, `REUSE …`:** skip steps 1 and 3 for this target, so create no checkout and spawn no agent for this target. Its verdict is `APPROVED` with `NOTES: none`; report the printed line. Step 2's baselines are taken as on any close.
- **Exit 3, `MISS …`:** go on, and keep the 64 characters after `KEY:`, if it printed one, for step 4's record.
- **Any other exit:** go on. On exit 2, print its message under Step 8's `Conventions:` line.

What the key covers: `REFERENCE.md` § *Step 2b — verdict reuse*.

1. Read the **entire** convention-bearing set of `CLAUDE.md`, every subsection — **not `## Prevention Conventions` alone**. Subsection names vary by project: a web project might have `Frontend`/`Backend`/`Auth boundaries`; a data-pipeline project might have `Data integrity`/`Privacy`/`Schema evolution`; an MCP server might have `MCP server boundaries`. **The set is `## Prevention Conventions` + `## Testing Patterns`, plus any other section step 0 identified as carrying a rule the diff's file types could violate.** Those two are named because `WORKFLOW.md` § 6.1's required-sections table is what makes them rule-bearing — `## Prevention Conventions` is *"the actual convention rules"*, `## Testing Patterns` is *"test framework, fixture patterns, mock patterns"* — while `## Architecture`, `## Key Files`, `## Commands` and `## Environment Variables` describe the project rather than constrain it. **That is an illustration, not a partition of the table** — § 6.1 lists more rows than those, several of them (`## Pre-merge verification`, `## Merge policy`, `## Plan review`) operational rather than descriptive, and none convention-bearing in the sense this paste needs. **Read the two named members as the floor and step 0's answer as the rest**: the tail is a judgement, step 0 already made it, and this step consumes that answer instead of re-deriving it.

   > **This reverses a scoping an earlier build took deliberately, and the reversal is the point.** That build closed the *skip predicate* — step 0 now reads three sources — but left this paste at one section and wrote here that the narrowing was intentional: *"what a sibling section governs is step 0's question."* It is not. Step 0 decides **whether to spawn**; step 1 decides **what the agent is given**. Splitting them that way produced an agent that runs, routes and reports honestly against a taxonomy missing the very section that kept it from being skipped — a narrower review, arrived at by a gate working exactly as written. Nobody is told a check happened that did not, which is why the entry was filed § Medium and not § High; it is still the wrong answer.
   >
   > **The filing's own preferred remedy was option (c) — amend § 6.1 to make `## Testing Patterns` a subsection of `## Prevention Conventions` — and it is refused here.** It settles the template's self-consistency and fixes nothing: a consumer who already followed the shipped template has the section at top level, so the paste would keep missing it. (c) is cheap because it changes no behaviour, and that is also why it is not a fix. Option (b), driving the paste off the convention map, remains the larger reshape the filing calls *"arguably the right shape"*; it is not this phase's.
   >
   > **The filing also forbids taking this option without measuring the paste against the threshold below, so it was measured — on both real consumers, not estimated.** GDP (the reference consumer): `## Prevention Conventions` 53,456 chars, `## Testing Patterns` 3,637, widened total **57,093**. BeanRider: 3,662 + 456, widened total **4,118**. **The widening moves neither consumer across the 10,000-character threshold** — GDP was already on the write-once arm and stays there, BeanRider was already on the inline arm and stays there. The worry the filing raised, that widening *"silently moves reviewers onto an unmeasured arm"*, does not materialise on either: for BeanRider to flip, the threshold would have to fall inside a 456-character window. The tail section step 0 may add is unbounded in principle, which is why the measurement command below measures the set it actually assembled rather than these two numbers.

   Retrieve the full diff — the target's **diff basis** from the table above, three dots, per Step 2a's note. Whichever arm you take below, a two-dot diff hands the reviewer `main`'s newest content as though the branch had torn it out.

   **Paste or write-once — the conventions threshold is 10,000 characters of section text.** The section is identical for every agent, so above the threshold pasting it N times is pure duplication (measured: 53,456 characters × a 13-agent close ≈ 174k tokens of the same text). Measure it, do not estimate it — the same rule as the diff threshold below. Run it from the repo root, as written:

   ```bash
   # Measure the WIDENED set, not one section: one argument per section,
   # without its `## `. Add each further section step 0 identified -- measuring a
   # narrower set than you paste is how a prompt silently lands on the wrong arm.
   python3 sysop/scripts/convention_size.py "Prevention Conventions" "Testing Patterns"
   ```

   A section that is absent contributes 0 and is not an error — `## Testing Patterns` is a required section, but a consumer who has not written one has no testing conventions to route against, which is a different thing from a missing file.

   **On a `TOTAL` of `0`**, the rules for it are an arm. Run, from the main checkout's top level, with the close id `begin` printed:

   ```bash
   python3 sysop/scripts/close_arms.py exited "<close-id>" 2b-no-conventions 1
   ```

   It prints `ARM: 2b-no-conventions`. **Exit 2**: stop and show its stderr.

   **Load this arm when the `exited` command above printed `ARM: 2b-no-conventions`**, once per close: the measurement is the same for every target. Read `${CLAUDE_SKILL_DIR}/steps/2b-no-conventions.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=2b-no-conventions -->

   **At or below 10,000, paste it into every prompt as before** — the dominant small-project path keeps the behaviour in use, and a paste has no failure mode. **Above 10,000, write it ONCE and hand every agent the same copy.** First remove any earlier close's copy:

   ```bash
   python3 sysop/scripts/review_pins.py clear-conventions
   ```

   then write **every section in the set, verbatim, every subsection, unfiltered** to `sysop/runtime/2b-conventions.md` in the **primary** worktree with the `Write` tool — each under its own original `## <name>` heading, in the order above, so the agent can still cite which section a rule came from — and substitute that file's **absolute path** into each prompt's `## Project conventions` block (second arm below). The removal first is the same loud-failure discipline as the baseline capture in step 2: without it, a run that skips the write hands every agent the *previous* close's conventions, silently. The authority question this resolves is stated in the prompt arm: agents read the orchestrator's copy, **never their own worktree's `CLAUDE.md`** — each worktree checks out its *branch's* version of that file, and a branch that edits the conventions would otherwise have each reviewer routing against a different taxonomy.

   **Paste or retrieve — the threshold is 1,000 lines of `git diff` output.** Measure it, do not estimate it:

   ```bash
   # The table above gives the diff basis as a WHOLE COMMAND, so write it out — do not
   # substitute it as an argument to another `git diff`. `git diff <a whole git diff
   # command>` fatals on an ambiguous argument, `wc -l` counts the empty stdout as 0,
   # and every target then scores below the threshold: the gate reads as "paste" for a
   # 452 KB diff and says nothing. Found by executing it.
   git diff <default branch>...refs/heads/<branch> | wc -l          # feature branch
   git diff origin/<default branch>...HEAD | wc -l                  # unpushed-main group
   ```

   Run the line for the target and read the number it prints; do not capture it in a variable.

   - **At or below 1,000 lines:** paste the diff verbatim into the prompt's `## Diff` block, as before. The paste is cheaper than the round-trip, and the reviewer starts reading immediately.
   - **Above 1,000 lines, load the arm first.** Run, from the main checkout's top level, with the close id `begin` printed:

     ```bash
     python3 sysop/scripts/close_arms.py exited "<close-id>" 2b-large-diff 1
     ```

     It prints `ARM: 2b-large-diff`. **Exit 2**: stop and show its stderr.

     **Load this arm when the `exited` command above printed `ARM: 2b-large-diff`**, once per close: a later target's large diff follows the arm already loaded. Read `${CLAUDE_SKILL_DIR}/steps/2b-large-diff.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=2b-large-diff -->

   > **Why a threshold and not a rule either way, and where the number comes from.** Measured over **ten branch-shaped merges** — one agent's worth of work each — in one real consumer repository; `review-close: consolidate` integration commits are excluded, because an integration branch is not a single 2b target. The ten are enumerated by commit in this project's maintainer record, not by a date range: a date range is not a stable population, and the first form of this sentence used one that had already stopped selecting the ten it quoted. Their diffs were 88, 224, 272, 273, 332, 366, 641, 2141, 2376 and 13,606 lines (5 KB – 452 KB). **Seven of ten sit under 700 lines; the top three are 77 KB, 112 KB and 452 KB.** A 1,000-line cut separates that population where it actually separates — anywhere in the 641→2141 gap gives the same split — and the number is a stated choice anchored on that measurement, not a claimed optimum. Above the cut the paste dominates the prompt and, at the top of the range, crowds the conventions section the agent is being asked to route against. Below it, retrieval buys nothing and costs a tool call.
   >
   > **What this does NOT claim.** Nobody has measured whether a retrieval-only reviewer finds what a pasted-diff reviewer finds. The threshold is sized so the dominant path (7 of 10 targets) keeps the behaviour that has been in use, and only the tail — where the paste is a liability on its own terms — changes. **The duplication this step used to carry was elsewhere:** the `## Prevention Conventions` section was pasted *identically* into every agent's prompt (53,456 characters in the reference consumer), whereas each agent's diff is its own target's and is not duplicated at all. An earlier build gave the conventions their own paste-or-write-once threshold — step 1 above — on the same keep-the-dominant-path logic as this one.

2. **Capture the primary-tree baseline — before any agent is spawned.** Step 3's assertion is a *delta* against this file and there is nothing to compare against if you skip it. It must run here, ahead of the spawn below; a baseline taken afterwards records the breach as though it were pre-existing and the assertion then certifies the tree clean.

   ```bash
   python3 sysop/scripts/review_pins.py baseline
   ```

   It prints `BASELINE: <n> status line(s), <m> config line(s)`. **Exit 2: stop and show its output.**

   > **Two baselines, because a spawn writes to two places.** The tree snapshot catches an agent
   > that created or edited a file; the config snapshot catches the harness itself. Spawning with
   > `isolation: "worktree"` rewrites a **relative** `core.hooksPath` to an absolute path in the
   > repository's shared `--local` config and never restores it — measured, one spawn. Both
   > captures must run here, before the first spawn, for the same reason: a baseline taken after
   > the fact records the damage as the starting state.

3. **Create each reviewer's checkout AT the target's commit — the harness will not do it for you, and this is the step that decides whether the gate runs at all.** `isolation: "worktree"` forks from the repository's **default branch**, not from the spawning session's `HEAD`. Under `pr` policy the target is always a branch that has not merged, so *every* agent spawned with isolation alone is handed the pre-merge tree: it reviews the default branch, finds nothing, and returns `APPROVED`. A convention gate reporting clean over a tree that does not contain the work is indistinguishable from one that reviewed it. `_shared/adversarial-review.md` § *Running more than one reviewer* states the rule; **this step is its invoker, and before it the only invoker lived in a maintainer file the public mirror strips, so for a consumer the rule shipped to nobody.**

   **First, check that a reviewer can run its git.** Each reviewer runs `sysop/scripts/git_ro.py` from its own isolated checkout, which is forked from `origin/<default branch>` (measured), not from your tree:

   ```bash
   python3 sysop/scripts/git_check.py fork-has "<default branch>" sysop/scripts/git_ro.py
   ```

   **Exit 1: stop the close** and tell the human to land the Sysop update on that branch first (push it, or merge its PR), then re-run: every reviewer's first call would fail. **Exit 2 or 3: stop and show its output.**

   **One checkout per agent, detached, under `sysop/runtime/pins/`**, created before the spawn and named in the prompt:

   ```bash
   # Per target, and the two targets resolve DIFFERENTLY. Write the arm you need; do not
   # collapse them. For a feature branch the pin is the BRANCH TIP -- never `HEAD`, which
   # under `pr` policy is the default branch this step is standing on, i.e. exactly the
   # pre-merge tree the measured defect is about. Collapsing the arms restores the defect SILENTLY:
   # the checkout is created at whatever the revision names, so the agent's echo still
   # matches and the receipt still passes while every lens reviews the default branch.
   python3 sysop/scripts/review_pins.py add "refs/heads/<target branch>"   # feature-branch target
   python3 sysop/scripts/review_pins.py add HEAD                          # unpushed-main group ONLY
   ```

   It prints `PIN=<sha> PINNED=<path> SCRATCH=<path>`, both paths absolute: write all three into that agent's prompt, since no variable survives to the next call. **Exit 2: stop and show its output** — a target that did not resolve has nothing to place a reviewer at.

   - **Under the ignored `sysop/runtime/`.** If `add` refuses because git does not ignore the path, add `sysop/runtime/` to `.gitignore`; never place the checkout anywhere else, since a reviewer cannot read one outside the project under `dontAsk`.
   - **One per agent, not one shared read-only checkout.** Sharing is cheaper and would be safe if the do-not-mutate rule held — it has been measured failing twice, and the failure mode of a shared pin is precisely a measured incident: one lens moves the checkout and its siblings silently describe the wrong revision. The echo below cannot catch that, because every echo runs *before* any sibling has had time to mutate. **The scratch directory is one per agent too, for the same reason:** `add` makes one beside each pin and prints both as absolute paths; write both into that agent's prompt, never a shared `/tmp`.
   - **Keep `isolation: "worktree"` anyway.** The pinned checkout is what the agent *reads*; its isolated worktree is where its stray writes land. Dropping isolation would put a stray scratch file back in the primary tree, which is the one thing that contained both measured breaches. **That containment is the whole reason.**
     See `REFERENCE.md` § *Step 2b — provenance*.

   Then spawn an Agent with:
   - `subagent_type: "general-purpose"`
   - `model: "sonnet"`, `effort: "high"` (always — the **convention-gate** role; do not omit, per `.claude/served_models.yml`) <!-- sysop:role=convention-gate -->
   - `isolation: "worktree"` — give each agent its own checkout (internal tracker #234). Steps 2a–2d run in the user's **primary** worktree, which has a single `HEAD`; a full-tool agent that decides to compare two revisions will reach for `git checkout` unless something stops it, and in a real run one did, moving `HEAD` off the branch the close was working on. Step 4's HARD RULE already names this hazard but frames the actor as *external*; here it is this skill's own agents, spawned two steps earlier. Isolation is available here because these agents have **no** pre-existing worktree, so `_shared/adversarial-review.md` § *Running more than one reviewer* applies directly — its "do not use it where a worktree already exists" caveat is about `/claim-task`, `/auto-build`, `/auto-fix` and `/auto-judge`, which spawn into a worktree an earlier step created, not about this step. **Where the harness offers no isolation parameter, the prompt's do-not-mutate rule below is the portable floor** — all that is available, which is not the same as sufficient. Measured twice, on two different instruction texts: a consumer's 13-agent run had one agent create `tasks/open/<ID>.md` and edit `tasks/index.yml`, with several others leaving scratch scripts in the worktree root; and this repo's own pre-build pass, under a more emphatic read-only instruction, had an agent create a scratch file inside its worktree anyway. Both were contained only because the run passed `isolation: "worktree"`. So isolation is the structural hardening the floor does not provide, not a redundant extra on top of it — and a harness without it **must** expect a dirty tree and re-assert cleanliness rather than trust the prompt.
   - `description: "Convention check: <target>"`
   - `prompt`:

     ```
     You are the final convention gate before this branch merges to production.
     Review the diff below for violations of the project's conventions — EVERY
     section given to you below, not `## Prevention Conventions` alone.

     ## Where you are — echo this BEFORE your first finding
     The tree you must review is NOT your own working directory. Your own
     checkout is forked from the default branch and does not contain this
     target's work. Read every file under the pinned checkout with your file
     tools, and run every git command against it through the read-only
     wrapper, from your own working directory:

         python3 sysop/scripts/git_ro.py "<absolute path to the pinned checkout>" rev-parse HEAD

     Report that output verbatim as your first line. It must equal <PIN>.
     If it does not, STOP and say so — do not re-point yourself and do not
     review. A lens that reads the wrong revision finds nothing to report,
     which is indistinguishable from a clean pass.

     The wrapper is the whole rule: a bare `git rev-parse HEAD` reports your
     shell's CWD, which is your own worktree, so you can echo a plausible SHA
     while reading the wrong tree. `git -C`, `cd <path> && git` and
     `--git-dir` are denied in this session; the wrapper runs read-only
     subcommands only (`log`, `show`, `diff`, `grep`, `ls-files`, `rev-parse`,
     `status`, `blame`, …).

     Run each wrapper line alone: nothing before it (no `P=…`), nothing
     after it (no `|`, `||`, `;` or `&&`), no `$(…)` in it. A composed call
     can be denied with no prompt, and you lose the fact. Read the whole
     output, narrow with git's flags (`grep -n`, `blame -L`, a pathspec),
     or read the pinned checkout with your file tools.

     Do not modify the pinned checkout — no `git checkout`, no branch switch,
     no staging, no stash. Other reviewers are reading their own copies and a
     lens that moves a checkout has, in a real round, made its siblings
     silently describe the wrong revision. Compare revisions with
     `python3 sysop/scripts/git_ro.py "<pinned>" show <sha>:<entry>`, which reads the object database and
     is unaffected by tree state. Run it once per entry, not in a shell loop;
     if you loop anyway, name the variable `entry`, never
     `path` — in zsh `path` is tied to `$PATH`, and assigning it replaces the
     command search path so every later command fails.

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
     against. Do NOT substitute a CLAUDE.md read from either tree you can see:
     your own worktree carries the DEFAULT branch's version of that file and the
     pinned checkout carries the target's, neither of which is the orchestrator's
     read, and a branch that edits the conventions would otherwise have each
     reviewer routing against a different taxonomy.
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

     Then, whatever the verdict:

     NOTES:
     - <file>:<line> — <one-line finding>
     (or `NOTES: none`)

     A note is something wrong that does not block this merge, in a file this
     diff touches: a stale path in a doc, a one-line config drift, a test that no
     longer asserts what its name says. Not a preference, not a hypothetical, and
     not a restatement of a violation above. The close fixes, files or drops
     each one; a note you leave out is a finding nobody acts on.

     Be thorough. A missed convention ships a security hole or reliability bug to prod.
     The ROUTING block is required so the human reviewer can audit which subsections
     you considered for each file.

     Do NOT mutate repository state — no `git checkout`, `switch`, `reset`, `stash`,
     `merge`, `rebase`, `add`, or `commit`, and no edits to tracked files. A close is
     in flight; moving `HEAD` corrupts it. Everything you need is reachable without
     moving `HEAD`: read any revision's file content with `git show <sha>:<path>`
     and any revision's changes with `git diff <base>...<tip>`. Both read the object
     database and are unaffected by tree state.

     Read many files one call each, not in a shell loop. If you loop anyway,
     **name the loop variable `entry`, never `path`.** `<path>` above is a placeholder for a
     value, not a suggested variable name: in zsh — the default shell on macOS, and
     so quite possibly yours — `path` is tied to `$PATH`, and a bare `path=…` empties
     the command search path. Every later command in that block then fails with
     `command not found`, `git` included. The damage is not that you stop: it is that
     you may already have scanned some files, and the rest silently return nothing, so
     you would emit `VERDICT: APPROVED` over a remainder you never actually read. If a
     command reports `command not found`, say so in your output and stop — do not
     return a verdict over a partial scan.

     Do NOT create new files either — no scratch scripts, no notes, no probe files,
     not even untracked ones, anywhere in the repository but your scratch directory.
     Compute from a heredoc, or
     write under <absolute path to this agent's scratch directory> and nowhere else:
     other reviewers are running beside you, and a fixed `/tmp` name can be theirs.
     "No edits to tracked files" is not permission to add untracked ones: an untracked
     file is invisible to every `git diff` gate this skill runs, so it survives to the
     close and is attributed to nobody.
     ```

3b. **Spawn the security twin — same dispatch, the other map**.

   **A second agent, not a bigger prompt.** An earlier round measured ~15% overlap across **four** lenses on the same diff, with each of the four reaching its sharpest finding alone; folding security into step 3's prompt is the cheap way to lose that, and it would also push the paste toward the threshold for no gain.

   ⚠ **What this reaches on a stock install is much less than the paragraph above implies, and it was measured.** **On an unlocalized install this gate spawns for infra and meta changes and skips application code** — including "an auth handler, an upload endpoint", the two examples the paragraph above names as the gap it closes. **This is the shipped map's localization debt, not a defect in this step**, and the twin becomes as sharp as the consumer's map is localized. **Say which it was.** When the gate skips every target and the map is unlocalized, report `security: skipped — N of M map sections still carry placeholder globs`, not a bare `no map match`: the first tells a consumer they have work to do, the second reads like a clean bill.
   See `REFERENCE.md` § *Step 2b — provenance*.

   **First, look up the target's security verdict, as the convention lookup does,** before reading the security sources for it. Exit 0 means no gate, no checkout and no spawn for this target; any other exit goes on to the gate below, exit 3's key is kept for item 4, and exit 2's message goes under Step 8's `Security map:` line:

   ```bash
   python3 sysop/scripts/gate_verdict.py lookup security "<target>" "<default branch>" "${CLAUDE_SKILL_DIR}"
   ```

   **Gate and copy — spawn only when the map's globs reach this target.** Unless the lookup printed `REUSE`, from the repo root:

   ```bash
   python3 sysop/scripts/security_map_filter.py "<target>" "<default branch>"
   ```

   It answers `SPAWN` only if some glob in either security map matches a path in this target's diff basis. Report every `WHOLE:` and `UNMATCHABLE:` line it prints under Step 8's `Security map:` line.

   - **Exit 3, `SKIP …`:** no checkout, no spawn and no security verdict for this target. Report the line it printed.
   - **Exit 0, `SPAWN …`:** spawn for this target. `COPY:` is this target's copy of both maps: every section but the `OMITTED:` ones, whose globs are all concrete and miss this diff. `FULL:` is both maps whole. Under `ARM: inline` (10,000 characters or fewer), paste the copy's text into the prompt; under `ARM: file`, hand the agent the `COPY:` path.
   - **Exit 2, or any other exit:** the gate could not be computed, and no agent is spawned for this target. Its security verdict is `VERDICT: BLOCKED`, with the printed message as its one violation, collected at item 4 like any other and counted as checked in item 5: an uncomputed gate is not a skip.

   See `REFERENCE.md` § *Step 2b — the security copy*.

   **Do NOT capture a second baseline.** Step 2's tree and config baselines were taken before the *first* spawn and cover every agent this step spawns as well. Re-capturing here would take the snapshot **after** step 3's agents have run, so a mutation one of them made would be recorded as the starting state and the assertion below would then certify the tree clean over it — the exact inversion step 2's own note warns about.

   **On `SPAWN`, the twin's spawn is an arm** (its `ARM: inline` or `ARM: file` line says how to hand over the copy, and names no arm). Run, from the main checkout's top level, with the close id `begin` printed:

   ```bash
   python3 sysop/scripts/close_arms.py exited "<close-id>" 2b-twin-spawn 1
   ```

   It prints `ARM: 2b-twin-spawn`. **Exit 2**: stop and show its stderr.

   **Load this arm when the `exited` command above printed `ARM: 2b-twin-spawn`**, once per close: a later target's `SPAWN` follows the arm already loaded. Read `${CLAUDE_SKILL_DIR}/steps/2b-twin-spawn.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=2b-twin-spawn -->

   **Under `--prepare`, a `VERDICT: BLOCKED` in item 4 below stops only its branch, and on the unpushed-main group halts the prepare** (*`--prepare` and `--resume <run-id>`* (`steps/prepare-resume.md`), item 3).

4. Collect all verdicts **and every `NOTES:` line**, **from both fleets**. Keep the notes with their target: Step 4 `4a-fix` acts on them once the approved branches have merged, and a note on a target that does not merge this run is reported, not acted on. If **any** subagent returns `VERDICT: BLOCKED`, first record the approvals as the paragraph below says, then list every violation with its file:line citation and **stop** — do not proceed to Step 3 until violations are fixed or explicitly waived by the user. A target skipped at step 0 has **no verdict** — report it as `skipped (doc-only)`, never as `APPROVED`; an agent that was never spawned has approved nothing. **The same rule binds step 3b's gate**: a target with no security-map glob match has no security verdict, and reporting it as approved would claim a review that never ran. A `REUSE` verdict is not that case: an agent reviewed the same key in the run its line dates.

   **Record each `VERDICT: APPROVED` whose `NOTES:` is `none`**, from both fleets, unless it was reused, with the SHA its agent echoed first, the 64 characters its lookup printed after `KEY:` and, for the convention gate, the lookup's sections. A target whose lookup printed no `KEY:` is not recorded. Under `--dry-run` too: the verdict is a real one.

   ```bash
   # The same sections the lookup was given.
   python3 sysop/scripts/gate_verdict.py record convention "<target>" "<default branch>" "${CLAUDE_SKILL_DIR}" "<echoed SHA>" "<key>" "Prevention Conventions" "Testing Patterns"
   python3 sysop/scripts/gate_verdict.py record security "<target>" "<default branch>" "${CLAUDE_SKILL_DIR}" "<echoed SHA>" "<key>"
   ```

   Exit 2 records nothing and says why: report it and continue.

5. **Record outcomes for Step 8.** Tally `<N checked, N reused, N skipped (doc-only)>` for the `Conventions:` line, and `<N checked, N reused, N skipped (no map match)>` for the `Security map:` line, in the final report. **Two tallies, because they answer different questions and one number cannot carry both** — a close where every target skipped the security twin and every target passed the convention check would otherwise read identically to one where both ran. Without them a skip is invisible in the artifact the human reads, the same gap Step 2d's `N doc-only` tally closes for test decisions.

> **HARD RULE — the agents' worktrees must be gone before Step 3b of the close** (that is **Step 3b of the *skill*, `## Step 3b: Prepare Worktrees for Merge`** — not step 3b of *this* step, which spawns the second fleet). **The assertion below covers BOTH fleets** — it enumerates whatever exists rather than counting what was spawned, so it needs no adjustment for the security twin, and it must run after step 4 has collected from both. Worktree isolation is not free of side effects: on Claude Code it materializes a **real worktree and a real branch** in this repository's shared namespace (observed shape: a worktree under `.claude/worktrees/` on a branch named `worktree-agent-<id>`). The harness removes them when an agent finishes and left its checkout unchanged — but an agent that wrote a scratch file, or a run that was interrupted, leaks both.
>
> **It must be a delta, not an absolute cleanliness test — that is why step 2 above captures a baseline.** Nothing in this skill establishes that the primary worktree is clean before the agents run: Step 1a excludes it by construction (it skips the **primary checkout**, matched by path identity, as Step 6's `pr` re-sync note also states in its own words — until this phase both sites said *the worktree whose branch is `main`*, which is the same worktree only while the primary happens to be on `main`). A bare `git diff --quiet HEAD --` here would fire on any ordinary uncommitted work and SKIP a close that is fine — a false-FAIL on the dominant path, which is how a gate gets disabled by the first operator who hits it.
>
> **Remove step 3's pinned checkouts FIRST — they are yours, and the assertion below is not
> the place to discover them.** The orchestrator created one per agent and nothing else
> deletes them, so running the assertion first reports a "leak" on **every** close that
> spawned anything: a false-FAIL on the dominant path, which is how a gate gets disabled by
> the first operator who hits it. Remove them once both fleets have reported, then assert
> that none remain:
>
> ```bash
> python3 sysop/scripts/review_pins.py clean
> ```
>
> **A `DIRTY:` line (the checkout is dirty) or a `MOVED:` line (its HEAD left the pinned commit) is a FINDING, not an obstacle.**
> The prompt forbids writing to the pinned tree, so either means a lens changed the
> revision its siblings were reading, and every verdict from that fleet is suspect — read
> the diff, decide whether to re-run the fleet, and only then `git worktree remove --force`.
> Do not reach for `--force` first; it deletes the evidence that tells you whether the round
> is trustworthy.
>
> After that, and after step 4 collects the verdicts, assert all five are clean before continuing:
>
> ```bash
> python3 sysop/scripts/review_pins.py check
> ```
>
> It runs the five in order, printing each one's clean line or what it found, and exits 1 when any is not clean.
>

**If any of the five printed anything but its clean line** (`no agent worktrees`, `no agent branches`, `primary tree unchanged by 2b`, `local config unchanged by 2b`, `no pinned checkouts`, each alone), what each one means is an arm. Run, from the main checkout's top level, with the close id `begin` printed:

```bash
python3 sysop/scripts/close_arms.py exited "<close-id>" 2b-leak 1
```

It prints `ARM: 2b-leak`. **Exit 2**: stop and show its stderr.

**Load this arm when the `exited` command above printed `ARM: 2b-leak`**. Read `${CLAUDE_SKILL_DIR}/steps/2b-leak.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=2b-leak -->
>
>
> **If your harness offers no `isolation` parameter, the first two checks do not apply — but the third one matters MORE, not less.** With no isolation the agents run directly in this checkout, so the prompt's do-not-mutate rule is the only thing standing between a stray edit and the close, and it has now been measured failing twice. Run the baseline and the delta. (An honest limit, stated so the check is not over-trusted: a tight window still cannot distinguish an agent's edit from a human's edit made while the agents ran.)
> See `REFERENCE.md` § *Step 2b — provenance*.

### 2c. Unpushed Main Commits

If main is ahead of origin:
1. `git log --oneline origin/<default branch>..HEAD` — list the unpushed commits
2. Review each commit's changes: `git show --stat <hash>` for each
3. Verify the changes look intentional and complete (no half-finished work, no debug code left in)
4. Check that documentation is accounted for: either `docs:` prefixed commits exist (legacy) or `sysop/runtime/pending-docs/*.md` files are present (current workflow)

### 2d. Test-Decision Verification (verify the record)

Every task claimed through `/claim-task` records a **test decision** in its body at plan time: either `test <X> proves <Y>` (the regression test that pins the changed behavior) or `no test because <Z>` (the reviewable rationale for adding none). See `tasks/schema.md` § Test decision. This step **verifies that record against what the branch actually delivers**, and it is the *only* thing that does. It does **not** re-judge whether a test *should* exist; that judgment is the adversarial plan reviewer's "Missing invariant tests" dimension (`_shared/adversarial-review.md` finding 7), applied at plan time. Verify the record, don't re-judge.
See `REFERENCE.md` § *Step 2d — provenance*.

> **The premise sentence above is accurate about `/claim-task` and it is not the gate's reach.** Every task claimed through that skill records a test decision; **not every task on a branch under review was claimed through it.** Grepping the shipped skills: `/auto-fix` writes the record **0** times, `/auto-judge` **0**, and manual work on a hand-cut branch writes none. **Do not re-derive this list by counting mentions of the heading**: several skills now *reference* it without writing it. This step nevertheless reads the record for each task ID the branch claims, whatever produced it, so a task that was never owed a record and a task whose record is genuinely missing used to arrive at the same prompt with the same three answers. The fourth disposition below separates them.
> See `REFERENCE.md` § *Step 2d — provenance*.

This is the sibling of Step 3c's manual-smoke gate — a per-task body convention, enforced here and nowhere else — and reuses the same shape: a deterministic classification (like Step 1a's worktree verdict) plus an `AskUserQuestion` halt on mismatch (like Step 3c).

For each **approved** feature branch (Step 2a verdict) except one approved as landed (Step 2a step 0b), for each task ID it claims (path resolved exactly as in Step 2a step 3 — `tasks/index.yml`'s `body:` per claimed ID):

> **Read the record at the branch tip — not out of the working tree.** Both writing paths *decide* the test decision at plan time, and on both the **executor writes it into the body during implementation, inside the worktree** — `/claim-task` at Step 7e Sequence item 3, `/auto-build` at Step 7c Sequence item 3‑record — so the section is committed on the feature branch and nowhere else. Step 2d runs at Step 2; nothing merges until Step 3b/4a. `HEAD` is still `main`, so the working tree's copy of the body is whatever `main` has — and for a task claimed this cycle that copy carries **no test-decision heading at all**, because every shipped body-author is told not to write one (`intake/SKILL.md:121`, `add-task/SKILL.md:64`, `onboard/SKILL.md:103`; the schema's placeholder is a template, not something a real body normally holds). Reading *that* copy therefore classifies the record `missing` for every task on every branch on every run, and each `missing` fires the halt below. **Nothing spares one** — step 0's doc-only skip does not, because a `missing` classification is not the `no-test` its second conjunct requires, so a doc-only branch halts here too. A gate that only ever reports the state of a revision it is not gating. Resolve the *path* from `main`'s `tasks/index.yml` — correct, because a claim does not move the body and Step 4c's archive move runs after this step — and read the *content* from the revision under review:
>
> ```bash
> # `body:` is canonically relative to `tasks/` — `open/<TASK-ID>.md`, NOT
> # `tasks/open/<TASK-ID>.md` (`tasks/schema.md` § body) — while `git show <rev>:<path>`
> # takes a REPO-ROOT-relative path. Resolve with the same two-branch rule all three
> # shipped readers use (validate_tasks.py, next_task.py, scope_overlap.py): prepend
> # `tasks/` unless the recorded value already starts with it. Quote the operand —
> # unquoted, `<…>` is a redirection to bash, not a placeholder (Step 6 states the same
> # rule for `git branch -D`), and an unquoted path containing a space truncates at it.
> #
> # This step ships NO LOOP and the lines below are one-shot templates, so you will
> # write the iteration yourself. **Name the loop variable `entry`, never `path`.**
> # In zsh — the default macOS shell — `path` is tied to `$PATH`, and `path=…`
> # REPLACES the command search path with the loop value, after which `git` is not
> # found. Step 1's fifth `unreadable` outcome has the diagnosis; this comment is
> # here so you never need it. Same rule, same reason, as Step 1a and Step 3b.
> # (The two lines below are one-shot templates on purpose — the quoting and the
> # canonical/back-compat pair are what they demonstrate. The loop is yours.)
> git show "refs/heads/<branch>:tasks/<body as recorded>"    # canonical:   body: open/<TASK-ID>.md
> git show "refs/heads/<branch>:<body as recorded>"          # back-compat: body: tasks/open/<TASK-ID>.md
> ```
>
> **Getting that prefix wrong is not a cosmetic slip** — it produces `fatal: path … does not exist`, which is exactly the `unreadable` signature below, so a mis-resolved path halts the close wearing a diagnosis that blames the branch. Check the recorded `body:` value before concluding anything from **that** fatal — and read the signature first, because the advice is wrong for the others: `ambiguous argument` and `invalid object name` **cannot** be produced by a prefix mistake, so re-checking `body:` there sends you looking in the one place the fault is not. This is the object-database read Step 2b's prompt already prescribes, and it is the same revision `git diff <default branch>...refs/heads/<branch>` reports — both halves of this gate must come from one revision, or the comparison is between two different trees. `WORKFLOW_GUIDE.md` § Merge Process already says to read "**the branch's** `## Test decision`" back against the diff, so the branch-tip read restores the spec rather than inventing a rule; `WORKFLOW.md` § 2.8 ("each approved branch's task body") scopes *whose* body rather than *which revision*, so it is consistent with that reading without compelling it.

**Under `--prepare`, ask nothing in item 3 below:** record each discrepancy as a question (*`--prepare` and `--resume <run-id>`* (`steps/prepare-resume.md`), item 2), and carry the branch on with its verdict marked `pending Q<n>`.

**0. Per-branch doc-only skip.** If this branch's diff (`git diff <default branch>...refs/heads/<branch>` — three dots, per Step 2a's note) touches no code files (the same code-file set Step 3 uses — `.py` / `.ts` / `.tsx` / `.js` / `.jsx` / `.sql` / `.sh` / `.kt` / `.swift` / `.go` / `.rs`), **and** *that task's* recorded decision is a `no-test`, skip verification for it with a one-line note (`2d: <branch>/<task id> — doc-only diff, no-test record`). **The two conjuncts have different granularity, and the skip takes the narrower one.** The diff test is per *branch*; the record is per *task*, and this gate iterates the tasks a branch claims. So a doc-only branch claiming two tasks skips only the task whose record is a `no-test` — the other is verified, which is the point: a record naming a test must not be silenced because a sibling task's record said none was needed. **Resolve step 1's read before deciding this** — the second conjunct is a fact about the record, so the classification has to exist before the skip can be evaluated, and reading it is one `git show` this gate runs either way. What this skip saves is step 2's verification, not the read; a step 0 that fired before the record was classified would be deciding on the extension test alone, which is the defect. An `unreadable` or `missing` classification is **not** a `no-test` and does not earn the skip — those have their own arms below. **A record that names a test is verified whatever the extensions say** — checking that the named test is present costs one read and is exactly as meaningful on a semgrep rule or a `checks.yml` entry as on a `.py` file. The extension test cannot carry this skip alone, because it calls semgrep rules, `checks.yml`, CI workflows and served-model config documentation, and a branch changes behaviour through any of them; Sysop's own `coverage-*` `blocking: true` flip had that shape. Step 2b's skip carries a second conjunct too — a different predicate (no rule in `## Prevention Conventions`, in a sibling CLAUDE.md section, or in either convention map governs the touched types), the same reason: the extension test is evidence about file names, and neither gate is about file names.

**1. Read the record.** Read the body **at the branch tip** (`git show "refs/heads/<branch>:<repo-root-relative body path>"`, resolved and quoted per the note above — never the working-tree copy) and find the section under a heading whose text matches `test\s+decision` (case-insensitive — `## Test decision`, `### Test Decision` both match; the pattern is defined in `tasks/schema.md` § Test decision, which is now its only home). Classify it:

- **`test-proves`** — the section names a test (the `test <X> proves <Y>` shape).
- **`no-test`** — the section states `no test because <Z>`.
- **`missing`** — no test-decision heading **at the branch tip**, or the section still holds the schema template placeholder (`<recorded at /claim-task plan time …>`). **Reachable only from output you know you read.** Empty output is not evidence of an absent heading: **two** `unreadable` outcomes below produce exactly it — the fifth under capture, and outcome 4's quiet sub-case, which exits **0** and so passes any "did it run?" check. Confirm you read file content from a revision, not an empty result. This is the only classification on this list a failed read can counterfeit.
- **`unreadable`** — `git show` did not hand you the file at the branch tip. **Five distinct outcomes land here, and the definition used to name only the first, so the others routed nowhere at all** — the first four verified by execution against git 2.50.1, the fifth against zsh 5.9:
  - `fatal: path '…' does not exist in '…'` — the rev resolved, the path did not. **Before believing it, re-check the `tasks/` prefix rule above — a mis-resolved path produces this identical fatal, and that is the likelier cause.** Genuinely reachable when the claim reused a pre-existing branch cut before the body file was written, since `claim_task.sh` reuses an existing branch rather than refusing.
  - `fatal: ambiguous argument '…': unknown revision or path not in the working tree.` — the **operand itself** was mangled, so neither half resolved. The `tasks/` prefix rule **cannot** produce this signature, so re-checking the prefix here is a dead end; check what mangled the operand instead. The known cause is a zsh history-modifier expansion: unbraced `"$b:tasks/…"` under zsh applies `:t` and eats the leading `t`, turning the path into `asks/…` — measured, and the shipped placeholders are braced/quoted literals precisely so this cannot arise from the skill's own text.
  - `fatal: invalid object name '…'.` — the **path** resolved but the rev did not exist. A stale or misspelled branch name, not a missing body.
  - **Exit `0` with a commit diff instead of a file — the one that is not a fatal, and the only one that can fabricate a verdict.** An operand that lost its `<rev>:` makes `git show <path>` mean `git show HEAD -- <path>`: it does **not** walk history — that correction is the round's — it shows **`HEAD`**, and exits **0** either way. Two sub-cases, and the quiet one is likelier: if `HEAD` happens to touch that path you get a commit diff whose `+` lines can contain `## Test decision` and the prose beneath it; if it does not, you get **exit 0 and no output at all**, which reads as an empty body rather than as a failed read. A reader scanning that output for the record finds one — **from the wrong revision, on `main`, not on the branch.** So do not treat exit 0 as proof you read the body: **confirm the operand you sent contained a literal `:`, and that the output is file content rather than a diff** (a `commit <sha>` header line, or lines beginning `+`/`-`/`@@`, means you read a commit). This is the fabricated-finding case the paragraph below forbids, arriving through the one door that looks like success.

  - **`zsh: command not found: git` — the loop variable took `$PATH` with it.** The command block above now ships this rule as a comment, so this should be unreachable; it is listed because a reader who wrote their own loop before reaching that block still lands here. In zsh — the default macOS shell — `path` is tied to `$PATH`, and `path=…` **replaces** the command search path with the loop value (it does not empty it; if that value names a real bin directory the command may even still resolve). `git` is then not found. Whether you *see* that depends on how you ran it: bare, as the block above prescribes, the error reaches you; captured — `out=$(git show "$rev:$entry" 2>/dev/null)` — you get empty stdout and the evidence goes to the stderr you discarded. Exit **127**. Treat it as `unreadable`, and check the loop variable before the branch.

  **None of the five is `missing`:** nothing has been asserted about the record either way, and reporting it as `missing` would put a fabricated finding in front of the human. Surface the branch, the path you resolved, the revision you read, and **which of the five outcomes you got** — they have different causes and the disposition used to collapse them.

  **Empty output identifies nothing on its own, and that is why the exit status is part of the report.** Three different states produce zero bytes on stdout: the fifth outcome under capture, outcome 4's quiet sub-case (the operand having lost its `<rev>:`, on a `HEAD` that does not touch that path), and a task body that is genuinely empty. They are **not** distinguishable by looking at the output, and one of them is not even a failed read. The exit status separates them where silence cannot: **127** for the clobbered `$PATH`, **128** for a path absent from the revision, **0** for a real body *and* for outcome 4's quiet case. Note what that last pair means — **a "did the command run?" check passes for outcome 4's quiet case**, because it did run and it exited 0, so that check alone cannot keep you out of `missing`. What does: confirm you are holding **file content from a named revision**, not an empty result. All measured.

**2. Verify the record against the branch diff:**

- **`test-proves` → "plan said test X — is it here?"** Confirm the diff adds or modifies a test matching X — a changed file on the project's test path (`tests/`, `*_test.py`, `*.test.ts`, `*.spec.ts`, or the project's documented test location) and, when X names a specific test/function, that name appearing in the diff. If the diff touches **no** test file at all, the record claims a test that wasn't delivered → **discrepancy**. (Record-vs-reality only: a test that is present but weak is out of scope here — that's the reviewer's coverage judgment, not this gate's.)
- **`no-test` → "plan said no-test-because-Z — does Z still hold?"** Re-read `Z` against the diff. `Z` **holds** when the diff's character still matches the stated rationale (pure rename/move, config-only, docs-only, covered by an existing named test, `manual_smoke:`-only) — **with the caveat that "config-only" and "docs-only" name a file's extension, not its consequence.** A semgrep rule, a `checks.yml` entry, a CI workflow, a lockfile pin and a lint config are all config, and each is behaviour a project checks; where the diff changes one of those, `Z` holds only if the rationale anticipated *that*, not merely that no `.py` file moved. `Z` is **stale** when the diff now carries behavior changes the rationale didn't anticipate (e.g. `Z` said "pure rename" but the diff edits logic) → **discrepancy**. This carries inherent judgment residue — acknowledged and bounded: you are matching the recorded rationale to the diff, **not** forming a fresh opinion that a test ought to exist.
- **`missing` → record absent.** This is the **first** notice, not a second one: nothing upstream warns on it any more (an earlier build retired the validator's warn-only test-decision check, which could not see this record at all from `main`). Treat as a discrepancy to surface.

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
python3 sysop/scripts/git_check.py lock "<TASK_ID>"
```

- **Lock present → the record was owed.** Do **not** offer *record not owed* for this task. `/claim-task` Step 7e writes the record and re-reads its own write in the worktree before committing, and the orchestrator then re-checks the same fact **at the branch tip** at Step 8 — the revision this gate reads. (Two different reads: 7e greps the worktree copy, Step 8 reads the branch. Attributing the branch-tip read to 7e, as the first draft of this sentence did, would tell a reader the worktree grep already proves what only the Step 8 arm proves.) So a missing record here is a real miss, not an unowed one, and waiving it as *not owed* would launder exactly the failure that read-back exists to surface.
- **Lock absent → cannot tell, and that is the honest answer.** `sysop/runtime/` is gitignored, so a fresh clone, a rebuilt worktree or a `/claim-task --resume` after a break all legitimately carry nothing; a non-Claude harness never wrote one; and the branch may not come from `/claim-task` at all. Offer all four options and let the human decide. **Never render absence as "the orchestrator did not run"** — this is the same three-valued rule Step 2e states in full, for the same reason.

> **Why the lock and not the run directory, stated as the argument it actually is.** A *retrospective* survey cannot settle this, and an earlier version of this note claimed it had. Over 476 archived tasks in a live consumer, run-directory presence looks like a strong signal (29/29 carried the record against a 15% base rate); it is confounded (all 29 closed in one month whose base rate was already 71%) and it is useless retrospectively, because every one of the 378 tasks missing a record is in the run-directory-absent bucket. **But the same test is worse for the lock, not better**: Step 4c removes both, and among those 476 tasks **0 locks survive against 29 run directories**. So the corpus disqualifies run directories as a *retrospective* proxy — which is all the retraction ever claimed — and says nothing about either artifact at gate time, where neither has been reaped yet.
>
> The real reason is **structural, and it is about the direction this signal is used in.** A lock exists for *every* `claim_task.sh` claim; a run directory exists only when the Step 7 orchestrator actually ran. The lock is therefore the **broader** signal — and this step uses it only to **withhold** the *record not owed* escape. For a withholding use, over-inclusion costs a waiver and under-inclusion lets a genuine miss be dismissed as unowed, so the broader artifact is the safe one. It is also written by a **script** rather than by an agent, so it cannot be skipped by a run that failed to follow the orchestration — which is precisely the documented failure.

**2‑also. The `## Also fixed` arm.**
See `REFERENCE.md` § *Step 2d — provenance*.

**This arm runs for every claimed task on every approved branch, including a task item 0 skipped.** It is inside Step 2d's loop, so its reach is that loop's: a branch claiming no roadmap task id — a review-batch branch, which holds a `BATCH-<N>.lock` rather than a `tasks/index.yml` claim, or a hand-cut branch — never enters it and is not covered here. Said plainly rather than left implied, because an earlier draft of this sentence claimed *every branch* and Step 2d cannot deliver that. Item 0's doc-only skip is scoped to *test-decision verification* — it exists because a docs branch carrying a `no test because Z` needs no test hunt. Carrying that skip across to this arm would silence it on precisely the branches most likely to trip it: a doc correction is the archetypal in-branch fix, so doc-only branches are where `## Also fixed` is *most* expected, not least. If item 0 skipped this branch, read the body anyway for this arm alone.

Once the body is in hand, this arm re-reads nothing. Find **every** section under a heading matching `also\s+fixed` (case-insensitive) — a **search, not an equality test**: `## Also fixed (PR 1)` is a real heading in a live consumer corpus and must match. **Two sections in one body is a reachable shape, so do not stop at the first match.** Each section ends at the next heading of the **same or shallower** depth, so a `#### ` sub-heading inside one belongs to it rather than terminating it. **Count three things as headings, because two of them are easy to miss and both fail in the over-counting direction**: an ATX heading indented by up to three spaces is still a heading (four or more is a code block), and a **setext** heading — a line of text underlined by `===` (depth 1) or `---` (depth 2) — is one too. A terminator model anchored to a column-0 `#` sees neither, so the section over-runs into the next one and the tally reports its entries as well. The error a first-match reader makes is an **undercount**, and that is the damaging direction. **Skip fenced content when you look** — a plan that discusses this very rule will quote the heading, and a fence-blind reader then reports check-1 findings against paths the branch legitimately never touched, a fabricated finding, which is the worst outcome this skill has. A fence opens on ``` or `~~~` and closes on a marker using the **same character**, **at least as long** as the opener, **and carrying no info string** — take only headings outside one. **Stated here in full rather than by reference to another skill**, because a rule held only by pointing at another skill's code moves when that code does. All of `/claim-task`'s walkers, the Step 7f script among them, now delegate the closer decision to one `fence_closes` predicate per block, cited at two lines that cannot be swapped for one another — `claim_record.py:80` and `claim-task/SKILL.md:1665`; an opener may carry an info string, a closer may not.
See `REFERENCE.md` § *Step 2d — provenance*.

**Why the info-string clause is load-bearing.** A ```` ```json ```` line *inside* a ```` ``` ```` fence is content, not a closer — a reader that accepts it as one believes it has left the fence while it is still inside, and then reads the fence's remaining lines as real sections, the fabricated-finding outcome this paragraph exists to prevent.
See `REFERENCE.md` § *Step 2d — provenance*.

**On an unterminated fence, report and stop — do not guess.** The arm is silent about this shape today and silence picks the worst answer by default: a reader that stays "inside" to EOF loses every real section and says nothing (the absence branch below is silent by design), and one that falls back to fence-blind reads the plan's quotations as records. Neither may pass unannounced, so surface it as `also-fixed record — unbalanced fences in <body>, not parsed` and let the human decide. `/claim-task` Step 8 detects the same condition and prints a NOTE rather than choosing silently; this is that rule, not a new one. **The ordering rule does not save you here**: `## Also fixed` before `## Plan` protects a first-match reader only when a real section exists, which is exactly the case where you did not need protecting.

- **No section anywhere → done. Absence is never a finding here**, and this arm never halts on it. The section is optional by design (`tasks/schema.md` § *Also fixed*): most branches carry no adjacent fix, and a branch that fixed nothing extra is the normal case, not an omission. This is the opposite of the test-decision arm above, where `missing` *is* the finding — do not carry the halt across.
- **One or more sections → check three things**, all against `git diff --name-only <default branch>...refs/heads/<branch>` (three dots, per Step 2a's note), which you already have. **Run all three over each section you found and report the union** — a finding in the second section is a finding, and the numbers item 4 asks for are sums across the sections rather than the first one's:
  1. **A line that names paths names at least one in the diff**. A line whose named paths are **all** outside the diff is a record of something that did not happen — a fabricated or copy-pasted entry — and the human reads the record: that is a finding. A line with **at least one** path in the diff may name others outside it, which is how a fix cites where the defect showed (its call sites, a reproduction): report each outside path as a note, `also-fixed note — <TASK-ID>: <path> named, not in the diff`, carry it to Step 8, and **do not halt on it**. A line naming no path at all is outside this check. **Know this check's reach before you rely on it:** it compares against the *whole* branch diff, so it catches a line none of whose paths the branch touched and nothing narrower. A fabricated line naming a file the task itself changed passes it trivially. That is a real bound, not a quibble — the check is a cheap screen against copy-paste, not a proof the fix happened. The `answers:` path in an approval suffix is not a path the line names: it is a gitignored run artifact that is never in the diff, and check 2 reads it. A path inside the quoted question still is.
  2. **No line concerns a never-list item without a recorded approval.** Migrations, auth or payment logic, or anything that writes to production. These are fixed in-branch only on the human's answer, and the line then ends `(approved: <YYYY-MM-DD>, "<the question as asked>")`. A line concerning one without that suffix means the rule was exceeded, whether or not the fix itself is correct. `/claim-task`'s answers run writes the suffix with `, answers: <path>` before the closing parenthesis: open that path in the main checkout, and if it exists and neither it nor an archived `answers.<n>.md` beside it records the line's question with `decision: fix`, that is a finding. An absent file, reaped by an earlier close or on another machine, is a note and not a finding.
  3. **The fixes are reviewable here.** The rule admits fixes of any size and in any module, as long as this close can read them. **Judge the summed set**, never each section's alone: the bound is per *branch*, so two sections that are each readable can still add up to a branch that is not. A branch whose fixes you cannot review properly in this close is a finding, even when each fix looks right.

**Judge checks 2 and 3 against today's rule.** Every earlier bound was narrower, with a longer never-list and a size limit, so a section written under one cannot fail them. An older section that breached its own older bound, such as a fix to a prompt body, passes today by that decision.

A finding on any of the three joins item 3's halt with the reason `also-fixed record — <detail>`, and takes the same four dispositions. **Prefer "Hold for fix" over "Waive" on check 1 specifically**: a false line in the record is cheap to delete and expensive to leave, because every later reader treats it as evidence the fix was reviewed.

**2‑after. The `## After merge` read.** From the same body, take every section whose heading text **begins** with `(?:after|post)[\s-]+merg(?:e|ing)` (case-insensitive), so `## After merge`, `## After-merge steps` and `## Post-merge steps` all match and `## Rollback if staging breaks after merging` does not. Find and bound each section exactly as the `2‑also` arm finds its sections, fences skipped. It has the same reach: claimed tasks on approved branches, including a task item 0 skipped. Check nothing and halt on nothing. Absence is the normal case. Carry each section verbatim, with its task ID and branch, to Step 8's `After merge:` line. A branch Step 2a approved as landed is not read.

**3. On a clean match, pass silently** (carry a `verified` note for Step 8). **On any discrepancy, missing record, or unreadable body, halt and ask** via `AskUserQuestion` (one task at a time, mirroring Step 3c). Present the recorded decision text verbatim, the task ID, **the revision you read it from**, what the diff shows, and **the ownership-probe verdict**. Options (single-select) — three always, plus a fourth only when the ownership probe said `CANNOT TELL`:

- **"Record holds — proceed"** — the human confirms the record is accurate or the rationale still applies; the branch stays approved.
- **"Hold for fix — don't merge this run"** — demote this branch from **approved** to **rejected** for this run, with the reason `test-decision record needs fixing — <detail>`. Downstream steps already handle a rejected branch correctly with no special-casing: Step 3b/Step 4 skip it (only approved branches merge), Step 6 leaves its worktree, lock, and branch intact for follow-up, and Step 8 reports it under "Remaining" with the reason. The test can then be added or the record corrected before a later `/review-close`.
- **"Waive — proceed with noted waiver"** — the branch stays approved; record a waiver (task ID + decision text) for Step 8. Use for accepted judgment calls (e.g. a stale-looking `Z` the human confirms is fine). **A waiver means the record was owed and is being let through anyway** — if it was never owed, the next option is the correct one and this one overstates what happened.
- **"Record not owed — no orchestrated plan ran"** — *offered only when the ownership probe said `CANNOT TELL`, and only on a `missing` record.* The branch stays approved and **nothing is waived**, because there was nothing to waive: the work came from `/auto-fix`, `/auto-judge`, a hand-cut branch or a manual edit, none of which write this record. Tally it separately (below). This is deliberately **not** a quieter waiver — it is the disposition that makes the tally mean something, so do not reach for it when the ownership probe said `OWED`, or when the record is merely *stale* rather than absent.

Waivers, "record holds" and "record not owed" do not block. Only "hold for fix" changes the verdict, and it does so by reusing the existing **reject** disposition — no edits to Steps 3b/4/6 are needed.

**4. Record outcomes for Step 8.** Tally per task: `verified`, `waived`, `not owed`, `held for fix` (now rejected), `unreadable`, or `skipped (doc-only)`. Tally the `## Also fixed` arm separately into its **own `Also fixed:` line** in the Step 8 report — `<N branches carrying a section, N lines total, N findings, N notes>` — never folded into the `Test decisions:` line, whose six fields answer a different question. **`N lines total` sums every section found, and a branch carrying two sections still counts once in the first field.** **A line is a list ITEM, not a physical line**. Count an item for each list marker at the section's top level — `-`, `*`, `+`, or `1.` — and **do not count its continuation lines or its nested sub-items**, which belong to the entry above them. A section that **records no entries** contributes **zero** — so do not read the rule as requiring a `_(none)_` marker to be the section's whole content; it is the absence of list items that makes the count zero. This drives the "Test decisions" line in the final report. **`waived` and `not owed` are counted separately and must not be merged back into one number** — that conflation is the whole reason the fourth disposition exists.
See `REFERENCE.md` § *Step 2d — provenance*.

If the approved-branch set is empty (only unpushed main commits this cycle), Step 2d is a no-op — unpushed main commits don't carry `/claim-task` test-decision records. Skip cleanly.

> **For new projects:** the test decision is decided by `/claim-task`'s planner at Step 7a and written into the task body by the Step 7e executor during implementation — or, on the plan-only path, by Step 7f, which has no executor to do it later (`tasks/schema.md` § Test decision). This gate reads it back — keep the `Z` in a `no test because Z` rationale concrete so "does Z still hold?" stays answerable.

### 2e. Claim-Artifact Report (report, never reject)

`/claim-task` Step 7 is an orchestrator: it spawns a planner, an independent reviewer, and an executor, and each stage leaves a file behind. This step **reports which of those files exist for each branch under review**. It is the close-path half of a pair: `/sitrep`'s `_claim_stall` probe is the other. They share the report-unknown rule below, not their artifact set — this step reads five run files plus the hook envelopes, the probe reads park markers plus `classification.md` and `outcome.md`.

**It never changes a branch's disposition.** No verdict moves, no branch is rejected, nothing halts. That is a decision with an argument, not caution: a *rejecting* gate must know whether it applies, and getting that wrong is a false FAIL on work already done — which is exactly how an earlier attempt died (a predicate inert on the review-batch claims it was reported for, a false FAIL on the dominant path, and 41 of 53 guard mutations surviving). A *reporting* step that mis-resolves prints "no artifacts found" beside a branch that has them: wrong, visible, and self-correcting. Sysop's settled pattern is **surface the ambiguous class, block the unambiguous one** (one mechanism blocks `failed`, another exits non-zero on a demonstrably-abandoned round, a third purely surfaces), and artifact absence is squarely the ambiguous class — see the rule below for why.

> **Report unknown. Never report "did not run".** Absence of these files is **not** evidence that the pipeline was skipped, and a report that says otherwise accuses honest consumers:
>
> - `sysop/runtime/` is **gitignored**, so a fresh clone, a rebuilt worktree and a `/claim-task --resume` after an overnight break all legitimately carry nothing.
> - The envelope is written by the `SubagentStop` hook, which is **Claude Code only** — a Codex or other-harness consumer never produces one, however correctly the claim ran.
> - A branch may not come from `/claim-task` at all (a hotfix, an `--adopt`, a hand-cut branch).
>
> So render three-valued — **present** / **absent** / **cannot tell** — and when the claim directory itself is missing, say *no artifact directory on disk* rather than anything about what ran. The unforgeability of this artifact set is a property of *a Claude Code run inspected before its runtime dir is gone*, not of the design.

**Resolve the branch to a claim id from the lock, not from the branch name.** Branch names are not reversible: Step 3 of `/claim-task` auto-generates one from the task id, but `--branch <name>` and `tasks/index.yml`'s `branch:` field both override it, and a review batch's branch comes from `review_tasks.md`. The lock file is the reverse map that exists — it records `branch:` against its own `task_id` — and locks are still on disk at Step 2 (Step 4c removes them). A branch with no matching lock is reported as such; it is not an error.

Run this once for the whole close, passing every branch Step 2a classified — **approved and rejected alike**, since a report changes nothing and a rejected branch's artifacts are exactly what a human wants when deciding what to do with it.

```bash
# Run from the repo root, as written. Substitute each branch name literally and QUOTED:
# unquoted, `<…>` is a redirection to bash rather than a placeholder.
python3 sysop/scripts/claim_artifacts.py "<branch 1>" "<branch 2>" "<...one argument per branch under review...>"
```

**Read the block into the Step 8 report — the `Orchestrator artifacts:` line, not `Claim artifacts:`, which is Step 4c's removal tally — and continue.** Nothing here gates anything: a branch with every artifact absent proceeds exactly as it would have, and a branch with every artifact present is not thereby approved. If a consumer ever reports a run where the artifacts were absent, the report was ignored, and the branch merged anyway, *that* is the evidence for revisiting a blocking form — and it should be revisited here, never at `/document-work`, whose earlier hard fail punished at the worst possible moment, after implementation.

## Step 3: Run Verification

> **Before you skip, weaken, or reword any rule in this step, read `REFERENCE.md` § `RC-3-1`
> through § `RC-3-8`.** Those eight rules are declared load-bearing and pinned by a required
> check: each section names what its loss would change, which is the thing this step cannot tell
> you while you are running it. The rest of this skill is not covered — do not read the file's
> existence as coverage of anything outside Step 3.

**This is the pre-merge pass, and it can only verify the tree it runs on.** `HEAD` is still `main` here — Step 3b has not removed a worktree and Step 4a has not merged anything — so no approved branch's files are in this working tree and its new tests do not exist yet. What this pass verifies is *this* tree: `origin/<default branch>` plus whatever local-only commits `main` already carries. It is a fail-fast on the base, and it is the last point where stopping is free. **It is not a verdict on the work, and nothing here may be reported as having verified a branch** — that verdict is `4a-post`, which re-runs the same resolved list on the merge target once the branches are merged.

**Each pass scopes itself to its own tree, with one command.** Item 3's surface gate reads the list this prints at **both** passes; item 4's doc-only skip reads it at **this pass only**, because `4a-post` does not inherit it:

```bash
# The changed-file list for THIS pass, read off stdout. Three dots, always — two would
# render everything the base gained since a branch was cut as though the branch deleted
# it (the Step 2a note). Run from the repo root.
git rev-parse --verify origin/<default branch> >/dev/null 2>&1 \
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

**The item-5 stop is about the run, not about this pass — resolve before you skip.** Item 4 decides whether to *run* the list; it does not decide whether the list had to exist. Taken in bare sequence the two collide on the dominant path: this pass's diff is doc-only, item 4 fires, and item 5 is never reached — so a consumer with no `## Pre-merge verification`, no `scripts.verify` and no detectable surface sails through Step 3 and hits "stop and ask the user what to run" at `4a-post`, **after every branch has been merged**, which is the one outcome this step exists to prevent. So run item 5 against the *run*: if no source produced a command list and **any** part of this cycle touches code — this pass's changed-file list, or `git diff --name-only <default branch>...refs/heads/<branch>` for any approved branch (the same per-branch read Step 3c makes) — stop and ask **here**, whether or not item 4 skipped the run.

If any command fails, report the failure and **stop**. Do not push with failing checks. Stopping *here* is free — nothing has been merged, no worktree has been removed, no lock has been dropped — so fix the failure and re-run `/review-close` from the top. (`4a-post` has a stop of its own, and it is not free in the same way; its recovery is stated there per policy.)

**Under `--prepare`:** a failing command halts the prepare (*`--prepare` and `--resume <run-id>`* (`steps/prepare-resume.md`), item 4). Item 5's ask and a silently denied command leave Step 3 not run, with the reason in the run directory, and the resume runs it (*`--prepare` and `--resume <run-id>`* (`steps/prepare-resume.md`), item 2).

**Venv-aware invocation** (the consumer's own tooling — **not** `sysop/scripts/*.py`, which resolve venv PyYAML themselves and are always invoked with a bare `python3`; see WORKFLOW.md § 6.1). If a verification command fails with `exit 127` (command not found) or `ModuleNotFoundError` and the project has a `.venv/` directory at the repo root, re-run with `.venv/bin/<cmd>` (for explicit binaries like `.venv/bin/pytest`) or `PATH=.venv/bin:$PATH <cmd>` (for shell pipelines or tools that re-exec). Same pattern as Step 4d's pre-push hook venv prefix. The canonical fix is consumer-side — the project's `<project>/CLAUDE.md § Pre-merge verification` commands should be authored with `.venv/bin/` prefixes when they depend on venv-installed tools (see WORKFLOW.md § 6.1 venv-aware-invocation paragraph) — but the prefix-on-rerun pattern unblocks the cycle when the consumer's command list hasn't been venv-ified yet.

**Boy-scout escalation (ratchet consequence).** A `### Ratchet` snippet invokes the project's lint/typecheck tool against the changed-file list, so if a file in the diff carries pre-existing findings — warnings or type errors not introduced in this review pass — the tool will report them and the gate will fail. That's intentional and not a Sysop-side rule: touching a file means cleaning it. Full-tree backlog cleanups stay as separate project-side tasks (e.g. `TECH-LINT-BACKLOG-FIX`, `TECH-TYPECHECK-BACKLOG-FIX` entries in `tasks/index.yml`), so the ratchet doesn't impose a clean-everything-first dependency on consumers with existing backlogs.

**If a verification command is silently denied** (auto-mode classifier rejects a `npm` / `pytest` / `cargo` / project-specific invocation): prompt the user to run that command themselves via `!`-shell-escape in their prompt — the same pattern Step 4d uses for protected-branch pushes. Do NOT use `AskUserQuestion`; ask for the literal `!`-prefixed command. Step 0's permission guard cannot anticipate every project-specific verification command. (The `PermissionDenied` hook surfaces guidance for exactly three shapes — a push to `origin` of one of the two branch names the hook **hard-codes** (`main` or `master`, literally; it does not resolve the default branch), a `--delete` push of any branch, and `git commit` on a protected branch — and emits nothing for anything else, verification commands included, because their vocabulary varies too widely per consumer to enumerate. So this prose remains the load-bearing instruction here. **State the coverage as those three shapes, never as the steps that use them** — a step reference reads as a promise about everything the step runs, and Step 4d under `pr` policy runs `gh pr`, which the hook does not match.)

> **For new projects:** add a `## Pre-merge verification` section to your CLAUDE.md (template in WORKFLOW.md § 6.1) listing the exact commands this skill should run. That keeps verification deterministic across consumer projects with different stacks.

## Step 3c: Manual Smoke Gate (BeanRider ISSUE-0008)

Some features can't be verified by automated checks — UI flows that need a browser, commands with external side effects, LLM round-trips whose output a human must eyeball. The contract: a task in `tasks/index.yml` may carry `manual_smoke: true`, and a `sysop/runtime/pending-docs/*.md` body, or the body of a task an approved branch links, may contain a procedure heading (`manual smoke`, `operator action`, `before merge` and the rest of step 1's set, case-insensitive). Any signal halts this step until the human runs, confirms or waives the procedure, or finds it unrunnable as specified.

**Run step 1's detection first, on every cycle, and let it decide.** A `manual_smoke: true` task or a `smoke required` heading is a human saying *ask me*, and no diff-shape test can see one: the extension list cannot tell a docs commit from a task implemented in a `docker-compose.yml`, a feature-flag `.json`, a k8s manifest or a `.env.example`, all doc-only by that list. So — **no signal → proceed to Step 3b; any signal → run the gate, whatever the diff's extensions say.**

**Skip Step 3c only when the whole *run* is doc-only — not when Step 3's pre-merge pass was.** Those are different claims, and keying the smoke gate to the second would disable it on nearly every cycle: Step 3's list is main's local-only commits, which are the claim flips and the `review_tasks.md` save, so it doc-only-skips while the approved branches carry real code. **With detection first, that rule is residual rather than operative** — a run with no signal has nothing to skip, and a run with one is not entitled to — so do not compute per-branch diffs to evaluate it. It stays stated because the coupling it forbids is the regression this step nearly shipped, not because it decides anything. A smoke gate over a change nobody flagged is incoherent — but this is the gate whose miss is a human never being asked, so the doc-only test must never overrule an explicit ask.

**The cost, stated rather than discovered:** detection now runs on cycles that used to skip it, so step 1's detection runs on a docs-only close too. That is the trade — a fetch and reads, against a human never being asked — and it is why the detection's failure modes are loud: an unsubstituted `<approved branch>` exits 3 and an unreachable PyYAML exits 2, both stopping the close instead of reporting no signal. PyYAML is a declared hard dependency, so the second is a broken install surfacing, not a new requirement.

**Under `--prepare`, run step 1 as written, loading the signal arm as its stub below says, and ask nothing from step 2 on:** record each signal as a question (*`--prepare` and `--resume <run-id>`* (`steps/prepare-resume.md`), item 2), record nothing with the recorder, drive nothing, and go to the prepare's `finish` (item 6).

**1. Detect signals.** The gate reads pending-docs from **main's `sysop/runtime/pending-docs/` and each approved branch's worktree** — a `/claim-task` worktree authors its pending-doc there, and it is not copied to main until Step 3b (merge time). Reading the worktrees *in place* keeps the gate honest without collecting docs early: collecting before the merge would widen the window in which main's `sysop/runtime/pending-docs/` holds a doc for work that did not land, and a branch SKIP'd at Step 3b (worktree remove-refusal, ISSUE-0016) or a whole-run halt could then leave a stray doc that a later Step 4c consolidates for unmerged work, marking its task `done` with the code never merged (BeanRider ISSUE-0050). **The old form of this sentence claimed an invariant that no longer holds and never fully did** — it read *"everything in main's `sysop/runtime/pending-docs/` belongs to a just-merged branch"*, which its own next clause then contradicted by naming two ways a stray doc gets there. Step 4c step 1b now **enforces** what this sentence used to assert, by testing each doc's branch against the merge target rather than trusting its presence; so the directory may legitimately hold a held-back doc between runs, and nothing downstream may assume otherwise. List this run's approved branches (the same set Step 3b merges), then run the detection from the repo root. Its first line is either `NO_SMOKE_REQUIRED` (proceed to Step 3b) or `SMOKE_REQUIRED: N signal(s)`, with one `---SIGNAL---` block per signal after any info lines:

> **Three detection sources, because a phrase list was one.** The gate matched two exact phrases — `manual smoke` and `smoke required` — so a pending doc headed `OPERATOR ACTION REQUIRED BEFORE MERGE`, describing a hard irreversible pre-merge step, scored `NO_SMOKE_REQUIRED` and the close proceeded without ever prompting. Unlike every other gate in this skill the failure was silent *and* terminal: nothing downstream notices the operator was not asked, and the action is by construction the one that cannot be undone after merge. The heading list is now longer, but a longer allowlist over free prose is still an allowlist, so **two of the three sources do not depend on phrasing at all**:
>
> 1. **A matching heading** in a pending doc, or in the body of a task this close covers. Widened phrase set; `## User ops (do these first)` is deliberately excluded, because `user_action: true` is a **large, routine class** whose wholesale prompting would train the operator to waive. That reason is timing-independent and is the whole of it. An earlier form of this sentence also asserted a POST-merge timing that nothing in the tree supports, since retired — see `tasks/schema.md` § "User ops", which carries the correction and is the only place that quotes the retired wording. A step that must happen before *merge* is `manual_smoke:`, which sources 2 and 3 below detect regardless of heading.
> 2. **`manual_smoke: true` in a pending doc's own frontmatter** — signals whatever the doc's headings say.
> 3. **`manual_smoke: true` on the `tasks/index.yml` entry** — and it now signals **even when the body carries no matching heading, no readable `body:`, or no `body:` at all.** A declaration is the ask; a missing procedure makes the ask louder, not absent.
>
> **Task linkage also has two sources, because pending-doc frontmatter alone was not one.** A task whose ID no pending doc named was invisible to source 3 — so a task that declared `manual_smoke: true` *and* authored its procedure under the sanctioned heading was still scored `NO_SMOKE_REQUIRED`. The fully compliant author was the one the gate did not protect. Linkage is now `roadmap_ids:`/`task_ids:` from a pending doc (never one Step 4c 1c holds back) **or** a lock under `sysop/runtime/locks/` whose `branch:` is one of this run's approved branches — which is why the approved branches are passed to the detection as arguments. Locks are keyed by fact, not by a document that may be absent or malformed.

Write each of this run's approved branches as its own quoted argument: the same set Step 3b will merge (rejected and SKIP'd branches are excluded: they are not closing this run and must not trip the gate), or none at all for a main-only close. The script finds each branch's worktree itself (BeanRider ISSUE-0050), and an argument still holding a `<placeholder>` exits 3, since a gate that scanned nothing would print `NO_SMOKE_REQUIRED`. Run, from the repo root:

```bash
python3 sysop/scripts/smoke_detect.py --branches "<default branch>" "<approved branch>" "<approved branch>"
```

**If it exits non-zero, stop the close and show its stderr**, which names the input it could not use (a `tasks/index.yml` or pending doc that does not parse, or an index of the wrong shape, exits 1; `git worktree list` failing exits 2; an unsubstituted `<default branch>` or `<approved branch>`, or a name that is not a local branch, exits 3): an empty stdout is not zero signals. If the output's first line is `NO_SMOKE_REQUIRED`, continue to Step 3b. Otherwise, parse the signal blocks and proceed to step 2. **The first line alone decides.** The lines between it and the first `---SIGNAL---` are never signals, so carry them to Step 8. `PREVIOUSLY ANSWERED:` is a section the human already answered, in a doc whose branch is not merging this run. `NOT IN THIS RUN:` is a `manual_smoke` task linked only by a doc Step 4c 1c is holding back. `ORIGIN INDEX:` says `origin/<default branch>`'s index was not read, or was read from a ref the fetch could not refresh. `BRANCH INDEX:` and `BODY NOT READ:` name an approved branch's index, or a linked task's body, that exists at the tip and could not be read there. `MERGE NOT READ:` names a linked task whose merge could not be read, and why; its body was read at the tip, so a heading the default branch added to it is not seen. It also names a default branch that does not resolve, where `HEAD` stood in as the merge target.

**Which task bodies are read, and which indexes.** Every task an approved branch links, by an approved doc's `roadmap_ids:` or a lock on an approved branch, has its body scanned for a procedure heading, with or without `manual_smoke:`. Only a declared task also signals a missing heading, body or `body:`. A task is declared when `manual_smoke: true` is set in the local `tasks/index.yml`, in `origin/<default branch>`'s, which the block fetches first, or in the approved branch's own index at its tip. A task is held only when its `user_action` is set locally and, where origin carries the task, on origin too. A doc is also held when its own frontmatter carries `hold:`. With a local index and an `origin` remote, no `ORIGIN INDEX:` line means origin's index was read. The fetch runs under `--dry-run` too, and moves only `refs/remotes/origin/<default branch>`.

**On `SMOKE_REQUIRED`, what the signal blocks say and steps 2 to 4, which ask, halt on and record each signal, are an arm.** Run, from the main checkout's top level, with the close id `begin` printed:

```bash
python3 sysop/scripts/close_arms.py exited "<close-id>" 3c-signals 1
```

It prints `ARM: 3c-signals`. **Exit 2**: stop and show its stderr.

**Load this arm when the `exited` command above printed `ARM: 3c-signals`**, under `--prepare` and `--dry-run` too: a prepare records step 2's options, and a dry run asks them. Read `${CLAUDE_SKILL_DIR}/steps/3c-signals.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=3c-signals -->

> **For new projects:** declare `manual_smoke: true` on `tasks/index.yml` entries whose verification needs a human (browser flow, side-effect-bearing command, LLM round-trip). Author the procedure under a `## Manual smoke required` heading in the task body file. The validator warns (not blocks) when the field is set but the heading is missing — see `tasks/schema.md § Manual smoke`. A procedure that can only run after the merge goes under `## After merge` instead, which Step 8 reports and nothing gates (`tasks/schema.md § After merge`).

## Step 3b: Prepare Worktrees for Merge

Feature branches created by `/claim-task` or `batch_work.sh` usually live in worktrees. Branches checked out in a worktree cannot be checked out from main, so worktrees for **approved** branches must be removed before merging.

> **A worktree is one workspace shape, not the only one — and the collect is not conditional on it.** `claim_task.sh --clone` produces a **full clone**, which `git worktree list` never lists. Previously the pending-doc collect below was nested under *"if a worktree exists"*, so a clone workspace fell through to *"the branch is already free for checkout"*: its pending-doc was never collected, Step 4c never consolidated it, its `roadmap_ids` never flipped to `done`, and its body was never archived. Nothing was lost — the clone directory persists — and nothing said so, which is why it is a silent-incompletion defect rather than a data-loss one. **The remove is worktree-only; the collect is not.** Removal is what needs a worktree. Collecting a doc needs a *directory*.

**Under `--prepare`, do not start this step:** the prepare ends at Step 3c (*`--prepare` and `--resume <run-id>`* (`steps/prepare-resume.md`), item 6).

**Under `--dry-run`, run step 0 only, which writes nothing:** report each approved branch's workspace and shape, and that steps 0b–2 did not run. Then go to Step 8's report; Steps 4 through 7 do not run.

For each approved feature branch:

**0. Locate the branch's workspace**, first hit wins, and record which shape it is. Run this from the repo root with `BRANCH` set to the branch this iteration is processing:

```bash
# Run from the repo root, as written: one quoted argument, the branch this iteration is
# processing. The script reads `git worktree list` and the prefix itself.
# See REFERENCE.md, section Step 3b — provenance.
python3 sysop/scripts/workspace_locate.py "<branch name>"
```

**If `WS` is empty**, there is nothing to collect and nothing to remove — the branch is already free for checkout. Say which of the two reasons applies (the `main-checkout` shape — a fixed enum value Step 0 prints verbatim, never a branch name — or no workspace found at all); they are not the same fact and a later step that has to reconstruct what happened cannot tell them apart from silence. **Then apply the collect's exit-8 test by hand, since the collect does not run here:** if a lock in `sysop/runtime/locks/` other than a review batch's `BATCH-<N>.lock` has this branch as its first column-0 `branch:` value, and no doc in main's `sysop/runtime/pending-docs/` carries (parsed as YAML, so quoted or bare) `branch: <this branch>` in its frontmatter, SKIP the branch exactly as exit 8's row says. If a doc there does claim the branch, list each claimed id that no such doc names in `roadmap_ids` (or `task_ids`) under Step 8's `Open claims:`. **When step 0 printed `shape=<none>`, also apply the collect's exit-6 test by hand:** for each such doc whose `branch_tip:` is a string of 7 to 64 hex digits, run `git rev-list --count "<branch_tip>..refs/heads/<branch>"`. A count above `0` SKIPs the branch exactly as exit 6's row says. Any other `branch_tip:` value, or a count that fails, is staleness unknown: print `PENDING-DOC STALENESS UNKNOWN: <doc> (<why>)` and go on, as the collect does. **Those two rows are in step 1's arm:** for either SKIP, run step 1's `exited` command with `8` or `6` written out as the code, and load the arm it prints; under `--dry-run`, report the SKIP and run neither.

**0b. Only when `SHAPE=worktree`: preserve the ignored files only this worktree holds.** Run from the repo root, with `<sanitized branch>` the branch name with every `/` replaced by `-`:
```bash
python3 sysop/scripts/ignored_refs.py "<worktree-path>" --preserve "sysop/runtime/preserved/<sanitized branch>"
```
**Exit 0**: go on to step 1. **Any other exit**: SKIP this branch (worktree, lock and branch intact) and do not run step 1, so nothing is collected and there is nothing to roll back. Print each `PRESERVED:` line and the `PRESERVE:` summary, or the error, under Step 8's `Ignored references:`.

**1. Collect this branch's pending-docs from the workspace step 0 resolved, whatever its shape** — worktree, clone, or discovered. Step 0 *prints* `workspace=… shape=…`; it does not export them, and the command below takes the path as a quoted positional argument. **Substitute the printed values by hand** — `WS` and `SHAPE` are names for the two things step 0 told you, not shell variables that survive into this block. (Every fenced block in this skill is independent: nothing set in one reaches the next.)
 - a. **Collect pending-docs**: bring each `sysop/runtime/pending-docs/*.md` from the worktree into main's `sysop/runtime/pending-docs/` (these are untracked files that would be lost when the worktree is removed). **The copy is provenance-checked, because the destination is keyed by basename and a basename is not unique to a branch.**

      ```bash
      # Run from the repo root. TWO quoted positional args: the worktree path and **the
      # branch this iteration is processing** — the same name step 1 above matched from
      # `git worktree list` and item (b) passes to `git worktree remove`.
      python3 sysop/scripts/pending_doc_collect.py collect "<worktree-path>" "<branch name>"
      ```

      **Why provenance and not a content comparison.** The two copies differing is *not* the signal — the overwhelmingly common collision is the **same branch collected twice** (a prior run copied the doc, then died before `git worktree remove`), where main's copy is stale by construction and the worktree must win. Step 3c states exactly that rule for its own dedup, and a byte-comparison would fire loudly on the case where overwriting is correct while staying silent on the case that matters. What matters is whether the two docs came from the **same branch**, and each doc already carries that claim in its own `branch:` field.

      **Print to stdout, and note there is no `2>/dev/null` any more.** The old form masked the dest-missing error, which is what made the failure silent; the collision lines above are the Step 8 `Pending-doc collisions:` row's only source. **The same is true of the `PENDING-DOC STALE:` and `PENDING-DOC STALENESS UNKNOWN:` lines** — they feed Step 8's `Stale pending-docs:` and `Staleness not measured:` rows, and a gate whose SKIP has no row in the run's report is a SKIP nobody sees. An earlier cut of this phase shipped both lines with no sink at all.

      **Exit 0: go on to (b).** A collect that did not run (a denied command has no exit code) is not exit 0: do not proceed to (b); relay the command as the permission guard's *Deliberate non-entries* says. **Any other exit:** do not proceed to (b). Read the exit code, never a printed line. Run, from the main checkout's top level, with the close id `begin` printed and that exit code written out:

      ```bash
      python3 sysop/scripts/close_arms.py exited "<close-id>" 3b-collect-exit <code>
      ```

      It prints `ARM: 3b-collect-exit` for any code but 0. **Exit 2**: stop and show its stderr.

      **Load this arm when the `exited` command above printed `ARM: 3b-collect-exit`**, once per close: a later branch's exit follows the arm already loaded. Read `${CLAUDE_SKILL_DIR}/steps/3b-collect-exit.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=3b-collect-exit -->
 - b. **ONLY WHEN `SHAPE=worktree`** — strip the non-work symlinks Step 1a downgraded, then **remove the worktree**, **never `--force`**.

      > **This gate is stated here, before the command, and item 2 below only elaborates it.** The first cut of this step put the gate 80 lines *after* this sub-item, and an operator following the steps in written order on a clone workspace did all of this: collected the doc (a), ran `git worktree remove` on a directory that is not a worktree, got `fatal: '<path>' is not a working tree` (exit 128), read *this sub-item's own* refusal prose — *"stop, surface the error, then roll back the pending-docs this branch copied in step (a)"* — rolled the doc back out of main, and downgraded the branch to SKIP. **Net result: the doc collected and then deleted, and the branch not merged** — the pre-fix end state plus a lost merge, produced by the very step that was supposed to fix it. A rule an operator reaches after the command it governs is not a gate.
      >
      > **For any other `SHAPE`, skip straight to item 2.** The removal is the only part of this step that needs a worktree, and `git worktree remove`'s failure on a clone carries **no** claim about untracked files — so it is never the ISSUE-0016 remove-refusal, and must never trigger the rollback below.

      Step 1a can now classify a worktree `clean-ahead` while a downgraded tooling symlink (an untracked `.venv`-into-the-main-venv, BeanRider ISSUE-0043) is still physically present, and that lone symlink is enough to make an *unforced* `git worktree remove` refuse (`contains modified or untracked files`). So before removing, delete just those symlinks, with Step 1a's own downgrade rule. Run from the repo root:
      ```bash
      python3 sysop/scripts/close_state.py strip-links "<worktree-path>"
      ```
      It prints `REMOVED LINK: <path>` for each and `STRIP-LINKS: <n> removed`. **Exit 2**: stop and show its line. Then remove the worktree, unforced, as its own call:
      ```bash
      git worktree remove "<worktree-path>"
      ```

      **Exit 0: the worktree is removed; go on to item 2.** **Any other exit:** `git worktree remove` refused. Run, from the main checkout's top level, with the close id `begin` printed and that exit code written out:

      ```bash
      python3 sysop/scripts/close_arms.py exited "<close-id>" 3b-rollback <code>
      ```

      It prints `ARM: 3b-rollback` for any code but 0. **Exit 2**: stop and show its stderr.

      **Load this arm when the `exited` command above printed `ARM: 3b-rollback`**, once per close: a later branch's exit follows the arm already loaded. Read `${CLAUDE_SKILL_DIR}/steps/3b-rollback.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=3b-rollback -->

**2. Remove the workspace — only when `SHAPE=worktree`.** Item (b) above is the removal, and it is the one part of this step that a worktree is required for. For any other shape:

   **Step 0 emits exactly five shapes**, and every one of them is dispositioned here. (The first version of this list named `SHAPE=branch`, which step 0 can *never* emit — a `--branch` claim records the main checkout, which resolves to `main-checkout` — and omitted `recorded` and `unresolvable`, both of which it can. A disposition table that names a value the producer cannot emit, and misses two it can, is not a table.)

   - **`worktree`** — item (b) above removed it. Nothing further.
   - **`clone`**, or **`discovered`** resolving to a clone — nothing to remove. A clone is an independent repository: it holds no ref in this repo's `HEAD`-per-worktree set, so it never blocks `git checkout <branch>` from main, and `git worktree remove` on it fails. Leave the directory; the collect in item 1 is what this branch needed. Its checkout is now stale relative to the merge, which is expected and is the consumer's to clean up.
   - **`recorded`** — a lock named a workspace but no `mode:`. Treat it as `clone`: collect, do not remove. The missing `mode:` is a malformed lock, worth saying out loud in the run's report, not worth halting a close over.
   - **`main-checkout`** — nothing to remove and nothing to collect; the work was done in the main checkout and its pending-docs are already where Step 4c looks. This is what a `--branch` claim produces.
   - **`unresolvable`** — a recorded workspace whose path could not be resolved at all. Nothing to collect and nothing to remove; **say so in the report**, because it is the one shape that means a doc may exist and this run could not reach it.
   - **no workspace found** (`<none>`) — the branch is already free for checkout.

   **Do not run `git worktree remove` on a shape that is not a worktree**, and do not treat its failure as the ISSUE-0016 remove-refusal: that guard's whole meaning is "a worktree carries an uncommitted file," and a clone failing the command carries no such claim. Misreading it downgrades an otherwise clean branch to SKIP for a reason that does not exist.

For **SKIP'd** branches (any Step 2a SKIP verdict), do nothing here — the worktree stays.
For **rejected** branches, leave worktrees in place (cleaned up in Step 6).

## Step 4: Merge & Land on Main

### 4-pre. Determine Merge Policy & Target

How approved work reaches `main` depends on the project's **merge policy** — run this from the main checkout's top level, with the close id `begin` printed written out:

```bash
python3 sysop/scripts/close_arms.py policy "<close-id>"
```

It reads `<project>/CLAUDE.md § Merge policy` (the same "consumer declares its shape" pattern as Step 3's `§ Pre-merge verification`), records the policy for Step 4d, and prints `POLICY:` and `SOURCE:`, then `ARM: 4-pre-pr` under `pr` and `ARM: none` under `direct`. Use the `POLICY:` it prints. **Exit 2**: stop and show its stderr; a word other than the two below, or a heading other than `## Merge policy`, is one. Two values; **default `direct`** when the section is absent:

- **`direct`** (default) — feature merges, batch close, and doc consolidation land on `main` locally, then `git push origin <default branch>`. Correct for any project whose `main` accepts a direct push (no required status check, no `enforce_admins`). This is the historical flow; a consumer who never configured a merge policy keeps it with zero change.
- **`pr`** — `main` is never written directly; it is written only through a squash PR. Usually that means assembling everything on a throwaway **integration branch** cut from local `<default branch>` and merged onto the current `origin/<default branch>`, pushing it, and merging it into `main` through a PR — but when a single approved branch already *has* an open PR against `main`, the close lands on that branch instead (see the reuse probe below). Required when `main` is push-protected (a required CI check and/or `enforce_admins`) — a direct push would be rejected. GitHub becomes the sole serialized writer of `main`, which also removes the race against a concurrent auto-merge (e.g. Dependabot) landing on `main` mid-close.

Determine the **merge target** for the rest of Step 4 from the policy, and hold it as a value you write out at each later use — not as a shell variable. Every later reader is in a different fenced block, and nothing survives across one (`WORKFLOW.md` § 8.2a *Persistence boundary*); Step 4a's two merge commands are the readers that matter, and an empty operand there is a `fatal:` at best.

**`direct`:** the merge target is `main`.
```bash
git checkout <default branch>
```

**`pr`:** the two shapes, the PR-reuse probe and the integration branch, are an arm. **Load this arm when the `policy` command above printed `ARM: 4-pre-pr`.** Read `${CLAUDE_SKILL_DIR}/steps/4-pre-pr.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=4-pre-pr -->

> **HARD RULE — branch guard.** Steps 4a–4c run in the shared **primary** worktree, which has a single `HEAD`; a concurrent local actor can move it off the branch you expect mid-flow, landing commits on the wrong branch. Apply `_shared/main-push-guard.md` **Rule A** before **every** commit in Step 4. The assert's expected value must come from somewhere **other than `HEAD`** — comparing HEAD against a HEAD-derived value is a tautology that passes even after a hijack. The check is
> `python3 sysop/scripts/git_check.py head-is "<merge target>" && <the commit>`, with the merge target Step 4-pre recorded written out: `<default branch>` under `direct`, `merge/review-close-<close-id>` under the integration-branch shape, and under the PR-reuse shape the literal branch name Step 2a approved. Never re-derive it from `HEAD`.
>
> Chain the commit after the check with `&&`, in one call, as written at each commit below. On a non-zero exit, STOP and reconcile via `git reflog` (cherry-pick your stranded commits onto the expected branch) — never commit blind. Per **Rule C**, **never** force-push `main`, the integration branch, or a reused PR branch.

> **Value persistence — every cross-block value in Step 4 is a written-out literal, and none is a variable.** Nothing survives from one fenced block to the next, *including two blocks under the same heading* (`WORKFLOW.md` § 8.2a *Persistence boundary*). This note previously said the values were "referenced in Steps 4a–4d" and told you to "re-export at the top of each later step". **A later build replaced both halves — the first because it was wrong for the one variable that mattered, the second because it was the wrong granularity for all three.** The scope claim held for `$MERGE_TARGET` (read in Step 4a) and `$INTEGRATION_BRANCH` (read in Step 4d); it was false for `$APPROVED_BRANCH`, which was referenced in Steps 4a–4d exactly zero times — every use was here in Step 4-pre, in the two blocks *after* the one that assigned it — so a re-export-per-step remedy prescribed nothing for the only sites that needed it, and a sweep then cited this note as its warrant for excluding all six. They had been expanding empty on every run. So: **the merge target, the approved branch name, the integration branch name, the PR number, and the pre-plan/pre-exec HEADs are all literals, written out and quoted at every use site.** An unsubstituted `"<PR>"` fails loudly; an unquoted `<PR>` is a bash redirection, and an *empty* `gh` operand is the silent-wrong-merge case below. Where a value has a cheap re-derivation at the point of use, prefer it — a bare `gh pr list` probe at Step 4d, `git branch --list 'merge/review-close-*'` at Step 6.
>
> **Why the PR number in particular is never a variable.** `git` rejects an empty ref operand (`git branch -D ""` → `error: branch '' not found`), but `gh` **falls back to resolving the current branch's PR**: `gh pr view ""` and `gh pr merge ""` do not error, they silently act on whatever branch is checked out. Held in a variable across shell calls, an unre-exported one meant `gh pr merge ""` merged the current branch's PR, `--delete-branch` then moved HEAD to `main`, and the verdict probe `gh pr view ""` found no PR for `main` and reported a non-`MERGED` state — a stuck-PR report, and Step 6 skipped, **after a merge that landed**. Writing the number out *removes* that failure mode rather than guarding it: there is no variable left to go empty. Step 4d still re-derives the number from a bare `gh pr list` probe and stops if it prints nothing — keep both the probe and the stop.
>
> Through Steps 4a–4c, HEAD is the merge target, so a forgotten merge-target name is always recoverable with a bare `git branch --show-current` — read it off stdout and write it out, rather than capturing it, and use it only as the `git merge` / `git checkout` / `git push` operand. Do **not** feed that HEAD-recovered value into the Rule A branch-assert (the HARD RULE above): asserting HEAD against a value just read from HEAD always passes, even after a hijack. For the assert, use the merge target Step 4-pre recorded, as the HARD RULE says. The integration branch is named from the close id, so Step 6's `git branch -D` writes the same name; if it is lost, `git branch --list 'merge/review-close-*'` reads it back.

### 4a. Merge Approved Feature Branches

**Skip this step entirely under the Step 4-pre PR-reuse shape** — the merge target *is* the one approved branch, so there is nothing to merge into it. (Rebasing that branch onto itself is a no-op that reports "up to date", but running it invites the reader to treat a self-rebase as meaningful; go straight to **`4a-fix`**, then **`4a-post`** — **not** to Step 4b. `4a-post` is not skipped with this step: under the reuse shape it is the *only* thing that verifies the tree the PR will squash, and skipping past it would land an approved branch on a protected `main` with nothing having run against it.)

For each approved feature branch (oldest first), merge it into the **merge target** Step 4-pre determined — `main` under `direct` policy, the integration branch or the reused PR branch under `pr`. Write it out at both use sites below: Step 4-pre is a different fenced block, so `"$MERGE_TARGET"` is empty here, and `git rebase ""` is a `fatal:` that aborts the close mid-merge.
1. **Is this branch published?** Answer it *here*, before anything moves — the rebase in item 2 is what the answer changes, and a rule an operator reaches after the command it governs is not a gate.
   ```bash
   python3 sysop/scripts/git_check.py published "<branch>"
   ```
   **Exit 0** prints the remote branch's SHA: published. **Exit 1** prints `(local-only)`. **Exit 3**: the name is still a placeholder; write it out and re-run, never read it as local-only, which takes the in-place rebase that damages a published branch. **Exit 2**: stop and show its line.
   A stale remote-tracking ref (pushed once, since deleted on the remote) also prints a SHA and so takes the published arm. That is the safe direction: the published arm's only cost is a merge commit in place of a linear replay.

   **Then ask whether a recorded PR head contains any of its commits**, under either policy (Step 4d records each `pr` close's PR head). Write the branch and the merge target out:
   ```bash
   python3 sysop/scripts/pr_head_check.py "<branch>" "<merge target>"
   ```
   - **A branch Step 2a approved as landed in `<ref>`** (step 0b) — its tip is already in `<ref>`, and item 1 prints `RECORDED HEAD: none` for it. Merge it under neither arm of item 2. Record it `merged — already in <ref>` for Steps 4c, 6 and 8.
   - **`RECORDED HEAD: none`** — take item 2's arm as written.
   - **`RECORDED HEAD: <ref>` and `REPLAY` above 0** — item 2 uses the ref. Carry the `SKIP` lines to Step 8's `Squash provenance:` line.
   - **`RECORDED HEAD: <ref>` and `REPLAY 0 commit(s)`**, on a branch Step 2a approved as **landed by PR #<N>** — every commit on it is already in that PR's squash. Merge it under neither arm of item 2; record it `merged — PR #<N>` for Steps 4c, 6 and 8.
   - **`REPLAY 0 commit(s)` on a branch Step 2a reviewed** (step 0b printed `NOT LANDED`) — its local ref holds nothing new, and step 0b found a reason not to call it landed. Merge it under neither arm and record it **4a-SKIP**, with step 0b's reason, per *When a branch really is skipped* below.
   - **`RECORDED HEAD: not usable`** — the head holding the most of the branch's commits lacks commits the branch carries and the target already has (the branch merged `<default branch>`, or a branch cut after that squash). Take item 2's arm as written, and put the line on Step 8.
   - **Exit 3** — a placeholder or a `git` failure. Nothing has moved; fix it and re-run.
   - **Any `CLOSED TASK EDITED:` line**, on a branch item 2 will merge — the merge target closed or removed a task body the branch edited. **Under `--headless`, STOP.** Otherwise show the person each `show:` diff. On a `moved it to` line, ask: merge it, and list it on Step 8's `Closed-task edits:`; or 4a-SKIP the branch. On a `deleted it` line, 4a-SKIP it. A skipped branch's line returns at every close until a person merges it or reverts the edit on the branch.
   See `REFERENCE.md` § *Squash provenance: why each `pr` close records its PR head*.

2. **Merge — rebase-then-ff when the branch is local-only, `--no-ff` when it is published.** **If either path below conflicts, go to item 4 before running anything else** — item 4 routes the conflict and nothing between here and there knows one happened. Stated at the command rather than only at item 4: in written order an operator meets the merge first, which is the shape an earlier round caught one step over, where the rule sat 81 lines past the command it governed.
   - **Local-only** (the common case: `/claim-task` branches are usually never pushed under `pr` policy) — rebase, then fast-forward, exactly as before:
     `git checkout <branch> && git rebase "<merge target>"`, then
     `git checkout "<merge target>" && git merge --ff-only refs/heads/<branch>`

     **When item 1 printed `RECORDED HEAD: <ref>`, rebase with `--onto` instead**, which replays only the commits that head does not contain:
     `git rebase --onto "<merge target>" "<ref>" <branch>`, then the same `git checkout "<merge target>" && git merge --ff-only refs/heads/<branch>`.
     A `status:` conflict that still appears is two actors: STOP, per item 4.

   - **Published** (item 1's `git_check.py published` exited 0) — **do not rebase it**, in place or through a throwaway ref. Record the arm, from the main checkout's top level, with the close id `begin` printed written out:

     ```bash
     python3 sysop/scripts/close_arms.py exited "<close-id>" 4a-published 1
     ```

     It prints `ARM: 4a-published`. **Exit 2**: stop and show its stderr.

     **Load this arm when the `exited` command above printed `ARM: 4a-published`**, once per close: a later published branch follows the arm already loaded. Read `${CLAUDE_SKILL_DIR}/steps/4a-published.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`. It holds the `--no-ff` merge, its trailers, the recorded-head conflict test and item 3.

<!-- sysop:arm=4a-published -->

3. **A published branch's own PR** is the published arm's item 3, in `steps/4a-published.md`.
4. If the merge conflicts, **route by which file conflicted** — do not abort reflexively. First list them, from the top level of the checkout where the merge stopped, with the close id `begin` printed written out, and again at every later stop: a rebase stops once per conflicting commit, and a later stop can be a shared file:
   ```bash
   python3 sysop/scripts/close_arms.py conflicts "<close-id>"
   ```
   It prints a `CONFLICTED:` line for each path git left unmerged (`CONFLICTED: none` when there is none), then `ARM: 4a-append` when a Sysop-written shared append file is among them and `ARM: none` when none is. `CONFLICTED: none` while a merge or rebase has stopped means git's list was not read where the merge is: stop and report it. **Exit 2**: stop and show its stderr.

   A conflict in one of the **Sysop-written shared append files** below is the expected multi-branch shape, not a reason to skip: resolve it per the next section — and for `tasks/index.yml`, its `validate_tasks.py` gate must pass before you continue, with the command the gate names for your arm. Abort-and-skip (`git rebase --abort`, report the conflict, downgrade the branch to **4a-SKIP** per *When a branch really is skipped* below) is for conflicts you cannot resolve confidently — genuine code overlap you are not equipped to adjudicate, or a shared-file resolution the validator rejects. **The two arms abort differently, and the published one is the gentler.** Local-only: `git rebase --abort` returns the branch to its pre-rebase tip. Published: there is no rebase to abort — `git merge --abort` restores the *merge target*, and `<branch>` was never touched at any point, so nothing about it needs undoing. Either way the branch and its lock stay intact for the next cycle.

#### Sysop-written shared append files — the conflicts this skill causes itself

**Load this arm when the `conflicts` command above printed `ARM: 4a-append`.** Read `${CLAUDE_SKILL_DIR}/steps/4a-append.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=4a-append -->

#### When a branch really is skipped at 4a

A branch you abort-and-skip here is **4a-SKIP**, and it is a *different* verdict from Step 2a's `dirty` SKIP and from `rejected`. It is approved work that did not merge, and three later steps would otherwise treat it as merged. Record the branch name in that state and carry it to **Step 8's report**; Steps 4c and 6 each key on it explicitly. Its worktree was already removed by Step 3b and its pending-doc already copied to main's `sysop/runtime/pending-docs/` — neither is rolled back here, because Step 4c's merged-branch filter is what keeps that doc out of consolidation. Leave the branch and its lock intact so the next cycle can re-run it.

### 4a-fix. Fix the Close's Notes

**Runs after the merges and before `4a-post`, on the merge target** — under the PR-reuse shape, the checked-out approved branch. Its input is the `NOTES:` lines Step 2b step 4 collected. With none, record `Close notes: none` for Step 8 and go to `4a-post`. **Apply the branch-guard HARD RULE's Rule A assert before each commit below**, as for every commit in Step 4.
See `REFERENCE.md` § *Step 4a-fix — provenance*.

Under `--dry-run` this step does not run, and Step 8 lists the notes collected.

Count the notes Step 2b step 4 collected, one per `- ` bullet under a `NOTES:` block (`NOTES: none` is 0), those on a target that did not merge included, and run, from the main checkout's top level, with the close id `begin` printed and the count written out:

```bash
python3 sysop/scripts/close_arms.py notes "<close-id>" <count>
```

It prints `ARM: 4a-fix` when the count is above 0, and `ARM: none` at 0, which is the "none" above. **Exit 2**: stop and show its stderr.

**Load this arm when the `notes` command above printed `ARM: 4a-fix`.** Read `${CLAUDE_SKILL_DIR}/steps/4a-fix.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=4a-fix -->

6. **File the notes routed to a task at the start of Step 4d, in one further commit.** Follow `/add-task` Steps 2, 3 and 5.1–5.3: extend a matching open task before opening a new one, `status: open`, and `surfaced_by:` the task ids the note's branch claimed (`[]` for a review-batch branch or the unpushed-main group).

   ```bash
   python3 sysop/scripts/validate_tasks.py
   python3 sysop/scripts/git_check.py head-is "<merge target>" && git add -- tasks/index.yml <each other file those steps wrote> && git commit -m "docs: review-close file close notes — <N> task(s)"
   ```

   Never commit on a red validator: fix the data and re-run. The close commits what `/add-task` leaves uncommitted. Without `tasks/index.yml`, put the notes on Step 8's `Close notes:` line for the human to file.

7. **Record for Step 8** the counts, `<fix-sha>`, the verdict and the filed ids.

### 4a-post. Verify the Merged Tree

**This is the gate whose green means something.** Step 3 ran the same resolved list against `main`; this runs it against the tree that is about to be pushed. Each approved branch was already verified *in its own worktree, at its own tip* — `/claim-task` Step 7e (its executor prompt's Sequence, item 5) and `/auto-build`'s execution-agent sequence (Step 7's prompt template, item 4b) both run the consumer's `## Pre-merge verification` gates there, which is why each of those says `/review-close` runs project-side verification "at merge time." What has never been verified anywhere until this step is the **assembled** result: the branches merged onto the live base and onto each other.

**Placed here on purpose — after the merges, before `close_batch.sh` and before doc consolidation.** A stop at this point consumes nothing. Step 4c deletes each pending-doc **it consolidated** — by name, from the set it routed, never by glob (its cleanup step says so explicitly, and a doc it held back or quarantined survives) — after routing that content into the shared docs, and those files are **untracked** — so the routed content survives only in 4c's commit. **Under `pr` that commit is on the merge target, which a failed close abandons** (the integration branch is re-cut next run), leaving the content recoverable from a discarded branch or not at all. Under `direct` the commit stays on local `main` and the recovery below keeps it, so the window is a `pr`-shape window — which is every protected-`main` consumer, and the shape this repo runs. Verifying later would verify a slightly larger tree; it would also put that window under a failing gate.

1. **Re-resolve the command list** exactly as Step 3 did — the same numbered resolution order, first source wins. Re-read it rather than carrying Step 3's result forward as a remembered value: it costs one file read, and it removes the only way this step can silently run something other than what the consumer declared.

2. **Recompute the changed-file list on *this* tree** — the same command Step 3 ran, unchanged:

   ```bash
   git rev-parse --verify origin/<default branch> >/dev/null 2>&1 \
     && git diff --name-only origin/<default branch>...HEAD \
     || echo "NO_ORIGIN_MAIN"
   ```

   `HEAD` is the merge target now, so this is the assembled diff: every approved branch's contribution, plus — under `pr` policy's integration-branch shape — the local-only `main` commits the integration branch carries by being cut from local `<default branch>`. **Under `direct` it can be a superset**, and deliberately so: Step 4-pre is a bare `git checkout <default branch>` with no fetch, so `origin/<default branch>` may be stale and the range then also covers whatever landed upstream since your last fetch. That errs toward verifying more, which is the safe direction; do not "fix" it with a fetch here, because refreshing the base mid-close is Rule B's job at Step 4d and doing it early would silently change the tree you are about to gate. It is also what makes the consumer's `### Ratchet` snippets correct for the first time — each one filters `git diff --name-only origin/<default branch>...HEAD` on its own, and only on this tree does that command name the work being shipped. `NO_ORIGIN_MAIN` here means the same thing it means at Step 3: gate nothing, skip nothing, run the full list.

   **An empty list here is not automatically a pass and not automatically a contradiction — the discriminator is how many branches are still approved after Step 3b, so read that count first.** Do not count a branch Step 4a item 1 recorded `merged — PR #<N>` or `merged — already in <ref>`: it merged nothing this run. Unlike at Step 3, an empty list at this point *can* mean something did not land; whether it does depends on whether anything was owed. **Take the count after Step 3b, not after Step 2a** — Step 2d can demote an approved branch to rejected and Step 3b can downgrade one to SKIP, which is the same stage Step 4-pre condition 1 insists on and for the same reason. A branch Step 4a aborted-and-skipped is **still approved**, and still stops.

   - **One or more still approved after Step 3b**, including the Step 4-pre PR-reuse shape where the merge target *is* the one approved branch: **stop.** An empty list says the merge target holds nothing `origin/<default branch>` does not already have, while this close approved work that should be in it. Something did not land: a rebase left the branch a no-op, a `--ff-only` merge was skipped after a conflict, or `HEAD` is not the merge target you think it is. Report it and reconcile before Step 4b — do not let a gate that executed nothing report green over a close that merged nothing.
   - **Zero still approved after Step 3b** — the docs-consolidation cycle: **expected, and not a contradiction.** Step 4a's loop ran over an empty set, so nothing was owed. Continue to item 3, which still runs the consumer's declared `### Always` list. Record `changed-file list empty — zero approved branches` on Step 8's `Verification:` line beside whatever item 3 reports; **that note is not `ran nothing`**, which is reserved for a run that executed zero commands.

3. **Run the list**, applying item 3's surface gate to *this* list. **Item 4's doc-only skip does not apply here.** It belongs to Step 3, which is allowed it because its green is not a verdict; this gate's green *is* the verdict, and "no file in the assembled diff carries a code extension" is not evidence that the consumer's declared list is unaffected — the same extension test calls build and lint configuration, dependency manifests, CI workflows and rule files documentation, and a full test suite can assert on prose. A consumer who wrote `### Always` wrote *always*, and `docs/getting-started.md` tells them a suite listed there runs "on the merged tree on every merge". So a doc-only assembled diff **still runs a consumer-declared list** (items 1–2). What it does not run is a command item 3's surface gate left unarmed — that gate still decides the auto-detected ones — or a `### Ratchet` snippet whose own filter comes back empty.

   **If the surface gate leaves nothing to run while the list still contains a code file, that is "ran nothing", not green** — it is item 5's case arriving late (no applicable command for a code-touching diff), so stop and ask the user what to run, naming the surfaces gated out and the unclaimed files. A gate that executed zero commands must never report the same as one that executed them and passed; that equivalence is the defect this whole step exists to remove, and surface-gating is the one way this step can re-manufacture it.

   **Count what you actually executed and report the number**, on Step 8's `Verification:` line (`ran on <merge target>: 3 commands`). A bare "ran" cannot be told apart from a run that resolved a list and executed none of it, which is the equivalence this whole step exists to remove — so the count is the evidence, not a decoration.

   **Zero commands on a doc-only assembled diff is a different case, and it reports rather than stops.** A consumer with no declared list and no armed surface has nothing for this gate to run and nothing to be asked about — halting every docs cycle after the merges would be a worse defect than the one above. Report it as `ran nothing` with the reason on Step 8's `Verification:` line; **never as `ran on <merge target>`**, which is what the line's earlier vocabulary forced, having offered only "ran" or "not reached". **Under `NO_ORIGIN_MAIN` neither of those two predicates is evaluable** — there is no changed-file list to hold a code file or not — so the full resolved list runs ungated per step 2, and if that list is empty because nothing was declared and no surface was detected, report `ran nothing: no origin/<default branch>, no declared list` and continue. Do not read an uncomputable scope as either a stop or a green. Everything Step 3 says about invocation still holds and is not restated: venv-aware re-invocation on `exit 127` / `ModuleNotFoundError`, the `!`-shell-escape route for a silently-denied command (never `AskUserQuestion`), and the read-only rule — no `pip install`, no state mutation, in a verification command.

   > **A command that could not be measured is neither a pass nor a failure — say so, and stop.** Every disposition above assumes the command *ran and answered*: it exited, and the exit code means something. A command killed by the Bash tool's timeout answers nothing. It gets no exit code you can read as a verdict — the harness reports the kill, not the program's own result — so the work it was checking is **unverified**, not verified-clean and not verified-broken. Report it on Step 8's `Verification:` line as `TIMEOUT: <command>` — deliberately the same token `/auto-fix` and `/auto-judge` put in their envelopes for the same event, so the three surfaces name one state one way — and then stop per item 4, because an assembled tree with an unmeasured gate is exactly what this step exists to refuse. **Do not silently re-run with a longer timeout and report the second result as the first**; raise the timeout, re-run, and report *that* it took two attempts. **Do not classify it as a failure either:** `failed` is a claim about the code, this is a claim about the measurement, and merging on one while reporting the other is how a green gate stops meaning anything. (The one shipped precedent agrees: `run_checks`'s accounting module classes its own subprocess timeout as `failed` and says why — *"work was lost, not declined"* — but it owns that subprocess and can tell a kill from an exit. This step does not.)

3a. **Run the Sysop pre-scan on the merged tree** — the promoted checks, at the one gate that can refuse a merge:

   ```bash
   bash sysop/scripts/run_checks.sh --mode both --fail-on-blocking
   ```

   **This is a Sysop-owned gate and it is deliberately NOT a fourth entry in item 1's resolution chain.** That chain stops at the first source producing a list, so a project with a `## Pre-merge verification` section never reaches auto-detect — and a pre-scan offered as one more source would therefore be invisible to exactly the consumers who already authored that section — everyone who has been running Sysop — because `install.sh` never rewrites a consumer's `CLAUDE.md` at all: the `--update` sweep skips it explicitly as *"the consumer's, not Sysop's"*, and the installer only ever **appends** sections that are absent. (A stronger guarantee than the installer's managed-path preservation, which is scoped to `scripts/*` and `scripts/hooks/*` and does not reach this file — an earlier draft cited that, right about the conclusion and wrong about the mechanism.) It runs **in addition to** the consumer's list, after it.

   **What it closes.** `run_checks.sh` was invoked by `/codebase-review` Step 2b and `/security-audit` Step 2b and by nothing else, so the promoted checks — the `checks.yml` registry, the semgrep rules, the LSP and coverage stages this workflow exists to accumulate — ran only at **audit** time, which is after the branch that violated one has merged. The violation then surfaced on the next audit round as a new-vs-baseline finding, post-merge, at the gate `README.md` calls "the single human merge gate". The permission rules for this command have shipped in this skill's own allow-list and in `settings.json` the whole time; nothing bound them.

   **Four dispositions, and only one is a stop:**

   - **Exit 0** — **not automatically clean, and this is the disposition most likely to be reported wrong.** `--fail-on-blocking` keys on `failed` and on new blocking findings; it does **not** key on **`degraded`** — `run_checks/accounting.py`'s third status, *"ran, but over less than its declared inputs"*, which must not block by design. A run in which a `blocking: true` stage saw a fraction of its inputs exits **0** with zero findings, and a zero from a degraded stage is not a real zero. Read the accounting block before reporting: `pre-scan: clean` only when its header shows `0 failed` and no `degraded`, `unroutable` or `unaccounted` count, and no line carries `⚠ BLOCKING CHECK`. Otherwise report `pre-scan: clean, but not every check ran fully —` followed by the header's counts and each `⚠ BLOCKING CHECK`, `failed:`, `degraded:`, `unroutable:` and `unaccounted:` line verbatim, and continue. Any other `⚠` line (review rounds, stale baseline entries) is not a check's state: quote it beside the verdict. **Not hypothetical** — the one consumer that enforced these checks at its merge gate before this step existed wrote a wrapper *because* `run_checks.sh --mode both --fail-on-blocking` exited 0 over sixteen degraded semgrep checks.
   - **A non-zero exit, or no `sysop/scripts/run_checks.sh` to run** — never fabricate the scan or hand-roll a substitute. Record the arm, from the main checkout's top level, with the close id `begin` printed written out:

     ```bash
     python3 sysop/scripts/close_arms.py exited "<close-id>" 4a-post-prescan 1
     ```

     It prints `ARM: 4a-post-prescan`. **Exit 2**: stop and show its stderr.

     **Load this arm when the `exited` command above printed `ARM: 4a-post-prescan`**, once per close: a re-run of this step, such as Rule B's, follows the arm already loaded. Read `${CLAUDE_SKILL_DIR}/steps/4a-post-prescan.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`. It tells a new blocking finding or a failed blocking stage, which stop per item 4, from an environment that cannot run the scan and an absent script, which continue.

<!-- sysop:arm=4a-post-prescan -->

   **De-duplication — does any resolved command REACH the pre-scan, directly or through a project wrapper?** If one does, this step does not run it again: report `pre-scan: ran via the consumer's list`. **A resolved command only counts if it can actually refuse.** `run_checks.sh` **without** `--fail-on-blocking` exits 0 on any finding, so a consumer whose `### Always` lists the bare form has a scan that reports and never blocks — and `install.sh`'s own post-install footer prescribes exactly `bash sysop/scripts/run_checks.sh  # smoke-test the check registry`, so this is the form a consumer is most likely to have copied. Treat a flagless invocation as **not** de-duplicating: run this step's own gated scan anyway and report `pre-scan: consumer's list runs an ungated scan — ran the gate as well`. **Ask that question, not "does a command contain the string `run_checks.sh`".** A name match is the obvious rule and it is wrong on the live case: the one consumer that already enforced these checks at its merge gate lists `bash scripts/run_checks_gated.sh --mode both --fail-on-blocking`, a **project-owned wrapper** around `sysop/scripts/run_checks.sh` written to add the `degraded` handling the flag does not do — so a name match sees no pre-scan and runs a **second whole-tree scan on every close**, the exact double payment this rule exists to prevent. When a resolved command is a project script you cannot classify by name, read it; one `grep -l run_checks` over the resolved commands' script files answers it. **Flags never enter the decision:** a consumer who wrote `--mode quality` narrowed the scan on purpose, and re-running at `--mode both` would overrule a choice `WORKFLOW.md` § 6.1 invites them to make.

   **No doc-only skip here, and the filing that asked for one was wrong about the step it lands in.** The filing proposed gating this "like Step 3's surface list so a doc-only close does not pay for a whole-tree scan". Item 3 above already refuses that reasoning for this pass, and it refuses it *harder* for a pre-scan than for a test suite: the extension test classes `checks.yml`, semgrep rule files and CI workflows as **documentation**, and those are precisely this scan's own inputs — so the one diff shape the proposed gate would skip includes every change that alters what the checks *are*. The cost is real and it is a whole-tree scan on every close; it is paid here rather than gambled.

   **`NO_ORIGIN_MAIN` does not reach this step** — also contrary to the filing, which asked for that rule to be inherited. It governs a **range**, and this scan takes none: it reads the working tree and the baseline file. There is nothing here for an uncomputable diff scope to narrow, so there is nothing to fail open.

4. **On failure, stop — unless the failure is one this close inherited and is about to repair, or, under `pr`, a test failure the default branch reproduces and the human answers for. Test those first, and stop on anything you cannot establish.**

   **When a gate command failed or timed out** — a command in item 3's list still failing, or reported `TIMEOUT`, once item 3 has run it to its verdict (venv re-runs and the `!` route included), or the pre-scan under 3a's **Non-zero** arm — record the arm, from the main checkout's top level, with the close id `begin` printed written out:

   ```bash
   python3 sysop/scripts/close_arms.py exited "<close-id>" 4a-post-failure 1
   ```

   It prints `ARM: 4a-post-failure`. **Exit 2**: stop and show its stderr. A denied command the `!` route did not run records nothing and loads nothing: stop as below. 3a's could-not-run and absent-script arms record nothing either, and continue.

   **Load this arm when the `exited` command above printed `ARM: 4a-post-failure`**, once per close: a re-run of this step, the fix-commit test's or Rule B's, follows the arm already loaded. Read `${CLAUDE_SKILL_DIR}/steps/4a-post-failure.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full before the stop below. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`. It holds the fix-commit test, the inherited-failure arm and the pre-existing ask, each of which can continue the close to item 5.

<!-- sysop:arm=4a-post-failure -->

   **On every other failure, stop.** Nothing has been pushed, `close_batch.sh` has not run, and no pending-doc has been consumed. Report the failing command with its output. Recovery is per merge policy:
   - **`pr`** — the merges are on the merge target, unpushed. Fix the failure, then re-run `/review-close`: a `pr` run cuts a fresh integration branch every time, so the abandoned one costs a `git branch -D` and nothing else. Under the PR-reuse shape there is no branch to abandon — the extra commits simply stay local until a later run pushes them.
   - **`direct`** — the merges are on local `main`, unpushed. **Do not `git reset --hard`**: that discards the claim flips and the merges together, and neither is recoverable from `origin`. Leave `main` as it stands. Those commits are now exactly the *unpushed main commits* category Step 1 already enumerates, so once the failure is fixed the next `/review-close` picks them up — and that run's Step 3 verifies them for real, because by then they are on its own tree.

5. **Confirm the gate left the tree clean**, before Step 4b asserts it:

   ```bash
   git diff --quiet HEAD -- && echo "CLEAN" || echo "DIRTY — verification modified tracked files"
   ```

   A formatter, a regenerated lockfile or a rewritten snapshot can leave tracked files modified. Step 4b's landing check is `git diff --quiet && git diff --cached --quiet`, so those modifications would surface there as a *close-batch commit that did not land* — a true report of the wrong cause. On `DIRTY`, resolve it project-side; do **not** fold the modifications into the close's commits. (Untracked build output is not at risk and does not trip this — `git diff` does not see it.)

   > **`DIRTY` here has a second cause this message does not name: a Step 2b agent.** The convention agents run five steps earlier and are contained only by a prompt rule and, where the harness offers it, worktree isolation — both of which have been measured failing. If Step 2b's own delta assertion was run, this cannot be the cause and the message above is right; if it was skipped, check that first, because the project-side remedy for a formatter is the wrong action for a stray agent edit and will commit it.

**Under the Step 4-pre PR-reuse shape this step still runs**, even though Step 4a was skipped there. The merge target is the approved branch and it is checked out, so step 2's command returns that branch's own diff against `origin/<default branch>` — which is exactly the tree its PR will squash.

> **This is the gate `_shared/main-push-guard.md` Rule B re-runs, and Step 3 is not.** When Rule B's merge fires at Step 4d because `origin/<default branch>` advanced mid-run, the base underneath the merge target changed, so the verdict *this* step produced no longer describes the tree being pushed. Re-run this step. Re-running Step 3 would answer a question nobody asked: its tree is not the one that moved.

### 4b. Close Merged Batches

After all branches are merged and `4a-post` reported green, or continued under item 4's `INHERITED:` or `PRE-EXISTING:`, but **before** doc consolidation.

**Determine the batch set first — this step never said where `<N1> <N2> <N3>` come from.** The set is the review batches whose branches Step 4a actually merged this run, and **the source is `review_tasks.md`**, read through `python3 sysop/scripts/review_index.py --list` with `--merged`, which prints the intersection, tab-separated: each batch whose branch is one of its operands, with its status and its branch. Write every branch Step 4a merged as its own operand, and under the PR-reuse shape, which skips Step 4a, the one approved branch. With no branch merged, run it with no operand: it prints the measured empty.

```bash
python3 sysop/scripts/review_index.py --list --merged <branch> <branch>
```

An operand that is not a local branch, spelled exactly, exits **7** and names it, since a mistyped branch would drop its batch from the set: correct the operand and re-run. The verdict line's `<J>` is the number of branches you passed: check it against the branches Step 4a merged before taking the empty arm.

**The locks corroborate; they do not define the set.** `batch_work.sh` writes `sysop/runtime/locks/BATCH-<N>.lock` carrying `task_id: BATCH-<N>` and the `branch:` it claimed, and `close_batch.sh` removes it at close — so a lock is good evidence a batch is in flight, and worth cross-checking against. But **a merged batch with no lock is an ordinary state, not an anomaly**: `close_batch.sh` says so in its own words when it finds none — *"claimed before batch locks shipped, or already released"*. Deriving the set from locks alone therefore drops exactly those batches, and because the empty-set arm below then fires, the close reports `none this cycle` over a batch left `Pending` with its boxes open. That trades this step's old failure — a loud halt — for a silent false record, which is the worse direction. **Where the two disagree, `review_tasks.md` wins and the discrepancy is reported.**

Two lock shapes to be aware of when cross-checking, because both fail quietly: two locks naming the same branch both match, and a lock whose free-text `notes:` tail carries a second column-0 `branch:` line is read differently by a `grep`-style reader (first wins, or nothing) than by PyYAML (last wins). Neither is a reason to prefer locks as the source; both are reasons the corroboration step reports rather than resolves.

**Do not read `review_task_ids` for this.** It is the obvious-looking candidate in the pending-doc frontmatter and it is the wrong namespace — it holds `TASK-NNNN` ids from `review_tasks.md`, and `close_batch.sh` takes a batch number — bare, zero-padded, or the `BATCH-<N>` form, and nothing else. Verified by running it rather than reasoned about: `BATCH-1` is accepted (the prefix is stripped), while `close_batch.sh TASK-0001` is rejected at **argument parsing** — `❌ Unknown argument: TASK-0001`, exit 1 — so it never reaches a batch lookup at all. "It takes integers" is the tempting shorthand and it is wrong in the direction that matters, because it implies the `BATCH-` form fails too. Three shipped sites already say so, which is why this is a convergence and not a new rule: Step 4c's routing note (*"`review_task_ids` is documentary only and never consulted here"*), `/document-work`'s two-namespace section, and `close_batch.sh`'s own `remove_claim_artifacts()` comment (*"Step 4c has no batch-id list to iterate"*).

**The empty set is the ordinary case, not an edge case, and it has its own arm — but it must be *derived*, never inferred from absence.** A `/claim-task` single-task cycle carries no review batch at all, which is the dominant path rather than a corner of it. **Empty means `review_index.py --list --merged` named no batch** — a positive reading of the authoritative file. It does **not** mean "no locks were found": that is the false-empty above, and it turns a missed batch into a clean-looking report. **And it does not mean the reader failed to run** — that is a second false-empty, arriving by a different route. `review_index.py --list` exits **0** whether it names batches or names none, so the exit code is a discriminator that stdout alone cannot be: exit `0` with no lines is a *measured-empty* set, and **any non-zero exit is a could-not-measure, never an empty set.** **Read the exit code before you read the lines.** On any non-zero exit, report it and **STOP** — do not take the empty arm below. A batch the reader could not name is left `Pending`, its task boxes open and its lock in place, while this step reports success.

**The reader now states its own verdict, and that line is what the empty arm keys on.** `--list` writes one line to **stderr** on every run — under `--merged`, `review_index --list --merged: read review_tasks.md (<N> lines); <K> batches in it; <M> listed for the <J> branches given.` — because stdout is a machine format in which a batch-free tracker is legitimately zero bytes, and a run that produced zero bytes could not be told from a run that never happened. **Absence of that line is a could-not-measure, exactly like a non-zero exit.** It also closes a **second route** into the incomplete-answer state the paragraph below names: a `### Batch` header the strict pattern rejects is reported by nothing — no row, no error — so the tracker plainly declares a batch and the list is silently short. `--list` now names the file and line for each such header (balanced-fence examples excluded, since those are documentation and not tracker content), **at two levels, and the level is the disposition**. `WARNING:` when the tracker's list came back **empty** — an empty set plus a visible batch header is a false empty, so this is a could-not-measure and it halts, exactly like the duplicate-number rule below. `NOTE:` when the tracker's other batches *were* read — the answer may be short, so open `review_tasks.md` at the line the `NOTE:` names, and if that batch's `Branch:` is one you passed, add its number to the set; do **not** halt: a near-miss spelling is tolerated elsewhere on purpose (`close_batch.sh` closes such a batch anyway through its permissive twin), and treating it as a hard stop would make one legacy header block every future close of unrelated work.

**A tracker that does not exist is the empty set too.** `--list` then prints `review_index --list: review_tasks.md absent; 0 batches listed` on stderr and exits 0 — a repo that has never run the convention loop has no review batches to close. **Unless `sysop/runtime/locks/BATCH-*.lock` exists, or `--list` itself exits 1 because git history shows the tracker once existed:** either means the tracker was deleted or moved mid-flight, not that there is none. STOP and report which.

**Exactly two exit codes are reachable from a bare `--list`.** `0` (it ran — on an absent tracker too, see above) and `1` (the tracker is absent but `git log -- review_tasks.md` shows it once existed: a deleted tracker is not the empty set) — plus `2` from a wrong command word. `--merged` adds `7` (an operand above) and `8` (a `WARNING:`, below), and prints no rows on either. The script's other refusal arms (`3`, `5`, `6`) sit behind `--check-duplicates`, `--check-fences` and `--check-headers`; **`--list` itself refuses only a deleted tracker**, and this step does not prescribe those flags.

**So exit `0` means the reader ran — NOT that its answer is complete, and this is the third state.** `--list` keys batches by number, so a tracker declaring the same batch number twice reports **only the last**, silently, at exit `0`. Measured: a fixture with a real `Batch 7` and a duplicate `Batch 7` printed one row — the duplicate — and the real batch's branch was simply absent from the output. **The only signal is a `WARNING:` line on stderr**, which a caller reading stdout for tab-separated rows never sees. **Under `--merged` a `WARNING:` exits 8 and prints no rows.** So: **capture stderr as well, and treat any `WARNING:` as a could-not-measure** — same disposition as a non-zero exit, stop and reconcile the tracker. Read as if it were absent, a dropped batch Step 4a merged would leave the set empty, this step would take its empty arm, and `close_batch.sh` would never be called for it — which is precisely the silent false close this arm exists to prevent, arriving at exit `0`. When the set is genuinely empty: report the one line

```
4b: no review batches this cycle
```

run nothing, and **skip the landing gate below** — go straight to Step 4c. Running the script anyway is not the escape: with no operands it exits 1 on `❌ No batch numbers provided.` and commits nothing, so an empty set has no shape in which this step succeeds. The gate looks for a `docs: close Batch …` tip that a zero-batch cycle never produces and never will, so applying it here halts a healthy close permanently, *after* Step 4a's merges have landed on the integration branch, which is the expensive place to stop. It also stops the compliant agent specifically: the operator who infers a no-op gets through, and the one who follows the step as written does not. Naming the did-not-run state rather than falling silent is the shape Step 2b's `N skipped (doc-only)` and `4a-post`'s `ran nothing: why` already use.

**With a non-empty set** — `--merged` printed a row, or the `NOTE:` check above added a batch — record the arm, from the main checkout's top level, with the close id `begin` printed written out:

```bash
python3 sysop/scripts/close_arms.py exited "<close-id>" 4b-batches 1
```

It prints `ARM: 4b-batches`. **Exit 2**: stop and show its stderr.

**Load this arm when the `exited` command above printed `ARM: 4b-batches`.** Read `${CLAUDE_SKILL_DIR}/steps/4b-batches.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`. It runs `close_batch.sh` and verifies the close-batch commit landed before Step 4c.

<!-- sysop:arm=4b-batches -->

**Do NOT remove completed batches** — they will be archived during the next `/codebase-review` run.

### 4c. Consolidate Pending Documentation

After all branches are merged but **before** pushing:

1. **Scan for pending docs**: `ls sysop/runtime/pending-docs/*.md 2>/dev/null`

   > **One entry in that glob is not a pending-doc, and consolidating it destroys something.** `convention-candidates.md` is a fixed-name file `/codebase-review` and `/security-audit` write, append to each other's copy of, and delete themselves at their own Step 9; it carries no `branch:` frontmatter and belongs to no branch. **Exclude it by name** — it is the shape the "no `branch:`" rule below reads as benign, so consolidating it routes nothing (no `type`, no `roadmap_ids`) and then deletes an open review round's candidate list. Do **not** quarantine it either: `/codebase-review` Step 9 reads it back at that exact path and would silently report "no candidates". Leave it where it is. `quarantine/` is a subdirectory, so this non-recursive glob does not reach it — that is deliberate, and it is why it is a subdirectory rather than a suffixed `.md` file, which every reader of this glob would pick up as a second doc.

1b. **Drop any pending-doc whose branch did not actually merge — this gate decides task state, so it must not run on an unmerged branch's doc.** Step 3b copies each approved branch's pending-doc into main's `sysop/runtime/pending-docs/` *before* the merge is attempted (that ordering is deliberate — it is what stops `git worktree remove` from destroying the doc). So a branch that is approved, has its doc collected, and then **fails to merge at Step 4a** leaves a doc here that this step would otherwise consolidate — routing its content to the shared docs, flipping its `roadmap_ids` to `status: done`, `git mv`-ing the body to `archive/`, and dropping the task's lock and parked markers, **with the code never merged**. Step 3b's own rollback (its step 2b) covers only the case where *it* skips a branch, and says so; nothing covered a 4a-SKIP until this filter.

   > **Before resolving anything, run 1c's hold test without `--stamp`** (`python3 sysop/scripts/pending_doc_hold.py check`) and read the doc's line. A `HELD:` line means 1c holds the whole doc — leave-in-place, route nothing — and **that outcome does not depend on what 1b returns**. Resolving the ref is then pure downside: the only thing it can add is 1b's *"stop and ask — do not guess in either direction"*, a halt on a branch reference for a doc that was never going to be routed.
   >
   > **It short-circuits 1b's REF RESOLUTION, not 1c.** A doc this test holds still goes through 1c below, which is what records the hold and puts it on Step 8's `Held-back docs:` row.
   >
   > **The command reads the ids the way 1c reads them:** `roadmap_ids`, falling back to `task_ids`.
   >
   > **Ordering, not deletion.** 1b still runs, unchanged, for every doc 1c does not hold; the population reaching its *ref resolution* is the only thing that changes.
   > See `REFERENCE.md` § *Step 4c — provenance*.

   For each file found in step 1, read its `branch:` frontmatter value (parsed as YAML, so without the quotes the templates write) and keep it only if that branch is contained in the merge target:

   ```bash
   git rev-list --count "refs/heads/<branch from frontmatter>" "^HEAD"
   ```

   **`0` means merged. A non-zero count is not yet a verdict**: ask the recorded PR heads and the fallback below first. `HEAD` is the merge target here. A **rebased-then-ff-merged** branch is fully contained in it, and a **`--no-ff`-merged** branch scores `0` too — its commits go onto the merge target unchanged, so `^HEAD` reaches them. Both shapes are contained. The one shape that is **not** is a rebase onto a throwaway ref, where the branch's own commits never join the target and a perfectly merged branch scores `2`. **This test is valid only pre-squash.** It is an ancestry test, and a squash breaks ancestry, so it must not be reused after the PR merges.
   See `REFERENCE.md` § *Step 4c — provenance*.

   **On a count other than `0`, or no count at all** (a ref that does not resolve prints none), the doc goes to the arm below: it asks the recorded PR heads, then falls back to `git cherry`. Run, from the main checkout's top level, with the close id `begin` printed:

   ```bash
   python3 sysop/scripts/close_arms.py exited "<close-id>" 4c-unmerged 1
   ```

   It prints `ARM: 4c-unmerged`. **Exit 2**: stop and show its stderr.

   **Load this arm when the `exited` command above printed `ARM: 4c-unmerged`**, once per close: a later doc's count follows the arm already loaded. Read `${CLAUDE_SKILL_DIR}/steps/4c-unmerged.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=4c-unmerged -->

   > **Quote the `^` operand. Both operands, every time.** `^HEAD` unquoted is a **negated-glob pattern** under zsh with `extended_glob` set — which oh-my-zsh and many `.zshrc` files enable, on the platform whose shell these blocks are commonly run in. It expands to *"every entry in the CWD except `HEAD`"*, git receives those as **pathspecs**, the exclusion is silently dropped, and the command exits 0 with a wrong number. Measured on a merged branch: `"^HEAD"` → `0`, bare `^HEAD` → `2`. A **merged** branch then classifies `NOT-MERGED`, so its pending-doc is never routed, its `roadmap_ids` never flip to `done`, its body never moves to `archive/`, and its lock and parked markers never drop — every close, silently. The spot-check that would catch it is the one an author is least likely to run, because an *unmerged* branch returns non-zero either way and looks correct. `WORKFLOW.md` § 8.2a names quoting as an uncovered invocation class; this is a shipped instance of it. **`NOT-MERGED` means leave the file in place and skip it entirely**: do not route it, do not touch its task IDs, do not delete it. It is re-collected on a later run once the branch is mergeable. Report each one on Step 8's report beside its 4a-SKIP entry.
   >
   > **Report it even when there is no 4a-SKIP entry to sit beside.** That instruction assumed the only way to be held back is to fail Step 4a, and the cherry-pick case above breaks the assumption: the branch merged, Step 4a recorded no skip, and Step 8's `Remaining:` block has no slot for the doc. Use the `Held-back docs:` line in Step 8's template — one row per doc, naming the branch, the count each test returned, and the reason — and never let the only trace be a smaller `<N>` in `Docs: Consolidated <N> pending-docs`, a number with nothing to compare it against.

   **If `refs/heads/<branch>` does not resolve, stop and ask — do not guess in either direction, and never retry the bare name**: a tag or remote-tracking ref of that name is not the branch, and a tag on an ancestor reads as merged. Step 6 is the only step that deletes feature branches and it runs *after* this one, so at this point every branch this close merged still has a local ref; a missing one is an unexplained state, not a legacy quirk.

   **If `branch:` is ABSENT, quarantine the doc and carry on — do not stop, and do not consolidate it.** Move it to `sysop/runtime/pending-docs/quarantine/` (a subdirectory, so no `*.md` reader sees it again) with `python3 sysop/scripts/pending_doc_collect.py quarantine "<name>.md"`, which creates the directory and never overwrites; a non-zero exit names what it could not move. Report it on Step 8's `Quarantined docs:` row, and continue with the next file.

   > **This rule replaced two opposite ones, and the ambiguity was not theoretical.** Until this phase the paragraph above read, verbatim, *"If `branch:` is absent or the ref no longer resolves, stop and ask — do not guess in either direction"*, while the blockquote two lines below said a doc *"with no `branch:` at all is the one benign shape … so consolidating it is safe"* — opposite dispositions for the identical input, and the second closed with *"say which case you hit rather than silently picking"*, which concedes the ambiguity without resolving it. **Measured:** two independent fresh-context reviewers, reading this same file with no contact between them, implemented one disposition each — one halted the close, the other consolidated the doc and deleted it. That is not a reading dispute; it is a step whose behaviour on a real input depends on which sentence the agent reaches first. Quarantine is chosen over both: *stop-and-ask* turns any such file into a permanent halt on every future close (nothing else in the tree deletes a pending-doc), and *consolidate-as-benign* routes nothing and then deletes the only copy. Quarantine loses no bytes, needs no human turn, and cannot recur — the file is out of the glob the moment it moves.

   > **If you are reading this having already hit the stop**, the doc's content is almost certainly in `main` already — verify with `git log --oneline --all --grep` on its summary before deciding, and do not consolidate on the assumption alone. The `git cherry` fallback above is what prevents the hold-back in the first place. **A doc with no `branch:` at all is quarantined, per the rule above.**
   > See `REFERENCE.md` § *Step 4c — provenance*.

1c. **Hold back any pending-doc whose deliverable is not finished: one whose own frontmatter carries `hold:`, or one naming a task whose human step is still outstanding.** This test is applied twice and the two are one mechanism. **1b short-circuits its ref resolution on it** (see 1b's first blockquote), so a held doc is spared 1b's stop-and-ask. **This pass runs over every doc regardless**, because it is the one that records the hold and reports it. A doc the short-circuit spared is still held, still reported, still left in place — the short-circuit removes a ref lookup, never a record. Run the test; it also stamps each held doc whose branch is merged and that it has not stamped before:

   ```bash
   python3 sysop/scripts/pending_doc_hold.py check --stamp
   ```

   It reads each doc's `hold:` and looks each of its ids up in `tasks/index.yml`. **Read `roadmap_ids`, falling back to `task_ids`** — the same `task_ids` compat shim step 3 applies. Both fields are read truthy, **not** `== true`, matching the round-trip's predicate exactly, so the two gates agree. A hold is per task: a doc naming an id that a held doc names is held too (`shares <ids> with a held doc`). **For each `HELD:` line, do not route this doc at all this run** — leave the file in `sysop/runtime/pending-docs/`, exactly as 1b leaves an unmerged branch's doc, and report it under Step 8's `Held-back docs:` with the reasons the line prints (`user_action outstanding: <TASK_ID>`, `hold: <reason>`, `shares <ids> with a held doc`) and its `held since` date. `ROUTE:` docs go on to step 2, and an `UNREADABLE:` doc is step 3's quarantine case. **If the command exits non-zero, stop the close:** it could not decide the holds (1: `tasks/index.yml` could not be read, or no git repository; 2: no PyYAML, or a usage error). A `NOT STAMPED:` note still holds its doc; put it on the Step 8 row, because `/document-work` does not protect an unstamped held doc from being replaced.

   **`held_since:` is this step's only write to a held doc. Never remove `hold:` here.** `/document-work` writes it, and the human removes it with `python3 sysop/scripts/pending_doc_hold.py clear <TASK_ID>`.

   **Why the WHOLE doc waits, and not just the status flip.** The first cut of this fix did the narrower thing the filing proposed — route the doc entries as normal, hold only the three mutations that assert completion — and it **stranded the task**. The path is worth writing down because nothing about it is obvious: step 6 deletes the pending-docs *this step consolidated*, a routed doc is consolidated, and the pending-doc is the **only** carrier of `roadmap_ids` into this round-trip. So the doc would be gone, the task would sit `in_progress` with its lock held and its body under `open/`, and nothing would ever close it — `clear_user_action.py` flips the flag and says so in its own output (*"status is `in_progress`, so the automated frontier … still will not pick it up"*), and a later `/review-close` has no doc naming the task. **A silent permanent stall, arriving from a fix for a silent false close.** Holding the doc keeps the carrier alive: the human performs the step, clears the flag or the `hold:`, and the next `/review-close` consolidates the doc and closes the task through the ordinary path, with no duplicated `CHANGELOG` entry. **The doc is only half the carrier, and the other half is the branch** — the doc's `branch:` is what step 1b resolves, and Step 6 deletes merged feature branches under both policies, so a held doc whose branch was cleaned up does not resume: it **halts** the next close on step 1b's stop-and-ask. Step 6 therefore carries a HARD RULE excluding those branches; that rule and this hold are one mechanism and neither works alone.


   **Granularity is the whole doc, deliberately.** A pending-doc naming two tasks, one held and one not, holds **both**. Splitting it would mean routing half a doc and re-routing the other half later, which is the duplication this ordering exists to avoid; the conservative direction is the one that cannot write a false `Complete`. Say so in the Step 8 row — name the held task *and* the siblings waiting on it — so the operator can see the whole doc is waiting on one human step.

2. **If none found**: check merged history for `docs:` commits (backward compatibility with branches that wrote docs directly). If present, skip doc consolidation — the docs are already in the shared files.

3. **If pending-docs files found**: parse each file's YAML frontmatter and extract:
   - `branch`, `date`, `type`, `roadmap_ids`, `review_task_ids`, `summary`

   **Format detection — three arms, and the third one is not optional.** Use the same reader Step 3c already ships (`fm_re = re.compile('^\\ufeff?---\\n(.*?)\\n---', re.DOTALL)`), not a `startswith('---')` test:

   1. **Frontmatter matches and `yaml.safe_load` returns a mapping** → parse it. The normal path.
   2. **No frontmatter match** → the legacy 5-section markdown format (`## Classification`, `## PROJECT_STATUS Entry`, etc.).
   3. **Frontmatter matches but will not parse, or parses to something that is not a mapping** → **quarantine the file and carry on.** "Will not parse" is any exception `yaml.safe_load` raises, not only `yaml.YAMLError`: `date: 2026-09-31` raises `ValueError`, so catch `Exception`. Move it to `sysop/runtime/pending-docs/quarantine/` with `python3 sysop/scripts/pending_doc_collect.py quarantine "<name>.md"`, which creates the directory and never overwrites, report it on Step 8's `Quarantined docs:` row, and continue with the next file. Do **not** route it (it has no `type`, so the routing table does nothing), do **not** delete it (its bytes are the only record of what shipped), and do **not** leave it in place (it would be re-encountered on every future close).

   > **`or {}` does not protect against a non-mapping — do not rely on it.** `yaml.safe_load("work in progress")` returns the truthy string `"work in progress"`, so `fm or {}` yields the string and `.get()` raises. Test `isinstance(fm, dict)` explicitly.
   > See `REFERENCE.md` § *Step 4c — provenance*.
   <!-- Legacy format support — remove after all active worktrees are merged -->

   **`task_ids` compat shim — read every pending-doc with this fallback:**

   ```python
   roadmap_ids    = pending.get('roadmap_ids')    or pending.get('task_ids') or []
   review_task_ids = pending.get('review_task_ids') or []
   ```

   Treat any IDs read via the fallback as `roadmap_ids`.
   See `REFERENCE.md` § *Step 4c — provenance*.

4. **Route by type and write to shared docs** (single pass, no conflicts since we're on main post-merge):

   Use this routing table to determine which shared docs to update for each entry. The "Roadmap" column shows which frontmatter field drives the `tasks/index.yml` round-trip; `review_task_ids` is **documentary only** and never consulted here (review-task closure happens in Step 4b via `bash sysop/scripts/close_batch.sh`) — **nor is it consulted there**, which this sentence used to leave open: Step 4b derives its batch set from the `BATCH-*.lock` files, because these are `TASK-NNNN` ids and that script takes batch integers. Previously neither step named a source, so the two pointed at each other.

   | Type | PROJECT_STATUS | Changelog | UI_Iterations | Roadmap (`roadmap_ids`) |
   |---|---|---|---|---|
   | feature | Yes | — | — | if populated |
   | bugfix | Yes | Yes | — | if populated |
   | ui-iteration | Yes | — | Yes | if populated |
   | infrastructure | Yes | — | — | if populated |
   | adhoc | Yes | — | — | if populated |

   The Roadmap column is **informational only** — `if populated` means the `tasks/index.yml` round-trip below runs unconditionally for every ID in `roadmap_ids`, regardless of `type`. This is intentional: the round-trip is mechanical (status flip + body move + lock/parked-marker cleanup), driven by data presence, not by type. **One condition was added later and it is not a type test either — it is a field test.** A task whose `user_action` is `true` is HELD: its doc entries route exactly as this table says, and the three mutations that assert completion do not run. `type` still governs nothing here; `user_action` governs whether the close may claim the task is finished. Take the ids from step 1c's `ROUTE:` docs, never from a `HELD:` one. The script also reads the pending docs and does not close an id a doc with `hold:` names (`HELD_BY_HOLD`). See the hold comment in `close_index.py` for why the smoke gate is not a backstop for it. A pending-doc with `roadmap_ids: []` simply skips the round-trip naturally. (BeanRider ISSUE-0034: tracked-bug close-outs use `type: bugfix` with a populated `roadmap_ids: [BUG-NNNN]` and need the round-trip; the prior `—` reading would have left the BUG entry stuck `in_progress` with the body orphaned under `open/`.)

   For each entry, generate the doc content from `type` + `summary` + `roadmap_ids` + `review_task_ids` + `date`:

   **PROJECT_STATUS.md §6**: Generate a one-line entry: `<date>: [<ID(s)> Complete:] <summary>`. Copy `summary` as the doc has it, here and in any changelog bullet this close writes for the same entry. Pull IDs from `roadmap_ids` AND/OR `review_task_ids` — both kinds belong in the PROJECT_STATUS entry as provenance. **If `PROJECT_STATUS.md` is absent, create it first** — `# Project status`, a blank line, then `## 6. Recent Major Updates` (the one heading item 5's check keys on) — and say `S6: created PROJECT_STATUS.md` on Step 8; a missing file is not a reason to skip the write. Insert at the TOP of Section 6 "Recent Major Updates" (below the section header, above existing entries). Newest branch first.

   **Consolidation clause — a wide close writes ONE §6 entry, not one per branch.** Count the pending-docs this run is routing (the merged-only set from step 1b, the same `<N>` the commit subject carries). **If `<N>` is more than 4**, do not write the per-branch entries above. Write a single one-line entry instead — `<date>: <N> branches merged in one close: <batch or branch list> — per-branch detail in CHANGELOG.md` — and route **every** entry's detail to `CHANGELOG.md` (see § *The changelog contract* below) as a bullet under `## [Unreleased]`, classed by `type` (feature → `### Added`, bugfix → `### Fixed`, everything else → `### Changed`) with ` (<date>)` appended, whatever its `type`. Then §6 reads as one update, which is what a close of many branches is; a squash PR is one update however many branches it consolidated.

   > **Why the cap is on the writer and not on the rotation.** The write above scales with branch count and the rotation below is a **constant**, so without this clause the two invert on exactly the shape `/auto-fix` and `/auto-judge` produce (internal tracker #364): with 6 pre-existing entries and 8 pending-docs, 6 + 8 = 14 rotates down to 6 — discarding all 6 pre-existing entries **and 2 of the 8 just written**, in the commit that wrote them.
   >
   > **The condition, derived rather than restated.** The run's entries are inserted newest-first, so rotation reaches them only after it has consumed every pre-existing entry: it removes `total − 6`, which exceeds `pre_existing` exactly when **`docs > 6`** — the retained count, not the trigger. So a run loses its own entries iff `pre_existing + docs > 8` **and `docs > 6`**. The filing (and this clause's first draft) said `docs > 2`, which over-claims on 22 of the 49 `(pre_existing, docs)` pairs up to 9 — every one of them in the "says it reproduces, does not" direction. The filing's worked example was right and its general rule was not.
   >
   > **What follows for the threshold, stated so it is not read as arithmetic.** Any cap of 6 or less closes the self-loss case completely, so **4 is not required by the defect** — it is chosen for the second reason option (b) was preferred at all: eight per-branch lines in "Recent Major Updates" is not a summary of anything, and a squash PR is one update however many branches it consolidated. That half is a judgement about readability, and it is the only reason the cap is 4 rather than 6. The invariant a test can hold is the one that matters: **the cap must never exceed the retained count**, or an entry this run wrote can be rotated out by this run.
   >
   > The rejected alternative was to make the rotation skip anything dated today: that grows §6 without bound on a day with several closes, and has no answer for a §6 in which every entry is from today.

   **Rotation check**: if §6 has more than 8 entries after adding, rotate the oldest entries to `CHANGELOG.md` — each as `- [<ID(s)>: ]<summary> (<original date>)` under `## [Unreleased]` → `### Changed` — until only 6 remain. **Report the count you rotated** in the Step 8 summary — a truncation nothing announces is how this step's scaling defect survived unnoticed.

   **Where §6's entries end.** An entry is a line in the shape the writer above produces: it starts with `<date>:`, after an optional list marker (`-`, `*` or `+`). §6's entries run from the section's first entry line, which may sit below a lead-in line or a subheading, through every entry or blank line after it, and end at the first line that is neither. An entry is one line. **If an indented line sits directly under an entry, with no blank line between, do not rotate:** a wrapped entry and indented furniture look the same there, and moving either the wrong way loses text. Add this close's entries, leave the rest of §6 as it is, and name the line in Step 8's §6 row; item 5's check exits 2 on it. That line may be text, the next section, or the end of the file, because §6 may be the file's last section, so never find the end by looking for the next numbered heading. Count, insert and rotate inside that run only: a new entry goes directly above its first entry, and the oldest leave from its bottom. Every other line in the section is furniture: a lead-in line, a `(Older entries rotated …)` marker, a note to agents. Furniture is never rotated, never deleted, and never joined onto an entry in either file. Item 5's check refuses a write that moved any of it.

   > **Rotation is a MOVE, and it must not re-write an entry that is already there.** A `bugfix` entry was written to §6 *and* to `CHANGELOG.md` on the close that created it (the routing table's `Yes | Yes` row). Some later close then rotates that §6 line out — into the same file the bullet already sits in — and the file ends up carrying one piece of work twice, in two formats. **So for each line you are about to rotate: search the whole of `CHANGELOG.md` for it first** — the whole file, not one section, because the existing bullet may sit under `## [Unreleased]` from the close that wrote it or under a `## [x.y.z]` heading if `/release` has folded it since. If a bullet already carries it, the entry is already recorded — **drop the §6 line instead of copying it**, and count it as rotated all the same (the §6 slot was still reclaimed). Only lines with no existing bullet are written. **Run two searches for every line and read every hit: one for each of its task ids, and one for its summary.** A close can write the changelog bullet for the same work in different words, or without the id, so either search alone can miss it; and an id can appear inside another entry's prose, so a hit counts only when it is that entry's own bullet. The two formats differ (`<date>: [ID Complete:] <summary>` in §6 versus `- **<Title>**: <summary> (<date>)` in the changelog), so match on the **summary**, not on the whole line — a whole-line match never fires and would leave this rule inert while looking present. **A Consolidation clause line** (`<date>: <N> branches merged in one close: …`) **is already recorded**, because the clause wrote every entry's detail to the changelog: drop it, and count it as rotated. If neither search finds the entry, write it: a duplicate is visible, a dropped entry is not.

   **CHANGELOG.md** (bugfix type only, **and only when the Consolidation clause did not fire**): Generate entry `- **[<ID(s)> — ]<Short Title>**: <summary> (<date>)`, where `<ID(s)>` are the doc's `roadmap_ids` and `review_task_ids` and the bracketed part is left out when it names none. Copy `summary` as the doc has it. Add under `## [Unreleased]` → `### Fixed`. Create the `### Fixed` class heading — and the `## [Unreleased]` section itself, directly under the file's title block — if missing.

   > **The changelog contract — one file, one grammar, shared with `/release`.** The file is `CHANGELOG.md` in [Keep a Changelog](https://keepachangelog.com) shape: a title block, then `## [Unreleased]`, then the `## [x.y.z] - <date>` version sections `/release` owns. This step writes **only** inside `## [Unreleased]`, as `- ...` bullets under the standard class headings (`### Added` / `### Changed` / `### Fixed`) in the bugfix write's `- **[<ID(s)> — ]<Short Title>**: <summary> (<date>)` shape, carrying the entry's task ids so a later rotation can find it by id (rotation's `- [<ID(s)>: ]<summary> (<original date>)` is the one exception — a rotated §6 line has no title to bold), with ` (<date>)` appended because `[Unreleased]` carries no date headings; **every writer above creates what is missing** — the class heading, the `## [Unreleased]` section (directly under the title block; on a legacy changelog with no title block, add the standard Keep-a-Changelog title block first), or the file itself — the create contract is the contract, not the bugfix row's private property; **a class heading is missing only when no `### <Class>` line lies anywhere between `## [Unreleased]` and the next `## ` heading, outside a code fence** — if one does, write under it wherever it sits and never create a second (if the file already has two, write under the first; item 5's check reports the fork for a human to merge); `/release` folds `[Unreleased]` into the next version section when a release is cut. Two rules keep the two writers off each other: **(a)** if the project already tracks its changelog under a different case (check `git ls-files -- ':(icase)changelog.md'` — one read-only git command, no pipe to bind a second rule — `changelog.md` and `CHANGELOG.md` are the *same file* on a case-insensitive filesystem, which is the macOS and Windows default), write to that existing tracked path rather than creating a second name; **(b)** if no changelog exists under any case, create `CHANGELOG.md` with the standard Keep-a-Changelog header — the same create contract as `/release`. The pre-222 grammar (`### YYYY-MM-DD` date headings under month headings) is retired; leave any existing date-headed entries where they are — they are history, not a format to continue.

   > **Why the second condition.** The Consolidation clause above routes **every** entry's detail to `CHANGELOG.md` on a close of more than 4 pending-docs — *including* the `bugfix` ones. Running this write as well would put **two bullets for one entry under the same class heading, in the same close**: the clause suppresses only the per-branch §6 writes "above", not this one. That is the `/auto-fix` and `/auto-judge` shape, so it is the automated path rather than an edge case. One clause fires or the other does; never both for the same entry.

   **tasks/index.yml**: For each ID in `roadmap_ids` (NOT `review_task_ids` — those are documentary, see the note above), round-trip the index through `yaml.safe_load` to set `status: done` + `completed_date: <today's ISO date>` on the entry, then `git mv` the body file from its current location under `open/` or `deferred/` to the corresponding location under `archive/` and update the entry's `body:` field. The script below is prefix-agnostic — it handles both canonical (`body: open/<TASK_ID>.md`) and `tasks/`-prefixed (`body: tasks/open/<TASK_ID>.md`) shapes by locating the `open` / `deferred` path segment and swapping it for `archive`. It also tolerates pending-docs authored before `roadmap_ids` existed (compat shim — see the **`task_ids` compat shim** block in step 3 above). After all IDs are processed, run the validator (`python3 sysop/scripts/validate_tasks.py` — a single command matching `Bash(python3 sysop/scripts/validate_tasks.py:*)`; an earlier build dropped the shared `PATH` prefix this line used to ride on and gave `validate_tasks.py` its own `sys.path` PyYAML bootstrap, so bare `python3` resolves `yaml` for both venv-only and non-venv consumers — BeanRider ISSUE-0049) — if it exits non-zero, abort the close. The schema invariants for `done` status require: a valid `completed_date`, either a `body:` or an `archive_summary:`, and (ISSUE-0009) the body path must NOT contain an `open/` or `deferred/` segment (a half-migrated state where the status flip wrote but the rename silently no-op'd). Fix any failure before pushing.

   Under `--request-review`, put `--keep-locks` before the ids: `python3 sysop/scripts/close_index.py --keep-locks "<roadmap id>" …`.

   ```bash
   # Run it as written: a PATH prefix, an `&&` compound or `.venv/bin/python3` binds no rule.
   # One quoted argument per roadmap id from step 1c's ROUTE: docs, never a HELD: doc's,
   # and none when they name none. An argument that is not an id (holding `<` or `>`,
   # starting with `-`, or empty) is refused before anything is written.
   python3 sysop/scripts/close_index.py "<roadmap id>" "<roadmap id>"
   ```

   **Its exit must be 0**: anything else means the rows above are incomplete, and the validator below cannot see it, so stop. Then, as its own call:

   ```bash
   python3 sysop/scripts/validate_tasks.py
   ```

   **A non-zero exit**: the validator rejected the index; stop the close.

   **UI_Iterations.md** (ui-iteration type only): Generate table row `| <name> | <date> | <summary> | <commit-hash> |`. Append to the markdown table.



5. **Check what the writes above did, before the pending-docs are deleted.** Run this once every write in item 4 is done. Item 4's script has already staged the index flip and the body renames and reaped the claim artifacts; the shared docs are not staged yet. The check compares `PROJECT_STATUS.md` and the tracked changelog on disk with `HEAD`, which does not yet carry these writes, and it resolves the repository root itself. It checks four things: every line of `PROJECT_STATUS.md` outside §6's entries is unchanged; §6 holds the entries the Rotation check leaves, the new ones above the newest old ones, in order; no line of §6's furniture reached the changelog; and the changelog lost no line and gained no second copy of a class heading, or of `## [Unreleased]`, under `[Unreleased]`. It does not check that a rotated entry reached the changelog, because the dedupe may drop it; that stays yours.

   ```bash
   python3 sysop/scripts/close_check.py
   ```

   - **Exit 0:** continue. Carry `ROTATED:` and any `WARN:` line into the Step 8 summary.
   - **Any other exit:** follow its arm before item 6. A check that did not run (a denied command has no exit code) is not exit 0: stop the close here, before item 6. Load the arm on the exit code, never on a printed line; the arm's rows then read the lines. Every exit the check means prints a `RESULT:` line; an exit with none (a traceback, or a shell's 126 or 127) is the check failing to run: stop, as the pre-flight says. Run, from the main checkout's top level, with the close id `begin` printed and that exit code written out:

     ```bash
     python3 sysop/scripts/close_arms.py exited "<close-id>" 4c-check-exit <code>
     ```

     It prints `ARM: 4c-check-exit` for any code but 0. **Exit 2**: stop and show its stderr.

     **Load this arm when the `exited` command above printed `ARM: 4c-check-exit`**. Read `${CLAUDE_SKILL_DIR}/steps/4c-check-exit.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=4c-check-exit -->

6. **Clean up pending-docs**: Delete the pending-docs **this step consolidated** — never a bare "delete all remaining" — by name, one quoted argument each, from the main checkout's top level. When it consolidated none, skip this item:

   ```bash
   python3 sysop/scripts/pending_doc_collect.py consume "<consolidated doc>.md" "<consolidated doc>.md"
   ```

   It removes the directory only when it is left empty, and prints `CONSUMED:`, `ALREADY ABSENT:` and `DIRECTORY:` lines. **Exit 5**: a name matched no doc, so a mistyped name left a consolidated doc behind; stop. **Any other non-zero exit**: stop and report its last line.

   > **A doc step 1b held back must survive this step, and an unqualified delete here silently destroys it.** 1b deliberately leaves any pending-doc whose branch did not merge, for re-collection on a later run. The branch's worktree is already gone (Step 3b removed it before the merge was attempted) and the doc is **untracked**, so deleting it here is unrecoverable — the exact BeanRider ISSUE-0050 class this filter exists to close, re-entered five items later. Delete by name from the set you routed, not by glob.

7. **Stage, then commit**: `docs: consolidate documentation for <N> merged branches`

   **Stage the shared docs one `git add` per file** — item 4's script already staged `tasks/index.yml` and both halves of each body rename, but the shared-doc edits above were made with the editor and are still unstaged. Add **only** the docs the routing table actually sent this run's entries to:

   ```bash
   git add PROJECT_STATUS.md                 # every type
   git add CHANGELOG.md                      # if a bugfix entry was routed there, OR if the
                                             # rotation check moved §6 entries into it
                                             # (use the project's tracked case — see § The
                                             # changelog contract)
   git add UI_Iterations.md                  # only if a ui-iteration entry was routed there
   python3 sysop/scripts/git_check.py head-is "<merge target>" && git commit -m "docs: consolidate documentation for <N> merged branches"
   ```

   > **One `git add` per file, never one command listing them all.** `git add` is **all-or-nothing across its pathspecs**: if any pathspec matches nothing, the whole invocation aborts with `fatal: pathspec '<path>' did not match any files` and stages **none** of the others (verified). `UI_Iterations.md` is consumer-authored and frequently absent — Sysop never creates it — and `CHANGELOG.md` is absent on any close that routed nothing to it (this step creates it only when a write lands there), so a combined `git add PROJECT_STATUS.md CHANGELOG.md UI_Iterations.md` aborts on the majority of close-outs. `-A` does **not** change this: `git add -A <missing-path>` aborts identically. Separate commands mean a missing optional doc costs only its own line.
   >
   > The same property is why the instinctive `git add <old-path> <new-path>` after a `git mv` does not help: the stale pre-rename pathspec aborts the invocation, so nothing is staged by it. It leaves the index exactly as it was — `git mv` had already staged both halves — which is the trap, because it *looks* like staging was attempted and the following `git commit` still succeeds on the unchanged index.
   >
   > **Do not stage `CHANGELOG.md` from the routing table alone.** Two steps above write it without the routing table's say-so, both regardless of entry type: the **Rotation check** writes it whenever §6 exceeds 8 entries, and the **Consolidation clause** writes every entry's detail there on a close of more than 4 branches. So a run with no bugfix at all can still have written `CHANGELOG.md`, and skipping it there commits the §6 truncation — or the consolidated §6 line — without the entries whose detail it points at.

   See `REFERENCE.md` § *Step 4c — provenance*.
   **Then verify the commit carried everything** — a rename-only commit is what this gate is for:

   ```bash
   git log -1 --pretty=%s | grep -q '^docs: consolidate documentation' && git diff --quiet && git diff --cached --quiet
   ```

   If that fails, the tree still has unstaged or staged-but-uncommitted consolidation edits: stage the missing file(s) and commit them with the same chained command and message before proceeding (no `--amend`: no rule admits it under `dontAsk`).

   > **Read the diff before that commit — this is the step that launders a foreign edit in.** `git add` the *named* files the routing table sent this run's entries to, never `-A` and never a bare `git add .`; then `git diff --cached` and confirm every hunk is this close's own work. A stray edit from a Step 2b agent reaches here as an ordinary unstaged modification, and an unread follow-up commit folds it into a commit whose message says "consolidate documentation for N merged branches" — attributed to this close, under a subject that describes something else. If a hunk is not yours, stop and resolve it rather than committing; Step 2b's delta assertion exists to catch it four steps earlier. **Additionally, if this run closed at least one `roadmap_ids` entry** (`close_index.py`'s `CLOSED_IDS:` row was not `(none)`), confirm the index flip is actually in the commit:

   ```bash
   git show --stat HEAD | grep -q 'tasks/index.yml'
   ```

   Skip that second check when no pending-doc carried `roadmap_ids` — `tasks/index.yml` is then legitimately untouched and its absence from the commit is correct, not a failure.

   **If the commit is silently denied** (auto-mode classifier rejects `git commit` on `main` — a `direct`-policy concern; under `pr` policy this commit lands on the integration branch, not `main`, so it does not hit this wall), the `PermissionDenied` hook surfaces the `!`-escape command and the multi-`-m`-flag rewrite recipe — follow its guidance and relay to the user.
   See `REFERENCE.md` § *Step 4c — provenance*.

### 4d. Land on `main`

**First, file the notes `4a-fix` routed to a task**, with its item 6, in their own commit. Step 3c's "Unrunnable as specified" defects and waived FAILs go in the same commit, by the same route. With no notes, commit those on their own with item 6's command, its message `docs: review-close file smoke tasks — <N> task(s)`. Every close that lands reaches this line, including one whose Step 4c made no commit. A close that stops earlier lists the notes on Step 8's `Close notes:` line and the defects on its `Manual smoke:` line, unfiled.

How the assembled work reaches `main` depends on the merge policy from Step 4-pre. Run, from the main checkout's top level, with the close id `begin` printed written out:

```bash
python3 sysop/scripts/close_arms.py arm "<close-id>" 4d
```

It prints `ARM: 4d-direct` under the `direct` policy Step 4-pre recorded, and `ARM: 4d-pr` under `pr`. **Exit 2**: stop and show its stderr, which names the command that did not run.

#### `direct` policy

**Load this arm when the `arm` command above printed `ARM: 4d-direct`.** Read `${CLAUDE_SKILL_DIR}/steps/4d-direct.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=4d-direct -->

#### `pr` policy

**Load this arm when the `arm` command above printed `ARM: 4d-pr`.** Read `${CLAUDE_SKILL_DIR}/steps/4d-pr.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full, except that a `--request-review` close runs only its Step 1 (*Under `--request-review`* item 4). Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=4d-pr -->

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
- **`pr` policy** — run cleanup **only if Step 4d's post-merge `gh pr view --json state` reported `MERGED`.** If 4d-1 reported a stuck PR (red check / `BLOCKED`), **skip Step 6 entirely** — the feature branches, worktrees, and `sysop/runtime/locks/` must survive so the work is recoverable once the check is fixed. When the PR did merge, first re-sync local `main`, then run the `pr` per-branch cleanup below.

**Step 6's arms.** When Step 6 runs, run, from the main checkout's top level, with the close id `begin` printed written out:

```bash
python3 sysop/scripts/close_arms.py arm "<close-id>" 6
```

It prints `ARM: 6-direct` under the `direct` policy, and `ARM: 6-pr-gate` and `ARM: 6-pr-cleanup` under `pr`. **Exit 2**: stop and show its stderr, which names the command that did not run.

**The `pr` re-sync** — the clean-tracked-tree gate, the commits-after-push check, the reset and the integration branch's drop — is an arm. **Load this arm when Step 6's `arm` command printed `ARM: 6-pr-gate`.** Read `${CLAUDE_SKILL_DIR}/steps/6-pr-gate.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=6-pr-gate -->

> **Lock-as-real-time-signal invariant (`pr` policy).** Step 4c removes each closed task's `sysop/runtime/locks/<TASK-ID>.lock` from disk on the integration branch, before the PR merges — so there is a brief window where, on `main`, the task is still `in_progress` (the `done` flip rides the unmerged PR) with no lock. This does **not** reopen the task for the autonomous paths: `/auto-build` and `next_task` only ever claim `status: open` tasks, so neither can pick it up. **Amended — the unqualified form of this sentence ("an `in_progress` task is never claimable regardless of its lock") is no longer true.** `/claim-task` gained a third entry state, and `in_progress` + no lock is exactly its `resumable` signature — which this window manufactures for a task that is *finished*. That is why `resumable` **stops and asks** instead of continuing: an explicitly-named `/claim-task <TASK_ID>` during this window would otherwise re-claim already-reviewed work. The other visible effects are a transient `/sitrep` "in_progress without lock" drift flag and a `validate_tasks.py` Invariant 9 error during the in-flight (or stuck-PR) window, both of which clear when the PR merges and the `done` flip lands. No action needed beyond not re-claiming. The same pre-merge timing applies to the task's **parked marker(s)** (`sysop/runtime/parked/<TASK-ID>__*.md`, removed by the same Step 4c cleanup) — with one honest asymmetry: a lock is trivially recreatable (`claim_task.sh --lock`), but a marker's content (the park's plan + adversarial verdict, never committed) is not. Accepted anyway: by the time Step 4c runs, the park was already resolved — the resume that produced this close consumed the verdict — so a stuck PR needs the *code* recoverable (the integration + feature branches Step 4d-1 leaves in place), not the historical park record. A consumer who wants park history durably should copy `parked/` entries somewhere tracked before closing.

**HARD RULE — do not delete a branch whose pending-doc Step 4c step 1c held back.** This applies under **both** policies below and is checked before either list is built. A 1c hold (`hold:` or `user_action`) keeps the doc so a later run can consolidate it; that doc carries a `branch:` field, and step 1b resolves it with `git rev-list --count "refs/heads/<branch>" "^HEAD"`. **Delete the branch and the next close does not resume — it halts**, on step 1b's *"If `refs/heads/<branch>` does not resolve, stop and ask — do not guess in either direction"*, which is the same self-inflicted stop the cherry-pick blockquote above step 1c already describes. The carrier is the doc **and** the branch; holding one without the other converts a deliberate hold into a hard stop on every subsequent close.

So: before cleaning up, list the docs still there with `find sysop/runtime/pending-docs/ -maxdepth 1 -type f -name '*.md'` (no output, or no such directory, is none), read each one's `branch:`, and **exclude those branches from both lists below**. Report them in Step 8's `Remaining:` as retained-for-a-held-doc, with the task id waiting on them. They are deleted by the close that finally consolidates the doc, one run later.

**`direct` policy — per-branch cleanup** is an arm. **Load this arm when Step 6's `arm` command printed `ARM: 6-direct`.** Read `${CLAUDE_SKILL_DIR}/steps/6-direct.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=6-direct -->

**`pr` policy — per-branch cleanup** is an arm. **Load this arm when Step 6's `arm` command printed `ARM: 6-pr-cleanup`.** Read `${CLAUDE_SKILL_DIR}/steps/6-pr-cleanup.md`, the `steps/` directory beside this `SKILL.md`, with your file tool and follow it in full. Where its first command says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`.

<!-- sysop:arm=6-pr-cleanup -->

For each **SKIP'd** branch (Step 2a verdict — Step 1a classified the worktree as `dirty`, or step 0a's clone pre-check):
1. Leave the worktree or clone, the `sysop/runtime/locks/<TASK_ID>.lock` file, and the branch fully in place — do NOT touch anything.
2. Carry the SKIP entry into Step 8's report so the user sees the paused-work list with its file count and worktree path, or step 0a's Step 1-pre line and remedy.

For each **4a-SKIP'd** branch (approved, but Step 4a could not merge it):
1. Leave the branch and its `sysop/runtime/locks/<TASK_ID>.lock` fully in place under **both** policies — do NOT delete it, and do NOT force-delete it. Its work is in no squash and its worktree is already gone (Step 3b removed it before the merge was attempted), so the branch ref is the only thing holding the commits.
2. Its pending-doc stays in `sysop/runtime/pending-docs/` — Step 4c's merged-branch filter left it there deliberately, and Step 4c item 6 kept the directory while it is present.
3. Carry the entry into Step 8's report with the conflicting file named, so the next cycle knows what to resolve.

For each **rejected** branch that still has a worktree:
1. Leave the worktree and branch in place for future work.

**Hard guard against worktree removal in this step (BeanRider ISSUE-0016).** Step 6's flow as documented does not call `git worktree remove` — worktrees for merged branches are gone after Step 3b, and worktrees for SKIP'd / rejected branches are explicitly preserved. If a future evolution of this skill adds a worktree-cleanup pass here, that pass MUST refuse to remove any worktree Step 1a classified as `dirty` AND MUST NOT use `--force`. The current shape avoids the trap structurally; this note exists to keep it that way as the skill evolves.

Nothing removes `sysop/runtime/pending-docs/` here: Step 4c item 6 removed it if that left it empty.

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

1. **Find the friction log:** `sysop/SYSOP_ISSUES.md` — inside the `sysop/` vendor dir at the consumer-repo root (NOT under `.claude/`, and no longer at the bare repo root). If an older install left it at the root, append there instead rather than treating it as missing. If neither exists, emit one line: `note: sysop/SYSOP_ISSUES.md not present — re-run bash install.sh to seed. Skipping friction capture.` and proceed to Step 8.

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

Resumed:       <under `--resume` only: the run id; each `GONE` line from `close_run.py check`;
               what re-ran and the line that made it; each `NOTE:` line>
Pushed:        <under `direct`: the SHA Step 4d confirmed. Under `pr`: the squash-merge
               SHA and its PR number — "<N> commits" is not a quantity that exists on
               that path, where `main` gains exactly one commit however many merged.>
Branches:      <merged list, each branch Step 4a recorded `merged — already in <ref>` as
               `<branch> — landed in <ref>`> (or "none")
Batches:       <the batch set Step 4b determined, and what it did — "closed N1, N2"
               / "none this cycle — 4b skipped" / "N closed, M failed — still open">.
               Never blank: a skipped Step 4b used to leave no trace anywhere in this
               report, so a close that silently never reached it read exactly like one
               that had no batches to close.
Docs:          Consolidated <N> pending-docs files (or "none" / "legacy docs: commits")
Manual smoke:  <N confirmed, N driven, N unrunnable (<filed task ids>), N failed-held (<branches,
                each with the signals skipped on it>),
                N failed-waived (<filed task ids>), N waived> (or "none required")
               <and each PREVIOUSLY ANSWERED:, NOT IN THIS RUN:, ORIGIN INDEX:, BRANCH INDEX:,
                BODY NOT READ: and MERGE NOT READ: line Step 3c printed, and each failed-waived signal's output, verbatim. Unrunnable,
                failed-held and failed-waived are never counted as waived.>
Verification:  pre-merge <ran | skipped: doc-only | skipped: no changed-file list>;
               merged-tree (4a-post) <ran on <merge target>: N commands
                                      | ran nothing: why | not reached: why
                                      | TIMEOUT: <command> — killed, so it returned no
                                        verdict. The tree is UNVERIFIED: neither passed
                                        nor failed, and never folded into "ran N commands".
                                      | INHERITED: <command> — fails on origin/<default
                                        branch> too; <TASK-ID> is in this close's Step 4c
                                        set. The gate RAN and a command FAILED; the close
                                        continued because 4a-post item 4's three
                                        preconditions all held. Never folded into "ran N
                                        commands" either — that would report a failing
                                        command as a passing one.
                                      | PRE-EXISTING: <command> — <N> test IDs also fail on
                                        origin/<default branch>; proceeded on the human's
                                        answer. A FAILED command, never folded into "ran N
                                        commands".>
               <and, on a zero-approved-branch cycle whose changed-file list came back
                empty, `changed-file list empty — zero approved branches` — a fact about
                SCOPE, never a substitute for the execution arm above.>
               pre-scan <clean | clean, but not every check ran fully — <the header's counts,
                          and each ⚠ BLOCKING CHECK, failed:, degraded:, unroutable:
                          and unaccounted: line, verbatim>
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
Conventions:   <N checked, N reused, N skipped (doc-only)> (or "none to check") — Step 2b step 3
Security map:  <N checked, N reused, N skipped (no map match)> (or "none to check") — Step 2b
               step 3b. Its own line, never folded into `Conventions:` above: a
               cycle where every target skipped the security twin and every
               target passed the convention check would otherwise read exactly
               like one where both fleets ran and both approved.
Test decisions: <N verified, N waived, N not-owed, N held-for-fix, N unreadable, N doc-only> (or "none to verify")
Also fixed:     <N branches carrying a section, N lines total across ALL its sections, N findings,
                N notes> (or "none") <and each check-1 `also-fixed note —` line, verbatim>
After merge:   <for each branch this close merged, each `## After merge` section Step 2d's
               `2‑after` read carried, verbatim, under `<TASK-ID> (<branch>):`> (or "none").
               Nothing for a branch that did not merge, whose PR this close did not see
               merge, or that Step 2a approved as landed.
               Steps a human runs now that the work has landed. Nothing checked them, and
               this close did not run them.
Close notes:   <N collected: N fixed at close (<fix-sha>), N filed (<ids>), N dropped,
               N not acted on (target did not merge)> (or "none") — Step 4 `4a-fix`.
               re-check <APPROVED | BLOCKED — dropped | not run: nothing fixed>
               <and `dropped after 4a-post failed` when that arm fired. A note
                listed for the human to file is not filed: say so.>
Orchestrator artifacts: <Step 2e's per-branch block, verbatim> (or "none — no branch
               under review resolved to a claim"). Distinct from `Claim artifacts:`
               below, which is Step 4c's REMOVAL tally: this line is Step 2e's
               pre-merge READ. It is a report — no line here moved a verdict, and an
               `absent` row means UNKNOWN, never that a stage was skipped, because
               sysop/runtime/ is gitignored and the hook is Claude Code only.
Staging:       <verified / skipped / broken>
Superseded PRs: <branch #PR, …> (or "none") — published branches whose own PR this
               close bypassed. Under `pr`: closed as unmerged by Step 6's branch delete,
               each carrying Step 4a item 3's comment. Under `direct`: GitHub marks them
               MERGED once Step 4d's push lands; list any Step 6 item 0 found still OPEN.
Closed-task edits: <each `<branch>: <path>` a person chose to merge at Step 4a item 1, and each
               `Rule B: <path>` at Step 4d's push> (or "none")
Squash provenance: <`pr` only: "recorded PR #N" | "not recorded — <error>"; each branch
               Step 2a approved as landed (`<branch> — PR #N`); each branch Step 4a
               printed `SKIP` lines for, rebased with `--onto` or merged on the published
               arm, and those lines; each line the published arm resolved to the
               target's side; each `not usable` line; each record made by hand>
               (or "none")
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
                                                              consolidation clause wrote one entry for many;
                                                              rotated out = the `ROTATED:` Step 4c item 5 printed)
  ✓ CHANGELOG.md:         <N> entries         (if any — count ALL THREE writers: the bugfix
                          routing row, the Consolidation clause, and the Rotation check. A count
                          taken from the routing table alone under-reports the other two.)
                          <and each `WARN:` line Step 4c item 5 printed — a forked heading the file
                           already had, for a human to merge>
  ✓ tasks/index.yml:      <the `CLOSED_IDS` Step 4c printed>  (if any — status flipped to done, body moved to archive/)
                          <and, when non-empty, `not in index: <NOT_IN_INDEX ids>` — ids this close was
                           asked to close and could not find. Never omit this line by choosing the other row.>
                          <and, when non-empty, `held (user_action): <HELD_USER_ACTION ids>` and
                           `held (hold:): <HELD_BY_HOLD ids>` — see Remaining. Any id on either row means
                           step 1c was skipped or its ids were pasted from a HELD: doc: an anomaly.
                           These four rows PARTITION the ids this close was asked to flip; if they do not
                           add up, the script did not finish and the rows above are incomplete.>
  ✓ UI_Iterations.md:     <N> rows            (if any)

Pending-doc collisions: <N> (or "none")
  - <filename> — the reason the collision line printed: main's copy authored by <branch>,
     worktree's by <branch>; or main's copy carries `hold:` and the worktree's does not. NOTHING was
     collected for the worktree's branch and main's copy was not touched; the branch is
     SKIP'd with its worktree, lock and branch intact. Both docs are still where their
     authors left them. Resolve by renaming one (for a dropped `hold:`, by adding it to the
     worktree's doc or clearing main's copy), then re-run; until then neither branch's task
     closes.

Stale pending-docs: <N> (or "none")
  - <filename> (<branch>) — <N> commit(s) landed after `branch_tip: <short SHA>`; the
     collect exited 6, so NOTHING was collected, main is untouched and the branch is
     SKIP'd with its worktree, lock and branch intact. Re-run /document-work on that
     branch to re-stamp it, then re-run the close.
     <one line per drifting commit, as the collect printed them>

Undocumented claims: <N> (or "none")
  - <branch> — claimed by <task id(s)> and no doc claims it; the collect exited 8, so
     NOTHING was collected, main is untouched and the branch is SKIP'd with its
     worktree, lock and branch intact. Run /document-work on that branch, then re-run
     the close.
     A branch with no workspace gets this row from the hand-applied test in Step 3b's
     `If WS is empty` paragraph, not from the collect.

Clone sync:    <Step 1-pre's lines and its CLONE SYNC: summary, which reads `0 line(s)` when
               no lock records a clone>

Arms:          <close_arms.py check's lines: ARMS:, each ARM NOT LOADED:, CORE:, LOADED:
               and SHARED:>

Ignored references: <N> (or "none")
  - <branch> — <path> (<file>:<line>), and the answer: committed to the branch at Step 2a
     step 3a (when its doc carries `branch_tip:`, re-run /document-work on it, then the
     close), kept ignored (copied to the main
     checkout), merged without it, the branch rejected, or unanswered (SKIP'd). A check that
     did not run: its error, and whether the human held the branch or merged without it.
  - <branch> — Step 3b step 0b's PRESERVED: lines and PRESERVE: summary (the files copied to
     sysop/runtime/preserved/<sanitized branch>/ before the worktree was removed), or its
     error and the SKIP it caused.

Claims unreadable: <N> (or "none")
  - <branch> — the collect printed `PENDING-DOC CLAIMS UNREADABLE:` for <the locks
     directory | a lock>; whether a task lock names the branch was not checked, and the
     branch was collected or refused on the rest of the evidence. Fix the permissions and
     re-check the claim by hand.

Open claims: <N> (or "none")
  - <task id> (<branch>) — the collect printed `PENDING-DOC OPEN CLAIM:`, or the no-workspace
     test found it. List it ONLY if the branch merged; drop it if the branch was SKIP'd.
     The task stays in_progress with its lock held, and once Step 6 runs the lock names a
     deleted branch. Intended for a partial merge. If not, the id was left out of the doc
     by mistake: close that task by hand.

Staleness not measured: <N> (or "none")
  - <filename> (<branch>) — <no `branch_tip:` | present but not a string | an
     unsubstituted placeholder | not an object name | does not resolve in the workspace>.
     The doc WAS collected and will route normally; only the currency check was skipped.
     A whole population reading this line every run means a writer is not stamping it.

Pending-doc write failures: <N> (or "none")
  - <filename> (<branch>) — the collect exited <5|7> because <the destination could not
     be created | the copy of <filename> failed: <error>>. On **7** stage 2 undid itself and
     main is as it was. On **5** the undo ALSO failed: main may be partially written, the
     displaced copies are preserved in the directory the `PENDING-DOC UNDO FAILED:` lines
     name, and they were restored by hand. **The rollback is run on neither** — it deletes
     by provenance rather than by what this run copied. Either way the branch is SKIP'd
     with its worktree, lock and branch intact. Fix the cause — usually an unwritable
     sysop/runtime/pending-docs/ — and re-run.

Quarantined docs: <N> (or "none")
  - <filename> — <no `branch:` frontmatter | frontmatter would not parse: <error>>;
     moved to sysop/runtime/pending-docs/quarantine/<filename>. Not routed, not deleted.
     No task IDs flipped. Recover by fixing the frontmatter and moving it back.

Held-back docs: <N> (or "none")
  - <pending-doc filename> — branch <name>; held because <reason>. Task IDs NOT flipped to
     done; doc left in place for a later run.
     **Two reasons, and they need different evidence — do not force one into the other's fields.**
     - 1b (unmerged): add `rev-list <count>, git cherry <count> unapplied`. Non-zero is the
       reason. (A doc can be held back WITHOUT a 4a-SKIP — a cherry-picked branch merges fine
       and still scores non-zero.)
     - 1c (`user_action outstanding: <TASK_ID>`, `hold: <reason>`, `shares <ids> with a held
       doc`, `held since <date>`): the evidence is the reasons the hold test printed, not
       `rev-list`, so omit the counts. A `NOT STAMPED:` note goes on the row too: `/document-work`
       does not protect an unstamped held doc. Add `branch retained by Step 6` so the two halves
       of the carrier are reported together.

Remaining:
  - <any SKIP'd branches — paused work; include file count + worktree path + recommendation,
     or, for step 0a's clone pre-check, the Step 1-pre line + its remedy>
  - <any 4a-SKIP'd branches — approved but did NOT merge; name the conflicting file or `CLOSED TASK EDITED:` path, and say
     the branch + lock are intact, its pending-doc was held back from consolidation, and its
     task was NOT flipped to done>
  - <any rejected branches with reasons>
  - <any tasks HELD on `user_action`. **There are two arms and they are not the same event.**
     ORDINARY (Step 1c): the doc was held back before routing, so `HELD_USER_ACTION` is
     `(none)` — the ids never reach the script — and the evidence is a `Held-back docs:` row
     reading `user_action outstanding: <TASK_ID>`. Say plainly what did and did not happen:
     the code merged, NOTHING was written for this task (no PROJECT_STATUS/CHANGELOG entry,
     no status flip), its body is still under `open/`, its lock is still held, and its branch
     was retained by Step 6's HARD RULE. Name the outstanding step from the body's
     `## User ops` section. ANOMALOUS (the script arm): `HELD_USER_ACTION` is non-empty,
     which means Step 1c did not run or the id list was substituted by hand from a stale run.
     Report it as an anomaly — the doc WAS routed, so entries landed for a task that did not
     close, and step 6 is about to delete that doc. Fix the id list.
     Either way the task closes on a later `/review-close`, after the human performs the step
     and clears the flag with `python3 sysop/scripts/clear_user_action.py <TASK_ID>`; the
     flag-clear alone closes nothing, and `clear_user_action.py` says so in its own output.>
  - <any docs HELD on `hold:` — same ordinary arm, same evidence, but the reason is the doc's
     own: name what `hold: <reason>` says is unfinished. The task closes on a later
     `/review-close` after the human finishes it and runs
     `python3 sysop/scripts/pending_doc_hold.py clear <TASK_ID>`. A doc held for both reasons
     needs both clears.
     **The invariant to check is the ordinary arm's:** every hold must show a
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

**Fill `Arms:` from the arm receipt**, with the close id `begin` printed written out:

```bash
python3 sysop/scripts/close_arms.py check "<close-id>" "${CLAUDE_SKILL_DIR}"
```

Carry every line it prints to `Arms:`. **Exit 1** names an arm that was due and never loaded: put each `ARM NOT LOADED:` line on `Remaining:` too, since the step it carries did not run as written. **Exit 2**: put its stderr on `Arms:` and on `Remaining:`, since the receipt could not be read.

If `$ARGUMENTS` contains `--prepare` or `--resume`, the section *`--prepare` and `--resume <run-id>`* (`steps/prepare-resume.md`) says which steps run.

If `$ARGUMENTS` contains `--dry-run`, run Steps 1, 2, 3 and 3c, run only step 0 of Step 3b, and report what *would* be done. Step 1b commits nothing, Step 2a step 3a neither commits nor copies, Step 3c records, files and drives nothing, and no step from Step 3b step 0b onward runs. A dry run still sweeps 1-pre's stale `refs/sysop/clone-sync/*` refs; runs all of Step 2b, which writes its runtime files, adds and removes its pinned checkouts, spawns its reviewers (whose harness can rewrite `core.hooksPath`, which 2b restores) and runs its HARD RULE cleanup; and fetches `origin/<default branch>` in Step 3c. **`4a-post` cannot run under `--dry-run`** — it needs the merges — so report the resolved command list and say the merged-tree gate did not run. Do not let Step 3's green stand in for it; that substitution is the defect the two-pass split exists to remove.
