"""Regression coverage for `/review-close` Step 3c's manual-smoke detection heredoc
(BeanRider ISSUE-0050). The heredoc lives inside `core/skills/review-close/SKILL.md`;
these tests extract its Python body and exercise the worktree-in-place scan + the
worktree-first basename dedup, so the fix — which is otherwise prose with no runtime
surface — has CI coverage. Guards against silent regression to the original bug (the
gate reading an empty main `sysop/runtime/pending-docs/` and returning NO_SMOKE_REQUIRED).
"""
from __future__ import annotations

import re
import subprocess
import sys

import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"


def _extract_smoke_heredoc() -> str:
    """Pull the Step 3c detection heredoc's Python body out of SKILL.md.

    Anchored on the unique invocation line that passes SMOKE_WORKTREE_DIRS and
    APPROVED_BRANCHES as quoted positional args into a `python3 - <<'EOF'` heredoc; body
    runs to the terminating `EOF` line. (Sysop Phase 126 converted the former env-var
    prefix to a positional arg and derives the repo root from CWD, so the runner sets
    `cwd=` and argv, not env. Phase 218 added the second positional arg: the gate reads
    locks for this run's approved branches, because pending-doc frontmatter was not the
    only task linkage and treating it as the only one was a fail-open.)
    """
    text = SKILL.read_text(encoding="utf-8")
    m = re.search(
        r'python3 - "\$SMOKE_WORKTREE_DIRS" "\$APPROVED_BRANCHES" <<\'EOF\'\n', text
    )
    assert m, "could not locate the Step 3c smoke-gate heredoc opener in SKILL.md"
    start = m.end()
    end = text.index("\nEOF\n", start)
    return text[start:end]


SMOKE_SRC = _extract_smoke_heredoc()


def _run(repo: Path, worktree_dirs: list[Path], branches: list[str] | None = None) -> str:
    # Phase 126: repo root is CWD, worktree-dir list is argv[1] (was REPO_ROOT /
    # SMOKE_WORKTREE_DIRS env vars). `cwd=repo` mirrors "run the heredoc from the repo root".
    # Phase 218: argv[2] is this run's approved branch names, one per line.
    smoke_arg = "\n".join(str(d) for d in worktree_dirs)
    branch_arg = "\n".join(branches or [])
    r = subprocess.run(
        [sys.executable, "-c", SMOKE_SRC, smoke_arg, branch_arg],
        capture_output=True,
        text=True,
        cwd=str(repo),
        timeout=30,
    )
    assert r.returncode == 0, f"smoke-gate heredoc errored ({r.returncode}):\n{r.stderr}"
    return r.stdout


def _seed_main(tmp_path: Path) -> Path:
    main = tmp_path / "main"
    (main / "tasks").mkdir(parents=True)
    (main / "tasks" / "index.yml").write_text("schema_version: 1\ntasks: []\n", encoding="utf-8")
    (main / "sysop/runtime/pending-docs").mkdir(parents=True)
    return main


def _write_pending(dir_: Path, name: str, *, with_heading: bool) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    body = "---\nbranch: feat/x\nroadmap_ids: [FEAT-X]\ntype: feature\n---\n# Summary\n"
    if with_heading:
        body += "\n## Manual smoke required\n1. Drive the browser flow.\n"
    (dir_ / name).write_text(body, encoding="utf-8")


def test_worktree_authored_smoke_doc_is_detected(tmp_path):
    """The ISSUE-0050 fix: a smoke doc that lives only in the worktree (main's
    `sysop/runtime/pending-docs/` empty) must still trip the gate."""
    main = _seed_main(tmp_path)
    wt = tmp_path / "wt"
    _write_pending(wt / "sysop/runtime/pending-docs", "feat-x.md", with_heading=True)

    out = _run(main, [wt])
    assert out.startswith("SMOKE_REQUIRED"), out
    assert "Manual smoke required" in out


def test_empty_worktree_set_and_empty_main_is_no_smoke(tmp_path):
    """No worktree dirs + empty main → NO_SMOKE_REQUIRED (correctly scoped, not blind)."""
    main = _seed_main(tmp_path)
    out = _run(main, [])
    assert out.strip() == "NO_SMOKE_REQUIRED", out


def test_main_authored_doc_still_detected(tmp_path):
    """Non-worktree flow (doc authored directly on main) is unaffected."""
    main = _seed_main(tmp_path)
    _write_pending(main / "sysop/runtime/pending-docs", "feat-x.md", with_heading=True)
    out = _run(main, [])
    assert out.startswith("SMOKE_REQUIRED"), out


def test_fresh_worktree_doc_not_shadowed_by_stale_main_copy(tmp_path):
    """A#3 dedup guard: a stale main copy WITHOUT the heading must not shadow the
    fresher worktree copy WITH the heading. Worktree-first ordering makes the worktree
    win the basename dedup; main-first ordering (the bug) would miss the signal."""
    main = _seed_main(tmp_path)
    _write_pending(main / "sysop/runtime/pending-docs", "feat-x.md", with_heading=False)  # stale
    wt = tmp_path / "wt"
    _write_pending(wt / "sysop/runtime/pending-docs", "feat-x.md", with_heading=True)     # fresh

    out = _run(main, [wt])
    assert out.startswith("SMOKE_REQUIRED"), (
        f"stale main copy shadowed the fresh worktree doc (dedup ordering regressed):\n{out}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 218 (GDP ISSUE-0095, upstream #455) — the gate matched two exact phrases,
# so a pending doc headed `OPERATOR ACTION REQUIRED BEFORE MERGE` scored
# NO_SMOKE_REQUIRED and the close proceeded without ever asking a human.
#
# Every assertion below is PER CASE, not per run: each names the exact signal count
# and the exact source label it expects. "At least one signal" is satisfied by the
# wrong signal, which is how seven rule-narrowing mutations walked through Phase 217's
# fixture proof.
# ─────────────────────────────────────────────────────────────────────────────

IDX_EMPTY = "schema_version: 1\ntasks: []\n"


def _idx(*, manual_smoke=True, body="open/FEAT-X.md", tid="FEAT-X"):
    line = f"    body: {body}\n" if body is not None else ""
    ms = "    manual_smoke: true\n" if manual_smoke else ""
    return (f"schema_version: 1\ntasks:\n  - id: {tid}\n    status: in_progress\n"
            f"{line}{ms}")


def _seed(tmp_path, *, index_yml=IDX_EMPTY, pending=None, bodies=None, locks=None):
    """A main checkout with an explicit index, pending-docs, task bodies and locks."""
    main = tmp_path / "main"
    (main / "tasks" / "open").mkdir(parents=True)
    (main / "tasks" / "index.yml").write_text(index_yml, encoding="utf-8")
    (main / "sysop/runtime/pending-docs").mkdir(parents=True)
    for name, body in (pending or {}).items():
        (main / "sysop/runtime/pending-docs" / name).write_text(body, encoding="utf-8")
    for name, body in (bodies or {}).items():
        (main / "tasks/open" / name).write_text(body, encoding="utf-8")
    if locks:
        (main / "sysop/runtime/locks").mkdir(parents=True)
        for name, body in locks.items():
            (main / "sysop/runtime/locks" / name).write_text(body, encoding="utf-8")
    return main


def _doc(*, heading=None, fm_extra="", link=True):
    fm = "---\nbranch: feat/x\n"
    if link:
        fm += "roadmap_ids: [FEAT-X]\n"
    fm += fm_extra + "---\n"
    out = fm + "# Summary\n\nSome prose.\n"
    if heading:
        out += f"\n{heading}\n1. Do the irreversible thing.\n"
    return out


def _signals(out: str) -> int:
    """Exact signal count from the header line — not a substring probe."""
    first = out.strip().splitlines()[0]
    if first == "NO_SMOKE_REQUIRED":
        return 0
    m = re.match(r"SMOKE_REQUIRED: (\d+) signal\(s\)$", first)
    assert m, f"unparseable gate output header: {first!r}"
    return int(m.group(1))


def _sources(out: str) -> list[str]:
    return [ln[len("SOURCE: "):] for ln in out.splitlines() if ln.startswith("SOURCE: ")]


# ── detection breadth: one case per phrase, each asserting exactly one signal ──

# EVERY alternative of EVERY alternation needs a member, or that alternative can be
# narrowed away with this module green — and the lockstep test below compares the two
# patterns only over this corpus, so a gap here is a gap in both directions at once.
# The round demonstrated exactly that: dropping `verify` and `test` from the skill's
# `manual\s+(?:...)` branch produced ZERO corpus disagreements while the two patterns
# genuinely diverged on `## Manual verify the export`.
WIDENED_HEADINGS = [
    "## OPERATOR ACTION REQUIRED BEFORE MERGE",   # the reported case
    "## Operator action",
    "### Human action needed",
    "## Manual smoke required",                    # the two originals must still fire
    "### Manual smoke",                            # schema.md names this form explicitly
    "### Smoke required",
    "## Smoke test",                               # smoke\s+(?:required|test)
    "## Manual verification",                      # manual\s+(?:verification|...)
    "## Manual verify the export",                 # ...|verify
    "## Manual test of the payment flow",          # ...|test
    "#### Manual check",                           # ...|check
    "## Manual step",                              # ...|step
    "## Requires a human",                         # requires?\s+a\s+human
    "## Require a human sign-off",                 # ...the optional `s`
    "## Run this before merge",                    # before\s+merg(?:e|ing)
    "## Run this before merging",                  # ...|ing
    "## Checks prior to merge",                    # prior\s+to\s+merg(?:e|ing)
    "## Checks prior to merging",                  # ...|ing
]


@pytest.mark.parametrize("heading", WIDENED_HEADINGS)
def test_each_accepted_heading_fires_exactly_one_signal(tmp_path, heading):
    main = _seed(tmp_path, pending={"a.md": _doc(heading=heading, link=False)})
    out = _run(main, [])
    assert _signals(out) == 1, f"{heading!r} produced {_signals(out)} signals:\n{out}"
    assert _sources(out) == ["sysop/runtime/pending-docs/a.md"], out
    assert heading in out, f"the matched section body is not reported back:\n{out}"


# ── negative controls: headings that must stay silent ──

SILENT_HEADINGS = [
    "## User ops (do these first)",   # post-merge operator steps — deliberately excluded
    "## Summary",
    "## Test decision",
    "## What changed",
    "## Follow-ups",
    "## Smoking gun",                 # 'smok' substring must not be enough
    "## Manually reviewed",           # 'manual' alone must not be enough
]


@pytest.mark.parametrize("heading", SILENT_HEADINGS)
def test_each_excluded_heading_stays_silent(tmp_path, heading):
    main = _seed(tmp_path, pending={"a.md": _doc(heading=heading, link=False)})
    out = _run(main, [])
    assert _signals(out) == 0, f"{heading!r} should not fire the gate:\n{out}"


def test_user_ops_exclusion_is_deliberate_and_stated():
    """`user_action: true` declares POST-merge operator steps. Firing the pre-merge gate
    on that whole routine class would train the operator to waive wholesale — which is the
    failure ISSUE-0099 names. If someone adds it to the pattern, this says why not to."""
    body = SKILL.read_text(encoding="utf-8")
    assert "`user ops`" in body or "`## User ops (do these first)` is deliberately" in body


# ── structural declaration 1: the pending doc's own frontmatter ──

def test_pending_doc_frontmatter_declaration_fires_without_any_heading(tmp_path):
    main = _seed(tmp_path, pending={"a.md": _doc(heading=None, fm_extra="manual_smoke: true\n",
                                                 link=False)})
    out = _run(main, [])
    assert _signals(out) == 1, out
    assert _sources(out) == ["sysop/runtime/pending-docs/a.md"], out
    assert "frontmatter `manual_smoke: true`" in out, out


def test_pending_doc_frontmatter_declaration_does_not_double_count_a_heading(tmp_path):
    """Declaration AND a matching heading in the same doc is one ask, not two — the
    heading is the procedure the declaration is asking about."""
    main = _seed(tmp_path, pending={"a.md": _doc(heading="## Manual smoke required",
                                                 fm_extra="manual_smoke: true\n", link=False)})
    out = _run(main, [])
    assert _signals(out) == 1, out


def test_pending_doc_frontmatter_false_stays_silent(tmp_path):
    main = _seed(tmp_path, pending={"a.md": _doc(heading=None, fm_extra="manual_smoke: false\n",
                                                 link=False)})
    assert _signals(_run(main, [])) == 0


# ── structural declaration 2: the index entry, and its four dispositions ──

def test_declared_task_with_unmatched_body_heading_now_fires(tmp_path):
    """The declared path used the SAME two-phrase regex, so an explicit
    `manual_smoke: true` was silent whenever the body heading was phrased otherwise."""
    main = _seed(tmp_path, index_yml=_idx(), pending={"a.md": _doc()},
                 bodies={"FEAT-X.md": "# X\n\n## OPERATOR ACTION REQUIRED BEFORE MERGE\n1. Go.\n"})
    out = _run(main, [])
    assert _signals(out) == 1, out
    assert _sources(out) == ["tasks/index.yml § FEAT-X"], out
    assert "OPERATOR ACTION REQUIRED BEFORE MERGE" in out


def test_declared_task_with_no_matching_heading_at_all_fires_a_named_signal(tmp_path):
    """A declaration is the ask; a missing procedure makes the ask louder, not absent."""
    main = _seed(tmp_path, index_yml=_idx(), pending={"a.md": _doc()},
                 bodies={"FEAT-X.md": "# X\n\nJust prose. No headings that match.\n"})
    out = _run(main, [])
    assert _signals(out) == 1, out
    assert _sources(out) == ["tasks/index.yml § FEAT-X"], out
    assert "no procedure heading matched" in out, out


def test_declared_task_with_unreadable_body_fires_a_named_signal(tmp_path):
    main = _seed(tmp_path, index_yml=_idx(body="open/GONE.md"), pending={"a.md": _doc()})
    out = _run(main, [])
    assert _signals(out) == 1, out
    assert "is not \nreadable" in out or "is not readable" in out.replace("\n", " "), out


def test_declared_task_with_no_body_key_fires_a_named_signal(tmp_path):
    main = _seed(tmp_path, index_yml=_idx(body=None), pending={"a.md": _doc()})
    out = _run(main, [])
    assert _signals(out) == 1, out
    assert "no `body:`" in out, out


def test_undeclared_task_with_a_smoke_heading_in_its_body_stays_silent(tmp_path):
    """Only `manual_smoke: true` opts a task body into the scan. A body that happens to
    carry the phrase is not a declaration, or every task body becomes a prompt."""
    main = _seed(tmp_path, index_yml=_idx(manual_smoke=False), pending={"a.md": _doc()},
                 bodies={"FEAT-X.md": "# X\n\n## Manual smoke required\n1. Go.\n"})
    assert _signals(_run(main, [])) == 0


# ── linkage source 2: locks, keyed on THIS run's approved branches ──

LOCK = "task_id: FEAT-X\nstatus: in_progress\nagent: a\nbranch: feat/x\nmode: worktree\n"


def test_lock_linkage_reaches_a_task_no_pending_doc_names(tmp_path):
    """The fully-compliant author — declared the field, wrote the procedure under the
    sanctioned heading — was the one the gate did not protect, because linkage came only
    from pending-doc frontmatter."""
    main = _seed(tmp_path, index_yml=_idx(),
                 pending={"other.md": "---\nbranch: feat/y\nroadmap_ids: [FEAT-Y]\n---\n# S\n"},
                 bodies={"FEAT-X.md": "# X\n\n## Manual smoke required\n1. Go.\n"},
                 locks={"FEAT-X.lock": LOCK})
    out = _run(main, [], branches=["feat/x"])
    assert _signals(out) == 1, out
    assert _sources(out) == ["tasks/index.yml § FEAT-X"], out


def test_lock_for_a_branch_not_in_this_run_is_ignored(tmp_path):
    """A lock is not a licence to prompt about work this close is not merging."""
    main = _seed(tmp_path, index_yml=_idx(),
                 pending={"other.md": "---\nbranch: feat/y\nroadmap_ids: [FEAT-Y]\n---\n# S\n"},
                 bodies={"FEAT-X.md": "# X\n\n## Manual smoke required\n1. Go.\n"},
                 locks={"FEAT-X.lock": LOCK})
    assert _signals(_run(main, [], branches=["feat/zzz"])) == 0


def test_locks_are_not_consulted_when_no_approved_branches_are_passed(tmp_path):
    """A main-only close passes an explicit empty branch list; every lock on the machine
    must stay out of it."""
    main = _seed(tmp_path, index_yml=_idx(),
                 pending={"other.md": "---\nbranch: feat/y\nroadmap_ids: [FEAT-Y]\n---\n# S\n"},
                 bodies={"FEAT-X.md": "# X\n\n## Manual smoke required\n1. Go.\n"},
                 locks={"FEAT-X.lock": LOCK})
    assert _signals(_run(main, [], branches=[])) == 0


def test_lock_and_pending_doc_linkage_do_not_double_count(tmp_path):
    main = _seed(tmp_path, index_yml=_idx(), pending={"a.md": _doc()},
                 bodies={"FEAT-X.md": "# X\n\n## Manual smoke required\n1. Go.\n"},
                 locks={"FEAT-X.lock": LOCK})
    out = _run(main, [], branches=["feat/x"])
    assert _signals(out) == 1, out


def test_a_damaged_lock_does_not_kill_the_close(tmp_path):
    """The gate runs before the merge; a malformed lock must degrade to 'no linkage from
    this lock', never to a traceback that strands the close."""
    main = _seed(tmp_path, index_yml=_idx(), pending={"a.md": _doc(link=False)},
                 bodies={"FEAT-X.md": "# X\n\n## Manual smoke required\n1. Go.\n"},
                 locks={"FEAT-X.lock": "this is not a lock\n", "empty.lock": ""})
    assert _signals(_run(main, [], branches=["feat/x"])) == 0


# ── the two patterns stay in lockstep ──

def test_validator_and_skill_share_one_heading_pattern():
    """validate_tasks.py's warn-only nudge and the gate's detection are documented as
    mirrors: an author who satisfies the validator must satisfy the gate. Compare
    BEHAVIOUR over a corpus, both directions — two regexes can differ textually and
    still agree, and can agree textually in a file and differ after an edit."""
    import validate_tasks as vt   # conftest puts core/companion/scripts on sys.path

    src = SMOKE_SRC
    ns: dict = {}
    exec(compile(src[src.index("heading_re = re.compile("):src.index("fm_re = re.compile(")],
                 "<gate>", "exec"), {"re": re}, ns)
    gate_re = ns["heading_re"]

    for h in WIDENED_HEADINGS + SILENT_HEADINGS:
        assert bool(gate_re.search(h)) == bool(vt._MANUAL_SMOKE_HEADING_RE.search(h)), (
            f"validator and gate disagree on {h!r} — the documented lockstep is broken"
        )
    # and the corpus is not vacuous in either direction
    assert all(gate_re.search(h) for h in WIDENED_HEADINGS), (
        "a heading in the accept corpus does not match — the corpus and the pattern "
        "have drifted apart, so agreement over it proves nothing"
    )
    assert not any(gate_re.search(h) for h in SILENT_HEADINGS)

    # ...and the corpus must exercise every alternative of every alternation, or a
    # sub-branch can be narrowed away with this test green in BOTH directions.
    # Derive the branches from the SOURCE LINES — one `r'|phrase'` per line — not by
    # splitting the concatenated pattern on `|`, which cuts `(?:required|test)` in half.
    import re as _re
    block = SMOKE_SRC[SMOKE_SRC.index("heading_re = re.compile("):
                      SMOKE_SRC.index("fm_re = re.compile(")]
    branches = [m.group(1) for m in _re.finditer(r"r'\|?([^']+)'", block)
                if m.group(1) not in ("^(#{1,6})\\s+.*(", ")")]
    alternatives = []
    for branch in branches:
        g = _re.search(r"\(\?:([^)]*)\)", branch)
        if g:
            alternatives += [branch[:g.start()] + alt + branch[g.end():]
                             for alt in g.group(1).split("|")]
        else:
            alternatives.append(branch)
    assert len(alternatives) >= 12, alternatives      # non-vacuity on the derivation itself
    bodies = [h.lstrip("# ") for h in WIDENED_HEADINGS]
    for alt in alternatives:
        probe = _re.compile(alt, _re.IGNORECASE)
        assert any(probe.search(b) for b in bodies), (
            f"no corpus member exercises the alternative {alt!r} — it can be deleted "
            f"from either pattern and this test stays green"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 218 round, lens 3 — the findings its OWN mutations could not reach.
#
# The first cut of this phase fixed Step 3b's blindness to a `--clone` workspace and
# left Step 3c blind to exactly the same shape, in the same commit. Step 3c runs
# BEFORE Step 3b, so a clone-authored pending doc is in neither main nor the
# worktree list, and the reported heading scored NO_SMOKE_REQUIRED with nothing to
# say so. Reproduced end to end before it was fixed.
#
# The other lesson is a POPULATION one: every worktree case below existed only for
# the (a) heading scan, so both Phase-218 sources could be silently restricted to
# main-only docs with the whole module green.
# ─────────────────────────────────────────────────────────────────────────────

def _clone_workspace(tmp_path: Path, branch: str, dirname: str, doc: str) -> Path:
    """A `claim_task.sh --clone` workspace: a real clone, checked out on `branch`.

    Deliberately a real git checkout, not a directory with a `.git` file faked by hand
    — the arm under test reads `HEAD` and must be exercised against the thing it will
    actually meet."""
    bare = tmp_path / "remote.git"
    if not bare.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        seed = tmp_path / "_seed"
        subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True)
        for a in (["config", "user.email", "t@t"], ["config", "user.name", "T"]):
            subprocess.run(["git", *a], cwd=seed, check=True, capture_output=True)
        (seed / "f.txt").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=seed, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "i"], cwd=seed, check=True, capture_output=True)
        subprocess.run(["git", "push", "-q", "origin", "HEAD:refs/heads/main"],
                       cwd=seed, check=True, capture_output=True)
    seed = tmp_path / "_seed"
    subprocess.run(["git", "branch", "-f", branch, "HEAD"], cwd=seed, check=True,
                   capture_output=True)
    subprocess.run(["git", "push", "-q", "origin", branch], cwd=seed, check=True,
                   capture_output=True)
    ws = tmp_path / dirname
    subprocess.run(["git", "clone", "-q", str(bare), str(ws)], check=True)
    subprocess.run(["git", "checkout", "-q", branch], cwd=ws, check=True, capture_output=True)
    pd = ws / "sysop/runtime/pending-docs"
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "doc.md").write_text(doc, encoding="utf-8")
    return ws


OPERATOR_DOC = ("---\nbranch: feat/x\n---\n# S\n\n"
                "## OPERATOR ACTION REQUIRED BEFORE MERGE\n1. Rotate the prod key.\n")


def test_a_clone_authored_doc_fires_via_the_lock(tmp_path):
    """Step 3c runs BEFORE Step 3b, so Step 3b's collect cannot rescue this."""
    main = tmp_path / "main"
    main.mkdir()
    _clone_workspace(tmp_path, "feat/x", "main-feat-x", OPERATOR_DOC)
    (main / "tasks").mkdir()
    (main / "tasks/index.yml").write_text(IDX_EMPTY, encoding="utf-8")
    (main / "sysop/runtime/pending-docs").mkdir(parents=True)
    lk = main / "sysop/runtime/locks"
    lk.mkdir(parents=True)
    (lk / "FEAT-X.lock").write_text(
        f"task_id: FEAT-X\nbranch: feat/x\nmode: clone\nworkspace: {tmp_path/'main-feat-x'}\n",
        encoding="utf-8")
    out = _run(main, [], branches=["feat/x"])
    assert _signals(out) == 1, out
    assert "OPERATOR ACTION REQUIRED BEFORE MERGE" in out


def test_a_clone_authored_doc_fires_with_no_lock_at_all(tmp_path):
    """`claim_task.sh` defaults to USE_LOCK=false, so the lock arm alone is not enough —
    which is the same reason Step 3b needed its verified-sibling arm."""
    main = tmp_path / "main"
    main.mkdir()
    _clone_workspace(tmp_path, "feat/x", "main-feat-x", OPERATOR_DOC)
    (main / "tasks").mkdir()
    (main / "tasks/index.yml").write_text(IDX_EMPTY, encoding="utf-8")
    (main / "sysop/runtime/pending-docs").mkdir(parents=True)
    assert not (main / "sysop/runtime/locks").exists()
    out = _run(main, [], branches=["feat/x"])
    assert _signals(out) == 1, out


def test_a_sibling_on_another_branch_is_not_scanned(tmp_path):
    """The sibling arm verifies HEAD. Scanning an unrelated checkout would prompt about
    work this close is not merging — the false positive that trains an operator to waive."""
    main = tmp_path / "main"
    main.mkdir()
    _clone_workspace(tmp_path, "feat/other", "main-feat-other", OPERATOR_DOC)
    (main / "tasks").mkdir()
    (main / "tasks/index.yml").write_text(IDX_EMPTY, encoding="utf-8")
    (main / "sysop/runtime/pending-docs").mkdir(parents=True)
    assert _signals(_run(main, [], branches=["feat/x"])) == 0


def test_a_clone_workspace_is_not_double_counted_with_argv1(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    ws = _clone_workspace(tmp_path, "feat/x", "main-feat-x", OPERATOR_DOC)
    (main / "tasks").mkdir()
    (main / "tasks/index.yml").write_text(IDX_EMPTY, encoding="utf-8")
    (main / "sysop/runtime/pending-docs").mkdir(parents=True)
    out = _run(main, [ws], branches=["feat/x"])
    assert _signals(out) == 1, out


# ── the population defect: the NEW sources must be exercised in a worktree too ──

def test_frontmatter_declaration_is_detected_in_a_WORKTREE_authored_doc(tmp_path):
    """Both Phase-218 sources could be restricted to main-only docs with this module
    green, because every worktree fixture only ever exercised the heading scan."""
    main = _seed(tmp_path)
    wt = tmp_path / "wt"
    (wt / "sysop/runtime/pending-docs").mkdir(parents=True)
    (wt / "sysop/runtime/pending-docs/a.md").write_text(
        _doc(heading=None, fm_extra="manual_smoke: true\n", link=False), encoding="utf-8")
    out = _run(main, [wt])
    assert _signals(out) == 1, out
    assert "frontmatter `manual_smoke: true`" in out


def test_index_linkage_is_detected_from_a_WORKTREE_authored_doc(tmp_path):
    main = _seed(tmp_path, index_yml=_idx(),
                 bodies={"FEAT-X.md": "# X\n\n## Manual smoke required\n1. Go.\n"})
    wt = tmp_path / "wt"
    (wt / "sysop/runtime/pending-docs").mkdir(parents=True)
    (wt / "sysop/runtime/pending-docs/a.md").write_text(_doc(), encoding="utf-8")
    out = _run(main, [wt])
    assert _signals(out) == 1, out
    assert _sources(out) == ["tasks/index.yml § FEAT-X"], out


# ── the operator must be shown the PROCEDURE, not just its heading ──

def test_the_signal_carries_the_procedure_body_not_only_the_heading(tmp_path):
    """Step 3c step 2 says "Present the section text verbatim". A guard that only checks
    the heading is in the output cannot tell a full section from a truncated one, and a
    human asked to confirm a smoke they cannot read will waive it."""
    main = _seed(tmp_path, pending={"a.md":
        "---\nbranch: feat/x\n---\n# S\n\n## Manual smoke required\n"
        "1. Rotate the prod key.\n2. Verify the webhook.\n"})
    out = _run(main, [])
    assert _signals(out) == 1, out
    assert "1. Rotate the prod key." in out, out
    assert "2. Verify the webhook." in out, out


def test_a_section_stops_at_the_next_heading_of_equal_or_higher_level(tmp_path):
    """The header-eats-neighbour class this repo has reopened more than once."""
    main = _seed(tmp_path, pending={"a.md":
        "---\nbranch: feat/x\n---\n# S\n\n## Manual smoke required\n1. Do it.\n\n"
        "## Unrelated section\nSHOULD-NOT-APPEAR\n\n### Deeper\nalso-not\n"})
    out = _run(main, [])
    assert _signals(out) == 1, out
    assert "1. Do it." in out
    assert "SHOULD-NOT-APPEAR" not in out, (
        "the section ran past the next same-level heading and swallowed its neighbour"
    )


# ── input shapes an author actually writes, each of which was silently NO_SMOKE ──

def test_a_scalar_roadmap_ids_still_links_the_task(tmp_path):
    """`roadmap_ids: FEAT-X` (no list) iterated its CHARACTERS, so the linkage was lost
    and the declared task was never consulted."""
    main = _seed(tmp_path, index_yml=_idx(),
                 pending={"a.md": "---\nbranch: feat/x\nroadmap_ids: FEAT-X\n---\n# S\n"},
                 bodies={"FEAT-X.md": "# X\n\n## Manual smoke required\n1. Go.\n"})
    out = _run(main, [])
    assert _signals(out) == 1, out
    assert _sources(out) == ["tasks/index.yml § FEAT-X"], out


def test_a_quoted_manual_smoke_true_still_fires(tmp_path):
    """`manual_smoke: "true"` is an author saying *ask me*. `is True` scored it silent."""
    idx = ('schema_version: 1\ntasks:\n  - id: FEAT-X\n    status: in_progress\n'
           '    body: open/FEAT-X.md\n    manual_smoke: "true"\n')
    main = _seed(tmp_path, index_yml=idx, pending={"a.md": _doc()},
                 bodies={"FEAT-X.md": "# X\n\n## Manual smoke required\n1. Go.\n"})
    assert _signals(_run(main, [])) == 1


def test_a_quoted_manual_smoke_false_stays_silent(tmp_path):
    idx = ('schema_version: 1\ntasks:\n  - id: FEAT-X\n    status: in_progress\n'
           '    body: open/FEAT-X.md\n    manual_smoke: "false"\n')
    main = _seed(tmp_path, index_yml=idx, pending={"a.md": _doc()},
                 bodies={"FEAT-X.md": "# X\n\n## Manual smoke required\n1. Go.\n"})
    assert _signals(_run(main, [])) == 0


def test_a_utf8_bom_does_not_hide_the_frontmatter(tmp_path):
    """The `^---` match failed on a BOM, so the structural declaration was invisible."""
    main = _seed(tmp_path)
    (main / "sysop/runtime/pending-docs/a.md").write_text(
        "﻿---\nbranch: feat/x\nmanual_smoke: true\n---\n# S\n", encoding="utf-8")
    assert _signals(_run(main, [])) == 1


def test_a_non_string_id_in_roadmap_ids_does_not_kill_the_close(tmp_path):
    """`roadmap_ids: 5` raised an uncaught TypeError. This gate runs before the merge."""
    main = _seed(tmp_path, index_yml=_idx(),
                 pending={"a.md": "---\nbranch: feat/x\nroadmap_ids: 5\n---\n# S\n"},
                 bodies={"FEAT-X.md": "# X\n\n## Manual smoke required\n1. Go.\n"})
    assert _signals(_run(main, [])) == 0
