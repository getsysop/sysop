"""A review batch whose branch a `direct` close merged and then stopped before Step 4b.

`/review-close` Step 4a merges onto `main`; a `4a-post` failure under `direct` stops
there and leaves the merges on local `main`, so `close_batch.sh` never marks the batch
`Merged`. The header still reads `In Progress`, the lock is kept, the branch is 0
commits ahead and its doc sits in the main checkout. `/sitrep` read that as `in progress
— continue work; 0 of N tasks have Doc-Work trailers yet`, the misroute `Q-643` fixed
for tasks. A re-run close does not reliably close the batch (its Step 2a reviews an
empty diff), so the route is `close_batch.sh <N>` first, then `/review-close`.

The batch twin reuses the task path's state, `merged, close pending`, and its detector,
`_merged_into_default`. Runs below use the shipped scripts step by step.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import sitrep_survey as ss

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
SITREP_MD = REPO_ROOT / "core" / "skills" / "sitrep" / "SKILL.md"
ROADMAP_MD = REPO_ROOT / "core" / "skills" / "roadmap" / "SKILL.md"
BRANCH = "review/batch-7"
MERGED = "merged, close pending"


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                        "WORKTREE_ROOT", "WORKTREE_PREFIX")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"
    return env


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    r = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, env=_env())
    assert r.returncode == 0, (args, r.stdout + r.stderr)
    return r


def _git(cwd: Path, *args: str) -> str:
    return _run(cwd, "git", *args).stdout.strip()


def _claimed(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / ".gitignore").write_text("sysop/runtime/\n", encoding="utf-8")
    (root / "review_tasks.md").write_text(
        "# Review Tasks\n\n### Batch 7 — Batch seven `Pending`\n\n"
        f"> **Branch:** `{BRANCH}`\n\n- [ ] **TASK-0007**: a fix\n\n## Statistics\n",
        encoding="utf-8")
    (root / "tasks").mkdir()
    (root / "tasks" / "index.yml").write_text(
        "schema_version: 2\nphases:\n"
        "  - {number: 1, title: P, status: in_progress, current_focus: true}\ntasks: []\n",
        encoding="utf-8")
    scripts = root / "sysop" / "scripts"
    scripts.mkdir(parents=True)
    for p in list(SCRIPTS.glob("*.py")) + list(SCRIPTS.glob("*.sh")):
        (scripts / p.name).write_bytes(p.read_bytes())
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    _run(root, "bash", "sysop/scripts/batch_work.sh", "7")
    return root, tmp_path / "proj-batch-7"


def _stopped(tmp_path: Path, merge: str, hold: bool) -> Path:
    """A `direct` close that ran Steps 3b and 4a and stopped at `4a-post`."""
    root, ws = _claimed(tmp_path)
    (ws / "fix.txt").write_text("fix", encoding="utf-8")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-qm", "fix", "-m", "Doc-Work: TASK-0007")
    doc = ws / "sysop" / "runtime" / "pending-docs" / "review-batch-7.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(f"---\nbranch: {BRANCH}\nbranch_tip: {_git(ws, 'rev-parse', 'HEAD')}\n"
                   "date: 2026-11-09\ntype: fix\nroadmap_ids: []\n"
                   'review_task_ids: [TASK-0007]\nsummary: "s"\n'
                   + ('hold: "a human check is outstanding"\n' if hold else "")
                   + "---\nbody\n", encoding="utf-8")
    _run(root, sys.executable, "sysop/scripts/pending_doc_collect.py", "collect", str(ws), BRANCH)
    _git(root, "worktree", "remove", str(ws))
    if merge == "no-ff":  # Step 4a item 2, published arm
        _git(root, "merge", "-q", "--no-ff", "-m", f"Merge {BRANCH}", BRANCH)
    else:  # Step 4a item 2, local-only arm: rebase, then fast-forward
        _git(root, "checkout", "-q", BRANCH)
        _git(root, "rebase", "-q", "main")
        _git(root, "checkout", "-q", "main")
        _git(root, "merge", "-q", "--ff-only", f"refs/heads/{BRANCH}")
    assert "`In Progress`" in (root / "review_tasks.md").read_text(encoding="utf-8")
    assert (root / "sysop" / "runtime" / "locks" / "BATCH-7.lock").exists()
    assert _git(root, "rev-list", "--count", f"main..{BRANCH}") == "0"
    return root


def _survey(root: Path) -> dict:
    return json.loads(_run(root, sys.executable, "sysop/scripts/sitrep_survey.py",
                           "--json").stdout)


def _batch(got: dict) -> dict:
    hits = [b for b in got["review_batches"] if b["batch_number"] == 7]
    assert len(hits) == 1, got["review_batches"]
    return hits[0]


CLOSE = "bash sysop/scripts/close_batch.sh 7 (from the main checkout, on main)"


@pytest.mark.parametrize("merge", ["no-ff", "rebase"])
def test_a_batch_merged_by_a_stopped_close_routes_to_close_batch(tmp_path, merge):
    root = _stopped(tmp_path, merge, hold=False)
    got = _survey(root)
    rb = _batch(got)
    assert rb["state"] == MERGED, rb
    assert rb["next_action"] == f"{CLOSE}, then /review-close", rb
    assert any("review-batch-7.md" in n and "main" in n for n in rb["notes"]), rb["notes"]
    assert got["recommended_next"]["command"] == rb["next_action"], got["recommended_next"]
    assert "Batch 7" in got["recommended_next"]["reason"]
    assert any(line.startswith("Batch 7: merged by a previous close") and CLOSE in line
               for line in got["suggested_order"]), got["suggested_order"]


def test_a_held_doc_puts_the_hold_step_between_close_batch_and_the_close(tmp_path):
    root = _stopped(tmp_path, "rebase", hold=True)
    rb = _batch(_survey(root))
    assert rb["state"] == MERGED, rb
    assert rb["next_action"] == (
        f"{CLOSE}; then finish what its pending doc's `hold:` names, then python3 "
        f"sysop/scripts/pending_doc_hold.py clear {BRANCH}, and /review-close"), rb
    assert any("hold: a human check is outstanding" in n for n in rb["notes"]), rb["notes"]


@pytest.mark.parametrize("hold", [False, True])
def test_running_the_route_s_close_batch_hands_over_to_the_kept_branch_arm(tmp_path, hold):
    """`close_batch.sh 7`, as the route names it, marks the batch `Merged` and drops the
    lock; the batch leaves the review set and the kept-branch discrepancy routes the rest
    (whose own route is the remainder of this one)."""
    root = _stopped(tmp_path, "rebase", hold=hold)
    before = _batch(_survey(root))["next_action"]
    _run(root, "bash", "sysop/scripts/close_batch.sh", "7")
    got = _survey(root)
    assert got["review_batches"] == [], got["review_batches"]
    kept = [d for d in got["discrepancies"] if d["kind"] == "branch kept for a pending doc"]
    assert len(kept) == 1, got["discrepancies"]
    assert got["recommended_next"]["command"] == kept[0]["suggestion"]
    assert before.endswith(kept[0]["suggestion"]), (before, kept[0]["suggestion"])


def test_a_claimed_batch_with_no_commits_and_no_doc_reads_as_today(tmp_path):
    root, _ws = _claimed(tmp_path)
    rb = _batch(_survey(root))
    assert rb["state"] == "in progress", rb
    assert rb["next_action"] == "continue work; 0 of 1 tasks have Doc-Work trailers yet"


# ── the skills ───────────────────────────────────────────────────────────


def test_the_sitrep_cascade_has_the_batch_row():
    rows = [ln for ln in SITREP_MD.read_text(encoding="utf-8").splitlines()
            if ln.startswith("| 3c ")]
    assert any("review batch" in ln and f"`{MERGED}`" in ln and "close_batch.sh" in ln
               for ln in rows), rows


def test_the_roadmap_has_the_state_and_its_actuator():
    text = ROADMAP_MD.read_text(encoding="utf-8")
    actuator = [ln for ln in text.splitlines() if ln.startswith(f"| `{MERGED}` |")]
    assert len(actuator) == 1 and "close_batch.sh" in actuator[0], actuator
