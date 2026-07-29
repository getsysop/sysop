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
    _install(installed, "--update")
    assert _lock(installed)["updated_at"] == SENTINEL_UPDATED


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
