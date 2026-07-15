"""Integration tests for core/companion/scripts/run_checks.sh (Phase 84).

`run_checks.sh` is a thin wrapper: it refuses outside a git repo, resolves the
toolchain PATH (worktree-aware `.venv`/node fallback), picks an interpreter,
then `exec`s `<repo>/scripts/run_checks_impl.py --repo-root <toplevel> "$@"`.
The Python impl is already covered by the `test_run_checks*.py` suite — these
tests lock the *bash wrapper's* contract only: the git guard, the
`--repo-root` injection + verbatim arg pass-through, and the repo-`.venv`
interpreter preference. We stub `run_checks_impl.py` with a tiny argv echo so
the wrapper is exercised without pyyaml / the real checks pipeline.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core/companion/scripts/run_checks.sh"

# Stub impl: prints its argv on one line so the wrapper's hand-off is observable.
STUB_IMPL = "import sys\nprint('IMPL_ARGV:', repr(sys.argv[1:]))\n"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo_with_stub(root):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    (root / "scripts").mkdir()
    (root / "scripts" / "run_checks_impl.py").write_text(STUB_IMPL)
    return root


def _run(cwd, *args):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True,
    )


def _impl_argv(stdout):
    """Parse the stub's `IMPL_ARGV: [...]` echo into a python list."""
    import ast
    for line in stdout.splitlines():
        if line.startswith("IMPL_ARGV:"):
            return ast.literal_eval(line[len("IMPL_ARGV:"):].strip())
    raise AssertionError(f"no IMPL_ARGV line in:\n{stdout}")


def test_not_a_git_repo_exits_1(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "Not inside a git repository" in r.stderr


def test_injects_repo_root_and_passes_mode_through(tmp_path):
    repo = _repo_with_stub(tmp_path / "repo")
    r = _run(repo, "--mode", "security")
    assert r.returncode == 0, r.stderr
    argv = _impl_argv(r.stdout)
    assert "--repo-root" in argv
    root_arg = argv[argv.index("--repo-root") + 1]
    assert os.path.realpath(root_arg) == os.path.realpath(str(repo))
    # Verbatim pass-through of the user's flags, after the injected --repo-root.
    assert argv[-2:] == ["--mode", "security"]


def test_default_invocation_injects_only_repo_root(tmp_path):
    repo = _repo_with_stub(tmp_path / "repo")
    r = _run(repo)
    assert r.returncode == 0, r.stderr
    argv = _impl_argv(r.stdout)
    assert "--mode" not in argv
    assert argv[0] == "--repo-root"
    assert len(argv) == 2  # just --repo-root <path>


def test_prefers_repo_venv_interpreter(tmp_path):
    # A repo-local .venv/bin/python3 must be preferred over PATH python3 (the
    # worktree-toolchain-resolution intent). The shim announces itself then
    # execs a real python3 so the stub impl still runs.
    real_py = shutil.which("python3")
    if real_py is None:
        pytest.skip("no python3 on PATH to back the venv shim")
    repo = _repo_with_stub(tmp_path / "repo")
    venv_bin = repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    shim = venv_bin / "python3"
    # exec the real interpreter by ABSOLUTE path: run_checks.sh prepends this
    # .venv/bin to PATH, so a bare `python3` would re-resolve to this shim
    # (an infinite exec loop).
    shim.write_text(f'#!/bin/sh\necho "VENV_PYTHON_USED"\nexec {real_py} "$@"\n')
    shim.chmod(0o755)
    r = _run(repo, "--mode", "quality")
    assert r.returncode == 0, r.stderr
    assert "VENV_PYTHON_USED" in r.stdout, "wrapper did not prefer repo .venv python"
    assert _impl_argv(r.stdout)[-2:] == ["--mode", "quality"]
