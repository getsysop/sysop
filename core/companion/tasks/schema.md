# Tasks Schema

This document specifies the schema for `tasks/index.yml` and the per-task `.md` body files. It replaces the format-rules section that used to live at the top of a single-file `product_roadmap.md`.

`sysop/scripts/validate_tasks.py` enforces every invariant in this document. If something is documented here but not validated, that's a bug — file it.

## File layout

```
tasks/
  index.yml                     # source of truth for status & metadata
  schema.md                     # this file
  README.md                     # orientation for humans
  open/
    <TASK-ID>.md                # body for tasks with status: open | in_progress
  deferred/
    <TASK-ID>.md                # body for tasks with status: deferred
  archive/
    <TASK-ID>.md                # body for tasks with status: done (if the task had real prose)
    _phase_<N>.md               # summary for a fully-completed phase (no per-task bodies)
```

The three-subdir shape (`open/`, `deferred/`, `archive/`) is the Sysop default — `install.sh` scaffolds it on fresh install. A flat `tasks/` layout is also valid: the validator's path-containment check (`realpath` resolves under `tasks/`) accepts any layout where `body:` paths stay under the `tasks/` base.

## `index.yml` top-level structure

```yaml
schema_version: 1

phases:
  - number: <int>               # 1-based phase number
    title: "<string>"
    status: <done | in_progress | planned>
    current_focus: <bool>       # exactly one phase must have this true
    sprint_note: |              # optional; multi-line prose context for the phase
      ...

tasks:
  - id: <TASK-ID>
    ...
```

## Task entry — fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | `^[A-Z][A-Z0-9-]{2,80}$`. Examples: `FEAT-FOO`, `TECH-BAR-BAZ`, `FIX-XYZ-123`. Used as filename for the body. Must be unique across the file. |
| `title` | string | yes | Short human-readable title. |
| `phase` | int | yes | Must match an entry in `phases[].number`. |
| `section` | string | no | Legacy section number from a pre-migration `product_roadmap.md` (e.g., `"6.88"`). Preserved for historical reference only; do not introduce on new tasks. |
| `status` | enum | yes | One of `open \| in_progress \| done \| deferred`. |
| `effort` | enum | yes (open/in_progress) | One of `Low \| Medium \| High`. Captures **how much work**. |
| `blast_radius` | enum | yes (open/in_progress) at `schema_version >= 2`; optional at v1 | One of `single-file \| single-module \| cross-module \| architectural`. Captures **surface area** — independent of effort. See "Blast radius" below for definitions. Validator enforces enum membership whenever the field is present, regardless of schema version. |
| `user_action` | bool | yes (open/in_progress) | `true` if the task requires console access, manual credential setup, domain registration, etc. `false` if fully agent-executable. |
| `depends_on` | list[TASK-ID] | yes (default `[]`) | Every ID listed must resolve to another task in this file. |
| `surfaced_by` | list[TASK-ID] | yes (default `[]`) | Cross-references: task IDs that filed this one (e.g., a review-discovered follow-up). Every ID must resolve. One non-ID value is allowed: the literal sentinel `imported`, marking a task brought in from a pre-Sysop backlog (a roadmap file or issue tracker) by `/onboard` — its `effort`/`blast_radius` are archaeological estimates; `/auto-build` re-estimates them from the body before its batch math trusts them. |
| `branch` | string | no | Suggested git branch name (e.g., `feat/foo-bar`). |
| `body` | path | yes (open/in_progress/deferred) | Path to the per-task body file. Must exist and resolve (via `realpath`) under the `tasks/` base directory. **Canonical shape:** `open/<TASK-ID>.md` — relative to `tasks/`, without the `tasks/` prefix (e.g. `open/FEAT-0001.md`, NOT `tasks/open/FEAT-0001.md`). The validator and `/review-close` Step 4c's segment-based rename also accept the `tasks/`-prefixed shape for backward compatibility with hand-migrated indexes — both shapes round-trip safely through the workflow. |
| `on_hold_until` | string \| null | no | Free-form reason or date (e.g., `"Stripe API v2 GA"`). When non-null, `/next-task` skips this task. |
| `whitelist` | list[TASK-ID] | no | Task IDs whose mention in the body should NOT trigger the `/document-work` follow-up-stub check. Mirrors the existing `whitelist:` frontmatter bypass. |
| `manual_smoke` | bool | no | `true` when this task requires a documented pre-merge manual smoke (UI flow, side-effect-bearing command, LLM round-trip) that automated verification can't cover. `/review-close` Step 3c halts and prompts the human before Step 4. The procedure text lives in the task body under a heading matching `manual smoke` / `smoke required` (case-insensitive). See "Manual smoke" below. |
| `archive_summary` | path | yes (done, no per-task body) | When a `done` task has no per-task `.md` (collapsed phase summary), this points at `tasks/archive/_phase_<N>.md`. |
| `completed_date` | string (ISO date) | yes (done) | `YYYY-MM-DD`. Used by daily-summary tooling. |

### Status-specific requirements

| Status | Requires `body` | Requires `archive_summary` | Requires `completed_date` | Requires lock file |
|---|---|---|---|---|
| `open` | yes | no | no | no |
| `in_progress` | yes | no | no | yes (`<main-repo-root>/sysop/runtime/locks/<TASK-ID>.lock`) |
| `done` | no (use `archive_summary` if no body) | yes if no `body` | yes | no |
| `deferred` | yes | no | no | no |

**Directory convention** (validator-enforced for `done` since ISSUE-0009, 2026-05-14): a `done` task's `body:` MUST NOT live under `open/` or `deferred/`. `/review-close` Step 4c moves the body to `archive/` via `git mv` as part of the status flip; if that rename silently no-ops (e.g., a stale prefix assumption in the rename heredoc), the validator catches the half-migrated state on the final-guard run and fails the close. Accepts bodies under `archive/` (canonical for `done`) or at the root of `tasks/` (flat-layout consumers). A `done` task with `body: archive/_phase_<N>.md` (collapsed phase summary) is also valid — that path is normally written via `archive_summary:` instead of `body:`, but either field placement passes.

### Blast radius

`blast_radius:` captures the **surface area** of a task — how much surrounding code gets pulled in — as a signal independent of `effort:` (which captures *amount of work*). Two `effort: Medium` tasks can be very different shapes: one touches a single file, one touches a shared schema.

| Value | When to use |
|---|---|
| `single-file` | Touches one file, or one file plus its test. Almost never collides with other in-flight work. |
| `single-module` | Touches one cohesive module/directory. Low collision risk unless two batched tasks target the same module. |
| `cross-module` | Touches multiple modules or crosses a layer boundary. Moderate collision risk. |
| `architectural` | Touches shared infrastructure, schemas, build config, or wide-reaching abstractions. High collision risk; usually wants to run alone. |

Author-assigned at task creation alongside `effort:`. The same calibration approach applies: it's a judgment call that gets sharper with practice. Standalone uses include at-a-glance triage when scanning `index.yml`; downstream uses (e.g., a parallel-orchestrator skill for batched concurrent work) treat `blast_radius` as a first-class batch-sizing signal.

At `schema_version: 1`, `blast_radius` is **optional** (validator accepts absence; if present, enum membership is enforced — typos still get caught). At `schema_version: 2`, `blast_radius` is **required on `status in {open, in_progress}`** (mirrors `effort:`'s required-status set; the validator does not retroactively require backfill on legacy `done` tasks, same accommodation as `completed_date`).

### Manual smoke

Some features can't be fully verified by automated tests — UI flows that need a browser, commands with external side effects, LLM round-trips whose output a human must eyeball. `manual_smoke: true` declares that this task's `/review-close` cycle must halt before merge so the human can run, confirm, or waive the procedure.

**Where the procedure lives.** Author the smoke steps in the task body file (`tasks/open/<TASK-ID>.md`) under a heading whose text contains `manual smoke` or `smoke required` (case-insensitive — `## Manual smoke required`, `### Manual smoke`, `## Smoke required before review-close` all match). `/review-close` Step 3c also scans `sysop/runtime/pending-docs/*.md` bodies for the same pattern, so a hotfix branch with no `tasks/index.yml` entry can still declare a smoke by including the heading in its pending-doc.

**Validator behavior** (warn-only): when `manual_smoke: true`, the validator warns (does NOT block) if the body file lacks a smoke-matching heading. This keeps task authoring fluid — a stub task can be filed with `manual_smoke: true` before the procedure is fully written, and the validator surfaces the gap without halting commits. The actual merge-gate lives in `/review-close` Step 3c.

**Skill behavior** (`/review-close` Step 3c, Phase 35, 2026-05-22): scans `sysop/runtime/pending-docs/*.md` bodies AND cross-checks `tasks/index.yml` for any task whose ID appears in a pending-doc's `roadmap_ids:` frontmatter AND carries `manual_smoke: true`. Either signal fires the gate. For each signal the skill calls `AskUserQuestion` with three options: (a) agent drives the smoke end-to-end via available MCP tools; (b) human confirms they already ran it; (c) skip with waiver (logged in Step 8 report). Waivers don't block merge; agent-drive failures do.

Field is purely optional. Tasks without `manual_smoke:` and pending-docs without the heading proceed through Step 3c without any prompt.

### Test decision

Every claimed task records a **test decision** in its body — the plan-time answer to "how do we know this works?" Authored during `/claim-task` planning (Step 6) and persisted to the durable body so `/review-close` (Phase 59) can read it back at close time. It takes one of two forms:

- **`test <X> proves <Y>`** — names the regression test (existing or new) that exercises the behavior this task changes, and the invariant it pins.
- **`no test because <Z>`** — the explicit, reviewable rationale when no automated test is added (pure rename/move, config-only change, docs, a path an existing named test already covers, or a behavior that can only be confirmed by `manual_smoke:`).

**Where it lives.** A heading whose text contains `test decision` (case-insensitive — `## Test decision`, `### Test Decision` both match) in the task body file (`tasks/open/<TASK-ID>.md`).

**Validator behavior** (warn-only): for `status: in_progress` tasks, the validator warns (does NOT block) if the body lacks a test-decision heading. It fires only on `in_progress` because the decision is a claim-time artifact — `open` backlog predates planning, and `done`/`deferred` are terminal or parked. Warn-not-block keeps authoring fluid; the read-and-verify gate lives in `/review-close` (Phase 59).

This is the **plan-time recording** half of Sysop's test discipline; the adversarial plan reviewer's "Missing invariant tests" dimension (`_shared/adversarial-review.md` finding #7) is the **review-time scrutiny** half — it judges whether a recorded `no test because Z` rationale is *sound*, rather than flagging the mere absence of a test. They are complementary, not redundant: the author records the decision here; the reviewer judges the recorded rationale.

## Phase entry — fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `number` | int | yes | Unique across phases. |
| `title` | string | yes | |
| `status` | enum | yes | `done \| in_progress \| planned`. |
| `current_focus` | bool | yes | **Exactly one** phase must have `current_focus: true`. `/next-task` anchors on it. |
| `sprint_note` | string \| null | no | Multi-line block scalar with sprint context, narrative, dated notes. Replaces the freeform blockquotes that used to float above the in-progress phase in a single-file roadmap. |

## Per-task body (`tasks/open/<TASK-ID>.md`, `tasks/deferred/<TASK-ID>.md`)

The body holds prose only. Metadata lives exclusively in `index.yml` — do not duplicate it as frontmatter. The body's first heading must be `# <TASK-ID>` (validator-enforced).

Conventional section layout:

```markdown
# FEAT-EXAMPLE

## Context
<problem, motivation, why this matters now>

## Requirements
1. <numbered list>
2. ...

## Key files
- `<module>/...`
- `<frontend>/...`

## Test decision
<recorded at /claim-task plan time — "test <X> proves <Y>" or "no test because <Z>". See "Test decision" below.>

## User ops (do these first)
<only present when index.yml has user_action: true>

## Surfaced by
<optional prose narrative — formal cross-references live in index.yml surfaced_by:>
```

## Invariants (validator-enforced)

1. **YAML parses** with `yaml.safe_load` (never `yaml.load` or `yaml.full_load`).
2. **`schema_version`** is a known value (currently `>= 1`; see "Versioning" below).
3. **`body:` paths exist** AND resolve under `tasks/` via `os.path.realpath()`. Rejects `body: tasks/../etc/passwd`.
4. **No orphan files** — every file under `tasks/open/`, `tasks/deferred/`, `tasks/archive/` corresponds to an entry in `index.yml`.
5. **Exactly one phase** has `current_focus: true`. Not zero, not two.
6. **Reference integrity** — every ID in any `depends_on:`, `surfaced_by:`, or `whitelist:` resolves to a known task ID (or for `whitelist:`, to a permanent external prefix like `BATCH-*`; or for `surfaced_by:`, the literal `imported` provenance sentinel).
7. **Unique IDs** — no duplicates across phases.
8. **Valid status values** — exactly one of `open | in_progress | done | deferred`.
9. **`in_progress` requires a lock** — `<main-repo-root>/sysop/runtime/locks/<TASK-ID>.lock` must exist. The lock lives under the **main** repo root (resolved via `git rev-parse --git-common-dir`) so a single canonical location is visible from any worktree (Phase 32, 2026-05-22 — closes BeanRider ISSUE-0028 / 0030 / 0032 / 0013). `claim_task.sh --lock` writes the lock there regardless of cwd; the validator resolves the same path. Catches stale state where `/claim-task` was invoked without `--lock` or the lock was hand-deleted.
10. **Status-field consistency** — `done` requires `completed_date`; `done` without `body` requires `archive_summary`; `done` with `body` rejects `open/` or `deferred/` path segments (catches the silent half-migration from ISSUE-0009 when Step 4c's status flip wrote but the rename skipped); `blast_radius` is required on `open`/`in_progress` at `schema_version >= 2`, and its enum is enforced whenever the field is present at any version; etc. (See tables above.)
11. **Secret-pattern scan** — warn (not block) on long hex strings, `sk-`-prefixed tokens, AWS-style access keys in any `tasks/**/*.md` body. False-positive prone, so non-blocking.
12. **Manual-smoke documentation (warn-only)** — when `manual_smoke: true`, the body should contain a heading whose text matches `manual\s+smoke|smoke\s+required` (case-insensitive). Warn-not-block: keeps task authoring fluid; the actual merge gate lives in `/review-close` Step 3c (Phase 35, 2026-05-22).
13. **Test-decision recording (warn-only)** — an `in_progress` task's body should contain a heading whose text matches `test\s+decision` (case-insensitive). Warn-not-block: the decision is recorded at `/claim-task` plan time and verified at `/review-close` (Phase 59); the validator is a backstop, never a merge gate. Fires only on `in_progress` (`open` predates planning; `done`/`deferred` are terminal or parked). See "Test decision" above (Phase 58b, 2026-06-17).

## Versioning

Sysop's validator accepts `schema_version >= 1` (forward-compatible): a consumer pinned to an older Sysop that adopts a newer `tasks/index.yml` from upstream will NOT be rejected as "unknown version" for purely-additive schema changes.

**Current supported versions:**

| Version | Status | Differences from prior |
|---|---|---|
| `1` | Original (Phase 16). `blast_radius` is optional; if present, enum is enforced. | — |
| `2` | Phase 19 (2026-05-14). `blast_radius` is **required** on `status in {open, in_progress}`. Otherwise identical to v1; consumers opt in by backfilling and bumping their `schema_version`. | Adds `blast_radius` requirement on active statuses only — `done`/`deferred` tasks may omit it without error. |

The starter `index.yml` shipped by `install.sh` stays at `schema_version: 1` until a future phase decides v2 has enough field experience to be the default. A consumer opts in to v2 by:

1. Backfilling `blast_radius` on every `open`/`in_progress` task in their `index.yml`.
2. Bumping `schema_version: 1 → 2` in their `index.yml`.
3. Confirming `python3 sysop/scripts/validate_tasks.py` exits 0.

A future **breaking** schema change bumps to `3` AND requires a new per-version code path in the validator. Until that happens, new fields land as forward-compatible additions following the same v1-optional / vN-required pattern Phase 19 used.

## What NOT to put here

- Hand-edits to `index.yml` — go through the skills (`/intake`, `/onboard`, `/add-task` to add tasks; `/claim-task`, `/document-work`, `/review-close` to advance status).
- Metadata duplicated in per-task `.md` frontmatter. Index is the only place.
- Status changes that bypass the lock file (in-progress tasks must have a lock).
- Inline prose for completed work (use `tasks/archive/_phase_<N>.md` for collapsed phase summaries).
