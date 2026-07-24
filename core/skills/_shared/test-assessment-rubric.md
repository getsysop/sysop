# Test Assessment Rubric — where to add tests, and which tests to retire

Canonical rubric for the two standing test-quality questions Sysop's forward-facing machinery never asks: **where is the codebase structurally exposed on tests** (missing coverage on load-bearing surfaces), and **which existing tests have gone dead, redundant, or hollow**. Consumed by `/test-audit` (its whole judgment layer). Also referenced by `/codebase-review`'s "Test Coverage Gaps" dimension — an in-diff review's test-worth judgment is the same judgment, so it lives in one home here rather than being duplicated into the review skill. Maintain in one place — do not copy the calibration into a skill.

> **Provisional — calibration pending (Phase 80).** This rubric ships alongside `/test-audit` but has **not yet been calibrated across real suites** (the 60a→60b pattern: spine + provisional rubric together, then calibrate from runs). A dimension earns **promotion-grade** only after it holds across Sysop's own suite **and** a real consumer suite **and** a large third suite — the cross-project-survival gate Sysop uses to promote any convention (WORKFLOW.md §5.1), exactly as `decomposition-rubric.md` was calibrated in 60b. **Scoping nuance that matters:** only the **Tier 2b judgment dimensions** (redundant / brittle / hollow) actually need accumulated real-run evidence — they earn high-confidence labels by observing which recommendations a human accepts. **Tier 1 (recommend a new test) and Tier 2a (retire a provably-dead test) fire correctly on the first run** — obsolescence-by-dead-referent is a fact, not a judgment, and needs no runway. Nothing about the feature waits for N rounds; only 2b's *confidence* matures. The archetypes below are generalized shapes, not project identifiers, so they read the same for any consumer.
>
> **Help sharpen it.** If a Tier-2b (redundant / brittle / hollow) recommendation is *wrong* for your codebase — it flagged a test that guards a real case — that veto is exactly the signal that matures the confidence labels. Note it in your friction log and run `/report-issues`; the fix ships back to every consumer on the next update. See `/test-audit` Step 4b.

The rubric answers each candidate surface with exactly one verdict: **recommend a test** (Tier 1) · **covered adequately** (no action) · **retire — provably dead** (Tier 2a) · **retire — judgment** (Tier 2b, confidence-labeled) · **keep despite looking retireable** (the deliberate no-op that protects a subtle case). Read-only throughout: every verdict is a *recommendation*; the human gates every actual edit.

---

## Tier 1 — is this surface worth a new test? *(fires immediately; no calibration needed)*

**The litmus: does an untested line here encode a load-bearing invariant — a promise the code makes that a wrong change could silently break?** If yes, and nothing guards it, recommend a test. If the line is trivial glue, do not — a test that only restates wiring is negative value (it adds maintenance drag and catches nothing).

**Load-bearing surfaces — recommend a test** (reusing adversarial-review dimension #7's "load-bearing invariant" vocabulary, applied to the *standing* codebase rather than a diff):

- **Guards and validation** — the branch that rejects bad input, enforces a precondition, or raises on an invalid state. The whole point of the guard is that it fires; an untested guard is a promise nobody checks.
- **Error and exception paths** — retry/backoff, rollback, fallback, the `except` that recovers vs. the one that re-raises. These run rarely in production and are exactly where silent regressions hide.
- **Boundary conditions** — empty / single / max, off-by-one edges, the first and last element, zero and overflow. The interior is usually fine; the edges are where the bug lives.
- **Security-critical and data-integrity code** — auth/permission checks, input sanitization, atomic-write / rollback paths, idempotency and dedup keys, money/quantity arithmetic, anything a `security_map.md` or `## Data integrity` note calls out. A wrong change here is not a visible crash; it is a quiet corruption.
- **Parsers, serializers, and format translators** — the shape-in / shape-out contract that downstream code trusts. Golden tests earn their keep here.

**Name the regression.** Every Tier-1 recommendation states the **specific failure the test would catch**: "if a change broke ⟨invariant⟩, ⟨observable wrong behavior⟩ would ship silently, and this test fails on it" — never just a category label ("needs edge-case coverage"). This symmetrizes the rubric — Tier 2b already demands named evidence per finding; Tier 1 carries the same burden. It is also a self-check: if you cannot name a concrete regression the test would catch, the surface is probably glue and the recommendation is the busywork failure mode (see the negative discipline below).

**The covered-but-hollow tell — a coverage report cannot see this, which is why the audit exists.** A line can be "covered" (a test executes it) while the invariant it carries is *unguarded* — the test asserts nothing meaningful about it. Symptoms: `assert result is not None` on a function that structurally cannot return `None`; a test that constructs an object and asserts only that construction didn't throw; a snapshot assertion over output that no one reads for a specific invariant. **Covered-but-hollow is a Tier-1 recommend (add a real assertion), not a Tier-2 retire** — the line needs a *better* test, not no test. (When the hollow test *also* adds maintenance drag with zero signal, pair the Tier-1 "assert the real invariant" recommendation with a Tier-2b note to replace rather than augment.)

**The negative discipline — do NOT manufacture coverage.** These are *not* worth pinning, and recommending tests for them is the "busywork Tier 1" failure mode:

- Trivial glue / pure wiring — a one-line pass-through, a dispatch-table registration, a re-export, a getter/setter with no logic.
- Framework or generated boilerplate — code the framework guarantees, not code you wrote.
- Config and constants — a settings dict, an enum of literals. A test that asserts `CONFIG["x"] == "x"` restates the source and breaks the instant the value legitimately changes (a change-detector, see Tier 2b).
- Code whose only honest test would restate the implementation line-for-line. If the test and the code would be the same statement, the test proves nothing.

**Rank by load-bearingness × exposure.** Among the surfaces worth a test, rank the recommendations by *invariant severity* (data-integrity / security > guards > boundary polish) times *exposure* — how much depends on it: crown-jewel membership (a `critical_path:` glob in `checks.yml`), call-site count, `blast_radius` if the surface maps to a task. Recommend the crown-jewel guard before the leaf boundary case.

---

## Tier 2a — is this test provably dead? *(mechanical, immediate, high-confidence)*

The exact analog of Phase 62's backward *convention* sweep (map → code: which map content lost its referent) applied to tests (test → code: which test lost its subject). A test is **provably dead** when a static check — not a judgment — shows its reason to exist is gone. Fires on the first run, every run, deterministically.

- **Production referent gone.** The symbol under test — the function, class, method, endpoint, or component the test exercises — no longer exists outside the test tree. The check: `git grep -nw <symbol>` (or the language equivalent) finds it *only* inside test files. The code it guarded was deleted; the test now guards nothing.
- **Deprecated / removed code path.** The test drives a branch, flag, or module that has been removed or permanently disabled — a feature flag hard-wired off, a legacy path the code no longer reaches.
- **Self-marked dead.** The test is indefinitely `skip` / `xfail` / `it.skip` / `@Disabled` with **no live un-skip condition** — a bare `skip("obsolete")` or `skip("flaky, ignore")` with no ticket, date, or platform gate. It has been quarantined and forgotten.

**FP guard — the "looks dead but isn't" trap** (Phase 58a dimension #9's discipline, reused by Phase 62's demotion sweep): a static grep does not see every reference. A symbol reached by **dynamic dispatch, a string key, reflection, a plugin/entry-point registry, serialization-by-name, or a public-API re-export** can appear grep-dead while production still calls it. Before flagging dead: check the export surface and any registration tables. **A conditional skip is not a dead skip** — a test gated on a platform (`skipif(sys.platform == "win32")`), an environment (needs a live binary / network), or a tracked upstream fix (`xfail(reason="upstream #1234")`) is *parked with a live condition*, not obsolete; keep it. **When you cannot tell whether the referent is truly gone, keep it and say so** — Tier 2a is the high-confidence tier; ambiguity demotes the finding to a Tier-2b judgment note or to no finding at all.

---

## Tier 2b — is this test worth retiring on judgment? *(confidence-labeled; the slice that calibrates over runs)*

Here the retire-vs-keep line is a genuine judgment with real false-positive cost — the "looks redundant but guards a subtle case" trap. The skill only *recommends* (read-only; the human vetoes), so 2b is shippable from day one — but its trustworthiness comes from **not crying wolf**, enforced by three non-negotiable attachments on every 2b recommendation:

1. **A confidence label** (`high` / `medium` / `low`) — and `low` means "flagging for your eyes, leaning keep."
2. **The specific evidence**, so the human verifies in seconds, not minutes: for redundancy, *name the sibling test* that already catches this; for brittleness, *name the observable behavior* the test should assert instead of the implementation detail it currently pins; for hollowness, *quote the assertion* (or its absence).
3. **The keep-when-unsure default** — Phase 58a dimension #9 again. If you cannot articulate the specific evidence in the two forms above, there is no 2b finding.

The three judgment shapes:

- **Redundant** — the test has **no unique failure**: every input that fails it also fails some other named test, on the same assertion. Retiring it loses no coverage. **The trap:** two tests over the same function are *not* redundant just because they share a subject — if they exercise different branches, inputs, or invariants, each has a unique failure. Redundancy is same-input-same-assertion, or a strict subset (test A's inputs and checks are wholly contained in test B's). Name the superset test or there is no finding.
- **Brittle / over-specified** — the test asserts *implementation*, not *behavior*: exact call order, private internal state, a verbatim log string, a mock's call count, a full-object snapshot where one field is the real invariant. The tell over history: **it broke on every refactor but never caught a real bug** — a pure change-detector. The recommendation is usually *rewrite to assert the observable behavior*, not delete — name that behavior. Only recommend outright deletion when the behavior it should assert is already covered by a named sibling (then it collapses into redundant).
- **Hollow** — the test executes lines but asserts nothing meaningful (or asserts a tautology: `assert True`, `assert x == x`, `assert isinstance(x, X)` right after `x = X()`). Distinct from Tier-1 covered-but-hollow only in framing: if the underlying invariant is load-bearing, the right move is Tier-1 *add a real assertion* (replace); if the executed code is trivial glue not worth pinning at all, the hollow test is pure drag → Tier-2b *retire*.

**2b is the only tier whose promote-lines mature over runs** — the rubric earns sharper confidence labels by observing which redundant/brittle/hollow calls the human accepts and which they veto. It is *not* withheld until then; it ships confidence-labeled and calibrates in the wild.

---

## Quick smell checklist (map each to a section above)

Scan a drafted set of findings for these — each is a known failure mode:

- **Busywork Tier 1** — recommending a test for trivial glue / config / a re-export. → Tier 1, negative discipline.
- **Coverage-as-proof** — treating a high line-coverage number as "well tested" and stopping. A suite can be 95% line-covered with every load-bearing invariant hollow. → the covered-but-hollow tell; judgment over measurement.
- **Reckless 2b retire** — recommending deletion of a test that quietly guards a subtle case, on a redundancy hunch, without a named sibling. → Tier 2b, keep-when-unsure + name-the-sibling.
- **Dead-looking-but-dynamic** — flagging a test dead because a static grep missed a string-keyed / reflected / re-exported referent. → Tier 2a, FP guard.
- **Conditional-skip-as-dead** — retiring a platform- or upstream-gated skip that has a live condition. → Tier 2a, "a conditional skip is not a dead skip."
- **Change-detector defense** — keeping a brittle test *because* it "fails a lot," mistaking noise for vigilance. A test that only fails on safe refactors is anti-signal. → Tier 2b, brittle.

**Two independent quality axes, never conflated:** *coverage quantity* (are the lines executed?) and *coverage quality* (do the assertions guard the invariants?). A codebase can score high on one and fail the other — the whole reason this audit is judgment-led and not a coverage percentage. **Judge the assertion, not the line count.**

---

> **Provenance.** Authored Phase 80 alongside `/test-audit`, replacing the ad-hoc "occasionally ask a strong model to look for weak testing" practice with a calibrated, repeatable rubric — the same move `decomposition-rubric.md` made for slicing and `adversarial-review.md` made for review. Ships **provisional**: cross-project survival across Sysop's own suite, a real consumer suite, and a large third suite is the promotion gate (WORKFLOW.md §5.1), and only the Tier-2b judgment dimensions require that runway — Tier 1 and Tier 2a are trustworthy from the first run. Generalized archetypes replace any project-specific test IDs, per the no-project-identifiers authoring rule.
