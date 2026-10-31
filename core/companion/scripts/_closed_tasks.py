"""_closed_tasks.py — the task bodies one side edited that the other side has since closed.

Shared by `pr_head_check.py` (`/review-close` Step 4a item 1, a branch against its merge target)
and `git_check.py closed-tasks` (`_shared/main-push-guard.md` Rule B step 3, the local default
branch against a newer `origin/<default branch>`). Not a command.

Step 4c closes a task by `git mv`-ing its body to `tasks/archive/`. A merge of an edit to the open
copy then has no conflict: git's rename detection carries the edit into the archived copy. So
the check runs before the merge: each body under `tasks/{open,deferred,archive}/` that `ours`
edited since `since` (`--diff-filter=M`, `--no-renames`) and that `theirs` has since moved to
`tasks/archive/` or deleted. A move between `open/` and `deferred/` is not reported: the edit
belongs in the live copy. Every operand is passed to git as given, so a caller passes full refs.
"""
from __future__ import annotations

import os
import shlex
import subprocess


class GitFailed(Exception):
    """A git call failed; the message says which, and why."""


class NoMergeBase(Exception):
    """`since` and `ours` share no merge base: a shallow clone, or unrelated histories."""


def _git_z(*args: str) -> list[str]:
    r = subprocess.run(["git", *args], capture_output=True)
    if r.returncode != 0:
        raise GitFailed(f"git {' '.join(args)} failed: {os.fsdecode(r.stderr).strip()}")
    return [os.fsdecode(p) for p in r.stdout.split(b"\0") if p]


def is_body(path: str) -> bool:
    parts = path.split("/")
    return (len(parts) == 3 and parts[0] == "tasks" and parts[1] in ("open", "deferred", "archive")
            and parts[2].endswith(".md"))


TASKS = ":(top)tasks/"  # anchored at the top level: a relative `tasks/` from a subdirectory matches nothing


def merge_bases(since: str, ours: str) -> list[str]:
    r = subprocess.run(["git", "merge-base", "--all", since, ours], capture_output=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise NoMergeBase(f"git merge-base {since} {ours} found no merge base (a shallow clone, "
                          "or unrelated histories)")
    return os.fsdecode(r.stdout).split()


def _from(base: str, ours: str, theirs: str, present: set[str]) -> dict[str, str]:
    edited = [p for p in _git_z("diff", "--name-only", "--no-renames", "--diff-filter=M", "-z",
                                base, ours, "--", TASKS) if is_body(p)]
    if not edited:
        return {}
    moved, status = {}, _git_z("diff", "--name-status", "-M", "-z", base, theirs, "--", TASKS)
    i = 0
    while i < len(status):
        if status[i].startswith(("R", "C")):
            moved[status[i + 1]] = status[i + 2]
            i += 3
        else:
            i += 2
    found = {}
    for path in edited:
        if path in present or not moved.get(path, "tasks/archive/").startswith("tasks/archive/"):
            continue  # kept, or moved between open/ and deferred/, where the edit is wanted
        found[path] = f"moved it to {moved[path]}" if path in moved else "deleted it"
    return found


def closed_task_edits(ours: str, theirs: str, since: str) -> tuple[str, list[tuple[str, str]]]:
    """(base, [(path, where)]) where `where` is `moved it to <path>` or `deleted it`. With more
    than one merge base (criss-cross history), a body counts only when every base reports it: a
    body one base calls edited, another base already holds."""
    bases = merge_bases(since, ours)
    present = set(_git_z("ls-tree", "-r", "-z", "--name-only", theirs, "--", TASKS))
    found = _from(bases[0], ours, theirs, present)
    for base in bases[1:]:
        if not found:
            break
        other = _from(base, ours, theirs, present)
        found = {p: w for p, w in found.items() if p in other}
    return bases[0], sorted(found.items())


def lines(found: list[tuple[str, str]], base: str, ours: str, side: str, theirs_name: str) -> list[str]:
    """The `CLOSED TASK EDITED:` and `show:` lines both callers print. `side` names who edited
    (`the branch`, `this close`); `theirs_name` names the side that closed it."""
    out = []
    for path, where in found:
        out.append(f"CLOSED TASK EDITED: {path} — {side} edited it, and {theirs_name} {where}")
        out.append(f"  show: git diff {base[:12]} {ours} -- {shlex.quote(path)}")
    return out
