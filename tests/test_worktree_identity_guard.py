"""Phase 264: a workspace directory is adopted only when it is OURS.

Three filings, one surface. `claim_task.sh` worktree mode (`Q-405`) and
`batch_work.sh` (`Q-415`, found while fixing the first) both answered "does a
worktree exist at this path" and neither answered "whose". Two checkouts of one
project sharing a workspace parent — the documented intended configuration since
Phase 262 gave `claim_task.sh` a `WORKTREE_ROOT` — made the second claim adopt
the first's live tree at exit 0, write a lock naming a workspace whose commits
belong to the other checkout, and strand: `git worktree remove` answers
`fatal: ... is not a working tree` even with `--force`, because this repository
never registered that path.

`Q-406` widens the root guard from "not inside THIS repository" to "not inside
ANY working tree" — the maintainer's ratified direction, because the arm's own
rationale (untracked content in a checkout, outside the `sysop/runtime/`
gitignore set, swept by the cleanup paths meant to remove it) is repo-agnostic
while the check was not. The monorepo-sandbox case is the accepted cost.

`Q-407` gives `batch_work.sh` the `WORKTREE_ROOT` Phase 262 shipped for one of
the two claim paths only.

**These tests drive the real scripts.** The refusals assert that NOTHING was
written — no branch, no lock, no status flip — because both defects were exit-0
paths whose damage was the record they left, not the error they raised.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_batch_work_sh import SCRIPT as BATCH
from test_batch_work_sh import _repo as _batch_repo
from test_batch_work_sh import _run as _batch_run
from test_claim_task_sh import SCRIPT, _git, _path_env, _py3_bin, _repo, _run

LIB = SCRIPT.parent / "_git_lib.sh"

INDEX = "tasks:\n  T-0001:\n    status: open\n"
BODY = "---\nid: T-0001\nstatus: open\n---\nbody\n"


def _seeded(parent, name="repo"):
    """A claimable checkout. `name` is a parameter because the whole defect
    needs two checkouts whose basenames COLLIDE, which is the norm rather than a
    contrivance: two clones of one project are both `<project>/`."""
    parent.mkdir(parents=True, exist_ok=True)
    root = _repo(parent / name)
    (root / "tasks" / "open").mkdir(parents=True)
    (root / "tasks" / "index.yml").write_text(INDEX)
    (root / "tasks" / "open" / "T-0001.md").write_text(BODY)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "tasks")
    return root


def _branches(root):
    return subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=str(root),
                          capture_output=True, text=True, check=True).stdout.split()


def _registered(root):
    """The worktrees git itself reports for *root*, minus root's own tree."""
    out = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=str(root),
                         capture_output=True, text=True, check=True).stdout
    paths = [Path(l.split(" ", 1)[1]).resolve()
             for l in out.splitlines() if l.startswith("worktree ")]
    return [p for p in paths if p != root.resolve()]


def _lib_call(func, *args, env=None):
    """Drive one `_git_lib.sh` function in a subshell; returns the CompletedProcess."""
    e = dict(os.environ)
    e.update({"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})
    if env:
        e.update(env)
    quoted = " ".join(f'"{a}"' for a in args)
    return subprocess.run(
        ["bash", "-c", f'source "{LIB}" || exit 9\n{func} {quoted}'],
        capture_output=True, text=True, env=e,
    )


# ── Q-405: claim_task.sh worktree mode ────────────────────────────────────

class TestClaimTaskAdoption:
    """The filed defect, driven end to end against two real checkouts."""

    @pytest.fixture
    def two_checkouts(self, tmp_path):
        a = _seeded(tmp_path / "a")
        b = _seeded(tmp_path / "b")          # same basename, by construction
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        env = {**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(sandbox)}
        first = _run(a, "--lock", "T-0001", "feat/t1", env=env)
        assert first.returncode == 0, first.stderr
        assert (sandbox / "repo-t-0001").is_dir(), first.stdout
        return a, b, sandbox, env

    def test_a_second_checkout_is_refused_the_first_s_worktree(self, two_checkouts):
        """The headline. Before Phase 264 this exited 0 and said "Start working!"."""
        _a, b, sandbox, env = two_checkouts
        r = _run(b, "--lock", "T-0001", "feat/t1", env=env)
        assert r.returncode == 1, f"adopted a foreign worktree: {r.stdout}"
        assert "not a worktree of this repository" in r.stderr, r.stderr

    def test_the_refusal_writes_no_lock(self, two_checkouts):
        """The damage was never the exit code — it was a lock whose `workspace:`
        sent /review-close Step 3b arm (ii) to collect from another checkout."""
        _a, b, _sandbox, env = two_checkouts
        _run(b, "--lock", "T-0001", "feat/t1", env=env)
        assert not (b / "sysop/runtime/locks/T-0001.lock").exists()

    def test_the_refusal_creates_no_branch(self, two_checkouts):
        """The first cut of this fix checked inside the mode block, where the
        branch already exists, and stranded an orphan ref on every refusal.
        `--clone` states the same principle for its own refusals."""
        _a, b, _sandbox, env = two_checkouts
        _run(b, "--lock", "T-0001", "feat/t1", env=env)
        assert "feat/t1" not in _branches(b)

    def test_the_first_checkout_keeps_its_worktree(self, two_checkouts):
        """Fail-closed means fail-closed: refusing must not touch the other
        repository's tree, which this one has no standing to remove."""
        a, b, sandbox, env = two_checkouts
        _run(b, "--lock", "T-0001", "feat/t1", env=env)
        assert (sandbox / "repo-t-0001").is_dir()
        assert _registered(a) == [(sandbox / "repo-t-0001").resolve()]

    def test_our_own_worktree_is_still_resumed(self, tmp_path):
        """The branch exists to RESUME a claim. Refusing every existing directory
        would be a fix that breaks the feature — so pin the legal direction."""
        root = _seeded(tmp_path / "solo")
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        env = {**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(sandbox)}
        first = _run(root, "T-0001", "feat/t1", env=env)
        assert first.returncode == 0, first.stderr
        again = _run(root, "T-0001", "feat/t1", env=env)
        assert again.returncode == 0, again.stderr
        assert "already exists" in again.stdout, again.stdout

    @pytest.mark.parametrize("shape", ["dangling-symlink", "regular-file"])
    def test_a_non_directory_at_the_path_is_refused_without_creating_a_branch(
            self, tmp_path, shape):
        """`-e || -L`, not `-d`. `-e` FOLLOWS the link, so a dangling symlink is
        invisible to it, and a regular file is not a directory either. Both slipped
        past the preflight's first cut and reached `git worktree add`, which lstats,
        refuses with a bare `fatal: ... already exists` at rc=128, and leaves the
        branch — violating this block's own stated contract that a refusal leaves
        nothing behind. `batch_work.sh`'s preflight had already learned this; the
        asymmetry between the two was the defect."""
        root = _seeded(tmp_path / "solo")
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        target = sandbox / "repo-t-0001"
        if shape == "dangling-symlink":
            target.symlink_to(tmp_path / "nonexistent")
        else:
            target.write_text("x")
        r = _run(root, "T-0001", "feat/t1",
                 env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(sandbox)})
        assert r.returncode == 1, f"{shape}: {r.stdout}{r.stderr}"
        assert "not a worktree of this repository" in r.stderr, r.stderr
        assert "feat/t1" not in _branches(root), f"{shape}: orphan branch left"

    def test_a_plain_directory_is_still_refused(self, tmp_path):
        """Not a regression of the narrower case: a non-repository directory at
        the path was already wrong, and must stay refused by the same guard."""
        root = _seeded(tmp_path / "solo")
        sandbox = tmp_path / "sandbox"
        (sandbox / "repo-t-0001").mkdir(parents=True)
        env = {**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(sandbox)}
        r = _run(root, "T-0001", "feat/t1", env=env)
        assert r.returncode == 1, r.stdout
        assert "not a worktree of this repository" in r.stderr, r.stderr


# ── Q-415: batch_work.sh, the same class in the other claim path ──────────

class TestBatchWorkAdoption:
    """Found by asking what `Q-405`'s population could not contain: the filing
    enumerated one script. `WORKTREE_PREFIX` alone makes this reachable today —
    two sibling checkouts, one shared prefix — and `Q-407` makes it as likely
    here as Phase 262 made it there."""

    @pytest.fixture
    def two_checkouts(self, tmp_path):
        a = _batch_repo(tmp_path / "p" / "one")
        b = _batch_repo(tmp_path / "p" / "two")
        env = {"WORKTREE_PREFIX": "shared"}
        first = _batch_run(a, "1", env=env)
        assert first.returncode == 0, first.stderr
        assert (tmp_path / "p" / "shared-batch-1").is_dir(), first.stdout
        return a, b, tmp_path / "p" / "shared-batch-1", env

    def test_a_second_checkout_is_refused_the_first_s_batch_worktree(self, two_checkouts):
        _a, b, _wt, env = two_checkouts
        r = _batch_run(b, "1", env=env)
        assert r.returncode == 1, f"adopted a foreign worktree: {r.stdout}"
        assert "worktree of a DIFFERENT repository" in r.stderr, r.stderr

    def test_the_refusal_writes_no_batch_lock(self, two_checkouts):
        _a, b, _wt, env = two_checkouts
        _batch_run(b, "1", env=env)
        assert not (b / "sysop/runtime/locks/BATCH-1.lock").exists()

    def test_the_refusal_does_not_flip_the_batch_status(self, two_checkouts):
        """`claim_batch` COMMITS the status flip. The preflight is above it
        precisely so a refusal leaves the record untouched — Phase 210's
        decide-then-write discipline, which this narrowing must not fall below."""
        _a, b, _wt, env = two_checkouts
        _batch_run(b, "1", env=env)
        assert "In Progress" not in (b / "review_tasks.md").read_text()

    def test_our_own_batch_worktree_is_still_resumed(self, tmp_path):
        root = _batch_repo(tmp_path / "solo")
        first = _batch_run(root, "1")
        assert first.returncode == 0, first.stderr
        again = _batch_run(root, "1")
        assert again.returncode == 0, again.stderr

    def test_a_plain_directory_still_gets_its_own_message(self, tmp_path):
        """Two refusals, two causes. The `Q-382` message names a non-repository;
        collapsing them would tell an operator to `rm -rf` another checkout's
        live worktree."""
        root = _batch_repo(tmp_path / "solo")
        (tmp_path / "solo-batch-1").mkdir()
        r = _batch_run(root, "1")
        assert r.returncode == 1
        assert "exists but is not a git worktree" in r.stderr, r.stderr


# ── Q-406: the root guard covers every working tree ───────────────────────

class TestAnyWorkTreeContainment:
    """Ratified 2026-09-04: refuse a root inside ANY git working tree. Phase 262
    shipped the this-repo arm alone and a root inside a NEIGHBOUR produced the
    same harm one repository over."""

    def test_claim_task_refuses_a_root_inside_another_repository(self, tmp_path):
        host = _repo(tmp_path / "host")
        nested = host / "sandbox"
        nested.mkdir()
        root = _seeded(tmp_path / "claimer")
        r = _run(root, "T-0001", "feat/t1",
                 env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(nested)})
        assert r.returncode == 1, r.stdout
        assert "resolves inside a git working tree" in r.stderr, r.stderr

    def test_batch_work_refuses_a_root_inside_another_repository(self, tmp_path):
        host = _repo(tmp_path / "host")
        nested = host / "sandbox"
        nested.mkdir()
        root = _batch_repo(tmp_path / "bw")
        r = _batch_run(root, "1", env={"WORKTREE_ROOT": str(nested)})
        assert r.returncode == 1, r.stdout
        assert "resolves inside a git working tree" in r.stderr, r.stderr

    def test_the_neighbour_repository_is_left_clean(self, tmp_path):
        """The arm's whole rationale: untracked content in a checkout that its
        own cleanup paths would sweep. Assert the harm, not just the exit code."""
        host = _repo(tmp_path / "host")
        nested = host / "sandbox"
        nested.mkdir()
        root = _seeded(tmp_path / "claimer")
        _run(root, "T-0001", "feat/t1",
             env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(nested)})
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=str(host),
                               capture_output=True, text=True, check=True).stdout
        assert dirty.strip() == "", f"left untracked content in the neighbour: {dirty}"

    def test_arm_one_carries_coverage_arm_two_cannot(self, tmp_path):
        """**Arm 2 does NOT subsume arm 1**, and this phase's own record said it did
        at five sites before a review lens falsified it by execution.

        Arm 2 asks `rev-parse --show-toplevel`, which inside a `.git` DIRECTORY
        exits 128 (`fatal: this operation must be run in a work tree`) — so it
        cannot see a root there at all. Arm 1's prefix match can, and does. With
        arm 1 stripped, `WORKTREE_ROOT=<repo>/.git/nested` is ACCEPTED.

        The earlier test here asserted only that arm 1's *message* still appears,
        which measured the wrong property: a reader who believed the shipped
        "subsumes" comment could delete arm 1, move its message onto arm 2, stay
        green, and open the hole. This asserts the refusal of a path arm 2 is
        structurally unable to reach."""
        root = _seeded(tmp_path / "claimer")
        nested = root / ".git" / "nested"
        nested.mkdir(parents=True)
        # Arm 2 is blind here — establish that, so the test cannot silently
        # start passing for arm 2's reason.
        probe = subprocess.run(["git", "-C", str(nested), "rev-parse", "--show-toplevel"],
                               capture_output=True, text=True)
        assert probe.returncode != 0, (
            "arm 2 can now see inside a .git directory; this test no longer "
            "isolates arm 1 and the 'subsumes' question must be re-derived"
        )
        r = _run(root, "T-0001", "feat/t1",
                 env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(nested)})
        assert r.returncode == 1, r.stdout
        assert "resolves inside the repository" in r.stderr, r.stderr

    def test_a_ceiling_cannot_switch_off_the_any_work_tree_arm(self, tmp_path):
        """`GIT_CEILING_DIRECTORIES` STOPS discovery rather than redirecting it.

        Arm 2 walks upward looking for an enclosing working tree, so a ceiling
        naming that tree made the walk find nothing and the guard accept —
        reproduced end to end before the fix, leaving `?? sandbox/` untracked in
        the neighbour, which is the exact harm `Q-406` exists to prevent. The
        original three-variable scrub was written for the REDIRECT class and did
        not cover the STOP class."""
        host = _repo(tmp_path / "host")
        nested = host / "sandbox"
        nested.mkdir()
        root = _seeded(tmp_path / "claimer")
        r = _run(root, "T-0001", "feat/t1",
                 env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(nested),
                      "GIT_CEILING_DIRECTORIES": str(host)})
        assert r.returncode == 1, r.stdout
        assert "resolves inside a git working tree" in r.stderr, r.stderr
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=str(host),
                               capture_output=True, text=True, check=True).stdout
        assert dirty.strip() == "", f"a ceiling let it pollute the neighbour: {dirty}"

    def test_this_repository_still_gets_the_specific_message(self, tmp_path):
        """Arm 1's message, kept distinct from arm 2's generic one so the operator
        gets the nearest true reason. Coverage is asserted above; this is the
        message half only."""
        root = _seeded(tmp_path / "claimer")
        inside = root / "inside"
        inside.mkdir()
        r = _run(root, "T-0001", "feat/t1",
                 env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(inside)})
        assert r.returncode == 1
        assert "resolves inside the repository" in r.stderr, r.stderr

    def test_a_root_outside_every_repository_is_accepted(self, tmp_path):
        """The legal direction. `Q-406` narrows what is legal, so the test that
        the narrowing did not swallow the feature is the load-bearing one."""
        root = _seeded(tmp_path / "claimer")
        free = tmp_path / "free"
        free.mkdir()
        r = _run(root, "T-0001", "feat/t1",
                 env={**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(free)})
        assert r.returncode == 0, r.stderr
        # `_seeded` names the checkout `repo/`, so the leaf is `repo-t-0001`.
        assert (free / "repo-t-0001").is_dir(), sorted(x.name for x in free.iterdir())


# ── Q-407: WORKTREE_ROOT reaches the review-batch claim ───────────────────

class TestBatchWorktreeRoot:
    def test_batch_work_honours_worktree_root(self, tmp_path):
        root = _batch_repo(tmp_path / "bw" / "one")
        sandbox = tmp_path / "declared"
        sandbox.mkdir()
        r = _batch_run(root, "1", env={"WORKTREE_ROOT": str(sandbox)})
        assert r.returncode == 0, r.stderr
        assert (sandbox / "one-batch-1").is_dir(), r.stdout

    def test_the_sibling_path_is_no_longer_used_when_a_root_is_declared(self, tmp_path):
        """The variable's whole purpose is that the parent need not be on a
        sandbox's writable-path allow-list. A worktree that lands in BOTH places
        would satisfy a naive existence assertion and defeat the point."""
        root = _batch_repo(tmp_path / "bw" / "one")
        sandbox = tmp_path / "declared"
        sandbox.mkdir()
        _batch_run(root, "1", env={"WORKTREE_ROOT": str(sandbox)})
        assert not (tmp_path / "bw" / "one-batch-1").exists()

    def test_unset_keeps_the_historical_sibling_path(self, tmp_path):
        """Byte-identical to every prior release when the variable is unset."""
        root = _batch_repo(tmp_path / "bw" / "one")
        r = _batch_run(root, "1")
        assert r.returncode == 0, r.stderr
        assert (tmp_path / "bw" / "one-batch-1").is_dir()

    def test_worktree_prefix_still_composes_with_the_root(self, tmp_path):
        """`WORKTREE_ROOT` names the parent, `WORKTREE_PREFIX` the leaf. Phase
        262's battery row W07 exists because a first cut had the root OVERRIDE
        the prefix; the same mistake is available here."""
        root = _batch_repo(tmp_path / "bw" / "one")
        sandbox = tmp_path / "declared"
        sandbox.mkdir()
        r = _batch_run(root, "1",
                       env={"WORKTREE_ROOT": str(sandbox), "WORKTREE_PREFIX": "pfx"})
        assert r.returncode == 0, r.stderr
        assert (sandbox / "pfx-batch-1").is_dir(), r.stdout

    def test_a_nonexistent_root_is_refused_here_too(self, tmp_path):
        """Reuse means the guards come with it. If this passes while
        `claim_task.sh`'s equivalent refuses, the call was not wired."""
        root = _batch_repo(tmp_path / "bw" / "one")
        r = _batch_run(root, "1", env={"WORKTREE_ROOT": str(tmp_path / "gone")})
        assert r.returncode == 1
        assert "not an existing directory" in r.stderr, r.stderr


# ── the shared predicate itself ───────────────────────────────────────────

class TestPathIsWorktreeOf:
    def test_a_linked_worktree_of_the_same_repo_passes(self, tmp_path):
        root = _repo(tmp_path / "r")
        wt = tmp_path / "wt"
        subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "x"],
                       cwd=str(root), check=True, capture_output=True)
        assert _lib_call("path_is_worktree_of", str(wt), str(root)).returncode == 0

    def test_a_worktree_of_a_different_repo_fails(self, tmp_path):
        """The identity test. Both trees are real worktrees, and the toplevel
        comparison every prior predicate used passes for both."""
        a = _repo(tmp_path / "a")
        b = _repo(tmp_path / "b")
        wt = tmp_path / "wt"
        subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "x"],
                       cwd=str(a), check=True, capture_output=True)
        assert _lib_call("path_is_worktree_of", str(wt), str(a)).returncode == 0
        assert _lib_call("path_is_worktree_of", str(wt), str(b)).returncode == 1

    def test_a_subdirectory_of_our_own_worktree_fails(self, tmp_path):
        """`--is-inside-work-tree` is true anywhere inside one, which answers a
        different question. The path must be the tree's ROOT.

        **This case is refused by the `.git` test, not by the toplevel test it is
        named for** — see the stray-`.git` case below, which is the one that
        actually isolates the toplevel check."""
        root = _repo(tmp_path / "r")
        sub = root / "sub"
        sub.mkdir()
        assert _lib_call("path_is_worktree_of", str(sub), str(root)).returncode == 1

    def test_a_subdirectory_carrying_a_stray_git_entry_fails(self, tmp_path):
        """The toplevel test's OWN case, and the phase's record was wrong about it.

        Phase 264 first recorded the toplevel and `.git` checks as mutually
        covering no-ops — *"only dropping BOTH is a false accept"* — and a review
        lens refuted it by execution. A subdirectory carrying a stray `.git`
        entry (a nested repo's leftover, a submodule remnant, an editor artifact)
        satisfies the `.git` test, and `git -C <sub> rev-parse --git-common-dir`
        walks UP and answers with OUR common dir, so the identity test passes
        too. Measured: with the toplevel check removed, `<repo>/sub` is
        ACCEPTED — a live hole, and the test above stays green through it because
        its fixture has no `.git` at all.

        The lesson kept in the record: a mutation that survives is not a no-op
        until you have built the input that would distinguish the two."""
        root = _repo(tmp_path / "r")
        sub = root / "sub" / ".git"
        sub.mkdir(parents=True)
        r = _lib_call("path_is_worktree_of", str(root / "sub"), str(root))
        assert r.returncode == 1, (
            "a subdirectory with a stray .git was accepted as a worktree of this "
            "repository — the toplevel check is gone or ineffective"
        )

    def test_a_plain_directory_fails(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        root = _repo(tmp_path / "r")
        assert _lib_call("path_is_worktree_of", str(plain), str(root)).returncode == 1

    def test_an_ambient_git_dir_cannot_make_a_stranger_pass(self, tmp_path):
        """The env scrub. These helpers are handed a FOREIGN path, so an exported
        `GIT_DIR` never expresses the caller's intent about it — unscrubbed,
        `git -C <foreign> rev-parse` answers about the ambient repository and the
        predicate grades the wrong tree."""
        a = _repo(tmp_path / "a")
        b = _repo(tmp_path / "b")
        wt = tmp_path / "wt"
        subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "x"],
                       cwd=str(a), check=True, capture_output=True)
        r = _lib_call("path_is_worktree_of", str(wt), str(b),
                      env={"GIT_DIR": str(b / ".git"), "GIT_WORK_TREE": str(b)})
        assert r.returncode == 1, "an exported GIT_DIR made a foreign tree pass"

    def test_the_scrub_keeps_our_OWN_worktree_recognised(self, tmp_path):
        """The scrub's other direction, and the one that closes the mutation.

        `test_an_ambient_git_dir_cannot_make_a_stranger_pass` above asserts a
        REFUSAL, and an unscrubbed predicate refuses too — for the wrong reason.
        It is therefore vacuous against the mutation that drops the scrub, which
        is how the author's own battery found it surviving. The direction that
        DISCRIMINATES is the false refusal: with `GIT_DIR` pointing at our own
        repository, `git -C <our worktree> rev-parse --show-toplevel` answers with
        the repo root instead of the worktree, so `top -ef candidate` fails and a
        legal resume is refused. Measured: scrubbed answers `.../wt`, unscrubbed
        answers `.../a`."""
        root = _repo(tmp_path / "a")
        wt = tmp_path / "wt"
        subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "x"],
                       cwd=str(root), check=True, capture_output=True)
        r = _lib_call("path_is_worktree_of", str(wt), str(root),
                      env={"GIT_DIR": str(root / ".git"), "GIT_WORK_TREE": str(root)})
        assert r.returncode == 0, (
            "an ambient GIT_DIR made the predicate refuse our own worktree — the "
            "env scrub is gone or ineffective"
        )

    def test_an_exported_cdpath_cannot_redirect_the_common_dir(self, tmp_path):
        """`CDPATH` is the defect this phase's round found in this phase's own code.

        From a PRIMARY checkout git answers with the relative `.git`, and `cd .git`
        consults `CDPATH` because the operand starts with neither `/`, `./` nor
        `../`. An exported `CDPATH` — ordinary in an interactive environment —
        resolved to a decoy `.git` elsewhere AND made `cd` echo the directory it
        reached, so the helper returned two lines. The identity test then compared
        the wrong repository: both scripts refused the operator's OWN worktree,
        accused it of belonging to another checkout, and advised removing it."""
        root = _repo(tmp_path / "r")
        decoy = tmp_path / "decoy"
        (decoy / ".git").mkdir(parents=True)
        clean = _lib_call("git_common_dir_abs", str(root))
        hijack = _lib_call("git_common_dir_abs", str(root), env={"CDPATH": str(decoy)})
        assert clean.returncode == 0 and hijack.returncode == 0, hijack.stderr
        assert hijack.stdout == clean.stdout, (
            f"CDPATH changed the answer: {clean.stdout!r} -> {hijack.stdout!r}"
        )
        assert hijack.stdout.strip().count("\n") == 0, (
            f"the helper returned more than one line: {hijack.stdout!r} — a newline "
            f"here lands in the lock's line-anchored workspace: field"
        )

    def test_an_exported_cdpath_cannot_make_the_claim_refuse_our_own_worktree(self, tmp_path):
        """The end-to-end half. The unit test above pins the helper; this pins the
        consequence, because the harm was a false accusation plus a `rm` remedy on
        the operator's live work — on the DOMINANT resume path, not an edge."""
        root = _seeded(tmp_path / "solo")
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        decoy = tmp_path / "decoy"
        (decoy / ".git").mkdir(parents=True)
        env = {**_path_env(_py3_bin(tmp_path)), "WORKTREE_ROOT": str(sandbox)}
        first = _run(root, "T-0001", "feat/t1", env=env)
        assert first.returncode == 0, first.stderr
        again = _run(root, "T-0001", "feat/t1", env={**env, "CDPATH": str(decoy)})
        assert again.returncode == 0, (
            f"CDPATH made the claim refuse its own worktree:\n{again.stderr}"
        )

    def test_git_common_dir_abs_is_absolute_from_a_primary_checkout(self, tmp_path):
        """From a primary checkout git answers with the RELATIVE `.git`. A
        comparison that skips absolutising matches two unrelated repositories on
        the string `.git` — a false accept, the fail-open direction."""
        root = _repo(tmp_path / "r")
        out = _lib_call("git_common_dir_abs", str(root))
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip().startswith("/"), out.stdout
        assert out.stdout.strip() != ".git"


def test_both_batch_work_sites_use_the_identity_predicate():
    """`Q-415`'s must-agree invariant, enforced rather than asserted in prose.

    `batch_work.sh` states beside its point of use that the two tests "have to
    agree, or the preflight refuses a shape this arm would have accepted (or
    worse, the reverse)". Nothing checked it. Reverting only the point of use to
    the pre-264 `path_is_worktree` survives every behavioural test, because the
    preflight refuses a foreign tree first and no live path reaches the second
    arm with one — measured as a surviving mutation, not assumed.

    So the pin is a source read. **Comments are stripped before anything is
    counted, and that is the load-bearing part**: the first version scoped to
    lines mentioning `$WORKTREE_DIR` and counted lines containing the literal
    call, which a reviewer defeated with

        if path_is_worktree "$WORKTREE_DIR"; then # was path_is_worktree_of ...

    — one line, both counts satisfied, the fix reverted, 36/36 green. The
    docstring claimed this pin avoided Phase 263's needle-inside-its-own-haystack
    by scoping per line; per-line scoping is exactly where the needle fits, and
    the person who wrote that sentence is the one it fooled."""
    src = (SCRIPT.parent / "batch_work.sh").read_text()
    code = [l.split("#", 1)[0] for l in src.splitlines()]
    calls = [l.strip() for l in code
             if "path_is_worktree" in l and "$WORKTREE_DIR" in l]
    assert len(calls) == 3, (
        f"expected exactly three WORKTREE_DIR predicate calls in batch_work.sh "
        f"(preflight narrow + preflight's message discriminator + point of use); "
        f"found {len(calls)}:\n  " + "\n  ".join(calls)
    )
    narrow = [c for c in calls if 'path_is_worktree_of "$WORKTREE_DIR" "$MAIN_ROOT"' in c]
    assert len(narrow) == 2, (
        "the preflight and the point of use must BOTH ask whose worktree it is — "
        f"only {len(narrow)} of them does:\n  " + "\n  ".join(calls)
    )


def test_both_scripts_hand_the_validator_the_PRIMARY_checkout():
    """The `Q-020`/`Q-307` class, pinned on both callers instead of one.

    `worktree_root_parent`'s arm 1 compares against whatever checkout it is
    handed. `git rev-parse --show-toplevel` answers "which worktree am I standing
    in", so handing it that instead of the primary makes arm 1 compare against the
    wrong tree. A review lens found this pinned on `claim_task.sh` and unpinned on
    `batch_work.sh`, and judged the impact message-only on the grounds that arm 2
    covers it. **Measured, that is wrong in one case**: with a root inside the
    primary checkout's `.git`, arm 2 exits 128 and sees nothing, so the wrong
    argument makes it ACCEPTED. Arm 2 does cover the ordinary case, which is why
    the assessment looked right.

    Comments stripped before matching, for the reason the batch pin above gives."""
    for name, expected in (("claim_task.sh", '"$_primary_root"'),
                           ("batch_work.sh", '"$MAIN_ROOT"')):
        src = (SCRIPT.parent / name).read_text()
        code = [l.split("#", 1)[0] for l in src.splitlines()]
        calls = [l.strip() for l in code if "worktree_root_parent" in l]
        assert len(calls) == 1, f"{name}: expected one call, found {calls}"
        assert f"worktree_root_parent {expected}" in calls[0], (
            f"{name} hands the root validator {calls[0]!r} rather than the primary "
            f"checkout ({expected}). `--show-toplevel` answers which worktree the "
            f"caller stands in, and arm 2 cannot cover the .git case."
        )


def test_this_module_is_still_collected():
    """The class Phase 263 and Phase 262 both had to guard: a module can be
    deleted, or its consequential tests renamed to something the reader skims
    past, and the suite stays green. Name the ones that must survive."""
    import test_worktree_identity_guard as mod
    required = [
        ("TestClaimTaskAdoption", "test_a_second_checkout_is_refused_the_first_s_worktree"),
        ("TestClaimTaskAdoption", "test_the_refusal_writes_no_lock"),
        ("TestClaimTaskAdoption", "test_our_own_worktree_is_still_resumed"),
        ("TestBatchWorkAdoption", "test_a_second_checkout_is_refused_the_first_s_batch_worktree"),
        ("TestBatchWorkAdoption", "test_the_refusal_does_not_flip_the_batch_status"),
        ("TestAnyWorkTreeContainment", "test_claim_task_refuses_a_root_inside_another_repository"),
        ("TestAnyWorkTreeContainment", "test_a_root_outside_every_repository_is_accepted"),
        ("TestBatchWorktreeRoot", "test_batch_work_honours_worktree_root"),
        ("TestBatchWorktreeRoot", "test_the_sibling_path_is_no_longer_used_when_a_root_is_declared"),
        ("TestPathIsWorktreeOf", "test_a_worktree_of_a_different_repo_fails"),
        ("TestPathIsWorktreeOf", "test_an_ambient_git_dir_cannot_make_a_stranger_pass"),
        ("TestPathIsWorktreeOf", "test_the_scrub_keeps_our_OWN_worktree_recognised"),
        ("TestPathIsWorktreeOf", "test_an_exported_cdpath_cannot_redirect_the_common_dir"),
        ("TestPathIsWorktreeOf", "test_a_subdirectory_carrying_a_stray_git_entry_fails"),
        ("TestAnyWorkTreeContainment", "test_arm_one_carries_coverage_arm_two_cannot"),
        ("TestAnyWorkTreeContainment", "test_a_ceiling_cannot_switch_off_the_any_work_tree_arm"),
    ]
    for cls, name in required:
        assert hasattr(getattr(mod, cls), name), f"{cls}::{name} is gone"
    assert hasattr(mod, "test_both_batch_work_sites_use_the_identity_predicate"), (
        "the only guard on the must-agree invariant is gone")
    assert hasattr(mod, "test_both_scripts_hand_the_validator_the_PRIMARY_checkout"), (
        "the only guard on the wrong-checkout class is gone")
    assert sys.modules[__name__].__doc__, "the module docstring carries the why"
