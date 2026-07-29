<!-- sysop:model-roles inline=reasoning -->

# Adversarial Plan Review — Shared Prompt & Classification

Canonical adversarial-review prompt template + finding-classification rubric. Consumed by `/claim-task` (Step 7) and `/plan-review` (Step 3). Maintain in one place — do not duplicate across skills.

## Caller contract

The caller (top-level skill OR a future top-level orchestrator) spawns the Agent tool with:

- `subagent_type: "general-purpose"`
- `model: "opus"` (always — fresh reasoning on code is worth the cost)
- `description: "Adversarial plan review"`
- `prompt`: the full `PLAN_TEXT` verbatim, followed by the **Prompt Template** below.

The sub-agent returns a prioritized list of concrete issues with `file:line` evidence, under 500 words. The caller then classifies each finding per the **Classification Rubric** below.

**Optional `SPEND_USD:` directive.** If the consuming project wires up a parser for sub-agent cost attribution, the caller MAY require the sub-agent to emit `SPEND_USD: <float>` on a line BEFORE the findings list (uncomment the corresponding line in the Prompt Template). If the directive is absent from the response, treat spend as unreported — do NOT fail the review on a missing line.

## Running more than one reviewer

A substantial change usually wants several reviewers on distinct lenses (e.g. *does it execute* / *are its claims true* / *are its tests real*). **Assign each a different lens** — redundant reviewers do not vote independently, they share a blind spot and ratify each other. **Never forks:** a fork inherits the author's reasoning, reintroducing the correlated error the whole step exists to remove. (Portability: fresh context is the requirement, not any particular spawning mechanism; see § Harness constraint for consumers whose agent cannot spawn at all.)

**Commit before the round starts.** The one rule that holds on every harness, and the one that makes everything below recoverable: a round that begins on a dirty tree can lose work no reviewer intended to touch.

**Reviewers must not mutate the working tree** — no `git checkout`, no branch switch, no staging, no stash. Say so in the prompt. "Read-only lens" is an *intention*, not a constraint: a reviewer that decides to compare two revisions will reach for `checkout` unless told otherwise, and in a real round one did exactly that, moving the tree off the branch under review while two siblings were still reading it. Their later reads silently described the wrong revision. Instead, have reviewers compare with `git show <sha>:<path>`, which reads the object database and is unaffected by tree state — and have each one verify **at the start** that the revision it is reading actually contains the commits under review.

**Worktree isolation, where the harness offers it.** Claude Code's Agent tool takes `isolation: "worktree"`, giving a reviewer its own checkout. Two caveats, both paid for:

- **It does not guarantee the revision you expect.** In one round two reviewers spawned together landed on *different* commits — one of them the pre-phase tip, so that reviewer's first findings described code the phase had already changed. Isolation removes the interference; it does not remove the need to check what you are reading.
- **Do not use it where a worktree already exists.** `/claim-task`, `/auto-build`, `/auto-fix` and `/auto-judge` spawn agents into a worktree an earlier step created, and each says "Do NOT set `isolation: \"worktree\"`" for that reason. This section is about an **ad-hoc review round with no pre-existing worktree**; it does not override those instructions. Where the harness offers no isolation at all, the commit-first + do-not-mutate + `git show` rules above are the portable form and are sufficient.
- **Shipped steps meet that description too, and one of them now sets isolation for exactly the reason above.** `/review-close` Step 2b spawns its convention reviewers into the user's **primary** worktree while a close is mid-flight, with no worktree of their own; an agent there once ran `git checkout` and moved `HEAD` off the integration branch (upstream #234) — the same failure this section records from an ad-hoc round, in shipped code rather than a maintainer's session. The `/codebase-review` and `/security-audit` fan-outs have the same shape (primary worktree, no worktree of their own) and the same exposure, so the rules above apply to them whether or not their prompts repeat them.

**Never weight findings by how many reviewers agree.** In the same round, one reviewer confirmed a finding that another disproved by reading the document that *governed* the behaviour — the lone dissenter was right. A majority that checked the surface loses to one reviewer that read the spec.

**A confirmed premise is not a confirmed conclusion.** "The two lists really are asymmetric" does not establish "the asymmetry is a bug." When a reviewer ratifies a finding, check which half they verified — this is the shape that lets a *fabricated* finding survive a review round. It is the confirming twin of the **compound-findings rule in § Classification Rubric** below, which covers the same error in the rejecting direction, and of `_shared/fanout-evidence.md` § *Adjudication* (Phase 141).

The caller still verifies every surviving finding itself — see the Classification Rubric. Reviewers are the adversary, not the authority.

## Prompt Template

Append the following text verbatim after `PLAN_TEXT`:

> Adversarially review this plan. You are a skeptical senior engineer with zero context from the planning session. Your job is to find what's wrong, not to compliment what's right.
>
> **Verify every file and line citation by actually opening the file.** Do not trust the plan's characterization of existing code — re-read it. Run Glob/Grep/DB queries to verify factual claims.
>
> Specifically flag:
>
> 1. **Mis-cited patterns** — "matches the pattern at foo.py:123" when foo.py:123 actually does something different.
> 2. **N+1 query patterns** — helpers called per-loop-iteration that should be hoisted to a single upfront call with in-memory intersection/lookup.
> 3. **Silent failure modes** — engine null guards returning empty collections instead of raising; upserts that can overwrite good data with empty/missing values; try/except swallowing the exact error the fix is meant to surface; fallbacks that substitute a default/empty/mock value without surfacing the failure (a mock or stub fallback reachable in production code is an architectural flag, not a convenience); retry logic that exhausts its attempts without logging, alerting, or raising; optional-chaining / null-coalescing / `.get(key, default)` that silently skips an operation that can fail.
> 4. **Asymmetric retry/error handling** — existing code path has retry logic and the new parallel path added by this plan does not (or vice versa).
> 5. **Factual drift** — counts, IDs, section numbers, file paths, line numbers that do not match current state.
> 6. **Convention mis-application** — plan cites a convention from CLAUDE.md § Prevention Conventions but applies it incorrectly.
> 7. **Missing invariant tests** — load-bearing guards or invariants with no regression test. **Consult the plan's `## Test decision` record** (the task body's plan-time decision — Phase 58b): this dimension is the *review-time scrutiny* counterpart to that *plan-time recording*, so scrutinize the recorded decision rather than re-making it. If it records `no test because <Z>`, judge whether `Z` is *sound* (pure rename/move, config/docs-only, a path an existing named test already covers, a `manual_smoke:`-only behavior) — don't flag the mere absence of a test. Flag when `Z` is a hand-wave ("will add later", "too hard to test"), when a load-bearing invariant has neither a test nor a sound recorded rationale, or when the `## Test decision` section is missing entirely on a behavior-touching task.
> 8. **Missing or empty `## Constraints & Risks` preamble** — the plan must include a `## Constraints & Risks` section as the first content block after the task summary, before any `## Implementation Steps`, with one bullet per touched file/directory citing applicable conventions from both maps. A boilerplate-only section (e.g., generic phrases without per-file bullets) counts as missing.
> 9. **Unverified external SDK/framework calls** — any call to an external library, SDK, or framework method (an LLM provider SDK, a cloud client, a web-framework API) that the plan neither backs with an **in-repo precedent** (an existing same-project call site using that method the same way, cited `file:line`) nor marks **`unverified — no in-repo precedent`**. External APIs drift — methods get renamed, removed, or change signature between releases, so a plan written from memory may cite a surface that no longer exists. **The bar here is *cite a precedent or flag it*, not *verify against live docs*** — you may have no web access at plan time, and a static "which APIs are real" list would rot the instant the SDK ships a release. Do NOT accept these rationalizations for skipping the citation: *"the SDK is well-known, the method must exist"* · *"I've called this before"* (recalled from memory ≠ found in this repo) · *"the signature probably hasn't changed"* · *"types/autocomplete would catch it"* (there is no execution or type-check at plan time) · *"it's close enough to the documented shape."* An external call that is neither precedent-cited nor flagged `unverified` is the finding.
>
> <!-- Optional — uncomment if the project tracks sub-agent spend:
> Emit `SPEND_USD: <float>` on a line BEFORE the findings list.
> -->
>
> Do NOT rewrite the plan. Do NOT suggest stylistic improvements. Return a prioritized list of concrete issues with `file:line` evidence. Where one issue asserts several independent claims or spans several sites, enumerate each claim/site explicitly (a terse `file:line` comma-list suffices — enumeration must not crowd out analysis) — findings are adjudicated clause-by-clause, so an unlisted clause is a clause the classifier can silently drop. Under 500 words.

## Classification Rubric

The caller classifies each returned finding as exactly one of:

- **`fixable`** — the planner can revise the plan inline to absorb the finding without needing human input. Mis-cited patterns, convention mis-applications, factual drift, missing tests, formatting drift, N+1 patterns, asymmetric error handling — all `fixable`. Action: incorporate the fix into the plan and continue. If a finding is rejected after consideration, document the rejection rationale inline in the plan (`> **Adversarial review rejected:** <finding>. Rationale: <why>.`) so the same issue does not resurface during human review.
- **`blocker`** — requires human input the agent cannot produce. Ambiguous requirements, missing source data the task body assumes, conflicting goals between Constraints & Risks and Implementation Steps, scope questions where neither code-reading nor revising would resolve them. Only mark as `blocker` if the planner has genuinely tried to resolve by reading more code and revising the plan, and the gap is still load-bearing for execution. Action: halt — do not call `ExitPlanMode`, do not execute, surface the question to the human.

**Compound findings — decompose before rejecting.** Many findings assert **multiple independent clauses** or cite **multiple `file:line` sites** under one heading. Before classifying such a finding, split it into its clauses and adjudicate each one separately: **refuting one clause does not reject the finding.** The surviving clauses are classified on their own merits, and a rejection rationale must name *every* clause and why each fails — not just the one disproved. This failure mode is measured and directional: partial refutation only ever turns a *real* finding into an apparent false positive, never the reverse, so every shortcut here is a lost real issue. In the 2026-07 cross-model review comparison that motivated this rule, half the audited dismissals were partial refutations concealing a real finding — one of them a High-severity security issue — and a same-family adversarial re-check ratified every dismissal; what recovered the dropped clauses was a re-adjudication constrained to **trace every cited site** rather than judge the finding as a unit. Apply the same recovery discipline: when rejecting a High-severity or security-relevant finding, have a **second, independent pass — fresh context at minimum, a different reviewer where available — re-adjudicate the rejection clause-by-clause** before it stands. (Portability: fresh context is the requirement; a different model family sharpens the check when the consumer has one, but is never assumed.) **Where the current shape cannot spawn that pass** — the reviewer-executor leaf self-classifies and must not nest; a bash-installer consumer's agent may have no spawning at all — **do not silently absorb the rejection**: record the full per-clause rejection rationale in the sealed report / plan so the next reader with independent context (the parent, the human at plan approval, the review-close gate) adjudicates it. The unsatisfiable form of this rule is "a second pass or nothing"; the portable form is "a second pass where possible, a loud per-clause record where not."

If the sub-agent returns no findings, the planner records `Adversarial review: no blockers found` explicitly in the plan so future reviewers know the step ran and came back clean.

## Harness constraint — orchestrator-spawned sub-agents

> **History:** through Claude Code 2.1.171 the harness blocked recursive Agent tool spawns — a sub-agent spawned by another sub-agent did NOT have Agent in its tool set, even when the `general-purpose` agent type advertised `Tools: *`. **Claude Code 2.1.172 (2026-06-10) lifted this:** sub-agents can now spawn their own sub-agents, up to 5 levels deep (hard server-side cap, no config). The official docs lagged the release; the changelog is ground truth.

The orchestrator-driven split below is **retained deliberately**, not out of necessity:

- **Top-level sessions** (a human running `/claim-task` or `/plan-review` directly) → Agent IS available; spawn the adversarial reviewer as described above.
- **Orchestrator-spawned sessions** (an agent spawned by `/auto-build` or similar) → do NOT spawn nested agents even where the harness now permits it; the orchestrator runs the plan + adversarial review at its OWN top-level layer, then feeds the absorbed plan into the execution agent.

Why retained: (1) the Phase 37 `SubagentStop` envelope contract (`parse_subagent_envelope.py`) was validated for direct children only — nested spawns would fire the hook for grandchildren with undocumented event routing relative to the parent's Agent-tool return; (2) Sysop's bash-installer consumers run on agents with no nesting support at all, and the orchestrator-driven shape is the portable one; (3) the capability is brand new and unproven on a real consumer. Re-evaluate via the nested-reviewer experiment tracked in Sysop's development roadmap (Medium priority, filed 2026-06-10) once 2.1.172+ has stabilized.

## Reviewer-executor variant — `/claim-task` Step 7

`/claim-task` collapses adversarial review + classification + plan revision + implementation + post-fix gates into a single "reviewer-executor" sub-agent (see `claim-task/SKILL.md` § Step 7). The variant is interactive-only — a human is at the keyboard waiting on the parent — and it differs from the `/auto-build` two-phase (reviewer Phase 6b/6c → executor Phase 6e) shape in three ways:

- **Self-classifies findings.** The reviewer-executor applies the **Classification Rubric** above to its own findings instead of returning raw findings for a separate classifier. The parent does NOT classify between two sub-agents.
- **Sealed `REVIEW_REPORT:` YAML at the TOP of its response.** The sealed report precedes any implementation discussion. It acts as a commitment device so findings cannot be silently softened by the same agent during implementation. Format: `findings:` (list of `{id, classification, summary, response}`) and `verdict: PROCEED | BLOCKED`.
- **Halt-on-blocker envelope at the leaf.** If any finding is `blocker`, the sub-agent emits `STATUS: BLOCKED` with a `BLOCKER_QUESTION:` field naming the question for the human. (Auto-build execution agents use `PARKED_REASON` instead — parking happens at the orchestrator BEFORE execution is spawned, so by Phase 6e no blocker can surface. In `/claim-task` the parent IS the human, so the sub-agent must be able to surface a blocker question on its own envelope. Do not "normalize" `BLOCKER_QUESTION` and `PARKED_REASON` without re-examining the parking-layer split.)

The **Prompt Template** and **Classification Rubric** sections above are still consumed verbatim by the reviewer-executor — only the framing (self-classification, sealed REVIEW_REPORT, leaf-level halt) differs. Out of scope: extending this collapse to `/auto-build` Phase 6b-6e. Validate the interactive shape under `/claim-task` first; the auto-build port is a follow-up after several `/claim-task` runs prove out the prompt discipline. (Claude Code 2.1.172's nested-spawn capability changes the calculus for that port — a per-task agent could spawn a genuinely independent fresh-eyes reviewer instead of self-classifying. See the § "Harness constraint" history note and Sysop's roadmap experiment entry before attempting it.)

## Envelope receipt — `SubagentStop` hook (Phase 37)

The `SubagentStop` hook at `sysop/scripts/parse_subagent_envelope.py` parses the reviewer-executor's (and `/auto-build` execution agent's) final-message envelope on the harness's terms and writes structured JSON to `sysop/runtime/subagent-envelopes/<TASK_ID>.json`. Parent skills prefer that JSON file when present, falling back to regex-parsing the agent's return text if the file is missing or malformed. The fallback's justification is defense in depth (hook not registered, file-write failure), not a timing race: the hooks docs now document the `SubagentStop` lifecycle — the hook runs synchronously when the sub-agent finishes, and can even block the stop via `decision: "block"`, which structurally guarantees it completes before the parent receives the Agent tool's return (Phase 54 retired the earlier "undocumented timing" caveat). The hook reads the envelope from `last_assistant_message` in hook input (Claude Code 2.1.47+), falling back to the sub-agent's own transcript at `agent_transcript_path` (2.0.42+) when the field is absent; the written JSON records which source was used in `message_source`. The hook is purely additive; the envelope shape this partial documents (sealed `REVIEW_REPORT:` at the TOP + `TASK`/`STATUS`/`BRANCH`/etc. block at the BOTTOM) is what the hook expects. Do not change the envelope shape without re-validating the hook's parser.

**Optional `PHASE:` field (Phase 159a).** An envelope may carry `PHASE: <stage>` alongside `TASK:`. When it does, the hook writes `sysop/runtime/subagent-envelopes/<TASK_ID>.<phase>.json` instead of `<TASK_ID>.json`, so several sub-agents sharing one claim id each get their own file rather than the last one overwriting the rest. Omit the field (or set it to the documented `none` sentinel) and the filename is unchanged — which is what every envelope shipped today does, so nothing that exists now needs to change. Emit it only when more than one enveloping sub-agent runs under a single claim; the parent skill must then read the phase-keyed path it expects, not the bare one. See `/claim-task` SKILL.md § Step 8 and `/auto-build` SKILL.md § Phase 6e + Phase 7 for the read-order contract.
