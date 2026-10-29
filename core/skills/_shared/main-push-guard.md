# Shared guard: safe commit + push to `main`

Any skill that **commits to, or pushes, `main` — or any branch a squash PR will write
`main` from — from the shared _primary_ worktree** MUST follow this guard. Git keeps **one
`HEAD` per worktree**, and Sysop runs concurrent loops (`/auto-build`'s parallel
batch, separate `/claim-task` sessions) against a `main` that — on an unprotected repo —
can also advance on its own. So a commit or push made without re-asserting the branch can
land on the wrong branch or clobber an autonomous merge.

Sites in Sysop that this guard covers:

| Site | Operation | Expected `HEAD` |
|---|---|---|
| `/review-close` Step 4a–4c (`direct` policy) | feature merges, batch close, doc-consolidation commits | the default branch |
| `/review-close` Step 4a–4c (`pr` policy, integration-branch shape) | the same commits, on the integration branch | `merge/review-close-<close-id>`, written out |
| `/review-close` Step 4a–4c (`pr` policy, PR-reuse shape) | the same commits, on the approved branch whose PR is being reused | the literal approved branch name |
| `/review-close` Step 4d (`direct` policy) | safe push to the default branch (Rule B) | the default branch |
| `/review-close` Step 4d (`pr` policy, integration-branch shape) | push the integration branch + open the PR | `merge/review-close-<close-id>`, written out |
| `/review-close` Step 4d (`pr` policy, PR-reuse shape) | push onto the existing PR's head branch | the literal approved branch name |
| `/claim-task` Step 4d | claim-flip commit (`open → in_progress`) | the default branch |
| `/auto-build` Step 5.4 | per-task claim-flip commit (in a loop) | the default branch |
| `/release` Step 2 + Step 8.3 | release preconditions and the pre-tag re-assert | the default branch (or a `CLAUDE.md`-named release branch) |
| `/document-work` Step 5 | `git push -u origin HEAD` (a feature branch) | **not** the default branch |

It closes two distinct races:

1. **Local HEAD-hijack.** A concurrent local actor (another Sysop loop, a manual
   `git checkout -b`) moves `HEAD` off the branch you expect mid-flow, so your commits
   land on the wrong branch — or a stale tip gets pushed. (Failure shape: an incomplete
   `main` ships, missing a load-bearing fix, caught only by the wrong tip SHA in the push
   summary.)
2. **Remote autonomous writer.** On a project whose `main` is unprotected and uses
   GitHub-native auto-merge (e.g. Dependabot patch/minor PRs landing whenever their
   required checks pass — Sysop's own `/pr-dependabot` standardizes this flow),
   `origin/main` advances at unpredictable times. A direct `git push origin main` can
   collide with a merge that landed since your last fetch.

## Rule A — assert the branch before EVERY commit and EVERY push

**Substitute `<expected branch>` with the branch this step intends to write** — see the
table above — before running it. It is a placeholder, not a variable
to set: nothing survives from one fenced block to the next (`WORKFLOW.md` § 8.2a
*Persistence boundary*), so a variable here would be empty and the halt message would name
no branch. So this is the template they copy from, never a snippet to run as-is.

**When the expected branch is the repository's DEFAULT branch, resolve it — never write
the literal `main`**. Every caller here used to, and on a `master`-default
consumer each one halted at a branch the repository does not have: `/claim-task` Step 4d
stopped with *"HEAD is not main"* on a repo whose HEAD was `master` and correct. Get the
name first, in its own command, and substitute what it prints:

```bash
bash sysop/scripts/default_branch.sh
```

It prints one bare name (`main`, `master`, `develop`, …) and exits 0, or prints nothing,
explains itself on stderr and exits 1 — in which case stop, because every branch
comparison the step is about to make is against that name. **Run it bare and read the
output; do not capture it into a shell variable.** Claude Code's permission matcher does
not match an allow rule past a variable assignment, so `DEFAULT_BRANCH="$(…)"` binds no
rule and routes to the auto-mode classifier, while the bare command binds
`Bash(bash sysop/scripts/default_branch.sh)` exactly. This is the same read-the-output
idiom `/claim-task` already uses for `batch_work.sh`'s `│  Branch:` / `│  Path:`
summary box.

Which callers need it: `/claim-task` Step 4d and its three resume arms, `/auto-build`
Step 5.4, `/release` (Step 2's precondition *and* Step 8.3's re-assert — the first one
gates the second, so fixing only the later one leaves the skill halted), and
`/document-work` Step 5 in the inverted form below. All four **compare against** the
default branch; three of them write it, and `/document-work` asserts it is *not* on it. `/review-close` asserts the merge target Step 4-pre recorded, written
out: the default branch under `direct` policy, `merge/review-close-<close-id>` under the
integration-branch shape, and the approved branch name under PR reuse; only the first is a
default-branch site.

```bash
python3 sysop/scripts/git_check.py head-is "<expected branch>" && <the write it guards>
```

**Chain the write after the check with `&&`, in the same call.** The check is the whole
assert: it prints one line and exits 0 only when `HEAD` is `refs/heads/<expected branch>`, so
`&&` runs the commit or push only then, and a check run as a call of its own leaves the window
between the two calls open. It compares the full ref name, so a tag or a remote ref spelled
like the branch cannot pass for it. Exit 1 means `HEAD` is elsewhere or detached; 2,
that git could not be read; 3, that an operand is still a placeholder. On any of them the write
does not run: stop. **This shape is also what makes the guard run under `dontAsk`**:
the form it replaces, `test "$(git …)" = "<branch>" || { echo …; exit 1; }`, binds no allow
rule, since `test` binds none and an `exit` or a `{ …; }` group is denied wherever it sits,
while `Bash(python3 sysop/scripts/git_check.py:*)` and the write's own rule each bind.

`/document-work` Step 5 is the one inverted case — it pushes a _feature_ branch, never the
default branch, so it asserts `HEAD` is **not** that branch (a detached `HEAD` fails it too):

```bash
python3 sysop/scripts/git_check.py head-is-not "<default branch>" && git push -u origin HEAD
```

**When the expected branch is dynamic** and no step carries its name as a literal, do **not**
recover the expected value from current `HEAD` — comparing `HEAD`'s name with itself is a
tautology that silently disables the guard. Assert against a fixed *pattern* instead, which stays
correct without remembering the exact name. (`/review-close` did this for its integration branch
until a later build named that branch from the close id, a literal every later step carries.)

```bash
python3 sysop/scripts/git_check.py head-matches "merge/review-close-*" && <the write it guards>
```

**When there is no pattern to match** — `/review-close`'s `pr`-policy **PR-reuse shape**, where
the merge target is an ordinary feature branch whose name follows no convention — assert against
the **literal** branch name with `head-is`, written out from wherever the decision was made
(there, the Step 2a approval verdict). The requirement is not "use a pattern"; it is that the
expected value must originate somewhere **other than `HEAD`**. A literal from an upstream
decision satisfies that; a value re-read from `HEAD` never does, whatever syntax surrounds it.

If the assert fails: do NOT commit/push. Reconcile via `git reflog` — cherry-pick your
stranded commits onto the expected branch, reset the hijack branch to only its own commit,
then resume. Never bundle another actor's un-reviewed commits into your push.

## Rule B — safe direct push to `main` (`direct` merge policy only)

Applies to `/review-close` Step 4d under the **`direct`** merge policy
(`<project>/CLAUDE.md § Merge policy`, the default). This is the canonical safe shape for
the supported `direct` path — not a fallback. Under the **`pr`** policy `main` is never
pushed directly: the integration-PR flow (Step 4d `pr`) replaces this whole sequence, and
on a push-protected `main` a direct push is rejected outright — which is itself the signal
to switch that project to `pr` policy.

**Resolve `<default branch>` first and write the name into every occurrence below**
(`bash sysop/scripts/default_branch.sh`, per Rule A). Run each numbered command as its own
call, as written. **A non-zero exit the step does not route is a STOP**; a push rejected because
`origin/<default branch>` moved again (`fetch first`) means re-run Rule B from step 1. Each write
is chained after a `git_check.py` check with `&&` (Rule A), and steps 2 and 4 read the default
branch's own ref, not `HEAD`, so the commit pushed is that branch's tip even if another actor
moved `HEAD` and back between calls. (A `test`, an `if`, a `$(…)` capture and a
`|| { …; exit 1; }` tail are each denied under `dontAsk`.)

1. On the default branch (Rule A), refresh the remote:

   ```bash
   python3 sysop/scripts/git_check.py head-is "<default branch>" && git fetch origin <default branch>
   ```

2. Has `origin/<default branch>` advanced (an autonomous auto-merge landed)?

   ```bash
   python3 sysop/scripts/git_check.py ancestor "refs/remotes/origin/<default branch>" "refs/heads/<default branch>"
   ```

   **Exit 0**: it has not; go to 4. **Exit 1**: it has; go to 3. **Exit 2 or 3**: stop.

3. Integrate it FIRST — by MERGE, never by rebase. A rebase rewrites every commit Step 4a put
   on this branch: a published branch's PR is then never marked merged, and a local-only
   branch's tip stops being an ancestor, so Step 6's `git branch -d` refuses. A merge commits,
   so the project's commit-msg and pre-merge-commit hooks fire here: put every trailer the
   project requires in the ONE final -m, one per line, or drop that -m.

   ```bash
   python3 sysop/scripts/git_check.py head-is "<default branch>" && git merge --no-edit -m "merge origin/<default branch> (autonomous advance)" -m "<trailers the project's commit convention requires, one per line>" origin/<default branch>
   ```

   **A non-zero exit: STOP.** Run `git ls-files -u`: paths it lists are a conflict with an
   auto-merged commit; none means a hook or git refused the merge (read its output). Then run
   `git merge --abort`, which also errors harmlessly when no merge was left in progress, and
   reconcile manually. **On exit 0, the base changed → RE-RUN review-close 4a-post** (the
   merged-tree gate: the project's § Pre-merge verification commands, run on the merge target)
   against the new base before pushing. NOT Step 3 — Step 3's tree is the default branch before
   any merge, which is not the tree this merge moved.

4. Print the exact verified tip, the default branch's own ref, and write it out as `<SHA>` below:

   ```bash
   git rev-parse "refs/heads/<default branch>"
   ```

5. Push that commit — NEVER `--force` (Rule C):

   ```bash
   python3 sysop/scripts/git_check.py head-is "<default branch>" && git push origin "<SHA>:<default branch>"
   ```

6. Confirm your push landed — assert CONTAINMENT, not equality: another autonomous auto-merge
   can land on the remote between your push and this fetch (the very race Rule B targets),
   which would fail a strict-equality check even though your push landed.

   ```bash
   git fetch origin <default branch> && python3 sysop/scripts/git_check.py ancestor "<SHA>" "refs/remotes/origin/<default branch>"
   ```

   **A non-zero exit**: the fetch failed, or the pushed SHA is not on `origin/<default branch>`
   (the check's `STOP:` line says which); investigate before continuing.

## Rule C — NEVER force-push `main` (or any branch a squash PR will write it from)

A non-fast-forward rejection on `main` means an **auto-merged commit** is on `origin/main`
that your local `main` lacks. `git push --force` / `--force-with-lease` would silently
delete it. Always fetch + merge the advance in + re-push (Rule B) instead. The same prohibition covers
the `pr`-policy merge target, whether that is a throwaway integration branch or a reused
PR head branch — it is the PR's source of truth; never force it.
