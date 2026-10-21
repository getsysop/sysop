"""`/review-close --request-review` / `--land` — the Step 4d split (`Q-411`, Phase 365).

Half A opens the PR, asks the consumer's `## Second reader` for a review and records what half B
needs; half B reads the verdict on the recorded head and merges or parks. `close_run.py` owns the
record and the verdict, so most of this module drives it as a subprocess against a fixture repo
with a fake `gh` on `PATH`. The reader's fixtures are the shapes read off public PRs reviewed by
`chatgpt-codex-connector[bot]` on 2026-10-03 and 2026-10-08 (PHASE_LOG.md § Phase 365): findings
as a `COMMENTED` review pinned to `commit_id` with `![P<n> Badge]` inline comments, a clean result
as a `+1` reaction plus a summary comment, and a usage-limit comment.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from skill_runner_text import text_of

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "core/companion/scripts/close_run.py"
SKILL = REPO / "core/skills/review-close/SKILL.md"
sys.path.insert(0, str(SCRIPT.parent))
import close_run  # noqa: E402

BOT = "chatgpt-codex-connector[bot]"
READER = textwrap.dedent(f"""\
    ## Second reader

    reviewer: {BOT}
    format: codex
    request: @codex review
    timeout: 20m
    """)

_ENV = {k: v for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
_ENV.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

FAKE_GH = r'''#!/usr/bin/env python3
import datetime, json, os, sys
state = os.environ["FAKE_GH"]
args = sys.argv[1:]
with open(os.path.join(state, "calls.jsonl"), "a") as f:
    f.write(json.dumps(args) + "\n")
def load(name, default):
    p = os.path.join(state, name)
    return json.load(open(p)) if os.path.exists(p) else default
if args[:2] == ["pr", "view"]:
    print(json.dumps(load("pr.json", {})))
    sys.exit(0)
if args[:1] == ["api"]:
    if "-f" in args or "-F" in args:
        if os.path.exists(os.path.join(state, "post_fail")):
            print("HTTP 502", file=sys.stderr); sys.exit(1)
        at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        print(json.dumps({"id": 4242, "created_at": at}))
        sys.exit(0)
    path = [a for a in args if a.startswith("repos/")][0]
    for suffix, name in (("/pulls/7/reviews", "reviews.json"), ("/pulls/7/comments", "review_comments.json"),
                         ("/issues/7/comments", "comments.json"), ("/issues/7/reactions", "reactions.json")):
        if path.endswith(suffix):
            print(json.dumps(load(name, [])))
            sys.exit(0)
print("unhandled: " + " ".join(args), file=sys.stderr)
sys.exit(2)
'''


def _g(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=_ENV)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    _g(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    root = tmp_path / "repo"
    root.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["remote", "add", "origin", str(origin)]):
        _g(root, *args)
    (root / ".gitignore").write_text("sysop/runtime/\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("# p\n\n## Merge policy\n\npr\n\n" + READER, encoding="utf-8")
    _g(root, "add", "-A")
    _g(root, "commit", "-qm", "base")
    _g(root, "push", "-q", "origin", "main")
    _g(root, "fetch", "-q", "origin")
    (root / "claim.txt").write_text("flip\n", encoding="utf-8")
    _g(root, "add", "claim.txt")
    _g(root, "commit", "-qm", "claim flip on local main")
    _g(root, "checkout", "-qb", "merge/review-close-20261008T000000Z")
    (root / "work.txt").write_text("w\n", encoding="utf-8")
    _g(root, "add", "work.txt")
    _g(root, "commit", "-qm", "close")
    locks = root / "sysop/runtime/locks"
    locks.mkdir(parents=True)
    (locks / "T-1.lock").write_text("task: T-1\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(FAKE_GH, encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    state = tmp_path / "gh-state"
    state.mkdir()
    head = _g(root, "rev-parse", "HEAD")
    _pr(state, head=head)
    return root


BRANCH = "merge/review-close-20261008T000000Z"


def _state(root: Path) -> Path:
    return root.parent / "gh-state"


def _pr(st: Path, **over) -> None:
    pr = {"number": 7, "url": "https://github.com/o/r/pull/7", "state": "OPEN", "isDraft": False,
          "isCrossRepository": False, "headRefName": BRANCH, "headRefOid": over.pop("head", ""),
          "baseRefName": "main"}
    pr.update(over)
    (st / "pr.json").write_text(json.dumps(pr), encoding="utf-8")


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(_ENV, FAKE_GH=str(_state(root)),
               PATH=f"{root.parent / 'bin'}{os.pathsep}{_ENV.get('PATH', '')}")
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=root,
                          capture_output=True, text=True, env=env)


def _lines(out: str) -> dict[str, str]:
    return {l.split(": ", 1)[0]: l.split(": ", 1)[1] for l in out.splitlines() if ": " in l}


def _calls(root: Path) -> list[list[str]]:
    p = _state(root) / "calls.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def _hand_off(root: Path, *extra: str) -> subprocess.CompletedProcess:
    pushed_from = _g(root, "rev-parse", "main")
    return _run(root, "hand-off", "main", BRANCH, "7", pushed_from, *extra)


REPORT = textwrap.dedent("""\
    ## Step 6
    Merged: feat/a
    Held-doc branches: (none)
    SKIP: (none)
    4a-SKIP: (none)
    Kept locks: T-1

    ## Step 8
    Verification: green
    """)


def _sealed(root: Path) -> tuple[str, Path]:
    r = _hand_off(root)
    assert r.returncode == 0, r.stderr
    run_id, run = _lines(r.stdout)["RUN"], Path(_lines(r.stdout)["DIR"])
    (run / "report.md").write_text(REPORT, encoding="utf-8")
    r = _run(root, "seal", run_id)
    assert r.returncode == 0, r.stdout + r.stderr
    return run_id, run


# --- `## Second reader` -------------------------------------------------------------------------

def _cfg(tmp_path: Path, body: str) -> dict:
    (tmp_path / "CLAUDE.md").write_text(body, encoding="utf-8")
    return close_run.read_second_reader(tmp_path)


def test_the_reader_section_parses_with_its_defaults(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, f"# p\n\n## Second reader\n\nreviewer: {BOT}\nformat: codex\nrequest: @codex review\n\n## Next\nx: y\n")
    assert cfg == {"reviewer": BOT, "format": "codex", "request": "@codex review",
                   "timeout": "20m", "blocking": "P0 P1"}


@pytest.mark.parametrize("body,why", [
    ("# p\n\n## Merge policy\n\npr\n", "no `## Second reader`"),
    ("# p\n\n```\n## Second reader\nreviewer: a\n```\n", "no `## Second reader`"),
    (f"## Second reader\n\nreviewer: {BOT}\nformat: codex\nrequest: x\nwho: me\n", "known key"),
    (f"## Second reader\n\nreviewer: {BOT}\nformat: codex\n", "request is required"),
    ("## Second reader\n\nreviewer: a b\nformat: codex\nrequest: x\n", "not a GitHub login"),
    (f"## Second reader\n\nreviewer: {BOT}\nformat: vibes\nrequest: x\n", "format must be"),
    (f"## Second reader\n\nreviewer: {BOT}\nformat: codex\nrequest: x\ntimeout: soon\n", "timeout must"),
    (f"## Second reader\n\nreviewer: {BOT}\nformat: approval\nrequest: x\nblocking: P0\n", "codex only"),
    (f"## Second reader\n\nreviewer: {BOT}\nreviewer: other\nformat: codex\nrequest: x\n", "given twice"),
    # Two sections are an ambiguity to name, not to resolve by reading the first (Phase 365 corpus).
    (f"## Second reader\n\nreviewer: {BOT}\nformat: codex\nrequest: x\n\n## Other\n\n"
     "## Second reader\n\nreviewer: someone\nformat: approval\nrequest: y\n", "two `## Second reader` sections"),
])
def test_a_reader_section_that_does_not_parse_refuses(tmp_path: Path, body: str, why: str) -> None:
    with pytest.raises(close_run.Refuse, match=re.escape(why)):
        _cfg(tmp_path, body)


# --- half A -------------------------------------------------------------------------------------

def test_hand_off_records_requests_and_marks(repo: Path) -> None:
    r = _hand_off(repo)
    assert r.returncode == 0, r.stderr
    out = _lines(r.stdout)
    run = Path(out["DIR"])
    rec = json.loads((run / "handoff.json").read_text())
    assert rec["status"] == "awaiting" and rec["pr"] == "7"
    assert rec["head"] == _g(repo, "rev-parse", BRANCH)
    assert rec["pushed_from"] == _g(repo, "rev-parse", "main")
    assert rec["origin_at_push"] == _g(repo, "rev-parse", "origin/main")
    assert rec["request_comment"] == "4242" and close_run.parse_time(rec["requested_at"])
    assert (run / "AWAITING").is_file()
    post = [c for c in _calls(repo) if "-f" in c or "-F" in c]
    # `-F body=@codex review` would read a FILE named "codex review"; `-f` sends the text.
    assert post == [["api", "repos/{owner}/{repo}/issues/7/comments", "-f", "body=@codex review"]]


@pytest.mark.parametrize("over,why", [
    ({"state": "CLOSED"}, "state is CLOSED"),
    ({"isDraft": True}, "draft"),
    ({"isCrossRepository": True}, "another repository"),
    ({"baseRefName": "develop"}, "its base is"),
    ({"headRefName": "other"}, "its head branch is"),
    ({"headRefOid": "0" * 40}, "its head is"),
])
def test_hand_off_refuses_a_pr_it_cannot_pin(repo: Path, over: dict, why: str) -> None:
    head = _g(repo, "rev-parse", BRANCH)
    _pr(_state(repo), head=over.pop("headRefOid", head), **over)
    r = _hand_off(repo)
    assert r.returncode == 2 and why in r.stderr, r.stderr
    assert not list((repo / "sysop/runtime/close").glob("*/AWAITING")) \
        if (repo / "sysop/runtime/close").exists() else True
    assert not [c for c in _calls(repo) if "-f" in c]


@pytest.mark.parametrize("rev", [BRANCH, "main~1"])
def test_hand_off_refuses_a_sha_that_is_not_local_main_at_the_push(repo: Path, rev: str) -> None:
    """Round 1: an ancestor check passed any older SHA, which Step 6 would then read as commits
    made after the push. The SHA must be local main's commit the pushed head was built on."""
    r = _run(repo, "hand-off", "main", BRANCH, "7", _g(repo, "rev-parse", rev))
    assert r.returncode == 2 and "is not local main's commit at the push" in r.stderr, r.stderr


def test_a_commit_on_main_after_the_push_does_not_move_the_recorded_sha(repo: Path) -> None:
    pushed_from = _g(repo, "rev-parse", "main")
    _g(repo, "checkout", "-q", "main")
    (repo / "late.txt").write_text("late\n", encoding="utf-8")
    _g(repo, "add", "late.txt")
    _g(repo, "commit", "-qm", "a claim during the gap")
    r = _run(repo, "hand-off", "main", BRANCH, "7", pushed_from)
    assert r.returncode == 0, r.stderr


def test_one_hand_off_at_a_time_and_prepare_refuses_while_one_waits(repo: Path) -> None:
    assert _run(repo, "reader").returncode == 0  # the control
    assert _hand_off(repo).returncode == 0
    r = _run(repo, "reader")
    assert r.returncode == 2 and "waiting for its second reader" in r.stderr
    r = _hand_off(repo)
    assert r.returncode == 2 and "another hand-off is waiting" in r.stderr
    r = _run(repo, "begin", "main")
    assert r.returncode == 2 and "waiting for its second reader" in r.stderr


def test_a_prepared_run_cannot_be_resumed_while_a_hand_off_waits(repo: Path) -> None:
    r = _run(repo, "begin", "main")
    assert r.returncode == 0, r.stderr
    run_id, run = r.stdout.splitlines()[0].split(": ", 1)[1], Path(r.stdout.splitlines()[1].split(": ", 1)[1])
    (run / "questions.md").write_text("", encoding="utf-8")
    assert _run(repo, "finish", run_id).returncode == 0
    assert _run(repo, "load", run_id, "main").returncode == 0  # the control
    assert _hand_off(repo).returncode == 0
    r = _run(repo, "load", run_id, "main")
    assert r.returncode == 2 and "waiting for its second reader" in r.stderr, r.stderr


def test_a_failed_request_is_recorded_and_re_requestable(repo: Path) -> None:
    (_state(repo) / "post_fail").write_text("")
    r = _hand_off(repo)
    assert r.returncode == 1 and "request-failed" in r.stderr
    run_id = _lines(r.stdout)["RUN"]
    run = Path(_lines(r.stdout)["DIR"])
    assert json.loads((run / "handoff.json").read_text())["status"] == "request-failed"
    assert (run / "AWAITING").is_file()
    (run / "report.md").write_text(REPORT, encoding="utf-8")
    assert _run(repo, "seal", run_id).returncode == 0  # round 1: items 5 and 6 (then 4 and 5) go on
    (_state(repo) / "post_fail").unlink()
    r = _run(repo, "re-request", run_id, "main")
    assert r.returncode == 0, r.stderr
    assert json.loads((run / "handoff.json").read_text())["status"] == "awaiting"
    assert _run(repo, "land-check", run_id, "main").returncode == 5


def test_seal_names_what_report_md_lacks_and_reads_the_kept_locks(repo: Path) -> None:
    r = _hand_off(repo)
    run_id, run = _lines(r.stdout)["RUN"], Path(_lines(r.stdout)["DIR"])
    r = _run(repo, "seal", run_id)
    assert r.returncode == 1 and "MISSING:" in r.stdout
    (run / "report.md").write_text(REPORT.replace("4a-SKIP: (none)\n", ""), encoding="utf-8")
    r = _run(repo, "seal", run_id)
    assert r.returncode == 1 and "MISSING IN report.md: 4a-SKIP:" in r.stdout
    (run / "report.md").write_text(REPORT.replace("Kept locks: T-1", "Kept locks: ../x"), encoding="utf-8")
    assert _run(repo, "seal", run_id).returncode == 1
    lock = repo / "sysop/runtime/locks/T-1.lock"
    saved = lock.read_text()
    lock.unlink()
    (run / "report.md").write_text(REPORT, encoding="utf-8")
    r = _run(repo, "seal", run_id)
    assert r.returncode == 1 and "NOT KEPT: no lock file for T-1" in r.stdout, r.stdout
    lock.write_text(saved)
    r = _run(repo, "seal", run_id)
    assert r.returncode == 0 and f"LAND: /review-close --land {run_id}" in r.stdout
    assert json.loads((run / "handoff.json").read_text())["kept_locks"] == ["T-1"]


# --- the verdict --------------------------------------------------------------------------------

HEAD = "c5128527be" + "0" * 30
OTHER = "f71fe10f22" + "0" * 30
ASKED = "2026-10-08T13:30:00Z"


def _rec(fmt: str = "codex") -> dict:
    return {"reviewer": BOT, "head": HEAD, "requested_at": ASKED, "timeout": "20m",
            "format": fmt, "blocking": "P0 P1" if fmt == "codex" else ""}


def _t(minutes: int) -> datetime.datetime:
    return close_run.parse_time(ASKED) + datetime.timedelta(minutes=minutes)


def _review(commit: str, at: str = "2026-10-08T13:33:01Z", state: str = "COMMENTED", rid: int = 1):
    return {"id": rid, "user": {"login": BOT}, "state": state, "commit_id": commit, "submitted_at": at,
            "body": f"### 💡 Codex Review\n\n**Reviewed commit:** `{commit[:10]}`"}


def _finding(sev: str, rid: int = 1, title: str = "Record this feature") -> dict:
    return {"user": {"login": BOT}, "pull_request_review_id": rid, "path": "a.js", "line": 20,
            "body": f"**<sub><sub>![{sev} Badge](https://img.shields.io/badge/{sev}-orange?style=flat)"
                    f"</sub></sub>  {title}**\n\ndetail"}


def _summary(status: str, commit: str) -> dict:
    word = {"completed": "✅ **Completed**", "running": "🔄 **Running** since"}[status]
    return {"user": {"login": BOT}, "created_at": "2026-10-08T13:31:00Z",
            "body": "<!-- codex-pull-request-review-summary -->\n\n## Codex Review Summary\n\n"
                    "| Review | Status | Commit | Review trigger |\n| --- | --- | --- | --- |\n"
                    f"| 📝 **Code Review** | {word} <relative-time>x</relative-time> | `{commit[:7]}` | PR opened |\n"}


def _plus1(at: str) -> dict:
    return {"user": {"login": BOT}, "content": "+1", "created_at": at}


@pytest.mark.parametrize("name,reviews,rcomments,comments,reactions,now,want", [
    ("P1 on the head parks", [_review(HEAD)], [_finding("P1")], [], [], 5, "park"),
    ("P2 only merges", [_review(HEAD)], [_finding("P2")], [], [], 5, "merge"),
    ("a finding with no badge parks", [_review(HEAD)],
     [{**_finding("P2"), "body": "**Something** unbadged"}], [], [], 5, "park"),
    ("a review with no finding parks", [_review(HEAD)], [], [], [], 5, "park"),
    ("CHANGES_REQUESTED parks", [_review(HEAD, state="CHANGES_REQUESTED")], [_finding("P2")], [], [], 5, "park"),
    # Round 2: a lagging review of the pre-push head waits for the head's own review.
    ("a stale head's review after the request waits", [_review(OTHER)], [_finding("P2")], [], [], 5, "wait"),
    ("…and parks on the timeout", [_review(OTHER)], [_finding("P2")], [], [], 21, "park"),
    ("a review with a null commit waits, never crashes", [{**_review(OTHER), "commit_id": None}],
     [], [], [], 5, "wait"),
    ("a stale head's review before the request is ignored", [_review(OTHER, at="2026-10-08T13:00:00Z")],
     [_finding("P1")], [], [], 5, "wait"),
    ("another login's review counts for nothing", [{**_review(HEAD), "user": {"login": "someone"}}],
     [{**_finding("P1"), "user": {"login": "someone"}}], [], [], 5, "wait"),
    ("+1 after the request with a completed summary merges", [], [],
     [_summary("completed", HEAD)], [_plus1("2026-10-08T13:35:00Z")], 6, "merge"),
    # Round 1, record lens: a reaction names no commit, so alone it never merges.
    ("+1 with no summary comment waits", [], [], [], [_plus1("2026-10-08T13:35:00Z")], 6, "wait"),
    ("…and parks on the timeout", [], [], [], [_plus1("2026-10-08T13:35:00Z")], 21, "park"),
    ("+1 from before the request waits", [], [], [], [_plus1("2026-10-08T13:00:00Z")], 6, "wait"),
    ("…and times out", [], [], [], [_plus1("2026-10-08T13:00:00Z")], 21, "park"),
    ("a running summary waits even with +1", [], [], [_summary("running", HEAD)],
     [_plus1("2026-10-08T13:35:00Z")], 6, "wait"),
    ("a summary for another head waits", [], [], [_summary("completed", OTHER)],
     [_plus1("2026-10-08T13:35:00Z")], 6, "wait"),
    ("a usage-limit comment parks", [], [],
     [{"user": {"login": BOT}, "created_at": "2026-10-08T13:31:00Z",
       "body": "You have reached your Codex usage limits for code reviews."}], [], 6, "park"),
    ("nothing yet waits", [], [], [], [], 6, "wait"),
    # Round 1: a re-request after an earlier clean +1 merges on the summary alone.
    ("a completed summary on the head merges despite an old +1", [], [],
     [_summary("completed", HEAD)], [_plus1("2026-10-08T13:00:00Z")], 6, "merge"),
    ("a completed summary on the head merges with no +1 at all", [], [],
     [_summary("completed", HEAD)], [], 6, "merge"),
    # Round 1: the summary is read even when a review of the head exists.
    ("a running row waits even with a clean review on the head", [_review(HEAD)], [_finding("P2")],
     [_summary("running", HEAD)], [], 6, "wait"),
    ("a summary with no readable row parks",
     [], [], [{"user": {"login": BOT}, "created_at": "2026-10-08T13:31:00Z",
               "body": "<!-- codex-pull-request-review-summary -->\n| a | ✅ **Completed** | [`c512852`](u) | x |"}],
     [_plus1("2026-10-08T13:35:00Z")], 6, "park"),
    ("another login's summary counts for nothing", [], [],
     [{**_summary("completed", HEAD), "user": {"login": "someone"}}], [], 6, "wait"),
    ("a usage-limit comment from before the request is old news", [], [],
     [{"user": {"login": BOT}, "created_at": "2026-10-08T13:00:00Z",
       "body": "You have reached your Codex usage limits for code reviews."}], [], 6, "wait"),
    ("nothing by the timeout parks", [], [], [], [], 21, "park"),
])
def test_the_codex_verdict(name, reviews, rcomments, comments, reactions, now, want) -> None:
    got, lines = close_run.reader_verdict(_rec(), reviews, rcomments, comments, reactions, _t(now))
    assert got == want, (name, lines)


def test_the_codex_verdict_lists_the_blocking_finding() -> None:
    got, lines = close_run.reader_verdict(
        _rec(), [_review(HEAD)], [_finding("P1", title="Revoke admin access"), _finding("P2")], [], [], _t(5))
    assert got == "park"
    assert "P1 a.js:20 — Revoke admin access" in lines, lines
    assert any(l.startswith("(non-blocking) P2") for l in lines), lines


@pytest.mark.parametrize("state,now,want", [
    ("APPROVED", 5, "merge"), ("CHANGES_REQUESTED", 5, "park"), ("COMMENTED", 5, "wait"),
    ("COMMENTED", 21, "park")])
def test_the_approval_verdict(state: str, now: int, want: str) -> None:
    got, _ = close_run.reader_verdict(_rec("approval"), [_review(HEAD, state=state)], [], [], [], _t(now))
    assert got == want


@pytest.mark.parametrize("now,want", [(5, "wait"), (21, "park")])
def test_the_approval_verdict_with_no_review_waits_then_parks(now: int, want: str) -> None:
    got, _ = close_run.reader_verdict(_rec("approval"), [], [], [], [_plus1("2026-10-08T13:35:00Z")], _t(now))
    assert got == want


@pytest.mark.parametrize("over,why", [
    ({"isDraft": True}, "the PR is a draft"),
    ({"isCrossRepository": True}, "another repository"),
    ({"state": "CLOSED"}, "the PR is CLOSED, not open"),
])
def test_land_check_parks_a_pr_that_is_no_longer_mergeable_as_recorded(repo: Path, over: dict, why: str) -> None:
    run_id, _ = _sealed(repo)
    head = _g(repo, "rev-parse", BRANCH)
    (_state(repo) / "reviews.json").write_text(json.dumps([_review(head)]))
    (_state(repo) / "review_comments.json").write_text(json.dumps([_finding("P2")]))
    assert _run(repo, "land-check", run_id, "main").returncode == 0  # the control: it would merge
    _pr(_state(repo), head=head, **over)
    r = _run(repo, "land-check", run_id, "main")
    assert r.returncode == 4 and "VERDICT: PARK" in r.stdout and why in r.stdout, r.stdout


def test_land_check_refuses_another_default_branch(repo: Path) -> None:
    run_id, _ = _sealed(repo)
    r = _run(repo, "land-check", run_id, "develop")
    assert r.returncode == 2 and "targets 'main'" in r.stderr, r.stderr


# --- half B -------------------------------------------------------------------------------------

def test_land_check_routes_the_pr_state(repo: Path) -> None:
    run_id, _ = _sealed(repo)
    head = _g(repo, "rev-parse", BRANCH)
    r = _run(repo, "land-check", run_id, "main")
    assert r.returncode == 5 and "VERDICT: WAIT" in r.stdout, r.stdout + r.stderr
    out = _lines(r.stdout)
    assert out["HEAD"] == head and out["PUSHED FROM"] == _g(repo, "rev-parse", "main")
    assert out["BRANCH"] == BRANCH and out["KEEP BRANCH"] == "no"
    assert out["SHAPE"] == "integration branch"
    (_state(repo) / "reviews.json").write_text(json.dumps([_review(head)]))
    (_state(repo) / "review_comments.json").write_text(json.dumps([_finding("P0")]))
    r = _run(repo, "land-check", run_id, "main")
    assert r.returncode == 4 and "VERDICT: PARK" in r.stdout
    (_state(repo) / "review_comments.json").write_text(json.dumps([_finding("P2")]))
    r = _run(repo, "land-check", run_id, "main")
    assert r.returncode == 0 and "VERDICT: MERGE" in r.stdout
    _pr(_state(repo), head="1" * 40)
    r = _run(repo, "land-check", run_id, "main")
    assert r.returncode == 4 and "not the recorded" in r.stdout
    _pr(_state(repo), head=head, baseRefName="develop")
    r = _run(repo, "land-check", run_id, "main")
    assert r.returncode == 4 and "base is 'develop'" in r.stdout, r.stdout
    _pr(_state(repo), head=head, state="MERGED")
    r = _run(repo, "land-check", run_id, "main")
    assert r.returncode == 0 and "VERDICT: ALREADY MERGED" in r.stdout
    assert "READER:" not in r.stdout
    _pr(_state(repo), head="2" * 40, state="MERGED")
    r = _run(repo, "land-check", run_id, "main")
    assert r.returncode == 0 and "merged outside this gate" in r.stdout, r.stdout


def test_land_check_refuses_an_unsealed_hand_off(repo: Path) -> None:
    run_id = _lines(_hand_off(repo).stdout)["RUN"]
    r = _run(repo, "land-check", run_id, "main")
    assert r.returncode == 2 and "unsealed" in r.stderr


def test_landed_needs_a_merged_pr_then_removes_the_kept_locks_and_the_marker(repo: Path) -> None:
    run_id, run = _sealed(repo)
    lock = repo / "sysop/runtime/locks/T-1.lock"
    r = _run(repo, "landed", run_id)
    assert r.returncode == 2 and lock.exists() and (run / "AWAITING").exists()
    _pr(_state(repo), head=_g(repo, "rev-parse", BRANCH), state="MERGED")
    r = _run(repo, "landed", run_id)
    assert r.returncode == 0 and "LOCKS_REMOVED: T-1" in r.stdout, r.stdout + r.stderr
    assert not lock.exists() and not (run / "AWAITING").exists()
    assert _run(repo, "begin", "main").returncode == 0


def test_abandon_frees_the_close_and_keeps_the_locks(repo: Path) -> None:
    run_id, run = _sealed(repo)
    head = _g(repo, "rev-parse", BRANCH)
    r = _run(repo, "abandon", run_id)
    assert r.returncode == 2 and "close it first, or land it" in r.stderr, r.stderr
    _pr(_state(repo), head=head, state="MERGED")
    r = _run(repo, "abandon", run_id)
    assert r.returncode == 2 and f"--land {run_id}" in r.stderr, r.stderr
    _pr(_state(repo), head=head, state="CLOSED")
    r = _run(repo, "abandon", run_id)
    assert r.returncode == 0 and "LOCKS_KEPT: T-1" in r.stdout
    assert f"BRANCH: {BRANCH}" in r.stdout
    assert not (run / "AWAITING").exists() and (repo / "sysop/runtime/locks/T-1.lock").exists()
    assert _run(repo, "abandon", run_id).returncode == 2


def test_re_request_moves_the_recorded_head_to_the_pushed_fix(repo: Path) -> None:
    run_id, run = _sealed(repo)
    (repo / "fix.txt").write_text("f\n", encoding="utf-8")
    _g(repo, "add", "fix.txt")
    _g(repo, "commit", "-qm", "fix")
    new = _g(repo, "rev-parse", BRANCH)
    _pr(_state(repo), head=new)
    r = _run(repo, "re-request", run_id, "main")
    assert r.returncode == 0 and new in r.stdout, r.stderr
    assert json.loads((run / "handoff.json").read_text())["head"] == new


# --- the skill text ------------------------------------------------------------------------------

def _section() -> str:
    t = text_of(SKILL)
    i = t.index("## `--request-review` and `--land <run-id>` (`Q-411`)")
    stop = t.index("## A close waiting for its second reader")
    # The AWAITING stop prescribes `abandon` too (round 1 found it unquoted there).
    return t[stop:t.index("## `--prepare`", stop)] + t[i:t.index("## Step 1: Gather State", i)]


def test_the_prescribed_commands_run_as_written(repo: Path) -> None:
    """Phase 168 rule 3: every `close_run.py` line the section prescribes, run in a half A then
    half B order against the fixture."""
    # Fenced lines and inline `…` spans alike: `re-request` and `abandon` are prescribed inline.
    found = re.findall(r"(python3 sysop/scripts/close_run\.py ([\w-]+)[^`\n]*)", _section())
    cmds: dict[str, list[str]] = {}
    for line, name in found:
        cmds.setdefault(name, []).append(line.strip())
    # Phase 366 added the `--agent` selection's commands; tests/test_unattended_land.py runs those.
    # Phase 380 (`Q-664`) added the unattended resume's parks; tests/test_unattended_half_a_build.py
    # runs those.
    assert set(cmds) == {"reader", "hand-off", "seal", "land-check", "landed", "re-request", "abandon",
                         "class", "eligible", "stop", "clear", "hold", "unhold"}, cmds
    (repo / "sysop/scripts").mkdir(parents=True)
    for name in ("close_run.py", "pending_doc_hold.py"):
        (repo / "sysop/scripts" / name).write_bytes((SCRIPT.parent / name).read_bytes())
    env = dict(_ENV, FAKE_GH=str(_state(repo)),
               PATH=f"{repo.parent / 'bin'}{os.pathsep}{_ENV.get('PATH', '')}")
    # A placed worktree has no `.venv`; the venv pytest runs in stands in.
    venv = REPO / ".venv" if (REPO / ".venv").is_dir() else (
        Path(sys.prefix) if sys.prefix != sys.base_prefix else None)
    if venv:
        (repo / ".venv").symlink_to(venv)

    def sh(cmd: str) -> subprocess.CompletedProcess:
        assert "<" not in cmd.replace("<<", ""), cmd
        return subprocess.run(["bash", "-c", cmd], cwd=repo, capture_output=True, text=True, env=env)

    assert sh(cmds["reader"][0]).returncode == 0
    r = sh(cmds["hand-off"][0].replace('"<default branch>"', '"main"')
           .replace('"<branch you pushed>"', f'"{BRANCH}"').replace('"<PR>"', '"7"')
           .replace('"<SHA 2b printed>"', f'"{_g(repo, "rev-parse", "main")}"'))
    assert r.returncode == 0, r.stderr
    run_id, run = _lines(r.stdout)["RUN"], Path(_lines(r.stdout)["DIR"])
    (run / "report.md").write_text(REPORT, encoding="utf-8")

    def sub(cmd: str) -> str:
        return cmd.replace('"<run-id>"', f'"{run_id}"').replace('"<default branch>"', '"main"')

    assert sh(sub(cmds["seal"][0])).returncode == 0
    assert sh(sub(cmds["land-check"][0])).returncode == 5
    for c in cmds["re-request"]:
        assert sh(sub(c)).returncode == 0
    _pr(_state(repo), head=_g(repo, "rev-parse", BRANCH), state="MERGED")
    assert sh(sub(cmds["land-check"][0])).returncode == 0
    assert sh(sub(cmds["landed"][0])).returncode == 0
    for c in cmds["abandon"]:
        assert '"<run-id>"' in c, c  # quoted, or an unsubstituted `<…>` is a redirection
        assert sh(sub(c)).returncode == 2  # already landed


def test_every_verdict_and_exit_the_script_emits_is_routed_by_the_section() -> None:
    sec = _section()
    for token in ("**Exit 5, `VERDICT: WAIT`**", "**Exit 4, `VERDICT: PARK`**",
                  "**Exit 0, `VERDICT: ALREADY MERGED`**", "**Exit 0, `VERDICT: MERGE`**"):
        assert token in sec, token
    src = SCRIPT.read_text(encoding="utf-8")
    assert '{"merge": 0, "park": 4, "wait": 5}' in src
    assert 'print("VERDICT: ALREADY MERGED")' in src


def test_half_b_pins_the_head_and_never_re_derives_the_pr() -> None:
    sec = _section()
    assert 'gh pr merge "<PR>" --squash --delete-branch --match-head-commit "<HEAD>"' in sec
    assert "never re-deriving it from HEAD" in sec


def test_the_heredoc_keeps_the_locks_only_when_told(tmp_path: Path) -> None:
    """Step 4c's `--keep-locks` arm: the lock stays and is reported kept, and the plain run is
    unchanged. Reuses the shipped heredoc's own extraction and fixture."""
    sys.path.insert(0, str(Path(__file__).parent))
    import test_review_close_close_heredoc as h
    for keep in (False, True):
        repo = h._seed_repo(tmp_path / ("keep" if keep else "plain"))
        # Step 4c's script since Phase 386: `--keep-locks` first, then the ids.
        r = subprocess.run([sys.executable, str(h.CLOSE_SCRIPT), *(["--keep-locks"] if keep else []),
                            "TASK-0001", "TASK-0002"],
                           capture_output=True, text=True, cwd=str(repo), timeout=30, env=h._git_env())
        assert r.returncode == 0, r.stderr
        lock = repo / "sysop/runtime/locks/TASK-0001.lock"
        assert lock.exists() is keep
        assert h._row(r.stdout, "LOCKS_REMOVED") == ([] if keep else ["TASK-0001"])
        assert h._row(r.stdout, "LOCKS_ALREADY_ABSENT") == ["TASK-0002"]
        kept = [l for l in r.stdout.splitlines() if l.startswith("LOCKS_KEPT: ")]
        assert kept == (["LOCKS_KEPT: TASK-0001"] if keep else [])


def test_the_section_tells_the_runner_to_pass_keep_locks_at_4c() -> None:
    t = text_of(SKILL)
    c4 = t[t.index("### 4c. Consolidate Pending Documentation"):t.index("### 4d.")]
    assert ("Under `--request-review`, put `--keep-locks` before the ids: "
            "`python3 sysop/scripts/close_index.py --keep-locks \"<roadmap id>\" …`.") in c4
    assert "run Step 4c item 4's `tasks/index.yml` script with `--keep-locks` before its ids." in _section()


def test_every_mode_but_land_stops_on_a_waiting_hand_off() -> None:
    t = text_of(SKILL)
    stop = t[t.index("## A close waiting for its second reader"):t.index("## `--prepare` and `--resume")]
    assert "**Unless `$ARGUMENTS` contains `--land`**, look for `sysop/runtime/close/*/AWAITING`" in stop
    assert t.index("## A close waiting for its second reader") < t.index("## Step 1: Gather State")


def test_landed_refuses_an_unsealed_hand_off(repo: Path) -> None:
    run_id = _lines(_hand_off(repo).stdout)["RUN"]
    _pr(_state(repo), head=_g(repo, "rev-parse", BRANCH), state="MERGED")
    r = _run(repo, "landed", run_id)
    assert r.returncode == 2 and "unsealed" in r.stderr
    assert (repo / "sysop/runtime/locks/T-1.lock").exists()


def test_a_hand_off_killed_before_its_request_can_be_re_requested(repo: Path) -> None:
    run_id, run = _sealed(repo)
    rec = json.loads((run / "handoff.json").read_text())
    rec["status"] = "requesting"
    (run / "handoff.json").write_text(json.dumps(rec))
    r = _run(repo, "re-request", run_id, "main")
    assert r.returncode == 0, r.stderr
    assert json.loads((run / "handoff.json").read_text())["status"] == "awaiting"


def test_a_hand_off_being_recorded_refuses_a_second(repo: Path) -> None:
    """Round 1 ran two `hand-off`s concurrently and both recorded. The guard is O_EXCL."""
    guard = repo / "sysop/runtime/close/.hand-off.lock"
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_text("")
    r = _hand_off(repo)
    assert r.returncode == 2 and "being recorded" in r.stderr
    assert not [c for c in _calls(repo) if "-f" in c]
    guard.unlink()
    assert _hand_off(repo).returncode == 0
    assert not guard.exists(), "the guard outlived the hand-off it held"


def test_a_codex_record_with_no_blocking_list_is_refused(repo: Path) -> None:
    run_id, run = _sealed(repo)
    rec = json.loads((run / "handoff.json").read_text())
    rec["blocking"] = ""
    (run / "handoff.json").write_text(json.dumps(rec))
    r = _run(repo, "land-check", run_id, "main")
    assert r.returncode == 2 and "blocking list" in r.stderr


def test_sitrep_routes_a_kept_lock_to_land_not_to_document_work(repo: Path) -> None:
    """Round 1: with the lock kept, the task's trailer, consumed doc and live branch read as
    `code committed, docs pending`, and /sitrep sent it to /document-work."""
    import sitrep_survey as ss
    run_id, _ = _sealed(repo)
    assert ss._awaiting_land(repo) == {"T-1": run_id}
    t = ss._classify_task(task_id="T-1", lock=None, worktree=None, branch="feat/a", index_entry=None,
                          commits=[], unpushed=0, dirty=False, stale_days=7,
                          phase40_cutoff=datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc),
                          awaiting_land=run_id)
    assert t.state == ss._AWAITING_LAND_STATE and t.next_action == f"/review-close --land {run_id}"
    _pr(_state(repo), head=_g(repo, "rev-parse", BRANCH), state="MERGED")
    assert _run(repo, "landed", run_id).returncode == 0
    assert ss._awaiting_land(repo) == {}


# --- round 1, record lens: the corpus and the battery's survivors ---------------------------------

_GOOD = f"## Second reader\n\nreviewer: {BOT}\nformat: codex\nrequest: @codex review\n"


@pytest.mark.parametrize("name,text,want", [
    ("crlf", _GOOD.replace("\n", "\r\n"), BOT),
    ("bom", "﻿" + _GOOD, BOT),
    ("an info-string fence before it", "```markdown\n## Second reader\nreviewer: x\n```\n\n" + _GOOD, BOT),
    ("an indented code block before it", "    ## Second reader\n    reviewer: x\n\n" + _GOOD, BOT),
    ("trailing hashes", _GOOD.replace("## Second reader", "## Second reader ##"), BOT),
    ("an h1 ends it", _GOOD + "\n# Next\n\nwho: me\n", BOT),
    ("an unterminated fence before it", "```\nnever closed\n\n" + _GOOD, None),
    ("backticks cannot close a ~~~ fence",
     "~~~\n## Second reader\nreviewer: evil\nformat: approval\nrequest: hi\n```\n\n" + _GOOD, None),
    ("h3 is not the section", _GOOD.replace("## Second", "### Second"), None),
    ("h1 is not the section", _GOOD.replace("## Second", "# Second"), None),
    # The dangerous mutant: an h3 that ENDED the section would drop the `blocking:` after it
    # and apply the default silently. It is a line in the section, so it refuses.
    ("an h3 inside it refuses", _GOOD + "### Notes\nblocking: P0 P1 P2\n", None),
])
def test_the_hostile_corpus(tmp_path: Path, name: str, text: str, want) -> None:
    (tmp_path / "CLAUDE.md").write_text(text, encoding="utf-8", newline="")
    if want is None:
        with pytest.raises(close_run.Refuse):
            close_run.read_second_reader(tmp_path)
    else:
        assert close_run.read_second_reader(tmp_path)["reviewer"] == want


@pytest.mark.parametrize("value,seconds", [("20m", 1200), ("2h", 7200), ("1m", 60)])
def test_timeout_units(value: str, seconds: int) -> None:
    assert close_run.timeout_seconds(value) == seconds


def test_the_latest_approval_review_decides(tmp_path: Path) -> None:
    reviews = [_review(HEAD, at="2026-10-08T13:31:00Z", state="APPROVED", rid=1),
               _review(HEAD, at="2026-10-08T13:33:00Z", state="CHANGES_REQUESTED", rid=2)]
    assert close_run.reader_verdict(_rec("approval"), reviews, [], [], [], _t(5))[0] == "park"
    assert close_run.reader_verdict(_rec("approval"), list(reversed(reviews)), [], [], [], _t(5))[0] == "park"


def test_a_record_with_no_request_time_parks() -> None:
    assert close_run.reader_verdict({**_rec(), "requested_at": ""}, [], [], [], [], _t(5))[0] == "park"


def test_keep_branch_is_recorded_and_printed(repo: Path) -> None:
    r = _hand_off(repo, "--keep-branch")
    assert r.returncode == 0, r.stderr
    run_id, run = _lines(r.stdout)["RUN"], Path(_lines(r.stdout)["DIR"])
    (run / "report.md").write_text(REPORT, encoding="utf-8")
    assert _run(repo, "seal", run_id).returncode == 0
    assert _lines(_run(repo, "land-check", run_id, "main").stdout)["KEEP BRANCH"] == "yes"


def test_re_request_moves_the_request_time_and_checks_the_pr(repo: Path) -> None:
    run_id, run = _sealed(repo)
    rec = json.loads((run / "handoff.json").read_text())
    rec["requested_at"] = "2020-01-01T00:00:00Z"
    (run / "handoff.json").write_text(json.dumps(rec))
    assert _run(repo, "re-request", run_id, "main").returncode == 0
    assert json.loads((run / "handoff.json").read_text())["requested_at"] != "2020-01-01T00:00:00Z"
    _pr(_state(repo), head=_g(repo, "rev-parse", BRANCH), state="CLOSED")
    r = _run(repo, "re-request", run_id, "main")
    assert r.returncode == 2 and "state is CLOSED" in r.stderr


@pytest.mark.parametrize("cmd", ["seal", "landed", "re-request"])
def test_a_finished_hand_off_refuses_every_further_step(repo: Path, cmd: str) -> None:
    run_id, _ = _sealed(repo)
    _pr(_state(repo), head=_g(repo, "rev-parse", BRANCH), state="MERGED")
    assert _run(repo, "landed", run_id).returncode == 0
    args = [cmd, run_id] + (["main"] if cmd == "re-request" else [])
    assert _run(repo, *args).returncode == 2


@pytest.mark.parametrize("pr,sha", [("7a", None), ("7", "abc123")])
def test_hand_off_refuses_a_malformed_pr_or_sha(repo: Path, pr: str, sha) -> None:
    r = _run(repo, "hand-off", "main", BRANCH, pr, sha or _g(repo, "rev-parse", "main"))
    assert r.returncode == 2, r.stderr


def test_every_page_of_a_list_is_read(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(close_run, "gh", lambda root, *a: '[{"id": 1}]\n[{"id": 2}, {"id": 3}]\n')
    assert [x["id"] for x in close_run.gh_list(tmp_path, "repos/x")] == [1, 2, 3]


def test_a_record_naming_an_unsafe_kept_lock_is_refused(repo: Path) -> None:
    run_id, run = _sealed(repo)
    rec = json.loads((run / "handoff.json").read_text())
    rec["kept_locks"] = ["../../x"]
    (run / "handoff.json").write_text(json.dumps(rec))
    assert _run(repo, "landed", run_id).returncode == 2


# --- round 2 ------------------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["request-failed", "requesting"])
def test_a_hand_merged_pr_finishes_a_hand_off_whose_request_never_went(repo: Path, status: str) -> None:
    """Round 2 (both lenses): this was a dead end. Every command refused, pointing at another
    that refused, and `AWAITING` stopped every later close."""
    run_id, run = _sealed(repo)
    rec = json.loads((run / "handoff.json").read_text())
    rec["status"] = status
    (run / "handoff.json").write_text(json.dumps(rec))
    r = _run(repo, "land-check", run_id, "main")  # the PR is still open: a request is owed
    assert r.returncode == 2 and "re-request" in r.stderr, r.stderr
    _pr(_state(repo), head=_g(repo, "rev-parse", BRANCH), state="MERGED")
    r = _run(repo, "land-check", run_id, "main")
    assert r.returncode == 0 and "VERDICT: ALREADY MERGED" in r.stdout, r.stdout + r.stderr
    r = _run(repo, "landed", run_id)
    assert r.returncode == 0 and "LOCKS_REMOVED: T-1" in r.stdout, r.stderr
    assert not (run / "AWAITING").exists()


def test_an_unsealed_hand_off_names_seal(repo: Path) -> None:
    run_id = _lines(_hand_off(repo).stdout)["RUN"]
    r = _run(repo, "land-check", run_id, "main")
    assert r.returncode == 2 and f"close_run.py seal {run_id}" in r.stderr


def test_landed_reports_a_merge_at_another_head(repo: Path) -> None:
    run_id, _ = _sealed(repo)
    _pr(_state(repo), head="3" * 40, state="MERGED")
    r = _run(repo, "landed", run_id)
    assert r.returncode == 0 and "MERGED ELSEWHERE: at 333" in r.stdout


def test_the_marker_names_every_way_on(repo: Path) -> None:
    run = Path(_lines(_hand_off(repo).stdout)["DIR"])
    text = (run / "AWAITING").read_text()
    assert f'--land {run.name}' in text and "re-request" in text
    assert f'abandon "{run.name}"' in text and "closed unmerged" in text


def test_only_the_newest_summary_comment_counts() -> None:
    old = {**_summary("completed", OTHER), "updated_at": "2026-10-08T13:00:00Z"}
    new = {**_summary("completed", HEAD), "updated_at": "2026-10-08T13:40:00Z"}
    assert close_run.reader_verdict(_rec(), [], [], [old, new], [], _t(12))[0] == "merge"
    assert close_run.reader_verdict(_rec(), [], [], [new, old], [], _t(12))[0] == "merge"
    stale = {**new, "updated_at": "2026-10-08T12:00:00Z"}
    assert close_run.reader_verdict(_rec(), [], [], [old, stale], [], _t(12))[0] == "wait"


@pytest.mark.parametrize("mutate,why", [
    (lambda run: (run / "handoff.json").write_text("{not json"), "cannot be read"),
    (lambda run: _set(run, sealed=None), "never sealed"),
    (lambda run: _set(run, kept_locks=[]), "kept no task lock"),
])
def test_sitrep_reports_a_hand_off_no_task_state_carries(repo: Path, mutate, why: str) -> None:
    import sitrep_survey as ss
    run_id, run = _sealed(repo)
    mutate(run)
    found = [d for d in ss._find_discrepancies([], [], {}, repo) if d.kind == "hand-off waiting"]
    assert len(found) == 1 and why in found[0].detail and run_id in found[0].suggestion, found


def test_sitrep_carries_a_sealed_hand_off_whose_request_failed(repo: Path) -> None:
    import sitrep_survey as ss
    run_id, run = _sealed(repo)
    _set(run, status="request-failed")
    assert ss._awaiting_land(repo) == {"T-1": run_id}
    assert not [d for d in ss._find_discrepancies([], [], {}, repo) if d.kind == "hand-off waiting"]


def test_sitrep_routes_land_ahead_of_every_close_row() -> None:
    src = (REPO / "core/companion/scripts/sitrep_survey.py").read_text(encoding="utf-8")
    body = src[src.index("def _recommended_next("):src.index("def _suggested_order(")]
    assert body.index("_AWAITING_LAND_STATE") < body.index("# P1: tasks ready for /review-close")
    order = src[src.index("def _suggested_order("):]
    assert order.index("_AWAITING_LAND_STATE") < order.index("# 1. Ready for /review-close")


def _set(run: Path, **kv) -> None:
    rec = json.loads((run / "handoff.json").read_text())
    for k, v in kv.items():
        if v is None:
            rec.pop(k, None)
        else:
            rec[k] = v
    (run / "handoff.json").write_text(json.dumps(rec))
