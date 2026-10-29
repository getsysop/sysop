   - **First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

      ```bash
      python3 sysop/scripts/close_arms.py loaded "<close-id>" 2a-ignored-refs 728e4449b3e10d90 "<skill directory>"
      ```

      It prints `LOADED: 2a-ignored-refs`. **Exit 2**: stop and show its stderr.

   **Exit 1**: ask about each `IGNORED-REF:` line with `AskUserQuestion`, at most four to a call, showing the line. Options:
   - `Commit it to the branch`: only when the workspace is a linked worktree. Run the block below with `commit`. When the branch's pending doc carries `branch_tip:`, the new commit makes it stale, so Step 3b's collect exits 6 and SKIPs the branch this run; Step 8 says to re-run `/document-work` on it and then the close.
   - `Keep it ignored: copy it to the main checkout`: run the block below with `copy`. The branch merges without the file.
   - `Not needed: merge without it`.
   - `Reject the branch`: the verdict is **reject**, with the line as the reason. For a `--clone` workspace, add: commit it in the clone with `git add -f` (and, when its pending doc carries `branch_tip:`, re-run `/document-work` there), then re-run the close; Step 1-pre brings the commit across. For a `--branch` workspace: check out `<branch>` in the main checkout, `git add -f` and commit it, check out the default branch again, then re-run the close.

   Mark `Commit it to the branch` (Recommended) when it is offered and a component of the path contains `fixture`, `testdata` or `test_data`, or is `__snapshots__`, in any case; for such a path where `Commit` is not offered, mark `Reject the branch` (Recommended); otherwise mark `Keep it ignored` (Recommended).

   **A line left unanswered makes the verdict SKIP — ignored file unanswered**, whatever the workspace's shape: not merged, and its worktree, lock and branch left as step 0's SKIP leaves them. A line is unanswered when the result says the human may be away, or when the block below exits non-zero; on `REFUSED` (exit 5), ask that line again with only `Not needed` and `Reject`.

   **Under `--dry-run`, do not run the block below:** report each answer and the commit or copy it would make.

   ```bash
   python3 sysop/scripts/feature_branch.py keep-ignored "<workspace>" "<path>" "<commit or copy>"
   ```

   Looping over the paths? Name the loop variable `entry`, never `path`: in zsh `path` is tied to `$PATH`.

   **Exit 3, or any other exit**, from the check: it did not run. Ask once, showing its error: `Hold the branch` (Recommended) or `Merge without the check`. `Hold`, or an away result, makes the verdict SKIP as above. Print the error under Step 8's `Ignored references:`.
