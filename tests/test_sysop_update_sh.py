"""Integration tests for core/companion/scripts/sysop-update.sh (Phase 84).

`sysop-update.sh` is the consumer-root shim around `install.sh --update`: it
validates `$SYSOP_SRC` (set / a dir / holds install.sh / is a git tree) and the
CWD (a git repo), then `exec`s `bash "$SYSOP_SRC/install.sh" <consumer-root>
--update "$@"`. Five guards are pure — four need no git repo at all, just env
manipulation. The success path is stubbed with a fake `install.sh` (a git repo)
so the hand-off argv contract and exit-code propagation are locked without
running the real 100 KB installer.
"""
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core/companion/scripts/sysop-update.sh"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _git_repo(root):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")  # ignore a contributor's global signing
    return root


def _run(cwd, sysop_src, *args):
    """sysop_src=None → SYSOP_SRC popped from the env (the unset-guard case)."""
    env = dict(os.environ)
    if sysop_src is None:
        env.pop("SYSOP_SRC", None)
    else:
        env["SYSOP_SRC"] = str(sysop_src)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True, env=env,
    )


class TestSysopSrcGuards:
    def test_unset_sysop_src_exits_1(self, tmp_path):
        r = _run(tmp_path, None)
        assert r.returncode == 1
        assert "SYSOP_SRC is not set" in r.stderr

    def test_missing_dir_exits_1(self, tmp_path):
        r = _run(tmp_path, tmp_path / "does-not-exist")
        assert r.returncode == 1
        assert "directory not found" in r.stderr

    def test_dir_without_install_sh_exits_1(self, tmp_path):
        empty = tmp_path / "sysop"
        empty.mkdir()
        r = _run(tmp_path, empty)
        assert r.returncode == 1
        assert "no install.sh found" in r.stderr

    def test_install_sh_but_not_git_tree_exits_1(self, tmp_path):
        src = tmp_path / "sysop"
        src.mkdir()
        (src / "install.sh").write_text("echo hi\n")  # present but no git init
        r = _run(tmp_path, src)
        assert r.returncode == 1
        assert "not a git working tree" in r.stderr


class TestConsumerGuard:
    def test_cwd_not_a_git_repo_exits_1(self, tmp_path):
        # All SYSOP_SRC guards pass; only the consumer-root check fails.
        src = _git_repo(tmp_path / "sysop")
        (src / "install.sh").write_text("echo hi\n")
        _git(src, "add", "-A")
        _git(src, "commit", "-qm", "seed")
        non_git = tmp_path / "not-a-repo"
        non_git.mkdir()
        r = _run(non_git, src)
        assert r.returncode == 1
        assert "run this script from inside a git repo" in r.stderr


class TestHandoff:
    def test_forwards_argv_and_propagates_exit_code(self, tmp_path):
        # A fake install.sh (in a git repo) echoes its argv and exits 7.
        src = _git_repo(tmp_path / "sysop")
        (src / "install.sh").write_text('echo "FAKE_INSTALL: $*"\nexit 7\n')
        _git(src, "add", "-A")
        _git(src, "commit", "-qm", "seed")
        consumer = _git_repo(tmp_path / "consumer")

        r = _run(consumer, src, "--dry-run", "--force")
        # exec means the fake installer's exit code becomes ours.
        assert r.returncode == 7
        # Scope-note lines print before the hand-off.
        assert "Plugin path auto-updates" in r.stdout
        assert "syncs bash-installer-delivered content only" in r.stdout
        # Consumer root + --update + the forwarded flags, in order.
        line = next(ln for ln in r.stdout.splitlines() if ln.startswith("FAKE_INSTALL:"))
        parts = line[len("FAKE_INSTALL:"):].split()
        assert os.path.realpath(parts[0]) == os.path.realpath(str(consumer))
        assert parts[1:] == ["--update", "--dry-run", "--force"]
