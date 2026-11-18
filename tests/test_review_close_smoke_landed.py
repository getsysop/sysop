"""`/review-close` Step 3c and a branch Step 2a step 0b approved as landed.

A landed branch has every commit in a merged PR's head, or in the default branch. Before this fix
an answer recorded to one of its signals was never honoured: `smoke_detect.py` consulted a
recorded answer only for a doc that is not merging, and a landed branch is approved. So every
consolidating close asked its before-merge questions again, with nothing saying the work had
already merged.

Now the script runs `feature_branch.py landed`, the check step 0b runs, for each approved branch.
A signal on a landed branch takes a recorded answer that matches its key, as a held doc's does,
and is otherwise ASKED, with an `ALREADY MERGED:` line in its block. It is never silenced: a
branch can land at its first close (a claim with no commits of its own whose doc was written
straight into main), so nothing proves an earlier close asked. A task that a merging branch also
links is read there, asked unmarked, and no answer recorded on the landed branch covers it.
Anything the landed check cannot say plainly reads as not landed: asked, unmarked.

The fixtures are `test_squash_provenance.py`'s: a local bare `origin` (never a real URL), one
`pr` close squash-merged as PR #1, and the head recorded as Step 4d records it.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_review_close_smoke_gate import SMOKE_SCRIPT, _signals, _sources  # noqa: E402
from test_squash_provenance import _ENV, git, record, squashed  # noqa: E402,F401

RECORDER = Path(SMOKE_SCRIPT).with_name("smoke_record.py")
HEADING = "## Manual smoke required\n1. Click through the export dialog.\n"
MARK = "ALREADY MERGED: "


def _doc(w: Path, branch: str, *, ids=("T1",), extra: str = "", body: str = HEADING) -> Path:
    d = w / "sysop/runtime/pending-docs"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{branch}.md"
    p.write_text(f"---\nbranch: {branch}\nroadmap_ids: [{', '.join(ids)}]\n{extra}---\n"
                 f"# Summary\n\n{body}", encoding="utf-8")
    return p


def _lock(w: Path, task: str, branch: str) -> None:
    d = w / "sysop/runtime/locks"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{task}.lock").write_text(f"task_id: {task}\nstatus: in_progress\nbranch: {branch}\n",
                                    encoding="utf-8")


def _smoke(w: Path, *branches: str, script: str = SMOKE_SCRIPT) -> str:
    r = subprocess.run([sys.executable, script, "--branches", "main", *branches],
                       cwd=w, env=_ENV, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _lines(out: str, prefix: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln.startswith(prefix)]


def _blocks(out: str) -> dict[str, list[str]]:
    """SOURCE -> the block's lines, for each signal block."""
    blocks, cur = {}, None
    for ln in out.splitlines():
        if ln == "---SIGNAL---":
            cur = []
        elif cur is not None:
            if ln.startswith("SOURCE: "):
                blocks[ln[len("SOURCE: "):]] = cur
            cur.append(ln)
    return blocks


def _mark(block: list[str]) -> list[str]:
    return [ln for ln in block if ln.startswith(MARK)]


def _key(section: str) -> str:
    return hashlib.sha256(section.strip().encode("utf-8")).hexdigest()[:16]


def _record(w: Path, doc: str, key: str) -> None:
    r = subprocess.run([sys.executable, str(RECORDER), doc, key, "confirmed"],
                       cwd=w, env=_ENV, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


@pytest.fixture
def landed(squashed):
    """B1 merged in PR #1, its head is recorded, and its doc is held in main: step 0b's LANDED."""
    w, _ = squashed
    assert record(w).returncode == 0
    _doc(w, "B1")
    return w


B1_DOC = "sysop/runtime/pending-docs/B1.md"


def test_a_landed_branchs_signal_is_asked_and_marked(landed):
    out = _smoke(landed, "B1")
    assert _signals(out) == 1, out
    block = _blocks(out)[B1_DOC]
    assert _mark(block) == [MARK + "PR #1 — Step 2a approved this branch as landed; no recorded "
                            "answer covers this section"], block
    assert "BRANCH: B1" in block and any(ln.startswith("KEY: ") for ln in block), block
    assert block.index("BRANCH: B1") < block.index(_mark(block)[0]), block


def test_a_recorded_answer_on_a_landed_branch_is_honoured(landed):
    """The answer an earlier close recorded is reported as answered, as a held doc's is."""
    _record(landed, B1_DOC, _key(HEADING))
    out = _smoke(landed, "B1")
    assert out.splitlines()[0] == "NO_SMOKE_REQUIRED", out
    (line,) = _lines(out, "PREVIOUSLY ANSWERED:")
    assert line.startswith(f"PREVIOUSLY ANSWERED: {B1_DOC} — confirmed on "), line
    assert MARK not in out, out


def test_an_edited_section_on_a_landed_branch_is_asked(landed):
    _record(landed, B1_DOC, _key(HEADING))
    doc = landed / B1_DOC
    doc.write_text(doc.read_text().replace("export dialog", "import dialog"))
    out = _smoke(landed, "B1")
    assert _signals(out) == 1 and _mark(_blocks(out)[B1_DOC]), out


def test_without_a_recorded_head_the_branch_is_asked_unmarked(squashed):
    """Control: no recorded head, so step 0b says NOT LANDED."""
    w, _ = squashed
    _doc(w, "B1")
    out = _smoke(w, "B1")
    assert _signals(out) == 1 and _sources(out) == [B1_DOC] and MARK not in out, out


def test_a_tip_past_the_recorded_head_is_asked_unmarked(landed):
    git(landed, "checkout", "-q", "B1")
    (landed / "more.txt").write_text("more\n")
    git(landed, "add", "more.txt")
    git(landed, "commit", "-qm", "feat: more")
    git(landed, "checkout", "-q", "main")
    out = _smoke(landed, "B1")
    assert _signals(out) == 1 and MARK not in out, out


def test_a_mixed_run_marks_only_the_landed_branchs_signal(landed):
    _doc(landed, "B2", ids=("T2",))
    out = _smoke(landed, "B1", "B2")
    blocks = _blocks(out)
    assert _signals(out) == 2 and set(blocks) == {B1_DOC, "sysop/runtime/pending-docs/B2.md"}, out
    assert _mark(blocks[B1_DOC]) and not _mark(blocks["sysop/runtime/pending-docs/B2.md"]), out


def test_a_branch_that_lands_at_its_first_close_is_still_asked(landed):
    """A claim with no commits of its own, cut before the close that squashed PR #1, whose doc was
    written straight into main: step 0b calls it landed though no close ever asked it."""
    (landed / B1_DOC).unlink()
    _doc(landed, "B3", ids=("T3",), body="## Before merge\n1. Rotate the key.\n")
    out = _smoke(landed, "B3")
    block = _blocks(out)["sysop/runtime/pending-docs/B3.md"]
    assert _signals(out) == 1 and _mark(block), out


def _declare(w: Path, task: str) -> None:
    idx = w / "tasks/index.yml"
    idx.write_text(idx.read_text().replace(f"  - id: {task}\n",
                                           f"  - id: {task}\n    manual_smoke: true\n"))


def test_a_landed_branchs_declared_task_is_asked_and_marked(landed):
    _declare(landed, "T1")
    _lock(landed, "T1", "B1")
    _doc(landed, "B1", body="no procedure here\n")
    out = _smoke(landed, "B1")
    assert _signals(out) == 1, out
    assert _mark(_blocks(out)["tasks/index.yml § T1"]), out


def test_a_frontmatter_declaration_on_a_landed_branch_is_asked_and_marked(landed):
    _doc(landed, "B1", extra="manual_smoke: true\n", body="no procedure\n")
    out = _smoke(landed, "B1")
    assert _signals(out) == 1 and _mark(_blocks(out)[B1_DOC]), out


def test_a_branch_landed_in_the_default_branch_is_marked(squashed):
    """`LANDED: in <ref>`: no recorded head, the tip is in local main, and the doc that close
    held carries `held_since:`."""
    w, _ = squashed
    git(w, "branch", "B4", "main")
    _doc(w, "B4", ids=("T3",), extra="held_since: 2026-11-01\n")
    out = _smoke(w, "B4")
    (line,) = _mark(_blocks(out)["sysop/runtime/pending-docs/B4.md"])
    assert line.startswith(MARK + "in main — "), line


def test_a_landed_check_that_cannot_run_asks_unmarked_and_says_why(landed, tmp_path):
    """With no `feature_branch.py` beside the script, nothing is landed."""
    alone = tmp_path / "alone"
    alone.mkdir()
    shutil.copy(SMOKE_SCRIPT, alone / "smoke_detect.py")
    out = _smoke(landed, "B1", script=str(alone / "smoke_detect.py"))
    assert _signals(out) == 1 and MARK not in out, out
    (line,) = _lines(out, "LANDED CHECK:")
    assert "`B1`" in line and "asked" in line, line


@pytest.mark.parametrize("stub, why", [
    ("import sys\nprint('LANDED: PR #1 — held doc B1.md')\nsys.exit(2)\n", "exit 2"),
    ("print('Traceback (most recent call last):')\n", "unrecognised output"),
])
def test_a_landed_check_that_fails_asks_unmarked_and_says_why(landed, tmp_path, stub, why):
    """A non-zero exit, even with a LANDED line, or output that is neither verdict, lands
    nothing, and the gate names the branch and the reason."""
    alone = tmp_path / "stubbed"
    alone.mkdir()
    shutil.copy(SMOKE_SCRIPT, alone / "smoke_detect.py")
    (alone / "feature_branch.py").write_text(stub, encoding="utf-8")
    out = _smoke(landed, "B1", script=str(alone / "smoke_detect.py"))
    assert _signals(out) == 1 and MARK not in out, out
    (line,) = _lines(out, "LANDED CHECK:")
    assert line.startswith(f"LANDED CHECK: not read for `B1` ({why}"), line


def test_an_unapproved_landed_branch_is_still_read_as_held(landed):
    """Unchanged: a doc whose branch is not in the run is not merging, and is asked with its
    NOT MERGING line; the landed check runs only for approved branches."""
    out = _smoke(landed)
    assert _signals(out) == 1 and _lines(out, "NOT MERGING:") and MARK not in out, out


def test_a_section_the_doc_asks_is_not_asked_again_from_its_own_branchs_body(landed):
    idx = landed / "tasks/index.yml"
    idx.write_text(idx.read_text().replace("  - id: T1\n", "  - id: T1\n    body: open/T1.md\n"))
    (landed / "tasks/open").mkdir(parents=True, exist_ok=True)
    (landed / "tasks/open/T1.md").write_text("# T1\n\n" + HEADING, encoding="utf-8")
    _lock(landed, "T1", "B1")
    out = _smoke(landed, "B1")
    assert _signals(out) == 1 and _sources(out) == [B1_DOC], out


# ── the unsafe direction: a task merging elsewhere is asked there, unmarked ──

def _body_on(w: Path, branch: str, task: str, text: str) -> None:
    """`task`'s body, committed on `branch`, and `body:` in main's working index."""
    git(w, "checkout", "-q", branch)
    (w / "tasks/open").mkdir(parents=True, exist_ok=True)
    (w / f"tasks/open/{task}.md").write_text(text, encoding="utf-8")
    git(w, "add", f"tasks/open/{task}.md")
    git(w, "commit", "-qm", f"body {task}")
    git(w, "checkout", "-q", "main")
    idx = w / "tasks/index.yml"
    idx.write_text(idx.read_text().replace(f"  - id: {task}\n", f"  - id: {task}\n    body: open/{task}.md\n"))


def _unmarked_on(out: str, src: str, branch: str | None) -> None:
    block = _blocks(out)[src]
    assert not _mark(block), out
    if branch:
        assert f"BRANCH: {branch}" in block, out
    else:
        assert not any(ln.startswith("BRANCH: ") for ln in block), out


@pytest.mark.parametrize("lock_on", ["B1", "B2"])
def test_a_task_a_merging_branch_also_links_is_asked_there(landed, lock_on):
    _declare(landed, "T1")
    _lock(landed, "T1", lock_on)
    _doc(landed, "B2", ids=("T1",), body="nothing\n")
    _unmarked_on(_smoke(landed, "B1", "B2"), "tasks/index.yml § T1", "B2")


@pytest.mark.parametrize("linked_by", ["lock", "doc"])
@pytest.mark.parametrize("longer", [False, True])
def test_a_merging_tasks_section_matching_a_landed_docs_is_asked_unmarked(landed, linked_by, longer):
    """A landed doc's section hides the same text on its own branch only."""
    if longer:
        _doc(landed, "B1", body=HEADING + "2. Then check the CSV.\n")
    _body_on(landed, "B2", "T2", "# T2\n\n" + HEADING)
    if linked_by == "lock":
        _lock(landed, "T2", "B2")
    else:
        _doc(landed, "B2", ids=("T2",), body="nothing\n")
    out = _smoke(landed, "B1", "B2")
    _unmarked_on(out, "tasks/index.yml § T2", "B2")


def test_a_reclaimed_task_on_a_merging_branch_is_asked_unmarked(landed):
    """T1 is linked by B1's held doc and re-claimed by a lock on B2, which carries its body."""
    _body_on(landed, "B2", "T1", "# T1\n\n" + HEADING)
    _declare(landed, "T1")
    _lock(landed, "T1", "B2")
    _unmarked_on(_smoke(landed, "B1", "B2"), "tasks/index.yml § T1", "B2")


def test_a_default_branch_doc_keeps_a_landed_branchs_task_merging(landed):
    """A `branch: main` doc is never approved and its work lands with this close, so a task it
    links is asked unmarked, and an answer recorded on the landed branch does not cover it."""
    _declare(landed, "T1")
    _doc(landed, "B1", body="nothing\n")
    (landed / "sysop/runtime/pending-docs/main.md").write_text(
        "---\nbranch: main\nroadmap_ids: [T1]\n---\n# S\n", encoding="utf-8")
    first = _smoke(landed, "B1")
    _unmarked_on(first, "tasks/index.yml § T1", None)
    (key_line,) = [ln for ln in _blocks(first)["tasks/index.yml § T1"] if ln.startswith("KEY: ")]
    _record(landed, B1_DOC, key_line.split()[1])   # the same section, answered on B1
    _unmarked_on(_smoke(landed, "B1"), "tasks/index.yml § T1", None)


# ── round 2: the carrier of a rerouted task, an undeclared one, and the placeholder key ──

@pytest.mark.parametrize("hold", ["", "hold: waiting\n"])
@pytest.mark.parametrize("linked_by", ["lock", "doc"])
def test_a_not_merging_docs_answer_does_not_cover_a_task_a_default_branch_doc_merges(landed, hold, linked_by):
    """A doc on an unapproved branch (held or not) sorts before the `branch: main` doc and holds
    a recorded answer for the task's section; the task merges with this close, so it is asked."""
    _body_on(landed, "main", "T1", "# T1\n\n## Before merge\n1. Rotate the key.\n")
    _declare(landed, "T1")
    if linked_by == "lock":
        _lock(landed, "T1", "B1")
    _doc(landed, "B1", ids=("T1",) if linked_by == "doc" else ("T9",), body="nothing\n")
    pd = landed / "sysop/runtime/pending-docs"
    sec = "## Before merge\n1. Rotate the key.\n"
    (pd / "a-x.md").write_text(f"---\nbranch: X\nroadmap_ids: [T1]\n{hold}---\n# S\n", encoding="utf-8")
    _record(landed, "sysop/runtime/pending-docs/a-x.md", _key(sec))
    (pd / "b-open.md").write_text("---\nbranch: main\nroadmap_ids: [T1]\n---\n# S\n", encoding="utf-8")
    out = _smoke(landed, "B1")
    assert "PREVIOUSLY ANSWERED" not in out, out
    _unmarked_on(out, "tasks/index.yml § T1", None)
    assert any(ln.endswith("(record in sysop/runtime/pending-docs/b-open.md)")
               for ln in _blocks(out)["tasks/index.yml § T1"]), out


def test_an_undeclared_task_a_default_branch_doc_merges_is_asked(landed):
    """No `manual_smoke:`; the body's heading alone signals. The landed doc's recorded answer for
    the same section does not cover it, because the `branch: main` doc's work merges now."""
    sec = "## Before merge\n1. Rotate the key.\n"
    _body_on(landed, "main", "T1", "# T1\n\n" + sec)
    _doc(landed, "B1", body="nothing\n")
    _record(landed, B1_DOC, _key(sec))
    (landed / "sysop/runtime/pending-docs/c-open.md").write_text(
        "---\nbranch: main\nroadmap_ids: [T1]\n---\n# S\n", encoding="utf-8")
    out = _smoke(landed, "B1")
    assert "PREVIOUSLY ANSWERED" not in out, out
    _unmarked_on(out, "tasks/index.yml § T1", None)


def test_one_tasks_placeholder_answer_does_not_cover_another_tasks(landed):
    """Two declared tasks with no `body:` on one landed doc: an answer to one is not the other's."""
    _declare(landed, "T1")
    _declare(landed, "T3")
    _doc(landed, "B1", ids=("T1", "T3"), body="nothing\n")
    first = _smoke(landed, "B1")
    blocks = _blocks(first)
    assert set(blocks) >= {"tasks/index.yml § T1", "tasks/index.yml § T3"}, first
    (key_line,) = [ln for ln in blocks["tasks/index.yml § T1"] if ln.startswith("KEY: ")]
    _record(landed, B1_DOC, key_line.split()[1])
    out = _smoke(landed, "B1")
    assert _sources(out) == ["tasks/index.yml § T3"], out
    assert len(_lines(out, "PREVIOUSLY ANSWERED: tasks/index.yml § T1")) == 1, out


# ── Q-785: every merging tip is read, and a landed one is never added to them ──

def test_a_landed_link_is_never_read_beside_a_merging_one(squashed):
    """B2 (merging) and B4 (landed in main) both link T2. Only B4's tip holds the body, with an
    answer recorded on B4's doc. B2's merge is what lands now, so B4 is not read beside it: its
    answer would cover B2's work. The body is read from the working tree and asked, unmarked."""
    w, _ = squashed
    _body_on(w, "main", "T2", "# T2\n\n" + HEADING)
    git(w, "branch", "B4", "main")
    _doc(w, "B4", ids=("T2",), extra="held_since: 2026-11-01\n", body="nothing\n")
    _record(w, "sysop/runtime/pending-docs/B4.md", _key(HEADING))
    _doc(w, "B2", ids=("T2",), body="nothing\n")
    out = _smoke(w, "B2", "B4")
    assert "PREVIOUSLY ANSWERED: tasks/index.yml" not in out, out
    _unmarked_on(out, "tasks/index.yml § T2", "B2")


@pytest.mark.parametrize("answered_in", ["B5", "B4"])
def test_a_landed_signal_takes_its_own_branchs_recorded_answer(squashed, answered_in):
    """Round 1's MEDIUM: B4 and B5 both landed in main and both link T2; a lock puts T2 on B5. The
    signal is B5's, so it is carried by B5's doc: an answer there is honoured, and one in B4's doc
    (which used to carry it by sorting first) is not, so the signal is asked, marked."""
    w, _ = squashed
    _body_on(w, "main", "T2", "# T2\n\n" + HEADING)
    for b in ("B4", "B5"):
        git(w, "branch", b, "main")
        _doc(w, b, ids=("T2",), extra="held_since: 2026-11-01\n", body="nothing\n")
    _lock(w, "T2", "B5")
    _record(w, f"sysop/runtime/pending-docs/{answered_in}.md", _key(HEADING))
    out = _smoke(w, "B4", "B5")
    if answered_in == "B5":
        assert out.splitlines()[0] == "NO_SMOKE_REQUIRED", out
        (line,) = _lines(out, "PREVIOUSLY ANSWERED: tasks/index.yml § T2")
        assert "recorded in sysop/runtime/pending-docs/B5.md" in line, out
    else:
        block = _blocks(out)["tasks/index.yml § T2"]
        assert _mark(block) and "BRANCH: B5" in block, out
        assert any(ln.endswith("(record in sysop/runtime/pending-docs/B5.md)") for ln in block), out
