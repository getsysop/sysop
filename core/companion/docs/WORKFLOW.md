# Development Workflow

> A portable, self-improving development process for AI-assisted solo builds.
> This document defines the complete lifecycle from task discovery to merge.
> It is independent of any specific project — project-specific configuration lives in CLAUDE.md and companion map files.

## Contents

- [1. Overview & Design Philosophy](#1-overview--design-philosophy)
- [2. Lifecycle Phases](#2-lifecycle-phases)
  - [2.1 Task Discovery](#21-task-discovery)
  - [2.2 Planning](#22-planning)
  - [2.3 Implementation](#23-implementation)
  - [2.4 Documentation](#24-documentation)
  - [2.5 Review — Code Quality](#25-review--code-quality)
  - [2.6 Review — Security](#26-review--security)
  - [2.7 Automated Fixing](#27-automated-fixing)
  - [2.8 Senior Merge & Verification](#28-senior-merge--verification)
  - [2.9 Cleanup](#29-cleanup)
- [3. Convention System](#3-convention-system)
  - [3.1 What conventions are and why they exist](#31-what-conventions-are-and-why-they-exist)
  - [3.2 Convention maps (scoping rules to files)](#32-convention-maps-scoping-rules-to-files)
  - [3.3 Security maps](#33-security-maps)
  - [3.4 Pre-commit enforcement (blocking vs advisory tiers)](#34-pre-commit-enforcement-blocking-vs-advisory-tiers)
  - [3.5 Convention promotion lifecycle](#35-convention-promotion-lifecycle)
  - [3.6 Map coverage auditing](#36-map-coverage-auditing)
- [4. Infrastructure](#4-infrastructure)
  - [4.1 Worktree isolation](#41-worktree-isolation)
  - [4.2 Task tracking (review_tasks.md format)](#42-task-tracking-review_tasksmd-format)
  - [4.3 Git hooks (pre-commit + pre-merge)](#43-git-hooks-pre-commit--pre-merge)
- [5. Feedback Loops](#5-feedback-loops)
  - [5.1 Convention creation](#51-convention-creation-review--candidate--promotion)
  - [5.2 Convention enforcement](#52-convention-enforcement-hook--catch--prevent)
  - [5.3 Map coverage](#53-map-coverage-audit--fix--coverage)
  - [5.4 Sibling amplification](#54-sibling-amplification-fix--scan--catch-siblings)
- [6. Project Configuration Interface](#6-project-configuration-interface)
  - [6.1 What CLAUDE.md should contain](#61-what-claudemd-should-contain)
  - [6.2 Convention map template](#62-convention-map-template)
  - [6.3 Security map template](#63-security-map-template)
  - [6.4 Pre-commit hook template](#64-pre-commit-hook-template)
  - [6.5 Grep check registry format](#65-grep-check-registry-format)
  - [6.6 Deferred docs schema + batch metadata format](#66-deferred-docs-schema--batch-metadata-format)
- [7. Bootstrap Checklist (New Project Setup)](#7-bootstrap-checklist-new-project-setup)
- [8. Portable Kit Manifest](#8-portable-kit-manifest)

---

## 1. Overview & Design Philosophy

This workflow was extracted from a system that processed 3,200+ code review tasks across 70+ rounds of iterative improvement. It is designed for a solo developer using AI coding agents (Claude Code or similar), but works without them.

### Core principles

1. **Plan before code.** Every task enters a planning phase where applicable conventions are looked up and the implementation approach is designed before any edits.
2. **Conventions over memory.** Learned rules are codified as prevention conventions and scoped to files via convention maps — not carried in human memory or conversation context.
3. **Self-improving.** The review process extracts recurring patterns as convention candidates. The merge process promotes them into enforceable rules. Each round of reviews teaches the system something new.
4. **Isolation by default.** Work happens in git worktrees on feature branches. The main branch is never committed to directly. Merges go through a verification gate.
5. **Deferred documentation.** Documentation is written to staging files during implementation and consolidated during merge — not written directly to shared files that cause merge conflicts.

### What this document covers

- **Sections 2–5**: The universal development process (portable to any project)
- **Section 6**: The project configuration interface — templates and worked examples showing what a project must define to use this workflow
- **Section 7**: A day-one bootstrap checklist for new projects
- **Section 8**: The portable kit manifest — every file, skill, and script a new project needs to copy to replicate this workflow

### What this document does NOT cover

- The actual prevention conventions for your project (those live in CLAUDE.md `§ Prevention Conventions`)
- Architecture, commands, environment variables (those live in CLAUDE.md as project reference)
- The content of your convention maps (those live in `.claude/convention_map.md` and `.claude/security_map.md`)

### Relationship to skill files

Each lifecycle phase (§ 2.1–2.9) references the skill file that implements it. Skills are the **source of truth for execution** — they contain the step-by-step instructions an agent follows. This document is the **source of truth for design intent** — it explains why each step exists and how the phases connect. If a skill and this document disagree, update this document to match the skill, then evaluate whether the skill's behavior is correct.

Skills in the reference implementation are [Claude Code](https://claude.com/claude-code) slash-commands (`/claim-task`, `/document-work`, etc.) stored as `.claude/skills/<name>/SKILL.md`. If you use a different AI agent or no agent at all, port the step lists from each SKILL.md into the equivalent mechanism (system prompts, agent instructions, or human runbooks) — the phase structure in § 2 is agent-agnostic. § 8 (Portable Kit Manifest) lists every skill, script, and config file a new project needs to copy to replicate this workflow.

---

## 2. Lifecycle Phases

The full lifecycle, in order:

```
Task Discovery → Planning → Implementation → Documentation → Review (Quality)
→ Review (Security) → Automated Fixing → Senior Merge → Cleanup
```

Not every task goes through every phase. Ad-hoc fixes may skip reviews. Reviews may find nothing to auto-fix. The phases are modular — use what applies.

### 2.1 Task Discovery

**Trigger:** Human decision, or running the `/next-task` skill.

**What happens:**
1. Read `tasks/index.yml` to find the next unclaimed task
2. Read the review task tracker to find pending review batches
3. Evaluate blockers (dependencies, human-required actions)
4. Present the single next actionable item with effort estimate

**YAML-driven selection:** `tasks/index.yml` is the source of truth for task metadata. `sysop/scripts/validate_tasks.py` enforces schema invariants — on demand, and at commit time once you wire it into your pre-commit hook (opt-in; § 8.4) — so `/next-task` filters the index directly — no prose-format fallback rubric. Selection rules:

- Anchor on the phase with `current_focus: true` (validator guarantees exactly one).
- Keep tasks with `status: open`, `user_action: false`, no active `sysop/runtime/locks/<id>.lock`, and all `depends_on:` IDs resolved to `status: done`.
- Sort survivors **unblocker-first** — by `unlock_count` descending (the number of open same-phase tasks that `depends_on` this one), then `effort:` (`Low → Medium → High`), then id — and return the first match. Doing the foundational task first makes its dependents claimable sooner.

If no candidate matches with `user_action: false`, relax once and surface the first survivor (flagged as user-action-required so the operator knows manual steps are expected).

`blast_radius:` (Phase 19) is read alongside `effort:` and displayed to the operator (e.g., "Medium / single-file") so the next task's surface area is visible at selection time, but it is not a sort key here — the primary sort key is `unlock_count` (unblocker-first, Phase 74), with `effort:` as the secondary. `/auto-build` consumes `blast_radius` for batch sizing; a `blast_radius`-aware secondary sort for `/next-task` remains a future candidate (deferred until `schema_version: 2` is populated widely enough). The optional `--avoid-inflight` flag (Phase 103) prepends a collision-avoidance key via the shared `sysop/scripts/scope_overlap.py` primitive: it prefers a task whose likely file scope doesn't touch any worktree building right now, and annotates the chosen task with its overlap verdict — the opt-in, single-task companion to `/roadmap`'s portfolio-level `--in-flight` annotation.

Per-task prose (Context / Requirements / Key files / User ops) lives at the path the index entry's `body:` field records — relative to `tasks/`, canonically `open/<TASK-ID>.md` — and is read lazily after selection narrows to one ID. The directory is **not** derived from `status`: a claim never moves the body, and no shipped layout has a `tasks/in_progress/` directory.

**Inputs:** `tasks/index.yml`, the body file each entry's `body:` points to (relative to `tasks/`), `review_tasks.md`, `sysop/runtime/locks/*.lock`
**Outputs:** A recommended next task with context

**Implementing skill:** `/next-task`

### 2.2 Planning

**Trigger:** Running the `/claim-task` skill with a task ID or batch number.

**What happens:**
1. **Validate** the task exists and is available (not already claimed or completed)
2. **Read context** — project status, roadmap priorities, design constraints
3. **Claim the task** — create an isolated git worktree on a feature branch (via `sysop/scripts/claim_task.sh`). `/claim-task` Step 4 always passes `--lock` so the validator's `in_progress requires lock` invariant is satisfied; the lock lives under `<main-repo-root>/sysop/runtime/locks/<TASK_ID>.lock` regardless of which worktree invokes the script (Phase 32). Solo workflows that bypass `/claim-task` and call the script directly may omit `--lock`
4. **Resolve the plan-review preference** (Step 6) — before any agent spawns, decide how much the human is in the loop: option **A** (human gate between review and implementation) or option **B** (run it unattended). Resolution order is flag → `<project>/CLAUDE.md § Plan review` → ask, per `_shared/plan-review-preference.md`. Front-loaded on purpose: planning plus review is 5–25 minutes, so asking afterwards asks someone who may have walked away
5. **Resolve the run and its artifact directory** (Step 7-pre) — `sysop/runtime/claim/<CLAIM_ID>/<RUN_ID>/` **in the main checkout**, where `<RUN_ID>` is a UTC timestamp plus a random suffix. Every run of the pipeline gets its own directory, which is what makes a previous run's artifacts unreachable rather than merely detectable. This is the **only** entry point to Step 7: a fresh claim mints a run id, a `--resume <RUN_ID>` adopts the named one, and either way the stage to re-enter is read off the artifacts present rather than remembered. A fresh run also moves any leftover envelopes for this claim into `<ARTIFACT_DIR>/prior-envelopes/`, since the hook keys them by claim and phase with no run component
6. **Spawn a planner** (Step 7a) — a sub-agent that produces the implementation plan and writes it to `plan.md`. It looks up conventions in both maps and emits a `## Constraints & Risks` block as the plan's first content section, checks map coverage for files it creates/moves/deletes, records a `## Test decision`, and cites an in-repo precedent (or flags `unverified`) for every external SDK call. It does not implement, does not commit, and does not enter plan mode
7. **Spawn an independent reviewer** (Step 7b) — a *different* sub-agent, which did not write the plan, is given the plan plus the **Prompt Template** from `_shared/adversarial-review.md` verbatim. It writes `review.md` and returns findings plus a sealed `REVIEW_REPORT:` block. **It does not classify them and does not decide whether the work proceeds.** This step always runs — review is never inherited and never skipped. The sealed block's one required home is the reviewer's final message, emitted *before* the envelope, because the block is the transport: the `SubagentStop` hook captures it into `review_report_raw`, and a verdict that arrives only in a file the reviewer wrote is indistinguishable from an invented one (internal tracker #329). A **post-review transport check** then classifies the return `OK` / `EMPTY_TRANSPORT` / `NO_ENVELOPE` / `NO_REVIEW_MD` and writes a `review-transport.md` receipt; only a missing `review.md` parks
8. **Classify the findings at the orchestrator's own level** (Step 7c) — apply the Classification Rubric to each finding, `fixable` or `blocker`, and write the result to `classification.md`. Not delegated to a third sub-agent: classification is the seam where the human stays the gate. On any `blocker`, park — write a marker at `sysop/runtime/parked/<CLAIM_ID>__<RUN_ID>.md` recording the reason, the branch and which artifacts were present, leave the lock and worktree intact, and surface the question. A pointer rather than a copy: the artifacts are already in the main checkout, so worktree cleanup cannot reach them
9. **Human gate** (Step 7d, option A only) — present the plan *as reviewed*, with the verdict and the classification. Approve → execute; revise → re-plan and re-review; abandon → release the claim (`batch_work.sh --release <N>` for a batch, never `claim_task.sh --release`)
10. **Spawn an executor** (Step 7e) — reads the plan, review and classification from disk, implements, persists the `## Test decision` **into the worktree's copy of the task body** so it rides the branch (an edit made in the main checkout is committed by nothing and reaches no PR — internal tracker #322), runs post-fix convention verification, runs the consumer's `## Pre-merge verification` gates *in the worktree*, runs UI verify if frontend files changed, and makes a single commit carrying a `Doc-Work:` trailer. It does not push and does not invoke `/document-work`
11. **Receive the executor envelope and hand off** (Step 8) — read `sysop/runtime/subagent-envelopes/<CLAIM_ID>.exec.json`, resolved against the main repo root. On `EXECUTED`, print the sealed report — saying so explicitly if `review_report_raw` was null rather than printing nothing — run the stranded-body check (tracked modifications under `tasks/` in the main checkout, which reach no PR), and direct the user to `/document-work`. On `BLOCKED`, park. On `FAILED` or a malformed envelope, surface the error verbatim and let the human decide — no auto-retry

**The orchestrator shape (replaces the Phase-29 reviewer-executor collapse).** `/claim-task` is now the same shape as `/auto-build`: plan, review, classify, execute, with each stage in its own cold context and the classification held one layer up. The collapsed "reviewer-executor" sub-agent it replaces **self-classified its own findings**, which was a recorded compromise — and it failed in the field. Internal tracker #220 observed a real review-batch claim run `EnterPlanMode` → ~200 tool calls → `ExitPlanMode` with no `Agent` call at any point, bypassing the review, the classification, the sealed report and the halt-on-blocker gate together; it surfaced only because a human asked. Worse, a review that *did* run left nothing durable either — the envelope was deleted after consumption — so a healthy claim and a skipped one produced identical evidence.

**What the shape does and does not fix, stated plainly.** It removes the `ExitPlanMode` attractor and it makes a skipped review *visible*, because the orchestrator's output is now an artifact set that a blocked run cannot produce. It does **not** prevent a harness that forbids the `Agent` tool outright — a system-prompt instruction outranks skill text — and Sysop reports that case rather than stopping it. **Nothing reads the difference automatically yet**: the `/review-close` and `/sitrep` readers, and close-time cleanup of the artifact set, are part B of the reshape and are unbuilt, so today the evidence is durable and inspectable by a human and no skill reports on it. Of the four artifacts, only the `SubagentStop`-written envelope is unforgeable: `plan.md`, `review.md` and `classification.md` are ordinary writes at paths the orchestrator also knows. `BLOCKER_QUESTION:` vs `PARKED_REASON:` still differs from `/auto-build` and is still load-bearing — see `_shared/adversarial-review.md`.

**Inputs:** `tasks/index.yml`, the body file each entry's `body:` points to (relative to `tasks/`), `review_tasks.md`, `.claude/convention_map.md`, `.claude/security_map.md`
**Outputs:** Git worktree, feature branch, a per-run artifact directory in the main checkout (`sysop/runtime/claim/<CLAIM_ID>/<RUN_ID>/` holding `plan.md`, `review.md`, `classification.md`), up to three hook-written envelopes (`<CLAIM_ID>.{plan,review,exec}.json`), a single commit in the worktree made by the executor, and an envelope-reported handoff plus the sealed `REVIEW_REPORT:` (plus a `sysop/runtime/locks/<CLAIM_ID>.lock` file — `/claim-task` Step 4 always passes `--lock`)
**Checks:** Task availability and entry state, map coverage for new files, adversarial plan review by an agent that did not write the plan, orchestrator-level finding classification with a halt on any `blocker`, post-fix convention + pre-merge + UI verification (the last three inside the executor)
**Feedback loop:** Map coverage check (§ 5.3) — ensures new files get convention coverage before code is written

**Implementing skill:** `/claim-task` (interactive single-task), `/auto-build` (parallel-batch orchestration, see § 2.4b), `/plan-review` (ad-hoc plans not produced by `/claim-task`)

### 2.3 Implementation

**Trigger:** Plan approved, agent begins coding.

**What happens:**
1. Work in the isolated worktree on the feature branch
2. Follow the prevention conventions scoped to the files being modified (from the plan's "Constraints & Risks" block)
3. Never commit directly to main
4. **Post-fix convention verification** — before handing off to `/document-work`, list changed files (`git diff --name-only main...HEAD`), look up each one in the convention map, and scan the **new/changed lines** (not just the original task locations) against those conventions. Common regressions to re-check: fetch calls missing `encodeURIComponent()` on dynamic path segments, error handling that exposes `str(e)`, moved code that dropped `<log sanitizer>()` wrappers, incomplete `useCallback` dependency arrays, SELECT queries routed to a write-only engine when a read-replica is available
5. **Post-fix UI verification** (frontend diffs only) — run the shared UI verification procedure (`.claude/skills/_shared/ui-verify.md`): probe the dev server, navigate to the changed feature via browser automation (Playwright MCP or equivalent), and check console + network for regressions. Hard-fail on console errors and 5xx responses; warn on console warnings; skip cleanly with an explicit note if the dev server is not running or the change is auth-gated only. Surface the skip note verbatim so the user knows manual verification is still required

**Inputs:** Implementation plan, convention map, source code
**Outputs:** Code changes on the feature branch
**Checks:** Prevention conventions (advisory — enforced at commit time by pre-commit hook), post-fix convention re-scan, post-fix UI verification

**Implementing skill:** Steps 1–3 are manual work or agent implementation. Steps 4–5 run inside the `/claim-task` Step 7e executor sub-agent (see § 2.2), before `/document-work`. A simplify pass — re-reading in-progress changes against the convention map and fixing reuse/quality issues before committing — runs mandatorily as `/document-work` Step 1b. Projects whose environment provides a separate `/simplify` slash command can also invoke it mid-implementation; this is optional and not provided by Sysop.

### 2.4 Documentation

**Trigger:** Implementation complete, running the `/document-work` skill.

**What happens:**
0. **Ensure the session is on a high-capability model** — the simplify pass adversarially re-reads the diff and benefits from top-tier reasoning. If execution ran on a smaller/faster model, switch before proceeding. (In the reference implementation, this means switching to Opus before `/document-work`.)
1. **Simplify pass** — before committing, cross-check all changed files against the convention map. Fix violations and eliminate code that reimplements existing helpers
2. **UI re-verify** (frontend diffs only) — re-run the shared UI verification procedure from § 2.3 to catch regressions introduced by simplify-pass edits. If the gate fails, fix the regression and re-run the simplify pass before proceeding
3. **Commit** — stage and commit changes with a conventional commit message (`feat:`, `fix:`, `refactor:`, etc.)
4. **Classify** — determine work type (feature, bugfix, UI iteration, infrastructure, ad-hoc) from the intent of the work, not the branch prefix
5. **Write deferred documentation** — create a structured file in `sysop/runtime/pending-docs/<sanitized-branch-name>.md` with YAML frontmatter describing the branch, date, type, task IDs, and summary. Do NOT modify shared documentation files directly (this prevents merge conflicts when parallel branches merge). The pending-docs file is untracked — `/review-close` consolidates it into the shared docs after merge
6. **Push** — push the branch to origin

**Inputs:** Changed files, convention map, `tasks/index.yml`
**Outputs:** Committed code, `sysop/runtime/pending-docs/<branch>.md`, pushed branch
**Checks:** Convention compliance (simplify pass), commit hygiene
**Feedback loop:** Simplify pass catches convention violations before they reach review

**Deferred docs format** (see § 6.6 for the full schema and routing table):
```yaml
---
branch: <branch-name>
date: <YYYY-MM-DD>
type: <feature|bugfix|ui-iteration|infrastructure|adhoc>
roadmap_ids: [<FEAT-NNNN | TECH-NNNN | BUG-NNNN>, ...]
review_task_ids: [<TASK-NNNN>, ...]
summary: "<one-sentence description including key files affected>"
---
```

**Implementing skill:** `/document-work`

### 2.4b Parallel-Batch Orchestration (optional)

**Trigger:** Running the `/auto-build` skill when the current-focus phase has ≥ 2 independently-claimable tasks and the human wants to walk away while a batch executes.

**What happens:**
1. **Read queue & filter** — read `tasks/index.yml`, filter to `status: open` tasks in the phase with `current_focus: true`, drop tasks with `user_action`, `on_hold_until`, an active lock, or unmet `depends_on`; order the survivors **unblocker-first** (`unlock_count` descending — open same-phase tasks that `depends_on` each candidate — then a soft in-flight-overlap tie-break, then effort, then id) so claiming a foundational task enlarges the next batch's pool. The in-flight tie-break (Leg B, Phase 103) grades each candidate against the worktrees building right now via the shared `sysop/scripts/scope_overlap.py` primitive and, among equally-foundational candidates, prefers the one that won't collide — **soft-flag only**: it de-prioritizes and annotates the Step 4 table (an *In-flight overlap* block), it never hard-excludes a claimable task (worktree isolation makes a collision recoverable rework). An explicit task-ID argument list (`/auto-build FEAT-A TECH-B`, e.g. from a `/roadmap` ordering's `Run it:` line) narrows this pool by intersection — requested IDs that fail the filters are reported with per-ID reasons, and the batch invariants never loosen for named tasks (Phase 97)
2. **Apply batch-sizing rule** — score each candidate by `effort_weight × blast_radius_weight`, enforce architectural-solo and migrations-solo invariants, cap cross-module tasks at two per batch, cap total weight at K=12 and raw count at N=4
3. **Confirmation gate** — print the proposed batch + estimated Opus fan-out, ask the human to proceed; this is the only destructive-action gate
4. **Sequential pre-claim on `main`** — for each task, flip `status: open → in_progress` in `tasks/index.yml`, create the worktree + lock via `claim_task.sh --lock`, validate schema, commit the claim (`claim: mark <TASK_ID> as in-progress`)
5. **Per-task three-phase orchestration** (parallel across tasks, sequential within a task):
   - **Phase 6a** — spawn plan-only Opus agents in parallel; each agent reads its task body + the convention/security maps and emits a fenced `plan` block
   - **Phase 6b** — spawn adversarial-reviewer Opus agents in parallel; each agent applies the `_shared/adversarial-review.md` prompt template to one plan
   - **Phase 6c** — the orchestrator classifies findings as `fixable` / `blocker` per the shared rubric (no recursive sub-agent — flat hierarchy by design; see `_shared/adversarial-review.md` § "Harness constraint")
   - **Phase 6d** — halt-on-blocker (park the task; write `plan.md` + `review.md` to `<worktree>/sysop/runtime/auto-build/` for the human to resume) OR pass `PLAN_TEXT + RAW_FINDINGS` to the execution agent
   - **Phase 6e** — spawn execution Opus agents in parallel for non-parked tasks; each agent absorbs findings, calls `ExitPlanMode`, implements, runs `<project>/CLAUDE.md § Pre-merge verification` gates, then invokes `/document-work --non-interactive` to commit + write pending docs
6. **Phase 7 envelope recovery** — for tasks whose execution agent omitted the YAML envelope, cross-check the filesystem (commit landed AND `sysop/runtime/pending-docs/<branch>.md` exists); if both hold, reclassify as `EXECUTED (envelope-recovered)` so the failure mode is visible without false-FAILing real work
7. **Final report** — print a status table (EXECUTED / EXECUTED (envelope-recovered) / PARKED / FAILED) with worktree paths; the orchestrator stops here and never runs `/review-close`

**Envelope-shape divergence from `/claim-task`:** `/auto-build`'s execution agent uses `PARKED_REASON:` because parking happens at the orchestrator's Phase 6d BEFORE the execution agent is spawned — by Phase 6e no blocker can surface. `/claim-task`'s executor uses `BLOCKER_QUESTION:` because the parent IS the human and the sub-agent must surface blockers on its own envelope. See `_shared/adversarial-review.md § "The reviewer-executor variant is retired"`.

**Inputs:** `tasks/index.yml` (current-focus phase + open tasks), `.claude/convention_map.md`, `.claude/security_map.md`, `<project>/CLAUDE.md § Pre-merge verification`, optional `sysop/runtime/locks/*.lock` for concurrent-claim detection
**Outputs:** Up to N worktrees on feature branches, per-task commits inside each worktree, per-task `sysop/runtime/pending-docs/<branch>.md`, status table with envelope details
**Checks:** Batch-sizing rule (effort × blast_radius weights, K=12 sum ceiling, N=4 count cap, ≤2 cross-module tasks), DB-contention warning, post-Phase-6a integrity check (plan-only agent didn't commit), post-Phase-6e envelope parse, Phase 7 filesystem cross-check
**Feedback loop:** `current_focus: true` discipline — the orchestrator only batches tasks in the actively-prosecuted phase, keeping launch-lane work serialized against future-phase work

**Implementing skill:** `/auto-build`

**When NOT to use:** if your roadmap is sequential (only one claimable task) or you're actively iterating on a single change. `/auto-build`'s value is amortizing Opus fan-out across multiple independent tasks; a one-task "batch" gains nothing over `/claim-task` and costs a confirmation gate.

### 2.5 Review — Code Quality

**Trigger:** Human decision, typically after a development sprint or batch of changes.

**What happens:**
1. **Determine scope** — full codebase scan or incremental (changes since last review round). Auto-detect based on time since last round (>7 days → full, ≤7 days → incremental)
2. **Collect context** — read existing open review tasks (for deduplication), convention map, security map, project status
3. **Audit map coverage** — check both maps for files not covered by any section, and for convention bullets not referenced in any map section. Then run the backward staleness sweep (§ 3.6 check 4) — map sections whose glob matches no file, and bullets citing a deleted helper. Offer to fix gaps and refresh stale citations inline before launching review agents; route genuine retirement candidates to the human
4. **Run deterministic pre-scan** (`bash sysop/scripts/run_checks.sh`) — six stages inside one invocation, all sharing the same `(check_id, file_line, message, identity)` finding shape so baseline matching, `--mode` filtering, and `--fail-on-blocking` apply uniformly:
   - **(a) Grep** — pattern-matching for mechanical convention violations (e.g., f-string SQL, raw exception exposure, missing mock cleanup). Check IDs are the registry `id` values. Findings tagged `[grep]`
   - **(b) LSP / typechecker** — `pyright` for Python, `tsc --noEmit` for TypeScript. Catches unresolved imports, undefined names, unused bindings, and type errors that grep cannot express. Check IDs prefixed `pyright-*` / `tsc-*`. Findings tagged `[lsp]`. Binaries resolve via PATH with `.venv/bin` and `frontend/node_modules/.bin` prepended (the PATH prepend is literal `frontend/` — a differently-named frontend dir gets no `tsc` prepend, though the ESLint stage discovers the actual dir itself); each half silently skips if its binary is missing
   - **(c) Semgrep AST** — rules from `.claude/semgrep/*.yaml` for patterns regex cannot express with precision (function-scope guards, JSX-context-only renders, template-literal interpolation, f-string argument detection). Check IDs prefixed `semgrep-*`. Findings tagged `[semgrep]`. Entire stage silently skips if the `semgrep` binary or `.claude/semgrep/` directory is absent
   - **(d) ESLint** — `eslint --format json .` from the discovered frontend dir (the directory under repo root containing `node_modules/eslint`). Single catch-all check ID `lint-error` with the original ESLint rule_id embedded in the message text. Findings tagged `[lsp]` (shares the LSP slot for tagging — both quality and security modes consume it since `jsx-a11y/*` rules cross both scopes). Silently skips if the `eslint` binary or `node_modules/eslint(-config-next)` is missing
   - **(e) pip-audit** — `pip-audit --skip-editable --format json` against the active venv (falling back to `python -m pip_audit` when the console script isn't on PATH). Runs for every requirements layout (requirements.txt, pyproject/uv, poetry) since it audits installed packages. Single catch-all check ID `pip-audit-vuln` anchored at the first discoverable `requirements*.txt` (sorted), then `pyproject.toml:1`; each finding embeds package name, version, CVE/GHSA ID, fix version, and description. Findings tagged `[pip-audit]`. Security-audit-only (codebase-review skips A06). Skips with a warning if `pip-audit` is missing both ways. **Known gap:** audits only the venv that pip-audit runs in — projects with multiple service-specific venvs need a per-venv invocation
   - **(f) Coverage** — glob-scoped *diff* coverage via `diff-cover`, reporting changed lines that lack test coverage, filtered to the `critical_path` globs each check declares (Phase 61a measurement, Phase 61b gate). Check IDs prefixed `coverage-*`. This is the one stage that **never baseline-suppresses** — a diff-relative coverage gap cannot be accepted as standing tech debt — so a `blocking: true` coverage check is a hard gate with no escape hatch. It consumes coverage reports (Cobertura XML from `pytest-cov`, lcov from `c8`/`istanbul`) that the consumer's CI produces ahead of this stage; `run_checks` never runs the test suite itself. Skips when `critical_path` is still placeholder globs, which reads as `gate unarmed`
4b. **Reconcile the dispatch table against the map, before any agent launches** — the table in Step 3-pre is authored by hand and cites convention_map sections by name, so it can cite a name no section carries, and a section added by a new pack reaches no row. The step reports both, plus any glob two rows claim. **Step 3 above cannot see this class**: a file matched by a section no row names is *matched*, so the coverage audit counts it as covered. `/security-audit` runs the mirror of this check against its OWASP roster (§ 2.6).
5. **Launch scoped LLM review agents** — group files by convention map section. Each agent receives only the 4–8 conventions relevant to its file group (not all conventions). This scoping reduces noise and false positives
6. **Deduplicate** — remove findings that duplicate existing open tasks
7. **Batch and write** — organize findings into batches grouped by file locality. Write to the review task tracker with batch metadata (branch name, scope, verify command, overlap tags)
8. **Extract convention candidates** — scan findings for recurring patterns (3+ occurrences across different files). Draft candidate prevention convention bullets, attribute each to this review round, and write to `sysop/runtime/pending-docs/convention-candidates.md`. The 3+ burst is the in-round *noticing* signal; promotion (step 9) gates on cross-round survival — see § 3.5
9. **Promote convention candidates (interactive)** — present each candidate to the reviewer in-session. Promote only candidates whose pattern has **recurred across two review rounds** (cross-round survival — § 3.5); a candidate seen for the first time this round is recorded and carried forward, not promoted yet. For each promoted candidate insert into CLAUDE.md, update the convention map, sweep for existing violations, and optionally add a pre-commit hook check. See § 3.5 for the full promotion flow. Promotion happens here (not during merge) so the feedback loop closes in the same review session that confirmed the pattern. **Demotion (Step 9b)** is the symmetric counterpart, run in the same session **independently of promotion** (a stale rule accrues whether or not this round promoted anything): a blocking-mechanical rule that accrued **stale-verdicts** at pre-scan triage (step 4) across 2+ review rounds — plus any removed-category prose convention the map sweep flagged at step 3 — is presented for `[retire / demote-to-advisory / tighten / keep]`. See § 3.5b for the full demotion flow

**Inputs:** Source code, `.claude/convention_map.md`, `.claude/security_map.md`, `review_tasks.md`, check registry (`.claude/checks.yml`), Semgrep rules (`.claude/semgrep/*.yaml`)
**Outputs:** New review round in `review_tasks.md`, promoted conventions in CLAUDE.md + convention map, optional pre-commit hook / registry / Semgrep updates
**Checks:** Map coverage audit, deterministic pre-scan (the six stages of § 2.5 step 4), LLM review
**Feedback loops:** Convention creation (§ 5.1), map coverage (§ 5.3)

**Key design choice:** Convention scoping. Rather than giving a review agent all 50+ conventions and hoping it finds violations, each agent gets only the conventions that apply to its file group. This was learned through trial — unscoped reviews produce excessive false positives.

**Implementing skill:** `/codebase-review`

### 2.6 Review — Security

**Trigger:** Human decision, typically run alongside or after code quality review.

**What happens:**
Same 9-step structure as code quality review (§ 2.5), but with security-focused checks:

1. Same scope detection and context collection
2. Same map coverage audit (but for the security map) — including the backward staleness sweep (§ 3.6 check 4)
3. **Security-specific grep checks** — patterns for prompt injection, missing audit trails, LLM cost abuse, HTTP redirect following, dangerouslySetInnerHTML, etc.
4. **OWASP-categorized LLM agents** — instead of grouping by file area, agents are grouped by threat category:
   - Injection & Prompt Safety (OWASP A03)
   - Authentication, Access Control & Data Exposure (A01, A02, A07)
   - SSRF, LLM Security, Configuration & Insecure Design (A10, A05, A04, LLM)
   - XSS & Frontend Security (A03 client-side)
   - Logging, Audit Trail & Privacy
   - Dependencies & Supply-Chain Integrity (A06, A08)
4b. **Assignment reconciliation, before any agent launches** — the roster is keyed on categories and coverage is a property of files, so the two are checked against each other rather than assumed to agree. The step reports sections whose categories no agent owns, categories the map uses that the roster does not staff, and `Check:` bullets carrying no category for a category-keyed dispatch to route. It is deterministic and runs on solo rounds too. **The map-coverage audit in step 2 cannot see this class** — a file matched by a section nobody audits is *matched*, so step 2 counts it as covered. `/codebase-review` runs the mirror of this check against its own dispatch table (§ 2.5).
5. Same deduplication, batching, convention candidate extraction, interactive convention promotion (Step 9), and interactive convention **demotion** (Step 9b — § 3.5b; for security rules, confirm the protection moved elsewhere before retiring)

**Inputs:** Same as § 2.5, plus `.claude/security_map.md` for agent scoping
**Outputs:** Same as § 2.5 (review tasks + convention candidates), grouped by threat category
**Checks:** Security map coverage, security grep checks, OWASP-category review

**Key design choice:** The security map has explicit "Check" and "Skip" subsections for each file area, both scoped to the files that section's globs actually match (a section still in placeholder form matches nothing and so tells an auditor nothing). This tells auditors what NOT to check, preventing audit fatigue from false positives in areas where a threat category doesn't apply (e.g., SQL injection checks on pure frontend components).

**Implementing skill:** `/security-audit`

**Optional external-scan ingest (claude-security).** If you separately run Anthropic's `claude-security` plugin — a top-level `/claude-security` scan you launch yourself; Sysop *cannot* launch it, because the plugin's multi-agent scan needs the `Workflow` tool, which Claude Code strips from every sub-agent — the next `/security-audit` folds that report's findings into `review_tasks.md` as `[reported]` tasks (a new Step 3c), surfacing the deep code-reasoning defects the deterministic pre-scan can't reach (one 2026-07 head-to-head, a single codebase at one commit, measured *zero overlapping findings* between the two tools — one run, not a general property). Cadence: the plugin is a periodic deep pass (quarterly / pre-release; whole-repo scans are expensive), while the pre-scan stays first on every round. The ingest is silent when no report is on disk; it **sanitizes the report's untrusted finding text** before it reaches markdown, tags every ingested row `[reported]` (the plugin's own panel verification is recorded as data, never promoted to `[verified]`), and surfaces a truncated scan loudly (`verified` certifies the plugin's per-finding panel completion, *not* repo coverage). See `/security-audit` Step 3c for the quarterly-sweep recipe.

### 2.7 Automated Fixing

**Trigger:** Running the `/auto-fix` skill after review tasks exist.

**What happens:**
1. **Triage prerequisite** — if any pending batch lacks a `> **Triaged:**` record, invoke `/triage` and wait. Classification is **not** this skill's job: Phase 44 extracted it, and `/triage` is the sole writer of `Flag:` and `Triaged:`
2. **Read queue** — an index pass (`grep` for batch headers and `> **Key:**` metadata lines) selects the auto pool: pending batches with **no** `> **Flag:**` line. Bodies are read only for those batches, bounded by line number. The tracker's size does not gate the run
3. **Skip the flag pool** — batches carrying a `> **Flag:**` line are `/auto-judge`'s (§ 2.7b), including partially-flagged ones: a batch is claimed as a unit, so splitting one across two concurrently-running skills would put two agents on one branch
4. **Process auto batches (Sonnet)** — spawn isolated Sonnet agents (one per batch) to apply fixes. Each agent:
   - Claims a worktree for the batch
   - Applies the prescribed fixes
   - **Sibling scan** — after fixing listed tasks, scans the same files for additional violations of the same convention that weren't listed as tasks (§ 5.4)
   - Runs verification (tests, build)
   - Pushes the branch
5. **Opus verification pass** — for every batch the Sonnet agent reported PASS, spawn a narrowly-scoped Opus sub-agent to re-review the branch diff for three things Sonnet underperforms on: (A) sibling violations missed by Sonnet's scan, (B) cross-convention regressions introduced by the fix itself (e.g., adding `redact_api_keys()` without truncate-before-regex), and (C) false-positive tasks Sonnet "fixed" despite an invalid premise. Opus applies corrections as new commits on the branch (no force-push) and records any false-positive drops as `> Dropped:` annotations in `review_tasks.md`. This pass is the safety net for Sonnet's weaker adversarial judgment — prior runs in the originating GDP Query System project showed Sonnet missing siblings in `ExportEngine.tsx` and fixing invalid tasks in Batch 416

**Two processing modes:**
- **Default (pass 1):** Process only non-overlapping batches, in parallel (up to a concurrency cap). Batches that touch the same files are deferred
- **Merge mode (pass 2):** Process overlapping batches sequentially, with intermediate merges between each. Run after pass 1's branches are merged

**Inputs:** `review_tasks.md`, source code, convention map
**Outputs:** Feature branches with fixes (Sonnet commit + optional Opus verify commits), updated task tracker
**Checks:** CI verification per batch, Opus adversarial re-review per branch (the classification gate is `/triage`'s, § 2.7a below)
**Feedback loop:** Sibling amplification (§ 5.4)

**Implementing skill:** `/auto-fix`

### 2.7b Automated Judgment

**Trigger:** Running the `/auto-judge` skill on batches that `/triage` flagged as needing judgment.

**Why this exists:** the classifier defers any batch where a task requires judgment — design choice, architectural refactor, investigation, or behavioral verification. Historically these batches queued up for manual `/claim-task` handling. That serialized a pool of work that could be parallelized if the judgment was done by Opus sub-agents. `/auto-judge` fills that gap.

**What happens:**
1. **Read queue** — an index pass selects pending batches with a `> **Flag:**` tag (the inverse of `/auto-fix`'s auto pool), then reads only those batches' bodies
2. **Split judgment from remainder** — the `> **Triaged:**` line's bracketed task IDs are the tasks that actually need judgment; everything else in the batch is fixed mechanically in the same worktree. A verdict with no bracket list means the whole batch, which is the pre-task-granular behaviour
3. **Categorize flag reasons** — group each batch's flag into design-choice / architectural / investigation / verification. Category primes the Opus agent's framing (e.g., architectural batches get scope-discipline reminders; investigation batches get "read broadly before fixing")
4. **Claim and execute** — same two-pass worktree shape as `/auto-fix`: default parallel, `--merge` sequential. Each Opus sub-agent can return one of three verdicts per task:
   - **FIX** — apply a judgment-informed change that addresses the root concern
   - **DROP** — mark the task as a false positive with a reason (appended as `> Dropped:` under the task line; checkbox left as `[ ]` so `close_batch.sh` counts it correctly at merge)
   - **FAIL** — the task is real but requires out-of-scope work (different function signature, cross-module redesign); annotated `> Failed:` under the task line with the checkbox left **unchanged**, so `close_batch.sh` leaves it open at merge instead of closing it with the rest of the batch, and reported for manual follow-up via `/claim-task`
5. **Verify, sibling scan, push** — same as `/auto-fix`, executed at Opus quality

**Concurrency:** runs concurrently with `/auto-fix` — the two skills target disjoint batch pools (no-flag vs flag). The pools stay disjoint at *batch* granularity even though flags are task-granular: a partially-flagged batch is wholly `/auto-judge`'s, which fixes its mechanical remainder itself rather than handing it back. Default concurrency cap is **2** (Opus is more expensive than Sonnet; err conservative).

**Inputs:** `review_tasks.md` (flagged batches only), source code, convention map
**Outputs:** Feature branches with fixes and/or drop annotations, updated task tracker
**Checks:** CI verification per batch, three-verdict adversarial review

**Implementing skill:** `/auto-judge`

### 2.8 Senior Merge & Verification

**Trigger:** Running the `/review-close` skill when branches are ready for review.

**What happens:**
1. **Gather state** — list all pending branches via `git branch -a` and unpushed main commits via `git log origin/main..HEAD`, check for stashes and uncommitted `review_tasks.md` changes. Step 1b commits the uncommitted state with one of two shapes: a single-file `docs: save pending review tasks` commit for new open tasks, or an atomic two-file `docs: archive …` commit when a sibling archive file (e.g., `review_tasks_archive.md`) is also dirty AND `review_tasks.md` has net deletions. Step 1c then issues a soft warning if any in-scope feature branch was cut before an archive rotation on main — those branches will conflict on `review_tasks.md` at the rebase in step 5 (resolve per the `/review-close` Step 4a prose; keep main's structure as authoritative).
2. **Review** — for each branch:
   - Review code for correctness and security
   - Spawn an Opus adversarial sub-agent per branch — isolated in its own worktree, since the close is mid-flight in the primary one — to check the merge-base-relative diff (`git diff main...<branch>`) against the full `§ Prevention Conventions` section of CLAUDE.md. Skipped for a doc-only diff **that no `## Prevention Conventions` rule governs** — both conjuncts, because conventions routinely govern non-code files (skill markdown, vendor ledgers, prompt templates) and the extension test alone would silence them. If any sub-agent returns `VERDICT: BLOCKED`, stop the close until violations are fixed or waived
   - Verify the recorded **test decision** (Step 2d, Phase 59): read the `## Test decision` section the **executor** wrote into each approved branch's task body, in the worktree, during implementation (the planner *decides* it at plan time and emits the step that writes it — Phase 58b) and check it against the diff — "plan said test X — is it here?" / "plan said no-test-because-Z — does Z still hold?". On a mismatch or a missing record, halt and prompt via `AskUserQuestion` to accept the record, hold the branch for a fix (demotes to rejected this run), or waive. Verify the record, don't re-judge whether a test should exist (that is the plan-time adversarial reviewer's job — `_shared/adversarial-review.md` finding 7)
   - Approve or reject with notes
3. **Run verification — the pre-merge pass** (Step 3). The project's command list resolves here, and runs against the tree the skill is standing on: `HEAD` is still `main`, nothing has been merged, so this pass verifies `main` plus its local-only commits and **cannot** verify an approved branch — their files are not in the working tree and their new tests do not exist yet. Its value is fail-fast (a broken base, an unresolvable command list) at the last point where stopping costs nothing; the gate that speaks for the work is step 5b. On the common cycle the pre-merge list is a claim flip and a `review_tasks.md` save, so it doc-only-skips and costs nothing. *This* pass is allowed that skip precisely because its green is not a verdict; step 5b does not inherit it. Each pass computes its own changed-file list with `git diff --name-only origin/main...HEAD` on its own tree, and each auto-detected command is gated on its own surface appearing in that list (a surface the diff does not touch is **skipped-not-failed**, and reported as such). After verification, the new Step 3c (Phase 35, BeanRider ISSUE-0008) gates on `manual_smoke: true` tasks and `sysop/runtime/pending-docs/` smoke headings: if any merged branch has a documented manual smoke procedure, the skill halts and prompts the human via `AskUserQuestion` to drive the smoke, confirm they ran it, or waive it (logged in the final report). **Phase 218 widened the detection in three directions**, because the gate whose miss is a human never being asked was matching only two exact phrases: the heading phrase list is longer, a pending-doc's own `manual_smoke: true` frontmatter signals independently of any heading, and a declared `manual_smoke: true` task now signals even when its body carries no matching heading — plus task linkage reads locks as well as pending-doc `roadmap_ids:`, so a compliant task is not missed because no doc named it
4. **Prepare worktrees for merge** — for each approved feature branch, collect any `sysop/runtime/pending-docs/*.md` from the worktree into main's `sysop/runtime/pending-docs/` (they're untracked and would otherwise be lost), then remove the worktree so the branch can be checked out on main. **The collect is provenance-checked, not an unconditional copy:** a basename is not unique to a branch, so if main already holds a doc of that name authored by a *different* branch, the step refuses — nothing is collected, main is untouched, the worktree stays and the branch is SKIP'd for this run. Same-branch means main's copy is a stale twin and the worktree wins
5. **Merge** — for approved branches, rebase onto the **merge target** then merge (ff-only). The target depends on the project's **merge policy** (§ 6.1, declared in `<project>/CLAUDE.md § Merge policy`; default `direct`): `direct` merges onto `main`; `pr` assembles everything on a throwaway integration branch cut from fresh `origin/main`, with local-only `main` commits (claim flips, Step 1b saves) swept onto it. `pr` has one narrower shape: when **exactly one** branch was approved, it already has an open non-draft same-repository PR against `main`, there are no local-only `main` commits *that the branch does not already contain*, it is not behind its remote, and it is not behind `origin/main`, the close lands on that PR's own branch instead — no second branch, no second PR, no duplicate CI cycle. **Five conditions, not four:** the not-behind-`origin/main` one is what replaces the integration branch's guarantee that the required checks ran against the current base, and this sentence omitted it until Phase 219. Any condition unmet falls through to the integration branch — and the fall-through is not free for a **published** branch, because the rebase below would rewrite history the remote already has. The skill rebases a published branch through a throwaway ref for that reason, and reports the branch's own PR as superseded rather than silently orphaning it. **A rebase conflict is routed, not reflexively aborted:** the two files every branch appends to as a matter of workflow — `tasks/index.yml` (`/document-work` *requires* a branch that surfaces a follow-up to file it there) and `review_tasks.md` — conflict deterministically when two branches file in the same cycle, and are resolved structurally from the merge stages, with `validate_tasks.py` run *before* `git -c core.editor=true rebase --continue` rather than at step 7 where it has always first run. Marker-stripping an indented YAML list is the resolution that corrupts silently: git leaves the fields two entries share outside the conflict markers, so keeping both sides starves one entry of the fields it shares with its neighbour while the next absorbs them — and it still parses with unique ids, which is what hides it. A branch whose conflict genuinely cannot be resolved is **4a-SKIP**: approved work that did not merge, a distinct verdict from a `dirty` SKIP and from `rejected`, and one that steps 7 and 10 must both honour
5b. **Run verification — the merged-tree pass** (`4a-post`), the authoritative one. The same resolved command list, re-read rather than remembered, run on the merge target now that the branches are on it. Each approved branch was already verified *in its own worktree* by `/claim-task` Step 7e (item 5 of its executor prompt's Sequence) or `/auto-build`'s execution-agent sequence (item 4b of Step 7's prompt template); what nothing verified until here is the **assembled** result — the branches on the live base and on each other — and it is also the first tree on which a `### Ratchet` snippet's own `origin/main...HEAD` filter names the work. It sits before step 6 and step 7 on purpose: a failure here has consumed nothing, whereas step 7 deletes each pending-doc it consolidated (by name, from the set it routed — never by glob) after routing it, and those files are untracked. An **empty** changed-file list here is a contradiction, not a pass — the merges did not land. **The pre-merge pass's doc-only skip does not reach this step** (Phase 175): a diff with no code extensions is not evidence a declared list is unaffected, since the same test classifies lint/build configuration, dependency manifests, CI workflows and rule files as documentation, and a full test suite can assert on prose — so a consumer-declared `### Always` runs here on a docs-only cycle too. A gate that ran zero commands never reports green: it **stops and asks** when the list still holds a code file (item 5's case arriving late), and reports `ran nothing` with its reason when the assembled diff is doc-only and nothing was declared. `_shared/main-push-guard.md` Rule B re-runs *this* step, not step 3, when a rebase changes the base at step 8
6. **Close merged batches** — run `bash sysop/scripts/close_batch.sh <N1> <N2> ...` on the merge target to flip batch headers to `Merged`, check off task boxes (except any annotated `> Failed:`, which stay open), and update the Statistics table (always `--force` under `pr` policy — nothing has reached local `main` yet, so the script's `merge-base --is-ancestor <branch> main` gate would reject the close under either shape). This runs after merges but before doc consolidation
7. **Consolidate documentation** — **first drop any pending-doc whose branch did not actually merge** (`git rev-list --count "<branch>" "^HEAD"`; `0` = merged — and quote the `^` operand, which is a negated glob under zsh `extended_glob` and silently yields the wrong answer unquoted). **A non-zero count is not by itself a verdict:** it is an ancestry test, so a cherry-picked branch scores non-zero even when its content is fully applied — including the `branch: main` pending-doc that Step 4-pre's own `git cherry-pick origin/main..main` produces under `pr` policy. Fall back to `git cherry HEAD "<branch>"` and treat zero unapplied commits as *ask*, not *skip*. Step 4 copies each approved branch's pending-doc to main *before* attempting the merge, so a 4a-SKIP'd branch leaves one here — and consolidating it would route its content, flip its `roadmap_ids` to `done`, archive the body and drop the task's lock with the code never merged. Then parse each surviving `sysop/runtime/pending-docs/*.md` (YAML frontmatter, falling back to the legacy markdown format) and route its entries to the shared docs using the type-based routing table (§ 6.6): `PROJECT_STATUS.md` for all types, `CHANGELOG.md` for bugfixes (under `## [Unreleased]` — the Keep-a-Changelog contract shared with `/release`, Phase 222; **this is one of three paths into that file** — Step 4c also routes the §6 rotation and the wide-close consolidation there, independently of type, see § 6.6 and § 8.1), `UI_Iterations.md` for ui-iterations — and `tasks/index.yml` (flip `status: done` + set `completed_date`; `git mv` body to `tasks/archive/`) for **every ID in `roadmap_ids`, regardless of type** (§ 6.6's note; the type-conditional reading was BeanRider ISSUE-0034). The index rewrite is staged by the same code that writes it, the shared docs get one `git add` each, and the commit is verified afterwards — `git mv` stages but `write_text` does not, and `git add` aborts its whole invocation on a single unmatched pathspec, so a half-staged index is the easy failure here
8. **Land on main** — under `direct` policy, `git push origin main`. Under `pr` policy (required when `main` is push-protected by a required check and/or `enforce_admins`), push the merge target and squash-merge its PR with a normal authenticated `gh pr merge --squash` (**not** `--auto` — native auto-merge is paid-plan-only for private repos; the non-`--auto` path mirrors `/pr-dependabot`). **The verdict is the PR's `state`, read after the merge — never the command's exit status or stderr:** `gh pr merge --delete-branch` also does local housekeeping, and in the integration-branch shape its fast-forward of local `main` cannot succeed (the swept commits exist twice at different SHAs), so a `fatal: Not possible to fast-forward` on a merge that succeeded is expected there. (It does not appear in the PR-reuse shape, whose preconditions require local `main` to already match `origin/main`.) On a genuinely stuck PR (failing required check / `BLOCKED`) the skill reports the PR URL and stops — it never force-merges and never falls back to a direct push
9. **Verify deployment** — confirm the deployment target (staging/production) is healthy
10. **Clean up** — `direct`: delete merged branches (local + remote), remove `sysop/runtime/pending-docs/`. `pr`: only after the PR reported `MERGED` — re-sync local `main` to `origin/main` (load-bearing in the integration-branch shape — exactly the housekeeping `gh` just failed at — and a harmless no-op in the PR-reuse shape; run it either way), drop the integration branch if there was one, and drop the squash-merged feature branches — **iterate the branches step 5 actually merged, never "approved"**, since the force-delete is licensed by the branch being inside the squash and a 4a-SKIP'd branch is not, has no worktree left (step 4 removed it), and would lose its commits with the ref. **Do not try to re-derive that containment here:** after a squash the branch is provably *not* an ancestor of `main`, so every ancestry-shaped test (`rev-list ^origin/main`, `merge-base --is-ancestor`, safe `-d`) reports non-zero for a correctly merged branch and a skipped one alike — the skip verdict step 5 recorded is the evidence. If the PR is stuck, skip cleanup so the work stays recoverable

> **Note:** Convention promotion is NOT a `/review-close` step. It happens during `/codebase-review` and `/security-audit` Step 9, in the same session that extracts candidates. See § 2.5 step 9 and § 3.5.

**Inputs:** Feature branches, `sysop/runtime/pending-docs/*.md`
**Outputs:** Updated main branch, consolidated documentation, closed review batches, cleaned branch state
**Checks:** Code review, adversarial convention sub-agent review, CI verification, deployment health
**Feedback loops:** Convention enforcement via pre-commit hook checks (§ 5.2)

**Implementing skill:** `/review-close`

### 2.9 Cleanup

**Trigger:** Part of `/review-close`, or manual housekeeping.

**What happens:**
1. Remove merged and stale worktrees (ACTIVE ones are skipped): `bash sysop/scripts/cleanup_worktrees.sh --clean`
2. Delete merged feature branches (local and remote)
3. Remove orphaned lock files (locks whose branches no longer exist)
4. Archive completed review rounds (move merged batches from the live tracker to the archive file)

**Inputs:** Git worktree state, `sysop/runtime/locks/`, `review_tasks.md`
**Outputs:** Clean filesystem and git state

**Implementing scripts:** `sysop/scripts/cleanup_worktrees.sh`, `sysop/scripts/close_batch.sh`, `sysop/scripts/archive_review_tasks.py`

---

## 3. Convention System

The convention system is what makes this workflow self-improving. Without it, you run reviews, find issues, fix them, and find the same issues next time. With it, each review round teaches the system something new, and future code is checked against every lesson learned.

### 3.1 What conventions are and why they exist

A **prevention convention** is a codified rule derived from a recurring review finding. It has three properties:

1. **Imperative phrasing**: "All X must Y" or "Never do Z" — unambiguous, actionable
2. **Specific mechanism**: References the exact utility, helper, or pattern to use (e.g., "use the project's error-display helper from the shared frontend utilities module")
3. **Derived from experience**: Every convention exists because the same issue recurred across review rounds (3+ occurrences across different files in a round, *and* surviving into a second round) — not from a single noisy round

Conventions live in the project's CLAUDE.md file under a `## Prevention Conventions` section, organized by category (Frontend, Backend, Testing, or whatever categories fit the project). They are the project-specific rules — this workflow document defines the process for creating, scoping, and enforcing them.

**Example convention:**
```markdown
- **Error display**: Never render `err.message` directly. Use the project's error-display helper from the shared frontend utilities module.
```

### 3.2 Convention maps (scoping rules to files)

A **convention map** is a markdown file that maps file patterns to the subset of conventions relevant to those files. It lives at `.claude/convention_map.md`.

**Why scoping matters:** A project might have 50+ conventions. Showing all 50 to an agent reviewing a single component produces noise and false positives. The convention map says "when reviewing files matching `<components dir>/**/*.tsx`, check only these 7 conventions." This was learned through trial — unscoped reviews degraded review quality.

**Format:**
```markdown
# Convention Map

> Maps file patterns to relevant Prevention Conventions from CLAUDE.md.

## `<glob-pattern-1>`, `<glob-pattern-2>` — <Section Name>

- **<Convention name>**: <One-line actionable reminder>
- **<Convention name>**: <One-line actionable reminder>
```

Each section header contains one or more file glob patterns and a human-readable section name. Under each section, list the conventions that apply to those files as one-line reminders (not the full rule — the full rule lives in CLAUDE.md).

**How it's used:**
- **During planning** (§ 2.2): Look up conventions for files you'll modify, include in plan
- **During simplify pass** (§ 2.4): Cross-check diff against conventions for changed files
- **During review** (§ 2.5): Each review agent receives only the conventions from the map sections matching its file group
- **During merge** (§ 2.8): Reviewer cross-checks changed files against applicable conventions

**Coverage requirement:** Every code file in the project should be matched by at least one section. The map coverage audit (§ 3.6) checks this.

See § 6.2 for a blank template and worked example.

### 3.3 Security maps

A **security map** works like a convention map but focuses on security concerns. It lives at `.claude/security_map.md`.

**Format difference from convention maps:** Security maps have explicit **Check** and **Skip** subsections, both **glob-scoped** — a section binds only the files its globs actually match, so one still in placeholder form (`<api module>/`) confers neither. The "Skip" list is as important as the "Check" list — it prevents auditors from wasting time on threat categories that don't apply to a file area (e.g., SQL injection checks on pure frontend utilities).

```markdown
## `<glob list>` — <Section Name>

**Check:**
- **A03 Injection**: <What to look for in these files>
- **A07 Auth**: <What to look for>

**Skip:** A06 (dependencies), A10 (SSRF — no outbound HTTP)
```

See § 6.3 for a blank template and worked example.

### 3.4 Pre-commit enforcement (blocking vs advisory tiers)

A **pre-commit hook** catches convention violations at commit time — before code reaches review. It uses a two-tier pattern:

**Blocking checks** (exit code 1 — commit is rejected):
- High-confidence anti-patterns with very low false-positive rates
- Examples: f-string SQL with both DML and structural keywords, raw exception details in API responses
- Typically 3–5 checks in a mature project

**Advisory checks** (exit code 0 — warning printed, commit proceeds):
- Patterns that are usually wrong but have legitimate uses
- Examples: `fetch()` without `AbortController`, `window.open` without `noopener`
- Typically 5–10 checks in a mature project

**Design principles:**
- Only staged files are checked (`git diff --cached --name-only --diff-filter=ACM`)
- Checks are filtered by file type (Python, TypeScript, test files)
- An escape hatch exists for legitimate bypasses: `PRE_COMMIT_ADVISORY_ONLY=1 git commit ...`
- Blocking checks are added only after the pattern has caused data integrity or security issues. Default new checks to advisory

**How checks get added:** During convention promotion (§ 2.5 step 9 / § 2.6 step 5, promotion sub-step a, option iii), the reviewer evaluates whether the anti-pattern is detectable via simple regex. If yes, they draft a check following the existing hook format and add it to the appropriate tier.

See § 6.4 for a hook template.

### 3.5 Convention promotion lifecycle

This is the process by which a review finding becomes an enforceable rule. It is the core feedback loop of the system.

**Extraction** (during review — § 2.5 step 8; § 2.6 step 5, whose condensed list bundles the shared structure's steps 6–9):
1. After writing all review tasks, scan findings for recurring patterns (3+ occurrences across different files, or systemic gaps not covered by existing conventions)
2. Draft a candidate convention bullet following the existing format
3. Draft a one-line convention map entry and list the map sections it should be added to
4. Write candidates to `sysop/runtime/pending-docs/convention-candidates.md`, each **attributed to the current review round** (the attribution is what makes the cross-round gate below computable)

**Promotion** (during a review session — § 2.5 step 9, § 2.6 step 5):
1. Reviewer evaluates each candidate interactively against the **cross-round survival gate**: promote only if the pattern has recurred across two review rounds — present in *this* round's findings **and** in an earlier round's archived `review_tasks.md` (recurrence is *computed* from that durable record each round, not maintained as a carried-forward watch-list — see the precondition below). A 3+-occurrence burst confined to a single round makes a strong *candidate*, not a promotion trigger on its own — waiting one round filters out one-off noisy rounds. A candidate that doesn't clear the gate is simply left unpromoted; this round's attributed findings become part of the durable record from which a later round recomputes recurrence.
2. For promoted candidates:
   a. **Choose enforcement mechanism (mechanical-first).** Walk this menu in order; stop at the first option that fits:
      - **(i) `.claude/checks.yml` regex** — single-line grep with low FP rate, gated at CI / `run_checks.sh`. Reviewer chooses `[yes-blocking / yes-advisory / skip]`; `blocking: true` requires zero verified FPs.
      - **(ii) `.claude/semgrep/*.yaml` AST rule** — needs structural awareness (function args, decorators, control flow). Reviewer chooses `[approve-with-fixture / approve-no-fixture / skip]`; fixture is the regression lock.
      - **(iii) `sysop/scripts/hooks/pre-commit` regex** — same regex shape as (i) but fires in the editor cycle. Choose (iii) when local feedback matters; (i) when CI is the canonical gate; both is acceptable.
      - **(iv) Prose fallback in CLAUDE.md** — only when the rule needs semantic reasoning. Canonical fallback list: audit-trail symmetry, tier enforcement, response filtering, rate-limit coverage, error caching. Anything else, the reviewer must justify why (i)–(iii) all fail before reaching for (iv).
   b. **If mechanical (i/ii/iii):** the check IS the rule. Add a one-line `> AST-backed equivalent: <rule-id>` (or analogous `> checks.yml: <id>` / `> pre-commit: <letter>`) reminder to every matching section of `.claude/convention_map.md`. Skip the CLAUDE.md prose insertion.
   c. **If prose-fallback (iv):** insert into the correct subsection of CLAUDE.md `§ Prevention Conventions`, then add a one-line reminder to every matching section of `.claude/convention_map.md`.
   d. **Sweep for existing violations**: Derive a grep pattern (or, if the rule was already mechanized via a.i / a.ii, use the rule's first-run output). Search relevant directories for the anti-pattern. The decision prompt fires regardless of mechanical vs prose:
      - **Fix inline** (≤15 hits, mechanical): Apply the fix immediately
      - **Generate batch**: Create a review batch for the violations
      - **Skip**: Note the violation count and move on
3. Emit a one-line `Promotion summary: <N> total (<M> mechanical / <K> prose)` (printed to terminal and included in the commit message body — see step 4).
4. Delete `sysop/runtime/pending-docs/convention-candidates.md` and commit the CLAUDE.md / convention map / checks / hook updates in a single `docs: promote <N> conventions from Round <N>` commit with the promotion-summary line in the body.

> **Where promoted content is written — consumer install vs. source repo (`_shared/promotion-write-target.md`):** the three concat-managed base maps (`.claude/convention_map.md`, `.claude/security_map.md`, `.claude/checks.yml`) are **regenerated from Sysop's core + pack sources on every `sysop-update.sh`** in a consumer install (§ 8.2c), so a promotion written only to a base map is silently lost on the next update. In a consumer install — detected by the presence of `.claude/sysop.lock` — the review skills **dual-write**: the base file (live effect this round + the cross-round recurrence gate reads it) **and** the never-managed `.project.*` overlay sibling (`.claude/checks.project.yml`, `.claude/convention_map.project.md`, `.claude/security_map.project.md`), which the installer re-appends / re-merges into the base every update. A new `.claude/semgrep/*.yaml` rule, a `sysop/scripts/hooks/pre-commit` letter, and a `CLAUDE.md` prose bullet need no overlay mirror (the installer never overwrites an unshipped semgrep filename; `sysop/scripts/hooks/*` is a preserved managed path per Phase 24b; `CLAUDE.md` is the consumer's own file). Demotion (§ 3.5b) retires the rule where it durably lives — the overlay for a locally-promoted rule, an override entry for a core/pack-shipped one. In the **source repo** (no lock — Sysop's own tree, or a project authoring maps in place) there is no overlay and no regeneration; the base writes are the whole story. The overlay is also the **read source for `/contribute-convention`** — the give-back transport that generalizes a consumer's locally-promoted conventions to placeholder vocabulary and files them upstream as pack/convention proposals (the convention sibling of `/report-issues`; base maps are never read as a contribution source — they are already upstream).

> **Why promotion runs in-session:** Deferring promotion to merge meant the reviewer had lost context about which findings drove which candidate by the time they ran `/review-close`. Promoting in the same review session — the one that confirms the pattern recurs — keeps the reasoning trail intact and closes the feedback loop faster.

> **Why cross-round survival (not in-round burst):** Promotion gates on a pattern *recurring across two review rounds*, not on a single round's 3+-occurrence burst. The burst over-promotes on a noisy round; surviving into a second round is higher-precision — the right trade for a high-signal 78-entry map where every prose bullet costs per-prompt context. **Precondition:** this gate is only computable because prior-round findings stay durably queryable — round-attributed convention-map entries plus archived `review_tasks.md` rounds. That keeps the loop "compute over maintain" (recurrence is *derived* from the durable record each round) rather than an agent-memory ledger the reviewer has to carry between sessions. If that record stops being queryable, the gate silently degrades to in-round.

> **Why mechanical-first:** Each prose bullet in CLAUDE.md `§ Prevention Conventions` expands the per-prompt LLM context budget the model must hold during every future code-generation and review pass. Mechanical checks (`.claude/checks.yml`, `.claude/semgrep/*.yaml`, `sysop/scripts/hooks/pre-commit`) block at CI or commit time with no per-prompt context cost. Prose remains the right choice only when the rule requires semantic reasoning that a regex or AST pattern cannot capture — the canonical fallback list (audit-trail symmetry, tier enforcement, response filtering, rate-limit coverage, error caching) names the rule families where this is genuinely true. The promotion-summary `Promotion summary: <N> total (<M> mechanical / <K> prose)` line in commit messages is the validation signal: `git log --grep "Promotion summary"` shows the mechanical-vs-prose ratio over time. If the ratio doesn't shift after this default flips (2026-04-30), the prompt edits aren't strong enough and need tightening.

**What makes a good convention candidate:**
- Recurs — 3+ occurrences across different files in a round, *and* the pattern survives into a second review round (not a one-off mistake, not a single noisy round)
- Has a specific, actionable remedy (not "write better code")
- References a concrete utility, helper, or pattern
- Can be explained in one sentence

**What is NOT a convention:**
- Architecture decisions ("use React for the frontend")
- Style preferences ("use single quotes")
- One-time fixes ("fix the bug in auth.py line 42")

### 3.5b Convention demotion lifecycle

The symmetric counterpart to § 3.5 — the loop that *removes* a rule the codebase has outgrown. Promotion has a rich pipeline; for a long time demotion had none, so conventions could only enter the maps, never leave. A convention is real at promotion and stays real until a **specific change event** invalidates it — staleness is event-driven, not time-driven (there is no "re-confirm everything every N months" calendar audit). Two halves catch the two kinds of staleness:

- **Static map staleness (Tier 1 — § 3.6 check 4, run at every review round's map audit, § 2.5 step 3 / § 2.6 step 2):** a map section whose glob matches zero tracked files (removed category, Mode C) or a bullet citing a now-absent helper (dead reference, Mode B). Detected deterministically by `git ls-files` / `git grep`; refreshed inline (helper renamed) or routed to the human for retirement (category removed — handed to the Tier 2 decision step below, which adjudicates it via static detection, not the ledger).
- **Behavioral FP staleness (Tier 2 — § 2.5 step 9b / § 2.6 step 5; the review skills' Step 9b):** a *blocking-mechanical* rule (`checks.yml` regex, `semgrep` rule, `pre-commit` letter) that keeps firing on matches that are **no longer violations** because its convention moved out from under it. The map sweep cannot see this — the rule's *referent* still exists; what changed is that the rule is now wrong about it. This is the expensive staleness: a stale blocking rule halts every commit that touches the scoped code, and the second-order cost is alert fatigue → a `--no-verify` suppression reflex that erodes trust in the whole gate.

**Change-event taxonomy** (what invalidates a convention): **A** default-moved (a library default changes) · **B** dead-reference (cited helper renamed/deleted — Tier 1 detects) · **C** category-removed (a migration deletes the scoped surface — Tier 1 detects) · **D** superseded (a prose rule later mechanized, leaving the bullet duplicative) · **E** version-fix (a dependency bump past a vuln/behavior moots an often-security rule) · **F** floor-moved (a platform/policy floor changes) · **G** over-broad-from-birth (a calibration miss that presents like staleness — fix by tightening, not retiring).

**The Tier 2 pipeline:**
1. **Capture (review triage at the pre-scan — § 2.5 step 4; the review skills' Step 2b):** every prescan hit already earns a real-vs-stale verdict during triage; the "stale" verdict — normally discarded — is recorded as one row per (rule, round) in a `## Convention fire ledger` section of `review_tasks.md`.
2. **Cross-round gate (step 9b):** a rule with stale-verdicts in **2+ distinct rounds** is a retirement candidate — the exact mirror of promotion's cross-round survival gate (a single-round burst is held, filtering one-off noisy rounds).
3. **Interactive decision (step 9b):** `[retire / demote-to-advisory / tighten / keep]`. Retire removes the rule + its convention-map reminder (and, rarely, a promoted prose bullet); demote-to-advisory flips `blocking: true → false` (de-fangs the halt, keeps the signal — the lower-regret middle); tighten narrows an over-broad-from-birth rule (Mode G); keep overrides the signal. Every disposition clears that rule's ledger rows. Security rules confirm the protection moved elsewhere before retiring (Mode E version-fixes are the common security case; a missed true positive on a security rule has production impact, so bias toward keeping).
4. **Trailer:** emit `Demotion summary: <N> retired (<B> blocking / <A> advisory-or-prose)` in the commit body — grep-auditable via `git log --grep "Demotion summary"`, mirroring `Promotion summary:`.

> **The one principled asymmetry — why demotion *maintains* a ledger while promotion *recomputes*:** Promotion is "compute over maintain" because a true positive becomes a durable task in `review_tasks.md`, so recurrence is re-derived from that record each round with no carried-forward watch-list. A *stale* positive becomes **nothing** — the match is judged a non-violation and dropped — so its verdict has no durable home unless one is made. The fire ledger is that minimum home, and it is deliberately bounded: a rule's rows are cleared the instant step 9b adjudicates it, so the ledger only ever holds un-adjudicated stale-verdicts accumulating toward the gate.

> **Why FP cost concentrates in the blocking-mechanical layer:** A stale *prose* bullet never halts you — it is a few glob-scoped tokens the model usually ignores (cost: slow accumulation, occasional misdirection). A stale *blocking mechanical* rule halts a commit/CI on every touch of the scoped code and trains the suppression reflex. That is why Tier 2 targets blocking rules specifically, and why **demote-to-advisory** exists as a first move short of full retirement.

**Tier 3** (a periodic prose-relevance audit + a dependabot-hooked re-confirmation of version-pinned conventions, for the change events A/E/F that have no static signal) is noted-not-built — speculative, low cost-of-inaction.

### 3.6 Map coverage auditing

Map coverage auditing ensures no code files fall through the cracks — every file should have conventions checked during review.

**Forward checks (under-coverage — code the map misses):**

1. **Files not matched by any convention map section**: Parse section headers from `.claude/convention_map.md`, cross-reference against actual code files (`git ls-files`). Collect unmatched files. Exclude config-only files, docs, data files, and small stable utilities.

2. **Files not matched by any security map section**: Same process for `.claude/security_map.md`.

3. **Convention bullets not in any map section**: Read CLAUDE.md `§ Prevention Conventions`. For each bullet, check if its bold prefix appears in any convention map section. Collect orphaned bullets.

**Backward check (staleness — map content the code has outgrown):**

4. **Stale sections and dead citations**: The reverse direction — for each map section, `git ls-files -- <section globs>`; a section matching **zero** tracked files is a removed-category candidate (staleness Mode C). For each bullet citing a concrete in-repo helper, `git grep -nw` the symbol; zero hits means a renamed/deleted referent (staleness Mode B). Flag candidates only — never auto-retire. Distinguish *refresh* (helper renamed → update the citation) from *retirement* (category gone → route to the human), and rule out relocation, aspirational/lead sections, un-substituted placeholders, and over-broad-from-birth globs (a calibration miss → tighten, don't retire). Catches the statically detectable staleness only; the FP-driven demotion of blocking rules is the demotion plan's Tier 2 (now active — see § 3.5b, step 9b). This is the *detection* half of convention demotion; § 3.5b is the *behavioral* half — together the symmetric counterpart to the promotion lifecycle in § 3.5.

**When it runs:**
- Before every review round (§ 2.5 step 3, § 2.6 step 2) — offers to fix gaps and refresh stale citations inline; routes genuine retirement candidates to the human
- During planning (§ 2.2 step 7) — for new files being created

**Why it matters:** If a file isn't matched by any map section, review agents won't receive any conventions for it — the file gets a free pass, and violations accumulate undetected. The forward checks prevent that silent degradation. The backward check prevents the opposite rot: a map entry whose code disappeared keeps misdirecting agents and erodes trust in the map. Auditing both directions every round keeps the map honest as the codebase moves.

---

## 4. Infrastructure

### 4.1 Worktree isolation

**Problem solved:** When multiple tasks are in progress (or when you want to switch between tasks), `git checkout` in a shared directory causes conflicts — unstaged changes block checkout, and file state gets mixed between tasks.

**Solution:** Each task gets its own git worktree — a separate filesystem directory that shares the repository's history but has independent checked-out files.

**How it works:**
- `bash sysop/scripts/claim_task.sh <TASK_ID> <BRANCH>` creates a worktree at `../<project>-<task-id>/`
- `bash sysop/scripts/claim_task.sh --entry-state <TASK_ID>` (Phase 159b) adjudicates a claim **before** anything is created. Read-only — it mutates nothing — and prints exactly one token: `claimable` (open, no lock), `resumable` (`in_progress` with **no** lock), `held` (`open`/`in_progress` *and* a lock), `closed:<status>`, or `absent`. Note the precedence: a closed status wins over a leftover lock, so a `done` task with a stale lock answers `closed:done` rather than `held`. `/claim-task` Step 2 gates on it. **`resumable` means stop and ask, not resume:** under `§ Merge policy: pr`, `/review-close` unlinks the lock on the integration branch before the PR merges while the `done` flip rides that PR, so on `main` a finished task reads `in_progress`-with-no-lock for the whole life of the PR — resuming there re-claims already-reviewed work. Refuses a `BATCH-*` id and a bare integer (a batch's claim state lives in `review_tasks.md`, not `tasks/index.yml`)
- Work happens in the worktree directory, not the main repo directory
- `bash sysop/scripts/cleanup_worktrees.sh --clean` removes worktrees whose branches have been merged, plus STALE ones whose directory is already gone; it skips ACTIVE worktrees and deletes each removed branch with the safe `git branch -d`
- `bash sysop/scripts/claim_task.sh --release <TASK_ID>` reverses a claim (un-claim): from the main checkout it removes the worktree recorded in the lock (never the main worktree; refuses a dirty worktree without `--force`), flips the task's `status: in_progress → open` in `tasks/index.yml` via a PyYAML round-trip (never a hand-edit — so the queue stays validator-clean; degrades to printed manual steps if PyYAML is absent), and deletes the lock. `--delete-branch` also drops the feature branch. It runs `validate_tasks.py` and prints the commit but never commits — the sanctioned owner for the `in_progress → open` flip plus the lock release

**Worktree states:**
- **MAIN**: The primary repository directory (never touched by cleanup)
- **MERGED**: Branch is ancestor of main (safe to remove)
- **ACTIVE**: Has uncommitted changes or untracked files (skipped by `--clean`)
- **STALE**: Directory missing (auto-pruned)

**When to use:**
- Default for all tasks. Creates filesystem isolation with no overhead
- Only use `--branch` mode (shared directory, separate branch) when you are the sole session working in the directory and explicitly want to avoid the worktree

**Lock file coordination** (for parallel agent work) is an optional extension not covered here. It uses YAML lock files in `sysop/runtime/locks/` to track which files each agent is modifying, enabling conflict detection at claim time. Lock files use `claim_task.sh --lock` to create `sysop/runtime/locks/<TASK_ID>.lock` files with task ownership metadata.

**Both claim kinds write one** (Phase 156). A review batch is locked at `sysop/runtime/locks/BATCH-<N>.lock`, in the same directory and the same file shape, written by `batch_work.sh` and removed by `close_batch.sh` at close or `batch_work.sh --release` on abandonment. **The removal is gated on the close having landed on `main` in the main checkout**, because the lock is main-repo-global while the `Merged` flip is branch-local: under `pr` policy the close commits to the integration branch, and releasing there would advertise the batch as claimable while its work sat on an unmerged PR. The lock is therefore the one identifier a batch claim and a roadmap claim share — `review_tasks.md` and `tasks/index.yml` have nothing in common — which is what lets `next_task.py`, `sitrep_survey.py` and `scope_overlap.py` treat the two kinds uniformly. Four readers had already been written against that file before anything produced it: `next_task.py`'s in-flight batch filter, `sitrep_survey.py`'s `has_lock` batch classifier and its orphan-worktree probe, and `scope_overlap.py`'s in-flight set. A fifth was in prose — `/claim-task` Step 2 told the agent to check `BATCH-<N>.lock` before claiming. All five read a file that never existed, and each failed *open*: `/next-task` handing out an in-flight batch, `/sitrep` reporting a live batch worktree as an orphan and its batch as unclaimed, and collision advisories blind to batch work. Locks live under the **main** repo root (resolved via `git rev-parse --git-common-dir`) regardless of which worktree the script was invoked from; the validator (`sysop/scripts/validate_tasks.py`) uses the same resolution so every caller — pre-commit hooks inside worktrees, `/review-close` from main, ad-hoc CLI invocations — agrees on one canonical lock state (Phase 32, 2026-05-22 — closes BeanRider ISSUE-0028 / 0030 / 0032 / 0013).

### 4.2 Task tracking (review_tasks.md format)

> **Scaling note:** The Round/Batch structure described here is useful once the review task tracker grows past ~50 tasks. For smaller or newer projects, a flat checklist of tasks suffices — adopt this format when the flat list becomes hard to navigate.

Review tasks are tracked in a markdown file (`review_tasks.md`) organized into **Rounds** and **Batches**.

**Structure:**
```markdown
## Round N: <Theme> (YYYY-MM-DD)

> **Coverage (<audit type>):** <Full | Scoped (<area>) | Sampled (<basis>)> · manifest <N> · opened <M> · grepped <G> · workers <K><, solo: <reason>>

### Batch <N> — <Title> `<Status>`

> **Branch:** `<branch-name>`
> **Scope:** <files affected>
> **Verify:** `<test command>`
> **Overlap:** <none | batch-N, batch-M>

- [ ] **TASK-NNN**: <description> <severity-emoji>
- [ ] **TASK-NNN**: <description> <severity-emoji>
```

**Quoting an example batch inside a task body — indent it two spaces, and close the fence.**

A parser cannot tell a fenced `### Batch <N>` from a real one once the fence is left open: an unterminated span runs to end-of-file, so a documentation example and a real batch written *below* a stray fence are textually identical. Phase 208 measured a detector that tried to separate them false-firing on 98.2% of opener positions on a real tracker. Two rules follow, and the first is the one to reach for:

- **Indent the example by two spaces.** `### Batch` is matched at **column 0 only**, so a two-space-indented example is invisible to every reader — `batch_work.sh`, `close_batch.sh`, `review_index.py`, `next_task.py`, `sitrep_survey.py` and `archive_review_tasks.py` alike. It needs no fence at all, and it is the only form that cannot be misread.
- **If you do fence one, close the fence.** A tracker carrying an unterminated fence with a batch header anywhere below it is **refused** by the claim, close and release paths (exit 5) — otherwise that header is claimable, and `batch_work.sh` will create a branch, a worktree and a lock against a batch that does not exist. Closing the fence clears it. If the tracker really is correct as written, `--allow-open-fence` proceeds — a **dedicated** flag, deliberately not `--force`: `--force` means "skip the merge-base ancestry check" on the close path, and `/review-close` Step 4b mandates it for every `pr`-policy consumer, so binding the escape to it would disarm this gate for exactly the consumers it protects.

Two narrower cases, so the rule is not read as wider than it is: a fence whose span contains **no** batch header is not refused (quoting a `> **Flag:**` example is fine), and a **collision** — a fenced header whose number also appears outside the fence — is refused at exit 3 and is **not** forceable, because there the fenced copy provably overwrites a real batch.

**Round metadata — the coverage ledger.** The `> **Coverage (…)**` line is the round's **Tier-0 ledger** (`_shared/fanout-evidence.md` § Tier 0) and is mandatory on every round. It records what the round actually reached: `manifest` = the files this round declared in scope after exclusions (**not** the repository total, unless the round was a full scan), `opened` = files whose bodies were read — **on a fan-out round, the deduplicated union of the orchestrator's own reads and every worker's enumerated `Opened` list; not a sum of the footers, and not the orchestrator's reads alone** (`_shared/fanout-evidence.md` § Tier 0 states the derivation and what a missing footer contributes) — `grepped` = files reached by search only (counted separately — grep is looking, not reading; it has no per-worker twin in the evidence footer, so it does not aggregate), `workers` = sub-agents dispatched, with a stated reason when it is `0`. A field the round cannot fill is written `unreported`, never left blank. A round merging two audit types carries one coverage line **per type**; neither overwrites the other.

Why it is mandatory: a manifest size stated alone reads as coverage. A measured round on a 1,561-file repository reported "1,477 reviewable files" in this header having opened 13 of them, and nothing downstream could tell that apart from a full scan — the ledger's job is to put `opened` beside `manifest` where the contradiction is visible. `sysop/scripts/self_check.sh` and `/sitrep` read the same numbers from the round receipt the skills write at close (`sysop/runtime/round-receipts/`, gitignored).

**Batch status values:** `Pending` → `In Progress` → `Review Ready` → `Complete` | `Merged` | `Ready for Review`

> **The two near-identical names are opposites, and this list is the § 8.4 declaration restated (Phase 222, Q-014).** `Review Ready` is **live** — the review work is done on the batch's branch and a human needs to act (`/review-close`); `batch_work.sh` calls it *"the one status that needs someone to act"*. `Ready for Review` is **terminal** — a finished batch, grouped with `Complete`/`Merged` by every shipped reader (`close_batch.sh`, `batch_work.sh`, `/claim-task`, the orchestrator skip lists). Take the live/terminal split from the scripts' declaration, never from the names.

**Batch metadata fields:**
| Field | Purpose | Used by |
|-------|---------|---------|
| `Branch` | Git branch for this batch's fixes | `batch_work.sh`, `/auto-fix` |
| `Scope` | Files affected | `/auto-fix` (agent prompt) |
| `Verify` | Test command to run after fixing | `/auto-fix` (CI gate) |
| `Overlap` | `none` \| `batch-N, batch-M` — batches that touch the same files | Written by `/codebase-review` + `/security-audit` only. Read by `/auto-fix` and `/auto-judge` (parallel vs sequential lane), `/triage` (candidate notes), `review_index.py` (stored, unread) |
| `Flag` | Why this batch needs manual work | Written by `/triage` only. Read by `/auto-judge` (pool), `/auto-fix` (skip), `/sitrep` |
| `Triaged` | `<YYYY-MM-DD> <auto\|flag> [TASK-…]` — when the batch was classified, the verdict, and which tasks need judgment | Written by `/triage` only. Read by `/triage` (skip re-analysis), `/auto-fix` + `/auto-judge` (Step 0.5 triage prereq), `/auto-judge` (judgment set), `/sitrep` (priority 4a) |

**`Flag` and `Triaged` have one writer — `/triage`** (`triage/SKILL.md` § Writer-side contract). The review generators (`/codebase-review`, `/security-audit`) emit neither: a batch arrives with no verdict because a generator has not made one. A `Flag` line with no `Triaged` sibling records no verdict. `/triage` and `/sitrep` therefore treat that batch as **untriaged** and re-read it; `/auto-fix` and `/auto-judge` still take their *pool* membership from `Flag:` presence alone, which is unchanged, but their triage prereq keys on the `Triaged:` record.

**`Overlap` has two writers and a whole-value read.** The review generators (`/codebase-review`, `/security-audit`) compute it at their Step 4b and are its only writers; nothing else may author the line. The grammar is exactly two shapes — the literal `none`, or a comma-separated list of `batch-<N>` references — and that grammar is what the readers are entitled to assume — a value outside it is not an alternative spelling, it is an unparseable value and is treated as one.

Readers apply a **whole-value** test, never a substring one: a batch routes to the parallel lane **only when the value, trimmed of surrounding whitespace, is exactly `none`**, and **every other value — including one that merely starts with `none`, an unparseable value, and a value in a shape this table does not declare — routes to the sequential lane.** That default is deliberate and it is asymmetric on purpose: serialising a batch that could have run in parallel costs wall-clock, while parallelising a batch that really does overlap costs a merge conflict and the rework behind it. When the field cannot be trusted, the cheap wrong answer is the safe one. **Existing trackers need no migration:** a batch tagged with bare numbers (`701, 702`) — the rendering `/auto-fix`'s and `/auto-judge`'s fallbacks compute, and the one older batches carry — is an undeclared shape, so it routes to the sequential lane, which is exactly the lane a correctly rendered `batch-701, batch-702` would have routed it to. The grammar binds what writers **emit**; the only already-written values whose lane changes are the ones a *substring* reader was routing **wrong** — and that reclassification is the fix, not a migration cost. The failure this closes is a value like `> **Overlap:** none (batch 5 shares tests/)`, which a substring reader routes to *parallel* — the opposite of what its author meant.

**What is not guaranteed: the value is trusted, not verified.** No site validates `Overlap:` when it is written, and no reader recomputes it — the `/auto-fix` and `/auto-judge` fallbacks at their Step 4a compute overlap only when the tag is **absent**, hold the result in memory, and never write it back, so a tag that is *present and wrong* is never corrected. A generator that computes the overlap set incorrectly therefore produces a wrong lane assignment that nothing downstream can detect. Recomputing rather than trusting is the only fix for that half, and it is not implemented. `review_index.py` parses the line into the shadow index's `overlap` key, which **no consumer reads** — do not mistake that parse for validation.

**Task severity emoji:**
- 🔴 Critical (security, data integrity)
- 🟡 Warning (convention violation, code quality)
- 🟢 Advisory (style, minor improvement)

**Scaling:** When the tracker gets large (**~125KB** is the historical rule of thumb), archive merged rounds to a separate file (`review_tasks_archive.md`) using `sysop/scripts/archive_review_tasks.py`. Not needed until you have 50+ batches.

**No skill refuses to run above that size.** `/triage`, `/auto-fix` and `/auto-judge` each used to halt there and send the operator to the archiver — a dead end whenever the overflow was *open* work, because `archive_review_tasks.py` selects what to relocate by **merge status**, not by size (it matches only `Merged` / `Complete` — a Round moves whole only when every batch in it is merged, otherwise the merged batches move individually), so it reclaims nothing from a queue of `Pending` batches. All three now read the tracker through a cheap index pass (`grep` for batch headers and `> **Key:**` metadata lines) plus a line-bounded body read of only the batches they will act on, so size does not gate them; above the threshold they print an advisory naming the real lever — close open batches, *then* archive — and continue. Archival remains a manual housekeeping step throughout.

**Shadow JSON index:** `sysop/scripts/review_index.py` maintains a shadow JSON index of `review_tasks.md` at `.claude/review_index.json`, auto-rebuilt when the Markdown changes (checksum-based drift detection). The Markdown remains the human-readable source of truth; the JSON is the machine-readable interface. After any Markdown mutation, the mutating script rebuilds the index.

**Which readers actually use it.** The shell scripts `batch_work.sh` and `close_batch.sh` read the index by shelling out to `review_index.py`. The other Python readers — `next_task.py`, `sitrep_survey.py` and `archive_review_tasks.py` — parse the Markdown directly, each with its own copy of the fence-masking logic, which `tests/test_flag_contract.py` pins byte-identical across all four modules. Their **batch-header** patterns are NOT pinned and are NOT identical (`next_task.py` tolerates an ASCII hyphen; `archive_review_tasks.py` matches only terminal statuses), so do not assume a change to one reaches the others, and do not assume a change to the index format reaches any of them.

> Two claims previously stood here and were false: that consuming scripts read the index *"instead of parsing Markdown directly"* (three of them parse it directly), and that the shell scripts *"fall back to inline regex parsing if Python is unavailable"* (`batch_work.sh`'s inline parser was retired — it is now an error, not a fallback; `close_batch.sh` retains a grep-based range fallback only).

**The canonical batch header, and what happens to a line that misses it.** The one spelling is the batch template shown above and repeated in § *Batch metadata format* below — ``### Batch <N> — <Title> `<Status>` `` with an **em-dash (U+2014)** and a **backticked status as the last token on the line**. Both operational writers (`/codebase-review`, `/security-audit`) emit exactly that.

A header that misses it is a **near miss**: it is not a batch to any strict reader, so it is never claimed, never counted and never archived — and before Phase 220 nothing said so. The failure was silent in every direction, and the readers disagreed about which lines were affected, so the same tracker produced different answers depending on which tool ran:

- `close_batch.sh`'s grep range fallback matches a near-miss header and **closes the batch**, while `batch_work.sh` refuses to claim it — reachable on a perfectly healthy install, not only when `python3` is missing.
- `review_index.py --check-duplicates <N>` answered `batch <N> unambiguous` over a near-miss line, while `next_task.py`'s duplicate warning names that check as *the authority*.
- `archive_review_tasks.py` counted the line as a batch but could not read its status, so a round archived **partially**: the readable batches relocated into the archive, the Grand Total stamped the round `Complete`, and the near-miss batch stayed in the tracker under a duplicate `## Round` header.

**The canon is enforced by detection, not by widening the readers.** Widening them to accept an ASCII hyphen would make every currently-invisible header appear at once across `/sitrep`, `/next-task`, `/roadmap`, `/triage`, `/auto-fix` and `/auto-judge`, on consumer trackers nobody can migrate — no shipped tool MIGRATES header spellings in `review_tasks.md` — the three that rewrite it only ever touch a status token or relocate a round — and `install.sh`'s never-sweep guard names the file explicitly. Making work *appear* silently is the same defect as making it disappear silently. So instead:

```bash
python3 sysop/scripts/review_index.py --check-headers   # exit 6 if any near miss
```

`archive_review_tasks.py` **refuses to run** while any near miss exists (whole-run, ahead of `--dry-run`), and `close_batch.sh` **still closes** a near-miss batch but now says which resolver answered and counts it in its summary. Examples inside a **balanced** fence, and two-space-indented ones, are excluded — so an ordinary documentation block is not reported. An *unterminated* fence is deliberately ignored by the shared fence mask (honouring one would disable parsing to end-of-file), so its contents ARE reported; `--check-fences` is the surface for that condition.

### 4.3 Git hooks (pre-commit + pre-merge)

Two hooks gate code quality:

**Both hooks ship as skeletons.** The armed files run, but their check bodies are commented-out templates until your project fills them in — a fresh install blocks nothing at commit or merge time. That is deliberate (§ 7's Day-1 framing: checks accrete as the promotion loop adds them), but don't mistake an armed skeleton for an armed gate.

**Pre-commit hook** (`sysop/scripts/hooks/pre-commit`):
- Runs blocking and advisory checks on staged files as they accrete (see § 3.4; the shipped example checks are commented out)
- Installed via `sysop/scripts/install_hooks.sh`
- Shared by every worktree — see **Installation** below

**Pre-merge hook** (`sysop/scripts/hooks/pre-merge-commit`):
- Runs before any merge to main
- Template checks (shipped commented out — uncomment and adapt):
  - If Python files changed: runs `pytest`
  - If frontend files changed: runs production build
  - Advisory (non-blocking): warns if source files changed but no test files changed in the same branch
- Bypass (not recommended): `git merge --no-verify`

**Installation:** the hooks are tracked in `sysop/scripts/hooks/` and copied into git's hooks directory by `bash sysop/scripts/install_hooks.sh`. `install.sh` arms them as its final step on a fresh install, so most consumers never run it by hand; run it after cloning the repo, and after reconciling `sysop/scripts/hooks/*` following an `--update` (Phase 15 / ISSUE-0007 deliberately does not re-arm). `bash sysop/scripts/self_check.sh` reports which hooks are currently armed.

**Worktrees do not need their own install** (Phase 150 / internal tracker #202). By default all worktrees of a repo share one hooks directory — `$(git rev-parse --git-common-dir)/hooks` — so a worktree already runs whatever the main checkout has armed. (A `core.hooksPath` moves that target, and a *relative* one is resolved per-worktree — see the paragraph below. The conclusion holds either way: Sysop does not write into a configured hooks path at all, so a worktree still needs no install of its own.) Arming *from inside* a worktree is worse than redundant: `install_hooks.sh` reads its source from the worktree's own toplevel, so it pushes that branch's `sysop/scripts/hooks/*` into the shared directory, silently replacing the main checkout's armed checks with whatever the branch happens to carry — the shipped skeletons, for a consumer who never adopted the Sysop hook frame. `claim_task.sh` and `batch_work.sh` used to do exactly this on every worktree creation; they no longer arm at all.

**If you set `core.hooksPath`,** git stops reading `.git/hooks/` entirely and Sysop stays out of the way: `install_hooks.sh` and `install.sh`'s auto-arm both skip with a note, and the armed-hook divergence check reports the arrangement instead of a remedy that would do nothing. That directory is yours — usually tracked in your own tree, which is the reason to set it. To adopt Sysop's templates there, copy them in yourself. Note that a *relative* `core.hooksPath` is resolved by git from the top of the working tree, so each worktree resolves it against its own checkout — hooks at the branch's revision, with no install step and no stale copy.

### 4.4 Working alongside a running build

Because every task builds in its own worktree (§4.1), you can keep working while a build — a single `/claim-task` or a whole `/auto-build` batch — is in flight. This section is the operating model: where the work physically lives, what you can safely do in a second session, and the ceilings on running more in parallel.

**Work happens in three places.** Understanding this is the whole trick:

1. **The primary checkout** (`~/Projects/<app>/`, on `main`) — your original clone. It holds the `/auto-build` orchestrator and is where `/review-close` merges finished branches. Very little *code* is written here; it's the hub, not a workbench. Its `HEAD` should stay on `main`.
2. **One worktree per task** (`~/Projects/<app>-<task-id>/`, on the task's branch) — a separate directory that shares the repo's history but has its own checked-out files and its own `HEAD`. This is where building agents actually edit code. Two tasks that touch the same file can't corrupt each other, because they're editing two different directories on two different branches.
3. **Two coordination files**, both read by every session: `sysop/runtime/locks/<TASK-ID>.lock` (the claim registry — who owns what; lives under the main repo via `git rev-parse --git-common-dir`, §4.1) and `tasks/index.yml` status (`open` / `in_progress` / `done` — the source of truth for what's claimable). A task that's `in_progress` **and** locked is being built right now.

**What you can safely do while a build runs:**

| Move | Tool | Why it's safe |
|---|---|---|
| Brainstorm, read, plan | any session | Reads nothing the builds are writing. |
| Add a task | `/add-task` (or `/intake`) | Append-only to `tasks/index.yml` + a new body file, left uncommitted; touches no existing status and no lock. |
| Start new work | `/claim-task <TASK-ID>` | Checks the lock first, then builds in a *fresh* worktree, leaving `main` untouched. |
| Run a parallel batch | `/auto-build` | Its candidate filter excludes already-locked tasks, so a second batch naturally picks a disjoint set. |
| Merge finished work | `/review-close` | Merges worktree branches back into `main` from the primary checkout; the human stays the gate. |

**The one thing to avoid: freehand work on `main`.** Nothing in the workflow *prevents* a session sitting in the primary checkout from editing files directly on `main`, or running `git checkout -b` there. Both are hazards:

- Editing on `main` skips the worktree, the branch, and the lock — the work is invisible to every coordination signal and lands unreviewed.
- `git checkout` in the primary checkout moves the *shared* `HEAD` off `main`. Any concurrent actor that expects to be on `main` and commits — an `/auto-build` claim commit, another `/claim-task` — then commits onto the wrong branch. This is the **HEAD-hijack** race.

The defense is `_shared/main-push-guard.md` **Rule A**: every commit or push to `main` first asserts `git rev-parse --abbrev-ref HEAD == main` and STOPs otherwise. It doesn't *prevent* a stray checkout — it turns a silent wrong-branch commit into a loud halt. The actual prevention is behavioral: **start new work through `/claim-task`**, which creates a branch and checks it out *in a new directory* (`git worktree add`), so the primary checkout's `HEAD` never moves.

**"Is this task safe to claim right now?"** `/claim-task` hard-fails if the task you named is itself already locked (showing the owner) and lists the other active locks. Beyond that, its Step 2 now runs a **non-blocking overlap advisory** (`sysop/scripts/scope_overlap.py`, Phase 102): it infers your candidate's likely file scope from its `## Key files` + `blast_radius` — a *pre-plan guess* — compares it against the **actual** changed set of each in-flight worktree (`git diff --name-only main...HEAD` + uncommitted), and warns on `likely` (exact path match) / `possible` (same directory or glob) overlap. It's *advisory*: overlap is recoverable rework, not corruption, so the human owns the call and the claim is never blocked on it (contrast the lock collision, which correctly hard-fails). The same primitive is now wired into the **selection** surfaces too (Phase 103): `/auto-build` grades each candidate against the in-flight set and soft-de-prioritizes + annotates an overlapping one (Leg B — its `blast_radius` solo / cross-module caps reason only about tasks *within one batch*, so the primitive adds the across-session dimension); `/next-task --avoid-inflight` prefers a non-colliding task and annotates its verdict; and `/roadmap --in-flight` annotates ready candidates + `Run it:` batch lines by collision risk. All three stay advisory — a warning and a re-ordering, never a hard exclusion. When a collision does slip through, it surfaces as a **merge conflict at `/review-close`** — recoverable, because the worktrees kept the builds isolated.

**Running more in parallel — and the real ceilings.** With credits to spare you can push more concurrent work (raise `/auto-build`'s `N`, up to 4; run a second `/auto-build` in another session; or fan out manual `/claim-task`s). The limits that actually bind, roughly in order:

- **`/review-close` is the throughput gate.** Build parallelism is cheap; the human merge review is sequential and human-paced. Ten branches in flight is ten branches queued for one reviewer — past a handful, you're usually rate-limited by your own reviewing, not by Sysop.
- **Shared verification state.** Parallel tasks that run the test suite against one local database, bind the same port, or hit a rate-limited sandbox API race on fixtures and produce *flaky* FAIL verdicts (`/auto-build` Step 3 warns about the DB case; it generalizes). Force `N=1`, or serialize, for suites that mutate shared state.
- **Semantic coupling that isn't file overlap.** Two tasks touching different files but the same *behavior* (one changes an API contract, another consumes it) merge cleanly yet break `main`. Only `depends_on` or human judgment catches this — `blast_radius` can't.
- **`tasks/index.yml` write races.** Every claim rewrites the file; `/auto-build` serializes its own pre-claims, but a concurrent manual claim isn't serialized against it. The window is seconds (the pre-claim step), not the long build phase.
- **Machine + supervision.** Each parallel task is a full worktree on disk plus a full agent session; your own capacity to supervise parked or failed tasks caps it as much as CPU or credits do.
- **Dependency ordering.** Parallel work must respect the `depends_on` DAG (build against a merged base, not a stale branch). `/auto-build` and `/next-task` enforce this automatically; a freehand claim can violate it.

---

## 5. Feedback Loops

These are the mechanisms that make the workflow self-improving. Each loop connects a detection step to a correction step, so the system learns from its mistakes.

### 5.1 Convention creation (review → candidate → promotion)

```
Review finds pattern (3+ occurrences in a round)
  → Convention candidate recorded, attributed to that round (sysop/runtime/pending-docs/convention-candidates.md)
    → Pattern recurs in a later round → cross-round survival gate clears
      → Review session interactively promotes to CLAUDE.md § Prevention Conventions
        → Convention map updated with new rule (+ optional pre-commit hook check)
          → Codebase swept for existing violations (fix inline / batch / skip)
            → Future review agents check the new rule
              → Fewer findings of that pattern in next review
```

**Detection:** § 2.5 step 8, § 2.6 step 5 (convention candidate extraction)
**Correction:** § 2.5 step 9, § 2.6 step 5 (interactive promotion in the same review session)
**Verification:** Next review round should find fewer instances of the promoted pattern

This is the core value of the framework. Without it, reviews find the same issues repeatedly. With it, each review round is smarter than the last.

**The reverse loop (demotion).** The same review session also *retires* a rule the codebase has outgrown — a blocking-mechanical check that keeps firing on non-violations earns a stale-verdict at pre-scan triage (the review skills' Step 2b), recorded round-attributed in a `## Convention fire ledger`; once those verdicts survive 2+ rounds, the skills' Step 9b prompts `[retire / demote-to-advisory / tighten / keep]`. Creation and demotion are the two directions of one loop — see § 3.5b.

### 5.2 Convention enforcement (hook → catch → prevent)

```
Convention promoted
  → Anti-pattern added to pre-commit hook
    → Developer commits code with the anti-pattern
      → Hook blocks or warns
        → Developer fixes before commit
          → Pattern never reaches the codebase
```

**Detection:** Pre-commit hook (§ 3.4)
**Correction:** Immediate — developer sees the warning and fixes before committing
**Verification:** Grep the codebase for the anti-pattern — count should not increase between reviews

### 5.3 Map coverage (audit → fix → coverage)

```
New file created (or existing file moved/split)
  → Map coverage audit detects file not matched by any section
    → Reviewer adds/expands map section
      → File now has conventions checked during review
        → Violations in new files are caught
```

**Detection:** § 2.2 step 7 (during planning), § 2.5 step 3 and § 2.6 step 2 (during review)
**Correction:** Inline map update during review, or plan step during planning
**Verification:** Re-run map coverage audit — unmatched file count should be zero or near-zero

Without this loop, refactors that split files into new modules silently create review blind spots. The map coverage audit catches them. The audit also runs in reverse (§ 3.6 check 4): when a refactor *deletes* the code a map section governed, the backward sweep flags the now-stale section or dead helper citation so the map can be refreshed or retired rather than quietly misdirecting agents — the detection half of convention demotion (§ 3.5b). Its behavioral half — step 9b's FP-driven retirement of stale *blocking* rules, which this static sweep cannot see — is now active too; together they form the symmetric counterpart to the promotion lifecycle in § 3.5.

### 5.4 Sibling amplification (fix → scan → catch siblings)

```
Auto-fix agent fixes listed task (e.g., TASK-123: add the project's log-sanitizer wrapper in `<auth module>/*.py`)
  → Agent scans the same file for other violations of the same convention
    → Finds 2 more instances of raw exception logging in the same module
      → Fixes those too (not listed as tasks, but same pattern)
        → Fewer tasks in next review round
```

**Detection:** § 2.7 step 4 (sibling scan after fixing listed tasks)
**Correction:** Immediate — agent fixes siblings in the same commit
**Verification:** Next review's grep pre-scan should find fewer instances of that pattern

This loop prevents the "whack-a-mole" problem where a review finds 3 of 5 instances, the agent fixes 3, and the next review finds the remaining 2.

---

## 6. Project Configuration Interface

This section defines what a project must provide to use this workflow. Each subsection includes a **blank template** (for a new project) and a **worked example** (from the GDP Query System project where this workflow was developed).

### 6.1 What CLAUDE.md should contain

CLAUDE.md is your project's configuration file — it tells AI agents what they need to know about the project. It should contain **project reference** (architecture, commands, key files, environment variables) and **project-specific rules** (prevention conventions, testing patterns).

It should NOT contain **process** (that's this document) or **convention scoping** (that's the convention map).

**Boundary rule:** If a section describes *how to do work* (lifecycle steps, review process, merge protocol), it belongs in WORKFLOW.md. If it describes *what the project is* (architecture, commands, conventions), it belongs in CLAUDE.md.

**Where to put project-specific convention/security/check additions** (Phase 24a). The CLAUDE.md `## Prevention Conventions` section is the right home for *prose* guidance (when-to-use rules, project narrative). For the *map* itself — per-file-pattern routing tables that compose alongside Sysop's core + pack convention maps — author `.claude/convention_map.project.md` (consumer-authored, never managed, survives every `--update`). Same shape for security maps (`.claude/security_map.project.md`) and grep checks (`.claude/checks.project.yml`). See § 8.2 table and § 8.2c.

**Required sections in CLAUDE.md:**

| Section | Purpose |
|---------|---------|
| `## Project Overview` | One-paragraph description of the project |
| `## Commands` | How to build, test, run, deploy |
| `## Architecture` | Request flow, key design decisions, database access patterns |
| `## Key Files` | Table mapping purposes to file locations |
| `## Prevention Conventions` | The actual convention rules (subsections grouped by domain — Frontend/Backend/Testing if you have those layers, or whatever subsections fit your project) |
| `## Pre-merge verification` | Bullet list of commands `/review-close` runs before pushing (build, tests, project-specific smoke). Keeps verification deterministic across stacks. Run **twice** — a cheap pre-merge pass on `main` (Step 3) and the authoritative pass on the merged tree (`4a-post`) — so author them re-runnable and read-only. |
| `## Merge policy` | *(optional; default `direct`)* `direct` or `pr`. Tells `/review-close` Step 4 how to land work on `main`: `direct` pushes `main` directly; `pr` routes through an integration branch + squash PR. Set `pr` when `main` is push-protected by a required status check and/or `enforce_admins` (a direct push is rejected there). |
| `## Sysop upstream repo` | *(optional; default `getsysop/sysop`)* A bare `owner/name` slug naming where the three give-back skills — `/report-issues`, `/contribute-convention`, `/share-wins` — file. The shipped default is the **public** Sysop repo, and friction logs and convention overlays routinely quote consumer security context, so any project whose give-back should stay private declares it here. Per-run `--repo` still overrides. Absent → the default; present-but-unparseable, or an almost-right heading → the skills stop rather than fall back. Enforced by skill prose, not by code: it warns and asks, it never redacts, and per-item consent stays the real gate. See the template below. |
| `## Guided mode` | *(optional; off by default — Phase 76)* Behavioral overlay for builders growing into the review judgment the workflow assumes. When present, skills explain each decision plainly, adversarially review their own recommendation, and surface only the calls the human can genuinely own. Points at `.claude/skills/_shared/guided-mode.md`; see the template below. |
| `## Post-deploy verification` | *(optional)* A project-defined smoke command `/review-close` runs after the merge lands — a Playwright run against the staging URL, a curl on a health endpoint, a synthetic monitor check. Absent → the step is a no-op. |
| `## Pending documentation routing` | *(optional)* Where `/auto-build` consolidates the per-task `sysop/runtime/pending-docs/*.md` it accumulates across a batch, so a multi-task run doesn't leave the human a pile of unrouted fragments. |
| `## Testing Patterns` | Test framework, fixture patterns, mock patterns |
| `## Environment Variables` | All env vars with descriptions |
| `## Task Workflow (pointer)` | "Follow the workflow in `sysop/docs/WORKFLOW.md`." (2 lines, not the full protocol) |

**Sections the audit skills read** (optional — `/codebase-review`, `/security-audit`, `/test-audit`). Beyond the required sections above, the review/audit skills read a few project-specific sections when present. These carry *review-run operational inputs* (what to scan, what to expect unmatched, what to weight) — they are **not** the per-file convention→file map (that lives in `.claude/convention_map.project.md`, per the boundary rule above), which is why they belong in CLAUDE.md rather than tripping the "no convention scoping in CLAUDE.md" rule. Absent, each skill falls back to roots parsed from the convention/security map headers. The first three are installer-seeded as empty stubs in both install modes; author them by filling in globs.

| Section | Read by | Purpose |
|---------|---------|---------|
| `## Scope mapping` | codebase-review, security-audit, test-audit | Maps each `--scope` value (e.g. `backend`, `frontend`) to a project path set, so a scoped run limits to those paths. Absent → scan roots parsed from `.claude/convention_map.md` (or `security_map.md`) section headers. |
| `## Map coverage exclusions` | codebase-review, security-audit | Globs the Step 2a map-coverage audit should **not** flag as unmapped (generated code, vendored dirs, fixtures). **Scopes that audit only — it does not change the review/scan manifest and is not a review-exclusion knob.** A listed path is still reviewed/scanned iff Step 3 dispatches an agent that covers it — and the two skills dispatch differently: `/security-audit` dispatches on the OWASP categories a matching security-map section lists under `Check:`, so a file in a matched section whose categories no agent owns is matched and unaudited (Step 3-0b is the check for that), while `/codebase-review` keys on the hand-authored 3-pre table, which cites convention-map sections **by name** and is not computed from the maps, so a section the table does not name has no agent of its own, however cleanly its globs match. A path is still reviewed if some 3-pre row's Files column reaches it directly — which is what `Infra & Config` does for paths no section covers. **Give each entry a one-line reason** (`` - `vendor/` — third-party code, not ours to change ``): Step 2a-0 asserts every top-level entry holding tracked code is either map-covered or excluded-with-a-reason, and reports reasonless entries — an unexplained exclusion is how a whole subtree gets silenced by accident. Only lockfiles, generated/vendored output and binary assets are out of 2a-0's scope: a config-only or docs-only *subtree* (a `.github/` of workflows, a `migrations/` of SQL) is still reported, because "negligible surface" is a claim about one file inside a mapped area, not about a whole unmapped tree. Existing reasonless entries are surfaced, never blocking. |
| `## Security-critical always-include files` | security-audit | Paths always pulled into the scan regardless of `--scope` or scan mode (auth, secrets handling, permission checks). |
| `## High-value files for review` | codebase-review | Large or security-concentrating files to give a dedicated review agent instead of bundling with many others. |

**`## Sysop upstream repo` template** *(optional — omit for the default public `getsysop/sysop`)*:

```markdown
## Sysop upstream repo

`your-org/sysop`

The GitHub-touching give-back skills — `/report-issues`, `/contribute-convention`,
`/share-wins` — target this repo. The shipped default, `getsysop/sysop`, is the
**public** upstream; this project's friction entries and convention overlays carry
context that should not land there by default.
```

> One `owner/name` slug on the first non-empty line, with or without backticks;
> the prose beneath it is yours and is not parsed. This is the **durable** target
> — `--repo owner/name` remains the per-run override on top of it, for the
> one-off exception in either direction. The section exists because shipped
> skills are outside the customization-preservation scope (§ 8.2c: skills take
> the standard overwrite, no silent prompt-forks), so editing a skill body to
> redirect it would not survive an update; `CLAUDE.md` is the sanctioned durable
> home for consumer-side skill configuration, the same precedent as `## Merge
> policy`. The skills also probe the resolved target's visibility (`gh repo
> view`) and warn before filing anything that reads as security-sensitive to a
> public — or unverifiable — destination; the full protocol is
> `.claude/skills/_shared/upstream-repo.md`.

**`## Guided mode` template (optional — Phase 76):**

Add this section to opt a project into guided (teaching) mode. Its presence is the toggle — removing it returns to default (senior-operator) behavior. The canonical protocol lives at `.claude/skills/_shared/guided-mode.md`; keep this section in sync with it. Guided mode governs only the *human* decision points — the deterministic gates (pre-commit checks, blocking conventions, worktree isolation, the security map) are unchanged. The stanza's presence is the whole mechanism today; wiring each decision-gate skill to cite the protocol directly is a deferred build.

```markdown
## Guided mode

Guided (teaching) mode is **ON** for this project. Canonical source:
`.claude/skills/_shared/guided-mode.md` — keep this section in sync with it.

At every point a skill would halt and ask me to approve, choose, or promote
something — plan approval, the manual-smoke and stuck-PR gates, convention
promotion, any AskUserQuestion — do all of this *before* asking:

1. State the decision plainly (no jargon as a load-bearing word).
2. Adversarially review your own recommendation — try to refute your pick.
3. Route it:
   - Genuine tradeoff I can own → give me honest pros/cons of each option and
     your recommendation; I choose.
   - Wrong option (security hole, data loss, broken invariant) → don't offer it
     as a choice; do the right thing and tell me in one line what you protected against.
   - Real but I can't weigh it → take the conservative default, log why in the
     task body, tell me as information, not a question.

You are allowed — required — to conclude "this isn't your call." Never present a
security or data-loss risk as a balanced 50/50. Deterministic gates are unchanged;
if a gate says no, the answer is no. Remove this section to return to default.
```

**`## Pre-merge verification` template:**

The section supports two shapes. The split-sub-headings form is recommended once a project has any lint or typecheck tooling — it gates regressions on touched files without forcing a full-tree backlog cleanup first. The flat-list form remains valid for projects without a ratchet (or as a starting point that grows the second sub-heading later).

**Venv-aware invocation (applies to both shapes).** The agent's tool shell starts cold — no virtualenv is activated, no shell rc files are sourced. If a verification command depends on a Python tool installed in a project venv (`pytest`, project-specific CLIs like `bean-check`, linters like `pyflakes` / `ruff` / `mypy`), name it by its venv path explicitly: `.venv/bin/pytest`, `.venv/bin/bean-check`, and — for a Python script your *own* repo ships — `.venv/bin/python scripts/build_ledger.py`. Bare command names fall through to the system PATH and either fail loudly (`command not found`) or — worse — succeed against the wrong interpreter (system `python3` lacking project dependencies, producing misleading verification results). The same rule applies to git hooks the project ships in `sysop/scripts/hooks/`: prepend `${REPO_ROOT}/.venv/bin` to `PATH` at the top of each hook rather than relying on the invoking shell's PATH. Projects that use a non-default venv directory (`venv/`, a poetry-managed env, `.python-version` + a per-directory shim) should still spell out the absolute-to-repo-root invocation in this section so the skill can run it from a cold shell. Sysop does not auto-detect venv paths — the consumer's `## Pre-merge verification` section is the source of truth.

> **This rule is about *your project's* tooling, not Sysop's own scripts.** Never give a `sysop/scripts/*.py` invocation a `.venv/bin/` command word. The four scripts a skill prescribes — `validate_tasks.py`, `next_task.py`, `scope_overlap.py`, `sitrep_survey.py` — plus `backfill_completed_dates.py`, which no skill instructs you to run — `/daily-summary` names it in prose — but `tasks/README.md` gives a recipe for, all resolve venv PyYAML themselves, **script-anchored first**: this file's ancestors, then the **main** checkout via git-common-dir, and only then the CWD, across both `.venv/` and `venv/` layouts (Phase 182; CWD-first would let an unrelated project's venv win). So bare `python3 sysop/scripts/<script>.py` is the one form that serves every consumer, and it is the form the shipped `.claude/settings.json` allow-rules cover. (Phase 184 corrected two things here: the sentence used to end mid-clause at "allow-rules", and it counted five scripts as skill-prescribed when one of them is only documented — under which `backfill_completed_dates.py` had no allow-rule at all, so a consumer following the recipe hit a prompt. **The first fix was incomplete and its own round caught that:** seeding the rule was not enough, because `tasks/README.md`'s recipe wrote the script with **no command word** — the file is executable with a `python3` shebang, so that string runs and binds no rule whatever is seeded. The recipe now names `python3` explicitly, which is the form this paragraph teaches. `tests/test_prescribed_command_coverage.py` derives this list from this sentence and checks it against the template; it reads fenced blocks, so the inline-backticked recipe above is **not** what caught this — a reviewer reading the doc was.) (`check_skill_models.py` and `resolve_skill_models.py` are the exception — they reach PyYAML through `_model_roles.py`'s lazy import, which carries no bootstrap; nothing prescribes them bare, and `install.sh` invokes them through its own probed `pick_python_with_yaml()`.)
>
> The venv command word is not merely redundant, it is *less* portable in the cases that matter: it is `command not found` on exactly the `venv/`-layout, poetry, conda and PEP-668 system-python projects this section exists to accommodate, and inside any linked worktree — which never carries a venv even when the main checkout does. It is a **trade rather than a strict improvement**: on a host where `python3` is absent from `PATH` altogether (or is a broken pyenv shim) while a `.venv` exists, the venv-prefixed form would have worked and the bare one exits 127. That host is far rarer than the ones above, and it degrades to a named `command not found` rather than to a wrong answer.

**Split-sub-headings form (recommended):**

````markdown
## Pre-merge verification

> Commands `/review-close` runs before push — TWICE, on two trees: a cheap
> pre-merge pass on `main` (Step 3) and the authoritative pass on the merged
> result (`4a-post`). Only the second one's tree contains the branches, so
> write these to be safely re-runnable. The skill runs the `### Always` block
> on the full tree, then the `### Ratchet (changed files only)` shell block
> whose snippets filter to changed files. List them here so the skill doesn't
> have to guess from project shape — a list you author is never surface-gated,
> which is the escape from auto-detect's per-surface skips.

### Always

- <project-specific build/typecheck command>
- <project-specific test command>
- <project-specific smoke / format-check command>

### Ratchet (changed files only)

Project-supplied shell snippets. Each snippet filters `git diff --name-only
origin/main...HEAD` to the file types it cares about and invokes lint or
typecheck against only the changed files. An empty filtered list
short-circuits the snippet and passes — so the range resolves against
whichever tree is checked out, and it is the merged-tree pass (`4a-post`),
not the pre-merge one, where it names the work being shipped. Boy-scout
consequence: editing a
file with pre-existing findings causes the ratchet to fire on those
findings too — touched files get cleaned. Full-tree backlog cleanups stay
as separate project-side tasks (e.g. `TECH-LINT-BACKLOG-FIX`,
`TECH-TYPECHECK-BACKLOG-FIX` in `tasks/index.yml`).

```bash
# Python — lint changed .py files (swap pyflakes for ruff/flake8/mypy/pyright
# depending on your stack)
CHANGED_PY=$(git diff --name-only origin/main...HEAD | grep -E '\.py$' || true)
[ -z "$CHANGED_PY" ] || python -m pyflakes $CHANGED_PY

# TypeScript/JavaScript — eslint on changed files under <frontend>/
CHANGED_TS=$(git diff --name-only origin/main...HEAD | grep -E '^<frontend>/.*\.(ts|tsx|js|jsx)$' || true)
if [ -n "$CHANGED_TS" ]; then
  REL=$(echo "$CHANGED_TS" | sed 's|^<frontend>/||')
  (cd <frontend> && npx eslint --max-warnings 0 $REL)
fi
```
````

**Flat-list form (backward compatible):**

```markdown
## Pre-merge verification

> Commands `/review-close` runs before push — twice: a cheap pre-merge pass on
> `main` (Step 3) and the authoritative pass on the merged result (`4a-post`).
> List them here so the skill doesn't have to guess from project shape.

- <project-specific build/typecheck command>
- <project-specific test command>
- <project-specific smoke / lint / format-check command>
```

**End-to-end / QA suites plug in here too.** A Playwright / Cypress / integration-test run is just another `### Always` entry (or a `### Ratchet` snippet if it should scope to changed areas) — `/review-close` executes it on the merged tree at `4a-post`, on every merge, with no Sysop-side wiring. Sysop deliberately ships no QA subsystem; if e2e patterns recur across real consumer use, an e2e pack is the eventual shape (same populate-from-friction discipline as the ops band).

**`## Merge policy` template** *(optional — omit for the default `direct`)*:

```markdown
## Merge policy

pr
```

> One word: `direct` (default — `/review-close` Step 4 does `git push origin
> main`) or `pr`. Use `pr` when `main` is push-protected — a required CI status
> check and/or `enforce_admins` — where a direct push is rejected. Under `pr`,
> `/review-close` assembles the close on a throwaway integration branch and
> squash-merges it through a PR (`gh pr merge --squash`, **non-`--auto`** — native
> auto-merge is paid-plan-only for private repos), so GitHub becomes the sole
> serialized writer of `main` and the local HEAD-hijack + remote-contention races
> disappear. When a single approved branch already has an open PR against `main`
> and there is nothing local-only to sweep, the close reuses that PR instead of
> opening a second one. Requires `gh` installed + authenticated and the `gh pr *`
> allow-rules in `.claude/settings.json` (see `/review-close` Step 0). Non-GitHub
> hosts or unprotected-`main` projects stay on `direct`.
>
> One `pr`-policy behaviour worth knowing before you see it: when the close ran on an
> integration branch, `gh pr merge --delete-branch` prints `fatal: Not possible to
> fast-forward, aborting.` **after a merge that succeeded**. It is `gh` trying to update
> your local `main`, which that shape leaves diverged. `/review-close` reads the PR's
> `state` rather than the command's output, and re-syncs `main` itself in cleanup.

**Protecting `main` with CI.** The `pr` policy only *bites* if `main` actually
requires a check — Sysop's git hooks are local-only, and an agent can bypass them
with `--no-verify`, so a required **CI** check is what makes a protected `main`
enforceable. Sysop ships a ready-made GitHub Actions workflow for this at
`sysop/scripts/ci/sysop-checks.yml.example` (delivered but **unarmed** — like the git-hook
templates). It runs the Sysop blocking-findings gate (`run_checks.sh --fail-on-blocking`)
plus your own test suite. To enable it:

1. `cp sysop/scripts/ci/sysop-checks.yml.example .github/workflows/sysop-checks.yml`
2. Edit the two `TODO` steps — install your dependencies, and swap the placeholder
   `Tests` step (which fails on purpose so an unedited copy can't become a
   meaningless green) for your real test command.
3. Commit + push, let it run green once, then mark the `sysop-checks` check
   **required** in your repo's branch-protection rules for `main`.

Now `/review-close`'s `pr` route lands through a PR that GitHub won't merge until
`sysop-checks` is green — the same gate a human reviewer would enforce, made
mechanical.

### 6.2 Convention map template

**Blank template** (`.claude/convention_map.md` — for a new project):

```markdown
# Convention Map

> Maps file patterns to relevant Prevention Conventions from CLAUDE.md.
> Use this during planning (before writing code) and review (before committing).
> Full rules live in CLAUDE.md § Prevention Conventions.

---

## `src/api/**/*.py`, `src/routes/**/*.py` — API Endpoints

- **Input validation**: All parameters need validation constraints
- **Error responses**: Never expose exception details in API responses
- **Auth enforcement**: Mutations require authenticated user

## `src/models/**/*.py`, `src/db/**/*.py` — Data Layer

- **SQL safety**: Never use f-strings for SQL — use parameterized queries
- **Engine selection**: Read queries use read replica; writes use primary

## `src/components/**/*.tsx` — UI Components

- **Error display**: Never render raw error messages — use the error display utility
- **Accessibility**: Interactive elements need appropriate ARIA attributes

## `tests/**/*.py`, `__tests__/**/*.ts` — Tests

- **Mock cleanup**: Restore all mocks in afterEach/tearDown
- **Meaningful assertions**: At least one assertion per test on the behavior under test
```

**Worked example** (from GDP Query System — 13 sections, 130 lines):

```markdown
## `agent/server.py`, `agent/routes/*.py` — API Endpoints

- **Tier enforcement**: Creator-tier mutations need `Depends(require_studio_access)`, not just `get_verified_user`
- **Rate limiting**: New endpoints must be added to `_PUBLIC_READ_PATHS`/`_PUBLIC_READ_PREFIXES` or call `_check_user_rate_limit()`
- **Input validation**: All parameters need `Field(max_length=...)` / `Query(ge=..., le=...)`; use `SafeId`, `BoundedLimit`, `BoundedOffset`
- **Response filtering**: Never expose `owner_id`, `firebase_uid`, `client_ip`, `stripe_customer_id` in responses
- **Error responses**: Never return `str(e)` or exception details — use generic messages
- **Error caching**: Never cache error responses with long TTLs; transient errors → 500 or `Cache-Control: no-store`
- **LLM output bounds**: All `GenerateContentConfig` calls must include `max_output_tokens`

## `frontend/app/components/*.tsx`, `frontend/app/components/**/*.tsx` — React Components

- **Fetch calls**: Use `useAbortableFetch()` for all component-level fetches; suppress `AbortError` with `isAbortError()`
- **`'use client'` directive**: Components using React hooks or Framer Motion must include `'use client'`
- **Error display**: Never render `err.message` — use `getDisplayError()` from `lib/errorMessages.ts`
- **Accessibility**: Modals/drawers need focus trap + Escape + `role="dialog"` / `aria-modal`; icon buttons need `aria-label`
- **Focus trap reuse**: Use shared `useFocusTrap()` hook — no copy-pasted inline implementations
- **SVG ID uniqueness**: SVG `<defs>` IDs via `useId()` hook, never hardcoded strings
- **ReactMarkdown**: Allow-list of elements only; links must validate scheme with `isSafeHref()`
```

### 6.3 Security map template

**Blank template** (`.claude/security_map.md` — for a new project):

```markdown
# Security Concern Map

> Maps file patterns to relevant OWASP security checks.
> Each section lists what TO check and what to SKIP — both scoped to the files that
> section's globs actually match, never to the subject in general.

---

## `src/api/**/*.py` — API Endpoints

**Check:**
- **A01 Access Control**: Authorization on all endpoints, IDOR prevention
- **A03 Injection**: SQL injection, prompt injection if using LLMs
- **A07 Auth**: Token verification, session management

**Skip:** A06 (dependencies — checked separately), A10 (SSRF — no outbound to user URLs)

## `src/components/**/*.tsx` — UI Components

**Check:**
- **XSS**: Dynamic content rendering, URL validation in href attributes
- **A01 Access Control**: Client-side auth gate correctness (but server must enforce)

**Skip:** A03 SQL (no database access), A07 Auth (handled by API layer)
```

**Worked example** (from GDP Query System — 2 of 15 sections shown):

```markdown
## `agent/routes/*.py` — API Endpoints

**Check:**
- **A01 Access Control**: IDOR (ownership verification before resource access), tier enforcement (`require_studio_access` on Creator-tier mutations), horizontal privilege escalation (user ID in path params vs. authenticated user)
- **A02 Data Exposure**: Response filtering — `owner_id`, `firebase_uid`, `stripe_customer_id`, `client_ip` must not appear in API responses
- **A03 Injection**: Prompt injection (user queries interpolated into LLM prompts must use `html.escape()`); SQL from external sources must pass through `validate_sql_safety()`
- **A05 Misconfiguration**: Rate limiting coverage (new endpoints in `_PUBLIC_READ_PATHS`/`_PUBLIC_READ_PREFIXES` or `_check_user_rate_limit()`), input validation (`Field(max_length=...)`, `SafeId`, `BoundedLimit`)
- **A07 Auth**: Auth gate correctness (required vs optional auth on each endpoint), no bypass paths
- **Logging**: Audit trail — state mutations logged at INFO on success; error sanitization (`_sanitize_log(str(e)[:500])`)

**Skip:** A06 (dependencies), A10 (SSRF — no outbound HTTP to user-supplied URLs), XSS (server-side)

## `frontend/app/components/*.tsx`, `frontend/app/hooks/*.ts` — React Components & Hooks

**Check:**
- **XSS**: URL validation with `isSafeHref()` before `href` attributes; reject `javascript:`, `data:` schemes; ReactMarkdown must use element allow-list
- **A01 Access Control**: Client-side tier gates are cosmetic — verify corresponding API enforcement exists
- **Privacy**: No PII in console.log or error boundaries; no analytics events with user-identifiable data

**Skip:** A03 SQL (no database access), A07 Auth (handled by API layer), A10 (SSRF — no server-side requests), A05 (server config)
```

Key design: every section has both **Check** (what to audit) and **Skip** (what to omit) subsections, both scoped to the files the section's globs match. The Skip list prevents audit fatigue on areas where a threat category doesn't apply — but a section whose globs are still placeholders matches nothing, so its Skip list excludes nothing.

### 6.4 Pre-commit hook template

**Skeleton** (`sysop/scripts/hooks/pre-commit` — for a new project):

```bash
#!/bin/bash
# Pre-commit hook: two-tier convention checks
# Blocking checks (B1-BN): reject commit on match
# Advisory checks (A1-AN): warn but allow commit
#
# Escape hatch: PRE_COMMIT_ADVISORY_ONLY=1 git commit ...

STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM)
[ -z "$STAGED_FILES" ] && exit 0

# Separate by file type
STAGED_PY=$(echo "$STAGED_FILES" | grep '\.py$' || true)
STAGED_TS=$(echo "$STAGED_FILES" | grep -E '\.(ts|tsx)$' || true)
STAGED_TESTS=$(echo "$STAGED_FILES" | grep -E '(__tests__|tests/)' || true)

BLOCKING_FAILED=0
ADVISORY_NOTES=""

# === BLOCKING CHECKS ===

# B1: <description>
if [ -n "$STAGED_PY" ]; then
    HITS=$(echo "$STAGED_PY" | xargs grep -ln '<anti-pattern>' 2>/dev/null || true)
    if [ -n "$HITS" ]; then
        echo "❌ B1: <description>"
        echo "$HITS"
        BLOCKING_FAILED=1
    fi
fi

# === ADVISORY CHECKS ===

# A1: <description>
if [ -n "$STAGED_TS" ]; then
    HITS=$(echo "$STAGED_TS" | xargs grep -ln '<anti-pattern>' 2>/dev/null || true)
    if [ -n "$HITS" ]; then
        ADVISORY_NOTES+="⚠️  A1: <description>\n"
        ADVISORY_NOTES+="$HITS\n\n"
    fi
fi

# === OUTPUT ===

if [ -n "$ADVISORY_NOTES" ]; then
    echo ""
    echo "Advisory warnings (commit proceeds):"
    echo -e "$ADVISORY_NOTES"
fi

if [ "$BLOCKING_FAILED" -eq 1 ]; then
    if [ "$PRE_COMMIT_ADVISORY_ONLY" = "1" ]; then
        echo "⚠️  Blocking checks failed but PRE_COMMIT_ADVISORY_ONLY=1 — proceeding"
        exit 0
    fi
    echo ""
    echo "Commit blocked. Fix the issues above or use PRE_COMMIT_ADVISORY_ONLY=1 to bypass."
    exit 1
fi

exit 0
```

**Worked example** (from GDP Query System — 286 lines): 5 blocking checks (B1–B5), 9 advisory checks (A1–A9). See `git-hooks/examples/pre-commit-python.example` in the Sysop source repo for the full worked example (the `examples/` directory is reference material — it is not installed into consumer trees).

### 6.5 Check registry format (grep + LSP + Semgrep + ESLint + pip-audit + coverage)

Deterministic checks detect convention violations without LLM interpretation. The shared registry at `.claude/checks.yml` defines grep entries directly; LSP (`pyright-*`, `tsc-*`), Semgrep (`semgrep-*`), and coverage (`coverage-*`) check IDs are auto-populated at scan time by `sysop/scripts/run_checks_impl.py`. All sources share the same `(check_id, file_line, message, identity)` output shape, so baseline matching, `--mode` filtering, and `--fail-on-blocking` apply uniformly. Both `/codebase-review` and `/security-audit` consume the same registry so every check has exactly one definition.

Run the registry directly with:

```bash
bash sysop/scripts/run_checks.sh                         # All checks (advisory)
bash sysop/scripts/run_checks.sh --mode quality          # Codebase-review checks only
bash sysop/scripts/run_checks.sh --mode security         # Security-audit checks only
bash sysop/scripts/run_checks.sh --mode both \
     --fail-on-blocking                            # CI contract — exit 1 on new blocking findings
bash sysop/scripts/run_checks.sh --mode both \
     --update-baseline                             # Regenerate .claude/checks_baseline.txt
bash sysop/scripts/run_checks.sh --print-keys      # Print the baseline key for every current finding
bash sysop/scripts/run_checks.sh --migrate-baseline  # One-shot: convert a pre-identity baseline
```

**The baseline key identifies the finding, not just its position.** An entry is
`check_id|path:line|identity`, where `identity` is whatever distinguishes *this*
finding from another the same check could report at the same place: a hash of the
matched line for grep checks, of the matched span for semgrep, the vulnerability
id for `pip-audit-vuln`, the rule id for `lint-error` / `tsc-type-error` /
`pyright-general-warning`. Checks with nothing to key on — the two
`invert_file_check` entries, whose finding is the whole file and whose key is
already stable — keep the two-field form.

The reason is that a two-field entry means *"whatever this check finds at this
line"*, which is not what anyone accepting a finding intends. Edit the accepted
line and the entry silently excuses whatever replaces it: on a `blocking: true`,
`severity: critical` check that is a live finding printed as `[baseline]` with
the gate exiting 0. The catch-all check ids made it worse still — one
`lint-error|app.js:7` entry excused every ESLint rule that would ever fire on
line 7, and because `pip-audit-vuln`'s anchor is constant for a whole run, one
accepted advisory excused **every CVE in the project, present and future**.

**Hand-adding an entry now starts with `--print-keys`.** For grep and semgrep
checks the identity is a content hash, so those keys cannot be typed from what the
finding line shows you. (The rule-id identities above — `lint-error`,
`pip-audit-vuln`, the two LSP catch-alls — *are* readable off the message, but
taking every key from one place is the habit worth having.) Run `--print-keys`,
copy the key for the finding you are accepting, paste it in with your rationale as
a `#` comment. Everything else about hand-authoring is
unchanged, including that comments are yours and no command rewrites them.

**Converting an existing baseline: `--migrate-baseline`, once.** It rewrites in
place and preserves every comment, so hand-written triage rationale survives —
which is why it is not `--update-baseline`, and why it is not built on
`load_baseline`/`write_baseline` (that pair drops comments and stamps a fresh
header). It rewrites an entry only where exactly one current finding matches it;
where none matches, or where several do, it **drops the entry** and prints why.
Several matching is the catch-all case: expanding one entry into N would accept
N−1 findings nobody reviewed, which is the silent acceptance the migration exists
to avoid. A dropped entry whose finding merely *moved* re-fires at its new line, loudly. One whose finding is genuinely gone does not re-fire — the entry and its rationale are simply gone too, which is why the report names every drop and why the migration holds anything it cannot tell apart. Entries
belonging to a check that did not execute this run are **held**, not dropped —
named in the report and left two-field, so a skipped stage is never mistaken for
findings that have gone away. That means a partial migration is the normal
outcome when semgrep, eslint or pip-audit is absent: the run exits 0, and the
held entries still do not suppress until you re-run with those stages
available. The migration refuses outright only when *every* baselined check
failed to execute, since then there is nothing it could convert.

Until you run it, a legacy entry does not suppress — the run names it and points
at the command. That is deliberate: honouring the old form as a fallback would
preserve the defect permanently for exactly the baselines that have it.

**CI integration.** Sysop ships a GitHub Actions template — `sysop/scripts/ci/sysop-checks.yml.example` — that runs `run_checks.sh --fail-on-blocking` on every PR (enable it per § 6.1 "Protecting `main` with CI"). Checks marked `blocking: true` fail the job when they produce a finding that is NOT present in `.claude/checks_baseline.txt`. Baseline-matched findings are printed with a `[baseline]` tag so the tech debt stays visible without blocking progress. To accept a new finding as baseline debt, regenerate with `--update-baseline` and commit the diff — but only after review, since a *blocking* check's baseline entry bypasses CI.

**An advisory check's findings are baselined too, and that buys them a tag, not an exemption.** Until internal tracker #363 both ends of the baseline were gated on `blocking: true`, so an entry for a `blocking: false` check could neither suppress anything nor be written — it survived until the next `--update-baseline` regeneration dropped it. That is inert state that reads as live state: on one measured run, ~300 of 341 findings were triaged as false positives or documented exceptions with nowhere to record the verdict, and the entries a consumer had hand-added as "accepted findings" were suppressing nothing. Now the only carve-out is coverage. The gate is unchanged in both directions — `--fail-on-blocking` reads `blocking: true` on its own, so **an advisory entry cannot change an exit code**; what it changes is that the finding prints as `[baseline]` instead of as a fresh finding, and the `baseline-matched: N` header count grows. Three consequences worth knowing before you regenerate. The baseline file gets substantially bigger (it now spans every check). An advisory entry a consumer added by hand *starts* suppressing at the next run — activating state that was written expecting exactly that. And the third is the one to plan around:

**Promotion does not retroactively un-accept a baselined finding.** Advisory is the staging state for a rule on its way to `blocking: true` (§ 6.5), so the checks this now baselines are the ones headed for promotion. Once a check's findings are in the baseline, flipping it to `blocking: true` arms the gate for **new** findings only — the pre-existing ones keep suppressing, print `[baseline]`, and the run reports `new blocking: 0` and exits 0. Verified by execution, and it is a change: before this, the same sequence exited 1. That is consistent with what a baseline *is* — accepted, do not fail CI — and it is the right answer when what you baselined were false positives, which is the case internal tracker #363 exists for. It is the wrong answer if you baselined real debt and expected promotion to force it out. So **when you promote a check, decide about its existing entries in the same commit**: drop that check's lines from `.claude/checks_baseline.txt` if the promotion is meant to bite, or leave them and let the gate cover new findings only. The run tells you which situation you are in — a `blocking suppressed:` line in the summary header names every blocking check whose findings were baseline-suppressed, so an inert gate is visible instead of reading as a clean scan.

**Execution accounting (the summary block).** Every check the mode filter *selects* ends the run in exactly one of three states, so the summary can never again pass off a dead scan as a clean one:

- **`executed`** — the tool ran to completion over its inputs. A zero-findings executed check is a real zero.
- **`skipped(reason)`** — a precondition was absent; the tool never ran. Reasons include `paths-unresolved` (placeholder globs not yet localized), `tool-missing`, `input-missing` (no coverage report, no `node_modules/eslint`), `not-installed` (`.claude/semgrep/` absent), `not-configured`, `misconfigured`.
- **`failed(reason)`** — the tool started and broke: a nonzero exit with no parseable output (e.g. semgrep's X.509 trust-store crash in a sandbox), a timeout, non-JSON output, grep rc≥2, or a caught exception.

The stderr summary reports all three as distinct counts, and enumerates every non-`executed` stage with its reason:

```
--- 890 finding(s) · checks: 5 executed / 16 skipped / 4 failed of 25 selected (mode: quality; baseline-matched: 0; new blocking: 0) ---
    failed: semgrep (4 checks) — exit 2: Fatal error: Failed to create system store X509 authenticator …
    skipped: grep (13 checks) — paths unresolved: placeholder globs not yet localized
    skipped: eslint (1 check) — no node_modules/eslint under repo root
    skipped: coverage (2 checks) — critical_path not yet configured (placeholder globs); gate unarmed
    executed with 0 findings: 3 pyright checks (pyright-undefined-variable, pyright-unused-import, pyright-unused-variable)
```

This means a bare finding total is no longer trustworthy on its own: `0 findings from N checks` is the exact output of a genuinely clean scan **and** of a run where nothing executed — the E/S/F split is what tells them apart. Two consequences: `--fail-on-blocking` fails not only on a new blocking finding but also when a **`blocking: true` check's tool crashed** (a `failed` blocking stage — a green gate over a stage that never ran would be a lie), and `--update-baseline` **refuses** (writes nothing) when any blocking check failed, since a crashed tool is not a state to snapshot. A `skipped` blocking check is loud — a `⚠ BLOCKING CHECK DID NOT RUN` line when the check is *localized* (its gate is armed and now dead) — but never fatal: gating on `skipped` would redden every armed consumer whose coverage report is produced after the gate step, and every fresh install whose blocking checks still carry placeholder globs (those render as a calm "gate unarmed" line, no ⚠).

**Format** (`.claude/checks.yml`):

```yaml
# Grep Check Registry
# Used by /codebase-review and /security-audit for deterministic pre-scan

checks:
  - id: sql-fstring
    name: f-string SQL
    category: correctness
    severity: critical
    paths: ["<api module>/", "<scripts dir>/"]
    include: ["*.py"]
    exclude: ["*test*"]
    pattern: 'f[''"](SELECT|INSERT|UPDATE|DELETE)'   # both quote styles — see "Quote-agnostic patterns" below
    description: "f-string SQL detected — use parameterized queries"
    convention: "SQL safety"
    used_by: [codebase-review, security-audit]

  - id: raw-exception-log
    name: Raw exception in logging
    category: correctness
    severity: medium
    paths: ["<api module>/", "<scripts dir>/"]
    include: ["*.py"]
    pattern: '_sanitize_log\((e|err)\)'
    negative_pattern: 'str\(e\)'
    description: "Use _sanitize_log(str(e)[:500]), not _sanitize_log(e)"
    convention: "Logging"
    used_by: [codebase-review]

  - id: missing-mock-cleanup
    name: Missing mock cleanup
    category: testing
    severity: medium
    paths: ["<frontend>/**/__tests__/"]
    include: ["*.ts", "*.tsx"]
    pattern: 'vi\.(mock|spyOn)\('
    file_must_also_contain: 'restoreAllMocks'
    invert_file_check: true  # flag files that have the pattern but NOT the required content
    description: "File uses vi.mock/vi.spyOn but has no vi.restoreAllMocks()"
    convention: "Mock cleanup"
    used_by: [codebase-review]
```

**Quote-agnostic patterns.** Python, JS/TS and SQL all accept `'` and `"` interchangeably, so a pattern that hard-codes one of them scans half its subject and reports the other half clean — silently, because a miss is indistinguishable from a real zero. Write the prefix as a character class: `f[''"](SELECT|…)`, not `f"(SELECT|…)`; `getenv\([''"]APP_ENV[''"]` , not `getenv\("APP_ENV"`. This applies to `position_check:` regexes too, where the cost is higher: `_run_position_check` skips the **whole file** when either regex fails to match, so a quote-anchored `earlier:` disarms the check on every file written in the other style rather than missing one line. (In YAML's single-quoted scalars a literal `'` is written `''`.) The exception is a format where only one quote is legal — a JSON object key, a JS template literal (backticks have no single/double-quote twin) — where anchoring is correct. (Sysop's own CI gates this over every shipped fragment via `tests/test_check_pattern_quotes.py` — not shipped.)

**Inline waivers — `no-check: <id>`.** A grep finding on a line carrying `no-check: <check id>` is suppressed for that check. This is the grep-stage counterpart to `# nosemgrep` and `# pragma: no cover`, and it **composes with the baseline rather than replacing it**: `.claude/checks_baseline.txt` is keyed on the finding's position *and* its identity, so a moved line re-fires rather than silently excusing whatever replaced it — but it still records *historical debt* pinned to a place, while an inline marker records a *reviewed, intentional exception* that travels with the line it excuses. (Before the identity field the baseline rotted on any line movement, in both directions; the dangerous direction is closed, and the entry re-firing after a move remains the expected, loud behaviour.) Where an exception is genuinely permanent, the inline marker is the durable half of that pair whatever the check's `blocking` value.

```python
count = run_sql(conn, f'SELECT COUNT(*) FROM "{table}";')  # no-check: sql-fstring — table name validated at :212
```

- The marker is comment-syntax agnostic (`#`, `//`, `--` all work — it is the token that matters, not the comment style), lower-case (like `# nosemgrep` / `# noqa`), and takes a comma-separated list: `# no-check: sql-fstring, raw-row-number`. Text after the ids is a rationale and is ignored — write one. Because ids end at the first character outside `[A-Za-z0-9_-]`, a check id containing anything else cannot be waived; keep ids in the shipped `[a-z0-9-]` shape.
- **The marker is literal text, so a file that *shows* one carries a live one.** It is matched per line, in any file a check scans — there is no "this is only an example" state. Keep marker examples out of scanned `paths:`, or write them with an id you do not ship.
- **A bare `no-check:` with no ids waives nothing.** A blanket marker would silently disable checks that do not exist yet, including a future `severity: critical` one.
- **The marker must sit on the line the finding cites** — for `position_check:` that is the `later` match. The one exception is a file-level check (`invert_file_check: true`), whose finding cites no line, so the marker may sit anywhere in the file.
- **Waiving is never silent.** Waived findings are reprinted with a `[waived]` tag and counted in the summary header (`waived: N`), exactly as `[baseline]` findings are. They do not reach the baseline file and do not trip `--fail-on-blocking`.
- Grep stage only. semgrep, coverage and the typecheckers have their own inline pragmas.

**Fields:**
| Field | Required | Purpose |
|-------|----------|---------|
| `id` | Yes | Unique identifier |
| `name` | Yes | Human-readable name |
| `category` | Yes | Grouping — shipped packs use `correctness`, `security`, `testing`, `convention`, `cleanliness` |
| `severity` | Yes | `low` / `medium` / `high` / `critical` — the vocabulary the shipped packs actually use. **Nothing validates it:** `_validate_check` does not check severity, and `run_checks/grep.py` only upper-cases whatever string it finds, so a typo renders verbatim in the report. |
| `paths` | Yes | Directories to search (literal file-or-directory roots, not globs; `.` / `./` mean the repo root = whole tree). Also scopes `semgrep-*` / `pyright-*` / `tsc-*` registry entries: those tools scan whole trees in one subprocess, so their findings are post-filtered to the entry's `paths:` when declared (Phase 133). Unlocalized `<placeholder>` entries contribute no scoping there — a fully-placeholder list stays whole-tree, a partially-localized list scopes to its localized entries — while the `__disabled_no_op__` sentinel scopes the check to nothing (the overlay disable shape now works for these stages too). |
| `include` | Yes | File glob patterns |
| `exclude` | No | File glob patterns to skip (matches file basenames — cannot drop a subtree) |
| `exclude_dir` | No | Directory-basename globs to skip at any depth (grep `--exclude-dir` semantics; Phase 133). Use when a `paths:` root contains a tree that shouldn't be scanned — e.g. a package with `migrations/` or `alembic/` inside it. Applies uniformly: the grep scan and the `semgrep-*`/`pyright-*`/`tsc-*` post-filter both honor it. |
| `pattern` | Yes | Regex to search for (the anti-pattern) |
| `negative_pattern` | No | If present, only flag matches that do NOT also match this |
| `file_must_also_contain` | No | For file-level checks (file has X but not Y) |
| `invert_file_check` | No | If true, flag when `file_must_also_contain` is absent |
| `description` | Yes | What to report when found |
| `convention` | Yes | Which convention this enforces |
| `used_by` | Yes | Which review skills use this check |
| `blocking` | No | If `true`, `--fail-on-blocking` exits non-zero on any non-baseline finding (CI contract). Reserve for deterministic checks with near-zero false-positive rate. **Coverage (`coverage-*`) exception:** a blocking coverage finding fails on *every* finding — it never baseline-suppresses (Phase 61b crown-jewel gate; a diff-relative coverage gap can't stand as tech debt). |
| `notes` | No | Operator-facing notes (e.g., `"Needs LLM triage"` — such checks must NOT be marked blocking). |
| `critical_path` | No | Coverage checks (`coverage-*`) only: the crown-jewel globs that scope the diff-coverage gate (a bare directory glob like `"billing/"` matches everything beneath it). The Phase 61a capability armed as a hard gate in Phase 61b — consumer-authored and **never installer-substituted** (substitution touches `paths:` only), so coverage entries use `critical_path:` as their sole scope field instead of `paths:`. |
| `report` | No | Coverage checks (`coverage-*`) only: path to the coverage report fed to `diff-cover` (default per id — `coverage.xml` for `coverage-diff-python`, `coverage/lcov.info` for `coverage-diff-frontend`). |

**LSP / typechecker findings.** `run_checks_impl.py` invokes `pyright` (Python) and `tsc --noEmit` (TypeScript) after the grep loop. Each diagnostic maps to a `pyright-*` or `tsc-*` check ID; a finding is emitted only when a registry entry with that ID exists (the python / nextjs-react packs ship them), and — Phase 133 — is post-filtered to that entry's `paths:` when the entry declares one (the typecheckers scan the whole project in one subprocess, so per-entry scoping happens on the findings). If a binary is missing, the relevant half silently skips with a stderr warning. `pyright-general-warning` is a catch-all; treat it the same as grep checks with `notes: "Needs LLM triage"`.

**ESLint findings.** `_run_eslint()` invokes `eslint --format json .` from the frontend dir discovered via `_find_frontend_dir()` (the directory under repo root containing `node_modules/eslint`; ambiguous matches raise so consumer misconfiguration surfaces explicitly). All findings map to a single catch-all `lint-error` check_id (registered in `checks.yml`) with the original ESLint rule_id (e.g., `react-hooks/exhaustive-deps`) embedded in the message text. The catch-all avoids enumerating dozens of rule-specific check IDs while keeping full information visible to the reviewer. Skips silently if the `eslint` binary or `node_modules/eslint(-config-next)` is missing. ESLint is registered as `used_by: [codebase-review, security-audit]` because `jsx-a11y/*` rules map to OWASP A07/A05.

**pip-audit findings.** `_run_pip_audit()` invokes `pip-audit --skip-editable --format json` against the active venv, falling back to `python -m pip_audit` when the console script isn't on PATH (a venv-installed pip-audit resolves either way). The stage audits installed packages, so it runs for every requirements layout. All vulnerabilities map to a single catch-all `pip-audit-vuln` check_id (registered in `checks.yml`, `used_by: [security-audit]`). Findings are anchored at the first discoverable `requirements*.txt` (sorted via `_find_requirements_files()`) since pip-audit reports per-package, not per-line; the package name, CVE/GHSA ID, and fix version are embedded in the message. Falls back to `pyproject.toml:1` for manifest-only consumers, then `requirements.txt:1`. Skips with a warning if `pip-audit` is missing both ways. **Known gap:** the audit only sees the venv pip-audit runs in; projects with multiple service-specific venvs need a per-venv invocation.

**Coverage gate (Phase 61a measurement + Phase 61b crown-jewel hard gate).** `_run_coverage()` (in `run_checks/coverage.py`) shells out to `diff-cover` for every `coverage-*` registry entry and reports *changed* lines that lack test coverage, **filtered to the entry's `critical_path:` globs** so only crown-jewel paths are gated (keeping consumer-CI weight small). Both the Python (`coverage-diff-python`) and frontend (`coverage-diff-frontend`) legs route through `diff-cover` — it reads Cobertura XML from `pytest-cov`/`coverage.py` and lcov from `c8`/`istanbul` alike — so the result is uniform *diff* coverage; the language-native tools are the report *producers* (run by CI before this stage, exactly as `coverage.xml` is), named per entry in the `report:` field. `critical_path:` is the schema's crown-jewel capability (parallel to `blocking:`): consumer-authored and **never installer-substituted** (substitution touches `paths:` only), so coverage entries carry `critical_path:` instead of `paths:`. **The gate (Phase 61b):** the shipped entries are `blocking: true`, so an uncovered changed line inside a `critical_path` glob fails `--fail-on-blocking`. Coverage is the one stage that **never baseline-suppresses** — `--update-baseline` will not accept a crown-jewel coverage gap (the carve-out exists precisely so these paths are never "caught later"). A genuinely untestable line is excluded with a coverage pragma (`# pragma: no cover`, `/* istanbul ignore */`) at the report-producer layer — that drops it from the report so it is not a violation — while the task's `## Test decision` record documents *why* (the record does not itself clear the gate). Set `blocking: false` to run measurement only. Skips silently when `diff-cover` is missing or the `report:` file is absent (e.g., CI didn't run coverage), so the stage is inert until a consumer fills `critical_path` and produces a report.

**Standing test assessment (`/test-audit`, Phase 80) — the complement to the diff-scoped gate.** The coverage gate above is deliberately **diff-scoped**: it measures only *changed* crown-jewel lines, so a module untested for a year but never in a diff produces zero findings, and a line a coverage report calls "covered" by a hollow test (asserts nothing) passes. The `/test-audit` skill is the standing, human-invoked counterpart that finds exactly those blind spots — the unchanged/standing gaps and existing-test health (dead, redundant, hollow) — judgment-led over source + test files, reusing the same `critical_path:` globs as its "audit this hardest" signal. It only *recommends* (read-only; routes accepted recs to `/intake`); it never writes tests or gates. The two form a loop: `/test-audit` surfaces a load-bearing gap → the human marks the path crown-jewel + adds the test → the gate keeps it covered going forward. Judgment lives in `_shared/test-assessment-rubric.md` (§ 8.3), shared with `/codebase-review`'s per-file "Test Coverage Gaps" dimension. See `core/skills/test-audit/SKILL.md`.

**Semgrep AST rules.** Rule *bodies* live in `.claude/semgrep/<rule-name>.yaml` (not in `checks.yml`); each rule's `id:` field becomes the check ID prefixed with `semgrep-` (so `id: sql_fstring` → `semgrep-sql_fstring`), and a matching `semgrep-*` *registry entry* in `checks.yml` opts the rule into mode filtering, baselines, and `--fail-on-blocking` — findings for rules without a registry entry are dropped. The registry entry's `paths:` scopes the rule's findings (Phase 133 post-filter; see the `paths` field row), which also means an overlay id-collision entry with `paths: ["__disabled_no_op__"]` now suppresses a shipped semgrep rule consumer-side. Fixtures for each rule live in `.claude/semgrep/fixtures/`. See `.claude/semgrep/README.md` for authoring conventions. The entire stage silently skips if `semgrep` or `.claude/semgrep/` is absent.

**Minimal Semgrep rule example** (`.claude/semgrep/sql_fstring.yaml`):

```yaml
rules:
  - id: sql_fstring
    message: "f-string SQL detected — use parameterized queries"
    severity: ERROR
    languages: [python]
    pattern-either:
      - pattern: f"... SELECT ..."
      - pattern: f"... INSERT ..."
      - pattern: f"... UPDATE ..."
      - pattern: f"... DELETE ..."
```

### 6.6 Deferred docs schema + batch metadata format

**Deferred docs schema** (`sysop/runtime/pending-docs/<sanitized-branch-name>.md`):

The file has YAML frontmatter and no body. The `/` in branch names is replaced with `-` for the filename. The file is untracked (gitignored) — `/review-close` consolidates it into shared docs post-merge and then deletes it.

```yaml
---
branch: <branch-name>
date: <YYYY-MM-DD>
type: <feature|bugfix|ui-iteration|infrastructure|adhoc>
roadmap_ids: [<FEAT-NNNN | TECH-NNNN | BUG-NNNN>, ...]
review_task_ids: [<TASK-NNNN>, ...]
summary: "<one-sentence description of the work, including key files affected>"
---
```

**Two ID namespaces — each independently optional** (Phase 23a; either or both may be `[]`). `roadmap_ids` holds IDs that live in `tasks/index.yml` (typically `FEAT-*`/`TECH-*`/`BUG-*`); `/review-close` Step 4c round-trips each one — flips `status: done` and archives the body file — and silently skips an ID with no index entry, so misclassifying review-task IDs here makes them invisible. `review_task_ids` holds `review_tasks.md` IDs (typically `TASK-*`) and is documentary only — their actual closure happens via `close_batch.sh` in Step 4b. (A legacy single `task_ids:` key is still read through a compatibility fallback slated for removal — do not author it.)

**Type selection** — set the `type` based on the intent of the work, not the branch prefix (prefixes can mismatch). If multiple types apply, pick the primary one.

| Type | When to use |
|---|---|
| `feature` | New user-facing functionality, `FEAT-*` task |
| `bugfix` | Fixing broken behavior, `fix:` commits |
| `ui-iteration` | Visual/UX changes to existing components |
| `infrastructure` | `TECH-*`, `DATA-*`, `UX-*` tasks, tooling, pipeline |
| `adhoc` | One-off work, no task ID |

**Routing table** (which shared *prose* docs `/review-close` updates based on `type`):

| Type | PROJECT_STATUS | Changelog | UI_Iterations |
|---|---|---|---|
| feature | Yes | — | — |
| bugfix | Yes | Yes | — |
| ui-iteration | Yes | — | Yes |
| infrastructure | Yes | — | — |
| adhoc | Yes | — | — |

> **This table is only one of `CHANGELOG.md`'s three writers — do not read it as the whole contract.** The `bugfix → Changelog` cell is the per-type route, and Step 4c has two further, *type-independent* paths into `## [Unreleased]`: the **§6 rotation** (when the shared §6 section exceeds 8 entries, the oldest rotate out to `### Changed` until 6 remain — a move, not a copy) and the **wide-close consolidation** (when a close carries more than 4 bullets, §6 gets one summary entry and the detail goes to the changelog). A reader who reconciles only this table with the skill will conclude the skill is wrong. Both are stated in § 8.1's `CHANGELOG.md` row and implemented in `/review-close` Step 4c; § 2.8 step 7 names the bugfix path only, for the same reason.

> **The roadmap round-trip is type-independent.** Every ID listed in `roadmap_ids` — regardless of `type` — gets the `tasks/index.yml` done-flip and body-file archival in `/review-close` Step 4c. It is deliberately *not* a column of this table: an earlier reading that ran the round-trip only for `feature`/`infrastructure` left a `BUG-*` entry stuck `in_progress` with its body orphaned under `open/` (BeanRider ISSUE-0034).

> **Legacy format:** Older branches may still carry a markdown-sectioned pending-docs file (`## Classification`, `## PROJECT_STATUS Entry`, etc.). `/review-close` detects this by checking whether line 1 starts with `---` and falls back to the legacy parser. Support will be removed once all active worktrees using the old format are merged.

**Batch metadata format** (in `review_tasks.md`):

```markdown
### Batch <N> — <Title> `<Status>`

> **Branch:** `<branch-name>`
> **Scope:** <files affected>
> **Verify:** `<test/build command>`
> **Overlap:** <none | batch-N, batch-M>
> **Flag:** <reason this batch needs manual work> (only if flagged)
> **Triaged:** <YYYY-MM-DD> <auto|flag> [<TASK-NNN, …>] (only after /triage has classified it)

- [ ] **TASK-NNN**: <description> <severity-emoji>
```

All metadata fields use the `> **Key:** value` format. Parsers should extract by matching this pattern.

`Flag:` and `Triaged:` are optional and are written **only by `/triage`** — a review generator emits the first four (plus `OWASP:` on security batches) and nothing else. `Flag:` carries the human-readable reason and its presence is the routing predicate (`/auto-judge` takes the batch, `/auto-fix` skips it). `Triaged:` carries the verdict record: the date the batch was classified, `auto` or `flag`, and — optionally — the bracketed IDs of the tasks that actually need judgment, so `/auto-judge` pays for adversarial reading on those and fixes the rest of the batch mechanically. An **absent** bracket list means the whole batch needs judgment. A `Flag:` line with **no `Triaged:` sibling** records no verdict, so `/triage` re-reads that batch and `/sitrep` routes it to `/triage` rather than onward. Pool membership (`/auto-judge` takes it, `/auto-fix` skips it) still comes from `Flag:` presence alone.

---

## 7. Bootstrap Checklist (New Project Setup)

When starting a new project with this workflow:

### Day 1 — Minimum viable workflow

> **See § 8 for the full portable kit manifest** (every skill, script, and config file to copy). The list below is the minimum viable subset to start working.

- [ ] Create `CLAUDE.md` with project overview, commands, architecture, key files, and an empty `## Prevention Conventions` section
- [ ] Create `.claude/convention_map.md` with 3–5 sections covering the major file areas (API, data layer, UI, tests)
- [ ] Create `sysop/scripts/hooks/pre-commit` with the skeleton from § 6.4 (no checks yet — add them as conventions accumulate)
- [ ] Create `sysop/scripts/install_hooks.sh` to copy hooks to `.git/hooks/`
- [ ] Copy this `WORKFLOW.md` and `WORKFLOW_GUIDE.md` into `sysop/docs/` (where the installer places them)
- [ ] Port the lifecycle skills from § 8.3 (`/next-task`, `/claim-task`, `/document-work` cover the core loop; add others as needed)
- [ ] Port `sysop/scripts/claim_task.sh` and `sysop/scripts/cleanup_worktrees.sh` from the reference implementation (§ 8.4)
- [ ] Set up `review_tasks.md` with an empty `## Round 1` section

### Week 2 — After first development sprint

- [ ] Run your first code quality review (§ 2.5) — this seeds the convention system
- [ ] Extract convention candidates from the review findings
- [ ] Promote 3–5 conventions into CLAUDE.md and update the convention map
- [ ] Add 1–2 blocking checks to the pre-commit hook for the highest-confidence patterns

### Month 1 — Refinement

- [ ] Create `.claude/security_map.md` with OWASP-aligned sections (once you have enough code to audit)
- [ ] Run your first security audit (§ 2.6)
- [ ] Set up the pre-merge hook (§ 4.3) if you have a test suite
- [ ] Review and expand convention map coverage — run the map coverage audit (§ 3.6)

### As needed — Scaling additions

- [ ] Add lock file coordination (§ 4.1 of the original system) if running multiple AI agents in parallel
- [ ] Add batch numbering and round system if review tasks exceed 50
- [ ] Add archive rotation if `review_tasks.md` exceeds 125KB
- [ ] Extract grep checks into `.claude/checks.yml` registry if maintaining checks in skill files becomes painful
- [ ] Add a shared contracts section to the roadmap if multiple agents work on the same feature phase

---

## 8. Portable Kit Manifest

This is the complete list of artifacts a new project needs to replicate the workflow. Templates live in this document (§ 6) where practical; for the larger artifacts (skills, scripts), the reference implementation in the source project is the canonical copy — port whole files, then adapt paths and commands.

> **Install modes.** This manifest describes the **full** install. The installer also supports `--mode loop`, which delivers only the convention-loop subset — the review/audit skills, the convention + security maps, and the compiled checks — with no task lifecycle (no `tasks/` queue, worktrees, or merge gate; enforcement is the pre-commit hook's own check slots plus CI, whose shipped template runs `run_checks`). A loop-mode install deliberately does not receive this document; its orientation lives in the public docs ([docs/loop-mode.md](https://github.com/getsysop/sysop/blob/main/docs/loop-mode.md), reference: [docs/install-and-update.md § Install modes](https://github.com/getsysop/sysop/blob/main/docs/install-and-update.md#install-modes-full-and-loop)).

### 8.1 Documentation (root of project)

| File | Source | Purpose |
|------|--------|---------|
| `sysop/docs/WORKFLOW.md` | this file | Authoritative process spec (you are reading it) |
| `sysop/docs/WORKFLOW_GUIDE.md` | companion file | Human-readable variant for contributors not using an AI agent |
| `CLAUDE.md` | template § 6.1 | Project reference: architecture, commands, key files, prevention conventions, env vars |
| `tasks/index.yml` + `tasks/{open,deferred,archive}/*.md` | format `tasks/schema.md` | Hybrid task system: YAML index is the source of truth for task metadata (`id`, `status`, `effort`, `blast_radius`, `user_action`, `depends_on`, `body:`, optional `whitelist:`, optional `manual_smoke:`). Per-task `.md` bodies hold prose only. `effort` captures how much work; `blast_radius` (Phase 19) captures surface area independently; `manual_smoke: true` (Phase 35, BeanRider ISSUE-0008) declares this task needs a pre-merge human smoke that `/review-close` Step 3c will gate on (procedure under a `## Manual smoke required`-style heading in the body — Phase 218 widened the accepted phrase list and made the declaration itself signal even when no heading matches; see `tasks/schema.md` § Manual smoke). `whitelist:` (Phase 27) lets a parent task list IDs that should bypass `/document-work` Step 3b's follow-up-stub check (mirrors the pending-docs frontmatter `whitelist:` bypass; persistent vs. one-off). Validator at `sysop/scripts/validate_tasks.py` enforces 13 invariants — on demand, or at commit time once wired into pre-commit (opt-in; § 8.4) (Invariant 12 is warn-only: when `manual_smoke: true`, body should contain a smoke heading; Invariant 13 (Phase 58b) is warn-only: an `in_progress` task's body should contain a `## Test decision` heading — the plan-time "test X proves Y" / "no test because Z" record `/review-close` reads back); `blast_radius` is optional at `schema_version: 1`, required on `open`/`in_progress` at `schema_version: 2`. Invariant 9 (`in_progress requires lock`) resolves the lock path via `git rev-parse --git-common-dir` (Phase 32, 2026-05-22) so every caller — pre-commit from inside a worktree, `/review-close` from main, ad-hoc CLI — finds the same canonical `<main-repo-root>/sysop/runtime/locks/<TASK-ID>.lock`. Replaces the single-file `product_roadmap.md` shape earlier Sysop consumers used. |
| `review_tasks.md` | format § 4.2 | Live review task tracker (starts with one empty `## Round 1` section) |
| `sysop/SYSOP_ISSUES.md` | seeded by installer on fresh install only | Project-owned log for signal encountered while using Sysop — friction (`ISSUE-NNNN`) and wins (`GOOD-NNNN`, `[good]`). **NOT** in `managed_paths`; `--update` never touches it. `/review-close` Step 7 prompts the agent to append both during cycle close-out; `/report-issues` files friction entries upstream as GitHub issues, and `/share-wins` shares `[good]` wins upstream as a Sysop Discussion comment (both per-entry consent). See § 8.2b. |
| `CHANGELOG.md` | project-owned; written by `/review-close` Step 4c and `/release` under one shared contract | Optional [Keep a Changelog](https://keepachangelog.com) file. **NOT** installed or in `managed_paths` — the installer never seeds it. **Two skills write it, under one grammar (Phase 222, Q-279):** `/review-close` Step 4c routes per-close bullets (bugfix entries, §6 rotation, the wide-close consolidation) into `## [Unreleased]`, and `/release` folds `[Unreleased]` into the `## [x.y.z]` version entry it prepends (uncommitted) when you cut a release, alongside an annotated git tag and an optional GitHub Release. Both resolve an existing changelog tracked under another case (e.g. `changelog.md`) to the same file rather than creating a second name — the two names are one file on a case-insensitive filesystem (the macOS/Windows default). An earlier revision of this row said Sysop never touches this file; that was false the whole time Step 4c's bugfix routing existed. |

### 8.2 `.claude/` config directory

| File/dir | Source | Purpose |
|----------|--------|---------|
| `.claude/convention_map.md` | template § 6.2 | Maps file globs to applicable prevention conventions |
| `.claude/security_map.md` | template § 6.3 | Maps file globs to OWASP check/skip lists |
| `.claude/checks.yml` | format § 6.5 | Grep check registry (starts empty — grows via convention promotion) |
| `.claude/checks_baseline.txt` | auto-generated, hand-editable | Pre-scan baseline — every check's accepted findings except coverage (seeded by `run_checks.sh --update-baseline`; hand-added entries take their key from `--print-keys`, and `#` comments are preserved by `--migrate-baseline` but not by `--update-baseline`) |
| `.claude/semgrep/*.yaml` | format § 6.5 | Optional Semgrep AST rules; skipped cleanly if absent |
| `.claude/semgrep/fixtures/` | — | Positive/negative test cases for each rule |
| `.claude/semgrep/README.md` | — | Authoring conventions for Semgrep rules |
| `.claude/review_index.json` | auto-generated | Shadow JSON index of `review_tasks.md`; rebuilt by `sysop/scripts/review_index.py` |
| `.claude/skills/*/SKILL.md` | see § 8.3 | Agent execution files (Claude Code skills in the reference impl) |
| `.claude/settings.json` | template § 8.2a | Project-scoped permission allow-list for the agent harness. |
| `.claude/sysop.lock` | installer | Install manifest (Sysop commit, packs, managed paths). Required by `--update` / `--check` (§ 8.2b). |
| `.claude/convention_map.project.md` | consumer-authored (optional) | Phase 24a (BeanRider ISSUE-0023): project-specific convention sections. When present, `install.sh` appends it (blank-line separator) to `.claude/convention_map.md` AFTER the core+pack body. **NOT** in `managed_paths`; `--update` never touches it. Same protection property as `tasks/index.yml` and `SYSOP_ISSUES.md`. See § 8.2c. |
| `.claude/security_map.project.md` | consumer-authored (optional) | Phase 24a: project-specific security map sections. Same append-after-concat semantics + protection property as `convention_map.project.md`. See § 8.2c. |
| `.claude/checks.project.yml` | consumer-authored (optional) | Phase 24a: project-specific grep checks. Must be a self-contained YAML doc with a top-level `checks:` list (NOT a `.fragment`-shaped file — pack fragments rely on the awk header strip). When present, `install.sh` merges it into `.claude/checks.yml` by `checks[*].id` — consumer wins on collision with a `⚠ id-collision: <id>` warn line so the substitution surfaces in the post-update delta. See § 8.2c. |

Two further installer-written paths live **outside** `.claude/` and so aren't in the table above — the Codex skill links at `.agents/skills/codebase-review` and `.agents/skills/security-audit` (§ 8.2d). They enter `managed_paths` when Sysop actually owns them, which is the normal case; the three deliberate exceptions (opted out, probe failed, or the path is consumer-owned) are in § 8.2d.

### 8.2a Required permissions (`.claude/settings.json`)

In agent harnesses like Claude Code, several skills perform git operations the harness may refuse (e.g., `git merge --ff-only` into `main`, `git worktree remove`, `git push origin --delete`). The mode that makes a refusal **non-interactive** is `permissions.defaultMode: "dontAsk"`, which auto-denies every tool call that would otherwise prompt — only `permissions.allow` rules, read-only Bash commands, and `PreToolUse`-approved calls run. There, missing allow-rules surface as opaque halts — worst-case mid-merge, with worktrees half-applied. Under `auto` the classifier can also block a call, and the denial is surfaced (notification + a `/permissions` retry entry) rather than silent, but the step still failed.

> **Phase 152 correction.** Through Phase 151 this section named the hazard as `permissions.defaultMode: "auto"` + `skipAutoPermissionPrompt: true`. A `claude-code-guide` probe of the official permissions/settings/changelog docs (2026-07-26) found no such key as `skipAutoPermissionPrompt`, and found `auto`-mode denials to be surfaced rather than silent; `dontAsk` is the documented no-prompt-denial mode. Two further facts from the same probe shape the list below: **read-only forms of `git` are auto-approved in every mode** (so read-only git verbs must not be listed as required rules), and **`gh` is not in that read-only set at all** (so every `gh` call, including `gh auth status`, needs a rule).

The reference installer (`bash install.sh`) writes a project-scoped `.claude/settings.json` covering exactly what the documented skills need. The **authoritative** allow-list is that installed file (written verbatim from `core/companion/.claude/settings.json` in the reference impl); the block below is an **illustrative core subset** — enough to show the shape, not the complete list (see the note after the table). The shape:

```json
{
  "permissions": {
    "allow": [
      "Bash(git checkout:*)",
      "Bash(git fetch origin:*)",
      "Bash(git merge --ff-only:*)",
      "Bash(git rebase:*)",
      "Bash(git rebase --abort)",
      "Bash(git reset --hard origin/main)",
      "Bash(git branch -d:*)",
      "Bash(git branch -D:*)",
      "Bash(git worktree list:*)",
      "Bash(git worktree add:*)",
      "Bash(git worktree remove:*)",
      "Bash(git cherry-pick:*)",
      "Bash(git push origin:*)",
      "Bash(git push -u origin:*)",
      "Bash(git push --force-with-lease:*)",
      "Bash(git add:*)",
      "Bash(git add tasks/index.yml)",
      "Bash(git commit -m claim:*)",
      "Bash(git commit -m rollback:*)",
      "Bash(bash sysop/scripts/claim_task.sh:*)",
      "Bash(bash sysop/scripts/batch_work.sh:*)",
      "Bash(bash sysop/scripts/close_batch.sh:*)",
      "Bash(bash sysop/scripts/run_checks.sh)",
      "Bash(bash sysop/scripts/run_checks.sh:*)",
      "Bash(bash sysop/scripts/install_hooks.sh)",
      "Bash(python sysop/scripts/archive_review_tasks.py:*)",
      "Bash(python3 sysop/scripts/archive_review_tasks.py:*)",
      "Bash(python3 -c:*)",
      "Bash(python3 -:*)",
      "Bash(python3 sysop/scripts/validate_tasks.py)",
      "Bash(python3 sysop/scripts/validate_tasks.py:*)"
    ]
  },
  "hooks": {
    "PermissionDenied": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $CLAUDE_PROJECT_DIR/sysop/scripts/permission_denied_hook.py"
          }
        ]
      }
    ],
    "SubagentStop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 $CLAUDE_PROJECT_DIR/sysop/scripts/parse_subagent_envelope.py"
          }
        ]
      }
    ]
  }
}
```

| Rule | Skills that need it |
|------|--------------------|
| `Bash(git checkout:*)` | `/claim-task`, `/auto-build` (Step 5 rollback path), `/review-close`, `/auto-fix`, `/auto-judge` |
| `Bash(git fetch origin:*)` | `/review-close` (the `_shared/main-push-guard.md` Rule B safe-push fetch, under **both** merge policies; plus Step 4-pre under `pr`), `/release` |
| `Bash(git merge --ff-only:*)` | `/review-close` |
| `Bash(git rebase:*)` | `/review-close` |
| `Bash(git rebase --abort)` | `/review-close` |
| `Bash(git reset --hard origin/main)` | `/review-close` Step 6 (`pr` policy — re-sync local `main` after the squash-merge) |
| `Bash(git branch -d:*)` | `/review-close` |
| `Bash(git branch -D:*)` | `/review-close` Step 6 (`pr` policy — the integration branch and squash-merged feature branches are not `-d`-deletable) |
| `Bash(git worktree list:*)` | `/review-close` (Step 1a + 3c `--porcelain` enumeration) — the only skill that shells it. `/sitrep` reaches the same data through `sitrep_survey.py`; `/auto-fix` and `/auto-judge` declared it until Phase 152 for a command neither runs |
| `Bash(git worktree add:*)` | `/claim-task` (via `claim_task.sh`), `/auto-build` (via `claim_task.sh` in Step 5.2), `/auto-fix`, `/auto-judge` (via `batch_work.sh`) |
| `Bash(git worktree remove:*)` | `/review-close` |
| `Bash(git cherry-pick:*)` | `/review-close` (rare path when worktree removal isn't possible) |
| `Bash(git push origin:*)` | `/review-close` (main push, branch deletion), `/auto-fix`, `/auto-judge` |
| `Bash(git push -u origin:*)` | `/document-work`, `/auto-fix`, `/auto-judge` |
| `Bash(git push --force-with-lease:*)` | `/auto-fix`, `/auto-judge` (when subagents amend) |
| `Bash(git add:*)` | Plain `git add <path>` staging — `/review-close` Step 4c's consumer-authored docs, the review skills' Step 7 archive add, and their Step 2a coverage + Step 9/9b promotion/demotion staging (unrolled from `for … done` loops by Phase 153). Does **not** reach the `cd … && git add …` compounds in the worktree skills; see § Invocation shapes |
| `Bash(git add tasks/index.yml)` | `/auto-build` Step 5.4 (commit each claim flip) — subsumed by `Bash(git add:*)`, kept because skills name it and removing a template rule never removes it from an installed consumer |
| `Bash(git commit -m claim:*)` | `/auto-build` Step 5.4 (commit message shape: `claim: mark <TASK_ID> as in-progress`) |
| `Bash(git commit -m rollback:*)` | `/auto-build` Step 5 rollback path on pre-claim failure |
| `Bash(bash sysop/scripts/claim_task.sh:*)` | `/claim-task`, `/auto-build` (Step 5.2 sequential pre-claim, one invocation per batched task) |
| `Bash(bash sysop/scripts/batch_work.sh:*)` | `/auto-fix`, `/auto-judge` |
| `Bash(bash sysop/scripts/close_batch.sh:*)` | `/review-close` |
| `Bash(bash sysop/scripts/run_checks.sh)`, `Bash(bash sysop/scripts/run_checks.sh:*)` | `/codebase-review`, `/security-audit`, `/review-close` |
| `Bash(bash sysop/scripts/install_hooks.sh)` | _(direct user invocation only — no skill or lifecycle script shells out to it; `claim_task.sh` and `batch_work.sh` both did until Phase 150 removed the worktree auto-arm)_ |
| `Bash(python sysop/scripts/archive_review_tasks.py:*)`, `Bash(python3 sysop/scripts/archive_review_tasks.py:*)` | _(no skill invokes the archiver — `/triage`, `/auto-fix` and `/auto-judge` name it in an advisory addressed to the operator, and `/codebase-review` and `/security-audit` only stage `review_tasks_archive.md` if it already exists. The rules are kept as headroom for an operator running it from a skill session, and because removing a template rule never removes it from an installed consumer.)_ |
| `Bash(python3 -:*)` | `/claim-task` Step 2/4, `/auto-build` Step 1 (queue-read/readiness-filter heredoc) + Step 5.1 (yaml-round-trip status flip), `/review-close` Step 3c + Step 4c (heredoc'd yaml.safe_load / safe_dump round-trips against `tasks/index.yml`), `/document-work` Step 3b (heredoc'd follow-up-stub check against `tasks/index.yml`) |
| `Bash(python3 -c:*)` | _(no skill — since Phase 126 every skill heredoc uses the `python3 - <<` form. Retained as headroom; the one live `python3 -c` is inside `claim_task.sh`, a subprocess of an already-permitted `bash` call, which binds no rule of its own.)_ |
| `Bash(python3 sysop/scripts/validate_tasks.py)`, `Bash(python3 sysop/scripts/validate_tasks.py:*)` | `/auto-build` Step 5.3 (post-claim schema validation), `/review-close` Step 4c (final-guard task-state validation) |

**This block is an illustrative subset — the installed `.claude/settings.json` is authoritative.** The reference template (`core/companion/.claude/settings.json`) carries additional rules the core subset above omits, added by later phases:

- the **GitHub-CLI family** — `gh auth status`, `gh pr {list,view,create,checks,merge,close}`, `gh issue {list,create}`, `gh repo view`, `gh release create`, and `gh api graphql` (Discussions, used by `/share-wins`) — used by `/review-close`'s `pr` merge policy, `/pr-dependabot`, `/report-issues`, `/contribute-convention`, `/share-wins`, and `/release`. **Every one of these needs a rule**: `gh` is outside the harness's built-in read-only set, so even `gh auth status` and `gh repo view` are denied under `dontAsk` without one (Phase 152 — several skills previously justified omitting them by calling them read-only ops);
- `git tag:*` (`/release`); `git add review_tasks.md` (the review skills — `/codebase-review`, `/security-audit`, `/triage`, `/review-close`); and `git commit -m docs:*` (the `docs:` / `Doc-Work` commit shape, e.g. `/document-work`);
- the `.venv/bin/python3` variants of the script rules (Phase 45b), and the `sitrep_survey.py` / `next_task.py` / `pr_dependabot.py` script rules used by `/sitrep`, `/next-task`, and `/pr-dependabot`.

When a new skill needs a permission rule, add it to the template — this doc subset is deliberately **not** kept in lockstep, so treat the installed file (and `core/companion/.claude/settings.json` in the source tree) as the source of truth.

**A note on `Bash(python3 -:*)` and `Bash(python3 -c:*)`.** These rules allow heredoc'd or `-c`-flag-passed python with any argv, including any `subprocess` invocation from inside the script — so the practical breadth is "the agent can run arbitrary shell via python." We accept this trade-off because the alternative (heavy regex substitution in bash for YAML round-trips) is fragile and Phase 16 specifically replaced that pattern. If your project's threat model can't tolerate this breadth, drop these two rules and accept that `/claim-task` Step 2 + Step 4, `/auto-build` Step 2 + Step 5.1, `/review-close` Step 4c, and `/document-work` Step 3b will require manual `python3` approvals at runtime.

**`AskUserQuestion` does NOT satisfy the auto-mode classifier when a push is denied.** Empirical (BeanRider 2026-05-12): agent calls `git push origin main` → classifier denies with "Pushing directly to main bypasses PR review" → agent asks the user via `AskUserQuestion` with a clear "Yes, push" option → user answers Yes → agent retries → classifier denies **again** with "AskUserQuestion was not answered with explicit approval." The classifier does not see (or chooses to disregard) the answer. The only unblocks are (a) a pre-laid `Bash(git push origin:*)` allow-rule (the default below covers this), or (b) the user running `! git push origin main` themselves in the prompt. When a skill hits the silent-deny path on push, it should prompt the user for the `!`-shell-escape — never `AskUserQuestion`.

**Phase 36 — `PermissionDenied` hook surfaces escape guidance automatically.** Claude Code 2.1.89 added a `PermissionDenied` hook event that fires after the auto-mode classifier denies a tool call. Sysop ships `sysop/scripts/permission_denied_hook.py` and registers it under `settings.json::hooks.PermissionDenied` so that when the classifier hard-blocks any of three well-known patterns — `git push origin main` (protected-branch policy), `git push origin --delete <branch>` (destructive-flag protection), or `git commit` while the current branch is `main`/`master` (protected-branch policy extended to the enabling commit) — the hook emits an `additionalContext` payload telling the model the exact `!`-prefixed shell-escape command to relay to the user, plus the venv-prefixed variant (`! PATH=.venv/bin:$PATH …`) when the consumer repo has a `.venv/` directory at the main repo root (resolved via `git rev-parse --git-common-dir`, so worktrees inherit the main repo's venv detection). The hook can NOT bypass the classifier itself (returning `retry: true` would just re-hit the same deny) — it surfaces guidance so the model doesn't need to remember it from skill prose. Unmatched denials produce no output (denial stands silently, same as pre-Phase-36 behavior); the hook only fires on patterns we know the classifier overrides allow-rules for. Verification-command denials (Step 3 — `pytest`, `npm test`, etc.) are NOT covered by the hook because the vocabulary varies too widely per consumer; the prose in `/review-close` Step 3 stays as the load-bearing instruction there. **Nor is `gh`, and that gap sits on the dominant path rather than an edge one** (Phase 175): under `pr` merge policy every close runs through `gh pr list`/`create`/`checks`/`view`/`merge` at Step 4d, and none of them matches — the three patterns are `git` shapes, so a `gh` denial runs the whole matcher loop, matches nothing, and falls through to the silent no-op like any other. `/review-close` relays those escapes from its own prose for the same reason Step 3 does. **State the hook's coverage as the three patterns, never as the steps that use them:** two shipped sites had promised the hook would rescue a denied `mkdir`/`cp` and a denied `gh pr`, and a third described the coverage by step number, which is how the `gh pr` claim looked plausible. The hook is presence-merged into existing consumer settings via `install.sh::install_permissions` (Phase 36 extension) — keyed by hook script filename, so consumer customizations of the same `PermissionDenied` event stay alongside Sysop's entry rather than being overwritten. Sub-agent fire behavior (Agent-tool spawns from `/claim-task` / `/auto-build`) is undocumented in Claude Code 2.1.89; verify on first consumer absorption.

**Phase 37 — `SubagentStop` hook parses sub-agent envelopes structurally.** Claude Code 2.1.47 added a `last_assistant_message` field to the `Stop` and `SubagentStop` hook inputs ("the final assistant response text so hooks can access it without parsing transcript files"); `agent_id` and `agent_transcript_path` arrived earlier, in 2.0.42. (Phase 37 originally attributed `last_assistant_message` to 2.1.41 — corrected against the changelog in Phase 54.) Sysop ships `sysop/scripts/parse_subagent_envelope.py` and registers it under `settings.json::hooks.SubagentStop` so that when a sub-agent finishes — `/claim-task`'s planner / reviewer / executor (Steps 7a, 7b, 7e) or `/auto-build` Phase 6e's execution agent — the hook parses the YAML envelope (`TASK:` / `STATUS:` / `WORKTREE:` / `BRANCH:` / `BLOCKER_QUESTION:` / `PARKED_REASON:` / `ERROR:`) from `last_assistant_message` on the harness's terms and writes structured JSON to `<repo>/sysop/runtime/subagent-envelopes/<TASK_ID>.json`. When `last_assistant_message` is absent, the hook falls back to reading the last assistant message from the sub-agent's own JSONL transcript at `agent_transcript_path`, recording the source used in the payload's `message_source` field (Phase 54). The hook also extracts the sealed `REVIEW_REPORT:` YAML at the TOP of the response and includes it as `review_report_raw`. Parent skills read the JSON file first and fall back to regex-parsing the agent's return text if the file is missing or malformed (Phase 7 envelope-recovery — `/auto-build`'s filesystem check via `git log $PRE_EXEC_HEAD..HEAD` + `sysop/runtime/pending-docs/<branch>.md` — stays as the deepest fallback). That fallback is defense in depth, not a race guard: the hooks docs now document the `SubagentStop` lifecycle (the hook runs synchronously on sub-agent completion and can block the stop via `decision: "block"`, so it completes before the parent receives the Agent tool's return). Phase 37 originally treated the timing as undocumented; Phase 54 retired that caveat. Multi-envelope shapes (an agent that emits two envelope blocks across an abort+restart sequence) resolve last-wins, matching the prompt's "LAST content in your final message" instruction. Unparseable inputs land as `_unparseable_<session>_<agent>.json` diagnostics that persist across runs for inspection; parsed envelopes land as `<TASK_ID>.json`. **They used to be deleted by the parent skill after consumption, and Phase 171 stopped that** — deleting the envelope at the moment it became evidence is why a review that *did* run and a review that was skipped left identical traces, which is internal tracker #220's root cause. `/claim-task` Step 8 now reads and keeps them. Because the hook keys the filename by claim id and phase with **no run component**, `/claim-task` Step 7-pre instead *moves* any envelopes left over from a previous run of the same claim into that run's own artifact directory (`<ARTIFACT_DIR>/prior-envelopes/`) before spawning anything: the mailbox is empty by construction at the start of each run, so "first hit wins" cannot hit a stale `exec.json`, and nothing is destroyed. `/auto-build` still deletes its own after consumption.

**Phase 159a — per-phase envelope keying, and the `TASK:` grammar realigned with the schema.** Two changes to the same hook, both required before the orchestrator reshape (specified in `tools/CLAIM_TASK_ORCHESTRATOR_SPEC.md`, maintainer-side and not in the public tree) can spawn a planner, a reviewer and an executor under one claim id. (1) The output file was keyed by the `TASK:` field alone, so a claim could hold exactly one envelope and a second enveloping sub-agent silently overwrote the first. An **optional `PHASE:` envelope field** now keys the file per stage — `<TASK_ID>.<phase>.json` when present, `<TASK_ID>.json` when absent or set to the documented `none` sentinel. The absent case is byte-identical to the pre-159a filename, so both current producers (`/claim-task` Step 7, `/auto-build` Phase 6e) and the read-then-`rm -f` consumers of the day were unaffected (Phase 171 later retired `/claim-task`'s delete — see above — leaving `/auto-build` Phase 6e as the only one); `PHASE:` is sanitized and length-capped before it reaches a path, and `TASK:` keeps its own shape check, so the change adds no injection surface. (2) The hook's `_TASK_ID_SHAPE_RE` was `^[A-Z][A-Z0-9]*-[A-Z0-9][A-Z0-9-]*$` while `validate_tasks.py`'s `_TASK_ID_RE` (and `tasks/schema.md` § Task ID) is `^[A-Z][A-Z0-9-]{2,80}$` — narrower in one direction (it **required** an interior hyphen, so schema-valid ids like `FEAT001` and `ABC` were rejected by the hook and silently downgraded to an `_unparseable_` diagnostic plus the parent's regex fallback) and looser in another (unbounded length where the schema caps at 81). The hook now carries the schema's grammar verbatim. The two patterns stay deliberately duplicated rather than imported — the hook is executed by the harness independently of the validator, and a hook that fails because a sibling script was missing from a partial install is worse than the duplication, the same reasoning the git-common-dir resolution carries across `claim_task.sh` / `batch_work.sh` / `close_batch.sh` / `next_task.py` / `validate_tasks.py` / `scope_overlap.py` — so a drift guard in `tests/test_parse_subagent_envelope.py` asserts the two patterns are identical. The hook is presence-merged via the same `install.sh::install_permissions` extension Phase 36 introduced (`SYSOP_HOOK_FILENAMES` tuple grew to include `parse_subagent_envelope.py`).

**Phase 54 — `disallowed-tools` frontmatter structurally enforces read-only skills.** Claude Code 2.1.152 added skill frontmatter `disallowed-tools` ("remove tools from the model while the skill is active"). Sysop sets `disallowed-tools: Edit, Write, NotebookEdit` on its read-only skills — `/sitrep` and `/next-task` at Phase 54, since joined by `/roadmap`, `/daily-summary`, and `/test-audit` — turning their prose-only "read-only" claims into a harness-level guard — same promotion pattern as Phases 36 and 37 (prose convention → structure). The enforcement is deliberately partial: these skills shell out via `Bash` for their git/python reads, so `Bash` stays allowed and a shell redirect could still write; the guard removes the dedicated write tools, it does not sandbox the skill. `/triage` is excluded — it legitimately writes `review_tasks.md`, and `disallowed-tools` has no per-path granularity. Non-Claude-Code agents consuming bash-installer-delivered skill copies treat SKILL.md frontmatter as inert prose; the unknown key is harmless there.

**Conscious omissions** (NOT in the allow-list, by design):

- `Bash(git *)` — too broad; would whitelist `git reset --hard <anything>`, `git push --force` (no-lease), force-push to main, etc. The point of an allow-list is to keep risky ops in the approval funnel, not to hand over the whole verb.
- `Bash(git push --force:*)` — non-lease force-push; use `--force-with-lease` instead.
- `Bash(git commit:*)` — not granted, so the only commit shapes the allow-list pre-authorizes are the three seeded ones (`claim:`, `rollback:`, `docs:`). This is narrower than what the skills write: `/auto-fix` and `/auto-judge` document `fix:` / `fix(batch-<N>):` / `revert(batch-<N>):` subjects, which no rule covers and which therefore route to the classifier like any other unlisted call. Neither skill declares a commit rule in its pre-flight, so this is a deliberate gap, not an oversight — but do not describe the seeded three as *the* commit shapes Sysop uses.

**Two entries left this list in Phase 152**, both because a skill's documented happy path requires them and the stated reason for omitting them did not survive verification:

- `Bash(git branch -D:*)` — previously omitted as "force-delete; the user should approve interactively." `/review-close` Step 6 under `pr` policy deletes the integration branch and the squash-merged feature branches, neither of which `-d` will drop, so the omission made the documented flow unsatisfiable. The narrower `Bash(git reset --hard origin/main)` (exact string, one ref) joined for the same step.
- `Bash(git add:*)` — previously omitted because "the auto-mode classifier passes these for staged/local-only changes." That is false under `dontAsk`, where an unlisted call is auto-denied, and `/review-close` Step 4c stages consumer-doc names (`CHANGELOG.md`, `UI_Iterations.md`) that no literal-path rule can enumerate. Staging remains the least-privileged write verb — what may be *done* with a staged tree is still bounded by the separately-granted commit and push rules. **Scope of the fix, stated honestly:** it authorizes plain `git add <path>` commands only. Phase 153 unrolled the review skills' Step 2a, Step 9 and Step 9b staging loops, so those sites are now covered too — but **not** every staging site Sysop ships: `/auto-fix`, `/auto-judge`, `/triage`, `/claim-task`, `/auto-build` and `/review-close` Step 4b all stage inside `cd … && git add … && git commit …` compounds, which this rule does not reach. Loop mode carries the rule for its review skills' Step 7 archive add and the same Step 2a/9/9b staging. See § Invocation shapes.

**§ Invocation shapes — a rule authorizes a *command*, not a *step*.** Added by Phase 152's adversarial review, which found the phase had verified the surface at the level of rule strings and never at the level of the bash the rules were meant to authorize. The matcher compares against the **literal text the model sends**, splits compound commands on `&&`, `||`, `;`, `|`, `|&`, `&` and newlines, and requires **each** part to match independently. Four shapes therefore defeat an otherwise-correct rule:

- **Assignment capture.** `PR_REF="$(gh pr create …)"` starts with `PR_REF=`, and an allow rule "won't match past an assignment of any other variable." (A fixed set of known-safe environment variables *is* stripped, so `NODE_ENV=test npm test` does match `Bash(npm test *)`; ordinary capture variables are not in it.) So `Bash(gh pr create:*)` does not authorize that line even though it ships.
- **Loops.** `for p in …; do git add -A -- "$p"; done` splits into parts including `for p in …` and `done`, neither of which any rule matches. Seeding a wider rule cannot fix this shape.
- **Tails.** `… || true` and `… 2>/dev/null || true` split on `||`; `true` is not in the documented read-only command set, so the tail is its own unmatched part. (The set is documented as non-exhaustive, so this one is a risk rather than a certainty.)
- **Variable command words.** `$PY script.py` binds no static rule; keep command words literal.

**Sysop's own call sites were audited against this and reshaped where reshaping is possible (Phase 153).** None of the four shapes can be fixed by widening a rule — no rule shape covers `for`/`done` at all — so the fix belongs at the call site. What changed: `/review-close`'s `pr` path runs `gh pr list` and `gh pr create` **bare**, reading their output from stdout, with the PR number and integration-branch name written out as **quoted** literals at every later use (quoted because unquoted `<PR>` is a bash redirection, and because an unsubstituted `"<PR>"` then fails loudly where an *empty* `gh` operand would silently resolve the current branch). Its two `|| true` tails became `|| echo …`, which keeps the do-not-abort semantics while staying authorized — `echo` is in the documented built-in read-only set, `true` is not. Its Step 4-pre commit sweep became a single `git cherry-pick origin/main..main` range instead of a loop over `git rev-list`. Both review skills' Step 2a/9/9b staging became one plain `git add -A -- <path>` per candidate path — the *list* is unchanged and still run unconditionally, so the consumer-install `.project.*` overlay write stays mechanically guaranteed; only the loop went.

**The authoring rule this yields:** before adding a rule, read the line of bash it is supposed to authorize; prefer a plain unwrapped command at any call site a rule is meant to cover; and where a command needs a value produced earlier, **write the value out, quoted** rather than carrying it in a variable — the assignment would cost the invocation its rule match, and the variable would not have survived anyway. **Scope, because the unscoped reading is wrong and was acted on once:** *quoted* applies to a **value that can contain spaces or shell metacharacters** — a PR number consumed by `gh`, a branch name, a path. It is **not** a corpus-wide rule about the unquoted `<PLACEHOLDER>` operand, which is the house convention across the shipped skills and is **pinned by a test** (`tests/test_batch_claim_kinds.py::TestEntryStateProseGuards`). Phase 169 read this sentence as corpus-wide, quoted three placeholder sites, and turned four tests red.

**§ Persistence boundary — the fenced block, not the step.** Until Phase 169 the sentence above ended "skill *steps* are separate shell calls", and that granularity was wrong in the direction that hides defects. A step is a `##` heading: prose, with no mechanical realization. Nothing binds the fenced blocks under one heading into a single shell call — the agent running the skill reads the prose between them and is free to split anywhere, or to interleave other tool calls. So the boundary an author may rely on is the **block**: **assume nothing survives from one fenced block to the next, even inside a single step.** That is deliberately a requirement on the author rather than a claim about the runner, so it holds however the harness batches; the strictly-safe form is to write the value out at *every* use site.

The step-granular wording did not merely read loosely — it licensed live defects and then defended them. `/review-close` Step 4-pre assigned `APPROVED_BRANCH=` in one block and read it six times across the two blocks after it, all under the same heading; the note meant to catch exactly this scoped its own remedy to "each later step", so it prescribed nothing, and a Phase-164 sweep cited that note as its warrant for excluding all six sites. Run as written they expanded empty, and the *shape* of the failure is why nobody noticed. Condition 4 became `git rev-list --count "..origin/"`, which fatals and prints **nothing** — and the step's own rule reads a missing count as "conditions unmet", so every run fell through to the integration-branch shape and the PR-reuse path was unreachable. It fails safe, which is exactly why it survived: the fall-through is also the correct outcome most of the time. The two neighbouring commands hid it further rather than causing it — `git fetch origin ""` exits 0 and prints a normal-looking line, and condition 5's `git rev-list --count "..origin/main"` silently resolves the empty side to `HEAD` and prints a plausible number. Phase 169 converted the sites to literals and this paragraph is the root-cause fix — the skills were the symptom.

**What remains uncovered — recorded, not hidden.** Reshaping has limits, and three classes survive:

- **Loops over sets discovered at runtime cannot be unrolled.** `/review-close` **Step 1c** iterates the branch list with `while IFS= read -r branch` (read-only commands only). It was a `for … in $BRANCHES_TO_MERGE` until Phase 219, and this bullet called it *Step 4a* — the variable never existed outside Step 1c. The reshape was not cosmetic: an unquoted expansion is word-split by bash and **not** by zsh, so the same check ran twice under one shell and once under the other, and the zsh run emitted no warnings at all. **Step 3b's `*.md` glob loop — the one write loop this bullet used to name, an `rm -f` behind `[ -e … ] &&` — was retired in Phase 210** and is now a `python3 -` heredoc that `Bash(python3 -:*)` already authorizes; a Python `for` is not a shell loop, so the shape leaves this class entirely. **One write loop still survives and this bullet names it rather than dropping it:** Step 3b's `git status --porcelain | while IFS= read -r line; do … rm -f … done` symlink strip, whose set is discovered at runtime and whose body writes. It is the only remaining `rm`-bearing loop in any skill. That is the pattern for the rest: the way out of an unmatched shell shape is usually to stop writing it in shell. `/auto-fix`, `/auto-judge`, `/triage`, `/claim-task` and `/auto-build` likewise run `cd <worktree> && git add -A && git commit …` compounds, where the `cd` alone already defeats the read-only set. These are pre-existing and unfixed; the earlier claim that the reshape covered "every staging site Sysop ships" was false.
- **Assignments that share a fenced block with a reshaped command.** Removing the capture from `gh pr create` does not remove `APPROVED_BRANCH=` or `INTEGRATION_BRANCH=` from the same block. Under a strict reading of the split rule those blocks are still unmatched. The strict reading also proves too much — if every assignment line denied its block, no consumer's lifecycle would ever have run — so the truth is somewhere between, and Sysop does not know where.
- **Quoting.** Whether shell quotes are part of the text a rule is compared against decides both the three `Bash(git commit -m <prefix>:*)` rules and the two reshaped `gh pr list` commands, which carry a `|` inside a single-quoted `--jq` argument. The docs neither define the normalization nor show one rule example containing a quote.

So the accurate claim is that Phase 153 removed the shapes that *provably* defeat a rule, not that every invocation is proven to bind. The last two items are tracked as open checklist entries with one-run human verification recipes rather than guessed at. Read-only `git` probes captured into variables (`MERGE_TARGET="$(git rev-parse --abbrev-ref HEAD)"` and similar) are left alone on purpose: an assignment defeats matching there too, but these are read-only commands for which Sysop ships no rule to defeat. An audit of all 20 such captures confirmed **no write command is captured into a variable anywhere in the skills**.

**Each affected skill runs a Step 0 / Pre-flight permission guard** that re-reads `.claude/settings.json` (and `.claude/settings.local.json`), checks for the rules it needs, and stops with a clean error if any are unsatisfied — except under `defaultMode: "bypassPermissions"`, where the allow-list is inert and the guard reports the drift and proceeds instead of halting a run that provably cannot be denied anything (Phase 152, internal tracker #205). The guard turns the harness's silent halt into a loud, actionable message. See `core/skills/_shared/permission-guard.md` (in the reference impl) for the shared algorithm.

**Skill model routing is delegated to the harness via frontmatter.** Each skill declares `model: opus` (or `model: haiku`) in its YAML frontmatter; Claude Code routes the skill invocation accordingly, per-turn, regardless of the session's default model. Earlier phases (12, 20) shipped a transcript-based "Model Guard" that tried to verify the actually-serving model from the on-disk `.jsonl`, but Phase 21 removed it: the guard could only read past assistant turns (the current turn's `message.model` isn't flushed to disk until after the tool subprocess returns), so a session that ran a `model: haiku` skill (e.g., `/next-task`) immediately before an Opus skill (e.g., `/claim-task`) would false-halt — the bash subprocess saw only the prior Haiku-attributed turns. The harness's frontmatter routing is the source of truth; trust it. If a future Claude Code version regresses on per-skill model routing, the symptom will be observable in skill output quality and a check can be re-introduced then.

The installer's merge behavior: if `<target>/.claude/settings.json` already exists, the Sysop allow-list is **set-unioned** into `permissions.allow` — the user's existing rules are preserved, Sysop rules already present are not duplicated. The user should `git add .claude/settings.json` after install (it's the workflow's contract with the agent harness; keeping it under version control prevents drift).

### 8.2b Updating Sysop in a consumer project

When Sysop itself changes upstream (new convention, fixed skill, new pack content), a consumer project needs a way to absorb the update without losing local edits. The reference installer ships three modes for this.

**Recommended invocation.** From the consumer project root: `bash sysop/scripts/sysop-update.sh`. The shim resolves the consumer root via `git rev-parse --show-toplevel` and the Sysop source via `$SYSOP_SRC` (an env var the consumer sets once in their shell rc — absolute path, no `~`), then exec's `bash "$SYSOP_SRC/install.sh" "<consumer-root>" --update "$@"`. All flags forward verbatim (`--force`, `--packs`, `--dry-run`, `--yes`, `--no-arm-hooks`, `--ref <tag-or-commit>`), and the install.sh exit code propagates. The shim is shipped to `<target>/sysop/scripts/sysop-update.sh` by the bash installer and refreshed on every `--update` run (it is a managed path), so improvements to the wrapper itself flow through the standard update channel.

`$SYSOP_SRC` is per-machine (paths vary across developer setups) and deliberately not recorded in the lock — the lock stays portable across machines. If the env var is unset, missing, or doesn't point at a Sysop git working tree, the shim fails loud with the exact one-liner to fix it; there is no silent fallback to a guessed path. Running from outside a git working tree fails the same way (git's own `fatal: not a git repository …` plus a hint). **Phase 34 / BeanRider ISSUE-0011:** the fresh-install footer (`install.sh` post-pipeline output) now prints the literal `export SYSOP_SRC="<path-to-sysop-source>"` line for the consumer's machine — so contributors landing on a freshly-installed project see the exact line to add to their shell rc instead of inferring it from this paragraph. **Phase 34 / BeanRider ISSUE-0012:** install.sh's three interactive prompts (`prompt_target`, `prompt_packs`, `confirm`) now pre-check `/dev/tty` openability and emit an actionable per-prompt flag suggestion (e.g., `--yes`, `--packs`, positional target) before reaching the read; agents invoking the shim from a tool subprocess no longer hit bash's cryptic `Device not configured` error. **Phase 75:** on a *fresh* install `prompt_packs` additionally scans the target tree for stack signals (`pyproject.toml`/`requirements*.txt`/`*.py` → python; `package.json` naming react/next, `next.config.*`, `*.tsx` → nextjs-react; `alembic.ini`, a compose file naming postgres, a `migrations/*.sql` → postgres; an LLM-SDK dependency → llm; a `*.beancount`/`*.bean` ledger → beancount) and offers the detected *populated* packs as the picker's blank-default. `--packs auto` accepts the detected set non-interactively (agent/CI-friendly, and the automated test seam), and an explicit `--packs ''` forces core only; both skip the picker. Detection is high-precision and advisory — vendored dirs (`node_modules/`, `.venv/`, `venv/`, `.git/`) are pruned, only Postgres-specific markers (not "any `.sql`") pull in the postgres pack, and the human always confirms. `--adopt` is deliberately excluded (it asks which packs were *originally* installed — the current stack is a different question); `--update` continues to take packs from the lock.

**Lower-level invocation** (advanced escape hatch). `bash <path-to-sysop-clone>/install.sh <consumer-root> --update [flags]` is what the shim wraps. Use it directly when you need a Sysop source other than `$SYSOP_SRC` (e.g., a different branch or worktree) without exporting a new value, or when running outside a consumer git working tree. The upgrade-flow steps below describe what `install.sh --update` does — the shim is purely an invocation-friction fix; the safety net is identical.

**Design contract.** The consumer's git repo is the version-control mechanism. The installer doesn't try to preserve inline edits via marker comments or diffs — its job is to ensure a clean snapshot of pre-update state exists in git history before any overwrite, so the consumer can reconcile via normal `git diff` / cherry-pick afterward. Think "vendored dependency": snapshot → bump version → diff → re-apply local deltas.

**`.claude/sysop.lock`.** Installer-managed manifest the consumer commits. JSON, with these top-level keys:

```json
{
  "version": 1,
  "sysop_commit": "<sha of the Sysop source HEAD at install/update time>",
  "packs": ["python", "postgres"],
  "mode": "full",
  "codex_links": true,
  "installed_at": "2026-05-12T22:04:54Z",
  "updated_at": "2026-05-12T22:04:54Z",
  "managed_paths": [".claude/checks.yml", ".claude/convention_map.md", ...]
}
```

`mode` records the install shape (`full` / `loop`) and `codex_links` the Codex-registration choice (§ 8.2d); `--update` re-reads both, so a consumer's prior decision survives a bare `sysop-update.sh` with no retyped flags. A lock predating either field reads as the default (`full` / `true`).

`managed_paths` is the explicit list of every path the installer wrote (workflow docs, `.claude/`, `.agents/skills/`, `sysop/scripts/`, `sysop/scripts/hooks/`, `sysop/scripts/ci/`). It's the contract that future `--update` and `--check` runs honour — files outside this list are user-owned and never touched.

**`bash install.sh <target> --update`** — upgrade flow:

1. Read `<target>/.claude/sysop.lock`. Refuse with a `--adopt` pointer if missing.
2. If `--packs` wasn't supplied, take the pack list from the lock so the merge matches the consumer's prior selection.
3. Identify dirty files in the lock's `managed_paths`. `.claude/settings.json` is excluded — it's merge-preserved (set-union), not overwritten, so a snapshot is unnecessary.
4. If any are dirty: stage them and create a single commit `sysop: pre-update snapshot (was at <old-hash>)` (with `--no-verify` so the user's pre-commit hooks don't block the snapshot). Other dirty paths in the working tree are left alone.
5. **Phase 8 pre-overwrite divergence check** (best-effort): if the lock's `sysop_commit` is reachable in the installer's source repo, materialise Sysop at that commit via `git worktree add --detach` and run the OLD `install.sh` against a throwaway shadow target. For each managed path, diff `git -C <target> show HEAD:<path>` against the reconstructed OLD content. Files that differ are recorded as **committed local edits** and printed in a fenced `⚠ committed local edits in managed paths` block with their `+added / -removed` line counts and a `git show HEAD:<path>` recovery hint. Skipped (with a `note:` line) if the OLD commit is unreachable (shallow clone, force-pushed, or `sysop_commit: "unknown"`).
6. Run the install pipeline — overwriting managed paths freely now that pre-update state is preserved in history and divergence has been surfaced. **Note (Phase 15 / ISSUE-0007):** `--update` deliberately does **not** auto-arm `.git/hooks/`. The pipeline overwrites `sysop/scripts/hooks/*` with upstream skeletons, then leaves the armed copies in `.git/hooks/` untouched so a consumer who customized those hook bodies can reconcile `sysop/scripts/hooks/*` via `git checkout HEAD -- …` before re-arming. Re-arm explicitly with `bash sysop/scripts/install_hooks.sh` after reconciliation. (Fresh installs still auto-arm — the race only exists in `--update`'s reconcile window.)
7. Handle drops: paths in OLD `managed_paths` but not in the NEW pipeline output are removed from the working tree (via `git rm`).
8. Refresh `.claude/sysop.lock` with the new commit hash, bumped `updated_at`, and the new `managed_paths` list. **Phase 148:** both timestamps are anchored to lock *content*, not to the clock — `installed_at` is preserved from the existing lock, and `updated_at` advances only if some other field actually changed. A re-run that resolves to an identical lock rewrites it byte-for-byte, so a no-op re-install or `--update` leaves a clean consumer tree clean instead of producing a lock-only diff.
9. **Phase 8 post-overwrite delta summary**: print a `git diff HEAD --numstat` table for every managed path with non-zero changes. Files with ≥ 5 deleted lines or that appeared in step 5's divergence list are marked `⚠`. Two independent signals catching the same class of issue: committed consumer content overwritten by upstream Sysop changes.
10. **Phase 15 armed-hook divergence check** (always runs, all modes): compare each `sysop/scripts/hooks/<base>` against `.git/hooks/<base>` (the actually-armed copy, untracked by git). Differences mean the armed hook is stale — either `--update` skipped auto-arm and the consumer has not yet re-armed, or `.git/hooks/` was hand-edited out of band. Read-only signal; never modifies hooks. The fix is `bash sysop/scripts/install_hooks.sh` after the consumer settles on the desired `sysop/scripts/hooks/<base>` body.
11. **Do not auto-commit the update.** Leave it uncommitted so the consumer reviews and commits intentionally. The final message points at `git diff <snapshot-hash>..HEAD` for the precise pre-update vs. post-update diff and reminds the consumer to inspect any `⚠`-flagged paths and to re-arm hooks if needed.

`--force` on `--update` skips both the snapshot step (4) AND the pre-overwrite divergence check (5) — "overwrite directly, I know what I'm doing." The post-overwrite delta summary (9) and the armed-hook divergence check (10) always run (read-only).

**Safety-net design choice.** Phase 8 deliberately does NOT implement section-level merge or three-way reconciliation. The contract stays "warn then diff" — Sysop makes content loss loud and unmissable, and the consumer (human or agent driving `--update`) does the re-apply with their own judgment. This came out of BeanRider's first `--adopt` + `--update` cycle (2026-05-12), where Phase 7's "uncommitted dirty state only" snapshot silently overwrote committed local sections in `.claude/convention_map.md` + `.claude/security_map.md`. The pre/post overwrite signals would have caught that loss before the consumer committed.

**Armed-hook safety (Phase 15 / BeanRider ISSUE-0007).** `.git/hooks/` is not tracked by git — `git diff` cannot reveal staleness there. Surfaced during BeanRider's first `sysop-update.sh` run (Phase 14's first real-world absorption), where pre-Phase-15 `install.sh` overwrote `sysop/scripts/hooks/pre-commit` with the upstream skeleton, then armed the skeleton into `.git/hooks/pre-commit` before the consumer reconciled — silently swapping a working bean-check guard for a no-op for the duration of the reconcile window. Phase 15 splits the contract: `--update` copies `sysop/scripts/hooks/*` (so the consumer can reconcile) but does NOT arm; the consumer re-runs `bash sysop/scripts/install_hooks.sh` after reconciling. The always-run armed-hook divergence check (step 10) catches not just the reconcile-window race but any case where `.git/hooks/<base>` falls out of sync with `sysop/scripts/hooks/<base>` — fresh-install hand-edits included. Fresh installs continue to auto-arm (no race window when there is nothing to reconcile). **Phase 24 update (see § 8.2c below):** the `sysop/scripts/hooks/*` *template* bodies themselves are now also preserved when the consumer has modified them since the last absorption — closing the gap where the pipeline used to overwrite a consumer-customized template with the upstream skeleton. The Phase 15 protection still applies (auto-arm is skipped in `--update`); Phase 24b adds the template-body preservation on top.

**`bash install.sh <target> --adopt --packs <list>`** — one-time backfill for consumers that installed before this mechanism existed. Computes `managed_paths` by running the install pipeline in dry-run mode (writes nothing, records destinations), writes the lock, and commits it as `sysop: adopt update tracking (lock anchored at <hash>)`. After `--adopt`, `--update` is available.

For adopted installs, `installed_at` is set to the adopt time — the actual original-install time is no longer recoverable. If you used `--anchor` to record a historical Sysop commit, `installed_at` is still adopt-time; only `sysop_commit` reflects the historical anchor. Downstream consumers reading the lock should treat `installed_at` as "first time this lock existed," not "first time Sysop files landed." Phase 148 makes the code match that reading everywhere: whenever a readable lock is already present — plain re-install, `--update`, or a re-adopt — its `installed_at` is carried forward rather than restarted, so only a lock that did not exist yet gets today's date.

**`bash install.sh <target> --check --source <path-to-sysop-clone>`** — read-only: reads the lock, compares against the source clone's HEAD, and reports `N upstream commit(s) total; M touch installable content` plus a oneliner log of the M relevant commits (scoped to `core/` and `packs/<installed-pack>/` in the source). Writes nothing. Cheap signal for the consumer to decide whether to update. (v1 requires a local clone path; remote URL + caching is a deferred enhancement.)

**`--ref <tag-or-commit>`** (Phase 111) — pin a fresh install or `--update` to a git tag/rev (a reviewed **release**) instead of the source clone's live HEAD. The default track is HEAD (every install/update follows the latest commit); `--ref <tag-or-commit>` copies from that rev's tree instead and records its commit in the lock (so a later `--check` shows how far behind HEAD you are). **`--ref` takes any rev the source clone can resolve — a release tag or a plain commit SHA** — which matters because a tag cut before a structural migration is refused outright (the `sysop/` namespace guard below), so a commit SHA is the pin available when no usable tag exists. Mechanism: there is no ref-establishment step in the copy path — every `install_*` reads `$REPO_ROOT` — so the installer materialises the rev into a temp worktree (the `reconstruct_old_install` pattern) and re-points `$REPO_ROOT` at it for the pipeline; the worktree is removed on exit. The rev must exist in the source clone (release tags: `git -C "$SYSOP_SRC" fetch --tags`); if it can't be resolved, `--ref` fails without writing anything. Rejected with `--adopt`/`--check` (record a rev in an adopt lock with `--anchor`). This is the **bash path's** supply-chain pin — the plugin path can't offer a consumer-side version pin; see the repo's `SECURITY.md` § "How updates reach you — and how to pin". Sticky pinning (a lock field that keeps subsequent updates on a release track) is a possible future enhancement; today `--ref` is per-invocation, which also means an update never silently stays on a stale release.

**Out of scope for this iteration** (deferred until pain emerges):

- Automated re-application of consumer-local edits. The contract is "snapshot then diff" — Phase 8's safety net makes the diff impossible to miss, but the re-apply is still the consumer's job.
- Marker-comment-based section preservation in `convention_map.md` / `security_map.md` / `checks.yml`. Same reasoning.
- Lock-recorded Sysop remote URL + `git fetch` on `--update` to acquire missing OLD commits for the Phase 8 divergence check. Today, if the installer's source repo doesn't have the OLD commit, divergence detection skips and the consumer falls back to the post-overwrite delta signal alone.
- Multi-remote support (cloning + caching a Sysop remote in `~/.cache/`).
- Plugin-install vs bash-install reconciliation.

**`sysop/SYSOP_ISSUES.md` is deliberately outside the lock.** Phase 13 added a friction-log file (relocated under the `sysop/` vendor dir in Phase 128), seeded by the installer on fresh install only. It is **not** recorded in `managed_paths` — that non-management is exactly the property that protects it from `--update`. The friction log is project-owned after the initial seed; `bash install.sh <target>` only writes the file if it does not yet exist, so re-running fresh install never clobbers a consumer's log. Pre/post-overwrite divergence checks (steps 5 + 9 above) ignore it by construction because they iterate over `managed_paths`. The corresponding in-flow capture mechanism lives in `/review-close` Step 7 (Friction Capture), which prompts the agent — append-only, never blocking — to log Sysop friction witnessed during the current cycle. The contract: capture happens at the right moment (while live context still has the silent-deny / shell-escape memory), gets logged in a per-consumer file that survives Sysop updates, and is queryable as a PR backlog by the Sysop maintainer. The **transport half** is the `/report-issues` skill (Phase 71): it renders each `Open`/`Prompt-ready` entry as a GitHub issue, files the ones the human consents to (per-entry) against the Sysop repo, and flips each filed entry to `Status: Filed to Sysop` with a `**Filed:** <url>` back-reference so re-runs never double-file. Capture (Step 7, maintainer-owned repo) and transport (`/report-issues`, external-tester path) are separable: the maintainer who owns both repos reads the file directly; an external tester needs the transport skill to get friction upstream at all. **Wins have their own transport:** Step 7 also captures positive signal (`GOOD-NNNN` entries, marked `[good]` — behavior worth *protecting from a future change*), and `/share-wins` (Phase 107) sends those upstream as **one aggregated comment** on a standing "Wins" Discussion in the Sysop repo — per-entry consent, then a `Status: Shared` flip with a `**Shared:** <url>` back-reference so re-runs never double-post. It is the family's one Discussions poster (a win is "don't regress this," not a tracked issue); the friction and wins transports are otherwise identical siblings.

### 8.2c Consumer-authored project suffix files (Phase 24a)

Phase 24a closes BeanRider ISSUE-0023 (≡ ISSUE-0010 Option 3): the three concat-style managed configs (`.claude/convention_map.md`, `.claude/security_map.md`, `.claude/checks.yml`) regenerate from `core/companion/` + `packs/*/companion/` sources on every install/update — by design, so upstream improvements propagate. To let consumers add project-specific content *alongside* the regenerated body, `install.sh` now checks for sibling `*.project.<ext>` files (per the `SYSOP_PROJECT_SUFFIXES` map) and appends them after concat finishes:

| Concat target | Consumer suffix file | Append shape |
|---|---|---|
| `.claude/convention_map.md` | `.claude/convention_map.project.md` | text-append after a blank-line separator |
| `.claude/security_map.md` | `.claude/security_map.project.md` | text-append after a blank-line separator |
| `.claude/checks.yml` | `.claude/checks.project.yml` | YAML-merge by `checks[*].id`. Common case (no collision) is a header-strip + text-append — preserves comments and formatting in both files. Collision case (Phase 55, BeanRider ISSUE-0042) removes the colliding upstream entries line-wise from the assembled body, then header-strip + text-appends the whole project file — comments in **both** files survive verbatim, including `# OVERRIDE (...):` annotations above overriding entries; the per-id `⚠ id-collision` warn line still fires (consumer wins). Overridden entries take the project-file position (end of the merged file), not the upstream position. If the line-wise removal can't confidently parse the assembled body, the installer falls back to the pre-Phase-55 structural round-trip with a `⚠` note — only in that fallback are comments lost. |

The suffix files are **never written** by the installer, are NOT in `managed_paths`, and are not touched by `--update`'s overwrite or obsolete-file deletion logic. Consumers author them by hand, commit them normally, and the installer reads from the working tree directly. Same protection property as `tasks/index.yml` (Phase 16) and `SYSOP_ISSUES.md` (Phase 13). The append fires whenever the suffix file is present — uncommitted suffix files take effect on the next `--update` (consistent with the rest of `install.sh`, which reads working-tree state).

`.claude/checks.project.yml` **must be a self-contained YAML document** with a top-level `checks:` list (not a `.fragment`-shaped file with a stripped header — pack `*.yml.fragment` files rely on `concat_files`' awk strip, which doesn't apply to consumer suffix files). Malformed YAML is a hard install abort — `yaml.safe_load` raises and the install exits non-zero with the python traceback visible.

**pyyaml dependency.** The id-collision pre-scan and the collision-case merge both need pyyaml. `install.sh` picks the python3 to use via `pick_python_with_yaml()` — tries `<target>/.venv/bin/python3`, then `<target>/venv/bin/python3`, then `python3` on PATH. If none can `import yaml` AND a `.claude/checks.project.yml` exists, the install aborts with an actionable error pointing at `python3 -m venv .venv && .venv/bin/pip install pyyaml`. The markdown suffix files have no pyyaml dependency. Worked example in the Sysop repo's [docs/configuration.md](../../../docs/configuration.md).

#### Phase 25 — placeholder substitution (closes BeanRider ISSUE-0026)

Phase 24a's append/merge shape closes the "add a new section" and "replace one check entirely" cases but not the "concretize this placeholder token inside an upstream check" case. Pack `checks.yml.fragment` files ship `paths:` lists with placeholder tokens (`<api module>/`, `<scripts dir>/`, `<datajobs dir>/`, `<data seed dir>/`, `<tests dir>/`, `<frontend>/`, `<components dir>/`, `<hooks dir>/`, etc.) that name the project layout abstractly so the pack stays framework-agnostic. Without substitution, `run_checks_impl.py` silently returns empty for any check whose `paths:` entries don't resolve on disk — the consumer's `.claude/checks.yml` reports `0 finding(s)` clean by accident, not by validation.

Phase 25 lets the consumer author one file mapping each token to its concrete project path:

| File | Format | Effect |
|---|---|---|
| `.claude/substitutions.project.yml` | YAML with top-level `substitutions:` mapping of `"<token>": "value"` pairs | Text-substituted into `paths:` values of `.claude/checks.yml` only (Phase 55, BeanRider ISSUE-0041 — both the inline `paths: [...]` form and block-form `paths:` items), AFTER concat finishes and BEFORE the `*.project.<ext>` suffix file is appended/merged. The markdown maps (`.claude/convention_map.md`, `.claude/security_map.md`) are **never** substituted — their placeholder tokens are accurate documentation of upstream's module-shape vocabulary, and substituting them garbled section headers (`## __disabled_no_op__/*.py — Auth`) |

The substitution mechanism deliberately operates only on **upstream-shipped** placeholder text — consumer suffix file content (`.claude/checks.project.yml` etc.) is taken byte-faithfully, so the consumer can write literal `<api module>` strings in their suffix (e.g., as documentation about the placeholder vocabulary) without auto-substitution. Substitution is **literal string replacement**, not regex — a key like `<api module>` matches that exact sequence; nothing fancier.

The substitutions file is **never written** by the installer, is NOT in `managed_paths`, and is not touched by `--update`'s overwrite or obsolete-file deletion logic. Same protection property as `tasks/index.yml` (Phase 16), `SYSOP_ISSUES.md` (Phase 13), and the Phase 24a suffix files. Author it by hand, commit it normally; the installer reads it from the working tree directly.

**Stale-token report.** After a real-run pipeline finishes, the installer reports any keys in `.claude/substitutions.project.yml` that did NOT match any `paths:` value in the regenerated `.claude/checks.yml` — likely typos (`<api modules>` for `<api module>`), stale entries from a layout change, or (post-Phase 55) keys that only ever matched markdown prose. Same surfacing pattern as Phase 24b's "stale `--accept-upstream` entries" block. Real-run only (the substitution itself is gated behind `concat_files`' dry-run short-circuit, so a dry-run report would be a false-positive "all stale"). The output appears before the agent commits the absorption, so the catch is timely. Fix is either remove the stale keys or correct the typos; the report includes a `grep -E '^\s*paths:' .claude/checks.yml | grep -oE '<[a-z][a-z _-]+>' | sort -u` hint for comparing against tokens actually present in upstream `paths:` values.

**pyyaml dependency.** Any non-empty substitutions file requires pyyaml (parsed via the same `pick_python_with_yaml()` helper Phase 24a uses for `checks.project.yml`). If pyyaml is missing AND the file exists, the install aborts with the same actionable error pointing at `python3 -m venv .venv && .venv/bin/pip install pyyaml`. Malformed YAML is a hard abort (python traceback + a Sysop follow-up line naming the file).

**What's in scope.** Substitution applies to `paths:` values in `.claude/checks.yml` only (narrowed from "the three concat-style configs" by Phase 55 / BeanRider ISSUE-0041 — the substitution's purpose is routing checks at real or sentinel directories, a `paths:` concern; everywhere else the tokens are documentation). The markdown maps, skills (`.claude/skills/*`), workflow docs (`WORKFLOW.md`, `WORKFLOW_GUIDE.md`), semgrep rules, and scripts are explicitly out of scope — those files' placeholder vocabulary is deliberately abstract (it stays portable across consumers and across packs); substituting in skill prose would silently fork the prompts per consumer, exactly the anti-pattern Phase 24b's scope filter is built to avoid for code-shaped managed paths. The substitution is line-scoped text replacement, not a YAML round-trip, so comments in the assembled `checks.yml` body survive (same comment-preservation posture as the Phase 55 collision merge).

**Worked example** — author `.claude/substitutions.project.yml`:

```yaml
substitutions:
  "<api module>": "parsers"
  "<scripts dir>": "scripts"
  "<datajobs dir>": "streamlit_app"
  "<data seed dir>": "data"
  "<tests dir>": "tests"
```

After `bash sysop/scripts/sysop-update.sh`, every `paths: ["<api module>/", "<scripts dir>/", "<datajobs dir>/"]` in the upstream `.claude/checks.yml` becomes `paths: ["parsers/", "sysop/scripts/", "streamlit_app/"]`. Checks now fire against real directories.

### 8.2c (continued) — Phase 24b: ancestor-aware preservation of consumer-modified sysop/scripts/* and sysop/scripts/hooks/*

Phase 24b closes BeanRider ISSUE-0024 (⊂ ISSUE-0005 Option 2) and ISSUE-0025. The append-point pattern from Phase 24a is the right shape for *configuration*, but not for *code* — you can't add `errors="replace"` to a Python `open()` call from a sibling file, and you can't add a `bean-check` invocation to a hook from outside the hook body. For managed scripts and hook templates where the consumer hardens the Sysop body itself over time, Phase 24b extends Phase 8's ancestor-comparison machinery from "warn about divergence" to "warn AND skip overwrite":

- The shadow worktree Phase 8 already builds via `reconstruct_old_install()` is hoisted to a module-scope `DIVERGENCE_SHADOW` global with `trap` cleanup, so it outlives the install pipeline (Phase 8's lifecycle disposed it before `run_install_pipeline`).
- `copy_file()` gains a scope-and-ancestor check. For in-scope paths whose target differs from the reconstructed ancestor, it skips the overwrite, records the path in `PRESERVED_PATHS`, and emits a `⚠ preserved: <relpath> (consumer-modified since <old_commit>)` log line. Preserved paths are still recorded in `MANAGED_PATHS` so the lock stays accurate.
- **Scope is intentionally narrow:** `sysop/scripts/*` (depth-1) and `sysop/scripts/hooks/*` (depth-2) only. Skills (`.claude/skills/*`), workflow docs (`sysop/docs/WORKFLOW.md`, `sysop/docs/WORKFLOW_GUIDE.md`), everything the installer writes under `.claude/semgrep/` — the authoring `README.md`, the pack rule files, and `fixtures/*` — tasks-scaffold templates (`tasks/schema.md`, `tasks/README.md`), and concat files are explicitly out of scope and take the standard overwrite. **Out of scope means "not preserved when the installer writes it", not "overwritten whatever it is":** a file the installer never ships — a consumer's own `.claude/semgrep/my-rule.yaml`, say — is not written at all, so it survives by never being a target. The two statements are about different files, and § 3.5's promotion-write-target block — *"the installer never overwrites an unshipped semgrep filename"* — is the other half of the same contract, not a contradiction of this one. Rationale: a silent prompt-fork channel for skills would accumulate divergence from upstream improvements indefinitely with no upstream pressure to reconcile — exactly the anti-pattern Sysop's marketplace channel is built to avoid. Project-specific guidance for those classes belongs in CLAUDE.md sections (prose) or pack-level extensions (code-shaped), not silent forks. Concat files are exempt because Phase 24a's suffix-file mechanism is the right shape for them — if both fired, the overwrite-skip would freeze the file at its last consumer state and silently drop upstream improvements.
- **Fail-closed on shadow-reconstruction failure.** If `reconstruct_old_install` fails (commit unreachable, OLD installer pre-dates the bash channel, network), `--update` non-`--force` **aborts** with a multi-line error naming the three escape hatches: `git fetch` to retry, `--accept-upstream <path>` per file you're willing to overwrite, or `--force` to skip preservation entirely. Stricter than Phase 8's warn-and-proceed posture — silent loss of customizations the consumer thought were safe was the failure mode that motivated ISSUE-0024/0025 in the first place.
- **`--dry-run` runs the divergence detection.** Phase 8's `--dry-run` short-circuit was lifted because the shadow-build is read-only (operates on a temp dir) and the only true write — the snapshot commit in `snapshot_managed_paths` — is already DRY_RUN-guarded. The plan output then includes the preserved-paths block so the agent can see preservation decisions before committing to the absorption.

**`--accept-upstream <relpath>` and `--accept-upstream-list <file>` flags** (both repeatable; forward through `sysop-update.sh`'s `"$@"` pass-through) explicitly override preservation per file. The list-file form ignores `#`-prefixed and blank lines. After the pipeline finishes, any path passed via these flags that did NOT match a preserved path surfaces as `note: accept-upstream: <relpath> not in preserved set; ignored` so stale list-file entries don't quietly accumulate.

**Two-pass workflow.** The realistic absorption is two-pass because the agent needs to see the preserved-paths summary before deciding which to accept-upstream:

1. **First run:** `bash sysop/scripts/sysop-update.sh` (or `... --dry-run` for a plan-only pass). Output reports preserved paths and `preserved: N managed path(s) preserved due to consumer modification`.
2. **Agent inspects** each preserved path's pending Sysop-side change against the consumer-side current content: `git -C "$SYSOP_SRC" log --oneline -p "<old_commit>..HEAD" -- core/companion/scripts/<file>` and `git -C "$TARGET" log --oneline -p -- sysop/scripts/<file>`. Decides per-file: take upstream, keep consumer, or merge by hand.
3. **Second run** (only if any preservation should be overridden): `bash sysop/scripts/sysop-update.sh --accept-upstream-list /tmp/accept.txt` (one path per line) — or `--accept-upstream <path>` flags for small sets.
4. **Commit the absorption.** The accepted paths carry upstream content; the still-preserved paths are unchanged from step 1.

**Reporting.** `report_post_overwrite_deltas` (the function that emits the post-overwrite `numstat` table from Phase 8) gains two preceding blocks: a "preserved managed paths (Phase 24b)" block listing every path in `PRESERVED_PATHS` with the override hint, and a "stale --accept-upstream entries (Phase 24b)" block listing any accept-upstream paths the pipeline didn't actually apply. The existing numstat table then runs unchanged for paths that DID overwrite. `numstat` won't see preserved paths (their working tree didn't change), so the dedicated block is the only signal for them.

**Phase 7 snapshot interaction.** For preserved paths, the Phase 7 pre-update snapshot commit becomes a no-op (working tree wasn't touched, so the snapshot diff is empty). Acceptable — the snapshot is still useful for out-of-scope paths (e.g., an uncommitted edit to a skill body the consumer wanted to capture before `--update` overwrites it).

**Boundary: `.claude/settings.json` is not affected by 24b.** It's not routed through `copy_file()` — `install_permissions()` runs Phase 6's set-union JSON merge instead. The existing Phase 8 exclusion at `detect_committed_divergence` is unchanged.

### 8.2d Codex-native skill registration (`.agents/skills/`, Phase 142)

The two review skills are exposed to the Codex CLI by relative symlink, in both install modes:

```
.agents/skills/codebase-review -> ../../.claude/skills/codebase-review
.agents/skills/security-audit  -> ../../.claude/skills/security-audit
```

Links, not copies — one source of truth per skill, so a skill-body update flows through the link with no second file to drift. Only these two skills are exposed; the rest of the installed set stays unlinked under `.claude/skills/`.

**Evidence boundary.** Ordinary-request selection under Codex was measured against a **loop-mode** install. Full mode links the same two directories at the same paths, and only linked directories register, so the registered set is expected to be identical — *derived from the documented scan rule, not measured*. The end-to-end acceptance run (a fresh Codex session against a shipped install) is a separate gate from the installer's own tests.

**A link's identity is its raw target string, never the bytes it resolves to.** Every ownership decision (create, leave alone, sweep, refuse) compares `readlink` output against the expected relative target. A link the consumer repointed is consumer data even if it happens to resolve to the same skill.

**Collision is a hard error, before any target mutation.** A pre-existing entry at either path that isn't exactly Sysop's link stops the install (or `--update`) before the pre-update snapshot, the namespace migration, and the pipeline — so a refused run leaves the tree byte-identical. The check covers the parent components too (`.agents` present as a file, or a parent Sysop can't write into): left to the creation step, those surface as a bare `mkdir`/`ln` failure that `set -e` turns into a mid-pipeline abort — a half-applied target with a stale lock. The reasoning is the same silent-divergence argument as § 2's promotion discipline: a consumer-owned `.agents/skills/codebase-review` would capture ordinary Codex requests while the install reported success. The consumer acknowledges (move it aside, or `--no-codex-links`) rather than discovers.

**Capability probe, after the confirm and before creating anything.** The installer probes the *target's* filesystem with a throwaway relative symlink (target-local, so it tests the consumer's mount rather than `/tmp`). It is the one part of this preflight that writes, so it runs after the plan is confirmed — a declined run must not have touched the repo. Failure disables link **creation** for that run, warns loudly, and lets the install proceed — a default-on convenience must not brick an install on a filesystem that can't symlink. Links that already exist and are still ours are unaffected by a probe failure: they stay recorded and managed, so a transient failure mid-`--update` can never feed a consumer's working links to the obsolete-path sweep. The probe never runs under `--dry-run` (which promises no writes).

**Opt-out is recorded, not per-run.** `--no-codex-links` writes `codex_links: false` to the lock; `--update` re-reads it like `mode` and `packs`, so the documented one-line update honours it forever. Opting out on a tree that has the links removes them: under `--update` via the normal obsolete-path sweep, and on a plain re-install (which never reaches the sweep) via the install step itself — otherwise the links would sit on disk dropped from `managed_paths` yet still registering, which is the opposite of what was asked. Both removals are guarded by raw target, so an entry that is no longer Sysop's exact link is left in place — the `--update` sweep reports it (`⚠ keep:`); the plain re-install path skips it silently.

Because a managed link can be *broken* (its target retired upstream), the sweep's on-disk resolution tests `-e || -L`; a broken link that is still ours is swept, a broken link that isn't is spared. The guard defaults to **deny** for everything else under `.agents/` — a lock entry naming a path *through* one of our links would otherwise be resolved by `-e` (which follows symlinks) and removed by `rm -f`, deleting the real skill body out of `.claude/skills/`. Only a corrupt or hand-edited lock produces such an entry, which is precisely what the sweep's sibling consumer-path guard exists for.

**Uninstall is manual** (§ "Backing out" in `docs/install-and-update.md`): remove the two entries only after checking `-L` plus the expected raw target, never recursively remove `.agents/` or `.agents/skills/`, and leave emptied parent dirs alone — they may not be Sysop's.

No `AGENTS.md` block is emitted, by default or otherwise. Prose routes but does not register, competes for the project-instruction budget, and is shadowed by a consumer `AGENTS.override.md`; the manual recipe is documented for consumers whose filesystem failed the probe, and it is theirs to maintain.

### 8.3 Skills (agent execution, one file per phase)

Each skill maps to a lifecycle phase in § 2. Skills are the step-by-step execution files. In the reference implementation they are Claude Code slash-commands; port their content into whatever mechanism your agent uses (or into a human runbook).

| Skill | Phase | Role |
|-------|-------|------|
| `/next-task` | § 2.1 | Find single next claimable task |
| `/claim-task` | § 2.2, 2.3 | Claim, worktree, then orchestrate: planner → independent reviewer → orchestrator classification → optional human gate → executor (implement + post-fix gates) |
| `/auto-build` | § 2.4b | Parallel-batch orchestration: pick N independent tasks (optionally restricted to an explicit task-ID subset) under K=12 complexity ceiling, sequentially pre-claim, then per-task plan-only → adversarial-reviewer → execution Opus agents (orchestrator-driven, no recursive Agent spawns). Human stays the merge gate via `/review-close` |
| `/plan-review` | § 2.2 | Adversarial review for ad-hoc plans not created by `/claim-task` |
| `/document-work` | § 2.4 | Simplify pass (mandatory, Step 1b), UI re-verify, commit, deferred docs, push (skipped under `--non-interactive`) |
| `/codebase-review` | § 2.5 | Scoped code-quality review + convention candidate extraction |
| `/security-audit` | § 2.6 | OWASP-categorized security review + candidate extraction |
| `/auto-fix` | § 2.7 | Mechanical auto-fix with sibling scan + Opus verification pass |
| `/auto-judge` | § 2.7b | Opus handling of flagged batches |
| `/review-close` | § 2.8 | Adversarial review, merge, consolidate docs, cleanup |

**Shared partials** live under `.claude/skills/_shared/` and are referenced by prose citation from the caller skills (no `Read`-directive convention — readers can scan the calling skill end-to-end without opening the partial, while the canonical text lives in exactly one place — the lone exception being a short assert one-liner such as `main-push-guard.md` Rule A, inlined at its call sites for scan-ability while the canonical *rules* and rationale stay in the partial). Eleven partials are present:

- `permission-guard.md` — pre-flight check that re-reads `.claude/settings.json` + `.claude/settings.local.json` and stops with an actionable error if required allow-rules are unsatisfied (skip-with-drift-report under `bypassPermissions`; a broader allow-rule that already covers a required one counts as satisfied). Consumed by 15 skills via prose citation of `_shared/permission-guard.md` § Algorithm step 5. The other eight do not run the guard, and none of those is an oversight — but they are not all the same case, which is worth stating because "it doesn't guard" and "it doesn't shell out" are not the same claim. `/daily-summary` and `/test-audit` genuinely stay inside the read-only auto-approved set and say so ("no Step 0 guard"); `/onboard` records the narrower claim that it needs no *new* rules, relying on ones shipped for other skills; and `/roadmap` does shell out to two `python3` scripts under `--in-flight` and **deliberately declines the hard stop**, degrading to a one-line "overlay skipped" note instead, because a missing read-only overlay should never halt a read-only skill.
- `ui-verify.md` — browser-driven verification procedure for frontend changes. Consumed by the `/claim-task` Step 7e executor and `/document-work` Step 1c (and indirectly by `/auto-build`'s Phase 6e execution agent) via prose citation of `.claude/skills/_shared/ui-verify.md`.
- `adversarial-review.md` — canonical adversarial-review prompt template + `fixable`/`blocker` classification rubric, plus a section (Phase 171) recording that the collapsed self-classifying "reviewer-executor" variant is **retired** — `/claim-task` now splits planner, independent reviewer and executor with the orchestrator classifying between them — and what carried over from it (the sealed REVIEW_REPORT block, now the verdict's transport via the SubagentStop hook; the BLOCKER_QUESTION / PARKED_REASON split), and **§ *Running more than one reviewer*** (Phase 154) — the procedure for a round rather than a single pass: commit before it starts, independent fresh-context `general-purpose` agents (**never forks**, which share a blind spot and ratify each other), a distinct lens each, reviewers forbidden from mutating the working tree (compare via `git show <sha>:<path>`), and the two adjudication rules that outrank agreement — *never weight findings by how many reviewers agree*, and *a confirmed premise is not a confirmed conclusion* — plus **§ *How many reviewers, how many rounds — the governor*** (Phase 174), the ratified sizing for an ad-hoc round over built work: two lenses default, a third when the change ships behaviour *and* a record making numeric claims, one round default with a stated second-round condition (each condition licenses its own step; past them — a third lens without the condition, a fourth lens, a third round — it is the maintainer's call, made outside the session that wants it), and the latent-finding disposition tier (verified-real but no live path → filed with a revisit trigger, never fuel for a further round; per-plan orchestrator reviewers and skill-sized fan-outs are out of the governor's scope by its own § Scope). Consumed by `/claim-task` Step 7, `/plan-review` Step 3, and `/auto-build` Phase 6b (orchestrator-spawned reviewer) via prose citation; the harness-constraint section documents the no-recursive-Agent-spawn rule that forces orchestrator-run reviews to happen at the orchestrator's own top layer.
- `decomposition-rubric.md` — calibrated task-decomposition rubric (Phase 60b), derived from cross-queue-surviving exemplars. Consumed by `/intake` Step 6 via prose citation as the four-test sizing gist (atomic? sized? ordered? blocked?).
- `main-push-guard.md` — branch-assert + safe-push rules (Phase 64) closing the HEAD-hijack and remote-autonomous-writer races for any commit/push to `main` or an integration branch from the shared primary worktree. Rule A (assert the branch before every commit/push) consumed by `/review-close` Step 4, `/claim-task` Step 4d, `/auto-build` Step 5.4, and — inverted — `/document-work` Step 5; Rule B (safe direct push, `direct` merge policy only) by `/review-close` Step 4d; Rule C (never force-push `main`/integration branch) throughout.
- `guided-mode.md` — decision-gate protocol for guided (teaching) mode (Phase 76): at each human decision point, state the choice plainly, adversarially review the recommendation, and triage it (own it / collapse a false choice / default an un-weighable one), with the load-bearing "allowed to conclude *this isn't your call*" rule. **Inert until a consumer opts in** via a `## Guided mode` activation stanza in CLAUDE.md (§ 6.1). Unlike the other partials it is not yet cited from inside the skills — the thin slice activates it via always-loaded CLAUDE.md prose; per-skill citation is the deferred build.
- `promotion-write-target.md` — canonical rule (Phase 78) for **where** convention promotion (`/codebase-review` + `/security-audit` Step 9) and demotion (Step 9b) writes land: in a consumer install (`.claude/sysop.lock` present) the base maps are regenerated on every `sysop-update.sh`, so promoted content is dual-written to the never-managed `.project.*` overlay to survive; in the source repo (no lock) the base writes stand alone. Consumed by both review skills' Step 9 / 9b and the Step 2a map-coverage commit via prose citation. See § 3.5.
- `test-assessment-rubric.md` — calibrated rubric (Phase 80) for the two standing test-quality questions: where load-bearing surfaces lack tests (Tier 1) and which existing tests are provably-dead (Tier 2a) or judgment-retireable (Tier 2b, confidence-labeled). Consumed by `/test-audit` as its whole judgment layer, and cited by `/codebase-review`'s "Test Coverage Gaps" dimension so the in-diff and standing test-worth judgments share one home. Ships **provisional** — only the Tier-2b dimensions calibrate over runs; Tier 1 + 2a fire on the first run. See § 6.5 (the coverage gate it complements).
- `upstream-repo.md` — target-repo resolution + disclosure protocol for the three give-back skills (`/report-issues`, `/contribute-convention`, `/share-wins`), Phase 147. Resolves the upstream target (`--repo` › `<project>/CLAUDE.md § Sysop upstream repo` › the shipped public default `getsysop/sysop`), stopping rather than falling back when a configured section is malformed or its heading is a near-miss; probes the resolved target's visibility (`gh repo view --json visibility`, advisory and non-fatal) with an offline fallback that never assumes private; and defines the pre-consent sensitivity nudge. Like every partial here it is prose an agent follows, not enforcement.
- `plan-review-preference.md` — resolves how much the human is in the loop on a claim, read by `/claim-task` Step 6 before any agent spawns. Resolution order is `--review-plan` / `--no-review-plan` › `<project>/CLAUDE.md § Plan review` (`always` / `never` / `ask`) › an `AskUserQuestion` fallback, the same "consumer declares its shape" pattern as `§ Merge policy`. Two options — **A** gates on the human between review and implementation, **B** runs unattended — and the adversarial reviewer runs on **both**; only the gate differs. Guided mode pins it to A by overriding the config tier, never the per-run flag. Handles the `askUserQuestionTimeout` interaction: an auto-closed question submits any option the human had already highlighted, so the answer can look entirely ordinary — but the harness also tells Claude the human may be away, and that signal is what the rule keys on (semantically, never on a literal sentence, since the exact wording is not part of the documented interface). Such a result is a **park, never a decision**. Because that is prose an agent follows rather than a lock, the file also names the durable fix: a consumer who sets `askUserQuestionTimeout` should set `§ Plan review`, which removes the question entirely. Lifecycle-only; loop mode does not ship it.
- `fanout-evidence.md` — fan-out evidence & finding-provenance contract (Phase 138). **Tier 1** (universal): every finding carries a `[verified]` / `[reported]` provenance marker — a self-declared honesty label, not a machine-checked guarantee. **Tier 2** (fan-out only): the sub-agent evidence footer (files-opened-vs-assigned + tool mix) plus orchestrator merge discipline — a hollow batch is flagged loudly, an un-re-read fan-out finding defaults to `[reported]` (only the orchestrator's sample re-read upgrades it), and the round summary carries a provenance class, never a bare coverage %. **§ Adjudication** (universal, Phase 141): what evidence a *judgement* requires — a falsified premise refutes outright; beyond that, kill/downgrade only on a mitigation located and read at a `file:line`, keep/escalate only on a traced path, and when neither can be established the finding survives with the gap recorded (a filed task gets another reader; a dismissal gets none). Consumed by `/codebase-review` (Step 3 dispatch + Step 3c merge + Step 4 dedup) and `/security-audit` (Step 3 dispatch + Step 3b merge + Step 4 dedup) via prose citation; `/test-audit` cites the Tier-1 marker and § Adjudication always, the Tier-2 contract only if it fans out.

### 8.4 Scripts (`sysop/scripts/`)

| Script | Purpose |
|--------|---------|
| `claim_task.sh <TASK_ID> <BRANCH>` | Create isolated worktree, branch, optional lock |
| `claim_task.sh --release <TASK_ID>` | Un-claim: remove the worktree, flip `status: in_progress → open` (PyYAML round-trip), release the lock. `--delete-branch` / `--force` opt-ins |
| `batch_work.sh [--force] <N>` | Claim a review batch (worktree + branch + status flip + `sysop/runtime/locks/BATCH-<N>.lock`). Accepts `BATCH-<N>` as well as `<N>`. **Decides on the batch's status before writing anything:** `Pending` claims, `In Progress` resumes (announcing the existing lock), `Review Ready` and the finished three (`Complete` / `Merged` / `Ready for Review`) are refused and need `--force` — that flag is how follow-up work on a finished batch is still reached — and a status outside the vocabulary is refused outright, because nothing can tell whether it is claimable. Flags go before the number; a trailing one is rejected rather than ignored. The lock write is idempotent — an existing lock is reported and left alone, never an error, because the script is re-runnable by design and `/auto-fix` / `/auto-judge` call it in a loop over `Pending` batches. The status flip is best-effort (skipped off `main`, on a dirty `review_tasks.md`, or on a failed pull); the lock is not, so an in-flight batch is detectable even when its status still reads `Pending` |
| `batch_work.sh --release [--force] <N>` | Un-claim a batch: remove the worktree, revert `In Progress` → `Pending` and `[/]` → `[ ]`, commit on `main`, release the lock. Refuses to run outside the main checkout (a worktree carries its branch's own `review_tasks.md`), refuses a `Complete`/`Merged` batch, and refuses one holding `[x]` tasks without `--force`. On an already-`Pending` batch it clears the lock only — which is the stranded-batch recovery, since `next_task.py` skips a locked batch whatever its status says |
| `close_batch.sh <N> [<N2> ...]` | Flip merged batches to `Merged`, check boxes, update stats, and release each closed batch's `BATCH-<N>.lock`. A task annotated `> Failed:` anywhere in its own block — the task line plus the indented lines under it — keeps its checkbox and is excluded from the batch's closed count (and so from the Grand Total) — a FAIL verdict means the work was attempted and not finished, so closing it would overstate what the round resolved; the batch still becomes `Merged`. Accepts `BATCH-<N>` and zero-padded forms. The release fires **only when the close committed to `main` in the main checkout** — under `pr` policy Step 4b runs on the integration branch, where stripping the lock would let `/next-task` re-offer a batch whose work is sitting on an unmerged PR; off main it defers loudly and names the recovery. A batch that is already finished (`Merged` / `Complete` / `Ready for Review`) sheds its lock whether or not this run closed anything — otherwise a follow-up re-claim writes a lock every other path refuses to remove |
| `install_hooks.sh` | Copy `sysop/scripts/hooks/*` into git's hooks dir (not needed per worktree — they share one; required after `--update` reconciliation per Phase 15 / ISSUE-0007 — `install.sh --update` no longer auto-arms; skips when `core.hooksPath` is set) |
| `cleanup_worktrees.sh [--clean \| --force]` | List or bulk-reclaim worktrees. Bare = list with a MAIN/MERGED/ACTIVE/STALE classification (not read-only: every mode, this one included, runs `git worktree prune`); `--clean` removes MERGED + STALE and **skips ACTIVE**; `--force` removes **ALL non-main worktrees, ACTIVE included** — uncommitted work is destroyed. Both removing modes also delete the removed worktree's branch with the safe `git branch -d`, so an unmerged branch survives. **ACTIVE is the classifier's fallthrough**, i.e. "not MAIN, not STALE, not merged into main" — it means *may* hold uncommitted work, not *does*: a pristine worktree on an unmerged branch is ACTIVE too. **Takes no path operand and has no lock handling:** every mode acts on the whole worktree set, so it is never the way to drop one orphan, and a worktree it removes leaves its `sysop/runtime/locks/<ID>.lock` behind. For one worktree use `git worktree remove <path>` (which refuses on uncommitted or untracked changes), or `claim_task.sh --release <TASK_ID>` / `batch_work.sh --release <N>` when a lock and a status also need releasing. A path operand is rejected rather than ignored (Phase 165 — three skill sites had prescribed `--force` as a single-target rollback, so one failed claim would have destroyed every concurrent claim's uncommitted work) |
| `self_check.sh` | Phase 133 one-command post-install health check. Reports install lock + mode, bash version, an `import yaml`-capable `python3` (probed in `run_checks.sh`'s order, which is the point — the **main** checkout's `.venv` then `venv`, then *this* checkout's, then `PATH`; a worktree carries no venv, so anchoring on the current root would answer about the wrong tree), armed git hooks, optional scanners, and Phase 143 review-round evidence (stale pending markers / asymmetric round history). Exits non-zero only on a hard prereq (lock / bash / PyYAML) or a demonstrably-abandoned round; hooks and scanners are reported but never fatal (loop-mode consumers may run checks in CI only). Ships in both modes; wired into the install footer + the quickstart docs. |
| `archive_review_tasks.py` | Archive merged rounds from `review_tasks.md` → `_archive.md` |
| `review_index.py` | Regenerate `.claude/review_index.json` from markdown |
| `validate_tasks.py` | Task-schema validator — enforces every invariant in `tasks/schema.md` against `tasks/index.yml` + the per-task bodies (13 invariants; 12 and 13 are warn-only, see the task-system row in § 8.1). Runs on demand; runs from pre-commit only once you wire it in — the shipped skeleton does not call it (copy the block from `git-hooks/examples/pre-commit-tasks-validate.example` in the Sysop source repo); and runs from the migration path via `--path`. `--quiet` is pre-commit mode, `--self-test` an internal consistency check. Exits non-zero on any ERROR — warnings (suspected secrets) never affect the exit code. Self-bootstraps PyYAML onto `sys.path` (Phase 126, widened Phase 182) so a bare `python3` serves every consumer: it walks this file's ancestors, then the **main** checkout via git-common-dir, then the CWD, trying both `.venv/` and `venv/` at each — and **commits a candidate only once `import yaml` actually succeeds from it**, rolling back otherwise, so one empty venv cannot end the search. The same block is inline in `sitrep_survey.py`, `next_task.py`, `backfill_completed_dates.py` and (non-fatally) `scope_overlap.py`; `tests/test_venv_pyyaml_bootstrap.py` pins the five copies identical, since it must run before any import can be trusted and so cannot be shared. |
| `next_task.py` | Phase 45a deterministic `/next-task` resolver — replaces what was an LLM call with a ~100 ms, zero-cost read of `tasks/index.yml` + `review_tasks.md` + `sysop/runtime/locks/`, printing the same user-facing markdown. Candidate ordering is unblocker-first (`unlock_count desc, effort asc, id`; Phase 74). `--review` restricts to pending review batches; `--avoid-inflight` (Phase 103) layers the two-tier collision key over `scope_overlap.py`. Exit 1 on an invariant violation (schema version, `current_focus`, body-path escape), 2 on an unexpected exception. |
| `sitrep_survey.py` | Read-only survey behind `/sitrep` — walks locks, worktrees, branches, `tasks/index.yml`, and `review_tasks.md`, classifies each active task into a deterministic lifecycle state via the `Doc-Work:` git trailer (Phase 40), flags discrepancies between filesystem reality and the state files, and emits a scannable text report (`--json` reserved; `--stale-days N`). Never mutates state — read-only by design, and `/sitrep` carries a matching `disallowed-tools` guard (Phase 54). |
| `run_checks.sh` | Thin wrapper; invokes `run_checks_impl.py` with PATH bootstrap |
| `run_checks_impl.py` | Parses `checks.yml`; runs all six stages (grep, LSP, Semgrep, ESLint, pip-audit, coverage — § 2.5 step 4); baseline matching |
| `scope_overlap.py <TASK_ID>` | Phase 102 collision-aware-claiming primitive. Infers a candidate task's likely scope (`## Key files` + `blast_radius`, a pre-plan guess) and compares it against each in-flight worktree's **actual** changed set (`git diff --name-only main...HEAD` + uncommitted → lock `files_impacted:` → body fallback), emitting a per-in-flight `likely`/`possible`/`none` verdict (text or `--json`). **Advisory, non-blocking** — exits 0 on every degrade path (no in-flight work, missing index, absent PyYAML, unreadable worktree) so it can never break the claim flow. Consumed by `/claim-task` Step 2 (Leg A advisory), `/auto-build` Step 1 (Leg B — soft de-prioritize + Step 4 annotation, Phase 103), `/next-task --avoid-inflight` (opt-in collision ranking, Phase 103), and `/roadmap --in-flight` (portfolio-level candidate + `Run it:` annotation, Phase 103). |
| `ingest_security_report.py` | Phase 144 `claude-security` report ingest — the read-and-normalize boundary behind `/security-audit` Step 3c. Reads a plugin scan report off disk (Sysop cannot *launch* the plugin: its multi-agent scan needs the `Workflow` tool, which is stripped from every sub-agent) and emits **sanitized, provenance-tagged** findings as JSON on stdout for the skill to file as `[reported]` tasks — the skill never hand-copies from the raw report, which is untrusted input. Parses tolerantly with trust keyed off the plugin's stable contract, and surfaces a truncated scan loudly: `verified` certifies the plugin's per-finding panel completion, **not** repo coverage. Best-effort — a denial or error prints one line and never blocks the round. |
| `sysop-update.sh` | Project-root shim around `install.sh --update`. Resolves the consumer root via `git rev-parse --show-toplevel` and the Sysop source via `$SYSOP_SRC`; fails loud if either is unresolvable. Forwards all flags. See § 8.2b. |
| `permission_denied_hook.py` | Phase 36 `PermissionDenied` hook (Claude Code 2.1.89+). Reads denial input on stdin, matches three classifier-override patterns (`git push origin main`, `git push origin --delete <branch>`, `git commit` on protected branch), and emits `additionalContext` with the exact `!`-shell-escape command for the model to relay to the user. Not directly invoked by skills — wired in via `settings.json::hooks.PermissionDenied`. See § 8.2a. |
| `parse_subagent_envelope.py` | Phase 37 `SubagentStop` hook (Claude Code 2.1.47+ primary path; 2.0.42+ transcript-fallback path, Phase 54). Reads hook input on stdin (`last_assistant_message`, `agent_id`, `session_id`, `agent_transcript_path`), parses the YAML envelope `/claim-task`'s planner / reviewer / executor and `/auto-build` execution agents emit, and writes structured JSON to `sysop/runtime/subagent-envelopes/<TASK_ID>[.<phase>].json` (the `.<phase>` infix only when the envelope carries a `PHASE:` field — Phase 159a) (or `_unparseable_<session>_<agent>.json` on parse miss). Parent skills prefer the JSON file with regex-parse-the-return-text fallback; `/auto-build` Phase 7's filesystem envelope-recovery stays as the deepest fallback. Not directly invoked by skills — wired in via `settings.json::hooks.SubagentStop`. See § 8.2a. |
| `resolve_skill_models.py` | Phase 69 model-role resolver. Skills pin a ROLE (`reasoning`/`mechanical`/`quick`) via a `<!-- sysop:model-roles … -->` body marker, not a model name; this rewrites each marked `model:` value to the model `.claude/served_models.yml` (+ the consumer's never-overwritten `served_models.local.yml`) maps that role to. `install.sh` runs it with `--apply` after copying the skills tree, re-running on every `--update`. A byte-for-byte no-op under the default mapping (so a default install does not diverge from source); a structural error writes nothing (skills keep shipped defaults — never half-applies). **Phase 223: `install.sh` runs `check_skill_models.py` immediately BEFORE `--apply` and refuses the whole rewrite if the mapping is invalid** — the checker judges what a role *resolves to*, so it is meaningful before the pins change, and afterwards it would only certify damage already done. Without that ordering the arm was inert on the one path that creates the defect: `--update` after editing `served_models.local.yml`, which is the remedy the docs prescribe. Marker/config parsing shared via `_model_roles.py`. Requires PyYAML. |
| `check_skill_models.py` | Phase 69 model-role guard (was the Phase 65b flat allowlist). Fails (exit 1) if any `.claude/skills/` pin is un-roled, names a role absent from `served_models.yml` `roles:`, resolves to a model absent from `served:`, or (Phase 223) governs an INLINE pin while resolving to a value absent from `inline_models:` — the Agent tool's `model` argument is a closed enum, so `best`/`inherit`/a full id would fail at spawn time. **A fifth arm checks the pin's own literal value against that enum, independently of its role**, because the other four judge what a role *resolves to* and the plugin install path never rewrites the file — so the literal in the tree is what the harness receives. Exit 2 (usage) on a malformed config or an empty skills tree, which is a broken install rather than a passing check. The `served:` arm is the loud-sunset signal: drop a retired model from `served:` and any role still mapped to it goes red. Defaults to the installed layout; in the Sysop source tree run with `--root core/skills --config core/companion/.claude/served_models.yml`. Wire into pre-commit via `git-hooks/examples/pre-commit-model-pins.example` (in the Sysop source repo — `examples/` is not installed); Sysop's own CI uses `tests/test_check_skill_models.py::test_sysop_own_skills_all_roles_served` (not shipped). Requires PyYAML. |
| `migrate_skill_model.py` | Model-alias bulk-rewriter — now the RARE path (Phase 69 made the common model swap a one-line `served_models.yml` role repoint). Tier-safe rewrite of bare-alias literals `--from <old> --to <new>` across `.claude/skills/` (dry-run default; `--apply` writes) for the role-vocabulary-change or pre-marker-tree case. Keys strictly on `--from`, so other tiers are structurally untouchable; flags freeform prose mentions for human review instead of robo-editing English. |
| `pr_dependabot.py` | Phase 53 client-side Dependabot sweep behind `/pr-dependabot` — a replacement for GitHub's native auto-merge, which is unavailable on private repos under the Free plan. Lists open Dependabot PRs, classifies each by ecosystem + semver bump, and prints a dry-run plan (default) or executes it (`--execute`): npm/docker patch+minor merge on green CI, trusted-publisher `github-actions` likewise, majors hold for human review, pip / `chore(deps)` close, superseded duplicates close. Supersession is scoped to the currently-open set only, never to history. Merge policy validated against ~50 real PRs. |
| `backfill_completed_dates.py` | One-time migration helper — when a project moves from a single-file `[x]` checklist (e.g. `product_roadmap.md`) to the hybrid `tasks/` system, already-done tasks lose their completion timestamps; this reconstructs `completed_date` by grepping git history for the commit that introduced each `[x]` marker. `--dry-run` previews. Not needed after migration: `/review-close` writes `completed_date` on every close. Atomic-rewrite + defensive-parse hardened in Phase 108. |
| `_log.py` | Private shared helper (underscore-prefixed — not an entry point). `_sanitize_log()` strips ANSI escapes and control characters and truncates to `max_len` before any script prints a path, YAML fragment, or exception message, so a malformed error can't corrupt the operator's terminal or hide warning text. Single source of truth for `sysop/scripts/`-internal callers since Phase 68 (`from _log import _sanitize_log`). `validate_tasks.py` and `next_task.py` keep inline copies **on purpose** — both run from pre-commit before the project venv (and therefore the full `sys.path`) is reliably wired up, so they stay standalone. |

A new project should port these from the reference implementation and adapt paths (e.g., frontend directory name, test framework). The pre-commit hook template in § 6.4 is the only script fully templated inline; the others are too project-specific to template but are ~100–300 lines each in the reference implementation.

**Model roles (Phase 69).** Skills do not hard-pin a model. They pin a *role* — `reasoning` (deep/adversarial/audit/judge + review-skill frontmatter), `mechanical` (prescriptive scoped fix agents, e.g. `/auto-fix`), or `quick` (trivial read-only surveys) — via a body marker the harness never parses. `.claude/served_models.yml` (Sysop-owned, refreshed on update so sunset fixes flow) maps each role to a model; the install/update resolver applies that mapping. To pick your own models without losing those updates, create `.claude/served_models.local.yml` with just the `roles:` you want to change (local wins; extend `served:` for any non-default value — `fable` is already pre-listed in the default `served:`, so `roles: reasoning: fable` is a complete override on its own; worked examples live in `served_models.yml` itself and the Sysop repo's `docs/configuration.md`). **A role's value is constrained by which pin kind it governs, and the two kinds differ (Phase 223).** A *frontmatter* pin accepts what `/model` accepts — a short alias (`opus`/`sonnet`/`haiku`/`fable`), a full id (`claude-opus-4-8`), a provider id (Bedrock ARN, Vertex name), or a meta-value (`best`/`opusplan`) — plus `inherit`, which is a frontmatter-only value and not a `/model` alias. An *inline* pin becomes the Agent tool's `model` argument, which is a **closed enum**: it takes the four short aliases and rejects everything else at spawn time, mid-skill. `reasoning` and `mechanical` both govern inline pins today, so mapping either outside the `inline_models:` list breaks every spawn in the skills that role governs — `check_skill_models.py` fails on it, and adding the value to `served:` does not help, because `served:` is the sunset allowlist and not the harness's enum. So the seam is provider-neutral for frontmatter and alias-only for inline; only the default mapping is Claude either way. Swapping the model behind a role (a sunset, a cost trade, a better model shipping) is a one-line config edit, not a sweep across the skills tree.

### 8.5 Git hooks (`sysop/scripts/hooks/`)

| Hook | Source | Purpose |
|------|--------|---------|
| `pre-commit` | skeleton § 6.4 | Two-tier (blocking + advisory) convention checks on staged files |
| `pre-merge-commit` | § 4.3 | Pre-merge gate skeleton — template pytest/build checks ship commented out; fill in per-project |

### 8.6 Runtime directories (created on demand, gitignored)

| Path | Populated by | Purpose |
|------|-------------|---------|
| `sysop/runtime/locks/<TASK_ID>.lock` | `claim_task.sh --lock` | Optional multi-agent coordination |
| `sysop/runtime/pending-docs/<branch>.md` | `/document-work` | Deferred documentation, consolidated at merge |
| `sysop/runtime/subagent-envelopes/<TASK_ID>[.<phase>].json` | `parse_subagent_envelope.py` (SubagentStop hook) | Structured envelope receipt from `/claim-task`'s planner / reviewer / executor + `/auto-build` execution agents (Phase 37). The `.<phase>` infix appears only when the envelope carries a `PHASE:` field (Phase 159a), which keys one file per stage so several sub-agents can share a claim id; absent it, the filename is `<TASK_ID>.json` as before. **`/auto-build` consumes and deletes its own; `/claim-task` keeps its three** (Phase 171 — a deleted envelope made a skipped review indistinguishable from a completed one) and instead moves any left over from a previous run of the same claim into `<ARTIFACT_DIR>/prior-envelopes/` at Step 7-pre. Persists on hook-parse miss as `_unparseable_<session>_<agent>.json` for diagnostics. |
| `sysop/runtime/claim/<CLAIM_ID>/<RUN_ID>/` | `/claim-task` Steps 7-pre, 7a, 7b, 7c | Per-run artifact set for one orchestrated claim: `plan.md` (planner), `review.md` (reviewer, carrying the sealed `REVIEW_REPORT:`), `classification.md` (the orchestrator itself), `review-transport.md` (the post-review transport receipt) and `planner-integrity.md`, plus `prior-envelopes/` when a re-claim moved a previous run's envelopes aside. `<RUN_ID>` is a UTC timestamp plus 8 random hex — per-run so a re-claim cannot *reach* a previous run's verdict, which a staleness comparison could not deliver (`batch_work.sh`'s lock write is idempotent and preserves `started:`, so a batch re-claim inherits a stamp-matching lock). Lives in the **main** checkout, resolved via `git rev-parse --git-common-dir`, so it is discoverable before a worktree is known and outlives `git worktree remove`. **Nothing removes it yet** — close-time cleanup is part B of the Phase 171 reshape. `<CLAIM_ID>` is the task id for a roadmap task and `BATCH-<N>` for a review batch. |
| `sysop/runtime/parked/<TASK_ID>__<timestamp>.md` | `/auto-build` Phase 6d | Durable archive of a parked task's plan + adversarial verdict, mirrored from the per-worktree `sysop/runtime/auto-build/` scratch so it survives `cleanup_worktrees.sh --force`, which removes every non-main worktree wholesale (Phase 65a). Lives at the project root, not in the worktree. Removed by `/review-close` Step 4c when the task closes (alongside the lock); a `claim_task.sh --release` deliberately leaves them for the next claimant. |
| `sysop/runtime/parked/<CLAIM_ID>__<RUN_ID>.md` | `/claim-task` Step 7c | Park **marker** for an orchestrated claim (Phase 171): the reason it parked, the branch, which artifacts were present, and the `--resume` line that re-enters it. A pointer, not a copy — the artifacts already live in the main checkout under `sysop/runtime/claim/`, so there is nothing to rescue from the worktree. Same `<id>__*.md` filename shape as `/auto-build`'s, so `/review-close` Step 4c's existing glob removes a **roadmap** marker at close; a `BATCH-<N>` marker is removed by nothing, because that list is built from roadmap ids only. |
| `../<project>-<task-id>/` | `claim_task.sh` | Git worktree per task |

### 8.7 Port checklist

When bootstrapping into a new project:

1. Copy `sysop/docs/WORKFLOW.md`, `sysop/docs/WORKFLOW_GUIDE.md`, and this manifest — no edits needed (Phase 128 moved these under the `sysop/` vendor dir; the bare paths this step used to name have not existed in a consumer install since)
2. Write CLAUDE.md from § 6.1 template (empty `## Prevention Conventions`)
3. Create `.claude/convention_map.md` and `.claude/security_map.md` from § 6.2 / § 6.3 templates (3–5 sections each)
4. Create empty `.claude/checks.yml` (add entries via convention promotion)
5. Write `.claude/settings.json` from § 8.2a (the project-scoped permission allow-list — under `git add`)
6. Port skills from `.claude/skills/` — in the reference impl, these are Claude Code files; for other agents, translate the step lists into the agent's instruction format
7. Port scripts from `sysop/scripts/` (adapt paths, test commands, frontend directory name)
8. Install hooks: `bash sysop/scripts/install_hooks.sh`
9. Create `review_tasks.md` with one empty `## Round 1` section
10. Run `bash sysop/scripts/run_checks.sh` to verify the check registry loads (should report zero findings on the empty registry)

After bootstrap, proceed with § 7 (Bootstrap Checklist) for the iterative development steps that follow.

---

*This workflow was extracted from the GDP Query System project, which developed it iteratively over 40+ review rounds. The portable process (sections 1–5) is independent of that project. Section 6 uses it as a worked example. Section 8 is the portable kit manifest.*
