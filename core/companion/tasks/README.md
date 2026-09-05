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
| `/next-task` | `index.yml`, `review_tasks.md`, `sysop/runtime/locks/*.lock` | — (default mode resolves a roadmap task, falling back to the next pending review batch; `--review` surfaces only batches) |
| `/roadmap` | `index.yml`, `vision.md`, `decisions.md`, `review_tasks.md` | — (read-only strategy view: groups both queues' outstanding work by kind + proposes orderings of attack; never mutates) |
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

## Authoring an entry by hand

Copy this shape. It is the reference the installer used to seed into `index.yml` itself — see § *Comments in `index.yml` do not survive* below for why it lives here instead.

```yaml
tasks:
  - id: FEAT-EXAMPLE
    title: "Short human-readable title"
    phase: 1
    status: open                       # open | in_progress | done | deferred
    effort: Medium                     # Low | Medium | High — how much work
    blast_radius: single-module        # single-file | single-module | cross-module | architectural — surface area
    user_action: false                 # true = requires console / credentials / domain reg
    manual_smoke: false                # true = /review-close Step 3c halts for human smoke
    solo: false                        # true = mutates shared state; /auto-build batches it alone
    depends_on: []                     # other task IDs this blocks on
    surfaced_by: []                    # IDs that filed this task (e.g., review findings)
    body: open/FEAT-EXAMPLE.md         # required for open/in_progress/deferred
```

**Copy the fields, not the comments.** The trailing `#` notes above document the field values *for you*; they are not part of the entry. Pasted into `index.yml` they are destroyed by the next write, for the reason in § *Comments in `index.yml` do not survive* below — which is why this template lives here and no longer ships inside the file itself.

**Quote the title.** A YAML plain (unquoted) scalar treats ` #` — space then hash — as the start of a comment, so `title: Fix the widget #define` parses as `Fix the widget`, and the rest is gone at *read* time, before any writer touches the file. The validator sees a valid file and reports no error, because what survives is still a legal title. Quoting is the whole defence: `title: "Fix the widget #define"` round-trips exactly. Anything after a space-hash hits this — issue and PR references, ordinals written with a hash, preprocessor tokens, markdown heading fragments. `phases[].title` has the same exposure.

Two more notes that used to sit in the seed:

- **`schema_version: 1`** keeps `blast_radius:` optional. Bump to `2` once every open/in_progress task declares a value; the validator then enforces its presence. See `schema.md` § Versioning.
- **`phases:`** — exactly one entry must carry `current_focus: true`. `/next-task` anchors on the current-focus phase.

Validate with `python3 sysop/scripts/validate_tasks.py` — it must exit 0.

### Comments in `index.yml` do not survive

`index.yml` is a machine-owned file. Seven code paths rewrite it whole through `yaml.safe_dump` — `/claim-task` Step 4a, `/auto-build` Step 5.1, `claim_task.sh --release`, `claim_task.sh --commit-claim` (Phase 261), `/review-close` Step 4c, `backfill_completed_dates.py`, and `clear_user_action.py` (Phase 237) — and a whole-file dump reproduces the *data*, not the text. On the first write that touches this file, every comment is stripped, quoting is normalised, indentation is rewritten, `|` literal block scalars become quoted folded ones, an anchor that has an alias is renamed (`&base` → `&id001`) while one with no alias is dropped, and a `<<:` merge key is resolved and flattened into the mapping it merged into. The output is a fixed point, so it happens once and then stops changing.

Nothing is lost *in the dump* — every value the parser read is written back, and every reader reads through the same parser. (A value can still be lost earlier, at *read* time: that is the unquoted-title case above, and quoting is its fix.) What does not survive the dump is anything you wrote for a human to read. **Put that here, or in the task's body file, not in `index.yml`.** This is why the reference template above lives in this file: seeded into `index.yml`, it was destroyed by the first whole-file write — `/intake`'s `Write` on a fresh project, the first `/claim-task` otherwise — on every install.

One construct the seed still uses is worth naming, because it is the exception that proves the rule: `phases[].sprint_note` is seeded as a `|` literal block. Its **text** survives, but after the first write it comes back as a quoted folded scalar with a trailing blank line. That is cosmetic and expected; it is not a reason to avoid `sprint_note`.

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
4. Run `python3 sysop/scripts/backfill_completed_dates.py --source-file product_roadmap.md --id-pattern '<your-ID-regex>'` to reconstruct `completed_date` for already-completed (`[x]`) items via git history. Inspect the output for plausibility before accepting.
5. `python3 sysop/scripts/validate_tasks.py` — must exit 0.
6. Delete `product_roadmap.md` (or move it to an archive location). Add a `DEPRECATED.md` pointer if other tooling still references the old path.

Migrating ~10–15 tasks by hand is usually faster than scripting it.

## Schema

See `schema.md` in this directory for the full schema reference and the complete invariant list.

## Why YAML + per-file markdown?

A single-file roadmap drifts on format because schema lives inside the document as English prose. Skills had to parse heuristically and ship fallback rubrics. The hybrid keeps machine-readable metadata in a strictly-validated YAML index and lets prose live in dedicated files where it can grow without bloating the queue view.
