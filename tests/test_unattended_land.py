"""`/review-close --land <run-id> --unattended <agent>` — merging with no human (`Q-411`, Phase 366).

Wade's rulings at Phase 366's opening (2026-10-08, `tools/UNATTENDED_CLOSE_SPEC.md` § 9): the
land half first, half A stays attended; `pr` policy and `## Second reader` both required; the
`## Unattended close class` checked at selection (`eligible`) and again at land against what the
PR merges; the class is an allow list, exclusions and a `blast_radius` ceiling, with CLAUDE.md,
.claude/**, sysop/** and .github/workflows/** always excluded alongside manual_smoke, solo and
held tasks; the close's own bookkeeping paths are the consumer's to allow; a park is durable
until a human clears it; and a check count of 0 waits for the hand-off's timeout, then parks.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from test_step_4d_split import BOT, FAKE_GH, READER, _ENV, _finding, _g, _summary

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "core/companion/scripts/close_run.py"
sys.path.insert(0, str(SCRIPT.parent))
import close_run  # noqa: E402

# The split's fake `gh`, plus the one endpoint the unattended land adds: the default branch's
# live tip (`git/ref/heads/<branch>`), served from `tip.json` when a test sets one and otherwise
# from the fixture's own `origin/main`, which is what GitHub would report after a fetch.
FAKE_GH_LAND = FAKE_GH.replace(
    '    path = [a for a in args if a.startswith("repos/")][0]\n',
    '    path = [a for a in args if a.startswith("repos/")][0]\n'
    '    if "/git/ref/heads/" in path:\n'
    '        import subprocess\n'
    '        tip = load("tip.json", None) or subprocess.run(["git", "rev-parse", "refs/remotes/origin/main"],\n'
    '                                                      capture_output=True, text=True).stdout.strip()\n'
    '        print(json.dumps({"object": {"sha": tip}}))\n'
    '        sys.exit(0)\n', 1)
assert FAKE_GH_LAND != FAKE_GH

AGENT = "autopilot"
BRANCH = "merge/review-close-20261008T000000Z"
CLASS = textwrap.dedent("""\
    ## Unattended close class

    allow: src/** tasks/** PROJECT_STATUS.md CHANGELOG.md UI_Iterations.md
    allow: review_tasks.md review_tasks_archive.md
    exclude: src/billing/**
    blast_radius: single-module
    """)
INDEX = textwrap.dedent("""\
    schema_version: 2
    tasks:
      - id: T-1
        status: in_progress
        blast_radius: single-file
      - id: T-2
        status: in_progress
        blast_radius: single-file
        manual_smoke: true
      - id: T-3
        status: in_progress
        blast_radius: cross-module
      - id: T-4
        status: in_progress
      - id: T-5
        status: in_progress
        blast_radius: single-module
        solo: true
      - id: T-6
        status: in_progress
        blast_radius: single-file
    """)
REPORT = textwrap.dedent("""\
    ## Step 6
    Merged: feat/t1
    Held-doc branches: (none)
    SKIP: (none)
    4a-SKIP: (none)
    Kept locks: T-1

    ## Step 8
    Verification: green
    """)


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _commit(root: Path, msg: str, files: dict[str, str]) -> str:
    for rel, text in files.items():
        _write(root, rel, text)
    _g(root, "add", "-A", "--", *files)
    _g(root, "commit", "-qm", msg)
    return _g(root, "rev-parse", "HEAD")


def _lock(root: Path, tid: str, branch: str, agent: str | None = AGENT, name: str = "") -> None:
    lines = [f"task_id: {tid}", "status: in_progress"]
    if agent is not None:
        lines.append(f"agent: {agent}")
    lines += [f"branch: {branch}", f"workspace: {root}"]
    _write(root, f"sysop/runtime/locks/{name or tid}.lock", "\n".join(lines) + "\n")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    _g(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    root = tmp_path / "repo"
    root.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["remote", "add", "origin", str(origin)]):
        _g(root, *args)
    _commit(root, "base", {
        ".gitignore": "sysop/runtime/\n",
        "CLAUDE.md": "# p\n\n## Merge policy\n\npr\n\n" + READER + "\n" + CLASS,
        "tasks/index.yml": INDEX,
        "src/a.py": "a = 1\n",
        "src/billing/pay.py": "p = 1\n",
    })
    _g(root, "push", "-q", "origin", "main")
    _g(root, "fetch", "-q", "origin")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(FAKE_GH_LAND, encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    (tmp_path / "gh-state").mkdir()
    return root


def _state(root: Path) -> Path:
    return root.parent / "gh-state"


def _pr(root: Path, **over) -> None:
    pr = {"number": 7, "url": "https://github.com/o/r/pull/7", "state": "OPEN", "isDraft": False,
          "isCrossRepository": False, "headRefName": BRANCH,
          "headRefOid": _g(root, "rev-parse", BRANCH), "baseRefName": "main",
          "baseRefOid": _g(root, "rev-parse", "origin/main"),
          "statusCheckRollup": [{"__typename": "CheckRun", "name": "pytest", "status": "COMPLETED",
                                 "conclusion": "SUCCESS"}]}
    pr.update(over)
    (_state(root) / "pr.json").write_text(json.dumps(pr), encoding="utf-8")


def _gh_file(root: Path, name: str, data) -> None:
    (_state(root) / name).write_text(json.dumps(data), encoding="utf-8")


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(_ENV, FAKE_GH=str(_state(root)),
               PATH=f"{root.parent / 'bin'}{os.pathsep}{_ENV.get('PATH', '')}")
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=root,
                          capture_output=True, text=True, env=env)


def _calls(root: Path) -> int:
    p = _state(root) / "calls.jsonl"
    return len(p.read_text().splitlines()) if p.exists() else 0


def _branch(root: Path, name: str, files: dict[str, str], base: str = "main") -> None:
    _g(root, "checkout", "-qb", name, base)
    _commit(root, name, files)
    _g(root, "checkout", "-q", "main")


def _out_lines(out: str) -> dict[str, str]:
    """`IN <branch>` / `OUT <branch>` -> the rest of the line."""
    found = {}
    for line in out.splitlines():
        m = re.match(r"(IN|OUT) (\S+): (.*)", line)
        if m:
            found[m.group(2)] = f"{m.group(1)} {m.group(3)}"
    return found


# --- the class ------------------------------------------------------------------------------

@pytest.mark.parametrize("pat,path,hit", [
    ("src/**", "src/a.py", True),
    ("src/**", "src/x/y/z.py", True),
    ("src/**", "srcx/a.py", False),
    ("src/", "src/x/a.py", True),
    ("*.md", "README.md", True),
    ("*.md", "docs/README.md", False),  # root-anchored, unlike gitignore
    ("**/x.py", "x.py", True),
    ("**/x.py", "a/b/x.py", True),
    ("src/*.py", "src/a/b.py", False),  # `*` stays inside one segment
    ("a?.py", "ab.py", True),
    ("a?.py", "a/.py", False),
    ("CLAUDE.md", "CLAUDE.md", True),
    ("CLAUDE.md", "sub/CLAUDE.md", False),
    ("x.py", "x.pyc", False),
])
def test_globs_are_root_anchored_and_segment_aware(pat: str, path: str, hit: bool) -> None:
    assert bool(close_run.glob_regex(pat).match(path)) is hit


@pytest.mark.parametrize("pat", ["/src/**", "src/../x", "a//b", "a**/b", "src/[ab].py",
                                 "src/{a,b}.py", "!src/a.py", "src\\a.py", "./src"])
def test_an_unsupported_glob_refuses_loudly(pat: str) -> None:
    with pytest.raises(close_run.Refuse, match="not a supported path glob"):
        close_run.glob_regex(pat)


def _cls(tmp_path: Path, body: str) -> dict:
    (tmp_path / "CLAUDE.md").write_text(body, encoding="utf-8")
    return close_run.read_class(tmp_path)


def test_the_class_parses_and_allow_repeats(tmp_path: Path) -> None:
    cls = _cls(tmp_path, "# p\n\n" + CLASS + "\n## Next\nx\n")
    assert [p for p, _ in cls["allow"]][:2] == ["src/**", "tasks/**"]
    assert "review_tasks_archive.md" in [p for p, _ in cls["allow"]]
    assert [p for p, _ in cls["exclude"]] == ["src/billing/**"]
    assert cls["ceiling"] == "single-module"


@pytest.mark.parametrize("body,why", [
    ("# p\n", "no `## Unattended close class`"),
    ("```\n## Unattended close class\nallow: src/**\nblast_radius: single-file\n```\n",
     "no `## Unattended close class`"),
    ("## Unattended close class\n\nblast_radius: single-file\n", "allow is required"),
    ("## Unattended close class\n\nallow: src/**\n", "blast_radius is required"),
    ("## Unattended close class\n\nallow: src/**\nblast_radius: huge\n", "blast_radius must be"),
    ("## Unattended close class\n\nallow: src/**\nblast_radius: single-file\nblast_radius: single-file\n",
     "given twice"),
    ("## Unattended close class\n\nallow: src/**\nblast_radius: single-file\nagent: me\n", "known key"),
])
def test_a_class_that_does_not_parse_refuses(tmp_path: Path, body: str, why: str) -> None:
    with pytest.raises(close_run.Refuse, match=re.escape(why)):
        _cls(tmp_path, body)


@pytest.mark.parametrize("path", ["CLAUDE.md", ".claude/settings.json", ".claude/skills/x/SKILL.md",
                                  "sysop/scripts/close_run.py", ".github/workflows/ci.yml"])
def test_the_fixed_exclusions_win_over_any_allow(tmp_path: Path, path: str) -> None:
    cls = _cls(tmp_path, "## Unattended close class\n\nallow: **\nblast_radius: architectural\n")
    assert "always excluded" in close_run.path_problem(cls, path)


def test_a_consumer_exclusion_wins_over_its_allow(tmp_path: Path) -> None:
    cls = _cls(tmp_path, CLASS)
    assert close_run.path_problem(cls, "src/a.py") == ""
    assert "excluded: src/billing/**" in close_run.path_problem(cls, "src/billing/pay.py")
    assert "not allowed" in close_run.path_problem(cls, "docs/x.md")


def test_the_class_warns_about_each_close_written_path_it_refuses(tmp_path: Path) -> None:
    assert close_run.class_warnings(_cls(tmp_path, CLASS)) == []
    narrow = _cls(tmp_path, "## Unattended close class\n\nallow: src/**\nblast_radius: single-file\n")
    warned = " ".join(close_run.class_warnings(narrow))
    for p in close_run.CLOSE_WRITTEN:
        assert p in warned


@pytest.mark.parametrize("entry,why", [
    (None, "no entry"),
    ({"blast_radius": "single-file", "manual_smoke": True}, "manual_smoke"),
    ({"blast_radius": "single-file", "solo": True}, "solo"),
    ({"blast_radius": "single-file", "user_action": True}, "user_action"),
    ({}, "no blast_radius"),
    ({"blast_radius": "cross-module"}, "above single-module"),
])
def test_a_task_outside_the_class_names_why(tmp_path: Path, entry, why: str) -> None:
    probs = close_run.task_problems(_cls(tmp_path, CLASS), "T-9", entry)
    assert any(why in p for p in probs), probs


def test_a_task_at_the_ceiling_passes(tmp_path: Path) -> None:
    cls = _cls(tmp_path, CLASS)
    assert close_run.task_problems(cls, "T-9", {"blast_radius": "single-module"}) == []
    assert close_run.task_problems(cls, "T-9", {"blast_radius": "single-file"}) == []


# --- half A's selection ---------------------------------------------------------------------

def test_eligible_admits_only_this_agents_in_class_branches(repo: Path) -> None:
    cases = {
        "feat/t1": ("T-1", AGENT, {"src/a.py": "a = 2\n"}),
        "feat/other": ("T-6", "someone-else", {"src/a.py": "a = 3\n"}),
        "feat/anon": ("T-6", None, {"src/a.py": "a = 4\n"}),
        "feat/smoke": ("T-2", AGENT, {"src/a.py": "a = 5\n"}),
        "feat/wide": ("T-3", AGENT, {"src/a.py": "a = 6\n"}),
        "feat/noblast": ("T-4", AGENT, {"src/a.py": "a = 7\n"}),
        "feat/solo": ("T-5", AGENT, {"src/a.py": "a = 8\n"}),
        "feat/rules": ("T-1", AGENT, {"CLAUDE.md": "# p\n## Unattended close class\nallow: **\nblast_radius: architectural\n"}),
        "feat/billing": ("T-1", AGENT, {"src/billing/pay.py": "p = 2\n"}),
    }
    for i, (b, (tid, agent, files)) in enumerate(cases.items()):
        _branch(repo, b, files)
        _lock(repo, tid, b, agent, name=f"L-{i}")  # the task_id line names the task
    _branch(repo, "feat/nolock", {"src/a.py": "a = 9\n"})
    r = _run(repo, "eligible", "main", AGENT, *cases, "feat/nolock")
    assert r.returncode == 0, r.stderr
    got = _out_lines(r.stdout)
    assert got["feat/t1"].startswith("IN T-1, blast_radius single-file, 1 path(s)")
    assert "not mine: its lock reads agent: someone-else" in got["feat/other"]
    assert "not mine: its lock reads agent: (none)" in got["feat/anon"]
    assert "T-2 is manual_smoke" in got["feat/smoke"]
    assert "above single-module" in got["feat/wide"]
    assert "no blast_radius" in got["feat/noblast"]
    assert "T-5 is solo" in got["feat/solo"]
    assert "CLAUDE.md (always excluded" in got["feat/rules"]
    assert "excluded: src/billing/**" in got["feat/billing"]
    assert "not mine: no lock names this branch" in got["feat/nolock"]
    assert all(v.startswith("OUT") for k, v in got.items() if k != "feat/t1")


def test_eligible_sees_a_rename_out_of_an_excluded_path(repo: Path) -> None:
    _g(repo, "checkout", "-qb", "feat/mv", "main")
    _g(repo, "mv", "src/billing/pay.py", "src/pay.py")
    _g(repo, "commit", "-qm", "mv")
    _g(repo, "checkout", "-q", "main")
    _lock(repo, "T-1", "feat/mv")
    got = _out_lines(_run(repo, "eligible", "main", AGENT, "feat/mv").stdout)
    assert got["feat/mv"].startswith("OUT") and "src/billing/pay.py (excluded" in got["feat/mv"]


def test_eligible_sets_aside_a_branch_whose_pending_doc_holds(repo: Path) -> None:
    _branch(repo, "feat/t1", {"src/a.py": "a = 2\n"})
    _lock(repo, "T-1", "feat/t1")
    _write(repo, "sysop/runtime/pending-docs/feat-t1.md",
           "---\nbranch: feat/t1\nroadmap_ids: [T-1]\nhold: waiting on a vendor\n---\nbody\n")
    got = _out_lines(_run(repo, "eligible", "main", AGENT, "feat/t1").stdout)
    assert got["feat/t1"].startswith("OUT") and "carries hold:" in got["feat/t1"]


def test_an_unreadable_shared_doc_does_not_set_aside_every_branch(repo: Path) -> None:
    _branch(repo, "feat/t1", {"src/a.py": "a = 2\n"})
    _lock(repo, "T-1", "feat/t1")
    _write(repo, "sysop/runtime/pending-docs/other.md", "---\nbranch: [unclosed\n---\n")
    got = _out_lines(_run(repo, "eligible", "main", AGENT, "feat/t1").stdout)
    assert got["feat/t1"].startswith("IN"), got


def test_eligible_notes_local_main_commits_the_class_refuses(repo: Path) -> None:
    _commit(repo, "a human edit on main", {"docs/notes.md": "n\n"})
    r = _run(repo, "eligible", "main", AGENT)
    assert "NOTE: local main carries commits" in r.stdout and "docs/notes.md (not allowed)" in r.stdout


def test_eligible_refuses_without_a_class_or_with_a_bad_agent(repo: Path) -> None:
    assert _run(repo, "eligible", "main", "two words").returncode == 2
    _commit(repo, "drop the class", {"CLAUDE.md": "# p\n\n## Merge policy\n\npr\n\n" + READER})
    r = _run(repo, "eligible", "main", AGENT)
    assert r.returncode == 2 and "no `## Unattended close class`" in r.stderr


def test_class_prints_the_class_and_its_warnings(repo: Path) -> None:
    r = _run(repo, "class")
    assert r.returncode == 0 and "BLAST_RADIUS: single-module" in r.stdout
    assert "ALWAYS EXCLUDED: CLAUDE.md .claude/** sysop/** .github/workflows/**" in r.stdout
    assert "WARN" not in r.stdout


# --- the hand-off and the unattended land ---------------------------------------------------

def _integration(repo: Path, files: dict[str, str] | None = None) -> str:
    _g(repo, "checkout", "-qb", BRANCH, "main")
    head = _commit(repo, "close", files or {"src/a.py": "a = 2\n", "tasks/index.yml": INDEX.replace(
        "  - id: T-1\n    status: in_progress", "  - id: T-1\n    status: done")})
    _g(repo, "checkout", "-q", "main")
    _lock(repo, "T-1", "feat/t1")
    _pr(repo)
    return head


def _hand_off(repo: Path, *extra: str) -> subprocess.CompletedProcess:
    return _run(repo, "hand-off", "main", BRANCH, "7", _g(repo, "rev-parse", "main"), *extra)


def _sealed(repo: Path, report: str = REPORT, files: dict[str, str] | None = None) -> tuple[str, Path]:
    _integration(repo, files)
    r = _hand_off(repo, "--agent", AGENT)
    assert r.returncode == 0, r.stderr
    run_id = re.search(r"^RUN: (\S+)", r.stdout, re.M).group(1)
    run = Path(re.search(r"^DIR: (.+)$", r.stdout, re.M).group(1))
    (run / "report.md").write_text(report, encoding="utf-8")
    r = _run(repo, "seal", run_id)
    assert r.returncode == 0, r.stdout + r.stderr
    return run_id, run


def _clean(repo: Path) -> None:
    _gh_file(repo, "comments.json", [_summary("completed", _g(repo, "rev-parse", BRANCH))])


# The unattended land is not enabled in the shipped CLI (Wade, 2026-10-08): `land-check
# --unattended` refuses. These tests keep the mechanism exercised for `Q-411`'s redesign by
# flipping the switch in-process, which the CLI never does.
_ENABLED = ("import sys; sys.path.insert(0, sys.argv[1]); import close_run; "
            "close_run.UNATTENDED_LAND_ENABLED = True; sys.exit(close_run.main(sys.argv[2:]))")


def _land(repo: Path, run_id: str, agent: str = AGENT) -> subprocess.CompletedProcess:
    env = dict(_ENV, FAKE_GH=str(_state(repo)),
               PATH=f"{repo.parent / 'bin'}{os.pathsep}{_ENV.get('PATH', '')}")
    return subprocess.run([sys.executable, "-c", _ENABLED, str(SCRIPT.parent), "land-check", run_id,
                           "main", "--unattended", agent], cwd=repo, capture_output=True, text=True,
                          env=env)


def test_the_shipped_cli_refuses_the_unattended_land(repo: Path) -> None:
    run_id, run = _sealed(repo)
    _clean(repo)
    before = _calls(repo)
    r = _run(repo, "land-check", run_id, "main", "--unattended", AGENT)
    assert r.returncode == 2 and "not enabled" in r.stderr and f"--land {run_id}" in r.stderr
    assert close_run.UNATTENDED_LAND_ENABLED is False
    assert not (run / "PARKED").exists() and _calls(repo) == before  # refused before any read


def _verdict(r: subprocess.CompletedProcess) -> str:
    m = re.search(r"^VERDICT: (.+)$", r.stdout, re.M)
    return m.group(1) if m else f"<none> rc={r.returncode} {r.stderr}"


def test_hand_off_with_agent_records_it(repo: Path) -> None:
    _run_id, run = _sealed(repo)
    rec = json.loads((run / "handoff.json").read_text())
    assert rec["unattended"] == {"agent": AGENT}


def test_hand_off_with_agent_refuses_without_a_class(repo: Path) -> None:
    _commit(repo, "drop the class", {"CLAUDE.md": "# p\n\n## Merge policy\n\npr\n\n" + READER})
    _integration(repo)
    r = _hand_off(repo, "--agent", AGENT)
    assert r.returncode == 2 and "Unattended close class" in r.stderr
    assert not list((repo / "sysop/runtime/close").glob("*/AWAITING"))


@pytest.mark.parametrize("args", [("--agent",), ("--agent", "a b"), ("--keep-branch", "--keep-branch"),
                                  ("--agent", AGENT, "--agent", AGENT), ("--bogus",)])
def test_hand_off_refuses_a_malformed_option_list(repo: Path, args) -> None:
    _integration(repo)
    r = _hand_off(repo, *args)
    assert r.returncode in (2, 3), r.stdout
    assert not list((repo / "sysop/runtime/close").glob("*/AWAITING"))


def test_an_attended_hand_off_cannot_be_landed_unattended(repo: Path) -> None:
    _integration(repo)
    r = _hand_off(repo)
    run_id = re.search(r"^RUN: (\S+)", r.stdout, re.M).group(1)
    run = Path(re.search(r"^DIR: (.+)$", r.stdout, re.M).group(1))
    (run / "report.md").write_text(REPORT, encoding="utf-8")
    assert _run(repo, "seal", run_id).returncode == 0
    r = _land(repo, run_id)
    assert r.returncode == 2 and "was not requested with --agent" in r.stderr


def test_another_agents_hand_off_is_refused(repo: Path) -> None:
    run_id, _ = _sealed(repo)
    r = _land(repo, run_id, "night-lane")
    assert r.returncode == 2 and "belongs to agent 'autopilot'" in r.stderr


def test_a_clean_in_class_hand_off_merges(repo: Path) -> None:
    run_id, run = _sealed(repo)
    _clean(repo)
    r = _land(repo, run_id)
    assert r.returncode == 0 and _verdict(r) == "MERGE", r.stdout + r.stderr
    assert "CHECKS: 1" in r.stdout and not (run / "PARKED").exists()


def test_a_head_that_touches_an_excluded_path_parks_durably(repo: Path) -> None:
    run_id, run = _sealed(repo, files={"src/a.py": "a = 2\n", "CLAUDE.md": "# widened\n"})
    _clean(repo)
    r = _land(repo, run_id)
    assert r.returncode == 4 and _verdict(r) == "PARK"
    assert "CLAUDE.md (always excluded" in r.stdout and "PARKED: class" in r.stdout
    parked = json.loads((run / "PARKED").read_text())
    assert parked["code"] == "class"
    assert json.loads((run / "handoff.json").read_text())["parks"][0]["code"] == "class"
    # A later unattended land reads nothing from GitHub: the park waits for a human.
    before = _calls(repo)
    r = _land(repo, run_id)
    assert r.returncode == 4 and "a human clears it" in r.stdout and _calls(repo) == before


@pytest.mark.parametrize("report,why", [
    (REPORT.replace("Held-doc branches: (none)", "Held-doc branches: feat/t1"), "held-doc branches"),
    (REPORT.replace("Held-doc branches: (none)\n", ""), "no Held-doc branches: line"),
])
def test_a_held_doc_in_the_report_parks(repo: Path, report: str, why: str) -> None:
    run_id, run = _sealed(repo)
    (run / "report.md").write_text(report, encoding="utf-8")  # after seal, which refuses the second
    _clean(repo)
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and why in r.stdout


def test_a_hand_off_that_kept_no_task_lock_parks(repo: Path) -> None:
    """Every in-class branch has a lock of this agent's, so a hand-off with none merges only work
    nobody selected: local main's commits, or a review batch's."""
    run_id, _ = _sealed(repo, report=REPORT.replace("Kept locks: T-1", "Kept locks: (none)"))
    _clean(repo)
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "kept no task lock" in r.stdout


def test_a_kept_task_above_the_ceiling_at_the_head_parks(repo: Path) -> None:
    run_id, _ = _sealed(repo, files={"src/a.py": "a = 2\n", "tasks/index.yml": INDEX.replace(
        "  - id: T-1\n    status: in_progress\n    blast_radius: single-file",
        "  - id: T-1\n    status: done\n    blast_radius: architectural")})
    _clean(repo)
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "T-1 is blast_radius architectural" in r.stdout


def test_a_kept_lock_that_changed_owner_parks(repo: Path) -> None:
    run_id, _ = _sealed(repo)
    _lock(repo, "T-1", "feat/t1", "someone-else")
    _clean(repo)
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "T-1's lock reads agent: someone-else" in r.stdout


def test_main_commits_riding_the_pr_are_checked_against_the_class(repo: Path) -> None:
    _commit(repo, "a human edit on main", {"docs/notes.md": "n\n"})
    run_id, _ = _sealed(repo)
    _clean(repo)
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "docs/notes.md (not allowed)" in r.stdout


def test_a_blocking_finding_parks_durably(repo: Path) -> None:
    run_id, run = _sealed(repo)
    head = _g(repo, "rev-parse", BRANCH)
    _gh_file(repo, "reviews.json", [{"id": 1, "user": {"login": BOT}, "commit_id": head,
                                     "state": "COMMENTED", "submitted_at": "2099-01-01T00:00:00Z"}])
    _gh_file(repo, "review_comments.json", [_finding("P1")])
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and json.loads((run / "PARKED").read_text())["code"] == "reader"


def test_no_verdict_yet_waits_without_parking(repo: Path) -> None:
    run_id, run = _sealed(repo)
    r = _land(repo, run_id)
    assert r.returncode == 5 and _verdict(r) == "WAIT" and not (run / "PARKED").exists()


def test_a_moved_head_parks(repo: Path) -> None:
    run_id, run = _sealed(repo)
    _pr(repo, headRefOid="f" * 40)
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and json.loads((run / "PARKED").read_text())["code"] == "pr-state"


def test_no_registered_check_waits_then_parks_at_the_timeout(repo: Path) -> None:
    run_id, run = _sealed(repo)
    _clean(repo)
    _pr(repo, statusCheckRollup=[])
    r = _land(repo, run_id)
    assert r.returncode == 5 and "no check registered on the PR" in r.stdout
    rec = json.loads((run / "handoff.json").read_text())
    assert close_run.parse_time(rec["checks_waiting_since"])
    # A second land inside the window keeps the first clock: set it a minute back, so a land
    # that restarted it would write a different second.
    import datetime as dt
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rec["checks_waiting_since"] = since
    (run / "handoff.json").write_text(json.dumps(rec), encoding="utf-8")
    assert _land(repo, run_id).returncode == 5
    rec = json.loads((run / "handoff.json").read_text())
    assert rec["checks_waiting_since"] == since
    rec["checks_waiting_since"] = "2000-01-01T00:00:00Z"
    (run / "handoff.json").write_text(json.dumps(rec), encoding="utf-8")
    r = _land(repo, run_id)
    assert r.returncode == 4 and json.loads((run / "PARKED").read_text())["code"] == "checks"


def test_a_merged_pr_finishes_even_unattended(repo: Path) -> None:
    run_id, _ = _sealed(repo)
    _pr(repo, state="MERGED")
    r = _land(repo, run_id)
    assert r.returncode == 0 and _verdict(r) == "ALREADY MERGED"


def test_re_request_unpark_and_landed_clear_a_park(repo: Path) -> None:
    run_id, run = _sealed(repo)
    assert _run(repo, "park", run_id, "relay", "gh pr merge was denied").returncode == 0
    assert (run / "PARKED").exists()
    r = _run(repo, "land-check", run_id, "main")  # attended: notes the park, reads afresh
    assert "PARKED: relay" in r.stdout and _verdict(r) == "WAIT"
    assert _run(repo, "unpark", run_id).returncode == 0 and not (run / "PARKED").exists()
    assert _run(repo, "unpark", run_id).returncode == 2
    assert _run(repo, "park", run_id, "gate-red", "PR stuck").returncode == 0
    r = _run(repo, "re-request", run_id, "main")
    assert r.returncode == 0 and "UNPARKED" in r.stdout and not (run / "PARKED").exists()
    assert _run(repo, "park", run_id, "gate-red", "PR stuck").returncode == 0
    _pr(repo, state="MERGED")
    assert _run(repo, "landed", run_id).returncode == 0
    assert not (run / "PARKED").exists() and not (run / "AWAITING").exists()


@pytest.mark.parametrize("code,reason", [("vibes", "x"), ("relay", "  ")])
def test_park_refuses_an_unknown_code_or_an_empty_reason(repo: Path, code: str, reason: str) -> None:
    run_id, run = _sealed(repo)
    assert _run(repo, "park", run_id, code, reason).returncode == 2
    assert not (run / "PARKED").exists()


# --- the skill text ---------------------------------------------------------------------------

SKILL = REPO / "core/skills/review-close/SKILL.md"


def _section() -> str:
    t = SKILL.read_text(encoding="utf-8")
    start = t.index("## `--request-review` and `--land <run-id>` (`Q-411`)")
    return t[start:t.index("## Step 1: Gather State", start)]


def test_the_selection_commands_run_as_written(repo: Path) -> None:
    """Phase 168 rule 3: every `close_run.py` line the `--agent` half A prescribes, run in order."""
    found = re.findall(r"(python3 sysop/scripts/close_run\.py ([\w-]+)[^`\n]*)", _section())
    cmds: dict[str, list[str]] = {}
    for line, name in found:
        cmds.setdefault(name, []).append(line.strip())
    assert not [c for c in cmds.get("land-check", []) if "--unattended" in c], cmds["land-check"]
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

    _branch(repo, "feat/t1", {"src/a.py": "a = 2\n"})
    _lock(repo, "T-1", "feat/t1")
    assert sh(cmds["class"][0]).returncode == 0
    r = sh(cmds["eligible"][0].replace('"<default branch>"', '"main"').replace('"<name>"', f'"{AGENT}"')
           .replace('"<branch>" "<branch>"', '"feat/t1"'))
    assert r.returncode == 0 and "IN feat/t1:" in r.stdout, r.stdout + r.stderr
    _integration(repo)
    r = sh(cmds["hand-off"][0].replace('"<default branch>"', '"main"')
           .replace('"<branch you pushed>"', f'"{BRANCH}"').replace('"<PR>"', '"7"')
           .replace('"<SHA 2b printed>"', f'"{_g(repo, "rev-parse", "main")}"') + f' --agent "{AGENT}"')
    assert r.returncode == 0, r.stderr


def test_the_skill_refuses_unattended_and_names_the_attended_land() -> None:
    sec = _section()
    assert "**`--unattended` is not enabled** (`Q-411`): stop and say so, and land the hand-off attended with `--land <run-id>`." in sec
    assert "### Under `--land <run-id> --unattended" not in sec
    assert "--unattended" not in SKILL.read_text(encoding="utf-8").split("\n", 5)[3]  # argument-hint


# --- /sitrep ----------------------------------------------------------------------------------

def test_sitrep_routes_a_parked_hand_off_to_a_human(repo: Path) -> None:
    import datetime as dt
    import sitrep_survey as ss
    run_id, _ = _sealed(repo)
    kw = dict(task_id="T-1", lock=None, worktree=None, branch="feat/t1", index_entry=None,
              commits=[], unpushed=0, dirty=False, stale_days=7,
              phase40_cutoff=dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc), awaiting_land=run_id)
    assert ss._land_park(repo, run_id) == ""
    assert ss._classify_task(**kw, land_parked="").state == ss._AWAITING_LAND_STATE
    assert _run(repo, "park", run_id, "gate-red", "PR stuck on a red check").returncode == 0
    why = ss._land_park(repo, run_id)
    assert why == "gate-red: PR stuck on a red check"
    t = ss._classify_task(**kw, land_parked=why)
    assert t.state == ss._PARKED_LAND_STATE and t.next_action.startswith("a human:")
    assert "--unattended" not in t.next_action  # a park never routes back to the scheduler
    (repo / "sysop/runtime/close" / run_id / "PARKED").write_text("{", encoding="utf-8")
    assert ss._land_park(repo, run_id) == "(unreadable)"


def test_sitrep_names_the_parked_state_in_both_orderings() -> None:
    src = (REPO / "core/companion/scripts/sitrep_survey.py").read_text(encoding="utf-8")
    body = src[src.index("def _recommended_next("):src.index("def _suggested_order(")]
    assert body.index("_PARKED_LAND_STATE") < body.index("# P1: tasks ready for /review-close")
    order = src[src.index("def _suggested_order("):]
    assert order.index("_PARKED_LAND_STATE") < order.index("# 1. Ready for /review-close")
    doc = (REPO / "core/skills/sitrep/SKILL.md").read_text(encoding="utf-8")
    assert "| 0e       | Any task `land parked`" in doc and "| **Land parked** |" in doc


# --- round 1 (Phase 366): each finding, and each assumption an independent battery walked through

def _cls_text(tmp_path: Path, allow: str = "**", exclude: str = "") -> dict:
    body = f"## Unattended close class\n\nallow: {allow}\n" + (f"exclude: {exclude}\n" if exclude else "") \
        + "blast_radius: architectural\n"
    return _cls(tmp_path, body)


@pytest.mark.parametrize("path", [".CLAUDE/settings.local.json", "claude.md", "CLAUDE.MD",
                                  "SYSOP/scripts/close_run.py", ".Github/Workflows/ci.yml",
                                  ".claude", "sysop", ".github/workflows"])
def test_the_fixed_exclusions_ignore_case_and_cover_the_bare_directory(tmp_path: Path, path: str) -> None:
    assert "always excluded" in close_run.path_problem(_cls_text(tmp_path), path)


def test_a_consumer_exclusion_ignores_case_and_an_allow_does_not(tmp_path: Path) -> None:
    cls = _cls_text(tmp_path, allow="src/**", exclude="src/billing/**")
    assert "excluded: src/billing/**" in close_run.path_problem(cls, "SRC/Billing/pay.py")
    assert "excluded: src/billing/**" in close_run.path_problem(cls, "src/Billing/pay.py")
    assert "not allowed" in close_run.path_problem(cls, "SRC/a.py")  # allow stays exact


def test_a_path_with_a_newline_is_matched_whole(tmp_path: Path) -> None:
    cls = _cls_text(tmp_path, allow="src/**")
    assert close_run.path_problem(cls, "src/a\nb.py") == ""
    assert "always excluded" in close_run.path_problem(cls, "sysop/a\nb.sh")


def test_a_branch_cannot_clear_its_own_tasks_flags(repo: Path) -> None:
    # T-2 is manual_smoke on main; the branch drops the flag in its own index.
    _branch(repo, "feat/t2", {"src/a.py": "a = 2\n", "tasks/index.yml": INDEX.replace(
        "    blast_radius: single-file\n    manual_smoke: true\n", "    blast_radius: single-file\n")})
    _lock(repo, "T-2", "feat/t2")
    got = _out_lines(_run(repo, "eligible", "main", AGENT, "feat/t2").stdout)
    assert got["feat/t2"].startswith("OUT") and "at local main: T-2 is manual_smoke" in got["feat/t2"]


def test_a_head_that_lowers_its_tasks_blast_radius_parks(repo: Path) -> None:
    _commit(repo, "T-1 is architectural", {"tasks/index.yml": INDEX.replace(
        "  - id: T-1\n    status: in_progress\n    blast_radius: single-file",
        "  - id: T-1\n    status: in_progress\n    blast_radius: architectural")})
    _g(repo, "push", "-q", "origin", "main")
    _g(repo, "fetch", "-q", "origin")
    run_id, _ = _sealed(repo)  # the integration head carries INDEX's single-file T-1
    _pr(repo)
    _clean(repo)
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "at the pushed-from commit: T-1 is blast_radius architectural" in r.stdout


@pytest.mark.parametrize("where", ["tip", "local"])
def test_an_index_naming_one_id_twice_is_unreadable(repo: Path, where: str) -> None:
    dup = INDEX + "  - id: T-1\n    status: in_progress\n    blast_radius: single-file\n"
    if where == "local":
        _commit(repo, "dup", {"tasks/index.yml": dup})
        _branch(repo, "feat/t1", {"src/a.py": "a = 2\n"})
    else:
        _branch(repo, "feat/t1", {"src/a.py": "a = 2\n", "tasks/index.yml": dup})
    _lock(repo, "T-1", "feat/t1")
    got = _out_lines(_run(repo, "eligible", "main", AGENT, "feat/t1").stdout)
    assert got["feat/t1"].startswith("OUT") and "names one id twice" in got["feat/t1"]


@pytest.mark.parametrize("text", ["tasks: [unclosed\n", "- just a list\n"])
def test_an_unparseable_tip_index_sets_the_branch_aside(repo: Path, text: str) -> None:
    _branch(repo, "feat/t1", {"src/a.py": "a = 2\n", "tasks/index.yml": text})
    _lock(repo, "T-1", "feat/t1")
    got = _out_lines(_run(repo, "eligible", "main", AGENT, "feat/t1").stdout)
    assert got["feat/t1"].startswith("OUT") and "does not parse" in got["feat/t1"]


def test_an_unparseable_head_index_parks(repo: Path) -> None:
    run_id, _ = _sealed(repo, files={"src/a.py": "a = 2\n", "tasks/index.yml": "tasks: [unclosed\n"})
    _clean(repo)
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "cannot be read" in r.stdout


@pytest.mark.parametrize("owner", ["autopilot2", "Autopilot", "autopilo", '"autopilot "'])
def test_a_lock_owner_must_match_exactly(repo: Path, owner: str) -> None:
    _branch(repo, "feat/t1", {"src/a.py": "a = 2\n"})
    _lock(repo, "T-1", "feat/t1", owner)
    got = _out_lines(_run(repo, "eligible", "main", AGENT, "feat/t1").stdout)
    assert got["feat/t1"].startswith("OUT") and "not mine" in got["feat/t1"]


@pytest.mark.parametrize("owner", ["autopilot2", "Autopilot"])
def test_a_kept_lock_owner_must_match_exactly_at_land(repo: Path, owner: str) -> None:
    run_id, _ = _sealed(repo)
    _lock(repo, "T-1", "feat/t1", owner)
    _clean(repo)
    assert _verdict(_land(repo, run_id)) == "PARK"


def test_two_locks_naming_one_branch_set_it_aside(repo: Path) -> None:
    _branch(repo, "feat/t1", {"src/a.py": "a = 2\n"})
    _lock(repo, "T-1", "feat/t1")
    _lock(repo, "T-6", "feat/t1")
    got = _out_lines(_run(repo, "eligible", "main", AGENT, "feat/t1").stdout)
    assert got["feat/t1"].startswith("OUT") and "2 locks name this branch" in got["feat/t1"]


def test_a_held_doc_in_the_branch_worktree_or_with_a_refs_prefix_sets_it_aside(repo: Path) -> None:
    _branch(repo, "feat/t1", {"src/a.py": "a = 2\n"})
    wt = repo.parent / "wt-t1"
    _g(repo, "worktree", "add", "-q", str(wt), "feat/t1")
    _lock(repo, "T-1", "feat/t1")
    _write(wt, "sysop/runtime/pending-docs/t1.md",
           "---\nbranch: refs/heads/feat/t1\nroadmap_ids: [T-1]\nhold: vendor\n---\nbody\n")
    got = _out_lines(_run(repo, "eligible", "main", AGENT, "feat/t1").stdout)
    assert got["feat/t1"].startswith("OUT") and "carries hold:" in got["feat/t1"]


def test_an_unreadable_doc_in_the_branch_worktree_sets_it_aside(repo: Path) -> None:
    _branch(repo, "feat/t1", {"src/a.py": "a = 2\n"})
    wt = repo.parent / "wt-t1"
    _g(repo, "worktree", "add", "-q", str(wt), "feat/t1")
    _lock(repo, "T-1", "feat/t1")
    _write(wt, "sysop/runtime/pending-docs/t1.md", "---\nbranch: [unclosed\n---\n")
    got = _out_lines(_run(repo, "eligible", "main", AGENT, "feat/t1").stdout)
    assert got["feat/t1"].startswith("OUT") and "cannot be read" in got["feat/t1"]


def test_a_non_ascii_path_under_an_excluded_directory_is_seen(repo: Path) -> None:
    _branch(repo, "feat/t1", {"sysop/é.sh": "x\n"})
    _lock(repo, "T-1", "feat/t1")
    got = _out_lines(_run(repo, "eligible", "main", AGENT, "feat/t1").stdout)
    assert "sysop/é.sh (always excluded" in got["feat/t1"]


def test_a_submodule_is_seen_whatever_diff_ignore_submodules_says(repo: Path) -> None:
    _g(repo, "config", "diff.ignoreSubmodules", "all")
    _g(repo, "checkout", "-qb", "feat/t1", "main")
    _g(repo, "update-index", "--add", "--cacheinfo", f"160000,{_g(repo, 'rev-parse', 'HEAD')},sysop/vendored")
    _g(repo, "commit", "-qm", "gitlink")
    _g(repo, "checkout", "-q", "main")
    _lock(repo, "T-1", "feat/t1")
    got = _out_lines(_run(repo, "eligible", "main", AGENT, "feat/t1").stdout)
    assert "sysop/vendored (always excluded" in got["feat/t1"]


def test_no_branch_in_needs_no_hand_off_but_selection_still_reports(repo: Path) -> None:
    _branch(repo, "feat/x", {"docs/x.md": "x\n"})
    _lock(repo, "T-1", "feat/x")
    r = _run(repo, "eligible", "main", AGENT, "feat/x")
    assert r.returncode == 0 and "IN " not in r.stdout


def test_the_class_at_land_is_the_bases_not_the_working_trees(repo: Path) -> None:
    run_id, run = _sealed(repo, files={"src/a.py": "a = 2\n", "docs/x.md": "x\n"})
    _clean(repo)
    assert _verdict(_land(repo, run_id)) == "PARK"
    (repo / "CLAUDE.md").write_text((repo / "CLAUDE.md").read_text().replace(
        "allow: src/**", "allow: ** src/**"), encoding="utf-8")  # uncommitted widening
    assert _run(repo, "unpark", run_id).returncode == 0
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "docs/x.md (not allowed)" in r.stdout


def test_a_revert_to_older_content_is_seen_against_the_live_tip(repo: Path) -> None:
    """Round 1's fixture: main moves ci.yml A -> B; a branch puts it back to A. Against the old
    base the diff is empty for ci.yml; against the tip the squash lands on it is a change. A
    local ref behind GitHub's tip waits for a fetch rather than diffing against it."""
    _commit(repo, "ci A", {".github/workflows/ci.yml": "A\n"})
    _g(repo, "push", "-q", "origin", "main")
    _g(repo, "fetch", "-q", "origin")
    stale = _g(repo, "rev-parse", "origin/main")
    _commit(repo, "ci B", {".github/workflows/ci.yml": "B\n"})
    _g(repo, "push", "-q", "origin", "main")
    _g(repo, "fetch", "-q", "origin")
    run_id, _ = _sealed(repo, files={"src/a.py": "a = 2\n", ".github/workflows/ci.yml": "A\n"})
    _clean(repo)
    tip = _g(repo, "rev-parse", "origin/main")
    _g(repo, "update-ref", "refs/remotes/origin/main", stale)  # a fetch that never happened
    _gh_file(repo, "tip.json", tip)
    r = _land(repo, run_id)
    assert _verdict(r) == "WAIT" and "fetch origin main" in r.stdout
    _g(repo, "update-ref", "refs/remotes/origin/main", tip)  # the fetch
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and ".github/workflows/ci.yml (always excluded" in r.stdout


@pytest.mark.parametrize("tip", ["e" * 40, "missing-ref"])
def test_a_tip_not_fetched_yet_waits(repo: Path, tip: str) -> None:
    run_id, run = _sealed(repo)
    _clean(repo)
    if tip == "missing-ref":  # a remote whose refspec never writes origin/main
        _gh_file(repo, "tip.json", _g(repo, "rev-parse", "origin/main"))
        _g(repo, "update-ref", "-d", "refs/remotes/origin/main")
    else:
        _gh_file(repo, "tip.json", tip)
    r = _land(repo, run_id)
    assert r.returncode == 5 and "fetch origin" in r.stdout and not (run / "PARKED").exists()


def test_a_class_withdrawn_on_the_default_branch_after_the_hand_off_parks(repo: Path) -> None:
    """Round 2: the kill switch. A human removes the class and pushes; the land must not merge."""
    run_id, _ = _sealed(repo)
    _clean(repo)
    _g(repo, "checkout", "-q", "--detach", "origin/main")
    _commit(repo, "withdraw the class", {"CLAUDE.md": "# p\n\n## Merge policy\n\npr\n\n" + READER})
    _g(repo, "push", "-q", "origin", "HEAD:main")
    _g(repo, "checkout", "-q", "main")
    _g(repo, "fetch", "-q", "origin")
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "no `## Unattended close class`" in r.stdout


def test_a_symlinked_claude_md_is_followed_at_the_tip(repo: Path) -> None:
    run_id, _ = _sealed(repo)
    _clean(repo)
    _g(repo, "checkout", "-q", "--detach", "origin/main")
    text = (repo / "CLAUDE.md").read_text()
    (repo / "CLAUDE.md").unlink()
    (repo / "AGENTS.md").write_text(text, encoding="utf-8")
    (repo / "CLAUDE.md").symlink_to("AGENTS.md")
    _g(repo, "add", "-A", "--", "CLAUDE.md", "AGENTS.md")
    _g(repo, "commit", "-qm", "CLAUDE.md -> AGENTS.md")
    _g(repo, "push", "-q", "origin", "HEAD:main")
    _g(repo, "checkout", "-q", "main")
    _g(repo, "fetch", "-q", "origin")
    r = _land(repo, run_id)
    assert _verdict(r) == "MERGE", r.stdout


def test_a_dirty_main_checkout_parks_before_the_merge(repo: Path) -> None:
    run_id, run = _sealed(repo)
    _clean(repo)
    (repo / "src/a.py").write_text("uncommitted\n", encoding="utf-8")
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and json.loads((run / "PARKED").read_text())["code"] == "dirty"


def test_a_commit_after_the_push_parks_before_the_merge(repo: Path) -> None:
    run_id, run = _sealed(repo)
    _clean(repo)
    _commit(repo, "a claim during the gap", {"tasks/notes.md": "claim\n"})
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and json.loads((run / "PARKED").read_text())["code"] == "after-push"


@pytest.mark.parametrize("entry,verdict", [
    ({"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "FAILURE"}, "PARK"),
    ({"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "CANCELLED"}, "PARK"),
    ({"__typename": "CheckRun", "name": "ci", "status": "IN_PROGRESS", "conclusion": None}, "WAIT"),
    ({"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "SKIPPED"}, "MERGE"),
    ({"__typename": "StatusContext", "context": "jenkins", "state": "ERROR"}, "PARK"),
    ({"__typename": "StatusContext", "context": "jenkins", "state": "PENDING"}, "WAIT"),
    ({"__typename": "StatusContext", "context": "jenkins", "state": "SUCCESS"}, "MERGE"),
    ("garbage", "PARK"),
])
def test_every_registered_check_must_pass(repo: Path, entry, verdict: str) -> None:
    run_id, run = _sealed(repo)
    _clean(repo)
    _pr(repo, statusCheckRollup=[{"__typename": "CheckRun", "name": "pytest", "status": "COMPLETED",
                                  "conclusion": "SUCCESS"}, entry])
    r = _land(repo, run_id)
    assert _verdict(r) == verdict, r.stdout
    if verdict == "PARK":
        assert json.loads((run / "PARKED").read_text())["code"] == "checks"


@pytest.mark.parametrize("over", [{"isDraft": True}, {"isCrossRepository": True},
                                  {"baseRefName": "develop"}, {"state": "CLOSED"}])
def test_the_unattended_pr_checks_park(repo: Path, over: dict) -> None:
    run_id, run = _sealed(repo)
    _clean(repo)
    _pr(repo, **over)
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and json.loads((run / "PARKED").read_text())["code"] == "pr-state"


def test_a_failed_request_parks_and_unpark_refuses_it(repo: Path) -> None:
    run_id, run = _sealed(repo)
    rec = json.loads((run / "handoff.json").read_text())
    rec["status"] = "request-failed"
    (run / "handoff.json").write_text(json.dumps(rec), encoding="utf-8")
    _clean(repo)
    assert _verdict(_land(repo, run_id)) == "PARK"
    r = _run(repo, "unpark", run_id)
    assert r.returncode == 2 and "re-request" in r.stderr


def test_an_unreadable_park_still_stops_the_land(repo: Path) -> None:
    run_id, run = _sealed(repo)
    (run / "PARKED").write_text("not json", encoding="utf-8")
    before = _calls(repo)
    r = _land(repo, run_id)
    assert r.returncode == 4 and "cannot be read" in r.stdout and _calls(repo) == before


def test_unpark_and_re_request_reset_the_checks_clock(repo: Path) -> None:
    run_id, run = _sealed(repo)
    for cmd in (["unpark", run_id], ["re-request", run_id, "main"]):
        rec = json.loads((run / "handoff.json").read_text())
        rec["checks_waiting_since"] = "2000-01-01T00:00:00Z"
        (run / "handoff.json").write_text(json.dumps(rec), encoding="utf-8")
        assert _run(repo, "park", run_id, "checks", "x").returncode == 0
        assert _run(repo, *cmd).returncode == 0, cmd
        assert "checks_waiting_since" not in json.loads((run / "handoff.json").read_text()), cmd


def test_a_missing_head_parks_rather_than_crashing(repo: Path) -> None:
    run_id, run = _sealed(repo)
    rec = json.loads((run / "handoff.json").read_text())
    rec["head"] = "d" * 40
    (run / "handoff.json").write_text(json.dumps(rec), encoding="utf-8")
    _pr(repo, headRefOid="d" * 40)
    _clean(repo)
    r = _land(repo, run_id)
    assert r.returncode == 4 and "is not in this repository" in r.stdout


@pytest.mark.parametrize("state", ["unsealed", "landed"])
def test_an_unsealed_or_finished_hand_off_is_refused_unattended(repo: Path, state: str) -> None:
    _integration(repo)
    r = _hand_off(repo, "--agent", AGENT)
    run_id = re.search(r"^RUN: (\S+)", r.stdout, re.M).group(1)
    run = Path(re.search(r"^DIR: (.+)$", r.stdout, re.M).group(1))
    if state == "landed":
        (run / "report.md").write_text(REPORT, encoding="utf-8")
        assert _run(repo, "seal", run_id).returncode == 0
        _pr(repo, state="MERGED")
        assert _run(repo, "landed", run_id).returncode == 0
        assert _run(repo, "park", run_id, "relay", "x").returncode == 2
    assert _land(repo, run_id).returncode == 2


def test_class_warns_in_the_case_the_repository_tracks(repo: Path) -> None:
    _commit(repo, "lowercase changelog", {"changelog.md": "# c\n"})
    r = _run(repo, "class")
    assert "WARN: the class does not admit changelog.md" in r.stdout
    assert "CHANGELOG.md" not in "\n".join(l for l in r.stdout.splitlines() if l.startswith("WARN"))


def test_sitrep_end_to_end_routes_a_parked_land_and_keeps_a_lockless_one(repo: Path, monkeypatch) -> None:
    import sitrep_survey as ss
    run_id, run = _sealed(repo)
    monkeypatch.chdir(repo)
    s = ss.run_survey()
    t = next(t for t in s.tasks if t.task_id == "T-1")
    assert t.state == ss._AWAITING_LAND_STATE
    assert t.next_action == f"/review-close --land {run_id}"  # the unattended land is not enabled
    assert _run(repo, "park", run_id, "gate-red", "PR stuck").returncode == 0
    s = ss.run_survey()
    t = next(t for t in s.tasks if t.task_id == "T-1")
    assert t.state == ss._PARKED_LAND_STATE
    rec = ss._recommended_next(s)
    assert rec is not None and rec.command.startswith("a human:")
    (repo / "sysop/runtime/locks/T-1.lock").unlink()
    s = ss.run_survey()
    t = next((t for t in s.tasks if t.task_id == "T-1"), None)
    assert t is not None and t.state == ss._PARKED_LAND_STATE
    assert any("is gone" in n for n in t.notes)
    assert not [d for d in s.discrepancies if "T-1" in d.detail and d.kind.startswith("index drift")]


def test_sitrep_routes_a_parked_failed_request_to_re_request_only(repo: Path) -> None:
    import sitrep_survey as ss
    run_id, run = _sealed(repo)
    rec = json.loads((run / "handoff.json").read_text())
    rec["status"] = "request-failed"
    (run / "handoff.json").write_text(json.dumps(rec), encoding="utf-8")
    assert _run(repo, "park", run_id, "reader", "no review was requested").returncode == 0
    route = ss._handoff_route(repo, run_id, True)
    assert "re-request" in route and "unpark" not in route
    rec["status"] = "awaiting"
    (run / "handoff.json").write_text(json.dumps(rec), encoding="utf-8")
    assert "unpark" in ss._handoff_route(repo, run_id, True)


# --- round 2 (Phase 366)

def _run_entry(name, conclusion, status="COMPLETED", started="2026-10-08T10:00:00Z", wf="ci"):
    return {"__typename": "CheckRun", "workflowName": wf, "name": name, "status": status,
            "conclusion": conclusion, "startedAt": started}


@pytest.mark.parametrize("rollup,failed,pending", [
    # A check that failed and was re-run green passes: its latest run decides (nodejs/node#66529's shape).
    ([_run_entry("t", "FAILURE", started="2026-10-07T11:03:00Z"), _run_entry("t", "SUCCESS", started="2026-10-07T12:22:00Z")], [], []),
    ([_run_entry("t", "SUCCESS", started="2026-10-07T11:03:00Z"), _run_entry("t", "FAILURE", started="2026-10-07T12:22:00Z")], ["t (FAILURE)"], []),
    # A re-run still going is pending, whatever the older run said.
    ([_run_entry("t", "FAILURE"), _run_entry("t", None, status="IN_PROGRESS", started="2026-10-08T11:00:00Z")], [], ["t"]),
    # Same name in two workflows is two checks.
    # (b's failure started first, so a key without the workflow would let a's later success hide it)
    ([_run_entry("t", "FAILURE", wf="b", started="2026-10-08T09:00:00Z"), _run_entry("t", "SUCCESS", wf="a")],
     ["t (FAILURE)"], []),
    ([_run_entry("t", None)], ["t (None)"], []),
    ([_run_entry("t", "NEUTRAL"), _run_entry("u", "SKIPPED")], [], []),
    ([{"__typename": "StatusContext", "context": "ci/j", "state": "EXPECTED"}], [], ["ci/j (EXPECTED)"]),
    ([{"__typename": "StatusContext", "context": "ci/j", "state": "FAILURE"}], ["ci/j (FAILURE)"], []),
])
def test_check_states_judges_each_check_on_its_latest_run(rollup, failed, pending) -> None:
    assert close_run.check_states(rollup) == (failed, pending)


def test_a_failed_check_parks_even_beside_a_pending_one(repo: Path) -> None:
    run_id, run = _sealed(repo)
    _clean(repo)
    _pr(repo, statusCheckRollup=[_run_entry("a", "FAILURE"), _run_entry("b", None, status="QUEUED")])
    assert _verdict(_land(repo, run_id)) == "PARK"
    assert json.loads((run / "PARKED").read_text())["code"] == "checks"


def test_a_pending_check_parks_at_the_timeout(repo: Path) -> None:
    run_id, run = _sealed(repo)
    _clean(repo)
    _pr(repo, statusCheckRollup=[_run_entry("a", None, status="IN_PROGRESS")])
    assert _verdict(_land(repo, run_id)) == "WAIT"
    rec = json.loads((run / "handoff.json").read_text())
    rec["checks_waiting_since"] = "2000-01-01T00:00:00Z"
    (run / "handoff.json").write_text(json.dumps(rec), encoding="utf-8")
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "still running" in r.stdout


@pytest.mark.parametrize("how", ["staged", "tasks"])
def test_dirt_anywhere_in_the_tracked_tree_parks(repo: Path, how: str) -> None:
    run_id, run = _sealed(repo)
    _clean(repo)
    if how == "staged":
        (repo / "src/a.py").write_text("staged\n", encoding="utf-8")
        _g(repo, "add", "src/a.py")
    else:
        (repo / "tasks/index.yml").write_text(INDEX + "# edited\n", encoding="utf-8")
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and json.loads((run / "PARKED").read_text())["code"] == "dirty"


def test_commits_a_pull_brought_in_are_not_after_the_push(repo: Path) -> None:
    run_id, _ = _sealed(repo)
    _clean(repo)
    # Someone else's commit lands on origin, and local main pulls it in.
    _g(repo, "checkout", "-q", "--detach", "origin/main")
    _commit(repo, "elsewhere", {"src/other.py": "o\n"})
    _g(repo, "push", "-q", "origin", "HEAD:main")
    _g(repo, "checkout", "-q", "main")
    _g(repo, "fetch", "-q", "origin")
    _g(repo, "merge", "-q", "--no-edit", "origin/main")
    r = _land(repo, run_id)
    assert _verdict(r) == "MERGE", r.stdout


def test_a_tip_that_moved_with_unrelated_commits_does_not_park(repo: Path) -> None:
    run_id, _ = _sealed(repo)
    _clean(repo)
    _g(repo, "checkout", "-q", "--detach", "origin/main")
    _commit(repo, "docs elsewhere", {"docs/elsewhere.md": "x\n"})  # outside the class
    _g(repo, "push", "-q", "origin", "HEAD:main")
    _g(repo, "checkout", "-q", "main")
    _g(repo, "fetch", "-q", "origin")
    assert _verdict(_land(repo, run_id)) == "MERGE"


def test_an_exclusion_with_a_trailing_slash_after_a_double_star_excludes(repo: Path) -> None:
    """Round 2: round 1's `X/**` fix emptied `X/**/` (a trailing `/` appends `**`)."""
    _commit(repo, "exclude with a trailing slash", {"CLAUDE.md": (repo / "CLAUDE.md").read_text().replace(
        "exclude: src/billing/**", "exclude: src/billing/**/")})
    _g(repo, "push", "-q", "origin", "main")
    _g(repo, "fetch", "-q", "origin")
    _branch(repo, "feat/t1", {"src/billing/pay.py": "p = 2\n"})
    _lock(repo, "T-1", "feat/t1")
    got = _out_lines(_run(repo, "eligible", "main", AGENT, "feat/t1").stdout)
    assert got["feat/t1"].startswith("OUT") and "excluded: src/billing/**/" in got["feat/t1"]
    run_id, _ = _sealed(repo, files={"src/billing/pay.py": "p = 3\n"})
    _clean(repo)
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "src/billing/pay.py (excluded" in r.stdout


@pytest.mark.parametrize("status", ["requesting", "request-failed"])
def test_sitrep_routes_any_unrequested_hand_off_to_re_request(repo: Path, status: str) -> None:
    import sitrep_survey as ss
    run_id, run = _sealed(repo)
    rec = json.loads((run / "handoff.json").read_text())
    rec["status"] = status
    (run / "handoff.json").write_text(json.dumps(rec), encoding="utf-8")
    for parked in (False, True):
        route = ss._handoff_route(repo, run_id, parked)
        assert "re-request" in route and "--land" not in route and "unpark" not in route


def test_sitrep_reports_a_lockless_hand_off_task_as_having_no_lock(repo: Path, monkeypatch) -> None:
    import sitrep_survey as ss
    run_id, _ = _sealed(repo)
    (repo / "sysop/runtime/locks/T-1.lock").unlink()
    monkeypatch.chdir(repo)
    t = next(t for t in ss.run_survey().tasks if t.task_id == "T-1")
    assert t.has_lock is False
