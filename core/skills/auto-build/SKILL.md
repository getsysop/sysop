---
name: auto-build
description: Orchestrate parallel claiming, planning, and execution of independent tasks from tasks/index.yml — picks a batch under a complexity ceiling (optionally narrowed to explicit task IDs passed as arguments, e.g. from a /roadmap ordering), sequentially pre-claims each task on main, then per task runs plan-only → adversarial-reviewer → execution Opus agents (orchestrator-driven; spawned agents do not nest further by design). Parks on adversarial-review blockers; auto-executes the rest. Human stays the merge gate via /review-close.
argument-hint: "[max-count] [TASK-ID ...] [--dry-run]"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning inline=reasoning -->

Read `tasks/index.yml`, pick a batch of N independent claimable tasks under a complexity ceiling, sequentially claim each on `main` (mirroring `/auto-fix`'s `batch_work.sh` pattern), then per task run three Opus phases at the orchestrator layer: plan-only agent → adversarial-reviewer agent → execution agent. Findings classified by the orchestrator itself (spawned sessions do not nest further agents — a deliberate design choice, see Step 6). Tasks with `blocker` findings park (worktree + lock intact, plan + verdict written to `.auto-build/` scratch dir); the rest auto-execute. The human resumes parked tasks manually and runs `/review-close` on executed branches.

This skill does NOT merge anything. It batches the front of the pipeline (claim + plan + execute) up to the point where the human re-engages.

> **Helper names** referenced in this skill (e.g., `_sanitize_log`, `useAbortableFetch`, `getDisplayError`, `redact_api_keys`, `shared_cli.py`) are placeholders — substitute the equivalent helpers from your project's `convention_map.md`. Worked examples may also reference specific batch numbers, file paths, or env-var names from the originating project; treat those as illustrations, not literal requirements.

## Pre-flight: Permission Guard

Verify `.claude/settings.json` carries the allow-rules this skill depends on. Under `auto` mode with `skipAutoPermissionPrompt: true`, a missing rule will silently halt mid-batch — worst case after Step 5 has pre-claimed several tasks on main.

Read `.claude/settings.json` and confirm `permissions.allow` contains:

- `Bash(bash sysop/scripts/claim_task.sh:*)` — Step 5.2 sequential pre-claim (also invoked transitively by every spawned execution agent's local context).
- `Bash(python3 -:*)` — Step 1's queue-read/readiness-filter heredoc and Step 5.1's yaml-round-trip status flip (both single `python3 - <<` commands; venv PyYAML is resolved by an in-heredoc `sys.path` bootstrap, not a `.venv/bin/python3` command word or an env prefix — either of which would bind to no rule; Sysop Phase 126).
- `Bash(python3 sysop/scripts/validate_tasks.py)` / `Bash(python3 sysop/scripts/validate_tasks.py:*)` and the `.venv/bin/python3 sysop/scripts/validate_tasks.py` / `.venv/bin/python3 sysop/scripts/validate_tasks.py:*` venv variants — Step 5.3 post-claim validator (the venv form is preferred per Phase 45b; the bare form remains for non-venv consumers).
- `Bash(git add tasks/index.yml)` — Step 5.4 commits each claim.
- `Bash(git commit -m claim:*)` — Step 5.4 commit message shape.
- `Bash(git commit -m rollback:*)` — Step 5 rollback path on pre-claim failure.
- `Bash(git checkout:*)` — Step 5 rollback path (`git checkout tasks/index.yml`).

Read-only git operations (`git rev-parse`, `git log`, `git branch --show-current`) used by Phase 6a/6e HEAD capture and Phase 7 envelope recovery are auto-passed by the classifier and do not require allow-rules; they are documented here for completeness. The Step 1 heredoc's in-flight overlap check (Leg B, Phase 103) imports `sysop/scripts/scope_overlap.py` **in-process** — it runs inside the same already-permitted `python3 -` heredoc, and its `git -C <worktree> diff --name-only` reads are read-only subprocesses inside that process — so it adds **no** new permission rule.

If any required rule is missing, stop with the `_shared/permission-guard.md` § Algorithm step 4 message (one-line reason: "pre-claims a batch of tasks on `main` via heredoc'd python + `claim_task.sh`, then spawns parallel Opus agents per task — silent denial mid-batch would leave half-claimed state in `tasks/index.yml`"). Do not proceed.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and continue.

## Step 0: Parse Arguments

Parse `$ARGUMENTS`:

- **Bare integer `N`** (1–4) → raw-count override. Default: `4`. Clamp to [1, 4].
- **Task IDs** — any token matching the schema ID grammar (`^[A-Z][A-Z0-9-]{2,80}$`, the same `_TASK_ID_RE` that `validate_tasks.py` enforces; e.g. `FEAT-0012 TECH-DB-BOOTSTRAP`) → explicit-subset restriction. Collect every such token as `SUBSET_IDS`; Step 1 narrows the candidate pool to them by intersection. Typical source: the `Run it:` line of a `/roadmap` ordering, or a deadline-driven hand-pick. The eligibility filters and batch ceilings never loosen for named tasks (see Steps 1–2).
- **`--dry-run`** → select batch and present math; stop after the confirmation prompt without spawning.
- Unrecognized argument → print usage and stop:
  ```
  Usage: /auto-build [N] [TASK-ID ...] [--dry-run]
    N — max raw batch count (1-4, default 4). Force N=1 for DB-heavy verify suites.
    TASK-ID ... — restrict the batch to an explicit task subset (e.g. from a
                  /roadmap ordering). Eligibility filters and batch ceilings
                  still apply; requested IDs that don't survive them are
                  reported with per-ID reasons, never silently dropped.
    --dry-run — preview batch without spawning agents.
  ```

## Step 1: Read Queue & Filter Claimable

Single pass through `tasks/index.yml` only — do not open any per-task body files yet. Use `python3` with `yaml.safe_load`; venv PyYAML is resolved by the heredoc's in-process `sys.path` bootstrap (per convention; Sysop Phase 126).

**Launch-lane filter:** only tasks in the project's currently-active phase are eligible. The active phase is the one with `current_focus: true` in `tasks/index.yml § phases` (Phase 16 invariant — exactly one phase carries the flag; the validator enforces this). Tasks in any other phase are excluded — they belong to a past launch lane or a future one and shouldn't be batched against the current focus.

**Explicit-subset restriction (optional):** when Step 0 collected `SUBSET_IDS`, the pool is the *intersection* of the subset with the same filtered frontier — never a bypass. Every eligibility rule above (open status, no `user_action` / `on_hold_until` / lock, current-focus phase, met `depends_on`) still applies to a named task; naming an ID is a narrowing instruction, not an override. Requested IDs that don't survive are printed as `EXCLUDED <id> <reason>` lines and surfaced to the human verbatim — never silently dropped. In particular, an out-of-lane ID stays excluded: the launch-lane filter guards against batching future-lane work, and naming an ID doesn't change which lane is being prosecuted — the reason line points at the real knob (`current_focus`).

> **Subset vs. lane shift.** Pass IDs when a deadline or a `/roadmap` ordering picks *these tasks first* out of the current lane — an ephemeral execution preference. If the deadline genuinely re-prioritizes the project (the important work lives in another phase, or deserves its own), that's a **lane shift**: reshape `phases:` via `/intake` re-entry and flip `current_focus` instead. Don't restructure phases just to steer one batch — phases are launch lanes with history, not sprint buckets.

```bash
# SUBSET_IDS = the space-separated Step 0 task-ID list ("" when no subset was given).
# Passed as ONE quoted positional arg: "$SUBSET_IDS" is a single argv element (spaces and
# all) that Python splits — quoting sidesteps the shell word-splitting that argued for
# env-passing before (unquoted $var splits in bash, not zsh; a quoted arg never splits).
# `python3` command word (not `.venv/bin/python3`) + in-heredoc PyYAML bootstrap so
# `Bash(python3 -:*)` matches as a single simple command (BeanRider ISSUE-0049; Phase 126).
python3 - "$SUBSET_IDS" <<'PY'
import os, sys, glob
try:
    import yaml
except ImportError:  # PyYAML lives only in the project venv (BeanRider ISSUE-0049)
    sys.path[:0] = glob.glob(".venv/lib/python*/site-packages")
    import yaml
from pathlib import Path

# Step 0 explicit subset; empty set = no restriction.
subset = set(sys.argv[1].split())

with open("tasks/index.yml", encoding="utf-8") as f:
    data = yaml.safe_load(f)

phases = data.get("phases", []) or []
active = next((p for p in phases if p.get("current_focus")), None)
if active is None:
    print("ERROR: no phase has current_focus: true in tasks/index.yml")
    raise SystemExit(2)
active_phase = active.get("number")

tasks = data.get("tasks", []) or []
by_id = {t["id"]: t for t in tasks}
locks = {os.path.basename(p)[:-5] for p in glob.glob(".locks/*.lock")}

order = {"Low": 0, "Medium": 1, "High": 2}

# unlock_count[id] = number of OPEN tasks in the active phase that list `id`
# in depends_on. Direct dependents only (not transitive — a transitive count
# overweights long chains whose tails are far off anyway). Phase-scoped because
# the claimable pool is phase-scoped: only a same-phase dependent becoming
# ready enlarges the NEXT batch's pool. It's the simple direct count — a
# dependent still blocked by OTHER unmet deps is counted anyway (a good-enough
# foundational-ness signal; precision isn't worth the extra graph walk).
unlock_count = {}
for t in tasks:
    if t.get("status") != "open" or t.get("phase") != active_phase:
        continue
    for dep in t.get("depends_on") or []:
        unlock_count[dep] = unlock_count.get(dep, 0) + 1

def ready(t):
    if t.get("status") != "open": return False
    if t.get("user_action"): return False
    if t.get("on_hold_until"): return False
    if t["id"] in locks: return False
    if t.get("phase") != active_phase: return False
    for dep in t.get("depends_on") or []:
        if by_id.get(dep, {}).get("status") != "done":
            return False
    return True

candidates = [t for t in tasks if ready(t)]

# Explicit-subset narrowing (Step 0): intersection with the filtered frontier.
# A named ID never bypasses ready() — it only narrows. Report every requested
# ID that didn't survive, with the first applicable reason.
if subset:
    selected_ids = {t["id"] for t in candidates if t["id"] in subset}
    for tid in sorted(subset - selected_ids):
        t = by_id.get(tid)
        if t is None:
            reason = "not in tasks/index.yml"
        elif t.get("status") != "open":
            reason = f"status is '{t.get('status')}', not open"
        elif t.get("user_action"):
            reason = "user_action: true — needs the human, not an agent"
        elif t.get("on_hold_until"):
            reason = f"on hold until: {t.get('on_hold_until')}"
        elif tid in locks:
            reason = "active lock in .locks/ — already claimed"
        elif t.get("phase") != active_phase:
            reason = (f"phase {t.get('phase')} is outside the current-focus phase "
                      f"{active_phase} — flip current_focus in tasks/index.yml § phases "
                      "if the lane should shift")
        else:
            unmet = [d for d in t.get("depends_on") or []
                     if by_id.get(d, {}).get("status") != "done"]
            reason = "unmet depends_on: " + ", ".join(unmet)
        print(f"EXCLUDED\t{tid}\t{reason}")
    candidates = [t for t in candidates if t["id"] in selected_ids]

# Leg B (Phase 103): in-flight overlap awareness. Grade each candidate against
# work already building in another worktree (a second concurrent batch, or a
# manual /claim-task) using the shared scope-overlap primitive, so this doesn't
# re-derive the inference /claim-task and /roadmap already share. SOFT signal —
# it de-prioritizes an overlapping candidate in the sort (secondary to
# unblocker-first, so a foundational task is never buried) and annotates the
# Step 4 table; it NEVER hard-excludes (worktree isolation makes a collision
# recoverable rework, not corruption). Degrade silently to "no overlap data" if
# the primitive can't be imported (advisory-non-blocking, matching
# scope_overlap.py's own stance) — the batch math is unaffected either way.
inflight_verdict = {}    # tid -> "likely" | "possible" | "none"
inflight_overlaps = {}   # tid -> [(in_flight_task_id, [shared_paths]), ...]
inflight_count = 0
try:
    import sys as _sys
    if "sysop/scripts" not in _sys.path:
        _sys.path.insert(0, "sysop/scripts")
    import scope_overlap as _so
    _wt_cache = {}
    def _reader(ws):
        if ws not in _wt_cache:
            _wt_cache[ws] = _so._worktree_changed_paths(ws)
        return _wt_cache[ws]
    for _c in candidates:
        _a = _so.assess(_c["id"], worktree_reader=_reader)
        inflight_count = _a.in_flight_count
        inflight_verdict[_c["id"]] = _a.max_verdict
        inflight_overlaps[_c["id"]] = [(o.task_id, o.evidence) for o in _a.overlaps]
except Exception:
    inflight_verdict = {}   # any failure → no annotation, batch math unchanged

orank = {"none": 0, "possible": 1, "likely": 2}

# Sort: unblocker-first, THEN in-flight-overlap-avoidance (soft, secondary),
# then effort, then id. Overlap is secondary to unlock_count on purpose —
# /auto-build's awareness is always-on (no opt-in flag), so it must not bury a
# foundational unblocker just because it touches an in-flight file; it only
# breaks ties among equally-foundational candidates toward the non-colliding
# one. (Contrast /next-task --avoid-inflight, where the human opted in, so there
# overlap is the PRIMARY key.) With nothing in flight every rank is 0 and this
# reduces to the pre-Phase-103 sort exactly. Ordering only; the Step 2 solo
# invariants + ceilings still decide the batch.
candidates.sort(key=lambda t: (
    -unlock_count.get(t["id"], 0),
    orank.get(inflight_verdict.get(t["id"], "none"), 0),
    order.get(t.get("effort"), 9),
    t["id"],
))

for t in candidates:
    v = inflight_verdict.get(t["id"], "none")
    print(f"{t['id']}\t{t.get('effort','?')}\t{t.get('blast_radius','?')}\t"
          f"unlocks={unlock_count.get(t['id'], 0)}\tinflight={v}\t"
          f"phase={t.get('phase','?')}\t{t.get('body','?')}")

# Human-readable overlap detail for the Step 4 In-flight overlap annotation.
# One `# overlap` line per (candidate, in-flight task) collision; absent when
# nothing overlaps. `# inflight-set` reports how many tasks are building now.
if inflight_count:
    print(f"# inflight-set\t{inflight_count} task(s) building now")
    for _c in candidates:
        for (otid, ev) in inflight_overlaps.get(_c["id"], []):
            shared = ", ".join(ev[:4]) + (f", +{len(ev)-4} more" if len(ev) > 4 else "")
            print(f"# overlap\t{_c['id']}\t{inflight_verdict.get(_c['id'],'none')}\t{otid}\t{shared}")
PY
```

Parse the output into the candidate list. The `unlocks=N` field is each task's `unlock_count` (open same-phase tasks that `depends_on` it); the `inflight=<verdict>` field is its collision risk against work building in another worktree right now (`likely` / `possible` / `none`, from the shared scope-overlap primitive — Leg B, Phase 103). The list is already sorted **unblocker-first, then in-flight-overlap-avoidance, then effort, then id** — so among equally-foundational candidates a non-colliding task comes first. Report total claimable count and carry both `unlocks` and `inflight` forward — `unlocks` appears in the Step 4 batch table, and any `# overlap` / `# inflight-set` detail lines feed the Step 4 **In-flight overlap** annotation. When nothing is in flight (or the primitive was unavailable), every candidate reads `inflight=none` and there are no `# overlap` lines — the sort *order* reduces to the pre-Phase-103 result exactly (only the always-present `inflight=none` field is added to each line). On a subset run, also carry every `EXCLUDED` line forward verbatim — they reappear under the Step 4 table. If zero candidates remain **without** a subset, stop:

```
No claimable tasks in the current-focus phase (`<active_phase>`) of tasks/index.yml.
Edit `current_focus:` in `tasks/index.yml § phases` if the lane should shift.
Run /next-task to surface user-action items.
```

If zero candidates remain **with** a subset, stop with the per-ID reasons instead of the generic message:

```
None of the requested tasks are claimable — per-ID reasons above.
Fix what's fixable (finish a dependency, release a lock, flip current_focus
for a genuine lane shift) or re-run /auto-build without IDs to batch the
open frontier.
```

## Step 2: Apply Batch-Sizing Rule

Inline math (no standalone script in v1 — promote to `sysop/scripts/select_batch.py` after 3-5 cycles when the shape stabilizes). The walk below is identical whether Step 1 produced the full frontier or an explicit subset — the solo invariants and ceilings never loosen because a task was named; a subset can shrink a batch, never inflate one.

> **K=12 sum ceiling + cross-module cap 2 — adopted 2026-07-17 from gdp's settled `TECH-AUTO-CLAIM-LOOSEN-GATE-EXPERIMENT` (permanent "keep" 2026-07-13).** gdp validated the ramp over 23 K=12 cycles against a 61-cycle K=8 baseline: executed/cycle **+78%** (1.34 → 2.39), $/executed down ($6.40 → $5.14), **zero reopened/abandoned merges** in either bucket, and the conflict-rate rise (2.82% → 7.89%) statistically indistinguishable from baseline (Fisher two-sided p = 0.28). The architectural/migration solo invariants (`a.`, `b.`) are **unchanged** — they guard genuine serialization, not conflict probability. Raising K is **parity/headroom, not a speed lever**: the real throughput ceiling is `/review-close` (human-paced), so this mainly cuts forced-solo batches rather than accelerating the pipeline. **Revert trigger:** a telemetry review (in a consumer running `/auto-build` at scale) showing sustained non-trivial `conflict_pre` growth *plus* a first reopened/abandoned merge → revert `K=12 → 8` and cross-module cap `2 → 1` in the rules and worked examples below. Prior ramps: K=6 → K=8 (2026-05-27), K=8 → K=12 experimental (2026-06-27). Sysop ships no telemetry stack (no consumer runs `/auto-build` at gdp's cadence yet), so the figures above are gdp's; the values are adopted on that evidence.

```
weight = effort_weight × blast_radius_weight

effort_weight:       Low=1   Medium=2   High=4
br_weight:           single-file=1   single-module=1.5
                     cross-module=2.5   architectural=4

Iterate candidates in sorted order. For each, BEFORE adding to batch, check:

1. Solo invariants — if matched and batch is non-empty → SKIP this candidate
                    if matched and batch is empty     → ADD alone, then STOP
   a. blast_radius == "architectural"
   b. body file contains "migrations/" or "ALTER TABLE" (case-insensitive)
      [open the body file ONLY when checking this candidate, not all candidates]
   c. candidate.weight > K=12 (heavier than the entire batch ceiling)
      [no other in-batch task could possibly fit; running alone is the
      only viable shape. Same Solo-invariants semantics: batch empty
      → ADD alone, STOP. This preempts rule 3's STOP-with-empty-batch
      path for any task that does exceed K. NOTE: since the K=6→K=12
      ramp (2026-07-17, see the provenance note above), the max
      non-architectural weight is High × cross-module = 10.0 ≤ 12, so
      this invariant is now DORMANT for non-architectural tasks — none
      can be heavier than the ceiling. Only a High-effort architectural
      task (weight 16) exceeds it, and all architectural tasks already
      solo via `a.` regardless of weight. Retained for
      correctness/headroom, and it re-arms if K is ever reverted.]
   [High-effort tasks are NOT solo — dropped per gdp 04cc2c84 (2026-05-21).
   Six weeks of mined data showed zero conflicts attributable to High-effort
   pairings while the gate was the binding parallelism constraint. High
   contributes weight 4 under the K=12 sum ceiling, which is the real
   conflict-throttle.]

2. Cross-module cap — if blast_radius == "cross-module" and the batch already
   contains 2 cross-module tasks → SKIP
   [cap raised 1 → 2 in the 2026-07-17 K=6→K=12 ramp — up to two
   cross-module tasks may share a batch]

3. Sum ceiling — if sum(weight) + candidate.weight > K=12 → STOP

4. Count ceiling — if raw_count + 1 > N (default 4, from Step 0) → STOP

Otherwise ADD candidate to batch and continue.
```

**Bounded body reads:** body files are opened only for candidates the Step 2 rules actually check — each add *or* skip is one read (the solo-invariant 1b check needs the body) — a handful per `/auto-build` invocation, not 35; the STOP rules bound the iteration.

**In-flight overlap is a soft signal, not a Step 2 gate (Leg B, Phase 103).** The `inflight=<verdict>` field from Step 1 already did its job: it reordered candidates so a non-colliding task is preferred among equally-foundational ones. The Step 2 rules above (solo invariants, cross-module cap, K=12/N ceilings) reason only about the tasks *within this batch* and are **unchanged** — a fresh candidate that overlaps an in-flight worktree is still eligible; it was just sorted a little lower and will be flagged for the human at Step 4. This is deliberate: worktree isolation makes an overlap a recoverable merge conflict at `/review-close`, not corruption, so the human owns the call (the guided-mode "genuine tradeoff" branch). The more aggressive option — extending the cross-module cap to *hard-exclude* against the in-flight set (an in-flight cross-module task touching module X blocks a fresh cross-module candidate touching X) — is **deferred** per `tools/COLLISION_AWARENESS_SPEC.md` § Leg B: it would silently drop legitimately-claimable work, so it ships only if the soft flag proves too weak in real use.

**Imported-provenance re-estimate:** a candidate whose `surfaced_by` contains the literal `imported` sentinel was brought in from a pre-Sysop backlog by `/onboard` — its recorded `effort`/`blast_radius` are archaeological guesses, not design-time signal. When such a candidate comes up for the checks above, its body is being opened anyway (the same single read the solo-invariant check budgets); re-estimate both fields from the body and the surface it names, and run rules 1–4 on the **heavier** of recorded vs. re-estimated, per field — never the lighter, so the discount can only tighten the gate. Show any change in the Step 4 table (`Medium→High (re-est)`), and do not rewrite `index.yml` — the human corrects the record, not the gate.

**Worked-example fixtures** (sanity-check reference; the model should be able to reproduce these on demand):

> Examples A–G assume no candidate unblocks another (every `unlock_count` = 0), so the Step 1 sort reduces to effort-ascending then id — the pre-unblocker-first order — and "first candidate" reads as before. Example H shows how a non-zero `unlock_count` reorders the pool.

- **Example A** — 4× Low + single-file → batch of 4 (sum = 4.0, under K=12). Take all four; the N=4 count ceiling stops further additions (the sum ceiling is slack here — N binds first).
- **Example B** — 2× Medium + single-module (each weight 3.0) → sum = 6.0, under K=12. Subsequent Low + single-file candidates keep fitting under the sum ceiling until the N=4 count ceiling binds: +Low (7.0, batch 3), +Low (8.0, batch 4 → N=4 STOP). At K=12 the count ceiling, not the sum ceiling, is the binding gate for small-weight tasks. (Under the old K=6 ceiling this example STOPped at sum 6.0 with just the two Mediums.)
- **Example C** — First candidate is High + architectural → batch size 1 (architectural solo invariant fires; takes the task alone regardless of effort). The High effort itself does not solo — see Example F.
- **Example D** — First candidate is Medium + cross-module (weight 5.0, under K=12). Take it. Under the raised cross-module cap of 2, a *second* cross-module task may now join: another Medium + cross-module (5.0) fits (5.0 + 5.0 = 10.0, under K=12) and is allowed (2 cross-module ≤ cap). A *third* cross-module candidate hits the cap → SKIP. A subsequent Low + single-file (weight 1.0) still fits under the sum ceiling (10.0 + 1.0 = 11.0, under K=12). (Under the old cap of 1, that second cross-module task was SKIPped and this batch stayed at one cross-module task.)
- **Example E** — First candidate's body contains `migrations/` → batch of 1 (migration serialization).
- **Example F** — First candidate is High + single-file (weight 4 × 1 = 4.0, under K=12). No solo invariant fires (architectural rule does not match single-file; migrations rule does not match the body; heavy-solo `c.` needs weight > 12). Take it. A subsequent Low + single-file (weight 1.0) fits cleanly (4.0 + 1.0 = 5.0, under K=12) — the High task pairs with the Low task. Further additions are throttled by the **N=4 count ceiling** before the K=12 sum ceiling: another Low + single-file (5.0 + 1.0 = 6.0, batch 3) still fits; a Medium + single-module after that (6.0 + 3.0 = 9.0, under K=12, batch 4 → N=4 STOP). At K=12 the count ceiling binds first for this mix. (Under the old K=6 ceiling the sum reached the ceiling first and STOPped on weight, not count.)
- **Example G** — First candidate is High + cross-module (weight 4 × 2.5 = 10.0). At K=12 this **no longer trips the heavy-solo invariant `c.`** (10.0 ≤ 12), so — unlike under the old K=6 ceiling, where `c.` forced it solo — the task is taken and can pair: a subsequent Low + single-file (1.0) fits (10.0 + 1.0 = 11.0, under K=12). The cross-module cap (rule 2) would permit a second cross-module task, but here the **sum ceiling binds first** — even the lightest cross-module task (Low + cross-module = 2.5) would push the sum to 12.5 > 12 → STOP — so this batch pairs the heavy task with a single-file Low only. This is the loosened gate's intended change: High × cross-module tasks were the single largest source of forced-solo batches under K=6 (historically, weight 10.0 > K=6 tripped `c.` and forced this shape solo; before rule `c` existed it hit rule 3's STOP-with-empty-batch and `/auto-build` refused to run).
- **Example H (unblocker-first ordering)** — Active-phase open candidates: `TECH-A` (Low + single-file, weight 1.0, **unlocks 0**), `TECH-B` (Low + single-file, weight 1.0, **unlocks 0**), `TECH-C` (Medium + single-module, weight 3.0, **unlocks 3** — three open same-phase tasks list `TECH-C` in `depends_on`). The Step 1 sort key `(unlock_count desc, effort asc, id)` orders them **`TECH-C`, `TECH-A`, `TECH-B`** — `TECH-C` leads on `unlocks=3` despite being the heaviest and highest-effort; the two leaves tie at `unlocks=0` and fall through to effort-then-id. (Pre-unblocker-first the order was `TECH-A`, `TECH-B`, `TECH-C`.) At the default N=4 all three fit (sum 3.0 + 1.0 + 1.0 = 5.0 < K, count 3 ≤ 4) → same batch *set*, only the claim order differs, so nothing observable changes downstream. **The reorder changes which tasks get claimed only when a ceiling binds:** force `N=2` and the new order claims **`TECH-C` + `TECH-A`** (the unblocker + one leaf; sum 4.0, count 2 stops the rest), leaving `TECH-B`; the old order claimed **`TECH-A` + `TECH-B`** (both leaves), leaving the unblocker `TECH-C` for a later cycle. Claiming `TECH-C` now makes its three dependents eligible next cycle — the pool-enlarging lookahead the sort exists for. **Tradeoff:** unblocker-first spent part of this batch's budget on a heavier task (weight 3.0) ahead of a 1.0 leaf to widen the *next* cycle's pool. When the unblocker is itself a heavy-solo (weight > K, rule `1c`), unblocker-first only changes the order it is *considered* — it still claims alone; the solo invariants and ceilings are unchanged by the sort.

## Step 3: Surface DB-Contention Warning

> **Parallel DB contention warning**: if the eligible batches share a verify command that mutates the same database (e.g. `APP_ENV=test pytest` against a shared test database), parallel execution can race on schema/seed fixtures and produce flaky FAIL verdicts. For DB-heavy batches, prefer running the lifecycle sequentially (one task at a time via `/claim-task`), or force concurrency=1 here by passing `1` as the bare-integer argument to `/auto-build`.

Print this warning before the confirmation gate. Do not auto-detect — that would require running each task's plan; the warning is the bake-in.

## Step 4: Confirm with Human (single destructive-gate)

Print the batch composition table:

```
## Proposed Batch

| Task                        | Effort | Blast Radius    | Unlocks | Weight |
|-----------------------------|--------|-----------------|---------|--------|
| <TASK-ID>                   | <eff>  | <br>            | <u>     | <w>    |
| ...                         | ...    | ...             | ...     | ...    |
|                                                        Total: <sum> / 12.0

The **Unlocks** column is each task's `unlock_count` from Step 1 — how many open same-phase tasks `depends_on` it. It explains the row order (unblocker-first) and does not enter the weight math. For an imported-provenance task whose fields were re-estimated (Step 2), render the changed cell as `recorded→re-estimated (re-est)` so the human sees the gate ran on the heavier value.

On a subset run, append a **Requested but not batched** list under the table — the fate of every ID the human asked for, before they confirm:

- each `EXCLUDED <id> <reason>` line from Step 1, verbatim;
- each subset task that survived the Step 1 filters but was cut by the Step 2 walk, with the **Step 2 rule** that cut it — a solo invariant, the cross-module cap, or the K=12 / N ceilings (e.g. `TECH-B — claimable, but exceeded this batch's K=12 / N=<N> ceilings — re-run /auto-build TECH-B after this batch merges`; `TECH-DB — claimable, but architectural tasks solo — re-run /auto-build TECH-DB alone`).

Shown-equals-dropped: never let a requested ID vanish between the argument list and the confirmation gate.

**In-flight overlap annotation (Leg B, Phase 103).** When Step 1 emitted any `# overlap` lines, append an **In-flight overlap** block under the table so the human sees the collision risk *before* confirming — shown-equals-claimed, the sibling of the subset "Requested but not batched" list:

```
In-flight overlap (worktrees building now: <inflight-set count>):
  ⚠ TECH-C — likely conflict with in-flight TECH-B (both touch src/api/routes.py) → expect a merge conflict at /review-close
  ⚠ FEAT-D — possible overlap with in-flight TECH-B (same dir: src/api/) → lower risk
```

Build each line from a `# overlap` record (`candidate`, `verdict`, `in-flight task`, shared paths). This is **advisory, not a veto**: the batch already de-prioritized these in the Step 1 sort, but an overlapping task the ceilings admitted stays in the proposed batch — the human may accept it (the conflict is recoverable rework). If they'd rather not, they re-run with an explicit subset that omits it. When Step 1 emitted no `# overlap` lines (nothing in flight, or no collisions), omit this block entirely.

Estimated Opus fan-out (per the lifted adversarial flow — see Steps 6a-6e):
  - Plan-only phase:    up to <N> concurrent Opus agents (one per task)
  - Adversarial phase:  up to <N> concurrent Opus agents (one per task, after plan returns)
  - Execution phase:    up to <N> concurrent Opus agents (one per task, after review absorbed)
Peak concurrency: <N>. Total spawns across the cycle: ~<3N> Opus sessions.
```

Ask the human: "proceed?". Wait for confirmation. If `--dry-run`, stop here.

This is the **only** destructive-action gate. Rolling-window refills in Step 6 draw exclusively from this confirmed batch list — no spawns are added beyond what the human approved here.

## Step 5: Sequential Pre-Claim on Main

Pre-create worktrees on `main` for the confirmed batch, mirroring `/claim-task` Step 4a-4d for each task. Sequential because each commit on `main` must be visible before the next claim runs.

For each task in the confirmed batch:

```bash
# 5.1 — flip index.yml status open → in_progress. `python3` command word + in-heredoc
# PyYAML bootstrap so `Bash(python3 -:*)` matches as a single simple command (Phase 126).
python3 - <<'PY' "$TASK_ID"
import sys
try:
    import yaml
except ImportError:  # PyYAML lives only in the project venv (BeanRider ISSUE-0049)
    import glob
    sys.path[:0] = glob.glob(".venv/lib/python*/site-packages")
    import yaml
from pathlib import Path
task_id = sys.argv[1]
index_path = Path("tasks/index.yml")
with index_path.open(encoding="utf-8") as f:
    data = yaml.safe_load(f)
found = False
for t in data.get("tasks", []):
    if t.get("id") == task_id:
        if t.get("status") != "open":
            print(f"ERROR: refusing to flip status; current='{t.get('status')}'", file=sys.stderr)
            sys.exit(1)
        t["status"] = "in_progress"
        found = True
        break
if not found:
    print(f"ERROR: {task_id} not in index", file=sys.stderr)
    sys.exit(1)
with index_path.open("w", encoding="utf-8") as f:
    yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False, allow_unicode=True, width=120)
PY

# 5.2 — create worktree + lock
bash sysop/scripts/claim_task.sh --lock "$TASK_ID" "$BRANCH_NAME"
# If non-zero exit: roll back the index.yml flip with `git checkout tasks/index.yml`,
# commit the rollback with `git commit -m "rollback: <TASK_ID> claim failed"`,
# and abort the batch (don't leave half-claimed). Report which task failed.

# 5.3 — validate schema invariants
.venv/bin/python3 sysop/scripts/validate_tasks.py
# If non-zero: report validator output verbatim; abort the batch.

# 5.4 — commit the claim (Rule A: assert HEAD is still main before each loop commit —
#        another Sysop session could have moved it; see _shared/main-push-guard.md.
#        On failure STOP and reconcile via git reflog, do not commit onto the wrong branch.)
test "$(git rev-parse --abbrev-ref HEAD)" = "main" || {
  echo "HEAD is not main (a concurrent actor moved it) — STOP."; exit 1; }
git add tasks/index.yml && git commit -m "claim: mark $TASK_ID as in-progress"
```

Branch-name generation (matches `/claim-task` Step 3): lowercase task ID with prefix `feat/` / `tech/` / `data/` / `ux/` / `fix/` based on the ID prefix; or honour `branch:` field in `index.yml` if present.

Collect `(task_id, worktree_path, branch_name)` tuples. Worktree path is `../$(basename "$REPO_ROOT")-<task-id-lowercase>/` relative to the project root — the path is computed by `sysop/scripts/claim_task.sh` itself (see `claim_task.sh:55`), so the orchestrator just records what the script printed rather than recomputing.

**Abort handling:** if any pre-claim step fails, roll back the partial state for that task (`git checkout tasks/index.yml` then `git commit -m "rollback: <TASK_ID> claim failed"`, plus `bash sysop/scripts/cleanup_worktrees.sh --force` on the orphan if created) and report which task failed. Tasks already pre-claimed earlier in the batch stay claimed — the human can either run `/auto-build` again to spawn agents for them, or `/document-work` / `/review-close` them manually.

## Step 6: Per-Task Plan → Review → Execute (orchestrator-driven, three sequential phases)

**Why three phases instead of one.** Historically Claude Code's harness blocked recursive Agent tool spawns (lifted in 2.1.172, 2026-06-10, with a 5-level cap), and spawned agents lose the fresh-eyes property if they try to self-administer the adversarial review. The orchestrator-driven shape is retained even on harness versions that permit nesting: the orchestrator (top-level session) lifts the adversarial review up one level — spawn a plan-only agent, then a separate adversarial-reviewer agent, classify findings, then spawn the execution agent. This keeps the Phase 37 envelope contract flat (validated for direct children only) and stays portable to non-Claude-Code consumers. See `_shared/adversarial-review.md` § "Harness constraint" for the full rationale and the re-evaluation trigger.

Spawned agents must NOT use `isolation: "worktree"` (worktree pre-exists from Step 5) and MUST set `model: "opus"` (fresh reasoning on code is worth the cost; matches every other adversarial-spawn site in Sysop).

The three phases run **sequentially within a task** but **in parallel across tasks** (rolling window up to N — shape adapted from `/auto-fix`'s batch-orchestration pattern). Peak concurrency is N; total spawns across the cycle ≈ 3N (modulo parked tasks that skip Phase 6e).

### Phase 6a: Plan-Only Agents (parallel across tasks)

In a **single message**, spawn `min(N, len(batch))` plan-only agents via parallel `Agent` tool calls. Each call:

- `subagent_type`: `"general-purpose"`
- `model`: `"opus"`
- `run_in_background`: `true`
- Do NOT set `isolation: "worktree"`.
- `description`: `"Plan <TASK_ID>"`
- `prompt`: the **Plan-Only Agent Prompt** in Step 7a, filled with `(task_id, worktree_path, branch_name)`.

When each plan-only agent returns, extract the plan text from the fenced ```` ```plan ```` block in its final message. Store as `PLAN_TEXT[<TASK_ID>]`.

**Post-Phase-6a integrity check.** The plan-only agent is instructed not to commit anything. Verify in the orchestrator BEFORE spawning the reviewer:

```bash
# Assert the worktree branch HEAD is unchanged from before the plan agent ran.
# If new commits exist, the plan agent violated the contract — abort and park.
NEW_HEAD=$(git -C "$WORKTREE_PATH" rev-parse HEAD)
if [ "$NEW_HEAD" != "$PRE_PLAN_HEAD" ]; then
  echo "PLAN-ONLY-VIOLATION: $TASK_ID committed during plan phase; parking"
  mkdir -p "$WORKTREE_PATH/.auto-build"
  echo "PLAN_PHASE_VIOLATION: plan-only agent committed $(git -C "$WORKTREE_PATH" log --oneline "$PRE_PLAN_HEAD..HEAD")" \
    > "$WORKTREE_PATH/.auto-build/review.md"
  # Mark this task PARKED and skip Phases 6b-6e for it.
fi
```

Capture `PRE_PLAN_HEAD` immediately before each Phase-6a spawn so the comparison is meaningful. The orchestrator holds one `PRE_PLAN_HEAD` value per task in its conversation context (NOT in a shell associative array); because the capture happens before the spawn, there is no parallel-race window.

### Phase 6b: Adversarial-Reviewer Agents (parallel across tasks)

For each task whose plan-only agent returned cleanly (no Phase-6a violation), spawn one adversarial-reviewer agent. Run these in parallel across tasks via a single message with `min(N, len(non_parked))` parallel `Agent` calls. Each call:

- `subagent_type`: `"general-purpose"`
- `model`: `"opus"`
- `run_in_background`: `true`
- `description`: `"Adversarial plan review <TASK_ID>"`
- `prompt`: the **Adversarial-Reviewer Agent Prompt** in Step 7b — the `PLAN_TEXT[<TASK_ID>]` verbatim, followed by the Prompt Template block from `.claude/skills/_shared/adversarial-review.md`.

When each reviewer returns, store its findings as `RAW_FINDINGS[<TASK_ID>]`.

### Phase 6c: Classify Findings (orchestrator-internal)

The orchestrator — at its own top level, where the Classification Rubric is the orchestrator's job to execute — classifies each finding in `RAW_FINDINGS[<TASK_ID>]` per the rubric in `_shared/adversarial-review.md`:

- **`fixable`** — incorporate inline.
- **`blocker`** — halt and park.

This is **not** delegated to another sub-agent. The orchestrator reads the rubric and applies it directly. Rationale: classification is the seam where the human (via the orchestrator) stays the gate; outsourcing it to a third sub-agent would just push the same parse-and-judge logic one more layer down without adding fresh-eyes value.

### Phase 6d: Halt-on-Blocker OR Write Revised Plan

For each task:

- **If any finding is `blocker`** → mark the task `PARKED`. Skip Phase 6e for it. Write the verdict and plan to a scratch directory in the worktree so the human picking up the parked task can resume:

  ```bash
  mkdir -p "$WORKTREE_PATH/.auto-build"
  printf '%s\n' "$PLAN_TEXT" > "$WORKTREE_PATH/.auto-build/plan.md"
  printf '%s\n' "$RAW_FINDINGS" > "$WORKTREE_PATH/.auto-build/review.md"
  ```

  The orchestrator does NOT commit these files — they are scratch for the human. Step 8 references the paths in the final report.

  **Mirror the verdict to a central archive so it survives worktree cleanup.** The per-worktree `plan.md`/`review.md` above are the *only* record of why the task parked — and they are destroyed the moment the worktree is removed (`cleanup_worktrees.sh --force` removes the worktree wholesale). A parked task is by definition resumed *later*, often after that cleanup has run, so the worktree scratch alone loses the verdict exactly when the human comes back for it. Write a second copy at the **project root** — where the orchestrator runs, so it outlives any worktree — gitignored under `.auto-build/`:

  ```bash
  mkdir -p .auto-build/parked
  TS=$(date -u +%Y%m%dT%H%M%SZ)
  ARCHIVE=".auto-build/parked/${TASK_ID}__${TS}.md"
  {
    printf '# %s — PARKED %s\n\n' "$TASK_ID" "$TS"
    printf '## Plan (verbatim)\n\n%s\n\n' "$PLAN_TEXT"
    printf '## Adversarial verdict (verbatim)\n\n%s\n' "$RAW_FINDINGS"
  } > "$ARCHIVE"
  ```

  The UTC timestamp keys the filename: a task parks at most once per cycle and cycles run minutes apart, so `<TASK_ID>__<timestamp>` is unique per park. This archive is the **durable** record — worktree cleanup never touches the project-root `.auto-build/parked/`. (No telemetry is emitted here; this is the standalone park-archive fix, not the `parked_reason`/`task_outcome` instrumentation it was extracted from.)

- **If all findings are `fixable` (or zero findings)** → the orchestrator builds a `REVISED_PLAN` from `PLAN_TEXT` + `RAW_FINDINGS` by passing both into the Phase-6e execution agent's prompt (one-shot inline absorption). No separate plan-revise agent in v1 — see "Out of scope for v1" below.

### Phase 6e: Execution Agents (parallel across tasks)

For each non-parked task, spawn one execution agent. Run these in parallel across tasks via a single message with parallel `Agent` calls (rolling-window refill if there are more non-parked tasks than the concurrency cap). Each call:

- `subagent_type`: `"general-purpose"`
- `model`: `"opus"`
- `run_in_background`: `true`
- Do NOT set `isolation: "worktree"`.
- `description`: `"Execute <TASK_ID>"`
- `prompt`: the **Execution Agent Prompt** in Step 7c, filled with `(task_id, worktree_path, branch_name, plan_text, raw_findings)`.

**Pre-execution HEAD capture (load-bearing for Phase 7).** Immediately BEFORE spawning each Phase-6e agent, capture the worktree branch HEAD so Phase 7 can compare against it:

```bash
# Captured per-task at Phase-6e spawn time. The orchestrator holds one value
# per task in its conversation context (NOT in a shell associative array) — same
# shape as PRE_PLAN_HEAD in Phase 6a. Because the orchestrator captures these
# values in its own context before spawning, there is no parallel-race window
# even when Phase 6e fans out across tasks.
PRE_EXEC_HEAD=$(git -C "$WORKTREE_PATH" rev-parse HEAD)
```

Phase 7 (below) uses this value to distinguish "agent omitted the envelope but the work landed" from "agent failed and nothing landed".

### Rolling-window refill on completion

When a background agent's completion notification arrives in any phase:

1. Collect that agent's result. For Phase 6e, get the envelope by trying — in this order, first hit wins — (a) read `.subagent-envelopes/<TASK_ID>.json` (Phase 37 `SubagentStop` hook output; resolve `<repo>/.subagent-envelopes/` against the main repo root via `git rev-parse --git-common-dir`); (b) regex-parse the YAML envelope from the LAST fenced block of the agent's return text (existing behavior — see Step 7c). After consuming the JSON file, `rm -f .subagent-envelopes/<TASK_ID>.json` to keep the dir clean for in-flight handoff; leave `_unparseable_*.json` diagnostics in place.
2. If the queue still has unstarted batch tasks at the same phase, spawn one more agent with the same shape in a single new message.
3. No polling, no sleeping — the harness delivers completion notifications.

When all Phase-6e agents have returned (or all tasks parked), proceed to Step 8.

## Step 7: Agent Prompt Templates

Three distinct prompts, one per phase. Each is verbatim with placeholders filled. **None of these prompts instructs the agent to call the Agent tool** — the orchestrator does all fan-out itself, keeping the spawn hierarchy flat (a deliberate choice even on Claude Code ≥2.1.172, where nesting is permitted; see Step 6).

### Step 7a: Plan-Only Agent Prompt

---

**START OF PLAN-ONLY AGENT PROMPT**

You are planning roadmap task `<TASK_ID>` for the `/auto-build` orchestrator. Your **only** job is to produce a structured plan in the format below and emit it in your final message. Do NOT execute, do NOT call `ExitPlanMode`, do NOT spawn sub-agents, do NOT commit or modify files.

The worktree at `<WORKTREE_PATH>` is already claimed — lock at `.locks/<TASK_ID>.lock`, branch `<BRANCH_NAME>`, `tasks/index.yml` flipped to `in_progress` on main by the orchestrator.

**Working directory:** `<WORKTREE_PATH>` (cd here first).

### Steps

1. **Read context.** Open `tasks/open/<TASK_ID>.md` for the task brief. Read `.claude/convention_map.md` and `.claude/security_map.md` for files the task is likely to touch. Read sibling files referenced in the task body as needed.
2. **Produce the plan.** Structure:
   - **Task summary** — one paragraph restating the task and goal.
   - **`## Constraints & Risks`** preamble — one bullet per file/directory the plan will touch, citing applicable conventions from `.claude/convention_map.md` AND applicable security checks from `.claude/security_map.md`, plus cross-cutting rules (logger formatting, APP_ENV default, log sanitization, fetch redirect guards). One bullet per risk; no prose padding. Include a `### Coverage gap` subsection listing files with no matching map section (write `_(none)_` if every file matches).
   - **`## Implementation Steps`** — numbered steps with concrete file paths, line ranges, and expected diffs.
3. **Hard constraints:**
   - Do **NOT** edit any file in the worktree (no `Edit` / `Write` tool calls).
   - Do **NOT** run `git commit` or any state-changing command.
   - Do **NOT** call `ExitPlanMode` (you are not in plan mode).
   - Do **NOT** invoke the Agent tool — the orchestrator handles fan-out.

### Final-message format

Emit your plan as the LAST content in your final message, wrapped in a fenced ```` ```plan ```` block (exactly that fence tag — the orchestrator parses on it):

````
```plan
<task summary>

## Constraints & Risks
- ...

### Coverage gap
- ...

## Implementation Steps
1. ...
2. ...
```
````

If the consuming project wires up sub-agent cost attribution, also emit `SPEND_USD: <float>` on a line BEFORE the fenced block. Otherwise omit it — `_shared/adversarial-review.md § Caller contract` documents the opt-in pattern. No other content after the closing fence.

**END OF PLAN-ONLY AGENT PROMPT**

---

### Step 7b: Adversarial-Reviewer Agent Prompt

The orchestrator constructs this prompt as `PLAN_TEXT[<TASK_ID>]` verbatim, immediately followed by the **Prompt Template** block copied verbatim from `.claude/skills/_shared/adversarial-review.md`. The sub-agent returns a prioritized list of concrete `file:line` findings under 500 words.

Set the same agent params as Step 7a (`subagent_type: "general-purpose"`, `model: "opus"`, `description: "Adversarial plan review <TASK_ID>"`, `run_in_background: true`).

No additional wrapper text — the shared template already supplies the framing. The orchestrator stores the returned text as `RAW_FINDINGS[<TASK_ID>]`.

### Step 7c: Execution Agent Prompt

---

**START OF EXECUTION AGENT PROMPT**

You are executing roadmap task `<TASK_ID>`. The orchestrator has already:

- Claimed the task: worktree at `<WORKTREE_PATH>`, lock at `.locks/<TASK_ID>.lock`, branch `<BRANCH_NAME>`, `tasks/index.yml` flipped to `in_progress` on main.
- Produced an implementation plan (`<PLAN_TEXT>` below).
- Run a fresh-eyes adversarial review of that plan (`<RAW_FINDINGS>` below) and classified all findings as `fixable`. No `blocker` findings remain — if any had existed, this agent would not have been spawned.

**Working directory:** `<WORKTREE_PATH>` (cd here first; do not run from the project root).

### Plan (as produced by the plan-only agent)

```
<PLAN_TEXT verbatim>
```

### Adversarial review findings (all `fixable`)

```
<RAW_FINDINGS verbatim>
```

### Sequence

1. **Absorb findings into the plan.** Re-read the plan above. For each `fixable` finding in `<RAW_FINDINGS>`, decide:
   - **Incorporate** — revise your mental model of the plan so the implementation accounts for it.
   - **Reject after consideration** — document the rejection rationale inline when you implement, so the same issue does not resurface during human review.
2. **Call `ExitPlanMode`** with the revised plan as the plan content. This is the agent's only ExitPlanMode call.
3. **Implement** per the revised plan.
4. **Post-fix convention verification** (the same gate `/claim-task` Step 7's reviewer-executor runs internally): list changed files via `git diff --name-only main...HEAD`, check each against `.claude/convention_map.md` for the relevant section, scan new lines for the listed conventions, fix any regressions before committing.
4b. **Run the consumer's pre-merge verification gates.** The consumer project's `<project>/CLAUDE.md` has a `## Pre-merge verification` section (per WORKFLOW.md § 6.1) that may contain two subsections:
   - **`### Always`** — full-tree commands run unconditionally (lint, typecheck, tests).
   - **`### Ratchet (changed files only)`** — a single bash block that filters `git diff --name-only origin/main...HEAD` to specific file types and invokes lint/typecheck against changed files only (Phase 17 split shape; empty filtered list short-circuits and passes).

   Run the commands listed under each subsection that is present. If both subsections are absent, skip this step — `/review-close` will run any project-side verification at merge time, and the consumer accepts the risk.

   Treat any non-zero exit like an implementation finding: fix the underlying issue, do not silence it without a `# type: ignore[...]` or `// eslint-disable-next-line <rule> -- <reason>` justified inline. If the gate exits non-zero and you cannot fix it (e.g., missing toolchain dependency in the worktree), emit `STATUS: FAILED` with the stderr in `ERROR`.
5. **Post-fix UI verification** (the same gate `/claim-task` Step 7's reviewer-executor runs internally) only if any `frontend/` files changed — invoke `.claude/skills/_shared/ui-verify.md`.
5b. **Invoke `/document-work --non-interactive`** via the `Skill` tool to commit your work, write `.pending-docs/<sanitized-branch>.md`, and enforce the follow-up stub check.

   The `--non-interactive` flag (see `/document-work` Step 0) tells the skill to:
   - Derive the commit message from `tasks/index.yml § tasks[]` `title:` + `<TASK_ID>` rather than prompting the human (Step 2).
   - Skip Step 4's "confirm pending docs" human-confirm prompt; the orchestrator + reviewer pair gated the work. The pending-docs body prints to stdout so this agent's transcript captures it.
   - Skip Step 5's `git push` (do NOT push from the worktree — `/review-close` owns the push to origin).

   Non-interactive invariants the agent MUST honor when invoking `/document-work --non-interactive`:
   - **Step 3b follow-up stub check** — if you surfaced a follow-up task in the work, file the stub (entry in `tasks/index.yml` + body file under `tasks/open/`) BEFORE invoking `/document-work`. The relaxed hard-constraint below permits this. The Step 3b gate fires whether invoked interactively or via `--non-interactive`.

   If `/document-work` exits non-zero (e.g., Step 3b hard-fail on an unfiled follow-up ID), treat it as the existing Step 7 failure path: do not retry; emit `STATUS: FAILED` with the `/document-work` stderr in `ERROR`.
6. On success → emit envelope with `STATUS: EXECUTED`.
7. On exception or test failure → do **NOT** add a retry loop. The post-fix convention pass in step 4 above already includes one-fix-and-recheck semantics; that's the budget. Emit envelope with `STATUS: FAILED` and the error text in `ERROR`.

### Hard constraints

- Do **NOT** invoke the Agent tool — the orchestrator has already done the planning + adversarial-review fan-out. No nested adversarial pass, even on harness versions (Claude Code ≥2.1.172) where nested spawns are permitted.
- Do **NOT** flip `status:` fields in `tasks/index.yml` — `/claim-task` (open → in_progress) and `/review-close` (in_progress → done) own status transitions.
- ADDING a new task entry (a follow-up surfaced during the work) IS allowed and expected. `/document-work` Step 3b (follow-up stub check) requires every `<PREFIX>-<NAME>` token in pending-docs prose to resolve to a real entry in `tasks/index.yml` — file the entry + body file before invoking `/document-work`, or whitelist it intentionally per `tasks/schema.md`.

### Required final-message format

Emit exactly this YAML block as the LAST content in your final message, with NO content after the closing backticks:

```yaml
TASK: <TASK_ID>
STATUS: EXECUTED | FAILED
WORKTREE: <absolute path, no trailing slash>
BRANCH: <branch name>
PARKED_REASON: none
ERROR: <error description if FAILED, else "none">
```

If the consuming project wires up sub-agent cost attribution, also emit `SPEND_USD: <float>` on a line BEFORE the closing envelope. Otherwise omit it — `_shared/adversarial-review.md § Caller contract` documents the opt-in pattern.

Execution agents never emit `STATUS: PARKED_ON_QUESTION` — parking happens at the orchestrator layer in Phase 6d before the execution agent is spawned. A malformed envelope (missing keys, content after the closing backticks, status not in {EXECUTED, FAILED}) causes the orchestrator to classify your run as `FAILED` with reason `envelope parse error` — subject to the **Phase 7: Envelope Recovery** filesystem check below, which can reclassify an envelope-parse miss back to `EXECUTED` when the commit landed and `.pending-docs/<branch>.md` exists. The valid envelope STATUS enum remains `{EXECUTED, FAILED}`; `EXECUTED (envelope-recovered)` is an orchestrator-synthesized rendering annotation used only in the Step 8 report — execution agents must not emit it.

**END OF EXECUTION AGENT PROMPT**

---

## Phase 7: Envelope Recovery

**Why this exists.** Execution agents sometimes complete their work cleanly (commit landed on the worktree branch AND `.pending-docs/<branch>.md` written by `/document-work`) but omit the required Step 7c YAML envelope. Strict envelope-only classification would FAIL these runs as `envelope parse error` despite the substantive work being correct. Phase 7 cross-checks the filesystem so an envelope-discipline miss does not become a false-positive FAIL — while remaining observed-state-only (it never synthesizes an EXECUTED claim where work did not actually land).

**Scope.** Phase 7 fires ONLY for tasks whose Phase-6e envelope failed to parse via BOTH the Phase 37 `SubagentStop` JSON path AND the existing regex-parse-the-return-text path. Tasks resolved via either of those two upstream paths pass through Phase 7 untouched (no extra git invocations). With the Phase 37 hook in place, Phase 7 moves from "expected sometimes-fires" to "rare-edge-case-only" — fires only when the sub-agent never emitted any envelope at all (e.g., crashed mid-write) or both parsers genuinely missed the envelope's existence.

### Phase 7 procedure (per task with malformed/missing envelope)

The orchestrator (top-level session, holding the per-task `PRE_EXEC_HEAD` captured in Phase 6e) runs:

```bash
# Canonical branch-name sanitization — matches /document-work's convention
# (git branch --show-current | tr / -). Do NOT substitute a bash parameter
# expansion; keep the tr form for parity with the rest of the workflow.
BRANCH_NAME=$(git -C "$WORKTREE_PATH" branch --show-current | tr / -)

# Filesystem check: did the work actually land?
NEW_COMMITS=$(git -C "$WORKTREE_PATH" log --oneline "$PRE_EXEC_HEAD..HEAD" | wc -l | tr -d ' ')
PENDING_DOC_EXISTS=$(test -f "$WORKTREE_PATH/.pending-docs/$BRANCH_NAME.md" && echo true || echo false)

# Load-bearing AND-check: BOTH conditions must hold for recovery. Either one
# alone is insufficient — commits without a pending-doc means /document-work
# never ran (so /review-close has nothing to consolidate), and a pending-doc
# without commits means the agent fabricated documentation against an empty
# diff. Recovery is observed-state-only; it confirms an envelope-parse miss
# against the filesystem, it does NOT synthesize a new EXECUTED claim.
if [ "$NEW_COMMITS" -ge 1 ] && [ "$PENDING_DOC_EXISTS" = "true" ]; then
  # Reclassify for Step 8 reporting only — the YAML envelope STATUS enum
  # itself remains {EXECUTED, FAILED}; this label is an orchestrator-side
  # rendering annotation, not a value any agent emits.
  RECOVERED_STATUS="EXECUTED (envelope-recovered)"
else
  # Keep FAILED with a more specific reason than bare "envelope parse error".
  RECOVERED_STATUS="FAILED"
  RECOVERED_ERROR="envelope parse error AND no committed work found"
fi
```

### Reporting in Step 8

Tasks reclassified to `EXECUTED (envelope-recovered)` MUST appear in the Step 8 result table with that exact sub-status (not bare `EXECUTED`) so envelope-discipline drift is visible to the human merge-gate. The Notes column should call out the recovery (e.g., `envelope omitted; recovered via filesystem check (N commits, pending-doc found)`).

### Acceptance test (manual)

A deliberately broken envelope test — return only the literal text `done.` from the execution agent — should:

- Recover to `EXECUTED (envelope-recovered)` in Step 8 if both the commit and `.pending-docs/<branch>.md` landed.
- Stay `FAILED` with reason `envelope parse error AND no committed work found` if either is missing.

## Step 8: Final Report

After all in-flight Phase-6e agents have returned envelopes — and all Phase-6d-parked tasks have been written to their scratch directories — produce the final report.

If `SPEND_USD:` was wired in by the consuming project, cumulative spend aggregates from every spawned sub-agent across all three phases (plan + reviewer + execution) plus any spend the orchestrator itself incurred. Tasks parked in Phase 6d still contribute the plan + reviewer spend even though no execution agent ran. If `SPEND_USD:` is not wired in, omit the spend column from the table and the cumulative-spend line.

Print the result table:

```
## Auto-Build Complete

| Task        | Status                          | Worktree                            | Branch        | Spend (plan+rev+exec) | Notes                                            |
|-------------|---------------------------------|-------------------------------------|---------------|-----------------------|--------------------------------------------------|
| TECH-X      | EXECUTED                        | ../<project>-tech-x/                | tech/tech-x   | $X.XX                 | .pending-docs/<branch>.md written; ready for /review-close |
| TECH-W      | EXECUTED (envelope-recovered)   | ../<project>-tech-w/                | tech/tech-w   | $X.XX                 | envelope omitted; recovered via Phase 7 filesystem check (N commits, pending-doc found) |
| TECH-Y      | PARKED                          | ../<project>-tech-y/                | tech/tech-y   | $X.XX                 | <one-line summary>; verdict at .auto-build/review.md |
| TECH-Z      | FAILED                          | ../<project>-tech-z/                | tech/tech-z   | $X.XX                 | <error from ERROR>                               |

Cumulative orchestrator + agent spend: $X.XX  (logged only; no enforcement in v1)

Next steps:
  - Resume PARKED tasks: cd into the listed worktree. The orchestrator wrote
    the plan-only agent's raw plan to `.auto-build/plan.md` and the adversarial
    verdict to `.auto-build/review.md` (parking happens BEFORE inline absorption,
    so plan.md is the unrevised plan). Read both, resolve the blocker (answer
    the question, add the missing source data, etc.), then continue the work
    manually — call `ExitPlanMode` yourself and implement, or invoke `/claim-task`
    to re-enter plan mode against the revised context. The `.auto-build/` scratch
    directory is not committed by the orchestrator; clean it up before
    `/document-work`. If the worktree was already cleaned up (e.g. via
    `cleanup_worktrees.sh --force`), the same plan + verdict survive at the
    project root under `.auto-build/parked/<TASK_ID>__<timestamp>.md` — the
    durable copy the orchestrator mirrored in Phase 6d.
  - For EXECUTED tasks: start a fresh session (`/clear`, or a new terminal),
    then run /review-close to merge each branch — `/review-close` is
    context-independent (it reconstructs from the committed branches, the
    `## Test decision` records, and `.pending-docs/`), so a clean session
    reviews every pending branch even-handedly instead of inheriting one
    task's implementation context. It discovers the `.pending-docs/<branch>.md`
    each execution agent wrote and consolidates per the consumer's
    `## Pending documentation routing` in `<project>/CLAUDE.md`. The human
    stays the merge gate.
  - For FAILED tasks: cd into the worktree, inspect git status and recent logs,
    then either fix-and-resume or roll back via `bash sysop/scripts/cleanup_worktrees.sh --force`
    (which removes the worktree and clears the lock).
```

After printing the table, the orchestrator's job is done. It does NOT run `/review-close`. The human is the merge gate.

## Done (v1 success criteria)

- `/auto-build` selects a batch using the Step 2 batch-sizing rule and presents per-task math to the human (Step 4).
- After confirmation, the orchestrator pre-claims each task on `main` (Step 5), then runs the three-phase per-task pipeline: Phase 6a plan-only agents → Phase 6b adversarial-reviewer agents → Phase 6c orchestrator classification → Phase 6d halt-or-revise → Phase 6e execution agents (Steps 6-7).
- Phase-6d `blocker` classification parks the task (lock + worktree intact, `plan.md` + `review.md` written to `<worktree>/.auto-build/`, and the plan + verdict mirrored to the durable project-root archive `.auto-build/parked/<TASK_ID>__<timestamp>.md` so they survive worktree cleanup); other tasks continue.
- Unparked tasks reach Phase 6e and execute. Final report (Step 8) prints `EXECUTED` / `PARKED` / `FAILED` with worktree paths.
- One full cycle on a 2-task batch of Low-effort + single-file tasks from the consumer's `tasks/open/` completes end-to-end, and the human runs `/review-close` cleanly on each resulting branch.
- A deliberately-broken plan (task body that mentions a non-existent file) causes Phase 6c to classify a `blocker` and Phase 6d to park the task — visible in the final report and via the scratch files.
- No nested Agent tool calls anywhere in the spawned-agent prompts (by design — the orchestrator does all fan-out, even on Claude Code ≥2.1.172 where nesting is permitted).
- No model-guard halt anywhere in the flow (Sysop Phase 21 removed the transcript-based guard; the harness honors `model: opus` frontmatter for every spawned agent directly).

## Out of scope for v1

Deferred to v2+:

- **Hard spend / token caps.** v1 logs cumulative spend (when wired up by the consumer) but does not enforce a kill switch.
- **Timeout-and-release on parked agents.** Default is parked-forever — the human resumes manually.
- **Auto-merge of clean batches.** Human stays the merge gate.
- **`/parked-agents` companion or resume helper.** Manual `cd` into the worktree.
- **Standalone `sysop/scripts/select_batch.py`.** Promote after 3-5 cycles when the batch-math shape stabilizes.
- **Auto-detecting DB-contention from task bodies.** The verbatim warning at Step 3 is the bake-in.
- **Separate plan-revise agent in Phase 6d.** v1 absorbs `fixable` findings inline by passing `PLAN_TEXT + RAW_FINDINGS` into the execution agent's prompt. A cleaner alternative is a third sub-agent that produces an explicit `REVISED_PLAN` text the execution agent consumes verbatim. Promote when the inline-absorption shape shows drift in practice.
- **Reviewer-executor collapse for `/auto-build` Phase 6b-6e.** `/claim-task` collapses adversarial review + classification + plan revision + implementation into one cold-context reviewer-executor sub-agent (see `_shared/adversarial-review.md § "Reviewer-executor variant"`). The handoff guidance there is "validate the interactive shape under `/claim-task` first; the auto-build port is a follow-up after several `/claim-task` runs prove out the prompt discipline." Bundle the collapse only into `/claim-task` for now; `/auto-build` keeps the three-phase (plan-only → adversarial-reviewer → execution) shape.

## First downstream consumer

TBD — Sysop has no consumer with a parallelizable batch yet. The skill ships speculatively against the day a real consumer needs it. The first cycle will surface friction via the consumer's `SYSOP_ISSUES.md`; iterate from there.
