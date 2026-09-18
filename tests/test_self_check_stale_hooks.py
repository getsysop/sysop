"""`Q-541` leg 2 — `self_check.sh` reads what an armed hook CONTAINS.

The Phase 128 vendor move relocated `scripts/` to `sysop/scripts/`. A consumer's
armed hook that still names the old flat path is dead: git runs it, the line does
not resolve, and the gate it was arming is gone. Before this, `self_check.sh`
iterated the TEMPLATE directory and asked only whether an executable of that name
existed — so it never read a hook, and `pre-push` (which Sysop does not ship) was
never in the loop at all. It reported every probe green over exactly the breakage
a migration produces.

Real-subprocess tests against scratch installs, following `test_self_check_sh.py`.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
SELF_CHECK_SRC = REPO_ROOT / "core/companion/scripts/self_check.sh"

from tests.test_install_namespace_migration import _build_old_consumer, _run_update

_GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                   env={**os.environ, **_GIT_ISOLATION})


def _consumer(root):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("hi\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _install(target, *extra):
    env = {**os.environ, **_GIT_ISOLATION}
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    return subprocess.run(["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
                          capture_output=True, text=True, env=env)


def _self_check(root):
    env = {**os.environ, **_GIT_ISOLATION}
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    return subprocess.run(["bash", str(root / "sysop/scripts/self_check.sh")],
                          cwd=str(root), capture_output=True, text=True, env=env)


def _arm(root, name, body):
    hooks = root / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    p = hooks / name
    p.write_text(body)
    p.chmod(0o755)
    return p


def _installed(tmp_path):
    root = _consumer(tmp_path / "c")
    r = _install(root, "--packs", "")
    assert r.returncode == 0, r.stdout + r.stderr
    return root


class TestArmedHookContent:
    def test_fresh_install_is_green(self, tmp_path):
        """Non-vacuity control. Everything below asserts a FAILURE, so this is
        the row that proves the check is not simply always red."""
        r = _self_check(_installed(tmp_path))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "0 failed" in r.stdout
        assert "still names a pre-migration" not in r.stdout

    def test_armed_pre_push_with_old_vendor_path_fails(self, tmp_path):
        """The reported case. `pre-push` is the sharpest instance because Sysop
        ships no template for it, so the template loop could never reach it."""
        root = _installed(tmp_path)
        _arm(root, "pre-push",
             '#!/bin/sh\nREPO_ROOT=$(git rev-parse --show-toplevel)\n'
             'bash "$REPO_ROOT/scripts/run_checks.sh" --fail-on-blocking\n')
        r = _self_check(root)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "armed hook 'pre-push' still names a pre-migration scripts/ path" in r.stdout
        assert "0 failed" not in r.stdout

    def test_armed_template_hook_with_old_vendor_path_fails(self, tmp_path):
        """The same defect in a hook Sysop DOES ship. The template loop already
        saw this name and still called it armed, because it only tested for the
        file's existence."""
        root = _installed(tmp_path)
        _arm(root, "pre-commit",
             '#!/bin/sh\npython3 scripts/validate_tasks.py || exit 1\n')
        r = _self_check(root)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "armed hook 'pre-commit' still names a pre-migration scripts/ path" in r.stdout
        # And it must still be counted as armed — this is an extra finding, not
        # a replacement for the presence probe.
        assert "hook armed: pre-commit" in r.stdout

    def test_migrated_reference_is_green(self, tmp_path):
        """Control for the strip. The pattern has to admit the `/` in
        `$REPO_ROOT/scripts/…`; without neutralising the migrated spelling first
        it would match `sysop/scripts/…` through that same `/` and call every
        correctly-migrated hook broken."""
        root = _installed(tmp_path)
        _arm(root, "pre-push",
             '#!/bin/sh\nREPO_ROOT=$(git rev-parse --show-toplevel)\n'
             'bash "$REPO_ROOT/sysop/scripts/run_checks.sh" --fail-on-blocking\n')
        r = _self_check(root)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "still names a pre-migration" not in r.stdout

    def test_consumer_owned_script_is_green(self, tmp_path):
        """Control for the basename scoping. A consumer's own `scripts/` dir is
        not Sysop's and never moved; flagging it would make the check noise, and
        the one real consumer's armed hook calls two such scripts."""
        root = _installed(tmp_path)
        _arm(root, "pre-push",
             '#!/bin/sh\nREPO_ROOT=$(git rev-parse --show-toplevel)\n'
             'python3 "$REPO_ROOT/scripts/lint_ledger.py"\n'
             'bash scripts/my_deploy.sh\n')
        r = _self_check(root)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "still names a pre-migration" not in r.stdout

    def test_consumer_scripts_sharing_a_vendor_directory_prefix_are_green(self, tmp_path):
        """Round finding (execution lens), HIGH. A first version built the alternation
        from `basename` of the TOP LEVEL of `sysop/scripts/`, which put the bare words
        `run_checks`, `ci` and `hooks` — three DIRECTORIES — into it. With no right
        boundary, every one of these ordinary consumer paths failed the health check.
        `scripts/ci*` is a very common prefix in real repositories."""
        root = _installed(tmp_path)
        _arm(root, "pre-push",
             "#!/bin/sh\n"
             "bash scripts/circleci-deploy.sh\n"
             "bash scripts/hooks_helper.sh\n"
             "python3 scripts/run_checks_of_ours.py\n"
             "sh scripts/hooks/pre-push-extra\n"
             "bash scripts/ci/deploy.sh\n")
        r = _self_check(root)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "still names a pre-migration" not in r.stdout, \
            "a consumer path merely sharing a vendor DIRECTORY's name failed the check"

    def test_moved_directory_reference_is_flagged(self, tmp_path):
        """The other side of the same fix: a bare reference to a directory that DID
        move still has to be caught, or narrowing to files loses it."""
        root = _installed(tmp_path)
        _arm(root, "pre-push",
             '#!/bin/sh\ngrep -E "^scripts/run_checks/" files.txt\n')
        r = _self_check(root)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "armed hook 'pre-push' still names a pre-migration scripts/ path" in r.stdout

    def test_a_non_executable_sourced_helper_is_read(self, tmp_path):
        """Round finding (execution lens). A hook that sources a helper beside it is a
        common idiom, and the helper is where the dead path usually sits. Filtering the
        scan on the executable bit reported green over exactly that: git runs the hook,
        the helper fatals, and the gate is gone."""
        root = _installed(tmp_path)
        hooks = root / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        helper = hooks / "common.sh"
        helper.write_text(
            '#!/bin/sh\nrun_gate() { bash "$REPO_ROOT/scripts/run_checks.sh"; }\n')
        helper.chmod(0o644)          # not executable — sourced, never exec'd
        _arm(root, "pre-push", '#!/bin/sh\n. "$(dirname "$0")/common.sh"\nrun_gate\n')
        r = _self_check(root)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "armed hook 'common.sh' still names a pre-migration scripts/ path" in r.stdout

    def test_git_sample_hooks_are_ignored(self, tmp_path):
        """git's own `.sample` templates are executable and are not the
        consumer's. One of them (`pre-push.sample`) would otherwise be read."""
        root = _installed(tmp_path)
        _arm(root, "pre-push.sample",
             '#!/bin/sh\nbash "$REPO_ROOT/scripts/run_checks.sh"\n')
        r = _self_check(root)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "still names a pre-migration" not in r.stdout


class TestPredicateSharedWithTheInstaller:
    """The guard `self_check.sh`'s comment promises — reshaped by the round, twice.

    Two programs answer overlapping questions and cannot share a runtime import:
    `install.sh` runs from the Sysop clone, `self_check.sh` from the consumer's
    `sysop/scripts/`. The duplication is deliberate; this pins it.

    **Version 1 pinned their text** and could not see that `install.sh` holds its
    boundary in a shell variable, so the literal never appears.

    **Version 2 ran both — but asked them about different FILES.** It handed the
    installer a tracked `.md` and the checker an armed hook. `install.sh` scans
    hook-class files with a deliberately wider arm, so routing its half through a
    `.md` guaranteed both used their narrow pattern: the single configuration in
    which they agree. Asked about the same hook, they disagreed on two of its own
    six corpus lines, and the test was built so it could not see it.

    **Version 3 asks both about the SAME armed hook** and asserts the two things
    that are actually true: they agree on the vendor-path predicate, and
    `install.sh` is wider by exactly the basename-free arm — enumerated, not
    waved at. A divergence that moves in either direction reddens this."""

    # Asked of both programs, about the same armed hook. `agree=True` rows are the
    # shared vendor-path predicate. `agree=False` rows are the DESIGNED divergence:
    # install.sh's always-scan arm matches a bare `scripts/` because a staged-path
    # trigger regex carries no basename; self_check deliberately does not.
    CORPUS = (
        ("slash_vendor", 'bash "$REPO_ROOT/scripts/run_checks.sh"', True, True),
        ("bare_vendor", "bash scripts/run_checks.sh", True, True),
        ("python_vendor", "python3 scripts/validate_tasks.py", True, True),
        ("vendor_pkg_dir", "omit = scripts/run_checks/*", True, True),
        ("migrated", 'bash "$REPO_ROOT/sysop/scripts/run_checks.sh"', False, False),
        ("consumer_own", 'python3 "$REPO_ROOT/scripts/lint_ledger.py"', False, False),
        # Designed divergence — installer wider, checker quiet. On a HOOK or CI file the
        # installer matches a bare `scripts/` with no basename at all, because a
        # staged-path trigger regex carries none (`trigger_regex` below is the shape the
        # pre-existing TestT4StaleRefReport asserts must be caught). The cost is the
        # other three rows: the consumer's OWN scripts, reported under "update them
        # yourself". That cost is pre-Phase-309 behaviour, unchanged here — this phase
        # narrowed only the SETTINGS files, which have no basename-free forms — and these
        # rows exist so it is a measured, pinned cost rather than an unexamined one.
        # A first version of this corpus guessed `False` for two of them and the test
        # caught the guess.
        ("trigger_regex", "git diff --cached --name-only | grep -E '^scripts/x'", True, False),
        ("own_bare", "bash scripts/my_deploy.sh", True, False),
        ("own_ci_prefix", "bash scripts/circleci-deploy.sh", True, False),
        ("own_runchecks", "python3 scripts/run_checks_of_ours.py", True, False),
    )

    def test_both_programs_asked_about_the_same_armed_hook(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        hooks = root / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        for name, line, _, _ in self.CORPUS:
            h = hooks / name
            h.write_text(f"#!/bin/sh\n{line}\n")
            h.chmod(0o755)

        r = _run_update(root)
        assert r.returncode == 0, r.stdout + r.stderr
        marker = "stale references to old scripts/ paths"
        assert marker in r.stdout, \
            "the installer printed no report at all — every `not in` below would be vacuous"
        section = r.stdout.split(marker, 1)[1]

        env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null",
               "GIT_CONFIG_SYSTEM": "/dev/null"}
        env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
        sc = subprocess.run(["bash", str(root / "sysop/scripts/self_check.sh")],
                            cwd=str(root), capture_output=True, text=True, env=env)

        wrong = []
        for name, _, want_i, want_c in self.CORPUS:
            got_i = f".git/hooks/{name}:" in section
            got_c = f"armed hook '{name}' still names" in sc.stdout
            if got_i != want_i:
                wrong.append(f"{name}: installer={got_i}, expected {want_i}")
            if got_c != want_c:
                wrong.append(f"{name}: checker={got_c}, expected {want_c}")
        assert not wrong, "; ".join(wrong)

        # Non-vacuity, both directions and both programs: the corpus must exercise a
        # yes and a no from each, or every row could be satisfied by silence.
        assert any(i for _, _, i, _ in self.CORPUS) and not all(i for _, _, i, _ in self.CORPUS)
        assert any(c for _, _, _, c in self.CORPUS) and not all(c for _, _, _, c in self.CORPUS)
        # And the divergence must be non-empty, or "enumerated" describes nothing.
        assert any(i != c for _, _, i, c in self.CORPUS)


class TestCheckerEscapesItsOwnAlternation:
    """Round finding (guard lens), and the exact drift the pin above is named for.

    `install.sh`'s dot-escaping is pinned by `test_vendor_names_are_matched_literally`.
    The checker's identical `${vendor_base//./\\.}` was pinned by nothing: removing it
    left every test green while making `scripts/_logXpy` — a file that never existed —
    fail a consumer's health check, with the installer correctly silent on the same
    line. Tested one side, not the other, on a mechanism whose whole point is that the
    two sides agree."""

    def test_a_dot_in_a_vendor_name_is_literal(self, tmp_path):
        root = _installed(tmp_path)
        _arm(root, "pre-push", "#!/bin/sh\npython3 scripts/_logXpy --check\n")
        r = _self_check(root)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "still names a pre-migration" not in r.stdout, \
            "an unescaped dot matched a filename that never existed"

    def test_the_real_vendor_name_still_matches(self, tmp_path):
        """Non-vacuity control for the test above."""
        root = _installed(tmp_path)
        _arm(root, "pre-push", "#!/bin/sh\npython3 scripts/_log.py --check\n")
        r = _self_check(root)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "armed hook 'pre-push' still names a pre-migration scripts/ path" in r.stdout
