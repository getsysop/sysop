---
name: daily-summary
description: Summarize yesterday's work in detail and the past week's highlights for standups and async updates — a git-log-driven retrospective, cross-referenced with completed tasks. Read-only reporting; the backward-looking sibling of /roadmap's forward-looking strategy view.
argument-hint: "[--date YYYY-MM-DD] [--days N] [--week-only] [--yesterday-only]"
model: opus
disallowed-tools: Edit, Write, NotebookEdit
---
<!-- sysop:model-roles frontmatter=reasoning -->

Generate a standup-ready report: a detailed breakdown of the most recent working day plus a high-level retrospective of the past week. Driven by `git log`, cross-referenced against completed tasks in `tasks/index.yml`, and enriched from any changelog/status docs the project keeps. Useful for daily standups, async team updates, and personal journaling.

> **Structural read-only guard (Phase 54):** the `disallowed-tools` frontmatter (Claude Code 2.1.152+) removes the file-write tools while this skill is active. Partial by design — `Bash` stays allowed for the read-only `git log` and `date` calls below, so the guard covers the dedicated write tools, not shell redirects. Non-Claude-Code harnesses ignore the key. This skill mutates nothing: it reads history and prints a report.

## Not `/roadmap` or `/sitrep`

These three read the same project through three different time horizons; `/daily-summary` is deliberately **not folded into** the others.

- **`/daily-summary`** looks **backward** — "what happened over the last day / week?" It reads *git history* + closed tasks and produces a human-facing retrospective narrative. Use it for a standup or an async update.
- **`/roadmap`** looks **forward** — "what's left, and in what order do I attack it?" It reads the *open backlog* and proposes orderings. Together, `/daily-summary` + `/roadmap` answer a human's two standing questions about any project: *what did I do* and *what's left*.
- **`/sitrep`** looks at the **present** — locks, worktrees, `task/*` / `review/*` branches — and deterministically classifies what is **in flight right now**. `/daily-summary` doesn't touch execution state; it reports completed history.

## Pre-flight: Permission Guard

**No new permission rules; no Step 0 guard.** Every operation this skill performs is read-only: `git log` (and read-only pipe tools like `wc` / `sort`), `date` arithmetic, and `Read` on `tasks/index.yml` and any changelog/status docs. Per `_shared/permission-guard.md` § Notes, read-only ops are auto-approved under `auto` mode and are **not** listed as allow-rules. It runs no scripts and writes nothing. It is portable to any git-backed project on any agent.

## Step 0 — Parse arguments

Parse `$ARGUMENTS` for flags:

- `--date YYYY-MM-DD` — override "yesterday" with a specific target date.
- `--days N` — override the week-lookback window (default 7). The window is inclusive of the target day, so `N` covers the `N` days before `TARGET_DATE` plus `TARGET_DATE` itself.
- `--week-only` — skip the detailed yesterday section; show only the weekly retrospective.
- `--yesterday-only` — skip the weekly retrospective; show only yesterday's detail.
- No flags → show both sections.

## Step 1 — Determine the date range

Sysop consumers run on both macOS (BSD `date`) and Linux (GNU `date`), which disagree on date arithmetic. Use these portable helpers — **BSD form first (`-v` / `-j -f`), GNU form as the fallback (`-d`)** — the same BSD→GNU pattern `claim_task.sh` uses (Phase 50). Whole-day arithmetic is cleanly expressible in both, so no third (epoch) fallback is needed here:

```bash
# print YYYY-MM-DD for N days before today (N default 1 → "yesterday")
_days_ago() { local n="${1:-1}"; date -v-"${n}"d +%Y-%m-%d 2>/dev/null || date -d "${n} days ago" +%Y-%m-%d 2>/dev/null; }
# _date_minus YYYY-MM-DD N → the date N days before the given date
_date_minus() { local d="$1" n="$2"; date -j -v-"${n}"d -f %Y-%m-%d "$d" +%Y-%m-%d 2>/dev/null || date -d "$d -$n days" +%Y-%m-%d 2>/dev/null; }
# _day_name YYYY-MM-DD → Monday..Sunday
_day_name() { local d="$1"; date -j -f %Y-%m-%d "$d" +%A 2>/dev/null || date -d "$d" +%A 2>/dev/null; }
```

If a helper prints nothing (neither `date` variant is present — a system with neither BSD nor GNU `date`), note "date arithmetic unavailable on this system" at the top of the report and continue with the git sections using whatever ranges you can compute; do not fail the whole report.

Compute:

1. `TARGET_DATE` = the `--date` value, or `_days_ago 1` (yesterday).
2. `WEEK_START` = `_date_minus "$TARGET_DATE" N` (N = `--days`, default 7).
3. `DAY_NAME` = `_day_name "$TARGET_DATE"`.

**Weekend / gap handling.** Check whether `TARGET_DATE` has any commits:

```bash
git log --oneline --after="<TARGET_DATE> 00:00" --before="<TARGET_DATE> 23:59:59" | wc -l
```

If zero, scan backward up to 3 days to find the most recent active day, use that as the effective `TARGET_DATE`, and note the shift at the top of the report (e.g., *"No activity on 2026-07-04 (Saturday) — showing Friday 2026-07-03 instead"*). Running on a Monday, this naturally lands on Friday.

## Step 2 — Gather data (run in parallel)

Issue these independent reads in one batch.

**Git — target day:**
```bash
git log --after="<TARGET_DATE> 00:00" --before="<TARGET_DATE> 23:59:59" --format="%h %ad %s" --date=short
git log --after="<TARGET_DATE> 00:00" --before="<TARGET_DATE> 23:59:59" --shortstat --format=""
git log --after="<TARGET_DATE> 00:00" --before="<TARGET_DATE> 23:59:59" --name-only --format=""
```

**Git — week range:**
```bash
git log --after="<WEEK_START>" --before="<TARGET_DATE> 23:59:59" --format="%h %ad %s" --date=short
git log --after="<WEEK_START>" --before="<TARGET_DATE> 23:59:59" --shortstat --format=""
git log --after="<WEEK_START>" --before="<TARGET_DATE> 23:59:59" --name-only --format="" | sort -u
```

**Completed tasks — `tasks/index.yml`** (the source of truth for done/`completed_date`). `Read` the file and, in-model, select tasks where `status: done` and `completed_date` is set, then split into two buckets:

- **Target-day completions:** `completed_date == TARGET_DATE`.
- **Week completions:** `WEEK_START <= completed_date <= TARGET_DATE`.

`completed_date` is an ISO `YYYY-MM-DD` string, so those comparisons are plain lexicographic — no date parsing needed. Build a `phase.number → phase.title` map from the `phases:` list so each completed task can be labelled with its phase. (This mirrors how `/roadmap` reads the same index in-model — no script, no `.venv` dependency, portable.) Per `tasks/schema.md`, `completed_date` is authoritative: `/review-close` writes it on close, and historical rows can be backfilled from git history via `sysop/scripts/backfill_completed_dates.py`.

**Optional enrichment docs** (`Read` if present — tolerate absence): a project changelog (`CHANGELOG.md` / `changelog.md`), a status/progress doc, or a phase log (e.g. `PHASE_LOG.md`). These frequently carry richer descriptions than commit subjects — file impacts, test counts, task IDs. All optional: the report is complete from `git log` + `tasks/index.yml` alone. If a project declares an enrichment/status doc in its `CLAUDE.md`, prefer that; otherwise auto-discover the common names above.

## Step 3 — Classify the target day's commits

Skip this step and Step 4 if `--week-only` was passed (the yesterday-detail section is dropped, so its classification/enrichment work is wasted).

Group commits by conventional-commit prefix:

| Prefix | Category |
|---|---|
| `feat:` | Features |
| `fix:` | Fixes |
| `refactor:` | Refactoring |
| `perf:` | Performance |
| `test:` | Testing |
| `docs:` | Documentation |
| `chore:`, `ci:`, `build:` | Maintenance |
| Other (no recognizable prefix) | Uncategorized |

Extract the scope from a parenthetical when present (`feat(report-issues):` → scope `report-issues`).

**Filtering rules:**

- **Merge commits** (subject starts with `Merge`) — filter out; they aren't discrete work. (Under Sysop's `pr` merge policy the queue squash-merges, so these are rare anyway.)
- **`docs:` commits — judge, don't blindly drop.** Many Sysop consumers pair a docs commit with each code commit (Sysop's own `/document-work` does exactly this), so listing both **double-counts** the work. When you see a clear 1:1 code↔docs pairing, treat the docs commits as *implicit confirmation* of the code work rather than separate line items — but still surface them as a distinct **count** in Stats (`N code + N docs`), so the docs work is visible, not erased. When docs commits stand alone (a docs-only day, or a project with no pairing convention), list Documentation as its own category. Use judgment from the actual commit shape rather than a hardcoded rule.

## Step 4 — Enrich descriptions from the docs

Cross-reference the target day's commits with the Step 2 enrichment sources for richer descriptions than the commit subjects alone:

1. **Changelog / status / phase-log entries dated `TARGET_DATE`** — when one describes a commit's work more fully (files touched, test counts, task IDs), use it as the primary description and fall back to the commit subject otherwise.
2. **Task IDs.** The Step 2 index read already returned every task whose `completed_date == TARGET_DATE`. Cross-reference each commit's task references (project-chosen prefixes — `FEAT-`, `TECH-`, `DATA-`, `FIX-`, `UX-`, …) against that list: a match marks the commit as the closing commit for that task; a task-ID in a commit subject with **no** `completed_date` yet is an in-progress reference — annotate it as such rather than reporting it done.
3. **Notable file classes** — surface any migration files, schema files, or other high-signal changed files that appear in the target day's `--name-only` output (adapt to the project's stack; don't hardcode a `.sql` assumption).
4. **Review tasks** — if `review_tasks.md` exists and its `TASK-N` IDs appear in the day's commits, note how many review tasks were completed.

## Step 5 — Build the weekly summary

Skip this step if `--yesterday-only` was passed. Aggregate across all commits in `WEEK_START → TARGET_DATE`:

1. **Commit statistics** — total commits; code-only count (excluding `docs:`, `chore:`/`ci:`/`build:`, and `Merge`); unique files changed; total insertions / deletions.
2. **Daily activity heatmap** — a text bar chart, one `█` per commit, every day in the range shown even at zero:
   ```
   Tue 06-30: ████████ (8)
   Wed 07-01: ████ (4)
   Thu 07-02: ██████████████ (14)
   Fri 07-03: ██ (2)
   Sat 07-04:  (0)
   ```
   Cap very long bars (e.g. render at most ~30 blocks and append the raw count) so a high-volume day doesn't overflow the line. Use the real weekday for each date (via `_day_name`) — don't hardcode Mon–Fri.
3. **Key themes** — the top 3–5 areas of work by commit frequency, grouped by scope or changed directory. This is the synthesis that makes the report legible; name themes the way a human would in standup, not just "commits to `src/`".
4. **Milestones** — the Step 2 weekly completions (`WEEK_START <= completed_date <= TARGET_DATE`), grouped by phase via the phase-title map, each shown as `<TASK-ID> — <title> (<completed_date>)`.
5. **Notable file classes this week** — migrations / schema / other high-signal files touched.
6. **Review-task progress** — any review-task batches completed during the week (from `review_tasks.md`), if present.

## Step 6 — Output the report

Honor the flags (`--week-only` drops "Yesterday in Detail"; `--yesterday-only` drops "Past Week"). Only render categories/subsections that have entries. A clean shape:

```
# Daily Summary — YYYY-MM-DD (DayName)

## Yesterday in Detail

### Features
- **<title>**: <enriched description, or commit subject>
  `<hash>` — Files: <key files> | <Task ID if any>

### Fixes
- **<title>**: <description>
  `<hash>` — Files: <key files>

### Tasks closed today
- `FEAT-XYZ` — Task title (YYYY-MM-DD) [phase: <phase title>]

### Notable files
- `<path>` — <brief purpose if discernible>

### Stats
- Commits: N code + N docs = N total
- Files changed: N
- Lines: +N / -N

---

## Past Week (MM-DD to MM-DD)

### Activity
Tue 06-30: ████████ (8)
Wed 07-01: ████ (4)
...

### Key Themes
1. **<Theme>** — brief description (N commits)
2. **<Theme>** — brief description (N commits)

### Milestones
**<Phase title>**
- `FEAT-XYZ` — Task title (YYYY-MM-DD)

### Weekly Stats
- Total commits: N (N code, N docs, N chore/merge)
- Files changed: N unique files
- Lines: +N / -N
```

Adapt the shape to the project; omit empty sections.

## Step 7 — Edge cases

Handle these gracefully:

- **No commits on `TARGET_DATE`** → the Step 1 backward scan (up to 3 days) finds the most recent active day; report the actual date used at the top.
- **No commits in the entire week** → print a brief "No activity in the past N days" and skip the report body.
- **Monday execution** → the backward scan naturally lands on Friday (or the most recent active weekday).
- **High-volume day (>15 commits)** → group by area/scope instead of listing every commit; show a count per area and highlight the most significant items.
- **No tasks closed on `TARGET_DATE`** → omit the "Tasks closed today" subsection (a commits-only day — WIP or batch cleanup).
- **`tasks/index.yml` missing or unparseable** → note "Task index unavailable — milestone section skipped" and continue with the git-derived sections. The git history alone still produces a useful report.
- **Not a git repository** → say so plainly and stop; this skill is git-driven and has nothing to report without history.

## Design notes

- **Reasoning role, not quick.** The git-log→classify core is mechanical, but the value is in the **synthesis** — enriching descriptions from docs, naming key themes the way a human would, producing a narrative a standup reader trusts. That is judgment work, in the same class as `/roadmap`, so the skill carries the `reasoning` role. *Revisitable:* a consumer who runs this often and wants lower latency/cost can remap the `reasoning` role (or this skill specifically) to a lighter model via `.claude/served_models.local.yml` (Phase 69) — the role is a stable pin, the model behind it is swappable.
- **Portability.** Everything is read-only and script-free: `git log`, `date` (BSD/GNU), and `Read`. It runs on any git-backed project and any agent, including bash-installer / non-Claude consumers. The only hard dependency is a git history.
- **Why the backward-looking sibling.** Sysop's lifecycle covers plan (`/intake`) → strategize (`/roadmap`) → select (`/next-task`) → execute (`/claim-task`, `/auto-build`) → document (`/document-work`) → review (`/review-close`) → audit (`/codebase-review`, `/security-audit`). Nothing was *retrospective*. `/daily-summary` fills that leg: it turns the trail those skills leave in git + `tasks/index.yml` into a standup-ready narrative, closing the "what happened" gap that was previously ad-hoc chat.
