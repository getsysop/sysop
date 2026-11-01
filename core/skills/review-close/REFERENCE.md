# `/review-close` — editor reference

**You are reading this because you are about to change the skill, not run it.**

`SKILL.md` and the step files it loads from `steps/` are the runner. They carry procedure, commands, and a one-line reason wherever the
reason changes what the runner does. This file carries what the *editor* needs: what a rule
protects, what its loss or softening would change, and where it came from.

Claude Code does not load a skill's sibling files automatically — they are read only when
something points at them — so this file costs the runner nothing and the editor pays for it once.

Notes here anchor to **rule ids and step headings, never line numbers.**

**Where a note says "the heredoc" about a step's program, read the shipped script that step
now runs.** Two earlier builds moved every Python heredoc this skill ran into
`core/companion/scripts/`, verbatim apart from the arguments each step's invocation names; a
note's claim that a heredoc binds `Bash(python3 -:*)` now means the script's own seeded rule.

The method behind the declaration below, and the pin that enforces it, are specified in
`tools/CONTEXT_THINNING_SPEC.md` (maintainer-side; never ships).

---

## Where new rationale goes

**New rationale is authored here, not in the runner.** When you add a rule to `SKILL.md` or a step file,
the runner gets the instruction and — only if it changes what the runner does — one line of reason.
The justification, what the rule's loss or softening would change, and the provenance go here.

This is a rule about *where text is written*, not a size budget. A skill may grow as much as the
work requires; what it may not do is grow by accumulating, in the file an agent reads at runtime,
material that only an editor ever needs.

The case for it is arithmetic rather than taste. Every rule in this runner was added because a
review round asked for it, so no single addition is wrong — and measured over eleven consecutive
commits that touched `SKILL.md`, it grew by roughly eight kilobytes per touching change, while a
relocation pass moves a small fraction of that per section it rewrites. Tidying after the fact
does not catch up with authorship. The cheap intervention is at the point of authorship, which is
here.

A required check counts the editor-facing mass of `SKILL.md` and refuses an increase, so this
convention is not carried by memory alone. It constrains *editor text only*: instructions stay
unconstrained, and a phase may add as much procedure as the work needs.

## Declared load-bearing rules

A rule is declared when the record can name **what its loss or softening would change**. Those
rules, and only those, are pinned verbatim by a required check. Everything else in the runner is
unprotected by construction.

**This roster is machine-read.** `tests/test_review_close_reference_pins.py` parses the list
below and asserts a three-way identity: the ids here, the `## <id>` sections in this file, and a
`DECLARED_IDS` constant pinned in the test module must be the same set. Removing a rule
therefore requires editing a pinned constant — it cannot happen as a side effect.

Rule ids are `RC-<step>-<n>` and are **stable**: an id is never reused for a different rule, and
a retired rule's id retires with it.

- `RC-3-1` — Step 3's green is never a verdict on a branch; `4a-post` is.
- `RC-3-2` — a scope that could not be computed never narrows the gate.
- `RC-3-3` — a surface absent from the changed-file list is `skipped` and recorded, never dropped.
- `RC-3-4` — "the diff" is this pass's changed-file list, never the run's.
- `RC-3-5` — the doc-only skip is licensed by the pass, not by the diff being harmless.
- `RC-3-6` — the item-5 stop is about the run, not this pass.
- `RC-3-7` — three dots on the changed-file diff, always; two silently corrupt the list.
- `RC-3-8` — the `NO_ORIGIN_MAIN` sentinel is what makes an uncomputable scope branchable.

**Coverage is one step, and one part of it.** Only Step `3` is declared today, and only eight of
its rules. Every other step in this skill, and the whole tail of it, ride **unprotected**. Do not
read the presence of this file as coverage of the skill.

---

## `RC-3-1`

**The rule.** Step 3 is the pre-merge pass and can only verify the tree it runs on. Its green is
**not** a verdict on any branch, and nothing in it may be reported as having verified one. That
verdict belongs to `4a-post`, which re-runs the same resolved list on the merge target after the
branches are merged.

**What its loss would change.** This is the rule that keeps a cheap fail-fast from being read as
proof. At Step 3, `HEAD` is still the default branch: no approved branch's files are in the tree
and its new tests do not exist yet. A report that says "verification passed" without that scoping
claims the work was checked when nothing about the work was executed. Softening it — "Step 3
verifies the changes" — converts a base-tree smoke check into a false clean bill for every branch
in the cycle.

**Why it is easy to soften.** The step *does* run the project's real command list, and on a
consumer with a `## Pre-merge verification` section that list is the same one `4a-post` runs. The
distinction is entirely about *which tree* it ran on, which is invisible in the output.

**Provenance.** The build that moved the verifying gate to `4a-post` and made Step 3
a declared pre-merge pass. Both specs of the day had the order wrong too.

---

## `RC-3-2`

**The rule.** If the changed-file list cannot be computed — no `origin`, or a remote whose
default branch differs, so the command prints `NO_ORIGIN_MAIN` — then **gate nothing and skip
nothing: run the full resolved list.** A scope you could not compute must never silently narrow
the gate.

**What its loss would change.** The changed-file list is an input to two narrowing decisions: the
surface gate (which auto-detected commands are armed) and the doc-only skip. If an uncomputable
list were treated as an *empty* list, both narrowings would fire at maximum — every surface
unarmed, the diff trivially "doc-only" — and the pass would report green having executed nothing,
on precisely the setups where the runner knows least about the repository. The failure is silent
and it is worst exactly where it is least likely to be noticed.

**The shape is general and worth keeping in mind when editing anything nearby:** a filter whose
input failed to compute must fail open, not closed.

**Provenance.** The `NO_ORIGIN_MAIN` sentinel and its verified failure mode — the bare diff exits
128 with `fatal: ambiguous argument` — are recorded in the step itself.

---

## `RC-3-3`

**The rule.** A surface that is present in the repo but absent from this pass's changed-file list
is **`skipped`, not `failed`**, and the skip is recorded on Step 8's `Verification:` line with
its reason. **The inverse is not licensed:** a surface the list *does* touch is never skipped by
hand.

**What its loss would change.** Recording is what makes the skip *authorized* rather than
improvised. Without the record, a narrowed gate and a fully-run gate produce the same report, so
a reader cannot tell which happened — and the next person to wonder whether the frontend was
built has no way to find out. Losing the second half is worse: it converts a mechanical,
list-driven narrowing into a judgement call the step never authorized, made silently and under
time pressure, which is the exact behaviour the surface gate exists to replace.

**The companion report is `Unverified surfaces:`** — every changed code file no detected surface
claimed. Surface-gating narrows the gate, so what it cannot account for has to become visible
rather than disappear. A `.sql` migration in a repo whose only detected surfaces are a frontend
and pytest is verified by nothing, and that was true before the gate existed.

**Provenance.** The surface gate and its reporting obligation were added together; separating
them is what this rule forbids.

---

## `RC-3-4`

**The rule.** "The diff" means **this pass's** changed-file list, never the run's. Step 3 and
`4a-post` compute it the same way on different trees, so each decides its own skip. `4a-post` is
never skipped because Step 3 was, and Step 3's skip is not evidence about any branch.

**What its loss would change.** On the dominant cycle Step 3's diff is genuinely doc-only — a
claim flip and a ledger save are the whole of the default branch's local-only diff — so the pass
skips. If that skip were inherited, the *post-merge* gate would skip on the strength of a
*pre-merge* tree's contents, and the assembled diff of every merged branch would go unverified.
The two passes reading one list is the single most natural implementation error here, because
"the diff" reads like a property of the run.

**This is the twin of `RC-3-1`.** One says Step 3's green is not a verdict; this one says Step 3's
*skip* is not evidence either. Both exist because the cheap pass and the real gate run the same
commands and look alike in the log.

**Provenance.** The same build as `RC-3-1`.

---

## `RC-3-5`

**The rule.** The doc-only skip is licensed by **the pass** — Step 3 is a fail-fast whose green
is already forbidden from being read as a verdict, so skipping it forfeits only the fail-fast.
It is **not** licensed by the idea that a doc-only diff is harmless.

**What its loss would change.** The extension test classifies as documentation a great many files
a build actually consumes — `pyproject.toml`, `tsconfig.json`, `.eslintrc.json`, `ruff.toml`,
`package.json` and its lockfile, CI workflows, semgrep rules, `checks.yml`. A diff that is
doc-only by that test can regress lint, typecheck and build directly, and a project's `### Always`
list is a full test suite, which can assert on prose as readily as on code. If the skip were
believed to rest on harmlessness, the obvious next edit is to let `4a-post` inherit it — and
`4a-post` is the gate that speaks for the work.

**So the correct justification is the narrow one**, and keeping it narrow is what stops the skip
spreading to a pass that cannot afford it.

**Note the boundary:** not every such file is caught. A `vite.config.ts` or `.eslintrc.js` is
`.ts`/`.js` and counts as code.

---

## `RC-3-6`

**The rule.** Item 5 ("no source produced a command list and the diff touches code → stop and
ask") is evaluated against **the run**, not this pass. Item 4 decides whether to *run* the list;
it does not decide whether the list had to exist. So resolve item 5 before skipping: if no source
produced a command list and **any** part of this cycle touches code — this pass's list, or the
per-branch diff for any approved branch — stop and ask **here**.

**What its loss would change.** Taken in bare sequence the two items collide on the dominant
path. This pass's diff is doc-only, item 4 fires, item 5 is never reached — so a consumer with no
`## Pre-merge verification` section, no `scripts.verify`, and no detectable surface sails through
Step 3 and meets "stop and ask the user what to run" at `4a-post`, **after every branch has been
merged.** That is the one outcome the step exists to prevent, and it is reached by following the
step's own items in order.

**This is an ordering rule, and ordering rules are invisible in the text they govern.** Nothing
about item 4's wording suggests item 5 must be evaluated first; only this paragraph says so.
Prose asserting an order is not a test of it.

---

## `RC-3-7`

**The rule.** The changed-file list is read with `git diff --name-only <base>...HEAD` — **three
dots, always**. Two dots compare the two *tips*, so everything the base gained since the branch
was cut renders as though the branch **deleted** it. The rule is stated as a shell comment inside
the prescribed command block, which is where the operator reads it.

**What its loss would change.** Not a failure — a wrong answer, silently. The two-dot form exits
0 and returns a list, so nothing halts; the list is simply not the one the step means. Every
narrowing decision in Step 3 reads that list and is therefore corrupted upstream of itself at
once: item 3's surface gate arms commands for surfaces the branch never touched and skips ones it
did, item 4's doc-only test classifies a code diff as documentation when the code files appear
only as phantom deletions, and Step 8's `Unverified surfaces:` line reports the corruption as
coverage. `/review-close` **manufactures** the condition rather than merely meeting it — Step 1b
commits `review_tasks.md` to `main` before any branch is inspected — so the stale-base case is
the normal one here, not the edge.

**Where it came from.** Internal tracker #241, and the build that rebuilt Step 2's diff basis for
this defect class. Step 2a's note is the canonical statement and this comment defers to it.

**What guards it besides this pin.** `tests/test_review_close_diff_basis.py` allowlists every
two-dot `git diff` in the shipped tree by whole line, over the raw text, so a regression of the
*command* fails there first. The pin covers what that scan cannot see: the comment that says why,
which a rewrite could delete or invert with the command left correct — measured, and missed by
the scan in all three shapes.

---

## `RC-3-8`

**The rule.** The changed-file command ends `|| echo "NO_ORIGIN_MAIN"`, and the prose above it
branches on that string. The sentinel is what converts *"the scope could not be computed"* into a
value the runner can act on.

**What its loss would change.** `RC-3-2` says a scope you could not compute must never silently
narrow the gate, and this is the mechanism that makes that sentence executable. Without the `||`
arm the diff alone exits 128 with `fatal: ambiguous argument` and prints nothing — so a runner
that treats a failed command's empty output as an empty changed-file list fires *every* narrowing
at maximum: no surface is in the list, so item 3 arms nothing; no code file is in the list, so
item 4 skips verification entirely. The setups this lands on are the ones the skill knows least
about — no `origin`, or a remote whose default branch is not `main`. The rule's own trigger would
be gone while its statement, *"If it prints `NO_ORIGIN_MAIN`"*, still sat in the prose above it,
which is the shape a round demonstrated: delete the arm and the pin stayed green.

**Why it is declared separately from `RC-3-2`.** `RC-3-2` is the *policy* and is prose; this is
the *sentinel that arms it* and is a command. They fail independently: the policy can be reworded
with the command intact, and the command can be deleted with the policy intact.

**What this declaration adds, stated narrowly because the detection already existed.**
`tests/test_review_close_merged_tree_gate.py` pins the whole three-line scope command —
`|| echo "NO_ORIGIN_MAIN"` included — as an *executable fenced line* in both the `step3` and
`post` sections, so deleting the arm already fails there. The earlier § Blocked entry said as
much. What was missing is not a detector but a **declaration**: nothing named what the sentinel
protects or what its loss would change, so an editor met a pinned string with no reason attached.
That is this file's job, and the roster is where it becomes machine-checkable.

---

## Candidates — meet the bar, not declared

These meet the § 2.2 bar and could be declared if the campaign shows Step 3 moving. They are
listed so the roster's *selection* is legible, not just its contents.

- An empty changed-file list is a real outcome to report — "green" and "ran nothing" must not
  read the same.
- `### Always` is unconditional at `4a-post`; the asymmetry with Step 3 is the only thing standing
  between the word "always" and a section the dominant cycle never runs.
- The `Unverified surfaces:` report (discussed under `RC-3-3`, not separately declared).
- The doc-only skip never cancels a command the surface gate already armed.
- A failing command means stop, and do not push with failing checks.
- The permission hook's coverage is stated as three command shapes, never as the steps that use
  them — a step reference reads as a promise about everything the step runs.

## Blocked — meets the bar, cannot be declared

**Empty since the fence-tagging build, and the reason is the point.** This section carried two entries — the
three-dot diff rule and the `NO_ORIGIN_MAIN` sentinel — and both were blocked for the same
mechanical reason rather than any property of the rules: they live in a shell comment and a
command inside Step 3's fenced block, and the pin's canonicaliser deleted fenced text before
comparing. They were recorded here as *"the campaign's standing evidence that the fence question
has to be settled before a command-heavy step is pinned"*.

That question is settled. The canonicaliser now **tags** wrappers instead of deleting them, so a
rule inside a fence is pinned while moving a rule into one still fails the pin as a change. Both
rules are declared above as `RC-3-7` and `RC-3-8`.

**One correction the settlement turned up, which this section had overstated.** The entry for the
three-dot rule described it as unguarded. Its *verdict-changing* failure mode — two dots in the
operative command — was already caught by `tests/test_review_close_diff_basis.py`, which scans
the raw shipped text (fences included) against a whole-line allowlist. Measured four ways against
**that scanner** before the fence question was settled: the two-dot regression is **caught**; deleting the
rationale comment, inverting it to recommend two dots, and deleting the sentinel are all
**missed** by it. (The sentinel is caught elsewhere — see `RC-3-8` — which the old entry for it
already said.) So what the pin adds here is protection for the *reasoning*, which no guard had,
and a **declaration** for the rest. A rule's blocked status was never the same as a rule being
unprotected, and this section had been read as though it were.

An entry belongs here when it meets § 2.2's bar and the mechanism cannot reach it. Nothing does
today. If something lands here again, say which mechanism cannot reach it and why, and check
whether another guard already covers the consequence before calling the rule unprotected.

## Declared limits of this mechanism

Stated so the file cannot be read as more coverage than it is. A round established each of these
by demonstration, not by argument.

- **Nothing outside Step 3 is screened.** A sentence contradicting one of these eight rules,
  planted in `4a-post`, Step 3c, Step 8 or `WORKFLOW.md`, reaches no screen here. The screens are
  section-scoped deliberately — a file-wide screen reddens the step that warns about a reading,
  for the sentence that warns about it — but the consequence is a real gap, not a theoretical one:
  `4a-post` is where the verdict lives, and a contradiction there would matter more than one here.
- **Nothing screens this file.** Inverting a rule's description *in `REFERENCE.md` itself* is
  caught by nothing.
- **A coordinated retirement lands.** Deleting a rule's roster bullet, its section, its subject
  pattern, its screen and relaxing the pinned floor — about eight edits in one commit — passes.
  The mechanism makes deletion a visible edit to pinned constants; it does not make it
  impossible, and it never claimed to.
- **A rule indented four spaces is invisible to the pin.** That is markdown's undelimited code
  form, and `_flat` collapses indentation before the pin compares. Every *delimited* neutering
  form is covered (``` and `~~~` at any length, `<!-- -->`, `<details>`, `>`), and a WHOLESALE
  re-indent of a step is refused — but a single indented rule is not refused by the pin. It is
  refused by `tests/test_commonmark_code_blocks.py`, which parses every tracked
  markdown file (the maintainer-side phase log excepted) as CommonMark and fails on any indented code block. A block parser tells a code
  block from a list continuation, which a line rule could not (68 of the 69 deep-indented lines
  in `SKILL.md` are continuations). The indented-code entry is closed by it.
- **A declared rule can be retired in three edits, not the eight this section used to imply.**
  Measured by a round: re-point the rule's subject pattern at another sentence of the same step,
  delete the rule, regenerate the block pin. The roster, the section and `DECLARED_IDS` stay
  untouched. `SUBJECT_QUOTES` now pins what each pattern must match, so the re-point has to
  replace the rule's own words and the diff says which rule left — it does not make retirement
  impossible, it makes it legible.
- **A re-wrap inside a prescribed command block reddens the pin.** Shell comments are tagged,
  not deleted, so their line breaks are inside the pinned text: re-wrapping a comment block
  moves the `#` prefixes and the pin fails as a change. That is the cost side of that
  settlement and it is deliberate — the alternative is the comment being invisible again — but
  it is a real innocent edit going red, and an open entry prices it. Ordinary
  prose and blockquotes are reflow-invariant; command-block comments are not.

---

## `--prepare` and `--resume` — provenance

### Why a prepare stops at the end of Step 3c

GDP measured Steps 1–3 at about USD 37–46 for one target and 326 calls for six (internal tracker #730), and
`--dry-run` keeps none of it, so a scheduled preview paid for every Step 2b agent twice. The
design is `tools/UNATTENDED_CLOSE_SPEC.md` (maintainer-side, not in the public mirror), and its § 1 records the maintainer's five answers of
2026-10-07. The boundary is the maintainer's answer (c). Step 3b asks nothing but holds the not-reversible
writes before Step 4 that matter (the collect's composite overwrite of a doc in main, and
`git worktree remove`), and Step 3c's answers decide what 3b does to each branch ("Hold just this
branch" exists because an approved branch's worktree is removed at 3b). A prepare that ran 3b
would act before the answers that should steer it.

### Why a prepare records instead of asking, and what each park is

A question that closes on its own is a park, never an answer
(`_shared/plan-review-preference.md` § D). The park at each site is the spec's § 3.5: Step 2a
step 3a's unanswered line already makes the verdict SKIP; Step 2d's park is "Hold for fix"; a
Step 3c signal with a `BRANCH:` line holds that branch; and a Step 3c signal with no branch halts
the resume, because there is nothing narrower to hold.

**Two sites the spec listed are not recorded** (round 1, semantics lens). Step 1b's "warrants
manual judgment" remark offers no options and the attended text falls through to the single-file
commit, so a prepare follows the text as written. Step 3's two asks are "what should run?", which
has no options, and a silently denied command's `!` relay, where the step forbids
`AskUserQuestion`; a prepare leaves Step 3 not run, with the reason, and the resume runs it
attended. A branch with a
pending Step 2a 3a or Step 2d question still goes through Steps 2b–2e, 3 and 3c, because the
point of a prepare is to have paid for that review once; the answer then decides its verdict.

**Every stop not named as recordable halts the prepare** (inside the maintainer's answer (b)): a prepare
has no instruction to record at an exit the text gives none for. The spec's § 3.3 lists the nine
such sites before the boundary. A `VERDICT: BLOCKED` is the one stop the maintainer's answer narrowed: under
`--prepare` it stops its branch, and the attended close keeps the whole-close stop. **On the
unpushed-main group it still halts the prepare** (round 1, semantics lens): the group's commits
are on local `<default branch>`, which every integration branch is cut from, so there is no branch
to hold and the blocked commits would merge.

### Why a script owns the run directory

The runner's memory is the thing a prepare must not depend on, and prose that says "write the
state down" can be skipped silently. `close_run.py` gives the run fixed file names, prints each
branch's state path, and refuses `finish` while a branch has no state file, so a prepare that
forgot to write cannot be resumed. The staleness check is code for the same reason: a branch
tip, a lock's bytes or a pending doc's bytes either moved or did not, and a runner comparing
them by eye is the failure the check replaces.

### What the staleness table is, and which parts are the maintainer's

The maintainer's answer (a) gave three rows: a branch's tip, lock or doc re-runs that branch from Step 2a;
the default branch re-runs Steps 3 and 3c; the conventions or maps re-run Step 2b. The rest is
this phase's:

- **`held_since:`** needs no row of its own: it is in the pending doc, whose bytes are hashed.
- **A pending doc is hashed without its `smoke_answers:` block.** The resume records Step 3c's
  answers into that block (its item 5) before its second `check` (item 6), and the recorder rewrites only
  that block, so hashing it would re-run from Step 2a every branch whose smoke the human answered:
  the Step 2b cost a prepare exists to save. The block is dropped by the recorder's own line rule.
  The author-side pass found this re-reading the resume order against `close_run.py`.
- **The recorded PR heads** (`refs/sysop/merged-pr-heads/*`) are keyed by PR, not by branch, so a
  change re-runs every branch from Step 2a, where step 0b decides which landed.
- **Worktree dirtiness** is not in the manifest. The resume runs Step 1 in full, and Step 1a's
  class feeds Step 2a step 0 directly, so the resume's items 2 and 6 say what a changed class does.
- **`core.hooksPath`** is reported and re-runs nothing. It changes which hooks run on the close's
  own commits, not what any step reviewed.
- **A branch merged or deleted since the prepare is dropped**, not a reason to refuse the resume. "Merged" means its recorded tip reached local
  or `origin`'s default branch after `begin`; a tip that was already there at `begin` is a branch
  Step 2a step 0b found landed, and stays in the run so Step 4 and Step 6 finish it.
- **A different default branch refuses the resume.** Every comparison in Steps 1 to 3c was
  against the recorded one, so nothing recorded would mean what it says.

The default branch moving keeps a branch's Step 2b verdicts because 2b reviews `git diff
<default>...<branch>`, anchored on the merge-base, which the default branch moving does not
change. **The unpushed-main group is the exception** (round 2, execution lens): its diff is
`origin/<default>...HEAD`, so a commit on local `<default branch>` since the prepare (a claim flip
during an overnight build, or the resume's own Step 1b save) is unreviewed, and `RERUN 3` naming
local `<default branch>` re-runs 2b for the group. Steps 3 and 3c read the default branch directly.

`finish` re-reads `origin/<default branch>` because Step 3c fetches it after `begin`; comparing
the resume against `begin`'s value would re-run Steps 3 and 3c on every resume.

### Why the resume runs Step 1 and a first check before asking anything

The spec's § 3.4 order was load, ask, apply, check, re-run, Step 3b, and did not place Step 1. The
first build put Step 1 after the answers on a false reason (that a Step 2a 3a "Commit it" answer in
a `--clone` workspace needs Step 1-pre; that answer is offered only for a linked worktree). Round
1's semantics lens then showed the order defeating the maintainer's ruling: answers applied before `check`
had committed to, or driven a smoke for, a branch another close had already merged, and the 3a
commit moved its tip, so `check` printed `RERUN`, not `GONE`. So the resume runs Step 1 (1-pre and
1b move what `check` reads), checks, drops each `GONE` branch, and only then asks and applies; a
second check after applying catches the tips the 3a answers moved, which is the spec's reason for
applying before checking.

### Why answers are marked `applied`, and a re-run reuses an outcome

The resume can halt after applying (a Step 3c question with no branch left unanswered), and
`load` then accepts the run again. Without a mark, the second resume re-applied every answer:
a second 3a commit exits non-zero, which the step reads as SKIP; a smoke is driven twice; an
unrunnable defect is filed twice (round 1, semantics lens). The same hazard sits inside one
resume: a step re-run after an answer was applied raises the same question again, and taking the
*answer* rather than its *outcome* would drive the smoke again. Step 3c exists for procedures that
act outside the repository.

### Why answers given in the resume are not asked again by a re-run Step 3c

Step 3c re-asks a merging doc's recorded smoke answer by design (Step 3c — provenance, *Why a held
doc links no task*), so a resume that recorded an answer at item 5 and then re-ran Step 3c would
ask the same question twice in one session. The `KEY:` line is a hash of the section's text, so
an unchanged section keeps its answer and a changed one is asked again.

**Spec § 3.6's carrier re-pointing is not built.** It assumed the resume records Step 3c's answers
after Step 3b has removed the worktree a `KEY:` line names. The resume records them at item 5,
before Step 3b, so the worktree path is still there.

### Why the resume loads Step 3c's arm itself

An earlier build moved Step 3c's signal rules (the label meanings, the four options, the halt rules,
the tally and the recorder) into `steps/3c-signals.md`, which the core's stub loads when the
detection prints `SMOKE_REQUIRED`. Item 5 applies the answers a prepare recorded before anything
re-runs Step 3c, and the prepare's receipt does not carry over: each invocation's `begin` opens a
fresh close id. A Step 3c that item 6 re-runs (on a `RERUN 3` line, or because Step 2a or 2b
re-ran) fires the stub on its own, but item 5 comes first. So item 5 loads the arm whenever a
Step 3c question is recorded, answered or parked: a **Hold just this branch** park's meaning is in
the arm too (round 1, lens A). It applies the arm's rules and does not ask its step 2, because item
4 has asked each recorded question, and `smoke_record.py` overwrites a recorded key without
complaint, so a second ask could replace the first answer.

### Why `consume`, and why Step 2b's files are copied

A second resume of the same run after Step 3b has removed worktrees would act on state that no
longer exists, so `consume` marks the run used and `load` and `check` refuse it after that. Step
2b's `2b-conventions.md` and `2b-security.md` have fixed names: the first is removed and rewritten
whenever a Step 2b takes its write-once arm (not on the paste arm), the second whenever
`security_map_filter.py` answers `SPAWN`, so a dry run or another close between prepare and resume would leave `4a-fix` with
another run's conventions; the copies in `2b/` go back when Step 2b did not run during the resume.

### Why the allow-rule is required only under the two flags

`Bash(python3 sysop/scripts/close_run.py:*)` is seeded by `install.sh`, but a consumer whose skill
copies are newer than their `settings.json` would otherwise have every ordinary close refused by
the guard for a rule only a prepare or a resume uses.

## The Step 4d split — provenance

### What was ruled, and by whom

The maintainer ruled at the open (2026-10-08): build the Step 4d split first, attended,
with the `## Unattended close class`, the `--agent` ownership filter and the unattended
dispositions of the 76 Step-4-on stops left for later phases; `pr` policy only; a second reader
the consumer configures in its own section, with the Codex format verified before the parser was
written; and GDP's deploy question (a merge to its default branch deploys a service that shares
code with the API) gated on a human check, not on this build. The design it executes is
`tools/UNATTENDED_CLOSE_SPEC.md` § 4 and § 8 (maintainer-side, not in the public mirror).

### Why every other close stops on `AWAITING`

A second close during the gap would cut a new integration branch from local `<default branch>`,
which still carries the first close's unpushed commits (claim flips, Step 1b's save), and open a
second PR holding the same work. `close_run.py reader`, `begin`, `load` and a second `hand-off` refuse too,
so a `--request-review`, a `--prepare`, a `--resume` and a second hand-off are stopped even by a
runner that skips the prose check. **An ordinary close is stopped only by the prose**: it runs no `close_run.py`
command before Step 4d, and the one script every close runs first, `default_branch.sh`, is run
by other skills too, so it cannot refuse on a close's marker.

### Why Step 4c keeps the locks under `--request-review`

Step 4c removes each closed task's lock before the PR merges. In an attended close that window is
minutes. Across a hand-off it lasts until `--land`, and for that whole time the task is
`in_progress` on `<default branch>` with no lock: `validate_tasks.py` Invariant 9 fails on the
default branch, so every claim path's validator and the shipped `pre-commit-tasks-validate`
example refuse, and `/claim-task` reads the task as `resumable`. Keeping the lock until
`close_run.py landed` keeps the default branch valid. The `done` flip on the integration branch
with a lock still on disk is not an error: Invariant 9 reads `in_progress` tasks only. Parked
markers and claim artifacts are still removed at 4c, as in an attended close.

### Why half A takes the pushed-from SHA as an argument

Step 6's reset gate needs local `<default branch>`'s SHA at the push. `hand-off` could
read it itself, but a claim committed between the push and `hand-off` would then be recorded as
pushed, and Step 6's `rev-list` would not list it, so the reset would drop it. The runner passes
what line 2b printed, and `hand-off` checks it is the merge base of local `<default branch>` and the
pushed head (round 1: an ancestor check passed any older SHA, which Step 6 would then read as
commits made after the push).

### Why the main checkout goes back to `<default branch>` at the end of half A

Half A stops with the primary checkout on `merge/review-close-*`. Left there for the gap, every
`/claim-task` and `/auto-build` run would meet `_shared/main-push-guard.md` Rule A's assertion.
Half B never reads HEAD: it merges the recorded PR number with `--match-head-commit` on the
recorded head, under both shapes, so a push to the branch during the gap refuses the merge
instead of landing unread code.

### What the Codex reader was built from

GDP's own PRs carry no Codex review yet (its 200 most recent PRs had no reviews, and its
`OPS-CODEX-PR-REVIEW-MANUAL-MODE` task, which connects the app, was still open), so the format
was read off public PRs reviewed by `chatgpt-codex-connector[bot]`, on 2026-10-03 and 2026-10-08:

- **Findings** are one PR review, state `COMMENTED`, whose `commit_id` is the reviewed head and
  whose body names `**Reviewed commit:**`; each finding is an inline comment on that review
  starting with an image badge whose alt text is `P<n> Badge`. **P2 badges occur**, so the
  OpenAI page's "Codex flags only P0 and P1 issues" is not what the app does; `blocking`
  defaults to `P0 P1` and the rest are reported and merge.
- **A clean result** posts no review. The app reacts `+1` on the PR, and on newer installs
  edits a summary comment (`<!-- codex-pull-request-review-summary -->`) whose table row shows
  `Completed` and the 7-character commit.
- **A review can lag the head.** One sampled PR's review named a commit the PR had already moved
  past.
- **A usage limit** is an issue comment, not a review.

So the reader binds every verdict to the recorded head: a review counts only when its
`commit_id` is that head; the newest summary comment is read before any review is, and a
`Running` row waits while one it cannot parse parks; a summary whose every row is `Completed` on
that head, with no review of it, is the only clean result; a `+1` never merges, because a reaction
names no commit and under the PR-reuse shape a review of an earlier head can finish after the
request (round 1, record lens); a review of another commit submitted after the request is that
lagging review, so it is reported and the reader waits for the head's own (round 2: parking on
it cost a re-request every time). A finding with no readable badge, a review with no
finding, and the usage-limit comment park. **Why the summary is a clean signal by itself
(round 1, both execution and semantics lenses):** a reaction is one per user and content, so a
`+1` from an earlier clean review is never re-created, and a re-request after a fix, or a
PR-reuse close of a PR Codex already passed, could otherwise only time out. **An install whose
app posts no summary comment never lands a clean result**: it waits, parks on the timeout, and a
human merges. That is the price of binding the verdict to the head, and it is stated rather than
bought back with the `+1`. Half B also re-reads the PR's base (round 1: `--match-head-commit`
pins the head only, so a base edited to another branch would have merged there), and a PR found
already merged at another head is reported as merged outside the gate, then cleaned up, because
it has landed either way. The
request is posted with `gh api -f`, never `-F`: `-F body=@codex review` would read a file named
`codex review`.

**Unverified:** that a `@codex review` comment triggers a review in manual mode (every sampled
review was triggered by the PR opening). GDP's first manual review settles it; until then a
missing review times out and parks, which is the safe failure.

### What `abandon` leaves (round 1)

`abandon` refuses an open PR (close it or land it) and a merged one (`--land` finishes that,
reporting a merge of another head, whatever the record's request status: round 2 found a failed
or interrupted request on a hand-merged PR left every command refusing). On a PR closed unmerged it removes `AWAITING` and nothing
else. The integration branch still holds Step 4c's `done` flips and consolidation, the tasks are
`in_progress` on `<default branch>` with their kept locks, and their pending docs are gone,
because Step 4c consumed them: the state Step 4d-1 leaves for a stuck PR, which a later ordinary
close does not pick up. The way back is to reopen the PR before abandoning, not after.

### Why one hand-off is recorded at a time

`hand-off` takes `sysop/runtime/close/.hand-off.lock` with `O_EXCL` around its check-and-record
(round 1 ran two concurrently and both recorded, each posting a request). A hand-off killed
inside it leaves the file; the refusal names it.

### Why the timeout defaults to 20 minutes

It is the default GDP's task states, "to be set from measurement". Nothing in Sysop measured it.

## The unattended close class and the `--agent` selection — provenance

### What was ruled, and by whom

The maintainer ruled at the open (2026-10-08), each answer the recommended option, to build the
land half first: a consumer `## Unattended close class` (an allow list, exclusions and
a `blast_radius` ceiling; `manual_smoke`, `solo` and held tasks always excluded; the governing
files always excluded; the close's own bookkeeping paths the consumer's to allow, with a
warning), an `--agent` ownership filter at selection, and `--land --unattended`, merging with no
human under `pr` policy and a `## Second reader`, re-checking the class at land, parking durably.
**After the phase's third adversarial round the maintainer narrowed it: the class, the selection and the
durable park shipped; the unattended land did not**, until a later build rebuilt it on the server
side (below). The design record is `tools/UNATTENDED_CLOSE_SPEC.md` §§ 9 to 12 (maintainer-side,
not in the public mirror).

### Why the first land was left off

Each of three rounds found a way for a PR, or the agent that made it, to shape what the gate
trusts, and each round's sharpest finding was in the previous round's fix: a branch clearing its
own task's `manual_smoke` in the index the class must admit; a stale base hiding a revert; a
diff base that was the PR's recorded base rather than the tip; task fields read at local
`<default branch>`, which the agent's own unpushed commits write; a symlink routing an edit to
`CLAUDE.md` or `.claude/` around the fixed exclusions. A gate that reasons on the client about
content the merger can shape had an open hole after every round, so it stayed off until a
redesign whose trust does not rest there.

### What the land decides now, and why

The redesign (spec § 10) moved the trust to GitHub: a signed check, `close_gate.py`, posted by
an app whose key a branch workflow cannot reach, decides paths, task fields and the second
reader's verdict, and the ruleset makes that check, code-owner review and up-to-date branches
binding. The maintainer ruled at the rebuild's opening, each the recommended option:

- **The client stops deciding what the gate decides.** `land-check --unattended` no longer reads
  paths, task fields or the reader. Keeping them as an early park would have kept the read at
  local `<default branch>` that round 3 showed unsafe. What it still reads is what GitHub cannot:
  the kept locks' owner, `report.md`'s held-doc line (`hold:` lives on a gitignored pending doc),
  and Step 6's two local conditions.
- **It verifies the server setup first**, with the token `gh` holds: not the code owner, role
  `write`, a ruleset requiring code-owner review, stale-review dismissal and the gate's check
  from `gate_app:` with strict checks, `current_user_can_bypass: never` on every ruleset on the
  default branch, and the gate environment limited to one branch rule naming the default
  branch. A setup it cannot read refuses. The rebuild measured each of these reads with a `write`
  token on a scratch repository, before the build.
- **What that token cannot read is the human's attestation**, recorded as `attested:` in the
  class, and the land refuses without it: whose credentials the repository's secrets hold (a
  name shows no owner), and `can_approve_pull_request_reviews` (a 404 to `write`). The class is
  in `CLAUDE.md`, a governing file, so no unattended merge can add the key.
- **Ruling (s) stays: every registered check passes before auto-merge is turned on.** Once on,
  GitHub merges on the required checks alone and would ignore a red check the ruleset does not
  require. So the land waits for the whole rollup, and only then turns auto-merge on, which on a
  green PR merges at once (measured). The gate's own reading is taken from its app's check runs
  on the head, not from the rollup, which names no app: a branch workflow posted a green
  `sysop/close-gate` as `github-actions` and the rollup showed it green (measured).

**Measured at the rebuild** on a scratch repository (spec § 12, maintainer-side): `gh pr merge --auto`
on a PR GitHub would merge now merges it at once; `--auto --delete-branch` arms and fires but
deletes no branch, so the skill deletes it; and auto-merge survives a later push by a `write`
user and merges the new head. So the land parks a PR whose head moved when it reads the move
before GitHub merges (a merge at another head reads `MERGED ELSEWHERE:`), and `park`, `unpark`
and `re-request` turn off an arm the land made, because a request for a new head must not inherit
the old head's arm.
A park turns off the land's own arm, and says so when it cannot (an arm someone else turns on
while a hand-off is parked is not read, because a parked land reads nothing from GitHub): a parked PR that GitHub later merged would
leave a hand-off no human had cleared.

### Why the governing set is always excluded

These hold the class itself, the second reader, the merge policy, the permission allow-list, the
skills, the scripts that compute verdicts, and CI. A merge that changes one changes the rules for
every later merge the class admits, so it needs a human however the consumer writes the class.
They match without regard to case, as consumer exclusions do (a case-insensitive filesystem
writes `.CLAUDE/x` into `.claude/`), and `X/**` matches `X` itself. The first build shipped four
(`CLAUDE.md`, `.claude/**`, `sysop/**`, `.github/workflows/**`). A later one widened them to the
set spec § 10.3 item 2 defines by name. A review round showed that a path list misses the
same files elsewhere: `CLAUDE.local.md` loads from subdirectories, Codex prefers
`AGENTS.override.md`, and git reads `.gitattributes` and `.gitmodules` as instructions. That build
also normalises with NFKC before casefolding, which adds the compatibility forms casefolding
alone misses: `ＣＬＡＵＤＥ.md` (fullwidth) is excluded too. **What it costs, measured:**
of GDP's 200 most recent `review-close: consolidate` PRs (2026-07-12 UTC to 2026-10-08), 66
touched one of these paths: `CLAUDE.md` in 40, the convention and security maps in 33,
`.github/workflows/` in 22, `checks.yml` or `checks.project.yml` in 16, `sysop/` in 1. The close
commits none of them into the PR, so they came with the merged branches or local
`<default branch>`'s unpushed commits; a squash does not say which. Selection sets aside a
branch that touches one, so the rest of such a close can still go to its second reader.

### Why the close's own paths are the consumer's to allow, and why `class` warns

A close commits `tasks/index.yml`, task bodies moved from `tasks/open/` to `tasks/archive/`,
`PROJECT_STATUS.md`, the changelog and the review-task files itself (Steps 1b, 4b and 4c).
Exempting a fixed set would also exempt a feature branch's edits to those files, so the allow
list is the whole truth, and `class` and `eligible` print a `WARN:` for each close-written path
the class refuses. Root files are checked in the case the repository tracks them, because Step
4c writes the changelog at the tracked case, and one consumer tracks it in lower case.

### Why a park is durable

A `PARKED` record, written by `close_run.py park`, keeps a hand-off for a human: `/sitrep` reports
its tasks as `land parked`, routed to a human, not to `--land`. A human clears it with
`re-request` (after a fix), `unpark` (to read again unchanged, refused when no review was
requested) or an attended `--land` that merges.

### Why selection does not blame one branch for an unreadable shared doc

The main checkout's `sysop/runtime/pending-docs/` holds every branch's docs. A doc there that
does not parse has no readable `branch:`, so `eligible` cannot say whose it is, and setting every
branch aside for it would stop the whole close on one file. Step 4c 1c reports it as
`UNREADABLE:`. A branch's own workspace holds only that branch's docs, so an unreadable doc there
sets that branch aside.

## Half A with no human — provenance

### What was ruled, and by whom

The maintainer ruled half A's stops per class first (`tools/UNATTENDED_CLOSE_SPEC.md` § 13, a
maintainer-side spec that does not ship, rows (aj) to (ay)), and at the build's open that the night runs headless under `dontAsk` ((az)) and
that its first live run seeds the `Edit` rules a later build will ship ((ba)). The shape is
`--prepare --agent <name>`, then `--resume <run-id> --request-review --agent <name> --unattended`:
the prepare already asks nothing, so the build is the resume's unattended arm.

### Why one timing rule and not 77 sites

The 134 half-A stops fall into ten classes, but every park of the close comes out early when it
fires before Step 4-pre and durable from Step 4-pre on, except three Step 3b exits. So the runner
gets that rule and the named exceptions. `tests/test_unattended_half_a_build.py` checks the 77
ruled close-park arms, at the pin the rows were taken at, against that model of the rule; it
reads no `SKILL.md` text, so the shipped sentence is held by its hash pin. Before Step 4-pre the
close has merged nothing, and the next run's prepare starts over on whatever moved. From Step
4-pre on, an integration branch exists, Step 4c has deleted the docs it consolidated and the locks
it unlinked, and only the step's own recovery finishes the work. Step 3b's collect exit 5 and the
rollback's exit 4 (refused) and exit 8 (a partial pass) leave main holding a collected doc for
a branch that will not merge, and Step 4c would consolidate it on the next run ((av)).

### Why the early park is `halted.md` and the durable one is `STOPPED`

`close_run.py load` already refuses a run with `halted.md`, and `begin` does not read it, so an
early park ends that run without blocking the next night's prepare. A durable park must block
every later close, so it is a marker `begin`, `load`, `reader`, `hand-off` and the unattended land
refuse on, beside `AWAITING`. It is not half B's `PARKED`, which needs a hand-off record: a durable
park before `hand-off` has none, and it goes in the resumed run's directory. `stop` refuses only
what it cannot record, because a refusing stop would leave the close unguarded.

### Why a branch hold is keyed to the head, and why `unhold` replays no answer

A `VERDICT: BLOCKED` or an unanswered question is about the commits it read. A new head is new
work, so it clears the hold, and an unchanged head would park the same way every night. `unhold`
records the human's answer but applies none: the next prepare asks the same question again, and
with no human it holds again. An attended close asks it and acts on the answer, so that is the
path for an answer; `unhold` is for a cause fixed outside the branch.

### Why Step 3b's empty-workspace arm applies exit 6 by hand

The unverified sequence § 13.3 named was run through the shipped heredocs
(`tests/test_review_close_early_park_recollect.py`): a branch collected and its worktree removed,
then an early park. The next run finds no workspace, passes the exit-8 test, reads the branch as
not landed, still sees the doc at Step 3c and routes it at Step 4c. One gap: the collect is the
only reader of `branch_tip:`, and with no workspace it does not run, so a head that moved between
the two runs merged under a stale doc. `/sitrep`'s drift reader followed the old blind spot on
purpose and now measures that case too. A `--branch` claim's `main-checkout` shape is unchanged,
a lockless one included: the survey reads the main checkout's branch as Step 0 does.

## Step 6 and 4d-1 — provenance

### Why Step 6 keeps a held doc's branch

It is the principle Step 4d-1 applies when a PR is stuck (*"Leave the integration branch, the
feature branches, the worktrees, and the `sysop/runtime/locks/` in place. Skip Step 6
entirely"*): cleanup is gated on the work being finished, and a held task's work is not. The
listing is a prescribed `find` because a headless session has no Glob tool: the
shipped land's first `dontAsk` night composed `ls …; git branch -a; git worktree list` for it,
which the read-only set happened to admit.

### Why Step 6 checks for commits made after Step 4d's push

`gh pr merge --delete-branch` returns HEAD to the default branch, and `claim_task.sh
--commit-claim` commits only while HEAD is there (`claim_task.sh`'s Rule A check), so a concurrent
claim during Step 5's wait lands on local `<default branch>`. The squash does not contain it, the
tracked-tree gate prints `CLEAN`, and the reset drops it: reproduced on a pure-git fixture before
the fix. Before `gh pr merge`, HEAD is on the integration or approved branch from Step 4-pre on,
so no claim can commit there; the SHA printed at the push is therefore the last one this cycle
owns. **`^origin/<default branch>` is load-bearing** (round 1, semantics lens): whenever `gh`'s
fast-forward succeeds — the PR-reuse shape when local `main` held nothing the branch lacked, or the
integration shape with no local-only commits — local `main` *is* the squash, and a bare
`<sha>..<default branch>` names the squash itself on every such close. The rebase it offers replays exactly the late commits; a commit
already upstream is dropped by `git rebase` as already applied. The unattended Half A must record the SHA
durably, because the gap there is a whole review wait.

### Why a stuck integration-shape PR is recovered on its branch

By the time a PR is stuck, Step 4c has deleted the pending docs it consolidated (item 6) and
unlinked their locks (item 4's script, `close_index.py`). Neither is in any commit, and Step 4c's index flips, body
moves and doc entries exist only in its commit on the integration branch. A re-run cuts a new
integration branch from local `<default branch>`, re-approves the same branches, and Step 3b's
exit 8 does not refuse them, because its discriminator is the lock (*Why a claimed branch with no
document is refused*). The replacement PR would merge without Step 4c's work, and the old 4d-1
text then told the operator to delete the only branch carrying it. 4a-post's placement note was
the true sentence. The recovery runs `4a-post`'s command list on the fix commit because nothing
else in the close reviews it: the PR's required checks are otherwise its only gate. The PR-reuse
shape is unaffected: its branch carries the 4c commit.

## Step 1-pre — provenance

### Why the close brings a clone's commits across itself

`claim_task.sh --clone` publishes the branch and clones `origin`, so the work happens in a
separate repository with its own object store. Step 4a merges *this* repository's
`refs/heads/<branch>`, which nothing in the close moved: measured before the fix, the clone's
`feat/cl` at one ordinary commit past the claim and the main repository's `feat/cl` still at the
claim commit. Step 2a reviewed an empty diff and Step 4c could mark the task done over work that
never merged. The only branch fetch in the skill (Step 4-pre's) lands in `FETCH_HEAD` and moves
no branch.

The maintainer chose (2026-10-04) to have the close sync the branch rather than require the claimant to
push. The rejected option was for `--clone` claims to push and for Step 2a to refuse a branch
whose local ref is behind `origin/<branch>`. The sync asks nothing new of a claimant whose
history only grows. One whose history was rewritten after a close synced it (an amend, a rebase
onto a newer default branch) meets `REFUSED` and step 0a's remedy, because the close cannot tell
a deliberate rewrite from lost work.

**No allow rule was added.** The heredoc binds the seeded `Bash(python3 -:*)`; its `git fetch` from
the clone path, which no seeded `git fetch origin:*` rule would cover, runs inside it as a
subprocess the permission layer never sees, as Step 4c's `git add` and `git mv` do.

**The source is the clone directory, not `origin`.** Nothing in a clone pushes after
`claim_task.sh` publishes the branch, so `origin/<branch>` sits at the claim commit too, and a
fetch from `origin` would be inert on the ordinary close.

**Fast-forward only, in both directions.** The fetch's refspec has no `+`, so git itself refuses a
non-fast-forward and a branch checked out in one of this repository's worktrees; the heredoc
classifies first so the line names the reason. A stale lock whose clone is gone no longer hides a
live lock on the same branch (round 1 measured both sort orders). A branch here that holds commits the clone lacks is `REFUSED` whether or not it
also holds the clone's tip. Round 1 first passed that case as `BEHIND`: after `git reset --hard
HEAD~1` in the clone, the commit the claimant had dropped stayed on this branch and would have
merged.

**A dirty clone is SKIPped.** Step 1a's `dirty` class never saw a clone, because `git worktree
list` does not list one, and that cost nothing while the clone's commits could not merge. Once
they can, a half-committed clone would merge its committed half, which is the merge the
ISSUE-0016 guard exists to stop. The state read is every worktree *of the clone* whose state is the
branch's: one standing on it, one rebasing or bisecting it (the operation records the branch), and
one detached at or past its tip. Round 2 measured the root-only read syncing over a linked
worktree of the clone that held the branch with edits, and with a conflicted rebase; round 3
measured round 2's "any detached worktree" rule reporting a look-around checkout of the default
branch as `DIRTY`, which no remedy could clear. A worktree whose directory is gone is skipped. In each such worktree an
operation in progress is `DIRTY` by itself (rebase, `am`, merge, cherry-pick, revert, bisect, and
the `sequencer` a multi-commit cherry-pick or revert leaves behind with a clean tree, which round 2
measured syncing with half the picks applied); so is a detached `HEAD` that continues past the branch's tip,
whose commits would otherwise be left out of what merges. Round 1 measured the first cut, which read
only a clone standing on the branch, syncing a clone mid-rebase. Step 1a's ISSUE-0043 downgrade
applies: an untracked symlink whose target this repository ignores (a `.venv` link) is not dirt.

**A clone that lost the work falls back to `origin`** (the maintainer, 2026-10-04, after round 2; it is the
"or `origin/<branch>` after the clone pushes" half of the original answer). When the lock's clone
is missing, is no longer a repository of its own, or no longer holds the branch, the same
fast-forward runs against `origin`'s branch, and the line names `origin` and why. `GONE` and `NO
BRANCH` mean neither holds it. `origin` behind this repository is `CURRENT`, not a refusal:
nothing in a clone pushes, so after a sync `origin` is behind as a matter of course, and round 3
measured the first fallback refusing every later close once the clone was gone, with a remedy
(fetch from `origin`, forced) that discarded the synced work. Whether `origin` holds the branch is
read with `ls-remote`, not from the wording of a fetch error. Round 2 found the first cut's remedy ("fetch from `origin` and
re-run") looping: `GONE` was decided by the lock and the directory alone, so bringing the work
across by hand could never clear it. Pushing to `origin` now clears it, because the close reads
`origin` itself. A directory re-created inside an enclosing repository is not mistaken for that
repository: a clone must be its own top level, compared by file identity rather than spelling
(round 3 measured a string comparison reading a live clone as missing when the lock's case
differed from the disk's, which silently reopened the entry).

**Two locks recording clones for one branch are refused.** The close cannot tell which holds the
work; the first cut took whichever sorted first.

**Locks only**. Round 1 added a scan of sibling directories to
catch a `--clone` claim made without `--lock`; it synced an ordinary personal clone of the same
project, and its replacement (report it as `UNCLAIMED` and SKIP) could not be cleared by its own
remedy, SKIPped a branch whenever any old checkout or released clone kept the name, and skipped the
dirt check once a human brought a clone across. `/claim-task` always passes `--lock`, so a lockless
`--clone` is a hand-typed invocation; the close sees only this repository's branch for it, as it
did before this phase, and Step 1-pre says so. Step 2a step 3a has the same gap: it finds no
workspace for such a claim, and no file is lost, because a clone is never removed.

**The examined commit is the one that lands.** The commit the checks read is fetched by id into
`refs/sysop/clone-sync/<branch>`, and the branch moves to it by a compare-and-swap `update-ref`, not
by a second fetch from the clone: round 3 measured a commit landing between two fetches and the line
reporting `REFUSED` over a branch that had moved. A branch checked out in one of this repository's
worktrees is refused before the update, since `update-ref` does not refuse it the way `fetch` does.
The fetch does not recurse into submodules (round 2 measured one that moved the branch and then
exited 1 on an unreachable submodule) and times out. Every ref left under the private namespace by
an interrupted run is deleted first; round 3 measured one blocking the fetch for good. Under
`--dry-run` nothing is fetched: round 3 measured the origin arm moving `refs/remotes/origin/<b>` and
writing `FETCH_HEAD`. Lines print as they are produced, so a crash after a sync leaves the record of
what moved.

**`ignored_refs.py` compares the clone's `refs/heads/<branch>`,** the ref the sync fetched, not
its `HEAD`. Round 1 measured the `HEAD` read refusing a finished clone that had stepped back onto
the default branch on every run, with a remedy (re-run the close) that could not help.

## Step 2a — provenance

Editor-addressed history for `### 2a. Feature Branches`. Nothing here binds the runner.

### Why step 3a asks about gitignored files the branch reads

A consumer close received a branch with every executor gate green whose code imported three
JSON fixtures a blanket `*.json` rule had kept out of every commit. The gates that read the
working tree (the test runner, the build) found the files; the merge would not have carried
them, and the merged tree would have failed its build and CI. A review lens caught it by reading
the tree. Nothing in the path asked whether a file the diff depends on was committed, and
`git status --porcelain` does not list ignored files, so Step 1a classified the worktree clean.

**Ask, not halt**: gates legitimately create ignored files, and an ignore can
be deliberate, so a hit is a question rather than a verdict. The reporter's alternative, "files
newer than the claim base", is unusable for the same reason: a gate run makes every output file
newer than the base.

**This step is the only asker**. The executors quote their hits and file
nothing. The first build had them file a task through the "an answer would make it fixable"
route, but only `/claim-task` option A ever asks that question before the close; on option B and
`/auto-build` the filed task merged as open after this step had answered it, and a later
`/auto-build` could implement the task's other fix against the human's answer.

**Only files a file pattern ignores**. A directory a pattern ignores as a
whole is one entry in `git ls-files --directory`, and the script does not read inside it. Every
false hit measured on one consumer's live claim worktrees was inside such a directory (a
lockfile naming `node_modules/...`, a test naming `tests/__pycache__`). The check reads the
consumer's resolver configuration where the maintainer ruled it should: a quoted token
through the `compilerOptions.paths` of the nearest `tsconfig.json`/`jsconfig.json` that declares
them, and a root-absolute URL through the `public/` directory beside the nearest `next.config.*`.
What it still cannot see: an import from a directory ignored as a whole, a config's `extends`, a
config under another name (`tsconfig.app.json`, reached by `references`), a bundler alias map, and
a name built at run time (`importlib`, a template literal, `import.meta.glob`). Its summary line
names the first and the last. Step 3b step 0b's preservation does not depend on the check, so none
of these loses a file; they merge without one. Prose (`.md`, `.rst`, `.adoc`) and
`*ignore` files are not read: over 40 commits of the same consumer's history, an early matcher
that read them reported 25 hits, 24 of them from `.md` files naming a tool, cache or
environment path. Those figures, and "nothing on the four live claim worktrees", came from
intermediate matchers; the shipped matcher measured 9 hits over the consumer's last 40 commits
and 20 over the last 200, measured read-only on that consumer.

**A directory reference needs a string literal or a glob.** `Path(__file__).parent / "fixtures"`
and `path.join(__dirname, "fixtures")` read every file in a directory beside them, and the
round showed the first build missing them while step 0b deleted the only copies. Resolving every
mention of a directory reported every ignored file under `frontend/` and `data/` on the same
consumer, from task text, comments and regexes. So a directory counts only inside a string
literal, beside the referencing file or, for two or more components, from the root, where test
runners stand (`Path("tests/fixtures")`); and a glob counts only for the files its pattern
matches, `/`-aware, beside the file or from the root.

**Four answers, and which is recommended**. `Commit it to the branch` is
right for a fixture or data file and wrong for a secret, and the file name cannot tell them
apart: the reporting consumer's `*.json` rule sits in the secrets section of its `.gitignore`, beside the
fixtures it also caught. So `Keep it ignored` is the default recommendation. It copies the file
into the main checkout, the branch merges without it, nothing is committed and nothing is lost;
the copy says `ALREADY` when the main checkout holds it (a symlinked `.env` included) and refuses
to overwrite a differing file or follow a link into the worktree. `Commit` is recommended only
for a path with a component containing `fixture`, `testdata` or `test_data`, or `__snapshots__`
(the maintainer, 2026-10-04: the consumer's own fixture directories are named like `<name>_fixtures/` and
`fixtures_<name>/`), and never offered for a symlink. Where `Commit` is not offered, such a path
gets `Reject`, the answer that carries the commit-it-yourself instruction.

**An unanswered line SKIPs the branch, in every shape.** The round-2 lenses showed "keep the
worktree" protecting nothing when the main checkout held an identical copy, and nothing at all
for a clone or a `--branch` claim, so an unanswered hit merged: the reported defect, with no
answer recorded. The SKIP is what the ask promised. A check that did not run is asked once
(`Hold` or `Merge without the check`), and an away result holds.

**Commit and copy go through a heredoc.** `git -C <workspace> add` and `git -C … commit` bind no
allow rule (`-C` is not a wrapper the matcher strips), so under `dontAsk` the recommended answer
would be denied. The heredoc runs under `Bash(python3 -:*)`, and its commit names the path, so
nothing else staged in the worktree rides along.

**Each workspace shape answers differently.** A `--clone` workspace is a separate repository: a
commit the close made there would never reach this repository's branch, which is what Step 4a
merges. So the human commits it in the clone and re-runs the close, whose Step 1-pre brings this
repository's branch to it, and the check refuses a clone whose tip is not this repository's
branch: reading the clone's tip had reported a file committed only there as clean. The script compares a clone with the
caller's main checkout, because the clone's own common dir is itself; from the main working tree
it takes that tree's top level, which holds under `--separate-git-dir` and in a submodule, where
the common dir's parent is somewhere else. A `--branch` claim's workspace is the main checkout,
which may be on the default branch at close time, so the check reads the branch's commits
(`--branch`) rather than whatever is checked out.

**The commit answer costs a re-run when the doc carries `branch_tip:`, and the step says so.**
The close commits the file onto the branch, which moves the tip past the doc's `branch_tip:`, so
Step 3b's collect exits 6 and SKIPs the branch; a doc without the key is collected as it is. That is the staleness gate doing its job: a doc must describe the tip that
merges.

## Step 2b — provenance

Editor-addressed history for `### 2b. Prevention Convention Check`. Nothing here binds the agent
running the skill; it is why a rule in that step is shaped the way it is, so that an editor
changing one knows what the shape was bought with. Authored, not copied — the runner keeps the
rule, this keeps the argument.

### What the doc-only skip's cross-reference used to claim, and why it is gone

The paragraph scoping step 0's skip away from step 3b's gate carried a parenthetical retracting an
earlier draft of itself. That draft claimed `security_map.md` *"routes root operational docs to
**A02**"* — **it does not**, because the core map's five sections are shell scripts and hooks,
`Dockerfile`, `.gitignore`/`.env*`, CI workflows and skill markdown, and the only A02-routed root
paths among them are configuration rather than documentation. (Verified against the map itself,
not inherited: those five `##` headings are what the shipped file carries.)

**The retraction and the sentence it retracted lived in different blocks, and only the retraction
was ever removed.** The false claim was restated two paragraphs later, inside the *"Check the
second condition"* blockquote, as a parenthetical gloss on secret-scanning — so the step asserted
and denied the same proposition within three lines, and had done since the correction was written.
That is why both blocks were thinned in one commit rather than separately: relocating the
retraction on its own would have left the assertion standing with nothing answering it, which is
strictly worse than the contradiction. The surviving sentence — secret-scanning is a separate
expectation covered by the project's scanner, and the skip neither touches nor waives it — was
always the true half and needed no parenthetical to stand.

One more claim moved with it. The llm pack's `<prompts dir>/**/*.md` glob is a **placeholder**
until a consumer localizes it, so on a stock install `.claude/skills/**/*.md` is the concrete
member carrying the argument that a doc-only target can still match a security glob. That is a
statement about how far the evidence reaches, not about what the runner does with it — the
instruction is the same either way: evaluate step 3b's gate on its own.

### Where the doc-only escape used to be sealed

Until an earlier build the escape hatch — *if any convention names documentation, config, prompts,
fixtures or committed data, do not skip* — was sealed inside the one section the predicate read.
A project whose only doc-governing rule lived in a convention-map glob, or in `## Testing
Patterns`, got the skip **and** the escape wrong together, from the same blind spot: the predicate
never saw the rule, so it skipped, and the escape never saw it either, so nothing reopened the
skip. Widening the predicate to three sources without widening the escape to the same three would
have left exactly half of that defect in place.

### Why isolation is kept beside the pinned checkout, and the second reason that was false

Keeping `isolation: "worktree"` alongside the pinned checkout has exactly one reason: the isolated
worktree is where the agent's own writes land, and containing them is the one thing that contained
both measured breaches. An earlier draft of that bullet offered a second reason and it was wrong.
It claimed that without isolation the first two assertion commands would report clean *while the
pinned checkouts leaked*. They would not. The fifth command reads `git worktree list`, not harness
state, so it finds the pinned checkouts whether or not isolation is set; with no isolation the
first two commands become **dead text** — vacuous, because their subject genuinely does not exist —
rather than blind. Nothing leaks undetected either way, so the false reason was load-bearing for
nothing and its removal costs the rule no force.

**The incident behind the spawn list's `isolation` bullet, read with care.** That bullet cites a
run in which an agent moved `HEAD`. The run had an integration
branch checked out at 2b, which this skill's step order does not produce — 4-pre cuts it two steps
later — so read the incident as "off the expected branch", not as evidence about which branch that
is. What the misplaced commit would have cost also depends on policy: Step 6 deletes a merged
feature branch with a safe `git branch -d`, and force-deletes only the integration branch under
`pr`. (Moved here from the bullet.)

### Why each lens gets its own scratch directory, and why the orchestrator makes it

The prompt once told every lens *"run it from a heredoc or write under `/tmp`"*: one unscoped
location, substituted identically into every prompt in the wave. A consumer's seven-lens wave
(internal tracker #705, the reporter's measurement) had one lens capture its target's diff to a file,
then read it back as 1,084 lines of an unrelated `CLAUDE.md` diff that belonged to a sibling's
target. That lens noticed, re-derived into a uniquely named path and checked the file stable before
reading it, so its verdict stood. **The recovery was the accident, not the property.** A lens that
captured once and read once would have routed one target's conventions against another target's
diff and returned `VERDICT: APPROVED` over a tree it never examined, which is the failure the pinned
checkout exists to prevent, arriving through the write path instead of `HEAD`. Nothing looks
corrupt, because both files are real diffs of real targets. The busiest closes are the most exposed,
since the fleet grows with the number of targets.

So the orchestrator gives each agent a scratch directory of its own beside its pinned checkout,
and writes the path into that agent's prompt: the same shape as the checkout pin, for the same
reason. **The weaker alternative was refused:** telling each lens to put its target's name in its
scratch filenames relies on every lens complying, which is what the pinned-checkout rule stopped
relying on.

**Since the headless-prepare build both live under the ignored `sysop/runtime/`**, made by
`review_pins.py add`: the checkout at `sysop/runtime/pins/<id>` and the scratch directory at
`sysop/runtime/scratch/<id>`, where `<id>` is `2b-<first 12 of the sha>-<6 random hex>`. Until
then the step made both with `mktemp -d` in the system temp directory and refused a pin inside
the repository with a containment check. Under `dontAsk` that block was denied line by line
(`mktemp -d`, `PIN=$(…)`, `case`, `git -C`), and a checkout outside the project is one a reviewer
cannot read there at all, so the location inverted. **`add` refuses a path git does not ignore,**
because an unignored checkout is an untracked directory in the very tree the step's baseline is
compared against: it would show in the delta as a phantom mutation and could mask a real one. The
script prints both paths as absolute paths, because no shell variable survives to the next call
and the orchestrator must write them into the prompt as literals. **`review_pins.py clean`
removes each checkout and its scratch directory** after the verdict, never with `--force`: a
checkout `git worktree remove` refuses as dirty is reported `DIRTY:` and kept, because a reviewer
wrote to a tree its siblings read, and one whose `HEAD` is no longer the commit in its name is
reported `MOVED:` and kept, because a commit made there would be removed with it.

**Step 2b checks that the wrapper is on the reviewers' fork before it spawns them.**
A reviewer reads its pinned checkout through `sysop/scripts/git_ro.py`, run from its own working
directory, which is the `isolation: "worktree"` checkout. That build measured where that checkout
comes from with one spawn in a consumer whose local default branch was one unpushed commit ahead
of `origin/<default branch>`: the agent's `HEAD` was the remote branch's commit, and the unpushed
commit's file was absent. So on the first close after a consumer installs or updates to a Sysop that ships the
wrapper, until that update is on `origin`'s default branch, every reviewer's first call fails and
the gate cannot approve; under a `pr` merge policy that includes the close that would land the
update. The failure is loud, but it costs a wave of spawns and reads as a broken round, so the
check stops the close first with the remedy. Where a repository has no `origin/<default branch>`
the check reads the local branch, which is a guess: that case was not measured. Running the main
checkout's copy by its absolute path would avoid the wait, but needs a seeded rule per install;
spawning without isolation would give up the containment of stray writes that two measured
breaches relied on.

**The baseline capture removes both files before it reads either, and reads the tree with
`-uall`.** The removal is what makes a capture that fails part-way leave no file to diff against,
so `check` reports `MISSING BASELINE:` rather than diffing against a previous close's tree. `-uall`
is required because plain `--porcelain` collapses an untracked directory to one `?? dir/` line,
so an agent writing into a directory that was already untracked is invisible; `check` reads the
tree the same way. The tree snapshot also records the primary's `HEAD` and branch tips, because a
reviewer's commit or checkout on a clean tree changes no status line, and
leaves out the two baseline files and `2b-conventions.md`, which the step writes after the read
and which would otherwise show as an agent's wherever `sysop/runtime/` is not ignored whole.
`review_pins.py` reads the baselines by their plain relative path, which is correct because Steps
2a–2d run in the primary checkout's top level by construction, and the script refuses to run
anywhere else.

`4a-fix`'s re-check spawns one agent, so no sibling can clobber it. It still gets its own
`$SCRATCH`, because its prompt is Step 2b step 3's, and that prompt names a scratch directory
to write under. The same rule reaches `/codebase-review` and `/security-audit`, whose fan-outs
carried the identical `/tmp` sentence. `_shared/adversarial-review.md` already said *"Name a
private scratch directory in each prompt too"* before this change; it reached none of the three
runners, which is why the runners now carry the instruction themselves.

Step 4a's conflict recipe had the same shape one level up: its stage extracts were fixed names in
the shared temp dir (`sysop-notes-base.md`, `sysop-ours.yml`, …), so two closes on one machine
overwrote each other's extracts with a plain `>`. Each stage block now makes a directory with
`mktemp -d` and prints it. `4a-post`'s inherited-failure probe keeps its fixed name
(`sysop-base-probe`) on purpose: it is a `git worktree add` target, which refuses a non-empty
existing path, so a collision stops the arm instead of corrupting it; minting it would put an
assignment in front of the call, which then binds none of full mode's seeded
`Bash(git worktree add:*)`.

### The gap the security twin closes, traced along the whole chain

`/claim-task` Step 5 has the *planner* read **both** maps into `## Constraints & Risks`; from there
the security map is never read again before the default branch. The plan reviewer is handed the
plan and `_shared/adversarial-review.md`, which **routes** against neither map: its dimension 6
checks that a *cited* convention was applied correctly, and its dimension 8 checks that
`## Constraints & Risks` carries per-file bullets citing both maps. That is **citation coverage** —
an audit of the planner's own read, not a fresh routing of the diff. The executor's post-fix
verification re-scanned changed lines against `convention_map.md` **only** — that half was fixed in
the same phase that added the twin, and `/claim-task` Step 7e now reads both maps, so the chain is
closed from both ends rather than one. And step 3 of this step routes against the convention
sources and not this one.

So a branch touching a path the security map governs — an auth handler, an upload endpoint, a
`<prompts dir>` template — reached the default branch with no security-map read since the plan was
written, and the plan's read was of the *intended* change, not of the diff that resulted. That is
the length of the gap, and it is why the remedy is a second agent at this step rather than a
stricter reading anywhere upstream.

### What the security twin reaches on a stock install, measured

Of the 16 sections in a fresh `--packs python` install's `.claude/security_map.md`, **11 carry
placeholder globs** — `<api module>/routes/**/*.py`, `<auth module>/*.py`, `<payments service
module>`, `<data pipeline>/*.py` and the rest. The concrete ones are `scripts/*.sh` and hooks,
`Dockerfile`/`.dockerignore`, `.gitignore`/`.env*`, `.github/workflows/*.yml`,
`.claude/skills/**/*.md` + `.claude/checks.yml`, and `pyrightconfig.json`. Run against a synthetic
diff of `src/api/routes/upload.py`, `src/auth/login.py`, `src/models/user.py`, the gate reports
`no security-map glob matches this diff` — the *"a map that matches nothing reads like a map nobody
consulted"* shape `/security-audit` Step 2a-0 exists for.

**The predicate behind that 11 is worth stating, because exactly one section decides it.** *Carries
placeholder globs* means **at least one** — which is what the runner's own report string says — and
under it the count is 11 of 16. Under the stricter reading, *every* glob in the section is a
placeholder, the count is 10: the discriminator is
`## \`Dockerfile\`, \`<datajobs Dockerfile>\`, \`.dockerignore\` — Container Build`, which mixes one
placeholder with two concrete globs and which the list of concrete sections above also names. Those
two lists overlap on that one section, which is why 11 + 6 exceeds 16. Re-derive rather than
inherit: `grep -h '^## ' core/companion/security_map.md packs/python/companion/security_map.md`
over a fresh `--packs python` install gives the whole population.

This is the shipped map's localization debt rather than a defect in the step, and it is the same
debt an earlier measurement put at 30 of 36 sections binding nothing. The twin becomes as sharp as the
consumer's map is localized, and the runner's obligation is only to say which case it was.

### Why the security sources are written once, and the draft that measured nothing

This step's first draft said *"paste or write-once, on step 1's threshold"* and told the runner to
*"measure the two security sources the same way step 1 measures the convention set"* — which is
prose with no command behind it. Step 1's shipped measurement reads section headings out of a
consumer's project instructions and has no analogue for a map file. The same filing that widened
step 1's paste had forbidden widening a paste without measuring it, and this step introduced a new
paste in the same edit without applying that discipline to itself. Measured afterwards:
`.claude/security_map.md` on a fresh `--packs python` install is **12,828 bytes** by the `wc -c`
it prescribed (12,724 characters), above the 10,000 threshold — so the inline arm is unreachable on a stock install and the write-once arm is
the live path. The runner is still told to measure rather than assume, because a consumer who trims
the map can fall below.

A later build moved the measurement into `security_map_filter.py`, which measures the
target's cut copy rather than the whole map, so the inline arm is reachable again for a target
whose diff misses most of a localized map. § *Step 2b — the security copy* has the rule.

### What the Step 3b disambiguation replaced

The HARD RULE names `## Step 3b: Prepare Worktrees for Merge` explicitly because an earlier draft
of that clause said *"the manual-smoke gate"*, which is **Step 3c**. A disambiguation that names
the wrong step is worse than none: the rule is about worktree preparation, not about smoke testing,
and a reader who followed the wrong pointer would have deferred the removal past the step that
depends on it.

### What a leaked agent worktree collides with, and what already answers it

A leak is not inert residue, and the shape of the hazard is why two of the three steps that
enumerate branches carry an exclusion for it. Step 1c's `git for-each-ref refs/heads/` sweep, Step 2a's *"every non-main local
branch"* and Step 1a's worktree classification all enumerate **whatever exists**, so an agent
branch that outlives its agent is, on its face, indistinguishable from someone's feature work: it
classifies `clean-merged`, a review finds no commits on it, and cleanup offers to delete it.

**Two of those three links are closed, and the record has to say which.** An earlier build
added the `worktree-agent-*` exclusion to Step 1c's enumerator — *"exclude them here and everywhere
else branches are enumerated"* — and to Step 2a, which now skips *"any **agent worktree branch** (a
branch whose registered worktree lives under `.claude/worktrees/`)"*. So a leaked agent branch is
not reviewed at Step 2a, and it never reaches Step 6's per-branch cleanup either — but the reason
is one step further along than it looks, and stating it loosely is how the previous version of this
paragraph went wrong. Step 6 iterates **the branches Step 4a actually merged**, not Step 2a's
output; a branch Step 2a never reviewed gets no verdict, so Step 4a never merges it, so Step 6
never sees it. **Step 1a still classifies one**, so the first link is live and the classification
is where a leak surfaces.

**An earlier draft of this paragraph stated the whole chain as a live consequence**, which was true
when it was written and has been false since that build — it named the two steps that had just been
taught to exclude the branch as the steps that would review it. It is recorded here in the
corrected form rather than deleted, because the hazard is what the exclusions are FOR, and a reader
deciding whether to relax one needs to know what it is holding back.

**The consequence the exclusions do not touch is the cross-session one**, and it is the reason the
rule is a hard one rather than a tidy-up: a *concurrent* `/review-close` can reach
`git worktree remove` on a checkout an agent is still running in. No branch-enumeration exclusion
reaches that, because the collision is over the worktree rather than over the branch.

### Why the worktree assertion is a delta and not a cleanliness test

Nothing in this skill establishes that the primary worktree is clean before the agents run. Step 1a
excludes it by construction — it skips the **primary checkout**, matched by path identity — and the
only earlier primary-tree reads are both in Step 1b, one path-scoped to `review_tasks.md` and one
whole-tree but grepped down to `review_tasks_archive.md`, while Step 1c reads no working tree at
all (`for-each-ref`, `merge-base`, `diff --name-only`). So nothing before the agents run
establishes anything about the rest of the tree, and an absolute test would fire on any ordinary
uncommitted work.

**The baseline's position in the step is load-bearing too.** It is captured after Steps 1b and 1c
because both deliberately create commits, so a Step-1 reading would be stale by design.

### Why the baseline lives under a gitignored runtime directory

`sysop/runtime/` is the single runtime home, and `install.sh`'s `ensure_runtime_gitignore`
appends the entry when missing and runs unconditionally in both modes and on `--update`, so a
consumer has it. **It is not there to stop the file reporting itself** — it cannot do that in
either location, because `>` creates the file before `git status` runs, so the file appears in the
baseline *and* in the comparison and cancels out. The reason is downstream: an untracked artefact
at a tracked path shows up in the operator's own `git status` for the rest of the close, and is
reachable by a later `git add`.

### Why the fifth assertion command gets its own line

The pinned checkouts live under the ignored `sysop/runtime/pins/`, so they never appear in the
third command's `git status` delta and never reach `.claude/worktrees/` for the first. The only handle on
them is `git worktree list` — which is why they get their own line rather than riding one of the
existing four, and why a reader who expects four commands to cover five populations is wrong about
the third one in particular.

## Step 2b — verdict reuse

A consumer's one-week field report counted unmoved branches re-checked three or
four times in one afternoon when a close was relaunched, at 60 to 84 cents a gate agent, with about
94% of gate passes finding nothing. Nothing keyed a verdict to its inputs, so nothing could reuse
one. `gate_verdict.py` keys each gate's `APPROVED` to every input the review depended on:

- **The target's commit and its merge-base.** The diff basis is three-dot, so those two ends fix
  the diff. The merge-base is in the key because an unmoved tip over a moved base would review a
  different diff.
- **What the agent can be handed.** The convention gate hashes the whole of `CLAUDE.md`, the
  section names, and the convention map and its overlay (the `TOTAL` 0 arm hands the map); the
  security gate hashes the security map and its overlay, and `security_map_filter.py`, which cuts
  the agent's copy of them. The sources are hashed, not the runner's
  copy, because the paste arm has no file. They are whole files because the first build cut
  sections as `convention_size.py` measures them, and the review round reused a verdict over
  each shape that cut misses: a fenced `## ` line ending the cut early, a heading with trailing
  space, the second of two same-named sections, and a section step 0 added that the runner left
  off the command. Any edit to the file runs the gate again, which errs the same way as the step's
  text below.
- **The step's own text.** The whole `### 2b.` section of the installed `SKILL.md`, which holds both
  prompts, is hashed, so a Sysop update that changes the step changes every key. It is coarser than
  the prompt alone and errs toward running the gate.
- **The model and the effort**, read from the role's spawn line. A replay found `medium`
  was not a subset of `high` on the same targets, so a verdict from one effort is not evidence for
  another. A line with no effort (a role mapped to a model with no `efforts:` entry) runs at the
  session's effort, which no key can see, so it is never reused. The model is the alias the spawn line names
  (`sonnet`, `opus`), not the version it resolves to, so an alias moving to a new model does not
  invalidate a record by itself; that is a stated residual, not a measured one. The record keeps both. It is not yet what the filed replay instrument needs: that
  replays blocked verdicts, and only approvals are recorded, one per gate and target.

**Only `APPROVED` with `NOTES: none` is recorded.** A reused verdict spawns nobody, so it has no
notes to hand `4a-fix`, and a close that stopped before `4a-fix` has not acted on the notes it
collected. Recording an approval with notes would drop them on the relaunch. A `BLOCKED` is never
reused, on the maintainer's 2026-10-20 answer: re-running it is how a false positive gets a second look.

**`record` takes the key the lookup printed before the spawn, and refuses when the key is
different now.** The first build recomputed the key at record time, and the round recorded a
verdict against a security-map overlay rule appended while the agent ran: the next close reused
it under a rule its agent never had. Promotions write the overlays, and several sessions can
share one clone, so an input can move mid-close. Round 2 found the same gap one step earlier: the lookup
ran after step 1 had read `CLAUDE.md` and the diff, so a move between the two was covered by no
key. Both lookups now come before anything is read for the target.

**`record` refuses an echo that is not the target's commit now.** The agent's first line is its
pinned checkout's `HEAD`, the placement receipt Step 2b already requires, so a misplaced lens, or a
tip that moved after the spawn, records nothing. The entry asked whether a reused verdict satisfies
"the Tier-0 coverage ledger's placement receipt". `/review-close` has no such ledger; that one
belongs to the loop review skills. The record exists only after a receipt matched, for the same
commit the key names.

**Where it does not help.** The `unpushed-main` group's commit moves whenever Step 1b commits to the
default branch, so it rarely reuses. `--prepare`/`--resume` keep their own per-run state: a resume
whose branch re-ran nothing keeps its recorded verdict and never looks up. `close_run.py` prints
`RERUN 2b` when `CLAUDE.md` or a map changed, which are hashed inputs, so the gate whose inputs
changed misses on every target; the other gate can still reuse. A dry run records
too: 2b already writes runtime files then, and its verdict is a real one.

## Step 2b — the security copy

The field report that filed it measured the security copy at 75 KB, read by
every security agent on every target, while the map already routes rules by glob. The filing named
both Step 2b copies; the convention copy holds `CLAUDE.md` sections only (step 1's set), which have
no globs, so the maintainer left it whole on 2026-10-20 and the entry narrowed to the security copy. GDP's
runtime copy of 2026-10-19, measured by cutting at every `## ` line: 70
sections, 44 with no placeholder in the heading (99,540 characters), 25 all-placeholder (18,617),
1 mixed. Three of the 44 name no glob in the heading at all (`Config & Infrastructure`, 32,467
characters then, and two `Coverage ledger` sections). The map has moved since (lens B: 71 sections
at the phase date).

**The overlay is read once.** `install.sh` appends `.claude/security_map.project.md` to the
shipped `.claude/security_map.md`, so reading both files read every overlay section
twice on an installed consumer, in the copy, the counts and the arm (the round, lens B: `2 of 18`
for one overlay section). The script reads the overlay live and drops it from the end of the
shipped map when it is there verbatim. An overlay edited since the last update is not, and is read
twice, which repeats a rule and loses none.

**What is dropped, on the maintainer's 2026-10-20 answers.** Only a section whose heading names globs, every
one concrete, none matching a path in the diff basis. A placeholder glob (`<api module>`) cannot
rule a path out, so a section carrying one is kept, mixed sections included. The filing's design
question, a cross-cutting rule whose glob misses a diff that reaches its subject, was answered
without a map marker: the agent is told which headings were left out and where the whole map is.

**The gate reads leniently and the cut reads strictly**. The first
build read globs only from `##` headings, and GDP's overlay routes 53 concrete globs in 17 `###`
headings under `## Config & Infrastructure`, `migrations/*.sql` among them (its shipped map
repeats them only because `install.sh` appended the overlay): a migration-only branch printed
`SKIP`, where the by-hand gate it replaced ("some glob in either matches") would have spawned. And
a heading the strict parse missed (a tab, an ASCII hyphen, a BOM) was kept in the copy but reached
no gate, so its rule was never read either. So every backticked token in every heading, at any
level, counts toward the gate; a `##` section is dropped only when its own heading parses as
`## <globs> — <Name>`, all concrete, and no heading in it carries a placeholder or matches.

**Every parse failure keeps.** A heading the strict parse cannot read is kept, and so are
`Config & Infrastructure` and its kind. A `#` or `##` heading, ATX or setext, indented or not, ends
the section above it, because otherwise its text rides with a dropped section; a deeper heading
belongs to the section above it. Lines in fences and HTML comments are not headings: a commented-out
`## ` cut a matched section short in the first build (lens A). A fence or comment that never closes
keeps its whole map, and its gate reads every heading-shaped line in it, since a skip would read as
a searched absence. Fences follow `claim_record.py`'s closer rule: an opener may carry
an info string and a closer may not, so a `` ```json `` line inside a plain fence does not end it;
and a backtick run followed by another backtick on its line is an inline span, not a fence
(CommonMark). `security_partition.py`'s section parser was not reused for the cut: it splits only
at `## <globs> — <Name>` headings, so a no-glob heading would ride with the section above it and be
dropped with it. Its heading pattern is reused for the strict parse, and its source is in the key.

**The match is git's, against the diff.** `git diff --quiet --no-renames <base> <tip> --
':(top,glob)<glob>'`: `**` means what the map means by it (a direct child of `api/**/*.py` matches),
`*` does not cross a directory, a deleted file reaches its section, and a renamed file reaches the
section of either name: git limits by the pathspec before it detects renames, so the old name is a
deletion either way, and `--no-renames` only says so. `top` reads from the top level, since a plain
`:(glob)` resolves against the current directory and a run from a subdirectory skipped (lens A). Braces are expanded first, and a leading `/` or `./` is dropped: git has no brace
expansion, so `*.{ts,tsx}` matched nothing and dropped its rule, and a leading `/` is an invalid
path. A glob git still cannot read counts as a match and is printed as `UNMATCHABLE:`, because a
prose token in a deep heading must neither stop every close nor read as an absence. The tracked-file resolver `/security-audit` uses answers a different
question: the primary checkout does not carry the branch's new files.

**One matcher decides the gate and the cut**, on the maintainer's 2026-10-20 answer, so the two cannot
disagree about what matched. The gate used to be a judgement the runner made by reading both maps.
An exit 2 is the target's `BLOCKED` verdict rather than a skip: an uncomputed security gate is not
a searched absence, and a skip would read as a clean one. It is a verdict, collected at item 4, so
the other targets still run, a `--prepare` stops only its branch, and Step 4's existing stop and
waiver apply; the first build said "stop as a `BLOCKED` does", which left open whether the close
stopped there or at item 4 (the round, lens B).

**The arm measures the cut copy**. Measured after the round: on GDP's maps the
copies were 63,177 characters (a branch touching `requirements.txt`) to 64,366 (one touching
`<api module>/routes/`) of a 121,485-character full copy, about half, and on a
stock `--packs python` install 10,779 of 12,757, so neither reaches the paste; the inline arm is
for a map that is small once cut. `2b-security.md` is still written whole, at a fixed name, because the agent is handed
its path for the left-out sections and `close_run.py` keeps its copy for a resume. Each target's
copy is its own file, named by a hash of the target as `gate_verdict.py` names its records, and the
script prints a path only after writing it, so no target is handed another run's copy.

## Step 2d — provenance

Editor-addressed history for `### 2d. Test-Decision Verification`. Nothing here binds the agent
running the skill; it is why a rule in that step is shaped the way it is, so that an editor
changing one knows what the shape was bought with. Authored, not copied — the runner keeps the
rule, this keeps the argument.

### What this gate replaced, and why reading the right revision is the whole of it

The test-decision convention arrived early. For a long stretch afterwards a second thing
claimed to enforce it and did not: `validate_tasks.py` carried a warn-only check on the
same fact, then numbered Invariant 13, and it read the body **off the working tree** while the record lives on the branch. So
it warned on every claimed task on every run and told the reader nothing — a check whose output
is constant carries no information, whatever its subject. A later build retired it and left this step
as the only enforcement.

That is why the runner's paragraph insists on the revision rather than the file. The failure it
guards is not "nobody checks"; it is "something checks the wrong copy and reports confidently".

### Why the premise sentence stands, and why the population was not narrowed instead

The scope note in the runner says the gate reads the record for every task the branch claims,
whatever produced it. The obvious alternative — narrow the gate to tasks that were *owed* a
record — was considered and refused, and the refusal is the reason the fourth disposition exists.
Narrowing stops the gate asking about tasks that genuinely should have carried a record, which is
the gate going quiet rather than getting honest. `Waive` had meant two different things and the
Step 8 tally conflated them: the case that should be free was priced like the case that should be
expensive. Separating the dispositions fixes that without giving up reach.

`/auto-build` belonged on the non-writing list until an earlier build and was its worst member. It claims
through `claim_task.sh --lock`, so the ownership probe answers `OWED` and withholds the fourth
disposition, leaving a human waive-or-hold on *every* autonomous branch. It now writes the record
at its Step 7c sequence, so `OWED` is the true answer for it rather than a trap.

**Do not re-derive the non-writing list by counting mentions of the heading.** Several skills
reference it without writing it, and an earlier version of that sentence counted a reference as a
write. The instruction survives in the runner; this is why it is there.

### What the `## Also fixed` reader was measured against

**Two sections in one body is not hypothetical.** `/claim-task`'s option-C writer was executed
against a body carrying `## Also fixed` *and* `## Also fixed (PR 1)` and re-emitted both — contents
preserved, both correctly placed, exit zero. A two-section body therefore reaches this gate looking
exactly as its author left it, and the reader that loses the second section is this one.

**The three heading shapes were measured, not assumed.** An ATX heading indented by up to three
spaces is still a heading; a setext heading underlined by `===` or `---` is one too. A terminator
model anchored to a column-0 `#` sees neither, and both failures were reproduced.

**The damaging direction is the undercount.** `## Also fixed` lines per branch is how fixes per
close are counted, the number the fix-by-default rule is judged on beside net open work per close,
so too few lines reads as the rule fixing less than it does, or as a branch sitting comfortably
inside a reviewable size it may already have left. That asymmetry is why the runner is told to search rather
than match, and to keep going past the first hit.

**Why the fence rule applies to this arm at all.** The `## Plan` section holds a reviewed plan
*verbatim in a fence* (`tasks/schema.md` § Plan), and a plan that discusses this very rule will
quote the `## Also fixed` heading. That is the concrete route by which a fence-blind reader finds a
heading that is a quotation — the *when it applies* half of the rule, which the runner's own
sentence no longer carries.

**And the asymmetry with item 1 is real, recorded here because it is recorded nowhere else.**
Step 1's `test\s+decision` heading search carries **no** fence caveat, while this arm does. An
earlier draft of this arm said item 1 did carry one; it does not. The caveat is therefore stated
locally rather than by reference to item 1, and an editor tempted to factor the two together
should know they genuinely differ rather than assume a duplication.

**The fence rule is stated in the runner in full, and that was a correction.** An earlier draft
said *track fences the way `/claim-task`'s Step 8 verifier does*. That was unsafe when written —
that walker carried no info-string check, so following it reproduced the very defect the rule
prevents — and it stayed wrong as an instruction even after the entry closed, because a rule held
only by pointing at another skill's code moves when that code does. All of `/claim-task`'s walkers
now delegate the closer decision to one `fence_closes` predicate per block, defined once per
heredoc since nothing is shared across them, and cited at two lines that cannot be swapped for one
another: the writer's clause explaining why its own openers carry info strings, and the clause in
the verifier itself. `fence_mark` still reports only that a line **is** a marker, which is the
distinction that made the defect possible.

### Why the info-string clause is load-bearing

The reachable window is narrower than it first looks, and worth knowing. A *balanced* nesting
inverts the model twice and cancels, so only a heading sitting **between the info-string line and
its matching closer** is exposed. Verified by execution in both positions. A live consumer body
carries the nesting — one of 911 bodies scanned — so the window is reachable on real input rather
than only in principle.

### Why the tally counts list items rather than physical lines

`tasks/schema.md` says *one line per fix*, and the live corpus wraps entries across three and four
physical lines, so counting physical lines over-reports by about 2× on real input. The marker set
is deliberately not restricted to `-`: a section written with `*` bullets carries real entries, and
a reader that only knows `-` tallies it as **zero** — the undercount direction the whole arm exists
to close.

The empty shape needed its own reading. In the live corpus a section recording no entries is an
explicit `_(none)_` marker *followed by a sentence or two saying why*, so the rule is not that the
marker must be the section's whole content; it is the absence of list items that makes the count
zero. Counting the explanatory prose would push the same number the other way.

**The two halves fail in opposite directions and corrupt the same ratio.** A first-match line count
understates the numerator; counting a two-section body as two branches inflates the denominator;
and the number being judged is lines *per branch*. That is also why the arm gets its own report
line: one line per gate is this step's own convention, and it is load-bearing twice here — a close
where no branch carried the section otherwise reads identically to a close where nobody looked, and
this count has to reach the artifact a human reads.

### Why the sub-step `2‑also` is numbered out of the list

It is numbered out of the list on purpose. This skill already ships a
`### 2b. Prevention Convention Check` as a sibling of `### 2d`, so a sub-step called *2b* would
name two different things at once.

**Its twin `2‑pre` states the same reason and still states it in the runner.** That block ends
with a colon introducing the command fence below it, so the pointer line this section's own
convention requires would have landed between the colon and its referent; the split was declined
on prose grounds rather than taken. So the rationale stands in two places, and this section covers
one of them. An editor changing the wording here must change `2‑pre`'s copy too.

### Why the `2‑also` arm judges against today's rule

Until fix-by-default arrived the arm judged a section against the bound in force when its branch was
claimed. That became unexecutable when fix-by-default retired the tier: no shipped runner
text states the old bound any more, so a runner told to apply it could not. It is also no
longer needed. Every earlier bound was a superset of today's never-list plus a size limit, so
a section written under one never fails today's check. An earlier draft of the arm had
granted a carve-out on the ground that the heading *predated any rule*. That was false: every
section that existed then was authored under a consumer-side copy of the same tier, bound and
never-list included.

## Step 3b — provenance

Editor-addressed history for `## Step 3b: Prepare Worktrees for Merge`. Nothing here binds the
agent running the skill; it is why a rule in that step is shaped the way it is, so that an editor
changing one knows what the shape was bought with. Authored, not copied — the runner keeps the
rule, this keeps the argument.

### Why `src_dir` is not in the loudness disjunction

Step 3b refuses a wrong or unsubstituted worktree path outright, and for a measured reason: the
retired copy form exited 1 on a bad path, while a bare glob over a missing directory yields
nothing and exits 0 with a success-shaped report — after which the step removes the worktree and
the untracked documents are gone. That rule stays in the runner.

**An absent source directory was once refused by the same test, and that was wrong.** It was
reported four times in eight days against a suite that stayed green. An absent pending-docs
directory is the *ordinary* state of three perfectly good branches: one whose document was
authored on the main checkout, which `/document-work` supports explicitly; a hand-cut branch that
never ran `/document-work` at all; and a prior run that collected and then died before the
worktree was removed. In every one of those the directory's absence **proves there is nothing to
lose**, which is exactly the condition under which proceeding is safe. The check was sending a
compliant operator to fix an invocation that was already correct — and the bypass that teaches is
the untracked-document data loss the step exists to prevent.

**What the check was reaching for is still refused, by a test that discriminates.** The real
hazard is a directory that exists but is the wrong one. A checkout carries `.git`; a directory
that merely exists does not. That question is asked only on the arm where it discriminates —
where the source directory is present, asking it buys nothing this arm does not already get —
a doc claiming a *different* branch is refused separately, further down — so asking here would have
widened the refusal across the whole population and discriminated nothing. (The block this replaces
said the present directory *"demonstrably holds this branch's pending documents"*, which is looser
than the skill: `SKILL.md` checks `branch_of(src) != branch` and refuses a foreign doc in its own
arm. The inaccuracy was inherited, not introduced — and relocating it into a file with almost no
guard density is exactly how an inherited inaccuracy stops being caught, so it is corrected here.)

The general shape the record already carried: **a guard that fires on the ordinary case teaches
operators to route around it**, and the routing is what costs you the thing the guard protects —
which is the reason given for the reversal itself, not a new rule. (A first draft closed with a
further sentence prescribing where to site such a question. It was a design rule that had existed
nowhere before, authored into a file § 4.1 measures as covered by nothing, which is the one thing a
provenance section must not do.)

### Why staleness is asked at Step 3b rather than at Step 4c

Step 3b is the last point in the close where the branch is still in the shape its document was
written against. Everything after it rewrites history — Step 4a rebases its local-only arm, and
the PR squash follows — and each of those orphans the commit the document recorded. Step 4c, where
the routing that writes the durable record actually happens, therefore cannot ask the question at
all; the ancestry property that makes that true is the one Step 1b's own blockquote already
documents. So it is asked at collect time and answered by refusing to collect, rather than held
open to a step that could not settle it.

### Why the recorded tip is validated before it reaches git

`branch_tip:` is free-form frontmatter — whatever the document's author wrote ends up in it. An
unvalidated value beginning with a hyphen reaches `git rev-list` as an option rather than as a
revision, which is why the field is matched against an object-name pattern before it is used at
all. The disposition that follows is deliberate rather than incidental: a value that is not an
object name is not a measurement, so it takes the same arm as a git that would not answer, and is
reported as unknown rather than as stale. Keeping those two together matters because the stale arm
refuses the close, and a malformed field is not evidence that a document is out of date.

### Why an absent source directory is dispositioned where it is

The absence is reported after the branch of each document is known, because two legitimate readings
have to be told apart: main already holds this branch's document, or no pending document exists for
this branch anywhere. Both permit the worktree removal that follows; only the second is something
an operator may want to act on before the branch merges, and one silent path would collapse them
into a single outcome that says nothing. **Since the claimed-branch rule arrived the second reading permits it only when no
task lock names the branch** — see the next section.

### Why a claimed branch with no document is refused

An earlier build ruled "no document for this branch anywhere" a legitimate reading and let it exit clean,
with a hand-cut branch that never ran `/document-work` as the case in mind. That is right for a
hand-cut branch and wrong for a claimed one. Step 4c's round-trip — the status flip, the body move
into `archive/`, the lock removal — is driven only by the ids a pending document names, so a claimed
branch that merges with no document leaves its tasks `in_progress`, its locks held and its bodies
under `open/`. Step 6 then deletes the branch, and Step 8's report is true and incomplete. A
consumer caught three such branches only by listing the directory by hand.

**The discriminator is a task lock naming the branch, not the directory being absent.** Keying the
refusal to the absent directory would have missed the existing-but-empty one, which that build
deliberately dispositions the same way and which strands tasks the same way. The lock is what
Step 4c would have removed, so it names exactly what would be stranded; `/claim-task` and
`/auto-build` both claim with `--lock`, and `tasks/schema.md` requires a lock for an `in_progress`
task. It is also the linkage Step 3c already uses as its second source, so this is not a new kind
of evidence. Two cases are excluded on purpose: a review batch's `BATCH-<N>.lock`, whose batch Step
4b closes from `review_tasks.md` with no document involved, and no lock at all — a hand-cut branch
strands nothing, so it still passes, on the maintainer's 2026-09-23 answer to the question the filing left open.

**Refusing, not asking.** The remedy is the one exit 6 already sends the operator to: run
`/document-work` on the branch, which needs the workspace this exit declines to remove.

**A claimed branch that merges without closing its task is not always a mistake, and the remedy
covers that case too.** A consumer's live lock showed one on purpose: the branch shipped a corrected
spec, and the task stayed `in_progress` because the release it waits for had not happened. Before
exit 8 that merged through this exact arm with no document. Neither remedy as first written fitted
it — `/document-work` names the task, and Step 4c would then flip it done, while `--release` reopens
it and drops the lock the consumer was holding deliberately. `/document-work` already allows
`roadmap_ids: []`, and a document with an empty list records the merge and closes nothing, so the
row and the refusal name that route. The refusal therefore costs a deliberate partial merge one
`/document-work` run, and in exchange the merge is written down. A SKIP keeps
the rest of a multi-branch close moving, as exits 3, 6 and 7 do, and adds no question to a skill
whose stop surface the unattended-close entry counts.

**A claimed id that a document leaves out is reported, not refused.** A branch that *has* a
document which omits one of its claimed ids strands that id the same way, but omitting an id is also
how a document says a branch delivered only part of a claim (above), so a refusal cannot tell the
mistake from the intent. The collect therefore prints `PENDING-DOC OPEN CLAIM:` for each such id,
before the merge, and Step 8 carries it only for a branch that then merged: the line is printed
before Step 4a, which can still skip the branch. What the operator learns there is the end state the partial
route really produces: the task stays `in_progress`, its lock stays held, and Step 6 deletes the
branch that lock names, because Step 6 keeps only branches whose document is still waiting. Whether
any of this should refuse is an open question.

**How the lock is read, and why.** Column-0 lines only and the FIRST `branch:` wins, because a
lock's free-text `notes:` tail can carry a column-0 `branch:` line; that is the rule Step 2e and
`claim_task.sh`'s own `awk` apply. A lock that is not a regular file is skipped, because
`read_text` on a FIFO blocks forever. Step 2e lacked that guard until this phase's round found it.
**The lock is stat'ed explicitly rather than through `Path.is_file()`.** Below Python 3.13 that
method raises `PermissionError` on a lock it cannot stat, which killed every close at exit 1 on the
3.9 floor. From 3.13 on it returns `False`, which hid the claim silently. Neither is acceptable in a
check whose job is to notice a claim.

**What it does not cover, stated rather than implied.** A lock that cannot be stat'ed or read is
skipped, and named on a `PENDING-DOC CLAIMS UNREADABLE:` line. That fails open to the earlier
behaviour, rather than halting every close on one damaged lock, and it says so. A lock that is not a
regular file is skipped silently, since it names nothing. A locks directory that cannot be listed is not silent — `Path.glob` returns
an empty list on a permission error, which would read as "no claims" — so it prints `PENDING-DOC
CLAIMS UNREADABLE:` and the close continues. Only a review batch's own `BATCH-<N>.lock` is excluded:
`claim_task.sh` accepts a task id such as `BATCH-IMPORT`, and a prefix test would have exempted it. The shapes that never run
the collect (no workspace, or the main checkout, which is every `--branch` claim) get both tests,
the exit-8 refusal and the open-claim report, as a runner instruction rather than code.

**The equivalence with an existing but empty source directory is stated in the runner rather than
here, and deliberately.** It is a constraint on what the code may do rather than an argument about
why it does it — an empty directory reaches the first stage with an empty document list, collects
nothing and exits clean, and the two states must not diverge. Splitting the two apart has been
measured once: the absent directory exited on the refusing arm while an empty one exited clean,
over the identical stale document. That is why the sentence stays where a reader of the runner
meets it.

### Why naming the main checkout as the worktree path is refused rather than handled

A document that claims the branch being processed clears the first stage when the "copy" is main's
own file: the branch matches, so no collision fires, and the copy then raises a same-file error.
Measured rather than reasoned. A document claiming some *other* branch is still refused earlier,
which is why the damage needs a document for the branch actually being closed.

**The refusal exists because the previous disposition was destructive.** That failure used to land
on an exit whose documented remedy was to run the rollback — and the rollback removes, by
provenance, every document in main claiming this branch. So an operand error destroyed exactly the
records the step exists to protect, through the skill's own prescribed recovery rather than in
spite of it.

**It is belt to the later split's braces, not redundant with it.** The same-file failure always
happens on the first copy, so with the later exit in place it would now land there instead —
measured with this refusal removed, and non-destructive. The later exit fixes the disposition; this
one refuses the operand, and the two answer different questions.

**The shipped path never produces this operand.** Step 0 maps the primary checkout to its own shape
with an empty workspace, and step 1 then skips the heredoc entirely, so the operand is reached only
by a hand-substituted path — which is the class that exit is for.

**The bound, stated because an earlier draft overstated it.** That draft claimed the check held
"however the operator got there", which is wider than what it does. The live directory is resolved
relative to the working directory, so the comparison is against the pending documents of wherever
the step is run. Run from a subdirectory of main while naming the primary checkout, the two paths
differ, the guard does not fire, and the step builds a spurious pending-docs directory under the
working directory — measured, exiting clean with no data lost, on an off-contract working
directory.

### Why the copy stage undoes itself instead of reporting and handing over

The first stage owns the principle it states in the runner: nothing is written until every document
has been checked, so there is no partial state to undo. The copy stage cannot have that property,
because a write either works or it does not — so it gets the same guarantee from the other side.

**What it replaced was destructive.** The earlier remedy reported an exit and told the operator to
run the rollback, and the rollback deletes by provenance: every document in main claiming this
branch, which is not the same set as the documents this run copied. Measured on a worktree holding
three documents, with main holding a prior run's copies of the first and third and the failure
falling on the second: the prescribed rollback removed both of main's, while the collect's own
"rollback required" line — all the operator had to go on — named only the first. The third was a
record the run never touched. That is the neighbouring operand defect one exit over, a documented
recovery destroying what the step exists to protect.

**An aliased document needed no separate arm.** A symlink or hardlink into main's own pending-docs
is invisible to the directory-level comparison, because same-file failure is about file identity
rather than directory identity. It now lands here like any other failure, and the restore puts
main's original back.

### What the conditional unlink was measured against

Three numbers sit behind the rules the runner keeps. The ordinary route leaves two copies and
removes one; the route where the source directory is absent leaves one and would remove it,
which is the whole reason the unlink is conditional rather than unconditional.

**The aliasing case was found outside a mutation frame, by a reviewer rather than by the author.**
A worktree entry that is a symlink pointing at main's own copy answers true to a regular-file test,
because that test follows links. The code then unlinks the file the link points to and the link
dangles: the run reports a successful rollback and exits clean, with zero readable copies left.
The half that copies had already guarded that shape — same-file failure is about file identity —
and the half that deletes had not.

**Hardlinks are deliberately not treated like symlinks.** A hardlink is a genuine surviving copy:
unlinking one link leaves the other readable, measured. A same-file comparison would hold it too,
which is safe but raises a false alarm on the one aliasing shape that is fine. Comparing resolved
paths separates the two, because a symlink resolves onto the destination and a hardlink does not.

### Why the population is measured on both routes

The first cut of this rule measured main's documents only on the arm where the source directory is
absent, which split two states the step explicitly forbids splitting. Measured on the fixtures that
found it: the absent directory exited on the refusing arm and an empty one exited clean, over the
identical stale document.

**The documented fix made it worse, which is the part worth keeping.** The refusing arm's own
remedy is to re-run the documentation step — and that step creates the pending-docs directory
unconditionally. So applying the remedy moved the close onto the arm that did not look, and the
gate turned itself off. Both halves were found by a review round rather than in use.

**The foreign-document guard was lost once and recovered by a shipped test.** Hoisting the
staleness read out of the loop dropped the skip that runs before it, which is why the runner states
the ordering rather than leaving it to the loop's shape.

### Why the workspace shape is re-tested here even though step 0 resolves it

An earlier draft of this comment claimed step 0 enforces that a workspace is a checkout. It does
not, and the distinction is the reason the test exists. The discovered arm is git-backed, because
it reads the head branch; the recorded arm is not — it accepts the lock's workspace on a
directory test alone. So a stale or hand-edited lock naming a plain directory resolves as recorded
and reaches this heredoc, and the refusal names that reason rather than reusing the generic
invocation message. Telling an operator to fix an invocation they never typed is the mis-blame this
arm was reshaped to remove.

**A filing about this arm was wrong, and the oracle it wanted overturned stands.** The filing held
that the fix must overturn the test pinning a wrong-but-existing worktree path. That test's fixture
is two bare directories, which is not observationally identical to the legitimate state after all:
the legitimate state carries a git entry, and neither the old guard nor the old test was reading
the one fact that separates them. What changed is that the test now pins a discrimination rather
than a conflation.

### Why the workspace search has a second pass at all

The prefix a claiming session used is read from that session's environment and recorded nowhere
except a lock the claim may not have written. Without the second pass, a consumer who exports
*that prefix* at claim time and not at close time gets no workspace — the silent incompletion this
step exists to remove.

**The relocated-root variable is the same kind of variable and is NOT cured by the second pass**,
which is the distinction the runner states and an earlier draft of this paragraph collapsed. Both
passes glob siblings of the repository, and a relocated root names a parent elsewhere, so no pass
reaches it. Its narrower reach is why the unresolvable combination is a relocated *clone* claimed
without a lock rather than every relocated workspace.

**Why the residue is only the clone case.** A linked worktree appears in the porcelain listing this
step is handed, wherever it sits on disk; a clone does not, because a clone is its own repository
rather than a worktree git tracks. That is what narrows the unresolvable combination to a relocated
clone claimed without a lock, rather than leaving it open for every relocated workspace.

### Why the workspace scan is a heredoc rather than a shell loop

An earlier draft used two bash `for` loops. Those are unauthorizable: `for` and `done` are not
documented command separators, so no permission rule binds them, and the same reasoning is why this
step's rollback became a heredoc too. Passing the worktree listing in as an argument is what lets
the block run no subprocess of its own, which is the property that keeps the whole thing matching
as a single simple command.

### What ordering an unverified arm first actually cost

The lock is the claim's own statement, and a claim can be stale. A lock left behind by a workspace
that had since been deleted or moved shadowed the live one, so the discovering arm never ran, and
the collect aborted on a path that no longer exists — with nothing in the disposition naming the
stale lock as the cause. The rule the runner keeps is the general one; this is the incident that
bought it.

### What deciding first replaced

An earlier draft copied as it went and undid the copies on a collision. Its undo deleted files main
already held, because an overwritten document sat in the same "collected" list as a newly created
one. Deciding before writing makes that class impossible rather than handled, which is why the
property is stated in the runner as a guarantee rather than as an implementation note.

### Why every frontmatter parse catches `Exception`

`yaml.safe_load` raises more than `yaml.YAMLError`. An impossible date (`date: 2026-09-31`)
raises `ValueError`, `!!bool abc` raises `KeyError`, `!!timestamp abc` raises `AttributeError`,
and a deeply nested flow sequence raises `RecursionError`. Its constructors call `int()`,
`float()`, `datetime()` and dict lookups, so the set is open-ended, and a tuple of the ones
measured today would go stale. The handlers here grew one member at a time: `RecursionError`
was added after a neighbour doc exited 1 with empty stdout on the half that deletes, and an
impossible date then did the same in the collect and the rollback. `date:` is typed by an agent
in every doc template, so one slipped character reached it. Each handler now takes its
existing unreadable-doc arm for any exception the parse raises. `tests/test_yaml_parse_failures.py`
fails on a shipped handler that catches `YAMLError` without the rest.

**Why the collect names the reason, and the templates quote `branch:`.** A branch
that YAML reads as a non-string (`1234` is an int, `2026-09-01` a date, `true` a bool) made
`branch_of` answer None, and the collect refused its own doc as a collision that "claims
None". Coercing in the reader is lossy (`0123` reads as 83, `true` as `True`). Step 3c's own
reader already coerces with `str()`, so on a non-string value it and this step disagree; only a
quoted value makes every reader agree, so the writers quote it, and `WHY` carries the reason
into the collision and exit-8 lines. The reason is for the report only:
nothing decides on it.

### Why Step 3b step 0b preserves every only-copy ignored file

An unforced `git worktree remove` refuses on modified or untracked files and deletes ignored
ones without a word (`tests/test_ignored_refs.py` measures it). The maintainer's ruling of 2026-09-30 was
to refuse the remove for a worktree holding an ignored file the branch reads. The first build
did that through the reference matcher, and both review rounds then found references it missed
while the remove deleted the only copy: a directory beside the file, a root-relative
`Path("tests/fixtures")`, a scoped alias, a template literal. A matcher over every consumer's
code is never complete, so on the maintainer's answer of 2026-10-02 the guard stopped depending on it:
step 0b copies **every** ignored file the main checkout has no identical copy of, referenced or
not, to `sysop/runtime/preserved/<branch>/`, then the remove goes ahead. Only a copy that cannot
be made, or a directory it holds (below), SKIPs the branch.

**What it copies, and what it does not.** Only files a file pattern ignores, as the check reads;
a directory ignored as a whole is not copied. Until internal tracker #939 that was silent: the
copy printed `0 preserved` at exit 0 and the remove deleted a consumer's eval-run outputs, which
existed only in the worktree. On the maintainer's answer of 2026-10-31 it lists and holds rather
than copies: a whole-ignored directory holding a file neither the main checkout nor an earlier
preserve has prints `HELD:` and exits 4, so the branch is SKIPped with its worktree intact. A
directory named like a cache or build output (`_CACHE_DIRS` in the script, and `*.egg-info`) is
never walked: a worktree's build never matches main's byte for byte, so a branch that built would
otherwise be held at every close, and build output joined the list on the maintainer's answer of
the same day. Symlinks are skipped, because removing one removes the link. A file the main
checkout holds byte for byte is skipped. Gate outputs (a `tsbuildinfo`, a log) are copied too,
and Step 8 lists them; that is the price of not guessing.

**The destination must be gitignored in the main checkout,** or every preserved file would show
up there as untracked work; the script checks with `git check-ignore` there and refuses
otherwise. A re-run (a branch SKIPped at exit 6 and closed again) skips a file already preserved
at the destination or in any earlier timestamped run, and puts a differing one, or one whose path
is blocked by a file or a link, under a fresh UTC timestamp, so nothing preserved is overwritten.
A main-checkout file that is a link, or resolves into the worktree, is not a copy: one that did
was skipped and then deleted with the worktree.

**Before the collect, not before the remove.** A failure after item 1 would leave a collected
doc for a branch that will not merge, and the rollback exists for that case with all of its own
failure routes. Failing first leaves nothing to undo.

---

## Step 3c — provenance

Editor-addressed history for `## Step 3c: Manual Smoke Gate`. Nothing here binds the runner.

### Why a task body is read at the branch tip

Step 3c runs before any merge, so `HEAD` is still the default branch, and source 3 used to read the
task body out of the working tree. A consumer's branch rewrote its own stale smoke procedure. The
gate showed the operator the version being retired: it named a schedule row whose article was
already `published`, and pinned a release that had not happened. The only thing that caught it was
the branch's own pending doc, read in place from the worktree, disagreeing with the index signal. A
branch that fixed a procedure and did not narrate the fix would have had nothing to contradict it.

Step 2d had fixed the same defect several hundred lines earlier ("Read the record at the branch tip — not out of
the working tree"). The two failures point in different directions. Step 2d's stale read was loud,
a false `missing` on every run. Step 3c's is a plausible-looking procedure, so nothing looked
wrong, and that is the likely reason it was left behind. The path still comes from main's
`tasks/index.yml`, for Step 2d's reason: a claim does not move the body, and Step 4c's archive move
runs later.

**Both asks shipped, and the second must not be dropped for the first.** Reading at the tip fixes
this read. The `READ:` line fixes the class. An operator can always tell whether the text in front
of them is the text that is merging, including on the paths that cannot read the tip: no approved
branch claims the task, or the tip read failed. A failed tip read falls back to the working tree
rather than suppressing the signal. The declaration is the ask, and the label says the text may
not be what is merging.

### Why a held doc links no task, and why its own headings still signal

Step 4c 1c keeps a doc in main's `pending-docs/` for as long as its task's `user_action` is
outstanding (or, since the hold field arrived, its own `hold:` is set), deliberately, because the doc carries `roadmap_ids` into the round-trip. That can take
many closes. The gate scanned the directory without knowing about the hold, so it re-fired every
close on work that had merged earlier. Two reports reached it by different routes:

- **Reported as internal tracker #704, through source 3.** The held doc's `roadmap_ids` linked a `manual_smoke` task, so its
  body's procedure was asked again on every close. The fix is the reporter's remedy (a): a held doc
  links nothing, because its task is not merging in this close. The gate prints
  `NOT IN THIS RUN:` so the skip is never silent. A lock on an approved branch still links the task
  if the task is claimed again.
- **Reported as internal tracker #605, through source 1.** A heading in the held doc itself, `## /review-close prerequisites —
  read before merging`, matched the phrase set on every close, although its first line recorded the
  step as done. Remedy (a) does not reach this route. **The bound the reporter stated is kept:**
  narrowing the phrase set, or skipping held docs wholesale, would reopen a consumer-reported case
  where a real pre-merge operator action scored `NO_SMOKE_REQUIRED`. So the heading still signals.
  On the maintainer's answer (2026-09-24), an answer the human gives to that section is **remembered**: the
  recorder writes `(hash of the section text, decision, date)` into the doc's own frontmatter, and
  a later close reports `PREVIOUSLY ANSWERED:` instead of asking again.

**"Not merging this run" is the discriminator, and it is not 1c's predicate.** 1c holds any doc
naming a task with a truthy `user_action`, or carrying `hold:`, whatever its branch. The gate needs a narrower fact: a
doc in main's `pending-docs/` whose `branch:` is neither approved this run nor the branch HEAD is
on at Step 3c. The second clause is load-bearing. A `branch: <default branch>` doc can never be
approved, and its work lands with this close. A review round found the first cut
suppressing exactly that doc's smoke. With HEAD unresolved, nothing counts as not merging, so the
gate asks. Only a not-merging doc has its links dropped (when 1c also holds it, which it tests
with Python truthiness, as the round-trip heredoc's `if t.get('user_action')` does) or its answers
honoured. A doc whose branch is approved again is this run's doc, and is asked like any other.

**Why the answer is recorded at the close that merges the work.** Round 1 also found that the first
cut recorded answers only in held docs. The close that merges the work reads the doc in its
worktree, not held, so the answer was never written, and the first held close asked again. So
every doc-carried signal gets a `KEY:` naming its doc, the recorder writes into whichever copy was
read, and Step 3b's collect carries a workspace copy to main. The answer is honoured only while the
doc is not merging, so the merging close always asks, and the held closes and the close that finally
releases the doc report it instead. **Round 2 found the carrier choice mattered too:** a task an
approved branch re-claims is merging, and taking an earlier held doc as its carrier let that doc's
answer silence the ask. A claimed task now takes its carrier only from a merging doc.

**The limit, stated:** a held `branch: <default branch>` doc is always treated as merging, so it is
asked on every close and its recorded answers are never read. That is the safe direction. **A later
build built two discriminators and its rounds refused both, and the maintainer closed the entry by
disposition on 2026-10-06: the limit stands.** (b), a
`held_since:` stamp from 1c, dropped the held task's links even when new commits for it sat on local
`main`, so a procedure nobody had answered went unasked (round 1, lenses A and C). Adding "and
`HEAD` has nothing `origin/<default branch>` lacks" was safe but inert: `/claim-task` commits each
claim flip to local `main` and does not push it, so `HEAD` is ahead of origin on almost every close
(round 2, lenses A and C, reproduced). On the maintainer's answer Step 3c went back to not reading the stamp.
A third design would need a fact that separates this doc's landed work from commits landing now,
under both policies, that claim flips do not move.

**Why the record lives in the doc and not in a sidecar under `sysop/runtime/`.** It dies with the
doc, and it travels with it. When the human performs the step and a later close consolidates the doc, the answers go with
it, so no orphan can suppress a future doc of the same name. The rewrite changes only the
`smoke_answers:` block, and re-parses the result to prove every other key is unchanged. It refuses
rather than guess.

**Why a waiver is never recorded.** The reporter's own constraint: suppression must be per section
and per doc, "never per run, or it becomes a waiver". A remembered waiver is a waiver that no longer
asks, which is the train-the-operator-to-waive equilibrium the `user ops` exclusion exists to
prevent. Only an answer that states a fact about the procedure is kept: *it was run*, or *it cannot
be run as written*. A change to the section's text re-arms the question.

### Why "unrunnable as specified" is its own disposition

The halt rule was written for a transient failure: "halt this run … the next `/review-close`
re-runs Step 3c". A consumer's procedure named a CSV that the data-job container can never reach.
The file is gitignored, never copied into the image, and the script has no remote source. Taken
literally, the rule halts every close forever, and three approved branches with every gate green
would never merge. None of the three options fit. "Already ran it" was false. "Waive" records that
the human declined the gate, when the fact is that the gate cannot run as specified, and Step 8
could not tell those apart. "I'll drive" was what had failed.

So smoke failure is now two states. A transient failure halts, as before. A structural failure
becomes a fourth disposition, chosen by the maintainer on 2026-09-24 over the smaller amend-the-halt-rule
version. It records the reason, files the blocking defect as a task, and leaves continuing or
stopping to the human. Step 8 reports it as its own count, never inside `waived`. The reporter had
improvised exactly this disposition by hand.

**Why the filing waits for Step 4d when the close continues.** Step 4d's first line is where every
landing close already files, with `4a-fix`'s notes, in one commit on the merge target. A commit on
the default branch at Step 3c would land after Step 3's pre-merge pass had verified that branch's
local commits. On the stop path nothing merges, so the filing commits at once, as Step 1b's archive
rotation does, and the defect survives the halt. **The accepted cost:** that commit is a local-only
default-branch commit, so on the next close Step 4a's PR-reuse condition fails for a pushed
single-branch PR. That is the same cost a claim flip already imposes.

The entry's first draft cited a "§ Report-and-exit integrity" rule in this skill, and no such rule
exists (a queue entry records that false-citation class). What is true is that could-not-measure is a
state of its own all over this skill (`4a-post`'s timeout arm, Step 3b's staleness-unknown), and
Step 3c was where it was not applied.

### Why an undeclared task's body is read

Step 3c's prose already promised a heading is read "in the body of a task this close covers", and
the heredoc read a task body only when the index set `manual_smoke: true`. A consumer measured the
gap on one close: two of three real asks were procedures written under `## Manual smoke required`
in task bodies whose authors had not set the flag. Over that consumer's history a verifier counted
five real unprompted body-only asks against three false positives.

**The scope is the approved branch, and the missing-procedure signals stay flagged-only.** An
undeclared body is read only when an approved branch links the task, as it will merge (the merge-file
read, below). A doc on an unmerging branch, or a held doc, links no undeclared
task. The flag still does what only it can: it turns a body with no procedure heading, an
unreadable body, or no `body:` into a signal. Reading undeclared bodies for those would ask about
every task that merges.

**A flag set on the branch counts.** Step 3c read the default branch's index only, so a branch
that set `manual_smoke: true` on its own task was invisible for the same reason. The reporter's
alternative, a `/document-work` flag in the index, was inert for that reason. The branch's index is
read at its tip for the tasks that branch links, and only for those. A stale branch, forked before
the default branch cleared a flag, still declares the task: that costs one extra ask, never a
missed one.

### Why a body is read as it merges, and why a fenced `#` ends no section

**The tip is not the text that merges when the default branch changed the body after the fork.**
A review round reproduced it: an undeclared task, a branch that edits its body elsewhere, and a
`## Manual smoke required` the default branch added later. The tip lacked the heading, so the gate
printed `NO_SMOKE_REQUIRED`, while a test merge carried it. A union of the tip, working-tree and
origin bodies was refused: it re-asks a procedure the branch retired, which is the defect
an earlier build fixed. The read is the merge result.

**`git merge-file`, not `git merge-tree --write-tree`**. The entry proposed the
second, which needs git 2.38 or later and would have given Sysop a stated git floor for one read.
`merge-file -p` and `-L` date from 2007, and the git 2.35 manual already documents `--ours` and `--theirs`. **It is not identical to git's own
merge.** `merge-file` aligns with git's default diff (myers), and `ort` uses histogram. A review
round fuzzed 400 random bodies and found one that `merge-tree` called a conflict and `merge-file`
merged clean; `merge-file --diff-algorithm` would close that, but it arrived in git 2.44. Step 4a's
local-only arm also replays commits one at a time rather than merging endpoints. Both are rare,
and both differ in where a hunk lands, not in whether a heading is present on either side.

**Which targets.** Under `direct`, Step 4a merges onto local `<default branch>` and Rule B merges
`origin/<default branch>` in before the push. Under `pr`, Step 4-pre cuts the integration branch
from local `<default branch>` and then merges `origin/<default branch>` into it. So origin's text
lands under both policies whenever origin holds work the local branch lacks, **diverged included**:
local `main` normally carries unpushed claim flips, which makes diverged the common `pr` state.
The gate reads both merges and scans each, unless one branch already contains the other. It reads
local `<default branch>`, not `HEAD`, because Step 4-pre checks the default branch out first.

**A conflicted body: each side is resolved on its own** (the maintainer, 2026-10-06, "scan both sides"; the
mechanism is the round's). The first build scanned `merge-file`'s marker text. The round showed that
text is not markdown: a fence opener from one side paired with a closer after the hunk and hid the
other side's heading, and under `merge.conflictStyle=diff3` the markers carry the base, which
re-asked a procedure both sides had removed. `--ours` and `--theirs` each give one coherent side,
with no markers, whatever the consumer's conflict style. It can still re-ask a procedure the branch
retired inside a region the target also changed, which is the gate's loud direction.

**A merge that cannot be read falls back to the tip, and says so outside the signal.** That covers a
`--clone` workspace whose objects lack the target (the normal state under `--dry-run`, because Step
1-pre only dry-runs), a blob `git show` cannot read, a binary body, and no resolvable target. A
non-UTF-8 body is decoded with replacement and merged, as a pending doc is (round 2). The `READ:`
line exists only on a signal, so an undeclared task with no signal needed the `MERGE NOT READ:`
header line, or the fallback would be silent. **A body the target moved or deleted is read at the tip.**
A per-path read cannot follow Step 4c's archive move, which is a rename, and reading it as a deletion
emptied the body. **A target that left the body alone contributes nothing** when another target's merge was
read: that merge already holds the tip's changes, and the tip beside it would re-ask the older text.
A failed target still keeps the tip, because the other merge can drop a heading the failed one carries.

**A fenced `#` line ends no section; it can still start one**.
The measured defect was the cut: over 1,272 consumer `.md` files a fenced `# comment` had been
ending three real procedures early, at 30 of 97, 78 of 133 and 24 of 61 lines. Section ends are now
found on a copy whose closed fences are blanked, by `_fence_state`'s rule; a fence still
open at the end of the file fences nothing. **A misread fence there can only lengthen a section,
never hide a heading,** because starts are matched on the real text.

**Why starts are not fence-aware, though the maintainer's first answer said they should be.** Round 1 built
that: a fenced `#` neither started nor ended a section. Its lens found real CommonMark headings
the repo's fence rule hid (between indented or tab-indented look-alikes, around an HTML comment
holding a fence line, after a fence-shaped frontmatter line, after an unclosed list-item fence). A
more conservative rule then went in, and round 2's two lenses each found it hiding headings again:
a top-level fence indented 1–3 spaces with a column-0 line inside it, an HTML comment opener in the middle of
a line, and a leading `---` thematic break. Every rule short of a CommonMark parser had a shape that
hid a heading in the gate's silent direction, and the gate ships with PyYAML as its only
dependency. So the start half stays as it was before this phase: a fenced line that
matches the heading pattern signals, and costs one ask with a waive option. The one fenced match
in the consumers' trees today is in a flagged task whose body carries the real heading unfenced.
`validate_tasks.py` stays fence-blind too, which keeps its documented lockstep with the gate.

**The heading regexes take `[ \t]+` after the `#`s, not `\s+`, and allow up to 3 spaces before
them.** `\s+` let a bare `#` line reach the next line's prose and read it as a heading, and a
column-0 anchor never saw a heading indented 1–3 spaces, which CommonMark renders (round 2, lens D). That changes the `KEY:` hash of a section holding a
bare `#` line, as lengthening changes the hash of a section with a fenced `#`; a recorded answer on
either is asked once more, the loud direction.

The phrase-breadth false positives the same entry measured (`### 3. Add a smoke test reproducing
the race`) are not fence-related and are unchanged.

### Why `origin/<default branch>`'s index is read beside the working tree

Under `pr`, Step 3c read local `<default branch>`'s index while Step 4c reads the integration
branch, after Step 4-pre has merged `origin/<default branch>` into it. A consumer's local main was
seven commits behind, and one upstream commit had cleared `user_action` on two tasks. Step 3c still
read both as held. It asked the smoke for one anyway, and reported the other, a `manual_smoke`
task, as linked only by a held doc, so it was never asked. Step 4c then consolidated both.

**Running Step 3c after Step 4-pre, the reporter's remedy, is not available:** Step 3c precedes
Step 3b, which precedes Step 4. So the gate fetches and reads origin's index beside the working
tree. **Each index can only add asks.** A task is declared if it is flagged on any index read. It
is held only when it is held locally and, where origin carries it, on origin too: origin can
release a hold but never add one, and a task origin does not carry yet is judged locally. The rule
is the same under `direct`, where Step 4c reads local `<default branch>`. There, origin releasing a
hold that Step 4c keeps costs extra asks: one per declared task the released doc names, because
a doc is held on any one of its ids. An approved branch's index releases a hold the same way, since
Step 4c reads the merged index; a branch that clears another task's `user_action` was otherwise a
silent consolidation (round 1).

A failed fetch reads the last-fetched ref and says so. An unresolvable ref is reported as
`ORIGIN INDEX: not read`, and the hold falls back to the working tree, which is the earlier
behaviour. A consumer with no `origin` remote gets no line: there is no upstream index to
disagree with. An origin index that does not parse stops the gate. An earlier build settled that an
input the gate cannot use stops it, and this is that input.

### Why a FAIL verdict is its own outcome

The "I'll drive" arm classified a failed attempt only by why it did not finish: transient (halt
and re-run) or cannot be completed as written (unrunnable). A consumer's procedure ran and exited
3, its own code for a measured regression. That is neither, and the closer improvised a menu.
"Cannot be completed as written" followed by "Continue the close" would have merged a measured
FAIL recorded as `unrunnable`.

**The maintainer's ruling (2026-09-30):** a FAIL halts by default and asks once among halt, hold just that
branch, and waive with the output recorded verbatim for Step 8 and the PR. `failed-held` and
`failed-waived` are their own states in Step 8's tally. The entry stays § Medium because merging a
FAIL took a human choosing "cannot be completed" and then "continue".

**"Hold just this branch" is Step 2d's demotion, not a literal 4a-SKIP.** The ruling said
"4a-SKIP it", but Step 3c runs before Step 3b. A branch still approved at Step 3b has its worktree
removed and its pending doc collected into main, which the 4a-SKIP handling assumes has happened.
A branch held for a failed smoke wants neither. Step 2d's "Hold for fix" already demotes approved
to rejected before Step 3b, with no downstream special-casing: Steps 3b and 4 skip it, and Step 6
keeps its worktree, lock and branch. The hold reuses that.

**Why the output goes into the PR.** A waived FAIL merges known-failing work, and the PR is what a
later reader of the default branch's history finds. Under the PR-reuse shape no PR is created, so
the record is a comment on the reused PR. Editing its body would overwrite its author's text.

**Why a waived FAIL is also filed as a task.** Under `direct`, the default,
there is no PR, so round 1 found the output living only in Step 8's report. Filing it by the
unrunnable defect's route gives it a durable record under both policies, through Step 4d's
existing filing commit. A close that halts files nothing: a waive is not recorded against the
signal's key, so the next close asks it again.

**"Hold just this branch" needs a `BRANCH:` line.** A signal from a doc on no approved branch, or a
task no approved branch claims, has no branch to demote, so only halt and waive are offered.

## Step 4-pre — provenance

### Why the integration branch is cut from the local default branch, and never from `origin/<default branch>` plus a cherry-pick

Until the provenance build this step cut the integration branch from `origin/<default branch>` and then swept
the local-only `main` commits onto it with `git cherry-pick origin/<default branch>..<default branch>`.
That cherry-pick **rewrites** the commits, so neither the rollback nor the re-claim remains an
ancestor of anything a feature branch knows, and the merge-base between the integration branch and
an approved branch collapses to `origin/<default branch>`. Step 4a's three-way merge then resolves
the task index against a base that has never seen the claim flip.

**Which arm, because the scope is the thing an editor prices a change with.** This reaches Step 4a's
**published** arm (`git merge --no-ff`) and **not** its local-only arm. The local-only arm rebases,
and a rebase replays each commit's *patch* against its real parent: the branch never changed
`status:`, so there is no status hunk to replay and the collapsed merge-base is never consulted.
Measured both ways. **That build's first record claimed the population was every approved branch cut
from a rollback, and its own round measured that wrong** — which matters, because `SKILL.md` calls
the local-only arm *"the common case"*, so the defect lives on the rarer arm. Pinned by
`tests/test_step4pre_ancestry.py::test_the_local_only_arm_was_never_vulnerable`.

**What that produces.** A task rolled back `in_progress` → `open` and then re-claimed leaves the
integration side *net unchanged* against `origin/<default branch>`, while the approved branch — cut
between those two commits — carries `open`. Three-way sees one side changed and takes it. The flip
is reverted, the merge reports `CLEAN (no conflict, no warning)`, and `validate_tasks.py` stays
green because `open` is a valid status.

**What the corruption actually costs, measured — not what the filing said it costs.** The filing,
and this section's first version, said the task *"sits `open` with its lock still held, which is
exactly what `/auto-build`'s frontier treats as claimable"*. **That is refuted by the frontier
itself:** `auto-build/SKILL.md`'s `ready()` rejects `tid in locks` with the reason *"active lock in
`sysop/runtime/locks/` — already claimed"*, so a held lock is precisely what makes it *un*claimable.
The real cost is quieter and is a data-integrity one:

- **The source of truth stops being the discriminator.** The task index — which every reader
  treats as authoritative — says `open` for work that is in flight. The lock is then the only thing
  standing between that task and a second claim, and the status field it is supposed to agree with
  now disagrees.
- **No gate can see it.** `validate_tasks.py`'s Invariant 9 is one-directional — *`in_progress`
  requires a lock* — with no converse, so `open` **with** a lock is legal and the validator is
  clean over the corrupted state. That is why the upstream report measured 839 tasks and 0 errors.
- **Dropping the lock is what makes it live.** Anything that releases the lock without re-reading
  the status — `claim_task.sh --release`, a failed close, a worktree cleanup — leaves a genuinely
  claimable task whose work is already in flight or merged.
- **The close does not surface it either.** Step 4c's `done` flip is keyed on `roadmap_ids`, not on
  the current status, so a reverted task still closes as `done` and the disagreement never appears.

**Measured**, over a fixture matrix of four branch-edit shapes × two base states:

| shape (Step 4a **published** arm) | merge-base | base current | merge | `status:` after |
|---|---|---|---|---|
| `origin/<default branch>` + cherry-pick | collapsed | yes | CLEAN | `open` — **reverted, 8/8** |
| cut from the local default branch, then merge `origin/<default branch>` | preserved | yes | CLEAN | `in_progress` — **correct, 8/8** |

In all eight of the fixed rows the branch's own work survived and, where `origin/<default branch>` had advanced
mid-run, the upstream commit survived too — so the property that motivated cutting from
`origin/<default branch>` in the first place (the PR's checks run against the current base) is kept
by the `git merge origin/<default branch>` that follows, not lost.

**Two claims in the filing that the measurement corrected.** The filing stated four conditions "all
required", the third being that the branch edits the same task entry far enough from `status:` that
the hunks do not overlap. That condition is **not required and not relevant**: under the collapsed
merge-base the integration side has *no* diff for the file, so there is nothing for any hunk to
conflict with at any distance. A branch that never touches the task index at all reverts the
flip just the same (on the published arm) — so the population is every **published** approved branch
cut from a rollback. That is wider than the entry described in one direction (the branch's own edit
is irrelevant) and narrower in another (the local-only arm is immune), and neither correction was
in the filing. The filing also attributed a conflicting outcome to a three-line
task entry as an independent trap; measured, that conflict appears **only** in combination with the
identical-SHA trap below, never on the defect path.

**The fixture trap, because it cost a round its verdict.** If the cherry-picked commits land with
the same committer timestamp as the originals, git produces **byte-identical SHAs** — same tree,
same parent, same author and author date, same message — the merge-base is the rollback commit
rather than its parent, and the flip survives. A fixture fast enough to cherry-pick within the same
second therefore reproduces nothing, and reports a clean pass. An earlier adversarial round ran
exactly such a script, concluded the defect was irreproducible, and was wrong; two of the author's
own attempts died the same way. Any test or fixture in this area must force distinct committer
dates (`GIT_COMMITTER_DATE`) and assert on the merge-base, not only on the merge's exit status.

### The Step 4c containment false positive the swap removed, and what the figure actually is

Step 4c step 1b's `git rev-list --count "refs/heads/<branch>" "^HEAD"` is an ancestry test. Until the provenance build,
Step 4-pre cut the integration branch off `origin/<default branch>` and swept local-only commits
across with `git cherry-pick`, which rewrites them — so a pending doc whose frontmatter is
`branch: <default branch>`, which `/document-work` writes whenever it runs on the default branch,
scored non-zero and was classified `NOT-MERGED` on **every** `pr`-policy close, while its content
was provably in the merge target. Cutting from the local default branch makes its tip a real
ancestor, and the same doc scores `0`.

**The figure, stated the way it is actually true.** The count before is *however many local-only
default-branch commits the tree has*, not a constant: on the phase's own test fixture, which
carries two (the rollback and the re-claim), it is **2 → 0**; on a one-commit fixture it is
**1 → 0**. That build's first record published *"one local-only `main` commit: `1` before, `0`
after"* as though it were one measurement, and its round found the two fixtures disagreeing — the
shipped sentence cited the one-commit number while the in-tree test used the two-commit fixture.
The guard asserts only that the before-count is non-zero and the after-count is `0`, which is the
part that generalises.

### The permission rules the swap moved, and the one it silently removed

Retiring the cherry-pick moved this step's whole permission footprint, and the first cut
shipped the move without the rules. Three facts, none of them visible to a mechanical check:

- **`git merge --no-edit …` binds neither shipped merge rule.** The seeded set has
  `Bash(git merge --ff-only:*)` and `Bash(git merge --no-ff:*)`, and the matcher compares literal
  text from the flag onwards — the same reason `SKILL.md`'s own pre-flight already gives for why
  `--ff-only` does not authorize `--no-ff`. Under `permissions.defaultMode: "dontAsk"` the base
  merge is therefore auto-denied on every `pr` close, the integration branch silently stays at the
  local default branch, and the single property the new shape exists to keep — the PR's checks
  running against the current base — is the one that is lost. The `PermissionDenied` hook matches
  three `git` shapes, none of them a merge, so the denial arrives bare.
- **`Bash(git cherry-pick:*)` stays seeded even though the sweep is gone**, because the Step 4
  branch-guard's reflog recovery (*"cherry-pick your stranded commits onto the expected branch"*)
  is now its only caller. Do not retire it with the step that used to justify it.
- **The escape disappeared with the sweep.** `git cherry-pick --abort` rode on
  `Bash(git cherry-pick:*)`. `git merge --abort` matches neither merge rule, and concluding a
  resolved merge needs a `git commit` that matches only `Bash(git commit -m "docs: *)` — so a
  conflicted Step 4-pre was, briefly, neither concludable nor abortable.
- **Nothing mechanical catches this class.** `tests/test_permission_surface_drift.py` checks
  *declared → seeded* and never *prescribed → declared*, and
  `tests/test_prescribed_command_coverage.py`'s invocation pattern only matches
  `sysop/scripts/<name>` paths, so every `git` command in every fence is outside its population.
  Both directions were green over a step prescribing a command no rule bound. Filed rather than
  fixed here: closing it means widening a guard's population, which is its own change.

**What a reversal would cost.** Reinstating the cherry-pick restores a silent data defect whose
blast radius is the claim ledger, on a path with no detector: the merge is clean, the validator is
green, and the only visible symptom is a duplicate claim some later cycle. `tests/test_step4pre_ancestry.py`
pins the mechanism — it asserts the merge-base is preserved and the status survives, with distinct
committer dates, so the identical-SHA false negative cannot make it pass vacuously.

## Step 4a — provenance

Editor-addressed history for Step 4a, its shared-append-files section, and the recorded PR heads
the close's readers share. Nothing here binds the agent running the skill.

### Squash provenance: why each `pr` close records its PR head

Under `pr`, `/claim-task` and `batch_work.sh` commit claim flips to local `<default branch>`, and a
branch cut before the next close's squash carries them as ancestors. Once the squash lands they
are on `origin/<default branch>` as content but are ancestors of neither ref, and a squash changes
patch-ids, so `git cherry` prints `+` for them. Two upstream reports measured the two ends:
`/sitrep` counted them as commits ahead (internal tracker #769), and Step 4a's rebase replayed one into a `status:`
conflict on a task the earlier close had moved to `done` (internal tracker #780). A later build reproduced both on a
local fixture, and both legs are pinned in `tests/test_squash_provenance.py`.

**The reporters' content predicate was refused before it was built.** It dropped index-only
commits whose entries `main` carries at the same or a later `status:`. That also drops a branch's
own non-status index edits (reproduced with a `user_action` flip), "later" is undefined once a
release reopens a task, and it ignores `review_tasks.md`. The maintainer's ruling (2026-09-30) was to decide
by provenance instead. Step 4-pre cuts the integration branch from local `<default branch>`, so
the merged PR's head contains every local-only commit the close carried, the claim flips
included.

**Why a ref, and why written by `git fetch`.** A SHA written to a file goes dangling: after
`gh pr merge --delete-branch` and Step 6's reset, the integration tip is reachable from nothing,
and `git gc` prunes it, after which `git log --not <sha>` is `fatal: bad revision`. A ref under
`refs/sysop/` keeps the head and its history alive. `git fetch origin
"refs/pull/<PR>/head:refs/sysop/merged-pr-heads/<PR>"` writes exactly the PR's `headRefOid`. It
makes the object present even when the head was pushed from elsewhere, it is idempotent, and it
binds the already-seeded `Bash(git fetch origin:*)`. No new allow-rule was needed. The refs are
per clone, which is the problem's own scope: the claim flips exist only in the clone that
committed them.

**Why Step 4a picks one head, and when it refuses to.** `git rebase --onto <target> <head>
<branch>` replays `<head>..<branch>`. That is the right set only when every commit it replays
is one a plain rebase would replay too. A branch that merged `<default branch>` after the squash
also carries the squash commit, which the head lacks and the target has, so `--onto` would replay
it. The heredoc takes the head holding the most of the branch's commits and prints `not usable`
when that head is of this shape; the arm then runs as before. Round 1 changed it to skip such a
head and take a usable runner-up, and round 2 reproduced why that was worse: the stale commits the
skipped head held are then replayed, the conflict they cause reads as two actors, and nothing
reports the head that was passed over. `not usable` stops at the same conflict with a true
reason. A branch is normally cut before exactly one close, so one head
applies. A `review_tasks.md` batch header or statistics conflict on the published arm takes the
same test, because `batch_work.sh` commits its claim to `<default branch>` the same way. A merge
conflict continues with `git -c core.editor=true merge --continue`, never `rebase --continue`,
which exits 128 there (an entry closed by this phase because its new route made it reachable).

**The published arm cannot rebase** (Step 4a item 2), so the ruling's second half covers it. On a
`status:` conflict, `git diff <head>...<branch>` shows only what the branch changed after leaving
the head's history. If that does not touch the conflicted line, the branch's side is a stale flip,
and the target's side wins. A branch that moved the status itself still stops, which keeps the
two-actor STOP.

**Readers, swept by class rather than by the filing's sites.** The filing named `/sitrep`. The
same ancestry-only count sat in Step 1a's `ahead` (an unstarted claim cut before the squash read
`AHEAD` instead of `clean-merged`), Step 2a step 1's listing, and `/claim-task` option C's
empty-branch check (a false stop before a `--delete-branch` release); round 1 added `/claim-task`'s
two `FAILED` listings. Each now passes
`--not --glob='refs/sysop/merged-pr-heads/*'`, which matches nothing when no head is recorded.
`cleanup_worktrees.sh`'s `MERGED` arm was left alone: it reads a squash-merged worktree as
`ACTIVE`, which reclaims nothing, and widening it would reclaim unstarted claims, whose tips the
heads also contain.

### The closed-task check: why item 1 reads the bodies before the merge

Step 4c closes a task by moving its body to `tasks/archive/` with `git mv`. A branch that edited
the open copy then merges with no conflict: git's rename detection carries the edit into the
archived copy, and no gate reads it. A conflict-time rule cannot catch what never conflicts, so
`pr_head_check.py` compares the branch's edits against the target's tree before item 2 moves
anything. It reads from the merge base of the recorded head and the branch when the head is
usable, since `--onto` replays only what is past it; otherwise from the target's merge base.

A body the target deleted is different: git does conflict (modify/delete), and there is no
target copy to merge into, so the only answer is a 4a-SKIP. The check runs against the local
merge target. Under `direct`, `_shared/main-push-guard.md` Rule B step 3 merges a newer
`origin/<default branch>` after Step 4a, and an archive move can arrive that way, so the same
check runs there first (`git_check.py closed-tasks`). By then the branches are merged, so it
cannot skip one: it stops the push, or a person lets the edit land.

Where a body went is read by its file name before git's rename pairing, because a close that
also edits the body, beside a near-copy of it filed as a new task, made `-M` pair the open body
with the new one, and the check read no close. A body the branch *adds* that the target closed
since the fork is the same race from the other side: a branch replayed after a squash of it
landed and a close archived the task puts the stale open copy back beside the closed one, again
with no conflict. That line has no merge-anyway arm, because the merge would only put the stale
copy back; a body whose archive copy predates the fork is a reopen and is not named. On the
published arm with a usable head the merge works from the fork point rather than the range the
check reads, so a re-add there is not caught; that is the arm's behaviour on any file.

### A landed branch stays approved

The landed-branch entry was filed as unfixable because its parent's constraint (4) required the merged state to be
recorded rather than derived, and nothing recorded it. The recorded heads are that record. Step
2a step 0b's heredoc asks for a held doc naming the branch, a recorded head containing it, and no
live tip past that head; all three mean every commit on it was in a merged PR.

**It is not a new verdict class, and that is deliberate.** Three earlier disqualified cuts
established constraints (5) and (6). Excluding the branch from Step 4a stalls its task forever,
and a new class must then be routed into every actor that keys on `approved`. A landed branch
keeps the `approve` verdict, so Step 3b, Step 3c, Step 4-pre's cardinality and Step 4a see it
unchanged. Only the review is skipped: steps 1–3, the Step 2b agent (the measured ~460k-token
cost) and Step 2d. Step 4a item 1 then prints `REPLAY 0`, and neither arm merges the branch:
Step 4c 1b's recorded-head test scores it merged, which is what lifts constraint (5), and Step 6
deletes it as a merged branch.

**Why neither arm merges it, rather than letting `--onto` no-op.** The local-only `--onto` would
replay nothing, but the published arm's `--no-ff` merge would put the branch's old task body
against the newer one the squash landed: the index-conflict entry's population (b), the same task at two ages, as
an `add/add` conflict. Not merging removes that population, and (c), for every branch a recorded
head fully contains. That entry's other populations do not involve a landed branch and are untouched. The re-stamp trap (Step 4a rewrites the ref)
does not bite, because the check reads the head, which nothing rewrites.

**A held doc is the discriminator, not the worktree.** Containment is not enough: a recorded head
contains the tip of anything cut from local `<default branch>` before that close. That covers an
unstarted claim in every workspace mode and any long-lived branch that is an ancestor of `main`.
The first cut used "no linked worktree", and its round broke it three ways (reproduced). A
`--clone` claim is never a linked worktree, and its work lives in the clone and on
`origin/<branch>` while the primary's ref stays at the cut point. `cleanup_worktrees.sh --force`
removes every non-main worktree, an active claim's included. And a branch no claim produced, `production` say, has none.
Each was approved as landed, merged under neither arm, and deleted by Step 6, the clone's
pushed work with it. Step 6's HARD RULE is the only reason a close leaves a merged branch alive, so
the test is that rule's own evidence: a pending doc in the main checkout's
`sysop/runtime/pending-docs/` naming the branch. Two more conditions close the clone case: no live
tip may sit past the head (the lock's recorded workspace ref, `origin/<branch>`), and a workspace
on the branch with uncommitted work is live. `/sitrep` applies the same three conditions before its
park, stale and `planning` arms. The order matters: with the heads excluded a held task reads 0
commits ahead, and the stale arm would have advised removing the lock of a task waiting on its
human step.

**The `direct` arm.** A `direct` close records no PR head, so until the
landed check the follow-up close of a held branch it had merged printed `NOT LANDED — no recorded PR head
contains it` and reviewed the branch in full. After Step 4a's rebase and `--ff-only` merge, both
`<default branch>..<branch>` and `<default branch>...<branch>` are empty, so Step 2d read the
`test-proves` record against a diff touching no test file, and `## Also fixed` check 1 found every
named path outside it and recommended *Hold for fix*. A build had just made `/sitrep` route such
a branch here as `merged, close pending`, so the routed path met the false halts. When no recorded
head contains the branch, step 0b now lands it when three things hold: its local tip is an ancestor
of local `<default branch>`, it is not the default branch, and a doc naming it carries
`held_since:`. Step 4c 1c writes that stamp on a held doc whose branch `HEAD` (or a recorded PR
head) already contains, so it records that a close held the doc with the branch inside it. It does
not record that the close merged the branch: a branch with no commits of its own is contained
trivially, so its held doc is stamped at its first close (round 2, lenses D and E).

**Why the stamp, and why the local branch only.** The first build asked
`/sitrep`'s `_merged_into_default` question unchanged: a held doc, and ancestry of the local default
branch or `origin`'s. Lens C showed a doc in the main checkout's pending-docs is not proof a close
held it: `/document-work` on a `--branch` claim writes there directly, so a branch at the default
branch's tip with zero commits landed on its first close. The stamp excludes a doc no close has held:
that one, and a doc a close collected but never held because it stopped after Step 4a merged, whose
branch is reviewed in full as before. What it does not exclude, round 2 showed: the same
zero-commit doc, once a close has held it, lands at the next close, and the PR arm takes no stamp at
all. The cost is bounded: Step 4c 1b routes an unheld zero-commit doc and closes its task whatever
step 0b says, so landing it skips only a review of an empty diff. The maintainer kept the stamp on that
reading (2026-10-06); a record written when Step 4a actually merges a branch is filed. Lenses A and C
showed the `origin/<default branch>` container was refused downstream: with local `main` behind it,
Step 4c 1b's `rev-list --count <branch> ^HEAD` was non-zero, so the doc did not route, and Step 6's
safe `-d` refused the branch. The arm now uses the ref both of those test against. `/sitrep`'s twin
keeps both refs and needs no stamp: it only routes, and the close's full review is the loud
direction.

**The lock workspace's status read.** The PR arm's lock loop already refused a workspace on the
branch with uncommitted work, with a bare `git status --porcelain`. The first build said 0b left
dirtiness to step 0; all three lenses showed that read was still there, and that it refuses a
`--clone` workspace whose only change is an untracked `.venv` symlink to an ignored target
(BeanRider ISSUE-0043). Step 1-pre's `noise()` downgrades that shape, so step 0a does not SKIP the
branch, and a clone is the one workspace a close never removes. The loop now applies the same
`noise()` test, and `/sitrep`'s `_live_work_past` mirrors it. 0b still leaves a linked worktree and
the primary to step 0, whose Step 1a classifier carries the same downgrade. Both arms now read the
branch's tip from `refs/heads/<branch>` before asking which recorded head contains it: a tag of the
same name otherwise resolved first and landed a branch with unmerged work (round 1, lens A,
pre-existing).

`origin/<branch>` is still read live with `ls-remote`, where `/sitrep` reads it as last fetched.
Neither arm merges the branch: rebasing an ancestor only moves its ref to the target's tip. Step
6's `direct` list deletes it with the safe `-d`, which passes because the tip is an ancestor of the
local default branch.

**What a landed branch still meets.** It counts toward Step 4-pre's condition 1, deliberately, so
a close holding one plus a single approved branch with its own PR takes the integration-branch
shape rather than reuse; reuse can never fire on the landed branch itself, because condition 5
fails. 4a-post does not count it among branches still approved, because it merged nothing this
run, and counting it would stop a close whose only approved branch is landed.

**Heads are recorded only from the provenance build on, and only on an in-run `MERGED` verdict.** A PR merged
by hand after a stuck-PR stop, or by an earlier close, has no head until someone runs Step 4d's
record command for it, which 4d-1 says.

**A reverted squash makes its head lie.** A recorded head means "these commits are in `main`",
which holds only until someone reverts the squash. Then `--onto` skips the reverted commits, Step
2a approves a held branch as landed, and Step 4c 1b closes its task with the work gone (round 2,
reproduced). The maintainer's ruling (2026-10-01): an operator rule, not a check. Step 4d tells the operator
to delete a PR's ref when its squash is reverted, and automatic detection is filed.

**Round 2's patches to the landed path.** The landed check reads frontmatter with the same `fm_re`
Steps 3b, 3c and 4c use, so a BOM or a branch name containing `---` reads the same in the close
and in `/sitrep`. It reads `origin/<branch>` with `git ls-remote`, because nothing in the close
fetches feature branches. A stale remote-tracking ref let a lockless clone's pushed work read as
landed and be deleted by Step 6. A failed `ls-remote` is NOT LANDED. A `REPLAY 0` branch Step 2a
did not approve as landed is 4a-SKIP rather than merged under neither arm, and 4c 1b's head test
does not route a 4a-SKIP's doc. The first cut trusted containment at every step after 0b, so a
reviewer approving a NOT LANDED clone reached Step 6's remote deletion anyway. On the published
arm, the structural recipe reads what the branch changed from `git diff <head>...<branch>`. Stage
1 is the pre-squash merge base, so read from it every stale flip looks like a branch edit the
recipe tells the operator to re-apply. The resolution is per line, not per hunk, because a hunk
can hold the branch's own line beside the stale one. `/sitrep`'s stale arm does not fire for a
task whose doc is held, whether or not the landed test passes.

**Why the `merge --continue` rule exists.** Step 4a merges a published branch `--no-ff`, and a
conflict there cannot be continued with `rebase --continue`, which exits 128
(`no rebase in progress`). The rule is exact for the same reason the rebase one is: `-c` is not a
wrapper the matcher strips. A PR merged outside the run (4d-1) needs its head recorded because
otherwise the next close cannot tell that PR's claim flips from a branch's own work.

### A held doc's branch and the reuse shape

`gh pr merge --delete-branch` deletes the merged PR's head branch on the remote and, once `gh` has
moved `HEAD` off it, locally too. Under the integration-branch shape that head is the integration
branch, which no pending doc names. Under the PR-reuse shape it is the approved branch itself, and
Step 4c 1c can hold that branch's doc on an outstanding `hold:` or `user_action`. Step 6's HARD
RULE keeps a held doc's branch because the next close's step 1b resolves the doc's `branch:`; with
the flag, the branch is already gone before Step 6 runs, and the next close stops on 1b's *"If
`refs/heads/<branch>` does not resolve, stop and ask"*. Dropping the flag on that one shape leaves both copies for
the close that consolidates the doc, whose step 0b approves the branch as landed and whose Step 6
then deletes it. A repository configured to delete head branches on merge removes the remote copy
regardless; step 1b and step 0b read the local ref, and 0b's `ls-remote` finds nothing to compare.

### A check that never started

GitHub completes an Actions job it refused to start (internal tracker #782: an exhausted Actions
budget, three times in one consumer) as `status: completed`, `conclusion: failure`, `steps: []`, with an
empty `runner_name`, and `gh pr checks` renders it `fail` like a job that ran and found something.
The only statement of the cause is a check-run annotation. So 4d-1's advice to fix the failing
check sent the operator to fix code that was never measured, and in the reported case the refused
job was a secret scan, which read as a leak. The test pairs the empty `steps` with the `failure`
conclusion because a `skipped` job also records none. It reads the job named by the check's link
(`…/actions/runs/<run>/job/<job>`) rather than listing the run's jobs, because a job's id is its
check run's id (verified on this repository's own CI), so one call answers for the check in hand.
`gh pr checks --json` exits 0 when a check has failed, where the plain form exits 1 (measured on
two public PRs with failing checks), so the listing needs no `|| echo` tail.
`gh run rerun` is not seeded as an allow-rule, so the re-run is the human's `!` command. Re-running
the whole close meets the same refusal: a new PR under the integration-branch shape, the same PR
under reuse.

### A landed branch's `## After merge` is printed once

Step 2d's loop excludes a branch Step 2a approved as landed, and `2‑also` and `2‑after` share its
reach. An earlier build had added a `landed by PR #<N>` label to Step 8's `After merge:` line that no step
could produce. On the maintainer's answer (2026-10-06) the label went, rather than the reach widening: the
close that merged the branch printed its steps, and printing them again at the follow-up close
invites running a migration or a deploy twice. A stuck-PR stop prints them in its report, since
that close did not see the merge (round 1, lens C). A `direct` close that stopped after Step 4a merged
and before Step 8 printed nothing; its doc is unstamped, so the next close reviews the branch in
full, over an empty diff.

### The retired notes ledger's conflict bullet

No skill writes `tasks/notes.md` after fix-by-default. The shared-append-files section keeps its
bullet because a consumer's existing ledger is still edited by hand and by `/add-task`'s
promotion until the consumer clears it, so the conflict can still arise.

## Step 4a-fix — provenance

Editor-addressed history for `### 4a-fix. Fix the Close's Notes` and the `NOTES:` block in
Step 2b's prompt. Nothing here binds the runner. Built on three menu
answers: fix-by-default scope, the `convention-gate` role, and a formal `NOTES:` block.

### Why a notes channel at all

Step 2b's verdict is binary, and until this channel existed its prompt had nowhere to put a finding that is
wrong but does not block. Reviewers wrote those findings in prose anyway, and the session filed
them. One real consumer's queue held between about 40 and 85 task bodies saying a close surfaced
them, about half still open (read 2026-09-24; the number depends heavily on the match form). So
the channel already existed, informally and unevenly, and the cheapest findings a close sees, a
stale path or a config drift in a file it just reviewed, were taking the most expensive route
out: a fresh agent onboarding to a task later. The `NOTES:` block makes the channel a contract,
and `4a-fix` gives each note the fix, file or drop outcome every executor already runs under.
Asking for notes may raise their count. The close still disposes of each one, so a higher count
costs close time rather than queue growth.

### Why the fix lands on the merge target, after the merges

This is a choice, not a constraint. A fix committed to a feature branch moves the branch tip past
the `branch_tip:` its pending-doc recorded, and Step 3b's collect then refuses with `PENDING-DOC
STALE`. `/document-work` Step 3 handles its own in-branch fixes by re-stamping
`branch_tip:`, and the close could do the same. It would then be editing a record another skill
wrote, whose `summary:` does not mention the fix. Landing the fix after the merges avoids that and
buys two further properties:
- it fixes the merged state once, even when two branches touched the file;
- `4a-post` then runs the consumer's full list and the pre-scan over a tree that contains the fix,
  and a failure it causes can be undone by itself.

### Why a failed fix is dropped rather than reverted, and filed at the start of Step 4d

The first build reverted with `git revert --no-edit`, and its round broke that twice. **The
revert conflicted:** item 6's filing commit sat on top of the fix, and when both touched the same
task body the revert stopped mid-way with `REVERT_HEAD` in the primary tree, a state no step
handled. **And no seeded rule matches `git revert`.** The drop is `git rebase --onto
<fix-sha>~1 <fix-sha>`, which binds the seeded `Bash(git rebase:*)` rule. It is safe only because
the fix commit is unpushed and is `HEAD`, which is why the runner checks `HEAD` first. Round 2 ran
it clean in every merge shape, including a `--no-ff` merge parent and a PR-reuse branch where the
fix is the only commit ahead of `origin`.

Filing moved out of `4a-fix` for two reasons:
- a drop is then always of `HEAD`, never of a commit with work on top;
- the validator is red before Step 4c's status flip in exactly the shape `4a-post` item 4's
  inherited-failure arm exists for: a task `in_progress` with its lock removed.

It sits at the start of Step 4d rather than at the end of 4c, because round 2 found the 4c
pointer unreachable. Step 4c skips consolidation when it finds no pending-docs, and that includes
the unpushed-main-only close whose notes item 6 names.

**When the drop does not cure a `4a-post` failure, the fix is restored** with `git cherry-pick`
(seeded). Without that, round 2 showed, an innocent fix is discarded and its notes are routed to a
filing step the stopping close never reaches.

**The fix commit carries no note text.** Notes are reviewer prose about code and routinely hold
backticks. In a double-quoted `-m` string, round 2 watched `` `date` `` run and its output land
in the commit body. So the notes live on Step 8's `Close notes:` line and in the filed tasks.

Both commit messages start `docs: `, which the seeded `Bash(git commit -m "docs: *)` admits.

### What stops remain

The verdict path adds no stop of its own while the drop succeeds. A `BLOCKED` re-check, a
mismatched echo or no verdict drops the fix and files its notes. **The step is not stop-free**,
and the first build's claim that it "cannot add a stop" was false:
- `review_pins.py add` refuses a pin path git does not ignore;
- a Rule A branch assert that fails before either commit;
- Step 2b's HARD RULE treats a dirty pinned checkout as a finding about the round;
- the menu in item 2 waits for the human;
- a drop that cannot run stops, whether `HEAD` is not the fix or git refuses over a dirty tree,
  and the fix commit stays on the merge target;
- a red validator holds the filing commit;
- `4a-post`'s drop arm fires only on its first run with `HEAD` still the fix and a clean tree.
  When the drop does not cure the failure, the fix is restored and the close stops like any
  other. On a Rule B re-run, or over a dirty tree, a fix-caused failure stops the close directly.

### Why the re-check uses the `convention-gate` role and one agent

The re-check is a convention gate over new hunks, so it takes the role the 2b convention agent
takes (defaults to `sonnet`; a consumer can move it in `served_models.local.yml`, which moves both
pins together). The saving comes from the diff size, one small commit rather than a branch, and
not from a cheaper model. The entry as filed proposed the `mechanical` role and itself flagged that
as undemonstrated for "is this fix safe". A cheaper model on hunks that bypassed the full gate
would weaken review at exactly the point it was supposed to preserve it. The agent spawns only on a
close that fixed something. The entry's "fires on every close" described a design that re-checked
unconditionally.

**Security stays on the path with a security lens.** A fix touching a security-map glob is filed,
and so is every note the security twin raised, since a note about a file outside the globs would
otherwise be fixed and re-checked by the convention lens alone. So no security twin is re-spawned.

### Why the scope is the merged diff

The fix-by-default rule says "whatever file", but at close the review net is one re-check agent
reading one commit, not a round. Bounding fixes to files the close's merged diff touches keeps
every fixed file inside a tree Step 2b already read. The one exception is the test that pins a
behaviour fix: without it, fix-by-default's own "add the test" rule would send nearly every
behaviour fix to the queue. The never-list is the executor's, and at close it is absolute: a
never-list note is filed even on the human's answer, because the close has no `## Also fixed`
record to carry the approval.

## Step 4a-post — provenance

Editor-addressed history for `### 4a-post. Verify the Merged Tree`. Nothing here binds the runner.

### Why the empty changed-file list branches on the approved-branch count

The stop this replaced was unconditional, and its own stated causes were the argument against it:
*a rebase left the branch a no-op, a `--ff-only` merge was skipped after a conflict, or `HEAD` is
not the merge target you think it is.* All three presuppose that a merge was **attempted**. On a
docs-consolidation cycle none was — Step 4a's loop runs over an empty set — so the premise of the
contradiction is false and the stop fired on a close behaving exactly as designed. Reported from a
consumer whose cycle had zero feature branches, zero unpushed `main` commits and four pending-docs.

**The cycle is not exotic.** It is the shape a close takes whenever the previous one merged its
branches but left pending-docs behind, held or stranded, and it is reachable any time
`/review-close` runs twice in a row.

**Why the predicate is the approved-branch count and not "Step 4a merged zero branches."** Those
two are not the same set, and the difference is the Step 4-pre PR-reuse shape: there Step 4a is
skipped entirely, so it merges zero branches, while the merge target *is* an approved branch. An
empty list in that shape is a genuine contradiction — an approved branch that contributes nothing
against `origin/<default branch>` — and must still stop. Measured on a fixture: a reuse-shape
branch carrying one file diffs non-empty; a reuse-shape branch built from an empty commit diffs
empty with an approved-branch count of 1, while the reported cycle diffs empty with a count of 0.
Keying on the merged count would have widened the arm onto the one shape that needs the stop.

**Why the report is not `ran nothing`.** The filing asked for `ran nothing: no branches merged`.
That token is false for the filing's own reported case: four consumer-declared commands ran there.
The changed-file list's emptiness is a fact about **scope**; `ran nothing` is a fact about
**execution**, and they are independent — a declared `### Always` list runs whatever the diff
shape, which is the promise Step 3's item 1 makes on this step's behalf. Folding the two would
report a close that executed four commands as one that executed none.

### Why item 4 gained an inherited-failure arm, and why it is scoped to one error

`4a-post` item 4 was an unconditional *on failure, stop*. A consumer hit it on a
`validate_tasks.py` Invariant 9 error — `status=in_progress but lock file missing` — that was
already present on `origin/<default branch>`, on a cycle that merged nothing and therefore could
not have introduced it. Stopping there prevents Step 4c, and **Step 4c's `done` flip is what
clears that error**: verified on a fixture, exit 1 before the flip and exit 0 after it.

**The skill already said so, in another step.** Step 6's *Lock-as-real-time-signal invariant* names
this exact error as an expected transient of `pr` policy — Step 4c removes the lock from disk on
the integration branch before the PR merges, so `main` briefly carries the task `in_progress` with
no lock — and says *"No action needed beyond not re-claiming."* Item 4 halted on it anyway. Two paragraphs in one file,
one error, opposite dispositions. The filing found the Step 6 note; this phase verified it.

**What the filing got wrong, and what the record should not repeat.** It argued the error is then
*permanent*, "because the only thing in the repo that clears it is the Step 4c round-trip that
stopping prevents." That is false. Both remedies the validator's **own** error message names clear
it, each verified on a fixture: recreating the lock (`claim_task.sh --lock`) exits 0, and flipping
the task back to `status: open` exits 0. So the defect is that a gate halts a healthy close until
someone clears the state out of band — real, and worth a fix — not that the close can never run
again. The two remedies are not the same size: `status: open` edits tracked `tasks/index.yml`,
while the lock remedy writes a gitignored runtime file and touches nothing tracked, so "hand-edits
the default branch" is true of one and false of the other. (A first measurement of the second remedy reported it failing; that was a fixture error, a
`sed` whose pattern matched the phase entry's `status:` as well as the task's. Re-derived with a
targeted edit, it passes.)

**Why three preconditions and not a general inherited/introduced test.** The filing proposed the
general form: re-run the failing command against `origin/<default branch>` and, if it reproduces
unchanged, classify it inherited and continue. That licenses continuing past **any** gate-visible
defect already on the default branch, which is a fail-open widening of the one gate this skill
calls *"the gate whose green means something."* The arm shipped instead is the narrowest one that
covers the reported case: it fires only on a cycle that approved zero branches, only when the
failure reproduces on the default branch, and only for the one error another step already
classifies as self-clearing **and** only when the pending-doc that will clear it can be named.
Anything it cannot establish is a stop.

**Why it reports rather than passing quietly.** A gate that continues past a failure and says
nothing is indistinguishable from one that passed. The `INHERITED:` token on Step 8's
`Verification:` line is deliberately not foldable into `ran on <merge target>: N commands`, for the
same reason `ran nothing` and `TIMEOUT` are not: each names a different state of the gate, and a
report that loses which one occurred is the equivalence this whole step exists to remove.

### Step 2d check 1's notes, and the bound they leave

Check 1 halts only when a line names paths and none of them is in the diff; a
line with one path in the diff reports its others as notes. Read literally, the ruling ("halt
only when no path in the line is in the diff") would also halt on a line that names no path at
all, which check 1 had always passed, so that line stays outside the check. The cost is a
narrower screen: a fabricated path written beside a real one now reaches the human as a note, not
a halt.

### Why item 4 also asks on a `pr` close's pre-existing failure, and why that is not the general form

**The case.** A consumer's close merged work, and two tests failed at `4a-post`. They failed only
because a local `.env` let an unmocked call reach a live service: they failed identically on
`origin/<default branch>`, passed in a worktree with no `.env`, and CI was green. The arm above could not fire,
because its condition 1 requires zero approved branches, so item 4 stopped. Every later close that
merged anything would have stopped the same way until someone repaired the tests out of band.

**What the maintainer ruled (2026-09-30), and how it differs from what an earlier build refused.** That build refused
the general form, which re-runs the failing command on the default branch and, if it reproduces,
classifies the failure inherited and **continues**. That form widens the one gate whose green means
something, for every defect already on the default branch, with no one asked. The arm shipped here
continues on nothing by itself. It establishes a fact and **asks**, once per close, and only an
answer moves the close forward. It is also narrower in three ways:

- **`pr` only.** Under `pr` the merged work reaches the default branch through a pull request, so
  whatever checks the consumer requires on that pull request run before it lands. Under `direct`,
  this gate is the last thing between the work and the pushed `main`.
- **Test IDs, not output.** The comparison is between two sets of named failing tests. A command
  that names no individual tests cannot be compared without guessing, so it stops. A failure that
  matches on output alone, such as the same exit code from a build, is not this arm's case.
- **Same environment.** A detached worktree carries no untracked file, so a probe run there drops
  the `.env` that caused the failure. On the reported case that probe *passes*, the sets differ,
  and the arm would never fire on the case it was ruled for. So the probe links the failing run's
  local files in at the same relative paths, and a probe that cannot be given them establishes
  nothing.

**Two ways the probe could agree for the wrong reason, both found by a review round and both
reproduced.** First, a run that stops at the first failure (`pytest -x`, `--maxfail`) reports only
the pre-existing failure it meets first; the regression behind it never runs, and the probe on the
default branch reports the same single ID. So the run must have run every test. Second, the
dependency tree. Linking the checkout's `.venv` into the probe makes the command run, but an
editable install (`pip install -e .`) points that interpreter at *this checkout's* `src/`, so the
probe on `origin/<default branch>` imports the merged code and fails identically. Linking only files does not
cure it either: the same interpreter named by absolute path still follows the editable install. So
the probe must show where the code under test loads from, and a path outside the probe stops the
arm. On a project that tests through an editable install the arm is therefore usually inert. It
fails closed, which is the right direction for a gate whose job is to refuse.

**Known bound: the same set, not a subset.** If the work fixes one of two pre-existing failures,
the merged tree fails a strict subset of what the default branch fails. The sets differ, so the arm
stops. That is the conservative reading of "identical", and it is the ruling's word. A later case
that needs the subset form is a new decision, not a reading of this one.

**Why `PRE-EXISTING:` and not `INHERITED:`.** `INHERITED:` means the three preconditions above held
and the close continued without asking. This token means a command failed, the default branch fails
the same tests, and a human chose to proceed. Folding the two would lose whether anyone was asked.

**The other half of the ruling is in `WORKFLOW.md` § 6.1:** a pre-merge gate should not depend on
local credentials. The ask is relief for a gate that already does; the template note is what stops a
consumer writing one.

### Why the Exit 0 arm keys on the printed counts and marker

`--fail-on-blocking` fails on a `failed` blocking stage and on a new blocking finding, nothing else.
`accounting.py`'s `blocking_failures()` keys on `failed` only, and its docstring points at
`tools/PRESCAN_ACCOUNTING_SPEC.md` (maintainer-side; never ships) for why gate-on-skipped cannot ship. So a localized blocking
check that was `skipped` or `unroutable` exits 0. The arm used to withhold `clean` for `degraded`
alone, which reported a gate that did not run as clean. A bundle executor found it in a
sibling sweep.

The fix keys on what `render()` prints. **Its first cut keyed on any `⚠` and was wrong both
ways**, which a review round measured:
- `render()` puts `⚠ BLOCKING CHECK …` only on a *localized* blocking check. A blocking check with
  no concrete `paths:` still runs whole-tree, can be `degraded`, and gets no `⚠`. So keying on the
  marker alone reported that run clean, a regression against the arm it replaced.
- `run_checks/cli.py` appends its own `⚠ … review round(s) started and never completed` note to
  the same block, and it has nothing to do with this scan.

So the arm reads the header's `failed`, `degraded`, `unroutable` and `unaccounted` counts, which cover every
check whatever its scope, plus the `⚠ BLOCKING CHECK` lines for a localized blocking check that was
`skipped`. It reports "not every check ran fully" rather than "a blocking check": from the output,
a degraded or unaccounted check cannot always be told to be blocking. It asks for no ids, because
a `⚠` line reads `<status>: <stage> (<N> checks) — <detail>` with none, and its N counts every check
in the group, blocking or not. (`render()` does print ids elsewhere, on the `unaccounted:` line and
on executed-with-zero-findings lines.) Quoting the lines verbatim is the report the output can
support. Round 2 added `failed`: a crashed *non-blocking* stage (an invalid semgrep rule) exits 0,
prints no `⚠`, and left the arm saying `clean` over a scan that did not run.
`tests/test_prescan_merge_gate.py` binds the counts and the marker to `render()`.

## Step 4a's shared-append resolver — provenance

`steps/4a-append.md` used to give the runner two stage-extraction blocks and five bullets of
judgement, and every close with several appending branches hand-built a resolver from them (GDP
wrote about 90 lines mid-close, internal tracker #766). Under `dontAsk` the blocks were also a wall:
`mktemp -d`, the `>` redirects and `comm … <(sort …)` are each denied (the headless table), so an
unattended resume that met the arm stopped there. `sysop/scripts/resolve_append_conflict.py` is
those blocks and bullets as one command.

### Why `index` refuses what it refuses

Union-by-id (take the target's file, append the ids it lacks) is right for the common case and
loses work, with the validator green, in five others. The resolver handles three of them and
refuses the rest:

- **A branch edit of an existing entry** (a retriage, an `/onboard` import) is discarded by
  union-by-id, because the id is present. The resolver applies it when the target left the entry
  as stage 1 had it, and refuses when the target edited it too.
- **A branch removal** (a withdrawn task) is undone by union-by-id; `validate_tasks.py` then
  reports the removed id's missing body, which invites recreating it. Applied when the target
  left the entry alone, refused when it edited it.
- **A target removal** looks new to union-by-id, which appends it back. Left out, and refused
  when the branch edited the entry.
- **A same-id add** was renumbered. The index-conflict entry found six populations (two branches auto-numbering
  one id, an already-landed branch replaying its own older copy, and four more) that no
  conflict-local fact separates, and renumbering files a stale duplicate in the replay case. The
  resolver refuses it, which 4a-SKIPs the branch; a skipped branch recurs on the next close, so
  this does not close that entry's item (7).
- **A change outside `tasks:`** (a new phase) is dropped by starting from the target's file, and
  the symptom invites retyping the task's `phase:`. Refused.

A conflicted body file beside an index conflict makes the resolver refuse. A body-only conflict,
with the index clean, is that entry's population (a): both sides edited one task's prose. Its
item (3) recorded aborting it as wrong, so on the maintainer's answer the
attended arm keeps both edits as `review_tasks.md` is resolved, aborting only where they change the
same lines, and an unattended close stops there and parks, so a person resolves it once rather
than a 4a-SKIP recurring every night. (An earlier round's body-only stop was a modify/delete,
which git also leaves unresolved, and the same rules route it.)

The arm's commands run under the seeded `Bash(python3 sysop/scripts/resolve_append_conflict.py:*)`
(`tests/test_resolve_append_conflict.py` checks the template carries it).

### Why it splices text

`yaml.safe_dump` would reorder and restyle the consumer's file. The resolver keeps stage 2's
text, replaces, removes or appends only whole entry blocks, copied from stage 3, and checks that
the spliced file parses to exactly the entries it meant to write before it writes. Entries are
compared by parsed value, so a reformat that parses the same is not a change and is not carried.

### Why `notes` is a three-way line merge

The old fallback for a ledger where a side deleted a line was "take the target's file and append
only the lines stage 3 added". That keeps the target's deletes and loses the branch's: a branch's
`/add-task` promotion, adjacent to the target's append, brought the promoted note back. The conversion
found it while converting the block; `notes` takes the target's lines less the branch's deletes,
plus the branch's additions the target did not also make.

### Why `--since`

On Step 4a item 2's published arm with a recorded PR head, stage 1 predates the claim commits that
head contains, so a status the claim set reads as two actors. `--since "<ref>" "<branch>"` reads
the branch's changes from its merge base with the ref, the same thing the item's `git diff
"<ref>"...` test reads, and prints `TARGET SIDE:` for each status it kept on the target's side,
for Step 8.

## Step 4c — provenance

Editor-addressed history for `### 4c. Consolidate Pending Documentation`. Nothing here binds the
agent running the skill; it is why a rule in that step is shaped the way it is, so that an editor
changing one knows what the shape was bought with. Authored, not copied — the runner keeps the
rule, this keeps the argument.

### Why the hold test short-circuits the ref resolution, and what was refused instead

The filing proposed two remedies and only one survived measurement. The second was a recorded merge
SHA in the pending-doc's frontmatter: it would give 1b a handle that survives branch deletion, but
it does not answer 1b's question once Step 4a squashes — that is the same ancestry property the
cherry-pick blockquotes spend three paragraphs on — and it buys nothing at all for a doc whose
disposition 1c has already settled. The `branch_tip:` field is a *different* field answering a
different question at a different step, and reading the two filings as sharing one key, which the
phase brief did, would have added a second consumer to a field that cannot serve it.

**The scope sentence in the runner is there because an earlier draft got it backwards.** That draft
said 1c runs only *"for every doc 1b did not short-circuit"*, which would have made the
short-circuit silently *delete* the hold report — a held doc vanishing from the run's own record is
the exact failure 1c's `Held-back docs:` row exists to prevent.

**And the ordering paragraph is load-bearing rather than explanatory.** A rewrite that drops it
restores a halt with no outcome attached to it: 1b's stop-and-ask firing on a branch reference for
a doc that was never going to be routed. That is the self-inflicted shape the cherry-pick
blockquote names one screen further down — the close halting on a doc it created the conditions
for.

### What the ancestry test was measured against

`rev-list --count "<branch>" "^HEAD"` answers one question — is this branch's history contained in
the merge target — and the two contained shapes were established separately. A rebase followed by
a fast-forward merge is contained by construction. A `--no-ff` merge is contained too, which is
less obvious and is why it is stated: its commits go onto the target unchanged, so the exclusion
reaches them. That arm is Step 4a's *published* path and arrived with it.

The one shape that defeats the test is a rebase onto a throwaway ref, where the branch's own
commits never join the target: a perfectly merged branch then scores `2`. That was measured on a
real tree, and it is the reason the mechanism it belonged to was withdrawn rather than shipped.

**What the runner's paragraph no longer claims, and the correction is the point.** An earlier
version said the count is `0` for every branch that landed under either policy. It is not, and the
drift guard pinning that sentence asserted all three merge shapes while the fixtures built exactly
one — `direct` ff-merge. The `pr` integration-branch and PR-reuse shapes are reasoned from the same
ancestry property, not exercised. **Do not restore the stronger wording without the two missing
fixtures.**

### What the cherry-pick arithmetic was measured against

Every number the runner's paragraph rests on came off a real tree rather than from reasoning about
git's model.

**The ancestry test's failure modes.** With the merge target diverged, a picked range of 2 commits
scores `2` while `git cherry` reports `0` unapplied; a rebase-then-cherry-pick scores `1`; and an
*empty* cherry-pick — content already applied, with `git diff --quiet <branch> HEAD --` reporting
the trees byte-identical — still scores `1`.

**Why the `main`-doc case does not hide.** A cherry-pick scores `0` only in the degenerate case
where it reproduces the identical SHA, which needs the picked commit to land on the **same parent**
it originally had **and** to carry the same committer timestamp. `git cherry-pick` stamps the
committer date at *pick* time, and the local-only commits in question are `/claim-task` Step 4d
flips and Step 1b `review_tasks.md` saves made minutes to days earlier — so the timestamp condition is
essentially never met on this path, and the same-parent condition alone is not enough. Measured on
a realistic five-minute-old local `main` commit: `rev-list --count` `1`, `git cherry` `0`
unapplied. The `0` outcome is confined to a pick made inside the same clock second as the original
commit, which the close path does not produce.

**The `-c` flag, verified rather than reasoned.** The `-c` form prints `0` and exits `1`; the
`grep | wc -l` form prints `0` and exits `0`. Zero is the *pass* value here, so the `-c` form
returns a failing status on the good outcome. This is the `|| true`-class trap
`_shared/permission-guard.md` already names, in a command whose exit status is read in exactly the
direction that inverts it.

**`git cherry`'s own limit.** A cherry-pick that required conflict resolution changes the patch, so
`git cherry` prints `+` for a commit that *is* applied — measured: `rev-list` `1`, `git cherry`
`+1`, content present.

### How the hard stop is reached, and why `direct` is benign

Under `pr` policy Step 6 force-deletes (`git branch -D`) every branch Step 4a recorded as merged. A
branch the operator cherry-picked is recorded merged, so it is deleted — while its pending-doc was
held back at 1b for scoring non-zero. On the next close the doc is re-collected, its `branch:` no
longer resolves, and the stop-and-ask fires: the close halts on a doc it created the conditions
for. Under `direct` the tail is benign, because that path's safe `git branch -d` refuses on a
cherry-picked branch and the ref survives.

**The parenthesis this replaced said the opposite of the rule above it.** It read that a doc with
no `branch:` at all was the benign legacy shape and consolidating it was safe, two lines under a
stop-and-ask. Both are now the single quarantine disposition, and the case the parenthesis was
reaching for — a legacy-format doc predating worktree-per-branch — is covered there too. Losing its
bytes to a quarantine directory costs nothing that consolidating an unroutable doc would have
preserved.

### Why `hold:` is a second field, and why a command now runs the test

Until the hold field arrived, 1c held a doc only while a named task's `user_action` was truthy. That flag has
two readers with two meanings. `/roadmap`, `/next-task` and `/auto-build` read it as *a human must
act before an agent can take this task*; 1c read it as *the deliverable is not finished, do not
close it*. A consumer reported three cases. In the first, the flag was cleared to clean up the
roadmap view. In the other two, the task simply reached the close with the flag false while its
body said the work was unfinished. Each time, the only thing between the doc and a false `done` was
1b failing to resolve a branch ref, or a closer who happened to read the task body.

`tasks/schema.md` § *User ops* had recorded "one field, not two" for `user_action` against a
`user_action_done:` companion. **`hold:` does not contradict that decision:** that argument was
about encoding one fact as two booleans on the task. `hold:` is a different fact, *this merge does
not finish the task*, and it lives on a different record: the pending doc, which is the thing 1c
holds. It is written by `/document-work` when the branch is documented and removed by
`pending_doc_hold.py clear`, after the shape of `clear_user_action.py`; no step of the close path
removes it. 1c holds on either field.

**Rejected:** inferring the hold from a body section still marked incomplete (`## User ops`, a
rollout list). That is not a mechanical test, because it asks the closer to judge prose, and the closer reading
the body was the safeguard that failed in two of the three reports.

**Why the test became a command.** With two inputs, one in the doc and one in the index, a prose
test is two judgments per doc at two sites (1b's short-circuit and 1c). It also needed a write:
`held_since:` (below). `pending_doc_hold.py check --stamp` puts the test, the shim, the
truthiness and the stamp in one place, and exits non-zero when it cannot read the index, because
then no hold can be decided. The round-trip heredoc is handed ids, not docs, so the runner tells
the closer to take its ids from `ROUTE:` docs only. As built, its defence-in-depth arm read
`user_action` alone, so a `hold:` had only that prose gate (lens A). The heredoc now reads the
pending docs itself and reports an id that a doc with `hold:` names as `HELD_BY_HOLD`, not closed.

**`held_since:`.** 1c stamps each held doc whose branch merged, the first time it holds it, as the
doc's first frontmatter line, because a line appended after a trailing block scalar would become
part of that scalar's value. One reader acts on it: `pending_doc_hold.py guard`, which never chooses
a stamped doc as the file `/document-work` writes. Step 3c read it too, for the landed-doc discriminator, until round 2
(§ *Step 3c — provenance*). The stamp is a date and not a SHA; nothing compares it. **The hold does
not depend on it, but `guard`'s protection does:** a held doc the stamp could not be written to (a
stray byte, mixed line endings, a flow-mapping frontmatter) is chosen and replaced like any
unstamped doc. 1c reports the `NOT STAMPED:` note on Step 8's row so the doc can be repaired. No
shipped writer produces those shapes.

**Why `/document-work` writes a second doc beside a stamped one (the maintainer's answers, 2026-10-01).**
`/document-work` writes `<sanitized-branch>.md`, so on the default branch every run writes the same
`main.md`. A held `main.md` is the only carrier of its tasks into the close that will finish them,
and replacing it lost them with nothing reporting it. That was already true of a `user_action` hold
from an earlier build on. The first answer was to refuse the write. Round 1 showed the cost: while any
`main.md` was held, no work on `main` could be documented, including the fix for the held task
itself. On the second answer, `guard` names the file to write: the base name, or the existing
unstamped `<name>--<n>.md` of the same branch, or a new one. Re-running `/document-work` rewrites
the unstamped one; that is the ordinary re-stamp of a doc no close has held. A `<stem>--<n>.md` of
another branch (a name `feat/x` and `feat-x--2` both sanitise to) is not a sibling. **Round 2 found
the second doc could write a false `Complete`:** a sibling naming the held doc's task routed, and
its PROJECT_STATUS entry said the task was complete while the round-trip held it. On the maintainer's answer a
hold became per task (above), so that sibling waits with the held doc. Every `/review-close` reader
globs `*.md`. `/sitrep`'s `_pending_doc_for` and `/auto-build`'s envelope recovery look up the base
name; both are reached only for a claimed branch, whose doc lives in its workspace, where a sibling
is never written.

**Why the collect refuses a doc that drops a hold.** Step 3b's
collect replaces main's copy of a same-branch doc with the workspace's, by design (the stale twin).
For a held feature branch that is claimed again and re-documented, that dropped the `hold:`, and
Step 4c then closed the task: a regression, because a `user_action` hold lived in the index and
survived the same replacement. Two parts close it. `guard` prints `CARRY HOLD:` when the main
checkout's same-named copy carries `hold:`, and `/document-work` writes it into the new doc. The
collect refuses (exit 3) when main's copy carries `hold:` and the incoming doc does not, so a doc
written any other way cannot drop it either. **A `--clone` workspace is its own repository**, so
`guard` cannot see the main checkout from it and prints no `CARRY HOLD:` (round 2). The refusal
names main's reason and says to add that line to the incoming doc, which works for every workspace
shape; its first wording, "re-run `/document-work`, which carries it", looped for a clone. The
collect checks that the incoming doc carries a hold, not that it carries the same reason; a changed
reason passes.

**What 1c's runner text used to argue, now that a command applies it.** The `task_ids` fallback
is not optional: a legacy doc keyed on `task_ids` that the gate skipped would be routed and
consolidated, and only the round-trip's defence-in-depth arm would then hold the task — the
stranding path, reached through the gate that exists to close it. The same is why 1b's
short-circuit reads both namespaces: keyed to one, it would resolve a ref for exactly that legacy
doc. Truthiness, and not `== true`, because the two gates must agree, and a malformed non-bool
value is where an equality test and a truthiness test diverge: an equality reading routes the doc,
the round-trip then holds the task, and the doc is deleted underneath it. The round-trip heredoc's
comment records why truthiness is the right bias. **A hold is per task (round 2):** a hold set on
one doc and read per doc let a second doc naming the same task route and write that task's
`Complete` while the task was held; `user_action` and the round-trip's `HELD_BY_HOLD` arm were
already per task, so `check` now holds every doc that shares an id with a held doc.

### The cost of holding the whole doc, stated rather than discovered later

When 1c holds a doc, the code merged this run and its `PROJECT_STATUS.md` / `CHANGELOG.md` entry
waits for the human step. That is the honest ordering — those files say a task is **Complete**, and
it is not — but it does mean a held task's documentation lags its merge, visibly, in
`Held-back docs:` on every run until the step is done.

### Why arm 3 exists, and why `startswith` is the wrong test

A doc that starts with `---` and fails to parse takes arm 1 under the old two-way rule, where
`yaml.safe_load` **raises** — and this step had no error arm at all, so the exception surfaced
mid-consolidation, after Step 4a had already merged.

The shapes that reach it are not exotic. An unterminated frontmatter block and a `---` used as a
markdown horizontal rule both fail the frontmatter match entirely, and raise `ValueError` under a
naive three-way `split('---', 2)` unpack — which is why the regex is the prescribed reader.
Malformed YAML raises `ScannerError`/`ParserError`. Frontmatter that loads to a *string* rather
than a mapping — a single prose line between the delimiters — is truthy, so the `or {}` idiom does
not catch it and `.get()` raises `AttributeError`.

**This file carried two divergent pending-doc readers, one defensive with code and one
prescriptive with none.** Step 3c's shipped reader skips three of the four — `if not m: return
{}`, `if not isinstance(fm, dict)`, and `errors="replace"` on all four reads in that heredoc —
and since a later build it **stops the gate on the fourth**, a frontmatter that will not parse,
naming the doc: a skipped doc carrying `manual_smoke` let the close merge unasked. It did not
handle any of them before the phase that wrote arm 3: a reviewer ran it and watched a non-mapping frontmatter and
a non-UTF-8 doc each kill the close with a traceback at a step that runs *before* this one, which
would have left arm 3 unreachable for those shapes. Arm 3 is what makes the two readers agree —
except that quarantining beats Step 3c's silent skip, because a skipped doc is invisible and a
quarantined one is reported with its bytes on disk.

### Why the `task_ids` fallback is still here, and when it goes

The fallback covers in-flight pending-docs authored before the `task_ids` → `roadmap_ids` rename.
Treating ids read through it as `roadmap_ids` matches the pre-rename consumer
behaviour: Step 4c's heredoc was already treating them as roadmap ids, silently no-op'ing on the
non-matches.

**Removal trigger.** The fallback can go once BeanRider has run one full `/review-close` cycle on a
pending-doc authored after the 23a absorption. The merged consolidation commit is the evidence;
`sysop/runtime/pending-docs/` is gitignored, so `git log` over it shows nothing. Pending-docs are
minutes-to-hours lived, so the shim's exposure window is one absorption cycle.

**Remove it from every reader in one change, never from Step 4c alone.** Six steps read it: Step
3c's smoke gate, Step 3b (its collect and its `WS`-empty open-claims line), `4a-post`'s
inherited-failure arm, and Step 4c's 1b short-circuit, 1c hold and step-3 shim. `grep -n task_ids
SKILL.md` lists them, and `tests/test_pending_doc_integrity.py` asserts some of them. Step 1b's note
says why a partial removal is a defect: a reader keyed to one field resolves a ref for exactly the
legacy doc 1c holds. This paragraph said "in any subsequent phase that touches Step 4c" until a
later build, which touched Step 4c, found the other readers, and left all of them in place. Its first count
of them was five; its round found the sixth step.

### Why the `git mv` needs its parent created

`git mv` into a directory that does not exist is fatal (`renaming … failed: No such file or
directory`), and with `check=True` that aborts the loop *after* earlier renames are already staged
and *before* the index write — reproducing the very half-staged commit the step exists to prevent.
`install.sh` ships `tasks/archive/.gitkeep`, so this only bites a branch cut before that landed;
the `mkdir` stays because the cost of keeping it is one line and the cost of losing it is a
half-staged close.

### Why `inside` gates both arms

The first cut of that block gated only the `rmtree` and let the symlink arm run unguarded, so a
`tid` of `../../../escaped_link` unlinked a symlink at the repo root and *reported it as a claim
artifact*. A review round reproduced it — against a comment in the same block claiming containment
was re-checked "before removing anything". The guard being written down is not the guard being
applied to every arm that needs it.

### What made `shutil.rmtree` the one call that must not raise

Every other operation in that loop is non-raising by construction — `unlink(missing_ok=True)` and
`glob` cannot throw on the inputs they get. `shutil.rmtree` over a user tree is the first that
realistically can, and a review round made one claim directory unremovable to see what happened:
the whole heredoc exited 1 with an earlier task's unrecreatable park marker already gone, a later
task's lock never cleaned, the index staged, and none of the six report rows printed — which puts
Step 8 straight back to supplying them from memory, the failure the report exists to close.

### Why the heredoc reports at all

Until an earlier build this heredoc printed nothing, while Step 8 asked it for three values — so the
agent supplied them from its memory of what it had intended, which is not the same list as what
the code did. The report is not a convenience: two of the values cannot be reconstructed after the
fact at any price, because `missing_ok=True` erases the distinction between a lock that was there
and one that was not, and an unlinked marker is gone.

### Two cross-references the runner does not act on

Step 4c carried two HTML comments addressed to no one running it. One named `WORKFLOW.md` § 2.8
(Senior Merge & Verification) as the canonical process for this step; the other recorded that
convention promotion had moved out of `/review-close` and into `/codebase-review` and
`/security-audit` Step 9. Both are true and both are editor-facing, so they are recorded here
rather than carried in the prompt.

### Why the consolidation commit is verified rather than trusted

Step 4b has had a trust-but-verify gate for this failure class for some time and Step 4c had none,
which is what let a rename-only commit pass as a consolidation (Sysop's internal tracker #203). The
`git mv`s inside the heredoc stage themselves, so a commit can carry the renames and none of the
shared-doc edits and still look like a successful consolidation from its subject line alone.

### Where §6's entries end, and why item 5's check compares everything else

Internal tracker #707 reported one rotation write that was wrong in two files. The Rotation check
said which entries to move and where to put them, and never said where §6's entries stop. On that
consumer §6 is the file's last section, so an end found by looking for the next numbered heading is
the end of the file. The section's closing furniture, a rotated-to marker and a standing note to
agents, has no entry shape and no marker the step named. It rode along as the tail of the last
entry: deleted from `PROJECT_STATUS.md` and joined onto a rotated bullet in the changelog. The
reporter caught it only by reading the staged diff, which showed 16 deletions where 6 were
expected.

**Sysop ships no `PROJECT_STATUS.md` template, so the step cannot name a marker to keep.** The
filing's "shipped template" was that consumer's. So the runner's rule bounds the entries by their
own shape, the writer's `<date>:` lines, and the check looks for no marker at all. It requires every
non-blank line outside §6's entry run to be unchanged apart from trailing whitespace, which catches
a lost line of furniture whatever a consumer calls it. §6's first entry is looked for only up to the
next section: a heading no deeper than §6's own (level 2 when §6 is a plain numbered line), or a
numbered line above 6. So a subheading or a numbered lead-in inside §6 does not end it.

**An indented line directly under an entry is reported, not resolved, because the text cannot say
what it is.** It may be the second line of a wrapped entry or a marker indented under the last one.
The phase that wrote this tried both readings, and each lost text in the other shape. Ending an
entry at its first line let the prescribed rotation split a wrapped entry, and the check passed the
split (round 2). Carrying the indented line with its entry let indented furniture ride out with the
last entry, and the only write the check passed was the one that deleted it (round 3), which is the
reported loss class again. So the rule names the ambiguity: the runner does not rotate, and the
check exits 2. Neither consumer's §6 has the shape today; a writer that makes one-line entries
never creates it. An unindented line under an entry is not ambiguous: it ends the run, as a marker
written straight after the last entry does in the reported case.

**What the check compares, and what it leaves to the prose.** Everything outside the entry run is
unchanged; §6 holds the count the Rotation check leaves, with the new entries above the newest old
ones in order; no line of §6's furniture reached the changelog, which was the durable half of the
reported loss; no line the changelog had at `HEAD` is gone; and, under `[Unreleased]` and outside
code fences (a closer needs its opener's character, at least its length, and no info string, the
rule an earlier build settled), no class heading or `## [Unreleased]` that appears more than once appears more often
than at `HEAD`. A first copy is not counted, because creating a missing heading is the contract. It
does **not** check that a rotated entry arrived in the changelog. The dedupe may drop it on purpose,
and deciding whether an existing bullet is that entry's own takes the reading the prose prescribes.

**Why it runs before item 6.** Item 6 deletes the pending-docs, and a doc is the only other copy of
the entry it produced. It cannot run before everything: item 4's heredoc has already staged the
index flip and reaped the claim artifacts by then, and the first rewording of its lead said nothing
was staged. A check after the deletion hands its runner a remedy that can destroy the one
copy left. The first cut of this check sat in item 7, and its round showed exactly that: a
subheading above §6's first entry made a correct write report the new entry as an added line, and
the remedy read as "delete it".

**Why exit 2 continues rather than stops, and what counts as exit 2.** No repository, a §6 the
check cannot find or finds twice, a file that will not decode, a git read that fails, or two tracked
changelogs is not evidence of loss. It is the state every close was in before the check existed, so the fallback is the diff read
that caught the reported case. A stop there would block every close on that consumer for a reason
unrelated to the close. **A git failure is kept apart from absence on purpose:** the first cut read
any failed `git show` as "not at `HEAD`", which skips the comparison and passes. The check resolves
the repository root itself for the same reason: run from a subdirectory, the first cut found neither
file and passed over a real loss.

**Why a fork the file already had only warns.** A copy of one consumer's live changelog, taken while
this check was built, carried `### Changed` three times and `### Fixed` twice under `[Unreleased]`.
Stopping the close on history it did not write would stop every close until a human edits the file.
So a fork this close created stops it, and one that was already there is reported.

### The changelog dedupe's join key, and where a class heading is looked for

Internal tracker #684 said the rotation dedupe's summary match cannot fire, because the two records
paraphrase each other. **It was right, and the refutation this repository first wrote was not.** The
triage that filed it argued that §6's line and the changelog bullet are written from the same
`summary` in one pass, so they match by construction, and put the reporter's divergent pairs down to
older writers or hand edits. The first draft of this subsection repeated that. The reporter's history
shows one stock close, on the current writers, writing both records for the same task with the
bullet reworded. The writer is an agent composing two lines, not a template filling one field twice.
**Neither key finds every record on its own.** A later stock close wrote three bullets titled in
prose, with no task id and reworded summaries, so the id search finds nothing for them, and the
summary search finds nothing either. So the runner runs both searches for every line and reads every
hit, since an id mentioned inside another entry's prose looks like a hit; and the rule's last clause,
write what neither search finds, turns a miss into a visible duplicate rather than a silent loss.
**The bullet shape now carries the entry's task ids and the doc's `summary` as written**, so records
this workflow writes from here on match on either key. The phase's round 2 had made the id the only
key for a line that has one, which dropped the summary search that finds a bullet with a prose
title; round 3 found both gaps in the reporter's history. **The Consolidation
clause's §6 line is the one rotation meets whose content is already recorded but which has no bullet
of its own**: it summarises many branches, and the clause wrote each one's detail separately. With
no rule for it, it would match nothing and be written back as a bullet pointing at the changelog.

Internal tracker #689 reported `## [Unreleased]` holding `### Changed`, then `### Fixed`, then a
second `### Changed`, and `git blame` showed the lower one was older. A rotation had appended a
`### Changed` at the end of `[Unreleased]`, which is legitimate because Keep a Changelog imposes no
class order. A later close looked near the top, found no `### Changed`, and made another. Both
readings fit "creates what is missing", so the runner now says where *missing* is judged. **The
filing's figures match the reporter's file as of 2026-09-16, and the fork recurred before it was
posted:** the next day a close added another `### Changed` and a merged fix added another
`### Fixed`, which is the five-heading state the check's `WARN:` lines describe.

### What the silent-denial paragraph leaves out

The auto-mode classifier extends protected-branch policy *upstream* from the push to its enabling
commit, when context implies an imminent push. That is why the first `docs(tasks):` commit of a
cycle goes through while the Step 4c consolidation commit hits the same wall as the Step 4d push.

The runner's paragraph is deliberately short: the `PermissionDenied` hook's `additionalContext`
names the specific escape form, and restating it here or in the skill is how the two drift apart.

### Why the runner is told to stay in the main conversation and to close in batches

Both sentences in the opening blockquote come from one consumer's field report (2026-10-12,
maintainer-side, under `tools/`) and this repo's own 30-day transcript measurement on its
production consumer (also maintainer-side). The consumer who wrote the report wrapped
`/claim-task` and `/review-close` in Agent calls: 188 of its 254 agents were launched by other
agents, and the orchestrators then expired their 5-minute subagent cache at every wait on a child,
rewriting ~150k tokens each time — about 39 USD of a 533 USD week, the report's "long foreground commands or its own child agents" bucket (23 USD) plus its "background waits on runtime files" bucket (16 USD), none of
it present on the production consumer, where no Sysop-spawned subagent is nested (six of the project's own research spawns were depth 2) and the
orchestrator sits on the main conversation's 1-hour cache. The batch sentence: 8 of that
consumer's 16 closes carried one branch, at 2.11 USD–17.30 USD each, against 3.57 USD for a six-PR run; the
production consumer spreads 92 closes over 384 merges. The skill never said its cost was fixed per
run, so a standing "close each PR as CI goes green" instruction read as reasonable. Softening
either sentence restores the shape measured; neither changes what a well-placed run does.

To stay under the editor ratchet when the item-3 `direct` arm landed in the published arm's mixed block, an earlier build deleted three clauses of that block's provenance rather than moving them: that the rebase-in-place and throwaway-ref alternatives were both tried and both measured dearer than the merge commit, that the `--no-ff` result was verified side by side on one fixture, and that a branch left at `0 0` was measured so after the merge. They are recorded here so the deletion is not a silent loss.

The same report is why Step 4c's §6 write now creates `PROJECT_STATUS.md` when it is absent (its issue 0004): the runner, finding no file, skipped the write and staged nothing, and item 6 then deleted the pending-docs that held the only copy of the routed summaries.

## The resume under `dontAsk` — provenance

An earlier build made the prepare run headless with no denial; the next did the same for Step 3b onward
and `_shared/main-push-guard.md`'s Rule B. Each replacement is a call a seeded rule admits,
measured by one-call probes (`tools/phase422_probe_log.jsonl`, maintainer-side) and by headless
nights on a trusted consumer. What the runner text no longer says, and why:

- **The AWAITING/STOPPED look is a `find`, not "your Glob tool".** No headless session this phase
  saved had Glob in its tool list (`claude -p`, Claude Code 2.1.310), so the Glob wording left the
  check to judgement: some sessions skipped it, others composed a `find`. The prescribed `find`
  ends its path in `/` so a `sysop/runtime/close` that is itself a symlink is followed (the
  round's lens A: without it, an AWAITING behind a link printed nothing, which reads as none).
- **Condition 3's count goes through `git_ro.py .`** because Claude Code's built-in read-only set
  refuses `git rev-list … --not` under `dontAsk` (probe r06), while the wrapper is admitted by its
  seeded rule. The other two counts have no `--not` and run bare.
- **Step 4a item 1's placeholder refusal.** The retired `case` guard existed because `git rev-parse
  --verify --quiet` exits non-zero and silently both for a ref that does not exist and for a name
  the operator forgot to write out, so an unsubstituted `<branch>` read as `(local-only)` and took
  the in-place rebase that damages a published branch. Measured three ways when it was written:
  published → SHA, local-only → `(local-only)`, `<branch>` unsubstituted → `(local-only)`.
  `git_check.py published` exits 3 on the placeholder itself.
- **Rule B is separate calls and reads the default branch's own ref.** A `test`, an `if`, a `$(…)` and
  a `|| { …; exit 1; }` tail are each denied under `dontAsk`, so the old single block
  could not run. Split into calls, a block's atomicity is gone; steps 2 and 4 therefore read
  `refs/heads/<default branch>`, not `HEAD`, so an actor that switches away and back between
  calls cannot get a commit of its own pushed (the round's lens A reproduced exactly that against
  a first cut that read `HEAD`).

## Known debt

**Both of this section's entries were paid by an earlier build and are kept here as the record of what
was owed.** They read, until then: that nothing in `SKILL.md` pointed at this file so nothing
would ever open it, and that the runner did not say its tail was unprotected.

`SKILL.md` now carries two pointers, inserted whole and reflowing nothing: one under the summary
line, saying this file is the editor's half and is not loaded with the skill; and one under
`## Step 3: Run Verification`, naming `RC-3-1` through `RC-3-8` and telling anyone about to skip,
weaken or reword a rule in that step to read them first. The second also states the limit
directly in the runner — *"the rest of this skill is not covered — do not read the file's
existence as coverage of anything outside Step 3."*

**What is still owed, and it is smaller than what was.** The pointer exists for Step `3` only,
because Step `3` is the only step with declared rules. Every other step gets one as its rules are
declared — a pointer to an empty roster would be worse than none, since it would read as coverage.
