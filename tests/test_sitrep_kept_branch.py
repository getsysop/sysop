"""`/sitrep` and a branch a close kept for its pending doc.

A batch close runs `close_batch.sh` (Step 4b: header `Merged`, lock removed) before
Step 4c holds a doc, and Step 6 keeps the branch of every doc still in
`sysop/runtime/pending-docs/`. So a completed close whose batch doc carries `hold:`
leaves a lockless, worktreeless branch beside a `Merged` batch. The orphan-branch arm
advised `git branch -D` for it, which strands the doc (the next close's Step 4c
step 1b stops on a branch that does not resolve), and RECOMMENDED NEXT read idle while
the doc waited on a human. The run below is a `direct` batch close done with the
shipped scripts, step by step.
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
BRANCH = "review/batch-7"
KIND = "branch kept for a pending doc"


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                        "WORKTREE_ROOT", "WORKTREE_PREFIX")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    # The shipped scripts' bare `python3` must find PyYAML, as a consumer's venv gives it.
    env["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{env.get('PATH', '')}"
    return env


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    r = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, env=_env())
    assert r.returncode == 0, (args, r.stdout + r.stderr)
    return r


def _git(cwd: Path, *args: str) -> str:
    return _run(cwd, "git", *args).stdout.strip()


@pytest.fixture
def closed(tmp_path: Path) -> Path:
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
    ws = tmp_path / "proj-batch-7"
    (ws / "fix.txt").write_text("fix", encoding="utf-8")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-qm", "fix", "-m", "Doc-Work: TASK-0007")
    doc = ws / "sysop" / "runtime" / "pending-docs" / "review-batch-7.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(f"---\nbranch: {BRANCH}\nbranch_tip: {_git(ws, 'rev-parse', 'HEAD')}\n"
                   "date: 2026-11-09\ntype: fix\nroadmap_ids: []\n"
                   'review_task_ids: [TASK-0007]\nsummary: "s"\n'
                   'hold: "a human check is outstanding"\n---\nbody\n', encoding="utf-8")
    _run(root, sys.executable, "sysop/scripts/pending_doc_collect.py", "collect", str(ws), BRANCH)
    _git(root, "worktree", "remove", str(ws))
    _git(root, "merge", "-q", "--no-ff", "-m", f"Merge {BRANCH}", BRANCH)
    _run(root, "bash", "sysop/scripts/close_batch.sh", "--merge-target", "main", "7")
    held = _run(root, sys.executable, "sysop/scripts/pending_doc_hold.py", "check", "--stamp")
    assert "HELD: review-batch-7.md" in held.stdout, held.stdout
    # What the close leaves: the measured end state this module is about.
    assert "`Merged`" in (root / "review_tasks.md").read_text(encoding="utf-8")
    assert not (root / "sysop" / "runtime" / "locks" / "BATCH-7.lock").exists()
    assert _git(root, "rev-list", "--count", f"main..{BRANCH}") == "0"
    return root


def _survey(root: Path) -> dict:
    return json.loads(_run(root, sys.executable, "sysop/scripts/sitrep_survey.py",
                           "--json").stdout)


def test_a_kept_branch_is_not_offered_for_deletion_and_routes_through_the_hold(closed):
    got = _survey(closed)
    kinds = [d["kind"] for d in got["discrepancies"]]
    assert "orphan branch" not in kinds, got["discrepancies"]
    hits = [d for d in got["discrepancies"] if d["kind"] == KIND]
    assert len(hits) == 1, got["discrepancies"]
    d = hits[0]
    assert "git branch -D" not in d["suggestion"], d
    assert "review-batch-7.md" in d["detail"] and "a human check is outstanding" in d["detail"]
    assert (f"python3 sysop/scripts/pending_doc_hold.py clear {BRANCH}" in d["suggestion"]
            and d["suggestion"].endswith("/review-close")), d
    rec = got["recommended_next"]
    assert rec is not None, "RECOMMENDED NEXT read idle while the doc waits on a human"
    assert rec["command"] == d["suggestion"], rec
    assert any(KIND in line or BRANCH in line for line in got["suggested_order"]), (
        got["suggested_order"])


def test_the_route_s_clear_command_clears_the_hold_and_then_routes_to_the_close(closed):
    """The command the route names runs, and once it has the hold step drops out."""
    _run(closed, sys.executable, "sysop/scripts/pending_doc_hold.py", "clear", BRANCH)
    got = _survey(closed)
    d = next(d for d in got["discrepancies"] if d["kind"] == KIND)
    assert "pending_doc_hold.py" not in d["suggestion"], d
    assert d["suggestion"].startswith("/review-close"), d
    assert got["recommended_next"]["command"] == d["suggestion"]


def test_deleting_the_doc_returns_the_branch_to_the_orphan_arm(closed):
    for p in (closed / "sysop" / "runtime" / "pending-docs").glob("*.md"):
        p.unlink()
    kinds = [d["kind"] for d in _survey(closed)["discrepancies"]]
    assert "orphan branch" in kinds and KIND not in kinds, kinds


def test_the_kind_is_in_the_discrepancy_table():
    text = SITREP_MD.read_text(encoding="utf-8")
    start = text.index("## Discrepancy categories")
    rows = [ln for ln in text[start:].splitlines() if ln.startswith("| ")]
    assert any(ln.split("|")[1].strip().lower() == KIND for ln in rows), rows


def test_the_task_path_and_the_kept_branch_share_the_hold_step():
    assert ss._hold_clear_step("FEAT-1") == (
        "finish what its pending doc's `hold:` names, then "
        "python3 sysop/scripts/pending_doc_hold.py clear FEAT-1")


def test_the_cascade_rows_name_both_new_arms():
    """`/sitrep`'s cascade table carries the batch `merged, close pending` row (3c) and the
    kept-branch row (3d), in that order, as `_recommended_next` ranks them."""
    rows = {}
    for ln in SITREP_MD.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")] if ln.startswith("|") else []
        if cells and cells[0] in ("3b", "3c", "3d"):
            assert cells[0] not in rows, cells[0]
            rows[cells[0]] = cells[1]
    assert set(rows) == {"3b", "3c", "3d"}, rows
    assert "review batch" in rows["3c"] and "`merged, close pending`" in rows["3c"], rows["3c"]
    assert KIND in rows["3d"].lower(), rows["3d"]
