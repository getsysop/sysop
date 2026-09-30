# `/security-audit` — editor reference

**You are reading this because you are about to change the skill, not run it.**

`SKILL.md` is the runner. It carries procedure, commands, and a one-line reason **only where the
reason changes what the runner does**. This file carries what the *editor* needs: what a rule
protects, what its loss or softening would change, and where it came from.

Claude Code does not load a skill's sibling files automatically — they are read only when
something points at them — so this file costs the runner nothing and the editor pays for it once.

Notes here anchor to **rule ids and step headings, never line numbers.**

---

## Where new rationale goes

**New rationale is authored here, not in the runner.** When you add a rule to `SKILL.md`, the
runner gets the instruction and — only if it changes what the runner does — one line of reason.
The justification, what the rule's loss or softening would change, and the provenance go here.

This is a rule about *where text is written*, not a size budget. A skill may grow as much as the
work requires; what it may not do is grow by accumulating, in the file an agent reads at runtime,
material that only an editor ever needs.

The case for it is arithmetic rather than taste. Every rule in a runner was added because a review
round asked for it, so no single addition is wrong, and rationale accretes at a rate no later
tidying pass recovers — relocating text after the fact moves a fraction of what the next few
changes add. The cheap intervention is at the point of authorship, which is here.

## What is declared

**Nothing yet, and this file is not coverage.** `/review-close` carries a roster of declared
load-bearing rules, each pinned verbatim by a required check. security-audit has no such roster: its
rules are unprotected by construction, exactly as they were before this file existed.

What this file is, today, is a **destination** — the place the rule above sends rationale, so that
the convention has somewhere to point on the day someone writes the next rule for the security audit. Sections
get added here as rules are declared; an empty roster is an honest statement of where the work has
reached, not a gap to paper over.

## What this skill's rules tend to be about

`/security-audit` runs a deterministic pre-scan and then an anchor-typed review — so most of its
rules are about coverage: what the scan is allowed to skip, and what a skip must record. The reason
a rule exists is usually a finding class that went missing when it did not.

---

*Sections below this line are editor rationale for single rules, not declared rules.*

## Step 9b — why the demotion commit is its own

Step 9's promotion commit has already been made by the time 9b runs, so "folding" 9b's changes
into it would be `git commit --amend`. No seeded allow-rule matches an amend: under `dontAsk` it is
denied, and interactively it asks to rewrite a commit that may already be pushed. A second
commit has the same `git commit -m "docs: …"` shape as Step 9's, so whatever the seeded
`docs:` rule allows for one it allows for the other.

## Pre-commit letters — why the runner tells the human to re-arm, and never arms

`install.sh` and the arm script arm hooks by **copying** `sysop/scripts/hooks/*` into git's
hooks directory, so a letter added, deleted or moved in the template changes nothing until the
copy is refreshed. A skill may not run the arm script itself, and may not even name it
(`tests/test_hook_autoarm_drift.py`, from Phase 150). An agent arming from a worktree pushes that
worktree's hook bodies into the one shared hooks directory, which can replace a consumer's armed
checks. `self_check.sh` reports an armed hook whose bytes differ from its template.

## Step 5f — why the receipt reads the `Fan-out coverage` line

The per-worker `opened/assigned` ratios were first printed only in the post-scan report, which
dies with the terminal; in a measured round one harness printed them and another printed none
while one of its workers had read 31 of 547 files. Step 5b's header line made them durable, and
Step 5f now carries them into the receipt, where `/sitrep` can see a fan-out round that closed
without them. What each choice protects:

- **The receipt key is `fanout`, not a field on the coverage line.** The coverage line has a fixed
  field set that `parse_coverage` reads per segment; a fifth kind of value there would change what
  every reader of that line sees. The key sits ahead of `"line"` for the same reason `tracked`
  does: `self_check.sh` extracts the coverage line with a greedy `sed` that relies on `"line"`
  being the last key.
- **Three values, each meaning one thing.** A dict (`text`, `ratios`, `waves`) when the line is
  present; `"unreported"` only when `workers` is an int above 0 and the line is absent; `null`
  otherwise. A solo round needs no line, and a round whose `workers` is itself unreported is
  already named by the `unreported field(s)` print, so neither is reported twice. `/sitrep` keys
  on the exact string `"unreported"`, so a receipt written before this key existed stays silent.
- **The two lines can never be read as each other.** The coverage selector matches `Coverage`
  (case-sensitive, as before) but skips any line whose quote *begins* with the fan-out label in any
  case; the fan-out selector takes only lines that begin with it. Before this, a `Fan-out Coverage
  (code quality)` line would have made the coverage line ambiguous and dropped the round's whole
  ledger to `unreported`.
- **The tag is matched in the `(…)` label, not the whole line** — for both lines. A quality round's
  `Sampled (security-relevant modules)` used to make its line a second match for the security
  reader, which then recorded the security round as `unreported`. A label outranks text: a line
  whose label names this skill wins over one that only mentions it. Only when no label names this
  skill does the selector fall back to the line's text, and then only over lines whose label names
  **neither** skill, which is the old behaviour for label-less and non-template labels.
- **A lone line labelled for the other skill is not this skill's.** The old fallback handed a
  merged round's single `(code quality)` line to a closing `security-audit`, crediting a security
  round with a quality round's files. And a marker naming neither skill (a missing `skill:` field
  reads `unknown`) selects nothing, instead of falling silently to the quality tag: a receipt that
  says `unreported` is honest, one that carries the other skill's numbers is not.
- **Lines below the first batch are not read**, on purpose: a `> Coverage` there is batch prose.
  So Step 5b's merged-round instruction says where the second skill's lines go, above Batch 1.
- **A lone unlabelled fan-out line is taken only when the header holds at most one coverage
  line.** In a merged round it could be either skill's, and taking the other skill's line would
  silence the warning for the skill that omitted its own. Missing is loud; wrong is silent.
- **The ratio parse is all-or-nothing.** An item that is not exactly
  `[<label>] <opened>/<assigned>` makes `ratios` `unreported`, with the text kept beside it: a
  partial list reads as fewer workers than ran. A comma followed by a space separates items; a
  comma between digits is a thousands mark. Step 3c's report ends its ratios with
  `; <B> batch(es) flagged low-opened`, and Step 5b says to copy those ratios, so that tail is
  dropped before parsing rather than refusing the list.
- **`FANOUT-UNREPORTED` warns, never aborts**, for the reason the `LOW-LOOK` comment gives: the
  marker must still clear. It is a stable token for tests and greps. It prints before the Step 7
  commit, so the header can still gain the line for the record, but the receipt is already written
  and is never rewritten: it stays `unreported`, and `/sitrep`'s discrepancy clears only when the
  next round writes its own receipt. Both messages say so, so neither promises a fix that cannot
  land.

## Step 3 — why a denied placement falls back to no isolation, and why its rules are not in the pre-flight

`isolation: "worktree"` alone forks each agent from the default branch. Run off that branch, an
unplaced agent audits a tree that does not contain the work, and its report reads exactly like a
clean one — `Q-489`, measured on at least 13 reviewers across Phases 284–287 of this repo's own
rounds. So an isolated agent that could not be placed is never dispatched. When `git worktree add`
is denied, the runner dispatches without `isolation` instead, in its own checkout, which is at the
commit under review: the right tree, with the containment the harness-without-isolation case
uses. Both arms snapshot status, commit and branch (`git symbolic-ref -q HEAD`), because each
misses something alone. Measured on git 2.50.1: checking out another branch leaves the status
equal and moves `HEAD`; `git switch -qc <new>` leaves status AND commit equal and moves only the
branch, and the runner's next commit then lands on the agent's branch. Until `Q-588`
the skill left the choice to the runner; Phase 333 first made a denial stop the fan-out, and Wade
replaced that with this fallback, because a stop costs the whole round over a missing rule when a
round on the right tree is available without it.

Placement applies only off the default branch. On it, bare `isolation` already lands every agent on
the right tree, so the runner text says a denied `add` changes nothing there, and scopes the
fallback to off-default runs so a literal reader keeps bare isolation on it. A denied `remove`
(with `add` allowed) is a different case from git refusing: the runner leaves the checkout and
names the rule, because a checkout outside the repository costs nothing to leave; the pre-flight
note says which of the two missing rules does what.

Loop mode shipped the placement rule with no allow-rule behind it until Phase 333 (`Q-588`):
`install.sh`'s `LOOP_ALLOW` now seeds `git worktree add` and `git worktree remove`. `remove` is
there because a placed checkout is otherwise left registered, with no way to clear it under
`dontAsk`. There is no `list` rule, because neither skill prescribes one.

`git worktree remove` refuses a checkout holding untracked files (exit 128). Measured in a
throwaway repo (git 2.50.1): a `.venv` symlink placed per `_shared/adversarial-review.md` makes it
refuse when `.gitignore` has no `.venv` entry, and when its only entry is the directory-only
form (`.venv/`, `/.venv/`), which does not match a symlink. `.venv`, `/.venv` and `.venv*` all
match it, and then there is nothing to refuse. So when the
only untracked entry is `?? .venv`, the runner's own symlink, the checkout is removed with
`--force`; with anything else untracked it is left in place and its status is reported. **What
that protects is narrower than it sounds.** Untracked files an agent wrote into **gitignored**
paths (`sysop/runtime/…`, for one) do not appear in `git status --porcelain -uall` and do not make
`git worktree remove` refuse: a plain `remove` deletes them, measured the same way. So leaving a
refused checkout preserves only an agent's writes to un-ignored paths. Writes to ignored paths are
lost on any removal, forced or not; a round that needs them must read them before removing.

The two rules are named in the pre-flight as a condition rather than in its hard-stop list: the
dominant run, from the default branch, places no agent and must not be stopped for a rule it will
not use (Wade's decision, Phase 333), and a missing rule no longer stops anything. Only the bare
`git worktree …` spelling binds `Bash(git worktree add:*)` or `Bash(git worktree remove:*)` — a
rule's prefix is matched literally, so anything in front of `git worktree` — a global option
(`git -C <repo> …`, `git -c <key>=<value> …`), an assignment, a `cd … &&` — binds nothing.
`tests/test_loop_worktree_placement.py` refuses every such spelling in any loop-shipped
`SKILL.md` and ties every `git worktree` subcommand those runners
name to `LOOP_ALLOW`; the whole placement paragraph and the pre-flight's stop-and-note paragraph
are hash-pinned in `tests/test_fix_in_branch_tier.py`'s `PINNED_SPANS`, each from its opener to
the next paragraph's lead, so nothing can be added beside them unseen.

## Step 3 — why each agent gets its own scratch directory

The containment rule once told every agent to *"compute from a heredoc or write under `/tmp`"*,
one unscoped location for the whole fan-out. `/review-close` Step 2b carried the same sentence,
and a consumer measured the harm there (internal tracker #705): one reviewer's captured diff was replaced
by a sibling's between two of its own reads, so it would have reported on content it never
produced. The fan-out here has the same shape, several agents at once each handed the same place
to write, so it has the same exposure. The orchestrator therefore creates one `mktemp -d` per agent and writes each path into its agent's
prompt. Telling agents to use distinct filenames was refused, because it relies on every agent
complying; the orchestrator's substitution does not.

**A printed path inside the repository gets the same answer as a denied `mktemp`.** The runner
text used to say "write under `/tmp`", a literal that is never inside a repository. The
replacement uses `${TMPDIR:-/tmp}`, and a project-local `TMPDIR` (legal, and used by several CI
images and nix shells) puts it in the tree, where a compliant agent's scratch file then reads as a
breach in the step's own after-dispatch snapshot. The round measured exactly that, so the runner
asks git of each printed path (`git -C <path> rev-parse --show-toplevel`) rather than trusting the
temp dir or comparing strings: `mktemp` prints the path as spelled, which on macOS is `/var/…`
while git answers `/private/var/…`, and a string check is also beaten by case. The command itself
makes each path absolute (`$(cd "${TMPDIR:-/tmp}" && pwd -P)`): a relative `TMPDIR` otherwise
prints a relative path, which each agent resolves against its own working directory.

All the `mktemp` calls go in one Bash call, so a harness that asks per call asks once, not once per
agent. No rule is seeded for `mktemp`, in either mode. A loop-mode run under `dontAsk` may be denied
it, so the runner then writes `(none — write no file)` in the placeholder. The agent is left with
heredocs only, which is the fail-safe direction: it can still compute, and it cannot collide with a
sibling. Seeding a rule was not done here, because it would widen the permission surface of every
install to buy a scratch file that a heredoc already replaces.

## Step 7 — why the claude-security mark names its scope, and carries a digest

Step 3c buckets an ingested report's findings by the round's scope file and promises the
out-of-scope ones come back on a later round whose scope reaches them, or the next `--full` round.
Until Phase 338 the mark after the round recorded the report whole, and a recorded report was never
read again, so on every scoped round those findings were counted in the summary and then lost.
The mark now records only the findings the round folded; the report is offered again
carrying the rest, and goes whole once every finding it emits is recorded.

**The scope flag is required, not defaulted.** A mark with neither `--scope-file` nor `--full` is
refused, because the old default — the whole report — is the defect.

**Why a digest and not just the scope file.** `sysop/runtime/audit-scope.txt` is a fixed name.
A concurrent round can rewrite it between Step 3c's ingest and Step 7's mark, and the mark would then
record the other round's in-scope findings as folded: a finding this round never filed would be
hidden for good. The ingest prints `scope_digest`, and a scoped mark refuses when the file no longer
matches it; the report is then offered again without anything that mark would have recorded,
which re-files rather than loses. The digest
also keeps an older script from taking a scoped mark: before Phase 338 the script ignored
`--scope-file` beside `--mark` and recorded the report whole, and it does not know
`--scope-digest`, so argparse exits 2 before anything is written. The plugin and bash-installer
paths update independently, so a consumer can hold the new skill and the old script. That pairing
never lands a mark (a scoped round has no digest to pass, and the old script does not know
`--full` either), so every report is offered whole each round and Step 4 re-files every fixed
finding as a possible regression, the cost that ruled out re-folding whole reports. The skill
tells the runner to name the update rather than fall back to a bare mark, because the bare mark is
the defect.

**Why the mark runs after the commit.** A recorded finding is never offered again, so its task
must already be durable. A mark before the commit that then fails loses the finding.

**Why "never `--full` when 3c passed `--scope-file`" is keyed to the ingest and not to the round's
name.** Step 1 allows `--full --scope <area>`, and Step 3c decides by the round's mode, so the two
readings can differ on such a round. The mark must declare the scope the ingest actually bucketed
with — whether Step 3c passed a scope file — whatever the round is called.
