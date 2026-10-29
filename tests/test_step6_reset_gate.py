"""`Q-651` — Step 6's reset must not drop a commit made on local `<default branch>` after Step 4d's push.

Under `pr` policy, `gh pr merge --delete-branch` returns HEAD to the default branch, and a
concurrent `claim_task.sh --commit-claim` (which commits only while HEAD is there) can land on it
during Step 5's wait. The squash does not contain that commit, and `git reset --hard
origin/<default branch>` drops it; the tracked-tree gate before the reset prints `CLEAN`.

These run the commands the skill prescribes, read out of `SKILL.md` rather than retyped, against a
fixture: Step 4d's `git rev-parse` at the push, Step 6's `git rev-list` gate, and the rebase it
offers instead of the reset.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
from skill_runner_text import text_of

REPO = Path(__file__).resolve().parent.parent
CLOSE = REPO / "core/skills/review-close/SKILL.md"

_ENV = {k: v for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
_ENV.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")


def _sh(cwd: Path, cmd: str) -> str:
    r = subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True, env=_ENV)
    assert r.returncode == 0, (cmd, r.stderr)
    return r.stdout.strip()


def _text() -> str:
    return text_of(CLOSE)


def _step(name: str, nxt: str) -> str:
    t = _text()
    return t[t.index(name):t.index(nxt, t.index(name))]


def _prescribed() -> dict[str, str]:
    step6 = _step("## Step 6: Clean Up", "## Step 7:")
    pr = _step("#### `pr` policy", "## Step 5:")
    record = re.findall(r"^\s*(git rev-parse \"<default branch>\")$", pr, re.M)
    gate = re.findall(r"^\s*(git rev-list \"<PUSHED FROM>\.\.<default branch>\" \^\"origin/<default branch>\")$",
                      step6, re.M)
    rebase = re.findall(r"`(git rebase --onto \"origin/<default branch>\" \"<PUSHED FROM>\" "
                        r"\"<default branch>\")`", step6)
    assert len(record) == 2, "Step 4d must print local <default branch>'s SHA under both shapes"
    assert len(gate) == 1 and len(rebase) == 1, "Step 6's PUSHED FROM gate or its rebase moved"
    return {"record": record[0], "gate": gate[0], "rebase": rebase[0]}


def _sub(cmd: str, pushed: str = "") -> str:
    return cmd.replace("<default branch>", "main").replace("<PUSHED FROM>", pushed)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _sh(tmp_path, "git init -q --bare -b main origin.git && git clone -q origin.git repo 2>/dev/null")
    root = tmp_path / "repo"
    _sh(root, "git config user.email t@t && git config user.name t && echo base > f && "
              "git add f && git commit -qm base && git push -q origin main && "
              "echo flip1 > tasks && git add tasks && git commit -qm 'claim: T-1'")
    return root


def _squash_on_origin(tmp_path: Path) -> None:
    _sh(tmp_path, "git clone -q origin.git gh 2>/dev/null && cd gh && git config user.email t@t && "
                  "git config user.name t && echo flip1 > tasks && git add tasks && "
                  "git commit -qm 'squash (#1)' && git push -q origin main")


def test_the_gate_names_a_commit_made_after_the_push_and_the_rebase_keeps_it(repo, tmp_path):
    cmds = _prescribed()
    pushed = _sh(repo, _sub(cmds["record"]))
    _squash_on_origin(tmp_path)
    _sh(repo, "echo flip2 >> tasks && git add tasks && git commit -qm 'claim: T-2'")
    late = _sh(repo, "git rev-parse HEAD")
    _sh(repo, "git fetch -q origin main")
    assert _sh(repo, "git diff --quiet HEAD -- && echo CLEAN") == "CLEAN"  # the old gate is blind
    assert _sh(repo, _sub(cmds["gate"], pushed)).split() == [late]
    # what the reset the gate now refuses would have done (round 1, record lens: asserted, not run)
    _sh(repo, "git checkout -q -b probe && git reset -q --hard origin/main")
    assert _sh(repo, f"git merge-base --is-ancestor {late} HEAD && echo kept || echo dropped") == "dropped"
    _sh(repo, "git checkout -q main && git branch -q -D probe")
    _sh(repo, _sub(cmds["rebase"], pushed))
    assert _sh(repo, "git log --format=%s -2").splitlines() == ["claim: T-2", "squash (#1)"]
    assert _sh(repo, "git rev-parse HEAD~1") == _sh(repo, "git rev-parse origin/main")
    assert "flip2" in (repo / "tasks").read_text()


def test_the_gate_is_empty_when_nothing_landed_after_the_push(repo, tmp_path):
    cmds = _prescribed()
    pushed = _sh(repo, _sub(cmds["record"]))
    _squash_on_origin(tmp_path)
    _sh(repo, "git fetch -q origin main")
    assert _sh(repo, _sub(cmds["gate"], pushed)) == ""


def test_no_false_stop_when_gh_fast_forwards_local_main(repo, tmp_path):
    """Round 1 (semantics lens): under the PR-reuse shape, and the integration shape with no
    local-only commits, `gh pr merge` fast-forwards local main onto the squash, so a bare
    `PUSHED FROM..main` printed the squash itself. `^origin/main` excludes it; a claim made after
    the fast-forward is still named."""
    cmds = _prescribed()
    _sh(repo, "git reset -q --hard origin/main")  # no local-only commits
    pushed = _sh(repo, _sub(cmds["record"]))
    _squash_on_origin(tmp_path)
    _sh(repo, "git fetch -q origin main && git merge -q --ff-only origin/main")
    assert _sh(repo, _sub(cmds["gate"], pushed)) == ""
    _sh(repo, "echo flip3 >> tasks && git add tasks && git commit -qm 'claim: T-3'")
    assert _sh(repo, _sub(cmds["gate"], pushed)).split() == [_sh(repo, "git rev-parse HEAD")]


def test_a_dirty_resume_returns_to_the_new_check_not_the_reset():
    step6 = _step("## Step 6: Clean Up", "## Step 7:")
    assert "continue from the commits-after-push check below when it reports `CLEAN`" in step6
    assert "continue from the reset when it reports" not in step6


def test_the_gate_precedes_the_reset_and_forbids_it():
    step6 = _step("## Step 6: Clean Up", "## Step 7:")
    gate = step6.index('git rev-list "<PUSHED FROM>..<default branch>"')
    reset = step6.index("git reset --hard origin/<default branch>\n")
    assert gate < reset
    rule = step6[gate:reset]
    assert "**If it printed any SHA, do not run the reset.**" in rule
    assert "skip the reset" in rule and "do not reset" in rule
