**First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

```bash
python3 sysop/scripts/close_arms.py loaded "<close-id>" 4a-fix 0005afd46702609b "<skill directory>"
```

It prints `LOADED: 4a-fix`. **Exit 2**: stop and show its stderr.

1. **Set aside the notes on a target that did not merge** — rejected, SKIP or 4a-SKIP. Report each as `not acted on — <target> did not merge`.

2. **Give every other note one of three outcomes**, the rule `/document-work` Step 3 states:
   - **Fix it here** only when all four hold:
     - every file the fix edits is in this close's merged diff — the command `4a-post` item 2 runs — apart from the test that pins a behaviour fix:

       ```bash
       git rev-parse --verify --quiet origin/<default branch> >/dev/null \
         && git diff --name-only origin/<default branch>...HEAD \
         || echo "NO_ORIGIN_MAIN"
       ```

       `NO_ORIGIN_MAIN` means no note qualifies: file them all;
     - it is not a migration, a production write, or auth or payment logic;
     - no file it edits matches a glob in `.claude/security_map.md` or `.claude/security_map.project.md`;
     - a fix that changes behaviour adds the test that pins it, in the same commit.

     Read the code before you change what it does.
   - **File a task** when it cannot be fixed here: it fails a condition above, it came from the security twin, it needs a design decision or a human action, or it is too large for one re-check to review.
   - **Drop it** when nothing is wrong: a preference, a hypothetical, or already handled.

   When the human's answer would make a note fixable, ask with `AskUserQuestion` as a menu, your recommendation first, and act on the answer. A never-list note is filed whatever the answer, and with no answer the note is filed with the question written into it.

3. **Make every fix in ONE commit, and print its SHA.** Skip items 3–5 when nothing qualified.

   ```bash
   git add -- <each file the fixes edited>
   git commit -m "docs: review-close fix at close — <N> note(s)"
   git rev-parse HEAD
   ```

   Write the printed SHA out as `<fix-sha>` below. It is a literal, because no variable survives to the next block. Use the message exactly as shown: the `docs:` prefix is what the seeded `Bash(git commit -m docs:*)` rule matches, and note text never goes into a shell string, where a backtick or `$` in it would run. Step 8 carries the notes.

4. **Re-check the fix commit with one agent.** First re-run Step 2b step 2's three baseline lines, verbatim: the tree has moved since, and the baseline must precede the spawn. Then place its checkout:

   ```bash
   PIN=<fix-sha>
   PINNED=$(mktemp -d "${TMPDIR:-/tmp}/sysop-2b-XXXXXX")
   case "$(git -C "$PINNED" rev-parse --show-toplevel 2>/dev/null)" in "$(git rev-parse --show-toplevel)")
     echo "REFUSING: temp dir is inside the repository ($PINNED)"; exit 1 ;; esac
   SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/sysop-scratch-XXXXXX") && echo "PINNED=$(cd "$PINNED" && pwd -P) SCRATCH=$(cd "$SCRATCH" && pwd -P)"
   git worktree add --detach "$PINNED" "$PIN"
   ```

   Then spawn an Agent with:
   - `subagent_type: "general-purpose"`
   - `model: "sonnet"`, `effort: "high"` (the **convention-gate** role, as Step 2b step 3) <!-- sysop:role=convention-gate -->
   - `isolation: "worktree"`
   - `description: "Fix re-check: <fix-sha>"`
   - `prompt`: Step 2b step 3's prompt, with these substitutions and nothing else changed:
     - the opening line: *"You are re-checking fixes the close made to approved work, just before it merges to production. Review the diff below for violations of the project's conventions, and BLOCK any hunk that does more than the note it cites asked for."*
     - `<PIN>` is `<fix-sha>`, and `## Target` is `fix commit <fix-sha>`.
     - `## Diff` carries `git diff <fix-sha>^ <fix-sha>` under Step 2b step 1's 1,000-line rule. Above it, the retrieval command is `git -C <absolute path to the pinned checkout> diff <fix-sha>^ <fix-sha>`.
     - a `## Notes being fixed` block after `## Diff`, listing verbatim each note the commit claims to fix.
     - the `NOTES:` block and its paragraph are removed. The re-check raises no notes, so fixing at close is one pass.

   `## Project conventions` is what Step 2b sent: the same paste, or the same `sysop/runtime/2b-conventions.md`. Spawn no security twin. After the verdict, apply Step 2b's HARD RULE: the removal loop, then the five-command assertion.

5. **Act on the verdict.** `APPROVED` keeps the commit. `BLOCKED`, a mismatched echo, or no verdict at all drops the whole commit, and every note it carried goes to item 6. Check first, in its own call:

   ```bash
   git rev-parse HEAD
   ```

   Only when that printed `<fix-sha>`, drop it:

   ```bash
   git rebase --onto <fix-sha>~1 <fix-sha>
   ```

   The commit is unpushed and is `HEAD`, so the drop leaves the merge target exactly as the merges left it, and the close continues. If the check printed anything else, or the drop fails, stop: report that the fix commit is still on the merge target, with the re-check's verdict. Do not amend the fix and re-check again.

