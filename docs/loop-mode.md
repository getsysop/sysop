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
git add .agents/ 2>/dev/null   # only present when the Codex skill links were installed
git commit -m "chore: install Sysop (loop mode)"
```

Prerequisites are the same as any Sysop install (git, bash 4+ **to run the installer** — the
companion scripts it installs run on bash 3.2, so stock macOS is fine afterwards — Python 3 with PyYAML — see the
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

**Optional — folding in an outside scanner.** If you separately run Anthropic's `claude-security`
plugin, your next `/security-audit` folds its findings into the same ledger. The order of operations:
run `/claude-security` yourself as a top-level action (a deep, expensive, occasional pass — quarterly is
a reasonable cadence, and it may not finish in one session), let it write its `CLAUDE-SECURITY-<timestamp>/`
report to your repo root, then run `/security-audit`. In-scope findings land under their own batch tagged
`[reported]` — filed from someone else's read, so confirm at the source before acting on one. Sysop only
ever *reads* such a report; it cannot launch the plugin, and when no report is present this step is
silent and nothing degrades.

Why bother: in one head-to-head — 2026-07-23, a single production codebase at one pinned commit — the
two tools' findings did not overlap at all. One run, not a general property, but it fits the mechanism:
a convention loop's deterministic floor is built from patterns somebody already ratified, and an outside
scanner isn't.

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

**Closed 2026-08-12: the semgrep stage used to skip test directories silently.** For the
record, because the limitation was published here and the workaround it recommended is no
longer needed. The pre-scan handed semgrep a directory, so semgrep's built-in default ignore
list dropped `test/`, `tests/`, `testsuite/` and `*_test.go` at any depth before they became
candidates — and discovery-excluded files never appear in `paths.skipped`, so the stage
reported "executed, 0 findings" over surface it had never read. Deterministic means
repeatable, not complete: shipped checks have been caught blind to part of their declared
subject before, which is why checks are maintained like code — with a demotion path for the
ones caught misfiring.

The pre-scan now keeps the directory operand and **adds the dropped files as explicit
operands**, which is the part that makes it work: semgrep applies its default ignore list to
what it discovers under a directory, but not to a file you name. (Naming the *directory*
recovers nothing — measured.) Everything the directory operand did, it still does: untracked
files are still scanned, the bundled-fixture exclusion still applies, symlinks and
mid-rename files still can't abort the scan, and it remains a single subprocess under one
timeout. Very large test trees have a ceiling — the recovered files travel on the command
line, so past the platform's exec limit the stage reports `degraded` and names how many it
omitted rather than quietly scanning fewer.

**If you keep a `.semgrepignore`, it wins and this recovery switches off entirely.** That is
deliberate: a project `.semgrepignore` already replaces semgrep's built-in list wholesale, so
there is nothing left to recover, and naming files explicitly would override exclusions you
chose on purpose.

**If you added the empty `.semgrepignore` this page used to recommend, the honest advice is
now "keep it or replace it, but don't just delete it."** Deleting it does get your test tree
scanned — the fix handles that — but it also hands `build/`, `vendor/`, `dist/`,
`node_modules/`, `.venv/`, `.tox/` and minified bundles back to semgrep's built-in list, and
files dropped that way are **as invisible as the test tree used to be**: they never appear in
the pre-scan's `paths.skipped`. If you carry committed dependency source (Go and PHP composer
both use `vendor/`), the better move is to keep a `.semgrepignore` listing everything on
semgrep's default list *except* the test entries.

**Expect new findings on your first run after updating**, from rules that were always enabled
over files they never actually saw. How many depends on your rules' `paths:` scope. On a fresh
install the shipped packs' scoping is still placeholder vocabulary, which is treated as
whole-tree, so test findings surface immediately. Once you localize `paths:` to your source
directories, rules scoped away from tests stop contributing — though localizing to `.`, which
is a legitimate choice for a small repo whose whole tree is source, keeps them all in scope.
Triage them the usual way, or accept the current state with `run_checks.sh --update-baseline`
(which snapshots *every* outstanding finding, not only these). To accept one finding rather than all of them, take its key from `run_checks.sh --print-keys` and add that line by hand — for grep and semgrep findings the key carries a content hash, so it cannot be typed from what the finding prints. If you are upgrading a project that already had a baseline, run `run_checks.sh --migrate-baseline` once: it converts your entries in place and keeps your comments, which `--update-baseline` does not.

One rule was re-scoped rather than left to your triage. `semgrep-recompile-inside-def` scopes
its own rationale to *"request handlers and hot-path code"*, and a test body is categorically
not that — so it now carries `exclude_dir: ["test", "tests", "testsuite"]` and skips those
directories at any depth. Measured on the Sysop tree, that is 15 of the newly-visible findings
on a fresh install and none at all once `paths:` is localized to real source directories. Every
other rule still reads your test tree, which is the point of the fix above.

## If you send friction upstream, check where it lands first

Loop mode ships two skills that file *outward*, to the Sysop repo rather than yours:
`/report-issues` (friction from `sysop/SYSOP_ISSUES.md`) and `/contribute-convention`
(conventions your project promoted locally). Both default to **`getsysop/sysop`, which is
public** — and friction entries have a habit of quoting the security context that produced the
friction.

If anything in your log or overlay should not land in a public repo, name your own target in
your project's `CLAUDE.md`:

```markdown
## Sysop upstream repo

`your-org/sysop`
```

That is the durable setting — a per-run `--repo owner/name` still overrides it, and with no
section at all the public default applies. Both skills check the resolved target's visibility
before filing and warn when security-sounding content is headed somewhere public, or somewhere
they could not verify. They are prompts, not enforcement: they warn and ask, they never redact
for you, and nothing is filed without your per-item consent. Full reference:
`.claude/skills/_shared/upstream-repo.md`, shipped with your install.

(The third give-back skill, `/share-wins`, is full-mode only — you will not have it here.)

## Updating — and growing into the full workflow

Updates work the same as any install: `bash sysop/scripts/sysop-update.sh` (after setting
`$SYSOP_SRC` — see [install-and-update.md](./install-and-update.md#updating-an-existing-install)).
The lock's `mode: loop` means an update re-applies the loop shape — it won't quietly grow you a
task queue.

If the loop earns its keep and you want the rest — planning, the queue, parallel builds under
one merge gate — the upgrade is one flag: `bash sysop/install.sh <target> --update --mode full`
(run from wherever your Sysop clone lives). It's purely additive: lifecycle skills, scripts,
and the `tasks/` scaffold are added; nothing the loop has learned is touched. Then review and
commit what it added — `git add .claude/ sysop/ tasks/ .gitignore; git add .agents/ 2>/dev/null; git commit -m "chore: grow
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

## What loop mode does not promise

**On some models, half of loop mode does not run.** The two review skills are prose, and a model
is free to decline the work: on one frontier non-Claude model, `/security-audit` was refused
outright on repeated attempts — once before doing anything, and once after a minute of real work.
A refused round is not a failure you can see. It writes no `review_tasks.md` entries and raises
no error, so it looks exactly like a clean round.

Sysop's answer is to make the absence visible rather than to talk a model past its own refusal
(which would no longer be measuring the skill). A refusal shows up in one of two shapes — and a
quieter third neighbor, a round that ran but barely looked, completes the set. Each has its own
surface:

- **Died partway** (refused after starting, crashed, ran out of context). Each round opens a
  marker under `sysop/runtime/pending-rounds/` and clears it only once findings are written, so a
  marker that outlives its round is the trace. The pre-scan summary repeats that stale-marker line
  every round — so this shape reaches you during ordinary work, not only when you go looking.
- **Refused before starting** (declined the task class outright). This writes no marker — nothing
  ran to write one — so the only trace is an **asymmetric history**: quality rounds recorded but no
  security audit ever completed. `bash sysop/scripts/self_check.sh` reports it. It is advisory, not
  a failure, because that trace is identical to "you simply haven't run the audit here yet" — run
  or schedule `self_check.sh` to catch this shape.

- **Ran, but barely** (completed normally, having looked at almost nothing). The quietest shape, and
  the one that reads cleanest: a round that opens a handful of files on a large repository still
  produces real findings, a normal-looking round, and no error. Every round therefore records a
  **coverage ledger** — `manifest`, `opened`, `grepped`, `workers` — in its `review_tasks.md` round
  header, so the denominator always sits beside the numerator. `self_check.sh` reports the last
  round's line, and calls out a round that declared a *full* pass while reaching under a third of
  its own declared scope. A thin round that says it was thin is correct and passes silently — what
  gets reported is a round whose numbers contradict its own label.

The honest limit that shapes all three: nothing running *inside* a round can detect a refusal that
happens before the round starts, and the coverage numbers are self-reported — nothing counts file
reads for you. That is precisely why these checks live outside the round — and why the before-start
shape is caught by a probe you run, not by the every-round pre-scan line. What the ledger buys is
that the count must now exist beside its denominator, where `opened 13 · manifest 1,477` refutes
itself on sight.

## What loop mode is not

It won't plan your work, order a backlog, isolate builds in worktrees, or gate your merges —
that's the full workflow's job, and the [tutorial](./getting-started.md) is its walkthrough.
Loop mode is the smallest honest slice of Sysop: reviews that remember, rules you ratified, and
checks the computer runs identically every time.
