"""`Q-276` (`claim_task.sh --clone`) and `Q-243` (flag position), Phase 220.

Both are bash-substrate defects that only reproduce by RUNNING the scripts.
`Q-276` in particular was filed by execution rather than by reading, and its
second shape — the one that exits 0 — was found the same way. Every test here
drives the real script against a real git repository with a real bare `origin`.
"""
import os
import subprocess
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
CLAIM_TASK = SCRIPTS / "claim_task.sh"


def _imports_yaml(interpreter):
    return subprocess.run(
        [str(interpreter), "-c", "import yaml"], capture_output=True
    ).returncode == 0


def _usable_venv_dir(root=None):
    """The venv `resolve_yaml_python()` would actually resolve under `root`, or None.

    `root` defaults to this repo and is a parameter ONLY so the shapes this
    predicate exists to distinguish can be BUILT and asserted against
    (`tests/test_venv_predicate_shapes.py`). Phase 226's round showed why that
    matters: deleting any one of the three conditions below — the file test, the
    executability test, the yaml import — left the entire suite green, because
    nothing anywhere executed this function against a venv it could inspect.

    It asks what the script asks, in the script's order — `<root>/.venv/bin`
    then `<root>/venv/bin` — accepting a candidate only when its `python3` is
    **executable** and **imports yaml**. `claim_task.sh` `continue`s past a
    candidate that fails either test and falls through to the PATH probe.

    **Phase 225's version asked a different question, and failed in the unsafe
    direction:** it returned True on the mere existence of a `.venv`
    *directory*. On a tree whose venv is empty, half-built, stale,
    non-executable, Windows-layout (`Scripts/`, no `bin/`) or simply yaml-less,
    the script refuses while the predicate says "reachable" — so the two
    release tests below FAIL rather than skip, which is the exact defect
    `Q-286` filed and that fix was believed to have closed. The
    skip-and-fall-through behaviour it should have mirrored was already pinned
    one module over, by
    `test_claim_task_venv_python.py::test_a_non_executable_venv_python3_is_skipped`,
    since Phase 182; nothing connected the two.

    Returning the *directory* rather than a bool is what lets `_repo` provision
    the fixture from the same answer, so the fixture and the skip can no longer
    disagree about whether an interpreter is reachable.
    """
    base = REPO_ROOT if root is None else Path(root)
    for name in (".venv", "venv"):
        py = base / name / "bin" / "python3"
        if py.is_file() and os.access(py, os.X_OK) and _imports_yaml(py):
            return base / name
    return None


def _a_pyyaml_interpreter_is_reachable(root=None):
    """Can `claim_task.sh --release` find an interpreter that imports yaml?

    The venv candidates first, then bare `python3` — the script's own order.

    **Why it has to be asked.** `_repo` provisions the fixture's `.venv` from
    this repo's, and without a usable one the release path hits the "no
    interpreter" refusal instead of releasing, so the two release tests below
    assert against a refusal they were not written for. That has been true
    since Phase 220.

    **What that costs, stated accurately.** The failing population is a
    developer machine or a tester's clone with no usable project venv *and* a
    PATH `python3` that cannot import yaml. It is **not** CI, which installs
    `pyyaml` from `requirements-dev.txt` into the interpreter bare `python3`
    resolves to, and which has been green on every phase since these tests
    landed. An earlier version of this docstring claimed the pair "would have
    gone red on the public snapshot's required `pytest` check, in public, at
    the push". Phase 225's own round disproved that; the correction reached
    `PHASE_LOG.md` and the queue entry but not this file — and this file ships,
    so the retracted claim was queued to become public at the next cut.

    A skip here is honest and a red is not: these tests assert what `--release`
    does when it CAN flip `tasks/index.yml`, and an environment where nothing
    can is not a counter-example to that. The refusal path itself is covered by
    execution, hermetically, in `tests/test_claim_task_venv_python.py`, so
    skipping here loses no coverage of the refusal.
    """
    if _usable_venv_dir(root) is not None:
        return True
    probe = shutil.which("python3")
    return probe is not None and _imports_yaml(Path(probe))


needs_pyyaml = pytest.mark.skipif(
    not _a_pyyaml_interpreter_is_reachable(),
    reason="claim_task.sh --release needs an interpreter with PyYAML to flip "
           "tasks/index.yml; none is reachable here (no usable venv, and "
           "python3 on PATH cannot import yaml)",
)
BATCH_WORK = SCRIPTS / "batch_work.sh"

TRACKER = (
    "# Review Tasks\n\n"
    "## Round 1: R (2026-08-21)\n\n"
    "### Batch 9 — Demo `Pending`\n\n"
    "> **Branch:** `review/nine`\n\n"
    "- [ ] **TASK-1**: a\n\n"
    "## Statistics\n\nTrailing.\n"
)

FENCED_TRACKER = TRACKER.replace(
    "## Statistics", "```\n### Batch 99 — fenced example `Pending`\n\n## Statistics")


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root: Path, *, task_id: str | None = None, tracker: str = TRACKER,
          origin: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "review_tasks.md").write_text(tracker)
    (root / "README.md").write_text("# seed\n")
    sd = root / "sysop" / "scripts"
    sd.mkdir(parents=True, exist_ok=True)
    for n in ("review_index.py", "_log.py"):
        s = SCRIPTS / n
        if s.exists():
            shutil.copy(s, sd / n)
    if task_id:
        (root / "tasks").mkdir(exist_ok=True)
        (root / "tasks" / "index.yml").write_text(
            f"tasks:\n  - id: {task_id}\n    title: Demo\n    status: open\n"
            f"    priority: high\n    effort: S\n    blast_radius: local\n")
    (root / ".gitignore").write_text(
        ".claude/review_index.json\nsysop/runtime/\n.venv\n")
    # `claim_task.sh` resolves PyYAML through `<repo>/.venv/bin/python3` before
    # falling back to PATH. The release path needs it to flip index.yml status,
    # and stock /usr/bin/python3 has no PyYAML — so a fixture without this
    # exercises the "no interpreter" refusal rather than the release.
    # Provisioned from the same answer `needs_pyyaml` skips on, so the fixture
    # and the skip cannot disagree. Symlinking a venv the script would REJECT
    # (non-executable, yaml-less, no `bin/`) is worse than symlinking none: it
    # makes these tests FAIL where they would otherwise have skipped, which is
    # the `Q-286` defect arriving through the fixture instead of the predicate.
    _venv = _usable_venv_dir()
    if _venv is not None:
        (root / ".venv").symlink_to(_venv)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    if origin:
        bare = root.parent / f"{root.name}-origin.git"
        # `-c init.defaultBranch=main`, like the working repo above. Without it
        # the bare repo's HEAD follows the RUNNER's git default — `main` on this
        # machine, `master` on CI — so a clone of it lands on `master` and every
        # assertion about the starting branch fails only in CI.
        subprocess.run(["git", "-c", "init.defaultBranch=main",
                        "init", "--bare", "-q", str(bare)],
                       check=True, capture_output=True)
        _git(root, "remote", "add", "origin", str(bare))
        _git(root, "push", "-q", "origin", "main")
    return root


def _run(script: Path, cwd: Path, *args):
    return subprocess.run(["bash", str(script), *args], cwd=str(cwd),
                          capture_output=True, text=True)


def _branch_of(d: Path) -> str:
    return subprocess.run(["git", "branch", "--show-current"], cwd=str(d),
                          capture_output=True, text=True).stdout.strip()


# ── Q-276 ──────────────────────────────────────────────────────────────

def test_clone_mode_works_on_its_documented_invocation(tmp_path):
    """The filed defect: the branch was created LOCALLY and never pushed, so
    `git checkout` inside the fresh clone failed with `pathspec ... did not
    match` and `set -euo pipefail` exited 1 — after creating the branch and the
    clone directory, before the lock block. The documented form could not work.

    Asserts the END STATE, not the exit code alone: a clone on the right branch
    and a lock that records it."""
    r = _repo(tmp_path / "w", task_id="FEAT-0001")
    out = _run(CLAIM_TASK, r, "--clone", "--lock", "FEAT-0001", "feat/demo")
    assert out.returncode == 0, (out.stdout + out.stderr)

    clone = r.parent / f"{r.name}-feat-0001"
    assert clone.is_dir()
    assert _branch_of(clone) == "feat/demo"

    lock = r / "sysop/runtime/locks/FEAT-0001.lock"
    assert lock.is_file()
    body = lock.read_text()
    assert "mode: clone" in body
    assert "branch: feat/demo" in body


def test_clone_mode_publishes_the_branch(tmp_path):
    """`--clone` builds its workspace from `origin`, so a branch that exists
    only locally cannot be cloned by definition. Stated as its own assertion
    because it is a real behaviour change: the branch is now PUBLISHED, which
    routes `/review-close` Step 4a to its published (`--no-ff`) arm."""
    r = _repo(tmp_path / "w", task_id="FEAT-0001")
    _run(CLAIM_TASK, r, "--clone", "--lock", "FEAT-0001", "feat/demo")
    remote = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", "feat/demo"],
        cwd=str(r), capture_output=True, text=True).stdout
    assert "refs/heads/feat/demo" in remote


def test_an_existing_clone_on_the_wrong_branch_is_corrected(tmp_path):
    """**The second shape, and the worse one — it exited 0.**

    With the clone directory already present the block short-circuited on
    "already exists" and checked nothing out, so the script printed its success
    banners and wrote a lock naming `branch:` and `workspace:` while the clone
    sat on `main`. `/review-close` Step 0 arm (ii) resolves exactly that lock and
    Step 3b collects from it.

    A push-before-clone fix alone is INERT here — the short-circuit returns
    before the clone block ever runs — which is why the entry's single
    prescribed remedy would have covered only half its own subject."""
    r = _repo(tmp_path / "w", task_id="FEAT-0002")
    pre = r.parent / f"{r.name}-feat-0002"
    subprocess.run(
        ["git", "clone", "-q", str(r.parent / f"{r.name}-origin.git"), str(pre)],
        check=True, capture_output=True)
    assert _branch_of(pre) == "main", "fixture must start on the wrong branch"

    out = _run(CLAIM_TASK, r, "--clone", "--lock", "FEAT-0002", "feat/two")

    assert out.returncode == 0, (out.stdout + out.stderr)
    assert _branch_of(pre) == "feat/two", (
        "the workspace the lock names is still on the wrong branch"
    )


def test_an_existing_non_repo_directory_is_refused_without_a_lock(tmp_path):
    """Refuse rather than record. A lock naming a workspace that is not a
    checkout sends Step 3b somewhere it cannot collect from, and the operator is
    told to start working there."""
    r = _repo(tmp_path / "w", task_id="FEAT-0003")
    junk = r.parent / f"{r.name}-feat-0003"
    junk.mkdir(parents=True)
    (junk / "junk.txt").write_text("x")

    out = _run(CLAIM_TASK, r, "--clone", "--lock", "FEAT-0003", "feat/three")

    assert out.returncode == 1
    assert "not a git repository" in (out.stdout + out.stderr)
    assert not (r / "sysop/runtime/locks/FEAT-0003.lock").exists(), (
        "a refusal that still writes the lock is not a refusal"
    )


def test_clone_mode_refuses_cleanly_with_no_origin(tmp_path):
    r = _repo(tmp_path / "w", task_id="FEAT-0004", origin=False)
    out = _run(CLAIM_TASK, r, "--clone", "--lock", "FEAT-0004", "feat/four")
    assert out.returncode == 1
    assert "No 'origin' remote" in (out.stdout + out.stderr)


def test_worktree_mode_is_unaffected(tmp_path):
    """The control: `--worktree` needs no remote and must not have acquired a
    push."""
    r = _repo(tmp_path / "w", task_id="FEAT-0005", origin=False)
    out = _run(CLAIM_TASK, r, "--worktree", "--lock", "FEAT-0005", "feat/five")
    assert out.returncode == 0, (out.stdout + out.stderr)
    wt = r.parent / f"{r.name}-feat-0005"
    assert _branch_of(wt) == "feat/five"


# ── Q-243 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("args", [
    ("9", "--allow-open-fence"),
    ("--release", "9", "--allow-open-fence"),
    ("9", "--force"),
    ("--release", "9", "--force"),
])
def test_a_trailing_flag_is_refused_as_a_flag_order_error(tmp_path, args):
    """The filed defect: the fence pre-scan matched `--allow-open-fence`
    ANYWHERE in argv, so the escape's "proceeding under ..." banner printed and
    the script only then exited 1 with "Flags must come before". Nothing was
    written, so the cost was a reader who believes an escape took effect.

    The fix stops the pre-scan at the first non-flag argument — which MOVED the
    diagnosis: with the trailing flag no longer scanned, an open-fenced tracker
    exits on the fence and tells the operator to close a fence when their actual
    mistake was flag placement. So the ordering refusal is hoisted ahead of the
    fence gate. This asserts the operator gets the accurate message."""
    r = _repo(tmp_path / "w", tracker=FENCED_TRACKER)
    out = _run(BATCH_WORK, r, *args)
    both = out.stdout + out.stderr
    assert out.returncode == 1
    assert "Flags must come before" in both
    assert "proceeding under" not in both, (
        "the escape banner printed for a flag the parser rejects"
    )
    # **This is the assertion that makes the hoist observable.** On a CLEAN
    # tracker the original in-place ordering check further down catches the same
    # invocation identically, so "the flag message is present" passes whether or
    # not the hoisted refusal did anything. On a FENCED tracker it does not: if
    # the hoisted refusal is disabled, execution reaches the fence gate and the
    # operator is told to close a fence when their mistake was flag placement.
    assert "unterminated" not in both.lower(), (
        "the fence gate answered a flag-placement mistake — the hoisted "
        "ordering refusal did not fire"
    )


def test_the_leading_flag_form_still_takes_the_escape(tmp_path):
    """The documented invocation must keep working — a fix that disables the
    escape is not a fix."""
    r = _repo(tmp_path / "w", tracker=FENCED_TRACKER)
    out = _run(BATCH_WORK, r, "--allow-open-fence", "9")
    both = out.stdout + out.stderr
    assert "proceeding under" in both
    assert "Flags must come before" not in both


def test_an_open_fence_with_no_flag_still_refuses_on_the_fence(tmp_path):
    """The ordering refusal must not shadow the fence gate for an invocation
    that has no flag-order problem."""
    r = _repo(tmp_path / "w", tracker=FENCED_TRACKER)
    out = _run(BATCH_WORK, r, "9")
    both = (out.stdout + out.stderr).lower()
    assert out.returncode == 1
    assert "fence" in both
    assert "flags must come before" not in both


def test_the_batch_id_form_is_not_read_as_a_flag(tmp_path):
    """`BATCH-9` is a positional, not a flag. If the pre-scan's stop condition
    were written as "starts with a letter" or similar, this would break."""
    r = _repo(tmp_path / "w")
    out = _run(BATCH_WORK, r, "BATCH-9")
    assert "Flags must come before" not in (out.stdout + out.stderr)


def test_a_trailing_flag_refuses_before_anything_is_written(tmp_path):
    """**Guard gap found by this phase's own battery (D25).**

    The parametrized test above asserts rc==1 and the message — and both survive
    `refuse_trailing_flags` being changed to `return 0`, because on a FENCED
    tracker the fence gate exits 1 a few lines later and the message has already
    been echoed. The test could not tell which refusal fired.

    A CLEAN tracker removes the second refusal, so the only thing that can stop
    the run is the one under test. Asserts on WRITES, not on output."""
    r = _repo(tmp_path / "w")           # no open fence
    out = _run(BATCH_WORK, r, "9", "--force")

    assert out.returncode == 1
    assert "Flags must come before" in (out.stdout + out.stderr)
    locks = r / "sysop" / "runtime" / "locks"
    assert not locks.exists() or not list(locks.glob("BATCH-*.lock")), (
        "the batch was claimed despite the refusal"
    )
    assert "`In Progress`" not in (r / "review_tasks.md").read_text(), (
        "the tracker was mutated despite the refusal"
    )


def test_a_clean_tracker_with_a_leading_flag_still_claims(tmp_path):
    """Non-vacuity for the test above: the same tracker DOES claim when the flag
    is where the parser wants it. Without this, the assertion that nothing was
    written would pass against a script that never claims anything."""
    r = _repo(tmp_path / "w")
    out = _run(BATCH_WORK, r, "--force", "9")
    assert out.returncode == 0, (out.stdout + out.stderr)
    assert "`In Progress`" in (r / "review_tasks.md").read_text()


def test_the_non_repo_refusal_is_the_one_that_fires(tmp_path):
    """**Guard gap found by the battery (D29).**

    `test_an_existing_non_repo_directory_is_refused_without_a_lock` asserts
    rc==1, the message, and no lock — and all three survive deleting that arm's
    `exit 1`, because execution falls through to the checkout arm which refuses
    for a different reason. Two refusals, one indistinguishable outcome.

    Distinguish them: the SECOND refusal's text must be absent."""
    r = _repo(tmp_path / "w", task_id="FEAT-0006")
    junk = r.parent / f"{r.name}-feat-0006"
    junk.mkdir(parents=True)
    (junk / "junk.txt").write_text("x")

    out = _run(CLAIM_TASK, r, "--clone", "--lock", "FEAT-0006", "feat/six")
    both = out.stdout + out.stderr

    assert out.returncode == 1
    assert "not a git repository" in both
    assert "could not be checked out there" not in both, (
        "fell through to the checkout refusal — the non-repo arm did not stop it"
    )


def test_an_existing_clone_that_cannot_reach_the_branch_is_refused(tmp_path):
    """**Guard gap found by the battery (D30): no test reached this arm at all.**

    An existing git repo that is NOT a clone of this origin cannot fetch the
    branch, so the checkout fails. Recording it would write a lock naming a
    workspace on the wrong branch — which is the whole of `Q-276`'s second
    shape, arriving by a different route."""
    r = _repo(tmp_path / "w", task_id="FEAT-0007")
    stranger = r.parent / f"{r.name}-feat-0007"
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(stranger)],
                   check=True, capture_output=True)
    _git(stranger, "config", "user.email", "t@t")
    _git(stranger, "config", "user.name", "t")
    _git(stranger, "config", "commit.gpgsign", "false")
    (stranger / "f.txt").write_text("x")
    _git(stranger, "add", "-A")
    _git(stranger, "commit", "-qm", "unrelated")

    out = _run(CLAIM_TASK, r, "--clone", "--lock", "FEAT-0007", "feat/seven")

    assert out.returncode == 1, (out.stdout + out.stderr)
    assert "could not be checked out there" in (out.stdout + out.stderr)
    assert not (r / "sysop/runtime/locks/FEAT-0007.lock").exists(), (
        "a lock was written naming a workspace on the wrong branch"
    )


@needs_pyyaml
def test_a_clone_claim_can_be_released(tmp_path):
    """**Round finding (MEDIUM): the fix made a lock that could not be released.**

    `--release` unconditionally called `git worktree remove`, which fatals on a
    clone ("is not a working tree") with or without `--force`, leaving the lock
    intact and the claim un-released — the state Phase 91 built `--release` to
    prevent. It was unreachable before, because `--clone` could not complete a
    claim at all; fixing the claim made the release reachable. "A fix in one
    step is a change to every step downstream of it."

    `mode:` had been written by every claim since it existed and read back by
    nothing until this fix."""
    r = _repo(tmp_path / "w", task_id="FEAT-0008")
    claim = _run(CLAIM_TASK, r, "--clone", "--lock", "FEAT-0008", "feat/eight")
    assert claim.returncode == 0, (claim.stdout + claim.stderr)
    lock = r / "sysop/runtime/locks/FEAT-0008.lock"
    assert lock.is_file()
    assert "mode: clone" in lock.read_text()

    rel = _run(CLAIM_TASK, r, "--release", "FEAT-0008")

    assert rel.returncode == 0, (rel.stdout + rel.stderr)
    assert not lock.exists(), "the lock survived the release"
    assert "is not a working tree" not in (rel.stdout + rel.stderr)
    # The clone directory is deliberately NOT deleted — it can hold commits this
    # repository has never seen — but the operator is told so.
    assert (r.parent / f"{r.name}-feat-0008").is_dir()
    assert "rm -rf" in rel.stdout


@needs_pyyaml
def test_a_worktree_claim_still_releases_normally(tmp_path):
    """Non-vacuity for the test above: the mode branch must not have broken the
    path that always worked. A `--worktree` release still removes the worktree."""
    r = _repo(tmp_path / "w", task_id="FEAT-0009", origin=False)
    assert _run(CLAIM_TASK, r, "--worktree", "--lock", "FEAT-0009", "feat/nine").returncode == 0
    wt = r.parent / f"{r.name}-feat-0009"
    assert wt.is_dir()

    rel = _run(CLAIM_TASK, r, "--release", "FEAT-0009")

    assert rel.returncode == 0, (rel.stdout + rel.stderr)
    assert not (r / "sysop/runtime/locks/FEAT-0009.lock").exists()
    assert not wt.is_dir(), "the worktree was not removed"


def test_a_refused_clone_does_not_publish_the_branch(tmp_path):
    """**Round finding (LOW): a refused command left a branch on origin.**

    The push was hoisted above the directory checks, so `--clone` against an
    existing non-git directory pushed the branch and THEN refused. Pre-220 a
    claim never touched origin at all, so this was a new remote-side side effect
    of a command that did nothing locally."""
    r = _repo(tmp_path / "w", task_id="FEAT-0010")
    junk = r.parent / f"{r.name}-feat-0010"
    junk.mkdir(parents=True)
    (junk / "junk.txt").write_text("x")

    out = _run(CLAIM_TASK, r, "--clone", "--lock", "FEAT-0010", "feat/ten")

    assert out.returncode == 1
    remote = subprocess.run(["git", "ls-remote", "--heads", "origin", "feat/ten"],
                            cwd=str(r), capture_output=True, text=True).stdout
    assert "refs/heads/feat/ten" not in remote, (
        "a refused claim published the branch anyway"
    )


def test_clone_refuses_when_origin_has_a_different_branch_of_the_same_name(tmp_path):
    """**Round finding (HIGH): the push probe checked the NAME, not the branch.**

    Reproduced by the round end to end: claim with `--clone`, then
    `--release --delete-branch` — which runs `git branch -D`, deleting the LOCAL
    ref and leaving origin's — then re-claim. The local branch is recreated at
    `main`, origin still carries the abandoned one, the name probe passes, the
    push is skipped, and the clone checks out the ABANDONED commits. The operator
    is told "Start working!" on resurrected work, and `/review-close` Step 0 arm
    (ii) resolves that lock.

    The block already verified-or-refused the DIRECTORY; it assumed for the ref."""
    r = _repo(tmp_path / "w", task_id="FEAT-0011")

    # Put a DIFFERENT commit on origin under the name we are about to claim.
    _git(r, "checkout", "-q", "-b", "feat/eleven")
    (r / "abandoned.txt").write_text("work nobody wants\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "abandoned")
    _git(r, "push", "-q", "origin", "feat/eleven")
    abandoned = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(r),
                               capture_output=True, text=True).stdout.strip()
    _git(r, "checkout", "-q", "main")
    _git(r, "branch", "-D", "feat/eleven")        # exactly what --delete-branch does

    out = _run(CLAIM_TASK, r, "--clone", "--lock", "FEAT-0011", "feat/eleven")

    assert out.returncode == 1, (out.stdout + out.stderr)
    assert "DIFFERENT" in (out.stdout + out.stderr)
    assert not (r / "sysop/runtime/locks/FEAT-0011.lock").exists(), (
        "a lock was written naming a workspace built from abandoned commits"
    )
    clone = r.parent / f"{r.name}-feat-0011"
    if clone.is_dir():
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(clone),
                              capture_output=True, text=True).stdout.strip()
        assert head != abandoned, "the clone checked out the abandoned commit"


def test_clone_still_skips_the_push_when_origin_has_the_SAME_commit(tmp_path):
    """Non-vacuity: the identity check must not turn every re-claim into a
    refusal. An idempotent re-run on an already-pushed branch is legal."""
    r = _repo(tmp_path / "w", task_id="FEAT-0012")
    assert _run(CLAIM_TASK, r, "--clone", "--lock", "FEAT-0012", "feat/twelve").returncode == 0
    (r / "sysop/runtime/locks/FEAT-0012.lock").unlink()

    out = _run(CLAIM_TASK, r, "--clone", "--lock", "FEAT-0012", "feat/twelve")

    assert out.returncode == 0, (out.stdout + out.stderr)
    assert "same commit" in (out.stdout + out.stderr)


def test_the_fixtures_use_the_directory_name_claim_task_actually_creates(tmp_path):
    """**Portability guard, added after CI caught what macOS hid.**

    `claim_task.sh` lower-cases the task id when it builds the sibling workspace
    path (`TASK_LOWER=$(echo "$TASK_ID" | tr '[:upper:]' '[:lower:]')`). Every
    fixture in this module named `<repo>-FEAT-000N` and passed anyway, because
    APFS is case-insensitive — then failed in CI with
    `FileNotFoundError: .../w-FEAT-0005`.

    That is the same class the round found in `_pending_doc_for`'s arm (iii),
    fixed in the product and left here. This asserts the real directory ENTRY,
    so the next fixture written from memory fails on any filesystem."""
    r = _repo(tmp_path / "w", task_id="FEAT-0099")
    assert _run(CLAIM_TASK, r, "--worktree", "--lock",
                "FEAT-0099", "feat/ninetynine").returncode == 0

    names = {p.name for p in r.parent.iterdir() if p.is_dir()}
    assert f"{r.name}-feat-0099" in names, (
        f"claim_task.sh created none of {names} under the expected name"
    )
    assert f"{r.name}-FEAT-0099" not in names


def test_the_bare_origin_defaults_to_main_not_the_runners_default(tmp_path):
    """**Portability guard, added after CI caught what this machine hid.**

    The bare origin was created without `-c init.defaultBranch=main`, so its
    HEAD followed the RUNNER's git default: `main` here, `master` on CI. A clone
    of it therefore landed on `master`, and three assertions about the starting
    branch failed only in CI."""
    r = _repo(tmp_path / "w", task_id="FEAT-0098")
    bare = r.parent / f"{r.name}-origin.git"
    head = subprocess.run(["git", "-C", str(bare), "symbolic-ref", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    assert head == "refs/heads/main", f"bare origin HEAD is {head!r}"
