**First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

```bash
python3 sysop/scripts/close_arms.py loaded "<close-id>" 4a-moved 7fe75c2ecb88ebdc "<skill directory>"
```

It prints `LOADED: 4a-moved`. **Exit 2**: stop and show its stderr.

`close_arms.py tip` found the branch is not the commit Step 2 reviewed. Its `MOVED:`, `REWRITTEN:` or `UNRECORDED:` line says how, and the lines after it list the commits no review read. Nothing has moved: the branch is not merged yet. Decide once per branch per close: a later `tip` line for a branch already decided follows that decision.

- **Under `--headless` or `--unattended`**: 4a-SKIP the branch, per *When a branch really is skipped at 4a* in `SKILL.md`, and carry the `tip` line to Step 8's 4a-SKIP item. The next close reviews it; when its pending doc carries an older `branch_tip:`, that close first SKIPs it until `/document-work` is re-run, and says so.
- **Attended**: show the person the `tip` lines (on an `UNRECORDED:` line, which lists no commits, show the branch's commits since its `<base>` instead: Step 2a step 1's `log`, with its `<base>` from `python3 sysop/scripts/feature_branch.py base "<branch>" "<default branch>"`), and ask with `AskUserQuestion`:
  - `Merge it`: merge the branch as it is now, by item 2's arm, and carry the `tip` line and its commits to Step 8's `Merged after review:` row.
  - `Skip it`: 4a-SKIP it, as in the bullet above.

After a 4a-SKIP of the only approved branch, Step 4a-post's empty-list rule stops the close before anything is pushed, as for any approved branch that did not merge; under `--unattended` that stop is a durable park.

See `REFERENCE.md` § *Step 4a — the reviewed commit*.
