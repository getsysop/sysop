---
name: release
description: Cut a release — bundle the work since the last git tag into a proposed semver bump, a Keep-a-Changelog entry, an annotated tag, and an optional GitHub Release. Reuses /daily-summary's commit classifier and joins tasks/index.yml for human-readable highlights. Write-side and human-gated; dry-run by default.
argument-hint: "[--execute] [--github-release] [--from <tag>] [--as <version>]"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning -->

The **release** leg of the lifecycle. Where `/review-close` verifies a *single* deploy (Step 5 waits on the pipeline and runs a post-deploy smoke), `/release` manages a *release*: it takes the **many** merges that have landed since the last tag and turns them into the artifacts a release is made of — a proposed version bump, a changelog entry, an annotated git tag, and (opt-in) a GitHub Release.

It is deliberately **lightweight**. v1 = changelog + version proposal + tag + optional GitHub-release notes. Staged rollout, canary, feature flags, and rollback runbooks are the *operations* band Sysop holds the line on — chasing them turns Sysop into Datadog/PagerDuty territory and dilutes the convention-ratchet identity. Those live in the deferred **(D) rollback / staged-rollout** sibling; `/release` is release *authoring/recording*, that one is release *operating*. Keep them separate.

**This is a write-side skill** — the sibling of `/review-close`, not the read-only `/daily-summary` / `/roadmap` / `/sitrep` family. It has no `disallowed-tools` guard because it writes `CHANGELOG.md`, creates a tag, and (opt-in) creates a GitHub Release. Every irreversible or outward-facing action is **human-gated**, exactly like `/review-close`'s merge confirmations: **dry-run is the default**, `--execute` performs local writes + tag, and the public GitHub Release needs a second explicit `--github-release` opt-in.

## Not `/daily-summary` or `/review-close`

- **`/daily-summary`** windows by **date** (yesterday / the past week) and is **read-only**. `/release` windows by **release boundary** (last tag → HEAD) and **writes** artifacts. They share the commit classifier (Step 3 below reuses `/daily-summary`'s exactly) but answer different questions: "what happened this week?" vs. "what's in this release?"
- **`/review-close`** lands *one* batch of approved work on `main` and verifies *one* deploy. `/release` sits a level up: it bundles the N review-close cycles that accumulated since the last tag into a single versioned, tagged, documented release. Run `/review-close` per batch; run `/release` when you want to cut a version.

## Pre-flight: Permission Guard

The **dry-run default requires no permission rules** — it only reads git history, `tasks/index.yml`, and `CHANGELOG.md`, and prints a plan. Per `_shared/permission-guard.md` § Notes, read-only git ops (`git log`, `git describe`, `git tag --list`) are auto-approved and not listed as allow-rules. On this default path the skill is as portable as `/daily-summary` — with one caveat: the *optional* Step 5 PR-link enrichment (only under `pr` merge policy) shells `gh pr list`, which relies on the `Bash(gh pr list:*)` rule already in the Sysop template. It is deliberately **not** on the required list — a missing rule or absent `gh` degrades it silently (the plan is complete without PR links), so it never blocks a dry-run.

The write path requires rules **conditionally**, mirroring `/review-close`'s policy-gated requirement (only demand what the chosen path invokes). Read `.claude/settings.json` and confirm `permissions.allow` contains:

- **When `--execute` is passed** (the local + tag path):
  - `Bash(git tag:*)` — create the annotated release tag
  - `Bash(git push origin:*)` — push the tag to origin (already in the Sysop allow-list template)
- **When `--github-release` is passed** (additionally):
  - `Bash(gh release create:*)` — create the public GitHub Release

If a required rule for the requested path is missing, stop with the `_shared/permission-guard.md` § Algorithm step 4 message (one-line reason: "cuts a release — creates and pushes a git tag, and optionally a GitHub Release"). `gh auth status`, `gh release view`, and `git fetch` are read-only and auto-approved under `auto` mode — they are **not** listed here (per `_shared/permission-guard.md` § Notes: don't list read-only ops). Editing `CHANGELOG.md` uses the `Edit`/`Write` tool, not Bash, so it needs no allow-rule.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and continue.

## Step 0 — Parse arguments

Parse `$ARGUMENTS`:

- **`--execute`** — perform the local writes: prepend the `CHANGELOG.md` entry (uncommitted), create the annotated tag on the verified `main` tip, and push the tag. **Without it the skill is a dry-run** — it computes and prints the full plan (proposed version, changelog entry, tag, would-be release notes) and writes/creates nothing.
- **`--github-release`** — additionally create a public GitHub Release from the tag (requires `--execute` and `gh`). Off by default: the changelog + tag stay inside your own git; publishing a Release page is a deliberate second opt-in.
- **`--from <tag>`** — override the window-start tag (default: the most recent tag reachable from HEAD). Use it to re-cut or to bundle across a mistagged point.
- **`--as <version>`** — override the proposed version (e.g. `--as 2.0.0`). Use when the semver inference is wrong or you're setting a first release. The skill still shows its inferred proposal and asks you to confirm the final value.

## Step 1 — Establish the release window

Find the last tag reachable from HEAD:

```bash
git describe --tags --abbrev=0 2>/dev/null   # → the most recent tag, or empty on a never-tagged repo
```

- **A tag exists** → the window is `<lasttag>..HEAD`. Record the tag's date for the task join: `git log -1 --format=%ad --date=short "<lasttag>"`.
- **No tag (first release)** → the window is the full history (root..HEAD). Note "first release — no prior tag; bundling full history" at the top of the plan.
- **`--from <tag>` given** → use it as the window start instead (validate it exists via `git rev-parse --verify "<tag>^{tag}" || git rev-parse --verify "<tag>"`; if it doesn't resolve, stop and say so).

Detect the **tag prefix convention** from the last tag so the new tag matches it: if the last tag is `v1.4.2`, keep the `v` prefix; if it's `1.4.2`, use none. Only infer the prefix from a **semver-shaped** tag — if the most-recent tag is not a version (see Step 6's semver guard), default the prefix to `v`. Default to `v` for a first release too (the most common convention), and surface it as part of the version confirmation so the human can drop it.

## Step 2 — Release hygiene preconditions (before any write)

A release must mark **shipped** code. Assert the following and **stop with a clear message** if any fails (these are checks, not writes, so they run even in dry-run — a dry-run that would fail these is worth surfacing early):

1. **On the release branch.** Default is `main` (the branch `/review-close` lands work on). Assert `git rev-parse --abbrev-ref HEAD` = `main` (or the project's release branch if its `CLAUDE.md` names one). If not, stop: *"Not on the release branch (`main`) — check out the branch you release from and re-run."* This is Rule A of `_shared/main-push-guard.md` applied to the tag site.
2. **HEAD is already on `origin/<branch>`.** Fetch and assert the tip you're about to tag is pushed:
   ```bash
   git fetch origin
   git merge-base --is-ancestor HEAD origin/<branch> || echo "UNPUSHED"
   ```
   If `UNPUSHED`, stop: *"You have local commits not yet on `origin/<branch>` — run `/review-close` to land them before cutting a release, so the tag marks code that actually shipped."* Do not tag un-pushed work.
3. **Working tree is clean of tracked-file changes** *(warn, don't hard-stop)*. `git status --porcelain` — if there are staged/unstaged tracked changes, warn that the tag will mark `HEAD` (not the dirty tree) and ask whether to continue. (The `CHANGELOG.md` edit this skill makes in Step 8 is expected and excluded from this check.)

These preconditions are the release-specific analogue of `/review-close`'s pre-merge gate: don't cut a release from a branch that isn't `main`, from unpushed code, or without noticing a dirty tree.

## Step 3 — Gather and classify the commits

List the commits in the window (excluding merges, which are noise under Sysop's squash-merge `pr` policy):

```bash
git log <lasttag>..HEAD --no-merges --format="%h %s"
```

Group them by conventional-commit prefix. **The category table below is identical to `/daily-summary` Step 3** — keep the *table* in sync (they are deliberate parallel copies, like the two `unlock_count` implementations). `/release` additionally flags breaking-change markers for the Step 6 bump, which `/daily-summary` has no need for — so the two are not wholesale-identical; mirror the table, not the breaking-detection:

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

Extract the scope from a parenthetical when present (`feat(report-issues):` → scope `report-issues`). Also flag **breaking-change markers** for Step 6: a `!` before the colon (`feat!:`, `fix(api)!:`) or a `BREAKING CHANGE:` / `BREAKING-CHANGE:` line in the commit body.

## Step 4 — Join `tasks/index.yml` for human-readable highlights

A commit subject is terse where a task title is meaningful. `Read` `tasks/index.yml` (tolerate absence) and select tasks with `status: done` whose `completed_date` falls in the release window — i.e. `completed_date >= <lasttag date>` (from Step 1), or all done tasks for a first release. `completed_date` is an ISO `YYYY-MM-DD` string, so the comparison is plain lexicographic — no date parsing (the same in-model index read `/daily-summary` and `/roadmap` use; no script, no `.venv` dependency).

For each, pull `id`, `title`, the `id`-prefix category (`FEAT-`/`TECH-`/`DATA-`/`FIX-`/`UX-` → Feature / Technical / Data-ops / Fix / UX), and `blast_radius` **when present** (optional at `schema_version: 1`). Use `blast_radius: architectural | cross-module` as a **highlights signal** — those are the changes worth leading the release notes with. Cross-reference task IDs that appear in commit subjects so each highlighted task links to its landing commit.

If `tasks/index.yml` is missing or unparseable, note "task index unavailable — highlights from commits only" and continue. The release is complete from `git log` alone; the index join only makes it more legible.

## Step 5 — Optional enrichment (best-effort; never block on these)

- **PR links (only under `pr` merge policy).** If `<project>/CLAUDE.md § Merge policy` is `pr` and `gh` is available, you may fetch merged-PR metadata to make the notes linkable:
  ```bash
  gh pr list --state merged --search "merged:>=<lasttag date>" --json number,title,url --limit 100
  ```
  Match PRs to the window and add `(#NNN)` links to the relevant entries. If the policy is `direct`, `gh` is absent, or the call fails, skip silently — this is polish, not required output.
- **Conventions-promoted line (optional flourish).** If the project runs Sysop's convention loop, count `Promotion summary:` trailers in the window's commits (`git log <lasttag>..HEAD --format=%B | grep -c '^Promotion summary:'`) and, if non-zero, add a one-line quality-trend note (*"N conventions promoted this release"*). Purely optional; omit if zero or if the project doesn't use the loop.

## Step 6 — Propose the version bump

Compute the base version, then the bump:

1. **Base version.** In order: (a) the last tag's version — **but only if the tag is semver-shaped** (`MAJOR.MINOR.PATCH`, optionally `v`-prefixed, optional `-prerelease` suffix), stripping the prefix. If the most-recent tag is **not** a version — a date tag (`2026-07-01`), a name (`beta`), or an unrelated marker such as Sysop's own `wade-flow-extract-base` — do **not** try to parse a version out of it; fall through to (b)/(c) and note *"last tag `<tag>` isn't a semver version — treating this as a first release; pass `--as X.Y.Z` to set the version explicitly."* (b) if there is no semver tag, read a version field from a **detected** manifest — `package.json` (`"version"`), `pyproject.toml` (`[project] version` or `[tool.poetry] version`), or a `plugin.json`/`marketplace.json` `version` — **read-only**; (c) if neither, `0.0.0`. **This skill never rewrites a manifest** — it only reads one to seed the base, then prints the new version so you can bump the manifest yourself through your normal flow. (Manifest-writing is a deliberate v2 deferral — see Design notes.)
2. **Bump type**, from the Step 3 classification:
   - **major** — any breaking-change marker (`!` or `BREAKING CHANGE`) in the window.
   - **minor** — otherwise, any `feat:` commit.
   - **patch** — otherwise (only `fix:`/`refactor:`/`chore:`/etc.).
3. **Apply** to the base per semver. **Pre-1.0 caveat:** while the base is `0.y.z`, a breaking change conventionally bumps the **minor** (`0.4.0 → 0.5.0`), not to `1.0.0` — surface this and let the human decide whether the project is ready to declare `1.0.0`. (In `0.y.z` this collapses breaking *and* `feat:` into the same minor bump; the Step 8.1 version gate is where the human sets the exact number if they want to distinguish them.)
4. **First release:** with no base, propose `0.1.0` (a pre-1.0 start) by default, and note that `--as 1.0.0` declares a stable first release if that's intended.

`--as <version>` overrides the computed proposal outright; still show the inferred value alongside it so the human sees what the commits implied.

## Step 7 — Render the plan (always) — changelog entry, tag, notes

Build and print, in full, exactly what would be written/created:

**Changelog entry** — [Keep a Changelog](https://keepachangelog.com) shape, newest-on-top, grouped by the standard change classes (map the commit categories: Features→**Added**/**Changed**, Fixes→**Fixed**, breaking→**Changed** with a `**BREAKING:**` lead, deprecations→**Deprecated**, removals→**Removed**, security fixes→**Security**). Lead with the `blast_radius`-flagged task highlights, then the categorized commit list.

```
## [<new version>] - <YYYY-MM-DD>

### Added
- <feat highlights, task-title-enriched where joined> (`<hash>`, <TASK-ID>)

### Fixed
- <fix entries>

### Changed
- **BREAKING:** <breaking entries, if any>
```

Use today's date for the entry: a plain `date +%Y-%m-%d` is portable on both BSD and GNU `date` (it's simple formatting — no arithmetic, unlike `/daily-summary`'s window math, so no BSD/GNU divergence to guard). If `date` is somehow unavailable, fall back to the tip commit's date (`git log -1 --format=%ad --date=short HEAD`), which is deterministic and close to the release moment.

**Tag** — an annotated tag `<prefix><new version>` with a one-paragraph message summarizing the release (the top highlights). Show the message and the tag name; the actual creation (Step 8.3) passes the message via `git tag -a … -F <file>`, never inline.

**Release notes** — for the optional GitHub Release: the same changelog entry body, suitable for `gh release create --notes-file`.

**If `--execute` was not passed, stop here:** print `Dry-run. Re-run with --execute to write the changelog + create and push the tag (add --github-release to also publish a GitHub Release).` Write nothing, create nothing.

## Step 8 — Execute: changelog, tag, push (only under `--execute`)

1. **Confirm the version** — the one genuine judgment gate. Use `AskUserQuestion` to confirm the proposed `<prefix><new version>` or take an override (offer the computed value, the next-larger bump, and "let me type it"). Nothing downstream happens until the human picks. This is the sibling of `/review-close`'s merge confirmation.

2. **Write the changelog entry (uncommitted).** Prepend the Step 7 entry to `CHANGELOG.md` (create the file with a Keep-a-Changelog header if absent) using `Edit`/`Write`. **Leave it uncommitted** — same contract as every other Sysop write-side skill (`/review-close` aside): the human reviews and commits it through their normal flow. This matters under `pr` merge policy, where `main` is protected and a changelog commit must ride a PR, not a direct push — so `/release` does not try to commit it. The tag (next) marks the *shipped code*; the changelog documents it and lands via the human's merge policy.

3. **Re-assert the branch/tip, then create the annotated tag.** The Step 8.1 version-confirmation pause is exactly the window `_shared/main-push-guard.md` Rule A warns about — a concurrent Sysop loop (`/auto-build` batch, another `/claim-task`) or a manual `git checkout` can move `HEAD` in the shared primary worktree while you wait, so the Step 2 guarantee is stale by now. Re-assert at the write site, and pass the tag **message as a file, never inline**: the release summary carries backticks, `$`, and quotes **by design** (Step 7), so `git tag -a … -m "<summary>"` would let bash run substitutions or execute approved text — the same hazard Step 9 and `/report-issues` avoid with a file. Write the Step 7 summary to a temp file outside the repo via `Write`, then run as one block:
   ```bash
   # Rule A + tip check at the actual write site (use the project's release branch if its CLAUDE.md names one, not literally `main`)
   test "$(git rev-parse --abbrev-ref HEAD)" = "main" || { echo "HEAD moved off main since Step 2 — STOP"; exit 1; }
   git merge-base --is-ancestor HEAD origin/main || { echo "HEAD advanced to unpushed work — run /review-close first, then re-run"; exit 1; }
   git tag -a "<prefix><new version>" -F "$TMPDIR/sysop-tag-<version>.md"
   ```
   Delete the temp file after the call returns. If the tag already exists (`git rev-parse --verify "<tag>"` succeeds), **stop** — do not overwrite an existing release tag; tell the human to pick a different version or delete the old tag deliberately.

4. **Push the tag** (confirm once before this outward step):
   ```bash
   git push origin "<prefix><new version>"
   ```
   No HEAD re-assert is needed here: the tag is an **immutable ref already created on a commit verified present on `origin/main`** (item 3), so pushing it just publishes that fixed ref — unlike a branch push, it doesn't depend on where `HEAD` now points. Never `--force` a tag push. If the push is rejected because the tag exists on origin, stop and surface it — a re-used release tag is a mistake to resolve deliberately, not to force past.

## Step 9 — Publish the GitHub Release (only under `--github-release`)

Requires `--execute` and `gh`. Confirm `gh auth status` first (if not logged in, tell the human to run `! gh auth login` and stop — never authenticate on their behalf). Then, after a final confirmation (this is the one action that creates a public, outward-facing artifact):

1. Write the Step 7 release notes to a temp file **outside the repo** (e.g. `"$TMPDIR/sysop-release-<version>.md"`) via `Write` — never echo release notes through the shell (they contain backticks, `$`, and quotes by design; inlining risks shell substitution altering or executing the approved text, the same hazard `/report-issues` fixed).
2. Create the release against the **current repo** (gh uses the current directory's default remote — this is *your own* repo, unlike `/report-issues`/`/contribute-convention` which target upstream):
   ```bash
   gh release create "<prefix><new version>" --title "<prefix><new version>" --notes-file "$TMPDIR/sysop-release-<version>.md"
   ```
   Add `--latest` for a normal release; add `--prerelease` if the version carries a pre-release suffix (`-rc.1`, `-beta`). Delete the temp file after the call returns (success or failure).
3. If `gh release create` fails (auth lapse, tag not yet on origin, network), surface it plainly; the tag and changelog already exist locally, so the human can retry `gh release create` by hand.

## Step 10 — Report

Print a summary:

```
Release <prefix><new version> (<bump type> from <base version>)

Window:      <lasttag>..HEAD  (<N> commits: <N> feat, <N> fix, <N> other)
Highlights:  <M> tasks closed since <lasttag>  (<K> architectural/cross-module)
Changelog:   CHANGELOG.md updated (uncommitted — commit via your merge policy)
Tag:         <prefix><new version> created + pushed to origin  [or: dry-run — not created]
Release:     <url>  [or: skipped — pass --github-release to publish]

Next: commit CHANGELOG.md through your normal flow. The tag marks <short-sha> (shipped code).
```

In dry-run, the Tag/Release/Changelog lines read as "would create / would write" so it's unambiguous nothing happened.

## Step 11 — Edge cases

- **No commits in the window** (nothing since the last tag) → print *"No commits since `<lasttag>` — nothing to release."* and stop. Don't cut an empty release.
- **Only `chore:`/`docs:`/`ci:` commits** → propose a **patch** bump but note the release is maintenance-only, so the human can decide it's not worth tagging.
- **Never-tagged repo** → first-release path (Step 1); propose `0.1.0`; window is full history.
- **`tasks/index.yml` missing** → highlights come from commits only (Step 4); the release still cuts.
- **Not a git repository** → say so plainly and stop; this skill is tag-driven and has nothing to release without history.
- **Detached HEAD / not on `main`** → Step 2 stops before any write with the branch message.
- **Uncommitted changes present** → Step 2 warns (the tag marks `HEAD`, not the dirty tree) and asks before continuing.

## Design notes

- **Write-side, human-gated.** Unlike the read-only reporting family, `/release` mutates: it writes `CHANGELOG.md`, creates a tag, and can publish a Release. So it follows `/review-close`'s discipline — dry-run default, `AskUserQuestion` at the version gate, confirmation before each outward step, and the public Release behind a second `--github-release` opt-in. Nothing irreversible happens without an explicit pick.
- **The changelog is left uncommitted — on purpose.** Committing it would either need a direct push to `main` (rejected under `pr` merge policy, where `main` is protected) or a whole PR flow — scope that belongs to `/review-close`, not a lightweight release skill. So `/release` writes the entry and hands the commit to the human's normal merge policy. The **tag** is the durable release marker (it points at already-shipped code on `origin/main`); the changelog is documentation that lands right after. A v2 could route a changelog commit through the `pr` flow — deferred.
- **Manifest-aware read, never write (Phase 83 decision).** The base version is seeded from the last tag, or read-only from a detected manifest, or `0.0.0`. `/release` does **not** rewrite `package.json`/`pyproject.toml` — that's stack-specific and risky (arbitrary manifest parsing/writing). Sysop's own plugin manifests stay deliberately unversioned (Phase 111 — release pinning is via git tags + `install.sh --ref`, not manifest `version` fields), so cutting a Sysop release exercises the *tag* path here but never the manifest-rewrite path. Writing the manifest version in the release commit is a filed v2 enhancement.
- **Reasoning role.** The git-log→classify core is mechanical, but the value is the **synthesis** — enriching commit subjects with task titles, choosing what leads the notes, mapping to changelog classes, judging the right semver bump. That's judgment work in the same class as `/daily-summary` and `/roadmap`, so the skill carries the `reasoning` role. *Revisitable:* a consumer who cuts releases often and wants lower latency can remap the role (or this skill) to a lighter model via `.claude/served_models.local.yml` (Phase 69).
- **Output quality scales with input discipline.** Clean conventional commits + a maintained `tasks/index.yml` yield polished, task-linked notes. A messy-commit consumer falls back to raw `git log` (still works, just less polished). Git-log-only is the floor, not the design.
- **Portability.** The dry-run path is `git log` + `Read` — it runs on any git-backed project and any agent. `--execute` needs `git tag`/`git push`; `--github-release` needs `gh`. Each degrades to the narrower path when its tools/rules are absent.
- **Explicitly out of scope (the ops band).** Staged rollout, canary, feature-flag orchestration, prod-rollback runbooks. That's the deferred **(D) rollback / staged-rollout** sibling — release *operating*, distinct from this skill's release *authoring/recording*.
