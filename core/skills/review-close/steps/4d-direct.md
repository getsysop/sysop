**First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

```bash
python3 sysop/scripts/close_arms.py loaded "<close-id>" 4d-direct f1f225cea068439c "<skill directory>"
```

It prints `LOADED: 4d-direct`. **Exit 2**: stop and show its stderr.

Once all merges and doc consolidation are complete (or if there were only unpushed main commits), push `main` via the **`_shared/main-push-guard.md` Rule B safe-push sequence** rather than a bare push — assert-on-`main` (Rule A) → `git fetch origin <default branch>` → if `origin/<default branch>` advanced, the closed-task check (`git_check.py closed-tasks`) and then merge-first (an autonomous auto-merge, e.g. Dependabot) → push the exact verified tip (`git push origin "<SHA>:<default branch>"`, **never `--force`** per Rule C) → confirm the SHA you pushed is on `origin/<default branch>`. The merge-first step also re-runs **`4a-post`** — the merged-tree gate — against the new base; not Step 3, whose tree is `main` and is not the thing that moved. The bare `git push origin <default branch>` is safe only when `origin/<default branch>` has not moved; Rule B makes that check explicit instead of assumed.

Then confirm the push succeeded.

If the push is **rejected because `main` is protected** (`! [remote rejected] main -> main (protected branch hook declined)`, a required status check, or `enforce_admins`), the project's `main` requires the PR flow: set `<project>/CLAUDE.md`'s `## Merge policy` to `pr` and re-run `/review-close`. This is the exact failure the `pr` policy exists to handle — do not try to force the push.

**If push is silently denied** (auto-mode classifier rejects pushing to a protected branch), the `PermissionDenied` hook surfaces an `!`-prefixed escape command naming **the branch it matched** — one of the two names it hard-codes, and nothing else — and a venv-prefix variant of the same when the consumer's repo has a `.venv/` directory. Relay what the hook printed; do not retype it from memory or substitute a resolved branch name into it. Follow the hook's guidance and relay to the user. The canonical consumer-side fix is unchanged: the project's `sysop/scripts/hooks/pre-push` should prepend `${REPO_ROOT}/.venv/bin` to its `PATH` at the top of the hook (see WORKFLOW.md § 6.1 venv-aware-invocation paragraph). Do **NOT** use `AskUserQuestion` — empirically the classifier does not honor its answer for protected-branch pushes and you'll burn a turn on a dead-end handshake. See WORKFLOW.md § 8.2a for the full rationale.
