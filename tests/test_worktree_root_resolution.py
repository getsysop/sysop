"""Phase 234 (`Q-020` mechanism (3) + `Q-307`(b)): a script that resolves the
repo with `git rev-parse --show-toplevel` is asking "which worktree am I
standing in", and every one of these scripts meant "which checkout is the
primary". The two answers differ exactly when the caller is inside a linked
worktree — which is the state the workflow *prescribes*: `batch_work.sh` prints
`cd ${WORKTREE_DIR}` and, five lines later, `bash sysop/scripts/cleanup_worktrees.sh --clean`.

Measured before the fix, and each is a distinct failure rather than one symptom:

- `cleanup_worktrees.sh` crowned the caller's worktree MAIN and demoted the real
  primary to **MERGED** (not ACTIVE, as `Q-307`(b) had it — `main` is trivially an
  ancestor of `main`). `--clean` therefore skipped the worktree it was pointed at
  and tried to remove the primary; git refused, so nothing was lost, but the run
  exited 1 having cleaned nothing.
- `batch_work.sh`'s claim path read `review_tasks.md` out of the caller's
  worktree — a frozen copy of whatever the branch was cut from. A batch reading
  `In Progress` on main read `Pending` there, so every status refusal the record
  exists to trigger was adjudicated against the wrong record.
- The same path's `git add review_tasks.md` was CWD-relative, so from
  `<repo>/sysop/scripts/` it died `fatal: pathspec … did not match any files`
  under `set -e` *after* the rewrite had landed: disk `In Progress`, HEAD `Pending`.

These are behaviour tests over real repos, not shape assertions — the class was
filed `[reported]` for three phases and the citations had rotted by the time it
was picked up, so the only durable pin is one that runs the thing.
"""
import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
CLEANUP = SCRIPTS / "cleanup_worktrees.sh"
BATCH = SCRIPTS / "batch_work.sh"
REAL_GIT = shutil.which("git")

TASKS = """\
# Review Tasks

### Batch 1 — First batch `Pending`

> **Branch:** `feat/one`

- [ ] a
"""


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _project(root, tasks=None):
    """A primary checkout at <root>/main, with an origin so `git pull --ff-only`
    (a precondition of batch_work.sh's claim) can succeed."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "--bare", str(root / "origin.git")],
                   check=True, capture_output=True)
    main = root / "main"
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(main)],
                   check=True, capture_output=True)
    _git(main, "config", "user.email", "test@test")
    _git(main, "config", "user.name", "test")
    _git(main, "config", "commit.gpgsign", "false")
    (main / "README.md").write_text("# seed\n")
    if tasks is not None:
        (main / "review_tasks.md").write_text(tasks)
        sd = main / "sysop" / "scripts"
        sd.mkdir(parents=True, exist_ok=True)
        for name in ("review_index.py", "_log.py"):
            src = SCRIPTS / name
            if src.exists():
                shutil.copy(src, sd / name)
    _git(main, "add", "-A")
    _git(main, "commit", "-qm", "seed")
    _git(main, "remote", "add", "origin", str(root / "origin.git"))
    _git(main, "push", "-q", "-u", "origin", "main")
    return main


def _run(script, cwd, *args, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(["bash", str(script), *args],
                          cwd=str(cwd), capture_output=True, text=True, env=e)


def _classes(stdout):
    """Map branch -> class from the listing table."""
    out = {}
    for line in stdout.splitlines():
        for cls in ("MAIN", "MERGED", "ACTIVE", "STALE"):
            if cls in line and "│" in line and "Legend" not in line:
                cells = [c.strip() for c in line.split("│")]
                if len(cells) >= 3 and cells[1].endswith(cls):
                    out[cells[2]] = cls
    return out


# ── cleanup_worktrees.sh ────────────────────────────────────────────────────

class TestCleanupResolvesThePrimary:
    def test_classification_is_the_same_from_every_directory(self, tmp_path):
        """The load-bearing property: MAIN is a fact about the repo, not about
        the caller. Before the fix, run C disagreed with A and B on both rows."""
        main = _project(tmp_path)
        _git(main, "worktree", "add", "-q", "-b", "feat/a", str(tmp_path / "wt-a"))
        (main / "sub").mkdir()
        seen = {}
        for label, cwd in (("main", main), ("subdir", main / "sub"), ("worktree", tmp_path / "wt-a")):
            r = _run(CLEANUP, cwd)
            assert r.returncode == 0, r.stderr
            seen[label] = _classes(r.stdout)
        assert seen["main"] == {"main": "MAIN", "feat/a": "MERGED"}, seen["main"]
        assert seen["subdir"] == seen["main"], seen
        assert seen["worktree"] == seen["main"], seen

    def test_clean_from_inside_a_worktree_reclaims_that_worktree(self, tmp_path):
        """The prescribed sequence, end to end. Before: exit 1, nothing removed,
        the primary named as the removal target."""
        main = _project(tmp_path)
        wt = tmp_path / "wt-a"
        _git(main, "worktree", "add", "-q", "-b", "feat/a", str(wt))
        r = _run(CLEANUP, wt, "--clean")
        assert r.returncode == 0, r.stdout + r.stderr
        assert not wt.exists(), "the worktree the caller stood in was not reclaimed"
        assert main.is_dir() and (main / "README.md").is_file(), "the primary was damaged"

    def test_clean_from_inside_a_worktree_never_targets_the_primary(self, tmp_path):
        """The direction that mattered: not just 'it works now' but 'it stopped
        aiming at the one checkout it must never touch'."""
        main = _project(tmp_path)
        wt = tmp_path / "wt-a"
        _git(main, "worktree", "add", "-q", "-b", "feat/a", str(wt))
        r = _run(CLEANUP, wt, "--clean")
        targeted = [ln for ln in r.stdout.splitlines() if "Removing" in ln]
        assert targeted, r.stdout
        assert not any(str(main) in ln for ln in targeted), targeted

    def test_the_caller_is_told_when_its_own_directory_is_removed(self, tmp_path):
        main = _project(tmp_path)
        wt = tmp_path / "wt-a"
        _git(main, "worktree", "add", "-q", "-b", "feat/a", str(wt))
        r = _run(CLEANUP, wt, "--clean")
        assert "the worktree you invoked from" in r.stdout, r.stdout

    def test_that_note_stays_silent_for_any_other_worktree(self, tmp_path):
        """Negative control. Without it the assertion above also passes on a
        message printed unconditionally, which is the cry-wolf failure Phase 165
        reshaped this script's other warning to avoid."""
        main = _project(tmp_path)
        _git(main, "worktree", "add", "-q", "-b", "feat/a", str(tmp_path / "wt-a"))
        r = _run(CLEANUP, main, "--clean")
        assert "Removing" in r.stdout, r.stdout
        assert "the worktree you invoked from" not in r.stdout, r.stdout

    def test_it_refuses_when_the_primary_cannot_be_resolved(self, tmp_path):
        """The fail-closed arm. A silent fallback to `--show-toplevel` would put
        one empty answer behind two meanings — "not a worktree" and "the probe
        broke" — which is the two-causes-one-signal shape this phase's subject is."""
        main = _project(tmp_path)
        shim = tmp_path / "bin"
        shim.mkdir()
        (shim / "git").write_text(
            "#!/usr/bin/env bash\n"
            'for a in "$@"; do [[ "$a" == "--git-common-dir" ]] && exit 1; done\n'
            f'exec {REAL_GIT} "$@"\n'
        )
        (shim / "git").chmod(0o755)
        r = _run(CLEANUP, main, "--clean", env={"PATH": f"{shim}:{os.environ['PATH']}"})
        assert r.returncode == 1, r.stdout + r.stderr
        assert "could not describe this checkout" in r.stderr, r.stderr
        assert "Removing" not in r.stdout, "it removed something before refusing"


# ── batch_work.sh ───────────────────────────────────────────────────────────

class TestBatchWorkReadsThePrimarysRecord:
    def _stale_worktree(self, tmp_path):
        """A worktree cut BEFORE the batch was claimed, so its review_tasks.md
        still says `Pending` while the primary says `In Progress`."""
        main = _project(tmp_path, TASKS)
        _git(main, "branch", "older")
        wt = tmp_path / "wt-old"
        _git(main, "worktree", "add", "-q", str(wt), "older")
        (main / "review_tasks.md").write_text(TASKS.replace("`Pending`", "`In Progress`"))
        _git(main, "commit", "-qam", "claim batch 1")
        _git(main, "push", "-q", "origin", "main")
        locks = main / "sysop/runtime/locks"
        locks.mkdir(parents=True, exist_ok=True)
        (locks / "BATCH-1.lock").write_text("owner: someone-else\n")
        return main, wt

    def test_status_is_read_from_the_primary_not_the_callers_branch(self, tmp_path):
        main, wt = self._stale_worktree(tmp_path)
        assert "`Pending`" in (wt / "review_tasks.md").read_text(), "fixture is not stale"
        r = _run(BATCH, wt, "1")
        assert "already claimed" in r.stdout, r.stdout + r.stderr
        assert "Status: Pending" not in r.stdout, "the branch's frozen copy was believed"

    def test_the_claim_commit_survives_a_subdirectory_cwd(self, tmp_path):
        """The bare `git add review_tasks.md`. Before: `fatal: pathspec …`, the
        script dead under `set -e`, and the rewrite stranded on disk."""
        main = _project(tmp_path, TASKS)
        sub = main / "sysop" / "scripts"
        r = _run(BATCH, sub, "1")
        assert "fatal: pathspec" not in (r.stdout + r.stderr), r.stdout + r.stderr
        head = subprocess.run(["git", "show", "HEAD:review_tasks.md"], cwd=str(main),
                              capture_output=True, text=True).stdout
        disk = (main / "review_tasks.md").read_text()
        assert "`In Progress`" in disk, disk
        assert "`In Progress`" in head, "the claim never reached HEAD — half-applied"
        assert not subprocess.run(["git", "diff", "--quiet", "--", "review_tasks.md"],
                                  cwd=str(main)).returncode, "review_tasks.md left dirty"

    def test_the_batch_worktree_lands_beside_the_primary(self, tmp_path):
        """`../<project basename>-batch-<N>/` is what the header advertises, and
        the primary's basename is what "project" means — not the caller's."""
        main = _project(tmp_path, TASKS)
        wt = tmp_path / "wt-old"
        _git(main, "branch", "older")
        _git(main, "worktree", "add", "-q", str(wt), "older")
        _run(BATCH, wt, "1")
        assert (tmp_path / "main-batch-1").is_dir(), sorted(p.name for p in tmp_path.iterdir())
        assert not (tmp_path / "wt-old-batch-1").exists()

    def test_a_run_from_the_primary_is_unchanged(self, tmp_path):
        """Negative control: the fix must not have bought correctness inside a
        worktree by changing what the dominant path does."""
        main = _project(tmp_path, TASKS)
        r = _run(BATCH, main, "1")
        assert r.returncode == 0, r.stdout + r.stderr
        assert (tmp_path / "main-batch-1").is_dir()
        head = subprocess.run(["git", "show", "HEAD:review_tasks.md"], cwd=str(main),
                              capture_output=True, text=True).stdout
        assert "`In Progress`" in head, head


class TestTheClaimWritesWhereItRead:
    """Found by this phase's own mutation battery, not by its author.

    Anchoring the record paths at the primary fixed *which record the claim is
    decided against* — and, left alone, split the decision from the write. Rows
    `R2` and `B5` survived the first battery run, and chasing them produced a
    defect this phase had introduced: with the primary on a feature branch and a
    worktree holding `main`, `claim_batch`'s on-main check read the CALLER's HEAD,
    passed, and committed the claim onto the primary's feature branch while
    printing `✅ Claimed Batch 1 on main`. `main` gained nothing.

    Not reachable before this phase: everything used `$REPO_ROOT`, so the write
    followed the same HEAD the check had read. A fix for a wrong *read* opened a
    wrong *acceptance*, which is the direction it is easy not to look in.
    """

    def _split(self, tmp_path):
        """Primary on a feature branch; a linked worktree holding `main`."""
        main = _project(tmp_path, TASKS)
        _git(main, "checkout", "-q", "-b", "feat/x")
        wt = tmp_path / "wt-main"
        _git(main, "worktree", "add", "-q", str(wt), "main")
        return main, wt

    def test_a_claim_is_refused_when_the_primary_is_not_on_main(self, tmp_path):
        main, wt = self._split(tmp_path)
        r = _run(BATCH, wt, "1")
        # Phase 254 (`Q-378`): a refusal, not a warn-and-continue. The claim
        # used to return 0 here and build branch/worktree/lock anyway.
        assert r.returncode == 1, r.stdout + r.stderr
        assert "is not on main" in r.stderr, r.stdout + r.stderr
        assert "nothing was written" in r.stderr, r.stderr
        for ref in ("main", "feat/x"):
            log = subprocess.run(["git", "log", "--oneline", ref], cwd=str(main),
                                 capture_output=True, text=True).stdout
            assert "docs: claim Batch" not in log, f"{ref} took a claim commit:\n{log}"

    def test_the_rewrite_lands_in_the_file_the_status_was_read_from(self, tmp_path):
        """`review_index.py` resolves review_tasks.md from its own location, so
        `$INDEX_SCRIPT` decides which record is READ; `$TASKS_FILE` is the file
        that gets REWRITTEN. Point them at different checkouts and the script
        decides against one file and edits another — which is what row `R2`
        reverts, and what nothing here caught until the battery said so."""
        main = _project(tmp_path, TASKS)
        wt = tmp_path / "wt-side"
        _git(main, "branch", "side")
        _git(main, "worktree", "add", "-q", str(wt), "side")
        r = _run(BATCH, wt, "1")
        assert r.returncode == 0, r.stdout + r.stderr
        head = subprocess.run(["git", "show", "HEAD:review_tasks.md"], cwd=str(main),
                              capture_output=True, text=True).stdout
        assert "`In Progress`" in head, "the claim was decided but never recorded"
        assert "`Pending`" in (wt / "review_tasks.md").read_text(), \
            "the caller's worktree copy was rewritten instead of the primary's"

    def test_a_dirty_copy_in_the_callers_worktree_does_not_block(self, tmp_path):
        """The claim's dirty-tree precondition is about the file it is going to
        edit. Row `B5`: reading the caller's copy makes an unrelated worktree's
        edits veto a claim against a clean primary."""
        main = _project(tmp_path, TASKS)
        wt = tmp_path / "wt-side"
        _git(main, "branch", "side")
        _git(main, "worktree", "add", "-q", str(wt), "side")
        (wt / "review_tasks.md").write_text(TASKS + "\n<!-- local scribble -->\n")
        r = _run(BATCH, wt, "1")
        assert "Skipping batch claim" not in r.stderr, r.stdout + r.stderr
        head = subprocess.run(["git", "show", "HEAD:review_tasks.md"], cwd=str(main),
                              capture_output=True, text=True).stdout
        assert "`In Progress`" in head, head

    def test_a_dirty_copy_in_the_primary_still_blocks(self, tmp_path):
        """The safety direction of the same predicate — the one that must not be
        traded away to win the test above."""
        main = _project(tmp_path, TASKS)
        (main / "review_tasks.md").write_text(TASKS + "\n<!-- uncommitted -->\n")
        r = _run(BATCH, main, "1")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "review_tasks.md has uncommitted changes" in r.stderr, r.stdout + r.stderr
        assert "nothing was written" in r.stderr, r.stderr
        head = subprocess.run(["git", "show", "HEAD:review_tasks.md"], cwd=str(main),
                              capture_output=True, text=True).stdout
        assert "`Pending`" in head, "a dirty primary was claimed anyway"

    def test_the_pull_does_not_fast_forward_the_callers_branch(self, tmp_path):
        """Row `B7`, the sibling of `B6` four lines below it in the script.

        `claim_batch`'s `git pull --ff-only origin main` was bare, which was safe
        only while the on-main check guaranteed the caller WAS on main. Making
        that check a fact about the primary removed the guarantee without moving
        the pull, so a caller on any branch behind `main` would have had it
        silently fast-forwarded. Survived the first two battery runs because both
        fixtures had the worktree level with `main`, where the pull is a no-op —
        an inert fixture, not a passing guard."""
        main = _project(tmp_path, TASKS)
        _git(main, "branch", "side")
        wt = tmp_path / "wt-behind"
        _git(main, "worktree", "add", "-q", str(wt), "side")
        behind = subprocess.run(["git", "rev-parse", "side"], cwd=str(main),
                                capture_output=True, text=True).stdout.strip()
        (main / "moved.txt").write_text("main advances\n")
        _git(main, "add", "-A")
        _git(main, "commit", "-qm", "main moves ahead of side")
        _git(main, "push", "-q", "origin", "main")
        r = _run(BATCH, wt, "1")
        assert r.returncode == 0, r.stdout + r.stderr
        after = subprocess.run(["git", "rev-parse", "side"], cwd=str(main),
                               capture_output=True, text=True).stdout.strip()
        assert after == behind, "the caller's branch was fast-forwarded by someone else's claim"


class TestExoticGitLayouts:
    """Found by this phase's review round (execution lens), and the sharpest
    finding in it: the first fix resolved the primary as
    `dirname "$(git rev-parse --git-common-dir)"` — the idiom five sibling scripts
    use for the LOCK path — which is the repo root only when the git dir is
    literally `<root>/.git`.

    In a submodule that yields `<super>/.git/modules/<name>`; under
    `git init --separate-git-dir` it yields the git dir's PARENT. Both are real
    directories, so the existence check passed and the wrong answer was used:
    measured, a run from inside a submodule re-rooted the whole script at the
    SUPERPROJECT and removed its worktrees, and a read-only `list` under
    `--separate-git-dir` died exit 128 where it had exited 0.

    The shipped resolution narrows to the one case the defect lives in —
    `--git-dir` differs from `--git-common-dir` only inside a linked worktree — so
    these layouts take the identity path and behave exactly as they did before the
    phase. That parity is the property under test; each case below is a layout the
    original test file did not contain.
    """

    def _separate_git_dir(self, tmp_path, tasks=None):
        work = tmp_path / "work"
        subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q",
                        "--separate-git-dir", str(tmp_path / "gd"), str(work)],
                       check=True, capture_output=True)
        _git(work, "config", "user.email", "test@test")
        _git(work, "config", "user.name", "test")
        _git(work, "config", "commit.gpgsign", "false")
        (work / "README.md").write_text("# seed\n")
        if tasks is not None:
            (work / "review_tasks.md").write_text(tasks)
            sd = work / "sysop" / "scripts"
            sd.mkdir(parents=True)
            for name in ("review_index.py", "_log.py"):
                shutil.copy(SCRIPTS / name, sd / name)
        _git(work, "add", "-A")
        _git(work, "commit", "-qm", "seed")
        return work

    def test_a_separate_git_dir_checkout_still_lists(self, tmp_path):
        """Exit 128 on a read-only run was the regression; PARITY is the fix — and
        parity, not correctness, is deliberately what is asserted.

        Under `--separate-git-dir`, `git worktree list --porcelain` reports the
        worktree's path as the GIT DIR, which is not where the files are, so the
        checkout classifies ACTIVE rather than MAIN. That was true before this
        phase too, and it is git's answer rather than the script's. The properties
        that matter are that the run completes and that `--clean` does not reclaim
        the only working tree; asserting MAIN here would be asserting a state this
        layout has never been in — which is what the first draft of this test did."""
        work = self._separate_git_dir(tmp_path)
        r = _run(CLEANUP, work)
        assert r.returncode == 0, f"exit {r.returncode}\n{r.stdout}\n{r.stderr}"
        assert "fatal:" not in r.stderr, r.stderr
        assert list(_classes(r.stdout)) == ["main"], r.stdout
        c = _run(CLEANUP, work, "--clean")
        assert c.returncode == 0, c.stdout + c.stderr
        assert (work / "README.md").is_file(), "the only working tree was reclaimed"

    def test_batch_work_still_finds_the_record_under_a_separate_git_dir(self, tmp_path):
        """The same defect reached `batch_work.sh` only because this phase pointed
        `$TASKS_FILE`/`$INDEX_SCRIPT` at the lock-path helper. `--list` answered
        `❌ review_tasks.md not found at <gitdir's parent>/review_tasks.md`."""
        work = self._separate_git_dir(tmp_path, TASKS)
        r = _run(BATCH, work, "--list")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "review_tasks.md not found" not in r.stdout + r.stderr, r.stdout + r.stderr
        assert "First batch" in r.stdout, r.stdout

    def test_a_submodule_run_cannot_reach_the_superproject(self, tmp_path):
        """The worst of the three: `--clean` from inside a submodule enumerated and
        removed the SUPERPROJECT's worktrees, and `--force` destroyed uncommitted
        work in one. Nothing outside the submodule may appear in the output at all."""
        sub = _project(tmp_path / "subrepo")
        super_ = _project(tmp_path / "super")
        add = subprocess.run(
            ["git", "-c", "protocol.file.allow=always", "submodule", "add", "-q",
             str(sub), "vendor/sub"],
            cwd=str(super_), capture_output=True, text=True)
        if add.returncode != 0:
            import pytest
            pytest.skip(f"local submodule add unavailable here: {add.stderr.strip()[:120]}")
        _git(super_, "commit", "-qm", "add submodule")
        wt = tmp_path / "super-wt"
        _git(super_, "worktree", "add", "-q", "-b", "feat/super", str(wt))
        (wt / "precious.txt").write_text("uncommitted work in the SUPERPROJECT\n")
        r = _run(CLEANUP, super_ / "vendor" / "sub", "--force")
        assert str(wt) not in r.stdout, f"reached a superproject worktree:\n{r.stdout}"
        assert wt.is_dir() and (wt / "precious.txt").is_file(), \
            "the superproject's worktree was destroyed from inside a submodule"

    def test_a_bare_repo_layout_still_protects_the_caller(self, tmp_path):
        """`git worktree list --porcelain`'s first entry is the BARE repo here, and
        it carries a `bare` marker. Taking it as the primary would leave no entry
        classified MAIN — so the checkout the operator is standing in becomes
        removable. The marker is checked, and the caller keeps the protection it
        had before this phase."""
        seed = _project(tmp_path / "seed")
        bare = tmp_path / "proj" / ".bare"
        bare.parent.mkdir(parents=True)
        subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(bare)],
                       check=True, capture_output=True)
        main = tmp_path / "proj" / "main"
        subprocess.run(["git", f"--git-dir={bare}", "worktree", "add", "-q", str(main)],
                       check=True, capture_output=True)
        r = _run(CLEANUP, main, "--clean")
        assert r.returncode == 0, r.stdout + r.stderr
        assert main.is_dir() and (main / "README.md").is_file(), \
            "the only working tree in a bare layout was reclaimed"


class TestFixtureShapesTheFirstBatteryMissed:
    """Found by this phase's review round (guards lens), which ran 40 mutations
    disjoint from the author's and watched **16 behaviour-changing ones survive** —
    against an author battery reporting 19/20. Two fixture assumptions did most of
    that damage, and neither was adversarial:

    1. **Every worktree in this file is a SIBLING of the primary.** Sysop's never
       are: `claim_task.sh` and the agent harness put them under
       `<primary>/.claude/worktrees/`. With a sibling fixture, a MAIN test that
       prefix-matches (`"$MAIN_ROOT"*`) is indistinguishable from one that compares
       equal, and `$REPO_ROOT/..` is indistinguishable from `$MAIN_ROOT/..` — so
       the two mutations that reinstate the phase's own defect both survived.
    2. **`claim_batch`'s commit-failure arm was declared "UNEXERCISED — needs a
       hostile index."** It needs a three-line `pre-commit` hook, and Sysop ships
       pre-commit hooks. That declaration was wrong, and it was the reason both the
       rollback's anchor and its `return 1` went unguarded.
    """

    def _nested(self, tmp_path, tasks=None):
        """The layout this project actually uses: worktrees UNDER the primary."""
        main = _project(tmp_path, tasks)
        wt = main / ".claude" / "worktrees" / "wt-a"
        wt.parent.mkdir(parents=True)
        _git(main, "worktree", "add", "-q", "-b", "feat/a", str(wt))
        return main, wt

    def test_a_nested_worktree_is_not_the_primary(self, tmp_path):
        """`"$wt_path" == "$MAIN_ROOT"` must not become `"$MAIN_ROOT"*`. Under a
        prefix match the nested worktree is crowned MAIN and `--clean` reports
        `Removed 0 worktree(s), 0 failed` at exit 0 — the pre-fix defect's dangerous
        half, silently."""
        main, wt = self._nested(tmp_path)
        r = _run(CLEANUP, main)
        assert _classes(r.stdout) == {"main": "MAIN", "feat/a": "MERGED"}, r.stdout
        c = _run(CLEANUP, main, "--clean")
        assert c.returncode == 0, c.stdout + c.stderr
        assert not wt.exists(), "a nested worktree was never reclaimed"
        assert (main / "README.md").is_file()

    def test_the_batch_worktree_parent_is_the_primarys(self, tmp_path):
        """Pins the PARENT, not only the basename. From a nested worktree,
        `$REPO_ROOT/..` is `<primary>/.claude/worktrees` — so a reverted parent puts
        the batch worktree inside the runtime directory."""
        main, wt = self._nested(tmp_path, TASKS)
        _run(BATCH, wt, "1")
        assert (tmp_path / "main-batch-1").is_dir(), sorted(p.name for p in tmp_path.iterdir())
        assert not (main / ".claude" / "worktrees" / "main-batch-1").exists()

    def _reject_commits(self, repo):
        """A `pre-commit` hook that refuses everything — the fixture the author's
        battery said it did not have."""
        hooks = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], cwd=str(repo),
                               capture_output=True, text=True).stdout.strip()
        h = (repo / hooks) if not hooks.startswith("/") else Path(hooks)
        h.mkdir(parents=True, exist_ok=True)
        (h / "pre-commit").write_text("#!/bin/sh\nexit 1\n")
        (h / "pre-commit").chmod(0o755)

    def test_a_refused_claim_commit_leaves_nothing_behind(self, tmp_path):
        """The arm's `return 1` matters: its caller is `claim_batch … || exit 1`.
        As `return 0` the run continues and writes a worktree and a lock for a batch
        still reading `Pending` — the claimable-but-half-applied state the rollback
        exists to prevent."""
        main = _project(tmp_path, TASKS)
        self._reject_commits(main)
        r = _run(BATCH, main, "1")
        assert r.returncode != 0, r.stdout + r.stderr
        assert "`Pending`" in (main / "review_tasks.md").read_text(), "rewrite not rolled back"
        assert not (tmp_path / "main-batch-1").exists(), "a worktree was created for a failed claim"
        locks = main / "sysop" / "runtime" / "locks"
        assert not (locks / "BATCH-1.lock").exists(), "a lock was written for a failed claim"

    def test_the_rollback_does_not_destroy_the_callers_own_edits(self, tmp_path):
        """The rollback is `git -C "$MAIN_ROOT" checkout -- review_tasks.md`.
        Anchored at `$REPO_ROOT` instead, it discards the CALLER's uncommitted
        review_tasks.md — data loss — and leaves the primary half-applied."""
        main, wt = self._nested(tmp_path, TASKS)
        self._reject_commits(main)
        (wt / "review_tasks.md").write_text(TASKS + "\n<!-- the caller's own work -->\n")
        r = _run(BATCH, wt, "1")
        assert r.returncode != 0, r.stdout + r.stderr
        assert "the caller's own work" in (wt / "review_tasks.md").read_text(), \
            "the caller's uncommitted work was destroyed by someone else's rollback"
        assert "`Pending`" in (main / "review_tasks.md").read_text(), "primary left half-applied"

    def test_a_staged_edit_to_the_record_also_blocks(self, tmp_path):
        """The precondition has two arms — `diff` and `diff --cached`. The control
        that was meant to pin it wrote the file and never staged it, so the
        `--cached` arm was untested and a STAGED edit was swept into the claim
        commit (Phase 151's all-or-nothing breach, through the other door)."""
        main = _project(tmp_path, TASKS)
        (main / "review_tasks.md").write_text(TASKS + "\n<!-- staged, not committed -->\n")
        _git(main, "add", "review_tasks.md")
        r = _run(BATCH, main, "1")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "review_tasks.md has uncommitted changes" in r.stderr, r.stdout + r.stderr
        head = subprocess.run(["git", "show", "HEAD:review_tasks.md"], cwd=str(main),
                              capture_output=True, text=True).stdout
        assert "staged, not committed" not in head, "a staged edit was swept into the claim commit"

    def test_an_unrelated_dirty_file_does_not_veto_a_claim(self, tmp_path):
        """The other end of the same predicate: the check is pathspec-scoped, so
        only `review_tasks.md` blocks. Dropping `-- review_tasks.md` makes any dirty
        file in the primary veto every claim."""
        main = _project(tmp_path, TASKS)
        (main / "README.md").write_text("# edited, and nothing to do with the batch\n")
        r = _run(BATCH, main, "1")
        assert "Skipping batch claim" not in r.stderr, r.stdout + r.stderr
        head = subprocess.run(["git", "show", "HEAD:review_tasks.md"], cwd=str(main),
                              capture_output=True, text=True).stdout
        assert "`In Progress`" in head, head

    def test_the_recovery_hint_names_the_primary(self, tmp_path):
        """The hint must name the PRIMARY, not the caller's own checkout: pointing
        it at `$REPO_ROOT` sends the operator back to the directory that was just
        refused — and, after a `--clean`, possibly to one that is gone.

        Phase 254 (`Q-378`) changed which hint this is. The arm used to write a
        lock and then say how to clear it (`cd <primary> && … --release N`); it
        now refuses before writing, so the hint says where the claim has to be
        made from instead. Same invariant, different sentence — and note the
        fixture's own topology (primary on `feat/x`, `main` held by a worktree)
        is the case where a flat `git checkout` recipe would be refused by git,
        which is why the message offers it as the usual case and names the
        worktree collision underneath."""
        main = _project(tmp_path, TASKS)
        _git(main, "checkout", "-q", "-b", "feat/x")
        wt = tmp_path / "wt-main"
        _git(main, "worktree", "add", "-q", str(wt), "main")
        r = _run(BATCH, wt, "1")
        assert r.returncode == 1, r.stderr
        assert str(main) in r.stderr, r.stderr
        assert f"git -C {main} checkout" in r.stderr, r.stderr
        assert "checked out in another worktree" in r.stderr, (
            "the fixture IS that collision — the hint must not stop at a "
            "command git will refuse here"
        )

    def test_the_force_loop_reports_the_callers_own_directory(self, tmp_path):
        """`--force` has its own loop; the author's battery declared it unreached.
        It shares the helper, and that sharing is what this pins."""
        main, wt = self._nested(tmp_path)
        (wt / "scratch.txt").write_text("uncommitted\n")
        r = _run(CLEANUP, wt, "--force")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "the worktree you invoked from" in r.stdout, r.stdout
        assert (main / "README.md").is_file(), "the primary was destroyed by --force"

    def test_batch_work_refuses_when_the_primary_cannot_be_resolved(self, tmp_path):
        """The batch_work twin of `test_it_refuses_when_the_primary_cannot_be_resolved`,
        and the last of the guards lens's survivors. A fallback to `$REPO_ROOT` here
        is not merely a wrong path: it silently restores the very read this phase
        exists to stop, on the one code path that writes a lock."""
        main = _project(tmp_path, TASKS)
        shim = tmp_path / "bin"
        shim.mkdir()
        (shim / "git").write_text(
            "#!/usr/bin/env bash\n"
            'for a in "$@"; do [[ "$a" == "--git-dir" ]] && exit 1; done\n'
            f'exec {REAL_GIT} "$@"\n')
        (shim / "git").chmod(0o755)
        r = _run(BATCH, main, "1", env={"PATH": f"{shim}:{os.environ['PATH']}"})
        assert r.returncode == 1, r.stdout + r.stderr
        assert "Could not resolve the primary checkout" in r.stderr, r.stderr
        assert not (tmp_path / "main-batch-1").exists(), "a worktree was created anyway"
