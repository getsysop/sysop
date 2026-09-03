"""The default branch is resolved, never assumed (Phase 252, `Q-365`).

`main` was hard-coded at eleven behavioural sites across `close_batch.sh`,
`batch_work.sh` and `cleanup_worktrees.sh`, plus the Python resolver
`sitrep_survey._resolve_main_ref`, whose docstring promised a fallback its body
did not have. On a `master`-default repository every one of them was silently
wrong: `git merge-base --is-ancestor X main 2>/dev/null` on a repo with no
`main` exits non-zero exactly like "not merged" does, so a close skipped every
batch, a cleanup reclaimed nothing, a claim warned and left a lock, and the
survey read every claim as 0 commits ahead — which satisfied the park gate.

**Every fixture in the suite was built with `git -c init.defaultBranch=main`**,
so nothing here had ever met a `master` repo. These tests build them.

Two layers:

* the primitive — `_git_lib.sh::resolve_default_branch` and its Python twin
  `sitrep_survey.resolve_default_branch` — driven over the same fixture
  matrix and required to AGREE (behaviourally, over repos; no source-text pin);
* the three scripts, end to end, on a `master` repo, plus the loud-failure
  arms: an undecidable repo, and a script hand-copied without its library.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
LIB = SCRIPTS / "_git_lib.sh"

sys.path.insert(0, str(SCRIPTS))
import sitrep_survey as ss  # noqa: E402

# Every bash the resolver must run under. macOS ships 3.2 at /bin/bash, which
# is the floor `self_check.sh` states; `bash` on PATH is whatever the runner
# has. Both are exercised when both exist, so a bash-4-only construct cannot
# creep into the primitive with the suite green on a Linux CI.
_BASHES = sorted({p for p in ("/bin/bash", shutil.which("bash") or "") if p and Path(p).is_file()})


def test_the_bash_matrix_is_reachable():
    """Round finding (guards lens): with `_BASHES` empty every parametrized
    primitive test vanished as a skip, and with `/bin/bash` dropped bash 3.2 was
    never exercised on the one machine that has it."""
    assert _BASHES, "no bash found — the primitive tests below would silently skip"
    if sys.platform == "darwin":
        assert "/bin/bash" in _BASHES, "macOS ships bash 3.2 at /bin/bash; the floor must be exercised"


def _git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(cwd), check=check,
                          capture_output=True, text=True)


def _repo(root, default="main", *, commit=True):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", f"init.defaultBranch={default}", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    if commit:
        (root / "README.md").write_text("# seed\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", "seed")
    return root


def _set_origin_head(repo, branch):
    """What `git clone` (or `git remote set-head`) leaves behind, without a
    network: a remote-tracking ref for the branch and origin/HEAD pointing at it."""
    _git(repo, "update-ref", f"refs/remotes/origin/{branch}", branch)
    _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{branch}")


def _bash_resolve(bash, repo):
    r = subprocess.run(
        [bash, "-c", f'source "$1"; resolve_default_branch "$2"', "_", str(LIB), str(repo)],
        capture_output=True, text=True,
    )
    return r.returncode, r.stdout.strip(), r.stderr


# ─────────────────────────────────────────────────────────────────────────────
# The primitive — bash and Python agree on every shape
# ─────────────────────────────────────────────────────────────────────────────

def _shapes(tmp_path):
    """(label, repo, expected name or "" for a refusal)."""
    out = []
    r = _repo(tmp_path / "main_only"); out.append(("main only", r, "main"))
    r = _repo(tmp_path / "master_only", "master"); out.append(("master only", r, "master"))
    r = _repo(tmp_path / "both_tied"); _git(r, "branch", "master")
    out.append(("both, no origin/HEAD", r, ""))
    r = _repo(tmp_path / "both_head_master"); _git(r, "branch", "master"); _set_origin_head(r, "master")
    out.append(("both, origin/HEAD -> master", r, "master"))
    r = _repo(tmp_path / "both_head_main"); _git(r, "branch", "master"); _set_origin_head(r, "main")
    out.append(("both, origin/HEAD -> main", r, "main"))
    r = _repo(tmp_path / "develop"); _git(r, "branch", "develop"); _set_origin_head(r, "develop")
    out.append(("origin/HEAD -> develop, local develop", r, "develop"))
    r = _repo(tmp_path / "stale_head")
    _git(r, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/gone")  # dangling
    out.append(("stale origin/HEAD (dangling), local main", r, "main"))
    r = _repo(tmp_path / "live_head_not_local")
    _git(r, "update-ref", "refs/remotes/origin/gone", "HEAD")
    _git(r, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/gone")
    out.append(("origin/HEAD -> a branch the remote has and the checkout lacks", r, ""))
    r = _repo(tmp_path / "stale_head_no_fallback", "trunk")
    _git(r, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/gone")  # dangling
    out.append(("stale origin/HEAD, no main/master", r, ""))
    r = _repo(tmp_path / "neither", "trunk"); out.append(("neither, on trunk", r, ""))
    r = _repo(tmp_path / "unborn", "trunk", commit=False); out.append(("unborn, HEAD -> trunk", r, "trunk"))
    src = _repo(tmp_path / "clone_src", "master")
    subprocess.run(["git", "clone", "-q", str(src), str(tmp_path / "clone")],
                   check=True, capture_output=True)
    out.append(("real clone of a master repo", tmp_path / "clone", "master"))
    # Round findings (execute lens): a consumer whose only remote is not called
    # `origin`, and a `clone -b main` of a `develop`-default repo — the remote
    # declares a default the checkout never created.
    dsrc = _repo(tmp_path / "dev_src", "develop")
    subprocess.run(["git", "clone", "-q", "-o", "upstream", str(dsrc), str(tmp_path / "up")],
                   check=True, capture_output=True)
    out.append(("only remote is `upstream`", tmp_path / "up", "develop"))
    _git(dsrc, "branch", "main")
    subprocess.run(["git", "clone", "-q", "-b", "main", str(dsrc), str(tmp_path / "bmain")],
                   check=True, capture_output=True)
    out.append(("origin/HEAD -> develop (live), local main only", tmp_path / "bmain", ""))
    # Two remotes whose HEADs differ: `origin` wins, not the first listed.
    two = _repo(tmp_path / "two"); _git(two, "branch", "develop")
    _git(two, "remote", "add", "alpha", str(tmp_path / "nowhere-a"))
    _git(two, "remote", "add", "origin", str(tmp_path / "nowhere-o"))
    _git(two, "update-ref", "refs/remotes/alpha/develop", "develop")
    _git(two, "symbolic-ref", "refs/remotes/alpha/HEAD", "refs/remotes/alpha/develop")
    _set_origin_head(two, "main")
    out.append(("two remotes, origin/HEAD -> main, alpha/HEAD -> develop", two, "main"))
    # A TAG named `main` on a master repo must not read as the branch.
    tagged = _repo(tmp_path / "tagged", "master"); _git(tagged, "tag", "main")
    out.append(("master repo with a tag named main", tagged, "master"))
    return out


@pytest.mark.parametrize("bash", _BASHES)
def test_bash_and_python_resolve_every_shape_identically(tmp_path, bash):
    """The pin between the twins: same fixture, same answer, refusal for
    refusal. A source-text pin was rejected — the two are different
    languages, and what must hold is the answer."""
    disagreements = []
    for label, repo, expected in _shapes(tmp_path):
        rc, name, err = _bash_resolve(bash, repo)
        py = ss.resolve_default_branch(repo)
        if expected:
            # `err == ""`: a bash-4-only construct (`local -n`, `[[ -v`) errors
            # on stderr under 3.2 and leaves the exit status alone, so the text
            # sweep below is not the only 3.2 guard (round finding, guards lens).
            if not (rc == 0 and name == expected and py == expected and err == ""):
                disagreements.append((label, expected, (rc, name, err[:80]), py))
        else:
            if not (rc == 1 and name == "" and py == ""):
                disagreements.append((label, "<refuse>", (rc, name), py))
    assert not disagreements, "\n".join(
        f"{lbl}: expected {exp!r}; bash={b!r}; python={p!r}" for lbl, exp, b, p in disagreements
    )


def test_the_shape_matrix_is_not_vacuous(tmp_path):
    shapes = _shapes(tmp_path)
    assert len(shapes) >= 14
    assert {e for _, _, e in shapes} >= {"main", "master", "develop", "trunk", ""}


@pytest.mark.parametrize("bash", _BASHES)
def test_a_refusal_names_the_reason_and_the_git_command(tmp_path, bash):
    both = _repo(tmp_path / "both"); _git(both, "branch", "master")
    rc, name, err = _bash_resolve(bash, both)
    assert rc == 1 and name == ""
    assert "Both 'main' and 'master' exist" in err, err
    assert "git remote set-head origin <branch>" in err, err
    # The explicit form, not `--auto`: measured, `--auto` fails with "Cannot
    # determine remote HEAD" on a bare origin whose own HEAD names a branch
    # nobody pushed (round finding, execute lens).
    assert "--auto" not in err, err

    neither = _repo(tmp_path / "neither", "trunk")
    rc, name, err = _bash_resolve(bash, neither)
    assert rc == 1 and "Neither 'main' nor 'master'" in err, err

    stale = _repo(tmp_path / "stale", "trunk")
    _git(stale, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/gone")  # dangling
    rc, name, err = _bash_resolve(bash, stale)
    assert rc == 1 and "origin/HEAD names 'gone'" in err and "stale" in err, err

    dsrc = _repo(tmp_path / "dsrc", "develop"); _git(dsrc, "branch", "main")
    subprocess.run(["git", "clone", "-q", "-b", "main", str(dsrc), str(tmp_path / "bm")],
                   check=True, capture_output=True)
    rc, name, err = _bash_resolve(bash, tmp_path / "bm")
    assert rc == 1 and "origin/develop exists" in err, err
    assert "git branch develop origin/develop" in err, err


@pytest.mark.parametrize("bash", _BASHES)
def test_the_answer_is_the_same_from_a_linked_worktree(tmp_path, bash):
    """Refs are shared across worktrees; the primitive is anchored by operand,
    not by CWD, so a caller standing in a worktree gets the repo's answer."""
    repo = _repo(tmp_path / "repo", "master")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))
    rc, name, _ = _bash_resolve(bash, wt)
    assert (rc, name) == (0, "master")
    assert ss.resolve_default_branch(wt) == "master"


def test_require_default_branch_adds_the_caller_line_only_on_failure(tmp_path):
    ok = _repo(tmp_path / "ok", "master")
    r = subprocess.run(["bash", "-c", f'source "{LIB}"; require_default_branch "{ok}"'],
                       capture_output=True, text=True)
    assert (r.returncode, r.stdout.strip(), r.stderr) == (0, "master", "")
    bad = _repo(tmp_path / "bad"); _git(bad, "branch", "master")
    r = subprocess.run(["bash", "-c", f'source "{LIB}"; require_default_branch "{bad}"'],
                       capture_output=True, text=True)
    assert r.returncode == 1 and r.stdout == ""
    assert "cannot continue without it" in r.stderr, r.stderr


def test_the_library_is_bash_3_2_clean():
    """No bash-4-only construct in the primitive, by grep as well as by the
    /bin/bash runs above (which only exist on a macOS runner)."""
    import re
    code = "\n".join(
        ln for ln in LIB.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )
    for bad in ("declare -A", "mapfile", "readarray"):
        assert bad not in code, bad
    # ${var,,} / ${var^^} case-modification is bash 4.
    assert not re.search(r"\$\{[A-Za-z_][A-Za-z0-9_]*(,,|\^\^)", code)


# ─────────────────────────────────────────────────────────────────────────────
# The Python side: the ref, and the survey's report of an unresolvable branch
# ─────────────────────────────────────────────────────────────────────────────

def test_resolve_main_ref_prefers_the_remote_tracking_ref_of_the_resolved_branch(tmp_path):
    src = _repo(tmp_path / "src", "master")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(src), str(clone)], check=True, capture_output=True)
    assert ss._resolve_main_ref(clone) == "origin/master"
    local_only = _repo(tmp_path / "local", "master")
    assert ss._resolve_main_ref(local_only) == "master"
    tied = _repo(tmp_path / "tied"); _git(tied, "branch", "master")
    assert ss._resolve_main_ref(tied) == ""


def test_an_unpushed_claim_commit_on_the_default_branch_is_not_branch_work(tmp_path):
    """Round finding (execute lens), HIGH. `batch_work.sh` commits `docs: claim
    Batch N` on the LOCAL default branch and never pushes, then cuts the batch
    branch from it. Counted against `origin/<default>` alone, that commit was
    branch work — and every ordinary batch park read `parked, work in progress`
    with the claim commit as its work. Commits must be reachable from NEITHER
    the local default branch nor its remote-tracking ref."""
    repo = _repo(tmp_path / "repo", "master")
    _origin(repo, "master")
    (repo / "review_tasks.md").write_text("claim\n")
    _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "docs: claim Batch 1")  # unpushed
    _git(repo, "branch", "review/batch-1")
    assert ss._commits_ahead_of_main("review/batch-1", repo) == []
    # …and an upstream commit not yet pulled is not branch work either.
    other = tmp_path / "other"
    # `-b master`: the bare origin's own HEAD names the runner's default, which
    # nobody pushed, so a bare clone would check out nothing.
    subprocess.run(["git", "clone", "-q", "-b", "master", str(repo.parent / "repo-origin.git"), str(other)],
                   check=True, capture_output=True)
    _git(other, "config", "user.email", "o@o"); _git(other, "config", "user.name", "o")
    (other / "up.txt").write_text("u\n"); _git(other, "add", "-A"); _git(other, "commit", "-qm", "upstream")
    _git(other, "push", "-q", "origin", "master")
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "branch", "review/batch-2", "origin/master")
    assert ss._commits_ahead_of_main("review/batch-2", repo) == []
    # A real branch commit still counts.
    _git(repo, "checkout", "-q", "review/batch-2")
    (repo / "b.txt").write_text("b\n"); _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "batch work")
    _git(repo, "checkout", "-q", "master")
    assert [c.subject for c in ss._commits_ahead_of_main("review/batch-2", repo)] == ["batch work"]


def test_commits_ahead_are_counted_against_master_on_a_master_repo(tmp_path):
    """The `Q-362` interaction: before Phase 252 this returned [] on a master
    repo, so every claim read 0 commits ahead and satisfied the park gate."""
    repo = _repo(tmp_path / "repo", "master")
    _git(repo, "checkout", "-qb", "task/t-1")
    (repo / "w.txt").write_text("w\n")
    _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "work")
    _git(repo, "checkout", "-q", "master")
    commits = ss._commits_ahead_of_main("task/t-1", repo)
    assert len(commits) == 1 and commits[0].subject == "work"


def test_a_lock_with_an_empty_branch_value_is_claimed_no_branch(tmp_path, monkeypatch):
    """Round finding (execute lens): `str(raw.get("branch", ""))` turned an
    EMPTY `branch:` line into the string "None", so the lock classified as a
    claim on a branch named None and `claimed, no branch` was reachable only
    when the key was absent."""
    repo = _repo(tmp_path / "repo", "master")
    locks = repo / "sysop/runtime/locks"; locks.mkdir(parents=True)
    (locks / "FEAT-1.lock").write_text("task_id: FEAT-1\nbranch:\nstarted: 2026-08-30T12:00:00Z\n")
    monkeypatch.chdir(repo)
    s = ss.run_survey()
    assert s.tasks and s.tasks[0].state == "claimed, no branch", [t.state for t in s.tasks]
    assert s.tasks[0].branch == ""


def test_run_survey_reports_an_unresolvable_default_branch_first(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo"); _git(repo, "branch", "master")
    monkeypatch.chdir(repo)
    s = ss.run_survey()
    assert s.discrepancies, "no discrepancy for an undecidable default branch"
    d = s.discrepancies[0]
    assert d.kind == "default branch unresolved", d
    assert "git remote set-head origin <branch>" in d.suggestion
    assert "git branch <branch> origin/<branch>" in d.suggestion
    # …and it reaches the report a human reads and the ordered list.
    text = ss.render_text(s)
    assert "default branch unresolved" in text
    assert any("discrepanc" in line for line in ss._suggested_order(s))


def test_the_default_branch_discrepancy_leads_when_others_exist(tmp_path, monkeypatch):
    """Round finding (guards lens): `insert(0, …)` → `append` stayed green
    because the fixture had no other discrepancy."""
    repo = _repo(tmp_path / "repo"); _git(repo, "branch", "master")
    monkeypatch.chdir(repo)
    other = ss.Discrepancy(kind="other", detail="d", suggestion="s")
    monkeypatch.setattr(ss, "_find_discrepancies", lambda *a, **k: [other])
    s = ss.run_survey()
    assert [d.kind for d in s.discrepancies][:2] == ["default branch unresolved", "other"]


def test_run_survey_is_silent_about_the_default_branch_when_it_resolves(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo", "master")
    monkeypatch.chdir(repo)
    s = ss.run_survey()
    assert not any(d.kind == "default branch unresolved" for d in s.discrepancies)


# ─────────────────────────────────────────────────────────────────────────────
# The three scripts, end to end, on a `master` repository
# ─────────────────────────────────────────────────────────────────────────────

_TASKS = """\
# Review Tasks

### Batch 1 — First batch `Pending`

> **Branch:** `review/batch-1`

- [ ] **TASK-1**: task one
"""


def _vendor(repo):
    """The consumer layout the scripts expect: `review_index.py` for the index
    path, `_log.py` beside it. The scripts under test run from the SOURCE tree,
    so `_git_lib.sh` is beside them there."""
    sd = repo / "sysop" / "scripts"
    sd.mkdir(parents=True, exist_ok=True)
    for name in ("review_index.py", "_log.py"):
        shutil.copy(SCRIPTS / name, sd / name)
    _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "vendor")


def _origin(repo, branch):
    """A reachable origin carrying `branch` — the claim path pulls it. The push
    also sets nothing about origin/HEAD (a push does not), so the resolver's
    step 2 (exactly one of main/master) is what these fixtures exercise."""
    bare = repo.parent / f"{repo.name}-origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True, capture_output=True)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", branch)


def _run(script, cwd, *args):
    # `_BASHES[0]` sorts `/bin/bash` (3.2 on macOS) ahead of a Homebrew bash, so
    # the end-to-end runs exercise the floor where it exists (round finding:
    # every script run here used PATH's bash 5).
    return subprocess.run([_BASHES[0], str(SCRIPTS / script), *args], cwd=str(cwd),
                          capture_output=True, text=True)


class TestCloseBatchOnMaster:
    def test_a_batch_merged_into_master_closes_under_direct_policy(self, tmp_path):
        """The filed reproduction: a `master` repo, `## Merge policy` `direct`
        (absent, which reads as direct), a batch correctly merged. It was
        refused as "NOT merged into the merge target or main"."""
        repo = _repo(tmp_path / "repo", "master")
        (repo / "review_tasks.md").write_text(_TASKS)
        _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "tasks")
        _vendor(repo)
        _git(repo, "checkout", "-qb", "review/batch-1")
        (repo / "w.txt").write_text("w\n"); _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "batch work")
        _git(repo, "checkout", "-q", "master")
        _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "review/batch-1")

        r = _run("close_batch.sh", repo, "1")

        assert r.returncode == 0, r.stdout + r.stderr
        assert "merge target: 'master' (§ Merge policy: direct)" in r.stdout, r.stdout
        assert "verified merged" in r.stdout, r.stdout
        assert "`Merged`" in (repo / "review_tasks.md").read_text()
        assert "main" not in r.stdout.replace("main checkout", ""), r.stdout

    def test_an_unmerged_batch_is_refused_naming_master(self, tmp_path):
        repo = _repo(tmp_path / "repo", "master")
        (repo / "review_tasks.md").write_text(_TASKS)
        _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "tasks")
        _vendor(repo)
        _git(repo, "checkout", "-qb", "review/batch-1")
        (repo / "w.txt").write_text("w\n"); _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "batch work")
        _git(repo, "checkout", "-q", "master")

        r = _run("close_batch.sh", repo, "1")

        assert "is NOT merged into the merge target or master" in r.stdout, r.stdout
        assert "or main." not in r.stdout
        assert "`Pending`" in (repo / "review_tasks.md").read_text()

    def test_under_pr_policy_a_batch_merged_into_master_is_verified_by_the_default_arm(self, tmp_path):
        """Round finding (guards lens), HIGH: with the default arm reverted to a
        literal `main` (behind a trailing `# main checkout` comment that the sweep
        guard exempted), every `pr` fixture stayed green because every `pr`
        fixture was a `main` repo. Under `pr` with no `--merge-target` the
        default-branch arm is the WHOLE verification."""
        repo = _repo(tmp_path / "repo", "master")
        (repo / "review_tasks.md").write_text(_TASKS)
        (repo / "CLAUDE.md").write_text("# f\n\n## Merge policy\n\npr\n")
        _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "tasks")
        _vendor(repo)
        _git(repo, "checkout", "-qb", "review/batch-1")
        (repo / "w.txt").write_text("w\n"); _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "batch work")
        _git(repo, "checkout", "-q", "master")
        _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "review/batch-1")

        r = _run("close_batch.sh", repo, "1")

        assert r.returncode == 0, r.stdout + r.stderr
        assert "verifying against 'master' only" in r.stdout, r.stdout
        assert "verified merged" in r.stdout, r.stdout
        assert "`Merged`" in (repo / "review_tasks.md").read_text()

    def test_an_undecidable_repo_refuses_without_a_merge_target_and_proceeds_with_one(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        (repo / "review_tasks.md").write_text(_TASKS)
        _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "tasks")
        _vendor(repo)
        _git(repo, "branch", "master")  # both exist, no origin/HEAD → undecidable
        _git(repo, "checkout", "-qb", "review/batch-1")
        (repo / "w.txt").write_text("w\n"); _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "batch work")
        _git(repo, "checkout", "-q", "main")
        _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "review/batch-1")

        r = _run("close_batch.sh", repo, "1")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "Cannot resolve this repository's default branch" in r.stderr, r.stderr
        assert "--merge-target" in r.stderr
        assert "`Pending`" in (repo / "review_tasks.md").read_text(), "refused but wrote"

        r = _run("close_batch.sh", repo, "--merge-target", "main", "1")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "verified merged" in r.stdout
        assert "`Merged`" in (repo / "review_tasks.md").read_text()
        # The probe at the top is QUIET on this path; the ONE diagnostic on
        # stderr is the lock-kept arm's, printed on purpose because the close
        # landed on `main` and the sweep could not tell whether that is the
        # default branch (round finding: with the probe's `2>/dev/null` dropped
        # it printed twice).
        assert r.stderr.count("Cannot resolve this repository's default branch") == 1, r.stderr
        assert "could not be resolved" in r.stdout, r.stdout
        assert "Declare the default branch to git" in r.stdout, r.stdout


class TestBatchWorkOnMaster:
    def test_a_claim_on_a_master_repo_flips_the_status_and_branches_from_master(self, tmp_path):
        """Before: `⚠️ Not on main (on 'master'). Skipping batch claim.` — with
        the worktree and lock still created and the status never flipped, and
        then `git branch <x> main` failing hard."""
        repo = _repo(tmp_path / "repo", "master")
        (repo / "review_tasks.md").write_text(_TASKS)
        _vendor(repo)
        _origin(repo, "master")

        r = _run("batch_work.sh", repo, "1")

        assert r.returncode == 0, r.stdout + r.stderr
        assert "Not on" not in r.stderr, r.stderr
        assert "Claimed Batch 1 on master" in r.stdout, r.stdout
        assert "from master" in r.stdout, r.stdout
        assert "`In Progress`" in (repo / "review_tasks.md").read_text()
        assert (repo / "sysop/runtime/locks/BATCH-1.lock").is_file()
        base = _git(repo, "merge-base", "review/batch-1", "master").stdout.strip()
        assert base == _git(repo, "rev-parse", "master").stdout.strip()
        lock = (repo / "sysop/runtime/locks/BATCH-1.lock").read_text()
        assert "git diff --name-only master...HEAD" in lock, lock

    def test_release_on_a_master_repo_reverts(self, tmp_path):
        repo = _repo(tmp_path / "repo", "master")
        (repo / "review_tasks.md").write_text(_TASKS)
        _vendor(repo)
        _origin(repo, "master")
        assert _run("batch_work.sh", repo, "1").returncode == 0
        r = _run("batch_work.sh", repo, "--release", "--force", "1")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Reverted Batch 1 to Pending on master" in r.stdout, r.stdout
        assert not (repo / "sysop/runtime/locks/BATCH-1.lock").exists()

    def test_release_requires_the_default_branch_and_names_it_in_its_refusal(self, tmp_path):
        """Round finding (guards lens): with `--release`'s own `require` removed,
        an undecidable repo printed `❌ Not on  (on 'master')` with no diagnostic;
        and no fixture had ever read the refusal on a `master` repo."""
        repo = _repo(tmp_path / "repo", "master")
        (repo / "review_tasks.md").write_text(_TASKS)
        _vendor(repo)
        _origin(repo, "master")
        assert _run("batch_work.sh", repo, "1").returncode == 0
        _git(repo, "checkout", "-qb", "elsewhere")
        r = _run("batch_work.sh", repo, "--release", "--force", "1")
        assert r.returncode == 1
        assert "Not on master (on 'elsewhere')" in r.stderr, r.stderr
        _git(repo, "checkout", "-q", "master")
        _git(repo, "branch", "main")  # now undecidable
        r = _run("batch_work.sh", repo, "--release", "--force", "1")
        assert r.returncode == 1
        assert "Cannot resolve this repository's default branch" in r.stderr, r.stderr
        assert "Not on " not in r.stderr, r.stderr

    def test_a_claim_from_a_feature_branch_warns_naming_master(self, tmp_path):
        """S11i: the claim's on-branch warning on a `master` repo names master."""
        repo = _repo(tmp_path / "repo", "master")
        (repo / "review_tasks.md").write_text(_TASKS)
        _vendor(repo)
        _origin(repo, "master")
        _git(repo, "checkout", "-qb", "feature")
        r = _run("batch_work.sh", repo, "1")
        # Phase 254 (`Q-378`) turned this arm from a warning into a refusal;
        # what Phase 252 pinned here — that the message names the RESOLVED
        # branch and never `main` — is unchanged and is still the subject.
        assert r.returncode == 1, r.stderr
        assert "is not on master (on 'feature')" in r.stderr, r.stderr
        assert "on main" not in r.stderr, r.stderr

    def test_an_undecidable_repo_refuses_the_claim_and_leaves_no_lock(self, tmp_path):
        """The `require` runs BEFORE anything is written: the old arm warned
        and returned, leaving a lock against a batch whose status never moved."""
        repo = _repo(tmp_path / "repo")
        (repo / "review_tasks.md").write_text(_TASKS)
        _vendor(repo)
        _git(repo, "branch", "master")

        r = _run("batch_work.sh", repo, "1")

        assert r.returncode == 1, r.stdout + r.stderr
        assert "Cannot resolve this repository's default branch" in r.stderr, r.stderr
        assert "batch_work.sh cannot continue without it" in r.stderr, r.stderr
        assert "Not on" not in r.stderr, "the on-branch check ran before the require (round finding)"
        assert not (repo / "sysop/runtime/locks").exists(), "a lock was left behind"
        assert "`Pending`" in (repo / "review_tasks.md").read_text()
        assert not (tmp_path / "repo-batch-1").exists(), "a worktree was created"

    def test_list_does_not_need_the_default_branch(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        (repo / "review_tasks.md").write_text(_TASKS)
        _vendor(repo)
        _git(repo, "branch", "master")
        r = _run("batch_work.sh", repo, "--list")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "First batch" in r.stdout


class TestCleanupWorktreesOnMaster:
    def test_a_branch_merged_into_master_classifies_merged_and_is_cleaned(self, tmp_path):
        """Before: `--is-ancestor X main` errored, the error was swallowed, and
        every worktree classified ACTIVE — `--clean` reclaimed nothing, silently."""
        repo = _repo(tmp_path / "repo", "master")
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "feat", str(wt))
        (wt / "f.txt").write_text("f\n"); _git(wt, "add", "-A"); _git(wt, "commit", "-qm", "feat")
        _git(repo, "merge", "-q", "feat")

        listed = _run("cleanup_worktrees.sh", repo)
        assert listed.returncode == 0, listed.stdout + listed.stderr
        assert "MERGED" in listed.stdout, listed.stdout

        r = _run("cleanup_worktrees.sh", repo, "--clean")
        assert r.returncode == 0, r.stdout + r.stderr
        assert not wt.exists(), r.stdout
        assert "Deleted merged branch: feat" in r.stdout, r.stdout

    def test_the_delete_guard_protects_master_not_main(self, tmp_path):
        """The `--force` arm never `git branch -d`s the default branch. On a
        master repo that guard compared against `main` and so did not fire;
        `git branch -d master` on a checked-out branch is refused by git anyway,
        which is why this was fail-open-but-harmless — the guard is now right
        for its own reason rather than rescued by git's."""
        text = (SCRIPTS / "cleanup_worktrees.sh").read_text(encoding="utf-8")
        assert text.count('"$wt_branch" != "$DEFAULT_BRANCH"') == 2, "both removal modes guard the delete"
        assert '"$wt_branch" != "main"' not in text

    def test_an_undecidable_repo_refuses_every_mode(self, tmp_path):
        repo = _repo(tmp_path / "repo"); _git(repo, "branch", "master")
        for mode in ((), ("--clean",), ("--force",)):
            r = _run("cleanup_worktrees.sh", repo, *mode)
            assert r.returncode == 1, (mode, r.stdout, r.stderr)
            assert "Cannot resolve this repository's default branch" in r.stderr, (mode, r.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# The library is the one thing a hand-copied script can lose — and it says so
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("script", ["close_batch.sh", "batch_work.sh", "cleanup_worktrees.sh"])
def test_a_script_copied_without_its_library_fails_loud_and_names_the_remedy(tmp_path, script):
    repo = _repo(tmp_path / "repo", "master")
    (repo / "review_tasks.md").write_text(_TASKS)
    sd = repo / "sysop" / "scripts"
    sd.mkdir(parents=True)
    for name in (script, "review_index.py", "_log.py"):
        shutil.copy(SCRIPTS / name, sd / name)
    _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "partial install")

    r = subprocess.run(["bash", str(sd / script), "--list"] if script == "batch_work.sh"
                       else ["bash", str(sd / script)], cwd=str(repo),
                       capture_output=True, text=True)

    assert r.returncode == 1, r.stdout + r.stderr
    assert f"_git_lib.sh is missing beside {script}" in r.stderr, r.stderr
    assert "sysop-update.sh" in r.stderr, r.stderr
    assert "`Pending`" in (repo / "review_tasks.md").read_text()


def test_every_sourcing_script_sources_from_its_own_directory():
    """The sourcing line must resolve the library beside the SCRIPT, not the
    CWD — the installed layout is `sysop/scripts/`, and every prescribed
    invocation runs from the repo root."""
    for name in ("close_batch.sh", "batch_work.sh", "cleanup_worktrees.sh"):
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        assert 'source "$(dirname "${BASH_SOURCE[0]}")/_git_lib.sh" || {' in text, name
        import re
        assert not re.search(r"^resolve_main_root\(\)", LIB.read_text(), re.M), (
            "the lock-dir resolver stays duplicate-and-pin on purpose; the "
            "library carries only the default-branch primitive"
        )


def test_no_behavioural_main_literal_remains_in_the_swept_scripts():
    """The class, re-derived from the source rather than from the filing's
    list: a bare `main` token outside a comment, outside a message string, in
    the three scripts. Message strings that say "main checkout" (the primary
    worktree) are not the branch and are allowed by the exclusion below."""
    import re
    # The primary-checkout senses of the word, removed from the line BEFORE the
    # branch-name test — a whole-line exemption let a trailing `# main checkout`
    # comment launder a reverted literal (round finding, guards lens, HIGH), and
    # let every `echo` line off entirely.
    exempt = re.compile(r"main checkout|main worktree|main repo(?:sitory)?|non-main|main working tree")
    offenders = []
    for name in ("close_batch.sh", "batch_work.sh", "cleanup_worktrees.sh"):
        for i, line in enumerate((SCRIPTS / name).read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if s.startswith("#"):
                continue
            code = re.sub(r"\s+#.*$", "", s)          # trailing comment
            code = exempt.sub("", code)
            if re.search(r"\bmain\b", code):
                offenders.append(f"{name}:{i}: {s[:100]}")
    assert not offenders, "\n".join(offenders)
