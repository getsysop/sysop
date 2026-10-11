"""`archive_review_tasks.py` takes the tracker write mutex — `Q-398`, Phase 368.

The archiver rewrites `review_tasks.md` (and `review_tasks_archive.md`), and was
the one writer of the tracker that did not take the mutex `batch_work.sh` and
`close_batch.sh` take through `_git_lib.sh`'s `tracker_lock_acquire`. These tests
hold it to being the SAME mutex — a bash holder stops the archiver, and the
archiver's lock stops a bash acquirer — rather than a Python lock that happens to
sit at a similar path.

The entry's other half, the fixed `<path>.tmp` tempfile, was already closed by
Phase 272 (`Q-448`): `_atomic_write_pair` mints both temps with `mkstemp` through
`_mkstemp_beside`. `test_archive_review_tasks.py` pins that; nothing here repeats it.

Every git call strips the discovery vars (`GIT_DIR` & co.), as the hermeticity
guard requires, and every fixture repo is `git init -b main`.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import archive_review_tasks as art

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
GIT_LIB = SCRIPTS / "_git_lib.sh"

_DISCOVERY = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")

TRACKER = """\
# Review Tasks

> **Archive:** Rounds 1 are in [review_tasks_archive.md](review_tasks_archive.md).

## Round 2 (2026-07-27) — Code Quality Review

### Batch 1 — Done thing `Merged`

- [x] **TASK-1**: fixed thing

## Statistics

text
"""

ARCHIVE = (
    "# Review Tasks Archive\n\n## Grand Total (Archived)\n\n"
    "| Round | Total | Done | Deferred | Status |\n"
    "|-------|-------|------|----------|--------|\n"
    "| **Archive Total** | **200** | **200** | **0** | |\n"
)


def _env(**extra):
    env = {k: v for k, v in os.environ.items() if k not in _DISCOVERY}
    env.update(extra)
    return env


def _git(cwd, *args, check=True):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                          text=True, env=_env(), check=check)


def _install(root: Path) -> Path:
    """Lay the archiver out the way install.sh does, and seed both files."""
    sd = root / "sysop" / "scripts"
    sd.mkdir(parents=True, exist_ok=True)
    for name in ("archive_review_tasks.py", "_log.py"):
        (sd / name).write_bytes((SCRIPTS / name).read_bytes())
    (root / "review_tasks.md").write_text(TRACKER, encoding="utf-8")
    (root / "review_tasks_archive.md").write_text(ARCHIVE, encoding="utf-8")
    return sd / "archive_review_tasks.py"


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True,
                   capture_output=True, env=_env())
    script = _install(root)
    return root, script


def _mutex(main_root: Path) -> Path:
    return main_root / "sysop" / "runtime" / "tracker.write.lock"


def _run(script, *args, wait="1", answer="y\n", **env):
    return subprocess.run([sys.executable, str(script), *args], input=answer,
                          capture_output=True, text=True, timeout=60,
                          env=_env(SYSOP_TRACKER_LOCK_WAIT=wait, **env))


class _BashHolder:
    """A real `tracker_lock_acquire` from `_git_lib.sh`, held until closed."""

    def __init__(self, locks_dir: Path, what="a rival claim"):
        self.proc = subprocess.Popen(
            ["bash", "-c",
             f'source "{GIT_LIB}" || exit 9\n'
             f'tracker_lock_acquire "{locks_dir}" "{what}" || exit 1\n'
             'echo held\n'
             'exec sleep 60'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=_env(SYSOP_TRACKER_LOCK_WAIT="1"))
        line = self.proc.stdout.readline()
        if line.strip() != "held":
            self.close()
            raise AssertionError(f"bash holder failed to acquire: {self.proc.stderr.read()}")

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(timeout=10)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _snapshot(root):
    return ((root / "review_tasks.md").read_bytes(),
            (root / "review_tasks_archive.md").read_bytes())


# ── interoperability: one mutex, two languages ───────────────────────────────


class TestOneMutexWithTheBashWriters:

    def test_a_bash_holder_makes_the_archiver_wait_then_refuse_writing_nothing(self, repo):
        root, script = repo
        before = _snapshot(root)
        with _BashHolder(root / "sysop" / "runtime" / "locks", "the claim of Batch 7"):
            started = time.monotonic()
            r = _run(script, wait="4")
            elapsed = time.monotonic() - started
            held = _mutex(root).read_text()
        assert r.returncode == 1, r.stdout + r.stderr
        assert "locked by another Sysop process" in r.stderr
        # It WAITED, and said so — two silent minutes look like a hang.
        assert "Waiting for the tracker lock" in r.stderr
        assert elapsed >= 3.5, f"refused after {elapsed:.1f}s; it did not wait"
        # The refusal shows the holder — the operator cannot judge staleness otherwise.
        assert "the claim of Batch 7" in r.stderr
        assert "Refusing this archive run" in r.stderr
        assert "rm -f" in r.stderr and "tracker.write.lock" in r.stderr
        # Wrote nothing, and did not touch the rival's lock.
        assert _snapshot(root) == before
        assert "holder_pid:" in held and "archive_review_tasks" not in held

    def test_the_archivers_lock_blocks_a_bash_acquirer(self, tmp_path):
        locks = tmp_path / "sysop" / "runtime" / "locks"
        got = art._tracker_lock_acquire(str(locks), "an archive under test")
        assert got == str(_mutex(tmp_path))
        try:
            r = subprocess.run(
                ["bash", "-c", f'source "{GIT_LIB}" || exit 9\n'
                               f'tracker_lock_acquire "{locks}" "a claim"'],
                capture_output=True, text=True, env=_env(SYSOP_TRACKER_LOCK_WAIT="1"))
            assert r.returncode == 1, r.stdout + r.stderr
            assert "locked by another Sysop process" in r.stderr
            # Bash reads our record and shows it: same keys, same file.
            assert "holder: archive_review_tasks.py" in r.stderr
            assert f"holder_pid: {os.getpid()}" in r.stderr
            assert "an archive under test" in r.stderr
        finally:
            art._tracker_lock_release(got)
        assert not _mutex(tmp_path).exists()
        # ...and once released, bash takes it normally.
        r = subprocess.run(
            ["bash", "-c", f'source "{GIT_LIB}" || exit 9\n'
                           f'tracker_lock_acquire "{locks}" "a claim" || exit 1\n'
                           'tracker_lock_release'],
            capture_output=True, text=True, env=_env(SYSOP_TRACKER_LOCK_WAIT="1"))
        assert r.returncode == 0, r.stderr

    def test_since_is_stamped_when_the_lock_is_taken_not_when_the_wait_began(
            self, tmp_path, monkeypatch):
        """`since:` is what an operator reads before deciding a lock is stale and
        removing it by hand; a stamp from the start of a long wait makes a fresh
        holder look old. The bash helper stamps each attempt."""
        import threading
        from datetime import datetime, timezone
        rival = _mutex(tmp_path)
        rival.parent.mkdir(parents=True)
        rival.write_text("holder_pid: 999999\nholder: rival.sh\n")
        monkeypatch.setenv("SYSOP_TRACKER_LOCK_WAIT", "10")
        started = datetime.now(timezone.utc).replace(microsecond=0)
        threading.Timer(2.5, rival.unlink).start()
        got = art._tracker_lock_acquire(str(tmp_path / "sysop/runtime/locks"), "x")
        try:
            assert got, "the lock never came free"
            since = next(ln.split(": ", 1)[1] for ln in Path(got).read_text().splitlines()
                         if ln.startswith("since: "))
            stamped = datetime.strptime(since, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            assert (stamped - started).total_seconds() >= 2, (
                f"since: {since} predates the acquisition (wait began {started:%H:%M:%S})")
        finally:
            art._tracker_lock_release(got)

    def test_the_record_carries_the_bash_keys_in_the_bash_order(self, tmp_path):
        got = art._tracker_lock_acquire(str(tmp_path / "sysop/runtime/locks"), "x")
        try:
            keys = [ln.split(":", 1)[0] for ln in Path(got).read_text().splitlines()]
            assert keys == ["holder_pid", "holder", "what", "since"]
        finally:
            art._tracker_lock_release(got)

    @pytest.mark.parametrize("layout", ["linked-worktree", "separate-git-dir"])
    def test_the_mutex_is_found_through_git_common_dir_not_the_trackers_tree(
            self, tmp_path, layout):
        """The behavioural half of "the same path". In a plain checkout the
        tracker's directory and `dirname(--git-common-dir)` are the same place,
        so nothing above can tell them apart. In these two layouts they differ,
        and the bash writers lock at the latter — so a holder there must stop
        the archiver. Held-lock rather than happy-path: a successful run proves
        nothing about where it looked."""
        if layout == "linked-worktree":
            main = tmp_path / "main"
            main.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main", str(main)],
                           check=True, capture_output=True, env=_env())
            for k, v in (("user.email", "t@t"), ("user.name", "t"),
                         ("commit.gpgsign", "false")):
                _git(main, "config", k, v)
            (main / "README.md").write_text("seed\n")
            _git(main, "add", "-A")
            _git(main, "commit", "-qm", "seed")
            tree = tmp_path / "wt"
            _git(main, "worktree", "add", "-q", "-b", "side", str(tree))
            lock_root = main
        else:
            outer = tmp_path / "x"
            outer.mkdir()
            tree = outer / "work"
            subprocess.run(["git", "init", "-q", "-b", "main",
                            f"--separate-git-dir={outer / 'elsewhere.git'}", str(tree)],
                           check=True, capture_output=True, env=_env())
            lock_root = outer
        script = _install(tree)
        common = _git(tree, "rev-parse", "--git-common-dir").stdout.strip()
        main_root = (tree / common).resolve().parent if not Path(common).is_absolute() \
            else Path(common).resolve().parent
        assert main_root == lock_root.resolve()
        assert main_root != tree.resolve(), "layout did not split the two roots"

        before = _snapshot(tree)
        with _BashHolder(main_root / "sysop" / "runtime" / "locks"):
            r = _run(script)
        assert r.returncode == 1, (
            "the archiver did not see a mutex the bash writers hold — it locked "
            f"somewhere else.\n{r.stdout}\n{r.stderr}")
        assert "locked by another Sysop process" in r.stderr
        assert _snapshot(tree) == before
        assert not (tree / "sysop" / "runtime" / "tracker.write.lock").exists()

    def test_an_ambient_git_dir_does_not_move_the_mutex(self, repo, tmp_path):
        """git exports `GIT_DIR` into every hook; inherited, it would resolve the
        mutex against the invoking repository instead of the tracker's."""
        root, script = repo
        other = tmp_path / "other"
        subprocess.run(["git", "init", "-q", "-b", "main", str(other)], check=True,
                       capture_output=True, env=_env())
        with _BashHolder(root / "sysop" / "runtime" / "locks"):
            r = _run(script, GIT_DIR=str((other / ".git").resolve()))
        assert r.returncode == 1, r.stdout + r.stderr
        assert "locked by another Sysop process" in r.stderr
        assert not _mutex(other).exists()


# ── release on every exit ────────────────────────────────────────────────────


class TestTheMutexIsReleasedOnEveryExit:

    def test_after_a_successful_archive(self, repo):
        root, script = repo
        r = _run(script)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "removed 1 archived tasks" in r.stdout, r.stdout
        assert "TASK-1" in (root / "review_tasks_archive.md").read_text()
        assert not _mutex(root).exists(), "the mutex survived a successful run"

    def test_after_a_refusal_inside_the_critical_section(self, repo):
        root, script = repo
        (root / "review_tasks_archive.md").unlink()
        r = _run(script)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "not found" in r.stdout
        assert not _mutex(root).exists()

    def test_after_an_exception_and_it_was_held_during_the_write(
            self, tmp_path, monkeypatch):
        review = tmp_path / "review_tasks.md"
        archive = tmp_path / "review_tasks_archive.md"
        review.write_text(TRACKER, encoding="utf-8")
        archive.write_text(ARCHIVE, encoding="utf-8")
        monkeypatch.setattr(art, "REVIEW_FILE", str(review))
        monkeypatch.setattr(art, "ARCHIVE_FILE", str(archive))
        monkeypatch.setattr(sys, "argv", ["archive_review_tasks.py"])
        monkeypatch.setattr("builtins.input", lambda _p: "y")
        monkeypatch.setenv("SYSOP_TRACKER_LOCK_WAIT", "1")
        for k in _DISCOVERY:
            monkeypatch.delenv(k, raising=False)
        seen = {}

        def boom(*_a, **_k):
            m = _mutex(tmp_path)
            seen["held"] = m.is_file() and f"holder_pid: {os.getpid()}" in m.read_text()
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(art, "_atomic_write_pair", boom)
        with pytest.raises(RuntimeError, match="disk on fire"):
            art.main()
        # Non-vacuity: the lock really was held around the write, by us.
        assert seen.get("held") is True, seen
        assert not _mutex(tmp_path).exists(), "an exception leaked the mutex"
        assert review.read_text() == TRACKER

    @pytest.mark.parametrize("signame", ["SIGTERM", "SIGHUP", "SIGINT"])
    def test_after_a_signal_mid_write(self, repo, tmp_path, signame):
        """Python's default SIGTERM and SIGHUP terminate WITHOUT unwinding, so a
        `finally` alone leaks the mutex — and nothing breaks it automatically."""
        root, script = repo
        driver = tmp_path / "driver.py"
        driver.write_text(
            "import sys, time\n"
            f"sys.path.insert(0, {str(script.parent)!r})\n"
            "import archive_review_tasks as a\n"
            "def stall(*_a, **_k):\n"
            "    print('IN', flush=True)\n"
            "    time.sleep(30)\n"
            "a._atomic_write_pair = stall\n"
            "sys.argv = ['archive_review_tasks.py']\n"
            "a.main()\n", encoding="utf-8")
        p = subprocess.Popen([sys.executable, str(driver)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             env=_env(SYSOP_TRACKER_LOCK_WAIT="1"))
        try:
            p.stdin.write("y\n")
            p.stdin.flush()
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                line = p.stdout.readline()
                if not line or "IN" in line:
                    break
            assert _mutex(root).is_file(), "the driver never reached the write"
            # End to end, while a real archiver run holds it: bash is kept out.
            b = subprocess.run(
                ["bash", "-c", f'source "{GIT_LIB}" || exit 9\n'
                               f'tracker_lock_acquire "{root / "sysop/runtime/locks"}" "a claim"'],
                capture_output=True, text=True, env=_env(SYSOP_TRACKER_LOCK_WAIT="1"))
            assert b.returncode == 1, b.stdout + b.stderr
            assert "locked by another Sysop process" in b.stderr
            assert "holder: archive_review_tasks.py" in b.stderr
            p.send_signal(getattr(signal, signame))
            p.wait(timeout=20)
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
        assert not _mutex(root).exists(), f"{signame} mid-write leaked the mutex"


# ── the critical section ─────────────────────────────────────────────────────


class TestTheCriticalSection:

    def _inproc(self, tmp_path, monkeypatch, answer):
        review = tmp_path / "review_tasks.md"
        archive = tmp_path / "review_tasks_archive.md"
        review.write_text(TRACKER, encoding="utf-8")
        archive.write_text(ARCHIVE, encoding="utf-8")
        monkeypatch.setattr(art, "REVIEW_FILE", str(review))
        monkeypatch.setattr(art, "ARCHIVE_FILE", str(archive))
        monkeypatch.setattr(sys, "argv", ["archive_review_tasks.py"])
        monkeypatch.setattr("builtins.input", answer)
        monkeypatch.setenv("SYSOP_TRACKER_LOCK_WAIT", "1")
        for k in _DISCOVERY:
            monkeypatch.delenv(k, raising=False)
        return review, archive

    def test_an_edit_made_while_the_prompt_was_open_is_not_overwritten(
            self, tmp_path, monkeypatch):
        """A lock around the write alone still loses this edit: the rewrite is
        computed from the read before the prompt. The archiver must re-read
        under the lock and refuse rather than put the old copy back."""
        edited = TRACKER + "\n- [ ] **TASK-9**: a rival's edit\n"
        review = tmp_path / "review_tasks.md"

        def answer(_p):
            review.write_text(edited, encoding="utf-8")  # another writer gets in
            return "y"

        review, archive = self._inproc(tmp_path, monkeypatch, answer)
        with pytest.raises(SystemExit) as ei:
            art.main()
        assert ei.value.code == 1
        assert review.read_text() == edited, "the rival's edit was overwritten"
        assert archive.read_text() == ARCHIVE
        assert not _mutex(tmp_path).exists()

    def test_the_prompt_is_answered_before_the_mutex_is_taken(self, tmp_path, monkeypatch):
        """An operator sitting at the prompt must not block every claim and close."""
        seen = {}

        def answer(_p):
            seen["held_at_prompt"] = _mutex(tmp_path).exists()
            return "y"

        self._inproc(tmp_path, monkeypatch, answer)
        art.main()
        assert seen == {"held_at_prompt": False}

    def test_a_dry_run_never_takes_the_mutex(self, repo):
        """A preview writes nothing and must not take a write mutex — nor wait
        behind one. `close_batch.sh --dry-run` holds the same rule."""
        root, script = repo
        with _BashHolder(root / "sysop" / "runtime" / "locks"):
            started = time.monotonic()
            r = _run(script, "--dry-run", wait="30", answer="")
            elapsed = time.monotonic() - started
            held = _mutex(root).read_text()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[DRY RUN]" in r.stdout
        assert elapsed < 20, f"the dry run waited {elapsed:.1f}s behind a write mutex"
        assert "archive_review_tasks" not in held

    def test_a_dry_run_creates_no_runtime_dir(self, repo):
        root, script = repo
        r = _run(script, "--dry-run", answer="")
        assert r.returncode == 0, r.stderr
        assert not (root / "sysop" / "runtime").exists()


# ── the refusal shapes ───────────────────────────────────────────────────────


class TestTheRefusalShapes:

    def test_a_directory_at_the_mutex_path_is_diagnosed_not_waited_on(self, repo):
        root, script = repo
        _mutex(root).mkdir(parents=True)
        before = _snapshot(root)
        started = time.monotonic()
        r = _run(script, wait="10")
        elapsed = time.monotonic() - started
        assert r.returncode == 1, r.stdout + r.stderr
        assert elapsed < 8, f"it waited {elapsed:.1f}s on a lock nothing can ever release"
        assert "NOT a regular file" in r.stderr
        assert "rm -rf" in r.stderr
        assert "locked by another Sysop process" not in r.stderr
        assert _snapshot(root) == before
        assert _mutex(root).is_dir()

    @pytest.mark.parametrize("exc", [OSError(28, "No space left on device"), KeyboardInterrupt()])
    def test_a_failed_record_write_leaves_no_lock_behind(self, tmp_path, monkeypatch, exc):
        """The round's lens 2 (`R09`): the record write is the one step after the
        exclusive create. An empty lock it left would carry no `holder_pid`, so
        neither twin's release would ever delete it, and every writer would wedge
        until someone removed it by hand."""
        locks = tmp_path / "sysop/runtime/locks"

        def boom(*a, **k):
            raise exc
        monkeypatch.setattr(art.os, "fdopen", boom)
        if isinstance(exc, OSError):
            assert art._tracker_lock_acquire(str(locks), "x") is None
        else:
            with pytest.raises(KeyboardInterrupt):
                art._tracker_lock_acquire(str(locks), "x")
        assert not (locks.parent / "tracker.write.lock").exists()

    def test_the_refusal_names_the_holder(self, tmp_path, monkeypatch, capsys):
        """The bash refusal shows who holds the lock, and this one says it follows
        the bash helper's: an operator cannot judge staleness without the holder
        (the round's lens 2, `R06`)."""
        locks = tmp_path / "sysop/runtime/locks"
        locks.mkdir(parents=True)
        (locks.parent / "tracker.write.lock").write_text(
            "holder_pid: 424242\nholder: rival.sh\nwhat: a rival\n")
        monkeypatch.setenv("SYSOP_TRACKER_LOCK_WAIT", "0")
        assert art._tracker_lock_acquire(str(locks), "x") is None
        err = capsys.readouterr().err
        assert "locked by another Sysop process" in err and "holder_pid: 424242" in err, err

    def test_the_previous_signal_handlers_are_restored(self, tmp_path, monkeypatch):
        """In-process callers are left as found (the round's lens 2, `R11`)."""
        import signal
        tracker = tmp_path / "review_tasks.md"
        tracker.write_text("x\n")
        before = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGHUP)}
        mine = lambda *a: None  # noqa: E731
        signal.signal(signal.SIGTERM, mine)
        try:
            with art._holding_tracker_lock(str(tracker), "x", "nothing"):
                assert signal.getsignal(signal.SIGTERM) is not mine
            assert signal.getsignal(signal.SIGTERM) is mine
            assert signal.getsignal(signal.SIGHUP) == before[signal.SIGHUP]
        finally:
            for sig, h in before.items():
                signal.signal(sig, h)

    def test_a_failed_write_is_not_reported_as_a_rival(self, tmp_path):
        """EEXIST on a path that does not exist is a dangling symlink: the write
        failed and no rival holds anything. Naming a rival sends the operator
        hunting for a process that is not there."""
        locks = tmp_path / "sysop" / "runtime" / "locks"
        locks.parent.mkdir(parents=True)
        _mutex(tmp_path).symlink_to(tmp_path / "nowhere" / "x")
        r = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, sys.argv[1]); import archive_review_tasks as a; "
             "sys.exit(0 if a._tracker_lock_acquire(sys.argv[2], 'x') else 3)",
             str(SCRIPTS), str(locks)],
            capture_output=True, text=True, env=_env(SYSOP_TRACKER_LOCK_WAIT="5"))
        assert r.returncode == 3, r.stderr
        assert "no rival holder" in r.stderr
        assert "locked by another Sysop process" not in r.stderr

    def test_release_does_not_delete_a_lock_it_did_not_write(self, tmp_path):
        got = art._tracker_lock_acquire(str(tmp_path / "sysop/runtime/locks"), "mine")
        Path(got).unlink()
        Path(got).write_text("holder_pid: 999999\nholder: rival.sh\n")
        art._tracker_lock_release(got)
        assert Path(got).read_text().startswith("holder_pid: 999999")

    def test_release_matches_the_whole_pid_line(self, tmp_path):
        """`holder_pid: 12` must not release a lock written by pid 123."""
        lock = _mutex(tmp_path)
        lock.parent.mkdir(parents=True)
        lock.write_text(f"holder_pid: {os.getpid()}0\nholder: rival.sh\n")
        art._tracker_lock_release(str(lock))
        assert lock.exists()

    def test_a_zero_wait_still_makes_one_attempt(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SYSOP_TRACKER_LOCK_WAIT", "0")
        got = art._tracker_lock_acquire(str(tmp_path / "sysop/runtime/locks"), "x")
        try:
            assert got, "a free lock was refused at wait 0"
        finally:
            art._tracker_lock_release(got)

    @pytest.mark.parametrize("raw,want", [
        ("0", 0), ("7", 7), ("999999", 999999), ("", 120), (" 5", 120), ("5 ", 120),
        ("+3", 120), ("-5", 120), ("1234567", 120), ("99999999999999999999", 120)])
    def test_the_wait_is_read_by_the_bash_helpers_rule(self, monkeypatch, raw, want):
        """Phase 368's round: `int()` accepted ` 5`, `+3` and `-5`, which bash's
        `case` filter reads as the default, and a 20-digit value waited forever in
        both. ASCII digits only, at most six, else 120 — the same rule as bash."""
        monkeypatch.setenv("SYSOP_TRACKER_LOCK_WAIT", raw)
        assert art._tracker_lock_wait() == want

    def test_a_non_integer_wait_means_the_default(self, monkeypatch):
        monkeypatch.setenv("SYSOP_TRACKER_LOCK_WAIT", "soon")
        assert art._tracker_lock_wait() == 120
        monkeypatch.setenv("SYSOP_TRACKER_LOCK_WAIT", "7")
        assert art._tracker_lock_wait() == 7
        monkeypatch.delenv("SYSOP_TRACKER_LOCK_WAIT")
        assert art._tracker_lock_wait() == 120
