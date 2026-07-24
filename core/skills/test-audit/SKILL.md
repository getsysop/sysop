---
name: test-audit
description: Survey the codebase for standing test-quality gaps — where load-bearing surfaces lack tests, and where existing tests have gone dead, redundant, or hollow. Read-only judgment audit; the standing counterpart to the diff-scoped coverage gate. Recommends tests and retirements; never writes tests or mutates the queue.
argument-hint: "[--path <glob>] [--all] [--tier1] [--tier2]"
model: opus
disallowed-tools: Edit, Write, NotebookEdit
---
<!-- sysop:model-roles frontmatter=reasoning -->

A read-only **standing test-quality audit**. Every other test mechanism in Sysop is forward-facing and anchored to the change in flight — `## Test decision` covers the current task, adversarial-review #7 judges the current plan, `/review-close` Step 2d verifies the current diff, and the coverage gate (`run_checks/coverage.py`) measures **only changed crown-jewel lines** by design. Two questions have no home anywhere: *where is the codebase structurally exposed on tests* (a module untested for a year but never in a diff produces zero findings), and *which existing tests have gone dead, redundant, or hollow*. `/test-audit` answers both. It reads the source and test trees, applies the calibrated `_shared/test-assessment-rubric.md`, and emits a ranked report of recommendations. **It never writes a test, never claims a task, and never mutates the queue** — every finding is a recommendation the human gates.

> **Read-only guard (Phase 54) — structural only when Claude Code *invokes* this as a skill.** The `disallowed-tools` frontmatter (Claude Code 2.1.152+) removes the file-write tools, but **only when the harness activates the skill** — a `/test-audit` call or a `Skill` invocation. When an agent is instead told to *read this `SKILL.md` and follow it* (path-based invocation — the **only** option on non-Claude-Code harnesses, and a common one inside Claude Code too), the frontmatter never fires: the write tools (`Write`/`Edit`/`NotebookEdit`) stay available, and read-only-ness rests entirely on the agent honoring the contract below, not on a structural guard. Even when the guard *is* active it is partial by design — `Bash` stays allowed for read-only `git grep` / `Grep` scans, so it covers the dedicated write tools, not shell redirects. This skill mutates nothing: it reads code and prints a report. (That the guarantee is narrower than "removes the write tools" sounds is portability evidence, not only a doc nit — it is what a non-Claude-Code harness actually gets.)

## Not the coverage gate, `/codebase-review`, or the deferred coverage signal

`/test-audit` is deliberately **not folded into** the machinery it complements.

- **vs. the coverage gate (Phase 61a/61b, `run_checks/coverage.py`)** — the gate *enforces* coverage on **changed** crown-jewel lines (diff-scoped, to keep consumer-CI weight small). `/test-audit` *finds* the **unchanged / standing** gaps the gate structurally cannot see, plus the covered-but-hollow tests a coverage percentage calls "covered." They form a loop: when the audit recommends a test on a load-bearing path and the human marks it crown-jewel + adds the test, the gate keeps it covered going forward. The audit is the on-ramp to the gate.
- **vs. `/codebase-review`'s "Test Coverage Gaps" dimension** — that fires per-file *inside a diff/round review* (reactive, changed files only). `/test-audit` is whole-surface, standing, and human-invoked at a different cadence (occasional, not every round). They share **one** test-worth judgment — both cite `_shared/test-assessment-rubric.md` — so the calibration lives in one place; they do not merge.
- **vs. a deferred automated coverage signal** (tracked as `(C3)` in Sysop's own roadmap) — that is an *always-on CI coverage-number emit feeding an audit loop*. `/test-audit` is the *human-invoked, judgment-led* realization of that audit ambition. If that automated number is ever built, it becomes this skill's optional `--report` enrichment — it never becomes a gate here.

## Judgment first, measurement as enrichment

The base path is **LLM judgment over source + test files** — pure `Read` / `Grep`, no coverage tooling required. This is deliberate: judgment catches *covered-but-hollow* (a line `diff-cover` calls "covered" by a test that asserts nothing), which a coverage percentage structurally cannot, and it keeps the skill **portable to any agent** (no `diff-cover` / `pytest-cov` dependency). A whole-repo coverage artifact, *when one already exists on disk*, only **narrows the candidate set** — it is never required and never gates. Degrades gracefully like `/roadmap --in-flight`: absent artifact → judgment-only, with a one-line note.

## Pre-flight: Permission Guard

**No new permission rules; no Step 0 guard.** Every operation on the base path is read-only: `Read` on source, test, `checks.yml`, `security_map.md`, `CLAUDE.md`, and any coverage artifact; `Grep` / read-only `git grep` for referent scans. Per `_shared/permission-guard.md` § Notes, read-only ops are auto-approved under `auto` mode and are **not** listed as allow-rules. The optional coverage-artifact read is a *file read*, not a shell call. The skill runs no scripts and writes nothing on any path documented here. It is portable to any project on any agent.

*(If a future tier shells out to `diff-cover` for whole-repo enrichment, gate that behind an explicit opt-in flag that degrades when the rule or artifact is absent — never on the base path. No such tier ships today.)*

## Step 0 — Parse arguments

Parse `$ARGUMENTS`:

- **`--path <glob>`** — scope the audit to one subtree (e.g. `--path "src/billing/**"`). Use when auditing a specific module rather than the crown-jewel default.
- **`--all`** — audit the **whole** source tree, not just crown-jewel-first. Off by default: a standing judgment audit over an entire large suite (a large monorepo — tens of thousands of lines) risks exhausting the context window, so the default works crown-jewel-first and per-module-chunked, and states plainly what it reached and what it did not. Opt in when the tree is small enough, or you accept a partial pass over a large one.
- **`--tier1`** — run only Tier 1 (recommend *new* tests on load-bearing surfaces).
- **`--tier2`** — run only Tier 2 (retire dead / redundant / hollow tests: 2a provably-dead + 2b judgment).
- No tier flag → run both jobs.

## Step 1 — Read the code and the crown-jewel signal

Read these, tolerating absence (a consumer may have run `install.sh` but not filled every signal):

1. **The source tree and the test tree** (`Read` / `Grep`). Identify the test tree by convention (`tests/`, `__tests__/`, `*_test.*`, `*.test.*`, `*.spec.*`) and the source it exercises.
2. **The crown-jewel globs — the authoritative "audit this hardest" signal.** Parse the `critical_path:` lists of the `coverage-*` checks in `.claude/checks.yml` (the same globs that arm the diff-coverage gate — *not* `CLAUDE.md`). **Guard for the placeholder state:** the shipped fragment carries placeholder globs (`<critical path module>/`, `<critical components>/`); if the only `critical_path:` values are angle-bracket placeholders, treat the crown-jewel signal as **absent** (the consumer hasn't designated crown jewels yet, so the gate is inert too) and fall back to the `CLAUDE.md § Scope mapping` / `convention_map.md` sources (item 4 below).
3. **`.claude/security_map.md`** (plus its `.claude/security_map.project.md` overlay, if present) — the *second* "audit this hardest" signal, alongside the crown-jewel globs. Its listed surfaces are security-critical, the class the rubric ranks top-tier ("anything a `security_map.md` … note calls out" — `_shared/test-assessment-rubric.md`, load-bearing invariants). Pull the surfaces it flags into the candidate set (Step 2) and weight them in the Tier-1 ranking (Step 4). **The shipped map is half-concrete** — maps are never installer-substituted, so its *pack* sections stay in placeholder form (`<api module>/…`, `<auth module>/…`) until the consumer localizes them, while its *core* workflow-meta sections (`scripts/*.sh`, CI YAML, `.claude/skills/**`) ship concrete. So — on the same placeholder-detection principle as the crown-jewel guard — treat any section still in `<...>` form as absent, and let the Tier-1 **negative discipline** govern the concrete sections (infra/config/meta don't become test candidates just because the map lists them). The genuine top-tier targets (app auth, payments, SQL) light up only once the pack globs are localized. Tolerate whole-file absence like every other signal — a consumer may not have populated it.
4. **`<project>/CLAUDE.md § Scope mapping`** *if present* — for the broader source path-sets when crown-jewel globs are absent/placeholder. If it too is absent, fall back to `convention_map.md` section headers, exactly as `/codebase-review` does to bound its review surface.
5. **A whole-repo coverage artifact** *if one already exists on disk* (`coverage.xml`, `coverage/lcov.info`) — optional enrichment only (§ "Judgment first"). Read it to *narrow* candidates (a line the report already marks uncovered is a strong Tier-1 candidate); never require it; note in one line whether it was found and used.

**Absence handling:** no source tree, or a tree with no identifiable code surfaces → report that plainly and stop; do not fabricate findings. No test tree at all → that is itself the headline Tier-1 finding (the whole load-bearing surface is unguarded); report the highest-exposure surfaces to seed first.

## Step 2 — Scope the candidate surfaces

- **Default (no `--all`, no `--path`): crown-jewel-first.** Start with the `critical_path:` paths from step 1.2 **and any surfaces `security_map.md` flags (step 1.3)** — both signals say "audit this hardest" — then expand outward by *exposure* (highest call-site count / broadest `blast_radius` / most-depended-on modules) until the context budget is spent.
- **`--path <glob>`:** restrict to that subtree.
- **`--all`:** whole tree, **per-module-chunked**. Announce the chunking and, at the end, state explicitly which modules were audited and which were not reached — a standing audit that silently stops halfway reads as "clean" when it isn't (the no-silent-caps discipline).

Whichever scope: name, up front, what surface the report covers, so the reader never mistakes a partial pass for a whole-tree verdict.

## Step 3 — Apply the rubric to each candidate surface

This is the skill's judgment core. For each candidate surface (a function, class, endpoint, component, or an existing test), apply `_shared/test-assessment-rubric.md` and assign exactly one verdict:

- **Tier 1 — recommend a new test** (`--tier1` / default): is this a load-bearing invariant — a guard, error/exception path, boundary, security-critical or data-integrity surface, parser/serializer — with no coverage or only a *covered-but-hollow* test? Recommend a specific test and say what invariant it should pin. Apply the **negative discipline**: do **not** recommend tests for trivial glue / wiring / config / re-exports (the "busywork Tier 1" failure). See the rubric's Tier 1 section.
- **Tier 2a — retire, provably dead** (`--tier2` / default): does a static check show the test's referent is gone — production symbol exists only inside the test tree (`git grep -nw`), a deprecated/removed path, or an indefinite `skip`/`xfail` with no live condition? High-confidence, fires now. Apply the **FP guard**: a dynamic-dispatch / string-keyed / re-exported referent can look grep-dead but isn't; a *conditional* skip is not a *dead* skip. When you cannot tell, keep it.
- **Tier 2b — retire, judgment** (`--tier2` / default): redundant (no unique failure vs. a **named** sibling), brittle (asserts implementation not behavior — a change-detector), or hollow (asserts nothing meaningful). Every 2b finding **must** carry a confidence label, the specific evidence (named sibling / the observable behavior to assert instead), and the keep-when-unsure default. See the rubric's Tier 2b section.
- **Covered adequately** / **keep despite looking retireable** — the deliberate no-ops. Surface a *keep* verdict only when a surface looks retireable but guards a subtle case worth naming (so the human isn't tempted to cut it later); otherwise stay silent on adequately-covered code.

## Step 4 — Rank and report

Rank Tier-1 recommendations by **load-bearingness × exposure** (invariant severity — a `security_map.md`-flagged surface ranks high here — × how much depends on it: crown-jewel membership, call-site count, `blast_radius`); rank Tier-2 findings dead-first (2a, immediate/high-confidence) then judgment (2b) ordered by confidence. Emit the report in the shape below.

## Step 4b — Emit Tier-2b findings as calibration rows (only if any)

**Only when the report carries Tier-2b findings.** Tier-2b (redundant / brittle / hollow) is the sole tier whose confidence labels are a *judgment* that matures with evidence — Tier 1 and Tier 2a fire correctly on the first run and are **not** emitted here. After the report, print each Tier-2b finding once more as a copy-pasteable ledger row, verdict and note left blank for you to fill:

```
CALIBRATION — Tier-2b decisions (optional; skip if you don't track test-decision quality)
| Date       | Suite/repo | Finding                                   | Dimension | Confidence | Verdict | Note |
|------------|------------|-------------------------------------------|-----------|------------|---------|------|
| YYYY-MM-DD | <repo>     | test_settle.py::test_refund_rounds_down   | redundant | med        |         |      |
| YYYY-MM-DD | <repo>     | test_import.py::test_calls_parser_once    | brittle   | low        |         |      |
```

Two portable uses, both opt-in:

- **Track your own accept/veto** on the judgment-tier retirements over time — `accept` = you deleted/rewrote the test, `veto` = you kept it.
- **Report a disagreement upstream.** If you think a Tier-2b recommendation is *wrong* (it flagged a test that guards a real case), that is the highest-value calibration signal there is. Note it in your friction log and run `/report-issues` — the shared `_shared/test-assessment-rubric.md` earns sharper confidence labels from exactly these vetoes, and the fix ships back to you on the next update.

This emits nothing to disk and points at no maintainer-internal file — it is a copy-pasteable block for *your* records and the opt-in upstream pipe. Never emit calibration rows for Tier 1 or Tier 2a.

## Step 5 — Offer the next move (informs, does not actuate)

Close with **one** routing offer — never actuate without explicit confirmation (the read-only contract: `/test-audit` informs; the human decides which findings become work):

- Accepted Tier-1 / Tier-2 recommendations → offer to route them into `/intake` as tasks (the same one actuation path `/roadmap` uses), **one at a time or as a small batch the human confirms** — never auto-file. A recommended test becomes a `FEAT-`/`TECH-` task; a retirement becomes a small cleanup task. On a **loop-mode install** (`.claude/sysop.lock` has `mode: loop` — `/intake` and the task queue are not installed), offer the accepted recommendations as copy-pasteable entries for the project's own tracker instead; never point at a skill this install doesn't ship.
- A recurring *pattern* of the same gap across many surfaces → note it may be worth promoting into a convention the review skills enforce (a `convention_map.md` entry), rather than filing N one-off tasks.
- Crown-jewel signal was absent (placeholder globs) → suggest the human designate crown jewels by filling `critical_path:` in `.claude/checks.yml`, which both sharpens this audit and arms the coverage gate.

Close with one line: `Read-only test audit — no code or tests changed. Actuator: /intake (route accepted recommendations into tasks).` — on a loop-mode install, swap the actuator clause for `Actuator: your own tracker (/intake is not part of a loop-mode install).`

## Output shape (reference)

```
## Test audit — <project>   (scope: <crown-jewel-first | --path <glob> | --all>; coverage report: <used coverage.xml | none>)

SURFACE AUDITED
Crown-jewel paths: billing/, ledger/import/   ·   plus 4 highest-exposure modules.
Not reached this pass: reporting/, admin/ (context budget) — re-run with --path to cover.

TIER 1 — recommend a new test
[high] [verified]  billing/settle.py:refund_split() — data-integrity: splits a refund
        across payees; no test pins the sum-invariant (Σparts == total). Recommend a
        golden test over the boundary cases (0, single payee, rounding remainder).
[med] [verified]  ledger/import/ofx.py:_parse_amount() — parser contract; covered-but-
        hollow (test asserts only `is not None`). Recommend asserting the parsed Decimal.
[low] [reported]  billing/refunds.py — coverage.xml flags this crown-jewel module thinly
        covered; a lead from the artifact, not opened this pass. Confirm by reading first.

TIER 2a — retire (provably dead)
[high] [verified]  test_legacy_router.py::test_v1_dispatch — production `v1_dispatch`
        is gone (`git grep -nw v1_dispatch` finds it only in this test). Referent deleted.

TIER 2b — retire (judgment)
[med] [verified]  test_settle.py::test_refund_rounds_down — redundant with
        ::test_refund_rounding (same input, same assertion). Retire the narrower one.
[low] [verified]  test_import.py::test_calls_parser_once — brittle: asserts a mock call
        count, not observable output. Leaning keep; rewrite to assert the imported rows.

CALIBRATION — Tier-2b decisions (optional)   [only when Tier-2b findings exist; see Step 4b]
| Date | Suite/repo | Finding | Dimension | Confidence | Verdict | Note |
(one row per Tier-2b finding above; fill Verdict accept/veto — track your own, or /report-issues a disagreement)

RECOMMENDED NEXT
Route the two Tier-1 recs into /intake as tasks? The dead Tier-2a test is a safe delete.

Read-only test audit — no code or tests changed. Actuator: /intake (route accepted recommendations into tasks).
```

Adapt the shape to the tree; omit empty tiers; render only the findings that survive the rubric's keep-when-unsure discipline.

**Every row carries two independent brackets** (per `_shared/fanout-evidence.md` § Tier 1). The first is **confidence** — how sure the recommendation is (`[high]`/`[med]`/`[low]`). The second is **provenance** — `[verified]` when you opened the cited `path:symbol` and confirmed the claim against source, `[reported]` when the finding rests on something you did *not* open (most often a coverage artifact flagging a module, or a `security_map.md`/`critical_path:` surface pulled in without reading it). They are orthogonal: a `[high] [reported]` is a strong lead you haven't yet confirmed by reading. Because this skill's base path *is* reading the source (`Read`/`Grep`), most findings are `[verified]`; `[reported]` is the honest tag for anything inferred from an artifact rather than the code. It is a **self-declared honesty label, not a machine-checked guarantee** — never route a `[reported]` recommendation into `/intake` without confirming it at the source first.

**If you fan out** — if an invocation dispatches sub-auditors (one per module) instead of reading inline, as the cross-harness reference run was observed to do — the full fan-out contract applies: each sub-auditor returns the **evidence footer** (files opened vs. assigned + tool mix), and you audit it before merging (row-provenance default + low-opened-ratio flag + sample re-read), per `_shared/fanout-evidence.md` § Tier 2. Merging sub-auditor reports without that check is the blind-merge this contract exists to stop. The shipped base path does **not** fan out — `--all` chunks per module *within one agent*, it does not spawn sub-auditors — so the single-agent base path above has no fan-out, and only the Tier-1 marker applies there.

**§ Adjudication applies on every path, fan-out or not** (`_shared/fanout-evidence.md`). A Tier-2 retire recommendation is a dismissal — you are proposing that a test's protection is unnecessary — so it carries the same evidence burden: name the sibling that covers the case, at `path:symbol`, having read it; never retire on an assumed duplicate. This is the same discipline as the rubric's keep-when-unsure default, stated as the general rule it is.

## Design notes

- **Why a sibling, not a `/codebase-review` flag.** `/codebase-review` is heavyweight, diff- and round-oriented, and writes `review_tasks.md`. Test assessment wants a different cadence — occasional, standing, read-only, human-invoked over the *whole* surface. Bolting it on would blur that skill's per-round contract. But the *judgment* is single-sourced: `/codebase-review`'s "Test Coverage Gaps" dimension cites the same `_shared/test-assessment-rubric.md` (Phase 80), so test-worth judgment has one home, not two.
- **The value is the rubric, not the shell.** A `/test-audit` that is just "go find weak tests" is the ad-hoc prompt with a slash in front of it. The calibrated `_shared/test-assessment-rubric.md` is the load-bearing half — it ships **provisional** and calibrates across real suites (60a→60b), and only its Tier-2b judgment dimensions need that runway; Tier 1 and Tier 2a fire correctly on the first run.
- **Portability.** The base path is pure `Read` / `Grep` — it runs on any agent, including bash-installer / non-Claude consumers, with no coverage tooling. The optional coverage-artifact read is the only enrichment, and it degrades to judgment-only when absent.
- **Two failure modes to design against** (the analogue of guided mode's over/under-escalation): *busywork Tier 1* (recommending tests for trivial glue) and *reckless Tier 2b* (retiring a test that quietly guards a subtle case). Both are bounded by the rubric — the Tier-1 negative discipline and the Tier-2b named-sibling + keep-when-unsure requirements — and by the read-only contract (the human vetoes every action).

## Deferred features

- **`--report <path>`** — an explicit whole-repo coverage artifact to enrich against, and/or shelling to `diff-cover` for a fresh whole-repo number. Reserved; today the skill auto-discovers an existing `coverage.xml` / `lcov.info` on disk and is judgment-only otherwise. Becomes the integration point if that deferred automated coverage signal (Sysop roadmap `(C3)`) is ever built.
- **`--json`** — structured emit for orchestrator consumption. Reserved; the text report is the only output today.
- **Consuming `## Test decision` records** — a `no test because Z` in a task body that has since gone stale is a Tier-2 candidate. Promising, but couples the audit to the task queue; weigh in a follow-up.
- **A local decision memory (`--suppress` / "don't re-nag me")** — a consumer-side record of Tier-2b findings you have already vetoed (chosen to keep), so re-runs skip them with a "N tests you kept were suppressed — `--all` to re-review" note, exactly like the `run_checks` baseline suppresses known-accepted findings. Reserved; today every run re-evaluates from scratch. It would live consumer-side and is never transported — distinct from the shared-rubric calibration (Step 4b), which sharpens the *defaults* for everyone. Deferred to be shaped by the first real audit runs.
