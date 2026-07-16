"""Integration tests for core/companion/scripts/install_hooks.sh (Phase 84).

`install_hooks.sh` copies the tracked git hooks (`pre-commit`,
`pre-merge-commit`, `pre-push`) from `scripts/hooks/` into `.git/hooks/`. The
logic is pure bash + filesystem, so these tests drive the real script against a
scratch git repo in tmp_path and assert on exit code / stdout / stderr / the
files that land in `.git/hooks/`.

The load-bearing case is the **allowlist** (SKILL/script comment: "only these
tracked filenames are ever copied … so stray files cannot get installed and
executed on git events"): a `.DS_Store` / `README.md` / arbitrary `evil` file
dropped into `scripts/hooks/` must never reach `.git/hooks/`. The backup-on-
differ / no-backup-on-identical behavior and the atomic executable install are
the other invariants worth locking.

The script operates on the git repo of its *current working directory* (it
takes no path argument), so `_run` sets `cwd=repo_root` — unlike the install.sh
tests, which pass the target as an argument.
"""
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core/companion/scripts/install_hooks.sh"

HOOK_NAMES = ("pre-commit", "pre-merge-commit", "pre-push")


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _init_repo(root):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    return root


def _seed_hooks(root, contents):
    """contents: {basename: file text}. Writes them under scripts/hooks/."""
    src = root / "scripts" / "hooks"
    src.mkdir(parents=True, exist_ok=True)
    for name, text in contents.items():
        (src / name).write_text(text)
    return src


def _run(cwd, *args):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True,
    )


class TestGuards:
    def test_not_a_git_repo_exits_1(self, tmp_path):
        # tmp_path is not inside any git repo → the show-toplevel guard fires.
        r = _run(tmp_path)
        assert r.returncode == 1
        assert "Not inside a git repository" in r.stderr

    def test_no_hooks_dir_exits_1(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        r = _run(repo)
        assert r.returncode == 1
        assert "No hooks found in scripts/hooks/" in r.stderr


class TestInstall:
    def test_installs_all_three_hooks(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _seed_hooks(repo, {n: f"#!/bin/sh\n# {n}\nexit 0\n" for n in HOOK_NAMES})
        r = _run(repo)
        assert r.returncode == 0, r.stderr
        assert "Done. 3 hook(s)" in r.stdout
        for n in HOOK_NAMES:
            dst = repo / ".git" / "hooks" / n
            assert dst.is_file(), f"{n} not installed"
            assert dst.read_text() == f"#!/bin/sh\n# {n}\nexit 0\n"

    def test_installed_hook_is_executable(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _seed_hooks(repo, {"pre-commit": "#!/bin/sh\nexit 0\n"})
        r = _run(repo)
        assert r.returncode == 0, r.stderr
        dst = repo / ".git" / "hooks" / "pre-commit"
        assert os.access(dst, os.X_OK), "installed hook is not executable"

    def test_partial_set_installs_only_present(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _seed_hooks(repo, {"pre-commit": "#!/bin/sh\nexit 0\n"})
        r = _run(repo)
        assert r.returncode == 0, r.stderr
        assert "Done. 1 hook(s)" in r.stdout
        assert (repo / ".git/hooks/pre-commit").is_file()
        assert not (repo / ".git/hooks/pre-merge-commit").exists()
        assert not (repo / ".git/hooks/pre-push").exists()

    def test_no_tmp_file_left_behind(self, tmp_path):
        # Atomic install writes .tmp then mv's it into place — nothing lingers.
        repo = _init_repo(tmp_path / "repo")
        _seed_hooks(repo, {"pre-commit": "#!/bin/sh\nexit 0\n"})
        _run(repo)
        assert not (repo / ".git/hooks/pre-commit.tmp").exists()


class TestAllowlist:
    """Only the three tracked basenames are ever copied — stray files dropped
    into scripts/hooks/ must not land in .git/hooks/ and become executable on
    git events. This is the script's stated security invariant."""

    def test_stray_files_are_not_installed(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _seed_hooks(repo, {
            "pre-commit": "#!/bin/sh\nexit 0\n",
            "evil": "#!/bin/sh\necho pwned\n",
            "README.md": "# docs, not a hook\n",
            ".DS_Store": "\x00\x01\x02",
            "post-checkout": "#!/bin/sh\nexit 0\n",  # a real git hook, but not allowlisted
            "pre-commit.bak": "#!/bin/sh\nexit 0\n",
        })
        r = _run(repo)
        assert r.returncode == 0, r.stderr
        assert "Done. 1 hook(s)" in r.stdout
        hooks_dir = repo / ".git" / "hooks"
        assert (hooks_dir / "pre-commit").is_file()
        for stray in ("evil", "README.md", ".DS_Store", "post-checkout", "pre-commit.bak"):
            assert not (hooks_dir / stray).exists(), f"stray {stray} was installed"


class TestBackup:
    def test_backs_up_differing_pre_existing_hook(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        dst = repo / ".git" / "hooks" / "pre-commit"
        dst.write_text("#!/bin/sh\n# my customization\nexit 0\n")
        _seed_hooks(repo, {"pre-commit": "#!/bin/sh\n# upstream\nexit 0\n"})
        r = _run(repo)
        assert r.returncode == 0, r.stderr
        assert "Backed up pre-existing customized hooks" in r.stdout
        backups = list((repo / ".git" / "hooks").glob("pre-commit.bak.*"))
        assert len(backups) == 1, f"expected one backup, got {backups}"
        assert "my customization" in backups[0].read_text()
        # …and the upstream version is now in place.
        assert "# upstream" in dst.read_text()

    def test_no_backup_when_identical(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        same = "#!/bin/sh\nexit 0\n"
        (repo / ".git" / "hooks" / "pre-commit").write_text(same)
        _seed_hooks(repo, {"pre-commit": same})
        r = _run(repo)
        assert r.returncode == 0, r.stderr
        assert "Backed up pre-existing" not in r.stdout
        assert not list((repo / ".git" / "hooks").glob("pre-commit.bak.*"))
