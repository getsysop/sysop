"""Regression coverage for `/review-close` Step 3c's manual-smoke detection heredoc
(BeanRider ISSUE-0050). The heredoc lives inside `core/skills/review-close/SKILL.md`;
these tests extract its Python body and exercise the worktree-in-place scan + the
worktree-first basename dedup, so the fix — which is otherwise prose with no runtime
surface — has CI coverage. Guards against silent regression to the original bug (the
gate reading an empty main `sysop/runtime/pending-docs/` and returning NO_SMOKE_REQUIRED).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"


def _extract_smoke_heredoc() -> str:
    """Pull the Step 3c detection heredoc's Python body out of SKILL.md.

    Anchored on the unique invocation line that passes SMOKE_WORKTREE_DIRS as a quoted
    positional arg into a `python3 - <<'EOF'` heredoc; body runs to the terminating
    `EOF` line. (Sysop Phase 126 converted the former env-var prefix to a positional arg
    and derives the repo root from CWD, so the runner sets `cwd=` and argv, not env.)
    """
    text = SKILL.read_text(encoding="utf-8")
    m = re.search(r'python3 - "\$SMOKE_WORKTREE_DIRS" <<\'EOF\'\n', text)
    assert m, "could not locate the Step 3c smoke-gate heredoc opener in SKILL.md"
    start = m.end()
    end = text.index("\nEOF\n", start)
    return text[start:end]


SMOKE_SRC = _extract_smoke_heredoc()


def _run(repo: Path, worktree_dirs: list[Path]) -> str:
    # Phase 126: repo root is CWD, worktree-dir list is argv[1] (was REPO_ROOT /
    # SMOKE_WORKTREE_DIRS env vars). `cwd=repo` mirrors "run the heredoc from the repo root".
    smoke_arg = "\n".join(str(d) for d in worktree_dirs)
    r = subprocess.run(
        [sys.executable, "-c", SMOKE_SRC, smoke_arg],
        capture_output=True,
        text=True,
        cwd=str(repo),
        timeout=30,
    )
    assert r.returncode == 0, f"smoke-gate heredoc errored ({r.returncode}):\n{r.stderr}"
    return r.stdout


def _seed_main(tmp_path: Path) -> Path:
    main = tmp_path / "main"
    (main / "tasks").mkdir(parents=True)
    (main / "tasks" / "index.yml").write_text("schema_version: 1\ntasks: []\n", encoding="utf-8")
    (main / "sysop/runtime/pending-docs").mkdir(parents=True)
    return main


def _write_pending(dir_: Path, name: str, *, with_heading: bool) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    body = "---\nbranch: feat/x\nroadmap_ids: [FEAT-X]\ntype: feature\n---\n# Summary\n"
    if with_heading:
        body += "\n## Manual smoke required\n1. Drive the browser flow.\n"
    (dir_ / name).write_text(body, encoding="utf-8")


def test_worktree_authored_smoke_doc_is_detected(tmp_path):
    """The ISSUE-0050 fix: a smoke doc that lives only in the worktree (main's
    `sysop/runtime/pending-docs/` empty) must still trip the gate."""
    main = _seed_main(tmp_path)
    wt = tmp_path / "wt"
    _write_pending(wt / "sysop/runtime/pending-docs", "feat-x.md", with_heading=True)

    out = _run(main, [wt])
    assert out.startswith("SMOKE_REQUIRED"), out
    assert "Manual smoke required" in out


def test_empty_worktree_set_and_empty_main_is_no_smoke(tmp_path):
    """No worktree dirs + empty main → NO_SMOKE_REQUIRED (correctly scoped, not blind)."""
    main = _seed_main(tmp_path)
    out = _run(main, [])
    assert out.strip() == "NO_SMOKE_REQUIRED", out


def test_main_authored_doc_still_detected(tmp_path):
    """Non-worktree flow (doc authored directly on main) is unaffected."""
    main = _seed_main(tmp_path)
    _write_pending(main / "sysop/runtime/pending-docs", "feat-x.md", with_heading=True)
    out = _run(main, [])
    assert out.startswith("SMOKE_REQUIRED"), out


def test_fresh_worktree_doc_not_shadowed_by_stale_main_copy(tmp_path):
    """A#3 dedup guard: a stale main copy WITHOUT the heading must not shadow the
    fresher worktree copy WITH the heading. Worktree-first ordering makes the worktree
    win the basename dedup; main-first ordering (the bug) would miss the signal."""
    main = _seed_main(tmp_path)
    _write_pending(main / "sysop/runtime/pending-docs", "feat-x.md", with_heading=False)  # stale
    wt = tmp_path / "wt"
    _write_pending(wt / "sysop/runtime/pending-docs", "feat-x.md", with_heading=True)     # fresh

    out = _run(main, [wt])
    assert out.startswith("SMOKE_REQUIRED"), (
        f"stale main copy shadowed the fresh worktree doc (dedup ordering regressed):\n{out}"
    )
