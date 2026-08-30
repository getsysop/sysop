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
| `title` | string | yes | Short human-readable title. **Quote every `title:` you write** — `title: "<the title>"`. Unquoted, YAML reads ` #` (space then hash) as the start of a comment, so `title: Fix the widget #define` lands on disk as `Fix the widget` the first time anything reads the file, and the validator stays green because what survives is still a legal title. Entry shape: `tasks/README.md` § *Authoring an entry by hand*. |
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
| `solo` | bool | no | `true` when the task mutates state shared **outside** the filesystem view — a global lockfile, a singleton registry, a live schema, a shared fixture corpus — so it must not run concurrently with anything, even a task whose paths are disjoint. `/auto-build` Step 2 solo invariant `d.` batches it alone. Independent of `blast_radius`, which grades surface area. See "Solo" below. |
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

**Where the procedure lives.** Author the smoke steps in the task body file (`tasks/open/<TASK-ID>.md`) under a heading whose text contains any of `manual smoke`, `smoke required`, `smoke test`, `manual verification` / `manual verify` / `manual test` / `manual check` / `manual step`, `operator action`, `human action`, `requires a human`, `before merge` / `before merging`, or `prior to merge` (case-insensitive — `## Manual smoke required`, `### Manual smoke`, `## Smoke required before review-close`, `## OPERATOR ACTION REQUIRED BEFORE MERGE` all match). `/review-close` Step 3c also scans `sysop/runtime/pending-docs/*.md` bodies for the same pattern, so a hotfix branch with no `tasks/index.yml` entry can still declare a smoke by including the heading in its pending-doc.

> **The phrase list was widened in Phase 218 and is still a phrase list.** The original two phrases scored a procedure headed `OPERATOR ACTION REQUIRED BEFORE MERGE` as *no smoke needed*, and the close proceeded without ever prompting — the one gate whose miss is a human never being asked. Do not rely on the list: **the structural declarations below are heading-independent and cannot be missed by phrasing.** `## User ops (do these first)` is deliberately *not* in the list, and see "User ops" below for why: those steps gate the *work*, so by close time they are already done, and `user_action: true` is a large routine class that would train the operator to waive wholesale. A step that must happen before *merge* is `manual_smoke:`, not that heading.

**The heading-independent declarations** (Phase 218). Two ways to declare a smoke that no phrase list can miss:

1. **`manual_smoke: true` in a pending-doc's frontmatter** — signals on its own, whatever the doc's headings say. This is the structural form of the hotfix escape above.
2. **`manual_smoke: true` on the `tasks/index.yml` entry** — signals whenever this close covers the task, and it now signals **even when the body carries no matching heading**, no readable `body:`, or no `body:` at all. A declaration is the ask; a missing procedure makes the ask louder, not absent.

**Validator behavior** (warn-only): when `manual_smoke: true`, the validator warns (does NOT block) if the body file lacks a smoke-matching heading. This keeps task authoring fluid — a stub task can be filed with `manual_smoke: true` before the procedure is fully written, and the validator surfaces the gap without halting commits. The actual merge-gate lives in `/review-close` Step 3c.

**Skill behavior** (`/review-close` Step 3c, Phase 35, 2026-05-22; widened Phase 218): scans `sysop/runtime/pending-docs/*.md` bodies for a matching heading, honours a pending-doc's own `manual_smoke: true` frontmatter, AND cross-checks `tasks/index.yml` for any task carrying `manual_smoke: true` that this close covers. **Task linkage has two sources, because pending-doc frontmatter alone was not one:** a task ID named in a pending-doc's `roadmap_ids:` (or legacy `task_ids:`), **or** a lock under `sysop/runtime/locks/` whose `branch:` is one of this run's approved branches. Before Phase 218 only the first existed, so a task that declared `manual_smoke: true` and authored its procedure under the sanctioned heading was still scored `NO_SMOKE_REQUIRED` when no pending doc named it — the fully compliant author was the one the gate did not protect. Any signal fires the gate. For each signal the skill calls `AskUserQuestion` with three options: (a) agent drives the smoke end-to-end via available MCP tools; (b) human confirms they already ran it; (c) skip with waiver (logged in Step 8 report). Waivers don't block merge; agent-drive failures do.

Field is purely optional. Tasks without `manual_smoke:` and pending-docs without the heading proceed through Step 3c without any prompt.

### Plan

**Optional, and written by exactly one thing:** `/claim-task` option C, the plan-only path. A task that has never been claimed under option C has no `## Plan` section, and that is the ordinary case — most tasks never take that path.

**What it holds.** The reviewed plan verbatim, followed by the sealed `REVIEW_REPORT:` block that passed it. Not a trailer line naming the verdict: option C is the one path with no implementation, so the adversarial review *is* the deliverable, and discarding it would reproduce the defect the orchestrator exists to remove — a review that ran and left nothing durable.

**Where it lives, and how that differs from `## Test decision`.** In the **main checkout's** body file, committed on `main`. This is the opposite of the sibling section below, and the difference is derived rather than stylistic: `/claim-task` Step 2 reads `tasks/open/<TASK-ID>.md` from the main checkout *before any worktree exists*, so a `## Plan` committed on a feature branch would be invisible to the very next claim — which is the entire thing option C exists to enable. Option C's write-back therefore carries `## Test decision` alongside it, on `main`, because that path has no executor to write it in the worktree later.

**Who reads it.** `/claim-task` Step 7a, as a **presence** test: a task whose body already carries a non-empty `## Plan` skips the planner. It does **not** skip the reviewer — the plan is re-reviewed against a `main` that has moved since it was written, which is both correct on its merits and the reason a forged marker buys its forger nothing. No gate reads the verdict inside the section.

**A second option-C run replaces the section in place** rather than appending, so a body never carries two plans and Step 7a can never read the stale one. The replaced content stays recoverable from git history.

**The validator does not check this, and will not.** There is no status at which a missing `## Plan` is wrong — option C is optional and most tasks never take it — so a warn-only invariant would fire on nearly every task in the queue rather than on a failure. That is the same defect, with more force, that retired the test-decision invariant in Phase 234 (see the note under "Invariants" below). If a check is ever wanted, the shape that works is `/review-close` Step 2d's: read the revision that actually has the record, not the filesystem.

**Roadmap tasks only.** A review batch has no per-task body file — its "body" is a `### Batch <N>` section inside the shared `review_tasks.md` — so option C is not offered on the batch path and `--plan-only` is rejected for a `BATCH-*` claim at `/claim-task` Step 1.

### Test decision

Every claimed task records a **test decision** in its body — the plan-time answer to "how do we know this works?" Decided by the planner at `/claim-task` Step 7a and written to the durable body by the Step 7e executor during implementation, so `/review-close` (Phase 59) can read it back at close time. (On the plan-only path there is no executor, so option C's write-back carries this section too — see "Plan" above.) It takes one of two forms:

- **`test <X> proves <Y>`** — names the regression test (existing or new) that exercises the behavior this task changes, and the invariant it pins.
- **`no test because <Z>`** — the explicit, reviewable rationale when no automated test is added (pure rename/move, config-only change, docs, a path an existing named test already covers, or a behavior that can only be confirmed by `manual_smoke:`).

**Where it lives.** A heading whose text contains `test decision` (case-insensitive — `## Test decision`, `### Test Decision` both match) in the task body file (`tasks/open/<TASK-ID>.md`).

**Where it is enforced.** `/review-close` Step 2d, and nowhere else. That gate reads the body **at the branch tip** (`git show "<branch>:<path>"`), classifies the record, and blocks on a discrepancy — with a per-task doc-only skip so a docs branch carrying a `no test because Z` is not held up.

**The validator does not check this** (Phase 234, Q-022). It did, warn-only, from Phase 58b: Invariant 13 warned when an `in_progress` body lacked the heading. But the validator reads the body off the **filesystem**, and the executor writes this section *inside the worktree*, so it is committed on the feature branch and nowhere else. Run from `main` — which is where both of its shipped callers run it — the section is absent for the entire `in_progress` window, so the warning fired on every claimed task on every validator run rather than on the tasks actually missing a record. A backstop that cannot distinguish the failure from the normal case is not a backstop, and it was diluting a channel that carries twelve invariants which can. Step 2d, which reads the revision that has the record, is the whole enforcement story.

This is the **plan-time recording** half of Sysop's test discipline; the adversarial plan reviewer's "Missing invariant tests" dimension (`_shared/adversarial-review.md` finding 7) is the **review-time scrutiny** half — it judges whether a recorded `no test because Z` rationale is *sound*, rather than flagging the mere absence of a test. They are complementary, not redundant: the author records the decision here; the reviewer judges the recorded rationale.

### User ops

`user_action: true` declares that some step of the task is **human-only** — console access, credential
provisioning, a domain registration, or private knowledge the agent cannot obtain. It is a *step*
property, not a task property: the flag fires when any gate step needs a human, even when the rest of the
task is fully agent-executable. See `_shared/decomposition-rubric.md` § 4 for the promotion-grade
definition and the canonical mis-flag (research-uncertainty dressed as a blocker).

**Where the steps live.** A `## User ops (do these first)` section in the task body
(`tasks/open/<TASK-ID>.md`). Written when `user_action: true`, and **kept after the flag is
cleared** — the section is the record of a step a human performed, which is worth more once it
has been performed, not less. **This sentence used to read "present only when `user_action:
true`"**, which made the schema and the clearing contradict each other: following it, a human who
finished the step had to delete the evidence that they had. That was half of `Q-314`.

**Clearing it — the flag is not set-once.** When the human step is done, clear the flag so the
task rejoins the agent-executable frontier:

```bash
python3 sysop/scripts/clear_user_action.py <TASK-ID>     # --dry-run to preview
```

**Until Phase 237 nothing did this**, and the consequence was permanent stranding: all three
frontier filters read `user_action` and no shipped writer ever cleared it, so a task stayed
excluded from every automated path forever after the human had unblocked it — while
`roadmap/SKILL.md`'s unblock-the-human-first ordering promised that "clearing it early converts a
serial stall into parallel progress" and nothing implemented a clearing. The only escape was a
hand edit the tree never instructed. **One field, not two:** a `user_action_done:` companion would
encode one fact as two booleans that must be kept in sync, and since this is a *step* property
rather than a task property, "done" is not even well defined for the non-prerequisite cases the
rubric lists (a go/no-go at a rollout boundary; a done-except-for-sign-off pairing). Clearing the
one field says the thing that is true: this task no longer needs a human before an agent can take
it.

**What the flag actually does — it gates *dispatch*.** Every reader of `user_action` is a
frontier filter over `status: open` tasks, and all three exclude the task from automated pickup:
`/auto-build` drops it from its executable frontier, `/roadmap` classes it 🔒 blocked-on-human and orders
on it, and `/next-task` keeps it out of the agent pool and surfaces it separately to the human who can
perform the step. That is the whole of the enforcement *on the dispatch side*.
**Nothing verifies the steps were performed** — `/claim-task` gates on `status` alone, so a
`user_action: true` task can be claimed and worked with the human step still outstanding.

**It can no longer be *closed* that way, which is the half Phase 241 changed (`Q-327`).** `/review-close`
Step 4c **step 1c** now reads this field, and holds the whole close for that task: a pending-doc naming
a task whose `user_action` is `true` is **held back in `sysop/runtime/pending-docs/`** and not routed at
all this run. Nothing is written for it — no `PROJECT_STATUS.md` / `CHANGELOG.md` / `UI_Iterations.md`
entry, no status flip, no body archive move, no lock or parked-marker cleanup. The task stays
`in_progress`, its body stays under `open/`, its lock stays held, **its feature branch is retained by a
HARD RULE in Step 6**, and Step 8 reports it under both `Held-back docs:` and `Remaining:`. It closes on
a later `/review-close`, after the human performs the step and clears the flag with
`python3 sysop/scripts/clear_user_action.py <TASK_ID>` — which is what that script has always been for.

**Why the WHOLE doc waits rather than just the status flip, because the narrower design is the one you
would reach for first.** It was built and it strands the task: Step 4c's step 6 deletes the pending-docs
that step consolidated, and the pending-doc is the only carrier of `roadmap_ids` into the round-trip — so
routing the doc consumes the carrier, and nothing can ever close the task. The cost of the wider hold is
real and worth stating: **a held task's documentation lags its merge**, visibly, on every run until the
human step is done. And a doc naming a held task and an unheld one holds **both** — the conservative
direction, because the alternative is routing half a doc and re-routing the rest later.
**Read the two paragraphs together:** dispatch is filtered, closure is held, and the gap that remains is
the middle — a task can still be *claimed and implemented* before its human step happens, which is
usually harmless and occasionally not (see the non-prerequisite cases below).

**When they run — usually first, and the heading says so, but that is a convention rather than a
guarantee.** The authoring surfaces (`/intake`, `/add-task`, the decomposition rubric) all write the
steps under "do these first", and the common cases are genuinely prerequisites: provisioning a
credential, standing up a connector, supplying private knowledge the agent cannot obtain. The rubric's
own list is not uniform, though — *"a go/no-go judgment at a rollout boundary"* and the `Low/architectural`
*"done-except-for-human-sign-off"* pairing both describe steps that are **not** prerequisites. So read
the heading as the common case, not as a property this schema enforces.

**Why the pre-merge smoke gate ignores this heading.** `/review-close` Step 3c deliberately excludes
`## User ops (do these first)` from its heading phrase list because `user_action: true` is a **large,
routine class**, and firing a halt on all of it would train the operator to waive wholesale. That reason
is timing-independent and is the whole of it. **A step that must happen before *merge* is `manual_smoke:`,
not this** — different field, different timing, and a task can legitimately carry both. If your step must
happen *after* the merge, note that Sysop currently has nowhere to declare that; do not reach for this
heading to express it.

> **This section exists because four shipped sites asserted the opposite** (Phase 235, `Q-235`).
> This file's § *Manual smoke* note, `/review-close` Step 3c's prose and its heredoc comment, and
> `validate_tasks.py`'s mirror comment all read *"that heading declares POST-merge operator steps"* —
> against the heading's own text and against all three authoring surfaces, and resting on no independent
> assertion anywhere in the tree — all four were the justification for one decision, the Step 3c
> exclusion below. **What replaced it is deliberately narrower**: this section states what the readers
> enforce (dispatch) and declines to assert a timing universal, because a first draft of the replacement
> claimed these steps are "already done by close time" and the rubric's own exemplars contradict it.
> Two of the four cited `schema.md § "User ops"` as their authority and no such section existed:
> the citation resolved to a line inside this file's fenced body template, so the claim could not be
> checked at the place it pointed to. **The exclusion those four sites justify is correct and is
> unchanged** — only the false half of its justification is retired, because a false reason in the
> document that records a decision is how the next reader re-derives the decision wrongly.


### Solo

`solo: true` declares that the task mutates state shared outside the filesystem view, so two tasks with
entirely disjoint file paths can still corrupt each other. A global
lockfile regenerated wholesale, a singleton service registry, a live database schema, a shared fixture
corpus, a dependency manifest every module resolves against: none of these are visible to a path-overlap
grader, which is why the declaration has to be explicit.

**It is not a restatement of `blast_radius`.** The two grade different things and neither implies the
other:

| | `blast_radius: architectural` | `solo: true` |
|---|---|---|
| Grades | **surface area** — how many places the change touches | **serialization** — whether anything else may run alongside it |
| Why it solos | a wide change conflicts with almost anything | a narrow change corrupts shared state regardless of paths |
| Example | a cross-cutting rename across every module | a one-line bump to the shared lockfile |

A `single-file` task can be `solo: true`; an `architectural` task solos already, via invariant `a.`, and
gains nothing from the flag.

**Relationship to the built-in heuristic.** `/auto-build` Step 2 has always had one hardcoded instance of
this property — invariant `b.`, which opens the body file and greps for `migrations/` or `ALTER TABLE`.
That catches SQL schema work and nothing else. `solo: true` is the general declaration for the cases a
body-text heuristic cannot reach, and `b.` **stays**: removing it would silently drop protection for every
existing task that relies on it without declaring the field.

**Where it is read — and the scope of that, stated rather than implied.** `/auto-build` Step 2, solo
invariant `d.`, and **nowhere else**. Matched with a non-empty batch the candidate is skipped; matched
with an empty batch it is added alone and batching stops, identical to `a.`/`b.`/`c.` semantics. The
validator enforces the type only, and absence means `false`.

So the field prevents the task being **batched** with others by `/auto-build`. It does **not** prevent
concurrency generally: `scope_overlap.py` grades path overlap and does not read `solo`, so
`/claim-task`'s in-flight advisory, `/next-task --avoid-inflight` and `/roadmap --in-flight` are all
blind to it. Claiming a `solo: true` task by hand while a batch is in flight is not warned about
anywhere. Read the field as "`/auto-build` will not batch this", not as a general mutual-exclusion lock.


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

## Plan
<optional; written only by /claim-task option C (plan-only). The reviewed plan verbatim in a
 fenced block, followed by the sealed REVIEW_REPORT: block that passed it. Ordered AFTER
 "Test decision" on purpose — the fenced plan contains its own "## Test decision" line, so a
 first-match heading reader must meet the real section first. See "Plan" below.>

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

> **There is no 14th, and there used to be a 13th.** A warn-only test-decision
> check shipped here from Phase 58b until Phase 234 retired it: it read the body
> off the filesystem, while the record it looked for is written inside the
> worktree and committed on the feature branch, so a run from `main` — the only
> place `/claim-task` Step 4c and `/review-close`'s final guard run it — found
> the section missing for the whole `in_progress` window and warned on every
> claimed task on every run. What enforces the record now is `/review-close`
> Step 2d, which reads the branch tip and blocks. See "Test decision" above.
>
> **`## Plan` did not get one either, and for a stronger version of the same
> reason.** The section above is optional by design — option C is one of three
> interaction modes and most tasks never take it — so a warn-only presence check
> would fire on nearly every task in the queue rather than merely on claimed
> ones. A check that cannot tell the failure from the normal case is not a
> backstop, and this one would be louder about it than Invariant 13 ever was.
> See "Plan" above.

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
