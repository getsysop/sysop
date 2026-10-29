"""`/sitrep` reads a branch a `direct` close merged and held as merged, not as `planning` (`Q-643`).

Under `§ Merge policy: pr` the state `merged, close pending` is decided by a recorded PR head
(`refs/sysop/merged-pr-heads/<PR>`, `tests/test_squash_provenance.py`). A `direct` close records
no head: `/review-close` Step 4a merges a local-only branch by rebase-then-`--ff-only` and a
published one with `--no-ff`, onto `main` itself, so the branch's tip becomes an ancestor of the
default branch. When Step 4c 1c holds the branch's pending doc (`user_action`, or the doc's own
`hold:`), Step 6 keeps the branch and the lock — and with the default branch excluded the branch
is 0 commits ahead, so `/sitrep` read it `planning` and advised continuing the build pipeline on
a task whose work had already landed.

Every fixture here merges the way Step 4a prescribes, on a local bare `origin` (never a real URL).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "core/companion/scripts"
sys.path.insert(0, str(SCRIPTS))
import sitrep_survey as ss  # noqa: E402

_ENV = {k: v for k, v in os.environ.items()
        if not k.startswith("GIT_") or k in ("GIT_EXEC_PATH",)}
_ENV.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"})

INDEX = """tasks:
  - id: T1
    status: open
    title: one
  - id: T2
    status: open
    title: two
  - id: T3
    status: open
    title: three
"""

OLD = "2026-01-01T00:00:00Z"  # past every --stale-days threshold
# Fresh relative to the run, not a calendar date: a fixed "2026-10-01" aged past the stale
# threshold on 2026-10-07 and turned a `planning` assertion red (found by Phase 363's suite).
NEW = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(cwd, *args, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, env=_ENV, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {r.stderr}")
    return r


def _flip(w: Path, task: str, status: str, msg: str | None = None):
    lines = (w / "tasks/index.yml").read_text().splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip() == f"- id: {task}":
            lines[i + 1] = f"    status: {status}\n"
    (w / "tasks/index.yml").write_text("".join(lines))
    git(w, "commit", "-qam", msg or f"docs: claim {task}")


def _commit(w: Path, branch: str, name: str):
    git(w, "checkout", "-q", branch)
    (w / name).write_text(name + "\n")
    git(w, "add", name)
    git(w, "commit", "-qm", f"feat: {name}")
    git(w, "checkout", "-q", "main")


@pytest.fixture
def repo(tmp_path):
    """A primary checkout with T1 claimed on B1 and worked, and T3 claimed on B3 and not."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    w = tmp_path / "w"
    git(tmp_path, "clone", "-q", str(origin), str(w))
    (w / "tasks").mkdir()
    (w / "tasks/index.yml").write_text(INDEX)
    (w / ".gitignore").write_text("sysop/runtime/\n")  # as the installer seeds it
    git(w, "add", "-A")
    git(w, "commit", "-qm", "init")
    git(w, "push", "-q", "origin", "main")
    _flip(w, "T1", "in_progress")
    git(w, "branch", "B1")
    _flip(w, "T3", "in_progress")
    git(w, "branch", "B3")
    _commit(w, "B1", "w1.txt")
    return w


def close_local_only(w: Path, branch: str = "B1", push: bool = True):
    """Step 4a item 2, local-only arm, then Step 4d's push of `main` under `direct`."""
    git(w, "checkout", "-q", branch)
    git(w, "rebase", "-q", "main")
    git(w, "checkout", "-q", "main")
    git(w, "merge", "-q", "--ff-only", branch)
    if push:
        git(w, "push", "-q", "origin", "main")


def close_published(w: Path, branch: str = "B1"):
    """Step 4a item 2, published arm: `--no-ff`, the branch never rebased."""
    git(w, "push", "-q", "origin", f"{branch}:refs/heads/{branch}")
    git(w, "fetch", "-q", "origin")
    git(w, "merge", "-q", "--no-ff", "-m", f"merge {branch} (published — not rebased)", branch)
    git(w, "push", "-q", "origin", "main")


def write_lock(w: Path, task: str, branch: str, started: str = NEW, extra: str = ""):
    d = w / "sysop/runtime/locks"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{task}.lock"
    p.write_text(f"task_id: {task}\nbranch: {branch}\nstarted: {started}\n"
                 f"status: in_progress\n{extra}")
    return p


def hold(w: Path, branch: str, task: str = "T1", extra: str = ""):
    """The doc a close held for `branch` (Step 4c 1c), where Step 3b collected it."""
    d = w / "sysop/runtime/pending-docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{branch.replace('/', '-')}.md").write_text(
        f'---\nbranch: "{branch}"\nroadmap_ids: [{task}]\n{extra}---\n\nheld\n')


def survey(w: Path, monkeypatch, t1_extra: str = "    user_action: true\n"):
    (w / "tasks/index.yml").write_text(
        "tasks:\n"
        "  - id: T1\n    status: in_progress\n    title: one\n" + t1_extra +
        "  - id: T2\n    status: open\n    title: two\n"
        "  - id: T3\n    status: in_progress\n    title: three\n")
    monkeypatch.chdir(w)
    monkeypatch.setattr(ss, "_resolve_main_repo_root", lambda: w)
    return ss.run_survey()


def by_id(s):
    return {t.task_id: t for t in s.tasks}


# ─────────────────────────────────────────────────────────────────────────────
# The filed case, both merge arms of Step 4a
# ─────────────────────────────────────────────────────────────────────────────

def test_a_held_branch_a_direct_close_rebased_and_fast_forwarded_reads_merged(repo, monkeypatch):
    w = repo
    _flip(w, "T2", "in_progress")  # main moves, so the rebase is real
    close_local_only(w)
    write_lock(w, "T1", "B1", OLD)
    hold(w, "B1")
    t1 = by_id(survey(w, monkeypatch))["T1"]
    assert t1.state == ss._MERGED_STATE, (t1.state, t1.next_action, t1.notes)
    assert t1.commits_ahead == 0
    assert t1.next_action == (
        "do T1's outstanding user step (its body's `## User ops`), then python3 "
        "sysop/scripts/clear_user_action.py T1 and /review-close"), t1.next_action
    assert not any("PR #" in n for n in t1.notes), t1.notes
    assert any("ancestor of main" in n for n in t1.notes), t1.notes


def test_a_held_branch_a_direct_close_merged_no_ff_reads_merged(repo, monkeypatch):
    w = repo
    _flip(w, "T2", "in_progress")
    close_published(w)
    write_lock(w, "T1", "B1")
    hold(w, "B1", extra='hold: "rollout to prod"\n')
    t1 = by_id(survey(w, monkeypatch, t1_extra=""))["T1"]
    assert t1.state == ss._MERGED_STATE, (t1.state, t1.notes)
    assert t1.next_action == (
        "finish what its pending doc's `hold:` names, then python3 "
        "sysop/scripts/pending_doc_hold.py clear T1 and /review-close"), t1.next_action
    assert any("hold: rollout to prod" in n for n in t1.notes), t1.notes


def test_with_both_holds_cleared_it_routes_straight_to_the_close(repo, monkeypatch):
    w = repo
    close_local_only(w)
    write_lock(w, "T1", "B1")
    hold(w, "B1")
    s = survey(w, monkeypatch, t1_extra="")
    t1 = by_id(s)["T1"]
    assert t1.state == ss._MERGED_STATE and t1.next_action == "/review-close T1", t1
    rec = ss._recommended_next(s)
    assert rec is not None and rec.command == "/review-close T1", rec
    assert "squash" not in rec.reason, rec.reason


def test_a_direct_close_whose_push_has_not_happened_still_reads_merged(repo, monkeypatch):
    """Merged on local `main` only — a close whose Step 4d push failed, or one still running.
    The arm tests ancestry against every default-branch ref, not `origin/<default>` alone."""
    w = repo
    close_local_only(w, push=False)
    write_lock(w, "T1", "B1")
    hold(w, "B1")
    t1 = by_id(survey(w, monkeypatch))["T1"]
    assert t1.state == ss._MERGED_STATE, (t1.state, t1.notes)
    assert any("not yet on origin/main" in n for n in t1.notes), t1.notes


def test_merged_on_origin_only_reads_merged(repo, monkeypatch):
    """Another checkout closed it and pushed; this one fetched but has not pulled."""
    w = repo
    other = w.parent / "other"
    git(w, "push", "-q", "origin", "B1:refs/heads/B1")
    git(w.parent, "clone", "-q", str(w.parent / "origin.git"), str(other))
    git(other, "merge", "-q", "--no-ff", "-m", "merge B1", "origin/B1")
    git(other, "push", "-q", "origin", "main")
    git(w, "fetch", "-q", "origin")
    write_lock(w, "T1", "B1")
    hold(w, "B1")
    assert ss._merged_into_default(w, "B1", None, None, False) == "origin/main"
    t1 = by_id(survey(w, monkeypatch))["T1"]
    assert t1.state == ss._MERGED_STATE, (t1.state, t1.notes)
    assert not any("not yet on origin" in n for n in t1.notes), t1.notes


# ─────────────────────────────────────────────────────────────────────────────
# What must NOT read as merged
# ─────────────────────────────────────────────────────────────────────────────

def test_without_a_held_doc_an_ancestor_is_not_merged(repo, monkeypatch):
    """Ancestry alone admits every unstarted claim cut from `main`: B3 has 0 commits and is an
    ancestor of `main` from the moment it is cut. With no held doc it keeps its old reading —
    `stale` past the threshold, `planning` inside it — and so does a merged branch whose doc
    the close routed (nothing is pending for it)."""
    w = repo
    close_local_only(w)
    write_lock(w, "T1", "B1")
    write_lock(w, "T3", "B3", OLD)
    s = by_id(survey(w, monkeypatch))
    assert ss._merged_into_default(w, "B3", None, None, False) == ""
    assert s["T3"].state == "stale", (s["T3"].state, s["T3"].notes)
    assert s["T1"].state == "planning", (s["T1"].state, s["T1"].notes)


def test_an_unstarted_claim_a_held_doc_names_reads_merged_as_the_close_would(repo, monkeypatch):
    """A decision, stated: a held doc naming a 0-commit branch is read as merged. Step 4c 1b's
    own merged-branch test (`rev-list --count <branch> ^HEAD` = 0) calls it merged too, so
    `/sitrep` agreeing with the close is what keeps the next action executable. The `pr` arm
    makes the same call for a branch its recorded head contains."""
    w = repo
    write_lock(w, "T3", "B3")
    hold(w, "B3", task="T3")
    t3 = by_id(survey(w, monkeypatch))["T3"]
    assert t3.state == ss._MERGED_STATE, (t3.state, t3.notes)


def test_a_held_branch_with_a_commit_past_main_is_not_merged(repo, monkeypatch):
    """A 4a-SKIP'd branch keeps its doc and its commits; so does a merged branch someone
    worked on again. Neither is an ancestor of `main`."""
    w = repo
    close_local_only(w)
    _commit(w, "B1", "more.txt")
    write_lock(w, "T1", "B1")
    hold(w, "B1")
    assert ss._merged_into_default(w, "B1", None, None, False) == ""
    t1 = by_id(survey(w, monkeypatch))["T1"]
    assert t1.state != ss._MERGED_STATE and t1.commits_ahead == 1, (t1.state, t1.notes)


def test_a_published_branch_pushed_past_main_is_not_merged(repo):
    w = repo
    close_published(w)
    hold(w, "B1")
    assert ss._merged_into_default(w, "B1", None, None, False) == "main"
    other = w.parent / "other"
    git(w.parent, "clone", "-q", "-b", "B1", str(w.parent / "origin.git"), str(other))
    (other / "o.txt").write_text("o\n")
    git(other, "add", "o.txt")
    git(other, "commit", "-qm", "feat: more on the published branch")
    git(other, "push", "-q", "origin", "B1")
    git(w, "fetch", "-q", "origin")
    assert ss._merged_into_default(w, "B1", None, None, False) == "", "origin/<branch> moved past"


def test_a_clone_workspace_past_main_is_not_merged(repo):
    w = repo
    close_published(w)
    hold(w, "B1")
    clone = w.parent / "clone-b1"
    git(w.parent, "clone", "-q", "-b", "B1", str(w.parent / "origin.git"), str(clone))
    lock = ss.Lock(task_id="T1", path=w / "x.lock", branch="B1", workspace=str(clone))
    assert ss._merged_into_default(w, "B1", lock, None, False) == "main"
    (clone / "c.txt").write_text("c\n")
    git(clone, "add", "c.txt")
    assert ss._merged_into_default(w, "B1", lock, None, False) == "", "dirty clone on the branch"
    git(clone, "commit", "-qm", "feat: clone work")
    assert ss._merged_into_default(w, "B1", lock, None, False) == "", "clone tip past main"


def test_a_dirty_linked_worktree_is_live_work(repo):
    w = repo
    close_local_only(w)
    hold(w, "B1")
    wt = ss.Worktree(path=w.parent / "wt-b1", branch="B1", head="", is_main=False)
    assert ss._merged_into_default(w, "B1", None, wt, False) == "main"
    assert ss._merged_into_default(w, "B1", None, wt, True) == ""


def test_the_primary_checked_out_on_the_branch_and_dirty_is_live_work(repo):
    """A `--branch` claim works in the primary itself, so the lock's workspace is skipped as
    the main checkout, and no linked worktree exists: the primary's own state is the only
    evidence of live work. Applies to the `pr` arm too, through the same helper."""
    w = repo
    close_local_only(w)
    hold(w, "B1")
    git(w, "checkout", "-q", "B1")
    assert ss._merged_into_default(w, "B1", None, None, False) == "main", "clean: still merged"
    (w / "scratch-notes.txt").write_text("untracked\n")
    assert ss._merged_into_default(w, "B1", None, None, False) == "main", (
        "an untracked file in the primary is not live work (Step 6 gates on tracked changes)")
    (w / "w1.txt").write_text("edited\n")
    assert ss._merged_into_default(w, "B1", None, None, False) == ""
    git(w, "checkout", "-q", "--", "w1.txt")
    (w / "scratch-notes.txt").unlink()
    git(w, "checkout", "-q", "main")
    (w / "w1.txt").write_text("edited on main\n")
    assert ss._merged_into_default(w, "B1", None, None, False) == "main", (
        "dirt on another branch is not this claim's work")


def test_the_default_branch_itself_is_never_a_merged_claim(repo, monkeypatch):
    """`/document-work` may run on `main` and write `branch: main`; that doc can be held. The
    default branch is an ancestor of itself, and is no claim's branch."""
    w = repo
    hold(w, "main")
    assert ss._merged_into_default(w, "main", None, None, False) == ""
    write_lock(w, "T1", "main")
    t1 = by_id(survey(w, monkeypatch))["T1"]
    assert t1.state != ss._MERGED_STATE, (t1.state, t1.notes)


def test_no_resolvable_default_branch_is_no_verdict(repo):
    w = repo
    close_local_only(w)
    hold(w, "B1")
    git(w, "branch", "-q", "-m", "main", "trunk")
    git(w, "remote", "remove", "origin")
    assert ss.resolve_default_branch(w) == ""
    assert ss._merged_into_default(w, "B1", None, None, False) == ""


def test_a_tag_named_like_the_branch_does_not_stand_in_for_it(repo):
    """The tip is read from `refs/heads/<branch>`: a bare name resolves a same-named tag first."""
    w = repo
    git(w, "tag", "B1-x", "main")
    _commit(w, "B1", "past.txt")
    git(w, "tag", "-f", "B1", "main")  # a tag `B1` at main; the branch B1 is past main
    hold(w, "B1")
    assert ss._merged_into_default(w, "B1", None, None, False) == ""


# ─────────────────────────────────────────────────────────────────────────────
# `pr` behaviour unchanged
# ─────────────────────────────────────────────────────────────────────────────

def test_a_squash_leaves_no_ancestry_so_the_direct_arm_stays_silent(repo):
    """Under `pr` the merged branch reaches `main` through a squash, which breaks ancestry, so
    the direct arm cannot fire there; the recorded-head arm decides it, unchanged."""
    w = repo
    git(w, "checkout", "-q", "-b", "merge/review-close-1", "main")
    git(w, "checkout", "-q", "B1")
    git(w, "rebase", "-q", "merge/review-close-1")
    git(w, "checkout", "-q", "merge/review-close-1")
    git(w, "merge", "-q", "--ff-only", "B1")
    head = git(w, "rev-parse", "HEAD").stdout.strip()
    squash = git(w, "commit-tree", "HEAD^{tree}", "-p", "origin/main", "-m", "squash (#1)").stdout.strip()
    git(w, "push", "-q", "origin", f"{squash}:refs/heads/main", f"{head}:refs/pull/1/head")
    git(w, "checkout", "-q", "main")
    git(w, "fetch", "-q", "origin", "main")
    git(w, "reset", "-q", "--hard", "origin/main")
    git(w, "branch", "-q", "-D", "merge/review-close-1")
    hold(w, "B1")
    assert ss._merged_into_default(w, "B1", None, None, False) == ""
    assert ss._landed_claim(w, "B1", None, None, False) == ""  # no record yet
    git(w, "fetch", "-q", "origin", "refs/pull/1/head:refs/sysop/merged-pr-heads/1")
    assert ss._landed_claim(w, "B1", None, None, False) == "1"


def test_the_pr_note_still_names_its_pr(repo, monkeypatch):
    w = repo
    t = ss._classify_task(
        task_id="T1", lock=None, worktree=None, branch="B1", index_entry={"status": "in_progress"},
        commits=[], unpushed=0, dirty=False, stale_days=7, phase40_cutoff=ss.datetime.now(ss.timezone.utc),
        main_root=w, landed_pr="7")
    assert t.state == ss._MERGED_STATE
    assert any("recorded PR #7's head" in n for n in t.notes), t.notes


def test_one_same_dir_and_it_refuses_a_nul_path_without_raising():
    """`_same_dir` was defined twice; the later copy, which caught only `OSError`, replaced the
    one `_landed_claim` was written against. A lock's `workspace:` is free text, and
    `Path.resolve()` raises `ValueError` on an embedded NUL. Both callers test `is_dir()` first
    today, so this pins the helper, not a reachable crash."""
    import inspect
    src = inspect.getsource(ss)
    assert src.count("def _same_dir(") == 1
    assert ss._same_dir(Path("a\x00b"), Path(".")) is False


def test_an_untracked_file_in_the_primary_does_not_unland_a_pr_claim(repo):
    """Round lens B: the shared helper's primary check counted `??` lines, so a `pr` claim
    landed by its recorded head read `planning` once someone checked the branch out in the
    primary beside an untracked file, while `/review-close` Step 2a 0b said LANDED."""
    w = repo
    git(w, "checkout", "-q", "B1")
    head = git(w, "rev-parse", "HEAD").stdout.strip()
    git(w, "update-ref", "refs/sysop/merged-pr-heads/1", head)
    hold(w, "B1")
    (w / "notes.txt").write_text("scratch\n")
    assert ss._landed_claim(w, "B1", None, None, False) == "1"


def test_the_skill_state_row_states_both_arms():
    """Round lens A (D19): the state-table row the runner reads had no guard. It must name
    both arms, the default-branch exclusion and the primary's tracked-changes rule."""
    skill = (Path(__file__).resolve().parents[1] / "core" / "skills" / "sitrep" / "SKILL.md")
    row = next(line for line in skill.read_text(encoding="utf-8").splitlines()
               if line.startswith("| **Merged, close pending** |"))
    for phrase in ("refs/sysop/merged-pr-heads/<PR>", "its local tip an ancestor of the default branch",
                   "the branch not being the default branch itself",
                   "or the branch never moved past its cut point",
                   "the main checkout included when it is on the branch (tracked changes only there)"):
        assert phrase in row, phrase
