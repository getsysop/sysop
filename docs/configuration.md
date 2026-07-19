# Configuring and customizing Sysop

Everything the installer writes sorts into three tiers on `--update` (update mechanics in [docs/install-and-update.md](./install-and-update.md)): **fully managed** — regenerated or overwritten every update (skills, workflow docs, the assembled base maps); **preserve-if-modified** — `sysop/scripts/*` and `sysop/scripts/hooks/*`, where your hand-edits survive automatically (Phase 24b, covered there); and **never-managed** — consumer-owned files the installer reads but never writes. Each tier has a matching customization surface. Rule of thumb: *behavior in `CLAUDE.md`, config in an overlay file, shipped skill bodies stay upstream-owned.* The customization surfaces on this page are identical in both [install modes](./install-and-update.md#install-modes-full-and-loop) — a [loop-mode](./loop-mode.md) install customizes through exactly these files, though examples naming lifecycle skills (guided mode's decision gates, a `/review-close` rule) apply only to full installs.

## Behavior — `CLAUDE.md` prose

Your project's `CLAUDE.md` is always in context, and every Sysop skill honors it. A section like `## Guided mode` (WORKFLOW.md § 6.1) changes how every skill handles decision gates without touching a single skill file — and the same pattern works for any standing per-project rule ("when running `/review-close`, also check the staging deploy"). This is the sanctioned way to change how a skill *behaves*, and it survives every update because `CLAUDE.md` is yours.

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
    description: Use NamedTemporaryFile + atomic write for ledger updates
    tier: blocking
    patterns:
      - 'open\([^)]*ledger\.beancount[^)]*\bw\b'
    globs:
      - "src/parser/**/*.py"
```

If a project check declares the same `id` as an upstream check (e.g., to override `tier: advisory` with `tier: blocking`), the installer emits `⚠ id-collision: <id> (consumer overrides upstream)` so the substitution surfaces in the post-update output. The merge is text-level (Phase 55): the colliding upstream entries are removed line-wise and your whole project file is appended verbatim, so comments — including `# OVERRIDE (...):` annotations explaining why an override exists — survive every update cycle. Malformed YAML in the suffix file is a hard install abort.

**pyyaml dependency for `.claude/checks.project.yml`.** If you author a YAML suffix, install pyyaml in the project's venv: `python3 -m venv .venv && .venv/bin/pip install pyyaml`. The installer auto-discovers `<target>/.venv/bin/python3`, then `<target>/venv/bin/python3`, then `python3` on PATH; the first one that can `import yaml` wins. If none can AND the suffix file exists, the install aborts with the same fix-instruction. The markdown suffix files have no pyyaml dependency.

### Placeholder substitution (Phase 25)

Placeholder vocabulary (`<api module>`, `<frontend>`, etc.) appears in pack `checks.yml.fragment` files so packs stay framework-agnostic. Authoring a `.claude/substitutions.project.yml` maps each token to your concrete project path; the installer text-substitutes `paths:` values in the upstream `.claude/checks.yml` body so they resolve on disk and checks actually fire.

Phase 24a's append/merge shape doesn't address the "concretize this placeholder inside an upstream check" case — pack `checks.yml.fragment` files ship `paths:` lists with placeholder tokens (`<api module>/`, `<scripts dir>/`, `<datajobs dir>/`, etc.) so packs stay framework-agnostic, and `run_checks_impl.py` silently returns empty when those don't resolve on disk. Author `.claude/substitutions.project.yml` to map each token to its concrete project path:

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

**Stale-token report.** After a real-run pipeline finishes, the installer reports any keys in `.claude/substitutions.project.yml` that didn't match any `paths:` value in the regenerated `.claude/checks.yml` — typos (`<api modules>` for `<api module>`), stale entries from a layout change, or keys that only ever matched markdown prose. Real-run only (the substitution itself is dry-run-gated, so dry-run can't tally matches and the report would otherwise false-positive on every key). The output appears before you commit the absorption.

**pyyaml dependency.** Any non-empty substitutions file requires pyyaml (same `pick_python_with_yaml()` helper Phase 24a uses). Install via `python3 -m venv .venv && .venv/bin/pip install pyyaml` if the install aborts complaining about its absence.

## Models

Skills pin *roles* (`reasoning` / `mechanical` / `quick`), and `.claude/served_models.yml` maps each role to a model — `reasoning` → Opus by default. To swap the model behind a role — say, run all the deep-reasoning skills on Claude Fable 5 — one key in `.claude/served_models.local.yml` is enough:

```yaml
roles:
  reasoning: fable   # or `best`: Fable 5 where your org has access, else latest Opus
```

Local keys win, updates never touch the file, and sunset fixes keep flowing through the managed default map. The mapping is applied by the install-time resolver — after creating or changing the file, run `bash sysop/scripts/sysop-update.sh` (or `install.sh <target> --update`) to rewrite the skills' pins. (`fable` needs Claude Code ≥ 2.1.170; where a pinned model isn't available, the session silently keeps its current model.)

## Skills — direct edits do not persist, by design

`.claude/skills/**` is fully managed: the next `--update` overwrites your edit. You're warned, not ambushed — a committed edit triggers the pre-overwrite divergence report, an uncommitted one is captured by the pre-update snapshot commit, and either is recoverable from git history — but the edit is not preserved. This is deliberate: a silently-preserved skill edit is a prompt fork that drifts from upstream indefinitely with no pressure to reconcile. If a `CLAUDE.md` rule genuinely can't express what you need, copy the skill directory to a name Sysop doesn't ship (e.g. `.claude/skills/my-review-close/`) — paths outside `managed_paths` are never overwritten or deleted by updates (one deliberate sync survives: a fork that keeps its `<!-- sysop:model-roles … -->` marker still gets its `model:` line updated to your role mapping; strip the marker to freeze that too) — and accept that your fork stops receiving upstream improvements. On the plugin path, skills live in the marketplace cache and refresh on auto-update; there is no in-place customization there — use the bash channel or a project-local copy.

## Optional external commands

A standalone `/simplify` slash command is *not* required to use Sysop. The simplify pass — re-reading in-progress changes against the convention map and fixing reuse/quality issues before commit — is bundled inline as `/document-work` Step 1b. If the consuming project's environment provides a separate `/simplify` slash command, it can also be invoked mid-implementation per WORKFLOW.md § 2.3, but that is purely optional.
