"""Integration tests for install.sh's unreachable-ancestor update fallback
(Phase 99, tester round).

When `install.sh --update` cannot reconstruct the OLD install (the lock's
sysop_commit is unreachable — e.g. force-pushed off every ref, as in the tester
snapshot-mirror update flow, where a plain `git fetch` can't restore it), Phase
24b previously hard-aborted. That made the documented tester update flow
unusable for a consumer who never touched a managed script.

The fallback proceeds WHEN the pre-update snapshot found no dirty managed paths
(nothing uncommitted to preserve), warning about the one case it cannot verify
without the ancestor: a *committed* edit to a managed script. It still aborts
when managed paths ARE dirty (the ISSUE-0024/0025 preservation guarantee).

These drive the real installer against scratch git consumers (the
test_install_*.py pattern).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
BOGUS_SHA = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"  # valid-format, unreachable


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _install(target, *extra):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    return subprocess.run(
        ["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env,
    )


def _installed_with_unreachable_ancestor(root):
    """Fresh-install, then rewrite the lock's sysop_commit to an unreachable SHA
    (the force-pushed-away state) so the next --update cannot reconstruct."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "commit", "-qm", "init", "--allow-empty")
    r = _install(root, "--packs", "")
    assert r.returncode == 0, r.stdout + r.stderr
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "sysop install")
    lock = root / ".claude/sysop.lock"
    data = json.loads(lock.read_text())
    data["sysop_commit"] = BOGUS_SHA
    lock.write_text(json.dumps(data, indent=2))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "bogus lock (unreachable ancestor)")
    return root


def test_unreachable_ancestor_clean_tree_proceeds(tmp_path):
    target = _installed_with_unreachable_ancestor(tmp_path / "c")
    r = _install(target, "--update")
    combined = r.stdout + r.stderr
    assert r.returncode == 0, f"clean-tree update should proceed:\n{combined}"
    assert "committed-edit detection skipped" in combined, combined


def test_unreachable_ancestor_dirty_managed_path_aborts(tmp_path):
    """Non-tautological guard: the fallback does NOT blanket-skip preservation.
    A dirty in-scope managed path with an unreachable ancestor still aborts."""
    target = _installed_with_unreachable_ancestor(tmp_path / "c")
    script = target / "scripts/run_checks.sh"
    script.write_text(script.read_text() + "\n# local edit\n")  # uncommitted
    r = _install(target, "--update")
    combined = r.stdout + r.stderr
    assert r.returncode == 1, f"dirty-tree update should abort:\n{combined}"
    assert "requires a recoverable ancestor" in combined, combined
