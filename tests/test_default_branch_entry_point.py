"""Phase 254 (`Q-377`) — the skill-facing default-branch entry point.

WHY THIS EXISTS SEPARATELY FROM `test_default_branch_resolution.py`
------------------------------------------------------------------
That module pins the *resolver* — `_git_lib.sh`'s `resolve_default_branch` and its Python
twin — behaviourally, over fixture repos. This one pins the **entry point** the skill layer
calls, which is a different contract with three parts the library does not have:

1. **stdout is a bare name and nothing else**, because the caller is an agent that
   substitutes what it reads into a git command. A stray banner becomes part of a refspec.
2. **stdout is EMPTY on failure.** A caller that ignores the exit code and substitutes the
   result gets `git diff ...HEAD` — a command that fails loudly — rather than
   `git diff origin/<wrong>...HEAD`, which silently compares the wrong things.
3. **It resolves from any checkout of the repository**, including a linked worktree
   standing on another branch, because `/claim-task` and `/auto-fix` run from worktrees.

The phase also shipped these as executed checks before any test existed; this module is
that verification made repeatable rather than a claim in a phase record.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests import shape_lib as S

SCRIPT = S.REPO_ROOT / "core" / "companion" / "scripts" / "default_branch.sh"
LIB = S.REPO_ROOT / "core" / "companion" / "scripts" / "_git_lib.sh"


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=check)


def _run(cwd: Path, *args: str, script: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(script or SCRIPT), *args], cwd=str(cwd),
                          capture_output=True, text=True)


def _repo(root: Path, branch: str = "main", *, commit: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", f"init.defaultBranch={branch}", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    if commit:
        (root / "seed.txt").write_text("x\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", "seed")
    return root


def _installed(root: Path) -> Path:
    """The script where a consumer has it — beside `_git_lib.sh` in `sysop/scripts/`.

    It resolves the library by `dirname "${BASH_SOURCE[0]}"`, so running it from the
    source tree while the fixture lives elsewhere would silently test the wrong layout.
    """
    d = root / "sysop" / "scripts"
    d.mkdir(parents=True, exist_ok=True)
    for src in (SCRIPT, LIB):
        (d / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return d / SCRIPT.name


def _declare_remote_head(repo: Path, bare: Path, branch: str) -> None:
    """What `git clone` leaves behind: a pushed branch and `refs/remotes/origin/HEAD`."""
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", branch)
    _git(repo, "remote", "set-head", "origin", branch)


# ---------------------------------------------------------------------------
# 1. The output contract
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("branch", ["main", "master", "develop"])
def test_it_prints_the_bare_name_and_nothing_else(tmp_path, branch):
    """`develop` needs a remote HEAD and the other two do not, which is the library's
    ladder showing through: step 2's no-remote fallback is `main`/`master` ONLY, by
    design ("nothing here guesses"). A `develop`-default repo with no remote is
    genuinely unresolvable, so the fixture declares the remote HEAD the way a real
    clone would — asserting otherwise would have pinned a behaviour the resolver does
    not have and must not grow."""
    repo = _repo(tmp_path / f"r-{branch}", branch)
    if branch not in ("main", "master"):
        _declare_remote_head(repo, tmp_path / f"bare-{branch}", branch)
    r = _run(repo, script=_installed(repo))
    assert r.returncode == 0, r.stderr
    assert r.stdout == f"{branch}\n", (
        "stdout is substituted into a git command — anything but the bare name "
        f"corrupts it; got {r.stdout!r}"
    )


def test_failure_prints_nothing_on_stdout(tmp_path):
    """The load-bearing half. An empty operand yields a command that fails loudly; a
    WRONG operand yields one that silently compares the wrong things."""
    repo = _repo(tmp_path / "ambiguous", "main")
    _git(repo, "branch", "master")          # both exist, no remote HEAD to break the tie
    r = _run(repo, script=_installed(repo))
    assert r.returncode == 1
    assert r.stdout == "", f"stdout must be empty on refusal, got {r.stdout!r}"
    assert "master" in r.stderr and "main" in r.stderr


def test_the_refusal_names_the_git_command_that_settles_it(tmp_path):
    repo = _repo(tmp_path / "ambiguous2", "main")
    _git(repo, "branch", "master")
    r = _run(repo, script=_installed(repo))
    assert "git remote set-head" in r.stderr, (
        "the diagnostic must name the command that fixes it — a refusal with no "
        "remedy is where the operator stops"
    )


def test_the_refusal_does_not_claim_this_script_makes_the_comparison(tmp_path):
    """`require_default_branch`'s suffix reads `<name> cannot continue without it — every
    branch comparison IT makes is against that branch`, which is false for an entry point
    that makes none. This is why the script calls `resolve_` and adds its own line."""
    repo = _repo(tmp_path / "ambiguous3", "main")
    _git(repo, "branch", "master")
    r = _run(repo, script=_installed(repo))
    assert "every branch comparison it makes" not in r.stderr
    assert "The skill step that asked for the default branch" in r.stderr


# ---------------------------------------------------------------------------
# 2. Where it can be run from
# ---------------------------------------------------------------------------
def test_it_resolves_from_a_linked_worktree_on_another_branch(tmp_path):
    """`/claim-task` and `/auto-fix` run inside batch worktrees. Refs are shared across
    every worktree of a repository, which is the property that makes this safe — asserted
    here rather than assumed from the library's docstring."""
    repo = _repo(tmp_path / "wt-repo", "master")
    script = _installed(repo)
    wt = tmp_path / "wt-linked"
    _git(repo, "worktree", "add", "-q", str(wt), "-b", "feature")
    r = _run(wt, script=script)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "master", (
        "a worktree standing on `feature` must still report the repository's default "
        "branch, not its own HEAD"
    )


def test_it_resolves_from_a_subdirectory(tmp_path):
    repo = _repo(tmp_path / "sub-repo", "master")
    script = _installed(repo)
    deep = repo / "a" / "b"
    deep.mkdir(parents=True)
    r = _run(deep, script=script)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "master"


def test_outside_a_git_repository_it_refuses_rather_than_guessing(tmp_path):
    repo = _repo(tmp_path / "host", "main")
    script = _installed(repo)
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    r = _run(outside, script=script)
    assert r.returncode == 1
    assert r.stdout == ""
    assert "Not inside a git repository" in r.stderr


# ---------------------------------------------------------------------------
# 3. Operands, and the missing-library failure
# ---------------------------------------------------------------------------
def test_an_explicit_checkout_operand_is_honoured(tmp_path):
    host = _repo(tmp_path / "host2", "main")
    script = _installed(host)
    other = _repo(tmp_path / "other", "master")
    r = _run(host, str(other), script=script)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "master", "the operand must select the checkout, not the CWD"


def test_more_than_one_operand_is_refused(tmp_path):
    repo = _repo(tmp_path / "arity", "main")
    r = _run(repo, "a", "b", script=_installed(repo))
    assert r.returncode == 1
    assert r.stdout == ""
    assert "Usage" in r.stderr


def test_help_exits_zero_and_prints_usage(tmp_path):
    """Documented in the header and, until this phase's round, tested nowhere: both
    "`--help` exits 1" and "the `-h|--help` case is deleted, so `--help` is read as a
    checkout operand and reported as `Not inside a git repository: --help`" survived the
    first version of this module."""
    repo = _repo(tmp_path / "helprepo", "main")
    script = _installed(repo)
    for flag in ("-h", "--help"):
        r = _run(repo, flag, script=script)
        assert r.returncode == 0, f"{flag}: {r.stderr}"
        assert "Usage:" in r.stdout, f"{flag} printed no usage: {r.stdout!r}"
        assert "Not inside a git repository" not in r.stderr, (
            f"{flag} was parsed as a checkout operand"
        )


def test_a_missing_library_fails_loud_and_names_the_recovery(tmp_path):
    """It sources `_git_lib.sh` from beside itself. A hand-copied single script is the one
    way to lose the library, and the message has to say so — the same contract the three
    lifecycle scripts state."""
    repo = _repo(tmp_path / "nolib", "main")
    script = _installed(repo)
    (script.parent / LIB.name).unlink()
    r = _run(repo, script=script)
    assert r.returncode == 1
    assert r.stdout == ""
    assert "_git_lib.sh is missing" in r.stderr
    assert "sysop-update.sh" in r.stderr


# ---------------------------------------------------------------------------
# 4. Non-vacuity — the population this file's claims rest on
# ---------------------------------------------------------------------------
def test_the_entry_point_delegates_and_does_not_reimplement():
    """Non-vacuity for everything above, plus the one design choice worth pinning.

    A third copy of the resolution ladder is the failure this entry point exists to avoid
    (the tree holds exactly two, pinned to each other behaviourally). And it deliberately
    calls `resolve_default_branch`, NOT `require_default_branch`, because the library's
    "which script stopped" suffix is false for a caller that makes no branch comparison —
    `test_the_refusal_does_not_claim_this_script_makes_the_comparison` is the behavioural
    half of this.
    """
    assert SCRIPT.is_file(), "the entry point must exist for anything above to mean anything"
    text = SCRIPT.read_text(encoding="utf-8")
    assert "source" in text and "_git_lib.sh" in text, "it must source the library, not inline it"
    body = "\n".join(ln for ln in text.split("set -euo pipefail", 1)[1].splitlines()
                     if not ln.lstrip().startswith("#"))
    assert 'resolve_default_branch "' in body, "the entry point must call the library resolver"
    assert "require_default_branch" not in body, (
        "it calls `resolve_`, not `require_`, on purpose: the library's closing line says "
        "the caller cannot continue because 'every branch comparison it makes is against "
        "that branch', and this script makes none — its caller does"
    )
    # The ladder itself must live only in the library: no `symbolic-ref refs/remotes`
    # probe, no main/master fallback list, in the entry point.
    for reimplementation in ("refs/remotes/", "refs/heads/main", "have_master"):
        assert reimplementation not in text, (
            f"{reimplementation!r} in the entry point means the resolution ladder was "
            "copied rather than delegated — the third-copy failure this avoids"
        )
