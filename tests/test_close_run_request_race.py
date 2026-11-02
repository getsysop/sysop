"""`close_run.py`'s request against GitHub's view of the PR: the push race and the lost post.

`Q-740`: `re-request` run straight after a push refused (exit 2), because GitHub had not yet
moved the PR's `headRefOid` to the pushed tip. The check now re-reads the PR a bounded number of
times, but only while GitHub's head is a proper ancestor of the local tip, which is what a push
GitHub has not caught up with looks like. A head that is diverged, unknown locally or ahead of
local still refuses at the first read. The waits come from `SYSOP_PR_HEAD_WAIT_TRIES` and
`SYSOP_PR_HEAD_WAIT_SECONDS`, which these tests set to a zero delay.

`Q-741`: `post_request` raises the same `Fail` when GitHub refused the request comment and when
it may have taken it (a timeout after the server accepted, or a reply with no id), so a hand-off
recorded `request-failed` and `re-request` posted the request a second time. `re-request` now
reads the PR's comments first and adopts an identical request posted since the hand-off opened,
for a record holding no confirmed request and a head that has not moved.

The fixture and the fake `gh` are `test_step_4d_split.py`'s; this module's fake adds a `pr view`
sequence (`pr_seq.json`, one object per call, then `pr.json`).
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_step_4d_split import (BRANCH, FAKE_GH, REPORT, _ENV, _calls, _g, _lines, _pr, _state)
from test_step_4d_split import repo  # noqa: F401  (the fixture)

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "core/companion/scripts/close_run.py"
TRIES = 3

FAKE_GH_SEQ = FAKE_GH.replace(
    'if args[:2] == ["pr", "view"]:\n    print(json.dumps(load("pr.json", {})))\n',
    'if args[:2] == ["pr", "view"]:\n'
    '    seq = load("pr_seq.json", [])\n'
    '    if seq:\n'
    '        json.dump(seq[1:], open(os.path.join(state, "pr_seq.json"), "w"))\n'
    '        print(json.dumps(seq[0]))\n'
    '        sys.exit(0)\n'
    '    print(json.dumps(load("pr.json", {})))\n', 1)
assert FAKE_GH_SEQ != FAKE_GH


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    gh = root.parent / "bin" / "gh"
    if gh.read_text(encoding="utf-8") != FAKE_GH_SEQ:
        gh.write_text(FAKE_GH_SEQ, encoding="utf-8")
    env = dict(_ENV, FAKE_GH=str(_state(root)),
               PATH=f"{root.parent / 'bin'}{os.pathsep}{_ENV.get('PATH', '')}",
               SYSOP_PR_HEAD_WAIT_TRIES=str(TRIES), SYSOP_PR_HEAD_WAIT_SECONDS="0")
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=root,
                          capture_output=True, text=True, env=env)


def _pr_obj(head: str, **over) -> dict:
    pr = {"number": 7, "url": "https://github.com/o/r/pull/7", "state": "OPEN", "isDraft": False,
          "isCrossRepository": False, "headRefName": BRANCH, "headRefOid": head,
          "baseRefName": "main"}
    pr.update(over)
    return pr


def _serve(root: Path, *prs: dict) -> None:
    (_state(root) / "pr_seq.json").write_text(json.dumps(list(prs)), encoding="utf-8")


def _views(root: Path) -> int:
    return sum(1 for c in _calls(root) if c[:2] == ["pr", "view"])


def _posts(root: Path) -> list[list[str]]:
    return [c for c in _calls(root) if "-f" in c or "-F" in c]


def _reset_calls(root: Path) -> None:
    (_state(root) / "calls.jsonl").unlink(missing_ok=True)


def _hand_off(root: Path) -> subprocess.CompletedProcess:
    return _run(root, "hand-off", "main", BRANCH, "7", _g(root, "rev-parse", "main"))


def _sealed(root: Path) -> tuple[str, Path]:
    r = _hand_off(root)
    assert r.returncode == 0, r.stderr
    run_id, run = _lines(r.stdout)["RUN"], Path(_lines(r.stdout)["DIR"])
    (run / "report.md").write_text(REPORT, encoding="utf-8")
    assert _run(root, "seal", run_id).returncode == 0
    return run_id, run


def _push_fix(root: Path) -> tuple[str, str]:
    """A fix committed on the branch: (the old tip, the new tip). The fake's `pr.json` is moved to
    the new tip, as GitHub's view would be once it caught up."""
    old = _g(root, "rev-parse", BRANCH)
    (root / "fix.txt").write_text("f\n", encoding="utf-8")
    _g(root, "add", "fix.txt")
    _g(root, "commit", "-qm", "fix")
    new = _g(root, "rev-parse", BRANCH)
    _pr(_state(root), head=new)
    return old, new


def _rec(run: Path) -> dict:
    return json.loads((run / "handoff.json").read_text(encoding="utf-8"))


def _iso(t: datetime.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _comments(root: Path, *items: dict) -> None:
    (_state(root) / "comments.json").write_text(json.dumps(list(items)), encoding="utf-8")


# --- Q-740: GitHub has not seen the push yet ----------------------------------------------------

def test_re_request_waits_for_github_to_see_the_push(repo: Path) -> None:
    run_id, run = _sealed(repo)
    old, new = _push_fix(repo)
    _serve(repo, _pr_obj(old), _pr_obj(old))
    _reset_calls(repo)
    r = _run(repo, "re-request", run_id, "main")
    assert r.returncode == 0, r.stderr
    assert f"HEAD: {old} -> {new}" in r.stdout
    assert _views(repo) == 3 and _rec(run)["head"] == new


def test_hand_off_waits_for_github_to_see_the_push(repo: Path) -> None:
    """The PR-reuse shape: the branch's PR already existed, so the push is the only thing that
    moves its head, and the hand-off follows the push at once."""
    head = _g(repo, "rev-parse", BRANCH)
    _serve(repo, _pr_obj(_g(repo, "rev-parse", BRANCH + "~1")))
    r = _hand_off(repo)
    assert r.returncode == 0, r.stderr
    assert _views(repo) == 2 and _rec(Path(_lines(r.stdout)["DIR"]))["head"] == head


def test_the_wait_is_bounded_and_then_refuses_as_before(repo: Path) -> None:
    run_id, run = _sealed(repo)
    old, new = _push_fix(repo)
    _serve(repo, *[_pr_obj(old)] * (TRIES + 5))
    _reset_calls(repo)
    r = _run(repo, "re-request", run_id, "main")
    assert r.returncode == 2 and f"its head is {old}, and local {BRANCH} is {new}" in r.stderr, r.stderr
    assert f"re-read {TRIES} times" in r.stderr and "push the branch if you have not" in r.stderr
    assert _views(repo) == 1 + TRIES and not _posts(repo)
    assert _rec(run)["head"] == old


@pytest.mark.parametrize("which", ["diverged", "unknown", "ahead", "a ref name"])
def test_a_head_that_is_not_behind_local_refuses_at_once(repo: Path, which: str) -> None:
    """Boundary pin (green on base too): only a head local descends from is a push in flight."""
    run_id, run = _sealed(repo)
    if which == "diverged":
        _g(repo, "checkout", "-qb", "side", BRANCH + "~1")
        (repo / "side.txt").write_text("s\n", encoding="utf-8")
        _g(repo, "add", "side.txt")
        _g(repo, "commit", "-qm", "side")
        reported = _g(repo, "rev-parse", "side")
        _g(repo, "checkout", "-q", BRANCH)
    elif which == "unknown":
        reported = "0123456789abcdef0123456789abcdef01234567"
    elif which == "a ref name":  # not a SHA, though git reads `main` as an ancestor of local
        reported = "main"
    else:  # GitHub is ahead: local is the old tip
        _push_fix(repo)
        reported = _g(repo, "rev-parse", BRANCH)
        _g(repo, "branch", "-f", "side-keep", BRANCH)
        _g(repo, "checkout", "-q", "main")
        _g(repo, "branch", "-f", BRANCH, BRANCH + "~1")
    _serve(repo, *[_pr_obj(reported)] * (TRIES + 5))
    _reset_calls(repo)
    r = _run(repo, "re-request", run_id, "main")
    assert r.returncode == 2 and "its head is" in r.stderr, r.stderr
    assert _views(repo) == 1 and not _posts(repo)


def test_a_stale_head_with_another_problem_refuses_at_once(repo: Path) -> None:
    """Boundary pin: a draft is not a push in flight, whatever the head says."""
    run_id, _ = _sealed(repo)
    old, _new = _push_fix(repo)
    _serve(repo, *[_pr_obj(old, isDraft=True)] * (TRIES + 5))
    _reset_calls(repo)
    r = _run(repo, "re-request", run_id, "main")
    assert r.returncode == 2 and "draft" in r.stderr and "its head is" in r.stderr, r.stderr
    assert _views(repo) == 1


def test_a_problem_that_appears_during_the_wait_refuses_with_it(repo: Path) -> None:
    run_id, _ = _sealed(repo)
    old, _new = _push_fix(repo)
    _serve(repo, _pr_obj(old), _pr_obj(old, state="CLOSED"))
    _reset_calls(repo)
    r = _run(repo, "re-request", run_id, "main")
    assert r.returncode == 2 and "state is CLOSED" in r.stderr, r.stderr
    assert _views(repo) == 2 and not _posts(repo)


@pytest.mark.parametrize("tries,secs", [("x", "0"), ("-1", "0"), ("3", "soon"), ("999999", "0")])
def test_a_bad_wait_setting_falls_back_or_is_capped(tries: str, secs: str,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    sys.path.insert(0, str(SCRIPT.parent))
    import close_run
    monkeypatch.setenv("SYSOP_PR_HEAD_WAIT_TRIES", tries)
    monkeypatch.setenv("SYSOP_PR_HEAD_WAIT_SECONDS", secs)
    n, s = close_run.pr_head_wait()
    assert 0 <= n <= close_run.PR_HEAD_WAIT_MAX_TRIES and 0 <= s <= close_run.PR_HEAD_WAIT_MAX_SECONDS
    if tries in ("x", "-1"):
        assert n == close_run.PR_HEAD_WAIT_TRIES
    if secs == "soon":
        assert s == close_run.PR_HEAD_WAIT_SECONDS


# --- Q-741: a request that may have been posted is not posted twice -----------------------------

def _failed_hand_off(root: Path) -> tuple[str, Path]:
    (_state(root) / "post_fail").write_text("")
    r = _hand_off(root)
    assert r.returncode == 1 and "request-failed" in r.stderr
    (_state(root) / "post_fail").unlink()
    return _lines(r.stdout)["RUN"], Path(_lines(r.stdout)["DIR"])


def _after_open(run: Path, seconds: int = 1) -> str:
    opened = datetime.datetime.strptime(_rec(run)["opened"], "%Y%m%dT%H%M%SZ")
    return _iso(opened + datetime.timedelta(seconds=seconds))


@pytest.mark.parametrize("body", ["@codex review", "@codex review \n"])
def test_re_request_adopts_a_request_the_failed_post_made(repo: Path, body: str) -> None:
    run_id, run = _failed_hand_off(repo)
    at = _after_open(run)
    _comments(repo, {"id": 31, "body": "unrelated", "created_at": at, "user": {"login": "a"}},
              {"id": 777, "body": body, "created_at": at, "user": {"login": "me"}})
    _reset_calls(repo)
    r = _run(repo, "re-request", run_id, "main")
    assert r.returncode == 0, r.stderr
    assert not _posts(repo), _calls(repo)
    rec = _rec(run)
    assert rec["status"] == "awaiting" and rec["request_comment"] == "777" and rec["requested_at"] == at
    assert f"REQUESTED: '@codex review' from" in r.stdout and at in r.stdout


def test_re_request_adopts_the_earliest_of_two(repo: Path) -> None:
    run_id, run = _failed_hand_off(repo)
    early, late = _after_open(run, 1), _after_open(run, 9)
    _comments(repo, {"id": 9, "body": "@codex review", "created_at": late},
              {"id": 8, "body": "@codex review", "created_at": early})
    _reset_calls(repo)
    assert _run(repo, "re-request", run_id, "main").returncode == 0
    assert not _posts(repo) and _rec(run)["request_comment"] == "8"


def test_a_same_second_tie_adopts_the_lower_id_as_a_number(repo: Path) -> None:
    """GitHub's ids grow with time; compared as strings, `"1000"` sorted before `"999"`."""
    run_id, run = _failed_hand_off(repo)
    at = _after_open(run, 1)
    _comments(repo, {"id": 1000, "body": "@codex review", "created_at": at},
              {"id": 999, "body": "@codex review", "created_at": at})
    _reset_calls(repo)
    assert _run(repo, "re-request", run_id, "main").returncode == 0
    assert not _posts(repo) and _rec(run)["request_comment"] == "999"


def test_a_hand_off_killed_mid_request_adopts_what_it_posted(repo: Path) -> None:
    """`requesting`: the hand-off died between recording and reading the post's reply."""
    run_id, run = _failed_hand_off(repo)
    rec = _rec(run)
    rec["status"] = "requesting"
    (run / "handoff.json").write_text(json.dumps(rec), encoding="utf-8")
    _comments(repo, {"id": 55, "body": "@codex review", "created_at": _after_open(run)})
    _reset_calls(repo)
    assert _run(repo, "re-request", run_id, "main").returncode == 0
    assert not _posts(repo) and _rec(run)["request_comment"] == "55"


@pytest.mark.parametrize("comment", [
    {"id": 1, "body": "@codex review", "created_at": "2020-01-01T00:00:00Z"},   # before the hand-off
    {"id": 2, "body": "@codex review please"},                                   # another body
    {"id": 3, "body": "please @codex review"},
    {"id": "", "body": "@codex review"},                                         # no id
    {"id": 4, "body": "@codex review", "created_at": "soon"},                    # no time
])
def test_re_request_posts_when_no_comment_is_the_lost_request(repo: Path, comment: dict) -> None:
    """Boundary pin (green on base too)."""
    run_id, run = _failed_hand_off(repo)
    comment = dict(comment)
    comment.setdefault("created_at", _after_open(run))
    _comments(repo, comment)
    _reset_calls(repo)
    r = _run(repo, "re-request", run_id, "main")
    assert r.returncode == 0, r.stderr
    assert len(_posts(repo)) == 1 and _rec(run)["request_comment"] == "4242"


def test_re_request_posts_when_the_head_moved_since_the_failed_request(repo: Path) -> None:
    """Boundary pin: a request posted for the old head asked for a review of the old head."""
    run_id, run = _failed_hand_off(repo)
    _comments(repo, {"id": 777, "body": "@codex review", "created_at": _after_open(run)})
    _, new = _push_fix(repo)
    _reset_calls(repo)
    r = _run(repo, "re-request", run_id, "main")
    assert r.returncode == 0, r.stderr
    assert len(_posts(repo)) == 1 and _rec(run)["request_comment"] == "4242" and _rec(run)["head"] == new


@pytest.mark.parametrize("moved", [False, True])
def test_a_confirmed_request_is_asked_again(repo: Path, moved: bool) -> None:
    """Boundary pin: with a request on record, `re-request` is the operator asking again — after a
    park's fix is pushed, or a usage limit — so an identical comment someone posted since is never
    taken for the new one."""
    run_id, run = _sealed(repo)
    rec = _rec(run)
    later = _iso(datetime.datetime.strptime(rec["requested_at"], "%Y-%m-%dT%H:%M:%SZ")
                 + datetime.timedelta(seconds=5))
    _comments(repo, {"id": 4242, "body": "@codex review", "created_at": rec["requested_at"]},
              {"id": 5000, "body": "@codex review", "created_at": later})
    if moved:
        _push_fix(repo)
    _reset_calls(repo)
    r = _run(repo, "re-request", run_id, "main")
    assert r.returncode == 0, r.stderr
    assert len(_posts(repo)) == 1
