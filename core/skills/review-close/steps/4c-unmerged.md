   - **First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

      ```bash
      python3 sysop/scripts/close_arms.py loaded "<close-id>" 4c-unmerged f14a854c538636e4 "<skill directory>"
      ```

      It prints `LOADED: 4c-unmerged`. **Exit 2**: stop and show its stderr.

   **On a non-zero count, ask the recorded PR heads before the `git cherry` fallback** — a branch a previous `pr` close squash-merged scores non-zero on both. Resolve the ref first, as the fallback below says, then:

   ```bash
   git for-each-ref --contains "refs/heads/<branch from frontmatter>" --format='%(refname)' refs/sysop/merged-pr-heads/
   ```

   A printed `refs/sysop/merged-pr-heads/<N>` means **merged** (by PR #<N>): route the doc, unless Step 4a recorded this branch 4a-SKIP, whose doc stays held. Nothing printed: go on to the fallback.

   > **It is an ancestry test, so a CHERRY-PICK breaks it.** Cherry-picking rewrites commits, so the tip is not an ancestor even when the content is fully applied. A rebase + `merge --ff-only` and a `--no-ff` merge both score `0`.
   >
   > **A `branch: <default branch>` pending doc scores `0` here and that is correct** — Step 4-pre cuts the integration branch from local `<default branch>`, so its tip is a real ancestor of the merge target. It used to score non-zero on every `pr` close; `REFERENCE.md` § *Step 4-pre — provenance* has why. **Keep the fallback below regardless** — it covers a cherry-pick anywhere else in the flow, and any improvisation that rewrites commits.
   >
   > **So do not trust a non-zero count on its own. Fall back before you skip — but resolve the ref first.** The stop-and-ask below (*"If `refs/heads/<branch>` does not resolve, stop and ask"*) governs this fallback too, and it is written *after* it, so apply it *before*: `git rev-parse --verify "refs/heads/<branch from frontmatter>^{commit}"` must succeed. If it does not, go straight to that stop. **A `fatal: unknown commit` leaves the pipeline printing `0`**, and `0` is this test's *merged* answer — so an unresolvable branch would read as "content is in the merge target" and get its doc routed, its task flipped to `done` and its lock dropped, which is the precise loss this filter exists to prevent.
   >
   > ```bash
   > git rev-parse --verify "refs/heads/<branch from frontmatter>^{commit}" >/dev/null || echo "ref does not resolve — go to the stop-and-ask below, do NOT read the count"
   > git cherry HEAD "refs/heads/<branch from frontmatter>" | grep '^+' | wc -l
   > ```
   >
   > **Count with `grep '^+' | wc -l`, never with `grep`'s own `-c` flag.** That flag exits **1** when the count is zero — and zero is the *pass* value here — so the prescribed form would return a failing status on the good outcome, abort under `set -e`, and never fire the right-hand side of an `&&` chain.
   >
   > `git cherry` compares **patch-ids** rather than ancestry, so it sees through a cherry-pick: `0` unapplied commits means the content is in the merge target however it got there. Treat that as **ask, not skip** — report the branch and let the human decide, because this is the one case where the two tests disagree. **State its limit rather than trusting it blindly:** a cherry-pick that required conflict resolution changes the patch, so `git cherry` prints `+` for a commit that *is* applied. Neither test is authoritative alone; a branch that fails both is genuinely unmerged, and a branch that passes either is not to be skipped silently.
   > See `REFERENCE.md` § *Step 4c — provenance*.
