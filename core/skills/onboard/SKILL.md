---
name: onboard
description: Onboard an existing project into Sysop. Two independent legs, both opt-in — reconstruct the vision/decisions intent layer from in-repo evidence (README, docs, git history) under a strict fabrication guard, and/or import an existing backlog (ROADMAP.md, TODO.md, GitHub issues) into tasks/index.yml with imported provenance. Hands off to /intake re-entry for going-forward planning.
argument-hint: "[path to a roadmap/brief/evidence file, or 'issues' — optional]"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning -->

The mature-project onboarding engine. `/intake` is Sysop's planning front door, but it plans *forward* — a greenfield brain-dump, or the next slice of an already-Sysop'd project. `/onboard` handles the third arrival: **a project that already exists** — code shipped, maybe a roadmap file or an issue tracker full of backlog — adopting Sysop. It does the two things that project needs and `/intake` deliberately doesn't do on its own:

- **Leg A — Reconstruct the intent layer.** Read the repo's own evidence (README, docs, manifests, git history — with consent, bounded) and *draft* `tasks/vision.md` + `tasks/decisions.md` for the human to confirm or correct, instead of interviewing from a blank page.
- **Leg B — Import the backlog.** Convert an existing roadmap file or open GitHub issues into `tasks/index.yml` + per-task bodies — decomposed to the task schema, provenance-marked, dedup'd, validated — so `/next-task`, `/claim-task`, and `/auto-build` work day one.

**The legs are independent.** Run either or both; Step 0 establishes which. Either way `/onboard` ends by handing off to `/intake` re-entry — the coherence check and staleness sweep against the (possibly brand-new) intent layer, and the going-forward decompose loop, stay `/intake`'s job. `/onboard` is the one-time archaeology; `/intake` is the recurring planning loop.

> **Not `/intake`.** `/intake` turns what's *in the human's head* into a queue; `/onboard` turns what's *already in the repo* into Sysop artifacts. If there's no existing product and no existing backlog, you want `/intake`. `/intake` Step 0's adopting branch routes here when systematic reconstruction or import is wanted; the light path (human pastes a doc, `/intake` drafts from it) stays in `/intake`.

## Two rules that govern everything below

**1. Opt-in, always.** Detection and offers are free; **scans and imports happen only after an explicit yes.** Never read the codebase, git history, or issue tracker "to be helpful" before the human has seen *what* you propose to read and agreed. This is both a trust boundary and a token-cost boundary. The shape is always: name what you found → offer → (only on yes) read.

**2. The fabrication guard.** Sysop's discipline is *detect, don't fabricate* — and reconstruction violates it by default unless you hold the line:

- Reading `psycopg` in the manifest is an **observation** — record it at high confidence. *"They chose Postgres because they needed transactional integrity"* is an **inference** — and the `Rationale:` / `Rules out:` fields of a `decisions.md` entry are exactly where a confident-but-wrong hallucination lands. Those fields are load-bearing: every future `/intake` coherence-checks new work against them, so a fabricated rationale corrupts planning forever after.
- **Rule:** record observations as fact; render every inferred *rationale* as a draft explicitly marked `(inferred — confirm or correct)`, and walk each one with the human before writing it. An inference the human hasn't confirmed does not get committed to `decisions.md` as if it were their reasoning.
- **Vision is interview-assisted, not interview-replaced.** Code and docs tell you *what* was built — never *who it's for*, or *where v1's done-line was*. Draft the skeleton from evidence; interview for the intent that only lives in the founder's head.

Do **NOT** accept these rationalizations for skipping the guard:

- *"The README implies it."* The README states what the product does; the *why* behind a technical choice is still your guess until confirmed.
- *"Any reasonable engineer would have chosen X for this reason."* That's **your** rationale. `decisions.md` records **theirs**.
- *"The human can fix it later."* They won't re-read every entry; a plausible fabricated rationale survives precisely because it's plausible. Confirm now, at draft time.

## Step 0 — Orient and pick the legs

Read `tasks/vision.md`, `tasks/decisions.md`, and `tasks/index.yml` (tolerate any of them absent), then establish scope with the human:

- **Intent layer already present** (either file exists) → Leg A is mostly moot: offer only the *missing* file if exactly one is absent (never overwrite the one that exists — same rule as `/intake` re-entry), otherwise skip straight to Leg B.
- **Queue already populated** → Leg B runs in **append + dedup** mode (Step B4); an empty or absent `index.yml` means Leg B authors it fresh.
- **`$ARGUMENTS`**: a file path is treated as the primary evidence document (Leg A) and/or import source (Leg B) — ask which if ambiguous. The literal `issues` pre-selects GitHub issues as the Leg B source.

State the plan in one short block — *"Leg A: draft vision + decisions from <evidence list>. Leg B: import <source>. Proceed?"* — and get the yes before reading anything beyond the three files above. Don't quote an item count here — you'd have to read the source to get one, which is exactly what this yes gates; counts come at B1, after consent.

## Leg A — Reconstruct the intent layer

### Step A1 — Enumerate evidence, then get consent

Build the candidate evidence list **without reading contents yet** — presence checks only (`ls` / glob, not file reads):

| Source | What it's evidence of |
|---|---|
| `README*` | Product shape, audience, install/usage surface |
| `docs/` (depth ≤ 2, prune `node_modules`/`.venv`/`venv`/`.git`/`dist`/`build`) | Design docs, ADRs (`docs/adr/`, `docs/decisions/`), architecture notes |
| `CHANGELOG.md` / `CHANGES.md` | What shipped, in what order |
| Dependency manifests (`package.json`, `pyproject.toml`, `requirements*.txt`, `go.mod`, `Cargo.toml`, `Gemfile`, …) | The stack as chosen — observations for `decisions.md` |
| Existing `CLAUDE.md` / `AGENTS.md` / `CONTRIBUTING.md` | House rules, stated constraints |
| `git log` — recent subjects (~100) + tags (read-only) | Sequencing, naming conventions, release cadence |

Present the actual list found (with sizes for anything large), let the human strike or add entries, and **read only the consented set**. The depth/prune bounds are not optional politeness — an unbounded scan of a mature repo reads the world and buries the signal.

### Step A2 — Draft under the fabrication guard

Draft both files per `/intake` § Artifact shapes (adjust each template's provenance header to name `/onboard` as the drafting skill — don't stamp `Authored by /intake` on files it didn't write):

- **`tasks/vision.md`** — Problem / Users / What it does (and deliberately does not) / Definition of done for v1. Evidence usually fills the *what*; **Users and the v1 done-line are interview questions**, not archaeology — ask them directly rather than guessing. A shipped product's "v1 done" may be behind it; then the question becomes *"what's the done-line for the next major slice?"* — capture that.
- **`tasks/decisions.md`** — the **3–5 load-bearing decisions**, not an exhaustive dig. (A skeleton the human corrects beats an exhaustive archaeology the human rubber-stamps — the fabrication guard scales badly with entry count.) For each: `Decision:` is the observation (high confidence — the manifest says Postgres); `Rationale:` and `Rules out:` are drafts marked `(inferred — confirm or correct)` **unless** an ADR, commit message, or doc states the reasoning explicitly — then cite it (`per docs/adr/0003`).

### Step A3 — Confirm-or-correct, then write

Play the drafts back. Walk **every** `(inferred …)` marker individually — confirm, correct, or delete; do not batch-accept ("all fine?" invites a rubber stamp over the exact fields the guard protects). Then write the files with the `Write` tool — never overwriting an intent file that already exists (Step 0 scoped this). Inferences the human corrected are recorded in their corrected form with the marker removed; inferences the human couldn't adjudicate stay marked `(unconfirmed)` rather than silently promoted to fact.

## Leg B — Import the backlog

### Step B1 — Source discovery + consent

Candidates, in rough value order (presence-check first, read after consent — same discipline as A1):

1. **A roadmap/backlog file** — `ROADMAP.md`, `TODO.md`, `BACKLOG.md`, `docs/roadmap*`, or a legacy `product_roadmap.md` (the shape Sysop itself migrated off of). `$ARGUMENTS` may name it directly.
2. **Open GitHub issues** — offer only if the repo has a GitHub remote. On yes, count first (`gh issue list --state open --limit 200 --json number --jq 'length'`), report the count, then fetch bodies (`gh issue list --state open --limit 200 --json number,title,body,labels`); the `Bash(gh issue list:*)` rule ships in the default settings template. **If the returned count equals the limit, the fetch is truncated** — say so and raise the limit (or paginate) rather than proceeding; a silently-capped fetch violates the no-silent-caps rule before B2 even starts.
3. **Inline `TODO:`/`FIXME:` comments** — lowest value, **only on explicit request**; never sweep them by default.

**External trackers (Jira, Linear, Notion, GitHub Projects) are not supported here** — they need permission surfaces this skill deliberately doesn't carry, and are planned as a separate opt-in module. Say so plainly if asked; don't improvise API calls.

### Step B2 — Read as reasoning, not a parser

Roadmap files are loose, restructured, half-abandoned markdown — that's expected. Read for meaning: items, groupings, stated priorities, "done" markers, staleness signals (a section dated two years ago; items the CHANGELOG says already shipped). Where an item is genuinely ambiguous — *"is 'auth v2' one task or a phase?"* — **ask, don't guess**. Flag items that look already-done or abandoned rather than importing them blind (they go in the held list, Step B5).

### Step B3 — Decompose and enrich to the task schema

Each surviving item becomes one or more tasks per `tasks/schema.md`. **Read `.claude/skills/_shared/decomposition-rubric.md` before slicing** — the four tests (atomic? sized? ordered? blocked?) apply to imported items exactly as to fresh ones; a roadmap bullet is usually an epic in disguise.

- **`effort` / `blast_radius`** — author both (the validator enforces the enums when present), knowing they are **archaeological guesses**: you're estimating someone else's backlog against a codebase you just met. The provenance marker (B4) is what keeps that honest downstream — don't agonize past a reasonable estimate.
- **`phase:`** — map the source's own structure (sections, milestones, priority tiers) onto `phases:` entries when it has one; otherwise emit a single current-focus "adopted backlog" phase and keep anything clearly-later as a coarse titled phase, per `/intake`'s later-phases-stay-coarse rule. Exactly one phase carries `current_focus: true`.
- **`depends_on`** — only physical impossibility, and only where the source states or the code makes it obvious. Don't manufacture a dependency graph the source doesn't have.
- **Bodies** — one `tasks/open/<TASK-ID>.md` per task (first heading `# <TASK-ID>`; `## Context`, `## Requirements`, `## Key files`). No `## Test decision` (that's `/claim-task` plan-time).

### Step B4 — Provenance

Every imported task carries, non-negotiably:

1. **`surfaced_by: [imported]`** — the validator-sanctioned sentinel (it is not a task ID and never fabricates one). This is the machine-visible signal that `effort`/`blast_radius` are estimates: `/auto-build` re-estimates them from the body before its batch math trusts them.
2. **An `**Imported from:**` line opening `## Context`** — the exact source: `ROADMAP.md § "Q3 ideas"`, `issue #142`, etc. The human auditing the queue can always trace a task back to what it came from.

### Step B5 — Dedup against the existing queue — and hold, don't drop

Compare each candidate against existing tasks (open, in-progress, deferred, **and** done) by meaning, not string equality — *"roadmap says 'CSV export'; DATA-EXPORT-CSV is already done"*. Build two lists and show both:

- **Proposed imports** — the tasks you'll emit.
- **Held items** — candidates you propose *not* to import, each with its reason: duplicate of `<ID>`, appears already shipped (cite the evidence), too vague to be a task (offer to interview it into shape), or reads abandoned.

**No silent caps.** Every item read in B2 appears in exactly one of the two lists. The human promotes held items back with a word; nothing vanishes because you judged it quietly.

### Step B6 — Chunked emit (the write path)

Follow `/intake` Step 7's contract exactly: **append with `Edit`** when `index.yml` already lists tasks (never rewrite or drop an existing entry or its `sprint_note`; flip the previous `current_focus: true` to `false` in the same pass if you introduce a new current-focus phase); **author with `Write`** only when the queue is empty (`schema_version: 1` at top). **Refuse ID collisions** — surface them, never overwrite. Pick an ID prefix vocabulary consistent with any existing tasks; emit each phase's entry before the tasks that reference it.

For a large backlog (tens of items), **emit in chunks** — one phase (or ~15 tasks) at a time, running the validator between chunks — so a structural mistake surfaces after the first chunk, not after task ninety.

## Final step — Validate (floor), hand off (ceiling)

Run the validator and make it pass:

```bash
.venv/bin/python3 sysop/scripts/validate_tasks.py
```

(Bare `python3` if the project has no `.venv`.) Then print the summary and hand off:

```
## Onboarding complete — review before committing

Leg A (intent layer): wrote tasks/vision.md + tasks/decisions.md
  — <N> decisions recorded; <K> rationales were inferred and confirmed by you.
Leg B (import): <N> tasks emitted across <M> phases (all surfaced_by: [imported])
  — held <H> items (listed above with reasons); nothing silently dropped.

Validator: PASS (the floor — well-formedness only).

Everything is uncommitted. Your turn (the ceiling): read vision.md and a sample
of imported bodies — are the rationales actually yours? are the tasks atomic?
Your commit is the sign-off.

Next: run /intake — it will pick up against the new intent layer (or offer to
establish one, if you skipped Leg A), coherence-check the imported queue, and
decompose the next slice with you.

Hit any Sysop friction while onboarding? Note it in SYSOP_ISSUES.md at the repo
root — /report-issues sends the keepers upstream.
```

**Leave everything uncommitted.** The commit is the human's sign-off on a potentially large write — `/onboard` never runs `git add` or `git commit`. Skip the Leg-A or Leg-B lines for a leg that didn't run.

## Boundary discipline

Same two hard lines as `/intake` Step 4, plus one of its own:

1. **Never adjudicate venture worth.** You're reconstructing and importing a plan, not judging whether the product deserves one.
2. **No hype drift.** Import what the backlog says, not what would be exciting to add to it. New ideas that surface mid-onboarding go to the held list as "candidate — raise in `/intake`," not into the import.
3. **Archaeology is not authorship.** When the evidence is silent, the answer is an interview question or an `(unconfirmed)` marker — never a filled-in blank.

## Permissions

`/onboard` needs **no new permission rules.** Writes go through `Write`/`Edit` (file-level, not Bash-gated); `sysop/scripts/validate_tasks.py` has allow-rules in the default template (bare + `.venv/bin/python3`); `gh issue list` has a rule (shipped for `/report-issues`); `git log`/`ls`/glob presence checks are read-only ops that need no rules per `_shared/permission-guard.md` § Notes for skill authors. It does not commit, push, or call any external API beyond the optional, consented `gh issue list`.
