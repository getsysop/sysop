"""Phase 266: a workspace is adopted only when it is ours AND on the right branch.

Two filings, one surface, and the surface is `claim_task.sh`'s decision to reuse a
directory that is already there. Phase 264 (`Q-405`) taught worktree mode to ask
*whose* tree this is; neither mode's adoption was complete after it:

  * `Q-417` — `--clone` adopted an existing directory on `rev-parse --git-dir`,
    which answers *is this a repository* and never *whose*. A stranger `git init`
    at the computed clone path was adopted at exit 0, printed "Start working!",
    and wrote a lock whose `workspace:` named a tree containing one file.
  * `Q-416` — an adopted WORKTREE's branch was never checked, so the lock
    recorded `branch: feat/b` over a tree sitting on `feat/a`. `/review-close`
    Step 3b then collects from that workspace on the strength of the lock's pair.

**The asymmetry is why one phase took both.** On the BRANCH question `--clone` was
already strong (`Q-276`, Phase 220) and worktree blind; on the IDENTITY question
it was the other way round. Each mode's fix is the other mode's shipped code.

**The two fixes are NOT one predicate**, and assuming they were is the trap this
module pins. `path_is_worktree_of` cannot serve `--clone`: a clone is a separate
repository by construction, so it would refuse every legitimate one. `--clone`
needs identity of ORIGIN, which needs normalisation — `TestRemoteIdentity` below
is the whole reason, and `test_an_exact_string_test_would_refuse_this_one` is the
case this machine actually has.

**These tests drive the real script**, because both defects were exit-0 paths
whose damage was the record they left, not an error they raised. Every refusal
test asserts no lock was written; the ones whose refusal could plausibly race the
index flip also assert `status: open`. (The first draft of this sentence said
*every* refusal asserted both — the round counted two of five. The index flip
happens after all of these exit, so the gap was harmless and the claim was still
false, which is the half that matters in a file that ships.)
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_claim_task_sh import SCRIPT, _git, _repo, _run

LIB = SCRIPT.parent / "_git_lib.sh"

INDEX = ("tasks:\n  - id: T-0001\n    title: Demo\n    status: open\n"
         "    priority: high\n    effort: S\n    blast_radius: local\n")
BODY = "---\nid: T-0001\nstatus: open\n---\nbody\n"


def _lib_call(func, *args, env=None):
    """Drive one `_git_lib.sh` function in a subshell; returns the CompletedProcess.

    Same shape as `test_worktree_identity_guard.py`'s helper of this name, and
    deliberately a copy rather than an import: that module's version is bound to
    its own `LIB`, and a shared one would make either module's failure ambiguous
    about which file it loaded.
    """
    e = dict(os.environ)
    e.update({"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"})
    if env:
        e.update(env)
    quoted = " ".join(f'"{a}"' for a in args)
    return subprocess.run(
        ["bash", "-c", f'source "{LIB}" || exit 9\n{func} {quoted}'],
        capture_output=True, text=True, env=e,
    )


def _identity(url, base=""):
    r = _lib_call("remote_identity", url, base)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _seeded(parent, name="w", origin=True):
    """A claimable checkout, with a bare `origin` on disk unless told otherwise."""
    parent.mkdir(parents=True, exist_ok=True)
    root = _repo(parent / name)
    (root / "tasks" / "open").mkdir(parents=True)
    (root / "tasks" / "index.yml").write_text(INDEX)
    (root / "tasks" / "open" / "T-0001.md").write_text(BODY)
    (root / ".gitignore").write_text("sysop/runtime/\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "tasks")
    if origin:
        bare = parent / f"{name}-origin.git"
        # `-c init.defaultBranch=main` for the reason
        # `test_claim_clone_and_flag_order.py` gives: without it the bare repo's
        # HEAD follows the RUNNER's git default, so a clone lands on `master` in
        # CI and on `main` here, and every branch assertion fails only in CI.
        subprocess.run(["git", "-c", "init.defaultBranch=main",
                        "init", "--bare", "-q", str(bare)],
                       check=True, capture_output=True)
        _git(root, "remote", "add", "origin", str(bare))
        _git(root, "push", "-q", "origin", "main")
    return root


def _workspace_of(root):
    """Where `claim_task.sh` computes the workspace for `T-0001` from *root*."""
    return root.parent / f"{root.name}-t-0001"


def _locks(root):
    d = root / "sysop" / "runtime" / "locks"
    return sorted(p.name for p in d.glob("*.lock")) if d.is_dir() else []


def _branch_of(d):
    return subprocess.run(["git", "branch", "--show-current"], cwd=str(d),
                          capture_output=True, text=True).stdout.strip()


# ── the normaliser ────────────────────────────────────────────────────────

class TestRemoteIdentity:
    """`Q-417`'s decision, pinned. The refusal is only correct if the ACCEPT is:
    an identity test that refuses a legitimate clone is a new defect, not a
    conservative one."""

    SAME = [
        "git@github.com:getsysop/sysop.git",
        "git@github.com:getsysop/sysop",
        "ssh://git@github.com/getsysop/sysop",
        "ssh://git@github.com/getsysop/sysop.git",
        "ssh://git@github.com:22/getsysop/sysop.git",
        "https://github.com/getsysop/sysop.git",
        "https://github.com/getsysop/sysop",
        "https://wade@github.com/getsysop/sysop.git",
        "https://github.com/getsysop/sysop.git/",
        "git://github.com/getsysop/sysop.git",
    ]

    def test_every_spelling_of_one_repository_is_one_identity(self):
        tokens = {_identity(u) for u in self.SAME}
        assert len(tokens) == 1, tokens

    def test_an_exact_string_test_would_refuse_this_one(self):
        """Not hypothetical. One checkout mixing the two spellings is ordinary:
        `gh auth status` reports a `Git operations protocol` while a hand-written
        runbook prescribes whichever spelling its author used, and the two
        disagree. A string compare would refuse a correct clone on such a
        machine — and this exact split is what prompted the decision."""
        ssh = "git@github.com:getsysop/sysop.git"
        https = "https://github.com/getsysop/sysop.git"
        assert ssh != https
        assert _identity(ssh) == _identity(https)

    @pytest.mark.parametrize("other", [
        "git@github.com:getsysop/other.git",          # different repo
        "git@github.com:someoneelse/sysop.git",       # different owner
        "git@gitlab.com:getsysop/sysop.git",          # different host
        "https://github.com/getsysop/sysop/extra",    # deeper path
    ])
    def test_a_different_repository_is_a_different_identity(self, other):
        assert _identity(other) != _identity("git@github.com:getsysop/sysop.git")

    def test_the_host_is_case_folded(self):
        assert _identity("https://GitHub.COM/getsysop/sysop.git") == \
               _identity("https://github.com/getsysop/sysop.git")

    def test_the_path_is_NOT_case_folded(self):
        """The ratified rule, and the asymmetry behind it: a false REFUSAL costs
        one message and a re-run, a false ACCEPT is the defect being closed. On a
        case-sensitive host two paths differing only in case are two
        repositories, and this test is what stops a later 'tidy-up' folding
        both."""
        assert _identity("https://github.com/GetSysop/sysop.git") != \
               _identity("https://github.com/getsysop/sysop.git")

    def test_a_local_path_and_a_url_never_compare_equal(self):
        """The form is the token's first field for exactly this reason."""
        assert _identity("/srv/git/sysop.git").startswith("path\t")
        assert _identity("https://github.com/getsysop/sysop.git").startswith("url\t")
        assert _identity("/github.com/getsysop/sysop") != \
               _identity("https://github.com/getsysop/sysop")

    def test_an_empty_url_returns_one_and_prints_nothing(self):
        r = _lib_call("remote_identity", "")
        assert r.returncode == 1
        assert r.stdout == ""

    def test_a_scp_like_colon_is_a_path_not_a_port(self):
        """The one arm that cannot be folded into the URL arm. `host:22/o/r` with
        no scheme means the PATH `22/o/r`, not port 22 — git reads it that way and
        so must this."""
        assert _identity("git@host:22/o/r.git") != _identity("ssh://git@host:22/o/r.git")
        assert _identity("git@host:22/o/r.git") == _identity("ssh://git@host/22/o/r.git")

    def test_an_ipv6_literal_keeps_its_brackets(self):
        assert _identity("ssh://git@[::1]:22/o/r.git") == "url\t[::1]/o/r"

    def test_a_PREFIX_of_our_path_is_a_different_repository(self):
        """The round's sharpest survivor (its X11): widening the comparison from
        equality to a prefix match walked through every guard, because no fixture
        paired prefix-related origins. `acme/api` must not accept
        `acme/api-internal` — the fold rows all mutate what the normaliser
        strips, and none of them mutates the comparison's strictness."""
        assert _identity("https://github.com/acme/api.git") != \
               _identity("https://github.com/acme/api-internal.git")
        assert _identity("https://github.com/acme/api.git") != \
               _identity("https://github.com/acme/api/sub.git")

    def test_a_doubled_slash_after_the_host_still_folds(self):
        """The round's N05. `https://h//o/r` is a legal spelling of `https://h/o/r`
        for the leading position; the strip is what makes them one remote."""
        assert _identity("https://h//o/r.git") == _identity("https://h/o/r.git")

    def test_only_ONE_trailing_dot_git_is_stripped(self):
        """A repository really can be named `r.git`, so `o/r.git.git` is `o/r.git`
        and not `o/r`. The round's X05 — stripping repeatedly survived, because
        nothing paired those two."""
        assert _identity("https://h/o/r.git.git") == "url\th/o/r.git"
        assert _identity("https://h/o/r.git.git") != _identity("https://h/o/r.git")
        assert _identity("https://h/o/r.git") == _identity("https://h/o/r.git/")

    def test_a_slash_before_the_colon_means_a_local_path(self):
        """git reads `a/b:c` as a local path, not as scp-like — measured:
        `git ls-remote a/b:c` says "does not appear to be a git repository" while
        `h:c` says "could not resolve hostname". Before the round's fix this was
        parsed as host `a/b`, and since a token is `host` + `/` + `path`, it
        collided with `https://a/b/c`. The scp arm is the only route by which a
        `/` can reach the host field, so this is the whole of that collision."""
        assert _identity("a/b:c").startswith("path\t")
        assert _identity("a/b:c") != _identity("https://a/b/c")
        assert _identity("h:c") == "url\th/c"


class TestRemotePathIdentity:
    """Local paths are not an edge case here: every fixture in this tree uses a
    bare repo on disk as `origin`, and so does any consumer whose remote is a
    path."""

    def test_two_spellings_of_one_directory_resolve_together(self, tmp_path):
        """The macOS case that makes this load-bearing rather than tidy: `/tmp`
        is a symlink to `/private/tmp`, so one bare repo reached by two spellings
        must not read as two remotes."""
        real = tmp_path / "real" / "origin.git"
        real.mkdir(parents=True)
        link = tmp_path / "alias"
        link.symlink_to(tmp_path / "real")
        assert _identity(str(real)) == _identity(str(link / "origin.git"))

    def test_a_relative_path_resolves_against_the_declaring_repo(self, tmp_path):
        """git resolves a relative remote against the repository that declares
        it, never against the caller's CWD."""
        base = tmp_path / "repos" / "mine"
        (tmp_path / "repos" / "origin.git").mkdir(parents=True)
        base.mkdir(parents=True)
        assert _identity("../origin.git", str(base)) == \
               _identity(str(tmp_path / "repos" / "origin.git"))

    def test_a_relative_path_with_no_base_is_left_as_written(self):
        assert _identity("../origin.git") == "path\t../origin.git"

    def test_dot_git_is_not_stripped_from_a_path(self, tmp_path):
        """Unlike the URL arm. `.git` is part of a bare repository's real
        directory name, and stripping it would send `cd` at a path that does not
        exist — which would silently disable the physical resolution above."""
        real = tmp_path / "origin.git"
        real.mkdir()
        assert _identity(str(real)).endswith("origin.git")

    def test_a_trailing_slash_is_stripped_on_a_path_that_does_not_exist(self):
        """The round's P03. An existing path is absorbed by `cd`+`pwd -P`, so the
        strip only shows on a path that is not there — which is exactly the case
        that falls through to string comparison."""
        assert _identity("/gone/p266/origin.git/") == _identity("/gone/p266/origin.git")

    def test_a_file_url_is_a_path(self, tmp_path):
        real = tmp_path / "origin.git"
        real.mkdir()
        assert _identity(f"file://{real}") == _identity(str(real))


class TestOriginIdentity:
    def test_a_repository_with_no_origin_returns_one(self, tmp_path):
        """Unidentifiable, not innocent — the caller refuses on 1."""
        r = _repo(tmp_path / "solo")
        assert _lib_call("origin_identity", str(r)).returncode == 1

    def test_a_non_repository_returns_one(self, tmp_path):
        d = tmp_path / "plain"
        d.mkdir()
        assert _lib_call("origin_identity", str(d)).returncode == 1

    def test_it_resolves_a_RELATIVE_origin_against_the_repo_that_declares_it(self, tmp_path):
        """The round's O03, and the only survivor of its three that reaches live
        behaviour. `remote_identity`'s base parameter was covered; `origin_identity`
        PASSING it was not, so dropping that argument survived every guard — and a
        relative origin then never resolves. Bare repos on disk are how every
        fixture here spells `origin`, and a relative one is ordinary."""
        parent = tmp_path / "repos"
        bare = parent / "origin.git"
        subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "--bare",
                        "-q", str(bare)], check=True, capture_output=True)
        r = _repo(parent / "mine")
        _git(r, "remote", "add", "origin", "../origin.git")
        got = _lib_call("origin_identity", str(r))
        assert got.returncode == 0, got.stderr
        assert got.stdout.strip() == _identity(str(bare)), (
            "a relative origin was not resolved against the declaring repo")

    def test_a_subdirectory_of_another_repo_does_not_borrow_its_origin(self, tmp_path):
        """`git -C <dir>` performs UPWARD DISCOVERY, and the scrub unsets
        `GIT_CEILING_DIRECTORIES`, so the first cut answered rc=0 with the
        ENCLOSING repository's origin for a plain empty directory — falsifying the
        function's own header and making the caller's refusal messages state
        falsehoods about it. Same hazard `path_is_worktree_of` documents for
        `--is-inside-work-tree`, same remedy."""
        outer = _repo(tmp_path / "outer")
        _git(outer, "remote", "add", "origin", "https://example.com/outer/outer.git")
        inner = outer / "plain-directory"
        inner.mkdir()
        assert _lib_call("origin_identity", str(inner)).returncode == 1
        assert _lib_call("path_is_worktree_root", str(inner)).returncode == 1

    def test_an_unset_origin_url_does_not_become_a_fabricated_token(self, tmp_path):
        """`git remote get-url origin` prints the remote NAME at rc=0 when
        `remote.origin.url` is unset or empty, so the first cut turned such a repo
        into `path\t<dir>/origin` AT SUCCESS — the one case the caller's no-origin
        message exists for. `config --get` returns 1 for an absent key."""
        r = _repo(tmp_path / "blank")
        subprocess.run(["git", "config", "remote.origin.url", ""], cwd=str(r),
                       check=True, capture_output=True)
        got = _lib_call("origin_identity", str(r))
        assert got.returncode == 1, got.stdout

    def test_an_ambient_GIT_WORK_TREE_cannot_forge_a_worktree_root(self, tmp_path):
        """**The scrub's real subject, and the round's last surviving mutation.**
        Dropping the scrub from `path_is_worktree_root` still refuses a stranger
        under an ambient `GIT_DIR` — but for the wrong reason: `--show-toplevel`
        answers about the ambient repo, whose root is not `-ef` the candidate, so
        the comparison neutralises the redirection by accident. `GIT_WORK_TREE`
        is the variable that makes the answer EQUAL the candidate, and then a
        plain directory is accepted as a working tree root. Measured both ways:
        rc=1 with the scrub, rc=0 without it.

        This is why a mutation that "is killed" is not the same as a guard that
        sees the defect — the old fixture killed nothing it was named for."""
        plain = tmp_path / "plain"
        plain.mkdir()
        elsewhere = _repo(tmp_path / "elsewhere")
        r = _lib_call("path_is_worktree_root", str(plain),
                      env={"GIT_DIR": str(elsewhere / ".git"),
                           "GIT_WORK_TREE": str(plain)})
        assert r.returncode == 1, "a plain directory was accepted as a worktree root"

    def test_an_ambient_git_dir_cannot_lend_our_origin_to_a_stranger(self, tmp_path):
        """The second scrub, on the config read. A stranger repository is a real
        worktree root, so it clears the predicate above — and if `config --get`
        then answers from the AMBIENT repository, the stranger comes back wearing
        OUR origin and the caller adopts it. That is the fail-open direction, and
        it is a different site from the one the test below covers."""
        ours = _seeded(tmp_path / "a")
        stranger = _repo(tmp_path / "b" / "stranger")
        _git(stranger, "remote", "add", "origin", "https://example.com/not/ours.git")
        r = _lib_call("origin_identity", str(stranger),
                      env={"GIT_DIR": str(ours / ".git")})
        assert r.returncode == 0, r.stderr
        assert "not/ours" in r.stdout, (
            "the stranger borrowed the ambient repository's origin: " + r.stdout)

    def test_an_ambient_git_dir_cannot_answer_for_a_foreign_path(self, tmp_path):
        """The git-env scrub, and the direction it protects: with `GIT_DIR`
        exported an unscrubbed probe answers about the AMBIENT repository, which
        reads a stranger's directory as ours — fail-open."""
        ours = _seeded(tmp_path / "a")
        stranger = _repo(tmp_path / "b" / "stranger")
        r = _lib_call("origin_identity", str(stranger),
                      env={"GIT_DIR": str(ours / ".git")})
        assert r.returncode == 1, r.stdout


# ── Q-417: --clone adopts only OUR repository ─────────────────────────────

class TestCloneAdoptionIdentity:
    def test_another_project_at_the_clone_path_is_refused(self, tmp_path):
        """The sharper half of `Q-417`, and the one the no-origin arm below does
        NOT cover: a complete, origin-backed repository that simply is not ours.
        Nothing about it is malformed — only its identity is wrong."""
        root = _seeded(tmp_path / "a")
        stranger = _seeded(tmp_path / "b", name="theirs")
        # Move it to the path our claim will compute, remote and all.
        stranger.rename(_workspace_of(root))
        moved = _workspace_of(root)
        _git(moved, "checkout", "-q", "-b", "feat/a")

        r = _run(root, "--lock", "--clone", "T-0001", "feat/a")
        assert r.returncode != 0, r.stdout + r.stderr
        assert "DIFFERENT repository" in r.stderr, r.stderr
        assert _locks(root) == [], "a refusal must record nothing"
        assert "status: open" in (root / "tasks" / "index.yml").read_text()

    def test_a_stranger_git_init_at_the_clone_path_is_refused(self, tmp_path):
        """The filed reproduction verbatim — a bare `git init`, which has no
        `origin`. Pre-fix this exited 0, printed 'Start working!', and wrote a
        lock whose `workspace:` named a tree containing one file."""
        root = _seeded(tmp_path / "a")
        stranger = _workspace_of(root)
        _repo(stranger)
        (stranger / "stranger.txt").write_text("not ours\n")
        _git(stranger, "add", "-A")
        _git(stranger, "commit", "-qm", "stranger")
        _git(stranger, "checkout", "-q", "-b", "feat/a")

        r = _run(root, "--lock", "--clone", "T-0001", "feat/a")
        assert r.returncode != 0, r.stdout + r.stderr
        assert "no 'origin' remote" in r.stderr, r.stderr
        assert _locks(root) == [], "a refusal must record nothing"
        assert "status: open" in (root / "tasks" / "index.yml").read_text()
        assert [p.name for p in stranger.glob("*.txt")] == ["stranger.txt"]

    def test_a_plain_directory_inside_another_repo_gets_the_RIGHT_refusal(self, tmp_path):
        """The round's M27 survivor. Reverting the caller's gate from
        `path_is_worktree_root` to `rev-parse --git-dir` still ends in a refusal —
        `origin_identity` catches it a step later — so exit code and lock
        assertions cannot see the difference. What changes is the DIAGNOSIS: the
        operator is told this directory is "a git repository with no 'origin'"
        when it is not a repository at all, which is one of the two false messages
        the round filed. The message is the assertion, because it is the only
        thing that moves."""
        root = _seeded(tmp_path / "a")
        # The workspace path is a plain directory nested inside ANOTHER checkout,
        # so `rev-parse --git-dir` answers yes by upward discovery.
        outer = _repo(tmp_path / "a" / "outer")
        _git(outer, "remote", "add", "origin", "https://example.com/outer/outer.git")
        ws = _workspace_of(root)
        ws.symlink_to(outer / "plain-directory")
        (outer / "plain-directory").mkdir()

        r = _run(root, "--lock", "--clone", "T-0001", "feat/a")
        assert r.returncode != 0, r.stdout + r.stderr
        assert "not the root of a git repository" in r.stderr, (
            "the refusal blamed the wrong thing: " + r.stderr)
        assert _locks(root) == []

    def test_a_legitimate_clone_spelled_differently_is_ACCEPTED(self, tmp_path):
        """The half that makes the refusal safe. The existing clone points at the
        same bare repo through a SYMLINKED path — a different string, the same
        remote — and an exact-string test would refuse it."""
        root = _seeded(tmp_path / "a")
        _git(root, "branch", "feat/a")
        _git(root, "push", "-q", "-u", "origin", "feat/a")
        clone = _workspace_of(root)
        subprocess.run(["git", "clone", "-q", str(tmp_path / "a" / "w-origin.git"),
                        str(clone)], check=True, capture_output=True)
        alias = tmp_path / "a" / "aliased.git"
        alias.symlink_to(tmp_path / "a" / "w-origin.git")
        _git(clone, "remote", "set-url", "origin", str(alias))
        _git(clone, "checkout", "-q", "feat/a")

        r = _run(root, "--lock", "--clone", "T-0001", "feat/a")
        assert r.returncode == 0, r.stdout + r.stderr
        assert _locks(root) == ["T-0001.lock"]

    def test_the_refusal_happens_before_the_branch_is_pushed(self, tmp_path):
        """This block's own stated ordering rule — 'an invocation that is going
        to be refused does not first publish a branch'. The identity check sits
        with the other directory refusal, above the push, for that reason."""
        root = _seeded(tmp_path / "a")
        stranger = _workspace_of(root)
        _repo(stranger)
        _git(stranger, "checkout", "-q", "-b", "feat/a")

        r = _run(root, "--lock", "--clone", "T-0001", "feat/a")
        assert r.returncode != 0
        remote = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", "feat/a"],
            cwd=str(root), capture_output=True, text=True).stdout
        assert remote.strip() == "", f"the branch reached origin anyway: {remote!r}"


# ── Q-416: an adopted worktree is on the branch the lock records ──────────

class TestWorktreeAdoptionBranch:
    def _claim_then_orphan(self, tmp_path, branch="feat/a"):
        """Claim once, then remove the lock — `--entry-state`'s `resumable`
        state, and what `/review-close` leaves when it unlinks the lock on the
        integration branch while the `done` flip rides the PR."""
        root = _seeded(tmp_path / "a", origin=False)
        r = _run(root, "--lock", "--worktree", "T-0001", branch)
        assert r.returncode == 0, r.stdout + r.stderr
        for lock in (root / "sysop" / "runtime" / "locks").glob("*.lock"):
            lock.unlink()
        return root

    def test_a_wrong_branch_worktree_is_CORRECTED_not_recorded_over(self, tmp_path):
        """The filed defect: pre-fix this exited 0 with the worktree still on
        `feat/a` and the lock reading `branch: feat/b`."""
        root = self._claim_then_orphan(tmp_path)
        ws = _workspace_of(root)
        assert _branch_of(ws) == "feat/a"

        r = _run(root, "--lock", "--worktree", "T-0001", "feat/b")
        assert r.returncode == 0, r.stdout + r.stderr
        assert _branch_of(ws) == "feat/b", "the worktree was left on the old branch"
        lock = (root / "sysop" / "runtime" / "locks" / "T-0001.lock").read_text()
        assert "branch: feat/b" in lock
        assert "moved from 'feat/a'" in r.stdout, r.stdout

    def test_a_worktree_already_on_the_branch_is_resumed_quietly(self, tmp_path):
        """The dominant path, and the one a correction must not disturb."""
        root = self._claim_then_orphan(tmp_path)
        r = _run(root, "--lock", "--worktree", "T-0001", "feat/a")
        assert r.returncode == 0, r.stdout + r.stderr
        assert _branch_of(_workspace_of(root)) == "feat/a"
        assert "already on 'feat/a'" in r.stdout, r.stdout

    def test_a_dirty_worktree_that_cannot_be_checked_out_is_REFUSED(self, tmp_path):
        """`Q-276`'s resolution, applied here: verify, correct if we can, refuse
        if we cannot. The refusal records nothing and leaves the tree alone."""
        root = self._claim_then_orphan(tmp_path)
        ws = _workspace_of(root)
        (ws / "README.md").write_text("committed on feat/a\n")
        _git(ws, "add", "-A")
        _git(ws, "commit", "-qm", "on feat/a")
        (ws / "README.md").write_text("uncommitted\n")

        r = _run(root, "--lock", "--worktree", "T-0001", "feat/b")
        assert r.returncode != 0, r.stdout + r.stderr
        assert "could not be checked out" in r.stderr, r.stderr
        assert _locks(root) == [], "a refusal must record nothing"
        assert _branch_of(ws) == "feat/a", "the worktree was moved anyway"
        assert (ws / "README.md").read_text() == "uncommitted\n", "work was lost"

    def test_a_branch_checked_out_in_another_worktree_is_REFUSED(self, tmp_path):
        """The second legitimate refusal, and the reason there is no
        `status --porcelain` probe: git refuses a branch that is checked out
        elsewhere in this repository, and a dirtiness test would not see it."""
        root = self._claim_then_orphan(tmp_path)
        other = tmp_path / "a" / "other-wt"
        subprocess.run(["git", "worktree", "add", "-q", str(other), "-b", "feat/b"],
                       cwd=str(root), check=True, capture_output=True)

        r = _run(root, "--lock", "--worktree", "T-0001", "feat/b")
        assert r.returncode != 0, r.stdout + r.stderr
        assert _locks(root) == []
        assert _branch_of(_workspace_of(root)) == "feat/a"

    def test_the_PRIMARY_checkout_is_never_adopted_or_checked_out(self, tmp_path):
        """**The round's § High, and it was introduced by this phase's own fix.**
        `path_is_worktree_of` accepts any working tree of the repository — the
        primary checkout included, by construction. Before the branch correction
        existed that produced only a wrong record; with it, the claim CHECKED THE
        OPERATOR'S MAIN CHECKOUT OUT onto the claim branch and reported success,
        and nothing puts it back.

        Reachable with no symlink and no privileges: `WORKTREE_PREFIX=proj` in a
        checkout named `proj-t-0001` computes the workspace path onto itself.
        `--release` has guarded this state with `-ef` since Phase 91; the claim
        path now does too, and it refuses BEFORE the branch is created."""
        root = _seeded(tmp_path / "p", name="proj-t-0001", origin=False)
        assert _branch_of(root) == "main"

        r = _run(root, "--lock", "--worktree", "T-0001", "feat/z",
                 env={"WORKTREE_PREFIX": "proj"})
        assert r.returncode != 0, r.stdout + r.stderr
        assert "PRIMARY checkout" in r.stderr, r.stderr
        assert _branch_of(root) == "main", "the claim moved the primary checkout"
        assert _locks(root) == []
        assert "feat/z" not in subprocess.run(
            ["git", "branch", "--format=%(refname:short)"], cwd=str(root),
            capture_output=True, text=True).stdout.split(), (
            "a branch was created before the refusal")

    def test_a_symlink_onto_the_primary_checkout_is_refused_too(self, tmp_path):
        """The same defect by its other route. `-ef` compares inodes, so a
        symlinked spelling cannot make the identity test MISS — the reason this
        file gives for `-ef` everywhere else."""
        root = _seeded(tmp_path / "a", origin=False)
        ws = _workspace_of(root)
        ws.symlink_to(root)

        r = _run(root, "--lock", "--worktree", "T-0001", "feat/z")
        assert r.returncode != 0, r.stdout + r.stderr
        assert _branch_of(root) == "main", "the claim moved the primary checkout"
        assert _locks(root) == []

    def test_a_fresh_worktree_is_unaffected(self, tmp_path):
        """The correction lives in the adopt arm only; the create arm still puts
        the worktree on the branch itself."""
        root = _seeded(tmp_path / "a", origin=False)
        r = _run(root, "--lock", "--worktree", "T-0001", "feat/a")
        assert r.returncode == 0, r.stdout + r.stderr
        assert _branch_of(_workspace_of(root)) == "feat/a"


# ── Q-416's other half: the sibling script ────────────────────────────────

class TestBatchWorkAdoptionBranch:
    """**The population was the filing, not the class — for the second time.**
    `Q-415` was the identity half: Phase 264 fixed `claim_task.sh` and
    `batch_work.sh` had the same defect. Phase 266's first cut fixed the BRANCH
    half in `claim_task.sh` only, because `Q-416` names only that script — and
    its round found the identical defect here. These tests exist so the pair
    cannot split a third time."""

    def _repo_with_batch(self, tmp_path, branch="review/one"):
        from test_batch_work_sh import _repo as _bw_repo
        root = _bw_repo(tmp_path / "bw")
        return root

    def test_a_wrong_branch_worktree_is_CORRECTED_here_too(self, tmp_path):
        from test_batch_work_sh import _repo as _bw_repo, _run as _bw_run
        root = _bw_repo(tmp_path / "bw")
        r = _bw_run(root, "1")
        assert r.returncode == 0, r.stdout + r.stderr
        ws = root.parent / f"{root.name}-batch-1"
        assert ws.is_dir(), r.stdout
        started_on = _branch_of(ws)

        # Move the adopted worktree off the batch branch, then re-run.
        _git(ws, "checkout", "-q", "-b", "someone-elses-work")
        assert _branch_of(ws) == "someone-elses-work"
        r2 = _bw_run(root, "1")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert _branch_of(ws) == started_on, (
            "the lock's branch was recorded over a worktree on another branch")

    def test_a_dirty_worktree_is_REFUSED_here_too(self, tmp_path):
        from test_batch_work_sh import _repo as _bw_repo, _run as _bw_run
        root = _bw_repo(tmp_path / "bw")
        assert _bw_run(root, "1").returncode == 0
        ws = root.parent / f"{root.name}-batch-1"
        on_batch = _branch_of(ws)

        # The two branches must DIVERGE in the dirty file, or git carries the
        # uncommitted change across and the checkout legitimately succeeds —
        # which is what the first cut of this test measured.
        (ws / "README.md").write_text("committed on the batch branch\n")
        _git(ws, "add", "-A")
        _git(ws, "commit", "-qm", "batch work")
        _git(ws, "checkout", "-q", "-b", "elsewhere", "HEAD~1")
        (ws / "README.md").write_text("uncommitted and conflicting\n")

        r = _bw_run(root, "1")
        assert r.returncode != 0, r.stdout + r.stderr
        assert "could not be checked out" in r.stderr, r.stderr
        assert _branch_of(ws) == "elsewhere", "the worktree was moved anyway"
        assert (ws / "README.md").read_text() == "uncommitted and conflicting\n", (
            "the refusal discarded the uncommitted work it exists to protect")
        assert on_batch != "elsewhere"


# ── wiring guards ─────────────────────────────────────────────────────────

class TestWiring:
    """**Three string-slicing guards stood here and the round killed two of
    them.** They asserted that a name appeared (or did not appear) in a sliced
    region of the script, and they failed in both directions at once: a trailing
    comment satisfied them (the branch probe replaced by
    `EXISTING_BRANCH="$BRANCH_NAME"   # branch --show-current` passed), while
    ordinary legal edits reddened them (`checkout "${BRANCH_NAME}"` braced, one
    extra space in `branch  --show-current`, `checkout` modernised to `switch`,
    and — for the absence guard — a comment merely *mentioning*
    `path_is_worktree_of`, which is the most natural way to record why it is not
    used).

    One of them carried a docstring claiming it had closed the same-line-comment
    class Phase 264's round found. It stripped only whole-line comments.

    Every mutation those guards were meant to catch is caught by the behavioural
    tests above, which drive the real script — so the proxies were not weaker
    coverage, they were zero coverage plus a brittleness tax. They are replaced
    here by the two properties they were standing in for, both asserted against
    behaviour, and by a non-vacuous collection control."""

    def test_the_helpers_are_defined_in_the_shared_lib_and_reachable(self):
        """Not a spelling check: it CALLS each one. A definition that a caller
        cannot reach — renamed, moved below its use, lost to a merge — is what
        this is for, and a name-in-file grep would not see it. `remote_identity`
        is exercised throughout this module; the other two are driven here."""
        for fn in ("remote_identity", "remote_path_identity",
                   "path_is_worktree_root", "origin_identity"):
            r = _lib_call(fn, "/nonexistent-p266")
            assert r.returncode != 9, f"{fn}: the lib failed to source"
            assert "command not found" not in r.stderr, f"{fn} is not defined"

    def test_a_worktree_of_this_repo_is_refused_at_the_clone_path(self, tmp_path):
        """The property the deleted absence-guard was proxying, stated as
        behaviour instead. A linked worktree shares the primary's config, so it
        passes the ORIGIN test — origin identity alone cannot tell a clone from
        one of our own trees, and `--release` then advises `rm -rf` on a tree git
        still has registered. Reachable by the documented route: claim
        `--worktree`, lose the lock, re-claim `--clone`."""
        root = _seeded(tmp_path / "a")
        _git(root, "branch", "feat/a")
        _git(root, "push", "-q", "-u", "origin", "feat/a")
        ws = _workspace_of(root)
        subprocess.run(["git", "worktree", "add", "-q", str(ws), "feat/a"],
                       cwd=str(root), check=True, capture_output=True)

        r = _run(root, "--lock", "--clone", "T-0001", "feat/a")
        assert r.returncode != 0, r.stdout + r.stderr
        assert "WORKTREE of this repository" in r.stderr, r.stderr
        assert _locks(root) == []

    def test_a_legitimate_clone_is_still_accepted(self, tmp_path):
        """The other half of that proxy, and the half that matters more: if the
        clone arm ever DID adopt `path_is_worktree_of` as its identity test, a
        clone — a separate repository by construction — would fail it, and every
        legitimate `--clone` resume would refuse. This is the test that notices."""
        root = _seeded(tmp_path / "a")
        _git(root, "branch", "feat/a")
        _git(root, "push", "-q", "-u", "origin", "feat/a")
        clone = _workspace_of(root)
        subprocess.run(["git", "clone", "-q", str(tmp_path / "a" / "w-origin.git"),
                        str(clone)], check=True, capture_output=True)
        _git(clone, "checkout", "-q", "feat/a")

        r = _run(root, "--lock", "--clone", "T-0001", "feat/a")
        assert r.returncode == 0, r.stdout + r.stderr
        assert _locks(root) == ["T-0001.lock"]

    def test_this_module_is_collected_in_full(self):
        """A canary that can chirp. The first cut of this was `assert True`,
        which cannot fail — if the module stopped being collected it would not
        run, and nothing counted its tests. This asserts a floor, so silently
        losing a class to an indentation slip or a bad merge reddens."""
        import inspect
        import sys as _sys
        mod = _sys.modules[__name__]
        n = sum(1 for _, obj in inspect.getmembers(mod, inspect.isclass)
                for _, m in inspect.getmembers(obj, inspect.isfunction)
                if m.__name__.startswith("test_"))
        n += sum(1 for name, _ in inspect.getmembers(mod, inspect.isfunction)
                 if name.startswith("test_"))
        assert n >= 36, f"only {n} tests found in this module — did a class vanish?"
