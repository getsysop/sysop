"""`--update` says whether upstream also changed a consumer-modified script it keeps.

Phase 24b keeps a consumer-modified `sysop/scripts/*` or `sysop/scripts/hooks/*` file on
`--update` unless `--accept-upstream` names it. It compared the consumer's copy with the old
install's copy only, so a file upstream left alone and a file upstream rewrote under the
consumer's patch printed the same `⚠ preserved:` line, and the update exited 0 with a kept
copy the refreshed skills no longer matched (GDP's ISSUE-0323: its patched `review_pins.py`
would have been kept through the release that rewrote the script, and every `/review-close`
would then stop at `reap`). The third comparison is the old install's copy against this
update's: these tests pin both answers, the byte-equal case, the `--dry-run` and `--ref`
spellings, and a sweep that no file reads "changed" when upstream moved nothing.

They drive `install.sh` from a scratch source (copied from this checkout's working tree and
committed), never from this checkout: `reconstruct_old_install` registers temporary worktrees
in the source repo.
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

CHANGED = "sysop/scripts/review_pins.py"
CHANGED_SRC = "core/companion/scripts/review_pins.py"
UNCHANGED = "sysop/scripts/run_checks.sh"
CONSUMER_EDIT = "\n# consumer local patch\n"
UPSTREAM_EDIT = "\n# upstream change after the install\n"

ALSO = "upstream ALSO changed it since then, and your copy lacks that change"
SAME = "upstream unchanged since then"
ROW_CHANGED = "(consumer-modified; UPSTREAM CHANGED it too; --accept-upstream to overwrite)"
ROW_SAME = "(consumer-modified; upstream unchanged; --accept-upstream to overwrite)"
BLOCK = "⚠ upstream changed"


def _env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    env.update(_GIT_ISOLATION)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                          text=True, env=_env()).stdout.strip()


def _identity(repo):
    _git(repo, "config", "user.email", "test@test")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "commit.gpgsign", "false")


def _commit(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", msg, "--allow-empty")


def _run(src, target, *extra):
    res = subprocess.run(
        ["bash", str(src / "install.sh"), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=_env(), cwd=str(target),
        stdin=subprocess.DEVNULL, timeout=900,
    )
    out = res.stdout + res.stderr
    assert res.returncode == 0, out
    return out


def _append(path: Path, text: str):
    path.write_text(path.read_text() + text)


def _note(out, rel):
    """The per-file note `copy_file` printed for `rel` (preserved or matches), or None."""
    m = re.search(rf"^\s*• (?:⚠ preserved|✓ matches upstream): {re.escape(rel)} \((.*)\)$",
                  out, re.M)
    return m.group(0) if m else None


@pytest.fixture(scope="module")
def pristine(tmp_path_factory):
    base = tmp_path_factory.mktemp("preserved_upstream")
    src = base / "src"
    src.mkdir()
    shutil.copy2(REPO_ROOT / "install.sh", src / "install.sh")
    for d in ("core", "packs"):
        shutil.copytree(REPO_ROOT / d, src / d,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv"))
    _git(src, "init", "-q", "-b", "main")
    _identity(src)
    _commit(src, "source A")

    tgt = base / "tgt"
    tgt.mkdir()
    _git(tgt, "init", "-q", "-b", "main")
    _identity(tgt)
    (tgt / "README.md").write_text("# scratch\n")
    _commit(tgt, "seed")
    _run(src, tgt, "--packs", "", "--no-arm-hooks")
    _commit(tgt, "installed at A")
    return src, tgt


@pytest.fixture
def setup(pristine, tmp_path):
    src0, tgt0 = pristine
    src = tmp_path / "src"
    subprocess.run(["git", "clone", "-q", str(src0), str(src)], check=True,
                   capture_output=True, env=_env())
    _identity(src)
    tgt = tmp_path / "tgt"
    shutil.copytree(tgt0, tgt, symlinks=True)
    yield src, tgt
    left = [ln for ln in _git(src, "worktree", "list", "--porcelain").splitlines()
            if ln.startswith("worktree ")][1:]
    for line in left:
        subprocess.run(["git", "-C", str(src), "worktree", "remove", "--force",
                        line[len("worktree "):]], capture_output=True, env=_env())
    assert not left, left


def _patch_both_and_move_one(src, tgt):
    """The consumer patches both scripts; upstream then changes only CHANGED."""
    _append(tgt / CHANGED, CONSUMER_EDIT)
    _append(tgt / UNCHANGED, CONSUMER_EDIT)
    _commit(tgt, "consumer patches")
    _append(src / CHANGED_SRC, UPSTREAM_EDIT)
    _commit(src, "source B")


def _assert_marked(out, src):
    changed, same = _note(out, CHANGED), _note(out, UNCHANGED)
    assert changed and ALSO in changed and "⚠ preserved:" in changed, out
    assert same and SAME in same and ALSO not in same, out
    assert f"↻  {CHANGED}   {ROW_CHANGED}" in out, out
    assert f"↻  {UNCHANGED}   {ROW_SAME}" in out, out
    assert f"{BLOCK} 1 of them since " in out, out
    diffs = re.findall(r"^\s+git -C (\S+) diff (\S+) -- (\S+)$", out, re.M)
    # Source A, the install's commit: HEAD~1, since `_patch_both_and_move_one` committed B.
    old = _git(src, "rev-parse", "--short=12", "HEAD~1")
    assert diffs == [(str(src), old, CHANGED_SRC)], (diffs, out)


def test_a_kept_copy_says_whether_upstream_changed_it(setup):
    src, tgt = setup
    _patch_both_and_move_one(src, tgt)
    out = _run(src, tgt, "--update", "--packs", "")
    _assert_marked(out, src)
    # Both copies are still the consumer's: the message changed, not the decision.
    assert (tgt / CHANGED).read_text().endswith(CONSUMER_EDIT)
    assert (tgt / UNCHANGED).read_text().endswith(CONSUMER_EDIT)
    # The printed command shows upstream's change and nothing of the consumer's.
    m = re.search(r"^\s+(git -C \S+ diff \S+ -- \S+)$", out, re.M)
    assert m, out
    shown = subprocess.run(m.group(1), shell=True, capture_output=True, text=True,
                           env=_env()).stdout
    assert "+# upstream change after the install" in shown, shown
    assert "consumer local patch" not in shown, shown


def test_dry_run_marks_the_same_paths(setup):
    src, tgt = setup
    _patch_both_and_move_one(src, tgt)
    out = _run(src, tgt, "--update", "--packs", "", "--dry-run")
    _assert_marked(out, src)


def test_a_copy_already_equal_to_upstream_is_not_reported_preserved(setup):
    """The consumer applied upstream's change by hand before it shipped: nothing is kept
    back, and an --accept-upstream entry for it is not reported stale."""
    src, tgt = setup
    _append(src / CHANGED_SRC, UPSTREAM_EDIT)
    _commit(src, "source B")
    shutil.copy2(src / CHANGED_SRC, tgt / CHANGED)
    _commit(tgt, "consumer takes the fix early")
    out = _run(src, tgt, "--update", "--packs", "", "--accept-upstream", CHANGED)
    note = _note(out, CHANGED)
    assert note and "✓ matches upstream:" in note, out
    assert f"preserved: {CHANGED}" not in out, out
    assert f"↻  {CHANGED} " not in out, out  # no summary row either
    assert f"accept-upstream: {CHANGED} not in preserved set" not in out, out
    assert BLOCK not in out, out
    assert (tgt / CHANGED).read_bytes() == (src / CHANGED_SRC).read_bytes()


def test_accept_upstream_still_overwrites_a_changed_file(setup):
    src, tgt = setup
    _patch_both_and_move_one(src, tgt)
    out = _run(src, tgt, "--update", "--packs", "", "--accept-upstream", CHANGED)
    assert f"↻ accept-upstream: {CHANGED}" in out, out
    assert (tgt / CHANGED).read_bytes() == (src / CHANGED_SRC).read_bytes()
    assert BLOCK not in out, out
    assert f"↻  {UNCHANGED}   {ROW_SAME}" in out, out


def test_under_ref_the_command_names_the_clone_and_the_pinned_commit(setup):
    """--ref installs from a temporary worktree the EXIT trap removes, so the printed
    command must name the persistent clone and the commit it pinned."""
    src, tgt = setup
    _patch_both_and_move_one(src, tgt)
    pinned = _git(src, "rev-parse", "--short=12", "HEAD")
    _commit(src, "source C, past the pin")
    out = _run(src, tgt, "--update", "--packs", "", "--ref", pinned)
    m = re.search(r"^\s+git -C (\S+) diff (\S+) (\S+) -- (\S+)$", out, re.M)
    assert m, out
    assert (m.group(1), m.group(3), m.group(4)) == (str(src), pinned, CHANGED_SRC), out
    assert re.match(r"[0-9a-f]{12}$", m.group(2)), out
    shown = subprocess.run(m.group(0).strip(), shell=True, capture_output=True, text=True,
                           env=_env()).stdout
    assert "+# upstream change after the install" in shown, shown


def test_no_kept_copy_reads_changed_when_upstream_moved_no_script(setup):
    """The false-positive sweep: every in-scope file is patched, and upstream's only new
    commit touches no script. The ancestor is a rebuilt install, not a checkout, so any
    installer rewrite of an in-scope file after the copy would read as an upstream change."""
    src, tgt = setup
    scripts = tgt / "sysop" / "scripts"
    patched = [p for p in sorted(scripts.iterdir()) if p.is_file() and not p.is_symlink()]
    patched += [p for p in sorted((scripts / "hooks").iterdir())
                if p.is_file() and not p.is_symlink()]
    assert len(patched) > 20, patched
    for p in patched:
        _append(p, CONSUMER_EDIT)
    _commit(tgt, "consumer patches every in-scope file")
    _append(src / "core" / "companion" / "docs" / "WORKFLOW.md", "\n<!-- moved -->\n")
    _commit(src, "source B, no script touched")
    out = _run(src, tgt, "--update", "--packs", "")
    kept = re.findall(r"^\s*• ⚠ preserved: (\S+) ", out, re.M)
    assert sorted(kept) == sorted(str(p.relative_to(tgt)) for p in patched), out
    assert ALSO not in out and "UPSTREAM CHANGED" not in out and BLOCK not in out, out
