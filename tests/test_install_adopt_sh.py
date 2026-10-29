"""Integration tests for `install.sh --adopt` guard behavior (Phase 85).

`--adopt` backfills a `.claude/sysop.lock` for an install that predates the lock
mechanism. Such a target already has a populated `.claude/` from that original
install. Adopting a target with *no* `.claude/` has nothing to adopt: the
managed_paths come from a DRY_RUN pipeline that writes nothing, so proceeding
would (a) mint a lock referencing paths never written and (b) crash the lock
write with a raw `FileNotFoundError` (the `.claude/` parent dir is absent —
poisoned in the shared `ensure_dir` memo during the dry-run pipeline, so the
real write's `mkdir` is skipped). Phase 85 replaces that traceback with a
graceful pre-check + actionable pointer.

These drive the real installer against scratch git consumers (the
test_install_*.py pattern). The second test is the non-tautological guard: the
pre-check must NOT fire when `.claude/` exists, or it would break the legitimate
adopt path it's meant to protect.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_consumer(root):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    (root / "README.md").write_text("hi\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run(target, *extra):
    """Drive install.sh with a pyyaml-capable python3 on PATH (matches the
    concat/detect suites) and --yes for non-interactive confirm."""
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    return subprocess.run(
        ["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env,
    )


def test_adopt_into_bare_target_fails_gracefully(tmp_path):
    """--adopt with no pre-existing .claude/ → clean rc!=0, no traceback, and a
    pointer to run a normal install first."""
    target = _make_consumer(tmp_path / "bare")
    result = _run(target, "--adopt", "--packs", "")

    assert result.returncode != 0, (
        f"expected non-zero rc\n--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "Traceback" not in combined, (
        "the raw FileNotFoundError traceback should be gone\n" + combined
    )
    # Actionable message: names the missing marker + points at a normal install.
    assert "No existing Sysop install found" in result.stderr
    assert "run a normal install first" in combined
    # And it must not have left a half-written lock behind.
    assert not (target / ".claude" / "sysop.lock").exists()


def test_adopt_after_real_install_still_works(tmp_path):
    """Non-tautological guard: with .claude/ present (a real prior install whose
    lock was removed to simulate a pre-lock install), --adopt succeeds and
    writes the lock. The pre-check must not over-block this legitimate path."""
    target = _make_consumer(tmp_path / "real")

    installed = _run(target, "--packs", "")
    assert installed.returncode == 0, (
        f"normal install failed\n--- stdout ---\n{installed.stdout}\n"
        f"--- stderr ---\n{installed.stderr}"
    )
    assert (target / ".claude").is_dir()

    # Simulate an install that predates the lock mechanism: .claude/ populated,
    # but no sysop.lock.
    (target / ".claude" / "sysop.lock").unlink()

    adopted = _run(target, "--adopt", "--packs", "")
    assert adopted.returncode == 0, (
        f"legit adopt failed\n--- stdout ---\n{adopted.stdout}\n"
        f"--- stderr ---\n{adopted.stderr}"
    )
    assert "Traceback" not in (adopted.stdout + adopted.stderr)
    assert (target / ".claude" / "sysop.lock").exists()


def test_adopt_refuses_when_lock_already_exists(tmp_path):
    """A normal install writes .claude/sysop.lock; re-adopting it is refused with
    a pointer to --update (a distinct branch from the bare-target pre-check —
    cmd_adopt hits the lock-exists guard first). This is the double-adopt guard."""
    target = _make_consumer(tmp_path / "already")

    installed = _run(target, "--packs", "")
    assert installed.returncode == 0, (
        f"normal install failed\n{installed.stdout}\n{installed.stderr}"
    )
    assert (target / ".claude" / "sysop.lock").exists()

    adopted = _run(target, "--adopt", "--packs", "")  # lock left in place
    assert adopted.returncode != 0, (
        f"expected refusal\n--- stdout ---\n{adopted.stdout}\n"
        f"--- stderr ---\n{adopted.stderr}"
    )
    assert "Lock already exists" in adopted.stderr
    assert "Traceback" not in (adopted.stdout + adopted.stderr)
