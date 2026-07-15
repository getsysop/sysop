# Sysop

**Recurring review findings become rules it enforces for you.**

Sysop brings a full team's engineering rigor to one builder and an AI — from first plan to merge. You bring the idea worth building; Sysop brings the discipline. It's a self-improving development workflow, extracted from the GDP Query System project (71 review rounds, 3,298 findings, 78 promoted conventions as of 2026-07).

The workflow defines a complete lifecycle from intent to merge — intake (`/intake` turns a brain-dump or brief into a validated, populated task queue; `/onboard` brings an *existing* project in, drafting the intent layer from your repo's own evidence and importing a `ROADMAP.md`/`TODO.md`/GitHub-issues backlog), task tracking, planning with adversarial review, isolated worktrees, deferred documentation, dual-mode code review (quality + security), and a feedback loop that converts recurring review findings into written conventions consulted automatically on every future task. Conventions don't stay prompt text: the mechanically checkable ones become deterministic checks — grep rules and Semgrep AST rules in a shared registry that also runs a language-server pass (`pyright`/`tsc`) and a diff-coverage gate on the paths you mark critical — enforced identically on every run with no model in the loop, while a false-positive ledger flags stale rules for demotion. It's the difference between advice a model is asked to remember and checks the computer runs. The effect is measurable: as the convention map grew, reviews shifted from critical defects to nits — the evidence is in [the monograph](./docs/workflow.html) (Fig. 7).

Sysop is open because the corpus is the point: every pack convention is a documented, generalized failure mode of an AI coding agent, earned from recurring findings on a real project — and the give-back skills let your project's locally-promoted rules join it (`/contribute-convention` generalizes them to placeholder vocabulary and shows you the exact proposal before anything is filed). Contributions land as issues and are maintainer-authored into the packs under a published [trust policy](./CONTRIBUTING.md#contribution-trust-policy) — convention prose is read by review agents in privileged contexts, so no contribution merges unreviewed. The floor this raises matters most when generation is cheap: the maps and deterministic checks are designed to catch the extra strays a lighter coding model produces, with a stronger reviewer only where judgment is needed (model roles are one config key — see [Customizing Sysop](#customizing-sysop)).

## Quickstart

```bash
git clone https://github.com/getsysop/sysop.git
bash sysop/install.sh /path/to/your/project --packs python,postgres
cd /path/to/your/project && git add .claude/ scripts/ WORKFLOW.md WORKFLOW_GUIDE.md tasks/ SYSOP_ISSUES.md && git commit -m "chore: install Sysop"
```

> **macOS:** the stock `/bin/bash` is 3.2; the installer needs bash 4+. Run `brew install bash` first (Homebrew's bash lands on your PATH ahead of the system one). Windows: run under WSL.

Run without `--packs` for an interactive picker — it detects your stack (`pyproject.toml` → python, `next.config.js` → nextjs-react, and so on) and offers the matches as the default — or pass `--packs auto` to accept the detected set non-interactively. `--dry-run` previews without writing. Claude Code users can additionally install the slash commands as a plugin: `/plugin marketplace add getsysop/sysop` then `/plugin install sysop@sysop`. Full install and update reference below.

**Read next:**
- *Start building* — [`docs/getting-started.md`](./docs/getting-started.md), a hands-on walkthrough from install to your first shipped change (install → `/intake` → `/claim-task` → `/review-close`).
- *Why it's built this way* — [`docs/workflow.html`](./docs/workflow.html), a visual monograph on the lifecycle, the parallel orchestrator, and the convention loop.
- *The process spec* — [`core/companion/docs/WORKFLOW.md`](./core/companion/docs/WORKFLOW.md) (authoritative), [`WORKFLOW_GUIDE.md`](./core/companion/docs/WORKFLOW_GUIDE.md) (human-readable).
- *How it got here* — [`PHASE_LOG.md`](./PHASE_LOG.md), one entry per development phase.

## Status

110 phases shipped; in daily use by its first consumers (BeanRider and the project it was extracted from). Per-phase history and rationale live in [`PHASE_LOG.md`](./PHASE_LOG.md). Layout:

```
sysop/
├── .claude-plugin/marketplace.json    # Claude Code plugin discovery
├── core/                              # always-required
│   ├── .claude-plugin/plugin.json
│   ├── skills/                        # lifecycle skills + pr-* GitHub family
│   └── companion/                     # installer-delivered files
│       ├── scripts/                   # claim_task, run_checks, etc.
│       ├── git-hooks/                 # pre-commit, pre-merge (+ examples/)
│       ├── docs/                      # WORKFLOW.md, WORKFLOW_GUIDE.md
│       ├── convention_map.md          # core conventions (bash, skills)
│       ├── security_map.md            # core OWASP map
│       └── semgrep/                   # README + universal authoring guide
└── packs/                             # opt-in
    ├── python/                        # populated (convention_map, security_map,
    │                                  #   checks.yml.fragment, 3 semgrep rules,
    │                                  #   shared_cli.py)
    ├── postgres/                      # populated (convention_map, security_map,
    │                                  #   checks.yml.fragment, 2 semgrep rules)
    ├── nextjs-react/                  # populated (convention_map, security_map,
    │                                  #   checks.yml.fragment, 4 semgrep rules)
    ├── llm/                           # populated (convention_map, security_map,
    │                                  #   checks.yml.fragment, 1 semgrep rule)
    ├── beancount/                     # populated (convention_map, security_map;
    │                                  #   overlays the python pack)
    ├── streamlit/                     # placeholder (manifest only)
    ├── pandas/                        # placeholder
    ├── kotlin/                        # placeholder
    ├── swift-ios/                     # placeholder
    ├── flutter/                       # placeholder
    └── mcp-server/                    # placeholder
```

The legacy `.claude/` directory has been fully migrated: `convention_map.md` (Phase 2E), `security_map.md` (Phase 2F), `checks.yml` (Phase 2G), and `semgrep/` (Phase 2H) are all distributed into the appropriate packs.

## Installation

Two install paths; they layer rather than conflict.

- **Bash installer** — `bash install.sh <target> --packs python,postgres,nextjs-react`. Delivers project-side files (workflow docs, skills, scripts, git-hook templates, semgrep rules + fixtures, concatenated `convention_map.md` / `security_map.md` / `checks.yml`, **`.claude/settings.json` permission allow-list**, **`.claude/sysop.lock` install manifest**, **`SYSOP_ISSUES.md` friction log at repo root** — seeded fresh-install only, project-owned thereafter; see WORKFLOW.md § 8.2b for the seed-once-never-overwrite contract) into the target project per WORKFLOW.md § 8.2. Applies by default with dirty-tree refusal (`--force` to override); use `--dry-run` to preview. Run without `--packs` for an interactive pack picker (it auto-detects your stack and offers the matching packs as the default); pass `--packs auto` to accept the detected set non-interactively, or `--packs ''` for core only. Requires bash 4+ (Windows: run under WSL — Git Bash may work but its worktree/symlink support is flakier). Git hooks are armed automatically as the final install step; pass `--no-arm-hooks` to opt out (templates still land in `scripts/hooks/`, run `scripts/install_hooks.sh` later). After install, commit the whole Sysop payload: `git add .claude/ scripts/ WORKFLOW.md WORKFLOW_GUIDE.md tasks/ SYSOP_ISSUES.md && git commit -m "chore: install Sysop"` — a `git worktree` (what `/claim-task` creates) only sees *committed* files, so `scripts/` and the workflow docs must be in the tree or later hook/check steps break. Three of those paths are Sysop's **contract files**, worth knowing by name: `.claude/settings.json` is the workflow's contract with the agent harness, `.claude/sysop.lock` is the contract with future `--update` runs, and `SYSOP_ISSUES.md` is your project's queryable record of Sysop signal — pain points and wins alike (`/review-close` Step 7 appends both during cycle close-out; `/report-issues` files the friction worth sending upstream, and `/share-wins` shares the `[good]` wins as a comment on the Sysop repo's Wins discussion — both per-entry, with your review). Then, on whichever machine has the Sysop clone, add `export SYSOP_SRC=/absolute/path/to/sysop` to your shell rc (`~/.zshrc` / `~/.bashrc`) and re-source it — required by `scripts/sysop-update.sh` (the one-line update entry point; see "Updating an existing install" below).
- **Claude Code plugin** — `/plugin marketplace add getsysop/sysop` then `/plugin install sysop@sysop` plus desired packs (e.g., `/plugin install sysop-python@sysop`). Delivers the slash commands with proper namespacing (`/sysop:claim-task`).

### Updating an existing install

Once installed, a project absorbs upstream Sysop changes by running one command from its own repo root (full design and rationale in WORKFLOW.md § 8.2b):

```bash
bash scripts/sysop-update.sh           # apply
bash scripts/sysop-update.sh --dry-run # preview (writes nothing)
bash scripts/sysop-update.sh --force   # skip the pre-update snapshot
```

The shim resolves the consumer root via `git rev-parse --show-toplevel` and the Sysop source via `$SYSOP_SRC` (set once in your shell rc — see the post-install bullet above), then hands off to `bash $SYSOP_SRC/install.sh <consumer-root> --update`. All flags forward verbatim. It is itself a managed path, so improvements to the wrapper flow through the same channel as everything else.

The underlying `--update` mode snapshots any dirty managed paths into a `Sysop: pre-update snapshot` commit, overwrites managed files with this checkout's version, refreshes the lock, and leaves the update uncommitted so you review and commit intentionally; `git diff <snapshot-hash>..HEAD` shows exactly what Sysop changed. If Sysop's reference repo has the previously-installed commit, a pre-overwrite divergence check warns about committed local edits in managed paths; a post-overwrite delta table flags files with significant deletions for follow-up review (see WORKFLOW.md § 8.2b for the warn-then-diff design). `--update` deliberately does **not** auto-arm git hooks (Phase 15 / ISSUE-0007) — `scripts/hooks/*` is overwritten with upstream skeletons but `.git/hooks/*` is left untouched so you can reconcile `scripts/hooks/*` via `git checkout HEAD -- …` before re-arming; an armed-hook divergence check at the end of the run flags any `scripts/hooks/<base>` that differs from `.git/hooks/<base>`. Re-arm with `bash scripts/install_hooks.sh` after reconciling.

Two additional modes (also invoked via `bash <path-to-sysop-clone>/install.sh`, since neither runs from a routine update cadence):

- `bash install.sh <target> --adopt --packs <list>` — one-time backfill for installs that pre-date the lock mechanism. Writes + commits `.claude/sysop.lock` so future `--update` runs work.
- `bash install.sh <target> --check --source <path-to-sysop-clone>` — read-only: reports how many upstream commits affect installable content, without writing anything.

The lower-level invocation `bash <sysop-src>/install.sh <consumer-root> --update [flags]` is what the shim wraps; reach for it directly when you need a Sysop source other than `$SYSOP_SRC` (e.g., a different branch or worktree) or are running outside a consumer git working tree.

Placeholder vocabulary (`<api module>`, `<frontend>`, etc.) appears in pack `checks.yml.fragment` files so packs stay framework-agnostic. Authoring a `.claude/substitutions.project.yml` (Phase 25 — see below) maps each token to your concrete project path; the installer text-substitutes `paths:` values in the upstream `.claude/checks.yml` body so they resolve on disk and checks actually fire.

#### Project-specific extensions (Phase 24a — append-point pattern)

The three concat-style managed configs regenerate from upstream + pack sources on every `--update`. To add project-specific content that *survives every update*, author a sibling `*.project.<ext>` file:

| Concat target | Consumer suffix file | How it composes |
|---|---|---|
| `.claude/convention_map.md` | `.claude/convention_map.project.md` | text-appended (blank-line separator) |
| `.claude/security_map.md` | `.claude/security_map.project.md` | text-appended (blank-line separator) |
| `.claude/checks.yml` | `.claude/checks.project.yml` | YAML-merged by `checks[*].id` (consumer wins on collision) |

The suffix files are **never written** by the installer and are **never in `managed_paths`** — same protection property as `tasks/index.yml` and `SYSOP_ISSUES.md`. Author them by hand (or let `/codebase-review` + `/security-audit` Step 9 promote recurring findings into them), commit them normally, and `--update` is incapable of touching them.

Because these overlay files are where a project's *locally-grown* conventions accumulate, they're also the give-back source: **`/contribute-convention`** reads them, strips your project's fingerprints down to placeholder vocabulary, and files the promotion-grade ones upstream to the Sysop repo as pack/convention proposals (per-pack consent, dry-run by default) — the convention counterpart to `/report-issues`.

**Markdown example** — `.claude/convention_map.project.md`:

```markdown
## `src/parser/**/*.py` — Beancount parsers

- All parsers must use NamedTemporaryFile for atomic writes
- Reject negative amounts in expense postings
```

After `bash scripts/sysop-update.sh`, `.claude/convention_map.md` ends with `<core+pack content>` then a blank line then the section above.

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

#### Phase 25 — placeholder substitution

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

#### Phase 24b — preserve consumer-modified scripts and hooks

For managed scripts and hook templates — where "append" isn't the right shape (you can't add `errors="replace"` to a Python `open()` from a sibling file) — Phase 24b preserves consumer-modified files automatically. Scope is intentionally narrow: `scripts/*` (depth-1) and `scripts/hooks/*` (depth-2). Skills, workflow docs, semgrep rules, and tasks-scaffold templates are explicitly out of scope (silent prompt-forks accumulate divergence with no upstream pressure to reconcile; for those, use CLAUDE.md prose or pack-level extensions).

When you've hand-edited a managed script and committed, the next `bash scripts/sysop-update.sh` reports:

```
── preserved managed paths (Phase 24b) ──

  ↻  scripts/archive_review_tasks.py   (consumer-modified; --accept-upstream to overwrite)
  ↻  scripts/hooks/pre-commit          (consumer-modified; --accept-upstream to overwrite)

  preserved: 2 managed path(s) preserved due to consumer modification.
  Re-run with --accept-upstream <relpath> (repeatable) or --accept-upstream-list <file> to override.
```

The preserved files are NOT touched by the overwrite; the rest of the pipeline runs as normal. Two-pass workflow when you want some of them updated:

```bash
# 1. First run: see what's preserved.
bash scripts/sysop-update.sh

# 2. Inspect the upstream-vs-consumer diff per preserved path:
#    git -C $SYSOP_SRC log --oneline -p <old_commit>..HEAD -- core/companion/scripts/<file>
#    git log --oneline -p -- scripts/<file>

# 3. Take upstream for the subset you want (repeatable, or pass a list file):
bash scripts/sysop-update.sh --accept-upstream scripts/archive_review_tasks.py
# or
echo "scripts/archive_review_tasks.py" > /tmp/accept.txt
echo "scripts/hooks/pre-merge-commit" >> /tmp/accept.txt
bash scripts/sysop-update.sh --accept-upstream-list /tmp/accept.txt
```

The list-file form ignores `#`-comments and blank lines; stale entries (paths that were not actually consumer-modified) surface as a `note: accept-upstream: <relpath> not in preserved set; ignored` line after the pipeline so they don't accumulate silently.

**Fail-closed posture.** If the shadow worktree can't be reconstructed (Sysop source missing the OLD commit, pre-bash-installer anchor, etc.), `--update` aborts in non-`--force` mode rather than silently overwriting your customizations. The error names the three escape hatches: `git fetch` (most common — the lock's commit may simply be missing locally), `--accept-upstream <path>` (take upstream per file), or `--force` (skip preservation entirely). See WORKFLOW.md § 8.2c for the full contract.

**Hook templates.** `scripts/hooks/pre-commit` and `scripts/hooks/pre-merge-commit` are in scope, so consumer-customized hook *bodies* survive `--update` automatically — closing the gap Phase 15 left open (Phase 15 protected `.git/hooks/<base>` armed copies but the upstream pipeline still overwrote the `scripts/hooks/<base>` templates). Re-arming after reconciling remains a Phase 15 contract: `bash scripts/install_hooks.sh` after the update.

#### Plugin path: how updates work

The plugin path delivers slash commands only — and only from the **core** plugin. Inspecting the manifests: `core/.claude-plugin/plugin.json` exposes `./skills/` (the lifecycle slash commands like `/sysop:claim-task`, plus the `pr-*` GitHub family — currently `/sysop:pr-dependabot`, the only skill that shells out to `gh`); every pack plugin (`sysop-python`, `sysop-postgres`, etc.) declares only a `dependencies` list (always including `sysop`; some packs — currently `sysop-postgres`, `sysop-beancount`, `sysop-mcp-server`, `sysop-pandas`, `sysop-streamlit` — also depend on `sysop-python` because their content layers on the python pack: a `companion/checks.yml.fragment` using python-pack-declared placeholders, or, for `sysop-beancount`, convention/security maps that overlay the python pack's baseline) and ships no `skills` / `commands` / `agents` / `hooks` payload of its own. The actual pack value (`convention_map.md`, `security_map.md`, `checks.yml.fragment`, semgrep rules) lives under `companion/` and is referenced by zero plugin manifests. That content reaches a consumer project *only* through the bash installer. A plugin-only install is useful for trying the slash commands out, but a real consumer always runs the bash installer as well so the skills have config to read.

Recommended setup for consumers who want both paths:

1. **Turn on auto-update for the Sysop marketplace.** Third-party marketplaces have auto-update **off** by default in Claude Code. We recommend enabling it for Sysop: toggle via `/plugin` → Marketplaces tab → Sysop → Auto-update, or set `"autoUpdate": true` for Sysop under `extraKnownMarketplaces` in `~/.claude/settings.json`. With auto-update on, Claude Code refreshes the marketplace and pulls the latest commit of every installed Sysop plugin at the start of each session — no other action needed for slash-command updates.
2. **There is no `/plugin update` command.** Updates apply at session start when auto-update is on. To force a check mid-session: `/plugin marketplace update Sysop` refreshes the marketplace's plugin list (catches new packs appearing upstream — e.g., `sysop-flutter` once that pack is populated); follow with `/plugin install <plugin>@sysop` per already-installed plugin to pull the latest commit.
3. **Pinning the plugin path.** Every Sysop `plugin.json` deliberately omits the `version` field, so Claude Code tracks each commit (auto-update on every commit). This is a conscious choice: adding a `version` would *freeze* plugin updates until a manual bump, and Claude Code offers no consumer-side version pin (`install sysop@x.y.z` isn't a thing), so a version field would cost frequent updates without buying a pin. To hold the plugin path at a known state, turn off auto-update for the Sysop marketplace (above) and update deliberately. For a **hard pin to a reviewed release**, use the bash path — `bash install.sh <target> --ref v0.1.0` (or `bash scripts/sysop-update.sh --ref v0.1.0`) installs from a tagged release instead of HEAD. See [SECURITY.md](SECURITY.md) § "How updates reach you — and how to pin".
4. **Reset / recovery.** Installed plugins live at `~/.claude/plugins/cache/`. To force a clean re-pull: `/plugin uninstall <plugin>@sysop` then `/plugin install <plugin>@sysop`.

**Reconciling plugin + bash-installer updates.** When upstream Sysop ships a change, both sides typically move in the same commit: a skill body edit (plugin path) often comes with a matching convention-map or checks.yml change (bash-installer path). The two paths update independently — plugin auto-updates at the next session start; bash-installer changes require an explicit `bash install.sh <target> --update`. Run `--update` whenever you notice a Sysop plugin auto-updated to a new commit; the `--update` snapshot diff + post-overwrite delta table (WORKFLOW.md § 8.2b) show what changed in your project tree.

### Required permissions

The bash installer writes `<target>/.claude/settings.json` with a scoped allow-list for every Bash command the Sysop skills invoke (git merges, worktrees, branch deletes, pushes, scripts in `scripts/`). This file is required when running under Claude Code's `auto` permission mode with `skipAutoPermissionPrompt: true` — without it, skills like `/review-close` silently halt mid-merge when the harness blocks `git merge --ff-only`. The installer merges with any existing `settings.json` rather than overwriting (set-union on `permissions.allow`). See WORKFLOW.md § 8.2a for the rule-by-skill table and the conscious omissions (no `Bash(git *)`, no `git push --force` without lease).

## Customizing Sysop

Everything the installer writes sorts into three tiers on `--update` (detailed under "Updating an existing install" above): **fully managed** — regenerated or overwritten every update (skills, workflow docs, the assembled base maps); **preserve-if-modified** — `scripts/*` and `scripts/hooks/*`, where your hand-edits survive automatically (Phase 24b above); and **never-managed** — consumer-owned files the installer reads but never writes. Each tier has a matching customization surface. Rule of thumb: *behavior in `CLAUDE.md`, config in an overlay file, shipped skill bodies stay upstream-owned.*

**Behavior — `CLAUDE.md` prose.** Your project's `CLAUDE.md` is always in context, and every Sysop skill honors it. A section like `## Guided mode` (WORKFLOW.md § 6.1) changes how every skill handles decision gates without touching a single skill file — and the same pattern works for any standing per-project rule ("when running `/review-close`, also check the staging deploy"). This is the sanctioned way to change how a skill *behaves*, and it survives every update because `CLAUDE.md` is yours.

**Config — never-managed overlay files.** Each shipped config has a consumer-owned sibling that survives every update:

| To change | Author this (never touched by `--update`) |
|---|---|
| Conventions / security map / grep checks | `.claude/convention_map.project.md`, `.claude/security_map.project.md`, `.claude/checks.project.yml` (append-point pattern, above) |
| Placeholder paths inside shipped checks | `.claude/substitutions.project.yml` (placeholder substitution, above) |
| Which model runs which skills | `.claude/served_models.local.yml` (below) |

**Models.** Skills pin *roles* (`reasoning` / `mechanical` / `quick`), and `.claude/served_models.yml` maps each role to a model — `reasoning` → Opus by default. To swap the model behind a role — say, run all the deep-reasoning skills on Claude Fable 5 — one key in `.claude/served_models.local.yml` is enough:

```yaml
roles:
  reasoning: fable   # or `best`: Fable 5 where your org has access, else latest Opus
```

Local keys win, updates never touch the file, and sunset fixes keep flowing through the managed default map. The mapping is applied by the install-time resolver — after creating or changing the file, run `bash scripts/sysop-update.sh` (or `install.sh <target> --update`) to rewrite the skills' pins. (`fable` needs Claude Code ≥ 2.1.170; where a pinned model isn't available, the session silently keeps its current model.)

**Skills — direct edits do not persist, by design.** `.claude/skills/**` is fully managed: the next `--update` overwrites your edit. You're warned, not ambushed — a committed edit triggers the pre-overwrite divergence report, an uncommitted one is captured by the pre-update snapshot commit, and either is recoverable from git history — but the edit is not preserved. This is deliberate: a silently-preserved skill edit is a prompt fork that drifts from upstream indefinitely with no pressure to reconcile. If a `CLAUDE.md` rule genuinely can't express what you need, copy the skill directory to a name Sysop doesn't ship (e.g. `.claude/skills/my-review-close/`) — paths outside `managed_paths` are never overwritten or deleted by updates (one deliberate sync survives: a fork that keeps its `<!-- sysop:model-roles … -->` marker still gets its `model:` line updated to your role mapping; strip the marker to freeze that too) — and accept that your fork stops receiving upstream improvements. On the plugin path, skills live in the marketplace cache and refresh on auto-update; there is no in-place customization there — use the bash channel or a project-local copy.

## Backing out

Everything Sysop writes is a tracked file plus one set of git hooks, so reversing it — a single task claim, or the whole tool — is a clean git operation.

### Reversing a task claim

`/claim-task` does three things: flips the task to `in_progress` in `tasks/index.yml`, takes a lock at `.locks/<TASK-ID>.lock` (under the main repo), and creates a worktree on a feature branch. To reverse all three, run the un-claim flag from the **main checkout** (not from inside the task's worktree):

```bash
bash scripts/claim_task.sh --release <TASK-ID>
#   --delete-branch   also drop the feature branch
#   --force           discard uncommitted work in the worktree (otherwise a dirty
#                     worktree aborts the release with everything left intact)
```

It reads the branch and worktree from the lock, so you supply only the task ID. It removes the worktree (never the main worktree), flips the task's `status:` back to `open`, deletes the lock, runs `validate_tasks.py`, and prints — but does not run — the commit:

```bash
git add tasks/index.yml && git commit -m "chore: release <TASK-ID>"
```

The status flip goes through a PyYAML round-trip, never a hand-edit, so the queue stays validator-clean. If the `python3` on your PATH lacks PyYAML, `--release` stops **before touching anything** and prints the manual reversal to run with your project's python — the same steps by hand:

```bash
git worktree remove <worktree-path>        # add --force if it has uncommitted work you're discarding
git branch -D <feature-branch>             # optional — drop the branch too
rm .locks/<TASK-ID>.lock                   # release the lock
# then flip that task's `status:` from in_progress back to open in tasks/index.yml
.venv/bin/python3 scripts/validate_tasks.py   # confirm the queue is consistent
git commit -am "chore: release <TASK-ID>"
```

Hand-editing `status:` is normally off-limits (`tasks/README.md` rule 2) precisely because it can desync the lock — but doing it in the *same pass* as the lock removal (exactly what `--release` automates) is the sanctioned reversal, and `validate_tasks.py` confirms nothing is left dangling.

### Removing Sysop from your project

Sysop's whole payload is the set you committed as `chore: install Sysop` — `.claude/`, `scripts/`, `WORKFLOW.md`, `WORKFLOW_GUIDE.md`, `tasks/`, `SYSOP_ISSUES.md` (the exact per-file managed-path list is recorded in `.claude/sysop.lock`'s `managed_paths`; see WORKFLOW.md § 8.2b). Because it is all tracked:

- **Revert the install commit** if nothing has touched the payload since — e.g. a fresh install you're immediately undoing: `git revert <install-commit>`. Once you've actually *used* Sysop, later cycles have committed to `tasks/index.yml`, so a revert conflicts there — fall back to deleting the paths instead.
- **Delete the managed paths.** Sysop installs `scripts/` **flat** and *merges* into any existing `.claude/`, so don't blindly `rm -r` those directories if you had your own content there first — remove Sysop's paths selectively, using `managed_paths` in `.claude/sysop.lock` as the source of truth. Where those directories are Sysop-only: `git rm -r .claude scripts && git rm WORKFLOW.md WORKFLOW_GUIDE.md`, then commit. `tasks/` holds both Sysop's scaffold (`schema.md`, `README.md`) and your own planning content (`vision.md`, `decisions.md`, the queue); `SYSOP_ISSUES.md` is your notes — remove or keep those independently.
- **Disarm the git hooks** — the one untracked, unrecoverable surface. `install.sh` copies Sysop's two hooks into `.git/hooks/` (which git never tracks): `rm -f .git/hooks/pre-commit .git/hooks/pre-merge-commit`. Remove only hooks Sysop armed — if you had your own, `install_hooks.sh` backed them up alongside as `*.bak.<timestamp>`.
- **Plugin users:** also `/plugin uninstall <plugin>@sysop` per installed Sysop plugin.

Outside the repo, the only traces are the optional `SYSOP_SRC` line in your shell rc and the Claude Code plugin cache — remove those if you added them.

## Optional external commands

A standalone `/simplify` slash command is *not* required to use Sysop. The simplify pass — re-reading in-progress changes against the convention map and fixing reuse/quality issues before commit — is bundled inline as `/document-work` Step 1b. If the consuming project's environment provides a separate `/simplify` slash command, it can also be invoked mid-implementation per WORKFLOW.md § 2.3, but that is purely optional.

## Support expectations

Sysop is built for my own daily use and published in that spirit. Issues and PRs are welcome and reviewed as time permits — there is no SLA, no roadmap commitment, and no backwards-compatibility guarantee during early development. Plugin manifests stay unversioned by design (every commit is the latest); reviewed checkpoints are cut as tagged releases you can pin to via the bash installer's `--ref` flag (see [SECURITY.md](SECURITY.md)). If it's useful to you, use it and fork freely — it's MIT-licensed.

## Prior art

`/intake`'s brain-dump → playback → sounding-board interaction shape draws on the `interview-me` pattern from [Addy Osmani's agent-skills](https://github.com/addyosmani/agent-skills) collection (MIT-licensed). Sysop's skill is written from scratch for its intent-layer (`tasks/vision.md` + `tasks/decisions.md`) and task-emission model — no prose was copied or paraphrased; the credit is for the conversational pattern.

## Provenance

Extracted from `gdp-query-system` (private) via `git filter-repo` on 2026-04-30; the source commit is tagged there as `wade-flow-extract-base`. The public repository is a fresh-history snapshot of a private development repo — the private history's commit messages and preserved file history reference the production application the workflow was extracted from, and stay private. [`PHASE_LOG.md`](./PHASE_LOG.md) is the public development history; the review-round provenance of individual conventions is carried in the convention maps themselves.
