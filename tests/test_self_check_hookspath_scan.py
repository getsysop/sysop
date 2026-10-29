"""`Q-573` — `self_check.sh` probe 4a reads the directory git ACTUALLY runs, and only
when that directory is the one Sysop arms.

Probe 4a took its scan directory from `rev-parse --git-path hooks`, which FOLLOWS
`core.hooksPath`. Under the documented relative idiom `core.hooksPath=scripts/hooks`
it therefore scanned the consumer's OWN hooks directory, and its vendor alternation
(built from `sysop/scripts/`, so it carries `hooks/pre-commit` and the directory arm
`hooks/([^A-Za-z0-9_.-]|$)`) matched every live line a consumer spells
`scripts/hooks/…` — e.g. a delegate's `real="$top/scripts/hooks/$name"`. The printed
remedy ("repoint it at sysop/scripts/<name>") would break that resolution.

The decided shape (Wade): skip 4a whenever `core.hooksPath` is configured to anything
other than the repo's own git-dir hooks directory, and say so with an `info` line, so a
skipped probe does not read as a clean one. An EMPTY `core.hooksPath` means git runs no
hooks at all, and `--git-path hooks` answers `./` for it — which made 4a scan the
working-tree root as if it were a hooks directory.

Every row is a real subprocess against a scratch install, as in
`test_self_check_stale_hooks.py`. Each arm of the skip predicate gets a control that
changes only what that arm reads.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"

_GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
_FLAG = "still names a pre-migration scripts/ path"
_SKIP = "armed-hook path scan (4a) skipped"

# The reported consumer's shape: a delegate that resolves the CURRENT working tree's
# hook, plus hooks named like the two Sysop ships. Every line here is live and correct.
_DELEGATE = (
    '#!/bin/sh\n'
    'top="$(git rev-parse --show-toplevel)"\n'
    'name="$(basename "$0")"\n'
    'real="$top/scripts/hooks/$name"\n'
    '[ -x "$real" ] && exec "$real" "$@"\n'
)
# A genuinely stale body: the pre-Phase-128 flat vendor path.
_STALE = '#!/bin/sh\nbash "$(git rev-parse --show-toplevel)/scripts/run_checks.sh"\n'


def _env():
    env = {**os.environ, **_GIT_ISOLATION}
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    return env


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True, env=_env())


def _installed(tmp_path, name="c"):
    root = (tmp_path / name).resolve()
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("hi\n")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "seed")
    r = subprocess.run(["bash", str(INSTALL_SH), str(root), "--packs", "",
                        "--no-arm-hooks", "--yes"],
                       capture_output=True, text=True, env=_env())
    assert r.returncode == 0, r.stdout + r.stderr
    return root


def _consumer_hooks_dir(root):
    """The reporter's `scripts/hooks/`, with a Sysop-shipped hook NAME in it."""
    d = root / "scripts" / "hooks"
    d.mkdir(parents=True, exist_ok=True)
    for n in ("pre-commit", "pre-merge-commit"):
        p = d / n
        p.write_text(_DELEGATE)
        p.chmod(0o755)
    (d / "_delegate.sh").write_text(_DELEGATE)
    return d


def _arm_git_dir(root, name, body):
    hooks = root / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    p = hooks / name
    p.write_text(body)
    p.chmod(0o755)
    return p


def _self_check(root, cwd=None):
    return subprocess.run(["bash", str(root / "sysop/scripts/self_check.sh")],
                          cwd=str(cwd or root), capture_output=True, text=True,
                          env=_env())


class TestConsumerHooksPathIsNotScanned:
    def test_the_reported_case_is_green_and_says_why(self, tmp_path):
        """The upstream report. The consumer's live delegate line and its
        `pre-commit` / `pre-merge-commit` must not fail the health check, and the
        skip must be printed — a silent skip reads exactly like a clean scan."""
        root = _installed(tmp_path)
        _consumer_hooks_dir(root)
        _git(root, "config", "core.hooksPath", "scripts/hooks")
        r = _self_check(root)
        assert _FLAG not in r.stdout, r.stdout
        assert r.returncode == 0, r.stdout + r.stderr
        assert _SKIP in r.stdout, r.stdout
        assert "core.hooksPath='scripts/hooks'" in r.stdout, r.stdout

    def test_the_skip_holds_when_a_stale_body_is_in_the_consumer_dir(self, tmp_path):
        """The decided shape is a SKIP, not a narrower pattern: the consumer's
        directory is theirs. Pinned so a later 'narrow instead' edit is a decision,
        not a drift — and the info line has to be what tells the reader."""
        root = _installed(tmp_path)
        d = _consumer_hooks_dir(root)
        (d / "pre-push").write_text(_STALE)
        (d / "pre-push").chmod(0o755)
        _git(root, "config", "core.hooksPath", "scripts/hooks")
        r = _self_check(root)
        assert _FLAG not in r.stdout, r.stdout
        assert _SKIP in r.stdout, r.stdout

    def test_an_absolute_consumer_hookspath_is_skipped_too(self, tmp_path):
        root = _installed(tmp_path)
        d = _consumer_hooks_dir(root)
        _git(root, "config", "core.hooksPath", str(d))
        r = _self_check(root)
        assert _FLAG not in r.stdout, r.stdout
        assert _SKIP in r.stdout, r.stdout

    def test_empty_hookspath_scans_nothing(self, tmp_path):
        """`--git-path hooks` answers `./` for an empty `core.hooksPath`, so 4a
        used to scan the WORKING-TREE ROOT as a hooks directory — any top-level
        file naming an old vendor path failed the check, though git runs no hook."""
        root = _installed(tmp_path)
        (root / "NOTES.md").write_text("we used to run scripts/run_checks.sh here\n")
        _git(root, "config", "core.hooksPath", "")
        r = _self_check(root)
        assert _FLAG not in r.stdout, r.stdout
        assert r.returncode == 0, r.stdout + r.stderr
        assert _SKIP in r.stdout and "git runs no hooks" in r.stdout, r.stdout


class TestTheGitDirHooksDirectoryIsStillScanned:
    """Controls. Each one changes only what one arm of the skip predicate reads,
    and each must still produce the `✗` — or the fix has simply turned 4a off."""

    def test_unset_hookspath_with_a_stale_git_dir_hook_fails(self, tmp_path):
        """Arm 1 (HOOKS_PATH_SET). The consumer's `scripts/hooks/` exists in the
        tree exactly as in the reported case; only the config key is absent."""
        root = _installed(tmp_path)
        _consumer_hooks_dir(root)
        _arm_git_dir(root, "pre-push", _STALE)
        r = _self_check(root)
        assert r.returncode == 1, r.stdout + r.stderr
        assert f"armed hook 'pre-push' {_FLAG}" in r.stdout, r.stdout
        assert _SKIP not in r.stdout, r.stdout

    def test_hookspath_set_to_the_git_dir_hooks_relative_is_scanned(self, tmp_path):
        """Arm 2 (configured dir == git-dir hooks), relative spelling."""
        root = _installed(tmp_path)
        _arm_git_dir(root, "pre-push", _STALE)
        _git(root, "config", "core.hooksPath", ".git/hooks")
        r = _self_check(root)
        assert r.returncode == 1, r.stdout + r.stderr
        assert f"armed hook 'pre-push' {_FLAG}" in r.stdout, r.stdout
        assert _SKIP not in r.stdout, r.stdout

    def test_the_git_dir_hooks_comparison_holds_from_a_subdirectory(self, tmp_path):
        """Arm 2 run from `sub/`: `--git-common-dir` answers a path relative to the
        repo root, so the comparison must anchor it there, not at the caller's CWD
        (round lens 2, H07)."""
        root = _installed(tmp_path)
        _arm_git_dir(root, "pre-push", _STALE)
        _git(root, "config", "core.hooksPath", ".git/hooks")
        (root / "sub").mkdir()
        r = _self_check(root, cwd=root / "sub")
        assert r.returncode == 1, r.stdout + r.stderr
        assert f"armed hook 'pre-push' {_FLAG}" in r.stdout, r.stdout
        assert _SKIP not in r.stdout, r.stdout

    def test_hookspath_set_to_the_git_dir_hooks_through_a_symlink_is_scanned(self, tmp_path):
        """Arm 2, resolution half: the two sides are compared PHYSICALLY. A
        string compare would call this a consumer directory and skip it."""
        root = _installed(tmp_path)
        _arm_git_dir(root, "pre-push", _STALE)
        alias = tmp_path / "alias"
        alias.symlink_to(root / ".git")
        _git(root, "config", "core.hooksPath", f"{alias}/hooks/")
        r = _self_check(root)
        assert r.returncode == 1, r.stdout + r.stderr
        assert f"armed hook 'pre-push' {_FLAG}" in r.stdout, r.stdout
        assert _SKIP not in r.stdout, r.stdout

    def test_a_linked_worktree_compares_against_the_common_dir(self, tmp_path):
        """Arm 2, worktree half. From a linked worktree the default hooks live
        under the COMMON dir; comparing against the worktree's private git dir
        would skip the scan on every worktree run."""
        root = _installed(tmp_path)
        _arm_git_dir(root, "pre-push", _STALE)
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", "install")
        wt = (tmp_path / "wt").resolve()
        _git(root, "worktree", "add", "-q", str(wt))
        r = _self_check(wt, cwd=wt)
        assert f"armed hook 'pre-push' {_FLAG}" in r.stdout, r.stdout
        assert _SKIP not in r.stdout, r.stdout
        # core.hooksPath set explicitly to the COMMON dir's hooks is still Sysop's
        # directory from a worktree. This is the half that separates the common
        # dir from `--git-dir` (the worktree's private `.git/worktrees/<name>`).
        _git(wt, "config", "core.hooksPath", str(root / ".git" / "hooks"))
        r1 = _self_check(wt, cwd=wt)
        assert f"armed hook 'pre-push' {_FLAG}" in r1.stdout, r1.stdout
        assert _SKIP not in r1.stdout, r1.stdout
        # And the consumer idiom from the same worktree is skipped.
        _git(wt, "config", "core.hooksPath", "scripts/hooks")
        _consumer_hooks_dir(wt)
        r2 = _self_check(wt, cwd=wt)
        assert _FLAG not in r2.stdout, r2.stdout
        assert _SKIP in r2.stdout, r2.stdout


class TestInstallerHooksDirUnderHooksPath:
    """`install.sh`'s migration stale-reference report shares the vendor predicate
    with 4a (`test_self_check_stale_hooks.py` pins that), and picks its hooks
    directory with `resolve_hook_dst`, which also follows `core.hooksPath`.

    * **Non-empty value: followed on purpose, and this is a designed divergence
      from 4a.** The report runs only during the Phase-128 migration, when the old
      layout's `scripts/hooks/` IS the vendor directory being moved, so a reference
      into it is genuinely stale there. 4a runs on a migrated tree, where that
      directory is the consumer's.
    * **Empty value: the same `./` defect 4a had.** `resolve_hook_dst` named the
      working-tree root, and every top-level file was read with the WIDE hook arm."""

    @staticmethod
    def _report(root):
        from tests.test_install_namespace_migration import _run_update
        r = _run_update(root, env=_env())
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout

    @staticmethod
    def _old(tmp_path):
        from tests.test_install_namespace_migration import _build_old_consumer
        root, _ = _build_old_consumer(tmp_path / "old")
        return root

    def test_empty_hookspath_does_not_read_the_tree_root_as_hooks(self, tmp_path):
        root = self._old(tmp_path)
        (root / "NOTES.txt").write_text("deploy: bash scripts/my_deploy.sh\n")
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "gate.yml").write_text("on: push\n# grep -E '^scripts/x'\n")
        _git(root, "config", "core.hooksPath", "")
        out = self._report(root)
        assert "NOTES.txt:" not in out, \
            "a top-level consumer file was read as an armed hook under an empty core.hooksPath"
        # Control: the always-scan producer still runs past the skipped `find` —
        # the CI-workflow channel below it must still report.
        assert ".github/workflows/gate.yml:" in out, out

    def test_a_configured_hookspath_is_still_followed_during_migration(self, tmp_path):
        """Control for the arm above: only the EMPTY value changed. A non-empty
        value still routes the wide hook scan into the configured directory."""
        root = self._old(tmp_path)
        d = root / "myhooks"
        d.mkdir()
        (d / "pre-push").write_text("#!/bin/sh\ngit diff --cached --name-only | grep -E '^scripts/x'\n")
        (d / "pre-push").chmod(0o755)
        _git(root, "config", "core.hooksPath", "myhooks")
        out = self._report(root)
        assert "myhooks/pre-push:" in out, out

    def test_the_designed_divergence_from_4a_is_enumerated(self, tmp_path):
        """Same consumer directory, both programs. The installer (migration time)
        reports the old vendor path in it; the checker (post-migration) skips the
        directory and says so. A drift in either direction reddens this."""
        root = self._old(tmp_path)
        d = root / "myhooks"
        d.mkdir()
        (d / "pre-push").write_text(_STALE)
        (d / "pre-push").chmod(0o755)
        _git(root, "config", "core.hooksPath", "myhooks")
        out = self._report(root)
        assert "myhooks/pre-push:" in out, out
        sc = _self_check(root)
        assert _FLAG not in sc.stdout, sc.stdout
        assert _SKIP in sc.stdout, sc.stdout
