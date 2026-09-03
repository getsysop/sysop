"""Integration tests for core/companion/scripts/batch_work.sh (Phase 84).

`batch_work.sh` lists review batches and creates an isolated worktree for one.
They lock: the guard ordering (review_tasks.md before arg handling), the arg
guards (missing / non-integer / not-found / no-Branch-metadata), the `--list` /
`--list-all` parse + Complete-filtering, and the auto-build graceful skip when
off `main` (which must not abort — the worktree is still created).

**Phase 209 changed what these exercise.** They used to run with NO
`review_index.py` present, deliberately, so that the inline
`_parse_batches_fallback` bash regex was the code under test. That parser has
been retired (Q-036: no fence rule, so a fenced `### Batch <N>` was structural
to it alone; Q-226: its `while read` silently dropped a final line with no
trailing newline). `review_index.py` is now the only parser, so the fixture
installs it and these tests exercise the index path. The refusal that replaced
the fallback is covered by
`test_batch_status_gate.py::test_claim_refuses_outright_when_the_index_is_absent`
and `test_duplicate_batch_numbers.py::test_a_present_but_unusable_parser_fails_loudly`.

(An earlier version of this sentence cited `test_parser_preflight.py`, which has
never existed in this tree. Caught by the review round; nothing mechanical could
see it, because the citation guard's scope excludes `tests/` and its pattern
requires a `:<line>` suffix.)
"""
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
SCRIPT = SCRIPTS / "batch_work.sh"

# em-dash header + `> **Branch:**` metadata line.
TWO_BATCHES = """\
# Review Tasks

### Batch 1 — First batch `Pending`

> **Branch:** `feat/one`

- [ ] a

### Batch 2 — Second batch `Complete`

> **Branch:** `feat/two`

- [x] b
"""


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root, tasks: "str | None" = TWO_BATCHES):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")  # ignore a contributor's global signing
    if tasks is not None:
        (root / "review_tasks.md").write_text(tasks)
    # Install the vendor scripts the way a consumer has them, so `INDEX_SCRIPT`
    # resolves. Required since Phase 209 retired the bash fallback: without
    # review_index.py the script now refuses rather than parsing inline.
    sd = root / "sysop" / "scripts"
    sd.mkdir(parents=True, exist_ok=True)
    for name in ("review_index.py", "_log.py"):
        src = SCRIPTS / name
        if src.exists():
            shutil.copy(src, sd / name)
    (root / "README.md").write_text("# seed\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run(cwd, *args, env=None):
    import os
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True, env=e,
    )


class TestGuards:
    def test_not_a_git_repo_exits_1(self, tmp_path):
        r = _run(tmp_path, "1")
        assert r.returncode == 1
        assert "Not inside a git repository" in r.stderr

    def test_missing_review_tasks_exits_1(self, tmp_path):
        repo = _repo(tmp_path / "repo", tasks=None)
        r = _run(repo, "1")
        assert r.returncode == 1
        assert "review_tasks.md not found" in r.stderr

    def test_missing_batch_number_exits_1(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo)
        assert r.returncode == 1
        assert "Usage: batch_work.sh" in r.stderr

    def test_non_integer_batch_exits_1(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "abc")
        assert r.returncode == 1
        assert "must be a positive integer" in r.stderr

    def test_batch_not_found_exits_1(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "99")
        assert r.returncode == 1
        assert "Batch 99 not found" in r.stderr

    def test_no_branch_metadata_exits_1(self, tmp_path):
        tasks = "# Review Tasks\n\n### Batch 3 — No branch batch `Pending`\n\n- [ ] x\n"
        repo = _repo(tmp_path / "repo", tasks=tasks)
        r = _run(repo, "3")
        assert r.returncode == 1
        assert "has no Branch: metadata" in r.stderr


class TestList:
    def test_list_shows_pending_hides_complete(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "--list")
        assert r.returncode == 0, r.stderr
        assert "First batch" in r.stdout       # Pending → shown
        assert "Second batch" not in r.stdout  # Complete → hidden

    def test_list_all_shows_complete_too(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "--list-all")
        assert r.returncode == 0, r.stderr
        assert "First batch" in r.stdout
        assert "Second batch" in r.stdout
        assert "Complete" in r.stdout

    def test_list_empty_when_only_complete(self, tmp_path):
        tasks = (
            "# Review Tasks\n\n"
            "### Batch 9 — Done batch `Complete`\n\n"
            "> **Branch:** `feat/done`\n\n"
            "- [x] x\n"
        )
        repo = _repo(tmp_path / "repo", tasks=tasks)
        r = _run(repo, "--list")
        assert r.returncode == 0, r.stderr
        assert "No batches found" in r.stdout


class TestClaimOnMain:
    def test_claims_pending_batch_on_main_and_commits(self, tmp_path):
        # The auto-build happy path: on main + clean review_tasks.md + a
        # reachable origin, a Pending batch is marked In Progress and committed
        # before the worktree is created. The batch here is the file's LAST
        # section (no trailing `##`), so this also locks the L182 grep guard —
        # without it, claim_batch aborts (set -e) before claiming.
        tasks = (
            "# Review Tasks\n\n"
            "### Batch 1 — Only batch `Pending`\n\n"
            "> **Branch:** `feat/one`\n\n"
            "- [ ] a\n"
        )
        repo = _repo(tmp_path / "repo", tasks=tasks)
        bare = tmp_path / "origin.git"
        subprocess.run(["git", "init", "--bare", "-q", str(bare)],
                       check=True, capture_output=True)
        _git(repo, "remote", "add", "origin", str(bare))
        _git(repo, "push", "-q", "origin", "main")
        r = _run(repo, "1", env={"WORKTREE_PREFIX": "bw"})
        assert r.returncode == 0, r.stderr
        assert "Claimed Batch 1 on main" in r.stdout
        # The claim was committed on main…
        subj = subprocess.run(["git", "log", "-1", "--pretty=%s"], cwd=str(repo),
                              capture_output=True, text=True).stdout.strip()
        assert subj == "docs: claim Batch 1"
        # …the batch flipped Pending → In Progress…
        assert "`In Progress`" in (repo / "review_tasks.md").read_text()
        # …and the worktree was still created.
        assert (tmp_path / "bw-batch-1").is_dir()

    def test_dirty_review_tasks_skips_claim(self, tmp_path):
        # Same on-main + reachable-origin setup as the happy path, but with an
        # *unstaged* edit to review_tasks.md → the claim is skipped (no commit,
        # status stays Pending) while the worktree is still created. Unstaged
        # (not staged) so removing the leading `!` from the guard's first clause
        # is the clean mutation that reddens this.
        tasks = (
            "# Review Tasks\n\n"
            "### Batch 1 — Only batch `Pending`\n\n"
            "> **Branch:** `feat/one`\n\n"
            "- [ ] a\n"
        )
        repo = _repo(tmp_path / "repo", tasks=tasks)
        bare = tmp_path / "origin.git"
        subprocess.run(["git", "init", "--bare", "-q", str(bare)],
                       check=True, capture_output=True)
        _git(repo, "remote", "add", "origin", str(bare))
        _git(repo, "push", "-q", "origin", "main")
        # Dirty review_tasks.md, unstaged.
        with open(repo / "review_tasks.md", "a") as fh:
            fh.write("\n<!-- local uncommitted edit -->\n")

        r = _run(repo, "1", env={"WORKTREE_PREFIX": "bw"})
        # Phase 254 (`Q-378`): a refusal, not a skip. The claim used to return 0
        # here and build the worktree and lock anyway, leaving a `Pending` batch
        # holding a lock at exit 0.
        assert r.returncode == 1, r.stderr
        assert "review_tasks.md has uncommitted changes" in r.stderr
        assert "nothing was written" in r.stderr
        # No claim commit was made…
        subj = subprocess.run(["git", "log", "-1", "--pretty=%s"], cwd=str(repo),
                              capture_output=True, text=True).stdout.strip()
        assert subj != "docs: claim Batch 1"
        assert subj == "seed"
        # …the batch stayed Pending (never flipped to In Progress)…
        body = (repo / "review_tasks.md").read_text()
        assert "`Pending`" in body
        assert "`In Progress`" not in body
        # …and nothing was built around it: no worktree, no lock, no branch.
        assert not (tmp_path / "bw-batch-1").exists()
        assert not (repo / "sysop/runtime/locks/BATCH-1.lock").exists()
        assert "feat/one" not in subprocess.run(
            ["git", "branch", "--format=%(refname:short)"], cwd=str(repo),
            capture_output=True, text=True).stdout


class TestWorktreeCreation:
    def test_a_configured_origin_that_will_not_fast_forward_refuses(self, tmp_path):
        """Phase 254 (`Q-377`/`Q-378`) — the arm nothing covered.

        This phase's own author-side battery scored the failed-pull refusal a SURVIVOR:
        every other arm had a test and this one did not, because every fixture in the
        corpus configures no remote and therefore never reaches the pull at all. That is
        the same fixture blindness that let the defect ship — the suite's ordinary claim
        path ran *through* this arm without exercising it.

        No remote is deliberately not this case (see
        `test_a_local_only_repo_still_claims_normally`): a local-only repo has nothing to
        pull and claims. This is a CONFIGURED origin whose history has diverged, where a
        claim would commit the status flip onto a base the batch was never reviewed
        against.
        """
        repo = _repo(tmp_path / "repo")
        bare = tmp_path / "origin.git"
        subprocess.run(["git", "init", "--bare", "-q", str(bare)],
                       check=True, capture_output=True)
        _git(repo, "remote", "add", "origin", str(bare))
        _git(repo, "push", "-q", "origin", "main")
        # Diverge: the remote gains a commit this checkout can never fast-forward over,
        # and the local branch gains a different one.
        #
        # Nothing here may depend on the ambient `init.defaultBranch`. The first version
        # did, and it passed locally and failed in CI: `git init --bare` takes its HEAD
        # from that setting, so on a runner where it is `master` the bare repo's HEAD
        # names a ref that does not exist, `git clone` cannot check anything out
        # ("remote HEAD refers to nonexistent ref"), the clone lands on an unborn
        # `master`, and `git push origin main` fails with "src refspec main does not
        # match any". So: branch from the remote-tracking ref by name, and push with an
        # explicit `<src>:<dst>` refspec rather than relying on a local branch called
        # `main` existing in the clone.
        clone = tmp_path / "clone"
        subprocess.run(["git", "clone", "-q", str(bare), str(clone)],
                       check=True, capture_output=True)
        _git(clone, "config", "user.email", "test@test")
        _git(clone, "config", "user.name", "test")
        _git(clone, "checkout", "-q", "-B", "work", "origin/main")
        (clone / "theirs.txt").write_text("theirs\n")
        _git(clone, "add", "-A")
        _git(clone, "commit", "-qm", "theirs")
        _git(clone, "push", "-q", "origin", "work:main")
        (repo / "mine.txt").write_text("mine\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "mine")

        r = _run(repo, "1", env={"WORKTREE_PREFIX": "bw"})
        assert r.returncode == 1, r.stdout + r.stderr
        assert "nothing was written" in r.stderr, r.stderr
        assert "diverged" in r.stderr, (
            "the refusal must name which of the two reachable causes this is — the "
            "operator's next command differs between them"
        )
        assert not (tmp_path / "bw-batch-1").exists()
        assert not (repo / "sysop/runtime/locks/BATCH-1.lock").exists()
        assert "`Pending`" in (repo / "review_tasks.md").read_text()

    def test_a_remote_whose_name_merely_contains_origin_is_not_origin(self, tmp_path):
        """`grep -qx origin`, anchored — not `grep -q origin`. A repo whose only remote is
        `upstream-origin` has no `origin` to pull from, so it takes the local-only path and
        claims. With the unanchored grep it would take the pull path, fail, and refuse —
        re-introducing the over-reach that reddened 33 tests. The mutation survived this
        module until the round pointed at it."""
        repo = _repo(tmp_path / "repo")
        bare = tmp_path / "elsewhere.git"
        subprocess.run(["git", "init", "--bare", "-q", str(bare)],
                       check=True, capture_output=True)
        _git(repo, "remote", "add", "upstream-origin", str(bare))
        r = _run(repo, "1", env={"WORKTREE_PREFIX": "bw"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "No 'origin' remote" in r.stdout
        assert (repo / "sysop/runtime/locks/BATCH-1.lock").is_file()

    def test_claim_batch_returns_success_from_exactly_one_arm(self, tmp_path):
        """The contract in one sentence: `claim_batch` returns 0 only when it flipped the
        status, or when the batch was already past `Pending` and this is a re-attach.

        Pinned on the source because one of the arms it covers — the empty `batch_start`
        case — is unreachable by derivation (`review_index.py --range` prints a 1-indexed
        int), so no fixture can reach it and a behavioural test cannot exist. The round
        flipped that arm back to `return 0` and nothing noticed."""
        body = SCRIPTS.joinpath("batch_work.sh").read_text(encoding="utf-8")
        start = body.index("claim_batch() {")
        end = body.index("\n}\n", start)
        fn = body[start:end]
        returns_zero = [ln.strip() for ln in fn.splitlines() if ln.strip() == "return 0"]
        assert len(returns_zero) == 1, (
            f"claim_batch has {len(returns_zero)} `return 0` arms, not 1. Every non-claim "
            "outcome must refuse before anything is written (`Q-378`) — the top level's "
            "`|| exit 1` is what turns that into a clean exit, and a second success arm "
            "silently restores the half-claim."
        )
    def test_a_local_only_repo_still_claims_normally(self, tmp_path):
        """The control for the arm above, and the mistake this phase made first: refusing
        every failed pull reddened 33 tests, because a local-only repo has nothing to pull
        and is not a broken state. Without this test the fix's own over-reach reads as
        correct."""
        repo = _repo(tmp_path / "repo")            # no remote configured at all
        r = _run(repo, "1", env={"WORKTREE_PREFIX": "bw"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "No 'origin' remote" in r.stdout
        assert (repo / "sysop/runtime/locks/BATCH-1.lock").is_file()
        assert "`In Progress`" in (repo / "review_tasks.md").read_text()

    def test_off_default_branch_refuses_and_builds_nothing(self, tmp_path):
        """Phase 254 (`Q-378`) — this test used to assert the defect, and said
        so in its own comment: *"Auto-build skips gracefully (never aborts)"*.

        What it actually pinned was a claim that returned 0 off the default
        branch and then built a branch, a worktree and a lock around a batch
        the tracker still called `Pending`. There is no consistent claim to be
        made from here — the status flip has to commit on the default branch in
        the primary — so the graceful outcome is a refusal that writes nothing,
        which is what `/auto-fix` and `/auto-judge` already handle: *"if the
        script exits non-zero, report the error, skip this batch, and continue
        to the next one."*"""
        repo = _repo(tmp_path / "repo")
        _git(repo, "checkout", "-q", "-b", "other")  # not on the default branch
        r = _run(repo, "1", env={"WORKTREE_PREFIX": "bw"})
        assert r.returncode == 1, r.stderr
        assert "not on main" in r.stderr.lower()
        assert "nothing was written" in r.stderr
        assert "Created worktree" not in r.stdout
        assert not (tmp_path / "bw-batch-1").exists()
        assert not (repo / "sysop/runtime/locks/BATCH-1.lock").exists()
