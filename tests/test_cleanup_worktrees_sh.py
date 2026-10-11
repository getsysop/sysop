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
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core/companion/scripts/cleanup_worktrees.sh"


# git's discovery variables outrank `cwd`, and git exports them into every hook —
# so a suite run from a pre-push hook would otherwise aim each fixture command at
# the invoking repository (BeanRider ISSUE-0048; `tests/test_git_env_hermeticity.py`).
_GIT_DISCOVERY_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")


def _env(**extra):
    env = {k: v for k, v in os.environ.items() if k not in _GIT_DISCOVERY_VARS}
    env.update(extra)
    return env


def _grun(argv, **kw):
    """`subprocess.run` for a git command, with the discovery variables stripped."""
    kw.setdefault("env", _env())
    return subprocess.run(argv, **kw)


def _git(cwd, *args):
    _grun(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root):
    root.mkdir(parents=True, exist_ok=True)
    _grun(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
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


def _ignore(repo, *patterns):
    """Commit a .gitignore. `_repo` deliberately ships without one, so every test
    that cares about gitignored content has to state its own ignore rules — which
    is also the honest fixture, since the probe under test reads the worktree's
    *effective* ignore rules and not a hardcoded list."""
    (repo / ".gitignore").write_text("".join(f"{p}\n" for p in patterns))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "ignore rules")


def _park_record(wt):
    """Write what `/auto-build` writes INSIDE a worktree when it parks a task:
    `sysop/runtime/auto-build/` scratch. Gitignored, so `git status --porcelain`
    and `ls-files --others --exclude-standard` are both blind to it."""
    d = wt / "sysop" / "runtime" / "auto-build"
    d.mkdir(parents=True)
    (d / "plan.md").write_text("# the plan\n")
    (d / "review.md").write_text("BLOCKER: the adversarial verdict\n")
    return d


def _pending_doc(wt):
    """A second, independent runtime home written INSIDE a worktree — and the one
    with no mirror at all. `/document-work` Step 3 writes the branch's
    documentation to `sysop/runtime/pending-docs/`, and `/review-close` Step 3b
    does not copy it to main until merge time (`review-close/SKILL.md:587`: "a
    `/claim-task` worktree authors its pending-doc there, and it is not copied to
    main until Step 3b"). Destroying the worktree while the doc is still uncollected
    loses it outright — Phase 65a's project-root archive covers park verdicts, not these.

    **Scoped honestly:** this fixture's branch carries no commit, and a *real*
    pending-doc worktree always does — `/document-work` Step 2 (`SKILL.md:80`)
    commits before Step 3 (`:125`) writes the doc. So the reachable shape is a
    *merged* branch whose doc Step 3b had not yet collected, not an unmerged one
    (which is ACTIVE by fallthrough either way). The fixture exists to pin the
    probe's PATH SCOPE — that it is `sysop/runtime/` and not `sysop/runtime/auto-build/`
    — and a commitless branch is the shape that isolates that. It is not a
    reproduction of the writer's own timeline.
    """
    d = wt / "sysop" / "runtime" / "pending-docs"
    d.mkdir(parents=True)
    (d / "feat-thing.md").write_text("---\nbranch: feat/thing\n---\n# what shipped\n")
    return d


def _run(cwd, *args, env=None):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True, env=env or _env(),
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
        got = _grun(["git", "show-ref", "--verify", "refs/heads/feat/merged"],
                             cwd=str(repo), capture_output=True)
        assert got.returncode != 0, "merged branch was not deleted"


class TestForcePreservesUnmergedBranch:
    """`--force` removes the worktree but must delete its branch with the *safe*
    `-d` (the `--force` loop's `git branch -d`) — so an *unmerged* branch (commits not in main) survives rather
    than being force-dropped. The existing MERGED tests can't catch a `-d`→`-D`
    refactor because for an ancestor branch `-d` and `-D` behave identically;
    only a genuinely-unmerged branch distinguishes them. `--force` (not `--clean`)
    is the reachable path: a clean-but-unmerged worktree classifies ACTIVE and
    `--clean` skips it before the branch-delete, whereas `--force` deletes every
    non-main worktree's branch regardless of class. (`--clean`'s own `-d` IS
    reachable with a branch `-d` refuses — two ways, both in
    `TestCleanBranchDeleteIsTheSafeOne`, Q-311.)"""

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
        # `-d`→`-D` in the `--force` loop would force-delete it and redden this.
        got = _grun(["git", "show-ref", "--verify", "refs/heads/feat/unmerged"],
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
            out = _grun(["git", "worktree", "list", "--porcelain"],
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
        got = _grun(["git", "show-ref", "--verify", "refs/heads/feat/committed"],
                             cwd=str(repo), capture_output=True)
        assert got.returncode == 0


class TestRuntimeArtifactsAreNotSilentlyDestroyed:
    """Q-023 — a worktree holding only gitignored content classified MERGED.

    Both of the script's content probes exclude gitignored files: `--clean`'s
    classifier used `ls-files --others --exclude-standard`, and `--force`'s
    warning uses `status --porcelain`. `/auto-build` parks a task by writing
    `sysop/runtime/auto-build/review.md` INSIDE the worktree (and, before Phase
    344, `plan.md` beside it), and a
    parked task's branch carries no commit of its own — so it is an ancestor of
    main, classifies MERGED, and `--clean` removed it with a non-force
    `git worktree remove` that never got the chance to refuse.

    The fix is scoped to `sysop/runtime/` rather than to ignored content at
    large, and the second test here is the half that pins that scope. Widening it
    would make `--clean` refuse on nearly every real worktree — venvs and build
    output are ignored too — which is the cry-wolf failure Phase 165's round
    already had to reshape the `--force` warning to avoid.
    """

    def test_clean_skips_a_worktree_holding_only_a_park_record(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        _ignore(repo, "sysop/runtime/")
        wt = tmp_path / "wt-parked"
        _add_worktree(repo, wt, "feat/parked")
        rec = _park_record(wt)

        # Precondition, asserted rather than assumed: this worktree is invisible
        # to both pre-fix probes. If either ever starts seeing ignored content,
        # this test would pass for the wrong reason.
        for probe in (["status", "--porcelain"],
                      ["ls-files", "--others", "--exclude-standard"]):
            got = _grun(["git", *probe], cwd=str(wt),
                                 capture_output=True, text=True)
            # The returncode check is load-bearing, not defensive. Both probes exit
            # 128 with EMPTY stdout when git fails (a non-repo cwd, a corrupt
            # worktree), so asserting only on stdout proves "git printed nothing"
            # rather than "git looked and saw nothing" — the precondition would
            # pass precisely when the fixture had stopped working.
            assert got.returncode == 0, (
                f"probe {probe} failed (rc={got.returncode}): {got.stderr!r} — the "
                "precondition cannot distinguish a clean tree from a broken one"
            )
            assert got.stdout == "", (
                f"fixture no longer exercises the defect: {probe} saw {got.stdout!r}"
            )

        r = _run(repo, "--clean")

        assert r.returncode == 0, r.stderr
        assert "Skipping ACTIVE" in r.stdout
        assert "Removed 0 worktree(s)" in r.stdout
        assert wt.is_dir(), "the parked worktree was removed"
        assert (rec / "review.md").read_text() == "BLOCKER: the adversarial verdict\n", (
            "the park record was destroyed — this is the whole of Q-023"
        )

    def test_clean_skips_a_worktree_holding_only_a_pending_doc(self, tmp_path):
        """The scope is `sysop/runtime/`, not `sysop/runtime/auto-build/` — and this
        is the test that makes that a guard rather than a claim.

        Without it, narrowing the probe to the one directory this phase happened to
        read the writer of (`auto-build/`) passes the whole suite: that mutation was
        the sole survivor of the author-side battery's first run. `pending-docs/` is
        the honest second case rather than a synthetic one — it is written inside the
        worktree by `/document-work` Step 3, and unlike a park verdict it has no
        project-root mirror until `/review-close` Step 3b copies it at merge time.
        """
        repo = _repo(tmp_path / "repo")
        _ignore(repo, "sysop/runtime/")
        wt = tmp_path / "wt-documented"
        _add_worktree(repo, wt, "feat/documented")
        doc = _pending_doc(wt)

        r = _run(repo, "--clean")

        assert r.returncode == 0, r.stderr
        assert "Skipping ACTIVE" in r.stdout
        assert wt.is_dir(), "the worktree holding the branch's pending doc was removed"
        assert (doc / "feat-thing.md").is_file(), (
            "the pending doc was destroyed — the probe is scoped to auto-build/ "
            "rather than to sysop/runtime/, so every other runtime home is unguarded"
        )

    def test_ordinary_ignored_noise_does_not_protect_a_merged_worktree(self, tmp_path):
        """The over-strictness control, and the reason the probe names a path.

        A merged worktree whose only ignored content is a venv has nothing worth
        keeping. Broadening the probe to all ignored content — `ls-files
        --others --ignored --exclude-standard` with no pathspec — makes `--clean`
        a no-op on real repositories and reddens exactly this test.
        """
        repo = _repo(tmp_path / "repo")
        _ignore(repo, "sysop/runtime/", ".venv/", "build/")
        wt = tmp_path / "wt-noisy"
        _add_worktree(repo, wt, "feat/noisy")
        (wt / ".venv" / "lib").mkdir(parents=True)
        (wt / ".venv" / "lib" / "junk.py").write_text("cached\n")
        (wt / "build").mkdir()
        (wt / "build" / "out.o").write_text("artifact\n")

        r = _run(repo, "--clean")

        assert r.returncode == 0, r.stderr
        assert "Removing MERGED" in r.stdout
        assert "Removed 1 worktree(s)" in r.stdout
        assert not wt.exists(), (
            "a venv/build-only worktree was kept — the probe is counting all "
            "ignored content instead of sysop/runtime/, so --clean now refuses "
            "on the common case"
        )

    def test_force_names_the_runtime_artifacts_it_destroys(self, tmp_path):
        """`--force` still removes it — the fix there is loudness, not a skip.

        Separate line from the UNCOMMITTED WORK warning on purpose: a worktree
        can hold both, either, or neither, and this fixture holds only the
        gitignored half, so a version that folded the two into one branch would
        report nothing here.
        """
        repo = _repo(tmp_path / "repo")
        _ignore(repo, "sysop/runtime/")
        wt = tmp_path / "wt-parked"
        _add_worktree(repo, wt, "feat/parked")
        _park_record(wt)

        r = _run(repo, "--force")

        assert r.returncode == 0, r.stderr
        # Assert the runtime line specifically. `"will be LOST" in r.stdout` also
        # matches the UNCOMMITTED WORK line, so on any fixture that is not
        # status-clean it would pass from the wrong line entirely.
        runtime_lines = [ln for ln in r.stdout.splitlines()
                         if "sysop/runtime/ artifacts" in ln]
        assert len(runtime_lines) == 1, f"expected exactly one runtime line: {r.stdout}"
        assert "will be LOST" in runtime_lines[0]
        assert "UNCOMMITTED WORK" not in r.stdout, (
            "this fixture is status-clean; an UNCOMMITTED WORK line here means the "
            "two warnings are no longer independent"
        )
        # The mirror is named as a maybe, not a promise: /auto-build writes the
        # project-root copy in Phase 6d, and the Phase 6a plan-violation park
        # writes review.md then skips 6b-6e, so that path leaves no mirror at all.
        assert "may exist" in r.stdout, (
            "the warning promises a surviving mirror; --force cannot tell a "
            "Phase-6d park (mirrored) from a Phase-6a one (not mirrored)"
        )
        assert not wt.exists(), "--force must still remove it — loudness, not a new skip"

    def test_force_names_the_pending_doc_class_separately(self, tmp_path):
        """The class whose recovery pointer was wrong until this phase's round.

        Both `--force` warning tests used `_park_record`, so nothing exercised the
        warning on a pending-doc — and `sysop/runtime/parked/` structurally never
        holds one, that directory being the park archive. The message offered it as
        the recovery location for everything it fired on, sending an operator who had
        just lost a branch's documentation to a directory that could not contain it.
        """
        repo = _repo(tmp_path / "repo")
        _ignore(repo, "sysop/runtime/")
        wt = tmp_path / "wt-doc"
        _add_worktree(repo, wt, "feat/doc")
        _pending_doc(wt)

        r = _run(repo, "--force")

        assert r.returncode == 0, r.stderr
        assert "sysop/runtime/ artifacts" in r.stdout
        assert "will be LOST" in r.stdout
        assert "pending-doc" in r.stdout.lower(), (
            "the warning fires on a pending-doc but names only the park case"
        )
        assert "Step 3b" in r.stdout, (
            "a pending-doc has no mirror until /review-close Step 3b collects it; the "
            "warning must say where it actually goes, not point at sysop/runtime/parked/"
        )
        assert not wt.exists()

    def test_force_stays_quiet_when_there_are_no_runtime_artifacts(self, tmp_path):
        """The false-positive half. A warning that fires on every worktree is one
        operators learn to skip — the same finding Phase 165's round made about
        keying the UNCOMMITTED WORK message on the ACTIVE class."""
        repo = _repo(tmp_path / "repo")
        _ignore(repo, "sysop/runtime/", ".venv/")
        wt = tmp_path / "wt-plain"
        _add_worktree(repo, wt, "feat/plain")
        (wt / ".venv").mkdir()
        (wt / ".venv" / "junk").write_text("ignored noise\n")
        (wt / "tracked.txt").write_text("real work\n")
        _git(wt, "add", "-A")
        _git(wt, "commit", "-qm", "real work")

        r = _run(repo, "--force")

        assert r.returncode == 0, r.stderr
        assert not wt.exists()
        assert "sysop/runtime/ artifacts" not in r.stdout, (
            "warned about runtime artifacts on a worktree that holds none"
        )


class TestForceFailureAccounting:
    """Q-024 — `"Force-removed N worktree(s), 0 failed."` was an unverified claim.

    Nothing in the suite ever made a real `git worktree remove --force` fail, so
    the FAILED branch and the `exit 1` it drives were dead to the tests. A
    reviewer mutated the removal to `... || true` with an unconditional
    `REMOVED=$((REMOVED + 1))` and every test stayed green.

    The fixture is `git worktree lock`, which is git's own supported way to make a
    removal refuse: `--force` alone is documented to fail on a locked worktree
    (`use 'remove -f -f' to override or unlock first`). The two shapes the filing
    proposed were both tried first — pointing the worktree at an unwritable path
    is a no-op under root, which CI often is, and deleting the
    `.git/worktrees/<name>` admin entry drops the worktree out of
    `git worktree list` entirely, so the script's loop never reaches it and the
    FAILED branch still goes unexercised. Locking is the one that is deterministic,
    cross-platform, and actually routes through the code under test.
    """

    @staticmethod
    def _locked_worktree(repo, path, branch):
        _add_worktree(repo, path, branch)
        _git(repo, "worktree", "lock", str(path))
        return path

    def test_force_reports_and_exits_1_when_a_removal_fails(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        wt = self._locked_worktree(repo, tmp_path / "wt-locked", "feat/locked")

        r = _run(repo, "--force")

        assert r.returncode == 1, (
            f"a failed removal must exit 1; got {r.returncode}\n{r.stdout}"
        )
        assert "Failed to remove worktree at" in r.stdout
        assert "Force-removed 0 worktree(s), 1 failed." in r.stdout
        assert wt.is_dir(), "the worktree was removed despite the lock"
        # The `continue` after a failure must skip the branch delete. Branch SURVIVAL
        # is the wrong oracle for that: `git branch -d` refuses a branch checked out
        # in an existing worktree, so the branch survives whether or not the
        # `continue` is there, and deleting the `continue` leaves this green. What
        # the `continue` actually controls is whether that refusal gets REPORTED —
        # as a flatly false line, since the branch is merged and is only "in use".
        assert "not deleted (not fully merged)" not in r.stdout, (
            "the branch-delete ran for a worktree whose removal failed, and printed a "
            "false reason: feat/locked IS fully merged — it survived because its "
            "worktree still exists. The `continue` exists to skip this."
        )
        assert "Deleted branch" not in r.stdout
        got = _grun(["git", "show-ref", "--verify", "refs/heads/feat/locked"],
                             cwd=str(repo), capture_output=True)
        assert got.returncode == 0, "branch deleted for a worktree that was never removed"

    def test_force_counts_successes_and_failures_separately(self, tmp_path):
        """The test that kills the exact mutation Q-024 was filed on.

        One removable worktree and one locked one. `... || true` with an
        unconditional increment reports `2 worktree(s), 0 failed.` and exits 0;
        the honest script reports `1 worktree(s), 1 failed.` and exits 1. A
        single-worktree fixture cannot tell those apart on the REMOVED count —
        it only sees the total — which is why this needs two.
        """
        repo = _repo(tmp_path / "repo")
        ok = tmp_path / "wt-ok"
        _add_worktree(repo, ok, "feat/ok")
        locked = self._locked_worktree(repo, tmp_path / "wt-locked", "feat/locked")

        r = _run(repo, "--force")

        assert r.returncode == 1, r.stdout
        assert "Force-removed 1 worktree(s), 1 failed." in r.stdout
        assert not ok.exists(), "the removable worktree was not removed"
        assert locked.is_dir(), "the locked worktree was removed"

    def test_clean_failure_accounting_is_exercised_too(self, tmp_path):
        """`--clean`'s FAILED branch and `exit 1` had the same hole, in the same
        script, reachable by the same fixture — a locked MERGED worktree. Added
        alongside Q-024 rather than filed: leaving the sibling path unguarded
        would mean a mutation to `--clean`'s accounting still ships green, which
        is the entire complaint Q-024 makes about `--force`.
        """
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-locked"
        _add_worktree(repo, wt, "feat/locked")
        _git(repo, "worktree", "lock", str(wt))  # clean + merged → MERGED → remove attempted

        r = _run(repo, "--clean")

        assert r.returncode == 1, f"a failed --clean removal must exit 1\n{r.stdout}"
        assert "Failed to remove worktree at" in r.stdout
        assert "re-run with --force to override" in r.stdout
        assert "Removed 0 worktree(s), skipped 0 active, 1 failed." in r.stdout
        assert wt.is_dir()
        # The `continue` after the failure must skip the branch delete here too.
        # Without it `git branch -d` runs and prints a flatly false reason — the
        # branch IS fully merged; it survives only because its worktree still
        # exists. The counters are identical either way, so nothing else sees this.
        assert "not deleted (not fully merged" not in r.stdout, (
            "the branch-delete ran for a worktree whose removal failed, and reported "
            "a false reason"
        )
        assert "Deleted merged branch" not in r.stdout


class TestCleanRemovalIsNonForce:
    """The second line of defence, which nothing pinned until Phase 232's round.

    `--clean`'s removal is deliberately non-force (`cleanup_worktrees.sh`'s comment:
    *"Use plain (non-force) remove so untracked work or submodule dirty state that
    slipped past the MERGED classification blocks the destructive op"*). A reviewer
    mutated that one call to `--force` and **every test in the suite stayed green**,
    including this module's docstring claim that the load-bearing tests lock it.

    **Why this is asserted on the invocation rather than on behaviour.** There is no
    single-threaded state where `classify_worktree` returns MERGED *and* a non-force
    `git worktree remove` refuses — four candidate fixtures were built and measured,
    and all four fail to discriminate: `--assume-unchanged`/`--skip-worktree` with a
    modified file (classifier clean, removal succeeds), an *ignored* nested git repo
    (classifier clean, removal succeeds), and a registered submodule with uncommitted
    changes (classifier already says ACTIVE, and removal then refuses for an unrelated
    reason — *"working trees containing submodules cannot be moved or removed"* —
    whether or not `--force` is passed). The flag only changes the outcome when content
    appears *between* the classification loop and the removal loop, which is the
    concurrent-session case `WORKFLOW.md` § 4.4 documents as supported and which a
    reviewer reproduced with 60 worktrees and a background writer: plain remove refused
    and reported `1 failed`; the same run with `--force` destroyed the file and exited 0.
    A timing race is not a test this suite should own, so the invariant is pinned at the
    point it is actually decided — the argv the script hands to git.

    The shim passes everything through to the real git, so this exercises the whole
    script rather than a stub.
    """

    @staticmethod
    def _shim(tmp_path):
        d = tmp_path / "shimbin"
        d.mkdir()
        log = tmp_path / "worktree-remove.log"
        real = shutil.which("git")
        (d / "git").write_text(
            "#!/usr/bin/env bash\n"
            f'if [[ "$1" == "worktree" && "$2" == "remove" ]]; then\n'
            f'  printf "%s\\n" "$*" >> {log}\n'
            "fi\n"
            f'exec {real} "$@"\n'
        )
        (d / "git").chmod(0o755)
        return d, log

    def _run_shimmed(self, repo, tmp_path, *args):
        d, log = self._shim(tmp_path)
        env = _env(PATH=f"{d}:{os.environ['PATH']}")
        r = subprocess.run(["bash", str(SCRIPT), *args], cwd=str(repo),
                           capture_output=True, text=True, env=env)
        calls = log.read_text().splitlines() if log.exists() else []
        return r, calls

    def test_clean_never_passes_force_to_worktree_remove(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-merged"
        _add_worktree(repo, wt, "feat/merged")

        r, calls = self._run_shimmed(repo, tmp_path, "--clean")

        assert r.returncode == 0, r.stderr
        assert not wt.exists(), "precondition: --clean should have removed this worktree"
        assert calls, "the shim saw no `git worktree remove` call — it did not take effect"
        for c in calls:
            assert "--force" not in c, (
                f"--clean invoked `git {c}` — the non-force removal is the second line of "
                "defence when the classifier is wrong (content appearing between the "
                "classify and remove loops, WORKFLOW.md § 4.4). Passing --force here makes "
                "that loss silent and exit 0."
            )

    def test_force_mode_does_pass_force(self, tmp_path):
        """The positive half — otherwise the guard above is satisfied by a script that
        never removes anything at all."""
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-dirty"
        _add_worktree(repo, wt, "feat/dirty")
        (wt / "scratch.txt").write_text("uncommitted\n")  # ACTIVE — only --force removes it

        r, calls = self._run_shimmed(repo, tmp_path, "--force")

        assert r.returncode == 0, r.stderr
        assert calls, "the shim saw no `git worktree remove` call"
        assert any("--force" in c for c in calls), (
            f"--force mode never passed --force: {calls}. It would then refuse on exactly "
            "the worktrees the flag exists to remove."
        )
        assert not wt.exists()


class TestClassifierRobustness:
    """Phase 232's round: 29 of 45 behaviour-changing mutations walked the guards.

    The author battery's `pre` column killed **0 of 12**, which is the tell — it was
    written against the new lines only and never asked whether they are safe in the
    code they sit inside. These are the classes that leaked. Each test here was
    written against a mutation an independent lens demonstrated, not invented.
    """

    def test_a_worktree_path_containing_spaces_is_handled(self, tmp_path):
        """No fixture in this module ever used a path with a space, so unquoting
        `$wt_path` in the helper or the classifier arm resurrected Q-023 verbatim:
        the park record classified MERGED and `--clean`'s non-force remove destroyed
        it, with every test green."""
        repo = _repo(tmp_path / "repo")
        _ignore(repo, "sysop/runtime/")
        wt = tmp_path / "my worktree dir"
        _add_worktree(repo, wt, "feat/spaced")
        rec = _park_record(wt)

        r = _run(repo, "--clean")

        assert r.returncode == 0, r.stderr
        assert "Skipping ACTIVE" in r.stdout
        assert (rec / "review.md").is_file(), (
            "park record in a space-containing path was destroyed — the probe's "
            "`git -C` argument or the classifier arm's is unquoted"
        )

    def test_force_warns_about_a_spaced_path_worktree(self, tmp_path):
        """The `--force` probes take `$wt_path` too, and unquoting either one there
        silences the warning while the destruction proceeds."""
        repo = _repo(tmp_path / "repo")
        _ignore(repo, "sysop/runtime/")
        wt = tmp_path / "another spaced wt"
        _add_worktree(repo, wt, "feat/spaced2")
        _park_record(wt)

        r = _run(repo, "--force")

        assert r.returncode == 0, r.stderr
        assert "sysop/runtime/ artifacts" in r.stdout
        assert not wt.exists()

    def test_clean_keeps_a_clean_but_unmerged_worktree(self, tmp_path):
        """The negative half of MERGED had no test at all, from either end: dropping
        the `merge-base --is-ancestor` call, or flipping the fallthrough to MERGED,
        both destroyed a live `/claim-task` worktree whose work was committed but not
        merged — and both left the suite green."""
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-inflight"
        _add_worktree(repo, wt, "feat/inflight")
        (wt / "work.txt").write_text("committed, not merged\n")
        _git(wt, "add", "-A")
        _git(wt, "commit", "-qm", "in-flight work")

        r = _run(repo, "--clean")

        assert r.returncode == 0, r.stderr
        assert "Skipping ACTIVE" in r.stdout
        assert wt.is_dir(), "an unmerged in-flight worktree was reclaimed by --clean"
        assert "Removed 0 worktree(s)" in r.stdout

    def test_a_detached_head_worktree_does_not_inherit_a_neighbours_branch(self, tmp_path):
        """The porcelain parser resets `current_branch` after each record. Without
        that reset a detached-HEAD worktree inherits its predecessor's branch — and
        if the predecessor's branch is merged, the detached worktree classifies
        MERGED and its unreachable commit is destroyed. No fixture created a
        detached worktree, so the reset was untested."""
        repo = _repo(tmp_path / "repo")
        merged = tmp_path / "aaa-merged"
        _add_worktree(repo, merged, "feat/merged")
        detached = tmp_path / "zzz-detached"
        head = _grun(["git", "rev-parse", "HEAD"], cwd=str(repo),
                              capture_output=True, text=True).stdout.strip()
        _git(repo, "worktree", "add", "-q", "--detach", str(detached), head)
        (detached / "work.txt").write_text("detached work\n")
        _git(detached, "add", "-A")
        _git(detached, "commit", "-qm", "detached commit")

        r = _run(repo, "--clean")

        assert r.returncode == 0, r.stderr
        assert detached.is_dir(), (
            "the detached worktree was removed — it inherited the merged branch of "
            "its alphabetical predecessor because current_branch was not reset"
        )

    def test_staged_but_uncommitted_work_classifies_active(self, tmp_path):
        """The dirty check is two calls — `diff --quiet` and `diff --cached --quiet`.
        No fixture ever staged anything, so dropping the second half was invisible:
        a `git add`-ed worktree reclassified MERGED and only the non-force remove's
        refusal stood between it and deletion."""
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-staged"
        _add_worktree(repo, wt, "feat/staged")
        (wt / "staged.txt").write_text("staged, not committed\n")
        _git(wt, "add", "-A")

        r = _run(repo, "--clean")

        assert "Skipping ACTIVE" in r.stdout, (
            "staged-but-uncommitted work did not classify ACTIVE — the "
            "`diff --cached` half of the dirty check is not being consulted"
        )
        assert wt.is_dir() and (wt / "staged.txt").is_file()

    def test_main_is_classified_main_even_when_the_repo_root_holds_runtime_artifacts(
            self, tmp_path):
        """A real Sysop consumer ALWAYS has `sysop/runtime/` at the repo root — that
        is where the locks and the park archive live. Two mutations exploit that:
        hoisting the runtime arm above the MAIN check makes the primary checkout
        classify ACTIVE, and probing the repo root instead of the worktree makes
        `--clean` a permanent no-op on every real install. Only git's own refusal
        backstopped the first, and nothing caught the second."""
        repo = _repo(tmp_path / "repo")
        _ignore(repo, "sysop/runtime/")
        (repo / "sysop" / "runtime" / "locks").mkdir(parents=True)
        (repo / "sysop" / "runtime" / "locks" / "TASK-1.lock").write_text("held\n")
        wt = tmp_path / "wt-merged"
        _add_worktree(repo, wt, "feat/merged")

        # The primary must still be MAIN, not ACTIVE: hoisting the runtime arm above
        # the MAIN check inverts this, and only git's own "is a main working tree"
        # refusal stands between that and `--force` attacking the primary checkout.
        listing = _run(repo)
        main_rows = [ln for ln in listing.stdout.splitlines() if str(repo)[-20:] in ln]
        assert main_rows, f"could not find the primary's row: {listing.stdout}"
        assert "MAIN" in main_rows[0], (
            f"the primary checkout did not classify MAIN: {main_rows[0]!r} — the "
            "runtime-artifact arm is running before the MAIN check"
        )

        r = _run(repo, "--clean")

        assert r.returncode == 0, r.stderr
        assert not wt.exists(), (
            "--clean removed nothing on a repo whose ROOT holds sysop/runtime/ — the "
            "probe is reading the repo root instead of the worktree, which makes this "
            "a no-op on every real Sysop consumer"
        )
        assert repo.is_dir() and (repo / "README.md").is_file()


class TestAccountingBeyondZeroAndOne:
    """Every counter in this script was only ever observed at 0 or 1.

    `--clean` had no multi-worktree fixture at all, and `--force`'s only one pinned
    `REMOVED=2`. So replacing any `X=$((X + 1))` with `X=1` was invisible — for
    REMOVED, SKIPPED and FAILED, in both modes. Q-024 is the entry about accounting
    being unverified; these are the rest of it.
    """

    @staticmethod
    def _locked(repo, path, branch):
        _add_worktree(repo, path, branch)
        _git(repo, "worktree", "lock", str(path))
        return path

    def test_force_counts_three_failures_not_one(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        ok = tmp_path / "wt-ok"
        _add_worktree(repo, ok, "feat/ok")
        for i in range(3):
            self._locked(repo, tmp_path / f"wt-locked{i}", f"feat/locked{i}")

        r = _run(repo, "--force")

        assert r.returncode == 1
        assert "Force-removed 1 worktree(s), 3 failed." in r.stdout, (
            f"FAILED is not accumulating: {r.stdout}"
        )

    def test_clean_counts_multiple_removals_and_skips(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        for i in range(2):
            _add_worktree(repo, tmp_path / f"wt-merged{i}", f"feat/merged{i}")
        for i in range(2):
            wt = tmp_path / f"wt-active{i}"
            _add_worktree(repo, wt, f"feat/active{i}")
            (wt / "scratch.txt").write_text("uncommitted\n")
        # TWO locked worktrees, not one. With a single failure `FAILED=1` and
        # `FAILED=$((FAILED + 1))` produce identical output, so a one-failure
        # fixture cannot see the counter being pinned — which is the whole defect
        # class this test exists for, and it had it.
        for i in range(2):
            self._locked(repo, tmp_path / f"wt-locked{i}", f"feat/locked{i}")

        r = _run(repo, "--clean")

        assert r.returncode == 1, r.stdout
        assert "Removed 2 worktree(s), skipped 2 active, 2 failed." in r.stdout, (
            f"a counter is pinned rather than accumulating: {r.stdout}"
        )


class TestForceWarningAttribution:
    """Every `--force` runtime fixture had exactly one secondary worktree, so nothing
    could tell "warns about the worktree it is removing" from "warns about any
    worktree in the set". A mutation probing the whole `WT_PATHS` array instead of
    `$wt_path` fired the warning on a worktree holding nothing, and stayed green.
    """

    def test_the_warning_names_only_the_worktree_that_holds_artifacts(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        _ignore(repo, "sysop/runtime/")
        # The repo ROOT holds sysop/runtime/ — which is true of every real Sysop
        # consumer, since that is where the locks and the park archive live. Without
        # it, a probe that consults $REPO_ROOT instead of (or as well as) $wt_path
        # is invisible: the warning would then fire on every worktree of every real
        # install, which is Phase 165's cry-wolf in the line this phase added.
        (repo / "sysop" / "runtime" / "locks").mkdir(parents=True)
        (repo / "sysop" / "runtime" / "locks" / "TASK-9.lock").write_text("held\n")
        plain = tmp_path / "aaa-plain"
        holder = tmp_path / "zzz-holder"
        _add_worktree(repo, plain, "feat/plain")
        _add_worktree(repo, holder, "feat/holder")
        _park_record(holder)

        r = _run(repo, "--force")

        assert r.returncode == 0, r.stderr
        lines = r.stdout.splitlines()
        # Find which "Removing" block each runtime warning belongs to.
        current, warned_for = None, []
        for ln in lines:
            if "Removing" in ln and "worktree" not in ln.split(":")[0].lower():
                current = ln
            if "Removing" in ln:
                current = ln
            elif "sysop/runtime/ artifacts" in ln:
                warned_for.append(current)
        assert len(warned_for) == 1, f"expected exactly one runtime warning: {r.stdout}"
        assert str(holder) in warned_for[0], (
            f"the runtime warning was attributed to the wrong worktree: {warned_for[0]}"
        )
        assert str(plain) not in warned_for[0]

    def test_a_clean_worktree_still_gets_a_removal_line(self, tmp_path):
        """Deleting the `else` arm made `--force` destroy a clean worktree with no
        line naming it at all. Nothing asserted the benign line exists."""
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-clean"
        _add_worktree(repo, wt, "feat/clean")

        r = _run(repo, "--force")

        assert r.returncode == 0, r.stderr
        assert any("Removing" in ln and str(wt) in ln for ln in r.stdout.splitlines()), (
            f"--force removed a worktree without naming it: {r.stdout}"
        )
        assert not wt.exists()

    def test_ignored_noise_does_not_trigger_the_uncommitted_warning(self, tmp_path):
        """Phase 165's cry-wolf, from the other side. Adding `--ignored` to the
        `status --porcelain` probe makes a worktree holding only a venv report
        `UNCOMMITTED WORK — it will be LOST`. The existing false-positive test
        asserts only the *runtime* line's absence, so it could not see this."""
        repo = _repo(tmp_path / "repo")
        _ignore(repo, "sysop/runtime/", ".venv/")
        wt = tmp_path / "wt-venv"
        _add_worktree(repo, wt, "feat/venv")
        (wt / ".venv").mkdir()
        (wt / ".venv" / "junk").write_text("ignored noise\n")

        r = _run(repo, "--force")

        assert r.returncode == 0, r.stderr
        assert "UNCOMMITTED WORK" not in r.stdout, (
            "warned about losing uncommitted work on a worktree whose only content "
            "is an ignored venv — the status probe is counting ignored content"
        )
        assert "sysop/runtime/ artifacts" not in r.stdout


class TestProbeScopeBothEnds:
    """`test_ordinary_ignored_noise_does_not_protect_a_merged_worktree` prices the
    all-ignored widening. Two other scope mutations walked it."""

    def test_an_empty_runtime_directory_does_not_protect_a_worktree(self, tmp_path):
        """Adding `--directory` to the probe makes an EMPTY `sysop/runtime/` tree
        flip MERGED → ACTIVE, so `--clean` refuses on a worktree with nothing in it.
        The probe is an existence test for *content*, not for the directory."""
        repo = _repo(tmp_path / "repo")
        _ignore(repo, "sysop/runtime/")
        wt = tmp_path / "wt-emptyruntime"
        _add_worktree(repo, wt, "feat/emptyruntime")
        (wt / "sysop" / "runtime" / "auto-build").mkdir(parents=True)  # dirs, no files

        r = _run(repo, "--clean")

        assert r.returncode == 0, r.stderr
        assert not wt.exists(), (
            "an empty sysop/runtime/ tree kept the worktree alive — the probe is "
            "matching directories rather than content, so --clean now refuses on "
            "every worktree a run has merely touched"
        )

    def test_a_nested_sysop_runtime_does_not_protect_a_worktree(self, tmp_path):
        """The header says the scope is `sysop/runtime/` and NOTHING wider. That was
        pinned only against the all-ignored widening, not against nesting: making
        the pathspec `*sysop/runtime/*` lets a vendored `vendor/sysop/runtime/`
        protect a merged worktree, which is a different repo's runtime dir."""
        repo = _repo(tmp_path / "repo")
        _ignore(repo, "sysop/runtime/", "vendor/")
        wt = tmp_path / "wt-nested"
        _add_worktree(repo, wt, "feat/nested")
        nested = wt / "vendor" / "othertool" / "sysop" / "runtime"
        nested.mkdir(parents=True)
        (nested / "someones-else-state.md").write_text("not ours\n")

        r = _run(repo, "--clean")

        assert r.returncode == 0, r.stderr
        assert not wt.exists(), (
            "a nested vendor/**/sysop/runtime/ protected the worktree — the pathspec "
            "is no longer anchored at the repo root"
        )


def _ref(repo, branch):
    """The SHA a local branch points at, or None when the branch does not exist."""
    got = _grun(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
                cwd=str(repo), capture_output=True, text=True)
    return got.stdout.strip() if got.returncode == 0 else None


def _listed_paths(repo):
    """Every worktree path git still has registered, read NUL-separated so a path
    holding a newline comes back whole."""
    out = _grun(["git", "worktree", "list", "--porcelain", "-z"], cwd=str(repo),
                capture_output=True, check=True).stdout.decode()
    return [f[len("worktree "):] for f in out.split("\0") if f.startswith("worktree ")]


class TestCleanBranchDeleteIsTheSafeOne:
    """Q-311 (a) — `--clean`'s `git branch -d` is load-bearing, and `-d`→`-D`
    survived every test in this module.

    **Why nothing caught it.** `--clean` reaches the delete only for a MERGED
    worktree, whose branch is by definition an ancestor of the default branch,
    and for such a branch `-d` and `-D` usually agree. They part in two places,
    and each test below takes one:

    * **The commit that arrives after classification** — the data-loss case.
      Every worktree is classified before any is removed, so a session that
      commits on the branch in between (§ 4.4's concurrent sessions) leaves a
      clean worktree whose non-force removal succeeds and a branch that is no
      longer merged. `-d` refuses and the commit survives; `-D` deletes the only
      ref to it. `TestCleanRemovalIsNonForce` documents the same window and pins
      its argv rather than racing it; this test stages the commit
      deterministically instead, from a `git` shim that commits in the worktree
      immediately before passing `worktree remove` through to the real git.
    * **`-d`'s own definition of merged** — merged into HEAD (or the branch's
      upstream), not into the default branch. With the primary checked out on
      another branch, a MERGED worktree's branch is one `-d` refuses. No commit
      is at risk here (it is on `main`); what is pinned is that the script
      keeps git's refusal rather than overriding it.
    """

    @staticmethod
    def _committing_shim(tmp_path):
        d = tmp_path / "shimbin"
        d.mkdir()
        sha_log = tmp_path / "injected.sha"
        real = shutil.which("git")
        (d / "git").write_text(
            "#!/usr/bin/env bash\n"
            '# `--clean` calls `git worktree remove <path>`: path is $3.\n'
            'if [[ "$1" == "worktree" && "$2" == "remove" && "$3" != "--force" ]]; then\n'
            f'  "{real}" -C "$3" commit -q --allow-empty -m "concurrent session" || exit 97\n'
            f'  "{real}" -C "$3" rev-parse HEAD >> "{sha_log}"\n'
            "fi\n"
            f'exec "{real}" "$@"\n'
        )
        (d / "git").chmod(0o755)
        return d, sha_log

    def test_a_commit_landing_after_classification_survives_clean(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        wt = tmp_path / "wt-raced"
        _add_worktree(repo, wt, "feat/raced")  # tip == main tip → MERGED
        d, sha_log = self._committing_shim(tmp_path)

        r = _run(repo, "--clean", env=_env(PATH=f"{d}:{os.environ['PATH']}"))

        assert r.returncode == 0, r.stdout + r.stderr
        assert sha_log.is_file(), "the shim never saw `git worktree remove` — no commit was staged"
        injected = sha_log.read_text().split()
        assert len(injected) == 1, f"expected one staged commit: {injected}"
        assert "Removing MERGED worktree" in r.stdout
        assert not wt.exists(), "precondition: the clean worktree's removal should succeed"
        assert _ref(repo, "feat/raced") == injected[0], (
            "the branch no longer points at the commit made after classification — "
            "`git branch -d` became `-D` and deleted the only ref to it"
        )
        assert "not deleted" in r.stdout, r.stdout

    def test_a_branch_merged_into_main_but_not_into_head_is_kept(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        _git(repo, "branch", "other")  # the seed commit, behind what main will be
        wt = tmp_path / "wt-merged-elsewhere"
        _add_worktree(repo, wt, "feat/landed")
        _git(wt, "commit", "-q", "--allow-empty", "-m", "landed on main")
        _git(repo, "merge", "-q", "--ff-only", "feat/landed")
        _git(repo, "checkout", "-q", "other")  # the primary is not on main

        r = _run(repo, "--clean")

        assert r.returncode == 0, r.stdout + r.stderr
        assert "Removing MERGED worktree" in r.stdout, r.stdout
        assert not wt.exists()
        assert _ref(repo, "feat/landed") is not None, (
            "a branch `git branch -d` refuses (not merged into HEAD) was deleted — "
            "the delete is overriding git's refusal"
        )
        assert "Branch 'feat/landed' not deleted" in r.stdout, r.stdout


class TestNewlineInWorktreePath:
    """Q-307 (a) — `git worktree list --porcelain` without `-z` does not quote a
    newline inside a path (measured on git 2.50.1), so the line parser split it.

    The entry called that fail-safe, and for a lone newline path it was: the
    truncated path did not exist, the worktree classified STALE, and `--clean`
    exited 1 on `is not a working tree` with nothing removed. It was not
    fail-safe when the truncated prefix is ANOTHER worktree's path — then that
    worktree was classified with this record's merged branch and removed in its
    place (`test_a_truncated_path_never_removes_the_worktree_it_names`, measured
    against the pre-fix script).
    """

    @staticmethod
    def _newline_wt(tmp_path, repo, branch="feat/nl", stem="wt-new"):
        wt = tmp_path / f"{stem}\nline"
        _add_worktree(repo, wt, branch)
        assert str(wt) in _listed_paths(repo), "precondition: git registered the newline path"
        return wt

    def test_a_merged_newline_path_worktree_is_reclaimed(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        wt = self._newline_wt(tmp_path, repo)

        r = _run(repo, "--clean")

        assert r.returncode == 0, r.stdout + r.stderr
        assert "Removing MERGED worktree" in r.stdout, (
            f"the newline path did not classify MERGED (pre-fix: STALE): {r.stdout}"
        )
        assert "Removed 1 worktree(s), skipped 0 active, 0 failed." in r.stdout
        assert not wt.exists()
        assert str(wt) not in _listed_paths(repo)
        assert _ref(repo, "feat/nl") is None, "the merged branch was not deleted"

    def test_a_newline_path_park_record_is_still_protected(self, tmp_path):
        """The whole path reaches the content probes, not a truncation of it."""
        repo = _repo(tmp_path / "repo")
        _ignore(repo, "sysop/runtime/")
        wt = self._newline_wt(tmp_path, repo)
        rec = _park_record(wt)

        r = _run(repo, "--clean")

        assert r.returncode == 0, r.stdout + r.stderr
        assert "Skipping ACTIVE" in r.stdout, r.stdout
        assert (rec / "review.md").is_file()

    def test_a_truncated_path_never_removes_the_worktree_it_names(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        _ignore(repo, "scratch/")
        inflight = tmp_path / "wt"
        _add_worktree(repo, inflight, "feat/inflight")
        _git(inflight, "commit", "-q", "--allow-empty", "-m", "in-flight, unmerged")
        (inflight / "scratch").mkdir()
        (inflight / "scratch" / "notes.txt").write_text("ignored, but real\n")
        # `…/wt\nx` truncates to `…/wt` — the in-flight worktree's own path.
        self._newline_wt(tmp_path, repo, branch="feat/nl", stem="wt")

        r = _run(repo, "--clean")

        assert r.returncode == 0, r.stdout + r.stderr
        assert inflight.is_dir(), (
            "the in-flight worktree was removed in place of the newline-path one: "
            "its path was the newline record's truncation, classified with that "
            "record's merged branch"
        )
        assert (inflight / "scratch" / "notes.txt").is_file()
        assert str(inflight) in _listed_paths(repo)

    def test_run_from_inside_a_newline_path_worktree_finds_the_primary(self, tmp_path):
        """The primary probe reads the same list; from inside a linked worktree it
        is the one that decides what is MAIN."""
        repo = _repo(tmp_path / "repo")
        wt = self._newline_wt(tmp_path, repo)

        r = _run(wt)

        assert r.returncode == 0, r.stdout + r.stderr
        rows = [ln for ln in r.stdout.splitlines() if "│" in ln and ("MAIN" in ln or "MERGED" in ln
                                                                      or "STALE" in ln or "ACTIVE" in ln)]
        main_rows = [ln for ln in rows if "MAIN" in ln]
        assert len(main_rows) == 1 and str(repo)[-20:] in main_rows[0], r.stdout
        assert not any("STALE" in ln for ln in rows), r.stdout
        # Shown as `?`, so the table row is not split across two lines.
        assert any("wt-new?line" in ln and "MERGED" in ln for ln in rows), r.stdout


    def test_a_newline_in_the_primary_checkouts_own_path(self, tmp_path):
        """Run from a linked worktree, the script finds the primary as the list's
        FIRST record. Pre-fix that read truncated a newline in the primary's own
        path and the run refused: `Resolved primary checkout '…' is not a
        directory`. Fail-closed, but every mode was dead from every linked
        worktree of such a checkout."""
        repo = _repo(tmp_path / "re\npo")
        linked = tmp_path / "wt-linked"
        _add_worktree(repo, linked, "feat/linked")

        r = _run(linked)

        assert r.returncode == 0, r.stdout + r.stderr
        main_rows = [ln for ln in r.stdout.splitlines() if "MAIN" in ln and "│" in ln]
        assert len(main_rows) == 1 and "re?po" in main_rows[0], r.stdout
        assert any("MERGED" in ln and "wt-linked" in ln for ln in r.stdout.splitlines()), r.stdout


class TestWorktreeListWithoutNulOutput:
    """`git worktree list -z` arrived in git 2.36, and this repo states no minimum
    git version — so the script probes `-z` and, on an older git, falls back to
    today's newline parse. Simulated with a shim that refuses `-z` the way an
    older git refuses an unknown switch (usage, exit 129)."""

    @staticmethod
    def _old_git_shim(tmp_path):
        d = tmp_path / "oldgit"
        d.mkdir()
        log = tmp_path / "z-attempts.log"
        real = shutil.which("git")
        (d / "git").write_text(
            "#!/usr/bin/env bash\n"
            'is_list=0; has_z=0\n'
            'for a in "$@"; do\n'
            '  [[ "$a" == "list" ]] && is_list=1\n'
            '  [[ "$a" == "-z" ]] && has_z=1\n'
            'done\n'
            'if [[ "$is_list" == 1 && "$has_z" == 1 && " $* " == *" worktree "* ]]; then\n'
            f'  printf "%s\\n" "$*" >> "{log}"\n'
            '  echo "error: unknown switch \\`z\'" >&2\n'
            "  exit 129\n"
            "fi\n"
            f'exec "{real}" "$@"\n'
        )
        (d / "git").chmod(0o755)
        return d, log

    def test_an_older_git_still_classifies_and_cleans(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        merged = tmp_path / "wt-merged"
        _add_worktree(repo, merged, "feat/merged")
        active = tmp_path / "wt-active"
        _add_worktree(repo, active, "feat/active")
        (active / "scratch.txt").write_text("uncommitted\n")
        d, log = self._old_git_shim(tmp_path)

        r = _run(repo, "--clean", env=_env(PATH=f"{d}:{os.environ['PATH']}"))

        # The positive half: without it, a script that never tries `-z` passes.
        assert log.is_file() and log.read_text().strip(), "the script never tried `-z`"
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Removed 1 worktree(s), skipped 1 active, 0 failed." in r.stdout, r.stdout
        assert not merged.exists() and (active / "scratch.txt").is_file()

    def test_an_older_git_keeps_the_pre_fix_newline_behaviour(self, tmp_path):
        """Without `-z` there is no way to read a newline path, so the fallback is
        exactly today's parse — which fails safe for a lone newline path: the
        truncation names nothing, and the removal of it is refused."""
        repo = _repo(tmp_path / "repo")
        wt = TestNewlineInWorktreePath._newline_wt(tmp_path, repo)
        d, _log = self._old_git_shim(tmp_path)

        r = _run(repo, "--clean", env=_env(PATH=f"{d}:{os.environ['PATH']}"))

        assert r.returncode == 1, r.stdout + r.stderr
        assert "Removing STALE worktree" in r.stdout, r.stdout
        assert wt.is_dir()


class TestNestedWorktree:
    """Found while closing Q-311: a worktree nested in another's gitignored
    directory is invisible to every content probe — git sees an ignored
    directory, not a repository. `--clean` classified the parent MERGED and
    removed it, taking the child's working tree with it, uncommitted work
    included, while printing `Skipping ACTIVE worktree` for the child (the
    child was classified before anything was removed).

    Every assertion here is independent of the order `git worktree list` prints
    the two in: that is the order of `.git/worktrees/` as the filesystem returns
    it, which is hash order on ext4.
    """

    @staticmethod
    def _nested(tmp_path, repo):
        _ignore(repo, "nest/")
        parent = tmp_path / "wt-parent"
        _add_worktree(repo, parent, "feat/parent")  # clean, merged → MERGED on its own
        child = parent / "nest" / "wt-child"
        _add_worktree(repo, child, "feat/child")
        (child / "uncommitted.txt").write_text("the child's work\n")
        return parent, child

    def test_clean_keeps_a_parent_that_holds_another_worktree(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        parent, child = self._nested(tmp_path, repo)

        r = _run(repo, "--clean")

        assert r.returncode == 0, r.stdout + r.stderr
        assert (child / "uncommitted.txt").is_file(), (
            "the nested worktree's uncommitted work was destroyed by removing its parent"
        )
        assert parent.is_dir()
        assert "Removed 0 worktree(s), skipped 2 active, 0 failed." in r.stdout, r.stdout
        assert f"It contains another worktree ({child})" in r.stdout, r.stdout
        assert str(child) in _listed_paths(repo)

    def test_force_names_the_nested_loss_whichever_is_removed_first(self, tmp_path):
        """`--force` removes both by design. Either order must name the child's
        uncommitted work: its own UNCOMMITTED WORK line when it goes first, the
        parent's nested line when the parent goes first (the child's own line is
        then computed against a directory already gone, and is silent)."""
        repo = _repo(tmp_path / "repo")
        parent, child = self._nested(tmp_path, repo)

        r = _run(repo, "--force")

        assert r.returncode == 0, r.stdout + r.stderr
        assert not parent.exists() and not child.exists()
        named = (f"Contains another worktree ({child})" in r.stdout
                 or any("UNCOMMITTED WORK" in ln and str(child) in ln
                        for ln in r.stdout.splitlines()))
        assert named, f"the nested worktree's uncommitted work was lost unnamed:\n{r.stdout}"

    def test_a_sibling_sharing_a_name_prefix_is_not_nested(self, tmp_path):
        """`wt-a` does not contain `wt-ab`: containment is by path component."""
        repo = _repo(tmp_path / "repo")
        a = tmp_path / "wt-a"
        ab = tmp_path / "wt-ab"
        _add_worktree(repo, a, "feat/a")
        _add_worktree(repo, ab, "feat/ab")

        r = _run(repo, "--clean")

        assert r.returncode == 0, r.stdout + r.stderr
        assert "Removed 2 worktree(s), skipped 0 active, 0 failed." in r.stdout, r.stdout
        assert not a.exists() and not ab.exists()

    def test_a_nested_entry_whose_directory_is_gone_protects_nothing(self, tmp_path):
        """A registered child with no directory has nothing a parent's removal can
        take. (Locked, or the opening prune would have reaped it before the list
        is read.)"""
        repo = _repo(tmp_path / "repo")
        parent, child = self._nested(tmp_path, repo)
        _git(repo, "worktree", "lock", str(child))
        shutil.rmtree(child)

        r = _run(repo, "--clean")

        assert not parent.exists(), (
            f"a nested entry with no directory kept its parent alive:\n{r.stdout}"
        )
        assert "Removing MERGED worktree: " + str(parent) in r.stdout, r.stdout
