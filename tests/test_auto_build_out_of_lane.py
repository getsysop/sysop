"""`/auto-build`'s task-ID subset lifts the current-focus filter for the IDs it names (`Q-635`).

Phase 97 made the subset an intersection with the filtered frontier, so a named task in
another phase was printed `EXCLUDED` with a pointer at `current_focus`. Wade reversed that
on 2026-09-30 and ruled its scope the same day: naming an ID lifts **only** the
current-focus filter. Open status, no lock / `user_action` / `on_hold_until`, and met
`depends_on` still apply, and each named out-of-lane task is printed with
`lane=OUT-OF-LANE (phase <N>)` so the Step 4 table can mark it.

These run Step 1's heredoc itself, extracted from the shipped skill, against a two-phase
index; the prose that tells the runner to carry the marker into Step 4 is pinned in
`tests/test_fix_in_branch_tier.py`.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from _heredoc_population import heredoc_containing

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTO_BUILD = REPO_ROOT / "core" / "skills" / "auto-build" / "SKILL.md"


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items()
            if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}


def _task(tid: str, phase: int, status: str = "open", depends_on: tuple[str, ...] = (),
          **extra: str) -> str:
    deps = ", ".join(depends_on)
    more = "".join(f", {k}: {v}" for k, v in extra.items())
    return (f"  - {{id: {tid}, title: T, phase: {phase}, status: {status}, effort: Low, "
            f"blast_radius: single-file, user_action: false, depends_on: [{deps}], "
            f"body: open/{tid}.md{more}}}\n")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Phase 6 is current-focus; phase 7 is the next lane.

    FOCUS-AAA is the in-lane control. LANE-BBB and LANE-CCC are ready phase-7 tasks.
    LANE-DEP depends on LANE-PRE, which is open, so it is not ready in any lane.
    LANE-LOCK holds a lock, LANE-HOLD is on hold, and LANE-ASK needs the human: the
    filters naming must not lift.
    LANE-KID (phase 7) and FOCUS-KID (phase 6) both depend on LANE-BBB.
    """
    root = tmp_path / "consumer"
    (root / "tasks" / "open").mkdir(parents=True)
    (root / "sysop" / "runtime" / "locks").mkdir(parents=True)
    (root / "sysop" / "runtime" / "locks" / "LANE-LOCK.lock").write_text(
        "task_id: LANE-LOCK\n", encoding="utf-8")
    (root / "tasks" / "index.yml").write_text(
        "schema_version: 2\nphases:\n"
        "  - {number: 6, title: Now, status: in_progress, current_focus: true}\n"
        "  - {number: 7, title: Next, status: planned}\n"
        "tasks:\n"
        + _task("FOCUS-AAA", 6)
        + _task("LANE-BBB", 7)
        + _task("LANE-CCC", 7)
        + _task("LANE-PRE", 7, status="in_progress")
        + _task("LANE-DEP", 7, depends_on=("LANE-PRE",))
        + _task("LANE-LOCK", 7)
        + _task("LANE-HOLD", 7, on_hold_until="2099-01-01")
        + _task("LANE-ASK", 7).replace("user_action: false", "user_action: true")
        + _task("LANE-KID", 7, depends_on=("LANE-BBB",))
        + _task("FOCUS-KID", 6, depends_on=("LANE-BBB",)),
        encoding="utf-8")
    return root


def _step1(root: Path, ids: str) -> list[str]:
    body = heredoc_containing(AUTO_BUILD, "inflight_verdict = {}")
    r = subprocess.run([sys.executable, "-", ids], input=body, cwd=root,
                       capture_output=True, text=True, env=_env())
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout.splitlines()


def _rows(out: list[str]) -> dict[str, list[str]]:
    return {ln.split("\t")[0]: ln.split("\t") for ln in out
            if ln and not ln.startswith(("#", "EXCLUDED"))}


def _excluded(out: list[str]) -> dict[str, str]:
    return {ln.split("\t")[1]: ln.split("\t")[2] for ln in out if ln.startswith("EXCLUDED\t")}


def test_without_a_subset_only_the_focus_lane_is_batched(repo):
    rows = _rows(_step1(repo, ""))
    assert set(rows) == {"FOCUS-AAA"}, rows
    assert rows["FOCUS-AAA"][-1] == "lane=focus", rows


def test_a_named_out_of_lane_task_is_selected_and_marked(repo):
    out = _step1(repo, "LANE-BBB FOCUS-AAA")
    rows = _rows(out)
    assert set(rows) == {"LANE-BBB", "FOCUS-AAA"}, out
    assert rows["LANE-BBB"][-1] == "lane=OUT-OF-LANE (phase 7)", out
    assert rows["FOCUS-AAA"][-1] == "lane=focus", out
    assert _excluded(out) == {}, out


def test_an_unnamed_out_of_lane_task_stays_out(repo):
    """Naming LANE-BBB lifts the filter for LANE-BBB, not for its lane."""
    rows = _rows(_step1(repo, "LANE-BBB"))
    assert set(rows) == {"LANE-BBB"}, rows
    assert "LANE-CCC" not in rows


@pytest.mark.parametrize("tid, reason", [
    ("LANE-DEP", "unmet depends_on: LANE-PRE"),
    ("LANE-LOCK", "active lock"),
    ("LANE-HOLD", "on hold until"),
    ("LANE-PRE", "status is 'in_progress'"),
    ("LANE-ASK", "user_action: true"),
])
def test_every_other_filter_still_applies_to_a_named_out_of_lane_task(repo, tid, reason):
    out = _step1(repo, f"{tid} LANE-CCC")
    assert tid not in _rows(out), out
    excluded = _excluded(out)
    assert tid in excluded and reason in excluded[tid], out
    assert "current-focus" not in excluded[tid] and "current_focus" not in excluded[tid], out


def test_no_excluded_reason_names_the_lane_any_more(repo):
    """The phase reason was the one the ruling removed; a named task that fails nothing
    else must not come back as `EXCLUDED` for its phase."""
    out = _step1(repo, "LANE-BBB LANE-CCC")
    assert _excluded(out) == {}, out
    assert all("lane=OUT-OF-LANE (phase 7)" == _rows(out)[t][-1] for t in ("LANE-BBB", "LANE-CCC"))


def test_unlock_count_counts_focus_and_named_dependents(repo):
    """LANE-BBB has two open dependents: FOCUS-KID in the focus lane, LANE-KID in its own.
    Neither is batchable in the same run as LANE-BBB (its dependency is not done); the count
    is next cycle's pool. Unnamed, LANE-KID is outside it; named, it is in it."""
    rows = _rows(_step1(repo, "LANE-BBB"))
    assert "unlocks=1" in rows["LANE-BBB"], rows
    rows = _rows(_step1(repo, "LANE-BBB LANE-KID"))
    assert "unlocks=2" in rows["LANE-BBB"], rows


def test_unlock_count_counts_only_open_dependents(repo):
    """LANE-PRE (in_progress) depends on nothing; give FOCUS-AAA a done dependent and an
    in-progress one, and neither counts."""
    idx = repo / "tasks" / "index.yml"
    idx.write_text(idx.read_text(encoding="utf-8")
                   + _task("FOCUS-DONE", 6, status="done", depends_on=("FOCUS-AAA",))
                   + _task("FOCUS-WIP", 6, status="in_progress", depends_on=("FOCUS-AAA",)),
                   encoding="utf-8")
    assert "unlocks=0" in _rows(_step1(repo, ""))["FOCUS-AAA"]
