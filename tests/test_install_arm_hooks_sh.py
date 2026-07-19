"""Regression test for install.sh's git-hook arming (arm_git_hooks /
check_armed_hooks_divergence).

The bug (found during the public-cut cold-clone verification): both functions
resolved the hooks dir with ``git -C "$TARGET" rev-parse --git-path hooks``,
which returns a path *relative to $TARGET* (".git/hooks"). install.sh then used
that relative path from its *own* CWD — not $TARGET — so arming targeted
whatever directory install.sh was launched from, not the consumer project.

It fires on the documented quickstart, where CWD is the clone's parent, not the
target::

    git clone .../sysop.git
    bash sysop/install.sh /path/to/project   # CWD = clone parent, != target

install exited 0 and reported "armed", but the hooks landed in the wrong place
(a stray .git/hooks in the launch dir) and the target got none — silently,
because the post-install divergence check shared the same relative-path flaw.

The existing install.sh integration suites never caught it: subprocess.run
inherits pytest's CWD (the repo root, itself a git repo), and none asserted
arming landed in the *target*. These tests set cwd to a NON-target dir and
assert the hooks land in the target with none stray.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
HOOK_NAMES = ("pre-commit", "pre-merge-commit")


# Isolate from a contributor's global/system git config. `git rev-parse
# --git-path hooks` HONORS core.hooksPath, so a global `core.hooksPath` would
# both redden these tests spuriously and make the real install.sh arm sysop's
# hook templates into that contributor's shared dir — a destructive write
# outside tmp_path. /dev/null restores git's built-in relative `.git/hooks`
# default (the exact branch the fix anchors, so the tests stay non-tautological).
# NB: do NOT pin core.hooksPath to an absolute dir — an absolute hook_dst works
# even under the original bug, which would defeat the regression.
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
    (root / "README.md").write_text("# scratch\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _non_sample_hooks(hooks_dir):
    if not hooks_dir.is_dir():
        return set()
    return {p.name for p in hooks_dir.glob("*") if not p.name.endswith(".sample")}


def _install(target, *extra, cwd):
    """Run the real install.sh with an explicit CWD (the crux of the regression)."""
    env = dict(os.environ)
    # Put the pytest interpreter's dir first so install.sh finds a
    # pyyaml-capable python3 (matches the other install integration suites).
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    # Isolate install.sh's own git calls from a contributor's global
    # core.hooksPath (see _GIT_ISOLATION note above).
    env.update(_GIT_ISOLATION)
    r = subprocess.run(
        ["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env, cwd=str(cwd),
    )
    assert r.returncode == 0, f"install failed\n{r.stdout}\n{r.stderr}"
    return r


class TestArmHooksLandInTarget:
    def test_arms_into_target_when_launched_from_non_target_cwd(self, tmp_path):
        # Documented quickstart shape: the launch dir is a plain (non-git) dir
        # that is NOT the target. Under the bug the hooks never reach the target.
        launch = tmp_path / "launchdir"
        launch.mkdir()
        target = _seed_consumer(tmp_path / "consumer")

        _install(target, "--packs", "", cwd=launch)

        hooks_dir = target / ".git" / "hooks"
        for base in HOOK_NAMES:
            armed = hooks_dir / base
            assert armed.is_file(), f"{base} not armed into target/.git/hooks/"
            assert os.access(armed, os.X_OK), f"{base} armed but not executable"
            # It's the real template, not an empty/placeholder file.
            template = target / "sysop" / "scripts" / "hooks" / base
            assert armed.read_bytes() == template.read_bytes(), \
                f"{base} armed body differs from sysop/scripts/hooks/{base}"

    def test_no_stray_git_hooks_in_non_repo_launch_dir(self, tmp_path):
        launch = tmp_path / "launchdir"
        launch.mkdir()
        target = _seed_consumer(tmp_path / "consumer")

        _install(target, "--packs", "", cwd=launch)

        # The launch dir is not a git repo; the bug created a bogus .git/hooks
        # there. The fix must leave it untouched.
        assert not (launch / ".git").exists(), \
            "install created a stray .git in the (non-target) launch dir"

    def test_does_not_arm_into_a_different_launch_dir_git_repo(self, tmp_path):
        # The nastier variant: CWD is *another* git repo (e.g. the sysop clone
        # itself). The bug armed hooks into THAT repo, not the target.
        other = _seed_consumer(tmp_path / "other_repo")
        before = _non_sample_hooks(other / ".git" / "hooks")
        target = _seed_consumer(tmp_path / "consumer")

        _install(target, "--packs", "", cwd=other)

        for base in HOOK_NAMES:
            assert (target / ".git" / "hooks" / base).is_file(), \
                f"{base} not armed into target"
        # The unrelated launch-dir repo's hooks must be untouched.
        after = _non_sample_hooks(other / ".git" / "hooks")
        assert after == before, \
            "install armed hooks into the launch-dir git repo instead of the target"
