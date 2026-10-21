**First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

```bash
python3 sysop/scripts/close_arms.py loaded "<close-id>" 4d-pr 8ffb613423c70f4c "<skill directory>"
```

It prints `LOADED: 4d-pr`. **Exit 2**: stop and show its stderr.

`main` is written only through a PR (squash), never a direct push. After the merge target holds every feature merge + `close_batch.sh` + doc consolidation, push it and merge one PR with a normal authenticated `gh pr merge` — **no `--auto`**. (GitHub-native auto-merge is gated behind paid plans for private repos; the non-`--auto` path is what `/pr-dependabot` already standardizes on and works on Free.)

**Step 1 — assert HEAD, push, and get the PR.** This is the only part that differs between the two Step 4-pre shapes.

*Integration-branch shape:*
```bash
# 1. assert HEAD is still a review-close integration branch (Rule A, HEAD-independent: a
#    concurrent actor may have moved HEAD onto main or a feature branch). Match the fixed
#    pattern — NOT $(git rev-parse --abbrev-ref HEAD), which would tautologically pass — then
#    it is safe to (re-)derive $INTEGRATION_BRANCH from HEAD for the push/PR commands below.
case "$(git rev-parse --abbrev-ref HEAD)" in
  merge/review-close-*) INTEGRATION_BRANCH="$(git rev-parse --abbrev-ref HEAD)" ;;
  *) echo "HEAD is not a review-close integration branch (merge/review-close-*) — STOP, reconcile via git reflog"; exit 1 ;;
esac
# 2. push the integration branch (NEVER push main directly; NEVER --force, per Rule C).
#    No -u: `git push -u origin` would not match the `Bash(git push origin:*)` allow-rule
#    (the -u sits between push and origin), and upstream tracking isn't needed — `gh pr
#    create --head` works off the pushed ref and Step 6 force-deletes the branch.
git push origin "$INTEGRATION_BRANCH"
# 2b. print local <default branch>'s SHA; carry it to Step 6 as PUSHED FROM (`Q-651`).
git rev-parse "<default branch>"
# 3. open the PR against main. Run it BARE — `gh pr create` prints the new PR's URL to
#    stdout and its last path segment is the number Step 2 needs. Do NOT capture it: an
#    allow-rule does not match past an assignment, so `PR_REF="$(gh pr create …)"` routes
#    to the classifier and is auto-denied under `dontAsk`, despite `Bash(gh pr create:*)`
#    being seeded (Phase 153). The title's run id is sliced off the branch name rather
#    than read from $RUN_ID, which was set in an earlier — separate — shell call.
gh pr create --base <default branch> --head "$INTEGRATION_BRANCH" \
  --title "review-close: consolidate ${INTEGRATION_BRANCH#merge/review-close-}" \
  --body "Automated /review-close integration PR: feature merges + batch close + doc consolidation. Squash-merges once required checks are green."
```

**When Step 3c recorded a `failed-waived` signal, the PR carries its output.** Write `sysop/runtime/review-close-pr-body.md` fresh with your file tool: the `--body` sentence above (not under the PR-reuse shape), then a `## Manual smoke FAIL waived` section per signal, giving its `SOURCE:`, the failing step, and the procedure's output in a fence longer than any backtick run inside it. Redact credentials, tokens and personal data first; Step 8 keeps the full output. GitHub refuses a body over 65,536 characters, so keep the output's last lines within that and say how many were cut. Run the `gh pr create` above with `--body-file sysop/runtime/review-close-pr-body.md` in place of `--body "…"`. Under the PR-reuse shape, post the file as a comment once the push below succeeds: `gh api "repos/{owner}/{repo}/issues/<PR number>/comments" -F body=@sysop/runtime/review-close-pr-body.md`. If the post fails, stop before Step 2 merges and report it.

*PR-reuse shape:* no branch is created and no PR is opened — the Step 4b/4c commits are appended to the branch the existing PR already tracks.
```bash
# 1. assert HEAD against the LITERAL branch name Step 2a approved (Rule A). There is no
#    fixed pattern to match here, and re-reading the name from HEAD would be a tautology.
test "$(git rev-parse --abbrev-ref HEAD)" = "<approved branch name>" || { echo "HEAD is not the approved branch — STOP, reconcile via git reflog"; exit 1; }
# 2. push the new commits onto the PR's head branch (fast-forward; NEVER --force, per Rule C)
git push origin "<approved branch name>"
# 2b. print local <default branch>'s SHA; carry it to Step 6 as PUSHED FROM (`Q-651`).
git rev-parse "<default branch>"
# 3. no `gh pr create` — Step 2 below merges the PR number the Step 4-pre probe printed.
```

**Under `--request-review`, stop here** and go on at that section's item 4: Step 2 runs in `--land`.

**Step 2 — wait for checks, merge, then gate on PR *state*.** Identical for both shapes, except where noted.

**First, re-derive the PR number.** This block is a separate shell call from Step 1, so nothing carries over. Run the probe bare and read the number off stdout:

```bash
gh pr list --head "$(git rev-parse --abbrev-ref HEAD)" --base <default branch> --state open \
  --json number,isDraft,isCrossRepository \
  --jq '[.[] | select(.isCrossRepository == false and .isDraft == false) | .number]
        | if length == 1 then .[0] else empty end'
```

**If that prints nothing, STOP** — reconcile by hand, and do not run anything below. This is a hard gate rather than a warning because `gh` does **not** reject an empty operand: it silently resolves the current branch's PR instead (see the `gh`-empty-operand note in Step 4-pre), so a missing number does not fail, it merges the wrong thing.

Otherwise substitute the printed number for `"<PR>"` below and run the commands **as written**. It is a literal, not a variable, for the same reason the probe is bare: a captured value would not survive to the next shell call, and an assignment would cost the invocation its allow-rule match. **Keep the quotes.** Unquoted, `<PR>` is not a placeholder to bash — `<` and `>` are redirections, and **what happens then depends on position and on the filesystem**, measured: in *final* position an unsubstituted `<X>` is a bash **syntax error** (loud, nothing runs); mid-command with no file of that name it is `bash: PR: No such file or directory`, exit 1, nothing created; and mid-command **with a file named `PR` present** it does run as `gh pr merge --delete-branch` reading from that file, `gh` falling back to the current branch — while `> --squash` also **creates a file literally named `--squash`** in the working tree. So the silent-wrong-merge case is the narrow one, and it is the one the quotes exist to remove. Quoted, an unsubstituted placeholder is a *loud* failure (`no pull requests found for branch "<PR>"`) instead of a silent wrong merge — which is what makes the stop above enforceable rather than merely advisory.

```bash
# 4. wait for the PR's required checks to finish (blocks ~1–2 min). Its exit status is NOT
#    the verdict — it exits non-zero both on a failing check and on a repo with no checks
#    at all (one protected only by enforce_admins), so a bare invocation would surface a
#    red tool result on a perfectly mergeable PR and invite you to stop. The `|| echo` tail
#    is deliberate and is NOT `|| true`: `echo` IS in Claude Code's documented built-in
#    read-only set while `true` is not, so this keeps the compound authorized while
#    preserving the do-not-abort semantics the step needs (Phase 153).
gh pr checks "<PR>" --watch --fail-fast || echo "checks reported non-zero — not the verdict; continue to command 5"
# 4b. DID ANY CHECK ACTUALLY REGISTER? Command 4 cannot tell you: it exits non-zero both on a
#     failing check and on a PR that has none, so its `|| echo` tail carries a repo-with-no-checks
#     and a checks-have-not-registered-yet through to the merge identically. Count what command 4
#     was waiting on. `statusCheckRollup` is deliberately the SAME data set `gh pr checks` reads —
#     a union of CheckRun AND StatusContext — so this counts GitHub Actions and the Status API
#     alike, and resolves the PR head itself rather than making you transcribe a SHA.
gh pr view "<PR>" --json statusCheckRollup --jq '.statusCheckRollup | length'
# 5. confirm mergeability, then squash-merge (blocks until landed; deletes the remote branch).
#    PR-reuse shape with a held doc naming the reused branch: drop --delete-branch (below).
gh pr view "<PR>" --json state,mergeStateStatus --jq '{state, mergeStateStatus}'
gh pr merge "<PR>" --squash --delete-branch
# 6. THE VERDICT. Run this as its own command, after the merge, always — the merge command's
#    exit status and stderr are NOT the verdict (see the note below). Only `state` is.
gh pr view "<PR>" --json state,mergedAt --jq '{state, mergedAt}'
```

> **Command 4b is a gate, and `0` is not a green light.** Read its number before running command 5, and route on three states, not two:
>
> - **a count ≥ 1** — checks registered and command 4 already waited for them. Proceed to command 5.
> - **the count is `0`** — **STOP. Do not run command 5.** This is *could not measure*, and it covers two different repositories that this step cannot tell apart: one with no CI configured at all, and one whose checks have simply not registered on this head yet. **Registration latency is an ordinary condition, not an incident** — measured by a consumer at roughly 30 minutes across an `opened` and a first `synchronize` event, with the checks then registering on a second `synchronize` and all passing. A repo protected by a server-side ruleset will refuse the merge anyway; one protected only by `enforce_admins`, or one where the actor holds admin bypass, will not. **The merge is the irreversible half, so the unmeasured state resolves against merging.**
> - **The probe itself errors** (network, auth, a `404` on a head SHA you mis-transcribed) — also *could not measure*. Same answer: stop.
>
> **Why this reads `statusCheckRollup` and not `commits/<sha>/check-runs`.** The REST check-runs endpoint counts **only** GitHub's Checks API. A repository whose required checks arrive through the older **Status API** — Jenkins, Buildkite, CircleCI classic, anything posting commit statuses, which is precisely what "required status checks" was built for — has `check-runs.total_count: 0` on a **fully green, fully registered** PR. Measured on a real PR head carrying one passing GitHub Actions check: `check-runs` **1**, `commits/<sha>/status` **0**, `statusCheckRollup` **1** — Sysop is the Checks-API case, and the mirror image is a consumer this gate would have blocked on every single run, with both of its stated remedies pointing the wrong way (waiting never helps, and the ruleset probe answers *yes, checks are required*). **A gate that cannot be satisfied is worse than the hole it closes.** `statusCheckRollup` is the union type — `CheckRun | StatusContext` — which is why it is the right question and why it matches command 4 rather than second-guessing it.
>
> **What to do at a `0`.** Report the PR URL and the head SHA, and hand the operator the one distinction the probe cannot make: whether the repository *has* required checks. That is a question about configuration, answered by `gh api "repos/{owner}/{repo}/rulesets"` or the branch-protection settings page — not by waiting longer. **If it answers *yes, checks are required* and the count is still `0` after command 4 returned, suspect the count before you suspect the repo**: that combination is the one shape this probe cannot produce from an honest reading, and it means the rollup and the requirement disagree. If checks are configured, re-run command 4b by hand after a few minutes; when it prints a non-zero count, resume at command 5. **`/review-close` does not need to be re-run for this, and re-running it does not help** — under the integration-branch shape a fresh run cuts a *new* branch and opens a *new* PR, whose head inherits exactly the same registration condition; under the PR-reuse shape it lands on the same PR again. Neither makes a check register.
>
> **Why there is no polling loop here.** A `while`/`sleep` retry would be the obvious shape and it is not available: `sleep` is in no seeded allow-rule and not in the harness's documented read-only set, and a loop around a runtime-discovered condition binds no rule at all (§ Invocation shapes). Re-invoking command 4's `--watch` is not a substitute either — with zero checks registered it returns *immediately*, which is the whole defect. The wait is the operator's, deliberately, and it is one re-run of one bare command.

> Here `$(git rev-parse --abbrev-ref HEAD)` is safe and non-tautological: HEAD was already asserted against a non-HEAD-derived value in Step 1 of this same block, so by this line it is *known* to be the right branch. It is a lookup key, not a guard.
>
> **PR-reuse shape only — keep a held doc's branch (`Q-642`).** When Step 4c step 1c printed a `HELD:` line whose `branch` is the reused branch, run command 5's merge as `gh pr merge "<PR>" --squash`, without `--delete-branch`, so Step 6's HARD RULE can keep the branch. The integration-branch shape always keeps `--delete-branch`. See `REFERENCE.md` § *A held doc's branch and the reuse shape*.
>
> **PR-reuse shape only — pin the head commit.** The integration-branch shape merges a branch it just created under a unique timestamped name that nothing else writes to. A reused branch is a long-lived branch someone else may push to between your push and your merge, so pass `--match-head-commit "$(git rev-parse HEAD)"` on the merge and let it refuse rather than squash-merging content you never verified. (Requires a reasonably current `gh`; if your `gh` rejects the flag, re-read `gh pr view --json headRefOid` and compare by hand before merging.)

> **A `fatal:` from `gh pr merge --delete-branch` does NOT mean the merge failed (internal tracker #208).** `--delete-branch` deletes the **local** branch as well as the remote one, so after the remote squash lands, `gh` switches the local checkout to the base branch and tries to fast-forward it. **In the integration-branch shape that fast-forward cannot succeed:** the squash commit's parent is the pre-squash `origin/<default branch>`, not local `<default branch>`, so local `<default branch>`'s commits are still not ancestors of it and `origin/<default branch>` is not a descendant of local `main` after the squash. `gh` reports it as:
>
> ```
> fatal: Not possible to fast-forward, aborting.
> ! warning: not possible to fast-forward to: "main"
> ```
>
> preceded by a block of `hint: git merge --no-ff` / `hint: git rebase` noise. That is **expected, benign, post-merge local housekeeping**, not a merge failure — `gh` swallows the error and the local branch is deleted anyway. It fires for every `pr` consumer that used `/claim-task` (its `open → in_progress` flip commits to local `main`) or whose Step 1b saved `review_tasks.md`, which is nearly all of them.
>
> **In the PR-reuse shape it does *not* fire** — reuse condition 3 requires local `main` to hold nothing the approved branch does not already carry (**not**, since Phase 219, that `origin/<default branch>..<default branch>` is empty — the widened form admits a branch that was brought up to date with `git merge <default branch>`, and such a branch leaves real local-only commits on `main`), so local `main` is an ancestor of `origin/<default branch>` and `gh`'s fast-forward succeeds. Expect the message in one shape and not the other; in neither shape is it the verdict.
>
> **Run command 6 regardless of what command 5 exited with** — that is the entire point. If your shell aborts the block early, re-run the state probe on its own; the verdict is unchanged either way. Do **not** write `gh pr merge … || true`: `gh` reports genuine failures through that exit status too, and masking it buys nothing when the next command already decides the outcome.

##### 4d-1. Stuck-PR handling (report + STOP, never force-merge)

**The trigger is PR state, never the merge command's exit status or stderr.** The PR is **not merged** if the post-merge `gh pr view "<PR>" --json state` (command 6 above) reports anything other than `MERGED`. Typical causes: a required check failed (`gh pr checks` reported a failing check) or `gh pr view` shows `mergeStateStatus: BLOCKED`/`DIRTY`. **A third cause is not a stuck PR at all and is handled before the merge, not here: command 4b printed `0`.** That is the could-not-measure state, this sub-step never sees it — by construction, since it classifies a merge that already ran — and it is the one arm of the three where nothing has landed and nothing needs unwinding. **Do not re-route a `0` into this section's recovery advice**: there is no failing check to fix, no `BLOCKED`/`DIRTY` state to rebase out of, and re-running `/review-close` inherits the condition rather than clearing it. Stop at command 4b and follow its note. Do **not** key this branch on `gh pr merge` "refusing" — under `pr` policy that command routinely prints `fatal: Not possible to fast-forward, aborting.` *after a merge that succeeded* (see the note above, internal tracker #208), and reading that as a refusal strands branches, worktrees, and `sysop/runtime/locks/` behind a close-out that actually landed. When `state` is genuinely not `MERGED`:

- **First ask whether each failing check ever ran (`Q-632`).** A job GitHub refused to start, as on an exhausted Actions budget, shows as `fail` too. List the failing checks and their links:
  ```bash
  gh pr checks "<PR>" --json name,bucket,link --jq '.[] | select(.bucket == "fail") | "\(.name)\t\(.link)"'
  ```
  A link ending `/actions/runs/<run id>/job/<job id>` is an Actions job. For each one, write its job id out and run both commands (a job's id is also its check run's id):
  ```bash
  gh api "repos/{owner}/{repo}/actions/jobs/<job id>" --jq 'if .status == "completed" and .conclusion == "failure" and (.steps | type) == "array" and (.steps | length) == 0 then "NEVER STARTED: \(.name) (run \(.run_id))" else "RAN: \(.name) — \(.conclusion), \(.steps | length) step(s)" end'
  gh api "repos/{owner}/{repo}/check-runs/<job id>/annotations" --jq '.[].message'
  ```
  **`NEVER STARTED`** is *could not measure*, like command 4b's `0`: **change no code for it.** Report the check as never started, with its annotation, and give the remedy: the human clears the cause the annotation names (only the account owner can raise an Actions budget), types `! gh run rerun <run id> --failed` (no seeded rule matches it), and resumes at command 4 when the re-run finishes. Do not re-run `/review-close` before the cause clears; its checks meet the same refusal. **`RAN`**, a probe that errors, and a failing check with any other link (a Status API context, a third-party app) are reported as failing checks, as below. When both kinds fail, report both: the re-run clears only the never-started ones, and the rest are fixed as below before command 4 is resumed. See `REFERENCE.md` § *A check that never started*.
- **Report** the PR URL and the failing check name(s), and each `## After merge` section Step 2d carried, under `<TASK-ID> (<branch>, after PR #<N> merges):`, then **STOP** — do not force-merge, do not fall back to a direct `git push origin <default branch>`, do not loop. Authority to merge belongs to the PR's required checks, not this skill.
- Leave the integration branch, the feature branches and every remaining worktree and lock **in place**. Step 3b has already removed the approved branches' worktrees, and Step 4c the locks and pending docs it consolidated. **Skip Step 6 entirely** this run — its cleanup is gated on a confirmed merge (see Step 6's merge-policy gate).
- **In the integration-branch shape, recover on the stuck branch; do not re-run `/review-close`** (`Q-652`): a re-run merges the same branches without Step 4c's work. Check out the integration branch. To fix a check, commit the fix there, run `4a-post`'s resolved command list on it, and only when that passes push it with `git push origin "<integration branch>"`; for a check that only needs re-running, re-run it. Then resume at command 4. Put the `PUSHED FROM` SHA in this stop's report: Step 6 needs it.
- **In the PR-reuse shape the recovery is different, and the sentence above does not apply.** There is no integration branch to orphan and no new one to cut: the stuck PR is the consumer's own, still open, now carrying the Step 4b/4c commits, and a re-run's probe finds that same PR again and lands on it again. That re-run is still safe — `close_batch.sh` is idempotent (its `sed` substitutions no-op on already-`Merged` batches) and Step 4c finds no pending-docs the second time because the first run deleted them, so it skips consolidation rather than double-applying it. What it is *not* is self-healing: re-running cannot clear a red required check. Fix the check, then re-run; or if the branch has become unmergeable (`BEHIND`/`DIRTY`), rebase it onto `origin/<default branch>` and push, which makes reuse condition 5 hold again. If you would rather stop reusing it, delete nothing — just let the next run fail condition 5 or close the PR by hand, and the integration-branch shape takes over.

- **A PR merged outside this run** — by hand after this stop, or by a close from before Step 4d recorded heads — gets its head recorded with Step 4d's record command, run from the primary checkout with that PR's number. Its tasks' `## After merge` steps are in the stuck close's report, and no later close prints them.

On a confirmed merge — `gh pr view "<PR>" --json state` reports `MERGED`, whatever the merge command's exit status or stderr said — **record the head of that PR**, the `<PR>` command 6 reported `MERGED`, under both shapes, then continue to Step 5 and Step 6 cleanup:

```bash
git fetch origin "refs/pull/<PR>/head:refs/sysop/merged-pr-heads/<PR>"; echo "--- record exit (0 = recorded): $?"
```

A non-zero exit records nothing. Put `not recorded — <its first error line>` on Step 8's `Squash provenance:` line and continue: the merge has landed, so do not stop. **If that PR's squash is ever reverted on `<default branch>`, delete its ref** (`git update-ref -d refs/sysop/merged-pr-heads/<PR>`): a recorded head reads as landed until it is removed, and Step 4a would skip the reverted commits. See `REFERENCE.md` § *Squash provenance: why each `pr` close records its PR head*.

**If a `gh pr` command is silently denied** (auto-mode classifier), **no hook will surface the escape for you — construct and relay it yourself.** The Phase 36 `PermissionDenied` hook matches three `git` shapes only (protected-branch push, `--delete` push, protected-branch commit); a `gh` command runs the matcher loop like any other and every matcher returns no match, so a denied `gh pr list` / `create` / `checks` / `view` / `merge` produces a bare denial with nothing attached. **This is the `pr`-policy mainline, not an edge case** — under `§ Merge policy: pr` every close runs through `gh pr`. Ask the user to type the literal `!`-prefixed command at the next prompt (`! gh pr merge "<PR>" --squash --delete-branch`, without `--delete-branch` when the note above dropped it, and so on per command), exactly as Step 3 does for a denied verification command. It is *not* the same pattern as the `direct`-policy push (`steps/4d-direct.md`): that one is hook-covered and this one is not. Do **NOT** use `AskUserQuestion`.
