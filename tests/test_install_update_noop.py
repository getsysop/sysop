"""`Q-034` (Phase 370): an `--update` whose source has not moved says so.

`install.sh --update` closed with `was: <sha>` / `now: <sha>` and had no branch
for the two being equal. Reproduced at `12e8285`: install, commit, `--update`
from the same clone — 101 `copy:` lines, a clean `git status`, exit 0, and the
only tell two identical SHAs nothing asks the reader to compare. The likeliest
cause in the field is a re-clone with `$SYSOP_SRC` still pointing at the old
one, so the line names the source clone that was actually read.

These drive the real install.sh against a scratch source clone (the
`test_install_source_dirty.py` fixture shape), so the outcome does not depend
on whether the live repo happens to be dirty.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


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
        ["bash", str(src / "install.sh"), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=_env(), cwd=str(target),
    )


@pytest.fixture(scope="module")
def pristine(tmp_path_factory):
    """A clean committed source, and a target installed from it and committed."""
    base = tmp_path_factory.mktemp("q034")
    src = base / "src"
    src.mkdir()
    shutil.copy2(REPO_ROOT / "install.sh", src / "install.sh")
    for d in ("core", "packs"):
        shutil.copytree(REPO_ROOT / d, src / d,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv"))
    _git(src, "init", "-q", "-b", "main")
    _identity(src)
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "source")

    tgt = base / "tgt"
    tgt.mkdir()
    _git(tgt, "init", "-q", "-b", "main")
    _identity(tgt)
    (tgt / "README.md").write_text("# scratch\n")
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-qm", "seed")
    res = _install(src, tgt, "--packs", "python", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-qm", "installed")
    return src, tgt


@pytest.fixture
def setup(pristine, tmp_path):
    """Per-test copies: a clone of the source and a copy of the installed target,
    so a test that moves the source or updates the target cannot leak."""
    src0, tgt0 = pristine
    src = tmp_path / "src"
    subprocess.run(["git", "clone", "-q", str(src0), str(src)], check=True,
                   capture_output=True, env=_env())
    _identity(src)
    tgt = tmp_path / "tgt"
    shutil.copytree(tgt0, tgt, symlinks=True)
    return src, tgt


def _lines(res):
    return (res.stdout + res.stderr).splitlines()


def test_an_update_from_an_unmoved_source_says_so_and_names_the_source(setup):
    src, tgt = setup
    head = _git(src, "rev-parse", "HEAD")
    res = _install(src, tgt, "--update")
    assert res.returncode == 0, res.stdout + res.stderr
    out = res.stdout + res.stderr
    assert f"already at {head[:12]}" in out, out
    assert any(ln.strip() == f"• source read: {src}" for ln in _lines(res)), out
    # The pair is replaced, not kept beside the line.
    assert not re.search(r"^\s*was:\s", out, re.M), out
    assert "update that clone" in out, out
    # And it does not then say the opposite: the tree is clean (Phase 148), so the
    # closing line names that instead of "uncommitted" (Phase 370's integrator).
    assert _git(tgt, "status", "--porcelain") == "", out
    assert "there is nothing to commit" in out, out
    assert "The update is uncommitted" not in out, out
    assert "BACKWARDS" not in out and "cannot tell forward from back" not in out, out


def test_an_update_from_a_moved_source_still_reports_was_and_now(setup):
    """Control: the equal-branch must not swallow a real update."""
    src, tgt = setup
    old = _git(src, "rev-parse", "HEAD")
    p = src / "core" / "companion" / "scripts" / "self_check.sh"
    p.write_text(p.read_text() + "\n# phase370 moved\n")
    _git(src, "commit", "-qam", "move")
    new = _git(src, "rev-parse", "HEAD")
    res = _install(src, tgt, "--update")
    assert res.returncode == 0, res.stdout + res.stderr
    out = res.stdout + res.stderr
    assert re.search(rf"^\s*was:\s+{old[:12]}$", out, re.M), out
    assert re.search(rf"^\s*now:\s+{new[:12]}$", out, re.M), out
    assert "already at" not in out, out
    assert "The update is uncommitted" in out, out
    assert "there is nothing to commit" not in out, out
    # `Q-260`: a forward move with the installed commit in the clone says nothing more.
    assert "BACKWARDS" not in out and "cannot tell forward from back" not in out, out


def test_an_unmoved_ref_update_names_the_clone_not_the_temp_worktree(setup):
    """Under --ref, $REPO_ROOT is a temp worktree the EXIT trap deletes; naming it
    would point the consumer at a path that no longer exists."""
    src, tgt = setup
    head = _git(src, "rev-parse", "HEAD")
    res = _install(src, tgt, "--update", "--ref", "HEAD")
    assert res.returncode == 0, res.stdout + res.stderr
    out = res.stdout + res.stderr
    assert f"already at {head[:12]}" in out, out
    assert any(ln.strip() == f"• source read: {src}" for ln in _lines(res)), out
    assert "--ref HEAD names the commit already installed" in out, out


# --- the divergence check's temporary worktree (Phase 370's integrator) -----------------
# `--update` materialises the OLD Sysop as a worktree of the source repo to rebuild what
# it installed. Registered in the SOURCE's `git worktree list`, so a leak outlives the run:
# one was found left in this repo's own list after a full-suite run (detached at the
# installed commit, tree clean). Its removal was `|| true` and it was the one temp resource
# the EXIT trap did not cover.

def _git_shim(tmp_path, body):
    real = shutil.which("git")
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "git").write_text(f"#!/bin/bash\nREAL={real}\n{body}\nexec \"$REAL\" \"$@\"\n")
    (shim / "git").chmod(0o755)
    return dict(_env(), PATH=f"{shim}:{os.environ['PATH']}")


def _worktrees(repo):
    return [ln for ln in _git(repo, "worktree", "list", "--porcelain").splitlines()
            if ln.startswith("worktree ")]


def _remove_extra_worktrees(repo):
    """With the real git, in a `finally`: a leaked worktree lives in the system temp dir,
    outside pytest's rotation, so a failing run must not leave one (Phase 370's round)."""
    for line in _worktrees(repo)[1:]:
        subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force",
                        line[len("worktree "):]], capture_output=True, env=_env())


def test_an_update_interrupted_after_the_divergence_worktree_exists_removes_it(setup, tmp_path):
    src, tgt = setup
    # SIGTERM the installer (git's parent: the call is not in a subshell) the moment the
    # worktree exists — the shape of an interrupt before the removal line.
    env = _git_shim(tmp_path, 'if [ "$3" = worktree ] && [ "$4" = add ]; then '
                              '"$REAL" "$@"; rc=$?; kill -TERM "$PPID"; exit $rc; fi')
    before = _worktrees(src)
    try:
        res = subprocess.run(["bash", str(src / "install.sh"), str(tgt), "--update", "--yes"],
                             cwd=str(tgt), capture_output=True, text=True, env=env,
                             stdin=subprocess.DEVNULL, timeout=600)
        assert res.returncode != 0, res.stdout + res.stderr   # it really was interrupted
        assert _worktrees(src) == before, (_worktrees(src), res.stdout + res.stderr)
    finally:
        _remove_extra_worktrees(src)


def test_an_interrupted_ref_update_leaves_no_worktree(setup, tmp_path):
    """Under `--ref` two worktrees of the source exist at once (the pin and the divergence
    check's); SIGTERM after the second `add` must leave neither registered (Phase 370's round,
    lens 2: a swapped trap order leaked one, and no test interrupted a `--ref` update)."""
    src, tgt = setup
    env = _git_shim(tmp_path, 'if [ "$3" = worktree ] && [ "$4" = add ]; then "$REAL" "$@"; rc=$?; '
                              'n=$(cat "$HOME/.adds" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$HOME/.adds"; '
                              '[ "$n" -ge 2 ] && kill -TERM "$PPID"; exit $rc; fi')
    env["HOME"] = str(tmp_path)
    before = _worktrees(src)
    try:
        res = subprocess.run(["bash", str(src / "install.sh"), str(tgt), "--update", "--ref", "HEAD",
                              "--yes"], cwd=str(tgt), capture_output=True, text=True, env=env,
                             stdin=subprocess.DEVNULL, timeout=600)
        assert (tmp_path / ".adds").read_text().strip() == "2", res.stdout + res.stderr
        assert res.returncode != 0, res.stdout + res.stderr
        assert _worktrees(src) == before, (_worktrees(src), res.stdout + res.stderr)
    finally:
        _remove_extra_worktrees(src)


def test_the_closing_line_reads_the_target_not_the_cwd(setup, tmp_path):
    """Every other test runs with cwd == target; from elsewhere, a status read of the cwd
    would describe the wrong tree (Phase 370's round, lens 2)."""
    src, tgt = setup
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _git(elsewhere, "init", "-q", "-b", "main")
    (elsewhere / "dirt.txt").write_text("x\n")
    res = subprocess.run(["bash", str(src / "install.sh"), str(tgt), "--update", "--yes"],
                         cwd=str(elsewhere), capture_output=True, text=True, env=_env(),
                         stdin=subprocess.DEVNULL, timeout=600)
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    assert "there is nothing to commit" in out, out


def test_a_failed_divergence_worktree_removal_is_reported(setup, tmp_path):
    src, tgt = setup
    env = _git_shim(tmp_path, 'if [ "$3" = worktree ] && [ "$4" = remove ]; then exit 1; fi')
    res = subprocess.run(["bash", str(src / "install.sh"), str(tgt), "--update", "--yes"],
                         cwd=str(tgt), capture_output=True, text=True, env=env,
                         stdin=subprocess.DEVNULL, timeout=600)
    out = res.stdout + res.stderr
    try:
        assert "could not remove its temporary worktree" in out, out
        assert f"git -C {src} worktree remove --force" in out, out
    finally:
        _remove_extra_worktrees(src)   # the shim kept it
    assert len(_worktrees(src)) == 1


def test_a_no_op_update_over_unrelated_dirt_does_not_claim_it(setup):
    """An update tolerates unrelated dirt, so a dirty tree afterwards is not the
    update's doing (Phase 370's round, lens 1)."""
    src, tgt = setup
    (tgt / "scratch-unrelated.txt").write_text("mine\n")
    readme = tgt / "README.md"
    readme.write_text(readme.read_text() + "edited\n")
    res = _install(src, tgt, "--update")
    assert res.returncode == 0, res.stdout + res.stderr
    out = res.stdout + res.stderr
    assert "its uncommitted changes were there before it ran" in out, out
    assert "The update is uncommitted" not in out, out


def test_a_failed_removal_under_ref_names_the_clone(setup, tmp_path):
    """Under --ref, $REPO_ROOT is a temp worktree the EXIT trap deletes; a remedy
    naming it could not run (Phase 370's round, lens 1)."""
    src, tgt = setup
    env = _git_shim(tmp_path, 'if [ "$3" = worktree ] && [ "$4" = remove ] && [ ! -e "$HOME/.r370" ]; '
                              'then : > "$HOME/.r370"; exit 1; fi')
    env["HOME"] = str(tmp_path)
    res = subprocess.run(["bash", str(src / "install.sh"), str(tgt), "--update", "--ref", "HEAD",
                          "--yes"], cwd=str(tgt), capture_output=True, text=True, env=env,
                         stdin=subprocess.DEVNULL, timeout=600)
    out = res.stdout + res.stderr
    try:
        assert "could not remove its temporary worktree" in out, out
        assert f"git -C {src} worktree remove --force" in out, out
    finally:
        _remove_extra_worktrees(src)
    assert len(_worktrees(src)) == 1


def test_an_unmoved_but_dirty_source_says_its_changes_were_copied(setup):
    src, tgt = setup
    p = src / "core" / "companion" / "docs" / "WORKFLOW.md"
    p.write_text(p.read_text() + "\n<!-- uncommitted -->\n")
    res = _install(src, tgt, "--update")
    out = res.stdout + res.stderr
    assert "already at" in out, out
    assert "its uncommitted changes WERE copied" in out, out


# --- `Q-260` (Phase 441): an update that moves the install backwards says so -------------
# A $SYSOP_SRC still naming an older clone after a re-clone installed that clone's tree at
# exit 0, and `was:`/`now:` were the only tell. `Q-034` covers the clone that has not moved;
# these cover the one that moves backwards. Direction is knowable only when the installed
# commit is in the clone read; otherwise the closing lines say so conditionally, because a
# forward update from a re-rooted clone lands in the same branch.

def _advance(src, tgt):
    """Commit once in *src*, update *tgt* to it and commit the target; return the new HEAD."""
    p = src / "core" / "companion" / "scripts" / "self_check.sh"
    p.write_text(p.read_text() + "\n# q260 newer\n")
    _git(src, "commit", "-qam", "newer")
    res = _install(src, tgt, "--update")
    assert res.returncode == 0, res.stdout + res.stderr
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-qm", "updated")
    return _git(src, "rev-parse", "HEAD")


def test_an_update_from_an_older_checkout_of_the_same_clone_says_backwards(setup):
    src, tgt = setup
    newer = _advance(src, tgt)
    _git(src, "checkout", "-q", "-B", "older", "HEAD~1")
    res = _install(src, tgt, "--update")
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    assert "this update moved Sysop BACKWARDS" in out, out
    assert f"is an ancestor of the installed {newer[:12]}" in out, out
    assert any(ln.strip().startswith(f"• source read: {src} ") for ln in _lines(res)), out
    assert f"--ref {newer[:12]}" in out, out


def test_an_older_ref_is_a_note_not_a_warning(setup):
    src, tgt = setup
    newer = _advance(src, tgt)
    res = _install(src, tgt, "--update", "--ref", "HEAD~1")
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    assert f"--ref HEAD~1 is older than the installed {newer[:12]}" in out, out
    assert "BACKWARDS" not in out, out


def test_an_update_from_a_clone_lacking_the_installed_commit_says_it_cannot_tell(setup, pristine,
                                                                                  tmp_path):
    """The filed shape: installed from a newer clone, $SYSOP_SRC still at one that lacks it."""
    src, tgt = setup
    newer = _advance(src, tgt)
    stale = tmp_path / "stale"
    subprocess.run(["git", "clone", "-q", str(pristine[0]), str(stale)], check=True,
                   capture_output=True, env=_env())
    res = _install(stale, tgt, "--update")
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    assert f"the installed {newer[:12]} is not in the source read ({stale})" in out, out
    assert "point $SYSOP_SRC at the newer clone and re-run the update" in out, out
    # The pre-overwrite block's by-SHA fetch remedy is qualified the same way.
    assert "A clone OLDER than the one you last installed from lacks that commit too" in out, out
    assert "point $SYSOP_SRC at the newer clone instead" in out, out
    assert "BACKWARDS" not in out, out


def test_a_forward_update_from_a_re_rooted_clone_claims_no_direction(setup, tmp_path):
    """Control: every consumer's first update after the public repo's re-root lands in the
    unreachable branch going FORWARD, so it must not be told it went backwards."""
    src, tgt = setup
    rooted = tmp_path / "rooted"
    shutil.copytree(src, rooted, ignore=shutil.ignore_patterns(".git"))
    p = rooted / "core" / "companion" / "scripts" / "self_check.sh"
    p.write_text(p.read_text() + "\n# q260 re-rooted\n")
    _git(rooted, "init", "-q", "-b", "main")
    _identity(rooted)
    _git(rooted, "add", "-A")
    _git(rooted, "commit", "-qm", "root")
    res = _install(rooted, tgt, "--update")
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    assert "cannot tell forward from back" in out, out
    assert "BACKWARDS" not in out, out


def test_an_update_to_a_sibling_branch_says_it_cannot_tell(setup):
    """Round 1, lens A: the first cut read "not an ancestor" as forward, so a move to another
    line of history, which drops the installed commit's changes, printed `was:`/`now:` alone."""
    src, tgt = setup
    newer = _advance(src, tgt)
    _git(src, "checkout", "-q", "-B", "sibling", "HEAD~1")
    p = src / "core" / "companion" / "docs" / "WORKFLOW.md"
    p.write_text(p.read_text() + "\n<!-- q260 sibling -->\n")
    _git(src, "commit", "-qam", "sibling")
    res = _install(src, tgt, "--update")
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    assert f"neither {newer[:12]} (installed) nor" in out, out
    assert "they are gone from this install" in out, out
    assert "BACKWARDS" not in out, out


def test_a_non_git_source_says_it_is_not_a_clone(setup, tmp_path):
    """Round 1, lens A: a tarball-shaped source got the clone sentence, and \\$SYSOP_SRC advice
    the shim would refuse."""
    src, tgt = setup
    flat = tmp_path / "flat"
    shutil.copytree(src, flat, ignore=shutil.ignore_patterns(".git"))
    res = _install(flat, tgt, "--update")
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    assert f"the source read ({flat}) is not a git clone" in out, out
    assert "point $SYSOP_SRC at the newer clone and re-run" not in out, out
    assert "point $SYSOP_SRC at the newer clone instead" not in out and " fetch origin " not in out, out


def test_a_ref_from_a_clone_lacking_the_installed_commit_names_the_clone(setup, pristine,
                                                                        tmp_path):
    """Round 1, lens B: under `--ref` the source read is a temp worktree the EXIT trap deletes,
    and nothing pinned that the unreachable note names the clone, or that it does not call the
    pin older than a commit it cannot see."""
    src, tgt = setup
    newer = _advance(src, tgt)
    stale = tmp_path / "stale"
    subprocess.run(["git", "clone", "-q", str(pristine[0]), str(stale)], check=True,
                   capture_output=True, env=_env())
    res = _install(stale, tgt, "--update", "--ref", "HEAD")
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    assert f"the installed {newer[:12]} is not in the source read ({stale})" in out, out
    assert "is older than the installed" not in out, out
