"""`Q-650`, closed by disposition (Phase 364, on Wade's answer): what already protects the claim path
from another claim's stranded flip, pinned by running it.

`Q-650` filed that `claim_task.sh --commit-claim` commits a dead session's uncommitted `status:
in_progress` along with its own claim. Phase 364 built a refusal, and its round showed the premise
false on both shipped callers:

* **A claim that stopped before its lock** leaves `in_progress` with no lock. The next claim runs
  `validate_tasks.py` before it commits (`/claim-task` 4c, `/auto-build` 5.3), Invariant 9 refuses
  `in_progress` with no lock, and the prescribed rollback (`git checkout tasks/index.yml`)
  discards the stray flip with this claim's own.
* **A claim that stopped after its lock** is committed alongside, and is consistent: the lock is
  on disk, so the validator passes. What it leaves is a held claim with no agent, not drift.

The refusal was reverted. These tests run the validator and the rollback the skills prescribe
against the same fixture as `tests/test_claim_commit_mutex.py`.
"""
from __future__ import annotations

import subprocess

from test_claim_commit_mutex import (  # noqa: F401  (`repo` is a fixture)
    _commit_claim, _git, _status_at_head, needs_interpreter, repo,
)


def _flip(repo, task_id):
    p = repo / "tasks" / "index.yml"
    out, cur = [], None
    for ln in p.read_text().split("\n"):
        s = ln.strip()
        if s.startswith("- id:"):
            cur = s.split(":", 1)[1].strip()
        if s == "status: open" and cur == task_id:
            ln = ln.replace("open", "in_progress")
        out.append(ln)
    p.write_text("\n".join(out))


def _lock(repo, task_id):
    d = repo / "sysop" / "runtime" / "locks"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{task_id}.lock").write_text(f"task_id: {task_id}\nbranch: tech/{task_id.lower()}\n")


def _validate(repo):
    """`/claim-task` Step 4c's command, as written."""
    return subprocess.run(["bash", "-c", "python3 sysop/scripts/validate_tasks.py"], cwd=str(repo),
                          capture_output=True, text=True)


def _lock_errors(repo, task_id):
    """Invariant 9's line for this task. The fixture's index is not schema-complete, so the exit
    status cannot carry the assertion: it is non-zero before any flip."""
    r = _validate(repo)
    return [l for l in (r.stdout + r.stderr).splitlines()
            if f"({task_id})" in l and "status=in_progress but lock file missing" in l]


@needs_interpreter
def test_the_fixture_starts_with_no_lock_error(repo):
    assert _lock_errors(repo, "TECH-0001") == [] and _lock_errors(repo, "TECH-0002") == []


@needs_interpreter
def test_a_lockless_stranded_flip_stops_the_next_claim_at_its_validator(repo):
    _flip(repo, "TECH-0002")                     # a dead session's 4a, no lock
    _flip(repo, "TECH-0001")                     # this claim's 4a
    _lock(repo, "TECH-0001")                     # this claim's 4b
    assert _lock_errors(repo, "TECH-0002"), "4c's validator did not name the stranded flip"
    assert _lock_errors(repo, "TECH-0001") == []     # this claim's own flip is locked


@needs_interpreter
def test_the_prescribed_rollback_discards_the_stray_flip(repo):
    """`/claim-task`'s rollback after a 4c failure is `git checkout tasks/index.yml`."""
    _flip(repo, "TECH-0002")
    _flip(repo, "TECH-0001")
    _git(repo, "checkout", "tasks/index.yml")
    assert "in_progress" not in (repo / "tasks" / "index.yml").read_text()


@needs_interpreter
def test_a_locked_stranded_flip_is_committed_alongside_and_consistent(repo):
    """A claim that died after its lock: the next claim's commit carries its flip, and the
    validator, which reads the lock on disk, stays clean."""
    _flip(repo, "TECH-0002")
    _lock(repo, "TECH-0002")                     # the dead session got as far as 4b
    _flip(repo, "TECH-0001")
    _lock(repo, "TECH-0001")
    assert _lock_errors(repo, "TECH-0002") == []
    r = _commit_claim(repo, "TECH-0001")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _status_at_head(repo, "TECH-0002") == "in_progress"
    assert _lock_errors(repo, "TECH-0002") == []
