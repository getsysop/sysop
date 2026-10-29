   - **First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

      ```bash
      python3 sysop/scripts/close_arms.py loaded "<close-id>" 4c-check-exit dc2a2b95f64e6e3c "<skill directory>"
      ```

      It prints `LOADED: 4c-check-exit`. **Exit 2**: stop and show its stderr.

   - **Exit 1 stops the close here, before the pending-docs are deleted and before the shared docs are staged.** Fix each `PROBLEM:` line, then re-run the check until it exits 0:
     - `removed` or `lost`: put the line back where `git show HEAD:<file>` has it, and take it out of any bullet it was joined onto.
     - `lines reordered`: put the lines back in the order `git show HEAD:PROJECT_STATUS.md` has them.
     - `added`: this close wrote the line in the wrong place. Move it into §6's entries, directly above the first one; do not delete it, because the pending-doc it came from is its only other copy.
     - `gained a line of §6's furniture`: take that text out of the changelog bullet it was joined onto; the line stays in §6.
     - the entry count or order: rotate exactly as the Rotation check says.
     - a heading or `## [Unreleased]` that appears twice: move this close's bullets under the copy `HEAD` already had, and delete the copy `HEAD` did not have.
     - a deleted file: restore it with `git checkout HEAD -- <file>` and redo this close's writes to it.
     Looping over the files these lines name? Name the loop variable `entry`, never `path`: in zsh `path` is tied to `$PATH`.
   - **Exit 2:** the check could not do its job, and its `RESULT: UNCHECKED` line says why: no repository, §6 missing or there twice, an indented line directly under a §6 entry, a file or git read that failed, or more than one tracked changelog. Read `git diff -- PROJECT_STATUS.md` and the changelog's diff by hand for the four things above, then continue. Count `ROTATED:` by hand for Step 8.
   - **Exit 2 with no `RESULT:` line**, or `can't open file`, is not that arm: the script is not installed. Stop, as the pre-flight says.
