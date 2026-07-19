"""Integration tests for install.sh's no-anchor `--update` guard
(BeanRider ISSUE-0047, Phase 125).

A lock with no `sysop_commit` anchor (empty or "unknown") cannot anchor Phase
24b's 3-way divergence detection: reconstruct_old_install() returns 1 and the
clean-tree fallback then overwrites in-scope consumer scripts (scripts/*,
scripts/hooks/*) undetected — same effect as --force, but silent, exit 0. The
read-only --check path already hard-errors on exactly this; the destructive
--update must be at least as strict.

The distinction from the Phase 99 unreachable-ancestor fallback
(test_install_update_fallback.py) is the whole point: an *unreachable* ancestor
with a clean tree PROCEEDS (nothing uncommitted to lose); a *no-anchor* lock
fails closed regardless of tree state (the lock is malformed — the fix is
re-adopt, not overwrite). --force is the deliberate opt-out of preservation and
so is exempt.

These drive the real installer against scratch git consumers (the
test_install_*.py pattern).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _install_from(install_sh, target, *extra):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    return subprocess.run(
        ["bash", str(install_sh), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env,
    )


def _install(target, *extra):
    return _install_from(INSTALL_SH, target, *extra)


def _init_consumer(root):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "commit", "-qm", "init", "--allow-empty")


def _installed_with_anchor(root, anchor):
    """Fresh-install (from the real git repo), then rewrite the lock's
    sysop_commit to `anchor` (empty or "unknown" — the corrupted-anchor state
    that a git-source consumer hits when a migration eats the anchor)."""
    _init_consumer(root)
    r = _install(root, "--packs", "")
    assert r.returncode == 0, r.stdout + r.stderr
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "sysop install")
    lock = root / ".claude/sysop.lock"
    data = json.loads(lock.read_text())
    data["sysop_commit"] = anchor
    lock.write_text(json.dumps(data, indent=2))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "no-anchor lock")
    return root


@pytest.mark.parametrize("anchor", ["", "unknown"])
def test_no_anchor_update_fails_closed_on_clean_tree(tmp_path, anchor):
    """The core ISSUE-0047 guard, and it is non-tautological: the tree is CLEAN
    (contrast Phase 99's unreachable-ancestor-clean case, which PROCEEDS).
    Removing the guard would route this to the clean-tree fallback → exit 0."""
    target = _installed_with_anchor(tmp_path / "c", anchor)
    r = _install(target, "--update")
    combined = r.stdout + r.stderr
    assert r.returncode == 1, f"no-anchor update should fail closed:\n{combined}"
    assert "no sysop_commit anchor" in combined, combined
    assert "ISSUE-0047" in combined, combined
    # It must NOT have silently degraded to the clean-tree fallback.
    assert "committed-edit detection skipped" not in combined, combined


@pytest.mark.parametrize("anchor", ["", "unknown"])
def test_no_anchor_update_force_proceeds_and_labels_summary(tmp_path, anchor):
    """--force opts out of preservation deliberately, so it is exempt from the
    guard AND the summary labels the missing anchor instead of a blank `was:`."""
    target = _installed_with_anchor(tmp_path / "c", anchor)
    r = _install(target, "--update", "--force")
    combined = r.stdout + r.stderr
    assert r.returncode == 0, f"--force no-anchor update should proceed:\n{combined}"
    assert "was:  (unknown — lock had no anchor)" in combined, combined


def _nongit_source(tmp_path):
    """Copy the installer tree (install.sh + core/) into a NON-git dir so
    get_sysop_commit() yields "unknown" — the unpacked-tarball / any-agent path
    the guard must NOT fail closed on."""
    src = tmp_path / "nongit_src"
    src.mkdir()
    shutil.copy2(INSTALL_SH, src / "install.sh")
    shutil.copytree(REPO_ROOT / "core", src / "core")
    assert not (src / ".git").exists()
    return src / "install.sh"


def test_nongit_source_unknown_anchor_does_not_fire_guard(tmp_path):
    """A non-git source's lock legitimately carries sysop_commit "unknown"; the
    ISSUE-0047 guard must NOT fire — that would break the documented tarball
    update flow and advertise a --adopt recovery that can't help. It falls
    through to the Phase-99 clean-tree fallback instead. Non-tautological: before
    the git-source gate this exited 1 with the ISSUE-0047 message (the reviewer's
    MEDIUM)."""
    install_sh = _nongit_source(tmp_path)
    consumer = tmp_path / "c"
    _init_consumer(consumer)
    r = _install_from(install_sh, consumer, "--packs", "")
    assert r.returncode == 0, r.stdout + r.stderr
    lock = json.loads((consumer / ".claude/sysop.lock").read_text())
    assert lock["sysop_commit"] == "unknown", lock  # confirms non-git source
    _git(consumer, "add", "-A")
    _git(consumer, "commit", "-qm", "sysop install (non-git source)")
    # Clean tree + "unknown" anchor → update proceeds via Phase-99, guard silent.
    r = _install_from(install_sh, consumer, "--update")
    combined = r.stdout + r.stderr
    assert r.returncode == 0, f"non-git update should proceed:\n{combined}"
    # The guard's own error carries the ISSUE-0047 token + this unique phrase;
    # the benign Phase-99 fallback note ("...lock has no sysop_commit anchor —
    # skipping") does not — so assert on the guard-specific strings, not the
    # substring the fallback shares.
    assert "ISSUE-0047" not in combined, combined
    assert "preservation (Phase 24b) cannot run" not in combined, combined
    # Positively confirm it took the Phase-99 clean-tree proceed path.
    assert "committed-edit detection skipped" in combined, combined


def test_readopt_rebuilds_no_anchor_lock(tmp_path):
    """ISSUE-0047 recovery (the reviewer's HIGH): --adopt must REBUILD a lock
    whose anchor is empty, not dead-end with 'Lock already exists / use
    --update' — which loops the user, since --update fails closed. The rebuilt
    lock carries a real anchor and preserves the recorded packs (no re-prompt),
    and the next --update then proceeds."""
    consumer = tmp_path / "c"
    _init_consumer(consumer)
    r = _install(consumer, "--packs", "python")
    assert r.returncode == 0, r.stdout + r.stderr
    lock_path = consumer / ".claude/sysop.lock"
    data = json.loads(lock_path.read_text())
    assert data.get("packs") == ["python"], data
    data["sysop_commit"] = ""  # corrupt the anchor
    lock_path.write_text(json.dumps(data, indent=2))
    _git(consumer, "add", "-A")
    _git(consumer, "commit", "-qm", "no-anchor lock")
    # Re-adopt with NO --packs — it must recover packs from the lock, not refuse.
    r = _install(consumer, "--adopt")
    combined = r.stdout + r.stderr
    assert r.returncode == 0, f"--adopt should rebuild, not refuse:\n{combined}"
    assert "Lock already exists" not in combined, combined
    rebuilt = json.loads(lock_path.read_text())
    assert re.fullmatch(r"[0-9a-f]{40}", rebuilt["sysop_commit"]), rebuilt
    assert rebuilt.get("packs") == ["python"], rebuilt  # recovered, not lost
    # The whole point: --update now works with a valid anchor (adopt committed
    # the rebuilt lock, so the tree is clean).
    r = _install(consumer, "--update")
    assert r.returncode == 0, f"update after re-adopt should proceed:\n{r.stdout + r.stderr}"
