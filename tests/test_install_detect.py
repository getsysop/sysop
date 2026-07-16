"""Integration tests for install.sh's stack auto-detection (Phase 75).

`--packs auto` scans the target tree and pre-selects the matching *populated*
packs; the interactive picker offers the same set as its blank-default. The
detection logic lives in bash (`detect_packs` / `_detect_has_file` /
`_detect_manifest_mentions`) inside install.sh, so these tests drive the real
installer in `--dry-run` against scratch git consumers and assert on the
resolved plan. `--dry-run` keeps them fast (no writes) while still exercising
detection → dependency resolution end-to-end; one non-dry-run test locks the
lock-file record.

Design intent under test: PRECISION over recall — a wrong pre-selection is
worse than none — so the negative cases (vendored files, a stray root .sql, a
react-free package.json) are as load-bearing as the positive ones.

The interactive picker's blank-accepts-detected mapping is not covered here: it
reads from /dev/tty, so it shares the un-tested surface of every other
`prompt_*` function. `--packs auto` is the automated seam for the same
`detect_packs` machinery.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_consumer(root, files):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run(target, *extra):
    env = dict(os.environ)
    # Match the concat suite: put the pytest interpreter's dir on PATH so
    # pick_python_with_yaml() finds a pyyaml-capable python3.
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    result = subprocess.run(
        ["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, (
        f"install.sh failed (rc={result.returncode})\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    return result


def _run_expect(target, expected_rc, *extra):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    result = subprocess.run(
        ["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == expected_rc, (
        f"expected rc={expected_rc}, got {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    return result


def _plan_packs(stdout):
    """The resolved SELECTED_PACKS from the plan summary, as a set (deps
    included, topologically ordered in the output). '(core only)' → set()."""
    m = re.search(r"^\s*packs:\s+(.*)$", stdout, re.MULTILINE)
    assert m, f"no plan packs line in:\n{stdout}"
    val = m.group(1).strip()
    if val == "(core only)":
        return set()
    return set(val.split())


def _detected(stdout):
    """The raw pre-dependency detection from the `→ auto-detected packs:` echo,
    as a set. Absent line (no signals) → set()."""
    m = re.search(r"auto-detected packs:\s+(.*)$", stdout, re.MULTILINE)
    if not m:
        assert "no populated-pack signals" in stdout
        return set()
    return {p.strip() for p in m.group(1).split(",")}


def _detect(tmp_path, name, files):
    root = _make_consumer(tmp_path / name, files)
    return _run(root, "--dry-run", "--packs", "auto")


class TestPositiveDetection:
    def test_python_via_pyproject(self, tmp_path):
        r = _detect(tmp_path, "py", {"pyproject.toml": ""})
        assert _detected(r.stdout) == {"python"}
        assert _plan_packs(r.stdout) == {"python"}

    def test_python_via_requirements(self, tmp_path):
        r = _detect(tmp_path, "pyreq", {"requirements.txt": "requests\n"})
        assert "python" in _plan_packs(r.stdout)

    def test_python_via_bare_py_file(self, tmp_path):
        r = _detect(tmp_path, "pybare", {"app.py": "print(1)\n", "README.md": "#\n"})
        assert _plan_packs(r.stdout) == {"python"}

    def test_nextjs_react_via_package_json(self, tmp_path):
        r = _detect(tmp_path, "nx", {"package.json": '{"dependencies":{"react":"18","next":"14"}}'})
        assert _detected(r.stdout) == {"nextjs-react"}
        assert _plan_packs(r.stdout) == {"nextjs-react"}

    def test_nextjs_react_via_next_config(self, tmp_path):
        r = _detect(tmp_path, "nxc", {"next.config.js": "module.exports={}\n", "README.md": "#\n"})
        assert "nextjs-react" in _plan_packs(r.stdout)

    def test_postgres_via_alembic_pulls_python(self, tmp_path):
        r = _detect(tmp_path, "pg", {"alembic.ini": ""})
        assert _detected(r.stdout) == {"postgres"}
        assert _plan_packs(r.stdout) == {"python", "postgres"}  # postgres → sysop-python

    def test_postgres_via_compose(self, tmp_path):
        r = _detect(
            tmp_path, "pgc",
            {"docker-compose.yml": "services:\n  db:\n    image: postgres:16\n"},
        )
        assert "postgres" in _plan_packs(r.stdout)

    def test_postgres_via_migrations_sql(self, tmp_path):
        r = _detect(tmp_path, "pgm", {"db/migrations/001_init.sql": "CREATE TABLE t();\n"})
        assert "postgres" in _detected(r.stdout)

    def test_llm_via_requirements(self, tmp_path):
        r = _detect(tmp_path, "llm", {"requirements.txt": "anthropic==0.40\n"})
        assert "llm" in _detected(r.stdout)
        assert "llm" in _plan_packs(r.stdout)

    def test_beancount_via_ledger(self, tmp_path):
        r = _detect(tmp_path, "bc", {"main.beancount": ";; ledger\n"})
        assert _detected(r.stdout) == {"beancount"}
        assert _plan_packs(r.stdout) == {"python", "beancount"}  # beancount → sysop-python

    def test_multi_signal_union(self, tmp_path):
        r = _detect(tmp_path, "multi", {
            "pyproject.toml": "",
            "package.json": '{"dependencies":{"next":"14"}}',
            "ledger.bean": ";;\n",
        })
        assert _detected(r.stdout) == {"python", "nextjs-react", "beancount"}
        assert _plan_packs(r.stdout) == {"python", "nextjs-react", "beancount"}

    def test_postgres_via_compose_v2_filename(self, tmp_path):
        # Compose v2's default filename drops the docker- prefix.
        r = _detect(tmp_path, "pgv2", {"compose.yaml": "services:\n  db:\n    image: postgres:16\n"})
        assert "postgres" in _plan_packs(r.stdout)

    def test_langchain_cohere_is_llm(self, tmp_path):
        # A real dependency that CONTAINS the 'cohere' token still detects (the
        # boundary anchor rejects 'coherence', not legitimate SDK names).
        r = _detect(tmp_path, "lcc", {"requirements.txt": "langchain-cohere==0.3\n"})
        assert "llm" in _detected(r.stdout)


class TestPrecision:
    """A wrong pre-selection is worse than none — lock the negatives."""

    def test_no_signals_is_core_only(self, tmp_path):
        r = _detect(tmp_path, "none", {"README.md": "# hi\n", "LICENSE": "MIT\n"})
        assert _detected(r.stdout) == set()
        assert _plan_packs(r.stdout) == set()

    def test_vendored_tsx_pruned(self, tmp_path):
        r = _detect(tmp_path, "nm", {"node_modules/foo/index.tsx": "x\n", "README.md": "#\n"})
        assert "nextjs-react" not in _plan_packs(r.stdout)

    def test_vendored_py_pruned(self, tmp_path):
        r = _detect(tmp_path, "venv", {".venv/lib/mod.py": "x\n", "README.md": "#\n"})
        assert _plan_packs(r.stdout) == set()

    def test_stray_root_sql_is_not_postgres(self, tmp_path):
        r = _detect(tmp_path, "stray", {"schema.sql": "SELECT 1;\n", "README.md": "#\n"})
        assert "postgres" not in _plan_packs(r.stdout)

    def test_compose_without_postgres_service_is_not_postgres(self, tmp_path):
        # The compose arm greps the file for 'postgres' — a redis-only compose
        # names no postgres service, so it must not false-select the pack (the
        # positive-control twin of test_postgres_via_compose above).
        r = _detect(tmp_path, "rediscompose",
                    {"compose.yaml": "services:\n  cache:\n    image: redis:7\n",
                     "README.md": "#\n"})
        assert "postgres" not in _plan_packs(r.stdout)
        assert _plan_packs(r.stdout) == set()

    def test_react_free_package_json_is_not_nextjs(self, tmp_path):
        r = _detect(tmp_path, "plainjs", {"package.json": '{"devDependencies":{"eslint":"9"}}'})
        assert _plan_packs(r.stdout) == set()

    def test_coherence_dep_is_not_llm(self, tmp_path):
        # 'coherence' must not substring-trip the 'cohere' llm token (S1). A
        # python signal is present, so python is expected — llm is not.
        r = _detect(tmp_path, "coh", {"requirements.txt": "coherence==1.0\n"})
        assert "llm" not in _plan_packs(r.stdout)
        assert _plan_packs(r.stdout) == {"python"}

    def test_vendored_venv_manifest_is_not_llm(self, tmp_path):
        # A gitignored on-disk .venv/ holding a manifest that names an LLM SDK
        # must be pruned by _detect_manifest_mentions, not counted (S2). Kept at
        # depth 1 under .venv so it would be in scope but for the prune.
        r = _detect(tmp_path, "venvllm", {".venv/requirements.txt": "anthropic==0.40\n", "README.md": "#\n"})
        assert "llm" not in _plan_packs(r.stdout)

    def test_vendored_venv_migrations_is_not_postgres(self, tmp_path):
        r = _detect(tmp_path, "venvpg", {".venv/db/migrations/001.sql": "CREATE TABLE t();\n", "README.md": "#\n"})
        assert "postgres" not in _plan_packs(r.stdout)


class TestPacksProvidedGate:
    """The PACKS_PROVIDED fix (Phase 75): an explicit `--packs ''`, or a
    `--packs auto` that detects nothing, installs core only and does NOT fall
    through to the interactive picker — which, non-interactive, would abort with
    a TTY error. rc==0 (asserted by _run) is the real guard here."""

    def test_explicit_empty_is_core_only_no_prompt(self, tmp_path):
        # A python signal is present, but --packs '' is an explicit override.
        root = _make_consumer(tmp_path / "empty", {"pyproject.toml": ""})
        r = _run(root, "--dry-run", "--packs", "")
        assert _plan_packs(r.stdout) == set()

    def test_auto_with_no_signals_is_core_only_no_prompt(self, tmp_path):
        root = _make_consumer(tmp_path / "autonone", {"README.md": "# hi\n"})
        r = _run(root, "--dry-run", "--packs", "auto")
        assert "no populated-pack signals" in r.stdout
        assert _plan_packs(r.stdout) == set()


class TestAutoSentinel:
    """`auto` is a standalone sentinel, not a pack token."""

    def test_auto_combined_with_pack_errors(self, tmp_path):
        # `--packs auto,python` must fail loud (rc 2), not die inside
        # resolve_packs with a confusing "unknown pack: auto".
        root = _make_consumer(tmp_path / "combo", {"pyproject.toml": ""})
        r = _run_expect(root, 2, "--dry-run", "--packs", "auto,python")
        assert "must be used on its own" in r.stderr


class TestLockRecordsDetected:
    """One non-dry-run: --packs auto records the RESOLVED packs in the lock so a
    future --update re-merges the same fragments."""

    def test_lock_records_resolved_packs(self, tmp_path):
        root = _make_consumer(tmp_path / "lockauto", {"main.beancount": ";;\n"})
        _run(root, "--packs", "auto")
        lock = (root / ".claude/sysop.lock").read_text()
        assert '"beancount"' in lock
        assert '"python"' in lock  # dependency was resolved before the lock write
