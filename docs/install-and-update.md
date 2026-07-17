# Installing and updating Sysop

The [README Quickstart](../README.md#quickstart) is the short version. This page is the full
reference: both install paths, how updates reach an installed project, pinning to a release,
required permissions, the repo layout, and how to back out. Consumer-side configuration — the
overlay files, placeholder substitution, model roles — lives in
[docs/configuration.md](./configuration.md); the authoritative process spec behind everything
here is [WORKFLOW.md § 8](../core/companion/docs/WORKFLOW.md).

## Two install paths

Two install paths; they layer rather than conflict.

- **Bash installer** — `bash install.sh <target> --packs python,postgres,nextjs-react`. Delivers project-side files (workflow docs, skills, scripts, git-hook templates, semgrep rules + fixtures, concatenated `convention_map.md` / `security_map.md` / `checks.yml`, **`.claude/settings.json` permission allow-list**, **`.claude/sysop.lock` install manifest**, **`SYSOP_ISSUES.md` friction log at repo root** — seeded fresh-install only, project-owned thereafter; see WORKFLOW.md § 8.2b for the seed-once-never-overwrite contract) into the target project per WORKFLOW.md § 8.2. Applies by default with dirty-tree refusal (`--force` to override); use `--dry-run` to preview. Run without `--packs` for an interactive pack picker (it auto-detects your stack and offers the matching packs as the default); pass `--packs auto` to accept the detected set non-interactively, or `--packs ''` for core only. Requires bash 4+ (Windows: run under WSL — Git Bash may work but its worktree/symlink support is flakier). Git hooks are armed automatically as the final install step; pass `--no-arm-hooks` to opt out (templates still land in `scripts/hooks/`, run `scripts/install_hooks.sh` later). After install, commit the whole Sysop payload: `git add .claude/ scripts/ WORKFLOW.md WORKFLOW_GUIDE.md tasks/ SYSOP_ISSUES.md && git commit -m "chore: install Sysop"` — a `git worktree` (what `/claim-task` creates) only sees *committed* files, so `scripts/` and the workflow docs must be in the tree or later hook/check steps break. Three of those paths are Sysop's **contract files**, worth knowing by name: `.claude/settings.json` is the workflow's contract with the agent harness, `.claude/sysop.lock` is the contract with future `--update` runs, and `SYSOP_ISSUES.md` is your project's queryable record of Sysop signal — pain points and wins alike (`/review-close` Step 7 appends both during cycle close-out; `/report-issues` files the friction worth sending upstream, and `/share-wins` shares the `[good]` wins as a comment on the Sysop repo's Wins discussion — both per-entry, with your review). Then, on whichever machine has the Sysop clone, add `export SYSOP_SRC=/absolute/path/to/sysop` to your shell rc (`~/.zshrc` / `~/.bashrc`) and re-source it — required by `scripts/sysop-update.sh` (the one-line update entry point; see "Updating an existing install" below).
- **Claude Code plugin** — `/plugin marketplace add getsysop/sysop` then `/plugin install sysop@sysop` plus desired packs (e.g., `/plugin install sysop-python@sysop`). Delivers the slash commands with proper namespacing (`/sysop:claim-task`) — **and only the slash commands**: the scripts, checks, maps, and hooks those commands operate on arrive via the bash installer above, so a Claude Code consumer runs both paths (details in [§ Plugin path](#plugin-path-how-updates-work)).

## What the git hooks do

The installer arms two hooks. Both ship as **skeletons that block nothing on day one** — every check in the shipped files is a commented-out example a project fills in as its own conventions are promoted; until then, commits and merges pass untouched.

- **`pre-commit`** — a two-tier convention-check frame: blocking checks reject the commit on match, advisory checks warn and allow it. The shipped file defines the frame only (staged-file collection, per-language filters, the B*/A* slots); worked examples live in the Sysop repo under [`core/companion/git-hooks/examples/`](https://github.com/getsysop/sysop/tree/main/core/companion/git-hooks/examples). Escape hatch: `PRE_COMMIT_ADVISORY_ONLY=1 git commit …` downgrades blocking checks to warnings for that commit.
- **`pre-merge-commit`** — runs your project's test/build commands before a merge lands on the protected branch (default `main`, edit the constant to match yours) and fires nowhere else; merges to other branches are untouched. Also a skeleton until you fill in the commands. It deliberately does **not** source `.env` — secrets reach tests through fixtures, not hook-time exports. Bypass: `git merge --no-verify`.

Armed copies live in `.git/hooks/` (untracked — git's design, the one surface a revert can't reach); the tracked templates live in `scripts/hooks/`. `--no-arm-hooks` skips arming at install time, `bash scripts/install_hooks.sh` arms later, and removal is two `rm` commands covered in [Backing out](#backing-out).

## Updating an existing install

Once installed, a project absorbs upstream Sysop changes by running one command from its own repo root (full design and rationale in WORKFLOW.md § 8.2b):

```bash
bash scripts/sysop-update.sh           # apply
bash scripts/sysop-update.sh --dry-run # preview (writes nothing)
bash scripts/sysop-update.sh --force   # skip the pre-update snapshot
```

The shim resolves the consumer root via `git rev-parse --show-toplevel` and the Sysop source via `$SYSOP_SRC` (set once in your shell rc — see the post-install bullet above), then hands off to `bash $SYSOP_SRC/install.sh <consumer-root> --update`. All flags forward verbatim. It is itself a managed path, so improvements to the wrapper flow through the same channel as everything else.

The underlying `--update` mode snapshots any dirty managed paths into a `Sysop: pre-update snapshot` commit, overwrites managed files with this checkout's version, refreshes the lock, and leaves the update uncommitted so you review and commit intentionally; `git diff <snapshot-hash>..HEAD` shows exactly what Sysop changed. If Sysop's reference repo has the previously-installed commit, a pre-overwrite divergence check warns about committed local edits in managed paths; a post-overwrite delta table flags files with significant deletions for follow-up review (see WORKFLOW.md § 8.2b for the warn-then-diff design). `--update` deliberately does **not** auto-arm git hooks (Phase 15 / ISSUE-0007) — `scripts/hooks/*` is overwritten with upstream skeletons but `.git/hooks/*` is left untouched so you can reconcile `scripts/hooks/*` via `git checkout HEAD -- …` before re-arming; an armed-hook divergence check at the end of the run flags any `scripts/hooks/<base>` that differs from `.git/hooks/<base>`. Re-arm with `bash scripts/install_hooks.sh` after reconciling.

To pin to a reviewed release instead of tracking HEAD, pass `--ref <tag>` (works on fresh installs and `--update` alike): `bash scripts/sysop-update.sh --ref v0.1.0` installs from that tag's tree and records its commit in the lock. See [SECURITY.md](../SECURITY.md) § "How updates reach you — and how to pin".

Two additional modes (also invoked via `bash <path-to-sysop-clone>/install.sh`, since neither runs from a routine update cadence):

- `bash install.sh <target> --adopt --packs <list>` — one-time backfill for installs that pre-date the lock mechanism. Writes + commits `.claude/sysop.lock` so future `--update` runs work.
- `bash install.sh <target> --check --source <path-to-sysop-clone>` — read-only: reports how many upstream commits affect installable content, without writing anything.

The lower-level invocation `bash <sysop-src>/install.sh <consumer-root> --update [flags]` is what the shim wraps; reach for it directly when you need a Sysop source other than `$SYSOP_SRC` (e.g., a different branch or worktree) or are running outside a consumer git working tree.

### Preserving consumer-modified scripts and hooks (Phase 24b)

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

### Plugin path: how updates work

The plugin path delivers slash commands only — and only from the **core** plugin. Inspecting the manifests: `core/.claude-plugin/plugin.json` exposes `./skills/` (the lifecycle slash commands like `/sysop:claim-task`, plus the `pr-*` GitHub family — currently `/sysop:pr-dependabot`, the only skill that shells out to `gh`); every pack plugin (`sysop-python`, `sysop-postgres`, etc.) declares only a `dependencies` list (always including `sysop`; some packs — currently `sysop-postgres`, `sysop-beancount`, `sysop-mcp-server`, `sysop-pandas`, `sysop-streamlit` — also depend on `sysop-python` because their content layers on the python pack: a `companion/checks.yml.fragment` using python-pack-declared placeholders, or, for `sysop-beancount`, convention/security maps that overlay the python pack's baseline) and ships no `skills` / `commands` / `agents` / `hooks` payload of its own. The actual pack value (`convention_map.md`, `security_map.md`, `checks.yml.fragment`, semgrep rules) lives under `companion/` and is referenced by zero plugin manifests. That content reaches a consumer project *only* through the bash installer. A plugin-only install is useful for trying the slash commands out, but a real consumer always runs the bash installer as well so the skills have config to read.

Recommended setup for consumers who want both paths:

1. **Turn on auto-update for the Sysop marketplace.** Third-party marketplaces have auto-update **off** by default in Claude Code. We recommend enabling it for Sysop: toggle via `/plugin` → Marketplaces tab → Sysop → Auto-update, or set `"autoUpdate": true` for Sysop under `extraKnownMarketplaces` in `~/.claude/settings.json`. With auto-update on, Claude Code refreshes the marketplace and pulls the latest commit of every installed Sysop plugin at the start of each session — no other action needed for slash-command updates.
2. **There is no `/plugin update` command.** Updates apply at session start when auto-update is on. To force a check mid-session: `/plugin marketplace update Sysop` refreshes the marketplace's plugin list (catches new packs appearing upstream — e.g., `sysop-flutter` once that pack is populated); follow with `/plugin install <plugin>@sysop` per already-installed plugin to pull the latest commit.
3. **Pinning the plugin path.** Every Sysop `plugin.json` deliberately omits the `version` field, so Claude Code tracks each commit (auto-update on every commit). This is a conscious choice: adding a `version` would *freeze* plugin updates until a manual bump, and Claude Code offers no consumer-side version pin (`install sysop@x.y.z` isn't a thing), so a version field would cost frequent updates without buying a pin. To hold the plugin path at a known state, turn off auto-update for the Sysop marketplace (above) and update deliberately. For a **hard pin to a reviewed release**, use the bash path — `bash install.sh <target> --ref v0.1.0` (or `bash scripts/sysop-update.sh --ref v0.1.0`) installs from a tagged release instead of HEAD. See [SECURITY.md](../SECURITY.md) § "How updates reach you — and how to pin".
4. **Reset / recovery.** Installed plugins live at `~/.claude/plugins/cache/`. To force a clean re-pull: `/plugin uninstall <plugin>@sysop` then `/plugin install <plugin>@sysop`.

**Reconciling plugin + bash-installer updates.** When upstream Sysop ships a change, both sides typically move in the same commit: a skill body edit (plugin path) often comes with a matching convention-map or checks.yml change (bash-installer path). The two paths update independently — plugin auto-updates at the next session start; bash-installer changes require an explicit `bash install.sh <target> --update`. Run `--update` whenever you notice a Sysop plugin auto-updated to a new commit; the `--update` snapshot diff + post-overwrite delta table (WORKFLOW.md § 8.2b) show what changed in your project tree.

## Required permissions

The bash installer writes `<target>/.claude/settings.json` with a scoped allow-list for every Bash command the Sysop skills invoke (git merges, worktrees, branch deletes, pushes, scripts in `scripts/`). This file is required when running under Claude Code's `auto` permission mode with `skipAutoPermissionPrompt: true` — without it, skills like `/review-close` silently halt mid-merge when the harness blocks `git merge --ff-only`. The installer merges with any existing `settings.json` rather than overwriting (set-union on `permissions.allow`). See WORKFLOW.md § 8.2a for the rule-by-skill table and the conscious omissions (no `Bash(git *)`, no `git push --force` without lease).

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
