"""`unknown` end to end (`Q-613`, Phase 339): the collision checks, run as shipped.

`Q-613` was reproduced on a fixture: `scope_overlap --json FEAT-CCC` graded a live
in-flight worktree `likely`, and with that task's lock corrupted the overlap was
simply gone, while git still listed the worktree. `next_task --avoid-inflight`
chose a task whose body could not be read over a readable one and printed
"none detected". Phase 333 had put the reason in `--json` `notes`, which neither
`next_task`'s stdout nor `/auto-build`'s rank reads.

Everything here runs the shipped code the way a consumer runs it: the scripts are
copied into a real repository's `sysop/scripts/`, the in-flight tasks are real
`git worktree`s with committed changes, and `/auto-build`'s Step 1 is the heredoc
extracted from the skill, run with its own command word's argument shape. No
reader is injected and nothing is monkeypatched. Two kinds of test change the
copied tree on purpose: one replaces the copied primitive with a stub, to make
it fail partway through `/auto-build`'s loop, and the locks-directory tests take
a directory's permissions away and restore them.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from _heredoc_population import heredoc_containing

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
AUTO_BUILD = REPO_ROOT / "core" / "skills" / "auto-build" / "SKILL.md"

BAD = b"\xff\xfe not utf-8 \xe9\n"
HINT = ('# plan_summary and notes are free text: quote a value that contains ": " '
        '(plan_summary: "a: b"), or every YAML reader of this lock (/sitrep, the collision '
        'checks) sees it as unreadable.')


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    return env


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True, env=_env()).stdout


def _task(tid: str, status: str, body: bool = True) -> str:
    line = f"  - {{id: {tid}, title: T, phase: 6, status: {status}, effort: Low, " \
           f"blast_radius: single-module, user_action: false"
    return line + (f", body: open/{tid}.md}}\n" if body else "}\n")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A consumer repository with two tasks building in real worktrees.

    FEAT-AAA's worktree commits `src/api/routes.py`; FEAT-BBB's commits
    `src/api/other.py`. A candidate whose `## Key files` names `src/api/routes.py`
    therefore grades `likely` against AAA and `possible` (same directory) against
    BBB, which is the healthy reading `Q-613` started from."""
    root = tmp_path / "consumer"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "src" / "api").mkdir(parents=True)
    (root / "src" / "api" / "base.py").write_text("x = 1\n", encoding="utf-8")
    (root / ".gitignore").write_text("sysop/runtime/\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    scripts = root / "sysop" / "scripts"
    scripts.mkdir(parents=True)
    for p in SCRIPTS.glob("*.py"):
        shutil.copy2(p, scripts / p.name)
    tasks = root / "tasks"
    (tasks / "open").mkdir(parents=True)
    (tasks / "index.yml").write_text(
        "schema_version: 2\nphases:\n"
        "  - {number: 6, title: P, status: in_progress, current_focus: true}\n"
        "tasks:\n" + _task("FEAT-AAA", "in_progress") + _task("FEAT-BBB", "in_progress")
        + _task("FEAT-CCC", "open") + _task("FEAT-DDD", "open"),
        encoding="utf-8")
    for tid in ("FEAT-AAA", "FEAT-BBB"):
        (tasks / "open" / f"{tid}.md").write_text(f"# {tid}\n", encoding="utf-8")
    (tasks / "open" / "FEAT-CCC.md").write_text(
        "# FEAT-CCC\n\n## Key files\n- `src/api/routes.py`\n", encoding="utf-8")
    (tasks / "open" / "FEAT-DDD.md").write_text(
        "# FEAT-DDD\n\n## Key files\n- `docs/guide.md`\n", encoding="utf-8")
    locks = root / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    for tid, path in (("FEAT-AAA", "src/api/routes.py"), ("FEAT-BBB", "src/api/other.py")):
        ws = tmp_path / f"wt-{tid.lower()}"
        _git(root, "worktree", "add", "-q", "-b", f"feat/{tid.lower()}", str(ws))
        (ws / path).write_text("y = 2\n", encoding="utf-8")
        _git(ws, "add", "-A")
        _git(ws, "commit", "-qm", tid)
        (locks / f"{tid}.lock").write_text(
            f"task_id: {tid}\nstatus: in_progress\nbranch: feat/{tid.lower()}\n"
            f"workspace: {ws}\n", encoding="utf-8")
    return root


def _overlap_json(root: Path, tid: str) -> dict:
    r = subprocess.run([sys.executable, "sysop/scripts/scope_overlap.py", "--json", tid],
                       cwd=root, capture_output=True, text=True, env=_env())
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _verdicts(obj: dict) -> list[tuple[str, str]]:
    return [(o["task_id"], o["verdict"]) for o in obj["overlaps"]]


def test_the_filed_reproduction_healthy(repo):
    obj = _overlap_json(repo, "FEAT-CCC")
    assert obj["max_verdict"] == "likely", obj
    assert _verdicts(obj) == [("FEAT-AAA", "likely"), ("FEAT-BBB", "possible")], obj


@pytest.mark.parametrize("corrupt", [BAD, b"task_id: [unclosed\n", b""],
                         ids=["undecodable", "yaml-error", "empty"])
def test_the_filed_reproduction_a_corrupted_lock_is_unknown_not_gone(repo, corrupt):
    (repo / "sysop/runtime/locks/FEAT-AAA.lock").write_bytes(corrupt)
    assert "wt-feat-aaa" in _git(repo, "worktree", "list")  # still listed by git
    obj = _overlap_json(repo, "FEAT-CCC")
    assert _verdicts(obj) == [("FEAT-AAA", "unknown"), ("FEAT-BBB", "possible")], obj
    assert obj["max_verdict"] == "unknown", obj
    assert "lock" in obj["overlaps"][0]["reason"], obj


def test_a_worktree_git_cannot_read_is_unknown(repo, tmp_path):
    (tmp_path / "wt-feat-aaa" / ".git").write_text("gitdir: /nonexistent\n", encoding="utf-8")
    obj = _overlap_json(repo, "FEAT-CCC")
    aaa = next(o for o in obj["overlaps"] if o["task_id"] == "FEAT-AAA")
    assert aaa["verdict"] == "unknown" and "could not read its worktree" in aaa["reason"], obj
    # Round 1 (execution lens): a broken worktree used to be reported as an unresolvable
    # default branch, with a `git remote set-head` remedy that cannot help.
    assert not any("default branch" in n for n in obj["notes"]), obj


def _next_task(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "sysop/scripts/next_task.py", "--avoid-inflight"],
        cwd=root, capture_output=True, text=True, env=_env())


def test_next_task_healthy_picks_by_id_and_reports_clear(repo):
    # FEAT-CCC likely-collides; FEAT-DDD is clear, so the flag picks FEAT-DDD.
    r = _next_task(repo)
    assert r.returncode == 0, r.stderr
    assert "FEAT-DDD" in r.stdout and "FEAT-CCC" not in r.stdout, r.stdout
    assert "**In-flight overlap:** none detected (2 task(s) in flight)" in r.stdout, r.stdout


def test_next_task_does_not_pick_an_unreadable_body_over_a_readable_one(repo):
    """`Q-613`'s second reproduction, with FEAT-CCC out of the pool so the choice
    is between an unreadable body that sorts first by id and a readable clear one."""
    idx = repo / "tasks" / "index.yml"
    idx.write_text(idx.read_text(encoding="utf-8").replace(
        "id: FEAT-CCC, title: T, phase: 6, status: open",
        "id: FEAT-CCC, title: T, phase: 6, status: deferred") + _task("FEAT-EEE", "open"),
        encoding="utf-8")
    (repo / "tasks" / "open" / "FEAT-EEE.md").write_text(
        "# FEAT-EEE\n\n## Key files\n- `docs/other.md`\n", encoding="utf-8")
    (repo / "tasks" / "open" / "FEAT-DDD.md").write_bytes(b"## Key files\n" + BAD)
    r = _next_task(repo)
    assert r.returncode == 0, r.stderr
    assert "FEAT-EEE" in r.stdout and "none detected" in r.stdout, r.stdout


def test_next_task_annotates_unknown_when_it_is_the_only_choice(repo):
    idx = repo / "tasks" / "index.yml"
    idx.write_text(idx.read_text(encoding="utf-8").replace(
        "id: FEAT-CCC, title: T, phase: 6, status: open",
        "id: FEAT-CCC, title: T, phase: 6, status: deferred"), encoding="utf-8")
    (repo / "tasks" / "open" / "FEAT-DDD.md").write_bytes(b"## Key files\n" + BAD)
    r = _next_task(repo)
    assert r.returncode == 0, r.stderr
    assert "**In-flight overlap:** ⚠ overlap unknown with FEAT-AAA — " in r.stdout, r.stdout
    assert "FEAT-DDD's body could not be read" in r.stdout, r.stdout
    assert "none detected" not in r.stdout, r.stdout


def _auto_build_step1(root: Path) -> list[str]:
    body = heredoc_containing(AUTO_BUILD, "inflight_verdict = {}")
    r = subprocess.run([sys.executable, "-", ""], input=body, cwd=root,
                       capture_output=True, text=True, env=_env())
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout.splitlines()


def test_auto_build_step1_prints_each_overlap_with_its_own_verdict(repo):
    """Before Phase 339 every `# overlap` line carried the candidate's MAX verdict,
    so FEAT-CCC's same-directory hit on FEAT-BBB printed as `likely`."""
    out = _auto_build_step1(repo)
    overlaps = [l.split("\t") for l in out if l.startswith("# overlap\t")]
    assert ["# overlap", "FEAT-CCC", "likely", "FEAT-AAA", "src/api/routes.py"] in overlaps, out
    assert any(o[1:4] == ["FEAT-CCC", "possible", "FEAT-BBB"] for o in overlaps), out


def test_auto_build_step1_grades_and_sorts_unknown(repo):
    (repo / "sysop/runtime/locks/FEAT-AAA.lock").write_bytes(BAD)
    out = _auto_build_step1(repo)
    rows = [l.split("\t") for l in out if l.startswith("FEAT-")]
    # Both lose FEAT-AAA's lock; equal grade, so id decides.
    assert [(r[0], r[4]) for r in rows] == [
        ("FEAT-CCC", "inflight=unknown"), ("FEAT-DDD", "inflight=unknown")], out
    overlaps = [l.split("\t") for l in out if l.startswith("# overlap\t")]
    unknown = [o for o in overlaps if o[2] == "unknown"]
    assert unknown and all(o[3] == "FEAT-AAA" and "lock" in o[4] for o in unknown), out


def test_auto_build_step1_sorts_unknown_behind_possible_and_clear(repo):
    """Four candidates at equal unlock and effort, one per grade. The id order is
    the reverse of the risk order, so only the overlap key can produce it."""
    idx = repo / "tasks" / "index.yml"
    text = idx.read_text(encoding="utf-8")
    for tid, kf in (("FEAT-ZCLEAR", "docs/z.md"), ("FEAT-YPOSS", "src/api/new.py"),
                    ("FEAT-XUNK", None), ("FEAT-WLIKE", "src/api/routes.py")):
        text += _task(tid, "open")
        body = f"# {tid}\n\n## Key files\n- `{kf}`\n" if kf else None
        path = repo / "tasks" / "open" / f"{tid}.md"
        path.write_bytes(body.encode() if body else b"## Key files\n" + BAD)
    text = text.replace("id: FEAT-CCC, title: T, phase: 6, status: open",
                        "id: FEAT-CCC, title: T, phase: 6, status: deferred")
    text = text.replace("id: FEAT-DDD, title: T, phase: 6, status: open",
                        "id: FEAT-DDD, title: T, phase: 6, status: deferred")
    idx.write_text(text, encoding="utf-8")
    rows = [l.split("\t") for l in _auto_build_step1(repo) if l.startswith("FEAT-")]
    assert [(r[0], r[4]) for r in rows] == [
        ("FEAT-ZCLEAR", "inflight=none"), ("FEAT-YPOSS", "inflight=possible"),
        ("FEAT-XUNK", "inflight=unknown"), ("FEAT-WLIKE", "inflight=likely")], rows


def test_auto_build_step1_drops_every_annotation_when_the_primitive_fails_partway(repo):
    """The heredoc's contract is "any failure → no annotation, batch math unchanged".
    Before Phase 339 its `except` emptied only the verdicts, so a failure on the second
    candidate still printed `# overlap` lines for the first. The stub stands in for the
    primitive and raises on FEAT-DDD, which Step 1 assesses after FEAT-CCC."""
    (repo / "sysop" / "scripts" / "scope_overlap.py").write_text(
        "from types import SimpleNamespace as N\n"
        "def _worktree_changed_paths(ws):\n    return []\n"
        "def assess(tid, worktree_reader=None):\n"
        "    if tid == 'FEAT-DDD':\n        raise RuntimeError('boom')\n"
        "    o = N(task_id='FEAT-AAA', verdict='likely', evidence=['src/api/routes.py'], reason='')\n"
        "    return N(in_flight_count=2, max_verdict='likely', overlaps=[o])\n",
        encoding="utf-8")
    out = _auto_build_step1(repo)
    assert not any(l.startswith("# ") for l in out), out
    assert all("inflight=none" in l for l in out if l.startswith("FEAT-")), out


@pytest.mark.parametrize("script", ["claim_task.sh", "batch_work.sh"])
def test_the_seeded_lock_says_to_quote_free_text(script):
    """A live consumer lock carried an unquoted `notes:` value containing `: `, and every
    YAML reader saw it as unreadable (the shell readers are anchored awk, and read on). The seeded template now says so beside the two
    free-text fields, as a YAML comment every reader skips."""
    import yaml

    text = (SCRIPTS / script).read_text(encoding="utf-8")
    hint = [l for l in text.splitlines() if l.startswith("# plan_summary and notes are free text")]
    assert hint == [HINT], hint  # the advice itself, not only its opening words
    at = text.index(hint[0])
    assert text.index("\nplan_summary: (update with", at) == at + len(hint[0]), \
        "the hint must sit directly above plan_summary:, inside the lock heredoc"
    sample = hint[0] + '\nplan_summary: "a: b"\nnotes: "held: waiting on data"\n'
    assert yaml.safe_load(sample) == {"plan_summary": "a: b", "notes": "held: waiting on data"}


def test_a_partial_git_read_with_a_same_directory_hit_is_unknown(repo, tmp_path):
    """Round 1, execution lens, HIGH. FEAT-BBB's worktree commits `src/api/other.py`
    and edits FEAT-CCC's `src/api/routes.py` uncommitted. With its index corrupted,
    `git status` fails and `git diff` does not, so what was read is a same-directory
    hit. The first cut graded that `possible`, below `unknown`, with no reason: the one
    task whose unread half held the exact match looked like the safer choice."""
    ws = tmp_path / "wt-feat-bbb"
    (ws / "src/api/routes.py").write_text("changed = True\n", encoding="utf-8")
    healthy = _overlap_json(repo, "FEAT-CCC")
    assert ("FEAT-BBB", "likely") in _verdicts(healthy), healthy
    index = Path(_git(ws, "rev-parse", "--git-path", "index").strip())
    index = index if index.is_absolute() else ws / index
    index.write_bytes(b"garbage")
    obj = _overlap_json(repo, "FEAT-CCC")
    bbb = next(o for o in obj["overlaps"] if o["task_id"] == "FEAT-BBB")
    assert bbb["verdict"] == "unknown" and bbb["evidence"] == ["src/api/other.py"], obj
    assert "git status failed" in bbb["reason"], obj


def test_a_lock_with_an_unquoted_colon_grades_a_fallback_hit_unknown(repo):
    """Round 1, execution lens: the lock shape found live in a consumer (an unquoted
    `notes:` value containing `: `). FEAT-AAA's lock is lost, but its body still names
    `src/api/routes.py`, so FEAT-ABC (`src/api/new.py`) reads a same-directory hit on
    that fallback. The first cut graded it `possible`, ahead of every `unknown`, and
    `next_task` picked it over FEAT-DDD. Both now read `unknown` against FEAT-AAA."""
    (repo / "tasks/open/FEAT-AAA.md").write_text(
        "# FEAT-AAA\n\n## Key files\n- `src/api/routes.py`\n", encoding="utf-8")
    idx = repo / "tasks" / "index.yml"
    idx.write_text(idx.read_text(encoding="utf-8").replace(
        "id: FEAT-CCC, title: T, phase: 6, status: open",
        "id: FEAT-CCC, title: T, phase: 6, status: deferred") + _task("FEAT-ABC", "open"),
        encoding="utf-8")
    (repo / "tasks/open/FEAT-ABC.md").write_text(
        "# FEAT-ABC\n\n## Key files\n- `src/api/new.py`\n", encoding="utf-8")
    lock = repo / "sysop/runtime/locks/FEAT-AAA.lock"
    lock.write_text(lock.read_text(encoding="utf-8") + "notes: held: waiting on data\n",
                    encoding="utf-8")
    abc = next(o for o in _overlap_json(repo, "FEAT-ABC")["overlaps"] if o["task_id"] == "FEAT-AAA")
    assert abc["verdict"] == "unknown" and abc["evidence"] == ["src/api/routes.py"], abc
    assert "lock could not be read" in abc["reason"], abc
    rows = [l.split("\t") for l in _auto_build_step1(repo) if l.startswith("FEAT-")]
    assert [(r[0], r[4]) for r in rows] == [
        ("FEAT-ABC", "inflight=unknown"), ("FEAT-DDD", "inflight=unknown")], rows


def test_an_unlistable_locks_directory_reaches_every_caller(repo):
    import os as _os
    if hasattr(_os, "geteuid") and _os.geteuid() == 0:
        pytest.skip("root lists a mode-000 directory")
    locks = repo / "sysop/runtime/locks"
    locks.chmod(0)
    try:
        text = subprocess.run([sys.executable, "sysop/scripts/scope_overlap.py", "FEAT-CCC"],
                              cwd=repo, capture_output=True, text=True, env=_env()).stdout
        body = heredoc_containing(AUTO_BUILD, "inflight_verdict = {}")
        step1 = subprocess.run([sys.executable, "-", ""], input=body, cwd=repo,
                               capture_output=True, text=True, env=_env())
    finally:
        locks.chmod(0o755)
    assert "No work in flight" not in text and "could not be listed" in text, text
    assert "sysop/runtime/locks/ — overlap unknown: no in-flight task can be named" in text, text
    # Round 2 (execution lens): Step 1's own lock set came from `glob`, so both claimed
    # tasks were offered, and sorted first. It now refuses, as `next_task` does.
    assert step1.returncode == 2, step1
    assert step1.stdout.startswith("ERROR: sysop/runtime/locks could not be listed"), step1.stdout
    assert "FEAT-" not in step1.stdout, step1.stdout


def test_next_task_refuses_an_unlistable_locks_directory(repo):
    """Round 1 (execution lens): `next_task`'s own lock read went blind too, so every
    claimed task read as free and FEAT-AAA, already claimed, could be offered."""
    import os as _os
    if hasattr(_os, "geteuid") and _os.geteuid() == 0:
        pytest.skip("root lists a mode-000 directory")
    locks = repo / "sysop/runtime/locks"
    locks.chmod(0)
    try:
        r = _next_task(repo)
    finally:
        locks.chmod(0o755)
    assert r.returncode == 1 and "cannot tell which tasks are claimed" in r.stderr, r
    assert "### FEAT-" not in r.stdout, r.stdout


def test_next_task_note_names_an_unlistable_locks_directory(repo, monkeypatch):
    """`note_for` itself, in-process, since the CLI now refuses before it runs."""
    import os as _os
    if hasattr(_os, "geteuid") and _os.geteuid() == 0:
        pytest.skip("root lists a mode-000 directory")
    sys.path.insert(0, str(repo / "sysop" / "scripts"))
    try:
        for name in ("next_task", "scope_overlap", "sitrep_survey"):
            sys.modules.pop(name, None)
        import next_task as copied
        _, note_for = copied._build_avoid_inflight(repo)
        locks = repo / "sysop/runtime/locks"
        locks.chmod(0)
        try:
            note = note_for("FEAT-CCC")
        finally:
            locks.chmod(0o755)
    finally:
        sys.path.remove(str(repo / "sysop" / "scripts"))
        for name in ("next_task", "scope_overlap", "sitrep_survey"):
            sys.modules.pop(name, None)
    assert note.startswith("⚠ overlap unknown with sysop/runtime/locks — the locks directory"), note


def test_auto_build_step1_keeps_unblocker_first_and_overlap_before_effort(repo):
    """Round 1, guards lens (a02, a03): every earlier sort test held unlock and effort
    equal, so the heredoc's key could be reordered with every test green. Here an
    `unknown` candidate unblocks another task and must still lead, and among the rest a
    clear High task must beat a `possible` Low one."""
    idx = repo / "tasks" / "index.yml"
    text = idx.read_text(encoding="utf-8")
    for tid in ("FEAT-CCC", "FEAT-DDD"):
        text = text.replace(f"id: {tid}, title: T, phase: 6, status: open",
                            f"id: {tid}, title: T, phase: 6, status: deferred")
    (repo / "sysop/runtime/locks/FEAT-AAA.lock").unlink()
    (repo / "sysop/runtime/locks/FEAT-AAA.lock").write_text(
        "task_id: FEAT-AAA\nstatus: in_progress\n", encoding="utf-8")  # no workspace: fallback
    (repo / "tasks/open/FEAT-AAA.md").write_text(
        "# FEAT-AAA\n\n## Key files\n- `src/api/routes.py`\n", encoding="utf-8")
    rows_in = {
        "FEAT-UNB": ("Low", None, b"## Key files\n" + BAD),      # unknown, unblocks FEAT-DEP
        "FEAT-POSS": ("Low", "src/api/new.py", None),               # possible (same dir)
        "FEAT-CLEAR": ("High", "docs/z.md", None),                  # clear, but High effort
    }
    for tid, (effort, kf, raw) in rows_in.items():
        text += (f"  - {{id: {tid}, title: T, phase: 6, status: open, effort: {effort}, "
                 f"blast_radius: single-module, user_action: false, body: open/{tid}.md}}\n")
        path = repo / "tasks/open" / f"{tid}.md"
        path.write_bytes(raw) if raw else path.write_text(
            f"# {tid}\n\n## Key files\n- `{kf}`\n", encoding="utf-8")
    text += ("  - {id: FEAT-DEP, title: T, phase: 6, status: open, effort: Low, "
             "blast_radius: single-module, user_action: false, body: open/FEAT-DEP.md, "
             "depends_on: [FEAT-UNB]}\n")
    (repo / "tasks/open/FEAT-DEP.md").write_text("# FEAT-DEP\n", encoding="utf-8")
    idx.write_text(text, encoding="utf-8")
    rows = [l.split("\t") for l in _auto_build_step1(repo) if l.startswith("FEAT-")]
    assert [(r[0], r[4]) for r in rows] == [
        ("FEAT-UNB", "inflight=unknown"), ("FEAT-CLEAR", "inflight=none"),
        ("FEAT-POSS", "inflight=possible")], rows
