**First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

```bash
python3 sysop/scripts/close_arms.py loaded "<close-id>" 1b-dirty-primary c3332cfd5dd786b1 "<skill directory>"
```

It prints `LOADED: 1b-dirty-primary`. **Exit 2**: stop and show its stderr.

The check found tracked files in the main checkout that are modified, staged or deleted (its `EDITED:` lines), or work in progress there. Steps 4a and `4a-fix` rebase this checkout and Step 6 resets it, and each refuses such a file. Nothing has moved yet.

- **Exit 2, 3 or 4**: stop and show its last line. Exit 4 is a merge, rebase, cherry-pick or revert in progress, or an unmerged path: a person finishes or aborts it, then runs the close again.
- **Exit 1, under `--prepare`, `--headless` or `--unattended`**: stop. Report the `EDITED:` lines on Step 8 and end the run. Never commit a person's edits without asking them.
- **Exit 1, attended**: show the `EDITED:` and `UNTRACKED:` lines and ask with `AskUserQuestion`:
  - `Commit them on <default branch>`: one commit of exactly the `EDITED:` files, made now so that Step 2 reviews it with the unpushed main commits; the `UNTRACKED:` files stay out of it. Under `direct` the close pushes it; under `pr` the close's PR carries it.
  - `Stop the close`: nothing has moved. Commit, stash or discard them, then run the close again.

  Offer only `Stop the close` when `git branch --show-current` does not print `<default branch>`, or when `tasks/index.yml` is `EDITED:` and an `UNTRACKED:` line is under `tasks/`: the commit would carry an index entry without the body it names.

  On `Commit them`, from the main checkout's top level, with `<default branch>` and the number of `EDITED:` lines written out:

  ```bash
  python3 sysop/scripts/git_check.py head-is "<default branch>" && git add -u && git commit -m "docs: review-close commit <N> tracked edit(s) left in the main checkout"
  ```

  Then check again, whatever that exited (a commit that found nothing to commit, because git refreshed a line-ending or filter difference away, leaves a clean tree):

  ```bash
  python3 sysop/scripts/git_check.py tracked-clean
  ```

  **Exit 0**: go on to Step 1c. Any other exit: stop and show its lines and the commit's.
