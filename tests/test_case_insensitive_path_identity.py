"""Path identity survives a case-divergent CWD spelling (Phase 198, `Q-187`).

Five shipped guards compared two absolute paths as STRINGS after `pwd -P`.
`pwd -P` resolves symlinks; it does not normalise case. The three paths involved
reach the shell from three different places — `git rev-parse --show-toplevel`
(the ON-DISK spelling), a `cd` into a path the caller supplied (the ENTERED
spelling), and a workspace path recorded in a lock file — so on a
case-insensitive filesystem two of them can name the same directory and compare
unequal.

That is not exotic: it is every default macOS install, where `~/projects/repo`
and the on-disk `~/Projects/repo` are the same directory.

Each guard failed in its own direction:

* `close_batch.sh` `close_landed_on_main` — the batch-lock sweep is gated on it,
  so the locks silently survived, and the remedy the script itself prints
  ("released by the next close run from main") was unreachable.
* `batch_work.sh --release` main-checkout guard — a HARD `exit 1` refusing a
  legitimate release from the real main checkout.
* `batch_work.sh` / `claim_task.sh` "never remove the main worktree" — fails
  OPEN (git refuses too, but a guard whose job is not reaching that error
  should not lean on it).
* `claim_task.sh` "you are inside the worktree being released" — fails OPEN, and
  the caller then removes the directory the operator is standing in.

**These tests are skipped on a case-sensitive filesystem, which is Linux, which
is where the required `pytest` check runs.** So they are skipped on CI by
construction and only ever execute on a developer's macOS checkout. That is
stated rather than discovered: the alternative is no regression coverage at all
for a defect that is only reachable on the filesystem the maintainer uses.
`tests/test_batch_claim_kinds.py:317` already exercises the same code path and
passes, because `tmp_path` always yields the on-disk spelling.
"""
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"


def _fs_is_case_insensitive(tmp_path: Path) -> bool:
    probe = tmp_path / "CaseProbe"
    probe.mkdir()
    return (tmp_path / "caseprobe").is_dir()


@pytest.fixture
def case_insensitive(tmp_path):
    if not _fs_is_case_insensitive(tmp_path):
        pytest.skip(
            "filesystem is case-sensitive — this defect is unreachable here. "
            "That includes CI (Linux), so this guard is skipped there by design."
        )


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root: Path, tasks: str | None = None):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    if tasks is not None:
        (root / "review_tasks.md").write_text(tasks)
    (root / "README.md").write_text("# seed\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _swapcase_leaf(p: Path) -> Path:
    """The same directory, spelled with its last component's case flipped."""
    return p.parent / p.name.swapcase()


def _run_from(cwd: Path, *argv: str, env=None):
    """Run a command with the shell having `cd`-ed to `cwd` AS SPELLED.

    This is load-bearing and the first version of this file got it wrong, which
    made every test here pass against the unfixed scripts. `subprocess(cwd=...)`
    uses `chdir(2)`, and a bash started that way initialises `$PWD` from
    `getcwd()` — which returns the CANONICAL on-disk spelling. The divergence
    this file is about only exists when a shell actually `cd`s to a spelling the
    user typed, because bash's `pwd -P` resolves symlinks from `$PWD` without
    re-canonicalising case:

        git rev-parse --show-toplevel  ->  .../Holder/repo   (on disk)
        pwd -P                          ->  .../hOLDER/repo   (as entered)

    So the entry has to go through the shell, not through the spawn.
    """
    quoted = " ".join(f"'{a}'" for a in argv)
    return subprocess.run(
        ["bash", "-c", f"cd '{cwd}' && exec {quoted}"],
        capture_output=True, text=True, env=env,
    )


# ── The primitive, isolated from any script ────────────────────────────

def test_a_string_compare_of_two_spellings_of_one_directory_disagrees(
    case_insensitive, tmp_path
):
    """The premise, measured rather than asserted — if this ever stops holding,
    every test below is passing for the wrong reason."""
    real = tmp_path / "Projects"
    real.mkdir()
    other = _swapcase_leaf(real)

    script = textwrap.dedent(f"""
        a="$(cd '{real}' && pwd -P)"
        b="$(cd '{other}' && pwd -P)"
        [[ "$a" == "$b" ]] && echo STRING_EQ   || echo STRING_NE
        [[ "$a" -ef "$b" ]] && echo INODE_EQ   || echo INODE_NE
    """)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert "STRING_NE" in r.stdout, r.stdout
    assert "INODE_EQ" in r.stdout, r.stdout


# ── close_batch.sh: the lock sweep that never ran ─────────────────────

TASKS = """\
# Review Tasks

### Batch 1 — First `Pending`

- [ ] **TASK-1**: a task
  `src/a.py:1` `[verified]` — description
"""


def test_close_batch_sweeps_batch_locks_via_a_case_divergent_cwd(
    case_insensitive, tmp_path
):
    holder = tmp_path / "Holder"
    holder.mkdir()
    repo = _repo(holder / "repo", tasks=TASKS)

    locks = repo / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    lock = locks / "BATCH-1.lock"
    lock.write_text("batch: 1\n")

    # Enter through the case-divergent spelling of an ancestor directory. The
    # repo root `git rev-parse` reports is unaffected; the derived main root is.
    divergent = _swapcase_leaf(holder) / "repo"
    assert divergent.is_dir(), divergent

    r = _run_from(divergent, "bash", str(SCRIPTS / "close_batch.sh"), "1")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert not lock.exists(), (
        "the batch lock survived a close run from the main checkout, reached "
        f"through a case-divergent spelling.\nstdout:\n{r.stdout}"
    )
    assert "Batch locks (already finished)" in r.stdout or "Removed" in r.stdout, r.stdout


# ── batch_work.sh --release: the hard refusal ─────────────────────────

def test_batch_work_release_is_not_refused_from_a_case_divergent_cwd(
    case_insensitive, tmp_path
):
    holder = tmp_path / "Holder"
    holder.mkdir()
    repo = _repo(holder / "repo", tasks=TASKS)
    divergent = _swapcase_leaf(holder) / "repo"

    r = _run_from(divergent, "bash", str(SCRIPTS / "batch_work.sh"), "--release", "1")
    # It may legitimately fail for other reasons (no claim to release); what it
    # must NOT do is refuse on the grounds that this is not the main checkout.
    assert "--release must run from the main checkout" not in r.stderr, (
        f"the main-checkout guard rejected the real main checkout.\n{r.stderr}"
    )


# ── claim_task.sh: the containment helper ─────────────────────────────

def _cwd_is_inside(cwd: Path, target: Path):
    """Drive the shipped helper directly, without a full claim/release cycle."""
    script = textwrap.dedent(f"""
        source_file='{SCRIPTS / "claim_task.sh"}'
        # Pull the function out rather than sourcing the whole script, which
        # parses flags and exits.
        eval "$(awk '/^cwd_is_inside\\(\\) \\{{/,/^\\}}/' "$source_file")"
        cwd_is_inside '{target}' && echo INSIDE || echo OUTSIDE
    """)
    r = subprocess.run(
        ["bash", "-c", f"cd '{cwd}' && " + script],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    return "INSIDE" in r.stdout


def test_cwd_is_inside_sees_through_a_case_divergent_spelling(
    case_insensitive, tmp_path
):
    ws = tmp_path / "Worktree"
    (ws / "sub" / "deeper").mkdir(parents=True)
    divergent = _swapcase_leaf(ws)

    # Standing in the worktree, spelled the other way.
    assert _cwd_is_inside(divergent, ws)
    # Standing in a subdirectory of it, spelled the other way.
    assert _cwd_is_inside(divergent / "sub" / "deeper", ws)


def test_cwd_is_inside_is_still_false_for_an_unrelated_directory(tmp_path):
    """The negative control — an over-broad containment test would refuse every
    release, which is the opposite failure and just as bad. Runs everywhere."""
    ws = tmp_path / "worktree"
    ws.mkdir()
    other = tmp_path / "elsewhere"
    other.mkdir()
    assert not _cwd_is_inside(other, ws)


def test_cwd_is_inside_is_true_for_the_plain_same_path(tmp_path):
    ws = tmp_path / "worktree"
    (ws / "sub").mkdir(parents=True)
    assert _cwd_is_inside(ws, ws)
    assert _cwd_is_inside(ws / "sub", ws)


def test_cwd_is_inside_rejects_an_empty_or_missing_target(tmp_path):
    ws = tmp_path / "worktree"
    ws.mkdir()
    assert not _cwd_is_inside(ws, tmp_path / "does-not-exist")


def test_cwd_is_inside_terminates_at_the_filesystem_root(tmp_path):
    """The walk-up loop is the new mechanism, so its termination is asserted
    rather than assumed: from `/` there is nowhere further up, and `dirname /`
    is `/` — a naive loop spins there forever."""
    assert not _cwd_is_inside(Path(os.sep), tmp_path / "worktree-that-exists-not")


# ── claim_task.sh --release: the guard that removes your CWD ──────────

def test_release_refuses_from_inside_the_worktree_spelled_differently(
    case_insensitive, tmp_path
):
    """The most expensive of the five failures, driven end to end.

    `--release` refuses when the operator is standing inside the worktree it is
    about to remove. With the guard doing a string compare, entering that
    worktree through a case-divergent spelling made the check miss, and the
    release then removed the directory the shell was sitting in.
    """
    repo = _repo(tmp_path / "repo")
    env = dict(os.environ, WORKTREE_PREFIX="wt")

    r0 = subprocess.run(
        ["bash", str(SCRIPTS / "claim_task.sh"), "--lock", "FEAT-X", "feat/x"],
        cwd=str(repo), capture_output=True, text=True, env=env,
    )
    assert r0.returncode == 0, (r0.stdout, r0.stderr)

    wt = tmp_path / "wt-feat-x"
    assert wt.is_dir(), sorted(p.name for p in tmp_path.iterdir())

    divergent = _swapcase_leaf(wt)
    r = _run_from(
        divergent, "bash", str(SCRIPTS / "claim_task.sh"), "--release", "FEAT-X",
        env=env,
    )

    assert wt.is_dir(), (
        "the worktree the shell was standing in was removed — the containment "
        f"guard did not fire through a case-divergent spelling.\n{r.stdout}\n{r.stderr}"
    )
    assert "inside the worktree being released" in r.stderr, (r.stdout, r.stderr)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)


def test_release_still_works_from_the_main_checkout(tmp_path):
    """The negative control, and it runs everywhere. An over-broad containment
    test would refuse every legitimate release — the opposite failure, and the
    one that would get the guard deleted rather than fixed."""
    repo = _repo(tmp_path / "repo")
    env = dict(os.environ, WORKTREE_PREFIX="wt")

    r0 = subprocess.run(
        ["bash", str(SCRIPTS / "claim_task.sh"), "--lock", "FEAT-X", "feat/x"],
        cwd=str(repo), capture_output=True, text=True, env=env,
    )
    assert r0.returncode == 0, (r0.stdout, r0.stderr)

    r = _run_from(repo, "bash", str(SCRIPTS / "claim_task.sh"), "--release",
                  "FEAT-X", env=env)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert not (tmp_path / "wt-feat-x").exists(), r.stdout
    assert not (repo / "sysop/runtime/locks" / "FEAT-X.lock").exists()
