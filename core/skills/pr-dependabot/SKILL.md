---
name: pr-dependabot
description: Sweep open Dependabot PRs on the GitHub repo — classify each by ecosystem + semver, then merge the safe ones (patch/minor, green CI), hold majors, and close pip + superseded. Dry-run by default. GitHub/Dependabot-specific by design.
argument-hint: "[--execute] [--json] [--repo owner/name]"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning -->

A client-side replacement for GitHub's native auto-merge. Native auto-merge
(`enablePullRequestAutoMerge`) is gated behind Pro/Team/Enterprise for **private
repos** — on the Free plan it silently stays off, so passing Dependabot PRs pile
up. This skill makes the agent the merge actor instead: it lists open Dependabot
PRs, classifies each, and either prints a plan (default) or executes it
(`--execute`) — merging safe updates with a normal authenticated `gh pr merge`
(no `--auto`), which works fine on Free.

**This is the first Sysop skill that talks to GitHub.** Every other skill is
local git only. It shells out to `gh` (the GitHub CLI) and therefore requires
`gh` installed + authenticated. It is **GitHub/Dependabot-specific by design** —
if a project uses Renovate or GitLab, that is a sibling skill (`pr-renovate`,
…), not a rename. It is the first of an intended `pr-*` family (a later
`pr-review` would cover human PRs); `pr-dependabot` is scoped narrowly on
purpose — bot dependency PRs have clean, machine-decidable rules, which human
PRs do not.

**Dry-run is the default and merging is irreversible-ish** (a merged PR squashes
to `main`). The skill never executes without an explicit `--execute`, and even
then the human is the one invoking it. Hold/surface PRs are never actuated.

## Pre-flight: Permission Guard

This skill shells out to `gh` and `python3`. It writes nothing to the filesystem
— its only side effects are GitHub PR merges/closes, and only under `--execute`.

Read `.claude/settings.json` and confirm `permissions.allow` contains:

- `Bash(python3 scripts/pr_dependabot.py:*)` — the classifier/executor itself
- `Bash(gh pr list:*)` — enumerate open Dependabot PRs
- `Bash(gh pr view:*)` — resolve `mergeable` + CI status per PR
- `Bash(gh pr merge:*)` — merge safe updates (only reached under `--execute`)
- `Bash(gh pr close:*)` — close pip + superseded PRs (only under `--execute`)

If any are missing, stop with the `_shared/permission-guard.md` § Algorithm
step 4 message (one-line reason: "client-side Dependabot PR sweep; shells `gh`
to merge/close bot PRs because native auto-merge is unavailable on Free-plan
private repos"). Do not proceed.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and
continue.

## Step 0: Parse Arguments

Parse `$ARGUMENTS`:

- **`--execute`** — actually merge/close per the plan. **Without it, the skill
  is read-only** (lists + classifies + prints, changes nothing).
- **`--json`** — emit the structured plan as JSON (for orchestrator consumption,
  consistent with `/sitrep --json`). Implies dry-run.
- **`--repo owner/name`** — override the repo (default: autodetected from the
  current directory's git remote by `gh`).

## Step 0.5: Confirm `gh` is authenticated

Run `gh auth status`. If it reports not-logged-in, stop and tell the human to
run `gh auth login` (suggest the `! gh auth login` in-session form). Do not
attempt to authenticate on their behalf.

## Step 1: Dry-run first — always

Run the planner read-only, regardless of whether the human asked for
`--execute`:

```bash
python3 scripts/pr_dependabot.py [--repo owner/name]
```

Print the plan verbatim. It lists each open Dependabot PR with its classified
action (`merge` / `hold` / `surface` / `close-pip` / `close-superseded`), the
CI + mergeable gate for merge candidates, and a one-line reason. If the output
is "No open Dependabot PRs. Nothing to sweep.", stop here — nothing to do.

## Step 2: Gate on human confirmation before executing

If the human invoked `--execute`, **still pause after the dry-run** and confirm
the plan looks right before running it — merges are hard to walk back. Only
after confirmation:

```bash
python3 scripts/pr_dependabot.py --execute [--repo owner/name]
```

The executor re-checks each merge candidate at merge time: it polls `gh pr view`
until `mergeable` resolves out of `UNKNOWN` (GitHub computes it lazily), and
**skips any PR whose CI is not green or whose `mergeable` is not `MERGEABLE`** —
a red or conflicted PR is left open, never force-merged. pip and superseded PRs
are closed with an explanatory comment. Print the executor's result lines
verbatim.

## Step 3: Report what's left for the human

After a sweep, the `hold` and `surface` PRs remain open by design — they need
human judgment (majors, untrusted-publisher Action bumps, grouped/security
updates that don't parse to a single semver). Briefly list them so the human
knows what to look at next. Do not merge them.

## Classification policy (reference)

Validated against ~50 real Dependabot PRs (see Phase 53 in `PHASE_LOG.md`). The
rules live in `scripts/pr_dependabot.py`; this table is the human-readable map.

| Class | Action | Rule |
|---|---|---|
| npm / docker **patch** or **minor** | **merge** | auto-merge if CI green + `MERGEABLE` |
| github-actions **patch**/**minor**, trusted publisher | **merge** | same gate; publisher must be on the allowlist |
| github-actions **patch**/**minor**, *untrusted* publisher | **surface** | supply-chain risk — Actions run in CI with secrets |
| **any** ecosystem **major** | **hold** | human review (even trusted publishers) |
| pip / `chore(deps)` | **close-pip** | Python deps owned by the pip-compile workflow |
| superseded duplicate | **close-superseded** | older open PR for same package+dir, lower target |
| grouped / unparseable version | **surface** | no single semver to decide on |

Two rules are deliberate improvements over a naive auto-merge:

1. **Majors are held even from trusted publishers.** The real history had a
   trusted-publisher allowlist that merged a *major* Action bump (`gitleaks
   2→3`) because it ignored semver. Here, semver wins: any major is held.
2. **github-actions auto-merge requires a trusted publisher.** A malicious
   Action update runs in CI with repository secrets — a higher-stakes
   supply-chain surface than an npm devDependency. The allowlist
   (`TRUSTED_ACTION_PUBLISHERS` in the script) is a constant consumers edit.

### Supersession is scoped to the currently-open set

`close-superseded` only fires when **two or more PRs are open *right now*** for
the same package + directory; it keeps the highest target version and closes the
rest. It is **never** computed over history — the same package is bumped
repeatedly over weeks, each PR merging before the next opens, and a
history-scoped check would false-flag every earlier bump. Dependabot also
auto-closes its own superseded PRs ("Looks like X is up-to-date now"), so this
handler is a safety net for the race window, not a primary job.

## Replacing a server-side auto-merge workflow

If the consumer repo has a broken `.github/workflows/dependabot-automerge.yml`
(the common case that motivates this skill — it fails on Free-plan private repos
with `GraphQL: Auto merge is not allowed for this repository`), this skill
*replaces* it. Retiring that workflow is the consumer's call, not this skill's:
note it in the report so the human can delete the dead workflow, but do not edit
`.github/` yourself.

## Deferred features

- **`pr-review`** — the sibling skill for human (non-bot) PRs. Different
  problem: human PRs need judgment, not a semver lookup. Deferred until it earns
  its way in from real use.
- **Scheduled/unattended sweeps** — pairs naturally with `/loop` or `/schedule`,
  but keep the human in the loop until the merge policy has run clean across a
  few weeks of real backlogs.
- **Renovate / non-GitHub hosts** — siblings, not options on this skill.
- **Docker digest bumps** (no semver in the title) currently classify as
  `surface`. Revisit if a consumer's digest-update volume makes that toil.
