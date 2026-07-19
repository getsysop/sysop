# Workflow Guide for Developers

> A human-readable companion to WORKFLOW.md.
> WORKFLOW.md is the authoritative spec (used by AI agents and automation).
> This guide explains the same process in plain terms — readable without
> wading through the full spec.
>
> The lifecycle is driven by Claude Code skills (`/intake`, `/claim-task`,
> `/document-work`, `/review-close`, …), and this guide names them at each
> step. **Every skill automates a manual procedure** — if you work without
> an AI assistant, the same step is described in plain terms alongside the
> skill name (e.g. "the senior reviewer merges and consolidates docs" is
> what `/review-close` automates). The whole workflow can be run by hand.
>
> A slimmer install also exists: `--mode loop` delivers only the convention system
> and review machinery (the "Convention System Explained" and "Running a Code Review"
> halves of this guide's world) with none of the 7-step lifecycle. Its guide is the
> public [docs/loop-mode.md](https://github.com/getsysop/sysop/blob/main/docs/loop-mode.md);
> this document ships with full installs only.

---

## Quick Start: The 7-Step Lifecycle

> **About the examples in this section:** Task IDs (`FEAT-STUDIO`, `TECH-CSP`, `Batch 270`) and worktree paths (`../gdp-feat-studio`) are drawn from the originating GDP Query System project. Substitute your project's task IDs and basename — `claim_task.sh` derives the worktree prefix from `$(basename "$REPO_ROOT")` automatically, so a project named `beanrider` will create `../beanrider-feat-*` rather than `../gdp-feat-*`.

### 0. Populate the Queue (first time, or when a new batch of work comes into focus)

Steps 1–7 below assume `tasks/index.yml` already holds claimable work. It doesn't populate itself — `install.sh` seeds an *empty* queue. The planning front door is **`/intake`**: bring a brain-dump or a written brief, and it runs an interactive loop (playback → sounding-board → phases → priority) and **emits a populated, validated phase-one slice** of `tasks/index.yml` plus `tasks/open/<TASK-ID>.md` bodies. It also seeds the intent layer — `tasks/vision.md` and `tasks/decisions.md` at the `tasks/` root (consumer-owned; the installer never creates them). Re-enter it later to deepen phases as they come into focus.

Onboarding an **existing** project instead of starting one? **`/onboard`** is the mature-project engine behind `/intake`'s adopting branch: with your consent (never silently) it reads the repo's own evidence — README, docs, manifests, git history — and *drafts* the intent layer for you to confirm or correct (observations recorded as fact; inferred rationales explicitly marked and walked with you, never asserted), and/or imports an existing backlog (`ROADMAP.md`, `TODO.md`, open GitHub issues) into `tasks/index.yml` — decomposed to the task schema, dedup'd against anything already queued, every imported task provenance-marked `surfaced_by: [imported]` so downstream batching (`/auto-build`) treats its effort estimates as the archaeological guesses they are. It leaves everything uncommitted and hands off to `/intake` for going-forward planning.

Mid-project, most planning events are smaller than a phase: a bug spotted in a screenshot, an idea that surfaces mid-review, a chore noticed in passing. **`/add-task`** is the quick-capture path for exactly that moment — one task (or two or three independent siblings) in, a validated `index.yml` entry plus `open/<TASK-ID>.md` body out, deduped against the open queue and left uncommitted for your sign-off. It never creates phases or touches the intent layer; when the thought turns out to be phase-shaped after all, it routes you back to `/intake`.

How big should each task be? Decomposition follows the shared rubric in `_shared/decomposition-rubric.md` — one-sentence done-condition litmus, `effort` ⊥ `blast_radius` (size of the work vs. size of the surface are independent), `depends_on` = physical impossibility, and so on.

Doing this by hand? Author `tasks/index.yml` entries directly against `tasks/schema.md` and validate with `.venv/bin/python sysop/scripts/validate_tasks.py` — or say `/add-task <what you want>` and let the skill do the schema bookkeeping.

### 1. Find Work

Check two sources:
- **`tasks/index.yml`** — feature/infrastructure tasks with IDs like `FEAT-STUDIO`, `TECH-CSP`. Per-task prose lives in `tasks/open/<TASK-ID>.md`. Schema: `tasks/schema.md`. Each task carries an `effort:` value (how much work — `Low/Medium/High`) and, from Phase 19 onward, an optional `blast_radius:` (surface area — `single-file/single-module/cross-module/architectural`). `blast_radius` becomes required at `schema_version: 2`; consumers opt in by backfilling and bumping the version.
- **`review_tasks.md`** — code review batches with IDs like `Batch 270`

Pick the first unclaimed item (checkbox is `[ ]`, not `[x]` or `[/]`).

### 2. Claim & Isolate

Create a git worktree so you have an isolated filesystem:

```bash
# For a roadmap task:
git worktree add ../gdp-feat-studio feat/feat-studio

# Install hooks in the worktree:
cd ../gdp-feat-studio && bash sysop/scripts/install_hooks.sh

# For a review batch (automated claim + worktree):
bash sysop/scripts/batch_work.sh 270
```

Mark the task as in-progress via `/claim-task <TASK-ID>` — it flips `status: open → in_progress` in `tasks/index.yml` and creates `.locks/<TASK-ID>.lock` (the validator's `in_progress` invariant requires both).

### 3. Plan

Before writing code, look up which conventions apply to the files you'll change:

1. Open `.claude/convention_map.md`
2. Find the section whose file glob matches your target files (e.g., `<api module>/routes/*.py` → "API Endpoints")
3. Read the 5-8 convention bullets in that section — these are the rules to follow

For security-sensitive files, also check `.claude/security_map.md` for OWASP-specific guidance.

### 4. Code

Work in the worktree on the feature branch. Follow the conventions from step 3. Never commit to `main` directly.

The pre-commit hook runs automatically and will warn or block on common anti-patterns (f-string SQL, raw exceptions in responses, etc.).

### 5. Commit & Document

Use conventional commit format:
```bash
git commit -m "feat: add payment-provider webhook endpoint"
```

Write a deferred documentation file (prevents merge conflicts):
```bash
mkdir -p .pending-docs
cat > .pending-docs/feat-feat-studio.md << 'EOF'
---
branch: feat/feat-studio
date: 2026-03-20
type: feature
roadmap_ids: [FEAT-STUDIO]
summary: Add payment-provider webhook endpoint. Key files: <api module>/routes/webhooks.py, <api module>/<payments service module>.
---
EOF
```

### 6. Verify & Push

```bash
# Backend tests:
APP_ENV=test pytest tests/

# Frontend build:
cd frontend && npm run build

# Push when passing:
git push -u origin HEAD
```

**Frontend diffs also need a UI verification pass** — before committing, start the dev server, load the changed feature in a browser, and check the console + network tab for errors. The `/claim-task` and `/document-work` skills automate this via Playwright when an AI agent is driving; when doing it manually, do it by hand. Hard-fail on console errors and 5xx responses. Skip cleanly if the feature is auth-gated only.

**Record the test decision.** In the task body (`tasks/open/<TASK-ID>.md`), write a `## Test decision` line stating either "test X proves Y" or "no test because Z". This is the record the senior reviewer reads back against your actual diff at merge time (see Merge Process below). `validate_tasks.py` warns when an in-progress task is missing it.

### 7. Wait for Review

Do NOT merge to `main`. The senior reviewer handles merging, documentation consolidation, and deployment verification.

---

## Convention System Explained

### What are conventions?

Prevention conventions are codified rules learned from past code reviews. Each one:
- States a specific rule: "Never render `err.message` directly"
- Points to the correct pattern: "Use the project's error-display helper from the shared frontend utilities module"
- Was derived from finding the same mistake 3+ times in a round *and* seeing it recur in a later round (cross-round survival — one noisy round doesn't promote)

They live in `CLAUDE.md` under `## Prevention Conventions`, organized by category (Frontend, Backend, Testing).

### Convention maps

**`.claude/convention_map.md`** maps file patterns to the subset of conventions relevant to those files. Instead of checking all 50+ conventions for every file, you check only the 5-8 that apply.

Example: when working on `<hooks dir>/*.ts`, check only the "Custom Hooks" section (AbortController cleanup, timer cleanup, stale closures, etc.).

**`.claude/security_map.md`** does the same for OWASP security checks. Each section has a **Check** list (what to audit) and a **Skip** list (what doesn't apply).

### Project-specific extensions to convention/security/checks (Phase 24a)

The three concat-style configs above (`convention_map.md`, `security_map.md`, `.claude/checks.yml`) regenerate from Sysop's core + selected packs on every `bash sysop/scripts/sysop-update.sh`. To add project-specific sections that *survive every update*, author a sibling `*.project.<ext>` file: `.claude/convention_map.project.md`, `.claude/security_map.project.md`, or `.claude/checks.project.yml`. The installer appends (markdown) or YAML-merges (checks) it AFTER the regenerated body. These files are consumer-authored and consumer-owned — Sysop never writes them, so `--update` cannot touch them. See WORKFLOW.md § 8.2c for the full contract.

**Placeholder substitution (Phase 25, scope narrowed Phase 55).** Pack `checks.yml.fragment` files ship `paths:` lists with placeholder tokens (`<api module>/`, `<scripts dir>/`, etc.) that name your project layout abstractly. Author `.claude/substitutions.project.yml` with a top-level `substitutions:` map (e.g., `"<api module>": "parsers"`) and the installer substitutes `paths:` values in the upstream `.claude/checks.yml` body BEFORE the suffix file is appended — so checks resolve on disk and actually fire. Substitution touches `paths:` lines only; the markdown maps (`convention_map.md`, `security_map.md`) keep their placeholder tokens verbatim as documentation. Same consumer-owned, never-overwritten property as the suffix files. Stale-token report at end of install catches typos.

### How new conventions get added

1. A code review finds the same issue 3+ times across different files in a round
2. A candidate convention is drafted (rule text + which map sections it applies to) and recorded against that round
3. The pattern recurs in a later round (cross-round survival), and the candidate is reviewed and approved — a first-round burst is carried forward, not promoted yet
4. The convention is added to `CLAUDE.md` and the map files are updated
5. If the anti-pattern is grep-detectable, a pre-commit hook check is added

This cycle repeats each review round, making the system progressively smarter.

---

## Running a Code Review

### Deterministic checks (anyone can run)

```bash
# Run all convention checks:
bash sysop/scripts/run_checks.sh --mode both

# Quality checks only:
bash sysop/scripts/run_checks.sh --mode quality

# Security checks only:
bash sysop/scripts/run_checks.sh --mode security
```

`run_checks.sh` runs six stages in one invocation:
- **Grep** — patterns from `.claude/checks.yml` (each check has an ID, pattern, severity, description; some need manual triage per the `notes` field)
- **LSP / typechecker** — `pyright` (Python) and `tsc --noEmit` (TypeScript). Findings get `pyright-*` or `tsc-*` IDs. Skipped if the binary is absent
- **Semgrep AST** — rules from `.claude/semgrep/*.yaml` for patterns regex cannot express. Findings get `semgrep-*` IDs. Skipped if `semgrep` or `.claude/semgrep/` is absent
- **ESLint** — JS/TS lint findings, emitted under a single `lint-*` catch-all ID. Skipped if ESLint is absent
- **pip-audit** — known-vulnerability scan of installed Python dependencies. Findings get `pip-audit-*` IDs. Skipped if `pip-audit` is absent
- **Coverage** — diff-coverage of *crown-jewel* paths via `diff-cover`. A check declares a `critical_path:` glob list; uncovered changed lines inside it become `coverage-*` findings. A `blocking: true` coverage check **hard-fails** and is deliberately carved out of the baseline — you can't `--update-baseline` your way past a crown-jewel coverage gap; the only legitimate escape is a coverage pragma at the report-producer layer. Skipped when no coverage report is present. See WORKFLOW.md §6.5.

All six share the same finding shape, so baseline matching (`.claude/checks_baseline.txt`) and `--fail-on-blocking` apply uniformly — except coverage, which never baselines (above).

### Manual review

For each file area, use the convention map to know what to check:
1. Open `.claude/convention_map.md`
2. Find the section matching the files being reviewed
3. Check each convention bullet against the code

One review dimension worth calling out: **source verification** (adversarial-review dimension #9). When a plan or a diff calls an external SDK/framework API that has no in-repo precedent, flag it as `unverified` rather than assuming it's correct — hallucinated API calls are a common failure mode. The `/claim-task` plan template carries a matching `## Constraints & Risks` preamble so this surfaces at plan time, not only at review time.

Write findings to `review_tasks.md` using the batch format documented in WORKFLOW.md §4.2.

---

## Merge Process (Senior Reviewer)

This whole process is what `/review-close` automates; run it by hand when no AI assistant is driving.

1. Review each feature branch: `git diff main..<branch>`
2. Cross-check changes against applicable conventions
3. **Verify the test-decision record** — read the branch's `## Test decision` back against the diff ("plan said test X — is it here?" / "no-test-because-Z — does Z still hold?"). Halt for a human decision on a mismatch. This *verifies the record*; it does not re-judge whether the test strategy was right (that was the plan-time reviewer's job).
4. Run full verification: `pytest` + `npm run build`
5. Merge: `git merge --ff-only <branch>`
6. Consolidate `.pending-docs/*.md` into shared documentation files
7. Push and verify staging deployment
8. Clean up: delete merged branches and worktrees

---

## Pre-merge Verification Structure

Each project's `CLAUDE.md` declares a `## Pre-merge verification` section listing the commands the senior reviewer (or `/review-close`) runs before push. It supports two shapes:

- **`### Always`** — full-tree commands that run unconditionally on every review pass (build, full test suite, project-level smoke tests). One command per bullet.
- **`### Ratchet (changed files only)`** — a bash code block of project-supplied snippets. Each snippet pipes `git diff --name-only origin/main...HEAD` through a file-type filter and invokes lint or typecheck against only the changed files. Snippets short-circuit and pass when no changed file matches the filter.

A section that omits both sub-headings is treated as a flat `### Always` list — fine for projects without a ratchet yet.

**Boy-scout consequence.** Editing a file with pre-existing lint or type findings causes the ratchet to fire on those findings too — touched files get cleaned, even when the regression isn't yours. Full-tree backlog cleanups stay as separate tasks (e.g. `TECH-LINT-BACKLOG-FIX`), so the ratchet doesn't force a clean-everything-first dependency on a project with an existing backlog. The full template lives in WORKFLOW.md § 6.1.

**Venv-aware invocation.** The agent's tool shell starts cold. If a verification command depends on a tool installed in a project venv (`pytest`, project-specific CLIs, linters), spell out the venv path in the section (`.venv/bin/pytest`, `.venv/bin/python sysop/scripts/validate_tasks.py`) — bare command names hit the system PATH and either fail or, worse, succeed against the wrong interpreter. The same rule applies to git hooks in `sysop/scripts/hooks/`: prepend `${REPO_ROOT}/.venv/bin` to `PATH` at the top of each hook. Sysop does not auto-detect venv paths.

---

## /review-close Hardening

`/review-close` has been hardened across many phases as real downstream cycles surfaced papercuts; PHASE_LOG.md carries the full trail (Phases 23, 30–35, 43a, 59, …). The most recent addition is the **verify-the-record** step (Phase 59) described in step 3 of the Merge Process above. The original five-papercut slice (Phase 23, BeanRider ISSUE-0018 through -0022) remains a good illustration of the kind of issue this skill absorbs:

- **Pending-doc namespace clarity:** `/document-work` now writes `roadmap_ids:` (consumed by Step 4c's `tasks/index.yml` round-trip) and `review_task_ids:` (documentary-only — actual closure happens via `bash sysop/scripts/close_batch.sh`). The old single `task_ids:` field silently no-op'd review-task IDs.
- **Step 1b atomic archive-rotation commit:** when both `review_tasks.md` and a sibling `*_archive.md` are dirty and `review_tasks.md` has net deletions, both files land in one atomic `docs: archive …` commit. Splitting them across two commits left the archive file untracked.
- **Step 1c drain warning:** a soft pre-rebase warning fires when any in-scope feature branch was cut before an archive rotation on main. The actual conflict resolution still happens at Step 4a (keep main's structure, re-apply the branch's intent).
- **Step 4a rebase-conflict prose:** the old "feature branches don't modify review_tasks.md" disclaimer was wrong (batch checkbox flips do, and rebases conflict after archive rotations). Rewritten with concrete resolution guidance.
- **Step 6 cleanup order swap:** delete the remote branch first, then the local branch — `git branch -d` refuses on every rebased branch when the upstream still points at the pre-rebase SHA. No `-D` fallback (safe-delete refusal is correct; the fix is to drop the upstream first).

---

## Navigating the queue: helper skills

A few read-mostly skills help you orient without changing state:

- **`/next-task`** — deterministically resolves and shows the single next claimable task (respecting `depends_on`, locks, and priority) with its effort estimate and blockers. The manual equivalent is "scan `tasks/index.yml` for the first `open` task whose dependencies are all `done`."
- **`/plan-review`** — an on-demand adversarial pass over any plan — one sketched in conversation, a file, or a task body — using the same template `/claim-task` runs internally (`_shared/adversarial-review.md`): findings classified `fixable`/`blocker`, external SDK/framework calls with no in-repo precedent flagged `unverified` (Phase 58a), and a revised plan presented for approval before anything executes. Reach for it when you want the plan critique without the claim/lock/worktree machinery.
- **`/sitrep`** — surveys the whole Sysop surface (locks, worktrees, branches, index entries, review batches) and reports where each task sits in the lifecycle, with one top routing recommendation. Read-only.
- **`/roadmap`** — reads the queue back at portfolio level: where the project stands against `tasks/vision.md`, the outstanding work grouped by kind (feature / data-ops / infra) with readiness flags, and one to three proposed orderings of attack (unblock-the-human-first / foundation-first / ship-fast) with the trade-off behind each — each closing with a copy-pasteable `Run it:` actuator line (`/auto-build <IDs>` / `/claim-task <ID>`) so an ordering is a handoff, not just advice. The judgment sibling of `/sitrep` — `/sitrep` classifies what's *in flight now*; `/roadmap` strategizes what's *left*. Read-only; the demo beat between `/intake` (populate the queue) and `/auto-build` (execute it).
- **`/daily-summary`** — the backward-looking retrospective: a git-log-driven standup/async report of the most recent working day (commits classified by type, enriched from changelog/status docs, cross-referenced with tasks closed that day) plus a past-week roundup (activity heatmap, key themes, milestones). `--date` / `--days` / `--week-only` / `--yesterday-only` flags; weekend/gap-aware. Read-only. Where `/roadmap` answers "what's left," `/daily-summary` answers "what happened" — together they cover a human's two standing questions about a project.
- **`/test-audit`** — a standing, read-only survey of test *quality*, not execution state: where load-bearing surfaces (guards, error paths, boundaries, security/data-integrity, parsers) lack tests, and which existing tests have gone dead, redundant, or hollow. The complement to the coverage gate, which is diff-scoped by design (only *changed* crown-jewel lines) — `/test-audit` finds the standing/unchanged gaps the gate can't see. Judgment-led (`_shared/test-assessment-rubric.md`), crown-jewel-first, `--path` / `--all` / `--tier1` / `--tier2` flags. Recommends tests and retirements; never writes tests or mutates the queue — routes accepted recommendations to `/intake`.
- **`/triage`** — classifies pending review batches as `auto` (mechanical, safe to fix unattended) or `flag` (needs judgment) and persists the verdict to `review_tasks.md`. It's the prerequisite for the `/auto-fix` and `/auto-judge` batch processors.
- **`/report-issues`** — the transport half of the friction log: renders each `Open`/`Prompt-ready` entry in `SYSOP_ISSUES.md` as a GitHub issue, files the ones you consent to (per-entry) against the Sysop repo, and flips each filed entry to `Filed to Sysop` with its issue URL. Dry-run by default; `--execute` to file. GitHub-specific (shells `gh`); the second skill in the `pr-*`/reporting family after `/pr-dependabot`.
- **`/contribute-convention`** — the give-back half of "grow your own pack from real use": reads the conventions this project promoted locally (the never-managed `.claude/*.project.*` overlay), **strips project fingerprints down to placeholder vocabulary**, surfaces each rule's cross-round provenance, groups them into one proposal per target pack, and files them upstream to the Sysop repo as `pack_or_convention` issues — per-pack consent, dry-run by default, `--execute` to file. The convention sibling of `/report-issues` (which transports friction); the third GitHub-touching skill in the family.
- **`/share-wins`** — the positive-signal half of the give-back loop: reads the `[good]` entries in `SYSOP_ISSUES.md` (what Sysop did notably well, worth *protecting from a future change*), and shares the ones you consent to (per-entry) as **one aggregated comment** on a standing "Wins" Discussion in the Sysop repo — then flips each shared entry to `Status: Shared` with a back-ref so re-runs never double-post. Dry-run by default; `--execute` to post. The only skill in the family that posts to **GitHub Discussions** (via `gh api graphql`) rather than the issue tracker — a win is "don't regress this," not tracked work. The wins sibling of `/report-issues` (friction) and `/contribute-convention` (conventions).
- **`/release`** — the release-authoring layer above per-batch `/review-close`: bundles the many merges since the last git tag into a proposed semver bump (inferred from conventional-commit types), a Keep-a-Changelog `CHANGELOG.md` entry, an annotated git tag, and — opt-in via `--github-release` — a GitHub Release. Reuses `/daily-summary`'s commit classifier and joins `tasks/index.yml` for task-title-enriched highlights. **Write-side and human-gated** (the sibling of `/review-close`, not the read-only family): dry-run by default, `--execute` writes the changelog + creates/pushes the tag, and the public Release is a second opt-in. Version source is tag-first, manifest read-only — it never rewrites `package.json`/`pyproject.toml`. Deliberately lightweight — staged rollout / canary / rollback are the ops band Sysop holds the line on.

## When to use `/auto-build`

`/auto-build` is the optional parallel-batch orchestrator (see WORKFLOW.md § 2.4b). Invoke when you have ≥ 2 independently-claimable tasks in your current-focus phase and want to walk away while a batch executes.

The orchestrator picks the batch (effort × `blast_radius` weights under a K=12 sum ceiling, max N=4 tasks, up to two cross-module tasks). Pass explicit task IDs — `/auto-build FEAT-A TECH-B`, e.g. the `Run it:` line a `/roadmap` ordering emits — to narrow the pool to a chosen subset; the eligibility filters and ceilings still apply, and requested IDs that don't survive them are reported with per-ID reasons, never silently dropped. It then pre-claims each task on `main`, then per task fans out plan-only → adversarial-reviewer → execution Opus sub-agents at the orchestrator layer (the orchestrator does all fan-out itself — a deliberate flat-hierarchy design; see `_shared/adversarial-review.md` § "Harness constraint"). Tasks that the orchestrator's classification step marks as `blocker` are parked with their plan + verdict written to `<worktree>/.auto-build/` for the human to resume. Tasks classified `fixable` continue to execution; each execution agent invokes `/document-work --non-interactive` to commit + write pending docs but does NOT push. The orchestrator prints a status table when done; the human runs `/review-close` on each EXECUTED branch to merge.

**Skip `/auto-build` when:**

- Your roadmap is sequential (only one claimable task in the current-focus phase).
- You're actively iterating on a single change — interactive `/claim-task` is the right shape.
- The batch shares a verify command that mutates a shared database — parallel execution races on schema/seed fixtures; force `N=1` (`/auto-build 1`) or use `/claim-task` sequentially.

The orchestrator never runs `/review-close`. Human stays the merge gate.

## Adapting for Mobile Development

The workflow structure is platform-agnostic. Here's what changes for iOS/Android:

### Build & Test Commands

| Web (current) | iOS | Android |
|---|---|---|
| `npm run build` | `xcodebuild -scheme App -sdk iphonesimulator build` | `./gradlew assembleDebug` |
| `npm run test` | `xcodebuild test -scheme App -destination 'platform=iOS Simulator'` | `./gradlew test` |
| `pytest` (backend) | Same (if shared backend) | Same (if shared backend) |
| `npx playwright test` | XCUITest or Detox | Espresso or Detox |

### Convention Categories

| Web | Mobile equivalent |
|---|---|
| React Components (`.tsx`) | Views / Screens (`.swift` / `.kt`) |
| Custom Hooks (`.ts`) | ViewModels / Managers |
| Frontend Utilities (`lib/`) | Shared utilities / Extensions |
| API Routes (`app/api/`) | Not applicable (no server routes) |
| Frontend Tests (`__tests__/`) | Unit tests (`*Tests.swift` / `*Test.kt`) |

### Security Map Differences

| Web concern | Mobile equivalent |
|---|---|
| XSS / `dangerouslySetInnerHTML` | WebView injection, deep link validation |
| `isSafeHref()` URL validation | Universal/app link validation, intent filtering |
| CSP headers | App Transport Security (iOS), Network Security Config (Android) |
| `window.open` noopener | `openURL` with source validation |
| CORS configuration | Not applicable (native networking) |

### Pre-commit Hook Checks

Replace web-specific patterns with mobile equivalents:

| Web check | Mobile equivalent |
|---|---|
| f-string SQL (Python) | Same (if shared backend) |
| `fetch()` without AbortController | URLSession without cancellation token |
| `window.open` without noopener | Force unwrap (`!`) without guard (Swift) |
| `vi.mock` without cleanup | Mock cleanup in `tearDown()` |
| `toBeDefined()` on DOM queries | Not applicable |

### What Stays the Same

- **Worktree isolation** — works with any git project
- **Convention map structure** — different entries, same format
- **Security map structure** — different threats, same Check/Skip format
- **Pre-commit two-tier pattern** — different checks, same shell structure
- **Review → batch → fix → merge lifecycle** — platform-independent
- **Convention promotion feedback loop** — the core learning mechanism
- **Deferred documentation** — prevents merge conflicts regardless of platform
- **`review_tasks.md` batch format** — tracks findings for any codebase

### What Needs New Content

When bootstrapping for mobile, create:
1. Convention map with mobile-specific sections (Views, ViewModels, Networking, etc.)
2. Security map with mobile-specific threats (deep links, local storage, biometrics, etc.)
3. Pre-commit hooks with language-specific anti-patterns
4. `.claude/checks.yml` entries for mobile conventions

The workflow scaffolding (WORKFLOW.md, batch scripts, archive tooling) works as-is.

---

*This guide covers the same process as WORKFLOW.md in human-readable form, naming the
Claude Code skills that drive each step alongside the manual procedure each one automates.
For the authoritative process specification, see WORKFLOW.md.*

*Keeping this in sync: WORKFLOW_GUIDE.md is a hand-maintained mirror. When a phase changes
the lifecycle — a new lifecycle skill, a new check stage, a schema field that shows up in
the examples here — refresh the relevant section in the same phase. PHASE_LOG.md stays the
canonical prose home, but the lifecycle-facing surfaces (this guide, WORKFLOW.md,
docs/workflow.html) need the touch-up too.*
