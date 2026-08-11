"""Guards for the repo-tree write guard (Phase 187).

`pyproject.toml` defaults `-n auto`, and the one thing that makes a test suite unsafe
under xdist is a test that writes into the repo every worker is reading. `conftest.py`
patches the Python-level writers to make that a hard error. This module proves the patch
is *installed* rather than merely defined — a guard whose `pytest_configure` body was
deleted would leave every other test in the suite green, which is this project's own
definition of a vacuous claim.

Two halves, deliberately different in kind. The predicate is driven directly, both
directions. Then each patched API is driven END TO END against a real repo path, because
"the predicate is correct" and "the predicate is wired to `Path.write_text`" are separate
claims and only the second one is what stops the next collision.
"""

from __future__ import annotations

import builtins
import inspect
import os
import re
import shutil
import tempfile
from pathlib import Path

import pytest

from tests import conftest
from tests.conftest import REPO_ROOT, repo_tree_violation


# --------------------------------------------------------------------------------------
# The predicate
# --------------------------------------------------------------------------------------


def test_a_repo_path_is_a_violation():
    assert repo_tree_violation(REPO_ROOT / "docs" / "probe.md") == "docs/probe.md"
    assert repo_tree_violation(str(REPO_ROOT / "README.md")) == "README.md"


def test_a_tmp_path_is_not(tmp_path):
    assert repo_tree_violation(tmp_path / "anything.md") is None
    assert repo_tree_violation(tmp_path / "deep" / "nest" / "f.txt") is None


def test_a_path_outside_the_repo_is_not():
    assert repo_tree_violation(Path("/etc/hosts")) is None


def test_the_allowlist_is_exactly_the_tool_owned_caches():
    """Pinned, because widening it is the cheapest way to disarm this guard.

    All three are tool-owned: `__pycache__` is CPython's, `.pytest_cache` is pytest's, and
    `pytest-cache-files-*` is the transient directory
    `_pytest/cacheprovider.py::_ensure_cache_dir_and_supporting_files` builds AT THE
    ROOTDIR before renaming it into place. A fourth entry needs a reason in the same diff.
    """
    assert conftest._WRITE_ALLOWED == (
        "__pycache__", ".pytest_cache", "pytest-cache-files-*")
    assert repo_tree_violation(REPO_ROOT / "tests" / "__pycache__" / "x.pyc") is None
    assert repo_tree_violation(REPO_ROOT / ".pytest_cache" / "v" / "cache") is None
    assert repo_tree_violation(REPO_ROOT / "pytest-cache-files-ab12" / "README.md") is None
    # …and the glob is anchored to a whole component, not a prefix of one.
    assert repo_tree_violation(REPO_ROOT / "docs" / "pytest-cache-files.md") is not None
    # …and the allowlist is a path-component test, not a substring one: a file merely
    # NAMED like the cache dir is still a repo write.
    assert repo_tree_violation(REPO_ROOT / "docs" / "__pycache__.md") == \
        "docs/__pycache__.md"


def test_a_traversal_out_of_the_repo_is_not_a_violation():
    """`normpath` before the containment test, so `repo/../elsewhere` is not claimed."""
    assert repo_tree_violation(REPO_ROOT / ".." / "not-sysop" / "f.md") is None


def test_the_predicate_is_not_trivially_permissive():
    """The negative control for every `is None` assertion above."""
    assert repo_tree_violation(REPO_ROOT / "core" / "skills" / "x" / "SKILL.md") is not None


# --------------------------------------------------------------------------------------
# The wiring — one case per patched API, driven for real
# --------------------------------------------------------------------------------------

# EVERY PROBE BELOW TARGETS A PATH THAT DOES NOT EXIST.
#
# The first draft pointed the destructive cases at real content —
# `(REPO_ROOT / "README.md").unlink()` and `shutil.rmtree(REPO_ROOT / "docs")` — reasoning
# that the guard would stop them. It does, right up until it does not: the phase's own
# mutation battery disabled the guard (that is what a battery against a guard *is*), these
# two tests then ran, and README.md and the whole of docs/ were deleted from the working
# tree. A guard test whose failure mode is data loss is a worse defect than the one it
# guards.
#
# The guard refuses on the PATH, before calling through, so a nonexistent target proves
# exactly the same thing: `pytest.raises(AssertionError, match=...)` still separates "the
# guard fired" from "FileNotFoundError, because the guard is gone".

TARGET = REPO_ROOT / "docs" / "_write_guard_probe.md"
DEAD_FILE = REPO_ROOT / "docs" / "_write_guard_absent.md"
DEAD_DIR = REPO_ROOT / "_write_guard_absent_dir"
_TMP_PROBE_PREFIX = "_write_guard_tmp"


@pytest.fixture(autouse=True)
def _no_probe_residue():
    """Remove any probe artefact, before and after every test in this module.

    A guard test whose subject is disabled — which is what a mutation battery against this
    guard does — writes its probe for real. The assertion catches it, but the file stays,
    and it then reads as a shipped defect to every other scanner in the suite and as an
    inexplicable false kill to the battery. Cleaned with `os.*`, which this guard
    deliberately does not patch, so the cleanup cannot be blocked by the thing it is
    cleaning up after.
    """
    def sweep():
        # The globbed arm is for probes whose name the test cannot know — `tempfile`
        # picks a random suffix, and two such files were left in the repo root before it
        # existed.
        dynamic = list(REPO_ROOT.glob(_TMP_PROBE_PREFIX + "*"))
        for path in (TARGET, DEAD_FILE, REPO_ROOT / "docs" / "_write_guard_dir", DEAD_DIR,
                     REPO_ROOT / "_write_guard_link", *dynamic):
            try:
                if path.is_dir():
                    os.rmdir(path)
                elif path.exists() or path.is_symlink():
                    os.remove(path)
            except OSError:
                pass
    sweep()
    yield
    sweep()


def _assert_blocked(fn):
    with pytest.raises(AssertionError, match="wrote into the Sysop repo tree"):
        fn()
    assert not TARGET.exists(), (
        "the guard raised but the write went through anyway — it must refuse BEFORE "
        "calling the original"
    )


def test_write_text_into_the_repo_is_blocked():
    _assert_blocked(lambda: TARGET.write_text("x", encoding="utf-8"))


def test_write_bytes_into_the_repo_is_blocked():
    _assert_blocked(lambda: TARGET.write_bytes(b"x"))


def test_touch_into_the_repo_is_blocked():
    _assert_blocked(TARGET.touch)


def test_mkdir_into_the_repo_is_blocked():
    _assert_blocked((REPO_ROOT / "docs" / "_write_guard_dir").mkdir)


def test_unlink_in_the_repo_is_blocked():
    """Deleting a file is the same shared-state hazard, in reverse."""
    _assert_blocked(DEAD_FILE.unlink)


def test_rmdir_in_the_repo_is_blocked():
    _assert_blocked(DEAD_DIR.rmdir)


def test_rename_within_the_repo_is_blocked():
    _assert_blocked(lambda: DEAD_FILE.rename(TARGET))


def test_replace_within_the_repo_is_blocked():
    _assert_blocked(lambda: DEAD_FILE.replace(TARGET))


def test_symlink_to_inside_the_repo_is_blocked():
    _assert_blocked(lambda: TARGET.symlink_to(DEAD_FILE))


def test_hardlink_to_inside_the_repo_is_blocked():
    _assert_blocked(lambda: TARGET.hardlink_to(DEAD_FILE))


def test_builtins_open_for_write_into_the_repo_is_blocked():
    _assert_blocked(lambda: builtins.open(TARGET, "w"))


def test_path_open_for_write_into_the_repo_is_blocked():
    _assert_blocked(lambda: TARGET.open("w"))


@pytest.mark.parametrize("mode", ["w", "a", "x", "r+", "wb", "ab"])
def test_every_write_mode_counts_as_a_write(mode):
    """`a` and `+` are writes too, and appending to a tracked file is the same
    shared-state hazard as truncating it. Narrowing the flag set to `("w", "x")` survived
    this phase's battery until these cases existed."""
    _assert_blocked(lambda: builtins.open(TARGET, mode))


@pytest.mark.parametrize("mode", ["r", "rb"])
def test_read_modes_are_not_writes(mode):
    """The control: a guard that reddened on every open would be deleted, not fixed."""
    with builtins.open(REPO_ROOT / "README.md", mode) as fh:
        assert fh.read()


def test_a_relative_path_is_resolved_against_the_cwd(monkeypatch):
    """A test that `chdir`s into the repo and writes a bare filename is writing into the
    repo. Returning None for any non-absolute path survived this phase's battery.
    """
    monkeypatch.chdir(REPO_ROOT / "docs")
    assert repo_tree_violation("_write_guard_probe.md") == "docs/_write_guard_probe.md"
    _assert_blocked(lambda: Path("_write_guard_probe.md").write_text("x"))


def test_shutil_rmtree_of_a_repo_dir_is_blocked():
    _assert_blocked(lambda: shutil.rmtree(DEAD_DIR))


def test_shutil_copytree_into_the_repo_is_blocked(tmp_path):
    src = tmp_path / "srctree"
    src.mkdir()
    _assert_blocked(lambda: shutil.copytree(src, DEAD_DIR))


def test_shutil_copy_into_the_repo_is_blocked(tmp_path):
    src = tmp_path / "src.md"
    src.write_text("x", encoding="utf-8")
    _assert_blocked(lambda: shutil.copy(src, TARGET))


def test_shutil_move_into_the_repo_is_blocked(tmp_path):
    src = tmp_path / "src2.md"
    src.write_text("x", encoding="utf-8")
    _assert_blocked(lambda: shutil.move(str(src), str(TARGET)))
    assert src.is_file(), "the guard refused but the move happened anyway"


# --------------------------------------------------------------------------------------
# Over-strictness — the direction that gets a correct guard deleted instead of fixed
# --------------------------------------------------------------------------------------


def test_reading_from_the_repo_is_untouched():
    assert (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    with builtins.open(REPO_ROOT / "README.md", encoding="utf-8") as fh:
        assert fh.read()


def test_every_patched_api_still_works_under_tmp_path(tmp_path):
    """The whole suite writes through these; a guard that broke one would be found by
    3,000 other tests, but stating it here means the failure names the guard."""
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / "b.bin").write_bytes(b"x")
    (tmp_path / "c").mkdir()
    (tmp_path / "d.md").touch()
    (tmp_path / "d.md").unlink()
    with builtins.open(tmp_path / "e.md", "w") as fh:
        fh.write("x")
    with (tmp_path / "f.md").open("w") as fh:
        fh.write("x")
    shutil.copy(tmp_path / "a.md", tmp_path / "g.md")
    shutil.move(str(tmp_path / "g.md"), str(tmp_path / "h.md"))
    shutil.rmtree(tmp_path / "c")
    assert not (tmp_path / "c").exists()


def test_the_parallel_default_and_its_dependency_ship_together():
    """`-n auto` in `pyproject.toml` and `pytest-xdist` in `requirements-dev.txt` are one
    fact written in two files.

    One direction is loud: drop the pin and pytest exits 4 on `unrecognized arguments:
    -n`, in CI, on the first fresh install. The other is silent — drop `-n auto` and the
    suite still passes, four times slower, while this whole module's stated reason for
    existing goes stale with nothing reddening. Both are pinned so either edit has to be
    a deliberate one.
    """
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    addopts = re.search(r'(?m)^addopts\s*=\s*"([^"]*)"', pyproject)
    assert addopts, "pyproject.toml no longer sets addopts at all"
    assert "-n auto" in addopts.group(1), (
        "the suite no longer defaults to parallel. If that is deliberate, the "
        "parallel-safety rationale in tests/conftest.py and tests/README.md is now "
        "describing a suite that does not exist and needs rewriting in the same commit")
    reqs = (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert re.search(r"(?m)^pytest-xdist==", reqs), (
        "`-n auto` is in addopts but pytest-xdist is not pinned in requirements-dev.txt "
        "— pytest exits 4 with `unrecognized arguments: -n` on a fresh install, which is "
        "what CI does on every run")


def test_that_pairing_guard_is_not_vacuous():
    """Both halves, driven against text that fails them."""
    assert not re.search(r'(?m)^addopts\s*=\s*"([^"]*)"', 'addopts = -ra\n')
    assert "-n auto" not in "-ra --strict-markers"
    assert not re.search(r"(?m)^pytest-xdist==", "pytest==9.0.3\npyyaml==6.0.2\n")
    assert re.search(r"(?m)^pytest-xdist==", "pytest-xdist==3.8.0\n")


def test_the_cacheprovider_writers_are_all_allowed():
    """Driven from pytest's own sequence rather than from what happened to fire: mkdir the
    rootdir, build `pytest-cache-files-<x>/` beside it, chmod it, `open(..., "x")` three
    files inside, rename it to `.pytest_cache`. The first cut allowed the first and last
    of those and rejected the middle — green under `-p no:cacheprovider`, red in CI.
    """
    staging = REPO_ROOT / "pytest-cache-files-guardtest"
    for path in (staging, staging / "README.md", staging / ".gitignore",
                 staging / "CACHEDIR.TAG", REPO_ROOT / ".pytest_cache"):
        assert repo_tree_violation(path) is None, (
            f"{path} would break pytest's own cache setup")


def test_mkdir_on_an_existing_directory_is_not_a_write():
    """pytest's cacheprovider does exactly this to the rootdir."""
    REPO_ROOT.mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / "docs").mkdir(parents=True, exist_ok=True)
    assert (REPO_ROOT / "docs").is_dir()


def test_mkdir_of_a_NEW_repo_directory_is_still_a_write():
    """The control: the exemption is scoped to `is_dir()`, not to `mkdir`."""
    _assert_blocked(DEAD_DIR.mkdir)
    _assert_blocked(lambda: DEAD_DIR.mkdir(parents=True, exist_ok=True))
    assert not DEAD_DIR.exists()


def test_the_exemption_is_scoped_to_mkdir_and_to_existing_directories():
    """THE PREDICATE IS CALLED DIRECTLY, AND THAT IS THE WHOLE POINT OF THIS TEST.

    The first version of it executed `shutil.rmtree(REPO_ROOT)` inside a
    `pytest.raises(AssertionError)`, on the reasoning that the guard would stop it — the
    exact reasoning the comment block above exists to refute, written by the same author
    on the same day, one screen below the paragraph refuting it. It then ran under a
    mutation battery, which is a run WITH THE GUARD DISABLED BY CONSTRUCTION, and deleted
    the entire working tree.

    A guard's own tests run unguarded during any battery against it. So the destructive
    case is asserted on the predicate, never executed: `_creates_nothing` is a pure
    function and answering "does it exempt an rmtree of the root" needs no rmtree.
    """
    assert conftest._creates_nothing("mkdir", REPO_ROOT) is True
    assert conftest._creates_nothing("rmdir", REPO_ROOT) is False
    assert conftest._creates_nothing("unlink", REPO_ROOT) is False
    assert conftest._creates_nothing("touch", REPO_ROOT / "README.md") is False
    assert conftest._creates_nothing("mkdir", DEAD_DIR) is False
    # …and `shutil.rmtree` never consults it at all, so no name can exempt a tree delete.
    assert "_creates_nothing" not in inspect.getsource(conftest._patch_shutil)
    assert repo_tree_violation(REPO_ROOT) == "."


# --------------------------------------------------------------------------------------
# The bypasses two independent reviewers reached the tree through. Each was a real write
# into this repo before the fix; each is driven at the API they used.
# --------------------------------------------------------------------------------------


def test_rename_INTO_the_repo_is_blocked(tmp_path):
    """The destination is the write. The guard checked `self` — the source — so a file
    moved from `tmp_path` into the repo landed for real, while `shutil.move`, the same
    operation, was checked on its destination all along."""
    src = tmp_path / "s.md"
    src.write_text("x", encoding="utf-8")
    _assert_blocked(lambda: src.rename(TARGET))
    assert src.is_file(), "the guard refused but the rename happened anyway"


def test_replace_INTO_the_repo_is_blocked(tmp_path):
    """`write to tmp, then replace` is this repo's own shipped atomic-write idiom."""
    src = tmp_path / "s2.md"
    src.write_text("x", encoding="utf-8")
    _assert_blocked(lambda: src.replace(TARGET))
    assert src.is_file()


@pytest.mark.parametrize("call", [
    lambda: shutil.rmtree(path=DEAD_DIR),
    lambda: shutil.copytree(src=str(DEAD_DIR), dst=str(TARGET)),
], ids=["rmtree", "copytree"])
def test_the_shutil_wrappers_are_not_bypassed_by_keyword_arguments(call):
    """Every one of these parameters is positional-or-keyword in CPython, and a reviewer
    reached the real `shutil.rmtree` by naming it."""
    _assert_blocked(call)


@pytest.mark.parametrize("call", [
    lambda: os.mkdir(DEAD_DIR),
    lambda: os.makedirs(DEAD_DIR),
    lambda: os.remove(DEAD_FILE),
    lambda: os.rmdir(DEAD_DIR),
    lambda: os.rename(str(DEAD_FILE), str(TARGET)),
    lambda: os.replace(str(DEAD_FILE), str(TARGET)),
    lambda: os.symlink(str(DEAD_FILE), str(TARGET)),
], ids=["mkdir", "makedirs", "remove", "rmdir", "rename", "replace", "symlink"])
def test_the_os_level_writers_are_blocked(call):
    _assert_blocked(call)


def test_os_open_for_write_is_blocked():
    """`os.open` is what `tempfile` writes through, which is how one reviewer got in."""
    _assert_blocked(lambda: os.open(TARGET, os.O_WRONLY | os.O_CREAT))


def test_tempfile_into_the_repo_is_blocked():
    """`prefix=` and `delete=True` are not decoration. With the guard disabled — which is
    what a battery against it does — this call creates a real file whose name is random,
    so the residue sweep below cannot name it: two `tmp*` files were left in the repo root
    exactly that way. The prefix makes them sweepable and `delete=True` means the healthy
    path leaves nothing even if the guard is gone."""
    _assert_blocked(lambda: tempfile.NamedTemporaryFile(
        dir=REPO_ROOT, prefix=_TMP_PROBE_PREFIX, delete=True))


def test_os_open_for_READ_is_untouched():
    """The control — the guard must not intercept every read in the process."""
    fd = os.open(REPO_ROOT / "README.md", os.O_RDONLY)
    try:
        assert os.read(fd, 4)
    finally:
        os.close(fd)


def test_a_dir_fd_relative_call_is_not_attributed_to_this_repo(tmp_path):
    """`shutil.rmtree` walks with `os.unlink(entry.name, dir_fd=topfd)`. Those arrive as
    bare basenames; resolving them against the CWD blamed this repo 64 times against one
    true positive. `dir_fd` is the discriminator, so the whole `os` layer is covered
    rather than exempt."""
    victim = tmp_path / "sub"
    victim.mkdir()
    (victim / "f.md").write_text("x", encoding="utf-8")
    shutil.rmtree(victim)          # exercises the dir_fd walk for real
    assert not victim.exists()


def test_a_symlink_pointing_INTO_the_repo_is_still_a_violation(tmp_path):
    """`normpath` cannot see through a link. A reviewer wrote into this tree through one
    while the predicate returned None."""
    link = tmp_path / "into_repo"
    link.symlink_to(REPO_ROOT)
    assert repo_tree_violation(link / "zz.md") == "zz.md"
    _assert_blocked(lambda: (link / "docs" / "_write_guard_probe.md").write_text("x"))


def test_a_symlink_pointing_OUT_of_the_repo_is_not_a_violation(tmp_path):
    """The converse, and the over-strictness direction.

    A test can no longer create this shape — `os.symlink` into the repo is itself a
    violation now — but a developer's tree carries them: `.venv/bin/python3` is one, and a
    linked worktree is another. So the case is asserted where it actually occurs, and the
    tmp-side half of the chain is built where a test may build it.
    """
    venv_python = REPO_ROOT / ".venv" / "bin" / "python3"
    if venv_python.is_symlink():
        assert repo_tree_violation(venv_python) is None, (
            "a path under this root whose realpath is outside it was called a violation")
    else:
        pytest.skip("no .venv symlink in this checkout (CI installs to the runner python)")


def test_the_predicate_resolves_a_chain_rather_than_normalising_it(tmp_path):
    """`normpath` collapses `..` textually and cannot see a link at all. Both halves are
    driven entirely under `tmp_path`, so this holds on a checkout with no `.venv`."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    hop = tmp_path / "hop"
    hop.symlink_to(outside)
    assert repo_tree_violation(hop / "f.md") is None
    # …and a two-hop chain landing back inside the repo is still caught.
    into = tmp_path / "a" / "b"
    into.parent.mkdir()
    into.symlink_to(REPO_ROOT / "docs")
    assert repo_tree_violation(into / "x.md") == "docs/x.md"


def test_the_patched_writer_set_is_pinned():
    """The patch loop is data-driven, so a name silently dropped from it is a hole no
    other test can see — the tuple is the population, and an unpinned population is the
    vacuity class rule 1 names under *where it looks*. Every name here is also driven end
    to end above; the pin is what catches a deletion of BOTH at once.
    """
    assert conftest._PATCHED_PATH_WRITERS == (
        "write_text", "write_bytes", "mkdir", "touch", "unlink", "rmdir",
        "rename", "replace", "symlink_to", "hardlink_to",
    )
    assert conftest._PATCHED_SHUTIL_DESTS == (
        "copy", "copy2", "copyfile", "copytree", "move",
    )
    assert conftest._OS_WRITERS_ARG0 == (
        "mkdir", "makedirs", "remove", "unlink", "rmdir", "truncate")
    assert conftest._OS_WRITERS_ARG1 == ("rename", "replace", "symlink", "link")
    assert set(conftest._SHUTIL_DEST_KWARG) == {
        "rmtree", *conftest._PATCHED_SHUTIL_DESTS}
    assert conftest._PATH_METHODS_WRITING_AT_THE_ARGUMENT == (
        "rename", "replace", "symlink_to", "hardlink_to")


def test_the_suite_leaves_no_probe_behind():
    """The class this guard exists for, asserted as a fact about the tree.

    `docs/_untracked_guard_probe.md` was the real one — planted by
    `test_venv_command_word.py` and deleted in a `finally`, which is safe serially and a
    race under `-n`. Its fixture now lives in `tmp_path`.
    """
    assert not (REPO_ROOT / "docs" / "_untracked_guard_probe.md").exists()
    assert not TARGET.exists()
    # The probes above must never have existed, or they were not testing the guard.
    assert not DEAD_FILE.exists() and not DEAD_DIR.exists()
    # …and the two paths the first draft aimed at are still here.
    assert (REPO_ROOT / "README.md").is_file() and (REPO_ROOT / "docs").is_dir()
