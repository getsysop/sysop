# Does the workflow actually get quieter? — gdp review-history analysis

**Date:** 2026-06-09 (revised same day after reviewer critique); refreshed **2026-07-11** to the July snapshot; **2026-07-15** the covered-class falsifier was run (Phase 112) — see § Revision notes.
**Filed as:** colleague-review item 4 (`REVIEW_CHECKLIST.md`, Medium)
**Source:** `~/Projects/gdp-query-system` — `review_tasks.md` + `review_tasks_archive.md` (71 rounds, 3,298 findings, 2026-02-23 → 2026-07-10) + `CLAUDE.md` git history (78 conventions, all dated).
**Reproduce:** `python3 mine_gdp_reviews.py` (read-only against the gdp clone) → `gdp_review_metrics.json`.

## Verdict

The thesis survives, but only in its severity-weighted form, and the headline
must rest on denominator-free shares — not on endpoint-to-endpoint rates.

- **Do NOT claim** "findings per round go down." They go up — Q1 averaged 37.7
  findings/round, Q4 averaged 78.7. Two reasons, both structural: the rubric
  grows (every promoted convention adds something to check), and late rounds
  file one task per call site where early rounds bundled.
- **Do NOT claim** "roughly ten-fold." That figure was criticals-per-100-commits
  computed endpoint-to-endpoint, and the endpoint months are the two least
  representative: February is the repo bootstrap (initial commit 2026-02-06), and
  the latest month is always partial — July, as of this snapshot, is one review
  round (Round 74, 2026-07-10), 99 commits, two critical findings.
- **DO claim** the severity-share shift, which needs no activity denominator:
  the critical share of findings fell from **21.4% (Feb) to 5.4% (Apr)** — the
  last full month before Round 70's retro-application sweep — and then **held in
  the low single digits through July** (16.7% in May during the Round 70 sweep,
  0.0% in June, 5.4% in July); the low-severity share rose from **22% (Feb) to
  59% (Apr)** and sits in the **43–75% band across the whole back half** (65% in
  July). The activity-normalized rates corroborate the direction: criticals per
  10k effective lines changed fell **~3.2× from the March peak (9.8) to May
  (3.1)**, with June and partial July lower still (0.0 / 0.42).

## Monthly series (from `gdp_review_metrics.json` § monthly)

| Month | Rounds | Commits | Eff. lines | Med. lines/commit | Findings | 🔴 | Crit/100c | Crit/10kL | Crit share | Low share |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-02 ¹ | 7 | 390 | 82,125 | 65 | 285 | 61 | 15.6 | 7.4 | 21.4% | 22% |
| 2026-03 | 47 | 1,534 | 166,335 | 21 | 1,549 | 163 | 10.6 | 9.8 | 10.5% | 29% |
| 2026-04 | 12 | 913 | 119,216 | 22 | 1,089 | 59 | 6.5 | 5.0 | 5.4% | 59% |
| 2026-05 | 2 | 479 | 146,290 | 13 | 270 | 45 | 9.4 | 3.1 | 16.7% | 43% |
| 2026-06 | 2 | 373 | 286,111 | 16 | 68 | 0 | 0.0 | 0.0 | 0.0% | 75% |
| 2026-07 ² | 1 | 99 | 47,599 | 236 | 37 | 2 | 2.0 | 0.4 | 5.4% | 65% |

¹ Bootstrap month — repo's initial commit is 2026-02-06; activity denominators unreliable.
² Partial month — July, as of 2026-07-10, one review round (Round 74). Don't anchor claims on it. (June is now a complete two-round month; its single June-8 critical from the older snapshot was reclassified out during a later consolidation, so June's critical share is 0.0%.)

"Eff. lines" excludes vendored/generated paths (`**/node_modules/**`,
`google-cloud-sdk`, lockfiles, data/log dirs); without the exclusions February
alone carries ~435k lines of vendored Playwright/`@types` churn.

## The May outlier, explained

All 45 May criticals come from Round 70 (2026-05-12), the first review after a
2.5-week gap. Reading the 45 titles: **roughly 25 are enforcement of
already-promoted conventions at additional call sites** — ~10 security-rejection
logging adds, 6 `redirect: 'error'` adds, ~7 input-bounding caps — filed one
task per site. A handful are genuine novel defects (a wrong import path that
breaks runtime, JWT shape validation before SDK calls). So the bump is mostly
the map being applied ever more broadly, not a regression to February's defect
rate.

A **review-process change underlies the granularity.** On 2026-04-17,
`TECH-LSP-REVIEW` (`2f3c5497`) made `/codebase-review` language-server-aware: it
added a `pyright`/`tsc` diagnostic stage and — load-bearing here — routed the
Step 9 convention **sweeps through `LSP.findReferences`**, which amplify a single
promoted convention into one task per call site across the whole tree (where
grep had only approximated). The same-day `TECH-SEMGREP-CHECKS` (`b9984ac7`) and
the 2026-04-20 `53764e3f` — which retired the noisy `audit-trail-gaps` /
`state-mutation-logging` greps into the `/security-audit` LLM agents — round out
the shift from a pure-grep pre-scan to grep + LSP + Semgrep. Round 70
(2026-05-12) was the first *broad* sweep to exploit the LSP amplification, which
is why criticals jumped while the incremental (changed-files-only) Round 69
(2026-04-25) had stayed at 10. The instrument got sharper; the code did not get
worse.

That classification is a manual read of 45 titles, not automated. Note
the May per-line rate (3.1) does *not* bump — the per-commit bump (9.4) is
partly the shrinking-commit artifact.

## Confounds — checked, with directions

1. **Commit-size shrinkage (biases TOWARD the trend in per-commit rates).**
   Median lines/commit fell 65 → 11 over the period as the workflow moved to
   parallel batches and smaller automated commits. This inflates the
   per-100-commits denominator over time. Handled by (a) re-anchoring the
   headline on denominator-free shares and (b) adding the per-10k-effective-lines
   rate, which is robust to commit granularity and still falls ~3.2× Mar → May.
2. **Per-site task granularity (biases against).** Late rounds file one task
   per call site; early rounds bundled. From Round 70 on this is driven by the
   `LSP.findReferences` amplification added 2026-04-17 (`TECH-LSP-REVIEW`),
   which locates every call site precisely rather than approximating with grep.
   Inflates late-period finding and critical counts.
3. **Severity labels are the reviewer's own (direction not fully pinned).**
   The rubric is impact-categorical and predates this analysis — 🔴 = "data
   integrity risk, security vulnerability, production crash potential"
   (gdp `codebase-review/SKILL.md:304`, `WORKFLOW.md:542`) — and nothing in it
   references the convention map or novelty. The one directly testable case
   runs against the "known → labeled lower" drift hypothesis: Round 70's
   map-enforcement findings were labeled 🔴, not discounted. But one round is
   not proof; treat the shares as primary evidence and the rates as the check.
4. **Endpoint months are unrepresentative (cuts both ways).** February is
   bootstrap; June is partial. All rate claims anchor on the interior full
   months (Mar–May), with Feb/Jun shown but flagged.

## The process-induced-findings sentence (for any public claim)

Many findings are process-induced: the rubric itself generates per-site
enforcement tasks as conventions broaden, so total findings track the rubric's
size, not the code's health. The loop's job is driving the *severe* rate down —
and that is the rate that fell, under every normalization checked.

## Convention accretion

78 conventions in gdp's CLAUDE.md § Prevention Conventions as of 2026-07-11
(unchanged from the June snapshot — Rounds 73 and 74 promoted none, confirming
the plateau); every one dated by first appearance in git history
(2026-02 → 2026-05-14).
Stale figures (1,400+ findings / 67 conventions) updated in README.md,
CLAUDE.md, WORKFLOW.md, and the monograph; the two "rounds 1–67" references in
CLAUDE.md § Provenance and HANDOVER.md correctly describe the 2026-04-30
extraction event and were left as-is.

## Revision notes (2026-06-09, second pass)

Reviewer critique of the first version surfaced four issues, all confirmed:
the ten-fold claim rested on the two least representative endpoint months; the
commit-granularity confound is real (median 65 → 11) and biases toward the
per-commit trend, falsifying the earlier "all confounds bias against" sentence;
the severity-label confound's direction was asserted without grounding; and
stale headline figures remained in README/CLAUDE/WORKFLOW. Fig. 7's bars were
re-based from criticals-per-100-commits to the denominator-free critical share,
June was relabeled partial, and the miner now emits `effective_lines_changed`,
`median_lines_per_commit`, and `critical_per_10k_lines` per month.

## Revision notes (2026-07-11, July snapshot refresh)

Re-mined after gdp's final pre-launch review rounds landed. Round 73 (2026-06-30,
Code Quality, 45 findings, 0 critical) and Round 74 (2026-07-10, 37 findings, 2
critical — a Code Quality pass with the OWASP security-audit tasks appended under
the same section header, so the miner types the round `quality`) bring the corpus
to **71 rounds / 3,298 findings / 78 conventions**. June flipped from a one-round
partial to a complete two-round month (its lone June-8 critical was reclassified
out of the archive during a later consolidation, so June critical share is now
0.0%), and July becomes the new partial endpoint.

The headline **holds in its severity-weighted form and gets stronger, not by
falling further but by staying down**: critical share fell 21.4% → 5.4% (Feb →
Apr), then, the Round 70 sweep aside, held in the low single digits through
partial July (May 16.7% during the sweep, June 0.0%, July 5.4%) while the
rubric kept growing. It is no
longer a monotonic decline — July ticks up from June's zero — so the prose was
reworded from "severity falls" to "**fell sharply, then held low**." No new
conventions promoted (plateau confirmed). Fig. 7 was hand-redrawn to six points
(June de-partialed, July added as the partial). Number sites updated together:
`gdp_review_metrics.json`, this report, `docs/workflow.html`, `README.md`,
`CLAUDE.md`.

## Revision notes (2026-07-12, limitations pass + the covered-class test)

An external critique of the public § II / Fig. 7 framing made four points, all
accepted: (1) the **maturation confound** — critical rates fall in most young
codebases as the foundational mistakes get fixed, so the 21% → 5% decline is
consistent with ordinary maturation and nothing published separated the two
hypotheses; (2) **n=1 with the loop's author as reviewer and severity grader** —
and the June reclassification shows the labels move in consolidations (counted,
June is ~1.5%, not 0%); (3) **small-n volatility in the tail** (68 findings in
June, 37 in July — one round moves the share by double digits); (4) the public
copy carried **none of the caveats this report already recorded**. The landing
page § II and the monograph's "Does it actually get quieter?" section now carry
an explicit limitations block and a falsifier statement, and the claim is
weakened to correlation-plus-mechanism: the severe share fell early and stayed
low while the rubric grew, and where a convention is mechanized its machine
check makes silent recurrence of that finding class structurally harder (a
prose-only convention's gate is the reviewer re-armed with the map).

### The covered-class test (run — Phase 112, 2026-07-15)

The analysis that would separate the loop from maturation: partition every
finding into **(A)** classes covered by an already-promoted convention at the
time of its round versus **(B)** classes nothing covered, and track both per
100 lines of diff per round. Maturation depresses A and B together; enforcement
selectively suppresses A. Three amendments were applied, all grounded in this
report's own earlier findings:

1. **Separate new-code recurrence from retro-application backfill.**
   Post-promotion sweeps file covered-class findings *by design* (Round 70:
   ~25 of its 45 criticals were one-per-call-site enforcement of existing
   rules, not new defects). A naive A-series would *rise* after promotion in
   sweep months and falsely falsify the claim.
2. **Split by enforcement tier.** Mechanized conventions (checks.yml /
   semgrep / hooks) are blocked before the review ever runs, so their archive
   recurrence is ~zero by construction; the informative subset is the
   prose-only conventions.
3. **Prefer the event-study form.** Promotion selects on recurrence bursts
   (the cross-round survival gate), so regression to the mean guarantees some
   post-promotion decline in A even with zero enforcement. Primary metric:
   recurrence of the *specific* promoted pattern in new code after its
   promotion date; the A/B time series is the secondary view.

**Method.** All 3,298 findings were classified against the 79 dated conventions
in the map at the 2026-07-15 run date (the § accretion figure of 78 is the
2026-07-11 snapshot; the map gained one entry between the two dates — a
convention name first appears in git history 2026-07-13) with a transparent
signature classifier (distinctive helper/option identifiers
— `_sanitize_log`, `encodeURIComponent`, `follow_redirects`, `max_output_tokens`,
`redirect: 'error'`, … — that recur verbatim in findings, plus a documented
prose-keyword layer). Each convention's *promotion* date (first CLAUDE.md git
appearance) and its *mechanization* date (first appearance of a real machine
gate for it: semgrep rule / `checks.yml` check / eslint error rule) were dated
independently. The classifier was validated blind by an independent labeler on a
100-finding stratified sample: **precision 0.80, recall 0.66, exact-class
agreement 0.82**. Low recall is conservative for the A/B contrast (missed
covered findings fall into B, diluting the difference). Reproduce via
`covered_class_analysis.py` (a dev-repo research artifact — it hardcodes gdp
convention signatures, so it is excluded from the public mirror; re-running it
needs the private archive).

**Result — the rate test is inconclusive; one denominator-free signal
survives.** gdp's review instrument changed twice mid-history — the grep check
registry (2026-03-20) and semgrep + LSP (2026-04-17, the activation "spike") —
which surfaced a whole-tree backlog across *every* finding class, covered and
novel alike, then collapsed as the tree was swept clean. The truly-novel
(uncovered) baseline itself swings **161 → 169 → 445 → 13 per 100k eff-lines**
across the four instrument eras, so per-window recurrence *rates* are dominated
by the instrument, not by code health or enforcement — for A and B classes
alike. Rate-normalized, the test does not separate the loop from maturation.
The one signal robust to this is within-convention and denominator-free:
**14 of 26 mechanized conventions have zero post-gate new-code recurrence
(21 of 26 have ≤ 2)** — for 13 of those 14 the class had been recurring in the
review before the gate landed (1–14 prior findings) and then stops; the
fourteenth (an abort-cleanup rule) appeared only in the activation sweep, so it
is not evidence of a reduced recurrence. Prose-only and novel classes keep
recurring into the late period. **The signal is not uniform, and the exceptions
cut against it:** the five mechanized classes that keep recurring post-gate
include the *two highest-volume* ones — Logging (~13 post-gate) and Engine
selection (~15) — where the machine gate is narrower than the prose convention
or the class is broad enough that the rule catches only part of it. So "the gate
kills the class" holds for the many small, sharply-scoped classes and fails for
the few big fuzzy ones. **Two load-bearing caveats:** (1) it is partly true
*by construction* — the machine gate catches the class before the review runs,
so it stops appearing as a review finding whether or not fewer are written; it
proves the gate works, not that the codebase is healthier absent the gate.
(2) the classifier's 0.66 recall runs *against* this count, not with it — a
missed post-gate finding makes a class look collapsed when it isn't, so "14 of
26 to zero" is an over-count to the extent recall < 1 (the two heaviest classes
not collapsing is consistent with real post-gate recurrence the classifier
under-counts elsewhere). For **prose-only conventions**, covered-class
recurrence tracks the maturation baseline — **no separable enforcement effect is
detectable** (see below).

**Prose-only conventions (the informative subset per amendment 2).** Rate per
100k eff-lines across the four instrument eras, covered-prose beside the novel
baseline in the same windows: **covered-prose 24 → 45 → 48 → 3**, **novel
161 → 169 → 445 → 13**. Both rise through the grep and LSP activations and crash
in the late period; the novel baseline spikes 2.6× at the 2026-04-17 activation
while covered-prose barely moves, and the covered-prose *share* of novel bounces
(0.15 / 0.26 / 0.11 / 0.23) with no trend. The trajectories are
instrument-dominated and covered-prose never falls *relative* to novel — so the
prose convention's independent contribution cannot be isolated from
maturation-plus-instrument. *No separable effect detectable*, not a clean null.

**Verdict.** The covered-class test **confirms the mechanization-specific
clause** already in the § II / monograph copy ("where a convention is mechanized
its machine check makes silent recurrence of that finding class structurally
harder") — for the sharply-scoped mechanized classes, with the two heaviest as
disclosed exceptions — finds **no separable effect for the prose-only clause
(inconclusive, not a proven null)**, and confirms **maturation is entangled and
large**. It does *not* support a blanket "the loop suppresses
covered classes beyond maturation" claim. So the Phase-98 weakened *claim*
stands unchanged, and this decision (2026-07-15, Phase 112) is: keep the
correlation-plus-mechanism framing and record the falsifier as *run, with a
mixed result* — more credible than the aggregate chart alone, because the test
was run and the mixed result reported rather than buried. The landing page
(`docs/index.html`) and monograph (`docs/workflow.html`) said the test "has not
been run"; that stale status was corrected to "run, mixed result" (a factual
correction — the claim itself is unchanged). Promoting the mechanization finding
to lead § II evidence was considered and declined (the by-construction caveat +
n=1 + classifier error bars make it too thin to headline).

### Points already covered, and one honest "say so"

- **Diff-size denominator:** already emitted (`effective_lines_changed`,
  `critical_per_10k_lines`) and already this report's corroborating check.
- **Finding-counting policy:** the process-induced-findings section above is
  the policy statement; per-call-site filing became precise and tree-wide with
  the LSP-driven review (2026-04-17) and is why raw counts track rubric size,
  not code health.
- **Demotion ledger:** the demotion pipeline exists (static staleness sweep +
  the FP fire ledger), and zero retirements have been adjudicated to date. A
  rule set that has retired nothing yet is a young audit — that is the honest
  description, and it is disclosable as such.
- **Second-codebase replication:** the other codebase running the loop is the
  same author's, far smaller, and in a different domain. Its month-one
  critical share is not an independent control, and no such comparison is
  published.

## Revision notes (2026-07-15, covered-class falsifier run — Phase 112)

The covered-class test above was **run** (it had been specified-not-run since
2026-07-12). Full method and result are in § "The covered-class test"; the
one-line outcome: the rate-normalized test is **inconclusive** (the twice-
changed review instrument confounds per-window rates for covered and novel
classes alike — the novel baseline itself swings 161 → 169 → 445 → 13 per 100k),
and the one robust, denominator-free signal — mechanized conventions' classes
stop appearing after their gate (14 of 26 to zero) — **confirms the
mechanization clause but is partly true by construction**, while prose-only
conventions show **no separable effect from maturation** (inconclusive, not a
clean null). Decision: the Phase-98 weakened *claim* stands unchanged; the
falsifier is now recorded as run with a mixed result, not promoted to lead
evidence. The landing page and monograph had their stale "not run" status
corrected to "run, mixed result" (a factual correction flagged by the phase's
fresh-eyes review — the claim itself is unchanged). Reproducible via the dev-repo
`covered_class_analysis.py` (mirror-excluded; it hardcodes gdp convention
signatures).
