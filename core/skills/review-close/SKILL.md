---
name: review-close
description: Senior review — review pending work, push to origin, verify staging, clean up
argument-hint: "[--dry-run]"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning inline=reasoning -->

Final gate before production. Reviews all pending work (feature branches AND unpushed main commits), pushes to origin, verifies staging, and cleans up.

## Pre-flight: Permission Guard

Before doing anything, verify `.claude/settings.json` carries the allow-rules this skill depends on. Under `permissions.defaultMode: "dontAsk"`, a missing rule on `git merge --ff-only` or `git worktree remove` surfaces as an opaque halt mid-merge. Run the `_shared/permission-guard.md` algorithm — including its **step 3 mode check**, which skips the hard stop (but still prints the drift report) when the project declares `bypassPermissions`, where the allow-list is inert.

Read `.claude/settings.json` (and `.claude/settings.local.json` if present) and confirm `permissions.allow` satisfies every rule below:

- `Bash(git checkout:*)`
- `Bash(git fetch origin:*)` — the `_shared/main-push-guard.md` Rule B safe-push sequence fetches `origin/main` before the Step 4d push, so this is required under **both** merge policies, not just `pr`
- `Bash(git rebase:*)`
- `Bash(git rebase --abort)`
- `Bash(git merge --ff-only:*)`
- `Bash(git worktree list:*)` — Step 1a + Step 3c's `--porcelain` worktree enumeration (the one read-only `git` form Sysop ships a rule for — see `_shared/permission-guard.md` § Notes)
- `Bash(git worktree remove:*)`
- `Bash(git branch -d:*)`
- `Bash(git push origin:*)`
- `Bash(git add:*)` — Step 4c step 7's shared-doc staging. Those are three plain, unwrapped `git add <path>` commands, which is what makes the wildcard the right shape here: the literal-path rules the template also ships (`git add tasks/index.yml`, `git add review_tasks.md`) cannot cover consumer-authored doc names like `changelog.md`. Note the review skills' Step 9 staging is **not** an exception any more: Phase 153 unrolled those loops into one plain `git add -A -- <path>` per path, so `Bash(git add:*)` covers them too. The shapes that still bind no rule are this skill's own runtime-set loops; see § Invocation shapes below
- `Bash(bash sysop/scripts/close_batch.sh:*)`
- `Bash(bash sysop/scripts/run_checks.sh)`
- `Bash(bash sysop/scripts/run_checks.sh:*)`
- `Bash(python3 -:*)` — Step 3c's smoke-gate detection heredoc **and** Step 4c's yaml-round-trip status flip + git mv + the `git add` of the index it rewrote (those git calls run *inside* the heredoc via `subprocess`, so they bind no Bash rule of their own). Both are single `python3 - <<` commands (literal `python3` command word, no PATH prefix or `&&` compound) so this one rule matches; venv PyYAML is resolved by an in-heredoc `sys.path` bootstrap, not a `.venv/bin/python3` invocation or an env prefix (BeanRider ISSUE-0049; Sysop Phase 126 — a `.venv/bin/python3` command word or a `VAR=… python3` prefix would each bind to no rule)
- `Bash(python3 sysop/scripts/validate_tasks.py)` — Step 4c's final-guard validator run (bare `python3`; the script self-resolves venv PyYAML via its own `sys.path` bootstrap, so this one form serves both venv-only and non-venv consumers — Sysop Phase 126)
- `Bash(python3 sysop/scripts/validate_tasks.py:*)` — same with `--quiet` / `--path`

**Deliberate non-entries.** Step 3b's pending-docs collect (`mkdir -p sysop/runtime/pending-docs && cp …`) ships with **no** allow-rule — the compound splits into `mkdir` + `cp` command words (Phase 126 matcher facts) and neither binds a rule here. On purpose: both are plain intra-repo file writes the auto-classifier has allowed in every live run to date (the bare `cp` shipped ruleless for as long as the step has existed), and a `Bash(cp:*)`-class rule would pre-authorize far more than this one copy. If the collect ever *does* halt there, the Phase 36 `PermissionDenied` hook surfaces the `!`-escape form — run it before continuing; Step 3b itself forbids proceeding to the worktree remove with the docs uncollected.

**Additionally, under `pr` merge policy only** (read `<project>/CLAUDE.md § Merge policy`; default is `direct` — see Step 4-pre): the PR-routed flow shells out to `gh` and a few extra git verbs. Require these too **only when the policy is `pr`** — a `direct`-policy consumer does not need them and must not be blocked for their absence:

- `Bash(git cherry-pick:*)` — Step 4-pre sweeps local-only `main` commits onto the integration branch
- `Bash(git reset --hard origin/main)` — Step 6 re-syncs local `main` after the PR squash-merges
- `Bash(git branch -D:*)` — Step 6 deletes the integration + squash-merged feature branches
- `Bash(gh pr list:*)` — Step 4-pre's PR-reuse probe (`gh pr list --head … --base main --state open`)
- `Bash(gh pr create:*)` — open the integration PR against `main` (integration-branch shape only; the PR-reuse shape never calls it)
- `Bash(gh pr checks:*)` — wait on the PR's required checks
- `Bash(gh pr view:*)` — read the PR's merge state
- `Bash(gh pr merge:*)` — squash-merge the integration PR (non-`--auto`)

Every rule named above ships in the installer's seeded allow-list, so a consumer who ran `bash install.sh` (or `sysop-update.sh` at Phase 152 or later) satisfies this block on a fresh install under either policy. **A consumer whose skills are newer than their `settings.json` will not** — skill copies auto-update through the plugin path while the allow-list ships only through the installer, so if this block reports a rule you have never seen, run `sysop-update.sh` rather than hand-editing.

**§ Invocation shapes — keep the `pr` path rule-matchable.** A rule authorizes a *command*, not a *step*: the matcher compares against the literal text the model sends, splits on `&&`, `||`, `;`, `|`, `|&`, `&` and newlines, and requires each part to match. Until Phase 153 this skill's `pr` path defeated its own rules in three places — `PR_NUMBER="$(gh pr list …)"` and `PR_REF="$(gh pr create …)"` (a rule does not match past a variable assignment) and two `|| true` tails (`true` is not in the documented read-only set, though that set is documented as non-exhaustive, so this one is a strong inference rather than a stated fact). Those are now invoked bare, with the PR number and integration-branch name as quoted literals. **When editing Step 4-pre, 4d or 6, do not reintroduce them:** no capture into a variable, no `|| true` (use `|| echo …` — `echo` *is* in the documented read-only set), and no `for … done` around a set you could write out.

**What this block does NOT claim.** Two shapes remain and are not defects introduced here. First, this skill still runs `for … done` loops over sets discovered at runtime — the Step 4a branch pre-check (`$BRANCHES_TO_MERGE`) and the Step 3b pending-docs strip (a `*.md` glob, which additionally wraps `rm -f` behind `[ -e … ] &&`). A glob-driven loop cannot be unrolled, so reshaping is not available there; the branch-check loop holds only read-only commands, the Step 3b one does not. Second, the reshaped `gh pr list` commands carry a `|` inside a single-quoted `--jq` argument, and whether the splitter is quote-aware is an open question the docs do not settle. So this block asserts that three *provable* defeaters are gone, not that every `pr`-path invocation is proven to bind. See `WORKFLOW.md` § 8.2a *Invocation shapes* for the full inventory. If any required rule (the always-required git set above, plus the `gh`/git set when the policy is `pr`) is unsatisfied, stop with the error message from `_shared/permission-guard.md` § Algorithm step 5 (substitute "merges approved feature branches and either pushes `main` directly or — under `pr` policy — assembles an integration branch and opens a squash-merge PR; updates `tasks/index.yml` via heredoc'd python and runs the validator as a final guard" as the one-line reason). Do not proceed — unless the guard's step 3 mode check applies.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and continue.

## Step 1: Gather State

Run these in parallel:
- `git branch -a` — all local and remote branches
- `git log --oneline origin/main..HEAD` — unpushed commits on main (if on main)
- `git branch --list | grep -v main` — local feature branches
- `git stash list` — any stashed work that might be forgotten
- `git worktree list --porcelain` — all worktrees (porcelain form is stable across git versions; consumed by Step 1a)

Identify two categories of pending work:
1. **Feature branches** — any non-main local branches (especially those marked `review_ready`)
2. **Unpushed main commits** — commits on main that are ahead of `origin/main`

### 1a. Classify Worktree State (silent-data-loss guard, BeanRider ISSUE-0016)

Branch tips are blind to uncommitted in-progress work. A `/claim-task`-ed branch where the agent did substantial worktree edits but never committed has a tip identical to a freshly-claimed branch with no work yet — Step 2a's commit-based verdict would say "no commits, reject" for both, and Step 6's cleanup would then try to remove the worktree. If a downstream codepath ever reaches for `--force` on `git worktree remove`, uncommitted work is silently destroyed. **No shipped skill does today** — no skill in this install contains `git worktree remove --force`, and the only forced removals anywhere are the opt-in `--force` arms of `claim_task.sh --release` and `batch_work.sh --release` (an earlier version of this sentence attributed such paths to `/auto-judge` and `/document-work`, which have none; corrected Phase 165, the same wrong-capability class as `/auto-build`'s "clears the lock" claim). The guard below is what keeps it that way.

For every worktree from `git worktree list --porcelain` (excluding the worktree whose branch is `main`), classify the state by running `git -C <worktree-path> status --porcelain` and combining with the branch's commit position relative to main:

```bash
# Use --porcelain to make the worktree listing machine-parseable.
# repo_root is the primary (main) worktree — the runner's vantage — and owns the
# .gitignore rules the symlink downgrade below consults (BeanRider ISSUE-0043).
repo_root=$(git rev-parse --show-toplevel)

git worktree list --porcelain | awk '
  /^worktree / { path = $2 }
  /^branch /   { br = substr($2, length("refs/heads/") + 1); print path "\t" br }
' | while IFS=$'\t' read -r wt_path branch; do
  # Skip the main worktree (it's the runner's vantage; not a feature worktree).
  [[ "$branch" == "main" ]] && continue

  porcelain=$(git -C "$wt_path" status --porcelain)
  ahead=$(git log --oneline "main..$branch" 2>/dev/null | wc -l | tr -d ' ')

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
        git -C "$repo_root" check-ignore -q "$target" 2>/dev/null && continue
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
ADDED=$(git diff --numstat HEAD -- review_tasks.md | awk '{print $1+0}')
DELETED=$(git diff --numstat HEAD -- review_tasks.md | awk '{print $2+0}')

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
BRANCHES_TO_MERGE=$(git for-each-ref --format='%(refname:short)' refs/heads/ | grep -v '^main$' | grep -v '^worktree-agent-')

for branch in $BRANCHES_TO_MERGE; do
  base=$(git merge-base main "$branch")
  # Did main touch an archive file since this branch was cut?
  if git diff --name-only "$base..main" -- | grep -qE "$ARCHIVE_RE"; then
    echo "WARN: $branch was cut before an archive rotation on main;"
    echo "      Step 4a's rebase will likely conflict on review_tasks.md."
    echo "      Resolve per Step 4a guidance, or skip this branch this cycle."
  fi
done
```

This is a **soft warning, not a hard gate** — informational only. The agent proceeds to Step 2 regardless; Step 4a's updated prose handles the actual conflict if it materializes. Hard-gating here would block legitimate close-outs whose conflict turns out to be trivial (single-line checkbox flip rebasing onto a slightly-shifted layout). If the warning fires repeatedly for a branch and the resolution is consistently expensive, that's project-side friction worth logging via Step 7's friction capture.

If `$BRANCHES_TO_MERGE` is empty (only unpushed main commits this cycle), Step 1c is a no-op — skip cleanly.

## Step 2: Review Pending Work

### 2a. Feature Branches

For every non-main local branch — excluding any **agent worktree branch** (a branch whose registered worktree lives under `.claude/worktrees/`; on Claude Code these are named `worktree-agent-<id>`). Those are review sub-agents' scratch checkouts, not anyone's feature work; Step 2b's HARD RULE covers removing leaked ones. Do not review, approve, reject, or merge them:

0. **Worktree-state pre-check (Step 1a result).** If Step 1a classified this branch's worktree as `dirty`, the verdict is **SKIP — paused work present**. Do NOT inspect the diff and do NOT propose approve/reject — uncommitted worktree changes mean the branch is mid-implementation, not in a reviewable state. Report the dirty file count and the recommendation: *"`<N>` pending changes in `<worktree-path>`. Commit-as-WIP, stash, or leave alone — re-run `/review-close` after the user decides. This branch is excluded from Step 3b (worktree removal), Step 4 (merge), and Step 6 (cleanup) for this run."* Then continue to the next branch. A SKIP'd branch is distinct from both `approve` and `reject`: it is not merged, but its worktree, lock, and branch are all preserved untouched.

1. `git log main..<branch> --oneline` — what commits are on it
2. `git diff main...<branch> --stat` — scope of changes
3. Read the diff. Check for correctness, security issues, and alignment with the task body — path from `tasks/index.yml`'s `body:` field for each task ID the branch claims (a claim does **not** move the body, and there is no `tasks/in_progress/` directory in any shipped layout, so it stays where it was written — normally the file `tasks/open/<TASK_ID>.md`, which `body:` records canonically as `open/<TASK_ID>.md`, relative to `tasks/` — until Step 4c's archive move). Read it **at the branch tip**, per Step 2d's revision note: a branch edits its own body, and the working tree is still `main`.
4. Verdict: **approve** (merge to main) or **reject** (report reason, leave branch)

> **Three dots on every `git diff` in Step 2 — 2a, 2b and 2d (upstream #241).** `git diff main..<branch>` compares the two *tips*, so everything `main` gained after the branch was cut renders as though the branch **deleted** it. That is not a rare condition: `/review-close` manufactures it, because Step 1b commits `review_tasks.md` to `main` before any branch is inspected. `git diff main...<branch>` diffs against the merge-base and shows exactly what the branch contributed. A false BLOCK costs a human round-trip; a **false APPROVE** — real hunks buried under phantom deletions — is the worse direction and gets likelier the staler the branch is. **`git log main..<branch>` keeps two dots**: for `log`, two-dot already means "commits on the branch and not on `main`," which is what step 1 wants. The rule is per-command, not a blanket search-and-replace.

### 2b. Prevention Convention Check

**Targets.** One agent per **approved-or-rejected** feature branch, plus **one for the unpushed-main commits as a group** if there are any. A branch Step 2a classified **SKIP — paused work present** is *not* a target: it is not merging this run, and a `VERDICT: BLOCKED` on it would halt the close over work already declared out of scope. These calls can be parallelized — launch one agent per target simultaneously.

Each target has a **diff basis**, used identically by step 0's predicate and step 1's retrieval:

| Target | Diff basis |
|---|---|
| feature branch `<branch>` | `git diff main...<branch>` |
| unpushed-main group | `git diff origin/main...HEAD` |

If the repo has no `origin` remote, or `HEAD` is not `main`, there is no unpushed-main group — skip that target rather than running a command that will fail or silently diff something else. (Step 1's `git log --oneline origin/main..HEAD` is already qualified "if on main"; this is the same condition.)

**0. Per-target doc-only skip (upstream #240).** Compute the target's diff basis first. If it touches **no** code files (the same code-file set Step 3 uses — `.py` / `.ts` / `.tsx` / `.js` / `.jsx` / `.sql` / `.sh` / `.kt` / `.swift` / `.go` / `.rs`) **and** the project's `## Prevention Conventions` contain no rule that governs the file types the diff *does* touch, skip the agent for that target with a one-line note (`2b: <target> — doc-only diff, no code-convention surface`). Docs-only cycles are not an edge case here — Step 7's own friction capture generates them routinely.

> **Check the second condition; do not assume it.** "Docs cannot violate a convention" is false often enough to be dangerous, and Sysop's own shipped maps are the counter-examples: `core/companion/convention_map.md` routes `.claude/skills/**/*.md` to five conventions including *No secrets in examples*; the beancount pack routes a per-vendor `README.md` to **"Synthetic content only: NO real account numbers, payees, amounts, addresses"** and `<ledger>.beancount` to *No PII in git-tracked ledgers*; the llm pack routes `<prompts dir>/**/*.md` to template rules. **None of those is scanner-shaped** — the beancount rule asks a reader to judge whether a digit string *looks* real, which no entropy or pattern scanner does. So the skip is licensed by the *absence of an applicable rule*, not by the file extension. Read the conventions section (you need it for step 1 anyway), and if any subsection names documentation, config, prompts, fixtures, or committed data, **do not skip** — spawn the agent and let it route. Secret-scanning (`security_map.md` routes root operational docs to **A02**) is a separate expectation covered by the project's scanner, and this skip neither touches nor waives it.

Step 2a still reads the diff either way. If every target skips, Step 2b is a clean no-op; say so in one line rather than reporting nothing.

**For each remaining target:**

1. Read the **entire** `## Prevention Conventions` section of `CLAUDE.md` (every subsection — subsection names vary by project: a web project might have `Frontend`/`Backend`/`Testing`; a data-pipeline project might have `Data integrity`/`Privacy`/`Testing Patterns`; an MCP server might have `MCP server boundaries`). Retrieve the full diff — the target's **diff basis** from the table above, three dots, per Step 2a's note. This text is pasted verbatim into the prompt below, so a two-dot diff hands the reviewer `main`'s newest content as though the branch had torn it out.

2. Spawn an Agent with:
   - `subagent_type: "general-purpose"`
   - `model: "opus"` (always — the **reasoning** role: adversarial convention review; do not omit, per `.claude/served_models.yml`)
   - `isolation: "worktree"` — give each agent its own checkout (upstream #234). Steps 2a–2d run in the user's **primary** worktree, which has a single `HEAD`; a full-tool agent that decides to compare two revisions will reach for `git checkout` unless something stops it, and in a real run one did, moving `HEAD` off the branch the close was working on. Step 4's HARD RULE already names this hazard but frames the actor as *external*; here it is this skill's own agents, spawned two steps earlier. (The reported run had an integration branch checked out at 2b, which this skill's step order does not produce — 4-pre cuts it two steps later — so read the incident as "off the expected branch", not as evidence about which branch that is. What the misplaced commit would have cost also depends on policy: Step 6 deletes a merged feature branch with a safe `git branch -d`, and force-deletes only the integration branch under `pr`.) Isolation is available here because these agents have **no** pre-existing worktree, so `_shared/adversarial-review.md` § *Running more than one reviewer* applies directly — its "do not use it where a worktree already exists" caveat is about `/claim-task`, `/auto-build`, `/auto-fix` and `/auto-judge`, which spawn into a worktree an earlier step created, not about this step. **Where the harness offers no isolation parameter, the prompt's do-not-mutate rule below is the portable floor** and is sufficient; isolation is the structural hardening on top of it, not a replacement.
   - `description: "Convention check: <target>"`
   - `prompt`:

     ```
     You are the final security gate before this branch merges to production. Review
     the diff below for violations of the project's Prevention Conventions.

     ## Target
     <branch name, or "unpushed main commits">

     ## Diff
     <full unified diff from the target's diff basis>
     (Merge-base-relative — this is what the branch ADDED, not a tip-to-tip
      comparison. Context you cannot see is context `main` already has; it is
      never a deletion this branch made. Do not report missing content as
      removed.)

     ## Prevention Conventions
     <paste the full ## Prevention Conventions section from CLAUDE.md verbatim,
      including every subsection — do not pre-filter or rename subsections>

     ## Instructions
     For each changed file, scan the Prevention Conventions section above and
     identify which subsection(s) apply, based on file path, language, and
     domain. A subsection applies when its bullets reference concepts the file
     touches — for example:
     - parsers/<format>.py → "Data integrity" + "Testing Patterns"
     - mcp_server/tools/*.py → "MCP server boundaries"
     - frontend/components/*.tsx → "Frontend" / "UI components"
     - api/routes/*.py → "Backend" / "API endpoints"

     Subsection names vary by project — discover them from the pasted section,
     don't assume a fixed taxonomy.

     For each changed file, list the subsections you routed it to (one line:
     `<file path> → <subsection names>`), then check each applicable bullet
     against the diff hunks.

     Return your findings in exactly this format:

     ROUTING:
     - <file path> → <subsection name(s)>
     (one line per changed file)

     VERDICT: APPROVED
     (if no violations)

     OR

     VERDICT: BLOCKED
     Violations:
     - <Convention bullet name> (<subsection>) — <file>:<line> — <one-line explanation>
     (one line per violation)

     Be thorough. A missed convention ships a security hole or reliability bug to prod.
     The ROUTING block is required so the human reviewer can audit which subsections
     you considered for each file.

     Do NOT mutate repository state — no `git checkout`, `switch`, `reset`, `stash`,
     `merge`, `rebase`, `add`, or `commit`, and no edits to tracked files. A close is
     in flight; moving `HEAD` corrupts it. The diff above is everything you need. If
     you need more context, read it with `git show <sha>:<path>`, which reads the
     object database and is unaffected by tree state.
     ```

3. Collect all verdicts. If **any** subagent returns `VERDICT: BLOCKED`, list every violation with its file:line citation and **stop** — do not proceed to Step 3 until violations are fixed or explicitly waived by the user. A target skipped at step 0 has **no verdict** — report it as `skipped (doc-only)`, never as `APPROVED`; an agent that was never spawned has approved nothing.

4. **Record outcomes for Step 8.** Tally `<N checked, N skipped (doc-only)>` for the `Conventions:` line in the final report. Without this, a skip is invisible in the artifact the human reads — the same gap Step 2d's `N doc-only` tally closes for test decisions.

> **HARD RULE — the agents' worktrees must be gone before Step 3b.** Worktree isolation is not free of side effects: on Claude Code it materializes a **real worktree and a real branch** in this repository's shared namespace (observed shape: a worktree under `.claude/worktrees/` on a branch named `worktree-agent-<id>`). The harness removes them when an agent finishes and left its checkout unchanged — but an agent that wrote a scratch file, or a run that was interrupted, leaks both. **That collides directly with this skill**: Step 1c's `git for-each-ref refs/heads/` sweep, Step 2a's "every non-main local branch", and Step 1a's worktree classification all enumerate whatever exists, so a leaked agent branch is reviewed as though it were someone's feature work — it classifies `clean-merged`, Step 2a finds no commits, and Step 6 offers to delete it. Worse across sessions: a *concurrent* `/review-close` can reach `git worktree remove` on a checkout an agent is still running in.
>
> After step 3 collects the verdicts, assert both are clean before continuing:
>
> ```bash
> git worktree list --porcelain | grep -F '/.claude/worktrees/' || echo "no agent worktrees"
> git for-each-ref --format='%(refname:short)' refs/heads/ | grep '^worktree-agent-' || echo "no agent branches"
> ```
>
> Anything listed is a leak: remove the worktree (`git worktree remove <path>`) and delete the branch (`git branch -D <name>`) before Step 3b. **Do not skip this because the harness usually cleans up** — "usually" is what makes the residue arrive on a later run, attached to nobody, in a step that force-deletes branches. If your harness offers no `isolation` parameter, none of this applies: you are relying on the prompt's do-not-mutate rule, which is the portable floor.

### 2c. Unpushed Main Commits

If main is ahead of origin:
1. `git log --oneline origin/main..HEAD` — list the unpushed commits
2. Review each commit's changes: `git show --stat <hash>` for each
3. Verify the changes look intentional and complete (no half-finished work, no debug code left in)
4. Check that documentation is accounted for: either `docs:` prefixed commits exist (legacy) or `sysop/runtime/pending-docs/*.md` files are present (current workflow)

### 2d. Test-Decision Verification (verify the record — Phase 59, C1)

Every task claimed through `/claim-task` records a **test decision** in its body at plan time (Phase 58b): either `test <X> proves <Y>` (the regression test that pins the changed behavior) or `no test because <Z>` (the reviewable rationale for adding none). See `tasks/schema.md` § Test decision. This step **verifies that record against what the branch actually delivers** — the read-and-verify gate that closes the loop the validator's warn-only Invariant 13 opens at plan time. It does **not** re-judge whether a test *should* exist; that judgment is the adversarial plan reviewer's "Missing invariant tests" dimension (`_shared/adversarial-review.md` finding #7), applied at plan time. Verify the record, don't re-judge.

This is the sibling of Step 3c's manual-smoke gate — a per-task body convention, warned by the validator, enforced here — and reuses the same shape: a deterministic classification (like Step 1a's worktree verdict) plus an `AskUserQuestion` halt on mismatch (like Step 3c).

For each **approved** feature branch (Step 2a verdict), for each task ID it claims (path resolved exactly as in Step 2a step 3 — `tasks/index.yml`'s `body:` per claimed ID):

> **Read the record at the branch tip — not out of the working tree.** `/claim-task` *decides* the test decision at plan time, but the **executor writes it into the body during implementation, inside the worktree** (`claim-task/SKILL.md` Step 7e, Sequence item 3), so the section is committed on the feature branch and nowhere else. Step 2d runs at Step 2; nothing merges until Step 3b/4a. `HEAD` is still `main`, so the working tree's copy of the body is whatever `main` has — and for a task claimed this cycle that copy carries **no test-decision heading at all**, because every shipped body-author is told not to write one (`intake/SKILL.md:111`, `add-task/SKILL.md:62`, `onboard/SKILL.md:95`; the schema's placeholder is a template, not something a real body normally holds). Reading *that* copy therefore classifies the record `missing` for every task on every code-touching branch on every run — step 0's doc-only skip is the only thing that spares one — and each `missing` fires the halt below. A gate that only ever reports the state of a revision it is not gating. Resolve the *path* from `main`'s `tasks/index.yml` — correct, because a claim does not move the body and Step 4c's archive move runs after this step — and read the *content* from the revision under review:
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
> **Getting that prefix wrong is not a cosmetic slip** — it produces `fatal: path … does not exist`, which is exactly the `unreadable` signature below, so a mis-resolved path halts the close wearing a diagnosis that blames the branch. Check the recorded `body:` value before concluding anything from a fatal. This is the object-database read Step 2b's prompt already prescribes, and it is the same revision `git diff main...<branch>` reports — both halves of this gate must come from one revision, or the comparison is between two different trees. `WORKFLOW_GUIDE.md` § Merge Process already says to read "**the branch's** `## Test decision`" back against the diff, so the branch-tip read restores the spec rather than inventing a rule; `WORKFLOW.md` § 2.8 ("each approved branch's task body") scopes *whose* body rather than *which revision*, so it is consistent with that reading without compelling it.

**0. Per-branch doc-only skip.** If this branch's diff (`git diff main...<branch>` — three dots, per Step 2a's note) touches no code files (the same code-file set Step 3 uses — `.py` / `.ts` / `.tsx` / `.js` / `.jsx` / `.sql` / `.sh` / `.kt` / `.swift` / `.go` / `.rs`), skip verification for it with a one-line note (`2d: <branch> — doc-only diff, no test decision to verify`). A test decision over a doc-only change is incoherent — there is no behavior to pin.

**1. Read the record.** Read the body **at the branch tip** (`git show "<branch>:<repo-root-relative body path>"`, resolved and quoted per the note above — never the working-tree copy) and find the section under a heading whose text matches `test\s+decision` (case-insensitive — `## Test decision`, `### Test Decision` both match; same pattern as validator Invariant 13). Classify it:

- **`test-proves`** — the section names a test (the `test <X> proves <Y>` shape).
- **`no-test`** — the section states `no test because <Z>`.
- **`missing`** — no test-decision heading **at the branch tip**, or the section still holds the schema template placeholder (`<recorded at /claim-task plan time …>`).
- **`unreadable`** — `git show` reports the path does not exist at the branch tip (`fatal: path '…' does not exist in '…'`). **Before believing it, re-check the `tasks/` prefix rule above — a mis-resolved path produces this identical fatal, and that is the likelier cause.** Genuinely reachable when the claim reused a pre-existing branch cut before the body file was written, since `claim_task.sh` reuses an existing branch rather than refusing. **This is not `missing`:** nothing has been asserted about the record either way, and reporting it as `missing` would put a fabricated finding in front of the human. Surface the branch, the path you resolved, and the revision you read.

**2. Verify the record against the branch diff:**

- **`test-proves` → "plan said test X — is it here?"** Confirm the diff adds or modifies a test matching X — a changed file on the project's test path (`tests/`, `*_test.py`, `*.test.ts`, `*.spec.ts`, or the project's documented test location) and, when X names a specific test/function, that name appearing in the diff. If the diff touches **no** test file at all, the record claims a test that wasn't delivered → **discrepancy**. (Record-vs-reality only: a test that is present but weak is out of scope here — that's the reviewer's coverage judgment, not this gate's.)
- **`no-test` → "plan said no-test-because-Z — does Z still hold?"** Re-read `Z` against the diff. `Z` **holds** when the diff's character still matches the stated rationale (pure rename/move, config-only, docs-only, covered by an existing named test, `manual_smoke:`-only). `Z` is **stale** when the diff now carries behavior changes the rationale didn't anticipate (e.g. `Z` said "pure rename" but the diff edits logic) → **discrepancy**. This carries inherent judgment residue — acknowledged and bounded: you are matching the recorded rationale to the diff, **not** forming a fresh opinion that a test ought to exist.
- **`missing` → record absent.** Invariant 13 already warned at validation time; the gap now reaches the merge gate → treat as a discrepancy to surface.

**3. On a clean match, pass silently** (carry a `verified` note for Step 8). **On any discrepancy, missing record, or unreadable body, halt and ask** via `AskUserQuestion` (one task at a time, mirroring Step 3c). Present the recorded decision text verbatim, the task ID, **the revision you read it from**, and what the diff shows. Three options (single-select):

- **"Record holds — proceed"** — the human confirms the record is accurate or the rationale still applies; the branch stays approved.
- **"Hold for fix — don't merge this run"** — demote this branch from **approved** to **rejected** for this run, with the reason `test-decision record needs fixing — <detail>`. Downstream steps already handle a rejected branch correctly with no special-casing: Step 3b/Step 4 skip it (only approved branches merge), Step 6 leaves its worktree, lock, and branch intact for follow-up, and Step 8 reports it under "Remaining" with the reason. The test can then be added or the record corrected before a later `/review-close`.
- **"Waive — proceed with noted waiver"** — the branch stays approved; record a waiver (task ID + decision text) for Step 8. Use for accepted judgment calls (e.g. a stale-looking `Z` the human confirms is fine).

Waivers and "record holds" do not block. Only "hold for fix" changes the verdict, and it does so by reusing the existing **reject** disposition — no edits to Steps 3b/4/6 are needed.

**4. Record outcomes for Step 8.** Tally per task: `verified`, `waived`, `held for fix` (now rejected), `unreadable`, or `skipped (doc-only)`. This drives the "Test decisions" line in the final report.

If the approved-branch set is empty (only unpushed main commits this cycle), Step 2d is a no-op — unpushed main commits don't carry `/claim-task` test-decision records. Skip cleanly.

> **For new projects:** the test decision is authored at `/claim-task` Step 6 into the task body (`tasks/schema.md` § Test decision). This gate reads it back — keep the `Z` in a `no test because Z` rationale concrete so "does Z still hold?" stays answerable.

## Step 3: Run Verification

**This is the pre-merge pass, and it can only verify the tree it runs on.** `HEAD` is still `main` here — Step 3b has not removed a worktree and Step 4a has not merged anything — so no approved branch's files are in this working tree and its new tests do not exist yet. What this pass verifies is *this* tree: `origin/main` plus whatever local-only commits `main` already carries. It is a fail-fast on the base, and it is the last point where stopping is free. **It is not a verdict on the work, and nothing here may be reported as having verified a branch** — that verdict is `4a-post`, which re-runs the same resolved list on the merge target once the branches are merged.

**Each pass scopes itself to its own tree, with one command.** Item 3's surface gate and item 4's doc-only skip both read the list this prints:

```bash
# The changed-file list for THIS pass, read off stdout. Three dots, always — two would
# render everything the base gained since a branch was cut as though the branch deleted
# it (the Step 2a note). Run from the repo root.
git rev-parse --verify --quiet origin/main >/dev/null \
  && git diff --name-only origin/main...HEAD \
  || echo "NO_ORIGIN_MAIN"
```

On this pass `HEAD` is `main`, so the list is main's local-only commits — the `open → in_progress` claim flips and any Step 1b `review_tasks.md` save — and that population is exactly what this pass is entitled to verify. At `4a-post` the identical command runs on the merge target and returns the whole assembled diff. **If it prints `NO_ORIGIN_MAIN`** (no `origin`, or a remote whose default branch is not `main` — verified: the diff alone exits 128 with `fatal: ambiguous argument`), there is no changed-file list: **gate nothing and skip nothing — run the full resolved list.** A scope you could not compute must never silently narrow the gate.

**An empty list is a real outcome here, and it is the one to report rather than pass over.** On a `main` already level with `origin/main` this command prints nothing, so a `### Ratchet` snippet filtering it short-circuits on every filter and the pass reports green having executed nothing at all. That is *correct* — there is nothing on this tree the base has not already seen — but "green" and "ran nothing" must not read the same, which is why Step 8's `Verification:` line carries the reason, not just the verdict.

Now discover the project's verification commands. Resolve in this order — stop at the first source that produces a command list:

1. **`<project>/CLAUDE.md` § "Pre-merge verification"** (preferred — the project owns its command list). Two shapes are supported:
   - **Split sub-headings (recommended).** If the section uses `### Always` and/or `### Ratchet (changed files only)` sub-headings, run them in that order:
     - **`### Always`** — full-tree commands run unconditionally (build, full test suite, project-level smoke tests). Bullet list; one command per bullet.
     - **`### Ratchet (changed files only)`** — project-supplied shell snippets in a single bash code block. Each snippet is expected to filter `git diff --name-only origin/main...HEAD` to its file-type of interest and invoke lint/typecheck against only the changed files. Run the block as-is from the repo root. A snippet whose filtered changed-file list is empty short-circuits and passes — that's project-side logic, not a Sysop rule. Treat the snippets as project-trusted input — they run with full agent shell privileges. If you didn't write them yourself, read the block before running it.
   - **Flat list (backward compatible).** If neither sub-heading exists, treat all bullets under `## Pre-merge verification` as the `### Always` list and skip the ratchet step.
2. **`package.json` `scripts.verify`** (if `package.json` is at the repo root or `<frontend>/`). If at repo root, run `npm run verify`. If at `<frontend>/`, run `(cd <frontend> && npm run verify)` from the repo root.
3. **Auto-detect from common surfaces** — each command gated on its own surface appearing in this pass's changed-file list (upstream #206). A surface being *present* says the project has one; it does not say this run *touched* one, and running a full frontend build for a diff of Python scripts is the cost that makes skipping tempting — and the skip is then a judgement this step never authorized, so it gets made silently.
   - `frontend/` exists with `package.json` → `cd frontend && npm run build && npm run test` — **only if** the changed-file list contains a path under `frontend/`
   - `pyproject.toml` exists with `pytest` declared in `[project.optional-dependencies]` (any extra) → `python -m pytest tests/` — **only if** the list contains a Python file
   - `Cargo.toml` exists → `cargo test --release` — **only if** the list contains a Rust file or `Cargo.toml`
   - Other detectable surfaces → run the platform-native test/build command, under the same rule: only if the list contains a file that surface owns.

   **A surface absent from the changed-file list is `skipped`, not `failed`.** Record it on Step 8's `Verification:` line (`skipped frontend — not in this run's changed files`). That is what makes the skip *authorized* rather than improvised. It does not license the inverse: do not decide by hand to skip a surface the list does touch.

   **Then report every changed code file that no detected surface claimed** — Step 8's `Unverified surfaces:` line. Surface-gating narrows the gate, so what it cannot account for has to become visible rather than disappear; a `.sql` migration or a `.go` service in a repo whose only detected surfaces are `frontend/` and `pytest` is verified by nothing, and that was true before this gate existed too. The fix is consumer-side and is one heading away: a `## Pre-merge verification` section is **never** surface-gated, because there the consumer said what to run.
4. **If the diff is doc-only** (no `.py` / `.ts` / `.tsx` / `.js` / `.jsx` / `.sql` / `.sh` / `.kt` / `.swift` / `.go` / `.rs` files changed — only `.md` / `.txt` / `.yaml` config / etc.): skip verification with a one-line note (`Step 3: skipped — diff is doc-only`). **"The diff" is this pass's changed-file list, never the run's.** The two passes compute it the same way on different trees, so each decides its own skip: `4a-post` is never skipped because Step 3 was, and Step 3's skip is not evidence about any branch. On the common cycle this pass *does* skip — a claim flip and a `review_tasks.md` save are the whole of main's local-only diff — which is why the pre-merge pass costs almost nothing and why nothing may be concluded from its green. Step 4 (push) still runs. This skip applies to both `### Always` and `### Ratchet` — a doc-only diff can't regress code-level lint/typecheck.
5. **If none of the above fire and the diff touches code**: stop and ask the user what to run. Do not invent commands. Do not run `pip install` or any state-mutating command during verification — verification is read-only.

**The item-5 stop is about the run, not about this pass — resolve before you skip.** Item 4 decides whether to *run* the list; it does not decide whether the list had to exist. Taken in bare sequence the two collide on the dominant path: this pass's diff is doc-only, item 4 fires, and item 5 is never reached — so a consumer with no `## Pre-merge verification`, no `scripts.verify` and no detectable surface sails through Step 3 and hits "stop and ask the user what to run" at `4a-post`, **after every branch has been merged**, which is the one outcome this step exists to prevent. So run item 5 against the *run*: if no source produced a command list and **any** part of this cycle touches code — this pass's changed-file list, or `git diff --name-only main...<branch>` for any approved branch (the same per-branch read Step 3c makes) — stop and ask **here**, whether or not item 4 skipped the run.

If any command fails, report the failure and **stop**. Do not push with failing checks. Stopping *here* is free — nothing has been merged, no worktree has been removed, no lock has been dropped — so fix the failure and re-run `/review-close` from the top. (`4a-post` has a stop of its own, and it is not free in the same way; its recovery is stated there per policy.)

**Venv-aware invocation.** If a verification command fails with `exit 127` (command not found) or `ModuleNotFoundError` and the project has a `.venv/` directory at the repo root, re-run with `.venv/bin/<cmd>` (for explicit binaries like `.venv/bin/pytest`) or `PATH=.venv/bin:$PATH <cmd>` (for shell pipelines or tools that re-exec). Same pattern as Step 4d's pre-push hook venv prefix. The canonical fix is consumer-side — the project's `<project>/CLAUDE.md § Pre-merge verification` commands should be authored with `.venv/bin/` prefixes when they depend on venv-installed tools (see WORKFLOW.md § 6.1 venv-aware-invocation paragraph) — but the prefix-on-rerun pattern unblocks the cycle when the consumer's command list hasn't been venv-ified yet.

**Boy-scout escalation (ratchet consequence).** A `### Ratchet` snippet invokes the project's lint/typecheck tool against the changed-file list, so if a file in the diff carries pre-existing findings — warnings or type errors not introduced in this review pass — the tool will report them and the gate will fail. That's intentional and not a Sysop-side rule: touching a file means cleaning it. Full-tree backlog cleanups stay as separate project-side tasks (e.g. `TECH-LINT-BACKLOG-FIX`, `TECH-TYPECHECK-BACKLOG-FIX` entries in `tasks/index.yml`), so the ratchet doesn't impose a clean-everything-first dependency on consumers with existing backlogs.

**If a verification command is silently denied** (auto-mode classifier rejects a `npm` / `pytest` / `cargo` / project-specific invocation): prompt the user to run that command themselves via `!`-shell-escape in their prompt — the same pattern Step 4d uses for protected-branch pushes. Do NOT use `AskUserQuestion`; ask for the literal `!`-prefixed command. Step 0's permission guard cannot anticipate every project-specific verification command. (Phase 36's `PermissionDenied` hook only surfaces guidance for the well-known git patterns in Steps 4c/4d/6 — verification commands vary too widely per consumer to enumerate, so this prose remains the load-bearing instruction here.)

> **For new projects:** add a `## Pre-merge verification` section to your CLAUDE.md (template in WORKFLOW.md § 6.1) listing the exact commands this skill should run. That keeps verification deterministic across consumer projects with different stacks.

## Step 3c: Manual Smoke Gate (BeanRider ISSUE-0008, Phase 35)

Some features can't be verified by automated checks — UI flows that need a browser, commands with external side effects, LLM round-trips whose output a human must eyeball. The contract: a task in `tasks/index.yml` may carry `manual_smoke: true`, and/or a `sysop/runtime/pending-docs/*.md` body may contain a heading matching `manual smoke` / `smoke required` (case-insensitive). Either signal halts this step until the human runs, confirms, or waives the procedure.

**Skip Step 3c only when the whole *run* is doc-only — not when Step 3's pre-merge pass was.** Those are different claims, and keying the smoke gate to the second would disable it on nearly every cycle: Step 3's list is main's local-only commits, which are the claim flips and the `review_tasks.md` save, so it doc-only-skips while the approved branches carry real code. Skip 3c when Step 3 doc-only-skipped **and** `git diff --name-only main...<branch>` is doc-only for every approved branch too (same code-file set as Step 3 item 4). Otherwise run it. A smoke gate over a doc-only change is incoherent — but only a doc-only *change* earns the skip, and this gate is the one whose miss is a human never being asked.

**1. Detect signals.** The gate reads pending-docs from **main's `sysop/runtime/pending-docs/` and each approved branch's worktree** — a `/claim-task` worktree authors its pending-doc there, and it is not copied to main until Step 3b (merge time). Reading the worktrees *in place* keeps the gate honest without collecting docs early: collecting before the merge would break the invariant Steps 4c/6 depend on — "everything in main's `sysop/runtime/pending-docs/` belongs to a just-merged branch" — and a branch SKIP'd at Step 3b (worktree remove-refusal, ISSUE-0016) or a whole-run halt could then leave a stray doc that a later Step 4c consolidates for unmerged work, marking its task `done` with the code never merged (BeanRider ISSUE-0050). List this run's approved branches (the same set Step 3b merges), then run the heredoc from the repo root. Output is either `NO_SMOKE_REQUIRED` (proceed to Step 3b) or `SMOKE_REQUIRED: N signal(s)` followed by one `---SIGNAL---` block per signal:

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
  _wt=$(git worktree list --porcelain | awk -v br="refs/heads/$_b" '
    /^worktree /{w=substr($0,10)}
    /^branch /{if(substr($0,8)==br) print w}')
  [ -n "$_wt" ] && SMOKE_WORKTREE_DIRS+="$_wt"$'\n'
done <<BR_LIST
$APPROVED_BRANCHES
BR_LIST

# `python3` command word + in-heredoc PyYAML bootstrap (BeanRider ISSUE-0049; Sysop
# Phase 126) so `Bash(python3 -:*)` matches as a single simple command. The worktree-dir
# list is passed as one quoted positional arg (env-var *prefixes* don't match the rule);
# the repo root is CWD (this heredoc runs from the repo root — the same assumption the
# venv bootstrap's relative glob makes), so the command line carries no env prefix.
python3 - "$SMOKE_WORKTREE_DIRS" <<'EOF'
import re, sys
from pathlib import Path
try:
    import yaml
except ImportError:  # PyYAML lives only in the project venv (BeanRider ISSUE-0049)
    import glob
    sys.path[:0] = glob.glob(".venv/lib/python*/site-packages")
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
search_dirs.append(repo / "sysop/runtime/pending-docs")

heading_re = re.compile(
    r'^(#{1,6})\s+.*(manual\s+smoke|smoke\s+required)',
    re.IGNORECASE | re.MULTILINE,
)
fm_re = re.compile(r'^---\n(.*?)\n---', re.DOTALL)

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
        if md.name in seen_names:
            continue
        seen_names.add(md.name)
        pending_files.append(md)

signals = []

# (a) pending-doc body scan
for md in pending_files:
    for sec in extract_sections(md.read_text(encoding="utf-8")):
        signals.append((label(md), sec))

# (b) index.yml manual_smoke:true cross-check via pending-doc roadmap_ids
index_path = repo / "tasks" / "index.yml"
if index_path.is_file():
    try:
        idx = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        idx = {}
    tasks = {t["id"]: t for t in (idx.get("tasks") or []) if isinstance(t, dict) and t.get("id")}
    smoke_ids = set()
    for md in pending_files:
        fm_m = fm_re.match(md.read_text(encoding="utf-8"))
        if not fm_m: continue
        try:
            fm = yaml.safe_load(fm_m.group(1)) or {}
        except yaml.YAMLError:
            continue
        # Phase 23a compat shim — roadmap_ids OR task_ids
        for tid in (fm.get("roadmap_ids") or fm.get("task_ids") or []):
            if tasks.get(tid, {}).get("manual_smoke") is True:
                smoke_ids.add(tid)
    seen_lc = "\n".join(s for _, s in signals).lower()
    for tid in sorted(smoke_ids):
        body_rel = tasks[tid].get("body", "")
        if not body_rel: continue
        body_path = repo / body_rel if body_rel.startswith("tasks/") else repo / "tasks" / body_rel
        if not body_path.is_file(): continue
        for sec in extract_sections(body_path.read_text(encoding="utf-8")):
            if sec.lower() in seen_lc: continue
            signals.append((f"tasks/index.yml § {tid}", sec))

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

Feature branches created by `/claim-task` or `batch_work.sh` live in worktrees. Branches checked out in a worktree cannot be checked out from main, so worktrees for **approved** branches must be removed before merging.

For each approved feature branch:
1. Check if it has a worktree: `git worktree list` and match the branch name
2. If a worktree exists:
   a. **Collect pending-docs**: Copy `sysop/runtime/pending-docs/*.md` from the worktree to main's `sysop/runtime/pending-docs/` (these are untracked files that would be lost when the worktree is removed): `mkdir -p sysop/runtime/pending-docs && cp <worktree>/sysop/runtime/pending-docs/*.md sysop/runtime/pending-docs/ 2>/dev/null`. The `mkdir -p` is load-bearing: main's `sysop/runtime/pending-docs/` often does not exist (it is gitignored — absent from any fresh clone — authored lazily by `/document-work` in the *worktree*, and removed-when-empty by Step 4c's pending-docs cleanup step), so a bare `cp <file> sysop/runtime/pending-docs/` silently fails with the dest-missing error masked by `2>/dev/null`, and the very next `git worktree remove` then deletes the gitignored pending-doc for good — losing the doc metadata with no warning, and invalidating the rollback guard below (which assumes the copy happened). For the same reason, if the collect itself could not run (e.g. a permission halt on the `mkdir`/`cp` — see the pre-flight guard's deliberate-non-entry note), do **NOT** proceed to (b): removing the worktree with the docs uncollected is exactly the data loss this command exists to prevent.
   b. **Strip the non-work symlinks Step 1a downgraded**, then **remove the worktree** — **never `--force`**. Step 1a can now classify a worktree `clean-ahead` while a downgraded tooling symlink (an untracked `.venv`-into-the-main-venv, BeanRider ISSUE-0043) is still physically present, and that lone symlink is enough to make an *unforced* `git worktree remove` refuse (`contains modified or untracked files`). So before removing, re-apply the same downgrade rule and delete just those symlinks — removing a symlink deletes only the pointer, never its (gitignored) target, and we stay unforced, so any *real* untracked or modified file still blocks the remove:

      ```bash
      repo_root=$(git rev-parse --show-toplevel)
      git -C "<worktree-path>" status --porcelain | while IFS= read -r line; do
        [[ "$line" == '?? '* ]] || continue           # untracked entries only
        entry=${line#'?? '}                           # `entry`, never `path` (zsh $PATH alias)
        [[ -L "<worktree-path>/$entry" ]] || continue # symlinks only — never a real file
        target=$(readlink "<worktree-path>/$entry")
        case "$target" in                             # same downgrade rule as Step 1a
          /*) : ;;
          *)  target=$(cd "<worktree-path>/$(dirname "$entry")" 2>/dev/null && cd "$(dirname "$target")" 2>/dev/null && printf '%s/%s' "$PWD" "$(basename "$target")") ;;
        esac
        git -C "$repo_root" check-ignore -q "$target" 2>/dev/null && rm -f "<worktree-path>/$entry"
      done
      git worktree remove <worktree-path>             # unforced
      ```

      By Step 1a's classification, an `approved` branch passed through Step 2a's clean-state check, so the unforced remove should now succeed. If `git worktree remove` **still** refuses after the strip, that means the worktree carries a genuine untracked/modified file that appeared between Step 1a and now — **stop**, surface the error, then **roll back the pending-docs this branch copied in step (a)** so a later Step 4c cannot consolidate an unmerged branch's doc and mark its task `done` with the code never merged:

      ```bash
      for f in "<worktree-path>"/sysop/runtime/pending-docs/*.md; do
        [ -e "$f" ] && rm -f "sysop/runtime/pending-docs/$(basename "$f")"   # re-collected on a later run once mergeable
      done
      ```

      Then downgrade this branch to SKIP for this run (leave its worktree, lock, and branch intact), and continue with the next approved branch. Silent data loss is the failure mode this guard prevents (BeanRider ISSUE-0016) — the strip never touches a real file, so it cannot cause it. (The rollback matters because step (a) copies before this remove is attempted; without it, a branch SKIP'd here leaves its doc stranded in main's `sysop/runtime/pending-docs/` for the merged branches' Step 4c to consolidate.)
3. If no worktree exists, the branch is already free for checkout

For **SKIP'd** branches (Step 2a verdict, dirty worktree), do nothing here — the worktree stays.
For **rejected** branches, leave worktrees in place (cleaned up in Step 6).

## Step 4: Merge & Land on Main

### 4-pre. Determine Merge Policy & Target

How approved work reaches `main` depends on the project's **merge policy** — read it from `<project>/CLAUDE.md § Merge policy` (the same "consumer declares its shape" pattern as Step 3's `§ Pre-merge verification`). Two values; **default `direct`** when the section is absent:

- **`direct`** (default) — feature merges, batch close, and doc consolidation land on `main` locally, then `git push origin main`. Correct for any project whose `main` accepts a direct push (no required status check, no `enforce_admins`). This is the historical flow; a consumer who never configured a merge policy keeps it with zero change.
- **`pr`** — `main` is never written directly; it is written only through a squash PR. Usually that means assembling everything on a throwaway **integration branch** cut from fresh `origin/main`, pushing it, and merging it into `main` through a PR — but when a single approved branch already *has* an open PR against `main`, the close lands on that branch instead (see the reuse probe below). Required when `main` is push-protected (a required CI check and/or `enforce_admins`) — a direct push would be rejected. GitHub becomes the sole serialized writer of `main`, which also removes the race against a concurrent auto-merge (e.g. Dependabot) landing on `main` mid-close.

Determine the **merge target** for the rest of Step 4 from the policy, and hold it as a value you write out at each later use — not as a shell variable. Every later reader is in a different fenced block, and nothing survives across one (`WORKFLOW.md` § 8.2a *Persistence boundary*); Step 4a's two merge commands are the readers that matter, and an empty operand there is a `fatal:` at best.

**`direct`:** the merge target is `main`.
```bash
git checkout main
```

**`pr`:** two shapes. Almost every run assembles on a throwaway **integration branch** (the default, below). One narrow case instead **reuses the approved branch's own open PR** — probe for it first, because cutting an integration branch there opens a *second* PR for content that already has one, re-runs the whole required-check suite on identical content, and orphans the first PR.

**PR-reuse probe (run first).** Reuse the existing PR when **all five** conditions hold:

1. **exactly one** branch is still approved **after Step 3b** — not merely after Step 2a. Step 2d can demote an approved branch to rejected ("Hold for fix") and Step 3b downgrades a branch to SKIP when its worktree refuses to remove, so the Step 2a verdict is not final. Reusing a branch this run decided *not* to merge would squash-merge it to `main`;
2. that branch has exactly one open, **non-draft, same-repository** PR whose base is `main`;
3. there are **no local-only `main` commits** to sweep (`git rev-list origin/main..main` is empty) — the sweep is the integration branch's job and there is nowhere to put those commits on a feature branch;
4. the local branch is **not behind** its remote counterpart — otherwise the Step 4b/4c commits would land on a branch missing work someone else pushed to the PR, and the Step 4d push would be rejected as non-fast-forward;
5. the branch is **not behind `origin/main`**. Step 4a is skipped under reuse, so nothing rebases the branch onto the live base. The integration-branch shape exists partly to run the required checks against *current* `origin/main`; this condition is what replaces that guarantee, and without it a branch-protection rule requiring up-to-date branches yields `mergeStateStatus: BEHIND` and a refused merge.

**If anything other than exactly one branch is still approved, condition 1 already fails — skip the probe entirely and go to the integration-branch shape.** Otherwise:

```bash
git fetch origin main
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
gh pr list --head "<approved branch name>" --base main --state open \
  --json number,isDraft,isCrossRepository \
  --jq '[.[] | select(.isCrossRepository == false and .isDraft == false) | .number]
        | if length == 1 then .[0] else empty end'
echo "--- local-only main commits (condition 3; must be 0 to reuse):"
git rev-list --count origin/main..main
```

Read both values off stdout and carry them forward as **literals**. The `echo` labels are load-bearing, not decoration: without them the two outputs are positionally ambiguous, and a *missing* first value silently shifts the second into its slot — a bare `2` reads as "PR #2" when it is actually the commit count with no PR found. (`echo` is in Claude Code's documented built-in read-only set, so labelling costs nothing at the permission layer.)

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
echo "--- behind origin/main (condition 5; must be 0):"
git rev-list --count "<approved branch name>..origin/main"
```

**If the fetch exit is not `0`, take the integration-branch shape and do not read the two counts at all.** This replaces a claim that was measured false (Phase 169's round): a failed fetch does **not** make condition 4 print nothing. `refs/remotes/origin/<branch>` survives a failed fetch for any branch this clone has ever fetched or pushed — which is every branch with an open PR, i.e. every branch that can reach this probe — so both counts resolve against **stale** refs and print `0`. `0` and `0` is exactly the answer that takes the reuse shape. Measured: with `gh` reachable over HTTPS but git transport broken (expired SSH key, agent not loaded, SSH egress blocked — the ordinary way to be here, since total network loss stops you at the `gh pr list` probe), a branch genuinely **1 behind its remote and 1 behind `origin/main`** printed `0` for both. That is a squash-merge of work this run decided not to merge, in the one direction the whole step exists to prevent. The `$?` echo is the only thing that distinguishes it, so it is not optional.

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

> **How often this actually fires.** Less often than it looks. Condition 3 fails whenever `/claim-task` made its `open → in_progress` flip on `main` (Step 4d) or Step 1b committed a `review_tasks.md` save — both commit to local `main` and neither is pushed — so the common single-branch cycle still takes the integration-branch shape. The reuse shape is for the case where the claim commits were already swept by a prior close and this cycle's only local-only work rode the feature branch. Falling through is never wrong, just wasteful; taking the reuse shape when a condition is unmet **is** wrong, so probe rather than assume.

**Integration-branch shape (the default — any condition above unmet).** Cut the branch off the **live** `origin/main` (so the PR's required checks run against the current base — an auto-merged commit may have landed since this run started), then sweep any local-only `main` commits onto it. Those commits are the `open → in_progress` claim flips from `/claim-task` Step 4d & `/auto-build` Step 5.4 and any Step 1b `review_tasks.md` save/rotation — all committed on `main` locally but never pushed, so the fresh branch does not carry them yet. At close time every local-only `main` commit belongs to this cycle; if you have unrelated un-pushed `main` work, resolve it before running `/review-close` under `pr` policy.

```bash
git fetch origin main
RUN_ID="$(date -u +%Y%m%dT%H%M%S)"
INTEGRATION_BRANCH="merge/review-close-${RUN_ID}"
git checkout -b "$INTEGRATION_BRANCH" origin/main
# No `MERGE_TARGET=` here — it would not reach Step 4a, which is a later block. The
# integration branch name IS the merge target; record it and write it out there. Echo it
# so the literal you carry forward comes off stdout rather than from memory:
echo "--- merge target for Steps 4a-4d:"
echo "$INTEGRATION_BRANCH"

# Sweep local-only main commits (claim flips + Step 1b doc saves) onto the branch.
# A range, applied oldest-first by cherry-pick itself — NOT a `for … done` loop over
# `git rev-list`, which would match no allow-rule (`for`/`done` are not documented
# command separators) and so be denied under `dontAsk`, leaving the claim flips off the
# integration branch while Step 6's `git reset --hard origin/main` later discarded them
# from local `main` as well (Phase 153).
#
# RUN THIS ONLY IF the local-only count you read in the Step 4-pre probe
# (`git rev-list --count origin/main..main`) was NON-ZERO. Unlike the loop it replaces,
# an empty range is not a silent no-op — cherry-pick hard-fails with
# `error: empty commit set passed`. You already have the number; skip the line if it is 0.
#
# A conflict means origin/main advanced over the same lines (rare — Dependabot touches
# deps, not tasks/index.yml); resolve it, or `git cherry-pick --abort` and re-cut the
# branch from local `main` instead.
git cherry-pick origin/main..main
```

> **HARD RULE — branch guard.** Steps 4a–4c run in the shared **primary** worktree, which has a single `HEAD`; a concurrent local actor can move it off the branch you expect mid-flow, landing commits on the wrong branch. Apply `_shared/main-push-guard.md` **Rule A** before **every** commit in Step 4. The assert's expected value must come from somewhere **other than `HEAD`** — comparing HEAD against a HEAD-derived value is a tautology that passes even after a hijack. By policy and shape:
> - **`direct`** — assert against the literal: `test "$(git rev-parse --abbrev-ref HEAD)" = "main"`.
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
1. `git checkout <branch> && git rebase "<merge target>"`
2. `git checkout "<merge target>" && git merge --ff-only <branch>`
3. If rebase has conflicts: `git rebase --abort`, report the conflict, skip that branch.

Feature branches MAY modify `review_tasks.md` — typically as single-line task-checkbox flips (`[/]` → `[x]`) that rebase clean. Structural conflicts arise when the merge target has moved `review_tasks.md` between branch-cut and rebase, in two common cases: (a) another already-merged batch added a sibling `### Batch N` section, (b) the project's archive-rotation script (e.g., `archive_review_tasks.py`) rotated rounds or batches out into a sibling archive file (committed by Step 1b — and, under `pr` policy, swept onto the integration branch by Step 4-pre). Resolve by reading both sides of the conflict: keep the merge target's structure as authoritative (it reflects the post-rotation / post-other-batch layout), then re-apply the branch's intent — checkbox flips and any net-new `### Batch N` section — in the new layout. Genuine code-overlap conflicts still surface here too; treat them the same way (resolve, don't abort).

### 4a-post. Verify the Merged Tree

**This is the gate whose green means something.** Step 3 ran the same resolved list against `main`; this runs it against the tree that is about to be pushed. Each approved branch was already verified *in its own worktree, at its own tip* — `/claim-task` Step 7e (its executor prompt's Sequence, item 5) and `/auto-build`'s execution-agent sequence (Step 7's prompt template, item 4b) both run the consumer's `## Pre-merge verification` gates there, which is why each of those says `/review-close` runs project-side verification "at merge time." What has never been verified anywhere until this step is the **assembled** result: the branches merged onto the live base and onto each other.

**Placed here on purpose — after the merges, before `close_batch.sh` and before doc consolidation.** A stop at this point consumes nothing. Step 4c deletes each `sysop/runtime/pending-docs/*.md` after routing its content into the shared docs, and those files are **untracked** — so the routed content survives only in 4c's commit. **Under `pr` that commit is on the merge target, which a failed close abandons** (the integration branch is re-cut from `origin/main` next run), leaving the content recoverable from a discarded branch or not at all. Under `direct` the commit stays on local `main` and the recovery below keeps it, so the window is a `pr`-shape window — which is every protected-`main` consumer, and the shape this repo runs. Verifying later would verify a slightly larger tree; it would also put that window under a failing gate.

1. **Re-resolve the command list** exactly as Step 3 did — the same numbered resolution order, first source wins. Re-read it rather than carrying Step 3's result forward as a remembered value: it costs one file read, and it removes the only way this step can silently run something other than what the consumer declared.

2. **Recompute the changed-file list on *this* tree** — the same command Step 3 ran, unchanged:

   ```bash
   git rev-parse --verify --quiet origin/main >/dev/null \
     && git diff --name-only origin/main...HEAD \
     || echo "NO_ORIGIN_MAIN"
   ```

   `HEAD` is the merge target now, so this is the assembled diff: every approved branch's contribution, plus — under `pr` policy's integration-branch shape — the local-only `main` commits Step 4-pre swept on. **Under `direct` it can be a superset**, and deliberately so: Step 4-pre is a bare `git checkout main` with no fetch, so `origin/main` may be stale and the range then also covers whatever landed upstream since your last fetch. That errs toward verifying more, which is the safe direction; do not "fix" it with a fetch here, because refreshing the base mid-close is Rule B's job at Step 4d and doing it early would silently change the tree you are about to gate. It is also what makes the consumer's `### Ratchet` snippets correct for the first time — each one filters `git diff --name-only origin/main...HEAD` on its own, and only on this tree does that command name the work being shipped. `NO_ORIGIN_MAIN` here means the same thing it means at Step 3: gate nothing, skip nothing, run the full list.

   **An empty list here is not a pass — it is a contradiction, and you must stop on it.** Unlike at Step 3, an empty list at this point says the merge target holds nothing `origin/main` does not already have, while Step 4a just reported merging approved branches. Something did not land: a rebase left the branch a no-op, a `--ff-only` merge was skipped after a conflict, or `HEAD` is not the merge target you think it is. Report it and reconcile before Step 4b — do not let a gate that executed nothing report green over a close that merged nothing.

3. **Run the list**, applying item 3's surface gate and item 4's doc-only skip to *this* list. **If the surface gate leaves nothing to run while the list still contains a code file, that is "ran nothing", not green** — it is item 5's case arriving late (no applicable command for a code-touching diff), so stop and ask the user what to run, naming the surfaces gated out and the unclaimed files. A gate that executed zero commands must never report the same as one that executed them and passed; that equivalence is the defect this whole step exists to remove, and surface-gating is the one way this step can re-manufacture it. Everything Step 3 says about invocation still holds and is not restated: venv-aware re-invocation on `exit 127` / `ModuleNotFoundError`, the `!`-shell-escape route for a silently-denied command (never `AskUserQuestion`), and the read-only rule — no `pip install`, no state mutation, in a verification command.

4. **On failure, stop.** Nothing has been pushed, `close_batch.sh` has not run, and no pending-doc has been consumed. Report the failing command with its output. Recovery is per merge policy:
   - **`pr`** — the merges are on the merge target, unpushed. Fix the failure, then re-run `/review-close`: a `pr` run cuts a fresh integration branch from `origin/main` every time, so the abandoned one costs a `git branch -D` and nothing else. Under the PR-reuse shape there is no branch to abandon — the extra commits simply stay local until a later run pushes them.
   - **`direct`** — the merges are on local `main`, unpushed. **Do not `git reset --hard`**: that discards the claim flips and the merges together, and neither is recoverable from `origin`. Leave `main` as it stands. Those commits are now exactly the *unpushed main commits* category Step 1 already enumerates, so once the failure is fixed the next `/review-close` picks them up — and that run's Step 3 verifies them for real, because by then they are on its own tree.

5. **Confirm the gate left the tree clean**, before Step 4b asserts it:

   ```bash
   git diff --quiet HEAD -- && echo "CLEAN" || echo "DIRTY — verification modified tracked files"
   ```

   A formatter, a regenerated lockfile or a rewritten snapshot can leave tracked files modified. Step 4b's landing check is `git diff --quiet && git diff --cached --quiet`, so those modifications would surface there as a *close-batch commit that did not land* — a true report of the wrong cause. On `DIRTY`, resolve it project-side; do **not** fold the modifications into the close's commits. (Untracked build output is not at risk and does not trip this — `git diff` does not see it.)

**Under the Step 4-pre PR-reuse shape this step still runs**, even though Step 4a was skipped there. The merge target is the approved branch and it is checked out, so step 2's command returns that branch's own diff against `origin/main` — which is exactly the tree its PR will squash.

> **This is the gate `_shared/main-push-guard.md` Rule B re-runs, and Step 3 is not.** When Rule B's rebase-first arm fires at Step 4d because `origin/main` advanced mid-run, the base underneath the merge target changed, so the verdict *this* step produced no longer describes the tree being pushed. Re-run this step. Re-running Step 3 would answer a question nobody asked: its tree is not the one that moved.

### 4b. Close Merged Batches

After all branches are merged and `4a-post` reported green, but **before** doc consolidation:

```bash
bash sysop/scripts/close_batch.sh <N1> <N2> <N3>
```

This script updates `review_tasks.md` on the checked-out branch (the merge target — it resolves the repo via `git rev-parse --show-toplevel`, so it commits to whatever branch is current): sets batch headers to `Merged`, marks task checkboxes `[x]`, updates the Statistics table, and adjusts the Grand Total counts. **One exception:** a task annotated `> Failed:` on the following line keeps its checkbox and is left out of both the flip and the counts — a FAIL verdict means the work was attempted and not finished, so the batch closes as "shipped, minus these" (Phase 157). Expect the per-batch line to read `(3 tasks closed, 1 failed — still open)` when that happens. One commit is created for all closed batches.

**Under `pr` policy, always pass `--force`** — in *both* Step 4-pre shapes. The script's gate is `git merge-base --is-ancestor <batch branch> main` against the literal `main`, and under `pr` policy nothing has reached local `main` yet at this point: the integration branch is cut from `origin/main` and is not a descendant of the batch commit tips, and a reused PR branch is by definition still unmerged. Either way the ancestry check would reject the close. (`--force` skips that check; it is the documented escape and lands the close commit on whichever branch is checked out.)

If any branches were cherry-picked instead of rebased+merged (e.g., because worktree removal wasn't possible), use `--force` to skip the merge-base ancestry check:

```bash
bash sysop/scripts/close_batch.sh --force <N1> <N2> <N3>
```

**Verify the close-batch commit landed before proceeding.** The script wraps its `git commit` in explicit failure handling (Phase 33 / BeanRider ISSUE-0015), but trust-but-verify: confirm a `docs: close Batch …` commit is the new tip and the working tree is clean before continuing to Step 4c.

```bash
git log -1 --pretty=%s | grep -q '^docs: close Batch ' && git diff --quiet && git diff --cached --quiet
```

If the check fails (no `docs: close Batch …` tip, or `review_tasks.md` is still modified/staged): the close-batch commit did NOT land. **Halt before Step 4c** — proceeding would fold the close-batch edits silently into the doc-consolidation commit instead of their own atomic commit, and ordering ("after merge but before doc consolidation") is broken. Inspect the script's stderr output (most commonly a pre-commit-hook failure — see Step 4d's venv-prefix pattern). The script's terminal `── close_batch.sh completed — close-batch commit present: N` line (Phase 43a / BeanRider ISSUE-0039) survives tail-truncation and tells you whether the script aborted silently (line absent) or completed with no commit landed (`present: 0`). Two recovery paths, in order:

1. **Re-run the script** with the same batch list — the rerun is idempotent for review_tasks.md (sed substitutions are no-ops on already-Merged batches) and will re-attempt the commit:
   ```bash
   bash sysop/scripts/close_batch.sh <N1> <N2> <N3> 2>&1 | tee /tmp/close-batch.log
   ```
   `tee` preserves the full output so a missing terminal line is unambiguously visible.

2. **If re-run still doesn't commit** (review_tasks.md is staged but the script aborts after the `git add`), commit by hand with the canonical subject — same form the script would have used — and proceed:
   ```bash
   git add review_tasks.md && git commit -m "docs: close Batch <N1>, <N2>, <N3>"
   ```
   Step 4c is safe once a `docs: close Batch …` commit is the tip.

**Do NOT remove completed batches** — they will be archived during the next `/codebase-review` run.

### 4c. Consolidate Pending Documentation

After all branches are merged but **before** pushing:

1. **Scan for pending docs**: `ls sysop/runtime/pending-docs/*.md 2>/dev/null`

2. **If none found**: check merged history for `docs:` commits (backward compatibility with branches that wrote docs directly). If present, skip doc consolidation — the docs are already in the shared files.

3. **If pending-docs files found**: parse each file's YAML frontmatter and extract:
   - `branch`, `date`, `type`, `roadmap_ids`, `review_task_ids`, `summary`

   **Format detection**: If the file starts with `---` on line 1, parse as YAML frontmatter. Otherwise, fall back to the legacy 5-section markdown format (parse `## Classification`, `## PROJECT_STATUS Entry`, etc.).
   <!-- Legacy format support — remove after all active worktrees are merged -->

   **Phase 23a compat shim — read every pending-doc with this fallback:**

   ```python
   roadmap_ids    = pending.get('roadmap_ids')    or pending.get('task_ids') or []
   review_task_ids = pending.get('review_task_ids') or []
   ```

   The fallback covers in-flight pending-docs authored before the `task_ids` → `roadmap_ids` rename (Phase 23a). Treat any IDs read via the fallback as `roadmap_ids` — that matches the pre-rename consumer behavior (Step 4c's heredoc was already treating them as roadmap IDs, just silently no-op'ing on the non-matches). **Removal trigger:** drop the `or pending.get('task_ids')` clause in any subsequent phase that touches Step 4c, once BeanRider has run one full `/review-close` cycle on a pending-doc authored after the 23a absorption (confirmable via `git log -p sysop/runtime/pending-docs/` or via the merged consolidation commit). Pending-docs are minutes-to-hours lived; the shim's exposure window is one absorption cycle.

4. **Route by type and write to shared docs** (single pass, no conflicts since we're on main post-merge):

   Use this routing table to determine which shared docs to update for each entry. The "Roadmap" column shows which frontmatter field drives the `tasks/index.yml` round-trip; `review_task_ids` is **documentary only** and never consulted here (review-task closure happens in Step 4b via `bash sysop/scripts/close_batch.sh`).

   | Type | PROJECT_STATUS | Changelog | UI_Iterations | Roadmap (`roadmap_ids`) |
   |---|---|---|---|---|
   | feature | Yes | — | — | if populated |
   | bugfix | Yes | Yes | — | if populated |
   | ui-iteration | Yes | — | Yes | if populated |
   | infrastructure | Yes | — | — | if populated |
   | adhoc | Yes | — | — | if populated |

   The Roadmap column is **informational only** — `if populated` means the `tasks/index.yml` round-trip below runs unconditionally for every ID in `roadmap_ids`, regardless of `type`. This is intentional: the round-trip is mechanical (status flip + body move + lock/parked-marker cleanup), driven by data presence, not by type. A pending-doc with `roadmap_ids: []` simply skips the round-trip naturally. (BeanRider ISSUE-0034: tracked-bug close-outs use `type: bugfix` with a populated `roadmap_ids: [BUG-NNNN]` and need the round-trip; the prior `—` reading would have left the BUG entry stuck `in_progress` with the body orphaned under `open/`.)

   For each entry, generate the doc content from `type` + `summary` + `roadmap_ids` + `review_task_ids` + `date`:

   **PROJECT_STATUS.md §6**: Generate a one-line entry: `<date>: [<ID(s)> Complete:] <summary>`. Pull IDs from `roadmap_ids` AND/OR `review_task_ids` — both kinds belong in the PROJECT_STATUS entry as provenance. Insert at the TOP of Section 6 "Recent Major Updates" (below the section header, above existing entries). Newest branch first.

   **Rotation check**: if §6 has more than 8 entries after adding, rotate the oldest entries to `changelog.md` (under the appropriate date heading) until only 6 remain.

   **changelog.md** (bugfix type only): Generate entry `- **<Short Title>**: <summary>`. Add under today's date heading (`### YYYY-MM-DD`). Create the heading if it doesn't exist (at the top, under the month heading).

   **tasks/index.yml**: For each ID in `roadmap_ids` (NOT `review_task_ids` — those are documentary, see the note above), round-trip the index through `yaml.safe_load` to set `status: done` + `completed_date: <today's ISO date>` on the entry, then `git mv` the body file from its current location under `open/` or `deferred/` to the corresponding location under `archive/` and update the entry's `body:` field. The heredoc below is prefix-agnostic — it handles both canonical (`body: open/<TASK_ID>.md`) and `tasks/`-prefixed (`body: tasks/open/<TASK_ID>.md`) shapes by locating the `open` / `deferred` path segment and swapping it for `archive`. It also tolerates pending-docs authored before Phase 23a (compat shim — see the **Phase 23a compat shim** block in step 3 above). After all IDs are processed, run the validator (`python3 sysop/scripts/validate_tasks.py` — a single command matching `Bash(python3 sysop/scripts/validate_tasks.py:*)`; Sysop Phase 126 dropped the shared `PATH` prefix this line used to ride on and gave `validate_tasks.py` its own `sys.path` PyYAML bootstrap, so bare `python3` resolves `yaml` for both venv-only and non-venv consumers — BeanRider ISSUE-0049) — if it exits non-zero, abort the close. The schema invariants for `done` status require: a valid `completed_date`, either a `body:` or an `archive_summary:`, and (ISSUE-0009) the body path must NOT contain an `open/` or `deferred/` segment (a half-migrated state where the status flip wrote but the rename silently no-op'd). Fix any failure before pushing.

   ```bash
   # `python3` command word + in-heredoc PyYAML bootstrap (BeanRider ISSUE-0049; Sysop
   # Phase 126) so `Bash(python3 -:*)` matches as a single simple command — no PATH prefix,
   # no `&&` compound, no `.venv/bin/python3` (none of which match that rule).
   python3 - <<'PY'
   import datetime, subprocess, sys
   try:
       import yaml
   except ImportError:  # PyYAML lives only in the project venv (BeanRider ISSUE-0049)
       import glob
       sys.path[:0] = glob.glob(".venv/lib/python*/site-packages")
       import yaml
   from pathlib import Path
   today = datetime.date.today().isoformat()
   # Populate from this round's pending-doc roadmap_ids (with the Phase 23a
   # compat shim applied at parse time — see step 3 above).
   # review_task_ids are NOT processed here — they're documentary only.
   ids = ["<ROADMAP_ID_1>", "<ROADMAP_ID_2>"]
   p = Path('tasks/index.yml')
   d = yaml.safe_load(p.read_text())
   closed = []
   for t in d.get('tasks', []):
       if t['id'] not in ids:
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
       p.write_text(yaml.safe_dump(d, sort_keys=False, default_flow_style=False, allow_unicode=True, width=120))
       # Stage the rewrite here, in the same code that performed it. `git mv` above already
       # staged both halves of each body rename, but `Path.write_text` does not stage
       # anything — so without this line the index is left HALF staged, and Step 7's
       # `git commit` would record the renames while silently dropping the `status: done`
       # + `completed_date` flip under a subject claiming the consolidation happened
       # (upstream #203). Staging beside the write is the only form that cannot drift out
       # of sync with what was written.
       subprocess.run(['git', 'add', str(p)], check=True)
   # Working-tree cleanup, deferred until every git mv landed and the index wrote:
   # an abort mid-loop must not have already destroyed an earlier task's records
   # (the parked marker below is unrecreatable — plan + verdict, never committed).
   # Keyed on the task id, not the body shape, so archive_summary and flat-layout
   # closes — which `continue` past the move above — are still cleaned up.
   for tid in closed:
       # Drop the per-task lock file (BeanRider ISSUE-0035). The lock's lifecycle
       # is open → in_progress (claim_task --lock creates it) → done (here). Leaving
       # it behind clutters sysop/runtime/locks/ and confuses the "is anyone working on this?"
       # signal. `sysop/runtime/locks/` is .gitignored, so this is a working-tree-only operation
       # — no stage, no commit. `missing_ok=True` tolerates pre-Phase-32 tasks
       # whose locks already got cleaned up by hand.
       Path(f'sysop/runtime/locks/{tid}.lock').unlink(missing_ok=True)
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
           marker.unlink(missing_ok=True)
   PY
   python3 sysop/scripts/validate_tasks.py || { echo "validator rejected the index — aborting"; exit 1; }
   ```

   **UI_Iterations.md** (ui-iteration type only): Generate table row `| <name> | <date> | <summary> | <commit-hash> |`. Append to the markdown table.

   <!-- Canonical process: WORKFLOW.md §2.8 (Senior Merge & Verification) -->

   <!-- Convention promotion moved to /codebase-review and /security-audit Step 9 -->

6. **Clean up pending-docs**: Delete all remaining `sysop/runtime/pending-docs/*.md` files. Remove the `sysop/runtime/pending-docs/` directory if empty.

7. **Stage, then commit**: `docs: consolidate documentation for <N> merged branches`

   **Stage the shared docs one `git add` per file** — the heredoc already staged `tasks/index.yml` and both halves of each body rename, but the shared-doc edits above were made with the editor and are still unstaged. Add **only** the docs the routing table actually sent this run's entries to:

   ```bash
   git add PROJECT_STATUS.md                 # every type
   git add changelog.md                      # if a bugfix entry was routed there, OR if the
                                             # rotation check moved §6 entries into it
   git add UI_Iterations.md                  # only if a ui-iteration entry was routed there
   git commit -m "docs: consolidate documentation for <N> merged branches"
   ```

   > **One `git add` per file, never one command listing them all.** `git add` is **all-or-nothing across its pathspecs**: if any pathspec matches nothing, the whole invocation aborts with `fatal: pathspec '<path>' did not match any files` and stages **none** of the others (verified). `changelog.md` and `UI_Iterations.md` are consumer-authored and frequently absent — Sysop never creates them — so a combined `git add PROJECT_STATUS.md changelog.md UI_Iterations.md` aborts on the majority of close-outs. `-A` does **not** change this: `git add -A <missing-path>` aborts identically. Separate commands mean a missing optional doc costs only its own line.
   >
   > The same property is why the instinctive `git add <old-path> <new-path>` after a `git mv` does not help: the stale pre-rename pathspec aborts the invocation, so nothing is staged by it. It leaves the index exactly as it was — `git mv` had already staged both halves — which is the trap, because it *looks* like staging was attempted and the following `git commit` still succeeds on the unchanged index.
   >
   > **Do not stage `changelog.md` from the routing table alone.** The **Rotation check** above writes it whenever §6 exceeds 8 entries, regardless of entry type — so a run with no bugfix at all can still have rotated entries into `changelog.md`, and skipping it there commits the §6 truncation without the entries it moved.

   **Then verify the commit carried everything** — Step 4b has a trust-but-verify gate for exactly this failure class and Step 4c historically had none, which is what let a rename-only commit pass as a consolidation (upstream #203):

   ```bash
   git log -1 --pretty=%s | grep -q '^docs: consolidate documentation' && git diff --quiet && git diff --cached --quiet
   ```

   If that fails, the tree still has unstaged or staged-but-uncommitted consolidation edits: stage the missing file(s) and `git commit --amend --no-edit` before proceeding. **Additionally, if this run closed at least one `roadmap_ids` entry** (the heredoc's `closed` list was non-empty), confirm the index flip is actually in the commit:

   ```bash
   git show --stat HEAD | grep -q 'tasks/index.yml'
   ```

   Skip that second check when no pending-doc carried `roadmap_ids` — `tasks/index.yml` is then legitimately untouched and its absence from the commit is correct, not a failure.

   **If the commit is silently denied** (auto-mode classifier rejects `git commit` on `main` — a `direct`-policy concern; under `pr` policy this commit lands on the integration branch, not `main`, so it does not hit this wall), the Phase 36 `PermissionDenied` hook surfaces the `!`-escape command and the multi-`-m`-flag rewrite recipe — follow its guidance and relay to the user. Background: the classifier extends protected-branch policy upstream from the push to its enabling commit when context implies an imminent push, so the first `docs(tasks):` commit of a cycle goes through but the Step 4c consolidation commit hits the same wall as the Step 4d push. The hook's `additionalContext` names the specific escape form; this skill stays brief on purpose to avoid drifting from the hook's authoritative phrasing.

### 4d. Land on `main`

How the assembled work reaches `main` depends on the merge policy from Step 4-pre.

#### `direct` policy

Once all merges and doc consolidation are complete (or if there were only unpushed main commits), push `main` via the **`_shared/main-push-guard.md` Rule B safe-push sequence** rather than a bare push — assert-on-`main` (Rule A) → `git fetch origin main` → rebase-first if `origin/main` advanced (an autonomous auto-merge, e.g. Dependabot) → push the exact verified tip (`git push origin "<SHA>:main"`, **never `--force`** per Rule C) → confirm `origin/main` equals the SHA you pushed. The rebase-first step also re-runs **`4a-post`** — the merged-tree gate — against the new base; not Step 3, whose tree is `main` and is not the thing that moved. The bare `git push origin main` is safe only when `origin/main` has not moved; Rule B makes that check explicit instead of assumed.

Then confirm the push succeeded.

If the push is **rejected because `main` is protected** (`! [remote rejected] main -> main (protected branch hook declined)`, a required status check, or `enforce_admins`), the project's `main` requires the PR flow: set `§ Merge policy: pr` in `<project>/CLAUDE.md` and re-run `/review-close`. This is the exact failure the `pr` policy exists to handle — do not try to force the push.

**If push is silently denied** (auto-mode classifier rejects pushing to a protected branch), the Phase 36 `PermissionDenied` hook surfaces the `! git push origin main` escape command — and the venv-prefix variant (`! PATH=.venv/bin:$PATH git push origin main`) when the consumer's repo has a `.venv/` directory. Follow the hook's guidance and relay to the user. The canonical consumer-side fix is unchanged: the project's `sysop/scripts/hooks/pre-push` should prepend `${REPO_ROOT}/.venv/bin` to its `PATH` at the top of the hook (see WORKFLOW.md § 6.1 venv-aware-invocation paragraph). Do **NOT** use `AskUserQuestion` — empirically the classifier does not honor its answer for protected-branch pushes and you'll burn a turn on a dead-end handshake. See WORKFLOW.md § 8.2a for the full rationale.

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
gh pr create --base main --head "$INTEGRATION_BRANCH" \
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
gh pr list --head "$(git rev-parse --abbrev-ref HEAD)" --base main --state open \
  --json number,isDraft,isCrossRepository \
  --jq '[.[] | select(.isCrossRepository == false and .isDraft == false) | .number]
        | if length == 1 then .[0] else empty end'
```

**If that prints nothing, STOP** — reconcile by hand, and do not run anything below. This is a hard gate rather than a warning because `gh` does **not** reject an empty operand: it silently resolves the current branch's PR instead (see the `gh`-empty-operand note in Step 4-pre), so a missing number does not fail, it merges the wrong thing.

Otherwise substitute the printed number for `"<PR>"` below and run the commands **as written**. It is a literal, not a variable, for the same reason the probe is bare: a captured value would not survive to the next shell call, and an assignment would cost the invocation its allow-rule match. **Keep the quotes.** Unquoted, `<PR>` is not a placeholder to bash — `<` and `>` are redirections, so `gh pr merge <PR> --squash` silently runs as `gh pr merge --delete-branch` reading from a file named `PR`, and `gh` then falls back to the current branch. Quoted, an unsubstituted placeholder is a *loud* failure (`no pull requests found for branch "<PR>"`) instead of a silent wrong merge — which is what makes the stop above enforceable rather than merely advisory.

```bash
# 4. wait for the PR's required checks to finish (blocks ~1–2 min). Its exit status is NOT
#    the verdict — it exits non-zero both on a failing check and on a repo with no checks
#    at all (one protected only by enforce_admins), so a bare invocation would surface a
#    red tool result on a perfectly mergeable PR and invite you to stop. The `|| echo` tail
#    is deliberate and is NOT `|| true`: `echo` IS in Claude Code's documented built-in
#    read-only set while `true` is not, so this keeps the compound authorized while
#    preserving the do-not-abort semantics the step needs (Phase 153).
gh pr checks "<PR>" --watch --fail-fast || echo "checks reported non-zero — not the verdict; continue to command 5"
# 5. confirm mergeability, then squash-merge (blocks until landed; deletes the remote branch)
gh pr view "<PR>" --json state,mergeStateStatus --jq '{state, mergeStateStatus}'
gh pr merge "<PR>" --squash --delete-branch
# 6. THE VERDICT. Run this as its own command, after the merge, always — the merge command's
#    exit status and stderr are NOT the verdict (see the note below). Only `state` is.
gh pr view "<PR>" --json state,mergedAt --jq '{state, mergedAt}'
```

> Here `$(git rev-parse --abbrev-ref HEAD)` is safe and non-tautological: HEAD was already asserted against a non-HEAD-derived value in Step 1 of this same block, so by this line it is *known* to be the right branch. It is a lookup key, not a guard.
>
> **PR-reuse shape only — pin the head commit.** The integration-branch shape merges a branch it just created under a unique timestamped name that nothing else writes to. A reused branch is a long-lived branch someone else may push to between your push and your merge, so pass `--match-head-commit "$(git rev-parse HEAD)"` on the merge and let it refuse rather than squash-merging content you never verified. (Requires a reasonably current `gh`; if your `gh` rejects the flag, re-read `gh pr view --json headRefOid` and compare by hand before merging.)

> **A `fatal:` from `gh pr merge --delete-branch` does NOT mean the merge failed (upstream #208).** `--delete-branch` deletes the **local** branch as well as the remote one, so after the remote squash lands, `gh` switches the local checkout to the base branch and tries to fast-forward it. **In the integration-branch shape that fast-forward cannot succeed:** Step 4-pre cherry-picked every local-only `main` commit onto the integration branch, so those commits exist twice at different SHAs and `origin/main` is not a descendant of local `main` after the squash. `gh` reports it as:
>
> ```
> fatal: Not possible to fast-forward, aborting.
> ! warning: not possible to fast-forward to: "main"
> ```
>
> preceded by a block of `hint: git merge --no-ff` / `hint: git rebase` noise. That is **expected, benign, post-merge local housekeeping**, not a merge failure — `gh` swallows the error and the local branch is deleted anyway. It fires for every `pr` consumer that used `/claim-task` (its `open → in_progress` flip commits to local `main`) or whose Step 1b saved `review_tasks.md`, which is nearly all of them.
>
> **In the PR-reuse shape it does *not* fire** — reuse condition 3 requires `origin/main..main` to be empty, so local `main` is an ancestor of `origin/main` and `gh`'s fast-forward succeeds. Expect the message in one shape and not the other; in neither shape is it the verdict.
>
> **Run command 6 regardless of what command 5 exited with** — that is the entire point. If your shell aborts the block early, re-run the state probe on its own; the verdict is unchanged either way. Do **not** write `gh pr merge … || true`: `gh` reports genuine failures through that exit status too, and masking it buys nothing when the next command already decides the outcome.

##### 4d-1. Stuck-PR handling (report + STOP, never force-merge)

**The trigger is PR state, never the merge command's exit status or stderr.** The PR is **not merged** if the post-merge `gh pr view "<PR>" --json state` (command 6 above) reports anything other than `MERGED`. Typical causes: a required check failed (`gh pr checks` reported a failing check) or `gh pr view` shows `mergeStateStatus: BLOCKED`/`DIRTY`. Do **not** key this branch on `gh pr merge` "refusing" — under `pr` policy that command routinely prints `fatal: Not possible to fast-forward, aborting.` *after a merge that succeeded* (see the note above, upstream #208), and reading that as a refusal strands branches, worktrees, and `sysop/runtime/locks/` behind a close-out that actually landed. When `state` is genuinely not `MERGED`:

- **Report** the PR URL and the failing check name(s), then **STOP** — do not force-merge, do not fall back to a direct `git push origin main`, do not loop. Authority to merge belongs to the PR's required checks, not this skill.
- Leave the integration branch, the feature branches, the worktrees, and the `sysop/runtime/locks/` **in place**. **Skip Step 6 entirely** this run — its cleanup is gated on a confirmed merge (see Step 6's merge-policy gate). The human (or a follow-up `/review-close`) fixes the check and re-runs.
- Re-running is safe and idempotent **in the integration-branch shape**: the next `pr`-policy run cuts a **new** integration branch from `origin/main` and re-sweeps the same still-unpushed local-`main` commits, so nothing is double-applied. The stuck branch is left orphaned but harmless — delete it by hand (`git branch -D <branch>` + `git push origin --delete <branch>`) once its replacement merges.
- **In the PR-reuse shape the recovery is different, and the sentence above does not apply.** There is no integration branch to orphan and no new one to cut: the stuck PR is the consumer's own, still open, now carrying the Step 4b/4c commits, and a re-run's probe finds that same PR again and lands on it again. That re-run is still safe — `close_batch.sh` is idempotent (its `sed` substitutions no-op on already-`Merged` batches) and Step 4c finds no pending-docs the second time because the first run deleted them, so it skips consolidation rather than double-applying it. What it is *not* is self-healing: re-running cannot clear a red required check. Fix the check, then re-run; or if the branch has become unmergeable (`BEHIND`/`DIRTY`), rebase it onto `origin/main` and push, which makes reuse condition 5 hold again. If you would rather stop reusing it, delete nothing — just let the next run fail condition 5 or close the PR by hand, and the integration-branch shape takes over.

On a confirmed merge — `gh pr view "<PR>" --json state` reports `MERGED`, whatever the merge command's exit status or stderr said — continue to Step 5, then Step 6 cleanup.

**If a `gh pr` command is silently denied** (auto-mode classifier), the Phase 36 `PermissionDenied` hook surfaces the `!`-escape form; follow its guidance and relay to the user — same pattern as the `direct`-policy push above. Do **NOT** use `AskUserQuestion`.

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
  git checkout main
  git fetch origin main
  # Gate the reset on a clean TRACKED tree. `git reset --hard` discards every
  # uncommitted modification to a tracked file in this checkout — not only the
  # pre-merge commits the note below explains. Untracked files are NOT at risk
  # (`reset --hard` leaves them), which is why this tests `git diff HEAD` and not
  # a bare `git status --porcelain`: an untracked scratch file is ordinary in a
  # live repo and would refuse every close.
  git diff --quiet HEAD -- && echo "CLEAN — safe to reset" || echo "DIRTY — STOP, see below"
  ```

  **If that printed `DIRTY`, do not run the reset.** Report the file list (`git status --porcelain --untracked-files=no`) and ask the user to commit or stash. **Resume at this gate, not at the top of the skill** — the PR has already merged by this point, so nothing before Step 6 may be repeated: re-run `git diff --quiet HEAD --`, and continue from the reset when it reports `CLEAN`. (Do not re-enter at Step 4-pre. Its PR-reuse probe requires `origin/main..main` to be empty, which is false here by construction — local `main` still carries the pre-merge commits the reset exists to discard.) **Do not stash on their behalf** — a stash this skill creates is consumed by no later step, so it converts a visible refusal into work parked where nobody looks. Two reasons the gate belongs *here* rather than at Step 1: Step 1a's `dirty` classifier never covers this checkout (it excludes the worktree whose branch is `main`), and Step 5's staging-deploy wait is a long idle window — exactly when a human is most likely to have edits open, so a Step 1 reading would already be stale.

  > **Narrower than the shipped convention, deliberately.** Both shipped maps name `git reset --hard` by name: `convention_map.md` § *Destructive command gating* requires it "be preceded by an explicit 'ask the user to confirm' instruction in the skill text", and `security_map.md` § *Confirmation gates on destructive operations* requires "an explicit confirmation step in the skill text". This gate confirms *conditionally* — it refuses only when the reset would actually destroy something — because the reset is either a no-op or a load-bearing re-sync (see the both-shapes note below), so an unconditional prompt would land on every close of the dominant `pr` path and buy nothing in the clean case. The conventions' purpose is met; their literal reading is not. Stated rather than silently narrowed.

  ```bash
  # local main's pre-merge commits are now inside the squash. Comment on its own
  # line: `Bash(git reset --hard origin/main)` is an exact-match rule and whether
  # the matcher strips a trailing comment is undocumented (Phase 152).
  git reset --hard origin/main
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

  > **Run the `git reset --hard origin/main` in both shapes once the clean-tracked-tree gate above passes — but know why it matters in each.** `gh pr merge --delete-branch` *attempts* this re-sync itself. **Integration-branch shape:** it fails, because local `main` has diverged by construction (see Step 4d's `fatal:` note, upstream #208) — here the reset is load-bearing, and treating `gh` as having already done it leaves local `main` on pre-merge commits now duplicated inside the squash. **PR-reuse shape:** it succeeds, because reuse condition 3 required `origin/main..main` to be empty — here the reset is a harmless no-op. Upstream #204's incidental note ("`gh` fast-forwards `main` itself, so Step 6's reset was already a no-op") was reported from a cycle that met condition 3, so it was **right about that cycle and wrong as a general rule**; #208, from the same reporter, is the other shape. Neither claim generalizes — which is why this step is stated per shape rather than picking a winner.

> **Lock-as-real-time-signal invariant (`pr` policy).** Step 4c removes each closed task's `sysop/runtime/locks/<TASK-ID>.lock` from disk on the integration branch, before the PR merges — so there is a brief window where, on `main`, the task is still `in_progress` (the `done` flip rides the unmerged PR) with no lock. This does **not** reopen the task for the autonomous paths: `/auto-build` and `next_task` only ever claim `status: open` tasks, so neither can pick it up. **Amended by Phase 159b — the unqualified form of this sentence ("an `in_progress` task is never claimable regardless of its lock") is no longer true.** `/claim-task` gained a third entry state, and `in_progress` + no lock is exactly its `resumable` signature — which this window manufactures for a task that is *finished*. That is why `resumable` **stops and asks** instead of continuing: an explicitly-named `/claim-task <TASK_ID>` during this window would otherwise re-claim already-reviewed work. The other visible effects are a transient `/sitrep` "in_progress without lock" drift flag and a `validate_tasks.py` Invariant 9 error during the in-flight (or stuck-PR) window, both of which clear when the PR merges and the `done` flip lands. No action needed beyond not re-claiming. The same pre-merge timing applies to the task's **parked marker(s)** (`sysop/runtime/parked/<TASK-ID>__*.md`, removed by the same Step 4c cleanup) — with one honest asymmetry: a lock is trivially recreatable (`claim_task.sh --lock`), but a marker's content (the park's plan + adversarial verdict, never committed) is not. Accepted anyway: by the time Step 4c runs, the park was already resolved — the resume that produced this close consumed the verdict — so a stuck PR needs the *code* recoverable (the integration + feature branches Step 4d-1 leaves in place), not the historical park record. A consumer who wants park history durably should copy `parked/` entries somewhere tracked before closing.

**`direct` policy — per-branch cleanup.** For each merged feature branch (worktrees already removed in Step 3b):
1. Delete the **remote** branch first: `git push origin --delete <branch>` (if it exists remotely).
2. Delete the **local** branch: `git branch -d <branch>`.

**Why this order matters (BeanRider ISSUE-0021).** Step 4a rebases the feature branch onto main, which rewrites its SHA. The local branch's tracked upstream (`refs/remotes/origin/<branch>`) still points at the *pre*-rebase commit, so `git branch -d` refuses with `not fully merged to refs/remotes/origin/<branch>, even though it is merged to HEAD` — git's safe-delete check compares against the upstream ref, not against `main`. Deleting the remote first removes the upstream pointer, so the subsequent `-d` falls back to checking against `HEAD` and succeeds. Do **not** use `-D` (force-delete) — the safe-delete refusal is correct behavior given the upstream check; the fix is to drop the upstream first, not to bypass the check.

**If `git push origin --delete <branch>` is silently denied** (BeanRider ISSUE-0033, classifier hard-codes destructive-flag protection on `--delete`/`--force` regardless of allow-rule glob), the Phase 36 `PermissionDenied` hook surfaces the `! git push origin --delete <branch>` escape command — with the venv-prefix variant when a `.venv/` directory is present. Follow the hook's guidance and relay to the user. The subsequent `git branch -d <branch>` runs in-band without classifier interference (local-only, no remote contact). Do **NOT** use `AskUserQuestion`.

**`pr` policy — per-branch cleanup** (only after the PR merged; the local-`main` re-sync and, in the integration-branch shape, the integration-branch drop are already done in the merge-policy gate above). Each approved feature branch reached `main` through a **squash** — in the integration-branch shape by being rebased onto the integration branch and ff-merged before that branch's PR squashed, and in the PR-reuse shape by being the PR's own head. Either way the branch is provably contained in the squash commit but is **not** an ancestor of it, so `git branch -d` would refuse with "not fully merged." Force-delete here; the content is safely in `main`:
1. Delete the **local** branch: `git branch -D <branch>` (the safe `-d` check is meaningless against a squash — the branch's commits are in the merged PR).
2. Delete the **remote** branch **only if it was pushed and still exists**: `git push origin --delete <branch>`. Feature branches created by `/claim-task` are usually local-only under `pr` policy (the integration branch is the only thing pushed), so skip this when the branch has no remote tracking ref.

**Under the PR-reuse shape both of the above are usually already done for you.** The reused branch *was* the PR's head, so `gh pr merge --delete-branch` deleted it remotely, and it deletes the local branch too once `gh` has switched HEAD off it. Verify rather than assume — `git branch --list <branch>` and `git ls-remote --heads origin <branch>` — and run only the deletions that are still outstanding. A `git push origin --delete` against an already-deleted remote branch fails with `remote ref does not exist`; that is cleanup noise, not an error worth halting on.

For each **SKIP'd** branch (Step 2a verdict — Step 1a classified the worktree as `dirty`):
1. Leave the worktree, the `sysop/runtime/locks/<TASK_ID>.lock` file, and the branch fully in place — do NOT touch anything.
2. Carry the SKIP entry into Step 8's report so the user sees the paused-work list with its file count and worktree path.

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

1. **Find the friction log:** `SYSOP_ISSUES.md` at the consumer-repo root (NOT under `.claude/`). If the file is missing (consumer pre-dates Phase 13 install), emit one line: `note: SYSOP_ISSUES.md not present — re-run bash install.sh to seed. Skipping friction capture.` and proceed to Step 8.

2. **Decide whether to log:** if no friction occurred this cycle, **move on silently to Step 8**. Do NOT append a "no friction this cycle" placeholder — that adds noise without signal.

3. **Determine the next ISSUE number:** read the file, find the max existing `ISSUE-NNNN` number, increment by 1. If the file has no ISSUE entries yet, start at `ISSUE-0001`. If you can't parse the file (corrupted, unreadable), emit one line: `note: could not determine next ISSUE number from SYSOP_ISSUES.md — please file manually. Skipping friction capture.` and proceed to Step 8.

4. **Append the entry** newest-first (immediately after the `<!-- Entries below. Newest first. -->` marker, or after the `---` separator if no marker exists). Use the Template block's structure verbatim — `Status: Open`, today's date, the witnessed-symptom in `### What happened`, your diagnosis with file paths in `### Diagnosis`, a concrete proposed fix in `### Proposed fix`, a repro recipe in `### Verification`, and what unblocked the user in `### Workaround in <consumer>`.

5. **Multiple frictions:** if more than one independent friction occurred, append multiple entries with sequential numbers. Each gets its own block.

6. **If friction was resolved mid-cycle** (e.g., user manually fixed a missing permission rule): still log it. Mark `Status: Fixed in <consumer> <date>` and put the resolution in `### Diagnosis` — even resolved-in-cycle friction is signal that Sysop's seeded ruleset / templates are incomplete.

**Positive signal (`[good]`) — same moment, same reflex:** friction isn't the only signal worth catching at close-out. If something Sysop did *notably well* this cycle stood out — a guardrail that fired correctly, a clear error that unblocked you, a step that just worked under an unusual setup — capture it too, so a later change doesn't quietly "fix" it. Prompt once: *"Anything Sysop did that worked notably well and is worth protecting from a future change?"* If yes, append a `[good]` entry using the positive-signal template in `SYSOP_ISSUES.md` (`## GOOD-NNNN — <title> (<date>)  [good]`, `Status: Good — keep`, a `### What worked` naming the skill / installer step / guardrail). Same witness-limited discipline — only what you observed this session, don't fabricate, don't extrapolate. No standout this cycle → say nothing and move on. This is what a tester round otherwise drops: the maintainer learns what to fix but not what to protect. (`[good]` entries are captured locally; **send them upstream with `/share-wins`** — the positive-signal sibling of `/report-issues`, which batches a round's wins into one comment on the Sysop repo's Wins discussion, per-entry consent, and flips each shared entry to `Status: Shared` so re-runs never double-post.)

This step is best-effort. If anything goes wrong (file unwritable, you're unsure which friction qualifies), prefer a single one-line note and move on rather than blocking close-out. The user can always file manually.

**Capture here, send with `/report-issues`.** This step only *captures* friction into `SYSOP_ISSUES.md` (local, project-owned). To get an entry upstream to the Sysop maintainer, the transport half is the `/report-issues` skill — it renders each `Open`/`Prompt-ready` entry as a GitHub issue, files the ones you consent to (per-entry) against the Sysop repo, and flips each filed entry to `Status: Filed to Sysop` with a `**Filed:** <url>` back-reference. That flip is why re-running `/report-issues` never double-files. Nothing here depends on it — capture stands alone — but a tester running Sysop should send periodically rather than let the log accrue unseen.

## Step 8: Report

Summarize what was done:

```
Review Complete.

Pushed:        <N> commits to origin/main
Branches:      <merged list> (or "none")
Docs:          Consolidated <N> pending-docs files (or "none" / "legacy docs: commits")
Manual smoke:  <N confirmed, N driven, N waived> (or "none required")
Verification:  pre-merge <ran | skipped: doc-only | skipped: no changed-file list>;
               merged-tree (4a-post) <ran on <merge target> | not reached: why>
               <per-surface skips, e.g. "skipped frontend — not in this run's changed files">
Unverified surfaces: <changed code files no detected surface claimed> (or "none")
Conventions:   <N checked, N skipped (doc-only)> (or "none to check")
Test decisions: <N verified, N waived, N held-for-fix, N unreadable, N doc-only> (or "none to verify")
Staging:       <verified / skipped / broken>
Locks cleaned: <list> (or "none")
Parked markers: <removed TASK-ID list> (or "none")
Friction:      <N entries appended to SYSOP_ISSUES.md> (or "none" / "log missing")
Signal:        <N [good] entries appended> (or "none")

Documentation written:
  ✓ PROJECT_STATUS.md §6: <N> new entries    (if any)
  ✓ changelog.md:         <N> entries         (if any)
  ✓ tasks/index.yml:      <task IDs>          (if any — status flipped to done, body moved to archive/)
  ✓ UI_Iterations.md:     <N> rows            (if any)

Remaining:
  - <any SKIP'd branches — paused work; include file count + worktree path + recommendation>
  - <any rejected branches with reasons>
  - <any remote branches needing manual cleanup>
```

If `$ARGUMENTS` contains `--dry-run`, perform Steps 1-3 only and report what *would* be done without making changes. **`4a-post` cannot run under `--dry-run`** — it needs the merges — so report the resolved command list and say the merged-tree gate did not run. Do not let Step 3's green stand in for it; that substitution is the defect the two-pass split exists to remove.
