# Fan-out evidence & finding provenance — shared contract

Canonical contract for **how findings declare what was actually checked**, and **what standard of evidence judging one requires**. Two tiers plus a universal adjudication rule:

- **Tier 1 — the provenance marker.** Universal. Every finding a review skill emits carries `[verified]` or `[reported]`. Fires on **every** run, inline or fan-out.
- **Tier 2 — the fan-out evidence footer + orchestrator merge discipline.** Fan-out only. Attaches when a skill dispatches sub-agents; never fires on a run that doesn't fan out.
- **Adjudication — evidence in both directions.** Universal. Governs every keep, downgrade, and dismissal, whoever makes it.

Consumed by `/codebase-review` (Step 3 dispatch + Step 3c merge), `/security-audit` (Step 3 dispatch + Step 3b merge), and — Tier 1 and adjudication always, Tier 2 only if it fans out — `/test-audit`. Maintain the contract here; do not duplicate it into the skills (they cite it).

---

## Tier 1 — the provenance marker (UNIVERSAL, every finding, every run)

Every finding carries exactly one provenance tag:

- **`[verified]`** — the agent that produced this finding **opened the cited `file:line` and confirmed the claim against the source it read**.
- **`[reported]`** — the finding is asserted from something *other than reading that site*: a grep/regex hit, a pre-scan or tool result, a coverage artifact, an upstream claim, or — in a fan-out run — a sub-agent's report the orchestrator has **not itself re-read**.

**In a fan-out run the emitter changes at merge — this is the load-bearing rule.** A sub-agent self-declares on its own findings (it tags what *it* opened). But the row that reaches the reader is written by the **orchestrator**, which can vouch only for what *it* re-read. So at merge, **a fan-out finding defaults to `[reported]` unless the orchestrator itself sampled and re-read the site** (which upgrades it to `[verified]`). Do **not** copy a sub-agent's self-`[verified]` onto the row unchallenged — that is exactly the laundered attestation this contract exists to stop (the sub-agent that read 8 of 82 files self-tags `[verified]` too). The sub-agent's self-tag and its evidence footer are *inputs the orchestrator audits* (Tier 2), not the final row tag. Catching a hollow batch is the **footer's** job (below); the marker's job is telling the reader which findings the orchestrator itself confirmed.

**It is a self-declared honesty label, not a machine-checked guarantee.** Nothing enforces that a `[verified]` finding was truly re-read; the tag records the author's own account of how they know. Read `[verified]` as *"I checked this site myself,"* never as *"this has been independently verified."* Wherever a skill defines the marker in its output format, it must say this in-line so the tag is never over-read.

**Orthogonal to severity/confidence.** Severity = how bad if real; a confidence label (where a skill has one, e.g. `/test-audit`'s `[high]`/`[med]`/`[low]`) = how sure the recommendation is; **provenance = whether the author opened the site.** All three can coexist on one row.

**What the reader / actuator does with it (the consumer story — this is why the marker exists):**

- A **`[verified]`** finding is safe to act on at its stated severity.
- A **`[reported]`** finding is a *lead, not a confirmed defect* — **spot-check it against the source before acting.** An actuator (`/auto-fix`, `/claim-task`, a human applying the fix) must **re-read the site before applying a fix to a `[reported]` finding** — never auto-apply blind. A `[reported]` High is still worth surfacing loudly; it simply hasn't been confirmed by a read yet.

Without the consumer story the marker is decoration. The point is a routing decision: `[verified]` → act; `[reported]` → confirm, then act.

---

## Adjudication — evidence in both directions (UNIVERSAL)

Provenance governs how a finding is **asserted**. This governs how it is **judged** — the moment someone keeps, escalates, downgrades, or kills it. The same standard binds both directions, because a dismissal and a finding are both claims about the code:

- **A falsified premise refutes a finding outright — this is the ordinary way a finding dies.** If you re-read the cited `file:line` and it does not contain what the finding claims — wrong symbol, wrong construct, the code simply absent — **that read is the refutation.** Drop the clause and note the miss. The two rules below do *not* apply to this case; they govern the case where the premise holds and the dispute is about **consequence**.
- **To kill or downgrade a finding whose premise holds, locate and read the mitigation.** A finding dies on a control you can point at — a specific `file:line` you opened — never on an assumed one ("the framework escapes that", "callers validate upstream", "that path can't be reached in production"). If you cannot name where the protection lives, you have not refuted the finding; you have guessed at it. Do not manufacture a defense in order to close something out.
- **To keep or escalate a finding, trace the path.** The mirror failure: asserting an attack path, a runtime consequence, or a reachability chain nobody actually traced. State the chain — the call sites that reach the flagged code — or mark it **explicitly unassessed** and file at the severity the evidence alone supports, saying which.
- **When neither can be established, keep the finding and record what is unassessed.** Default to survival, not dismissal. The asymmetry is deliberate and specific to this loop: **a filed task gets another reader — the fixer, the reviewer, `/review-close` — while a dismissal gets none.** An unverified finding costs a review cycle; an unverified dismissal is silent and permanent, and nothing downstream will ever surface it. This default covers an unproven **mitigation or consequence** — never a premise you checked and found false, which the first rule already disposes of.

**Where this binds:** every drop, downgrade, or resolve — the merge discipline below, the Step 4 dedup pass, and any severity call an agent makes on its own findings before reporting them (so the kill/keep pair is pasted into fan-out dispatch prompts alongside the footer, since the spawned agent never reads this file).

**Composing with the compound-findings rule** (`_shared/adversarial-review.md` § Compound findings), in this order: decompose the finding into its clauses **first**, then hold each surviving clause to the standard above separately. That rule's **second leg binds here too** — on a High-severity or security-relevant dismissal, a second independent pass (fresh context at minimum) re-adjudicates the rejection clause-by-clause, or, where the shape cannot spawn one, the full per-clause rationale is recorded in the round summary for the next reader. Carrying the decomposition without the second pass satisfies half the rule while appearing to satisfy all of it.

**This is an adjudication rule, not a hunting rule.** It applies to whoever is *judging* a candidate finding. Do not push it back onto the agents doing discovery as a "default to false positive" stance — a skeptical hunter reports less, which suppresses real findings before anyone can adjudicate them at all. Hunters report; adjudicators demand evidence.

---

## Tier 2 — the fan-out evidence footer (FAN-OUT ONLY)

Applies whenever the skill dispatches fan-out sub-agents (one per scope cluster, OWASP category, module, etc.). This is the **sub-agent return contract** — dispatch prompts state *what to check*; this states *what to return*.

Every fan-out sub-agent's report MUST:

1. Tag **every finding** with a `file:line` anchor **and** its Tier-1 `[verified]`/`[reported]` self-tag.
2. **End with an evidence footer:**

```
EVIDENCE FOOTER
Assigned: <N> files  (<the glob / list this agent was given>)
Opened:   <M> files  (the paths actually read — list them, or "anchored in findings above")
Tools:    read=<n> grep=<n> lsp=<n> other=<n>   (rough mix used)
```

**The orchestrator MUST paste this exact footer block — and the per-finding `file:line` + `[verified]`/`[reported]` self-tag requirement — into each sub-agent's dispatch prompt.** The spawned sub-agent does not read this file, so a bare reference ("include an evidence footer") is not enough; copy the template in verbatim, exactly as the scoped convention bullets are copied in.

**Why the footer is the load-bearing piece.** It makes over-attestation *falsifiable*. A sub-agent that read 8 of 82 assigned files and claims full coverage must now write `Opened: 8` beside `Assigned: 82` — a visible, checkable contradiction — instead of an invisible "reviewed everything." A specific count is a far bigger, more falsifiable lie than a coverage adjective, so requiring the count is itself the deterrent. (The footer is *also* self-reported — there is no per-file read telemetry — so it is a **commitment device, not a guarantee**; the merge discipline below is what audits it.)

---

## Tier 2 — orchestrator merge discipline (FAN-OUT ONLY)

When the orchestrator collects the fan-out reports, **before** merging them into the round output:

1. **Low-opened-ratio flag — MANDATORY, cheap.** Read the footer's `Opened`, `Assigned`, and `Tools` (grep counts as looking). Two signals — either one fires the flag: **(a) low look-coverage** — `opened + grepped` covers **< ~⅓** of `Assigned`, i.e. the agent didn't actually look at most of its scope; **(b) unbacked claim** — a finding self-tagged `[verified]` whose cited file is *not* in the agent's `Opened` list (a direct self-contradiction). Record either as a **loud line in the round summary — a coverage gap, not a clean pass.** Do **not** flag an honestly *sparse* review (assigned 82, only 3 relevant, opened those 3 + grepped the rest, findings on all three) — that is full coverage of a sparse scope, and grep is a legitimate review tool; flagging it trains the orchestrator to ignore the one mandatory check. Reading the footer costs nothing; this leg is not optional.
2. **Sample re-read — ADVISORY.** Re-read **2–3 of each sub-agent's claimed `file:line` findings** against the source — prioritizing the ones it self-tagged `[verified]` (the claims it is vouching for) and any finding whose cited file is absent from its `Opened` list. A claim that survives → carry it into the merged output as **`[verified]`**; a claim that doesn't → drop or downgrade it and note the miss. **Decompose compound findings before dropping — this rule binds on every drop *and every downgrade*, even though the sampling itself stays advisory.** A finding that asserts several independent clauses or cites several sites is adjudicated only **clause-by-clause**: a failed re-read refutes the clause you re-read, not the finding — adjudicate its *remaining* clauses (re-checking its other cited sites where they exist) before the row is dropped, downgraded, or resolved, and record which clauses survived. A downgrade earned by one refuted clause while an unexamined clause carries the real severity is the same laundering as a drop. A merge that resolves a multi-clause sub-agent finding on a one-clause refutation is the same laundering shape as copying a self-`[verified]` through unchallenged: partial refutation — refute one clause, silently drop the rest — is the measured way real findings get dismissed as false positives, and it only ever fires in that direction (real → apparent-FP). This runs at the merge boundary **alongside — not folded into** — Post-Scan amplification: **amplification reads *outward* (LSP/grep for *siblings* of a finding elsewhere in the tree); sampling reads *inward*, re-opening the cited `file:line` itself to confirm the claim.** They are adjacent passes over the same findings, not the same read — do not conflate them. It stays sampled (2–3, not exhaustive) because re-reading everything would defeat the purpose of fanning out — the goal is making false attestation *detectable*, not re-doing the review. (Whether to make it a hard merge gate is deferred until its overhead is weighed against real throughput data; leave it advisory until then.)
3. **Provenance class in the round summary — MANDATORY.** State the split, never a bare coverage percentage: e.g. `38 findings: 12 verified (orchestrator-read + sampled), 26 reported` plus the per-batch `opened/assigned` ratios (here "verified" means the *orchestrator* read the site — a sub-agent's self-`[verified]` it never sampled counts as reported). A bare "97% covered" with no provenance class is exactly the attestation this contract exists to stop.

---

## Honest limit

Every attestation signal here — marker, footer, opened/assigned — is **self-reported**: this contract makes dishonesty *visible and falsifiable*, not impossible. (§ Adjudication is the exception in kind: it does not ask anyone to attest, it sets what evidence a judgement requires.) What actually upgrades a `[reported]` finding to checked is a *reader* opening the site — the orchestrator's sample re-read or the actuator's pre-fix re-read. Keep that reader in the loop; the marker is a routing hint toward it, not a substitute.
