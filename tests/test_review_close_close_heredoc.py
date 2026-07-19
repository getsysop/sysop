"""Regression coverage for the Phase 134 gdp backports into `/review-close`.

Two same-day gdp fixes (2026-07-19), both silent-failure classes:

- **Step 3b `mkdir -p` before the pending-docs cp** (gdp `cb8f3840`): main's
  `sysop/runtime/pending-docs/` is gitignored (absent from any fresh clone) and
  authored lazily in the *worktree*, so a bare `cp <file> <missing-dir>/` fails
  with its error masked by `2>/dev/null` — and the very next `git worktree remove`
  destroys the doc for good. Guarded here as a prose drift-check on the command.

- **Step 4c parked-marker removal at close** (gdp `5f6a74b5`): the close heredoc
  flipped status + dropped the lock but never touched
  `sysop/runtime/auto-build/parked/<TASK_ID>__*.md`, so markers for done tasks
  accumulated as stale drift. Exercised here by extracting the heredoc's Python
  body from SKILL.md and running it against a fixture repo (same pattern as
  test_review_close_smoke_gate.py), so the fix has CI coverage.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
import datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"

PLACEHOLDER_IDS = 'ids = ["<ROADMAP_ID_1>", "<ROADMAP_ID_2>"]'


def _extract_close_heredoc() -> str:
    """Pull the Step 4c tasks/index.yml close heredoc's Python body out of SKILL.md.

    Anchor on the body's unique placeholder-ids line and walk back to the nearest
    `python3 - <<'PY'` opener (robust to future heredocs being added or blocks
    reordered — the Step 3c smoke gate uses a different `<<'EOF'` opener); the body
    runs to the terminating `PY` line. The block sits inside a numbered markdown
    list, so every line carries a 3-space indent — dedent before returning.
    """
    text = SKILL.read_text(encoding="utf-8")
    ids_at = text.find(PLACEHOLDER_IDS)
    assert ids_at != -1, "could not locate the Step 4c placeholder-ids anchor in SKILL.md"
    opener = "python3 - <<'PY'\n"
    opener_at = text.rfind(opener, 0, ids_at)
    assert opener_at != -1, "could not locate the Step 4c heredoc opener above the ids anchor"
    start = opener_at + len(opener)
    end = text.find("\n   PY\n", start)
    assert end != -1, "could not locate the Step 4c heredoc terminator"
    return textwrap.dedent(text[start:end])


CLOSE_SRC = _extract_close_heredoc()


def _seed_repo(tmp_path: Path) -> Path:
    """A minimal consumer repo: two open tasks (tracked), locks + parked markers
    (gitignored working-tree artifacts, deliberately NOT committed)."""
    repo = tmp_path / "consumer"
    (repo / "tasks" / "open").mkdir(parents=True)
    (repo / "tasks" / "archive").mkdir(parents=True)
    (repo / "tasks" / "archive" / ".gitkeep").write_text("", encoding="utf-8")
    index = {
        "schema_version": 1,
        "tasks": [
            {"id": "TASK-0001", "status": "in_progress", "body": "open/TASK-0001.md"},
            {"id": "TASK-0002", "status": "in_progress", "body": "open/TASK-0002.md"},
        ],
    }
    (repo / "tasks" / "index.yml").write_text(yaml.safe_dump(index, sort_keys=False), encoding="utf-8")
    (repo / "tasks" / "open" / "TASK-0001.md").write_text("# TASK-0001\n", encoding="utf-8")
    (repo / "tasks" / "open" / "TASK-0002.md").write_text("# TASK-0002\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "seed"],
        cwd=repo, check=True,
    )
    # Gitignored runtime artifacts (working-tree-only, like a real consumer).
    (repo / "sysop" / "runtime" / "locks").mkdir(parents=True)
    (repo / "sysop" / "runtime" / "locks" / "TASK-0001.lock").write_text("x", encoding="utf-8")
    parked = repo / "sysop" / "runtime" / "auto-build" / "parked"
    parked.mkdir(parents=True)
    (parked / "TASK-0001__20260719T000000Z.md").write_text("park 1", encoding="utf-8")
    (parked / "TASK-0001__20260719T010000Z.md").write_text("park 2", encoding="utf-8")
    (parked / "TASK-0002__20260719T000001Z.md").write_text("other task", encoding="utf-8")
    return repo


def _run_close(repo: Path, ids: list[str]) -> None:
    src = CLOSE_SRC.replace(PLACEHOLDER_IDS, f"ids = {ids!r}")
    assert src != CLOSE_SRC, "placeholder ids line not found in the extracted heredoc"
    r = subprocess.run(
        [sys.executable, "-c", src], capture_output=True, text=True, cwd=str(repo), timeout=30
    )
    assert r.returncode == 0, f"close heredoc errored ({r.returncode}):\n{r.stderr}"


def test_close_drops_lock_and_parked_markers_for_closed_task_only(tmp_path):
    repo = _seed_repo(tmp_path)
    before = datetime.date.today().isoformat()
    _run_close(repo, ["TASK-0001"])
    after = datetime.date.today().isoformat()

    d = yaml.safe_load((repo / "tasks" / "index.yml").read_text(encoding="utf-8"))
    by_id = {t["id"]: t for t in d["tasks"]}
    assert by_id["TASK-0001"]["status"] == "done"
    assert by_id["TASK-0001"]["completed_date"] in (before, after)
    assert by_id["TASK-0001"]["body"] == "archive/TASK-0001.md"
    assert (repo / "tasks" / "archive" / "TASK-0001.md").exists()
    assert not (repo / "tasks" / "open" / "TASK-0001.md").exists()

    # The Phase 134 assertions: lock AND both parked markers for the closed task
    # are gone; the other task's marker (and its open state) are untouched.
    assert not (repo / "sysop" / "runtime" / "locks" / "TASK-0001.lock").exists()
    parked = repo / "sysop" / "runtime" / "auto-build" / "parked"
    assert sorted(p.name for p in parked.glob("*.md")) == ["TASK-0002__20260719T000001Z.md"]
    assert by_id["TASK-0002"]["status"] == "in_progress"


def test_close_noops_cleanly_when_never_parked(tmp_path):
    repo = _seed_repo(tmp_path)
    # Simulate a consumer that has never run /auto-build: no parked dir at all.
    parked = repo / "sysop" / "runtime" / "auto-build"
    for p in sorted(parked.rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    parked.rmdir()
    _run_close(repo, ["TASK-0001"])
    d = yaml.safe_load((repo / "tasks" / "index.yml").read_text(encoding="utf-8"))
    assert {t["id"]: t["status"] for t in d["tasks"]}["TASK-0001"] == "done"


def test_close_cleanup_runs_for_archive_summary_and_flat_layout_bodies(tmp_path):
    """The cleanup is keyed on the task id, not the body shape (Phase 134 review
    finding): an `archive_summary` close (no `body:`) and a flat-layout body (no
    open/deferred segment) both `continue` past the git-mv logic — their lock and
    parked markers must still be dropped."""
    repo = tmp_path / "consumer"
    (repo / "tasks").mkdir(parents=True)
    (repo / "tasks" / "TASK-0003.md").write_text("# TASK-0003\n", encoding="utf-8")
    index = {
        "schema_version": 1,
        "tasks": [
            {"id": "TASK-0003", "status": "in_progress", "body": "TASK-0003.md"},
            {"id": "TASK-0004", "status": "in_progress", "archive_summary": "done inline"},
        ],
    }
    (repo / "tasks" / "index.yml").write_text(yaml.safe_dump(index, sort_keys=False), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "seed"],
        cwd=repo, check=True,
    )
    (repo / "sysop" / "runtime" / "locks").mkdir(parents=True)
    parked = repo / "sysop" / "runtime" / "auto-build" / "parked"
    parked.mkdir(parents=True)
    for tid in ("TASK-0003", "TASK-0004"):
        (repo / "sysop" / "runtime" / "locks" / f"{tid}.lock").write_text("x", encoding="utf-8")
        (parked / f"{tid}__20260719T000000Z.md").write_text("park", encoding="utf-8")

    _run_close(repo, ["TASK-0003", "TASK-0004"])

    d = yaml.safe_load((repo / "tasks" / "index.yml").read_text(encoding="utf-8"))
    assert all(t["status"] == "done" for t in d["tasks"])
    assert list((repo / "sysop" / "runtime" / "locks").glob("*.lock")) == []
    assert list(parked.glob("*.md")) == []


def test_step3b_collect_has_loadbearing_mkdir():
    """Drift guard for the gdp cb8f3840 backport: the Step 3b collect command must
    create main's pending-docs dir before the silently-failing-when-dest-missing cp."""
    text = SKILL.read_text(encoding="utf-8")
    assert (
        "`mkdir -p sysop/runtime/pending-docs && "
        "cp <worktree>/sysop/runtime/pending-docs/*.md sysop/runtime/pending-docs/ 2>/dev/null`"
    ) in text


def test_final_report_template_carries_parked_markers_row():
    text = SKILL.read_text(encoding="utf-8")
    assert 'Parked markers: <removed TASK-ID list> (or "none")' in text
