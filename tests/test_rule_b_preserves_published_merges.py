"""Rule B keeps a published branch's tip an ancestor of the default branch (Phase 379).

A consumer's field report (2026-10-12, issue 0007): `_shared/main-push-guard.md` Rule B
integrated an advanced `origin/<default branch>` with a plain `git rebase`, which replays
the local commits one by one — so the `--no-ff` merge commits Step 4a's published arm makes
are flattened and the merged branch's commits are rewritten. The reporter proposed
`--rebase-merges`. Measured here: that keeps the graph SHAPE but still rewrites the side
branch's commits, so the published branch's tip is still an ancestor of nothing on the
default branch, GitHub still never marks its PR merged, and Step 6's branch delete closes
it unmerged (issue 0006's shape). Merging the remote advance in is what preserves the tip.

The phase's first cut merged only when local merge commits existed and rebased otherwise;
its round (lens C) showed the rebase arm still breaks a `direct` close that merged only
local-only branches — Step 4a's rebase-then-ff makes those tips ancestors of `main`, the
rebase rewrites them, and Step 6's `git branch -d` refuses. And lens A showed the merge arm
fired commit hooks a rebase never did, with every refusal reported as a conflict. Rule B now
ALWAYS merges, carries the project's trailers in one final `-m`, and tells a conflict from a
refusal. The tests below run the SHIPPED block, extracted from the guard file, so a
mutation of the block's text is a mutation of what runs.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GUARD = (REPO / "core/skills/_shared/main-push-guard.md").read_text(encoding="utf-8")


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "init.defaultBranch=main",
         "-c", "advice.detachedHead=false", *args],
        cwd=str(cwd), capture_output=True, text=True, check=check,
    )


@pytest.fixture
def published_merge(tmp_path: Path):
    """`main` holds a `--no-ff` merge of published branch B; origin/main has since advanced."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "-q", "--bare")
    w = tmp_path / "w"
    _git(tmp_path, "clone", "-q", str(origin), "w")
    _git(w, "checkout", "-q", "-B", "main")
    (w / "a").write_text("a")
    _git(w, "add", "a"); _git(w, "commit", "-qm", "base"); _git(w, "push", "-q", "origin", "main")
    _git(w, "checkout", "-qb", "B")
    (w / "b").write_text("b")
    _git(w, "add", "b"); _git(w, "commit", "-qm", "B1")
    _git(w, "push", "-q", "origin", "B")
    _git(w, "checkout", "-q", "main")
    _git(w, "merge", "-q", "--no-ff", "-m", "merge B (published — not rebased)", "B")
    b_tip = _git(w, "rev-parse", "B").stdout.strip()
    # an autonomous merge lands on origin/main meanwhile
    o = tmp_path / "o"
    _git(tmp_path, "clone", "-q", str(origin), "o")
    _git(o, "checkout", "-q", "main")
    (o / "c").write_text("c")
    _git(o, "add", "c"); _git(o, "commit", "-qm", "auto-merged C"); _git(o, "push", "-q", "origin", "main")
    _git(w, "fetch", "-q", "origin")
    return w, b_tip


def _is_ancestor(w: Path, sha: str) -> bool:
    return _git(w, "merge-base", "--is-ancestor", sha, "HEAD", check=False).returncode == 0


def test_a_plain_rebase_loses_the_published_tip(published_merge):
    w, b_tip = published_merge
    assert _is_ancestor(w, b_tip)
    _git(w, "rebase", "-q", "origin/main")
    assert not _is_ancestor(w, b_tip), "a plain rebase should have rewritten B's commits"


def test_rebase_merges_keeps_the_shape_but_still_loses_the_tip(published_merge):
    """The reporter's proposed fix, measured: not sufficient."""
    w, b_tip = published_merge
    _git(w, "rebase", "-q", "--rebase-merges", "origin/main")
    merges = _git(w, "rev-list", "--merges", "--count", "origin/main..HEAD").stdout.strip()
    assert merges == "1", "the merge commit should survive --rebase-merges"
    assert not _is_ancestor(w, b_tip), "--rebase-merges still rewrites the side branch's commits"


def test_the_merge_arm_keeps_the_published_tip_and_pushes(published_merge):
    w, b_tip = published_merge
    local_merges = _git(w, "rev-list", "--merges", "--count", "origin/main..HEAD").stdout.strip()
    assert local_merges != "0", "the fixture must put Rule B on its merge arm"
    _git(w, "merge", "-q", "--no-edit", "origin/main")
    assert _is_ancestor(w, b_tip)
    tip = _git(w, "rev-parse", "HEAD").stdout.strip()
    _git(w, "push", "-q", "origin", f"{tip}:main")
    _git(w, "fetch", "-q", "origin")
    assert _git(w, "merge-base", "--is-ancestor", tip, "origin/main", check=False).returncode == 0




GIT_CHECK = REPO / "core/companion/scripts/git_check.py"


def _rule_b_calls() -> list[str]:
    """The shipped calls, one per fenced block in Rule B's section, `<default branch>`
    substituted and the trailer `-m` dropped as a runner with no required trailers would drop
    it. Since Phase 422 (`Q-665`) Rule B is six calls, not one block: a `test`, an `if` and a
    `$(…)` are each denied under `dontAsk`. Phase 446 (`Q-547`) added a seventh, step 3's
    closed-task check before its merge."""
    sec = GUARD[GUARD.index("## Rule B"):GUARD.index("## Rule C")]
    blocks = re.findall(r"```bash\n(.*?)```", sec, re.S)
    assert len(blocks) == 7, f"Rule B has {len(blocks)} fenced calls, not 7; re-anchor this test"
    out = []
    for b in blocks:
        b = b.strip().replace("<default branch>", "main")
        b = b.replace(' -m "<trailers the project\'s commit convention requires, one per line>"', "")
        b = b.replace("python3 sysop/scripts/git_check.py", f'"{sys.executable}" "{GIT_CHECK}"')
        assert "<" not in b.replace("<SHA>", ""), f"unsubstituted placeholder left in a call: {b}"
        out.append(b)
    return out


def _run_rule_b(w: Path, env: dict | None = None, extra_m: str = "") -> tuple[str, str]:
    """Run the seven calls as Rule B's prose orders them; return (outcome, everything printed).

    Step 2's exit 0 skips step 3; exit 1 runs it. Step 3's closed-task check stops on a
    non-zero exit, as a headless run does; exit 0 goes on to the merge. A failed merge runs `git ls-files -u` (any
    path listed is a conflict, none a refusal) and `git merge --abort`, then stops. Step 4's
    output is the `<SHA>` steps 5 and 6 are written with."""
    import os
    e = dict(os.environ); e.update({"GIT_AUTHOR_EMAIL": "t@t", "GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t"})
    if env: e.update(env)
    calls, printed = _rule_b_calls(), []

    def sh(cmd: str) -> subprocess.CompletedProcess:
        r = subprocess.run(["/bin/bash", "-c", cmd], cwd=str(w), capture_output=True, text=True, env=e)
        printed.append(r.stdout + r.stderr)
        return r

    if sh(calls[0]).returncode:
        return "stop: not on main", "".join(printed)
    adv = sh(calls[1]).returncode
    if adv == 1:
        if sh(calls[2]).returncode:
            return "stop: closed task", "".join(printed)
        merge = calls[3].replace('(autonomous advance)"', f'(autonomous advance)" -m "{extra_m}"') \
            if extra_m else calls[3]
        if sh(merge).returncode:
            unmerged = sh("git ls-files -u").stdout.strip()
            sh("git merge --abort")
            return ("conflict" if unmerged else "refused"), "".join(printed)
    elif adv != 0:
        return "stop: advance not measured", "".join(printed)
    sha = sh(calls[4]).stdout.strip()
    if sh(calls[5].replace("<SHA>", sha)).returncode:
        return "stop: push", "".join(printed)
    if sh(calls[6].replace("<SHA>", sha)).returncode:
        return "stop: not landed", "".join(printed)
    return ("merged and pushed" if adv == 1 else "pushed"), "".join(printed)


def test_the_shipped_block_keeps_the_published_tip_and_the_remote_advance(published_merge):
    w, b_tip = published_merge
    outcome, printed = _run_rule_b(w)
    assert outcome == "merged and pushed", printed
    _git(w, "fetch", "-q", "origin")
    assert _git(w, "merge-base", "--is-ancestor", b_tip, "origin/main", check=False).returncode == 0
    assert _git(w, "cat-file", "-e", "origin/main:c", check=False).returncode == 0, "the auto-merged commit's content must survive"
    assert not (w / ".git" / "MERGE_HEAD").exists()


def test_the_shipped_sequence_skips_the_merge_when_origin_has_not_advanced(published_merge):
    w, _ = published_merge
    _git(w, "merge", "-q", "--no-edit", "origin/main")          # nothing left to integrate
    outcome, printed = _run_rule_b(w)
    assert outcome == "pushed", printed


def test_the_shipped_sequence_pushes_the_branch_tip_after_head_moves_away_and_back(published_merge):
    """Phase 422's round (lens A, M1): step 4 read `HEAD`, so an actor that checked out a work
    branch between steps 2 and 4 and returned before step 5 had its unreviewed commit pushed.
    Steps 2 and 4 read `refs/heads/main` now."""
    w, _ = published_merge
    _git(w, "merge", "-q", "--no-edit", "origin/main")
    tip = _git(w, "rev-parse", "main").stdout.strip()
    calls = _rule_b_calls()
    import os
    e = dict(os.environ); e.update({"GIT_AUTHOR_EMAIL": "t@t", "GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t"})
    sh = lambda c: subprocess.run(["/bin/bash", "-c", c], cwd=str(w), capture_output=True, text=True, env=e)
    assert sh(calls[0]).returncode == 0 and sh(calls[1]).returncode == 0
    _git(w, "checkout", "-q", "-b", "wip"); (w / "wip").write_text("x"); _git(w, "add", "wip")
    _git(w, "commit", "-qm", "unreviewed wip")
    sha = sh(calls[4]).stdout.strip()                   # step 4, while HEAD is on wip
    _git(w, "checkout", "-q", "main")
    assert sh(calls[5].replace("<SHA>", sha)).returncode == 0
    _git(w, "fetch", "-q", "origin")
    assert sha == tip and _git(w, "rev-parse", "origin/main").stdout.strip() == tip, \
        "Rule B pushed a commit that is not the default branch's tip"


def test_the_shipped_sequence_stops_before_merging_an_advance_that_closed_an_edited_task(tmp_path):
    """Phase 446 (`Q-547`): another clone's close archived T-1 on origin while this close merged
    an edit to it. Step 3's merge would be clean and write the edit into the archived copy; the
    closed-task check stops first, and nothing is pushed."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "-q", "--bare")
    w = tmp_path / "w"
    _git(tmp_path, "clone", "-q", str(origin), "w")
    _git(w, "checkout", "-q", "-B", "main")
    (w / "tasks/open").mkdir(parents=True)
    (w / "tasks/open/T-1.md").write_text("# T-1\n\na\nb\nc\n")
    _git(w, "add", "-A"); _git(w, "commit", "-qm", "base"); _git(w, "push", "-q", "origin", "main")
    o = tmp_path / "o"
    _git(tmp_path, "clone", "-q", str(origin), "o")
    _git(o, "checkout", "-q", "main")
    (o / "tasks/archive").mkdir()
    _git(o, "mv", "tasks/open/T-1.md", "tasks/archive/T-1.md")
    _git(o, "commit", "-qm", "another close archives T-1"); _git(o, "push", "-q", "origin", "main")
    advanced = _git(o, "rev-parse", "main").stdout.strip()
    with open(w / "tasks/open/T-1.md", "a") as fh:
        fh.write("\n## Plan\nmerged by this close\n")
    _git(w, "commit", "-qam", "this close merged a plan for T-1")
    _git(w, "fetch", "-q", "origin")
    outcome, printed = _run_rule_b(w)
    assert outcome == "stop: closed task", printed
    assert "CLOSED TASK EDITED: tasks/open/T-1.md" in printed, printed
    assert not (w / ".git" / "MERGE_HEAD").exists()
    _git(w, "fetch", "-q", "origin")
    assert _git(w, "rev-parse", "origin/main").stdout.strip() == advanced, "nothing may be pushed"


def test_the_shipped_sequence_refuses_off_the_default_branch(published_merge):
    w, _ = published_merge
    _git(w, "checkout", "-q", "B")
    outcome, printed = _run_rule_b(w)
    assert outcome == "stop: not on main", printed
    assert _git(w, "rev-parse", "origin/main").stdout != _git(w, "rev-parse", "B").stdout


@pytest.fixture
def local_only_merge(tmp_path: Path):
    """Step 4a's local-only arm: L rebased onto main and taken `--ff-only`; origin advanced since."""
    origin = tmp_path / "origin.git"; origin.mkdir(); _git(origin, "init", "-q", "--bare")
    w = tmp_path / "w"; _git(tmp_path, "clone", "-q", str(origin), "w"); _git(w, "checkout", "-q", "-B", "main")
    (w / "a").write_text("a"); _git(w, "add", "a"); _git(w, "commit", "-qm", "base"); _git(w, "push", "-q", "origin", "main")
    _git(w, "checkout", "-qb", "L"); (w / "l").write_text("l"); _git(w, "add", "l"); _git(w, "commit", "-qm", "L1")
    _git(w, "checkout", "-q", "main"); _git(w, "merge", "-q", "--ff-only", "L")
    l_tip = _git(w, "rev-parse", "L").stdout.strip()
    o = tmp_path / "o"; _git(tmp_path, "clone", "-q", str(origin), "o"); _git(o, "checkout", "-q", "main")
    (o / "c").write_text("c"); _git(o, "add", "c"); _git(o, "commit", "-qm", "auto-merged C"); _git(o, "push", "-q", "origin", "main")
    _git(w, "fetch", "-q", "origin")
    return w, l_tip


def test_the_shipped_block_keeps_a_local_only_branch_deletable(local_only_merge):
    """Lens C's H1: the first cut's rebase arm rewrote L's commit and `git branch -d L` refused."""
    w, l_tip = local_only_merge
    outcome, printed = _run_rule_b(w)
    assert outcome == "merged and pushed", printed
    assert _git(w, "merge-base", "--is-ancestor", l_tip, "main", check=False).returncode == 0
    assert _git(w, "branch", "-d", "L", check=False).returncode == 0, "Step 6's `git branch -d` must still succeed after Rule B"


def test_the_shipped_block_calls_a_conflict_a_conflict_and_leaves_a_clean_tree(published_merge):
    w, _ = published_merge
    o = w.parent / "o"
    (o / "b").write_text("zz"); _git(o, "add", "b"); _git(o, "commit", "-qm", "conflicting b"); _git(o, "push", "-q", "origin", "main")
    _git(w, "fetch", "-q", "origin")
    outcome, printed = _run_rule_b(w)
    assert outcome == "conflict", printed
    assert not (w / ".git" / "MERGE_HEAD").exists()
    assert _git(w, "status", "--porcelain").stdout == ""


def test_the_shipped_block_calls_a_hook_refusal_a_refusal(published_merge):
    """Lens A's F1: a commit-msg hook fires on the merge; the block must not call that a conflict."""
    w, _ = published_merge
    hook = w / ".git" / "hooks" / "commit-msg"
    hook.write_text("#!/bin/sh\ngrep -q '^Co-Authored-By:' \"$1\" || { echo 'commit-msg: Co-Authored-By trailer required' >&2; exit 1; }\n")
    hook.chmod(0o755)
    outcome, printed = _run_rule_b(w)
    assert outcome == "refused", printed
    assert not (w / ".git" / "MERGE_HEAD").exists()


def test_a_trailer_in_the_final_m_satisfies_that_hook(published_merge):
    w, b_tip = published_merge
    hook = w / ".git" / "hooks" / "commit-msg"
    hook.write_text("#!/bin/sh\ngrep -q '^Co-Authored-By:' \"$1\" || exit 1\n"); hook.chmod(0o755)
    outcome, printed = _run_rule_b(w, extra_m="Co-Authored-By: T <t@t>")
    assert outcome == "merged and pushed", printed
    assert "Co-Authored-By: T <t@t>" in _git(w, "log", "-1", "--format=%B").stdout


def test_rule_b_prescribes_a_merge_and_no_rebase_outside_comments():
    sec = GUARD[GUARD.index("## Rule B"):GUARD.index("## Rule C")]
    code = "\n".join(re.findall(r"```bash\n(.*?)```", sec, re.S))
    assert 'git merge --no-edit -m "merge origin/<default branch> (autonomous advance)"' in code
    assert "git rebase" not in code, "the rebase arm is back — lens C's H1"
    assert "--rebase-merges" not in code
    # The conflict-or-refusal reading and the abort are prose now, each a call of its own.
    flat = " ".join(sec.split())
    assert "Run `git ls-files -u`: paths it lists are a conflict with an auto-merged commit; none means a hook or git refused the merge" in flat
    assert "Then run `git merge --abort`" in flat
    assert "**Exit 0**: it has not; go to 4. **Exit 1**: it has; go to 3. **Exit 2 or 3**: stop." in flat
