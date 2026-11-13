"""_ignored_link.py — whether an untracked symlink in a workspace is tooling or work.

An untracked symlink whose target is gitignored is tooling (a `.venv` link), not a pending
change (BeanRider ISSUE-0043). Which repository's ignore rules answer depends on where the
target lies: a target inside the workspace is asked of the workspace itself, any other target
of the main checkout. Asking the main checkout about a target inside a worktree it holds under
an ignored directory (`.claude/worktrees/<x>`) answered "ignored" for every file there, so a
link to the worktree's own tracked file read as tooling (`Q-775`). A `--branch` claim's
workspace is the main checkout, so both questions are the same one there.

`/review-close` Step 1a (`close_state.py worktrees`), Step 1-pre (`clone_sync.py`), Step 2a
step 0b (`feature_branch.py landed`), Step 3b item b (`close_state.py strip-links`) and
`/sitrep`'s survey all read the shape through `ignored_link`, so they give one answer.
"""
import os
import subprocess

# A caller's GIT_DIR or GIT_WORK_TREE would answer for its own repository whatever `-C` names.
_ENV = {k: v for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}


def _ignored(repo: str, target: str, timeout: "float | None") -> bool:
    try:
        r = subprocess.run(["git", "-C", repo, "check-ignore", "-q", "--", target],
                           capture_output=True, env=_ENV, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def ignored_link(where: str, entry: str, primary: str, timeout: "float | None" = None) -> bool:
    """True when `<where>/<entry>` is a symlink whose target is gitignored: by `<where>`'s own
    rules when the target resolves inside `<where>`, by `<primary>`'s otherwise.

    Anything else is work: not a link, a link whose directory or whose target's directory is
    missing, and any answer but "ignored" (1, or 128 for a path outside the repository asked).
    The workspace's "not ignored" is final: falling back to the main checkout would undo the
    rule for every link under an ignored worktree directory."""
    link = os.path.join(where, entry)
    if not os.path.islink(link):
        return False
    raw = os.readlink(link)
    here = os.path.dirname(link)
    target = os.path.normpath(os.path.join(here, raw))
    if not (os.path.isdir(here) and os.path.isdir(os.path.dirname(target))):
        return False          # a broken link is kept: classified dirty, never removed
    space, real = os.path.realpath(where), os.path.realpath(link)
    if _inside(real, space):
        return _ignored(space, real, timeout)
    return _ignored(primary, target, timeout)


def _inside(path: str, space: str) -> bool:
    """Whether `path` or one of its parents is the directory `space`, by identity, not by
    spelling: `realpath` keeps a case-variant spelling on a case-insensitive file system."""
    try:
        home = os.stat(space)
    except OSError:
        return False
    while True:
        try:
            if os.path.samestat(os.stat(path), home):
                return True
        except OSError:
            pass
        parent = os.path.dirname(path)
        if parent == path:
            return False
        path = parent
