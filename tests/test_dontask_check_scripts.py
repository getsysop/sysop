"""The three scripts Phase 421 ships so `/review-close`'s prepare runs under `dontAsk` (`Q-665`, `Q-710`).

Under `dontAsk` the shell the skills prescribed was denied line by line (Phase 421's probes,
`tools/phase421_probe_log.jsonl`): `test` binds no rule, an `exit` or a `{ …; }` group is denied
wherever it sits, `git -C` is denied at every path, and `rm -f`, a `>` redirect, `mktemp -d`,
`PIN=$(…)`, `case`, `| while read` and `diff <(…)` are denied. Each script is a check or an
action as one command a seeded rule admits:

* `git_check.py` — Rule A and the fail-stops: exit 0 holds, 1 does not, 2 could not be measured,
  3 an operand is a placeholder; a branch is compared as `refs/heads/<name>` (`Q-703`), so a
  branch whose name merely ends in it (`release/main`) cannot pass for it;
* `git_ro.py` — read-only git in another worktree of the repository: an allowlist of subcommands,
  refusals for the arguments that make one write or run a program, and only `git worktree list`'s
  paths;
* `review_pins.py` — Step 2b's baselines, a pinned checkout under the ignored `sysop/runtime/`,
  its removal (never `--force`) and the five post-spawn assertions with their clean lines.

Each is run as a subprocess in a scratch repository, as a skill runs it. The module's last section
guards the skills' side: every Rule A check is chained into its write with `&&`, and the prepare
reaches no worktree through `git -C`.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from skill_runner_text import text_of

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "core" / "companion" / "scripts"
GIT_ENV = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
ID = ("-c", "user.email=t@t", "-c", "user.name=t")


def g(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, check=True, capture_output=True,
                          text=True).stdout.strip()


def run(script: str, cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    # A timeout and no stdin: a mutant that lets an argument through can start a program that
    # waits on a terminal (Phase 421's battery hung 8 h on `grep -Ovim`), and a hang measures
    # nothing.
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=cwd,
                          env={**GIT_ENV, **(env or {})},
                          capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    g(r, "init", "-q", "-b", "main")
    (r / ".gitignore").write_text("sysop/runtime/\n")
    g(r, "add", ".gitignore")
    g(r, *ID, "commit", "-q", "-m", "init")
    g(r, "checkout", "-q", "-b", "feat")
    (r / "f.txt").write_text("feat\n")
    g(r, "add", "f.txt")
    g(r, *ID, "commit", "-q", "-m", "feat")
    g(r, "checkout", "-q", "main")
    return r


# --- git_check.py ---------------------------------------------------------------------------

@pytest.mark.parametrize("args,code,line", [
    (("head-is", "main"), 0, "OK: HEAD is refs/heads/main"),
    (("head-is", "refs/heads/main"), 0, "OK: HEAD is refs/heads/main"),
    (("head-is", "feat"), 1, "STOP: HEAD is refs/heads/main, not refs/heads/feat"),
    (("head-is-not", "feat"), 0, "OK: HEAD is refs/heads/main, not refs/heads/feat"),
    (("head-is-not", "main"), 1, "STOP: HEAD is refs/heads/main; this step must not run on"),
    (("head-matches", "ma*"), 0, "OK:"),
    (("head-matches", "merge/review-close-*"), 1, "STOP:"),
    (("primary-checkout",), 0, "OK: this is the primary checkout"),
    (("ancestor", "refs/heads/main", "refs/heads/feat"), 0, "OK: refs/heads/main is an ancestor of"),
    (("ancestor", "refs/heads/feat", "refs/heads/main"), 1, "STOP: refs/heads/feat is not an ancestor"),
    (("ancestor", "refs/heads/nope", "HEAD"), 2, "STOP: refs/heads/nope does not name a commit"),
    # Phase 421's round, lens A: a short name resolves to whatever shadows it.
    (("ancestor", "HEAD", "origin/main"), 3, "STOP: operand 'origin/main' is a short name"),
    (("ancestor", "main", "HEAD"), 3, "STOP: operand 'main' is a short name"),
    (("nothing-staged", "f.txt"), 0, "OK: nothing is staged at f.txt"),
    (("file", ".gitignore"), 0, "OK:"),
    (("file", "absent"), 1, "STOP: no such file: absent"),
    (("file", ".git"), 1, "STOP: no such file: .git"),          # a directory is not a file (lens B)
    (("head-is", "main", "extra"), 2, "STOP: head-is takes 1 operand(s), got 2"),
    (("head-is", "<default branch>"), 3, "STOP: operand"),
    (("head-is", ""), 3, "STOP: operand"),
    (("head-is",), 2, "STOP: head-is takes 1 operand"),
    (("bogus",), 2, "STOP: usage"),
])
def test_git_check_exit_codes_and_lines(repo: Path, args, code, line) -> None:
    p = run("git_check.py", repo, *args)
    assert (p.returncode, p.stdout.count("\n")) == (code, 1), p.stdout + p.stderr
    assert p.stdout.startswith(line), p.stdout


@pytest.mark.parametrize("args,line", [
    (("head-is", "main"), "STOP: git symbolic-ref HEAD failed"),
    (("nothing-staged", "f.txt"), "STOP: git diff --cached failed"),
])
def test_git_check_outside_a_repository_could_not_measure(tmp_path: Path, args, line) -> None:
    """Exit 2, not 1: a check that could not run is not a check that failed (lens B)."""
    (tmp_path / "none").mkdir()
    p = run("git_check.py", tmp_path / "none", *args, env={"GIT_CEILING_DIRECTORIES": str(tmp_path)})
    assert (p.returncode, p.stdout.startswith(line)) == (2, True), p.stdout


def test_git_check_fork_has_reads_origins_default_branch(repo: Path) -> None:
    """`Q-712`: an isolated reviewer's checkout is forked from `origin/<default branch>` (measured,
    Phase 421), so a file committed only on the local branch is not there for it."""
    g(repo, "update-ref", "refs/remotes/origin/main", "main")
    (repo / "tool.txt").write_text("x\n")
    g(repo, "add", "tool.txt")
    g(repo, *ID, "commit", "-q", "-m", "an update, not pushed")
    p = run("git_check.py", repo, "fork-has", "main", "tool.txt")
    assert p.returncode == 1 and "is not on refs/remotes/origin/main" in p.stdout, p.stdout
    g(repo, "update-ref", "refs/remotes/origin/main", "main")
    p = run("git_check.py", repo, "fork-has", "main", "tool.txt")
    assert p.returncode == 0 and p.stdout.startswith("OK: tool.txt is on refs/remotes/origin/main"), p.stdout


@pytest.mark.parametrize("args,code,line", [
    (("fork-has", "main", ".gitignore"), 0, "OK: .gitignore is on refs/heads/main"),   # no origin: the local branch
    (("fork-has", "main", "f.txt"), 1, "STOP: f.txt is not on refs/heads/main"),
    (("fork-has", "nope", ".gitignore"), 2, "STOP: refs/heads/nope does not name a commit"),
    (("fork-has", "<default branch>", ".gitignore"), 3, "STOP: operand"),
    (("fork-has", "main"), 2, "STOP: fork-has takes 2 operand(s)"),
])
def test_git_check_fork_has_without_an_origin(repo: Path, args, code, line) -> None:
    p = run("git_check.py", repo, *args)
    assert (p.returncode, p.stdout.startswith(line)) == (code, True), p.stdout


def test_git_check_a_branch_ending_in_the_name_does_not_pass_for_it(repo: Path) -> None:
    """`Q-703`: the comparison is of whole refnames. HEAD is a branch (`symbolic-ref`), so a tag
    can never be what it names; the short-name hazard is a suffix, `release/main` read as on
    `main`, and that is the case a guard on `main` exists to stop."""
    g(repo, "checkout", "-q", "-b", "release/main")
    for args in (("head-is", "main"), ("head-is", "refs/heads/main")):
        p = run("git_check.py", repo, *args)
        assert p.returncode == 1 and "refs/heads/release/main" in p.stdout, (args, p.stdout)
    assert run("git_check.py", repo, "head-is-not", "main").returncode == 0


def test_git_check_ancestor_is_not_fooled_by_a_branch_named_like_the_remote(repo: Path) -> None:
    """`/release` 8.3 tags only a HEAD `refs/remotes/origin/<default>` contains. A local branch
    called `origin/main` at HEAD made the short form pass over an unpushed commit."""
    g(repo, "update-ref", "refs/remotes/origin/main", "main")
    g(repo, *ID, "commit", "-q", "--allow-empty", "-m", "unpushed")
    g(repo, "branch", "origin/main", "HEAD")
    p = run("git_check.py", repo, "ancestor", "HEAD", "refs/remotes/origin/main")
    assert p.returncode == 1, p.stdout


def test_git_check_staged_and_detached_and_linked(repo: Path, tmp_path: Path) -> None:
    (repo / "x").write_text("x\n")
    g(repo, "add", "x")
    assert run("git_check.py", repo, "nothing-staged", "x").returncode == 1
    wt = tmp_path / "wt"
    g(repo, "worktree", "add", "-q", "--detach", str(wt), "feat")
    assert run("git_check.py", wt, "primary-checkout").returncode == 1
    for args in (("head-is", "main"), ("head-is-not", "main"), ("head-matches", "*")):
        p = run("git_check.py", wt, *args)
        assert p.returncode == 1 and "detached" in p.stdout, (args, p.stdout)


def test_git_check_lock_reads_the_main_checkout_from_a_linked_worktree(repo: Path,
                                                                     tmp_path: Path) -> None:
    """Locks live in the main checkout (Phase 32); Step 2d may run from any worktree."""
    locks = repo / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    (locks / "T-1.lock").write_text("task: T-1\n")
    wt = tmp_path / "wt"
    g(repo, "worktree", "add", "-q", "--detach", str(wt), "feat")
    for where in (repo, wt):
        p = run("git_check.py", where, "lock", "T-1")
        assert p.returncode == 0 and p.stdout.startswith("OWED"), (where, p.stdout)
    p = run("git_check.py", wt, "lock", "T-2")
    assert p.returncode == 1 and p.stdout.startswith("CANNOT TELL"), p.stdout


def test_git_check_chains_into_the_write_it_guards(repo: Path) -> None:
    """The ruled shape: `check && write` is one call, and a failing check stops the write."""
    shell = f'"{sys.executable}" "{SCRIPTS / "git_check.py"}" head-is feat && git {" ".join(ID)} commit --allow-empty -qm x'
    before = g(repo, "rev-parse", "HEAD")
    p = subprocess.run(["bash", "-c", shell], cwd=repo, env=GIT_ENV, capture_output=True, text=True)
    assert p.returncode == 1 and g(repo, "rev-parse", "HEAD") == before


# --- git_ro.py ------------------------------------------------------------------------------

@pytest.fixture
def pinned(repo: Path, tmp_path: Path) -> Path:
    wt = tmp_path / "pinned"
    g(repo, "worktree", "add", "-q", "--detach", str(wt), "feat")
    return wt


def test_git_ro_reads_another_worktree(repo: Path, pinned: Path) -> None:
    p = run("git_ro.py", repo, str(pinned), "rev-parse", "HEAD")
    assert p.returncode == 0 and p.stdout.strip() == g(repo, "rev-parse", "feat")
    p = run("git_ro.py", repo, str(pinned), "log", "-C", "--oneline", "-1")
    assert p.returncode == 0 and "feat" in p.stdout


@pytest.mark.parametrize("args", [
    ("checkout", "main"), ("config", "user.name", "x"), ("commit", "-m", "x"), ("branch", "-D", "feat"),
    ("stash",), ("reset", "--hard"), ("worktree", "remove", "."),
])
def test_git_ro_refuses_a_subcommand_outside_the_allowlist(repo: Path, pinned: Path, args) -> None:
    head = g(pinned, "rev-parse", "HEAD")
    p = run("git_ro.py", repo, str(pinned), *args)
    assert p.returncode == 2 and p.stdout.startswith("STOP:"), p.stdout
    assert g(pinned, "rev-parse", "HEAD") == head


@pytest.mark.parametrize("args", [
    ("diff", "--output=OUT"), ("diff", "--output", "OUT"), ("log", "-p", "--ext-diff"),
    ("show", "--textconv", "HEAD"), ("cat-file", "--filters", "HEAD:f.txt"), ("grep", "-O", "feat"),
    ("grep", "-Otrue", "feat"), ("grep", "--open-files-in-pager=true", "feat"),
    ("log", "--git-dir=/x"), ("status", "--work-tree=/x"),
    ("grep", "--open-files-in-pag=true", "feat"), ("grep", "--open=true", "feat"),
    ("diff", "--outp=OUT"), ("cat-file", "--filt", "HEAD:f.txt"), ("show", "--textc", "HEAD"),
    # A short option inside a cluster (Phase 421's round, lens A: `-nO<program>` ran it).
    ("grep", "-nOtrue", "feat"), ("grep", "-hniOtrue", "feat"),
    # Reads of a file outside the repository (lens A).
    ("diff", "--no-index", "/etc/hosts", "/dev/null"), ("blame", "--contents", "/etc/hosts", "f.txt"),
    ("blame", "-S", "/etc/hosts", "f.txt"), ("grep", "-f", "/etc/hosts"), ("grep", "-nf/etc/hosts"),
    ("ls-files", "--exclude-from=/etc/hosts"), ("status", "--pathspec-from-file=/etc/hosts"),
    ("describe", "--dirty", "--always"),
    # `status -v` runs a textconv filter and takes no `--no-textconv` (`Q-726`).
    ("status", "-v"), ("status", "-sv"), ("status", "--verbose"), ("status", "--verb"),
    # A submodule's diff and a submodule read its own config, which no override reaches.
    ("diff", "--submodule=diff"), ("log", "-p", "--submodule"), ("show", "--submod=log"),
    ("status", "--ignore-submodules=none"), ("diff", "--ignore-submodules"),
])
def test_git_ro_refuses_an_argument_that_writes_or_runs(repo: Path, pinned: Path, args) -> None:
    p = run("git_ro.py", repo, str(pinned), *args)
    assert p.returncode == 2 and "refused argument" in p.stdout, p.stdout
    assert not (pinned / "OUT").exists() and not (repo / "OUT").exists()


def test_git_ro_runs_no_program_through_a_short_option_cluster(repo: Path, pinned: Path,
                                                               tmp_path: Path) -> None:
    """git's parse-options splits `-nO<value>` into `-n` and `-O<value>`, and `grep -O` runs
    its value through the shell, so a cluster must be read letter by letter."""
    mark = tmp_path / "ran"
    p = run("git_ro.py", repo, str(pinned), "grep", f"-nOtouch {mark}", "feat")
    assert p.returncode == 2 and "refused argument" in p.stdout and not mark.exists(), p.stdout


def test_git_ro_runs_no_program_through_an_abbreviated_option(repo: Path, pinned: Path,
                                                              tmp_path: Path) -> None:
    """git's option parser takes a unique prefix, so `--open-files-in-pag=<program>` ran the
    program as `grep`'s pager. Called straight, past the wrapper's own refusal, git must refuse
    it too: the wrapper tells it to, for a git that honours the switch."""
    mark = tmp_path / "ran"
    env = dict(GIT_ENV, GIT_TEST_DISALLOW_ABBREVIATED_OPTIONS="true")
    p = subprocess.run(["git", "--no-pager", "grep", f"--open-files-in-pag=touch {mark}", "feat"],
                       cwd=pinned, env=env, capture_output=True, text=True, timeout=60,
                       stdin=subprocess.DEVNULL)
    assert p.returncode != 0 and not mark.exists(), p.stderr
    assert "GIT_TEST_DISALLOW_ABBREVIATED_OPTIONS='true'" in (SCRIPTS / "git_ro.py").read_text()


@pytest.mark.parametrize("args", [("diff", "--text", "HEAD"), ("rev-list", "--filter=blob:none",
                                                               "--objects", "HEAD"),
                                  ("log", "-Sfeat", "--oneline"), ("grep", "-n", "-e", "feat")])
def test_git_ro_allows_a_whole_option_that_prefixes_a_refused_one(repo: Path, pinned: Path,
                                                                  args) -> None:
    p = run("git_ro.py", repo, str(pinned), *args)
    assert p.returncode == 0, p.stdout + p.stderr


def test_git_ro_refuses_a_path_that_is_not_a_worktree(repo: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    g(other, "init", "-q")
    for path in (str(other), str(tmp_path), "<pinned>", ""):
        p = run("git_ro.py", repo, path, "status")
        assert p.returncode == 2 and p.stdout.startswith("STOP:"), (path, p.stdout)


def test_git_ro_exits_with_gits_own_code(repo: Path, pinned: Path) -> None:
    """A failed read must not read as a successful one (lens B): Step 2a's commit list and a
    reviewer's `show` act on the exit."""
    assert run("git_ro.py", repo, str(pinned), "rev-parse", "--verify", "-q", "refs/heads/nope").returncode == 1
    assert run("git_ro.py", repo, str(pinned), "show", "nope:f.txt").returncode == 128


def test_git_ro_runs_no_external_diff_from_the_environment(repo: Path, pinned: Path,
                                                           tmp_path: Path) -> None:
    hit = tmp_path / "ran.txt"
    prog = tmp_path / "ext.sh"
    prog.write_text(f"#!/bin/sh\necho ran > '{hit}'\n")
    prog.chmod(0o755)
    (pinned / "f.txt").write_text("changed\n")
    p = run("git_ro.py", repo, str(pinned), "diff", env={"GIT_EXTERNAL_DIFF": str(prog)})
    assert p.returncode == 0 and "+changed" in p.stdout and not hit.exists(), p.stdout


def test_git_ro_diff_writes_no_index(repo: Path, pinned: Path) -> None:
    """Porcelain `diff` refreshes the index whatever `GIT_OPTIONAL_LOCKS` says (measured, lens
    B), so it reads a copy. Only a stat change git can settle is refreshed: the file keeps its
    content and gains a new mtime (a content change leaves the entry stale, and nothing written)."""
    f = pinned / "f.txt"
    os.utime(f, ns=(f.stat().st_atime_ns, f.stat().st_mtime_ns + 5_000_000_000))
    index = Path(g(pinned, "rev-parse", "--absolute-git-dir")) / "index"
    before = index.stat().st_mtime_ns
    p = run("git_ro.py", repo, str(pinned), "diff")
    assert (p.returncode, p.stdout) == (0, ""), p.stdout
    assert index.stat().st_mtime_ns == before
    (f).write_text("touched\n")
    assert "+touched" in run("git_ro.py", repo, str(pinned), "diff").stdout


def test_git_ro_status_takes_no_index_lock(repo: Path, pinned: Path) -> None:
    (pinned / "f.txt").write_text("touched\n")
    index = Path(g(pinned, "rev-parse", "--absolute-git-dir")) / "index"
    before = index.stat().st_mtime_ns
    assert run("git_ro.py", repo, str(pinned), "status", "--porcelain").returncode == 0
    assert index.stat().st_mtime_ns == before


def test_git_ro_diff_sees_a_same_second_edit(repo: Path, pinned: Path) -> None:
    """The private index keeps the real one's mtime (`Q-726` leg 2): git rehashes an entry whose
    mtime is not older than the index's, and a copy dated now trusted a same-size edit's stat.
    The entry is refreshed from an old mtime first, since a checkout in the index's own second
    leaves it smudged (size 0, always rehashed); the edit then gets that mtime back, the index
    is dated to it, and ctime is not trusted, so no clock races."""
    g(repo, "config", "core.trustctime", "false")
    f = pinned / "f.txt"
    old = f.stat().st_mtime_ns - 10_000_000_000
    os.utime(f, ns=(old, old))
    g(pinned, "update-index", "--refresh")
    f.write_text("FEAT\n")  # the size of "feat\n"
    os.utime(f, ns=(old, old))
    index = Path(g(pinned, "rev-parse", "--absolute-git-dir")) / "index"
    os.utime(index, ns=(old, old))
    p = run("git_ro.py", repo, str(pinned), "diff")
    assert p.returncode == 0 and "+FEAT" in p.stdout, p.stdout + p.stderr


#: git picks the verifying program by the signature's armor, not by `gpg.format`.
SIGNATURES = {"SIGNED": "-----BEGIN PGP SIGNATURE-----", "SSHSIGNED": "-----BEGIN SSH SIGNATURE-----",
              "X509SIGNED": "-----BEGIN SIGNED MESSAGE-----"}


@pytest.mark.parametrize("config,args", [
    ({"core.fsmonitor": "PROG"}, ("status",)), ({"core.fsmonitor": "PROG"}, ("diff",)),
    ({"core.fsmonitor": "PROG"}, ("diff-tree", "-p", "main", "HEAD")),
    ({"core.fsmonitor": "PROG"}, ("blame", "f.txt")), ({"core.fsmonitor": "PROG"}, ("grep", "FEAT")),
    ({"core.fsmonitor": "PROG"}, ("ls-files", "-m")),
    # A driver name holding `=` and `.`, which a `-c name=value` override could not carry.
    ({"filter.c=f.x.clean": "PROG"}, ("status",)), ({"filter.c=f.x.clean": "PROG"}, ("diff",)),
    ({"filter.c=f.x.clean": "PROG"}, ("ls-files", "-m")),
    ({"filter.c=f.x.process": "PROG"}, ("diff",)),
    ({"diff.external": "PROG"}, ("diff",)), ({"diff.d.command": "PROG"}, ("diff",)),
    ({"diff.d.textconv": "PROG"}, ("diff",)),
    ({"diff.d.textconv": "PROG"}, ("log", "-p", "-1")), ({"diff.d.textconv": "PROG"}, ("blame", "f.txt")),
    ({"diff.d.textconv": "PROG"}, ("show", "HEAD")),
    ({"diff.d.textconv": "PROG", "diff.d.cachetextconv": "true"}, ("log", "-p", "-1")),
    ({"gpg.program": "PROG", "log.showSignature": "true"}, ("log", "-1", "SIGNED")),
    ({"gpg.program": "PROG"}, ("log", "-1", "--show-signature", "SIGNED")),
    ({"gpg.program": "PROG"}, ("log", "-1", "--format=%G?", "SIGNED")),
    # ssh verification refuses to start without an allowed-signers file (measured).
    ({"gpg.ssh.allowedSignersFile": "PROG", "gpg.ssh.program": "PROG"},
     ("log", "-1", "--show-signature", "SSHSIGNED")),
    ({"gpg.x509.program": "PROG"}, ("log", "-1", "--show-signature", "X509SIGNED")),
])
def test_git_ro_runs_no_program_config_names(repo: Path, pinned: Path, tmp_path: Path, config,
                                             args) -> None:
    """`Q-726`: a read runs a program named in config with no argument asking for it. Each case
    ran its program through the wrapper before the fix (measured on git 2.50.1)."""
    mark = tmp_path / "ran"
    prog = tmp_path / "prog"
    prog.write_text(f"#!/bin/sh\necho \"$0 $*\" >> '{mark}'\ncat \"$1\" 2>/dev/null\nexit 1\n")
    prog.chmod(0o755)
    (pinned / ".gitattributes").write_text("f.txt diff=d filter=c=f.x\n")
    # The size of "feat\n": a clean filter runs only when the size cannot settle the compare.
    (pinned / "f.txt").write_text("FEAT\n")
    for k, v in config.items():
        g(repo, "config", k, str(prog) if v == "PROG" else v)
    commits = {}
    for word, armor in SIGNATURES.items():
        end = armor.replace("BEGIN", "END")
        sig = f"gpgsig {armor}\n AAAA\n {end}\n"
        body = g(repo, "cat-file", "commit", "feat").replace("\n\n", "\n" + sig + "\n", 1)
        commits[word] = subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin"],
                                       cwd=repo, env=GIT_ENV, input=body + "\n", capture_output=True,
                                       text=True, check=True).stdout.strip()
    p = run("git_ro.py", repo, str(pinned), *[commits.get(a, a) for a in args])
    assert p.returncode == 0 and not mark.exists(), (p.stdout, p.stderr,
                                                     mark.exists() and mark.read_text())
    assert g(repo, "for-each-ref", "refs/notes") == ""


def test_git_ro_runs_no_filter_from_global_config(repo: Path, pinned: Path, tmp_path: Path) -> None:
    """The realistic filter is LFS, configured globally: the drivers are read with the
    worktree's whole config, not its repository file alone."""
    mark = tmp_path / "ran"
    prog = tmp_path / "prog"
    prog.write_text(f"#!/bin/sh\necho ran >> '{mark}'\ncat\n")
    prog.chmod(0o755)
    glob = tmp_path / "global"
    glob.write_text(f"[filter \"lfs\"]\n\tclean = {prog}\n\tprocess = {prog}\n\trequired = true\n")
    (pinned / ".gitattributes").write_text("f.txt filter=lfs\n")
    (pinned / "f.txt").write_text("FEAT\n")
    for args in (("status", "--porcelain"), ("diff",), ("ls-files", "-m")):
        p = run("git_ro.py", repo, str(pinned), *args, env={"GIT_CONFIG_GLOBAL": str(glob)})
        assert p.returncode == 0 and not mark.exists(), (args, p.stdout, p.stderr)


def test_git_ro_reads_filters_from_the_config_git_reads(repo: Path, pinned: Path,
                                                        tmp_path: Path) -> None:
    """`GIT_CONFIG` narrows `git config` to one file but not the read itself, so a caller's
    `GIT_CONFIG` hid the repository's drivers from the enumeration: it is stripped."""
    mark = tmp_path / "ran"
    prog = tmp_path / "prog"
    prog.write_text(f"#!/bin/sh\necho ran >> '{mark}'\ncat\n")
    prog.chmod(0o755)
    g(repo, "config", "filter.cf.clean", str(prog))
    (pinned / ".gitattributes").write_text("f.txt filter=cf\n")
    (pinned / "f.txt").write_text("FEAT\n")
    empty = tmp_path / "empty.cfg"
    empty.write_text("")
    p = run("git_ro.py", repo, str(pinned), "status", env={"GIT_CONFIG": str(empty)})
    assert p.returncode == 0 and not mark.exists(), p.stdout + p.stderr


def test_git_ro_runs_no_program_a_submodules_config_names(tmp_path: Path) -> None:
    """A submodule's own config (`.git/modules/<name>/config`) is not read for its filter
    drivers, and `status` and `diff` ran its clean filter by running `status` inside it; a
    superproject's `diff.submodule=diff` ran its textconv under `log -p` (Phase 451's round)."""
    mark = tmp_path / "ran"
    prog = tmp_path / "prog"
    prog.write_text(f"#!/bin/sh\necho \"$0 $*\" >> '{mark}'\ncat\n")
    prog.chmod(0o755)
    inner, sup = tmp_path / "inner", tmp_path / "super"
    for d in (inner, sup):
        d.mkdir()
        g(d, "init", "-q", "-b", "main")
    (inner / ".gitattributes").write_text("f.txt filter=evil diff=evil\n")
    (inner / "f.txt").write_text("aaaa\n")
    g(inner, "add", "-A")
    g(inner, *ID, "commit", "-q", "-m", "i")
    g(sup, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(inner), "inner")
    g(sup, *ID, "commit", "-q", "-m", "s")
    (sup / "inner" / "f.txt").write_text("bbbb\n")
    g(sup / "inner", *ID, "commit", "-q", "-am", "moved")
    (sup / "inner" / "f.txt").write_text("cccc\n")
    for k in ("filter.evil.clean", "diff.evil.textconv", "diff.evil.command", "diff.external"):
        g(sup / "inner", "config", k, str(prog))
    g(sup, "config", "diff.submodule", "diff")
    for args in (("status",), ("status", "--porcelain"), ("diff",), ("diff", "HEAD"),
                 ("log", "-p", "-1"), ("show",)):
        p = run("git_ro.py", sup, str(sup), *args)
        assert p.returncode == 0 and not mark.exists(), (args, p.stdout, p.stderr,
                                                         mark.exists() and mark.read_text())
    # The submodule's new commit still shows: only its uncommitted changes are left unread.
    assert "inner" in run("git_ro.py", sup, str(sup), "status", "--porcelain").stdout


def test_git_ro_starts_no_lazy_fetch(tmp_path: Path) -> None:
    """In a partial clone a missing object was fetched on demand, running the remote's transport
    (`core.sshCommand` here, at an unroutable `.invalid` host) and writing what it fetched."""
    origin = tmp_path / "origin"
    origin.mkdir()
    g(origin, "init", "-q", "-b", "main")
    g(origin, "config", "uploadpack.allowfilter", "true")
    (origin / "b.txt").write_text("one\n")
    g(origin, "add", "-A")
    g(origin, *ID, "commit", "-q", "-m", "one")
    g(tmp_path, "clone", "-q", "--filter=blob:none", "--no-checkout", f"file://{origin}", "pc")
    pc = tmp_path / "pc"
    mark = tmp_path / "ran"
    ssh = tmp_path / "ssh"
    ssh.write_text(f"#!/bin/sh\necho ran >> '{mark}'\nexit 1\n")
    ssh.chmod(0o755)
    g(pc, "config", "remote.origin.url", "ssh://sysop-fixture.invalid/x")
    g(pc, "config", "core.sshCommand", str(ssh))
    p = run("git_ro.py", pc, str(pc), "cat-file", "-p", "HEAD:b.txt")
    assert p.returncode != 0 and not mark.exists(), (p.stdout, p.stderr)


def test_git_ro_diff_still_shows_the_change_with_helpers_off(repo: Path, pinned: Path,
                                                             tmp_path: Path) -> None:
    """Turning the helpers off must not empty the read: the diff is git's own."""
    prog = tmp_path / "prog"
    prog.write_text("#!/bin/sh\nexit 0\n")
    prog.chmod(0o755)
    g(repo, "config", "diff.external", str(prog))
    (pinned / "f.txt").write_text("changed\n")
    p = run("git_ro.py", repo, str(pinned), "diff")
    assert p.returncode == 0 and "+changed" in p.stdout, p.stdout + p.stderr


# --- review_pins.py -------------------------------------------------------------------------

CLEAN = ["no agent worktrees", "no agent branches", "primary tree unchanged by 2b",
         "local config unchanged by 2b", "no pinned checkouts"]


def test_review_pins_round_trip_is_clean(repo: Path) -> None:
    assert run("review_pins.py", repo, "baseline").returncode == 0
    p = run("review_pins.py", repo, "add", "refs/heads/feat")
    assert p.returncode == 0, p.stdout
    fields = dict(kv.split("=", 1) for kv in p.stdout.split())
    assert fields["PIN"] == g(repo, "rev-parse", "feat")
    pin = Path(fields["PINNED"])
    assert g(pin, "rev-parse", "HEAD") == fields["PIN"], "the checkout is not at the revision asked for"
    assert pin.is_absolute() and pin.is_relative_to((repo / "sysop/runtime/pins").resolve())
    assert Path(fields["SCRATCH"]).is_dir()
    assert g(repo, "status", "--porcelain", "-uall") == ""
    p = run("review_pins.py", repo, "check")
    assert p.returncode == 1 and str(pin) in p.stdout
    assert run("review_pins.py", repo, "clean").returncode == 0
    assert not pin.exists() and not Path(fields["SCRATCH"]).exists()
    p = run("review_pins.py", repo, "check")
    assert (p.returncode, p.stdout.splitlines()) == (0, CLEAN)


def test_review_pins_check_reports_each_breach(repo: Path) -> None:
    run("review_pins.py", repo, "baseline")
    (repo / "stray.txt").write_text("x\n")
    g(repo, "config", "--local", "core.hooksPath", "/abs/hooks")
    g(repo, "branch", "worktree-agent-abc")
    p = run("review_pins.py", repo, "check")
    assert p.returncode == 1
    assert "+?? stray.txt" in p.stdout and "+core.hookspath=/abs/hooks" in p.stdout
    assert "worktree-agent-abc" in p.stdout
    assert "primary tree unchanged by 2b" not in p.stdout


def test_review_pins_check_reports_an_agent_worktree(repo: Path) -> None:
    run("review_pins.py", repo, "baseline")
    agent = repo / ".claude" / "worktrees" / "agent-x"
    g(repo, "worktree", "add", "-q", "--detach", str(agent), "HEAD")
    p = run("review_pins.py", repo, "check")
    assert p.returncode == 1 and ".claude/worktrees/agent-x" in p.stdout, p.stdout
    assert "no agent worktrees" not in p.stdout


def test_review_pins_check_does_not_count_its_own_files(repo: Path) -> None:
    """With only `pins/` and `scratch/` ignored (enough to pass `add`), the baselines and the
    conventions copy are written after the read, and showed as an agent's (lens B)."""
    (repo / ".gitignore").write_text("sysop/runtime/pins/\nsysop/runtime/scratch/\n")
    g(repo, "add", ".gitignore")
    g(repo, *ID, "commit", "-q", "-m", "narrow ignore")
    assert run("review_pins.py", repo, "baseline").returncode == 0
    (repo / "sysop/runtime/2b-conventions.md").write_text("conventions\n")
    p = run("review_pins.py", repo, "check")
    assert (p.returncode, p.stdout.splitlines()) == (0, CLEAN), p.stdout


def test_review_pins_clear_conventions_removes_the_file(repo: Path) -> None:
    conv = repo / "sysop/runtime/2b-conventions.md"
    conv.parent.mkdir(parents=True)
    conv.write_text("a previous close's\n")
    p = run("review_pins.py", repo, "clear-conventions")
    assert (p.returncode, p.stdout.startswith("CLEARED:"), conv.exists()) == (0, True, False), p.stdout
    assert run("review_pins.py", repo, "clear-conventions").stdout.startswith("ABSENT:")


def test_review_pins_leaves_a_hooks_path_the_baseline_never_had(repo: Path) -> None:
    run("review_pins.py", repo, "baseline")
    g(repo, "config", "--local", "core.hooksPath", "/abs/hooks")
    p = run("review_pins.py", repo, "restore-hooks-path")
    assert p.returncode == 1 and "did not record" in p.stdout, p.stdout
    assert g(repo, "config", "--local", "core.hooksPath") == "/abs/hooks"


def test_review_pins_check_without_a_baseline_is_not_clean(repo: Path) -> None:
    p = run("review_pins.py", repo, "check")
    assert p.returncode == 1 and "MISSING BASELINE" in p.stdout


def test_review_pins_clean_keeps_a_dirty_pin(repo: Path) -> None:
    run("review_pins.py", repo, "baseline")
    pin = Path(dict(kv.split("=", 1) for kv in run("review_pins.py", repo, "add", "HEAD").stdout.split())["PINNED"])
    (pin / "written.txt").write_text("a lens wrote here\n")
    p = run("review_pins.py", repo, "clean")
    assert p.returncode == 1 and f"DIRTY: {pin}" in p.stdout and (pin / "written.txt").exists()


def test_review_pins_check_sees_a_commit_on_a_clean_primary(repo: Path) -> None:
    """Phase 421's round, lens A: a reviewer's commit on the primary's branch changes no status
    line, so all five clean lines printed over it (the Phase 153 class)."""
    run("review_pins.py", repo, "baseline")
    g(repo, *ID, "commit", "-q", "--allow-empty", "-m", "a reviewer wrote onto main")
    p = run("review_pins.py", repo, "check")
    assert p.returncode == 1 and "primary tree unchanged by 2b" not in p.stdout, p.stdout
    assert "refs/heads/main" in p.stdout, p.stdout


def test_review_pins_check_sees_a_branch_moved_off_head(repo: Path) -> None:
    """A reviewer's `branch -f` or commit on a branch the primary does not hold changes neither
    the status nor `HEAD`."""
    run("review_pins.py", repo, "baseline")
    g(repo, "branch", "-f", "feat", "main")
    p = run("review_pins.py", repo, "check")
    assert p.returncode == 1 and "refs/heads/feat" in p.stdout, p.stdout


def test_review_pins_clean_keeps_a_pin_whose_head_moved(repo: Path) -> None:
    """A lens that checks out another commit in its pin leaves a clean tree, which `worktree
    remove` takes, with any commit made there."""
    run("review_pins.py", repo, "baseline")
    pin = Path(dict(kv.split("=", 1) for kv in run("review_pins.py", repo, "add", "refs/heads/feat").stdout.split())["PINNED"])
    g(pin, "checkout", "-q", "--detach", "main")
    p = run("review_pins.py", repo, "clean")
    assert p.returncode == 1 and f"MOVED: {pin}" in p.stdout and pin.exists(), p.stdout


def test_review_pins_refuses_a_linked_worktrees_top_level(repo: Path, tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    g(repo, "worktree", "add", "-q", "--detach", str(wt), "feat")
    p = run("review_pins.py", wt, "baseline")
    assert p.returncode == 2 and "main checkout" in p.stdout, p.stdout


def test_review_pins_refuses_an_unignored_pin(repo: Path) -> None:
    (repo / ".gitignore").write_text("")
    p = run("review_pins.py", repo, "add", "HEAD")
    assert p.returncode == 2 and "is not ignored by git" in p.stdout
    assert not (repo / "sysop/runtime/pins").exists()
    assert g(repo, "worktree", "list", "--porcelain").count("worktree ") == 1


@pytest.mark.parametrize("args", [("add", "refs/heads/nope"), ("add", "<target branch>"), ("add",),
                                  ("baseline", "x"), ("nope",)])
def test_review_pins_refuses_bad_operands(repo: Path, args) -> None:
    p = run("review_pins.py", repo, *args)
    assert p.returncode == 2 and p.stdout.startswith("STOP:"), p.stdout


def test_review_pins_runs_only_from_the_top_level(repo: Path) -> None:
    (repo / "sub").mkdir()
    assert run("review_pins.py", repo / "sub", "baseline").returncode == 2


# --- the skills' calls ----------------------------------------------------------------------

SKILLS = REPO / "core" / "skills"
#: Rule A's chained sites (`Q-710`): a check whose job is to stop the write beside it.
GUARDING = re.compile(r"^\s*python3 sysop/scripts/git_check\.py (head-is|head-is-not|head-matches|ancestor|file)\b")
#: Each site's whole line: a count and the operators let `head-is-not` turn into `head-is`, a
#: dropped `ancestor` and a widened pattern through (Phase 421's round, lens B).
CHAINED_SITES = {
    "_shared/main-push-guard.md": [
        'python3 sysop/scripts/git_check.py head-is "<expected branch>" && <the write it guards>',
        'python3 sysop/scripts/git_check.py head-is-not "<default branch>" && git push -u origin HEAD',
        'python3 sysop/scripts/git_check.py head-matches "merge/review-close-*" && <the write it guards>',
        # Rule B (Phase 422, `Q-665`): each write of the sequence after its own check.
        'python3 sysop/scripts/git_check.py head-is "<default branch>" && git fetch origin <default branch>',
        'python3 sysop/scripts/git_check.py head-is "<default branch>" && git merge --no-edit -m '
        '"merge origin/<default branch> (autonomous advance)" -m "<trailers the project\'s commit '
        'convention requires, one per line>" refs/remotes/origin/<default branch>',  # Phase 446: the ref the check reads
        'python3 sysop/scripts/git_check.py head-is "<default branch>" && git push origin "<SHA>:<default branch>"',
    ],
    "auto-build/SKILL.md": [
        'python3 sysop/scripts/git_check.py file "<WORKTREE_PATH>/<BODY_PATH_AS_RESOLVED>" && grep -niE -A1 '
        "'^#+[[:space:]]*test[[:space:]]+decision\\b' \"<WORKTREE_PATH>/<BODY_PATH_AS_RESOLVED>\"",
    ],
    "claim-task/SKILL.md": [
        'python3 sysop/scripts/git_check.py head-is "<default branch>" && git add tasks/index.yml && git commit -m "chore: release <CLAIM_ID>"',
        'python3 sysop/scripts/git_check.py head-is "<default branch>" && git add "<BODY_PATH_AS_RESOLVED>" && git commit -m "plan: record reviewed plan for <CLAIM_ID>"',
        'python3 sysop/scripts/git_check.py head-is "<default branch>" && git add tasks/index.yml && git commit -m "chore: release <CLAIM_ID>"',
    ],
    "document-work/SKILL.md": [
        'python3 sysop/scripts/git_check.py head-is-not "<default branch>" && git push -u origin HEAD',
    ],
    # Step 4's commits (Phase 422, `Q-665`): the HARD RULE's check is the merge target's.
    "review-close/SKILL.md": [
        'python3 sysop/scripts/git_check.py head-is "<merge target>" && git add -- tasks/index.yml '
        '<each other file those steps wrote> && git commit -m "docs: review-close file close notes '
        '— <N> task(s)"',
        'python3 sysop/scripts/git_check.py head-is "<merge target>" && git commit -m "docs: '
        'consolidate documentation for <N> merged branches"',
    ],
    "review-close/steps/3c-signals.md": [
        'python3 sysop/scripts/git_check.py head-is "<default branch>" && git add -- tasks/index.yml '
        '<each other file those steps wrote> && git commit -m "docs: review-close file unrunnable '
        'smoke — <N> task(s)"',
    ],
    "review-close/steps/4a-fix.md": [
        'python3 sysop/scripts/git_check.py head-is "<merge target>" && git add -- <each file the '
        'fixes edited> && git commit -m "docs: review-close fix at close — <N> note(s)"',
    ],
    "review-close/steps/4b-batches.md": [
        'python3 sysop/scripts/git_check.py head-is "<merge target>" && git add review_tasks.md && '
        'git commit -m "docs: close Batch <N1>, <N2>, <N3>"',
    ],
    "review-close/steps/4d-pr.md": [
        'python3 sysop/scripts/git_check.py head-is "<integration branch>" && git push origin '
        '"refs/heads/<integration branch>"',
        'python3 sysop/scripts/git_check.py head-is "<approved branch name>" && git push origin '
        '"refs/heads/<approved branch name>"',
    ],
    "release/SKILL.md": [
        'python3 sysop/scripts/git_check.py head-is "<default branch>" && python3 sysop/scripts/git_check.py '
        'ancestor HEAD "refs/remotes/origin/<default branch>" && git tag -a "<prefix><new version>" '
        "--cleanup=verbatim -F '<tag message file>'",
    ],
}


#: A check read for its exit code alone, deciding which numbered step runs next; it guards no
#: write beside it, so it stands alone. Whole lines, as above, so one cannot hide a guard.
DECISION_SITES = {
    "_shared/main-push-guard.md": [
        'python3 sysop/scripts/git_check.py ancestor "refs/remotes/origin/<default branch>" '
        '"refs/heads/<default branch>"',
    ],
}


def _operators(line: str) -> list[str]:
    lex = shlex.shlex(line, posix=True, punctuation_chars=";&|")
    lex.whitespace_split = True
    return [tok for tok in lex if tok and set(tok) <= set(";&|")]


def test_every_guarding_check_is_chained_into_its_write_with_and() -> None:
    """A `;` or `||` after the check runs the write whatever the check printed: the warn-and-
    continue arm Rule A exists to remove. Every site is counted, so deleting one is seen too."""
    found: dict[str, list[str]] = {}
    decisions: dict[str, list[str]] = {}
    for md in sorted(SKILLS.rglob("*.md")):
        for n, line in enumerate(md.read_text(encoding="utf-8").splitlines(), 1):
            if not GUARDING.match(line):
                continue
            rel = md.relative_to(SKILLS).as_posix()
            ops = _operators(line)
            if not ops and line.strip() in DECISION_SITES.get(rel, []):
                decisions.setdefault(rel, []).append(line.strip())
                continue
            found.setdefault(rel, []).append(line.strip())
            assert ops and set(ops) == {"&&"}, f"{rel}:{n} joins its check with {ops}: {line.strip()}"
    assert found == CHAINED_SITES, found
    assert decisions == DECISION_SITES, decisions


def _prepare_span() -> str:
    """`/review-close`'s prepare as a runner reads it: the spliced core up to Step 3b, where the
    resume begins (Phase 422's), with the step files the prepare loads spliced in at their stubs."""
    text = text_of(SKILLS / "review-close" / "SKILL.md")
    assert text.count("\n## Step 3b:") == 1, "COULD NOT LOCATE Step 3b; nothing was measured"
    span = text.split("\n## Step 3b:")[0]
    for arm in PREPARE_ARMS:
        assert f'close_arms.py loaded "<close-id>" {arm} ' in span, f"steps/{arm}.md is not in the span"
    return span


PREPARE_ARMS = ("prepare-resume", "2a-ignored-refs", "2b-large-diff", "2b-leak", "2b-no-conventions", "2b-twin-spawn",
                "3c-signals")

#: A command that reaches another worktree's git the way `dontAsk` denies (Phase 421's probes).
DENIED_GIT = re.compile(r"^\s*(?:>\s*)?(?:git -C\b|cd \S+ && git\b|git --git-dir\b)")
#: The same, inside an inline code span, with an operand after it: prose names `git -C` bare.
DENIED_INLINE = re.compile(r"`(?:git -C\s+\S|cd \S+ && git \S|git --git-dir\S*\s)[^`]*`")
#: The prepare's own reads that replaced a denied shape; one dropped or reverted is a denied call.
PREPARE_CALLS = (
    'python3 sysop/scripts/git_ro.py "<absolute path to the pinned checkout>" rev-parse HEAD',
    'python3 sysop/scripts/git_ro.py "<pinned>" show <sha>:<entry>',
    'python3 sysop/scripts/git_check.py lock "<TASK_ID>"',
    'python3 sysop/scripts/git_check.py fork-has "<default branch>" sysop/scripts/git_ro.py',
)


def test_the_prepare_reaches_no_worktree_by_git_dash_c() -> None:
    """`git -C`, `cd <path> && git` and `--git-dir` are denied at every path under `dontAsk`, and
    a placed reviewer's first call is its `rev-parse HEAD`, so one such line is a denied
    reviewer. The read goes through `git_ro.py`; the reviewer prompt's own call is asserted so a
    span that lost it cannot pass by being empty."""
    span = _prepare_span()
    for n, line in enumerate(span.splitlines(), 1):
        assert not DENIED_GIT.match(line), f"spliced review-close:{n}: {line.strip()}"
        assert not DENIED_INLINE.search(line), f"spliced review-close:{n}: {line.strip()}"
    for call in PREPARE_CALLS:
        assert call in span, f"the prepare lost {call!r}"
