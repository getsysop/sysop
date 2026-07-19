"""Regression guard for BeanRider ISSUE-0048 (surfaced by the TECH-0007 sysop
migration) — git's ambient discovery env must not leak into
``_resolve_canonical_locks_dir``'s ``git rev-parse --git-common-dir`` probe.

``GIT_DIR`` / ``GIT_WORK_TREE`` / ``GIT_COMMON_DIR`` / ``GIT_INDEX_FILE`` take
precedence over ``git -C``, and git exports them (absolute, from a worktree)
into every hook. Left inherited, the probe resolved tmpdir fixtures against the
*invoking* repo's ``.locks/`` — so ``validate_tasks.py --self-test`` failed
Invariant 9 inside the pre-push pytest gate and ``git push`` died from every
``/claim-task`` worktree.

The helper is duplicated verbatim across all three scripts (a deliberate
zero-dependency choice — each must import from a minimal environment). BeanRider's
own fix reached only ``validate_tasks.py``; the parametrization here keeps the
three copies in lockstep so a future one-site fix can't silently re-open the bug
in the other two.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import next_task
import scope_overlap
import validate_tasks

MODULES = [validate_tasks, next_task, scope_overlap]
MODULE_IDS = [m.__name__ for m in MODULES]

_GIT_DISCOVERY_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")


@pytest.mark.parametrize("mod", MODULES, ids=MODULE_IDS)
def test_git_discovery_env_strips_discovery_vars(mod, monkeypatch):
    """Every copy of ``_git_discovery_env`` drops the four discovery vars and
    preserves everything else."""
    for var in _GIT_DISCOVERY_VARS:
        monkeypatch.setenv(var, "/some/leaked/path")
    monkeypatch.setenv("SYSOP_SENTINEL", "keep-me")

    env = mod._git_discovery_env()

    for var in _GIT_DISCOVERY_VARS:
        assert var not in env, f"{mod.__name__}._git_discovery_env leaked {var}"
    assert env.get("SYSOP_SENTINEL") == "keep-me", (
        f"{mod.__name__}._git_discovery_env dropped an unrelated var"
    )


@pytest.mark.parametrize("mod", MODULES, ids=MODULE_IDS)
def test_locks_dir_ignores_ambient_git_dir(mod, tmp_path, monkeypatch):
    """With an absolute ``GIT_DIR`` pointing at an unrelated repo, resolution must
    fall back to the probed ``project_root``'s ``.locks/``, not the leaked repo's.

    This is the ISSUE-0048 shape as a unit test: ``project_root`` is a non-git
    tmpdir, so a correct (env-stripped) probe fails to resolve and returns
    ``<project_root>/.locks``. A *leaking* probe honors the ambient ``GIT_DIR``
    and returns the other repo's ``.locks`` instead. An **absolute** ``GIT_DIR``
    is load-bearing — git sets it relative for a normal checkout (fails to resolve,
    passes for the wrong reason) and absolute for a worktree (the real failure).
    """
    other = tmp_path / "other_repo"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True, env=os.environ.copy())
    leaked_git_dir = (other / ".git").resolve()
    assert leaked_git_dir.is_absolute()
    monkeypatch.setenv("GIT_DIR", str(leaked_git_dir))

    project_root = tmp_path / "workspace"  # a different, non-git tmpdir
    project_root.mkdir()

    resolved = mod._resolve_canonical_locks_dir(project_root)

    assert resolved == project_root / ".locks", (
        f"{mod.__name__}._resolve_canonical_locks_dir resolved {resolved} — "
        f"ambient GIT_DIR ({leaked_git_dir}) leaked past `-C`"
    )
    assert other not in resolved.parents, (
        f"{mod.__name__} resolved into the leaked repo's tree: {resolved}"
    )


def test_validate_tasks_self_test_ignores_ambient_git_env():
    """End-to-end guard lifted from BeanRider's TECH-0007 fix: ``validate_tasks.py
    --self-test`` stays hermetic with an absolute ``GIT_DIR`` in the env — the exact
    ``git push``-from-a-worktree failure. Only ``validate_tasks.py`` carries
    ``--self-test``; the two unit tests above cover ``next_task`` / ``scope_overlap``.
    """
    repo_root = Path(__file__).resolve().parent.parent
    script = repo_root / "core" / "companion" / "scripts" / "validate_tasks.py"
    git_dir = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--absolute-git-dir"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    ).stdout.strip()
    assert Path(git_dir).is_absolute(), f"fixture needs an absolute GIT_DIR, got {git_dir!r}"

    result = subprocess.run(
        [sys.executable, str(script), "--self-test"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        timeout=60,
        env={**os.environ, "GIT_DIR": git_dir},
    )
    assert result.returncode == 0, (
        f"--self-test exited {result.returncode} with GIT_DIR={git_dir} in the env; "
        "the ambient git environment is leaking into fixture validation.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
