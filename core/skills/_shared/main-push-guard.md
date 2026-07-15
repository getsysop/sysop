# Shared guard: safe commit + push to `main`

Any skill that **commits to, or pushes, `main` (or an integration branch destined for
`main`) from the shared _primary_ worktree** MUST follow this guard. Git keeps **one
`HEAD` per worktree**, and Sysop runs concurrent loops (`/auto-build`'s parallel
batch, separate `/claim-task` sessions) against a `main` that — on an unprotected repo —
can also advance on its own. So a commit or push made without re-asserting the branch can
land on the wrong branch or clobber an autonomous merge.

Sites in Sysop that this guard covers:

| Site | Operation | Expected `HEAD` |
|---|---|---|
| `/review-close` Step 4a–4c (`direct` policy) | feature merges, batch close, doc-consolidation commits | `main` |
| `/review-close` Step 4a–4c (`pr` policy) | the same commits, on the integration branch | `$INTEGRATION_BRANCH` |
| `/review-close` Step 4d (`direct` policy) | safe push to `main` (Rule B) | `main` |
| `/review-close` Step 4d (`pr` policy) | push the integration branch + open the PR | `$INTEGRATION_BRANCH` |
| `/claim-task` Step 4d | claim-flip commit (`open → in_progress`) | `main` |
| `/auto-build` Step 5.4 | per-task claim-flip commit (in a loop) | `main` |
| `/document-work` Step 5 | `git push -u origin HEAD` (a feature branch) | **not** `main` |

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

```bash
# EXPECTED_BRANCH is the branch this step intends to write — see the table above.
test "$(git rev-parse --abbrev-ref HEAD)" = "$EXPECTED_BRANCH" || {
  echo "HEAD is not $EXPECTED_BRANCH (a concurrent actor moved it) — STOP."; exit 1; }
```

`/document-work` Step 5 is the one inverted case — it pushes a _feature_ branch, never
`main`, so it asserts `HEAD` is **not** `main`:

```bash
test "$(git rev-parse --abbrev-ref HEAD)" != "main" || {
  echo "HEAD is main — Step 5 pushes a feature branch; /review-close owns main. STOP."; exit 1; }
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

```bash
# 1. on main? (Rule A)
test "$(git rev-parse --abbrev-ref HEAD)" = "main" || { echo "not on main — STOP"; exit 1; }
# 2. refresh the remote
git fetch origin main
# 3. if origin/main advanced (an autonomous auto-merge landed), integrate it FIRST
if [ "$(git rev-parse origin/main)" != "$(git merge-base HEAD origin/main)" ]; then
  echo "origin/main advanced (autonomous merge) — rebasing local main onto it."
  git rebase origin/main || { git rebase --abort; \
    echo "conflict with an auto-merged commit — STOP, reconcile manually"; exit 1; }
  # The base changed → RE-RUN review-close Step 3 (the project's
  # § Pre-merge verification commands) against the new base before pushing.
fi
# 4. push the exact verified tip — NEVER --force (Rule C)
PUSHED_SHA="$(git rev-parse HEAD)"
git push origin "${PUSHED_SHA}:main"
# 5. confirm your push reached main — assert CONTAINMENT, not equality: another autonomous
#    auto-merge can land on origin/main between your push and this fetch (the very race
#    Rule B targets), which would fail a strict-equality check even though your push landed.
git fetch origin main
git merge-base --is-ancestor "${PUSHED_SHA}" origin/main || {
  echo "pushed SHA is not on origin/main — investigate before continuing"; exit 1; }
```

## Rule C — NEVER force-push `main` (or an integration branch destined for it)

A non-fast-forward rejection on `main` means an **auto-merged commit** is on `origin/main`
that your local `main` lacks. `git push --force` / `--force-with-lease` would silently
delete it. Always fetch + rebase + re-push (Rule B) instead. The same prohibition covers
the `pr`-policy integration branch — it is the PR's source of truth; never force it.
