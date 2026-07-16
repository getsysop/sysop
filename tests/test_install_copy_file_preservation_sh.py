"""Integration tests for install.sh's Phase-24b managed-path preservation
(copy_file), Phase 105.

On `--update`, a managed path under `scripts/` or `scripts/hooks/` that the
consumer has modified since the last install is *preserved* (not overwritten) —
unless the consumer passes `--accept-upstream <relpath>`, which takes the new
upstream version. This is the mechanism that lets a consumer harden a shipped
script and keep the change across updates. `test_sysop_update_sh.py` only covers
the update *shim* guards; copy_file's preserve/accept-upstream branch had no test.

These drive a real fresh-install → modify → `--update` round-trip. The installer
reconstructs the previous install into a shadow tree (a detached worktree of the
Sysop repo at the lock's recorded commit) to diff against, so these exercise the
real divergence machinery. The out-of-scope companion is the non-tautological
guard: preservation must be *scoped* to scripts/*, not universal.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"

# Isolate install.sh's own git calls (worktree add for the shadow) from a
# contributor's global config, consistent with the other install suites.
_GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                   env={**os.environ, **_GIT_ISOLATION})


def _seed_consumer(root):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("# seed\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _install(target, *extra):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    env.update(_GIT_ISOLATION)
    r = subprocess.run(
        ["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, f"install failed\n{r.stdout}\n{r.stderr}"
    return r


_SENTINEL = "#SENTINEL-phase105-consumer-hardening\n"


def _fresh_install_then_modify(consumer, rel_path):
    """Fresh-install, commit it, overwrite `rel_path` with the sentinel, commit
    that too (clean tree → deterministic divergence). Returns the target file."""
    _seed_consumer(consumer)
    _install(consumer, "--packs", "")
    _git(consumer, "add", "-A")
    _git(consumer, "commit", "-qm", "install sysop")
    f = consumer / rel_path
    assert f.is_file(), f"{rel_path} should have been installed"
    f.write_text(_SENTINEL)
    _git(consumer, "add", "-A")
    _git(consumer, "commit", "-qm", "consumer hardening")
    return f


def test_update_preserves_consumer_modified_managed_script(tmp_path):
    consumer = tmp_path / "consumer"
    f = _fresh_install_then_modify(consumer, "scripts/run_checks.sh")

    r = _install(consumer, "--update", "--packs", "")
    assert "preserved: scripts/run_checks.sh" in r.stdout, r.stdout
    # Load-bearing: the consumer's edit survived the update.
    assert f.read_text() == _SENTINEL, "consumer-modified managed script was overwritten"


def test_accept_upstream_overwrites_consumer_modified_managed_script(tmp_path):
    consumer = tmp_path / "consumer"
    f = _fresh_install_then_modify(consumer, "scripts/run_checks.sh")

    r = _install(consumer, "--update", "--packs", "",
                 "--accept-upstream", "scripts/run_checks.sh")
    assert "accept-upstream: scripts/run_checks.sh" in r.stdout, r.stdout
    # The sentinel is gone — upstream was taken. (Don't assert byte-equality vs
    # the source: REPO_ROOT working-tree drift is possible; sentinel absence is
    # the robust signal.)
    assert _SENTINEL not in f.read_text(), "accept-upstream did not overwrite the file"


def test_out_of_scope_path_is_overwritten_on_update(tmp_path):
    """Preservation is scoped to scripts/* — an out-of-scope managed path
    (WORKFLOW.md) is overwritten on update regardless of consumer edits."""
    consumer = tmp_path / "consumer"
    f = _fresh_install_then_modify(consumer, "WORKFLOW.md")

    _install(consumer, "--update", "--packs", "")
    assert _SENTINEL not in f.read_text(), (
        "an out-of-scope managed path should be overwritten, not preserved"
    )
