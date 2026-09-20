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

## Where new rationale goes

**New rationale is authored here, not in the runner.** When you add a rule to `SKILL.md`, the
runner gets the instruction and — only if it changes what the runner does — one line of reason.
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

Until Phase 241 the escape hatch — *if any convention names documentation, config, prompts,
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
debt Phase 203 measured at 30 of 36 sections binding nothing. The twin becomes as sharp as the
consumer's map is localized, and the runner's obligation is only to say which case it was.

### Why the security sources are written once, and the draft that measured nothing

This step's first draft said *"paste or write-once, on step 1's threshold"* and told the runner to
*"measure the two security sources the same way step 1 measures the convention set"* — which is
prose with no command behind it. Step 1's shipped measurement reads section headings out of a
consumer's project instructions and has no analogue for a map file. The same filing that widened
step 1's paste had forbidden widening a paste without measuring it, and this step introduced a new
paste in the same edit without applying that discipline to itself. Measured afterwards:
`.claude/security_map.md` on a fresh `--packs python` install is **12,828 characters**, above the
10,000 threshold — so the inline arm is unreachable on a stock install and the write-once arm is
the live path. The runner is still told to measure rather than assume, because a consumer who trims
the map can fall below.

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

**Two of those three links are closed, and the record has to say which.** Phase 158 (`d955aa0`)
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
when it was written and has been false since Phase 158 — it named the two steps that had just been
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

`sysop/runtime/` is Phase 133's single runtime home, and `install.sh`'s `ensure_runtime_gitignore`
appends the entry when missing and runs unconditionally in both modes and on `--update`, so a
consumer has it. **It is not there to stop the file reporting itself** — it cannot do that in
either location, because `>` creates the file before `git status` runs, so the file appears in the
baseline *and* in the comparison and cancels out. The reason is downstream: an untracked artefact
at a tracked path shows up in the operator's own `git status` for the rest of the close, and is
reachable by a later `git add`.

### Why the fifth assertion command gets its own line

The pinned checkouts live outside the repository by design, so they never appear in the third
command's `git status` delta and never reach `.claude/worktrees/` for the first. The only handle on
them is `git worktree list` — which is why they get their own line rather than riding one of the
existing four, and why a reader who expects four commands to cover five populations is wrong about
the third one in particular.

## Step 2d — provenance

Editor-addressed history for `### 2d. Test-Decision Verification`. Nothing here binds the agent
running the skill; it is why a rule in that step is shaped the way it is, so that an editor
changing one knows what the shape was bought with. Authored, not copied — the runner keeps the
rule, this keeps the argument.

### What this gate replaced, and why reading the right revision is the whole of it

The test-decision convention arrived in Phase 58b. For a long stretch afterwards a second thing
claimed to enforce it and did not: `validate_tasks.py` carried a warn-only Invariant 13 on the
same fact, and it read the body **off the working tree** while the record lives on the branch. So
it warned on every claimed task on every run and told the reader nothing — a check whose output
is constant carries no information, whatever its subject. Phase 234 retired it and left this step
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

`/auto-build` belonged on the non-writing list until Phase 277 and was its worst member. It claims
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

**The damaging direction is the undercount.** `## Also fixed` lines per branch is one of the three
numbers the fix-in-branch tier is judged on, so too few lines reads as the tier sitting comfortably
inside a bound it may already have left. That asymmetry is why the runner is told to search rather
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
prevents — and it stayed wrong as an instruction even after `Q-468` closed it, because a rule held
only by pointing at another skill's code moves when that code does. Both of `/claim-task`'s walkers
now delegate the closer decision to one `fence_closes` predicate per block, defined once per
heredoc since nothing is shared across them, and cited at two lines that cannot be swapped for one
another: the writer's clause explaining why its own openers carry info strings, and the clause in
the verifier itself. `fence_mark` still reports only that a line **is** a marker, which is the
distinction that made the defect possible.

### Why the info-string clause is load-bearing

The reachable window is narrower than it first looks, and worth knowing. A *balanced* nesting
inverts the model twice and cancels, so only a heading sitting **between the info-string line and
its matching closer** is exposed. Verified by execution in both positions. A live consumer body
carries the nesting — one in 912 bodies, scanned — so the window is reachable on real input rather
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

---

## Step 4-pre — provenance

### Why the integration branch is cut from the local default branch, and never from `origin/<default branch>` plus a cherry-pick

Until Phase 304 this step cut the integration branch from `origin/<default branch>` and then swept
the local-only `main` commits onto it with `git cherry-pick origin/<default branch>..<default branch>`.
That cherry-pick **rewrites** the commits, so neither the rollback nor the re-claim remains an
ancestor of anything a feature branch knows, and the merge-base between the integration branch and
an approved branch collapses to `origin/<default branch>`. Step 4a's three-way merge then resolves
the task index against a base that has never seen the claim flip.

**Which arm, because the scope is the thing an editor prices a change with.** This reaches Step 4a's
**published** arm (`git merge --no-ff`) and **not** its local-only arm. The local-only arm rebases,
and a rebase replays each commit's *patch* against its real parent: the branch never changed
`status:`, so there is no status hunk to replay and the collapsed merge-base is never consulted.
Measured both ways. **Phase 304's first record claimed the population was every approved branch cut
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

**Measured, Phase 304**, over a fixture matrix of four branch-edit shapes × two base states:

| shape (Step 4a **published** arm) | merge-base | base current | merge | `status:` after |
|---|---|---|---|---|
| `origin/<default branch>` + cherry-pick | collapsed | yes | CLEAN | `open` — **reverted, 8/8** |
| cut from the local default branch, then merge `origin/<default branch>` | preserved | yes | CLEAN | `in_progress` — **correct, 8/8** |

In all eight of the fixed rows the branch's own work survived and, where `origin/<default branch>` had advanced
mid-run, the upstream commit survived too — so the property that motivated cutting from
`origin/<default branch>` in the first place (the PR's checks run against the current base) is kept
by the `git merge origin/<default branch>` that follows, not lost.

**Two claims in the filing that the measurement corrected.** `Q-521` stated four conditions "all
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
second therefore reproduces nothing, and reports a clean pass. Phase 303's adversarial round ran
exactly such a script, concluded the defect was irreproducible, and was wrong; two of the author's
own attempts died the same way. Any test or fixture in this area must force distinct committer
dates (`GIT_COMMITTER_DATE`) and assert on the merge-base, not only on the merge's exit status.

### The Step 4c containment false positive the swap removed, and what the figure actually is

Step 4c step 1b's `git rev-list --count "<branch>" "^HEAD"` is an ancestry test. Until Phase 304,
Step 4-pre cut the integration branch off `origin/<default branch>` and swept local-only commits
across with `git cherry-pick`, which rewrites them — so a pending doc whose frontmatter is
`branch: <default branch>`, which `/document-work` writes whenever it runs on the default branch,
scored non-zero and was classified `NOT-MERGED` on **every** `pr`-policy close, while its content
was provably in the merge target. Cutting from the local default branch makes its tip a real
ancestor, and the same doc scores `0`.

**The figure, stated the way it is actually true.** The count before is *however many local-only
default-branch commits the tree has*, not a constant: on the phase's own test fixture, which
carries two (the rollback and the re-claim), it is **2 → 0**; on a one-commit fixture it is
**1 → 0**. Phase 304's first record published *"one local-only `main` commit: `1` before, `0`
after"* as though it were one measurement, and its round found the two fixtures disagreeing — the
shipped sentence cited the one-commit number while the in-tree test used the two-commit fixture.
The guard asserts only that the before-count is non-zero and the after-count is `0`, which is the
part that generalises.

### The permission rules the swap moved, and the one it silently removed

Retiring the cherry-pick moved this step's whole permission footprint, and Phase 304's first cut
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
  resolved merge needs a `git commit` that matches only `Bash(git commit -m docs:*)` — so a
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
prescriptive with none.** Step 3c's shipped reader now handles all four by skipping —
`if not fm_m: continue`, `except yaml.YAMLError: continue`, `if not isinstance(fm, dict):
continue`, and `errors="replace"` on all four reads in that heredoc — and it did
not before the phase that wrote arm 3: a reviewer ran it and watched a non-mapping frontmatter and
a non-UTF-8 doc each kill the close with a traceback at a step that runs *before* this one, which
would have left arm 3 unreachable for those shapes. Arm 3 is what makes the two readers agree —
except that quarantining beats Step 3c's silent skip, because a skipped doc is invisible and a
quarantined one is reported with its bytes on disk.

### Why the Phase 23a fallback is still here, and when it goes

The fallback covers in-flight pending-docs authored before the `task_ids` → `roadmap_ids` rename
(Phase 23a). Treating ids read through it as `roadmap_ids` matches the pre-rename consumer
behaviour: Step 4c's heredoc was already treating them as roadmap ids, silently no-op'ing on the
non-matches.

**Removal trigger.** Drop the `or pending.get('task_ids')` clause in any subsequent phase that
touches Step 4c, once BeanRider has run one full `/review-close` cycle on a pending-doc authored
after the 23a absorption — confirmable via `git log -p sysop/runtime/pending-docs/` or via the
merged consolidation commit. Pending-docs are minutes-to-hours lived, so the shim's exposure window
is one absorption cycle.

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

Until Phase 219 this heredoc printed nothing, while Step 8 asked it for three values — so the
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

### What the silent-denial paragraph leaves out

The auto-mode classifier extends protected-branch policy *upstream* from the push to its enabling
commit, when context implies an imminent push. That is why the first `docs(tasks):` commit of a
cycle goes through while the Step 4c consolidation commit hits the same wall as the Step 4d push.

The runner's paragraph is deliberately short: the `PermissionDenied` hook's `additionalContext`
names the specific escape form, and restating it here or in the skill is how the two drift apart.

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
because Step `3` is the only step with declared rules. Every other step gets one as its rules are
declared — a pointer to an empty roster would be worse than none, since it would read as coverage.
