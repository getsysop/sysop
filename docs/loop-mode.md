# Loop mode — the convention loop on its own

Sysop's full install is a workflow: planning, a task queue, isolated worktrees, a single human
merge gate. **Loop mode is the front door.** `--mode loop` installs only the convention loop —
the review and audit skills, the convention and security maps, and the compiled checks — into a
repo where you keep your own planning, branching, and merge workflow. It's the recommended
first install for an existing codebase: the smallest honest slice of the system, the cheapest
to walk back, and the mechanism the published evidence measures — evidence gathered, to be
plain, inside full-workflow use on the source project. The full workflow is a one-flag
graduation when the loop has earned its keep.

This page is the day-one walkthrough for that install. The reference for the flag itself —
exactly what's included, switching modes, how updates behave — is
[install-and-update.md § Install modes](./install-and-update.md#install-modes-full-and-loop).

## Install

```bash
git clone https://github.com/getsysop/sysop.git
bash sysop/install.sh /path/to/your/project --packs auto --mode loop
cd /path/to/your/project
git status                                   # review everything Sysop wrote
git add .claude/ sysop/ CLAUDE.md .gitignore
git commit -m "chore: install Sysop (loop mode)"
```

Prerequisites are the same as any Sysop install (git, bash 4+, Python 3 with PyYAML — see the
[README Quickstart](../README.md#quickstart) for the macOS and Windows notes). `--packs auto`
detects your stack and installs the matching convention packs — packs are entirely loop-side
content (maps, checks, semgrep rules, and their support files), so every pack applies fully here.

What lands is deliberately less than the full install:

- **Five skills** in `.claude/skills/`: `/codebase-review` (quality), `/security-audit` (OWASP),
  `/test-audit` (test-suite health) — plus the give-back pair, `/report-issues` and
  `/contribute-convention`.
- **The maps**: `.claude/convention_map.md` and `.claude/security_map.md` (core + your packs,
  concatenated) — with never-managed `.project.*` sibling paths reserved for your own promoted
  rules (created when the first promotion lands, never touched by updates).
- **The checks**: `.claude/checks.yml`, semgrep rules with their fixtures, the `run_checks`
  runner under `sysop/scripts/`, two git hooks (armed at install — skeletons that block nothing
  until your project fills them in), and a CI workflow template in `sysop/scripts/ci/`.
- **A permission allow-list** (`.claude/settings.json`) scoped to what these skills actually
  run, and `.claude/sysop.lock` recording `mode: loop` so future updates re-apply the same shape.
- **`CLAUDE.md` stubs** for the three sections the audit skills read — `## Scope mapping`,
  `## Map coverage exclusions`, `## Security-critical always-include files` — appended only if
  your `CLAUDE.md` doesn't already have them (your existing content is never rewritten).

No `tasks/` queue, no worktrees, no `/claim-task` or `/review-close`, no workflow docs. Two
files are deliberately lazy rather than installed: `review_tasks.md` (the findings ledger) is
created by your first audit run, and `sysop/SYSOP_ISSUES.md` (the friction log) by your first
captured issue.

One note for Claude Code users: skip the plugin here. The five skills land project-side in
`.claude/skills/`, so a loop install needs nothing else — the plugin's additional commands are
the lifecycle skills, whose supporting scripts a loop install deliberately doesn't have.

## Day one: run a review

Open your agent in the project and run `/codebase-review`. It reads the convention maps, sweeps
your tree for files no map section covers, reviews against the rules that do match, and records
its findings in `review_tasks.md` — created on this first run, with everything filed under
`## Round 1`. Fix what's worth fixing, however you normally work; the ledger is the loop's
memory, not a queue you owe anything to.

`/security-audit` is the same motion with an OWASP lens; its findings file into the same
day's Round (or open the next one).
`/test-audit` assesses the test suite — gaps worth filling, dead weight worth retiring — and
only recommends; it never writes tests or gates anything.

A freshly installed pack isn't fully wired to your tree yet — shipped rules use placeholder
vocabulary (`<api module>`) that you localize as you go. The review's coverage sweep is what
drives that: it names the unmatched files and proposes real globs. How localization works, and
where your edits safely live, is [Anatomy of a pack rule](./packs.md); the mechanics are in
[configuration.md](./configuration.md).

## How the loop closes

Run the audits at whatever cadence suits the project. When a finding class recurs across rounds,
the skill proposes promoting it into a written convention — **you adjudicate every promotion;
nothing is learned autonomously.** Promoted rules are written to your `.project.*` overlay
files, which updates never touch, so what the loop learns about your project survives every
`sysop-update.sh`. Where a promoted convention is mechanically checkable, it's compiled into a
grep or semgrep check — after which that mistake has to get past a standing check, not a
memory, to happen twice. The loop also runs in reverse: a rule that keeps firing wrongly is
tracked in a false-positive ledger and proposed for demotion.

## Where enforcement lives

Loop mode has no merge gate — deliberately. Enforcement is the checks the computer runs:
promoted rules bite at the **pre-commit hook** (as its own check slots — armed at install;
re-arm with `sysop/scripts/install_hooks.sh` after editing) and/or at the shipped **CI
template**, which runs the full `run_checks` suite. You merge however you already merge. Both
hooks ship as skeletons that block nothing on day one; they gain teeth exactly as fast as your
project promotes mechanical rules.

## Updating — and growing into the full workflow

Updates work the same as any install: `bash sysop/scripts/sysop-update.sh` (after setting
`$SYSOP_SRC` — see [install-and-update.md](./install-and-update.md#updating-an-existing-install)).
The lock's `mode: loop` means an update re-applies the loop shape — it won't quietly grow you a
task queue.

If the loop earns its keep and you want the rest — planning, the queue, parallel builds under
one merge gate — the upgrade is one flag: `bash sysop/install.sh <target> --update --mode full`
(run from wherever your Sysop clone lives). It's purely additive: lifecycle skills, scripts,
and the `tasks/` scaffold are added; nothing the loop has learned is touched. Then review and
commit what it added — `git add .claude/ sysop/ tasks/ .gitignore && git commit -m "chore: grow
Sysop to full mode"` — worktree builds only see committed files.
[getting-started.md](./getting-started.md) walks the full workflow from there; you've already
installed, so skip its step 1 and start at step 2 (`/intake`). The reverse direction
(full → loop) is a fresh reinstall, not an update.

## Has this actually been run?

Yes, once, deliberately, before it shipped: the full loop was run end-to-end against a real
~60k-line open-source codebase — code the model didn't write. Install, three
review rounds, promotion, mechanization: the loop closed on foreign code, and one freshly
mechanized convention then caught an instance no review round had filed — the pitch of the
whole design, observed rather than claimed. That's one run on one project: evidence the
mechanism works end to end, not a benchmark.

## What loop mode is not

It won't plan your work, order a backlog, isolate builds in worktrees, or gate your merges —
that's the full workflow's job, and the [tutorial](./getting-started.md) is its walkthrough.
Loop mode is the smallest honest slice of Sysop: reviews that remember, rules you ratified, and
checks the computer runs identically every time.
