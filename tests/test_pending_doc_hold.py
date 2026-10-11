"""Phase 353 — a pending doc's own hold (`Q-625`), and the stamp Step 3c reads (`Q-610`(b)).

`/review-close` Step 4c 1c held a doc only while a named task's `user_action` was truthy. That
flag also means *a human must act before an agent can take this task*, and clearing it for that
reason released the close-path hold on unfinished work: three recurrences in one consumer
(upstream #781 leg (a)). Wade's ruling (2026-09-30): a dedicated `hold:` in the pending doc,
written by `/document-work`, cleared by an explicit command; 1c holds on `hold:` **or**
`user_action`; and 1c stamps `held_since:` into a doc it holds, which Step 3c reads so that a held
`branch: <default branch>` doc stops re-asking its answered sections.

Everything is executed: `pending_doc_hold.py` directly, Step 3c's heredoc through the harness
its own tests use, the commands the skills prescribe by running their fences, and `/sitrep`'s
landed arm through `run_survey`.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"
SCRIPTS = REPO / "core/companion/scripts"
CLOSE = REPO / "core/skills/review-close/SKILL.md"
DOCWORK = REPO / "core/skills/document-work/SKILL.md"
SCHEMA = REPO / "core/companion/tasks/schema.md"
WF = REPO / "core/companion/docs/WORKFLOW.md"
SCRIPT = SCRIPTS / "pending_doc_hold.py"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(TESTS))

import pending_doc_hold as pdh  # noqa: E402
import sitrep_survey as ss  # noqa: E402
from test_review_close_smoke_held_and_tip import (  # noqa: E402
    HELD_DOC, _field, _index, _keys, _record, _run, _signals, _sources, _task, _tree,
)
from test_squash_provenance import (  # noqa: E402,F401  (`squashed` is a fixture)
    _survey, _write_lock, record, squashed,
)

_ENV = {k: v for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}


def _g(root: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, env=_ENV)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def _repo(tmp_path: Path, index: str, docs: dict[str, str]) -> Path:
    """A main checkout on `main`, every branch a doc names created at HEAD: merged, so
    `--stamp` may stamp it. A test that needs an unmerged branch moves it on."""
    root = tmp_path / "repo"
    (root / "tasks").mkdir(parents=True)
    (root / "tasks/index.yml").write_text(index, encoding="utf-8")
    pd = root / "sysop/runtime/pending-docs"
    pd.mkdir(parents=True)
    for name, text in docs.items():
        (pd / name).write_text(text, encoding="utf-8")
    (root / ".gitignore").write_text("sysop/runtime/\n", encoding="utf-8")
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["add", "-A"], ["commit", "-qm", "base"]):
        _g(root, *args)
    for text in docs.values():
        m = re.search(r'^branch: "([^"]+)"', text, re.M)
        if m and m.group(1) != "main":
            subprocess.run(["git", "branch", m.group(1)], cwd=root, capture_output=True,
                           env=_ENV)
    return root


def _doc(branch="feat/a", ids="[T-1]", extra=""):
    return f'---\nbranch: "{branch}"\nroadmap_ids: {ids}\nsummary: "s"\n{extra}---\n# body\n'


def _ix(*entries: tuple[str, object]) -> str:
    out = "schema_version: 1\ntasks:\n"
    for tid, ua in entries:
        out += f"  - id: {tid}\n    status: in_progress\n"
        if ua is not None:
            out += f"    user_action: {ua}\n"
    return out


def _check(root, capsys, **kw):
    rc = pdh.check(root, **kw)
    return rc, capsys.readouterr().out


def _lines(out: str, tag: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln.startswith(tag + ":")]


# ─────────────────────────────────────────────────────────────────────────────
# `check`: the hold test
# ─────────────────────────────────────────────────────────────────────────────

def test_hold_alone_holds_a_doc_whose_flag_was_cleared(tmp_path, capsys):
    """The reported case: `user_action` was cleared for `/roadmap`'s reasons. The doc's own
    `hold:` still holds it."""
    root = _repo(tmp_path, _ix(("T-1", "false")),
                 {"a.md": _doc(extra='hold: "staging rollout not done"\n')})
    rc, out = _check(root, capsys)
    assert rc == 0
    assert _lines(out, "HELD") == [
        "HELD: a.md — branch feat/a; hold: staging rollout not done"], out


def test_user_action_still_holds_and_both_reasons_are_named(tmp_path, capsys):
    root = _repo(tmp_path, _ix(("T-1", "true"), ("T-2", "false")), {
        "a.md": _doc(),
        "b.md": _doc("feat/b", "[T-1, T-2]", 'hold: "rollout"\n'),
        "c.md": _doc("feat/c", "[T-2]"),
    })
    rc, out = _check(root, capsys)
    assert rc == 0
    # c.md holds nothing itself, but T-2 is named by held b.md: a hold is per task.
    assert _lines(out, "HELD") == [
        "HELD: a.md — branch feat/a; user_action outstanding: T-1",
        "HELD: b.md — branch feat/b; user_action outstanding: T-1; hold: rollout",
        "HELD: c.md — branch feat/c; shares T-2 with a held doc",
    ], out
    assert out.splitlines()[-1] == "HOLD CHECK: 3 held, 0 to route"


def test_a_hold_is_per_task_and_closes_transitively(tmp_path, capsys):
    """Round 2, lenses A and C: `main--2.md` naming the held `main.md`'s task routed and wrote
    `T-1 Complete` while T-1 was held. A doc naming a held doc's id waits with it, and so does
    one sharing an id with THAT doc; an unrelated doc still routes."""
    root = _repo(tmp_path, _ix(), {
        "main.md": _doc("main", "[T-1]", 'hold: "rollout"\n'),
        "main--2.md": _doc("main", "[T-1, T-2]"),
        "feat-c.md": _doc("feat/c", "[T-2, T-3]"),
        "feat-d.md": _doc("feat/d", "[T-4]"),
    })
    _, out = _check(root, capsys)
    assert _lines(out, "HELD") == [
        "HELD: feat-c.md — branch feat/c; shares T-2 with a held doc",
        "HELD: main--2.md — branch main; shares T-1 with a held doc",
        "HELD: main.md — branch main; hold: rollout",
    ], out
    assert _lines(out, "ROUTE") == ["ROUTE: feat-d.md"], out


@pytest.mark.parametrize("value, held", [
    ('"rollout"', True), ('"false"', True), ("true", True), ("' '", True),
    ("false", False), ('""', False), ("0", False), ("null", False),
])
def test_hold_is_read_truthy_like_user_action(tmp_path, capsys, value, held):
    """A malformed value holds: holding a doc that should have closed costs one `clear`;
    closing one that should have held writes a false `done`."""
    root = _repo(tmp_path, _ix(("T-1", None)), {"a.md": _doc(extra=f"hold: {value}\n")})
    _, out = _check(root, capsys)
    assert bool(_lines(out, "HELD")) is held, out


@pytest.mark.parametrize("ids", ["T-1", "[T-1]"])
def test_legacy_task_ids_and_a_scalar_are_read(tmp_path, capsys, ids):
    root = _repo(tmp_path, _ix(("T-1", "true")),
                 {"a.md": f'---\nbranch: "feat/a"\ntask_ids: {ids}\n---\n'})
    _, out = _check(root, capsys)
    assert _lines(out, "HELD") == ["HELD: a.md — branch feat/a; user_action outstanding: T-1"], out


def test_convention_candidates_and_legacy_docs(tmp_path, capsys):
    root = _repo(tmp_path, _ix(), {
        "convention-candidates.md": "hold: x\n",
        "legacy.md": "## Classification\nfeature\n",
        "bad.md": "---\nbranch: [unclosed\n---\n",
    })
    _, out = _check(root, capsys)
    assert "convention-candidates" not in out, out
    assert _lines(out, "ROUTE") == ["ROUTE: legacy.md"], out
    assert _lines(out, "UNREADABLE")[0].startswith("UNREADABLE: bad.md — frontmatter does not parse"), out


@pytest.mark.parametrize("index", ["tasks: [unclosed\n", "- just a list\n", "date: 2026-09-31\n"])
def test_an_unreadable_index_exits_1_and_stamps_nothing(tmp_path, capsys, index):
    root = _repo(tmp_path, index, {"a.md": _doc(extra='hold: "x"\n')})
    before = (root / "sysop/runtime/pending-docs/a.md").read_bytes()
    assert pdh.check(root, stamp=True) == 1
    assert (root / "sysop/runtime/pending-docs/a.md").read_bytes() == before
    assert "no doc's hold can be decided" in capsys.readouterr().err.lower()


def test_no_index_still_reads_hold(tmp_path, capsys):
    root = _repo(tmp_path, "", {"a.md": _doc(extra='hold: "x"\n')})
    (root / "tasks/index.yml").unlink()
    rc, out = _check(root, capsys)
    assert rc == 0 and _lines(out, "HELD"), out


# ─────────────────────────────────────────────────────────────────────────────
# `--stamp`
# ─────────────────────────────────────────────────────────────────────────────

def test_stamp_writes_once_and_changes_nothing_else(tmp_path, capsys):
    doc = _doc(extra='hold: "x"\nsmoke_answers:\n- section: abc\n  decision: confirmed\n')
    root = _repo(tmp_path, _ix(("T-1", None), ("T-2", None)),
                 {"a.md": doc, "b.md": _doc("feat/b", "[T-2]")})
    pdh.check(root, stamp=True, today="2026-10-01")
    out = capsys.readouterr().out
    a = (root / "sysop/runtime/pending-docs/a.md").read_text()
    assert "(stamped now)" in out
    # FIRST frontmatter line, as Step 3c's recorder writes `smoke_answers`: appended, it would
    # join a trailing block scalar (lens A, round 1).
    assert a == doc.replace("---\nbranch:", "---\nheld_since: '2026-10-01'\nbranch:", 1), a
    assert yaml.safe_load(a.split("---")[1])["held_since"] == "2026-10-01"
    # a routed doc is never stamped
    assert (root / "sysop/runtime/pending-docs/b.md").read_text() == _doc("feat/b", "[T-2]")
    # idempotent: a second close keeps the first date
    pdh.check(root, stamp=True, today="2026-12-31")
    out = capsys.readouterr().out
    assert (root / "sysop/runtime/pending-docs/a.md").read_text() == a
    assert "held since 2026-10-01" in out and "stamped now" not in out


def test_a_trailing_block_scalar_is_stamped_and_keeps_its_value(tmp_path, capsys):
    doc = _doc(extra='hold: "x"\nnotes: |\n  line one\n')
    root = _repo(tmp_path, _ix(), {"a.md": doc})
    pdh.check(root, stamp=True, today="2026-10-01")
    fm = yaml.safe_load((root / "sysop/runtime/pending-docs/a.md").read_text().split("---")[1])
    assert fm["held_since"] == "2026-10-01" and fm["notes"] == "line one\n", fm


def test_an_unmerged_branch_is_held_and_never_stamped(tmp_path, capsys):
    """Lens C, round 1: `--stamp` stamped a held doc whose branch never merged (a 4a-SKIP),
    and the stamp then made the doc read as landed."""
    root = _repo(tmp_path, _ix(), {"a.md": _doc(extra='hold: "x"\n')})
    _g(root, "checkout", "-q", "feat/a")
    (root / "f.txt").write_text("work\n")
    _g(root, "add", "f.txt")
    _g(root, "commit", "-qm", "unmerged work")
    _g(root, "checkout", "-q", "main")
    before = (root / "sysop/runtime/pending-docs/a.md").read_bytes()
    pdh.check(root, stamp=True, today="2026-10-01")
    out = capsys.readouterr().out
    assert _lines(out, "HELD") == [
        "HELD: a.md — branch feat/a; hold: x; NOT STAMPED: branch feat/a is not merged into HEAD"], out
    assert (root / "sysop/runtime/pending-docs/a.md").read_bytes() == before


def test_a_branch_in_a_recorded_pr_head_is_stamped(tmp_path, capsys):
    """Under `pr` the squash breaks ancestry; a recorded head (`Q-623`) says it merged."""
    root = _repo(tmp_path, _ix(), {"a.md": _doc(extra='hold: "x"\n')})
    _g(root, "checkout", "-q", "feat/a")
    (root / "f.txt").write_text("work\n")
    _g(root, "add", "f.txt")
    _g(root, "commit", "-qm", "work")
    _g(root, "update-ref", "refs/sysop/merged-pr-heads/7", "feat/a")
    _g(root, "checkout", "-q", "main")
    pdh.check(root, stamp=True, today="2026-10-01")
    assert "(stamped now)" in capsys.readouterr().out


def test_check_without_stamp_writes_nothing(tmp_path, capsys):
    root = _repo(tmp_path, _ix(), {"a.md": _doc(extra='hold: "x"\n')})
    before = (root / "sysop/runtime/pending-docs/a.md").read_bytes()
    pdh.check(root)
    assert (root / "sysop/runtime/pending-docs/a.md").read_bytes() == before


def test_an_empty_held_since_is_replaced_not_duplicated(tmp_path, capsys):
    root = _repo(tmp_path, _ix(), {"a.md": _doc(extra='hold: "x"\nheld_since:\n')})
    pdh.check(root, stamp=True, today="2026-10-01")
    a = (root / "sysop/runtime/pending-docs/a.md").read_text()
    assert a.count("held_since") == 1, a
    assert yaml.safe_load(a.split("---")[1])["held_since"] == "2026-10-01"


def test_crlf_is_preserved_and_mixed_endings_refuse_but_still_hold(tmp_path, capsys):
    crlf = _doc(extra='hold: "x"\n').replace("\n", "\r\n")
    mixed = _doc("feat/m", extra='hold: "x"\n').replace("summary", "\r\nsummary", 1)
    root = _repo(tmp_path, _ix(), {})
    _g(root, "branch", "feat/a")
    _g(root, "branch", "feat/m")
    pd = root / "sysop/runtime/pending-docs"
    (pd / "c.md").write_bytes(crlf.encode())
    (pd / "m.md").write_bytes(mixed.encode())
    pdh.check(root, stamp=True, today="2026-10-01")
    out = capsys.readouterr().out
    c = (pd / "c.md").read_bytes().decode()
    assert c.count("\r\n") == c.count("\n") and "held_since: '2026-10-01'\r\n" in c, repr(c)
    assert (pd / "m.md").read_bytes().decode() == mixed
    m_line = next(ln for ln in _lines(out, "HELD") if ln.startswith("HELD: m.md"))
    assert "NOT STAMPED: it mixes line endings" in m_line, out


def test_a_bom_prefixed_doc_still_holds(tmp_path, capsys):
    """Step 3c's and Step 4c's readers allow a leading BOM; so must the hold test."""
    root = _repo(tmp_path, _ix(), {"a.md": "\ufeff" + _doc(extra='hold: "x"\n')})
    pdh.check(root)
    assert _lines(capsys.readouterr().out, "HELD") == ["HELD: a.md — branch feat/a; hold: x"]


def test_a_stray_byte_still_holds_and_refuses_only_the_rewrite(tmp_path, capsys):
    """Step 3c and Step 4c decode with `errors="replace"`, so they parse this doc and Step 4c
    would route it: a hold test that called it UNREADABLE let its `hold:` through."""
    root = _repo(tmp_path, _ix(), {})
    _g(root, "branch", "feat/a")
    path = root / "sysop/runtime/pending-docs/a.md"
    raw = _doc(extra='hold: "x"\n').encode().replace(b"# body", b"# b\xffdy")
    path.write_bytes(raw)
    pdh.check(root, stamp=True, today="2026-10-01")
    out = capsys.readouterr().out
    assert _lines(out, "HELD") == [
        "HELD: a.md — branch feat/a; hold: x; NOT STAMPED: it is not valid UTF-8"], out
    assert path.read_bytes() == raw


# ─────────────────────────────────────────────────────────────────────────────
# `clear`
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("target", ["T-1", "feat/a", "a.md", "a"])
def test_clear_selects_by_task_branch_or_file_name(tmp_path, capsys, target):
    doc = _doc(extra='hold: "x"\nheld_since: \'2026-10-01\'\n')
    root = _repo(tmp_path, _ix(("T-1", "false")), {"a.md": doc})
    assert pdh.clear(root, target) == 0
    a = (root / "sysop/runtime/pending-docs/a.md").read_text()
    assert a == doc.replace('hold: "x"\n', ""), a
    assert "next /review-close consolidates" in capsys.readouterr().out
    pdh.check(root)
    assert _lines(capsys.readouterr().out, "ROUTE") == ["ROUTE: a.md"]


def test_clear_keeps_the_authors_blank_line(tmp_path, capsys):
    """Lens B, round 1: the blank line after `hold:` was removed with it."""
    doc = _doc(extra='hold: "x"\n\nreview_task_ids: []\n')
    root = _repo(tmp_path, _ix(), {"a.md": doc})
    assert pdh.clear(root, "T-1") == 0
    assert (root / "sysop/runtime/pending-docs/a.md").read_text() == doc.replace('hold: "x"\n', "")


def test_clear_dry_run_writes_nothing(tmp_path, capsys):
    root = _repo(tmp_path, _ix(), {"a.md": _doc(extra='hold: "x"\n')})
    before = (root / "sysop/runtime/pending-docs/a.md").read_bytes()
    assert pdh.clear(root, "T-1", dry_run=True) == 0
    assert (root / "sysop/runtime/pending-docs/a.md").read_bytes() == before
    assert "DRY RUN" in capsys.readouterr().out


def test_clear_leaves_a_user_action_hold_and_says_so(tmp_path, capsys):
    root = _repo(tmp_path, _ix(("T-1", "true")), {"a.md": _doc(extra='hold: "x"\n')})
    assert pdh.clear(root, "T-1") == 0
    out = capsys.readouterr().out
    assert "python3 sysop/scripts/clear_user_action.py T-1" in out
    assert "next /review-close consolidates" not in out
    pdh.check(root)
    assert _lines(capsys.readouterr().out, "HELD") == [
        "HELD: a.md — branch feat/a; user_action outstanding: T-1"]


def test_clear_removes_a_block_scalar_hold(tmp_path, capsys):
    doc = _doc(extra="hold: |\n  rollout to staging\n  then prod\nreview_task_ids: []\n")
    root = _repo(tmp_path, _ix(), {"a.md": doc})
    assert pdh.clear(root, "T-1") == 0
    fm = yaml.safe_load((root / "sysop/runtime/pending-docs/a.md").read_text().split("---")[1])
    assert "hold" not in fm and fm["review_task_ids"] == [] and fm["summary"] == "s", fm


def test_clear_refuses_rather_than_change_another_key(tmp_path, capsys):
    """A column-0 `hold:` inside a flow mapping belongs to that mapping. With `b: 3` after it,
    the line-based removal leaves YAML that PARSES, minus the mapping's own key, so only the
    re-parse comparison refuses it (the battery's D10: a fixture whose result failed to parse
    refused for the wrong reason)."""
    doc = _doc(extra="hold: x\nextra: {a: 1,\nhold: 2,\nb: 3}\n")
    root = _repo(tmp_path, _ix(), {"a.md": doc})
    assert pdh.clear(root, "T-1") == 1
    assert (root / "sysop/runtime/pending-docs/a.md").read_text() == doc
    assert "REFUSING" in capsys.readouterr().err


def test_clear_with_no_match_exits_2(tmp_path, capsys):
    root = _repo(tmp_path, _ix(), {"a.md": _doc(), "bad.md": "---\n[x\n---\n"})
    assert pdh.clear(root, "T-9") == 2
    err = capsys.readouterr().err
    assert "names T-9" in err and "bad.md could not be read" in err


# ─────────────────────────────────────────────────────────────────────────────
# `guard`: the file `/document-work` writes, and the hold it carries (Wade, 2026-10-01)
# ─────────────────────────────────────────────────────────────────────────────

def _guard(path: Path, capsys) -> tuple[int, str]:
    rc = pdh.guard(path)
    return rc, capsys.readouterr().out


def _write_line(out: str) -> str:
    (w,) = [ln[len("WRITE: "):] for ln in out.splitlines() if ln.startswith("WRITE: ")]
    return Path(w).name


def test_guard_writes_beside_a_doc_a_close_has_stamped(tmp_path, capsys):
    """`/document-work` on `main` writes `main.md`. A held `main.md` is the only carrier of its
    tasks into a later close, so the new doc goes beside it; it is never replaced."""
    doc = _doc("main", "[T-1, T-2]", "hold: \"rollout\"\nheld_since: '2026-10-01'\n")
    root = _repo(tmp_path, _ix(), {"main.md": doc})
    pd = root / "sysop/runtime/pending-docs"
    rc, out = _guard(pd / "main.md", capsys)
    assert rc == 0 and _write_line(out) == "main--2.md", out
    assert "NOTE: main.md is held by a close (held since 2026-10-01)" in out
    assert (pd / "main.md").read_text() == doc
    # the sibling, once written, is the one a re-run rewrites
    (pd / "main--2.md").write_text(_doc("main", "[T-3]"))
    rc, out = _guard(pd / "main.md", capsys)
    assert _write_line(out) == "main--2.md", out
    # once the sibling is stamped too, the next goes to --3
    (pd / "main--2.md").write_text(_doc("main", "[T-3]", "held_since: '2026-10-02'\n"))
    rc, out = _guard(pd / "main.md", capsys)
    assert _write_line(out) == "main--3.md", out


@pytest.mark.parametrize("extra", ["", 'hold: "rollout"\n', "held_since:\n"])
def test_guard_rewrites_a_doc_no_close_has_held(tmp_path, capsys, extra):
    """A `hold:` with no stamp is the branch's own earlier doc: rewriting it is the re-stamp."""
    root = _repo(tmp_path, _ix(), {"a.md": _doc(extra=extra)})
    pd = root / "sysop/runtime/pending-docs"
    assert _write_line(_guard(pd / "a.md", capsys)[1]) == "a.md"
    assert _write_line(_guard(pd / "absent.md", capsys)[1]) == "absent.md"


def test_guard_carries_the_main_checkouts_hold_into_a_worktree_doc(tmp_path, capsys):
    """Lenses A and C, round 1: Step 3b's collect replaces main's held copy with the
    worktree's, so the worktree's doc must carry the `hold:`."""
    root = _repo(tmp_path, _ix(), {"feat-a.md": _doc(extra='hold: "verify after deploy"\n'
                                                       "held_since: '2026-10-01'\n")})
    wt = tmp_path / "wt"
    _g(root, "worktree", "add", "-q", str(wt), "feat/a")
    wpd = wt / "sysop/runtime/pending-docs"
    wpd.mkdir(parents=True)
    import os as _os
    cwd = _os.getcwd()
    try:
        _os.chdir(wt)
        rc, out = _guard(wpd / "feat-a.md", capsys)
    finally:
        _os.chdir(cwd)
    assert rc == 0 and _write_line(out) == "feat-a.md", out
    assert "CARRY HOLD: verify after deploy (from the main checkout's feat-a.md)" in out, out


def test_guard_fails_closed_on_an_unreadable_doc(tmp_path, capsys):
    root = _repo(tmp_path, _ix(), {"a.md": "---\nbranch: [x\n---\n"})
    assert pdh.guard(root / "sysop/runtime/pending-docs/a.md") == 1


def test_document_work_runs_the_guard_as_written(tmp_path):
    text = DOCWORK.read_text(encoding="utf-8")
    (cmd,) = re.findall(r"`(python3 sysop/scripts/pending_doc_hold\.py guard [^`]+)`", text)
    assert cmd == ("python3 sysop/scripts/pending_doc_hold.py guard "
                   "sysop/runtime/pending-docs/<sanitized-branch-name>.md"), cmd
    step3 = text[text.index("## Step 3: Write Pending Documentation"):text.index("## Step 3b:")]
    assert step3.index(cmd) < step3.index("3. Write `<pending-doc path>`"), (
        "the guard must run before the write it chooses the file for")
    main = _installed(tmp_path)
    pd = main / "sysop/runtime/pending-docs"
    (pd / "main.md").write_text(_doc("main", extra="held_since: '2026-10-01'\n"))
    env = _env_with_python3(tmp_path)
    r = subprocess.run(["bash", "-c", cmd.replace("<sanitized-branch-name>", "main")], cwd=main,
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "WRITE: sysop/runtime/pending-docs/main--2.md" in r.stdout, r.stdout


def test_document_work_step_3b_reads_the_doc_guard_chose(tmp_path):
    """Step 3b's follow-up check must read the file step 2b wrote, not the base name."""
    text = DOCWORK.read_text(encoding="utf-8")
    m = re.search(r"python3 - <<'PY'\n(.*?)\nPY\n", text[text.index("## Step 3b:"):], re.DOTALL)
    body = m.group(1)
    main = _installed(tmp_path)
    pd = main / "sysop/runtime/pending-docs"
    # `T-99` uses the index's own prefix (`T-1`), so Step 3b flags it as an unfiled task in
    # whichever doc it reads: a token with a prefix the index lacks is never scanned for, and
    # the battery's R12 showed the first fixture was vacuous for that reason.
    (pd / "main.md").write_text(_doc("main", "[T-1]", "held_since: '2026-10-01'\n")
                                + "Filed as T-99.\n")
    (pd / "main--2.md").write_text(_doc("main", "[T-1]"))
    r = subprocess.run([sys.executable, "-"], input=body, cwd=main, capture_output=True,
                       text=True, env=_env_with_python3(tmp_path))
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert "T-99" not in r.stdout + r.stderr, (r.stdout, r.stderr)
    (pd / "main--2.md").write_text(_doc("main", "[T-1]") + "Filed as T-99.\n")
    r = subprocess.run([sys.executable, "-"], input=body, cwd=main, capture_output=True,
                       text=True, env=_env_with_python3(tmp_path))
    assert r.returncode != 0 and "T-99" in r.stdout + r.stderr, (  # the control: it does scan
        r.returncode, r.stdout, r.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# The commands the skills prescribe, run as written
# ─────────────────────────────────────────────────────────────────────────────

def _installed(tmp_path: Path) -> Path:
    """A consumer checkout with a linked worktree, the scripts at `sysop/scripts/`."""
    main = tmp_path / "main"
    (main / "sysop/scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, main / "sysop/scripts/pending_doc_hold.py")
    (main / "tasks").mkdir()
    (main / "tasks/index.yml").write_text(_ix(("T-1", "false")))
    (main / ".gitignore").write_text("sysop/runtime/\n")
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["add", "-A"], ["commit", "-qm", "base"]):
        subprocess.run(["git", *args], cwd=main, check=True, capture_output=True, env=_ENV)
    pd = main / "sysop/runtime/pending-docs"
    pd.mkdir(parents=True)
    (pd / "a.md").write_text(_doc(extra='hold: "rollout"\n'))
    subprocess.run(["git", "branch", "feat/a"], cwd=main, check=True, capture_output=True, env=_ENV)
    return main


def _env_with_python3(tmp_path: Path) -> dict:
    """`python3` on PATH resolving to an interpreter that has PyYAML, as on a consumer whose
    venv is active. A shell shim, not a symlink: a symlinked venv interpreter loses its venv."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    shim = d / "python3"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    shim.chmod(0o755)
    return {**_ENV, "PATH": f"{d}{os.pathsep}{_ENV.get('PATH', '')}"}


def test_step_4c_1c_runs_its_command_as_written(tmp_path):
    text = CLOSE.read_text(encoding="utf-8")
    start = text.index("1c. **Hold back any pending-doc")
    step = text[start:text.index("2. **If none found**", start)]
    cmds = [ln.strip() for ln in step.splitlines() if ln.strip().startswith("python3 sysop/")]
    assert cmds == ["python3 sysop/scripts/pending_doc_hold.py check --stamp"], cmds
    main = _installed(tmp_path)
    r = subprocess.run(["bash", "-c", cmds[0]], cwd=main, capture_output=True, text=True,
                       env=_env_with_python3(tmp_path))
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("HELD: a.md — branch feat/a; hold: rollout; held since "), r.stdout
    assert "held_since:" in (main / "sysop/runtime/pending-docs/a.md").read_text()


@pytest.mark.parametrize("path", [DOCWORK, SCHEMA, CLOSE, WF])
def test_the_clear_command_runs_as_written_from_a_linked_worktree(tmp_path, path):
    """Every shipped `clear <TASK_ID>` prescription, substituted and run from a worktree:
    the held docs live in the main checkout, and a human may be standing anywhere."""
    text = path.read_text(encoding="utf-8")
    found = re.findall(r"python3 sysop/scripts/pending_doc_hold\.py clear <TASK_ID>", text)
    assert found, f"{path.name} no longer prescribes the clear"
    # Every occurrence, not the first (lens B, round 1); each is the same literal, so one
    # run per occurrence on a fresh hold.
    for i, cmd in enumerate(found):
        main = _installed(tmp_path / str(i))
        wt = tmp_path / str(i) / "wt"
        subprocess.run(["git", "worktree", "add", "-q", "--detach", str(wt)], cwd=main,
                       check=True, capture_output=True, env=_ENV)
        r = subprocess.run(["bash", "-c", cmd.replace("<TASK_ID>", "T-1")], cwd=wt,
                           capture_output=True, text=True, env=_env_with_python3(tmp_path / str(i)))
        assert r.returncode == 0, r.stderr
        assert "hold" not in yaml.safe_load(
            (main / "sysop/runtime/pending-docs/a.md").read_text().split("---")[1])


# ─────────────────────────────────────────────────────────────────────────────
# Step 3c reads `hold:` and the stamp (`Q-610`(b))
# ─────────────────────────────────────────────────────────────────────────────

BODY = {"FEAT-H.md": "# H\n\n## Manual smoke required\n1. Console step.\n"}


def test_step_3c_holds_a_doc_on_its_own_hold(tmp_path):
    doc = '---\nbranch: feat/old\nroadmap_ids: [FEAT-H]\nhold: "rollout"\n---\n# S\n'
    main = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="false")),
                 pending={"old.md": doc}, bodies=BODY)
    out = _run(main, [], branches=["feat/new"])
    assert out.splitlines()[0] == "NO_SMOKE_REQUIRED", out
    assert "NOT IN THIS RUN: tasks/index.yml § FEAT-H — linked only by held doc" in out, out


def test_step_3c_names_both_reasons_and_the_stamp(tmp_path):
    doc = HELD_DOC.replace("roadmap_ids", "hold: \"rollout\"\nheld_since: '2026-10-01'\nroadmap_ids")
    main = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")), pending={"old.md": doc})
    (held,) = _field(_run(main, [], branches=[]), "NOT MERGING")
    assert held.startswith("held by Step 4c 1c (user_action outstanding: FEAT-H; hold: rollout), "
                           "held since 2026-10-01; not merging in this run"), held


@pytest.mark.parametrize("value", ['"rollout"', '"false"', "true", "false", '""', "0", "' '", "No"])
def test_step_3c_and_the_script_agree_on_hold(tmp_path, capsys, value):
    """The two readers of `hold:` must agree, value for value, or 3c drops the links of a doc
    4c then routes, or asks about one 4c holds."""
    doc = f"---\nbranch: feat/old\nroadmap_ids: [FEAT-H]\nhold: {value}\n---\n# S\n"
    main = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="false")),
                 pending={"old.md": doc}, bodies=BODY)
    out = _run(main, [], branches=[])
    by_gate = "NOT IN THIS RUN" in out
    pdh.check(main)
    by_script = bool(_lines(capsys.readouterr().out, "HELD"))
    assert by_gate is by_script, (value, out)


def _main_doc_reasks(tmp_path) -> tuple[Path, str]:
    """`Q-610`'s reproduction: a held `branch: main` doc, its section answered at the close
    that merged it, asked again at the next."""
    doc = HELD_DOC.replace("branch: feat/old", "branch: main")
    main = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")),
                 pending={"main.md": doc}, bodies=BODY)
    out = _run(main, [], branches=[])
    assert _signals(out) == 2, out                          # its heading + the task's body
    for key in _keys(out):
        assert _record(main, "sysop/runtime/pending-docs/main.md", key, "confirmed").returncode == 0
    return main, doc


def test_an_unstamped_main_doc_is_still_asked(tmp_path):
    """The safe direction, kept: without the stamp the doc's work may be landing now."""
    main, _ = _main_doc_reasks(tmp_path)
    out = _run(main, [], branches=[])
    assert _signals(out) == 2 and "PREVIOUSLY ANSWERED" not in out, out


def _origin_at_head(main: Path) -> None:
    """`origin/main` where local `main` is: what Step 6 leaves after the stamping close."""
    _g(main, "update-ref", "refs/remotes/origin/main", "HEAD")


def test_a_stamped_main_doc_is_still_asked_the_accepted_q610_limit(tmp_path, capsys):
    """`Q-610` was reopened on Wade's answer (round 2): neither a date stamp nor "nothing on
    `main` beyond origin" tells a landed default-branch doc from one whose work lands now (the
    second is false whenever a claim flip is committed and unpushed). So Step 3c does not read
    the stamp, and a held `branch: main` doc is asked as before Phase 353. Wade closed `Q-610`
    by disposition on 2026-10-06 (Phase 360): the re-ask is the accepted, loud direction, and
    this test holds it."""
    main, _ = _main_doc_reasks(tmp_path)
    assert pdh.check(main, stamp=True) == 0
    assert "(stamped now)" in capsys.readouterr().out
    _origin_at_head(main)
    out = _run(main, [], branches=[])
    assert _signals(out) == 2 and "PREVIOUSLY ANSWERED" not in out, out


def test_a_stamped_main_doc_is_asked_again_while_main_has_work_to_land(tmp_path, capsys):
    """Lenses A and C, round 1: a date stamp alone dropped the held task's links, so a new,
    never-answered procedure (and fix code for the task) landed unasked. Any local commit
    beyond origin makes the doc merging again."""
    main, _ = _main_doc_reasks(tmp_path)
    pdh.check(main, stamp=True)
    _origin_at_head(main)
    (main / "tasks/open/FEAT-H.md").write_text(
        BODY["FEAT-H.md"] + "\n## Manual smoke required — the fix\n1. Re-check the console.\n")
    _g(main, "commit", "-qam", "fix for FEAT-H on main")
    out = _run(main, [], branches=[])
    assert "the fix" in out and _signals(out) >= 1, out
    assert "NOT IN THIS RUN" not in out, out


def test_a_stamped_main_doc_with_no_origin_ref_is_asked(tmp_path, capsys):
    main, _ = _main_doc_reasks(tmp_path)
    pdh.check(main, stamp=True)
    out = _run(main, [], branches=[])
    assert _signals(out) == 2 and "PREVIOUSLY ANSWERED" not in out, out


def test_an_unstamped_main_doc_with_hold_is_asked(tmp_path):
    """Lens A's G11: only the stamp, never `hold:` alone, makes a default-branch doc settled."""
    doc = HELD_DOC.replace("branch: feat/old", "branch: main").replace(
        "roadmap_ids", 'hold: "rollout"\nroadmap_ids')
    main = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="false")),
                 pending={"main.md": doc}, bodies=BODY)
    _origin_at_head(main)
    out = _run(main, [], branches=[])
    assert "tasks/index.yml § FEAT-H" in _sources(out) and "NOT IN THIS RUN" not in out, out


def test_an_empty_held_since_is_not_a_stamp_to_step_3c(tmp_path):
    doc = HELD_DOC.replace("branch: feat/old", "branch: main").replace(
        "roadmap_ids", "held_since:\nroadmap_ids")
    main = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")),
                 pending={"main.md": doc}, bodies=BODY)
    _origin_at_head(main)
    out = _run(main, [], branches=[])
    assert "tasks/index.yml § FEAT-H" in _sources(out), out


def test_a_stamped_doc_whose_branch_is_approved_again_is_asked(tmp_path):
    doc = HELD_DOC.replace("roadmap_ids", "held_since: '2026-10-01'\nroadmap_ids")
    main = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")),
                 pending={"old.md": doc}, bodies=BODY)
    out = _run(main, [], branches=["feat/old"])
    assert _field(out, "NOT MERGING") == [], out
    assert "tasks/index.yml § FEAT-H" in _sources(out), out


def test_a_stamped_main_doc_with_head_unresolved_is_asked(tmp_path):
    doc = HELD_DOC.replace("branch: feat/old", "branch: main").replace(
        "roadmap_ids", "held_since: '2026-10-01'\nroadmap_ids")
    main = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")),
                 pending={"main.md": doc}, bodies=BODY, git=False)
    out = _run(main, [], branches=[])
    assert _field(out, "NOT MERGING") == [] and "NOT IN THIS RUN" not in out, out


# ─────────────────────────────────────────────────────────────────────────────
# `/sitrep`'s landed arm names the clear
# ─────────────────────────────────────────────────────────────────────────────

def _held_doc(w: Path, branch: str, extra: str = ""):
    d = w / "sysop/runtime/pending-docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{branch}.md").write_text(f'---\nbranch: "{branch}"\nroadmap_ids: [T1]\n{extra}---\n')


def test_sitrep_names_the_hold_clear(squashed, monkeypatch):
    w, _ = squashed
    record(w)
    _write_lock(w, "T1", "B1", "2026-09-30T00:00:00Z")
    _held_doc(w, "B1", 'hold: "rollout to prod"\n')
    t1 = _survey(w, monkeypatch)["T1"]
    assert t1.state == ss._MERGED_STATE, (t1.state, t1.notes)
    assert t1.next_action == ("finish what its pending doc's `hold:` names, then python3 "
                              "sysop/scripts/pending_doc_hold.py clear T1 and /review-close"), t1
    assert any("hold: rollout to prod" in n for n in t1.notes), t1.notes


def test_sitrep_names_both_clears(squashed, monkeypatch):
    w, _ = squashed
    record(w)
    _write_lock(w, "T1", "B1", "2026-09-30T00:00:00Z")
    _held_doc(w, "B1", 'hold: "rollout"\n')
    t1 = _survey(w, monkeypatch, "    user_action: true\n")["T1"]
    assert "clear_user_action.py T1" in t1.next_action
    assert "pending_doc_hold.py clear T1" in t1.next_action
    assert t1.next_action.endswith(" and /review-close"), t1.next_action


# ─────────────────────────────────────────────────────────────────────────────
# Hash pins over the text Phase 353 decided
# ─────────────────────────────────────────────────────────────────────────────
#
# What a test cannot execute is the prose the runner acts on: what holds a doc, that 1c never
# removes `hold:`, that the round-trip takes its ids from `ROUTE:` docs, when `/document-work`
# writes `hold:`. A deliberate change moves its pin in the same commit (`_print_pins()`).

from _reversal import slice_between  # noqa: E402
from test_fix_in_branch_tier import (_anchor_count, _pin_hash, _pin_liveness,  # noqa: E402
                                     _pin_norm, _pin_span)

SPANS: dict[str, tuple[Path, str, str, bool]] = {
    "4c 1b runs the hold test": (CLOSE, "**Before resolving anything, run 1c's hold test without `--stamp`**", "\n   >\n", False),
    "4c 1c hold test": (CLOSE, "1c. **Hold back any pending-doc whose deliverable is not finished",
                        "\n\n   **Why the WHOLE doc waits", False),
    "4c round-trip ids from ROUTE": (CLOSE, "Take the ids from step 1c's `ROUTE:` docs, never from a `HELD:` one.", "\n", False),
    "step 8 hold bullet": (CLOSE, "  - <any docs HELD on `hold:`", "     **The invariant to check", True),
    "document-work hold": (DOCWORK, "**`hold:` — only when this merge does not finish the task",
                           "\n\n", False),
    "schema hold": (SCHEMA, "**A second input to the same hold", "\n\n", False),
    "document-work guard": (DOCWORK, "2b. **Choose the file, and carry any hold.**", "\n3. Write", False),
    "sitrep row 3b": (REPO / "core/skills/sitrep/SKILL.md", "| 3b       | Any task `merged, close pending`", "\n", False),
    "step 8 1c row": (CLOSE, "     - 1c (`user_action outstanding: <TASK_ID>`, `hold: <reason>`", "\n\nRemaining:", True),
    "3b collect exit 3": (CLOSE, "| **3** | a collision — some doc does not belong to this branch", "\n", False),
    "permission bullet": (CLOSE, "- `Bash(python3 sysop/scripts/pending_doc_hold.py:*)` — Step 4c", "\n", False),
    "step 8 held rows anomaly": (CLOSE, "`held (hold:): <HELD_BY_HOLD ids>` — see Remaining.", "These four rows PARTITION", True),
    "step 6 held-doc rule": (CLOSE, "**HARD RULE — do not delete a branch whose pending-doc Step 4c step 1c held back",
                             "\n\n", False),
    "4a-post third filter": (CLOSE, "**Step 1c is the one most easily missed and it is decisive**",
                             "**If you cannot name a doc that clears all three, stop.**", False),
    "WORKFLOW 6.6 hold fields": (WF, "> **`hold:` and `held_since:` are optional", "\n\n", False),
}

PINS = {
    # Regenerate with:  .venv/bin/python3 -c "import sys; sys.path.insert(0,'tests'); import test_pending_doc_hold as T; T._print_pins()"
    "4c 1b runs the hold test": "2eaa42885664950e",
    "4c 1c hold test": "f6b792ae8b942183",
    "4c round-trip ids from ROUTE": "c51cc46bb2d4d3ff",
    "step 8 hold bullet": "4bfc5f1ff0b2551b",
    "document-work hold": "5b1e796ff4d4fbf3",
    "schema hold": "41ae29c8f864c59f",
    "document-work guard": "e1cc9954baf52215",
    "sitrep row 3b": "f6a6999d66fab07b",
    "step 8 1c row": "da40f7132a37802b",
    "3b collect exit 3": "d94580e46fc808ec",
    "permission bullet": "0e0a7c3878c06e07",
    "step 8 held rows anomaly": "71dd86cd4e9005ca",
    "step 6 held-doc rule": "94a51dda402a40e8",
    "4a-post third filter": "c5fed5f2e373ffe4",
    "WORKFLOW 6.6 hold fields": "7bd0013a7881d0cd",
}


def _located(label: str) -> tuple[str, str, int]:
    path, start, end, _ = SPANS[label]
    text = path.read_text(encoding="utf-8")
    span = slice_between(text, start, end, label)
    return text, span, text.index(span)


def _span(label: str) -> str:
    text, span, at = _located(label)
    span = _pin_span(SPANS[label][0], text, at, span)
    assert len(_pin_norm(span)) > 60, f"{label}: the pinned span is nearly empty — anchors drifted"
    return span


def _print_pins() -> None:
    for label in SPANS:
        print(f'    "{label}": "{_pin_hash(_span(label))}",')


@pytest.mark.parametrize("label", sorted(SPANS))
def test_the_decided_text_is_pinned(label: str) -> None:
    got = _pin_hash(_span(label))
    assert label in PINS, f'{label}: no pin recorded; add "{label}": "{got}"'
    assert got == PINS[label], (
        f"{label} changed (hash {got}, pinned {PINS[label]}). Phase 353 decided this text. "
        "If the edit is deliberate, move the pin in the same commit and record why.")


@pytest.mark.parametrize("label", sorted(SPANS))
def test_every_span_start_anchor_is_unique(label: str) -> None:
    path, start, _, _ = SPANS[label]
    assert _anchor_count(path.read_text(encoding="utf-8"), start) == 1, label


@pytest.mark.parametrize("label", sorted(SPANS))
def test_every_span_is_live(label: str) -> None:
    text, _, at = _located(label)
    problem = _pin_liveness(SPANS[label][0], text, at, SPANS[label][3])
    assert problem is None, f"{label} {problem}"


def test_every_pin_has_a_span() -> None:
    assert set(PINS) == set(SPANS), set(PINS) ^ set(SPANS)


# ─────────────────────────────────────────────────────────────────────────────
# Round 1: Step 3b's collect and the round-trip heredoc
# ─────────────────────────────────────────────────────────────────────────────

from test_pending_doc_integrity import _run as _collect_run, scripts  # noqa: E402,F401
from test_review_close_cluster_241 import _run_round_trip, _task as _rt_task  # noqa: E402


def _collect_tree(tmp_path: Path, main_doc: str, wt_doc: str) -> tuple[Path, Path]:
    main, wt = tmp_path / "main", tmp_path / "wt"
    for root, doc in ((main, main_doc), (wt, wt_doc)):
        d = root / "sysop/runtime/pending-docs"
        d.mkdir(parents=True)
        (d / "feat-x.md").write_text(doc, encoding="utf-8")
    return main, wt


def test_the_collect_refuses_a_doc_that_drops_main_copys_hold(scripts, tmp_path):
    """Lenses A and C, round 1, reproduced: re-documenting a held feature branch replaced
    main's held copy, the `hold:` went with it, and Step 4c closed the task."""
    collect, _ = scripts
    held = ('---\nbranch: feat/x\nroadmap_ids: [T-1]\nhold: "verify after deploy"\n'
            "held_since: '2026-10-01'\n---\n")
    main, wt = _collect_tree(tmp_path, held, "---\nbranch: feat/x\nroadmap_ids: [T-1]\n---\n")
    r = _collect_run(collect, main, wt)
    assert r.returncode == 3, (r.returncode, r.stdout)
    assert "main copy carries `hold: verify after deploy`" in r.stdout, r.stdout
    assert (main / "sysop/runtime/pending-docs/feat-x.md").read_text() == held


def test_the_collect_takes_a_doc_that_carries_the_hold(scripts, tmp_path):
    collect, _ = scripts
    held = '---\nbranch: feat/x\nroadmap_ids: [T-1]\nhold: "verify"\n---\n'
    new = '---\nbranch: feat/x\nroadmap_ids: [T-1]\nhold: "verify"\nsummary: "new"\n---\n'
    main, wt = _collect_tree(tmp_path, held, new)
    r = _collect_run(collect, main, wt)
    assert r.returncode == 0, (r.returncode, r.stdout)
    assert (main / "sysop/runtime/pending-docs/feat-x.md").read_text() == new


def test_the_round_trip_does_not_close_an_id_a_doc_with_hold_names(tmp_path):
    """Lens A, round 1: `hold:` had only a prose gate at the round-trip. An id pasted from a
    HELD: doc is now reported, not closed, as a `user_action` id is."""
    d = tmp_path / "sysop/runtime/pending-docs"
    d.mkdir(parents=True)
    (d / "held.md").write_text('---\nbranch: "feat/a"\nroadmap_ids: [T-1]\nhold: "x"\n---\n')
    r, written = _run_round_trip(tmp_path, [_rt_task("T-1", False), _rt_task("T-2", False)],
                                 ["T-1", "T-2"])
    assert r.returncode == 0, r.stderr
    status = {e["id"]: e["status"] for e in written["tasks"]}
    assert status == {"T-1": "in_progress", "T-2": "done"}, status
    assert "HELD_BY_HOLD: T-1" in r.stdout and "NOT_IN_INDEX: (none)" in r.stdout, r.stdout


def test_sitrep_reads_a_held_doc_with_a_stray_byte(tmp_path):
    """Lenses A and B, round 1: `/sitrep` decoded strictly and lost a held doc the close holds."""
    d = tmp_path / "sysop/runtime/pending-docs"
    d.mkdir(parents=True)
    (d / "B1.md").write_bytes(b'---\nbranch: "B1"\nhold: "rollout"\n---\n# b\xe9\n')
    assert ss._held_doc_names(tmp_path, "B1") == ["B1.md"]
    assert ss._doc_holds(tmp_path, "B1") == ["rollout"]


def test_a_cr_only_doc_holds_as_step_3c_reads_it(tmp_path, capsys):
    """Lens A, round 1: Step 3c reads with universal newlines, so a CR-only doc parses and
    holds there; the hold test normalised only CRLF and routed it."""
    root = _repo(tmp_path, _ix(), {})
    _g(root, "branch", "feat/a")
    (root / "sysop/runtime/pending-docs/a.md").write_bytes(
        _doc(extra='hold: "x"\n').replace("\n", "\r").encode())
    pdh.check(root, stamp=True, today="2026-10-01")
    out = capsys.readouterr().out
    assert _lines(out, "HELD") == [
        "HELD: a.md — branch feat/a; hold: x; NOT STAMPED: it mixes line endings"], out


def test_a_rewrite_keeps_the_files_mode(tmp_path, capsys):
    """Lens A's A06: `mkstemp` creates 0600, so a rewrite without the chmod narrows the doc."""
    root = _repo(tmp_path, _ix(), {"a.md": _doc(extra='hold: "x"\n')})
    path = root / "sysop/runtime/pending-docs/a.md"
    path.chmod(0o644)
    pdh.check(root, stamp=True, today="2026-10-01")
    assert "held_since" in path.read_text() and (path.stat().st_mode & 0o777) == 0o644


# ─────────────────────────────────────────────────────────────────────────────
# Round 2
# ─────────────────────────────────────────────────────────────────────────────

def _in(cwd: Path, fn):
    import os as _os
    old = _os.getcwd()
    try:
        _os.chdir(cwd)
        return fn()
    finally:
        _os.chdir(old)


def _worktree(root: Path, tmp_path: Path, branch: str = "feat/a") -> Path:
    wt = tmp_path / "wt"
    _g(root, "worktree", "add", "-q", str(wt), branch)
    (wt / "sysop/runtime/pending-docs").mkdir(parents=True)
    return wt


def test_guard_carries_an_unstamped_held_main_copy(tmp_path, capsys):
    """Lens A's A08: a held copy 1c could not stamp (or that a 4a-SKIP left) still carries."""
    root = _repo(tmp_path, _ix(), {"feat-a.md": _doc(extra='hold: "verify"\n')})
    wt = _worktree(root, tmp_path)
    rc, out = _in(wt, lambda: _guard(wt / "sysop/runtime/pending-docs/feat-a.md", capsys))
    assert "CARRY HOLD: verify (from the main checkout's feat-a.md)" in out, out


def test_guard_carries_only_the_same_named_copy(tmp_path, capsys):
    """Round 2, lenses A (M2) and C (C7): a sibling is never replaced, so its hold is not carried."""
    root = _repo(tmp_path, _ix(), {"feat-a--2.md": _doc("feat-a--2", extra='hold: "other"\n')})
    _g(root, "branch", "feat/a")
    wt = _worktree(root, tmp_path)
    rc, out = _in(wt, lambda: _guard(wt / "sysop/runtime/pending-docs/feat-a.md", capsys))
    assert "CARRY HOLD" not in out, out


def test_guard_ignores_another_branchs_name_collision(tmp_path, capsys):
    """Lens C's C7: a branch named `main--2` is not `main`'s sibling."""
    root = _repo(tmp_path, _ix(), {
        "main.md": _doc("main", extra="held_since: '2026-10-01'\n"),
        "main--2.md": _doc("main--2"),
    })
    rc, out = _guard(root / "sysop/runtime/pending-docs/main.md", capsys)
    assert _write_line(out) == "main--3.md", out


def _collect_refusal(scripts, tmp_path, main_doc: str | bytes) -> subprocess.CompletedProcess:
    collect, _ = scripts
    main, wt = _collect_tree(tmp_path, "", "---\nbranch: feat/x\nroadmap_ids: [T-1]\n---\n")
    d = main / "sysop/runtime/pending-docs/feat-x.md"
    d.write_bytes(main_doc if isinstance(main_doc, bytes) else main_doc.encode())
    return _collect_run(collect, main, wt)


@pytest.mark.parametrize("main_doc", [
    '---\nbranch: feat/x\nroadmap_ids: [T-1]\nhold: "verify"\n---\n',          # unstamped (A20)
    "---\nbranch: feat/x\nroadmap_ids: [T-1]\nhold: true\n---\n",              # non-string (A17)
    b'---\nbranch: feat/x\nroadmap_ids: [T-1]\nhold: "v"\n---\n# \xe9\n',     # stray byte (A18)
])
def test_the_collect_refuses_every_shape_of_a_dropped_hold(scripts, tmp_path, main_doc):
    r = _collect_refusal(scripts, tmp_path, main_doc)
    assert r.returncode == 3 and "main copy carries `hold:" in r.stdout, (r.returncode, r.stdout)


def test_the_collect_refusal_names_a_remedy_every_workspace_shape_can_take(scripts, tmp_path):
    """Round 2, lenses A and C: a `--clone` gets no CARRY HOLD, so "re-run /document-work, which
    carries it" looped. The refusal names main's reason and says to add it."""
    r = _collect_refusal(scripts, tmp_path,
                         '---\nbranch: feat/x\nroadmap_ids: [T-1]\nhold: "verify"\n---\n')
    assert "add that `hold:` line to the incoming doc" in r.stdout, r.stdout
    assert "re-run /document-work on this branch, which carries it" not in r.stdout, r.stdout


@pytest.mark.parametrize("fm", [
    'branch: "feat/a"\ntask_ids: [T-1]\nhold: "x"\n',                        # A21
    '﻿XX',                                                               # A22 (BOM), filled below
    'branch: "feat/a"\nroadmap_ids: 123\nhold: "x"\n',                        # L1: scalar non-string
])
def test_the_round_trip_arm_reads_every_shape_the_hold_test_does(tmp_path, fm):
    d = tmp_path / "sysop/runtime/pending-docs"
    d.mkdir(parents=True)
    text = ("﻿---\nbranch: \"feat/a\"\nroadmap_ids: [T-1]\nhold: \"x\"\n---\n" if fm.startswith("﻿")
            else f"---\n{fm}---\n")
    (d / "held.md").write_text(text, encoding="utf-8")
    tid = "123" if "123" in fm else "T-1"
    r, written = _run_round_trip(tmp_path, [_rt_task(tid, False)], [tid])
    assert r.returncode == 0, r.stderr
    assert written["tasks"][0]["status"] == "in_progress" and f"HELD_BY_HOLD: {tid}" in r.stdout, r.stdout


def test_document_work_declares_the_rule_its_step_2b_needs():
    """Lens A's A29: removing the rule from /document-work's permission guard left every test
    green, because /review-close still named it."""
    text = DOCWORK.read_text(encoding="utf-8")
    guard = text[text.index("## Pre-flight: Permission Guard"):text.index("## Step 0")]
    assert "`Bash(python3 sysop/scripts/pending_doc_hold.py:*)`" in guard


def test_guard_does_not_carry_a_same_branch_siblings_hold(tmp_path, capsys):
    """S04: main's same-named copy carries no hold, its same-branch sibling does. The sibling is
    never replaced by the collect, so its hold is not copied onto the new doc."""
    root = _repo(tmp_path, _ix(), {
        "feat-a.md": _doc(),
        "feat-a--2.md": _doc(extra='hold: "sibling step"\n'),
    })
    wt = _worktree(root, tmp_path)
    rc, out = _in(wt, lambda: _guard(wt / "sysop/runtime/pending-docs/feat-a.md", capsys))
    assert "CARRY HOLD" not in out, out
