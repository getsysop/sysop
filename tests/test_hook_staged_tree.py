"""Phase 222 (Q-020, mechanism 2) — pre-commit hooks must read the INDEX, executed.

The reproduced false green: a pre-commit check takes its file list from
`git diff --cached` and then reads the WORKING TREE — stage a violating blob, clean
the disk copy without re-staging, and the hook passes while the commit carries the
violation. These are consumer-copied templates armed by `install_hooks.sh`, so the
blast radius is every consumer.

Every test here RUNS the shipped hook text in a fixture repository and asserts on
what it did — both directions: the staged breakage the working tree hides must be
caught, and a dirty working tree over a clean stage must not false-fire.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS = REPO_ROOT / "core" / "companion" / "git-hooks"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def _clean_env(extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.setdefault("HOME", "/tmp")
    if extra:
        env.update(extra)
    return env


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True,
        check=True, env=_clean_env(),
    )


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "consumer"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    return r


# ---------------------------------------------------------------------------
# The python example's full-file checks (A4 shape)
# ---------------------------------------------------------------------------


def _run_example_hook(repo: Path) -> subprocess.CompletedProcess:
    hook = repo / "hook.sh"
    shutil.copy(HOOKS / "examples" / "pre-commit-python.example", hook)
    return subprocess.run(
        ["bash", str(hook)], cwd=str(repo), capture_output=True, text=True,
        env=_clean_env(),
    )


def test_a4_catches_the_staged_violation_the_worktree_hides(repo):
    """The reproduced false green, replayed against the shipped text: staged blob
    violates (vi.mock, no restoreAllMocks), disk copy was cleaned WITHOUT
    re-staging. Pre-222 the hook grepped the disk copy and stayed silent."""
    f = repo / "a.test.ts"
    f.write_text("vi.mock('m')\n", encoding="utf-8")
    _git(repo, "add", "a.test.ts")
    f.write_text("vi.mock('m')\nafterEach(vi.restoreAllMocks)\n", encoding="utf-8")

    r = _run_example_hook(repo)
    assert "restoreAllMocks" in r.stdout and "a.test.ts" in r.stdout, (
        f"the staged violation went unreported (the Q-020 false green):\n{r.stdout}\n{r.stderr}"
    )


def test_a4_does_not_false_fire_on_a_clean_stage_with_a_dirty_worktree(repo):
    """The symmetric direction: staged content is clean, the disk copy violates.
    A hook that reads the index must stay silent — the commit is fine."""
    f = repo / "a.test.ts"
    f.write_text("vi.mock('m')\nafterEach(vi.restoreAllMocks)\n", encoding="utf-8")
    _git(repo, "add", "a.test.ts")
    f.write_text("vi.mock('m')\n", encoding="utf-8")

    r = _run_example_hook(repo)
    assert "restoreAllMocks" not in r.stdout, (
        f"false fire on a clean staged blob:\n{r.stdout}"
    )


def test_a_worktree_deleted_staged_file_is_still_checked(repo):
    """The `[[ -f \"$FILE\" ]] || continue` guards skipped any staged file whose
    disk copy was deleted — an index-based check has no business consulting disk
    existence at all."""
    f = repo / "a.test.ts"
    f.write_text("vi.mock('m')\n", encoding="utf-8")
    _git(repo, "add", "a.test.ts")
    f.unlink()

    r = _run_example_hook(repo)
    assert "restoreAllMocks" in r.stdout and "a.test.ts" in r.stdout, (
        f"a staged blob with no disk copy was silently skipped:\n{r.stdout}\n{r.stderr}"
    )


# ---------------------------------------------------------------------------
# The tasks-validate fragment (validator + staged export)
# ---------------------------------------------------------------------------

_VALID_INDEX = """\
schema_version: 1

phases:
  - number: 1
    title: "Active phase"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-0001
    title: "A task"
    phase: 1
    status: open
    effort: Medium
    user_action: false
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-0001.md
"""

_BROKEN_INDEX = "schema_version: [unterminated\n"


def _prepare_validator_repo(repo: Path) -> None:
    scripts = repo / "sysop" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(
        REPO_ROOT / "core" / "companion" / "scripts" / "validate_tasks.py",
        scripts / "validate_tasks.py",
    )
    # The fragment prefers <main-repo-root>/.venv/bin/python3; hand it the test
    # interpreter (which carries PyYAML) under that exact path. A WRAPPER, not a
    # symlink: python resolves argv0 symlinks past pyvenv.cfg, so a symlinked
    # venv python loses its venv (and its PyYAML) — invoking sys.executable by
    # its real path keeps the test interpreter's environment.
    venv_bin = repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    wrapper = venv_bin / "python3"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    open_dir = repo / "tasks" / "open"
    open_dir.mkdir(parents=True)
    (open_dir / "FEAT-0001.md").write_text("# FEAT-0001\n\n## Context\nx.\n", encoding="utf-8")


def _run_fragment(repo: Path) -> subprocess.CompletedProcess:
    driver = repo / "driver.sh"
    driver.write_text(
        "STAGED=$(git diff --cached --name-only --diff-filter=ACM)\n"
        'block() { echo "BLOCKED: $1"; }\n'
        f"source '{HOOKS / 'examples' / 'pre-commit-tasks-validate.example'}'\n",
        encoding="utf-8",
    )
    return subprocess.run(
        ["bash", str(driver)], cwd=str(repo), capture_output=True, text=True,
        env=_clean_env(),
    )


def test_tasks_validate_rejects_the_staged_breakage_the_worktree_hides(repo):
    _prepare_validator_repo(repo)
    idx = repo / "tasks" / "index.yml"
    idx.write_text(_BROKEN_INDEX, encoding="utf-8")
    _git(repo, "add", "tasks/")
    idx.write_text(_VALID_INDEX, encoding="utf-8")  # fixed on disk, NOT re-staged

    r = _run_fragment(repo)
    assert "BLOCKED:" in r.stdout, (
        "the staged breakage passed because the validator read the (fixed) working "
        f"tree — the exact false green Q-020 filed:\n{r.stdout}\n{r.stderr}"
    )


def test_tasks_validate_passes_a_clean_stage_under_a_broken_worktree(repo):
    _prepare_validator_repo(repo)
    idx = repo / "tasks" / "index.yml"
    idx.write_text(_VALID_INDEX, encoding="utf-8")
    _git(repo, "add", "tasks/")
    idx.write_text(_BROKEN_INDEX, encoding="utf-8")  # broken on disk, clean in index

    r = _run_fragment(repo)
    assert "BLOCKED:" not in r.stdout, (
        f"false block on a clean staged tree:\n{r.stdout}\n{r.stderr}"
    )


# ---------------------------------------------------------------------------
# Text pins for the shapes that cannot execute (the skeleton's commented templates)
# ---------------------------------------------------------------------------


def test_skeleton_templates_grep_the_index():
    body = (HOOKS / "pre-commit").read_text(encoding="utf-8")
    assert "git grep --cached" in body, (
        "the skeleton's B1/A1 templates no longer model the index-based grep — "
        "consumers copy exactly this shape (Q-020)"
    )
    assert "xargs grep -ln" not in body, (
        "the working-tree xargs-grep template shape is back in the skeleton"
    )


def test_no_working_tree_existence_guard_survives_in_the_example():
    body = (HOOKS / "examples" / "pre-commit-python.example").read_text(encoding="utf-8")
    assert '[[ -f "$FILE" ]]' not in body, (
        "a working-tree existence guard is back — it silently skips staged blobs "
        "whose disk copy was deleted (Q-020)"
    )


def test_tasks_validate_export_carries_the_real_lock_state(repo):
    """Phase 222's round HIGH 1, closed: the validator's locks-dir resolution falls
    back BESIDE a /tmp export (its docstring names the tmpdir caller as the fallback
    case), so before the fix a staged in_progress task — the workflow's NORMAL state,
    e.g. the claim status-flip commit — read lock-missing and blocked every commit.
    The fragment now copies the main root's locks into the export."""
    _prepare_validator_repo(repo)
    idx = repo / "tasks" / "index.yml"
    idx.write_text(_VALID_INDEX.replace("status: open", "status: in_progress"), encoding="utf-8")
    locks = repo / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    (locks / "FEAT-0001.lock").write_text("workspace: x\nbranch: b\n", encoding="utf-8")
    _git(repo, "add", "tasks/")

    r = _run_fragment(repo)
    assert "BLOCKED:" not in r.stdout, (
        "a legitimately locked in_progress task was blocked — the export lost the "
        f"real lock state again (round HIGH 1):\n{r.stdout}\n{r.stderr}"
    )


def test_tasks_validate_still_blocks_a_truly_lockless_in_progress_task(repo):
    """The control for the fix above: copying the locks in must not blind the
    invariant it feeds — an in_progress task with NO lock anywhere still blocks."""
    _prepare_validator_repo(repo)
    idx = repo / "tasks" / "index.yml"
    idx.write_text(_VALID_INDEX.replace("status: open", "status: in_progress"), encoding="utf-8")
    _git(repo, "add", "tasks/")

    r = _run_fragment(repo)
    assert "BLOCKED:" in r.stdout, (
        f"a lockless in_progress task passed — invariant 9 went blind:\n{r.stdout}"
    )


def test_diff_based_checks_see_a_worktree_deleted_staged_file(repo):
    """Phase 222's round HIGH 2, closed: `git diff --cached -U0 <file>` without `--`
    fatals ('ambiguous argument') when the disk copy is gone, so 16 diff-based checks
    exited 0 over a staged violation — the same skip the `[[ -f ]]` removal claimed
    to have fixed, one layer down. Executed: a staged B2 violation (raw exception in
    a response) with the disk copy deleted must block."""
    f = repo / "api.py"
    f.write_text("def f(e):\n    return str(e)\n", encoding="utf-8")
    _git(repo, "add", "api.py")
    f.unlink()

    r = _run_example_hook(repo)
    assert r.returncode == 1 and "raw exception in response" in r.stdout, (
        f"staged B2 violation missed with the disk copy deleted:\n{r.stdout}\n{r.stderr}"
    )
    assert "ambiguous argument" not in r.stderr, (
        "the diff sites lost their `--` separator again (round HIGH 2)"
    )


# ---------------------------------------------------------------------------
# Round lens 3's surviving doors, closed in kind (HK-1, HK-2, HK-3, HK-4, HK-7)
# ---------------------------------------------------------------------------


def test_no_working_tree_existence_test_of_any_spelling(  # HK-1
):
    """The old pin knew one spelling (`[[ -f "$FILE" ]]`); the round re-introduced the
    skip with single brackets. Forbid the CLASS: any -f test of $FILE, any bracket."""
    body = (HOOKS / "examples" / "pre-commit-python.example").read_text(encoding="utf-8")
    assert '-f "$FILE"' not in body and "test -f" not in body, (
        "a working-tree existence test is back in some spelling (round HK-1)"
    )


def test_skeleton_template_hits_lines_grep_the_index():  # HK-2
    """The old pin was satisfied by the explanatory COMMENT plus the sibling template —
    the round dropped `--cached` from B1's grep line and stayed green. Pin the grep
    lines themselves: every `git grep` in the skeleton's templates reads the index."""
    body = (HOOKS / "pre-commit").read_text(encoding="utf-8")
    grep_lines = [l for l in body.splitlines() if "git grep" in l and "if git grep" in l]
    assert len(grep_lines) >= 2, (
        f"expected the B1+A1 template grep lines, found {len(grep_lines)}"
    )
    for l in grep_lines:
        assert "--cached" in l, f"a template grep line lost --cached (round HK-2): {l}"
        assert ":(literal)" in l, f"a template grep line lost its literal pathspec: {l}"


def test_tasks_validate_exports_the_whole_staged_tree_not_the_delta(repo):  # HK-3
    """`git ls-files -- tasks/` exports the full staged tasks/ tree. The round swapped
    it for the staged DELTA (`git diff --cached --name-only`) and the all-fresh fixture
    could not tell: validation needs files the current commit does not touch. Here a
    body file is committed history, and only index.yml is in the delta — a delta
    export loses the body and false-blocks; the tree export passes."""
    _prepare_validator_repo(repo)
    idx = repo / "tasks" / "index.yml"
    idx.write_text(_VALID_INDEX, encoding="utf-8")
    _git(repo, "add", "tasks/")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed")
    idx.write_text(_VALID_INDEX.replace('"A task"', '"A retitled task"'), encoding="utf-8")
    _git(repo, "add", "tasks/index.yml")  # body file NOT in this delta

    r = _run_fragment(repo)
    assert "BLOCKED:" not in r.stdout, (
        "an index-only staged edit was blocked — the export lost files outside the "
        f"delta (round HK-3):\n{r.stdout}\n{r.stderr}"
    )


def test_a12_reads_the_staged_blob_not_the_worktree(repo):  # HK-7
    """A12 (APP_ENV setdefault must precede sys.path.insert) reverted to working-tree
    greps in the round with nothing reddening. Staged blob violates the order, disk
    copy fixed without re-staging → the warning must still fire."""
    tdir = repo / "tests"
    tdir.mkdir()
    f = tdir / "x.py"
    f.write_text(
        "import sys\nsys.path.insert(0, 'x')\nimport os\n"
        "os.environ.setdefault('APP_ENV', 'test')\n",
        encoding="utf-8",
    )
    _git(repo, "add", "tests/x.py")
    f.write_text(
        "import os\nos.environ.setdefault('APP_ENV', 'test')\nimport sys\n"
        "sys.path.insert(0, 'x')\n",
        encoding="utf-8",
    )
    r = _run_example_hook(repo)
    assert "must come BEFORE" in r.stdout and "tests/x.py" in r.stdout, (
        f"A12 no longer reads the staged blob (round HK-7):\n{r.stdout}\n{r.stderr}"
    )


def test_model_pins_example_keeps_its_staged_export():  # HK-4
    """The model-pins staged-export rewrite had zero coverage — the round reverted it
    wholesale and nothing anywhere reddened. Pin the load-bearing pieces: the export,
    and every explicit argument that points the checker at it (the script's defaults
    read the working tree, which is the false green this hook was fixed for)."""
    body = (HOOKS / "examples" / "pre-commit-model-pins.example").read_text(
        encoding="utf-8"
    )
    for needle, why in [
        ("git checkout-index --prefix=\"$STAGED_CLAUDE_EXPORT/\"", "the staged export"),
        ('--root "$STAGED_CLAUDE_EXPORT/.claude/skills"', "the skills root argument"),
        ('--config "$STAGED_CLAUDE_EXPORT/.claude/served_models.yml"', "the config argument"),
        ("--local .claude/served_models.local.yml", "the real runtime local overlay"),
    ]:
        assert needle in body, (
            f"pre-commit-model-pins.example lost {why} — the working-tree read is "
            f"back (round HK-4): missing {needle!r}"
        )
