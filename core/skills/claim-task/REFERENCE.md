# `/claim-task` — editor reference

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
load-bearing rules, each pinned verbatim by a required check. claim-task has no such roster: its
rules are unprotected by construction, exactly as they were before this file existed.

What this file is, today, is a **destination** — the place the rule above sends rationale, so that
the convention has somewhere to point on the day someone writes the next rule for the claim path. Sections
get added here as rules are declared; an empty roster is an honest statement of where the work has
reached, not a gap to paper over.

## What this skill's rules tend to be about

`/claim-task` claims a task, sets up the worktree, and hands off to an executor — so most of its
rules are about state that two sessions can reach at once, and the reason a rule exists is usually
a race that is invisible in the procedure itself.

## Step 8 — the diagnostic mailbox is bounded, and why the runner is told so

**The rule.** Step 8's `_unparseable_*.json` paragraph states a 7-day retention and says that an
*absent* diagnostic may have aged out, so absence is not evidence the executor never ran.

**What it protects.** An earlier build added a 7-day reclaim to the mailbox and left this paragraph
describing the old unbounded behaviour, including a worked example — *"a run of this claim from
last week"* — that had become exactly the retention boundary. Neither sentence was flatly false,
which is why it survived: the files do still persist across runs, and an agent still must not
delete them. What changed is that they are now *bounded* rather than permanent, and the runner was
never told.

**What its loss or softening would change.** The operational half is the absence clause, and it is
the only part that earns a line in the runner: an orchestrator that reads an empty mailbox as
proof the executor never ran will report a stranger's silence as this claim's result. Before the
cap that reading was sound, because nothing removed a diagnostic. After it, the same reading is a
false negative that grows with the age of the run. Drop the clause and the skill is not wrong
about any single sentence — it is wrong about what an empty mailbox means, which is the question
the step exists to answer.

**Provenance.** Filed by a review round and closed by a later build. The build that added the reclaim corrected the
three surfaces it was permitted to touch in-branch and could not touch this one, because
`core/skills/**` was then never tier 1 under CLAUDE.md's fix-in-branch stanza, at any size. The sharp
part of the record: the original entry's own body had *named* this surface as one of three documenting
retention as intended, and that build copied that sentence into the archive and wrote "RESOLVED"
beneath it without changing the surfaces. The sibling sentence in `auto-build/SKILL.md`'s
rolling-window refill step was corrected in the same commit; that skill has no reference file, so
its runner carries the bound in a parenthetical and nothing more.

**Adjacent, still open.** The diagnostics are keyed `_unparseable_<session>_<agent>.json`,
never by claim or phase, so the "go and look" instruction this paragraph gives is still not
filterable by an orchestrator. The cap made that population smaller, not navigable.

## Steps 1 and 3 — a roadmap task is classified by its shape, and named by one rule

**The rule.** Step 1 takes any argument matching the schema's id grammar as a roadmap task,
after the batch arm has had first refusal, and does not check that the id exists. Step 3 derives
the branch from the id by one rule: the leading `^[A-Z][A-Z0-9]*` segment, lowercased, is the
directory, and the whole id, lowercased, is the leaf.

**What it protects.** Both steps used to carry a fixed list of five prefixes (`FEAT`, `TECH`,
`DATA`, `UX`, `FIX`). `tasks/schema.md` leaves prefixes to the project, and `validate_tasks.py`
accepts any id that matches the grammar, so a consumer whose queue used `OPS-` had tasks its own
validator passed and this skill refused with a usage message. The reasonable reaction to that
message is to doubt the id, not the skill. The Step 3 table was the same five-item list written
out as five branch names, so even an id that got past Step 1 had no branch to generate.
`/document-work`'s follow-up gate had already solved the vocabulary question by reading the
prefixes from the index, and `/roadmap` groups kinds under the literal prefix for the same reason.

**Why shape, and not a lookup, at Step 1.** Step 2 already resolves the id, through
`claim_task.sh --entry-state`, which answers `absent` for an id the task index does not list,
and Step 2 stops there with a named remedy. A second existence check at Step 1 would read the
index twice and give a missing id a usage message instead of that remedy. So Step 1 answers only "is this a batch,
a task id, or neither", and the grammar is the whole of that answer. The batch arm goes first
because `BATCH-120` matches the task grammar.

**What its loss or softening would change.** Put a prefix list back into either step and every
consumer with a prefix outside it loses `/claim-task`: with a misleading usage message at Step 1,
and with no branch rule at Step 3. Swap the arm order and `BATCH-<N>` is classified as a roadmap
task, which `--entry-state` then refuses as a batch. Change the leaf half of the Step 3 rule
and the branch no longer matches what `sitrep_survey.py` reverses when it maps a branch with no
`branch:` field back to a task: it upper-cases everything after the first `/`, so
`ops/ops-foo` → `OPS-FOO`.

**Provenance.** Reported upstream by a consumer with 34 outstanding `OPS-` tasks, and fixed in
a later build. `/release` Step 4's category map had the same five-prefix list and gained a literal-prefix
fallback in the same build. It has no reference file, so its runner carries the one-clause reason.

## Step 7a — the integrity check asks what HEAD gained, not whether it moved

**The rule.** Step 7a captures two SHAs before the planner is spawned: the worktree's HEAD and the
default branch's tip. The post-plan check reports `OK` when HEAD is still on the task branch and either is
unmoved, or moved only forward onto commits that were all already on the default branch at
capture. Anything else, including a git error in that forward arm or either SHA not
being a full object id, reports `VIOLATED` and parks. A worktree whose HEAD cannot be read at all
stops the check with a traceback before any verdict is written, which is loud rather than a
verdict.

**What it protects.** The property is *the planner did not commit*. A bare SHA compare answers
*did HEAD move*, which is strictly broader. A consumer that fast-forwards the worktree from the
default branch between capture and check trips it with no planner commit at all: the claim parks,
and the resume re-plans from scratch. On the reported run that discarded 688 lines of plan. Sysop
itself prescribes no such mutation inside Step 7a; the exposure is a consumer-local practice.

**Why the tip is captured, not named.** The first cut passed the default branch's *name* and read
it at check time. A review round broke that twice: a planner commit made on the default branch
in the main checkout, then fast-forwarded into the worktree by the consumer, read `OK`; and
substituting the task's own branch name read a planner commit as `OK`, because that branch
already contains it. A tip captured before the spawn cannot contain anything made during 7a, and
a name is never accepted in its place. Round 2 found the same hole one argument over: a name
substituted for the pre-plan HEAD (`HEAD`, `@`, the task branch) also resolves at check time to
the commit being judged, so both SHAs must be full object ids.

**Why the branch.** With the worktree behind the default branch, a planner that detaches onto it,
or switches to another branch inside the captured tip, gains only base commits, and the executor
would then commit off the task branch. The check requires HEAD to still be on the task branch for
either `OK`: a planner that switches branch or detaches without moving HEAD (round 3) would
otherwise read `OK (HEAD unmoved)`, which the bare compare never caught either.

**Why both conditions.** "Every commit gained was on the captured tip" alone passes a HEAD that
moved *backwards*, which gains nothing and drops work; the ancestry check refuses that. The
ancestry check alone passes a planner commit. The upstream proposal was "zero commits ahead of the
default branch"; that is the same property only on a branch with no commits of its own, and a
reused branch or a resume can reach 7a carrying some.

**What it costs.** A close that lands on the default branch *during* 7a, fast-forwarded into the
worktree before the check, false-parks: the commit was not on the tip at capture. That is the
safe direction, and rarer than the case fixed. A `--no-ff` merge of the default branch, or a
fast-forward from a remote-tracking branch ahead of the local one, false-parks as before. Every
re-entry at 7a holds the recorded tip (a later build widened this from the `VIOLATED` route to all of
them), and that tip cannot include later default-branch commits: a consumer that fast-forwards
the worktree between the record and a resume false-parks on every re-entry, with no planner
commit involved. Reset to `pre_plan_head` exactly, and fast-forward only after the check passes;
the runner's park report names both causes. Re-reading the tip at resume would clear the false
park and reopen the route the captured tip closed (a planner commit made on the default branch,
fast-forwarded in), so the stop stays in the safe direction.

**`/auto-build` Phase 6a keeps the bare compare.** It has the same exposure: a consumer that
fast-forwards a worktree during Phase 6a false-parks it. The reported consumer fast-forwards
before its 6a capture, so it does not hit it there. If one does, the same two captures and the
same check port as they are.

**Why a re-entry holds the recorded SHAs, and why they have their own file.** Any re-entry at 7a
after a planner has run may find a rogue commit in the branch, and a fresh capture would take
that commit as the baseline and pass it. An earlier build built the hold for the `VIOLATED` route only,
reading the SHAs back out of `planner-integrity.md`. Its round 3 found three routes that reach 7a
with no such file: a crash between the planner's return and the check, the check exiting
2 on a missing substitution, and a planner re-spawn that fails again and stops. So 7a writes the
SHAs to `pre-plan.md` **before** it spawns anything, and holds that file whenever it exists.
The route back no longer matters.

The maintainer chose a separate file over an early `planner-integrity.md` with a `pending` verdict. 7-pre's
routing table reads that file's presence and verdict, and its "no `planner-integrity.md`" row is
the one a crash reaches: an early file would turn that row off, so the table would have to learn
`pending` to keep routing a crash to 7a. `/review-close` Step 2e would also report the file
present for a run that recorded no verdict. `pre-plan.md` is read only by 7a's pre-plan block;
7a's `## Plan` recovery also stands aside when it exists.

**Two older shapes the block still reads.** A run recorded by an older build has
`planner-integrity.md` with `pre_plan_head:` and no `pre-plan.md`: the block holds those SHAs and
writes `pre-plan.md` from them. An integrity file with no `pre_plan_head:` (the skip-the-planner
`OK`, which runs no planner) records no baseline, so the block captures. When both files exist and the check's record holds a full
object id, the two must agree, or the block exits 4: the check writes the SHAs it judged against,
so a disagreement means one file was edited after the other. A value in the check's record that is
not an id is a mis-substituted argument, not a baseline, and is not compared (rule 4 of the
author-side pass found the false stop comparing it would cause).

**Why a re-spawn keeps the SHAs in context.** The planner is handed `<ARTIFACT_DIR>` to write
`plan.md`, so it can also rewrite `pre-plan.md`. The first cut of this hold re-ran the record before a
re-spawn, and its round showed a planner that commits, rewrites the record and fails being
re-spawned against its own commit and passing. The SHAs the orchestrator already holds are out of
the planner's reach, so a re-spawn keeps them, as the base did.

**What it does not cover.** Within the run the check uses the SHAs the orchestrator holds, and a
later re-entry sees any disagreement with `planner-integrity.md`. Three shapes still reach a
re-entry holding a planner's baseline: a planner that commits, rewrites `pre-plan.md`, and is then
followed by a crash before the check, or by a second failure and a stop; and one that commits and
**deletes** `pre-plan.md` before either, so the resume captures afresh. Each takes a planner
deliberately subverting its orchestrator, not one breaking its no-commit rule, and the check was
never a defence against the first. A run that started under an older build and crashed between the
planner and the check has neither file and captures afresh, as before; that shape ends with the
runs in flight when a consumer updates.

**Why the env strip.** An inherited `GIT_DIR` overrides `-C`, so the check read the main
checkout's HEAD as the worktree's and a planner commit read `OK (HEAD unmoved)`. An established rule,
which this skill's other heredocs already follow; round 2 found this one did not.

**What its loss or softening would change.** Drop the fast-forward arm and the false park
returns. Drop the ancestry condition and a reset onto the default branch reads as clean. Read the
tip at check time, or accept a name for either SHA, and a planner commit can read as clean. Drop
the branch condition and a planner can leave the task branch unnoticed. Let a git error fall
through to `OK` and the gate opens.

**Provenance.** Internal tracker #680, filed by a triage pass and closed by a later
build, whose first round replaced the first cut's named base with the captured tip and whose
second added the pre-plan HEAD and branch conditions.

## Step 7e item 5b — the ignored-file check reports and files nothing

A gate that reads the working tree passes on an ignored file the commit will not carry. The
executor is the first actor that can see it, so it runs the check and quotes each hit in its
final message. It does not file a task or a `questions.md` entry: only option
A reaches Step 8b before the close, so on option B a filed task merged as open after
`/review-close` Step 2a step 3a had already answered the same question. The close is the single
asker; Step 8 prints the executor's quoted lines so an attended run sees them early. It does not commit the file or edit `.gitignore` either, because an ignore can be
deliberate (a secret, a large corpus) and committing past it is the human's call.

Why the script reads only files a file pattern ignores, and skips prose, is in
`review-close/REFERENCE.md` § *Step 2a — provenance*; the same script serves both.

## Steps 8b and 8c — the ask, and why the answers run is a spawn of its own

**The rule.** When the executor files a finding only a human's answer can unblock, it lists it in
`questions.md` (Step 7e item 2b). On option A, or on any `--resume`, Step 8b asks each entry as a
menu and records the answers in `answers.md`. Step 8c then spawns a second executor, the answers
run, for the entries answered `fix`. It gets the full Step 7e prompt with an addendum, emits
`PHASE: answers`, undoes the filing each fix replaces, marks each fix with the approval suffix,
and makes a new commit. `answers-outcome.md` records what came back. A fresh option-B run only
reports the questions, as before.

**Why the orchestrator does not fix them itself.** This skill's frontmatter disallows `Edit` and
`Write`, and its opening rule is that it never implements. An earlier shape told the
orchestrator to make the fix, which skipped every verification item the executor is bound to run.
Its round disqualified that shape.

**Why the full 7e prompt, and why its own envelope phase.** A second earlier shape spawned a
follow-up with an inline prompt: no body path, none of 7e's hard constraints, and no `PHASE:`. Its
envelope landed at `<CLAIM_ID>.json` or `_unparseable_*`, Step 8's first-hit read took the first
executor's `EXECUTED`, and a failed fix read as success. So the answers run gets 7e's prompt
verbatim, `<ENVELOPE_PHASE>` makes its envelope `<CLAIM_ID>.answers.json`, and 8c moves any
earlier `answers.json` out of the mailbox before the spawn, so the read after it cannot find a
stale one.

**Why the branch tip is checked, not only the envelope.** `EXECUTED` is the agent's claim about
itself. The record block compares the branch tip with the one the prepare block printed:
`NO_COMMIT` when it did not move, and `REWRITTEN` when the old tip is not an ancestor of the new
one (the addendum forbids amending). Either one is handled as `FAILED`. This makes that
failure mechanically visible even when the envelope reads `EXECUTED`.

**Why 8b lists before it asks.** The first cut had the orchestrator `Read`
`questions.md` to build the menu while the record block parsed it separately. The two disagreed:
a fenced `## `, entries wrapped in the ```` ```markdown ```` fence 7e's prompt shows them in, or
entries indented under a list item made the counts differ, and in one case they matched while
pairing answers with the wrong entries. The listing is the same parse as the record, so the menu
cannot drift from it. The parser uses Step 8's `fence_mark`/`fence_closes`, copied rather than
re-derived, and unwraps a whole-file `markdown` fence. The listing is also where a recorded
outcome stops the ask: the first cut asked on every resume and then refused to record, which
threw the human's answers away.

**Why the spawn is recorded before it happens.** A crash after the answers executor returned, and
before its outcome was recorded, left `answers.md` with no outcome, and the first cut spawned it
again over the fixes it had already committed. The prepare block also moved aside the envelope
that would have shown it. `answers-started.md` is written before the spawn, so a re-entry reads the
envelope and records it instead. The cost is the crash between that write and the spawn, which
records `MALFORMED` for a spawn that never ran. The human retries it, which is the safe
direction.

**Why the answers run is not asked again.** Its item 2b questions are filed as tasks and not
written to `questions.md`, because nothing asks a second round and the record is final. A
questions file that grew during the answers run would have promised the answers executor an ask
that never comes.

**Why every answer is a file, and the routing rows.** The routing table reads files. `answers.md`
without `answers-outcome.md` means the answers run never ran or never finished, so a resume runs
8c again rather than skipping it. A declined or unanswered menu is recorded as `leave`, so a
resume does not ask forever. `outcome.md` reading `EXECUTED`, with questions and no answers, is
the option-B case and the crash-before-ask case: a resume is a human, so it asks.

**Why a `BLOCKED` answers run leaves `classification.md` alone.** Step 8's executor-`BLOCKED` arm
rewrites the classification so a resume reaches 7c. Here that would re-run the *first* executor
over work already committed. The cycle's answer files are archived instead (`answers.<n>.md`,
`answers-started.<n>.md`, `answers-outcome.<n>.md`, the outcome last, so an interrupted archive
still reads `BLOCKED` and routes back to 8b), and 8b asks again with the blocker question beside
the entries. **The start record has to go too (round 2, HIGH):** round 1 added it to stop a crash
re-spawning, and the archive did not move it, so after a re-ask 8c read it as `SPAWNED_BEFORE`,
re-read the `BLOCKED` cycle's envelope and parked again, forever. An all-`leave` re-ask could not
escape.

**Why the filing is undone.** The first executor filed the finding on the branch, where it has not
reached `main`. Left in place, it would land open after the merge, beside the fix that made it
moot, because a close closes only the claimed ids. Where the executor extended an existing open
task instead, only the appended text goes.

**Why the suffix cites the answers file.** Check 2 in `/review-close` Step 2d would otherwise rest
on the fixing agent's own statement that a human approved a never-list fix. The file is evidence
from the run that asked. **Its limit:** `sysop/runtime/` is gitignored, and Step 4c removes the
claim directory when the task closes, so check 2 can read it only on the machine that ran the
claim and before an earlier close reaped it. An absent file is therefore a note, not a finding.
A file that is present and does not record the question as `fix`, with no archived
`answers.<n>.md` beside it that does, is a finding; the archive clause is for a fix committed by a
cycle that later went `BLOCKED` and was re-asked. **It never runs
on a review batch:** `/review-close` Step 2d's `## Also fixed` arm is roadmap-only, so on a
`BATCH-<N>` claim the file is evidence nobody reads.

**Why a timed-out menu is not an answer (round 2).** Under `askUserQuestionTimeout` a question
left idle submits the pre-highlighted option and tells Claude the human may be away. 8b puts the
recommended fix first, so a timeout would record `decision: fix`, and for a never-list item the
answers executor would write an approval suffix that check 2 then reads as the human's. 8b follows
`_shared/plan-review-preference.md`'s rule: a result carrying the away signal is a park, not an
answer, and nothing is recorded. A human who skips or declines is still recorded `leave`.

**Why option A and resumes only.** Option B is the unattended choice, and a menu in an
unattended session blocks the `/document-work` chain until someone answers. The resume command
that asks is printed under B's report instead.

**What it does not buy.** A fix made on an answer is still a fix an agent wrote. The close reviews
it like any other `## Also fixed` line.

**The park marker lists what it stands on.** The marker recorded three
artifacts. It now records `plan.md`, `planner-integrity.md`, `review.md` and `classification.md`
as present or `MISSING`, and adds `pre-plan.md` and Step 8's files when present. They are listed
only when present because a 7a skip writes no `pre-plan.md`, and the files written from Step 7e on
(`questions.md`, `outcome.md`, and the answers files) cannot exist at an earlier park.

**Provenance.** Filed after two disqualified builds; built on
the maintainer's four answers of 2026-09-29: undo the filing, cite the answers file, park and re-ask on
`BLOCKED`, and ask on option A and resumes only.

## Steps 7f, 8 and 8c — the commit counts read past the recorded PR heads

Option C's empty-branch check (Step 7f) and the `FAILED` / `MALFORMED` listings (Steps 8 and 8c)
count commits on the branch that the default branch lacks. Under `§ Merge policy: pr`, a branch cut
before an earlier `/review-close` squash still carries that close's claim flips as ancestors, and
a squash leaves nothing ancestry can match them to, so the counts read them as the branch's work:
option C stopped short of a `--delete-branch` release, and a failure listing showed commits that
are already in `main` as content. `/review-close` Step 4d records each merged PR's head as
`refs/sysop/merged-pr-heads/<PR>`, and each count passes
`--not --glob='refs/sysop/merged-pr-heads/*'`, which matches nothing when no head is recorded.
The rationale for the record itself is in `review-close/REFERENCE.md` § *Step 4a — provenance*.

### Why the opening says to run in the main conversation

A consumer's one-week field report (2026-10-12, maintainer-side under `tools/`) wrapped this skill in Agent calls: 188 of its 254 agents were launched by other agents, and each orchestrator then expired its 5-minute subagent cache while waiting on its own planner, reviewer and executor, rewriting its whole context at every hand-back — about 39 USD of a 533 USD week, the report's "own child agents" (23 USD) and "background waits" (16 USD) buckets together. The main conversation's cache lasts an hour on a subscription, which is why the orchestrator belongs there. The delegated case, when it is legitimate, is this one: a named agent file can carry a 1-hour cache TTL where a generic Agent-tool spawn cannot.

## Step 4d — the claim worktree is fast-forwarded to the claim

**Why.** Step 4b runs `claim_task.sh --lock`, which creates the branch with `git branch <name>`
from the primary checkout's `HEAD` before Step 4d's commit exists. Left there, the worktree is one
claim short, and its own copy of the task index reads `open` for the task it was made for. Every Step 7
agent works in that worktree. A consumer's plan reviewer read that, plus `origin/<default>`, as
"the claim never landed" and filed a false HIGH; every observation it made was true.

**Why not the filed reorder.** The report proposed flip → validate → commit → `--lock`. Its own
validate step fails: `validate_tasks.py`'s invariant 9 errors on an `in_progress` task with no
lock file. Dropping that step would commit the state the validator rejects, and any failure
before `--lock` would leave it on the default branch, where undoing it takes a revert commit
rather than today's uncommitted checkout.

**What the step does instead, and why each skip exits 0.** `--commit-claim` reads the default
branch's ref (never `HEAD`) before it releases the tracker mutex, and fast-forwards the worktree
to it after, so a slow consumer `post-merge` hook never holds the tracker. `HEAD` is wrong
because a concurrent `git checkout` in the primary checkout moves it, and a review round
merged another branch's unmerged commits into a claim worktree that way. The mutex serializes
tracker writers only, so the tip can include a commit another writer landed; every such commit
holds the claim too, which is all the fast-forward needs. It skips a worktree that is on another
branch, has commits of its own, or has uncommitted tracked changes, and it merges with
`--no-overwrite-ignore`: by default `git merge` refuses over an untracked file but overwrites an
ignored one silently, and round 1 reproduced that loss under a success line. Round 1's own
exact-path check missed three routes git's flag covers (a file that becomes a directory, a
case-folded name on a case-insensitive filesystem, a symlink that becomes a directory), so the
flag replaced it. Verified on git 2.50.1. Every skip exits 0 because the claim is committed, and
a non-zero exit would send the runner into a rollback over it. Before any of these arms the tip is
checked once more: one that no longer holds the claim exits 1, because the commit's own
check had just passed, so the default branch moved since and the claim is not where the success
line put it.

**What it does not cover.** A skipped worktree still reads `open`, and the `⚠️` line reaches the
runner, not the agents. `origin/<default>` reads `open` until `/review-close` pushes, which is the
issue's second route to the same false finding. Both stay open.

## Step 4d — the claim commit checks where it landed

Rule A runs before the flip, and the tracker mutex serializes tracker writers, not `git checkout`.
A review round put a checkout between the two with a `git` shim: the claim commit
landed on that other branch, and the script printed `✅ Committed the claim for <ID> on main.`
while `main` never got it, because `git commit` asserts no branch. The commit arm now
re-applies Rule A immediately before `git commit`, and both arms then read the default branch's
ref: it must hold the task `in_progress`, and on the commit arm it must also have moved. Otherwise
the script exits 1, naming which check failed and where `HEAD` now is.

**Why both arms.** The resume arm compares against `HEAD`, so a checkout onto a branch that
already carried a committed flip (what the earlier defect left behind) read as "nothing to
commit" and exited 0 over a default branch reading `open`; a review round found it.

**What the re-check does and does not prevent.** It prevents the stray *commit* in the common
case, but the flip is already written and staged by then, and a checkout carries a staged change
with it. So a refusal there leaves the flip staged on the branch `HEAD` moved to, where that
branch's next `git commit` would take it. The script does not unstage it: a restore in a checkout
another actor now holds can drop that actor's own edits to the same file, the hazard the 4b/4c
rollback's `HEAD --` form was disqualified for. It says so
instead, and names the commands; run against a branch whose index differed, the printed recovery
restored that branch's copy and the re-run committed the claim. Only the ref check is exact,
because nothing can be checked between `git commit` and the ref it moves.

**Why exit 1, unlike the fast-forward's skips.** Those skips exit 0 because the claim is on the
default branch. Here it is not, so the runner must reconcile rather than proceed.
