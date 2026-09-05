"""`claim_task.sh --commit-claim` — the claim path's write mutex (`Q-397`, Phase 261).

**Why this module exists and the prose guards do not cover it.**
`tests/test_batch_claim_kinds.py` pins that Step 4d invokes this mode and that the
mode still carries its mutex, its idempotence test, its self-heal arm and Rule A.
Every one of those is a *source* check. None of them runs anything, and the defect
this phase fixed was invisible to source reading: the old Step 4d block looked
correct and exited 0 while losing the claim. `_shared/adversarial-review.md`
§ *Before you spawn anyone* rule 3 — run the commands the change prescribes — is
the only thing that reaches it, so this module runs them.

**What was measured, and against what.** A maintainer-side harness (not shipped)
drove two concurrent claims through the shipped Step 4a and Step 4d blocks,
extracted from `SKILL.md` verbatim. Pre-fix, in the tight window, **6 to 19 of 100**
trials ended with one task still `open` at `HEAD` while its own claim process
exited 0 — the author measured 16 and 19, an independent reviewer measured 6 on the
same tree. **The loss reproduces on every run; the rate is load- and
machine-dependent, and the range is the honest figure.** Post-fix: 0 of 100 on
every run, reproduced independently. The serial control — the same scripts run one
after the other — was clean in every state, which is what distinguishes a race from
a broken fixture. It earned that: an earlier fixture lacked an executable
`.venv/bin/python3`, so `resolve_yaml_python` refused and Step 4b failed on every
trial, and the rate it reported was ~48/100. The control caught it; the first
number had already been written down.

**The concurrency case here is probabilistic and load-dependent**, exactly as
`test_tracker_write_mutex.py` says of its own. It is a real two-process race, but
the deterministic cases below it are what carry this module: a mode that refuses
under a held mutex, releases what it takes, re-flips a clobbered edit, and refuses
off the default branch.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
CLAIM_TASK = SCRIPTS / "claim_task.sh"
SKILL = REPO_ROOT / "core/skills/claim-task/SKILL.md"

TRIALS = 6


def _a_pyyaml_interpreter_is_reachable() -> bool:
    """Can `claim_task.sh --commit-claim` find an interpreter that imports yaml?

    **The script's own order**: the venv candidates it anchors on, then bare
    `python3` on PATH. This has to be the predicate, and the first version of this
    module got it wrong in the direction that hides the whole module.

    That version gated on `REPO_ROOT/.venv/bin/python3` merely EXISTING. CI does
    `pip install -r requirements-dev.txt` into the runner's python and never
    creates a `.venv` in the checkout — so on the one machine whose result gates
    `main`, this module ran **1 of 25 tests** and skipped the rest, with the
    required `pytest` check green over the entire behavioural guard for `Q-397`.
    Found by Phase 261's own review round, which ran it in a fresh clone.
    `tests/test_claim_clone_and_flag_order.py` had the right predicate already.
    """
    for cand in (REPO_ROOT / ".venv/bin/python3", REPO_ROOT / "venv/bin/python3"):
        if cand.exists() and subprocess.run(
                [str(cand), "-c", "import yaml"], capture_output=True).returncode == 0:
            return True
    found = shutil.which("python3")
    return bool(found) and subprocess.run(
        [found, "-c", "import yaml"], capture_output=True).returncode == 0


# Applied PER CLASS, not module-wide. A module-level `pytestmark` also gated the
# pure source-shape guards below — which only read files and assert strings — so on
# a checkout with no reachable interpreter (a fresh clone, a tester's machine) the
# whole module went dark and a truncate-in-place regression walked through it. That
# is HIGH-2's class a second time, one layer in: the honest gate covers exactly the
# tests that need the thing it probes for.
needs_interpreter = pytest.mark.skipif(
    not _a_pyyaml_interpreter_is_reachable(),
    reason="claim_task.sh --commit-claim needs an interpreter with PyYAML to flip "
           "tasks/index.yml; none is reachable here (no usable venv, and python3 "
           "on PATH cannot import yaml)",
)


def _index(task_ids) -> str:
    body = ["schema_version: 1", "tasks:"]
    for tid in task_ids:
        body += [f"  - id: {tid}", f"    title: task {tid}", "    status: open",
                 "    kind: tech", "    effort: 1", "    priority: medium"]
    return "\n".join(body) + "\n"


def _git(root, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                          text=True, check=check)


def _build_repo(tmp_path, with_venv=True):
    """A primary checkout with the shipped scripts, optionally with a usable venv.

    The venv symlink is load-bearing, not scaffolding: `--commit-claim` refuses
    before taking the mutex when `resolve_yaml_python` finds no interpreter, so a
    fixture without one exercises the refusal path on every case below and proves
    nothing about the mutex.
    """
    main = tmp_path / "main"
    (main / "tasks" / "open").mkdir(parents=True)
    (main / "sysop" / "scripts").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main", str(main))
    _git(main, "config", "user.email", "t@example.invalid")
    _git(main, "config", "user.name", "t")
    (main / ".gitignore").write_text("sysop/runtime/\n.venv/\n")
    (main / "tasks" / "index.yml").write_text(_index(("TECH-0001", "TECH-0002")))
    for tid in ("TECH-0001", "TECH-0002"):
        (main / "tasks" / "open" / f"{tid}.md").write_text(f"# {tid}\n")
    for name in ("claim_task.sh", "_git_lib.sh", "validate_tasks.py",
                 "default_branch.sh", "_log.py"):
        src = SCRIPTS / name
        if src.exists():
            (main / "sysop" / "scripts" / name).write_bytes(src.read_bytes())
    if with_venv:
        # Symlink the checkout's venv WHEN THERE IS ONE, and fall through to PATH
        # `python3` when there is not — which is exactly what `resolve_yaml_python`
        # does, and is the state CI runs in. Skipping here instead is what made
        # this module invisible on the machine that gates `main`; the module-level
        # skipif above is the honest gate, and it fires only when NO interpreter
        # anywhere can import yaml.
        #
        # Never REMOVE the symlink afterwards to get the no-venv case: `repo/.venv`
        # resolves into the real checkout, and the suite's repo-write guard
        # (correctly) refuses the unlink. Build the variant instead.
        venv = REPO_ROOT / ".venv"
        if (venv / "bin" / "python3").exists():
            (main / ".venv").symlink_to(venv)
    _git(main, "add", "-A")
    _git(main, "commit", "-qm", "init")
    return main


@pytest.fixture
def repo(tmp_path):
    return _build_repo(tmp_path)


@pytest.fixture
def repo_without_venv(tmp_path):
    return _build_repo(tmp_path, with_venv=False)


def _commit_claim(repo, task_id, **kw):
    return subprocess.run(
        ["bash", "sysop/scripts/claim_task.sh", "--commit-claim", task_id],
        cwd=str(repo), capture_output=True, text=True, **kw)


def _status_at_head(repo, task_id):
    out = _git(repo, "show", "HEAD:tasks/index.yml").stdout
    cur = None
    for ln in out.splitlines():
        s = ln.strip()
        if s.startswith("- id:"):
            cur = s.split(":", 1)[1].strip()
        elif s.startswith("status:") and cur == task_id:
            return s.split(":", 1)[1].strip()
    return None


def _mutex(repo):
    return repo / "sysop" / "runtime" / "tracker.write.lock"


def false_success(repo, task_id, returncode):
    """The pre-fix failure shape: the claim process reported success and the task
    is not `in_progress` at HEAD. Extracted so the concurrency case and its
    non-vacuity control exercise THE SAME predicate — a control that re-asserts an
    inline copy proves only that `assert False` raises."""
    return returncode == 0 and _status_at_head(repo, task_id) != "in_progress"


@needs_interpreter
class TestItRuns:
    def test_a_claim_is_flipped_and_committed(self, repo):
        r = _commit_claim(repo, "TECH-0001")
        assert r.returncode == 0, r.stdout + r.stderr
        assert _status_at_head(repo, "TECH-0001") == "in_progress"
        assert "claim: mark TECH-0001 as in-progress" in _git(
            repo, "log", "--oneline").stdout

    def test_the_commit_message_matches_what_reads_it(self, repo):
        """`scripts/auto_claim_miner.py`'s CLAIM_RE is `^claim: mark ([A-Z][A-Z0-9-]+)
        as in-progress$`. The subject is a contract with a reader, not a label."""
        import re
        _commit_claim(repo, "TECH-0001")
        subject = _git(repo, "log", "-1", "--format=%s").stdout.strip()
        assert re.match(r"^claim: mark ([A-Z][A-Z0-9-]+) as in-progress$", subject)

    def test_a_second_run_is_a_clean_no_op(self, repo):
        assert _commit_claim(repo, "TECH-0001").returncode == 0
        before = _git(repo, "rev-parse", "HEAD").stdout
        r = _commit_claim(repo, "TECH-0001")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "nothing to commit" in r.stdout
        assert _git(repo, "rev-parse", "HEAD").stdout == before, \
            "the resume path made a second commit"

    def test_only_the_index_is_committed(self, repo):
        """Step 4d's bare `git commit` swept in whatever else was staged in the
        shared primary checkout — under concurrency, another agent's work."""
        (repo / "unrelated.txt").write_text("someone else's staged work\n")
        _git(repo, "add", "unrelated.txt")
        assert _commit_claim(repo, "TECH-0001").returncode == 0
        files = _git(repo, "show", "--name-only", "--format=", "HEAD").stdout.split()
        assert files == ["tasks/index.yml"], files
        assert "unrelated.txt" in _git(repo, "diff", "--cached", "--name-only").stdout


@needs_interpreter
class TestTheCommittedPathIsTheWrittenPath:
    """Both writers resolve `os.path.realpath` and write THROUGH; the committer has
    to follow them there.

    Phase 261's first cut did not: it probed `git diff --quiet HEAD -- tasks/index.yml`
    and committed `-- tasks/index.yml` with no `git add`, so whenever the tracked
    path and the written file differed it printed `nothing to commit (resume path)`
    and exited 0 over an uncommitted flip — the exact `Q-397` signature the mode
    exists to remove, reintroduced by the fix for it. Its own review round found
    both cases by execution. The untracked one was a strict REGRESSION: the inline
    `git add` + `git commit` block this phase deleted handled it correctly.
    """

    def test_a_symlinked_index_is_committed_not_reported_as_a_no_op(self, tmp_path):
        repo = _build_repo(tmp_path)
        real = repo / "data" / "index.yml"
        real.parent.mkdir()
        (repo / "tasks" / "index.yml").rename(real)
        (repo / "tasks" / "index.yml").symlink_to(Path("..") / "data" / "index.yml")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "symlink the index")

        r = _commit_claim(repo, "TECH-0001")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "nothing to commit" not in r.stdout, \
            "the flip was made and then reported as a no-op:\n" + r.stdout
        committed = _git(repo, "show", "HEAD:data/index.yml").stdout
        assert "in_progress" in committed, "the claim is not at HEAD"
        assert _git(repo, "status", "--porcelain").stdout.strip() == "", \
            "the flip was left uncommitted in the working tree"

    def test_an_untracked_index_is_committed(self, tmp_path):
        repo = _build_repo(tmp_path)
        _git(repo, "rm", "-q", "--cached", "tasks/index.yml")
        _git(repo, "commit", "-qm", "untrack the index")
        assert _git(repo, "cat-file", "-e", "HEAD:tasks/index.yml",
                    check=False).returncode != 0, "fixture did not untrack it"

        r = _commit_claim(repo, "TECH-0001")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "nothing to commit" not in r.stdout, r.stdout
        assert _status_at_head(repo, "TECH-0001") == "in_progress"

    def test_the_detector_would_see_the_regression(self, repo):
        """Non-vacuity: on an ORDINARY index the mode must still commit, so the two
        assertions above are not passing because they are unreachable."""
        r = _commit_claim(repo, "TECH-0001")
        assert r.returncode == 0
        assert "nothing to commit" not in r.stdout
        assert _status_at_head(repo, "TECH-0001") == "in_progress"


@needs_interpreter
class TestTheSelfHeal:
    """The half that makes the fix work without reordering Steps 4a-4d.

    A mutex taken at 4d cannot protect the write 4a already made outside it, so
    4d must repair. Deleting this arm restores silent claim loss with every
    source-level guard still green — which is why it is tested by execution.
    """

    def test_a_clobbered_step_4a_edit_is_re_flipped(self, repo):
        # The fixture's index is `open` on disk, which is exactly the state a
        # rival's whole-file safe_dump leaves your flip in by the time 4d runs.
        assert _status_at_head(repo, "TECH-0001") == "open"
        r = _commit_claim(repo, "TECH-0001")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "re-flipped" in r.stdout, \
            "a repaired claim must say so; a silent repair reads as a clean run"
        assert _status_at_head(repo, "TECH-0001") == "in_progress"

    def test_a_non_claimable_status_is_refused_rather_than_flipped(self, repo):
        idx = repo / "tasks" / "index.yml"
        idx.write_text(idx.read_text().replace(
            "  - id: TECH-0001\n    title: task TECH-0001\n    status: open",
            "  - id: TECH-0001\n    title: task TECH-0001\n    status: done", 1))
        r = _commit_claim(repo, "TECH-0001")
        assert r.returncode != 0
        assert "not open or in_progress" in r.stderr
        assert "Nothing was written" in r.stderr

    def test_an_absent_task_is_refused(self, repo):
        r = _commit_claim(repo, "TECH-9999")
        assert r.returncode != 0
        assert "not found" in r.stderr


@needs_interpreter
class TestTheMutex:
    def test_a_held_mutex_refuses_and_writes_nothing(self, repo):
        m = _mutex(repo)
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text("holder_pid: 999999\nholder: someone\nwhat: a test\n")
        before = _git(repo, "rev-parse", "HEAD").stdout
        r = _commit_claim(repo, "TECH-0001", env={**os.environ,
                                                  "SYSOP_TRACKER_LOCK_WAIT": "1"})
        assert r.returncode != 0
        assert _git(repo, "rev-parse", "HEAD").stdout == before
        assert _status_at_head(repo, "TECH-0001") == "open"
        assert m.exists(), "a refusal must not break the lock it refused on"

    def test_the_refusal_names_the_holder_and_what_was_not_written(self, repo):
        m = _mutex(repo)
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text("holder_pid: 999999\nholder: batch_work.sh\nwhat: the claim of Batch 3\n")
        r = _commit_claim(repo, "TECH-0001", env={**os.environ,
                                                  "SYSOP_TRACKER_LOCK_WAIT": "1"})
        out = r.stdout + r.stderr
        assert "batch_work.sh" in out
        assert "no status flip, no commit" in out

    def test_the_mutex_does_not_survive_a_successful_run(self, repo):
        assert _commit_claim(repo, "TECH-0001").returncode == 0
        assert not _mutex(repo).exists()

    def test_a_missing_interpreter_refuses_before_taking_the_mutex(self, repo_without_venv):
        """Fail-closed ORDER, not just fail-closed.

        `resolve_yaml_python` is probed before `tracker_lock_acquire` on purpose: a
        run that takes the mutex and then discovers it cannot write would refuse
        every other writer for the duration of a doomed run, and the mutex is
        deliberately never broken automatically. Without this case that ordering is
        untested — the fixture always has an interpreter — so a battery row
        attacking it could only be declared, not killed.
        """
        repo = repo_without_venv
        if subprocess.run(["python3", "-c", "import yaml"],
                          capture_output=True).returncode == 0:
            pytest.skip("this host's bare python3 has PyYAML; the refusal is unreachable")
        r = _commit_claim(repo, "TECH-0001")
        assert r.returncode != 0
        assert "PyYAML is required" in r.stderr
        assert not _mutex(repo).exists(), \
            "the mode took the mutex before it knew it could write"
        assert _status_at_head(repo, "TECH-0001") == "open"

    def test_the_mutex_does_not_survive_a_refused_run(self, repo):
        r = _commit_claim(repo, "TECH-9999")
        assert r.returncode != 0
        assert not _mutex(repo).exists(), \
            "a task-not-found refusal leaked the mutex and would wedge every writer"

    def test_it_blocks_on_the_path_the_batch_writers_use(self, repo):
        """One mutex, not two. `_git_lib.sh` records that anchoring per script
        would ship two lock paths under `--separate-git-dir` and in submodules,
        so this asserts the path by OBSERVING what blocks the mode — the absence
        of a second file somewhere else would prove nothing.
        """
        m = _mutex(repo)
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text("holder_pid: 999999\nholder: batch_work.sh\nwhat: Batch 3\n")
        r = _commit_claim(repo, "TECH-0001",
                          env={**os.environ, "SYSOP_TRACKER_LOCK_WAIT": "1"})
        assert r.returncode != 0, "a lock at the batch writers' path did not block"
        # …and it is that exact file, not merely some lock: removing it lets the
        # same command through.
        m.unlink()
        assert _commit_claim(repo, "TECH-0001").returncode == 0


@needs_interpreter
class TestRuleA:
    def test_a_primary_checkout_off_the_default_branch_is_refused(self, repo):
        _git(repo, "checkout", "-q", "-b", "feature/x")
        before = _git(repo, "rev-parse", "HEAD").stdout
        r = _commit_claim(repo, "TECH-0001")
        assert r.returncode != 0
        assert "STOP" in r.stderr
        assert _git(repo, "rev-parse", "HEAD").stdout == before
        assert not _mutex(repo).exists(), "the Rule A refusal leaked the mutex"

    def test_the_branch_is_resolved_not_asserted_as_main(self, repo):
        """`Q-377`: a hard-coded `main` stopped this step dead on a `master` repo."""
        _git(repo, "branch", "-m", "main", "master")
        r = _commit_claim(repo, "TECH-0001")
        assert r.returncode == 0, r.stdout + r.stderr
        assert _status_at_head(repo, "TECH-0001") == "in_progress"


@needs_interpreter
class TestConcurrently:
    """The real two-process race. Probabilistic and load-dependent — under `-n auto`
    a defect can hide — which is why every case above it is deterministic."""

    @pytest.mark.parametrize("attempt", range(TRIALS))
    def test_two_concurrent_claims_both_land(self, repo, attempt):
        procs = [
            (tid, subprocess.Popen(
                ["bash", "sysop/scripts/claim_task.sh", "--commit-claim", tid],
                cwd=str(repo), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True))
            for tid in ("TECH-0001", "TECH-0002")
        ]
        outs = {tid: p.communicate()[0] for tid, p in procs}
        rcs = {tid: p.returncode for tid, p in procs}

        # The criterion that matters, and it is narrower than "each has its own
        # commit": two flips can legitimately land in one commit when the second
        # claim finds the first's already staged. What must never happen is a
        # claim that reports success over a task still `open`.
        for tid in ("TECH-0001", "TECH-0002"):
            if rcs[tid] == 0:
                assert not false_success(repo, tid, rcs[tid]), (
                    f"{tid} exited 0 but is not in_progress at HEAD — a false "
                    f"success, which is the whole of `Q-397`.\n{outs[tid]}")
            else:
                # A loud refusal is the acceptable outcome: the mutex was held.
                assert "tracker" in outs[tid].lower() or "STOP" in outs[tid], outs[tid]
        assert not _mutex(repo).exists(), "a concurrent pair leaked the mutex"

    def test_the_predicate_fires_on_the_pre_fix_shape_and_not_otherwise(self, repo):
        """Non-vacuity, against the real predicate rather than an inline copy.

        Both polarities, because a detector that always fires certifies nothing
        and one that never fires certifies less.
        """
        # rc 0 with the task still `open` IS the pre-fix failure.
        assert _status_at_head(repo, "TECH-0001") == "open"
        assert false_success(repo, "TECH-0001", 0)
        # A loud refusal over the same state is not a false success.
        assert not false_success(repo, "TECH-0001", 1)
        # And a genuine claim is not one either.
        assert _commit_claim(repo, "TECH-0001").returncode == 0
        assert not false_success(repo, "TECH-0001", 0)


def _step_4a_script(task_id):
    """Step 4a's heredoc out of the shipped `SKILL.md`, verbatim, runnable.

    Extracted rather than retyped: a copy would pass while the shipped step broke,
    which is the whole reason `test_claim_task_heredocs_execute.py` exists.
    """
    import re as _re
    text = SKILL.read_text(encoding="utf-8")
    blocks, buf, live = [], [], False
    for raw in text.splitlines():
        m = _re.match(r"^\s*```(\S*)", raw)
        if m:
            if live:
                blocks.append("\n".join(buf))
            buf, live = [], (not live) and m.group(1).lower() == "bash"
            continue
        if live:
            buf.append(raw)
    hits = [b for b in blocks if "disappeared between Step 2 and Step 4" in b]
    assert len(hits) == 1, f"expected exactly one Step 4a block, found {len(hits)}"
    return hits[0].replace("<TASK_ID>", task_id)


@needs_interpreter
class TestStep4a:
    """The forward flip, which is the OTHER half of `Q-397`.

    These two close what the phase's own battery first reported as declared
    survivors. The battery reached them only through the maintainer-side
    concurrency harness, and "only a non-shipped tool can see it" is a reason to
    write a deterministic case, not a reason to leave the row declared.
    """

    def test_an_empty_index_is_refused_in_words_not_an_attributeerror(self, repo):
        """A rival mid-truncate leaves this file zero-length, and `safe_load("")`
        returns None. Before Phase 261 that died on `.get` with a raw traceback and
        lost the claim — measured at 4-5 of 100 concurrent trials."""
        (repo / "tasks" / "index.yml").write_text("")
        r = subprocess.run(["bash", "-c", _step_4a_script("TECH-0001")],
                           cwd=str(repo), capture_output=True, text=True)
        assert r.returncode != 0
        assert "read as empty" in r.stderr, r.stderr
        assert "AttributeError" not in r.stderr, \
            "the empty read still crashes instead of refusing"

    def test_the_flip_is_written_atomically_and_leaves_no_temp_file(self, repo):
        """`os.replace`, not a truncate in place.

        The behavioural difference — that a concurrent READER never sees a
        zero-length file — is only observable under concurrency, and the shipped
        suite cannot make it deterministic. What it CAN pin is that the write goes
        through a temp file and lands by replace, and that no `.tmp` residue is
        left behind; the concurrency half is measured by the maintainer harness.
        """
        r = subprocess.run(["bash", "-c", _step_4a_script("TECH-0001")],
                           cwd=str(repo), capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        import yaml
        data = yaml.safe_load((repo / "tasks" / "index.yml").read_text())
        got = {t["id"]: t["status"] for t in data["tasks"]}
        assert got["TECH-0001"] == "in_progress"
        assert got["TECH-0002"] == "open", "the flip touched a task it was not given"
        leftovers = list((repo / "tasks").glob("index.yml.*"))
        assert leftovers == [], f"temp-file residue left beside the index: {leftovers}"

    def test_the_write_does_not_truncate_in_place(self):
        """The source half of the case above, scoped to the extracted block so a
        sentence about `os.replace` in the prose cannot satisfy it."""
        block = _step_4a_script("TECH-0001")
        assert "os.replace(tmp, real)" in block
        assert 'index_path.open("w"' not in block, \
            "Step 4a truncates the index in place again — every concurrent reader " \
            "can see a zero-length file"


@needs_interpreter
class TestInterpreterChatter:
    def test_stderr_noise_does_not_become_a_false_failure(self, repo):
        """`CC_OUT=$(... 2>&1)` folds any interpreter chatter into the capture.
        Matching the WHOLE capture against exact tokens reported `Could not update`
        over a flip that had in fact succeeded — found by the round with a
        `sitecustomize.py`, but a DeprecationWarning or a `.pth` print does it too.
        The sentinel is read off the last line; the chatter is surfaced, not
        swallowed (Phase 135: a silent abort and a clean run must not look alike).
        """
        site = repo / "sitecustomize.py"
        site.write_text("import sys; print('chatter from a site hook', file=sys.stderr)\n")
        r = subprocess.run(
            ["bash", "sysop/scripts/claim_task.sh", "--commit-claim", "TECH-0001"],
            cwd=str(repo), capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(repo)})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Could not update" not in r.stderr, \
            "chatter on stderr was read as a failure:\n" + r.stdout + r.stderr
        assert _status_at_head(repo, "TECH-0001") == "in_progress"
        assert "chatter from a site hook" in r.stderr, \
            "the chatter was swallowed; a silent abort must not look like a clean run"


def _commit_claim_source():
    """The `--commit-claim` block only — scoped so a match cannot drift into
    `--release` below it, which since Phase 261's round has a near-identical write."""
    import re as _re
    text = CLAIM_TASK.read_text(encoding="utf-8")
    m = _re.search(r"^if \$COMMIT_CLAIM; then$(.*?)^fi$", text, _re.M | _re.S)
    assert m, "the --commit-claim block is gone from claim_task.sh entirely"
    return m.group(1)


def _release_source():
    import re as _re
    text = CLAIM_TASK.read_text(encoding="utf-8")
    m = _re.search(r"^if \$RELEASE; then$(.*?)^fi$", text, _re.M | _re.S)
    assert m, "the --release block is gone from claim_task.sh entirely"
    return m.group(1)


class TestEveryIndexWriterInThisScriptIsAtomic:
    """Phase 261's round found the atomicity of `--commit-claim`'s OWN write pinned
    by nothing: swapping `mkstemp` + `os.replace` for `open(path, "w")` left the
    whole suite green, and a concurrent reader polling the file during the write
    observed a zero-length window — the exact torn read this phase measured as
    costing 4-5 of 100 trials. The `--release` writer had the same hole.

    Behavioural atomicity cannot be made deterministic in-process, so these pin the
    shape: the temp file, the replace, the absence of a truncate, and — separately,
    because a fixed name re-opens `Q-382`'s collision class with `os.replace` still
    present — that the temp name comes from `mkstemp`.
    """

    @pytest.mark.parametrize("name,block", [
        ("--commit-claim", _commit_claim_source),
        ("--release", _release_source),
    ])
    def test_the_writer_replaces_rather_than_truncates(self, name, block):
        src = block()
        assert "os.replace(" in src, f"{name} no longer lands its write by os.replace"
        assert 'open(index_path, "w"' not in src and 'open(_real, "w"' not in src, \
            f"{name} truncates the index in place again"

    @pytest.mark.parametrize("name,block", [
        ("--commit-claim", _commit_claim_source),
        ("--release", _release_source),
    ])
    def test_the_temp_name_is_minted_not_derived(self, name, block):
        """`Q-382`: a fixed `<path>.tmp` collides between two concurrent writers and
        clobbers a pre-existing file of that name. `os.replace` being present says
        nothing about this."""
        src = block()
        assert "tempfile.mkstemp(" in src, \
            f"{name} builds its temp path instead of minting it — Q-382's class"
        assert '+ ".tmp"' not in src, \
            f"{name} derives a fixed temp name from the index path"

    @pytest.mark.parametrize("name,block", [
        ("--commit-claim", _commit_claim_source),
        ("--release", _release_source),
    ])
    def test_the_write_follows_a_symlink_and_keeps_the_mode(self, name, block):
        """Two properties `write_text` had for free and `os.replace` does not: it
        writes THROUGH a symlink rather than replacing it, and it preserves the mode.
        Dropping either is silent — the mode change turns 0644 into 0600."""
        src = block()
        assert "os.path.realpath(" in src, \
            f"{name} lost realpath; a symlinked index becomes a regular file and the " \
            "real target keeps the old status"
        assert "os.chmod(" in src, f"{name} lost the mode carry-over"


class TestStep4aIsAtomicToo:
    def test_the_temp_name_is_minted_not_derived(self):
        block = _step_4a_script("TECH-0001")
        assert "tempfile.mkstemp(" in block
        assert '+ ".tmp"' not in block

    def test_it_follows_a_symlink_and_keeps_the_mode(self):
        block = _step_4a_script("TECH-0001")
        assert "os.path.realpath(" in block
        assert "os.chmod(" in block


@needs_interpreter
class TestStep4aSymlinkBehaviour:
    def test_a_symlinked_index_is_flipped_through_not_replaced(self, tmp_path):
        """Behavioural, not shape: drop `realpath` and this is what breaks — the
        symlink becomes a regular file and the real target is never flipped."""
        repo = _build_repo(tmp_path)
        real = repo / "data" / "index.yml"
        real.parent.mkdir()
        (repo / "tasks" / "index.yml").rename(real)
        (repo / "tasks" / "index.yml").symlink_to(Path("..") / "data" / "index.yml")
        r = subprocess.run(["bash", "-c", _step_4a_script("TECH-0001")],
                           cwd=str(repo), capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert (repo / "tasks" / "index.yml").is_symlink(), \
            "the symlink was replaced by a regular file"
        assert "in_progress" in real.read_text(), "the real target was never flipped"


@needs_interpreter
class TestFromALinkedWorktree:
    """`SKILL.md` Step 4d states the script resolves the primary checkout itself, so
    it commits main-side wherever it is invoked from. Phase 261's round found NO test
    invoked it from a worktree — so swapping `--git-common-dir` for `--show-toplevel`
    (`Q-234`'s exact defect, which the code comment claims to avoid) survived.
    """

    def test_a_claim_run_from_a_worktree_commits_in_the_primary_checkout(self, repo):
        wt = repo.parent / "wt"
        _git(repo, "worktree", "add", "-q", str(wt), "-b", "feature/x")
        r = subprocess.run(
            ["bash", str(repo / "sysop/scripts/claim_task.sh"),
             "--commit-claim", "TECH-0001"],
            cwd=str(wt), capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        # Committed in the PRIMARY checkout, on its branch, not the worktree's.
        assert _status_at_head(repo, "TECH-0001") == "in_progress"
        assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"

    def test_rule_a_reads_the_primary_checkouts_head_not_the_worktrees(self, repo):
        """The worktree is on `feature/x`. If Rule A read the caller's HEAD instead of
        the primary checkout's, this legitimate claim would be refused."""
        wt = repo.parent / "wt2"
        _git(repo, "worktree", "add", "-q", str(wt), "-b", "feature/y")
        r = subprocess.run(
            ["bash", str(repo / "sysop/scripts/claim_task.sh"),
             "--commit-claim", "TECH-0002"],
            cwd=str(wt), capture_output=True, text=True)
        assert r.returncode == 0, \
            "a claim from a worktree was refused by Rule A:\n" + r.stdout + r.stderr
        assert "STOP" not in r.stderr


@needs_interpreter
class TestReleaseTakesTheMutexToo:
    """Half this phase's shipped behaviour change. The round deleted the acquire and
    both traps from the `--release` block and the ENTIRE suite stayed green."""

    def test_release_refuses_while_the_mutex_is_held(self, repo):
        _git(repo, "worktree", "add", "-q", str(repo.parent / "wtr"), "-b", "tech/r")
        lock_dir = repo / "sysop" / "runtime" / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        (lock_dir / "TECH-0001.lock").write_text(
            f"task: TECH-0001\nbranch: tech/r\nworkspace: {repo.parent / 'wtr'}\nmode: worktree\n")
        m = _mutex(repo)
        m.write_text("holder_pid: 999999\nholder: batch_work.sh\nwhat: Batch 3\n")
        r = subprocess.run(
            ["bash", "sysop/scripts/claim_task.sh", "--release", "TECH-0001"],
            cwd=str(repo), capture_output=True, text=True,
            env={**os.environ, "SYSOP_TRACKER_LOCK_WAIT": "1"})
        assert r.returncode != 0, \
            "--release ran while the tracker mutex was held:\n" + r.stdout + r.stderr
        assert (lock_dir / "TECH-0001.lock").exists(), "the claim was released anyway"
        assert m.exists(), "the refusal broke the lock it refused on"

    def test_release_does_not_leave_the_mutex_behind(self, repo):
        _git(repo, "worktree", "add", "-q", str(repo.parent / "wtr2"), "-b", "tech/r2")
        lock_dir = repo / "sysop" / "runtime" / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        (lock_dir / "TECH-0001.lock").write_text(
            f"task: TECH-0001\nbranch: tech/r2\nworkspace: {repo.parent / 'wtr2'}\nmode: worktree\n")
        subprocess.run(["bash", "sysop/scripts/claim_task.sh", "--release", "TECH-0001"],
                       cwd=str(repo), capture_output=True, text=True)
        assert not _mutex(repo).exists(), "--release leaked the tracker mutex"


@needs_interpreter
class TestRefusalsThatFailOpenIfDeleted:
    def test_a_trailing_flag_is_refused_not_ignored(self, repo):
        r = _commit_claim(repo, "TECH-0001")  # sanity: the normal form works
        assert r.returncode == 0
        r = subprocess.run(
            ["bash", "sysop/scripts/claim_task.sh", "--commit-claim", "TECH-0002", "--force"],
            cwd=str(repo), capture_output=True, text=True)
        assert r.returncode != 0, \
            "a trailing flag was silently ignored and the claim proceeded"
        assert "Flags must come before" in r.stderr
        assert _status_at_head(repo, "TECH-0002") == "open"

    def test_a_missing_index_is_refused_in_words(self, repo):
        (repo / "tasks" / "index.yml").unlink()
        r = _commit_claim(repo, "TECH-0001")
        assert r.returncode != 0
        assert "no task index" in r.stderr or "not found" in r.stderr
        assert "Traceback" not in r.stderr

    def test_an_empty_index_is_refused_as_empty_not_as_a_missing_task(self, repo):
        """`safe_load(f) or {}` reported a mid-truncate read as NOT_FOUND — the exact
        misdiagnosis this phase exists to remove, in the code written to remove it."""
        (repo / "tasks" / "index.yml").write_text("")
        r = _commit_claim(repo, "TECH-0001")
        assert r.returncode != 0
        assert "read as empty" in r.stderr, r.stderr
        assert "not found" not in r.stderr

    def test_a_batch_id_is_routed_to_its_owner(self, repo):
        r = _commit_claim(repo, "BATCH-3")
        assert r.returncode != 0
        assert "batch_work.sh 3" in r.stderr, \
            "the batch refusal lost its routing hint to the script that owns both halves"
