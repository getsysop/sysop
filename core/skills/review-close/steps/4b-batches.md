**First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

```bash
python3 sysop/scripts/close_arms.py loaded "<close-id>" 4b-batches 9441b791c3901eb4 "<skill directory>"
```

It prints `LOADED: 4b-batches`. **Exit 2**: stop and show its stderr.

With a non-empty set:

```bash
# Substitute the merge target Step 4-pre recorded — the integration branch name
# under `pr`, the approved branch under PR-reuse, `main` under `direct`. Write it
# out as a LITERAL: Step 4-pre is a different fenced block and `"$MERGE_TARGET"`
# is empty here (`WORKFLOW.md` § 8.2a *Persistence boundary*).
bash sysop/scripts/close_batch.sh --merge-target "<merge target>" <N1> <N2> <N3>
```

This script updates `review_tasks.md` on the checked-out branch (the merge target — it resolves the repo via `git rev-parse --show-toplevel`, so it commits to whatever branch is current): sets batch headers to `Merged`, marks task checkboxes `[x]`, updates the Statistics table, and adjusts the Grand Total counts. **One exception:** a task annotated `> Failed:` anywhere in its own block keeps its checkbox and is left out of both the flip and the counts. **The block is the task line plus the indented lines under it**, because `/codebase-review` and `/security-audit` emit a two-line task (checkbox + indented `file:line` + provenance) and the annotation lands below that — the one-line reading this sentence used to state was why the protection could not fire at all — a FAIL verdict means the work was attempted and not finished, so the batch closes as "shipped, minus these". Expect the per-batch line to read `(3 tasks closed, 1 failed — still open)` when that happens. One commit is created for all closed batches.

**`--merge-target` is not optional under `pr`, and `--force` is not its substitute**. The gate asks whether the batch branch's work landed in what this close is landing. It used to answer that by INFERRING the target from `HEAD`, and that inference is unsound in both directions — **both defects were measured on fixtures built from this step's own commands, and both are now guarded by `tests/test_close_batch_merge_target.py`**:

- **It accepted work that reaches nothing.** A branch cut FROM the batch branch, with its own commits on top, strictly contains the batch branch — so the gate printed `✓ verified merged` and flipped the header, while nothing established that `HEAD` reaches `main`. On Step 4a's **local-only (`--ff-only`) arm** — the common case in that step's own words — a legitimate integration branch and that scratch branch agree on **every** ancestry column a local check could consult, first-parent reachability included. (On the **published `--no-ff`** arm first-parent does separate them; a predicate right on one of Step 4a's two arms and wrong on the other is not a gate.) That is why the repair is to state the target rather than to narrow the test.
- **It refused work that landed correctly, on the dominant path, every run.** Step 4a merges a local-only branch with `git merge --ff-only`, which moves the merge target **to the branch tip** — so the target and the branch share a SHA for the LAST branch merged, and for the ONLY branch of a single-branch cycle. Strict SHA containment skipped its arm there and `main` refused. **The two paragraphs previously here asserted the opposite** ("the gate passes with no `--force`", "measured"); the measurement behind that claim was taken on a fixture with an extra commit after the merge, which is not the shape this step produces.

So the target is now something you **state**, and `HEAD` is never read for it. Pass the literal Step 4-pre recorded. Identity between target and branch is compared by resolved **ref name**, not by SHA: after an ff-merge they legitimately share a SHA while being different refs, and standing on the unmerged branch itself they are the same ref.

**What each Step 4-pre shape passes.** The gate itself is still `git merge-base --is-ancestor refs/heads/<batch branch> <merge target>`; what changed is where the second operand comes from, and that identity is checked by ref name before it runs. *Integration-branch shape:* `--merge-target <integration branch>`; the gate accepts every branch Step 4a merged, ff or `--no-ff`, and you **no longer need `--force` for the ancestry reason**. *PR-reuse shape:* the merge target **is** the one approved branch, so target and branch resolve to the same ref, the target arm is withheld, and **reuse still needs `--force`** — before the PR squashes there is genuinely no ancestry evidence that the work landed, which is what Step 6 says in its own words: *"After a squash there is no ancestry-shaped containment test."* *`direct`:* the target is `main`, which is also what the script resolves on its own from `§ Merge policy`, so the flag is redundant there — pass it anyway for one shape at both policies.

> **If a batch skips with `unmerged`, that is a real verdict — read it before overriding it.** It means the batch branch is an ancestor of neither the stated merge target nor `main`, i.e. Step 4a did not merge it. Fix that rather than forcing past it. **If the script reports `merge target: UNRESOLVED`, you omitted the flag under `pr` policy** — that is not a reason to reach for `--force`, which would disarm the cherry-pick detection for every batch in the run; supply the target. The one legitimate override is below: work that reached the target by **cherry-pick** rather than merge is genuinely not an ancestor, and `--force` is its documented escape.

If any branches were cherry-picked instead of rebased+merged (e.g., because worktree removal wasn't possible), use `--force` to skip the merge-base ancestry check:

```bash
bash sysop/scripts/close_batch.sh --force --merge-target "<merge target>" <N1> <N2> <N3>
```

**Verify the close-batch commit landed before proceeding — non-empty batch set only.** The script wraps its `git commit` in explicit failure handling (BeanRider ISSUE-0015), but trust-but-verify: confirm a `docs: close Batch …` commit is the new tip and the working tree is clean before continuing to Step 4c. **If the batch set was empty this gate does not apply and was already skipped above** — it asserts the result of a command this cycle correctly did not run, so reaching it with no batches is a reading error, not a failed close.

```bash
git log -1 --pretty=%s | grep -q '^docs: close Batch ' && git diff --quiet && git diff --cached --quiet
```

**A batch that landed on an earlier run is not a failed close.** When every batch you passed is reported `already-merged` with no `Could not compare this batch against HEAD` line under it, the summary reads `close-batch commit present: 0`, and the working tree is clean (`git diff --quiet && git diff --cached --quiet`), each batch is `Merged` in `HEAD` already: the gate does not apply, so continue to Step 4c. A re-run of a stuck PR-reuse close (`steps/4d-pr.md`) reaches this. An interrupted close prints `Commit resumed for:` instead, and the gate applies to it.

If the check fails **on a non-empty batch set** (no `docs: close Batch …` tip, or `review_tasks.md` is still modified/staged): the close-batch commit did NOT land. **Halt before Step 4c** — proceeding would fold the close-batch edits silently into the doc-consolidation commit instead of their own atomic commit, and ordering ("after merge but before doc consolidation") is broken. Inspect the script's stderr output (most commonly a pre-commit-hook failure — see Step 4d's venv-prefix pattern). The script's terminal `── close_batch.sh completed — close-batch commit present: N` line (BeanRider ISSUE-0039) survives tail-truncation and tells you whether the script aborted silently (line absent) or completed with no commit landed (`present: 0`). Two recovery paths, in order:

1. **Re-run the script** with the same batch list. It re-attempts the commit, and **the mechanism is worth knowing, because for a long time it did not**: the failed run left every requested batch reading `Merged` in the working tree, so the re-run's status check skipped each one as `already-merged` **before** reaching the commit block — which is gated on a non-empty closed set. Reproduced by blocking the commit with a failing `pre-commit` hook: the first run flipped and failed, and the re-run reported `Skipped: 1:already-merged` and `close-batch commit present: 0`. The script now asks a second question of each already-`Merged` batch — *is it `Merged` in `HEAD` too?* — and a batch that is `Merged` in the tree but not in the last commit is an **interrupted close**, not a finished one, so its commit is re-attempted and the summary reports `Commit resumed for: <N>`:
   ```bash
   bash sysop/scripts/close_batch.sh --merge-target "<merge target>" <N1> <N2> <N3> 2>&1
   ```
   Read the full output in the tool result — a missing terminal line is then unambiguously visible. **Do not pipe it through `tee`** (this step used to, into a bare `/tmp` path): `|` is a documented separator, so the tail becomes its own invocation, `tee` is not in the harness's read-only set and binds no shipped rule, and the prompt lands *after* the close has already run.

2. **If re-run still doesn't commit**, commit by hand with the canonical subject — same form the script would have used — and proceed. **Two reachable causes, and the second is by design:** the script aborts after the `git add` (the original cause, review_tasks.md staged and uncommitted); or it could not read the batch from `HEAD` at all, in which case it says so — `Could not read this batch from HEAD, so an interrupted-close resume cannot be offered` — and skips rather than guessing. That refusal is deliberate: it would otherwise land `docs: close Batch <N>` for a batch nobody closed. **A resume commits the INDEX and does not re-stage** — the failed run's own `git add` already put the flip there, so an unrelated working-tree edit made *between* the two runs stays uncommitted; if nothing is staged, the resume refuses rather than take the worktree copy. **That guarantee covers the resume path only.** An ordinary close still runs `git add -- review_tasks.md` and takes the whole file, so an unrelated edit already sitting in `review_tasks.md` when you run the script is committed with the close. That is long-standing behaviour, not changed here, and it is the reason to look at `git status` before closing on a dirty tracker.
   ```bash
   python3 sysop/scripts/git_check.py head-is "<merge target>" && git add review_tasks.md && git commit -m "docs: close Batch <N1>, <N2>, <N3>"
   ```
   Step 4c is safe once a `docs: close Batch …` commit is the tip.
