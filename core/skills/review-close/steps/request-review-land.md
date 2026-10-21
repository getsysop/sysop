**First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

```bash
python3 sysop/scripts/close_arms.py loaded "<close-id>" request-review-land 123f65f8980594aa "<skill directory>"
```

It prints `LOADED: request-review-land`. **Exit 2**: stop and show its stderr.

Both need `Bash(python3 sysop/scripts/close_run.py:*)` in the allow-list the guard above read, unless `--skip-permission-guard` skipped the guard. If it is missing, stop. **On any non-zero exit from `close_run.py` not named below, stop and show its stderr.**

The close is split at Step 4d. Half A (`--request-review`) opens the PR, asks the reviewer `## Second reader` names in the project's `CLAUDE.md` for a review, records what half B needs, and stops. Half B (`--land`) reads that reviewer's verdict on the recorded head and merges or parks.

### Under `--request-review`

1. **Before Step 1**, confirm the second reader parses:

   ```bash
   python3 sysop/scripts/close_run.py reader
   ```

   With `--agent <name>`, confirm the unattended class parses too, and report each `WARN:` line it prints:

   ```bash
   python3 sysop/scripts/close_run.py class
   ```

2. **With `--agent <name>`, select after Step 1** (under `--resume`, after its item 2). Name every branch Step 2a will consider (agent worktree branches excluded), each quoted:

   ```bash
   python3 sysop/scripts/close_run.py eligible "<default branch>" "<name>" "<branch>" "<branch>"
   ```

   Under `--unattended`, put `--held` after `"<name>"`; a `NOTE:` line then may also say a hold is cleared, which you report. Each `OUT` branch's verdict is **SKIP — outside the unattended class**, with its line as the reason, for the rest of the run, a re-run of Steps 2a to 2e included. Treat it as Step 2a step 0a's SKIP: not reviewed or merged, and left as it is, excluded from Steps 3b, 4 and 6. If no branch is `IN`, stop: there is nothing to land unattended. Report any `NOTE:` line: those commits of local `<default branch>` ride the PR, outside the class.

3. **Run the close as usual through Step 4c** (or the `--resume` path through Step 4c), with one change: run Step 4c item 4's `tasks/index.yml` script with `--keep-locks` before its ids. It prints `LOCKS_KEPT:` beside the other rows; those locks stay until half B's merge. **If half A stops anywhere after this and before `hand-off` prints `RUN:`**, report the `LOCKS_KEPT:` ids with the stop: they stay on disk until the PR merges, and are removed by hand (`sysop/runtime/locks/<ID>.lock`) once it has.

4. **At Step 4d**, run the filing commit and the `pr` policy's Step 1 for your shape as written (push, print local `<default branch>`'s SHA, and `gh pr create` under the integration-branch shape). Do not run its Step 2. Take the PR number from `gh pr create`'s URL, or from the Step 4-pre probe under the PR-reuse shape, and the SHA from line 2b, then:

   ```bash
   python3 sysop/scripts/close_run.py hand-off "<default branch>" "<branch you pushed>" "<PR>" "<SHA 2b printed>"
   ```

   Add `--keep-branch` as a fifth argument when the PR-reuse note on a held doc's branch would drop `--delete-branch`. With `--agent <name>`, add `--agent "<name>"` last. **Exit 2** means nothing was recorded or requested: fix what its reason names and run `hand-off` again, or report the reason and the PR URL and stop. **Exit 1 after a `RUN:` line** means the request comment failed: go on with items 5 and 6, report it, and once `gh` works run `python3 sysop/scripts/close_run.py re-request "<run-id>" "<default branch>"`.

5. **Write `<DIR>/report.md`** with your file tool: a `## Step 6` heading with one line each for `Merged:`, `Held-doc branches:`, `SKIP:`, `4a-SKIP:` (each followed by branch names, or `(none)`) and `Kept locks:` (the `LOCKS_KEPT:` ids, or `(none)`); then a `## Step 8` heading with every Step 8 row this close has produced so far, including each `## After merge` section Step 2d carried. Then:

   ```bash
   python3 sysop/scripts/close_run.py seal "<run-id>"
   ```

   Exit 1 names what `report.md` lacks: add it and run `seal` again.

6. **Return the main checkout to `<default branch>`**: `git checkout <default branch>`. Do not run Steps 5 or 6. Run Step 7. Step 8 reports the PR URL, the run id, the `LAND:` line, and the rows in `report.md`, with `Locks cleaned:` reading `kept until --land: <ids>` and `Pushed:` and `Squash provenance:` reading `at --land`.

### Under `--resume <run-id> --request-review --agent <name> --unattended` (`Q-664`)

No human is present. Never use `AskUserQuestion` and never relay a `!` command: report each stop in Step 8 and end the run. Run the resume (*Under `--resume <run-id>`*, in `steps/prepare-resume.md`) and half A (*Under `--request-review`* above) as written, with these changes:

1. **Resume item 4 asks nothing.** Every question item 4 would ask takes its `If unanswered:` line. For each one that names a branch, hold the branch:

   ```bash
   python3 sysop/scripts/close_run.py hold "<run-id>" "<branch>" "unanswered: Q<n> (<step>)"
   ```

   A Step 3c question with no `BRANCH:` line parks the close early (item 4).

2. **Resume item 6.** A question a re-run raises that `answers.md` does not answer takes the park the prepare gives its step (*Under `--prepare`* item 2), with a hold as in item 1. A re-run Step 2b's `VERDICT: BLOCKED` on a branch holds the branch (`"VERDICT: BLOCKED: <first violation>"`) and leaves it out of the rest of the close; on the unpushed-main group it parks the close early. Step 3, when the prepare left it not run, parks the close early.

3. **Step 2b.** A reviewer that returns no `VERDICT:` line parks the close early, with its last output as the reason.

4. **Every other stop parks the close.** Wherever Steps 1 to 4d's Step 1, the items above, or Steps 7 and 8 say to stop, halt, ask or relay, and the step gives no outcome that needs no human:
   - **Before Step 4-pre, an early park.** Write the step and the reason to `<DIR>/halted.md`, report them on Step 8, and end the run. Leave locks, worktrees and branches as they are. Before `load` has printed `DIR:`, only report and end.
   - **From Step 4-pre on, a durable park.** Record it, then report it on Step 8 and end the run, leaving everything in place:

     ```bash
     python3 sysop/scripts/close_run.py stop "<run-id>" "<step>" "<reason>. Recovery: <the step's own>" --locks-kept <id> <id>
     ```

     Leave out `--locks-kept` and its ids until Step 4c has printed `LOCKS_KEPT:` with ids, and on `LOCKS_KEPT: (none)`. The recovery is the step's own: finish on the integration branch where one exists, as Step 4d-1's stuck-PR recovery does; for Step 4-pre's missing local default branch, recreate it and re-run, as that step says.
   - **Also durable, though before Step 4-pre:** Step 3b's collect exit 5, the rollback's exit 4, and a rollback that leaves main still holding a doc claiming the branch. The recovery is that exit's row in its exit table.
   - A relay's park names the denied command, written out, in its reason; never retype it to run it.
   - When `stop` itself fails, report `STOP NOT RECORDED`, its stderr, the step and the reason on Step 8, and end the run.

5. **A `close_run.py` exit the text gives no instruction for, or whose instruction is to stop,** is a stop by item 4's timing: before Step 2a it ends the run, and after the push it parks the close durably, `hand-off`'s exit 2 included. Where the instruction is to fix something and run the command again, do that once; if it fails again, it is a stop.

6. **A `status:` conflict in Step 4a** (each of the three places Step 4a says to report both values and STOP) 4a-SKIPs that branch, with both values as the reason.

7. **Step 7** appends nothing to `SYSOP_ISSUES.md` and skips the `[good]` prompt: Step 8's `Friction:` row lists the friction itself.

Name each held branch on Step 8 with what clears it: a new head, an attended close, which does not read holds and so asks its question, or, once its cause is fixed outside the branch, `python3 sysop/scripts/close_run.py unhold "<branch>" "<what was fixed>"`.

### Under `--land <run-id>`

Run the default-branch resolve and the permission guard above first. Do not run Steps 1 to 4c, or Step 4d before its Step 2: half A ran them. Then:

1. **Read the verdict:**

   ```bash
   python3 sysop/scripts/close_run.py land-check "<run-id>" "<default branch>"
   ```

   It prints `PR:`, `BRANCH:`, `SHAPE:`, `HEAD:`, `PUSHED FROM:`, `KEEP BRANCH:`, `REPORT:`, one `READER:` line per thing it read, and a `VERDICT:`.
   - **Exit 5, `VERDICT: WAIT`** — the reviewer has not answered and the timeout has not passed. Report the `READER:` lines and stop; run `--land` again later.
   - **Exit 4, `VERDICT: PARK`** — nothing merges. Report the `READER:` lines and stop, leaving the PR, branches and locks in place. To go on, `git checkout "<branch>"` with `BRANCH:`'s name; if a `READER:` line says the PR's head moved, first bring that push in with `git fetch origin "<branch>"` and `git merge --ff-only "origin/<branch>"`. Commit any fix there, run `CLAUDE.md`'s `## Pre-merge verification` commands on it as `4a-post` does, push with `git push origin "<branch>"`, then `git checkout <default branch>` and run `python3 sysop/scripts/close_run.py re-request "<run-id>" "<default branch>"`; run `--land` again later. To give up instead, close the PR on GitHub and run `python3 sysop/scripts/close_run.py abandon "<run-id>"`, then report its `BRANCH:` and `LOCKS_KEPT:` lines.
   - **Exit 0, `VERDICT: ALREADY MERGED`** — skip to Step 4d's command 6.
   - **Exit 0, `VERDICT: MERGE`** — go on.

2. **Merge, with Step 4d's Step 2 commands**, substituting `PR:`'s number for `"<PR>"` and never re-deriving it from HEAD: command 4, command 4b (and its note on a `0`), then command 5: its `gh pr view` line as written, and its merge as `gh pr merge "<PR>" --squash --delete-branch --match-head-commit "<HEAD>"`, with `HEAD:`'s SHA and without `--delete-branch` when `KEEP BRANCH: yes`. Then command 6. A state other than `MERGED` is Step 4d-1's stuck PR; recover on `BRANCH:` as item 1's park says, not by re-running `/review-close`.

3. **On `MERGED`**, record the head with Step 4d's record command, then:

   ```bash
   python3 sysop/scripts/close_run.py landed "<run-id>"
   ```

   It removes the kept locks and the `AWAITING` marker, and prints `LOCKS_REMOVED:` and `LOCKS_ALREADY_ABSENT:` for Step 8's `Locks cleaned:` row.

4. **Run Steps 5, 6, 7 and 8** from `report.md`: Step 6 uses its lists and `PUSHED FROM:` as the SHA Step 4d printed, and when `SHAPE:` is the integration branch deletes `BRANCH:` by that name. Step 8 is `report.md`'s rows plus this run's.

### Under `--land <run-id> --unattended --agent <name>`

No human is present. Never use `AskUserQuestion` and never relay a `!` command: report each stop in Step 8 and end the run. Run the default-branch resolve and the permission guard above first. Do not run Steps 1 to 4c, or Step 4d before its Step 2: half A ran them. Then:

1. **Check, and turn on auto-merge**, after bringing in the default branch's tip:

   ```bash
   git fetch origin "<default branch>"
   python3 sysop/scripts/close_run.py land-check "<run-id>" "<default branch>" --unattended "<name>"
   ```

   It prints the attended land's `PR:` to `REPORT:` lines, one `READER:` line per thing it read, and a `VERDICT:`. It checks the PR, the hand-off's locks and held docs, Step 6's two local conditions, the server setup with the token `gh` holds and the class's `attested:` date; once every check on the PR has passed, and the gate app's own `sysop/close-gate` run on `HEAD:` with them, it turns on auto-merge at `HEAD:`, and GitHub merges under its own rules.
   - **Exit 5, `VERDICT: WAIT` or `VERDICT: ARMED`** — nothing to do yet. Report the `READER:` lines and stop; the same command, run later, goes on.
   - **Exit 4, `VERDICT: PARK`** — nothing merges, and the land's own auto-merge is off unless a `READER:` line says it could not be turned off. Report the `READER:` lines and stop. The park lasts until a human clears it: do not fix the branch, `re-request`, `unpark` or `abandon`.
   - **Exit 0, `VERDICT: ALREADY MERGED`** — go on. A `MERGED ELSEWHERE:` line means GitHub merged a head the land never checked: put it on Step 8's `Remaining:` row.

2. **Confirm and record the merge:** Step 4d's command 6 with `PR:`'s number for `"<PR>"`, then on `MERGED` Step 4d's record command, then:

   ```bash
   python3 sysop/scripts/close_run.py landed "<run-id>"
   ```

3. **Delete the remote branch** unless `KEEP BRANCH: yes`: `git push origin --delete "<BRANCH>"`, with `BRANCH:`'s name written out. Auto-merge never deletes it. `remote ref does not exist` means the repository deleted it: that is done. If the command fails otherwise or is denied, record the branch and the error for Step 8's `Remaining:` row.

4. **Run Steps 6, 7 and 8** from `report.md`, as item 4 of the attended land says, with three changes. Do not run Step 5: Step 8's `Staging:` row reads `not run: unattended`. If Step 6 finds the tracked tree `DIRTY` or a commit made after the push, run none of Step 6 and list its commands on Step 8's `Remaining:` row as owed. Step 7 appends nothing to `SYSOP_ISSUES.md` and skips the `[good]` prompt: Step 8's `Friction:` row lists the friction itself.
