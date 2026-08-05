---
name: auto-judge
description: Automatically process flagged review batches with Opus judgment — claims, fixes or drops via isolated Opus agents, then pushes
argument-hint: "[concurrency] [--dry-run] [--merge]"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning inline=reasoning -->

Automatically process pending review batches that `/triage` flagged for judgment. Claims flagged batches via isolated Opus subagents that can **FIX**, **DROP**, or **FAIL** each task after adversarial re-reading. If any pending batch lacks a `> **Triaged:**` record, invokes `/triage` first as a prereq.

**The `Triaged:` task list decides where the money goes.** A `flag` verdict may name the specific tasks that need judgment — `> **Triaged:** 2026-08-03 flag [TASK-1124]`. When it does, only those tasks get adversarial re-reading; the rest of the batch is mechanical and gets a prescriptive fix in the same worktree. When it does not, the whole batch is judged, as before. Without this, one judgment task in a 50-task batch put 49 mechanical ones through the expensive lane.

> **Helper names** referenced in this skill (e.g., `_sanitize_log`, `useAbortableFetch`, `getDisplayError`, `redact_api_keys`, `shared_cli.py`) are placeholders — substitute the equivalent helpers from your project's `convention_map.md`. Worked examples may also reference specific batch numbers, file paths, or env-var names from the originating project; treat those as illustrations, not literal requirements.

Runs concurrently with `/auto-fix`: the two skills target disjoint batch pools (`/triage` partitions them) — `/auto-fix` handles mechanical (no `Flag:` tag), `/auto-judge` handles flagged. Both feed `/review-close` for merging.

Two-pass workflow mirrors `/auto-fix`:
- **Default mode (pass 1)**: processes only **non-overlapping** flagged batches, in parallel. Pushes branches.
- **`--merge` mode (pass 2)**: processes only **overlapping** flagged batches, sequentially. Pushes branches.
- Run `/review-close` after both complete to merge all branches.

## Pre-flight: Permission Guard

Before parsing arguments, verify `.claude/settings.json` carries the allow-rules this skill depends on. Same failure mode as `/auto-fix`: under `dontAsk` mode a missing rule is auto-denied with no prompt, halting Opus subagents mid-fix.

Read `.claude/settings.json` and confirm `permissions.allow` contains:

- `Bash(git checkout:*)`
- `Bash(git worktree add:*)`
- `Bash(git push -u origin:*)`
- `Bash(git push origin:*)`
- `Bash(git push --force-with-lease:*)` _(used only when a subagent amends a commit and re-pushes — conditional path; consumers can omit from settings.json if they don't run amend-based fixes)_
- `Bash(bash sysop/scripts/batch_work.sh:*)`

If any are missing, stop with the `_shared/permission-guard.md` § Algorithm step 5 message (one-line reason: "spawns isolated Opus subagents that judge flagged tasks, fix or drop them, and push the resulting branches"). Do not proceed — unless the guard's step 3 mode check applies.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and continue.

## Step 0: Parse Arguments

Parse `$ARGUMENTS`:

- **Bare integer** (e.g., `2`) → concurrency cap. Default: **2** (Opus costs more than Sonnet — be conservative). Only affects the default path.
- **`--dry-run`** → report without claiming or fixing. Stops after Step 3.
- **`--merge`** → process only overlapping batches, sequentially. Concurrency cap ignored.

## Step 0.5: Triage Prerequisite

Run the index pass from Step 1a and check whether any batch with status **`Pending`** lacks a `> **Triaged:**` record. If any such batch exists, invoke `/triage` via the Skill tool and wait for it to complete. `/triage` will commit any uncommitted `review_tasks.md` additions from `/codebase-review` or `/security-audit`, classify each pending batch as auto or flag, and write the resulting `Triaged:` (and `Flag:`) lines as a single `docs:` commit. After `/triage` returns, re-run the index pass so Step 1 sees the freshly written records.

**Key the check on `Triaged:`, not on `Flag:`.** A `Flag:` tag with no `Triaged:` sibling records no verdict, so treating its presence as "already triaged" routes an unread batch straight into the Opus lane on the strength of a tag nobody can attribute.

If every pending batch already carries a `Triaged:` record (or no pending batches exist), skip this step — the queue is already triaged.

## Step 1: Read Queue

**Do not read `review_tasks.md` in full.** Read it in two passes; see `triage/SKILL.md` § Step 1 for the same procedure stated at length.

### 1a. Index pass

```bash
grep -n -E '^## |^### Batch |^> \*\*(OWASP|Scope|Branch|Verify|Overlap|Flag|Triaged):\*\*' review_tasks.md
```

Each `### Batch N — <title> \`<Status>\`` line gives number, title and status; the `> **Key:**` lines beneath it are its metadata. A batch's **body** runs from its header line to the line *before* the next `^## ` or `^### Batch ` line, or to end-of-file when nothing follows the last batch.

**The index pass is line-oriented and cannot see fenced blocks — check before you trust a boundary.** A task's remediation text routinely quotes the tracker's own shapes (`## Deferred`, `### Batch N — … \`Pending\``, `> **Flag:** <reason>`), and `grep` will report those example lines exactly like real ones. Two consequences, both silent:

- A fenced heading looks like a boundary, so the batch containing it appears to end early and its remaining tasks vanish from your view.
- A fenced `> **Flag:**` or `> **Triaged:**` looks like the enclosing batch's verdict — which is the #337 failure mode arriving from inside the file.

So: when a candidate boundary or metadata line sits *inside* a batch you have already bounded, open that region with the scoped read below and look at it before acting on it — a fence is obvious on sight and invisible to `grep`.

**If your boundary disagrees with what `/sitrep` or a claim script reports, do not assume either side is right.** The shipped parsers are fence-aware and you are not, so a *balanced* fenced example explains most disagreements — but not all of them, and the ones it does not explain fail in the opposite direction. An unbalanced fence marker, a column-0 `## ` heading written as prose in a task body, or a batch header whose dash is not an em dash will each make one side see structure the other does not. **Read the region. Do not resolve the disagreement by rule.**

Select the flag pool from this output alone — batches with status **`Pending`** that have a `> **Flag:**` line — and record for each:
- Batch number and title
- Branch name (`> **Branch:** \`...\``)
- Scope (`> **Scope:** ...`)
- Verify command (`> **Verify:** ...`)
- Overlap tag (`> **Overlap:** ...`)
- Flag reason (text after `> **Flag:**`)
- **Judgment set** — the bracketed task IDs in `> **Triaged:** <date> flag [TASK-…, TASK-…]`, if present. **Absent brackets mean the whole batch**, which is the pre-existing behaviour and the correct degradation.

**Skip** batches without a `Flag:` line (they belong to `/auto-fix`). Skip batches with status `In Progress`, `Merged`, `Complete`, or `Ready for Review`.

### 1b. Scoped body pass

For each **selected** batch only, read its body — nothing else:

```bash
sed -n '<START>,<END>p' review_tasks.md
```

`<START>` is the batch header's line number; `<END>` is one less than the next `^## ` / `^### Batch ` line number, or `$` **only when no `^## ` section follows the last batch** — on a tracker with a trailing `## Deferred` / `## Statistics` / `## Convention fire ledger`, `$` re-reads the whole tail, which is the thing this pass exists to avoid. Extract all task lines (`- [ ] **TASK-NNN**: description emoji`) and their indented detail lines — **all** of them, not just the judgment set: the agent fixes the whole batch, it just does not *judge* the whole batch.

### 1c. Tracker size is advisory, never a stop

If `review_tasks.md` is large (**~125KB** is the historical rule of thumb), print an advisory and **continue** — do not halt. `archive_review_tasks.py` selects what to relocate by **merge status**, not by size (`archive_review_tasks.py:100` matches only `Merged`/`Complete`; a Round moves whole only when every batch in it is merged, otherwise it relocates the merged batches individually), so it cannot shrink a tracker whose bulk is *open* work. Levers, in order: run this skill and `/auto-fix`, then `/review-close`; once batches are merged, run `python3 sysop/scripts/archive_review_tasks.py`.

## Step 2: Categorize Flags

For each flagged batch, read the `Flag:` reason and assign a **category** used only to prime the agent prompt:

- **design-choice** — reason mentions "design choice", "decide", "choose", "select", "alternative", "semantics"
- **architectural** — "refactor", "extract", "consolidate", "shared helper", "abstraction", "architectural", "restructure"
- **investigation** — "investigate", "requires investigation", "verify.*before", "confirm", "depends on.*behavior", "understand"
- **verification** — "judgment call", "benign race", "verify conflict", "behavioral judgment"
- **other** — anything else

The category tunes the agent's framing (see Step 4b). It does **not** branch execution logic.

## Step 3: Report Plan

Print a classification table:

```
## Auto-Judge Plan

| Batch | Title | Tasks | Judgment | Category | Overlap | Flag Reason |
|-------|-------|-------|----------|----------|---------|-------------|
| 421   | Backend Auth & Middleware | 10 | 2 of 10 | verification | none | TASK-2283/2285: judgment call on benign race; design choices... |
| 424   | Backend Payments stripe_service | 8 | 3 of 8 | design-choice | 425 | TASK-2312/2313: alerting design; TASK-2314: when to validate... |
| 427   | Backend SQL & Data Layer cache | 9 | 9 of 9 | investigation | none | TASK-2329: requires investigation of SET LOCAL pattern |

<if no --merge>
Processing: <N> parallel batches (concurrency: <cap>)
Deferred:  <M> overlapping batches (run /auto-judge --merge)
Estimated: <N> Opus agent runs
</if>

<if --merge>
Processing: <N> overlapping batches (sequential)
Skipped:   <M> non-overlapping batches
Estimated: <N> Opus agent runs
</if>

Judgment set: <J> of <T> tasks across these batches (the rest are fixed
mechanically in the same worktree). Batches showing "<T> of <T>" carry no
Triaged: task list — either the judgment was not attributable per task, or
the verdict predates task-granular flags.
```

The **Judgment** column is `<len(judgment set)> of <batch task count>`. A row reading `<T> of <T>` is the degraded case, not an error.

If no eligible batches for the current mode, report and stop:
- Without `--merge`: "No non-overlapping flagged batches. Run `/auto-judge --merge` for overlapping."
- With `--merge`: "No overlapping flagged batches."

If `--dry-run`, **stop here**.

Otherwise, ask: "Proceed with <N> flagged batches? (Opus: ~$X per batch)"

Wait for confirmation. Do not proceed without it.

## Step 4: Process Flagged Batches

**Prerequisite:** Verify you are on `main` with a clean working tree. If not, stop.

### 4a. Compute Overlap (if missing)

For each flagged batch, check if its `Overlap:` tag was extracted in Step 1. If any lack the tag, compute overlap dynamically:

1. Extract all `file:line` references from task lines
2. Strip line numbers to get file paths
3. Two batches overlap if they share any file path
4. Assign computed overlap: `none` or list of batch numbers

Store in memory — do not write back to `review_tasks.md`.

### 4b. Claim and Execute

Determine eligible batches:
- **Without `--merge`**: batches with `Overlap: none`
- **With `--merge`**: batches with overlap (NOT `Overlap: none`)

To claim a batch:

```bash
bash sysop/scripts/batch_work.sh <BATCH_NUMBER>
```

Parse the output for the **Worktree path** (`Path:`) and **Branch name** (`Branch:`). If the script exits non-zero, report the error, **skip this batch**, and continue.

---

**Without `--merge`**: claim ALL eligible batches sequentially (each claim commits on main), collect worktree paths into a queue, then spawn Opus fix agents in a rolling window:

1. **Initial fill**: spawn agents for the first `<cap>` claimed batches in a single message with parallel Agent tool calls, all with `run_in_background: true`.
2. **Refill on completion**: when a background agent's completion notification arrives, collect its result. If the queue has unstarted batches, spawn one new agent for the next queued batch (`run_in_background: true`). Keep the pool full until the queue drains.
3. **Finish**: when the queue is empty and all in-flight agents complete, proceed to Step 4c.

**With `--merge`**: claim → spawn one Opus fix agent (`run_in_background: false`) → after report, claim the next. Sequential. Each batch pushes but does NOT merge; `/review-close` handles merging.

**For each batch**, use the **Agent tool** to spawn an Opus subagent:
- `subagent_type`: `"general-purpose"`
- `model`: `"opus"` — the **reasoning** role, set explicitly, per `.claude/served_models.yml`. The whole point of this skill is reasoning-tier judgment.
- `description`: `"Judge review batch <N>"`
- Do **NOT** set `isolation: "worktree"` — the agent works in the existing worktree from `batch_work.sh`.

Pass this prompt, filling in all placeholders including the **category-specific framing** (below the Tasks block):

---

**START OF AGENT PROMPT**

You are processing **Batch <N> — "<TITLE>"**. `/triage` flagged this batch as containing tasks that need judgment. Your job is to use Opus judgment to FIX, DROP, or FAIL the tasks that need it, and to apply the prescribed fix to the ones that do not.

**Working directory:** `<WORKTREE_PATH>`
**Branch:** `<BRANCH>`
**Verify command:** `<VERIFY_COMMAND>`
**Flag reason (from /triage):** <FLAG_REASON>
**Category:** <CATEGORY>

## Tasks

### Judgment set — <J> of <T> tasks

<paste the task lines whose IDs appear in the batch's `> **Triaged:**` list, including full descriptions. If the batch has no Triaged: task list, paste ALL task lines here and write "no task list on the verdict — the whole batch is the judgment set" under this heading.>

These are the tasks the flag reason is about. Apply the Verdicts section below to **these** — read the code, weigh the alternatives, and FIX, DROP, or FAIL each one.

### Mechanical remainder — <T - J> tasks

<paste every remaining task line for this batch, including full descriptions. Omit this section entirely when the judgment set is the whole batch.>

These tasks were classified as mechanical and are in this batch only because they share its scope. **Do not re-litigate them.** Apply the prescriptive fix each one names, exactly as `/auto-fix` would: re-read the cited site first if the task is tagged `[reported]` rather than `[verified]`, apply the change, move on. The FIX/DROP/FAIL verdicts still apply if a task turns out to be wrong on its face — a mechanical task whose premise is false is still a DROP — but do not spend adversarial reading on them by default.

**Why the split exists:** a batch is flagged as a unit, and batches run 14–50 tasks. Judging every task in a batch because one of them needs judgment is what this section removes. If the two lists together do not account for every task line in the batch, stop and report — the split is wrong.

## Category Framing

<if category == "design-choice">
These tasks ask you to choose between viable alternatives. Read the code at each citation. Pick the alternative that best aligns with the existing patterns in the file, the conventions in `.claude/convention_map.md`, and the minimum-change principle. If multiple alternatives are genuinely tied, pick the one closest to the existing code path.
</if>

<if category == "architectural">
These tasks request refactors or abstractions. **Scope discipline is critical** — do not expand the refactor beyond the explicit task. If a task asks for a shared helper, create it minimally with only the arguments the current call sites need; do not add speculative parameters. If the refactor would touch files outside the batch's stated scope, DROP the task with reason "out-of-scope for batch; needs dedicated roadmap task".
</if>

<if category == "investigation">
These tasks require you to read code beyond the cited line to understand behavior before fixing. Read broadly first (call sites, related helpers, tests), then fix. If your investigation reveals the task premise is wrong — e.g., the behavior is already correct, or the prescribed fix would break invariants — DROP the task.
</if>

<if category == "verification">
These tasks flag behaviors that may or may not be bugs. Your first move is to verify whether the flagged behavior is actually a problem. Read the code, trace the call path, and make a determination. If the concern is real, apply a narrow fix. If the concern is a false alarm, DROP the task with a one-sentence explanation of why the behavior is correct.
</if>

<if category == "other">
Read the flag reason and each task carefully. Apply judgment on a per-task basis.
</if>

## Verdicts

You have three verdicts per task:

1. **FIX** — apply a change that addresses the task's root concern. The task description may be imprecise; use your judgment on the specific patch. Cite which convention or existing pattern you followed.

2. **DROP** — the task's premise is wrong. Examples from prior runs:
   - Route-layer cap duplicates an existing SQL `LIMIT` (theatre, not defense)
   - FastAPI `Depends()` can't gate body-parse because body parses first
   - Prescribed fix targets the symptom, not the cause
   - Claimed pattern already holds (false positive from the reviewer)

   When dropping, update `review_tasks.md` in the worktree:
   - **Leave the checkbox as `[ ]`** — `close_batch.sh` will mark it `[x]` at merge time alongside other tasks. This keeps the Grand Total counts correct.
   - Append a new line immediately below the task: `  > Dropped: <one-sentence reason>`

   The `> Dropped:` annotation signals to future readers that the task was resolved as a false positive rather than patched.

3. **FAIL** — the task premise is valid but the fix requires decisions outside this batch's scope (e.g., changing a function signature that affects uncited callers). Do not half-fix.

   When failing, update `review_tasks.md` in the worktree:
   - **Leave the checkbox exactly as you found it** — do not mark `[x]`. The task was not done, and `close_batch.sh` reads the annotation below to leave it open at merge time instead of closing it with the rest of the batch.
   - Append a new line immediately below the task: `  > Failed: <one-sentence reason>`

   The `> Failed:` annotation is the **only durable record** that this task was attempted and left unfinished — the verdict summary in step 7 is terminal output that disappears with the session. Without it, a merged batch reads as fully resolved.

## Convention Awareness

Before fixing any task, read `<WORKTREE_PATH>/.claude/convention_map.md`. For each file you plan to edit, find its applicable conventions. Read the relevant `CLAUDE.md` § Prevention Conventions subsection only as needed.

For batches from security audit rounds (`> **OWASP:**` in the batch header), also read `<WORKTREE_PATH>/.claude/security_map.md`.

## Context Awareness

- **Large files (>500 lines)**: use Read with `offset`/`limit` to read ~50 lines around each cited line. Do not read the full file unless the task explicitly requires cross-function analysis.
- **CLAUDE.md**: do not read in full. Load only the convention subsection flagged by convention_map.

## Instructions

All file paths in tasks are relative to the project root. Prepend `<WORKTREE_PATH>/` for Read/Edit.

### 1. Process each task in order

For each task, decide FIX / DROP / FAIL:

- **FIX**: read the file, apply the change using Edit. Include a short inline comment only if the WHY is non-obvious — otherwise no comment (per CLAUDE.md).
- **DROP**: edit `<WORKTREE_PATH>/review_tasks.md` to **leave the checkbox as `[ ]`** and append `  > Dropped: <reason>` under the task line (see § Verdicts). Do **not** pre-mark `[x]` — `close_batch.sh` flips it at merge, and a pre-marked task is invisible to that count, so the Grand Total drifts by one.
- **FAIL**: make no code edit. Edit `<WORKTREE_PATH>/review_tasks.md` to **leave the checkbox unchanged** and append `  > Failed: <reason>` under the task line (see § Verdicts). Also record the reason for the verdict summary.

**Idempotency**: If Edit fails with "old_string not found", read the file and check if `new_string` is already present. If so, the fix is already applied — treat as FIXED and continue.

### 2. Sibling scan (after all FIX verdicts)

For each file you edited, scan the rest of the file for sibling violations of the same convention you just enforced. Fix them in the same commit. This is expected Opus behavior — do not skip this step.

### 3. Commit all changes

Single commit covering FIX edits, DROP and FAIL annotations in review_tasks.md, and sibling fixes:

```bash
cd <WORKTREE_PATH> && git add -A && git diff --cached --quiet && echo "Nothing to commit" || git commit -m "fix: <batch title, lowercase>"
```

If no verdict produced a code change (all DROP and/or FAIL), commit the annotations alone with:

```bash
cd <WORKTREE_PATH> && git commit -m "docs(batch-<N>): drop <count> false-positive tasks"
```

**Never skip this commit because the batch produced no code change.** The `> Dropped:` and `> Failed:` annotations are the batch's entire durable output in that case; an uncommitted worktree edit is discarded with the worktree.

### 4. Run verify (skip if no code changes)

If your commit touched only `review_tasks.md` (only DROP/FAIL annotations, no FIX edits), skip verify.

Otherwise:

```bash
cd <WORKTREE_PATH> && <VERIFY_COMMAND>
```

Pass `timeout: 600000` to the Bash tool. If verify exceeds timeout, treat as failure and report `VERIFY: TIMEOUT`.

### 5. Handle verify failure

If verify fails:
1. Read the error output
2. Check if tests need updating because your fixes changed behavior that tests assert on (co-change rule)
3. Make **ONE** fix attempt
4. Commit: `git commit -m "fix: update test for batch <N> changes"`
5. Re-run verify
6. If still failing, **stop**. Report the error. Do NOT enter a retry loop.

### 6. Push

```bash
cd <WORKTREE_PATH> && git push -u origin HEAD
```

### 7. Report

Return in this exact format:

```
BATCH: <N>
STATUS: PASS or FAIL
VERIFY: PASS, FAIL, TIMEOUT, or SKIPPED
TASKS_FIXED: <count>
TASKS_DROPPED: <count>
TASKS_FAILED: <count>
TASKS:
- TASK-NNN: FIXED — <what you changed and which convention/pattern you followed>
- TASK-NNN: DROPPED — <why the premise is wrong>
- TASK-NNN: FAILED — <why this needs out-of-scope work>
SIBLINGS_FOUND: <count>
SIBLINGS_FIXED: <count>
SIBLINGS:
- <file:line> — <convention>: <description>
ERROR: <description if failed, "none" if passed>
```

**END OF AGENT PROMPT**

---

### 4c. Collect Results

For each agent, extract FIX/DROP/FAIL counts and any errors. If STATUS is FAIL, note the batch. Continue regardless.

### 4d. Create Pending Docs (on any PASS with pushed commits)

If STATUS is PASS and commits were pushed, create a pending-docs file in the worktree. Use Write to create `<WORKTREE_PATH>/sysop/runtime/pending-docs/<sanitized-branch>.md`:

1. `mkdir -p <WORKTREE_PATH>/sysop/runtime/pending-docs` (via Bash)
2. Write the file:

```yaml
---
branch: <branch-name>
date: YYYY-MM-DD
type: infrastructure
roadmap_ids: []
review_task_ids: []
summary: "Batch <N> complete (judgment): <Title>. Fixed <X>, dropped <Y>, failed <Z>."
---
```

If all tasks were DROP (no code change pushed, only review_tasks.md annotation), still create the pending-docs so the batch's close is documented, and push the review_tasks.md commit on the branch.

## Step 5: Summary Report

After all batches are processed:

```
## Auto-Judge Complete

### Processed
| Batch | Title | Status | Fixed | Dropped | Failed | Verify |
|-------|-------|--------|-------|---------|--------|--------|
| 421   | Backend Auth & Middleware | PASS | 8 | 1 | 1 | PASS |
| 424   | Backend Payments | PASS | 6 | 2 | 0 | PASS |

### Deferred (overlapping — use --merge)        <if no --merge, omit if empty>
| Batch | Title | Overlaps With |
|-------|-------|---------------|

### Failed (needs investigation)
| Batch | Title | Error |
|-------|-------|-------|

### Tasks Marked FAILED (need manual finish)
| Batch | Task | Reason |
|-------|------|--------|
| 421   | TASK-2285 | requires cross-module return-shape change |

Each row above is also recorded durably in `review_tasks.md` as a `> Failed:` annotation, and `close_batch.sh` leaves those tasks open when the batch merges — so the batch closes as "shipped, minus these" rather than as fully resolved.

Next steps:
  <if no --merge>
  1. Run /review-close to merge processed batches
  2. Run /auto-judge --merge for <M> overlapping flagged batches
  3. For any FAILED tasks above, use /claim-task <N> to finish manually
  </if>
  <if --merge>
  1. Run /review-close to merge all branches (Opus convention gate + staging verify)
  2. For any FAILED tasks above, use /claim-task <N> to finish manually
  </if>
```
