"""`/sitrep` and a pending-doc the branch has outgrown (`Q-617`, Phase 347).

`/sitrep` routed a task to `/review-close` whenever a `Doc-Work:` trailer and a
pending-doc existed, without comparing the doc's `branch_tip:` to the branch. Any
commit after `/document-work` (a human fix, an option-B `/claim-task --resume`)
left the doc stale, and `/review-close` Step 3b then refused it (exit 6) — the
survey sent the operator to the one command that would stop.

What is pinned here:

* **Decision parity with the close.** `_pending_doc_drift` and Step 3b's
  `staleness()` are driven over the same frontmatter shapes, in real repositories,
  and must agree three ways: stale, current, or unknown. The close's heredoc is
  run as extracted from the shipped skill, by `test_pending_doc_integrity`'s own
  extractor, so a change to the close reddens this module.
* **Where the count runs.** A `--clone` claim's commits live in the clone; the
  count runs in the workspace the doc was found in, as `staleness(where=...)` does.
* **Routing.** The state has an arm in both routing tables, sits right after
  `code committed, docs pending`, and fails open to today's routing with a note.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import sitrep_survey as ss
from test_pending_doc_integrity import _heredocs, _Sub

# Step 3b's collect, as the step runs it: the shipped script's subcommand (Phase 386).
COLLECT_ARGV = _Sub("collect").argv

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
SKILL_MD = REPO_ROOT / "core" / "skills" / "sitrep" / "SKILL.md"
STALE = "pending doc stale"
BRANCH = "feat/x"
CUTOFF = datetime(2026, 5, 23, tzinfo=timezone.utc)


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    return env


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True, env=_env()).stdout.strip()


def _commit(cwd: Path, name: str, body: str = "") -> str:
    (cwd / name).write_text(name, encoding="utf-8")
    _git(cwd, "add", "-A")
    args = ["commit", "-qm", f"change {name}"] + (["-m", body] if body else [])
    _git(cwd, *args)
    return _git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> dict:
    """A main checkout and a linked worktree on `feat/x` with two commits:
    `doc_tip` (the one the doc was written against) and `head` (one after it)."""
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    (main / ".gitignore").write_text("sysop/runtime/\n", encoding="utf-8")
    _commit(main, "base.txt")
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "-b", BRANCH, str(wt))
    doc_tip = _commit(wt, "a.txt", "Doc-Work: FEAT-1")
    head = _commit(wt, "b.txt")
    return {"main": main, "wt": wt, "doc_tip": doc_tip, "head": head}


def _write_doc(ws: Path, tip_line: str | None, *, raw: str | None = None) -> Path:
    doc = ws / "sysop" / "runtime" / "pending-docs" / "feat-x.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    if raw is None:
        fm = f"---\nbranch: {BRANCH}\n"
        if tip_line is not None:
            fm += tip_line + "\n"
        raw = fm + 'type: feature\nroadmap_ids: [FEAT-1]\nsummary: "s"\n---\n'
    doc.write_text(raw, encoding="utf-8")
    return doc


def _close_verdict(main: Path, wt: Path, tmp_path: Path) -> str:
    """What `/review-close` Step 3b's collect says about the doc: stale / unknown / current."""
    r = subprocess.run([sys.executable, *COLLECT_ARGV, str(wt), BRANCH], cwd=main,
                       capture_output=True, text=True, env=_env())
    if "PENDING-DOC STALE:" in r.stdout:
        assert r.returncode == 6, r.stdout + r.stderr
        return "stale"
    assert r.returncode == 0, r.stdout + r.stderr
    return "unknown" if "PENDING-DOC STALENESS UNKNOWN:" in r.stdout else "current"


def _sitrep_verdict(doc: Path) -> str:
    drift = ss._pending_doc_drift(doc, BRANCH)
    if drift.commits is None:
        assert drift.why, "an unknown verdict must say why"
        return "unknown"
    return "stale" if drift.commits else "current"


# Each shape: (id, the `branch_tip:` line with {tip}/{head}/{short} filled in, verdict).
SHAPES = [
    ("absent", None, "unknown"),
    ("yaml-int", "branch_tip: 1234567", "unknown"),
    ("yaml-bool", "branch_tip: true", "unknown"),
    ("yaml-null", "branch_tip: null", "unknown"),
    ("empty-string", "branch_tip: ''", "unknown"),
    ("placeholder", "branch_tip: <full 40-char SHA>", "unknown"),
    ("not-hex", "branch_tip: not-a-sha", "unknown"),
    ("option-shaped", "branch_tip: '-abcdef1'", "unknown"),
    ("too-short", "branch_tip: abcdef", "unknown"),
    ("unresolvable", "branch_tip: abcdef0abcdef0", "unknown"),
    ("current", "branch_tip: {head}", "current"),
    ("current-quoted-padded", "branch_tip: '  {head}  '", "current"),
    ("stale", "branch_tip: {tip}", "stale"),
    # Quoted: a 7-hex prefix is all decimal digits about 4% of the time, and YAML
    # then reads it as an int, which both sides call unknown (the row above).
    ("stale-short", "branch_tip: '{short}'", "stale"),
    ("stale-upper", "branch_tip: {upper}", "stale"),
]


@pytest.mark.parametrize("tip_line,expected", [(s[1], s[2]) for s in SHAPES],
                         ids=[s[0] for s in SHAPES])
def test_the_survey_and_the_close_agree_on_every_branch_tip_shape(repo, tmp_path,
                                                                   tip_line, expected):
    if tip_line is not None:
        tip_line = tip_line.format(tip=repo["doc_tip"], head=repo["head"],
                                   short=repo["doc_tip"][:7],
                                   upper=repo["doc_tip"].upper())
    doc = _write_doc(repo["wt"], tip_line)
    assert _close_verdict(repo["main"], repo["wt"], tmp_path) == expected
    assert _sitrep_verdict(doc) == expected


def test_an_undecodable_byte_is_replaced_by_both_not_fatal(repo, tmp_path):
    """The close reads the doc with `errors='replace'`; a strict decode here raised
    UnicodeDecodeError, which no caller catches, out of the whole survey."""
    doc = _write_doc(repo["wt"], f"branch_tip: {repo['doc_tip']}")
    doc.write_bytes(doc.read_bytes().replace(b'summary: "s"', b'summary: "\xff"'))
    assert _close_verdict(repo["main"], repo["wt"], tmp_path) == "stale"
    assert _sitrep_verdict(doc) == "stale"


def test_crlf_frontmatter_is_read_by_both(repo, tmp_path):
    """Both read the doc in universal-newline mode, so CRLF parses in both."""
    raw = f"---\r\nbranch: {BRANCH}\r\nbranch_tip: {repo['doc_tip']}\r\n---\r\n"
    doc = _write_doc(repo["wt"], None, raw=raw)
    assert _close_verdict(repo["main"], repo["wt"], tmp_path) == "stale"
    assert _sitrep_verdict(doc) == "stale"


def test_a_bom_frontmatter_is_read_by_both(repo, tmp_path):
    """Phase 348 gave Step 3b's `fm_re` the BOM tolerance Step 3c's already had, and the
    survey's reader follows it, so a BOM-prefixed doc is measured by both."""
    raw = f"\ufeff---\nbranch: {BRANCH}\nbranch_tip: {repo['doc_tip']}\n---\n"
    doc = _write_doc(repo["wt"], None, raw=raw)
    assert _close_verdict(repo["main"], repo["wt"], tmp_path) == "stale"
    assert _sitrep_verdict(doc) == "stale"


@pytest.mark.parametrize("raw", [
    "no frontmatter at all\n",
    "---\nbranch: feat/x\nbranch_tip: [unclosed\n---\n",
], ids=["no-frontmatter", "broken-yaml"])
def test_a_doc_the_close_cannot_read_is_unknown_not_stale(repo, tmp_path, raw):
    """A doc with no frontmatter, or one whose frontmatter will not parse, claims no
    branch: the close refuses both as a COLLISION (exit 3) before any staleness read. The survey cannot see a collision; its reading must be
    the fail-open one, never `stale`."""
    doc = _write_doc(repo["wt"], None, raw=raw.format(tip=repo["doc_tip"]))
    r = subprocess.run([sys.executable, *COLLECT_ARGV, str(repo["wt"]), BRANCH],
                       cwd=repo["main"], capture_output=True, text=True, env=_env())
    assert r.returncode == 3 and "PENDING-DOC COLLISION" in r.stdout, r.stdout + r.stderr
    assert _sitrep_verdict(doc) == "unknown"


def test_a_rebased_branch_whose_tip_is_no_longer_an_ancestor_is_stale_in_both(repo, tmp_path):
    """Step 4a rebases; a doc stamped before an amend points at an orphan, and
    `rev-list tip..branch` counts the whole rewritten branch."""
    doc = _write_doc(repo["wt"], f"branch_tip: {repo['head']}")
    _git(repo["wt"], "commit", "-q", "--amend", "-m", "amended")
    assert _close_verdict(repo["main"], repo["wt"], tmp_path) == "stale"
    assert _sitrep_verdict(doc) == "stale"


# ── where the count runs ──────────────────────────────────────────────────


@pytest.fixture
def clone_repo(tmp_path: Path) -> dict:
    """The `--clone` shape: the main checkout's local `feat/x` holds the Doc-Work'd
    commit (as after a fetch from the clone), and the clone has one more."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    (main / ".gitignore").write_text("sysop/runtime/\n", encoding="utf-8")
    _commit(main, "base.txt")
    _git(main, "remote", "add", "origin", str(origin))
    _git(main, "push", "-q", "origin", "main")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    _git(clone, "checkout", "-q", "-b", BRANCH)
    doc_tip = _commit(clone, "a.txt", "Doc-Work: FEAT-1")
    _git(main, "fetch", "-q", str(clone), f"{BRANCH}:{BRANCH}")
    head = _commit(clone, "b.txt")
    return {"main": main, "clone": clone, "doc_tip": doc_tip, "head": head}


def test_a_clone_claims_count_runs_in_the_clone(clone_repo, tmp_path):
    main, clone = clone_repo["main"], clone_repo["clone"]
    doc = _write_doc(clone, f"branch_tip: {clone_repo['doc_tip']}")
    # Precondition: the two repositories disagree, which is what makes the choice matter.
    assert _git(main, "rev-list", "--count", f"{clone_repo['doc_tip']}..{BRANCH}") == "0"
    assert _git(clone, "rev-list", "--count", f"{clone_repo['doc_tip']}..{BRANCH}") == "1"
    assert _close_verdict(main, clone, tmp_path) == "stale"
    assert _sitrep_verdict(doc) == "stale"


def test_the_clone_doc_is_found_through_the_locks_workspace_and_classified_stale(clone_repo):
    """End to end through `_pending_doc_for`'s arm (ii) and `_classify_task`."""
    main, clone = clone_repo["main"], clone_repo["clone"]
    _write_doc(clone, f"branch_tip: {clone_repo['doc_tip']}")
    lock = ss.Lock(task_id="FEAT-1", path=main / "x.lock", branch=BRANCH,
                   workspace=str(clone))
    doc = ss._pending_doc_for(main, BRANCH, lock, None)
    assert doc is not None and clone in doc.parents, doc
    ts = _classify(main, doc)
    assert ts.state == STALE, (ts.state, ts.notes)
    assert ts.next_action == "/document-work FEAT-1"


def test_a_doc_on_main_is_counted_in_main(clone_repo):
    """`_pending_doc_for`'s last arm is the main checkout; the close measures main's
    own docs `where=Path.cwd()`, which is main. There main's ref is current."""
    main = clone_repo["main"]
    doc = _write_doc(main, f"branch_tip: {clone_repo['doc_tip']}")
    assert _sitrep_verdict(doc) == "current"


def test_an_inherited_git_dir_does_not_move_the_count(clone_repo, monkeypatch):
    """Hermetic: `GIT_DIR` from a hook's environment overrides `cwd`. With it
    pointing at main, an unstripped read would answer main's 0 for the clone's doc."""
    doc = _write_doc(clone_repo["clone"], f"branch_tip: {clone_repo['doc_tip']}")
    monkeypatch.setenv("GIT_DIR", str(clone_repo["main"] / ".git"))
    assert _sitrep_verdict(doc) == "stale"


@pytest.mark.parametrize("var", ["GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"])
def test_the_other_inherited_git_variables_do_not_move_the_count(clone_repo, monkeypatch, var):
    """Phase 347's round (lens 1, L05): stripping only `GIT_DIR` survived every test."""
    doc = _write_doc(clone_repo["clone"], f"branch_tip: {clone_repo['doc_tip']}")
    target = {"GIT_COMMON_DIR": clone_repo["main"] / ".git", "GIT_WORK_TREE": clone_repo["main"],
              "GIT_INDEX_FILE": clone_repo["main"] / ".git" / "index"}[var]
    monkeypatch.setenv(var, str(target))
    assert _sitrep_verdict(doc) == "stale"


# ── classification and routing ────────────────────────────────────────────


def _classify(main: Path, doc: Path | None, *, unpushed: int = 0):
    commit = ss.Commit(sha="abc", subject="feat: x",
                       author_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
                       doc_work_ids=["FEAT-1"], subject_task_id=None)
    return ss._classify_task(
        task_id="FEAT-1", lock=None, worktree=None, branch=BRANCH,
        index_entry={"status": "in_progress"}, commits=[commit], unpushed=unpushed,
        dirty=False, stale_days=7, phase40_cutoff=CUTOFF, pending_doc=doc,
        main_root=main,
    )


def test_a_stale_doc_routes_to_document_work_whether_or_not_pushed(repo):
    doc = _write_doc(repo["wt"], f"branch_tip: {repo['doc_tip']}")
    for unpushed in (0, 3):
        ts = _classify(repo["main"], doc, unpushed=unpushed)
        assert ts.state == STALE, ts.state
        assert ts.next_action == "/document-work FEAT-1"
        assert any("1 commit(s) landed on feat/x" in n and repo["doc_tip"][:12] in n
                   for n in ts.notes), ts.notes
        assert ts.pending_doc is True


def test_a_current_doc_keeps_both_close_states(repo):
    doc = _write_doc(repo["wt"], f"branch_tip: {repo['head']}")
    assert _classify(repo["main"], doc).state == "ready for /review-close"
    assert _classify(repo["main"], doc, unpushed=2).state == "doc-work done, unpushed"
    assert not any("staleness" in n for n in _classify(repo["main"], doc).notes)


@pytest.mark.parametrize("tip_line,why", [
    (None, "no readable `branch_tip:`"),
    ("branch_tip: 1234567", "not a string"),
    ("branch_tip: <sha>", "placeholder"),
    ("branch_tip: zzzzzzz", "not an object name"),
    ("branch_tip: abcdef0abcdef0", "does not resolve"),
])
def test_unknown_staleness_keeps_todays_routing_and_says_why(repo, tip_line, why):
    doc = _write_doc(repo["wt"], tip_line)
    ts = _classify(repo["main"], doc)
    assert ts.state == "ready for /review-close", ts.state
    assert ts.next_action == "/review-close FEAT-1"
    unknown = [n for n in ts.notes if n.startswith("pending-doc staleness unknown:")]
    assert len(unknown) == 1 and why in unknown[0], ts.notes


def test_one_rev_list_per_task_and_none_for_an_unusable_tip(repo, monkeypatch):
    calls = []
    real = ss._git

    def counting(args, *a, **k):
        calls.append(list(args))
        return real(args, *a, **k)

    monkeypatch.setattr(ss, "_git", counting)
    doc = _write_doc(repo["wt"], f"branch_tip: {repo['doc_tip']}")
    ss._pending_doc_drift(doc, BRANCH)
    assert calls == [["rev-list", "--count", f"{repo['doc_tip']}..{BRANCH}"]], calls
    calls.clear()
    ss._pending_doc_drift(_write_doc(repo["wt"], "branch_tip: <sha>"), BRANCH)
    assert calls == [], calls


def _task(state: str, tid: str = "FEAT-1") -> ss.TaskState:
    return ss.TaskState(task_id=tid, state=state, branch=f"feat/{tid.lower()}",
                        commits_ahead=2, pending_doc=True, next_action=f"x {tid}")


def _survey(tasks=(), batches=()) -> ss.Survey:
    return ss.Survey(timestamp=datetime(2026, 9, 29, tzinfo=timezone.utc),
                     main_root=Path("/tmp/r"), head_short="abc1234", tasks=list(tasks),
                     review_batches=list(batches), discrepancies=[], stale_days=7,
                     open_roadmap_ids=[])


def test_the_recommendation_is_document_work_with_the_evidence():
    t = _task(STALE)
    t.notes = ["3 commit(s) landed on feat/feat-1 after the pending-doc's branch_tip abc"]
    rec = ss._recommended_next(_survey([t]))
    assert rec.command == "/document-work FEAT-1", rec
    assert "stale" in rec.reason and rec.detail_lines == t.notes


def test_the_rank_sits_right_after_docs_pending_and_above_in_progress():
    stale = _task(STALE, "FEAT-1")
    pending = _task("code committed, docs pending", "FEAT-2")
    live = _task("in progress", "FEAT-3")
    ready = _task("ready for /review-close", "FEAT-4")
    assert "FEAT-2" in ss._recommended_next(_survey([stale, pending])).command
    assert "FEAT-1" in ss._recommended_next(_survey([live, stale])).command
    assert "FEAT-4" in ss._recommended_next(_survey([stale, ready])).command
    order = ss._suggested_order(_survey([live, stale, pending, ready]))
    idx = {tid: next(i for i, line in enumerate(order) if tid in line)
           for tid in ("FEAT-1", "FEAT-2", "FEAT-3", "FEAT-4")}
    assert idx["FEAT-4"] < idx["FEAT-2"] < idx["FEAT-1"] < idx["FEAT-3"], order
    assert "/document-work FEAT-1" in order[idx["FEAT-1"]]


def test_the_routing_row_is_4f_and_names_document_work():
    text = SKILL_MD.read_text(encoding="utf-8")
    start = text.index("| Priority | State")
    rows = [ln for ln in text[start:text.index("\n\n", start)].splitlines()
            if ln.startswith("|")]
    hits = []
    for ln in rows:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[1].replace("`", "") == f"Any task {STALE}":
            hits.append(cells)
    assert len(hits) == 1, rows
    prio, _state, rec, nudge = hits[0]
    assert prio == "4f" and rec.startswith("`/document-work <ID>`") and nudge == "no", hits


# ── end to end, with the real claim writer ───────────────────────────────


def test_end_to_end_a_claim_documented_then_committed_to_routes_to_document_work(tmp_path):
    """`claim_task.sh --lock` builds the worktree and lock as a consumer's would;
    `/sitrep` is run as shipped. Re-stamping `branch_tip:` (what `/document-work`
    does) returns the task to the close states."""
    root = tmp_path / "main"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / ".gitignore").write_text("sysop/runtime/\n", encoding="utf-8")
    scripts = root / "sysop" / "scripts"
    scripts.mkdir(parents=True)
    for p in list(SCRIPTS.glob("*.py")) + list(SCRIPTS.glob("*.sh")):
        (scripts / p.name).write_bytes(p.read_bytes())
    (root / "tasks" / "open").mkdir(parents=True)
    (root / "tasks" / "index.yml").write_text(
        "schema_version: 2\nphases:\n"
        "  - {number: 6, title: P, status: in_progress, current_focus: true}\n"
        "tasks:\n  - {id: FEAT-1, title: T, phase: 6, status: open, effort: Low, "
        "blast_radius: single-module, user_action: false, body: open/FEAT-1.md}\n",
        encoding="utf-8")
    (root / "tasks" / "open" / "FEAT-1.md").write_text("# FEAT-1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    r = subprocess.run(["bash", "sysop/scripts/claim_task.sh", "--lock", "FEAT-1", BRANCH, "a"],
                       cwd=root, capture_output=True, text=True, env=_env())
    assert r.returncode == 0, r.stdout + r.stderr
    lock = (root / "sysop" / "runtime" / "locks" / "FEAT-1.lock").read_text(encoding="utf-8")
    ws = Path(next(ln.partition(":")[2].strip() for ln in lock.splitlines()
                   if ln.partition(":")[0] == "workspace"))
    doc_tip = _commit(ws, "a.txt", "Doc-Work: FEAT-1")
    _write_doc(ws, f"branch_tip: {doc_tip}")

    def survey() -> dict:
        import json
        out = subprocess.run([sys.executable, "sysop/scripts/sitrep_survey.py", "--json"],
                             cwd=root, capture_output=True, text=True, env=_env())
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)

    assert survey()["tasks"][0]["state"] == "doc-work done, unpushed"
    head = _commit(ws, "b.txt")
    got = survey()
    assert got["tasks"][0]["state"] == STALE, got["tasks"]
    assert got["recommended_next"]["command"] == "/document-work FEAT-1"
    _write_doc(ws, f"branch_tip: {head}")
    assert survey()["tasks"][0]["state"] == "doc-work done, unpushed"


# ── the batch path ────────────────────────────────────────────────────────


def _batch_dict(branch: str = BRANCH) -> dict:
    return {"number": 7, "title": "B", "status": "In Progress", "branch": branch,
            "tasks": [{"id": "TASK-1", "checkbox": "x"}]}


def _batch_state(repo: dict, tip_line: str | None) -> ss.ReviewBatchState:
    _git(repo["wt"], "commit", "-q", "--allow-empty", "-m", "docs", "-m", "Doc-Work: TASK-1")
    if tip_line is not None:
        _write_doc(repo["wt"], tip_line.format(tip=repo["doc_tip"],
                                               head=_git(repo["wt"], "rev-parse", "HEAD")))
    lock = ss.Lock(task_id="BATCH-7", path=repo["main"] / "BATCH-7.lock", branch=BRANCH,
                   workspace=str(repo["wt"]))
    wts = [ss.Worktree(path=repo["wt"], branch=BRANCH, head="")]
    return ss._classify_review_batches([_batch_dict()], [lock], wts, repo["main"])[0]


def test_a_batch_whose_every_task_is_documented_but_whose_doc_is_stale(repo):
    rb = _batch_state(repo, "branch_tip: {tip}")
    assert rb.state == STALE, (rb.state, rb.notes)
    assert "/document-work on feat/x" in rb.next_action and "batch 7" in rb.next_action
    assert any("commit(s) landed on feat/x" in n for n in rb.notes), rb.notes


def test_a_batch_with_a_current_doc_or_none_is_still_ready(repo):
    assert _batch_state(repo, "branch_tip: {head}").state == "ready for /review-close"


def test_a_batch_with_no_doc_is_still_ready(repo):
    assert _batch_state(repo, None).state == "ready for /review-close"


def test_a_batch_doc_of_unknown_staleness_is_ready_with_the_reason(repo):
    rb = _batch_state(repo, "branch_tip: <sha>")
    assert rb.state == "ready for /review-close", rb.state
    assert any(n.startswith("pending-doc staleness unknown:") for n in rb.notes), rb.notes


def test_the_batch_twin_ranks_after_the_task_state_and_before_in_progress():
    rb = ss.ReviewBatchState(
        batch_number=7, title="B", md_status="In Progress", branch=BRANCH, has_lock=True,
        has_branch=True, has_flag=False, flag_reason="", total_tasks=1, doc_worked_tasks=1,
        state=STALE, next_action="/document-work on feat/x ..., then /review-close (batch 7)")
    live = _task("in progress", "FEAT-3")
    assert "Batch 7" in ss._recommended_next(_survey([live], [rb])).reason
    assert "FEAT-1" in ss._recommended_next(_survey([_task(STALE)], [rb])).command


# ── the two patterns the parity rests on ─────────────────────────────────────


def _close_pattern(name: str) -> str:
    """`name = re.compile(<literal>, ...)` from the Step 3b collect heredoc — the one that
    defines `staleness()` — as the string the literal denotes."""
    import ast
    import re
    body = next(b for b in _heredocs() if "def staleness(" in b)
    lines = [ln for ln in body.splitlines() if ln.strip().startswith(f"{name} = re.compile(")]
    assert len(lines) == 1, (name, lines)
    call = ast.parse(lines[0].strip().split("#")[0]).body[0].value
    return ast.literal_eval(call.args[0])


def test_the_survey_uses_step_3bs_own_patterns():
    """The shape parity above drives only the tips it lists, and in a SHA-1 repo a 41–64
    hex tip is unknown to both sides whatever either regex says, so narrowing the close's
    `SHA_RE` to 40 survived it (Phase 347's round, lens 3). Pin the constants."""
    assert ss._BRANCH_TIP_RE.pattern == _close_pattern("SHA_RE")
    assert ss._PENDING_DOC_FM_RE.pattern == _close_pattern("fm_re")


# ── round 1's findings ─────────────────────────────────────────────────────


def test_an_impossible_date_in_a_doc_is_unknown_not_a_crash(repo):
    """PyYAML raises ValueError for `date: 2026-09-31`, which is not a YAMLError; it took
    the whole survey down for every task (Phase 347's round, lens 1, HIGH)."""
    doc = _write_doc(repo["wt"], None, raw=f"---\nbranch: {BRANCH}\nbranch_tip: "
                     f"{repo['doc_tip']}\ndate: 2026-09-31\n---\n")
    assert _sitrep_verdict(doc) == "unknown"
    ts = _classify(repo["main"], doc)
    assert ts.state == "ready for /review-close", ts.state


def test_a_branch_claims_doc_in_main_is_not_measured(repo):
    """A `--branch` claim's workspace is the main checkout: the close's Step 0 reports the
    `main-checkout` shape and its Step 3b collect never runs, so the survey must not name a
    refusal that will not happen (Phase 347's round, lens 1, MED)."""
    doc = _write_doc(repo["main"], f"branch_tip: {repo['doc_tip']}")
    lock = ss.Lock(task_id="FEAT-1", path=repo["main"] / "FEAT-1.lock", branch=BRANCH,
                   workspace=str(repo["main"]))
    commit = ss.Commit(sha="abc", subject="feat: x",
                       author_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
                       doc_work_ids=["FEAT-1"], subject_task_id=None)
    ts = ss._classify_task(
        task_id="FEAT-1", lock=lock, worktree=None, branch=BRANCH,
        index_entry={"status": "in_progress"}, commits=[commit], unpushed=0,
        dirty=False, stale_days=7, phase40_cutoff=CUTOFF, pending_doc=doc, main_root=repo["main"])
    assert ts.state == "ready for /review-close", ts.state
    assert any("not measured" in n for n in ts.notes), ts.notes


def test_a_doc_in_main_whose_worktree_was_removed_is_measured(repo):
    """Phase 380 (`Q-664`): a close that parked after Step 3b collected the doc and removed
    the worktree leaves the branch with no workspace, and Step 3b step 0's arm for it now
    applies exit 6's test by hand; the survey follows it. With a worktree it is measured
    too."""
    doc = _write_doc(repo["main"], f"branch_tip: {repo['doc_tip']}")
    _git(repo["main"], "worktree", "remove", str(repo["wt"]))  # the branch stays
    assert not repo["wt"].exists()
    ts = _classify(repo["main"], doc)
    assert ts.state == STALE, (ts.state, ts.notes)
    assert not any("not measured" in n for n in ts.notes), ts.notes
    commit = ss.Commit(sha="abc", subject="feat: x",
                       author_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
                       doc_work_ids=["FEAT-1"], subject_task_id=None)
    ts = ss._classify_task(
        task_id="FEAT-1", lock=None, worktree=ss.Worktree(path=repo["wt"], branch=BRANCH, head=""),
        branch=BRANCH, index_entry={"status": "in_progress"}, commits=[commit], unpushed=0,
        dirty=False, stale_days=7, phase40_cutoff=CUTOFF, pending_doc=doc, main_root=repo["main"])
    assert ts.state == STALE, (ts.state, ts.notes)


def test_a_batch_with_tasks_still_undocumented_is_in_progress_even_with_a_stale_doc(repo):
    """Phase 347's round (lens 1, L10): the stale arm at `done > 0` survived every test."""
    _git(repo["wt"], "commit", "-q", "--allow-empty", "-m", "docs", "-m", "Doc-Work: TASK-1")
    _write_doc(repo["wt"], f"branch_tip: {repo['doc_tip']}")
    lock = ss.Lock(task_id="BATCH-7", path=repo["main"] / "BATCH-7.lock", branch=BRANCH,
                   workspace=str(repo["wt"]))
    two = dict(_batch_dict(), tasks=[{"id": "TASK-1", "checkbox": "x"},
                                     {"id": "TASK-2", "checkbox": " "}])
    rb = ss._classify_review_batches([two], [lock], [ss.Worktree(path=repo["wt"], branch=BRANCH,
                                                                  head="")], repo["main"])[0]
    assert rb.state == "in progress", (rb.state, rb.notes)


def test_a_lockless_branch_checked_out_in_main_is_not_measured(tmp_path):
    """Phase 380's round (lens 3, B1): `claim_task.sh --branch` without `--lock` leaves the
    branch checked out in the main checkout with no lock. Step 0 prints `shape=main-checkout`,
    so the close's hand-applied exit-6 test (gated on `shape=<none>`) does not run, and the
    survey must not call the doc stale either."""
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    (main / ".gitignore").write_text("sysop/runtime/\n", encoding="utf-8")
    _commit(main, "base.txt")
    _git(main, "checkout", "-q", "-b", BRANCH)
    tip = _commit(main, "a.txt", "Doc-Work: FEAT-1")
    _commit(main, "b.txt")
    doc = _write_doc(main, f"branch_tip: {tip}")
    ts = _classify(main, doc)
    assert ts.state == "ready for /review-close", (ts.state, ts.notes)
    assert any("not measured" in n for n in ts.notes), ts.notes


def test_a_branch_claims_unresolved_workspace_is_still_the_main_checkout(repo):
    """Phase 380's round (lens 2, S03): `claim_task.sh` writes `workspace:` unresolved, so the
    main checkout can arrive as `<main>/../<main-name>`; it is still the main checkout."""
    doc = _write_doc(repo["main"], f"branch_tip: {repo['doc_tip']}")
    _git(repo["main"], "worktree", "remove", str(repo["wt"]))
    lock = ss.Lock(task_id="FEAT-1", path=repo["main"] / "FEAT-1.lock", branch=BRANCH,
                   workspace=str(repo["main"] / ".." / repo["main"].name))
    commit = ss.Commit(sha="abc", subject="feat: x",
                       author_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
                       doc_work_ids=["FEAT-1"], subject_task_id=None)
    ts = ss._classify_task(
        task_id="FEAT-1", lock=lock, worktree=None, branch=BRANCH,
        index_entry={"status": "in_progress"}, commits=[commit], unpushed=0,
        dirty=False, stale_days=7, phase40_cutoff=CUTOFF, pending_doc=doc, main_root=repo["main"])
    assert any("not measured" in n for n in ts.notes), (ts.state, ts.notes)
