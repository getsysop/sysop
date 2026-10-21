#!/usr/bin/env python3
"""pr_head_check.py — `/review-close` Step 4a: does a recorded PR head contain the branch's commits?

    python3 sysop/scripts/pr_head_check.py "<branch>" "<merge target>"

Run from the repo root. Prints `RECORDED HEAD: none`, `RECORDED HEAD: not usable — …`, or the
head followed by the `SKIP` and `REPLAY` commit lists. A git failure or an unsubstituted
operand exits 3.

The skill text is the contract: `/review-close` Step 4a says what each line means. This file
was that step's heredoc until Phase 387 (`Q-409` P3), moved verbatim.
"""
import os, subprocess, sys
branch, target = sys.argv[1], sys.argv[2]
if not branch or not target or "<" in branch + target:
    print("UNSUBSTITUTED or empty operand — write the branch and the merge target out. STOP.")
    sys.exit(3)
def git(*args):
    r = subprocess.run(["git", *args], capture_output=True)
    if r.returncode != 0:
        print(f"git {' '.join(args)} failed: {os.fsdecode(r.stderr).strip()} — STOP.")
        sys.exit(3)
    return os.fsdecode(r.stdout).split()
heads = git("for-each-ref", "--format=%(refname)", "refs/sysop/merged-pr-heads/")
own = git("rev-list", branch, "^" + target)
best, skip = "", []
for head in heads:
    rest = set(git("rev-list", branch, "^" + target, "^" + head))
    stale = [c for c in own if c not in rest]
    if len(stale) > len(skip):
        best, skip = head, stale
if not best:
    print("RECORDED HEAD: none")
    sys.exit(0)
replay = git("rev-list", branch, "^" + best)
extra = set(replay) - set(own)
if extra:
    print(f"RECORDED HEAD: not usable — {best} lacks {len(extra)} commit(s) the merge "
          "target already has, and --onto would replay them")
    sys.exit(0)
print(f"RECORDED HEAD: {best}")
print(f"SKIP {len(skip)} commit(s) PR #{best.rsplit('/', 1)[1]}'s head contains:")
for sha in reversed(skip):
    out = subprocess.run(["git", "log", "-1", "--format=%h %s", sha], capture_output=True)
    print("  " + os.fsdecode(out.stdout).strip())
print(f"REPLAY {len(replay)} commit(s)")
