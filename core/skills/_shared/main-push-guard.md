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
| `/review-close` Step 4a–4c (`pr` policy, integration-branch shape) | the same commits, on the integration branch | `$INTEGRATION_BRANCH` |
| `/review-close` Step 4a–4c (`pr` policy, PR-reuse shape) | the same commits, on the approved branch whose PR is being reused | the literal approved branch name |
| `/review-close` Step 4d (`direct` policy) | safe push to the default branch (Rule B) | the default branch |
| `/review-close` Step 4d (`pr` policy, integration-branch shape) | push the integration branch + open the PR | `$INTEGRATION_BRANCH` |
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
table above — at both occurrences, before running it. It is a placeholder, not a variable
to set: nothing survives from one fenced block to the next (`WORKFLOW.md` § 8.2a
*Persistence boundary*), so a variable here would be empty and the halt message would name
no branch. So this is the template they copy from, never a snippet to run as-is.

**When the expected branch is the repository's DEFAULT branch, resolve it — never write
the literal `main`** (`Q-377`). Every caller here used to, and on a `master`-default
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
default branch; three of them write it, and `/document-work` asserts it is *not* on it. `/review-close` writes in three forms: the default branch under
`direct` policy, the fixed `merge/review-close-*` pattern under the integration-branch
shape, and the written-out approved branch name under PR reuse; only the first is a
default-branch site.

```bash
test "$(git rev-parse --abbrev-ref HEAD)" = "<expected branch>" || {
  echo "HEAD is not <expected branch> (a concurrent actor moved it) — STOP."; exit 1; }
```

`/document-work` Step 5 is the one inverted case — it pushes a _feature_ branch, never the
default branch, so it asserts `HEAD` is **not** that branch:

```bash
test "$(git rev-parse --abbrev-ref HEAD)" != "<default branch>" || {
  echo "HEAD is <default branch> — Step 5 pushes a feature branch; /review-close owns it. STOP."; exit 1; }
```

**When the expected branch is dynamic** (the `/review-close` `pr`-policy integration branch,
whose name embeds a per-run id), do **not** recover the expected value from current `HEAD` —
`test "$(git rev-parse --abbrev-ref HEAD)" = "$(git rev-parse --abbrev-ref HEAD)"` is a
tautology that silently disables the guard. Assert against the fixed *pattern* instead, which
stays correct without remembering the exact name:

```bash
case "$(git rev-parse --abbrev-ref HEAD)" in
  merge/review-close-*) : ;;  # on an integration branch — ok
  *) echo "HEAD is not a review-close integration branch — STOP."; exit 1 ;;
esac
```

**When there is no pattern to match** — `/review-close`'s `pr`-policy **PR-reuse shape**, where
the merge target is an ordinary feature branch whose name follows no convention — assert against
the **literal** branch name, written out from wherever the decision was made (there, the Step 2a
approval verdict). The requirement is not "use a pattern"; it is that the expected value must
originate somewhere **other than `HEAD`**. A literal from an upstream decision satisfies that; a
value re-read from `HEAD` never does, whatever syntax surrounds it.

If the assert fails: do NOT commit/push. Reconcile via `git reflog` — cherry-pick your
stranded commits onto the expected branch, reset the hijack branch to only its own commit,
then resume. Never bundle another actor's un-reviewed commits into your push.

## Rule B — safe direct push to `main` (`direct` merge policy only)

Applies to `/review-close` Step 4d under the **`direct`** merge policy
(`<project>/CLAUDE.md § Merge policy`, the default). This is the canonical safe shape for
the supported `direct` path — not a fallback. Under the **`pr`** policy `main` is never
pushed directly: the integration-PR flow (Step 4d `pr`) replaces this whole sequence, and
on a push-protected `main` a direct push is rejected outright — which is itself the signal
to switch that project to `pr` policy. Run the whole sequence as a single shell block: it is
one atomic call, so the step-1 assert covers the push at step 4 (HEAD cannot be hijacked
between them within one synchronous block).

**Resolve `<default branch>` first and write the name into every occurrence below**
(`bash sysop/scripts/default_branch.sh`, per Rule A). Substituting it is what keeps the
sequence atomic: resolving it *inside* the block would mean a variable assignment, which
binds no allow rule, and step 4 would then push to a refspec whose destination half is
empty — which git rejects, loudly, but only after steps 1–3 have already run.

```bash
# 1. on the default branch? (Rule A)
test "$(git rev-parse --abbrev-ref HEAD)" = "<default branch>" || { echo "not on <default branch> — STOP"; exit 1; }
# 2. refresh the remote
git fetch origin <default branch>
# 3. if origin/<default branch> advanced (an autonomous auto-merge landed), integrate it FIRST
if [ "$(git rev-parse origin/<default branch>)" != "$(git merge-base HEAD origin/<default branch>)" ]; then
  echo "origin/<default branch> advanced (autonomous merge) — rebasing onto it."
  git rebase origin/<default branch> || { git rebase --abort; \
    echo "conflict with an auto-merged commit — STOP, reconcile manually"; exit 1; }
  # The base changed → RE-RUN review-close 4a-post (the merged-tree gate: the
  # project's § Pre-merge verification commands, run on the merge target) against
  # the new base before pushing. NOT Step 3 — Step 3's tree is the default branch
  # before any merge, which is not the tree this rebase moved.
fi
# 4. push the exact verified tip — NEVER --force (Rule C)
PUSHED_SHA="$(git rev-parse HEAD)"
git push origin "${PUSHED_SHA}:<default branch>"
# 5. confirm your push landed — assert CONTAINMENT, not equality: another autonomous
#    auto-merge can land on the remote between your push and this fetch (the very race
#    Rule B targets), which would fail a strict-equality check even though your push landed.
git fetch origin <default branch>
git merge-base --is-ancestor "${PUSHED_SHA}" origin/<default branch> || {
  echo "pushed SHA is not on origin/<default branch> — investigate before continuing"; exit 1; }
```

## Rule C — NEVER force-push `main` (or any branch a squash PR will write it from)

A non-fast-forward rejection on `main` means an **auto-merged commit** is on `origin/main`
that your local `main` lacks. `git push --force` / `--force-with-lease` would silently
delete it. Always fetch + rebase + re-push (Rule B) instead. The same prohibition covers
the `pr`-policy merge target, whether that is a throwaway integration branch or a reused
PR head branch — it is the PR's source of truth; never force it.
