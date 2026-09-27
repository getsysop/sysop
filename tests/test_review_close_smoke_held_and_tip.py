"""Phase 330 — `/review-close` Step 3c reads the text that is merging, and stops re-asking a
held doc's answered procedure (`Q-568`, `Q-528`), plus the answer recorder its step 4 runs.

Both heredocs are extracted from `core/skills/review-close/SKILL.md` and executed, because
the defects were in what they read, not in what the prose says:

* `Q-568` (upstream #708): source 3 read a task body out of the WORKING TREE. Step 3c runs
  before any merge, so `HEAD` is the default branch and the operator was shown the procedure
  the branch was retiring. The body is now read at the approved branch's tip, and every
  signal names what it was read from (`READ:`).
* `Q-528` (#704 via source 3, #605 via source 1): a doc Step 4c 1c holds back on an
  outstanding `user_action` stays in main's pending-docs across closes. It links no task now
  (its work is not merging here), and its own headings still signal, so ISSUE-0095 stays
  closed. An answer the human gave to one of its sections is recorded in the doc and reported
  instead of asked again, until the section text changes. A waiver is never recorded.

Fixtures that need a branch tip are real git repos with a local-only history; no remote is
ever configured.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_review_close_smoke_gate import (  # noqa: E402
    SKILL, SMOKE_SRC, _run, _signals, _sources,
)


def _extract_recorder() -> str:
    text = SKILL.read_text(encoding="utf-8")
    m = re.search(
        r'python3 - "<the doc the KEY line names>" "<the KEY\'s 16 hex>" "<confirmed \| unrunnable>" <<\'EOF\'\n',
        text,
    )
    assert m, "could not locate Step 3c's answer-recorder heredoc"
    return text[m.end():text.index("\nEOF\n", m.end())]


RECORDER_SRC = _extract_recorder()
_ENV = {k: v for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                       env=_ENV, timeout=30)
    assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r.stdout.strip()


def _record(repo: Path, doc: str, key: str, decision: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", RECORDER_SRC, doc, key, decision],
                          capture_output=True, text=True, cwd=str(repo), timeout=30)


def _field(out: str, name: str) -> list[str]:
    return [ln[len(name) + 2:] for ln in out.splitlines() if ln.startswith(name + ": ")]


def _keys(out: str) -> list[str]:
    """The 16-hex values of the KEY lines (each reads `<hex> (record in <doc>)`)."""
    return [k.split()[0] for k in _field(out, "KEY")]


def _index(*tasks: str) -> str:
    return "schema_version: 1\ntasks:\n" + "".join(tasks)


def _task(tid: str, *, smoke=True, user_action=None, body=None) -> str:
    out = f"  - id: {tid}\n    status: in_progress\n    body: {body or f'open/{tid}.md'}\n"
    if smoke:
        out += "    manual_smoke: true\n"
    if user_action is not None:
        out += f"    user_action: {user_action}\n"
    return out


def _tree(tmp_path: Path, *, index: str, bodies=None, pending=None, locks=None,
          git: bool = True) -> Path:
    """A main checkout. A git repo on `main` by default, because the gate's "not merging"
    test needs the branch HEAD is on; with HEAD unresolved it treats every doc as merging."""
    main = tmp_path / "main"
    (main / "tasks" / "open").mkdir(parents=True)
    (main / "tasks" / "index.yml").write_text(index, encoding="utf-8")
    (main / "sysop/runtime/pending-docs").mkdir(parents=True)
    for name, body in (bodies or {}).items():
        (main / "tasks/open" / name).write_text(body, encoding="utf-8")
    for name, body in (pending or {}).items():
        (main / "sysop/runtime/pending-docs" / name).write_text(body, encoding="utf-8")
    if locks:
        (main / "sysop/runtime/locks").mkdir(parents=True)
        for name, body in locks.items():
            (main / "sysop/runtime/locks" / name).write_text(body, encoding="utf-8")
    if git:
        _init(main)
    return main


def _init(repo: Path) -> None:
    (repo / ".gitignore").write_text("sysop/runtime/\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")


def _git_tree(tmp_path: Path, *, main_body: str, branch_body: str | None, **kw) -> Path:
    """A git repo whose `main` carries `main_body` for FEAT-X and whose `feat/x` carries
    `branch_body` (or deletes the file when None). Runtime dirs stay untracked."""
    repo = _tree(tmp_path, bodies={"FEAT-X.md": main_body}, **kw)
    _git(repo, "checkout", "-q", "-b", "feat/x")
    body = repo / "tasks/open/FEAT-X.md"
    if branch_body is None:
        body.unlink()
    else:
        body.write_text(branch_body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "retire the stale procedure")
    _git(repo, "checkout", "-q", "main")
    return repo


OLD = "# X\n\n## Manual smoke required\n1. Run against schedule row 17627 (STALE).\n"
NEW = "# X\n\n## Manual smoke required\n1. Read-only Cloud Logging route (CURRENT).\n"
LOCK = "task_id: FEAT-X\nstatus: in_progress\nagent: a\nbranch: feat/x\nmode: worktree\n"


# ── Q-568: the body is read at the branch tip, and the signal says so ──

def test_a_lock_linked_body_is_read_at_the_branch_tip_not_the_working_tree(tmp_path):
    """The #708 reproduction: the branch rewrote its own smoke section. The working tree
    (main) still holds the retired text, and the gate must show the branch's."""
    repo = _git_tree(tmp_path, main_body=OLD, branch_body=NEW,
                     index=_index(_task("FEAT-X")), locks={"FEAT-X.lock": LOCK})
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1, out
    assert "CURRENT" in out and "STALE" not in out, out
    tip = _git(repo, "rev-parse", "feat/x")[:12]
    assert _field(out, "READ") == [f"feat/x@{tip} — the branch tip, the text that is merging"], out


def test_a_doc_linked_body_on_an_approved_branch_is_read_at_its_tip(tmp_path):
    """Linkage source 1 (a pending doc's roadmap_ids) names the branch in its own
    `branch:`; when that branch is approved this run, the tip is the revision."""
    doc = "---\nbranch: feat/x\nroadmap_ids: [FEAT-X]\n---\n# Summary\n"
    repo = _git_tree(tmp_path, main_body=OLD, branch_body=NEW,
                     index=_index(_task("FEAT-X")), pending={"feat-x.md": doc})
    out = _run(repo, [], branches=["feat/x"])
    assert "CURRENT" in out and "STALE" not in out, out


def test_a_task_no_approved_branch_claims_is_read_from_the_working_tree_and_says_so(tmp_path):
    doc = "---\nbranch: feat/x\nroadmap_ids: [FEAT-X]\n---\n# Summary\n"
    repo = _git_tree(tmp_path, main_body=OLD, branch_body=NEW,
                     index=_index(_task("FEAT-X")), pending={"feat-x.md": doc})
    out = _run(repo, [], branches=[])
    assert "STALE" in out, out
    (read,) = _field(out, "READ")
    assert read.startswith("working tree (main@"), read
    assert "no approved branch in this run claims this task" in read, read


def test_a_failed_tip_read_falls_back_loudly_never_silently(tmp_path):
    """The body is gone at the tip. The working-tree text is still shown, because the
    declaration is the ask, but the label must say it may not be what is merging."""
    repo = _git_tree(tmp_path, main_body=OLD, branch_body=None,
                     index=_index(_task("FEAT-X")), locks={"FEAT-X.lock": LOCK})
    out = _run(repo, [], branches=["feat/x"])
    (read,) = _field(out, "READ")
    assert "could NOT be read at `feat/x`" in read, read
    assert "may not be the text that is merging" in read, read


def test_an_unreadable_body_names_what_was_not_found(tmp_path):
    main = _tree(tmp_path, index=_index(_task("FEAT-X", body="open/GONE.md")),
                 pending={"a.md": "---\nbranch: feat/x\nroadmap_ids: [FEAT-X]\n---\n# S\n"})
    out = _run(main, [])
    assert _field(out, "READ") == ["nothing — `tasks/open/GONE.md` not found"], out


def test_every_signal_names_what_it_was_read_from(tmp_path):
    main = _tree(tmp_path, index=_index(),
                 pending={"a.md": "---\nbranch: feat/a\n---\n# S\n\n## Manual smoke required\n1. Go.\n"})
    wt = tmp_path / "wt"
    (wt / "sysop/runtime/pending-docs").mkdir(parents=True)
    (wt / "sysop/runtime/pending-docs/b.md").write_text(
        "---\nbranch: feat/b\n---\n# S\n\n## Operator action\n1. Go.\n", encoding="utf-8")
    out = _run(main, [wt])
    reads = _field(out, "READ")
    assert _signals(out) == 2 == len(reads), out
    assert "main checkout's sysop/runtime/pending-docs/, read in place" in reads, reads
    assert any(r.startswith("workspace of ") and r.endswith("read in place") for r in reads), reads


# ── Q-528: the held doc ──

HELD_DOC = ("---\nbranch: feat/old\nroadmap_ids: [FEAT-H]\n---\n# Summary\n\n"
            "## /review-close prerequisites — read before merging\n"
            "**DONE 2026-09-09** — migration 194 applied.\n")
HELD_IDX = _index(_task("FEAT-H", user_action="true"))


def test_a_held_doc_links_no_task_and_says_so(tmp_path):
    """#704: the held doc's task merged in an earlier close. Its body's procedure is not
    asked; the gate prints why, so a skipped procedure is never a silent one."""
    doc = "---\nbranch: feat/old\nroadmap_ids: [FEAT-H]\n---\n# Summary\n"
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": doc},
                 bodies={"FEAT-H.md": "# H\n\n## Manual smoke required\n1. Console step.\n"})
    out = _run(main, [], branches=["feat/new"])
    assert _signals(out) == 0, out
    assert out.splitlines()[0] == "NO_SMOKE_REQUIRED"
    assert out.splitlines()[1] == (
        "NOT IN THIS RUN: tasks/index.yml § FEAT-H — linked only by held doc "
        "sysop/runtime/pending-docs/old.md, so its body's procedure is not asked"), out


def test_a_held_docs_own_heading_still_signals_with_its_key(tmp_path):
    """The ISSUE-0095 bound: never skip a held doc wholesale. Its heading is asked, and the
    prompt shows that it is held."""
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": HELD_DOC})
    out = _run(main, [], branches=[])
    assert _signals(out) == 1, out
    assert _sources(out) == ["sysop/runtime/pending-docs/old.md"], out
    (held,) = _field(out, "NOT MERGING")
    assert held.startswith("held by Step 4c 1c (user_action outstanding: FEAT-H)"), held
    (key,) = _keys(out)
    assert re.fullmatch(r"[0-9a-f]{16}", key), key
    assert _field(out, "KEY") == [f"{key} (record in sysop/runtime/pending-docs/old.md)"], out
    assert _field(out, "READ") == ["main checkout's sysop/runtime/pending-docs/, read in place"], out


def test_a_held_docs_merged_branch_is_named_as_merged(tmp_path):
    repo = _git_tree(tmp_path, main_body=OLD, branch_body=NEW, index=HELD_IDX,
                     pending={"old.md": HELD_DOC.replace("feat/old", "feat/x")})
    _git(repo, "merge", "-q", "--ff-only", "feat/x")
    out = _run(repo, [], branches=[])
    (held,) = _field(out, "NOT MERGING")
    assert held.endswith("branch `feat/x` is already in HEAD"), held


def test_an_approved_branch_is_never_held(tmp_path):
    """A doc whose branch is merging this run is this run's doc, whatever its task's
    user_action says: it links its task and carries no KEY."""
    main = _tree(tmp_path, index=HELD_IDX,
                 pending={"old.md": HELD_DOC.replace("feat/old", "feat/x")},
                 bodies={"FEAT-H.md": "# H\n\n## Manual smoke required\n1. Go.\n"})
    out = _run(main, [], branches=["feat/x"])
    assert _field(out, "NOT MERGING") == [], out
    assert "tasks/index.yml § FEAT-H" in _sources(out), out


def test_a_held_link_does_not_hide_a_lock_on_an_approved_branch(tmp_path):
    """A task a held doc names can be re-claimed on a branch in this run; the lock wins."""
    doc = "---\nbranch: feat/old\nroadmap_ids: [FEAT-H]\n---\n# Summary\n"
    lock = LOCK.replace("FEAT-X", "FEAT-H")
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": doc}, locks={"FEAT-H.lock": lock},
                 bodies={"FEAT-H.md": "# H\n\n## Manual smoke required\n1. Go.\n"})
    out = _run(main, [], branches=["feat/x"])
    assert _sources(out) == ["tasks/index.yml § FEAT-H"], out
    assert "NOT IN THIS RUN" not in out, out


@pytest.mark.parametrize("value, held", [("true", True), ("false", False), ("'no'", True), ("0", False)])
def test_held_uses_step_4c_1cs_python_truthiness(tmp_path, value, held):
    """1c holds on `if t.get('user_action')`. The gate must agree with it exactly, including
    the malformed string `'no'`, which is truthy there."""
    main = _tree(tmp_path, index=_index(_task("FEAT-H", user_action=value)),
                 pending={"old.md": HELD_DOC})
    out = _run(main, [], branches=[])
    notes = _field(out, "NOT MERGING")
    assert notes and any(n.startswith("held by Step 4c 1c") for n in notes) is held, out


def test_a_worktree_copy_is_never_held(tmp_path):
    """Only a doc in MAIN's pending-docs is held by 1c; a worktree copy is authoring."""
    main = _tree(tmp_path, index=HELD_IDX)
    wt = tmp_path / "wt"
    (wt / "sysop/runtime/pending-docs").mkdir(parents=True)
    (wt / "sysop/runtime/pending-docs/old.md").write_text(HELD_DOC, encoding="utf-8")
    out = _run(main, [wt], branches=[])
    assert "sysop/runtime/pending-docs/old.md" not in _sources(out), out
    assert _field(out, "NOT MERGING") == [], out
    assert "read before merging" in out, out


# ── the recorded answer, end to end ──

def _held_key(main: Path) -> str:
    out = _run(main, [], branches=[])
    (key,) = [k.split()[0] for k in _field(out, "KEY")
              if k.endswith("(record in sysop/runtime/pending-docs/old.md)")
              and "read before merging" in out]
    return key


@pytest.mark.parametrize("decision", ["confirmed", "unrunnable"])
def test_an_answer_recorded_by_step_4_is_reported_not_asked_next_close(tmp_path, decision):
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": HELD_DOC})
    key = _held_key(main)
    r = _record(main, "sysop/runtime/pending-docs/old.md", key, decision)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"RECORDED: old.md — {decision} for key {key}"
    out = _run(main, [], branches=[])
    assert _signals(out) == 0, out
    assert out.splitlines()[1].startswith(
        f"PREVIOUSLY ANSWERED: sysop/runtime/pending-docs/old.md — {decision} on "), out
    assert (f"(key {key}, recorded in sysop/runtime/pending-docs/old.md): "
            "## /review-close prerequisites — read before merging") in out


def test_editing_the_answered_section_asks_again(tmp_path):
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": HELD_DOC})
    key = _held_key(main)
    assert _record(main, "sysop/runtime/pending-docs/old.md", key, "confirmed").returncode == 0
    doc = main / "sysop/runtime/pending-docs/old.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace("migration 194", "migration 195"),
                   encoding="utf-8")
    out = _run(main, [], branches=[])
    assert _signals(out) == 1 and _keys(out) != [key], out


def test_a_recorded_waiver_never_suppresses(tmp_path):
    """The recorder refuses a waiver; a hand-written one is ignored by the gate."""
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": HELD_DOC})
    key = _held_key(main)
    doc = main / "sysop/runtime/pending-docs/old.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace(
        "roadmap_ids: [FEAT-H]\n",
        f"roadmap_ids: [FEAT-H]\nsmoke_answers:\n- section: {key}\n  decision: waived\n"),
        encoding="utf-8")
    assert _signals(_run(main, [], branches=[])) == 1


def test_an_answer_in_a_doc_that_is_not_held_is_ignored(tmp_path):
    """Only a held doc's answer carries across closes. A doc merging now is asked now."""
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": HELD_DOC})
    key = _held_key(main)
    assert _record(main, "sysop/runtime/pending-docs/old.md", key, "confirmed").returncode == 0
    out = _run(main, [], branches=["feat/old"])   # its branch is approved: not held
    assert "sysop/runtime/pending-docs/old.md" in _sources(out), out
    assert "PREVIOUSLY ANSWERED" not in out, out


# ── the recorder's own contract ──

def test_the_recorder_keeps_every_other_frontmatter_line_byte_for_byte(tmp_path):
    fm = ("---\nbranch: feat/old   # a comment the recorder must keep\n"
          "roadmap_ids: [FEAT-H]\ndate: 2026-09-09\nsummary: \"x: y\"\n---\n")
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": fm + HELD_DOC.split("---\n", 2)[2]})
    key = _held_key(main)
    assert _record(main, "sysop/runtime/pending-docs/old.md", key, "confirmed").returncode == 0
    after = (main / "sysop/runtime/pending-docs/old.md").read_text(encoding="utf-8")
    assert after.startswith("---\nsmoke_answers:\n"), after
    assert after.endswith(fm[len("---\n"):] + HELD_DOC.split("---\n", 2)[2]), after
    assert after.count("smoke_answers:") == 1
    assert [p.name for p in (main / "sysop/runtime/pending-docs").iterdir()] == ["old.md"]


def test_recording_the_same_key_twice_replaces_and_a_new_key_appends(tmp_path):
    import yaml
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": HELD_DOC})
    doc = "sysop/runtime/pending-docs/old.md"
    assert _record(main, doc, "a" * 16, "confirmed").returncode == 0
    assert _record(main, doc, "a" * 16, "unrunnable").returncode == 0
    assert _record(main, doc, "b" * 16, "confirmed").returncode == 0
    text = (main / doc).read_text(encoding="utf-8")
    fm = yaml.safe_load(text.split("---\n")[1])
    assert [(a["section"], a["decision"]) for a in fm["smoke_answers"]] == [
        ("a" * 16, "unrunnable"), ("b" * 16, "confirmed")]
    assert fm["branch"] == "feat/old" and fm["roadmap_ids"] == ["FEAT-H"]


def test_a_flow_style_answers_list_is_replaced_whole(tmp_path):
    import yaml
    doc_text = HELD_DOC.replace("roadmap_ids: [FEAT-H]\n",
                                "smoke_answers: [{section: " + "c" * 16 + ", decision: confirmed}]\n"
                                "roadmap_ids: [FEAT-H]\n")
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": doc_text})
    assert _record(main, "sysop/runtime/pending-docs/old.md", "d" * 16, "confirmed").returncode == 0
    fm = yaml.safe_load((main / "sysop/runtime/pending-docs/old.md").read_text().split("---\n")[1])
    assert [a["section"] for a in fm["smoke_answers"]] == ["c" * 16, "d" * 16]
    assert fm["roadmap_ids"] == ["FEAT-H"]


@pytest.mark.parametrize("doc, key, decision, why", [
    ("sysop/runtime/pending-docs/old.md", "a" * 16, "waived", "never a waiver"),
    ("sysop/runtime/pending-docs/old.md", "a" * 16, "skip", "never a waiver"),
    ("sysop/runtime/pending-docs/old.md", "not-a-key", "confirmed", "16-hex"),
    ("sysop/runtime/pending-docs/../old.md", "a" * 16, "confirmed", "pending-docs/ directory"),
    ("tasks/open/FEAT-H.md", "a" * 16, "confirmed", "pending-docs/ directory"),
    ("sysop/runtime/pending-docs/gone.md", "a" * 16, "confirmed", "pending-docs/ directory"),
    ("sysop/runtime/pending-docs/nofm.md", "a" * 16, "confirmed", "no frontmatter mapping"),
    ("sysop/runtime/pending-docs/badlist.md", "a" * 16, "confirmed", "is not a list"),
])
def test_the_recorder_refuses_and_writes_nothing(tmp_path, doc, key, decision, why):
    main = _tree(tmp_path, index=HELD_IDX, pending={
        "old.md": HELD_DOC, "nofm.md": "# no frontmatter\n",
        "badlist.md": HELD_DOC.replace("roadmap_ids", "smoke_answers: yes\nroadmap_ids")},
        bodies={"FEAT-H.md": "---\nx: 1\n---\n"})
    (main / "old.md").write_text("---\nx: 1\n---\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in main.rglob("*") if p.is_file() and ".git" not in p.parts}
    r = _record(main, doc, key, decision)
    assert r.returncode != 0 and "REFUSING" in r.stderr and why in r.stderr, r.stderr
    after = {p: p.read_bytes() for p in main.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert after == before


def test_the_recorder_refuses_a_rewrite_that_would_change_another_key(tmp_path):
    """The block removal is line-based. A column-0 `smoke_answers:` that is really the
    continuation of another key's quoted scalar would be cut out of that value; the
    re-parse check must refuse rather than write the damage (or crash on it)."""
    doc_text = HELD_DOC.replace("roadmap_ids: [FEAT-H]\n",
                                'roadmap_ids: [FEAT-H]\nsummary: "first\nsmoke_answers: inner"\n')
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": doc_text})
    before = (main / "sysop/runtime/pending-docs/old.md").read_bytes()
    r = _record(main, "sysop/runtime/pending-docs/old.md", "a" * 16, "confirmed")
    assert r.returncode != 0 and "REFUSING: rewriting old.md would change another" in r.stderr, r.stderr
    assert (main / "sysop/runtime/pending-docs/old.md").read_bytes() == before
    assert [p.name for p in (main / "sysop/runtime/pending-docs").iterdir()] == ["old.md"]


def test_the_recorder_refuses_unparseable_frontmatter_without_a_traceback(tmp_path):
    main = _tree(tmp_path, index=HELD_IDX,
                 pending={"old.md": "---\nbranch: [unclosed\n---\n# S\n"})
    r = _record(main, "sysop/runtime/pending-docs/old.md", "a" * 16, "confirmed")
    assert r.returncode != 0 and "REFUSING" in r.stderr and "Traceback" not in r.stderr, r.stderr


def test_the_token_inside_another_keys_block_scalar_is_left_alone(tmp_path):
    """Rule 4's 'what else matches this': an indented `smoke_answers:` inside a block
    scalar is prose in another key, not the key. The removal is column-0 only."""
    import yaml
    doc_text = HELD_DOC.replace("roadmap_ids: [FEAT-H]\n",
                                "roadmap_ids: [FEAT-H]\nsummary: |\n  smoke_answers: prose\n  more\n")
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": doc_text})
    assert _record(main, "sysop/runtime/pending-docs/old.md", "a" * 16, "confirmed").returncode == 0
    fm = yaml.safe_load((main / "sysop/runtime/pending-docs/old.md").read_text().split("---\n")[1])
    assert fm["summary"] == "smoke_answers: prose\nmore\n", fm
    assert [a["section"] for a in fm["smoke_answers"]] == ["a" * 16]


def test_an_unterminated_frontmatter_is_refused(tmp_path):
    """Rule 4's 'what happens when the construct never closes'."""
    main = _tree(tmp_path, index=HELD_IDX,
                 pending={"old.md": "---\nbranch: feat/old\nroadmap_ids: [FEAT-H]\n# no closer\n"})
    before = (main / "sysop/runtime/pending-docs/old.md").read_bytes()
    r = _record(main, "sysop/runtime/pending-docs/old.md", "a" * 16, "confirmed")
    assert r.returncode != 0 and "no frontmatter mapping" in r.stderr, r.stderr
    assert (main / "sysop/runtime/pending-docs/old.md").read_bytes() == before


def test_a_rewrite_that_parses_but_changes_another_key_is_refused(tmp_path):
    """The re-parse check is the recorder's only defence against a line-based removal that
    yields VALID yaml with a different value: here the removed line is a member of another
    key's multi-line flow mapping. A parse-error check alone would write the damage."""
    doc_text = HELD_DOC.replace("roadmap_ids: [FEAT-H]\n",
                                "roadmap_ids: [FEAT-H]\nextra: {a: 1,\nsmoke_answers: 2,\nb: 3}\n")
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": doc_text})
    before = (main / "sysop/runtime/pending-docs/old.md").read_bytes()
    r = _record(main, "sysop/runtime/pending-docs/old.md", "a" * 16, "confirmed")
    assert r.returncode != 0 and "would change another frontmatter key" in r.stderr, r.stderr
    assert (main / "sysop/runtime/pending-docs/old.md").read_bytes() == before


def test_a_failed_write_leaves_the_doc_and_no_temp_file(tmp_path):
    """`os.replace` failing mid-record must leave the doc byte-identical and remove the
    temp file, which sits in the directory every `*.md` reader globs."""
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": HELD_DOC})
    before = (main / "sysop/runtime/pending-docs/old.md").read_bytes()
    boom = ("import os\n"
            "def _boom(*a, **k):\n    raise OSError('simulated replace failure')\n"
            "os.replace = _boom\n")
    r = subprocess.run([sys.executable, "-c", boom + RECORDER_SRC,
                        "sysop/runtime/pending-docs/old.md", "a" * 16, "confirmed"],
                       capture_output=True, text=True, cwd=str(main), timeout=30)
    assert r.returncode != 0 and "simulated replace failure" in r.stderr, r.stderr
    assert (main / "sysop/runtime/pending-docs/old.md").read_bytes() == before
    assert [p.name for p in (main / "sysop/runtime/pending-docs").iterdir()] == ["old.md"]


def test_info_lines_come_before_the_first_signal_block(tmp_path):
    """Step 2 parses blocks from `---SIGNAL---` to the next one, so an info line printed
    after the signals would be read as part of the last signal's procedure."""
    other = "---\nbranch: feat/new\n---\n# S\n\n## Manual smoke required\n1. Go.\n"
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": HELD_DOC, "new.md": other},
                 bodies={"FEAT-H.md": "# H\n\n## Manual smoke required\n1. Console.\n"})
    key = _held_key(main)
    assert _record(main, "sysop/runtime/pending-docs/old.md", key, "confirmed").returncode == 0
    lines = _run(main, [], branches=[]).splitlines()
    assert lines[0] == "SMOKE_REQUIRED: 1 signal(s)", lines
    first_block = lines.index("---SIGNAL---")
    info = [i for i, ln in enumerate(lines)
            if ln.startswith(("PREVIOUSLY ANSWERED:", "NOT IN THIS RUN:"))]
    assert len(info) == 2 and max(info) < first_block, lines


def test_a_lock_on_an_approved_branch_outranks_an_unapproved_doc_link(tmp_path):
    """Both linkage sources name the task: a doc whose branch is not in this run, and a lock
    on a branch that is. The body must be read at the approved branch's tip."""
    doc = "---\nbranch: feat/other\nroadmap_ids: [FEAT-X]\n---\n# Summary\n"
    repo = _git_tree(tmp_path, main_body=OLD, branch_body=NEW, index=_index(_task("FEAT-X")),
                     pending={"other.md": doc}, locks={"FEAT-X.lock": LOCK})
    out = _run(repo, [], branches=["feat/x"])
    assert "CURRENT" in out and "STALE" not in out, out


# ── Phase 330 round 1: what "not merging" must and must not cover ──

def test_a_default_branch_doc_is_never_held_its_work_lands_with_this_close(tmp_path):
    """Round 1's HIGH. A `branch: main` doc can never be approved, and its commits land with
    this close (`direct` pushes them; `pr` carries them). Treating it as held suppressed the
    smoke for code that was landing."""
    doc = HELD_DOC.replace("branch: feat/old", "branch: main")
    main = _tree(tmp_path, index=HELD_IDX, pending={"main.md": doc},
                 bodies={"FEAT-H.md": "# H\n\n## Manual smoke required\n1. Click it.\n"})
    out = _run(main, [], branches=[])
    assert _field(out, "NOT MERGING") == [] and "NOT IN THIS RUN" not in out, out
    assert "tasks/index.yml § FEAT-H" in _sources(out), out


def test_with_head_unresolved_nothing_is_treated_as_not_merging(tmp_path):
    """Fail closed: without the branch HEAD is on, a `branch: main` doc and a held doc
    cannot be told apart, so the gate asks about both."""
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": HELD_DOC},
                 bodies={"FEAT-H.md": "# H\n\n## Manual smoke required\n1. Go.\n"}, git=False)
    out = _run(main, [], branches=[])
    assert _field(out, "NOT MERGING") == [] and "NOT IN THIS RUN" not in out, out
    assert "tasks/index.yml § FEAT-H" in _sources(out), out


def test_an_answer_given_at_the_merging_close_carries_to_the_held_closes(tmp_path):
    """Round 1: the merging close reads the doc in its worktree, where it is not held. Its
    answer must be recorded THERE, travel with the doc (Step 3b's collect copies it to
    main), and be honoured by the first close that does not merge the branch."""
    main = _tree(tmp_path, index=HELD_IDX)
    wt = tmp_path / "wt"
    (wt / "sysop/runtime/pending-docs").mkdir(parents=True)
    wdoc = wt / "sysop/runtime/pending-docs/old.md"
    wdoc.write_text(HELD_DOC, encoding="utf-8")
    out = _run(main, [wt], branches=["feat/old"])          # the merging close
    assert _field(out, "NOT MERGING") == [], out
    entries = _field(out, "KEY")
    assert entries and all(k.endswith(f"(record in {wdoc})") for k in entries), out
    for entry in entries:
        r = _record(main, str(wdoc), entry.split()[0], "confirmed")
        assert r.returncode == 0, r.stderr
    (main / "sysop/runtime/pending-docs/old.md").write_bytes(wdoc.read_bytes())  # 3b's collect
    out = _run(main, [], branches=[])                        # the next close
    assert _signals(out) == 0 and "PREVIOUSLY ANSWERED" in out, out


def test_the_close_that_releases_the_doc_does_not_ask_again(tmp_path):
    """Round 1: once `user_action` is cleared the doc is no longer held, but its work still
    merged closes ago. Its answered heading AND its task's answered body procedure are
    reported, not asked, because the doc is still not merging."""
    body = "# H\n\n## Manual smoke required\n1. Console step.\n"
    held = _tree(tmp_path / "a", index=HELD_IDX, pending={"old.md": HELD_DOC},
                 bodies={"FEAT-H.md": body})
    released = _index(_task("FEAT-H", user_action="false"))
    main = _tree(tmp_path / "b", index=released, pending={"old.md": HELD_DOC},
                 bodies={"FEAT-H.md": body})
    first = _run(main, [], branches=[])
    assert _signals(first) == 2, first
    for entry in _field(first, "KEY"):
        assert entry.endswith("(record in sysop/runtime/pending-docs/old.md)"), entry
        assert _record(main, "sysop/runtime/pending-docs/old.md", entry.split()[0],
                       "confirmed").returncode == 0
    out = _run(main, [], branches=[])
    assert _signals(out) == 0, out
    assert sum(ln.startswith("PREVIOUSLY ANSWERED:") for ln in out.splitlines()) == 2, out
    assert _signals(_run(held, [], branches=[])) == 1


def test_a_clone_workspace_body_is_read_from_the_clone(tmp_path):
    """Round 1: a `--clone` workspace keeps its commits in its own object store; the local
    ref in main is the claim base. Reading there printed the stale text under a label
    claiming it was merging."""
    repo = _tree(tmp_path, index=_index(_task("FEAT-X")), bodies={"FEAT-X.md": OLD})
    _git(repo, "branch", "feat/x")                               # the claim base, as --clone leaves it
    clone = tmp_path / "main-FEAT-X"
    subprocess.run(["git", "clone", "-q", str(repo), str(clone)], check=True, env=_ENV)
    _git(clone, "checkout", "-q", "feat/x")
    _git(clone, "config", "user.email", "t@example.invalid")
    _git(clone, "config", "user.name", "t")
    (clone / "tasks/open/FEAT-X.md").write_text(NEW, encoding="utf-8")
    _git(clone, "commit", "-q", "-am", "re-baseline")
    lock = LOCK.replace("mode: worktree\n", f"mode: clone\nworkspace: {clone}\n")
    (repo / "sysop/runtime/locks").mkdir(parents=True)
    (repo / "sysop/runtime/locks/FEAT-X.lock").write_text(lock, encoding="utf-8")
    out = _run(repo, [], branches=["feat/x"])
    assert "CURRENT" in out and "STALE" not in out, out
    tip = _git(clone, "rev-parse", "feat/x")[:12]
    assert _field(out, "READ")[0].startswith(f"feat/x@{tip}"), out


def test_the_recorder_refuses_non_utf8_without_a_traceback(tmp_path):
    main = _tree(tmp_path, index=HELD_IDX)
    doc = main / "sysop/runtime/pending-docs/old.md"
    doc.write_bytes(b"---\nbranch: feat/old\ntitle: caf\xe9\n---\n## Manual smoke\nx\n")
    before = doc.read_bytes()
    r = _record(main, "sysop/runtime/pending-docs/old.md", "a" * 16, "confirmed")
    assert r.returncode != 0 and "not valid UTF-8" in r.stderr and "Traceback" not in r.stderr
    assert doc.read_bytes() == before


def test_the_recorder_keeps_a_blank_line_after_an_existing_block(tmp_path):
    doc_text = ("---\nsmoke_answers:\n- section: " + "c" * 16 + "\n  decision: confirmed\n"
                "\nbranch: feat/old\nroadmap_ids: [FEAT-H]\n---\n# S\n")
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": doc_text})
    assert _record(main, "sysop/runtime/pending-docs/old.md", "d" * 16, "confirmed").returncode == 0
    after = (main / "sysop/runtime/pending-docs/old.md").read_text()
    assert "\n\nbranch: feat/old\n" in after, after


# ── Phase 330 round 1, lens 2: behaviours no test exercised ──

def test_a_legacy_task_ids_held_doc_is_held_too(tmp_path):
    """Step 4c 1c reads `roadmap_ids`, falling back to `task_ids`; the gate must as well, or a
    legacy held doc links its task and re-asks its body on every close."""
    doc = HELD_DOC.replace("roadmap_ids: [FEAT-H]", "task_ids: [FEAT-H]")
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": doc},
                 bodies={"FEAT-H.md": "# H\n\n## Manual smoke required\n1. Console.\n"})
    out = _run(main, [], branches=[])
    assert "NOT IN THIS RUN: tasks/index.yml § FEAT-H" in out, out
    assert "tasks/index.yml § FEAT-H" not in _sources(out), out


def test_roadmap_ids_win_over_task_ids(tmp_path):
    """The shim is `roadmap_ids OR task_ids`: a doc carrying both is read by `roadmap_ids`."""
    doc = HELD_DOC.replace("roadmap_ids: [FEAT-H]", "roadmap_ids: [FEAT-X]\ntask_ids: [FEAT-H]")
    idx = _index(_task("FEAT-H", user_action="true"), _task("FEAT-X", smoke=False))
    main = _tree(tmp_path, index=idx, pending={"old.md": doc})
    (note,) = _field(_run(main, [], branches=[]), "NOT MERGING")
    assert note.startswith("not held"), note


def test_an_approved_doc_link_is_not_overwritten_by_a_later_unapproved_one(tmp_path):
    """Two docs name the task: `a.md` on the approved branch, `z.md` on another. The tip
    link must survive whichever sorts later."""
    a = "---\nbranch: feat/x\nroadmap_ids: [FEAT-X]\n---\n# S\n"
    z = "---\nbranch: feat/zzz\nroadmap_ids: [FEAT-X]\n---\n# S\n"
    repo = _git_tree(tmp_path, main_body=OLD, branch_body=NEW, index=_index(_task("FEAT-X")),
                     pending={"a.md": a, "z.md": z})
    out = _run(repo, [], branches=["feat/x"])
    assert "CURRENT" in out and "STALE" not in out, out


def test_an_answered_only_run_prints_no_smoke_required_exactly(tmp_path):
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": HELD_DOC})
    assert _record(main, "sysop/runtime/pending-docs/old.md", _held_key(main),
                   "confirmed").returncode == 0
    assert _run(main, [], branches=[]).splitlines()[0] == "NO_SMOKE_REQUIRED"


def test_a_frontmatter_only_declaration_in_a_not_merging_doc_carries_a_key(tmp_path):
    doc = "---\nbranch: feat/old\nroadmap_ids: [FEAT-H]\nmanual_smoke: true\n---\n# S\n"
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": doc})
    out = _run(main, [], branches=[])
    (key,) = _keys(out)
    assert _record(main, "sysop/runtime/pending-docs/old.md", key, "confirmed").returncode == 0
    assert _run(main, [], branches=[]).splitlines()[0] == "NO_SMOKE_REQUIRED"


def test_a_procedure_in_both_the_doc_and_the_body_is_asked_once(tmp_path):
    sec = "## Manual smoke required\n1. The same steps.\n"
    doc = "---\nbranch: feat/x\nroadmap_ids: [FEAT-X]\n---\n# S\n\n" + sec
    main = _tree(tmp_path, index=_index(_task("FEAT-X")), pending={"a.md": doc},
                 bodies={"FEAT-X.md": "# X\n\n" + sec})
    assert _signals(_run(main, [], branches=["feat/x"])) == 1


def test_the_not_merging_note_names_an_unmerged_or_unresolvable_branch(tmp_path):
    repo = _git_tree(tmp_path, main_body=OLD, branch_body=NEW, index=HELD_IDX,
                     pending={"x.md": HELD_DOC.replace("feat/old", "feat/x"),
                              "g.md": HELD_DOC.replace("feat/old", "feat/gone")})
    notes = _field(_run(repo, [], branches=[]), "NOT MERGING")
    assert any(n.endswith("branch `feat/x` has 1 commit(s) not in HEAD") for n in notes), notes
    assert any(n.endswith("branch `feat/gone` does not resolve here") for n in notes), notes


def test_an_inherited_git_dir_does_not_redirect_the_tip_read(tmp_path):
    """git exports GIT_DIR into hooks; left in place it outranks cwd and `-C`."""
    repo = _git_tree(tmp_path / "r", main_body=OLD, branch_body=NEW,
                     index=_index(_task("FEAT-X")), locks={"FEAT-X.lock": LOCK})
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    _git(decoy, "init", "-q")
    env = dict(os.environ, GIT_DIR=str(decoy / ".git"))
    r = subprocess.run([sys.executable, "-c", SMOKE_SRC, "", "feat/x"], capture_output=True,
                       text=True, cwd=str(repo), env=env, timeout=30)
    assert "CURRENT" in r.stdout and "STALE" not in r.stdout, r.stdout + r.stderr


def test_the_recorder_writes_its_temp_file_beside_the_doc_and_keeps_its_mode(tmp_path):
    """Same directory, so `os.replace` is an atomic rename; and the doc keeps its mode,
    which `mkstemp`'s 0600 would otherwise replace."""
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": HELD_DOC})
    doc = main / "sysop/runtime/pending-docs/old.md"
    doc.chmod(0o644)
    spy = ("import tempfile, os\n_mk = tempfile.mkstemp\n"
           "def _spy(*a, **k):\n"
           "    assert os.path.samefile(k['dir'], " + repr(str(doc.parent)) + "), k\n"
           "    return _mk(*a, **k)\ntempfile.mkstemp = _spy\n")
    r = subprocess.run([sys.executable, "-c", spy + RECORDER_SRC,
                        "sysop/runtime/pending-docs/old.md", "a" * 16, "confirmed"],
                       capture_output=True, text=True, cwd=str(main), timeout=30)
    assert r.returncode == 0, r.stderr
    assert oct(doc.stat().st_mode & 0o777) == oct(0o644)
    assert re.search(r"date: '\d{4}-\d{2}-\d{2}'", doc.read_text()), doc.read_text()


@pytest.mark.parametrize("key", ["a" * 15, "a" * 17, "A" * 16, "g" * 16])
def test_the_recorder_takes_exactly_sixteen_lowercase_hex(tmp_path, key):
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": HELD_DOC})
    r = _record(main, "sysop/runtime/pending-docs/old.md", key, "confirmed")
    assert r.returncode != 0 and "16-hex" in r.stderr, r.stderr


# ── Phase 330 round 2 ──

def test_an_answer_in_a_held_doc_never_silences_a_task_an_approved_branch_is_merging(tmp_path):
    """Round 2's HIGH. The task was held under `feat/old`, answered there, then released and
    re-claimed on `feat/x`, which is approved now. The held doc still names the task and sorts
    first, so it was chosen as the index signal's carrier and its answer silenced the ask for
    work that IS merging. A claimed task takes its carrier only from a merging doc."""
    body = "# X\n\n## Manual smoke required\n1. Console.\n"
    old = HELD_DOC.replace("FEAT-H", "FEAT-X")
    new = "---\nbranch: feat/x\nroadmap_ids: [FEAT-X]\n---\n# S\n"
    idx = _index(_task("FEAT-X", user_action="true"))
    main = _tree(tmp_path, index=idx, pending={"a-old.md": old, "z-new.md": new},
                 bodies={"FEAT-X.md": body}, locks={"FEAT-X.lock": LOCK})
    first = _run(main, [], branches=["feat/old"])  # feat/old's own merging close
    assert any(e.endswith("(record in sysop/runtime/pending-docs/a-old.md)")
               for e in _field(first, "KEY")), first
    for entry in _field(first, "KEY"):
        doc = entry.split("(record in ")[1].rstrip(")")
        assert _record(main, doc, entry.split()[0], "confirmed").returncode == 0
    out = _run(main, [], branches=["feat/x"])      # the close that merges the re-claim
    assert "tasks/index.yml § FEAT-X" in _sources(out), out
    assert "PREVIOUSLY ANSWERED: tasks/index.yml" not in out, out


def test_a_refs_heads_branch_spelling_is_the_same_branch(tmp_path):
    """`branch: refs/heads/feat/x` with `feat/x` approved is this run's doc, not a
    not-merging one (Step 4c's `rev-list` resolves either spelling)."""
    doc = HELD_DOC.replace("branch: feat/old", "branch: refs/heads/feat/x")
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": doc})
    out = _run(main, [], branches=["feat/x"])
    assert _field(out, "NOT MERGING") == [] and "PREVIOUSLY ANSWERED" not in out, out


def test_a_task_claimed_on_an_approved_branch_is_asked_even_if_its_only_doc_is_not_merging(tmp_path):
    """Round 2 (lens 5): the task's only pending doc is on another branch, and a lock claims
    it on an approved one. It is merging, so it gets no not-merging carrier, no NOT MERGING
    label, and no answer from that doc."""
    body = "# H\n\n## Manual smoke required\n1. Console.\n"
    for ua in ("true", "false"):
        base = tmp_path / ua
        main = _tree(base, index=_index(_task("FEAT-H", user_action=ua)),
                     pending={"old.md": HELD_DOC}, bodies={"FEAT-H.md": body},
                     locks={"FEAT-H.lock": LOCK.replace("FEAT-X", "FEAT-H")})
        doc = main / "sysop/runtime/pending-docs/old.md"
        doc.write_text(HELD_DOC.replace("roadmap_ids: [FEAT-H]\n",
                       f"roadmap_ids: [FEAT-H]\nsmoke_answers:\n- section: "
                       f"{_key_for(body)}\n  decision: confirmed\n"), encoding="utf-8")
        out = _run(main, [], branches=["feat/x"])
        blocks = out.split("---SIGNAL---")
        (idx_block,) = [b for b in blocks if "SOURCE: tasks/index.yml § FEAT-H" in b]
        assert "NOT MERGING" not in idx_block and "KEY:" not in idx_block, out
        assert "PREVIOUSLY ANSWERED: tasks/index.yml" not in out, out


def _key_for(body: str) -> str:
    import hashlib
    sec = body[body.index("## Manual smoke required"):].rstrip()
    return hashlib.sha256(sec.strip().encode("utf-8")).hexdigest()[:16]


def test_a_doc_with_no_branch_is_never_not_merging(tmp_path):
    doc = HELD_DOC.replace("branch: feat/old\n", "")
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": doc})
    out = _run(main, [], branches=[])
    assert _field(out, "NOT MERGING") == [] and "NOT IN THIS RUN" not in out, out


def test_a_detached_head_fails_closed(tmp_path):
    main = _tree(tmp_path, index=HELD_IDX, pending={"old.md": HELD_DOC})
    _git(main, "checkout", "-q", "--detach")
    out = _run(main, [], branches=[])
    assert _field(out, "NOT MERGING") == [], out


def test_the_recorder_refuses_a_pending_docs_dir_outside_sysop_runtime(tmp_path):
    main = _tree(tmp_path, index=HELD_IDX)
    stray = main / "other" / "pending-docs"
    stray.mkdir(parents=True)
    (stray / "old.md").write_text(HELD_DOC, encoding="utf-8")
    r = _record(main, "other/pending-docs/old.md", "a" * 16, "confirmed")
    assert r.returncode != 0 and "pending-docs/ directory" in r.stderr, r.stderr


def test_the_recorder_keeps_crlf_line_endings(tmp_path):
    main = _tree(tmp_path, index=HELD_IDX)
    doc = main / "sysop/runtime/pending-docs/old.md"
    doc.write_bytes(HELD_DOC.replace("\n", "\r\n").encode())
    assert _record(main, "sysop/runtime/pending-docs/old.md", "a" * 16, "confirmed").returncode == 0
    after = doc.read_bytes()
    assert after.count(b"\n") == after.count(b"\r\n") > 0, after
    assert after.endswith(HELD_DOC.split("---\n", 2)[2].replace("\n", "\r\n").encode())


def test_the_recorder_refuses_mixed_line_endings(tmp_path):
    main = _tree(tmp_path, index=HELD_IDX)
    doc = main / "sysop/runtime/pending-docs/old.md"
    doc.write_bytes(HELD_DOC.replace("\n", "\r\n", 2).encode())
    before = doc.read_bytes()
    r = _record(main, "sysop/runtime/pending-docs/old.md", "a" * 16, "confirmed")
    assert r.returncode != 0 and "mixes line endings" in r.stderr and doc.read_bytes() == before


def test_the_heredoc_source_is_the_one_under_test():
    """Guard the extraction: the recorder this module runs is the one step 4 prescribes."""
    assert "REFUSING" in RECORDER_SRC and "smoke_answers" in RECORDER_SRC
    assert "def emit(src, read, carrier, sec):" in SMOKE_SRC
