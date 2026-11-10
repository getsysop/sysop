**First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

```bash
python3 sysop/scripts/close_arms.py loaded "<close-id>" 2b-leak 4abdd64e7c746fc7 "<skill directory>"
```

It prints `LOADED: 2b-leak`. **Exit 2**: stop and show its stderr.

`check` sorts what it found by whose it is. Act on each line by its first word, and on the five checks' other lines as the paragraphs below say. Where this arm says to carry a line to Step 8's `Left by 2b:` row, under `--prepare` write it to the run's `<DIR>/close.md` instead.

1. **`LEAK:`** is ours: a `worktree-agent-*` branch, or a worktree whose path Step 2b step 4 recorded with `own`. Remove ours with the one command that removes nothing else:

   ```bash
   python3 sysop/scripts/review_pins.py reap "<default branch>"
   ```

   It prints a `DISCARDING:` line for each uncommitted file it removes, `REMOVED:` for each worktree and branch, `KEPT: <what>, <why>` for each it left, and `REAPED: <n> removed, <n> kept`. **Exit 2**: stop and show its output. **Do not run `git worktree remove` or `git branch -D` yourself**, and never `--force`. Carry each `DISCARDING:` and `KEPT:` line to Step 8's `Left by 2b:` row; a `KEPT:` line is reported, not fixed.
2. **`FOREIGN:`** is another session's: a worktree under `.claude/worktrees/` or inside this checkout that this close did not create, or the branch tip or `branch.<name>.*` config of a branch another worktree has checked out, or had at the baseline. **Never remove, revert or reset it.** Attended, show the lines and ask with `AskUserQuestion`: `Leave it and continue` (carry the lines to Step 8's `Left by 2b:` row) or `Stop the close`. Under `--prepare`, `--headless` or `--unattended`, leave it, carry the lines to that row, and continue. A `FOREIGN:` tip of a branch this close is merging is not settled here: Step 4a's `tip` check compares that branch with the commit Step 2 reviewed.
3. **`LOCKED:` and `PREDATES:`** are not findings, and `check` exits 0 on them alone: carry them to Step 8's `Left by 2b:` row.

Then run `python3 sysop/scripts/review_pins.py check` again. When every line it prints is a clean line, a `FOREIGN:` line you were told to leave, a `LEAK:` line `reap` reported `KEPT:`, `LOCKED:` or `PREDATES:`, continue where the HARD RULE was applied: Step 3b, or `4a-fix`'s next item. Otherwise stop and show the lines; under `--prepare` that halts the prepare.

> **The fifth check VERIFIES the removal above; it does not discover the checkouts.** They live under `sysop/runtime/pins/`, which git ignores, so they never appear in the third check's `git status` delta and never reach `.claude/worktrees/` for the first — the only handle on them is `git worktree list`. Because `review_pins.py clean` runs first, the ordinary result here is `no pinned checkouts`, and **anything it lists is a checkout `clean` could not take** — a dirty one it refused, or one belonging to a concurrent close. Read it, do not `--force` past it. `reap` does not take these: they are `--detach`ed under `sysop/runtime/pins/`, and a leaked pin is never reviewed as someone's feature work (Step 1a's porcelain parser emits no row for a detached worktree).
>
> A **third-check** difference `check` did not mark `FOREIGN:` **is a mutation of the primary tree**, by an agent or by a person while the agents ran. Inspect each line and revert or set it aside deliberately; do not carry it into Step 3b, where it becomes indistinguishable from the close's own work and rides Step 4c's consolidation commit under that commit's message. Lines inside a worktree the first check named are that check's, and `check` leaves them out of this one. **Do not skip this because the harness usually cleans up.**
>
> **If the first, third or fourth check prints `MISSING BASELINE:` or `UNREADABLE BASELINE:`, that step-2 baseline was never captured — that is the loud failure, and it is not optional to fix.** Re-running the capture *now* cannot help: it would record whatever the agents did as the starting state. Inspect the tree by hand against `git log`, or re-run Step 2b from a known-clean point.
>
> **Use `status --porcelain`, not `git diff --quiet HEAD --`.** The dominant observed breach shape is a *new untracked* scratch file, and `git diff` cannot see one — untracked files are invisible to it and to the 4a-post and 4b gates alike, which is why the prompt rule above had to name file creation directly. `status --porcelain` lists them.
>
> **The fourth check's delta is usually not an agent — it is the harness, and its remedy is a restore rather than a revert.** Spawning with `isolation: "worktree"` converts a **relative** `core.hooksPath` to an absolute path in the repository's shared `--local` config and never puts it back. Both spellings name the same directory, so `main`'s hooks keep working and the close is not at risk — but every *worktree* created afterwards runs the **primary** checkout's hooks instead of its own branch's, which is the opposite of the property the relative form was chosen for. Restore it with `python3 sysop/scripts/review_pins.py restore-hooks-path`, which sets the value `sysop/runtime/2b-config-baseline.txt` recorded and prints `RESTORED:`; a `git config` of your own is denied under `dontAsk`. **Match on the lower-cased key.** `git config --list` renders it `core.hookspath`, so a grep for `core.hooksPath` finds nothing and reports clean — which is why this is a diff against a captured baseline and not a targeted probe. **A repo that sets no `core.hooksPath` sees no delta here**, so a clean fourth check is the ordinary result and is not evidence the check is inert.
