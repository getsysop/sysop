"""Phase 380 (`Q-664`): a branch Step 3b collected before an early park, closed by the next run.

Spec § 13.3 ruled that an early park of an unattended close (before Step 4-pre) is recorded and
does not block the next run (ruling (ak)), and recorded one claim as unverified: that a branch
whose doc Step 3b copied into main and whose worktree Step 3b removed closes cleanly on the next
run. The ordinary collision the collect is written for is a doc collected twice from a worktree
that is still there; with the worktree gone the next run takes Step 3b step 0's empty-workspace
arm instead, which nobody had run.

These tests run that sequence through the shipped heredocs, extracted from `SKILL.md` by the
modules that already pin them: night 1 is step 0, the collect and step (b)'s unforced remove, and
then the run ends; night 2 is Step 2a step 0b's landed check, Step 3c's detection, Step 3b
step 0 again, the merge, and Step 4c 1b's hold test and ancestry count.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from skill_runner_text import text_of

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
from test_review_close_smoke_gate import SMOKE_SCRIPT, SMOKE_SRC  # noqa: E402
from test_review_close_workspace_discovery import COLLECT_ARGV, COLLECT_PY, DISCOVER_ARGV  # noqa: E402
from test_squash_provenance import _landed  # noqa: E402

SCRIPTS = TESTS.parent / "core" / "companion" / "scripts"
SKILL = TESTS.parent / "core" / "skills" / "review-close" / "SKILL.md"
BRANCH = "feat/x"


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)} failed:\n{r.stderr}"
    return r.stdout.strip()


def _discover(repo: Path) -> tuple[str, str]:
    listing = _git(repo, "worktree", "list", "--porcelain")
    r = subprocess.run([sys.executable, *DISCOVER_ARGV, BRANCH, listing, repo.name],
                       cwd=str(repo), capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    ws, _, shape = r.stdout.strip().splitlines()[-1].partition(" shape=")
    return ws[len("workspace="):], shape


def _collect(repo: Path, wt: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *COLLECT_ARGV, str(wt), BRANCH],
                          cwd=str(repo), capture_output=True, text=True, timeout=30)


def _smoke(repo: Path, worktree_dirs: list[Path]) -> str:
    r = subprocess.run([sys.executable, SMOKE_SCRIPT, "\n".join(map(str, worktree_dirs)),
                        BRANCH, "main"], cwd=str(repo), capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.fixture
def night_one(tmp_path: Path) -> tuple[Path, Path]:
    """A consumer whose close collected `feat/x` at Step 3b, removed its worktree, and then
    parked early: main holds the branch's only doc, the lock is kept, nothing merged."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    repo = tmp_path / "consumer"
    _git(tmp_path, "clone", "-q", str(origin), str(repo))
    _git(repo, "checkout", "-q", "-b", "main")
    (repo / ".gitignore").write_text("sysop/runtime/\n")
    (repo / "tasks").mkdir()
    (repo / "tasks/index.yml").write_text(
        "schema_version: 1\ntasks:\n  - id: T1\n    status: in_progress\n"
        "    title: one\n    body: open/T1.md\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    _git(repo, "push", "-q", "origin", "main")

    wt = tmp_path / f"{repo.name}-feat-x"
    _git(repo, "worktree", "add", "-q", "-b", BRANCH, str(wt))
    (wt / "src").mkdir()
    (wt / "src/x.py").write_text("X = 1\n")
    _git(wt, "add", "-A")
    _git(wt, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "feat: x")
    tip = _git(wt, "rev-parse", "HEAD")
    docs = wt / "sysop/runtime/pending-docs"
    docs.mkdir(parents=True)
    (docs / "feat-x.md").write_text(
        f'---\nbranch: "{BRANCH}"\nbranch_tip: "{tip}"\nroadmap_ids: [T1]\ntype: feature\n'
        'summary: "x"\n---\n\n## Manual smoke required\n1. Drive the flow.\n')
    locks = repo / "sysop/runtime/locks"
    locks.mkdir(parents=True)
    (locks / "T1.lock").write_text(f"branch: {BRANCH}\nmode: worktree\nworkspace: {wt}\n")

    # Night 1, Step 3b for feat/x: step 0, the collect, step (b)'s unforced remove.
    assert _discover(repo)[1] == "worktree"
    r = _collect(repo, wt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PENDING-DOC COLLECTED" in r.stdout, r.stdout
    _git(repo, "worktree", "remove", str(wt))
    # The early park: the run ends here. Nothing merged, the lock stays.
    assert (repo / "sysop/runtime/pending-docs/feat-x.md").is_file()
    assert not wt.exists()
    return repo, wt


def test_night_two_finds_no_workspace_and_the_exit_8_test_passes(night_one):
    repo, _ = night_one
    assert _discover(repo) == ("<none>", "<none>")
    # Step 3b step 0's hand-applied exit-8 test: a lock names the branch, and a doc on main
    # claims it, so the branch is not SKIP'd.
    held = [d for d in (repo / "sysop/runtime/pending-docs").glob("*.md")
            if f'branch: "{BRANCH}"' in d.read_text()]
    assert held, "no doc on main claims the branch: exit 8 would SKIP it"


def test_night_two_reviews_it_as_not_landed(night_one):
    repo, _ = night_one
    out = _landed(repo, BRANCH)
    assert out.returncode == 0, out
    assert out.stdout.startswith("NOT LANDED — no recorded PR head contains it, and main does not"), \
        out.stdout


def test_night_two_smoke_gate_still_reads_the_collected_doc(night_one):
    repo, _ = night_one
    out = _smoke(repo, [])
    assert out.startswith("SMOKE_REQUIRED"), out
    assert "Manual smoke required" in out


def test_night_two_merges_and_step_4c_routes_the_doc(night_one):
    repo, _ = night_one
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "merge", "-q", "--no-ff",
         "-m", "merge feat/x", BRANCH)
    hold = subprocess.run([sys.executable, str(SCRIPTS / "pending_doc_hold.py"), "check"],
                          cwd=str(repo), capture_output=True, text=True, timeout=30)
    assert hold.returncode == 0, hold.stdout + hold.stderr
    assert "HELD:" not in hold.stdout, hold.stdout
    assert _git(repo, "rev-list", "--count", BRANCH, "^HEAD") == "0"


def _empty_ws_arm() -> str:
    text = text_of(SKILL)
    start = text.index("**If `WS` is empty**")
    return text[start:text.index("\n", start)]


def test_a_head_moved_between_nights_is_skipped_as_stale(night_one):
    """The collect's `branch_tip:` staleness test (exit 6) never runs on night two, since
    there is no workspace to collect from. Step 3b step 0's empty-workspace arm applies it by
    hand: run the command the arm prescribes, and it must see the commit."""
    repo, tmp = night_one
    doc = repo / "sysop/runtime/pending-docs/feat-x.md"
    tip = re.search(r'branch_tip: "([0-9a-f]+)"', doc.read_text()).group(1)
    other = tmp.parent / "elsewhere"
    _git(repo, "worktree", "add", "-q", str(other), BRANCH)
    (other / "src/y.py").write_text("Y = 1\n")
    _git(other, "add", "-A")
    _git(other, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "feat: y")
    _git(repo, "worktree", "remove", str(other))
    assert _discover(repo) == ("<none>", "<none>")
    arm = _empty_ws_arm()
    assert "When step 0 printed `shape=<none>`" in arm and "exit 6's row" in arm, arm
    cmds = re.findall(r"`(git rev-list --count [^`]+)`", arm)
    assert cmds == ['git rev-list --count "<branch_tip>..<branch>"'], cmds
    cmd = cmds[0].replace("<branch_tip>", tip).replace("<branch>", BRANCH)
    r = subprocess.run(["bash", "-c", cmd], cwd=str(repo), capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "1", r.stdout + r.stderr


def test_an_unmoved_head_counts_zero(night_one):
    repo, _ = night_one
    doc = repo / "sysop/runtime/pending-docs/feat-x.md"
    tip = re.search(r'branch_tip: "([0-9a-f]+)"', doc.read_text()).group(1)
    assert _git(repo, "rev-list", "--count", f"{tip}..{BRANCH}") == "0"
