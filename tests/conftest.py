"""Sysop test suite shared fixtures.

Intentionally minimal — Sysop has no DB, no app process. Most tests
exercise pure functions or subprocess calls mocked at the boundary.
"""
import builtins
import fnmatch
import hashlib
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


# --------------------------------------------------------------------------------------
# CI shard selection (Phase 279, `Q-465`).
#
# The merge gate was ONE job costing ~16 min per PR. Measured on job `102888048011` (of run
# `34482362099`): 949 s of the 981 s is `Run tests`, and the whole setup chain -- checkout,
# two `setup-python`, the dependency install -- is 28 s, so caching buys nothing and the
# test step is the entire bill. The suite is NOT core-bound: 7x the workers (14 local
# against 2 on `ubuntu-latest`) buys 1.94x, and on a small population more xdist workers is
# actively WORSE. So the lever is more MACHINES, not bigger ones, and `--durations` says the
# work divides: a long tail with no critical path.
#
# Measured after the fact on this repo's own first sharded runs: **351 s end to end against
# ~981 s, a 2.80x improvement, for about 25% more billed minutes.** Both figures are worse
# than this comment's first version predicted (4.7 min, +14%) -- the model was built from
# local per-test durations and could not see runner overhead or queueing.
#
# ITEM-LEVEL, NOT FILE-LEVEL, and that is not a detail. `pyproject.toml` keeps xdist's
# `--dist load` deliberately over `loadfile`, because putting a module's tests back on one
# worker MASKED the one real defect Phase 187 found. A file-level shard is `loadfile` at
# machine granularity and would reintroduce exactly that blindness, four ways.
#
# A HASH, AND THE FIRST VERSION OF THIS BLOCK CHOSE OTHERWISE ON A MEASUREMENT THAT WAS
# ANSWERING THE WRONG QUESTION. A round-robin over the sorted node ids balances better --
# measured on this suite's real ids and durations, 1.020 against the hash's 1.230 at four
# shards, because the slow tests cluster by module and a round-robin interleaves that
# clustering while a hash is a random draw against it. That was the whole argument, and it
# is worth about 5% of the critical path.
#
# **It is wrong, because a round-robin's owner depends on the SET.** `rank % count` is a
# position, so every id after a divergence shifts. The four shards are four machines and
# NOTHING anywhere compares their collections -- so if one of them collects a different set,
# the others do not find out. That is not hypothetical here: three modules carry a
# module-level `pytest.importorskip`, and a parametrized module can collect a different
# number of items on a different host (`test_python_floor_portability.py` parametrizes over
# the interpreters actually installed, which is why CI collects 6,652 where this machine
# collects 6,674). Simulated by dropping one 43-item module from one machine's collection:
#
#     round-robin    2,540 ids change owner     646 ids run on NO machine
#     blake2b hash           0 change owner       6 ids run on no machine
#
# 646 tests unrun, four green legs, a green aggregator, and no line of output anywhere that
# says so. That is precisely the failure this whole design exists to prevent, and the
# better-balanced strategy bought it. A hash's owner depends on nothing but the id, so a
# divergence costs exactly the ids that diverged and re-parents nothing.
#
# (A third shape -- hash the module, round-robin within it -- measured 1.029 and also
# re-parents nothing ACROSS modules. It is not taken because its guarantee is conditional:
# it still reshuffles WITHIN a module whose own item count differs between hosts, which is
# the one divergence this repo has actually observed. The hash's property has no condition
# on it, and an unconditional property is what a claim like the one below is allowed to rest
# on.)
#
# COLLECTION IS NOT FILTERED, ONLY SELECTION. Every shard still imports every test module,
# so an import-time error surfaces in ALL shards rather than only in whichever one happened
# to own it. Collection costs ~0.9 s here, so paying it four times is free.
#
# COVERAGE IS BY CONSTRUCTION. `shard_assignment` is TOTAL into `[0, count)` and each owner
# is a pure function of the id, so N shards partition any collection exactly -- no item in
# two, none in none -- provided the ids really are 0..N-1 and every one of them runs. The
# workflow buys both without a second number to keep in step: it reads `SYSOP_SHARD_ID` off
# `strategy.job-index` and `SYSOP_SHARD_COUNT` off `strategy.job-total`, both properties of
# the matrix itself, and the aggregator job named `pytest` requires every leg to have
# succeeded. The failure that shape exists to make impossible is a hand-written count
# disagreeing with the matrix width: four legs and a count of five runs a fifth of the suite
# on no machine at all, with every check green.
#
# Confirmed in CI rather than asserted: on the first sharded run all four legs collected
# 1663 items, 4 x 1663 = 6652, the whole collection.
# --------------------------------------------------------------------------------------

SHARD_ID_VAR = "SYSOP_SHARD_ID"
SHARD_COUNT_VAR = "SYSOP_SHARD_COUNT"

#: Every node id this session collected, BEFORE any shard filtering. Populated by
#: `pytest_collection_modifyitems` so `tests/test_ci_shard.py` can drive the partition
#: property over the suite's real population instead of over invented strings.
COLLECTED_NODEIDS: list[str] = []


class ShardConfigError(pytest.UsageError):
    """The shard environment is present but unusable.

    A `UsageError` rather than a bare `Exception`, and raised from `pytest_configure` rather
    than from the collection hook -- **both halves are needed and the first alone does
    nothing.** `pyproject.toml` defaults `-n auto`, so collection happens inside an xdist
    worker, and a `UsageError` raised there surfaces as a 49-line `INTERNALERROR` traceback
    with exit 3 and the message nowhere in the output. From `pytest_configure`, which the
    controller runs before spawning anything, pytest prints the reason as the first line and
    exits 4. Measured both ways under `-n auto`, which is how CI runs it.

    The gate fails closed either way -- 3 is as non-zero as 4 -- so this is diagnosis, not
    coverage. Worth having anyway: the reader is someone looking at one red leg out of four,
    and the one thing they need is which variable was wrong.
    """


def shard_assignment(all_nodeids, count: int) -> dict:
    """`{node id: owning shard}`. The partition primitive.

    TOTAL -- every id gets exactly one owner in `[0, count)` -- and each owner depends on
    **nothing but that id**. Not on the order the ids arrived in, and not on which other ids
    came with them. That second half is the whole reason this is a hash and not something
    better balanced; see the header above.
    """
    if count < 1:
        raise ValueError(f"shard count must be >= 1, got {count!r}")
    return {nodeid: _owner(nodeid, count) for nodeid in all_nodeids}


def _owner(nodeid: str, count: int) -> int:
    """`blake2b`, and specifically NOT `hash()`.

    CPython salts str hashing per process (PYTHONHASHSEED), xdist workers ARE separate
    processes, and across four MACHINES nothing compares two collections at all -- so a
    salted key is not a flaky run, it is ids that quietly go unrun. `blake2b` is stable
    across processes, interpreters and platforms.
    """
    return int.from_bytes(
        hashlib.blake2b(nodeid.encode("utf-8"), digest_size=8).digest(), "big"
    ) % count


def shard_config(environ):
    """`(shard_id, count)` when this run is a shard, `None` when it is not.

    FAILS CLOSED, and the asymmetry is deliberate. BOTH vars absent means "not sharded" --
    the local default and every developer run. A var that is PRESENT but empty or
    unparseable means a CI expression did not resolve, and the safe reading of THAT is not
    "run everything": four shards each running the whole suite is a silent 4x cost
    regression that no line of output would name and that would still be green. So it
    raises, and the shard goes red carrying the reason.
    """
    raw_id = environ.get(SHARD_ID_VAR)
    raw_count = environ.get(SHARD_COUNT_VAR)
    if raw_id is None and raw_count is None:
        return None
    if raw_id is None or raw_count is None:
        raise ShardConfigError(
            f"{SHARD_ID_VAR}={raw_id!r} {SHARD_COUNT_VAR}={raw_count!r}: set both or "
            "neither. One alone is a workflow that half-resolved."
        )
    try:
        shard, count = int(raw_id), int(raw_count)
    except (TypeError, ValueError):
        raise ShardConfigError(
            f"{SHARD_ID_VAR}={raw_id!r} {SHARD_COUNT_VAR}={raw_count!r}: both must be "
            "integers. An empty string here is an unresolved `${{ strategy.* }}`, which is "
            "the one case that must not read as 'no sharding requested'."
        ) from None
    if count < 1 or not 0 <= shard < count:
        raise ShardConfigError(
            f"{SHARD_ID_VAR}={shard} {SHARD_COUNT_VAR}={count}: need count >= 1 and "
            "0 <= id < count. Out of range means some slice of the suite runs nowhere."
        )
    return shard, count


def select_shard(items, shard: int, count: int):
    """Split `items` into `(kept, deselected)` for this shard. No pytest state touched."""
    owner = shard_assignment((it.nodeid for it in items), count)
    kept, dropped = [], []
    for item in items:
        (kept if owner[item.nodeid] == shard else dropped).append(item)
    return kept, dropped


def _unset_shard_env() -> None:
    """Drop the shard variables so no CHILD process inherits them. Called once collection
    is done, from every exit of the hook below.

    **This is a real defect found in CI, not a precaution.** Several tests in this suite
    spawn `python -m pytest` as a subprocess -- vacuity guards that collect another module
    and assert a floor, and the mirror skip-discipline checks that run a module against a
    sterilized tree. A child inherits its parent's environment, so under a sharded run each
    of those children silently became a SHARD of itself. One of them asserts a floor and
    went red on the first sharded CI run (`tests/test_index_writer_class.py` collected 4
    tests where it requires 17). **The loud one is the lucky case.** A child guard that
    asserts a property rather than a floor keeps passing over a quarter of its subject, and
    nothing anywhere reports that -- which is this change's whole failure class, reproduced
    inside the change itself.

    Fixed HERE rather than at the call sites, because the call sites are not a closed set:
    a future test that spawns pytest would inherit the same bug and nothing would remind its
    author. Collection always precedes the run phase, so by the time any test body executes
    the variables are already gone. Under xdist the workers are spawned before this runs, so
    they still receive the config they need; it is only the grandchildren that are cleaned.

    Unconditional on purpose -- popping an absent key is a no-op, and an early return that
    skipped the cleanup would leave exactly the `count=1` nightly leaking into its children.
    """
    for var in (SHARD_ID_VAR, SHARD_COUNT_VAR):
        os.environ.pop(var, None)


def pytest_report_header(config):
    """Name the slice in the run log. The workflow echoes the same two numbers before
    invoking pytest; this is the half that proves pytest agreed with them."""
    try:
        cfg = shard_config(os.environ)
    except ShardConfigError:
        # The collection hook raises this with its reason and stops the run. Pre-empting it
        # here would surface the same fault as an INTERNALERROR instead.
        return None
    if cfg is None:
        return None
    shard, count = cfg
    return f"sysop shard: {shard} of {count}"


def pytest_collection_modifyitems(config, items):
    # Recorded BEFORE anything below touches `items`, because the shard filter at the end
    # of this function removes most of them and `tests/test_ci_shard.py` needs the whole
    # population to check that the shards partition it.
    COLLECTED_NODEIDS[:] = [item.nodeid for item in items]

    skip_node = pytest.mark.skip(reason="npx/eslint not on PATH")
    skip_pip_audit = pytest.mark.skip(reason="pip-audit not on PATH")
    has_node = shutil.which("npx") is not None
    has_pip_audit = shutil.which("pip-audit") is not None
    for item in items:
        if item.get_closest_marker("requires_node") and not has_node:
            item.add_marker(skip_node)
        if item.get_closest_marker("requires_pip_audit") and not has_pip_audit:
            item.add_marker(skip_pip_audit)

    # Shard LAST. The markers above are applied to the whole collection first, so a shard
    # reports the same skip reasons it would have reported unsharded -- otherwise which
    # tests are "skipped: npx not on PATH" would depend on which slice drew them, and the
    # nightly's numbers would stop being comparable with a PR's.
    try:
        cfg = shard_config(os.environ)
        if cfg is None:
            return
        shard, count = cfg
        if count == 1:
            # The whole suite, and the path the nightly takes. Not merely an optimisation:
            # skipping the filter here means `count=1` is provably identical to no sharding
            # at all, rather than identical-looking.
            return
        kept, dropped = select_shard(items, shard, count)
        if dropped:
            config.hook.pytest_deselected(items=dropped)
        items[:] = kept
    finally:
        _unset_shard_env()


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
    # Validate the shard environment HERE, not at collection, and the difference is the
    # whole point. `pyproject.toml` defaults `-n auto` and the workflow runs bare `pytest`,
    # so collection happens inside an xdist WORKER -- and a `UsageError` raised there is
    # reported as a 49-line `INTERNALERROR` traceback with exit 3, with the message nowhere
    # in the output. Measured both ways. `pytest_configure` runs in the controller before
    # any worker is spawned, where pytest prints the reason as the first line and exits 4.
    #
    # The gate failed closed either way -- 3 is as non-zero as 4 -- so this buys diagnosis,
    # not coverage. It is worth a line anyway: the reader is someone looking at one red leg
    # out of four, and the one thing they need is which variable was wrong.
    shard_config(os.environ)

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
