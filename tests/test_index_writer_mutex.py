"""The three Python writers of `tasks/index.yml` take the tracker write mutex (`Q-404`).

`close_index.py` (`/review-close` Step 4c), `backfill_completed_dates.py` and
`clear_user_action.py` each read the index, change it, and replace it whole. Until Phase 461
none took the mutex `claim_task.sh --commit-claim` and `--release` take, so a claim whose flip
and commit landed between such a writer's read and its replace was put back to `open` on disk
by the replace — and, for the close, staged that way for Step 7's commit — with every
command exiting 0. `_tracker_lock.py` now holds the shared Python twin of `_git_lib.sh`'s
`tracker_lock_acquire`, and these tests hold each writer to it:

  * a real two-process race against a real `claim_task.sh --commit-claim`, with the writer
    paused between its read and its replace, which loses the claim on the unfixed scripts;
  * a bash holder (the real `_git_lib.sh` helper) makes each writer wait, then refuse with
    the shared message having written nothing — or proceed once the holder lets go;
  * a dry run (and a close with no ids) takes no lock.

Every git call strips the discovery vars, and the fixture's scripts are copies laid out the
way `install.sh` lays them out, so a writer that cannot find `_tracker_lock.py` beside it
fails here.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import pytest
import yaml

from test_claim_commit_mutex import needs_interpreter

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
GIT_LIB = SCRIPTS / "_git_lib.sh"

_DISCOVERY = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")

# The fixture's queue. TECH-0001 is what the close closes, TECH-0002 what the rival claims,
# TECH-0003 what `clear_user_action.py` clears, TECH-0004 what the backfill looks up.
TASKS = [
    {"id": "TECH-0001", "title": "to close", "status": "in_progress", "kind": "tech",
     "effort": 1, "priority": "medium", "user_action": False},
    {"id": "TECH-0002", "title": "to claim", "status": "open", "kind": "tech",
     "effort": 1, "priority": "medium", "user_action": False},
    {"id": "TECH-0003", "title": "to clear", "status": "open", "kind": "tech",
     "effort": 1, "priority": "medium", "user_action": True},
    {"id": "TECH-0004", "title": "done, undated", "status": "done", "kind": "tech",
     "effort": 1, "priority": "medium", "user_action": False},
]

COPIED = ("claim_task.sh", "_git_lib.sh", "validate_tasks.py", "default_branch.sh", "_log.py",
          "_tracker_lock.py", "close_index.py", "backfill_completed_dates.py",
          "clear_user_action.py")


def _env(**extra):
    env = {k: v for k, v in os.environ.items() if k not in _DISCOVERY}
    env.update(extra)
    return env


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          env=_env(), check=True)


@pytest.fixture
def repo(tmp_path):
    """A primary checkout on `main` with the shipped scripts under `sysop/scripts/`.

    A script missing from the source tree is skipped rather than failed, so this module
    can be run over an older tree to show what it catches there.
    """
    main = tmp_path / "main"
    (main / "tasks" / "open").mkdir(parents=True)
    (main / "sysop" / "scripts").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(main)], check=True,
                   capture_output=True, env=_env())
    _git(main, "config", "user.email", "t@example.invalid")
    _git(main, "config", "user.name", "t")
    _git(main, "config", "commit.gpgsign", "false")
    (main / ".gitignore").write_text("sysop/runtime/\n.venv/\n")
    (main / "tasks" / "index.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "tasks": TASKS}, sort_keys=False,
                       default_flow_style=False, allow_unicode=True, width=120))
    for name in COPIED:
        src = SCRIPTS / name
        if src.exists():
            (main / "sysop" / "scripts" / name).write_bytes(src.read_bytes())
    # `claim_task.sh` resolves its PyYAML interpreter from the checkout's venv first, then
    # PATH; see `test_claim_commit_mutex._build_repo` for why the symlink is load-bearing.
    venv = REPO_ROOT / ".venv"
    if (venv / "bin" / "python3").exists():
        (main / ".venv").symlink_to(venv)
    _git(main, "add", "-A")
    _git(main, "commit", "-qm", "init")
    return main


def _mutex(root):
    return root / "sysop" / "runtime" / "tracker.write.lock"


def _index(root):
    return root / "tasks" / "index.yml"


def _task(root, tid):
    data = yaml.safe_load(_index(root).read_text(encoding="utf-8"))
    return next(t for t in data["tasks"] if t["id"] == tid)


# What each writer is asked to do, and what its write leaves behind.
WRITERS = {
    "close_index.py": (["TECH-0001"], lambda r: _task(r, "TECH-0001")["status"] == "done"),
    "clear_user_action.py": (["TECH-0003"], lambda r: _task(r, "TECH-0003")["user_action"] is False),
    # The fixture's history has no roadmap file, so the backfill finds no date and still
    # rewrites the index; the rewrite is what is observed (a new inode, from `os.replace`).
    "backfill_completed_dates.py": ([], None),
}
DRY = {
    "close_index.py": [],  # no ids: nothing can be written
    "clear_user_action.py": ["--dry-run", "TECH-0003"],
    "backfill_completed_dates.py": ["--dry-run"],
}


def _argv(root, name, args, preamble=""):
    script = root / "sysop" / "scripts" / name
    if not preamble:
        return [sys.executable, str(script), *args]
    # `runpy` sets no `sys.path[0]`, so the script's own directory goes on it here.
    return [sys.executable, "-c",
            f"import sys\nsys.path.insert(0, {str(script.parent)!r})\n" + preamble
            + f"import runpy\nsys.argv = [{str(script)!r}] + sys.argv[1:]\n"
              f"runpy.run_path({str(script)!r}, run_name='__main__')\n", *args]


def _wrote(root, name, before_ino):
    check = WRITERS[name][1]
    changed = os.stat(_index(root)).st_ino != before_ino
    return changed and (check is None or check(root))


class _BashHolder:
    """A real `tracker_lock_acquire` from `_git_lib.sh`, held until released."""

    def __init__(self, root, what="a rival claim"):
        self.proc = subprocess.Popen(
            ["bash", "-c",
             f'source "{GIT_LIB}" || exit 9\n'
             f'tracker_lock_acquire "{root / "sysop" / "runtime" / "locks"}" "{what}" || exit 1\n'
             'echo held\n'
             'read -r _\n'
             'tracker_lock_release\n'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=_env(SYSOP_TRACKER_LOCK_WAIT="1"))
        line = self.proc.stdout.readline()
        if line.strip() != "held":
            self.close()
            raise AssertionError(f"bash holder failed to acquire: {self.proc.stderr.read()}")

    def release(self):
        if self.proc.poll() is None:
            self.proc.stdin.write("\n")
            self.proc.stdin.flush()
            self.proc.wait(timeout=10)

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(timeout=10)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ── the race this exists for ─────────────────────────────────────────────────

# Pauses the writer between its read and its replace: every one of them dumps through
# `yaml.safe_dump`, after the read and before the `os.replace`.
_PAUSE = (
    "import os, time, yaml\n"
    "_real_dump = yaml.safe_dump\n"
    "def _paused_dump(*a, **kw):\n"
    "    open(os.environ['P461_REACHED'], 'w').close()\n"
    "    _end = time.monotonic() + 60\n"
    "    while not os.path.exists(os.environ['P461_GO']) and time.monotonic() < _end:\n"
    "        time.sleep(0.05)\n"
    "    return _real_dump(*a, **kw)\n"
    "yaml.safe_dump = _paused_dump\n"
    "_real_replace = os.replace\n"
    "def _recorded_replace(src, dst, *a, **kw):\n"
    "    _real_replace(src, dst, *a, **kw)\n"
    "    if os.path.basename(str(dst)) == 'index.yml':\n"
    "        with open(os.environ['P461_REPLACED'], 'a') as _f:\n"
    "            _f.write(os.path.realpath(dst) + '\\n')\n"
    "os.replace = _recorded_replace\n"
)


def _wait_for(pred, timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


@needs_interpreter
@pytest.mark.parametrize("name", sorted(WRITERS))
def test_a_claim_landing_between_the_read_and_the_replace_survives(repo, tmp_path, name):
    """The defect, run: the writer reads, a real `--commit-claim` flips and commits, the
    writer replaces. Unlocked, the replace put TECH-0002 back to `open` on disk while the
    claim exited 0. Locked, the claim waits for the writer and flips after it."""
    reached, go = tmp_path / "reached", tmp_path / "go"
    claim_err, replaced = tmp_path / "claim.err", tmp_path / "replaced"
    env = _env(P461_REACHED=str(reached), P461_GO=str(go), P461_REPLACED=str(replaced),
               SYSOP_TRACKER_LOCK_WAIT="60")
    writer = subprocess.Popen(_argv(repo, name, WRITERS[name][0], _PAUSE), cwd=str(repo),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              env=env)
    claim = None
    try:
        assert _wait_for(reached.exists, 30), (
            "the writer never reached its replace: " + (writer.communicate(timeout=5)[1]
                                                         if writer.poll() is not None else ""))
        with open(claim_err, "w") as err:
            claim = subprocess.Popen(
                ["bash", "sysop/scripts/claim_task.sh", "--commit-claim", "TECH-0002"],
                cwd=str(repo), stdout=subprocess.PIPE, stderr=err, text=True, env=env)
        # Until the claim has finished, or is visibly waiting on the mutex: releasing the
        # writer before either would let a slow claim flip after the replace and pass here
        # on the unfixed scripts too.
        assert _wait_for(lambda: claim.poll() is not None
                         or "Waiting for the tracker lock" in claim_err.read_text(), 30)
        go.touch()
        w_out, w_err = writer.communicate(timeout=60)
        c_out, _ = claim.communicate(timeout=90)
    finally:
        for p in (writer, claim):
            if p is not None and p.poll() is None:
                p.kill()
                p.wait(timeout=10)
    c_err = claim_err.read_text()
    assert writer.returncode == 0, w_out + w_err
    assert claim.returncode == 0, c_out + c_err
    assert _task(repo, "TECH-0002")["status"] == "in_progress", (
        f"{name}'s replace put the claimed task back to "
        f"{_task(repo, 'TECH-0002')['status']!r} on disk, under a claim that exited 0:\n"
        + c_out + c_err)
    # The writer's own replace, recorded in its process: the claim replaces the index after
    # it, so an inode change cannot say which of the two wrote, and on a filesystem that
    # reuses inode numbers the claim's file can take the original's (CI, ext4).
    # One replace, onto this repository's index: the backfill has no content check, so the
    # path is what tells its write from one onto another `index.yml`.
    check = WRITERS[name][1]
    recorded = replaced.read_text().splitlines() if replaced.exists() else []
    assert recorded == [os.path.realpath(_index(repo))] and (check is None or check(repo)), (
        f"{name}'s own write did not land (replaced: {recorded}):\n{w_out}{w_err}")
    # It was serialized, not lucky: the claim waited on a holder this writer recorded.
    assert "Waiting for the tracker lock" in c_err, c_err
    assert f"holder: {name}" in c_err, c_err
    assert not _mutex(repo).exists(), "the mutex outlived both runs"


def test_the_backfill_refuses_when_the_index_changed_during_its_scan(tmp_path, capsys):
    """The backfill takes the mutex after its `git log` scan, not before the read, so it
    must not replace a file that changed while the scan ran — a claim flip landing then
    would be lost exactly as above."""
    import backfill_completed_dates as bcd
    root = tmp_path / "proj"
    (root / "tasks").mkdir(parents=True)
    index = root / "tasks" / "index.yml"
    index.write_text(yaml.safe_dump({"schema_version": 1, "tasks": TASKS}, sort_keys=False))

    def rival_flip(tid, _source):
        data = yaml.safe_load(index.read_text(encoding="utf-8"))
        next(t for t in data["tasks"] if t["id"] == "TECH-0002")["status"] = "in_progress"
        index.write_text(yaml.safe_dump(data, sort_keys=False))
        return "2026-04-01"

    with mock.patch.object(bcd, "find_completion_date", side_effect=rival_flip):
        rc = bcd.main(["--index", str(index)])
    err = capsys.readouterr().err
    assert rc == 1, err
    assert "changed while the backfill ran" in err and "nothing was written" in err
    assert _task(root, "TECH-0002")["status"] == "in_progress", "the rival's flip was lost"
    assert not _task(root, "TECH-0004").get("completed_date")
    assert not _mutex(root).exists()


# ── waiting and refusing ─────────────────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(WRITERS))
def test_a_bash_holder_makes_it_wait_then_refuse_writing_nothing(repo, name):
    raw = _index(repo).read_bytes()
    before = os.stat(_index(repo)).st_ino
    with _BashHolder(repo, "the claim of TECH-0009"):
        started = time.monotonic()
        r = subprocess.run(_argv(repo, name, WRITERS[name][0]), cwd=str(repo),
                           capture_output=True, text=True, timeout=60,
                           env=_env(SYSOP_TRACKER_LOCK_WAIT="4"))
        elapsed = time.monotonic() - started
        held = _mutex(repo).read_text()
    assert r.returncode == 1, r.stdout + r.stderr
    assert "locked by another Sysop process" in r.stderr
    assert "Waiting for the tracker lock" in r.stderr
    assert elapsed >= 3.5, f"refused after {elapsed:.1f}s; it did not wait"
    assert "the claim of TECH-0009" in r.stderr, "the refusal does not show the holder"
    assert "Refusing " in r.stderr and "rm -f" in r.stderr
    assert _index(repo).read_bytes() == raw and os.stat(_index(repo)).st_ino == before
    assert "holder_pid:" in held and name not in held, "it touched the rival's lock"


@pytest.mark.parametrize("name", sorted(WRITERS))
def test_it_proceeds_once_the_holder_lets_go(repo, name):
    before = os.stat(_index(repo)).st_ino
    with _BashHolder(repo) as holder:
        proc = subprocess.Popen(_argv(repo, name, WRITERS[name][0]), cwd=str(repo),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                env=_env(SYSOP_TRACKER_LOCK_WAIT="30"))
        time.sleep(2)
        assert proc.poll() is None, "it did not wait for the holder"
        assert os.stat(_index(repo)).st_ino == before, "it wrote while the holder held"
        holder.release()
        out, err = proc.communicate(timeout=60)
    assert proc.returncode == 0, out + err
    assert _wrote(repo, name, before), out + err
    assert not _mutex(repo).exists(), "the writer left the mutex behind"


@pytest.mark.parametrize("name", sorted(DRY))
def test_a_run_that_writes_nothing_takes_no_lock(repo, name):
    """A preview — and a close with no ids — writes nothing, so a stale lock must not
    stop it (the rule `close_batch.sh` and `archive_review_tasks.py` hold)."""
    raw = _index(repo).read_bytes()
    with _BashHolder(repo):
        started = time.monotonic()
        r = subprocess.run(_argv(repo, name, DRY[name]), cwd=str(repo), capture_output=True,
                           text=True, timeout=60, env=_env(SYSOP_TRACKER_LOCK_WAIT="30"))
        elapsed = time.monotonic() - started
    assert r.returncode == 0, r.stdout + r.stderr
    assert elapsed < 10, f"{name} waited {elapsed:.1f}s on a lock it does not need"
    assert "tracker lock" not in r.stderr
    assert _index(repo).read_bytes() == raw


def test_a_close_refused_by_the_lock_says_nothing_was_changed(repo):
    """Step 4c item 4 reads a non-zero exit as stop, and the refusal must not leave a
    half-done close: no rename staged, no lock or marker removed."""
    (repo / "sysop" / "runtime" / "locks").mkdir(parents=True)
    task_lock = repo / "sysop" / "runtime" / "locks" / "TECH-0001.lock"
    task_lock.write_text("held\n")
    with _BashHolder(repo):
        r = subprocess.run(_argv(repo, "close_index.py", ["TECH-0001"]), cwd=str(repo),
                           capture_output=True, text=True, timeout=60,
                           env=_env(SYSOP_TRACKER_LOCK_WAIT="0"))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "nothing was changed" in r.stderr
    assert "CLOSED_IDS:" not in r.stdout
    assert task_lock.exists()
    # `tasks/` only: importing the scripts leaves an untracked `sysop/scripts/__pycache__/`.
    assert _git(repo, "status", "--porcelain", "--", "tasks").stdout == ""


@pytest.mark.parametrize("breakage", ["missing-body", "unparseable-index"])
def test_a_close_that_fails_while_holding_the_lock_releases_it(repo, breakage):
    """`close_index.py` is top-level code, so its release is explicit plus `atexit`, not a
    `with`. A `git mv` that raises and the `sys.exit` on an unreadable index both leave
    while the mutex is held; neither may wedge every later claim and close. Boundary pins:
    the unfixed script takes no lock, so these pass there too."""
    if breakage == "missing-body":
        data = yaml.safe_load(_index(repo).read_text(encoding="utf-8"))
        data["tasks"][0]["body"] = "open/TECH-0001.md"  # never created: `git mv` fails
        _index(repo).write_text(yaml.safe_dump(data, sort_keys=False))
    else:
        _index(repo).write_text("tasks: [unclosed\n")
    r = subprocess.run(_argv(repo, "close_index.py", ["TECH-0001"]), cwd=str(repo),
                       capture_output=True, text=True, timeout=60,
                       env=_env(SYSOP_TRACKER_LOCK_WAIT="0"))
    assert r.returncode != 0, r.stdout + r.stderr
    assert not _mutex(repo).exists(), "a failed close left the tracker mutex behind"
