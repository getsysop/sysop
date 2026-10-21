"""`/review-close --land <run-id> --unattended --agent <name>` — merging with no human (`Q-411`,
Phases 366 and 375).

Wade's rulings at Phase 366's opening (2026-10-08, `tools/UNATTENDED_CLOSE_SPEC.md` § 9): the
land half first, half A stays attended; `pr` policy and `## Second reader` both required; the
`## Unattended close class` checked at selection (`eligible`) and again at land against what the
PR merges; the class is an allow list, exclusions and a `blast_radius` ceiling, with CLAUDE.md,
.claude/**, sysop/** and .github/workflows/** always excluded alongside manual_smoke, solo and
held tasks; the close's own bookkeeping paths are the consumer's to allow; a park is durable
until a human clears it; and a check count of 0 waits for the hand-off's timeout, then parks.

Wade's rulings at Phase 375 (part B, spec § 12): the client stops deciding what the signed gate
decides (paths, task fields, the reader's verdict); it verifies the server setup with the token
`gh` holds, requires the class's `attested:` date for what that token cannot read, keeps ruling
(s) by turning auto-merge on only once every registered check has passed, and parks otherwise.
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
from skill_runner_text import text_of

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "core/companion/scripts/close_run.py"
sys.path.insert(0, str(SCRIPT.parent))
import close_run  # noqa: E402

# The split's fake `gh`, plus what the unattended land adds: the default branch's live tip
# (`git/ref/heads/<branch>`), served from `tip.json` when a test sets one and otherwise from the
# fixture's own `origin/main`, which is what GitHub would report after a fetch; the server-setup
# reads (Phase 375), each served from `<name>.json` over a passing default and failing when a
# `fail_<name>` file exists; and `pr merge --auto` / `--disable-auto`. `merge_mode` holds
# `merge` (the default: GitHub merges at once, as Phase 375's P2 measured on a green PR), `arm`
# (auto-merge is on and GitHub waits) or `silent` (gh exits 0 and nothing changes).
SETUP_DEFAULTS = {
    "user": {"login": "sysop-bot"},
    "permission": {"permission": "write", "role_name": "write"},
    "rules": [
        {"type": "pull_request", "ruleset_id": 11, "parameters": {
            "require_code_owner_review": True, "dismiss_stale_reviews_on_push": True,
            "require_last_push_approval": False, "required_approving_review_count": 0}},
        {"type": "required_status_checks", "ruleset_id": 11, "parameters": {
            "strict_required_status_checks_policy": True,
            "required_status_checks": [{"context": "sysop/close-gate", "integration_id": 42}]}}],
    "ruleset": {"id": 11, "current_user_can_bypass": "never"},
    "environment": {"name": "sysop-close-gate", "deployment_branch_policy": {
        "protected_branches": False, "custom_branch_policies": True}},
    "policies": {"total_count": 1, "branch_policies": [{"name": "main", "type": "branch"}]},
    "gate_runs": {"total_count": 1, "check_runs": [
        {"id": 1, "name": "sysop/close-gate", "app": {"id": 42, "slug": "gate"}, "status": "completed",
         "conclusion": "success", "started_at": "2026-10-11T00:00:00Z"}]},
}
FAKE_GH_LAND = FAKE_GH.replace(
    '    path = [a for a in args if a.startswith("repos/")][0]\n',
    '    def serve(name):\n'
    '        if os.path.exists(os.path.join(state, "fail_" + name)):\n'
    '            print("HTTP 404: Not Found", file=sys.stderr); sys.exit(1)\n'
    '        print(json.dumps(load(name + ".json", SETUP.get(name)))); sys.exit(0)\n'
    '    if args[1:] == ["user"]:\n'
    '        serve("user")\n'
    '    path = [a for a in args if a.startswith("repos/")][0]\n'
    '    for part, name in (("/check-runs", "gate_runs"), ("/collaborators/", "permission"), ("/rules/branches/", "rules"),\n'
    '                       ("/rulesets/", "ruleset"), ("/deployment-branch-policies", "policies"),\n'
    '                       ("/environments/", "environment")):\n'
    '        if part in path:\n'
    '            if name == "ruleset" and os.path.exists(os.path.join(state, "ruleset_" + path.rsplit("/", 1)[-1] + ".json")):\n'
    '                serve("ruleset_" + path.rsplit("/", 1)[-1])\n'
    '            serve(name)\n'
    '    if "/git/ref/heads/" in path:\n'
    '        import subprocess\n'
    '        tip = load("tip.json", None) or subprocess.run(["git", "rev-parse", "refs/remotes/origin/main"],\n'
    '                                                      capture_output=True, text=True).stdout.strip()\n'
    '        print(json.dumps({"object": {"sha": tip}}))\n'
    '        sys.exit(0)\n', 1).replace(
    'if args[:2] == ["pr", "view"]:\n',
    'SETUP = ' + repr(SETUP_DEFAULTS) + '\n'
    'if args[:2] == ["pr", "merge"]:\n'
    '    if os.path.exists(os.path.join(state, "merge_fail")):\n'
    '        print("GraphQL: Auto merge is not allowed for this repository", file=sys.stderr); sys.exit(1)\n'
    '    pr = load("pr.json", {})\n'
    '    if "--disable-auto" in args:\n'
    '        pr["autoMergeRequest"] = None\n'
    '    else:\n'
    '        mode = (load("merge_mode.json", "merge"))\n'
    '        if mode == "merge":\n'
    '            pr["state"] = "MERGED"\n'
    '        elif mode in ("arm", "arm_then_fail"):\n'
    '            pr["autoMergeRequest"] = {"mergeMethod": "SQUASH", "enabledAt": "2026-10-11T00:00:00Z"}\n'
    '    json.dump(pr, open(os.path.join(state, "pr.json"), "w"))\n'
    '    sys.exit(1 if load("merge_mode.json", "merge") == "arm_then_fail" and "--disable-auto" not in args else 0)\n'
    'if args[:2] == ["pr", "view"]:\n', 1)
assert FAKE_GH_LAND.count("SETUP = ") == 1 and "serve(\"user\")" in FAKE_GH_LAND

AGENT = "autopilot"
BRANCH = "merge/review-close-20261008T000000Z"
CLASS = textwrap.dedent("""\
    ## Unattended close class

    allow: src/** tasks/** PROJECT_STATUS.md CHANGELOG.md UI_Iterations.md
    allow: review_tasks.md review_tasks_archive.md
    exclude: src/billing/**
    blast_radius: single-module
    code_owner: @wade
    gate_app: 42
    attested: 2026-10-01
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
GATE = {"__typename": "CheckRun", "name": "sysop/close-gate", "status": "COMPLETED",
        "conclusion": "SUCCESS"}
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
          "mergeStateStatus": "CLEAN", "autoMergeRequest": None,
          "statusCheckRollup": [{"__typename": "CheckRun", "name": "pytest", "status": "COMPLETED",
                                 "conclusion": "SUCCESS"}, GATE]}
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


def test_eligible_reads_the_merge_result_symlinks_conflicts_and_lookalikes_included(repo: Path) -> None:
    """Phase 374 (spec § 10.8): selection reads the merge result GitHub's squash would make, the
    same one the gate reads, so a symlink, a governing lookalike and a conflict are all OUT."""
    _g(repo, "checkout", "-qb", "feat/link", "main")
    os.symlink("a.py", repo / "src" / "link.py")
    _g(repo, "add", "src/link.py")
    _g(repo, "commit", "-qm", "link")
    _g(repo, "checkout", "-q", "main")
    _branch(repo, "feat/look", {"src/Claude.MD": "x\n"})
    _branch(repo, "feat/clash", {"src/a.py": "a = 'branch'\n"})
    _commit(repo, "main moves", {"src/a.py": "a = 'main'\n"})
    for i, b in enumerate(("feat/link", "feat/look", "feat/clash")):
        _lock(repo, "T-1", b, name=f"L-{i}")
    got = _out_lines(_run(repo, "eligible", "main", AGENT, "feat/link", "feat/look", "feat/clash").stdout)
    assert "src/link.py is a symlink or gitlink (mode 120000)" in got["feat/link"]
    assert "src/Claude.MD (always excluded: CLAUDE.md)" in got["feat/look"]
    assert "does not merge cleanly onto" in got["feat/clash"] and got["feat/clash"].startswith("OUT")


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
    assert ("ALWAYS EXCLUDED: CLAUDE.md CLAUDE.local.md AGENTS.md AGENTS.override.md .mcp.json "
            ".gitmodules .gitattributes .claude/ .agents/ .codex/ /sysop/** /.github/** /CODEOWNERS "
            "/docs/CODEOWNERS") in r.stdout
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


def _land(repo: Path, run_id: str, agent: str = AGENT) -> subprocess.CompletedProcess:
    return _run(repo, "land-check", run_id, "main", "--unattended", agent)


def _argv(root: Path) -> list[list[str]]:
    p = _state(root) / "calls.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def _merges(root: Path) -> list[list[str]]:
    return [a for a in _argv(root) if a[:2] == ["pr", "merge"]]


def test_the_shipped_cli_runs_the_unattended_land(repo: Path) -> None:
    """Part B (Phase 375): the shipped constant is on, and the CLI lands without a test flipping it."""
    assert close_run.UNATTENDED_LAND_ENABLED is True
    run_id, run = _sealed(repo)
    r = _land(repo, run_id)
    assert r.returncode == 0 and _verdict(r) == "ALREADY MERGED", r.stdout + r.stderr


def test_the_switch_off_refuses_before_any_read(repo: Path) -> None:
    run_id, run = _sealed(repo)
    before = _calls(repo)
    env = dict(_ENV, FAKE_GH=str(_state(repo)),
               PATH=f"{repo.parent / 'bin'}{os.pathsep}{_ENV.get('PATH', '')}")
    off = ("import sys; sys.path.insert(0, sys.argv[1]); import close_run; "
           "close_run.UNATTENDED_LAND_ENABLED = False; sys.exit(close_run.main(sys.argv[2:]))")
    r = subprocess.run([sys.executable, "-c", off, str(SCRIPT.parent), "land-check", run_id, "main",
                        "--unattended", AGENT], cwd=repo, capture_output=True, text=True, env=env)
    assert r.returncode == 2 and "switched off" in r.stderr and f"--land {run_id}" in r.stderr
    assert not (run / "PARKED").exists() and _calls(repo) == before


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


def test_a_clean_hand_off_turns_on_auto_merge_at_the_recorded_head(repo: Path) -> None:
    run_id, run = _sealed(repo)
    head = _g(repo, "rev-parse", BRANCH)
    r = _land(repo, run_id)
    assert r.returncode == 0 and _verdict(r) == "ALREADY MERGED", r.stdout + r.stderr
    assert "CHECKS: 2" in r.stdout and not (run / "PARKED").exists()
    # Never --delete-branch: with --auto it deleted nothing (Phase 375's P3); Step 6 deletes.
    assert _merges(repo) == [["pr", "merge", "7", "--auto", "--squash", "--match-head-commit", head]]
    assert json.loads((run / "handoff.json").read_text())["armed"]["head"] == head


def test_a_keep_branch_hand_off_arms_the_same_way(repo: Path) -> None:
    _integration(repo)
    r = _hand_off(repo, "--keep-branch", "--agent", AGENT)
    run_id = re.search(r"^RUN: (\S+)", r.stdout, re.M).group(1)
    run = Path(re.search(r"^DIR: (.+)$", r.stdout, re.M).group(1))
    (run / "report.md").write_text(REPORT, encoding="utf-8")
    assert _run(repo, "seal", run_id).returncode == 0
    r = _land(repo, run_id)
    assert _verdict(r) == "ALREADY MERGED" and "KEEP BRANCH: yes" in r.stdout
    assert [a for a in _merges(repo) if "--delete-branch" in a] == []


def test_a_setup_problem_parks_durably_without_arming(repo: Path) -> None:
    run_id, run = _sealed(repo)
    _gh_file(repo, "ruleset.json", {"id": 11, "current_user_can_bypass": "always"})
    r = _land(repo, run_id)
    assert r.returncode == 4 and _verdict(r) == "PARK" and "PARKED: setup" in r.stdout
    assert "can bypass ruleset 11 ('always')" in r.stdout and _merges(repo) == []
    assert json.loads((run / "PARKED").read_text())["code"] == "setup"
    assert json.loads((run / "handoff.json").read_text())["parks"][0]["code"] == "setup"
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


def test_a_kept_lock_that_changed_owner_parks(repo: Path) -> None:
    run_id, _ = _sealed(repo)
    _lock(repo, "T-1", "feat/t1", "someone-else")
    _clean(repo)
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "T-1's lock reads agent: someone-else" in r.stdout


def test_the_land_leaves_paths_and_the_reader_to_the_gate(repo: Path) -> None:
    """Wade's Phase 375 ruling: the client stops deciding what the signed gate decides. A head
    touching a governing path and a blocking finding on it do not park here; the gate's own
    failure does, and nothing is armed."""
    run_id, run = _sealed(repo, files={"src/a.py": "a = 2\n", "CLAUDE.md": "# widened\n"})
    head = _g(repo, "rev-parse", BRANCH)
    _gh_file(repo, "reviews.json", [{"id": 1, "user": {"login": BOT}, "commit_id": head,
                                     "state": "COMMENTED", "submitted_at": "2099-01-01T00:00:00Z"}])
    _gh_file(repo, "review_comments.json", [_finding("P1")])
    _pr(repo, statusCheckRollup=[dict(GATE, conclusion="FAILURE")])
    _gh_file(repo, "gate_runs.json", {"check_runs": [
        {"id": 1, "name": "sysop/close-gate", "app": {"id": 42}, "status": "completed", "conclusion": "failure",
         "started_at": "2026-10-11T00:00:00Z", "output": {"title": "governing path"}}]})
    before = _calls(repo)
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "concluded failure: governing path" in r.stdout and _merges(repo) == []
    assert json.loads((run / "PARKED").read_text())["code"] == "gate-red"
    read = [" ".join(a) for a in _argv(repo)[before:]]
    assert not [a for a in read if "/reviews" in a or "/comments" in a or "/reactions" in a], read


@pytest.mark.parametrize("gate", [None, dict(GATE, status="IN_PROGRESS", conclusion=None)])
def test_no_gate_reading_yet_waits_without_parking(repo: Path, gate) -> None:
    run_id, run = _sealed(repo)
    _pr(repo, statusCheckRollup=[c for c in [{"__typename": "CheckRun", "name": "pytest",
                                              "status": "COMPLETED", "conclusion": "SUCCESS"}, gate] if c])
    _gh_file(repo, "gate_runs.json", {"check_runs": [] if gate is None else [
        {"id": 1, "name": "sysop/close-gate", "app": {"id": 42}, "status": "in_progress", "conclusion": None, "started_at": "2026-10-11T00:00:00Z"}]})
    r = _land(repo, run_id)
    assert r.returncode == 5 and _verdict(r) == "WAIT" and not (run / "PARKED").exists()
    assert ("no sysop/close-gate check from app 42" in r.stdout) if gate is None else ("is in_progress" in r.stdout)
    assert _merges(repo) == []


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
    t = text_of(SKILL)
    start = t.index("## `--request-review` and `--land <run-id>` (`Q-411`)")
    return t[start:t.index("## Step 1: Gather State", start)]


def test_the_selection_commands_run_as_written(repo: Path) -> None:
    """Phase 168 rule 3: every `close_run.py` line the `--agent` half A prescribes, then the
    unattended land's own (Phase 375), run in order."""
    found = re.findall(r"(python3 sysop/scripts/close_run\.py ([\w-]+)[^`\n]*)", _section())
    cmds: dict[str, list[str]] = {}
    for line, name in found:
        cmds.setdefault(name, []).append(line.strip())
    unattended = [c for c in cmds.get("land-check", []) if "--unattended" in c]
    assert len(unattended) == 1, cmds["land-check"]
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
    run_id = re.search(r"^RUN: (\S+)", r.stdout, re.M).group(1)
    run = Path(re.search(r"^DIR: (.+)$", r.stdout, re.M).group(1))
    (run / "report.md").write_text(REPORT, encoding="utf-8")
    assert sh(cmds["seal"][0].replace('"<run-id>"', f'"{run_id}"')).returncode == 0
    r = sh(unattended[0].replace('"<run-id>"', f'"{run_id}"').replace('"<default branch>"', '"main"')
           .replace('"<name>"', f'"{AGENT}"'))
    assert r.returncode == 0 and _verdict(r) == "ALREADY MERGED", r.stdout + r.stderr
    landed = [c for c in cmds["landed"] if c.endswith('landed "<run-id>"')]
    r = sh(landed[-1].replace('"<run-id>"', f'"{run_id}"'))
    assert r.returncode == 0 and "LOCKS_REMOVED: T-1" in r.stdout, r.stdout + r.stderr


def _unattended() -> str:
    sec = _section()
    start = sec.index("### Under `--land <run-id> --unattended --agent <name>`")
    return sec[start:]


def test_the_skill_names_the_unattended_land_and_its_flags() -> None:
    sec = _section()
    # Since Phase 393 (`Q-409` P4b) `close_arms.py begin` refuses every other use.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core" / "companion" / "scripts"))
    import close_arms
    assert {s for s in close_arms.FLAG_SETS if "--unattended" in s} == {
        frozenset({"--land", "--agent", "--unattended"}),
        frozenset({"--resume", "--request-review", "--agent", "--unattended"})}
    assert "not enabled" not in sec
    hint = text_of(SKILL).split("\n", 5)[3]
    assert hint.startswith("argument-hint:") and "--land <run-id> [--unattended --agent <name>]" in hint


def test_the_unattended_land_never_asks_and_never_passes_delete_branch() -> None:
    """No human is present (Phase 366's decisions, spec § 9), and `--auto --delete-branch` deleted
    nothing (Phase 375's P3), so item 3 deletes the branch and no merge here names the flag."""
    u = _unattended()
    assert "Never use `AskUserQuestion` and never relay a `!` command" in u
    assert "--delete-branch" not in u
    assert 'git push origin --delete "<BRANCH>"' in u and "unless `KEEP BRANCH: yes`" in u
    assert "do not fix the branch, `re-request`, `unpark` or `abandon`" in u
    assert "Do not run Step 5" in u and "appends nothing to `SYSOP_ISSUES.md`" in u
    for verdict in ("`VERDICT: WAIT` or `VERDICT: ARMED`", "`VERDICT: PARK`", "`VERDICT: ALREADY MERGED`"):
        assert verdict in u


def test_every_land_check_exit_the_unattended_section_names_is_one_the_cli_prints() -> None:
    src = SCRIPT.read_text(encoding="utf-8")
    body = src[src.index("def cmd_land_unattended("):src.index("# GitHub's CheckConclusionState")]
    printed = set(re.findall(r'print\("VERDICT: ([A-Z ]+)"\)', body))
    named = set(re.findall(r"`VERDICT: ([A-Z ]+)`", _unattended()))
    assert printed == named == {"WAIT", "ARMED", "PARK", "ALREADY MERGED"}, (printed, named)


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
    assert "| 0f       | Any task `land parked`" in doc and "| **Land parked** |" in doc


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


def test_the_class_at_land_is_the_tips_not_the_working_trees(repo: Path) -> None:
    """The class is read at the default branch's live tip: local main has the attestation and
    origin's tip does not, so the land parks."""
    text = (repo / "CLAUDE.md").read_text()
    _commit(repo, "no attestation", {"CLAUDE.md": text.replace("attested: 2026-10-01\n", "")})
    _g(repo, "push", "-q", "origin", "main")
    _g(repo, "fetch", "-q", "origin")
    _commit(repo, "attested locally only", {"CLAUDE.md": text})
    run_id, run = _sealed(repo)
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "names no attested" in r.stdout and _merges(repo) == []


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
    assert _verdict(r) == "ALREADY MERGED", r.stdout


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
    ({"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "SKIPPED"}, "ALREADY MERGED"),
    ({"__typename": "StatusContext", "context": "jenkins", "state": "ERROR"}, "PARK"),
    ({"__typename": "StatusContext", "context": "jenkins", "state": "PENDING"}, "WAIT"),
    ({"__typename": "StatusContext", "context": "jenkins", "state": "SUCCESS"}, "ALREADY MERGED"),
    ("garbage", "PARK"),
])
def test_every_registered_check_must_pass(repo: Path, entry, verdict: str) -> None:
    run_id, run = _sealed(repo)
    _clean(repo)
    _pr(repo, statusCheckRollup=[{"__typename": "CheckRun", "name": "pytest", "status": "COMPLETED",
                                  "conclusion": "SUCCESS"}, GATE, entry])
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


def test_a_missing_pushed_from_commit_parks_rather_than_crashing(repo: Path) -> None:
    run_id, run = _sealed(repo)
    rec = json.loads((run / "handoff.json").read_text())
    rec["pushed_from"] = "d" * 40
    (run / "handoff.json").write_text(json.dumps(rec), encoding="utf-8")
    r = _land(repo, run_id)
    assert r.returncode == 4 and "is not in this repository" in r.stdout and _merges(repo) == []


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
    assert t.next_action == f"/review-close --land {run_id} --unattended --agent {AGENT}"  # Phase 375
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
    assert _verdict(r) == "ALREADY MERGED", r.stdout


def test_a_tip_that_moved_with_unrelated_commits_does_not_park(repo: Path) -> None:
    run_id, _ = _sealed(repo)
    _clean(repo)
    _g(repo, "checkout", "-q", "--detach", "origin/main")
    _commit(repo, "docs elsewhere", {"docs/elsewhere.md": "x\n"})  # outside the class
    _g(repo, "push", "-q", "origin", "HEAD:main")
    _g(repo, "checkout", "-q", "main")
    _g(repo, "fetch", "-q", "origin")
    assert _verdict(_land(repo, run_id)) == "ALREADY MERGED"


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


# --- Phase 375: part B, the server setup and auto-merge ---------------------------------------

def _rules(**pr_over) -> list:
    rules = json.loads(json.dumps(SETUP_DEFAULTS["rules"]))
    rules[0]["parameters"].update(pr_over)
    return rules


def _status_rules(**over) -> list:
    rules = json.loads(json.dumps(SETUP_DEFAULTS["rules"]))
    rules[1]["parameters"].update(over)
    return rules


@pytest.mark.parametrize("name,data,why", [
    ("user", {"login": "Wade"}, "authenticated as the code owner Wade"),
    ("user", {"id": 1}, "the token's user has no login"),
    ("user", {"login": None}, "the token's user has no login"),
    ("permission", {"permission": "admin", "role_name": "admin"}, "role on the repository is 'admin'"),
    ("permission", {"permission": "write", "role_name": "maintain"}, "role on the repository is 'maintain'"),
    ("permission", {"permission": "write"}, "role on the repository is None"),
    ("rules", _rules(require_code_owner_review=False), "code-owner review and stale-review dismissal"),
    ("rules", _rules(dismiss_stale_reviews_on_push=False), "code-owner review and stale-review dismissal"),
    ("rules", _rules(require_last_push_approval=True), "last-push approval"),
    ("rules", _status_rules(strict_required_status_checks_policy=False), "with strict status checks"),
    ("rules", _status_rules(required_status_checks=[{"context": "sysop/close-gate", "integration_id": 15368}]),
     "requires sysop/close-gate from app 42"),
    ("rules", _status_rules(required_status_checks=[{"context": "sysop/close-gate"}]),
     "requires sysop/close-gate from app 42"),
    ("rules", _status_rules(required_status_checks=[{"context": "pytest", "integration_id": 42}]),
     "requires sysop/close-gate from app 42"),
    ("rules", [], "no ruleset applies to main"),
    ("rules", [dict(SETUP_DEFAULTS["rules"][0], type="required_status_checks")],
     "requires sysop/close-gate"),
    ("ruleset", {"current_user_can_bypass": "pull_requests_only"}, "can bypass ruleset 11 ('pull_requests_only')"),
    ("ruleset", {}, "can bypass ruleset 11 (None)"),
    ("environment", {"deployment_branch_policy": None}, "not set to selected branches"),
    ("environment", {"deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False}},
     "not set to selected branches"),
    ("policies", {"branch_policies": [{"name": "main", "type": "branch"}, {"name": "dev", "type": "branch"}]},
     "not exactly one branch rule naming main"),
    ("policies", {"branch_policies": [{"name": "main", "type": "tag"}]}, "not exactly one branch rule naming main"),
    ("policies", {"branch_policies": [{"name": "*", "type": "branch"}]}, "not exactly one branch rule naming main"),
    ("policies", {"branch_policies": []}, "not exactly one branch rule naming main"),
])
def test_each_setup_problem_parks_without_arming(repo: Path, name: str, data, why: str) -> None:
    run_id, run = _sealed(repo)
    _gh_file(repo, f"{name}.json", data)
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and why in r.stdout, r.stdout
    assert json.loads((run / "PARKED").read_text())["code"] == "setup" and _merges(repo) == []


@pytest.mark.parametrize("name", ["user", "permission", "rules", "ruleset", "environment", "policies"])
def test_a_setup_read_that_fails_parks(repo: Path, name: str) -> None:
    """Fail closed: the land does not merge on a setup it could not see."""
    run_id, run = _sealed(repo)
    (_state(repo) / f"fail_{name}").write_text("", encoding="utf-8")
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "cannot read" in r.stdout, r.stdout
    assert json.loads((run / "PARKED").read_text())["code"] == "setup" and _merges(repo) == []


@pytest.mark.parametrize("key", ["code_owner", "gate_app", "attested"])
def test_a_class_without_the_lands_keys_parks(repo: Path, key: str) -> None:
    text = (repo / "CLAUDE.md").read_text()
    line = next(l for l in text.splitlines() if l.startswith(f"{key}:"))
    _commit(repo, f"drop {key}", {"CLAUDE.md": text.replace(line + "\n", "")})
    _g(repo, "push", "-q", "origin", "main")
    _g(repo, "fetch", "-q", "origin")
    run_id, run = _sealed(repo)
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and f"names no {key}" in r.stdout and _merges(repo) == []


def test_a_future_attestation_parks(repo: Path) -> None:
    text = (repo / "CLAUDE.md").read_text()
    _commit(repo, "future", {"CLAUDE.md": text.replace("attested: 2026-10-01", "attested: 2999-01-01")})
    _g(repo, "push", "-q", "origin", "main")
    _g(repo, "fetch", "-q", "origin")
    run_id, _ = _sealed(repo)
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "is in the future" in r.stdout and _merges(repo) == []


@pytest.mark.parametrize("value", ["yes", "2026-13-01", "2026-02-30", "2026-10-1", "20261001", "2026-10-01T00:00"])
def test_an_attestation_that_is_not_a_date_refuses(tmp_path: Path, value: str) -> None:
    with pytest.raises(close_run.Refuse, match="attested is not a date"):
        _cls(tmp_path, CLASS + f"attested: {value}\n" if "attested" not in CLASS else
             CLASS.replace("attested: 2026-10-01", f"attested: {value}"))


def test_the_class_prints_its_attestation(repo: Path) -> None:
    r = _run(repo, "class")
    assert r.returncode == 0 and "ATTESTED: 2026-10-01" in r.stdout


def test_an_armed_pr_waits_then_parks_and_turns_auto_merge_off(repo: Path) -> None:
    run_id, run = _sealed(repo)
    _gh_file(repo, "merge_mode.json", "arm")
    r = _land(repo, run_id)
    assert r.returncode == 5 and _verdict(r) == "ARMED" and "auto-merge is on" in r.stdout
    assert len(_merges(repo)) == 1
    # A second land does not arm again.
    r = _land(repo, run_id)
    assert _verdict(r) == "ARMED" and len(_merges(repo)) == 1
    rec = json.loads((run / "handoff.json").read_text())
    rec["armed"]["at"] = "2000-01-01T00:00:00Z"
    (run / "handoff.json").write_text(json.dumps(rec), encoding="utf-8")
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "auto-merge turned off" in r.stdout
    assert _merges(repo)[-1] == ["pr", "merge", "7", "--disable-auto"]
    assert json.loads((_state(repo) / "pr.json").read_text())["autoMergeRequest"] is None
    assert json.loads((run / "PARKED").read_text())["code"] == "checks"


def test_an_armed_pr_whose_head_moved_parks_and_turns_auto_merge_off(repo: Path) -> None:
    """Phase 375's P4: auto-merge survives a push and merges the new head, so the land parks a
    moved head rather than letting GitHub merge a head the hand-off never recorded."""
    run_id, run = _sealed(repo)
    _gh_file(repo, "merge_mode.json", "arm")
    assert _verdict(_land(repo, run_id)) == "ARMED"
    pr = json.loads((_state(repo) / "pr.json").read_text())
    pr["headRefOid"] = "f" * 40
    (_state(repo) / "pr.json").write_text(json.dumps(pr), encoding="utf-8")
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "auto-merge turned off" in r.stdout
    assert json.loads((run / "PARKED").read_text())["code"] == "pr-state"


def test_a_park_reports_when_auto_merge_cannot_be_turned_off(repo: Path) -> None:
    run_id, run = _sealed(repo)
    _gh_file(repo, "merge_mode.json", "arm")
    assert _verdict(_land(repo, run_id)) == "ARMED"
    (_state(repo) / "merge_fail").write_text("", encoding="utf-8")
    _pr(repo, autoMergeRequest={"mergeMethod": "SQUASH"},
        statusCheckRollup=[dict(GATE, conclusion="FAILURE")])
    _gh_file(repo, "gate_runs.json", {"check_runs": [
        {"id": 1, "name": "sysop/close-gate", "app": {"id": 42}, "status": "completed", "conclusion": "failure", "started_at": "x"}]})
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "could not be turned off" in r.stdout and "a human turns it off" in r.stdout


@pytest.mark.parametrize("mode,why", [("fail", "enabling auto-merge failed"), ("silent", "shows none")])
def test_an_arm_that_fails_or_does_nothing_parks(repo: Path, mode: str, why: str) -> None:
    run_id, run = _sealed(repo)
    if mode == "fail":
        (_state(repo) / "merge_fail").write_text("", encoding="utf-8")
    else:
        _gh_file(repo, "merge_mode.json", "silent")
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and why in r.stdout
    assert json.loads((run / "PARKED").read_text())["code"] == "hard-fail"
    if mode == "silent":  # lens 2's D03: the land's own arm is turned off even when the PR shows none
        assert _merges(repo)[-1] == ["pr", "merge", "7", "--disable-auto"]


@pytest.mark.parametrize("state,code", [("BEHIND", "pr-state"), ("DIRTY", "conflict")])
def test_a_pr_github_cannot_merge_parks_before_arming(repo: Path, state: str, code: str) -> None:
    run_id, run = _sealed(repo)
    _pr(repo, mergeStateStatus=state)
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and _merges(repo) == []
    assert json.loads((run / "PARKED").read_text())["code"] == code


def test_a_missing_gate_check_parks_at_the_timeout(repo: Path) -> None:
    run_id, run = _sealed(repo)
    _pr(repo, statusCheckRollup=[{"__typename": "CheckRun", "name": "pytest", "status": "COMPLETED",
                                  "conclusion": "SUCCESS"}])
    _gh_file(repo, "gate_runs.json", {"check_runs": []})
    assert _verdict(_land(repo, run_id)) == "WAIT"
    rec = json.loads((run / "handoff.json").read_text())
    rec["checks_waiting_since"] = "2000-01-01T00:00:00Z"
    (run / "handoff.json").write_text(json.dumps(rec), encoding="utf-8")
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "no sysop/close-gate check" in r.stdout and _merges(repo) == []


def test_the_gate_is_read_from_its_apps_check_runs_not_the_rollups_name(repo: Path) -> None:
    """The rollup names no app: a rollup carrying the gate's name only as a status still lands
    when the gate app's own check run on the head is green."""
    run_id, _ = _sealed(repo)
    _pr(repo, statusCheckRollup=[{"__typename": "StatusContext", "context": "sysop/close-gate",
                                  "state": "SUCCESS"}])
    assert _verdict(_land(repo, run_id)) == "ALREADY MERGED"
    head = _g(repo, "rev-parse", BRANCH)
    assert any(f"commits/{head}/check-runs" in " ".join(a) for a in _argv(repo))


def _gate_run(app=42, status="completed", conclusion="success", started="2026-10-11T00:00:00Z", rid=1,
              title="t") -> dict:
    return {"id": rid, "name": "sysop/close-gate", "app": {"id": app, "slug": "x"}, "status": status,
            "conclusion": conclusion, "started_at": started, "output": {"title": title}}


def test_a_forged_gate_from_another_app_waits_then_parks(repo: Path) -> None:
    """Phase 375's R1: a branch workflow posted a green `sysop/close-gate` as `github-actions`,
    and the rollup showed it green. The land does not arm on it."""
    run_id, run = _sealed(repo)
    _gh_file(repo, "gate_runs.json", {"check_runs": [_gate_run(app=15368)]})
    r = _land(repo, run_id)
    assert _verdict(r) == "WAIT" and "no sysop/close-gate check from app 42" in r.stdout
    assert "1 run(s) of that name from another app, ignored" in r.stdout and _merges(repo) == []
    rec = json.loads((run / "handoff.json").read_text())
    rec["checks_waiting_since"] = "2000-01-01T00:00:00Z"
    (run / "handoff.json").write_text(json.dumps(rec), encoding="utf-8")
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and json.loads((run / "PARKED").read_text())["code"] == "checks"
    assert _merges(repo) == []


@pytest.mark.parametrize("runs,verdict,why", [
    ([_gate_run(conclusion="failure", title="governing path")], "PARK", "concluded failure: governing path"),
    ([_gate_run(status="in_progress", conclusion=None)], "WAIT", "is in_progress"),
    # The newest of the app's runs decides, whatever an older one said.
    ([_gate_run(rid=1, started="2026-10-11T00:00:00Z"),
      _gate_run(rid=2, started="2026-10-11T01:00:00Z", status="in_progress", conclusion=None)], "WAIT", "is in_progress"),
    ([_gate_run(rid=1, started="2026-10-11T00:00:00Z", conclusion="failure"),
      _gate_run(rid=2, started="2026-10-11T01:00:00Z")], "ALREADY MERGED", ""),
    ([_gate_run(conclusion="neutral")], "PARK", "concluded neutral"),
    ([], "WAIT", "no sysop/close-gate check from app 42"),
])
def test_the_gate_apps_newest_run_decides(repo: Path, runs, verdict: str, why: str) -> None:
    run_id, run = _sealed(repo)
    _gh_file(repo, "gate_runs.json", {"check_runs": runs})
    r = _land(repo, run_id)
    assert _verdict(r) == verdict and why in r.stdout, r.stdout
    if verdict == "PARK":
        assert json.loads((run / "PARKED").read_text())["code"] == "gate-red" and _merges(repo) == []


@pytest.mark.parametrize("how", ["fail", "shape"])
def test_an_unreadable_gate_reading_waits(repo: Path, how: str) -> None:
    run_id, _ = _sealed(repo)
    if how == "fail":
        (_state(repo) / "fail_gate_runs").write_text("", encoding="utf-8")
    else:
        _gh_file(repo, "gate_runs.json", {"check_runs": "nope"})
    r = _land(repo, run_id)
    assert _verdict(r) == "WAIT" and _merges(repo) == []


def test_setup_is_read_after_the_local_conditions_and_before_any_check(repo: Path) -> None:
    """The order the skill and spec state: PR, class, hand-off, Step 6's conditions, setup, checks."""
    src = SCRIPT.read_text(encoding="utf-8")
    body = src[src.index("def cmd_land_unattended("):src.index("# GitHub's CheckConclusionState")]
    order = ["return merged(data)", 'stop("pr-state", problems)', "read_class(root, rev=tip)",
             "handoff_problems(root, run, rec, agent)", 'stop("dirty"', 'stop("after-push"',
             "setup_problems(root, cls, default)", "check_states([c for c in checks", '"--auto", "--squash"']
    at = [body.index(n) for n in order]
    assert at == sorted(at), dict(zip(order, at))


# --- Phase 375's round 1 (lens 1) ------------------------------------------------------------

def _armed(repo: Path) -> tuple[str, Path]:
    run_id, run = _sealed(repo)
    _gh_file(repo, "merge_mode.json", "arm")
    assert _verdict(_land(repo, run_id)) == "ARMED"
    return run_id, run


def _auto(repo: Path):
    return json.loads((_state(repo) / "pr.json").read_text()).get("autoMergeRequest")


def test_a_park_by_command_turns_off_this_lands_auto_merge(repo: Path) -> None:
    """Lens 1's HIGH: `close_run.py park` wrote PARKED and left auto-merge on, so GitHub could
    merge a hand-off every reader called parked."""
    run_id, run = _armed(repo)
    r = _run(repo, "park", run_id, "relay", "a denied command")
    assert r.returncode == 0 and "auto-merge turned off" in r.stdout
    assert _auto(repo) is None and "armed" not in json.loads((run / "handoff.json").read_text())
    assert _merges(repo)[-1] == ["pr", "merge", "7", "--disable-auto"]


def test_a_parked_land_whose_disarm_failed_tries_again(repo: Path) -> None:
    run_id, run = _armed(repo)
    (_state(repo) / "merge_fail").write_text("", encoding="utf-8")
    r = _run(repo, "park", run_id, "relay", "x")
    assert "could not be turned off" in r.stdout and json.loads((run / "handoff.json").read_text())["armed"]
    (_state(repo) / "merge_fail").unlink()
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "auto-merge turned off" in r.stdout and _auto(repo) is None
    assert "armed" not in json.loads((run / "handoff.json").read_text())


@pytest.mark.parametrize("cmd", ["unpark", "re-request"])
def test_unpark_and_re_request_drop_the_arm(repo: Path, cmd: str) -> None:
    """Lens 1: an arm survives a push and merges the new head (P4), so a human who pushes a fix
    and re-requests must not inherit the arm made for the old head."""
    run_id, run = _armed(repo)
    if cmd == "unpark":
        (run / "PARKED").write_text(json.dumps({"code": "relay", "at": "x", "lines": ["x"]}), encoding="utf-8")
        args = ["unpark", run_id]
    else:
        args = ["re-request", run_id, "main"]
    r = _run(repo, *args)
    assert r.returncode == 0 and "auto-merge turned off" in r.stdout, r.stdout + r.stderr
    assert _auto(repo) is None and "armed" not in json.loads((run / "handoff.json").read_text())


def test_auto_merge_this_land_did_not_turn_on_parks_and_is_turned_off(repo: Path) -> None:
    """Lens 1: a request someone else made (here a merge commit, not a squash) was read as this
    land's arm, so its timeout restarted every run and ruling (s) never held."""
    run_id, run = _sealed(repo)
    _pr(repo, autoMergeRequest={"mergeMethod": "MERGE", "enabledBy": {"login": "someone-else"}})
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "turned on by someone-else (MERGE)" in r.stdout
    assert json.loads((run / "PARKED").read_text())["code"] == "pr-state"
    assert _auto(repo) is None and not [a for a in _merges(repo) if "--auto" in a]


def test_a_merge_at_another_head_is_named(repo: Path) -> None:
    run_id, _ = _sealed(repo)
    _pr(repo, state="MERGED", headRefOid="f" * 40)
    r = _land(repo, run_id)
    assert _verdict(r) == "ALREADY MERGED" and f"MERGED ELSEWHERE: merged at {'f' * 40}" in r.stdout


def test_an_attestation_dated_tomorrow_utc_is_not_the_future(repo: Path) -> None:
    import datetime as dt
    tomorrow = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).strftime("%Y-%m-%d")
    text = (repo / "CLAUDE.md").read_text()
    _commit(repo, "east of UTC", {"CLAUDE.md": text.replace("attested: 2026-10-01", f"attested: {tomorrow}")})
    _g(repo, "push", "-q", "origin", "main")
    _g(repo, "fetch", "-q", "origin")
    run_id, _ = _sealed(repo)
    assert _verdict(_land(repo, run_id)) == "ALREADY MERGED"


# --- Phase 375's round 1 (lens 3) ------------------------------------------------------------

def test_the_gates_superseded_in_progress_runs_do_not_hold_the_land(repo: Path) -> None:
    """Lens 3: each gate run opens an `in_progress` check run before it evaluates, and the
    superseded ones stay `in_progress` (three of them, then a `success`, on Phase 375's P2 head).
    Judged by `check_states`, that group was pending for good; the land must take the newest."""
    run_id, _ = _sealed(repo)
    stale = [{"__typename": "CheckRun", "name": "sysop/close-gate", "status": "IN_PROGRESS",
              "conclusion": None, "startedAt": f"2026-10-11T0{i}:00:00Z"} for i in range(3)]
    _pr(repo, statusCheckRollup=[{"__typename": "CheckRun", "name": "pytest", "status": "COMPLETED",
                                  "conclusion": "SUCCESS"}, *stale, dict(GATE, startedAt="2026-10-11T05:00:00Z")])
    _gh_file(repo, "gate_runs.json", {"check_runs": [
        *[{"id": i, "name": "sysop/close-gate", "app": {"id": 42}, "status": "in_progress", "conclusion": None,
           "started_at": f"2026-10-11T0{i}:00:00Z"} for i in range(3)],
        {"id": 9, "name": "sysop/close-gate", "app": {"id": 42}, "status": "completed", "conclusion": "success", "started_at": "2026-10-11T05:00:00Z"}]})
    assert _verdict(_land(repo, run_id)) == "ALREADY MERGED"


def test_a_tip_not_fetched_parks_at_the_timeout(repo: Path) -> None:
    """Lens 3: the stale-tip wait had no deadline, so a runner that never fetched waited for good."""
    run_id, run = _sealed(repo)
    _gh_file(repo, "tip.json", "e" * 40)
    assert _verdict(_land(repo, run_id)) == "WAIT"
    rec = json.loads((run / "handoff.json").read_text())
    rec["checks_waiting_since"] = "2000-01-01T00:00:00Z"
    (run / "handoff.json").write_text(json.dumps(rec), encoding="utf-8")
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "fetch origin main" in r.stdout and _merges(repo) == []


# --- Phase 375's round 1 (lens 2) ------------------------------------------------------------

def test_an_arm_that_fails_after_github_turned_it_on_is_turned_off(repo: Path) -> None:
    """Lens 2: `gh pr merge --auto` can fail after the server armed (a lost reply). The park must
    read the PR again and turn off what it shows."""
    run_id, run = _sealed(repo)
    _gh_file(repo, "merge_mode.json", "arm_then_fail")
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "auto-merge turned off" in r.stdout, r.stdout
    assert _auto(repo) is None and json.loads((run / "PARKED").read_text())["code"] == "hard-fail"


def test_a_kept_lock_that_is_gone_parks(repo: Path) -> None:
    run_id, run = _sealed(repo)
    (repo / "sysop/runtime/locks/T-1.lock").unlink()
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "T-1's kept lock is gone" in r.stdout and _merges(repo) == []


def test_an_arm_recorded_at_an_older_head_is_not_this_lands(repo: Path) -> None:
    """Lens 2's U01: a re-request whose disarm failed keeps `armed` at the old head while the
    hand-off's head moves on; auto-merge then on is not this land's arm for this head."""
    run_id, run = _armed(repo)
    rec = json.loads((run / "handoff.json").read_text())
    rec["armed"]["head"] = "a" * 40
    (run / "handoff.json").write_text(json.dumps(rec), encoding="utf-8")
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "not by this land at the recorded head" in r.stdout


def test_a_second_ruleset_that_can_be_bypassed_parks(repo: Path) -> None:
    """Lens 2's C09: every ruleset on the default branch is read, not only the first."""
    run_id, _ = _sealed(repo)
    rules = json.loads(json.dumps(SETUP_DEFAULTS["rules"]))
    rules[1]["ruleset_id"] = 12
    _gh_file(repo, "rules.json", rules)
    _gh_file(repo, "ruleset_12.json", {"id": 12, "current_user_can_bypass": "always"})
    r = _land(repo, run_id)
    assert _verdict(r) == "PARK" and "can bypass ruleset 12" in r.stdout and "ruleset 11" not in r.stdout


def test_a_gate_app_run_of_another_name_is_not_the_gate(repo: Path) -> None:
    run_id, _ = _sealed(repo)
    _gh_file(repo, "gate_runs.json", {"check_runs": [dict(_gate_run(), name="something-else")]})
    r = _land(repo, run_id)
    assert _verdict(r) == "WAIT" and "no sysop/close-gate check from app 42" in r.stdout


def test_sitrep_never_routes_a_parked_agent_hand_off_to_the_unattended_land(repo: Path) -> None:
    """Lens 2's R03: the existing check read the fallback string, never `_handoff_route`."""
    import sitrep_survey as ss
    run_id, _ = _sealed(repo)
    route = ss._handoff_route(repo, run_id, True)
    assert route.startswith("a human:") and "--unattended" not in route
    assert ss._handoff_route(repo, run_id, False) == f"/review-close --land {run_id} --unattended --agent {AGENT}"


@pytest.mark.parametrize("owner", ["a b", "a;rm -rf /", "", "-x", "x" * 65])
def test_sitrep_appends_no_agent_it_could_not_have_written(repo: Path, owner: str) -> None:
    import sitrep_survey as ss
    run_id, run = _sealed(repo)
    rec = json.loads((run / "handoff.json").read_text())
    rec["unattended"] = {"agent": owner}
    (run / "handoff.json").write_text(json.dumps(rec), encoding="utf-8")
    assert ss._handoff_route(repo, run_id, False) == f"/review-close --land {run_id}"
