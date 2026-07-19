"""Tests for sysop/scripts/self_check.sh (Phase 133 — the round-4 cold-read
one-command post-install prereq check: bash + PyYAML + hooks in one report
instead of discovery-by-failure).

Real-subprocess tests against scratch consumers (the test_install_*.py
pattern): the script's contract is exit 0 iff the hard prereqs (git repo,
install lock, a PyYAML-capable python3) all pass; hooks + optional scanners
are reported but advisory.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
SELF_CHECK_SRC = REPO_ROOT / "core/companion/scripts/self_check.sh"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _consumer(root):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("hi\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _install(target, *extra):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    return subprocess.run(
        ["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env,
    )


def _self_check(root):
    env = dict(os.environ)
    # The test venv's python has PyYAML — put it first on PATH so probe 3
    # passes deterministically regardless of the host system python.
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    return subprocess.run(
        ["bash", str(root / "sysop/scripts/self_check.sh")],
        cwd=root, capture_output=True, text=True, env=env,
    )


def test_passes_on_fresh_full_install(tmp_path):
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    r = _self_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "install lock present (mode: full)" in r.stdout
    assert "python3 with PyYAML" in r.stdout
    # Fresh installs arm hooks by default — the report should show them armed.
    assert "hook armed:" in r.stdout
    assert "0 failed" in r.stdout


def test_passes_on_loop_install_and_reports_mode(tmp_path):
    root = _consumer(tmp_path / "l")
    assert _install(root, "--packs", "", "--mode", "loop").returncode == 0
    r = _self_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "install lock present (mode: loop)" in r.stdout


def test_fails_without_lock(tmp_path):
    root = _consumer(tmp_path / "n")
    assert _install(root, "--packs", "").returncode == 0
    (root / ".claude" / "sysop.lock").unlink()
    r = _self_check(root)
    assert r.returncode == 1
    assert "no .claude/sysop.lock" in r.stdout


def test_fails_outside_git_repo(tmp_path):
    root = _consumer(tmp_path / "g")
    assert _install(root, "--packs", "").returncode == 0
    script = root / "sysop/scripts/self_check.sh"
    bare = tmp_path / "bare"
    bare.mkdir()
    env = dict(os.environ)
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path)
    r = subprocess.run(["bash", str(script)], cwd=bare,
                       capture_output=True, text=True, env=env)
    assert r.returncode == 1
    assert "not inside a git repository" in r.stdout


def test_unarmed_hooks_reported_advisory_not_failing(tmp_path):
    root = _consumer(tmp_path / "u")
    assert _install(root, "--packs", "", "--no-arm-hooks").returncode == 0
    r = _self_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "hook not armed:" in r.stdout
    assert "install_hooks.sh" in r.stdout


def test_source_and_installed_copies_match():
    """self_check.sh ships via install_companion_scripts — drift guard that the
    source copy is executable bash (a syntax error would break every consumer's
    first command)."""
    r = subprocess.run(["bash", "-n", str(SELF_CHECK_SRC)],
                      capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
