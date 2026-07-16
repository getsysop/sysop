"""Integration tests for install.sh's dirty-tree refusal (validate_target, Phase 105).

On a *fresh* install (not --update/--adopt/--check) without --force, a target
whose git tree has uncommitted or untracked changes is refused before any
pipeline work runs — so a stray edit can't be clobbered by the install. This
guard (install.sh validate_target, the `git status --porcelain` test) had zero
coverage because every other install fixture commits its seed and is therefore
clean.

These drive the real installer against a scratch git consumer (the
test_install_*.py pattern). The --force companion is the non-tautological guard:
the refusal must be specifically the dirty/no-force branch, not a blanket
failure.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _make_consumer(root):
    """A clean, committed consumer — the baseline every other suite installs into."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("# seed\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run(target, *extra):
    """Drive install.sh with a pyyaml-capable python3 on PATH + --yes; return the
    CompletedProcess (does NOT assert rc — these tests inspect the refusal)."""
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    return subprocess.run(
        ["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env,
    )


def test_dirty_target_refused_without_force(tmp_path):
    target = _make_consumer(tmp_path / "consumer")
    # Dirty the tree with an untracked file (git status --porcelain → non-empty).
    (target / "unsaved.txt").write_text("work I have not committed\n")

    r = _run(target, "--packs", "")
    assert r.returncode != 0, (
        f"expected refusal\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"
    )
    assert "Target git tree has uncommitted changes." in r.stderr
    # And nothing was installed — the refusal fires before the pipeline.
    assert not (target / ".claude").exists()
    # The unsaved work is untouched.
    assert (target / "unsaved.txt").read_text() == "work I have not committed\n"


def test_dirty_target_allowed_with_force(tmp_path):
    """Non-tautological guard: the same dirty tree installs cleanly under --force,
    proving the refusal is the dirty/no-force branch, not a blanket failure."""
    target = _make_consumer(tmp_path / "consumer")
    (target / "unsaved.txt").write_text("work I have not committed\n")

    r = _run(target, "--packs", "", "--force")
    assert r.returncode == 0, (
        f"install should proceed under --force\n{r.stdout}\n{r.stderr}"
    )
    assert (target / ".claude").exists()
