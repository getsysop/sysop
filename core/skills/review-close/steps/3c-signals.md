**First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

```bash
python3 sysop/scripts/close_arms.py loaded "<close-id>" 3c-signals 130b7b267e622ad3 "<skill directory>"
```

It prints `LOADED: 3c-signals`. **Exit 2**: stop and show its stderr.

Each block's `READ:` line names what its text was read from. **A task body is read as it will merge**: the tip of the approved branch that claims it, three-way merged with local `<default branch>`, and with `origin/<default branch>` unless the local branch already contains it. A label ending `the branch tip, the text that is merging` means no target changed the body. `merged with` names the targets that changed it after the fork. `CONFLICTS` means each side of the conflict was read on its own and both were scanned. `the branch tip, read as is:` means a merge could not be read, says why, and comes with a `MERGE NOT READ:` line. A `working tree` label means no approved branch claims the task, or the tip read failed and the line says why. A `#` line inside a closed fenced code block does not end a section, so a procedure is shown whole; a fenced line that matches the heading pattern still signals. A `NOT MERGING:` line marks a doc in main's `pending-docs/` whose branch is neither approved nor the branch HEAD is on, and says whether Step 4c 1c is holding it. A `KEY:` line is a hash of the section's text and names the doc its answer is recorded in. A `BRANCH:` line names the approved branch the signal's work merges on; a signal without one is on no approved branch.

**2. For each signal, call `AskUserQuestion`.** Present the section text verbatim with its `SOURCE:`, `READ:` and any `NOT MERGING:` or `BRANCH:` line. Four options (single-select):

- **"I'll drive the smoke"** — agent attempts to run the procedure using available MCP tools (chrome-devtools-mcp, playwright, project-specific CLI tooling). The agent reads the section's step list, drives it, and reports the outcome.
- **"Already ran it manually — proceed"** — human confirms they ran the smoke; record as confirmed.
- **"Unrunnable as specified"** — the procedure cannot be completed as written, so no re-run can help: an input the job cannot reach, or a step the environment rejects. Record the reason. Step 3 files the blocking defect.
- **"Skip with waiver"** — record as waived, with the source label, for Step 8's report.

Ask signals one at a time; track per-signal decisions in a structured tally (source → decision, and the reason for an unrunnable one). **Record each "Already ran it manually" or "Unrunnable as specified" answer to a signal with a `KEY:` line at once**, with step 4's recorder, before the next signal and before any halt below. Under `--dry-run`, offer only the other three options, record nothing and file nothing, and report the signals and each answer; a halt below ends the dry run at Step 8's report.

**3. Halt rules.**
- If the human picks "I'll drive", the procedure either passed (record the signal `driven`), ran to a FAIL verdict, or could not finish.
- **Ran, verdict FAIL** — the procedure ran and a step failed: a check it states failed, or a step exited non-zero. When you cannot tell a failed step from something outside the procedure stopping it, take this arm. A re-run will not change a verdict, so do not ask whether one can succeed. Show the output and ask once, with `AskUserQuestion`:
  - **"Halt the close"** (recommended, first): halt as for a transient failure below.
  - **"Hold just this branch"**, offered only when the signal has a `BRANCH:` line: demote that branch from approved to rejected for this run, as Step 2d's "Hold for fix" does, with the reason `smoke FAIL — <the failing step>`. Skip the remaining signals on that branch and continue with the rest. Record the signal `failed-held`, with the signals skipped on that branch.
  - **"Waive — merge with the FAIL recorded"**: record the signal `failed-waived`, with the procedure's output verbatim, and file it as a task as for an unrunnable defect below, its body naming the failing step and carrying the redacted output; file it at the start of Step 4d. Step 8 reports it, and under `pr` Step 4d also puts it in the PR.
- **Could not finish** — something outside the procedure stopped it. **Ask whether a re-run can succeed**, with `AskUserQuestion` and two options. **"Transient — halt and re-run"** covers an MCP tool not available, a credential, or a network or infrastructure error: **halt this run**. Do not proceed to Step 4. Before any halt in this step, file each unrunnable defect a "Continue the close" answer deferred to Step 4d, by the **Stop** path below; its answer is already recorded, so a later close will not ask it again. Surface what failed; the next `/review-close` invocation re-runs Step 3c. **"Cannot be completed as written"** makes the signal "Unrunnable as specified", with what failed as its reason. A procedure that ran to a FAIL takes the FAIL arm above, never this one.
- **"Unrunnable as specified" is neither a waiver nor a halt.** File the blocking defect as a task by `/add-task` Steps 2, 3 and 5.1–5.3: `status: open`, `surfaced_by:` the task ids the signal's source names: the `§ <id>` of an index signal, or the doc's `roadmap_ids` (`[]` when it names none), and a body saying which part of the procedure cannot run and why. Then ask with `AskUserQuestion`: **"Continue the close"** or **"Stop the close"**.
  - **Continue:** file it at the start of Step 4d. A close that stops before Step 4d names it on Step 8's `Manual smoke:` line, unfiled.
  - **Stop:** file it now, then halt as for a transient failure. `HEAD` is the default branch before Step 4, so the commit is chained after that check:

    ```bash
    python3 sysop/scripts/validate_tasks.py
    python3 sysop/scripts/git_check.py head-is "<default branch>" && git add -- tasks/index.yml <each other file those steps wrote> && git commit -m "docs: review-close file unrunnable smoke — <N> task(s)"
    ```

    If the check exits non-zero, nothing was committed: name the defect on Step 8's `Manual smoke:` line, unfiled, and halt. Never commit on a red validator. Without `tasks/index.yml`, name the defect on Step 8's `Manual smoke:` line for the human to file.
- Waivers do NOT halt; they accumulate for Step 8.
- "Already ran it manually" is trusted at face value — the entire point of the gate is letting the human assert "yes, I did the thing."

**4. Record outcomes for Step 8.** The tally drives the "Manual smoke" line in the final report (e.g., `Manual smoke: 1 confirmed, 1 unrunnable (FIX-CSV-UNREACHABLE filed), 1 failed-held (feat/export), 1 waived (sysop/runtime/pending-docs/feat-foo.md)`). **An unrunnable, `failed-held` or `failed-waived` signal is its own state, never counted as waived.**

**The recorder step 2 runs.** Pass it the doc the `KEY:` line names, in main or in a workspace, and the key's 16 hex. **Never record a waiver.** Under `--dry-run`, record nothing and file nothing; list what would be recorded and filed.

```bash
python3 sysop/scripts/smoke_record.py "<the doc the KEY line names>" "<the KEY's 16 hex>" "<confirmed or unrunnable>"
```

A `REFUSING:` line records nothing and changes nothing. Report it on Step 8's `Manual smoke:` line; the next close asks that section again.
