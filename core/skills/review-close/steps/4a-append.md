**First, record that this arm loaded**, from the main checkout's top level, with the close id `begin` printed and the skill directory the stub named written out:

```bash
python3 sysop/scripts/close_arms.py loaded "<close-id>" 4a-append 481d6d28cb7dc00a "<skill directory>"
```

It prints `LOADED: 4a-append`. **Exit 2**: stop and show its stderr.

Three tracked files are appended to across branches as a matter of workflow, so a conflict in them is prescribed rather than exceptional — the first two by *every* branch, `tasks/notes.md` only by a branch that edited a consumer's existing ledger. **Never resolve the first two by stripping the `<<<<<<<`/`=======`/`>>>>>>>` markers and keeping both sides**; `tasks/notes.md` is the one exception and its bullet states the two properties that make it one. For an indented list marker-stripping is exactly the resolution that corrupts silently — verified by repro, not reasoned:

- **`tasks/index.yml`** — **a conflict on a `status:` line is the one shape here that is NOT an append collision: two actors moved the same task's status, so report both values and STOP rather than resolving it** — unless Step 4a item 2's published arm traced the branch's side to a recorded PR head, which resolves it to the target's side. **Everything below is about the append case.** `/document-work` **requires** a branch that surfaces a follow-up to file it here: its otherwise-blanket "do NOT modify `tasks/index.yml`" rule carries one explicit carve-out, *"Filing a NEW follow-up task entry (id + body file under `tasks/open/`) IS allowed and is required when the work surfaces a follow-up that Step 3b would otherwise hard-fail on."* `/add-task` appends here too. So two branches filing follow-ups in one cycle collide deterministically — this is a conflict Sysop's own workflow prescribes, not an edge case. Git splits the entry into **two separate hunks** — the `id:` line and the `body:` line — and leaves every field the two entries share (`title` when identical, `phase`, `status`, `effort`, `blast_radius`, `user_action`, `depends_on`, `surfaced_by`) *outside* the markers as common context. Strip the markers and you get one entry holding **`id:` alone** while the next entry absorbs the whole shared field block plus a duplicate `body:` key. `yaml.safe_load` accepts it, the ids stay unique, and the damage is invisible to a diff read.
- **`review_tasks.md`** — see the paragraph below, which predates this section and still governs.
- **`tasks/notes.md`** — the retired notes ledger (`tasks/README.md` § *The notes ledger*). **This is the one of the three where keeping both sides IS the resolution**, and that is a property of its shape rather than a relaxation: it is a flat list of independent one-line entries with no nesting, so a union has nothing to splice wrongly. Order carries no meaning — do not reorder to make the diff tidy, and do not merge two lines that look similar; they were written by different branches about different work. **Two properties make the union safe, and BOTH must hold — check them, do not assume them.** **(1) The file is flat**: one line per note, no sub-bullets, no sections, no line continued across two lines. A nested list is the `tasks/index.yml` corruption above in a file with no validator behind it. **(2) Neither side DELETED a line.** A delete is not structure and leaves the file perfectly flat, so property (1) does not catch it — and this workflow *creates* deletes: `/add-task` Step 2 promotes a note by filing it as a task and removing its line. Union a promotion against another branch's append and **the promoted note comes back**, now duplicating a filed task. Verify with the merge stages before you union — same numbering as the `tasks/index.yml` recipe below, stage 2 is the merge target and stage 3 is the branch being replayed:

```bash
STAGES=$(mktemp -d "${TMPDIR:-/tmp}/sysop-stages-XXXXXX") && echo "STAGES=$STAGES"
git show :1:tasks/notes.md > "$STAGES/base.md"    # merge base
git show :2:tasks/notes.md > "$STAGES/ours.md"    # merge target
git show :3:tasks/notes.md > "$STAGES/theirs.md"  # this branch
# Any line present in the base and missing from a side is that side's deliberate delete:
comm -23 <(sort "$STAGES/base.md") <(sort "$STAGES/ours.md")
comm -23 <(sort "$STAGES/base.md") <(sort "$STAGES/theirs.md")
```

**Both empty → union is correct, keep both sides.** **Either non-empty → do not union.** Take the merge target's file and append only the lines stage 3 *added* relative to stage 1, so each side's deletes survive. **Two more traps, both measured rather than reasoned:** under `merge.conflictStyle=diff3`/`zdiff3` there is a fourth marker, `|||||||`, and a strip of only the three named above leaves it and the whole base section in the file — which reinjects exactly the line a promotion removed; and two branches appending a *byte-identical* line merge with **no conflict at all** and collapse to one, which no resolution step can catch because none runs. No validator gates this file, so there is no green light afterwards; re-read the resolved file before you stage it.

**Resolve `tasks/index.yml` from the merge stages, structurally.** Both sides are complete files in the index; only the textual splice is broken. Stage numbering is the opposite of the intuitive reading during a rebase and was confirmed by execution, not recalled — **stage 2 is the merge target you are rebasing onto, stage 3 is the commit being replayed** (the feature branch):

```bash
STAGES=$(mktemp -d "${TMPDIR:-/tmp}/sysop-stages-XXXXXX") && echo "STAGES=$STAGES"
git show :1:tasks/index.yml > "$STAGES/base.yml"     # merge base — what the branch started from
git show :2:tasks/index.yml > "$STAGES/ours.yml"     # merge target — has the other branches' entries
git show :3:tasks/index.yml > "$STAGES/theirs.yml"   # this branch — has its own changes
```

Take the merge target's file as the base and append only the entries whose `id` it does not already carry, copying each new entry's block **verbatim** from stage 3. Do not hand-retype fields and do not reorder the target's existing entries.

**Union-by-id alone is not sufficient, and each gap below can lose work with the validator green.** Before you apply it, diff stage 3 against **stage 1** (the replayed commit's parent during a rebase, the merge base during a merge — present on a content conflict) and classify what the branch actually did:

- **The branch MODIFIED an existing entry** (a retriage, a `status`/`effort`/`blast_radius` change, a `deferred` move, an `/onboard` import rewriting the backlog). Union-by-id **discards that change wholesale** — the id is already present, so stage 3's version is never applied — and the result validates clean, because the merge target's file is internally consistent on its own. Re-apply each modified entry's fields onto the base by hand, or abort and 4a-SKIP. **Do not assume this cannot happen** because `/document-work` and `/add-task` are append-only: a task whose *subject* is the backlog legitimately rewrites entries on its branch.
- **The branch REMOVED an entry** — an id in stage 1 that stage 3 no longer carries (a withdrawn task, an `/onboard` dedup). Union-by-id keeps the target's copy, so the removal is undone. Delete that entry from the base too; if the target removed it as well, there is nothing to do. If the target changed the entry or its body file (`tasks/open/<ID>.md`, which then conflicts modify/delete) since stage 1, both sides edited it: abort and 4a-SKIP. A `body file does not exist` error naming an id stage 3 dropped is this shape; do not recreate the body.
- **The TARGET removed an entry the branch kept** — an id in stage 1 and stage 3 that stage 2 no longer carries. It is not new: do not append it, or the target's removal is undone. If the branch changed the entry or its body file (which then conflicts modify/delete) since stage 1, abort and 4a-SKIP.
- **Both sides added the SAME id** — the deterministic outcome when two branches auto-number from the same base. Union-by-id keeps one and **silently annihilates the other's task**. Renumber the incoming entry to the next free id, and **resolve its body file too**: `tasks/open/<ID>.md` conflicts `add/add` in this shape, and neither `validate_tasks.py` nor the shipped `pre-commit` scans for conflict markers, so staging it commits `<<<<<<<` into the task body with every gate green. Grep the branch for references to the old id before continuing.
- **The branch edited anything outside `tasks:`** — `phases:`, `schema_version:`, a sprint note. Taking the target's file as the base drops those too. A new phase plus a task filed into it surfaces as `task 'phase' N does not match any phases[].number`; **do not "fix" that by retyping the task's `phase:`**, which validates green while discarding the phase and silently reassigning the task.

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

**What this gate does and does not cover.** It validates `tasks/index.yml` only — `validate_tasks.py` has no knowledge of `review_tasks.md` whatsoever. A `review_tasks.md` conflict is resolved by reading both sides per the paragraph below and has **no automated gate**; do not let this step's green stand in for it. (Git does enforce one thing for free: either arm's `--continue` refuses while *any* conflicted path is unresolved, so a half-resolved commit is not reachable even though the two files are documented separately.)

Write the stage extracts into the fresh directory each block makes and prints (`STAGES=`), not the repo root and never a fixed name in the shared temp directory, which a concurrent close would overwrite — and delete them when the resolution is written. Nothing in the shipped flow stages untracked files, so a repo-root scratch file is not committed; but Step 1a deliberately skips the primary checkout, so one left behind is never surfaced and persists indefinitely. `${TMPDIR:-/tmp}` is the house convention (Phase 153 — `TMPDIR` is unset on most Linux shells, so the fallback is required and a drift guard enforces it) and removes the question.

Feature branches MAY modify `review_tasks.md` — typically as single-line task-checkbox flips (`[/]` → `[x]`) that rebase clean. Structural conflicts arise when the merge target has moved `review_tasks.md` between branch-cut and rebase, in two common cases: (a) another already-merged batch added a sibling `### Batch N` section, (b) the project's archive-rotation script (e.g., `archive_review_tasks.py`) rotated rounds or batches out into a sibling archive file (committed by Step 1b — and, under `pr` policy, carried onto the integration branch by Step 4-pre, which cuts it from local `<default branch>`). Resolve by reading both sides of the conflict: keep the merge target's structure as authoritative (it reflects the post-rotation / post-other-batch layout), then re-apply the branch's intent — checkbox flips and any net-new `### Batch N` section — in the new layout.
