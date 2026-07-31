"""Integration tests for core/companion/scripts/cleanup_worktrees.sh (Phase 84).

The script lists git worktrees (MAIN / MERGED / ACTIVE / STALE) and, under
`--clean` / `--force`, removes non-main ones. Its whole reason for existing is
safety, so the load-bearing tests lock the guards: MAIN is *never* removed
(even under `--force`); `--clean` skips ACTIVE (dirty) worktrees and uses a
non-force `git worktree remove` so it can't destroy uncommitted work; branch
deletion is the safe `-d`. Repos are initialised with `main` as the default
branch because the MERGED classification hardcodes `main`.

Phase 165 added the scoping guards at the bottom. The script takes no path
operand — it only ever reads `$1` — and three skill sites nonetheless prescribed
`--force` as the way to drop one orphan worktree. They wrote it **bare**, with the
targeting only in their prose, and the bare form removes every non-main worktree
just the same; `--force <path>` silently means the same thing because `$2` is
ignored. Note what the pre-existing tests above could not catch: both of the two
that exercise `--force` (`TestForceNeverRemovesMain`, Phase 84; and
`TestForcePreservesUnmergedBranch`, added Phase 105) create exactly *one* secondary
worktree, so neither can tell "removes ALL non-main" from "removes the one I
named" — the misreading itself. `TestForceIsWholesale` closes that.
"""
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core/companion/scripts/cleanup_worktrees.sh"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")  # ignore a contributor's global signing
    (root / "README.md").write_text("# seed\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _add_worktree(repo, path, branch):
    _git(repo, "worktree", "add", "-q", "-b", branch, str(path))


def _run(cwd, *args):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True,
    )


class TestGuards:
    def test_not_a_git_repo_exits_1(self, tmp_path):
        r = _run(tmp_path)
        assert r.returncode == 1
        assert "Not inside a git repository" in r.stderr

    def test_unknown_action_exits_1(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "--bogus")
        assert r.returncode == 1
        assert "Unknown action: --bogus" in r.stderr
        assert "Usage: cleanup_worktrees.sh" in r.stderr


class TestList:
    def test_list_main_only(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo)  # default action = list
        assert r.returncode == 0, r.stderr
        assert "MAIN" in r.stdout
        assert "Legend:" in r.stdout


class TestCleanNoOp:
    def test_clean_with_only_main_removes_nothing(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "--clean")
        assert r.returncode == 0, r.stderr
        assert "Removed 0 worktree(s)" in r.stdout


class TestForceNeverRemovesMain:
    """The single most important invariant: MAIN is never removed."""

    def test_force_removes_secondary_but_keeps_main(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-a"
        _add_worktree(repo, wt, "feat/a")
        assert wt.is_dir()
        r = _run(repo, "--force")
        assert r.returncode == 0, r.stderr
        # Full message incl. "0 failed" — so removing the MAIN guard (git then
        # refuses to remove the primary → FAILED=1 → "1 failed", rc 1) reddens
        # this directly, not just incidentally via rc.
        assert "Force-removed 1 worktree(s), 0 failed." in r.stdout
        assert not wt.exists(), "secondary worktree was not removed"
        # The primary worktree survives, intact.
        assert repo.is_dir() and (repo / ".git").exists()
        assert (repo / "README.md").is_file()


class TestCleanSkipsActive:
    def test_clean_skips_active_worktree(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-active"
        _add_worktree(repo, wt, "feat/active")
        (wt / "scratch.txt").write_text("uncommitted work\n")  # untracked → ACTIVE
        r = _run(repo, "--clean")
        assert r.returncode == 0, r.stderr
        assert "Skipping ACTIVE" in r.stdout
        assert "skipped 1 active" in r.stdout
        # The dirty worktree — and its uncommitted file — survive.
        assert wt.is_dir()
        assert (wt / "scratch.txt").is_file()


class TestCleanRemovesMerged:
    def test_clean_removes_merged_and_deletes_branch(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-merged"
        # A clean worktree whose branch tip == main tip → ancestor of main → MERGED.
        _add_worktree(repo, wt, "feat/merged")
        r = _run(repo, "--clean")
        assert r.returncode == 0, r.stderr
        assert "Removing MERGED" in r.stdout
        assert "Removed 1 worktree(s)" in r.stdout
        assert not wt.exists()
        # Branch deleted with safe -d (it was an ancestor of main).
        got = subprocess.run(["git", "show-ref", "--verify", "refs/heads/feat/merged"],
                             cwd=str(repo), capture_output=True)
        assert got.returncode != 0, "merged branch was not deleted"


class TestForcePreservesUnmergedBranch:
    """`--force` removes the worktree but must delete its branch with the *safe*
    `-d` (L216) — so an *unmerged* branch (commits not in main) survives rather
    than being force-dropped. The existing MERGED tests can't catch a `-d`→`-D`
    refactor because for an ancestor branch `-d` and `-D` behave identically;
    only a genuinely-unmerged branch distinguishes them. `--force` (not `--clean`)
    is the reachable path: a clean-but-unmerged worktree classifies ACTIVE and
    `--clean` skips it before the branch-delete, whereas `--force` deletes every
    non-main worktree's branch regardless of class."""

    def test_force_keeps_unmerged_branch(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-unmerged"
        _add_worktree(repo, wt, "feat/unmerged")
        # A commit *inside* the worktree puts its branch tip ahead of main → not
        # an ancestor of main → `git branch -d` refuses (not fully merged).
        (wt / "work.txt").write_text("unmerged commit\n")
        _git(wt, "add", "-A")
        _git(wt, "commit", "-qm", "unmerged work")

        r = _run(repo, "--force")
        assert r.returncode == 0, r.stderr
        assert "Force-removed 1 worktree(s), 0 failed." in r.stdout
        assert not wt.exists(), "worktree was not removed"
        assert "not deleted (not fully merged)" in r.stdout
        # Load-bearing: the unmerged branch — and its commit — survive.
        # `-d`→`-D` at L216 would force-delete it and redden this.
        got = subprocess.run(["git", "show-ref", "--verify", "refs/heads/feat/unmerged"],
                             cwd=str(repo), capture_output=True)
        assert got.returncode == 0, "unmerged branch was force-deleted — commits lost"


class TestNoPathOperand:
    """Phase 165 — the data-loss guard.

    `ACTION="${1:-list}"` reads only `$1`, and every mode acts on the whole
    worktree set. So `--force ../proj-feat-0001` used to destroy *every* non-main
    worktree and exit 0.

    Scoped honestly: the three skill sites that prescribed `--force` as a
    single-orphan rollback wrote it **bare** — no operand — so this guard does not
    block the shape they shipped, and the prose reshape plus the § 8.4 row are what
    closed the defect. This blocks the natural next move of a reader who believes
    such prose: appending the path they mean. The operand is rejected before the
    script prunes or removes anything.
    """

    def test_force_with_path_operand_exits_1_and_destroys_nothing(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        wt_named = tmp_path / "wt-named"
        wt_sibling = tmp_path / "wt-sibling"
        _add_worktree(repo, wt_named, "feat/named")
        _add_worktree(repo, wt_sibling, "feat/sibling")
        # Uncommitted work in the sibling — the concurrent claim that the old
        # behaviour destroyed.
        (wt_sibling / "scratch.txt").write_text("another session's work\n")

        r = _run(repo, "--force", str(wt_named))

        assert r.returncode == 1, f"a path operand must be rejected: {r.stdout}"
        assert "takes no path operand" in r.stderr
        # Name the offending operand, not some other argument: interpolating ${1}
        # instead of ${2} here survived Phase 165's own mutation set.
        assert f"got: {wt_named}" in r.stderr
        # Nothing removed — not even the worktree the caller named.
        assert wt_named.is_dir(), "the named worktree was removed by a rejected call"
        assert wt_sibling.is_dir(), "a sibling worktree was removed by a rejected call"
        assert (wt_sibling / "scratch.txt").is_file(), "uncommitted work was destroyed"
        # The rejection has to route the caller somewhere correct, or it just
        # blocks the job without fixing the belief.
        assert "git worktree remove <path>" in r.stderr
        assert "claim_task.sh --release" in r.stderr

    def test_clean_with_path_operand_is_rejected_too(self, tmp_path):
        """The operand is meaningless in every mode, not just the destructive one."""
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-a"
        _add_worktree(repo, wt, "feat/a")
        r = _run(repo, "--clean", str(wt))
        assert r.returncode == 1
        assert "takes no path operand" in r.stderr
        assert wt.is_dir()

    def test_rejection_happens_before_anything_mutates(self, tmp_path):
        """`git worktree prune` runs at the top of the script, so the rejection has
        to precede it. Moving the guard below the prune left all 13 tests green in
        Phase 165's round — the ordering was asserted in prose and nowhere else.

        A worktree whose directory is deleted stays in git's admin DB until a prune
        reaps it, which makes the prune observable.
        """
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-gone"
        _add_worktree(repo, wt, "feat/gone")
        shutil.rmtree(wt)  # now a prunable STALE entry

        def listed():
            out = subprocess.run(["git", "worktree", "list", "--porcelain"],
                                 cwd=str(repo), capture_output=True, text=True).stdout
            return "wt-gone" in out

        assert listed(), "precondition: the stale entry should still be registered"
        r = _run(repo, "--force", str(wt))
        assert r.returncode == 1
        assert listed(), (
            "a rejected invocation pruned the worktree admin DB — the operand "
            "rejection must come before `git worktree prune`, not after it"
        )

    def test_bare_and_flag_only_invocations_still_work(self, tmp_path):
        """The guard must not cost the legitimate forms — no caller passes an operand.

        Asserts on OUTPUT, not just the return code: a return-code-only version of
        this test passed against a script replaced by a bare `exit 0` stub, which
        is zero signal. Each mode has to prove it still reached its own work.
        """
        repo = _repo(tmp_path / "repo")
        bare = _run(repo)
        assert bare.returncode == 0 and "MAIN" in bare.stdout and "Legend:" in bare.stdout
        clean = _run(repo, "--clean")
        assert clean.returncode == 0 and "Removed 0 worktree(s)" in clean.stdout
        force = _run(repo, "--force")
        assert force.returncode == 0 and "Force-removed 0 worktree(s)" in force.stdout


class TestForceIsWholesale:
    """The scope the § 8.4 row now states, pinned with *two* secondaries.

    Every Phase-84 `--force` test creates one secondary worktree, so none of them
    can tell "removes ALL non-main worktrees" from "removes the one I named" —
    and that ambiguity is exactly what three skill sites read the wrong way. This
    is the positive half of the fix: the documented blast radius is real.
    """

    def test_force_removes_every_non_main_worktree(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        wt_a = tmp_path / "wt-a"
        wt_b = tmp_path / "wt-b"
        _add_worktree(repo, wt_a, "feat/a")
        _add_worktree(repo, wt_b, "feat/b")

        r = _run(repo, "--force")

        assert r.returncode == 0, r.stderr
        assert "Force-removed 2 worktree(s), 0 failed." in r.stdout
        assert not wt_a.exists() and not wt_b.exists(), (
            "--force is documented as wholesale; if it removed only one, the "
            "§ 8.4 row and three skill warnings are now the wrong description"
        )
        assert repo.is_dir() and (repo / "README.md").is_file()


class TestForceNamesTheLossItCauses:
    """`--force` deliberately does NOT inherit `--clean`'s ACTIVE skip — that is
    the flag's whole purpose, and skipping would leave no way to do what it
    advertises. The correct application of the `--clean` precedent is therefore
    loudness, not refusal: a destructive op silent about its blast radius is the
    other half of the Phase 165 defect.

    The warning must be driven by a real `git status --porcelain` check, NOT by the
    ACTIVE class. ACTIVE is `classify_worktree`'s fallthrough, so it also covers a
    pristine worktree on an unmerged branch and a pristine detached HEAD — keying
    on it made the message fire, falsely, on every clean unmerged worktree,
    including the `/auto-build` EXECUTED ones whose work is safely committed. Phase
    165's round found that by executing `--force` over five differently-shaped
    worktrees: two of four warnings were false.
    """

    def test_force_names_the_uncommitted_work_it_destroys(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-dirty"
        _add_worktree(repo, wt, "feat/dirty")
        (wt / "scratch.txt").write_text("uncommitted work\n")  # untracked

        r = _run(repo, "--force")

        assert r.returncode == 0, r.stderr
        assert "UNCOMMITTED WORK" in r.stdout
        assert "it will be LOST" in r.stdout
        # And it still removes it — the loudness is a warning, not a new skip.
        assert not wt.exists()

    def test_force_stays_quiet_on_a_clean_unmerged_worktree(self, tmp_path):
        """The false-positive half. This worktree is ACTIVE (unmerged branch) but
        has nothing uncommitted — its work is on the branch and survives the
        removal, so claiming loss here is simply untrue."""
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-committed"
        _add_worktree(repo, wt, "feat/committed")
        (wt / "work.txt").write_text("committed work\n")
        _git(wt, "add", "-A")
        _git(wt, "commit", "-qm", "committed work")

        r = _run(repo, "--force")

        assert r.returncode == 0, r.stderr
        assert not wt.exists()
        assert "UNCOMMITTED WORK" not in r.stdout, (
            "warned about losing uncommitted work on a clean worktree — the commit "
            "is on feat/committed and survives; keying this on the ACTIVE class "
            "instead of `git status` reintroduces the false alarm"
        )
        # Proof the work really did survive: the unmerged branch is still there.
        got = subprocess.run(["git", "show-ref", "--verify", "refs/heads/feat/committed"],
                             cwd=str(repo), capture_output=True)
        assert got.returncode == 0
