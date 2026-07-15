---
name: roadmap
description: Read the task queue back at portfolio level — where the project stands against its vision, outstanding work grouped by kind, and 1–3 proposed orderings of attack with rationale. Read-only strategy view; the judgment sibling of /sitrep's execution-state survey.
argument-hint: "[--in-flight]"
model: opus
disallowed-tools: Edit, Write, NotebookEdit
---
<!-- sysop:model-roles frontmatter=reasoning -->

A read-only **strategy view** of the outstanding queue. `/roadmap` reads `tasks/index.yml` and the intent layer (`tasks/vision.md`, `tasks/decisions.md`), then answers the standing question a human asks whenever they step back from execution: *"What's left, and in what order should I attack it?"* It reports where the project stands against its vision, groups the open work by kind with readiness flags, and proposes one to three distinct execution orderings — each with the trade-off that makes it the right pick. **It never mutates state and never claims or executes a task itself** — the orderings are proposals; any actuation is the human's or the routed skill's.

> **Structural read-only guard (Phase 54):** the `disallowed-tools` frontmatter (Claude Code 2.1.152+) removes the file-write tools while this skill is active. Partial by design — `Bash` stays allowed for the optional `--in-flight` survey below, so the guard covers the dedicated write tools, not shell redirects. Non-Claude-Code harnesses ignore the key.

## Not `/sitrep`, `/next-task`, or `/intake`

These four read the same project from four different contracts; `/roadmap` is deliberately **not folded into** any of them.

- **`/sitrep`** surveys *execution state* — locks, worktrees, `task/*` / `review/*` branches, review batches — and deterministically classifies what is **in flight right now**, with one routing recommendation. Its value is a fixed, mechanical classification you can trust reflexively on cold resume. `/roadmap` reads the *backlog* — what's planned but not yet done — and applies *judgment* (grouping, ordering, trade-offs). Keeping them separate defends `/sitrep`'s deterministic contract; `/roadmap` can *optionally* overlay `/sitrep`'s survey (`--in-flight`) but never duplicates or replaces its classification.
- **`/next-task`** resolves the *single* next claimable task deterministically. `/roadmap` shows the *whole* outstanding portfolio and multiple ways through it. Use `/next-task` when you've already decided the strategy and just want the next unit; use `/roadmap` when you're deciding the strategy.
- **`/intake`** *writes* the queue (brain-dump → validated tasks). `/roadmap` only *reads* it. If `/roadmap` finds the queue empty or a phase too coarse to sequence, it **recommends** `/intake` — it does not decompose or author tasks itself.

## Pre-flight: Permission Guard

**Base path (default): no new permission rules.** `/roadmap` reads `tasks/index.yml`, `tasks/vision.md`, and `tasks/decisions.md` with the `Read` tool (file-level, not Bash-gated) and writes nothing. It runs no scripts on the default path.

**`--in-flight` only:** this flag makes Bash-tool calls to two read-only scripts — `python3 scripts/sitrep_survey.py --json` for the live execution overlay (the survey `/sitrep` runs) and `python3 scripts/scope_overlap.py --json <ID>` per ready candidate for the collision annotation (Step 2b, Phase 103). The git reads happen as subprocesses *inside* those already-approved Python processes, so they never hit the `Bash` permission gate — and per `_shared/permission-guard.md` § Notes, read-only git ops aren't listed as allow-rules anyway. So the only rules `--in-flight` needs are:

- `Bash(python3 scripts/sitrep_survey.py:*)` — the survey script (the same rule `/sitrep` relies on)
- `Bash(python3 scripts/scope_overlap.py:*)` — the collision-overlap primitive (the same rule `/claim-task` relies on, shipped in Phase 102)

Each is independent: if either rule (or its script) is missing, print a one-line note naming which overlay was skipped (`survey overlay skipped: missing Bash(python3 scripts/sitrep_survey.py:*)`, or `collision overlay skipped: scripts/scope_overlap.py unavailable`) and continue **without** that overlay. This flag is optional, so a missing rule *degrades*, it does not halt — never emit the hard-stop permission-guard template for it. If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and continue.

## Step 0 — Parse arguments

Parse `$ARGUMENTS`:

- **`--in-flight`** — overlay live execution state from `/sitrep`'s survey (Step 2a) **and** annotate each ready candidate by collision risk against the worktrees building right now (Step 2b, Phase 103). Off by default: `tasks/index.yml`'s own `status:` field already gives a baseline in-flight picture (which tasks are `in_progress`); the overlay adds lock/worktree/branch reality, stale detection, index-drift discrepancies, and — the collision half — which ready tasks would likely fight an in-flight branch at `/review-close`. Opt in when you want the strategy view reconciled against what's *actually* running, especially before handing a `Run it:` batch to `/auto-build`.
- **`--json`** — reserved for future orchestrator consumption; if unimplemented, fall back to the text report and print a one-line note.

No positional arguments. `/roadmap` always surveys the whole queue.

## Step 1 — Read the queue and the intent layer

Read these, tolerating absence (a consumer may have run `install.sh` but not `/intake` yet):

1. **`tasks/index.yml`** — the source of truth for tasks and phases. Parse the `phases:` list and the `tasks:` list. Per task, the fields that drive this skill: `id`, `title`, `phase`, `status`, `effort`, `blast_radius`, `user_action`, `depends_on`, `on_hold_until`. See `tasks/schema.md` for the full field spec.
2. **`tasks/vision.md`** — if present, read the *Definition of done for v1* and the *What it does — and deliberately does not* sections. These anchor the "where do we stand?" framing.
3. **`tasks/decisions.md`** — if present, skim for load-bearing sequencing decisions (a recorded decision may explain *why* the natural technical order isn't the chosen one — respect it).

**Absence handling:**

- **No `tasks/index.yml`, or `tasks:` is empty** → there is no queue to strategize. Report that plainly and recommend `/intake`: *"No populated queue yet — run `/intake` to turn a brief into a validated backlog, then `/roadmap` to sequence it."* Stop here; do not fabricate tasks.
- **`index.yml` present, `vision.md` / `decisions.md` absent** → skip the "against its vision" framing (note the absence in one line), and produce the grouping + orderings from the index alone. Optionally suggest `/intake` to author the intent layer so future roadmap reads have a vision to measure against.

## Step 2 — Overlay live execution state (only if `--in-flight`)

### Step 2a — Execution-state survey

Run the survey exactly as `/sitrep` does and consume its JSON:

```bash
python3 scripts/sitrep_survey.py --json
```

Read each task's `state` (e.g. `in progress`, `planning`, `ready for /review-close`) and the `discrepancies` list, and overlay them onto the index tasks by `id`. Surface, in the Standing block, anything the index and the live state disagree on (index says `in_progress` but no lock; an orphan branch with no index entry) — but **route hygiene to `/sitrep`**: name the discrepancy, then say *"run `/sitrep` for the full execution-state survey and cleanup routing"*. Do not attempt cleanup; do not re-derive `/sitrep`'s classification table here.

If the survey exits non-zero, print a one-line note that the survey overlay was skipped and continue with the index-only view.

### Step 2b — Collision annotation (Phase 103)

For each **✅ ready** candidate identified in Step 3 (the agent-executable frontier — not blocked, on-hold, or in-flight tasks), ask the shared scope-overlap primitive whether its likely file scope collides with any worktree building right now:

```bash
python3 scripts/scope_overlap.py --json <TASK_ID>
```

Read the JSON `max_verdict` (`likely` / `possible` / `none`), the `overlaps` list (each names the in-flight `task_id` and the `evidence` paths that matched), and `broad_radius_note`. This is the same primitive `/claim-task` Step 2 runs — it infers the candidate's scope from its `## Key files` + `blast_radius` (a *pre-plan guess*) and compares it against each in-flight worktree's **actual** changed set. Cache the result per task id; you'll reuse it in Step 3 (the readiness marker) and Step 4 (the `Run it:` caveat).

**Keep it advisory and bounded:**

- Run it **only for ✅-ready candidates** — a 🔒/⛔/⏸ task can't be batched, so its collision risk is moot until it becomes ready.
- If there is **no work in flight** (Step 2a found no locks/worktrees), skip 2b entirely — nothing to collide with; note it in one line and move on.
- A `none` verdict means *no declared overlap*, **not** *provably safe* (the candidate side is a guess). Never present it as a guarantee.
- If `scope_overlap.py` is missing or its permission rule absent, print the one-line degrade note from the Permission Guard and produce the roadmap **without** collision annotations — the orderings still stand.

## Step 3 — Group the outstanding work by kind

"Outstanding" = every task with `status` in `{open, in_progress}` (skip `done` and `deferred`; count `done` for the Standing block only).

**Classify each outstanding task's readiness** from its fields — a task can carry more than one flag:

- 🔒 **Blocked on you (human):** `user_action: true`. These need a console, credentials, a domain, or private knowledge only the human has — an agent cannot start them. Surface these **first-class**: they are the tasks that silently stall everything downstream.
- ⏸ **On hold:** `on_hold_until` is non-null (e.g. waiting on an upstream release). Note what it waits on.
- ⛔ **Dep-blocked:** `depends_on` lists at least one task that is not yet `done` — an `open`/`in_progress` prerequisite still being built, or a `deferred` one that's parked. A **`deferred` dependency is not satisfied**: don't advertise a task sitting on a parked prerequisite as ready. Only a `done` dependency counts as met. Name the blocker(s) and their status.
- ▶ **In flight:** `status: in_progress` (or, under `--in-flight`, the survey's live `in progress` / `planning` state).
- ✅ **Ready now:** `open`, not `user_action`, not on hold, and **every** `depends_on` target is `done`. The agent-executable frontier.

**Collision marker (only under `--in-flight`, from Step 2b):** a ✅-ready task whose likely scope collides with a worktree building right now carries a trailing 💥 marker — `💥 likely conflict with TECH-B` (exact-path overlap) or `💥 possible overlap with TECH-B` (same-directory/glob). This is orthogonal to the readiness flags (a task is still ✅ *ready* — it just isn't *clear*): the marker warns that claiming it now risks a merge conflict at `/review-close`, not that it can't be claimed. Absent `--in-flight`, or when nothing is in flight, no 💥 marker appears.

**Group by kind** for the human's category view. Derive kinds from the `id` prefix vocabulary actually present in the queue (`tasks/schema.md` leaves prefixes project-chosen), mapping the common ones:

| Prefix | Kind label |
|---|---|
| `FEAT-` | Feature development |
| `TECH-` | Technical / infrastructure |
| `DATA-` | Data-ops |
| `FIX-` | Fixes |
| `UX-` | UX / frontend |
| *(other)* | Group under the literal prefix |

Present each kind as a short list of its outstanding tasks with `id`, `title`, `effort` (and `blast_radius` **only when present** — it's optional at `schema_version: 1`, which is what `install.sh` ships, so a hand-authored or legacy v1 queue may omit it; render it when there, elide it when not), and readiness flags. The readiness flags are the orthogonal cut (a `DATA-` task can be 🔒 blocked-on-you); the kind grouping is the category cut. Together they answer "what have I got, by category, and what's waiting on what."

## Step 4 — Propose 1–3 orderings of attack

This is the skill's distinctive output: not one "correct" order, but the **two or three genuinely different paths** through the ready + soon-ready work, each with the trade-off that makes it the right call. Compute them from the schema signals; present **only the orderings that are materially different for this queue** — never pad to three.

- **Unblock-the-human-first** — lead with every 🔒 `user_action: true` task so the human clears credentials/console/domain setup in one sitting while agents work the rest in parallel. **Prefer when** ≥1 `user_action` task gates downstream work — clearing it early converts a serial stall into parallel progress. Drop this ordering entirely if the queue has no `user_action` tasks.
- **Foundation-first** — a topological order over `depends_on`, breaking ties toward higher `blast_radius` (`architectural` / `cross-module`) and higher *unlock count* (how many other open tasks list this one in their `depends_on`; where `blast_radius` is absent, tie-break on unlock count then `effort`). **Prefer when** the queue has real dependency chains or shared-infrastructure tasks — it builds the base before the things that sit on it and minimizes rework. Collapse into ship-fast when there are no dependencies and nothing architectural. **Cycle guard:** `depends_on` is meant to be acyclic, but `validate_tasks.py` checks only reference integrity — it does *not* detect cycles, so a fully-valid `index.yml` can still contain one (A→B→A). Check for a cycle before ordering; if you find one, do **not** emit a topological order (it's undefined and would mislead) — surface it as a data defect (*"`depends_on` cycle A↔B — the index is internally inconsistent; fix it or route to the human"*) and order only the acyclic remainder.
- **Ship-fast** — lowest `effort` first (and, where `blast_radius` is present, smallest surface first) among tasks with no unmet deps, to land a visible win and build momentum. **Prefer when** the priority is a demo, a morale/momentum beat, or validating the pipeline end-to-end before investing in foundations. Flag the cost: cheap-first can defer an architectural task whose late arrival forces rework — say so when that risk is real in this queue.

For each ordering you present: the first ~3–5 task IDs in that order, a one-sentence rationale, the "prefer when" condition — and a copy-pasteable **`Run it:`** actuator line built from the ordering's leading ✅-ready IDs: `/auto-build <ready IDs>` when two or more lead (list them in the ordering's sequence for readability — `/auto-build` re-sorts internally, so argument order carries no scheduling weight), `/claim-task <ID>` when only one does. Include only ✅-ready IDs (🔒/⛔/⏸ tasks can't be batched — `/auto-build` would just report them excluded); when a 🔒 task leads the ordering, name it as the human's move and hand the agent-ready remainder to `/auto-build`. The line is a handoff, not a guarantee — `/auto-build` re-applies its own eligibility filters and K=6/N ceilings to the IDs, reports any it can't batch with per-ID reasons, and still stops at its own confirmation gate. Where a recorded decision in `tasks/decisions.md` constrains the order (an explicit sequencing call), honor it and cite the decision rather than proposing an order that contradicts it.

**Collision caveat on `Run it:` lines (only under `--in-flight`, from Step 2b).** If any ID in a `Run it:` line carries a 💥 marker, append a one-line caveat naming the collision — e.g. `Run it: /auto-build FEAT-A FEAT-B  (heads up: FEAT-A 💥 overlaps in-flight TECH-B on src/api/routes.py — expect a /review-close conflict, or drop it and batch the rest)`. It stays a handoff, not a veto: the human may still want the overlapping task (worktree isolation makes the conflict recoverable rework, and `/auto-build` re-checks anyway). When *every* ready ID in an ordering is clear, say so in one word (`Run it: /auto-build FEAT-A FEAT-B  (both clear of in-flight work)`) — the absence of a collision is itself useful signal for what to batch next.

**Honesty about the ceiling.** These orderings are heuristics over the fields; the human's context — an external deadline, what they have energy for today, a stakeholder demo — legitimately overrides any of them. Present the trade-offs; do not pretend one path is objectively correct. When a deadline picks a *subset*, hand it straight to `/auto-build <IDs>`; when it genuinely re-prioritizes the *lane*, reshape `phases:` via `/intake` re-entry and flip `current_focus` instead — don't restructure phases to steer one batch.

## Step 5 — Surface the report and offer the next move

Print the report in the shape below, then offer **one** routing move — but do not actuate without explicit confirmation (the read-only contract: `/roadmap` informs; the human or the routed skill acts).

- Ready-now tasks exist → offer `/next-task` (see the single next unit) or `/auto-build` (batch the ready frontier) or `/auto-build <IDs>` (batch the exact subset an ordering proposes — its `Run it:` line) or `/claim-task <ID>` (start a specific one you chose from an ordering).
- Only 🔒 / ⛔ / ⏸ tasks remain (nothing ready) → name what unblocks the frontier (usually a `user_action` task the human must do) rather than routing to a build skill.
- Queue empty or a phase too coarse to sequence → `/intake`.
- Want live execution detail or discrepancy cleanup → `/sitrep`.

Close with one line: `Read-only strategy view — no state changed. Actuators: /intake, /claim-task, /auto-build, /next-task, /sitrep.`

## Output shape (reference)

```
## Roadmap — <project>

STANDING
Phase <K> of <M> ("<current-focus phase title>") is current-focus.
Status: <N> done · <O> open · <P> in flight · <D> deferred     (status buckets — these partition the queue)
Of the open + in-flight: <R> 🔒 need you · <S> ⛔ dep-blocked · <T> ⏸ on hold · <U> ✅ ready     (readiness — orthogonal, may overlap)
v1 done: <one line from vision.md, or "no vision.md — run /intake to author one">

OUTSTANDING WORK — by kind      (💥 markers appear only under --in-flight — see below)
Feature development
  FEAT-LEDGER-IMPORT   Import OFX statements     Medium / single-module   ✅ ready
  FEAT-DASHBOARD       Spending dashboard        High / cross-module      ⛔ needs FEAT-LEDGER-IMPORT
Data-ops
  DATA-VENDOR-SEED     Seed vendor catalog       Low / single-file        🔒 you: obtain vendor list
Technical / infrastructure
  TECH-DB-BOOTSTRAP    Schema + migrations       High / architectural     ✅ ready

PROPOSED ORDERINGS
1. Unblock-the-human-first  → DATA-VENDOR-SEED, then TECH-DB-BOOTSTRAP, FEAT-LEDGER-IMPORT …
   Clear the one credential-gated task now so nothing downstream waits on you.
   Prefer when: a user_action task is on the critical path (it is — DATA-VENDOR-SEED).
   Run it: DATA-VENDOR-SEED is yours; agents take the rest → /auto-build TECH-DB-BOOTSTRAP FEAT-LEDGER-IMPORT   (the architectural task will solo — expect two cycles)
2. Foundation-first         → TECH-DB-BOOTSTRAP, FEAT-LEDGER-IMPORT, FEAT-DASHBOARD …
   Build the schema before the features that read it; avoids re-plumbing later.
   Prefer when: dependency chains are real (FEAT-DASHBOARD → FEAT-LEDGER-IMPORT → schema).
   Run it: /auto-build TECH-DB-BOOTSTRAP FEAT-LEDGER-IMPORT   (the architectural task will solo under /auto-build's invariants — expect two cycles; FEAT-DASHBOARD stays ⛔ until the import lands)
3. Ship-fast                → DATA-VENDOR-SEED, FEAT-LEDGER-IMPORT …
   Land a visible import feature quickly; defers the architectural DB work (rework risk if the schema shifts).
   Prefer when: you want a demo beat before investing in foundations.
   Run it: /claim-task FEAT-LEDGER-IMPORT   (single ready task at the front — no batch needed)

RECOMMENDED NEXT
Nothing is blocked on an agent, but DATA-VENDOR-SEED is blocked on you. Clear it, then /auto-build the ready frontier.

Read-only strategy view — no state changed. Actuators: /intake, /claim-task, /auto-build, /next-task, /sitrep.
```

Adapt the shape to the queue; omit empty groups; render only the orderings that differ materially.

**Under `--in-flight`, the collision overlay adds 💥 markers + `Run it:` caveats** (Step 2b). Suppose `TECH-DB-BOOTSTRAP` is being built right now — it becomes `▶ in flight` (not `✅ ready`, per the Step 3 taxonomy), so it drops out of every `Run it:` batch, and a ready task whose scope collides with it gets a 💥 marker and a caveat:

```
Technical / infrastructure
  TECH-DB-BOOTSTRAP    Schema + migrations       High / architectural     ▶ in flight (being built now)
Feature development
  FEAT-LEDGER-IMPORT   Import OFX statements     Medium / single-module   ✅ ready  💥 possible overlap with in-flight TECH-DB-BOOTSTRAP

PROPOSED ORDERINGS
1. Ship-fast → FEAT-LEDGER-IMPORT …
   Run it: /claim-task FEAT-LEDGER-IMPORT   (heads up: 💥 possible overlap with in-flight TECH-DB-BOOTSTRAP on the schema — expect a /review-close conflict, or wait for it to merge)
```

The 💥 marker warns; it never removes the task from an ordering (advisory, read-only). When every ready ID in a `Run it:` line is clear of in-flight work, say so (`… (both clear of in-flight work)`).

## Design notes

- **Why a sibling, not a `/sitrep` flag.** `/sitrep`'s value is a *deterministic* classification safe to trust reflexively on cold resume — folding judgment (grouping, ordering, trade-offs) into it would blur that contract. `/roadmap` is the judgment layer; `/sitrep` is the mechanical one. They compose (`--in-flight`) without merging.
- **The demo beat.** On a fresh install the natural sequence is `/intake` (populate the queue) → `/roadmap` (see what you've got and how to attack it) → `/auto-build` or `/claim-task` (execute). `/roadmap` fills the "what do I have, and in what order?" beat that was previously ad-hoc chat.
- **Portability.** The base path is pure file reads (`Read` on three files) — it runs on any agent, including bash-installer/non-Claude consumers, with no git or script dependency. `--in-flight` is the only path that needs `git` + `scripts/sitrep_survey.py`, and it degrades gracefully to the index-only view when they're absent.
- **Wired (Phase 73a):** `/sitrep`'s `RECOMMENDED NEXT` cascade (Phase 44) routes to `/roadmap` at priority **7a** when the queue is deeper than one `/auto-build` batch (> 4 open roadmap tasks) — a strategy view before batch execution; a shallower queue (1–4, fits one batch) keeps the `/auto-build` recommendation (7b). See `sitrep/SKILL.md` § Recommendation routing rules.
- **Executable orderings (Phase 97).** `/auto-build` accepts an explicit task-ID subset (`/auto-build FEAT-A TECH-B`), so each ordering closes with a `Run it:` actuator line — the orderings are handoffs, not just advice. `/auto-build` re-applies its own filters and ceilings to the IDs and reports any it can't batch; the line never pre-commits the human past `/auto-build`'s own confirmation gate, so `/roadmap`'s read-only contract is intact.
- **Collision annotation (Phase 103).** Under `--in-flight`, ready candidates and `Run it:` lines are annotated by collision risk against the worktrees building right now, via the shared `scripts/scope_overlap.py` primitive (the same one `/claim-task` Step 2 runs, and `/auto-build`'s Leg B). It's the read-only, portfolio-level companion to `/claim-task`'s single-task advisory — "of everything I *could* batch, which won't fight what's already running?" — and answers the "surface me better tasks to batch" need directly. Advisory only: a 💥 marker warns, it never removes a task from an ordering (the read-only contract holds, and overlap is recoverable rework). The base path (no `--in-flight`) stays pure file reads with no git/script dependency, so portability is unchanged.

## Deferred features

- **`--json`** — structured emit for orchestrator consumption. Reserved; the text report is the only output today.
- **`--phase N`** — scope the grouping + orderings to a single phase for very deep queues. Deferred; today's report covers all outstanding phases and the human reads the phase they care about.
