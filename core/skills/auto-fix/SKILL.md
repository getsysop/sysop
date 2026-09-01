---
name: auto-fix
description: Automatically fix mechanical review batches — claims, fixes, verifies, and pushes via isolated agents
argument-hint: "[concurrency] [--batches <selector>] [--merge]"
---
<!-- sysop:model-roles inline=reasoning -->

Automatically process pending review batches that have prescriptive, mechanical fixes. Reads the `Flag:` tags written by `/triage` (the sole writer — see `triage/SKILL.md` § Writer-side contract) and claims + fixes only the unflagged (auto) batches via isolated agents. If any pending batch lacks a `> **Triaged:**` record, invokes `/triage` first as a prereq.

Two-pass workflow:
- **Default mode (pass 1)**: processes only **non-overlapping** auto batches, in parallel. Pushes branches.
- **`--merge` mode (pass 2)**: processes only **overlapping** auto batches, sequentially. Pushes branches.
- Both passes can run concurrently. Run `/review-close` after both complete to merge all branches through the Opus convention gate, staging verification, and push.

> **Helper names** referenced in this skill (e.g., `_sanitize_log`, `useAbortableFetch`, `getDisplayError`, `redact_api_keys`, `shared_cli.py`) are placeholders — substitute the equivalent helpers from your project's `convention_map.md`. Worked examples may also reference specific batch numbers, file paths, or env-var names from the originating project; treat those as illustrations, not literal requirements.

## Pre-flight: Permission Guard

Before parsing arguments or doing any work, verify `.claude/settings.json` carries the allow-rules this skill depends on. Under `dontAsk` mode a missing rule for `git worktree add`, `git push -u origin`, or `bash sysop/scripts/batch_work.sh` is auto-denied with no prompt, halting subagents mid-fix.

Read `.claude/settings.json` and confirm `permissions.allow` contains:

- `Bash(git checkout:*)`
- `Bash(git worktree add:*)`
- `Bash(git push -u origin:*)`
- `Bash(git push origin:*)`
- `Bash(git push --force-with-lease:*)` _(used only when a subagent amends a commit and re-pushes — conditional path; consumers can omit from settings.json if they don't run amend-based fixes)_
- `Bash(bash sysop/scripts/batch_work.sh:*)`

If any are missing, stop with the `_shared/permission-guard.md` § Algorithm step 5 message (one-line reason: "spawns isolated subagents that claim batch worktrees, fix tasks, and push the resulting branches"). Do not proceed — unless the guard's step 3 mode check applies.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and continue.

## Step 0: Parse Arguments

Parse `$ARGUMENTS`:

- **Bare integer** (e.g., `4`) → concurrency cap (max parallel agents). Default: 4. Only affects the default (non-merge) path. All eligible batches are processed regardless — the cap controls how many agents run simultaneously.
- **`--merge`** → process only overlapping batches, sequentially. Fixes and pushes each branch without merging to main. Run `/review-close` afterward to merge all branches through the Opus convention gate. Concurrency cap is ignored (sequential execution).
- **`--batches <selector>`** → narrow this run to the named batches. The selector is comma-separated bare integers and inclusive `<lo>-<hi>` ranges: `--batches 563-584`, `--batches 563,570,580-584`. Applied at Step 1d — after the pool is selected and before Step 4's lane split — so it can only ever narrow what the pool already holds. Omitted, nothing is narrowed. **It is a flag rather than a bare argument on purpose:** a bare integer is already this skill's concurrency cap, so `/auto-fix 563` would set a 563-way cap, and nothing in the invocation would say which of the two was meant. That is the one thing `/auto-build`'s positional task-ID grammar (`auto-build:40`) cannot be copied on — its bare integer and its `^[A-Z]`-shaped IDs are structurally disjoint, and two integers are not.

For an assess-only preview without claiming or fixing, run `/triage --dry-run` directly (Phase 44 extracted the classifier; the old `/auto-fix --dry-run` no longer exists).

## Step 0.5: Triage Prerequisite

Run the index pass from Step 1a and check whether any batch with status **`Pending`** lacks a `> **Triaged:**` record. If any such batch exists, invoke `/triage` via the Skill tool and wait for it to complete. `/triage` will commit any uncommitted `review_tasks.md` additions from `/codebase-review` or `/security-audit`, classify each pending batch as auto or flag, and write the resulting `Triaged:` (and `Flag:`) lines as a single `docs:` commit. After `/triage` returns, re-run the index pass so Step 1 sees the freshly written records.

**Key the check on `Triaged:`, not on `Flag:`.** A `Flag:` tag with no `Triaged:` sibling records no verdict — nothing in it says who wrote it or that anything read the batch — so treating its presence as "already triaged" is how batches get skipped unread. `/triage` re-reads them.

If every pending batch already carries a `Triaged:` record (or no pending batches exist), skip this step — the queue is already triaged.

## Step 1: Read Queue

**Do not read `review_tasks.md` in full.** Most of it is task bodies belonging to batches this skill will not touch. Read it in two passes; see `triage/SKILL.md` § Step 1 for the same procedure stated at length.

### 1a. Index pass

```bash
grep -n -E '^## |^### Batch |^> \*\*(OWASP|Scope|Branch|Verify|Overlap|Flag|Triaged):\*\*' review_tasks.md
```

Each `### Batch N — <title> \`<Status>\`` line gives number, title and status; the `> **Key:**` lines beneath it are its metadata (`Branch:`, `Scope:`, `Verify:`, `Overlap:` — `Overlap:` may be absent on older batches). A batch's **body** runs from its header line to the line *before* the next `^## ` or `^### Batch ` line, or to end-of-file when nothing follows the last batch.

**The index pass is line-oriented and cannot see fenced blocks — check before you trust a boundary.** A task's remediation text routinely quotes the tracker's own shapes (`## Deferred`, `### Batch N — … \`Pending\``, `> **Flag:** <reason>`), and `grep` will report those example lines exactly like real ones. Two consequences, both silent:

- A fenced heading looks like a boundary, so the batch containing it appears to end early and its remaining tasks vanish from your view.
- A fenced `> **Flag:**` or `> **Triaged:**` looks like the enclosing batch's verdict — which is the internal tracker #337 failure mode arriving from inside the file.

So: when a candidate boundary or metadata line sits *inside* a batch you have already bounded, open that region with the scoped read below and look at it before acting on it — a fence is obvious on sight and invisible to `grep`.

**If your boundary disagrees with what `/sitrep` or a claim script reports, do not assume either side is right.** The shipped parsers are fence-aware and you are not, so a *balanced* fenced example explains most disagreements — but not all of them, and the ones it does not explain fail in the opposite direction. An unbalanced fence marker, a column-0 `## ` heading written as prose in a task body, or a batch header whose dash is not an em dash will each make one side see structure the other does not. **Read the region. Do not resolve the disagreement by rule.** One narrow shape is now decided for you: when an *unterminated* fence contains a `### Batch <N>` header whose number **also appears outside it**, the claim, release and close paths refuse and name the offending line — that collision is a contradiction in the file, not a judgement call. `--dry-run` warns instead of refusing. Nothing else is decided: a stray fence with no such collision, a bare `## ` heading inside one, the balanced-fence, prose-heading and dash shapes above are all still yours to read.

Select the auto pool from this output alone:

- **Process** batches with status **`Pending`** that have **no** `> **Flag:**` line.
- **Skip** batches with a `> **Flag:**` line — those belong to `/auto-judge`, including partially-flagged ones (a batch is claimed as a unit, so splitting one across two concurrently-running skills would put two agents on one branch; `/auto-judge` handles the mechanical remainder itself, at Step 4b).
- **Skip** batches with status `In Progress`, `Merged`, `Complete`, or `Ready for Review` — and `Review Ready`, which is **live but not this skill's**: the fix work is done and the batch is waiting on a human to run `/review-close` (Phase 222, Q-014 — the near-identical `Ready for Review` is a *finished* batch; the two are opposites, per WORKFLOW.md § 4's declaration).
- **Refuse and report** a batch whose `> **Triaged:**` line says `flag` but which carries **no** `> **Flag:**` line, and one whose record says `auto` but which *does* carry a `Flag:` line. Both are malformed records — `/triage` writes the pair together — and the first fails toward *this* skill, since the pool test above is literally "no `Flag:` line". Name the batch, do not claim it, and tell the user to re-run `/triage`. Without this the record can say a batch needs judgment while a mechanical agent claims it.

### 1b. Scoped body pass

For each **selected** batch only, read its body — nothing else:

```bash
sed -n '<START>,<END>p' review_tasks.md
```

`<START>` is the batch header's line number; `<END>` is one less than the next `^## ` / `^### Batch ` line number, or `$` **only when no `^## ` section follows the last batch** — on a tracker with a trailing `## Deferred` / `## Statistics` / `## Convention fire ledger`, `$` re-reads the whole tail, which is the thing this pass exists to avoid. Extract all task lines (`- [ ] **TASK-NNN**: description emoji`) and their indented detail lines.

### 1c. Tracker size is advisory, never a stop

If `review_tasks.md` is large (**~125KB** is the historical rule of thumb), print an advisory and **continue** — do not halt. `archive_review_tasks.py` selects what to relocate by **merge status**, not by size (`archive_review_tasks.py:101` matches only `Merged`/`Complete`; a Round moves whole only when every batch in it is merged, otherwise it relocates the merged batches individually), so it cannot shrink a tracker whose bulk is *open* work — which is exactly the state this skill exists to clear. Levers, in order: run this skill and `/auto-judge`, then `/review-close`; once batches are merged, run `python3 sysop/scripts/archive_review_tasks.py`.

### 1d. Optional `--batches` narrowing

When Step 0 collected a `--batches` selector, narrow the pool selected in 1a to it **by intersection**. Expand the selector first: comma-separated bare integers and inclusive `<lo>-<hi>` ranges. A range whose low bound exceeds its high bound is a malformed selector — stop and say so, rather than silently selecting nothing.

**The selector narrows; it never overrides.** Every 1a rule still applies to a named batch: a status other than `Pending`, or the wrong side of the `Flag:` split, keeps it out however explicitly it was named. A selector can shrink the pool, never grow it.

Then print this, and carry it into Step 2's output ahead of the plan table:

```
Selected:  <batch numbers this run will process>
Excluded by --batches: <every pool batch the selector left out>
Requested but not in the pool: <number> — <reason: status is `<Status>`, not Pending / has a Flag: line (belongs to /auto-judge) / no such batch in review_tasks.md>
```

**Report what was excluded, not only what was selected.** A narrowed run and a full run otherwise print the same-shaped report, and the failure that costs is reading a 6-batch run as having cleared a 38-batch queue. A requested number that never reaches the pool is reported with its reason and is never silently dropped.

If the intersection is empty, stop and print the requested numbers with the reason each was excluded — do **not** fall through to the "no batches" message below, which describes an empty queue rather than an empty selection, and would send the operator looking for work that is sitting right there.

## Step 2: Report Plan + Confirm

Print a plan table covering the auto batches this skill will process. Note: the rationale and any flagged-batch decisions are surfaced by `/triage` — this skill's plan is auto-only.

```
## Auto-Fix Plan

| Batch | Title | Tasks | Overlap |
|-------|-------|-------|---------|
| 198   | Scripts: shared_cli.py Migration | 5 | none |
| 200   | Tests: Mock Cleanup | 6 | none |
| 201   | Backend Error Handling | 4 | batch-202 |
| 202   | Backend Logging | 3 | batch-201 |

<if no --merge>
Processing: <N> parallel batches (concurrency: <cap>)
Deferred:  <M> overlapping batches (run /auto-fix --merge concurrently or after)
Flagged:   <K> batches for /auto-judge (see review_tasks.md for Flag: reasons)
           of those, <J> are partially flagged — only <T_J> of their <T_ALL>
           tasks need judgment (from the Triaged: task lists)
Estimated: <N> agent runs
</if>

<if --merge>
Processing: <N> overlapping batches (sequential, push only)
Skipped:   <M> non-overlapping batches (already handled or run /auto-fix without --merge)
Flagged:   <K> batches for /auto-judge (see review_tasks.md for Flag: reasons)
           of those, <J> are partially flagged — only <T_J> of their <T_ALL>
           tasks need judgment (from the Triaged: task lists)
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
4. Assign computed overlap: `none` if no shared files, or a `batch-<N>` list in the declared grammar (`WORKFLOW.md` § Batch metadata fields)

Store the overlap data in memory — do not write back to `review_tasks.md`.

### 4b. Claim and Execute

Determine which auto batches are eligible based on mode. **Test the value whole, never as a substring** (`WORKFLOW.md` § Batch metadata fields):

- **Without `--merge`**: only batches whose `Overlap:` value, trimmed of surrounding whitespace, is **exactly** `none`.
- **With `--merge`**: every other batch — anything that is not exactly `none`.

**Anything you cannot parse counts as overlapping.** A value in an undeclared shape, a trailing comment, `none (batch 5 shares tests/)` — all of them are *overlapping*, because a substring match on `none` there would route a genuinely conflicting batch into the parallel lane. The asymmetry is deliberate: serialising a batch that could have run in parallel costs wall-clock; parallelising one that really overlaps costs a merge conflict and the rework behind it.

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
   a. **Initial fill**: spawn agents for the first `<cap>` claimed batches in a single message with parallel Agent tool calls. Sub-agents have run in the background by default since Claude Code 2.1.198, and `run_in_background` <!-- skill-audit-ok: run_in_background --> is **not** a parameter of the `Agent` tool — its schema is closed, so a compliant call raises `InputValidationError`, and a rejected tool call is itself an invitation to proceed without the step (`Q-031`).
   b. **Refill on completion**: each background agent's completion triggers an automatic notification. Do NOT poll or sleep. When a notification arrives, collect that agent's result; if the queue still has unstarted batches, immediately spawn one new agent for the next queued batch. The in-flight pool stays full until the queue drains.
   c. **Finish**: when the queue is empty and all in-flight agents have completed, proceed to Step 4c.

**With `--merge`** (all eligible batches are overlapping):

Process batches one at a time — **sequentially** claim, fix, and push:
1. Claim the first eligible batch via `batch_work.sh`
2. Spawn **one** fix agent, and spawn nothing else until it reports. There is no parameter that makes a sub-agent run in the foreground — sequencing here is orchestrator discipline, not a flag: wait for that agent's completion notification before doing anything further.
3. After the agent reports (PASS or FAIL), claim and process the next eligible batch
4. Repeat until all eligible batches are processed

Each batch is pushed to origin but NOT merged to main. All merging is deferred to `/review-close`, which runs the Opus convention gate, staging verification, and doc consolidation.

**For each batch**, use the **Agent tool** to spawn a subagent:
- `description`: `"Fix review batch <N>"`
- Do **NOT** set `isolation: "worktree"` — the agent must work in the existing worktree created by `batch_work.sh`
- Set `model: "sonnet"` <!-- sysop:role=mechanical --> — the **mechanical** role (`.claude/served_models.yml`). These fix agents apply prescriptive, mechanical changes, so they are pinned to the cheap tier, not the reasoning tier (Opus is reserved for adversarial review — the verification pass below and `/review-close`'s convention gate). The sibling scan (Step 1b of the agent prompt) and post-fix convention verification (Step 5) are scoped checks of the just-edited files, not broad adversarial review. A consumer who wants a different tier here remaps `mechanical` in `.claude/served_models.local.yml` — **to one of `opus`/`sonnet`/`haiku`/`fable`, not to `inherit`.** This pin is *inline*: its value is handed to the Agent tool's `model` parameter, which is a closed enum, so `inherit` (and `best`, and a full model id) is rejected at spawn time and would break this very agent. Cost-follows-session is not available for an inline pin.

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
the security context, not just code quality conventions. Both lists are **glob-scoped**:
a section whose header glob is still in `<…>` placeholder form matches no file, so it
neither adds a check nor authorises a skip for anything you are fixing.

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

### 1b. Sibling scan (agent-prompt step, not this skill's Step 1b)

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

Pass `timeout: 600000` to the Bash tool call (10 min) — the default 120s is too short for full pytest suites or `npm run build`. If the command exceeds the timeout, **do not treat it as a verify failure.** A timeout is a statement about the *measurement*, not about the code: the command was killed, so it returned no verdict and the work is **unverified** — not verified-broken. Report `VERIFY: TIMEOUT` in Step 7 and **skip § 4 entirely**; that section makes a one-shot code edit to fix a failure, and there is no failure here to read. Editing code on a timeout changes working code on no evidence. Raise the timeout and re-run if you can, and say that it took two attempts.

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
2. For each changed file, re-read the applicable conventions from **`convention_map.md` and `security_map.md`** (`Q-352` — both maps; the third site of the same one-map gap)
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

If an agent reports `STATUS: FAIL`, note the batch as **failed** and continue. `STATUS: PASS` beside `VERIFY: FAIL` is a malformed report — § 4 re-verifies after its one fix attempt, so a passing status cannot honestly ride a failed verify; treat the batch as **failed** (fail-closed) and name the inconsistency in Step 5's Failed table. If it reports `VERIFY: TIMEOUT`, the batch is **unverified, not failed** (Phase 222, Q-283): the verify command was killed and returned no verdict — the same fact the agent instruction in § 3 states, three sections up — so recording it as failed would be a statement about the code made from a measurement that never ran. Note it as **unverified** and continue; it gets its own Step 5 table, and closing it requires a verify re-run first.

### 4d. Opus Verification Pass (for every PASS batch — `STATUS: PASS` *and* `VERIFY: PASS`)

A `VERIFY: TIMEOUT` batch is excluded even when its `STATUS` says PASS: this pass certifies a verified diff, and there is no verified diff to certify — re-run verify first (Step 4c's unverified disposition), then send it through here.

Sonnet's sibling-scan (Step 1b of the agent prompt) and post-fix convention check (Step 5) are weaker than Opus's on the same prompts — prior runs have shown Sonnet-missed siblings (`fix(batch-449): ExportEngine setTimeout`) and cross-convention regressions (`fix: truncate before redact_api_keys`) that only Opus catches reliably. This pass is the scoped safety net.

For each batch that reported `STATUS: PASS` **and** `VERIFY: PASS` (a `VERIFY: TIMEOUT` batch is unverified and skips this pass — see 4c), spawn an **Opus** subagent to re-review the branch's committed diff. Run these in parallel across batches (single message, multiple Agent tool calls — same rolling-window refill used in Step 4b).

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
roadmap_ids: []
review_task_ids: []
summary: "Batch <N> complete: <Title>. <Scope>."
---
```

This file is **untracked** (gitignored). It will be copied to main by `/review-close` Step 3b before the worktree is removed.

**Note:** `/review-close` discovers branches via `git branch -a`, not via lock files — so nothing here waits on a lock. A batch claim *does* write one (`sysop/runtime/locks/BATCH-<N>.lock`, Phase 156): it is the in-flight signal `/next-task`, `/sitrep` and `scope_overlap.py` read, not a gate on this skill. `batch_work.sh` writes it idempotently, so claiming batches in a loop is unaffected, and `close_batch.sh` releases it at `/review-close` Step 4b.

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

### Unverified (verify timed out — no verdict; re-run verify before closing)
| Batch | Title | Verify Command |
|-------|-------|----------------|
| (none) | | |

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
