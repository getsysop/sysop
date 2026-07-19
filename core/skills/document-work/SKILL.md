---
name: document-work
description: Commit, document, and prepare completed work for review
---

The "I'm done" skill. Commits code changes, writes documentation to the right files, and prepares everything for `/review-close`.

> **Helper names** referenced in this skill (e.g., `_sanitize_log`, `useAbortableFetch`, `getDisplayError`, `redact_api_keys`, `shared_cli.py`) are placeholders — substitute the equivalent helpers from your project's `convention_map.md`. Worked examples may also reference specific batch numbers, file paths, or env-var names from the originating project; treat those as illustrations, not literal requirements.

## Pre-flight: Permission Guard

This skill ends with `git push -u origin HEAD`. Under `auto` mode with `skipAutoPermissionPrompt: true`, a missing push allow-rule will halt the session after work is committed locally but before it reaches the remote — confusing because everything *looks* successful until the push step.

Read `.claude/settings.json` and confirm `permissions.allow` contains:

- `Bash(git push -u origin:*)`
- `Bash(git push origin:*)`
- `Bash(python3 -:*)` — required by Step 3b's heredoc'd follow-up-stub check (shipped in Phase 16.1)

If any are missing, stop with the `_shared/permission-guard.md` § Algorithm step 4 message (one-line reason: "pushes the documented branch upstream as the final step before `/review-close`, after Step 3b's `python3` heredoc verifies named follow-up task IDs resolve in `tasks/index.yml`"). Do not proceed.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and continue.

## Step 0: Parse Arguments

Parse `$ARGUMENTS` for the optional `--non-interactive` flag:

- **`--non-interactive`** → invoked by an `/auto-build` execution agent (Phase 6e), NOT by a human. Affects three steps later in this skill:
  - **Step 2 (Commit)** — derive the commit message from `tasks/index.yml § tasks[]` `title:` + `<TASK_ID>` (resolve `<TASK_ID>` from the current branch name) rather than asking the human.
  - **Step 4 (Verify)** — skip the human-confirm prompt; print the pending-docs contents to stdout (so the parent's transcript captures them) and proceed to Step 5.
  - **Step 5 (Prepare)** — do NOT `git push`. `/review-close` owns the push from the orchestrator-driven flow.
- **Bare invocation (no flag)** → interactive mode (default behavior). All three steps prompt or push as documented.

Step 3b (HARD FAIL follow-up stub check) is identical in both modes — non-interactive callers honor the gate the same way.

A direct human invocation of `/document-work --non-interactive` is not blocked, but it's intended for orchestrator use; behavior in a non-orchestrator context is "skip the prompts" and may not produce the result a human expects.

## Step 1: Gather Context

Run these in parallel:
- `git status` — check for uncommitted changes
- `git log --oneline -5` — recent commits
- `git branch --show-current` — current branch
- `git diff --stat` — unstaged changes summary
- `git diff --cached --stat` — staged changes summary

Also read `tasks/index.yml` to check if the work maps to a task ID. The body for any referenced ID lives at `tasks/<status>/<TASK-ID>.md` (status resolved from the index entry's `status:` field).

## Step 1b: Simplify Pass

Before committing, review all staged and unstaged changes for inline quality improvements:

1. Read `.claude/convention_map.md`. For each file in the diff, note the applicable conventions (4-7 per file section).
2. Read the diff (`git diff` + `git diff --cached`) and check against:
   - **Convention map violations** — the 4-7 conventions listed for each file's matching section
   - **Duplicated logic** — code that reimplements an existing helper (e.g., `_latest_obs_sql()`, `_escape_like()`, `getDisplayError()`, `useAbortableFetch()`, `isSafeHref()`, `validate_identifier()`)
   - **Unnecessary complexity** — verbose patterns that can be simplified without changing behavior
3. Fix any issues found inline — edit the source files directly, citing the convention map section
4. If nothing needs simplifying, proceed silently to Step 2

This step catches reuse and quality issues *before* they're committed, so the review gate in `/review-close` sees clean code.

## Step 1c: UI Verification

If the staged + unstaged diff touches `frontend/`, run the shared UI
verification procedure at `.claude/skills/_shared/ui-verify.md` before
committing. Hard-fail on console errors; warn on console warnings; skip
cleanly if the dev server is not running.

This is the same gate `/claim-task` Step 7's reviewer-executor runs internally
(post-fix UI verification). Re-running it here catches regressions introduced
after the claim step (e.g., last-minute fixups or simplify-pass edits from
Step 1b).

If the gate fails, fix the regression and re-run Step 1b → 1c before
proceeding to Step 2.

## Step 2: Commit Code Changes

Every close-out commit this step writes (or amends) MUST carry a `Doc-Work: <TASK_ID>` git trailer on a final line of the commit message body, separated from the body prose by one blank line. The trailer is the deterministic marker `/sitrep` uses to classify the branch as "doc-work done" without re-scanning subject heuristics. If the work closes multiple task IDs (rare — a single commit landing both a `FEAT-*` and a follow-up `TECH-*`), emit one `Doc-Work:` line per ID — git natively supports repeated trailer keys.

```
<type>: <title> (<TASK_ID>)

<optional body prose>

Doc-Work: <TASK_ID>
Co-Authored-By: ...
```

**All trailers share one trailing paragraph — no blank line between them.** `git interpret-trailers --parse` only inspects the last paragraph of the commit body; if `Doc-Work:` sits in a paragraph of its own above `Co-Authored-By:` (or vice versa), parsing silently drops whichever line isn't in the final paragraph and `/sitrep` will misclassify the commit as "in progress." When you invoke `git commit --trailer "Doc-Work: ..."` or `git commit --amend --trailer ...`, git handles the placement correctly; the hazard is only when the commit message is hand-written end-to-end.

If no `<TASK_ID>` can be derived from the branch (true adhoc work on `main` with no task entry), omit the trailer — `/sitrep` correctly classifies adhoc work as "not a task" via the absence of a lock and index entry.

**Trailer placement on existing commits.** If Step 2 enters with no uncommitted changes (the reviewer-executor in `/claim-task` Step 7 or another upstream step already committed), the most recent commit IS the close-out commit. Verify it carries `Doc-Work: <TASK_ID>` for the current branch's `<TASK_ID>` (resolved per the derivation rule below) by running:

```bash
git log -1 --format=%B | git interpret-trailers --parse | grep -q "^Doc-Work: <TASK_ID>$"
```

If the trailer is absent, **probe for an upstream first**:

```bash
git rev-parse --abbrev-ref --quiet '@{u}' >/dev/null 2>&1
```

- If the probe **fails** (no upstream — the normal `/claim-task` → `/document-work` → `/review-close` pipeline state, since the reviewer-executor in `/claim-task` Reviewer-Executor Prompt step 9 hard-constrains "Do NOT push"), amend the most recent commit to add the trailer: `git commit --amend --no-edit --trailer "Doc-Work: <TASK_ID>"`. Safe because the commit has not been pushed yet (the worktree branch has no upstream until `/review-close` Step 4a pushes it).
- If the probe **succeeds** (the branch already tracks a remote — e.g., `/document-work` invoked outside the claim-task pipeline on a pushed branch, or on `main` mid-direct-commit-flow), do **NOT** amend. Instead, write a fresh trailer-only commit so published history isn't rewritten: `git commit --allow-empty -m "chore: emit Doc-Work trailer (<TASK_ID>)" --trailer "Doc-Work: <TASK_ID>"`. `/sitrep` finds the trailer on this commit and classifies the branch identically to an amended one.

This is the only Step-2 path that could use `--amend`, and the probe-then-branch shape hardens the no-upstream-yet pipeline invariant into a check that catches `/document-work` invocations outside the orchestrated flow before they can rewrite pushed history.

**If invoked with `--non-interactive`** (Phase 6e execution agent): if there are uncommitted changes, stage tracked changes via `git add` (never add `.env`, credentials, or secrets) and commit with a derived message + trailer. Derive `<TASK_ID>` by matching the current branch name (`git branch --show-current`) against `tasks[].branch` first, then by lowercase-mapping the branch suffix back to a task ID (e.g., `tech/tech-foo` → `TECH-FOO`). Format: `<type>: <title> (<TASK_ID>)` for the subject, with `<type>` chosen from the ID prefix per Step 3's type table (FEAT → feat, TECH → tech, BUG → fix, etc.), and `Doc-Work: <TASK_ID>` as the final trailer line. If there are no uncommitted changes, apply the trailer-placement rule above to the most recent commit.

**Interactive invocation (default):** if there are uncommitted changes (staged or unstaged):

1. Show the user a summary of what will be committed
2. Stage all tracked changes and relevant untracked files (`git add` specific files — never add `.env`, credentials, or secrets)
3. Ask the user for a brief description of what was done if the changes aren't self-evident from context
4. Derive `<TASK_ID>` from the current branch using the same resolution as `--non-interactive` (match `tasks[].branch` first, then lowercase-segment mapping). If a `<TASK_ID>` resolves, commit with a conventional message (`fix:`, `feat:`, `refactor:`, `docs:`, `test:`, etc.) AND a `Doc-Work: <TASK_ID>` trailer on the final line. If no `<TASK_ID>` resolves (adhoc on `main`), omit the trailer.

If there are no uncommitted changes, apply the trailer-placement rule above to the most recent commit.

## Step 3: Write Pending Documentation

Instead of modifying shared documentation files directly (which causes merge conflicts when parallel branches merge), write a structured file to `.pending-docs/`. The `/review-close` skill will consolidate these into the shared docs after merging.

1. Create the `.pending-docs/` directory if it doesn't exist: `mkdir -p .pending-docs`
2. Sanitize the branch name for the filename (replace `/` with `-`)
3. Write `.pending-docs/<sanitized-branch-name>.md` with YAML frontmatter:

```yaml
---
branch: <branch-name>
date: <YYYY-MM-DD>
type: <feature|bugfix|ui-iteration|infrastructure|adhoc>
roadmap_ids: [<FEAT-NNNN | TECH-NNNN | BUG-NNNN>, ...]
review_task_ids: [<TASK-NNNN>, ...]
summary: <one-sentence description of the work, including key files affected>
---
```

**Two ID namespaces — each independently optional.** `roadmap_ids` and `review_task_ids` capture distinct lifecycles and have different consumers; either or both may be `[]`.

- **`roadmap_ids`** — IDs that live in `tasks/index.yml` (typically `FEAT-NNNN`, `TECH-NNNN`, `BUG-NNNN`). Consumed by `/review-close` Step 4c: each ID is round-tripped through `yaml.safe_load` to flip `status: done`, and its body file is `git mv`'d from `open/` (or `deferred/`) to `archive/`. An ID that doesn't match an entry in `tasks/index.yml` is silently skipped — so misclassifying review-task IDs here makes them invisible.
- **`review_task_ids`** — IDs that live in `review_tasks.md` (typically `TASK-NNNN` from `/codebase-review` or `/security-audit`). **Documentary only** — never consulted programmatically by `/review-close`. Their actual closure happens in `/review-close` Step 4b via `bash sysop/scripts/close_batch.sh`, which reads `review_tasks.md` directly. The field exists so the PROJECT_STATUS entry can mention which review-queue tasks the work touched, and so a human reader can grep for the ID later.

If the work closes both kinds of IDs (e.g., a feature that also resolves a review-queue task), populate both. If it closes neither (an adhoc commit), both stay `[]`.

**Type selection** — set the type explicitly based on the intent of the work:

| Type | When to use |
|---|---|
| `feature` | New user-facing functionality, `FEAT-*` task |
| `bugfix` | Fixing broken behavior, `fix:` commits |
| `ui-iteration` | Visual/UX changes to existing components |
| `infrastructure` | `TECH-*`, `DATA-*`, `UX-*` tasks, tooling, pipeline |
| `adhoc` | One-off work, no task ID |

Set the type based on intent, not branch prefix — branch prefixes can mismatch.
If multiple types could apply, use the primary one.

**Do NOT** modify `PROJECT_STATUS.md`, `changelog.md`, `UI_Iterations.md`, `tasks/index.yml`, or `tasks/**/*.md` body files directly (with one exception, below). Status transitions on `tasks/index.yml` are owned by `/claim-task` and `/review-close`. **Filing a NEW follow-up task entry (id + body file under `tasks/open/`) IS allowed and is required when the work surfaces a follow-up that Step 3b would otherwise hard-fail on.**

<!-- Routing logic (which shared docs to update based on type) lives in /review-close Step 4c -->
<!-- Canonical process: WORKFLOW.md §2.4 (Documentation) -->

## Step 3b: Follow-up Task Stub Check (HARD FAIL)

The pending-docs body often names follow-up tasks like "filed as `TECH-FOO-BAR`" or "deferred to `BUG-BAZ`". Historically these were named in prose but no actual task stub was created — the follow-up rotted forever because `/next-task` never saw it.

Run this check on the just-written pending-docs file. The source of truth is `tasks/index.yml` (see `tasks/schema.md`). All ID resolution and whitelist lookups go through it via `python3 - <<'PY'` heredoc; never grep the file as text.

**Scope and skip conditions:**

- If `tasks/index.yml` does NOT exist at the project root (consumer hasn't run `install_tasks_scaffold` or deleted the file), log `Follow-up check: skipped (no tasks/index.yml)` and continue. The gate only protects projects that have opted into the `tasks/` system.
- If `tasks/index.yml` exists but has no entries under `tasks:` (or the file is empty), the discovered prefix set is empty and no tokens are scanned. Log `Follow-up check: 0 task IDs named (no prefixes in tasks/index.yml)` and continue.

**Algorithm:**

1. **Discover the prefix vocabulary dynamically** from `tasks/index.yml` — collect the leading `^[A-Z][A-Z0-9]*` segment of every `tasks[].id`. Sysop's vocabulary is consumer-extensible (Phase 23a established `roadmap_ids` for FEAT/TECH/BUG-style prefixes; consumers can add their own). Reading from the index keeps the gate framework-agnostic. The check has no opinion on which prefixes a project uses — it only enforces that named tokens matching those prefixes resolve. **Known limitation:** a pending-doc that mentions a token with a prefix NOT yet present in the index (e.g., the very first `BUG-*` mentioned before any `BUG-*` task is filed) slips through unchecked. Once at least one task with that prefix is filed, all future mentions are gated. This is intentional — the gate cannot distinguish a typo from a genuinely novel prefix without an explicit allow-list, and the workflow encourages "file the stub first" anyway.
2. **Token scan** the pending-docs body (after splitting YAML frontmatter) for `\b(?:<prefix1>|<prefix2>|...)-[A-Z0-9][A-Z0-9-]+\b` using the prefix set from step 1. Strip duplicates. Preserve 1-based line numbers (in the body, not the full file) for the error message.
3. **Build the resolution set** from `tasks/index.yml`:
   - Parse with `yaml.safe_load` (never `yaml.load` / `yaml.full_load`).
   - Treat every value of `tasks[].id` as a known task ID. Match is case-sensitive on the token itself.
4. **Build the bypass set:**
   - **Parent task IDs** — read `roadmap_ids:` from the pending-docs frontmatter (the Phase 23a-renamed field; see Step 3 for namespace semantics). Every ID listed there is a parent (the heading the work is documented under) and is subtracted from the check.
   - **Pending-docs `whitelist:` frontmatter** — read the optional `whitelist:` list from the same frontmatter. IDs there are skipped (used when the body intentionally mentions external/non-task IDs).
   - **Per-task `whitelist:` in `tasks/index.yml`** — for each parent task ID, look up its entry in `tasks/index.yml` and union its `whitelist:` list (if present) into the bypass set. The field is defined in `tasks/schema.md` and may be absent on most tasks — treat missing as `[]`.
5. **For each grepped token, fail if it is NOT in the resolution set AND NOT in the bypass set.** If any such tokens remain, HARD FAIL with this message, listing each missing token with its line number:
   ```
   /document-work: blocked. Pending docs name follow-up task IDs that aren't filed in tasks/index.yml:
     - TECH-FOO-BAR (line N of pending-docs body)
     - BUG-BAZ (line M of pending-docs body)

   File a stub for each in tasks/index.yml + tasks/open/<TASK-ID>.md (per tasks/schema.md),
   then re-run /document-work.

   Stub minimum: an entry in tasks/index.yml (id, title, phase, status: open, effort, user_action,
   depends_on: [], surfaced_by: [<parent task id>], body: open/<TASK-ID>.md) plus a body file under
   tasks/open/ whose first heading is `# <TASK-ID>`. Cross-reference from the parent task's body if
   appropriate.
   ```
   Do NOT proceed to Step 4. Block until the user files the stubs.
6. If all tokens resolve (either in `tasks/index.yml` or via the bypass set), log `Follow-up check: <N> task IDs named, all resolved` and continue.

**Reference implementation** (copy-pasteable; run from repo root after writing the pending-docs file):

```bash
# `python3` command word (not `.venv/bin/python3`, no PATH prefix, no `&&` compound) so
# the allow-rule `Bash(python3 -:*)` matches as a single simple command. PyYAML — which
# this heredoc imports — is resolved for venv-only consumers by the bootstrap below; the
# pending-docs path (formerly a shell $PENDING assignment) is computed in-process too, so
# the whole block is one command (BeanRider ISSUE-0049; Sysop Phase 126).
python3 - <<'PY'
import os, re, sys, subprocess
try:
    import yaml
except ImportError:  # PyYAML lives only in the project venv (BeanRider ISSUE-0049)
    import glob
    sys.path[:0] = glob.glob(".venv/lib/python*/site-packages")
    try:
        import yaml
    except ImportError:
        print("ERROR: Step 3b requires PyYAML. Install: pip install pyyaml", file=sys.stderr)
        sys.exit(2)

branch = subprocess.check_output(["git", "branch", "--show-current"], text=True).strip()
pending_path = f".pending-docs/{branch.replace('/', '-')}.md"
with open(pending_path) as f:
    raw = f.read()

# Split YAML frontmatter from body
fm = {}
body = raw
if raw.startswith("---\n"):
    end = raw.find("\n---\n", 4)
    if end != -1:
        fm = yaml.safe_load(raw[4:end]) or {}
        body = raw[end + 5 :]

# Skip if no tasks/ system
if not os.path.exists("tasks/index.yml"):
    print("Follow-up check: skipped (no tasks/index.yml)")
    sys.exit(0)

with open("tasks/index.yml") as f:
    idx = yaml.safe_load(f) or {}
tasks_by_id = {t["id"]: t for t in (idx.get("tasks") or []) if isinstance(t, dict) and t.get("id")}
known_ids = set(tasks_by_id)

# 1. Dynamic prefix discovery
prefix_re = re.compile(r"^[A-Z][A-Z0-9]*")
prefixes = set()
for tid in known_ids:
    m = prefix_re.match(tid)
    if m:
        prefixes.add(m.group(0))

if not prefixes:
    print("Follow-up check: 0 task IDs named (no prefixes in tasks/index.yml)")
    sys.exit(0)

# 2. Token scan with line numbers
token_re = re.compile(
    r"\b(?:" + "|".join(sorted(prefixes)) + r")-[A-Z0-9][A-Z0-9-]+\b"
)
found = {}  # id -> first line number (1-based, in body)
for i, line in enumerate(body.splitlines(), start=1):
    for m in token_re.finditer(line):
        found.setdefault(m.group(0), i)

# 3+4. Bypass set: parent roadmap_ids, frontmatter whitelist, per-parent whitelist
bypass = set()
parents = fm.get("roadmap_ids") or []
bypass.update(parents)
bypass.update(fm.get("whitelist") or [])
for parent in parents:
    task = tasks_by_id.get(parent)
    if task:
        bypass.update(task.get("whitelist") or [])

# 5. Missing = found - bypass - known
missing = [(tok, ln) for tok, ln in found.items() if tok not in bypass and tok not in known_ids]
if missing:
    print(
        "/document-work: blocked. Pending docs name follow-up task IDs "
        "that aren't filed in tasks/index.yml:"
    )
    for tok, ln in missing:
        print(f"  - {tok} (line {ln} of pending-docs body)")
    print(
        "\nFile a stub for each in tasks/index.yml + tasks/open/<TASK-ID>.md "
        "(per tasks/schema.md),\nthen re-run /document-work."
    )
    sys.exit(1)

print(f"Follow-up check: {len(found)} task IDs named, all resolved")
PY
```

A non-zero exit is the hard-fail; block Step 4 until the consumer files the missing stubs (or bypasses them via one of the two whitelist paths below).

**Why this gate:** prevents the recurring drift where pending-docs prose claims "filed as TECH-X" but TECH-X never makes it into `tasks/index.yml`. The failure mode is invisible without the gate — the close-out commit lands clean, the follow-up disappears into prose, and `/next-task` never surfaces it.

**Allowed bypass paths** — if a token is genuinely not a follow-up (e.g., the work documents an external system that happens to use this naming, or a permanent non-task prefix that shares a prefix with the project's vocabulary), pick one:

- **One-off, branch-local:** add the token to a `whitelist:` field in the pending-docs frontmatter:
  ```yaml
  whitelist: [SOME-EXTERNAL-ID]   # not a roadmap task — see context
  ```
- **Persistent, parent-task-scoped:** add the token to the parent task's `whitelist:` list in `tasks/index.yml` (the field is defined in `tasks/schema.md` line 60 + invariant 6). Use this when the same external reference will keep showing up across multiple documentation passes for that task.

Both bypass paths are visible in code review and intentional. `review_task_ids:` (`TASK-NNNN` from `review_tasks.md`) are NOT bypassed via this mechanism — review-task IDs use a prefix that doesn't appear in `tasks/index.yml`, so the dynamic prefix discovery naturally excludes them.

**Non-interactive callers** (e.g., a future `/auto-build`-style orchestrator) treat the hard-fail identically: block close-out until stubs are filed.

## Step 4: Verify Pending Docs

**If invoked with `--non-interactive`** (Phase 6e execution agent): skip this step's human-confirm prompt entirely. The orchestrator + reviewer pair gated the work; the human reads the pending-docs body after the agent returns. Verify the file exists, print its contents to stdout (so the parent's transcript captures them), and proceed to Step 5.

**Interactive invocation (default):** the pending docs file is untracked (gitignored). No docs commit is needed.

1. Verify `.pending-docs/<sanitized-branch-name>.md` exists
2. Display its full contents to the user for review
3. Confirm the proposed entries look correct before proceeding

## Step 5: Prepare for Review

**If invoked with `--non-interactive`** (Phase 6e execution agent): do NOT push regardless of branch state. The orchestrator-driven flow defers all pushes to `/review-close`, which the human runs after walking through the final report. Note the number of unpushed commits: `git rev-list --count origin/main..HEAD`. Proceed to Step 6.

**Interactive invocation (default):**

**If on a feature branch:**
1. Assert you are not on `main` before pushing `HEAD` — a concurrent actor moving `HEAD` onto `main` would otherwise make this push land on `main` (`/review-close` owns `main`, never this skill). This is the inverted form of `_shared/main-push-guard.md` Rule A:
   ```bash
   test "$(git rev-parse --abbrev-ref HEAD)" != "main" || {
     echo "HEAD is main — Step 5 pushes a feature branch; /review-close owns main. STOP."; exit 1; }
   ```
2. Push the branch: `git push -u origin HEAD`

**If on `main`:**
1. Do NOT push — that's `/review-close`'s job
2. Note the number of unpushed commits: `git rev-list --count origin/main..HEAD`

## Step 6: Confirm

Report to the user:

```
Work committed and ready for review.

Code commit:    <hash> <message>
Branch:         <branch name>
Pending docs:   .pending-docs/<sanitized-branch-name>.md
Type:           <type>
Roadmap IDs:    <roadmap_ids or "none">       (consumed by /review-close Step 4c)
Review tasks:   <review_task_ids or "none">   (documentary only)
Summary:        <summary text>
```

End with: "Start a fresh session (`/clear`, or a new terminal), then run `/review-close` to merge, consolidate docs, and push. `/review-close` is designed context-independent — it reconstructs from the committed branch, the `## Test decision` records, and `.pending-docs/` — so a clean session reviews this branch (and any others awaiting close) even-handedly, without this implementation session's context biasing the merge gate with the implementer's own rationalizations."
