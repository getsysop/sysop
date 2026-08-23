---
name: sitrep
description: Survey the Sysop surface — locks, worktrees, branches, index entries, review batches — and report where each task sits in the lifecycle with a single top routing recommendation. Read-only.
disallowed-tools: Edit, Write, NotebookEdit
---

A read-only situation report across all active Sysop work. Surveys the filesystem + git state (locks, worktrees, `task/*` / `review/*` branches, `tasks/index.yml`, `review_tasks.md`), correlates each artifact against the others, classifies every task into a deterministic lifecycle state, and prints a scannable summary plus a top routing recommendation (which skill to invoke next, and whether to `/clear` first).

> **Structural read-only guard (Phase 54):** the `disallowed-tools` frontmatter (Claude Code 2.1.152+) removes the file-write tools while this skill is active. Partial by design — `Bash` stays allowed for the git/python reads below, so the guard covers the dedicated write tools, not shell redirects. Non-Claude-Code harnesses ignore the key.

Designed for cold-context resumption: run after a restart, after stepping away, or when one parent session needs to know what other sessions are doing without asking each one. **Never mutates state** — no file writes, no lock cleanup, no pushes, no `/triage` invocation (the recommendation is informational; the human or the routed skill is the actuator). The actuators stay `/review-close`, `/triage`, `/auto-fix`, `/auto-judge`, `/auto-build`, `cleanup_worktrees.sh`, and the consumer's hand.

## Pre-flight: Permission Guard

This skill shells out to `git`, `python3`, and reads under `<main-repo>/sysop/runtime/locks/`, `tasks/index.yml`, and `review_tasks.md`. It writes nothing.

Read `.claude/settings.json` (and `.claude/settings.local.json` if present) and confirm `permissions.allow` satisfies:

- `Bash(python3 sysop/scripts/sitrep_survey.py:*)` — the survey script itself, and the skill's **only** Bash call

The skill's git work — `git rev-parse` for git-common-dir resolution, `git log` / `git status` / `git branch` / `git rev-list` / `git worktree list --porcelain` — all happens **inside `sitrep_survey.py`**, as subprocesses of the permitted `python3` call, so none of it binds a Bash rule of its own (the same reasoning `/claim-task` Step 2 applies to `scope_overlap.py`). Even at the Bash layer they would need no rule: read-only forms of `git` are auto-approved in every permission mode. (All six *were* listed as hard requirements until Phase 152, none shipped in the seeded allow-list, and the block ended "Do not proceed" — so an agent following this skill literally hard-stopped `/sitrep` on a fresh install. It went unnoticed for the reason internal tracker #205 gives for its own case: the one consumer exercising the path knowingly overrode the documented gate.)

If the required rule is unsatisfied, stop with the `_shared/permission-guard.md` § Algorithm step 5 message (one-line reason: "read-only survey of active Sysop tasks; shells `git` plumbing + `python3 sysop/scripts/sitrep_survey.py` to classify lifecycle states"). Do not proceed — unless the guard's step 3 mode check applies.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and continue.

## Step 0: Parse Arguments

Parse `$ARGUMENTS` for optional flags:

- **`--json`** — emit the structured classification as JSON to stdout (default is the human-readable text report). Reserved for future orchestrator consumption; if the survey script does not yet support it, fall back to the text report and print a one-line note.
- **`--stale-days N`** — override the abandoned-claim threshold (default 7 days). Used when investigating a long-paused task that should not yet be flagged.

No positional arguments. `/sitrep` always surveys the entire Sysop surface; per-task investigation is the human's follow-up via `git`/`cat` after seeing the report.

## Step 1: Run the Survey Script

Invoke from the repo root (the script resolves `git rev-parse --git-common-dir` itself, so it works from any worktree):

```bash
python3 sysop/scripts/sitrep_survey.py [--json] [--stale-days N]
```

The script is idempotent and read-only. It exits 0 on a successful survey regardless of how many discrepancies it finds — discrepancies are reported in the body, not via exit code. Exit 1 means the script itself failed (corrupt YAML, missing repo, etc.); surface the error to the human and stop.

## Step 2: Surface the Report

Print the script's stdout verbatim. The report is already formatted for direct human consumption — do NOT re-summarize or paraphrase; the human is reading the same screen as you and re-summarization adds latency without adding signal.

After the verbatim report, add one closing line:

```
Read-only survey — no state changed. Actuators: /review-close, /document-work, cleanup_worktrees.sh, manual git.
```

## Step 3: Offer Next Action (optional)

The report's `RECOMMENDED NEXT` block (Phase 44+) names the single highest-priority next move (e.g., `→ /review-close TECH-0015`, `→ /triage`, `→ /auto-judge`). You may ask the human whether to proceed with it. Do NOT proceed without explicit confirmation — the survey is meant to inform, not actuate. The recommendation is also surfaced in `--json` output under `recommended_next` for orchestrator consumption.

## Recommendation routing rules (reference)

The `RECOMMENDED NEXT` block applies a priority cascade — first match wins:

| Priority | State                                                                  | Recommendation                                                       | /clear nudge |
| -------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------- | ------------ |
| 1        | Any task `ready for /review-close`                                     | `/review-close <ID>`                                                 | no           |
| 2        | Any review batch with all tasks Doc-Work'd, **or header status `Review Ready`** | `/review-close (batch N)`                                            | no           |
| 3        | Any task `doc-work done, unpushed`                                     | `/review-close <ID>`                                                 | no           |
| 4a       | Pending unclaimed batches exist, ≥1 lacks a `> **Triaged:**` record    | `/triage` (with sample of untriaged batch numbers; names how many carry an unstamped `Flag:` tag) | no           |
| 4b       | Pending unclaimed batches all triaged, mix of auto + flag              | `/auto-fix` (concurrent with `/auto-judge`)                       | yes          |
| 4c       | Pending unclaimed batches all triaged, flag-only                       | `/auto-judge`                                                        | yes          |
| 4d       | Pending unclaimed batches all triaged, auto-only                       | `/auto-fix`                                                       | yes          |
| 5        | Any task `in progress`                                                 | `continue work or /document-work <ID>`                               | no           |
| 6        | Any task `planning`                                                    | `resume planning for <ID>`                                           | no           |
| 7a       | No active work, **> 4** open roadmap tasks (deeper than one `/auto-build` batch) | `/roadmap` (strategy view: group + order before batching; with sample of open IDs) | no           |
| 7b       | No active work, **1–4** open roadmap tasks (fits one batch)            | `/auto-build` (with sample of open IDs)                             | yes          |
| 8        | Truly idle (no work, no roadmap)                                       | none — block reads `(idle …)`                                        | no           |

The `/clear` nudge fires on every recommendation that spawns parallel/Opus agents (`/auto-fix`, `/auto-judge`, `/auto-build`). It is intentionally always-on for those skills because `sitrep` cannot see the caller's context size and the cost of an unneeded nudge is small.

### Why `/sitrep` does not auto-invoke `/triage`

**Priority 2's `Review Ready` arm is computed by the script, from the raw `review_tasks.md` headers** (Phase 222, Q-014): `sitrep_survey.py` filters to `Pending`/`In Progress` before building `review_batches` (and the `--json` payload `/roadmap` reads — that contract is unchanged), so a `Review Ready` batch never enters that list. The survey therefore carries the live-status batches on their own field (`review_ready_batches`, read from the raw headers) and `_recommended_next`'s P2 arm fires on it first — the cascade table above documents what the script computes, not an instruction to re-derive it by hand (Step 2's print-verbatim rule stands). Do not confuse it with the near-identical *terminal* status `Ready for Review` (a finished batch, no recommendation).

When pending batches lack a `> **Triaged:**` record, `/sitrep` recommends `/triage` but does not run it. (Routing on the `Triaged:` record rather than on `Flag:`-tag presence is what lets 4a distinguish "classified as auto" from "never read" — as `Flag:`-keyed states, those were the same state, so an all-auto queue re-recommended `/triage` on every run.) The read-only property is worth defending: `/sitrep` is meant to be safe to invoke reflexively when cold-resuming, with no risk of "did that just write something?" The extra keystroke to run `/triage` after `/sitrep` is cheap; the violated invariant is not.

## Classification states (reference)

The survey script classifies each discovered task into exactly one state. Listed here so consumers reading the output know what each label means:

| State | Deterministic signal |
|---|---|
| **Claimed, no branch** | Lock present at `<git-common-dir>/sysop/runtime/locks/<TASK_ID>.lock`; no matching `task/*` or `review/*` branch exists |
| **Planning** | Lock + branch present; branch has 0 commits ahead of main |
| **In progress** | Branch has ≥1 commits ahead of main; no commit on the branch carries a `Doc-Work:` trailer |
| **Code committed, docs pending** | At least one commit carries `Doc-Work: <TASK_ID>` but **no pending-doc exists** for the branch — the normal terminal state of `/claim-task`'s build pipeline, whose executor emits the trailer without running `/document-work` |
| **Ready for `/review-close`** | At least one commit ahead of main carries `Doc-Work: <TASK_ID>`, a pending-doc exists for the branch, and the branch is pushed to origin |
| **Doc-work done, unpushed** | As above with a pending-doc present; local ahead of `origin/<branch>` (or no upstream tracked) |
| **Stale** | Lock or worktree exists, no commit activity in ≥ `--stale-days` (default 7); flagged as a candidate for human triage |

> **The trailer is not by itself a record that `/document-work` ran (`Q-019`).** It was a
> proxy for that, and stayed true only while `/document-work` was its sole emitter. Since
> Phase 171 `/claim-task` Step 7e's executor emits `Doc-Work: <CLAIM_ID>` from its own
> commit, so a branch where documentation was written and one where it was skipped became
> indistinguishable to this survey — which then routed the operator past `/document-work`
> while `/claim-task`'s own final report told them to run it. The two states are separated
> by the presence of the pending-doc `/document-work` Step 3 writes. `/auto-fix` and
> `/auto-judge` write one too, and `/auto-build` writes one via `/document-work
> --non-interactive` — so the signal is not "only one skill writes the doc" but that the
> doc and the `Doc-Work:` trailer have **disjoint producers**: none of those three emits
> the trailer, and the state requires both. It is looked up in the branch's **workspace**, not on the
> branch: `sysop/runtime/` is gitignored, so the file is never committed and a git-side
> read would report it absent for every branch alike. Workspace resolution mirrors
> `/review-close` Step 0's three arms (git-listed worktree → the lock's recorded
> `workspace:` → the conventional sibling directory), because a `--clone` claim is listed
> by no worktree and a `--clone` without `--lock` is recoverable by neither of the first two.

The `Doc-Work:` trailer landed in Phase 40 — pre-Phase-40 commits do not carry it and would misclassify as "in progress." The survey script applies a one-time fallback: if a commit's subject matches `<type>: ... (<TASK_ID>)` AND the branch is tracking `origin/<branch>` AND there are no later commits, treat as "ready for `/review-close`" with a `~` marker on the state to flag the heuristic. This fallback applies only to commits older than the Phase 40 commit; the survey script reads its own embedded `PHASE_40_COMMIT` constant for the cutoff. Remove this fallback once all in-flight pre-Phase-40 branches close out.

## Discrepancy categories (reference)

The survey flags every mismatch between filesystem reality and the state files. Each discrepancy is paired with a suggested investigation, never an automated action:

| Discrepancy | Detection | Suggested investigation |
|---|---|---|
| Stale lock | Lock exists, no worktree on disk | Investigate, then `rm <lock-path>` if dead |
| Orphan worktree | Worktree exists, no matching lock | Check uncommitted work, then `git worktree remove` |
| Orphan branch | `task/*` or `review/*` branch with no lock + no index entry | Investigate, delete if dead |
| Index drift (in_progress without lock) | `tasks/index.yml` says `in_progress`, no `sysop/runtime/locks/<id>.lock` | Resync index or recreate lock |
| Abandoned claim | Lock + worktree exist, no commits + claimed ≥ stale-days ago | Confirm dead with human, release lock |
| Uncommitted work in stale worktree | Dirty status + no commits in N days | DO NOT cleanup — likely user's parked work |
| Abandoned review round | `sysop/runtime/pending-rounds/*.pending` older than 2h | Re-run the skill; delete the marker only once the round is confirmed dead |

## Deferred features

- **`--cleanup-stale`** — actuate cleanup based on discrepancies. Deferred until classification accuracy is validated across 2–4 weeks of real use.
- **`--task <TASK_ID>`** — drill into a single task's full state (lock contents, plan file, commit log, etc.). Deferred; today's report renders the per-task summary, and the human reads individual files for detail.
- **Telemetry log** — append each invocation's classification + timestamp to `.sitrep.log` for trend analysis. Deferred until eyeballing the printed output proves insufficient.
