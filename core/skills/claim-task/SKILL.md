---
name: claim-task
description: Claim a roadmap task or review batch — creates lock, worktree, and enters planning mode
argument-hint: "<TASK_ID or BATCH_NUMBER>"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning inline=reasoning -->

Claim a roadmap task or review batch, create an isolated worktree, and enter plan mode before coding. Follow these steps in order.

> **Helper names** referenced in this skill (e.g., `_sanitize_log`, `useAbortableFetch`, `getDisplayError`, `redact_api_keys`, `shared_cli.py`) are placeholders — substitute the equivalent helpers from your project's `convention_map.md`. Worked examples may also reference specific batch numbers, file paths, or env-var names from the originating project; treat those as illustrations, not literal requirements.

## Pre-flight: Permission Guard

Verify `.claude/settings.json` carries the allow-rules this skill depends on. Under `auto` mode with `skipAutoPermissionPrompt: true`, a missing worktree-add or branch-creation rule will silently halt before the workspace is created.

Read `.claude/settings.json` and confirm `permissions.allow` contains:

- `Bash(git checkout:*)` — Step 4 rollback path on 4b/4c failure (`git checkout tasks/index.yml`).
- `Bash(git worktree add:*)` — transitively invoked by `scripts/claim_task.sh`.
- `Bash(bash scripts/claim_task.sh:*)` — Step 4b worktree + lock creation.
- `Bash(bash scripts/batch_work.sh:*)` — Step 4 review-batch path.
- `Bash(python3 -:*)` — Step 2's `tasks/index.yml` lookup + Step 4a's yaml-round-trip status flip (both are `python3 - <<'PY'` heredocs).
- `Bash(python3 scripts/validate_tasks.py)` / `Bash(python3 scripts/validate_tasks.py:*)` and the `.venv/bin/python3 scripts/validate_tasks.py` / `.venv/bin/python3 scripts/validate_tasks.py:*` venv variants — Step 4c post-claim validator (the venv form is preferred per Phase 45b; the bare form remains for non-venv consumers).
- `Bash(python3 scripts/scope_overlap.py:*)` (and the `.venv/bin/python3` variant) — Step 2's non-blocking overlap advisory. The `git -C <worktree> diff` it shells out to needs **no** separate rule (it's a subprocess of the permitted python call, and read-only `git` auto-passes per `_shared/permission-guard.md` § Notes). This rule is **not** load-bearing — a missing rule (or any non-zero exit) just means the advisory is skipped; the claim still proceeds.
- `Bash(git add tasks/index.yml)` — Step 4d commits the claim.
- `Bash(git commit -m claim:*)` — Step 4d commit message shape.

If any are missing, stop with the `_shared/permission-guard.md` § Algorithm step 4 message (one-line reason: "creates an isolated worktree and a feature branch for the claimed task; queries + updates `tasks/index.yml` via heredoc'd python; runs the schema validator before committing the claim"). Do not proceed.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and continue.

## Step 1: Parse Argument & Classify

Parse `$ARGUMENTS`:

- **Bare integer** (e.g., `116`) or **`BATCH-<N>`** → review batch. Extract the number.
- **Known prefix** (`FEAT-*`, `TECH-*`, `DATA-*`, `UX-*`, `FIX-*`) → roadmap task.
- **Empty or unrecognized** → print usage and stop:
  ```
  Usage: /claim-task <TASK_ID | BATCH_NUMBER>

  Examples:
    /claim-task FEAT-STUDIO-UI     — claim a roadmap task
    /claim-task DATA-SERIES-CROSSWALK
    /claim-task 120                — claim review batch 120
    /claim-task BATCH-120          — same as above
  ```

If `--branch <name>` appears in `$ARGUMENTS`, extract it as the branch override (roadmap tasks only).

## Step 2: Read Context & Validate

**For roadmap tasks** — look the task up in `tasks/index.yml` via Python (never grep YAML). Run:

```bash
python3 - <<'PY' "$TASK_ID"
import sys, yaml
from pathlib import Path

task_id = sys.argv[1]
index_path = Path("tasks/index.yml")
if not index_path.exists():
    print("ERROR: tasks/index.yml not found", file=sys.stderr)
    sys.exit(2)

with index_path.open(encoding="utf-8") as f:
    data = yaml.safe_load(f)

tasks = data.get("tasks", []) or []
match = next((t for t in tasks if t.get("id") == task_id), None)
if not match:
    print(f"ERROR: task '{task_id}' not found in tasks/index.yml", file=sys.stderr)
    sys.exit(3)

status = match.get("status")
body = match.get("body")
print(f"id={match['id']}")
print(f"title={match.get('title', '')}")
print(f"status={status}")
print(f"phase={match.get('phase', '')}")
print(f"effort={match.get('effort', '')}")
print(f"user_action={match.get('user_action', False)}")
print(f"branch={match.get('branch', '')}")
print(f"body={body or ''}")

if status != "open":
    print(f"ERROR: task '{task_id}' has status='{status}'; only 'open' tasks may be claimed", file=sys.stderr)
    sys.exit(4)

if not body:
    print(f"ERROR: task '{task_id}' has no body path set", file=sys.stderr)
    sys.exit(5)

body_full = Path("tasks") / body
if not body_full.exists():
    print(f"ERROR: body file {body_full} does not exist", file=sys.stderr)
    sys.exit(6)
PY
```

Hard-fail (exit and report) if the script exits non-zero. Surface the stderr message verbatim. **Exit-code contract** (typed so the parent can branch without re-parsing stderr):

- `2` — `tasks/index.yml` itself missing (consumer not bootstrapped, or wrong cwd).
- `3` — task ID not found. The user mistyped the ID, or the task lives in `deferred/` / `archive/`. Suggest `/next-task` to find a claimable one.
- `4` — status not `open`. If `in_progress`, check `.locks/<TASK_ID>.lock` for owner info before suggesting takeover. If `done` / `deferred`, the task is closed; stop.
- `5` / `6` — `body:` field missing or the body file doesn't exist on disk. The index entry is broken — `validate_tasks.py` will reject it; fix the entry before re-claiming.

Also list `.locks/*.lock` files to surface concurrent claims:

```bash
ls .locks/*.lock 2>/dev/null
```

If `.locks/<TASK_ID>.lock` already exists, hard-fail with the file contents — another session owns this task. Do not overwrite.

Read the body file `tasks/open/<TASK_ID>.md` in full so it's loaded as context for Step 6 plan mode.

**Overlap advisory (roadmap tasks — non-blocking).** The lock check above only asks "is *this* task claimed?" — it says nothing about whether the task's *files* collide with work already in flight in another worktree. Two claims touching the same files sail through and surface as a merge conflict at `/review-close` — recoverable rework (the worktrees kept the builds isolated), but wasted work the advisory can warn about. Run the shared scope-overlap primitive:

```bash
.venv/bin/python3 scripts/scope_overlap.py <TASK_ID>
```

(The `.venv/bin/python3` form is preferred per Phase 45b so the advisory still fires for consumers whose PyYAML lives only in the venv; bare `python3` also works where PyYAML is on the system interpreter. Both permission rules exist.) It infers the candidate's likely scope from its `## Key files` + `blast_radius` (a *pre-plan guess*), reads the **actual** changed set of each in-flight worktree (`git diff --name-only main...HEAD` + uncommitted), and prints a per-in-flight verdict — `likely` (exact path match) / `possible` (same directory or glob) / `none`.

- **Surface the output verbatim** if it reports any overlap, then continue. This is **advisory, not a gate** — overlap is a recoverable rework cost, not corruption, so the human owns the call (the guided-mode "genuine tradeoff → human owns it" branch, in contrast to the lock collision above, which *is* a false choice and correctly hard-fails). Do **not** block the claim on it.
- The primitive is **non-blocking by construction**: it exits 0 on every degrade path (no in-flight work, missing index, absent PyYAML, an unreadable worktree). Treat *any* non-zero exit or error as "advisory unavailable — proceed"; never halt the claim because the overlap check couldn't run.
- If it warns of a `likely` overlap, it's worth mentioning `/next-task` (which surfaces claimable tasks) as the clean alternative — but the human may legitimately choose to claim the overlapping task anyway (e.g. the collision is small, or they'll coordinate the merge).

**For review batches:**
- Read `review_tasks.md` (full)
- Verify the batch number exists
- Check its status (the backtick-wrapped status after the batch title):
  - `Pending` → available, proceed
  - `In Progress` → check for `.locks/BATCH-<N>.lock`. If locked, report "already claimed" and stop. If no lock, it may be resumable — proceed (the script handles this).
  - `Merged`, `Complete`, `Ready for Review` → report current status and stop

## Step 3: Generate Branch Name

**Roadmap tasks:**
- If `--branch <name>` was provided, use that.
- Else if the task entry has a `branch:` field set in `tasks/index.yml` (surfaced as the `branch=...` line by Step 2's Python script), use it.
- Otherwise, auto-generate from the task ID by lowercasing and mapping the prefix:
  - `FEAT-X` → `feat/feat-x`
  - `TECH-X` → `tech/tech-x`
  - `DATA-X` → `data/data-x`
  - `UX-X` → `ux/ux-x`
  - `FIX-X` → `fix/fix-x`

**Review batches:** The branch is specified in `review_tasks.md` metadata and handled by `batch_work.sh`. No branch generation needed.

## Step 4: Claim the Task

**Roadmap tasks** — four actions, in order. **Each is destructive — print the action before running, then run.** If any step fails, fall through to the rollback at the bottom of this section before reporting.

### 4a. Flip `status: open` → `status: in_progress` in `tasks/index.yml`

Do NOT edit the YAML by hand with a regex — round-trip through `yaml.safe_load` / `yaml.safe_dump` so the file stays validator-clean. PyYAML round-trip loses inline comments — that's acceptable for `index.yml` (sprint prose lives in block scalars which round-trip fine).

```bash
python3 - <<'PY' "$TASK_ID"
import sys, yaml
from pathlib import Path

task_id = sys.argv[1]
index_path = Path("tasks/index.yml")

with index_path.open(encoding="utf-8") as f:
    data = yaml.safe_load(f)

found = False
for t in data.get("tasks", []):
    if t.get("id") == task_id:
        if t.get("status") != "open":
            print(f"ERROR: refusing to flip status; current status='{t.get('status')}'", file=sys.stderr)
            sys.exit(1)
        t["status"] = "in_progress"
        found = True
        break

if not found:
    print(f"ERROR: task '{task_id}' disappeared between Step 2 and Step 4", file=sys.stderr)
    sys.exit(1)

with index_path.open("w", encoding="utf-8") as f:
    yaml.safe_dump(
        data,
        f,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=120,
    )

print(f"OK: flipped {task_id} → in_progress in tasks/index.yml")
PY
```

### 4b. Run the claim script with `--lock` to create the worktree and lock file

The lock file is **required** by the schema for `in_progress` tasks (see `tasks/schema.md` § lock invariant). The script creates `.locks/<TASK_ID>.lock` under the **main** repo's `.locks/` via `git rev-parse --git-common-dir`, so the validator resolves the same path from any working tree. Always pass `--lock`:

```bash
bash scripts/claim_task.sh --lock <TASK_ID> <BRANCH_NAME>
```

This also creates the git worktree at `../<project>-<task-id-lower>/` on `<BRANCH_NAME>` (branched from current HEAD; main if you ran the skill from main).

### 4c. Validate state with `scripts/validate_tasks.py`

This proves the schema invariants hold (status, lock file presence, body existence, ref integrity) before the claim commit lands on `main`:

```bash
.venv/bin/python3 scripts/validate_tasks.py
```

If it fails, **do not proceed to 4d**. Report the validator output verbatim and fall through to the rollback below. Common causes: lock file missing (4b silently failed), body file moved, ID collision introduced upstream.

### 4d. Commit the claim on main

This commit lands on `main` in the shared **primary** worktree, so apply `_shared/main-push-guard.md` **Rule A** first — assert `HEAD` is still `main` (a concurrent `/auto-build` batch or another `/claim-task` session could have moved it). If it is not, STOP and reconcile via `git reflog` rather than committing the claim onto the wrong branch:

```bash
test "$(git rev-parse --abbrev-ref HEAD)" = "main" || {
  echo "HEAD is not main (a concurrent actor moved it) — STOP."; exit 1; }
git add tasks/index.yml && git commit -m "claim: mark <TASK_ID> as in-progress"
```

Run on the main checkout (the worktree at `../<project>-<task-id-lower>/` will pick this up via the shared object DB).

### Rollback on failure of 4b or 4c

If 4b's script exits non-zero, or 4c's validator exits non-zero, undo 4a's uncommitted edit before stopping:

```bash
git checkout tasks/index.yml
```

If 4b created an orphan worktree before failing, also run `bash scripts/cleanup_worktrees.sh --force` to drop it. Then report the failing step's error output and stop.

**Review batches:**
```bash
bash scripts/batch_work.sh <BATCH_NUMBER>
```
The script handles `Pending` → `In Progress` transition in `review_tasks.md` and commits on main automatically. (Review-batch state still lives in `review_tasks.md` — only roadmap tasks live in `tasks/index.yml`.)

If the script exits non-zero, report the error output and stop.

## Step 5: Report Claim Result

Print a summary box:

```
## Claimed: <TASK_ID or Batch N>

| Field     | Value                              |
|-----------|------------------------------------|
| Type      | Roadmap task / Review batch        |
| Worktree  | ../<project>-<task-lower>/         |
| Branch    | <branch_name>                      |

Work in: `<worktree_path>`

When finished, run `/document-work` to commit and prepare for review.
Do NOT merge to main — `/review-close` handles that.
```

## Step 6: Enter Plan Mode

Call the `EnterPlanMode` tool so you design the implementation before writing any code.

In plan mode:
- **Roadmap tasks:** Read the task's full requirements from `tasks/open/<TASK_ID>.md` (or wherever `body:` points in `tasks/index.yml`), explore the referenced files, and produce a structured implementation plan.
- **Review batches:** Read all tasks in the batch from `review_tasks.md`, examine each referenced file and line, and plan the fix order.

**Constraints & Risks (must precede implementation steps):** Read `.claude/convention_map.md` and `.claude/security_map.md`. For each file or directory the plan will create or modify, find its matching sections in **both** maps. Emit a `## Constraints & Risks` heading as the **first** content block after the task summary (Context / problem statement) and **before** any `## Implementation Steps` heading. Under it, list one bullet per file/directory enumerating the applicable conventions and security checks from both maps, plus any cross-cutting rules that apply to the file type (logger formatting, APP_ENV defaults, log sanitization, fetch redirect guards). **One bullet per risk; no prose padding.** Use this structure:

```
## Constraints & Risks

- **`<file or glob>`** — convention/security bullet · convention/security bullet · cross-cutting rule
- **`<another file>`** — …
- **Cross-cutting** — logger `%s` formatting, APP_ENV default `"dev"`, …

### Coverage gap

- **`<file>`** — no matching section in convention_map.md / security_map.md (log for next map-coverage audit)
```

If every touched file matches ≥1 applicable convention from at least one map, write `_(none)_` under `### Coverage gap`. **Do NOT skip a file silently** — an empty match means the maps are missing coverage for that path and must be logged here so `/codebase-review` map-coverage auditing (`WORKFLOW.md §3.6`) can pick it up.

**External SDK/framework call check:** For any plan step that calls an external library, SDK, or framework method (LLM provider SDKs, cloud clients, web-framework APIs), the Constraints & Risks bullet for that file must either **cite an in-repo precedent** (`file:line` of an existing same-project call site using that method the same way) or mark the call **`unverified — no in-repo precedent`**. External APIs drift between releases — a method recalled from memory may no longer exist. The bar is *cite a precedent or flag it*, **not** *verify against live docs* (you may have no web access at plan time, and a static API map would rot the moment the SDK ships a release). `/plan-review`'s adversarial dimension #9 hard-flags any external call that is neither precedent-cited nor flagged.

**Test decision (record in the task body):** As part of the plan, decide how this change is verified and add a plan step to write a `## Test decision` section into the task's body file (`tasks/open/<TASK_ID>.md`, or wherever `body:` points; the reviewer-executor persists it during implementation). The section states either **`test <X> proves <Y>`** — the regression test (existing or new) that pins the behavior this task changes — or **`no test because <Z>`** — the explicit rationale (pure rename/move, config-only, docs, a path an existing named test already covers, or a `manual_smoke:`-only behavior). This is the durable, plan-time record `/review-close` reads back at close time to verify "plan said test X — is it here?" / "plan said no-test-because-Z — does Z still hold?". The adversarial reviewer's "Missing invariant tests" dimension (finding #7) scrutinizes whether a `no test because Z` rationale is sound, so make `Z` reviewable, not a hand-wave. `validate_tasks.py` warns (never blocks) if an `in_progress` task body lacks the section. See `tasks/schema.md` § Test decision.

**Convention & security map gap check:** For each file the plan **creates, moves/refactors into, or deletes**, check both `.claude/convention_map.md` AND `.claude/security_map.md`:

1. **New files**: Check whether the path matches at least one `## ` section header in each map. If not, add a plan step:

```
### Plan Step: Update convention_map.md / security_map.md

New file `<path>` is not covered by any convention_map section.
Action: [Add new section / Expand existing section glob] to cover `<path>`,
then list the applicable Prevention Convention bullets from CLAUDE.md for that file type.

New file `<path>` is not covered by any security_map section.
Action: [Add new section / Expand existing section glob] to cover `<path>`,
then list the applicable OWASP checks from security_map.md for that file type.
```

2. **Moved/refactored files**: When code moves from `<old_path>` to `<new_path>`, the destination may not match any section even though the source did. Check the new path against both maps and add a plan step if unmatched.

3. **Deleted files**: If a file is explicitly named in a map section header (not just matched by glob), removing it leaves a stale reference. Add a plan step to clean up the header:

```
### Plan Step: Clean up map references

Deleted file `<path>` is explicitly named in convention_map.md § <Section Name>.
Action: Remove `<path>` from the section header (or remove the section if it's now empty).
```

This prevents convention coverage gaps from silently accumulating when the codebase grows or refactors split files into new modules (e.g., a single `<api module>` file split into `<api module>/routes/*.py` refactors created files the map didn't cover).

## Step 7: Spawn Reviewer-Executor Sub-Agent (before ExitPlanMode)

Before calling `ExitPlanMode`, hand the plan off to a single sub-agent that performs adversarial review, finding self-classification, plan revision, implementation, post-fix convention check, and post-fix UI verification (if frontend touched). Planning and critique have different attention patterns inside a single session — a planner builds context momentum and stops re-verifying its own citations. By the time post-implementation verification would run, the parent's context holds 40–60K tokens (spec + maps + explored files + plan + diff). Collapsing all of that into one fresh sub-agent keeps the heavy lifting in a context that opens cold.

The parent's role shrinks to: compose the plan (Step 6), spawn this sub-agent, then handle its envelope. The `/document-work` and `/review-close` Opus gates remain the load-bearing safety net for execution-time issues — this step does not weaken them.

Before spawning, print one line so the parent's transcript does not go silent during the sub-agent run:

```
Spawning reviewer-executor sub-agent — adversarial review + classification +
implementation + Steps 9/10 + single commit all run inside it. This may take
5–25 minutes for a moderate task; the parent is waiting on the envelope.
```

### Spawning the sub-agent

- Use the `Agent` tool with:
  - `subagent_type`: `"general-purpose"`
  - `model`: `"opus"` (always — adversarial review + implementation against a fresh plan benefits from full reasoning depth)
  - `run_in_background`: `false` (parent waits synchronously; background mode is reserved for `/auto-build`'s batched-parallel shape)
  - Do NOT set `isolation: "worktree"` — the worktree pre-exists from Step 4; the sub-agent `cd`s into it.
  - `description`: `"Reviewer-executor for <TASK_ID>"`
- `prompt`: the **Reviewer-Executor Prompt** below, with `<TASK_ID>`, `<WORKTREE_PATH>`, `<BRANCH_NAME>`, and `<PLAN_TEXT>` (the full Step 6 plan body verbatim — Constraints & Risks + Implementation Steps) filled in.

### Reviewer-Executor Prompt

---

**START OF REVIEWER-EXECUTOR PROMPT**

You are executing roadmap task `<TASK_ID>`. The parent session has already claimed the task (worktree at `<WORKTREE_PATH>`, lock at `.locks/<TASK_ID>.lock`, branch `<BRANCH_NAME>`, `tasks/index.yml` flipped to `in_progress` on main) and produced the plan below. Your job, in one cold-context pass:

1. Adversarially review the plan.
2. Self-classify findings per `_shared/adversarial-review.md`.
3. If any finding is `blocker`, halt at the BLOCKED envelope.
4. Otherwise, revise the plan inline, call `ExitPlanMode`, implement, run post-fix gates, emit the EXECUTED envelope.

**Working directory:** `<WORKTREE_PATH>` (cd here first; do not run from the project root or any sibling worktree).

**Plan (verbatim from parent):**

```
<PLAN_TEXT>
```

### Sequence

1. **Adversarial review.** Read `.claude/skills/_shared/adversarial-review.md`. Apply its **Prompt Template** verbatim to the plan above. Verify every file:line citation by actually opening the file. Re-grep factual claims.

2. **Emit a sealed `REVIEW_REPORT:` YAML block at the TOP of your response** — BEFORE any implementation discussion. The sealed report acts as a commitment device so findings cannot be silently softened during implementation:

   ```yaml
   REVIEW_REPORT:
     findings:
       - id: F1
         classification: fixable | blocker
         summary: "..."
         response: "incorporated in step X | rejected because Y | (blocker — see envelope)"
     verdict: PROCEED | BLOCKED
   ```

   If you find zero issues, emit `findings: []` and `verdict: PROCEED` explicitly so future reviewers know the step ran clean.

3. **Self-classify** per the **Classification Rubric** in `_shared/adversarial-review.md`:
   - `fixable` — you can revise the plan inline without human input (mis-cited patterns, convention mis-applications, factual drift, missing tests, N+1 patterns, asymmetric error handling).
   - `blocker` — requires human input the agent cannot produce (ambiguous requirements, missing source data the task assumes, conflicting goals between Constraints & Risks and Implementation Steps). Only mark as `blocker` after genuinely trying to resolve by reading more code.

4. **If any finding is `blocker`** → STOP. Emit the BLOCKED envelope (see "Required final-message format" below) with `BLOCKER_QUESTION:` set to the question the human needs to answer. Do NOT call `ExitPlanMode`. Do NOT implement. Do NOT commit.

5. **Otherwise**, revise the plan inline (or document rejection rationale: `> **Adversarial review rejected:** <finding>. Rationale: <why>.`). Call `ExitPlanMode` with the revised plan.

6. **Implement** per the revised plan. Re-open the files the plan touches; do not rely on summaries.

7. **Post-fix convention verification:**
   - `git diff --name-only main...HEAD`
   - For each changed file, look up its section in `.claude/convention_map.md`.
   - Scan the **new/changed lines** (not just original task locations) against those conventions.
   - Common regressions: `fetch()` without `encodeURIComponent()` on dynamic path segments; error handling with `str(e)` exposed to API responses; moved code that dropped `_sanitize_log()` wrappers; `useCallback` with incomplete dependency arrays; SELECT queries on a write-only engine.
   - Fix regressions before committing.

7b. **Run the consumer's pre-merge verification gates.** The consumer project's `<project>/CLAUDE.md § Pre-merge verification` (per WORKFLOW.md § 6.1) may contain two subsections (Phase 17 split shape):
   - **`### Always`** — full-tree commands run unconditionally (lint, typecheck, tests).
   - **`### Ratchet (changed files only)`** — a bash block that filters `git diff --name-only origin/main...HEAD` to specific file types and invokes lint/typecheck against changed files only. Empty filtered list short-circuits and passes.

   Run the commands listed under each subsection that is present. If both are absent, skip — `/review-close` will run any project-side verification at merge time.

   Treat any non-zero exit like an implementation finding: fix the underlying issue, do not silence it without a `# type: ignore[...]` or `// eslint-disable-next-line <rule> -- <reason>` justified inline.

8. **Post-fix UI verification:** if `git diff --name-only main...HEAD` touches any `frontend/` files, run the shared procedure at `.claude/skills/_shared/ui-verify.md`. Hard-fail on console errors and 5xx responses; warn on console warnings; skip cleanly with an explicit note if the dev server is not running. Surface the skip note verbatim in your final message so the human knows manual verification is still required.

9. **Commit your changes** with a conventional commit message (`feat:`, `fix:`, `refactor:`, etc.) — a SINGLE commit on the worktree branch. Derive the message from the task title in `tasks/index.yml` (the `title:` field on the task whose `id:` is `<TASK_ID>`) plus the `<TASK_ID>` itself; this matches how `/document-work` formats messages elsewhere. **Append a `Doc-Work: <TASK_ID>` git trailer on the final line of the commit body**, separated from any body prose by one blank line — this is the deterministic marker `/sitrep` consumes to classify the branch as "ready for `/review-close`" (Phase 40). Format:

   ```
   <type>: <title> (<TASK_ID>)

   <optional body prose>

   Doc-Work: <TASK_ID>
   ```

   Do NOT push. Do NOT write to `.pending-docs/`. Do NOT invoke `/document-work`. The trailer eliminates the need for `/document-work` to amend later just to add the marker; the subsequent `/document-work` run will find the trailer already present and proceed straight to Step 3 documentation.

10. **Emit the EXECUTED envelope** (see below).

### Hard constraints

- Do **NOT** invoke the Agent tool — this run is designed as a leaf. (Claude Code ≥2.1.172 permits nested spawns, but the Phase 37 envelope contract assumes a flat hierarchy; see `_shared/adversarial-review.md` § "Harness constraint".)
- Do **NOT** flip `status:` fields in `tasks/index.yml`. ADDING a new follow-up task entry IS allowed and expected if `/document-work`'s Step 3b would flag an unfiled follow-up ID — file the entry + body file under `tasks/open/` BEFORE the human invokes `/document-work`, or whitelist the ID per `tasks/schema.md`.
- Do **NOT** push to origin (`/review-close` owns the push).
- Do **NOT** invoke `/document-work` (the parent will instruct the human to run it next).

### Required final-message format

Emit exactly this YAML block as the LAST content in your final message, with NO content after the closing backticks. The `REVIEW_REPORT:` block at the TOP of your response is separate from this envelope — both are required:

```yaml
TASK: <TASK_ID>
STATUS: EXECUTED | BLOCKED | FAILED
BLOCKER_QUESTION: <only if BLOCKED — the question for the human; else "none">
WORKTREE: <absolute path, no trailing slash>
BRANCH: <branch name>
ERROR: <error description if FAILED, else "none">
```

> **Envelope-shape note:** `BLOCKER_QUESTION` is the `/claim-task` reviewer-executor's parent-facing field for halt-on-blocker. `/auto-build`'s execution agent uses `PARKED_REASON` instead because parking happens at the orchestrator layer BEFORE execution is spawned — by the time the execution agent runs in auto-build, no blocker can surface. In `/claim-task`, the parent IS the human running it directly, so the sub-agent must be able to surface a blocker question on its own envelope. This divergence is load-bearing for the interactive shape; do not "normalize" the two fields without re-examining the parking-layer split. See `_shared/adversarial-review.md § "Reviewer-executor variant"`.

A malformed envelope (missing keys, content after the closing backticks, status not in `{EXECUTED, BLOCKED, FAILED}`) causes the parent to classify your run as `FAILED` with reason `envelope parse error`. Print Step 7 + Step 7b + Step 8 outputs as prose in the body of your final message ABOVE the envelope so the human can see what happened even if the envelope is malformed.

**END OF REVIEWER-EXECUTOR PROMPT**

---

> **Note for orchestrator-spawned sessions:** Sysop keeps the spawn hierarchy flat — orchestrator-spawned sessions do not nest further agents, even on Claude Code ≥2.1.172 where the harness permits it (through 2.1.171 it was blocked outright). If you are running inside `/auto-build` (rather than from a top-level human prompt), the orchestrator runs the plan + adversarial-review phases at its own top-level layer and supplies you with the absorbed plan; skip this step and proceed to implement against the orchestrator-supplied plan. See `auto-build/SKILL.md` Phase 6a-6e and `_shared/adversarial-review.md` § "Harness constraint".

## Step 8: Receive Envelope + Print Handoff

After the reviewer-executor sub-agent returns, get the envelope. Read in this order — first hit wins; never go past a clean hit to the next source:

1. **JSON file** (preferred, Phase 37). Try to read `.subagent-envelopes/<TASK_ID>.json` (resolved against the main repo root via `git rev-parse --git-common-dir` if you're in a worktree). The `SubagentStop` hook (`scripts/parse_subagent_envelope.py`) parses the sub-agent's final message on the harness's terms and writes structured JSON keyed by the `TASK:` field. Keys you'll need: `status`, `worktree`, `branch`, `error`, `blocker_question`, `review_report_raw`. If the file is missing (hook didn't fire, fired after this read, or crashed) OR `parsed: false` (envelope wasn't found in the agent's final message), continue to (2).
2. **Regex parse of the sub-agent's return text** (existing behavior). Parse the YAML envelope from the LAST content block of the sub-agent's final message. Validate that the envelope has the required keys (`TASK`, `STATUS`, `WORKTREE`, `BRANCH`, `ERROR`). Multiple envelopes → last-wins (matches the prompt's "LAST content" instruction).

The `REVIEW_REPORT:` block at the TOP of the sub-agent's response is read from the response body (or from `review_report_raw` in the JSON if path (1) hit).

**After consuming (1)**, delete the JSON file: `rm -f .subagent-envelopes/<TASK_ID>.json`. The dir is for in-flight handoff only; leftover files accumulate stale state across cycles. Do NOT delete `_unparseable_*.json` diagnostics — those persist intentionally for inspection.

**On `STATUS: EXECUTED`:**

Print the REVIEW_REPORT (from the response body) followed by a handoff summary:

```
## Reviewer-executor returned: EXECUTED

| Field    | Value                              |
|----------|------------------------------------|
| Task     | <TASK_ID>                          |
| Worktree | <WORKTREE_PATH>                    |
| Branch   | <BRANCH_NAME>                      |

The reviewer-executor adversarially reviewed, self-classified, revised the
plan, implemented, ran post-fix gates, and committed your work in the
worktree. It did NOT push. Run `/document-work` next to commit-message-polish,
write the pending-docs handoff, and prepare for review. Do NOT merge to main —
`/review-close` handles that.
```

**Auto-mode chaining (BeanRider ISSUE-0038).** Under `auto` mode, after printing the EXECUTED handoff above, invoke `/document-work` directly via the `Skill` tool rather than ending the turn and waiting for the user to type the command. The chain `claim-task → document-work` is the canonical lifecycle — `/document-work` writes the pending-doc and stages it; it does NOT push or merge, so chaining is safe. Skip the chain (end the turn) when any of: the sub-agent returned `STATUS: BLOCKED` or `STATUS: FAILED`, the UI-verify note flags pending manual checking, the harness is not in `auto` mode, OR the user explicitly asked to pause for inspection in this session. The user can still interrupt mid-chain. The same chaining note does NOT extend to `/document-work → /review-close` — `/review-close` is the senior-reviewer merge gate; that step intentionally stays user-initiated unless a downstream skill version asserts otherwise.

If Step 8 (UI verify) emitted a skipped/manual-verification note, it appears in the sub-agent's final-message body above the envelope — surface that note verbatim to the user so they know what still needs manual checking. Do NOT call `ExitPlanMode` at the parent — the sub-agent already exited plan mode in its own session. The parent's plan-mode state is separate and ends naturally when control returns to the user.

**On `STATUS: BLOCKED`:**

Print the REVIEW_REPORT, the `BLOCKER_QUESTION:` from the envelope (prefixed with `Sub-agent halted on a blocker; needs human input:`), and:

```
## Reviewer-executor returned: BLOCKED

| Field    | Value                              |
|----------|------------------------------------|
| Task     | <TASK_ID>                          |
| Worktree | <WORKTREE_PATH>                    |
| Branch   | <BRANCH_NAME>                      |

Worktree intact. Lock intact. The sub-agent did not call ExitPlanMode and did
not implement. Resolve the blocker (answer the question, add the missing source
data, etc.), then re-run `/claim-task <TASK_ID>` or continue manually in the
worktree.
```

Do NOT call `ExitPlanMode` at the parent — the work is incomplete and a fresh plan may be needed.

**On `STATUS: FAILED`:**

Print the failure summary with the `ERROR` field verbatim. Run `git log --oneline main..HEAD` and `git status --short` in the worktree and surface the output. If substantive work landed despite the failure, let the human decide whether to recover or discard. Do NOT auto-retry; the next move (fix manually in the worktree, re-spawn the sub-agent, or park the task) is theirs.

**On malformed envelope:**

Print `Reviewer-executor returned with malformed envelope — treating as FAILED`. The sub-agent's prose body (above where the envelope should have been) likely contains the implementation output. Surface the prose body to the user so they can see what actually happened. Do NOT auto-retry.

This is the parent session's terminal action for `/claim-task`. Control returns to the user.
