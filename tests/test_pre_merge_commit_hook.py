"""`Q-376` (Phase 368) — the shipped `pre-merge-commit` gates the DEFAULT branch.

The template hard-coded `PROTECTED_BRANCH="main"` and exited 0 whenever `HEAD` was not
that branch, so on a `master`-default consumer every merge skipped the gate — silently,
and invisibly today only because every check in the skeleton is commented out. The day a
consumer uncomments one on a `master` repository it never runs and nothing says so.

These tests drive the REAL install path rather than running the file in place, because
where the hook lives is the whole fix: `install_hooks.sh` copies it into
`$(git rev-parse --git-path hooks)` (`.git/hooks/`), so a `dirname`-relative `source`
would look for `.git/_git_lib.sh`. The fixture is a consumer laid out as `install.sh`
leaves it — `_git_lib.sh` in `sysop/scripts/`, the template in `sysop/scripts/hooks/` —
armed by the real `install_hooks.sh`, and the hook is exercised by a real
`git merge --no-ff`, which is what fires `pre-merge-commit`.

"The gate ran" is asserted two ways: the banner the hook prints once it has decided the
merge is on the protected branch, and — for the case the entry is about — a fixture copy
with a failing check enabled, whose merge must be BLOCKED. A banner alone could be
printed by a body that then gates nothing.
"""
from __future__ import annotations

import os
import subprocess
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "core/companion/git-hooks/pre-merge-commit"
LIB = REPO_ROOT / "core/companion/scripts/_git_lib.sh"
INSTALL_HOOKS = REPO_ROOT / "core/companion/scripts/install_hooks.sh"

BANNER = "Running checks before merging to "
# Unique to the fallback warning: the banner line also starts "pre-merge-commit:", and git
# routes a hook's stdout to stderr, so the stream does not tell them apart.
WARNING = "gating 'main'"


def _env(**extra: str) -> dict:
    """Inherited `GIT_*` stripped (a hook-run pytest exports `GIT_DIR` and friends,
    which would point every fixture command at the invoking repository), global and
    system config nulled (a contributor's `core.hooksPath` would send `install_hooks.sh`
    down its skip path), and `SYSOP_PROTECTED_BRANCH` cleared unless a test sets it."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_") and k != "SYSOP_PROTECTED_BRANCH"}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null", **extra)
    return env


def _git(cwd: Path, *args: str, check: bool = True, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                          check=check, env=_env(**env))


def _consumer(root: Path, default: str = "master", *, lib: bool = True,
              hook_text: str | None = None) -> Path:
    """A consumer on `default`, with Sysop's files where `install.sh` puts them, and the
    hook armed by the real `install_hooks.sh`."""
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", default)
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    scripts = root / "sysop" / "scripts"
    (scripts / "hooks").mkdir(parents=True)
    (scripts / "install_hooks.sh").write_text(INSTALL_HOOKS.read_text(encoding="utf-8"), encoding="utf-8")
    if lib:
        (scripts / "_git_lib.sh").write_text(LIB.read_text(encoding="utf-8"), encoding="utf-8")
    (scripts / "hooks" / "pre-merge-commit").write_text(
        hook_text if hook_text is not None else HOOK.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "seed.txt").write_text("seed\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    r = subprocess.run(["bash", str(scripts / "install_hooks.sh")], cwd=str(root),
                       capture_output=True, text=True, env=_env())
    assert r.returncode == 0, r.stdout + r.stderr
    armed = Path(_git(root, "rev-parse", "--git-path", "hooks").stdout.strip())
    armed = armed if armed.is_absolute() else root / armed
    assert (armed / "pre-merge-commit").is_file(), "install_hooks.sh did not arm the hook"
    return root


def _merge_into(repo: Path, target: str, **env: str) -> subprocess.CompletedProcess:
    """Merge a fresh one-commit side branch into `target` with `--no-ff`: a merge
    commit is what fires `pre-merge-commit` (a fast-forward fires nothing)."""
    _git(repo, "checkout", "-q", target)
    side = f"side-{target}-{len(list(repo.iterdir()))}"
    _git(repo, "checkout", "-qb", side)
    (repo / f"{side}.txt").write_text("w\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"work on {side}")
    _git(repo, "checkout", "-q", target)
    return _git(repo, "merge", "--no-ff", "-m", f"merge {side}", side, check=False, **env)


def _out(r: subprocess.CompletedProcess) -> str:
    return r.stdout + r.stderr


def _failing_hook() -> str:
    """The shipped template with one blocking check enabled — the state the entry is
    about ("the day they uncomment a check"). Derived from the template, so the
    resolution logic under test is the shipped one."""
    text = HOOK.read_text(encoding="utf-8")
    assert text.count("\nFAILED=false\n") == 1
    return text.replace("\nFAILED=false\n", "\nFAILED=true\n", 1)


# ---------------------------------------------------------------------------
# The entry's case: a `master`-default consumer
# ---------------------------------------------------------------------------
def test_a_merge_into_master_runs_the_gate_on_a_master_repository(tmp_path):
    repo = _consumer(tmp_path / "c")
    r = _merge_into(repo, "master")
    assert r.returncode == 0, _out(r)
    assert BANNER + "master" in _out(r), (
        "the gate exited before its checks on a master-default repository — the "
        f"`Q-376` no-op: {_out(r)!r}")
    assert WARNING not in _out(r), _out(r)


def test_an_enabled_check_blocks_a_merge_into_master(tmp_path):
    """The consequence, not just the banner: with a failing check enabled, the merge
    into `master` must not complete."""
    repo = _consumer(tmp_path / "c", hook_text=_failing_hook())
    before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    r = _merge_into(repo, "master")
    assert r.returncode != 0, f"the merge into master was not blocked: {_out(r)!r}"
    assert "MERGE BLOCKED" in _out(r), _out(r)
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == before, "a merge commit landed"


def test_a_merge_into_another_branch_is_not_gated_and_says_nothing(tmp_path):
    repo = _consumer(tmp_path / "c", hook_text=_failing_hook())
    _git(repo, "branch", "feature")
    r = _merge_into(repo, "feature")
    assert r.returncode == 0, _out(r)
    assert BANNER not in _out(r) and WARNING not in _out(r), _out(r)


def test_a_main_repository_still_gates_main(tmp_path):
    repo = _consumer(tmp_path / "c", "main")
    r = _merge_into(repo, "main")
    assert r.returncode == 0 and BANNER + "main" in _out(r), _out(r)
    assert WARNING not in r.stderr, r.stderr


# ---------------------------------------------------------------------------
# The override knobs
# ---------------------------------------------------------------------------
def test_the_environment_override_wins_over_the_resolved_default(tmp_path):
    repo = _consumer(tmp_path / "c")
    _git(repo, "branch", "release")
    r = _merge_into(repo, "master", SYSOP_PROTECTED_BRANCH="release")
    assert r.returncode == 0 and BANNER not in _out(r), _out(r)
    r = _merge_into(repo, "release", SYSOP_PROTECTED_BRANCH="release")
    assert BANNER + "release" in _out(r), _out(r)


def test_the_in_file_setting_wins_over_the_environment(tmp_path):
    """The knob the template always had — editing the variable — keeps working, and
    an edited file is the more specific statement, so it outranks the env var."""
    text = HOOK.read_text(encoding="utf-8")
    assert text.count('\nPROTECTED_BRANCH=""\n') == 1
    repo = _consumer(tmp_path / "c", hook_text=text.replace(
        '\nPROTECTED_BRANCH=""\n', '\nPROTECTED_BRANCH="release"\n', 1))
    _git(repo, "branch", "release")
    r = _merge_into(repo, "release", SYSOP_PROTECTED_BRANCH="master")
    assert BANNER + "release" in _out(r), _out(r)
    r = _merge_into(repo, "master", SYSOP_PROTECTED_BRANCH="master")
    assert BANNER not in _out(r), _out(r)


# ---------------------------------------------------------------------------
# The fallback: the literal `main`, never silently
# ---------------------------------------------------------------------------
def test_a_missing_library_falls_back_to_main_with_a_warning(tmp_path):
    """A hand-copied hook, or a partial install, has no `_git_lib.sh` beside it
    (both install modes ship it since Phase 368). The literal is kept for that
    case — but announced, with the knob that silences it."""
    repo = _consumer(tmp_path / "c", lib=False)
    r = _merge_into(repo, "master")
    assert r.returncode == 0, _out(r)
    assert "_git_lib.sh is not in this checkout" in r.stderr and "gating 'main'" in r.stderr, _out(r)
    assert "SYSOP_PROTECTED_BRANCH" in r.stderr, r.stderr
    assert BANNER not in _out(r), _out(r)
    _git(repo, "branch", "main")
    r = _merge_into(repo, "main")
    assert BANNER + "main" in _out(r), _out(r)


def test_an_unresolvable_default_falls_back_to_main_with_a_warning(tmp_path):
    """Both `main` and `master`, no remote HEAD to break the tie: the library refuses.
    One line points at the entry point that explains why; the library's six-line
    diagnostic is not repeated on every merge."""
    repo = _consumer(tmp_path / "c")
    _git(repo, "branch", "main")
    r = _merge_into(repo, "master")
    assert r.returncode == 0, _out(r)
    assert "default branch could not be resolved" in r.stderr, r.stderr
    assert "bash sysop/scripts/default_branch.sh" in r.stderr and "gating 'main'" in r.stderr, r.stderr
    assert "Cannot resolve this repository's default branch" not in r.stderr, r.stderr


def test_a_broken_library_degrades_to_the_warning_not_a_blocked_merge(tmp_path):
    """`set -e` turns a failed `source` into exit 1, and exit 1 from this hook BLOCKS
    the merge. A hook that cannot tell which branch it guards must not stop a merge
    for that reason alone."""
    repo = _consumer(tmp_path / "c")
    (repo / "sysop/scripts/_git_lib.sh").write_text("return 3\n")
    r = _merge_into(repo, "master")
    assert r.returncode == 0, f"a broken library blocked the merge: {_out(r)!r}"
    assert "could not be sourced" in r.stderr and "gating 'main'" in r.stderr, r.stderr


# Every bash the hook can run under: its shebang is `#!/usr/bin/env bash`, which on
# stock macOS is /bin/bash 3.2, where a syntax error in a sourced file is fatal to the
# sourcing shell rather than a failed `source`.
_BASHES = sorted({p for p in ("/bin/bash", shutil.which("bash") or "") if p and Path(p).is_file()})

_FATAL_LIBRARIES = {
    "unbound-variable": 'echo "$UNDEFINED_VAR_X"\n',
    "syntax-error": "if true; then\n",
    "exit-on-load": "exit 7\n",
}


@pytest.mark.parametrize("bash", _BASHES)
@pytest.mark.parametrize("kind", sorted(_FATAL_LIBRARIES))
def test_a_library_that_dies_while_loading_does_not_block_the_merge(tmp_path, kind, bash):
    """Phase 368's round: `if ! source` stops `set -e`, not a FATAL error raised while
    the file loads — an unbound variable under the hook's `set -u`, a bash 3.2 syntax
    error, an `exit` — each of which killed the hook and blocked the merge. Loading
    happens in a subshell now, so the hook survives to its warning."""
    hook = HOOK.read_text(encoding="utf-8")
    assert hook.startswith("#!/usr/bin/env bash\n")
    repo = _consumer(tmp_path / "c", hook_text=hook.replace("#!/usr/bin/env bash", f"#!{bash}", 1))
    (repo / "sysop/scripts/_git_lib.sh").write_text(_FATAL_LIBRARIES[kind])
    r = _merge_into(repo, "master")
    assert r.returncode == 0, f"{kind} under {bash} blocked the merge: {_out(r)!r}"
    assert "could not be sourced" in r.stderr and WARNING in r.stderr, r.stderr


@pytest.mark.parametrize("bash", _BASHES)
def test_a_resolver_that_dies_does_not_block_the_merge(tmp_path, bash):
    """The same, one step later: the library loads, and the function it defines dies."""
    hook = HOOK.read_text(encoding="utf-8")
    repo = _consumer(tmp_path / "c", hook_text=hook.replace("#!/usr/bin/env bash", f"#!{bash}", 1))
    (repo / "sysop/scripts/_git_lib.sh").write_text(
        'resolve_default_branch() { echo "$UNDEFINED_VAR_Y"; }\n')
    r = _merge_into(repo, "master")
    assert r.returncode == 0, f"under {bash}: {_out(r)!r}"
    assert "could not be resolved" in r.stderr and WARNING in r.stderr, r.stderr


def test_an_empty_resolve_gates_main_and_says_why(tmp_path):
    """A resolver that exits 0 and prints nothing is not a branch: before the round's
    fix the hook gated `main` with a warning whose reason was the empty string."""
    repo = _consumer(tmp_path / "c")
    (repo / "sysop/scripts/_git_lib.sh").write_text("resolve_default_branch() { :; }\n")
    r = _merge_into(repo, "master")
    assert r.returncode == 0 and "could not be resolved" in r.stderr and WARNING in r.stderr, r.stderr


def test_the_library_is_found_from_the_repo_root_in_a_linked_worktree(tmp_path):
    """Hooks are shared by every worktree and run from the worktree's top level, so
    the library is looked up in the checkout doing the merge."""
    repo = _consumer(tmp_path / "c")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "wt-target", str(wt))
    _git(wt, "checkout", "-q", "--detach")
    _git(repo, "checkout", "-q", "--detach")
    r = _merge_into(wt, "master")
    assert r.returncode == 0 and BANNER + "master" in _out(r), _out(r)
    assert WARNING not in r.stderr, r.stderr


def test_the_template_carries_no_literal_main_assignment():
    """Text pin for the one line the entry names, alongside the behavioural tests
    above: the protected branch is not assigned the literal `main` anywhere but the
    announced fallback."""
    code = [ln.strip() for ln in HOOK.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]
    assigns = [ln for ln in code if ln.startswith("PROTECTED_BRANCH=")]
    assert 'PROTECTED_BRANCH="main"' in assigns, "the announced fallback is gone"
    assert assigns[0] == 'PROTECTED_BRANCH=""', assigns
