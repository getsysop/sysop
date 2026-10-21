"""The lock's two kinds of reader agree about `workspace:` and `branch:` (`Q-614`, Phase 347).

Both lock writers (`claim_task.sh`, `batch_work.sh`) emit `workspace:` and `branch:`
unquoted. The line readers — `claim_task.sh --release`'s awk and `/review-close`'s
`line.partition(":")` loops — read the whole line; YAML did not. It cut a path at
` #` (`/tmp/proj #2/c7` read `/tmp/proj`), raised on a path holding `: ` (so the
whole lock read `lock unreadable`), and typed a branch named `0123`, `true`,
`2026-09-01` or `null` as a number, bool, date or None.

The fix is on the YAML side, and deliberately not a writer change: quoting on write
would have to strip in every line reader, six of which are `/review-close`'s, and
leaves every lock already on disk unquoted. So the YAML readers
(`sitrep_survey.load_lock_text`, which `scope_overlap.py` imports, and
`validate_tasks._load_lock_yaml`) take those two fields as the line readers do.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

import scope_overlap as so
import sitrep_survey as ss
import validate_tasks as vt
from skill_runner_text import text_of

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
REVIEW_CLOSE = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"


def _partition_reading(text: str, key: str) -> str | None:
    """`/review-close`'s reader (Step 0 arm (ii), and the tip read's workspace map):
    first line whose text before its first `:` IS the key, value `.strip()`ped."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        k, sep, v = line.partition(":")
        if sep and k not in fields:
            fields[k] = v.strip()
    return fields.get(key)


def _lock_text(workspace: str = "/w/proj-feat-1", branch: str = "feat/feat-1") -> str:
    """The writers' template, as `claim_task.sh` emits it."""
    return (
        "task_id: FEAT-1\nstatus: in_progress\nagent: a\n"
        f"branch: {branch}\nmode: worktree\nworkspace: {workspace}\n"
        "started: 2026-09-01T10:00:00Z\nexpires: 2026-09-03T10:00:00Z\n"
        "files_impacted:\n  - (update manually or via git diff --name-only main...HEAD)\n"
        "# plan_summary and notes are free text\n"
        "plan_summary: (update with a one-line description of the work)\nnotes:\n"
    )


def test_the_partition_reader_this_module_compares_against_is_still_the_closes():
    """The reference above is only a reference while `/review-close` reads that way.
    Both loops that resolve a branch's workspace from its lock are pinned here; if
    either changes shape, this module's parity claim must be re-derived."""
    # The first loop is Step 3c's, in `smoke_detect.py` since Phase 386 (`Q-409` P3); the
    # second is Step 3b step 0's, in `workspace_locate.py` since Phase 387. Each is checked
    # against the script the step still runs.
    text = text_of(REVIEW_CLOSE)
    assert "python3 sysop/scripts/smoke_detect.py" in text and "python3 sysop/scripts/workspace_locate.py" in text
    scripts = Path(__file__).resolve().parents[1] / "core/companion/scripts"
    smoke = (scripts / "smoke_detect.py").read_text(encoding="utf-8")
    locate = (scripts / "workspace_locate.py").read_text(encoding="utf-8")
    for loop, where in (
        ('_k, _sep, _v = _line.partition(":")\n'
         '                if _sep and _k not in _f:\n'
         '                    _f[_k] = _v.strip()', smoke),
        ('k, sep, v = line.partition(":")\n'
         '                if sep and k not in fields:\n'
         '                    fields[k] = v.strip()', locate),
    ):
        assert loop in where, f"/review-close no longer reads the lock this way:\n{loop}"


# ── workspace ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("workspace", [
    "/tmp/proj #2/c7",                 # the filed reproduction: YAML cut it at ` #`
    "/tmp/a: b/c",                     # YAML raised: the whole lock read unreadable
    "/tmp/it's here",
    "/tmp/it's: here",                 # the fallback's quoting doubles the `'`
    "/tmp/x #1: y #2",
    "/tmp/ordinary-path",
])
def test_workspace_is_the_line_reading_in_every_yaml_reader(workspace):
    text = _lock_text(workspace=workspace)
    assert _partition_reading(text, "workspace") == workspace
    data = ss.load_lock_text(text)
    assert data["workspace"] == workspace
    # The rest of the lock still reads — `: ` in one value must not hide the others.
    assert data["task_id"] == "FEAT-1" and data["status"] == "in_progress"
    assert data["files_impacted"] == ["(update manually or via git diff --name-only main...HEAD)"]
    assert data["plan_summary"] == "(update with a one-line description of the work)"
    assert vt._load_lock_yaml(text)["plan_summary"] == data["plan_summary"]


@pytest.mark.parametrize("agent", ["Agent: 7", "agent #2", "0123"])
def test_agent_the_callers_free_third_argument_is_the_line_reading(agent):
    """`claim_task.sh` writes `agent: ${AGENT_NAME}` from its third argument, unquoted:
    a `: ` in it made the whole lock unreadable, which routed /sitrep to a repair."""
    text = _lock_text().replace("agent: a", f"agent: {agent}")
    data = ss.load_lock_text(text)
    assert data["agent"] == agent == _partition_reading(text, "agent")
    assert data["workspace"] == "/w/proj-feat-1"
    assert vt._load_lock_yaml(text)["task_id"] == "FEAT-1"


def test_a_hand_quoted_workspace_keeps_its_quotes_as_the_partition_readers_do():
    text = _lock_text(workspace="'/x'")
    assert _partition_reading(text, "workspace") == "'/x'"
    assert ss.load_lock_text(text)["workspace"] == "'/x'"


def test_a_duplicate_workspace_line_first_wins_as_in_the_partition_readers():
    text = _lock_text(workspace="/first") + "workspace: /second\n"
    assert yaml.safe_load(text)["workspace"] == "/second"  # YAML alone: last wins
    assert ss.load_lock_text(text)["workspace"] == "/first"


def test_a_key_no_exact_line_carries_is_absent_as_in_the_partition_readers():
    """`workspace : /x` (space before the colon) is YAML's `workspace`. The exact-key
    partition readers (Step 0 arm (ii), the tip read's map) and `claim_task.sh`'s awk see no
    workspace, and neither does the survey. `/review-close`'s other two readers (2e and
    `claimed_ids`) strip the key and would see `/x`: the close disagrees with itself on this
    hand-edited shape, and no writer produces it (Phase 347's round, lenses 1 and 3)."""
    text = _lock_text().replace("workspace: /w/proj-feat-1", "workspace : /x")
    assert yaml.safe_load(text)["workspace"] == "/x"
    assert _partition_reading(text, "workspace") is None
    assert "workspace" not in ss.load_lock_text(text)


def test_a_block_scalar_workspace_stays_readable_and_reads_as_its_line():
    """The re-parse runs only on a parse error: a lock that YAML reads is read as
    before, so a `workspace: >` block scalar (never written by a writer) does not
    become unreadable, and its line reading, `>`, is what every line reader sees."""
    text = _lock_text().replace("workspace: /w/proj-feat-1", "workspace: >\n  /w/x")
    assert yaml.safe_load(text)["workspace"] == "/w/x\n"
    data = ss.load_lock_text(text)
    assert data["workspace"] == ">" == _partition_reading(text, "workspace")
    assert data["task_id"] == "FEAT-1"


def test_an_empty_workspace_reads_as_empty_not_none():
    text = _lock_text(workspace="")
    assert ss.load_lock_text(text)["workspace"] == ""


@pytest.mark.parametrize("text", [
    _lock_text(),
    _lock_text(workspace="/srv/work/app-feat-0001"),
    _lock_text(branch="feat/ops-foo", workspace="/w/app-ops-foo"),
    "task_id: BATCH-7\nstatus: in_progress\nagent: batch_work.sh\nbranch: review/batch-7\n"
    "mode: worktree\nworkspace: /w/app-batch-7\nstarted: 2026-09-01T10:00:00Z\n",
    "task_id: FEAT-1\nbranch: feat/x\n",          # no workspace at all
    "{}\n",
    "",
    "- a list\n",
])
def test_an_ordinary_lock_reads_exactly_as_before(text):
    assert ss.load_lock_text(text) == yaml.safe_load(text)
    assert vt._load_lock_yaml(text) == yaml.safe_load(text)


def test_a_lock_broken_elsewhere_still_raises():
    text = _lock_text(workspace="/tmp/a: b") + "notes: [unclosed\n"
    with pytest.raises(yaml.YAMLError):
        ss.load_lock_text(text)
    with pytest.raises(yaml.YAMLError):
        vt._load_lock_yaml(text)
    with pytest.raises(yaml.YAMLError):
        ss.load_lock_text("task_id: [unclosed\n")


# ── branch ───────────────────────────────────────────────────────────────


BRANCHES = ["0123", "true", "2026-09-01", "1e3", "null", "0", "false", "1_000", "yes", "12e3"]


@pytest.mark.parametrize("branch", BRANCHES)
def test_a_branch_yaml_would_type_is_the_line_reading(branch):
    # Every one is a legal git branch name.
    r = subprocess.run(["git", "check-ref-format", "--branch", branch], capture_output=True)
    assert r.returncode == 0, branch
    text = _lock_text(branch=branch)
    assert ss.load_lock_text(text)["branch"] == branch == _partition_reading(text, "branch")


def test_the_branch_sweep_is_not_vacuous():
    """Most of `BRANCHES` are not strings to YAML — that is what makes them the class."""
    typed = [b for b in BRANCHES if not isinstance(yaml.safe_load(f"b: {b}")["b"], str)]
    assert len(typed) >= 8, typed


def test_sitrep_reads_a_branch_named_0_as_that_branch_not_as_no_branch(tmp_path):
    """`branch: 0` read as `0`, which is falsy: `str(raw.get("branch") or "")` gave
    "", and the claim classified `claimed, no branch` — whose next action offers
    `--release`."""
    locks = tmp_path / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    (locks / "FEAT-1.lock").write_text(_lock_text(branch="0"), encoding="utf-8")
    lock = ss._read_locks(tmp_path)[0]
    assert lock.branch == "0" and not lock.unreadable


# ── the three loaders, end to end ────────────────────────────────────────


def test_sitrep_reads_a_colon_space_workspace_lock_as_readable(tmp_path):
    locks = tmp_path / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    (locks / "FEAT-1.lock").write_text(_lock_text(workspace="/tmp/a: b/c"), encoding="utf-8")
    unreadable: list = []
    lock = ss._read_locks(tmp_path, unreadable)[0]
    assert unreadable == [] and lock.unreadable == ""
    assert lock.workspace == "/tmp/a: b/c" and lock.branch == "feat/feat-1"


def test_scope_overlap_reads_a_colon_space_workspace_lock_as_readable(tmp_path):
    p = tmp_path / "FEAT-1.lock"
    p.write_text(_lock_text(workspace="/tmp/a: b/c", branch="0123"), encoding="utf-8")
    got = so._parse_lock_file(p)
    assert got.unreadable == ""
    assert got["workspace"] == "/tmp/a: b/c" and got["branch"] == "0123"


def test_scope_overlap_says_so_when_the_shared_reader_cannot_be_imported(tmp_path, monkeypatch):
    p = tmp_path / "FEAT-1.lock"
    p.write_text(_lock_text(), encoding="utf-8")
    monkeypatch.setattr(so, "_survey_module", lambda: None)
    got = so._parse_lock_file(p)
    assert "sitrep_survey.py could not be imported" in got.unreadable


def _expired_placeholder_lock(workspace: str) -> str:
    past = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _lock_text(workspace=workspace).replace(
        "expires: 2026-09-03T10:00:00Z", f"expires: {past}").replace(
        "started: 2026-09-01T10:00:00Z", "started: 2026-01-01T10:00:00Z")


@pytest.mark.parametrize("workspace", ["/tmp/ordinary", "/tmp/a: b/c"])
def test_validate_warns_on_an_expired_placeholder_lock_whatever_its_workspace(tmp_path, workspace):
    """The expiry warning read the whole lock as YAML, so a `: ` in the workspace
    path raised, the lock was skipped, and the warning never fired."""
    locks = tmp_path / "locks"
    locks.mkdir()
    p = locks / "FEAT-1.lock"
    p.write_text(_expired_placeholder_lock(workspace), encoding="utf-8")
    report = vt.Report()
    vt._check_expired_placeholder_lock(p, "FEAT-1", report)
    assert any("expired at" in str(w) for w in report.warnings), report.warnings


def test_a_deeply_nested_lock_is_unreadable_not_a_crash(tmp_path):
    """`yaml.safe_load` raises `RecursionError`, which is not a `YAMLError`; uncaught,
    it took `/sitrep` down with a traceback (its `main()` catches only
    `KeyboardInterrupt`)."""
    locks = tmp_path / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    p = locks / "FEAT-1.lock"
    p.write_text("task_id: FEAT-1\nnotes: " + "[" * 5000 + "\n", encoding="utf-8")
    unreadable: list = []
    lock = ss._read_locks(tmp_path, unreadable)[0]
    assert "RecursionError" in lock.unreadable and len(unreadable) == 1
    assert "RecursionError" in so._parse_lock_file(p).unreadable
    vt._check_expired_placeholder_lock(p, "FEAT-1", vt.Report())  # no raise


# ── the filed reproduction, through both scripts as shipped ──────────────


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    return env


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True, env=_env()).stdout.strip()


def test_the_filed_reproduction_a_claim_under_proj_hash_2(tmp_path):
    """A real `claim_task.sh --lock` under a directory named `proj #2`: the collision
    check grades the live worktree `likely`, and `/sitrep` finds it rather than
    calling the lock stale and suggesting its removal."""
    root = tmp_path / "proj #2" / "main"
    (root / "src" / "api").mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    (root / "src" / "api" / "base.py").write_text("x = 1\n", encoding="utf-8")
    (root / ".gitignore").write_text("sysop/runtime/\n", encoding="utf-8")
    scripts = root / "sysop" / "scripts"
    scripts.mkdir(parents=True)
    for p in list(SCRIPTS.glob("*.py")) + list(SCRIPTS.glob("*.sh")):
        (scripts / p.name).write_bytes(p.read_bytes())
    (root / "tasks" / "open").mkdir(parents=True)
    task = ("  - {{id: {0}, title: T, phase: 6, status: open, effort: Low, "
            "blast_radius: single-module, user_action: false, body: open/{0}.md}}\n")
    (root / "tasks" / "index.yml").write_text(
        "schema_version: 2\nphases:\n"
        "  - {number: 6, title: P, status: in_progress, current_focus: true}\n"
        "tasks:\n" + task.format("FEAT-AAA") + task.format("FEAT-CCC"), encoding="utf-8")
    (root / "tasks" / "open" / "FEAT-AAA.md").write_text("# FEAT-AAA\n", encoding="utf-8")
    (root / "tasks" / "open" / "FEAT-CCC.md").write_text(
        "# FEAT-CCC\n\n## Key files\n- `src/api/routes.py`\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    r = subprocess.run(["bash", "sysop/scripts/claim_task.sh", "--lock", "FEAT-AAA",
                        "feat/feat-aaa", "a"], cwd=root, capture_output=True, text=True,
                       env=_env())
    assert r.returncode == 0, r.stdout + r.stderr
    lock = (root / "sysop" / "runtime" / "locks" / "FEAT-AAA.lock").read_text(encoding="utf-8")
    ws = _partition_reading(lock, "workspace")
    assert " #2/" in ws, ws  # the precondition: the writer put ` #` in the value
    (Path(ws) / "src" / "api" / "routes.py").write_text("y = 2\n", encoding="utf-8")
    _git(Path(ws), "add", "-A")
    _git(Path(ws), "commit", "-qm", "aaa")

    out = subprocess.run([sys.executable, "sysop/scripts/scope_overlap.py", "--json", "FEAT-CCC"],
                         cwd=root, capture_output=True, text=True, env=_env())
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["max_verdict"] == "likely", got
    assert [(o["task_id"], o["verdict"], o["workspace"]) for o in got["overlaps"]] == [
        ("FEAT-AAA", "likely", ws)], got

    out = subprocess.run([sys.executable, "sysop/scripts/sitrep_survey.py", "--json"],
                         cwd=root, capture_output=True, text=True, env=_env())
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert not [d for d in got["discrepancies"] if d["kind"] == "stale lock"], got["discrepancies"]
    assert got["tasks"][0]["state"] == "in progress", got["tasks"]
    assert re.search(r"proj #2/main-feat-aaa$", got["tasks"][0]["worktree"]), got["tasks"]


def test_trailing_whitespace_is_stripped_as_the_partition_readers_do():
    """Phase 347's round (lens 1, L13): an lstrip-only reading kept trailing spaces the
    close's `.strip()` drops, and nothing noticed."""
    text = _lock_text(workspace="/w/proj-feat-1   ")
    assert _partition_reading(text, "workspace") == "/w/proj-feat-1"
    assert ss.load_lock_text(text)["workspace"] == "/w/proj-feat-1"


def test_an_impossible_date_makes_the_lock_unreadable_not_a_crash(tmp_path):
    """PyYAML raises ValueError, not a YAMLError, for `2026-09-31`; a hand-extended
    `expires:` then took the whole survey down (Phase 347's round, lens 1)."""
    lock = tmp_path / "FEAT-1.lock"
    lock.write_text(_lock_text().replace("expires: 2026-09-03T10:00:00Z",
                                         "expires: 2026-09-31T10:00:00Z"), encoding="utf-8")
    fields, exc = ss._load_lock_file(lock)
    assert fields == {} and isinstance(exc, ValueError), (fields, exc)
    assert so._parse_lock_file(lock).unreadable
