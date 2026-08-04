---
name: claim-task
description: Claim a roadmap task or review batch — creates lock and worktree, then orchestrates plan → adversarial review → execute
argument-hint: "<TASK_ID or BATCH_NUMBER> [--review-plan | --no-review-plan] [--resume <RUN_ID>]"
model: opus
disallowed-tools: Edit, Write, NotebookEdit
---
<!-- sysop:model-roles frontmatter=reasoning inline=reasoning -->

Claim a roadmap task or review batch, create an isolated worktree, then **orchestrate** the work: spawn a planner, spawn an independent reviewer, classify the findings yourself, optionally gate on the human, spawn an executor. Follow these steps in order.

> **This skill is an orchestrator. It never implements.** It does not enter plan mode, does not call `ExitPlanMode`, and does not edit files. Its whole body is: claim, spawn, gate, spawn, report.
>
> **What `disallowed-tools` above does and does not buy** — state this honestly rather than treating the frontmatter as a proof. It denies the `Edit` / `Write` / `NotebookEdit` tools, so the orchestrator cannot quietly become the implementer by reaching for them. It is **partial by design**: `Bash` stays allowed, so shell redirects and `sed -i` are not covered. **Non-Claude-Code harnesses ignore the key entirely**, so it does nothing for a Codex consumer. It fires only when the harness *activates* this skill — when an agent is instead told to read this `SKILL.md` and follow it (path-based invocation, the only option on some harnesses), the frontmatter never fires. And it is **turn-scoped**: the documented behaviour is that the restriction clears when the user sends their next message, so any run in which the human types anything has lost it from that point. Whether it survives a sub-agent return, an `AskUserQuestion` answer, or a nested `Skill` invocation is **not established in either direction** — probed 2026-07-31 and no documentation was found for any tool-mediated boundary, which is weaker than proof that none exists and is exactly why nothing here rests on the answer. **Nothing in this skill may depend on the guard's reach past the step that invoked it.** The durable protection against an orchestrator drifting into implementing is the split spawns and the artifact set below, not this key.

> **Helper names** referenced in this skill (e.g., `_sanitize_log`, `useAbortableFetch`, `getDisplayError`, `redact_api_keys`, `shared_cli.py`) are placeholders — substitute the equivalent helpers from your project's `convention_map.md`. Worked examples may also reference specific batch numbers, file paths, or env-var names from the originating project; treat those as illustrations, not literal requirements.

## Pre-flight: Permission Guard

Verify `.claude/settings.json` carries the allow-rules this skill depends on. Under `dontAsk` mode a missing worktree-add or branch-creation rule is auto-denied with no prompt, halting before the workspace is created.

Read `.claude/settings.json` and confirm `permissions.allow` contains:

- `Bash(git checkout:*)` — Step 4 rollback path on 4b/4c failure (`git checkout tasks/index.yml`).
- `Bash(git worktree add:*)` — transitively invoked by `sysop/scripts/claim_task.sh`.
- `Bash(bash sysop/scripts/claim_task.sh:*)` — Step 2's `--entry-state` query **and** Step 4b's worktree + lock creation. One rule covers both: the trailing `:*` is a prefix match over the whole argument string, so no separate `--entry-state` rule is needed (and adding one would be dead). Verified against Phase 152's finding that rules seeded against invocations which bind none are worse than no rule.
- `Bash(bash sysop/scripts/batch_work.sh:*)` — Step 4 review-batch path.
- `Bash(python3 -:*)` — Step 1's `--resume` validation, Step 2's `tasks/index.yml` lookup, Step 4a's yaml-round-trip status flip, Step 7a's post-plan integrity check, **and every write the orchestrator makes at Steps 7-pre, 7c and its park path** (all are `python3 - <<'PY'` heredocs, single simple commands, so one rule covers them). This is deliberate: routing the orchestrator's reads and writes through an interpreter it is already permitted to run means the reshape adds **no** new permission surface, and it does not depend on the auto-classifier's treatment of bare `mkdir` / `cp` / `test`. It also survives this skill's `disallowed-tools: Edit, Write, NotebookEdit` frontmatter, which a `Write`-tool artifact write would not.
- `Bash(python3 sysop/scripts/validate_tasks.py)` / `Bash(python3 sysop/scripts/validate_tasks.py:*)` and the `.venv/bin/python3 sysop/scripts/validate_tasks.py` / `.venv/bin/python3 sysop/scripts/validate_tasks.py:*` venv variants — Step 4c post-claim validator (the venv form is preferred per Phase 45b; the bare form remains for non-venv consumers).
- `Bash(python3 sysop/scripts/scope_overlap.py:*)` (and the `.venv/bin/python3` variant) — Step 2's non-blocking overlap advisory. The `git -C <worktree> diff` it shells out to needs **no** separate rule (it's a subprocess of the permitted python call, and read-only `git` auto-passes per `_shared/permission-guard.md` § Notes). This rule is **not** load-bearing — a missing rule (or any non-zero exit) just means the advisory is skipped; the claim still proceeds.
- `Bash(git add tasks/index.yml)` — Step 4d commits the claim.
- `Bash(git commit -m claim:*)` — Step 4d commit message shape.

If any are missing, stop with the `_shared/permission-guard.md` § Algorithm step 5 message (one-line reason: "creates an isolated worktree and a feature branch for the claimed task; queries + updates `tasks/index.yml` via heredoc'd python; runs the schema validator before committing the claim"). Do not proceed — unless the guard's step 3 mode check applies.

If `$ARGUMENTS` contains `--skip-permission-guard`, print a one-line warning and continue.

## Step 1: Parse Argument & Classify

Parse `$ARGUMENTS`:

- **Bare integer** (e.g., `116`) or **`BATCH-<N>`** → review batch. Extract the number.
- **Known prefix** (`FEAT-*`, `TECH-*`, `DATA-*`, `UX-*`, `FIX-*`) → roadmap task.
- **Empty or unrecognized** → print usage and stop:
  ```
  Usage: /claim-task <TASK_ID | BATCH_NUMBER>

  Examples:
    /claim-task FEAT-STUDIO-UI     — claim a roadmap task
    /claim-task DATA-SERIES-CROSSWALK
    /claim-task 120                — claim review batch 120
    /claim-task BATCH-120          — same as above
  ```

If `--branch <name>` appears in `$ARGUMENTS`, extract it as the branch override (roadmap tasks only).

**Also extract, here, the three flags the later steps read** — all optional:

| Flag | Read by | Effect |
|---|---|---|
| `--review-plan` / `--no-review-plan` | Step 6 | Forces the plan-review preference to option A / option B, outranking any consumer config. |
| `--resume <RUN_ID>` | Step 2, Step 7-pre | Re-enters a parked or abandoned claim at the named run instead of starting a new one. |

`--resume` takes a `<RUN_ID>` exactly as Step 7-pre minted it (`<UTC timestamp>-<8 hex>`). **Validate it below, after `<CLAIM_ID>` is fixed** — the run directory is keyed by the claim id, so the check is not performable until the normalisation table has run.

### Normalise the claim ID here, not later

Fix **both** identifiers now, before any step addresses a file by name:

| Name | Roadmap task | Review batch |
|---|---|---|
| `<TASK_ID>` | the task ID (`TECH-0007`) | — not defined; a batch has no roadmap task ID |
| `<BATCH_NUMBER>` | — | the bare number (`116`), what `batch_work.sh` takes |
| `<CLAIM_ID>` | the task ID (`TECH-0007`) | **`BATCH-<N>`** (`BATCH-116`) |

**`<CLAIM_ID>` is what every lock, runtime artifact, and envelope is keyed by**, for both kinds. `<BATCH_NUMBER>` is only ever a script argument. The distinction is load-bearing: `/claim-task 116` on a batch leaves an agent holding `116`, and a step that addresses `sysop/runtime/locks/<TASK_ID>.lock` with it looks for `116.lock` while `batch_work.sh` wrote `BATCH-116.lock` — a check that reads as "not claimed" for every batch that ever was. Normalising at Step 7 instead of here is how that class of miss happens, so it is done once, at the top, for both kinds.

Where a later step names `<TASK_ID>` inside a *roadmap-only* mechanism (`tasks/index.yml` lookups, body files, branch generation), that is deliberate and correct — those steps carry an explicit **Review batches:** clause instead.

### Validate `--resume <RUN_ID>` — only if it was passed

Skip this entirely on an ordinary claim. **Reject an invocation that passes `--resume` with no value, or with a value that is not an existing run directory** — print the available run ids and stop. Guessing here would re-enter the wrong run. Run ids *are* chronologically sortable — the timestamp half is the prefix, and the listing below is `sorted()` — but newest is not the same as correct: a run may have been superseded, abandoned, or already executed, which is what the routing table at Step 7-pre reads and what an ordering cannot tell you.

```bash
# `python3` command word + positional args — a single simple command, so `Bash(python3 -:*)`
# matches. Substitute both placeholders literally, quoted, so an unsubstituted one fails
# loudly instead of being read as a redirection.
python3 - <<'PY' "<CLAIM_ID>" "<RUN_ID>"
import sys, subprocess
from pathlib import Path

claim_id, run_id = sys.argv[1], sys.argv[2].strip()
# Runs live in the MAIN checkout (Step 7-pre), which is why this check is performable HERE,
# before any lock has been read and before a worktree path is known.
common = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                        capture_output=True, text=True, check=True).stdout.strip()
claim_root = Path(common).resolve().parent / "sysop" / "runtime" / "claim" / claim_id

if not run_id:
    print("ERROR: --resume needs a <RUN_ID>", file=sys.stderr)
    sys.exit(2)

available = sorted(p.name for p in claim_root.iterdir() if p.is_dir()) if claim_root.is_dir() else []
if run_id not in available:
    print("ERROR: no run '{}' under {}".format(run_id, claim_root), file=sys.stderr)
    print("available runs: " + (", ".join(available) or "(none)"), file=sys.stderr)
    sys.exit(3)
print("RESUME_OK=" + str(claim_root / run_id))
PY
```

`claim_root.is_dir()` is tested before listing it, so a claim that has never run reports `available runs: (none)` instead of raising — the error path this check exists for must not itself be the thing that crashes.

## Step 2: Read Context & Validate

**For roadmap tasks — resolve the entry state first.** This is the authority on whether the claim may proceed; the metadata heredoc below extracts fields, it does not adjudicate.

```bash
bash sysop/scripts/claim_task.sh --entry-state <TASK_ID>
```

Write the id out literally, here and at **every** later site — Steps 2, 4a and 4b all take it as a substituted literal. **Do not carry it in a shell variable:** nothing survives from one fenced block to the next, even inside a single step (`WORKFLOW.md` § 8.2a, *Persistence boundary*), so `"$TASK_ID"` expands to the empty string and this script exits on its usage guard. Phase 169 fixed two sites in this file that broke the rule this sentence states — the `python3 -` heredocs at Step 2 and Step 4a — so treat it as load-bearing rather than advisory.

It prints exactly one token and exits 0 on every resolved state:

| Token | Meaning | Do |
|---|---|---|
| `claimable` | `status: open`, no lock | Ordinary fresh claim — **continue**. |
| `resumable` | `status: in_progress`, **no lock** | **Stop and ask.** Ambiguous — see below. Continue only on an explicit human go-ahead. |
| `held` | a lock exists | **Stop.** Print the lock file contents. Someone or something holds this claim. **Unless `--resume <RUN_ID>` was passed** — see below. |
| `closed:<status>` | `done` / `deferred` / … | **Stop.** The task is not claimable. |
| `absent` | no such id in `tasks/index.yml` | **Stop.** Mistyped id, or the task lives in `deferred/` / `archive/` — suggest `/next-task`. |

A non-zero exit means the question could not be answered at all (`2` no index, `3` no python3/PyYAML, `4` unreadable index) — surface stderr verbatim and stop.

**`resumable` is the ambiguous class, and it must not auto-continue.** Two very different situations produce the identical signature, and nothing on disk separates them:

1. **An abandoned claim** — someone claimed the task, the lock was cleaned up, no work is in flight. Resuming is correct.
2. **A close that is still in flight.** Under `§ Merge policy: pr`, `/review-close` Step 4c unlinks the lock on the integration branch *before the PR merges*, while the `done` flip rides the unmerged PR — so on `main` the task reads `in_progress` **with no lock** for the whole life of that PR. `review-close/SKILL.md` § *Lock-as-real-time-signal invariant* documents exactly this window. Resuming here re-claims **finished, already-reviewed work**.

So: report the state, name both possibilities, and **require an explicit human go-ahead before continuing**. If the answer is to resume, continue and skip Step 4a's status flip (the status is already `in_progress`). This follows the house pattern the orchestrator spec's Q1 settles on — *surface the ambiguous class, block the unambiguous one* — rather than guessing.

Two further limits, stated because the earlier draft of this step overclaimed both:

- **It is not "your claim."** `claim_task.sh` records `agent: anonymous` unless a name was passed, so no code here can tell an abandoned claim of yours from a colleague's.
- **Two shipped tools call this state a defect, not a state.** `validate_tasks.py` Invariant 9 makes `in_progress` without a lock a **blocking** validator error, and `sitrep_survey.py` reports it as `index drift (in_progress without lock)` and suggests flipping back to `open`. On the ordinary claim path that disagreement is momentary — Step 4b re-creates the lock immediately — but if you stop between here and Step 4b, you have left the tree in a state the validator rejects.

**`held` plus `--resume <RUN_ID>` is the one way past the stop, and it requires the human to have named the run.** A claim that parked at Step 7c leaves its lock deliberately in place, so `--entry-state` answers `held` — correctly, because from the outside a parked claim and a colleague's live claim are indistinguishable (`claim_task.sh` records `agent: anonymous` unless a name was passed, so no code here can tell them apart). Without a way past it the artifact set would be a one-way door: the park writes a plan, a review and a verdict specifically so the work can be picked up, and then nothing could pick it up.

So: on `held`, if Step 1's `--resume <RUN_ID>` check passed, print the lock contents and — **if that run has one** — its `classification.md` verdict, then continue: skip Step 4 entirely, since the claim, worktree, branch and lock all already exist, and **re-enter at Step 7-pre**, which adopts the named run rather than minting a new one and routes to the right stage from the artifacts on disk. Step 7-pre is the *only* re-entry point; nothing jumps straight to a later stage. On `held` with no `--resume`, stop as the table says.

**A run parked before 7c ran has no `classification.md`, and that is ordinary, not an error** — the 7a integrity park and the 7b reviewer-failure park both happen before any classification exists. The park marker (`sysop/runtime/parked/<CLAIM_ID>__<RUN_ID>.md`) carries the reason in every case and is the file to print when the verdict is absent.

<a id="resume-establishes-branch"></a>**Read `<BRANCH_NAME>` and the worktree path out of the lock — this is the only step on a resume that establishes them.** They are the `branch:` and `workspace:` fields of `sysop/runtime/locks/<CLAIM_ID>.lock`, written there by `claim_task.sh --lock` and by `batch_work.sh` alike. Step 4 is skipped on a resume, so the sites that normally establish them — Step 3 for a roadmap task, `batch_work.sh`'s summary box for a batch — never run, while all three Step 7 prompts substitute `<BRANCH_NAME>` and every envelope requires it.

**This is an explicit human instruction, not an inference.** The flag *is* the go-ahead; the skill never decides on its own that a `held` claim is stale enough to take over. Note the honest limit: `--resume` on a lock genuinely held by a colleague will take their claim. That is the same trust model as `--force` elsewhere in this workflow — the human is asserting something the tree cannot verify.

**`--resume` changes exactly one row of that table, and no other.** It names which *run* to re-enter; it is not a blanket override of the entry state.

- On **`resumable`** it does **not** short-circuit the stop-and-ask. The ambiguity that arm exists for — an abandoned claim versus a `pr` close still in flight — is about the *task*, and naming a run says nothing about it. Report the state, name both possibilities, ask. If the answer is to resume, Step 4 still runs (the lock is missing and the schema requires it), and Step 7-pre then adopts the named run.
- On **`closed:<status>`** and **`absent`** it changes nothing. A run directory can outlive the task it belonged to; that is not permission to re-claim a done task.

**Review batches:** `--entry-state` **refuses** a `BATCH-<N>` id and exits 1, exactly as `--release` does — a batch's claim state lives in `review_tasks.md`, not `tasks/index.yml`, so answering from there would report `absent` for every batch that exists. Do not call it on the batch path; the review-batch branch below performs the equivalent check against `review_tasks.md` plus the lock (five outcomes, same shape).

Then look the task up in `tasks/index.yml` via Python (never grep YAML) for the metadata Steps 3–6 need. Run:

```bash
# Substitute the task id for <TASK_ID>, per the rule above — quoted, so an unsubstituted
# placeholder fails loudly instead of being read as a redirection.
# `python3` command word (not `.venv/bin/python3`, no PATH prefix, no `&&` compound) so
# the allow-rule `Bash(python3 -:*)` matches as a single simple command. PyYAML — which
# this heredoc imports — is resolved for venv-only consumers by the bootstrap below, not
# by the caller's interpreter choice (BeanRider ISSUE-0049; Sysop Phase 126).
python3 - <<'PY' "<TASK_ID>"
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
if not index_path.exists():
    print("ERROR: tasks/index.yml not found", file=sys.stderr)
    sys.exit(2)

with index_path.open(encoding="utf-8") as f:
    data = yaml.safe_load(f)

tasks = data.get("tasks", []) or []
match = next((t for t in tasks if t.get("id") == task_id), None)
if not match:
    print(f"ERROR: task '{task_id}' not found in tasks/index.yml", file=sys.stderr)
    sys.exit(3)

status = match.get("status")
body = match.get("body")
print(f"id={match['id']}")
print(f"title={match.get('title', '')}")
print(f"status={status}")
print(f"phase={match.get('phase', '')}")
print(f"effort={match.get('effort', '')}")
print(f"user_action={match.get('user_action', False)}")
print(f"branch={match.get('branch', '')}")
print(f"body={body or ''}")

# `in_progress` is allowed through because --entry-state above already ruled on
# it: it reaches here only as `resumable` (in_progress with NO lock). A held
# task stopped at the entry-state gate, so re-refusing it here would make the
# resume path unreachable while looking like defence in depth.
if status not in ("open", "in_progress"):
    print(f"ERROR: task '{task_id}' has status='{status}'; only 'open' (fresh claim) or 'in_progress' (resume) tasks may be claimed", file=sys.stderr)
    sys.exit(4)

if not body:
    print(f"ERROR: task '{task_id}' has no body path set", file=sys.stderr)
    sys.exit(5)

body_full = Path("tasks") / body
if not body_full.exists():
    print(f"ERROR: body file {body_full} does not exist", file=sys.stderr)
    sys.exit(6)
PY
```

Hard-fail (exit and report) if the script exits non-zero. Surface the stderr message verbatim. **Exit-code contract** (typed so the parent can branch without re-parsing stderr):

- `2` — `tasks/index.yml` itself missing (consumer not bootstrapped, or wrong cwd).
- `3` — task ID not found. The user mistyped the ID, or the task lives in `deferred/` / `archive/`. Suggest `/next-task` to find a claimable one.
- `4` — status is neither `open` nor `in_progress` (i.e. `done` / `deferred` / unknown). The task is closed; stop. `in_progress` no longer exits here — the `--entry-state` gate above already separated `resumable` (no lock) from `held` (lock present), and re-deciding it in this heredoc would just make the resume path unreachable.
- `5` / `6` — `body:` field missing or the body file doesn't exist on disk. The index entry is broken — `validate_tasks.py` will reject it; fix the entry before re-claiming.

Also list `sysop/runtime/locks/*.lock` files to surface concurrent claims:

```bash
ls sysop/runtime/locks/*.lock 2>/dev/null
```

If `sysop/runtime/locks/<CLAIM_ID>.lock` already exists, hard-fail with the file contents — another session owns this claim. Do not overwrite.

This check sits in the roadmap branch; the review-batch branch has its own, below. What is uniform is the **path**: both kinds write a lock at `sysop/runtime/locks/<CLAIM_ID>.lock` (`batch_work.sh` writes `BATCH-<N>.lock`, Phase 156), so the `ls` listing above surfaces in-flight batches alongside in-flight roadmap tasks and is worth reading on either path.

Read the body file `tasks/open/<TASK_ID>.md` in full so it is loaded as context for Step 7's prompts. (This sentence used to say "for Step 6 plan mode" — there is no plan mode, Step 6 is now the plan-review preference, and the planner reads the body itself from the main checkout. It survived the reshape unedited.)

**Overlap advisory (roadmap tasks — non-blocking).** The lock check above only asks "is *this* task claimed?" — it says nothing about whether the task's *files* collide with work already in flight in another worktree. Two claims touching the same files sail through and surface as a merge conflict at `/review-close` — recoverable rework (the worktrees kept the builds isolated), but wasted work the advisory can warn about. Run the shared scope-overlap primitive:

```bash
.venv/bin/python3 sysop/scripts/scope_overlap.py <TASK_ID>
```

(The `.venv/bin/python3` form is preferred per Phase 45b so the advisory still fires for consumers whose PyYAML lives only in the venv; bare `python3` also works where PyYAML is on the system interpreter. Both permission rules exist.) It infers the candidate's likely scope from its `## Key files` + `blast_radius` (a *pre-plan guess*), reads the **actual** changed set of each in-flight worktree (`git diff --name-only main...HEAD` + uncommitted), and prints a per-in-flight verdict — `likely` (exact path match) / `possible` (same directory or glob) / `none`.

- **Surface the output verbatim** if it reports any overlap, then continue. This is **advisory, not a gate** — overlap is a recoverable rework cost, not corruption, so the human owns the call (the guided-mode "genuine tradeoff → human owns it" branch, in contrast to the lock collision above, which *is* a false choice and correctly hard-fails). Do **not** block the claim on it.
- The primitive is **non-blocking by construction**: it exits 0 on every degrade path (no in-flight work, missing index, absent PyYAML, an unreadable worktree). Treat *any* non-zero exit or error as "advisory unavailable — proceed"; never halt the claim because the overlap check couldn't run.
- If it warns of a `likely` overlap, it's worth mentioning `/next-task` (which surfaces claimable tasks) as the clean alternative — but the human may legitimately choose to claim the overlapping task anyway (e.g. the collision is small, or they'll coordinate the merge).

**For review batches:**
- Read `review_tasks.md` (full)
- Verify the batch number exists
- Check its status (the backtick-wrapped status after the batch title):
  - `Pending` → available **unless `sysop/runtime/locks/<CLAIM_ID>.lock` exists**. A lock on a `Pending` batch is not a contradiction: `batch_work.sh` skips the `Pending` → `In Progress` commit when it is off `main`, when `review_tasks.md` is dirty, or when the pull fails, and still creates the worktree. So the lock is the more reliable of the two signals. If locked, report "already claimed" with the lock contents and stop.
  - `In Progress` → check for `sysop/runtime/locks/<CLAIM_ID>.lock`. If locked, report "already claimed" and stop. If no lock, it may be resumable — proceed (the script handles this).
  - `Merged`, `Complete`, `Ready for Review` → report current status and stop

**`--resume <RUN_ID>` gets a batch past the "already claimed" stop, on the same terms as the roadmap `held` arm.** A batch that parked at Step 7c leaves its lock in place by design, so both locked rows above would otherwise refuse it — and a parked batch is exactly the case #220 reported, since a review batch is the claim kind it happened on. When Step 1's `--resume` check passed and a lock exists, print the lock contents and — if the run has one — its `classification.md` verdict, then skip Step 4 (worktree, branch and lock all exist) and re-enter at Step 7-pre.

**Read `<BRANCH_NAME>` and the worktree path out of `sysop/runtime/locks/<CLAIM_ID>.lock`** — its `branch:` and `workspace:` fields — exactly as the roadmap resume arm does; `batch_work.sh` writes both. This is not a repetition for symmetry's sake: skipping Step 4 skips the summary box that Step 3's review-batch clause names as the establishing site, so on this path the lock is the *only* source, and all three Step 7 prompts substitute `<BRANCH_NAME>`.

The same honest limit applies: on a colleague's live lock this takes their claim.

To hand a stranded batch back, use `bash sysop/scripts/batch_work.sh --release <BATCH_NUMBER>` — it reverses both halves of the claim (the `review_tasks.md` status and the lock). `claim_task.sh --release` refuses a `BATCH-*` ID on purpose: it owns `tasks/index.yml`, so it would release the lock and leave the batch reading `In Progress` forever.

## Step 3: Generate Branch Name

**Roadmap tasks:**
- If `--branch <name>` was provided, use that.
- Else if the task entry has a `branch:` field set in `tasks/index.yml` (surfaced as the `branch=...` line by Step 2's Python script), use it.
- Otherwise, auto-generate from the task ID by lowercasing and mapping the prefix:
  - `FEAT-X` → `feat/feat-x`
  - `TECH-X` → `tech/tech-x`
  - `DATA-X` → `data/data-x`
  - `UX-X` → `ux/ux-x`
  - `FIX-X` → `fix/fix-x`

**Review batches:** The branch is specified in `review_tasks.md` metadata and handled by `batch_work.sh`, so nothing is *generated* here — but `<BRANCH_NAME>` still has to be **established**, because all three Step 7 prompts substitute it and every envelope requires it. `batch_work.sh` prints it in its summary box (`│  Branch: <name>`); read it off Step 4's output there and hold it in context. See Step 4's review-batch block.

## Step 4: Claim the Task

**Roadmap tasks** — four actions, in order. **Each is destructive — print the action before running, then run.** If any step fails, fall through to the rollback at the bottom of this section before reporting.

### 4a. Flip `status: open` → `status: in_progress` in `tasks/index.yml`

Do NOT edit the YAML by hand with a regex — round-trip through `yaml.safe_load` / `yaml.safe_dump` so the file stays validator-clean. PyYAML round-trip loses inline comments — that's acceptable for `index.yml` (sprint prose lives in block scalars which round-trip fine).

```bash
# Substitute the task id for <TASK_ID>, per Step 2's rule — quoted, so an unsubstituted
# placeholder fails loudly instead of being read as a redirection.
# `python3` command word + in-heredoc PyYAML bootstrap (see Step 2's note; BeanRider
# ISSUE-0049; Sysop Phase 126) — single simple command, so `Bash(python3 -:*)` matches.
python3 - <<'PY' "<TASK_ID>"
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
resumed = False
for t in data.get("tasks", []):
    if t.get("id") == task_id:
        current = t.get("status")
        if current == "in_progress":
            # Resume path (Step 2 entry state `resumable`): already flipped by
            # the claim this one is re-entering. Leave it alone and write
            # nothing — re-flipping is a no-op, but treating it as an error
            # would make the resume unreachable at the LAST guard instead of
            # the first. Anything other than open/in_progress still refuses.
            resumed = True
        elif current != "open":
            print(f"ERROR: refusing to flip status; current status='{current}'", file=sys.stderr)
            sys.exit(1)
        else:
            t["status"] = "in_progress"
        found = True
        break

if not found:
    print(f"ERROR: task '{task_id}' disappeared between Step 2 and Step 4", file=sys.stderr)
    sys.exit(1)

if resumed:
    # Write NOTHING on the resume path. The status is already correct, and a
    # safe_dump round-trip of an unchanged doc still reflows the file (comments
    # dropped, quoting and wrapping normalised) — a whole-file diff with no
    # semantic change, which Step 4d would then commit and /review-close's
    # dirty classifier would react to.
    print(f"OK: {task_id} already in_progress — resuming, index untouched")
else:
    with index_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            data,
            f,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
            width=120,
        )
    print(f"OK: flipped {task_id} → in_progress in tasks/index.yml")
PY
```

**On the resume path this step is a no-op by design.** It prints `already in_progress — resuming, index untouched` and writes nothing, so Step 4d has nothing to stage — see the resume clause there.

### 4b. Run the claim script with `--lock` to create the worktree and lock file

The lock file is **required** by the schema for `in_progress` tasks (see `tasks/schema.md` § lock invariant). The script creates `sysop/runtime/locks/<TASK_ID>.lock` under the **main** repo's `sysop/runtime/locks/` via `git rev-parse --git-common-dir`, so the validator resolves the same path from any working tree. Always pass `--lock`:

```bash
bash sysop/scripts/claim_task.sh --lock <TASK_ID> <BRANCH_NAME>
```

This also creates the git worktree on `<BRANCH_NAME>`, branched from current HEAD (main if you ran the skill from main).

**Take `<WORKTREE_PATH>` off this script's output and hold it in context** — it prints the lock it wrote, whose `workspace:` field is the absolute path. Do **not** derive it from a shape: the conventional location is `../<project>-<task-id-lower>/`, but `WORKTREE_PREFIX` overrides that, and every later site — Step 7a's `git -C`, all three prompts, the executor's working directory — needs the real absolute path rather than a guess.

### 4c. Validate state with `sysop/scripts/validate_tasks.py`

This proves the schema invariants hold (status, lock file presence, body existence, ref integrity) before the claim commit lands on `main`:

```bash
.venv/bin/python3 sysop/scripts/validate_tasks.py
```

If it fails, **do not proceed to 4d**. Report the validator output verbatim and fall through to the rollback below. Common causes: lock file missing (4b silently failed), body file moved, ID collision introduced upstream.

### 4d. Commit the claim on main

This commit lands on `main` in the shared **primary** worktree, so apply `_shared/main-push-guard.md` **Rule A** first — assert `HEAD` is still `main` (a concurrent `/auto-build` batch or another `/claim-task` session could have moved it). If it is not, STOP and reconcile via `git reflog` rather than committing the claim onto the wrong branch:

```bash
test "$(git rev-parse --abbrev-ref HEAD)" = "main" || {
  echo "HEAD is not main (a concurrent actor moved it) — STOP."; exit 1; }
git add tasks/index.yml
git diff --cached --quiet -- tasks/index.yml \
  || git commit -m "claim: mark <TASK_ID> as in-progress"
```

**Resume path (Step 2 entry state `resumable`): there is nothing to commit, and that is not an error.** Step 4a wrote no change, so `tasks/index.yml` is already staged-clean and `git commit` would abort with *nothing to commit* — which reads as a failed claim. The `git diff --cached --quiet` test above is what makes the step idempotent; keep it rather than letting the commit fail and be interpreted. Rule A's `HEAD` assert still runs on both paths, because a resume commits nothing but every *later* step still assumes it is standing on `main`.

Run on the main checkout (the worktree at `../<project>-<task-id-lower>/` will pick this up via the shared object DB).

### Rollback on failure of 4b or 4c

If 4b's script exits non-zero, or 4c's validator exits non-zero, undo 4a's uncommitted edit before stopping:

```bash
git checkout tasks/index.yml
```

If 4b got as far as creating anything, undo **only this task's** artifacts. Do **not** reach for `cleanup_worktrees.sh --force`: it takes no path operand, so it removes *every* non-main worktree — ACTIVE ones included — and would destroy any concurrent claim's uncommitted work (WORKFLOW.md § 8.4). Which command applies depends on how far 4b got, because `claim_task.sh` writes the lock **last** (branch → worktree → lock):

- **A lock exists at `sysop/runtime/locks/<TASK_ID>.lock`** — i.e. 4b completed and 4c's validator is what failed. Use the lock-aware inverse: `bash sysop/scripts/claim_task.sh --release <TASK_ID>`. It removes the recorded worktree, releases the lock, and treats the already-`open` status left by the `git checkout` above as an info line rather than an error. It leaves the branch — add `--delete-branch` to drop it, or `git branch -d <BRANCH_NAME>` afterwards. To discard uncommitted work in the worktree, add `--force` **before** the task ID (`--release --force <TASK_ID>`): the script consumes flags only ahead of the positional and rejects a trailing one. **Its index-flip step needs a PyYAML-capable `python3` on `PATH`** — if it reports PyYAML unavailable it exits having changed nothing and prints a manual recipe; activate the project venv and re-run rather than hand-editing.
- **No lock exists** — i.e. 4b failed before writing the lock (it is written last). `--release` refuses here on purpose, the lock being the claim record it keys on, so undo by hand: `git worktree remove <worktree-path>` if a worktree exists (it refuses on uncommitted or untracked changes; `--force` to discard), then `git branch -d <BRANCH_NAME>`. A 4b failure *at* `git worktree add` leaves the branch and no worktree, so the branch delete is the whole cleanup there — harmless if skipped, since 4b tolerates a pre-existing branch on the retry.

Then report the failing step's error output and stop.

**Review batches:**
```bash
bash sysop/scripts/batch_work.sh <BATCH_NUMBER>
```
The script handles `Pending` → `In Progress` transition in `review_tasks.md` and commits on main automatically, creates the worktree, and writes `sysop/runtime/locks/<CLAIM_ID>.lock` — the same lock file, in the same main-repo-anchored directory, that `claim_task.sh --lock` writes for a roadmap task. (Review-batch state still lives in `review_tasks.md` — only roadmap tasks live in `tasks/index.yml`. The *lock* is the one thing both kinds share, which is what makes `/next-task`, `/sitrep` and `scope_overlap.py` able to see a batch and a task the same way.)

The status commit is best-effort and the lock is not: off `main`, or with a dirty `review_tasks.md`, the script warns, skips the flip, and still creates the worktree **and** the lock. Read the output — a batch that stayed `Pending` is claimed all the same.

**Take `<BRANCH_NAME>` and the worktree path off this script's summary box and hold both in context** — the `│  Branch:` and `│  Path:` lines. This is not optional bookkeeping: the roadmap path establishes `<BRANCH_NAME>` at Step 3, the batch path has no equivalent, and Step 7's three prompts and all three envelopes name it. If the script exited before printing the box, both values are in the lock it wrote — `sysop/runtime/locks/<CLAIM_ID>.lock`, fields `branch:` and `workspace:`.

If the script exits non-zero, report the error output and stop.

## Step 5: Report Claim Result

Print a summary box:

```
## Claimed: <TASK_ID or Batch N>

| Field     | Value                              |
|-----------|------------------------------------|
| Type      | Roadmap task / Review batch        |
| Worktree  | ../<project>-<task-lower>/         |
| Branch    | <branch_name>                      |

Workspace: `<worktree_path>`

The claim is in place. This run continues at Step 6 — plan, adversarial
review, classification, then implementation — all in sub-agents. You are not
being handed the worktree to work in yourself.
```

**Do not stop here and tell the human to go work in the worktree.** That is what this skill used to do, and the steps below are the run, not a suggestion. `/document-work` comes after Step 8, not after this box.

## Step 6: Resolve the plan-review preference

**Resolved here, once, before any agent spawns.** Planning plus review takes 5–25 minutes, so asking *afterwards* asks someone who may have walked away — and "the human didn't really review it" then happens by degradation rather than by choice. Front-loading makes it a declared decision that is always answerable.

Follow `.claude/skills/_shared/plan-review-preference.md` to resolve it. That partial is the single source of truth for the resolution order (flag → `<project>/CLAUDE.md § Plan review` → ask), for the guided-mode interaction, and for the `askUserQuestionTimeout` hazard. **Never prompt when the flag or the config resolves it** — `/claim-task <CLAIM_ID>` on a configured project must stay a single command.

Two options are offered:

| Option | Flow | For |
|---|---|---|
| **A — review the plan first** | planner → reviewer → **human gate** → executor | Work you want to eyeball before it lands. |
| **B — run it** | planner → reviewer → executor | Mechanical or well-specified work; walk away. |

**The reviewer runs on both paths.** Only the gate at Step 7d differs. Collapsing reviewer and executor on the unattended path would give the run *nobody is watching* the weaker review property, and `_shared/adversarial-review.md` § *The reviewer-executor variant is retired* already records collapsed self-classification as a known compromise. The autonomous path needs more fresh-eyes rigour, not less.

**A third option — plan-only, where the pipeline stops after review and writes the reviewed plan back to the task body — is specified but not built** (`tools/CLAIM_TASK_ORCHESTRATOR_SPEC.md` § *The three options*, option C). Do not offer it, and do not improvise it: it needs a `## Plan` body section that `tasks/schema.md` does not yet define and a release ordering this skill does not yet carry. Say so in one line if the human asks for it, rather than silently behaving like option B. **Stating the absence is the point** — silence about a missing branch is exactly how Steps 7–8 acquired roadmap-only vocabulary in Phase 29, and it is the failure upstream #220 reported.

**Review batches:** both options are offered, unchanged. Option C would not have been (a batch has no body file to persist a plan into — its "body" is a `### Batch N` section inside the shared `review_tasks.md`, whose six metadata keys are parsed into a shadow index two scripts consume), but since C is not offered to anyone, no asymmetry arises here yet.

## Step 7: Orchestrate — plan → review → classify → gate → execute

**Why this is three spawns, a classification and a gate rather than one sub-agent.** Upstream #220: a real `/claim-task` run on a review batch went `EnterPlanMode` → ~200 tool calls → `ExitPlanMode` with **no `Agent` call at any point**. The adversarial review, the finding classification, the sealed report and the halt-on-blocker gate were all bypassed, and it surfaced only because a human asked. Three distinct failure modes look identical from outside:

1. **Drift** — the skill was read hundreds of tool calls ago and plan mode's own reminder pushes toward `ExitPlanMode`. Attention decay, not intent. This is what #220 observed. The split spawns and the artifact set below are what address it.
2. **Blocked** — the harness forbids the `Agent` tool outright (a system-prompt instruction outranks skill text). The agent *cannot* comply. **This shape does not prevent that, and does not claim to** — it makes it *visible*: an orchestrator whose entire body is "spawn agents" cannot silently degrade into doing the work itself without leaving an empty artifact directory and no envelopes, where a healthy run leaves three of each. Today it degrades into "just implement it", which looks normal. **Stated exactly: nothing reads that difference yet.** The `/review-close` and `/sitrep` readers are specified and deferred (part B of this reshape), so the evidence today is durable and inspectable by a human, and nothing reports on it automatically. Do not describe those readers as existing.
3. **Read as not-applicable** — Step 7's prompt opened *"You are executing roadmap task `<TASK_ID>`"* and was threaded with `tasks/index.yml` machinery a review batch does not have, so an agent holding a batch claim reasonably concluded the step was not about it. Every step below is spelled `<CLAIM_ID>` and carries a `Review batches:` clause wherever behaviour differs.

**Say the residual out loud rather than burying it:** a harness that forbids `Agent` produces a claim with no plan, no review and no envelope, and Sysop will *say so* rather than stop it.

### Step 7-pre: resolve the run and its artifact directory

**This is the only entry point to Step 7, on a fresh claim and on a `--resume` alike.** No later stage is entered directly; the routing table below decides which one this run lands on.

Every run of this pipeline gets its own directory. **This is what makes a stale artifact unreachable rather than merely detectable** — a re-invocation never looks in a previous run's directory, so it cannot inherit its `review.md`. That matters most on the batch path: `batch_work.sh`'s `write_batch_lock` is idempotent by design and leaves an existing lock **as-is** (`batch_work.sh:192-195`), and nothing in it refuses a re-claim, so a batch re-invocation would otherwise find yesterday's artifacts sitting under a lock that still looks current. Keying on the lock's `started:` stamp does **not** close this — the stamp is preserved across exactly that re-claim.

**The directory lives in the MAIN checkout, not the worktree**, resolved through `git rev-parse --git-common-dir`. Three properties depend on that and none of them survive a worktree-side path: Step 1 has to validate `--resume` *before* any lock is read, so the run must be discoverable before a worktree path exists; the artifacts have to outlive `git worktree remove` and `cleanup_worktrees.sh`, which is what the park previously needed a second copy for; and the orchestrator itself runs in the main checkout, alongside the hook-written envelopes. An earlier revision created it under `<WORKTREE_PATH>` while Steps 1 and 2 looked for it in the main checkout — the two never met, and every `--resume` was rejected.

```bash
# `python3` command word + positional args — a single simple command, so `Bash(python3 -:*)`
# matches. Substitute both placeholders literally. The second argument is the `--resume`
# run id, or an EMPTY STRING on a fresh claim.
python3 - <<'PY' "<CLAIM_ID>" "<RESUME_RUN_ID or empty>"
import sys, secrets, datetime, subprocess
from pathlib import Path

claim_id, resume = sys.argv[1], sys.argv[2].strip()
# Quoting alone does NOT make an unsubstituted placeholder loud here, the way it does at
# Step 2 where the id is looked up and not found: this block CREATES its path, so
# `<CLAIM_ID>` would quietly become a directory of that literal name. Refuse it instead.
if "<" in claim_id or "<" in resume:
    print("ERROR: placeholder not substituted: {!r} {!r}".format(claim_id, resume), file=sys.stderr)
    sys.exit(2)

common = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                        capture_output=True, text=True, check=True).stdout.strip()
main_root = Path(common).resolve().parent
claim_root = main_root / "sysop" / "runtime" / "claim" / claim_id

if resume:
    # ADOPT the named run. Do not mint, do not mkdir, do not touch what is in it.
    d = claim_root / resume
    if not d.is_dir():
        print("ERROR: no run '{}' under {}".format(resume, claim_root), file=sys.stderr)
        sys.exit(2)
    run_id = resume
    print("RESUMED=1")
else:
    run_id = "{}-{}".format(
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        secrets.token_hex(4),
    )
    d = claim_root / run_id
    d.mkdir(parents=True, exist_ok=True)
    # Clear the shared envelope mailbox INTO this run, moving rather than deleting. The
    # hook keys envelopes `<CLAIM_ID>.<phase>.json` with NO run component, and Step 8 never
    # deletes them, so a re-claim would otherwise read the PREVIOUS run's exec.json and
    # print "Claim complete" for work this run never did. Per-run keying protects the
    # artifact directory; this is what protects the artifact Step 8 actually reads.
    env_dir = main_root / "sysop" / "runtime" / "subagent-envelopes"
    moved = []
    if env_dir.is_dir():
        prior = d / "prior-envelopes"
        stale = sorted(set(env_dir.glob(claim_id + ".*.json")) | set(env_dir.glob(claim_id + ".json")))
        for p in stale:
            prior.mkdir(parents=True, exist_ok=True)
            p.rename(prior / p.name)
            moved.append(p.name)
    print("MOVED_PRIOR_ENVELOPES=" + (", ".join(moved) or "none"))

print("RUN_ID=" + run_id)
print("ARTIFACT_DIR=" + str(d))
PY
```

Read `RUN_ID` and `ARTIFACT_DIR` off stdout and **hold them in your own context**, keyed to this claim — not in a shell variable and not in a shell array. Nothing survives from one fenced block to the next, even inside a single step (`WORKFLOW.md` § 8.2a, *Persistence boundary*), so a later `"$RUN_ID"` expands to the empty string and would silently collapse every run into one directory. Substitute them literally at each later site, exactly as `<CLAIM_ID>` is substituted. `ARTIFACT_DIR` is **absolute and outside the worktree** — the sub-agents `cd` into the worktree and still write to it by absolute path.

The timestamp half of the run id is for a human reading the directory listing; the random half is what guarantees uniqueness. A timestamp alone is not enough — `started:` is second-granular, and a release followed immediately by a re-claim produces an identical one.

**On a `--resume`, the mailbox is deliberately left alone.** The moved-aside envelopes belong to *earlier* runs of this claim, and a resumed run's own `plan.json` / `review.json` may still be sitting there from before it parked. The honest limit: if some *other* run of this claim ran after the one being resumed, its `exec.json` is still in the mailbox and Step 8 would read it. `--resume` is a human naming a specific run, and this is one more thing that assertion covers.

#### Where a resume re-enters — read it off the artifacts, not off memory

The artifacts on disk **are** the resume state.

**Route on files in `<ARTIFACT_DIR>` and on nothing else.** In this order, first match wins:

| State of `<ARTIFACT_DIR>` | Re-enter at | Why |
|---|---|---|
| `classification.md` reads `verdict: SUPERSEDED` | **stop** | Step 7d's *revise* rejected this run's plan and minted a successor. Name the successor and stop; resuming a plan a human rejected is worse than doing nothing. |
| `classification.md` reads `verdict: BLOCKED` | **7c** | The ordinary park, and the executor's `BLOCKED` return. Re-classify **with the human's answer in hand** — the answer is the new input, and 7c is where it lands. |
| `outcome.md` present | **Step 8** | The executor already ran and Step 8 recorded its terminal status. **Do not re-spawn it** — report `outcome.md`. |
| no `plan.md` | **7a** | Nothing was planned, or the planner failed before writing. |
| no `planner-integrity.md`, or it reads `VIOLATED` | **7a** | The plan was never re-gated, or it came from a planner that broke its contract by committing. Re-plan; do not review it. |
| no `review.md` | **7b** | The plan stands and its integrity is recorded `OK`; it has not been reviewed. |
| no `classification.md` | **7c** | Findings exist and were never adjudicated. |
| `verdict: PROCEED` | **7d** (option A) / **7e** (option B) | Already adjudicated clean; the run stalled before the executor returned. |

Print which row matched and why before continuing.

**Two rules make this table sound, and both were installed because a round found the table wrong without them.**

**1. Nothing routes off the shared envelope mailbox.** An earlier revision's first row keyed on `<CLAIM_ID>.exec.json` being present in `sysop/runtime/subagent-envelopes/`. That is a *shared* directory keyed by claim and phase with **no run component**, and a resume deliberately does not clear it — so a `BLOCKED` executor's envelope was still sitting there, the first row matched, and the resume went to Step 8, re-parked, and printed "resume with `--resume`" again. **A loop, and it made the `BLOCKED` row below it unreachable** — the row that exists for the one runtime path that actually produces a blocker question. The same shape sent a resume of an *older* run to the executor, because a later fresh claim had moved that run's envelope aside. `outcome.md` is written into **this run's** directory by Step 8, so it answers "did the executor already run *here*" without consulting anything shared.

**2. Every stage that gates records its verdict as a file.** `planner-integrity.md` is why the integrity check is not lost to a crash: it lived only in orchestrator context, so a crash between the planner's return and the check left `plan.md` on disk with no marker and no verdict, and the table routed it to a reviewer — **laundering exactly the plan the check exists to catch**, reachable by a crash rather than by a park. The file also carries the *original* pre-plan SHA, so a re-entry at 7a re-baselines on that rather than on the rogue commit, which an earlier revision did.

`plan.md` is written at most once per run: the rows above reach 7a only when it is absent, and Step 7d's *revise* mints a new run rather than re-planning into this one. Presence-based routing is only sound over an artifact set where each file describes one plan.

**The artifact directory makes the MAIN checkout untracked-dirty on a consumer that has not run the installer.** `install.sh` seeds `sysop/runtime/` into the consumer's `.gitignore`, and git honours a working-tree `.gitignore` whether or not it has been committed, so on a bootstrapped consumer the directory is ignored and nothing shows. Where the entry is absent, do **not** key any check on the literal string `?? sysop/runtime/` — git collapses to the topmost untracked directory, so it is `?? sysop/` when nothing under `sysop/` is tracked. And do not let this decide whether the pipeline may proceed: it is a bootstrap gap, not a fault.

### Step 7a: Spawn the planner

**Capture the pre-plan HEAD first — before the spawn, not after it.** The integrity check below compares against it, and a SHA captured after the planner has already run proves nothing:

```bash
git -C "<WORKTREE_PATH>" rev-parse HEAD
```

Hold that SHA in your own context as `<PRE_PLAN_HEAD>` and substitute it literally below. Not a shell variable: nothing survives from one fenced block to the next (`WORKFLOW.md` § 8.2a), and the failure is silent rather than loud — `git -C ""` does not fail, it runs in the CWD and returns a real SHA, so a comparison against an empty right-hand side is always unequal and would park every claim.

Print one line first so the transcript does not go silent:

```
Spawning planner for <CLAIM_ID> — plan only, no implementation. 3–10 minutes.
```

Spawn with the `Agent` tool:

- `subagent_type`: `"general-purpose"`
- `model`: `"opus"`
- Do **NOT** set `isolation: "worktree"` — the worktree pre-exists from Step 4; the planner `cd`s into it.
- Do **NOT** pass `run_in_background`. <!-- skill-audit-ok: run_in_background --> It is **not** a parameter of the `Agent` tool and its schema is closed, so a compliant call raises `InputValidationError` — and a rejected tool call is itself an invitation to proceed without the step. Sub-agents have run in the background by default since Claude Code 2.1.198.
- `description`: `"Plan <CLAIM_ID>"`
- `prompt`: the **Planner Prompt** below, with `<CLAIM_ID>`, `<WORKTREE_PATH>`, `<BRANCH_NAME>`, `<ARTIFACT_DIR>` filled in.

---

**START OF PLANNER PROMPT**

You are planning `<CLAIM_ID>` for the `/claim-task` orchestrator. Your **only** job is to produce an implementation plan and write it to disk. Do NOT implement, do NOT commit, do NOT call `ExitPlanMode` (you are not in plan mode), do NOT invoke the Agent tool.

The work is already claimed: worktree at `<WORKTREE_PATH>`, lock at `sysop/runtime/locks/<CLAIM_ID>.lock`, branch `<BRANCH_NAME>`.

**Working directory:** `<WORKTREE_PATH>` (cd here first).

**Read the task from the main checkout, not the worktree.** For a roadmap task the body is `tasks/open/<CLAIM_ID>.md` — or wherever `body:` points in `tasks/index.yml`, which is **relative to `tasks/`**, not to the repo root. A body filed by `/add-task` is deliberately left uncommitted, and the feature branch is cut at pre-claim `HEAD`, so an untracked body never entered this branch and opening it here returns ENOENT. Resolve it against the main repo root (`git rev-parse --git-common-dir`, then its parent). **If the body cannot be read, stop and report it — do not plan from the index title alone.**

**Body *edits* go in the worktree copy, not the one you just read.** The rule above is about *locating* the body; it is not the write path, and reading it as one is what upstream #322 reported. **Nothing commits a body edit made in the main checkout.** Be precise about why, because the obvious reason is wrong: `main` *is* committed to directly here — Step 4d does it — and under `§ Merge policy: pr`, `/review-close` Step 4-pre even sweeps local-only `main` **commits** onto the integration branch. What it sweeps is commits. A body edit left uncommitted in the main checkout is not one, no step stages it, and so it reaches no branch and no PR. Meanwhile `/review-close` Step 2d reads the `## Test decision` record **at the branch tip** (that step says so in as many words — *"the executor writes it into the body during implementation, inside the worktree"*), where a main-checkout edit is not. So every plan step that writes to the body must name the copy under `<WORKTREE_PATH>`.

**If the body is untracked in the main checkout** (filed by `/add-task` and never committed — the case the read rule above exists for) there is no worktree copy, and one cannot be created: `git add`ing it on the branch makes `/review-close`'s merge abort with *"The following untracked working tree files would be overwritten by merge"*. Plan the write against the main-checkout copy, and add a plan step to **say so in the executor's final message** — that record will not reach the PR, and the body needs committing before `/review-close` runs.

**Review batches:** there is no per-task body file. Read the `### Batch <N>` section of `review_tasks.md` in full, including its `> **Branch:** / **Scope:** / **Verify:**` metadata, and plan the fix order across the batch's tasks.

### What the plan must contain

1. **Task summary** — one paragraph restating the goal.
2. **`## Constraints & Risks`** — the **first** content block after the summary, before any implementation steps. Read `.claude/convention_map.md` and `.claude/security_map.md`; for each file or directory the plan will create or modify, list one bullet enumerating the applicable conventions and security checks from **both** maps, plus cross-cutting rules for the file type. One bullet per risk, no prose padding. Close it with a `### Coverage gap` subsection listing any touched file matching no section in either map (write `_(none)_` if every file matches). **Do not skip a file silently** — an empty match means the maps lack coverage for that path and must be logged so `/codebase-review` map-coverage auditing can pick it up.
3. **External SDK/framework calls.** Any plan step calling an external library, SDK or framework method must either **cite an in-repo precedent** (`file:line` of an existing same-project call site using that method the same way) or be marked **`unverified — no in-repo precedent`**. The bar is *cite a precedent or flag it*, not *verify against live docs*.
4. **`## Test decision`** — state either **`test <X> proves <Y>`** (the regression test, existing or new, that pins the behaviour this change touches) or **`no test because <Z>`** with a reviewable rationale. Add a plan step to write this section into the task's body file during implementation, **naming the worktree copy** (`<WORKTREE_PATH>/tasks/…`) as the path it writes to, per the write rule above. Make `Z` reviewable, not a hand-wave — the reviewer scrutinises it.
5. **Map gap steps.** For each file the plan **creates**, **moves/refactors into**, or **deletes**, check both maps: a new or moved path matching no `## ` section needs a plan step to extend the map; a deleted file named explicitly in a section header needs a plan step to clean up the reference.
6. **`## Implementation Steps`** — numbered, with concrete file paths, line ranges and expected diffs.

### Write the plan to disk

Write the full plan to `<ARTIFACT_DIR>/plan.md`. This file is the orchestrator's input to the reviewer and the durable record that planning happened; a plan that exists only in your final message is lost the moment this agent ends.

`<ARTIFACT_DIR>` is an **absolute path in the main checkout, outside your worktree**. Use it exactly as given — do not re-derive it, do not make it relative to the working directory above, and do not `git add` it. The directory already exists.

### Final message

Emit exactly this as the LAST fenced block of your final message, with no content after the closing backticks:

```yaml
TASK: <CLAIM_ID>
PHASE: plan
STATUS: EXECUTED
WORKTREE: <absolute path, no trailing slash>
BRANCH: <branch name>
ERROR: <error description if you could not produce a plan, else "none">
```

`TASK:` must be exactly `<CLAIM_ID>` — the `SubagentStop` hook validates it against `^[A-Z][A-Z0-9-]{2,80}$` and writes a diagnostic instead of an envelope if it does not match. `PHASE: plan` is what keeps your envelope from overwriting the reviewer's and the executor's.

**END OF PLANNER PROMPT**

---

**Post-plan integrity check.** The planner is instructed not to commit. Verify before spawning the reviewer. The comparison is **mechanical** — an orchestrator that has to eyeball two SHAs hundreds of tool calls into a run is the attention decay this whole reshape exists to remove:

```bash
# Substitute BOTH literals, quoted: the worktree path, and the pre-plan SHA captured at the
# top of this step. An unsubstituted `<PRE_PLAN_HEAD>` reports VIOLATED, which parks — loud,
# and in the safe direction.
python3 - <<'PY' "<WORKTREE_PATH>" "<PRE_PLAN_HEAD>" "<CLAIM_ID>" "<RUN_ID>"
import sys, subprocess
from pathlib import Path

worktree, pre, claim_id, run_id = sys.argv[1], sys.argv[2].strip(), sys.argv[3], sys.argv[4]
if "<" in claim_id or "<" in run_id:
    print("ERROR: placeholder not substituted", file=sys.stderr)
    sys.exit(2)

now = subprocess.run(["git", "-C", worktree, "rev-parse", "HEAD"],
                     capture_output=True, text=True, check=True).stdout.strip()
verdict = "OK" if now == pre else "VIOLATED"

# The verdict is a FILE, not a line of transcript. Held only in context it is lost
# to a crash between the planner's return and this check -- and then `plan.md` sits
# on disk with nothing recording that it was never re-gated, so a resume routes it
# to a reviewer and a clean review launders exactly the plan this check exists to
# catch. The file also carries the ORIGINAL pre-plan SHA, so a re-entry at 7a
# re-baselines on that rather than on the planner's rogue commit.
common = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                        capture_output=True, text=True, check=True).stdout.strip()
out = Path(common).resolve().parent / "sysop" / "runtime" / "claim" / claim_id / run_id / "planner-integrity.md"
if not out.parent.is_dir():
    print("ERROR: no such run directory {}".format(out.parent), file=sys.stderr)
    sys.exit(3)
out.write_text("# Planner integrity — {} run {}\n\n- pre_plan_head: {}\n- post_plan_head: {}\n"
               "- verdict: {}\n".format(claim_id, run_id, pre, now, verdict), encoding="utf-8")
print("PRE=" + pre)
print("NOW=" + now)
print("planner-integrity: " + verdict)
PY
```

On `VIOLATED` the planner committed, in breach of its contract: **do not proceed to 7b.** Park per Step 7c's park procedure, passing `planner committed during 7a (HEAD moved <PRE_PLAN_HEAD> -> <NOW>)` as the recorded reason. `planner-integrity.md` now records the violation durably, so Step 7-pre's routing table sends a resume back to 7a rather than handing the un-re-gated plan to a reviewer — and 7a re-baselines on the `pre_plan_head` recorded there, **not** on the rogue commit.

### Step 7b: Spawn the reviewer

**Always.** Review is never inherited, never skipped, and never merged into another agent's job. A reviewer that did not write the plan is the property the collapsed reviewer-executor shape conceded, and recovering it is most of the point of this reshape.

Same agent parameters as 7a, with `description`: `"Adversarial plan review <CLAIM_ID>"`.

`prompt`: the **contents of `<ARTIFACT_DIR>/plan.md` verbatim**, followed by the **Prompt Template** block copied verbatim from `.claude/skills/_shared/adversarial-review.md`, followed by the two paragraphs below. No other wrapper text — the shared template supplies the framing, and duplicating it here would fork it.

---

**START OF REVIEWER PROMPT TAIL** (appended after the plan and the shared Prompt Template)

**Working directory:** `<WORKTREE_PATH>` (cd here first). You did not write this plan and have no context from the session that did. Do not fix it — find what is wrong with it.

Write your full findings to `<ARTIFACT_DIR>/review.md` — an **absolute path in the main checkout, outside your worktree**; use it exactly as given, do not re-derive it, and do not `git add` it. That file is the durable record of what you found. It is **not** the transport, and it does not discharge the sealed block: the block's one required home is your final message, below.

**Your final message must carry two fenced blocks, in this order, with no content after the second.**

**First — the sealed report.** A fenced block whose body begins `REVIEW_REPORT:`. The hook captures the first such block into the envelope's `review_report_raw`, which is how the verdict reaches the orchestrator through a file no agent writes. Leave it out and the orchestrator has nothing but a file you wrote yourself, which is exactly what an invented review would also produce:

```yaml
REVIEW_REPORT:
  findings:
    - id: F1
      summary: "..."
      evidence: "file:line"
  verdict: FINDINGS | CLEAN
```

**Second — the envelope, as the LAST fenced block of your final message:**

```yaml
TASK: <CLAIM_ID>
PHASE: review
STATUS: EXECUTED
WORKTREE: <absolute path, no trailing slash>
BRANCH: <branch name>
ERROR: <error description if you could not complete the review, else "none">
```

Report findings only. **Do not classify them** as `fixable` or `blocker` and do not decide whether the work proceeds — that is the orchestrator's job at Step 7c, deliberately kept one layer up. If you find nothing, emit `findings: []` and `verdict: CLEAN` explicitly so the orchestrator can record that the step ran clean rather than that it failed to run.

**END OF REVIEWER PROMPT TAIL**

---

**Post-review transport check.** The sealed block is the *only* channel the reviewer cannot forge, and when it is missing nothing says so: the hook writes `review_report_raw: null` beside `"parsed": true` and exits `0`, so a run whose verdict never arrived is byte-for-byte as healthy-looking as one whose verdict did (upstream #329 — the failure shape #220 reported, reappearing inside the mechanism built to fix it). The check is **mechanical** for the same reason the post-plan one is: an orchestrator that has to remember to open a JSON file and notice a `null` is the attention decay this reshape exists to remove.

```bash
# Substitute BOTH literals, quoted. Reads the review envelope the hook wrote and the
# review.md the reviewer wrote, and records a verdict. Stdlib only — NO PyYAML (a
# consumer whose bare `python3` lacks it is the PEP-668 default, Phase 131), and the
# same MAIN-checkout resolution every other block in this step uses.
python3 - <<'PY' "<CLAIM_ID>" "<RUN_ID>"
import sys, json, subprocess
from pathlib import Path

claim_id, run_id = sys.argv[1], sys.argv[2]
if "<" in claim_id or "<" in run_id:
    print("ERROR: placeholder not substituted", file=sys.stderr)
    sys.exit(2)
common = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                        capture_output=True, text=True, check=True).stdout.strip()
main_root = Path(common).resolve().parent
run_dir = main_root / "sysop" / "runtime" / "claim" / claim_id / run_id
if not run_dir.is_dir():
    print("ERROR: no such run directory {}".format(run_dir), file=sys.stderr)
    sys.exit(3)

env_path = main_root / "sysop" / "runtime" / "subagent-envelopes" / (claim_id + ".review.json")
review_md = run_dir / "review.md"
status, sealed = None, None
if env_path.is_file():
    try:
        payload = json.loads(env_path.read_text(encoding="utf-8"))
    except ValueError:
        payload = {}
    status = payload.get("status")
    sealed = payload.get("review_report_raw")

# Order matters. An absent `review.md` is the failure table's reviewer row and outranks
# anything the envelope says: without the durable artifact there is nothing for 7c to fall
# back to, so routing it as EMPTY_TRANSPORT would send classification at a file that does
# not exist. An absent envelope FILE is not a reviewer failure at all — Step 8's read-order
# contract names an unregistered hook and a failed write as supported configurations.
if not review_md.is_file():
    verdict = "NO_REVIEW_MD"
elif not env_path.is_file():
    verdict = "NO_ENVELOPE"
elif sealed:
    verdict = "OK"
else:
    verdict = "EMPTY_TRANSPORT"

# A FILE, not a line of transcript: the whole point of the sealed block is that the
# record survives the context that read it, so a report about the record must too.
(run_dir / "review-transport.md").write_text(
    "# Review transport — {} run {}\n\n- envelope: {}\n- envelope_status: {}\n"
    "- review_md: {}\n- verdict: {}\n".format(
        claim_id, run_id, env_path, status, review_md.is_file(), verdict),
    encoding="utf-8")
print("review_md: {}".format(review_md.is_file()))
print("envelope_status: {}".format(status))
print("review-transport: " + verdict)
PY
```

Dispositions, one per verdict — these are rules, not judgement, for the same reason the failure table below is:

- **`OK`** — proceed to 7c and classify from the sealed block.
- **`EMPTY_TRANSPORT`** — the reviewer ran, left `review.md`, and returned an envelope, but the verdict reached you through no unforgeable channel. **Re-spawn 7b once**, unchanged — and **move the stale `<CLAIM_ID>.review.json` into `<ARTIFACT_DIR>/prior-envelopes/` first**, exactly as Step 7-pre does at run start and for the same reason: the mailbox is keyed by claim and phase with **no run component**, so a second reviewer whose envelope fails to write leaves the first one sitting there to be read as its result. If the second return is also `EMPTY_TRANSPORT`, proceed to 7c on `<ARTIFACT_DIR>/review.md` — but say so out loud in your Step 8 report and leave `review-transport.md` recording it. **This does not park**, and the asymmetry with the table below is deliberate: a review that demonstrably ran and left a durable artifact is worth more than a claim discarded over a channel failure, and the receipt is what keeps the degraded case from reading as the healthy one.
- **`NO_ENVELOPE`** — the hook wrote no envelope file. **This alone is not a failure and must not park.** Step 8's read-order contract names an **unregistered hook or a failed write** as supported configurations and falls back to regex-parsing the agent's return text; do the same here. Read the reviewer's own return text and look for the first fenced block whose body begins `REVIEW_REPORT:`. Found, and that is this run's transport — record `OK (return-text fallback)` in the receipt by hand and proceed. Not found, and the case is `EMPTY_TRANSPORT` above. Check for an `_unparseable_*.json` diagnostic while you are there (Step 8 states how to read one, and how not to attribute a stranger's to this claim).
- **`NO_REVIEW_MD`** — the reviewer left no durable artifact. **This** is the failure table's reviewer row, and it is the one that parks: re-spawn once, then park per 7c with `reviewer returned no review.md twice` as the recorded reason. Nothing here is recoverable from the envelope, because 7c's fallback input is the file that is missing.

**The receipt is a report, not a freshness proof.** It records what was in the mailbox when it ran, and the mailbox has no run component — Step 7-pre's move-aside is what keeps it fresh for a *fresh* run, and a `--resume` deliberately leaves it alone. So on a resume, treat a bare `OK` as unproven until you have checked that the envelope belongs to this run's reviewer rather than the previous one's.

### Step 7c: Classify the findings — the orchestrator does this itself

Apply the **Classification Rubric** in `.claude/skills/_shared/adversarial-review.md` to each finding the reviewer returned. **This is not delegated to a third sub-agent**: classification is the seam where the human stays the gate, and pushing parse-and-judge one layer down adds no fresh eyes.

- **`fixable`** — absorbed into the plan without human input (mis-cited patterns, convention mis-applications, factual drift, missing tests, N+1 patterns, asymmetric error handling).
- **`blocker`** — needs human input the agent cannot produce (ambiguous requirements, missing source data the task assumes, conflicting goals). Only after genuinely trying to resolve it by reading more code.

**Decompose before rejecting.** A finding asserting several independent clauses, or citing several sites, is adjudicated clause by clause — refuting one clause does not reject the finding, and a rejection rationale must name every clause and why each fails. This failure mode is directional: partial refutation only ever turns a real finding into an apparent false positive, never the reverse.

**Write the classification to disk.** It is the third artifact, and without it the claim that "the artifacts on disk are the resume state" is false — Step 7e takes the classification as an input, and an orchestrator that dies between 7c and 7d otherwise loses it.

```bash
# Compose `findings` from your own classification. Values are yours to write as literals —
# they are not shell variables and nothing carries between blocks (WORKFLOW.md § 8.2a).
# Stdlib only — NO PyYAML. This artifact must be writable on a consumer whose
# bare `python3` has no PyYAML (the PEP-668 default, Phase 131): a classification
# that cannot be written is a pipeline that halts at 7c on an ordinary install.
# `json.dumps` is used to emit the block because JSON is a subset of YAML 1.2, so
# the fence below is genuinely YAML and every scalar is escaped by the stdlib
# rather than by hand.
python3 - <<'PY' "<CLAIM_ID>" "<RUN_ID>"
import sys, json, subprocess
from pathlib import Path

claim_id, run_id = sys.argv[1], sys.argv[2]
# Same reason as Step 7-pre's: this block mkdir -p's its own parent, so an unsubstituted
# placeholder would write into a literally-named directory instead of failing.
if "<" in claim_id or "<" in run_id:
    print("ERROR: placeholder not substituted: {!r} {!r}".format(claim_id, run_id), file=sys.stderr)
    sys.exit(2)

report = {
    "claim_id": claim_id,
    "run_id": run_id,
    "classified_by": "orchestrator",
    "findings": [
        # {"id": "F1", "classification": "fixable", "summary": "...", "response": "incorporated in step 3"},
    ],
    "verdict": "PROCEED",  # or "BLOCKED"
}

# Same MAIN-checkout resolution as Step 7-pre — the artifact directory is not in the
# worktree, so `Path(worktree)/…` here would write a second, unreachable copy.
common = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                        capture_output=True, text=True, check=True).stdout.strip()
main_root = Path(common).resolve().parent

out = main_root / "sysop" / "runtime" / "claim" / claim_id / run_id / "classification.md"
# REFUSE to create the run directory. Step 7-pre is the only thing that mints a run, and
# a `mkdir(parents=True)` here would manufacture one from a mistyped <RUN_ID> -- which
# Step 1's `--resume` validator would then bless, because its whole test is "does this
# directory exist". Only 7-pre creates; every later block writes into what it made.
if not out.parent.is_dir():
    print("ERROR: no such run directory {} -- Step 7-pre mints runs, this step does not"
          .format(out.parent), file=sys.stderr)
    sys.exit(3)
out.write_text(
    "# Classification — {} run {}\n\n```yaml\n{}\n```\n".format(
        claim_id, run_id, json.dumps(report, indent=2, ensure_ascii=False)
    ),
    encoding="utf-8",
)
print("wrote " + str(out))
PY
```

`classified_by: orchestrator` is load-bearing metadata, not decoration: the collapsed shape had the reviewer self-classify, and on disk the two are otherwise indistinguishable.

**If any finding is `blocker` — park. Do not spawn the executor.**

Surface the blocker question to the human if one is present. Then write the park marker. **This is the park procedure the whole skill refers to** — Step 7a's integrity check, the reviewer-failure rule and Step 8's `BLOCKED` arm all route here, and each supplies its own `<PARK_REASON>`:

```bash
# Substitute all four literals. <PARK_REASON> is one line of plain prose saying why this
# claim parked — a `blocker` finding's question, `planner committed during 7a`, `reviewer
# returned no review.md twice`, the executor's BLOCKER_QUESTION — and it is written verbatim.
#
# It is SINGLE-quoted, and that is the one asymmetry in this file: every other placeholder
# here is a shape the tree produced (an id, a SHA, a path), while the park reason is FREE
# TEXT that came back from a sub-agent. Inside double quotes a `$(…)` in that text is command
# substitution and runs — verified, not reasoned. Single quotes make it inert. Before
# substituting, collapse it to one line and replace any `'` with a backtick or `’`; a literal
# single quote is the one character that would end the quoting.
python3 - <<'PY' "<CLAIM_ID>" "<RUN_ID>" "<BRANCH_NAME>" '<PARK_REASON>'
import sys, subprocess
from pathlib import Path

claim_id, run_id, branch, reason = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
# The id and the run key a path this block creates; the branch and the reason are only
# recorded, so an unsubstituted one of those is visible in the marker rather than silent.
if "<" in claim_id or "<" in run_id:
    print("ERROR: placeholder not substituted: {!r} {!r}".format(claim_id, run_id), file=sys.stderr)
    sys.exit(2)

common = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                        capture_output=True, text=True, check=True).stdout.strip()
main_root = Path(common).resolve().parent
art = main_root / "sysop" / "runtime" / "claim" / claim_id / run_id
# Same refusal as the classification write: only Step 7-pre mints a run.
if not art.is_dir():
    print("ERROR: no such run directory {} -- refusing to park against a run that was "
          "never minted".format(art), file=sys.stderr)
    sys.exit(3)

# Which artifacts this park is standing on. An absent one is RECORDED, never silently
# omitted — a missing record and a lost one must not look the same.
present = {n: (art / n).is_file() for n in ("plan.md", "review.md", "classification.md")}

marker = main_root / "sysop" / "runtime" / "parked" / "{}__{}.md".format(claim_id, run_id)
marker.parent.mkdir(parents=True, exist_ok=True)
marker.write_text(
    "# Parked — {} run {}\n\n"
    "- claim_id: {}\n- run_id: {}\n- branch: {}\n- artifacts: {}\n"
    "- reason: {}\n\n"
    "## Artifacts at park time\n\n{}\n\n"
    "Resume with: /claim-task {} --resume {}\n".format(
        claim_id, run_id, claim_id, run_id, branch, art, reason,
        "\n".join("- {}: {}".format(n, "present" if ok else "MISSING")
                  for n, ok in present.items()),
        claim_id, run_id,
    ),
    encoding="utf-8",
)
print("parked -> " + str(marker))
PY
```

**The marker is a pointer, not a copy.** Under the earlier worktree-side layout the park had to *duplicate* the three artifacts, because `cleanup_worktrees.sh --force` removes every non-main worktree wholesale and would have taken the verdict with it. They now live in the main checkout from the moment they are written, so there is nothing to rescue — and one record beats two that can disagree. What the marker adds is a **reason** (which the artifacts do not carry) and **discoverability**: `sysop/runtime/parked/` is where a human hunting resumable work looks, alongside `/auto-build`'s parks.

`/auto-build` Phase 6d writes its park with the `Write` tool from context-held text, and carries a bold warning that a shell variable there would silently produce a blank file reading as a successful record. The divergence is deliberate: this orchestrator carries `disallowed-tools`, so its writes route through the already-seeded `Bash(python3 -:*)` heredoc instead — and `<PARK_REASON>` is the only context-held value in the block, substituted as a quoted literal where an empty one is visible in the marker rather than hidden.

Worktree and lock stay **intact** on a park. Nothing is deleted mid-lifecycle.

**Who removes the marker.** `/review-close` Step 4c already globs `sysop/runtime/parked/<TASK_ID>__*.md` for each closing roadmap task, so a roadmap park's marker is removed when the task closes — the filename shape above is chosen to match that reader, which the earlier directory-shaped park could never have matched. **A review batch's marker is removed by nothing**: Step 4c's list is built from roadmap ids only (`review-close/SKILL.md`, Step 4c), so `BATCH-<N>__<RUN_ID>.md` markers accumulate. That is a known gap, filed with part B; do not paper over it here.

**Re-entering a parked claim.** A park leaves the lock in place, so `claim_task.sh --entry-state <CLAIM_ID>` answers `held` and Step 2 stops — correctly, because from the outside a parked claim and someone else's live claim are the same thing. To resume, the human names the run explicitly: re-invoke with `/claim-task <CLAIM_ID> --resume <RUN_ID>`, which Step 2 honours as the explicit go-ahead its `held` arm requires. **Re-entry lands at Step 7-pre**, which adopts the named run and routes to the stage its artifacts call for — see 7-pre's routing table; the ordinary blocker park re-enters at 7c with the human's answer as the new input. **Do not tell the human to "just re-run `/claim-task <CLAIM_ID>`"** — that hits the `held` stop and reads as a bug.

### Step 7d: The human gate — option A only

Skip this step entirely when Step 6 resolved to **B**.

Present the plan **as reviewed**: the plan artifact, the reviewer's verdict, and your own classification. Approving a plan that has already survived adversarial review is strictly more useful than approving a raw one, which is what plan mode nominally offered.

Three outcomes:

- **approve** → Step 7e.
- **revise** → **first re-run Step 7c's classification write for THIS run with `verdict: SUPERSEDED`**, then go back to Step 7-pre and mint a **new** run, and spawn the planner into it with the human's note appended to the Planner Prompt, running 7b and 7c over it — a revised plan has not been reviewed. **Do not re-plan into this run's directory.** A revised `plan.md` sitting beside the previous plan's `review.md` and `classification.md` is exactly the state 7-pre's routing table cannot tell from a reviewed one. The `SUPERSEDED` flip is the other half and is not bookkeeping: without it the rejected run keeps reading `verdict: PROCEED`, and a later `--resume` naming it walks straight to the executor with **a plan a human explicitly rejected**. One run, one plan; the superseded run stays on disk as the record of what was rejected, and 7-pre's first row refuses to resume it.
- **abandon** → release the claim, **and commit the release**:

  ```bash
  bash sysop/scripts/claim_task.sh --release <CLAIM_ID>
  ```

  ```bash
  test "$(git rev-parse --abbrev-ref HEAD)" = "main" || {
    echo "HEAD is not main (a concurrent actor moved it) — STOP."; exit 1; }
  git add tasks/index.yml
  git commit -m "chore: release <CLAIM_ID>"
  ```

  **The commit is not optional and the script will not do it for you** — it says so on its own last line. Step 4d *committed* `status: in_progress` onto `main`; `--release` flips the index back and deletes the lock in the **working tree only**. Stop after the script and committed `main` reads `in_progress` **with no lock**, which is `validate_tasks.py` Invariant 9 — a blocking error — plus `/sitrep` index drift, for every person who pulls. Step 2's own table calls that state a defect. Verified by execution.

  **Review batches need no commit here:** `batch_work.sh --release` owns `review_tasks.md` and commits its own reversal, so its working tree comes back clean. The asymmetry is real, not an oversight — the two scripts divide the work differently.

**Review batches:** the abandon outcome is `bash sysop/scripts/batch_work.sh --release <BATCH_NUMBER>`, **never** `claim_task.sh --release`. That script matches a `BATCH-*` id and a bare integer and **exits 1**, because it owns `tasks/index.yml` and releasing only the lock would leave the batch reading `In Progress` forever. Getting this wrong is a runtime hard error on the gate's own exit path.

### Step 7e: Spawn the executor

Inputs: the (possibly revised) plan artifact, the review artifact, and your classification.

Same agent parameters as 7a, with `description`: `"Execute <CLAIM_ID>"`.

---

**START OF EXECUTOR PROMPT**

You are implementing `<CLAIM_ID>`. The orchestrator has already claimed the work (worktree at `<WORKTREE_PATH>`, lock at `sysop/runtime/locks/<CLAIM_ID>.lock`, branch `<BRANCH_NAME>`), produced a plan, run an independent adversarial review of it, and classified every finding as `fixable`. **No `blocker` findings remain — if any had, you would not have been spawned.**

**Working directory:** `<WORKTREE_PATH>` (cd here first; do not run from the project root or any sibling worktree).

Read your three inputs from disk rather than from this prompt: `<ARTIFACT_DIR>/plan.md`, `<ARTIFACT_DIR>/review.md`, `<ARTIFACT_DIR>/classification.md`. `<ARTIFACT_DIR>` is an **absolute path in the main checkout, outside your worktree** — read it as given, and do not include it in your commit.

### Sequence

1. **Absorb the classification.** For each `fixable` finding, apply its recorded `response` to the plan as you implement. Where a finding was rejected, its rationale is in `classification.md` — do not silently re-litigate it.
2. **Implement** per the plan. Re-open the files it touches; do not rely on its summaries.
3. **Persist the `## Test decision`** section into the task's body file, per the plan's step for it. **Write the worktree copy** (`<WORKTREE_PATH>/tasks/…`), never the main checkout's — an edit there is on no branch, so it never reaches the PR, and `/review-close` Step 2d reads this record at the branch tip. **If the plan's step names a main-checkout path, correct it and note the correction** rather than following it. The one exception is a body that is untracked in the main checkout (`/add-task` filed it and nobody committed it): it is on no branch and cannot be put on one, so write the main-checkout copy and **say so in your final message** — that record will not reach the PR and the body needs committing before `/review-close` runs.
4. **Post-fix convention verification.** `git diff --name-only main...HEAD`; for each changed file look up its section in `.claude/convention_map.md` and scan the **new/changed lines** — not just the original task locations — against those conventions. Common regressions: `fetch()` without `encodeURIComponent()` on dynamic path segments; `str(e)` exposed to API responses; moved code that dropped `_sanitize_log()` wrappers; `useCallback` with incomplete dependency arrays; SELECT queries on a write-only engine. Fix regressions before committing.
5. **Run the consumer's pre-merge verification gates.** `<project>/CLAUDE.md § Pre-merge verification` may carry `### Always` (full-tree commands) and `### Ratchet (changed files only)`. Run the commands under each subsection present. If both are absent, skip — `/review-close` will run any project-side verification at merge time (its `4a-post` step, on the merged tree). Note the division of labour: this run verifies **this branch in its own worktree** — so when the consumer ships no `## Pre-merge verification` section and this step skips, *nothing* verifies the branch in isolation; `4a-post` verifies the **assembled** result and cannot substitute for it. Treat a non-zero exit like an implementation finding — fix the cause, do not silence it without a justified inline `# type: ignore[...]` or `// eslint-disable-next-line <rule> -- <reason>`.
6. **Post-fix UI verification.** If the diff touches any `frontend/` files, run `.claude/skills/_shared/ui-verify.md`. Hard-fail on console errors and 5xx responses; warn on console warnings; skip cleanly with an explicit note if the dev server is not running, and surface that note verbatim in your final message.
7. **Commit** — a SINGLE commit on the worktree branch, conventional message derived from the task title plus `<CLAIM_ID>`, with a `Doc-Work: <CLAIM_ID>` trailer on the final line of the body, separated by one blank line. That trailer is the deterministic marker `/sitrep` consumes to classify the branch as ready for `/review-close`.

   ```
   <type>: <title> (<CLAIM_ID>)

   <optional body prose>

   Doc-Work: <CLAIM_ID>
   ```

### Hard constraints

- Do **NOT** invoke the Agent tool — this run is a leaf, and the envelope contract assumes a flat hierarchy.
- Do **NOT** write to `sysop/runtime/subagent-envelopes/`. That directory is written **only** by the `SubagentStop` hook, and that is the entire reason it is evidence: no agent can cause it to exist. Writing it yourself converts the one unforgeable artifact into a forgeable one.
- Do **NOT** flip `status:` fields in `tasks/index.yml`. Adding a new follow-up task entry IS allowed and expected if `/document-work` Step 3b would flag an unfiled follow-up ID.
- Do **NOT** push to origin (`/review-close` owns the push).
- Do **NOT** invoke `/document-work` (the orchestrator does, at Step 8).

### Required final-message format

Emit exactly this as the LAST fenced block of your final message, with NO content after the closing backticks:

```yaml
TASK: <CLAIM_ID>
PHASE: exec
STATUS: EXECUTED | BLOCKED | FAILED
BLOCKER_QUESTION: <only if BLOCKED — the question for the human; else "none">
WORKTREE: <absolute path, no trailing slash>
BRANCH: <branch name>
ERROR: <error description if FAILED, else "none">
```

Print your step outputs as prose ABOVE the envelope so a human can see what happened even if the envelope is malformed.

**END OF EXECUTOR PROMPT**

---

### Failure handling — one rule per spawn point

The tempting recovery from a failed reviewer is *"continue to the executor anyway"*, which is failure mode 1 restored with no plan mode to blame and no `ExitPlanMode` signature to detect it. So these are rules, not judgement:

| Spawn | Failed, malformed, or artifact-less return | Rule |
|---|---|---|
| **7a planner** | no `plan.md`, or a `FAILED` envelope | **Do not hand-write the plan.** Re-spawn once. On a second failure, stop and report with worktree and lock intact. |
| **7b reviewer** | no `review.md`, or a `FAILED` envelope | **Never proceed to 7e.** This is the single most important rule in the pipeline. Re-spawn once, then park per 7c with `reviewer returned no review.md twice` (or the envelope's `ERROR:`) as the recorded reason. |
| **7b reviewer** | `review.md` present, envelope parsed, `review_report_raw` null | Disjoint from the row above — that row fires on a **missing `review.md`** or a `FAILED` envelope, and this one requires `review.md` to be there, so the two cannot both apply. It was the shape that shipped a silent failure (#329). The **post-review transport check** decides it: re-spawn once, then proceed on `review.md` with `review-transport.md` recording `EMPTY_TRANSPORT`. **Does not park** — see the dispositions in Step 7b for why this one differs. |
| **7e executor** | `FAILED` or malformed | Today's Step 8 handling, unchanged: surface `ERROR` verbatim, show `git log` / `git status` in the worktree, let the human decide. **No auto-retry.** |

**Orchestrator context exhaustion mid-pipeline** — the artifacts under `<ARTIFACT_DIR>` are the resume state, and nothing is deleted mid-lifecycle, so re-entry is `/claim-task <CLAIM_ID> --resume <RUN_ID>`, which lands at Step 7-pre and routes off those artifacts. Nothing parked, so there is no park marker — but the claim's **own** lock is still in place, so `--entry-state` answers `held`, and `--resume` is exactly the way past it.

## Step 8: Receive the executor envelope and hand off

Read the envelope in this order — first hit wins; never go past a clean hit:

1. **JSON file** (preferred). `sysop/runtime/subagent-envelopes/<CLAIM_ID>.exec.json`, resolved against the **main repo root** (`git rev-parse --git-common-dir`, then its parent) — the hook resolves its own output that way, so the file lands in the main checkout even when the sub-agent ran in a worktree. Keys: `status`, `worktree`, `branch`, `error`, `blocker_question`, `review_report_raw`. The `SubagentStop` hook runs synchronously before the parent receives the `Agent` return, so absence is never a race.

   Because every prompt above emits `PHASE:`, this claim's envelopes are `<CLAIM_ID>.plan.json`, `<CLAIM_ID>.review.json` and `<CLAIM_ID>.exec.json`. **Read the `exec` one here.** The plan and review envelopes are still live and carry the reviewer's sealed report; do not read them as the executor's result and do not delete them.

   **Before concluding an envelope is absent, look for `_unparseable_*.json`.** A malformed envelope is written as `_unparseable_<session>_<agent>.json` — keyed by session and agent, **not** by claim id or phase — so an orchestrator globbing `<CLAIM_ID>.*.json` sees nothing at all and would otherwise report "the executor never ran" when what actually happened is that it ran and its envelope did not parse.

   **Treat it as a hint to go and look, never as this run's result.** Nothing in the filename ties a diagnostic to a claim, a phase or a run, and these files persist across runs on purpose — Step 7-pre's move-aside deliberately leaves them alone, precisely because they are diagnostics rather than results. So a diagnostic sitting in the mailbox may belong to another claim entirely, to `/auto-build`, or to a run of this claim from last week. Open it and read its contents before attributing it to anything; if it does not name this claim's work, say the executor's envelope is missing and report that, rather than reporting a stranger's failure as this claim's.

2. **Regex parse of the executor's return text.** Parse the YAML envelope from the LAST fenced block of its final message. Defense in depth for an unregistered hook or a failed write, not a timing fallback.

**Review batches:** substitute `<CLAIM_ID>` throughout — the hook's shape check accepts `BATCH-<N>`, so a batch claim's envelopes really are `BATCH-116.exec.json`. This step is **not** roadmap-only.

**Do not delete the envelopes here.** Deleting after consumption is why a review that *did* run left no durable trace: the envelope was the one artifact no agent could forge, and it was removed at the moment it became evidence. The whole artifact set — `<ARTIFACT_DIR>` and the three envelopes — persists.

**What cleans it up, stated as it is rather than as it should be.** Nothing does, yet. `/review-close` Step 4c removes the *lock* and any roadmap park *marker* for a closing task; it does not touch `sysop/runtime/claim/` for either claim kind, and it does not remove a batch's park marker. Close-time cleanup of the artifact set is part B of this reshape and is not built. Until it is, the directory grows one run per claim under a gitignored path — the deliberate trade, since the failure this reshape exists to remove is an artifact that vanished, not one that accumulated. Step 7-pre's move-aside is what keeps the *envelope mailbox* from going stale between runs, and it is the only thing that touches these files mid-lifecycle.

**On `BLOCKED`, rewrite the classification FIRST — before the outcome record below.** The order is load-bearing and a different-model review of the whole pipeline is what found it: a crash between the two writes must leave the run in the state that routes *back into adjudication*, not the one that reports it as finished. Writing `outcome.md` first and crashing leaves `classification.md` still reading `PROCEED`, and the routing table then matches the outcome row and reports a blocked run as complete. Writing the classification first and crashing leaves `verdict: BLOCKED` with no outcome record, which routes to 7c — correct, and the safe direction.

**Then, whatever the status, record the executor's terminal outcome into this run.** It is what tells a later `--resume` that the executor already ran *here*, without consulting the shared envelope mailbox — which is keyed by claim and phase with no run component, and which a resume deliberately does not clear:

```bash
# Substitute all three literally. <EXEC_STATUS> is the envelope's STATUS verbatim
# (EXECUTED | BLOCKED | FAILED | MALFORMED).
python3 - <<'PY' "<CLAIM_ID>" "<RUN_ID>" "<EXEC_STATUS>"
import sys, subprocess
from pathlib import Path

claim_id, run_id, status = sys.argv[1], sys.argv[2], sys.argv[3]
if "<" in claim_id or "<" in run_id:
    print("ERROR: placeholder not substituted", file=sys.stderr)
    sys.exit(2)
common = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                        capture_output=True, text=True, check=True).stdout.strip()
out = Path(common).resolve().parent / "sysop" / "runtime" / "claim" / claim_id / run_id / "outcome.md"
if not out.parent.is_dir():
    print("ERROR: no such run directory {}".format(out.parent), file=sys.stderr)
    sys.exit(3)
out.write_text("# Outcome — {} run {}\n\n- executor_status: {}\n".format(claim_id, run_id, status),
               encoding="utf-8")
print("wrote " + str(out))
PY
```

**On `STATUS: EXECUTED`** — print the sealed `REVIEW_REPORT` (from `review_report_raw` on the review envelope). **If that field is null**, do not print nothing and move on: say `Review transport was empty — the sealed report never reached the orchestrator` and print `review-transport.md`'s verdict alongside `<ARTIFACT_DIR>/review.md`, so the human reading this report sees which channel the findings came through. Then run the stranded-body check:

```bash
# No placeholders — run it as written. The orchestrator stands in the main checkout, but
# a CWD that had drifted into the worktree would report the WORKTREE's tree, clean by
# construction after 7e's commit, so the root is resolved rather than assumed. Scoped to
# `tasks/` and to TRACKED modifications on purpose: an untracked-inclusive probe fires on
# every ordinary scratch file (review-close/SKILL.md Step 6 narrows the same way for the
# same reason), and an untracked body is the one case the executor deliberately writes
# on main. Stdlib only, and a heredoc rather than a bash one-liner, per Phase 126.
python3 - <<'PY'
import subprocess
from pathlib import Path

common = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                        capture_output=True, text=True, check=True).stdout.strip()
main_root = Path(common).resolve().parent
changed = subprocess.run(
    ["git", "-C", str(main_root), "diff", "--name-only", "HEAD", "--", "tasks/"],
    capture_output=True, text=True, check=True).stdout.split()
if changed:
    print("STRANDED — task-body edits are uncommitted on main:")
    for p in changed:
        print("  " + p)
else:
    print("tasks/ CLEAN — no body edits stranded on main")
PY
```

**If that printed `STRANDED`** — the executor wrote body edits into the main checkout instead of the worktree (upstream #322). They are on no branch, so they do not reach the PR, and nothing downstream notices: `/review-close` Step 4c `git mv`s the body into `tasks/archive/`, and the edits never having been staged, the rename stages **`HEAD`'s** content, so the body contributes `0 insertions(+), 0 deletions(-)` to the consolidation commit — the rename lands, the documentation does not. (The commit itself is larger; it also carries `tasks/index.yml` and the pending docs.) The only backstop is Step 6's tracked-tree gate, which fires **after `gh pr merge` has landed**, too late to save the PR. So: surface the file list the block just printed, **skip the auto-mode chain**, and tell the human the edits must be moved onto the branch (still checked out at `<WORKTREE_PATH>`, whose work commit is amendable) before `/review-close` runs. **Do not move them yourself** — which copy is authoritative is the human's call.

**An untracked body is not `STRANDED`, and the probe is scoped so it does not report as one.** `git diff HEAD` ignores untracked files, so an `/add-task` body nobody committed leaves this quiet — correctly, because that body is on no branch and cannot be put on one. The executor reports that case itself, in its own final message.

Then:

```
## Claim complete: <CLAIM_ID>

| Field     | Value                                    |
|-----------|------------------------------------------|
| Task      | <CLAIM_ID>                               |
| Worktree  | <WORKTREE_PATH>                          |
| Branch    | <BRANCH_NAME>                            |
| Artifacts | <ARTIFACT_DIR>                           |

A planner, an independent reviewer, and an executor each ran in their own cold
context; findings were classified by this session. The work is committed in the
worktree and NOT pushed. Run `/document-work` next. Do NOT merge to main —
`/review-close` handles that.
```

`<ARTIFACT_DIR>` is the absolute path Step 7-pre printed — `<main repo root>/sysop/runtime/claim/<CLAIM_ID>/<RUN_ID>/`. Print the absolute form rather than the repo-relative one: the human reading this box may be standing in the worktree, where the relative path resolves to nothing.

**Auto-mode chaining.** Under `auto` mode, invoke `/document-work` directly via the `Skill` tool rather than ending the turn. Skip the chain when the executor returned `BLOCKED` or `FAILED`, **when the stranded-body check printed `STRANDED`**, when a UI-verify note flags pending manual checking, when the harness is not in `auto` mode, or when the user asked to pause. The chain does **not** extend to `/review-close`, which stays user-initiated.

**On `STATUS: BLOCKED`** — print the sealed report and the `BLOCKER_QUESTION:`. **The same null arm applies here** — `review_report_raw` can be null on this path exactly as on the one above, and this is the report a human is about to answer a question from, so an empty sealed report has to be named rather than rendered as a blank. Then, **before parking, re-run Step 7c's classification write with `verdict: BLOCKED`** and a finding recording the executor's blocker question. Only then park per Step 7c, with the `BLOCKER_QUESTION:` text as the recorded reason, and tell the human to resume with `/claim-task <CLAIM_ID> --resume <RUN_ID>`.

**The rewrite is not bookkeeping — without it the resume is a no-op that re-runs the executor.** `classification.md` still reads `verdict: PROCEED` at this point, because it had to for 7e to have been spawned at all. Leaving it there sends 7-pre's routing table to its last row, which re-spawns the executor with byte-identical inputs and gives the human's answer nowhere to land — so the one runtime path that actually produces a blocker question would never reach the row written for it.

**On `STATUS: FAILED`** — print the `ERROR` verbatim, run `git log --oneline main..HEAD` and `git status --short` in the worktree and surface both. If substantive work landed despite the failure, let the human decide whether to recover or discard. **Do not auto-retry.**

**On a malformed envelope** — print `Executor returned with a malformed envelope — treating as FAILED`, surface its prose body (which likely contains the implementation output), and check for an `_unparseable_*.json` diagnostic. Do not auto-retry.

This is the orchestrator's terminal action. Control returns to the user.
