**First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

```bash
python3 sysop/scripts/close_arms.py loaded "<close-id>" 4a-append 03ad02a93ad1b079 "<skill directory>"
```

It prints `LOADED: 4a-append`. **Exit 2**: stop and show its stderr.

Three tracked files are appended to across branches as a matter of workflow, so a conflict in them is prescribed rather than exceptional — the first two by *every* branch, `tasks/notes.md` only by a branch that edited a consumer's existing ledger. **Never resolve the first two by stripping the `<<<<<<<`/`=======`/`>>>>>>>` markers and keeping both sides**; `tasks/notes.md` is the one exception and its bullet states the two properties that make it one. For an indented list marker-stripping is exactly the resolution that corrupts silently — verified by repro, not reasoned. **`resolve_append_conflict.py` resolves `tasks/index.yml` and `tasks/notes.md` from the merge stages, never from the markers**:

- **`tasks/index.yml`** — **a conflict on a `status:` line is the one shape here that is NOT an append collision: two actors moved the same task's status, so report both values and STOP rather than resolving it** — unless Step 4a item 2's published arm traced the branch's side to a recorded PR head, which resolves it to the target's side. **Everything below is about the append case.** `/document-work` **requires** a branch that surfaces a follow-up to file it here: its otherwise-blanket "do NOT modify `tasks/index.yml`" rule carries one explicit carve-out, *"Filing a NEW follow-up task entry (id + body file under `tasks/open/`) IS allowed and is required when the work surfaces a follow-up that Step 3b would otherwise hard-fail on."* `/add-task` appends here too. So two branches filing follow-ups in one cycle collide deterministically — this is a conflict Sysop's own workflow prescribes, not an edge case. Git splits the entry into **two separate hunks** — the `id:` line and the `body:` line — and leaves every field the two entries share (`title` when identical, `phase`, `status`, `effort`, `blast_radius`, `user_action`, `depends_on`, `surfaced_by`) *outside* the markers as common context. Strip the markers and you get one entry holding **`id:` alone** while the next entry absorbs the whole shared field block plus a duplicate `body:` key. `yaml.safe_load` accepts it, the ids stay unique, and the damage is invisible to a diff read.
- **`review_tasks.md`** — see the paragraph below, which predates this section and still governs.
- **`tasks/notes.md`** — the retired notes ledger (`tasks/README.md` § *The notes ledger*). **This is the one of the three where keeping both sides IS the resolution**, and that is a property of its shape rather than a relaxation: it is a flat list of independent one-line entries with no nesting, so a union has nothing to splice wrongly. Order carries no meaning — do not reorder to make the diff tidy, and do not merge two lines that look similar; they were written by different branches about different work. **Two properties make the union safe, and BOTH must hold.** **(1) The file is flat**: one line per note, no sub-bullets, no sections, no line continued across two lines. A nested list is the `tasks/index.yml` corruption above in a file with no validator behind it. **(2) Neither side DELETED a line, or its delete is kept.** A delete leaves the file perfectly flat, and this workflow *creates* deletes: `/add-task` Step 2 promotes a note by filing it as a task and removing its line, so a union of a promotion against another branch's append brings **the promoted note back**, now duplicating a filed task. Resolve it from the stages, from the top level:

```bash
python3 sysop/scripts/resolve_append_conflict.py notes
```

It checks (1) in all three stages and writes stage 2's lines, less the lines the branch deleted, plus the lines it added that the target did not add too. **Exit 0** prints `RESOLVED:`; re-read the file, then `git add tasks/notes.md`. **Exit 1** prints `REFUSED:` (the file is not flat, or one side deleted it) and wrote nothing: abort and 4a-SKIP the branch. **Exit 2**: nothing was written; stop and show its line. Lines are compared whole, so a note one side edited and the other deleted comes back edited; look for that when you re-read. Two branches appending a *byte-identical* line merge with **no conflict at all** and collapse to one, which no resolution step can catch because none runs. No validator gates this file, so there is no green light afterwards; re-read the resolved file before you stage it.

**Resolve `tasks/index.yml` from the merge stages, structurally.** Both sides are complete files in the index; only the textual splice is broken. Stage numbering is the opposite of the intuitive reading during a rebase and was confirmed by execution, not recalled — **stage 2 is the merge target you are rebasing onto, stage 3 is the commit being replayed** (the feature branch), and stage 1 is the replayed commit's parent (the merge base during a merge). The resolver reads `:1:`, `:2:tasks/index.yml` and `:3:tasks/index.yml` itself. From the top level of the checkout where the merge stopped:

```bash
python3 sysop/scripts/resolve_append_conflict.py index
```

**On Step 4a item 2's published arm, when item 1 printed `RECORDED HEAD: <ref>`**, stage 1 predates the claim commits that head contains, so read what the branch changed since it instead, with the ref and the branch written out:

```bash
python3 sysop/scripts/resolve_append_conflict.py index --since "<ref>" "<branch>"
```

Each `TARGET SIDE: <id> …` line it prints is a status it kept on the target's side; put `<branch>: <id> — target's side (PR #<N>'s head)` on Step 8.

It starts from the merge target's file and changes only what the branch changed, copying each block verbatim from stage 3: it appends an entry the branch filed (`APPENDED:`), applies the branch's edit to an entry the target left as stage 1 had it (`APPLIED:`), removes an entry the branch removed (`REMOVED:`), and leaves out an entry the target removed (`KEPT OUT:`). It does not stage the file.
- **Exit 0** prints those lines and `RESOLVED:`. Stage and gate it, below.
- **Exit 1** prints a `REFUSED:` line for each shape that needs a person and wrote nothing: both sides added the same id differently, both sides edited one entry, the branch edited an entry the target removed or removed one the target edited, the branch changed something outside `tasks:` (`phases:`, `schema_version:`), one side deleted `tasks/index.yml`, or a body file under `tasks/` conflicted too. Abort and 4a-SKIP the branch, per item 4.
- **Exit 4** prints a `STATUS: <id> target <x>, branch <y>` line: two actors moved that task's status. Report both values and STOP.
- **Exit 2**: nothing was written (the file is not conflicted here, PyYAML or git failed, the entries could not be mapped to the text, or `--since`'s ref already holds the whole branch, which item 1's `REPLAY 0` should have kept from merging); stop and show its line. **Exit 3**: an operand is still a placeholder; write it out and re-run.

**A conflicted body file under `tasks/`** (`tasks/open/<ID>.md`, any `.md` there but the notes ledger) **with `tasks/index.yml` not conflicted** is both sides editing one task's prose. **Under `--headless`, STOP**: the close parks, and a person resolves it once. Otherwise read both sides and keep both edits, as `review_tasks.md` is resolved below; where the two edits change the same lines, abort and 4a-SKIP the branch. With `tasks/index.yml` conflicted too, the resolver refuses (exit 1) and the branch is 4a-SKIPped. Stage the resolved body with `git add`, then run `validate_tasks.py` before you continue: it exits 1 on a body that still holds a conflict marker.

Then, **stage the resolved file and gate it**:

```bash
git add tasks/index.yml
```

**before you continue — `git -c core.editor=true rebase --continue` on the local-only arm, `git -c core.editor=true merge --continue` on the published arm**:

```bash
python3 sysop/scripts/validate_tasks.py
```

**The validator run is the load-bearing half of this recipe, and its placement is the whole point.** It catches the corrupting resolution precisely — a marker-stripped union reports `task 'phase' must be int or float, got NoneType`, the same for `title` and `status`, plus an orphan body file. But Step 4c is where the validator has always first run (`### 4c` step 4's `tasks/index.yml` block, and again at the end of Step 4c), which is *after* the merge and after Step 4b's `close_batch.sh` has already committed. Running it here means a bad resolution stops the rebase instead of being discovered downstream of two commits. **Never `--continue` past a red validator.**

**Read the exit code — `1` and `2` mean different things and take different actions.** `validate_tasks.py` returns **1** for schema errors (your resolution is wrong: fix it, or abort and 4a-SKIP the branch) and **2** for environment failures — missing PyYAML, a missing `tasks/` directory, an unreadable script. A `2` says nothing about the resolution, so **do not abort on it**: fix the environment (the script self-resolves venv PyYAML via its own `sys.path` bootstrap, but a `python3` with neither will exit 2 and say so) and re-run. Aborting on a `2` discards a correct resolution and downgrades an approved branch over a missing dependency.

**What this gate does and does not cover.** It validates `tasks/index.yml`, and the task bodies only for conflict markers — `validate_tasks.py` has no knowledge of `review_tasks.md` whatsoever. A `review_tasks.md` conflict is resolved by reading both sides per the paragraph below and has **no automated gate**; do not let this step's green stand in for it. (Git does enforce one thing for free: either arm's `--continue` refuses while *any* conflicted path is unresolved, so a half-resolved commit is not reachable even though the two files are documented separately.)

Feature branches MAY modify `review_tasks.md` — typically as single-line task-checkbox flips (`[/]` → `[x]`) that rebase clean. Structural conflicts arise when the merge target has moved `review_tasks.md` between branch-cut and rebase, in two common cases: (a) another already-merged batch added a sibling `### Batch N` section, (b) the project's archive-rotation script (e.g., `archive_review_tasks.py`) rotated rounds or batches out into a sibling archive file (committed by Step 1b — and, under `pr` policy, carried onto the integration branch by Step 4-pre, which cuts it from local `<default branch>`). Resolve by reading both sides of the conflict: keep the merge target's structure as authoritative (it reflects the post-rotation / post-other-batch layout), then re-apply the branch's intent — checkbox flips and any net-new `### Batch N` section — in the new layout.
