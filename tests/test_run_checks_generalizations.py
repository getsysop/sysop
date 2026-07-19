"""Sysop-original tests for the discovery helpers added in Phase 47b.

gdp's tests cover `_run_eslint` and `_run_pip_audit` only — the helpers
(`_find_frontend_dir`, `_find_requirements_files`) are sysop-original
generalizations of gdp's hardcoded `frontend/` and `requirements.txt`
paths, so Sysop owns their test coverage.

Also covers boundary cases that gdp's mock-only tests do not exercise:
malformed JSON output, very large output, subprocess timeout, and the
mode-filter routing contract (lint in codebase-review + security-audit;
pip-audit in security-audit only).
"""
import json
import os
import subprocess
from unittest.mock import patch

import pytest

import run_checks_impl
from run_checks_impl import (
    FrontendDirAmbiguous,
    _find_frontend_dir,
    _find_requirements_files,
    _run_eslint,
    _run_pip_audit,
)


# ── _find_frontend_dir ────────────────────────────────────────────────────


def test_find_frontend_dir_returns_none_when_no_eslint(tmp_path):
    assert _find_frontend_dir(str(tmp_path)) is None


def test_find_frontend_dir_returns_unique_match(tmp_path):
    eslint = tmp_path / "frontend" / "node_modules" / "eslint"
    eslint.mkdir(parents=True)
    result = _find_frontend_dir(str(tmp_path))
    assert result == str(tmp_path / "frontend")


def test_find_frontend_dir_raises_on_ambiguous_match(tmp_path):
    (tmp_path / "app-a" / "node_modules" / "eslint").mkdir(parents=True)
    (tmp_path / "app-b" / "node_modules" / "eslint").mkdir(parents=True)
    with pytest.raises(FrontendDirAmbiguous) as exc:
        _find_frontend_dir(str(tmp_path))
    assert "multiple" in str(exc.value)
    assert "app-a" in str(exc.value)
    assert "app-b" in str(exc.value)


def test_find_frontend_dir_skips_skip_dirs(tmp_path):
    # node_modules-nested eslint dirs inside .venv / .git / nested node_modules
    # should never match — they would be a false positive.
    (tmp_path / ".venv" / "lib" / "node_modules" / "eslint").mkdir(parents=True)
    (tmp_path / ".git" / "node_modules" / "eslint").mkdir(parents=True)
    assert _find_frontend_dir(str(tmp_path)) is None


def test_find_frontend_dir_handles_symlinks_without_recursion(tmp_path):
    real = tmp_path / "real"
    (real / "node_modules" / "eslint").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    # followlinks=False keeps the walk bounded; expect 1 match (the real dir),
    # not infinite recursion or a duplicate from the symlink.
    result = _find_frontend_dir(str(tmp_path))
    assert result == str(real)


# ── _find_requirements_files ──────────────────────────────────────────────


def test_find_requirements_files_returns_empty_when_none(tmp_path):
    assert _find_requirements_files(str(tmp_path)) == []


def test_find_requirements_files_returns_sorted_list(tmp_path):
    (tmp_path / "requirements.txt").write_text("flask\n")
    (tmp_path / "requirements-dev.txt").write_text("pytest\n")
    (tmp_path / "requirements-prod.txt").write_text("gunicorn\n")
    result = _find_requirements_files(str(tmp_path))
    assert result == [
        "requirements-dev.txt",
        "requirements-prod.txt",
        "requirements.txt",
    ]


def test_find_requirements_files_does_not_match_directory(tmp_path):
    (tmp_path / "requirements").mkdir()
    (tmp_path / "requirements" / "base.txt").write_text("flask\n")
    result = _find_requirements_files(str(tmp_path))
    assert result == []


def test_find_requirements_files_does_not_match_extension_suffix(tmp_path):
    (tmp_path / "requirements.txt.bak").write_text("flask\n")
    (tmp_path / "requirements.txt.orig").write_text("flask\n")
    result = _find_requirements_files(str(tmp_path))
    assert result == []


# ── invariant tests: malformed JSON ───────────────────────────────────────


def test_run_eslint_handles_non_json_output(tmp_path, capsys):
    eslint = tmp_path / "frontend" / "node_modules" / "eslint"
    eslint.mkdir(parents=True)
    config_next = (
        tmp_path / "frontend" / "node_modules" / "eslint-config-next" / "package.json"
    )
    config_next.parent.mkdir(parents=True)
    config_next.write_text("{}")

    with patch("run_checks_impl.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="<<not json>>", stderr=""
        )
        result = _run_eslint(str(tmp_path), {"lint-error"})
    assert result == []
    assert "non-JSON" in capsys.readouterr().err


def test_run_pip_audit_handles_non_json_output(tmp_path, capsys):
    with patch("run_checks_impl.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="<<not json>>", stderr=""
        )
        result = _run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert result == []
    assert "non-JSON" in capsys.readouterr().err


# ── invariant tests: pip-audit invocation + silent-abort guard (ISSUE-0046) ─


def test_run_pip_audit_skips_editable_and_drops_strict(tmp_path):
    """The invocation must use --skip-editable (an editable `pip install -e .`
    always leaves one unresolvable local package) and must NOT use --strict,
    which pip-audit treats as fatal on any skip → aborts before emitting JSON,
    silently reporting zero findings on every editable consumer (ISSUE-0046)."""
    with patch("run_checks_impl.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"dependencies": []}), stderr="",
        )
        _run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    cmd = run.call_args[0][0]
    assert "--skip-editable" in cmd, cmd
    assert "--strict" not in cmd, cmd


def test_run_pip_audit_warns_on_nonzero_exit_with_empty_stdout(tmp_path, capsys):
    """A failed run (non-zero exit, no JSON) must announce itself, not return an
    empty (== 'all clear') list — the silent-abort path ISSUE-0046 closed."""
    with patch("run_checks_impl.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=2, stdout="",
            stderr="usage: pip-audit ...\npip-audit: error: unrecognized arguments",
        )
        result = _run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    err = capsys.readouterr().err
    assert result == []
    assert "did NOT run" in err, err
    assert "unrecognized arguments" in err, err  # stderr tail surfaced


def test_run_pip_audit_silent_on_clean_empty_output(tmp_path, capsys):
    """Guard the guard: exit 0 with empty stdout must NOT emit the failure
    warning (only a non-zero exit signals an aborted run)."""
    with patch("run_checks_impl.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="",
        )
        result = _run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    err = capsys.readouterr().err
    assert result == []
    assert "did NOT run" not in err, err


def test_run_eslint_handles_truncated_json(tmp_path, capsys):
    """ESLint killed mid-write — output is valid prefix but invalid JSON."""
    eslint = tmp_path / "frontend" / "node_modules" / "eslint"
    eslint.mkdir(parents=True)
    config_next = (
        tmp_path / "frontend" / "node_modules" / "eslint-config-next" / "package.json"
    )
    config_next.parent.mkdir(parents=True)
    config_next.write_text("{}")

    with patch("run_checks_impl.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=-9,
            stdout='[{"filePath":"/foo.js","messages":[{"ruleId":"no-un',
            stderr="",
        )
        result = _run_eslint(str(tmp_path), {"lint-error"})
    assert result == []
    assert "non-JSON" in capsys.readouterr().err


# ── invariant tests: large output ─────────────────────────────────────────


def test_run_eslint_handles_large_output(tmp_path):
    """Large monorepo lint output (~1MB) must parse without OOM."""
    eslint = tmp_path / "frontend" / "node_modules" / "eslint"
    eslint.mkdir(parents=True)
    config_next = (
        tmp_path / "frontend" / "node_modules" / "eslint-config-next" / "package.json"
    )
    config_next.parent.mkdir(parents=True)
    config_next.write_text("{}")

    # 2000 files × 5 messages each = 10000 findings
    payload = [
        {
            "filePath": str(tmp_path / "frontend" / f"src/file_{i}.tsx"),
            "messages": [
                {"ruleId": "no-unused-vars", "severity": 2,
                 "line": j, "column": 1, "message": "unused var x"}
                for j in range(1, 6)
            ],
        }
        for i in range(2000)
    ]

    with patch("run_checks_impl.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps(payload), stderr=""
        )
        result = _run_eslint(str(tmp_path), {"lint-error"})
    assert len(result) == 10000
    assert all(r[0] == "lint-error" for r in result)


# ── invariant tests: timeout ──────────────────────────────────────────────


def test_run_eslint_honors_subprocess_timeout(tmp_path, capsys):
    eslint = tmp_path / "frontend" / "node_modules" / "eslint"
    eslint.mkdir(parents=True)
    config_next = (
        tmp_path / "frontend" / "node_modules" / "eslint-config-next" / "package.json"
    )
    config_next.parent.mkdir(parents=True)
    config_next.write_text("{}")

    with patch("run_checks_impl.subprocess.run") as run:
        run.side_effect = subprocess.TimeoutExpired(cmd=["eslint"], timeout=300)
        result = _run_eslint(str(tmp_path), {"lint-error"})
    assert result == []
    assert "timeout" in capsys.readouterr().err.lower()


def test_run_pip_audit_honors_subprocess_timeout(tmp_path, capsys):
    with patch("run_checks_impl.subprocess.run") as run:
        run.side_effect = subprocess.TimeoutExpired(cmd=["pip-audit"], timeout=300)
        result = _run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert result == []
    assert "timeout" in capsys.readouterr().err.lower()


def test_run_eslint_configures_a_subprocess_timeout(tmp_path):
    eslint = tmp_path / "frontend" / "node_modules" / "eslint"
    eslint.mkdir(parents=True)
    config_next = (
        tmp_path / "frontend" / "node_modules" / "eslint-config-next" / "package.json"
    )
    config_next.parent.mkdir(parents=True)
    config_next.write_text("{}")

    with patch("run_checks_impl.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr=""
        )
        _run_eslint(str(tmp_path), {"lint-error"})
    _, kwargs = run.call_args
    # The load-bearing invariant is that a timeout is configured at all (an
    # unbounded subprocess can hang); the exact value is not a contract.
    assert kwargs["timeout"] and kwargs["timeout"] > 0


def test_run_pip_audit_configures_a_subprocess_timeout(tmp_path):
    with patch("run_checks_impl.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"dependencies": []}), stderr="",
        )
        _run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    _, kwargs = run.call_args
    # Invariant: a timeout is configured at all, not its exact value.
    assert kwargs["timeout"] and kwargs["timeout"] > 0


# ── invariant tests: mode-filter routing ──────────────────────────────────


def test_run_eslint_skipped_when_check_id_not_in_included(tmp_path):
    """If lint-error is filtered out by mode, returns empty without shelling out."""
    eslint = tmp_path / "frontend" / "node_modules" / "eslint"
    eslint.mkdir(parents=True)
    config_next = (
        tmp_path / "frontend" / "node_modules" / "eslint-config-next" / "package.json"
    )
    config_next.parent.mkdir(parents=True)
    config_next.write_text("{}")

    with patch("run_checks_impl.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout=json.dumps([
                {"filePath": str(tmp_path / "frontend" / "x.js"),
                 "messages": [{"ruleId": "r", "severity": 2,
                               "line": 1, "column": 1, "message": "m"}]}
            ]),
            stderr="",
        )
        result = _run_eslint(str(tmp_path), {"some-other-id"})
    assert result == []


def test_run_pip_audit_skipped_when_check_id_not_in_included(tmp_path):
    with patch("run_checks_impl.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({
                "dependencies": [{"name": "x", "version": "1.0",
                                  "vulns": [{"id": "CVE-1"}]}]
            }),
            stderr="",
        )
        result = _run_pip_audit(str(tmp_path), {"some-other-id"})
    assert result == []


def test_run_eslint_returns_empty_when_included_ids_empty(tmp_path):
    """No subprocess shell-out when caller passes an empty set."""
    with patch("run_checks_impl.subprocess.run") as run:
        result = _run_eslint(str(tmp_path), set())
    assert result == []
    run.assert_not_called()


def test_run_pip_audit_returns_empty_when_included_ids_empty(tmp_path):
    with patch("run_checks_impl.subprocess.run") as run:
        result = _run_pip_audit(str(tmp_path), set())
    assert result == []
    run.assert_not_called()


# ── invariant tests: pip-audit anchor selection ───────────────────────────


def test_run_pip_audit_anchors_to_first_requirements_file(tmp_path):
    (tmp_path / "requirements-dev.txt").write_text("pytest\n")
    (tmp_path / "requirements.txt").write_text("flask\n")
    with patch("run_checks_impl.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({
                "dependencies": [{
                    "name": "flask", "version": "1.0",
                    "vulns": [{"id": "CVE-1", "description": "x"}],
                }],
            }),
            stderr="",
        )
        result = _run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    # sorted glob → "requirements-dev.txt" sorts before "requirements.txt"
    assert len(result) == 1
    assert result[0][1] == "requirements-dev.txt:1"


def test_run_pip_audit_falls_back_to_requirements_txt_when_none_found(tmp_path):
    with patch("run_checks_impl.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({
                "dependencies": [{
                    "name": "flask", "version": "1.0",
                    "vulns": [{"id": "CVE-1", "description": "x"}],
                }],
            }),
            stderr="",
        )
        result = _run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert len(result) == 1
    assert result[0][1] == "requirements.txt:1"
