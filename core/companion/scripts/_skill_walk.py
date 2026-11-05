"""The skills-tree walk the model-role scripts share (`check_skill_models.py`,
`resolve_skill_models.py`, `migrate_skill_model.py`).

Its own module so each script imports it fresh: an installer update keeps a consumer-modified
script as it is, and a walk that lived inside one of them would leave the other two on that
copy's walk.
"""
from __future__ import annotations

import errno
import os
import stat
from pathlib import Path


# A name that stat cannot resolve to anything: a dangling or looping link. `rglob` + `is_file`
# never yielded one, so neither does the walk.
_GONE = (errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.EBADF)


def walk_skill_files(root: Path) -> tuple[list[Path], list[Path]]:
    """``(files, unlistable)``: every markdown file under *root*, and every directory under
    it the walk could not list, each sorted.

    ``rglob`` skipped a directory it could not list without a word, so its files reached no
    read guard and no "unreadable" count (``Q-350``). A file whose directory can be listed
    but not searched cannot be stat'ed; ``rglob`` + ``is_file`` raised ``PermissionError``
    for it on Python 3.13 and older and dropped it on 3.14, so it is returned here and the
    caller's ``read_skill_text`` reports it. Otherwise the set is ``rglob("*.md")``'s:
    hidden names included, a directory link not followed, a file link followed, the match
    case-sensitive.
    """
    files: list[Path] = []
    unlistable: list[Path] = []

    def cannot_list(err: OSError) -> None:
        unlistable.append(Path(err.filename) if err.filename else root)

    for top, _subdirs, names in os.walk(root, onerror=cannot_list):
        for name in names:
            if not name.endswith(".md"):
                continue
            path = Path(top) / name
            try:
                mode = os.stat(path).st_mode
            except OSError as exc:
                if exc.errno not in _GONE:
                    files.append(path)
                continue
            if stat.S_ISREG(mode):
                files.append(path)
    return sorted(files), sorted(unlistable)


def iter_skill_files(root: Path) -> list[Path]:
    """Every markdown file under *root* in stable order (``walk_skill_files``' files)."""
    return walk_skill_files(root)[0]


def describe_skipped(files: list[Path], dirs: list[Path]) -> str:
    """The scope a scan states when it skipped something: ``1 unreadable file(s) skipped``,
    with ``; 2 unlistable directories skipped`` beside it when a directory could not be
    listed. A directory is never turned into a file count, which nothing could know."""
    parts = [f"{len(files)} unreadable file(s) skipped"] if files else []
    if dirs:
        noun = "directory" if len(dirs) == 1 else "directories"
        parts.append(f"{len(dirs)} unlistable {noun} skipped")
    return "; ".join(parts)
