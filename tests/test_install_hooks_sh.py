"""Integration tests for core/companion/scripts/install_hooks.sh (Phase 84).

`install_hooks.sh` copies the tracked git hooks (`pre-commit`,
`pre-merge-commit`, `pre-push`) from `sysop/scripts/hooks/` into `.git/hooks/`. The
logic is pure bash + filesystem, so these tests drive the real script against a
scratch git repo in tmp_path and assert on exit code / stdout / stderr / the
files that land in `.git/hooks/`.

The load-bearing case is the **allowlist** (SKILL/script comment: "only these
tracked filenames are ever copied … so stray files cannot get installed and
executed on git events"): a `.DS_Store` / `README.md` / arbitrary `evil` file
dropped into `sysop/scripts/hooks/` must never reach `.git/hooks/`. The backup-on-
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


# Isolate from a contributor's global/system git config. Since Phase 150 the
# script resolves its destination with `git rev-parse --git-path hooks` and
# skips outright when core.hooksPath is set — so a contributor carrying a global
# core.hooksPath would send every test in this module down the skip path and
# redden the suite. /dev/null restores git's built-in `.git/hooks` default.
# Same rationale (and same shape) as test_install_arm_hooks_sh.py.
_GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                   env={**os.environ, **_GIT_ISOLATION})


def _init_repo(root):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    return root


def _seed_hooks(root, contents):
    """contents: {basename: file text}. Writes them under sysop/scripts/hooks/."""
    src = root / "sysop" / "scripts" / "hooks"
    src.mkdir(parents=True, exist_ok=True)
    for name, text in contents.items():
        (src / name).write_text(text)
    return src


def _run(cwd, *args):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True,
        env={**os.environ, **_GIT_ISOLATION},
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
        assert "No hooks found in sysop/scripts/hooks/" in r.stderr


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
    into sysop/scripts/hooks/ must not land in .git/hooks/ and become executable on
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


class TestWorktreeSharesMainHooksDir:
    """Phase 150 swapped the destination resolution from
    ``$(git rev-parse --git-common-dir)/hooks`` to ``--git-path hooks`` so that
    core.hooksPath is honored. These lock the *unchanged* half of that swap:
    with no core.hooksPath, both spellings resolve to the main repo's shared
    hooks dir, including from inside a linked worktree."""

    def test_run_from_worktree_targets_the_main_repo_hooks_dir(self, tmp_path):
        main = _init_repo(tmp_path / "main")
        (main / "README.md").write_text("# seed\n")
        _git(main, "add", "-A")
        _git(main, "-c", "commit.gpgsign=false", "commit", "-qm", "seed")
        wt = tmp_path / "wt"
        _git(main, "worktree", "add", "-q", "-b", "feat/x", str(wt))
        # Seed templates in the worktree, run from the worktree.
        _seed_hooks(wt, {"pre-commit": "#!/bin/sh\n# from worktree\nexit 0\n"})

        r = _run(wt)
        assert r.returncode == 0, r.stderr
        # Lands in the MAIN repo's hooks dir — worktrees share one.
        assert (main / ".git/hooks/pre-commit").is_file()
        assert "# from worktree" in (main / ".git/hooks/pre-commit").read_text()
        # A worktree has no hooks dir of its own to write into.
        assert not (wt / ".git/hooks/pre-commit").exists()


class TestRunFromSubdirectory:
    """`git rev-parse --git-path hooks` answers relative to the CURRENT
    DIRECTORY, not the toplevel — `../../.git/hooks` from `src/api/`. Anchoring
    that result to REPO_ROOT resolves *outside* the repo, and in a repo nested
    one level inside another it lands squarely in the OUTER repo's hooks while
    reporting success — reintroducing #202's defect by a new route. The probe is
    therefore anchored with `-C "$REPO_ROOT"`.

    Every other test in this module runs the script from the repo root, where
    the anchoring is a no-op; without these two the whole `case` block is dead
    weight that could be deleted with the suite still green."""

    def test_installs_correctly_when_run_from_a_subdirectory(self, tmp_path):
        repo = _init_repo(tmp_path / "repo")
        _seed_hooks(repo, {"pre-commit": "#!/bin/sh\n# real\nexit 0\n"})
        sub = repo / "src" / "api"
        sub.mkdir(parents=True)

        r = _run(sub)
        assert r.returncode == 0, f"failed from a subdirectory:\n{r.stdout}\n{r.stderr}"
        dst = repo / ".git" / "hooks" / "pre-commit"
        assert dst.is_file(), "nothing installed when run from a subdirectory"
        assert "# real" in dst.read_text()

    def test_nested_repo_does_not_arm_the_outer_repository(self, tmp_path):
        # inner must be a DIRECT child of outer, and the run one level down
        # inside inner: `--git-path` gives `../.git/hooks`, which anchored to
        # inner resolves to outer/.git/hooks.
        outer = _init_repo(tmp_path / "outer")
        outer_hook = outer / ".git" / "hooks" / "pre-commit"
        outer_hook.parent.mkdir(parents=True, exist_ok=True)
        outer_hook.write_text("#!/bin/sh\n# the OUTER repo's hook\nexit 0\n")

        inner = _init_repo(outer / "inner")
        _seed_hooks(inner, {"pre-commit": "#!/bin/sh\n# inner template\nexit 0\n"})
        sub = inner / "src"
        sub.mkdir(parents=True)

        r = _run(sub)
        assert r.returncode == 0, r.stderr
        assert "# the OUTER repo's hook" in outer_hook.read_text(), \
            "armed into the OUTER repository's hooks — #202's defect by another route"
        assert "# inner template" in (inner / ".git/hooks/pre-commit").read_text(), \
            "did not arm the repo it was actually run in"


class TestCoreHooksPath:
    """When core.hooksPath is configured, git ignores .git/hooks/ entirely and
    the configured directory belongs to the consumer — typically tracked in
    their own tree, which is the point of setting it. Writing there would
    clobber tracked files: strictly worse than the untracked-.git/hooks case.
    Skipped-not-failed (exit 0), so callers report no phantom install error."""

    def _repo_with_hookspath(self, tmp_path, value):
        repo = _init_repo(tmp_path / "repo")
        _seed_hooks(repo, {n: f"#!/bin/sh\n# skeleton {n}\nexit 0\n" for n in HOOK_NAMES})
        _git(repo, "config", "core.hooksPath", value)
        return repo

    def test_relative_hookspath_skips_and_writes_nothing(self, tmp_path):
        repo = self._repo_with_hookspath(tmp_path, "myhooks")
        (repo / "myhooks").mkdir()
        r = _run(repo)
        assert r.returncode == 0, r.stderr
        assert "core.hooksPath is set" in r.stdout
        assert "Installed:" not in r.stdout
        for n in HOOK_NAMES:
            assert not (repo / "myhooks" / n).exists(), f"wrote into the consumer's dir: {n}"
            assert not (repo / ".git/hooks" / n).exists(), f"wrote into inert .git/hooks: {n}"

    def test_does_not_clobber_a_tracked_hook_in_the_configured_dir(self, tmp_path):
        # The upstream #202 shape, one directory over: the consumer's real,
        # tracked pre-commit must survive verbatim.
        repo = self._repo_with_hookspath(tmp_path, "myhooks")
        (repo / "myhooks").mkdir()
        real = repo / "myhooks" / "pre-commit"
        real.write_text("#!/bin/sh\n# the consumer's real checks\nexit 1\n")
        r = _run(repo)
        assert r.returncode == 0, r.stderr
        assert "the consumer's real checks" in real.read_text()
        assert not list((repo / "myhooks").glob("*.bak.*")), "backed up a file it should not touch"

    def test_empty_hookspath_skips_and_does_not_litter_the_worktree(self, tmp_path):
        # `core.hooksPath = ""` makes git run NO hooks, while `--git-path hooks`
        # resolves to `./` — so a non-empty value test would fall through and
        # drop three executables into the root of the consumer's working tree
        # while printing "Done. 3 hook(s) installed". Guard is key-set, not
        # value-non-empty.
        repo = self._repo_with_hookspath(tmp_path, "")
        r = _run(repo)
        assert r.returncode == 0, r.stderr
        assert "empty string" in r.stdout, "did not recognise the empty-value case"
        for n in HOOK_NAMES:
            assert not (repo / n).exists(), f"dropped {n} into the working-tree root"
            assert not (repo / ".git/hooks" / n).exists()

    def test_global_scope_offers_no_copy_remedy(self, tmp_path):
        # A global core.hooksPath is a per-machine directory. Sysop's hook
        # templates are per-project, so advising a copy there would apply this
        # project's checks to every repo on the machine — and a second project
        # would silently overwrite the first.
        fake_global = tmp_path / "gitconfig"
        shared = tmp_path / "shared-hooks"
        shared.mkdir()
        fake_global.write_text(f"[core]\n\thooksPath = {shared}\n")
        repo = _init_repo(tmp_path / "repo")
        _seed_hooks(repo, {n: f"#!/bin/sh\nexit 0\n" for n in HOOK_NAMES})
        r = subprocess.run(
            ["bash", str(SCRIPT)], cwd=str(repo), capture_output=True, text=True,
            env={**os.environ, "GIT_CONFIG_GLOBAL": str(fake_global),
                 "GIT_CONFIG_SYSTEM": "/dev/null"},
        )
        assert r.returncode == 0, r.stderr
        assert "global" in r.stdout, "did not name the scope"
        assert "cp " not in r.stdout, \
            "advised copying this project's hook templates into a machine-wide dir"
        assert not any(shared.iterdir()), "wrote into a machine-wide hooks dir"

    def test_absolute_hookspath_also_skips(self, tmp_path):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        repo = self._repo_with_hookspath(tmp_path, str(elsewhere))
        r = _run(repo)
        assert r.returncode == 0, r.stderr
        assert "core.hooksPath is set" in r.stdout
        assert not any(elsewhere.iterdir()), "wrote into an absolute core.hooksPath"

    def test_message_points_at_the_configured_dir_not_git_hooks(self, tmp_path):
        # This is what makes the `--git-path hooks` resolution load-bearing
        # rather than cosmetic: the skip message tells the consumer where git
        # actually reads hooks and where to copy the templates. Under the old
        # `--git-common-dir`/hooks spelling both would have read `.git/hooks` —
        # precisely the directory git is now ignoring.
        repo = self._repo_with_hookspath(tmp_path, "myhooks")
        (repo / "myhooks").mkdir()
        r = _run(repo)
        # Assert on the remedy line, not the whole of stdout — the prose above
        # it names .git/hooks deliberately, to say git is *not* reading there.
        cp_lines = [ln for ln in r.stdout.splitlines() if "cp " in ln]
        assert len(cp_lines) == 1, f"expected one copy remedy, got {cp_lines}"
        remedy = cp_lines[0]
        assert "myhooks" in remedy, f"remedy does not target the configured dir: {remedy}"
        assert ".git/hooks" not in remedy, \
            f"remedy points at .git/hooks, which git is configured to ignore: {remedy}"
        assert "chmod +x" in r.stdout, "remedy leaves the hooks non-executable"
