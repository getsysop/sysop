#!/usr/bin/env python3
"""pr_head_check.py — `/review-close` Step 4a: does a recorded PR head contain the branch's commits?

    python3 sysop/scripts/pr_head_check.py "<branch>" "<merge target>"

Run from the repo root, under either merge policy. Prints `RECORDED HEAD: none`,
`RECORDED HEAD: not usable — …`, or the head followed by the `SKIP` and `REPLAY` commit lists.
A git failure or an unsubstituted operand exits 3.

Then a `CLOSED TASK EDITED: <path> — …` line, and a `show:` line under it, for each task body
the branch edited that the merge target has since moved to `tasks/archive/` or deleted
(`_closed_tasks.py` holds the check), and a `CLOSED TASK RE-ADDED: <path> — …` line for each body
the branch adds that the merge target holds under `tasks/archive/`. The branch's edits are read from
`merge-base <recorded head> <branch>` when the head is usable, the range `--onto` replays, and
from `merge-base <merge target> <branch>` otherwise. The published arm's `--no-ff` merge works
from the fork point instead, so with a usable head it can re-apply a landed line the target has
since removed; that is the arm's behaviour on any file, and this check does not read it.

The skill text is the contract: `/review-close` Step 4a says what each line means. This file
was that step's heredoc until Phase 387 (`Q-409` P3), moved verbatim.
"""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _closed_tasks  # noqa: E402
branch, target = sys.argv[1], sys.argv[2]
if not branch or not target or "<" in branch + target:
    print("UNSUBSTITUTED or empty operand — write the branch and the merge target out. STOP.")
    sys.exit(3)
# The branch as a branch: bare, a tag of its name resolves first (`Q-686`). A name with no
# local branch fails the first `rev-list`, which exits 3. The merge target is a local branch too.
ref = f"refs/heads/{branch}"
tgt = f"refs/heads/{target}"
def git(*args):
    r = subprocess.run(["git", *args], capture_output=True)
    if r.returncode != 0:
        print(f"git {' '.join(args)} failed: {os.fsdecode(r.stderr).strip()} — STOP.")
        sys.exit(3)
    return os.fsdecode(r.stdout).split()
heads = git("for-each-ref", "--format=%(refname)", "refs/sysop/merged-pr-heads/")
own = git("rev-list", ref, "^" + tgt)
best, skip = "", []
for head in heads:
    rest = set(git("rev-list", ref, "^" + tgt, "^" + head))
    stale = [c for c in own if c not in rest]
    if len(stale) > len(skip):
        best, skip = head, stale
def closed_task_edits(since):
    try:
        base, found = _closed_tasks.closed_task_edits(ref, tgt, since)
    except _closed_tasks.NoMergeBase as e:
        print(f"{e}, so the closed-task check cannot run. Unshallow and re-run — STOP.")
        sys.exit(3)
    except _closed_tasks.GitFailed as e:
        print(f"{e} — STOP.")
        sys.exit(3)
    for line in _closed_tasks.lines(found, base, ref, "the branch", target):
        print(line)
if not best:
    print("RECORDED HEAD: none")
    closed_task_edits(tgt)
    sys.exit(0)
replay = git("rev-list", ref, "^" + best)
extra = set(replay) - set(own)
if extra:
    print(f"RECORDED HEAD: not usable — {best} lacks {len(extra)} commit(s) the merge "
          "target already has, and --onto would replay them")
    closed_task_edits(tgt)
    sys.exit(0)
print(f"RECORDED HEAD: {best}")
print(f"SKIP {len(skip)} commit(s) PR #{best.rsplit('/', 1)[1]}'s head contains:")
for sha in reversed(skip):
    out = subprocess.run(["git", "log", "-1", "--format=%h %s", sha], capture_output=True)
    print("  " + os.fsdecode(out.stdout).strip())
print(f"REPLAY {len(replay)} commit(s)")
closed_task_edits(best)
