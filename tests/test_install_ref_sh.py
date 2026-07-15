"""Integration tests for install.sh's ``--ref <tag>`` release-pinning (Phase 111).

``--ref`` lets a cautious consumer install/update from a reviewed *release* tag
instead of the source clone's live HEAD — the bash-path half of the supply-chain
hardening (the plugin path can't offer a consumer-side pin; see SECURITY.md).

There is no ref-establishment step in install.sh's copy path — every ``install_*``
reads ``$REPO_ROOT`` directly — so ``--ref`` materialises the rev into a temp
worktree (the ``reconstruct_old_install`` pattern) and re-points ``$REPO_ROOT`` at
it for the whole pipeline; ``get_sysop_commit`` then records the rev's commit.

These drive the *real* install.sh against a self-contained scratch **source
clone** built from the current working tree (so it captures the edits under test),
tagged at an earlier commit than its HEAD. That gap is load-bearing: a ``--ref``
install must record the *tag's* commit and ship the *tag's* content, where a plain
install records HEAD and ships HEAD — the two are asserted against each other so
the tests can't pass by accident.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Isolate every git call (source-clone build AND install.sh's own worktree ops)
# from a contributor's global/system git config — mirrors the other install
# integration suites.
_GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}

_SENTINEL = "PHASE111-HEAD-ONLY-SENTINEL"
TAG = "v0.1.0-test"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                   env={**os.environ, **_GIT_ISOLATION})


def _git_out(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                          text=True, env={**os.environ, **_GIT_ISOLATION}).stdout.strip()


@pytest.fixture(scope="module")
def pinned_source(tmp_path_factory):
    """A scratch Sysop *source clone* with a tag one commit behind its HEAD.

    Returns (src_dir, tag_sha, head_sha). The post-tag HEAD commit appends
    ``_SENTINEL`` to a shipped doc, so a ``--ref TAG`` install (pre-sentinel) is
    distinguishable from a HEAD install (with sentinel) by content, not just sha.
    """
    src = tmp_path_factory.mktemp("sysop_src")
    # Copy the install-relevant tree from the live working tree (captures the
    # uncommitted --ref edits under test).
    shutil.copy2(REPO_ROOT / "install.sh", src / "install.sh")
    for d in ("core", "packs"):
        shutil.copytree(REPO_ROOT / d, src / d,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv"))
    _git(src, "init", "-q")
    _git(src, "config", "user.email", "test@test")
    _git(src, "config", "user.name", "test")
    _git(src, "config", "commit.gpgsign", "false")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "release cut")
    _git(src, "tag", TAG)
    tag_sha = _git_out(src, "rev-parse", "HEAD")
    # A later commit that modifies shipped content — HEAD is now ahead of the tag.
    workflow = src / "core" / "companion" / "docs" / "WORKFLOW.md"
    workflow.write_text(workflow.read_text() + f"\n<!-- {_SENTINEL} -->\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "post-release edit")
    head_sha = _git_out(src, "rev-parse", "HEAD")
    assert tag_sha != head_sha
    return src, tag_sha, head_sha


def _seed_target(root):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("# scratch\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run(src, target, *extra):
    """Run the scratch-source install.sh; return the CompletedProcess (no assert)."""
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    env.update(_GIT_ISOLATION)
    return subprocess.run(
        ["bash", str(src / "install.sh"), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env, cwd=str(target),
    )


def _lock_commit(target):
    return json.loads((target / ".claude" / "sysop.lock").read_text())["sysop_commit"]


def _tree_has_sentinel(target):
    for p in target.rglob("*"):
        if p.is_file():
            try:
                if _SENTINEL in p.read_text():
                    return True
            except (UnicodeDecodeError, OSError):
                continue
    return False


class TestRefPinsToTag:
    def test_fresh_ref_records_tag_commit_not_head(self, pinned_source, tmp_path):
        src, tag_sha, head_sha = pinned_source
        target = _seed_target(tmp_path / "pinned")
        r = _run(src, target, "--packs", "python", "--ref", TAG)
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        assert "pinned to " + TAG in r.stdout
        assert _lock_commit(target) == tag_sha       # the tag's commit …
        assert _lock_commit(target) != head_sha      # … not the source HEAD
        # The fresh-install footer must point SYSOP_SRC at the real clone, not
        # the ephemeral --ref worktree (which is deleted on exit) — otherwise the
        # documented first `sysop-update.sh` fails the shim's SYSOP_SRC check.
        # (If the footer regressed to $REPO_ROOT it would print the temp worktree
        # path, not `src`, so this assertion pins the SYSOP_SRC_CLONE fallback.)
        assert f'export SYSOP_SRC="{src}"' in r.stdout

    def test_fresh_without_ref_records_head(self, pinned_source, tmp_path):
        # Control: the SAME install without --ref records HEAD. The delta between
        # this and the test above is exactly what --ref changes.
        src, tag_sha, head_sha = pinned_source
        target = _seed_target(tmp_path / "unpinned")
        r = _run(src, target, "--packs", "python")
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        assert _lock_commit(target) == head_sha
        assert _lock_commit(target) != tag_sha

    def test_ref_ships_content_from_the_tag_not_head(self, pinned_source, tmp_path):
        # The sentinel exists only in the post-tag HEAD commit. Pinning to the tag
        # must ship pre-sentinel content; a plain install must ship it. Proves the
        # FILES come from the ref, not merely the recorded sha.
        src, _, _ = pinned_source
        pinned = _seed_target(tmp_path / "c_pinned")
        unpinned = _seed_target(tmp_path / "c_unpinned")
        assert _run(src, pinned, "--packs", "python", "--ref", TAG).returncode == 0
        assert _run(src, unpinned, "--packs", "python").returncode == 0
        assert not _tree_has_sentinel(pinned), "pinned install leaked post-tag content"
        assert _tree_has_sentinel(unpinned), "control install missing HEAD content"


class TestRefGuards:
    def test_nonexistent_ref_fails_cleanly(self, pinned_source, tmp_path):
        src, _, _ = pinned_source
        target = _seed_target(tmp_path / "bad")
        r = _run(src, target, "--packs", "python", "--ref", "no-such-tag-xyz")
        assert r.returncode == 1
        assert "cannot resolve" in r.stderr
        assert "fetch --tags" in r.stderr
        # A failed pin writes nothing — no partial install.
        assert not (target / ".claude").exists()

    def test_ref_rejected_with_adopt(self, pinned_source, tmp_path):
        src, _, _ = pinned_source
        target = _seed_target(tmp_path / "adopt")
        r = _run(src, target, "--adopt", "--packs", "python", "--ref", TAG)
        assert r.returncode == 2
        assert "only valid for a fresh install or --update" in r.stderr

    def test_ref_requires_a_value(self, pinned_source, tmp_path):
        # A trailing `--ref` with no tag exits 2 with a clear message (not a
        # silent shift-2 failure); mirrors --accept-upstream's value guard.
        src, _, _ = pinned_source
        target = _seed_target(tmp_path / "noval")
        r = _run(src, target, "--packs", "python", "--ref")
        assert r.returncode == 2
        assert "--ref requires a tag/rev" in r.stderr
        assert not (target / ".claude").exists()

    def test_ref_rejected_with_check(self, pinned_source, tmp_path):
        src, _, _ = pinned_source
        target = _seed_target(tmp_path / "check")
        # --check would also need --source; the --ref rejection fires first
        # (arg-validation, before mode dispatch), so it exits 2 regardless.
        r = _run(src, target, "--check", "--source", str(src), "--ref", TAG)
        assert r.returncode == 2
        assert "only valid for a fresh install or --update" in r.stderr


class TestUpdateRef:
    def test_update_ref_repins_and_leaves_no_worktree(self, pinned_source, tmp_path):
        src, tag_sha, head_sha = pinned_source
        target = _seed_target(tmp_path / "upd")
        # Install tracking HEAD, then update pinned to the tag.
        assert _run(src, target, "--packs", "python").returncode == 0
        assert _lock_commit(target) == head_sha
        wt_before = _git_out(src, "worktree", "list").count("\n")

        r = _run(src, target, "--update", "--ref", TAG)
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        assert "pinned to " + TAG in r.stdout
        # The update re-pinned the recorded commit back to the tag …
        assert _lock_commit(target) == tag_sha
        # … and the ref worktree + divergence shadow were cleaned (no leak).
        assert _git_out(src, "worktree", "list").count("\n") == wt_before
