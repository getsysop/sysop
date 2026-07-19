---
name: review-close
description: Senior review — review pending work, push to origin, verify staging, clean up
argument-hint: "[--dry-run]"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning inline=reasoning -->

Final gate before production. Reviews all pending work (feature branches AND unpushed main commits), pushes to origin, verifies staging, and cleans up.

## Pre-flight: Permission Guard

Before doing anything, verify `.claude/settings.json` carries the allow-rules this skill depends on. Under `permissions.defaultMode: "auto"` with `skipAutoPermissionPrompt: true`, a missing rule on `git merge --ff-only` or `git worktree remove` surfaces as a silent halt mid-merge.

Read `.claude/settings.json` and confirm `permissions.allow` contains every rule below (exact-string match):

- `Bash(git checkout:*)`
- `Bash(git rebase:*)`
- `Bash(git rebase --abort)`
- `Bash(git merge --ff-only:*)`
- `Bash(git worktree list:*)` — Step 1a + Step 3c's `--porcelain` worktree enumeration
- `Bash(git worktree remove:*)`
- `Bash(git branch -d:*)`
- `Bash(git push origin:*)`
- `Bash(bash sysop/scripts/close_batch.sh:*)`
- `Bash(bash sysop/scripts/run_checks.sh)`
- `Bash(bash sysop/scripts/run_checks.sh:*)`
- `Bash(python3 -:*)` — Step 3c's smoke-gate detection heredoc **and** Step 4c's yaml-round-trip status flip + git mv. Both are single `python3 - <<` commands (literal `python3` command word, no PATH prefix or `&&` compound) so this one rule matches; venv PyYAML is resolved by an in-heredoc `sys.path` bootstrap, not a `.venv/bin/python3` invocation or an env prefix (BeanRider ISSUE-0049; Sysop Phase 126 — a `.venv/bin/python3` command word or a `VAR=… python3` prefix would each bind to no rule)
- `Bash(python3 sysop/scripts/validate_tasks.py)` — Step 4c's final-guard validator run (bare `python3`; the script self-resolves venv PyYAML via its own `sys.path` bootstrap, so this one form serves both venv-only and non-venv consumers — Sysop Phase 126)
- `Bash(python3 sysop/scripts/validate_tasks.py:*)` — same with `--quiet` / `--path`

**Additionally, under `pr` merge policy only** (read `<project>/CLAUDE.md § Merge policy`; default is `direct` — see Step 4-pre): the PR-routed flow shells out to `gh` and a few extra git verbs. Require these too **only when the policy is `pr`** — a `direct`-policy consumer does not need them and must not be blocked for their absence:

- `Bash(git fetch origin:*)` — Step 4-pre cuts the integration branch off fresh `origin/main`
- `Bash(git cherry-pick:*)` — Step 4-pre sweeps local-only `main` commits onto the integration branch
- `Bash(git reset --hard origin/main)` — Step 6 re-syncs local `main` after the PR squash-merges
- `Bash(git branch -D:*)` — Step 6 deletes the integration + squash-merged feature branches
- `Bash(gh pr create:*)` — open the integration PR against `main`
- `Bash(gh pr checks:*)` — wait on the PR's required checks
- `Bash(gh pr view:*)` — read the PR's merge state
- `Bash(gh pr merge:*)` — squash-merge the integration PR (non-`--auto`)

If any required rule (the always-required git set above, plus the `gh`/git set when the policy is `pr`) is missing, stop with the error message from `_shared/permission-guard.md` § Algorithm step 4 (substitute "merges approved feature branches and either pushes `main` directly or — under `pr` policy — assembles an integration branch and opens a squash-merge PR; updates `tasks/index.yml` via heredoc'd python and runs the validator as a final guard" as the one-line reason). Do not proceed.

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

Branch tips are blind to uncommitted in-progress work. A `/claim-task`-ed branch where the agent did substantial worktree edits but never committed has a tip identical to a freshly-claimed branch with no work yet — Step 2a's commit-based verdict would say "no commits, reject" for both, and Step 6's cleanup would then try to remove the worktree. If a downstream codepath ever reaches for `--force` on `git worktree remove` (some `/auto-judge` and `/document-work` cleanup paths legitimately do when the worktree is expected to be clean), uncommitted work is silently destroyed.

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
- **`dirty`** — after the symlink downgrade above, the *significant* set (`git status --porcelain` minus the downgraded lines) is still non-empty. **Paused mid-implementation work.** Step 2a will produce an automatic SKIP verdict for this branch and Step 6 must refuse to touch the worktree. Two classes of noise are already excluded so they don't false-positive into `dirty`: gitignored `.locks/` and `.pending-docs/` never appear in `--porcelain` without `--ignored`; and an untracked symlink whose target is gitignored in the main repo (a `.venv`-into-the-main-venv tooling convenience) is downgraded out of the significant set (BeanRider ISSUE-0043). Everything with reviewable content — modified tracked files, real untracked files, and any symlink whose target is not provably ignored — stays significant, so the silent-data-loss guard is unweakened.

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
BRANCHES_TO_MERGE=$(git for-each-ref --format='%(refname:short)' refs/heads/ | grep -v '^main$')

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

For every non-main local branch:

0. **Worktree-state pre-check (Step 1a result).** If Step 1a classified this branch's worktree as `dirty`, the verdict is **SKIP — paused work present**. Do NOT inspect the diff and do NOT propose approve/reject — uncommitted worktree changes mean the branch is mid-implementation, not in a reviewable state. Report the dirty file count and the recommendation: *"`<N>` pending changes in `<worktree-path>`. Commit-as-WIP, stash, or leave alone — re-run `/review-close` after the user decides. This branch is excluded from Step 3b (worktree removal), Step 4 (merge), and Step 6 (cleanup) for this run."* Then continue to the next branch. A SKIP'd branch is distinct from both `approve` and `reject`: it is not merged, but its worktree, lock, and branch are all preserved untouched.

1. `git log main..<branch> --oneline` — what commits are on it
2. `git diff main..<branch> --stat` — scope of changes
3. Read the diff. Check for correctness, security issues, and alignment with the task body at `tasks/<status>/<TASK_ID>.md` (path resolved from `tasks/index.yml`'s `body:` field for each task ID the branch claims)
4. Verdict: **approve** (merge to main) or **reject** (report reason, leave branch)

### 2b. Prevention Convention Check

For each feature branch (and for any unpushed main commits as a group), spawn an Opus subagent to perform the convention review. These calls can be parallelized — launch one agent per branch simultaneously.

**For each branch:**

1. Read the **entire** `## Prevention Conventions` section of `CLAUDE.md` (every subsection — subsection names vary by project: a web project might have `Frontend`/`Backend`/`Testing`; a data-pipeline project might have `Data integrity`/`Privacy`/`Testing Patterns`; an MCP server might have `MCP server boundaries`). Retrieve the full diff (`git diff main..<branch>`).

2. Spawn an Agent with:
   - `subagent_type: "general-purpose"`
   - `model: "opus"` (always — the **reasoning** role: adversarial convention review; do not omit, per `.claude/served_models.yml`)
   - `description: "Convention check: <branch-name>"`
   - `prompt`:

     ```
     You are the final security gate before this branch merges to production. Review
     the diff below for violations of the project's Prevention Conventions.

     ## Branch
     <branch name>

     ## Diff
     <full unified diff from git diff main..<branch>>

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
     ```

3. Collect all verdicts. If **any** subagent returns `VERDICT: BLOCKED`, list every violation with its file:line citation and **stop** — do not proceed to Step 3 until violations are fixed or explicitly waived by the user.

### 2c. Unpushed Main Commits

If main is ahead of origin:
1. `git log --oneline origin/main..HEAD` — list the unpushed commits
2. Review each commit's changes: `git show --stat <hash>` for each
3. Verify the changes look intentional and complete (no half-finished work, no debug code left in)
4. Check that documentation is accounted for: either `docs:` prefixed commits exist (legacy) or `.pending-docs/*.md` files are present (current workflow)

### 2d. Test-Decision Verification (verify the record — Phase 59, C1)

Every task claimed through `/claim-task` records a **test decision** in its body at plan time (Phase 58b): either `test <X> proves <Y>` (the regression test that pins the changed behavior) or `no test because <Z>` (the reviewable rationale for adding none). See `tasks/schema.md` § Test decision. This step **verifies that record against what the branch actually delivers** — the read-and-verify gate that closes the loop the validator's warn-only Invariant 13 opens at plan time. It does **not** re-judge whether a test *should* exist; that judgment is the adversarial plan reviewer's "Missing invariant tests" dimension (`_shared/adversarial-review.md` finding #7), applied at plan time. Verify the record, don't re-judge.

This is the sibling of Step 3c's manual-smoke gate — a per-task body convention, warned by the validator, enforced here — and reuses the same shape: a deterministic classification (like Step 1a's worktree verdict) plus an `AskUserQuestion` halt on mismatch (like Step 3c).

For each **approved** feature branch (Step 2a verdict), for each task ID it claims (resolved exactly as in Step 2a step 3 — `tasks/index.yml`'s `body:` per claimed ID):

**0. Per-branch doc-only skip.** If this branch's diff (`git diff main..<branch>`) touches no code files (the same code-file set Step 3 uses — `.py` / `.ts` / `.tsx` / `.js` / `.jsx` / `.sql` / `.sh` / `.kt` / `.swift` / `.go` / `.rs`), skip verification for it with a one-line note (`2d: <branch> — doc-only diff, no test decision to verify`). A test decision over a doc-only change is incoherent — there is no behavior to pin.

**1. Read the record.** Open the task body and find the section under a heading whose text matches `test\s+decision` (case-insensitive — `## Test decision`, `### Test Decision` both match; same pattern as validator Invariant 13). Classify it:

- **`test-proves`** — the section names a test (the `test <X> proves <Y>` shape).
- **`no-test`** — the section states `no test because <Z>`.
- **`missing`** — no test-decision heading, or the section still holds the schema template placeholder (`<recorded at /claim-task plan time …>`).

**2. Verify the record against the branch diff:**

- **`test-proves` → "plan said test X — is it here?"** Confirm the diff adds or modifies a test matching X — a changed file on the project's test path (`tests/`, `*_test.py`, `*.test.ts`, `*.spec.ts`, or the project's documented test location) and, when X names a specific test/function, that name appearing in the diff. If the diff touches **no** test file at all, the record claims a test that wasn't delivered → **discrepancy**. (Record-vs-reality only: a test that is present but weak is out of scope here — that's the reviewer's coverage judgment, not this gate's.)
- **`no-test` → "plan said no-test-because-Z — does Z still hold?"** Re-read `Z` against the diff. `Z` **holds** when the diff's character still matches the stated rationale (pure rename/move, config-only, docs-only, covered by an existing named test, `manual_smoke:`-only). `Z` is **stale** when the diff now carries behavior changes the rationale didn't anticipate (e.g. `Z` said "pure rename" but the diff edits logic) → **discrepancy**. This carries inherent judgment residue — acknowledged and bounded: you are matching the recorded rationale to the diff, **not** forming a fresh opinion that a test ought to exist.
- **`missing` → record absent.** Invariant 13 already warned at validation time; the gap now reaches the merge gate → treat as a discrepancy to surface.

**3. On a clean match, pass silently** (carry a `verified` note for Step 8). **On any discrepancy or missing record, halt and ask** via `AskUserQuestion` (one task at a time, mirroring Step 3c). Present the recorded decision text verbatim, the task ID, and what the diff shows. Three options (single-select):

- **"Record holds — proceed"** — the human confirms the record is accurate or the rationale still applies; the branch stays approved.
- **"Hold for fix — don't merge this run"** — demote this branch from **approved** to **rejected** for this run, with the reason `test-decision record needs fixing — <detail>`. Downstream steps already handle a rejected branch correctly with no special-casing: Step 3b/Step 4 skip it (only approved branches merge), Step 6 leaves its worktree, lock, and branch intact for follow-up, and Step 8 reports it under "Remaining" with the reason. The test can then be added or the record corrected before a later `/review-close`.
- **"Waive — proceed with noted waiver"** — the branch stays approved; record a waiver (task ID + decision text) for Step 8. Use for accepted judgment calls (e.g. a stale-looking `Z` the human confirms is fine).

Waivers and "record holds" do not block. Only "hold for fix" changes the verdict, and it does so by reusing the existing **reject** disposition — no edits to Steps 3b/4/6 are needed.

**4. Record outcomes for Step 8.** Tally per task: `verified`, `waived`, `held for fix` (now rejected), or `skipped (doc-only)`. This drives the "Test decisions" line in the final report.

If the approved-branch set is empty (only unpushed main commits this cycle), Step 2d is a no-op — unpushed main commits don't carry `/claim-task` test-decision records. Skip cleanly.

> **For new projects:** the test decision is authored at `/claim-task` Step 6 into the task body (`tasks/schema.md` § Test decision). This gate reads it back — keep the `Z` in a `no test because Z` rationale concrete so "does Z still hold?" stays answerable.

## Step 3: Run Verification

Before pushing anything, discover the project's verification commands and run them. Resolve in this order — stop at the first source that produces a command list:

1. **`<project>/CLAUDE.md` § "Pre-merge verification"** (preferred — the project owns its command list). Two shapes are supported:
   - **Split sub-headings (recommended).** If the section uses `### Always` and/or `### Ratchet (changed files only)` sub-headings, run them in that order:
     - **`### Always`** — full-tree commands run unconditionally (build, full test suite, project-level smoke tests). Bullet list; one command per bullet.
     - **`### Ratchet (changed files only)`** — project-supplied shell snippets in a single bash code block. Each snippet is expected to filter `git diff --name-only origin/main...HEAD` to its file-type of interest and invoke lint/typecheck against only the changed files. Run the block as-is from the repo root. A snippet whose filtered changed-file list is empty short-circuits and passes — that's project-side logic, not a Sysop rule. Treat the snippets as project-trusted input — they run with full agent shell privileges. If you didn't write them yourself, read the block before running it.
   - **Flat list (backward compatible).** If neither sub-heading exists, treat all bullets under `## Pre-merge verification` as the `### Always` list and skip the ratchet step.
2. **`package.json` `scripts.verify`** (if `package.json` is at the repo root or `<frontend>/`). If at repo root, run `npm run verify`. If at `<frontend>/`, run `(cd <frontend> && npm run verify)` from the repo root.
3. **Auto-detect from common surfaces**:
   - `frontend/` exists with `package.json` → `cd frontend && npm run build && npm run test`
   - `pyproject.toml` exists with `pytest` declared in `[project.optional-dependencies]` (any extra) → `python -m pytest tests/`
   - `Cargo.toml` exists → `cargo test --release`
   - Other detectable surfaces → run the platform-native test/build command.
4. **If the diff is doc-only** (no `.py` / `.ts` / `.tsx` / `.js` / `.jsx` / `.sql` / `.sh` / `.kt` / `.swift` / `.go` / `.rs` files changed — only `.md` / `.txt` / `.yaml` config / etc.): skip verification with a one-line note (`Step 3: skipped — diff is doc-only`). Step 4 (push) still runs. This skip applies to both `### Always` and `### Ratchet` — a doc-only diff can't regress code-level lint/typecheck.
5. **If none of the above fire and the diff touches code**: stop and ask the user what to run. Do not invent commands. Do not run `pip install` or any state-mutating command during verification — verification is read-only.

If any command fails, report the failure and **stop**. Do not push with failing checks.

**Venv-aware invocation.** If a verification command fails with `exit 127` (command not found) or `ModuleNotFoundError` and the project has a `.venv/` directory at the repo root, re-run with `.venv/bin/<cmd>` (for explicit binaries like `.venv/bin/pytest`) or `PATH=.venv/bin:$PATH <cmd>` (for shell pipelines or tools that re-exec). Same pattern as Step 4d's pre-push hook venv prefix. The canonical fix is consumer-side — the project's `<project>/CLAUDE.md § Pre-merge verification` commands should be authored with `.venv/bin/` prefixes when they depend on venv-installed tools (see WORKFLOW.md § 6.1 venv-aware-invocation paragraph) — but the prefix-on-rerun pattern unblocks the cycle when the consumer's command list hasn't been venv-ified yet.

**Boy-scout escalation (ratchet consequence).** A `### Ratchet` snippet invokes the project's lint/typecheck tool against the changed-file list, so if a file in the diff carries pre-existing findings — warnings or type errors not introduced in this review pass — the tool will report them and the gate will fail. That's intentional and not a Sysop-side rule: touching a file means cleaning it. Full-tree backlog cleanups stay as separate project-side tasks (e.g. `TECH-LINT-BACKLOG-FIX`, `TECH-TYPECHECK-BACKLOG-FIX` entries in `tasks/index.yml`), so the ratchet doesn't impose a clean-everything-first dependency on consumers with existing backlogs.

**If a verification command is silently denied** (auto-mode classifier rejects a `npm` / `pytest` / `cargo` / project-specific invocation): prompt the user to run that command themselves via `!`-shell-escape in their prompt — the same pattern Step 4d uses for protected-branch pushes. Do NOT use `AskUserQuestion`; ask for the literal `!`-prefixed command. Step 0's permission guard cannot anticipate every project-specific verification command. (Phase 36's `PermissionDenied` hook only surfaces guidance for the well-known git patterns in Steps 4c/4d/6 — verification commands vary too widely per consumer to enumerate, so this prose remains the load-bearing instruction here.)

> **For new projects:** add a `## Pre-merge verification` section to your CLAUDE.md (template in WORKFLOW.md § 6.1) listing the exact commands this skill should run. That keeps verification deterministic across consumer projects with different stacks.

## Step 3c: Manual Smoke Gate (BeanRider ISSUE-0008, Phase 35)

Some features can't be verified by automated checks — UI flows that need a browser, commands with external side effects, LLM round-trips whose output a human must eyeball. The contract: a task in `tasks/index.yml` may carry `manual_smoke: true`, and/or a `.pending-docs/*.md` body may contain a heading matching `manual smoke` / `smoke required` (case-insensitive). Either signal halts this step until the human runs, confirms, or waives the procedure.

If Step 3 was skipped (doc-only diff), skip Step 3c too — a smoke gate over a doc-only change is incoherent.

**1. Detect signals.** The gate reads pending-docs from **main's `.pending-docs/` and each approved branch's worktree** — a `/claim-task` worktree authors its pending-doc there, and it is not copied to main until Step 3b (merge time). Reading the worktrees *in place* keeps the gate honest without collecting docs early: collecting before the merge would break the invariant Steps 4c/6 depend on — "everything in main's `.pending-docs/` belongs to a just-merged branch" — and a branch SKIP'd at Step 3b (worktree remove-refusal, ISSUE-0016) or a whole-run halt could then leave a stray doc that a later Step 4c consolidates for unmerged work, marking its task `done` with the code never merged (BeanRider ISSUE-0050). List this run's approved branches (the same set Step 3b merges), then run the heredoc from the repo root. Output is either `NO_SMOKE_REQUIRED` (proceed to Step 3b) or `SMOKE_REQUIRED: N signal(s)` followed by one `---SIGNAL---` block per signal:

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
# Search each approved branch's worktree .pending-docs/ AND main's (BeanRider ISSUE-0050
# — worktree-authored docs aren't copied to main until Step 3b). Worktrees FIRST: if a doc
# exists in both (a stale copy a prior halted run left in main + the fresher worktree
# original), the worktree — the authoring source of truth — must win the basename dedup
# below, so a newly-added smoke heading is never shadowed by the stale main copy.
search_dirs = []
for _d in sys.argv[1].splitlines():
    _d = _d.strip()
    if _d:
        search_dirs.append(Path(_d) / ".pending-docs")
search_dirs.append(repo / ".pending-docs")

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

**4. Record outcomes for Step 8.** The tally drives the "Manual smoke" line in the final report (e.g., `Manual smoke: 1 confirmed, 1 waived (.pending-docs/feat-foo.md)`).

> **For new projects:** declare `manual_smoke: true` on `tasks/index.yml` entries whose verification needs a human (browser flow, side-effect-bearing command, LLM round-trip). Author the procedure under a `## Manual smoke required` heading in the task body file. The validator warns (not blocks) when the field is set but the heading is missing — see `tasks/schema.md § Manual smoke`.

## Step 3b: Prepare Worktrees for Merge

Feature branches created by `/claim-task` or `batch_work.sh` live in worktrees. Branches checked out in a worktree cannot be checked out from main, so worktrees for **approved** branches must be removed before merging.

For each approved feature branch:
1. Check if it has a worktree: `git worktree list` and match the branch name
2. If a worktree exists:
   a. **Collect pending-docs**: Copy `.pending-docs/*.md` from the worktree to main's `.pending-docs/` (these are untracked files that would be lost when the worktree is removed): `cp <worktree>/.pending-docs/*.md .pending-docs/ 2>/dev/null`
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
      for f in "<worktree-path>"/.pending-docs/*.md; do
        [ -e "$f" ] && rm -f ".pending-docs/$(basename "$f")"   # re-collected on a later run once mergeable
      done
      ```

      Then downgrade this branch to SKIP for this run (leave its worktree, lock, and branch intact), and continue with the next approved branch. Silent data loss is the failure mode this guard prevents (BeanRider ISSUE-0016) — the strip never touches a real file, so it cannot cause it. (The rollback matters because step (a) copies before this remove is attempted; without it, a branch SKIP'd here leaves its doc stranded in main's `.pending-docs/` for the merged branches' Step 4c to consolidate.)
3. If no worktree exists, the branch is already free for checkout

For **SKIP'd** branches (Step 2a verdict, dirty worktree), do nothing here — the worktree stays.
For **rejected** branches, leave worktrees in place (cleaned up in Step 6).

## Step 4: Merge & Land on Main

### 4-pre. Determine Merge Policy & Target

How approved work reaches `main` depends on the project's **merge policy** — read it from `<project>/CLAUDE.md § Merge policy` (the same "consumer declares its shape" pattern as Step 3's `§ Pre-merge verification`). Two values; **default `direct`** when the section is absent:

- **`direct`** (default) — feature merges, batch close, and doc consolidation land on `main` locally, then `git push origin main`. Correct for any project whose `main` accepts a direct push (no required status check, no `enforce_admins`). This is the historical flow; a consumer who never configured a merge policy keeps it with zero change.
- **`pr`** — `main` is never written directly. Everything is assembled on a throwaway **integration branch** cut from fresh `origin/main`, pushed, and merged into `main` through a squash PR. Required when `main` is push-protected (a required CI check and/or `enforce_admins`) — a direct push would be rejected. GitHub becomes the sole serialized writer of `main`, which also removes the race against a concurrent auto-merge (e.g. Dependabot) landing on `main` mid-close.

Set `$MERGE_TARGET` for the rest of Step 4 from the policy:

**`direct`:**
```bash
MERGE_TARGET=main
git checkout main
```

**`pr`:** cut the integration branch off the **live** `origin/main` (so the PR's required checks run against the current base — an auto-merged commit may have landed since this run started), then sweep any local-only `main` commits onto it. Those commits are the `open → in_progress` claim flips from `/claim-task` Step 4d & `/auto-build` Step 5.4 and any Step 1b `review_tasks.md` save/rotation — all committed on `main` locally but never pushed, so the fresh branch does not carry them yet. At close time every local-only `main` commit belongs to this cycle; if you have unrelated un-pushed `main` work, resolve it before running `/review-close` under `pr` policy.

```bash
git fetch origin main
RUN_ID="$(date -u +%Y%m%dT%H%M%S)"
INTEGRATION_BRANCH="merge/review-close-${RUN_ID}"
git checkout -b "$INTEGRATION_BRANCH" origin/main
MERGE_TARGET="$INTEGRATION_BRANCH"

# Sweep local-only main commits (claim flips + Step 1b doc saves) onto the branch,
# oldest first. No-op when origin/main == main. A conflict means origin/main advanced
# over the same lines (rare — Dependabot touches deps, not tasks/index.yml); resolve it,
# or `git cherry-pick --abort` and re-cut the branch from local `main` instead.
for sha in $(git rev-list --reverse origin/main..main); do
  git cherry-pick "$sha"
done
```

> **HARD RULE — branch guard.** Steps 4a–4c run in the shared **primary** worktree, which has a single `HEAD`; a concurrent local actor can move it off the branch you expect mid-flow, landing commits on the wrong branch. Apply `_shared/main-push-guard.md` **Rule A** before **every** commit in Step 4. Under `direct` policy assert against the literal: `test "$(git rev-parse --abbrev-ref HEAD)" = "main"`. Under `pr` policy assert against the integration-branch **pattern** — `case "$(git rev-parse --abbrev-ref HEAD)" in merge/review-close-*) : ;; *) echo STOP; exit 1 ;; esac` — and **not** `test "$(...)" = "$INTEGRATION_BRANCH"` when `$INTEGRATION_BRANCH` was itself recovered from `HEAD` (Step 4-pre / the variable-persistence note below): comparing HEAD against a HEAD-derived value is a tautology that passes even after a hijack. On failure, STOP and reconcile via `git reflog` (cherry-pick your stranded commits onto the expected branch) — never commit blind. Per **Rule C**, **never** force-push `main` or the integration branch.

> **Variable persistence across steps.** `$RUN_ID`, `$INTEGRATION_BRANCH`, and `$MERGE_TARGET` are referenced in Steps 4a–4d and Step 6, which the skill runner executes as **separate** shell calls — exported variables do **not** persist between them. Re-export the values at the top of each later `pr`-policy step; never run a later `git merge` / `git checkout` / `git branch -D` with any of them empty. Through Steps 4a–4c, HEAD is the integration branch, so it is always recoverable with `INTEGRATION_BRANCH="$(git rev-parse --abbrev-ref HEAD)"` (and `MERGE_TARGET="$INTEGRATION_BRANCH"`) — but only for use as the `git merge` / `git checkout` / `git branch -D` operands. Do **not** feed that HEAD-recovered value into the Rule A branch-assert (the HARD RULE above): asserting HEAD against a value just read from HEAD always passes, even after a hijack. For the assert, guard on the fixed `merge/review-close-*` pattern instead, which needs no remembered name. `$RUN_ID` matters only for the branch name and PR title — if lost, read the branch name back rather than regenerating it.

### 4a. Merge Approved Feature Branches

For each approved feature branch (oldest first), merge it into `$MERGE_TARGET` (set in Step 4-pre — `main` under `direct` policy, the integration branch under `pr`):
1. `git checkout <branch> && git rebase "$MERGE_TARGET"`
2. `git checkout "$MERGE_TARGET" && git merge --ff-only <branch>`
3. If rebase has conflicts: `git rebase --abort`, report the conflict, skip that branch.

Feature branches MAY modify `review_tasks.md` — typically as single-line task-checkbox flips (`[/]` → `[x]`) that rebase clean. Structural conflicts arise when `$MERGE_TARGET` has moved `review_tasks.md` between branch-cut and rebase, in two common cases: (a) another already-merged batch added a sibling `### Batch N` section, (b) the project's archive-rotation script (e.g., `archive_review_tasks.py`) rotated rounds or batches out into a sibling archive file (committed by Step 1b — and, under `pr` policy, swept onto the integration branch by Step 4-pre). Resolve by reading both sides of the conflict: keep the merge target's structure as authoritative (it reflects the post-rotation / post-other-batch layout), then re-apply the branch's intent — checkbox flips and any net-new `### Batch N` section — in the new layout. Genuine code-overlap conflicts still surface here too; treat them the same way (resolve, don't abort).

### 4b. Close Merged Batches

After all branches are merged but **before** doc consolidation:

```bash
bash sysop/scripts/close_batch.sh <N1> <N2> <N3>
```

This script updates `review_tasks.md` on the checked-out branch (`$MERGE_TARGET` — it resolves the repo via `git rev-parse --show-toplevel`, so it commits to whatever branch is current): sets batch headers to `Merged`, marks all task checkboxes `[x]`, updates the Statistics table, and adjusts the Grand Total counts. One commit is created for all closed batches.

**Under `pr` policy, always pass `--force`** — the integration branch is cut from `origin/main`, so it is not a descendant of the batch commit tips and the default merge-base ancestry check would reject the close. (`--force` skips that check; it is the documented escape and lands the close commit on the integration branch.)

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

1. **Scan for pending docs**: `ls .pending-docs/*.md 2>/dev/null`

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

   The fallback covers in-flight pending-docs authored before the `task_ids` → `roadmap_ids` rename (Phase 23a). Treat any IDs read via the fallback as `roadmap_ids` — that matches the pre-rename consumer behavior (Step 4c's heredoc was already treating them as roadmap IDs, just silently no-op'ing on the non-matches). **Removal trigger:** drop the `or pending.get('task_ids')` clause in any subsequent phase that touches Step 4c, once BeanRider has run one full `/review-close` cycle on a pending-doc authored after the 23a absorption (confirmable via `git log -p .pending-docs/` or via the merged consolidation commit). Pending-docs are minutes-to-hours lived; the shim's exposure window is one absorption cycle.

4. **Route by type and write to shared docs** (single pass, no conflicts since we're on main post-merge):

   Use this routing table to determine which shared docs to update for each entry. The "Roadmap" column shows which frontmatter field drives the `tasks/index.yml` round-trip; `review_task_ids` is **documentary only** and never consulted here (review-task closure happens in Step 4b via `bash sysop/scripts/close_batch.sh`).

   | Type | PROJECT_STATUS | Changelog | UI_Iterations | Roadmap (`roadmap_ids`) |
   |---|---|---|---|---|
   | feature | Yes | — | — | if populated |
   | bugfix | Yes | Yes | — | if populated |
   | ui-iteration | Yes | — | Yes | if populated |
   | infrastructure | Yes | — | — | if populated |
   | adhoc | Yes | — | — | if populated |

   The Roadmap column is **informational only** — `if populated` means the `tasks/index.yml` round-trip below runs unconditionally for every ID in `roadmap_ids`, regardless of `type`. This is intentional: the round-trip is mechanical (status flip + body move + lock cleanup), driven by data presence, not by type. A pending-doc with `roadmap_ids: []` simply skips the round-trip naturally. (BeanRider ISSUE-0034: tracked-bug close-outs use `type: bugfix` with a populated `roadmap_ids: [BUG-NNNN]` and need the round-trip; the prior `—` reading would have left the BUG entry stuck `in_progress` with the body orphaned under `open/`.)

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
   for t in d.get('tasks', []):
       if t['id'] not in ids:
           continue
       t['status'] = 'done'
       t['completed_date'] = today
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
       subprocess.run(['git', 'mv', src, dst], check=True)
       t['body'] = new_body
       # Drop the per-task lock file (BeanRider ISSUE-0035). The lock's lifecycle
       # is open → in_progress (claim_task --lock creates it) → done (here). Leaving
       # it behind clutters .locks/ and confuses the "is anyone working on this?"
       # signal. `.locks/` is .gitignored, so this is a working-tree-only operation
       # — no stage, no commit. `missing_ok=True` tolerates pre-Phase-32 tasks
       # whose locks already got cleaned up by hand.
       Path(f'.locks/{t["id"]}.lock').unlink(missing_ok=True)
   p.write_text(yaml.safe_dump(d, sort_keys=False, default_flow_style=False, allow_unicode=True, width=120))
   PY
   python3 sysop/scripts/validate_tasks.py || { echo "validator rejected the index — aborting"; exit 1; }
   ```

   **UI_Iterations.md** (ui-iteration type only): Generate table row `| <name> | <date> | <summary> | <commit-hash> |`. Append to the markdown table.

   <!-- Canonical process: WORKFLOW.md §2.8 (Senior Merge & Verification) -->

   <!-- Convention promotion moved to /codebase-review and /security-audit Step 9 -->

6. **Clean up pending-docs**: Delete all remaining `.pending-docs/*.md` files. Remove the `.pending-docs/` directory if empty.

7. **Commit**: `docs: consolidate documentation for <N> merged branches`

   **If the commit is silently denied** (auto-mode classifier rejects `git commit` on `main` — a `direct`-policy concern; under `pr` policy this commit lands on the integration branch, not `main`, so it does not hit this wall), the Phase 36 `PermissionDenied` hook surfaces the `!`-escape command and the multi-`-m`-flag rewrite recipe — follow its guidance and relay to the user. Background: the classifier extends protected-branch policy upstream from the push to its enabling commit when context implies an imminent push, so the first `docs(tasks):` commit of a cycle goes through but the Step 4c consolidation commit hits the same wall as the Step 4d push. The hook's `additionalContext` names the specific escape form; this skill stays brief on purpose to avoid drifting from the hook's authoritative phrasing.

### 4d. Land on `main`

How the assembled work reaches `main` depends on the merge policy from Step 4-pre.

#### `direct` policy

Once all merges and doc consolidation are complete (or if there were only unpushed main commits), push `main` via the **`_shared/main-push-guard.md` Rule B safe-push sequence** rather than a bare push — assert-on-`main` (Rule A) → `git fetch origin main` → rebase-first if `origin/main` advanced (an autonomous auto-merge, e.g. Dependabot) → push the exact verified tip (`git push origin "<SHA>:main"`, **never `--force`** per Rule C) → confirm `origin/main` equals the SHA you pushed. The rebase-first step also re-runs the Step 3 verification gate against the new base. The bare `git push origin main` is safe only when `origin/main` has not moved; Rule B makes that check explicit instead of assumed.

Then confirm the push succeeded.

If the push is **rejected because `main` is protected** (`! [remote rejected] main -> main (protected branch hook declined)`, a required status check, or `enforce_admins`), the project's `main` requires the PR flow: set `§ Merge policy: pr` in `<project>/CLAUDE.md` and re-run `/review-close`. This is the exact failure the `pr` policy exists to handle — do not try to force the push.

**If push is silently denied** (auto-mode classifier rejects pushing to a protected branch), the Phase 36 `PermissionDenied` hook surfaces the `! git push origin main` escape command — and the venv-prefix variant (`! PATH=.venv/bin:$PATH git push origin main`) when the consumer's repo has a `.venv/` directory. Follow the hook's guidance and relay to the user. The canonical consumer-side fix is unchanged: the project's `sysop/scripts/hooks/pre-push` should prepend `${REPO_ROOT}/.venv/bin` to its `PATH` at the top of the hook (see WORKFLOW.md § 6.1 venv-aware-invocation paragraph). Do **NOT** use `AskUserQuestion` — empirically the classifier does not honor its answer for protected-branch pushes and you'll burn a turn on a dead-end handshake. See WORKFLOW.md § 8.2a for the full rationale.

#### `pr` policy

`main` is written only through a PR (squash), never a direct push. After the integration branch holds every feature merge + `close_batch.sh` + doc consolidation, push it and open one PR, then merge it with a normal authenticated `gh pr merge` — **no `--auto`**. (GitHub-native auto-merge is gated behind paid plans for private repos; the non-`--auto` path is what `/pr-dependabot` already standardizes on and works on Free.)

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
# 3. open the PR against main
PR_URL="$(gh pr create --base main --head "$INTEGRATION_BRANCH" \
  --title "review-close: consolidate ${RUN_ID}" \
  --body "Automated /review-close integration PR: feature merges + batch close + doc consolidation. Squash-merges once required checks are green.")"
echo "Integration PR: $PR_URL"
# 4. wait for the PR's required checks to finish (blocks ~1–2 min; exits non-zero on a
#    failing check). A "no checks reported" message is NOT a failure — a repo protected
#    only by enforce_admins may have zero status checks; fall through to the gate below.
gh pr checks "$PR_URL" --watch --fail-fast || true
# 5. confirm mergeability, then squash-merge (blocks until landed; deletes the remote branch)
gh pr view "$PR_URL" --json state,mergeStateStatus --jq '{state, mergeStateStatus}'
gh pr merge "$PR_URL" --squash --delete-branch
```

##### 4d-1. Stuck-PR handling (report + STOP, never force-merge)

The PR is **not mergeable** if a required check failed (`gh pr checks` reports a failing check), `gh pr view` shows `mergeStateStatus: BLOCKED`/`DIRTY`, or `gh pr merge` refuses. When that happens:

- **Report** the PR URL and the failing check name(s), then **STOP** — do not force-merge, do not fall back to a direct `git push origin main`, do not loop. Authority to merge belongs to the PR's required checks, not this skill.
- Leave the integration branch, the feature branches, the worktrees, and the `.locks/` **in place**. **Skip Step 6 entirely** this run — its cleanup is gated on a confirmed merge (see Step 6's merge-policy gate). The human (or a follow-up `/review-close`) fixes the check and re-runs.
- Re-running is safe and idempotent: the next `pr`-policy run cuts a **new** integration branch from `origin/main` and re-sweeps the same still-unpushed local-`main` commits, so nothing is double-applied. The stuck branch is left orphaned but harmless — delete it by hand (`git branch -D <branch>` + `git push origin --delete <branch>`) once its replacement merges.

On a confirmed merge (`gh pr merge` exits 0 / `gh pr view` shows `state: MERGED`), continue to Step 5, then Step 6 cleanup.

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
- **`pr` policy** — run cleanup **only if Step 4d confirmed the integration PR `MERGED`.** If 4d-1 reported a stuck PR (red check / `BLOCKED`), **skip Step 6 entirely** — the feature branches, worktrees, and `.locks/` must survive so the work is recoverable once the check is fixed. When the PR did merge, first re-sync local `main` and drop the integration branch, then run the `pr` per-branch cleanup below:
  ```bash
  git checkout main
  git fetch origin main
  git reset --hard origin/main          # local main's pre-merge commits are now in the squash
  # `gh pr merge --delete-branch` removes BOTH the remote and (once HEAD left it) the local
  # integration branch, so it may already be gone — tolerate that, don't error on cleanup.
  git branch -D "$INTEGRATION_BRANCH" 2>/dev/null || true
  ```

> **Lock-as-real-time-signal invariant (`pr` policy).** Step 4c removes each closed task's `.locks/<TASK-ID>.lock` from disk on the integration branch, before the PR merges — so there is a brief window where, on `main`, the task is still `in_progress` (the `done` flip rides the unmerged PR) with no lock. This does **not** reopen the task: `/auto-build` and `next_task` only ever claim `status: open` tasks, and an `in_progress` task is never claimable regardless of its lock. The only visible effect is a transient `/sitrep` "in_progress without lock" drift flag during the in-flight (or stuck-PR) window, which clears when the PR merges and the `done` flip lands. No action needed.

**`direct` policy — per-branch cleanup.** For each merged feature branch (worktrees already removed in Step 3b):
1. Delete the **remote** branch first: `git push origin --delete <branch>` (if it exists remotely).
2. Delete the **local** branch: `git branch -d <branch>`.

**Why this order matters (BeanRider ISSUE-0021).** Step 4a rebases the feature branch onto main, which rewrites its SHA. The local branch's tracked upstream (`refs/remotes/origin/<branch>`) still points at the *pre*-rebase commit, so `git branch -d` refuses with `not fully merged to refs/remotes/origin/<branch>, even though it is merged to HEAD` — git's safe-delete check compares against the upstream ref, not against `main`. Deleting the remote first removes the upstream pointer, so the subsequent `-d` falls back to checking against `HEAD` and succeeds. Do **not** use `-D` (force-delete) — the safe-delete refusal is correct behavior given the upstream check; the fix is to drop the upstream first, not to bypass the check.

**If `git push origin --delete <branch>` is silently denied** (BeanRider ISSUE-0033, classifier hard-codes destructive-flag protection on `--delete`/`--force` regardless of allow-rule glob), the Phase 36 `PermissionDenied` hook surfaces the `! git push origin --delete <branch>` escape command — with the venv-prefix variant when a `.venv/` directory is present. Follow the hook's guidance and relay to the user. The subsequent `git branch -d <branch>` runs in-band without classifier interference (local-only, no remote contact). Do **NOT** use `AskUserQuestion`.

**`pr` policy — per-branch cleanup** (only after the integration PR merged; the local-`main` re-sync and integration-branch drop are already done in the merge-policy gate above). Each approved feature branch was rebased onto the integration branch, ff-merged, and then **squash-merged** to `main` via the PR — so it is provably contained in the squash commit but is **not** an ancestor of it, and `git branch -d` would refuse with "not fully merged." Force-delete here; the content is safely in `main`:
1. Delete the **local** branch: `git branch -D <branch>` (the safe `-d` check is meaningless against a squash — the branch's commits are in the merged PR).
2. Delete the **remote** branch **only if it was pushed**: `git push origin --delete <branch>`. Feature branches created by `/claim-task` are usually local-only under `pr` policy (the integration branch is the only thing pushed), so skip this when the branch has no remote tracking ref.

For each **SKIP'd** branch (Step 2a verdict — Step 1a classified the worktree as `dirty`):
1. Leave the worktree, the `.locks/<TASK_ID>.lock` file, and the branch fully in place — do NOT touch anything.
2. Carry the SKIP entry into Step 8's report so the user sees the paused-work list with its file count and worktree path.

For each **rejected** branch that still has a worktree:
1. Leave the worktree and branch in place for future work.

**Hard guard against worktree removal in this step (BeanRider ISSUE-0016).** Step 6's flow as documented does not call `git worktree remove` — worktrees for merged branches are gone after Step 3b, and worktrees for SKIP'd / rejected branches are explicitly preserved. If a future evolution of this skill adds a worktree-cleanup pass here, that pass MUST refuse to remove any worktree Step 1a classified as `dirty` AND MUST NOT use `--force`. The current shape avoids the trap structurally; this note exists to keep it that way as the skill evolves.

Remove `.pending-docs/` directory if it still exists and is empty: `rmdir .pending-docs 2>/dev/null`

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
Test decisions: <N verified, N waived, N held-for-fix, N doc-only> (or "none to verify")
Staging:       <verified / skipped / broken>
Locks cleaned: <list> (or "none")
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

If `$ARGUMENTS` contains `--dry-run`, perform Steps 1-3 only and report what *would* be done without making changes.
