---
name: intake
description: The planning front door — turn a brain-dump or a written brief into a populated, validated task queue. Interactive: brain-dump → playback → sounding-board → phases → priority → emit a phase-one slice. Re-enterable to deepen later phases as they come into focus, or to onboard an existing project that has a queue but no vision/decisions intent layer.
argument-hint: "[brief text, or a path to a brief file — optional]"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning -->

The planning front door. `/intake` turns a brain-dump or a written brief into a **populated, validated** task queue — the one thing no other Sysop skill does. `install.sh` seeds an *empty* scaffold; `/codebase-review` and `/security-audit` write to a separate `review_tasks.md`; every other lifecycle skill (`/next-task`, `/claim-task`, `/document-work`, `/review-close`) operates on a queue that already has entries. Before `/intake`, the first real task was authored by hand.

`/intake` is also Sysop's **first instructional skill** — it runs a conversation, not a procedure — and its **first bulk task-writer**: it owns its write path into `tasks/index.yml` + the per-task bodies, anchored on `sysop/scripts/validate_tasks.py` as its one structural gate.

> **Not `/plan-review`.** `/plan-review` takes an *existing* ad-hoc plan and runs an adversarial pass on it. `/intake` builds the queue from nothing. Different front doors: use `/intake` when there is no queue yet (or a new phase needs decomposing); use `/plan-review` when you already have a plan and want it stress-tested.

## What this skill produces

Three durable artifacts, all **consumer-owned** — authored by `/intake` and yours to commit; none is a Sysop-managed path. `install.sh` seeds an empty `index.yml` once and skips it on every `--update`; `vision.md` and `decisions.md` the installer never creates *at all*, so there is simply nothing for an update to overwrite (the protection is by absence, not by a skip-if-exists guard — don't assume one exists).

1. **`tasks/vision.md`** — the durable *why + what*. Stable across sessions; the anchor every phase and decision must trace back to.
2. **`tasks/decisions.md`** — the *technical-decisions record*: stack/schema/sequencing calls and their rationale. This is the **planning-side analog of the convention map** — a re-invoked `/intake` checks new decisions against what's already committed here.
3. **`tasks/index.yml` + `tasks/open/<TASK-ID>.md` bodies** — an actionable phase-one backlog, plus the later phases kept deliberately coarse.

It leaves all of this **uncommitted** — see § Step 8.

## The intent layer (coherence = detection, not prevention)

`tasks/vision.md` and `tasks/decisions.md` are the intent layer. They exist so that planning has a durable memory: a decision made in session 1 is still binding in session 4, and `/intake` can *detect* when new work contradicts or has drifted from it. The discipline mirrors the convention map exactly — the map doesn't *prevent* you from writing non-conforming code, it gives `/codebase-review` something to detect drift against. Same here: the intent layer doesn't prevent a contradictory decision, it lets `/intake` surface the contradiction so a human resolves it. **Detection is the job; the conversation and the human are the resolution.**

## Step 0 — Orient (fresh · re-entry · adopting)

Read `tasks/vision.md`, `tasks/decisions.md`, **and** `tasks/index.yml` up front — the classification keys on all three, not just the intent layer. Then branch:

- **Neither intent file exists AND the queue empty** (`index.yml` is unwritten or has `tasks: []`) → **fresh project.** You will author vision + decisions from scratch this session; proceed to Step 1. One guard: if the working tree shows an existing codebase — a light *"is there real source beyond the Sysop scaffold, or a README describing a shipped product?"* check, **not** the deferred code-reconstruction of the note below — don't assume greenfield; ask *"brand-new project, or an existing one adopting Sysop?"* first. If it's an existing project, use the **adopting** offer below to establish the intent layer grounded in what already exists — or hand off to `/onboard` when they want the systematic path (evidence archaeology and/or importing an existing roadmap/issue backlog) — *then* decompose the first slice via Step 1 onward.

- **Either intent file present** (`vision.md` and/or `decisions.md`) → **re-entry** (you're deepening an existing plan, not starting it). Load what exists as the *committed intent* — and if exactly one of the two is missing, author only that missing file this session, **never overwriting the one that already exists.** Then do two things before adding anything new:
  1. **Coherence check.** As new decisions emerge this session, check each against `tasks/decisions.md`. A contradiction (this session reaches for SQLite; decision **D3** committed Postgres) is **not** silently resolved either way — surface it: *"This contradicts D3 (Postgres, chosen because …). Either D3 is superseded — and I'll record the supersession with its reason — or this idea bends to fit D3."* Let the human and the conversation resolve it.
  2. **Staleness sweep.** If `tasks/vision.md` or a recorded decision has changed since the existing roadmap was derived, the already-emitted tasks may now be wrong. Flag the affected `open` / `in_progress` tasks for re-check — the same discipline as a stale convention-map entry invalidating code that cited it. **List them and ask; do not silently rewrite them.**

- **Neither intent file exists BUT the queue already lists tasks** → **adopting an existing project.** A mature project is onboarding to Sysop. Do **not** open with the greenfield "tell me everything" prompt — there is already a product and a queue. Instead:
  1. **Name what you see** — e.g. *"You have <N> tasks across <M> phases but no `vision.md` / `decisions.md`. Those are the intent layer Sysop checks new work against — contradiction and staleness detection. Establishing them is optional, and pays off the moment you plan the next slice."*
  2. **Offer, with the trade-off honest.** *Pros:* a durable why/what that every future `/intake` and `/roadmap` reads against; the coherence/staleness detection you don't get without it. *Cons:* a short session of retroactive documentation now, some of which — for a product that already exists — will feel like writing down the obvious. Ask whether to establish them now or skip straight to decomposing new work (if they skip, run a **scoped** brain-dump for just the new slice — not the greenfield "tell me everything" — then Steps 5–8 as re-entry).
  3. **If yes, seed from evidence the human hands you.** They may point you at (or paste) an existing README, design doc, or roadmap, and you draft `vision.md` / `decisions.md` *from it* — marking every inference as an inference to correct (the Step 2 playback discipline; an observed stack choice is fact, its *rationale* is a guess until confirmed). Absent a supplied doc, establish them by interview grounded in the existing queue — or, when they want more than the light interview, hand off to `/onboard` (see the note below). Then **rejoin re-entry**: run the coherence check and staleness sweep above — a vision you just wrote is a sharp lens for spotting queued tasks that no longer serve it.

> **The systematic version lives in `/onboard`:** consent-gated evidence archaeology (a bounded read of README/docs/manifests/git history that *drafts* the intent layer under a fabrication guard — inferred rationales are confirmed, never asserted) and backlog import (a roadmap file, `TODO.md`, or open GitHub issues → `index.yml` + bodies, provenance-marked `surfaced_by: [imported]`). Offer it when the human wants more than the light interview above. `/intake` itself still never scans your code or imports tasks on its own; external trackers (Jira/Linear/Notion) remain a planned separate module.

Whichever branch: you must not clobber or duplicate existing `index.yml` entries when you emit (see Step 7). If `$ARGUMENTS` names a file path or carries inline brief text, treat it as the opening brain-dump (fresh) or the seed document (adopting) and fold it in rather than asking the human to re-type it.

## Step 1 — Brain-dump

Invite one rich, unstructured dump: *"Tell me everything — the problem, who it's for, what you picture it doing, any constraints or things you already know you want. Don't organize it; I will."*

**Take the whole dump in one pass.** Do **not** interrogate field-by-field or fire a volley of multiple-choice questions — that turns planning into a form. Let the human talk; you do the structuring. Only ask a follow-up when something load-bearing is genuinely missing (who the user is, what "done" looks like for a first version) and you cannot reasonably infer it.

**Discovery-stage guard.** If the dump reveals the human hasn't actually decided what to build — several candidate ideas still competing, or the live question is *"is this worth doing?"* rather than *"how do we build it?"* — say so plainly before decomposing anything: Sysop's on-ramp is a committed idea, and discovery (divergent ideation, market research, validating that the thing is worth building) sits upstream of it, out of scope on purpose (see Step 4, boundary 1). Do **not** run a pretend market-research interview, and do not quietly decompose the strongest-sounding candidate — a clean task queue for an idea nobody has committed to is diligence theater, not planning. Name the boundary, then offer to resume the moment they can state the one thing they're building.

## Step 2 — Playback

Reflect your understanding back as a compact structured summary — problem, user, the shape of the thing, the constraints you heard, and anything you're **inferring** (mark inferences as inferences so they're easy to correct). Playback is where misunderstandings get caught cheaply, before they're baked into a roadmap. Invite correction in prose: *"Fix anything I got wrong or missed."*

When the playback stabilizes, draft `tasks/vision.md` (see § Artifact shapes) and confirm it captures the durable intent.

## Step 3 — Sounding-board

You are a technical sounding-board, **not** a stenographer. Have opinions on stack, schema, and sequencing — say *"I'd reach for X over Y here, because Z,"* not *"what database would you like?"* The human came for judgment, not transcription.

But the instant you've made a strong call, **argue the other side of it before it hardens into the plan.** A decision recorded without its strongest counter-argument considered is one you'll relitigate at implementation time, when reversing it is expensive. At the moment you're about to commit a stack/schema/sequencing decision to `tasks/decisions.md`, run this self-check:

- **What would make this the wrong call in three months?** If you can't name it, you haven't stress-tested it.
- **Is this the simplest thing that delivers the v1 value — or the most interesting thing?** Resist the second.
- **Am I choosing this because it fits *this* problem, or because it's what I reach for by habit / what's currently fashionable?**

Do **NOT** accept these rationalizations for skipping the counter-argument:

- *"The human said so."* They hired you for judgment; a decision they'll regret is still yours to flag.
- *"It's the obvious choice."* Obvious choices are exactly the ones worth a sentence of stress-testing — they're the ones nobody questions until they hurt.
- *"We can change it later."* Schema and sequencing decisions are the expensive-to-reverse ones; that's *why* they get the counter-argument now.

## Step 4 — Boundary discipline

Two hard boundaries on this whole session:

1. **Never adjudicate venture worth.** You judge whether the *plan* is sound and the *decomposition* is clean — never whether the idea is worth building, will find a market, or is a good business. If asked *"is this a good idea?"*, redirect to what you can actually judge: *"I can't tell you whether it'll work as a business — but I can tell you whether the plan to build it hangs together, and here's where it's weak."* Sysop plans software; it does not pick winners.
2. **Self-check against hype drift.** Scope inflates when something sounds exciting. Before adding a phase or recording a decision, ask: *does this serve the v1 definition-of-done in `tasks/vision.md`, or did it get pulled in because it's a trendy capability* (an LLM dropped in here, a real-time feed there, a plugin system nobody asked for)? If it doesn't trace to the vision, it's a later-phase candidate **at most** — or an explicit non-goal. **Name the temptation out loud** rather than quietly acting on it: *"An LLM summarizer would be cool here, but nothing in the v1 vision needs it — parking it as a phase-3 maybe, not phase-1 scope."*

## Step 5 — Phases & decisions

Derive a phase plan from the stabilized vision. A phase is a coherent slice of value, not a calendar bucket.

- **Record each load-bearing technical decision** to `tasks/decisions.md` as you make it — with its rationale and, where relevant, what it rules out (see § Artifact shapes). This is the durable record the next `/intake` checks against.
- **Keep later phases COARSE.** Phase one gets decomposed into real tasks (Step 6). Every phase after it gets a title, a one-line intent, and a rough effort — **not** a task list. Resist decomposing the uncommitted future: phase-three tasks written today will be wrong by the time phase three arrives, and rewriting them is waste dressed up as planning. `/intake` is re-enterable precisely so a *later* pass can decompose the next slice against what you actually learned shipping the current one.

## Step 6 — Priority & slice (decompose phase one)

Choose the current-focus phase (usually phase one on a fresh project) and decompose **only that phase** into atomic tasks.

> **Decomposition rubric.** The calibrated rubric for sizing and slicing — atomicity, `effort` × `blast_radius`, `depends_on`, `user_action`, plus the anti-pattern smells — lives at `.claude/skills/_shared/decomposition-rubric.md`. **Read it before you slice**; it's the planning-side analog of the adversarial-review rubric, calibrated from real task queues. The load-bearing tests, in brief:
>
> - **Atomic?** State the done-condition in **one falsifiable sentence**. If it needs a bulleted list of independent outcomes, it's an epic — split it. The unit is one coherent *reviewable surface*: split the incoherent, but lump the genuinely-cohesive (and don't manufacture dependencies between independent siblings to make a phase "look" structured).
> - **Sized?** `effort` (work/risk) and `blast_radius` (surface touched) are **independent** — a risky refactor of one file is `High / single-file`. Author **both** on every emitted task even at `schema_version: 1` (the validator enforces the enum when present; it's free signal for `/next-task` and `/auto-build`). See the rubric's calibration table.
> - **Ordered?** `depends_on` is physical impossibility — "can B start before A finishes?" — not topical relatedness. A shared file is a *body convention* ("whichever ships first creates it"), not an edge. Use `surfaced_by` for provenance.
> - **Blocked?** `user_action: true` is a human-only *action* (cloud console, credentials, private knowledge only you have), and write `## User ops (do these first)` when true. It is **not** "I'm unsure how to build this" (a planning gap — resolve it now) and **not** "this must wait" (that's `on_hold_until`).
>
> One rule worth lifting to the front: for any capability split across several tasks, **exactly one task's done-condition must own the user-visible wire-up** — otherwise the feature ships as a set of "done" parts that don't connect.

Keep the interaction to **a few rich turns, not micro multiple-choice rounds.** Reserve `AskUserQuestion` for a genuine load-bearing fork the human hasn't already decided (e.g., two viable sequencings with a real trade-off). Everything else is conversational prose — you propose the decomposition, the human corrects it.

## Step 7 — Emit the slice (the write path)

You own this write path. Produce:

1. **Per-task bodies** — one `tasks/open/<TASK-ID>.md` per emitted task, via the `Write` tool, following the body shape in `tasks/schema.md` § Per-task body. The first heading **must** be `# <TASK-ID>` (validator-enforced). Sections: `## Context`, `## Requirements`, `## Key files`, and `## User ops (do these first)` when `user_action: true`. **Do not** write a `## Test decision` section — that's recorded at `/claim-task` plan time, not here.
2. **`tasks/index.yml`** — the index entries:
   - **Fresh project** (the seeded index has `tasks: []`) → author the complete file with the `Write` tool. Keep `schema_version: 1` at the top (the validator hard-errors without it). Required per-task fields: `id`, `title`, `phase`, `status: open`, `effort`, `blast_radius`, `user_action`, `depends_on: []`, `surfaced_by: []`, `body: open/<TASK-ID>.md`. Required `phases:` shape: each phase has `number`, `title`, `status` (`in_progress` for the current-focus phase, `planned` for the coarse later ones), `current_focus` — and **exactly one** phase has `current_focus: true`. Skeleton:

     ```yaml
     schema_version: 1

     phases:
       - number: 1
         title: "<phase-one title>"
         status: in_progress
         current_focus: true
       - number: 2
         title: "<coarse later phase — title + intent only>"
         status: planned
         current_focus: false

     tasks:
       - id: FEAT-EXAMPLE
         title: "<one-line task title>"
         phase: 1
         status: open
         effort: Medium
         blast_radius: single-module
         user_action: false
         depends_on: []
         surfaced_by: []
         body: open/FEAT-EXAMPLE.md
     ```
   - **Re-entry** (the index already lists tasks) → **append** with the `Edit` tool — add the new `tasks:` and `phases:` entries, and never rewrite or drop an existing entry or its `sprint_note` block scalar. If you're introducing a new current-focus phase, flip the previous `current_focus: true` to `false` in the same pass (exactly-one is a validator invariant). **Refuse to reuse an existing task `id`** — surface the collision to the human instead of overwriting.
3. **`tasks/vision.md`** (if not already written in Step 2) and **`tasks/decisions.md`** — see § Artifact shapes.

ID format: `^[A-Z][A-Z0-9-]{2,80}$` (e.g. `FEAT-LEDGER-IMPORT`, `TECH-DB-BOOTSTRAP`). Pick a prefix vocabulary that fits the project (`FEAT-`, `TECH-`, `DATA-`, `UX-`, `FIX-`) and stay consistent — downstream skills discover prefixes from the index. Every task's `phase:` must match a `number:` you actually defined under `phases:` (the validator rejects a task pointing at an undefined phase) — so emit the phase entry before the tasks that reference it.

## Step 8 — Validate (floor), then hand off (ceiling)

`/intake` is done in **two legs, and the floor is not the ceiling.**

**Floor (mechanical).** Run the validator and make it pass:

```bash
.venv/bin/python3 sysop/scripts/validate_tasks.py
```

(Use bare `python3 sysop/scripts/validate_tasks.py` if the project has no `.venv`.) Exit 0 proves the queue is *well-formed* — IDs match the pattern, every body exists with the right first heading, references resolve, exactly one phase is current-focus. If it fails, fix the data and re-run; **do not** hand off on a red validator. What the validator **cannot** judge is whether the decomposition is any *good*: a single 40-hour `FEAT-EVERYTHING` task passes it cleanly.

**Ceiling (judgment).** Print a scannable summary — the phases, the emitted phase-one tasks with `effort` / `blast_radius`, and a pointer to two or three sample bodies — and hand off:

```
## Intake complete — review before committing

Wrote (uncommitted):
- tasks/vision.md, tasks/decisions.md
- tasks/index.yml  (<N> tasks across <M> phases; phase <K> is current-focus)
- tasks/open/<TASK-ID>.md × <N>

Validator: PASS (the floor — well-formedness only).

Your turn (the ceiling): read the roadmap — the task queue in `tasks/index.yml`
(run `/roadmap` for a rendered view, or see `tasks/README.md` for the queue
format) — and a sample of bodies in `tasks/open/`. Are the tasks atomic? Are
the efforts plausible? Does the sequencing hold? Anything load-bearing missing?
When it reads right, commit it — that commit is your sign-off on the
decomposition, which the validator can't give you.

Hit any Sysop friction while planning (a confusing step, a rough edge)? Note it
in SYSOP_ISSUES.md at the repo root — /report-issues sends the keepers upstream.
```

The closing friction line is part of the completion summary, not a new turn — `/intake` is judgment-heavy and its turn budget is precious, so this is a one-line nudge in the message the skill already prints, never an extra `AskUserQuestion`.

**Leave everything uncommitted.** The commit is the human's sign-off on the *ceiling*; `/intake` stops at the floor. Do not `git add`, do not `git commit` — this is deliberate, and it's why `/intake` needs no commit permission rules (see § Permissions).

## Artifact shapes

**`tasks/vision.md`** (authored once when it doesn't yet exist — fresh *or* adopting; revised deliberately on re-entry):

```markdown
# Vision

> Authored by /intake. The durable "why + what." Revise deliberately, not casually —
> phases and decisions trace back here, and /intake checks new work against it.

## Problem
<what's broken or missing for the intended user>

## Users
<who this is for — single user? a team? public?>

## What it does — and deliberately does not
<the shape of the product; explicit non-goals belong here>

## Definition of done for v1
<the smallest thing that delivers the core value>
```

**`tasks/decisions.md`** (created on the first recorded decision; appended thereafter):

```markdown
# Technical decisions

> Authored + appended by /intake. The planning-side analog of the convention map:
> the durable record of stack/schema/sequencing calls, so a re-invoked /intake
> checks new decisions against what's already committed. One entry per decision.

## D1 — <short decision title> (<YYYY-MM-DD>)
**Decision:** <what was chosen>
**Rationale:** <why; which alternatives were weighed and why they lost>
**Rules out:** <what this forecloses, if anything — else "nothing material">
```

When a re-entry supersedes a decision, **don't delete the old entry** — append a new one and note the supersession (`Supersedes D3:` …) so the rationale history survives, exactly as the convention map keeps its promotion provenance.

## Permissions

`/intake` needs **no new permission rules.** It writes via the `Write` / `Edit` tools (file-level, not Bash-gated) and runs only `validate_tasks.py`, which the default `.claude/settings.json` already allows (bare + `.venv/bin/python3` variants). It does not commit, push, or merge. If a consumer's `settings.json` is missing the `validate_tasks.py` allow-rule, the validator step will prompt once under `auto` mode — not silently halt — because a human is present for the whole interactive session.

## Two-leg done, restated

- **Floor:** `validate_tasks.py` exits 0 — the queue is well-formed.
- **Ceiling:** a human reads the roadmap + sample bodies and commits — the decomposition is sound.

`/intake` guarantees the floor and *hands you* the ceiling. It never pretends the floor is the ceiling.

---

> **Prior art.** The brain-dump → playback → sounding-board shape draws on the `interview-me` pattern from Addy Osmani's agent-skills collection (MIT-licensed). Written from scratch for Sysop's intent-layer + task-emission model; no prose copied or paraphrased.
