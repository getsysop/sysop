# Configuring and customizing Sysop

Everything the installer writes sorts into three tiers on `--update` (update mechanics in [docs/install-and-update.md](./install-and-update.md)): **fully managed** — regenerated or overwritten every update (skills, workflow docs, the assembled base maps); **preserve-if-modified** — `sysop/scripts/*` and `sysop/scripts/hooks/*`, where your hand-edits survive automatically (Phase 24b, covered there); and **never-managed** — consumer-owned files the installer reads but never writes. Each tier has a matching customization surface. Rule of thumb: *behavior in `CLAUDE.md`, config in an overlay file, shipped skill bodies stay upstream-owned.* The customization surfaces on this page are identical in both [install modes](./install-and-update.md#install-modes-full-and-loop) — a [loop-mode](./loop-mode.md) install customizes through exactly these files, though examples naming lifecycle skills (guided mode's decision gates, a `/review-close` rule) apply only to full installs.

## Behavior — `CLAUDE.md` prose

Your project's `CLAUDE.md` is always in context, and every Sysop skill honors it. A section like `## Guided mode` (WORKFLOW.md § 6.1) changes how every skill handles decision gates without touching a single skill file — and the same pattern works for any standing per-project rule ("when running `/review-close`, also check the staging deploy"). This is the sanctioned way to change how a skill *behaves*, and it survives every update because `CLAUDE.md` is yours.

Several sections are read as structured input rather than prose. Seven are pure configuration — all optional, each consumed by a named skill (six by the lifecycle, one by the give-back family):

| Section | Effect |
|---|---|
| `## Merge policy` | `direct` (default) or `pr` — how `/review-close` lands work on `main`. Use `pr` when `main` is push-protected. |
| `## Second reader` | Who reviews a `/review-close --request-review` close's PR before `--land` merges it: a GitHub login, a `format` (`codex` or `approval`), the `request` comment that asks, a `timeout`, and for Codex the `blocking` severities. Only those two flags read it, and they need `## Merge policy: pr`. |
| `## Unattended close class` | Which branches `/review-close --request-review --agent <name>` closes: `allow:` and `exclude:` path globs and a `blast_radius:` ceiling. `CLAUDE.md`, `.claude/`, `sysop/` and `.github/workflows/` are always excluded, as are `manual_smoke`, `solo` and held tasks. A human still lands the result; merging with no human is not enabled. |
| `## Plan review` | `always`, `never`, or `ask` (default) — how much you are in the loop on a `/claim-task` claim. `always` puts a human gate between the adversarial plan review and implementation; `never` runs it unattended. The plan is adversarially reviewed either way; this only changes what happens after. `--review-plan` / `--no-review-plan` / `--plan-only` override it per run. |
| `## Sysop upstream repo` | A bare `owner/name` slug naming where the give-back skills (`/report-issues`, `/contribute-convention`, `/share-wins`) file. Default is the **public** `getsysop/sysop`; set it if your friction log or convention overlay carries anything that shouldn't land in a public repo. `--repo` stays the per-run override. |
| `## Post-deploy verification` | A smoke command `/review-close` runs *after* the merge lands — a Playwright run against staging, a curl on a health endpoint, a synthetic monitor check. Absent → the step is a no-op. |
| `## Pending documentation routing` | Where `/auto-build` consolidates the per-task pending-docs it accumulates across a batch, so a multi-task run doesn't hand you a pile of unrouted fragments. |

Templates are in WORKFLOW.md § 6.1, which also documents `## Pre-merge verification` (the commands `/review-close` runs before pushing — twice, as a cheap pre-merge pass on `main` and again on the merged tree, which is the run that counts), the sections the review/audit skills read as run inputs (`## Scope mapping`, `## Map coverage exclusions`, `## Security-critical always-include files`, `## High-value files for review`) and the `## Guided mode` toggle. The give-back skills additionally check the resolved target's visibility before filing and warn when security-sounding content is headed somewhere public — or somewhere they could not verify.

## Config — never-managed overlay files

Each shipped config has a consumer-owned sibling that survives every update:

| To change | Author this (never touched by `--update`) |
|---|---|
| Conventions / security map / grep checks | `.claude/convention_map.project.md`, `.claude/security_map.project.md`, `.claude/checks.project.yml` (append-point pattern, below) |
| Placeholder paths inside shipped checks | `.claude/substitutions.project.yml` (placeholder substitution, below) |
| Which model runs which skills | `.claude/served_models.local.yml` (below) |

### Project-specific extensions (Phase 24a — append-point pattern)

The three concat-style managed configs regenerate from upstream + pack sources on every `--update`. To add project-specific content that *survives every update*, author a sibling `*.project.<ext>` file:

| Concat target | Consumer suffix file | How it composes |
|---|---|---|
| `.claude/convention_map.md` | `.claude/convention_map.project.md` | text-appended (blank-line separator) |
| `.claude/security_map.md` | `.claude/security_map.project.md` | text-appended (blank-line separator) |
| `.claude/checks.yml` | `.claude/checks.project.yml` | YAML-merged by `checks[*].id` (consumer wins on collision) |

The suffix files are **never written** by the installer and are **never in `managed_paths`** — same protection property as `tasks/index.yml` and `sysop/SYSOP_ISSUES.md`. Author them by hand (or let `/codebase-review` + `/security-audit` Step 9 promote recurring findings into them), commit them normally, and `--update` is incapable of touching them.

> **This table is about durability, not liveness — write both places.** The **review** skills read the **base** files at review time (`.claude/convention_map.md`, `.claude/security_map.md`, `.claude/checks.yml`) — the siblings are merged into the base only at install/update time, so a review round does not see them. (`/contribute-convention` and `/test-audit` *do* read the overlays directly, but they read them as their subject — what this project promoted locally — not as review inputs.) So an overlay-only edit is **durable but inert** — invisible until the next `sysop-update.sh` re-runs the concat. That is why promotion **dual-writes**: the base copy makes the rule live in this round, the overlay copy makes it survive the next update. Retiring a rule has the mirror-image trap — remove it from the overlay, or the next update re-supplies it. Full rules: [`_shared/promotion-write-target.md`](../core/skills/_shared/promotion-write-target.md).

Because these overlay files are where a project's *locally-grown* conventions accumulate, they're also the give-back source: **`/contribute-convention`** reads them, strips your project's fingerprints down to placeholder vocabulary, and files the promotion-grade ones upstream to the Sysop repo as pack/convention proposals (per-pack consent, dry-run by default) — the convention counterpart to `/report-issues`.

**Markdown example** — `.claude/convention_map.project.md`:

```markdown
## `src/parser/**/*.py` — Beancount parsers

- All parsers must use NamedTemporaryFile for atomic writes
- Reject negative amounts in expense postings
```

After `bash sysop/scripts/sysop-update.sh`, `.claude/convention_map.md` ends with `<core+pack content>` then a blank line then the section above.

**YAML example** — `.claude/checks.project.yml` (must be a self-contained YAML doc with top-level `checks:`, NOT a `.fragment`-shaped file):

```yaml
# Project-specific grep checks. Merged into .claude/checks.yml by checks[*].id;
# consumer wins on id-collision with a ⚠ warn line in the install output.
checks:
  - id: project-bean-temp-file
    name: Ledger written without an atomic temp file
    category: correctness
    severity: high
    paths: ["src/parser/"]
    include: ["*.py"]
    pattern: 'open\([^)]*ledger\.beancount[^)]*\bw\b'
    description: Use NamedTemporaryFile + atomic write for ledger updates
    convention: "Atomic writes"
    used_by: [codebase-review]
```

> **Use these field names exactly.** `pattern` is singular, `paths` and `include` are both
> required, and there is no `tier` field — severity is `low` / `medium` / `high` / `critical`,
> and `blocking: true` is the separate flag that fails the run. An entry with unrecognised keys
> **still parses and still validates**, and then matches nothing: a check with no `pattern` and
> no `paths` is a silent no-op, not an error. The full field table is
> [`WORKFLOW.md` § 6.5](../core/companion/docs/WORKFLOW.md).

If a project check declares the same `id` as an upstream check (e.g., to override an upstream check's `severity`, narrow its `paths`, or set `blocking: true`), the installer emits `⚠ id-collision: <id> (consumer overrides upstream)` so the substitution surfaces in the post-update output. The merge is text-level (Phase 55): the colliding upstream entries are removed line-wise and your whole project file is appended verbatim, so comments — including `# OVERRIDE (...):` annotations explaining why an override exists — survive every update cycle. Malformed YAML in the suffix file is a hard install abort.

**pyyaml dependency for `.claude/checks.project.yml`.** If you author a YAML suffix, install pyyaml in the project's venv: `python3 -m venv .venv && .venv/bin/pip install pyyaml`. The installer auto-discovers `<target>/.venv/bin/python3`, then `<target>/venv/bin/python3`, then `python3` on PATH; the first one that can `import yaml` wins. If none can AND the suffix file exists, the install aborts with the same fix-instruction. The markdown suffix files have no pyyaml dependency.

### Placeholder substitution (Phase 25)

Placeholder vocabulary (`<api module>`, `<frontend>`, etc.) appears in pack `checks.yml.fragment` files so packs stay framework-agnostic. Authoring a `.claude/substitutions.project.yml` maps each token to your concrete project path; the installer text-substitutes `paths:` values in the upstream `.claude/checks.yml` body so they resolve on disk and checks actually fire.

Phase 24a's append/merge shape doesn't address the "concretize this placeholder inside an upstream check" case — pack `checks.yml.fragment` files ship `paths:` lists with placeholder tokens (`<api module>/`, `<scripts dir>/`, `<datajobs dir>/`, etc.) so packs stay framework-agnostic, and a grep check whose paths don't resolve on disk scans nothing — the pre-scan reports it `skipped` (`paths unresolved: placeholder globs not yet localized`), not as a clean pass. Tool-stage checks (pyright, tsc, semgrep, lint) scan the whole tree until localized instead. Author `.claude/substitutions.project.yml` to map each token to its concrete project path:

```yaml
substitutions:
  "<api module>": "parsers"
  "<scripts dir>": "scripts"
  "<datajobs dir>": "streamlit_app"
  "<data seed dir>": "data"
  "<tests dir>": "tests"
```

The installer text-substitutes upstream-shipped placeholder text in `paths:` values of `.claude/checks.yml` only (Phase 55 narrowed this from all three concat configs — markdown maps keep their tokens verbatim as documentation), AFTER concat finishes and BEFORE the suffix file (`*.project.<ext>`) is appended. Consumer suffix content stays byte-faithful — literal `<api module>` text in your `.claude/checks.project.yml` is never auto-substituted. Substitution is literal string replacement, not regex.

The substitutions file is consumer-authored, NOT in `managed_paths`, and `--update` cannot touch it — same protection as the Phase 24a suffix files. Author it by hand, commit it normally.

**Granularity: map each token to real *source* dirs, not a package root that contains excluded trees.** The value sweeps everything beneath it into every check using the token — `"<api module>": "pkg"` pulls `pkg/alembic/**` (migrations, vendored code, fixtures) into every scan and manufactures false positives. Either enumerate the actual source dirs, or keep the broad mapping and narrow the affected checks with an `exclude_dir: ["alembic", "migrations"]` override in `.claude/checks.project.yml` (Phase 133 — directory-basename globs at any depth, grep `--exclude-dir` semantics). Since Phase 133 the `paths:` scoping also applies to `semgrep-*`/`pyright-*`/`tsc-*` registry entries (their findings are post-filtered), so a localized `paths:` — or a `paths: ["__disabled_no_op__"]` disable — now works uniformly across all check stages.

**Stale-token report.** After a real-run pipeline finishes, the installer reports any keys in `.claude/substitutions.project.yml` that didn't match any `paths:` value in the regenerated `.claude/checks.yml` — typos (`<api modules>` for `<api module>`), stale entries from a layout change, or keys that only ever matched markdown prose. Real-run only (the substitution itself is dry-run-gated, so dry-run can't tally matches and the report would otherwise false-positive on every key). The output appears before you commit the absorption.

**pyyaml dependency.** Any non-empty substitutions file requires pyyaml (same `pick_python_with_yaml()` helper Phase 24a uses). Install via `python3 -m venv .venv && .venv/bin/pip install pyyaml` if the install aborts complaining about its absence.

## Models

Every skill pins a *role* (`reasoning` / `planner` / `plan-review` / `executor` / `convention-gate` / `mechanical` / `quick`), and `.claude/served_models.yml` maps each role to a model — `reasoning` → Opus by default, and the four roles named after a job follow it. To swap the model behind a role — say, run all the deep-reasoning skills on Claude Fable 5 — one key in `.claude/served_models.local.yml` is enough:

```yaml
roles:
  reasoning: fable
```

**Map every role except `quick` — `reasoning`, `mechanical`, `convention-gate`, `planner`, `plan-review`, `executor` — to one of `opus` / `sonnet` / `haiku` / `fable`, or to the name of another role.** Those roles govern *inline* pins — values a skill body hands to the Agent tool's `model` parameter, which is a closed enum. Mapping any of them to `best`, `inherit`, `opusplan`, a full model id, or a provider-specific id breaks every agent spawn in the skills that role governs, and it breaks them mid-skill at spawn time rather than at install. Adding the value to `served:` does not rescue it: `served:` is Sysop's sunset allowlist, not the harness's enum. `check_skill_models.py` fails loudly on this, and `.claude/served_models.yml` carries an `inline_models:` list you can extend if your harness accepts more. A *frontmatter*-only role (today that is `quick`) is not so constrained — it accepts anything `/model` accepts.

For a value outside the default lists, extend `served:` too, or `check_skill_models.py` fails:

```yaml
roles:
  quick: inherit
served:
  - inherit
```

### Spending less

There is no cheap lever hiding in the default map. `mechanical` and `quick` already resolve to Sonnet and Haiku — they are not the expensive part — and they govern little: on a full install they carry 4 of the 40 pins in the skills tree (`/next-task`, `/sitrep`, and `/auto-fix`'s orchestrator and fix agents — though an `/auto-fix` run that first invokes `/triage`, which pins `reasoning`, finishes that turn on the reasoning model); 2 are `convention-gate`, 9 are the three roles split out for planning, plan review and execution, and the other 25 are `reasoning`. **On a loop-mode install they carry none at all**, because loop mode ships none of those skills; the 8 pins a loop install carries all resolve through `reasoning` — 7 on it directly, and 1, the shared plan-review contract, on a role that follows it.

Either way the money is in `reasoning` and the roles that follow it — and on the one consumer with per-phase spend recorded, it is concentrated in *execution*, not review — 63.7% of it, against 21.8% for planning and 14.5% for review. That is why `executor` is a role of its own. It governs only the agent that implements an already-reviewed plan (`/claim-task` Step 7e and its answers re-run, `/auto-build` Phase 6e), so you can move execution without moving the planner, the plan reviewer, or `/review-close`'s gates. The evidence below covers only Low and Medium tasks. The consumer that ran it plans to keep High and architectural tasks on the reasoning tier, which one `executor` key cannot express: it moves every executor spawn:

```yaml
roles:
  executor: sonnet   # implements a plan a reasoning-tier reviewer already checked
```

**Set that model's effort as well.** A role picks a model, not an effort, and the Agent tool has no effort parameter. Save a level for the executor's model under `modelSettings` in your Claude Code settings: the consumer that ran the A/B below measured each executor running at its own model's saved level, and at the model's default — `medium` for Sonnet 5.5 — when none was saved, while the docs say a subagent's effort defaults to the session's. Save one rather than rely on either. A saved level is read at session start, so save it before the session that runs the executor, and read the level off the transcript rather than assuming it:

```json
"modelSettings": { "claude-sonnet-5-5": { "effortLevel": "high" } }
```

One consumer's A/B of Sonnet 5.5 against Opus 5.5 in the executor seat, on two tasks with adversarially reviewed plans, found the same design at every call site for about two-fifths of Opus's tokens-at-list-price at `high` effort (about a third at `medium`), assuming both arms had the same input/output mix. At `medium` it departed from the reviewed plan once, on the cross-module task, by leaving a required typecheck red, and `high` closed that. The Opus control was still better on smaller points of that task. Two tasks is a smoke test, not a measurement, so the default stays on `reasoning`. One interaction is unmeasured: `/auto-build`'s executor ends by invoking `/document-work`, which pins `reasoning`, and whether that skill's frontmatter pin applies inside a spawned executor has not been checked — if it does, the executor's documentation step runs on the reasoning model.

Sysop ships `reasoning` conservative on purpose and does not recommend a blanket downgrade. If you want that trade anyway, take it explicitly — it moves planning, plan review, judging and the audits along with execution:

```yaml
roles:
  reasoning: sonnet   # cheaper, and shallower where it matters most
```

**The role is the unit you can configure**, and four roles were split out of `reasoning` for exactly this reason: `executor` above, `planner` and `plan-review` beside it, and `convention-gate`. `convention-gate` governs two spawns — `/review-close` Step 2b's convention agent, which runs on every target of every close (the security twin beside it is gated on a security-map glob and skips most targets on a stock install), and the `4a-fix` re-check of the close's own fix commit, which runs only on a close that fixed a note — so you can move it without moving the security twin beside it or anything else on `reasoning`:

```yaml
roles:
  convention-gate: sonnet   # the 2b convention agent and the 4a-fix re-check
```

Finer still exists in the skill files themselves — a trailing `<!-- sysop:role=… -->` marker overrides the role for a single pin, which is how `/auto-fix` runs its fix agents on the mechanical tier while its verification pass stays on reasoning. But that marker lives in managed skill text, so reaching a pin that has *no* named role means forking the skill and giving up upstream updates to it. Naming a role, as `convention-gate` and `executor` do, is what turns a marker into a knob you can reach from `served_models.local.yml`.

That split comes from one project over one window, running the stock mapping, and its `fix` and `verify` rows recorded no spend at all — a gap in what that project logged, not a free phase. Read it as a rough shape, not a budget.

Local keys win, updates never touch the file, and sunset fixes keep flowing through the managed default map. The mapping is applied by the install-time resolver — after creating or changing the file, run `bash sysop/scripts/sysop-update.sh` (or `install.sh <target> --update`) to rewrite the skills' pins. (`fable` needs Claude Code ≥ 2.1.170; where a pinned model isn't available, the session silently keeps its current model.)

## Skills — direct edits do not persist, by design

`.claude/skills/**` is fully managed: the next `--update` overwrites your edit. You're warned, not ambushed — a committed edit triggers the pre-overwrite divergence report, an uncommitted one is captured by the pre-update snapshot commit, and either is recoverable from git history — but the edit is not preserved. This is deliberate: a silently-preserved skill edit is a prompt fork that drifts from upstream indefinitely with no pressure to reconcile. If a `CLAUDE.md` rule genuinely can't express what you need, copy the skill directory to a name Sysop doesn't ship (e.g. `.claude/skills/my-review-close/`) — paths outside `managed_paths` are never overwritten or deleted by updates (one deliberate sync survives: a fork that keeps its `<!-- sysop:model-roles … -->` marker still gets its `model:` line updated to your role mapping; strip the marker to freeze that too) — and accept that your fork stops receiving upstream improvements. On the plugin path, skills live in the marketplace cache and refresh on auto-update; there is no in-place customization there — use the bash channel or a project-local copy.

## Optional external commands

A standalone `/simplify` slash command is *not* required to use Sysop. The simplify pass — re-reading in-progress changes against the convention map and fixing reuse/quality issues before commit — is bundled inline as `/document-work` Step 1b. If the consuming project's environment provides a separate `/simplify` slash command, it can also be invoked mid-implementation per WORKFLOW.md § 2.3, but that is purely optional.
