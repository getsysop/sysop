"""Step 2b's leak check removes only this close's agents' leaks (`Q-530`, upstream #992, #595, #764).

#992: another session created `.claude/worktrees/npm-audit-fix` on its own branch during a close's
Step 2b window and committed there. `review_pins.py check` listed it as this close's leak, and the
arm's remedy (`git worktree remove`, then `git branch -D`) removed a clean peer's worktree and left
its unpushed commit on no ref. The rule Wade ruled (2026-11-09): ours is a `worktree-agent-*`
branch or a worktree whose path the runner recorded from a spawn's result; anything else new is
`FOREIGN:` and is never removed; checks 1 and 2 get a baseline; only a recorded worktree's
uncommitted files may be discarded. Measured at the phase's open on Claude Code: a live agent's
worktree is `locked` by the parent process, and a finished agent that wrote a file leaves an
unlocked dirty worktree that plain `git worktree remove` refuses.

Every case runs the shipped script in a scratch repository with its own bare origin.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from skill_runner_text import text_of

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "core/companion/scripts/review_pins.py"
SKILL = REPO / "core/skills/review-close/SKILL.md"
ARM = REPO / "core/skills/review-close/steps/2b-leak.md"
FIX = REPO / "core/skills/review-close/steps/4a-fix.md"

ENV = {k: v for k, v in os.environ.items()
       if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
ENV.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
           GIT_AUTHOR_NAME="fx", GIT_AUTHOR_EMAIL="fx@example.invalid",
           GIT_COMMITTER_NAME="fx", GIT_COMMITTER_EMAIL="fx@example.invalid")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, check=True, capture_output=True,
                          text=True).stdout


def pins(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=repo, env=ENV,
                          capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "--bare", "-b", "main", "origin.git")
    r = tmp_path / "repo"
    git(tmp_path, "init", "-q", "-b", "main", str(r))
    git(r, "remote", "add", "origin", str(tmp_path / "origin.git"))
    # Not ignored: a consumer install does not ignore `.claude/worktrees/`, so its worktrees show
    # in the third check's status, which is the harder case.
    (r / ".gitignore").write_text("sysop/runtime/\n")
    (r / "a.txt").write_text("a\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "init")
    git(r, "push", "-q", "-u", "origin", "main")
    return r


def agent(repo: Path, name: str, *, branch: str | None = None) -> Path:
    path = repo / ".claude/worktrees" / f"agent-{name}"
    git(repo, "worktree", "add", "-q", "-b", branch or f"worktree-agent-{name}", str(path), "main")
    return path


def lines(r: subprocess.CompletedProcess, prefix: str) -> list[str]:
    return [l for l in r.stdout.splitlines() if l.startswith(prefix)]


# --------------------------------------------------------------------------
# #992: another session's work is FOREIGN and never removed
# --------------------------------------------------------------------------

def test_a_peer_worktree_made_during_the_window_is_foreign_and_reap_keeps_its_commit(repo):
    assert pins(repo, "baseline").returncode == 0
    peer = repo / ".claude/worktrees/npm-audit-fix"
    git(repo, "worktree", "add", "-q", "-b", "fix/npm-audit", str(peer), "main")
    (peer / "x.txt").write_text("x\n")
    git(peer, "add", "x.txt")
    git(peer, "commit", "-qm", "peer")
    git(peer, "push", "-q", "-u", "origin", "fix/npm-audit")
    tip = git(repo, "rev-parse", "fix/npm-audit").strip()

    r = pins(repo, "check")
    assert r.returncode == 1
    foreign = lines(r, "FOREIGN:")
    assert any("npm-audit-fix (branch fix/npm-audit)" in l for l in foreign)
    assert any("refs/heads/fix/npm-audit" in l for l in foreign), "its tip is the peer's"
    assert any("branch.fix/npm-audit.remote" in l for l in foreign), "its push -u config too"
    assert not lines(r, "LEAK:"), r.stdout
    assert "primary tree unchanged by 2b" in r.stdout
    assert "local config unchanged by 2b" in r.stdout

    r = pins(repo, "reap", "main")
    assert r.returncode == 0, r.stdout
    assert peer.is_dir()
    assert git(repo, "rev-parse", "fix/npm-audit").strip() == tip


def test_a_commit_in_a_sibling_claim_worktree_is_foreign_not_a_primary_mutation(repo):
    claim = repo.parent / "repo-claim"
    git(repo, "worktree", "add", "-q", "-b", "feature/claim", str(claim), "main")
    pins(repo, "baseline")
    (claim / "c.txt").write_text("c\n")
    git(claim, "add", "c.txt")
    git(claim, "commit", "-qm", "claim work")

    r = pins(repo, "check")
    assert r.returncode == 1
    assert "primary tree unchanged by 2b" in r.stdout, r.stdout
    assert len([l for l in lines(r, "FOREIGN:") if "refs/heads/feature/claim" in l]) == 2


def test_a_worktree_there_before_the_baseline_predates_the_close_and_passes(repo):
    peer = repo / ".claude/worktrees/npm-audit-fix"
    git(repo, "worktree", "add", "-q", "-b", "fix/npm-audit", str(peer), "main")
    left = agent(repo, "old")
    pins(repo, "baseline")

    r = pins(repo, "check")
    assert r.returncode == 0, r.stdout
    assert r.stdout.splitlines()[:5] == [
        "no agent worktrees", "no agent branches", "primary tree unchanged by 2b",
        "local config unchanged by 2b", "no pinned checkouts"]
    predates = lines(r, "PREDATES:")
    assert any("npm-audit-fix" in l for l in predates)
    assert any(str(left.name) in l for l in predates)
    assert any("branch worktree-agent-old" in l for l in predates)


# --------------------------------------------------------------------------
# ours: removed by `reap`, and only within the ruling
# --------------------------------------------------------------------------

def test_a_recorded_dirty_agent_worktree_is_discarded_with_its_files_listed(repo):
    pins(repo, "baseline")
    wt = agent(repo, "a1")
    (wt / "scratch.txt").write_text("s\n")
    assert pins(repo, "own", str(wt)).stdout.startswith("OWN: ")

    assert lines(pins(repo, "check"), "LEAK:")
    r = pins(repo, "reap", "main")
    assert r.returncode == 0, r.stdout
    assert any(l.endswith("?? scratch.txt") for l in lines(r, "DISCARDING:"))
    assert not wt.exists()
    assert "worktree-agent-a1" not in git(repo, "branch", "--list")
    assert pins(repo, "check").returncode == 0


def test_an_unrecorded_dirty_agent_worktree_is_kept(repo):
    """A peer session's isolated implementation agent can leave real uncommitted work."""
    pins(repo, "baseline")
    wt = agent(repo, "a2")
    (wt / "work.py").write_text("real work\n")

    r = pins(repo, "reap", "main")
    assert r.returncode == 1
    assert any("agent-a2" in l and "not recorded" in l for l in lines(r, "KEPT:"))
    assert (wt / "work.py").read_text() == "real work\n"


def test_an_unrecorded_clean_agent_worktree_and_a_bare_agent_branch_are_removed(repo):
    pins(repo, "baseline")
    wt = agent(repo, "a3")
    git(repo, "branch", "worktree-agent-zz", "main")

    r = pins(repo, "reap", "main")
    assert r.returncode == 0, r.stdout
    assert not wt.exists()
    assert git(repo, "branch", "--list", "worktree-agent-*").strip() == ""


def test_an_agent_branch_with_commits_is_kept(repo):
    pins(repo, "baseline")
    wt = agent(repo, "a5")
    (wt / "c.txt").write_text("c\n")
    git(wt, "add", "c.txt")
    git(wt, "commit", "-qm", "an agent committed")
    pins(repo, "own", str(wt))

    r = pins(repo, "reap", "main")
    assert r.returncode == 1
    assert any("1 commit(s) ahead of main" in l for l in lines(r, "KEPT:"))
    assert wt.is_dir()


def test_a_locked_agent_worktree_is_left_and_alone_does_not_fail_the_check(repo):
    """#595: the harness locks a live agent's worktree with the session's own process."""
    pins(repo, "baseline")
    wt = agent(repo, "a4")
    (wt / "scratch.txt").write_text("s\n")
    git(repo, "worktree", "lock", "--reason", "claude agent agent-a4 (pid 1)", str(wt))
    pins(repo, "own", str(wt))

    r = pins(repo, "check")
    assert r.returncode == 0, r.stdout
    assert any("agent-a4" in l and "claude agent" in l for l in lines(r, "LOCKED:"))
    assert "primary tree unchanged by 2b" in r.stdout, "its own `??` line is the LOCKED line's"
    r = pins(repo, "reap", "main")
    assert r.returncode == 0
    assert (wt / "scratch.txt").is_file()


def test_an_agent_that_switched_branch_in_its_recorded_worktree_is_ours(repo):
    """The Phase 333 shape: `git switch -c` inside the agent's own worktree."""
    pins(repo, "baseline")
    wt = agent(repo, "e1")
    git(wt, "switch", "-qc", "scratch-by-agent")
    pins(repo, "own", str(wt))

    r = pins(repo, "check")
    assert any("branch scratch-by-agent" in l for l in lines(r, "LEAK:")), r.stdout
    assert not lines(r, "FOREIGN:"), r.stdout
    assert "primary tree unchanged by 2b" in r.stdout
    # Wade, after round 2: only an agent-named branch is ours to delete. The switched-to branch
    # is kept and reported, since a peer could have made it during the window.
    r = pins(repo, "reap", "main")
    assert r.returncode == 1
    assert any("branch scratch-by-agent, not an agent branch" in l for l in lines(r, "KEPT:"))
    assert git(repo, "branch", "--list", "worktree-agent-e1").strip() == ""
    assert git(repo, "branch", "--list", "scratch-by-agent").strip()
    # Nothing holds the kept branch now, so the re-check shows its tip and the arm stops.
    r = pins(repo, "check")
    assert r.returncode == 1 and "+# refs/heads/scratch-by-agent" in r.stdout, r.stdout


def test_an_unrecorded_worktree_on_a_switched_branch_is_foreign(repo):
    """Without the record the same worktree is not provably ours, so it is never removed."""
    pins(repo, "baseline")
    wt = agent(repo, "e2")
    git(wt, "switch", "-qc", "scratch-by-agent")
    r = pins(repo, "check")
    assert any("agent-e2" in l for l in lines(r, "FOREIGN:")), r.stdout
    pins(repo, "reap", "main")
    assert wt.is_dir()


def test_a_branch_a_peer_released_during_the_window_is_foreign(repo):
    """A concurrent close removes its claim worktree and deletes the branch while 2b runs."""
    claim = repo.parent / "repo-claim"
    git(repo, "worktree", "add", "-q", "-b", "feature/done", str(claim), "main")
    pins(repo, "baseline")
    git(repo, "worktree", "remove", str(claim))
    git(repo, "branch", "-D", "feature/done")

    r = pins(repo, "check")
    assert any("-# refs/heads/feature/done" in l for l in lines(r, "FOREIGN:")), r.stdout
    assert "primary tree unchanged by 2b" in r.stdout


@pytest.mark.parametrize("name", ["release.v1", "feat=x"])
def test_a_branch_name_with_a_dot_or_an_equals_keeps_its_config_foreign(repo, name):
    pins(repo, "baseline")
    peer = repo.parent / "repo-peer"
    git(repo, "worktree", "add", "-q", "-b", name, str(peer), "main")
    git(peer, "push", "-q", "-u", "origin", name)
    r = pins(repo, "check")
    assert any(f"branch.{name}.remote" in l for l in lines(r, "FOREIGN:")), r.stdout
    assert "local config unchanged by 2b" in r.stdout


def test_a_primary_file_sharing_a_worktrees_name_prefix_is_still_a_mutation(repo):
    pins(repo, "baseline")
    wt = agent(repo, "x")
    git(repo, "worktree", "lock", "--reason", "claude agent agent-x (pid 1)", str(wt))
    (repo / ".claude/worktrees/agent-x-notes.txt").write_text("an agent wrote this here\n")
    r = pins(repo, "check")
    assert "+?? .claude/worktrees/agent-x-notes.txt" in r.stdout
    assert r.returncode == 1


def test_a_bare_agent_branch_with_commits_is_kept(repo):
    pins(repo, "baseline")
    git(repo, "branch", "worktree-agent-c1", "main")
    wt = repo.parent / "tmp-c1"
    git(repo, "worktree", "add", "-q", str(wt), "worktree-agent-c1")
    (wt / "c.txt").write_text("c\n")
    git(wt, "add", "c.txt")
    git(wt, "commit", "-qm", "c")
    git(repo, "worktree", "remove", str(wt))

    r = pins(repo, "reap", "main")
    assert r.returncode == 1
    assert any("branch worktree-agent-c1" in l and "ahead" in l for l in lines(r, "KEPT:"))
    assert git(repo, "branch", "--list", "worktree-agent-c1").strip()


def test_a_worktree_whose_commits_cannot_be_read_is_kept(repo):
    pins(repo, "baseline")
    wt = agent(repo, "u1")
    admin = Path(git(wt, "rev-parse", "--absolute-git-dir").strip())
    (admin / "HEAD").write_text("0" * 39 + "1\n")      # a commit no object store holds
    pins(repo, "own", str(wt))                          # detached now, so ours only by record
    r = pins(repo, "reap", "main")
    assert r.returncode == 1
    assert any("agent-u1" in l and l.endswith("its commits unreadable")
               for l in lines(r, "KEPT:")), r.stdout
    assert wt.is_dir()


def test_own_resolves_a_relative_path(repo):
    pins(repo, "baseline")
    wt = agent(repo, "r1")
    (wt / "scratch.txt").write_text("s\n")
    assert pins(repo, "own", ".claude/worktrees/agent-r1").returncode == 0
    assert pins(repo, "reap", "main").returncode == 0
    assert not wt.exists()


def test_the_scripts_own_files_are_not_a_mutation_when_runtime_is_not_ignored(repo):
    (repo / ".gitignore").write_text("sysop/runtime/pins/\nsysop/runtime/scratch/\n")
    git(repo, "commit", "-qam", "runtime not ignored")
    pins(repo, "baseline")
    wt = agent(repo, "w1")
    pins(repo, "own", str(wt))
    pins(repo, "reap", "main")
    r = pins(repo, "check")
    assert r.returncode == 0, r.stdout


# --------------------------------------------------------------------------
# the round's findings (Phase 479, lenses A and B)
# --------------------------------------------------------------------------

def test_reap_keeps_a_branch_that_was_there_before_the_close(repo):
    """Lens A: a recorded agent that switches its worktree to an existing claim branch."""
    git(repo, "branch", "feature/claimed", "main")
    git(repo, "config", "branch.feature/claimed.remote", "origin")
    pins(repo, "baseline")
    wt = agent(repo, "q1")
    git(wt, "switch", "-q", "feature/claimed")
    pins(repo, "own", str(wt))

    r = pins(repo, "reap", "main")
    assert any("branch feature/claimed, not an agent branch" in l
               for l in lines(r, "KEPT:")), r.stdout
    assert git(repo, "branch", "--list", "feature/claimed").strip()
    assert git(repo, "config", "branch.feature/claimed.remote").strip() == "origin"
    assert "worktree-agent-q1" not in git(repo, "branch", "--list")


def test_reap_never_deletes_the_default_branch(repo):
    """Lens B: under `pr` the primary is on the integration branch, so `main` is free."""
    git(repo, "switch", "-qc", "merge/review-close-x")
    pins(repo, "baseline")
    wt = agent(repo, "aaa")
    git(wt, "switch", "-q", "main")
    (wt / "scratch.txt").write_text("s\n")
    pins(repo, "own", str(wt))

    r = pins(repo, "reap", "main")
    assert any("branch main, not an agent branch" in l for l in lines(r, "KEPT:")), r.stdout
    assert git(repo, "branch", "--list", "main").strip()


def test_own_refuses_a_path_that_is_not_an_agent_worktree(repo):
    """Lens B: a recorded path's uncommitted files are discarded, so `own` takes only one."""
    pins(repo, "baseline")
    peer = repo.parent / "repo-peer"
    git(repo, "worktree", "add", "-q", "-b", "feat-peer", str(peer), "main")
    (peer / "work.txt").write_text("w\n")
    assert pins(repo, "own", str(peer)).returncode == 2
    assert pins(repo, "own", str(repo / ".claude/worktrees/agent-none")).returncode == 2
    assert pins(repo, "own", str(repo)).returncode == 2
    assert not (repo / "sysop/runtime/2b-own.txt").exists()
    pins(repo, "reap", "main")
    assert (peer / "work.txt").is_file()


def test_reap_takes_a_leak_whose_directory_is_gone(repo):
    """Lens A: a prunable entry crashed `reap` with a traceback."""
    pins(repo, "baseline")
    wt = agent(repo, "p1")
    shutil.rmtree(wt)
    r = pins(repo, "reap", "main")
    assert "Traceback" not in r.stderr, r.stderr
    assert r.returncode == 0, r.stdout
    assert pins(repo, "check").returncode == 0


def test_a_peer_worktree_with_a_non_ascii_name_is_not_a_primary_mutation(repo):
    """Lens A: `git status` C-quoted the name, so its line went unattributed."""
    pins(repo, "baseline")
    git(repo, "worktree", "add", "-q", "-b", "fix/cafe", str(repo / ".claude/worktrees/café-fix"),
        "main")
    r = pins(repo, "check")
    assert "primary tree unchanged by 2b" in r.stdout, r.stdout
    assert any("café-fix" in l for l in lines(r, "FOREIGN:"))


def test_a_peer_worktree_inside_the_checkout_elsewhere_is_foreign(repo):
    """Lenses A and B: `wt-peer/` read as a primary mutation the arm said to revert."""
    pins(repo, "baseline")
    git(repo, "worktree", "add", "-q", "-b", "fix/in", str(repo / "wt-peer"), "main")
    (repo / "wt-peer/work.txt").write_text("w\n")
    r = pins(repo, "check")
    assert "primary tree unchanged by 2b" in r.stdout, r.stdout
    assert any("wt-peer (branch fix/in)" in l for l in lines(r, "FOREIGN:"))


def test_a_lone_leaked_agent_worktree_fails_the_check(repo):
    """Lens A's mutant Ma: every other exit-1 test also carried a FOREIGN line."""
    pins(repo, "baseline")
    agent(repo, "m1")
    r = pins(repo, "check")
    assert r.returncode == 1
    assert len(lines(r, "LEAK:")) == 1 and not lines(r, "FOREIGN:")


def test_a_lone_new_agent_branch_fails_the_check(repo):
    """Lens A's mutant Mb."""
    pins(repo, "baseline")
    git(repo, "branch", "worktree-agent-zz", "main")
    r = pins(repo, "check")
    assert r.returncode == 1
    assert lines(r, "LEAK:") == ["LEAK: branch worktree-agent-zz"]


def test_an_agent_branch_outside_the_agents_directory_is_still_ours(repo):
    """Lens A's mutant Mc: ours by name, wherever its worktree is."""
    pins(repo, "baseline")
    git(repo, "worktree", "add", "-q", "-b", "worktree-agent-o1", str(repo.parent / "o1"), "main")
    r = pins(repo, "check")
    assert any("o1 (branch worktree-agent-o1)" in l for l in lines(r, "LEAK:")), r.stdout


def test_a_predated_agent_branch_has_its_own_line(repo):
    """Lens A's mutant Mf: the worktree's line named the branch too, so it hid this one."""
    git(repo, "branch", "worktree-agent-b0", "main")
    pins(repo, "baseline")
    r = pins(repo, "check")
    assert "PREDATES: branch worktree-agent-b0, there before this close; not removed" in r.stdout


# --------------------------------------------------------------------------
# round 2 (Phase 479, one lens on the round-1 fixes)
# --------------------------------------------------------------------------

def test_reap_keeps_a_peer_branch_made_during_the_window_that_our_agent_checked_out(repo):
    """Round 2's A: "made during the window" did not mean "ours"."""
    pins(repo, "baseline")
    wt = agent(repo, "aaa")
    pins(repo, "own", str(wt))
    git(repo, "branch", "peer-claim", "main")
    git(repo, "config", "branch.peer-claim.description", "a peer's")
    git(wt, "checkout", "-q", "peer-claim")

    r = pins(repo, "reap", "main")
    assert any("branch peer-claim, not an agent branch" in l for l in lines(r, "KEPT:"))
    assert git(repo, "branch", "--list", "peer-claim").strip()
    assert git(repo, "config", "branch.peer-claim.description").strip() == "a peer's"


def test_reap_keeps_an_agent_branch_the_baseline_had(repo):
    """Round 2's B: `check` said PREDATES and `reap` then deleted it."""
    git(repo, "branch", "worktree-agent-old", "main")
    pins(repo, "baseline")
    wt = agent(repo, "n")
    pins(repo, "own", str(wt))
    git(wt, "checkout", "-q", "worktree-agent-old")
    assert "PREDATES: branch worktree-agent-old" in pins(repo, "check").stdout
    r = pins(repo, "reap", "main")
    assert any("branch worktree-agent-old" in l for l in lines(r, "KEPT:")), r.stdout
    assert git(repo, "branch", "--list", "worktree-agent-old").strip()


def test_reaped_counts_a_deleted_branch(repo):
    """Round 2's F: a deleted held branch was left out of `REAPED:`."""
    pins(repo, "baseline")
    wt = agent(repo, "cnt")
    pins(repo, "own", str(wt))
    r = pins(repo, "reap", "main")
    assert lines(r, "REMOVED:") and "REAPED: 2 removed, 0 kept" in r.stdout, r.stdout


def test_a_dirty_pin_is_not_called_another_sessions(repo):
    """Round 2's C, a regression of round 1's inside-the-checkout attribution."""
    pins(repo, "baseline")
    pin = repo / "sysop/runtime/pins/2b-abc-1"
    pin.parent.mkdir(parents=True)
    git(repo, "worktree", "add", "-q", "--detach", str(pin), "HEAD")
    (pin / "x").write_text("x\n")
    r = pins(repo, "check")
    assert not lines(r, "FOREIGN:"), r.stdout
    assert any(l.endswith("2b-abc-1") for l in r.stdout.splitlines()), "the fifth check lists it"


def test_our_config_on_a_dotted_branch_is_not_a_prefix_peers(repo):
    """Round 2's D: `branch.feat.x.merge` is `feat.x`'s, not foreign `feat`'s."""
    pins(repo, "baseline")
    git(repo, "worktree", "add", "-q", "-b", "feat", str(repo.parent / "peer"), "main")
    git(repo, "config", "branch.feat.x.merge", "refs/heads/main")
    r = pins(repo, "check")
    assert not any("feat.x" in l for l in lines(r, "FOREIGN:")), r.stdout
    assert "+branch.feat.x.merge=refs/heads/main" in r.stdout


def test_own_refuses_a_peer_worktree_inside_the_agents_directory(repo):
    """Round 2's E: #992's own shape, a peer's `.claude/worktrees/npm-audit-fix`."""
    pins(repo, "baseline")
    peer = repo / ".claude/worktrees/npm-audit-fix"
    git(repo, "worktree", "add", "-q", "-b", "npm-audit-fix", str(peer), "main")
    (peer / "a.txt").write_text("changed\n")
    assert pins(repo, "own", str(peer)).returncode == 2
    pins(repo, "reap", "main")
    assert (peer / "a.txt").read_text() == "changed\n"


def test_own_refuses_an_agent_worktree_the_baseline_had(repo):
    wt = agent(repo, "early")
    pins(repo, "baseline")
    assert pins(repo, "own", str(wt)).returncode == 2


# --------------------------------------------------------------------------
# what the check still catches
# --------------------------------------------------------------------------

def test_a_mutation_of_the_primary_tree_is_still_a_finding(repo):
    pins(repo, "baseline")
    (repo / "z.txt").write_text("z\n")
    r = pins(repo, "check")
    assert r.returncode == 1
    assert "+?? z.txt" in r.stdout
    assert not lines(r, "FOREIGN:")


def test_a_missing_agents_baseline_fails_loudly(repo):
    pins(repo, "baseline")
    (repo / "sysop/runtime/2b-agents-baseline.txt").unlink()
    r = pins(repo, "check")
    assert r.returncode == 1
    assert "MISSING BASELINE: sysop/runtime/2b-agents-baseline.txt" in r.stdout
    assert pins(repo, "reap", "main").returncode == 2


def test_baseline_clears_the_previous_closes_record(repo):
    pins(repo, "baseline")
    wt = agent(repo, "old")
    assert pins(repo, "own", str(wt)).returncode == 0
    assert (repo / "sysop/runtime/2b-own.txt").read_text() == os.path.realpath(wt) + "\n"
    pins(repo, "baseline")
    assert not (repo / "sysop/runtime/2b-own.txt").exists()


@pytest.mark.parametrize("args", [("own", "<path>"), ("own", ""), ("reap", "<default branch>"),
                                  ("reap", "no-such-branch")])
def test_placeholders_and_unknown_branches_are_refused(repo, args):
    assert pins(repo, *args).returncode == 2


# --------------------------------------------------------------------------
# the runner text
# --------------------------------------------------------------------------

def test_the_arm_removes_through_reap_and_never_by_hand():
    arm = ARM.read_text()
    assert 'review_pins.py reap "<default branch>"' in arm
    assert "Do not run `git worktree remove` or `git branch -D` yourself" in arm
    assert "remove the worktree (`git worktree remove <path>`) and delete the branch" not in arm
    for word in ("`FOREIGN:`", "`LOCKED:`", "`PREDATES:`", "`KEPT:`"):
        assert word in arm, word
    assert "`Leave it and continue`" in arm and "`Stop the close`" in arm
    foreign = arm[arm.index("2. **`FOREIGN:`**"):arm.index("3. **`LOCKED:`")]
    assert "**Never remove, revert or reset it.**" in foreign
    # Wade, 2026-11-09: a non-target FOREIGN does not stop a headless close.
    assert ("Under `--prepare`, `--headless` or `--unattended`, leave it, carry the lines to "
            "that row, and continue.") in foreign


def test_the_fix_recheck_records_its_agent_before_the_hard_rule():
    fix = FIX.read_text()
    own = fix.index('review_pins.py own "<path>"')
    assert own < fix.index("python3 sysop/scripts/review_pins.py clean")


def test_the_runner_records_each_returned_worktree_before_the_check():
    text = text_of(SKILL)
    own = text.index('review_pins.py own "<path>"')
    assert own < text.index("python3 sysop/scripts/review_pins.py check")
    assert "Left by 2b:" in text


def test_step_2a_excludes_agent_branches_by_name_or_by_zero_commits():
    text = text_of(SKILL)
    m = re.search(r"excluding any \*\*agent worktree branch\*\*: (.+?)Do not review", text, re.S)
    assert m, "Step 2a's exclusion sentence moved"
    rule = m.group(1)
    assert "`worktree-agent-*`" in rule
    assert "rev-list --count refs/heads/<default branch>..refs/heads/<branch>" in rule
    # The entry's filed fix: surface one with commits for a decision, never review it unasked.
    assert "attended, ask with `AskUserQuestion` (`Review it` / `Skip it`)" in rule
    assert "its verdict is **SKIP — in an agent worktree**" in rule
