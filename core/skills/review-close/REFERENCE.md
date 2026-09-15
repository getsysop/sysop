# `/review-close` — editor reference

**You are reading this because you are about to change the skill, not run it.**

`SKILL.md` is the runner. It carries procedure, commands, and a one-line reason wherever the
reason changes what the runner does. This file carries what the *editor* needs: what a rule
protects, what its loss or softening would change, and where it came from.

Claude Code does not load a skill's sibling files automatically — they are read only when
something points at them — so this file costs the runner nothing and the editor pays for it once.

Notes here anchor to **rule ids and step headings, never line numbers.**

The method behind the declaration below, and the pin that enforces it, are specified in
`tools/CONTEXT_THINNING_SPEC.md` (maintainer-side; never ships).

---

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
its rules. The other six declared steps (`4c`, `4b`, `4a`, `3b`, `1a`, `2d`) and the whole tail of
the skill ride **unprotected**. Do not read the presence of this file as coverage of the skill.

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

**Provenance.** Phase 170 — the phase that moved the verifying gate to `4a-post` and made Step 3
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

**Provenance.** Phase 170.

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

**Where it came from.** Internal tracker #241, Phase 158, which rebuilt Step 2's diff basis for
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

**Empty since Phase 291, and the reason is the point.** This section carried two entries — the
three-dot diff rule and the `NO_ORIGIN_MAIN` sentinel — and both were blocked for the same
mechanical reason rather than any property of the rules: they live in a shell comment and a
command inside Step 3's fenced block, and the pin's canonicaliser deleted fenced text before
comparing. They were recorded here as *"the campaign's standing evidence that the fence question
has to be settled before a command-heavy step is pinned"* (`Q-457`).

That question is settled. The canonicaliser now **tags** wrappers instead of deleting them, so a
rule inside a fence is pinned while moving a rule into one still fails the pin as a change. Both
rules are declared above as `RC-3-7` and `RC-3-8`.

**One correction the settlement turned up, which this section had overstated.** The entry for the
three-dot rule described it as unguarded. Its *verdict-changing* failure mode — two dots in the
operative command — was already caught by `tests/test_review_close_diff_basis.py`, which scans
the raw shipped text (fences included) against a whole-line allowlist. Measured four ways against
**that scanner** before `Q-457` was settled: the two-dot regression is **caught**; deleting the
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
  re-indent of a step is refused — but a single indented rule is not. No general detector is
  built because 68 of the 69 deep-indented lines in `SKILL.md` are list continuations, so one
  would mis-tag them to catch this. Filed as `Q-497`.
- **A declared rule can be retired in three edits, not the eight this section used to imply.**
  Measured by a round: re-point the rule's subject pattern at another sentence of the same step,
  delete the rule, regenerate the block pin. The roster, the section and `DECLARED_IDS` stay
  untouched. `SUBJECT_QUOTES` now pins what each pattern must match, so the re-point has to
  replace the rule's own words and the diff says which rule left — it does not make retirement
  impossible, it makes it legible.
- **A re-wrap inside a prescribed command block reddens the pin.** Shell comments are tagged,
  not deleted, so their line breaks are inside the pinned text: re-wrapping a comment block
  moves the `#` prefixes and the pin fails as a change. That is the cost side of `Q-457`'s
  settlement and it is deliberate — the alternative is the comment being invisible again — but
  it is a real innocent edit going red, and `Q-458` is the open entry that prices it. Ordinary
  prose and blockquotes are reflow-invariant; command-block comments are not.

---

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
written against. Everything after it rewrites history — Step 4-pre rebases or cherry-picks, and
Step 4a may squash — and each of those orphans the commit the document recorded. Step 4c, where
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
into a single outcome that says nothing.

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

## Known debt

**Both of this section's entries were paid by Phase 293 and are kept here as the record of what
was owed.** They read, until then: that nothing in `SKILL.md` pointed at this file so nothing
would ever open it, and that the runner did not say its tail was unprotected.

`SKILL.md` now carries two pointers, inserted whole and reflowing nothing: one under the summary
line, saying this file is the editor's half and is not loaded with the skill; and one under
`## Step 3: Run Verification`, naming `RC-3-1` through `RC-3-8` and telling anyone about to skip,
weaken or reword a rule in that step to read them first. The second also states the limit
directly in the runner — *"the rest of this skill is not covered — do not read the file's
existence as coverage of anything outside Step 3."*

**What is still owed, and it is smaller than what was.** The pointer exists for Step `3` only,
because Step `3` is the only step with declared rules. The other six steps the method selects
(`4c`, `4b`, `4a`, `3b`, `1a`, `2d`) get theirs as they are declared — a pointer to an empty
roster would be worse than none, since it would read as coverage.
