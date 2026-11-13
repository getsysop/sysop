"""`Q-775` (Phase 485): which repository answers whether a tooling symlink's target is ignored.

An untracked symlink whose target is gitignored is tooling, not work (BeanRider ISSUE-0043).
Until Phase 485 every reader asked the main checkout, which ignores `.claude/worktrees/`, so a
link in a worktree there to the worktree's own tracked `README.md` read as tooling: Step 1a
said `MERGED`, `/sitrep` said clean, while `strip-links` kept the link as work. Wade's ruling
(2026-11-08): a target inside the workspace is asked of the workspace itself, any other of the
main checkout, `--branch` claims included. `_ignored_link.py` holds the rule; every reader
calls it, so one matrix here is the parity guard.
"""
import ast
import importlib
import os
import re
import subprocess
from pathlib import Path

import pytest

import _ignored_link as IL
import sitrep_survey as ss

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
_ENV = {k: v for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}


def _g(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=_ENV)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


@pytest.fixture
def fx(tmp_path):
    """A primary that ignores `.claude/worktrees/` and `.venv/`, a worktree inside that
    directory (`inner`) and one outside the primary (`outer`), each with its own `.venv/`."""
    p = tmp_path / "prim"
    p.mkdir()
    _g(p, "-c", "init.defaultBranch=main", "init", "-q")
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        _g(p, "config", k, v)
    (p / ".gitignore").write_text(".claude/worktrees/\n.venv/\nsysop/runtime/\n")
    (p / "README.md").write_text("r\n")
    _g(p, "add", "-A")
    _g(p, "commit", "-qm", "seed")
    _g(p, "worktree", "add", "-q", "-b", "inner", ".claude/worktrees/inner")
    _g(p, "worktree", "add", "-q", "-b", "outer", str(tmp_path / "outer"))
    spaces = {"inner": p / ".claude/worktrees/inner", "outer": tmp_path / "outer", "primary": p}
    for w in spaces.values():
        (w / ".venv").mkdir()
    return p, spaces


def _link(where: Path, name: str, target) -> str:
    (where / name).symlink_to(target)
    return name


# (link name, target relative to the workspace or "PRIMARY_VENV", tooling?) per workspace kind.
CASES = [
    ("self", "README.md", False),          # the workspace's own tracked file: work
    ("tonew", "new.txt", False),           # an untracked, unignored file there: work
    ("venvlink", ".venv", True),           # the workspace's own ignored directory: tooling
    ("pvenv", "PRIMARY_VENV", True),       # the main checkout's ignored `.venv`: tooling
]


@pytest.mark.parametrize("kind", ["inner", "outer", "primary"])
@pytest.mark.parametrize("name,target,tooling", CASES)
def test_the_rule(fx, kind, name, target, tooling):
    p, spaces = fx
    w = spaces[kind]
    (w / "new.txt").write_text("n\n")
    _link(w, name, (p / ".venv") if target == "PRIMARY_VENV" else target)
    assert IL.ignored_link(str(w), name, str(p)) is tooling


def test_the_reproduction_asking_the_primary_reads_a_tracked_file_as_ignored(fx):
    """The premise, measured: the primary ignores every file of a worktree it holds under
    `.claude/worktrees/`, while the worktree ignores none of its tracked files."""
    p, spaces = fx
    readme = spaces["inner"].resolve() / "README.md"
    assert subprocess.run(["git", "-C", str(p), "check-ignore", "-q", str(readme)],
                          env=_ENV).returncode == 0
    assert subprocess.run(["git", "-C", str(spaces["inner"]), "check-ignore", "-q", str(readme)],
                          env=_ENV).returncode == 1


def test_a_workspace_spelled_through_a_symlink_is_still_the_workspace(fx, tmp_path):
    """A lock's `workspace:` may be any spelling of the directory; both sides resolve."""
    p, spaces = fx
    alias = tmp_path / "alias"
    alias.symlink_to(spaces["inner"])
    _link(spaces["inner"], "self", "README.md")
    _link(spaces["inner"], "venvlink", ".venv")
    assert IL.ignored_link(str(alias), "self", str(p)) is False
    assert IL.ignored_link(str(alias), "venvlink", str(p)) is True


def test_an_absolute_link_into_the_workspace_is_asked_of_the_workspace(fx):
    p, spaces = fx
    _link(spaces["inner"], "abs", spaces["inner"] / "README.md")
    assert IL.ignored_link(str(spaces["inner"]), "abs", str(p)) is False


def test_a_callers_git_dir_does_not_answer_for_the_workspace(fx, monkeypatch, tmp_path):
    """An unrelated repository that ignores everything: with its GIT_DIR kept, `-C` would
    still ask it, and the tracked file would read as ignored."""
    p, spaces = fx
    _link(spaces["inner"], "self", "README.md")
    other = tmp_path / "other"
    other.mkdir()
    _g(other, "-c", "init.defaultBranch=main", "init", "-q")
    (other / ".git/info/exclude").write_text("*\n")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    try:
        assert importlib.reload(IL).ignored_link(str(spaces["inner"]), "self", str(p)) is False
    finally:
        monkeypatch.delenv("GIT_DIR")
        importlib.reload(IL)


def test_a_link_into_a_missing_ignored_directory_is_work(fx):
    """Kept, classified dirty, never removed: `sysop/runtime/` is ignored, but the target's
    directory does not exist, so the link is not provably tooling."""
    p, spaces = fx
    _link(spaces["inner"], "gone", "sysop/runtime/nope/x")
    assert IL.ignored_link(str(spaces["inner"]), "gone", str(p)) is False


def test_a_link_chained_through_another_link_is_asked_where_it_resolves(fx):
    """`via -> hop/x`, `hop -> .venv`: the lexical target passes through a link git refuses
    to look beyond; the resolved one lies in the ignored `.venv/`."""
    p, spaces = fx
    w = spaces["inner"]
    _link(w, "hop", ".venv")
    _link(w, "via", "hop/x")
    assert IL.ignored_link(str(w), "via", str(p)) is True


@pytest.mark.parametrize("exc", [subprocess.TimeoutExpired(["git"], 15), OSError("no git")])
def test_a_check_that_cannot_answer_is_work(fx, monkeypatch, exc):
    p, spaces = fx
    _link(spaces["inner"], "venvlink", ".venv")

    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(IL.subprocess, "run", boom)
    assert IL.ignored_link(str(spaces["inner"]), "venvlink", str(p), timeout=15) is False


def test_a_case_variant_spelling_of_the_workspace_is_still_the_workspace(fx):
    """On a case-insensitive file system `realpath` keeps the spelling, so the inside test
    compares by identity; by spelling, the main checkout answered and the link read as
    tooling (Phase 485's round, lens A)."""
    p, spaces = fx
    w = spaces["inner"]
    if not (w.parent / "INNER").exists():
        pytest.skip("case-sensitive file system")
    _link(w, "ci", "../INNER/README.md")
    assert IL.ignored_link(str(w), "ci", str(p)) is False


def test_a_target_outside_every_repository_is_work(fx, tmp_path):
    """The main checkout answers 128 for it, which is not "ignored"."""
    p, spaces = fx
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere/f.txt").write_text("x\n")
    _link(spaces["inner"], "far", tmp_path / "elsewhere/f.txt")
    assert IL.ignored_link(str(spaces["inner"]), "far", str(p)) is False


def test_a_link_in_a_subdirectory_resolves_from_its_own_directory(fx):
    p, spaces = fx
    w = spaces["inner"]
    (w / "src").mkdir()
    _link(w / "src", "pv", "../../../../.venv")
    assert (w / "src/pv").resolve() == (p / ".venv").resolve()
    assert IL.ignored_link(str(w), "src/pv", str(p)) is True


def test_a_broken_link_and_a_plain_file_are_work(fx):
    p, spaces = fx
    _link(spaces["inner"], "gone", "nodir/x")
    (spaces["inner"] / "plain").write_text("x\n")
    assert IL.ignored_link(str(spaces["inner"]), "gone", str(p)) is False
    assert IL.ignored_link(str(spaces["inner"]), "plain", str(p)) is False


# ── each reader, end to end ─────────────────────────────────────────────────────

def _close_state(p: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["python3", str(SCRIPTS / "close_state.py"), *args], cwd=str(p),
                          capture_output=True, text=True, env=_ENV)


def _row(out: str, branch: str) -> str:
    hits = [ln for ln in out.splitlines() if re.match(rf"^\S+\s+{re.escape(branch)}\s", ln)]
    assert len(hits) == 1, out
    return hits[0]


@pytest.mark.parametrize("kind", ["inner", "outer"])
def test_step_1a_reads_a_link_to_the_worktrees_own_file_as_work(fx, kind):
    """The entry's symptom: `inner` read `MERGED` with this link as its only change."""
    p, spaces = fx
    _link(spaces[kind], "self", "README.md")
    row = _row(_close_state(p, "worktrees", "main").stdout, kind)
    assert row.startswith("DIRTY") and "1 pending changes" in row, row


@pytest.mark.parametrize("kind", ["inner", "outer"])
def test_step_1a_and_strip_links_agree_on_every_link(fx, kind):
    """Every untracked link is either counted by Step 1a or removed by `strip-links`, never
    neither: a downgraded link `strip-links` kept made the unforced remove refuse, and a kept
    one Step 1a downgraded is the entry's symptom."""
    p, spaces = fx
    w = spaces[kind]
    (w / "new.txt").write_text("n\n")
    for name, target, _ in CASES:
        _link(w, name, (p / ".venv") if target == "PRIMARY_VENV" else target)
    r = _close_state(p, "strip-links", str(w))
    assert r.returncode == 0, r.stdout + r.stderr
    removed = set(re.findall(r"^REMOVED LINK: (\S+)$", r.stdout, re.M))
    assert removed == {n for n, _, tooling in CASES if tooling}, r.stdout
    kept = {n for n, _, _ in CASES} - removed
    row = _row(_close_state(p, "worktrees", "main").stdout, kind)
    assert f"{len(kept) + 1} pending changes" in row, row   # + new.txt


def test_a_branch_claims_primary_reads_the_same_either_way(fx):
    """`--branch`: the workspace is the main checkout, so these shapes read as they did. A link
    chained through another link is asked by its realpath now, so it can move (Phase 485's
    round, lens B)."""
    p, _ = fx
    _g(p, "checkout", "-q", "-b", "feat/b")
    locks = p / "sysop/runtime/locks"
    locks.mkdir(parents=True)
    (locks / "T-1.lock").write_text(f"task: T-1\nbranch: feat/b\nworkspace: {p}\n")
    _link(p, "venvlink", ".venv")
    _link(p, "pvenv", p / ".venv")
    assert _row(_close_state(p, "worktrees", "main").stdout, "feat/b").startswith("MERGED")
    _link(p, "self", "README.md")
    row = _row(_close_state(p, "worktrees", "main").stdout, "feat/b")
    assert row.startswith("DIRTY") and "1 pending changes" in row, row


def test_sitrep_reads_the_same_rule(fx):
    p, spaces = fx
    inner = spaces["inner"]
    _link(inner, "venvlink", ".venv")
    _link(inner, "pvenv", p / ".venv")
    assert ss._worktree_dirty(inner, p) is False
    _link(inner, "self", "README.md")
    assert ss._worktree_dirty(inner, p) is True
    assert ss._ignored_symlink(inner, "self", p) is False


# ── one rule, by construction ───────────────────────────────────────────────────

# Each reader's function, which must call the shared rule; `noise` in `feature_branch.py` is
# nested in the `landed` block, so the walk reaches it at any depth.
READERS = {"close_state.py": "ignored_link", "clone_sync.py": "noise",
           "feature_branch.py": "noise", "sitrep_survey.py": "_ignored_symlink"}


def _calls_the_rule(fn: ast.AST) -> bool:
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "ignored_link" and isinstance(n.func.value, ast.Name)
               and n.func.value.id == "_ignored_link" for n in ast.walk(fn))


@pytest.mark.parametrize("name", sorted(READERS))
def test_every_reader_asks_through_the_shared_rule(name):
    """A reader that ran its own `check-ignore` would answer from whichever repository its
    working directory is, the defect this phase removed. Read from the syntax tree, so a
    comment naming the call does not satisfy it."""
    tree = ast.parse((SCRIPTS / name).read_text(encoding="utf-8"))
    fns = [n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == READERS[name]]
    assert fns, f"{name} has no {READERS[name]}()"
    assert all(_calls_the_rule(fn) for fn in fns), f"{name}'s {READERS[name]} no longer calls _ignored_link"
    words = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
             and isinstance(n.value, str) and n.value.strip() == "check-ignore"]
    assert not words, f"{name} runs its own check-ignore again"
