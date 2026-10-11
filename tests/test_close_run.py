"""`close_run.py` — the run directory behind `/review-close --prepare` / `--resume` (`Q-603`).

Each test drives the real script as a subprocess against a fixture: a main checkout on `main`
with a bare `origin`, a feature branch in a linked worktree carrying a pending doc, and a lock.
The staleness table it implements is `tools/UNATTENDED_CLOSE_SPEC.md` § 3.4, plus Wade's
2026-10-07 ruling that a branch merged or deleted between prepare and resume is dropped.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "core/companion/scripts/close_run.py"

_ENV = {k: v for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
_ENV.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")


def _g(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=_ENV)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd,
                          capture_output=True, text=True, env=_ENV)


def _commit(cwd: Path, name: str, text: str = "x\n", msg: str = "c") -> None:
    (cwd / name).write_text(text, encoding="utf-8")
    _g(cwd, "add", name)
    _g(cwd, "commit", "-qm", msg)


def _doc(branch: str, extra: str = "") -> str:
    return f'---\nbranch: "{branch}"\nroadmap_ids: [T-1]\nsummary: "s"\n{extra}---\n# body\n'


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
    (root / "CLAUDE.md").write_text("# p\n\n## Prevention Conventions\n- a rule\n", encoding="utf-8")
    _g(root, "add", "-A")
    _g(root, "commit", "-qm", "base")
    _g(root, "push", "-q", "origin", "main")
    _g(root, "fetch", "-q", "origin")
    wt = tmp_path / "wt-a"
    _g(root, "worktree", "add", "-q", "-b", "feat/a", str(wt))
    _commit(wt, "a.py", msg="a")
    (wt / "sysop/runtime/pending-docs").mkdir(parents=True)
    (wt / "sysop/runtime/pending-docs/feat-a.md").write_text(_doc("feat/a"), encoding="utf-8")
    _g(root, "branch", "feat/b")
    _commit(root, "main-only.txt", msg="main local")
    _g(root, "checkout", "-q", "feat/b")
    _commit(root, "b.py", msg="b")
    _g(root, "checkout", "-q", "main")
    locks = root / "sysop/runtime/locks"
    locks.mkdir(parents=True)
    (locks / "T-1.lock").write_text(f"task: T-1\nbranch: feat/a\nworkspace: {wt}\n", encoding="utf-8")
    return root


def _begin(root: Path, *branches: str) -> dict:
    r = _run(root, "begin", "main", *(branches or ("feat/a", "feat/b")))
    assert r.returncode == 0, r.stderr
    out = dict(line.split(": ", 1) for line in r.stdout.splitlines() if not line.startswith("STATE "))
    out["states"] = {line[6:].split(": ", 1)[0]: Path(line.split(": ", 1)[1])
                     for line in r.stdout.splitlines() if line.startswith("STATE ")}
    return out


def _finish(root: Path, run: dict, questions: str = "") -> subprocess.CompletedProcess:
    for p in run["states"].values():
        p.write_text("verdict: approve\n", encoding="utf-8")
    (Path(run["DIR"]) / "questions.md").write_text(questions, encoding="utf-8")
    r = _run(root, "finish", run["RUN"])
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def _check(root: Path, run: dict) -> list[str]:
    r = _run(root, "check", run["RUN"], "main")
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


def test_begin_creates_the_run_in_the_main_checkout(repo: Path, tmp_path: Path) -> None:
    run = _run(tmp_path / "wt-a", "begin", "main", "feat/a", "feat/b")
    assert run.returncode == 0, run.stderr
    lines = run.stdout.splitlines()
    run_id = lines[0].split(": ", 1)[1]
    d = repo / "sysop/runtime/close" / run_id
    assert lines[1] == f"DIR: {d}"
    assert f"STATE feat/a: {d / 'branches' / 'feat%2Fa.md'}" in lines
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert m["default_branch"] == "main" and set(m["branches"]) == {"feat/a", "feat/b"}
    assert m["branches"]["feat/a"]["doc"] and m["branches"]["feat/a"]["lock"]
    assert m["branches"]["feat/b"]["doc"] == "" and m["branches"]["feat/b"]["lock"] == ""


@pytest.mark.parametrize("args,code", [(("main", "nope"), 1), (("nope", "feat/a"), 1),
                                       (("main", "<branch>"), 1), (("<default branch>", "feat/a"), 3)])
def test_begin_refuses_an_unknown_ref(repo: Path, args, code: int) -> None:
    """An unsubstituted default branch is a usage error (3), as in the other scripts."""
    r = _run(repo, "begin", *args)
    assert r.returncode == code and r.stderr
    assert not (repo / "sysop/runtime/close").exists() or not any((repo / "sysop/runtime/close").iterdir())


def test_finish_refuses_a_branch_with_no_state(repo: Path) -> None:
    run = _begin(repo)
    run["states"]["feat/a"].write_text("verdict: approve\n", encoding="utf-8")
    (Path(run["DIR"]) / "questions.md").write_text("", encoding="utf-8")
    r = _run(repo, "finish", run["RUN"])
    assert r.returncode == 1 and "MISSING STATE feat/b:" in r.stdout
    assert "finished" not in json.loads((Path(run["DIR"]) / "manifest.json").read_text())
    assert _run(repo, "load", run["RUN"], "main").returncode == 2


def test_finish_refuses_without_questions_file(repo: Path) -> None:
    run = _begin(repo)
    for p in run["states"].values():
        p.write_text("verdict: approve\n", encoding="utf-8")
    r = _run(repo, "finish", run["RUN"])
    assert r.returncode == 1 and "questions.md" in r.stdout


def test_finish_counts_questions_and_copies_2b_files(repo: Path) -> None:
    (repo / "sysop/runtime/2b-conventions.md").write_text("conv\n", encoding="utf-8")
    run = _begin(repo)
    r = _finish(repo, run, "## Q1 · Step 2d · feat/a\nq\n\n## Q2 · Step 3c · close\nq\n")
    assert "QUESTIONS: 2" in r.stdout and "COPIED: 2b-conventions.md" in r.stdout
    assert (Path(run["DIR"]) / "2b/2b-conventions.md").read_text() == "conv\n"
    assert f"RESUME: /review-close --resume {run['RUN']}" in r.stdout


def test_nothing_moved_is_current(repo: Path) -> None:
    run = _begin(repo)
    _finish(repo, run)
    assert _check(repo, run) == ["CURRENT"]


def test_finish_records_origin_after_3c_fetch(repo: Path, tmp_path: Path) -> None:
    """3c fetches origin after `begin`; the resume compares against what 3c read."""
    run = _begin(repo)
    other = tmp_path / "other"
    _g(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
    _g(other, "config", "user.email", "t@t")
    _g(other, "config", "user.name", "t")
    _commit(other, "o.txt")
    _g(other, "push", "-q", "origin", "main")
    _g(repo, "fetch", "-q", "origin")
    _finish(repo, run)
    assert _check(repo, run) == ["CURRENT"]


def test_tip_lock_and_doc_moves_rerun_that_branch(repo: Path, tmp_path: Path) -> None:
    run = _begin(repo)
    _finish(repo, run)
    wt = tmp_path / "wt-a"
    _commit(wt, "a2.py")
    lock = repo / "sysop/runtime/locks/T-1.lock"
    lock.write_text(lock.read_text() + "notes: x\n", encoding="utf-8")
    doc = wt / "sysop/runtime/pending-docs/feat-a.md"
    doc.write_text(_doc("feat/a", "held_since: '2026-10-07'\n"), encoding="utf-8")
    assert _check(repo, run) == ["RERUN feat/a: tip, lock, doc moved"]


def test_doc_collected_into_main_counts_as_moved(repo: Path, tmp_path: Path) -> None:
    run = _begin(repo)
    _finish(repo, run)
    pd = repo / "sysop/runtime/pending-docs"
    pd.mkdir(parents=True)
    (pd / "feat-a-extra.md").write_text(_doc("feat/a"), encoding="utf-8")
    assert _check(repo, run) == ["RERUN feat/a: doc moved"]


def test_recording_a_smoke_answer_does_not_move_the_doc(repo: Path, tmp_path: Path) -> None:
    """The resume records Step 3c's answers (item 3) before `check` (item 5). The recorder writes
    a `smoke_answers:` block first in the frontmatter and keeps every other line, so that write
    must not re-run the branch from Step 2a; any other change to the doc still does."""
    run = _begin(repo)
    _finish(repo, run)
    doc = tmp_path / "wt-a/sysop/runtime/pending-docs/feat-a.md"
    doc.write_text(doc.read_text().replace(
        "---\n", "---\nsmoke_answers:\n- section: abcd\n  decision: confirmed\n  date: '2026-10-07'\n", 1),
        encoding="utf-8")
    assert _check(repo, run) == ["CURRENT"]
    doc.write_text(doc.read_text().replace('summary: "s"', 'summary: "t"'), encoding="utf-8")
    assert _check(repo, run) == ["RERUN feat/a: doc moved"]


def test_a_doc_for_another_branch_moves_nothing(repo: Path) -> None:
    run = _begin(repo)
    _finish(repo, run)
    pd = repo / "sysop/runtime/pending-docs"
    pd.mkdir(parents=True)
    (pd / "other.md").write_text(_doc("feat/zzz"), encoding="utf-8")
    assert _check(repo, run) == ["CURRENT"]


def test_branch_merged_since_prepare_is_gone(repo: Path) -> None:
    run = _begin(repo)
    _finish(repo, run)
    _g(repo, "merge", "-q", "--no-ff", "-m", "m", "feat/b")
    assert _check(repo, run) == ["GONE feat/b: merged in main", "RERUN 3: main moved"]


def test_branch_merged_and_deleted_is_gone_merged(repo: Path) -> None:
    run = _begin(repo)
    _finish(repo, run)
    _g(repo, "merge", "-q", "--no-ff", "-m", "m", "feat/b")
    _g(repo, "branch", "-q", "-d", "feat/b")
    assert "GONE feat/b: merged in main" in _check(repo, run)


def test_branch_deleted_unmerged_is_gone_deleted(repo: Path) -> None:
    run = _begin(repo)
    _finish(repo, run)
    _g(repo, "branch", "-q", "-D", "feat/b")
    assert _check(repo, run) == ["GONE feat/b: deleted"]


def test_branch_already_merged_at_prepare_is_not_gone(repo: Path) -> None:
    """A branch Step 2a step 0b saw as landed stays in the run; only a merge AFTER the
    prepare drops it."""
    _g(repo, "merge", "-q", "--no-ff", "-m", "m", "feat/b")
    run = _begin(repo)
    _finish(repo, run)
    assert _check(repo, run) == ["CURRENT"]


def test_default_branch_moves_rerun_step_3(repo: Path) -> None:
    run = _begin(repo)
    _finish(repo, run)
    _commit(repo, "late.txt")
    assert _check(repo, run) == ["RERUN 3: main moved"]


def test_conventions_change_reruns_2b(repo: Path) -> None:
    run = _begin(repo)
    _finish(repo, run)
    (repo / ".claude").mkdir()
    (repo / ".claude/convention_map.project.md").write_text("map\n", encoding="utf-8")
    (repo / "CLAUDE.md").write_text("# changed\n", encoding="utf-8")
    assert _check(repo, run) == ["RERUN 2b: CLAUDE.md changed",
                                 "RERUN 2b: .claude/convention_map.project.md changed"]


def test_recorded_pr_heads_change_reruns_all(repo: Path) -> None:
    run = _begin(repo)
    _finish(repo, run)
    _g(repo, "update-ref", "refs/sysop/merged-pr-heads/7", "feat/b")
    assert _check(repo, run) == ["RERUN ALL: recorded PR heads changed"]


def test_hooks_path_change_is_a_note_only(repo: Path) -> None:
    run = _begin(repo)
    _finish(repo, run)
    _g(repo, "config", "core.hooksPath", "hooks")
    assert _check(repo, run) == ["NOTE: core.hooksPath was (unset), is hooks", "CURRENT"]


@pytest.mark.parametrize("state", ["unfinished", "halted", "consumed", "other-default", "garbled"])
def test_load_and_check_refuse(repo: Path, state: str) -> None:
    run = _begin(repo)
    d = Path(run["DIR"])
    default = "main"
    if state != "unfinished":
        _finish(repo, run)
    if state == "halted":
        (d / "halted.md").write_text("Step 3 failed\n", encoding="utf-8")
    elif state == "consumed":
        assert _run(repo, "consume", run["RUN"]).returncode == 0
    elif state == "other-default":
        default = "master"
    elif state == "garbled":
        (d / "manifest.json").write_bytes(b"{\xff")
    for cmd in ("load", "check"):
        r = _run(repo, cmd, run["RUN"], default)
        assert r.returncode == 2 and r.stderr.startswith("REFUSED:"), (cmd, r.stdout, r.stderr)


def test_unknown_run_id_is_refused(repo: Path) -> None:
    assert _run(repo, "load", "20261007T000000Z-abcd", "main").returncode == 2
    assert _run(repo, "load", "../../etc", "main").returncode == 2


def test_load_counts_questions_and_answers(repo: Path) -> None:
    run = _begin(repo)
    _finish(repo, run, "## Q1 · Step 2d · feat/a\nq\n## Q2 · Step 3c · close\nq\n")
    (Path(run["DIR"]) / "answers.md").write_text("## Q1\nHold for fix\n", encoding="utf-8")
    r = _run(repo, "load", run["RUN"], "main")
    assert r.returncode == 0
    assert r.stdout.splitlines()[1:] == ["QUESTIONS: 2", "ANSWERED: 1"]


def test_consume_restores_2b_files_and_blocks_a_second_resume(repo: Path) -> None:
    rt = repo / "sysop/runtime"
    (rt / "2b-security.md").write_text("sec\n", encoding="utf-8")
    run = _begin(repo)
    _finish(repo, run)
    (rt / "2b-security.md").unlink()
    r = _run(repo, "consume", run["RUN"], "--restore-2b")
    assert r.returncode == 0 and (rt / "2b-security.md").read_text() == "sec\n"
    assert _run(repo, "consume", run["RUN"]).returncode == 2
    assert _run(repo, "check", run["RUN"], "main").returncode == 2


def test_consume_without_restore_leaves_runtime_alone(repo: Path) -> None:
    rt = repo / "sysop/runtime"
    (rt / "2b-security.md").write_text("old\n", encoding="utf-8")
    run = _begin(repo)
    _finish(repo, run)
    (rt / "2b-security.md").write_text("fresh\n", encoding="utf-8")
    assert _run(repo, "consume", run["RUN"]).returncode == 0
    assert (rt / "2b-security.md").read_text() == "fresh\n"


def test_a_frontmatter_that_does_not_parse_fails_loudly(repo: Path, tmp_path: Path) -> None:
    """Step 3c stops the close on a pending doc it cannot parse; so does the prepare."""
    (tmp_path / "wt-a/sysop/runtime/pending-docs/bad.md").write_text("---\nbranch: [\n---\n", encoding="utf-8")
    r = _run(repo, "begin", "main", "feat/a")
    assert r.returncode == 1 and "bad.md" in r.stderr


def test_begin_with_no_branch_opens_a_run(repo: Path) -> None:
    """A cycle of unpushed main commits only has no branch to name."""
    r = _run(repo, "begin", "main")
    assert r.returncode == 0, r.stderr
    run = {"RUN": r.stdout.splitlines()[0].split(": ", 1)[1], "DIR": r.stdout.splitlines()[1].split(": ", 1)[1],
           "states": {}}
    _finish(repo, run)
    assert _check(repo, run) == ["CURRENT"]


@pytest.mark.parametrize("args", [[], ["begin"], ["finish"], ["load", "x"], ["check", "x"],
                                  ["consume", "x", "--force"], ["frob", "x"]])
def test_usage_errors_exit_3(repo: Path, args) -> None:
    assert _run(repo, *args).returncode == 3


def test_a_worktree_doc_is_read_without_a_lock(repo: Path, tmp_path: Path) -> None:
    """The linked worktree is found from `git worktree list`, not only from a lock."""
    (repo / "sysop/runtime/locks/T-1.lock").unlink()
    run = _begin(repo)
    _finish(repo, run)
    doc = tmp_path / "wt-a/sysop/runtime/pending-docs/feat-a.md"
    doc.write_text(doc.read_text().replace('summary: "s"', 'summary: "t"'), encoding="utf-8")
    assert _check(repo, run) == ["RERUN feat/a: doc moved"]


def test_a_clone_workspace_doc_is_read_through_its_lock(repo: Path, tmp_path: Path) -> None:
    """A `--clone` workspace is not a linked worktree; only its lock's `workspace:` names it."""
    clone = tmp_path / "clone-b"
    (clone / "sysop/runtime/pending-docs").mkdir(parents=True)
    doc = clone / "sysop/runtime/pending-docs/feat-b.md"
    doc.write_text(_doc("feat/b"), encoding="utf-8")
    (repo / "sysop/runtime/locks/T-2.lock").write_text(
        f"task_id: T-2\nbranch: feat/b\nmode: clone\nworkspace: {clone}\n", encoding="utf-8")
    run = _begin(repo)
    _finish(repo, run)
    doc.write_text(doc.read_text().replace('summary: "s"', 'summary: "t"'), encoding="utf-8")
    assert _check(repo, run) == ["RERUN feat/b: doc moved"]


def test_a_locks_first_branch_line_wins(repo: Path) -> None:
    """As `claim_task.sh` reads it: a free-text `notes:` tail may carry a column-0 `branch:`."""
    lock = repo / "sysop/runtime/locks/T-1.lock"
    lock.write_text(lock.read_text() + "notes:\nbranch: feat/b\n", encoding="utf-8")
    run = _begin(repo)
    m = json.loads((Path(run["DIR"]) / "manifest.json").read_text())
    assert m["branches"]["feat/a"]["lock"] and m["branches"]["feat/b"]["lock"] == ""


def test_a_run_id_cannot_reach_outside_the_runs_directory(repo: Path) -> None:
    run = _begin(repo)
    _finish(repo, run)
    elsewhere = repo / "sysop/runtime/elsewhere"
    elsewhere.mkdir()
    (elsewhere / "manifest.json").write_bytes((Path(run["DIR"]) / "manifest.json").read_bytes())
    assert _run(repo, "load", "../elsewhere", "main").returncode == 2
    assert _run(repo, "check", "../elsewhere", "main").returncode == 2


@pytest.mark.parametrize("before,after,same", [
    # the recorder's own write: block first, every other line kept
    (b'---\nbranch: "a"\n---\nx\n', b'---\nsmoke_answers:\n- section: k\n  decision: confirmed\nbranch: "a"\n---\nx\n', True),
    # CRLF: the recorder preserves the doc's newline style
    (b'---\r\nbranch: "a"\r\n---\r\nx\r\n',
     b'---\r\nsmoke_answers:\r\n- section: k\r\n  decision: confirmed\r\nbranch: "a"\r\n---\r\nx\r\n', True),
    # a hand-placed block mid-frontmatter is dropped too
    (b'---\nbranch: "a"\nsummary: s\n---\n', b'---\nbranch: "a"\nsmoke_answers: []\nsummary: s\n---\n', True),
    # X10: a key after the block keeps its own list lines
    (b'---\nsmoke_answers: []\ntags:\n- a\n---\n', b'---\nsmoke_answers: []\ntags:\n- b\n---\n', False),
    # X11: a `---` rule in the body does not end the frontmatter later
    (b'---\nbranch: "a"\n---\nsmoke_answers: 1\n---\nend\n', b'---\nbranch: "a"\n---\nsmoke_answers: 2\n---\nend\n', False),
    # a lookalike key is not the block
    (b'---\nbranch: "a"\n---\n', b'---\nbranch: "a"\nsmoke_answers_note: x\n---\n', False),
    # the key in the BODY is content, not the recorder's write
    (b'---\nbranch: "a"\n---\nx\n', b'---\nbranch: "a"\n---\nsmoke_answers:\n- y\n', False),
    # a leading BOM, which the recorder accepts (round 1, record lens: the first cut skipped such
    # a doc entirely, so `check` printed CURRENT over an edited doc)
    (b'\xef\xbb\xbf---\nbranch: "a"\n---\n', b'\xef\xbb\xbf---\nsmoke_answers: []\nbranch: "a"\n---\n', True),
])
def test_the_smoke_answers_rule_on_hostile_docs(before: bytes, after: bytes, same: bool) -> None:
    sys.path.insert(0, str(SCRIPT.parent))
    import close_run
    assert (close_run.without_smoke_answers(before) == close_run.without_smoke_answers(after)) is same


@pytest.mark.parametrize("prefix,branch_line", [
    ("\ufeff", 'branch: "feat/a"'),            # a BOM, as the recorder accepts
    ("", 'branch: "feat/a" # a note'),          # an inline comment
    ("", "branch: 'feat/a'"),                   # single-quoted
    ("", "branch: feat/a"),                     # plain
])
def test_check_sees_every_branch_spelling(repo: Path, tmp_path: Path, prefix: str, branch_line: str) -> None:
    doc = tmp_path / "wt-a/sysop/runtime/pending-docs/feat-a.md"
    doc.write_text(prefix + _doc("feat/a").replace('branch: "feat/a"', branch_line), encoding="utf-8")
    (repo / "sysop/runtime/locks/T-1.lock").unlink()   # the doc alone must carry the link
    run = _begin(repo)
    assert json.loads((Path(run["DIR"]) / "manifest.json").read_text())["branches"]["feat/a"]["doc"]
    _finish(repo, run)
    doc.write_text(doc.read_text(encoding="utf-8").replace('summary: "s"', 'summary: "t"'), encoding="utf-8")
    assert _check(repo, run) == ["RERUN feat/a: doc moved"]


@pytest.mark.parametrize("line", [
    'branch: "feat/a\\"b"', "branch: 'it''s'", "branch: feat/b # c", 'branch: "feat/x "',
    "branch: other\nbranch: feat/x", "branch: >\n  feat/x", "branch: &a feat/x", "branch: !!str feat/x",
    "\"branch\": feat/x", "branch: fix/issue#7", "branch: refs/heads/feat/x", 'branch: "\\x41b"',
])
def test_a_docs_branch_is_read_exactly_as_pyyaml_reads_it(tmp_path: Path, line: str) -> None:
    """Round 2 (execution lens): a hand-rolled scan diverged from PyYAML, and a doc it misread was
    never hashed. Step 3c's `branch_of` is the oracle: PyYAML, stripped, `refs/heads/` dropped."""
    yaml = pytest.importorskip("yaml")
    sys.path.insert(0, str(SCRIPT.parent))
    import close_run
    d = tmp_path / "d.md"
    d.write_text(f"---\n{line}\nsummary: s\n---\n# body\n", encoding="utf-8")
    b = str(yaml.safe_load(f"{line}\nsummary: s\n").get("branch") or "").strip()
    assert close_run.doc_branch(d) == (b[len("refs/heads/"):] if b.startswith("refs/heads/") else b)


@pytest.mark.parametrize("damage", ['"tip": 123', '"tip": "a\\u0000b"'])
def test_a_wrong_typed_or_nul_branch_record_is_refused(repo: Path, damage: str) -> None:
    """Round 2: per-branch types and an embedded NUL reached git as a traceback."""
    run = _begin(repo)
    _finish(repo, run)
    mp = Path(run["DIR"]) / "manifest.json"
    m = json.loads(mp.read_text())
    m["branches"]["feat/a"]["tip"] = json.loads("{" + damage + "}")["tip"]
    mp.write_text(json.dumps(m), encoding="utf-8")
    for cmd in ("load", "check"):
        r = _run(repo, cmd, run["RUN"], "main")
        assert r.returncode == 2 and "Traceback" not in r.stderr, r.stderr


# ── round 1 (execution lens) survivors, closed ──────────────────────────────

def test_a_merged_tip_with_new_work_reruns_rather_than_going(repo: Path, tmp_path: Path) -> None:
    """X03: the old tip reached main, but the branch moved on: new unmerged work is not GONE."""
    run = _begin(repo)
    _finish(repo, run)
    _g(repo, "merge", "-q", "--no-ff", "-m", "m", "feat/b")
    _g(repo, "checkout", "-q", "feat/b")
    _commit(repo, "b2.py")
    _g(repo, "checkout", "-q", "main")
    assert "RERUN feat/b: tip moved" in _check(repo, run)


def test_a_tip_already_in_origin_at_begin_is_never_gone(repo: Path, tmp_path: Path) -> None:
    """X05: merged into origin before the prepare, local main behind; pulling later is not a
    merge since the prepare."""
    _g(repo, "push", "-q", "origin", "feat/b:main", "--force")
    _g(repo, "fetch", "-q", "origin")
    run = _begin(repo)
    _finish(repo, run)
    _g(repo, "reset", "-q", "--hard", "origin/main")
    assert not [l for l in _check(repo, run) if l.startswith("GONE")]


def test_a_branch_merged_in_origin_since_the_prepare_is_gone(repo: Path) -> None:
    """X06: merged on origin, local main still behind."""
    run = _begin(repo)
    _finish(repo, run)
    _g(repo, "push", "-q", "origin", "feat/b:main", "--force")
    _g(repo, "fetch", "-q", "origin")
    assert "GONE feat/b: merged in origin/main" in _check(repo, run)


def test_origin_moving_after_the_prepare_reruns_step_3(repo: Path, tmp_path: Path) -> None:
    """X16: the resume fetches before `check`, so origin's move is seen."""
    run = _begin(repo)
    _finish(repo, run)
    other = tmp_path / "other2"
    _g(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
    _g(other, "config", "user.email", "t@t")
    _g(other, "config", "user.name", "t")
    _commit(other, "o2.txt")
    _g(other, "push", "-q", "origin", "main")
    _g(repo, "fetch", "-q", "origin")
    assert _check(repo, run) == ["RERUN 3: origin/main moved"]


def test_finish_does_not_report_its_own_fetch(repo: Path, tmp_path: Path) -> None:
    """X07: Step 3c's fetch moving origin during the prepare is not a MOVED line."""
    run = _begin(repo)
    other = tmp_path / "other3"
    _g(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
    _g(other, "config", "user.email", "t@t")
    _g(other, "config", "user.name", "t")
    _commit(other, "o3.txt")
    _g(other, "push", "-q", "origin", "main")
    _g(repo, "fetch", "-q", "origin")
    assert "MOVED DURING PREPARE" not in _finish(repo, run).stdout


def test_a_doc_moved_from_the_worktree_to_main_counts_as_moved(repo: Path, tmp_path: Path) -> None:
    """X09: Step 3b's collect moves the same bytes to another path."""
    run = _begin(repo)
    _finish(repo, run)
    src = tmp_path / "wt-a/sysop/runtime/pending-docs/feat-a.md"
    dst = repo / "sysop/runtime/pending-docs/feat-a.md"
    dst.parent.mkdir(parents=True)
    dst.write_bytes(src.read_bytes())
    src.unlink()
    assert _check(repo, run) == ["RERUN feat/a: doc moved"]


def test_an_indented_branch_line_does_not_link_a_lock(repo: Path) -> None:
    """X12: `claim_task.sh` reads `^branch:`, column 0 only."""
    (repo / "sysop/runtime/locks/T-9.lock").write_text("task_id: T-9\nnotes:\n  branch: feat/b\n", encoding="utf-8")
    run = _begin(repo)
    assert json.loads((Path(run["DIR"]) / "manifest.json").read_text())["branches"]["feat/b"]["lock"] == ""


def test_only_question_headings_are_counted(repo: Path) -> None:
    """X17."""
    run = _begin(repo)
    r = _finish(repo, run, "## Q1 · Step 2d · feat/a\nq\n## Quiet notes\n## Q2x\n")
    assert "QUESTIONS: 1" in r.stdout


@pytest.mark.parametrize("damage", ['{"branches": {}}', '{"branches": {"x": 1}, "run": {}, "default_branch": "main", "finished": "t"}',
                                    '[]', '{"default_branch": "main", "branches": {}, "run": {"local": 1}, "finished": "t"}'])
def test_a_damaged_manifest_is_refused_not_a_traceback(repo: Path, damage: str) -> None:
    run = _begin(repo)
    _finish(repo, run)
    (Path(run["DIR"]) / "manifest.json").write_text(damage, encoding="utf-8")
    for cmd in ("load", "check"):
        r = _run(repo, cmd, run["RUN"], "main")
        assert r.returncode == 2 and r.stderr.startswith("REFUSED:") and "Traceback" not in r.stderr


def test_two_concurrent_consumes_cannot_both_succeed(repo: Path) -> None:
    run = _begin(repo)
    _finish(repo, run)
    procs = [subprocess.Popen([sys.executable, str(SCRIPT), "consume", run["RUN"]], cwd=repo, env=_ENV,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(8)]
    codes = sorted(p.wait() for p in procs)
    assert codes.count(0) == 1 and set(codes[1:]) == {2}, codes
