---
name: roadmap
description: Read both work queues back at portfolio level — where the project stands against its vision, outstanding roadmap tasks and review batches grouped by kind, and 1–4 proposed orderings of attack with rationale. Read-only strategy view; the judgment sibling of /sitrep's execution-state survey.
argument-hint: "[--in-flight]"
model: opus
disallowed-tools: Edit, Write, NotebookEdit
---
<!-- sysop:model-roles frontmatter=reasoning -->

A read-only **strategy view** of the outstanding work. `/roadmap` reads **both of the project's work queues** — `tasks/index.yml` (roadmap tasks) and `review_tasks.md` (review batches) — plus the intent layer (`tasks/vision.md`, `tasks/decisions.md`), then answers the standing question a human asks whenever they step back from execution: *"What's left, and in what order should I attack it?"* It reports where the project stands against its vision, groups the open work by kind with readiness flags, and proposes up to four distinct execution orderings — each with the trade-off that makes it the right pick. **It never mutates state and never claims or executes a task itself** — the orderings are proposals; any actuation is the human's or the routed skill's.

> **Why both queues (Phase 199).** A project that runs the convention loop has a *second* work queue with its own lifecycle (`Pending → In Progress → Merged`), its own claimer (`batch_work.sh`), its own closer (`close_batch.sh`) and its own `/triage` → `/auto-fix` / `/auto-judge` routing. Surveying only `tasks/index.yml` meant the portfolio view a human consults to decide what to work on could omit **the only open security work in the project** — which is exactly what a consumer reported (Sysop's internal tracker #394): two `Pending` batches carrying nine findings, four of them security, sat seven days while `/roadmap` reported 195 tasks and three orderings and named none of them. `/next-task` already spans both queues on its default path (`next_task.py` — *"Default mode: index first, then review"*), so cross-queue reading is the established shape for a read-side skill here, not a new one.

> **Structural read-only guard (Phase 54):** the `disallowed-tools` frontmatter (Claude Code 2.1.152+) removes the file-write tools while this skill is active. Partial by design — `Bash` stays allowed for the optional `--in-flight` survey below, so the guard covers the dedicated write tools, not shell redirects. Non-Claude-Code harnesses ignore the key.

## Not `/sitrep`, `/next-task`, or `/intake`

These four read the same project from four different contracts; `/roadmap` is deliberately **not folded into** any of them.

- **`/sitrep`** surveys *execution state* — locks, worktrees, `task/*` / `review/*` branches — and deterministically classifies what is **in flight right now**, with one routing recommendation. Its value is a fixed, mechanical classification you can trust reflexively on cold resume. `/roadmap` reads the *backlog* — what's planned but not yet done — and applies *judgment* (grouping, ordering, trade-offs). Keeping them separate defends `/sitrep`'s deterministic contract; `/roadmap` can *optionally* overlay `/sitrep`'s survey (`--in-flight`) but never duplicates or replaces its classification.
  - **Both skills read both queues; the split is determinism vs judgment, not which file.** An earlier revision of this bullet listed "review batches" as `/sitrep`'s territory, which contradicted the criterion in its own next sentence: an unclaimed `Pending` batch is *backlog*, not something in flight, and the survey classifies it as `pending (not claimed)` for exactly that reason. The dividing line is what each skill *does* with a batch — `/sitrep` classifies it mechanically and routes; `/roadmap` ranks it against everything else you could be doing.
  - **Precedence, stated because the two skills can disagree and that is legitimate.** `/sitrep`'s cascade is batch-first (its priorities 2 and 4 fire before the roadmap-depth priority 7), so while any `Pending` unclaimed batch exists it will route you to `/triage` / `/auto-fix` / `/auto-judge`. `/roadmap` is **roadmap-first with batches ranked alongside**, matching `/next-task`'s default mode. So on the same state `/sitrep` may say "triage batch 583" while `/roadmap` ranks a task above it. That is the judgment layer doing its job, not a bug — but say so when it happens rather than presenting an ordering as if `/sitrep` agreed with it.
- **`/next-task`** resolves the *single* next claimable unit deterministically — a roadmap task where one is claimable, otherwise the next pending review batch (`--review` surfaces only batches). `/roadmap` shows the *whole* outstanding portfolio and multiple ways through it. Use `/next-task` when you've already decided the strategy and just want the next unit; use `/roadmap` when you're deciding the strategy.
- **`/intake`** *writes* the queue (brain-dump → validated tasks). `/roadmap` only *reads* it. If `/roadmap` finds the queue empty or a phase too coarse to sequence, it **recommends** `/intake` — it does not decompose or author tasks itself.

## Pre-flight: Permission Guard

**Base path (default): no new permission rules.** `/roadmap` reads `tasks/index.yml`, `tasks/vision.md`, `tasks/decisions.md`, and `review_tasks.md` with the `Read` tool (file-level, not Bash-gated) and writes nothing. It runs no scripts on the default path — `review_tasks.md` is read directly, **not** through `sysop/scripts/review_index.py`, which would need a `Bash` rule the template does not seed and would cost the no-new-rules property this paragraph asserts.

**`--in-flight` only:** this flag makes Bash-tool calls to two read-only scripts — `python3 sysop/scripts/sitrep_survey.py --json` for the live execution overlay (the survey `/sitrep` runs) and `python3 sysop/scripts/scope_overlap.py --json <ID>` per ready candidate for the collision annotation (Step 2b, Phase 103). The git reads happen as subprocesses *inside* those already-approved Python processes, so they never hit the `Bash` permission gate — and per `_shared/permission-guard.md` § Notes, read-only git ops aren't listed as allow-rules anyway. So the only rules `--in-flight` needs are:

- `Bash(python3 sysop/scripts/sitrep_survey.py:*)` — the survey script (the same rule `/sitrep` relies on)
- `Bash(python3 sysop/scripts/scope_overlap.py:*)` — the collision-overlap primitive (the same rule `/claim-task` relies on, shipped in Phase 102)

Each is independent: if either rule (or its script) is missing, print a one-line note naming which overlay was skipped (`survey overlay skipped: missing Bash(python3 sysop/scripts/sitrep_survey.py:*)`, or `collision overlay skipped: sysop/scripts/scope_overlap.py unavailable`) and continue **without** that overlay. This flag is optional, so a missing rule *degrades*, it does not halt — never emit the hard-stop permission-guard template for it. If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and continue.

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
4. **`review_tasks.md`** — the review-batch queue. **It lives at the repository root, not under `sysop/`** (Phase 128 moved the consumer footprint into `sysop/`; this file did not move). Per batch, take only: the batch number, its title, its status, and its `> **Flag:**` / `> **Triaged:**` metadata lines.

### Which tree, and which batches

**The base path reads whatever tree it is invoked in — including `review_tasks.md`.** That is forced by the portability contract below (pure `Read`, no git, no scripts): resolving the main checkout needs `git rev-parse --git-common-dir`, which the base path deliberately cannot run. **This is a real limitation, not a detail.** A worktree carries its branch's own `review_tasks.md` *and its own `tasks/index.yml`* — it applies to all four reads above, not just the tracker — while `--in-flight` describes the **main checkout** (`sitrep_survey.py` resolves both the index and the tracker from it). So a `/roadmap` run from a worktree can legitimately report a different queue from `/sitrep` run beside it.

- **Under `--in-flight`, prefer the payload.** The survey returns `main_root`; when it disagrees with your working directory, say so in one line and treat the payload as authoritative for the overlay half.
- **On the base path, name the tree you read** when you can tell you are not in the main checkout (a `.git` *file* rather than a directory is the cheap signal, and reading it costs no script). Do not guess at the main checkout's path.

**Survey the three LIVE statuses: `Pending`, `In Progress` and `Review Ready`.** The tracker declares which of its six statuses are live and which are terminal, and the two that read like each other are on opposite sides: `batch_work.sh` states it outright — *"Declared: Pending · In Progress · Review Ready (live) · Complete · Merged · Ready for Review (finished)"* — and calls `Review Ready` *"the one status that needs someone to act"*. `Complete`, `Merged` and `Ready for Review` are terminal. **Take that list from the tracker's own declaration, not from the names**, which are actively misleading here.

**`--in-flight` reaches only two of the three, and you must say which rows it could not enrich.** The survey filters to `Pending`/`In Progress` before emitting `review_batches`, so a `Review Ready` batch appears on the base path with no `state`, no lock/branch reality and no progress count. That is the *correct* trade: the base path is the broader view, and dropping a live status to make the two halves match would reproduce the defect this skill exists to fix — work that needs a human, absent from the strategy view.

**Status is not the only gate, and the other one cuts the wrong way.** The survey also **drops entirely** any batch whose header its strict pattern rejects — a tab or double space after `###`, a missing em-dash, an unbackticked status. Such a batch closes its predecessor and is then never emitted, so it is invisible to `--in-flight`, and to `/sitrep`, `/triage`, `/auto-fix` and `/auto-judge` with it. **The base path is the only thing that can see it.** So when you find a batch the strict shape rejects, report it and say it is invisible to every other tool — that is a malformed-header defect worth a line of its own, and it is the reported failure of this skill (an open batch outside the strategy view) reached one layer deeper.

### Reading it safely

`review_tasks.md` is a tracker several different steps append to, and its structural markers appear inside its own content. Three rules, each of which has a recorded failure behind it:

- **Mask fenced blocks before matching anything.** Task remediation text routinely quotes batch headers and checkbox lines. **An *unterminated* fence must be ignored rather than honoured** — treating it as open-to-EOF disables structural parsing for the rest of the file, which is how a whole range once got misread.
- **Any level-2 (`## `) heading closes the open batch.** Without this the last batch absorbs the `## Deferred` / `## Statistics` sections beneath it and reports their lines as its own.
- **A batch header is `### Batch <N> — <Title> \`<Status>\``**, with an em-dash and a backticked status. Treat *any* `### Batch <N>` line as closing the previous batch even when it does not match that shape exactly — a tab or a double space after `###` is a real thing that has appeared, and a header the strict shape rejects must still not be swallowed by its neighbour.

You need batch-level rollups, not task-level line ranges, so you do **not** need the two-pass index-then-range procedure `/triage`, `/auto-fix` and `/auto-judge` each carry. Do not improvise one; if you find yourself needing per-task line numbers, that is a sign the work belongs in one of those skills.

**Absence handling:**

- **No `tasks/index.yml`, or `tasks:` is empty** → there is no queue to strategize. Report that plainly and recommend `/intake`: *"No populated queue yet — run `/intake` to turn a brief into a validated backlog, then `/roadmap` to sequence it."* Stop here; do not fabricate tasks.
- **`index.yml` present, `vision.md` / `decisions.md` absent** → skip the "against its vision" framing (note the absence in one line), and produce the grouping + orderings from the index alone. Optionally suggest `/intake` to author the intent layer so future roadmap reads have a vision to measure against.
- **`review_tasks.md` absent** → **this is the common case, not an error.** `install.sh` does not seed the file; it first exists after the project's first `/codebase-review` or `/security-audit` run, so a consumer who installed and ran `/intake` legitimately has no review queue yet. Cost it **one line** (*"no `review_tasks.md` — the convention loop has not run here"*), emit no batch group and no heading, and continue. Never present its absence as a defect or a reason to stop.

## Step 2 — Overlay live execution state (only if `--in-flight`)

### Step 2a — Execution-state survey

Run the survey exactly as `/sitrep` does and consume its JSON:

```bash
python3 sysop/scripts/sitrep_survey.py --json
```

Read each task's `state` (e.g. `in progress`, `planning`, `ready for /review-close`) and the `discrepancies` list, and overlay them onto the index tasks by `id`. Surface, in the Standing block, anything the index and the live state disagree on (index says `in_progress` but no lock; an orphan branch with no index entry) — but **route hygiene to `/sitrep`**: name the discrepancy, then say *"run `/sitrep` for the full execution-state survey and cleanup routing"*. Do not attempt cleanup; do not re-derive `/sitrep`'s classification table here.

**Also read the payload's `review_batches` array** and upgrade the batch rows Step 1 already built. The flag adds **depth, not breadth**: it carries cells the base path cannot compute, on a **subset** of the rows Step 1 built. The payload filters to `Pending` / `In Progress`, so a `Review Ready` row stays exactly as Step 1 built it — **the base path is the broader view, and the two halves do not cover the same batches.** Saying they do drops the one live status that needs a human from the enriched half without saying so. Per batch the payload carries `batch_number`, `title`, `md_status`, `branch`, `has_lock`, `has_branch`, `has_flag`, `flag_reason`, `has_triage_record`, `triaged_verdict`, `triaged_tasks`, `total_tasks`, `doc_worked_tasks`, `notes`, plus:

- **`state`** — one of `pending (not claimed)`, `claimed, no branch`, `empty batch`, `in progress`, `ready for /review-close`. **Every one of these needs git** (branch existence, the main-repo lock dir, and `Doc-Work:` trailers on `git log main..<branch>` — *not* `[x]` checkboxes), which is why the base path cannot produce it and must not pretend to.
- **`next_action`** — a prose sentence, e.g. `"/triage will classify (then /auto-fix or /auto-judge picks it up)"`. **Read it, never print it as a command.** See Step 4's batch actuator rules.

If the survey exits non-zero, print a one-line note that the survey overlay was skipped and continue with the index-only view — including the base-path batch rows, which do not depend on it.

### Step 2b — Collision annotation (Phase 103)

For each **✅ ready** candidate identified in Step 3 (the agent-executable frontier — not blocked, on-hold, or in-flight tasks), ask the shared scope-overlap primitive whether its likely file scope collides with any worktree building right now:

```bash
python3 sysop/scripts/scope_overlap.py --json <TASK_ID>
```

Read the JSON `max_verdict` (`likely` / `possible` / `none`), the `overlaps` list (each names the in-flight `task_id` and the `evidence` paths that matched), and `broad_radius_note`. This is the same primitive `/claim-task` Step 2 runs — it infers the candidate's scope from its `## Key files` + `blast_radius` (a *pre-plan guess*) and compares it against each in-flight worktree's **actual** changed set. Cache the result per task id; you'll reuse it in Step 3 (the readiness marker) and Step 4 (the `Run it:` caveat).

**Keep it advisory and bounded:**

- Run it **only for ✅-ready candidates** — a 🔒/⛔/⏸ task can't be batched, so its collision risk is moot until it becomes ready.
- If there is **no work in flight** (Step 2a found no locks/worktrees), skip 2b entirely — nothing to collide with; note it in one line and move on.
- A `none` verdict means *no declared overlap*, **not** *provably safe* (the candidate side is a guess). Never present it as a guarantee.
- If `scope_overlap.py` is missing or its permission rule absent, print the one-line degrade note from the Permission Guard and produce the roadmap **without** collision annotations — the orderings still stand.

## Step 3 — Group the outstanding work by kind

"Outstanding" = every **roadmap task** with `status` in `{open, in_progress}` (skip `done` and `deferred`; count `done` for the Standing block only), **plus every `Pending`, `In Progress` and `Review Ready` review batch** from Step 1 — all three of the statuses Step 1 surveyed, not the two the `--in-flight` payload reaches. **`Review Ready` is the one that must not be dropped here:** the tracker calls it *"the one status that needs someone to act"*, so excluding it hides the most actionable work in the project from the strategy view — this skill's own reported defect, one layer in.

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

### Review batches are their own kind

Batches do **not** go through the prefix table — they have no task ID, and you must not invent one. (`BATCH-<N>` exists only as a lock filename. `claim_task.sh` refuses an id of that shape on its `--entry-state` and `--release` paths — **but not on the primary claim path, which will happily create a worktree and mint the lock** — so minting one here would manufacture a value other skills are already unable to reject.) Give them a fixed `Review batches` group, listed after the prefix-derived kinds.

The readiness flags do not apply either — a batch has no `user_action`, `on_hold_until` or `depends_on`. Use this instead, per batch:

| Cell | Base path | `--in-flight` adds |
|---|---|---|
| identity | `Batch <N> — <title>` | — |
| status | `` `Pending` ``, `` `In Progress` `` or `` `Review Ready` `` from the header — all three live statuses reach this column | `state` (the live classification), on the two the payload reaches |
| routing | `⚑ flagged: <reason>` from `> **Flag:**`, or `✓ triaged <verdict>` from `> **Triaged:**`, or `untriaged` when neither is present | `has_lock` / `has_branch` reality |
| size | count lines matching `- [<state>] **TASK-<n>**:` — **three** states (` `, `/`, `x`; `[/]` is "in progress"), and the **bold id plus colon are required**, because that is the shape the survey counts. A bare `- [ ]` sub-checkbox inside a task's remediation prose is *not* a task; counting it makes this cell disagree with the `--in-flight` cell beside it. Add the severity mix where the findings carry one | `doc_worked_tasks` / `total_tasks` progress |

**An untriaged `Pending` batch is the one to surface hardest.** It has been through no classification at all, so nothing downstream is going to pick it up on its own — and it is the shape that produced the reported failure, where two flagged batches carrying security findings sat a week while the strategy view reported neither.

## Step 4 — Propose 1–4 orderings of attack

This is the skill's distinctive output: not one "correct" order, but the **genuinely different paths** through the ready + soon-ready work, each with the trade-off that makes it the right call. Compute them from the schema signals; present **only the orderings that are materially different for this queue** — never pad to the maximum. Three are task-shaped and the fourth is queue-shaped (**drain the review queue**, below); a queue with no outstanding batches simply drops it, exactly as unblock-the-human-first drops when nothing is `user_action`.

- **Unblock-the-human-first** — lead with every 🔒 `user_action: true` task so the human clears credentials/console/domain setup in one sitting while agents work the rest in parallel. **Prefer when** ≥1 `user_action` task gates downstream work — clearing it early converts a serial stall into parallel progress. **Name the mechanism when you say this**: the human clears the flag with `python3 sysop/scripts/clear_user_action.py <TASK-ID>` once the step is done, and the task rejoins the agent-executable frontier. Before Phase 237 this sentence promised a clearing that nothing implemented, so the ordering led with a task that had nothing left to unblock (`Q-314`). Drop this ordering entirely if the queue has no `user_action` tasks.
- **Foundation-first** — a topological order over `depends_on`, breaking ties toward higher `blast_radius` (`architectural` / `cross-module`) and higher *unlock count* (how many other open tasks list this one in their `depends_on`; where `blast_radius` is absent, tie-break on unlock count then `effort` **ascending**, matching ship-fast's direction — the direction was previously unstated here, leaving the tie-break genuinely ambiguous). **Prefer when** the queue has real dependency chains or shared-infrastructure tasks — it builds the base before the things that sit on it and minimizes rework. Collapse into ship-fast when there are no dependencies and nothing architectural. **Cycle guard:** `depends_on` is meant to be acyclic, but `validate_tasks.py` checks only reference integrity — it does *not* detect cycles, so a fully-valid `index.yml` can still contain one (A→B→A). Check for a cycle before ordering; if you find one, do **not** emit a topological order (it's undefined and would mislead) — surface it as a data defect (*"`depends_on` cycle A↔B — the index is internally inconsistent; fix it or route to the human"*) and order only the acyclic remainder.
- **Ship-fast** — lowest `effort` first (and, where `blast_radius` is present, smallest surface first) among tasks with no unmet deps, to land a visible win and build momentum. **Prefer when** the priority is a demo, a morale/momentum beat, or validating the pipeline end-to-end before investing in foundations. Flag the cost: cheap-first can defer an architectural task whose late arrival forces rework — say so when that risk is real in this queue.
- **Drain the review queue** — outstanding review batches, oldest-flagged first, then untriaged, then triaged-`auto`. This is the one queue-shaped ordering: it ranks batches against each other rather than tasks against each other. **Prefer when** flagged or untriaged batches have aged, when a batch carries security findings, or when the roadmap frontier is blocked and the batch queue is not. Drop it entirely when no batch is outstanding. Its cost is the mirror of ship-fast's: draining review work defers feature work, and a batch that has aged is usually aged *because* someone judged it lower value — say so rather than presenting age alone as urgency.

For each ordering you present: the first ~3–5 task IDs in that order, a one-sentence rationale, the "prefer when" condition — and a copy-pasteable **`Run it:`** actuator line built from the ordering's leading ✅-ready IDs: `/auto-build <ready IDs>` when two or more lead (list them in the ordering's sequence for readability — `/auto-build` re-sorts internally, so argument order carries no scheduling weight), `/claim-task <ID>` when only one does. Include only ✅-ready IDs (🔒/⛔/⏸ tasks can't be batched — `/auto-build` would just report them excluded); when a 🔒 task leads the ordering, name it as the human's move and hand the agent-ready remainder to `/auto-build`. The line is a handoff, not a guarantee — `/auto-build` re-applies its own eligibility filters and K=12/N ceilings to the IDs, reports any it can't batch with per-ID reasons, and still stops at its own confirmation gate. Where a recorded decision in `tasks/decisions.md` constrains the order (an explicit sequencing call), honor it and cite the decision rather than proposing an order that contradicts it.

### Where review batches sit in an ordering, and how to actuate them

**Rank batches alongside tasks, roadmap-first on ties.** The *precedence* matches `/next-task`'s default mode (a claimable roadmap task wins; otherwise the next pending batch). The **populations differ, and that is not a bug to fix here**: `/next-task` surfaces only `Pending` batches, while `/roadmap` also carries `In Progress` and `Review Ready` ones, because a survey should show work that is underway or waiting on a human, and a resolver should not hand you a batch someone else claimed. It deliberately differs from `/sitrep`, whose cascade puts batches first — say which you are following when you present an ordering that contradicts a `/sitrep` recommendation the human has already seen.

A batch's weight in an ordering comes from its routing cell, not from `effort`/`blast_radius` (which it does not have): an **untriaged `Pending`** batch is unowned work that nothing will pick up on its own; a **flagged** batch is waiting on a human judgment call; a **triaged `auto`** batch is already routable and cheap to drain. Where a batch carries security findings, say so in the ordering's rationale — that is precisely the signal this skill exists to surface.

**A `Review Ready` batch outranks all three, and it is the one case where the routing cell must not decide.** It is past being worked and is waiting on a human, so the tracker calls it *"the one status that needs someone to act"* — it belongs at the head of a *drain-the-review-queue* ordering, not sorted by triage state. **Do not route it by its routing cell:** an untriaged `Review Ready` batch is not unowned work, and sending it to `/triage` re-triages something already reviewed. It is also invisible to `--in-flight`, so it never carries a survey `state` and can never present as `ready for /review-close` — **read its status from the `review_tasks.md` header, not from the payload**, and say the row could not be enriched.

**Batch actuators, and the grammar is load-bearing:**

| Batch state | `Run it:` line |
|---|---|
| triaged `auto` | `/auto-fix --batches <N>` |
| flagged / triaged `flag` | `/auto-judge --batches <N>` |
| untriaged — `Pending` or `In Progress`, **never `Review Ready`** (see the row below) | `/triage` — **no batch argument exists**; name the batch in prose |
| ready for `/review-close` | `/review-close` — **no batch argument exists**; run it on the batch's branch |
| header status `Review Ready` | `/review-close` — **no batch argument exists**; run it on the batch's branch. Keyed on the **header**, because this batch never reaches the payload and so never carries the survey `state` the row above matches on |

**Never write `/auto-fix <N>` or `/auto-judge <N>`.** A bare integer is those skills' **concurrency cap**, not a batch selector — `/auto-fix 583` requests a 583-way concurrency, and both skills say so in their own Step 0 (*"a bare integer is already this skill's concurrency cap"*). The selector is the `--batches` flag, which accepts comma-separated integers and inclusive ranges (`--batches 563,570,580-584`).

**Never emit the survey's `next_action` string as a `Run it:` line.** It is descriptive prose (`"/auto-fix will pick this up — triaged auto"`), and `Run it:` is contractually copy-pasteable. Translate it through the table above, or omit the line and say what the batch is waiting on.

**Collision caveat on `Run it:` lines (only under `--in-flight`, from Step 2b).** If any ID in a `Run it:` line carries a 💥 marker, append a one-line caveat naming the collision — e.g. `Run it: /auto-build FEAT-A FEAT-B  (heads up: FEAT-A 💥 overlaps in-flight TECH-B on src/api/routes.py — expect a /review-close conflict, or drop it and batch the rest)`. It stays a handoff, not a veto: the human may still want the overlapping task (worktree isolation makes the conflict recoverable rework, and `/auto-build` re-checks anyway). When *every* ready ID in an ordering is clear, say so in one word (`Run it: /auto-build FEAT-A FEAT-B  (both clear of in-flight work)`) — the absence of a collision is itself useful signal for what to batch next.

**Honesty about the ceiling.** These orderings are heuristics over the fields; the human's context — an external deadline, what they have energy for today, a stakeholder demo — legitimately overrides any of them. Present the trade-offs; do not pretend one path is objectively correct. When a deadline picks a *subset*, hand it straight to `/auto-build <IDs>`; when it genuinely re-prioritizes the *lane*, reshape `phases:` via `/intake` re-entry and flip `current_focus` instead — don't restructure phases to steer one batch.

## Step 5 — Surface the report and offer the next move

Print the report in the shape below, then offer **one** routing move — but do not actuate without explicit confirmation (the read-only contract: `/roadmap` informs; the human or the routed skill acts).

**The cascade is ordered, and the first bullet is the one that had to be added.** An earlier revision led with "ready-now tasks exist", which fires on essentially every real queue — so on the 195-task queue that produced this skill's reported failure, the flagged security batch could be *described* in the report and still never be the move the human was offered. Improving visibility without moving the routing decision would have been half a fix.

- A batch carries **security findings**, or a flagged/untriaged batch has aged past the roadmap work you would otherwise recommend → route to it **first**, naming why it outranks: `/triage` if untriaged, `/auto-judge --batches <N>` if flagged, `/auto-fix --batches <N>` if triaged `auto`. Roadmap-first governs *ties*; this is not a tie, and saying so is the whole reason this skill now reads the second queue.
- Ready-now tasks exist → offer `/next-task` (see the single next unit) or `/auto-build` (batch the ready frontier) or `/auto-build <IDs>` (batch the exact subset an ordering proposes — its `Run it:` line) or `/claim-task <ID>` (start a specific one you chose from an ordering).
- Only 🔒 / ⛔ / ⏸ tasks remain (nothing ready) but review batches are outstanding → route to the batch queue: `/triage` for untriaged batches, `/auto-fix --batches <N>` or `/auto-judge --batches <N>` for triaged ones. A blocked roadmap frontier does not mean there is nothing to do.
- Only 🔒 / ⛔ / ⏸ tasks remain and no batches are outstanding → name what unblocks the frontier (usually a `user_action` task the human must do) rather than routing to a build skill.
- Queue empty or a phase too coarse to sequence → `/intake`.
- Want live execution detail or discrepancy cleanup → `/sitrep`.

Close with one line: `Read-only strategy view — no state changed. Actuators: /intake, /claim-task, /auto-build, /next-task, /triage, /auto-fix, /auto-judge, /sitrep.`

## Output shape (reference)

```
## Roadmap — <project>

STANDING
Phase <K> of <M> ("<current-focus phase title>") is current-focus.
Status: <N> done · <O> open · <P> in flight · <D> deferred     (status buckets — these partition the queue)
Of the open + in-flight: <R> 🔒 need you · <S> ⛔ dep-blocked · <T> ⏸ on hold · <U> ✅ ready     (readiness — orthogonal, may overlap)
Review batches: <B> outstanding (<F> flagged · <G> untriaged)      (omit this line entirely when review_tasks.md is absent)
v1 done: <one line from vision.md, or "no vision.md — run /intake to author one">

OUTSTANDING WORK — by kind      (💥 markers appear only under --in-flight — see below)
Feature development
  FEAT-LEDGER-IMPORT   Import OFX statements     Medium / single-module   ✅ ready
  FEAT-DASHBOARD       Spending dashboard        High / cross-module      ⛔ needs FEAT-LEDGER-IMPORT
Data-ops
  DATA-VENDOR-SEED     Seed vendor catalog       Low / single-file        🔒 you: obtain vendor list
Technical / infrastructure
  TECH-DB-BOOTSTRAP    Schema + migrations       High / architectural     ✅ ready
Review batches
  Batch 583   LLM and renderer abuse resistance    Pending   ⚑ flagged: needs a human call    4 tasks (3 security)
  Batch 567   Backend deterministic utilities      Pending   ✓ triaged auto                   5 tasks

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

4. Drain the review queue   → Batch 583, Batch 567 …
   Batch 583 carries three security findings and has sat flagged for a week. Roadmap-first
   puts DATA-VENDOR-SEED ahead of it on ties, but security findings are not a tie — this
   ordering exists to say so out loud rather than let the batch place fourth by default.
   Prefer when: flagged or untriaged batches have aged, or when the roadmap frontier is blocked.
   Run it: /auto-judge --batches 583   (flagged — needs the judgment pass; then /auto-fix --batches 567)

RECOMMENDED NEXT
Nothing is blocked on an agent, but DATA-VENDOR-SEED is blocked on you. Clear it, then /auto-build the ready frontier.
Note: /sitrep will route you to Batch 583 first — its cascade is batch-first. Either order is defensible.

Read-only strategy view — no state changed. Actuators: /intake, /claim-task, /auto-build, /next-task, /triage, /auto-fix, /auto-judge, /sitrep.
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
- **Portability, and what it costs.** The base path is pure file reads (`Read` on four files — three under `tasks/`, plus `review_tasks.md` at the repo root) — it runs on any agent, including bash-installer/non-Claude consumers, with no git or script dependency. `--in-flight` is the only path that needs `git` + `sysop/scripts/sitrep_survey.py`, and it degrades gracefully to the index-only view when they're absent. **The price is stated in Step 1 rather than hidden:** without git the base path cannot resolve the main checkout, so in a worktree it reads that branch's queue while `--in-flight` reads main's. Shipping the resolution would mean shipping `git rev-parse --git-common-dir`, which buys accuracy in a minority case and costs the portability property outright — so the skill declares the divergence instead of pretending it away.
- **Why the batch read is on the base path, not behind `--in-flight` (Phase 199).** The reported failure happened on a **default** run, so fixing it only under an off-by-default flag would not have fixed it. The batch queue's status also lives in the tracker itself rather than in git or lock state, which makes it more base-path-worthy than the execution overlay: `md_status`, the routing metadata and the task counts are all plain file content. What `--in-flight` adds is the half that genuinely needs git — `state`, lock/branch reality, and `Doc-Work:` progress.
- **What this does not do.** It does not give the two queues a shared ID space. `surfaced_by` still cannot record "this roadmap task exists because Batch 584 found something" — `validate_tasks.py` allows external refs for `whitelist` alone — so review→roadmap provenance stays in prose that no tool reads. That is filed separately; this skill deliberately does not mint a `BATCH-<N>` task ID to work around it.
- **Loop mode does not get this.** `/roadmap` is excluded from `--mode loop` installs, which is the one mode whose *only* queue is `review_tasks.md`. So the skill that most needs a batch-aware strategy view is unavailable exactly where batches are all there is. Left as-is deliberately — loop mode is a deliberately small surface — but worth knowing before reading this fix as complete.
- **Wired (Phase 73a):** `/sitrep`'s `RECOMMENDED NEXT` cascade (Phase 44) routes to `/roadmap` at priority **7a** when the queue is deeper than one `/auto-build` batch (> 4 open roadmap tasks) — a strategy view before batch execution; a shallower queue (1–4, fits one batch) keeps the `/auto-build` recommendation (7b). See `sitrep/SKILL.md` § Recommendation routing rules.
- **Executable orderings (Phase 97).** `/auto-build` accepts an explicit task-ID subset (`/auto-build FEAT-A TECH-B`), so each ordering closes with a `Run it:` actuator line — the orderings are handoffs, not just advice. `/auto-build` re-applies its own filters and ceilings to the IDs and reports any it can't batch; the line never pre-commits the human past `/auto-build`'s own confirmation gate, so `/roadmap`'s read-only contract is intact.
- **Collision annotation (Phase 103).** Under `--in-flight`, ready candidates and `Run it:` lines are annotated by collision risk against the worktrees building right now, via the shared `sysop/scripts/scope_overlap.py` primitive (the same one `/claim-task` Step 2 runs, and `/auto-build`'s Leg B). It's the read-only, portfolio-level companion to `/claim-task`'s single-task advisory — "of everything I *could* batch, which won't fight what's already running?" — and answers the "surface me better tasks to batch" need directly. Advisory only: a 💥 marker warns, it never removes a task from an ordering (the read-only contract holds, and overlap is recoverable rework). The base path (no `--in-flight`) stays pure file reads with no git/script dependency, so portability is unchanged.

## Deferred features

- **`--json`** — structured emit for orchestrator consumption. Reserved; the text report is the only output today.
- **`--phase N`** — scope the grouping + orderings to a single phase for very deep queues. Deferred; today's report covers all outstanding phases and the human reads the phase they care about.
