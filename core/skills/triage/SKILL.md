---
name: triage
description: Classify pending review batches as auto (mechanical) or flag (judgment) and persist the verdict to review_tasks.md. Idempotent. Prerequisite for /auto-fix and /auto-judge.
argument-hint: "[--dry-run]"
---

A standalone classifier for review batches. Reads `review_tasks.md`, classifies every pending batch lacking a `> **Flag:**` tag as **auto** (prescriptive, mechanical) or **flag** (requires human judgment), writes the `Flag:` tag for flagged batches, and prints a classification table.

This skill is the prerequisite step for `/auto-fix` (which fixes auto batches) and `/auto-judge` (which processes flag batches). Both invoke `/triage` automatically when any pending batch lacks a `Flag:` tag, so you only run `/triage` directly when you want the assessment without committing to fix work — or when you want `/sitrep` to give you a deterministic routing recommendation on its next run.

> **Helper names** referenced below (e.g., `_sanitize_log`, `useAbortableFetch`, `shared_cli.py`) are placeholders — substitute the equivalent helpers from your project's `convention_map.md`.

## Pre-flight: Permission Guard

This skill stages and commits a single file (`review_tasks.md`) when it writes `Flag:` tags. Under `auto` mode + `skipAutoPermissionPrompt: true`, those commits silently halt without explicit allow-rules.

Read `.claude/settings.json` and confirm `permissions.allow` contains:

- `Bash(git add review_tasks.md)`
- `Bash(git commit -m docs:*)`

Read-only ops (`git status`, `git log`, etc.) are auto-approved under `auto` mode and do not need rules.

If any required rule is missing, stop with the `_shared/permission-guard.md` § Algorithm step 4 message (one-line reason: "stages and commits `review_tasks.md` to persist Flag tags so future /auto-fix and /auto-judge runs skip re-analysis").

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and continue.

## Step 0: Parse Arguments

- **`--dry-run`** → classify and print the table, but do NOT write `Flag:` tags or commit. Useful as a no-op preview when you only want to see what `/triage` would do.

## Step 1: Read Queue

Read `review_tasks.md` in full. If it exceeds 125KB, stop and tell the user to run `.venv/bin/python3 scripts/archive_review_tasks.py` first.

Find all batches with status **`Pending`**. For each, extract:

- Batch number and title
- Branch name (from `> **Branch:** \`...\``)
- Overlap tag (from `> **Overlap:** ...`) — may be absent on older batches
- Flag tag (from `> **Flag:** ...`) — present only if a prior `/triage` (or pre-Phase-44 `/auto-fix`) run flagged this batch
- All task lines (`- [ ] **TASK-NNN**: description emoji`)

**Skip** batches with status `In Progress`, `Merged`, `Complete`, or `Ready for Review`.

If no pending batches without a `Flag:` tag exist, print `No batches to classify.` and exit cleanly — the queue is already triaged.

### 1b. Preserve Uncommitted `review_tasks.md`

Check `git status -- review_tasks.md` for uncommitted changes. The `/codebase-review` and `/security-audit` skills generate new pending batches in `review_tasks.md` without committing them — those additions must not be bundled into the Flag-tag commit from Step 4.

If uncommitted changes exist:

```bash
git add review_tasks.md && git commit -m "docs: save pending review tasks"
```

This **must** happen before Step 4 writes Flag tags, so the Flag commit only contains classification changes.

## Step 2: Classify Batches

**Already-flagged batches:** If a batch has a `Flag:` tag from Step 1, it was flagged by a prior run. Carry the stored reason forward to Step 3's table — do not re-analyze its tasks.

For each remaining pending batch, read every task description and classify the **entire batch** as **auto** or **flag**.

### Flag the entire batch if ANY task matches these signals:

- **Open-ended design choice**: description contains "choose between", "decide", "select an approach", "design", "evaluate"
- **External knowledge required**: "requires understanding", "depends on.*behavior", "configure.*appropriate", "consult.*documentation"
- **Architectural refactoring**: "extract.*shared method", "refactor into.*helper", "create a.*abstraction", "consolidate.*into"
- **No prescriptive fix**: the task describes a problem but does not specify what code to write or which function/helper to use
- **Multiple viable solutions** described with no clear recommendation

### Auto if ALL tasks have:

- **Prescriptive remediation**: "Replace X with Y", "Add Z guard", "Wrap in...", "Use helper...", "Migrate to...", "Apply `shared_cli.py`"
- **Specific file:line locations**
- **A known pattern to follow**: references a canonical example, existing helper, or specific function

**Important:** When a batch is borderline, flag it. False flags cost one manual `/claim-task` cycle. False autos produce bad fixes that waste review time.

## Step 3: Report Classification

Print a classification table:

```
## Triage Plan

| Batch | Title | Tasks | Class | Reason |
|-------|-------|-------|-------|--------|
| 198   | Scripts: shared_cli.py Migration | 5 | Auto | All prescriptive migrations to shared_cli.py |
| 200   | Tests: Mock Cleanup | 6 | Auto | All add afterEach / fix assertions |
| 203   | Data Exposure & Alerting | 4 | Flag | TASK-1124: open-ended sanitizer choice |
| 205   | Security Configuration | 4 | Flag | TASK-1127: requires GCP LB knowledge |

Classified: <NEW_FLAG> newly flagged, <ALREADY_FLAGGED> already flagged, <AUTO> auto.
```

Group rows by class (auto first, then flag) so the routing surface is scannable.

## Step 4: Persist Flag Tags

If `--dry-run`, **stop here** — do NOT write tags, do NOT commit. Print `Dry-run: no tags written.` and exit.

Otherwise, for each batch newly classified as **flag** (i.e., it did not already have a `Flag:` tag from Step 1), insert a `> **Flag:**` line into the batch header. Place it after the last existing metadata tag (`Overlap:`, `Verify:`, `Branch:`, etc.):

```markdown
> **Flag:** TASK-1124: open-ended sanitizer choice
```

If zero new flag verdicts were written (everything classified `auto`, or all flag verdicts already had tags from a prior run), skip the commit — `git diff review_tasks.md` will be empty and there is nothing to record.

Otherwise commit:

```bash
git add review_tasks.md && git commit -m "docs: flag <N> batches for manual work"
```

This persists the classification so future `/triage` / `/auto-fix` / `/auto-judge` runs skip re-analysis and so anyone browsing `review_tasks.md` can see why the batch needs manual work.

## Step 5: Recommend Next

Print a single closing line that names the next skill to run, based on the post-triage queue:

| State                                              | Recommendation                                                     |
| -------------------------------------------------- | ------------------------------------------------------------------ |
| ≥1 auto batch, 0 flag batches                      | `Run /auto-fix to fix the auto batches.`                        |
| 0 auto batches, ≥1 flag batches                    | `Run /auto-judge to process the flag batches.`                     |
| ≥1 auto batch, ≥1 flag batches                     | `Run /auto-fix and /auto-judge concurrently (disjoint pools).`  |
| 0 auto batches, 0 flag batches (all closed)        | `No review work pending. Consider /auto-build or /next-task.`      |

This is informational — `/triage` does not invoke the next skill. The caller (a human, or `/auto-fix` / `/auto-judge` running `/triage` as a prereq) decides.

## When `/triage` is invoked as a prereq

`/auto-fix` and `/auto-judge` invoke `/triage` automatically at their Step 0.5 when any pending batch lacks a `Flag:` tag. In that case, `/triage` runs end-to-end (writes tags, commits), then control returns to the calling skill which re-reads `review_tasks.md` and proceeds. The closing recommendation from Step 5 is still printed but is informational only — the calling skill ignores it because it already knows what it's doing.
