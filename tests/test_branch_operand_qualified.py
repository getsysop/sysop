"""`Q-686`: a branch name that is also a tag name is read as the branch.

git resolves a bare name tag-first (`refs/tags/<n>` before `refs/heads/<n>`), so where a tag of
a branch's name sits on an ancestor of the merge target, an ancestry test on the bare name reads
an unmerged branch as merged: `/review-close` Step 4c routed its doc, flipped its tasks `done` and
dropped its lock. Wade's ruling (Phase 406's open): every operand whose value is a local branch
name is `refs/heads/<branch>`, and a `branch:` with no local branch stops the close.

The split this module holds, measured in Phase 409's probe (opened as 407): a REVISION operand (`rev-list`,
`rev-parse`, `log`, `diff`, `show`, `cherry`, `merge-base`, `merge`, `for-each-ref --contains`,
`push --delete`) takes `refs/heads/`; a BRANCH-NAME operand (`checkout`, `rebase`'s branch,
`branch -d/-D`) stays bare, because those look up branches only and `git checkout refs/heads/x`
detaches HEAD. The script sites are executed against the collision; the skill text is a census.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "core" / "companion" / "scripts"
CLOSE = REPO / "core" / "skills" / "review-close"
sys.path.insert(0, str(SCRIPTS))

import gate_verdict as gv  # noqa: E402
import ignored_refs as ir  # noqa: E402
import pending_doc_hold as pdh  # noqa: E402
import permission_denied_hook as hook  # noqa: E402
import sitrep_survey as ss  # noqa: E402

_ENV = {k: v for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}


def _g(root: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, env=_ENV)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def _commit(root: Path, name: str) -> str:
    (root / name).write_text(f"{name}\n", encoding="utf-8")
    _g(root, "add", name)
    _g(root, "commit", "-qm", name)
    return _g(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """`main` at `seed`; tag `dup` at `seed`; branch `dup` one commit past it, unmerged; a tag
    `onlytag` with no branch; a branch `clean` at `seed`, merged, with no tag."""
    root = tmp_path / "repo"
    root.mkdir()
    _g(root, "-c", "init.defaultBranch=main", "init", "-q")
    _g(root, "config", "user.email", "t@example.invalid")
    _g(root, "config", "user.name", "t")
    _g(root, "config", "commit.gpgsign", "false")
    seed = _commit(root, "seed")
    _g(root, "tag", "dup", seed)
    _g(root, "tag", "onlytag", seed)
    _g(root, "branch", "clean", seed)
    _g(root, "checkout", "-q", "-b", "dup")
    _commit(root, "work.py")
    _g(root, "checkout", "-q", "main")
    # The premise: bare `dup` is the tag, and reads merged.
    assert _g(root, "rev-list", "--count", "dup", "^HEAD") == "0"
    assert _g(root, "rev-list", "--count", "refs/heads/dup", "^HEAD") == "1"
    return root


# ── pending_doc_hold.py (Step 4c 1c) ──

def test_branch_merged_reads_the_branch_not_the_tag(repo):
    assert pdh.branch_merged(repo, "dup") is False
    assert pdh.branch_merged(repo, "clean") is True, "the control: a merged branch still reads merged"


def test_a_name_that_is_only_a_tag_has_no_local_branch(repo):
    assert pdh.has_local_branch(repo, "onlytag") is False
    assert pdh.branch_merged(repo, "onlytag") is False
    assert pdh.has_local_branch(repo, "dup") is True


def _held_doc(repo: Path, name: str, branch: str) -> None:
    pd = repo / "sysop" / "runtime" / "pending-docs"
    pd.mkdir(parents=True, exist_ok=True)
    (pd / f"{name}.md").write_text(
        f"---\nbranch: {branch}\nhold: waiting on a run\nroadmap_ids: [FEAT-1]\n---\n# x\n",
        encoding="utf-8")


def test_the_stamp_note_says_which_case_fired(repo, capsys):
    """A reader of Step 8's row must tell 'no local branch' from 'not merged'."""
    _held_doc(repo, "a", "onlytag")
    _held_doc(repo, "b", "dup")
    assert pdh.check(repo, stamp=True, today="2026-10-22") == 0
    out = capsys.readouterr().out
    assert "a.md" in out and "NOT STAMPED: no local branch onlytag" in out, out
    assert "NOT STAMPED: branch dup is not merged into HEAD" in out, out
    assert "held_since" not in (repo / "sysop/runtime/pending-docs/b.md").read_text()



def test_branch_merged_asks_the_recorded_heads_about_the_branch(repo):
    """A recorded PR head at `main` contains the tag's commit, not the branch's work."""
    _g(repo, "update-ref", "refs/sysop/merged-pr-heads/5", "main")
    assert pdh.branch_merged(repo, "dup") is False


# ── pr_head_check.py (Step 4a item 1) ──

def test_the_recorded_head_check_reads_the_branch(repo):
    """The branch's work was squashed by PR 12 and a follow-up commit added: bare, the tag's
    commit is in `main` and no recorded head reads as containing the branch's commits."""
    _g(repo, "update-ref", "refs/sysop/merged-pr-heads/12", "refs/heads/dup")
    _g(repo, "checkout", "-q", "dup")
    _commit(repo, "follow_up.py")
    _g(repo, "checkout", "-q", "main")
    (repo / "work.py").write_text("work.py\n", encoding="utf-8")
    _g(repo, "add", "work.py")
    _g(repo, "commit", "-qm", "squash of PR 12")
    r = subprocess.run([sys.executable, str(SCRIPTS / "pr_head_check.py"), "dup", "main"],
                       cwd=repo, capture_output=True, text=True, env=_ENV)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RECORDED HEAD: refs/sysop/merged-pr-heads/12" in r.stdout, r.stdout


def test_the_recorded_head_check_refuses_a_name_with_no_local_branch(repo):
    r = subprocess.run([sys.executable, str(SCRIPTS / "pr_head_check.py"), "onlytag", "main"],
                       cwd=repo, capture_output=True, text=True, env=_ENV)
    assert r.returncode == 3 and "STOP" in r.stdout, r.stdout

# ── gate_verdict.py (Step 2b's verdict key) ──

def test_the_gate_key_hashes_the_branch_tip_not_the_tag(repo, monkeypatch):
    monkeypatch.chdir(repo)
    tip, _ = gv.ends("dup", "main")
    assert tip == _g(repo, "rev-parse", "refs/heads/dup")


def test_the_gate_refuses_a_name_with_no_local_branch(repo, monkeypatch):
    monkeypatch.chdir(repo)
    with pytest.raises(gv.Refuse):
        gv.ends("onlytag", "main")


# ── ignored_refs.py (Step 3b's ignored-file check) ──

def test_the_ignored_file_check_reads_the_branchs_commits(repo):
    assert ir._tip(repo, "dup") == "refs/heads/dup"
    files = {f for f, _, _ in ir.added_lines(repo, "main", "dup")}
    assert "work.py" in files, files


# ── sitrep_survey.py ──

def test_sitrep_drift_counts_the_branch_past_a_same_named_tag(repo):
    """The doc's `branch_tip:` is the tag's commit; the branch moved one commit past it."""
    doc = repo / "sysop" / "runtime" / "pending-docs" / "dup.md"
    doc.parent.mkdir(parents=True)
    seed = _g(repo, "rev-parse", "refs/tags/dup")
    doc.write_text(f"---\nbranch: dup\nbranch_tip: {seed}\n---\n", encoding="utf-8")
    assert ss._pending_doc_drift(doc, "dup").commits == 1


def test_sitrep_unpushed_count_reads_the_branch(repo, tmp_path):
    origin = tmp_path / "origin.git"
    _g(tmp_path, "init", "-q", "--bare", str(origin))
    _g(repo, "remote", "add", "origin", str(origin))
    _g(repo, "push", "-q", "origin", "refs/heads/dup:refs/heads/dup")
    _g(repo, "branch", "-q", "--set-upstream-to=origin/dup", "dup")
    _g(repo, "checkout", "-q", "dup")
    _commit(repo, "more.py")
    _g(repo, "checkout", "-q", "main")
    assert ss._commits_unpushed("dup", repo) == 1



def test_sitrep_reads_a_claimed_batch_whose_branch_is_only_a_tag_as_branchless(repo):
    """The batch's branch was deleted and a tag of its name remains: bare, `rev-parse
    --verify` resolves the tag and the claim reads as having a branch."""
    batch = {"number": 7, "title": "Batch 7", "status": "Pending", "branch": "onlytag",
             "flag_reason": "", "triaged_date": "2026-08-30", "triaged_verdict": "auto",
             "triaged_tasks": [], "tasks": [{"id": "TASK-601", "checkbox": " "}]}
    lock = ss.Lock(path=repo / "BATCH-7.lock", task_id="BATCH-7", branch="onlytag",
                   started="2026-08-30T12:00:00Z", raw={})
    (out,) = ss._classify_review_batches([batch], [lock], [], repo)
    assert out.state == "claimed, no branch", out.state


def test_sitrep_counts_the_branchs_own_commits(repo):
    assert len(ss._commits_ahead_of_main("dup", repo)) == 1


def test_the_ignored_file_check_names_the_checked_out_branch(repo):
    """`symbolic-ref --short HEAD` prints `heads/dup` under the collision."""
    _g(repo, "checkout", "-q", "dup")
    assert ir._head_branch(repo) == "dup"
    assert ir._tip(repo, "dup") == "HEAD"


def test_sitrep_live_work_sees_a_dirty_primary_on_the_branch(repo):
    """The primary's check (`--branch` claims work there) compared `--abbrev-ref HEAD`'s
    `heads/dup` with `dup`, so its uncommitted work did not count."""
    _g(repo, "checkout", "-q", "dup")
    (repo / "work.py").write_text("uncommitted\n", encoding="utf-8")
    assert ss._live_work_past(repo, "dup", None, None, False, []) is True


def test_sitrep_lists_a_task_shaped_orphan_by_its_name(repo):
    """`%(refname:lstrip=2)` names the branch; `lstrip=1` (or `refname:short` under a tag)
    gives `heads/<name>`, which is not task-shaped, and the orphan vanishes."""
    _g(repo, "branch", "tech/tech-orphan")
    _g(repo, "tag", "tech/tech-orphan")
    ds = ss._find_discrepancies([], [], {}, repo)
    assert [d.detail for d in ds if d.kind == "orphan branch"] == [
        "branch tech/tech-orphan has no lock, no worktree, no index entry"], ds


def test_the_ignored_file_check_names_a_slashed_branch(repo):
    """A checked-out `feat/x`: the name is everything after `refs/heads/`, not its last segment."""
    _g(repo, "checkout", "-q", "-b", "feat/x")
    assert ir._head_branch(repo) == "feat/x"
    assert ir._tip(repo, "feat/x") == "HEAD"

# ── permission_denied_hook.py ──

def test_the_hook_names_the_bare_branch_for_the_local_delete():
    for denied in ("refs/heads/feat/x", '"refs/heads/feat/x"', "'refs/heads/feat/x'", "feat/x"):
        msg = hook._match_destructive_push(f"git push origin --delete {denied}", "/nonexistent")
        assert f"! git push origin --delete {denied}" in msg
        assert "`git branch -d feat/x`" in msg, msg


# ── cleanup_worktrees.sh ──

def test_cleanup_does_not_read_an_unmerged_worktree_as_merged(repo, tmp_path):
    wt = tmp_path / "wt"
    _g(repo, "worktree", "add", "-q", str(wt), "dup")
    r = subprocess.run(["bash", str(SCRIPTS / "cleanup_worktrees.sh"), "list"], cwd=repo,
                       capture_output=True, text=True, env=_ENV)
    assert r.returncode == 0, r.stderr
    line = next(ln for ln in r.stdout.splitlines() if str(wt.name) in ln and "dup" in ln)
    assert "MERGED" not in line, r.stdout


# ── the skill text ──

# Every shipped skill file a runner reads (its `REFERENCE.md` is rationale, quoting history), the
# companion docs and the task templates: a census over a hand-picked list misses the file nobody
# picked (round 2, lens D: dropping five members from the old list went unseen).
_CORE = REPO / "core"
CENSUS_FILES = (sorted(p for p in (_CORE / "skills").rglob("*.md") if p.name != "REFERENCE.md")
                + sorted((_CORE / "companion" / "docs").glob("*.md"))
                + sorted((_CORE / "companion" / "tasks").glob("*.md")))

# git, its global options (`-C <dir>` with a spaced placeholder or quoted path, `-c k=v`, `-P`,
# `--no-pager`, a long option with a quoted value), then a command that takes a revision.
_GLOBAL = (r"""(?:\s+(?:-C\s+(?:<[^<>]*>|"[^"]*"|'[^']*'|\S+)|-c\s+\S+|-[pP](?![\w-])"""
           r"""|--[\w-]+(?:=\S+|\s+(?:"[^"]*"|'[^']*'))?))*""")
_REVISION = re.compile(
    r"\bgit" + _GLOBAL + r"\s+(rev-list|rev-parse|log|diff|show|cherry|merge-base|merge"
    r"|for-each-ref|push|fetch|cat-file|ls-tree|reset|range-diff|format-patch|cherry-pick|revert"
    r"|restore)\b")
# A branch placeholder in any spelling (`<branch>`, `<target branch>`, `<BRANCH_NAME>`,
# `<feature_branch>`, …) or a branch variable (`$branch`, `${BRANCH}`, `$APPROVED_BRANCH`), not
# already behind `refs/heads/`, `origin/` or another path segment. `<…default branch>` and
# `$DEFAULT_BRANCH` are the default branch, outside `Q-686`'s population (`Q-703`); a `…tip`
# is a commit.
_BARE = re.compile(
    r"(?<![\w/])(<(?![^<>]*branch_tip)(?![^<>]*default branch)[^<>]*[bB][rR][aA][nN][cC][hH][^<>]*>"
    r"|\$\{?(?![A-Za-z_]*(?:TIP|tip|DEFAULT|default))[A-Za-z_]*(?:branch|BRANCH)[A-Za-z_]*\}?(?!\w))")
# Exact spans that QUOTE a command as history or as an illustration, each with its reason; removed
# before matching, so a bare operand elsewhere on the same line is still read.
_EXEMPT_SPANS = {
    # Step 6's rationale, quoting the containment re-check an earlier draft prescribed.
    "prescribed `git rev-list --count <branch> ^origin/<default branch>`",
    # The author-side pass's account of the round that produced rule 3.
    'a prescribed `git show "<branch>:<body path>"`',
    # `/document-work` Step 0's illustration of what an EMPTY operand does.
    "`git rev-list --count ..<branch>` both",
}


def _census_text(p: Path) -> str:
    text = p.read_text(encoding="utf-8").replace("\\\n", " ")   # a continuation is one command
    for span in _EXEMPT_SPANS:
        text = text.replace(span, "")
    return text


def _skill_lines():
    for p in CENSUS_FILES:
        for n, line in enumerate(_census_text(p).splitlines(), 1):
            yield p.relative_to(REPO), n, line


def _span(line: str, i: int) -> str:
    """The command from `i`: to a code span's end or the line's, or to `;`, `|` or `)` outside
    quotes, so `--format='%h (%s)'` does not end it and a following `|| echo` is not read."""
    quote, j = None, i
    while j < len(line) and line[j] not in "`\n":
        ch = line[j]
        if quote:
            quote = None if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch in ";|)":
            break
        j += 1
    return line[i:j]


def _bare_operands(line: str) -> list[str]:
    line = line.replace("\\\n", " ")
    hits = []
    for m in _REVISION.finditer(line):
        cmd = _span(line, m.start())
        if m.group(1) in ("merge", "cherry-pick", "revert"):
            cmd = re.sub(r'-m\s+"[^"]*"', "", cmd)   # a commit message (`log -m` takes none)
        hits += [b.group(1) for b in _BARE.finditer(cmd)]
    return hits


def test_the_census_reads_every_runner_file():
    names = {p.relative_to(REPO).as_posix() for p in CENSUS_FILES}
    for must in ("core/skills/review-close/SKILL.md", "core/skills/review-close/steps/2b-large-diff.md",
                 "core/skills/claim-task/SKILL.md", "core/skills/_shared/main-push-guard.md",
                 "core/companion/docs/WORKFLOW_GUIDE.md", "core/companion/tasks/schema.md"):
        assert must in names, must
    assert not any(n.endswith("REFERENCE.md") for n in names)
    assert len(names) > 40, len(names)


def test_no_revision_operand_names_a_bare_branch():
    found = [f"{p}:{n}: {_bare_operands(line)}" for p, n, line in _skill_lines()
             if _bare_operands(line)]
    assert not found, "\n".join(found)


def test_every_exempt_span_is_live_and_exempts_one_operand():
    """A stale span exempts nothing; a wide one (`git push`) would exempt every push."""
    text = "\n".join(p.read_text(encoding="utf-8") for p in CENSUS_FILES)
    for span in _EXEMPT_SPANS:
        assert text.count(span) == 1, (span, text.count(span))
        assert len(_bare_operands(span)) == 1, (span, _bare_operands(span))


@pytest.mark.parametrize("line", [
    'git rev-list --count "<branch from frontmatter>" "^HEAD"',
    "`git merge --ff-only <branch>`",
    'git merge --ff-only "$BRANCH"',
    'git merge --ff-only "$APPROVED_BRANCH"',
    "git merge --ff-only $branch_name",
    'git log --oneline "<default branch>..$branch" --not',
    'git log --oneline "<default branch>..${branch}" --not',
    'git log -m "<default branch>..<branch>"',
    "git log --format='%h (%s)' <default branch>..<branch>",
    "git log --format='%H|%s' <default branch>..<branch>",
    'git show "<branch>:tasks/x.md"',
    "git push origin --delete <branch>",
    "git push --delete origin <branch>",
    'git cherry HEAD "<branch from frontmatter>"',
    'PIN=$(git rev-parse --verify "<target branch>^{commit}")',
    "git -C <absolute path to the pinned checkout> diff <default branch>...<branch>",
    "git -C '/a spaced/path' diff <default branch>...<branch>",
    "git --no-pager show <branch>:x",
    "git -P log <branch>",
    'git --git-dir "/x y/.git" log <branch>',
    "git -c core.quotepath=off diff <default branch>...<branch>",
    'git fetch origin "<approved branch name>"',
    "git rev-list --count <default branch>..<BRANCH_NAME>",
    "git log <feature_branch>",
    "git log <branchname>",
    'git rev-list --count origin/<default branch>..<default branch> --not "<approved branch name>"',
    "git merge-base --is-ancestor <batch branch> <merge target>",
    "git for-each-ref --contains <branch> refs/sysop/merged-pr-heads/",
    "git cat-file -e <branch>:tasks/index.yml",
    "git ls-tree <branch> tasks/",
    "git reset --hard <branch>",
    "git range-diff <default branch>...<branch>",
    "git format-patch <default branch>..<branch>",
    "git restore --source=<branch> -- x",
    'git diff \\\n  <default branch>...<branch> --stat',
])
def test_the_census_sees_a_bare_operand(line):
    """The vacuity control: each shape this phase fixed or a round evaded with, written bare."""
    assert _bare_operands(line), line


@pytest.mark.parametrize("line", [
    'git merge --no-ff -m "merge <branch> (x)" refs/heads/<branch>',
    'PIN=$(git rev-parse --verify "refs/heads/<target branch>^{commit}") || { echo "STOP: <target branch>"; }',
    "git diff <default branch>...refs/heads/<branch>",
    "git rev-list --count <branch_tip>..refs/heads/<branch>",
    'git log "$DEFAULT_BRANCH"..refs/heads/x',
    "git checkout <branch> && git rebase <merge target>",
    'git fetch origin "+refs/heads/<branch>:refs/remotes/origin/<branch>"',
])
def test_the_census_passes_a_qualified_operand(line):
    assert not _bare_operands(line), line


# HEAD's name read short. `rev-parse --abbrev-ref HEAD` and `symbolic-ref --short HEAD` print
# `heads/<name>` when a tag shares the name; `git branch --show-current` prints the name. The
# reads left are against the default branch (`Q-703`) or are prose naming the anti-pattern, so
# the count per file is a ratchet: a new one is either `--show-current` or a `Q-703` site.
_SHORT_HEAD = re.compile(r"rev-parse\s+--abbrev-ref\s+HEAD|symbolic-ref\s+(?:-q\s+)?--short(?:\s+-q)?\s+HEAD")
SHORT_HEAD_KNOWN = {
    # Phase 421 (`Q-710`): Rule A's templates and the claim-task, document-work and release
    # asserts became `git_check.py`, which compares `refs/heads/<name>`. Phase 422 (`Q-665`):
    # Rule B's assert, Step 4's HARD RULE, 3c's stop check and 4d-pr's comment did too.
    "core/companion/docs/WORKFLOW.md": 2,          # prose
}


def test_no_new_head_name_is_read_short():
    got = {}
    for p in CENSUS_FILES:
        n = len(_SHORT_HEAD.findall(p.read_text(encoding="utf-8")))
        if n:
            got[p.relative_to(REPO).as_posix()] = n
    assert got == SHORT_HEAD_KNOWN, got


def test_the_short_head_census_sees_each_spelling():
    for line in ('test "$(git rev-parse --abbrev-ref HEAD)" = "<b>"', "git symbolic-ref --short HEAD",
                 "git symbolic-ref -q --short HEAD", 'gh pr list --head "$(git rev-parse --abbrev-ref HEAD)"'):
        assert _SHORT_HEAD.search(line), line
    assert not _SHORT_HEAD.search("git branch --show-current")


_QUALIFIED_NAME_POSITION = re.compile(
    r"git" + _GLOBAL + r"\s+(?:checkout|switch|branch\s+-[dD](?:\s+--)?|worktree\s+add\s+\S+|rebase)"
    r"(?:\s+[^\s`&|;]+)*?\s+[\"']?refs/heads/")


def test_branch_name_positions_stay_bare():
    """`git checkout refs/heads/x` and `git rebase <upstream> refs/heads/x` detach HEAD, and
    `git branch -D refs/heads/x` fails."""
    text = "\n".join(line for _, _, line in _skill_lines())
    assert "git checkout <branch> && git rebase" in text
    assert 'git rebase --onto "<merge target>" "<ref>" <branch>' in text
    assert "git branch -D <branch>" in text and "git branch -d <branch>" in text
    hits = [m.group(0) for line in text.splitlines() for m in _QUALIFIED_NAME_POSITION.finditer(line)]
    assert not hits, hits


@pytest.mark.parametrize("line", [
    "git checkout -q refs/heads/x", "git -C d checkout refs/heads/x", "git checkout 'refs/heads/x'",
    "git branch -D -- refs/heads/x", "git worktree add p refs/heads/x", "git rebase main refs/heads/x",
    "git switch refs/heads/x"])
def test_the_stay_bare_check_sees_a_qualified_name_position(line):
    assert _QUALIFIED_NAME_POSITION.search(line), line


def test_enumerations_print_the_branch_name_not_the_short_refname():
    """`%(refname:short)` prints `heads/dup` when a tag `dup` exists; prefixed, that is
    `refs/heads/heads/dup`."""
    text = "\n".join(line for _, _, line in _skill_lines())
    assert "refname:short" not in text
    assert "refname:short" not in (SCRIPTS / "self_check.sh").read_text()
    assert "refname:short" not in (SCRIPTS / "sitrep_survey.py").read_text()
