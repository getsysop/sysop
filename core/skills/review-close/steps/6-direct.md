**First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

```bash
python3 sysop/scripts/close_arms.py loaded "<close-id>" 6-direct faee13c46ed72faf "<skill directory>"
```

It prints `LOADED: 6-direct`. **Exit 2**: stop and show its stderr.

**`direct` policy — per-branch cleanup.** For each merged feature branch (worktrees already removed in Step 3b), one Step 4a recorded `merged — already in <ref>` included:
0. **A branch Step 4a took with the `--no-ff` published arm:** `gh pr view <branch> --json number,state --jq '"\(.number) \(.state)"'`. `MERGED` → continue. `OPEN` → GitHub has not registered Step 4d's push yet; wait and re-run before deleting, because deleting first closes the PR unmerged. `CLOSED` before this close ran, or no PR at all → not this close's doing; continue. Put any branch left `OPEN` on Step 8's `Superseded PRs:` row.
1. Delete the **remote** branch first: `git push origin --delete refs/heads/<branch>` (if it exists remotely).
2. Delete the **local** branch: `git branch -d <branch>`.

**Why this order matters (BeanRider ISSUE-0021).** Step 4a rebases the feature branch onto main, which rewrites its SHA. The local branch's tracked upstream (`refs/remotes/origin/<branch>`) still points at the *pre*-rebase commit, so `git branch -d` refuses with `not fully merged to refs/remotes/origin/<branch>, even though it is merged to HEAD` — git's safe-delete check compares against the upstream ref, not against `main`. Deleting the remote first removes the upstream pointer, so the subsequent `-d` falls back to checking against `HEAD` and succeeds. Do **not** use `-D` (force-delete) — the safe-delete refusal is correct behavior given the upstream check; the fix is to drop the upstream first, not to bypass the check.

**If `git push origin --delete refs/heads/<branch>` is silently denied** (BeanRider ISSUE-0033, classifier hard-codes destructive-flag protection on `--delete`/`--force` regardless of allow-rule glob), the `PermissionDenied` hook surfaces the `! git push origin --delete refs/heads/<branch>` escape command — with the venv-prefix variant when a `.venv/` directory is present. Follow the hook's guidance and relay to the user. The subsequent `git branch -d <branch>` runs in-band without classifier interference (local-only, no remote contact). Do **NOT** use `AskUserQuestion`.
