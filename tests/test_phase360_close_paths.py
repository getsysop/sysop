"""Phase 360: the follow-up close of a held branch, and a check that never ran.

* `Q-646` — under `direct`, `/review-close` Step 2a step 0b had only the recorded-PR-head arm, so
  the follow-up close of a held branch a `direct` close had merged printed `NOT LANDED`, reviewed
  an empty diff, and raised false Step 2d halts. Step 0b now asks `/sitrep`'s
  `_merged_into_default` question when no head contains the branch. Every fixture here is built
  the way a `direct` close builds it (rebase, `--ff-only`, push) on a local bare `origin`.
* `Q-642` — under the `pr` PR-reuse shape, Step 4d's `--delete-branch` deleted the branch a held
  doc names. The note keys on Step 4c 1c's `HELD:` line, so its format is pinned by running
  `pending_doc_hold.py` itself.
* `Q-632` — Step 4d-1 read a job GitHub refused to start as a failing check. The two `jq`
  filters it prescribes are run against the job shapes upstream #782 recorded.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from skill_runner_text import text_of

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
from test_squash_provenance import (  # noqa: E402
    INDEX, LANDED_MARKER, SCRIPTS, _close, _fence_with, _from_tree, _hold, _ws_lock, git, sh, ss)
from test_squash_provenance import _landed  # noqa: E402

REPO = TESTS.parent


def _commit(w: Path, name: str, msg: str) -> None:
    (w / name).parent.mkdir(parents=True, exist_ok=True)
    (w / name).write_text(name + "\n")
    git(w, "add", name)
    git(w, "commit", "-qm", msg)


def _flip(w: Path, task: str, status: str) -> None:
    lines = (w / "tasks/index.yml").read_text().splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip() == f"- id: {task}":
            lines[i + 1] = f"    status: {status}\n"
    (w / "tasks/index.yml").write_text("".join(lines))
    git(w, "commit", "-qam", f"docs: claim {task}")


@pytest.fixture
def direct_closed(tmp_path):
    """One `direct` close has run and held B1's doc.

    * B1 (T1) — claimed on main, worked with a test file, rebased onto main and
      fast-forwarded, then main pushed. Its doc is held, so Step 6 kept the branch.
    * B2 (T2) — claimed and worked, not in that close: its own commit is in no default ref.
    """
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    w = tmp_path / "w"
    git(tmp_path, "clone", "-q", str(origin), str(w))  # empty: takes origin HEAD, main
    (w / "tasks").mkdir()
    (w / "tasks/index.yml").write_text(INDEX)
    git(w, "add", "-A")
    git(w, "commit", "-qm", "init")
    git(w, "push", "-q", "origin", "main")
    _flip(w, "T1", "in_progress")
    git(w, "branch", "B1")
    _flip(w, "T2", "in_progress")
    git(w, "branch", "B2")
    git(w, "checkout", "-q", "B1")
    _commit(w, "src/one.py", "feat: one")
    _commit(w, "tests/test_one.py", "test: one")
    git(w, "checkout", "-q", "B2")
    _commit(w, "src/two.py", "feat: two")
    git(w, "checkout", "-q", "B1")
    git(w, "rebase", "-q", "main")
    git(w, "checkout", "-q", "main")
    git(w, "merge", "-q", "--ff-only", "B1")
    git(w, "push", "-q", "origin", "main")
    return w


# ─────────────────────────────────────────────────────────────────────────────
# Q-646 — the `direct` arm of Step 2a step 0b
# ─────────────────────────────────────────────────────────────────────────────

def test_the_premise_a_direct_merged_branch_has_an_empty_diff(direct_closed):
    """What the follow-up close reviewed before the arm: nothing, so Step 2d halted falsely."""
    w = direct_closed
    assert git(w, "diff", "--name-only", "main...B1").stdout == ""
    assert git(w, "log", "--oneline", "main..B1").stdout == ""
    assert not list(w.glob("**/refs/sysop/merged-pr-heads/*"))


def _stamp(w: Path, branch: str, task: str = "T1"):
    """A doc a close HELD: Step 4c 1c's `check --stamp` writes `held_since:` on a held doc
    whose branch `HEAD` (or a recorded head) already contains, and the `direct` arm requires
    it (Wade, round 1). It records containment when held, not a merge: a zero-commit branch's
    held doc is stamped too (round 2, lenses D and E)."""
    d = w / "sysop/runtime/pending-docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{branch.replace('/', '-')}.md").write_text(
        f"---\nheld_since: '2026-10-06'\nbranch: \"{branch}\"\nroadmap_ids: [{task}]\n---\n\nheld\n")


def test_a_held_direct_merged_branch_is_landed_and_both_readers_agree(direct_closed):
    w = direct_closed
    assert _landed(w, "B1").stdout.startswith("NOT LANDED — no pending doc"), _landed(w, "B1")
    assert ss._merged_into_default(w, "B1", None, None, False) == ""
    _stamp(w, "B1")
    out = _landed(w, "B1")
    assert out.returncode == 0 and out.stdout.strip() == "LANDED: in main — held doc B1.md", out
    assert ss._merged_into_default(w, "B1", None, None, False) == "main"


def test_the_stamp_is_what_pending_doc_hold_writes(direct_closed):
    """The arm keys on `held_since:`, so run the writer: a held doc on a merged branch is
    stamped, and the stamped doc lands."""
    w = direct_closed
    _hold(w, "B1")
    idx = (w / "tasks/index.yml").read_text().replace(
        "  - id: T1\n    status: in_progress\n",
        "  - id: T1\n    status: in_progress\n    user_action: deploy it\n")
    (w / "tasks/index.yml").write_text(idx)
    assert _landed(w, "B1").stdout.strip() == \
        "NOT LANDED — main contains it, but no doc naming it carries held_since:", _landed(w, "B1")
    env = {**os.environ, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run([sys.executable, str(SCRIPTS / "pending_doc_hold.py"), "check", "--stamp"],
                       cwd=w, env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "(stamped now)" in r.stdout, r
    assert _landed(w, "B1").stdout.strip() == "LANDED: in main — held doc B1.md", _landed(w, "B1")


def test_an_unstamped_doc_at_the_tip_is_not_landed(direct_closed):
    """Round 1, lens C: a `--branch` claim's `/document-work` writes its doc straight into the
    main checkout's pending-docs, so a branch at main's tip with zero commits and that doc is
    not evidence of a close. Without the stamp it is reviewed, as before the phase. `/sitrep`
    routes it as merged; the close's review is the loud direction."""
    w = direct_closed
    git(w, "branch", "Z1", "main")
    _hold(w, "Z1")
    assert _landed(w, "Z1").stdout.strip() == \
        "NOT LANDED — main contains it, but no doc naming it carries held_since:", _landed(w, "Z1")
    assert ss._merged_into_default(w, "Z1", None, None, False) == "main"


def test_a_branch_with_its_own_unmerged_work_is_not_landed(direct_closed):
    w = direct_closed
    _stamp(w, "B2", "T2")
    out = _landed(w, "B2")
    assert out.stdout.strip() == "NOT LANDED — no recorded PR head contains it, and main does not", out
    assert ss._merged_into_default(w, "B2", None, None, False) == ""


def test_the_default_branch_itself_is_never_landed(direct_closed):
    w = direct_closed
    _stamp(w, "main")
    assert _landed(w, "main").stdout.startswith("NOT LANDED — no recorded PR head contains it"), \
        _landed(w, "main")
    assert ss._merged_into_default(w, "main", None, None, False) == ""


def test_origins_copy_alone_does_not_land_it(direct_closed):
    """Round 1, lenses A and C: landed in `origin/main` alone, Step 4c 1b counted the branch's
    commits against local HEAD and did not route the doc, and Step 6's `-d` refused it. The arm
    reads local `<default branch>` only, the ref both of those test against. `/sitrep` keeps
    origin's copy as a container; it only routes."""
    w = direct_closed
    _stamp(w, "B1")
    git(w, "reset", "-q", "--hard", "main~2")
    out = _landed(w, "B1")
    assert out.stdout.strip() == "NOT LANDED — no recorded PR head contains it, and main does not", out
    assert git(w, "rev-list", "--count", "B1", "^HEAD").stdout.strip() != "0"
    assert ss._merged_into_default(w, "B1", None, None, False) == "origin/main"


def test_a_published_copy_past_the_default_branch_is_live_work(direct_closed):
    w = direct_closed
    _stamp(w, "B1")
    git(w, "push", "-q", "origin", "B1:refs/heads/B1")
    assert _landed(w, "B1").stdout.startswith("LANDED: in main"), "a contained origin tip refused"
    other = w.parent / "other"
    git(w.parent, "clone", "-q", "-b", "B1", str(w.parent / "origin.git"), str(other))
    _commit(other, "src/more.py", "feat: more")
    git(other, "push", "-q", "origin", "B1")
    out = _landed(w, "B1")
    assert out.stdout.startswith("NOT LANDED — origin/B1 is at") and out.stdout.rstrip().endswith(
        "past main"), out


def _published_clone(w: Path, name: str = "clone-b1") -> Path:
    git(w, "push", "-q", "origin", "B1:refs/heads/B1")
    clone = w.parent / name
    git(w.parent, "clone", "-q", "-b", "B1", str(w.parent / "origin.git"), str(clone))
    return clone


def test_a_live_clone_from_the_lock_is_live_work(direct_closed):
    w = direct_closed
    _stamp(w, "B1")
    clone = _published_clone(w)
    _commit(clone, "src/clone.py", "feat: clone work")
    lock = _ws_lock(w, "T1", "B1", clone)
    assert _landed(w, "B1").stdout.startswith(f"NOT LANDED — workspace {clone} is at"), \
        _landed(w, "B1")
    assert ss._merged_into_default(w, "B1", lock, None, False) == ""


def _ignored_venv(w: Path, ws: Path) -> None:
    """BeanRider ISSUE-0043's shape: `.venv/` is ignored, so the main checkout's `.venv`
    directory is, but a symlink to it in a workspace is not matched by the trailing slash."""
    (w / ".gitignore").write_text(".venv/\n")
    (w / ".venv").mkdir(exist_ok=True)
    (ws / ".venv").symlink_to(w / ".venv")
    assert git(ws, "status", "--porcelain").stdout.strip() == "?? .venv", "fixture: not the shape"
    assert git(w, "check-ignore", "-q", str(w / ".venv")).returncode == 0, "fixture: target not ignored"


@pytest.mark.parametrize("mode", ["clone", "worktree"])
def test_a_lock_workspace_holding_only_an_ignored_venv_symlink_still_lands(direct_closed, mode):
    """Round 1, all three lenses: the lock loop read a bare `status --porcelain`, so a
    `--clone` workspace (the one a close never removes) holding only the ISSUE-0043 symlink
    sent the branch back to the full review. It now applies Step 1-pre's `noise()` test, and
    `/sitrep`'s `_live_work_past` the same one."""
    w = direct_closed
    _stamp(w, "B1")
    if mode == "clone":
        ws = _published_clone(w)
    else:
        ws = w.parent / "wt-b1"
        git(w, "worktree", "add", "-q", str(ws), "B1")
    _ignored_venv(w, ws)
    lock = _ws_lock(w, "T1", "B1", ws, mode=mode)

    def sitrep():
        # A worktree reaches `/sitrep` twice: as the lock's workspace, and as the linked
        # worktree `run_survey` passes with its `_worktree_dirty` (round 2, lens D).
        if mode == "clone":
            return ss._merged_into_default(w, "B1", lock, None, False)
        wt = ss.Worktree(path=ws, branch="B1", head="")
        return ss._merged_into_default(w, "B1", lock, wt, ss._worktree_dirty(ws, w))

    assert _landed(w, "B1").stdout.startswith("LANDED: in main"), _landed(w, "B1")
    assert sitrep() == "main"
    (ws / "scratch.txt").write_text("real untracked work\n")
    assert _landed(w, "B1").stdout.startswith(f"NOT LANDED — workspace {ws} has uncommitted"), \
        _landed(w, "B1")
    assert sitrep() == ""


def test_run_survey_reads_a_worktree_holding_only_the_symlink_as_merged(direct_closed, monkeypatch):
    """Round 2, lens D's reproduction, through `run_survey` itself: the linked worktree's
    `dirty` came from a bare `status --porcelain`, so the survey read `planning`."""
    w = direct_closed
    _stamp(w, "B1")
    ws = w.parent / "wt-b1"
    git(w, "worktree", "add", "-q", str(ws), "B1")
    _ignored_venv(w, ws)
    _ws_lock(w, "T1", "B1", ws, mode="worktree")
    monkeypatch.chdir(w)
    monkeypatch.setattr(ss, "_resolve_main_repo_root", lambda: w)
    t1 = {t.task_id: t for t in ss.run_survey().tasks}["T1"]
    assert t1.state == ss._MERGED_STATE and not t1.dirty, (t1.state, t1.dirty)

def test_a_relative_symlink_to_an_ignored_target_is_noise(direct_closed):
    """Round 2, lens D: both readers resolve a relative link against its own directory."""
    w = direct_closed
    _stamp(w, "B1")
    clone = _published_clone(w)
    (w / ".gitignore").write_text(".venv/\n")
    (w / ".venv").mkdir()
    (clone / ".venv").symlink_to(Path("..") / w.name / ".venv")
    assert git(clone, "status", "--porcelain").stdout.strip() == "?? .venv"
    lock = _ws_lock(w, "T1", "B1", clone)
    assert _landed(w, "B1").stdout.startswith("LANDED: in main"), _landed(w, "B1")
    assert ss._merged_into_default(w, "B1", lock, None, False) == "main"


@pytest.mark.parametrize("value", ["''", "null", "false"])
def test_an_empty_stamp_is_no_stamp(direct_closed, value):
    """Round 2, lens D: a falsy `held_since:` is not a stamp; `check --stamp` rewrites it."""
    w = direct_closed
    d = w / "sysop/runtime/pending-docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "B1.md").write_text(f'---\nheld_since: {value}\nbranch: "B1"\nroadmap_ids: [T1]\n---\n\nheld\n')
    assert _landed(w, "B1").stdout.strip() == \
        "NOT LANDED — main contains it, but no doc naming it carries held_since:", _landed(w, "B1")


def test_a_symlink_to_an_unignored_target_is_still_live_work(direct_closed):
    w = direct_closed
    _stamp(w, "B1")
    clone = _published_clone(w)
    (clone / "link").symlink_to(w / "tasks")
    lock = _ws_lock(w, "T1", "B1", clone)
    assert _landed(w, "B1").stdout.startswith(f"NOT LANDED — workspace {clone} has uncommitted"), \
        _landed(w, "B1")
    assert ss._merged_into_default(w, "B1", lock, None, False) == ""


def test_a_tag_named_like_the_branch_does_not_land_it(direct_closed):
    """Round 1, lens A (pre-existing since Phase 352): `for-each-ref --contains <bare name>`
    resolved a same-named tag first, so a recorded head containing the TAG landed a branch
    with unmerged work. Both readers now read `refs/heads/<branch>`."""
    w = direct_closed
    _hold(w, "B2", "T2")
    git(w, "tag", "B2", "main")
    git(w, "update-ref", "refs/sysop/merged-pr-heads/7", "main")
    out = _landed(w, "B2")
    assert out.stdout.startswith("NOT LANDED — no recorded PR head contains it"), out
    assert ss._landed_claim(w, "B2", None, None, False) == ""


def test_a_placeholder_default_branch_stops(direct_closed):
    w = direct_closed
    script = _from_tree(_fence_with(_close(), LANDED_MARKER))
    out = sh(w, script.replace('"<branch>"', '"B1"'))
    assert out.returncode == 3 and "STOP" in out.stdout, out
    out = sh(w, script.replace('"<branch>"', '"B1"').replace('"<default branch>"', '""'))
    assert out.returncode == 3, out


def test_step_4a_item_1_prints_no_recorded_head_for_it(direct_closed):
    """The arm's prose says item 1 prints `RECORDED HEAD: none` for a branch landed in a ref."""
    w = direct_closed
    _stamp(w, "B1")
    script = _from_tree(_fence_with(_close(), 'python3 sysop/scripts/pr_head_check.py "<branch>"'))
    out = sh(w, script.replace('"<branch>"', '"B1"').replace('"<merge target>"', '"main"'))
    assert out.returncode == 0 and out.stdout.strip() == "RECORDED HEAD: none", out


def test_step_4c_1b_scores_it_merged(direct_closed):
    """Q-646: 'Step 4c 1b still routes the doc on ancestry'. Its count is 0 for B1."""
    w = direct_closed
    assert git(w, "rev-list", "--count", "B1", "^HEAD").stdout.strip() == "0"


def test_step_6s_safe_delete_accepts_it(direct_closed):
    w = direct_closed
    git(w, "branch", "-d", "B1")


# ─────────────────────────────────────────────────────────────────────────────
# Q-642 — the `HELD:` line the reuse-shape note keys on
# ─────────────────────────────────────────────────────────────────────────────

def test_the_held_line_names_the_branch(direct_closed):
    w = direct_closed
    _hold(w, "feature/reused", "T1")
    idx = (w / "tasks/index.yml").read_text().replace(
        "  - id: T1\n    status: in_progress\n",
        "  - id: T1\n    status: in_progress\n    user_action: deploy it\n")
    (w / "tasks/index.yml").write_text(idx)
    env = {**os.environ, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run([sys.executable, str(SCRIPTS / "pending_doc_hold.py"), "check"], cwd=w,
                       env=env, capture_output=True, text=True)
    held = [ln for ln in r.stdout.splitlines() if ln.startswith("HELD:")]
    assert r.returncode == 0 and len(held) == 1, r
    assert "— branch feature/reused;" in held[0], held


def test_the_reuse_merge_keeps_the_flag_in_the_shipped_command():
    """The default command keeps `--delete-branch`; only the held-doc note drops it."""
    block = _fence_with(_close(), 'gh pr merge "<PR>" --squash')
    assert 'gh pr merge "<PR>" --squash --delete-branch' in block


# ─────────────────────────────────────────────────────────────────────────────
# Q-632 — the never-started test, run against the shapes #782 recorded
# ─────────────────────────────────────────────────────────────────────────────

JQ = shutil.which("jq")


def _jq_filters() -> tuple[str, str]:
    import re
    text = _close()
    checks = re.search(r"gh pr checks \"<PR>\" --json name,bucket,link --jq '([^']*)'", text)
    jobs = re.search(r'gh api "repos/\{owner\}/\{repo\}/actions/jobs/<job id>" --jq \'([^\']*)\'',
                     text)
    assert checks and jobs, "Step 4d-1's two filters moved"
    return checks.group(1), jobs.group(1)


def _run_jq(expr: str, doc) -> str:
    if JQ is None:
        if os.environ.get("CI"):
            pytest.fail("jq is not installed on the CI runner; the Q-632 filters went untested")
        pytest.skip("jq not installed")
    r = subprocess.run([str(JQ), "-r", expr], input=json.dumps(doc), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _job(name, status, conclusion, steps, runner="ubuntu-24.04"):
    return {"id": 105923837075, "run_id": 35453204281, "name": name, "status": status,
            "conclusion": conclusion, "steps": [{"name": f"s{i}"} for i in range(steps)],
            "runner_name": runner}


@pytest.mark.parametrize("job,want", [
    # Run 35453204281 attempt 1: refused for billing.
    (_job("Gitleaks Secret Scan", "completed", "failure", 0, runner=""),
     "NEVER STARTED: Gitleaks Secret Scan (run 35453204281)"),
    # Attempt 3, after the budget was raised: it ran five steps.
    (_job("Gitleaks Secret Scan", "completed", "success", 5),
     "RAN: Gitleaks Secret Scan — success, 5 step(s)"),
    # A skipped job also records no steps; the conclusion is what tells them apart.
    (_job("Slack Alert on Failure", "completed", "skipped", 0, runner=""),
     "RAN: Slack Alert on Failure — skipped, 0 step(s)"),
    # A job that ran and failed is a real failure.
    (_job("pytest", "completed", "failure", 3), "RAN: pytest — failure, 3 step(s)"),
    # Not finished yet: no verdict of never started.
    (_job("pytest", "in_progress", None, 0), "RAN: pytest — null, 0 step(s)"),
])
def test_the_job_filter_separates_a_refused_job(job, want):
    assert _run_jq(_jq_filters()[1], job) == want


def test_a_job_without_a_steps_array_is_not_called_never_started():
    job = _job("x", "completed", "failure", 0)
    del job["steps"]
    assert _run_jq(_jq_filters()[1], job).startswith("RAN: x")


def test_the_checks_filter_lists_only_failing_checks_with_links():
    checks = [
        {"name": "Gitleaks Secret Scan", "bucket": "fail",
         "link": "https://github.com/o/r/actions/runs/35453204281/job/105923837075"},
        {"name": "pytest", "bucket": "pass", "link": "https://github.com/o/r/actions/runs/1/job/2"},
        {"name": "ci/jenkins", "bucket": "fail", "link": "https://jenkins.example/job/9"},
        {"name": "lint", "bucket": "pending", "link": ""},
    ]
    assert _run_jq(_jq_filters()[0], checks).splitlines() == [
        "Gitleaks Secret Scan\thttps://github.com/o/r/actions/runs/35453204281/job/105923837075",
        "ci/jenkins\thttps://jenkins.example/job/9",
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Hash pins over the text Phase 360 decided
# ─────────────────────────────────────────────────────────────────────────────
#
# The heredoc and the two `jq` filters are executed above. What a test cannot execute is the
# prose the runner acts on: when the reuse shape drops `--delete-branch`, what a never-started
# check routes to, and where a landed branch is merged and deleted. The `## After merge` ruling
# (Wade, 2026-10-06) moved `test_fix_in_branch_tier.py`'s three pins over that text instead.
# A deliberate change moves its pin in the same commit (`_print_pins()`).

from _reversal import slice_between  # noqa: E402
from test_fix_in_branch_tier import (_anchor_count, _pin_hash, _pin_liveness,  # noqa: E402
                                     _pin_span)

CLOSE_MD = REPO / "core/skills/review-close/SKILL.md"
WORKFLOW_MD = REPO / "core/companion/docs/WORKFLOW.md"

SPANS: dict[str, tuple[Path, str, str, bool]] = {
    "4d reuse keeps a held branch": (CLOSE_MD, "> **PR-reuse shape only — keep a held doc's branch",
                                     "\n>\n", False),
    "4d-1 never started": (CLOSE_MD, "- **First ask whether each failing check ever ran",
                           "- **Report** the PR URL", False),
    "step 6 reuse held exception": (CLOSE_MD, "**Under the PR-reuse shape both of the above are usually",
                                    "\n", False),
    "step 6 direct landed included": (CLOSE_MD, "**`direct` policy — per-branch cleanup.**", "\n", False),
    "step 8 branches": (CLOSE_MD, "Branches:      <merged list", "\nBatches:", True),
    "2a direct arm prose": (CLOSE_MD, "**`LANDED: in <ref>`** means no recorded head", " **`NOT LANDED", False),
    # Round 1, lens A: two Phase 360 edits deletable with every test green.
    "4d command 5 comment": (CLOSE_MD, "# 5. confirm mergeability, then squash-merge", "\ngh pr view", True),
    "4d denied escape": (CLOSE_MD, "**If a `gh pr` command is silently denied**", "\n", False),
    # The author battery's one survivor after round 1 (P10).
    "4d-1 report carries after merge": (CLOSE_MD, "- **Report** the PR URL and the failing check name(s)", "\n", False),
    # Round 2, lens E: deletable with every test green.
    "WORKFLOW step 8 delete-branch": (WORKFLOW_MD, "squash-merge its PR with a normal authenticated `gh pr merge --squash` (with",
                                      "**not** `--auto`", False),
}

PINS = {
    # Regenerate with:  .venv/bin/python3 -c "import sys; sys.path.insert(0,'tests'); import test_phase360_close_paths as T; T._print_pins()"
    "4d reuse keeps a held branch": "a134dd4747429799",
    "4d-1 never started": "4149b10514f2fd42",
    "step 6 reuse held exception": "602f883ac673e0e4",
    "step 6 direct landed included": "d5b064330debb2a0",
    "step 8 branches": "e035237e081dc163",
    "2a direct arm prose": "87ed7af7f8b8e75f",
    "4d command 5 comment": "b515e737d1704198",
    "4d denied escape": "2fdf16c0a6a83552",  # Phase 393's round: "the `direct`-policy push above" names its step file, `steps/4d-direct.md`
    "4d-1 report carries after merge": "75ecdcd4cf8ac672",
    "WORKFLOW step 8 delete-branch": "75431f128e51c545",
}


def _located(label: str) -> tuple[str, str, int]:
    path, start, end, _ = SPANS[label]
    text = text_of(path)
    span = slice_between(text, start, end, label)
    return text, span, text.index(span)


def _span(label: str) -> str:
    text, span, at = _located(label)
    return _pin_span(SPANS[label][0], text, at, span)


def _print_pins() -> None:
    for label in SPANS:
        print(f'    "{label}": "{_pin_hash(_span(label))}",')


@pytest.mark.parametrize("label", sorted(SPANS))
def test_the_decided_text_is_pinned(label: str) -> None:
    got = _pin_hash(_span(label))
    assert label in PINS, f'{label}: no pin recorded; add "{label}": "{got}"'
    assert got == PINS[label], (
        f"{label} changed (hash {got}, pinned {PINS[label]}). Phase 360 decided this text. "
        "If the edit is deliberate, move the pin in the same commit and record why.")


@pytest.mark.parametrize("label", sorted(SPANS))
def test_every_span_start_anchor_is_unique(label: str) -> None:
    path, start, _, _ = SPANS[label]
    assert _anchor_count(text_of(path), start) == 1, label


@pytest.mark.parametrize("label", sorted(SPANS))
def test_every_span_is_live(label: str) -> None:
    text, _, at = _located(label)
    problem = _pin_liveness(SPANS[label][0], text, at, SPANS[label][3])
    assert problem is None, f"{label} {problem}"


def test_every_pin_has_a_span() -> None:
    assert set(PINS) == set(SPANS), set(PINS) ^ set(SPANS)
