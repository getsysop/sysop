"""`walk_skill_files` and the skip disclosures built on it (`Q-349`, `Q-350`; Phase 466).

`iter_skill_files` was `sorted(p for p in root.rglob("*.md") if p.is_file())`. `rglob`
skips a directory it cannot list without a word, so those files reached no read guard and
the checker's green line stated a scope wider than the scan. And on Python 3.13 and older
`is_file()` raised `PermissionError` for a file in a directory that can be listed but not
searched, a traceback the installer reads as a refused mapping.

The checker's own disclosures are pinned in `tests/test_check_skill_models.py`, and the
installer's in `tests/test_install_model_roles.py`. This module pins the walk, the resolver
and the migrator, and that a preserved older `migrate_skill_model.py` does not take the walk
back to `rglob`.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import migrate_skill_model as m
import resolve_skill_models as rs

SCRIPTS = Path(__file__).resolve().parents[1] / "core" / "companion" / "scripts"
SKILL = "---\nname: s\nmodel: opus\n---\n<!-- sysop:model-roles frontmatter=reasoning -->\nbody\n"
CFG = "roles:\n  reasoning: opus\nserved:\n  - opus\n"
LATIN1 = "# Notas del café, año 2026\n".encode("latin-1")


def _needs_permissions():
    if os.geteuid() == 0:
        pytest.skip("root reads past mode bits, so the fixture cannot reproduce")


def _tree(tmp_path):
    root = tmp_path / "skills"
    (root / "s").mkdir(parents=True)
    (root / "s" / "SKILL.md").write_text(SKILL)
    cfg = tmp_path / "served_models.yml"
    cfg.write_text(CFG)
    return root, cfg


def _rglob(root):
    return sorted(p for p in root.rglob("*.md") if p.is_file())


def test_the_walk_returns_what_rglob_returned_on_a_readable_tree(tmp_path):
    """Parity on every shape `rglob("*.md")` + `is_file()` treats specially: hidden names
    in, a directory link not followed, a file link followed, a dangling link out, a
    directory or a FIFO named `*.md` out, the match case-sensitive."""
    root = tmp_path / "skills"
    outside = tmp_path / "outside" / "s"
    for d in (root / "a" / "deep", root / ".hid", root / "dir.md", outside / "deeper"):
        d.mkdir(parents=True)
    for f in (root / "a" / "SKILL.md", root / "a" / "deep" / "x.md", root / ".hid" / "h.md",
              root / ".dot.md", root / "UP.MD", root / "a" / "notes.txt",
              outside / "one.md", outside / "deeper" / "two.md"):
        f.write_text("# x\n")
    (root / "link").symlink_to(outside, target_is_directory=True)
    (root / "filelink.md").symlink_to(outside / "one.md")
    (root / "dangling.md").symlink_to(tmp_path / "nowhere.md")
    os.mkfifo(root / "pipe.md")

    files, unlistable = m.walk_skill_files(root)
    assert files == _rglob(root)
    assert [p.relative_to(root).as_posix() for p in files] == [
        ".dot.md", ".hid/h.md", "a/SKILL.md", "a/deep/x.md", "filelink.md"]
    assert unlistable == []
    assert m.iter_skill_files(root) == files


def test_an_unlistable_directory_is_returned_not_dropped(tmp_path):
    _needs_permissions()
    root, _ = _tree(tmp_path)
    locked = root / "locked"
    (locked / "sub").mkdir(parents=True)
    (locked / "SKILL.md").write_text(SKILL)
    locked.chmod(0o000)
    try:
        files, unlistable = m.walk_skill_files(root)
    finally:
        locked.chmod(0o755)
    assert unlistable == [locked]
    assert files == [root / "s" / "SKILL.md"], "a file under the unlistable directory was counted"


def test_a_listable_but_unsearchable_directorys_files_reach_the_read_guard(tmp_path):
    """Mode 444: the names can be listed and not stat'ed. `rglob` + `is_file` raised
    `PermissionError` here on Python <= 3.13 and dropped the file on 3.14; the walk returns
    it, the read guard returns `None` for it, and its subdirectory is unlistable."""
    _needs_permissions()
    root, _ = _tree(tmp_path)
    rnox = root / "rnox"
    (rnox / "sub").mkdir(parents=True)
    (rnox / "f.md").write_text("# f\n")
    (rnox / "sub" / "g.md").write_text("# g\n")
    rnox.chmod(0o444)
    try:
        files, unlistable = m.walk_skill_files(root)
        assert rnox / "f.md" in files
        assert m.read_skill_text(rnox / "f.md") is None
    finally:
        rnox.chmod(0o755)
    assert unlistable == [rnox / "sub"]


def test_an_unlistable_root_is_returned(tmp_path):
    _needs_permissions()
    root, _ = _tree(tmp_path)
    root.chmod(0o000)
    try:
        assert m.walk_skill_files(root) == ([], [root])
    finally:
        root.chmod(0o755)


def test_describe_skipped_counts_and_never_turns_a_directory_into_files():
    a, b = Path("a"), Path("b")
    assert m.describe_skipped([], []) == ""
    assert m.describe_skipped([a, b], []) == "2 unreadable file(s) skipped"
    assert m.describe_skipped([], [a]) == "1 unlistable directory skipped"
    assert m.describe_skipped([a], [a, b]) == (
        "1 unreadable file(s) skipped; 2 unlistable directories skipped")


# ── the resolver: its summary is the line `install.sh` keeps (`tail -1`) ───────────────

def test_the_resolver_summary_carries_an_unreadable_file(tmp_path, capsys):
    root, cfg = _tree(tmp_path)
    (root / "s" / "NOTES.md").write_bytes(LATIN1)
    assert rs.main(["--root", str(root), "--config", str(cfg), "--apply", "--quiet"]) == 0
    out = capsys.readouterr()
    assert out.out.rstrip().splitlines()[-1].endswith("(1 unreadable file(s) skipped)."), out.out
    assert "NOTES.md" in out.err, out.err


def test_the_resolver_reports_an_unlistable_directory(tmp_path, capsys):
    _needs_permissions()
    root, cfg = _tree(tmp_path)
    locked = root / "locked"
    locked.mkdir()
    (locked / "SKILL.md").write_text(SKILL)
    locked.chmod(0o000)
    try:
        assert rs.main(["--root", str(root), "--config", str(cfg), "--apply", "--quiet"]) == 0
    finally:
        locked.chmod(0o755)
    out = capsys.readouterr()
    assert out.out.rstrip().splitlines()[-1].endswith("(1 unlistable directory skipped)."), out.out
    assert "could not list 1 directory" in out.err and str(locked) in out.err, out.err


def test_a_clean_resolver_summary_states_no_skip(tmp_path, capsys):
    root, cfg = _tree(tmp_path)
    assert rs.main(["--root", str(root), "--config", str(cfg), "--apply", "--quiet"]) == 0
    out = capsys.readouterr()
    assert "skipped" not in out.out and out.err == "", out


def test_the_migrator_reports_an_unlistable_directory(tmp_path, capsys):
    _needs_permissions()
    root, _ = _tree(tmp_path)
    locked = root / "locked"
    locked.mkdir()
    (locked / "SKILL.md").write_text(SKILL)
    locked.chmod(0o000)
    try:
        assert m.main(["--root", str(root), "--from", "opus", "--to", "sonnet"]) == 0
    finally:
        locked.chmod(0o755)
    err = capsys.readouterr().err
    assert "could not list 1 directory" in err and str(locked) in err, err


# ── a preserved `migrate_skill_model.py` from before `walk_skill_files` ────────────────

_OLD_MIGRATE = '''
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
def iter_skill_files(root):
    # The real older file walked with `rglob` + `is_file()`, which crashes on a mode-444
    # directory on Python 3.13 and older and drops it on 3.14. Raising here shows that no
    # caller, the judges in `_model_roles.py` included, walks with it on any interpreter.
    raise AssertionError("the preserved migrator's walk was used")
def read_skill_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
'''


def test_the_checker_and_resolver_keep_the_walk_beside_an_older_migrate_module(tmp_path):
    """`install.sh` preserves a consumer-modified vendored script, so the new checker and
    resolver can run beside a `migrate_skill_model.py` with no `walk_skill_files`. They
    import the walk from `_skill_walk.py`, so they still report a directory they could not
    list and a file in one they could list but not search (the round's lens 1: a fallback
    onto the old file's `rglob` crashed on Python 3.13 and older and was silent on 3.14)."""
    _needs_permissions()
    scripts = tmp_path / "sysop" / "scripts"
    scripts.mkdir(parents=True)
    for name in ("check_skill_models.py", "resolve_skill_models.py", "_model_roles.py",
                 "_skill_walk.py"):
        shutil.copy2(SCRIPTS / name, scripts / name)
    (scripts / "migrate_skill_model.py").write_text(_OLD_MIGRATE)
    root, cfg = _tree(tmp_path)
    (root / "s" / "NOTES.md").write_bytes(LATIN1)
    locked, nox = root / "locked", root / "nox"
    locked.mkdir()
    nox.mkdir()
    (nox / "f.md").write_text("x\n")
    locked.chmod(0o000)
    nox.chmod(0o444)
    try:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        common = ["--root", str(root), "--config", str(cfg), "--local", str(tmp_path / "none.yml")]
        chk = subprocess.run([sys.executable, str(scripts / "check_skill_models.py"), *common,
                              "--managed-only"], capture_output=True, text=True, env=env)
        res = subprocess.run([sys.executable, str(scripts / "resolve_skill_models.py"), *common,
                              "--quiet"], capture_output=True, text=True, env=env)
    finally:
        locked.chmod(0o755)
        nox.chmod(0o755)
    want = "(2 unreadable file(s) skipped; 1 unlistable directory skipped)."
    assert chk.returncode == 0, chk.stdout + chk.stderr
    assert chk.stdout.rstrip().endswith(want), chk.stdout
    assert res.returncode == 0, res.stdout + res.stderr
    assert res.stdout.rstrip().endswith(want), res.stdout
