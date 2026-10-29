"""`Q-633` (Phase 354): gitignored files the work reads.

A gate that reads the working tree passed on a file the commit did not carry, and an
unforced `git worktree remove` deletes ignored files without refusing. `ignored_refs.py`
lists the references; `/claim-task` 7e item 5b and `/auto-build` 7c item 4c run it before
committing, `/review-close` Step 2a step 3a asks about each hit, and Step 3b step 0b keeps
a worktree that holds the only copy.

Everything is executed: the script directly, and the commands the three skills prescribe,
extracted from their text and run against a fixture.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import textwrap
import subprocess
import sys
from pathlib import Path

import pytest
from skill_runner_text import text_of

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"
SCRIPTS = REPO / "core/companion/scripts"
SCRIPT = SCRIPTS / "ignored_refs.py"
CLOSE = REPO / "core/skills/review-close/SKILL.md"
CLAIM = REPO / "core/skills/claim-task/SKILL.md"
AUTO = REPO / "core/skills/auto-build/SKILL.md"
WF = REPO / "core/companion/docs/WORKFLOW.md"
SETTINGS = REPO / "core/companion/.claude/settings.json"
sys.path.insert(0, str(TESTS))

_ENV = {k: v for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}


def _g(root: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, env=_ENV)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path, gitignore: str = "*.json\nnode_modules/\nsysop/runtime/\n",
          files: dict[str, str] | None = None) -> Path:
    """A main checkout on `main` carrying the script at `sysop/scripts/`, as an install does."""
    root = tmp_path / "repo"
    root.mkdir()
    _g(root, "init", "-q", "-b", "main")
    _g(root, "config", "user.email", "t@t")
    _g(root, "config", "user.name", "t")
    _g(root, "config", "commit.gpgsign", "false")
    _write(root, ".gitignore", gitignore)
    for rel, text in (files or {"app/page.ts": "export const x = 1\n"}).items():
        _write(root, rel, text)
    (root / "sysop/scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "sysop/scripts/ignored_refs.py")
    _g(root, "add", "-A")
    _g(root, "commit", "-qm", "base")
    return root


def _worktree(root: Path, tmp_path: Path, branch: str = "feat") -> Path:
    wt = tmp_path / "wt"
    _g(root, "worktree", "add", "-q", str(wt), "-b", branch)
    return wt


def _run(ws: Path, base: str = "main", *extra: str, cwd: Path | None = None):
    return subprocess.run([sys.executable, str(SCRIPT), str(ws), base, *extra],
                          cwd=cwd or ws, capture_output=True, text=True, env=_ENV)


def _refs(out: str) -> list[str]:
    return [ln.split(" <- ")[0][len("IGNORED-REF: "):] for ln in out.splitlines()
            if ln.startswith("IGNORED-REF: ")]


# ─────────────────────────────────────────────────────────────────────────────
# The premise, measured: what the guard exists for
# ─────────────────────────────────────────────────────────────────────────────

def test_premise_unforced_worktree_remove_deletes_ignored_files_silently(tmp_path):
    """The entry's premise. If git ever starts refusing, Step 3b step 0b is redundant."""
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "app/fixtures/a.json", "{}")
    assert _g(wt, "status", "--porcelain") == ""  # Step 1a would call it clean
    r = subprocess.run(["git", "worktree", "remove", str(wt)], cwd=root,
                       capture_output=True, text=True, env=_ENV)
    assert r.returncode == 0 and not wt.exists(), r.stderr


# ─────────────────────────────────────────────────────────────────────────────
# The script
# ─────────────────────────────────────────────────────────────────────────────

def test_the_reporters_reproduction(tmp_path):
    """The reporter's: gitignore *.json, add x.json, commit a module importing it."""
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "x.json", "{}")
    _write(wt, "app/page.ts", "import x from '../x.json'\n")
    _g(wt, "commit", "-qam", "work")
    r = _run(wt)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "IGNORED-REF: x.json <- app/page.ts:1 (only copy)" in r.stdout, r.stdout
    assert r.stdout.strip().splitlines()[-1].startswith("IGNORED-REFS: 1 found"), r.stdout


def test_uncommitted_work_and_new_files_are_read(tmp_path):
    """Both executors run it before they commit."""
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "app/fixtures/a.json", "{}")
    _write(wt, "app/fixtures/b.json", "{}")
    _write(wt, "app/page.ts", "export const x = 1\nimport a from './fixtures/a.json'\n")
    _write(wt, "app/new.ts", "// new\nconst b = require('./fixtures/b.json')\n")
    r = _run(wt)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "IGNORED-REF: app/fixtures/a.json <- app/page.ts:2 (only copy)" in r.stdout
    assert "IGNORED-REF: app/fixtures/b.json <- app/new.ts:2 (only copy)" in r.stdout


def test_nothing_referenced_is_exit_0_and_the_summary_counts_what_it_read(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "unused.json", "{}")
    _write(wt, "app/page.ts", "export const x = 2\nexport const y = 3\n")
    r = _run(wt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == ("IGNORED-REFS: none (1 ignored files; 0 ignored directories "
                                "not read; 2 added lines in 1 files; 0 resolver configs read; "
                                "names built at run time not read)"), r.stdout


@pytest.mark.parametrize("line,where,want", [
    ("import data from '@/data/c.json'", "app/page.ts", "src/data/c.json"),
    ("import d from './fixtures/data'", "app/page.ts", "app/fixtures/data.json"),
    ("import d from './fixtures'", "app/page.ts", "app/fixtures/index.json"),
    ("fetch('/data/c.json')", "app/page.ts", "src/data/c.json"),
    ("load(\"a.json\")", "app/page.ts", "app/fixtures/a.json"),
    ("Path(__file__).parent / 'fixtures' / 'a.json'", "app/x.py", "app/fixtures/a.json"),
])
def test_reference_shapes(tmp_path, line, where, want):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    for rel in ("src/data/c.json", "app/fixtures/data.json", "app/fixtures/index.json",
                "app/fixtures/a.json"):
        _write(wt, rel, "{}")
    _write(wt, where, line + "\n")
    r = _run(wt)
    assert want in _refs(r.stdout), r.stdout


@pytest.mark.parametrize("line", [
    "import local_settings",
    "from . import local_settings",
    "from pkg import local_settings",
    "from pkg.local_settings import X",
    "import pkg.local_settings as ls",
])
def test_python_import_forms(tmp_path, line):
    root = _repo(tmp_path, gitignore="local_settings.py\n")
    wt = _worktree(root, tmp_path)
    _write(wt, "pkg/local_settings.py", "A = 1\n")
    _write(wt, "pkg/__init__.py", "")
    _write(wt, "pkg/mod.py", line + "\n")
    r = _run(wt)
    assert _refs(r.stdout) == ["pkg/local_settings.py"], r.stdout


def test_a_relative_import_resolves_against_the_package(tmp_path):
    """`from ..conf import x` in `pkg/sub/m.py` is `pkg/conf.py`, not `conf.py`."""
    root = _repo(tmp_path, gitignore="conf.py\n")
    wt = _worktree(root, tmp_path)
    _write(wt, "pkg/conf.py", "")
    _write(wt, "conf.py", "")
    _write(wt, "pkg/sub/m.py", "from ..conf import x\n")
    assert _refs(_run(wt).stdout) == ["pkg/conf.py"]


def test_directories_ignored_as_a_whole_are_not_read(tmp_path):
    """Wade, 2026-10-01: the two false hits on a consumer's live worktrees were a lockfile
    naming `node_modules/...` and a test naming `tests/__pycache__`."""
    root = _repo(tmp_path, gitignore="*.json\nnode_modules/\n__pycache__/\n")
    wt = _worktree(root, tmp_path)
    _write(wt, "node_modules/@js-sdsl/ordered-map/index.js", "1")
    _write(wt, "tests/__pycache__/t.pyc", "x")
    _write(wt, "package.lock", '"node_modules/@js-sdsl/ordered-map": {\n')
    _write(wt, "tests/test_x.py", "assert not Path('tests/__pycache__/t.pyc').exists()\n")
    r = _run(wt)
    assert r.returncode == 0, r.stdout
    assert "2 ignored directories not read" in r.stdout, r.stdout


@pytest.mark.parametrize("rel", ["README.md", "docs/x.rst", "guide.adoc", ".gitignore",
                                 "Dockerfile.dockerignore", "web/.eslintignore"])
def test_prose_and_ignore_files_are_not_read(tmp_path, rel):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "app/fixtures/a.json", "{}")
    _write(wt, rel, "see app/fixtures/a.json\n")
    r = _run(wt)
    assert r.returncode == 0, r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# Phase 354's round: what the first build missed or over-read
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel,line,want", [
    ("requirements.txt", "./wheels/internal-1.0-py3-none-any.whl", "wheels/internal-1.0-py3-none-any.whl"),
    ("requirements.txt", "-r requirements.local.txt", "requirements.local.txt"),
    ("CMakeLists.txt", "include(cmake/dev.local.cmake)", "cmake/dev.local.cmake"),
    ("content/page.mdx", "import data from './data.json'", "content/data.json"),
])
def test_build_files_that_look_like_prose_are_read(tmp_path, rel, line, want):
    root = _repo(tmp_path, gitignore="*.whl\n*.local.txt\n*.local.cmake\n*.json\n")
    wt = _worktree(root, tmp_path)
    _write(wt, want, "x")
    _write(wt, rel, line + "\n")
    assert want in _refs(_run(wt).stdout)


@pytest.mark.parametrize("line", [
    'FIXTURES = pathlib.Path(__file__).parent / "fixtures"',
    "files = fs.readdirSync(path.join(__dirname, 'fixtures'))",
    'paths = glob.glob("tests/fixtures/*.json")',
    'for p in Path("tests/fixtures").iterdir(): pass',
    'FILES = sorted(os.listdir("tests/fixtures"))',
    "const files = fs.readdirSync('tests/fixtures')",
    "//go:embed fixtures/*.json",
])
def test_a_directory_reference_reports_the_files_under_it(tmp_path, line):
    """Phase 354 round, lens C's HIGH: the files are ignored by a file pattern, so
    they are listed, and a test that reads the directory reads them all."""
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    for n in ("a", "b"):
        _write(wt, f"tests/fixtures/{n}.json", "{}")
    _write(wt, "tests/test_x.py", line + "\n")
    r = _run(wt)
    assert r.returncode == 1 and _refs(r.stdout) == ["tests/fixtures/a.json",
                                                     "tests/fixtures/b.json"], r.stdout


@pytest.mark.parametrize("line", [
    "# negation like `!tests/**` names nothing",
    "// see tests/fixtures/(group)/page.tsx for the layout",
    "# `tests/fixtures/*.py` are helpers",
    "fixtures = load_all()",
])
def test_a_directory_mentioned_without_reading_it_is_not_a_reference(tmp_path, line):
    """Measured on a consumer's history: comments, regexes and a bare `**` reported
    every ignored file under a directory until directory references needed a string
    literal beside the file, or a glob that names files."""
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    for n in ("a", "b"):
        _write(wt, f"tests/fixtures/{n}.json", "{}")
    _write(wt, "tests/test_x.py", line + "\n")
    _write(wt, "tests/README.ts", line + "\n")
    assert _run(wt).returncode == 0, _run(wt).stdout


def test_a_root_glob_reports_only_the_files_it_matches(tmp_path):
    root = _repo(tmp_path, gitignore="*.json\n*.log\n")
    wt = _worktree(root, tmp_path)
    _write(wt, "tests/fixtures/a.json", "{}")
    _write(wt, "tests/fixtures/run.log", "x")
    _write(wt, "tests/test_x.py", 'paths = glob.glob("tests/fixtures/*.json")\n')
    assert _refs(_run(wt).stdout) == ["tests/fixtures/a.json"]


@pytest.mark.parametrize("rel,line", [
    ("vitest.config.ts", 'include: ["tests/**/*.test.ts"]'),
    ("pyproject.toml", 'exclude = ["tests/**"]'),
])
def test_a_root_glob_in_a_root_file_reads_only_its_matches(tmp_path, rel, line):
    """Round 2, lens A: a quoted glob also took the beside arm and read the whole dir."""
    root = _repo(tmp_path, gitignore="*.json\n*.log\n")
    wt = _worktree(root, tmp_path)
    _write(wt, "tests/fixtures/a.json", "{}")
    _write(wt, "tests/run.log", "x")
    _write(wt, rel, line + "\n")
    assert _run(wt).returncode == 0, _run(wt).stdout


def test_a_glob_star_stays_inside_one_component(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "tests/fixtures/a.json", "{}")
    _write(wt, "tests/fixtures/sub/b.json", "{}")
    _write(wt, "tests/test_x.py", 'glob.glob("tests/fixtures/*.json")\n')
    assert _refs(_run(wt).stdout) == ["tests/fixtures/a.json"]


def test_a_quoted_directory_reaches_nested_files(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "tests/fixtures/sub/a.json", "{}")
    _write(wt, "tests/test_x.py", 'D = Path(__file__).parent / "fixtures"\n')
    assert _refs(_run(wt).stdout) == ["tests/fixtures/sub/a.json"]


def test_a_backtick_is_a_quote(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "tests/fixtures/a.json", "{}")
    _write(wt, "tests/t.ts", "const d = path.join(__dirname, `fixtures`)\n")
    assert _refs(_run(wt).stdout) == ["tests/fixtures/a.json"]


def test_a_star_after_a_token_not_ending_in_a_slash_is_not_a_glob(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "tests/fixtures/a.json", "{}")
    _write(wt, "x.py", "n = tests/fixtures*2\n")
    assert _run(wt).returncode == 0


def test_a_bare_identifier_is_not_a_directory_reference(tmp_path):
    """`from app import create_app` names a module, not the directory `app/`."""
    root = _repo(tmp_path, gitignore="*.log\n*.db\n")
    wt = _worktree(root, tmp_path)
    _write(wt, "app/server.log", "x")
    _write(wt, "app.db", "x")
    _write(wt, "app/__init__.py", "")
    _write(wt, "run.py", "from app import create_app\napp = create_app()\n")
    assert _run(wt).returncode == 0


@pytest.mark.parametrize("files,line,where", [
    (("config.json",), "import config", "main.py"),
    (("src/api.log",), "import { get } from './api'", "src/page.ts"),
])
def test_completion_tries_only_what_a_resolver_tries(tmp_path, files, line, where):
    root = _repo(tmp_path, gitignore="*.json\n*.log\n")
    wt = _worktree(root, tmp_path)
    for f in files:
        _write(wt, f, "x")
    _write(wt, where, line + "\n")
    assert _run(wt).returncode == 0


@pytest.mark.parametrize("line,want", [
    ('source "$ROOT/config/dev.local.sh"', "config/dev.local.sh"),
    ("from mypkg import secrets_local", "src/mypkg/secrets_local.py"),
    ("import os, local_settings", "local_settings.py"),
    ("import pkg", "pkg/__init__.py"),
    ("x = load('my-data.json')", "my-data.json"),
])
def test_more_reference_shapes(tmp_path, line, want):
    root = _repo(tmp_path, gitignore="*.local.sh\nsecrets_local.py\nlocal_settings.py\n"
                                     "pkg/__init__.py\n*.json\n")
    wt = _worktree(root, tmp_path)
    _write(wt, want, "x")
    _write(wt, "run.py", line + "\n")
    assert want in _refs(_run(wt).stdout)


def test_a_closed_parenthesised_import_ends_at_its_paren(tmp_path):
    root = _repo(tmp_path, gitignore="local.py\n")
    wt = _worktree(root, tmp_path)
    _write(wt, "pkg/local.py", "")
    _write(wt, "pkg/mod.py", "from pkg import (\n    other,\n)\nlocal = 1\n")
    assert _run(wt).returncode == 0


def test_the_src_suffix_keeps_its_component_boundary(tmp_path):
    root = _repo(tmp_path, gitignore="local.py\n")
    wt = _worktree(root, tmp_path)
    _write(wt, "src/xmypkg/local.py", "")
    _write(wt, "run.py", "from mypkg import local\n")
    assert _run(wt).returncode == 0


def test_a_pyi_file_is_read_for_imports(tmp_path):
    root = _repo(tmp_path, gitignore="local_settings.py\n")
    wt = _worktree(root, tmp_path)
    _write(wt, "local_settings.py", "")
    _write(wt, "stubs.pyi", "import local_settings\n")
    assert _refs(_run(wt).stdout) == ["local_settings.py"]


def test_a_parenthesised_import_reads_its_continuation_lines(tmp_path):
    root = _repo(tmp_path, gitignore="local.py\n")
    wt = _worktree(root, tmp_path)
    _write(wt, "pkg/local.py", "")
    _write(wt, "pkg/mod.py", "from pkg import (\n    other,\n    local,\n)\n")
    assert _refs(_run(wt).stdout) == ["pkg/local.py"]


def test_the_suffix_match_keeps_its_component_boundary(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "xfixtures/a.json", "{}")
    _write(wt, "app/page.ts", "load('fixtures/a.json')\n")
    assert _run(wt).returncode == 0


def test_a_reference_in_a_later_file_of_the_diff_is_read(tmp_path):
    root = _repo(tmp_path, files={"a.ts": "x\n", "b.ts": "x\n"})
    wt = _worktree(root, tmp_path)
    _write(wt, "x.json", "{}")
    _write(wt, "a.ts", "x\ny\n")
    _write(wt, "b.ts", "x\nimport './x.json'\n")
    assert "IGNORED-REF: x.json <- b.ts:2 (only copy)" in _run(wt).stdout


def test_a_moved_file_is_read_whole(tmp_path):
    """Its relative import now resolves somewhere else; with rename detection only the
    changed lines would be read."""
    root = _repo(tmp_path, files={"app/a.ts": "import x from './fixtures/x.json'\n"})
    wt = _worktree(root, tmp_path)
    (wt / "lib").mkdir()
    (wt / "app/a.ts").rename(wt / "lib/a.ts")
    _write(wt, "lib/fixtures/x.json", "{}")
    _g(wt, "add", "-A")
    _g(wt, "commit", "-qm", "move")
    assert _refs(_run(wt).stdout) == ["lib/fixtures/x.json"]


def test_lines_the_default_branch_removed_are_not_the_branchs(tmp_path):
    """The diff is against the merge-base, not the base tip: a line main deleted after
    the fork must not read as one the branch added."""
    root = _repo(tmp_path, files={"app/a.ts": "import x from '../x.json'\n"})
    wt = _worktree(root, tmp_path)
    _write(wt, "x.json", "{}")
    _write(root, "app/a.ts", "\n")
    _g(root, "commit", "-qam", "main drops the import")
    assert _run(wt).returncode == 0


def test_a_bare_directory_name_is_not_a_file(tmp_path):
    root = _repo(tmp_path, gitignore=".venv/\n")
    wt = _worktree(root, tmp_path)
    _write(wt, ".venv/bin/python3", "x")
    _write(wt, "run.sh", ". .venv/bin/activate\n")
    assert _run(wt).returncode == 0


def test_a_path_with_a_space_and_a_diff_attribute(tmp_path):
    """git ends a `+++` header with a TAB when the path holds a space, and a `-diff`
    attribute turns a hunk into `Binary files differ` unless `--text` is passed. Each
    file references its own target, so no first reference can mask another."""
    root = _repo(tmp_path)
    _write(root, ".gitattributes", "*.lock.ts -diff\n")
    _g(root, "add", "-A")
    _g(root, "commit", "-qm", "attrs")
    wt = _worktree(root, tmp_path)
    for name in ("code.json", "lock.json", "notes.json", "mod_local.py"):
        _write(wt, name, "{}")
    _write(root, ".gitignore", "*.json\nnode_modules/\nsysop/runtime/\n")
    _write(wt, ".gitignore", "*.json\nnode_modules/\nsysop/runtime/\nmod_local.py\n")
    _write(wt, "src/my code.ts", "import '../code.json'\n")
    _write(wt, "deps.lock.ts", "import './lock.json'\n")
    _write(wt, "docs/my notes.md", "notes.json\n")
    _write(wt, "my tool.py", "import mod_local\n")
    _g(wt, "add", "-A")
    _g(wt, "commit", "-qm", "work")
    out = _run(wt).stdout
    assert "IGNORED-REF: code.json <- src/my code.ts:1 (only copy)" in out, out
    assert "IGNORED-REF: lock.json <- deps.lock.ts:1 (only copy)" in out, out
    assert "IGNORED-REF: mod_local.py <- my tool.py:1 (only copy)" in out, out
    assert "notes.json" not in out and "\t" not in out, out


def test_a_directory_beside_its_read_files_is_not_counted_unread(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "a/b/c/x.json", "{}")
    assert "0 ignored directories not read" in _run(wt).stdout


@pytest.mark.parametrize("checked_out", [True, False])
def test_a_branch_claim_reads_the_branch_not_the_checkout(tmp_path, checked_out):
    """Lens A and C: a `--branch` claim's workspace is the main checkout, which may be
    back on the default branch at close time."""
    root = _repo(tmp_path)
    _g(root, "checkout", "-q", "-b", "feat/br")
    _write(root, "data/cfg.json", "{}")
    _write(root, "src/a.ts", "import cfg from '../data/cfg.json'\n")
    _g(root, "add", "src/a.ts")
    _g(root, "commit", "-qm", "work")
    if not checked_out:
        _g(root, "checkout", "-q", "main")
    r = _run(root, "main", "--branch", "feat/br")
    assert r.returncode == 1 and _refs(r.stdout) == ["data/cfg.json"], r.stdout + r.stderr


def test_a_clone_is_compared_with_the_callers_main_checkout(tmp_path):
    """A clone's own common dir is its own `.git`; compared with itself every hit read
    as having an identical copy."""
    root = _repo(tmp_path)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(root), str(clone)], check=True, env=_ENV)
    _g(clone, "config", "user.email", "t@t")
    _g(clone, "config", "user.name", "t")
    _g(clone, "checkout", "-q", "-b", "feat")
    _write(clone, "q.json", "{}")
    _write(clone, "app/page.ts", "import '../q.json'\n")
    r = _run(clone, "main", cwd=root)
    assert "IGNORED-REF: q.json <- app/page.ts:1 (only copy)" in r.stdout, r.stdout
    inside = _run(clone, "main")
    assert "not compared" in inside.stdout, inside.stdout


def test_an_unexpected_exception_is_exit_3_not_found(tmp_path, monkeypatch):
    """Exit 1 means "found"; a crash read that way would make an executor file nothing
    and Step 3b SKIP for no reason."""
    import importlib
    sys.path.insert(0, str(SCRIPT.parent))
    mod = importlib.import_module("ignored_refs")
    root = _repo(tmp_path)
    def boom(*a, **k):
        raise KeyError("x")
    monkeypatch.setattr(mod, "run", boom)
    assert mod.main([str(root), "main"]) == 3


def test_the_first_referencing_line_is_reported(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "x.json", "{}")
    _write(wt, "a.ts", "import './x.json'\nimport './x.json'\n")
    assert "IGNORED-REF: x.json <- a.ts:1 " in _run(wt).stdout


@pytest.mark.parametrize("line", ["fetch('/config.json')", "load('~/config.json')"])
def test_a_root_prefix_resolves_from_the_root(tmp_path, line):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "config.json", "{}")
    _write(wt, "app/deep/page.ts", line + "\n")
    assert _refs(_run(wt).stdout) == ["config.json"]


def test_an_alias_does_not_resolve_beside_the_file(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "app/data.json", "{}")
    _write(wt, "app/page.ts", "import d from '@/data.json'\n")
    assert _run(wt).returncode == 0


def test_prose_is_matched_in_any_case(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "x.json", "{}")
    _write(wt, "README.MD", "x.json\n")
    assert _run(wt).returncode == 0


def test_binary_and_symlinked_untracked_files_are_not_read(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "x.json", "{}")
    (wt / "blob.bin").write_bytes(b"\0x.json")
    _write(root, "outside.ts", "import './x.json'\n")
    (wt / "link.ts").symlink_to(root / "outside.ts")
    assert _run(wt).returncode == 0


def test_a_branch_claim_off_its_branch_does_not_read_untracked_files(tmp_path):
    root = _repo(tmp_path)
    _g(root, "branch", "feat/br")
    _write(root, "x.json", "{}")
    _write(root, "scratch.ts", "import './x.json'\n")
    assert _run(root, "main", "--branch", "feat/br").returncode == 0


def test_the_runtime_exclusion_keeps_its_boundary(tmp_path):
    root = _repo(tmp_path, gitignore="*.json\n")
    wt = _worktree(root, tmp_path)
    _write(wt, "sysop/runtimes/x.json", "{}")
    _write(wt, "tool.sh", "cat sysop/runtimes/x.json\n")
    assert _refs(_run(wt).stdout) == ["sysop/runtimes/x.json"]


@pytest.mark.parametrize("where", ["nested", "info", "global"])
def test_every_ignore_source_counts(tmp_path, where, monkeypatch):
    root = _repo(tmp_path, gitignore="node_modules/\n")
    wt = _worktree(root, tmp_path)
    if where == "nested":
        _write(wt, "app/.gitignore", "local.json\n")
        _g(wt, "add", "app/.gitignore")
        _g(wt, "commit", "-qm", "nested")
    elif where == "info":
        _write(Path(_g(root, "rev-parse", "--path-format=absolute", "--git-common-dir")),
               "info/exclude", "local.json\n")
    else:
        _write(tmp_path, "global_ignore", "local.json\n")
        _g(root, "config", "core.excludesFile", str(tmp_path / "global_ignore"))
    _write(wt, "app/local.json", "{}")
    _write(wt, "app/page.ts", "import './local.json'\n")
    assert _refs(_run(wt).stdout) == ["app/local.json"]


def test_a_code_file_with_the_same_line_is_read(tmp_path):
    """The control for the test above: the line itself is a reference."""
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "app/fixtures/a.json", "{}")
    _write(wt, "build.sh", "see app/fixtures/a.json\n")
    assert _refs(_run(wt).stdout) == ["app/fixtures/a.json"]


def test_sysops_own_runtime_is_never_reported(tmp_path):
    """A branch cut before the installer's `sysop/runtime/` append ignores runtime files only
    through a file pattern, so they are listed one by one (Step 1a's note on that layout)."""
    root = _repo(tmp_path, gitignore="*.json\n")
    wt = _worktree(root, tmp_path)
    _write(wt, "sysop/runtime/pending-docs/feat.json", "{}")
    _write(wt, "tool.sh", "cat sysop/runtime/pending-docs/feat.json\n")
    r = _run(wt)
    assert r.returncode == 0, r.stdout


@pytest.mark.parametrize("name", ['app/we"ird.ts', "app/tab\there.ts", "app/back\\slash.ts"])
def test_a_file_whose_name_git_quotes_is_still_read(tmp_path, name):
    """git C-quotes a header path holding `"`, a tab or a backslash, whatever
    `core.quotePath` says; read raw, every line under it went unread."""
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "x.json", "{}")
    _write(wt, name, "import '../x.json'\n")
    _g(wt, "add", "-A")
    _g(wt, "commit", "-qm", "work")
    r = _run(wt)
    assert _refs(r.stdout) == ["x.json"], r.stdout + r.stderr
    assert f"<- {name}:1 " in r.stdout, r.stdout


def test_a_relative_name_does_not_match_a_namesake_elsewhere(tmp_path):
    """`./a.json` resolves against its file; only a bare `a.json` matches anywhere."""
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "other/a.json", "{}")
    _write(wt, "app/page.ts", "import a from './a.json'\n")
    assert _run(wt).returncode == 0


def test_a_bare_word_does_not_match_by_stem(tmp_path):
    """`config` is an identifier, not a reference to `config.json`."""
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "config.json", "{}")
    _write(wt, "app/config.json", "{}")
    _write(wt, "app/page.ts", "const config = load(index)\n")
    assert _run(wt).returncode == 0


def test_a_failing_git_command_is_exit_3_not_none(tmp_path):
    """`merge-base` still works over a corrupt index; `ls-files` and `diff` do not. A failure
    there read as an empty listing would print `none` and exit 0."""
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "x.json", "{}")
    _write(wt, "app/page.ts", "import '../x.json'\n")
    index = Path(_g(wt, "rev-parse", "--path-format=absolute", "--git-path", "index"))
    index.write_bytes(b"DIRC garbage")
    r = _run(wt)
    assert r.returncode == 3 and "did not run" in r.stderr, (r.stdout, r.stderr)
    assert "IGNORED-REFS:" not in r.stdout


def test_a_deleted_file_and_a_body_line_starting_plus_plus_plus(tmp_path):
    """Header parsing: `+++ /dev/null` adds nothing, and a body line `++ x` arrives as
    `+++ x`, which must be read as a line, not a header."""
    root = _repo(tmp_path, files={"gone.ts": "a\n", "app/page.ts": "x\n"})
    wt = _worktree(root, tmp_path)
    (wt / "gone.ts").unlink()
    _write(wt, "x.json", "{}")
    _write(wt, "app/page.ts", "x\n++ ../x.json\n")
    r = _run(wt)
    assert "IGNORED-REF: x.json <- app/page.ts:2 (only copy)" in r.stdout, r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# --only-copy and --clear: Step 3b step 0b's two arguments
# ─────────────────────────────────────────────────────────────────────────────

def test_the_label_says_whether_the_main_checkout_holds_a_copy(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    for d in (root, wt):
        _write(d, "same.json", "{}")
    _write(root, "differs.json", '{"a": 1}')
    _write(wt, "differs.json", '{"a": 2}')
    _write(wt, "only.json", "{}")
    _write(wt, "app/page.ts", "import '../same.json'\nimport '../differs.json'\nimport '../only.json'\n")
    out = _run(wt).stdout
    assert "IGNORED-REF: same.json <- app/page.ts:1 (the main checkout has an identical copy)" in out
    assert "IGNORED-REF: differs.json <- app/page.ts:2 (only copy)" in out
    assert "IGNORED-REF: only.json <- app/page.ts:3 (only copy)" in out


def test_the_main_checkout_as_workspace_is_not_compared(tmp_path):
    """`--branch` mode: the workspace IS the main checkout, which no step removes."""
    root = _repo(tmp_path)
    _write(root, "x.json", "{}")
    _write(root, "app/page.ts", "import '../x.json'\n")
    r = _run(root)
    assert r.returncode == 1 and "(not compared: the workspace is its own main checkout)" in r.stdout


def _preserve(ws: Path, dest: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), str(ws), "--preserve", dest],
                          cwd=cwd, capture_output=True, text=True, env=_ENV)


def test_preserve_copies_every_only_copy_ignored_file_referenced_or_not(tmp_path):
    """Wade, 2026-10-02: step 0b's data-loss guard is matcher-free. A fixture read through
    a template literal the check cannot see survives the remove."""
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "tests/fixtures/a.json", "{}")
    _write(wt, "src/t.ts", "const f = `./fixtures/${name}.json`\n")
    _write(root, "same.json", "{}")
    _write(wt, "same.json", "{}")
    (wt / "link.json").symlink_to(root / "same.json")
    _g(wt, "add", "src/t.ts")
    _g(wt, "commit", "-qm", "work")
    assert _run(wt).returncode == 0                       # the check cannot see it
    r = _preserve(wt, "sysop/runtime/preserved/feat", root)
    assert r.returncode == 0, r.stdout + r.stderr
    kept = root / "sysop/runtime/preserved/feat/tests/fixtures/a.json"
    assert kept.read_text() == "{}"
    assert not (root / "sysop/runtime/preserved/feat/same.json").exists()
    assert not (root / "sysop/runtime/preserved/feat/link.json").exists()
    assert "PRESERVED: tests/fixtures/a.json -> " in r.stdout
    assert "PRESERVE: 1 preserved (2 bytes), 0 already preserved, 1 with a copy" in r.stdout
    assert _g(root, "status", "--porcelain") == "", "a preserved file shows as untracked"
    subprocess.run(["git", "worktree", "remove", str(wt)], cwd=root, check=True, env=_ENV)
    assert kept.read_text() == "{}"


def test_preserve_reruns_never_overwrite_a_differing_copy(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "x.json", "v1")
    assert _preserve(wt, "sysop/runtime/preserved/feat", root).returncode == 0
    again = _preserve(wt, "sysop/runtime/preserved/feat", root)
    assert "1 already preserved" in again.stdout and "PRESERVED:" not in again.stdout
    _write(wt, "x.json", "v2")
    r = _preserve(wt, "sysop/runtime/preserved/feat", root)
    assert r.returncode == 0
    assert (root / "sysop/runtime/preserved/feat/x.json").read_text() == "v1"
    stamped = list((root / "sysop/runtime/preserved/feat").glob("*/x.json"))
    assert len(stamped) == 1 and stamped[0].read_text() == "v2", r.stdout


@pytest.mark.parametrize("dest,needle", [
    ("kept", "not gitignored"),
    ("../outside", "not inside the main checkout"),
])
def test_preserve_refuses_a_destination_that_would_leak_or_escape(tmp_path, dest, needle):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "x.json", "{}")
    r = _preserve(wt, dest, root)
    assert r.returncode == 3 and needle in r.stderr, r.stderr
    assert not (root / "kept").exists()


def test_preserve_reruns_add_no_duplicates_and_keep_every_version(tmp_path):
    """Round 3: a stamped copy was re-made on every re-run, and a same-run stamp could
    overwrite an earlier one."""
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    d = root / "sysop/runtime/preserved/feat"
    for v in ("v1", "v2", "v3", "v3", "v3"):
        _write(wt, "k.json", v)
        assert _preserve(wt, "sysop/runtime/preserved/feat", root).returncode == 0
    kept = sorted(f.read_text() for f in d.rglob("k.json"))
    assert kept == ["v1", "v2", "v3"], kept


def test_preserve_stamps_around_a_file_where_a_directory_is_needed(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(root, "sysop/runtime/preserved/feat/sub", "a file, not a directory")
    (root / "sysop/runtime/preserved/feat/dangling.json").symlink_to(tmp_path / "nowhere")
    _write(wt, "sub/n.json", "{}")
    _write(wt, "dangling.json", "{}")
    r = _preserve(wt, "sysop/runtime/preserved/feat", root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(list((root / "sysop/runtime/preserved/feat").glob("*/sub/n.json"))) == 1
    assert len(list((root / "sysop/runtime/preserved/feat").glob("*/dangling.json"))) == 1
    assert not (tmp_path / "nowhere").exists()


def test_preserve_treats_a_main_checkout_link_into_the_worktree_as_no_copy(tmp_path):
    """Round 3, lens A: `proj/x.json -> ../wt/x.json` read as an identical copy, so the
    remove deleted the only bytes."""
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "x.json", "only")
    (root / "x.json").symlink_to(wt / "x.json")
    (root / "d.json").mkdir()
    _write(wt, "d.json", "file in the worktree, directory in main")
    r = _preserve(wt, "sysop/runtime/preserved/feat", root)
    assert "PRESERVED: x.json" in r.stdout and "PRESERVED: d.json" in r.stdout, r.stdout
    _write(wt, "page.ts", "import './x.json'\n")
    assert "IGNORED-REF: x.json <- page.ts:1 (only copy)" in _run(wt, cwd=root).stdout


def test_preserve_treats_a_main_directory_linked_into_the_worktree_as_no_copy(tmp_path):
    """The file itself is no link: its parent directory in the main checkout is."""
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "sub/x.json", "only")
    (root / "sub").symlink_to(wt / "sub")
    r = _preserve(wt, "sysop/runtime/preserved/feat", root)
    assert "PRESERVED: sub/x.json" in r.stdout, r.stdout


def test_preserve_treats_a_main_checkout_symlink_as_no_copy(tmp_path):
    """A link is not a copy even when its target outside the worktree holds the bytes:
    preserve keeps one more copy rather than trust a link."""
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "x.json", "same")
    _write(tmp_path, "elsewhere.json", "same")
    (root / "x.json").symlink_to(tmp_path / "elsewhere.json")
    r = _preserve(wt, "sysop/runtime/preserved/feat", root)
    assert "PRESERVED: x.json" in r.stdout, r.stdout


def test_preserve_under_a_separate_git_dir(tmp_path):
    """Round 3, lens A: the main checkout was taken as the git dir's parent."""
    proj, store = tmp_path / "proj", tmp_path / "store"
    proj.mkdir()
    store.mkdir()
    _g(proj, "init", "-q", "-b", "main", "--separate-git-dir", str(store / "repo.git"))
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        _g(proj, "config", k, v)
    _write(proj, ".gitignore", "*.json\nsysop/runtime/\n")
    _write(proj, "a.ts", "x\n")
    _g(proj, "add", "-A")
    _g(proj, "commit", "-qm", "base")
    wt = tmp_path / "wt"
    _g(proj, "worktree", "add", "-q", str(wt), "-b", "feat")
    _write(wt, "a.json", "{}")
    r = _preserve(wt, "sysop/runtime/preserved/feat", proj)
    assert r.returncode == 0 and (proj / "sysop/runtime/preserved/feat/a.json").exists(), r.stderr
    assert not (store / "sysop").exists()
    c = _act(proj, wt, "a.json", "copy")
    assert c.returncode == 0 and (proj / "a.json").exists() and not (store / "a.json").exists(), c.stdout
    _write(wt, "b.json", "{}")
    _write(wt, "page.ts", "import './b.json'\n")
    # From a linked worktree nothing names this main checkout: the executor's label says so.
    assert ("IGNORED-REF: b.json <- page.ts:1 (not compared: the main checkout cannot be found "
            "from here)") in _run(wt).stdout


def test_preserve_reads_the_main_checkouts_ignore_rules(tmp_path):
    """The destination must be ignored where the file will sit: in the main checkout,
    whatever the branch's `.gitignore` says."""
    root = _repo(tmp_path, gitignore="*.json\n")
    wt = _worktree(root, tmp_path)
    _write(wt, ".gitignore", "*.json\nsysop/runtime/\n")
    _g(wt, "commit", "-qam", "the branch ignores the runtime dir; main does not")
    _write(wt, "x.json", "{}")
    r = _preserve(wt, "sysop/runtime/preserved/feat", root)
    assert r.returncode == 3 and "not gitignored" in r.stderr, r.stderr


def test_preserve_refuses_a_destination_linked_out_of_the_checkout(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "x.json", "{}")
    (root / "sysop/runtime").mkdir(parents=True)
    (tmp_path / "elsewhere").mkdir()
    (root / "sysop/runtime/preserved").symlink_to(tmp_path / "elsewhere")
    r = _preserve(wt, "sysop/runtime/preserved/feat", root)
    assert r.returncode == 3 and "not inside the main checkout" in r.stderr, r.stderr
    assert not any((tmp_path / "elsewhere").iterdir())


def test_a_name_holding_a_less_than_is_not_a_placeholder(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "a<b.json", "{}")
    r = _preserve(wt, "sysop/runtime/preserved/feat-<x>", root)
    assert r.returncode == 0, r.stderr
    assert (root / "sysop/runtime/preserved/feat-<x>/a<b.json").exists()


def test_an_unencodable_name_does_not_crash_the_report(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "café.json", "{}")
    _write(wt, "page.ts", "import './café.json'\n")
    env = dict(_ENV, PYTHONIOENCODING="ascii:strict")
    for args in ([str(wt), "main"], [str(wt), "--preserve", "sysop/runtime/preserved/f"]):
        r = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=root, capture_output=True,
                           text=True, env=env)
        assert r.returncode in (0, 1) and "Traceback" not in r.stderr, (args, r.stderr)


@pytest.mark.parametrize("same", [True, False])
def test_a_clone_is_checked_only_when_its_tip_is_this_repositorys_branch(tmp_path, same):
    """Round 3, lens B: the check read the clone's HEAD while Step 4a merges this
    repository's branch; a file committed only in the clone read as clean."""
    root = _repo(tmp_path)
    _g(root, "branch", "feat")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "-b", "feat", str(root), str(clone)], check=True, env=_ENV)
    for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")):
        _g(clone, "config", k, v)
    _write(clone, "q.json", "{}")
    _write(clone, "app/page.ts", "import '../q.json'\n")
    _g(clone, "add", "app/page.ts")
    _g(clone, "commit", "-qm", "work")
    if same:
        _g(root, "fetch", "-q", str(clone), "feat:feat")
    r = _run(clone, "origin/main", "--branch", "feat", cwd=root)
    if same:
        assert r.returncode == 1 and _refs(r.stdout) == ["q.json"], r.stdout + r.stderr
    else:
        assert r.returncode == 3 and "bring this repository's branch" in r.stderr, r.stderr


def test_preserve_refuses_the_main_checkout_as_workspace(tmp_path):
    root = _repo(tmp_path)
    r = _preserve(root, "sysop/runtime/preserved/x", root)
    assert r.returncode == 3 and "nothing to preserve" in r.stderr


def test_preserve_and_base_are_exclusive(tmp_path):
    root = _repo(tmp_path)
    for args in ([str(root)], [str(root), "main", "--preserve", "d"],
                 [str(root), "--preserve", "d", "--branch", "b"]):
        r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                           text=True, env=_ENV, cwd=root)
        assert r.returncode == 2, (args, r.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# Exit 3: the check did not run, and says so
# ─────────────────────────────────────────────────────────────────────────────

def test_exit_3_cases(tmp_path):
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    (wt / "sub").mkdir()
    for args, needle in (
        (["<worktree-path>", "main"], "placeholder"),
        ([str(wt), "<default branch>"], "placeholder"),
        ([str(wt), "--preserve", "sysop/runtime/preserved/<sanitized branch>"], "placeholder"),
        ([str(wt), "main", "--branch", "<branch>"], "placeholder"),
        ([str(wt), "nosuch"], "merge-base"),
        ([str(wt / "sub"), "main"], "not the top"),
        ([str(tmp_path / "absent"), "main"], "no such workspace"),
        ([str(tmp_path), "main"], "did not run"),
    ):
        r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                           text=True, env=_ENV, cwd=tmp_path)
        assert r.returncode == 3 and needle in r.stderr, (args, r.stdout, r.stderr)
        assert "IGNORED-REFS:" not in r.stdout, args


def test_an_ambient_git_dir_does_not_redirect_the_check(tmp_path):
    """git exports GIT_DIR into hooks; `-C` loses to it (BeanRider ISSUE-0048)."""
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "x.json", "{}")
    _write(wt, "app/page.ts", "import '../x.json'\n")
    other = tmp_path / "other"
    other.mkdir()
    _g(other, "init", "-q")
    env = dict(_ENV, GIT_DIR=str(other / ".git"), GIT_WORK_TREE=str(other))
    r = subprocess.run([sys.executable, str(SCRIPT), str(wt), "main"], capture_output=True,
                       text=True, env=env)
    assert r.returncode == 1 and _refs(r.stdout) == ["x.json"], r.stdout + r.stderr


# ─────────────────────────────────────────────────────────────────────────────
# The prescribed commands, extracted and run
# ─────────────────────────────────────────────────────────────────────────────

def _section(path: Path, start: str, end: str) -> str:
    text = text_of(path)
    assert text.count(start) == 1, start
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j]


STEP_2A = ("3a. **Gitignored files the branch reads.**", "\n4. Verdict:")
STEP_3B = ("**0b. Only when `SHAPE=worktree`: preserve the ignored files", "**1. Collect this branch's")
EXEC_7E = ("5b. **Check for gitignored files your work reads.**", "\n6. **Post-fix UI")
EXEC_6E = ("4c. **Check for gitignored files your work reads.**", "\n5. **Post-fix UI")


def _fenced_command(section: str) -> str:
    (cmd,) = re.findall(r"(?m)^ *```bash\n *(python3 sysop/scripts/ignored_refs\.py[^\n]*)\n *```",
                        section)
    return cmd


def _shell(cmd: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/bash", "-c", cmd], cwd=cwd, capture_output=True, text=True,
                          env=_ENV)


def _fixture_shape(tmp_path: Path) -> tuple[Path, Path]:
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    for n in ("a", "b"):
        _write(wt, f"app/fixtures/{n}.json", "{}")
    _write(wt, "app/page.ts", "import a from './fixtures/a.json'\nimport b from './fixtures/b.json'\n")
    _g(wt, "commit", "-qam", "work")
    return root, wt


def test_step_2a_command_runs_from_the_repo_root_and_names_both_files(tmp_path):
    root, wt = _fixture_shape(tmp_path)
    cmd = _fenced_command(_section(CLOSE, *STEP_2A))
    assert cmd == ('python3 sysop/scripts/ignored_refs.py "<workspace>" "<default branch>" '
                   '--branch "<branch>"'), cmd
    r = _shell(cmd.replace("<workspace>", str(wt)).replace("<default branch>", "main")
               .replace("<branch>", "feat"), root)
    assert r.returncode == 1 and _refs(r.stdout) == ["app/fixtures/a.json", "app/fixtures/b.json"], \
        r.stdout + r.stderr


def _action_block() -> str:
    sec = _section(CLOSE, *STEP_2A)
    (block,) = re.findall(r"(?m)^ *```bash\n *(python3 sysop/scripts/feature_branch\.py keep-ignored "
                          r"\"<workspace>\" \"<path>\" \"<commit or copy>\")\n *```", sec)
    return block


def _act(root: Path, ws: Path, rel: str, action: str) -> subprocess.CompletedProcess:
    # The fence as written, pointed at this tree's script: step 3a's commit-or-copy program
    # was a heredoc until Phase 387 (`Q-409` P3), and not every fixture carries `sysop/scripts/`.
    cmd = (_action_block().replace("<workspace>", str(ws)).replace("<path>", rel)
           .replace("<commit or copy>", action)
           .replace("python3 sysop/scripts/", f"python3 {SCRIPT.parent}/"))
    return _shell(cmd, root)


def test_step_2a_commit_answer_makes_the_file_tracked_and_the_check_clean(tmp_path):
    root, wt = _fixture_shape(tmp_path)
    _write(wt, "unrelated.txt", "staged but not part of the answer")
    _g(wt, "add", "unrelated.txt")
    for rel in ("app/fixtures/a.json", "app/fixtures/b.json"):
        r = _act(root, wt, rel, "commit")
        assert r.returncode == 0 and r.stdout.startswith("COMMITTED: " + rel), r.stdout + r.stderr
    assert _g(wt, "ls-tree", "-r", "--name-only", "HEAD", "app/fixtures").split() == \
        ["app/fixtures/a.json", "app/fixtures/b.json"]
    assert _g(wt, "log", "-1", "--format=%s") == "fix: commit app/fixtures/b.json, which the branch reads"
    assert "unrelated.txt" not in _g(wt, "ls-tree", "-r", "--name-only", "HEAD"), \
        "the answer committed something else the worktree had staged"
    assert _shell(_fenced_command(_section(CLOSE, *STEP_2A)).replace("<workspace>", str(wt))
                  .replace("<default branch>", "main").replace("<branch>", "feat"), root).returncode == 0


def test_step_2a_commit_answer_refuses_the_main_checkout(tmp_path):
    """Phase 430's round (lens A): step 3a offers `commit` only for a linked worktree, and the
    script committed onto the main checkout's branch when called there anyway."""
    root, wt = _fixture_shape(tmp_path)
    _write(root, "app/fixtures/a.json", "{}")
    head = _g(root, "rev-parse", "HEAD")
    r = _act(root, root, "app/fixtures/a.json", "commit")
    assert r.returncode == 5 and r.stdout.startswith("REFUSED: "), r.stdout + r.stderr
    assert _g(root, "rev-parse", "HEAD") == head


def test_step_2a_copy_answer_copies_and_never_overwrites(tmp_path):
    root, wt = _fixture_shape(tmp_path)
    r = _act(root, wt, "app/fixtures/a.json", "copy")
    assert r.returncode == 0 and r.stdout.startswith("COPIED: app/fixtures/a.json"), r.stdout + r.stderr
    assert (root / "app/fixtures/a.json").read_text() == "{}"
    assert "a.json <- app/page.ts:1 (the main checkout has an identical copy)" in _run(wt).stdout
    again = _act(root, wt, "app/fixtures/a.json", "copy")
    assert again.returncode == 0 and again.stdout.startswith("ALREADY:"), again.stdout
    _write(root, "app/fixtures/b.json", '{"main": 1}')
    r = _act(root, wt, "app/fixtures/b.json", "copy")
    assert r.returncode == 5 and "REFUSED" in r.stdout, r.stdout
    assert (root / "app/fixtures/b.json").read_text() == '{"main": 1}'


def test_step_2a_copy_answer_on_a_symlink_to_the_main_checkouts_file(tmp_path):
    """Round 2, lens C: one consumer's `frontend/.env` is a symlink to the root `.env`; the copy
    raised `SameFileError` (exit 1)."""
    root = _repo(tmp_path, gitignore=".env\n")
    _write(root, ".env", "S=1")
    wt = _worktree(root, tmp_path)
    (wt / "frontend").mkdir()
    (root / "frontend").mkdir()
    (root / "frontend/.env").symlink_to(root / ".env")
    (wt / "frontend/.env").symlink_to(root / ".env")
    r = _act(root, wt, "frontend/.env", "copy")
    assert r.returncode == 0 and r.stdout.startswith("ALREADY:"), r.stdout + r.stderr


def test_step_2a_copy_answer_refuses_a_link_into_the_worktree_or_a_dangling_one(tmp_path):
    root, wt = _fixture_shape(tmp_path)
    (root / "app/fixtures").mkdir(parents=True)
    (root / "app/fixtures/a.json").symlink_to(wt / "app/fixtures/a.json")
    r = _act(root, wt, "app/fixtures/a.json", "copy")
    assert r.returncode == 5 and "REFUSED" in r.stdout, r.stdout
    (root / "app/fixtures/b.json").symlink_to(tmp_path / "OUTSIDE.json")
    r = _act(root, wt, "app/fixtures/b.json", "copy")
    assert r.returncode == 5 and not (tmp_path / "OUTSIDE.json").exists(), r.stdout


def test_step_2a_copy_answer_reports_an_os_error_instead_of_a_traceback(tmp_path):
    root, wt = _fixture_shape(tmp_path)
    _write(root, "app/fixtures", "a file where a directory is needed")
    r = _act(root, wt, "app/fixtures/a.json", "copy")
    assert r.returncode == 4 and r.stdout.startswith("FAILED:") and "Traceback" not in r.stderr


def test_step_2a_commit_answer_refuses_a_symlink(tmp_path):
    root = _repo(tmp_path, gitignore=".venv\n")
    wt = _worktree(root, tmp_path)
    (root / ".venv").mkdir()
    (wt / ".venv").symlink_to(root / ".venv")
    r = _act(root, wt, ".venv", "commit")
    assert r.returncode == 4 and "symlink" in r.stdout
    assert ".venv" not in _g(wt, "ls-tree", "-r", "--name-only", "HEAD")


def test_step_2a_copy_answer_reaches_the_callers_checkout_from_a_clone(tmp_path):
    root = _repo(tmp_path)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(root), str(clone)], check=True, env=_ENV)
    _write(clone, "q.json", "{}")
    r = _act(root, clone, "q.json", "copy")
    assert r.returncode == 0 and (root / "q.json").exists(), r.stdout + r.stderr


def test_step_2a_action_block_refuses_a_placeholder(tmp_path):
    root, wt = _fixture_shape(tmp_path)
    cmd = (_action_block().replace("<workspace>", str(wt)).replace("<path>", "app/fixtures/a.json")
           .replace("python3 sysop/scripts/", f"python3 {SCRIPT.parent}/"))
    r = _shell(cmd, root)
    assert r.returncode == 3 and "placeholder" in r.stdout, r.stdout


def test_step_2a_recommends_keeping_unless_the_path_is_a_fixture():
    """Wade, 2026-10-02: the reporting consumer's `*.json` rule sits in its secrets section, so a
    name test cannot tell a key from a fixture; committing is recommended only for one."""
    sec = _section(CLOSE, *STEP_2A)
    assert ("Mark `Commit it to the branch` (Recommended) when it is offered and a component "
            "of the path contains `fixture`, `testdata` or `test_data`, or is `__snapshots__`, "
            "in any case; for such a path where `Commit` is not offered, mark `Reject the "
            "branch` (Recommended); otherwise mark `Keep it ignored` (Recommended).") in sec


def test_step_2a_an_unanswered_line_skips_the_branch_in_every_shape():
    """Round 2, lenses B and C: the identical-copy, clone and `--branch` shapes merged an
    unanswered hit, because only step 0b kept a worktree."""
    sec = _section(CLOSE, *STEP_2A)
    assert "**A line left unanswered makes the verdict SKIP — ignored file unanswered**, whatever the workspace's shape" in sec
    assert "`Hold`, or an away result, makes the verdict SKIP as above." in sec


def test_step_3b_0b_preserves_before_the_remove(tmp_path):
    root, wt = _fixture_shape(tmp_path)
    cmd = _fenced_command(_section(CLOSE, *STEP_3B))
    assert cmd == ('python3 sysop/scripts/ignored_refs.py "<worktree-path>" --preserve '
                   '"sysop/runtime/preserved/<sanitized branch>"'), cmd
    r = _shell(cmd.replace("<worktree-path>", str(wt)).replace("<sanitized branch>", "feat"), root)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["git", "worktree", "remove", str(wt)], cwd=root, check=True, env=_ENV)
    for n in ("a", "b"):
        assert (root / f"sysop/runtime/preserved/feat/app/fixtures/{n}.json").exists()


def test_step_3b_0b_comes_before_the_collect_and_the_remove():
    """A refusal after the collect would need the rollback; before it, nothing to undo."""
    text = text_of(CLOSE)
    at = text.index(STEP_3B[0])
    assert at < text.index(STEP_3B[1]) < text.index('git worktree remove "<worktree-path>"')
    assert text.index("## Step 3b: Prepare Worktrees for Merge") < at


@pytest.mark.parametrize("site", [EXEC_7E, EXEC_6E], ids=["claim-task 7e", "auto-build 6e"])
def test_the_executors_command_runs_in_the_worktree_before_a_commit(tmp_path, site):
    path = CLAIM if site is EXEC_7E else AUTO
    sec = _section(path, *site)
    (cmd,) = re.findall(r"run `(python3 sysop/scripts/ignored_refs\.py[^`]*)`", sec)
    assert cmd == "python3 sysop/scripts/ignored_refs.py . <default branch>", cmd
    root = _repo(tmp_path)
    wt = _worktree(root, tmp_path)
    _write(wt, "app/fixtures/a.json", "{}")
    _write(wt, "app/page.ts", "import a from './fixtures/a.json'\n")
    r = _shell(cmd.replace("<default branch>", "main"), wt)
    assert r.returncode == 1 and _refs(r.stdout) == ["app/fixtures/a.json"], r.stdout + r.stderr


def test_the_executor_items_sit_after_the_gates_and_before_the_commit():
    text = CLAIM.read_text(encoding="utf-8")
    assert (text.index("5. **Run the consumer's pre-merge verification gates.**")
            < text.index(EXEC_7E[0]) < text.index("7. **Commit** — a SINGLE commit"))
    text = AUTO.read_text(encoding="utf-8")
    assert (text.index("4b. **Run the consumer's pre-merge verification gates.**")
            < text.index(EXEC_6E[0]) < text.index("5b. **Invoke `/document-work --non-interactive`**"))


def test_the_orchestrators_relay_the_executors_quotes():
    """Round 2, lens B: the executors quote their hits, and without a relay the quotes
    reached no human on `/auto-build`."""
    claim = CLAIM.read_text(encoding="utf-8")
    at = claim.index("**Then print any `IGNORED-REF:` lines the executor quoted (Step 7e item 5b) under the report below.**")
    assert claim.index("## Step 8: Receive the executor envelope") < at < claim.index("### Step 8b")
    auto = AUTO.read_text(encoding="utf-8")
    assert ("**Then copy any `IGNORED-REF:` lines the agent quoted (Step 7c item 4c) into that "
            "task's Step 8 `Notes`.**") in auto


def test_every_site_declares_the_rule_it_runs_under():
    rule = "Bash(python3 sysop/scripts/ignored_refs.py:*)"
    assert rule in json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]["allow"]
    for path, head in ((CLOSE, "## Step 1: Gather State"), (CLAIM, "## Step 1: Parse Argument"),
                       (AUTO, "## Step 0")):
        text = text_of(path)
        guard = text[text.index("## Pre-flight: Permission Guard"):text.index(head)]
        assert f"`{rule}`" in guard, path


def test_workflow_lists_the_script():
    rows = [ln for ln in WF.read_text(encoding="utf-8").splitlines()
            if ln.startswith("| `ignored_refs.py ")]
    assert len(rows) == 1
    row = rows[0]
    for needle in ("`ignored_refs.py <WORKSPACE> <BASE> [--branch <NAME>]`",
                   "`ignored_refs.py <WORKSPACE> --preserve <DEST>`",
                   "Exit 0 none or copied, 1 found, 2 usage, 3 did not run |",
                   "an unanswered hit SKIPs the branch",
                   "referenced or not, to DEST, which must be gitignored there"):
        assert needle in row, needle


# ─────────────────────────────────────────────────────────────────────────────
# The decided text (Wade's ruling, 2026-09-30, and the scope answer, 2026-10-01)
# ─────────────────────────────────────────────────────────────────────────────

from _reversal import slice_between  # noqa: E402
from test_fix_in_branch_tier import (_anchor_count, _pin_hash, _pin_liveness, _pin_program,  # noqa: E402
                                     _pin_norm, _pin_span)

SPANS = {
    "2a step 3a": (CLOSE, STEP_2A[0], STEP_2A[1], False),
    "3b step 0b": (CLOSE, STEP_3B[0], STEP_3B[1], False),
    "step 8 ignored references": (CLOSE, "Ignored references: <N> (or \"none\")", "\n\n", True),
    "claim-task 7e item 5b": (CLAIM, EXEC_7E[0], EXEC_7E[1], False),
    "auto-build 7c item 4c": (AUTO, EXEC_6E[0], EXEC_6E[1], False),
}

PINS = {
    # Regenerate with:  .venv/bin/python3 -c "import sys; sys.path.insert(0,'tests'); import test_ignored_refs as T; T._print_pins()"
    "2a step 3a": "d8da2d56481da7fa",  # Phase 430's round (lens A): `keep-ignored commit` refuses (exit 5) outside a linked worktree. Phase 430 (P5): the answers moved to `steps/2a-ignored-refs.md`, read spliced, behind a stub on the check's non-zero exit. Phase 387: the span plus feature_branch.py keep-ignored, the heredoc moved verbatim (`Q-409` P3). The program is appended fenced, so its indentation counts (Phase 387's round). Phase 380: the commit-or-copy heredoc's env-strip is `dict(...)`, which dontAsk admits (`Q-664`). Phase 362: the --dry-run arm (no commit or copy). Before it, Phase 355: the --clone remedy and workspace lookup name Step 1-pre; round 2 added the branch_tip: re-run
    "3b step 0b": "8f4d1258b11128a2",
    "step 8 ignored references": "374cb27c300286f9",
    "claim-task 7e item 5b": "e38f488e999fbf2d",
    "auto-build 7c item 4c": "c608b7001314d134",
}


def _located(label: str) -> tuple[str, str, int]:
    path, start, end, _ = SPANS[label]
    text = text_of(path)
    span = slice_between(text, start, end, label)
    return text, span, text.index(span)


# Since Phase 387 (`Q-409` P3) step 3a's commit-or-copy program is a shipped script, so its
# pin covers the span plus the program it runs.
_PROGRAMS = {"2a step 3a": lambda: __import__("_shipped_scripts").subcommand_body("feature_branch.py", "keep-ignored")}


def _span(label: str) -> str:
    text, span, at = _located(label)
    span = _pin_span(SPANS[label][0], text, at, span)
    assert len(_pin_norm(span)) > 60, f"{label}: the pinned span is nearly empty — anchors drifted"
    return span


def _pinned(label: str) -> str:
    """What a pin hashes: the span, plus the program a moved heredoc became (Phase 387)."""
    return _span(label) + _pin_program(_PROGRAMS[label]()) if label in _PROGRAMS else _span(label)


def _print_pins() -> None:
    for label in SPANS:
        print(f'    "{label}": "{_pin_hash(_pinned(label))}",')


@pytest.mark.parametrize("label", sorted(SPANS))
def test_the_decided_text_is_pinned(label: str) -> None:
    got = _pin_hash(_pinned(label))
    assert label in PINS, f'{label}: no pin recorded; add "{label}": "{got}"'
    assert got == PINS[label], (
        f"{label} changed (hash {got}, pinned {PINS[label]}). Phase 354 decided this text. "
        "If the edit is deliberate, move the pin in the same commit and record why.")


@pytest.mark.parametrize("label", sorted(SPANS))
def test_every_span_start_anchor_is_unique(label: str) -> None:
    path, start, _, _ = SPANS[label]
    assert _anchor_count(text_of(path), start) == 1, label


@pytest.mark.parametrize("label", sorted(SPANS))
def test_every_span_is_live(label: str) -> None:
    text, _, at = _located(label)
    problem = _pin_liveness(SPANS[label][0], text, at, SPANS[label][3])
    assert problem is None, f"{label} {problem}"


def test_every_pin_has_a_span() -> None:
    assert set(PINS) == set(SPANS), set(PINS) ^ set(SPANS)
