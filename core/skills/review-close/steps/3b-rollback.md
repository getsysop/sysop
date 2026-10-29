   - **First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

      ```bash
      python3 sysop/scripts/close_arms.py loaded "<close-id>" 3b-rollback 900ad7a6dace677d "<skill directory>"
      ```

      It prints `LOADED: 3b-rollback`. **Exit 2**: stop and show its stderr.

      By Step 1a's classification, an `approved` branch passed through Step 2a's clean-state check, so the unforced remove should now succeed. If `git worktree remove` **still** refuses after the strip, that means the worktree carries a genuine untracked/modified file that appeared between Step 1a and now — **stop**, surface the error, then **roll back the pending-docs this branch copied in step (a)** so a later Step 4c cannot consolidate an unmerged branch's doc and mark its task `done` with the code never merged:

      ```bash
      python3 sysop/scripts/pending_doc_collect.py rollback "<worktree-path>" "<branch name>"
      ```

      **Exit 0 is the pass completing with every doc dispositioned**, and it prints three
      lines rather than one: `ROLLED BACK:` names what it unlinked — main's copy, where the
      worktree's own copy survives, so the doc is re-collected on a later run;
      `MAIN'S ONLY COPY, LEFT IN PLACE:` names what it deliberately did **not** remove
      because removing it would have destroyed the record rather than rolled back a copy;
      and `LEFT ALONE:` what is not this branch's, with the reason. Nothing is destroyed on
      any arm. Exit 0 means the third list is the only non-empty one it can be — anything in
      the second list exits **8**, because main is still holding this branch's doc.

      **The non-zero exits.** A separate table from the collect's, because the two subcommands
      are separate invocations and an exit code read off the wrong one is a remedy for a
      different failure.

      | exit | meaning | state of the record | what to do |
      |---|---|---|---|
      | **4** | refused before touching anything — an unsubstituted `<worktree-path>` **or `<branch name>`**, an empty branch name, a `<worktree-path>` that is not a directory, a `src_dir` that cannot be resolved, or one resolving to main's own pending-docs | **untouched** | fix the invocation. This is an assertion about the operand, never about the branch |
      | **8** | the pass ran and main is **still holding a doc claiming this branch**. The report names which case, and they are not the same: the worktree holds no readable copy, so removing main's would destroy the only record and it was left in place on purpose (`MAIN'S ONLY COPY, LEFT IN PLACE:`); or an unlink that should have succeeded failed, most often on an unwritable `sysop/runtime/pending-docs/` (`PENDING-DOC ROLLBACK FAILED:`, naming each file and its errno) | **main still holds a doc claiming this branch.** Whatever the other three lines report did happen: this is a partial pass, not a refusal | clear the cause and **re-run this rollback before Step 4c**. Step 4c item 1b holds an unmerged branch's doc rather than consolidating it, so this is not a silent loss — but it is then the only thing standing between that doc and BeanRider ISSUE-0050 |

      > **Provenance, not basename — that distinction IS the fix.** The previous form was `rm -f sysop/runtime/pending-docs/$(basename "$f")` over the worktree's files, which deleted main's copy by name with no check that this branch ever wrote it. Measured: against a **different** branch's doc it removed a file this branch never authored, and step (a) had already overwritten it, so both records were gone while the victim's worktree was already removed. Reading `branch:` from both copies makes the rollback delete only what step (a) copied. **Nothing is restored for a differing-branch collision, because nothing is displaced**: (a) refuses one outright rather than overwriting, so a doc that is not this branch's is never touched by either step. (An earlier draft briefly added a restore half for a different case — main holding the **only** copy of *this* branch's doc — and its own round removed it again: the only destination available is the worktree, and `git worktree remove` deletes that directory's gitignored content silently. So there is still no restore half, and the scoped claim above is the one that was ever measured.) An earlier draft of this phase parked the displaced copy under a `superseded/` subdirectory; that was withdrawn when its own review round showed the directory had **no consumer anywhere in the tree** — `ls sysop/runtime/pending-docs/*.md` is non-recursive, so Step 4c never sees a parked doc, and the branch's task would never close. Preserving bytes where no reader looks is not preservation. **That draft proposed the worktree's own `sysop/runtime/pending-docs/` as a destination on exactly that reasoning — it is where `/document-work` writes and where this step's collect reads, so it has a reader where `superseded/` had none — and its round killed it for a different reason: `git worktree remove`, the command step (b) is trying to run, deletes that directory's gitignored content silently at exit 0. A destination with a reader is still not a destination if it is scheduled for deletion.**

      Then downgrade this branch to SKIP for this run (leave its worktree, lock, and branch intact), and continue with the next approved branch. Silent data loss is the failure mode this guard prevents (BeanRider ISSUE-0016) — the strip never touches a real file, so it cannot cause it. (The rollback matters because step (a) copies before this remove is attempted; without it, a branch SKIP'd here leaves its doc stranded in main's `sysop/runtime/pending-docs/` for the merged branches' Step 4c to consolidate.)
