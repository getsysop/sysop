---
name: add-task
description: Capture a single task into the queue mid-conversation — one bug, idea, or chore becomes a validated tasks/index.yml entry + body, deduped against the open queue, left uncommitted for sign-off. The lightweight sibling of /intake — reach for it whenever a task-shaped thought appears ("add a task for this", "file this", "spec this into the queue", "put it in the backlog"); route to /intake when the thought is a feature or phase that needs decomposing.
argument-hint: "[one-line task description — or omit and describe it conversationally]"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning -->

The quick-capture path into the task queue. `/intake` is the planning front door — a multi-turn interview that decomposes a phase of intent into a slice of tasks. But the highest-frequency planning event in a live project is much smaller: a bug spotted in a screenshot, an idea mid-review, a chore noticed in passing. `/add-task` gives that moment a thirty-second landing: one task in, one validated queue entry out, uncommitted, ready to `/claim-task`.

This skill exists so the capture is *deterministic*, not emergent. Without it, "spec that as a task" depends on the session rediscovering `tasks/schema.md` from scratch — sometimes producing a validator-failing entry, sometimes skipping the queue entirely. With it, both entry points converge on the same procedure: the human invokes `/add-task` explicitly, or the agent routes here on its own when the conversation produces a task-shaped thought.

## Routing — is this even the right tool?

Three neighbors, three boundaries. Check before drafting:

- **"Fix it now" is not a capture-only event.** If the human wants the change made in this session, do the work — or, when it deserves the full plan/lock/worktree discipline, file the task here and immediately `/claim-task <TASK-ID>` it (claiming requires a queue entry, so filing first costs seconds and keeps the record). What `/add-task` never does is make the change itself.
- **Friction with Sysop itself goes to `SYSOP_ISSUES.md`**, not the task queue. "The `/review-close` prompt confused me" is a Sysop issue (captured in `SYSOP_ISSUES.md`, transported by `/report-issues`); "the login button is the wrong color" is *your project's* work and belongs here. When the thought is about the workflow rather than the product, say so and capture it in `SYSOP_ISSUES.md` instead.
- **A phase is not a task.** If the thought decomposes into more than about three independent tasks, or wants a new phase, that's planning — hand off to `/intake` (re-entry mode). See Step 1.

## Step 0 — Orient

1. Read `tasks/index.yml`. If it doesn't exist or the `tasks/` scaffold is absent, this project hasn't adopted the queue — stop and route: `/intake` for a new project, `/onboard` for an existing one with a backlog to import. Do not scaffold `tasks/` yourself.
2. Get the task-shaped thought: from `$ARGUMENTS` if provided, otherwise from the surrounding conversation (a screenshot the human just annotated, a bug they just described). If neither yields one, ask — one open question, not a form: *"What's the task? Tell me what done looks like."*
3. Note the queue's existing shape while the file is open: the ID prefix vocabulary in use (`FEAT-`, `TECH-`, `FIX-`, …), which phase has `current_focus: true`, and the `schema_version`.

## Step 1 — Scope check (rubric-lite)

Apply the atomicity litmus from `.claude/skills/_shared/decomposition-rubric.md`: **can you state the done-condition in one falsifiable sentence?**

- **One sentence** → one task; proceed.
- **Two or three clean sentences** → two or three sibling tasks; offer to file them together in this run (each gets its own entry + body in Steps 3–5). Don't manufacture `depends_on` edges between independent siblings.
- **More than that, or a new phase wanted** → this is planning, not capture. Say so plainly and hand off: *"That's phase-shaped — `/intake` will decompose it properly. Want me to run it?"* Never create a new `phases:` entry from this skill.

**Intent-layer cross-check (tolerate-absent).** If `tasks/decisions.md` exists and the task plainly contradicts a recorded decision (the task reaches for SQLite; decision D3 committed Postgres), surface the contradiction — don't silently file it or silently bend it. Detection is the job; the human resolves it. If the intent files don't exist, skip this without comment.

## Step 2 — Dedup

Search the queue for overlap before drafting: task titles in `index.yml` plus a `Grep` over `tasks/open/` and `tasks/deferred/` bodies for the task's key nouns. If a plausible match exists:

- **An open task already covers it** → surface it; offer to extend that task's body with the new detail instead of filing a duplicate.
- **A deferred task covers it** → surface it; the right move may be un-parking that task (a human decision), not filing a twin.
- **Related but genuinely distinct** → file the new task and record the relationship in prose in `## Context` (formal `surfaced_by:` only when the existing task actually *spawned* this one).

No match → proceed.

## Step 3 — Draft

Draft the index entry and body. Sizing and semantics come from the decomposition rubric — read it if you haven't this session.

Every captured entry is `status: open` and carries the full required field set — `id`, `title`, `phase`, `status`, `effort`, `blast_radius`, `user_action`, `depends_on`, `surfaced_by`, `body` (the same list `/intake` Step 7 emits). The bullets below cover the fields with judgment in them:

- **`id`** — follow the queue's existing prefix vocabulary from Step 0; pick the prefix that fits the work's kind and a short slug (`FIX-LOGIN-BUTTON-COLOR`). Must match `^[A-Z][A-Z0-9-]{2,80}$` and be unique — on collision, pick a new slug; never overwrite.
- **`title`** — one short human-readable line; lead with what changes, not with "fix" boilerplate.
- **`phase`** — default to the `current_focus: true` phase. If the task clearly belongs to a *later* existing phase (it's an idea for phase 3, not current work), assign that phase and say so in the playback. Only `AskUserQuestion` when the assignment is genuinely ambiguous *and* materially changes what happens next — this skill's budget is one question, usually zero.
- **`effort` + `blast_radius`** — author **both**, even at `schema_version: 1` (rubric § 2: independent axes — work/risk vs. surface touched).
- **`user_action`** — `true` only for a human-only *action* (console, credentials, private knowledge), never for uncertainty (rubric § 4). When `true`, the body gets `## User ops (do these first)`.
- **`depends_on`** — physical impossibility only ("can this start before X finishes?" — if yes, no edge). Default `[]`.
- **`surfaced_by`** — provenance, only when a known task ID actually spawned this one. Default `[]`.
- **`on_hold_until`** — set when the human names a real external wait ("after the Stripe v2 GA"); it's timing, not a `user_action`.
- **`manual_smoke`** — `true` when verification is human-eyeball-only (a UI flow, a side-effect-bearing command); then include a `## Manual smoke required` section in the body describing the procedure.
- **`body`** — `open/<TASK-ID>.md`, first heading `# <TASK-ID>` (validator-enforced), sections `## Context` (why this matters, where it came from), `## Requirements` (numbered, falsifiable), `## Key files` (best current guess is fine). **Do not** write a `## Test decision` section — that's recorded at `/claim-task` plan time, not capture time.

Keep the body proportional to the task: a `Low / single-file` fix gets a few lines per section, not a spec. Capture is the point; `/claim-task`'s planning pass fills gaps at claim time.

## Step 4 — Playback (one turn)

Show exactly what will be written — the drafted `index.yml` entry and the body, compact — and invite correction in prose: *"Fix anything before I write it."* What's shown is what gets emitted; don't silently revise after approval. For a batch of two or three siblings, show all of them in the same turn.

This is one conversational turn, not a review gate. The human's real sign-off is the commit (Step 5).

## Step 5 — Emit, validate, hand off

1. **`tasks/index.yml`** — append with the `Edit` tool: add the new `tasks:` entry (or entries) under the existing list. If the queue is still the installer seed (a literal `tasks: []`), replace the inline empty list with a block sequence containing your entry — you're authoring the first entry, not appending to a list. **Never** rewrite or drop an existing entry or its `sprint_note` block scalar, never touch `phases:`, never change any existing task's `status:`. On an ID collision discovered at write time, stop and re-slug — surface it, don't overwrite.
2. **Body file(s)** — `Write` `tasks/open/<TASK-ID>.md` per the Step 3 shape.
3. **Validate (the floor):**

   ```bash
   .venv/bin/python3 sysop/scripts/validate_tasks.py
   ```

   (Bare `python3` if the project has no `.venv`.) Exit 0 or fix the data and re-run — never hand off on a red validator.
4. **Leave everything uncommitted** and print the hand-off:

   ```
   ## Task filed — review before committing

   Wrote (uncommitted):
   - tasks/index.yml           (+<N> entry: <TASK-ID> — <title>)
   - tasks/open/<TASK-ID>.md

   Validator: PASS.

   Commit is your sign-off. Claim it when ready: /claim-task <TASK-ID>
   ```

   Do not `git add`, do not `git commit` — the commit is the human's sign-off, same contract as `/intake`.

## What this skill never does

- Creates or edits `phases:`, `tasks/vision.md`, or `tasks/decisions.md` — that's `/intake`.
- Changes any existing task's `status:`, touches `.locks/`, or edits an existing entry — capture only appends.
- Imports backlogs or scans the repo for work — that's `/onboard`.
- Commits, pushes, or merges anything.

## Permissions

`/add-task` needs **no new permission rules.** It writes via the `Write` / `Edit` tools (file-level, not Bash-gated) and runs only `validate_tasks.py`, which the default `.claude/settings.json` already allows (bare + `.venv/bin/python3` variants). It does not commit, push, or merge.
