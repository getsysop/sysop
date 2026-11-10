"""Every route `/sitrep` prints for a batch a stopped close merged agrees, and runs.

Three shapes the batch twin of `merged, close pending` first missed:

* a `Review Ready` header, the normal one a batch carries into `/review-close`
  (WORKFLOW.md's lifecycle), which never enters `_classify_review_batches`;
* a lockless branch, where `batch branch without lock` offered `batch_work.sh` and
  `--release` (which commits the header back to `Pending`, and the next survey said
  `/triage` and `git branch -D`);
* a merge that reached only `origin/<default>`, where `close_batch.sh` on the local
  default branch prints `NOT merged … Skipping` and exits 0.

Each route below is run as printed, on fixtures built with the shipped scripts.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from test_sitrep_batch_merged import BRANCH, CLOSE, _claimed, _git, _run, _stopped, _survey

KEPT = "branch kept for a pending doc"


def _header(root: Path) -> str:
    return re.search(r"^### Batch 7 — .*`([^`]+)`$",
                     (root / "review_tasks.md").read_text(encoding="utf-8"), re.M).group(1)


def _set_header(root: Path, status: str) -> None:
    p = root / "review_tasks.md"
    p.write_text(re.sub(r"(^### Batch 7 — .*)`[^`]+`$", rf"\1`{status}`",
                        p.read_text(encoding="utf-8"), flags=re.M), encoding="utf-8")
    _git(root, "commit", "-qam", f"Batch 7 {status}")


def _run_route(root: Path, route: str) -> None:
    """Run each shell command a route names, as printed, from the main checkout."""
    for part in route.split(", then "):
        part = part.removeprefix("then ").split(" (from the main checkout")[0]
        if part.startswith("/"):
            continue  # a skill: nothing to run here
        _run(root, "bash", "-c", part)


# ── 1. a `Review Ready` header in the merged state ───────────────────────


@pytest.mark.parametrize("merge", ["no-ff", "rebase"])
def test_a_review_ready_batch_a_stopped_close_merged_routes_to_close_batch(tmp_path, merge):
    root = _stopped(tmp_path, merge, hold=False)
    _set_header(root, "Review Ready")
    got = _survey(root)
    want = f"{CLOSE}, then /review-close"
    assert got["recommended_next"]["command"] == want, got["recommended_next"]
    assert "Review Ready" in got["recommended_next"]["reason"]
    assert any("review-batch-7.md" in d for d in got["recommended_next"]["detail_lines"])
    assert got["review_ready_merged"] == [7] and got["review_ready_stale"] == []
    assert got["review_batches"] == [], "the Pending/In Progress filter is unchanged"
    assert f"Batch 7: merged by a previous close — {want}" in got["suggested_order"], (
        got["suggested_order"])
    text = _run(root, sys.executable, "sysop/scripts/sitrep_survey.py").stdout
    head = text.split("RECOMMENDED NEXT")[0]
    assert "merged, close pending" in head and want in head, head


def test_close_batch_closes_a_review_ready_batch_and_the_kept_branch_arm_takes_over(tmp_path):
    root = _stopped(tmp_path, "rebase", hold=True)
    _set_header(root, "Review Ready")
    before = _survey(root)["recommended_next"]["command"]
    assert before.startswith(f"{CLOSE}; then finish what its pending doc's `hold:`"), before
    _run(root, "bash", "sysop/scripts/close_batch.sh", "7")
    assert _header(root) == "Merged"
    got = _survey(root)
    assert got["review_ready_merged"] == []
    kept = [d for d in got["discrepancies"] if d["kind"] == KEPT]
    assert len(kept) == 1 and got["recommended_next"]["command"] == kept[0]["suggestion"]
    assert before.endswith(kept[0]["suggestion"]), (before, kept[0]["suggestion"])


# ── 2. the lockless remedy agrees with the merged state ──────────────────


def _no_delete_or_release(got: dict) -> None:
    for d in got["discrepancies"]:
        assert "git branch -D" not in d["suggestion"], d
        assert "--release" not in d["suggestion"], d


@pytest.mark.parametrize("status", ["In Progress", "Review Ready"])
def test_a_lockless_merged_batch_s_remedy_is_its_route(tmp_path, status):
    root = _stopped(tmp_path, "no-ff", hold=False)
    if status != "In Progress":
        _set_header(root, status)
    (root / "sysop" / "runtime" / "locks" / "BATCH-7.lock").unlink()
    got = _survey(root)
    want = f"{CLOSE}, then /review-close"
    assert got["recommended_next"]["command"] == want, got["recommended_next"]
    hits = [d for d in got["discrepancies"] if d["kind"] == "batch branch without lock"]
    assert len(hits) == 1 and hits[0]["suggestion"].startswith(want), hits
    _no_delete_or_release(got)


def test_a_released_merged_batch_still_routes_to_close_batch_not_triage(tmp_path):
    """The state `--release` leaves (header `Pending`, no lock): before, `/triage`, and
    `git branch -D` for a branch the doc names."""
    root = _stopped(tmp_path, "no-ff", hold=False)
    (root / "sysop" / "runtime" / "locks" / "BATCH-7.lock").unlink()
    _run(root, "bash", "sysop/scripts/batch_work.sh", "--release", "7")
    assert _header(root) == "Pending"
    got = _survey(root)
    rb = got["review_batches"][0]
    assert rb["state"] == "merged, close pending", rb
    assert got["recommended_next"]["command"] == f"{CLOSE}, then /review-close"
    _no_delete_or_release(got)
    _run_route(root, got["recommended_next"]["command"])
    assert _header(root) == "Merged"


def test_a_lockless_live_branch_a_doc_names_is_never_offered_for_deletion(tmp_path):
    """Not merged, so not the merged route: a `Pending` batch's lockless branch that a doc
    in the main checkout names keeps the claim remedy and loses only the delete."""
    root, ws = _claimed(tmp_path)
    (ws / "fix.txt").write_text("fix", encoding="utf-8")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-qm", "fix")
    doc = root / "sysop" / "runtime" / "pending-docs" / "review-batch-7.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(f"---\nbranch: {BRANCH}\nsummary: s\n---\n", encoding="utf-8")
    _git(root, "worktree", "remove", "--force", str(ws))
    (root / "sysop" / "runtime" / "locks" / "BATCH-7.lock").unlink()
    _set_header(root, "Pending")
    got = _survey(root)
    hits = [d for d in got["discrepancies"] if d["kind"] == "batch branch without lock"]
    assert len(hits) == 1, got["discrepancies"]
    assert "git branch -D" not in hits[0]["suggestion"], hits
    assert "review-batch-7.md" in hits[0]["suggestion"], hits


# ── 3. a merge only the remote-tracking ref holds ────────────────────────


def _remote_merged(tmp_path: Path, local_commit: bool) -> Path:
    root, ws = _claimed(tmp_path)
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    _git(root, "remote", "add", "origin", str(bare))
    _git(root, "push", "-q", "-u", "origin", "main")
    (ws / "fix.txt").write_text("fix", encoding="utf-8")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-qm", "fix", "-m", "Doc-Work: TASK-0007")
    tip = _git(ws, "rev-parse", "HEAD")
    doc = ws / "sysop" / "runtime" / "pending-docs" / "review-batch-7.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(f"---\nbranch: {BRANCH}\nbranch_tip: {tip}\ntype: fix\nroadmap_ids: []\n"
                   'summary: "s"\n---\nbody\n', encoding="utf-8")
    _run(root, sys.executable, "sysop/scripts/pending_doc_collect.py", "collect", str(ws), BRANCH)
    _git(root, "worktree", "remove", str(ws))
    _git(root, "checkout", "-q", "-b", "elsewhere")
    _git(root, "merge", "-q", "--no-ff", "-m", f"Merge {BRANCH}", BRANCH)
    _git(root, "push", "-q", "origin", "elsewhere:main")
    _git(root, "checkout", "-q", "main")
    _git(root, "branch", "-D", "elsewhere")
    _git(root, "fetch", "-q", "origin")
    if local_commit:  # local main carries its own unpushed work
        (root / "local.txt").write_text("l", encoding="utf-8")
        _git(root, "add", "local.txt")
        _git(root, "commit", "-qm", "local only")
    assert _git(root, "rev-list", "--count", f"main..{BRANCH}") == "1"
    return root


@pytest.mark.parametrize("local_commit", [False, True])
def test_a_merge_only_the_remote_holds_routes_through_merging_it(tmp_path, local_commit):
    root = _remote_merged(tmp_path, local_commit)
    got = _survey(root)
    rb = got["review_batches"][0]
    want = ("git merge --ff-only origin/main (from the main checkout, on main; if it "
            "refuses, main has commits of its own: bring it level with origin/main first), "
            "then bash sysop/scripts/close_batch.sh 7, then /review-close")
    assert rb["state"] == "merged, close pending" and rb["next_action"] == want, rb
    assert got["recommended_next"]["command"] == want
    assert any(want in line for line in got["suggested_order"]), got["suggested_order"]
    if not local_commit:
        _run_route(root, want)
        assert _header(root) == "Merged"
        assert not (root / "sysop" / "runtime" / "locks" / "BATCH-7.lock").exists()
        return
    # Local work of its own: the route's first step refuses loudly and writes nothing; the
    # survey does not decide how the person reconciles their default branch.
    before = _git(root, "rev-parse", "main")
    r = subprocess.run(["bash", "-c", "git merge --ff-only origin/main"], cwd=root,
                       capture_output=True, text=True)
    assert r.returncode != 0, r.stdout + r.stderr
    assert _git(root, "rev-parse", "main") == before
    assert _header(root) == "In Progress"


def test_the_remote_only_route_names_the_local_branch_and_says_why(tmp_path):
    """The two halves the round mutated: the route is run `on main`, never `on origin/main`,
    and a detail line says why the merge step is there."""
    root = _remote_merged(tmp_path, False)
    got = _survey(root)
    assert "(from the main checkout, on main;" in got["recommended_next"]["command"]
    assert "on origin/main" not in got["recommended_next"]["command"]
    assert any("not on the local default branch" in d
               for d in got["recommended_next"]["detail_lines"]), got["recommended_next"]


# ── the rank of the kept-branch arm (row 3d), by behaviour ───────────────


def test_a_kept_branch_outranks_the_queue_and_in_progress_work(tmp_path):
    """Row 3d sits above the batch queue (4a) and claim work (5): a kept branch beside an
    untriaged `Pending` batch and a task in progress is routed first."""
    import sitrep_survey as ss
    from datetime import datetime, timezone
    kept = ss.Discrepancy(kind=KEPT, detail="branch review/batch-7 …",
                          suggestion="/review-close")
    pending = ss.ReviewBatchState(
        batch_number=9, title="B", md_status="Pending", branch="review/batch-9",
        has_lock=False, has_branch=False, has_flag=False, flag_reason="", total_tasks=1,
        doc_worked_tasks=0, state="pending (not claimed)", next_action="/triage …")
    task = ss.TaskState(task_id="FEAT-1", state="in progress", next_action="x",
                        commits_ahead=1)
    s = ss.Survey(timestamp=datetime(2026, 11, 9, tzinfo=timezone.utc), main_root=tmp_path,
                  head_short="a", tasks=[task], review_batches=[pending],
                  discrepancies=[kept], stale_days=7, open_roadmap_ids=["FEAT-2"])
    rec = ss._recommended_next(s)
    assert rec.command == "/review-close" and "kept a branch" in rec.reason, rec
    s.discrepancies = []
    assert ss._recommended_next(s).command != "/review-close"


# ── the lockless remedy at both call sites ───────────────────────────────


def test_a_lockless_merged_batch_with_its_worktree_back_gets_the_merged_remedy(tmp_path):
    """The worktree call site of `_batch_without_lock` (the branch site is pinned above)."""
    root = _stopped(tmp_path, "no-ff", hold=False)
    _git(root, "worktree", "add", "-q", str(tmp_path / "proj-batch-7"), BRANCH)
    (root / "sysop" / "runtime" / "locks" / "BATCH-7.lock").unlink()
    got = _survey(root)
    hits = [d for d in got["discrepancies"] if d["kind"] == "batch branch without lock"]
    assert len(hits) == 1 and "worktree" in hits[0]["detail"], hits
    assert hits[0]["suggestion"].startswith(f"{CLOSE}, then /review-close"), hits
    _no_delete_or_release(got)


def test_the_lockless_row_names_both_routes_for_a_review_ready_batch():
    import test_sitrep_batch_merged as m
    rows = [ln for ln in m.SITREP_MD.read_text(encoding="utf-8").splitlines()
            if ln.startswith("| Batch branch without lock |")]
    assert len(rows) == 1, rows
    cell = rows[0].split("|")[3]
    assert "`/document-work` on the branch first when its pending doc is stale" in cell, cell
    assert "already merged (row `3c`)" in cell and "never a claim or a `--release`" in cell
    assert "never `git branch -D` on a branch a pending doc names" in cell, cell
