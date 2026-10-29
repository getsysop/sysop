**First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

```bash
python3 sysop/scripts/close_arms.py loaded "<close-id>" prepare-resume f7f30d8eecc3b582 "<skill directory>"
```

It prints `LOADED: prepare-resume`. **Exit 2**: stop and show its stderr.

Both also require `Bash(python3 sysop/scripts/close_run.py:*)` in the allow-list the guard above read, unless `--skip-permission-guard` skipped the guard. If it is missing, stop as the guard does.

### Under `--prepare`

A prepare runs Steps 1, 2, 3 and 3c for real, asks the human nothing, records the questions it can in a run directory instead (Step 3's are left for the resume), and stops before Step 3b. Step 1b commits, Step 2b spawns its reviewers and Step 3c fetches, as on any close. Nothing from Step 3b on runs.

1. **Open the run** after Step 1 and before Step 2a, from the main checkout's top level. Name every branch Step 2a will consider (agent worktree branches excluded), each quoted, or none when there is none:

   ```bash
   python3 sysop/scripts/close_run.py begin "<default branch>" "<branch>" "<branch>"
   ```

   It prints `RUN: <run-id>`, `DIR: <run directory>` and one `STATE <branch>: <file>` line per branch. On a non-zero exit, stop the prepare and show its stderr.

   **With `--agent <name>`**, before Step 1, read `CLAUDE.md`'s `## Merge policy`, then run `python3 sysop/scripts/close_run.py reader` and `python3 sysop/scripts/close_run.py class` and report each `WARN:` line. If the policy is not `pr` or either command exits non-zero, stop. Pass `--agent "<name>"` to `begin`, right after `"<default branch>"`, so `finish` names the unattended resume. Append nothing to `SYSOP_ISSUES.md` in this prepare; put friction in the run's `close.md`. Then, right after `begin`, select with the same branches:

   ```bash
   python3 sysop/scripts/close_run.py eligible "<default branch>" "<name>" --held "<branch>" "<branch>"
   ```

   Write each `OUT` branch's verdict, **SKIP — outside the unattended class** with its line as the reason, into its `STATE` file, and leave it out of Steps 2a to 3c. Write each `NOTE:` line into `<DIR>/close.md`. If no branch is `IN`, halt the prepare (item 4). On a non-zero exit, halt the prepare.

2. **Ask nothing; record instead.** Where Step 2a step 3a, Step 2d or Step 3c says to ask, append the question to `<DIR>/questions.md` in this shape, numbering from `Q1`, and carry on:

   ```
   ## Q<n> · <step> · <branch, or close>
   <the question, with every line the step says to show, verbatim>
   Options: <each option the step offers, verbatim, separated by " | ">
   If unanswered: <the park, from the list below>
   ```

   Write `<step>` as exactly `Step 2a step 3a`, `Step 2d` or `Step 3c`: item 5 of the resume keys on it.

   The parks: Step 2a step 3a → the verdict **SKIP — ignored file unanswered**; Step 2d → **Hold for fix**; a Step 3c signal with a `BRANCH:` line → **Hold just this branch**; a Step 3c signal without one → the resume halts before Step 3b.
   - **Step 2a step 3a and Step 2d:** carry the branch on through Steps 2b–2e, 3 and 3c as approved, with its verdict marked `pending Q<n>`. Step 3a commits and copies nothing.
   - **Step 3:** item 5's ask, or a silently denied command, records no question. Write why in `<DIR>/close.md` and leave Step 3 not run; the resume runs it attended.
   - **Step 3c:** record each signal as its own question, with its `SOURCE:`, `READ:`, `KEY:`, `BRANCH:` and `NOT MERGING:` lines and its four options. Record nothing with the recorder, and drive nothing.

3. **A `VERDICT: BLOCKED` from Step 2b on a branch stops that branch, not the prepare.** Write its violations, with their `file:line` citations, into the branch's state, keep the branch out of Steps 2d, 3 and 3c, and go on with the others. A `VERDICT: BLOCKED` on the unpushed-main group halts the prepare (item 4). **With `--agent <name>`**, also hold the branch, with the first violation as the reason:

   ```bash
   python3 sysop/scripts/close_run.py hold "<run-id>" "<branch>" "VERDICT: BLOCKED: <first violation>"
   ```

   A Step 2b reviewer that returns no `VERDICT:` line halts the prepare (item 4), with its last output as the reason.

4. **Every other stop halts the prepare:** any halt, failure or refusal the text gives in Steps 1 to 3c, and any exit it gives no instruction for. Write the step and the reason to `<DIR>/halted.md`, report them with the run id, and stop.

5. **Write the state as you go.** Each branch's `STATE` file holds Step 1a's class and any Step 1-pre line; Step 2a's verdict, its reason and any step 0, 0a or 0b line; Step 2b's verdicts and `NOTES:` from both fleets, or why a fleet skipped; Step 2d's tally; Step 2e's report; and the numbers of its pending questions. `<DIR>/close.md` holds Step 1's other lines, Step 2b's verdicts and `NOTES:` for the unpushed-main group, Step 2c's result, Step 3's `Verification:` line or why it did not run, Step 3c's output verbatim (its first line, the carried lines and every signal block), and every Step 8 row these steps produced. Write `questions.md` even when it holds no question.

6. **Finish** at the end of Step 3c:

   ```bash
   python3 sysop/scripts/close_run.py finish "<run-id>"
   ```

   Exit 1 names each missing file: write it, then run `finish` again. Then report the run id, each branch's verdict, the `QUESTIONS:` count, every `MOVED DURING PREPARE:` line and the `RESUME:` line, and stop.

### Under `--resume <run-id>`

Run the default-branch resolve and the permission guard above first. Then, in this order. **On any non-zero exit from `close_run.py`, stop and show its stderr.**

1. **Load the run:**

   ```bash
   python3 sysop/scripts/close_run.py load "<run-id>" "<default branch>"
   ```

2. **Run Step 1 in full**, attended. A branch Step 1a now classifies `dirty`, or that Step 1-pre does not bring across, is SKIP as Step 2a steps 0 and 0a say.

3. **Check what moved.** When the repository has an `origin`, fetch its default branch first, then check:

   ```bash
   git fetch origin "<default branch>"
   python3 sysop/scripts/close_run.py check "<run-id>" "<default branch>"
   ```

   Act now only on these lines:
   - `GONE <branch>: …` — drop the branch: its recorded state and questions no longer apply. Name it on Step 8's `Resumed:` row with the line's reason.
   - `RERUN <branch>: …` or `RERUN ALL: …` — set aside that branch's recorded questions, or every branch's; item 6 re-runs those branches and asks afresh.
   - `RERUN 3: …` — set aside the recorded Step 3c questions; item 6 re-runs Step 3c.

4. **Ask the recorded questions** not set aside in item 3, except a gone or SKIP branch's, from `<DIR>/questions.md` in one pass, at most four to an `AskUserQuestion` call, each with its options verbatim. Skip any question `<DIR>/answers.md` already answers. As each answer is given, append `## Q<n>` and the option chosen to `answers.md`. A question that closes without an answer takes its `If unanswered:` line: that is a park, never an answer.

5. **Apply each answer `answers.md` does not mark `applied`**, as its step prescribes: Step 2a step 3a's commit or copy, Step 2d's holds and waivers, and Step 3c's. Load Step 2a step 3a's arm and Step 3c's first (the next two paragraphs). Record a Step 3c "Already ran it manually" or "Unrunnable as specified" with Step 3c's recorder; "I'll drive the smoke" means drive it now. A drive's FAIL and could-not-finish asks, and an "Unrunnable as specified" answer's Continue-or-Stop ask, are asked live. After applying an answer, append `applied` under it.

   **When `<DIR>/questions.md` holds a Step 2a step 3a question item 3 did not set aside** (its `## Q<n> · <step> · …` heading names Step 2a step 3a), **load Step 2a step 3a's arm before you apply any answer**, once per close, answered or parked: its rules apply both. Run, from the main checkout's top level, with the close id `begin` printed:

   ```bash
   python3 sysop/scripts/close_arms.py exited "<close-id>" 2a-ignored-refs 1
   ```

   It prints `ARM: 2a-ignored-refs`. **Exit 2**: stop and show its stderr.

   **When it printed `ARM: 2a-ignored-refs`**, read `steps/2a-ignored-refs.md` in the skill directory you wrote in this file's first command, with your file tool, and run its first command. Where it says `<skill directory>`, write that directory. Then apply its rules to the answers and parks item 4 left. Do not ask a recorded question again: item 4 asked each one. A `REFUSED` re-ask is asked live.

   **When `<DIR>/questions.md` holds a Step 3c question item 3 did not set aside** (its `## Q<n> · <step> · …` heading names Step 3c), **load Step 3c's signal arm before you apply any answer**, once per close, answered or parked: its rules apply both. Run, from the main checkout's top level, with the close id `begin` printed:

   ```bash
   python3 sysop/scripts/close_arms.py exited "<close-id>" 3c-signals 1
   ```

   It prints `ARM: 3c-signals`. **Exit 2**: stop and show its stderr.

   **When it printed `ARM: 3c-signals`**, read `steps/3c-signals.md` in the skill directory you wrote in this file's first command, with your file tool, and run its first command. Where it says `<skill directory>`, write that directory. Then apply its rules to the answers and parks item 4 left. Do not ask its step 2 again: item 4 asked each recorded question.

   **Every answer given live, in this item or item 6, also goes in `answers.md`:** as a line `live: <the ask> → <the option>, applied` under the `## Q<n>` it followed, or under a new `## L<n> · <step> · <branch, or close>` heading. A question that closed without an answer is not written, so a later resume asks it again.

6. **Check again**, with item 3's command, and act on every line:
   - `GONE <branch>: …` — as in item 3.
   - `RERUN <branch>: …` — run Steps 2a to 2e for that branch, unless item 3 dropped it.
   - `RERUN ALL: …` — run Steps 2a to 2e for every branch item 3 did not drop.
   - `RERUN 2b: …` — run Step 2b for every target.
   - `RERUN 3: …` — run Steps 3 and 3c. When the line names local `<default branch>`, also run Step 2b for the unpushed-main group.
   - `NOTE: …` — report it on Step 8's `Resumed:` row.
   - `CURRENT` — nothing moved.
   - A branch the prepare SKIP'd as dirty or not brought across that item 2 no longer marks — run Steps 2a to 2e for it.
   - Unless the flags you gave `close_arms.py begin` hold `--unattended`, a branch the prepare SKIP'd on an `eligible` `OUT` line — run Steps 2a to 2e for it: an attended close does not read holds, and with `--agent`, *Under `--request-review`* item 2 selects it again.

   If anything re-ran from Step 2a or Step 2b, run Steps 3 and 3c too. Run Step 3 as well when the prepare left it not run. **A question a re-run raises that `answers.md` already answers** (the same step, branch and text, or for Step 3c the same `KEY:`) **takes that answer's outcome: never apply or drive it twice.** Ask any new question live. A re-run Step 2b's `VERDICT: BLOCKED` stops the close, as in an attended close. A branch that re-ran nothing keeps its recorded verdict, `NOTES:`, tally and report, changed only by the answers item 5 applied.

7. **Run Step 3b onward as an attended close**, on the recorded and re-run state: the approved set without held, rejected, BLOCKED, SKIP and gone branches; Step 2b's `NOTES:` for `4a-fix`; Step 3c's tally for Step 8. If a Step 3c question without a `BRANCH:` line is still unanswered, halt here. Immediately before Step 3b, run:

   ```bash
   python3 sysop/scripts/close_run.py consume "<run-id>" --restore-2b
   ```

   Leave out `--restore-2b` when Step 2b ran for any target during this resume.
