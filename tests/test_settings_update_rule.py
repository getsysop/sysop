"""Locks the sysop-update.sh permission rules in the settings.json allow-list
(Phase 99, tester round).

An agent-driven consumer (no TTY) applying an update must run
`sysop-update.sh --yes` to clear install.sh's interactive Proceed? gate, but the
shipped allow-list didn't cover the `--yes` form, so the permission system
denied it and the update dead-ended on every run. The fix allow-lists the shim
(bare + glob), making agent-driven updates one-shot.

Asserts the rules in BOTH the shipped template and a freshly-installed target
(install_permissions set-unions the template into the consumer settings.json).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
TEMPLATE = REPO_ROOT / "core/companion/.claude/settings.json"
RULES = (
    "Bash(bash scripts/sysop-update.sh)",
    "Bash(bash scripts/sysop-update.sh:*)",
)


def _allow(settings_path):
    return json.loads(Path(settings_path).read_text())["permissions"]["allow"]


def test_template_allowlists_update_shim():
    allow = _allow(TEMPLATE)
    for rule in RULES:
        assert rule in allow, f"missing allow rule {rule!r}"


def test_fresh_install_ships_update_rules(tmp_path):
    root = tmp_path / "c"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "config", k, v], cwd=root, check=True, capture_output=True)
    (root / "README.md").write_text("hi\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=root, check=True, capture_output=True)

    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    r = subprocess.run(
        ["bash", str(INSTALL_SH), str(root), "--packs", "", "--yes"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    allow = _allow(root / ".claude/settings.json")
    for rule in RULES:
        assert rule in allow, f"installed settings.json missing {rule!r}"
