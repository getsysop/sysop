- **First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

  ```bash
  python3 sysop/scripts/close_arms.py loaded "<close-id>" 6-pr-gate 95aec4c23c55ac3c "<skill directory>"
  ```

  It prints `LOADED: 6-pr-gate`. **Exit 2**: stop and show its stderr.

  ```bash
  git checkout <default branch>
  git fetch origin <default branch>
  # Gate the reset on a clean TRACKED tree. `git reset --hard` discards every
  # uncommitted modification to a tracked file in this checkout — not only the
  # pre-merge commits the note below explains. Untracked files are NOT at risk
  # (`reset --hard` leaves them), which is why this tests `git diff HEAD` and not
  # a bare `git status --porcelain`: an untracked scratch file is ordinary in a
  # live repo and would refuse every close.
  git diff --quiet HEAD -- && echo "CLEAN — safe to reset" || echo "DIRTY — STOP, see below"
  ```

  **If that printed `DIRTY`, do not run the reset.** Report the file list (`git status --porcelain --untracked-files=no`) and ask the user to commit or stash. **Resume at this gate, not at the top of the skill** — the PR has already merged by this point, so nothing before Step 6 may be repeated: re-run `git diff --quiet HEAD --`, and continue from the commits-after-push check below when it reports `CLEAN`. (Do not re-enter at Step 4-pre: local `main` still carries the pre-merge commits the reset exists to discard, and its PR-reuse probe's condition 3 would read them.) **Do not stash on their behalf** — a stash this skill creates is consumed by no later step, so it converts a visible refusal into work parked where nobody looks. Two reasons the gate belongs *here* rather than at Step 1: Step 1a's `dirty` classifier never covers this checkout (it excludes the primary checkout by path identity, whatever branch that checkout holds), and Step 5's staging-deploy wait is a long idle window — exactly when a human is most likely to have edits open, so a Step 1 reading would already be stale.

  **Then check for commits made after Step 4d's push**, with the `PUSHED FROM` SHA Step 4d printed:
  ```bash
  git rev-list "<PUSHED FROM>..<default branch>" ^"origin/<default branch>"
  ```

  **If it printed any SHA, do not run the reset.** Show `git log --oneline "<PUSHED FROM>..<default branch>" ^"origin/<default branch>"` and stop: those commits reached local `<default branch>` after the push, so the squash does not contain them and the reset would drop them. Ask the user to replay them onto the merged base with `git rebase --onto "origin/<default branch>" "<PUSHED FROM>" "<default branch>"`. That rebase is the re-sync: after it, skip the reset and continue with the cleanup below it. If Step 4d's SHA was not carried, stop and say so; do not reset.

  > **Narrower than the shipped convention, deliberately.** Both shipped maps name `git reset --hard` by name: `convention_map.md` § *Destructive command gating* requires it "be preceded by an explicit 'ask the user to confirm' instruction in the skill text", and `security_map.md` § *Confirmation gates on destructive operations* requires "an explicit confirmation step in the skill text". This gate confirms *conditionally* — it refuses only when the reset would actually destroy something — because the reset is either a no-op or a load-bearing re-sync (see the both-shapes note below), so an unconditional prompt would land on every close of the dominant `pr` path and buy nothing in the clean case. The conventions' purpose is met; their literal reading is not. Stated rather than silently narrowed.

  ```bash
  # local main's pre-merge commits are now inside the squash. Comment on its own
  # line: `Bash(git reset --hard origin/<default branch>)` is an exact-match rule and whether
  # the matcher strips a trailing comment is undocumented.
  git reset --hard origin/<default branch>
  ```

  **Integration-branch shape only — then drop the integration branch.** It is `merge/review-close-<close-id>`, the merge target Step 4-pre recorded (under `--land`, `land-check`'s `BRANCH:`), written out. If it is lost, look it up — the local branch still exists at this point:
  ```bash
  git branch --list 'merge/review-close-*'
  ```
  Then delete it by its literal name, **quoted** (unquoted, `<…>` is a redirection to bash, not a placeholder):
  ```bash
  git branch -D "<integration branch>" 2>/dev/null || echo "integration branch already deleted by gh pr merge --delete-branch"
  ```
  `gh pr merge --delete-branch` removes both the remote and (once HEAD left it) the local integration branch, so it is often already gone — hence the tolerant tail. It is `|| echo`, not `|| true`: `echo` IS in Claude Code's documented built-in read-only set while `true` is not, so the compound stays authorized. The `2>/dev/null` is fine either way — a redirection is not a command separator, so it never cost the `Bash(git branch -D:*)` match; only the `|| true` did.

  **Do not run that line at all in the PR-reuse shape** — there is no integration branch, and the reused branch is handled by the per-branch cleanup below.

  > **Run the `git reset --hard origin/<default branch>` in both shapes once the clean-tracked-tree gate above passes — but know why it matters in each.** `gh pr merge --delete-branch` *attempts* this re-sync itself. **Integration-branch shape:** it fails, because local `main` has diverged by construction (see Step 4d's `fatal:` note, internal tracker #208) — here the reset is load-bearing, and treating `gh` as having already done it leaves local `main` on pre-merge commits now duplicated inside the squash. **PR-reuse shape:** it succeeds, because reuse condition 3 required local `main` to hold nothing the approved branch does not already carry (**not** that `origin/<default branch>..<default branch>` is empty — the widened form admits a branch that was brought up to date with `git merge <default branch>`, and such a branch leaves real local-only commits on `main`) — here the reset was described as a harmless no-op, and a review round measured that false for the widened condition 3: with a merge-updated branch the reuse shape is taken while local `main` still holds unpushed commits, `gh`'s fast-forward fails with the same `fatal:` as the other shape, and the reset **moves** `main` rather than doing nothing. Run it; it is load-bearing in both shapes now. Internal tracker #204's incidental note ("`gh` fast-forwards `main` itself, so Step 6's reset was already a no-op") was reported from a cycle that met condition 3, so it was **right about that cycle and wrong as a general rule**; internal tracker #208, from the same reporter, is the other shape. Neither claim generalizes — which is why this step is stated per shape rather than picking a winner.
