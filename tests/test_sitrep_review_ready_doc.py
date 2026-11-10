"""`/sitrep` reads a `Review Ready` batch's pending doc before routing it to a close.

A batch whose `review_tasks.md` header reads `Review Ready` never enters
`_classify_review_batches` (it filters to `Pending`/`In Progress`), so the P2 header
arm sent it to `/review-close (batch N)` without measuring its pending doc, and a
stale doc then met Step 3b's exit 6. The survey now runs `_batch_doc_drift` (the
batch path's own measure, through `_doc_drift.py`) for each such batch. A stale one
keeps P2's rank and takes row `4g`'s command; a current or unmeasurable one routes
as before. `review_batches` still filters to `Pending`/`In Progress`; the payload
names a stale `Review Ready` batch in a flat top-level list, `review_ready_stale`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import sitrep_survey as ss
from test_pending_doc_integrity import _Sub

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
SITREP_MD = REPO_ROOT / "core" / "skills" / "sitrep" / "SKILL.md"
ROADMAP_MD = REPO_ROOT / "core" / "skills" / "roadmap" / "SKILL.md"
BRANCH = "review/batch-7"


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                        "WORKTREE_ROOT", "WORKTREE_PREFIX")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    return env


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True, env=_env()).stdout.strip()


def _commit(cwd: Path, name: str, body: str = "") -> str:
    (cwd / name).write_text(name, encoding="utf-8")
    _git(cwd, "add", "-A")
    _git(cwd, "commit", "-qm", f"change {name}", *(["-m", body] if body else []))
    return _git(cwd, "rev-parse", "HEAD")


def _tracker(status: str) -> str:
    return ("# Review Tasks\n\n"
            f"### Batch 7 — Batch seven `{status}`\n\n"
            f"> **Branch:** `{BRANCH}`\n\n"
            "- [x] **TASK-0007**: a fix\n")


def _write_doc(ws: Path, tip: str) -> Path:
    doc = ws / "sysop" / "runtime" / "pending-docs" / "review-batch-7.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(f"---\nbranch: {BRANCH}\nbranch_tip: {tip}\ntype: fix\n"
                   'summary: "s"\n---\n', encoding="utf-8")
    return doc


@pytest.fixture
def claimed(tmp_path: Path) -> dict:
    """A consumer's batch, claimed by the shipped `batch_work.sh` (worktree, branch,
    `BATCH-7.lock`), worked, documented at `doc_tip`, then committed to once more;
    its header is then set to `Review Ready`, which no shipped script writes."""
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / ".gitignore").write_text("sysop/runtime/\n", encoding="utf-8")
    (root / "review_tasks.md").write_text(_tracker("Pending"), encoding="utf-8")
    scripts = root / "sysop" / "scripts"
    scripts.mkdir(parents=True)
    for p in list(SCRIPTS.glob("*.py")) + list(SCRIPTS.glob("*.sh")):
        (scripts / p.name).write_bytes(p.read_bytes())
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    r = subprocess.run(["bash", "sysop/scripts/batch_work.sh", "7"], cwd=root,
                       capture_output=True, text=True, env=_env())
    assert r.returncode == 0, r.stdout + r.stderr
    lock = (root / "sysop" / "runtime" / "locks" / "BATCH-7.lock").read_text(encoding="utf-8")
    ws = Path(next(ln.partition(":")[2].strip() for ln in lock.splitlines()
                   if ln.partition(":")[0] == "workspace"))
    assert _git(ws, "symbolic-ref", "--short", "HEAD") == BRANCH
    doc_tip = _commit(ws, "fix.txt", "Doc-Work: TASK-0007")
    head = _commit(ws, "later.txt")
    text = (root / "review_tasks.md").read_text(encoding="utf-8")
    assert "`In Progress`" in text, text
    (root / "review_tasks.md").write_text(text.replace("`In Progress`", "`Review Ready`"),
                                          encoding="utf-8")
    return {"root": root, "ws": ws, "doc_tip": doc_tip, "head": head}


def _survey(root: Path) -> dict:
    out = subprocess.run([sys.executable, "sysop/scripts/sitrep_survey.py", "--json"],
                         cwd=root, capture_output=True, text=True, env=_env())
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _text(root: Path) -> str:
    out = subprocess.run([sys.executable, "sysop/scripts/sitrep_survey.py"],
                         cwd=root, capture_output=True, text=True, env=_env())
    assert out.returncode == 0, out.stderr
    return out.stdout


# ── end to end, with the real claim writer ───────────────────────────────


def _close_collect_exit(claimed: dict) -> int:
    """Step 3b's collect, as the close runs it, on the batch's workspace."""
    r = subprocess.run([sys.executable, *_Sub("collect").argv, str(claimed["ws"]), BRANCH],
                       cwd=claimed["root"], capture_output=True, text=True, env=_env())
    return r.returncode


def test_a_review_ready_batch_with_a_stale_doc_routes_to_document_work(claimed):
    _write_doc(claimed["ws"], claimed["doc_tip"])
    assert _close_collect_exit(claimed) == 6, "the close no longer refuses this doc"
    got = _survey(claimed["root"])
    rec = got["recommended_next"]
    assert rec["command"] == (f"/document-work on {BRANCH} (re-stamps the pending-doc's "
                              "branch_tip), then /review-close (batch 7)"), rec
    assert "Review Ready" in rec["reason"] and "stale" in rec["reason"], rec
    assert any("1 commit(s) landed on " + BRANCH in d for d in rec["detail_lines"]), rec
    assert got["review_ready_stale"] == [7], got["review_ready_stale"]
    # The filter `/roadmap` documents as a premise is untouched.
    assert got["review_batches"] == [], got["review_batches"]
    assert any("/document-work on " + BRANCH in line for line in got["suggested_order"]), (
        got["suggested_order"])
    text = _text(claimed["root"])
    assert "REVIEW READY (waiting on /review-close): batch 7" in text, text
    assert "1 commit(s) landed on " + BRANCH in text.split("RECOMMENDED NEXT")[0], text


def test_re_stamping_the_doc_returns_the_batch_to_review_close(claimed):
    _write_doc(claimed["ws"], claimed["head"])
    assert _close_collect_exit(claimed) == 0
    got = _survey(claimed["root"])
    assert got["recommended_next"]["command"] == "/review-close (batch 7)", got
    assert got["review_ready_stale"] == []
    assert "/review-close (batch 7, header reads Review Ready)" in got["suggested_order"], (
        got["suggested_order"])


def test_a_review_ready_batch_with_no_doc_routes_as_before(claimed):
    got = _survey(claimed["root"])
    assert got["recommended_next"]["command"] == "/review-close (batch 7)", got
    assert got["review_ready_stale"] == []


def test_an_unmeasurable_doc_routes_as_before_and_says_why(claimed):
    _write_doc(claimed["ws"], "<sha>")
    got = _survey(claimed["root"])
    assert got["recommended_next"]["command"] == "/review-close (batch 7)", got
    assert got["review_ready_stale"] == []
    assert "pending-doc staleness unknown:" in _text(claimed["root"])


def test_the_lockless_discrepancy_names_the_stale_doc_too(claimed):
    """`_batch_without_lock` is the fourth reader of the status: its `Review Ready`
    remedy sent the same batch to `/review-close` beside a RECOMMENDED NEXT that
    says `/document-work`."""
    _write_doc(claimed["ws"], claimed["doc_tip"])
    (claimed["root"] / "sysop" / "runtime" / "locks" / "BATCH-7.lock").unlink()
    got = _survey(claimed["root"])
    hits = [d for d in got["discrepancies"] if d["kind"] == "batch branch without lock"]
    assert len(hits) == 1, got["discrepancies"]
    assert hits[0]["suggestion"].startswith(f"/document-work on {BRANCH}"), hits
    assert got["recommended_next"]["command"].startswith(f"/document-work on {BRANCH}")
    _write_doc(claimed["ws"], claimed["head"])
    hits = [d for d in _survey(claimed["root"])["discrepancies"]
            if d["kind"] == "batch branch without lock"]
    assert hits[0]["suggestion"].startswith("/review-close (batch 7)"), hits


# ── the cascade, on a hand-built survey ──────────────────────────────────


def _rr(stale: bool, notes=("n",)) -> ss.ReviewReadyDoc:
    drift = ss.DocDrift(2, tip="a" * 40) if stale else None
    return ss.ReviewReadyDoc(branch=BRANCH, drift=drift, notes=list(notes))


def _s(tasks=(), batches=(), ready=(), docs=None) -> ss.Survey:
    return ss.Survey(timestamp=datetime(2026, 11, 9, tzinfo=timezone.utc),
                     main_root=Path("/tmp/r"), head_short="abc1234", tasks=list(tasks),
                     review_batches=list(batches), discrepancies=[], stale_days=7,
                     open_roadmap_ids=[], review_ready_batches=list(ready),
                     review_ready_docs=dict(docs or {}))


def _ready_batch(n: int) -> ss.ReviewBatchState:
    return ss.ReviewBatchState(
        batch_number=n, title="B", md_status="In Progress", branch=f"b/{n}", has_lock=True,
        has_branch=True, has_flag=False, flag_reason="", total_tasks=1, doc_worked_tasks=1,
        state="ready for /review-close", next_action=f"/review-close (batch {n})")


def test_a_stale_header_batch_keeps_p2s_rank():
    """Above every state arm, a `ready for /review-close` batch included; below P1."""
    s = _s(batches=[_ready_batch(3)], ready=[(7, "T")], docs={7: _rr(True)})
    rec = ss._recommended_next(s)
    assert rec.command.startswith(f"/document-work on {BRANCH}") and "batch 7" in rec.command
    assert rec.detail_lines == ["n"]
    task = ss.TaskState(task_id="FEAT-1", state="ready for /review-close")
    s.tasks = [task]
    assert ss._recommended_next(s).command == "/review-close FEAT-1"


def test_a_current_or_unmeasured_header_batch_is_unchanged():
    for docs in ({}, {7: _rr(False)}):
        rec = ss._recommended_next(_s(ready=[(7, "T")], docs=docs))
        assert rec.command == "/review-close (batch 7)", rec
        assert rec.detail_lines == [], rec


def test_the_ordered_list_carries_the_header_batches_at_p2s_rank():
    """The ordered list had no `Review Ready` arm: a report whose only work was one
    such batch said `/review-close (batch 7)` under RECOMMENDED NEXT and `(no active
    Sysop work; …)` under SUGGESTED ORDER."""
    order = ss._suggested_order(_s(ready=[(7, "T")]))
    assert order == ["/review-close (batch 7, header reads Review Ready)"], order
    order = ss._suggested_order(_s(batches=[_ready_batch(3)], ready=[(7, "T"), (8, "U")],
                                   docs={8: _rr(True)}))
    assert order[0] == "/review-close (batch 7, header reads Review Ready)", order
    assert order[1].startswith("Batch 8 header reads Review Ready, but its pending-doc is "
                               f"stale — /document-work on {BRANCH}"), order
    assert order[2] == "/review-close (batch 3, ready now)", order


def test_the_payload_lists_only_the_stale_header_batches():
    p = json.loads(ss.render_json(_s(ready=[(7, "T"), (8, "U"), (9, "V")],
                                     docs={7: _rr(False), 8: _rr(True)})))
    assert p["review_ready_stale"] == [8]
    assert p["review_batches"] == []


# ── the two skills say what the script does ──────────────────────────────


def _row(text: str, first_cell: str) -> list[str]:
    hits = [ln for ln in text.splitlines()
            if ln.startswith("|") and ln.strip("|").split("|")[0].strip() == first_cell]
    assert len(hits) == 1, (first_cell, hits)
    return [c.strip() for c in hits[0].strip().strip("|").split("|")]


def test_sitrep_row_2_says_the_doc_is_read():
    row = _row(SITREP_MD.read_text(encoding="utf-8"), "2")
    assert "its doc is not read" not in row[1], row
    assert "4g" in row[1] and "Review Ready" in row[1], row


def test_roadmap_routes_a_stale_header_batch_by_the_payload_key():
    text = ROADMAP_MD.read_text(encoding="utf-8")
    row = _row(text, "header status `Review Ready`")
    assert "`review_ready_stale`" in row[1] and "/document-work" in row[1], row
    assert "never reaches the payload" not in text


def test_a_review_ready_batch_whose_branch_is_gone_reads_no_doc(claimed):
    """The doc is read only for a branch on disk, as the state path reads one: a doc in the
    main checkout naming a deleted branch is not measured, noted or listed as stale."""
    root, ws = claimed["root"], claimed["ws"]
    _git(root, "worktree", "remove", "--force", str(ws))
    _git(root, "branch", "-D", BRANCH)
    _write_doc(root, claimed["doc_tip"])
    got = _survey(root)
    assert got["review_ready_stale"] == [], got["review_ready_stale"]
    assert got["recommended_next"]["command"] == "/review-close (batch 7)", got
    assert got["recommended_next"].get("detail_lines") in (None, []), got["recommended_next"]
    head = _text(root).split("RECOMMENDED NEXT")[0]
    assert "staleness unknown" not in head and "\n  Batch 7" not in head, head


def test_the_lockless_branch_site_names_the_stale_doc_too(claimed):
    """The `branch … (no worktree)` call site of `_batch_without_lock`: lock gone, worktree
    removed, doc collected into the main checkout (as Step 3b leaves it)."""
    root, ws = claimed["root"], claimed["ws"]
    _write_doc(ws, claimed["doc_tip"])
    r = subprocess.run([sys.executable, *_Sub("collect").argv, str(ws), BRANCH], cwd=root,
                       capture_output=True, text=True, env=_env())
    assert "PENDING-DOC STALE:" in r.stdout, r.stdout + r.stderr
    (root / "sysop" / "runtime" / "pending-docs").mkdir(parents=True, exist_ok=True)
    (ws / "sysop" / "runtime" / "pending-docs" / "review-batch-7.md").rename(
        root / "sysop" / "runtime" / "pending-docs" / "review-batch-7.md")
    _git(root, "worktree", "remove", "--force", str(ws))
    (root / "sysop" / "runtime" / "locks" / "BATCH-7.lock").unlink()
    got = _survey(root)
    assert got["review_ready_stale"] == [7], got
    hits = [d for d in got["discrepancies"] if d["kind"] == "batch branch without lock"]
    assert len(hits) == 1 and "(no worktree)" in hits[0]["detail"], hits
    assert hits[0]["suggestion"].startswith(f"/document-work on {BRANCH}"), hits


def test_the_text_report_prints_the_stale_batch_s_next_line(claimed):
    _write_doc(claimed["ws"], claimed["doc_tip"])
    head = _text(claimed["root"]).split("RECOMMENDED NEXT")[0]
    assert ("  Batch 7      pending doc stale\n               ↳ next: /document-work on "
            f"{BRANCH} (re-stamps the pending-doc's branch_tip), then /review-close "
            "(batch 7)") in head, head


def test_roadmap_names_the_payload_s_review_ready_keys_as_the_survey_emits_them():
    p = json.loads(ss.render_json(_s()))
    emitted = {k for k in p if k.startswith("review_ready_")}
    assert emitted == {"review_ready_stale", "review_ready_merged"}, emitted
    text = ROADMAP_MD.read_text(encoding="utf-8")
    named = set(re.findall(r"`(review_ready_[a-z_]+)`", text))
    assert named == emitted, (named, emitted)


def test_roadmap_says_where_else_the_payload_names_a_review_ready_batch():
    """The payload also names one in `recommended_next`, `suggested_order` and
    `discrepancies` (P2, the ordered list, the lockless entry); no sentence may say the two
    keys are its only words."""
    text = ROADMAP_MD.read_text(encoding="utf-8")
    assert "only words on it" not in text
    hits = [ln for ln in text.splitlines() if "only batch-level fields" in ln]
    assert len(hits) == 2, hits
    for ln in hits:
        for key in ("`recommended_next`", "`suggested_order`", "`discrepancies`"):
            assert key in ln, (key, ln[:120])


def test_roadmap_s_state_enum_names_every_batch_state():
    from test_roadmap_batch_survey import _survey_batch_states
    line = next(ln for ln in ROADMAP_MD.read_text(encoding="utf-8").splitlines()
                if ln.startswith("- **`state`** — one of "))
    enum = line[:line.index(". ")]
    missing = [s for s in _survey_batch_states() if f"`{s}`" not in enum]
    assert not missing, missing
