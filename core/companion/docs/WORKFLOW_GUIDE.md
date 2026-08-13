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

Doing this by hand? Author `tasks/index.yml` entries directly against `tasks/schema.md` and validate with `python3 sysop/scripts/validate_tasks.py` — or say `/add-task <what you want>` and let the skill do the schema bookkeeping.

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

# For a review batch (automated claim + worktree):
bash sysop/scripts/batch_work.sh 270
```

No hook install is needed in the worktree — by default every worktree shares the main repo's hooks directory, so it already runs whatever you have armed there. (Arming from inside a worktree actively harms: it pushes that branch's `sysop/scripts/hooks/*` into the shared directory. If you use `core.hooksPath` the target differs, but Sysop does not write there either. See WORKFLOW.md § 4.3.)

Mark the task as in-progress via `/claim-task <TASK-ID>` — it flips `status: open → in_progress` in `tasks/index.yml` and creates `sysop/runtime/locks/<TASK-ID>.lock` (the validator's `in_progress` invariant requires both).

**Both claim kinds take a lock.** A review batch is not the informal half of this — `batch_work.sh` writes `sysop/runtime/locks/BATCH-<N>.lock` in the same directory and the same shape, which is what stops `/next-task`, `/sitrep` and the collision advisories from handing the same batch to a second agent. Reverse either one from the main checkout: `claim_task.sh --release <TASK-ID>` for a roadmap task, `batch_work.sh --release <BATCH-NUMBER>` for a batch.

**`/claim-task` does not stop at the claim any more.** Since Phase 171 it is an *orchestrator*: after the lock and worktree it spawns a planner, spawns an independent reviewer of that plan, classifies the findings itself, optionally gates on you, and spawns an executor — writing `plan.md`, `review.md` and `classification.md` under `sysop/runtime/claim/<CLAIM_ID>/<RUN_ID>/` as it goes. `WORKFLOW.md` § 2.2 is the authoritative description. **Steps 3 through 5 below are the manual path** — what to do when you are working the task yourself rather than handing it to `/claim-task`, and what the sub-agents are doing on your behalf when you are not. They are not a second set of steps to run after it.

### 3. Plan

Before writing code, look up which conventions apply to the files you'll change:

1. Open `.claude/convention_map.md`
2. Find the section whose file glob matches your target files (e.g., `<api module>/routes/*.py` → "API Endpoints")
3. Read the 5-8 convention bullets in that section — these are the rules to follow

For security-sensitive files, also check `.claude/security_map.md` for OWASP-specific guidance.

### 4. Code

Work in the worktree on the feature branch. Follow the conventions from step 3. Never commit to `main` directly.

The pre-commit hook runs automatically — though it ships as a skeleton: it warns or blocks only once your project's checks accrete into it (f-string SQL, raw exceptions in responses, and the like are the shape of what gets added by convention promotion).

### 5. Commit & Document

Use conventional commit format:
```bash
git commit -m "feat: add payment-provider webhook endpoint"
```

Write a deferred documentation file (prevents merge conflicts):
```bash
mkdir -p sysop/runtime/pending-docs
cat > sysop/runtime/pending-docs/feat-feat-studio.md << 'EOF'
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

**Record the test decision.** In the task body (`tasks/open/<TASK-ID>.md`), write a `## Test decision` line stating either "test X proves Y" or "no test because Z". **Write it in your worktree's copy** — the merge-time reader looks at the branch, so a copy edited in the main checkout is committed by nothing and never reaches the PR. This is the record the senior reviewer reads back against your actual diff at merge time (see Merge Process below). `validate_tasks.py` warns when an in-progress task is missing it.

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

**`.claude/security_map.md`** does the same for OWASP security checks. Each section has a **Check** list (what to audit) and a **Skip** list (what doesn't apply) — both scoped to the files the section's globs match, so a section still in placeholder form confers neither.

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

One review dimension worth calling out: **source verification** (adversarial-review dimension 9). When a plan or a diff calls an external SDK/framework API that has no in-repo precedent, flag it as `unverified` rather than assuming it's correct — hallucinated API calls are a common failure mode. The `/claim-task` plan template carries a matching `## Constraints & Risks` preamble so this surfaces at plan time, not only at review time.

Write findings to `review_tasks.md` using the batch format documented in WORKFLOW.md §4.2.

---

## Merge Process (Senior Reviewer)

This whole process is what `/review-close` automates; run it by hand when no AI assistant is driving.

1. Review each feature branch: `git diff main...<branch>` (three dots — two compares the tips, so anything `main` gained after the branch was cut looks like the branch deleted it)
2. Cross-check changes against applicable conventions
3. **Verify the test-decision record** — read the branch's `## Test decision` back against the diff ("plan said test X — is it here?" / "no-test-because-Z — does Z still hold?"). Halt for a human decision on a mismatch. This *verifies the record*; it does not re-judge whether the test strategy was right (that was the plan-time reviewer's job).
4. Run a cheap pre-merge pass of the verification commands — but know what it can reach: you are still on `main`, so it verifies `main`, not the branches. Their files are not in your tree yet.
5. Merge — `git merge --ff-only <branch>` under the default `## Merge policy: direct`. If your project's `CLAUDE.md` declares `## Merge policy: pr` (the setting for a `main` that is push-protected by a required status check or `enforce_admins`), `main` is never written directly: land the approved branches on a throwaway integration branch and open one squash PR, so GitHub becomes the sole serialized writer of `main`. See WORKFLOW.md § 6.1. **When the rebase conflicts, route it — don't reflexively abort.** Two files every branch appends to as a matter of workflow conflict deterministically when two branches file in the same cycle: `tasks/index.yml` and `review_tasks.md`. Resolve them from the merge stages (`git show :2:<path>` is the target, `:3:` the branch) and run `python3 sysop/scripts/validate_tasks.py` **before** `git rebase --continue` — never by deleting the `<<<<<<<` markers and keeping both sides, which for an indented YAML list leaves one entry holding its `id` alone and still parses. A branch whose conflict you genuinely can't resolve is *skipped*, and steps 6 and 8 both have to know that.
5b. **Run full verification on the merged result: `pytest` + `npm run build`.** This is the gate that counts — the merged tree is the first tree that is both the work and what you are about to push. Do it here, before consolidating docs: a failure now costs nothing, and step 6 deletes the pending-docs after routing them.
6. Consolidate `sysop/runtime/pending-docs/*.md` into shared documentation files — but **first drop any whose branch did not actually merge** (`git rev-list --count "<branch>" "^HEAD"`; `0` = merged, and quote the `^` operand or zsh's `extended_glob` turns it into a filename pattern and silently returns the wrong answer). Step 5's copy happens *before* the merge is attempted, so a branch you skipped at step 5 leaves a doc here; consolidating it flips its task to `done` and archives the body with the code never merged. Delete only the docs you consolidated — never a bare "delete all remaining"
7. Push and verify staging deployment
8. Clean up: delete the branches step 5 **merged**, and their worktrees. A branch you skipped at step 5 keeps its branch, its lock and its doc — do not delete it, and under `pr` policy do not force-delete it either (after a squash no ancestry test can tell a merged branch from a skipped one, so the skip verdict itself is the evidence)

---

## Pre-merge Verification Structure

Each project's `CLAUDE.md` declares a `## Pre-merge verification` section listing the commands the senior reviewer (or `/review-close`) runs before push. **They run twice, on two different trees:** once before the merges as a cheap fail-fast on `main` (`/review-close` Step 3), and once after them on the merge target (`4a-post`) — that second run is the authoritative one, because it is the only one whose tree contains the work. It supports two shapes:

- **`### Always`** — full-tree commands (build, full test suite, project-level smoke tests). One command per bullet. **"Always" binds on the authoritative pass**: `4a-post` runs this list whatever the diff looks like, and no diff-shape heuristic skips it there. The cheap pre-merge pass *does* drop it when its own tree's diff touches no code — which on the dominant cycle is every time, since that tree holds only claim flips — and that is deliberate: a pass whose green is explicitly not a verdict is the one that can afford to be skipped.
- **`### Ratchet (changed files only)`** — a bash code block of project-supplied snippets. Each snippet pipes `git diff --name-only origin/main...HEAD` through a file-type filter and invokes lint or typecheck against only the changed files. Snippets short-circuit and pass when no changed file matches the filter — which is why *which tree they run on* decides whether they check anything: on the pre-merge pass that range is `main`'s local-only commits (often empty), and only on the merge target does it name the work.

A section that omits both sub-headings is treated as a flat `### Always` list — fine for projects without a ratchet yet.

**Boy-scout consequence.** Editing a file with pre-existing lint or type findings causes the ratchet to fire on those findings too — touched files get cleaned, even when the regression isn't yours. Full-tree backlog cleanups stay as separate tasks (e.g. `TECH-LINT-BACKLOG-FIX`), so the ratchet doesn't force a clean-everything-first dependency on a project with an existing backlog. The full template lives in WORKFLOW.md § 6.1.

**Venv-aware invocation.** The agent's tool shell starts cold. If a verification command depends on a tool installed in a project venv (`pytest`, project-specific CLIs, linters), spell out the venv path in the section (`.venv/bin/pytest`, or `.venv/bin/python scripts/build_ledger.py` for a Python script your own repo ships) — bare command names hit the system PATH and either fail or, worse, succeed against the wrong interpreter. The same rule applies to git hooks in `sysop/scripts/hooks/`: prepend `${REPO_ROOT}/.venv/bin` to `PATH` at the top of each hook. Sysop does not auto-detect venv paths.

This rule is about **your project's** tooling, not Sysop's own scripts. Never give a `sysop/scripts/*.py` invocation a `.venv/bin/` command word — the scripts a skill prescribes resolve venv PyYAML themselves, script-anchored first and only then the CWD, under both `.venv/` and `venv/` layouts (Phase 182). So bare `python3 sysop/scripts/<script>.py` is the form to use: it works inside a worktree and on the poetry/conda/`venv/`-layout/system-python projects where `.venv/bin/python3` is simply `command not found`. (The one host it does not serve and the venv form would is one with no `python3` on `PATH` at all — rarer, and it fails loudly.)

---

## /review-close Hardening

`/review-close` has been hardened across many phases as real downstream cycles surfaced papercuts; PHASE_LOG.md carries the full trail (Phases 23, 30–35, 43a, 59, 134, 151, 156–158, …) — this list dates fast, so treat PHASE_LOG.md as the current one rather than this sentence. The **verify-the-record** step (Phase 59) in step 3 of the Merge Process above is one instance; later ones include the `pr` merge policy with PR-state-as-verdict and PR reuse (Phase 151), releasing a review batch's lock at close (Phase 156), excluding a `> Failed:`-annotated task from the close so it stops flipping to done (Phase 157), and the merge-base diff basis plus isolated Step 2b reviewers (Phase 158). The original five-papercut slice (Phase 23, BeanRider ISSUE-0018 through -0022) remains a good illustration of the kind of issue this skill absorbs:

- **Pending-doc namespace clarity:** `/document-work` now writes `roadmap_ids:` (consumed by Step 4c's `tasks/index.yml` round-trip) and `review_task_ids:` (documentary-only — actual closure happens via `bash sysop/scripts/close_batch.sh`). The old single `task_ids:` field silently no-op'd review-task IDs.
- **Step 1b atomic archive-rotation commit:** when both `review_tasks.md` and a sibling `*_archive.md` are dirty and `review_tasks.md` has net deletions, both files land in one atomic `docs: archive …` commit. Splitting them across two commits left the archive file untracked.
- **Step 1c drain warning:** a soft pre-rebase warning fires when any in-scope feature branch was cut before an archive rotation on main. The actual conflict resolution still happens at Step 4a (keep main's structure, re-apply the branch's intent).
- **Step 4a rebase-conflict prose:** the old "feature branches don't modify review_tasks.md" disclaimer was wrong (batch checkbox flips do, and rebases conflict after archive rotations). Rewritten with concrete resolution guidance.
- **Step 6 cleanup order swap:** delete the remote branch first, then the local branch — `git branch -d` refuses on every rebased branch when the upstream still points at the pre-rebase SHA. No `-D` fallback (safe-delete refusal is correct; the fix is to drop the upstream first).

---

## Navigating the queue: helper skills

A few read-mostly skills help you orient without changing state:

- **`/next-task`** — deterministically resolves and shows the single next claimable task (respecting `depends_on`, locks, and priority) with its effort estimate and blockers. The manual equivalent is "scan `tasks/index.yml` for the first `open` task whose dependencies are all `done`."
- **`/plan-review`** — an on-demand adversarial pass over any plan — one sketched in conversation, a file, or a task body — using the same template `/claim-task` runs internally (`_shared/adversarial-review.md`): findings classified `fixable`/`blocker`, external SDK/framework calls with no in-repo precedent flagged `unverified` (Phase 58a), and — when every finding is `fixable` — a revised plan presented for approval before anything executes. **Any `blocker` halts instead**, per the rubric's halt arm: the plan is not revised, `ExitPlanMode` is not called, and the question goes to the human, because a `blocker` is by definition a finding no agent can resolve. Reach for it when you want the plan critique without the claim/lock/worktree machinery.
- **`/sitrep`** — surveys the whole Sysop surface (locks, worktrees, branches, index entries, review batches) and reports where each task sits in the lifecycle, with one top routing recommendation. Read-only.
- **`/roadmap`** — reads the queue back at portfolio level: where the project stands against `tasks/vision.md`, the outstanding work grouped by kind (feature / data-ops / infra) with readiness flags, and one to three proposed orderings of attack (unblock-the-human-first / foundation-first / ship-fast) with the trade-off behind each — each closing with a copy-pasteable `Run it:` actuator line (`/auto-build <IDs>` / `/claim-task <ID>`) so an ordering is a handoff, not just advice. The judgment sibling of `/sitrep` — `/sitrep` classifies what's *in flight now*; `/roadmap` strategizes what's *left*. Read-only; the demo beat between `/intake` (populate the queue) and `/auto-build` (execute it).
- **`/daily-summary`** — the backward-looking retrospective: a git-log-driven standup/async report of the most recent working day (commits classified by type, enriched from changelog/status docs, cross-referenced with tasks closed that day) plus a past-week roundup (activity heatmap, key themes, milestones). `--date` / `--days` / `--week-only` / `--yesterday-only` flags; weekend/gap-aware. Read-only. Where `/roadmap` answers "what's left," `/daily-summary` answers "what happened" — together they cover a human's two standing questions about a project.
- **`/test-audit`** — a standing, read-only survey of test *quality*, not execution state: where load-bearing surfaces (guards, error paths, boundaries, security/data-integrity, parsers) lack tests, and which existing tests have gone dead, redundant, or hollow. The complement to the coverage gate, which is diff-scoped by design (only *changed* crown-jewel lines) — `/test-audit` finds the standing/unchanged gaps the gate can't see. Judgment-led (`_shared/test-assessment-rubric.md`), crown-jewel-first, `--path` / `--all` / `--tier1` / `--tier2` flags. Recommends tests and retirements; never writes tests or mutates the queue — routes accepted recommendations to `/intake`.
- **`/triage`** — classifies pending review batches as `auto` (mechanical, safe to fix unattended) or `flag` (needs judgment) and persists the verdict to `review_tasks.md`. It's the prerequisite for the `/auto-fix` and `/auto-judge` batch processors.
- **`/report-issues`** — the transport half of the friction log: renders each `Open`/`Prompt-ready` entry in `sysop/SYSOP_ISSUES.md` as a GitHub issue, files the ones you consent to (per-entry) against the configured upstream repo, and flips each filed entry to `Filed to Sysop` with its issue URL. **All three give-back skills resolve that target the same way** (Phase 147): `--repo` beats `<project>/CLAUDE.md § Sysop upstream repo`, which beats the shipped default — and the shipped default is the **public** `getsysop/sysop`. They probe the resolved target's visibility and warn before filing security-sounding content somewhere public, but the warning never redacts; per-item consent stays the real gate. Dry-run by default; `--execute` to file. GitHub-specific (shells `gh`); the second skill in the `pr-*`/reporting family after `/pr-dependabot`.
- **`/contribute-convention`** — the give-back half of "grow your own pack from real use": reads the conventions this project promoted locally (the never-managed `.claude/*.project.*` overlay), **strips project fingerprints down to placeholder vocabulary**, surfaces each rule's cross-round provenance, groups them into one proposal per target pack, and files them upstream to the configured upstream repo as `pack_or_convention` issues — per-pack consent, dry-run by default, `--execute` to file. The convention sibling of `/report-issues` (which transports friction); the third GitHub-touching skill in the family.
- **`/share-wins`** — the positive-signal half of the give-back loop: reads the `[good]` entries in `sysop/SYSOP_ISSUES.md` (what Sysop did notably well, worth *protecting from a future change*), and shares the ones you consent to (per-entry) as **one aggregated comment** on a standing "Wins" Discussion in the configured upstream repo — then flips each shared entry to `Status: Shared` with a back-ref so re-runs never double-post. Dry-run by default; `--execute` to post. The only skill in the family that posts to **GitHub Discussions** (via `gh api graphql`) rather than the issue tracker — a win is "don't regress this," not tracked work. The wins sibling of `/report-issues` (friction) and `/contribute-convention` (conventions).
- **`/release`** — the release-authoring layer above per-batch `/review-close`: bundles the many merges since the last git tag into a proposed semver bump (inferred from conventional-commit types), a Keep-a-Changelog `CHANGELOG.md` entry, an annotated git tag, and — opt-in via `--github-release` — a GitHub Release. Reuses `/daily-summary`'s commit classifier and joins `tasks/index.yml` for task-title-enriched highlights. **Write-side and human-gated** (the sibling of `/review-close`, not the read-only family): dry-run by default, `--execute` writes the changelog + creates/pushes the tag, and the public Release is a second opt-in. Version source is tag-first, manifest read-only — it never rewrites `package.json`/`pyproject.toml`. Deliberately lightweight — staged rollout / canary / rollback are the ops band Sysop holds the line on.

## When to use `/auto-build`

`/auto-build` is the optional parallel-batch orchestrator (see WORKFLOW.md § 2.4b). Invoke when you have ≥ 2 independently-claimable tasks in your current-focus phase and want to walk away while a batch executes.

The orchestrator picks the batch (effort × `blast_radius` weights under a K=12 sum ceiling, max N=4 tasks, up to two cross-module tasks). Pass explicit task IDs — `/auto-build FEAT-A TECH-B`, e.g. the `Run it:` line a `/roadmap` ordering emits — to narrow the pool to a chosen subset; the eligibility filters and ceilings still apply, and requested IDs that don't survive them are reported with per-ID reasons, never silently dropped. It then pre-claims each task on `main`, then per task fans out plan-only → adversarial-reviewer → execution Opus sub-agents at the orchestrator layer (the orchestrator does all fan-out itself — a deliberate flat-hierarchy design; see `_shared/adversarial-review.md` § "Harness constraint"). Tasks that the orchestrator's classification step marks as `blocker` are parked with their plan + verdict written to `<worktree>/sysop/runtime/auto-build/` for the human to resume. Tasks classified `fixable` continue to execution; each execution agent invokes `/document-work --non-interactive` to commit + write pending docs but does NOT push. The orchestrator prints a status table when done; the human runs `/review-close` on each EXECUTED branch to merge.

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
