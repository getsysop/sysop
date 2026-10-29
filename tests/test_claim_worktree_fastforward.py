"""`claim_task.sh --commit-claim` brings the claim's own worktree up to the claim commit
(`Q-532` #587).

**The defect.** Both callers run `--lock` before `--commit-claim` (`/claim-task` 4b then
4d, `/auto-build` 5.2 then 5.4), and `--lock` branches from the default branch as it
stood then, one commit short of the claim. The worktree's own `tasks/index.yml` then read
`open` for the task it was made for, and every planner, reviewer and executor works in
that worktree. A consumer's reviewer read it as "the claim never landed" and filed a false
HIGH (upstream #587).

**The fix, and the one the reporter proposed.** The reporter proposed flip -> validate ->
commit -> `--lock`; its own validate step fails, because `validate_tasks.py`'s invariant 9
errors on an `in_progress` task with no lock. So `--commit-claim` reads the default branch's
ref before it releases the tracker mutex, fast-forwards the claim's worktree to it after, with
`--no-overwrite-ignore`, and states every case where it cannot.

**What these tests run.** Real subprocesses over the shipped script in a scratch repo
built with `-b main`: the fixture reproduces the defect first (the control), then each
arm of the new block. Every skip arm must exit 0, because the claim is committed, and must
print its `⚠️` or `ℹ️` line, because a silent skip is the state the block exists to end.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
TID = "TECH-0001"
BRANCH = "tech/tech-0001"


def _a_pyyaml_interpreter_is_reachable() -> bool:
    """The script's own order: the venv candidates, then `python3` on PATH. Same
    predicate as `test_claim_commit_mutex.py`, for the reason its docstring gives:
    gating on a `.venv` merely existing hid the module on CI."""
    for cand in (REPO_ROOT / ".venv/bin/python3", REPO_ROOT / "venv/bin/python3"):
        if cand.exists() and subprocess.run(
                [str(cand), "-c", "import yaml"], capture_output=True).returncode == 0:
            return True
    found = shutil.which("python3")
    return bool(found) and subprocess.run(
        [found, "-c", "import yaml"], capture_output=True).returncode == 0


# Per test, not module-wide: the prose guard at the bottom reads files only, and a
# module-level mark would take it dark with the rest on a checkout with no interpreter.
needs_interpreter = pytest.mark.skipif(
    not _a_pyyaml_interpreter_is_reachable(),
    reason="claim_task.sh --commit-claim needs an interpreter with PyYAML; none is reachable",
)


def _git(root, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                          text=True, check=check)


def _index() -> str:
    body = ["schema_version: 1", "tasks:"]
    for tid in (TID, "TECH-0002"):
        body += [f"  - id: {tid}", f"    title: task {tid}", "    status: open",
                 "    kind: tech", "    effort: 1", "    priority: medium",
                 f"    body: open/{tid}.md"]
    return "\n".join(body) + "\n"


def _build(tmp_path, branch="main"):
    main = tmp_path / "main"
    (main / "tasks" / "open").mkdir(parents=True)
    (main / "sysop" / "scripts").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", branch, str(main))
    _git(main, "config", "user.email", "t@example.invalid")
    _git(main, "config", "user.name", "t")
    (main / ".gitignore").write_text("sysop/runtime/\n.venv/\n")
    (main / "tasks" / "index.yml").write_text(_index())
    for tid in (TID, "TECH-0002"):
        (main / "tasks" / "open" / f"{tid}.md").write_text(f"# {tid}\n")
    for name in ("claim_task.sh", "_git_lib.sh", "validate_tasks.py",
                 "default_branch.sh", "_log.py"):
        src = SCRIPTS / name
        if src.exists():
            (main / "sysop" / "scripts" / name).write_bytes(src.read_bytes())
    venv = REPO_ROOT / ".venv"
    if (venv / "bin" / "python3").exists():
        (main / ".venv").symlink_to(venv)
    _git(main, "add", "-A")
    _git(main, "commit", "-qm", "init")
    return main


@pytest.fixture
def repo(tmp_path):
    return _build(tmp_path)


def _run(repo, *args):
    return subprocess.run(["bash", "sysop/scripts/claim_task.sh", *args],
                          cwd=str(repo), capture_output=True, text=True)


def _lock(repo):
    r = _run(repo, "--lock", TID, BRANCH)
    assert r.returncode == 0, r.stdout + r.stderr
    ws = None
    for ln in (repo / "sysop/runtime/locks" / f"{TID}.lock").read_text().splitlines():
        if ln.startswith("workspace:"):
            ws = Path(ln.split(":", 1)[1].strip())
    assert ws is not None and ws.is_dir(), "the lock names no existing workspace"
    return ws


def _status_in(tree, task_id=TID):
    cur = None
    for ln in (Path(tree) / "tasks" / "index.yml").read_text().splitlines():
        s = ln.strip()
        if s.startswith("- id:"):
            cur = s.split(":", 1)[1].strip()
        elif s.startswith("status:") and cur == task_id:
            return s.split(":", 1)[1].strip()
    return None


def _head(tree):
    return _git(tree, "rev-parse", "HEAD").stdout.strip()


@needs_interpreter
def test_control_the_fixture_reproduces_the_defect(repo):
    """Without `--commit-claim` the worktree sits one claim short. If this ever reads
    `in_progress`, the fixture no longer exercises the defect and every test below is
    vacuous."""
    ws = _lock(repo)
    assert _status_in(ws) == "open"


@needs_interpreter
def test_the_worktree_reads_its_own_claim(repo):
    ws = _lock(repo)
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Fast-forwarded" in r.stdout
    assert _status_in(repo) == "in_progress"
    assert _status_in(ws) == "in_progress"
    assert _head(ws) == _head(repo)
    assert _git(ws, "branch", "--show-current").stdout.strip() == BRANCH


@needs_interpreter
def test_a_rerun_is_a_stated_no_op(repo):
    ws = _lock(repo)
    assert _run(repo, "--commit-claim", TID).returncode == 0
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "is already at main (" in r.stdout and "which holds the claim" in r.stdout
    # Phase 400 moved the commit's success line behind a flag; the resume arm commits
    # nothing and must not print it (round 2, lens D).
    assert "nothing to commit (resume path)" in r.stdout
    assert "Committed the claim" not in r.stdout
    assert _head(ws) == _head(repo)


@needs_interpreter
def test_a_rerun_repairs_a_worktree_left_behind(repo):
    """The resume arm commits nothing, and it still brings a stale worktree up."""
    ws = _lock(repo)
    flip = (repo / "tasks" / "index.yml").read_text().replace(
        "status: open", "status: in_progress", 1)
    (repo / "tasks" / "index.yml").write_text(flip)
    _git(repo, "commit", "-qam", f"claim: mark {TID} as in-progress")
    assert _status_in(ws) == "open"
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "nothing to commit (resume path)" in r.stdout
    assert "Fast-forwarded" in r.stdout
    assert _status_in(ws) == "in_progress"


@needs_interpreter
def test_a_branch_with_its_own_commits_is_left_and_said_so(repo):
    ws = _lock(repo)
    (ws / "work.txt").write_text("executor work\n")
    _git(ws, "add", "work.txt")
    _git(ws, "commit", "-qm", "work")
    before = _head(ws)
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "⚠️" in r.stdout and "commits of its own" in r.stdout
    assert f"may still read 'open' for {TID}" in r.stdout
    assert "not a lost claim" in r.stdout
    assert _head(ws) == before
    assert _status_in(repo) == "in_progress"


@needs_interpreter
def test_uncommitted_tracked_changes_block_and_survive(repo):
    ws = _lock(repo)
    body = ws / "tasks" / "open" / f"{TID}.md"
    body.write_text("# edited, not committed\n")
    before = _head(ws)
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "⚠️" in r.stdout and "uncommitted changes" in r.stdout
    assert _head(ws) == before
    assert body.read_text() == "# edited, not committed\n"


@needs_interpreter
def test_an_untracked_file_does_not_block_and_survives(repo):
    ws = _lock(repo)
    note = ws / "scratch-notes.txt"
    note.write_text("mine\n")
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Fast-forwarded" in r.stdout
    assert note.read_text() == "mine\n"


def _main_starts_tracking(repo, name, text):
    """Another session's commit on the default branch adds `name`, after `--lock`
    branched, so the fast-forward would write it into the worktree."""
    (repo / name).write_text(text)
    _git(repo, "add", "-f", name)
    _git(repo, "commit", "-qm", f"track {name}")


@needs_interpreter
def test_an_ignored_file_the_fast_forward_would_overwrite_blocks_and_survives(repo):
    """Round 1, lens A: `git merge` refuses over an untracked file but overwrites an
    IGNORED one silently, and the first cut printed its success line over the loss."""
    ws = _lock(repo)
    (ws / "local.cfg").write_text("PRECIOUS\n")
    exclude = Path(_git(repo, "rev-parse", "--git-common-dir").stdout.strip())
    if not exclude.is_absolute():
        exclude = repo / exclude
    with open(exclude / "info" / "exclude", "a") as f:
        f.write("local.cfg\n")
    assert _git(ws, "check-ignore", "-q", "local.cfg", check=False).returncode == 0
    _main_starts_tracking(repo, "local.cfg", "shared default\n")
    before = _head(ws)
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "⚠️" in r.stdout and "git refused the fast-forward" in r.stdout
    assert "local.cfg" in r.stdout + r.stderr
    assert (ws / "local.cfg").read_text() == "PRECIOUS\n"
    assert _head(ws) == before


@needs_interpreter
def test_an_untracked_file_the_fast_forward_would_write_blocks_and_survives(repo):
    ws = _lock(repo)
    (ws / "notes.md").write_text("mine\n")
    _main_starts_tracking(repo, "notes.md", "theirs\n")
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "⚠️" in r.stdout and "git refused the fast-forward" in r.stdout
    assert (ws / "notes.md").read_text() == "mine\n"


@needs_interpreter
def test_an_ignored_file_elsewhere_does_not_block(repo):
    """The clobber check is scoped to the paths the fast-forward writes. An empty
    pathspec would list every untracked file, so an unrelated ignored file must not
    read as a collision."""
    ws = _lock(repo)
    (ws / ".venv-local").mkdir()
    (ws / ".venv-local" / "x").write_text("x\n")
    exclude = Path(_git(repo, "rev-parse", "--git-common-dir").stdout.strip())
    if not exclude.is_absolute():
        exclude = repo / exclude
    with open(exclude / "info" / "exclude", "a") as f:
        f.write(".venv-local/\n")
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Fast-forwarded" in r.stdout
    assert (ws / ".venv-local" / "x").read_text() == "x\n"


@needs_interpreter
def test_no_lock_is_stated(repo):
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "No lock for" in r.stdout
    assert _status_in(repo) == "in_progress"


@needs_interpreter
def test_a_non_worktree_claim_is_stated(repo):
    _lock(repo)
    lock = repo / "sysop/runtime/locks" / f"{TID}.lock"
    lock.write_text(lock.read_text().replace("mode: worktree", "mode: clone"))
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "mode 'clone', which this step does not move" in r.stdout
    assert "may still read 'open'" in r.stdout


@needs_interpreter
def test_a_missing_workspace_is_stated(repo):
    ws = _lock(repo)
    _git(repo, "worktree", "remove", "--force", str(ws))
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "⚠️" in r.stdout and "does not exist" in r.stdout


@needs_interpreter
def test_a_workspace_on_another_branch_is_left(repo):
    ws = _lock(repo)
    _git(ws, "checkout", "-q", "-b", "elsewhere")
    before = _head(ws)
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "⚠️" in r.stdout and f"not on '{BRANCH}'" in r.stdout
    assert _head(ws) == before


@needs_interpreter
def test_it_works_when_run_from_inside_the_claim_worktree(repo):
    """The script resolves the primary checkout and the lock itself, so a caller standing
    in the claim worktree gets the same result (round 1, lens B: every other test runs it
    from the primary)."""
    ws = _lock(repo)
    r = subprocess.run(["bash", str(repo / "sysop/scripts/claim_task.sh"), "--commit-claim", TID],
                       cwd=str(ws), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Fast-forwarded" in r.stdout
    assert _status_in(ws) == "in_progress"


def _section(text, start, stop):
    i = text.index(start)
    j = text.index(stop, i + len(start))
    return " ".join(text[i:j].split())


def test_the_skills_say_what_the_script_now_does():
    """Both callers name the fast-forward and the `⚠️` exit-0 case INSIDE the step that
    runs it, so a runner reading a `⚠️` line knows it is not a failed claim. Whole
    clauses, because `⚠️` and "fast-forward" occur elsewhere in both files, and scoped to
    the step, because a sentence moved to the end of the file passes a whole-file check
    (round 1, lens B: both survived the first cut)."""
    claim = _section((REPO_ROOT / "core/skills/claim-task/SKILL.md").read_text(),
                     "### 4d. Commit the claim on the default branch", "### Rollback on failure of 4b or 4c")
    build = _section((REPO_ROOT / "core/skills/auto-build/SKILL.md").read_text(),
                     "## Step 5: Sequential Pre-Claim on Main", "**Abort handling:**")
    assert ("**It then fast-forwards this claim's worktree to the default branch, which now "
            "holds the claim**, so every agent in Step 7 reads this task as "
            "`in_progress` there.") in claim
    assert ("it prints a `⚠️` line saying so and still exits 0: the claim is committed, and "
            "an `open` read in that worktree is the pre-claim tree, not a lost claim.") in claim
    assert ("5.4's script also fast-forwards the task's worktree to the default branch, which "
            "now holds its claim:") in build
    assert ("A `⚠️` line from 5.4 means it could not, and that it still exited 0 over a "
            "committed claim.") in build


def test_the_workflow_spec_says_what_the_mode_does():
    wf = " ".join((REPO_ROOT / "core/companion/docs/WORKFLOW.md").read_text().split())
    bullet = _section(wf, "- `bash sysop/scripts/claim_task.sh --commit-claim <TASK_ID>`",
                      "- `bash sysop/scripts/claim_task.sh --release <TASK_ID>`")
    assert ("**After the commit it fast-forwards the claim's own worktree to the default branch, "
            "which now holds the claim** (`Q-532`), reading the branch's ref (never `HEAD`") in bullet
    assert "it merges with `--no-overwrite-ignore`" in bullet
    assert "each such skip prints a `⚠️` line and exits 0, since the claim is committed." in bullet
    assert "`git merge` overwrites an ignored file without a word" in bullet


def _exclude(repo, pattern):
    common = Path(_git(repo, "rev-parse", "--git-common-dir").stdout.strip())
    if not common.is_absolute():
        common = repo / common
    with open(common / "info" / "exclude", "a") as f:
        f.write(pattern + "\n")


@needs_interpreter
def test_an_ignored_file_that_becomes_a_directory_survives(repo):
    """Round 2, lens C: an exact-path check missed this; the incoming commit adds `foo/bar`
    over an ignored file `foo`, and `git merge` deleted `foo` to make the directory."""
    ws = _lock(repo)
    (ws / "foo").write_text("PRECIOUS\n")
    _exclude(repo, "foo")
    (repo / "foo").mkdir()
    (repo / "foo" / "bar").write_text("theirs\n")
    _git(repo, "add", "-f", "foo/bar")
    _git(repo, "commit", "-qm", "track foo/bar")
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "⚠️" in r.stdout
    assert (ws / "foo").is_file() and (ws / "foo").read_text() == "PRECIOUS\n"


@needs_interpreter
def test_an_ignored_symlink_that_becomes_a_directory_survives(repo, tmp_path):
    ws = _lock(repo)
    outside = tmp_path / "outside"
    outside.mkdir()
    (ws / "lnkdir").symlink_to(outside)
    _exclude(repo, "lnkdir")
    (repo / "lnkdir").mkdir()
    (repo / "lnkdir" / "new").write_text("theirs\n")
    _git(repo, "add", "-f", "lnkdir/new")
    _git(repo, "commit", "-qm", "track lnkdir/new")
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "⚠️" in r.stdout
    assert (ws / "lnkdir").is_symlink()


def _case_insensitive(path):
    probe = path / "CaseProbe"
    probe.write_text("x")
    try:
        return (path / "caseprobe").exists()
    finally:
        probe.unlink()


@needs_interpreter
def test_a_case_folded_ignored_name_survives(repo):
    """On a case-insensitive filesystem (macOS's default) an ignored `Local.cfg` and an
    incoming `local.cfg` are one file. Skipped where the filesystem is case-sensitive,
    because there they are two files and nothing is overwritten."""
    if not _case_insensitive(repo):
        pytest.skip("filesystem is case-sensitive: Local.cfg and local.cfg do not collide")
    ws = _lock(repo)
    (ws / "Local.cfg").write_text("PRECIOUS\n")
    _exclude(repo, "Local.cfg")
    _exclude(repo, "local.cfg")
    _main_starts_tracking(repo, "local.cfg", "theirs\n")
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "⚠️" in r.stdout
    assert (ws / "Local.cfg").read_text() == "PRECIOUS\n"


@needs_interpreter
@pytest.mark.parametrize("trigger,resume", [
    ("diff --cached --quiet", True),
    ("commit -q -m claim: mark", False),
])
def test_a_concurrent_checkout_does_not_steer_the_fast_forward(repo, tmp_path, trigger, resume):
    """Round 2, lens C: reading `HEAD` for the target let a concurrent `git checkout` in the
    primary checkout merge another branch's unmerged commits into the claim worktree. A
    `git` shim runs that checkout once, at the named step; the worktree must land on the
    default branch with no foreign file."""
    import os
    ws = _lock(repo)
    _git(repo, "branch", "other")
    other_wt = tmp_path / "otherwt"
    _git(repo, "worktree", "add", "-q", str(other_wt), "other")
    (other_wt / "foreign.txt").write_text("unmerged\n")
    _git(other_wt, "add", "foreign.txt")
    _git(other_wt, "commit", "-qm", "foreign")
    _git(repo, "worktree", "remove", str(other_wt))
    if resume:
        flip = (repo / "tasks" / "index.yml").read_text().replace(
            "status: open", "status: in_progress", 1)
        (repo / "tasks" / "index.yml").write_text(flip)
        _git(repo, "commit", "-qam", f"claim: mark {TID} as in-progress")
    real = shutil.which("git")
    shim = tmp_path / "shim"
    shim.mkdir()
    once = shim / "once"
    (shim / "git").write_text(
        "#!/bin/bash\n"
        f'"{real}" "$@"; rc=$?\n'
        f'case " $* " in *"{trigger}"*) if [[ ! -e "{once}" ]]; then : > "{once}"; '
        f'"{real}" -C "{repo}" checkout -q other; fi ;; esac\n'
        "exit $rc\n")
    (shim / "git").chmod(0o755)
    env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}")
    r = subprocess.run(["bash", "sysop/scripts/claim_task.sh", "--commit-claim", TID],
                       cwd=str(repo), capture_output=True, text=True, env=env)
    assert once.exists(), "the shim never fired, so this test exercised nothing"
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (ws / "foreign.txt").exists()
    assert _head(ws) == _git(repo, "rev-parse", "refs/heads/main").stdout.strip()
    assert _status_in(ws) == "in_progress"


@needs_interpreter
def test_a_master_repo_fast_forwards_to_master(tmp_path):
    """Round 3, lens D: every other fixture is `-b main`, so a target read hard-coded to
    `refs/heads/main` passed them all."""
    repo = _build(tmp_path, branch="master")
    ws = _lock(repo)
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Fast-forwarded" in r.stdout and "to master (" in r.stdout
    assert _head(ws) == _git(repo, "rev-parse", "refs/heads/master").stdout.strip()
    assert _status_in(ws) == "in_progress"


@needs_interpreter
def test_a_tip_that_stops_holding_the_claim_fails(repo, tmp_path):
    """Round 3, lens D: the default branch rewound to before the claim between the commit
    and the target read. The worktree is already at that tip, and the first cut printed
    "which holds the claim" over a worktree reading `open`. Phase 392 made that a `⚠️`
    over exit 0, under a footer saying the claim is committed on the default branch;
    Phase 400's round found the footer false, so it is an exit 1."""
    import os
    ws = _lock(repo)
    pre = _head(repo)
    real = shutil.which("git")
    shim = tmp_path / "shim"
    shim.mkdir()
    once = shim / "once"
    # Fired after the commit's own ref check (`Q-404`; `claim_held_at`'s read is its
    # only `cat-file --filters`): a rewind AT the commit is
    # now the commit's failure, tested below; this one comes after it has passed.
    (shim / "git").write_text(
        "#!/bin/bash\n"
        f'"{real}" "$@"; rc=$?\n'
        f'case " $* " in *"cat-file --filters"*) if [[ ! -e "{once}" ]]; then : > "{once}"; '
        f'"{real}" -C "{repo}" update-ref refs/heads/main {pre}; fi ;; esac\n'
        "exit $rc\n")
    (shim / "git").chmod(0o755)
    env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}")
    r = subprocess.run(["bash", "sysop/scripts/claim_task.sh", "--commit-claim", TID],
                       cwd=str(repo), capture_output=True, text=True, env=env)
    assert once.exists(), "the shim never fired, so this test exercised nothing"
    assert r.returncode == 1, r.stdout + r.stderr
    assert "✅ Committed the claim" in r.stdout
    assert "✅ " + str(ws) not in r.stdout and "Fast-forwarded" not in r.stdout
    assert "no longer reads TECH-0001 as in_progress" in r.stderr
    assert "the claim is committed on" not in r.stdout + r.stderr
    assert _status_in(ws) == "open"


# ── `Q-404`: the commit's own success line ───────────────────────────────────


def _shimmed_commit_claim(repo, tmp_path, trigger, action):
    """Run `--commit-claim` with a `git` shim that runs `action` (git arguments, against
    the primary checkout) once, right after the first git command whose arguments
    contain `trigger`."""
    import os
    real = shutil.which("git")
    shim = tmp_path / "shim"
    shim.mkdir()
    once = shim / "once"
    (shim / "git").write_text(
        "#!/bin/bash\n"
        f'"{real}" "$@"; rc=$?\n'
        f'case " $* " in *"{trigger}"*) if [[ ! -e "{once}" ]]; then : > "{once}"; '
        f'"{real}" -C "{repo}" {action}; fi ;; esac\n'
        "exit $rc\n")
    (shim / "git").chmod(0o755)
    env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}")
    r = subprocess.run(["bash", "sysop/scripts/claim_task.sh", "--commit-claim", TID],
                       cwd=str(repo), capture_output=True, text=True, env=env)
    assert once.exists(), "the shim never fired, so this test exercised nothing"
    return r


def _subject(repo, ref):
    return _git(repo, "log", "-1", "--format=%s", ref).stdout.strip()


@needs_interpreter
def test_a_checkout_before_the_commit_commits_nothing(repo, tmp_path):
    """Phase 392's round 3, lens D: a checkout after Rule A and before the commit put the
    claim commit on that branch, and the script printed it as committed on `main`. Rule A
    again at the commit refuses before anything is committed."""
    _lock(repo)
    _git(repo, "branch", "other")
    pre = _head(repo)
    r = _shimmed_commit_claim(repo, tmp_path, "diff --cached --quiet", "checkout -q other")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Committed the claim" not in r.stdout
    assert "moved to 'other' before the claim commit" in r.stderr
    assert "carries this claim's flip, staged" in r.stderr
    # The recovery round 1 found missing, pinned so it cannot quietly go again.
    assert "git diff --cached -- tasks/index.yml" in r.stderr
    assert "git restore --staged --worktree -- tasks/index.yml" in r.stderr
    assert _git(repo, "diff", "--cached", "--name-only").stdout.strip() == "tasks/index.yml"
    assert _git(repo, "rev-parse", "refs/heads/other").stdout.strip() == pre
    assert _git(repo, "rev-parse", "refs/heads/main").stdout.strip() == pre


@needs_interpreter
def test_a_commit_that_lands_on_another_branch_fails_loudly(repo, tmp_path):
    """The gap Rule A cannot close: a checkout between the re-check and `git commit`.
    The commit lands on `other`; the ref check after it says so and exits non-zero."""
    _lock(repo)
    _git(repo, "branch", "other")
    pre = _head(repo)
    r = _shimmed_commit_claim(repo, tmp_path, "symbolic-ref -q --short HEAD",
                              "checkout -q other")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Committed the claim" not in r.stdout
    assert "main does not hold the claim for TECH-0001: it did not move" in r.stderr
    assert "The primary checkout is on 'other'" in r.stderr
    assert _git(repo, "rev-parse", "refs/heads/main").stdout.strip() == pre
    assert _subject(repo, "other") == f"claim: mark {TID} as in-progress"


@needs_interpreter
def test_a_rewind_at_the_commit_fails_loudly(repo, tmp_path):
    """The default branch rewound to before the claim as the commit returned: the claim
    is on no branch, so the commit's success line would be false."""
    _lock(repo)
    pre = _head(repo)
    r = _shimmed_commit_claim(repo, tmp_path, "commit -q -m claim: mark",
                              f"update-ref refs/heads/main {pre}")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Committed the claim" not in r.stdout
    assert "main does not hold the claim for TECH-0001: it did not move" in r.stderr


def _commit_on(repo, tmp_path, branch, index_text, msg):
    """Commit `index_text` as tasks/index.yml on `branch` (created from HEAD) without
    touching the primary checkout; returns the commit."""
    wt = tmp_path / f"wt-{branch}"
    _git(repo, "worktree", "add", "-q", "-b", branch, str(wt))
    (wt / "tasks" / "index.yml").write_text(index_text)
    _git(wt, "commit", "-qam", msg)
    sha = _head(wt)
    _git(repo, "worktree", "remove", str(wt))
    return sha


_FOREIGN_INDEX = {
    "open": None,  # filled from the fixture: the task still open
    "absent": "schema_version: 1\ntasks:\n  - id: TECH-0002\n    status: open\n",
    "unparseable": "tasks: [\n  - id: TECH-0001\n    status: in_progress\n",
    "done": "schema_version: 1\ntasks:\n  - id: TECH-0001\n    status: done\n",
}


@needs_interpreter
@pytest.mark.parametrize("shape", sorted(_FOREIGN_INDEX))
def test_a_tip_that_does_not_hold_the_claim_fails_the_commit(repo, tmp_path, shape):
    """The default branch moved, but to a commit whose index does not read the task
    `in_progress`: still `open`, the task absent or `done`, or an index that does not
    parse.
    Each is `claim_held_at`'s non-zero arm, and each must fail the commit."""
    _lock(repo)
    pre = _head(repo)
    text = _FOREIGN_INDEX[shape] or (repo / "tasks" / "index.yml").read_text()
    foreign = _commit_on(repo, tmp_path, "other", text + "# foreign\n", "unrelated")
    assert foreign != pre
    r = _shimmed_commit_claim(repo, tmp_path, "commit -q -m claim: mark",
                              f"update-ref refs/heads/main {foreign}")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Committed the claim" not in r.stdout
    assert f"does not read {TID} as in_progress" in r.stderr


@needs_interpreter
def test_a_rewind_before_a_skip_arm_fails_too(repo, tmp_path):
    """Round 2, lens D: the tip check sat in the fast-forward block after the no-lock and
    skip arms, so a rewind there exited 0 under "No lock". It now runs before every arm."""
    pre = _head(repo)
    r = _shimmed_commit_claim(repo, tmp_path, "cat-file --filters",
                              f"update-ref refs/heads/main {pre}")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "✅ Committed the claim" in r.stdout
    assert "No lock for" not in r.stdout
    assert "no longer reads TECH-0001 as in_progress" in r.stderr


@needs_interpreter
def test_a_forced_checkout_before_the_commit_says_nothing_is_staged(repo, tmp_path):
    """Round 2, lens C: `checkout -f` discards the staged flip, and the refusal said it
    was still staged on the other branch. It now reads the index before saying so."""
    _lock(repo)
    _git(repo, "branch", "other")
    r = _shimmed_commit_claim(repo, tmp_path, "diff --cached --quiet", "checkout -q -f other")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "nothing of this claim is staged there" in r.stderr
    assert "carries this claim's flip" not in r.stderr
    assert _git(repo, "diff", "--cached", "--name-only").stdout == ""


@needs_interpreter
def test_a_filtered_index_is_read_as_the_checkout_reads_it(tmp_path):
    """Round 2, lens C: `claim_held_at` read the commit with `git show`, which prints the
    stored blob. Under a clean/smudge filter on the index (rot13 here; git-crypt in the
    field) a committed claim failed the ref check, and every re-run failed again."""
    repo = _build(tmp_path)
    rot = "tr 'A-Za-z' 'N-ZA-Mn-za-m'"
    _git(repo, "config", "filter.rot.clean", rot)
    _git(repo, "config", "filter.rot.smudge", rot)
    (repo / ".gitattributes").write_text("tasks/index.yml filter=rot\n")
    _git(repo, "add", ".gitattributes")
    _git(repo, "add", "--renormalize", "tasks/index.yml")
    _git(repo, "commit", "-qm", "filter the index")
    assert "fgnghf" in _git(repo, "cat-file", "-p", "HEAD:tasks/index.yml").stdout
    ws = _lock(repo)
    r = _run(repo, "--commit-claim", TID)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "✅ Committed the claim" in r.stdout
    assert _status_in(ws) == "in_progress"


@needs_interpreter
def test_a_resume_onto_a_branch_carrying_the_flip_fails(repo, tmp_path):
    """Round 1, lens A: the resume arm compared against HEAD. A checkout to a branch
    that already carried a committed flip (what the pre-phase bug left behind) read as
    "nothing to commit" and exited 0 over a default branch reading `open`."""
    _lock(repo)
    flipped = (repo / "tasks" / "index.yml").read_text().replace(
        "status: open", "status: in_progress", 1)
    _commit_on(repo, tmp_path, "stray", flipped, f"claim: mark {TID} as in-progress")
    r = _shimmed_commit_claim(repo, tmp_path, "rev-parse --abbrev-ref HEAD",
                              "checkout -q stray")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "nothing to commit (resume path)" in r.stdout
    assert "main does not hold the claim for TECH-0001" in r.stderr
    assert "the claim is committed on" not in r.stdout + r.stderr
