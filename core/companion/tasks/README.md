# tasks/

Source of truth for the project's task queue. Replaces the single-file `product_roadmap.md` shape that earlier Sysop consumers used.

## How to read the queue

- `index.yml` — at-a-glance view of every task with status, effort, dependencies, and a pointer to the prose body. Skim this when you want to see what's open.
- `open/<TASK-ID>.md` — full prose for an open or in-progress task (Context, Requirements, Key files).
- `deferred/<TASK-ID>.md` — same shape, for parked work.
- `archive/<TASK-ID>.md` — completed tasks that had substantive prose worth keeping.
- `archive/_phase_<N>.md` — summary for a fully-completed phase (no per-task bodies).

## How skills use it

| Skill | Reads | Writes |
|---|---|---|
| `/intake` | `vision.md`, `decisions.md`, `index.yml` | the populated queue itself — `index.yml` + `open/<ID>.md` bodies + the intent layer (`vision.md`, `decisions.md`); leaves it **uncommitted** for human sign-off |
| `/onboard` | consented in-repo evidence (README/docs/manifests/git log), a roadmap/`TODO.md` file or `gh issue list`, `index.yml` (dedup) | for an *existing* project adopting Sysop: drafts `vision.md` + `decisions.md` from evidence (fabrication-guarded — inferred rationales confirmed, never asserted) and/or imports the backlog into `index.yml` + bodies with `surfaced_by: [imported]` provenance; leaves everything **uncommitted**, then hands off to `/intake` for going-forward planning |
| `/add-task` | `index.yml`, `open/` + `deferred/` bodies (dedup), `decisions.md` (contradiction check; tolerates absence) | quick capture of a single task (or 2–3 independent siblings): appends the validated `index.yml` entry + writes `open/<TASK-ID>.md`; never creates phases, never edits existing entries or `status:`, leaves it **uncommitted** — routes phase-shaped thoughts to `/intake` |
| `/next-task` | `index.yml`, `sysop/runtime/locks/*.lock` | — |
| `/roadmap` | `index.yml`, `vision.md`, `decisions.md` | — (read-only strategy view: groups the outstanding queue by kind + proposes orderings of attack; never mutates) |
| `/daily-summary` | `index.yml` (completed tasks for the milestone section), git history | — (read-only retrospective: standup/async report of the last day + week, git-log-driven; never mutates) |
| `/test-audit` | source + test trees, `.claude/checks.yml` (`critical_path:` globs), optional coverage artifact | — (read-only test-quality audit: recommends new tests on load-bearing surfaces + retirements of dead/redundant/hollow tests; routes accepted recs to `/intake`; never writes tests or mutates) |
| `/claim-task <ID>` | `index.yml`, body | flips `status: open → in_progress` in `index.yml`; creates `sysop/runtime/locks/<ID>.lock` |
| `/document-work` | `index.yml`, body | — (verifies referenced IDs exist) |
| `/review-close` | `index.yml`, body | sets `status: done` + `completed_date`; `git mv` body to `archive/` |
| `/release` | `index.yml` (done tasks since last tag → highlights), git history | writes a `CHANGELOG.md` entry (uncommitted) + creates/pushes an annotated tag; optional GitHub Release. Write-side, human-gated, dry-run by default; never rewrites a version manifest |

## Rules

1. **`index.yml` is the source of truth for metadata.** Never duplicate status, effort, or `user_action` as frontmatter in a body file.
2. **Never edit `status:` by hand.** Use the skills. A misedit can desync `sysop/runtime/locks/`, leave a phantom in-progress task, or break `/next-task`. To *un-claim* a task you changed your mind about (`in_progress → open` + release the lock + drop the worktree, in one consistent pass), run `bash sysop/scripts/claim_task.sh --release <TASK-ID>` from the main checkout — the sanctioned inverse of a claim.
3. **`validate_tasks.py` is authoritative.** If you can't get the validator to pass, fix the data — don't bypass the hook.
4. **Adding a task:** run `/add-task` — it appends the `index.yml` entry, writes `open/<TASK-ID>.md`, dedups against the queue, and validates. (By hand is fine too: add the entry + body yourself; the ID must match `^[A-Z][A-Z0-9-]{2,80}$`.)
5. **Renaming a task:** `git mv` the body file AND change `id:` in `index.yml` AND update any `depends_on:` / `surfaced_by:` references. The validator catches stragglers.

## The intent layer (`vision.md` + `decisions.md`)

`/intake` (the planning front door) authors two **consumer-owned** artifacts alongside the queue:

- `vision.md` — the durable *why + what* the project exists to do. Stable; phases and tasks trace back to it.
- `decisions.md` — the *technical-decisions record* (stack/schema/sequencing calls + rationale). This is the planning-side analog of `convention_map.md`: a re-invoked `/intake` checks new decisions against what's already committed here, and flags derived tasks for re-check if the intent has drifted.

Both are authored only by `/intake` (or drafted by `/onboard` when an existing project adopts Sysop) — `install.sh` never creates them, so there is nothing for `--update` to overwrite (protection by absence, not by the skip-if-exists guard `index.yml` gets). They are not managed paths. They live at the `tasks/` root, so the validator's orphan check (which scans only `open/`, `deferred/`, `archive/`) ignores them.

## Migrating from `product_roadmap.md`

If your project still has a single-file `product_roadmap.md`:

1. Scaffold the directory tree: `mkdir -p tasks/open tasks/deferred tasks/archive`.
2. Hand-author `tasks/index.yml` — every phase heading becomes a `phases:` entry; every task becomes a `tasks:` entry.
3. For each open/deferred task, create the per-task body at `tasks/{open,deferred}/<TASK-ID>.md`. The first heading must be `# <TASK-ID>`.
4. Run `sysop/scripts/backfill_completed_dates.py --source-file product_roadmap.md --id-pattern '<your-ID-regex>'` to reconstruct `completed_date` for already-completed (`[x]`) items via git history. Inspect the output for plausibility before accepting.
5. `python3 sysop/scripts/validate_tasks.py` — must exit 0.
6. Delete `product_roadmap.md` (or move it to an archive location). Add a `DEPRECATED.md` pointer if other tooling still references the old path.

Migrating ~10–15 tasks by hand is usually faster than scripting it.

## Schema

See `schema.md` in this directory for the full schema reference and the complete invariant list.

## Why YAML + per-file markdown?

A single-file roadmap drifts on format because schema lives inside the document as English prose. Skills had to parse heuristically and ship fallback rubrics. The hybrid keeps machine-readable metadata in a strictly-validated YAML index and lets prose live in dedicated files where it can grow without bloating the queue view.
