"""The tracker write mutex — `Q-387`, Phase 258.

**This is the suite's first test that runs two processes at once.** Every prior
"race" test in this tree pre-seeds the rival's artifact and then runs a single
process: `test_claim_artifact_reaping.py::test_the_extracted_block_refuses_and_
preserves_a_rival_lock` writes a rival lock by hand, and
`test_batch_claim_atomicity.py` says so about itself in as many words — *"it is
not evidence that concurrent claims are safe, and nothing here is."* Those are
good tests of a refusal path; none of them could have caught `Q-387`, because the
defect only exists when two processes interleave.

WHAT THE DEFECT WAS, as measured rather than as filed. Two `batch_work.sh` claims
on DIFFERENT batches in one repo:

  * claim B's `sed` reads `review_tasks.md` INCLUDING claim A's uncommitted flip
    and writes both back, so A's pathspec `git commit -- review_tasks.md` records
    BOTH. B's commit then has nothing to commit, exits non-zero, prints "the
    claim was rolled back, nothing was claimed", and its `git checkout --`
    restores a state that already contains B's flip. B is left committed
    `In Progress` with no lock, no branch and no worktree — invisible to
    `/next-task` (not `Pending`) and to every in-flight reader (no lock).
  * and `review_index.py.write_index()` used a FIXED `<path>.tmp`, so two
    concurrent readers — `ensure_fresh()` writes the index on the READ path —
    collided there too and the loser died `FileNotFoundError`, surfacing as
    "Batch N not found in review_tasks.md" for a batch that was plainly present.

The filing said "about half of trials". On the criterion it used — a batch
committed `In Progress` holding no lock — this harness measures 5 of 40. On the
criterion that actually matters, *did both claims succeed*, it measured **40 of
40 defective**: two concurrent claims never both worked. Post-fix, 0 of 100.

THE POSITIVE ASSERTION IS THE POINT. The first post-fix run of this harness
scored a perfect 0 defects while one claim was silently refusing every time —
the shape where a "fix" that breaks claiming outright certifies itself clean. So
`_assert_both_claimed` checks that each batch really is claimed (committed flip
AND lock AND branch) before it looks for any failure signature. A test that only
counts bad outcomes passes when there are no outcomes at all.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
BATCH_WORK = SCRIPTS / "batch_work.sh"
GIT_LIB = SCRIPTS / "_git_lib.sh"


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


def _tasks(batches):
    out = ["# Review Tasks", ""]
    for n, status in batches:
        out += [
            f"### Batch {n} — Batch {n} title `{status}`",
            "",
            f"> **Branch:** `review/batch-{n}`",
            f"> **Scope:** scope-{n}",
            f"> **Verify:** pytest -k batch{n}",
            "",
            f"- [ ] **TASK-{n:04d}**: task for batch {n}",
            "",
        ]
    return "\n".join(out) + "\n"


def _repo(root, batches):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "review_tasks.md").write_text(_tasks(list(batches)))
    (root / "README.md").write_text("# seed\n")
    sd = root / "sysop" / "scripts"
    sd.mkdir(parents=True)
    for name in ("batch_work.sh", "close_batch.sh", "_log.py", "_git_lib.sh",
                 "review_index.py", "cleanup_worktrees.sh"):
        src = SCRIPTS / name
        if src.exists():
            shutil.copy(src, sd / name)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _head_status(repo, n):
    for line in _git(repo, "show", "HEAD:review_tasks.md").stdout.splitlines():
        if line.startswith(f"### Batch {n} "):
            return line.rsplit("`", 2)[-2]
    return "<no header>"


def _lock(repo, n):
    return repo / "sysop" / "runtime" / "locks" / f"BATCH-{n}.lock"


def _mutex(repo):
    return repo / "sysop" / "runtime" / "tracker.write.lock"


def _claim_concurrently(repo, batches):
    """Background one `batch_work.sh` per batch, then collect. Returns per-batch
    (stdout+stderr, returncode)."""
    procs = [
        (n, subprocess.Popen(["bash", str(BATCH_WORK), str(n)], cwd=str(repo),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True))
        for n in batches
    ]
    return {n: (p.communicate()[0], p.returncode) for n, p in procs}


def _assert_both_claimed(repo, results):
    """Every batch must be claimed for real. This runs BEFORE any failure-shape
    check on purpose — see the module docstring."""
    for n, (out, rc) in results.items():
        assert _head_status(repo, n) == "In Progress", (
            f"batch {n} not committed In Progress (rc={rc}).\n{out}")
        assert _lock(repo, n).is_file(), f"batch {n} has no lock (rc={rc}).\n{out}"
        assert _git(repo, "rev-parse", "--verify",
                    f"review/batch-{n}").returncode == 0, (
            f"batch {n} has no branch (rc={rc}).\n{out}")
        assert rc == 0, f"batch {n} exited {rc}.\n{out}"


#: Internal trials per parametrized case. See `TestTwoConcurrentClaims`.
TRIALS_PER_CASE = 8


class TestTwoConcurrentClaims:
    """The defect, run the way it actually happens.

    **This detector is probabilistic, and the honest number is not the one a
    single run reports.** Measured during the build: run serially (`-n 0`), the
    pre-fix source fails 9 of 9 of this class's tests and the standalone harness
    failed 40 of 40 trials. Run under the suite's own `-n auto`, the SAME pre-fix
    source passed 5 of 6 of these — xdist saturates the machine, the two claims
    get scheduled far enough apart that the winner finishes its whole critical
    section before the loser starts, and the window never opens. A defect that
    only exists when two processes interleave stops being detectable exactly when
    nothing lets them interleave.

    So this class does NOT carry the phase on its own, and saying otherwise would
    be the vacuous-guard shape one layer up. The load is carried by the
    source-pinned guards below — both writers acquire, the mutex is anchored on
    the shared locks dir, the tempfiles are PID-qualified, no bare `trap - EXIT`
    survives — every one of which is deterministic in any scheduler. This class is
    the evidence that those guards are guarding something real.

    `TRIALS_PER_CASE` internal trials per case is the compromise that keeps it
    useful under load: at the measured per-trial masking rate, 8 trials × 3 cases
    puts pre-fix detection near-certain even fully parallel, while costing a few
    seconds.

    **Honest about which half of that is measured.** A reviewer found 8 to be
    over-provisioned on their machine — pre-fix source red in 10 of 10 runs at
    every value from 1 to 8, at a cost of 4.6s → 16.5s per suite run. The value
    stays anyway, and the reason is precautionary rather than measured: the
    masking is load-dependent by construction, one machine's headroom is not
    another's, and a detector for a race is the wrong place to trim to the edge of
    what worked once. Note also that under the FULL suite rather than this module
    alone, the pre-fix failure is 4 of 6 rather than 6 of 6 —
    `test_neither_claim_reports_a_rollback_that_did_not_happen` and
    `test_the_mutex_does_not_survive_the_run` run a single trial each.
    """

    @pytest.mark.parametrize("attempt", range(3))
    def test_two_concurrent_claims_on_different_batches_both_succeed(
            self, tmp_path, attempt):
        for t in range(TRIALS_PER_CASE):
            repo = _repo(tmp_path / f"r{attempt}_{t}",
                         [(1, "Pending"), (2, "Pending")])
            results = _claim_concurrently(repo, (1, 2))
            _assert_both_claimed(repo, results)

    def test_neither_claim_reports_a_rollback_that_did_not_happen(self, tmp_path):
        """The filed symptom in its own words: a run that printed "nothing was
        claimed" over a batch whose flip was committed anyway. A message that
        contradicts the committed state is the harm, separately from the
        stranding — it is what sends the operator looking for work that is not
        where they were told it is not."""
        repo = _repo(tmp_path / "r", [(1, "Pending"), (2, "Pending")])
        results = _claim_concurrently(repo, (1, 2))
        _assert_both_claimed(repo, results)
        for n, (out, _rc) in results.items():
            if "nothing was claimed" in out:
                assert _head_status(repo, n) != "In Progress", (
                    f"batch {n} says 'nothing was claimed' but HEAD has it "
                    f"In Progress — the exact contradiction Q-387 filed.\n{out}")

    def test_the_mutex_does_not_survive_the_run(self, tmp_path):
        """A leaked mutex is worse than the bug: it wedges every later claim AND
        close until someone removes it by hand. Nothing auto-breaks it, by
        design, so nothing may leak it either."""
        repo = _repo(tmp_path / "r", [(1, "Pending"), (2, "Pending")])
        _assert_both_claimed(repo, _claim_concurrently(repo, (1, 2)))
        assert not _mutex(repo).exists(), (
            f"{_mutex(repo)} survived a successful run")

    def test_three_concurrent_claims_all_succeed(self, tmp_path):
        """Two is the filed shape; the mutex is not allowed to be a two-party
        arrangement. Three contend for one lock and one git index."""
        repo = _repo(tmp_path / "r",
                     [(1, "Pending"), (2, "Pending"), (3, "Pending")])
        results = _claim_concurrently(repo, (1, 2, 3))
        _assert_both_claimed(repo, results)
        assert not _mutex(repo).exists()


class TestTheMutexPrimitive:
    """`tracker_lock_acquire` / `tracker_lock_release`, driven directly."""

    def _probe(self, tmp_path, script, wait="1"):
        """Run a bash snippet with `_git_lib.sh` sourced.

        `SYSOP_TRACKER_LOCK_WAIT=1` because the shipped default is 120s. That
        default is not arbitrary and must not be lowered to suit the tests: the
        claim's critical section contains a network `git pull`, so a shorter wait
        outlasts a *legitimate* holder and invites an operator to break a live
        lock. The override exists so the refusal path stays cheap to exercise.
        """
        env = dict(os.environ, SYSOP_TRACKER_LOCK_WAIT=wait)
        return subprocess.run(
            ["bash", "-c", f'source "{GIT_LIB}" || exit 99\n{script}'],
            cwd=str(tmp_path), capture_output=True, text=True, env=env)

    def test_a_held_mutex_refuses_and_names_the_holder(self, tmp_path):
        locks = tmp_path / "sysop" / "runtime" / "locks"
        locks.mkdir(parents=True)
        (locks.parent / "tracker.write.lock").write_text(
            "holder_pid: 424242\nholder: someone_else.sh\nwhat: a rival\n")
        r = self._probe(tmp_path, f'tracker_lock_acquire "{locks}" "my claim"')
        assert r.returncode == 1
        assert "locked by another Sysop process" in r.stderr
        assert "someone_else.sh" in r.stderr, (
            "the refusal must show the holder; an operator cannot decide whether "
            "a lock is stale without knowing who claims to hold it")
        assert "my claim" in r.stderr, "the refusal must name what it refused"

    def test_the_refusal_does_not_break_the_lock(self, tmp_path):
        """No auto-break, on purpose (Phase 258's stated policy): breaking a lock
        this function cannot prove is dead is how it breaks a live one."""
        locks = tmp_path / "sysop" / "runtime" / "locks"
        locks.mkdir(parents=True)
        mutex = locks.parent / "tracker.write.lock"
        mutex.write_text("holder_pid: 424242\nholder: rival.sh\n")
        before = mutex.read_text()
        self._probe(tmp_path, f'tracker_lock_acquire "{locks}" "my claim"')
        assert mutex.exists() and mutex.read_text() == before

    def test_the_refusal_names_the_command_that_clears_it(self, tmp_path):
        """Refuse-loudly is only a policy if the operator is told the remedy."""
        locks = tmp_path / "sysop" / "runtime" / "locks"
        locks.mkdir(parents=True)
        (locks.parent / "tracker.write.lock").write_text("holder: rival.sh\n")
        r = self._probe(tmp_path, f'tracker_lock_acquire "{locks}" "x"')
        assert "rm -f" in r.stderr and "tracker.write.lock" in r.stderr

    def test_acquire_then_release_leaves_nothing(self, tmp_path):
        locks = tmp_path / "sysop" / "runtime" / "locks"
        locks.mkdir(parents=True)
        r = self._probe(
            tmp_path,
            f'tracker_lock_acquire "{locks}" "x" || exit 1\n'
            f'test -f "{locks.parent}/tracker.write.lock" || exit 2\n'
            "tracker_lock_release\n"
            f'test -f "{locks.parent}/tracker.write.lock" && exit 3\n'
            "exit 0")
        assert r.returncode == 0, r.stdout + r.stderr

    def test_release_without_acquire_is_a_no_op(self, tmp_path):
        """The EXIT trap in `close_batch.sh` fires on every path, including ones
        that never reached the acquire."""
        r = self._probe(tmp_path, "tracker_lock_release; echo ok")
        assert r.returncode == 0 and "ok" in r.stdout

    def test_an_empty_locks_dir_refuses_rather_than_locking_the_wrong_place(
            self, tmp_path):
        """`resolve_locks_dir` returns 1 when the main root is unresolvable, and
        both callers pass its output through. An empty argument must refuse: a
        mutex at `/tracker.write.lock` would be shared across every repo on the
        machine, or unwritable, and either way it is not this repo's mutex."""
        r = self._probe(tmp_path, 'tracker_lock_acquire "" "my claim"')
        assert r.returncode == 1
        assert "Could not resolve the runtime directory" in r.stderr


class TestBothWritersTakeIt:
    """A mutex one of two writers skips is not a mutex. Pinned on the source
    because the alternative is a fixture that runs a claim and a close at once
    against a merged branch, which needs far more setup than the property is
    worth — and the property is structural, not behavioural."""

    def test_the_claim_path_acquires_and_releases(self):
        body = BATCH_WORK.read_text(encoding="utf-8")
        assert "tracker_lock_acquire" in body
        assert "tracker_lock_release" in body

    def test_the_close_path_acquires_and_releases(self):
        body = (SCRIPTS / "close_batch.sh").read_text(encoding="utf-8")
        assert "tracker_lock_acquire" in body
        assert "tracker_lock_release" in body

    def test_both_writers_derive_the_mutex_path_from_resolve_locks_dir(self):
        """Both callers must derive the mutex from `resolve_locks_dir` — the
        resolver they already share — rather than from any root of their own.
        `batch_work.sh` records that `resolve_main_root` and
        `resolve_primary_worktree` disagree, and that changing one script alone
        would put two scripts' locks in different places.

        **The first version of this test checked the wrong thing and the author's
        own mutation battery caught it.** It asserted that the *variable name*
        `_locks_dir` appeared on the acquire line — and the mutation that
        reintroduces the bug (`W03`: assign `_locks_dir` from `${MAIN_ROOT}/...`
        instead of from `resolve_locks_dir`) still satisfies that, so it survived.
        A guard on a variable's spelling is not a guard on its provenance. This
        version pins the assignment, and
        `test_a_separate_git_dir_repo_locks_where_the_close_would` is the
        behavioural half."""
        for name in ("batch_work.sh", "close_batch.sh"):
            body = (SCRIPTS / name).read_text(encoding="utf-8")
            lines = [ln for ln in body.splitlines() if not ln.strip().startswith("#")]
            call = [ln for ln in lines if "tracker_lock_acquire " in ln]
            assert call, f"{name} never calls tracker_lock_acquire"
            var = None
            for ln in call:
                between = ln.split("tracker_lock_acquire", 1)[1].strip()
                var = between.split()[0].strip('"').lstrip("$").strip("{}")
            assert var, f"{name}: could not read the acquire's first argument"
            assigns = [ln for ln in lines
                       if ln.strip().startswith(f"{var}=")
                       or ln.strip().startswith(f"  {var}=")]
            assert assigns, f"{name}: nothing assigns ${var}"
            # EVERY assignment, not any: a reviewer added a second, shadowing
            # `CLOSE_LOCKS_DIR=$(git rev-parse --show-toplevel)/...` after the
            # real one and the `any()` form accepted it. That is `W03` one layer
            # up — a guard on where *an* assignment came from rather than on
            # which one wins.
            assert all("resolve_locks_dir" in ln for ln in assigns), (
                f"{name} builds the mutex path without calling resolve_locks_dir: "
                f"{[a.strip() for a in assigns]}. The two writers must agree on "
                f"one path or the mutex is not a mutex.")

    def test_a_separate_git_dir_repo_locks_where_the_close_would(self, tmp_path):
        """The behavioural half of the assertion above, and the reason the source
        pin alone was not enough.

        `resolve_main_root` (`dirname` of `--git-common-dir`) and
        `resolve_primary_worktree` (`--show-toplevel`) return the SAME path in an
        ordinary checkout, which is why every other test here cannot tell them
        apart. Under `git init --separate-git-dir` they diverge: the primary
        worktree is `<x>/work` while `resolve_main_root` yields `<x>`. The batch
        locks use the latter, so the mutex must too — a claim that locked on
        `$MAIN_ROOT` would take a *different* file from the close, and both would
        proceed.

        Held-lock rather than happy-path on purpose: a passing claim proves
        nothing about WHERE it looked. Refusing proves it looked at the same place
        the close writes."""
        outer = tmp_path / "x"
        outer.mkdir()
        gitdir = outer / "elsewhere.git"
        work = outer / "work"
        subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q",
                        f"--separate-git-dir={gitdir}", str(work)],
                       check=True, capture_output=True)
        _git(work, "config", "user.email", "test@test")
        _git(work, "config", "user.name", "test")
        _git(work, "config", "commit.gpgsign", "false")
        (work / "review_tasks.md").write_text(_tasks([(1, "Pending")]))
        sd = work / "sysop" / "scripts"
        sd.mkdir(parents=True)
        for name in ("batch_work.sh", "close_batch.sh", "_log.py", "_git_lib.sh",
                     "review_index.py", "cleanup_worktrees.sh"):
            src = SCRIPTS / name
            if src.exists():
                shutil.copy(src, sd / name)
        _git(work, "add", "-A")
        _git(work, "commit", "-qm", "seed")

        # Sanity: the two resolvers really do diverge here, or the test proves
        # nothing. `resolve_main_root` is dirname of --git-common-dir.
        common = _git(work, "rev-parse", "--git-common-dir").stdout.strip()
        main_root = Path(common).resolve().parent
        assert main_root != work.resolve(), (
            "this layout did not split the resolvers, so the test cannot "
            f"discriminate: main_root={main_root} work={work}")

        # Hold the mutex where the CLOSE path would write it.
        held = main_root / "sysop" / "runtime" / "tracker.write.lock"
        held.parent.mkdir(parents=True, exist_ok=True)
        held.write_text("holder_pid: 424242\nholder: close_batch.sh\n")

        r = subprocess.run(["bash", str(BATCH_WORK), "1"], cwd=str(work),
                           capture_output=True, text=True,
                           env=dict(os.environ, SYSOP_TRACKER_LOCK_WAIT="1"))
        assert "locked by another Sysop process" in r.stderr, (
            "the claim did not see a mutex the close path holds — it locked "
            f"somewhere else.\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}")
        # The lock lands under the LOCKS dir, which in this layout is
        # `<outer>/sysop/runtime/locks/` — NOT `<outer>/work/...`. The first
        # version of this test asserted the latter, which a *successful* claim
        # also satisfies; a reviewer's `|| return 1` → `|| true` mutation
        # survived through exactly that hole. Assert on the real path, and on
        # the refusal actually refusing.
        real_lock = main_root / "sysop" / "runtime" / "locks" / "BATCH-1.lock"
        assert not real_lock.exists(), (
            f"a refused claim wrote {real_lock} — it did not refuse, it proceeded")
        assert r.returncode != 0, f"refused claim exited 0.\n{r.stdout}\n{r.stderr}"
        assert _head_status(work, 1) != "In Progress", (
            "a refused claim committed the status flip")

    def test_the_mutex_is_not_inside_the_globbed_locks_dir(self):
        """`scope_overlap.py`, `sitrep_survey.py` and `next_task.py` all glob
        `<locks>/*.lock` and parse each hit as a YAML task lock. A mutex in there
        would read as an in-flight claim and could drop a real batch out of the
        in-flight set."""
        lib = GIT_LIB.read_text(encoding="utf-8")
        # Behavioural, not spelling. The first version pinned the literal
        # `runtime_dir="$(dirname "$locks_dir")"`, and a reviewer's control —
        # `${locks_dir%/*}`, a byte-identical value — was FALSE-KILLED by it. A
        # guard that reds on a legal rewrite gets weakened or deleted, and this
        # one bought nothing: the real property is that the mutex lands beside
        # the locks dir rather than inside it, which is observable.
        assert '${runtime_dir}/tracker.write.lock' in lib
        import tempfile as _tf
        with _tf.TemporaryDirectory() as td:
            locks = Path(td) / "sysop" / "runtime" / "locks"
            locks.mkdir(parents=True)
            r = subprocess.run(
                ["bash", "-c", f'source "{GIT_LIB}" || exit 9\n'
                               f'tracker_lock_acquire "{locks}" "x" || exit 1\n'
                               'printf "%s\\n" "$TRACKER_LOCK_FILE"'],
                capture_output=True, text=True,
                env=dict(os.environ, SYSOP_TRACKER_LOCK_WAIT="1"))
            assert r.returncode == 0, r.stderr
            got = Path(r.stdout.strip())
            assert got.parent == locks.parent, (
                f"mutex landed at {got}, inside or beside the wrong directory; "
                f"it must sit in {locks.parent}, NOT in the globbed {locks}")
            assert not str(got).startswith(str(locks) + "/")


class TestTheTempfileClass:
    """`Q-382`'s class — a fixed tempfile shared by concurrent writers — had three
    instances, not the one Phase 256 fixed."""

    def test_review_index_tempfile_is_pid_qualified(self):
        """The instance that made a lock insufficient on its own: this one is on
        the READ path, so it crashed before a claim reached any mutex."""
        body = (SCRIPTS / "review_index.py").read_text(encoding="utf-8")
        assert 'tmp_path = "%s.%d.tmp" % (path, os.getpid())' in body

    def test_close_batch_tempfiles_are_pid_qualified(self):
        body = (SCRIPTS / "close_batch.sh").read_text(encoding="utf-8")
        fixed = [ln.strip() for ln in body.splitlines()
                 if 'TMP_FILE="${TASKS_FILE}' in ln]
        assert fixed == [], f"close_batch.sh still has a fixed tempfile: {fixed}"
        assert body.count('TMP_FILE="${TASKS_FILE%.md}.$$.md.tmp"') == 2

    def test_close_batch_tempfiles_keep_the_md_tmp_ending(self):
        """`archive_review_tasks.py:83` documents `review_tasks*.md.tmp` as the
        orphan shape it recognises at the repo root, and `batch_work.sh:877`
        keeps its name inside that class deliberately. `review_tasks.md.<pid>.tmp`
        ends in `.tmp` but NOT `.md.tmp`, so the obvious PID-qualification would
        have dropped these two files out of that class silently. This test exists
        because the first cut of this phase did exactly that."""
        body = (SCRIPTS / "close_batch.sh").read_text(encoding="utf-8")
        assert 'TMP_FILE="${TASKS_FILE}.$$.tmp"' not in body


class TestTheCombinedExitTrap:
    """`close_batch.sh` armed and disarmed three tempfile EXIT traps. `trap - EXIT`
    clears the WHOLE handler, so a lock-release trap would have been silently
    disarmed by the first rewrite that finished — and the mutex would then survive
    the process and wedge every later close."""

    def test_close_batch_has_no_bare_trap_dash_exit(self):
        body = (SCRIPTS / "close_batch.sh").read_text(encoding="utf-8")
        bare = [ln.strip() for ln in body.splitlines()
                if ln.strip() == "trap - EXIT"]
        assert bare == [], (
            "a bare `trap - EXIT` clears the combined handler and leaks the "
            f"tracker mutex: {bare}")

    def test_the_inspection_path_still_keeps_its_tempfile(self):
        """The one site that deliberately preserved `$TMP_FILE` for inspection
        did it by disarming the trap. It now clears `TMP_FILE` instead — same
        effect on the file, without also dropping the lock release."""
        body = (SCRIPTS / "close_batch.sh").read_text(encoding="utf-8")
        assert "Tempfile kept for inspection" in body
        lines = body.splitlines()
        i = [n for n, ln in enumerate(lines)
             if "Tempfile kept for inspection" in ln]
        assert len(i) == 1, f"anchor is no longer unique: {i}"
        # THREE lines, not a 400-char window. A reviewer measured that the window
        # spanned TWO `TMP_FILE=""` — the inspection one and the post-`mv` one
        # five lines later — so deleting the very line this test is named for
        # still passed, and the tempfile it promises to keep was then removed by
        # the EXIT handler.
        window = "\n".join(lines[i[0]:i[0] + 3])
        assert 'TMP_FILE=""' in window, (
            "the inspection path no longer clears TMP_FILE, so the combined EXIT "
            "handler deletes the tempfile the message promises to keep")
        assert "trap - EXIT" not in window


class TestTheWaitCoversTheNetworkPull:
    """The wait is 120s because `claim_batch`'s critical section contains
    `git pull --ff-only origin <default>`.

    This was a defect in this phase's own first cut, found by the author-side pass
    rule that says to RUN the command the change prescribes: at a 10s wait, a
    legitimate holder doing a slow fetch was outlasted, and the loser printed a
    refusal inviting the operator to `rm -f` a live lock — the same lost update
    this lock exists to prevent, reached from the other side.

    Pinned because the pressure to lower it is real and constant: every test that
    exercises the refusal pays the wait, and the cheap fix is to shrink the
    default rather than use the override."""

    def test_the_default_wait_is_not_seconds(self):
        lib = GIT_LIB.read_text(encoding="utf-8")
        line = [ln for ln in lib.splitlines()
                if "SYSOP_TRACKER_LOCK_WAIT" in ln and "max_wait=" in ln]
        assert line, "the wait is no longer overridable via SYSOP_TRACKER_LOCK_WAIT"
        import re
        m = re.search(r":-(\d+)\}", line[0])
        assert m, f"cannot read the default out of: {line[0].strip()}"
        assert int(m.group(1)) >= 60, (
            f"default tracker-lock wait is {m.group(1)}s. The critical section "
            "contains a network `git pull`, so a short wait refuses against a LIVE "
            "holder and tells the operator the lock may be stale. Use "
            "SYSOP_TRACKER_LOCK_WAIT in tests instead of lowering this.")

    def test_a_waiting_claim_says_so_rather_than_looking_hung(self, tmp_path):
        """Two minutes of silence is indistinguishable from a hang, and an
        operator who kills it has no idea why they waited."""
        lib = GIT_LIB.read_text(encoding="utf-8")
        assert "Waiting for the tracker lock" in lib

    def test_the_refusal_warns_before_the_rm(self, tmp_path):
        """The remedy is correct but not unconditional: the message must say that
        a live holder can legitimately hold the lock this long."""
        locks = tmp_path / "sysop" / "runtime" / "locks"
        locks.mkdir(parents=True)
        (locks.parent / "tracker.write.lock").write_text("holder: rival.sh\n")
        r = subprocess.run(
            ["bash", "-c", f'source "{GIT_LIB}" || exit 99\n'
                           f'tracker_lock_acquire "{locks}" "x"'],
            cwd=str(tmp_path), capture_output=True, text=True,
            env=dict(os.environ, SYSOP_TRACKER_LOCK_WAIT="1"))
        assert "CHECK FIRST" in r.stderr
        assert "network" in r.stderr


class TestTheReleasePathIsAlsoAWriter:
    """`batch_work.sh --release` is the THIRD writer of `review_tasks.md` and the
    second one inside `batch_work.sh`.

    This phase's first cut locked `claim_batch` and left `--release` open, and the
    record said "both writers of review_tasks.md" while being wrong about its own
    file. Two independent reviewers reproduced it — a release racing a claim was
    defective in 7 of 8 and 12 of 12 trials — producing both of `Q-387`'s
    symptoms: a batch committed under a message denying it, and an orphan lock
    over a `Pending` batch that `next_task.py` skips forever while this script's
    own preflight refuses to re-claim it.

    `--release` is not exotic: `/claim-task` prescribes it as the abandon outcome
    and `/roadmap` and `/review-close` both relay it."""

    def test_a_release_racing_a_claim_leaves_both_batches_consistent(self, tmp_path):
        repo = _repo(tmp_path / "r", [(1, "Pending"), (2, "Pending")])
        # claim 1 first, sequentially, so there is something to release
        r0 = subprocess.run(["bash", str(BATCH_WORK), "1"], cwd=str(repo),
                            capture_output=True, text=True)
        assert r0.returncode == 0, r0.stdout + r0.stderr
        procs = [
            subprocess.Popen(["bash", str(BATCH_WORK), "--release", "1"],
                             cwd=str(repo), stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True),
            subprocess.Popen(["bash", str(BATCH_WORK), "2"], cwd=str(repo),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True),
        ]
        outs = [p.communicate()[0] for p in procs]
        rcs = [p.returncode for p in procs]

        # The claim of 2 must have fully landed, or fully refused. Not half.
        if rcs[1] == 0:
            assert _head_status(repo, 2) == "In Progress", (
                f"claim of batch 2 exited 0 without committing the flip.\n{outs[1]}")
            assert _lock(repo, 2).is_file(), (
                f"claim of batch 2 exited 0 with no lock.\n{outs[1]}")
        else:
            assert _head_status(repo, 2) != "In Progress", (
                "batch 2 is committed In Progress under a run that refused — the "
                f"Q-387 contradiction, via --release.\n{outs[1]}")

        # And the release of 1 must have fully landed, or fully refused.
        if rcs[0] == 0:
            assert _head_status(repo, 1) == "Pending", (
                f"release exited 0 without reverting the flip.\n{outs[0]}")
            assert not _lock(repo, 1).exists(), (
                f"release exited 0 leaving its lock.\n{outs[0]}")
        else:
            assert _lock(repo, 1).is_file(), (
                "the release refused but removed its lock anyway — the orphan "
                f"shape, Pending with no lock or claimed with none.\n{outs[0]}")
        assert not _mutex(repo).exists()

    def test_the_release_path_acquires_the_mutex(self):
        """Source-pinned as well, because the behavioural test above is
        probabilistic and this property is not."""
        body = BATCH_WORK.read_text(encoding="utf-8")
        rel = body[body.index("REL_NUM=\"$(normalize_batch_arg"):]
        assert "tracker_lock_acquire" in rel, (
            "batch_work.sh --release does a sed/mv/git-commit over review_tasks.md "
            "and must take the same mutex the claim takes")
        assert "tracker_lock_release" in rel


class TestTheSignalTrapsExist:
    """A reviewer deleted `trap 'tracker_lock_release; exit 130' INT TERM` and
    every test in this module still passed — Ctrl-C mid-claim strands a mutex
    nothing auto-breaks, and nothing noticed.

    A second reviewer then measured that INT/TERM alone misses **SIGHUP** — the
    terminal closing, an SSH session dropping, a tmux window being killed — and
    that the claim path leaked the mutex on HUP while `close_batch.sh` survived
    the same signal, because the close had a real EXIT trap and the claim's
    comment merely *claimed* one existed at its call site. It did not."""

    def test_both_writers_arm_an_exit_trap_for_the_release(self):
        for name in ("batch_work.sh", "close_batch.sh"):
            body = (SCRIPTS / name).read_text(encoding="utf-8")
            armed = [ln for ln in body.splitlines()
                     if ln.strip().startswith("trap ")
                     and ln.rstrip().endswith("EXIT")
                     and "tracker_lock_release" in ln or
                     (ln.strip().startswith("trap ") and "_close_exit_cleanup" in ln)]
            assert armed, (
                f"{name} arms no EXIT trap that releases the tracker mutex. "
                "INT/TERM alone misses SIGHUP, which is the terminal closing.")

    def test_no_bare_trap_dash_exit_in_either_writer(self):
        """Widened from `close_batch.sh` to both. A reviewer pointed out that
        `batch_work.sh` still contained the forbidden pattern in `--release`, and
        that it went from latent to live the moment that path took the lock."""
        for name in ("batch_work.sh", "close_batch.sh"):
            body = (SCRIPTS / name).read_text(encoding="utf-8")
            bare = [n + 1 for n, ln in enumerate(body.splitlines())
                    if ln.strip() == "trap - EXIT"]
            assert bare == [], (
                f"{name} has a bare `trap - EXIT` at line(s) {bare}: it clears the "
                "WHOLE handler, silently disarming the mutex release")


class TestTheReleaseUnlinksOnlyItsOwnLock:
    """A reviewer walked a cascade: the refusal invites a hand `rm -f`, an
    operator takes it while the holder is alive, a third process acquires the
    now-free path, and the original holder's release deletes the NEW holder's
    lock — leaving that one running unprotected."""

    def test_release_does_not_delete_a_lock_it_did_not_write(self, tmp_path):
        locks = tmp_path / "sysop" / "runtime" / "locks"
        locks.mkdir(parents=True)
        mutex = locks.parent / "tracker.write.lock"
        r = subprocess.run(
            ["bash", "-c",
             f'source "{GIT_LIB}" || exit 9\n'
             f'tracker_lock_acquire "{locks}" "mine" || exit 1\n'
             # somebody removes it and a rival takes the path
             f'rm -f "{mutex}"\n'
             f'printf "holder_pid: 999999\\nholder: rival.sh\\n" > "{mutex}"\n'
             'tracker_lock_release\n'
             f'test -f "{mutex}" || exit 3\n'
             'exit 0'],
            capture_output=True, text=True,
            env=dict(os.environ, SYSOP_TRACKER_LOCK_WAIT="1"))
        assert r.returncode == 0, (
            "tracker_lock_release deleted a lock written by another process "
            f"(rc={r.returncode}). {r.stdout}{r.stderr}")


class TestANonRegularFileAtTheMutexPath:
    """A directory at the mutex path wedged every claim and close, and the
    printed remedy could not clear it: `rm -f <dir>` fails "is a directory", so
    the operator was told, forever, to run a command that does not work."""

    def test_a_directory_at_the_mutex_path_is_diagnosed(self, tmp_path):
        locks = tmp_path / "sysop" / "runtime" / "locks"
        locks.mkdir(parents=True)
        (locks.parent / "tracker.write.lock").mkdir()
        r = subprocess.run(
            ["bash", "-c", f'source "{GIT_LIB}" || exit 9\n'
                           f'tracker_lock_acquire "{locks}" "my claim"'],
            capture_output=True, text=True,
            env=dict(os.environ, SYSOP_TRACKER_LOCK_WAIT="1"))
        assert r.returncode == 1
        assert "NOT a regular file" in r.stderr
        assert "rm -rf" in r.stderr, (
            "the remedy must be `rm -rf` — `rm -f` cannot remove a directory, "
            "which is what made the original message unactionable")


class TestDryRunDoesNotTakeTheWriteMutex:
    """Two reviewers, independently: `close_batch.sh --dry-run` acquired
    unconditionally, so a preview created `sysop/runtime/`, held the write lock
    for the whole run, and could block a real claim or be refused itself."""

    def test_the_acquire_is_gated_on_dry_run(self):
        body = (SCRIPTS / "close_batch.sh").read_text(encoding="utf-8")
        i = body.index('tracker_lock_acquire "$CLOSE_LOCKS_DIR"')
        before = body[:i]
        assert before.rstrip().splitlines()[-2:], "no context before the acquire"
        window = "\n".join(before.splitlines()[-8:])
        assert "$DRY_RUN" in window, (
            "the close's tracker_lock_acquire is not gated on DRY_RUN; a preview "
            "that writes nothing must not take a write mutex")

