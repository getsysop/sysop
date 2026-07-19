---
name: auto-fix
description: Automatically fix mechanical review batches — claims, fixes, verifies, and pushes via isolated agents
argument-hint: "[concurrency] [--merge]"
---
<!-- sysop:model-roles inline=reasoning -->

Automatically process pending review batches that have prescriptive, mechanical fixes. Reads the `Flag:` tags previously written by `/triage` and claims + fixes only the unflagged (auto) batches via isolated agents. If any pending batch lacks a `Flag:` tag, invokes `/triage` first as a prereq.

Two-pass workflow:
- **Default mode (pass 1)**: processes only **non-overlapping** auto batches, in parallel. Pushes branches.
- **`--merge` mode (pass 2)**: processes only **overlapping** auto batches, sequentially. Pushes branches.
- Both passes can run concurrently. Run `/review-close` after both complete to merge all branches through the Opus convention gate, staging verification, and push.

> **Helper names** referenced in this skill (e.g., `_sanitize_log`, `useAbortableFetch`, `getDisplayError`, `redact_api_keys`, `shared_cli.py`) are placeholders — substitute the equivalent helpers from your project's `convention_map.md`. Worked examples may also reference specific batch numbers, file paths, or env-var names from the originating project; treat those as illustrations, not literal requirements.

## Pre-flight: Permission Guard

Before parsing arguments or doing any work, verify `.claude/settings.json` carries the allow-rules this skill depends on. Under `auto` mode with `skipAutoPermissionPrompt: true`, a missing rule for `git worktree add`, `git push -u origin`, or `bash sysop/scripts/batch_work.sh` will silently halt subagents mid-fix.

Read `.claude/settings.json` and confirm `permissions.allow` contains:

- `Bash(git checkout:*)`
- `Bash(git worktree add:*)`
- `Bash(git worktree list)`
- `Bash(git push -u origin:*)`
- `Bash(git push origin:*)`
- `Bash(git push --force-with-lease:*)` _(used only when a subagent amends a commit and re-pushes — conditional path; consumers can omit from settings.json if they don't run amend-based fixes)_
- `Bash(bash sysop/scripts/batch_work.sh:*)`

If any are missing, stop with the `_shared/permission-guard.md` § Algorithm step 4 message (one-line reason: "spawns isolated subagents that claim batch worktrees, fix tasks, and push the resulting branches"). Do not proceed.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and continue.

## Step 0: Parse Arguments

Parse `$ARGUMENTS`:

- **Bare integer** (e.g., `4`) → concurrency cap (max parallel agents). Default: 4. Only affects the default (non-merge) path. All eligible batches are processed regardless — the cap controls how many agents run simultaneously.
- **`--merge`** → process only overlapping batches, sequentially. Fixes and pushes each branch without merging to main. Run `/review-close` afterward to merge all branches through the Opus convention gate. Concurrency cap is ignored (sequential execution).

For an assess-only preview without claiming or fixing, run `/triage --dry-run` directly (Phase 44 extracted the classifier; the old `/auto-fix --dry-run` no longer exists).

## Step 0.5: Triage Prerequisite

Read `review_tasks.md` and check whether any batch with status **`Pending`** lacks a `> **Flag:**` tag. If any such batch exists, invoke `/triage` via the Skill tool and wait for it to complete. `/triage` will commit any uncommitted `review_tasks.md` additions from `/codebase-review` or `/security-audit`, classify each pending batch as auto or flag, and write the resulting `Flag:` tags as a single `docs:` commit. After `/triage` returns, re-read `review_tasks.md` so Step 1 sees the freshly written tags.

If every pending batch already carries a `Flag:` tag (or no pending batches exist), skip this step — the queue is already triaged.

## Step 1: Read Queue

Read `review_tasks.md` in full (or re-read after Step 0.5). If `review_tasks.md` exceeds 125KB, stop and tell the user to run `.venv/bin/python3 sysop/scripts/archive_review_tasks.py` first.

Find all batches with status **`Pending`** that do **not** have a `> **Flag:**` tag — those are the auto batches this skill processes. For each, extract:
- Batch number and title
- Branch name (from `> **Branch:** \`...\``)
- Scope (from `> **Scope:** ...`)
- Verify command (from `> **Verify:** ...`)
- Overlap tag (from `> **Overlap:** ...`) — may be absent on older batches
- All task lines (`- [ ] **TASK-NNN**: description emoji`)

**Skip** batches with a `> **Flag:**` tag (those belong to `/auto-judge`). **Skip** batches with status `In Progress`, `Merged`, `Complete`, or `Ready for Review`.

## Step 2: Report Plan + Confirm

Print a plan table covering the auto batches this skill will process. Note: the rationale and any flagged-batch decisions are surfaced by `/triage` — this skill's plan is auto-only.

```
## Auto-Fix Plan

| Batch | Title | Tasks | Overlap |
|-------|-------|-------|---------|
| 198   | Scripts: shared_cli.py Migration | 5 | none |
| 200   | Tests: Mock Cleanup | 6 | none |
| 201   | Backend Error Handling | 4 | 202 |
| 202   | Backend Logging | 3 | 201 |

<if no --merge>
Processing: <N> parallel batches (concurrency: <cap>)
Deferred:  <M> overlapping batches (run /auto-fix --merge concurrently or after)
Flagged:   <K> batches for /auto-judge (see review_tasks.md for Flag: reasons)
Estimated: <N> agent runs
</if>

<if --merge>
Processing: <N> overlapping batches (sequential, push only)
Skipped:   <M> non-overlapping batches (already handled or run /auto-fix without --merge)
Flagged:   <K> batches for /auto-judge (see review_tasks.md for Flag: reasons)
Estimated: <N> agent runs
</if>
```

If no eligible auto batches exist for the current mode, report and stop:
- Without `--merge` and no non-overlapping auto batches: "No non-overlapping auto batches to process. Run `/auto-fix --merge` for overlapping batches, or `/auto-judge` for flagged batches."
- With `--merge` and no overlapping auto batches: "No overlapping auto batches to process."

Ask the user to confirm before proceeding: "Proceed with <N> auto batches?"

Wait for confirmation. Do not proceed without it.

## Step 4: Process Auto Batches

**Prerequisite:** Verify you are on `main` with a clean working tree (`git status` shows nothing to commit). If not, stop and report.

### 4a. Compute Overlap (if missing)

For each auto batch, check if its `Overlap:` tag was extracted in Step 1.

If **any** auto batch lacks the tag (older batches generated before overlap tagging was added), compute overlap dynamically:

1. For each auto batch, extract all `file:line` locations from its task lines
2. Strip line numbers to get file paths (e.g., `<file path>:<line>` → `<file path>`)
3. Two batches overlap if they share **any** file path
4. Assign computed overlap: `none` if no shared files, or a list of overlapping batch numbers

Store the overlap data in memory — do not write back to `review_tasks.md`.

### 4b. Claim and Execute

Determine which auto batches are eligible based on mode:
- **Without `--merge`**: only batches with `Overlap: none` (non-overlapping)
- **With `--merge`**: only batches with overlap (NOT `Overlap: none`)

To claim a batch, run:

```bash
bash sysop/scripts/batch_work.sh <BATCH_NUMBER>
```

Parse the output for:
- **Worktree path**: extract from the line containing `Path:` (e.g., `│  Path:   /path/to/worktrees/task-batch-198`)
- **Branch name**: extract from the line containing `Branch:`

If the script exits non-zero, report the error, **skip this batch**, and continue to the next one.

---

**Without `--merge`** (all eligible batches are non-overlapping):

1. Claim ALL eligible batches sequentially (each `batch_work.sh` call commits a claim on main that the next must see). Collect worktree paths and branch names into a queue.

2. **Parallel DB contention warning**: if the eligible batches share a verify command that mutates the same database (e.g. `APP_ENV=test pytest` against `<test database name>`), parallel execution can race on schema/seed fixtures and produce flaky FAIL verdicts. For DB-heavy batches, prefer `--merge` (sequential) or invoke `/auto-fix 1` to force concurrency=1.

3. Spawn fix agents using a **rolling window** up to the concurrency cap:
   a. **Initial fill**: spawn agents for the first `<cap>` claimed batches in a single message with parallel Agent tool calls, all with `run_in_background: true`.
   b. **Refill on completion**: each background agent's completion triggers an automatic notification. Do NOT poll or sleep. When a notification arrives, collect that agent's result; if the queue still has unstarted batches, immediately spawn one new agent for the next queued batch (`run_in_background: true`). The in-flight pool stays full until the queue drains.
   c. **Finish**: when the queue is empty and all in-flight agents have completed, proceed to Step 4c.

**With `--merge`** (all eligible batches are overlapping):

Process batches one at a time — **sequentially** claim, fix, and push:
1. Claim the first eligible batch via `batch_work.sh`
2. Spawn one fix agent with `run_in_background: false`
3. After the agent reports (PASS or FAIL), claim and process the next eligible batch
4. Repeat until all eligible batches are processed

Each batch is pushed to origin but NOT merged to main. All merging is deferred to `/review-close`, which runs the Opus convention gate, staging verification, and doc consolidation.

**For each batch**, use the **Agent tool** to spawn a subagent:
- `description`: `"Fix review batch <N>"`
- Do **NOT** set `isolation: "worktree"` — the agent must work in the existing worktree created by `batch_work.sh`
- Set `model: "sonnet"` <!-- sysop:role=mechanical --> — the **mechanical** role (`.claude/served_models.yml`). These fix agents apply prescriptive, mechanical changes, so they are pinned to the cheap tier, not the reasoning tier (Opus is reserved for adversarial review — the verification pass below and `/review-close`'s convention gate). The sibling scan (Step 1b of the agent prompt) and post-fix convention verification (Step 5) are scoped checks of the just-edited files, not broad adversarial review. A consumer who prefers cost-follows-session can set `mechanical: inherit` in `.claude/served_models.local.yml`.

Pass this prompt to the agent, filling in all placeholders:

---

**START OF AGENT PROMPT**

You are fixing review tasks in **Batch <N> — "<TITLE>"**.

**Working directory:** `<WORKTREE_PATH>`
**Branch:** `<BRANCH>`
**Verify command:** `<VERIFY_COMMAND>`

## Tasks

<paste ALL task lines from review_tasks.md for this batch, including full descriptions>

## Convention Awareness

Before fixing tasks, read `.claude/convention_map.md` in the worktree
(`<WORKTREE_PATH>/.claude/convention_map.md`). For each file you edit, check which
conventions apply to that file's glob pattern. If your fix touches code near a pattern
covered by a convention (SQL queries, fetch calls, error handling, Slack messages, etc.),
ensure your fix is consistent with those conventions. Read the relevant `CLAUDE.md`
§ Prevention Conventions subsection only if a convention_map entry applies — do not
read the entire CLAUDE.md upfront.

For batches from security audit rounds (identified by `> **OWASP:**` in the batch header),
also read `.claude/security_map.md` in the worktree
(`<WORKTREE_PATH>/.claude/security_map.md`). Use the security map's Check/Skip lists
to understand which OWASP categories apply to each file — this ensures fixes align with
the security context, not just code quality conventions.

## Context Awareness

- **Large files**: If a file is over 500 lines, use the Read tool with `offset` and `limit` to read ~50 lines above and below the target line from the task description. Do not read the entire file.
- **CLAUDE.md**: Do not read it in full. Only read the specific Prevention Conventions subsection if `convention_map.md` directs you to.

## Instructions

All file paths in tasks are relative to the project root. Prepend `<WORKTREE_PATH>/` to get absolute paths for the Read and Edit tools.

### 1. Fix each task in order

For each task:
1. Read the file at the specified location using the Read tool
2. Understand the current code and the requested change
3. Apply the fix as described using the Edit tool
4. **Idempotency check**: If an Edit fails because `old_string` is not found, read the file and check whether `new_string` is already present. If so, the fix is already applied — skip it and continue to the next task. Do NOT treat this as an error.
5. Continue to the next task

### 1b. Sibling scan

After all tasks are fixed, scan each file you modified for **sibling violations** of the same convention(s) you just enforced. The convention you fixed is already in your context from reading the task description and convention_map — now check whether the rest of the file has the same problem at a different location.

**How:**
1. For each file you edited, note which convention(s) the task(s) enforced (e.g., "missing `getDisplayError()`", "loading state not cleared on abort", "`_sanitize_log(str(e)[:500])`")
2. Scan the rest of the file for the same anti-pattern — use Grep or read the full file if it's under 500 lines
3. If you find sibling violations, fix them in the same commit

**Scope limits:**
- Only scan files you already modified — do not expand to other files
- Only check conventions you already enforced in this batch — do not audit for unrelated conventions
- If a sibling violation requires a non-trivial design decision (not a mechanical fix), skip it and note it in the report as `SIBLING_SKIPPED`

**Report format** (append to step 6 report):
```
SIBLINGS_FOUND: <count>
SIBLINGS_FIXED: <count>
SIBLINGS:
- <file:line> — <convention name>: <one-sentence description>
```

If no siblings found, report `SIBLINGS_FOUND: 0`.

### 2. Commit all fixes

After ALL tasks are fixed (or confirmed already-applied), stage and commit with a single commit:

```bash
cd <WORKTREE_PATH> && git add -A && git diff --cached --quiet && echo "Nothing to commit" || git commit -m "fix: <batch title, lowercase>"
```

If nothing to commit (all fixes were already applied), skip to step 5 (push) — the branch may already have the commit from a prior run.

### 3. Run verify

```bash
cd <WORKTREE_PATH> && <VERIFY_COMMAND>
```

Pass `timeout: 600000` to the Bash tool call (10 min) — the default 120s is too short for full pytest suites or `npm run build`. If the command exceeds the timeout, treat it as a verify failure and report `VERIFY: TIMEOUT` in Step 7.

If verify output exceeds 150 lines, focus on the first failure only — errors appear near the top.

### 4. Handle verify failure

If verify fails:
1. Read the error output carefully
2. Check if a test file needs updating because your fixes changed behavior that a test asserts on (co-change rule: when changing implementation, update tests that assert on the affected behavior)
3. Make **ONE** fix attempt — edit the failing code or test
4. Commit the fix: `cd <WORKTREE_PATH> && git add -A && git commit -m "fix: update test for batch <N> changes"`
5. Re-run verify
6. If still failing: **stop trying**. Report the error. Do NOT enter a retry loop.

### 5. Post-fix convention verification

After verify passes but before pushing, re-check that the fixes themselves didn't introduce new convention violations:

1. List all files changed in this branch: `cd <WORKTREE_PATH> && git diff --name-only main...HEAD`
2. For each changed file, re-read the applicable conventions from `convention_map.md`
3. Scan the **new/changed lines** (not just the task locations) for violations of those conventions
4. Common regression patterns to watch for:
   - Fix adds a new `fetch()` call but forgets `encodeURIComponent()` on the path
   - Fix adds error handling but uses `str(e)` instead of generic message
   - Fix moves code into a new function but doesn't carry over the `_sanitize_log()` wrapper
   - Fix adds a `useCallback` but the dependency array is incomplete
5. If you find regressions, fix them and amend the commit: `cd <WORKTREE_PATH> && git add -A && git commit --amend --no-edit`
6. Report any regressions found and fixed in the `REGRESSIONS:` section of your report

### 6. Push (only if verify passes)

```bash
cd <WORKTREE_PATH> && git push -u origin HEAD
```

If push says "Everything up-to-date", that's fine — the branch was already pushed from a prior run.

### 7. Report results

Return your results in this exact format:

```
BATCH: <N>
STATUS: PASS or FAIL
VERIFY: PASS, FAIL, or TIMEOUT
TASKS_FIXED: <count>/<total>
TASKS:
- TASK-NNN: Fixed — <one-sentence summary of what you changed>
- TASK-NNN: Fixed — <one-sentence summary>
SIBLINGS_FOUND: <count>
SIBLINGS_FIXED: <count>
SIBLINGS:
- <file:line> — <convention name>: <one-sentence description>
REGRESSIONS_FOUND: <count>
REGRESSIONS_FIXED: <count>
REGRESSIONS:
- <file:line> — <convention name>: <one-sentence description of regression introduced by fix>
ERROR: <description if failed, "none" if passed>
```

**END OF AGENT PROMPT**

---

### 4c. Collect Results

For each agent (parallel or sequential), read its response. Extract:
- Pass/fail status
- Number of tasks fixed
- Any errors

If an agent reports FAIL or TIMEOUT, note the batch as failed and continue.

### 4d. Opus Verification Pass (for every PASS batch)

Sonnet's sibling-scan (Step 1b of the agent prompt) and post-fix convention check (Step 5) are weaker than Opus's on the same prompts — prior runs have shown Sonnet-missed siblings (`fix(batch-449): ExportEngine setTimeout`) and cross-convention regressions (`fix: truncate before redact_api_keys`) that only Opus catches reliably. This pass is the scoped safety net.

For each batch that reported `STATUS: PASS`, spawn an **Opus** subagent to re-review the branch's committed diff. Run these in parallel across batches (single message, multiple Agent tool calls, all with `run_in_background: true` — same rolling-window refill used in Step 4b).

Use the Agent tool with:
- `subagent_type`: `"general-purpose"`
- `model`: `"opus"` — the **reasoning** role, set explicitly, per `.claude/served_models.yml`. This is adversarial review, which is the reasoning tier's job.
- `description`: `"Verify batch <N>"`
- Do **NOT** set `isolation: "worktree"` — the agent works in the existing worktree.

Agent prompt:

---

**START OF VERIFICATION PROMPT**

You are reviewing **Batch <N> — "<TITLE>"** after a Sonnet fix pass. Your scope is narrow: catch the three things Sonnet underperforms on.

**Working directory:** `<WORKTREE_PATH>`
**Branch:** `<BRANCH>`
**Sonnet's report:** <PASTE THE SONNET AGENT'S FULL REPORT FROM STEP 4c>

## Step 1: Load the diff

```bash
cd <WORKTREE_PATH> && git diff main...HEAD
```

Read the diff in full. Note which files changed and what convention each change enforces (e.g., "added `_sanitize_log()` wrapper", "added `useAbortableFetch`", "replaced `str(e)` with generic message").

## Step 2: Three checks

### Check A — Sibling violations Sonnet missed

Sonnet's Step 1b scan is supposed to find sibling instances of the same anti-pattern in each modified file. It often misses them. For each file you see in the diff:
1. Open the full file with Read
2. For each convention Sonnet enforced, search the rest of the file for the same anti-pattern at a different location
3. List each sibling Sonnet missed

Example pattern from Batch 449: Sonnet fixed a Timer-cleanup violation in `DesignControls.tsx` but missed the identical `setTimeout` in `ExportEngine.tsx`.

### Check B — Cross-convention regressions introduced by the fix

Fixes can introduce secondary violations. Scan each added/modified line against adjacent conventions:
- Did the fix add error handling that uses `str(e)` instead of a generic message?
- Did the fix add a `fetch()` call and forget `encodeURIComponent()` on the path?
- Did the fix add `redact_api_keys()` but skip truncate-before-regex (`str(e)[:N]`)?
- Did the fix add a `useCallback` with an incomplete dependency array?
- Did the fix add a `SELECT` query on `writer_engine`?
- Did the fix leave an unused import after removing a call?

Example pattern from prior runs: Sonnet added `_sanitize_log(str(e))` but forgot the `[:500]` truncation, creating an unbounded-regex surface that Opus later fixed.

### Check C — False-positive tasks Sonnet executed anyway

Sonnet applies prescriptions literally even when the prescription is wrong. Signals:
- A "gate" at a layer that cannot physically enforce it (e.g., FastAPI `Depends()` can't gate body parse)
- A cap that duplicates an already-existing bound (SQL `LIMIT`, Pydantic `max_length`)
- A fix that targets a symptom the change doesn't actually address
- The task description conflicts with existing code comments or tests that justify the current behavior

Example from Batch 416: TASK-2245 (route-layer point cap) and TASK-2250 (FastAPI body-parse-before-Depends) were both false positives that Sonnet "fixed" before Opus dropped them.

## Step 3: Apply corrections (if any found)

For each issue, fix it directly in the worktree. Do **NOT** amend or force-push Sonnet's commit — make a new commit on top:

- **Sibling / Regression**: fix and commit with `git commit -m "fix(batch-<N>): <what you caught> (opus verify)"`
- **False-positive**: revert Sonnet's change for that task in a new commit. Also update `<WORKTREE_PATH>/review_tasks.md`: **leave the task's `[ ]` checkbox unchanged** and append `  > Dropped: <one-sentence reason>` under the task line. `close_batch.sh` will flip `[ ]` → `[x]` at merge time alongside the other tasks — leaving the checkbox here keeps Grand Total counts accurate. Commit both edits together: `git commit -m "revert(batch-<N>): drop TASK-NNN — <short reason> (opus verify)"`

Push each commit:

```bash
cd <WORKTREE_PATH> && git push
```

## Step 4: Report

Return in this exact format:

```
BATCH: <N>
VERDICT: CLEAN or CORRECTIONS_APPLIED
SIBLINGS_FIXED: <count>
REGRESSIONS_FIXED: <count>
DROPS: <count>
DROPPED_TASKS:
- TASK-NNN — <reason>
CORRECTIONS:
- <file:line> — <check A/B/C>: <one-sentence description>
NOTES: <any notable observations about the Sonnet pass, or "none">
```

**END OF VERIFICATION PROMPT**

---

**Collect verification results.** If any batch returned `CORRECTIONS_APPLIED`, note the counts — they appear in the final summary (Step 5). Sonnet's STATUS remains PASS unless the Opus pass itself failed to run; Opus corrections are additive, not remedial.

If an Opus verify agent itself fails (e.g., crashes, returns malformed output), log the batch as `VERIFY_INCOMPLETE` and continue — the branch was pushed by Sonnet and `/review-close`'s convention gate will run again as a backstop.

### 4e. Create Pending Docs (on success only)

If the agent reported PASS, create a pending-docs file in the worktree so `/review-close` can consolidate documentation.

Use the Write tool to create `<WORKTREE_PATH>/sysop/runtime/pending-docs/<sanitized-branch>.md`:

1. `mkdir -p <WORKTREE_PATH>/sysop/runtime/pending-docs` (via Bash)
2. Write the file:

```yaml
---
branch: <branch-name>
date: YYYY-MM-DD
type: infrastructure
task_ids: []
summary: "Batch <N> complete: <Title>. <Scope>."
---
```

This file is **untracked** (gitignored). It will be copied to main by `/review-close` Step 3b before the worktree is removed.

**Note:** `/review-close` discovers branches via `git branch -a`, not via lock files. No lock file is needed for review batches.

## Step 5: Summary Report

After all batches are processed, print:

```
## Auto-Fix Complete

### Processed (Sonnet fix + Opus verify)
| Batch | Title | Sonnet | Verify | Opus Verdict | Siblings+ | Regress+ | Drops |
|-------|-------|--------|--------|--------------|-----------|----------|-------|
| 198   | Scripts: shared_cli.py Migration | PASS 5/5 | PASS | CLEAN | 0 | 0 | 0 |
| 200   | Tests: Mock Cleanup | PASS 6/6 | PASS | CORRECTIONS_APPLIED | 1 | 0 | 0 |
| 416   | Backend Routes — data/errors/pinned | PASS 6/6 | PASS | CORRECTIONS_APPLIED | 0 | 0 | 2 |

### Deferred (overlapping — use --merge)        <if no --merge, omit if empty>
| Batch | Title | Overlaps With |
|-------|-------|---------------|
| 201   | Backend Error Handling | batch-202 |
| 202   | Backend Logging | batch-201 |

### Flagged for Judgment (handled by /auto-judge)
| Batch | Title | Flag Reason |
|-------|-------|-------------|
| 203   | Data Exposure & Alerting | TASK-1124: open-ended sanitizer choice |
| 205   | Security Configuration | TASK-1127: requires GCP LB knowledge |

### Failed (needs investigation)
| Batch | Title | Error |
|-------|-------|-------|
| (none) | | |

### Opus-Verify Incomplete (backstopped by /review-close)
| Batch | Title | Reason |
|-------|-------|--------|
| (none) | | |

Next steps:
  <if no --merge>
  1. Run /auto-judge (and /auto-judge --merge) for flagged batches — can run concurrently with step 2
  2. Run /auto-fix --merge for <M> overlapping auto batches
  3. Run /review-close after all auto-* skills finish to merge everything
  </if>
  <if --merge>
  1. Run /auto-judge and /auto-judge --merge if any flagged batches remain
  2. Run /review-close to merge all branches (Opus convention gate + staging verify)
  </if>
```
