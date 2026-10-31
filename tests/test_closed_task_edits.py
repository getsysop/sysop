"""`Q-547`, Phase 445: a branch edit to a task body the merge target has since closed.

`/review-close` Step 4c closes a task by `git mv`-ing its body to `tasks/archive/`. A branch that
edited the open copy then replays with no conflict: git's rename detection carries the edit into
the closed copy, and every gate stays green. `pr_head_check.py`, which Step 4a item 1 runs before
it merges, prints a `CLOSED TASK EDITED:` line for each such body, and the step stops on it.

The first test is the premise, run against git itself: if git ever starts conflicting here, the
check is redundant, and this test says so before anyone reads the step.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from skill_runner_text import text_of

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "core/companion/scripts/pr_head_check.py"

_ENV = {k: v for k, v in os.environ.items()
        if not k.startswith("GIT_") or k in ("GIT_EXEC_PATH",)}
_ENV.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"})

BODY = "# {t}\n\nline a\nline b\nline c\nline d\n"
PLAN = "\n## Plan\nthe branch's plan\n"


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, env=_ENV, capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr}"
    return r.stdout


def check(repo, branch="feat", target="main"):
    r = subprocess.run(["python3", str(SCRIPT), branch, target], cwd=repo, env=_ENV,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def edited(out):
    return [ln for ln in out.splitlines() if ln.startswith("CLOSED TASK EDITED:")]


def seed(tmp_path, *names):
    repo = tmp_path / "repo"
    (repo / "tasks/open").mkdir(parents=True)
    (repo / "tasks/archive").mkdir()
    (repo / "tasks/index.yml").write_text("tasks: []\n")
    (repo / "tasks/notes.md").write_text("- a note\n")
    for t in names:
        (repo / f"tasks/open/{t}.md").write_text(BODY.format(t=t))
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    return repo


def append(repo, path, text):
    with open(repo / path, "a") as fh:
        fh.write(text)


def test_git_carries_the_edit_into_the_closed_copy_silently(tmp_path):
    repo = seed(tmp_path, "T-1")
    git(repo, "checkout", "-qb", "feat")
    append(repo, "tasks/open/T-1.md", PLAN)
    git(repo, "commit", "-qam", "plan")
    git(repo, "checkout", "-q", "main")
    git(repo, "mv", "tasks/open/T-1.md", "tasks/archive/T-1.md")
    git(repo, "commit", "-qm", "close T-1")
    git(repo, "checkout", "-q", "feat")
    git(repo, "rebase", "main")  # exit 0: no conflict for any gate to see
    assert "the branch's plan" in (repo / "tasks/archive/T-1.md").read_text()
    assert not (repo / "tasks/open/T-1.md").exists()


def test_a_closed_or_removed_body_the_branch_edited_is_named(tmp_path):
    repo = seed(tmp_path, "T-1", "T-2", "T-3", "T 4")
    git(repo, "checkout", "-qb", "feat")
    for t in ("T-1", "T-2", "T-3", "T 4"):
        append(repo, f"tasks/open/{t}.md", PLAN)
    append(repo, "tasks/notes.md", "- another\n")
    (repo / "tasks/open/T-5.md").write_text(BODY.format(t="T-5"))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "branch edits")
    git(repo, "checkout", "-q", "main")
    git(repo, "mv", "tasks/open/T-1.md", "tasks/archive/T-1.md")
    git(repo, "rm", "-q", "tasks/open/T-2.md")
    append(repo, "tasks/open/T-3.md", "target's own edit\n")
    git(repo, "mv", "tasks/open/T 4.md", "tasks/archive/T 4.md")
    git(repo, "rm", "-q", "tasks/notes.md")
    git(repo, "commit", "-qm", "target closes T-1 and T 4, removes T-2, edits T-3")
    out = check(repo)
    assert out.splitlines()[0] == "RECORDED HEAD: none"
    assert edited(out) == [
        "CLOSED TASK EDITED: tasks/open/T 4.md — the branch edited it, and main moved it to "
        "tasks/archive/T 4.md",
        "CLOSED TASK EDITED: tasks/open/T-1.md — the branch edited it, and main moved it to "
        "tasks/archive/T-1.md",
        "CLOSED TASK EDITED: tasks/open/T-2.md — the branch edited it, and main deleted it",
    ], out
    base = git(repo, "merge-base", "main", "feat").strip()[:12]
    assert f"  show: git diff {base} refs/heads/feat -- tasks/open/T-1.md" in out.splitlines()


def test_nothing_is_named_when_the_target_kept_every_body(tmp_path):
    repo = seed(tmp_path, "T-1")
    git(repo, "checkout", "-qb", "feat")
    append(repo, "tasks/open/T-1.md", PLAN)
    git(repo, "commit", "-qam", "plan")
    git(repo, "checkout", "-q", "main")
    append(repo, "tasks/open/T-1.md", "target's own edit\n")
    git(repo, "commit", "-qam", "edit")
    assert edited(check(repo)) == []


def test_a_usable_recorded_head_reads_only_what_the_branch_replays(tmp_path):
    """With a usable head, `--onto` replays only the commits past it, so an edit the head's
    squash already landed is not the branch editing a closed task. The control runs the same
    repository without the ref, where that landed edit is named."""
    repo = seed(tmp_path, "T-1", "T-2")
    git(repo, "checkout", "-qb", "feat")
    append(repo, "tasks/open/T-1.md", PLAN)
    git(repo, "commit", "-qam", "landed plan")
    head = git(repo, "rev-parse", "HEAD").strip()
    append(repo, "tasks/open/T-2.md", PLAN)
    git(repo, "commit", "-qam", "after the head")
    git(repo, "checkout", "-q", "main")
    append(repo, "tasks/open/T-1.md", PLAN)
    git(repo, "commit", "-qam", "squash of PR #7")
    git(repo, "mv", "tasks/open/T-1.md", "tasks/archive/T-1.md")
    git(repo, "commit", "-qm", "close T-1")

    assert [ln.split(" — ")[0] for ln in edited(check(repo))] == [
        "CLOSED TASK EDITED: tasks/open/T-1.md"]

    git(repo, "update-ref", "refs/sysop/merged-pr-heads/7", head)
    out = check(repo)
    assert "RECORDED HEAD: refs/sysop/merged-pr-heads/7" in out.splitlines(), out
    assert edited(out) == [], out

    git(repo, "mv", "tasks/open/T-2.md", "tasks/archive/T-2.md")
    git(repo, "commit", "-qm", "close T-2")
    out = check(repo)
    assert edited(out) == [
        "CLOSED TASK EDITED: tasks/open/T-2.md — the branch edited it, and main moved it to "
        "tasks/archive/T-2.md"], out
    assert f"  show: git diff {head[:12]} refs/heads/feat -- tasks/open/T-2.md" in out.splitlines()


def test_a_head_that_is_not_usable_reads_from_the_merge_base(tmp_path):
    """The branch merged the target after its PR head, so the head lacks commits the target
    has and item 2 takes its arm as written: the edits are read from the target's merge base."""
    repo = seed(tmp_path, "T-1", "T-2")
    git(repo, "checkout", "-qb", "feat")
    append(repo, "tasks/open/T-2.md", PLAN)
    git(repo, "commit", "-qam", "landed plan")
    git(repo, "update-ref", "refs/sysop/merged-pr-heads/7", "HEAD")
    git(repo, "checkout", "-q", "main")
    append(repo, "tasks/open/T-2.md", PLAN)
    git(repo, "commit", "-qam", "squash of PR #7")
    git(repo, "checkout", "-q", "feat")
    git(repo, "merge", "-q", "--no-edit", "-X", "theirs", "main")
    append(repo, "tasks/open/T-1.md", PLAN)
    git(repo, "commit", "-qam", "after the merge")
    git(repo, "checkout", "-q", "main")
    git(repo, "mv", "tasks/open/T-1.md", "tasks/archive/T-1.md")
    git(repo, "commit", "-qm", "close T-1")
    out = check(repo)
    assert out.splitlines()[0].startswith("RECORDED HEAD: not usable"), out
    assert edited(out) == [
        "CLOSED TASK EDITED: tasks/open/T-1.md — the branch edited it, and main moved it to "
        "tasks/archive/T-1.md"], out


def test_only_an_archive_move_or_a_delete_is_named(tmp_path):
    """Defer and reopen move a body between live directories, where the branch's edit is wanted.
    The check runs from the branch's own checkout, a nested or non-`.md` path is not a body, and
    a space-named body the target kept stays quiet."""
    repo = seed(tmp_path, "T-1", "T-2", "T 6")
    (repo / "tasks/deferred").mkdir()
    (repo / "tasks/deferred/T-3.md").write_text(BODY.format(t="T-3"))
    (repo / "tasks/deferred/T-4.md").write_text(BODY.format(t="T-4"))
    (repo / "tasks/open/sub").mkdir()
    (repo / "tasks/open/sub/T-5.md").write_text(BODY.format(t="T-5"))
    (repo / "tasks/open/T-5.txt").write_text(BODY.format(t="T-5"))
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "more")
    git(repo, "checkout", "-qb", "feat")
    for p in ("open/T-1.md", "open/T-2.md", "open/T 6.md", "deferred/T-3.md", "deferred/T-4.md",
              "open/sub/T-5.md", "open/T-5.txt"):
        append(repo, f"tasks/{p}", PLAN)
    git(repo, "commit", "-qam", "branch edits")
    git(repo, "checkout", "-q", "main")
    git(repo, "mv", "tasks/open/T-1.md", "tasks/deferred/T-1.md")
    git(repo, "mv", "tasks/deferred/T-3.md", "tasks/open/T-3.md")
    git(repo, "mv", "tasks/deferred/T-4.md", "tasks/archive/T-4.md")
    append(repo, "tasks/open/T 6.md", "target's own edit\n")
    git(repo, "rm", "-q", "tasks/open/sub/T-5.md", "tasks/open/T-5.txt", "tasks/open/T-2.md")
    git(repo, "commit", "-qam", "defer T-1, reopen T-3, close T-4, remove T-2")
    git(repo, "checkout", "-q", "feat")
    assert edited(check(repo)) == [
        "CLOSED TASK EDITED: tasks/deferred/T-4.md — the branch edited it, and main moved it to "
        "tasks/archive/T-4.md",
        "CLOSED TASK EDITED: tasks/open/T-2.md — the branch edited it, and main deleted it",
    ]


def test_the_show_line_quotes_its_path(tmp_path):
    repo = seed(tmp_path, "T 4")
    git(repo, "checkout", "-qb", "feat")
    append(repo, "tasks/open/T 4.md", PLAN)
    git(repo, "commit", "-qam", "plan")
    git(repo, "checkout", "-q", "main")
    git(repo, "mv", "tasks/open/T 4.md", "tasks/archive/T 4.md")
    git(repo, "commit", "-qm", "close")
    show = [ln for ln in check(repo).splitlines() if ln.startswith("  show: ")]
    assert len(show) == 1 and show[0].endswith("-- 'tasks/open/T 4.md'"), show
    r = subprocess.run(["/bin/bash", "-c", show[0][len("  show: "):]], cwd=repo, env=_ENV,
                       capture_output=True, text=True)
    assert "the branch's plan" in r.stdout, r.stdout + r.stderr


def test_a_tag_named_like_the_target_does_not_hide_the_line(tmp_path):
    repo = seed(tmp_path, "T-1")
    git(repo, "tag", "main")
    git(repo, "checkout", "-qb", "feat")
    append(repo, "tasks/open/T-1.md", PLAN)
    git(repo, "commit", "-qam", "plan")
    git(repo, "checkout", "-q", "main")
    git(repo, "mv", "tasks/open/T-1.md", "tasks/archive/T-1.md")
    git(repo, "commit", "-qm", "close")
    assert len(edited(check(repo))) == 1


def test_no_merge_base_stops_with_its_reason(tmp_path):
    repo = seed(tmp_path, "T-1")
    git(repo, "checkout", "-q", "--orphan", "feat")
    git(repo, "commit", "-qm", "unrelated")
    r = subprocess.run(["python3", str(SCRIPT), "feat", "main"], cwd=repo, env=_ENV,
                       capture_output=True, text=True)
    assert r.returncode == 3, r.stdout
    assert "found no merge base" in r.stdout and "Unshallow" in r.stdout, r.stdout


GIT_CHECK = REPO / "core/companion/scripts/git_check.py"


def closed_tasks(repo, *ops):
    return subprocess.run(["python3", str(GIT_CHECK), "closed-tasks", *ops], cwd=repo, env=_ENV,
                          capture_output=True, text=True)


def test_rule_b_checks_an_advance_that_closed_a_task_this_close_edited(tmp_path):
    """Under `direct`, Rule B step 3 merges a newer `origin/<default branch>` after Step 4a. Another
    clone's close archived T-1 there; this close merged a branch's edit to it. The merge itself
    is clean and carries the edit into the archive, which is why the check runs first."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    repo = seed(tmp_path, "T-1", "T-2")
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-q", "origin", "main")
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", "-b", "main", str(origin), str(other))
    (other / "tasks/archive").mkdir(exist_ok=True)
    git(other, "mv", "tasks/open/T-1.md", "tasks/archive/T-1.md")
    git(other, "commit", "-qm", "another clone's close archives T-1")
    git(other, "push", "-q", "origin", "main")
    append(repo, "tasks/open/T-2.md", PLAN)
    git(repo, "commit", "-qam", "this close: T-2 only")
    git(repo, "fetch", "-q", "origin")
    ok = closed_tasks(repo, "refs/heads/main", "refs/remotes/origin/main")
    assert ok.returncode == 0 and ok.stdout.startswith("OK: "), ok.stdout + ok.stderr

    append(repo, "tasks/open/T-1.md", PLAN)
    git(repo, "commit", "-qam", "this close: a branch's plan for T-1")
    r = closed_tasks(repo, "refs/heads/main", "refs/remotes/origin/main")
    assert r.returncode == 1, r.stdout + r.stderr
    assert [ln for ln in r.stdout.splitlines() if ln.startswith("CLOSED TASK EDITED:")] == [
        "CLOSED TASK EDITED: tasks/open/T-1.md — this close edited it, and "
        "refs/remotes/origin/main moved it to tasks/archive/T-1.md"], r.stdout
    assert r.stdout.splitlines()[-1].startswith("STOP: "), r.stdout

    git(repo, "merge", "-q", "--no-edit", "origin/main")  # the premise: clean, and it lands
    assert "the branch's plan" in (repo / "tasks/archive/T-1.md").read_text()


def test_closed_tasks_refuses_short_names_and_a_missing_merge_base(tmp_path):
    repo = seed(tmp_path, "T-1")
    r = closed_tasks(repo, "main", "refs/heads/main")
    assert r.returncode == 3 and "short name" in r.stdout, r.stdout
    git(repo, "checkout", "-q", "--orphan", "other")
    git(repo, "commit", "-qm", "unrelated")
    r = closed_tasks(repo, "refs/heads/main", "refs/heads/other")
    assert r.returncode == 2 and "no merge base" in r.stdout, r.stdout


def test_criss_cross_history_reports_only_what_every_merge_base_reports(tmp_path):
    """Phase 446's round (lens C): published branch F edits T-3 from O0; the target advances to O1,
    which edits T-1. Ours merges O1 then F; theirs merges F, then archives T-1 and T-3. There are
    two merge bases (O1, F). From O1 ours "edited" T-3, from F it "edited" T-1, and theirs archived
    both, yet the merge is clean and writes nothing of ours into either archive."""
    repo = seed(tmp_path, "T-1", "T-3")
    o0 = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "checkout", "-qb", "F")
    append(repo, "tasks/open/T-3.md", PLAN)
    git(repo, "commit", "-qam", "F edits T-3")
    git(repo, "checkout", "-q", "main")
    append(repo, "tasks/open/T-1.md", PLAN)
    git(repo, "commit", "-qam", "O1 edits T-1")
    git(repo, "checkout", "-qb", "theirs", o0)
    git(repo, "merge", "-q", "--no-edit", "main")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "F")
    git(repo, "mv", "tasks/open/T-1.md", "tasks/archive/T-1.md")
    git(repo, "mv", "tasks/open/T-3.md", "tasks/archive/T-3.md")
    git(repo, "commit", "-qm", "theirs archives both")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "F")
    bases = git(repo, "merge-base", "--all", "main", "theirs").split()
    assert len(bases) == 2, bases  # the shape under test
    r = closed_tasks(repo, "refs/heads/main", "refs/heads/theirs")
    assert r.returncode == 0, r.stdout
    git(repo, "merge", "-q", "--no-edit", "theirs")
    assert git(repo, "diff", "theirs", "HEAD", "--", "tasks/") == ""  # nothing of ours landed


def test_the_check_reads_from_the_top_level_wherever_it_runs(tmp_path):
    repo = seed(tmp_path, "T-1")
    git(repo, "checkout", "-qb", "feat")
    append(repo, "tasks/open/T-1.md", PLAN)
    git(repo, "commit", "-qam", "plan")
    git(repo, "checkout", "-q", "main")
    git(repo, "mv", "tasks/open/T-1.md", "tasks/archive/T-1.md")
    git(repo, "commit", "-qm", "close")
    assert closed_tasks(repo / "tasks", "refs/heads/feat", "refs/heads/main").returncode == 1


def test_rule_b_runs_the_check_before_its_merge():
    text = (REPO / "core/skills/_shared/main-push-guard.md").read_text(encoding="utf-8")
    step3 = text.split("3. Integrate it FIRST", 1)[1].split("\n4. ", 1)[0]
    check = step3.index('git_check.py closed-tasks "refs/heads/<default branch>" '
                        '"refs/remotes/origin/<default branch>"')
    assert check < step3.index("git merge --no-edit")
    routing = step3[check:step3.index("git merge --no-edit")]
    assert "**under `--headless`, STOP**, with nothing pushed" in routing
    assert "`Closed-task edits:`" in routing and "**Exit 2 or 3**: stop." in routing
    assert "On a `deleted it` line, STOP." in routing
    assert "until a person merges anyway or reverts the edit" in routing
    assert step3.count("refs/remotes/origin/<default branch>") == 2, "the check and the merge read one ref"


def test_the_step_routes_the_line_before_the_merge():
    """The line is only worth printing if Step 4a item 1 says what to do with it, under both
    policies, and stops on it headless."""
    text = text_of(REPO / "core/skills/review-close/SKILL.md")
    item1 = text.split("1. **Is this branch published?**", 1)[1].split("\n2. **Merge", 1)[0]
    assert "under either policy" in item1
    bullet = item1.split("**Any `CLOSED TASK EDITED:` line**", 1)[1].split("\n   ", 1)[0]
    assert "**Under `--headless`, STOP.**" in bullet
    assert "4a-SKIP" in bullet and "Step 8" in bullet
    assert "On a `deleted it` line, 4a-SKIP it." in bullet
    row = text.split("\nClosed-task edits: ", 1)[1].split("\nSquash provenance:", 1)[0]
    assert "Step 4a item 1" in row and "`Rule B: <path>` at Step 4d's push" in row, row
