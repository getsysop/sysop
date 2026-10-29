"""Squash provenance: each `pr` close records its merged PR's head, and readers use it (`Q-623`).

Under `§ Merge policy: pr`, `/claim-task` commits its claim flip to local `main`, and a worktree
cut before the next close's squash carries that flip as an ancestor. Once the squash lands the flip
is on `origin/main` as CONTENT and is an ancestor of neither ref, and a squash changes patch-ids, so
nothing ancestry-shaped can tell it from the branch's own work. Two upstream reports measured the
two ends: `/sitrep` counted the flips as commits ahead (internal tracker #769), and Step 4a's rebase replayed them
into a `status:` conflict the step says to STOP on (internal tracker #780).

Wade's ruling (2026-09-30): decide by provenance. The integration branch is cut from local `main`,
so the merged PR's head contains every local-only commit the close carried. `/review-close` Step 4d
records it as `refs/sysop/merged-pr-heads/<PR>`; readers exclude it; Step 4a replays only what it
does not contain.

Every fixture here is built the way the close builds it, on a local bare `origin` (never a real
URL), with the squash simulated by `commit-tree` and the PR head published as `refs/pull/1/head` so
the record step runs exactly as Step 4d prescribes it.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from skill_runner_text import text_of

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "core/companion/scripts"
sys.path.insert(0, str(SCRIPTS))
import sitrep_survey as ss  # noqa: E402

GLOB = "refs/sysop/merged-pr-heads/*"

_ENV = {k: v for k, v in os.environ.items()
        if not k.startswith("GIT_") or k in ("GIT_EXEC_PATH",)}
_ENV.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"})


def git(cwd, *args, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, env=_ENV, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {r.stderr}")
    return r


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


def _flip(w: Path, task: str, status: str, msg: str | None = None):
    lines = (w / "tasks/index.yml").read_text().splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.strip() == f"- id: {task}":
            lines[i + 1] = f"    status: {status}\n"
    (w / "tasks/index.yml").write_text("".join(lines))
    git(w, "commit", "-qam", msg or f"docs: claim {task}")


def _work(w: Path, branch: str, name: str):
    git(w, "checkout", "-q", branch)
    (w / name).write_text(name + "\n")
    git(w, "add", name)
    git(w, "commit", "-qm", f"feat: {name}")
    git(w, "checkout", "-q", "main")


@pytest.fixture
def squashed(tmp_path):
    """One `pr` close has run. B1 (T1) merged in it; B2 (T2) and B3 were cut before it.

    * B1 — claimed, worked, rebased onto the integration branch and fast-forwarded: merged.
    * B2 — claimed after B1, worked, NOT in the close: carries both claim flips as ancestors.
    * B3 — cut from local main beside B2 and never worked on: an unstarted claim.

    The close then flipped T1 to done, pushed, and the PR squashed. Local main was reset to
    `origin/main` as Step 6 does. The head is NOT recorded here; `record()` does that.
    """
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    w = tmp_path / "w"
    git(tmp_path, "clone", "-q", str(origin), str(w))
    (w / "tasks").mkdir()
    (w / "tasks/index.yml").write_text(INDEX)
    git(w, "add", "-A")
    git(w, "commit", "-qm", "init")
    git(w, "push", "-q", "origin", "main")
    _flip(w, "T1", "in_progress")
    git(w, "branch", "B1")
    _flip(w, "T2", "in_progress")
    git(w, "branch", "B2")
    git(w, "branch", "B3")
    _work(w, "B1", "w1.txt")
    _work(w, "B2", "w2.txt")
    git(w, "checkout", "-q", "-b", "merge/review-close-1", "main")
    git(w, "merge", "-q", "--no-edit", "origin/main")
    git(w, "checkout", "-q", "B1")
    git(w, "rebase", "-q", "merge/review-close-1")
    git(w, "checkout", "-q", "merge/review-close-1")
    git(w, "merge", "-q", "--ff-only", "B1")
    _flip(w, "T1", "done", "docs: review-close consolidate")
    head = git(w, "rev-parse", "HEAD").stdout.strip()
    squash = git(w, "commit-tree", "HEAD^{tree}", "-p", "origin/main", "-m", "squash (#1)").stdout.strip()
    git(w, "push", "-q", "origin", f"{squash}:refs/heads/main", f"{head}:refs/pull/1/head")
    git(w, "checkout", "-q", "main")
    git(w, "fetch", "-q", "origin", "main")
    git(w, "reset", "-q", "--hard", "origin/main")
    git(w, "branch", "-q", "-D", "merge/review-close-1")
    return w, head


def record(w: Path, pr: str = "1"):
    """Step 4d's record command, verbatim in shape."""
    return git(w, "fetch", "origin", f"refs/pull/{pr}/head:refs/sysop/merged-pr-heads/{pr}",
               check=False)


def subjects(commits):
    return [c.subject for c in commits]


# ─────────────────────────────────────────────────────────────────────────────
# The record itself
# ─────────────────────────────────────────────────────────────────────────────

def test_the_record_writes_the_pr_head_and_is_idempotent(squashed):
    w, head = squashed
    assert record(w).returncode == 0
    assert git(w, "rev-parse", "refs/sysop/merged-pr-heads/1").stdout.strip() == head
    again = record(w)
    assert again.returncode == 0, again.stderr
    assert git(w, "rev-parse", "refs/sysop/merged-pr-heads/1").stdout.strip() == head


def test_a_failed_record_writes_nothing(squashed):
    """A PR number with no `refs/pull/<N>/head` fails loudly and leaves no ref behind, so a
    reader never sees a half-written provenance."""
    w, _ = squashed
    assert record(w, "99").returncode != 0
    assert git(w, "for-each-ref", "refs/sysop/").stdout == ""


# ─────────────────────────────────────────────────────────────────────────────
# /sitrep's reader (internal tracker #769)
# ─────────────────────────────────────────────────────────────────────────────

def test_without_a_record_the_stale_flips_count_as_work(squashed):
    """The defect, reproduced: the base the fix is measured against."""
    w, _ = squashed
    got = subjects(ss._commits_ahead_of_main("B2", w))
    assert got == ["feat: w2.txt", "docs: claim T2", "docs: claim T1"], got
    assert subjects(ss._commits_ahead_of_main("B3", w)) == ["docs: claim T2", "docs: claim T1"]


def test_with_the_record_only_the_branchs_own_work_counts(squashed):
    w, _ = squashed
    record(w)
    assert subjects(ss._commits_ahead_of_main("B2", w)) == ["feat: w2.txt"]
    assert ss._commits_ahead_of_main("B3", w) == []
    assert ss._commits_ahead_of_main("B1", w) == []


def test_landed_by_names_the_pr_for_every_branch_the_head_contains(squashed):
    """B1 merged and B3 was cut before the close: both tips are in the head. B2 has work the
    head never saw. The worktree is what tells B1 from B3, and that is the caller's job."""
    w, _ = squashed
    record(w)
    assert ss._landed_by("B1", w) == "1"
    assert ss._landed_by("B3", w) == "1"
    assert ss._landed_by("B2", w) == ""
    assert ss._landed_by("no-such-branch", w) == ""


def _write_lock(w: Path, task: str, branch: str, started: str):
    d = w / "sysop/runtime/locks"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{task}.lock").write_text(
        f"task_id: {task}\nbranch: {branch}\nstarted: {started}\nstatus: in_progress\n")


def _hold(w: Path, branch: str, task: str = "T1"):
    """The doc a close held for `branch` (Step 4c 1c), where Step 3b collected it."""
    d = w / "sysop/runtime/pending-docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{branch.replace('/', '-')}.md").write_text(
        f'---\nbranch: "{branch}"\nroadmap_ids: [{task}]\n---\n\nheld\n')


def _survey(w: Path, monkeypatch, index_extra: str = ""):
    (w / "tasks/index.yml").write_text(
        "tasks:\n"
        "  - id: T1\n    status: in_progress\n    title: one\n" + index_extra +
        "  - id: T2\n    status: in_progress\n    title: two\n"
        "  - id: T3\n    status: in_progress\n    title: three\n")
    monkeypatch.chdir(w)
    monkeypatch.setattr(ss, "_resolve_main_repo_root", lambda: w)
    return {t.task_id: t for t in ss.run_survey().tasks}


def test_run_survey_reads_a_merged_branch_as_merged_and_never_as_stale(squashed, monkeypatch):
    """End to end through `run_survey`, with a lock older than the stale threshold: the
    merged branch's task waits on its human step, and the stale arm would have told the
    operator to remove its lock. An unstarted claim with its worktree reads `planning`, not
    `in progress`; with 0 commits and an old lock it reads `stale`, which is right for it."""
    w, _ = squashed
    record(w)
    old = "2026-01-01T00:00:00Z"
    _write_lock(w, "T1", "B1", old)
    _write_lock(w, "T3", "B3", old)
    _hold(w, "B1")
    git(w, "worktree", "add", "-q", str(w.parent / "wt-b3"), "B3")
    by_id = _survey(w, monkeypatch, "    user_action: true\n")
    t1 = by_id["T1"]
    assert t1.state == ss._MERGED_STATE, (t1.state, t1.notes)
    assert t1.commits_ahead == 0, t1.commits_ahead
    assert "clear_user_action.py T1" in t1.next_action
    assert any("PR #1" in n for n in t1.notes), t1.notes
    t3 = by_id["T3"]
    assert t3.state == "stale", (t3.state, t3.notes)  # 0 commits ahead now, and old


def test_run_survey_without_the_record_misreads_both(squashed, monkeypatch):
    """The same tree before the fix's input exists: the merged branch is `in progress` on
    the stale flips it shares with nothing, and so is the unstarted claim."""
    w, _ = squashed
    old = "2026-01-01T00:00:00Z"
    _write_lock(w, "T3", "B3", old)
    git(w, "worktree", "add", "-q", str(w.parent / "wt-b3"), "B3")
    by_id = _survey(w, monkeypatch)
    assert by_id["T3"].state == "in progress", by_id["T3"].state


def test_a_merged_branch_with_the_flag_cleared_routes_to_the_close(squashed, monkeypatch):
    w, _ = squashed
    record(w)
    _write_lock(w, "T1", "B1", "2026-09-30T00:00:00Z")
    _hold(w, "B1")
    t1 = _survey(w, monkeypatch)["T1"]
    assert t1.state == ss._MERGED_STATE
    assert t1.next_action == "/review-close T1"
    rec = ss._recommended_next(ss.Survey(
        timestamp=ss.datetime.now(ss.timezone.utc), main_root=w, head_short="x", stale_days=7,
        tasks=[t1], review_batches=[], discrepancies=[], open_roadmap_ids=[]))
    assert rec is not None and rec.command == "/review-close T1", rec


def _ws_lock(w: Path, task: str, branch: str, ws: Path, mode: str = "clone"):
    d = w / "sysop/runtime/locks"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{task}.lock").write_text(
        f"task_id: {task}\nbranch: {branch}\nstarted: 2026-09-30T00:00:00Z\n"
        f"status: in_progress\nmode: {mode}\nworkspace: {ws}\n")
    return ss.Lock(task_id=task, path=d / f"{task}.lock", branch=branch, workspace=str(ws))


def _clone_claim(w: Path, branch: str = "B3"):
    """A `--clone` claim on `branch`: published, cloned, and worked on in the clone. The
    primary's local ref stays at the cut point, which is inside the recorded head."""
    git(w, "push", "-q", "origin", f"{branch}:refs/heads/{branch}")
    clone = w.parent / f"clone-{branch}"
    git(w.parent, "clone", "-q", "-b", branch, str(w.parent / "origin.git"), str(clone))
    (clone / "c.txt").write_text("clone work\n")
    git(clone, "add", "c.txt")
    git(clone, "commit", "-qm", "feat: clone work")
    return clone


def test_the_merged_state_outranks_pending_batches():
    """Lens A, round 1 (A08): the P3b arm is not suppressed by a review batch waiting below it."""
    t = ss.TaskState(task_id="T1", state=ss._MERGED_STATE, next_action="/review-close T1")
    rb = ss.ReviewBatchState(
        batch_number=7, title="Batch 7", md_status="Pending", branch="", has_lock=False,
        has_branch=False, has_flag=False, flag_reason="", total_tasks=2, doc_worked_tasks=0,
        state="pending (not claimed)", next_action="/triage", notes=[], has_triage_record=False,
        triaged_verdict="")
    rec = ss._recommended_next(ss.Survey(
        timestamp=ss.datetime.now(ss.timezone.utc), main_root=Path("/tmp/x"), head_short="x",
        stale_days=7, tasks=[t], review_batches=[rb], discrepancies=[], open_roadmap_ids=[]))
    assert rec is not None and rec.command == "/review-close T1", rec


def test_landed_claim_needs_a_held_doc(squashed):
    """Containment alone admits an unstarted claim and any branch cut from main before the
    close; only the held doc Step 6 keeps a merged branch alive for tells a landed one."""
    w, _ = squashed
    record(w)
    git(w, "branch", "production", "origin/main^")  # cut before the close
    assert ss._landed_by("B3", w) == "1" and ss._landed_by("production", w) == "1"
    assert ss._landed_claim(w, "B3", None, None, False) == ""
    assert ss._landed_claim(w, "production", None, None, False) == ""
    assert ss._landed_claim(w, "B1", None, None, False) == ""
    _hold(w, "B1")
    assert ss._landed_claim(w, "B1", None, None, False) == "1"


def test_landed_claim_refuses_a_clone_whose_work_moved_on(squashed):
    """Round 1 (lens C, reproduced): a `--clone` claim's work is in its clone and on
    `origin/<branch>`, never in a linked worktree, so a held doc plus containment would
    have landed it and Step 6 would have deleted its pushed work."""
    w, _ = squashed
    record(w)
    _hold(w, "B3", "T3")
    clone = _clone_claim(w)
    lock = _ws_lock(w, "T3", "B3", clone)
    assert ss._landed_claim(w, "B3", lock, None, False) == "", "clone workspace past the head"
    git(clone, "push", "-q", "origin", "B3")
    git(w, "fetch", "-q", "origin", "B3:refs/remotes/origin/B3")
    assert ss._landed_claim(w, "B3", None, None, False) == "", "origin/<branch> past the head"


def test_landed_claim_refuses_a_dirty_workspace(squashed):
    w, _ = squashed
    record(w)
    _hold(w, "B1")
    git(w, "push", "-q", "origin", "B1:refs/heads/B1")
    clone = w.parent / "clone-b1"
    git(w.parent, "clone", "-q", "-b", "B1", str(w.parent / "origin.git"), str(clone))
    (clone / "dirt.txt").write_text("uncommitted\n")
    git(clone, "add", "dirt.txt")
    lock = _ws_lock(w, "T1", "B1", clone)
    assert ss._landed_claim(w, "B1", lock, None, False) == ""
    git(clone, "reset", "-q", "--hard")
    assert ss._landed_claim(w, "B1", lock, None, False) == "1"


# ─────────────────────────────────────────────────────────────────────────────
# /review-close: every prescribed command, extracted from the skill and run as written
# ─────────────────────────────────────────────────────────────────────────────

import re  # noqa: E402
import textwrap  # noqa: E402

CLOSE = REPO / "core/skills/review-close/SKILL.md"
CLAIM = REPO / "core/skills/claim-task/SKILL.md"
WF = REPO / "core/companion/docs/WORKFLOW.md"
IU = REPO / "docs/install-and-update.md"


def _close() -> str:
    return text_of(CLOSE)


def _fence_with(text: str, marker: str) -> str:
    """The one fenced block holding `marker`, dedented as the renderer would."""
    blocks = [m.group(1) for m in re.finditer(r"```bash\n(.*?)\n\s*```", text, re.S)
              if marker in m.group(1)]
    assert len(blocks) == 1, f"{marker!r}: {len(blocks)} fenced blocks"
    return textwrap.dedent(blocks[0])


def _inline(text: str, prefix: str) -> str:
    """The one backticked command starting with `prefix`."""
    hits = re.findall(r"`(" + re.escape(prefix) + r"[^`]*)`", text)
    assert len(set(hits)) == 1, f"{prefix!r}: {hits}"
    return hits[0]


# The heredocs run as `python3`; put this interpreter first so the ones that parse YAML find
# PyYAML, as the in-heredoc bootstrap does from a consumer's `.venv`.
_SH_ENV = {**_ENV, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{_ENV.get('PATH', '')}"}


def _from_tree(fence: str) -> str:
    """A fence that runs a shipped script, pointed at this tree's copy: the fixture repos
    have no `sysop/scripts/`. Since Phase 387 (`Q-409` P3) Step 2a's landed check and Step
    4a's recorded-head check are scripts; the fence is still what runs, as written."""
    return fence.replace("python3 sysop/scripts/", f"python3 {SCRIPTS}/")


def sh(w: Path, script: str):
    return subprocess.run(["/bin/bash", "-c", script], cwd=w, env=_SH_ENV,
                          capture_output=True, text=True)


def _heredoc(w: Path, branch: str, target: str):
    script = _from_tree(_fence_with(_close(), 'python3 sysop/scripts/pr_head_check.py "<branch>"'))
    script = script.replace('"<branch>"', f'"{branch}"').replace('"<merge target>"', f'"{target}"')
    return sh(w, script)


@pytest.fixture
def closing(squashed):
    """The next close is under way: the head is recorded and Step 4-pre has cut its
    integration branch from local main."""
    w, head = squashed
    assert record(w).returncode == 0
    git(w, "checkout", "-q", "-b", "merge/review-close-2", "main")
    return w, head


def test_step_4d_records_with_the_shipped_command(squashed):
    w, head = squashed
    cmd = _fence_with(_close(), 'refs/pull/<PR>/head:refs/sysop/merged-pr-heads/<PR>')
    out = sh(w, cmd.replace("<PR>", "1"))
    # Phase 422 (`Q-665`): the command's own exit, not an echoed `$?` (denied under `dontAsk`).
    assert out.returncode == 0, out
    assert git(w, "rev-parse", "refs/sysop/merged-pr-heads/1").stdout.strip() == head


def test_step_4d_unsubstituted_record_fails_loudly_and_writes_nothing(squashed):
    w, _ = squashed
    cmd = _fence_with(_close(), 'refs/pull/<PR>/head:refs/sysop/merged-pr-heads/<PR>')
    out = sh(w, cmd)
    assert out.returncode != 0 and "<PR>" in out.stderr, out
    assert git(w, "for-each-ref", "refs/sysop/").stdout == ""


def test_step_4a_heredoc_names_the_head_and_the_stale_flips(closing):
    w, _ = closing
    out = _heredoc(w, "B2", "merge/review-close-2")
    assert out.returncode == 0, out
    lines = out.stdout.splitlines()
    assert lines[0] == "RECORDED HEAD: refs/sysop/merged-pr-heads/1", out.stdout
    assert lines[1] == "SKIP 2 commit(s) PR #1's head contains:", out.stdout
    assert [l.split(" ", 3)[-1] for l in lines[2:4]] == ["docs: claim T1", "docs: claim T2"], lines
    assert lines[-1] == "REPLAY 1 commit(s)", out.stdout


def test_the_plain_rebase_conflicts_and_the_onto_rebase_does_not(closing):
    """Internal tracker #780, end to end: the arm as written before this phase stops on the `status:`
    conflict; the `--onto` form the skill now prescribes replays only the branch's work, and
    T1 keeps the `done` the earlier close gave it."""
    w, _ = closing
    git(w, "checkout", "-q", "B2")
    plain = git(w, "rebase", "merge/review-close-2", check=False)
    assert plain.returncode != 0
    assert "tasks/index.yml" in git(w, "diff", "--name-only", "--diff-filter=U").stdout
    git(w, "rebase", "--abort")
    text = _close()
    onto = _inline(text, 'git rebase --onto "<merge target>"')
    onto = (onto.replace('"<merge target>"', "merge/review-close-2")
                .replace('"<ref>"', "refs/sysop/merged-pr-heads/1").replace("<branch>", "B2"))
    assert sh(w, onto).returncode == 0
    ff = sh(w, "git checkout -q merge/review-close-2 && git merge --ff-only B2")
    assert ff.returncode == 0, ff
    assert "status: done" in (w / "tasks/index.yml").read_text().split("- id: T2")[0]
    assert (w / "w2.txt").exists()


def test_a_landed_branch_has_nothing_to_replay(closing):
    w, _ = closing
    out = _heredoc(w, "B1", "merge/review-close-2")
    assert out.stdout.splitlines()[0] == "RECORDED HEAD: refs/sysop/merged-pr-heads/1"
    assert out.stdout.splitlines()[-1] == "REPLAY 0 commit(s)", out.stdout


def test_no_recorded_head_means_none(squashed):
    w, _ = squashed
    git(w, "checkout", "-q", "-b", "merge/review-close-2", "main")
    out = _heredoc(w, "B2", "merge/review-close-2")
    assert out.returncode == 0 and out.stdout.strip() == "RECORDED HEAD: none", out


def test_a_branch_that_merged_main_after_the_squash_is_not_usable(closing):
    """`--onto <head>` would replay the squash commit the head lacks and the target has."""
    w, _ = closing
    git(w, "checkout", "-q", "B2")
    git(w, "merge", "-q", "--no-edit", "origin/main", check=False)
    if git(w, "diff", "--name-only", "--diff-filter=U").stdout:
        git(w, "checkout", "--theirs", "tasks/index.yml")
        git(w, "commit", "-qam", "merge main")
    git(w, "checkout", "-q", "merge/review-close-2")
    out = _heredoc(w, "B2", "merge/review-close-2")
    assert out.stdout.startswith("RECORDED HEAD: not usable"), out.stdout


@pytest.mark.parametrize("args", [("<branch>", "merge/review-close-2"), ("B2", ""),
                                  ("B2", "no-such-target")])
def test_the_heredoc_stops_on_a_placeholder_or_a_git_failure(closing, args):
    w, _ = closing
    out = _heredoc(w, *args)
    assert out.returncode == 3 and "STOP" in out.stdout, out


def test_the_published_arms_stale_test_separates_a_stale_flip_from_two_actors(closing):
    w, _ = closing
    stale_cmd = _inline(_close(), 'git diff "<ref>"')
    run = (stale_cmd.replace('"<ref>"', "refs/sysop/merged-pr-heads/1")
                    .replace('"refs/heads/<branch>"', "refs/heads/B2").replace("<that file>", "tasks/index.yml"))
    assert sh(w, run).stdout == "", "a stale flip shows in the branch's own diff"
    merged = git(w, "merge", "--no-ff", "-m", "m", "B2", check=False)
    assert merged.returncode != 0, "the published arm's conflict did not reproduce"
    git(w, "merge", "--abort")
    git(w, "checkout", "-q", "B2")
    _flip(w, "T1", "deferred", "B2 defers T1")
    git(w, "checkout", "-q", "merge/review-close-2")
    assert "status: deferred" in sh(w, run).stdout, "a genuine move was read as stale"


LANDED_MARKER = 'python3 sysop/scripts/feature_branch.py landed "<branch>"'


def _landed(w: Path, branch: str, default: str = "main"):
    script = _from_tree(_fence_with(_close(), LANDED_MARKER))
    return sh(w, script.replace('"<branch>"', f'"{branch}"').replace('"<default branch>"', f'"{default}"'))


def test_step_2a_landed_check_lands_only_a_held_branch(closing):
    w, _ = closing
    git(w, "branch", "production", "origin/main^")  # cut before the close
    for branch, want in (("B1", "NOT LANDED — no pending doc"), ("B3", "NOT LANDED — no pending doc"),
                         ("production", "NOT LANDED — no pending doc")):
        out = _landed(w, branch)
        assert out.returncode == 0 and out.stdout.startswith(want), (branch, out)
    _hold(w, "B1")
    out = _landed(w, "B1")
    assert out.stdout.startswith("LANDED: PR #1 — held doc B1.md"), out
    # Another branch's held doc lands nothing (round 2, lens A: A01).
    assert _landed(w, "B3").stdout.startswith("NOT LANDED — no pending doc"), "B3 borrowed B1's doc"
    # A published copy at the same tip is contained, so still landed (A03).
    git(w, "push", "-q", "origin", "B1:refs/heads/B1")
    assert _landed(w, "B1").stdout.startswith("LANDED: PR #1"), "a contained origin tip refused"
    _hold(w, "B2", "T2")
    assert _landed(w, "B2").stdout.startswith("NOT LANDED — no recorded PR head"), "B2 has own work"


def test_step_2a_landed_check_refuses_a_live_clone(closing):
    w, _ = closing
    _hold(w, "B3", "T3")
    clone = _clone_claim(w)
    _ws_lock(w, "T3", "B3", clone)
    out = _landed(w, "B3")
    assert out.stdout.startswith(f"NOT LANDED — workspace {clone} is at"), out
    (w / "sysop/runtime/locks/T3.lock").unlink()
    git(clone, "push", "-q", "origin", "B3")
    git(w, "fetch", "-q", "origin", "B3:refs/remotes/origin/B3")
    out = _landed(w, "B3")
    assert out.stdout.startswith("NOT LANDED — origin/B3 is at"), out


def test_step_2a_landed_check_refuses_a_dirty_workspace(closing):
    """Round 2, lens A (A04): the heredoc's uncommitted-work check had no behavioural test."""
    w, _ = closing
    _hold(w, "B1")
    git(w, "push", "-q", "origin", "B1:refs/heads/B1")
    clone = w.parent / "clone-b1"
    git(w.parent, "clone", "-q", "-b", "B1", str(w.parent / "origin.git"), str(clone))
    (clone / "dirt.txt").write_text("uncommitted\n")
    git(clone, "add", "dirt.txt")
    _ws_lock(w, "T1", "B1", clone)
    assert _landed(w, "B1").stdout.startswith(f"NOT LANDED — workspace {clone} has uncommitted"), \
        _landed(w, "B1")


def test_step_2a_landed_check_reads_origin_live(closing):
    """Round 2 (lenses A and C): a lockless clone pushes work and the primary never fetches.
    A stale remote-tracking ref read it as landed; `ls-remote` sees the push."""
    w, _ = closing
    _hold(w, "B3", "T3")
    clone = _clone_claim(w)
    git(clone, "push", "-q", "origin", "B3")
    # The primary's tracking ref is stale at the cut point, inside the head.
    assert git(w, "rev-parse", "refs/remotes/origin/B3").stdout == git(w, "rev-parse", "B3").stdout
    out = _landed(w, "B3")
    assert out.stdout.startswith("NOT LANDED — origin/B3 is at"), out
    git(w, "remote", "rename", "origin", "elsewhere")
    out = _landed(w, "B3")
    assert out.stdout.startswith("NOT LANDED — could not read origin"), out


def test_both_readers_read_a_bom_doc_the_same(closing):
    """Round 2 (lens A F3): the heredoc used `startswith('---')`, `/sitrep` the shared regex,
    so a BOM doc read as held in one and not the other."""
    w, _ = closing
    d = w / "sysop/runtime/pending-docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "B1.md").write_text('\ufeff---\nbranch: "B1"\nroadmap_ids: [T1]\n---\n\nheld\n', encoding="utf-8")
    assert _landed(w, "B1").stdout.startswith("LANDED: PR #1"), _landed(w, "B1")
    assert ss._landed_claim(w, "B1", None, None, False) == "1"
    (d / "B1.md").write_text('---\nbranch: "fix/a---b"\n---\n', encoding="utf-8")
    assert ss._held_doc_names(w, "fix/a---b") == ["B1.md"]


def test_sitrep_refuses_a_dirty_linked_worktree(squashed):
    """Round 2, lens A (A06)."""
    w, _ = squashed
    record(w)
    _hold(w, "B1")
    wt = ss.Worktree(path=w.parent / "wt-b1", branch="B1", head="", is_main=False)
    assert ss._landed_claim(w, "B1", None, wt, True) == ""
    assert ss._landed_claim(w, "B1", None, wt, False) == "1"


def test_a_held_task_is_never_called_stale(squashed, monkeypatch):
    """Round 2, lens C (7): with the heads excluded a held task the landed test declines reads
    0 commits ahead, and the stale arm would have advised removing its lock."""
    w, _ = squashed
    record(w)
    _hold(w, "B3", "T3")
    clone = _clone_claim(w)                      # its work moved past the head: not landed
    lock = _ws_lock(w, "T3", "B3", clone)
    lock.path.write_text(lock.path.read_text().replace("2026-09-30T00:00:00Z", "2026-01-01T00:00:00Z"))
    t3 = _survey(w, monkeypatch)["T3"]
    assert t3.state != "stale", (t3.state, t3.next_action)
    assert any("not stale" in n for n in t3.notes), t3.notes


def test_step_2a_landed_check_stops_on_a_placeholder(closing):
    w, _ = closing
    script = _from_tree(_fence_with(_close(), LANDED_MARKER))
    out = sh(w, script)
    assert out.returncode == 3 and "STOP" in out.stdout, out


def test_step_4c_1b_asks_the_heads(closing):
    w, _ = closing
    held = _fence_with(_close(), 'git for-each-ref --contains "refs/heads/<branch from frontmatter>"')
    assert sh(w, held.replace("<branch from frontmatter>", "B1")).stdout.strip() \
        == "refs/sysop/merged-pr-heads/1"
    assert sh(w, held.replace("<branch from frontmatter>", "B2")).stdout.strip() == ""
    # 1b's own ancestry test cannot see it: the branch is in no ancestry of HEAD.
    assert git(w, "rev-list", "--count", "B1", "^HEAD").stdout.strip() != "0"


def test_two_heads_with_multi_digit_numbers(squashed):
    """Lens A, round 1: every fixture recorded one head, PR #1, so a glob that matched one
    digit and a head choice that took the first ref both passed. Here PR #9 is the close B2
    was cut before, and PR #10 a later close that B2 never met; `10` sorts before `9`."""
    w, head1 = squashed
    git(w, "push", "-q", "origin", f"{head1}:refs/pull/9/head")
    assert record(w, "9").returncode == 0
    _flip(w, "T3", "in_progress")
    git(w, "checkout", "-q", "-b", "merge/review-close-2", "main")
    _flip(w, "T3", "done", "docs: review-close consolidate 2")
    head2 = git(w, "rev-parse", "HEAD").stdout.strip()
    sq2 = git(w, "commit-tree", "HEAD^{tree}", "-p", "origin/main", "-m", "squash (#10)").stdout.strip()
    git(w, "push", "-q", "origin", f"{sq2}:refs/heads/main", f"{head2}:refs/pull/10/head")
    git(w, "checkout", "-q", "main")
    git(w, "fetch", "-q", "origin", "main")
    git(w, "reset", "-q", "--hard", "origin/main")
    git(w, "branch", "-q", "-D", "merge/review-close-2")
    assert record(w, "10").returncode == 0
    assert subjects(ss._commits_ahead_of_main("B2", w)) == ["feat: w2.txt"]
    git(w, "checkout", "-q", "-b", "merge/review-close-3", "main")
    out = _heredoc(w, "B2", "merge/review-close-3")
    lines = out.stdout.splitlines()
    assert lines[0] == "RECORDED HEAD: refs/sysop/merged-pr-heads/9", out.stdout
    assert lines[-1] == "REPLAY 1 commit(s)", out.stdout


def test_a_branch_cut_after_the_squash_has_no_head(closing):
    """Round 2, lens A (A08): heads exist, but none holds anything this branch carries."""
    w, _ = closing
    git(w, "branch", "fresh", "main")
    git(w, "checkout", "-q", "fresh")
    (w / "f.txt").write_text("f\n")
    git(w, "add", "f.txt")
    git(w, "commit", "-qm", "feat: fresh")
    git(w, "checkout", "-q", "merge/review-close-2")
    out = _heredoc(w, "fresh", "merge/review-close-2")
    assert out.stdout.strip() == "RECORDED HEAD: none", out


def test_the_most_containing_head_unusable_means_not_usable(squashed):
    """Round 2, lens A (F1): B2 merged local main while it held T3's claim, then a second close
    recorded PR #2. PR #1's head holds the most of B2's commits and is unusable; round 1's
    choice of the runner-up replayed PR #1's claim flips into a conflict it misnamed."""
    w, head1 = squashed
    assert record(w).returncode == 0
    _flip(w, "T3", "in_progress")
    git(w, "checkout", "-q", "B2")
    git(w, "merge", "-q", "--no-edit", "main", check=False)
    if git(w, "diff", "--name-only", "--diff-filter=U").stdout:
        git(w, "checkout", "--theirs", "tasks/index.yml")
        git(w, "commit", "-qam", "merge main")
    git(w, "checkout", "-q", "-b", "merge/review-close-2", "main")
    _flip(w, "T3", "done", "docs: review-close consolidate 2")
    head2 = git(w, "rev-parse", "HEAD").stdout.strip()
    sq2 = git(w, "commit-tree", "HEAD^{tree}", "-p", "origin/main", "-m", "squash (#2)").stdout.strip()
    git(w, "push", "-q", "origin", f"{sq2}:refs/heads/main", f"{head2}:refs/pull/2/head")
    git(w, "checkout", "-q", "main")
    git(w, "fetch", "-q", "origin", "main")
    git(w, "reset", "-q", "--hard", "origin/main")
    git(w, "branch", "-q", "-D", "merge/review-close-2")
    assert record(w, "2").returncode == 0
    git(w, "checkout", "-q", "-b", "merge/review-close-3", "main")
    out = _heredoc(w, "B2", "merge/review-close-3")
    assert out.stdout.startswith("RECORDED HEAD: not usable — refs/sysop/merged-pr-heads/1"), out.stdout


def test_only_pr_ten_recorded_still_excludes(squashed):
    """A glob that matches a single character would miss every PR from #10 on."""
    w, head = squashed
    git(w, "push", "-q", "origin", f"{head}:refs/pull/10/head")
    assert record(w, "10").returncode == 0
    assert subjects(ss._commits_ahead_of_main("B2", w)) == ["feat: w2.txt"]


def test_step_1a_and_step_2a_listings_leave_out_the_stale_flips(closing):
    """Since Phase 421 (`Q-665`) Step 1a's count is `close_state.py`'s and Step 2a's listing runs
    through `git_ro.py`; both still leave out the commits a recorded PR head holds."""
    import sys
    w, _ = closing
    text = _close()
    scripts = Path(__file__).resolve().parents[1] / "core" / "companion" / "scripts"
    src = (scripts / "close_state.py").read_text(encoding="utf-8")
    assert ("log = git('log', '--oneline', f'refs/heads/{default}..refs/heads/{branch}', '--not',\n"
            "                  '--glob=refs/sysop/merged-pr-heads/*')") in src
    count = lambda b: len(sh(w, "git log --oneline refs/heads/main..refs/heads/" + b
                             + " --not --glob='refs/sysop/merged-pr-heads/*'").stdout.splitlines())
    assert count("B3") == 0, "Step 1a still reads an unstarted claim as AHEAD"
    assert count("B2") == 1
    listing = _inline(text, "python3 sysop/scripts/git_ro.py . log refs/heads/<default branch>..refs/heads/<branch> --not")
    listing = listing.replace("python3 sysop/scripts/git_ro.py", f'"{sys.executable}" "{scripts}/git_ro.py"')
    out = sh(w, listing.replace("<default branch>", "main").replace("<branch>", "B2")).stdout
    assert [l.split(" ", 1)[1] for l in out.splitlines()] == ["feat: w2.txt"], out


def test_claim_task_option_c_reads_an_unstarted_claim_as_empty(closing):
    w, _ = closing
    cmd = _fence_with(CLAIM.read_text(encoding="utf-8"),
                      "git rev-list --count <default branch>..refs/heads/<BRANCH_NAME>")
    out = sh(w, cmd.replace("<default branch>", "main").replace("<BRANCH_NAME>", "B3"))
    assert out.stdout.strip() == "0", out


def test_published_stale_conflict_continues_with_merge_continue(closing):
    """`Q-637`, closed here: the published arm's stale `status:` conflict is resolved to the
    target's side and continued with the command the skill names; `rebase --continue`
    fails on a merge."""
    w, _ = closing
    merged = git(w, "merge", "--no-ff", "-m", "merge B2 (published — not rebased)", "B2", check=False)
    assert merged.returncode != 0
    text = (w / "tasks/index.yml").read_text()
    resolved = re.sub(r"<<<<<<< [^\n]*\n(.*?)=======\n.*?>>>>>>> [^\n]*\n", r"\1", text, flags=re.S)
    (w / "tasks/index.yml").write_text(resolved)
    git(w, "add", "tasks/index.yml")
    assert sh(w, "git -c core.editor=true rebase --continue").returncode != 0
    cont = _inline(_close(), "git -c core.editor=true merge --continue")
    done = subprocess.run(["/bin/bash", "-c", cont], cwd=w, env=_ENV, capture_output=True,
                          text=True, stdin=subprocess.DEVNULL)
    assert done.returncode == 0, done
    assert len(git(w, "rev-list", "--parents", "-1", "HEAD").stdout.split()) == 3
    assert "status: done" in (w / "tasks/index.yml").read_text().split("- id: T2")[0]


def test_the_merge_continue_rule_is_seeded_exactly():
    """An exact-match rule: `Bash(git merge --no-ff:*)` does not cover `git -c … merge`,
    because `-c` is not a wrapper the matcher strips, so the published arm's continue
    needs its own seeded rule or every such conflict routes to the classifier."""
    import json
    allow = json.loads((REPO / "core/companion/.claude/settings.json").read_text())["permissions"]["allow"]
    assert "Bash(git -c core.editor=true merge --continue)" in allow


# ─────────────────────────────────────────────────────────────────────────────
# Hash pins over the text Phase 352 decided
# ─────────────────────────────────────────────────────────────────────────────
#
# The behaviour is executed above. What a test cannot execute is the prose the runner acts
# on: which branch is landed and what it skips, when the published arm takes the target's
# side and when it stops, and that a failed record does not stop a landed merge. A
# substring check survives a negation beside the right sentence; a hash over the span does
# not. A deliberate change moves its pin in the same commit (`_print_pins()`).

from _reversal import slice_between  # noqa: E402
from _shipped_scripts import subcommand_body  # noqa: E402
from test_fix_in_branch_tier import (_anchor_count, _pin_hash, _pin_liveness, _pin_program,  # noqa: E402
                                     _pin_norm, _pin_span)

SPANS: dict[str, tuple[Path, str, str, bool]] = {
    "2a landed check": (CLOSE, "**Landed check.** Ask whether a previous close",
                        "1. `python3 sysop/scripts/git_ro.py . log refs/heads/<default branch>..refs/heads/<branch> --not", False),
    "2b landed not a target": (CLOSE, "Nor is a branch Step 2a approved as landed (step 0b",
                               "\n\n", False),
    "4a recorded head": (CLOSE, "**Then ask whether a recorded PR head contains any of its commits**",
                         "See `REFERENCE.md` § *Squash provenance", False),
    "4a local-only onto": (CLOSE, "**When item 1 printed `RECORDED HEAD: <ref>`, rebase with `--onto` instead**",
                           "   - **Published**", False),
    "4a published stale status": (CLOSE, "**When item 1 printed `RECORDED HEAD: <ref>` and the merge stops",
                                  "\n     Rebasing a published branch", False),
    "shared append status": (CLOSE, "**a conflict on a `status:` line is the one shape here",
                             " `/document-work` **requires**", False),
    "4c 1b recorded heads": (CLOSE, "**On a non-zero count, ask the recorded PR heads",
                             "\n\n   > **It is an ancestry test", False),
    "4d record": (CLOSE, "**record the head of that PR**",
                  "**If a `gh pr` command is silently denied**", False),
    "step 8 squash provenance": (CLOSE, "Squash provenance: <`pr` only", "\nLocks cleaned:", True),
    "2d landed skipped": (CLOSE, "For each **approved** feature branch (Step 2a verdict) except one approved as landed",
                          "\n\n", False),
    "WORKFLOW recorded heads": (WF, "The skill merges a published branch with `--no-ff` instead of rebasing it",
                                " **A rebase conflict is routed", False),
    "uninstall ref removal": (IU, "**Delete the recorded PR heads**", "\n- **Plugin users:**", False),
    "step 6 recorded-merged cleanup": (CLOSE, "Force-delete here; the content is safely in `main`. A branch Step 4a recorded",
                                       "\n\n", False),    "4a-post recorded-merged not counted": (CLOSE, "Do not count a branch Step 4a item 1 recorded", "\n", False),
    "4d-1 record outside the run": (CLOSE, "**A PR merged outside this run**", "\n", False),
    "merge continue rule": (CLOSE, "`Bash(git -c core.editor=true merge --continue)` — exact match", "\n", False),
    # Phase 429's round (lens B): the inventory's `--no-ff` line was under no guard, so a rule
    # renamed to another seeded one passed every test; the published arm's merge needs it.
    "merge no-ff rule": (CLOSE, "`Bash(git merge --no-ff:*)` — Step 4a's **published** arm", "\n", False),
}

PINS = {
    # Regenerate with:  .venv/bin/python3 -c "import sys; sys.path.insert(0,'tests'); import test_squash_provenance as T; T._print_pins()"
    "2a landed check": "e055069a3203431f",  # Phase 387: the span plus feature_branch.py landed, the heredoc moved verbatim, appended fenced so its indentation counts (round 1) (Phase 380: dict(...) env-strip)
    "2b landed not a target": "b451c64d35fc19a9",
    "4a recorded head": "34b3325798e6e052",  # Phase 387: the span plus pr_head_check.py, the heredoc moved verbatim, appended fenced so its indentation counts (round 1)
    "4a local-only onto": "e28d544a201e5344",
    "4a published stale status": "4683e760d0b82465",  # Phase 425 (`Q-629`): `tasks/index.yml`'s resolution is the arm's `index --since`
    "shared append status": "3f3a06552dbf9c66",  # Phase 390's round: the bullet sits in `steps/4a-append.md`, and its "item 2" names Step 4a
    "4c 1b recorded heads": "c36a8758e19f97cc",
    "4d record": "04f919f75c731e48",  # Phase 422 (`Q-665`): the record's `; echo "$?"` tail went (denied under `dontAsk`); the command's own exit is read
    "step 8 squash provenance": "a4194238cfe0281c",
    "2d landed skipped": "1b92ad9e9fd08fa5",
    "WORKFLOW recorded heads": "93850235e2f1824e",
    "uninstall ref removal": "3125b52a27b0ad21",
    "step 6 recorded-merged cleanup": "34cf890ae463254a",
    "4a-post recorded-merged not counted": "e09b4ee59160b31c",
    "4d-1 record outside the run": "17a8e4aa921890fe",
    "merge continue rule": "8444ef0f80cd7597",
    "merge no-ff rule": "dbf81975b78e70eb",
}


def _located(label: str) -> tuple[str, str, int]:
    path, start, end, _ = SPANS[label]
    text = text_of(path)
    span = slice_between(text, start, end, label)
    return text, span, text.index(span)


# Since Phase 387 (`Q-409` P3) the decided programs of these two spans are shipped scripts,
# so each pin covers its prose span plus the program it runs.
_PROGRAMS = {
    "2a landed check": lambda: subcommand_body("feature_branch.py", "landed"),
    "4a recorded head": lambda: (SCRIPTS / "pr_head_check.py").read_text(encoding="utf-8"),
}


def _span(label: str) -> str:
    text, span, at = _located(label)
    span = _pin_span(SPANS[label][0], text, at, span)
    assert len(_pin_norm(span)) > 60, f"{label}: the pinned span is nearly empty — anchors drifted"
    return span


def _pinned(label: str) -> str:
    """What a pin hashes: the span, plus the program a moved heredoc became (Phase 387)."""
    return _span(label) + _pin_program(_PROGRAMS[label]()) if label in _PROGRAMS else _span(label)


def _print_pins() -> None:
    for label in SPANS:
        print(f'    "{label}": "{_pin_hash(_pinned(label))}",')


@pytest.mark.parametrize("label", sorted(SPANS))
def test_the_decided_text_is_pinned(label: str) -> None:
    got = _pin_hash(_pinned(label))
    assert label in PINS, f'{label}: no pin recorded; add "{label}": "{got}"'
    assert got == PINS[label], (
        f"{label} changed (hash {got}, pinned {PINS[label]}). Phase 352 decided this text. "
        "If the edit is deliberate, move the pin in the same commit and record why.")


@pytest.mark.parametrize("label", sorted(SPANS))
def test_every_span_start_anchor_is_unique(label: str) -> None:
    path, start, _, _ = SPANS[label]
    assert _anchor_count(text_of(path), start) == 1, label


@pytest.mark.parametrize("label", sorted(SPANS))
def test_every_span_is_live(label: str) -> None:
    text, _, at = _located(label)
    problem = _pin_liveness(SPANS[label][0], text, at, SPANS[label][3])
    assert problem is None, f"{label} {problem}"


def test_every_pin_has_a_span() -> None:
    assert set(PINS) == set(SPANS), set(PINS) ^ set(SPANS)
