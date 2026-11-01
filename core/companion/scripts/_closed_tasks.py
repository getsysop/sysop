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

Where a body went is decided by its file name first, since every writer names a body `<ID>.md`
and a close keeps the name: `tasks/archive/<name>` in `theirs` is the close, and an `open/` or
`deferred/` copy a live move. Rename pairing (`-M`) is the fallback only: a close that also edits
the body, beside a near-copy filed as a new task, paired the open body with the new one, and the
check read no close. And a body `ours` ADDED (`--diff-filter=A`) whose name `theirs` holds under
`tasks/archive/`, closed since the merge base, is re-added: a branch replaying a landed squash puts the stale open copy back
beside the closed one, with no conflict.
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


#: A `where` that starts with this is a body `ours` adds and `theirs` has closed.
READDED = "closed it at "
TASKS = ":(top)tasks/"  # anchored at the top level: a relative `tasks/` from a subdirectory matches nothing


def merge_bases(since: str, ours: str) -> list[str]:
    r = subprocess.run(["git", "merge-base", "--all", since, ours], capture_output=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise NoMergeBase(f"git merge-base {since} {ours} found no merge base (a shallow clone, "
                          "or unrelated histories)")
    return os.fsdecode(r.stdout).split()


def _from(base: str, ours: str, theirs: str, present: set[str]) -> dict[str, str]:
    found = {}
    added = [p for p in _git_z("diff", "--name-only", "--no-renames", "--diff-filter=A", "-z", base,
                               ours, "--", TASKS) if is_body(p) and p not in present]
    # Closed since the fork only: an archive copy the base already held is an earlier close, and a
    # body `ours` adds under that name is a reopen, not a replay.
    archived = set(_git_z("ls-tree", "-r", "-z", "--name-only", "--full-name", base, "--",
                          ":(top)tasks/archive/")) if added else set()
    for path in added:
        closed = "tasks/archive/" + path.rsplit("/", 1)[-1]
        if closed in present and closed not in archived:
            found[path] = f"{READDED}{closed}"
    edited = [p for p in _git_z("diff", "--name-only", "--no-renames", "--diff-filter=M", "-z",
                                base, ours, "--", TASKS) if is_body(p) and p not in present]
    if not edited:
        return found
    moved, status = {}, _git_z("diff", "--name-status", "-M", "-z", base, theirs, "--", TASKS)
    i = 0
    while i < len(status):
        if status[i].startswith(("R", "C")):
            moved[status[i + 1]] = status[i + 2]
            i += 3
        else:
            i += 2
    for path in edited:
        name = path.rsplit("/", 1)[-1]
        if f"tasks/archive/{name}" in present:
            found[path] = f"moved it to tasks/archive/{name}"
        elif f"tasks/open/{name}" in present or f"tasks/deferred/{name}" in present:
            continue  # moved between open/ and deferred/, where the edit is wanted
        elif not moved.get(path, "tasks/archive/").startswith("tasks/archive/"):
            continue  # renamed into a live copy under another name
        else:
            found[path] = f"moved it to {moved[path]}" if path in moved else "deleted it"
    return found


def closed_task_edits(ours: str, theirs: str, since: str) -> tuple[str, list[tuple[str, str]]]:
    """(base, [(path, where)]) where `where` is `moved it to <path>`, `deleted it`, or (a body
    `ours` added) `closed it at <path>`. With more
    than one merge base (criss-cross history), a body counts only when every base reports it: a
    body one base calls edited, another base already holds."""
    bases = merge_bases(since, ours)
    # `--full-name`: from a subdirectory `ls-tree` prints paths relative to it, and `diff` does not.
    present = set(_git_z("ls-tree", "-r", "-z", "--name-only", "--full-name", theirs, "--", TASKS))
    found = _from(bases[0], ours, theirs, present)
    for base in bases[1:]:
        if not found:
            break
        other = _from(base, ours, theirs, present)
        found = {p: w for p, w in found.items() if p in other}
    return bases[0], sorted(found.items())


def lines(found: list[tuple[str, str]], base: str, ours: str, side: str, theirs_name: str) -> list[str]:
    """The `CLOSED TASK EDITED:` (or `CLOSED TASK RE-ADDED:`) and `show:` lines both callers print.
    `side` names who edited (`the branch`, `this close`); `theirs_name` names the side that closed it."""
    out = []
    for path, where in found:
        if where.startswith(READDED):
            out.append(f"CLOSED TASK RE-ADDED: {path} — {side} adds it, and {theirs_name} {where}")
        else:
            out.append(f"CLOSED TASK EDITED: {path} — {side} edited it, and {theirs_name} {where}")
        out.append(f"  show: git diff {base[:12]} {ours} -- {shlex.quote(path)}")
    return out
