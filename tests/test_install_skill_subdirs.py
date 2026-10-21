"""Phase 383 (`Q-409` P0): the installer delivers a skill's subdirectories.

`install_skills` copied each skill directory's top-level files and nothing
deeper, so a split skill's `steps/` never reached a consumer, the lock did not
list it, and the install exited 0. Measured by Phase 382 on its probe tree
(`tools/RUNNER_CORE_SPLIT_SPEC.md` § 2).

No shipped skill has a subdirectory yet, so these plant one in a scratch copy
of the source and drive the real install.sh against it: a fresh install, a loop
install (a kept skill's nested file ships; an excluded skill's and an excluded
`_shared/` directory's do not), an `--update` that adds one and an `--update`
that drops one. The drop case runs twice: once on a tracked target (the sweep's
`git rm`) and once where `.claude/skills/` is gitignored (its `rm -f`).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}

# Planted in the scratch source. codebase-review and fanout-evidence are kept by
# loop mode; review-close and ui-verify are excluded by it.
NESTED = {
    "core/skills/codebase-review/steps/1-pre.md": "step one\n",
    "core/skills/codebase-review/steps/deeper/2.md": "step two\n",
    "core/skills/review-close/steps/1-pre.md": "close step\n",
    "core/skills/_shared/fanout-evidence/part.md": "kept partial\n",
    "core/skills/_shared/ui-verify/part.md": "excluded partial\n",
    # Named like an excluded `_shared/` partial, but below the top level of
    # `_shared/` or in another skill: loop mode filters only `_shared/`'s own entries.
    "core/skills/codebase-review/steps/ui-verify.md": "not a partial\n",
    "core/skills/_shared/fanout-evidence/ui-verify.md": "not a partial either\n",
    "core/skills/security-audit/ui-verify/part.md": "a kept skill's own directory\n",
    # Sorts last under `steps/`, so the sweep's last removal empties two levels.
    "core/skills/codebase-review/steps/zz/last.md": "deepest\n",
}
# Filtered at every depth, as at the top level.
SKIPPED = {
    "core/skills/codebase-review/steps/__pycache__/x.cpython-312.pyc": "pyc\n",
    "core/skills/codebase-review/steps/.hidden.md": "dotfile\n",
    "core/skills/codebase-review/.dotdir/a.md": "dot dir\n",
}
LINKED_DIR = "core/skills/codebase-review/linked"   # -> steps; never followed


def _env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    env.update(_GIT_ISOLATION)
    return env


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                          text=True, env=_env()).stdout.strip()


def _identity(repo):
    _git(repo, "config", "user.email", "test@test")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "commit.gpgsign", "false")


def _install(src, target, *extra):
    return subprocess.run(
        ["bash", str(src / "install.sh"), str(target), *extra, "--no-arm-hooks", "--yes"],
        capture_output=True, text=True, env=_env(), cwd=str(target),
    )


def _plant(src, files):
    for rel, body in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)


@pytest.fixture(scope="module")
def pristine_src(tmp_path_factory):
    """A committed source copy with no planted files."""
    src = tmp_path_factory.mktemp("p383") / "src"
    src.mkdir()
    shutil.copy2(REPO_ROOT / "install.sh", src / "install.sh")
    for d in ("core", "packs"):
        shutil.copytree(REPO_ROOT / d, src / d,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv"))
    _git(src, "init", "-q", "-b", "main")
    _identity(src)
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "source")
    return src


@pytest.fixture
def src(pristine_src, tmp_path):
    s = tmp_path / "src"
    subprocess.run(["git", "clone", "-q", str(pristine_src), str(s)], check=True,
                   capture_output=True, env=_env())
    _identity(s)
    return s


def _planted(src):
    _plant(src, NESTED)
    _plant(src, SKIPPED)
    (src / LINKED_DIR).symlink_to("steps")
    _git(src, "add", "-A", "-f")
    _git(src, "commit", "-qm", "plant")
    return src


def _target(tmp_path, gitignore=None):
    t = tmp_path / "tgt"
    t.mkdir()
    _git(t, "init", "-q", "-b", "main")
    _identity(t)
    (t / "README.md").write_text("# scratch\n")
    if gitignore:
        (t / ".gitignore").write_text(gitignore)
    _git(t, "add", "-A")
    _git(t, "commit", "-qm", "seed")
    return t


def _installed_rel(rel):
    return ".claude/skills/" + rel[len("core/skills/"):]


def _managed(target):
    return set(json.loads((target / ".claude/sysop.lock").read_text())["managed_paths"])


def test_a_fresh_install_writes_nested_files_and_the_lock_lists_them(src, tmp_path):
    _planted(src)
    t = _target(tmp_path)
    res = _install(src, t, "--packs", "python")
    assert res.returncode == 0, res.stdout + res.stderr
    managed = _managed(t)
    for rel, body in NESTED.items():
        dst = _installed_rel(rel)
        assert (t / dst).read_text() == body, dst
        assert dst in managed, dst


def test_skipped_entries_are_skipped_at_every_depth(src, tmp_path):
    _planted(src)
    t = _target(tmp_path)
    assert _install(src, t, "--packs", "python").returncode == 0
    managed = _managed(t)
    for rel in SKIPPED:
        dst = _installed_rel(rel)
        assert not (t / dst).exists(), dst
        assert dst not in managed, dst
    linked = t / _installed_rel(LINKED_DIR)
    assert not linked.exists() and not linked.is_symlink()
    assert not any(m.startswith(_installed_rel(LINKED_DIR) + "/") for m in managed)


def test_a_loop_install_ships_kept_nested_files_and_filters_excluded_ones(src, tmp_path):
    _planted(src)
    t = _target(tmp_path)
    res = _install(src, t, "--packs", "", "--mode", "loop")
    assert res.returncode == 0, res.stdout + res.stderr
    managed = _managed(t)
    kept = ["core/skills/codebase-review/steps/1-pre.md",
            "core/skills/codebase-review/steps/deeper/2.md",
            "core/skills/_shared/fanout-evidence/part.md",
            "core/skills/codebase-review/steps/ui-verify.md",
            "core/skills/_shared/fanout-evidence/ui-verify.md",
            "core/skills/security-audit/ui-verify/part.md",
            "core/skills/codebase-review/steps/zz/last.md"]
    dropped = ["core/skills/review-close/steps/1-pre.md",
               "core/skills/_shared/ui-verify/part.md"]
    for rel in kept:
        assert (t / _installed_rel(rel)).is_file(), rel
        assert _installed_rel(rel) in managed, rel
    for rel in dropped:
        assert not (t / _installed_rel(rel)).exists(), rel
        assert _installed_rel(rel) not in managed, rel
    assert not (t / ".claude/skills/_shared/ui-verify").exists()


def test_an_update_from_a_source_that_adds_a_nested_file_installs_it(src, tmp_path):
    t = _target(tmp_path)
    assert _install(src, t, "--packs", "python").returncode == 0
    _git(t, "add", "-A")
    _git(t, "commit", "-qm", "installed")
    _planted(src)
    res = _install(src, t, "--update")
    assert res.returncode == 0, res.stdout + res.stderr
    managed = _managed(t)
    for rel, body in NESTED.items():
        dst = _installed_rel(rel)
        assert (t / dst).read_text() == body, dst
        assert dst in managed, dst


@pytest.mark.parametrize("gitignore", [None, ".claude/skills/\n"],
                         ids=["tracked", "gitignored"])
def test_an_update_from_a_source_that_drops_a_nested_file_sweeps_it(src, tmp_path, gitignore):
    _planted(src)
    t = _target(tmp_path, gitignore)
    assert _install(src, t, "--packs", "python").returncode == 0
    _git(t, "add", "-A")
    _git(t, "commit", "-qm", "installed")
    _git(src, "rm", "-rq", "core/skills/codebase-review/steps")
    _git(src, "commit", "-qm", "drop")
    res = _install(src, t, "--update")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "remove: .claude/skills/codebase-review/steps/1-pre.md" in res.stdout
    steps = t / ".claude/skills/codebase-review/steps"
    # Gone, directory and all: `git rm` prunes it, and the `rm -f` fallback
    # used to leave it behind empty.
    assert not steps.exists(), sorted(p.name for p in steps.iterdir())
    assert (t / ".claude/skills/codebase-review/SKILL.md").is_file()
    managed = _managed(t)
    assert not any(m.startswith(".claude/skills/codebase-review/steps/") for m in managed)
    # The sibling skill's nested file is untouched by the sweep.
    assert (t / ".claude/skills/review-close/steps/1-pre.md").is_file()


@pytest.mark.parametrize("gitignore", [None, ".claude/skills/\n"],
                         ids=["tracked", "gitignored"])
def test_a_dropped_nested_file_spares_the_consumers_own_files(src, tmp_path, gitignore):
    """Phase 383's round. The empty-parent walk must stop at a directory that still
    holds the consumer's file, and `git rm` must read a lock path literally: a
    shipped file named `*.md` once matched the consumer's tracked
    `steps/zz/mine/keep.md` across `/`."""
    _planted(src)
    _plant(src, {"core/skills/codebase-review/steps/*.md": "a literal star\n"})
    _git(src, "add", "-A", "-f")
    _git(src, "commit", "-qm", "a star")
    t = _target(tmp_path, gitignore)
    assert _install(src, t, "--packs", "python").returncode == 0
    assert (t / ".claude/skills/codebase-review/steps/*.md").is_file()
    steps = t / ".claude/skills/codebase-review/steps"
    mine = [steps / "zz/mine/keep.md", steps / "sub/keep.md"]
    for p in mine:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("the consumer's\n")
    _git(t, "add", "-A")
    _git(t, "commit", "-qm", "installed, plus mine")
    _git(src, "rm", "-rq", "core/skills/codebase-review/steps")
    _git(src, "commit", "-qm", "drop")
    res = _install(src, t, "--update")
    assert res.returncode == 0, res.stdout + res.stderr
    for p in mine:
        assert p.read_text() == "the consumer's\n", p
    assert not (steps / "*.md").exists()
    assert not (steps / "1-pre.md").exists()
    assert not (steps / "zz/last.md").exists()
    if gitignore is None:
        assert _git(t, "status", "--porcelain", "--", ".claude/skills/codebase-review/steps/zz/mine",
                    ".claude/skills/codebase-review/steps/sub") == ""


def test_a_lock_path_that_leaves_the_target_is_not_swept(src, tmp_path):
    """A hand-edited lock entry with a `..` segment reached `rm -f` outside the
    tree, and the empty-parent walk climbed from there (Phase 383's round)."""
    t = _target(tmp_path)
    assert _install(src, t, "--packs", "python").returncode == 0
    outside = tmp_path / "outside" / "sub" / "f"
    outside.parent.mkdir(parents=True)
    outside.write_text("not ours\n")
    lock = t / ".claude/sysop.lock"
    data = json.loads(lock.read_text())
    data["managed_paths"] += ["../outside/sub/f", str(outside)]
    lock.write_text(json.dumps(data, indent=2) + "\n")
    _git(t, "add", "-A")
    _git(t, "commit", "-qm", "installed, lock hand-edited")
    res = _install(src, t, "--update")
    assert res.returncode == 0, res.stdout + res.stderr
    assert outside.read_text() == "not ours\n"
    assert "remove: ../outside" not in res.stdout
