"""Phase 418 (`Q-409` P5, Step 4b) — `review_index.py --list --merged`, the trigger source.

Step 4b's non-empty arm moved to `steps/4b-batches.md`, and the core loads it when this
command prints a row. Before the phase the runner intersected `--list`'s branch column with
the branches Step 4a merged by hand, so no printed value decided the arm (the split spec's
§ 17 row). `--merged` makes the intersection a printed value, on Wade's answers of 2026-10-23
(the runner types the branches Step 4a merged; the filter is a flag on the one reader).

Every claim here is executed against the real script in a scratch repository, because
the script resolves `REPO_ROOT` from its own file and the operands are checked against
real `refs/heads/` refs. The three states Step 4b keys on:

* exit 0 with rows: the arm is due;
* exit 0, no rows, and the `--merged` verdict line: the measured-empty set;
* any non-zero exit, with no rows on stdout: could-not-measure, so the arm can never be made
  due on a close that must stop.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "core/companion/scripts/review_index.py"
GIT_ENV = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
IDENT = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]

TWO = (
    "# Review Tasks\n\n## Round 1 — fixture\n\n"
    "### Batch 1 — one `Pending`\n\n> **Branch:** `review/batch-1`\n\n- [ ] **TASK-0001**: a\n\n"
    "### Batch 2 — two `Pending`\n\n> **Branch:** `review/batch-2`\n\n- [ ] **TASK-0002**: b\n"
)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *IDENT, "-C", str(root), *args], check=True,
                          capture_output=True, text=True, env=GIT_ENV)


def _repo(root: Path, tasks: str | None = TWO, branches=("review/batch-1",)) -> Path:
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True, env=GIT_ENV)
    scripts = root / "sysop" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(SCRIPT, scripts / SCRIPT.name)
    if tasks is not None:
        (root / "review_tasks.md").write_text(tasks, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "fixture")
    for b in branches:
        _git(root, "branch", b)
    return root


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(root / "sysop" / "scripts" / SCRIPT.name), *args],
                          cwd=str(root), capture_output=True, text=True, env=GIT_ENV)


def test_a_branch_is_matched_whole(tmp_path):
    """Its round, lens B (L01, L02): with only batches 1 and 2 a prefix or substring match
    passed every test."""
    tasks = TWO + "\n### Batch 10 — ten `Pending`\n\n> **Branch:** `review/batch-10`\n"
    root = _repo(tmp_path / "r")
    (root / "review_tasks.md").write_text(tasks, encoding="utf-8")
    r = _run(root, "--list", "--merged", "review/batch-1")
    assert r.returncode == 0, r.stderr
    assert r.stdout == "1\tone\tPending\treview/batch-1\t\t\n", r.stdout


def test_a_tracker_branch_differing_only_in_case_exits_8(tmp_path):
    """Its round 2, lens C: on a case-insensitive filesystem git can store `Review/x` under an
    existing `review/` directory, so the tracker and git disagree in case; exact matching would
    drop that batch silently, and a case-folded match (lens B's L03) would close the wrong one."""
    tasks = TWO + "\n### Batch 11 — eleven `Pending`\n\n> **Branch:** `Review/batch-1`\n"
    root = _repo(tmp_path / "r")
    (root / "review_tasks.md").write_text(tasks, encoding="utf-8")
    r = _run(root, "--list", "--merged", "review/batch-1")
    assert r.returncode == 8 and r.stdout == "", (r.returncode, r.stdout, r.stderr)
    assert "WARNING: review_tasks.md's Branch: 'Review/batch-1' differs from --merged " \
           "'review/batch-1' only in case" in r.stderr, r.stderr


def test_a_case_only_miss_names_gits_spelling(tmp_path):
    root = _repo(tmp_path / "r")
    r = _run(root, "--list", "--merged", "Review/Batch-1")
    assert r.returncode == 7, r.stderr
    assert "git stores it as 'review/batch-1'" in r.stderr, r.stderr


def test_git_failing_to_list_branches_is_exit_1_not_a_bad_operand(tmp_path):
    """Its round 2, lens C (F3): exit 7 says an operand is wrong, and here none is."""
    root = _repo(tmp_path / "r")
    shutil.rmtree(root / ".git")
    (root / ".git").write_text("gitdir: /nonexistent\n", encoding="utf-8")
    r = _run(root, "--list", "--merged")
    assert r.returncode == 1 and "git could not list the local branches" in r.stderr, r.stderr


def test_a_batch_that_landed_earlier_reruns_clean_and_the_arm_says_so(tmp_path):
    """Its round 2, lens C (F1): a stuck PR-reuse close re-runs Step 4b over a batch already
    `Merged` in HEAD; `close_batch.sh` skips it and commits nothing, so the landing gate halted
    with no recovery. The arm's carve-out keys on these strings, so run the script for them."""
    root = _repo(tmp_path / "r")
    scripts = Path(__file__).resolve().parents[1] / "core/companion/scripts"
    for f in scripts.iterdir():
        if f.is_file():
            shutil.copy2(f, root / "sysop" / "scripts" / f.name)
    (root / "CLAUDE.md").write_text("# P\n\n## Merge policy\n\ndirect\n", encoding="utf-8")
    (root / ".gitignore").write_text("sysop/runtime/\n.claude/\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "scripts")
    env = dict(GIT_ENV, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    run = lambda: subprocess.run(  # noqa: E731
        ["bash", "sysop/scripts/close_batch.sh", "--merge-target", "main", "1"],
        cwd=str(root), capture_output=True, text=True, env=env)
    first = run()
    assert "close-batch commit present: 1" in first.stdout, first.stdout + first.stderr
    again = run()
    out = again.stdout
    assert "1:already-merged" in out and "close-batch commit present: 0" in out, out
    assert "Could not compare this batch against HEAD" not in out and "Commit resumed for:" not in out
    arm = (Path(__file__).resolve().parents[1]
           / "core/skills/review-close/steps/4b-batches.md").read_text(encoding="utf-8")
    assert ("**A batch that landed on an earlier run is not a failed close.** When every batch you "
            "passed is reported `already-merged` with no `Could not compare this batch against HEAD` "
            "line under it, the summary reads `close-batch commit present: 0`, and the working tree "
            "is clean") in " ".join(arm.split())


def test_it_prints_only_the_rows_on_the_branches_given(tmp_path):
    root = _repo(tmp_path / "r", branches=("review/batch-1", "feat/x"))
    r = _run(root, "--list", "--merged", "review/batch-1", "feat/x")
    assert r.returncode == 0, r.stderr
    assert r.stdout == "1\tone\tPending\treview/batch-1\t\t\n", r.stdout
    assert ("review_index --list --merged: read review_tasks.md (15 lines); 2 batches in it; "
            "1 listed for the 2 branches given.") in r.stderr


def test_bare_list_is_unchanged(tmp_path):
    root = _repo(tmp_path / "r")
    r = _run(root, "--list")
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["1\tone\tPending\treview/batch-1\t\t",
                                     "2\ttwo\tPending\treview/batch-2\t\t"]
    assert "review_index --list: read review_tasks.md (15 lines); 2 batches listed." in r.stderr


def test_a_refs_heads_operand_is_the_same_branch(tmp_path):
    root = _repo(tmp_path / "r")
    r = _run(root, "--list", "--merged", "refs/heads/review/batch-1")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("1\t"), r.stdout


def test_no_matching_row_is_the_measured_empty_set(tmp_path):
    root = _repo(tmp_path / "r", branches=("feat/x",))
    r = _run(root, "--list", "--merged", "feat/x")
    assert r.returncode == 0 and r.stdout == "", (r.returncode, r.stdout)
    assert "0 listed for the 1 branch given." in r.stderr, r.stderr


@pytest.mark.parametrize("make", ["typo", "tag only", "remote-tracking only", "case variant",
                                  "revision suffix"])
def test_an_operand_that_is_not_a_local_branch_exits_7_with_no_rows(tmp_path, make):
    """A mistyped branch would match no row and read as the empty set, so it refuses. A tag or a
    remote-tracking ref of the name is not the branch (`Q-686`)."""
    root = _repo(tmp_path / "r")
    name = "review/batch-2"
    if make == "tag only":
        _git(root, "tag", name)
    elif make == "remote-tracking only":
        _git(root, "update-ref", f"refs/remotes/origin/{name}", "HEAD")
    elif make == "typo":
        name = "review/batch-l"
    elif make == "case variant":
        # Loose refs resolve case-insensitively on macOS's default filesystem, so `rev-parse`
        # accepted this one there (its round, lens A).
        name = "REVIEW/BATCH-1"
    elif make == "revision suffix":
        name = "review/batch-1^0"
    for argv in (("review/batch-1", name), (name, "review/batch-1")):
        r = _run(root, "--list", "--merged", *argv)
        assert r.returncode == 7, (argv, r.returncode, r.stderr)
        assert r.stdout == ""
        assert f"--merged '{name}' names no local branch" in r.stderr, r.stderr


def test_a_duplicate_number_exits_8_with_no_rows(tmp_path):
    """Bare `--list` warns at exit 0 and prints the survivor; under `--merged` a row beside a
    WARNING would make the arm due on a close that must stop."""
    dup = TWO + "\n### Batch 1 — again `Pending`\n\n> **Branch:** `review/batch-9`\n"
    root = _repo(tmp_path / "r", tasks=dup, branches=("review/batch-1", "review/batch-9"))
    r = _run(root, "--list", "--merged", "review/batch-9")
    assert r.returncode == 8, (r.returncode, r.stderr)
    assert r.stdout == ""
    assert "WARNING: review_tasks.md declares Batch 1 2 times" in r.stderr
    bare = _run(root, "--list")
    assert bare.returncode == 0 and "review/batch-9" in bare.stdout


def test_a_near_miss_header_over_an_empty_tracker_exits_8(tmp_path):
    near = "# Review Tasks\n\n### Batch 3 - near `Pending`\n\n> **Branch:** `review/batch-1`\n"
    root = _repo(tmp_path / "r", tasks=near)
    r = _run(root, "--list", "--merged", "review/batch-1")
    assert r.returncode == 8, (r.returncode, r.stderr)
    assert r.stdout == "" and "WARNING: review_tasks.md:3 declares a batch" in r.stderr


def test_a_near_miss_header_beside_read_batches_is_a_note_keyed_on_the_whole_list(tmp_path):
    """The level is the bare list's: batches were read, so a legacy header does not halt every
    close. Keyed on the filtered list instead, a close whose branch matches no row would turn
    the NOTE into a halting WARNING."""
    tasks = TWO + "\n### Batch 3 - near `Pending`\n"
    root = _repo(tmp_path / "r", tasks=tasks, branches=("feat/x",))
    r = _run(root, "--list", "--merged", "feat/x")
    assert r.returncode == 0, (r.returncode, r.stderr)
    assert r.stdout == ""
    assert "NOTE: review_tasks.md:" in r.stderr and "WARNING" not in r.stderr, r.stderr


def test_an_absent_tracker_is_the_empty_set_and_a_deleted_one_is_not(tmp_path):
    never = _repo(tmp_path / "never", tasks=None)
    r = _run(never, "--list", "--merged", "review/batch-1")
    assert r.returncode == 0 and r.stdout == "", (r.returncode, r.stderr)
    assert "review_tasks.md absent; 0 batches listed" in r.stderr
    gone = _repo(tmp_path / "gone")
    _git(gone, "rm", "-q", "review_tasks.md")
    _git(gone, "commit", "-qm", "rm")
    r = _run(gone, "--list", "--merged", "review/batch-1")
    assert r.returncode == 1 and r.stdout == "", (r.returncode, r.stderr)


def test_merged_without_list_is_a_usage_error(tmp_path):
    root = _repo(tmp_path / "r")
    r = _run(root, "--merged", "review/batch-1")
    assert r.returncode == 2 and "--merged filters --list and needs it" in r.stderr


def test_step_4bs_reader_is_the_bare_python3_merged_command():
    """The fenced command the core prescribes, at column 0 with the bare command word, so it
    binds `Bash(python3 sysop/scripts/review_index.py:*)` (Phase 241's class)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from skill_runner_text import text_of
    text = text_of(Path(__file__).resolve().parents[1] / "core/skills/review-close/SKILL.md")
    step = text[text.index("### 4b. Close Merged Batches"):text.index("### 4c. Consolidate")]
    assert "\npython3 sysop/scripts/review_index.py --list --merged <branch> <branch>\n" in step
    # The spliced text replaces the marker with the arm, so the stub ends where the arm begins.
    stub = step[step.index("**With a non-empty set**"):step.index("**First, record that this arm loaded**")]
    assert "`--merged` printed a row, or the `NOTE:` check above added a batch" in " ".join(stub.split())


def test_the_inventory_and_workflow_name_the_merged_reader():
    """The phase's battery (S17, W02, W03): the allow-rule inventory and both WORKFLOW.md sites
    could fall back to the bare `--list` unseen."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from skill_runner_text import text_of
    repo = Path(__file__).resolve().parents[1]
    core = text_of(repo / "core/skills/review-close/SKILL.md")
    at = core.index("- `Bash(python3 sysop/scripts/review_index.py:*)`")
    rule = " ".join(core[at:core.index("\n- ", at + 1)].split())
    assert "Step 4b's batch-set derivation (`--list --merged`)." in rule, rule
    wf = " ".join((repo / "core/companion/docs/WORKFLOW.md").read_text(encoding="utf-8").split())
    assert ("the review batches whose branches step 5 merged, read from `review_tasks.md` "
            "(via `review_index.py --list --merged <branch>...`, which prints the authoritative "
            "rows, status and branch, for the branches it is given)") in wf
    assert ("`--list --merged <branch>...` prints only the batches on those branches "
            "(`/review-close` Step 4b; exit 7 names an operand that is not a local branch, exit 8 a "
            "`WARNING:`)") in wf


def test_no_operand_is_the_measured_empty_set(tmp_path):
    """The docs-consolidation cycle and a close of landed branches merge nothing at Step 4a, and
    reach Step 4b; `nargs="+"` made the command unformable there and its exit 2 a halt (its
    round, lens A)."""
    root = _repo(tmp_path / "r")
    r = _run(root, "--list", "--merged")
    assert r.returncode == 0 and r.stdout == "", (r.returncode, r.stderr)
    assert "0 listed for the 0 branches given." in r.stderr, r.stderr


def test_a_tab_in_a_title_does_not_drop_the_batch(tmp_path):
    """The filter reads the parsed branch, not the rendered line's fourth column (its round)."""
    tasks = TWO.replace("### Batch 1 — one `Pending`", "### Batch 1 — o\tne `Pending`")
    root = _repo(tmp_path / "r", tasks=tasks)
    r = _run(root, "--list", "--merged", "review/batch-1")
    assert r.returncode == 0 and r.stdout.startswith("1\t"), (r.stdout, r.stderr)


def test_no_repository_is_named_as_such_not_as_a_bad_operand(tmp_path):
    scripts = tmp_path / "bare" / "sysop" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(SCRIPT, scripts / SCRIPT.name)
    r = subprocess.run([sys.executable, str(scripts / SCRIPT.name), "--list", "--merged", "x"],
                       cwd=str(tmp_path / "bare"), capture_output=True, text=True, env=GIT_ENV)
    assert r.returncode == 1 and "no repository root above this script" in r.stderr, r.stderr


def test_the_core_names_the_reuse_operand_and_the_empty_run():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from skill_runner_text import text_of
    text = " ".join(text_of(Path(__file__).resolve().parents[1]
                            / "core/skills/review-close/SKILL.md").split())
    assert ("Write every branch Step 4a merged as its own operand, and under the PR-reuse shape, "
            "which skips Step 4a, the one approved branch. With no branch merged, run it with no "
            "operand: it prints the measured empty.") in text


def test_the_help_states_both_refusals(tmp_path):
    """Its round, lens B (D01): the help could say a WARNING exits 0 unseen."""
    root = _repo(tmp_path / "r")
    r = _run(root, "--help")
    text = " ".join(r.stdout.split())
    assert "Exit 7 when one is not a local branch, spelled exactly;" in text, text
    assert "exit 8, printing no rows, on any WARNING" in text, text
