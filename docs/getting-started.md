# Getting Started with Sysop

A hands-on walkthrough: from installing Sysop into one of your own projects to shipping
your first change through the full loop. Budget 20–30 minutes — most of it is the
planning conversation in step 2, which is as long or short as you want.

By the end you'll have done the whole cycle once: a task queue you planned *with* the
agent, one task built in an isolated worktree behind an adversarial plan review, and that
change reviewed and merged to `main`. That's the same loop Sysop runs every day — this guide
just walks you through it the first time. In the [monograph](./workflow.html)'s frame — a
project's arc of *plan · execute · maintain* — this walkthrough is the first two phases:
`/intake` plans, `/claim-task` through `/review-close` executes. The third, *maintain*,
enters at the end, once there's merged code to keep clean.

> **Want the "why" first?** This is the *tutorial* (learn by doing). For what Sysop is and
> why it's shaped this way, skim [`workflow.html`](./workflow.html) (a 5-minute visual
> overview) or the [README](../README.md). The authoritative spec is
> [`WORKFLOW.md`](../core/companion/docs/WORKFLOW.md); you don't need it to follow along here.

## Before you start

You'll need:

- **A decided idea.** Sysop's on-ramp is planning: `/intake` assumes you already know *what*
  you're building and turns it into a validated task queue. It will argue the weak points of
  your plan, but it deliberately won't tell you whether the thing is worth building —
  discovery (ideation, market research, validating demand) sits upstream of Sysop and is out
  of scope on purpose. If you're still choosing between ideas, settle that first and come
  back with the winner.
- **A git repository you can experiment in.** A real side project is ideal — Sysop works
  *on* your code, so the walkthrough is more satisfying with something you actually care
  about. If it's brand new, run `git init` first. (Nothing here is destructive: every
  change lands on a feature branch and you review it before it merges.)
- **Claude Code.** This walkthrough drives Sysop through Claude Code's slash commands — the
  fastest way to see the whole loop. (Sysop's companion scripts and docs are agent-neutral
  and run standalone; see [*Running on another agent*](#running-on-another-agent) at the end.)
- **Bash 4+.** The installer uses associative arrays. macOS ships `/bin/bash` 3.2 by
  default — run `bash --version`, and if it's 3.x, `brew install bash` first. On Windows,
  run the installer and scripts under WSL (Git Bash may work, but its worktree/symlink
  support is flakier and unverified); native Windows isn't supported.
- **Python 3 with PyYAML.** The check runner (`sysop/scripts/run_checks.sh`) needs it. Install
  it in your project's venv (`python3 -m venv .venv && .venv/bin/pip install pyyaml`) — the
  check runner resolves the repo's `.venv` on its own, no activation needed. Note that a bare
  `pip install pyyaml` refuses on externally-managed Pythons (PEP 668 — modern Homebrew
  macOS and Debian included); the venv is the path of least resistance.

Everything you "send" below is a slash command you type to Claude Code while it's open in
your project.

## 1. Install Sysop

Clone Sysop once, then install it into your project:

```bash
git clone https://github.com/getsysop/sysop.git
bash sysop/install.sh /path/to/your/project --packs auto
cd /path/to/your/project
bash sysop/scripts/self_check.sh                        # one-command prereq check: bash, PyYAML, hooks
git status                                              # review everything Sysop wrote
git add .claude/ sysop/ tasks/ CLAUDE.md .gitignore
git commit -m "chore: install Sysop"
```

- **`--packs auto`** auto-detects your stack (a `pyproject.toml` pulls in the `python`
  pack, `next.config.js` the `nextjs-react` pack, and so on). Omit `--packs` entirely for
  an interactive picker, or name them explicitly: `--packs python,postgres`. Add
  `--dry-run` first if you want to preview without writing anything.
- **Started with `--mode loop`?** (The README quickstart's recommended first install for an
  existing codebase.) This guide is the graduation path: grow the install in place with
  `bash sysop/install.sh /path/to/your/project --update --mode full` — purely additive,
  nothing the loop has learned is touched — commit what it added
  (`git add .claude/ sysop/ tasks/ .gitignore`), then skip step 1 and continue from step 2.
  Loop mode's own day-one walkthrough is [`docs/loop-mode.md`](./loop-mode.md); the guide
  you're reading assumes the full install.
- **What landed:** a `.claude/` directory (the lifecycle skills, the convention and
  security maps, the deterministic checks, and a permission allow-list), a `sysop/` vendor
  directory (`sysop/scripts/` — the check runner and the claim/close/validate machinery —
  `sysop/docs/` with `WORKFLOW.md` + `WORKFLOW_GUIDE.md`, and a `sysop/SYSOP_ISSUES.md` friction
  log), and a `tasks/` scaffold. Commit them all — the workflow uses git worktrees, and an
  isolated worktree only sees files you've committed, so an uncommitted `sysop/` would be
  missing exactly where later steps need it.

> **Command names.** After a bash install the skills are available under their bare names —
> `/intake`, `/claim-task`, and so on. If you *also* add the Claude Code plugin
> (`/plugin marketplace add getsysop/sysop` then `/plugin install sysop@sysop`), the same commands
> appear namespaced as `/sysop:intake`. This guide uses the bare form.

> **Newer to this style of workflow?** Sysop has a **guided (teaching) mode** that, at every
> point a skill would ask you to approve or choose something, explains the decision plainly,
> stress-tests its own recommendation, and only hands you the calls that are genuinely
> yours — taking a safe default on anything you couldn't fairly weigh. Turn it on by copying
> the `## Guided mode` section from [`WORKFLOW.md`](../core/companion/docs/WORKFLOW.md) §6.1
> into your project's `CLAUDE.md` (create that file at your repo root if you don't have one).
> Remove that section any time to return to the default.

## 2. Plan your first queue — `/intake`

> **Bringing an existing project into Sysop instead of starting fresh?** This walkthrough
> assumes a new project. On an existing one, `/intake` will notice (real code, maybe a
> backlog, no `tasks/vision.md`/`decisions.md`) and offer **`/onboard`** — which, with your
> consent at every step, drafts the vision/decisions files from your repo's own evidence
> (README, docs, git history; its inferences are marked and confirmed with you, never
> asserted) and/or imports an existing `ROADMAP.md`, `TODO.md`, or open GitHub issues into
> the task queue. Everything lands uncommitted; your commit is the sign-off. Then rejoin
> this walkthrough at step 3 — the rest of the lifecycle is identical.

`install.sh` seeds an *empty* queue — nothing to build yet. `/intake` is the planning front
door that fills it. Send:

```
/intake
```

It runs a conversation, not a form. Expect this shape:

1. **Brain-dump** — it invites you to describe the problem, who it's for, and what you
   picture building, all in one unstructured pass. You talk; it organizes.
2. **Playback** — it reflects your intent back as a compact summary and marks anything it
   inferred, so misunderstandings get caught before they're baked into a plan.
3. **Sounding-board** — it has opinions and will argue against weak calls, but it never
   adjudicates whether the *idea* is worth pursuing — that stays yours.
4. **Phases & priority** — it proposes a first phase decomposed into concrete tasks, with
   later phases kept deliberately coarse.
5. **Emit** — it writes the queue to disk and leaves it **uncommitted** so the commit is
   your sign-off.

You'll get three things: `tasks/vision.md` (the durable *why*), `tasks/decisions.md` (the
technical-decisions record), and `tasks/index.yml` + `tasks/open/<TASK-ID>.md` bodies (the
actual backlog). Read the roadmap and a couple of task bodies, then commit:

```bash
git add tasks/ && git commit -m "plan: initial roadmap"
```

> **Already have a brief?** Pass it in: `/intake path/to/brief.md` (or paste the text
> inline). `/intake` is re-enterable — run it again later to decompose the next phase as it
> comes into focus.

## 3. Build your first task — `/claim-task`

Open `tasks/index.yml` and pick a task ID to build first (they look like `FEAT-…`,
`TECH-…`, `FIX-…`). Then send:

```
/claim-task FEAT-YOUR-FIRST-TASK
```

Here's what it does, and why each part matters:

- **Claims the task** — flips it to `in_progress` and takes a lock so parallel sessions
  don't collide.
- **Creates an isolated worktree** — a sibling checkout at `../<your-project>-feat-…` on a
  fresh feature branch. Your main checkout stays untouched; you can keep working in it.
- **Looks up the conventions that apply** to the files it's about to touch (from
  `.claude/convention_map.md`), so it follows your project's learned rules instead of
  generic defaults.
- **Plans, then stress-tests the plan** — it drafts an approach and runs an *adversarial
  review* of that plan (a fresh-eyes pass looking for what's wrong) before writing any code.
  This is the step most likely to feel unfamiliar and most likely to save you: catching a
  bad approach at the plan stage is far cheaper than at review.
- **Implements** the task in the worktree, following the conventions it looked up. (The
  deterministic check gate runs later, at `/review-close` — see step 5.)

When it finishes it prints `Work in: <worktree path>`. That sibling worktree is where this
task's work lives; the follow-up commands below (`/document-work`) act on that task's
branch, so Claude Code runs them there within the same session — not against your main
checkout, which is still sitting on `main`.

> **Not sure which task to start with?** Send `/next-task` — it picks the best claimable
> task for you: unblocked tasks first, favoring the ones that unblock the most other work,
> and cheapest-effort first among equals.

## 4. Hand it off for review — `/document-work`

When the work is done, send:

```
/document-work
```

It commits the change with a conventional-commit message, writes a small deferred
documentation note (kept out of shared files so parallel branches don't conflict), and
pushes the feature branch. It ends by telling you to start a **fresh session** before
reviewing:

```
/clear
```

That handoff is deliberate. `/review-close` is designed to reconstruct everything it needs
from the committed branch — so a clean session reviews your work even-handedly, without the
implementation session's own rationalizations coloring the merge gate.

## 5. Review & merge — `/review-close`

In the fresh session — from your main checkout, where you started — send:

```
/review-close
```

This is the final gate. Because it surveys *every* branch waiting to merge (not just this
one), run it from your main checkout rather than the worktree. It reviews each pending
branch against its plan and your conventions, runs the deterministic checks, merges what
passes to `main`, and cleans up the worktree.

> **Have an end-to-end or QA suite?** A Playwright, Cypress, or integration-test run plugs
> in as one more command under `## Pre-merge verification` → `### Always` in your project's
> `CLAUDE.md` — `/review-close` runs it on every merge, no Sysop-side wiring. See
> [`WORKFLOW.md`](../core/companion/docs/WORKFLOW.md) §6.1.

By default it pushes to `main` directly. If your `main` is push-protected, route it through
a pull request instead by adding this to your `CLAUDE.md` (create the file at your repo root
if you don't have one):

```markdown
## Merge policy

pr
```

Both policies are documented in [`WORKFLOW.md`](../core/companion/docs/WORKFLOW.md) §2.8.

For `pr` to actually *enforce* anything, `main` needs a required CI check (local git
hooks can be bypassed with `--no-verify`). Sysop ships one ready to go —
`cp sysop/scripts/ci/sysop-checks.yml.example .github/workflows/sysop-checks.yml`, fill its two
`TODO` steps, then mark the `sysop-checks` check required in your branch-protection rules.
See [`WORKFLOW.md`](../core/companion/docs/WORKFLOW.md) §6.1 "Protecting `main` with CI".

When it finishes, that change is shipped. **You just ran the whole loop.**

> Want to see the review reasoning without merging? `/review-close --dry-run` previews.

## What just happened — and where to go next

You planned a queue, built a task behind an adversarial plan review, and merged it — solo,
but with a full team's review discipline standing in. That was *plan* and *execute*; the
arc's third phase — *maintain* — is where the compounding lives, in the
**convention loop**: as you run `/codebase-review` and `/security-audit` over time, findings
that recur across rounds get promoted into written conventions, which the convention map
then surfaces automatically on every future `/claim-task`. Reviews shift from catching the
same defects again to catching new, subtler ones. (This loop is also the part of Sysop that
installs on its own — `--mode loop`, walked through in [`docs/loop-mode.md`](./loop-mode.md).)

A few skills worth knowing once you're past the first loop:

- **`/roadmap`** — "what's left, and in what order should I attack it?" — a strategic read
  of your queue.
- **`/daily-summary`** — "what happened?" — a retrospective of a day/week of commits and
  closed tasks.
- **`/sitrep`** — a fast, deterministic status check of any in-flight work (locks,
  worktrees, branches).
- **`/auto-build`** — builds several independent, non-overlapping tasks in parallel, then
  hands the batch to one `/review-close` sitting. Reach for it once one-at-a-time feels slow.

**Make it yours — without losing updates.** Sysop separates what you customize from what
it manages: your `CLAUDE.md` prose steers how every skill behaves, and never-managed
overlay files carry your config — project conventions (`.claude/*.project.*`) and which
model runs which skills (`.claude/served_models.local.yml`, e.g. one line to run the
deep-reasoning skills on Claude Fable 5 — applied on your next `sysop-update.sh` run).
Direct edits to shipped skill files are the one
thing that *doesn't* persist across `sysop-update.sh` — deliberately. The full story is
[`docs/configuration.md`](./configuration.md).

Go deeper when you want it: the visual overview is [`workflow.html`](./workflow.html), the
human-readable process guide is
[`WORKFLOW_GUIDE.md`](../core/companion/docs/WORKFLOW_GUIDE.md), and the authoritative spec
is [`WORKFLOW.md`](../core/companion/docs/WORKFLOW.md).

**Hit friction?** Jot it in `sysop/SYSOP_ISSUES.md` the moment you hit it — it's
freshest before the session moves on. On Claude Code, `/report-issues` turns those notes
into GitHub issues (showing you each one before it files). That feedback is how Sysop improves.

## Working alongside a build

Once you're running `/auto-build` (or several `/claim-task`s at once), a natural question is:
*what can I do in another session while a build is running?* Quite a lot — because each task
builds in its own **git worktree**: a separate directory (`~/Projects/<app>-<task-id>/`) on its
own branch. Your original clone stays on `main`; the building agents edit code somewhere else
entirely, so a second session doesn't step on them.

While work is in flight, in another session you can freely:

- **Brainstorm and plan** — you're only reading.
- **Add tasks** with `/add-task` — it appends to the queue and leaves it uncommitted; it can't
  collide with what's building.
- **Start another task** with `/claim-task <TASK-ID>` — it checks the lock, spins up a *new*
  worktree, and leaves `main` alone.

The one habit to build: **start new work through `/claim-task`, never by editing files on `main`
directly.** Freehand edits on `main` skip the worktree, branch, and lock that keep parallel work
safe — and a stray `git checkout` in your main clone can knock a running build's commits onto the
wrong branch. `/claim-task` sidesteps all of it.

Two things worth knowing before you fan out wide: the merge step (`/review-close`) is human-paced,
so past a handful of parallel branches you're usually gated by your own reviewing, not by Sysop;
and parallel tasks that share a test database or port can produce flaky failures — run those one
at a time. The full model — where work lives, what's safe, and the parallelism ceilings — is in
[§4.4 of `WORKFLOW.md`](../core/companion/docs/WORKFLOW.md).

## Backing out

Changed your mind — on one task, or on Sysop entirely? Both undo cleanly, because everything
Sysop writes is a tracked file (plus one set of git hooks). To reverse a single `/claim-task`,
run `bash sysop/scripts/claim_task.sh --release <TASK-ID>` from the main checkout — it releases the
lock, removes the worktree, and flips the task back to `open` in one consistent pass. To remove
Sysop from the project altogether (revert the install commit or `git rm` the payload, then disarm
the hooks), the exact steps are in [*Backing out*](../README.md#backing-out) in the README.

## Running on another agent

The lifecycle *skills* above are written for Claude Code, but Sysop's companion layer — the
check runner, the git hooks, the convention and security maps, the workflow docs — is plain
text with no Claude Code dependency, delivered by the same `bash install.sh`. The intent is
that the process runs on any capable agent, or none. That end-to-end portability is still
being validated against a non-Claude agent, so today the guided slash-command experience in
this guide is the Claude Code path; the underlying workflow is not Claude-specific.
