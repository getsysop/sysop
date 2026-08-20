---
name: triage
description: Classify pending review batches as auto (mechanical) or flag (judgment) and persist a dated, task-granular verdict to review_tasks.md. Idempotent. Prerequisite for /auto-fix and /auto-judge.
argument-hint: "[--dry-run]"
---

A standalone classifier for review batches. Reads `review_tasks.md`, classifies every pending batch lacking a `> **Triaged:**` record as **auto** (prescriptive, mechanical) or **flag** (requires human judgment), writes that record — plus a `> **Flag:**` reason on flagged batches — and prints a classification table.

This skill is the prerequisite step for `/auto-fix` (which fixes auto batches) and `/auto-judge` (which processes flag batches). Both invoke `/triage` automatically when any pending batch lacks a `Triaged:` record, so you only run `/triage` directly when you want the assessment without committing to fix work — or when you want `/sitrep` to give you a deterministic routing recommendation on its next run.

## The two metadata lines, and why there are two

`/triage` is the **sole writer** of both. See § Writer-side contract at the end of this file — it is a contract on the *generators* as much as on this skill.

| Line | Shape | Meaning |
|---|---|---|
| `> **Flag:**` | `> **Flag:** <free-text reason>` | Human-readable: why this batch needs judgment. **Its presence is the pool predicate** — `/auto-judge` takes the batch, `/auto-fix` skips it. Unchanged from earlier versions. |
| `> **Triaged:**` | `> **Triaged:** <YYYY-MM-DD> <auto\|flag> [<TASK-NNN, …>] — <optional note>` | Machine-readable verdict: which run classified this batch, what it decided, and — on a `flag` verdict — exactly **which tasks** need judgment. The bracketed list is optional; absent means the whole batch needs judgment. |

**A `Flag:` line with no `Triaged:` sibling is a tag of unknown provenance, and this skill treats it as untriaged.** Nothing inside a `Flag:` line says who wrote it or that anything ever read the batch — so a tag an emitting agent produced by pattern-matching its neighbours is indistinguishable from a verdict a classifier reached. The `Triaged:` record is what makes the difference legible.

**Both lines are optional in the sense that a parser must tolerate their absence, and neither may be written by anything but `/triage`.**

> **Helper names** referenced below (e.g., `_sanitize_log`, `useAbortableFetch`, `shared_cli.py`) are placeholders — substitute the equivalent helpers from your project's `convention_map.md`.

## Pre-flight: Permission Guard

This skill stages and commits a single file (`review_tasks.md`) when it writes triage records. Under `dontAsk` mode those commits are auto-denied with no prompt unless explicit allow-rules cover them.

Read `.claude/settings.json` and confirm `permissions.allow` contains:

- `Bash(git add review_tasks.md)`
- `Bash(git commit -m docs:*)`

Read-only ops (`git status`, `git log`, etc.) are auto-approved in every permission mode and do not need rules.

If any required rule is missing, stop with the `_shared/permission-guard.md` § Algorithm step 5 message (one-line reason: "stages and commits `review_tasks.md` to persist triage records so future /auto-fix and /auto-judge runs skip re-analysis"), unless the guard's step 3 mode check applies.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and continue.

## Step 0: Parse Arguments

- **`--dry-run`** → classify and print the table, but do NOT write `Triaged:` / `Flag:` lines or commit. Useful as a no-op preview when you only want to see what `/triage` would do.

## Step 1: Read Queue

**Do not read `review_tasks.md` in full.** Most of the file is task bodies belonging to batches this run will not classify, and an active tracker grows without bound — reading all of it is what made a size ceiling look necessary in the first place. Read it in two passes.

### 1a. Index pass

One command returns every batch header and every metadata line, with line numbers:

```bash
grep -n -E '^## |^### Batch |^> \*\*(OWASP|Scope|Branch|Verify|Overlap|Flag|Triaged):\*\*' review_tasks.md
```

Each `### Batch N — <title> \`<Status>\`` line gives the number, title and status. The `> **Key:**` lines beneath it, up to the next `^## ` or `^### Batch ` line, are that batch's metadata. Those same two patterns bound each batch's **body**: it runs from the batch header line to the line *before* the next `^## ` or `^### Batch ` line, or to end-of-file when nothing follows the last batch. (The `^## ` half is load-bearing — without it the last batch's body swallows whatever standalone section follows it, e.g. `## Convention fire ledger`.)

**The index pass is line-oriented and cannot see fenced blocks — check before you trust a boundary.** A task's remediation text routinely quotes the tracker's own shapes (`## Deferred`, `### Batch N — … \`Pending\``, `> **Flag:** <reason>`), and `grep` will report those example lines exactly like real ones. Two consequences, both silent:

- A fenced heading looks like a boundary, so the batch containing it appears to end early and its remaining tasks vanish from your view.
- A fenced `> **Flag:**` or `> **Triaged:**` looks like the enclosing batch's verdict — which is the internal tracker #337 failure mode arriving from inside the file.

So: when a candidate boundary or metadata line sits *inside* a batch you have already bounded, open that region with the scoped read below and look at it before acting on it — a fence is obvious on sight and invisible to `grep`.

**If your boundary disagrees with what `/sitrep` or a claim script reports, do not assume either side is right.** The shipped parsers are fence-aware and you are not, so a *balanced* fenced example explains most disagreements — but not all of them, and the ones it does not explain fail in the opposite direction. An unbalanced fence marker, a column-0 `## ` heading written as prose in a task body, or a batch header whose dash is not an em dash will each make one side see structure the other does not. **Read the region. Do not resolve the disagreement by rule.** One narrow shape is now decided for you: when an *unterminated* fence contains a `### Batch <N>` header whose number **also appears outside it**, the claim, release and close paths refuse and name the offending line — that collision is a contradiction in the file, not a judgement call. `--dry-run` warns instead of refusing. Nothing else is decided: a stray fence with no such collision, a bare `## ` heading inside one, the balanced-fence, prose-heading and dash shapes above are all still yours to read.

Build the candidate set from this output alone:

- **Candidate** = status is **`Pending`** **and** the batch carries no `> **Triaged:**` line.
- **Skip** batches with status `In Progress`, `Merged`, `Complete`, or `Ready for Review`.
- **Carry forward** `Pending` batches that already have a `> **Triaged:**` line — their verdict is recorded; Step 2 does not re-analyze them.

Note each candidate's `Branch:` and `Overlap:` values (both come from the index pass; `Overlap:` may be absent on older batches) and its body line range. `Overlap:` is `none` or a `batch-<N>, batch-<M>` list, tested **whole** after trimming surrounding whitespace — anything that is not exactly `none`, including an unparseable value, counts as overlapping (`WORKFLOW.md` § Batch metadata fields). This skill only records the value; `/auto-fix` and `/auto-judge` are what route on it.

If there are no candidates, print `No batches to classify.` and exit cleanly — the queue is already triaged.

### 1b. Scoped body pass

For each **candidate** batch only, read its body — nothing else:

```bash
sed -n '<START>,<END>p' review_tasks.md
```

where `<START>` is the batch header's line number and `<END>` is one less than the next `^## ` / `^### Batch ` line number, or `$` **only when no `^## ` section follows the last batch** — on a tracker with a trailing `## Deferred` / `## Statistics` / `## Convention fire ledger`, `$` re-reads the whole tail, which is the thing this pass exists to avoid. An agent with a ranged file-read tool may use that instead; the bounds are the same. Extract all task lines (`- [ ] **TASK-NNN**: description emoji`) and their indented detail lines.

### 1c. Tracker size is advisory, never a stop

The two passes above are why this step no longer has a size gate. If `review_tasks.md` is large (**~125KB** is the historical rule of thumb), print an advisory and **continue** — do not halt:

> `review_tasks.md` is <SIZE>. This does not block triage. Note that `archive_review_tasks.py` selects what to relocate by **merge status**, not by size (`archive_review_tasks.py:101` matches only `Merged`/`Complete`; a Round moves whole only when every batch in it is merged, otherwise it relocates the merged batches individually), so it cannot shrink a tracker whose bulk is *open* work. The levers, in order: close open batches (`/auto-fix`, `/auto-judge`, then `/review-close`), then — once batches are merged — run `python3 sysop/scripts/archive_review_tasks.py`.

A halt here was a dead end whenever the overflow was open work, which is the case archiving cannot answer.

### 1d. Preserve Uncommitted `review_tasks.md`

Check `git status -- review_tasks.md` for uncommitted changes. The `/codebase-review` and `/security-audit` skills generate new pending batches in `review_tasks.md` without committing them — those additions must not be bundled into the triage commit from Step 4.

If uncommitted changes exist:

```bash
git add review_tasks.md && git commit -m "docs: save pending review tasks"
```

This **must** happen before Step 4 writes verdicts, so the triage commit only contains classification changes. It runs *after* the index pass on purpose: those uncommitted batches are exactly the ones this run has to classify, so the passes above must see them.

## Step 2: Classify Batches

**Already-triaged batches:** a batch carrying a `> **Triaged:**` line was classified by a prior run. Carry its verdict (and `Flag:` reason, if any) forward to Step 3's table — do not re-analyze its tasks.

**A bare `Flag:` tag is not a prior verdict.** If a `Pending` batch has a `Flag:` line and no `Triaged:` line, it is a **candidate**: re-analyze it. Carry the existing reason text into whatever this run decides — never discard it (Step 4 says where it goes on each verdict).

> **Legacy cost, named so it does not surprise anyone.** On the first run after a tracker adopts the `Triaged:` record, every batch tagged by an earlier run re-opens for classification, because none of them carries the record. A settled-looking queue will churn once. That is the right direction — re-reading a flagged batch costs one pass, skipping an unread one costs the whole batch — but it is a real cost and the run should say so in its output.

For each candidate batch, read every task description (from Step 1b's scoped read) and decide, **per task**, whether it needs judgment.

### A task needs judgment if it matches any of these signals:

- **Open-ended design choice**: description contains "choose between", "decide", "select an approach", "design", "evaluate"
- **External knowledge required**: "requires understanding", "depends on.*behavior", "configure.*appropriate", "consult.*documentation"
- **Architectural refactoring**: "extract.*shared method", "refactor into.*helper", "create a.*abstraction", "consolidate.*into"
- **No prescriptive fix**: the task describes a problem but does not specify what code to write or which function/helper to use
- **Multiple viable solutions** described with no clear recommendation

### A task is auto if it has:

- **Prescriptive remediation**: "Replace X with Y", "Add Z guard", "Wrap in...", "Use helper...", "Migrate to...", "Apply `shared_cli.py`"
- **Specific file:line locations**
- **A known pattern to follow**: references a canonical example, existing helper, or specific function

**Important:** When a *task* is borderline, treat it as needing judgment. A false judgment call costs one Opus read of one task. A false auto produces a bad fix that wastes review time.

### Batch verdict

- **auto** — no task in the batch needs judgment. The batch is wholly mechanical.
- **flag** — at least one task needs judgment. **Record which ones, by task ID.** They are the only tasks that need judgment; the rest of the batch stays mechanical and `/auto-judge` fixes them prescriptively without paying for adversarial re-reading.

**Naming the tasks is the payload of the verdict, not a nicety.** A verdict with no ID list pulls every task in the batch into the judgment lane, and batches now run 14–50 tasks where they once ran ~5 — so one judgment task can drag up to 49 mechanical ones with it. If the judgment genuinely cannot be attributed to specific tasks, omit the list; the whole batch is then flagged, exactly as before. Omit it because it is true, not because listing is work.

## Step 3: Report Classification

Print a classification table:

```
## Triage Plan

| Batch | Title | Tasks | Class | Judgment | Reason |
|-------|-------|-------|-------|----------|--------|
| 198   | Scripts: shared_cli.py Migration | 5 | Auto | — | All prescriptive migrations to shared_cli.py |
| 200   | Tests: Mock Cleanup | 6 | Auto | — | All add afterEach / fix assertions |
| 203   | Data Exposure & Alerting | 14 | Flag | 1 of 14 | TASK-1124: open-ended sanitizer choice |
| 205   | Security Configuration | 4 | Flag | 4 of 4 | requires GCP LB knowledge; not attributable per task |

Classified: <NEW_AUTO> auto, <NEW_FLAG> flag (<NEW_UNSTAMPED> of them re-read from unstamped tags).
Carried forward: <CARRIED> batches with an existing Triaged: record.
Flag rate: <F> of <T> pending batches (<P>%) — <J> of <TOTAL_TASKS> tasks need judgment.
```

Group rows by class (auto first, then flag) so the routing surface is scannable. The **Judgment** column is `<len(ID list)> of <batch task count>`, or `<N> of <N>` when the verdict carries no ID list.

### 3b. Report a vacuous rate as the no-signal outcome it is

Compute the flag rate over the **pending** batches this run classified *plus* those it carried forward — the queue `/auto-fix` and `/auto-judge` will actually route on.

**If the flag rate is ≥ 80% and there are ≥ 5 pending batches**, print this notice immediately above Step 5's recommendation:

```
⚠ Low-signal classification: <F> of <T> pending batches flagged (<P>%).
  A classifier that flags nearly everything carries no routing information —
  the recommendation below is a near-total routing to the expensive lane, not
  a split. Worth checking before you act on it:
    - Task-level: <J> of <TOTAL_TASKS> tasks are actually named as needing
      judgment. If that fraction is small, the batches are flagged by
      association, not on their merits.
    - Provenance: <NEW_UNSTAMPED> of these were re-read from tags with no
      Triaged: record. If that number is large, an earlier writer was tagging
      batches it had not classified.
```

**Both thresholds are chosen, not measured** — 80% and 5 batches are a judgement about when a split stops being a split, and nothing here calibrates them. Say so if the user asks. Do **not** suppress the recommendation; print it under the notice, so the operator sees the routing and the reason to distrust it together.

Sysop's own review skills argue against detectors that fire on everything (`_shared/fanout-evidence.md` § Adjudication; the demotion loop's stale-verdict ledger). A near-total flag rate is the same shape, in the router.

## Step 4: Persist the Verdict

If `--dry-run`, **stop here** — do NOT write lines, do NOT commit. Print `Dry-run: no verdicts written.` and exit.

Otherwise, get the run date once:

```bash
date -u +%Y-%m-%d
```

For **every batch this run classified** (not only the flagged ones — an auto verdict is a verdict, and recording it is what stops the next run re-reading the batch), insert the lines below into the batch header, after the last existing metadata tag (`Overlap:`, `Verify:`, `Branch:`, `OWASP:`, etc.). Leave carried-forward batches untouched.

**Verdict = flag:**

```markdown
> **Flag:** TASK-1124: open-ended sanitizer choice
> **Triaged:** 2026-08-03 flag [TASK-1124]
```

- Write the `Flag:` line only if the batch does not already have one; if it does, leave its text as-is (it is the prior author's reason, and this run agreed with the direction).
- The bracketed list holds every task ID that needs judgment, comma-separated. **Omit the brackets entirely** when the judgment is not attributable per task — that means "the whole batch", which is the pre-existing behaviour.

**Verdict = auto:**

```markdown
> **Triaged:** 2026-08-03 auto
```

- If the batch carried an **unstamped `Flag:` line** that this run re-read and reclassified as auto, **delete that `Flag:` line** (it is the pool predicate — leaving it would keep the batch in `/auto-judge`'s pool against the verdict) and preserve its text in the record:

  ```markdown
  > **Triaged:** 2026-08-03 auto — superseded unstamped flag: "requires GCP LB knowledge"
  ```

  Never drop the prior reason silently. A future reader needs to see that a reason existed and what this run decided about it.

If zero batches were classified (everything was carried forward), skip the commit — `git diff review_tasks.md` will be empty and there is nothing to record.

Otherwise commit:

```bash
git add review_tasks.md && git commit -m "docs: triage <N> review batches (<F> flagged)"
```

This persists the classification so future `/triage` / `/auto-fix` / `/auto-judge` / `/sitrep` runs skip re-analysis, and so anyone browsing `review_tasks.md` can see when each batch was classified and what needs manual work.

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

`/auto-fix` and `/auto-judge` invoke `/triage` automatically at their Step 0.5 when any pending batch lacks a `Triaged:` record. In that case, `/triage` runs end-to-end (writes verdicts, commits), then control returns to the calling skill which re-runs its own index pass and proceeds. The closing recommendation from Step 5 is still printed but is informational only — the calling skill ignores it because it already knows what it's doing.

## Writer-side contract

**`/triage` is the only writer of `> **Flag:**` and `> **Triaged:**`.** Six shipped surfaces read these lines — this skill, `/auto-fix`, `/auto-judge`, `/sitrep`, `review_index.py` and `sitrep_survey.py` — and before this contract existed, exactly one skill wrote them while nothing said so. The consequence was not hypothetical: a review generator's emitting agent, pattern-matching the metadata of batches already in the file, produced `Flag:` lines about its own findings, and `/triage` read them as prior verdicts and skipped those batches unread.

Rules:

1. **Generators do not write these lines.** `/codebase-review` and `/security-audit` emit `Scope:` / `Branch:` / `Verify:` / `Overlap:` (and `OWASP:` for security batches) and nothing else. A batch arrives from a generator with no verdict, because a generator has not made one.
2. **Nothing writes `Flag:` without also writing `Triaged:`.** A reason with no record is exactly the ambiguity this contract removes.
3. **A reader treats an unstamped `Flag:` as untriaged**, not as a prior verdict. `/triage` Step 2 does; so does `/sitrep` (`sitrep_survey.py`, priority 4a).
4. **Hand-editing is fine and is not an exception** — a human who flags a batch by hand should write both lines, dating the `Triaged:` line to the day they did it. The record says *when a decision was made*, not *which program made it*.

Two consumers parse these lines with duplicated regexes (`review_index.py`, `sitrep_survey.py`); the patterns are pinned equal by `tests/test_flag_contract.py`. If you change the shape of either line, that test names both sites.
