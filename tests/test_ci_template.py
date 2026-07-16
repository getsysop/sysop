"""Tests for the Consumer CI template (Phase 92).

`core/companion/ci/sysop-checks.yml.example` is a hardened, unarmed GitHub Actions
workflow shipped to a consumer's `scripts/ci/` (like the git-hook templates —
delivered but not activated). A consumer copies it into `.github/workflows/`,
fills the two TODO steps, and marks the `sysop-checks` check required in branch
protection to make Phase 63's `pr` merge policy enforceable.

Two things worth locking: the template's hardened shape (valid YAML, the
run_checks gate, SHA-pinned actions, least-privilege permissions, and a
placeholder test step that fails so an unedited copy can't become a
meaningless green required check), and that install.sh actually ships it
unarmed (into scripts/ci/, recorded in the lock, NOT dropped into
.github/workflows/).
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
TEMPLATE = REPO_ROOT / "core/companion/ci/sysop-checks.yml.example"


class TestTemplateShape:
    def _load(self):
        return yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))

    def test_valid_yaml_named_sysop_checks(self):
        d = self._load()
        assert d["name"] == "sysop-checks"
        assert "sysop-checks" in d["jobs"]

    def test_runs_the_blocking_findings_gate(self):
        steps = self._load()["jobs"]["sysop-checks"]["steps"]
        runs = [s.get("run", "") for s in steps]
        assert any("run_checks.sh --fail-on-blocking" in r for r in runs), \
            "the Sysop blocking-findings gate step is missing"

    def test_least_privilege_permissions(self):
        # A required check should not carry write scopes.
        assert self._load()["permissions"] == {"contents": "read"}

    def test_actions_are_sha_pinned(self):
        # Hardened like Sysop's own tests.yml — every `uses:` pins a 40-hex SHA,
        # never a floating tag (a supply-chain footgun in a required check).
        uses = re.findall(r"uses:\s*(\S+)", TEMPLATE.read_text(encoding="utf-8"))
        assert uses, "no `uses:` actions found"
        for u in uses:
            assert re.search(r"@[0-9a-f]{40}$", u), f"action not SHA-pinned: {u}"

    def test_placeholder_test_step_fails_by_design(self):
        # The unedited Tests step must NOT pass — a green-but-meaningless
        # required check is worse than none. It exits 1 until the consumer
        # replaces it with their real test command.
        steps = self._load()["jobs"]["sysop-checks"]["steps"]
        tests_step = next(s for s in steps if s.get("name") == "Tests")
        assert "exit 1" in tests_step["run"]

    def test_is_not_itself_an_active_workflow(self):
        # The `.example` suffix is what keeps GitHub from running it — a bare
        # `.yml` would activate on push the moment it's committed.
        assert TEMPLATE.name.endswith(".yml.example")


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _seed_consumer(root):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("# scratch\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _install(target, *extra):
    env = dict(os.environ)
    # Put the pytest interpreter's dir first so install.sh finds a
    # pyyaml-capable python3 (matches the other install integration suites).
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    r = subprocess.run(
        ["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, f"install failed\n{r.stdout}\n{r.stderr}"
    return r


class TestInstallShipsTemplate:
    def test_ships_unarmed_into_scripts_ci_and_records_it(self, tmp_path):
        target = _seed_consumer(tmp_path / "consumer")
        _install(target, "--packs", "", "--no-arm-hooks")
        shipped = target / "scripts" / "ci" / "sysop-checks.yml.example"
        assert shipped.is_file(), "CI template not shipped to scripts/ci/"
        # Parses after shipping (no placeholder substitution mangled it).
        yaml.safe_load(shipped.read_text(encoding="utf-8"))
        # Recorded in the lock so --update / uninstall track it.
        lock = (target / ".claude" / "sysop.lock").read_text(encoding="utf-8")
        assert "scripts/ci/sysop-checks.yml.example" in lock, "not in lock managed_paths"
        # UNARMED: install must never drop an active workflow into the
        # consumer's .github/workflows/ (that would run on their Actions
        # minutes without consent).
        assert not (target / ".github" / "workflows").exists(), \
            "install armed CI into .github/workflows/ — must stay unarmed"
