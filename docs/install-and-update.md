# Installing and updating Sysop

The [README Quickstart](../README.md#quickstart) is the short version. This page is the full
reference: both install paths, how updates reach an installed project, pinning to a release,
required permissions, the repo layout, and how to back out. Consumer-side configuration — the
overlay files, placeholder substitution, model roles — lives in
[docs/configuration.md](./configuration.md); the authoritative process spec behind everything
here is [WORKFLOW.md § 8](../core/companion/docs/WORKFLOW.md).

## Two install paths

Two install paths; they layer rather than conflict.

- **Bash installer** — `bash install.sh <target> --packs python,postgres,nextjs-react`. Delivers project-side files (workflow docs, skills, scripts, git-hook templates, semgrep rules + fixtures, concatenated `convention_map.md` / `security_map.md` / `checks.yml`, **`.claude/settings.json` permission allow-list**, **`.claude/sysop.lock` install manifest**, **`sysop/SYSOP_ISSUES.md` friction log** — seeded fresh-install only, project-owned thereafter; see WORKFLOW.md § 8.2b for the seed-once-never-overwrite contract) into the target project per WORKFLOW.md § 8.2. Everything Sysop delivers lands under one visible vendor dir, `sysop/` (Phase 128): `sysop/scripts/`, `sysop/docs/`, `sysop/SYSOP_ISSUES.md`. The only things outside it are `.claude/` (the harness contract), `tasks/` (your backlog), and the `CLAUDE.md` / `.gitignore` appends. Applies by default with dirty-tree refusal (`--force` to override); use `--dry-run` to preview. Run without `--packs` for an interactive pack picker (it auto-detects your stack and offers the matching packs as the default); pass `--packs auto` to accept the detected set non-interactively, or `--packs ''` for core only. Requires bash 4+ (Windows: run under WSL — Git Bash may work but its worktree/symlink support is flakier). Git hooks are armed automatically as the final install step; pass `--no-arm-hooks` to opt out (templates still land in `sysop/scripts/hooks/`, run `sysop/scripts/install_hooks.sh` later). After install, commit the whole Sysop payload: `git add .claude/ sysop/ tasks/ CLAUDE.md .gitignore && git commit -m "chore: install Sysop"` — a `git worktree` (what `/claim-task` creates) only sees *committed* files, so `sysop/` (the scripts and the workflow docs) must be in the tree or later hook/check steps break. Three of those paths are Sysop's **contract files**, worth knowing by name: `.claude/settings.json` is the workflow's contract with the agent harness, `.claude/sysop.lock` is the contract with future `--update` runs, and `SYSOP_ISSUES.md` is your project's queryable record of Sysop signal — pain points and wins alike (`/review-close` Step 7 appends both during cycle close-out; `/report-issues` files the friction worth sending upstream, and `/share-wins` shares the `[good]` wins as a comment on the Sysop repo's Wins discussion — both per-entry, with your review). Then, on whichever machine has the Sysop clone, add `export SYSOP_SRC=/absolute/path/to/sysop` to your shell rc (`~/.zshrc` / `~/.bashrc`) and re-source it — required by `sysop/scripts/sysop-update.sh` (the one-line update entry point; see "Updating an existing install" below).
- **Claude Code plugin** — `/plugin marketplace add getsysop/sysop` then `/plugin install sysop@sysop` plus desired packs (e.g., `/plugin install sysop-python@sysop`). Delivers the slash commands with proper namespacing (`/sysop:claim-task`) — **and only the slash commands**: the scripts, checks, maps, and hooks those commands operate on arrive via the bash installer above, so a Claude Code consumer runs both paths (details in [§ Plugin path](#plugin-path-how-updates-work)).

## Install modes: full and loop

`--mode` chooses how much of Sysop lands. Default is **full** — the whole workflow (planning, task queue, worktrees, merge gate). **`--mode loop`** installs only the *convention loop*: the review/audit skills (`/codebase-review`, `/security-audit`, `/test-audit`) plus the give-back channel (`/report-issues`, `/contribute-convention`), the convention + security maps, and the compiled checks (`run_checks`, semgrep, the git-hook + CI templates) — into a repo whose owner keeps their own planning, branching, and merge workflow. The `review_tasks.md` findings ledger those skills maintain is created on your first `/codebase-review` run, not written at install. This section is the reference for the flag; the day-one walkthrough — first review run, how promotion lands, growing into the full workflow — is [docs/loop-mode.md](./loop-mode.md).

```bash
bash install.sh <target> --packs python --mode loop
```

Loop mode drops the lifecycle: no `tasks/` queue, no worktrees, no `/claim-task` or `/review-close` merge gate, no root `WORKFLOW.md`. It also leaves `sysop/SYSOP_ISSUES.md` lazy — created on your first friction capture, not at install — so a loop install's root footprint is just `.claude/`, the `sysop/` vendor dir, and a `CLAUDE.md`. Enforcement is the checks the computer runs, not a Sysop merge gate: promoted mechanical rules compile into `checks.yml` / semgrep (run by the shipped CI template) or into the pre-commit hook's own check slots (armed automatically at install; re-arm with `sysop/scripts/install_hooks.sh` after edits), and you merge however you already merge.

The audit skills read three sections from your project's `CLAUDE.md` — `## Scope mapping`, `## Map coverage exclusions`, `## Security-critical always-include files` — so the installer ensures they're present: it creates `CLAUDE.md` with commented stubs if the file is absent, or appends only the sections you don't already have (never rewriting your content).

**Switching modes.** The mode is recorded in `.claude/sysop.lock`, and `--update` re-applies it. To grow a loop install into the full workflow, run `bash install.sh <target> --update --mode full` — purely additive (it adds the lifecycle skills, scripts, and the `tasks/` scaffold). The other direction (full → loop) is a fresh reinstall, not an `--update`.

## What the git hooks do

The installer arms two hooks. Both ship as **skeletons that block nothing on day one** — every check in the shipped files is a commented-out example a project fills in as its own conventions are promoted; until then, commits and merges pass untouched.

- **`pre-commit`** — a two-tier convention-check frame: blocking checks reject the commit on match, advisory checks warn and allow it. The shipped file defines the frame only (staged-file collection, per-language filters, the B*/A* slots); worked examples live in the Sysop repo under [`core/companion/git-hooks/examples/`](https://github.com/getsysop/sysop/tree/main/core/companion/git-hooks/examples). Escape hatch: `PRE_COMMIT_ADVISORY_ONLY=1 git commit …` downgrades blocking checks to warnings for that commit.
- **`pre-merge-commit`** — runs your project's test/build commands before a merge lands on the protected branch (default `main`, edit the constant to match yours) and fires nowhere else; merges to other branches are untouched. Also a skeleton until you fill in the commands. It deliberately does **not** source `.env` — secrets reach tests through fixtures, not hook-time exports. Bypass: `git merge --no-verify`.

Armed copies live in `.git/hooks/` (untracked — git's design, the one surface a revert can't reach); the tracked templates live in `sysop/scripts/hooks/`. `--no-arm-hooks` skips arming at install time, `bash sysop/scripts/install_hooks.sh` arms later, and removal is two `rm` commands covered in [Backing out](#backing-out).

## Updating an existing install

Once installed, a project absorbs upstream Sysop changes by running one command from its own repo root (full design and rationale in WORKFLOW.md § 8.2b):

```bash
bash sysop/scripts/sysop-update.sh           # apply
bash sysop/scripts/sysop-update.sh --dry-run # preview (writes nothing)
bash sysop/scripts/sysop-update.sh --force   # skip the pre-update snapshot
```

The shim resolves the consumer root via `git rev-parse --show-toplevel` and the Sysop source via `$SYSOP_SRC` (set once in your shell rc — see the post-install bullet above), then hands off to `bash $SYSOP_SRC/install.sh <consumer-root> --update`. All flags forward verbatim. It is itself a managed path, so improvements to the wrapper flow through the same channel as everything else.

The underlying `--update` mode snapshots any dirty managed paths into a `Sysop: pre-update snapshot` commit, overwrites managed files with this checkout's version, refreshes the lock, and leaves the update uncommitted so you review and commit intentionally; `git diff <snapshot-hash>..HEAD` shows exactly what Sysop changed. If Sysop's reference repo has the previously-installed commit, a pre-overwrite divergence check warns about committed local edits in managed paths; a post-overwrite delta table flags files with significant deletions for follow-up review (see WORKFLOW.md § 8.2b for the warn-then-diff design). `--update` deliberately does **not** auto-arm git hooks (Phase 15 / ISSUE-0007) — `sysop/scripts/hooks/*` is overwritten with upstream skeletons but `.git/hooks/*` is left untouched so you can reconcile `sysop/scripts/hooks/*` via `git checkout HEAD -- …` before re-arming; an armed-hook divergence check at the end of the run flags any `sysop/scripts/hooks/<base>` that differs from `.git/hooks/<base>`. Re-arm with `bash sysop/scripts/install_hooks.sh` after reconciling.

To pin to a reviewed release instead of tracking HEAD, pass `--ref <tag>` (works on fresh installs and `--update` alike): `bash sysop/scripts/sysop-update.sh --ref v0.1.0` installs from that tag's tree and records its commit in the lock. See [SECURITY.md](../SECURITY.md) § "How updates reach you — and how to pin".

Two additional modes (also invoked via `bash <path-to-sysop-clone>/install.sh`, since neither runs from a routine update cadence):

- `bash install.sh <target> --adopt --packs <list>` — one-time backfill for installs that pre-date the lock mechanism. Writes + commits `.claude/sysop.lock` so future `--update` runs work.
- `bash install.sh <target> --check --source <path-to-sysop-clone>` — read-only: reports how many upstream commits affect installable content, without writing anything.

The lower-level invocation `bash <sysop-src>/install.sh <consumer-root> --update [flags]` is what the shim wraps; reach for it directly when you need a Sysop source other than `$SYSOP_SRC` (e.g., a different branch or worktree) or are running outside a consumer git working tree.

### Preserving consumer-modified scripts and hooks (Phase 24b)

For managed scripts and hook templates — where "append" isn't the right shape (you can't add `errors="replace"` to a Python `open()` from a sibling file) — Phase 24b preserves consumer-modified files automatically. Scope is intentionally narrow: `sysop/scripts/*` (depth-1) and `sysop/scripts/hooks/*` (depth-2). Skills, workflow docs, semgrep rules, and tasks-scaffold templates are explicitly out of scope (silent prompt-forks accumulate divergence with no upstream pressure to reconcile; for those, use CLAUDE.md prose or pack-level extensions).

When you've hand-edited a managed script and committed, the next `bash sysop/scripts/sysop-update.sh` reports:

```
── preserved managed paths (Phase 24b) ──

  ↻  sysop/scripts/archive_review_tasks.py   (consumer-modified; --accept-upstream to overwrite)
  ↻  sysop/scripts/hooks/pre-commit          (consumer-modified; --accept-upstream to overwrite)

  preserved: 2 managed path(s) preserved due to consumer modification.
  Re-run with --accept-upstream <relpath> (repeatable) or --accept-upstream-list <file> to override.
```

The preserved files are NOT touched by the overwrite; the rest of the pipeline runs as normal. Two-pass workflow when you want some of them updated:

```bash
# 1. First run: see what's preserved.
bash sysop/scripts/sysop-update.sh

# 2. Inspect the upstream-vs-consumer diff per preserved path:
#    git -C $SYSOP_SRC log --oneline -p <old_commit>..HEAD -- core/companion/scripts/<file>
#    git log --oneline -p -- sysop/scripts/<file>

# 3. Take upstream for the subset you want (repeatable, or pass a list file):
bash sysop/scripts/sysop-update.sh --accept-upstream sysop/scripts/archive_review_tasks.py
# or
echo "sysop/scripts/archive_review_tasks.py" > /tmp/accept.txt
echo "sysop/scripts/hooks/pre-merge-commit" >> /tmp/accept.txt
bash sysop/scripts/sysop-update.sh --accept-upstream-list /tmp/accept.txt
```

The list-file form ignores `#`-comments and blank lines; stale entries (paths that were not actually consumer-modified) surface as a `note: accept-upstream: <relpath> not in preserved set; ignored` line after the pipeline so they don't accumulate silently.

**Fail-closed posture.** If the shadow worktree can't be reconstructed (Sysop source missing the OLD commit, pre-bash-installer anchor, etc.), `--update` aborts in non-`--force` mode rather than silently overwriting your customizations. The error names the three escape hatches: `git fetch` (most common — the lock's commit may simply be missing locally), `--accept-upstream <path>` (take upstream per file), or `--force` (skip preservation entirely). See WORKFLOW.md § 8.2c for the full contract.

**Hook templates.** `sysop/scripts/hooks/pre-commit` and `sysop/scripts/hooks/pre-merge-commit` are in scope, so consumer-customized hook *bodies* survive `--update` automatically — closing the gap Phase 15 left open (Phase 15 protected `.git/hooks/<base>` armed copies but the upstream pipeline still overwrote the `sysop/scripts/hooks/<base>` templates). Re-arming after reconciling remains a Phase 15 contract: `bash sysop/scripts/install_hooks.sh` after the update.

### Plugin path: how updates work

The plugin path delivers slash commands only — and only from the **core** plugin. Inspecting the manifests: `core/.claude-plugin/plugin.json` exposes `./skills/` (the lifecycle slash commands like `/sysop:claim-task`, plus the `pr-*` GitHub family — currently `/sysop:pr-dependabot`, the only skill that shells out to `gh`); every pack plugin (`sysop-python`, `sysop-postgres`, etc.) declares only a `dependencies` list (always including `sysop`; some packs — currently `sysop-postgres`, `sysop-beancount`, `sysop-mcp-server`, `sysop-pandas`, `sysop-streamlit` — also depend on `sysop-python` because their content layers on the python pack: a `companion/checks.yml.fragment` using python-pack-declared placeholders, or, for `sysop-beancount`, convention/security maps that overlay the python pack's baseline) and ships no `skills` / `commands` / `agents` / `hooks` payload of its own. The actual pack value (`convention_map.md`, `security_map.md`, `checks.yml.fragment`, semgrep rules) lives under `companion/` and is referenced by zero plugin manifests. That content reaches a consumer project *only* through the bash installer. A plugin-only install is useful for trying the slash commands out, but a real consumer always runs the bash installer as well so the skills have config to read.

Recommended setup for consumers who want both paths:

1. **Turn on auto-update for the Sysop marketplace.** Third-party marketplaces have auto-update **off** by default in Claude Code. We recommend enabling it for Sysop: toggle via `/plugin` → Marketplaces tab → Sysop → Auto-update, or set `"autoUpdate": true` for Sysop under `extraKnownMarketplaces` in `~/.claude/settings.json`. With auto-update on, Claude Code refreshes the marketplace and pulls the latest commit of every installed Sysop plugin at the start of each session — no other action needed for slash-command updates.
2. **There is no `/plugin update` command.** Updates apply at session start when auto-update is on. To force a check mid-session: `/plugin marketplace update Sysop` refreshes the marketplace's plugin list (catches new packs appearing upstream — e.g., `sysop-flutter` once that pack is populated); follow with `/plugin install <plugin>@sysop` per already-installed plugin to pull the latest commit.
3. **Pinning the plugin path.** Every Sysop `plugin.json` deliberately omits the `version` field, so Claude Code tracks each commit (auto-update on every commit). This is a conscious choice: adding a `version` would *freeze* plugin updates until a manual bump, and Claude Code offers no consumer-side version pin (`install sysop@x.y.z` isn't a thing), so a version field would cost frequent updates without buying a pin. To hold the plugin path at a known state, turn off auto-update for the Sysop marketplace (above) and update deliberately. For a **hard pin to a reviewed release**, use the bash path — `bash install.sh <target> --ref v0.1.0` (or `bash sysop/scripts/sysop-update.sh --ref v0.1.0`) installs from a tagged release instead of HEAD. See [SECURITY.md](../SECURITY.md) § "How updates reach you — and how to pin".
4. **Reset / recovery.** Installed plugins live at `~/.claude/plugins/cache/`. To force a clean re-pull: `/plugin uninstall <plugin>@sysop` then `/plugin install <plugin>@sysop`.

**Reconciling plugin + bash-installer updates.** When upstream Sysop ships a change, both sides typically move in the same commit: a skill body edit (plugin path) often comes with a matching convention-map or checks.yml change (bash-installer path). The two paths update independently — plugin auto-updates at the next session start; bash-installer changes require an explicit `bash install.sh <target> --update`. Run `--update` whenever you notice a Sysop plugin auto-updated to a new commit; the `--update` snapshot diff + post-overwrite delta table (WORKFLOW.md § 8.2b) show what changed in your project tree.

## Required permissions

The bash installer writes `<target>/.claude/settings.json` with a scoped allow-list for every Bash command the Sysop skills invoke (git merges, worktrees, branch deletes, pushes, scripts in `sysop/scripts/`). This file is required when running under Claude Code's `auto` permission mode with `skipAutoPermissionPrompt: true` — without it, skills like `/review-close` silently halt mid-merge when the harness blocks `git merge --ff-only`. Know what you're granting: the full-mode list pre-authorizes the lifecycle git flow, including `git push origin` and `git push --force-with-lease` (the worktree close path) — the installer says this out loud at install time, and the file is yours to trim (delete any rule you don't want; the affected skill just prompts instead). **The allow-list is already tiered by mode:** a `--mode loop` install ships a small check/read-only subset (no push, merge, or rebase grants, no hooks). The installer merges with any existing `settings.json` rather than overwriting (set-union on `permissions.allow`). See WORKFLOW.md § 8.2a for the rule-by-skill table and the conscious omissions (no `Bash(git *)`, no `git push --force` without lease).

## Repo layout

The Sysop repo itself:

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

## Backing out

Everything Sysop writes is a tracked file plus one set of git hooks, so reversing it — a single task claim, or the whole tool — is a clean git operation.

### Reversing a task claim

`/claim-task` does three things: flips the task to `in_progress` in `tasks/index.yml`, takes a lock at `.locks/<TASK-ID>.lock` (under the main repo), and creates a worktree on a feature branch. To reverse all three, run the un-claim flag from the **main checkout** (not from inside the task's worktree):

```bash
bash sysop/scripts/claim_task.sh --release <TASK-ID>
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
.venv/bin/python3 sysop/scripts/validate_tasks.py   # confirm the queue is consistent
git commit -am "chore: release <TASK-ID>"
```

Hand-editing `status:` is normally off-limits (`tasks/README.md` rule 2) precisely because it can desync the lock — but doing it in the *same pass* as the lock removal (exactly what `--release` automates) is the sanctioned reversal, and `validate_tasks.py` confirms nothing is left dangling.

### Removing Sysop from your project

Sysop's whole payload is the set you committed as `chore: install Sysop` — the `sysop/` vendor dir (scripts, docs, the friction log), plus the `.claude/` merge, `tasks/`, and the `CLAUDE.md` / `.gitignore` appends (the exact per-file managed-path list is recorded in `.claude/sysop.lock`'s `managed_paths`; see WORKFLOW.md § 8.2b). Because it is all tracked:

- **Revert the install commit** if nothing has touched the payload since — e.g. a fresh install you're immediately undoing: `git revert <install-commit>`. Once you've actually *used* Sysop, later cycles have committed to `tasks/index.yml`, so a revert conflicts there — fall back to deleting the paths instead.
- **Delete the managed paths.** Everything Sysop owns lives under `sysop/`, so removing it is `git rm -r sysop`, then commit — nothing of yours is mingled in there to pick apart (Phase 128; the pre-namespace flat `scripts/` layout is why older docs warned about selective removal). Sysop also *merges* into any existing `.claude/`, so revert that merge using `managed_paths` in `.claude/sysop.lock` as the source of truth rather than deleting `.claude/` wholesale. `tasks/` stays — it holds both Sysop's scaffold (`schema.md`, `README.md`) and your own planning content (`vision.md`, `decisions.md`, the queue); keep or prune it as you like.
- **Disarm the git hooks** — the one untracked, unrecoverable surface. `install.sh` copies Sysop's two hooks into `.git/hooks/` (which git never tracks): `rm -f .git/hooks/pre-commit .git/hooks/pre-merge-commit`. Remove only hooks Sysop armed — if you had your own, `install_hooks.sh` backed them up alongside as `*.bak.<timestamp>`.
- **Plugin users:** also `/plugin uninstall <plugin>@sysop` per installed Sysop plugin.

Outside the repo, the only traces are the optional `SYSOP_SRC` line in your shell rc and the Claude Code plugin cache — remove those if you added them.
