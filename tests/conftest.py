"""Sysop test suite shared fixtures.

Intentionally minimal — Sysop has no DB, no app process. Most tests
exercise pure functions or subprocess calls mocked at the boundary.
"""
import builtins
import fnmatch
import os
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_REPO_REAL = Path(os.path.realpath(REPO_ROOT))

for _var in (
    "SLACK_WEBHOOK_URL",
    "PIPELINE_SLACK_WEBHOOK_URL",
    "PAGERDUTY_ROUTING_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
):
    os.environ.pop(_var, None)


def pytest_collection_modifyitems(config, items):
    skip_node = pytest.mark.skip(reason="npx/eslint not on PATH")
    skip_pip_audit = pytest.mark.skip(reason="pip-audit not on PATH")
    has_node = shutil.which("npx") is not None
    has_pip_audit = shutil.which("pip-audit") is not None
    for item in items:
        if item.get_closest_marker("requires_node") and not has_node:
            item.add_marker(skip_node)
        if item.get_closest_marker("requires_pip_audit") and not has_pip_audit:
            item.add_marker(skip_pip_audit)


# --------------------------------------------------------------------------------------
# The repo-tree write guard (Phase 187).
#
# `pyproject.toml` defaults `-n auto`. Under xdist, a test that writes into THIS repo is
# visible to every other worker for as long as the file exists, so a write-then-delete is
# a race rather than a private act. The suite had exactly one — a probe file planted in
# `docs/` to prove `git ls-files --others` was in scope — and a sibling worker scanning
# the shipped file set read it and reported it as a shipped defect. It fired in one of
# two `-n auto` runs, which is why the fix is a guard and not a re-run.
#
# THE POPULATION IS DERIVED, NOT ASSUMED. A line-scoped grep is useless here: `tests/`
# has 818 `write_text`/`mkdir`/`touch` call sites and 51 modules that both write and
# reference `REPO_ROOT`, but `p = REPO_ROOT / "x"` on one line and `p.write_text(...)` on
# the next is invisible to any single-line probe. The real number came from instrumenting
# the writers and running the whole suite: **one** test wrote into this tree, everything
# else wrote under `tmp_path`. This guard makes that one the last one.
#
# WHAT IT COVERS, and what it does not. The `pathlib.Path` writers, `builtins.open` and
# `Path.open` in write modes, the `shutil` copy/move/rmtree family, and the `os`-level
# writers (`mkdir`, `makedirs`, `open`, `remove`, `unlink`, `rmdir`, `truncate`, `rename`,
# `replace`, `symlink`, `link`). The first cut patched only the first three groups on the
# reasoning that they are "the APIs a test author actually calls"; **two independent
# reviewers then reached this tree through `os.mkdir`, `os.fdopen` on an `os.open` fd, and
# `tempfile.NamedTemporaryFile(dir=REPO_ROOT)`**, and a third route moved a file in with
# `Path.rename`, whose destination nothing checked. The one real reason not to patch the
# `os` layer was never the layer: `shutil.rmtree` walks with
# `os.unlink(entry.name, dir_fd=topfd)`, so those calls arrive as bare basenames that
# CWD-relative resolution mis-attributes here — 64 false positives against one true one
# when it was first instrumented. `dir_fd` is the actual discriminator, so it is tested
# for directly and the rest of the layer is covered.
#
# STILL OUT OF REACH, and stated rather than implied: a **subprocess** that writes here.
# The suite drives `install.sh`, `git` and `bash` in thousands of real subprocesses; this
# guard sees none of their writes. It bounds what a test does in-process, which is where
# every instance the derivation found actually lived.
#
# There is NO opt-out marker. After the fix the population is zero, and an escape hatch is
# the cheapest way to silence a guard — a future test that genuinely needs to write here
# should be a deliberate edit to this file, made by someone who has read this comment.
# --------------------------------------------------------------------------------------

# Tool-owned cache artefacts at the rootdir. None is test-authored state another worker
# reads, and every other path under REPO_ROOT is a violation.
#
# DERIVED FROM PYTEST'S OWN SOURCE, not from what happened to fire. The first cut listed
# the two obvious names, went green locally under `-p no:cacheprovider` — which is not how
# CI runs pytest — and CI then rejected pytest's cache setup and took the whole suite down.
# `_pytest/cacheprovider.py::_ensure_cache_dir_and_supporting_files` is the entire writer:
# it `mkdir`s the cache dir's PARENT (the rootdir itself, handled by `_creates_nothing`),
# then builds the cache in a `TemporaryDirectory(prefix="pytest-cache-files-",
# dir=<rootdir>)` — a `chmod` plus three `open(..., "x")` — and `rename`s that into place.
# The transient prefix is as much a part of pytest's contract as `.pytest_cache` is.
#
# Matched per PATH COMPONENT with `fnmatch`, so `docs/__pycache__.md` — a file merely
# NAMED like a cache dir — is still a violation.
_WRITE_ALLOWED = ("__pycache__", ".pytest_cache", "pytest-cache-files-*")


def repo_tree_violation(target) -> str | None:
    """The predicate, exposed so `test_repo_write_guard.py` can drive it directly.

    Returns the repo-relative path when `target` is a write into this tree that another
    xdist worker could observe, and None otherwise.
    """
    try:
        path = Path(target)
        if not path.is_absolute():
            path = Path.cwd() / path
        # `realpath`, not `normpath`. A symlink is a live bypass in BOTH directions and a
        # round found both: a link under `tmp_path` pointing AT this repo let a write
        # through with the predicate returning None, and a link inside the repo pointing
        # OUT was flagged as a violation it is not. `realpath` resolves the whole chain,
        # tolerates a path that does not exist yet, and answers the question the guard is
        # actually asking — which bytes on disk does this touch.
        path = Path(os.path.realpath(path))
        rel = path.relative_to(_REPO_REAL)
    except (ValueError, OSError, TypeError):
        return None
    # Matched at ANY depth on purpose: a `__pycache__` under `docs/` is still CPython's.
    if any(fnmatch.fnmatchcase(part, pat)
           for part in rel.parts for pat in _WRITE_ALLOWED):
        return None
    return str(rel)


_MESSAGE = (
    "test wrote into the Sysop repo tree at {rel!r}.\n"
    "The suite runs under `-n auto`, so this file is visible to every other worker "
    "for as long as it exists — a write-then-delete is a race, not a private act, "
    "and it is also visible to any concurrent session sharing this clone.\n"
    "Write under `tmp_path`. If the test needs a real git repo, build one in "
    "`tmp_path` with the git discovery vars stripped "
    "(`tests/test_cut_release_gate.py::_hermetic_env` is the pattern).\n"
    "See tests/conftest.py -- the repo-tree write guard."
)


def _guard(rel: str) -> None:
    raise AssertionError(_MESSAGE.format(rel=rel))


def _creates_nothing(name: str, target: Path) -> bool:
    """True when this call cannot bring a new path into existence.

    ONE CASE, and it is not a convenience. `mkdir` on a directory that already exists
    either no-ops (`exist_ok=True`) or raises `FileExistsError` — it can never create
    anything, so it is not a write another worker could observe. `mkdir(parents=True)`
    walks up, and **pytest's own cacheprovider calls
    `self._cachedir.parent.mkdir(parents=True, exist_ok=True)` on the rootdir** — the repo
    root itself. Without this the guard rejects pytest's cache setup and takes the suite
    down, which is what it did in CI while every local run was green.

    Deliberately not generalised to `touch`, which updates mtime on an existing file and
    IS a write; and deliberately not written as "the repo root is exempt", which would let
    a tree deletion through.
    """
    return name == "mkdir" and target.is_dir()


# `rename`/`replace`/`symlink_to`/`hardlink_to` write at their ARGUMENT, not at `self`.
# A round moved a file from `tmp_path` INTO the repo with `(tmp/"s").rename(REPO_ROOT/"x")`
# and the guard never looked: it checked the source. `shutil.move` — the same operation —
# was checked on its destination all along, so the guard was internally inconsistent, and
# tmp-write-then-`replace` is this repo's own shipped atomic-write idiom
# (`archive_review_tasks.py`, `backfill_completed_dates.py`).
_PATH_METHODS_WRITING_AT_THE_ARGUMENT = ("rename", "replace", "symlink_to", "hardlink_to")


def _patch_path_method(name: str) -> None:
    original = getattr(Path, name)
    checks_arg = name in _PATH_METHODS_WRITING_AT_THE_ARGUMENT

    def wrapper(self, *args, **kwargs):
        rel = repo_tree_violation(self)
        if rel is not None and not _creates_nothing(name, self):
            _guard(rel)
        if checks_arg and args:
            # `symlink_to`/`hardlink_to` name the TARGET being pointed at, which is a read;
            # the path being created is `self`, already checked above. `rename`/`replace`
            # name the destination, which is the write.
            if name in ("rename", "replace"):
                dest = repo_tree_violation(args[0])
                if dest is not None:
                    _guard(dest)
        return original(self, *args, **kwargs)

    wrapper.__name__ = name
    setattr(Path, name, wrapper)


# Every one of these parameters is positional-OR-keyword in CPython, so a call written
# `shutil.rmtree(path=...)` slipped past a wrapper that only read `args[argidx]`. Found by
# a round, which reached the real `shutil.rmtree` that way.
_SHUTIL_DEST_KWARG = {"rmtree": "path", "copy": "dst", "copy2": "dst",
                      "copyfile": "dst", "copytree": "dst", "move": "dst"}


def _patch_shutil(name: str, argidx: int) -> None:
    original = getattr(shutil, name)
    kwarg = _SHUTIL_DEST_KWARG[name]

    def wrapper(*args, **kwargs):
        target = args[argidx] if len(args) > argidx else kwargs.get(kwarg)
        if target is not None:
            rel = repo_tree_violation(target)
            if rel is not None:
                _guard(rel)
        return original(*args, **kwargs)

    wrapper.__name__ = name
    setattr(shutil, name, wrapper)


# The os-level writers. NOT patched before, on a justification that only ever covered
# `os.unlink`/`os.rmdir`: `shutil.rmtree` walks with `os.unlink(entry.name, dir_fd=topfd)`,
# so those arrive as bare basenames that CWD-relative resolution mis-attributes here.
# `dir_fd` is the actual discriminator, so it is tested for directly — and that leaves
# `os.mkdir`, `os.makedirs`, `os.open` (which is what `tempfile` writes through),
# `os.rename`, `os.replace`, `os.symlink` and `os.link` covered rather than exempt. Two
# independent lenses reached the tree through three of them.
_OS_WRITERS_ARG0 = ("mkdir", "makedirs", "remove", "unlink", "rmdir", "truncate")
_OS_WRITERS_ARG1 = ("rename", "replace", "symlink", "link")


def _patch_os_writer(name: str, argidx: int) -> None:
    original = getattr(os, name, None)
    if original is None:  # pragma: no cover - platform-dependent
        return

    def wrapper(*args, **kwargs):
        # A `dir_fd`-relative call is `shutil.rmtree`'s internal walk, never a test.
        if kwargs.get("dir_fd") is None and len(args) > argidx:
            rel = repo_tree_violation(args[argidx])
            if rel is not None and not _creates_nothing(
                    "mkdir" if name in ("mkdir", "makedirs") else name, Path(args[argidx])):
                _guard(rel)
        return original(*args, **kwargs)

    wrapper.__name__ = name
    setattr(os, name, wrapper)


def _patch_os_open() -> None:
    """`os.open` with any create/write flag. This is the one `tempfile` writes through."""
    original = os.open
    write_flags = (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC)

    def wrapper(path, flags, *args, **kwargs):
        if kwargs.get("dir_fd") is None and flags & write_flags:
            rel = repo_tree_violation(path)
            if rel is not None:
                _guard(rel)
        return original(path, flags, *args, **kwargs)

    os.open = wrapper


def _is_write_mode(mode) -> bool:
    return any(flag in str(mode) for flag in ("w", "a", "x", "+"))


# The patched populations, named rather than inlined so `test_repo_write_guard.py` can pin
# them: the loops below are data-driven, and a name dropped from a literal inside a `for`
# is a hole no other test can see.
_PATCHED_PATH_WRITERS = (
    "write_text", "write_bytes", "mkdir", "touch", "unlink", "rmdir",
    "rename", "replace", "symlink_to", "hardlink_to",
)
# `shutil.rmtree` takes its target first; the copy/move family takes the DESTINATION
# second, which is the argument that writes.
_PATCHED_SHUTIL_DESTS = ("copy", "copy2", "copyfile", "copytree", "move")


def pytest_configure(config):
    for name in _PATCHED_PATH_WRITERS:
        if hasattr(Path, name):
            _patch_path_method(name)

    _patch_shutil("rmtree", 0)
    for name in _PATCHED_SHUTIL_DESTS:
        _patch_shutil(name, 1)

    for name in _OS_WRITERS_ARG0:
        _patch_os_writer(name, 0)
    for name in _OS_WRITERS_ARG1:
        _patch_os_writer(name, 1)
    _patch_os_open()

    builtins_open = builtins.open

    def open_wrapper(file, mode="r", *args, **kwargs):
        if _is_write_mode(mode):
            rel = repo_tree_violation(file)
            if rel is not None:
                _guard(rel)
        return builtins_open(file, mode, *args, **kwargs)

    builtins.open = open_wrapper

    path_open = Path.open

    def path_open_wrapper(self, mode="r", *args, **kwargs):
        if _is_write_mode(mode):
            rel = repo_tree_violation(self)
            if rel is not None:
                _guard(rel)
        return path_open(self, mode, *args, **kwargs)

    Path.open = path_open_wrapper
