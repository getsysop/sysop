---
name: plan-review
description: Run an adversarial pass on an ad-hoc plan (from conversation or a file), incorporate findings, and present the revised plan for approval before executing.
argument-hint: "[<path/to/plan.md>]"
model: opus
---
<!-- sysop:model-roles frontmatter=reasoning -->

Run an adversarial pass on a plan, incorporate findings, and re-present it for approval. Use this for ad-hoc plans — plans NOT produced by `/claim-task`, which has the adversarial step built in. Follow these steps in order.

> **Helper names** referenced in this skill (e.g., `_sanitize_log`, `useAbortableFetch`, `getDisplayError`, `redact_api_keys`, `shared_cli.py`) are placeholders — substitute the equivalent helpers from your project's `convention_map.md`. Worked examples may also reference specific batch numbers, file paths, or env-var names from the originating project; treat those as illustrations, not literal requirements.

## Step 1: Parse Argument

Parse `$ARGUMENTS`:

- **Empty** → operate on the most recent plan in the current conversation (**in-conversation mode**).
- **A file path** → `Read` the file and operate on its contents (**file mode**).
- **Anything else** → print usage and stop:

  ```
  Usage: /plan-review [<path/to/plan.md>]

  Examples:
    /plan-review                          — review the most recent plan in this conversation
    /plan-review .claude/plans/foo.md     — review a saved plan file
  ```

## Step 2: Locate the Plan

**In-conversation mode:** scan conversation history for the most recent plan. Look, in order of preference:

1. The most recent `EnterPlanMode` / `ExitPlanMode` tool call — the plan content is in the tool's input.
2. The most recent assistant message containing a heading like `## Plan`, `## Implementation Plan`, `## Approach`, or `## Proposed Implementation`.
3. The most recent assistant message that is structurally a plan (numbered steps, "Step 1/2/3...", file/line citations, critical files table).

If none of those exist, print:

```
No plan found in conversation. Either draft a plan first, or pass a file path:
  /plan-review <path/to/plan.md>
```

and stop.

**File mode:** `Read` the file path. If the file does not exist or is empty, print an error and stop.

Store the plan text as `PLAN_TEXT` for use in the next step.

**Deterministic preamble check:** Before continuing to Step 3, scan `PLAN_TEXT` for a `## Constraints & Risks` heading. If absent, OR if present but the section body contains zero bullets (`- ` lines) before the next `## ` or `### ` heading, print:

```
## Plan Rejected — Missing `## Constraints & Risks` preamble

Required by `.claude/skills/claim-task/SKILL.md` Step 6: the plan must enumerate
per-file/directory conventions and risks from `.claude/convention_map.md` +
`.claude/security_map.md` before any `## Implementation Steps`. Add the section
and re-run `/plan-review`.
```

…and stop without spawning the sub-agent (do not proceed to Step 3). This saves an Opus invocation when the structural defect is unambiguous.

## Step 3: Spawn Adversarial Review Sub-Agent

**Procedure:** follow `.claude/skills/_shared/adversarial-review.md` — it owns the Agent-tool call shape, the prompt template, and the `fixable` / `blocker` classification rubric. `PLAN_TEXT` for this caller is the plan content located in Step 2 (either the conversation-found plan or the file-mode body).

**Caller-specific contract for /plan-review:**

- After the sub-agent returns, store the response verbatim as `RAW_FINDINGS` for Step 4's print-back, then proceed to Step 5's classification + revision pass.
- Steps 4–8 own the incorporation, summary, branch-on-mode, and presentation flows — the shared partial covers the spawn + classify contract only.

## Step 4: Print Raw Findings

Before incorporating anything, print `RAW_FINDINGS` verbatim in a clearly-labeled block so the output is auditable:

```
## Adversarial Review — Raw Findings

<RAW_FINDINGS verbatim>
```

## Step 5: Incorporate Findings into Revised Plan

Produce a revised plan (`REVISED_PLAN`) that is executable as the new source of truth — not a commentary on the original.

- For each **blocker** finding → modify the relevant plan step so the issue is resolved. Prefer targeted revisions over full rewrites.
- For each finding you **reject** (genuinely disagree with after considering it) → add an inline note in the relevant plan section explaining why, so the same issue does not resurface in a future review. Format:

  ```
  > **Adversarial review rejected:** <finding summary>. Rationale: <why>.
  ```

- Append an `## Adversarial Review — Incorporated Changes` section at the end of the revised plan listing each blocker that was accepted and what changed in response:

  ```
  ## Adversarial Review — Incorporated Changes

  1. <finding summary> → <what changed in the plan>
  2. ...
  ```

- If the sub-agent returned **zero blockers**, append this line to the plan instead:

  ```
  > **Adversarial review: no blockers found.**
  ```

  Still proceed to Step 8 — a clean review still goes through the native approval prompt.

## Step 6: Print Review Summary

Print a compact summary table:

```
## Adversarial Review Summary

| Metric                                | Count |
|---------------------------------------|-------|
| Blockers incorporated                 | N     |
| Findings rejected (with rationale)    | M     |
| File/line citations verified          | K     |
```

Count `K` from whatever `RAW_FINDINGS` indicates the sub-agent re-opened. If the sub-agent did not report verification count, omit that row.

## Step 7: Branch on Mode

**In-conversation mode:** skip to Step 8.

**File mode:** use the `AskUserQuestion` tool to ask which action to take:

```
Question: How should I handle the revised plan for <path>?
Options:
  A. Overwrite <path> with the revised plan and proceed to execute
  B. Leave <path> alone and proceed to execute with the revised plan in-memory
```

- If the user picks **A** → `Edit` or `Write` the file at `<path>` with `REVISED_PLAN` content. Confirm the write (print `Wrote revised plan to <path>`), then proceed to Step 8.
- If the user picks **B** → proceed to Step 8 without touching the file. Print `Leaving <path> unchanged; executing from in-memory revised plan.`

## Step 8: Present Revised Plan for Approval

Present `REVISED_PLAN` using the standard plan-mode approval flow:

- If not already in plan mode, call `EnterPlanMode`.
- Call `ExitPlanMode` with `REVISED_PLAN` as the plan content.

This surfaces the native accept/reject confirmation prompt, matching the existing plan-mode UX.

**After the user approves the plan,** return to implementation mode and print:

```
Revised plan approved. Proceeding with implementation.
```

Then proceed with implementation of the revised plan exactly as written. Do not re-interpret or re-scope the plan after approval.

If the user rejects the plan, do not execute. Ask what they want changed and revise — do not loop back into another adversarial review unless explicitly asked.

## Notes

- **Complementary to `/claim-task`.** `/claim-task` runs the same adversarial review automatically at Step 7, inside a single reviewer-executor sub-agent that also self-classifies and implements (see `claim-task/SKILL.md` § Step 7 and `_shared/adversarial-review.md` § "Reviewer-executor variant"). Use `/plan-review` only for plans NOT produced by `/claim-task` — otherwise you are paying for two adversarial passes on the same plan.
- **Token cost.** Each invocation spawns a fresh opus sub-agent. Re-running on the same plan after edits is valid but costs tokens. Do not re-run speculatively.
- **No size gate.** The skill does not gate on plan size — tiny plans still trigger the full adversarial pass. Skip invoking the skill for trivial changes rather than adding a complexity threshold, which would reopen the gap we are trying to close.
- **Do not dismiss findings silently.** Every finding must be either incorporated or explicitly rejected with rationale in the revised plan. Silent dismissal defeats the purpose of the review.
