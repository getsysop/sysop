"""Phase 351 — which task bodies and which indexes `/review-close` Step 3c reads (`Q-624`,
`Q-626`), and the `BRANCH:` line `Q-627`'s hold option needs.

The detection heredoc is extracted from `core/skills/review-close/SKILL.md` and executed
against real git repositories:

* `Q-624` (upstream #767): a body's procedure heading was read only for a task whose index
  entry set `manual_smoke: true`, so an author who wrote the procedure where the schema says
  to and forgot the flag was never asked. Every task an approved branch links now has its
  tip body scanned. The missing-procedure signals stay flagged-only. A flag set on the
  branch's own `tasks/index.yml` counts too.
* `Q-626` (upstream #768): under `pr` the gate read local `<default branch>`'s index, which
  can be behind `origin`. It now fetches and reads `origin/<default branch>:tasks/index.yml`
  beside it: flagged on either is asked, and origin can release a hold but never add one.

Every remote here is a local bare repository. No fixture names a real URL.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_review_close_smoke_gate import SMOKE_SCRIPT, SMOKE_SRC, _run, _signals, _sources  # noqa: E402
from test_review_close_smoke_held_and_tip import (  # noqa: E402
    _ENV, _field, _git, _index, _task, _tree,
)

PROC = "# X\n\n## Manual smoke required\n1. Drive the export end to end.\n"
NO_HEADING = "# X\n\nPlain notes, no procedure heading.\n"
LOCK = "task_id: FEAT-X\nstatus: in_progress\nagent: a\nbranch: feat/x\nmode: worktree\n"
DOC_X = "---\nbranch: feat/x\nroadmap_ids: [FEAT-X]\n---\n# Summary\n"


def _branch(repo: Path, *, body: str | None = None, index: str | None = None,
            name: str = "feat/x") -> str:
    """Commit `body` (FEAT-X's) and/or `index` on a new branch; return to main."""
    _git(repo, "checkout", "-q", "-b", name)
    if body is not None:
        (repo / "tasks/open/FEAT-X.md").write_text(body, encoding="utf-8")
    if index is not None:
        (repo / "tasks/index.yml").write_text(index, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "branch work")
    _git(repo, "checkout", "-q", "main")
    return _git(repo, "rev-parse", name)


def _run_rc(repo: Path, branches: list[str], default: str | None = "main"):
    args = [sys.executable, SMOKE_SCRIPT, "", "\n".join(branches)]
    if default is not None:
        args.append(default)
    return subprocess.run(args, capture_output=True, text=True, cwd=str(repo), env=_ENV,
                          timeout=60)


# ── Q-624: an undeclared task an approved branch links is scanned ──

def test_an_undeclared_lock_linked_body_with_a_procedure_heading_is_asked(tmp_path):
    """The #767 reproduction: the procedure is under the schema's own heading, the flag is
    missing, and a lock ties the task to an approved branch."""
    repo = _tree(tmp_path, index=_index(_task("FEAT-X", smoke=False)),
                 bodies={"FEAT-X.md": NO_HEADING}, locks={"FEAT-X.lock": LOCK})
    tip = _branch(repo, body=PROC)
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1, out
    assert _sources(out) == ["tasks/index.yml § FEAT-X"], out
    assert _field(out, "READ") == [f"feat/x@{tip[:12]} — the branch tip, the text that is merging"]
    assert "Drive the export end to end." in out, out


def test_an_undeclared_doc_linked_body_on_an_approved_branch_is_asked(tmp_path):
    repo = _tree(tmp_path, index=_index(_task("FEAT-X", smoke=False)),
                 bodies={"FEAT-X.md": PROC}, pending={"feat-x.md": DOC_X})
    _branch(repo)
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1, out
    assert _sources(out) == ["tasks/index.yml § FEAT-X"], out


def test_an_undeclared_body_without_a_heading_stays_silent(tmp_path):
    """The missing-heading signal stays flagged-only: an undeclared task asked nothing of
    anyone, so a body with no procedure is not a question."""
    repo = _tree(tmp_path, index=_index(_task("FEAT-X", smoke=False)),
                 bodies={"FEAT-X.md": NO_HEADING}, locks={"FEAT-X.lock": LOCK})
    _branch(repo)
    assert _run(repo, [], branches=["feat/x"]).splitlines() == ["NO_SMOKE_REQUIRED"]


def test_an_undeclared_task_with_no_body_or_a_missing_body_stays_silent(tmp_path):
    idx = _index(_task("FEAT-X", smoke=False, body="open/GONE.md"),
                 "  - id: FEAT-Y\n    status: in_progress\n")
    lock_y = LOCK.replace("FEAT-X", "FEAT-Y")
    repo = _tree(tmp_path, index=idx, locks={"FEAT-X.lock": LOCK, "FEAT-Y.lock": lock_y})
    _branch(repo)
    assert _run(repo, [], branches=["feat/x"]).splitlines() == ["NO_SMOKE_REQUIRED"]


def test_an_undeclared_task_linked_by_no_approved_branch_stays_silent(tmp_path):
    """A doc on a branch this run does not merge is not a reason to read an undeclared body."""
    repo = _tree(tmp_path, index=_index(_task("FEAT-X", smoke=False)),
                 bodies={"FEAT-X.md": PROC}, pending={"feat-x.md": DOC_X})
    _branch(repo)
    assert _signals(_run(repo, [], branches=["feat/other"])) == 0


def test_an_undeclared_task_under_a_held_doc_is_not_named_not_in_this_run(tmp_path):
    """`NOT IN THIS RUN:` names a declared procedure that is not asked. An undeclared task
    had none to skip."""
    doc = "---\nbranch: feat/old\nroadmap_ids: [FEAT-X]\n---\n# Summary\n"
    repo = _tree(tmp_path, index=_index(_task("FEAT-X", smoke=False, user_action="true")),
                 bodies={"FEAT-X.md": PROC}, pending={"old.md": doc})
    assert _run(repo, [], branches=["feat/new"]).splitlines() == ["NO_SMOKE_REQUIRED"]


def test_a_batch_lock_on_an_approved_branch_links_no_task_and_does_not_crash(tmp_path):
    lock = "batch: 3\nstatus: in_progress\nbranch: feat/x\n"
    repo = _tree(tmp_path, index=_index(_task("FEAT-X", smoke=False)),
                 bodies={"FEAT-X.md": PROC}, locks={"BATCH-3.lock": lock})
    _branch(repo)
    assert _run(repo, [], branches=["feat/x"]).splitlines() == ["NO_SMOKE_REQUIRED"]


def test_a_flag_set_on_the_branch_tip_index_declares_the_task(tmp_path):
    """The sibling #767 named: the flag lives in the branch's own `tasks/index.yml`, which
    main's index cannot show. Declared, so its missing heading is a signal."""
    repo = _tree(tmp_path, index=_index(_task("FEAT-X", smoke=False)),
                 bodies={"FEAT-X.md": NO_HEADING}, locks={"FEAT-X.lock": LOCK})
    _branch(repo, index=_index(_task("FEAT-X", smoke=True)))
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1, out
    assert "no procedure heading matched" in out, out


def test_a_branch_flag_does_not_declare_the_task_for_an_unapproved_link(tmp_path):
    """The tip index is read only for the approved branch that links the task."""
    repo = _tree(tmp_path, index=_index(_task("FEAT-X", smoke=False)),
                 bodies={"FEAT-X.md": NO_HEADING}, pending={"feat-x.md": DOC_X})
    _branch(repo, index=_index(_task("FEAT-X", smoke=True)))
    assert _signals(_run(repo, [], branches=["feat/other"])) == 0


def test_a_task_only_the_branch_index_carries_is_found_there(tmp_path):
    """A follow-up filed on the branch exists in no other index; its `body:` comes from the
    branch's own entry."""
    repo = _tree(tmp_path, index=_index(), pending={})
    (repo / "sysop/runtime/pending-docs/feat-x.md").write_text(
        "---\nbranch: feat/x\nroadmap_ids: [FEAT-N]\n---\n# Summary\n", encoding="utf-8")
    _git(repo, "checkout", "-q", "-b", "feat/x")
    (repo / "tasks/index.yml").write_text(_index(_task("FEAT-N", smoke=True)), encoding="utf-8")
    (repo / "tasks/open/FEAT-N.md").write_text(PROC, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "file FEAT-N")
    _git(repo, "checkout", "-q", "main")
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1, out
    assert _sources(out) == ["tasks/index.yml § FEAT-N"], out
    assert "Drive the export end to end." in out, out


def test_a_branch_index_that_does_not_parse_stops_the_gate(tmp_path):
    repo = _tree(tmp_path, index=_index(_task("FEAT-X", smoke=False)),
                 bodies={"FEAT-X.md": PROC}, locks={"FEAT-X.lock": LOCK})
    _branch(repo, index="tasks: [unclosed\n")
    r = _run_rc(repo, ["feat/x"])
    assert r.returncode == 1 and r.stdout == "", (r.returncode, r.stdout)
    assert "feat/x:tasks/index.yml does not parse" in r.stderr, r.stderr


# ── Q-626: origin/<default branch>'s index ──

HELD_DOC = "---\nbranch: feat/old\nroadmap_ids: [FEAT-H]\n---\n# Summary\n"
H_BODY = {"FEAT-H.md": "# H\n\n## Manual smoke required\n1. Console step.\n"}


def _with_origin(tmp_path: Path, repo: Path) -> Path:
    """A local bare `origin`, holding `main` as the repo has it now."""
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", "main")
    return bare


def _advance_origin(tmp_path: Path, bare: Path, index: str) -> str:
    """Another clone pushes `index` to origin's main. The repo under test does not fetch,
    so its remote-tracking ref stays behind until the gate fetches."""
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(bare), str(other))
    _git(other, "config", "user.email", "t@example.invalid")
    _git(other, "config", "user.name", "t")
    (other / "tasks/index.yml").write_text(index, encoding="utf-8")
    _git(other, "commit", "-q", "-am", "upstream index change")
    _git(other, "push", "-q", "origin", "main")
    return _git(other, "rev-parse", "HEAD")


def test_origin_clearing_user_action_releases_the_hold(tmp_path):
    """The #768 reproduction: local main is behind; an upstream commit cleared
    `user_action`, and the gate reported the task as linked only by a held doc."""
    repo = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")),
                 pending={"old.md": HELD_DOC}, bodies=H_BODY)
    bare = _with_origin(tmp_path, repo)
    _advance_origin(tmp_path, bare, _index(_task("FEAT-H", user_action="false")))
    out = _run(repo, [], branches=["feat/new"])
    assert _signals(out) == 1, out
    assert "NOT IN THIS RUN" not in out, out
    assert _sources(out) == ["tasks/index.yml § FEAT-H"], out


def test_without_the_upstream_change_the_hold_stands(tmp_path):
    """The control for the test above: same tree, origin agrees with the working tree."""
    repo = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")),
                 pending={"old.md": HELD_DOC}, bodies=H_BODY)
    _with_origin(tmp_path, repo)
    out = _run(repo, [], branches=["feat/new"])
    assert _signals(out) == 0, out
    assert "NOT IN THIS RUN: tasks/index.yml § FEAT-H" in out, out


def test_origin_cannot_add_a_hold(tmp_path):
    repo = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="false")),
                 pending={"old.md": HELD_DOC}, bodies=H_BODY)
    bare = _with_origin(tmp_path, repo)
    _advance_origin(tmp_path, bare, _index(_task("FEAT-H", user_action="true")))
    assert _signals(_run(repo, [], branches=["feat/new"])) == 1


def test_a_task_origin_does_not_carry_is_held_on_the_working_tree_alone(tmp_path):
    repo = _tree(tmp_path, index=_index(_task("FEAT-Z")), bodies={})
    bare = _with_origin(tmp_path, repo)
    (repo / "tasks/index.yml").write_text(_index(_task("FEAT-H", user_action="true")),
                                          encoding="utf-8")
    (repo / "tasks/open/FEAT-H.md").write_text(H_BODY["FEAT-H.md"], encoding="utf-8")
    (repo / "sysop/runtime/pending-docs/old.md").write_text(HELD_DOC, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "local-only task")
    assert bare.exists()
    out = _run(repo, [], branches=["feat/new"])
    assert _signals(out) == 0, out
    assert "NOT IN THIS RUN: tasks/index.yml § FEAT-H" in out, out


def test_a_flag_set_only_on_origin_is_asked(tmp_path):
    doc = "---\nbranch: feat/old\nroadmap_ids: [FEAT-X]\n---\n# Summary\n"
    repo = _tree(tmp_path, index=_index(_task("FEAT-X", smoke=False)),
                 bodies={"FEAT-X.md": NO_HEADING}, pending={"old.md": doc})
    bare = _with_origin(tmp_path, repo)
    _advance_origin(tmp_path, bare, _index(_task("FEAT-X", smoke=True)))
    out = _run(repo, [], branches=[])
    assert _signals(out) == 1, out
    assert "no procedure heading matched" in out, out


def test_no_origin_remote_prints_no_origin_line(tmp_path):
    repo = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")),
                 pending={"old.md": HELD_DOC}, bodies=H_BODY)
    out = _run(repo, [], branches=["feat/new"])
    assert "ORIGIN INDEX" not in out, out


def test_an_origin_without_the_default_branch_says_it_was_not_read(tmp_path):
    repo = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")),
                 pending={"old.md": HELD_DOC}, bodies=H_BODY)
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    out = _run(repo, [], branches=["feat/new"])
    (line,) = [ln for ln in out.splitlines() if ln.startswith("ORIGIN INDEX:")]
    assert line.startswith("ORIGIN INDEX: not read — origin/main does not resolve; fetch failed: "), line
    assert line.endswith("; a hold is judged from the working tree alone"), line
    assert "NOT IN THIS RUN: tasks/index.yml § FEAT-H" in out, out


def test_a_failed_fetch_reads_the_last_fetched_ref_and_says_so(tmp_path):
    repo = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")),
                 pending={"old.md": HELD_DOC}, bodies=H_BODY)
    _with_origin(tmp_path, repo)
    sha = _git(repo, "rev-parse", "origin/main")
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "no-such-remote.git"))
    out = _run(repo, [], branches=["feat/new"])
    (line,) = [ln for ln in out.splitlines() if ln.startswith("ORIGIN INDEX:")]
    assert line.startswith("ORIGIN INDEX: fetch failed ("), line
    assert line.endswith(f"read the last-fetched origin/main@{sha[:12]}, which may be behind"), line


def test_the_gate_reads_the_named_default_branch_not_main(tmp_path):
    """`origin/<default branch>` is the resolved name, never a hard-coded `main`."""
    repo = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")),
                 pending={"old.md": HELD_DOC}, bodies=H_BODY)
    bare = _with_origin(tmp_path, repo)
    _git(repo, "push", "-q", "origin", "main:trunk")
    _advance_origin(tmp_path, bare, _index(_task("FEAT-H", user_action="false")))
    # `main` first: its fetch moves origin/main to the released index, so a gate that read
    # origin/main whatever it was told would release the `trunk` run's hold too.
    assert _signals(_run(repo, [], branches=["feat/new"], default_branch="main")) == 1
    assert _signals(_run(repo, [], branches=["feat/new"], default_branch="trunk")) == 0
    # The fetch wrote each branch to its own tracking ref, and left the other's alone.
    assert _git(repo, "rev-parse", "refs/remotes/origin/main") == _git(bare, "rev-parse", "main")
    assert _git(repo, "rev-parse", "refs/remotes/origin/trunk") == _git(bare, "rev-parse", "trunk")


def test_an_origin_index_that_does_not_parse_stops_the_gate(tmp_path):
    repo = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")),
                 pending={"old.md": HELD_DOC}, bodies=H_BODY)
    bare = _with_origin(tmp_path, repo)
    _advance_origin(tmp_path, bare, "tasks: [unclosed\n")
    r = _run_rc(repo, ["feat/new"])
    assert r.returncode == 1 and r.stdout == "", (r.returncode, r.stdout)
    assert "origin/main:tasks/index.yml does not parse" in r.stderr, r.stderr


def test_the_origin_line_comes_before_the_first_signal(tmp_path):
    repo = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")),
                 pending={"old.md": HELD_DOC + "\n## Operator action\n1. Do it.\n"}, bodies=H_BODY)
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    lines = _run(repo, [], branches=["feat/new"]).splitlines()
    assert lines[0].startswith("SMOKE_REQUIRED:"), lines
    first = lines.index("---SIGNAL---")
    assert any(ln.startswith("ORIGIN INDEX:") for ln in lines[1:first]), lines


def test_an_unsubstituted_or_missing_default_branch_exits_3(tmp_path):
    repo = _tree(tmp_path, index=_index())
    for default in ("<default branch>", "<main>", "", None):
        r = _run_rc(repo, [], default=default)
        assert r.returncode == 3 and r.stdout == "", (default, r.returncode, r.stdout)
        assert "third argument" in r.stderr, r.stderr


# ── Q-627: the branch a signal merges on ──

def test_a_signal_on_an_approved_branch_names_it(tmp_path):
    repo = _tree(tmp_path, index=_index(_task("FEAT-X")), bodies={"FEAT-X.md": PROC},
                 locks={"FEAT-X.lock": LOCK})
    _branch(repo)
    out = _run(repo, [], branches=["feat/x"])
    assert _field(out, "BRANCH") == ["feat/x"], out


def test_a_doc_signal_names_its_approved_branch(tmp_path):
    doc = DOC_X.replace("roadmap_ids: [FEAT-X]\n", "") + "\n## Operator action\n1. Do it.\n"
    repo = _tree(tmp_path, index=_index(), pending={"feat-x.md": doc})
    _branch(repo)
    out = _run(repo, [], branches=["feat/x"])
    assert _field(out, "BRANCH") == ["feat/x"], out


def test_a_signal_on_no_approved_branch_has_no_branch_line(tmp_path):
    repo = _tree(tmp_path, index=_index(_task("FEAT-X")), bodies={"FEAT-X.md": PROC},
                 pending={"feat-x.md": DOC_X})
    _branch(repo)
    out = _run(repo, [], branches=[])
    assert _signals(out) == 1, out
    assert _field(out, "BRANCH") == [], out


# ── the validator's warning names the set Step 3c reads ──

def test_the_validator_warning_names_more_than_the_original_two_phrases(tmp_path):
    """`#767` found the warning naming `manual smoke` / `smoke required` while the pattern
    behind it carries the widened set; an author fixing the warning by the message alone
    would think `## Operator action` does not count."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core/companion/scripts"))
    import validate_tasks as V
    body = tmp_path / "FEAT-X.md"
    body.write_text(NO_HEADING, encoding="utf-8")
    report = V.Report()
    V._check_manual_smoke({"manual_smoke": True}, body, "FEAT-X", report)
    (w,) = report.warnings
    assert "'operator action'" in w.message and "'before merge'" in w.message, w.message
    body.write_text("# X\n\n## Operator action\n1. Do it.\n", encoding="utf-8")
    report = V.Report()
    V._check_manual_smoke({"manual_smoke": True}, body, "FEAT-X", report)
    assert report.warnings == [], report.warnings


# ── Phase 351 round 1: an approved branch can release a hold too ──

def test_an_approved_branch_clearing_user_action_releases_the_hold(tmp_path):
    """Lens C's reproduction: an approved branch clears another task's `user_action`, so the
    merged index Step 4c reads no longer holds the doc and consolidates it. Step 3c must ask
    the declared smoke, and the note must say why the doc is not held."""
    repo = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")),
                 pending={"old.md": HELD_DOC}, bodies=H_BODY)
    _branch(repo, name="feat/y", index=_index(_task("FEAT-H", user_action="false")))
    out = _run(repo, [], branches=["feat/y"])
    assert _signals(out) == 1, out
    assert "NOT IN THIS RUN" not in out, out
    (note,) = _field(out, "NOT MERGING")
    assert note.startswith("not held here: user_action is set locally but not on origin/main "
                           "or an approved branch that carries the task (FEAT-H); "
                           "Step 4c may still hold it;"), note


def test_an_approved_branch_cannot_add_a_hold(tmp_path):
    repo = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="false")),
                 pending={"old.md": HELD_DOC}, bodies=H_BODY)
    _branch(repo, name="feat/y", index=_index(_task("FEAT-H", user_action="true")))
    out = _run(repo, [], branches=["feat/y"])
    assert _signals(out) == 1, out
    assert _field(out, "NOT MERGING")[0].startswith("not held;"), out


def test_an_approved_branch_without_the_task_leaves_the_hold(tmp_path):
    repo = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")),
                 pending={"old.md": HELD_DOC}, bodies=H_BODY)
    _branch(repo, name="feat/y", index=_index())
    out = _run(repo, [], branches=["feat/y"])
    assert _signals(out) == 0, out
    assert "NOT IN THIS RUN: tasks/index.yml § FEAT-H" in out, out



# ── Phase 351 round 1: lens A's reproductions and test gaps ──

def test_an_origin_without_a_fetch_refspec_is_still_refreshed(tmp_path):
    """`git fetch origin main` with no `remote.origin.fetch` writes only FETCH_HEAD; the
    gate names its refspec so the tracking ref it reads moves."""
    repo = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")),
                 pending={"old.md": HELD_DOC}, bodies=H_BODY)
    bare = _with_origin(tmp_path, repo)
    _git(repo, "config", "--unset-all", "remote.origin.fetch")
    _advance_origin(tmp_path, bare, _index(_task("FEAT-H", user_action="false")))
    out = _run(repo, [], branches=["feat/new"])
    assert _signals(out) == 1 and "ORIGIN INDEX" not in out, out


def test_a_branch_index_that_cannot_be_decoded_is_named(tmp_path):
    repo = _tree(tmp_path, index=_index(_task("FEAT-X", smoke=False)),
                 bodies={"FEAT-X.md": NO_HEADING}, locks={"FEAT-X.lock": LOCK})
    _git(repo, "checkout", "-q", "-b", "feat/x")
    (repo / "tasks/index.yml").write_bytes(
        _index(_task("FEAT-X", smoke=True)).encode() + b"# caf\xe9\n")
    _git(repo, "commit", "-qam", "latin-1 byte")
    _git(repo, "checkout", "-q", "main")
    out = _run(repo, [], branches=["feat/x"])
    assert any(ln.startswith("BRANCH INDEX: not read — `feat/x:tasks/index.yml`:")
               for ln in out.splitlines()), out


def test_an_undeclared_body_the_tip_cannot_be_read_for_is_named(tmp_path):
    """Lens A's c5: the tip body fails to decode, the working tree's has no heading, and an
    undeclared task signals nothing, so the failure must be said."""
    repo = _tree(tmp_path, index=_index(_task("FEAT-X", smoke=False)),
                 bodies={"FEAT-X.md": NO_HEADING}, locks={"FEAT-X.lock": LOCK})
    _git(repo, "checkout", "-q", "-b", "feat/x")
    (repo / "tasks/open/FEAT-X.md").write_bytes(b"# X caf\xe9\n\n## Manual smoke required\n1. Go.\n")
    _git(repo, "commit", "-qam", "latin-1 body")
    _git(repo, "checkout", "-q", "main")
    out = _run(repo, [], branches=["feat/x"])
    assert out.splitlines()[0] == "NO_SMOKE_REQUIRED", out
    assert any(ln.startswith("BODY NOT READ: tasks/index.yml § FEAT-X at `feat/x`")
               for ln in out.splitlines()), out


def test_a_tip_read_body_prints_no_body_not_read_line(tmp_path):
    repo = _tree(tmp_path, index=_index(_task("FEAT-X", smoke=False)),
                 bodies={"FEAT-X.md": NO_HEADING}, locks={"FEAT-X.lock": LOCK})
    _branch(repo, body=NO_HEADING + "\nmore\n")
    assert _run(repo, [], branches=["feat/x"]).splitlines() == ["NO_SMOKE_REQUIRED"]


def test_a_doc_linked_task_flagged_only_at_the_tip_is_declared(tmp_path):
    """A03: the doc link (not a lock) reads the tip index too. The body has no heading, so
    only a declared task signals."""
    repo = _tree(tmp_path, index=_index(_task("FEAT-X", smoke=False)),
                 bodies={"FEAT-X.md": NO_HEADING}, pending={"feat-x.md": DOC_X})
    _branch(repo, index=_index(_task("FEAT-X", smoke=True)))
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "no procedure heading matched" in out, out


def test_a_clone_workspace_tip_index_is_read_in_the_clone(tmp_path):
    """A01: a `--clone` workspace's branch exists only in the clone, so its index is read
    there (`git -C <workspace>`), found through the lock's `workspace:`."""
    repo = _tree(tmp_path, index=_index(_task("FEAT-X", smoke=False)),
                 bodies={"FEAT-X.md": NO_HEADING})
    clone = tmp_path / "main-FEAT-X"
    _git(tmp_path, "clone", "-q", str(repo), str(clone))
    _git(clone, "config", "user.email", "t@example.invalid")
    _git(clone, "config", "user.name", "t")
    _git(clone, "checkout", "-q", "-b", "feat/x")
    (clone / "tasks/index.yml").write_text(_index(_task("FEAT-X", smoke=True)), encoding="utf-8")
    _git(clone, "commit", "-qam", "flag in the clone")
    (repo / "sysop/runtime/locks").mkdir(parents=True, exist_ok=True)
    (repo / "sysop/runtime/locks/FEAT-X.lock").write_text(
        LOCK.replace("mode: worktree\n", f"mode: clone\nworkspace: {clone}\n"), encoding="utf-8")
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "no procedure heading matched" in out, out


def test_a_string_user_action_on_origin_is_truthy_like_step_4c(tmp_path):
    """A07: `user_action: "false"` is a truthy string to Step 4c 1c's Python test, on origin
    as in the working tree, so origin does not release the hold."""
    repo = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")),
                 pending={"old.md": HELD_DOC}, bodies=H_BODY)
    bare = _with_origin(tmp_path, repo)
    _advance_origin(tmp_path, bare, _index(_task("FEAT-H", user_action='"false"')))
    out = _run(repo, [], branches=["feat/new"])
    assert _signals(out) == 0 and "NOT IN THIS RUN: tasks/index.yml § FEAT-H" in out, out


def test_an_origin_index_with_no_tasks_releases_no_hold(tmp_path):
    """A09: origin carries none of the tasks, so it releases nothing."""
    repo = _tree(tmp_path, index=_index(_task("FEAT-H", user_action="true")),
                 pending={"old.md": HELD_DOC}, bodies=H_BODY)
    bare = _with_origin(tmp_path, repo)
    _advance_origin(tmp_path, bare, "schema_version: 1\ntasks: []\n")
    out = _run(repo, [], branches=["feat/new"])
    assert _signals(out) == 0 and "NOT IN THIS RUN: tasks/index.yml § FEAT-H" in out, out
