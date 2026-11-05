"""The worked `pre-merge-commit-python.example` runs pytest on the main checkout's venv.

The example gates merges into `main` and used to find its interpreter by sourcing
`$(git rev-parse --show-toplevel)/.venv/bin/activate`. In a linked worktree that holds
`main` (the primary checkout is on another branch), the top level is the worktree,
which has no `.venv`, so pytest ran on whatever `python3` was first on `PATH`. The
`pre-commit-*` examples beside it already resolve the main checkout through
`git rev-parse --git-common-dir`; this module pins that the merge example does too.

Every case fires the hook the way git does: the example is installed in the common
hooks directory and a real `git merge --no-ff` runs it. Two stub interpreters make the
result independent of the host: `<checkout>/.venv/bin/python3` writes `venv:<checkout>`
to a marker file, and a `python3` first on `PATH` writes `path`. Each exits with the
status the test asks for, so "which interpreter ran pytest" is read off the marker, not
off whether a real pytest happened to be installed.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "core/companion/git-hooks/examples/pre-merge-commit-python.example"

if shutil.which("git") is None:  # pragma: no cover - the suite needs git everywhere
    pytest.skip("git is not on PATH", allow_module_level=True)


def _stub(path: Path, label: str, marker: Path, status: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        f"printf '%s %s\\n' '{label}' \"$*\" >> '{marker}'\n"
        f"exit {status}\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _venv(checkout: Path, marker: Path, status: int = 0) -> None:
    """A venv as `python -m venv` leaves it, reduced to what the hook touches: the
    interpreter, and an `activate` that puts its `bin/` first on `PATH`."""
    bindir = checkout / ".venv" / "bin"
    _stub(bindir / "python3", f"venv:{checkout.name}", marker, status)
    (bindir / "activate").write_text(
        f"VIRTUAL_ENV='{checkout / '.venv'}'\nexport VIRTUAL_ENV\n"
        'PATH="$VIRTUAL_ENV/bin:$PATH"\nexport PATH\n',
        encoding="utf-8",
    )


def _bash_major(bash: str) -> int:
    r = subprocess.run([bash, "-c", 'echo "${BASH_VERSINFO[0]}"'], capture_output=True, text=True)
    return int(r.stdout.strip() or 0)


class Fixture:
    def __init__(self, tmp: Path, *, bash: str | None = None) -> None:
        self.tmp = tmp
        self.primary = tmp / "primary"
        self.marker = tmp / "ran.txt"
        self.pathbin = tmp / "pathbin"
        _stub(self.pathbin / "python3", "path", self.marker, 0)
        # The hook's `#!/usr/bin/env bash` takes the first `bash` on PATH; pin which.
        (self.pathbin / "bash").symlink_to(bash or shutil.which("bash"))
        git_dir = Path(shutil.which("git")).parent
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(
            GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null",
            GIT_TERMINAL_PROMPT="0",
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
            PATH=os.pathsep.join([str(self.pathbin), str(git_dir), "/usr/bin", "/bin"]),
        )
        self.primary.mkdir()
        self.git(self.primary, "init", "-q", "-b", "main")
        self.git(self.primary, "config", "commit.gpgsign", "false")
        (self.primary / "seed.txt").write_text("seed\n")
        self.git(self.primary, "add", "-A")
        self.git(self.primary, "commit", "-qm", "seed")
        hooks = self.primary / ".git" / "hooks"
        hooks.mkdir(exist_ok=True)
        hook = hooks / "pre-merge-commit"
        shutil.copyfile(EXAMPLE, hook)
        hook.chmod(0o755)

    def git(self, cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                           env=self.env)
        if check:
            assert r.returncode == 0, f"git {' '.join(args)}: {r.stdout}{r.stderr}"
        return r

    def worktree_on_main(self) -> Path:
        """Free `main` in the primary checkout and hold it in a linked worktree."""
        self.git(self.primary, "checkout", "-q", "-b", "dev")
        wt = self.tmp / "wt"
        self.git(self.primary, "worktree", "add", "-q", str(wt), "main")
        return wt

    def merge(self, cwd: Path, filename: str = "mod.py", branch: str = "main") -> subprocess.CompletedProcess:
        """Commit `filename` on a topic branch and merge it into `branch` with --no-ff,
        which is what fires `pre-merge-commit`."""
        self.git(cwd, "checkout", "-q", "-b", "topic")
        (cwd / filename).write_text("x = 1\n")
        self.git(cwd, "add", filename)
        self.git(cwd, "commit", "-qm", "topic")
        self.git(cwd, "checkout", "-q", branch)
        return self.git(cwd, "merge", "--no-ff", "-m", "merge topic", "topic", check=False)

    def ran(self) -> list[str]:
        if not self.marker.exists():
            return []
        return [line.split(" ", 1)[0] for line in self.marker.read_text().splitlines()]


@pytest.fixture
def fx(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path)


def test_worktree_holding_main_runs_the_main_checkouts_venv(fx: Fixture):
    """The defect: a linked worktree on `main` has no `.venv` of its own, so the
    `--show-toplevel` anchor found none and pytest ran on `PATH`'s `python3`."""
    _venv(fx.primary, fx.marker)
    wt = fx.worktree_on_main()
    r = fx.merge(wt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == ["venv:primary"], (fx.ran(), r.stdout + r.stderr)


def test_failing_pytest_in_the_main_venv_blocks_a_worktree_merge(fx: Fixture):
    _venv(fx.primary, fx.marker, status=1)
    wt = fx.worktree_on_main()
    r = fx.merge(wt)
    assert r.returncode != 0
    assert "MERGE BLOCKED" in r.stdout + r.stderr
    assert fx.ran() == ["venv:primary"]
    assert fx.git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False).returncode == 0


def test_the_pytest_run_is_a_module_run_of_pytest(fx: Fixture):
    _venv(fx.primary, fx.marker)
    wt = fx.worktree_on_main()
    fx.merge(wt)
    assert fx.marker.read_text().splitlines() == ["venv:primary -m pytest -q"]


# ── Boundary pins: behaviour the base already had and the fix must keep ──────────


def test_primary_checkout_on_main_runs_its_venv(fx: Fixture):
    _venv(fx.primary, fx.marker)
    r = fx.merge(fx.primary)
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == ["venv:primary"]


def test_no_venv_anywhere_falls_back_to_python3_on_path(fx: Fixture):
    r = fx.merge(fx.primary)
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == ["path"]


def test_no_venv_in_a_worktree_falls_back_to_python3_on_path(fx: Fixture):
    wt = fx.worktree_on_main()
    r = fx.merge(wt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == ["path"]


def test_a_worktrees_own_venv_serves_when_the_main_checkout_has_none(fx: Fixture):
    """The base sourced the worktree's own `activate`; a worktree that carries a venv
    while the main checkout does not keeps getting it."""
    wt = fx.worktree_on_main()
    _venv(wt, fx.marker)
    r = fx.merge(wt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == ["venv:wt"]


def test_the_main_checkouts_venv_wins_over_a_worktrees_own(fx: Fixture):
    _venv(fx.primary, fx.marker)
    wt = fx.worktree_on_main()
    _venv(wt, fx.marker)
    fx.merge(wt)
    assert fx.ran() == ["venv:primary"]


def test_a_merge_into_another_branch_runs_nothing(fx: Fixture):
    _venv(fx.primary, fx.marker)
    fx.git(fx.primary, "checkout", "-q", "-b", "dev")
    r = fx.merge(fx.primary, branch="dev")
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == []


def test_a_merge_with_no_python_change_runs_nothing(fx: Fixture):
    _venv(fx.primary, fx.marker)
    wt = fx.worktree_on_main()
    r = fx.merge(wt, filename="notes.txt")
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == []


@pytest.mark.skipif(not Path("/bin/bash").exists() or _bash_major("/bin/bash") != 3,
                    reason="needs bash 3.2 at /bin/bash (macOS)")
def test_a_missing_env_file_does_not_end_the_hook_under_bash_3_2(tmp_path: Path):
    """bash 3.2 under `set -e` exits the shell when `source` cannot read its file,
    `|| true` notwithstanding. The example's `source "$REPO_ROOT/.env" 2>/dev/null ||
    true` therefore ended the hook, and blocked the merge with only git's "Not
    committing merge", for every Python merge in a checkout with no `.env` (any
    linked worktree, since `.env` is ignored) on macOS's stock bash."""
    fx = Fixture(tmp_path, bash="/bin/bash")
    _venv(fx.primary, fx.marker)
    r = fx.merge(fx.primary)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "pytest passed" in r.stdout + r.stderr
    assert fx.ran() == ["venv:primary"]


def test_an_env_file_is_still_sourced(fx: Fixture):
    """The `.env` source stays (the header's security note explains it)."""
    _venv(fx.primary, fx.marker)
    (fx.primary / ".env").write_text(f"echo envread >> '{fx.marker}'\n")
    r = fx.merge(fx.primary)
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == ["envread", "venv:primary"]


def test_an_env_file_whose_last_command_fails_does_not_end_the_hook(fx: Fixture):
    """`|| true` stays beside the guard: a `.env` whose last line returns non-zero
    (`[ -n "$X" ] && export Y`) must not end a `set -e` hook."""
    _venv(fx.primary, fx.marker)
    (fx.primary / ".env").write_text('[ -n "${UNSET_IN_THIS_TEST:-}" ] && export Y=1\n')
    r = fx.merge(fx.primary)
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == ["venv:primary"]


def test_the_header_keeps_its_security_note_and_the_env_source():
    text = EXAMPLE.read_text(encoding="utf-8")
    assert "SECURITY NOTE" in text
    assert 'source "$REPO_ROOT/.env"' in text
    assert "preserved\n# verbatim" not in text, (
        "the example is no longer the source project's hook verbatim")
    assert "gdp-shaped" in text, "the provenance token that the token allowlist names"


# --- the shipped skeleton's commented backend block ---------------------------------
# `core/companion/git-hooks/pre-merge-commit` ships its pytest block commented out, for
# the consumer to uncomment. It carried the same `--show-toplevel` venv lookup, so a
# consumer who uncommented it met the same defect. These cases uncomment exactly that
# block and fire the skeleton the way git does.
SKELETON = REPO_ROOT / "core/companion/git-hooks/pre-merge-commit"


def _skeleton_with_backend_block_uncommented() -> str:
    lines = SKELETON.read_text(encoding="utf-8").split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith("# Backend tests"))
    end = next(i for i, l in enumerate(lines) if l.startswith("# Frontend build"))
    out, uncommented = [], 0
    for i, line in enumerate(lines):
        if start < i < end and (line.startswith("# if ") or line == "# fi"
                                or line.startswith("#   ")):
            out.append(line[2:])
            uncommented += 1
        else:
            out.append(line)
    assert uncommented > 10, "the skeleton's backend block was not found to uncomment"
    return "\n".join(out)


def _install_skeleton(fx: Fixture) -> None:
    hook = fx.primary / ".git" / "hooks" / "pre-merge-commit"
    hook.write_text(_skeleton_with_backend_block_uncommented(), encoding="utf-8")
    hook.chmod(0o755)
    fx.env["SYSOP_PROTECTED_BRANCH"] = "main"


def test_the_skeletons_uncommented_block_runs_the_main_checkouts_venv_in_a_worktree(fx: Fixture):
    _install_skeleton(fx)
    _venv(fx.primary, fx.marker)
    wt = fx.worktree_on_main()
    r = fx.merge(wt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == ["venv:primary"], (fx.ran(), r.stdout + r.stderr)


def test_the_skeletons_uncommented_block_blocks_on_a_failing_venv_pytest(fx: Fixture):
    _install_skeleton(fx)
    _venv(fx.primary, fx.marker, status=1)
    wt = fx.worktree_on_main()
    r = fx.merge(wt)
    assert r.returncode != 0, r.stdout + r.stderr
    assert fx.ran() == ["venv:primary"], (fx.ran(), r.stdout + r.stderr)


def test_the_skeletons_uncommented_block_falls_back_to_path_python3(fx: Fixture):
    _install_skeleton(fx)
    r = fx.merge(fx.primary)
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == ["path"], (fx.ran(), r.stdout + r.stderr)


# --- a venv with no `activate` -------------------------------------------------------
# Sourcing `activate` puts the venv first on PATH, so a bare `python3` would also reach
# it, and only the explicit "$PYTHON3" holds when there is no `activate` to source.
def test_a_venv_without_activate_still_runs_its_python3(fx: Fixture):
    _venv(fx.primary, fx.marker)
    (fx.primary / ".venv" / "bin" / "activate").unlink()
    wt = fx.worktree_on_main()
    r = fx.merge(wt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == ["venv:primary"], (fx.ran(), r.stdout + r.stderr)


def test_the_skeletons_block_runs_a_venv_without_activate(fx: Fixture):
    _install_skeleton(fx)
    _venv(fx.primary, fx.marker)
    (fx.primary / ".venv" / "bin" / "activate").unlink()
    wt = fx.worktree_on_main()
    r = fx.merge(wt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == ["venv:primary"], (fx.ran(), r.stdout + r.stderr)


# --- the round's cases (Phase 464) -----------------------------------------------------

def _activate_records(checkout: Path, marker: Path) -> None:
    """Make the venv's `activate` write `activate` to the marker when it is sourced."""
    act = checkout / ".venv" / "bin" / "activate"
    act.write_text(f"printf 'activate\\n' >> '{marker}'\n" + act.read_text(), encoding="utf-8")


def test_the_resolved_venvs_activate_is_sourced(fx: Fixture):
    _venv(fx.primary, fx.marker)
    _activate_records(fx.primary, fx.marker)
    wt = fx.worktree_on_main()
    r = fx.merge(wt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == ["activate", "venv:primary"], (fx.ran(), r.stdout + r.stderr)


def test_the_skeletons_block_sources_the_resolved_venvs_activate(fx: Fixture):
    _install_skeleton(fx)
    _venv(fx.primary, fx.marker)
    _activate_records(fx.primary, fx.marker)
    wt = fx.worktree_on_main()
    r = fx.merge(wt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == ["activate", "venv:primary"], (fx.ran(), r.stdout + r.stderr)


def test_a_venv_python3_that_is_not_executable_is_passed_over(fx: Fixture):
    _venv(fx.primary, fx.marker)
    py = fx.primary / ".venv" / "bin" / "python3"
    py.chmod(0o644)
    r = fx.merge(fx.primary)
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == ["path"], (fx.ran(), r.stdout + r.stderr)


def test_the_skeletons_block_prefers_the_main_checkouts_venv_over_a_worktrees_own(fx: Fixture):
    _install_skeleton(fx)
    _venv(fx.primary, fx.marker)
    wt = fx.worktree_on_main()
    _venv(wt, fx.marker)
    r = fx.merge(wt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == ["venv:primary"], (fx.ran(), r.stdout + r.stderr)


def _separate_git_dir_fixture(tmp: Path) -> Fixture:
    """A repository whose git dir lives elsewhere (`git init --separate-git-dir`), with a
    decoy `.venv` beside that git dir. The common dir's parent is then not the checkout."""
    fx = Fixture(tmp)
    gitdir = tmp / "store" / "proj.git"
    gitdir.parent.mkdir()
    fx.git(fx.primary, "init", "-q", "--separate-git-dir", str(gitdir))
    assert (fx.primary / ".git").is_file()
    _venv(tmp / "store", fx.marker)
    return fx


def test_separate_git_dir_runs_the_checkouts_own_venv(tmp_path: Path):
    fx = _separate_git_dir_fixture(tmp_path)
    hook = Path(fx.git(fx.primary, "rev-parse", "--git-path", "hooks").stdout.strip())
    if not hook.is_absolute():
        hook = fx.primary / hook
    hook.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(EXAMPLE, hook / "pre-merge-commit")
    (hook / "pre-merge-commit").chmod(0o755)
    _venv(fx.primary, fx.marker)
    r = fx.merge(fx.primary)
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == ["venv:primary"], (fx.ran(), r.stdout + r.stderr)


def test_the_skeletons_block_under_separate_git_dir_runs_the_checkouts_own_venv(tmp_path: Path):
    fx = _separate_git_dir_fixture(tmp_path)
    hook = Path(fx.git(fx.primary, "rev-parse", "--git-path", "hooks").stdout.strip())
    if not hook.is_absolute():
        hook = fx.primary / hook
    hook.mkdir(parents=True, exist_ok=True)
    (hook / "pre-merge-commit").write_text(_skeleton_with_backend_block_uncommented(), encoding="utf-8")
    (hook / "pre-merge-commit").chmod(0o755)
    fx.env["SYSOP_PROTECTED_BRANCH"] = "main"
    _venv(fx.primary, fx.marker)
    r = fx.merge(fx.primary)
    assert r.returncode == 0, r.stdout + r.stderr
    assert fx.ran() == ["venv:primary"], (fx.ran(), r.stdout + r.stderr)
