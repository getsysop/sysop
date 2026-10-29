**First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

```bash
python3 sysop/scripts/close_arms.py loaded "<close-id>" 4-pre-pr bb6a73003a22b647 "<skill directory>"
```

It prints `LOADED: 4-pre-pr`. **Exit 2**: stop and show its stderr.

**`pr`:** two shapes. Almost every run assembles on a throwaway **integration branch** (the default, below). One narrow case instead **reuses the approved branch's own open PR** — probe for it first, because cutting an integration branch there opens a *second* PR for content that already has one, re-runs the whole required-check suite on identical content, and orphans the first PR.

**PR-reuse probe (run first).** Reuse the existing PR when **all five** conditions hold:

1. **exactly one** branch is still approved **after Step 3b** — not merely after Step 2a. Step 2d can demote an approved branch to rejected ("Hold for fix") and Step 3b downgrades a branch to SKIP when its worktree refuses to remove, so the Step 2a verdict is not final. Reusing a branch this run decided *not* to merge would squash-merge it to `main`;
2. that branch has exactly one open, **non-draft, same-repository** PR whose base is `main`;
3. there are **no local-only `main` commits that the branch does not already contain** (`git rev-list --count origin/<default branch>..<default branch> --not "refs/heads/<approved branch name>"` is `0`). Carrying local-only `main` commits is the integration branch's job, and it does that by being cut from local `<default branch>` rather than by a sweep; a commit the approved branch already carries as an ancestor needs no carrying either way, because merging the branch lands it. The unqualified form of this condition (`git rev-list origin/<default branch>..<default branch>` empty) rejected that case, and the rationale it gave — *"there is nowhere to put those commits on a feature branch"* — is void precisely when they are already on it. **Measured both ways** on a branch updated by `git merge <default branch>`: unqualified `1`, `--not` form `0`. **One case the widening does NOT reach, stated because a reader will otherwise assume it does:** a branch updated by `git rebase <default branch>` instead is then *behind its own remote* by the pre-rebase commits, so **condition 4** rejects it whatever this condition says — measured `1`. The widening is reachable for a merge-updated branch and inert for a rebase-updated one;
4. the local branch is **not behind** its remote counterpart — otherwise the Step 4b/4c commits would land on a branch missing work someone else pushed to the PR, and the Step 4d push would be rejected as non-fast-forward;
5. the branch is **not behind `origin/<default branch>`**. Step 4a is skipped under reuse, so nothing rebases the branch onto the live base. The integration-branch shape exists partly to run the required checks against *current* `origin/<default branch>`; this condition is what replaces that guarantee, and without it a branch-protection rule requiring up-to-date branches yields `mergeStateStatus: BEHIND` and a refused merge.

**If anything other than exactly one branch is still approved, condition 1 already fails — skip the probe entirely and go to the integration-branch shape.** Otherwise:

```bash
git fetch origin <default branch>
# Substitute the literal branch name Step 2a approved and Step 3b left approved, here and
# in each of the two blocks that follow. Do NOT read it back from HEAD: the Rule A assert
# below has to compare HEAD against a value that did not come from HEAD (see the HARD
# RULE). It is written out rather than assigned to a variable because the later blocks
# could not have read the variable anyway (`WORKFLOW.md` § 8.2a *Persistence boundary*),
# and because an assignment sharing this block would cost the `gh` call its rule match.
# `--head` cannot be scoped to an owner (`gh pr list --help`: "<owner>:<branch> syntax not
# supported"), and GitHub allows several open PRs to share a head-branch NAME across forks.
# So filter to same-repository non-drafts and demand exactly one: `.[0]` on an unfiltered
# list can select a third party's PR, and merging that would land their code on `main`
# while reporting this run's work as merged.
#
# Run it BARE and read the number off stdout. Do NOT capture it into a variable: an
# allow-rule does not match past an assignment, so `PR_NUMBER="$(gh pr list …)"` routes
# to the classifier — and is auto-denied under `dontAsk` — despite `Bash(gh pr list:*)`
# being seeded. Every later step writes the number out as a literal for the same reason
# a variable would not survive anyway: nothing carries between fenced blocks (the
# boundary is the block, not the step).
echo "--- reusable PR number (nothing printed = none, which is the normal outcome):"
gh pr list --head "<approved branch name>" --base <default branch> --state open \
  --json number,isDraft,isCrossRepository \
  --jq '[.[] | select(.isCrossRepository == false and .isDraft == false) | .number]
        | if length == 1 then .[0] else empty end'
echo "--- local-only main commits NOT already on the branch (condition 3; must be 0 to reuse):"
python3 sysop/scripts/git_ro.py . rev-list --count origin/<default branch>..<default branch> --not "refs/heads/<approved branch name>"
```

Read both values off stdout and carry them forward as **literals**. The `echo` labels are load-bearing, not decoration: without them the two outputs are positionally ambiguous, and a *missing* first value silently shifts the second into its slot — a bare `2` reads as a PR number when it is actually the commit count with no PR found. (`echo` is in Claude Code's documented built-in read-only set, so labelling costs nothing at the permission layer. Run the count through `git_ro.py`, as written.)

**If the `gh pr list` output is empty, stop here — take the integration-branch shape.** That is the normal outcome, and it is also what an ambiguous result (two candidate PRs) deliberately produces. `/claim-task` feature branches are usually local-only under `pr` policy, so most runs have no PR to reuse. Do **not** run the remaining probes in that case — `git fetch origin refs/heads/<branch>` on a branch that was never pushed fails with `fatal: couldn't find remote ref <branch>`, which is alarming output on the *expected* path.

Only when a PR exists are conditions 4 and 5 worth checking:

```bash
# Substitute the approved branch name — the same literal you wrote into the block above.
# `$APPROVED_BRANCH` is EMPTY here: it was assigned in an earlier fenced block, and
# nothing survives from one block to the next even inside a single step (`WORKFLOW.md`
# § 8.2a *Persistence boundary*). This is not theoretical — it is what these three lines
# did on every run until it was fixed, and on this line it was invisible: `git fetch origin ""`
# exits 0 and prints a normal-looking `* branch HEAD -> FETCH_HEAD` while refreshing no
# remote-tracking ref at all. (The comment was accurate prose on an inoperative command.)
git fetch origin "+refs/heads/<approved branch name>:refs/remotes/origin/<approved branch name>"
```

**Read that fetch's exit code, and run the next block only on `0`.**

```bash
echo "--- behind remote (condition 4; must be 0):"
git rev-list --count "refs/heads/<approved branch name>..origin/<approved branch name>"
echo "--- behind origin/<default branch> (condition 5; must be 0):"
git rev-list --count "refs/heads/<approved branch name>..origin/<default branch>"
```

**If the fetch's exit is not `0`, take the integration-branch shape and do not run the counts at all.** This replaces a claim that was measured false: a failed fetch does **not** make condition 4 print nothing. `refs/remotes/origin/<branch>` survives a failed fetch for any branch this clone has ever fetched or pushed — which is every branch with an open PR, i.e. every branch that can reach this probe — so both counts resolve against **stale** refs and print `0`. `0` and `0` is exactly the answer that takes the reuse shape. Measured: with `gh` reachable over HTTPS but git transport broken (expired SSH key, agent not loaded, SSH egress blocked — the ordinary way to be here, since total network loss stops you at the `gh pr list` probe), a branch genuinely **1 behind its remote and 1 behind `origin/<default branch>`** printed `0` for both. That is a squash-merge of work this run decided not to merge, in the one direction the whole step exists to prevent. The fetch's own exit code is the only thing that distinguishes it, which is why the fetch runs as a call of its own.

Label the counts too, for a second reason: when *no* remote-tracking ref exists (a branch never pushed), condition 4 prints nothing while condition 5 still prints `0`, so an unlabelled block emits a single `0` that reads as "both are zero". The labels make an absent value visible as an absent value.

If a count **errors** or prints nothing, the conditions are unmet — take the integration-branch shape. That is the safe direction and it is intentional: this probe fails toward the flow that always works.

If the local-only count from the first probe and **both** counts above are `0` (and conditions 1–2 held, which is why you got here), take the **PR-reuse shape**:

```bash
# Substitute the approved branch name again. No `MERGE_TARGET=` assignment here: it
# would not reach Step 4a (a later block), and Step 4a now takes the merge target as a
# literal for that reason — see the note below.
git checkout "<approved branch name>"
# The PR number the first probe printed is the PR Step 4d merges; there is no
# integration branch this run. Write it out where Step 4d needs it — it is a literal
# from here on, because nothing carries between fenced blocks.
```

**Record the merge target for Step 4a as a literal**: under this shape it is the approved branch name you just checked out.

The policy's invariant is *"`main` is written only through a squash PR"* — landing the Step 4b/4c commits on the existing PR branch and merging that PR satisfies it exactly, with one fewer branch and one fewer CI cycle. Under this shape: **Step 4a is skipped** (the merge target *is* the one approved branch — there is nothing to merge into it), Step 4d pushes that same branch name and merges the PR number this probe printed instead of running `gh pr create`, and Step 6 has no integration branch to drop. Everything else in Step 4 is unchanged.

> **How often this actually fires.** Less often than it looks. Condition 3 fails whenever `/claim-task` made its `open → in_progress` flip on `main` (Step 4d) or Step 1b committed a `review_tasks.md` save — both commit to local `main` and neither is pushed — so the common single-branch cycle still takes the integration-branch shape. The reuse shape is for the case where the claim commits were already swept by a prior close and this cycle's only local-only work rode the feature branch, or where the branch was brought up to date with `git merge <default branch>` (condition 3's `--not` form, which is what makes that case reachable at all).
>
> **Falling through is not free, and the sentence that used to say so — *"falling through is never wrong, just wasteful"* — was measured false.** Taking the reuse shape when a condition is unmet is still the worse error, so keep probing rather than assuming; but the fall-through has a cost that lands on exactly one population: **an approved branch that has already been pushed.** Step 4a rebases each approved branch onto the merge target, and on a published branch that rewrites history someone else can already see. Reproduced end to end on a real remote: a branch in sync with `origin/<branch>` (`0 0`) came out of the fall-through **1 behind, 2 ahead** with a new tip SHA, and `origin/<branch>` was no longer an ancestor of anything being merged — so any PR tracking it points at commits the close abandoned, and the close opens a *second* PR for the same content. Step 4a's **Published** arm is what removes the rewrite: it merges the branch with `--no-ff` instead of rebasing it. That does not save the branch's own PR — `main` is written by a squash, so GitHub never marks it merged, and Step 6 then deletes the head branch, which closes it as *unmerged*. Step 4a item 3 says to comment on it first, and Step 8 names it either way.

**Integration-branch shape (the default — any condition above unmet).** Cut the branch off **local `<default branch>`**, so the local-only `main` commits ride on it as real ancestors, then merge `origin/<default branch>` into it so the PR's required checks still run against the current base. Those commits are the `open → in_progress` claim flips from `/claim-task` Step 4d & `/auto-build` Step 5.4 and any Step 1b `review_tasks.md` save/rotation — all committed on `main` locally but never pushed. At close time every local-only `main` commit belongs to this cycle; if you have unrelated un-pushed `main` work, resolve it before running `/review-close` under `pr` policy. **Do not re-create this branch from `origin/<default branch>` plus a cherry-pick** — that shape silently reverts a claim flip at Step 4a, and the branch under it is indistinguishable from a healthy one; `REFERENCE.md` § *Step 4-pre — provenance* has the measurement.

```bash
git fetch origin <default branch>
# The branch is named from the close id `begin` printed, written out: unique per run, and a
# literal you carry to Steps 4a-4d with no variable and no `$(date …)`.
# Cut from LOCAL <default branch>, NOT from origin/<default branch>. The local-only
# claim flips are then real ancestors of this branch, which is the whole of what stops
# Step 4a's three-way merge from resolving `status:` against a merge-base that never saw
# them.
#
# This needs a LOCAL <default branch> to exist, which the retired shape did not. If it
# does not (a `--branch <other>` clone, or someone deleted it), this fails LOUDLY with
# `fatal: '<default branch>' is not a commit` and nothing has moved yet. Recreate it —
# `git branch <default branch> origin/<default branch>` — and re-run from the top of
# Step 4-pre. Do NOT substitute origin/<default branch> here to get past it.
git checkout -b "merge/review-close-<close-id>" <default branch>
# No `MERGE_TARGET=` here — it would not reach Step 4a, which is a later block. The
# integration branch name IS the merge target: `merge/review-close-<close-id>`, written
# out at every later use.

# Bring the branch onto the CURRENT base, so the PR's required checks run against
# whatever landed since this run started. Run it UNCONDITIONALLY: it prints
# "Already up to date." when origin/<default branch> has not moved, and adds one merge
# commit when it has, which Step 4d's squash collapses. Unlike the cherry-pick this
# replaces, an empty range is a no-op rather than a hard failure, so there is no count
# to read first and no line to skip.
#
# There is a THIRD outcome, and it is not a failure of this step: with no `origin`
# remote, or no origin/<default branch> tracking ref, this exits 1 with
# `merge: origin/<default branch> - not something we can merge` and leaves NO merge in
# progress. The branch is still correct — it carries every local commit — it is merely
# not on a newer base, because there is no newer base to be on. Report it and continue.
# Distinguish it from a real conflict by `git status`: a conflict leaves MERGING.
#
# A conflict means origin/<default branch> advanced over the same lines (rare — Dependabot
# touches deps, not tasks/index.yml); resolve it in place. Do NOT `git merge --abort` and
# fall back to cutting from origin/<default branch> plus a cherry-pick: that is the shape
# that collapses the merge-base, and its damage is silent.
git merge --no-edit origin/<default branch>
```
