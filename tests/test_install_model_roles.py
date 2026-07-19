"""Integration tests for install.sh's model-role resolution (Phase 69).

Invokes the real installer against a scratch git consumer in tmp_path. Two
guarantees the unit suite can't cover because they live in the install pipeline:

  1. A DEFAULT install ships the role layer (served_models.yml + resolver +
     _model_roles) and leaves skills at their shipped literals — the resolver is
     a byte-for-byte no-op, so nothing diverges.
  2. A consumer-seeded served_models.local.yml override is applied AT INSTALL
     TIME — install copies skills (opus literals), then resolve_skill_models.py
     rewrites them to the overridden models.

`python3` resolves to the pytest interpreter via a PATH prefix so the installer's
`pick_python_with_yaml()` finds pyyaml (same trick as test_install_concat.py).
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_consumer(root, files=None):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    for rel, content in (files or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed", "--allow-empty")
    return root


def _run_install(target, *extra):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    result = subprocess.run(
        ["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, (
        f"install.sh failed (rc={result.returncode})\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    return result


def _fm_model(path):
    for line in path.read_text().splitlines():
        if line.startswith("model:"):
            return line.split(":", 1)[1].strip()
    return None


def test_default_install_ships_role_layer_as_noop(tmp_path):
    root = _make_consumer(tmp_path / "consumer")
    result = _run_install(root, "--packs", "python", "--no-arm-hooks")

    # The pieces ship.
    for rel in (".claude/served_models.yml",
                "sysop/scripts/resolve_skill_models.py",
                "sysop/scripts/_model_roles.py",
                "sysop/scripts/check_skill_models.py"):
        assert (root / rel).is_file(), f"installer did not ship {rel}"

    # Skills keep their shipped literals + their role markers.
    auto_build = root / ".claude/skills/auto-build/SKILL.md"
    assert _fm_model(auto_build) == "opus"
    assert "sysop:model-roles frontmatter=reasoning" in auto_build.read_text()
    assert _fm_model(root / ".claude/skills/next-task/SKILL.md") == "haiku"

    # The resolver ran (PATH carries pyyaml) and the installed tree validates.
    assert "model-roles" in result.stdout
    check = subprocess.run(
        [sys.executable, str(root / "sysop/scripts/check_skill_models.py"),
         "--root", str(root / ".claude/skills"),
         "--config", str(root / ".claude/served_models.yml")],
        capture_output=True, text=True,
    )
    assert check.returncode == 0, check.stdout + check.stderr


def test_local_override_resolves_at_install(tmp_path):
    # Consumer commits a local override BEFORE installing: reasoning -> sonnet.
    root = _make_consumer(
        tmp_path / "consumer",
        {".claude/served_models.local.yml":
         "roles:\n  reasoning: sonnet\nserved:\n  - sonnet\n"},
    )
    _run_install(root, "--packs", "python", "--no-arm-hooks")

    # Reasoning-role skills are rewritten to sonnet at install time...
    assert _fm_model(root / ".claude/skills/auto-build/SKILL.md") == "sonnet"
    assert _fm_model(root / ".claude/skills/review-close/SKILL.md") == "sonnet"
    # ...the quick role is untouched by a reasoning override...
    assert _fm_model(root / ".claude/skills/next-task/SKILL.md") == "haiku"
    # ...and the consumer's override file is never overwritten by the installer.
    assert "reasoning: sonnet" in (root / ".claude/served_models.local.yml").read_text()
