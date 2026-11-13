"""Phase 488 (`Q-750`, `wade-cms/sysop` #944): Step 6's `pr` cleanup comments on each open PR a
remote branch delete would close, before it deletes.

Step 4a's published arm takes a pushed branch with `--no-ff`; under `pr` the merge target is
squash-merged, so GitHub never marks the branch's own PR merged, and Step 6's
`git push origin --delete` closes it unmerged. Item 3 of the arm asked for a comment first, but
named no command, and the integration PR it should point at does not exist until Step 4d. GDP's
close of 2026-10-07 closed PR #1103 with no comment. Item 0 of `steps/6-pr-cleanup.md` now looks
the PRs up at the delete, posts through the comment shape Step 4d already ships, re-reads, and
keeps the branch when the comment is not there.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from _bash_rule_match import binds
from skill_runner_text import text_of

REPO = Path(__file__).resolve().parent.parent
STEPS = REPO / "core" / "skills" / "review-close" / "steps"
CLEANUP = (STEPS / "6-pr-cleanup.md").read_text(encoding="utf-8")
PUBLISHED = (STEPS / "4a-published.md").read_text(encoding="utf-8")
SETTINGS = json.loads((REPO / "core" / "companion" / ".claude" / "settings.json").read_text(encoding="utf-8"))
ALLOW = SETTINGS["permissions"]["allow"]


def _item0() -> str:
    i = CLEANUP.index("0. **Comment on each open PR whose head is a branch item 2 will delete")
    return CLEANUP[i:CLEANUP.index("\n1. Delete the **local** branch", i)]


def _fenced(block: str) -> list[str]:
    return [m.strip() for m in re.findall(r"```bash\n(.*?)```", block, re.S)]


def _lookup_and_view() -> tuple[str, str]:
    lookup, view = _fenced(_item0())
    return lookup, view


def _group(pattern: str, text: str) -> str:
    m = re.search(pattern, text)
    assert m, pattern
    return m.group(1)


def _jq_of(command: str) -> str:
    return _group(r"--jq '(.*)'$", command)


def test_item_0_runs_before_either_delete():
    i0 = CLEANUP.index("0. **Comment on each open PR whose head is a branch item 2 will delete")
    assert i0 < CLEANUP.index("1. Delete the **local** branch") < CLEANUP.index("2. Delete the **remote** branch")


def test_the_lookup_lists_open_same_repository_prs_drafts_included():
    lookup, _ = _lookup_and_view()
    assert lookup.startswith('gh pr list --head "<branch>" --state open ')
    assert "select(.isCrossRepository == false)" in lookup, "a fork's same-named head is not closed by this delete"
    assert "isDraft" not in lookup, "deleting the head closes a draft PR too, so a draft needs the comment"
    assert "--base" not in lookup, "the delete closes the PR whatever its base"
    assert "--draft" not in lookup and "--limit" not in lookup, "every open same-repo PR on the head needs the comment"
    assert "For each branch item 2 will delete remotely" in _item0(), "item 0 covers every remote delete, not only 4a's published arm"


def test_the_marker_the_view_counts_is_the_body_the_post_writes():
    _, view = _lookup_and_view()
    marker = _group(r'contains\("([^"]+)"\)', view)
    assert marker == "Superseded by #<PR>:"
    body = _group(r"reading `([^`]+)`", _item0())
    assert body.startswith(marker), "a body the view does not count would be posted again, or never read as on"


def test_the_post_uses_the_shipped_comment_shape_and_no_new_rule():
    item = _item0()
    post = 'gh api "repos/{owner}/{repo}/issues/<N>/comments" -F body=@sysop/runtime/review-close-pr-body.md'
    assert post in item
    assert post.replace("<N>", "<PR number>") in (STEPS / "4d-pr.md").read_text(encoding="utf-8"), (
        "item 0 is meant to reuse Step 4d's shipped post, whose rules every release tag seeds")
    assert "gh pr comment" not in item, "a new `gh pr comment` rule is missing from older settings and is denied under dontAsk"
    assert "Edit(/sysop/runtime/review-close-pr-body.md)" in ALLOW


@pytest.mark.parametrize("rule, command", [
    ("Bash(gh pr list:*)", None),
    ("Bash(gh pr view:*)", None),
    ("Bash(gh api:*)", 'gh api "repos/{owner}/{repo}/issues/1103/comments" -F body=@sysop/runtime/review-close-pr-body.md'),
])
def test_each_command_binds_a_seeded_rule(rule, command):
    assert rule in ALLOW
    if command is None:
        lookup, view = _lookup_and_view()
        command = (lookup if "list" in rule else view).replace("<branch>", "tasks/x").replace(
            "<N>", "1103").replace("<PR>", "1108")
    assert binds(rule, command), command


def test_the_arms_route_each_state():
    item = " ".join(_item0().split())
    _, view = _lookup_and_view()
    assert '"\\(.state) \\([' in view, "the view must print the PR's state, not a constant"
    assert "**`OPEN 0` on the first read**: write `sysop/runtime/review-close-pr-body.md` fresh with your file tool" in item
    assert "Read it first if it exists" in item
    assert "If the write fails or is denied, post nothing and take the last arm." in item
    assert ", then run the `gh pr view` line again." in item, "without the re-read nothing confirms the comment is on"
    assert "**`OPEN` with a count of 1 or more**: the comment is on; go on." in item
    assert "**`CLOSED` or `MERGED`**: this delete does not close it; go on." in item


def test_the_comment_names_the_pr_that_carried_the_commits():
    item = " ".join(_item0().split())
    assert ("`#<N>` for a branch Step 2a approved as landed by PR #<N> (Step 8's `Squash provenance:` row names it, "
            "under `--land` too), otherwise this close's merged PR (Step 4d's, or `PR:` under `--land`)") in item


def test_a_comment_that_does_not_post_keeps_the_branch():
    item = " ".join(_item0().split())
    assert "**Any command or write in this item that fails or is denied, or a count still `0` after the post**: run neither item 1 nor item 2 for that branch" in item
    assert "Nothing printed and exit 0: go on to item 1. A non-zero exit is the last arm below." in item, (
        "a failed or denied lookup prints nothing too; read as no PR, it deletes the branch")
    assert "Step 8's `Remaining:` remote-branch row" in item
    assert "Put each `<branch> #<N>` whose count reads 1 or more on Step 8's `Superseded PRs:` row. A branch the last arm kept goes on `Remaining:` only." in item
    skill = " ".join(text_of(REPO / "core" / "skills" / "review-close" / "SKILL.md").split())
    assert "did not succeed, and each branch its item 0 kept." in skill, "Step 8's Remaining row must take a kept branch"


def test_item_3_points_at_step_6_and_runs_nothing():
    flat = " ".join(PUBLISHED.split())
    i = flat.index("3. **Under the `pr` policy, a published branch's own PR does not survive this close")
    item3 = flat[i:]
    assert "Nothing to run here" in item3 and "does not exist until Step 4d opens it" in item3
    assert "Step 6's `pr` cleanup (its item 0) comments on that PR before it deletes the branch" in item3
    assert "Before Step 6 runs, comment" not in item3
    assert "```" not in item3


JQ = shutil.which("jq") or ""


def _run_jq(program: str, data) -> str:
    return subprocess.run([JQ, "-r", program], input=json.dumps(data), capture_output=True,
                          text=True, check=True).stdout


@pytest.mark.skipif(not JQ, reason="jq is not installed")
def test_the_lookup_filter_prints_each_same_repository_number():
    lookup, _ = _lookup_and_view()
    out = _run_jq(_jq_of(lookup), [{"number": 5, "isCrossRepository": False},
                                   {"number": 7, "isCrossRepository": True},
                                   {"number": 9, "isCrossRepository": False}])
    assert out.split() == ["5", "9"]
    assert _run_jq(_jq_of(lookup), []) == "", "no PR prints nothing, the go-on-to-item-1 case"


@pytest.mark.skipif(not JQ, reason="jq is not installed")
@pytest.mark.parametrize("pr, expected", [("1108", "OPEN 1"), ("110", "OPEN 0"), ("11", "OPEN 0")])
def test_the_view_filter_counts_only_this_close_s_comment(pr, expected):
    """`#110` must not count a comment naming `#1108`: the colon ends the number."""
    _, view = _lookup_and_view()
    body = _group(r"reading `([^`]+)`", _item0()).replace("<PR>", "1108")
    data = {"state": "OPEN", "comments": [{"body": body}, {"body": "see #1108, thanks"}]}
    assert _run_jq(_jq_of(view.replace("<PR>", pr)), data).strip() == expected
