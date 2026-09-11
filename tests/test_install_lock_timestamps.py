"""Lock timestamps are content-anchored, not clock-anchored (Phase 148).

Found by the Codex integration evaluation (cell D5): a no-op plain re-install
reset `installed_at` to now, and a no-op `--update` advanced `updated_at`, so
either one dirtied a previously clean consumer repository with a lock-only
working-tree diff — on operations a consumer reasonably expects to be
idempotent. The installed content and the managed paths were correct in both
cases; only the timestamps moved.

Two rules, both enforced inside `write_lock_file`'s serializer so no caller has
to cooperate:

  * `installed_at` means "first time this lock existed" — the semantics
    WORKFLOW.md § 8.2b already documented and the code did not honor. Any
    readable existing lock's value is carried forward; only a lock that is
    not there yet gets today's date.
  * `updated_at` advances only when some OTHER field actually changed. A run
    that resolves to an identical lock is not an update.

The tests below pin both directions. Preservation alone is not the property
worth having — a serializer that froze `updated_at` unconditionally would pass
a preservation-only suite while making the field meaningless — so every
preservation assertion is paired with a change assertion that proves the
timestamp still moves when the lock's content genuinely does.

Timestamps are forced to a sentinel rather than slept past: `iso_now` has
one-second granularity, so a same-second re-run would let the pre-fix
behaviour pass by luck.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"

SENTINEL_INSTALLED = "2020-01-01T00:00:00Z"
SENTINEL_UPDATED = "2020-06-15T12:34:56Z"


def _git(cwd, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, capture_output=True, text=True
    )


def _consumer(root):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("hi\n")
    # Any real Python consumer ignores bytecode. Without this the installer's
    # own model-role resolution regenerates sysop/scripts/__pycache__/*.pyc and
    # a committed copy shows up as tree dirt on every run — separate friction,
    # filed in REVIEW_CHECKLIST.md, and not the property these tests measure.
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _install(target, *extra):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    r = subprocess.run(
        ["bash", str(INSTALL_SH), str(target), "--packs", "", "--yes", *extra],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return r


STAMPS = ("installed_at", "updated_at")


def lock_drift_report(before: dict, after: dict) -> str:
    """Why `updated_at` moved, in the terms the preservation rule is defined in.

    A module-level function rather than an inline message body, and the round is the
    reason: replacing a name inside the old `AssertionError` string with
    `THIS_NAME_DOES_NOT_EXIST` left all 22 tests green. The phase's stated deliverable
    for `Q-466` -- "the next occurrence names its own field" -- had no coverage at all,
    so a typo in it would have surfaced only on the nightly it exists to serve.
    """
    fields = sorted(set(before) | set(after) - set(STAMPS))
    drift = {
        k: (before.get(k, "<absent>"), after.get(k, "<absent>"))
        for k in fields
        if k not in STAMPS and before.get(k) != after.get(k)
    }
    both_moved = (
        after.get("installed_at") != before.get("installed_at")
        and after.get("updated_at") != before.get("updated_at")
    )
    return (
        "updated_at advanced on a no-op --update "
        f"({before.get('updated_at')!r} -> {after.get('updated_at')!r}).\n"
        f"  installed_at: {before.get('installed_at')!r} -> {after.get('installed_at')!r}"
        f"{'  <-- BOTH stamps moved' if both_moved else ''}\n"
        f"  non-timestamp fields that differ: {drift or '<none>'}\n"
        "  Both stamps moved with an empty diff means the lock READ failed and a present "
        "lock was treated as absent. Every such path now refuses (`Q-466`, Phase 280) -- "
        "in `write_lock_file`, in `lock_field`, and in `get_sysop_commit` -- so that "
        "combination here means a NEW cause, not a known one."
    )


def _lock_path(target):
    return Path(target) / ".claude" / "sysop.lock"


def _lock(target):
    return json.loads(_lock_path(target).read_text())


def _write_lock(target, data, commit=True):
    """Rewrite the lock in the installer's exact serialization (byte-identity).

    Commits by default — the installer refuses a dirty target, so a test that
    damages the lock has to hand it over the way a consumer would.
    """
    with open(_lock_path(target), "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    if commit:
        _commit_all(target, "lock edit")


def _write_lock_text(target, text):
    _lock_path(target).write_text(text)
    _commit_all(target, "lock edit")


def _backdate(target, installed=SENTINEL_INSTALLED, updated=SENTINEL_UPDATED):
    """Force both timestamps to known-old values, preserving byte formatting."""
    data = _lock(target)
    data["installed_at"] = installed
    data["updated_at"] = updated
    _write_lock(target, data)


def _commit_all(target, msg="install"):
    _git(target, "add", "-A")
    _git(target, "commit", "-qm", msg, check=False)


def _status(target):
    return _git(target, "status", "--porcelain").stdout.strip()


@pytest.fixture()
def installed(tmp_path):
    """A consumer with Sysop installed, backdated lock, and a clean tree."""
    target = _consumer(tmp_path / "consumer")
    _install(target)
    _backdate(target)
    _commit_all(target)
    assert _status(target) == "", "fixture must start clean"
    return target


# --- installed_at: preserved across every re-entry path ---------------------


def test_fresh_install_stamps_both_timestamps(tmp_path):
    """With no prior lock there is nothing to preserve — today's date is right."""
    target = _consumer(tmp_path / "fresh")
    _install(target)
    lock = _lock(target)
    assert lock["installed_at"] != SENTINEL_INSTALLED
    assert lock["installed_at"].endswith("Z")
    # A fresh install is its own update.
    assert lock["updated_at"] == lock["installed_at"]


def test_plain_reinstall_preserves_installed_at(installed):
    """The regression itself: a re-install must not restart installed_at."""
    _install(installed)
    assert _lock(installed)["installed_at"] == SENTINEL_INSTALLED


def test_update_preserves_installed_at(installed):
    _install(installed, "--update")
    assert _lock(installed)["installed_at"] == SENTINEL_INSTALLED


def test_installed_at_survives_a_content_changing_reinstall(installed):
    """Preservation is independent of whether anything else changed."""
    _install(installed, "--no-codex-links")
    lock = _lock(installed)
    assert lock["installed_at"] == SENTINEL_INSTALLED
    assert lock["codex_links"] is False


# --- no-op runs leave a clean tree clean ------------------------------------


def test_noop_reinstall_leaves_tree_clean(installed):
    """The consumer-facing property: re-running the installer dirties nothing."""
    _install(installed)
    assert _status(installed) == "", "no-op re-install dirtied the working tree"


def test_noop_update_leaves_tree_clean(installed):
    _install(installed, "--update")
    assert _status(installed) == "", "no-op --update dirtied the working tree"


def test_noop_reinstall_rewrites_lock_byte_for_byte(installed):
    before = _lock_path(installed).read_bytes()
    _install(installed)
    assert _lock_path(installed).read_bytes() == before


def test_noop_update_preserves_updated_at(installed):
    """`Q-466`: this is the assertion that goes red intermittently under load.

    It asserts a TIMESTAMP, so when it fires it reports the symptom and nothing
    else -- which is why one observation on 2026-09-10 could not be turned into a
    mechanism. But the rule it tests is defined entirely in terms of the lock's
    NON-timestamp content: `updated_at` moves if and only if some other field
    changed. So the field-level diff IS the mechanism, and taking it costs one
    comparison on a path that is about to fail anyway.

    The nightly is now the only place the class can still surface (a PR run is
    sharded four ways and no longer carries the full population under
    contention), so the next occurrence has to be worth more than the last one.
    """
    before = _lock(installed)
    _install(installed, "--update")
    after = _lock(installed)
    if after["updated_at"] != SENTINEL_UPDATED:
        raise AssertionError(lock_drift_report(before, after))


# --- but updated_at still moves when the lock genuinely changes -------------
# Without these, a serializer that simply froze updated_at would pass above.


def test_updated_at_advances_when_a_field_changes(installed):
    """Flipping codex_links is a real lock change — the stamp must move."""
    _install(installed, "--no-codex-links")
    lock = _lock(installed)
    assert lock["updated_at"] != SENTINEL_UPDATED, (
        "updated_at froze through a real content change"
    )
    assert lock["codex_links"] is False


def test_updated_at_advances_when_managed_paths_change(installed):
    """--no-codex-links also drops two managed paths; the stamp tracks that."""
    before = set(_lock(installed)["managed_paths"])
    _install(installed, "--no-codex-links")
    after = _lock(installed)
    assert set(after["managed_paths"]) != before
    assert after["updated_at"] != SENTINEL_UPDATED


def test_update_after_a_change_advances_then_holds(installed):
    """Two-step: a real change bumps the stamp, the next no-op holds it."""
    _install(installed, "--no-codex-links")
    bumped = _lock(installed)["updated_at"]
    assert bumped != SENTINEL_UPDATED
    _commit_all(installed, "opt out")
    _install(installed, "--update")
    assert _lock(installed)["updated_at"] == bumped
    assert _status(installed) == ""


# --- defensive parsing: a damaged lock must not crash the install ------------


def test_missing_installed_at_falls_back_to_now(installed):
    data = _lock(installed)
    del data["installed_at"]
    _write_lock(installed, data)
    _install(installed)
    lock = _lock(installed)
    assert lock["installed_at"] and lock["installed_at"] != SENTINEL_INSTALLED


def test_non_string_timestamps_fall_back_to_now(installed):
    data = _lock(installed)
    data["installed_at"] = 1234
    data["updated_at"] = None
    _write_lock(installed, data)
    _install(installed)
    lock = _lock(installed)
    assert isinstance(lock["installed_at"], str) and lock["installed_at"].endswith("Z")
    assert isinstance(lock["updated_at"], str) and lock["updated_at"].endswith("Z")


def test_unparseable_lock_does_not_block_reinstall(installed):
    _write_lock_text(installed, "{ this is not json\n")
    _install(installed)
    lock = _lock(installed)
    assert lock["installed_at"].endswith("Z")
    assert lock["updated_at"].endswith("Z")


def test_non_object_lock_does_not_block_reinstall(installed):
    _write_lock_text(installed, "[]\n")
    _install(installed)
    assert _lock(installed)["installed_at"].endswith("Z")


# --- the read that could not tell absence from failure (`Q-466`, Phase 280) ---
#
# The preservation rules above are only as good as the read that feeds them. The
# serializer caught a bare `OSError`, so "no lock here" and "a lock is here and I
# could not read it this instant" took the same branch -- and that branch rewrites
# BOTH timestamps to now. On a fresh install that is right; on a re-install it
# silently destroys the two fields this block exists to preserve.
#
# Driven against the SHIPPED serializer, extracted from install.sh, because the
# claim is about what that block does and a reimplementation would only prove this
# module is self-consistent. EMFILE is the load-dependent OSError, which is why
# this is filed under `Q-466` rather than as a standalone hardening: a transient
# one produces exactly the symptom that entry reports, silently.


def _serializer_source():
    """The `python3 - <<'PY'` block inside write_lock_file, as shipped."""
    src = INSTALL_SH.read_text(encoding="utf-8")
    start = src.index("write_lock_file() {")
    block = src[start:src.index("\n# Snapshot dirty paths", start)]
    # The round: a non-greedy FIRST match with no uniqueness check was defeated by a
    # dead `if false; then python3 - <<'PY' ... PY fi` carrying a byte-identical copy of
    # the fixed serializer, while the real one reverted to the defect. All tests green.
    found = re.findall(r"python3 - <<'PY'\n(.*?)\nPY\n", block, re.S)
    assert len(found) == 1, (
        f"write_lock_file must contain exactly one `python3 - <<'PY'` heredoc; found "
        f"{len(found)}. A second one lets this extractor read a decoy while the shipped "
        "serializer carries the defect."
    )
    return found[0]


_PRIOR = {
    "version": 3, "sysop_commit": "deadbeef", "packs": [], "mode": "full",
    "codex_links": True, "installed_at": SENTINEL_INSTALLED,
    "updated_at": SENTINEL_UPDATED, "managed_paths": ["a", "b"],
}
_CALLER_STAMP = "2026-09-10T00:00:00Z"


def _run_serializer(lock_path, fail_read_with=None):
    """Execute the shipped serializer; optionally make the lock READ raise."""
    import builtins
    env = {
        "SYSOP_LOCK_PATH": str(lock_path), "SYSOP_LOCK_VERSION": "3",
        "SYSOP_COMMIT": "deadbeef", "SYSOP_PACKS": "", "SYSOP_MODE": "full",
        "SYSOP_CODEX_LINKS": "true", "SYSOP_INSTALLED_AT": _CALLER_STAMP,
        "SYSOP_UPDATED_AT": _CALLER_STAMP, "SYSOP_MANAGED_PATHS": "a\nb",
    }
    real_open = builtins.open

    def fake_open(f, *a, **k):
        mode = a[0] if a else k.get("mode", "r")
        if fail_read_with is not None and str(f) == str(lock_path) and "r" in mode:
            raise fail_read_with
        return real_open(f, *a, **k)

    saved = dict(os.environ)
    os.environ.update(env)
    try:
        exec(compile(_serializer_source(), "<install.sh serializer>", "exec"),
             {"__name__": "__main__", "open": fake_open})
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return json.loads(real_open(lock_path).read())


def test_serializer_preserves_both_stamps_when_the_lock_reads(tmp_path):
    """The control. Without it the two tests below pass on a serializer that does nothing."""
    lp = tmp_path / "sysop.lock"
    lp.write_text(json.dumps(_PRIOR, indent=2) + "\n")
    out = _run_serializer(lp)
    assert out["installed_at"] == SENTINEL_INSTALLED
    assert out["updated_at"] == SENTINEL_UPDATED


def test_an_absent_lock_is_still_the_fresh_install_path(tmp_path):
    """`FileNotFoundError` must stay tolerated -- it is the legitimate absence.

    The fix narrows the except clause, and the direction that would break a real
    consumer is narrowing it too far: a first install has no lock, and raising
    there would refuse every fresh install on the planet.
    """
    lp = tmp_path / "sysop.lock"
    out = _run_serializer(lp)
    assert out["installed_at"] == _CALLER_STAMP
    assert out["updated_at"] == _CALLER_STAMP


def test_a_malformed_lock_is_still_tolerated(tmp_path):
    """Phase 148's decision, unchanged: a hand-mangled lock must not abort the install."""
    lp = tmp_path / "sysop.lock"
    lp.write_text("{not json at all")
    out = _run_serializer(lp)
    assert out["installed_at"] == _CALLER_STAMP


def test_an_unreadable_lock_raises_rather_than_resetting_both_stamps(tmp_path):
    """The defect itself, driven rather than described.

    Before the fix this returned a lock with BOTH timestamps set to the caller's
    values and said nothing -- `installed_at` destroyed, `updated_at` advanced, on
    a consumer whose lock was perfectly intact and merely unreadable for one
    instant. That is the symptom `Q-466` reports.
    """
    lp = tmp_path / "sysop.lock"
    lp.write_text(json.dumps(_PRIOR, indent=2) + "\n")
    with pytest.raises(SystemExit) as exc:
        _run_serializer(lp, fail_read_with=OSError(24, "Too many open files"))
    msg = str(exc.value)
    assert "cannot read the existing lock" in msg, msg
    # The lock on disk must be untouched -- refusing means refusing to WRITE too.
    assert json.loads(lp.read_text())["updated_at"] == SENTINEL_UPDATED, (
        "the serializer raised but had already rewritten the lock, which is the "
        "data loss this fix exists to stop, arriving one line later."
    )


def test_the_ladder_does_not_discriminate_on_errno():
    """The docstring below claims a RULE; this is what makes it one.

    The round wrote three bypasses that kept every named errno raising while silently
    tolerating the rest -- `if exc.errno == 5`, `if exc.errno not in (24, 4, 13)`, and
    widening the tolerated tuple with `BlockingIOError`/`TimeoutError`. A parametrized
    list of errnos cannot see any of them, because it only ever asks about its own
    three. The rule is absence-versus-failure, so the ladder must not mention errno at
    all, and must tolerate exactly the two absence/ malformed classes.
    """
    src = _serializer_source()
    assert "errno" not in src, (
        "the lock-read ladder discriminates on errno. That turns a rule into a list, "
        "and every errno not on the list is silently tolerated again."
    )
    tolerated = set(re.findall(r"^except ([A-Za-z_, ()]+):", src, re.M))
    assert tolerated == {"FileNotFoundError", "ValueError", "OSError as exc"} or \
        tolerated == {"FileNotFoundError", "ValueError"} | {t for t in tolerated if "as exc" in t}, (
        f"the ladder's except clauses changed to {sorted(tolerated)}. Exactly two classes "
        "may resolve to `prev = None`: FileNotFoundError (absence) and ValueError "
        "(malformed, Phase 148). Anything else added there is silently tolerated."
    )


@pytest.mark.parametrize("err", [
    pytest.param(OSError(24, "Too many open files"), id="EMFILE"),
    pytest.param(OSError(4, "Interrupted system call"), id="EINTR"),
    pytest.param(PermissionError(13, "Permission denied"), id="EACCES"),
    pytest.param(OSError(5, "Input/output error"), id="EIO"),
    pytest.param(BlockingIOError(35, "Resource temporarily unavailable"), id="EAGAIN"),
    pytest.param(TimeoutError(60, "Operation timed out"), id="ETIMEDOUT"),
    pytest.param(OSError(122, "Disk quota exceeded"), id="EDQUOT"),
])
def test_every_non_absence_oserror_refuses(tmp_path, err):
    """Not just EMFILE. The rule is absence-versus-failure, not a list of errnos.

    Four errnos added by the round, which tolerated EIO, EAGAIN and ETIMEDOUT while
    the original three still raised. The list is still a list -- the guard that makes
    it a rule is `test_the_ladder_does_not_discriminate_on_errno` above.
    """
    lp = tmp_path / "sysop.lock"
    lp.write_text(json.dumps(_PRIOR, indent=2) + "\n")
    with pytest.raises(SystemExit):
        _run_serializer(lp, fail_read_with=err)


# --- the reader that runs FIRST (`Q-466`, Phase 280 round findings M3 + M4) ---


def test_an_unreadable_lock_refuses_before_touching_the_tree(installed):
    """The refusal must land before a single managed path is written.

    Found by the round. `write_lock_file` runs LAST -- after all ~104 managed paths
    are on disk -- so a refusal there leaves a HALF-APPLIED install: new files in the
    tree, lock still holding the old `sysop_commit` and the old `managed_paths`. The
    next `--update` then computes its Phase-24b preservation diff against the wrong
    anchor. That is a worse consumer state than the timestamp reset it trades away.

    `lock_field` is the reader that runs first, and it had the identical
    absence-versus-failure conflation. Fixing it is what makes the refusal clean.
    """
    lock = _lock_path(installed)
    before = lock.read_bytes()
    os.chmod(lock, 0o000)
    try:
        r = subprocess.run(
            ["bash", str(INSTALL_SH), str(installed), "--packs", "", "--yes", "--update"],
            capture_output=True, text=True,
            env={**os.environ, "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"]},
        )
    finally:
        os.chmod(lock, 0o644)
    assert r.returncode != 0, "an unreadable lock must refuse, not proceed"
    assert lock.read_bytes() == before, "the lock was rewritten despite the refusal"
    assert _status(installed) == "", (
        "the install mutated the consumer tree before refusing -- a half-applied "
        f"install. Dirty paths: {_status(installed)!r}"
    )


def test_the_refusal_does_not_blame_a_missing_anchor(installed):
    """The FALSE diagnosis, and the reason this one matters more than a wrong message.

    Treating a transient read failure as absence yields an empty `sysop_commit`, which
    trips the no-anchor guard -- whose two prescribed remedies both destroy exactly
    what is being protected: `--adopt` rewrites the lock, `--force` overwrites every
    managed path without preservation. So the wrong message routes the operator into
    the data loss.
    """
    lock = _lock_path(installed)
    os.chmod(lock, 0o000)
    try:
        r = subprocess.run(
            ["bash", str(INSTALL_SH), str(installed), "--packs", "", "--yes", "--update"],
            capture_output=True, text=True,
            env={**os.environ, "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"]},
        )
    finally:
        os.chmod(lock, 0o644)
    out = r.stdout + r.stderr
    assert "could not be read" in out, "the refusal no longer says the read failed"
    assert "has no sysop_commit anchor" not in out, (
        "the installer is blaming a missing anchor again. The anchor is present and "
        "fine; only the read failed. That diagnosis prescribes --adopt/--force, both "
        "of which rewrite state the refusal exists to preserve."
    )


def test_a_malformed_lock_still_reads_as_absent_end_to_end(installed):
    """Phase 148's tolerance, unchanged, and checked through the installer.

    The fix narrows `lock_field`'s except clause; the direction that would break real
    consumers is narrowing it too far. A hand-mangled lock must still let the install
    proceed rather than refusing.
    """
    _write_lock_text(installed, "{ this is not json")
    r = subprocess.run(
        ["bash", str(INSTALL_SH), str(installed), "--packs", "", "--yes"],
        capture_output=True, text=True,
        env={**os.environ, "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"]},
    )
    assert r.returncode == 0, (
        "a malformed lock now refuses. Phase 148 decided it must not: "
        + (r.stdout + r.stderr)[-500:]
    )


def test_the_serializer_does_not_swallow_a_directory_at_the_lock_path():
    """The round showed the `IsADirectoryError` clause strictly harmful.

    `prev = None` fell through to the WRITE, which raises the identical error
    uncaught -- converting a clean actionable message into a raw traceback. A
    directory at the lock path is not absence.
    """
    src = _serializer_source()
    # The CLAUSE, not the word -- the comment recording why it was removed names it,
    # and a guard that greps for the bare identifier fails on its own explanation.
    assert "except IsADirectoryError" not in src, (
        "the IsADirectoryError clause is back. It cannot help: setting prev=None "
        "falls through to `open(lock_path, 'w')`, which raises the same error with "
        "no handler. The installer refuses a non-file lock path upstream anyway."
    )


# --- `sysop_commit`, the field the phase's own elimination skipped (`Q-466`) ---
#
# Found by the round: the lock has six non-timestamp fields and the phase excluded
# five. `sysop_commit` is the only one that is neither a literal nor read back from
# the lock -- it FORKS `git rev-parse HEAD` on every install, which is load-dependent
# by construction, and the old shape fell back to the literal `unknown` in silence.
# It is also the better fit for the reported flake: the serializer's fail-open moves
# BOTH timestamps, while a changed `sysop_commit` moves only `updated_at`, which is
# exactly and only what `test_noop_update_preserves_updated_at` asserts.
#
# Driven by extracting the shipped function and running it under bash against three
# real directories, because the refusal arm cannot be reached through a normal
# install -- which is precisely why it shipped unguarded until a mutation survived.


def _get_sysop_commit_harness(repo_root: Path) -> subprocess.CompletedProcess:
    """Run install.sh's `get_sysop_commit` verbatim with REPO_ROOT pointed at *repo_root*."""
    src = INSTALL_SH.read_text(encoding="utf-8")
    start = src.index("get_sysop_commit() {")
    end = src.index("\n}\n", start) + 3
    fn = src[start:end]
    assert "rev-parse --git-dir" in fn, (
        "get_sysop_commit's shape moved -- this test extracts it by name and asserts "
        "the arm it is written about is present, so it fails closed rather than "
        "passing over a function that no longer has it."
    )
    script = (
        "set -uo pipefail\n"
        'err() { printf "ERR %s\\n" "$*" >&2; }\n'
        'ANCHOR_OVERRIDE=""\n'
        f'REPO_ROOT={repo_root!s}\n'
        f"{fn}\n"
        "get_sysop_commit\n"
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


def test_a_non_git_source_still_yields_unknown(tmp_path):
    """The legitimate absence: a tarball install has no `.git` and must still work."""
    d = tmp_path / "tarball"
    d.mkdir()
    r = _get_sysop_commit_harness(d)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "unknown", (
        "a source tree with no .git must still resolve to `unknown`. Narrowing this "
        "arm would refuse every tarball install."
    )


def test_a_normal_source_yields_the_head_sha(tmp_path):
    """The control. Without it the two arms below pass on a function that always fails."""
    d = tmp_path / "repo"
    d.mkdir()
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "t@t")
    _git(d, "config", "user.name", "t")
    _git(d, "config", "commit.gpgsign", "false")
    (d / "f").write_text("x")
    _git(d, "add", "-A")
    _git(d, "commit", "-qm", "c")
    r = _get_sysop_commit_harness(d)
    assert r.returncode == 0, r.stderr
    assert re.fullmatch(r"[0-9a-f]{40}", r.stdout.strip()), r.stdout


def test_a_git_source_whose_head_is_unreadable_refuses(tmp_path):
    """The arm a mutation survived: silently substituting `unknown` moves `updated_at`.

    A repo with no commits is a git repository whose HEAD cannot be resolved -- the
    exact shape the old code could not distinguish from "not a git repo at all". It
    used to print `unknown`, which changes `sysop_commit`, which makes an otherwise
    no-op install look like a real update.
    """
    d = tmp_path / "headless"
    d.mkdir()
    _git(d, "init", "-q")
    r = _get_sysop_commit_harness(d)
    assert r.returncode != 0, (
        f"a git repo with an unreadable HEAD did not refuse; it printed {r.stdout.strip()!r}. "
        "Substituting a different value into sysop_commit is what moves updated_at."
    )
    assert "unknown" not in r.stdout, "the silent fallback is back"
    assert "HEAD could not" in r.stderr, r.stderr


def test_the_drift_report_names_the_field_that_moved():
    """The Q-466 deliverable, driven. It was dead code on every green run."""
    base = {"version": 3, "sysop_commit": "aaa", "packs": [], "mode": "full",
            "codex_links": True, "installed_at": SENTINEL_INSTALLED,
            "updated_at": SENTINEL_UPDATED, "managed_paths": ["a"]}
    moved = dict(base, sysop_commit="bbb", updated_at="2026-09-10T00:00:00Z")
    msg = lock_drift_report(base, moved)
    assert "sysop_commit" in msg, msg
    assert "'aaa'" in msg and "'bbb'" in msg, msg
    assert "BOTH stamps moved" not in msg, "only updated_at moved here"


def test_the_drift_report_flags_the_read_failure_signature():
    """Both stamps moving with an empty field diff is the read-failed signature."""
    base = {"version": 3, "sysop_commit": "aaa", "packs": [], "mode": "full",
            "codex_links": True, "installed_at": SENTINEL_INSTALLED,
            "updated_at": SENTINEL_UPDATED, "managed_paths": ["a"]}
    moved = dict(base, installed_at="2026-09-10T00:00:00Z", updated_at="2026-09-10T00:00:00Z")
    msg = lock_drift_report(base, moved)
    assert "BOTH stamps moved" in msg, msg
    assert "<none>" in msg, "an empty field diff must be shown as such, not omitted"
    assert "NEW cause" in msg, "the reader needs to know the known paths now refuse"
