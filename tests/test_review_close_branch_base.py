"""Phase 472 (`Q-734`) — a branch's Step 2 diffs start at its newest common ancestor with either
`<default branch>` or `origin/<default branch>`.

Step 2a, 2b and 2d diffed a feature branch three-dot from local `<default branch>`, so a local
`<default branch>` behind `origin` handed the reviewers the upstream commits a branch was cut
over as the branch's own. Wade ruled the base on 2026-11-06: `git merge-base <branch>
<default branch> origin/<default branch>`. `gate_verdict.py`'s `ends` computes it,
`feature_branch.py base` prints it for the runner, and `security_map_filter.py` inherits it.

Each shape below fails a one-sided base: dropping the `origin` side fails the behind case,
dropping the local side fails the local-only-commit case, and dropping the fallback fails the
no-remote cases.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "core" / "companion" / "scripts"
CLOSE_DIR = REPO / "core" / "skills" / "review-close"
sys.path.insert(0, str(SCRIPTS))
import gate_verdict  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_runner_text import text_of  # noqa: E402

GIT_ENV = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}

# One glob the upstream-only and local-only files match, and none the branch's file does.
MAP = "# Security map\n\n## `scripts/*.sh` — Shell Scripts\n- **Check:** A03 shell injection\n"


def git(cwd, *args) -> str:
    p = subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                       capture_output=True, text=True, env=GIT_ENV)
    assert p.returncode == 0, (args, p.stderr)
    return p.stdout.strip()


def commit(cwd, name, text="x\n"):
    (cwd / name).parent.mkdir(parents=True, exist_ok=True)
    (cwd / name).write_text(text, encoding="utf-8")
    git(cwd, "add", "-A")
    git(cwd, "commit", "-q", "-m", name)


def script(cwd, name, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / name), *args], cwd=cwd,
                          capture_output=True, text=True, env=GIT_ENV)


def base_of(cwd, branch, default="main") -> str:
    p = script(cwd, "feature_branch.py", "base", branch, default)
    assert p.returncode == 0, p.stderr
    m = re.fullmatch(r"BASE: ([0-9a-f]{40,64})\n", p.stdout)
    assert m, p.stdout
    return m.group(1)


def changed(cwd, base, branch) -> list[str]:
    return git(cwd, "diff", "--name-only", base, f"refs/heads/{branch}").splitlines()


@pytest.fixture
def clone(tmp_path):
    """`up` is `origin`; `local` is the consumer's clone, with the security map on both."""
    up = tmp_path / "up"
    subprocess.run(["git", "init", "-q", "-b", "main", str(up)], check=True, env=GIT_ENV)
    commit(up, ".claude/security_map.md", MAP)
    local = tmp_path / "local"
    subprocess.run(["git", "clone", "-q", "-b", "main", str(up), str(local)], check=True,
                   env=GIT_ENV, capture_output=True)
    return up, local


@pytest.fixture
def behind_and_ahead(clone):
    """The entry's fixture: local `main` one behind and one ahead of `origin/main`, and the
    branch cut from `origin/main`."""
    up, local = clone
    commit(up, "scripts/upstream.sh")
    git(local, "fetch", "-q")
    commit(local, "notes/local.md")
    git(local, "switch", "-q", "--no-track", "-c", "feat", "refs/remotes/origin/main")
    commit(local, "docs/feature.md")
    git(local, "switch", "-q", "main")
    return local


def test_premise_three_dots_from_local_main_hand_over_upstream_work(behind_and_ahead):
    """Not coverage: the old basis, shown wrong on the fixture, so the tests below can tell."""
    old = git(behind_and_ahead, "diff", "--name-only", "main...refs/heads/feat").splitlines()
    assert sorted(old) == ["docs/feature.md", "scripts/upstream.sh"]


def test_a_branch_cut_from_origin_over_a_stale_main_diffs_only_its_own_work(behind_and_ahead):
    base = base_of(behind_and_ahead, "feat")
    assert base == git(behind_and_ahead, "rev-parse", "refs/remotes/origin/main")
    assert changed(behind_and_ahead, base, "feat") == ["docs/feature.md"]


def test_a_branch_carrying_a_local_only_main_commit_does_not_review_it_again(clone):
    """The unpushed-main group reviews a local-only commit; `origin` alone as the base would
    review it a second time as the branch's."""
    _, local = clone
    commit(local, "scripts/local.sh")
    git(local, "switch", "-q", "-c", "feat", "main")
    commit(local, "docs/feature.md")
    git(local, "switch", "-q", "main")
    base = base_of(local, "feat")
    assert base == git(local, "rev-parse", "refs/heads/main")
    assert changed(local, base, "feat") == ["docs/feature.md"]


@pytest.mark.parametrize("shape", ["no remote", "remote never fetched"])
def test_with_no_origin_default_branch_the_local_one_is_the_base(clone, shape):
    _, local = clone
    commit(local, "scripts/local.sh")
    git(local, "switch", "-q", "-c", "feat", "main")
    commit(local, "docs/feature.md")
    git(local, "switch", "-q", "main")
    git(local, "remote", "remove", "origin")
    if shape == "remote never fetched":
        git(local, "remote", "add", "origin", str(local.parent / "nowhere"))
    assert base_of(local, "feat") == git(local, "merge-base", "refs/heads/main", "refs/heads/feat")



@pytest.mark.parametrize("upstream_newer", [True, False])
def test_two_bases_take_origins(clone, upstream_newer):
    """A branch cut from a local-only commit that merged `origin/main` in has two newest common
    ancestors; git picks one by commit date. Wade (2026-11-06): take origin's, so the diff can
    hold only the local-only commit, never upstream work (the round's lens A)."""
    up, local = clone
    env = dict(GIT_ENV)
    def dated(cwd, name, when):
        (cwd / name).parent.mkdir(parents=True, exist_ok=True)
        (cwd / name).write_text("x\n", encoding="utf-8")
        git(cwd, "add", "-A")
        d = f"2026-01-0{when}T00:00:00"
        subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                        "-m", name], env={**env, "GIT_AUTHOR_DATE": d, "GIT_COMMITTER_DATE": d}, check=True)
    dated(local, "L1.txt", 1 if upstream_newer else 3)
    dated(up, "O2.txt", 3 if upstream_newer else 1)
    git(local, "fetch", "-q")
    git(local, "switch", "-q", "-c", "feat", "main")
    commit(local, "F1.txt")
    git(local, "merge", "-q", "--no-edit", "refs/remotes/origin/main")
    git(local, "switch", "-q", "main")
    assert len(git(local, "merge-base", "--all", "refs/heads/feat", "refs/heads/main",
                   "refs/remotes/origin/main").split()) == 2, "premise: two bases"
    base = base_of(local, "feat")
    assert base == git(local, "rev-parse", "refs/remotes/origin/main")
    assert "O2.txt" not in changed(local, base, "feat")

def test_the_verdict_key_and_the_printed_base_are_one_computation(behind_and_ahead, monkeypatch):
    """`gate_verdict.py` keys a verdict on the base; a key from another base than the diff
    the agent reviewed would reuse a verdict over a different diff."""
    monkeypatch.chdir(behind_and_ahead)
    tip, base = gate_verdict.ends("feat", "main")
    assert tip == git(behind_and_ahead, "rev-parse", "refs/heads/feat")
    assert base == base_of(behind_and_ahead, "feat")


def test_the_unpushed_main_group_keeps_its_origin_basis(behind_and_ahead, monkeypatch):
    """Its target is local `main` itself, so the newest common ancestor with local `main` would
    be `HEAD` and the group's diff empty."""
    monkeypatch.chdir(behind_and_ahead)
    tip, base = gate_verdict.ends("unpushed-main", "main")
    assert tip == git(behind_and_ahead, "rev-parse", "HEAD")
    assert base == git(behind_and_ahead, "merge-base", "refs/remotes/origin/main", "HEAD")
    assert base != tip


def test_the_security_gate_skips_a_branch_whose_only_match_is_upstream_work(behind_and_ahead):
    """`security_map_filter.py` reads the same base: the upstream `scripts/upstream.sh` matches
    the map's one glob, and the branch touched only a doc."""
    p = script(behind_and_ahead, "security_map_filter.py", "feat", "main")
    assert p.returncode == 3, (p.stdout, p.stderr)
    assert p.stdout.startswith("SKIP feat"), p.stdout


def test_the_security_gate_still_spawns_on_the_branchs_own_match(behind_and_ahead):
    git(behind_and_ahead, "switch", "-q", "feat")
    commit(behind_and_ahead, "scripts/feature.sh")
    git(behind_and_ahead, "switch", "-q", "main")
    p = script(behind_and_ahead, "security_map_filter.py", "feat", "main")
    assert p.returncode == 0, (p.stdout, p.stderr)
    assert p.stdout.startswith("SPAWN feat"), p.stdout


@pytest.mark.parametrize("args", [("<branch>", "main"), ("feat", "<default branch>"), ("", "main"),
                                  ("feat",), ("feat", "main", "extra")])
def test_base_refuses_an_unwritten_operand_with_exit_3(behind_and_ahead, args):
    p = script(behind_and_ahead, "feature_branch.py", "base", *args)
    assert p.returncode == 3, (p.stdout, p.stderr)
    assert "BASE:" not in p.stdout


def test_base_stops_with_exit_2_on_a_branch_git_cannot_read(behind_and_ahead):
    p = script(behind_and_ahead, "feature_branch.py", "base", "nosuch", "main")
    assert p.returncode == 2 and "BASE:" not in p.stdout
    assert "refs/heads/nosuch" in p.stderr



def test_step_3a_reads_only_the_branchs_lines_from_its_base(clone, tmp_path):
    """Step 2a step 3a's ignored-file check diffs from its BASE too: an upstream line reading a
    gitignored file raised the question as though the branch had written it (the round's lens A)."""
    up, local = clone
    commit(up, ".gitignore", ".env.local\n")
    commit(up, "app/cfg.py", 'load(".env.local")\n')
    git(local, "fetch", "-q")
    wt = tmp_path / "wt"
    git(local, "worktree", "add", "-q", "-b", "feat", str(wt), "refs/remotes/origin/main")
    commit(wt, "notes.md", "doc\n")
    (wt / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
    base = base_of(local, "feat")
    def check(b):
        return script(local, "ignored_refs.py", str(wt), b, "--branch", "feat")
    assert check("main").returncode == 1, "premise: from local main the upstream line is read"
    p = check(base)
    assert p.returncode == 0, (p.stdout, p.stderr)
    p = check("<base>")
    assert p.returncode == 3 and "placeholder not substituted" in p.stderr, (
        "an unwritten <base> is refused as a placeholder (exit 3), not handed to git", p.stderr)

# ── the runner text ────────────────────────────────────────────────────────────────────────

def _runner_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in [CLOSE_DIR / "SKILL.md", *sorted((CLOSE_DIR / "steps").glob("*.md"))])


def test_no_runner_diff_of_a_branch_starts_three_dots_from_local_main():
    """The one mention left is the note's refusal of it."""
    text = _runner_text()
    hits = [m.start() for m in re.finditer(re.escape("<default branch>...refs/heads/<branch>"), text)]
    refusal = "Not `<default branch>...refs/heads/<branch>`: a local `<default branch>` behind `origin`"
    assert text.count(refusal) == 1
    assert hits == [text.index(refusal) + len("Not `")], hits


def test_the_runner_names_the_base_command_with_its_exits():
    text = text_of(CLOSE_DIR / "SKILL.md")
    step = text[text.index("### 2a. Feature Branches"):text.index("### 2b. Prevention Convention Check")]
    line = next(ln for ln in step.splitlines() if ln.startswith("1. "))
    assert line.startswith('1. `python3 sysop/scripts/feature_branch.py base "<branch>" "<default branch>"`'
                           " prints `BASE: <sha>`")
    assert "write that sha as `<base>` in every Step 2 command for this branch" in line, (
        "the only sentence that says what `<base>` is elsewhere (the round's lens B, F5)")
    assert "**Exit 2**: stop and show its stderr." in line
    assert "`python3 sysop/scripts/git_ro.py . log <base>..refs/heads/<branch> " in line
    assert 'python3 sysop/scripts/ignored_refs.py "<workspace>" "<base>" --branch "<branch>"' in step


def test_the_update_line_names_yes_for_a_non_interactive_shell():
    """`Q-774`: the instruction to run the updater, which stops at `Proceed?` without a
    terminal, names `--yes` as every shipped script message does."""
    text = text_of(CLOSE_DIR / "SKILL.md")
    assert ("If one is missing, stop and run `sysop/scripts/sysop-update.sh` "
            "(with `--yes` in a non-interactive shell).") in text
