# Task Decomposition Rubric — atomicity, sizing, dependencies, blockers

Canonical rubric for turning a phase of intent into correctly-sized, claimable tasks. Consumed by `/intake` (Step 6, when decomposing the current-focus phase). Also applicable to `/plan-review` — an ad-hoc plan's *decomposition* is reviewable the same way its correctness is, and the adversarial pass has no decomposition dimension today; a future phase may wire it in. Maintain in one place — do not duplicate the calibration into a skill.

> **Calibrated 2026-06-17 from curated exemplars across two real task queues (a large multi-service product queue and a small single-user consumer queue).** A rule is stated below as **promotion-grade** only when it surfaced *independently in both* queues — the same cross-round-survival gate Sysop uses to promote a convention (WORKFLOW.md §5.1). Rules seen strongly in one queue and uncontradicted by the other are marked **candidate**. (These labels grade *the evidence that a rule generalizes* — a separate axis from whether the rubric itself has been wired in and run: the rubric as a whole is **provisional until one real `/intake` dogfood exercises it end-to-end** (Phase 60b), so a rule can be promotion-grade by cross-queue recurrence and still ride on a rubric that's provisional overall.) The archetypes below are generalized shapes, not project identifiers, so they read the same for any consumer.

The four dimensions, in the order you should reason about them: **atomicity** (is this one task?) → **sizing** (`effort` × `blast_radius`) → **dependencies** (`depends_on`) → **blockers** (`user_action`).

---

## 1. Atomicity — is this one task? *(promotion-grade)*

**The litmus: can you state the task's done-condition in ONE falsifiable sentence?** If the honest done-condition needs a bulleted list of independent outcomes, you're holding an epic, not a task — slice it.

- *One task:* "A `parse_<institution>` function turns that CSV shape into ledger entries, with golden tests." · "`pyright` reports 0 errors in the four `Optional*` rules." · "Delete the verified-dead pathname-skip branch from the component."
- *Epic in disguise:* "New table + CRUD endpoints + a composite embed route + a drag/resize grid editor + PNG/PDF export." That's four-plus sentences → four-plus tasks (schema+CRUD / embed render / editor / export).

**The real unit is one coherent, reviewable *surface* — not "as small as possible."** Decomposition cuts both ways, and the skill is knowing which way:

- **Split the incoherent.** A cleanup of 150 case-by-case type fixes scattered across 30 files is not one reviewable PR — slice it by rule-cluster so each slice has a one-sentence done-gate.
- **Lump the cohesive.** Four per-failure-mode validators that are all the same deterministic module are *one* task, not four — splitting them invents seams that don't exist. (A flat fan-out of genuinely-independent template instances — five sibling parsers, each `depends_on: []` — is the *healthy* version of "many small tasks": independent atoms, not an over-split of one thing. Do not manufacture dependencies between them to make the phase "look" structured.)

**Staging is the escape hatch for big-but-coherent work.** When a task is genuinely one surface but large (a deterministic builder subsuming thousands of lines of legacy enrichers), keep it atomic by *scoping itself*: ship two cases now, leave the rest as explicit per-case follow-ups, so the done-condition stays one sentence ("…for cases A and B; all others fall back to the existing path"). Staging-by-scope beats bundling-everything.

Do **NOT** accept these rationalizations for leaving an epic whole:

- *"It's all one feature, so it's one task."* A feature is a unit of *value*; a task is a unit of *review*. One feature routinely spans several tasks.
- *"Splitting it is just bookkeeping overhead."* The overhead is the point — each slice gets its own review, its own done-gate, its own test decision. An un-sliced epic gets reviewed as a blur.
- *"Smaller is always better."* No — *coherent* is better. Over-splitting a cohesive module manufactures integration seams (see §3, the un-owned seam).

---

## 2. Sizing — `effort` × `blast_radius` *(promotion-grade)*

The two axes are **independent**, and conflating them is the most common sizing error. `effort` = **how much work / judgment / risk**. `blast_radius` = **how much surface the diff touches**. A risky 1,400-line refactor of *one* file is `High / single-file`. A two-line dependency bump that ripples through coupled lockfiles is `Low / single-module`.

### Calibration table (generalized archetypes)

| | `single-file` | `single-module` | `cross-module` | `architectural` |
|---|---|---|---|---|
| **Low** | delete a verified-dead branch from one component (+ its test); single commit, no follow-ups | add a parser/handler from an established sibling template (+ golden test + 2-line registration) | a small change that genuinely crosses two layers but is shallow in each | **umbrella/verification-gate whose child tasks all shipped** — residual work is only human dogfooding, but blast tracks the cross-cutting feature |
| **Medium** | (rare) one file, but real internal logic + careful tests | a module with real internal complexity (two entry points over a shared helper; a status state-machine) — no cross-layer reach | a convention declared in the data layer **and** enforced in a hook **and** documented — each piece small, the *spread* is what makes it Medium; or a prompt/config rewrite touching ~15 files in one layer (breadth, not depth) | a schema field that several modules must start honoring |
| **High** | a risky behavior-preserving refactor of one large function, gated on the full regression suite — only one production file changes | build a new sub-package (a new eval harness; a PDF parser pulling a new vetted dependency) — substantial work, one module | the largest category-slice of a cleanup (e.g. ~65 errors across SDK-heavy files); a stage that subsumes thousands of LOC but scopes itself | **establish a cross-cutting contract every component must now emit** (an identity-hash on every parser + a new dedupe layer); a schema migration wired through orchestrator + repository + reader in one PR |

### Calibration rules the exemplars proved

1. **`effort` tracks volume/difficulty at fixed surface.** A cleanup sliced by error-category gives a controlled series: ~7 errors → `Low`, ~45 → `Medium`, ~65 → `High`, all the *same* `cross-module` (or `single-module`) blast. Same shape, effort scales with count.
2. **What bumps `single-file` → `single-module`: coupled files, not edited files.** A file **and its test** is `single-file` (one logical artifact). A change that *must* touch a source file plus its two generated lockfiles together is `single-module` (several coupled artifacts). Trivial registration edits (adding a line to an `__init__` and a dispatch table) do **not** promote a parser past `single-module` — they're mechanical, not logic spread across layers.
3. **Intrinsic difficulty raises `effort`, never `blast_radius`.** "This is hard" (PDF table extraction; a 1,400-line untangle) stays `single-file`/`single-module` if the diff stays there. Resist letting difficulty inflate the surface.
4. **Breadth raises `blast_radius`, not necessarily `effort`.** A prompt rewrite touching 15 files where each edit is mechanical is `Medium/cross-module` — wide but shallow.
5. **The paradox cell `Low/architectural` is real and useful:** an umbrella that's done-except-for-human-sign-off. Effort is Low because the code landed; blast is architectural because the task *tracks* a cross-cutting capability. Pair it with `user_action: true` (the sign-off is the human's).

Author **both** fields on every emitted task even at `schema_version: 1`. Sizing is a judgment call that sharpens with practice; the table is a starting calibration, not a lookup.

---

## 3. Dependencies — `depends_on` is physical impossibility *(promotion-grade)*

`depends_on` encodes **true ordering**, not topical relatedness. The test: **can B start before A finishes?** If yes, B does **not** depend on A — even if they're about the same feature, even if they touch the same file.

- **A true edge** means B's *primary artifact or contract cannot exist* until A lands: a config gate-flip that physically cannot land until a backlog count hits zero; a wiring task that cannot wire stages that don't exist yet; a UI that dispatches to the parser function its predecessor creates.
- **"Needs the same file" is NOT an edge.** Two tasks that both extend a shared module, but whose logic is orthogonal, have *no* edge between them. Resolve the shared artifact with a **body convention** ("whichever of these ships first creates the shared module; the second extends it"), not a fake `depends_on`. A fan-out where four tasks each depend on one root but **not on each other** is a star, not a chain — model it as a star.
- **`surfaced_by` ≠ `depends_on`.** When an umbrella task *spawns* rule-cluster children, the children carry `surfaced_by: <umbrella>` (provenance — "this is where I came from") but **not** `depends_on`, because they can start independently. Using `depends_on` for provenance is a vibe-dependency; the two fields agreeing (a follow-up that's both spawned-by and truly-ordered-after its predecessor — e.g. "rename-for-disambiguation can't happen until the second sibling exists") is a health signal, not the default.

**The un-owned seam — the most dangerous decomposition failure** *(**candidate** by evidence — it surfaced in one queue — but stated firmly because it holds by construction, not by frequency: split a capability so that no slice owns the seam and it cannot connect, however many queues you check).* When a single user-observable capability is split across N tasks, **exactly one task's done-condition must include the integration that makes the capability observable.** The cautionary shape: a matcher task and a capture-UI task both close `done` — and the feature is non-functional, because the wire-up between them belonged to *neither*, and was discovered later as a bug. If you split "build the part" from "build the other part," name the task that owns "wire them together so the user sees it" — or fold the wire-up into one of the two's done-condition.

Do **NOT** accept: *"they're both about feature X, so the later one depends on the earlier"* (relatedness ≠ ordering) · *"they touch the same module, so I'll chain them"* (shared file → body convention, not an edge).

---

## 4. Blockers — `user_action` is a human-only *action*, not uncertainty *(promotion-grade)*

`user_action: true` means **some gate step requires a surface only a human can reach**: a cloud console / IAM / secret provisioning; rotating a leaked key in a vendor's account console; standing up a tunnel and registering an external connector in a third-party UI; a go/no-go judgment at a rollout boundary; supplying private domain data that lives only in the user's head or their private files.

Three properties the exemplars established:

1. **It's a step-property, not a task-property.** The flag fires if *any* gate step is human-only, even when most of the task is agent-executable (a cleanup that's all code except the one console key-rotation). When `true`, write the steps under a `## User ops (do these first)` body section.
2. **It's a gradient with a hard floor.** Strong: provision cloud IAM, rotate a key in a vendor console, register an external connector. Legitimate-but-softer: "only the user knows their actual spreadsheet categories / which dump folder is canonical" (private knowledge the agent cannot obtain — still genuinely human-only). The floor is the canonical **mis-flag**:
   - **Research-uncertainty dressed as a blocker.** *"The fix needs research into the file format — read the three sample files and work out the row-identity scheme."* That is analysis the agent can do. It is **not** a human-only action. Marking it `user_action: true` is the exact anti-pattern. (Resolve the research now during planning, or file it as an ordinary task — don't park it behind a human.)
3. **"Needs a human" ≠ "needs to wait."** An experiment that must wait for a low-traffic window or an upstream GA date is an `on_hold_until` (timing), not a `user_action` (human action). Keep the two distinct — a task can have either, both, or neither. (A task can also be *blocked because it isn't decomposable yet* — that's neither flag; see §5.)

Do **NOT** accept: *"I'm not sure how to build this, so it needs the user"* — that's a planning gap to close now, not a blocker. *"The user should confirm the approach"* — a preference question is a quick conversational turn, not a `user_action` gate.

---

## 5. Quick anti-pattern checklist (the smells)

When you've drafted the slice, scan it for these — each maps to a section above:

- **Epic-as-task** — done-condition needs a bulleted list of independent outcomes. → §1, split.
- **Over-split cohesive work** — four tasks that are obviously one module, or a manufactured dependency chain across genuinely-independent siblings. → §1, lump / flatten.
- **Difficulty inflating surface** — a hard task marked `architectural` when its diff lives in one module. → §2.3.
- **Mis-sized effort** — `Low` on a task whose `## Work` lists a migration + a multi-function refactor + a new endpoint. → §2.1.
- **Vibe-dependency** — `depends_on` where B could start before A finishes, or `depends_on` used for provenance. → §3.
- **Un-owned seam** — a multi-task capability where no task's done-condition owns the user-visible wire-up. → §3.
- **Research-as-blocker** — `user_action: true` whose justification is "needs investigation." → §4.2.
- **Vagueness-parked deferral** — a deferred task with no statable done-condition ("scope TBD"). That's planning debt, not a backlog item: either decompose it to a claimable atom or record the concrete blocker + a revisit trigger (the well-parked shape carries a full mini-spec + a "when to revisit" condition). → §1 litmus, applied to the parked queue.

**Two independent quality axes, never conflated:** a task body can be richly documented *and* badly decomposed (a beautifully-written epic is still an epic). **Judge the slice, not the prose.** Conversely, terse is fine if the slice is clean.

---

> **Provenance.** Derived in Phase 60b from curated, cross-queue-surviving task exemplars. Cross-queue survival is the promotion gate (mirroring Sysop's own convention-promotion semantics, WORKFLOW.md §5.1): a sizing or dependency rule earns "promotion-grade" only by appearing independently in two unrelated real queues. The generalized archetypes replace the project-specific task IDs they were distilled from, per the no-project-identifiers authoring rule.
