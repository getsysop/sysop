#!/usr/bin/env python3
"""workspace_locate.py — `/review-close` Step 3b step 0: locate a branch's workspace.

    python3 sysop/scripts/workspace_locate.py "<branch name>" "$(git worktree list --porcelain)" "${WORKTREE_PREFIX:-$(basename "$(git rev-parse --show-toplevel)")}"

Run from the repo root. Prints one line, `workspace=<path> shape=<shape>`, either side
`<none>` when nothing was found; the first hit wins. The worktree listing comes in as an
argument, so it starts no child process. An unsubstituted branch exits 3.

The skill text is the contract: `/review-close` Step 3b step 0 says what each shape means.
This file was that step's heredoc until Phase 387 (`Q-409` P3), moved verbatim.
"""
import sys
from pathlib import Path

branch, wt_listing, prefix = sys.argv[1], sys.argv[2], sys.argv[3]
repo = Path.cwd().resolve()

# An unsubstituted placeholder must HARD-FAIL, not quietly match nothing. A block that
# resolves no workspace is indistinguishable from a branch that legitimately has none,
# and "resolved nothing, said nothing" is the exact failure this step is being fixed for.
if branch.startswith("<") or not branch.strip():
    print("ERROR: substitute the branch name before running Step 3b step 0.", file=sys.stderr)
    sys.exit(3)

ws, shape = None, None

# (i) a worktree — the default /claim-task and batch_work.sh shape.
_w = None
for line in wt_listing.splitlines():
    if line.startswith("worktree "):
        _w = line[len("worktree "):]
    elif line == f"branch refs/heads/{branch}":
        ws, shape = Path(_w), "worktree"
        break

# (ii) the lock's RECORDED workspace. `claim_task.sh --lock` writes `mode:` and
# `workspace:` at claim time, so this is the claim's own statement of where the work
# happened — a fact, not a path guess. Locks are canonical under the main repo
# (git-common-dir), which is CWD here.
if ws is None:
    locks = repo / "sysop" / "runtime" / "locks"
    if locks.is_dir():
        for lk in sorted(locks.glob("*.lock")):
            if not lk.is_file():        # a lock that is a directory must not kill the close
                continue
            fields = {}
            for line in lk.read_text(encoding="utf-8", errors="replace").splitlines():
                k, sep, v = line.partition(":")
                if sep and k not in fields:
                    fields[k] = v.strip()
            if fields.get("branch") != branch or not fields.get("workspace"):
                continue
            cand = Path(fields["workspace"])
            # VERIFY the recorded workspace before taking it. The lock is the claim's own
            # statement, but a claim can be stale. An unverified arm must not be ordered
            # ahead of a verified one.
            # See REFERENCE.md, section Step 3b — provenance.
            if not cand.is_dir():
                continue
            ws, shape = cand, fields.get("mode") or "recorded"
            break

# (iii) the conventional sibling directory `claim_task.sh` computes, VERIFIED rather
# than assumed: a candidate counts only if it is a git checkout whose HEAD is this
# branch. This is the arm for `--clone` without `--lock` — USE_LOCK defaults to false,
# so a lock-only fix would be inert on exactly that invocation. HEAD is read from the
# object store, not from `git`, so this block still spawns nothing.
def head_branch(d):
    dot = d / ".git"
    if dot.is_file():                       # a worktree/submodule: `gitdir: <path>`
        line = dot.read_text(encoding="utf-8", errors="replace").strip()
        if not line.startswith("gitdir:"):
            return None
        dot = Path(line[len("gitdir:"):].strip())
        if not dot.is_absolute():
            dot = (d / dot).resolve()
    head = dot / "HEAD"
    if not head.is_file():
        return None
    ref = head.read_text(encoding="utf-8", errors="replace").strip()
    return ref[len("ref: refs/heads/"):] if ref.startswith("ref: refs/heads/") else None

if ws is None:
    # Two passes. The prefixed glob first, because it is what `claim_task.sh` computes —
    # then EVERY sibling directory, because `WORKTREE_PREFIX` is read from the *claiming*
    # session's environment and recorded nowhere except a lock that `--lock` may not have
    # written. The widening is safe because the arm verifies `HEAD`: a directory only
    # counts if it is a git checkout standing on this exact branch.
    #
    # BOTH passes glob siblings of the repo, so neither finds a workspace built under a
    # relocated root. So: relocated + `--clone` + no `--lock` is the one combination this
    # arm cannot resolve, and it resolves to `<none>`, which this step already reports
    # rather than guessing at.
    # See REFERENCE.md, section Step 3b — provenance.
    for cands in (sorted(repo.parent.glob(f"{prefix}-*")),
                  sorted(d for d in repo.parent.iterdir() if d.is_dir())):
        for cand in cands:
            if cand.resolve() == repo:
                continue
            if cand.is_dir() and head_branch(cand) == branch:
                ws, shape = cand, "discovered"
                break
        if ws is not None:
            break

# The main checkout is not a collectible workspace: `--branch` mode records
# WORKSPACE_PATH=$REPO_ROOT, and copying main's pending-docs onto themselves is at best
# a no-op and at worst a self-overwrite. Its docs are already where Step 4c looks.
# Compare RESOLVED paths — `claim_task.sh` writes `workspace:` unresolved, so it can
# contain `/../`, and on macOS the repo root reaches through `/private`.
if ws is not None:
    try:
        if ws.resolve() == repo:
            ws, shape = None, "main-checkout"
    except OSError:
        ws, shape = None, "unresolvable"

print(f"workspace={ws or '<none>'} shape={shape or '<none>'}")
