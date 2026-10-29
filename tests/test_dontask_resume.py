"""`/review-close`'s resume under `dontAsk` (`Q-665`, Phase 422): Step 3b onward and Rule B.

Phase 421 made the prepare (Steps 1 to 3c) run headless with no denial; Phase 422 takes the rest.
Its baseline night (`tools/phase422_night_resume_baseline.*`) met three denials on the shipped
text, and its probes (`tools/phase422_probe_log.jsonl`) found the others a one-branch night cannot
reach: a quoted `$(…)` (`workspace_locate.py`'s old arguments), `git rev-parse --verify --quiet
… || echo`, `rm`, `mkdir -p`, `git rev-list … --not`, `git rev-list --left-right`, `git
ls-remote`, and a `; echo "$?"` tail. Each became a call a seeded rule admits:

* `workspace_locate.py "<branch>"` reads `git worktree list` and the prefix itself;
* `close_state.py strip-links` is Step 3b's symlink strip, Step 1a's downgrade rule as one call;
* `git_check.py published` is Step 4a item 1's published test;
* `pending_doc_collect.py consume` and `quarantine` are Step 4c's two file moves;
* Rule B and every Step 4 commit chain their write after a `git_check.py` check with `&&`.

Each script is run as a subprocess in a scratch repository. The last section guards the skills'
side: the resume's commands carry none of the denied shapes, and each replacement call is there.
`steps/4a-append.md` was left out until Phase 425 (`Q-629`): its stage extraction used `mktemp -d`,
`>` redirects and `comm … <(sort …)`, and is `resolve_append_conflict.py` now, so the scan reads it
with the rest.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from skill_runner_text import text_of

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "core" / "companion" / "scripts"
SKILLS = REPO / "core" / "skills"
GIT_ENV = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                        "WORKTREE_PREFIX")}
ID = ("-c", "user.email=t@t", "-c", "user.name=t")


def g(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, check=True, capture_output=True,
                          text=True).stdout.strip()


def run(script: str, cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    # A timeout and no stdin, as `test_dontask_check_scripts.py` gives its own: a hang measures
    # nothing.
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=cwd,
                          env={**GIT_ENV, **(env or {})},
                          capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "proj"
    r.mkdir()
    g(r, "init", "-q", "-b", "main")
    (r / ".gitignore").write_text(".venv/\nsysop/runtime/\n")
    (r / ".venv").mkdir()
    g(r, "add", ".gitignore")
    g(r, *ID, "commit", "-qm", "base")
    return r


# --- git_check.py published -------------------------------------------------------------------

def test_published_prints_the_remote_branchs_sha(repo: Path) -> None:
    sha = g(repo, "rev-parse", "HEAD")
    g(repo, "update-ref", "refs/remotes/origin/feat/x", sha)
    r = run("git_check.py", repo, "published", "feat/x")
    assert (r.returncode, r.stdout.strip()) == (0, sha)


def test_published_reads_local_only_without_a_remote_branch(repo: Path) -> None:
    g(repo, "branch", "feat/x")             # a local branch of the name is not a published one
    r = run("git_check.py", repo, "published", "feat/x")
    assert (r.returncode, r.stdout.strip()) == (1, "(local-only)")


def test_published_is_not_fooled_by_a_tag_or_local_branch_spelled_as_the_remote(repo: Path) -> None:
    g(repo, "tag", "origin/feat/x")
    g(repo, "branch", "origin/feat/x")
    r = run("git_check.py", repo, "published", "feat/x")
    assert (r.returncode, r.stdout.strip()) == (1, "(local-only)")


@pytest.mark.parametrize("operand", ["<branch>", "", "  "])
def test_published_refuses_a_placeholder_rather_than_reading_local_only(repo: Path,
                                                                        operand: str) -> None:
    r = run("git_check.py", repo, "published", operand)
    assert r.returncode == 3 and "(local-only)" not in r.stdout, r.stdout


def test_published_outside_a_repository_could_not_measure(tmp_path: Path) -> None:
    r = run("git_check.py", tmp_path, "published", "feat/x")
    assert r.returncode == 2 and r.stdout.startswith("STOP:"), r.stdout


# --- workspace_locate.py "<branch>" -----------------------------------------------------------

def test_locate_with_the_branch_alone_reads_the_worktree_listing_itself(repo: Path) -> None:
    wt = repo.parent / "proj-T-1"
    g(repo, "worktree", "add", "-q", str(wt), "-b", "feat/T-1")
    r = run("workspace_locate.py", repo, "feat/T-1")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"workspace={wt.resolve()} shape=worktree", r.stdout


def test_locate_discovers_a_sibling_by_the_repository_name(repo: Path) -> None:
    """The prefix defaults to the repository's directory name, as the old
    `${WORKTREE_PREFIX:-$(basename …)}` argument did: a clone at `proj-T-2` is found."""
    clone = repo.parent / "proj-T-2"
    g(repo.parent, "clone", "-q", str(repo), str(clone))
    g(clone, "checkout", "-q", "-b", "feat/T-2")
    r = run("workspace_locate.py", repo, "feat/T-2")
    assert r.stdout.strip() == f"workspace={clone} shape=discovered", r.stdout


def test_locate_takes_the_prefix_from_worktree_prefix(repo: Path) -> None:
    """`WORKTREE_PREFIX` ranks the prefixed siblings first: with two clones on the branch, the
    prefixed one wins, and without the variable the alphabetically first does."""
    for name in ("aaa-T-3", "zzz-T-3"):
        d = repo.parent / name
        g(repo.parent, "clone", "-q", str(repo), str(d))
        g(d, "checkout", "-q", "-b", "feat/T-3")
    plain = run("workspace_locate.py", repo, "feat/T-3")
    pref = run("workspace_locate.py", repo, "feat/T-3", env={"WORKTREE_PREFIX": "zzz"})
    assert plain.stdout.strip().startswith(f"workspace={repo.parent / 'aaa-T-3'} "), plain.stdout
    assert pref.stdout.strip().startswith(f"workspace={repo.parent / 'zzz-T-3'} "), pref.stdout


def test_locate_still_takes_the_three_argument_form(repo: Path) -> None:
    wt = repo.parent / "proj-T-4"
    g(repo, "worktree", "add", "-q", str(wt), "-b", "feat/T-4")
    listing = g(repo, "worktree", "list", "--porcelain")
    r = run("workspace_locate.py", repo, "feat/T-4", listing, "proj")
    assert r.stdout.strip() == f"workspace={wt.resolve()} shape=worktree", r.stdout


def test_locate_ignores_an_inherited_git_dir(repo: Path, tmp_path: Path) -> None:
    """Lens B's P01: a `GIT_DIR` inherited from a hook or a wrapper must not point the listing at
    another repository."""
    wt = repo.parent / "proj-T-5"
    g(repo, "worktree", "add", "-q", str(wt), "-b", "feat/T-5")
    other = tmp_path / "other"
    g(tmp_path, "init", "-q", str(other))
    r = run("workspace_locate.py", repo, "feat/T-5", env={"GIT_DIR": str(other / ".git")})
    assert r.stdout.strip() == f"workspace={wt.resolve()} shape=worktree", (r.stdout, r.stderr)


@pytest.mark.parametrize("args", [(), ("feat/x", "listing")])
def test_locate_refuses_a_wrong_operand_count(repo: Path, args) -> None:
    assert run("workspace_locate.py", repo, *args).returncode == 2


def test_locate_outside_a_repository_says_so(tmp_path: Path) -> None:
    r = run("workspace_locate.py", tmp_path, "feat/x")
    assert r.returncode == 2 and "git worktree list" in r.stderr, (r.stdout, r.stderr)


# --- close_state.py strip-links ---------------------------------------------------------------

@pytest.fixture
def linked(repo: Path) -> Path:
    wt = repo.parent / "proj-T-9"
    g(repo, "worktree", "add", "-q", str(wt), "-b", "feat/T-9")
    os.symlink("../proj/.venv", wt / ".venv")            # tooling: target ignored by main
    os.symlink(str(repo / ".gitignore"), wt / "tracked-link")   # target tracked: work
    (wt / "work.txt").write_text("x\n")                  # a real untracked file
    return wt


def test_strip_links_removes_only_a_link_whose_target_main_ignores(repo: Path,
                                                                   linked: Path) -> None:
    r = run("close_state.py", repo, "strip-links", str(linked))
    assert r.returncode == 0, r.stdout
    assert r.stdout.splitlines() == ["REMOVED LINK: .venv", "STRIP-LINKS: 1 removed"], r.stdout
    assert not os.path.lexists(linked / ".venv")
    assert (repo / ".venv").is_dir(), "the link's target was removed, not the link"
    assert os.path.islink(linked / "tracked-link") and (linked / "work.txt").is_file()
    # The real file still blocks the unforced remove the step runs next.
    rm = subprocess.run(["git", "worktree", "remove", str(linked)], cwd=repo, env=GIT_ENV,
                        capture_output=True, text=True)
    assert rm.returncode != 0 and linked.is_dir()


def test_strip_links_lets_the_unforced_remove_through_a_lone_tooling_link(repo: Path) -> None:
    wt = repo.parent / "proj-T-8"
    g(repo, "worktree", "add", "-q", str(wt), "-b", "feat/T-8")
    os.symlink("../proj/.venv", wt / ".venv")
    assert run("close_state.py", repo, "strip-links", str(wt)).returncode == 0
    g(repo, "worktree", "remove", str(wt))
    assert not wt.exists()


def test_strip_links_sees_untracked_links_whatever_the_config_says(repo: Path,
                                                                   linked: Path) -> None:
    """`status.showUntrackedFiles=no` hides untracked files from a plain `git status`; the
    strip reads them anyway (Phase 421's round, lens A's H2, on Step 1a's classifier)."""
    g(linked, "config", "status.showUntrackedFiles", "no")
    r = run("close_state.py", repo, "strip-links", str(linked))
    assert "REMOVED LINK: .venv" in r.stdout, r.stdout


def test_strip_links_refuses_the_primary_checkout(repo: Path) -> None:
    os.symlink(".venv", repo / "venv-link")
    r = run("close_state.py", repo, "strip-links", str(repo))
    assert r.returncode == 2 and "primary checkout" in r.stdout, r.stdout
    assert os.path.islink(repo / "venv-link")


def test_strip_links_refuses_a_directory_git_does_not_list(repo: Path, tmp_path: Path) -> None:
    other = tmp_path / "elsewhere"
    other.mkdir()
    os.symlink(str(repo / ".venv"), other / ".venv")
    r = run("close_state.py", repo, "strip-links", str(other))
    assert r.returncode == 2 and "not a worktree" in r.stdout, r.stdout
    assert os.path.islink(other / ".venv")


@pytest.mark.parametrize("operand", ["<worktree-path>", ""])
def test_strip_links_refuses_a_placeholder(repo: Path, operand: str) -> None:
    assert run("close_state.py", repo, "strip-links", operand).returncode == 2


def test_strip_links_keeps_a_link_into_the_worktree_itself(repo: Path) -> None:
    """Lens A, L2: a worktree under a directory the primary ignores (`.claude/worktrees/x`)
    makes every untracked link's target ignored, so a user's `alias.md -> README.md` read as
    tooling, was removed, and the unforced remove then succeeded with it gone."""
    (repo / ".gitignore").write_text(".venv/\nwt/\n")
    g(repo, *ID, "commit", "-qam", "ignore wt")
    wt = repo / "wt" / "x"
    g(repo, "worktree", "add", "-q", str(wt), "-b", "feat/x")
    os.symlink("README.md", wt / "alias.md")
    (wt / "README.md").write_text("hi\n")
    g(wt, "add", "README.md"); g(wt, *ID, "commit", "-qm", "readme")
    r = run("close_state.py", repo, "strip-links", str(wt))
    assert r.returncode == 0 and "STRIP-LINKS: 0 removed" in r.stdout, r.stdout
    assert os.path.islink(wt / "alias.md")


def test_strip_links_reports_a_link_it_cannot_remove(repo: Path, linked: Path) -> None:
    """Lens A, L1: a `PermissionError` was a traceback at exit 1, an exit the step names no
    arm for; it is a `STOP:` line at exit 2."""
    linked.chmod(0o555)                      # the link's own directory cannot be written
    try:
        r = run("close_state.py", repo, "strip-links", str(linked))
    finally:
        linked.chmod(0o755)
    assert r.returncode == 2 and r.stdout.splitlines()[-1].startswith("STOP: could not remove:"), r.stdout
    assert "Traceback" not in r.stderr


def test_strip_links_removes_a_file_link_and_never_its_target(repo: Path) -> None:
    """Lens B's P06: no test stripped a link to a FILE, so unlinking the resolved target in
    place of the link deleted the primary's ignored `.env` and still printed `REMOVED LINK`."""
    (repo / ".gitignore").write_text(".venv/\n.env\n")
    g(repo, *ID, "commit", "-qam", "ignore .env")
    (repo / ".env").write_text("SECRET=1\n")
    wt = repo.parent / "proj-T-7"
    g(repo, "worktree", "add", "-q", str(wt), "-b", "feat/T-7")
    os.symlink("../proj/.env", wt / ".env-link")
    r = run("close_state.py", repo, "strip-links", str(wt))
    assert "REMOVED LINK: .env-link" in r.stdout, r.stdout
    assert not os.path.lexists(wt / ".env-link")
    assert (repo / ".env").read_text() == "SECRET=1\n", "the link's target was deleted"


def test_strip_links_takes_a_relative_operand(repo: Path, linked: Path) -> None:
    """Lens B (LOW): a relative operand reached `check-ignore` as a `../` path and printed
    `0 removed` over a link it should have removed."""
    r = run("close_state.py", repo, "strip-links", os.path.relpath(linked, repo))
    assert "REMOVED LINK: .venv" in r.stdout, r.stdout


def test_strip_links_reads_a_name_with_a_space(repo: Path) -> None:
    """Lens B's P09: without `-z`, porcelain quotes a name with a space, and the quoted name
    names no file."""
    wt = repo.parent / "proj-T-6"
    g(repo, "worktree", "add", "-q", str(wt), "-b", "feat/T-6")
    os.symlink("../proj/.venv", wt / "my venv")
    (repo / ".gitignore").write_text(".venv/\n")
    r = run("close_state.py", repo, "strip-links", str(wt))
    assert "REMOVED LINK: my venv" in r.stdout, r.stdout


def test_strip_links_stops_when_status_fails(repo: Path, linked: Path) -> None:
    (linked / ".git").unlink()                       # the worktree's link to its git dir, gone
    (linked / ".git").write_text("gitdir: /nonexistent\n")
    r = run("close_state.py", repo, "strip-links", str(linked))
    assert r.returncode == 2 and r.stdout.startswith("STOP:"), r.stdout
    assert os.path.islink(linked / ".venv")


# --- pending_doc_collect.py consume / quarantine ----------------------------------------------

@pytest.fixture
def docs(tmp_path: Path) -> Path:
    root = tmp_path / "main"
    d = root / "sysop" / "runtime" / "pending-docs"
    d.mkdir(parents=True)
    for n in ("a.md", "b.md", "held.md"):
        (d / n).write_text(f"---\nbranch: {n}\n---\n")
    return root


PD = "sysop/runtime/pending-docs"


def test_consume_deletes_only_the_named_docs(docs: Path) -> None:
    r = run("pending_doc_collect.py", docs, "consume", "a.md", "b.md")
    assert r.returncode == 0, r.stdout
    assert sorted(os.listdir(docs / PD)) == ["held.md"]
    assert "CONSUMED: a.md, b.md" in r.stdout and "DIRECTORY: kept" in r.stdout, r.stdout


def test_consume_removes_the_directory_once_empty(docs: Path) -> None:
    r = run("pending_doc_collect.py", docs, "consume", "a.md", "b.md", "held.md")
    assert r.returncode == 0 and not (docs / PD).exists(), r.stdout
    assert f"DIRECTORY: removed {PD}/ (empty)" in r.stdout


def test_consume_keeps_the_directory_while_quarantine_holds_a_doc(docs: Path) -> None:
    assert run("pending_doc_collect.py", docs, "quarantine", "held.md").returncode == 0
    r = run("pending_doc_collect.py", docs, "consume", "a.md", "b.md")
    assert r.returncode == 0 and (docs / PD / "quarantine" / "held.md").is_file(), r.stdout


def test_consume_exits_5_on_a_name_that_matched_no_doc(docs: Path) -> None:
    """Phase 422's round (lens A, M3): a mistyped name exited 0 and left its consolidated doc
    behind, and the step stopped only on a non-zero exit."""
    r = run("pending_doc_collect.py", docs, "consume", "a.md", "gone.md")
    assert r.returncode == 5 and "ALREADY ABSENT: gone.md" in r.stdout, r.stdout
    assert not (docs / PD / "a.md").exists(), "the names that did match are still consumed"


@pytest.mark.parametrize("name", ["Convention-Candidates.md", "CONVENTION-CANDIDATES.MD", "a.MD"])
def test_consume_folds_case_before_refusing(docs: Path, name: str) -> None:
    """Lens A, M2: on a case-insensitive filesystem a case variant names the review round's own
    file. `a.MD` is a legal name and is not refused for its suffix's case."""
    (docs / PD / "convention-candidates.md").write_text("candidates\n")
    r = run("pending_doc_collect.py", docs, "consume", name)
    if name == "a.MD":
        assert r.returncode in (0, 5), r.stdout
    else:
        assert r.returncode == 3, r.stdout
        assert (docs / PD / "convention-candidates.md").read_text() == "candidates\n"


@pytest.mark.parametrize("key", ["hold: waiting on the human", "held_since: 2026-10-26"])
def test_consume_refuses_a_held_doc_and_deletes_nothing(docs: Path, key: str) -> None:
    """Lens A, M2: a doc Step 4c item 1c holds must survive item 6 (BeanRider ISSUE-0050)."""
    (docs / PD / "held.md").write_text(f"---\nbranch: b\n{key}\n---\nbody\n")
    r = run("pending_doc_collect.py", docs, "consume", "a.md", "held.md")
    assert r.returncode == 3 and "held.md" in r.stdout, r.stdout
    assert (docs / PD / "held.md").is_file() and (docs / PD / "a.md").is_file()


def test_consume_does_not_read_hold_outside_the_frontmatter(docs: Path) -> None:
    (docs / PD / "b.md").write_text("---\nbranch: b\n---\nhold: this line is body text\n")
    r = run("pending_doc_collect.py", docs, "consume", "b.md")
    assert r.returncode == 0 and not (docs / PD / "b.md").exists(), r.stdout


@pytest.mark.parametrize("bad", ["../a.md", "sub/a.md", ".hidden.md", "a.txt", "<doc>.md", "",
                                 "convention-candidates.md"])
def test_consume_refuses_anything_but_a_bare_doc_name_before_deleting(docs: Path, bad: str) -> None:
    r = run("pending_doc_collect.py", docs, "consume", "a.md", bad)
    assert r.returncode == 3, r.stdout
    assert (docs / PD / "a.md").is_file(), "a valid operand was deleted beside a refused one"


def test_consume_needs_the_main_checkouts_directory(tmp_path: Path) -> None:
    assert run("pending_doc_collect.py", tmp_path, "consume", "a.md").returncode == 4


def test_consume_fails_loudly_when_a_doc_cannot_be_removed(docs: Path) -> None:
    (docs / PD / "a.md").unlink()
    (docs / PD / "a.md").mkdir()                      # a directory of that name cannot be unlinked
    r = run("pending_doc_collect.py", docs, "consume", "a.md")
    assert r.returncode == 1 and "FAILED" in r.stdout, r.stdout


def test_quarantine_moves_a_doc_and_never_overwrites(docs: Path) -> None:
    r = run("pending_doc_collect.py", docs, "quarantine", "a.md")
    assert r.returncode == 0 and (docs / PD / "quarantine" / "a.md").is_file(), r.stdout
    (docs / PD / "a.md").write_text("second\n")
    r = run("pending_doc_collect.py", docs, "quarantine", "a.md")
    assert r.returncode == 1 and "nothing was overwritten" in r.stdout, r.stdout
    assert (docs / PD / "a.md").read_text() == "second\n"
    assert (docs / PD / "quarantine" / "a.md").read_text() == "---\nbranch: a.md\n---\n"


def test_quarantine_refuses_the_review_rounds_file_in_any_case(docs: Path) -> None:
    """Lens B's P03."""
    (docs / PD / "convention-candidates.md").write_text("c\n")
    for name in ("convention-candidates.md", "Convention-Candidates.md"):
        assert run("pending_doc_collect.py", docs, "quarantine", name).returncode == 3
    assert (docs / PD / "convention-candidates.md").is_file()


def test_quarantine_refuses_a_symlinked_doc(docs: Path, tmp_path: Path) -> None:
    """Lens B's P04: a link would move the pointer and leave the content where it was."""
    (tmp_path / "elsewhere.md").write_text("x\n")
    os.symlink(str(tmp_path / "elsewhere.md"), docs / PD / "link.md")
    r = run("pending_doc_collect.py", docs, "quarantine", "link.md")
    assert r.returncode == 1 and os.path.islink(docs / PD / "link.md"), r.stdout


def test_consume_reports_a_directory_it_cannot_list(docs: Path) -> None:
    """Lens B's P08: an unreadable directory must not read as empty."""
    d = docs / PD
    d.chmod(0o333)                                   # writable and searchable, not listable
    try:
        r = run("pending_doc_collect.py", docs, "consume", "a.md")
    finally:
        d.chmod(0o755)
    assert r.returncode == 1 and "could not be listed" in r.stdout, r.stdout
    assert d.is_dir(), "an unlistable directory was removed as empty"


def test_quarantine_refuses_a_missing_doc_and_a_path(docs: Path) -> None:
    assert run("pending_doc_collect.py", docs, "quarantine", "nope.md").returncode == 1
    assert run("pending_doc_collect.py", docs, "quarantine", "../a.md").returncode == 3


# --- the skills' side -------------------------------------------------------------------------

def _fenced_commands(text: str) -> list[tuple[int, str]]:
    """Each non-comment line inside a fence labelled as shell, with its line number. An unlabelled
    fence is a template (Step 8's report), not a command."""
    out, inside, shell = [], False, False
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip().lstrip(">").strip()
        if s.startswith("```"):
            if not inside:
                inside, shell = True, s[3:].strip() in ("bash", "sh", "shell", "zsh")
            else:
                inside = False
            continue
        if inside and shell and s and not s.startswith("#"):
            out.append((n, s))
    return out


def _resume_span() -> str:
    """The spliced core from Step 3b to its end, every arm it loads included."""
    text = text_of(SKILLS / "review-close" / "SKILL.md")
    assert text.count("\n## Step 3b:") == 1, "COULD NOT LOCATE Step 3b; nothing was measured"
    span = text.split("\n## Step 3b:")[1]
    for arm in RESUME_ARMS:
        assert f'close_arms.py loaded "<close-id>" {arm} ' in span, f"steps/{arm}.md is not in the span"
    return span


def _rule_b() -> str:
    text = text_of(SKILLS / "_shared" / "main-push-guard.md")
    start, end = text.index("## Rule B"), text.index("## Rule C")
    assert end > start
    return text[start:end]


RESUME_ARMS = ("3b-collect-exit", "3b-rollback", "4-pre-pr", "4a-append", "4a-fix", "4a-post-failure",
               "4a-post-prescan", "4a-published", "4b-batches", "4c-check-exit", "4c-unmerged", "4d-direct", "4d-pr", "6-direct",
               "6-pr-cleanup", "6-pr-gate")

#: Each shape a probe or a night measured denied under `dontAsk` (Phases 420-422).
DENIED_SHAPES = {
    "a quoted $(…)": re.compile(r'"[^"]*\$\('),
    "a variable assigned from $(…)": re.compile(r"^\w+=\S*\$\("),
    "a || { … } or || exit tail": re.compile(r"\|\|\s*(\{|exit\b)"),
    "a test or [ ] check": re.compile(r"^(test|if|\[)\s|;\s*then\b"),
    "a case statement": re.compile(r"^case\b"),
    "an appended echo of $?": re.compile(r";\s*echo\b[^#]*\$\?"),
    "an rm, rmdir or mkdir": re.compile(r"^(rm|rmdir|mkdir)\b|&&\s*(rm|rmdir|mkdir)\b"),
    "a while-read loop": re.compile(r"\|\s*while\b"),
    "git rev-parse --verify --quiet": re.compile(r"^git\s+rev-parse\b.*--quiet\b"),
    "a bare git rev-list --not": re.compile(r"^git\s+rev-list\b.*\s--not\b"),
    "a bare git rev-list --left-right": re.compile(r"^git\s+rev-list\b.*--left-right"),
    "git ls-remote": re.compile(r"\bgit\s+ls-remote\b"),
    "git -C": re.compile(r"\bgit\s+-C\b"),
    "git commit --amend": re.compile(r"\bgit\s+commit\b.*--amend\b"),
    "a forced worktree remove": re.compile(r"\bgit\s+worktree\s+remove\b.*(\s--force\b|\s-f\b)"),
    # Phase 425 (`Q-629`): the shapes `steps/4a-append.md`'s stage extraction used.
    "mktemp": re.compile(r"\bmktemp\b"),
    "a process substitution": re.compile(r"<\("),
    # `2>/dev/null` and `>/dev/null` were measured admitted; `2>&1` writes no file and is spared
    # unmeasured. Read through `_redirect_view` (lens B, L1). Lens B's M4: no space is needed
    # before the operator, and `>|` is the same write.
    "a redirect into a file": re.compile(r"(?<![-=>])(?:\d?>>?\|?|&>)\s*(?!/dev/null\b|&\d)[^\s&;|]"),
    "a tee into a file": re.compile(r"\|\s*tee\b"),
}


def _redirect_view(line: str) -> str:
    """The line as the redirect pattern reads it: `<placeholder>` operands and a trailing comment
    removed, so `"<branch 2>"` and `# must be > 0` are not read as redirects (lens B, L1)."""
    return re.sub(r"\s+#[^\"']*$", "", re.sub(r"<[^<>\n]*>", "X", line))


def _shape_hits(name: str, pat: "re.Pattern[str]", line: str) -> bool:
    return bool(pat.search(_redirect_view(line) if name == "a redirect into a file" else line))

#: A command written inline in prose for the runner to run: a denied command word with operands.
#: Bare words (`mkdir`, `git commit`) are prose naming a form, not a command.
INLINE_COMMAND = re.compile(r"`((?:mkdir|rm|rmdir|mv|git\s+commit\s+-\S*|git\s+ls-remote|"
                            r"git\s+update-ref|git\s+worktree\s+remove\s+\S+\s+--force)\s[^`]*)`")
#: Inline commands the resume names on purpose, each never run by the close.
INLINE_KNOWN = {
    # 3b-rollback's provenance quotes the form it replaced.
    'rm -f sysop/runtime/pending-docs/$(basename "$f")',
    # 4d-pr's advice for a human after a squash is reverted, outside any close.
    "git update-ref -d refs/sysop/merged-pr-heads/<PR>",
}


def test_the_resume_names_no_denied_command_inline() -> None:
    """Lens B's H1: Step 4c's second quarantine site said `mkdir -p …` in prose, and the fenced
    scan could not see it."""
    found = [m.group(1) for t in (_resume_span(), _rule_b()) for m in INLINE_COMMAND.finditer(t)
             if m.group(1) not in INLINE_KNOWN]
    assert not found, found


def test_the_inline_scan_sees_the_line_it_replaced() -> None:
    line = "create the directory first (`mkdir -p sysop/runtime/pending-docs/quarantine`; nothing"
    assert INLINE_COMMAND.search(line)
    assert INLINE_COMMAND.search("stage them and `git commit --amend --no-edit` before")
    assert INLINE_COMMAND.search("commit them as `git commit -m \"docs: x\"`, unchained")
    assert not INLINE_COMMAND.search("no `mkdir` here, and `git commit` is named only")


def test_the_worktree_remove_is_the_unforced_line() -> None:
    """Lens B's H2: a trailing `--force` passed every guard, and a forced remove deletes a
    worktree's untracked work (BeanRider ISSUE-0016). The remove is pinned whole."""
    removes = [line for _, line in _fenced_commands(_resume_span()) if "worktree remove" in line]
    assert removes == ['git worktree remove "<worktree-path>"'], removes


@pytest.mark.parametrize("where", ["resume", "rule B"])
def test_the_resume_prescribes_no_shape_dontask_denies(where: str) -> None:
    span = _resume_span() if where == "resume" else _rule_b()
    found = [(n, name, line) for n, line in _fenced_commands(span)
             for name, pat in DENIED_SHAPES.items() if _shape_hits(name, pat, line)]
    assert not found, "\n".join(f"{where}:{n}: {name}: {line}" for n, name, line in found)


@pytest.mark.parametrize("name,line", [
    ("a quoted $(…)", 'python3 sysop/scripts/workspace_locate.py "b" "$(git worktree list --porcelain)"'),
    ("a variable assigned from $(…)", 'RUN_ID="$(date -u +%Y%m%dT%H%M%S)"'),
    ("a || { … } or || exit tail", 'python3 sysop/scripts/validate_tasks.py || { echo x; exit 1; }'),
    ("a test or [ ] check", 'test "$(git branch --show-current)" = "x" || exit 1'),
    ("a test or [ ] check", 'if [ "$(git rev-parse origin/main)" != "x" ]; then'),
    ("a case statement", 'case "<branch>" in'),
    ("an appended echo of $?", 'git fetch origin "+refs/heads/x:refs/remotes/origin/x"; echo "--- exit: $?"'),
    ("an rm, rmdir or mkdir", "rm sysop/runtime/pending-docs/x.md"),
    ("an rm, rmdir or mkdir", "mkdir -p sysop/runtime/pending-docs/quarantine"),
    ("a while-read loop", 'git status --porcelain | while IFS= read -r line; do'),
    ("git rev-parse --verify --quiet", 'git rev-parse --verify --quiet "refs/remotes/origin/x" || echo "(local-only)"'),
    ("a bare git rev-list --not", 'git rev-list --count origin/main..main --not "refs/heads/x"'),
    ("a bare git rev-list --left-right", "git rev-list --left-right --count origin/main...HEAD"),
    ("git ls-remote", "git ls-remote --heads origin x"),
    ("git -C", 'git -C "<worktree-path>" status --porcelain'),
    ("git ls-remote", "git  ls-remote --heads origin x"),
    ("git commit --amend", "git commit --amend --no-edit"),
    ("a forced worktree remove", 'git worktree remove "<worktree-path>" --force'),
    ("mktemp", 'STAGES=$(mktemp -d "${TMPDIR:-/tmp}/sysop-stages-XXXXXX") && echo "STAGES=$STAGES"'),
    ("a process substitution", 'comm -23 <(sort "$STAGES/base.md") <(sort "$STAGES/ours.md")'),
    ("a redirect into a file", 'git show :1:tasks/index.yml > "$STAGES/base.yml"'),
    ("a redirect into a file", "git show :2:tasks/notes.md >>notes.txt"),
    ("a redirect into a file", 'git show :2:tasks/index.yml>"$X/ours.yml"'),
    ("a redirect into a file", 'git show ":2:tasks/index.yml">ours.yml'),
    ("a redirect into a file", "git show :2:tasks/index.yml >| ours.yml"),
    ("a tee into a file", "git show :2:tasks/index.yml | tee ours.yml"),
])
def test_each_denied_shape_is_seen(name: str, line: str) -> None:
    """The scan's patterns, each against the line it replaced: a pattern that cannot see its
    own shape would leave the scan above green over a reverted step."""
    assert _shape_hits(name, DENIED_SHAPES[name], line), (name, line)


@pytest.mark.parametrize("line", [
    "git rev-parse HEAD 2>/dev/null",
    "python3 sysop/scripts/close_run.py class >/dev/null",
    "git status --porcelain 2>&1",
    'python3 sysop/scripts/claim_artifacts.py "<branch 1>" "<branch 2>"',
    "grep -c . f   # must be > 0",
])
def test_the_redirect_pattern_spares_what_was_measured_admitted(line: str) -> None:
    """The first two were measured admitted; `2>&1` writes no file; the last two are a placeholder
    and a comment, which lens B (L1) showed the first cut reading as redirects."""
    assert not _shape_hits("a redirect into a file", DENIED_SHAPES["a redirect into a file"], line), line


@pytest.mark.parametrize("line", [
    'python3 sysop/scripts/git_ro.py . rev-list --count origin/main..main --not "refs/heads/x"',
    'python3 sysop/scripts/git_ro.py . rev-list --left-right --count origin/main...HEAD',
    'git rev-parse --verify origin/main >/dev/null 2>&1 \\',
    'git branch -D "merge/review-close-x" 2>/dev/null || echo "already deleted"',
    'gh pr create --base main --head "merge/review-close-<close-id>" \\',
])
def test_an_admitted_line_is_not_flagged(line: str) -> None:
    hits = [name for name, pat in DENIED_SHAPES.items() if _shape_hits(name, pat, line)]
    assert not hits, (hits, line)


#: The calls that replaced a denied shape; one dropped or reverted is a denied call, and a span
#: that lost them all cannot pass the scan by being empty.
RESUME_CALLS = (
    'python3 sysop/scripts/workspace_locate.py "<branch name>"\n',
    'python3 sysop/scripts/close_state.py strip-links "<worktree-path>"',
    'git worktree remove "<worktree-path>"',
    'python3 sysop/scripts/git_check.py published "<branch>"',
    'python3 sysop/scripts/pending_doc_collect.py quarantine "<name>.md"',
    'python3 sysop/scripts/pending_doc_collect.py consume "<consolidated doc>.md"',
    'python3 sysop/scripts/git_ro.py . rev-list --count origin/<default branch>..<default branch> --not',
    'python3 sysop/scripts/git_ro.py . rev-list --left-right --count origin/<default branch>...HEAD',
    'git checkout -b "merge/review-close-<close-id>" <default branch>',
    'python3 sysop/scripts/git_check.py head-is "<integration branch>" && git push origin "refs/heads/<integration branch>"',
    'find sysop/runtime/close/ -maxdepth 2 -name AWAITING -o -maxdepth 2 -name STOPPED',
    'python3 sysop/scripts/git_check.py head-is "<approved branch name>" && git push origin "refs/heads/<approved branch name>"',
    'gh pr create --base <default branch> --head "<integration branch>"',
)

RULE_B_CALLS = (
    'python3 sysop/scripts/git_check.py head-is "<default branch>" && git fetch origin <default branch>',
    'python3 sysop/scripts/git_check.py ancestor "refs/remotes/origin/<default branch>" "refs/heads/<default branch>"',
    'git rev-parse "refs/heads/<default branch>"',
    'python3 sysop/scripts/git_check.py head-is "<default branch>" && git merge --no-edit',
    'python3 sysop/scripts/git_check.py head-is "<default branch>" && git push origin "<SHA>:<default branch>"',
    'git fetch origin <default branch> && python3 sysop/scripts/git_check.py ancestor "<SHA>" "refs/remotes/origin/<default branch>"',
)


def _live(text: str) -> str:
    """The text a runner acts on: fenced comment lines dropped (a commented-out call is no call,
    lens B's C05)."""
    out, inside = [], False
    for line in text.splitlines():
        s = line.strip().lstrip(">").strip()
        if s.startswith("```"):
            inside = not inside
        elif inside and s.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


def _call_pattern(call: str) -> re.Pattern:
    """A call, matched as a runner may legally requote it (lens B's X04, X05): a quoted word in
    either quote character, and a bare `<placeholder>` quoted or not. A quoted placeholder must
    stay quoted: unquoted, `<…>` is a redirection, which is what the quotes are for."""
    parts = []
    for tok in re.findall(r'"[^"]*"|\'[^\']*\'|\s+|[^\s"\']+', call):
        if tok.isspace():
            parts.append(r"\s+")
        elif tok[0] in "\"'":
            parts.append("[\"']" + re.escape(tok[1:-1]) + "[\"']")
        elif tok.startswith("<"):
            parts.append("[\"']?" + re.escape(tok) + "[\"']?")
        else:
            parts.append(re.escape(tok))
    return re.compile("".join(parts))


def test_each_replacement_call_is_in_the_resume() -> None:
    span = _live(_resume_span() + text_of(SKILLS / "review-close" / "SKILL.md").split("\n## Step 1:")[0])
    for call in RESUME_CALLS:
        assert _call_pattern(call).search(span), f"the resume lost {call!r}"
    rule_b = _live(_rule_b())
    for call in RULE_B_CALLS:
        assert _call_pattern(call).search(rule_b), f"Rule B lost {call!r}"


@pytest.mark.parametrize("line,ok", [
    ('python3 sysop/scripts/git_check.py published "<branch>"', True),
    ("python3 sysop/scripts/git_check.py published '<branch>'", True),      # requoted (X05)
    ("python3 sysop/scripts/git_check.py published <branch>", False),       # a redirection
    ("#    python3 sysop/scripts/git_check.py published \"<branch>\"", False),
])
def test_the_call_check_takes_a_requoting_and_refuses_an_unquoting(line: str, ok: bool) -> None:
    text = _live("```bash\n" + line + "\n```")
    assert bool(_call_pattern('python3 sysop/scripts/git_check.py published "<branch>"').search(text)) is ok


#: The prose that routes each exit; a call whose exits are re-routed is a different step
#: (lens B's R04, R05, E01, E05 survived because only the calls were pinned).
ROUTING = (
    (_rule_b, "**Exit 0**: it has not; go to 4. **Exit 1**: it has; go to 3. **Exit 2 or 3**: stop."),
    (_rule_b, "**A non-zero exit: STOP.**"),
    (_rule_b, "**A non-zero exit**: the fetch failed, or the pushed SHA is not on"),
    (_rule_b, "**A non-zero exit the step does not route is a STOP**"),
    (_resume_span, "never read it as local-only, which takes the in-place rebase that damages a published branch. **Exit 2**: stop and show its line."),
    (_resume_span, "`STRIP-LINKS: <n> removed`. **Exit 2**: stop and show its line."),
    (_resume_span, "**Exit 5**: a name matched no doc, so a mistyped name left a consolidated doc behind; stop."),
)


@pytest.mark.parametrize("where,sentence", ROUTING, ids=[r[1][:40] for r in ROUTING])
def test_each_call_keeps_its_exit_routing(where, sentence: str) -> None:
    assert sentence in " ".join(where().split()), sentence


def test_every_step_4_commit_is_chained_after_its_rule_a_check() -> None:
    """Step 4's HARD RULE runs Rule A before every commit; under `dontAsk` the check and the
    commit are one call (`Q-710`), so each commit line opens with the check and `&&`. Before
    Step 4 (3c's filing) the check is the default branch's, written out; in Step 4, the merge
    target's."""
    texts = (_resume_span(), text_of(SKILLS / "review-close" / "steps" / "3c-signals.md"))
    commits = [line for t in texts for _, line in _fenced_commands(t)
               if re.search(r"\bgit commit\b", line)]
    assert len(commits) == 5, commits
    for line in commits:
        assert re.match(r'python3 sysop/scripts/git_check\.py head-is "(<merge target>|<default branch>)" && ',
                        line), line
        assert "||" not in line and ";" not in line, line


def test_the_hard_rule_gives_each_shape_its_check() -> None:
    span = text_of(SKILLS / "review-close" / "SKILL.md")
    flat = " ".join(span.split())
    for part in ('`python3 sysop/scripts/git_check.py head-is "<merge target>" && <the commit>`',
                 '`<default branch>` under `direct`, `merge/review-close-<close-id>` under the '
                 'integration-branch shape, and under the PR-reuse shape the literal branch name Step 2a approved'):
        assert part in flat, part
