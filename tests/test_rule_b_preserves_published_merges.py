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




def _rule_b_script() -> str:
    """The shipped fenced sequence, `<default branch>` substituted, the trailer `-m` dropped
    as a runner with no required trailers would drop it."""
    m = re.search(r"```bash\n(# 1\. on the default branch\? \(Rule A\).*?)```", GUARD, re.S)
    assert m, "Rule B's fenced sequence has moved; re-anchor this test"
    script = m.group(1).replace("<default branch>", "main")
    script = script.replace(' -m "<trailers the project\'s commit convention requires, one per line>"', "")
    assert "<" not in script.replace("<<", ""), f"unsubstituted placeholder left in the block: {script}"
    return script


def _run_rule_b(w: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    import os
    e = dict(os.environ); e.update({"GIT_AUTHOR_EMAIL": "t@t", "GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t"})
    if env: e.update(env)
    return subprocess.run(["/bin/bash", "-c", _rule_b_script()], cwd=str(w), capture_output=True, text=True, env=e)


def test_the_shipped_block_keeps_the_published_tip_and_the_remote_advance(published_merge):
    w, b_tip = published_merge
    r = _run_rule_b(w)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "merging it in" in r.stdout
    assert _git(w, "merge-base", "--is-ancestor", b_tip, "origin/main", check=False).returncode == 0
    assert _git(w, "cat-file", "-e", "origin/main:c", check=False).returncode == 0, "the auto-merged commit's content must survive"
    assert not (w / ".git" / "MERGE_HEAD").exists()


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
    r = _run_rule_b(w)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _git(w, "merge-base", "--is-ancestor", l_tip, "main", check=False).returncode == 0
    assert _git(w, "branch", "-d", "L", check=False).returncode == 0, "Step 6's `git branch -d` must still succeed after Rule B"


def test_the_shipped_block_calls_a_conflict_a_conflict_and_leaves_a_clean_tree(published_merge):
    w, _ = published_merge
    o = w.parent / "o"
    (o / "b").write_text("zz"); _git(o, "add", "b"); _git(o, "commit", "-qm", "conflicting b"); _git(o, "push", "-q", "origin", "main")
    _git(w, "fetch", "-q", "origin")
    r = _run_rule_b(w)
    assert r.returncode == 1
    assert "conflict with an auto-merged commit" in r.stdout
    assert "merge refused" not in r.stdout, "a conflict must be diagnosed as a conflict only — falling through to the refusal arm means the conflict arm lost its exit (battery A13)"
    assert not (w / ".git" / "MERGE_HEAD").exists()
    assert _git(w, "status", "--porcelain").stdout == ""


def test_the_shipped_block_calls_a_hook_refusal_a_refusal(published_merge):
    """Lens A's F1: a commit-msg hook fires on the merge; the block must not call that a conflict."""
    w, _ = published_merge
    hook = w / ".git" / "hooks" / "commit-msg"
    hook.write_text("#!/bin/sh\ngrep -q '^Co-Authored-By:' \"$1\" || { echo 'commit-msg: Co-Authored-By trailer required' >&2; exit 1; }\n")
    hook.chmod(0o755)
    r = _run_rule_b(w)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "merge refused" in r.stdout and "conflict" not in r.stdout.split("merge refused")[0].split("merging it in")[-1]
    assert not (w / ".git" / "MERGE_HEAD").exists()


def test_a_trailer_in_the_final_m_satisfies_that_hook(published_merge):
    w, b_tip = published_merge
    hook = w / ".git" / "hooks" / "commit-msg"
    hook.write_text("#!/bin/sh\ngrep -q '^Co-Authored-By:' \"$1\" || exit 1\n"); hook.chmod(0o755)
    script = _rule_b_script().replace('-m "merge origin/main (autonomous advance)"', '-m "merge origin/main (autonomous advance)" -m "Co-Authored-By: T <t@t>"')
    import os
    e = dict(os.environ); e.update({"GIT_AUTHOR_EMAIL": "t@t", "GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t"})
    r = subprocess.run(["/bin/bash", "-c", script], cwd=str(w), capture_output=True, text=True, env=e)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Co-Authored-By: T <t@t>" in _git(w, "log", "-1", "--format=%B").stdout


def test_rule_b_prescribes_a_merge_and_no_rebase_outside_comments():
    m = re.search(r"```bash\n(# 1\. on the default branch\? \(Rule A\).*?)```", GUARD, re.S)
    code = "\n".join(l for l in m.group(1).split("\n") if not l.strip().startswith("#"))
    assert 'git merge --no-edit -m "merge origin/<default branch> (autonomous advance)"' in code
    assert "git rebase" not in code, "the rebase arm is back — lens C's H1"
    assert "--rebase-merges" not in code
    assert 'git ls-files -u' in code and "git merge --abort" in code
    assert "merge refused" in code and "conflict with an auto-merged commit" in code
