"""The pack grep checks skip test files by name and directory, never by substring.

Five checks in the python and postgres packs used ``exclude: ["*test*"]``. The
runner passes ``exclude:`` to ``grep --exclude``, and the two greps read it
differently, both badly for that glob:

* GNU grep matches a recursed file's basename, so ``*test*`` skipped production
  modules such as ``latest_rates.py``, ``stress_test.py``, ``contest.py``;
* macOS grep matches the basename OR the whole path (``*`` crossing ``/``), and
  the runner passes absolute operands, so a checkout whose path holds "test"
  anywhere (``~/latest/``, a user named ``tester``, pytest's own ``tmp_path``)
  scanned nothing at all — two of the five are ``severity: critical``.

The ruled replacement is ``exclude: ["test_*.py", "conftest.py"]`` plus
``exclude_dir: ["tests", "test"]``. ``*_test.py`` is deliberately absent: it
would still skip ``stress_test.py``.

What this module cannot see: a consumer's own ``.claude/checks.project.yml``
override of one of these ids (it replaces the entry wholesale and keeps whatever
glob the consumer wrote), and an install that has not run ``install.sh
--update`` (its ``.claude/checks.yml`` is a concat output of the fragments and
keeps the old glob until regenerated). The behavioural test runs whichever
``grep`` is first on PATH, so the whole-path half is exercised only on macOS.
"""

import fnmatch
import os
import re
from pathlib import Path

import pytest
import yaml

import run_checks.grep as grep_mod
import run_checks_impl as rci

REPO_ROOT = Path(__file__).resolve().parents[1]
FRAGMENTS = sorted(REPO_ROOT.glob("packs/*/companion/checks.yml.fragment")) + [
    REPO_ROOT / "core/companion/checks.yml.fragment"
]
WORKFLOW = REPO_ROOT / "core/companion/docs/WORKFLOW.md"

RULED_EXCLUDE = ["test_*.py", "conftest.py"]
RULED_EXCLUDE_DIR = ["tests", "test"]
RULED_IDS = {
    "logger-fstring",
    "app-env-prod-without-staging",
    "sql-fstring",
    "missing-writer-engine-guard",
    "nosemgrep-sqlalchemy-pair",
}

# Production files whose names hold "test" as a substring.
PRODUCTION = ["stress_test.py", "latest_rates.py", "contest.py", "attestation.py", "plain.py"]
# Test files, by name and by directory.
TESTS = ["test_foo.py", "conftest.py", "tests/helpers.py", "test/x.py"]

# One line per check that trips each of the five patterns.
BODY = (
    'logger.info(f"x {y}")\n'
    'if APP_ENV == "prod": pass\n'
    'q = f"SELECT * FROM {t}"\n'
    "with writer_engine.begin() as c: pass\n"
    "x = 1  # nosemgrep: sqlalchemy-execute-raw-query\n"
)

PLACEHOLDERS = {"<api module>": "api", "<scripts dir>": "scripts", "<datajobs dir>": "datajobs"}


def _checks(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["checks"]


def _all_checks():
    return [(p, c) for p in FRAGMENTS for c in _checks(p)]


def _ruled_checks():
    found = {c["id"]: c for _p, c in _all_checks() if c.get("id") in RULED_IDS}
    assert set(found) == RULED_IDS, sorted(RULED_IDS - set(found))
    return found


def _localized(check):
    c = dict(check)
    paths = []
    for p in c["paths"]:
        for k, v in PLACEHOLDERS.items():
            p = p.replace(k, v)
        paths.append(p)
    c["paths"] = paths
    return c


def _build_tree(root):
    for rel in PRODUCTION + TESTS:
        p = root / "api" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(BODY, encoding="utf-8")


def _reported_files(findings):
    return {fl.split(":", 1)[0] for _cid, fl, _msg, _ident in findings}


# ── the shipped shape ────────────────────────────────────────────────────────


def test_the_five_checks_carry_the_ruled_pair():
    for cid, c in _ruled_checks().items():
        assert c.get("exclude") == RULED_EXCLUDE, cid
        assert c.get("exclude_dir") == RULED_EXCLUDE_DIR, cid


def test_the_ruled_pair_is_carried_by_exactly_those_five():
    """Derived, not counted: every check naming ``test_*.py`` is one of the five."""
    carrying = {c["id"] for _p, c in _all_checks() if "test_*.py" in (c.get("exclude") or [])}
    assert carrying == RULED_IDS


def _skips(glob, path):
    """True when either grep would skip ``path`` (absolute) for ``--exclude glob``.

    GNU: the basename. macOS: the basename or the whole path, ``*`` crossing ``/``
    (``fnmatchcase`` does the same, so it models that rule).
    """
    return fnmatch.fnmatchcase(os.path.basename(path), glob) or fnmatch.fnmatchcase(path, glob)


@pytest.mark.parametrize("name", PRODUCTION + ["latest.tsx", "contest.ts", "protest_view.tsx"])
def test_no_shipped_exclude_glob_skips_a_production_name(name):
    """No ``exclude:`` glob in any shipped fragment skips a production file whose
    name merely contains "test", under either grep's rule, from a checkout that
    sits below a directory whose name contains "test"."""
    offenders = []
    for path, c in _all_checks():
        for glob in c.get("exclude") or []:
            for root in c.get("paths") or []:
                full = f"/srv/latest/repo/{root.rstrip('/')}/{name}"
                if _skips(glob, full):
                    offenders.append(f"{path.relative_to(REPO_ROOT)} {c['id']}: {glob!r} skips {full}")
    assert not offenders, "\n".join(offenders)


def test_workflow_md_example_matches_the_ruled_pair():
    text = WORKFLOW.read_text(encoding="utf-8")
    head = "**Format** (`.claude/checks.yml`):"
    assert text.count(head) == 1
    block = re.search(r"```yaml\n(.*?)```", text[text.index(head):], re.S).group(1)
    examples = yaml.safe_load(block)["checks"]
    sql = {c["id"]: c for c in examples}["sql-fstring"]
    assert sql.get("exclude") == RULED_EXCLUDE
    assert sql.get("exclude_dir") == RULED_EXCLUDE_DIR
    assert not [c["id"] for c in examples if "*test*" in (c.get("exclude") or [])]


# ── behaviour, through the real grep stage ───────────────────────────────────


@pytest.fixture
def tree(tmp_path):
    """A checkout under a directory named ``latest`` — "test" is in its path."""
    root = tmp_path / "latest" / "repo"
    _build_tree(root)
    return root


@pytest.mark.parametrize("cid", sorted(RULED_IDS))
def test_each_check_scans_production_names_and_skips_tests(tree, cid):
    check = _localized(_ruled_checks()[cid])
    got = _reported_files(rci.run_check(check, str(tree)))
    assert got == {f"api/{n}" for n in PRODUCTION}, sorted(got)


@pytest.mark.parametrize("cid", sorted(RULED_IDS))
def test_the_file_walk_scan_path_agrees_with_grep(tree, cid):
    """``_iter_check_files`` (basename ``fnmatch``) skips the same files grep does."""
    check = _localized(_ruled_checks()[cid])
    walked = {
        os.path.relpath(p, tree)
        for p in grep_mod._iter_check_files(
            check["paths"], check["include"], check["exclude"], str(tree),
            check["exclude_dir"],
        )
    }
    grepped = _reported_files(rci.run_check(check, str(tree)))
    assert walked == grepped == {f"api/{n}" for n in PRODUCTION}


# ── the nextjs-react sibling: a test directory goes in exclude_dir ───────────


def test_createobjecturl_leak_skips_a_tests_directory_on_either_grep(tmp_path):
    """``*__tests__*`` in ``exclude:`` never skipped a file inside ``__tests__/``
    on GNU grep, which matches the file name only. The directory is now an
    ``exclude_dir:`` entry, which both greps match by directory name."""
    check = {c["id"]: c for _p, c in _all_checks()}["createobjecturl-leak"]
    assert "*__tests__*" not in (check.get("exclude") or [])
    assert "__tests__" in (check.get("exclude_dir") or [])
    c = dict(check)
    c["paths"] = [p.replace("<app dir>", "app") for p in c["paths"]]
    root = tmp_path / "repo"
    for rel in ("app/Upload.tsx", "app/__tests__/Blob.tsx", "app/Upload.test.tsx"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("const u = URL.createObjectURL(b);\n", encoding="utf-8")
    assert _reported_files(rci.run_check(c, str(root))) == {"app/Upload.tsx"}


# ── a relative --repo-root ───────────────────────────────────────────────────


def test_a_relative_repo_root_still_finds_a_grep_hit(tmp_path):
    """The grep stage resolved ``paths:`` from the process cwd and then ran grep
    with ``cwd=repo_root``, so a relative root was doubled and the check read
    ``executed`` with 0 findings. The CLI now resolves the root first."""
    import subprocess
    import sys

    root = tmp_path / "proj"
    (root / ".claude").mkdir(parents=True)
    (root / "api").mkdir()
    (root / "api" / "q.py").write_text('q = f"SELECT * FROM {t}"\n', encoding="utf-8")
    (root / ".claude" / "checks.yml").write_text(
        "checks:\n"
        "  - id: sql-fstring\n"
        "    name: f-string SQL\n"
        "    category: correctness\n"
        "    severity: critical\n"
        '    paths: ["api/"]\n'
        '    include: ["*.py"]\n'
        "    pattern: 'f[\"](SELECT)'\n"
        "    description: x\n",
        encoding="utf-8",
    )
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT / "core/companion/scripts"))
    out = subprocess.run(
        [sys.executable, "-m", "run_checks", "--repo-root", "proj"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    assert "api/q.py" in out.stdout, (out.returncode, out.stdout, out.stderr)


def test_no_shipped_exclude_glob_is_an_unanchored_substring():
    """The class is any glob holding ``*word*`` (``*spec*``, ``*spec*.py``), not
    only ``*test*``: it skips every
    production file whose name happens to contain the word, and on macOS any
    file whose checkout path does. A directory goes in ``exclude_dir:``; a file
    glob anchors to a prefix or suffix of the name."""
    offenders = [
        f"{p.relative_to(REPO_ROOT)} {c['id']}: {g!r}"
        for p, c in _all_checks()
        for g in c.get("exclude") or []
        if re.search(r"\*[^*/]+\*", g)
    ]
    assert not offenders, "\n".join(offenders)
