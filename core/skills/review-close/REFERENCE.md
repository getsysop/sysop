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

**Coverage is one step, and one part of it.** Only Step `3` is declared today, and only six of
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

**The three-dot diff rule.** `git diff --name-only <base>...HEAD` uses three dots, always; two
would render everything the base gained since a branch was cut as though the branch deleted it.
This changes a verdict — it corrupts the changed-file list every narrowing decision reads — but
it lives in a **shell comment inside a fenced block**, and the pin's canonicaliser strips fenced
text before comparing. It therefore fails roster check (a) and cannot be declared under the
current mechanism.

**The `NO_ORIGIN_MAIN` sentinel, same reason.** `RC-3-2` depends entirely on the runner printing
`NO_ORIGIN_MAIN` when the changed-file list cannot be computed, and the `|| echo "NO_ORIGIN_MAIN"`
that produces it is inside the same fence. A round deleted it and the pin stayed green while the
prose above still said *"If it prints `NO_ORIGIN_MAIN`"* — the rule's own trigger removed, its
statement intact. (A pre-existing guard elsewhere in the suite does catch this one; the pin does
not.)

Both are recorded here because they are the campaign's standing evidence that the fence question
has to be settled before a command-heavy step is pinned.

## Declared limits of this mechanism

Stated so the file cannot be read as more coverage than it is. A round established each of these
by demonstration, not by argument.

- **Nothing outside Step 3 is screened.** A sentence contradicting one of these six rules,
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

---

## Known debt

**Nothing in `SKILL.md` points at this file, so nothing will open it.** Claude reads a skill's
supporting files only when the skill body names them, and the on-demand pointer — *"if you are
about to skip or weaken this step, read `REFERENCE.md` § `<rule-id>`"* — is not installed. The
phase that introduced this file deliberately made no edit to `SKILL.md`. **Installing that
pointer is the first edit of the first thinning phase, ahead of moving any text**, because until
it exists this file's zero runner cost is the trivial kind: it costs nothing because it is never
read.

**The runner does not yet say that its tail is unprotected.** The unguarded majority of the skill
should declare itself as such in `SKILL.md`. The phase that introduced this file deliberately made
no edit to `SKILL.md`, so that sentence is owed by the first thinning phase. Until then, this file
is the only place the limit is written down.
