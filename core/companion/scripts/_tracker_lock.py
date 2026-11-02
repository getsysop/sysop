"""_tracker_lock.py — the tracker write mutex, for the writers that run as Python.

Shared by `archive_review_tasks.py` (`review_tasks.md`) and the three Python writers of
`tasks/index.yml`: `close_index.py` (`/review-close` Step 4c), `backfill_completed_dates.py`
and `clear_user_action.py`. Not a command.

It is the SAME mutex `_git_lib.sh`'s `tracker_lock_acquire` takes for the bash writers
(`batch_work.sh`, `close_batch.sh`, `claim_task.sh --commit-claim` and `--release`), not a
Python one beside it. A mutex one writer skips is not a mutex: a writer that reads the file,
lets a rival's flip land, and then replaces the file from its first read loses that flip
with every command reporting success. Every detail below is there so a bash holder and a
Python one exclude each other:

  * the same path — `dirname(<locks dir>)/tracker.write.lock`, where the locks dir comes
    from `git rev-parse --git-common-dir`, as the bash writers derive it. `_git_lib.sh`
    § tracker_lock_acquire says why it is anchored on the LOCKS dir and not on a repo root:
    the two disagree under `--separate-git-dir` and inside a submodule, and a mutex whose
    holders compute different paths excludes nothing;
  * an exclusive create (`O_CREAT | O_EXCL`, the primitive behind bash's `set -C`), so
    whichever side creates the file first holds it;
  * the same four holder keys in the same order, so each side's refusal can print the
    other's holder, and bash's release — which unlinks only a file carrying its own
    `holder_pid` — never removes ours, nor ours its.

Where it differs from the bash helper, on purpose:

  * The caller names the directory it is resolved from (the anchor), not the CWD, so the
    mutex guards the file actually being written. In an install the anchor and the CWD
    are the same checkout.
  * Outside a git repository the locks dir falls back to `<anchor>/sysop/runtime/locks`,
    as `validate_tasks.py`'s resolver does, where the bash helper refuses on an empty
    locks dir. The bash writers cannot run outside a repository at all, so there is no
    rival to exclude there; refusing would only stop a write that is safe. Two Python
    writers given the same anchor still exclude each other.

Not broken automatically when stale, for `_git_lib.sh`'s reason: a PID check is unsound
across containers, and breaking a live lock is the lost update this exists to prevent. The
wait and the refusal text follow the bash helper's.
"""
from __future__ import annotations

import atexit
import contextlib
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from _log import _sanitize_log

LOCK_NAME = "tracker.write.lock"
DEFAULT_WAIT = 120


def git_discovery_env():
    """`os.environ` minus git's discovery vars (BeanRider ISSUE-0048).

    Duplicated from `validate_tasks.py` (which says why the copies are not shared):
    `GIT_DIR`/`GIT_WORK_TREE`/`GIT_COMMON_DIR`/`GIT_INDEX_FILE` take precedence over
    `git -C`, and git exports them into every hook, so leaving them inherited would
    resolve the mutex against whatever repository invoked the writer rather than the
    tracker's own.
    """
    return {
        k: v
        for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")
    }


def resolve_locks_dir(project_root):
    """The canonical `sysop/runtime/locks/` for `project_root`.

    Duplicated from `validate_tasks._resolve_canonical_locks_dir`: the MAIN repo's
    locks dir via `git rev-parse --git-common-dir`, so a call from any worktree agrees
    with the bash writers, and `project_root/sysop/runtime/locks` when git cannot
    answer (no repository, no `git`, a timeout).
    """
    project_root = Path(project_root)
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=git_discovery_env(),
        )
    except (FileNotFoundError, subprocess.SubprocessError, UnicodeDecodeError):
        return project_root / "sysop/runtime/locks"
    if result.returncode != 0:
        return project_root / "sysop/runtime/locks"
    raw = result.stdout.strip()
    if not raw:
        return project_root / "sysop/runtime/locks"
    common_dir = Path(raw)
    if not common_dir.is_absolute():
        common_dir = (project_root / common_dir).resolve()
    return common_dir.parent / "sysop/runtime/locks"


def lock_wait():
    """`SYSOP_TRACKER_LOCK_WAIT`, or the 120 s default."""
    raw = os.environ.get("SYSOP_TRACKER_LOCK_WAIT", "")
    if raw == "":
        return DEFAULT_WAIT
    # The bash helper's rule, character for character: ASCII digits only, at most six
    # of them, else the default. `int()` alone accepted ` 5`, `+3` and `-5`, which bash
    # reads as the default, and a 20-digit value waited forever in both.
    if re.fullmatch(r"[0-9]{1,6}", raw):
        return int(raw)
    print(
        f"Note: SYSOP_TRACKER_LOCK_WAIT={_sanitize_log(raw)!r} is not a whole number "
        f"of seconds from 0 to 999999; waiting the default {DEFAULT_WAIT}s.",
        file=sys.stderr,
    )
    return DEFAULT_WAIT


def _unlink_quietly(path):
    """Best-effort removal on an error path that is already reporting a cause."""
    try:
        os.unlink(path)
    except OSError:
        pass


def holder_text(lock_file):
    """The holder record, indented for display. Display only — never parsed."""
    try:
        with open(lock_file, "r", encoding="utf-8", errors="replace") as fh:
            body = fh.read()
    except OSError:
        return "     (unreadable)"
    return "\n".join("     " + _sanitize_log(ln) for ln in body.splitlines()) or "     (empty)"


def acquire(locks_dir, what, consequences="nothing was written", *, holder):
    """Take the tracker mutex; return its path, or None after printing why not.

    Python twin of `_git_lib.sh`'s `tracker_lock_acquire` — see the module docstring
    for what must stay identical and what differs. `holder` is the writer's script name,
    recorded on the `holder:` line as the bash helper records `${0##*/}`.
    """
    if not locks_dir:
        print("❌ Could not resolve the runtime directory — refusing to serialize "
              "the tracker write.", file=sys.stderr)
        print(f"   Refusing {what} — {consequences}.", file=sys.stderr)
        return None
    runtime_dir = os.path.dirname(str(locks_dir))
    lock_file = os.path.join(runtime_dir, LOCK_NAME)

    # A non-regular file here (a directory, a fifo) can never be acquired, and the
    # `rm -f` remedy below cannot remove a directory — so it gets its own diagnosis
    # with a remedy that works, as in the bash helper.
    if os.path.exists(lock_file) and not os.path.isfile(lock_file):
        print(f"❌ {lock_file} exists but is NOT a regular file.", file=sys.stderr)
        print(f"   Refusing {what} — {consequences}.", file=sys.stderr)
        print("   The tracker mutex must be a regular file. Inspect and remove it:",
              file=sys.stderr)
        print(f"     rm -rf {lock_file}      # -rf, not -f: -f alone cannot remove "
              f"a directory", file=sys.stderr)
        return None

    max_wait = lock_wait()
    try:
        os.makedirs(runtime_dir, exist_ok=True)
    except OSError:
        print(f"❌ Could not create {runtime_dir} — refusing to serialize the "
              f"tracker write.", file=sys.stderr)
        print(f"   Proceeding without the lock is what {what} must not do: two "
              f"concurrent writers of the same tracker file strand one of them. "
              f"{consequences}.", file=sys.stderr)
        return None

    waited = 0
    notified = False
    while True:
        try:
            fd = os.open(lock_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        except FileExistsError:
            # Discriminate before naming a cause: EEXIST on a path that does not EXIST
            # is a dangling symlink, so the write failed and no rival holds anything.
            # Reporting a rival there sends the operator hunting for a process that is
            # not there.
            if not os.path.exists(lock_file):
                _report_lock_write_failed(lock_file, runtime_dir, what, consequences)
                return None
        except OSError:
            _report_lock_write_failed(lock_file, runtime_dir, what, consequences)
            return None
        else:
            # We created it, so it is ours to remove if the record cannot be written —
            # an empty lock carries no `holder_pid` and no release would ever clear it.
            # `since:` is stamped at the attempt that succeeded, as the bash helper
            # stamps it, not when the wait began: it is what an operator reads to judge
            # whether a lock is stale.
            try:
                record = (
                    f"holder_pid: {os.getpid()}\n"
                    f"holder: {holder}\n"
                    f"what: {what}\n"
                    f"since: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
                ).encode("utf-8")
                with os.fdopen(fd, "wb") as fh:
                    fh.write(record)
            except BaseException as exc:
                _unlink_quietly(lock_file)
                if isinstance(exc, OSError):
                    _report_lock_write_failed(lock_file, runtime_dir, what, consequences)
                    return None
                raise
            return lock_file

        if waited >= max_wait:
            break
        if not notified and waited >= 3:
            print(f"⏳ Waiting for the tracker lock ({what})…", file=sys.stderr)
            print(holder_text(lock_file), file=sys.stderr)
            notified = True
        time.sleep(1)
        waited += 1

    # The phrase "locked by another Sysop process" is the one the bash helper prints,
    # and `tests/test_tracker_write_mutex.py` asserts it — keep it.
    print(f"❌ The tracker is locked by another Sysop process; waited {max_wait}s.",
          file=sys.stderr)
    print(f"   Refusing {what} — {consequences}.", file=sys.stderr)
    print("   The holder:", file=sys.stderr)
    print(holder_text(lock_file), file=sys.stderr)
    print("", file=sys.stderr)
    print("   If that process is gone, the lock is stale and safe to remove by hand.",
          file=sys.stderr)
    print("   CHECK FIRST — a claim's critical section includes a network 'git pull', "
          "so a", file=sys.stderr)
    print("   live holder on a slow remote can legitimately hold it this long. It is "
          "NOT", file=sys.stderr)
    print("   removed automatically, because breaking it blind is the same lost-update "
          "this", file=sys.stderr)
    print("   lock exists to prevent.", file=sys.stderr)
    print(f"     rm -f {lock_file}", file=sys.stderr)
    return None


def _report_lock_write_failed(lock_file, runtime_dir, what, consequences):
    print(f"❌ Could not write the tracker lock {lock_file} — no rival holder;",
          file=sys.stderr)
    print(f"   the write itself failed. Check that {runtime_dir} is writable and",
          file=sys.stderr)
    print("   that the filesystem is not full or read-only.", file=sys.stderr)
    print(f"   Refusing {what} — {consequences}.", file=sys.stderr)


def release(lock_file):
    """Unlink the mutex only if it is still OURS.

    The bash release's rule: a refusal invites a hand `rm -f`, a third process can then
    take the free path, and an unconditional unlink here would delete THAT holder's lock
    and leave it running unprotected. Read as bytes and matched as a whole line, so no
    decode can fail and `holder_pid: 12` never matches `holder_pid: 123`.
    """
    if not lock_file:
        return
    try:
        with open(lock_file, "rb") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return
    if f"holder_pid: {os.getpid()}".encode("ascii") in lines:
        _unlink_quietly(lock_file)


def _exit_on_signal(signum, _frame):
    # SystemExit, so every `finally` between here and the top of the stack runs —
    # including the one that releases the mutex — and so do `atexit` handlers. SIGINT
    # needs no handler: its default already raises KeyboardInterrupt.
    raise SystemExit(128 + signum)


class Hold:
    """A held mutex. `release()` is idempotent; a `with` block releases on the way out.

    SIGTERM and SIGHUP are turned into `SystemExit` while it is held: Python's default
    action for both terminates WITHOUT unwinding, so no `finally` would run and the
    mutex — which nothing breaks automatically — would wedge every later claim and
    close. SIGHUP is the terminal closing; the bash claim path leaked its mutex on
    exactly that signal until a reviewer measured it (see
    `tests/test_tracker_write_mutex.py` `TestTheSignalTrapsExist`). The previous
    handlers are restored on release, so an in-process caller is left as it was found.
    The release is also registered with `atexit`, for a writer whose body is top-level
    code that cannot sit inside a `with` and exits through `sys.exit` on its error paths.
    """

    def __init__(self, lock_file, previous):
        self.lock_file = lock_file
        self._previous = previous
        self._released = False
        atexit.register(self.release)

    def release(self):
        if self._released:
            return
        self._released = True
        try:
            release(self.lock_file)
        finally:
            _restore_handlers(self._previous)
            atexit.unregister(self.release)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.release()
        return False


def _install_handlers():
    previous = {}
    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            previous[sig] = signal.signal(sig, _exit_on_signal)
        except (ValueError, OSError):  # not the main thread: cannot install
            pass
    return previous


def _restore_handlers(previous):
    for sig, handler in previous.items():
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass


def hold(anchor_dir, what, consequences, *, holder):
    """Resolve the mutex from `anchor_dir` and take it: a `Hold`, or None after printing why not.

    The signal handlers are installed before the wait, so a SIGTERM during it unwinds as
    well; they are restored on a refusal.
    """
    locks_dir = resolve_locks_dir(anchor_dir)
    previous = _install_handlers()
    try:
        lock_file = acquire(str(locks_dir), what, consequences, holder=holder)
    except BaseException:
        _restore_handlers(previous)
        raise
    if lock_file is None:
        _restore_handlers(previous)
        return None
    return Hold(lock_file, previous)


@contextlib.contextmanager
def holding(anchor_dir, what, consequences, *, holder):
    """Hold the tracker mutex for the body of a `with`; exit 1 if refused."""
    held = hold(anchor_dir, what, consequences, holder=holder)
    if held is None:
        sys.exit(1)
    with held:
        yield held.lock_file
