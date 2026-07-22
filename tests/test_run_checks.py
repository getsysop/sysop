"""Unit tests for ``core/companion/scripts/run_checks_impl.py`` helpers.

Ported from gdp's ``tests/test_run_checks.py`` (post-``2fdca506`` state,
21 functions). Covers the ``position_check`` runner extension, the
ESLint + pip-audit ingest stages, and the mode-filter routing contract.

Generalization adjustments versus gdp:
- ``_make_eslint_frontend`` builds a tmp_path tree; the frontend dir is
  discovered via ``_find_frontend_dir`` rather than hardcoded.
- ``test_eslint_skips_when_node_modules_missing`` confirms a silent skip
  when the frontend dir is absent — Sysop's ``_find_frontend_dir``
  returns ``None`` rather than logging, since the absence of any
  ``node_modules/eslint`` is normal (not every project has a frontend).
- ``test_pip_audit_skips_when_binary_missing`` does not assert a pinned
  version in the warning text; Sysop does not own a CI workflow to
  pin to.
- ``test_pip_audit_parser_emits_finding_per_vuln`` does not pre-create
  ``requirements.txt`` — the parser falls back to ``requirements.txt:1``
  when no requirements file is found (covered separately in
  ``test_run_checks_generalizations.py``).
- Registry-contract tests read ``core/companion/checks.yml.fragment``
  instead of gdp's ``.claude/checks.yml`` (the fragment is the upstream
  source of truth before the installer concats it into a consumer's
  ``.claude/``).
"""

import json
import os
import subprocess
import sys
from unittest.mock import patch

import run_checks_impl as rci


_CHECKS_FRAGMENT = os.path.join(
    os.path.dirname(__file__),
    "..",
    "core",
    "companion",
    "checks.yml.fragment",
)


def _make_check(tmp_path, paths, includes=None):
    """Construct a check dict matching the production schema for position_check."""
    return {
        "id": "test-app-env-before-syspath",
        "paths": paths,
        "include": includes or ["*.py"],
        "position_check": {
            "earlier": r'os\.environ\.setdefault\("APP_ENV"',
            "later": r"sys\.path\.insert\(",
        },
        "severity": "medium",
        "description": "test description",
    }


def test_position_check_wrong_order_fires(tmp_path):
    """sys.path.insert before APP_ENV setdefault → finding."""
    target = tmp_path / "test_wrong.py"
    target.write_text(
        "import os\n"
        "import sys\n"
        "sys.path.insert(0, '.')\n"
        'os.environ.setdefault("APP_ENV", "test")\n'
    )
    check = _make_check(tmp_path, paths=["."])
    findings = rci.run_check(check, str(tmp_path))
    assert len(findings) == 1, findings
    check_id, file_line, _msg = findings[0]
    assert check_id == "test-app-env-before-syspath"
    assert file_line.endswith(":3"), file_line


def test_position_check_correct_order_silent(tmp_path):
    """APP_ENV setdefault before sys.path.insert → no finding."""
    target = tmp_path / "test_correct.py"
    target.write_text(
        "import os\n"
        "import sys\n"
        'os.environ.setdefault("APP_ENV", "test")\n'
        "sys.path.insert(0, '.')\n"
    )
    check = _make_check(tmp_path, paths=["."])
    findings = rci.run_check(check, str(tmp_path))
    assert findings == [], findings


def test_position_check_missing_earlier_silent(tmp_path):
    """Test file lacks APP_ENV setdefault entirely → no finding (out of scope)."""
    target = tmp_path / "test_missing.py"
    target.write_text(
        "import sys\n"
        "sys.path.insert(0, '.')\n"
    )
    check = _make_check(tmp_path, paths=["."])
    findings = rci.run_check(check, str(tmp_path))
    assert findings == [], findings


def test_position_check_missing_later_silent(tmp_path):
    """File has APP_ENV setdefault but no sys.path.insert → no finding."""
    target = tmp_path / "test_no_syspath.py"
    target.write_text(
        "import os\n"
        'os.environ.setdefault("APP_ENV", "test")\n'
    )
    check = _make_check(tmp_path, paths=["."])
    findings = rci.run_check(check, str(tmp_path))
    assert findings == [], findings


def test_position_check_skips_comment_lines(tmp_path):
    """A commented-out sys.path.insert at the top must not spoof the order check."""
    target = tmp_path / "test_comment.py"
    target.write_text(
        "# sys.path.insert(0, '.')  # historical note\n"
        "import os\n"
        "import sys\n"
        'os.environ.setdefault("APP_ENV", "test")\n'
        "sys.path.insert(0, '.')\n"
    )
    check = _make_check(tmp_path, paths=["."])
    findings = rci.run_check(check, str(tmp_path))
    assert findings == [], findings


# ── ESLint stage tests ────────────────────────────────────────────────────


def _make_eslint_frontend(tmp_path, name="frontend"):
    """Create a tmp_path/frontend tree with the guard files _run_eslint expects."""
    frontend = tmp_path / name
    (frontend / "node_modules" / "eslint").mkdir(parents=True)
    (frontend / "node_modules" / "eslint" / "package.json").write_text("{}")
    (frontend / "node_modules" / "eslint-config-next").mkdir(parents=True)
    (frontend / "node_modules" / "eslint-config-next" / "package.json").write_text("{}")
    return frontend


def test_eslint_parser_emits_finding_per_message(tmp_path):
    """Canned ESLint JSON → one tuple per message, check_id=lint-error, rule_id in msg."""
    frontend = _make_eslint_frontend(tmp_path)
    file_path = str(frontend / "app" / "components" / "Foo.tsx")
    canned = [
        {
            "filePath": file_path,
            "messages": [
                {
                    "ruleId": "react-hooks/exhaustive-deps",
                    "severity": 2,
                    "line": 42,
                    "column": 8,
                    "message": "React Hook useEffect has a missing dependency.",
                }
            ],
            "errorCount": 1,
            "warningCount": 0,
        }
    ]
    with patch("run_checks_impl.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps(canned), stderr=""
        )
        findings = rci._run_eslint(str(tmp_path), {"lint-error"})
    assert len(findings) == 1, findings
    check_id, file_line, msg = findings[0]
    assert check_id == "lint-error"
    assert file_line == "frontend/app/components/Foo.tsx:42"
    assert "react-hooks/exhaustive-deps" in msg
    assert "missing dependency" in msg


def test_eslint_invocation_never_uses_exit_on_fatal_error(tmp_path):
    """Drift guard (Phase 135 follow-up, deliverable 04): the rc≠0 + empty-stdout
    crash discriminator in lint.py is only sound because the invocation omits
    `--exit-on-fatal-error`. That flag makes a formatted fatal parse result exit
    2 while KEEPING valid JSON, so exit 2 would no longer imply a crash and real
    findings would be misread as a failed run. Forbid the flag in the argv."""
    _make_eslint_frontend(tmp_path)
    with patch("run_checks_impl.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr=""
        )
        rci._run_eslint(str(tmp_path), {"lint-error"})
    argv = mock_run.call_args.args[0]
    assert "--exit-on-fatal-error" not in argv, argv


def test_eslint_skips_when_binary_missing(tmp_path, capsys):
    """FileNotFoundError from subprocess.run → empty list + stderr warning."""
    _make_eslint_frontend(tmp_path)
    with patch("run_checks_impl.subprocess.run", side_effect=FileNotFoundError):
        findings = rci._run_eslint(str(tmp_path), {"lint-error"})
    assert findings == []
    captured = capsys.readouterr()
    assert "eslint not on PATH" in captured.err


def test_eslint_skips_silently_when_no_frontend_dir(tmp_path, capsys):
    """No node_modules/eslint anywhere → silent skip (returns None from finder).

    Sysop diverges from gdp here: gdp expected a stderr warning when
    `frontend/` lacks `node_modules/`, but in Sysop the absence of any
    `node_modules/eslint` candidate is normal (not every project has a
    frontend), so `_find_frontend_dir` returns None and `_run_eslint`
    returns silently. The subprocess must not be invoked.
    """
    with patch("run_checks_impl.subprocess.run") as mock_run:
        findings = rci._run_eslint(str(tmp_path), {"lint-error"})
        assert mock_run.call_count == 0
    assert findings == []
    assert capsys.readouterr().err == ""


def test_eslint_skips_when_eslint_config_next_missing(tmp_path, capsys):
    """Missing eslint-config-next next to a real eslint install → warn + skip."""
    frontend = tmp_path / "frontend"
    (frontend / "node_modules" / "eslint").mkdir(parents=True)
    (frontend / "node_modules" / "eslint" / "package.json").write_text("{}")
    with patch("run_checks_impl.subprocess.run") as mock_run:
        findings = rci._run_eslint(str(tmp_path), {"lint-error"})
        assert mock_run.call_count == 0
    assert findings == []
    captured = capsys.readouterr()
    assert "eslint-config-next missing" in captured.err


def test_eslint_severity_warning_mapped_to_medium(tmp_path):
    """ESLint severity=1 (warning) → MEDIUM in finding text."""
    frontend = _make_eslint_frontend(tmp_path)
    canned = [
        {
            "filePath": str(frontend / "Foo.tsx"),
            "messages": [
                {
                    "ruleId": "no-unused-vars",
                    "severity": 1,
                    "line": 5,
                    "message": "Variable 'x' is unused.",
                }
            ],
        }
    ]
    with patch("run_checks_impl.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(canned), stderr=""
        )
        findings = rci._run_eslint(str(tmp_path), {"lint-error"})
    assert len(findings) == 1
    _, _, msg = findings[0]
    assert "MEDIUM" in msg


def test_eslint_null_rule_id_uses_syntax_error(tmp_path):
    """ESLint message with null ruleId (e.g., parser error) → 'syntax-error' tag."""
    frontend = _make_eslint_frontend(tmp_path)
    canned = [
        {
            "filePath": str(frontend / "Foo.tsx"),
            "messages": [
                {
                    "ruleId": None,
                    "severity": 2,
                    "line": 1,
                    "message": "Parse error.",
                }
            ],
        }
    ]
    with patch("run_checks_impl.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps(canned), stderr=""
        )
        findings = rci._run_eslint(str(tmp_path), {"lint-error"})
    assert len(findings) == 1
    _, _, msg = findings[0]
    assert "syntax-error" in msg


# ── pip-audit stage tests ─────────────────────────────────────────────────


def test_pip_audit_parser_emits_finding_per_vuln(tmp_path):
    """Canned pip-audit JSON → one tuple per vulnerability, check_id=pip-audit-vuln."""
    canned = {
        "dependencies": [
            {
                "name": "idna",
                "version": "3.11",
                "vulns": [
                    {
                        "id": "CVE-2026-45409",
                        "aliases": ["GHSA-65pc-fj4g-8rjx"],
                        "fix_versions": ["3.15"],
                        "description": "DoS via crafted IDN input.",
                    }
                ],
            },
            {"name": "clean-package", "version": "1.0", "vulns": []},
        ]
    }
    with patch("run_checks_impl.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(canned), stderr=""
        )
        findings = rci._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert len(findings) == 1, findings
    check_id, file_line, msg = findings[0]
    assert check_id == "pip-audit-vuln"
    # No requirements file in tmp_path → falls back to default anchor
    assert file_line == "requirements.txt:1"
    assert "idna==3.11" in msg
    assert "CVE-2026-45409" in msg
    assert "GHSA-65pc-fj4g-8rjx" in msg
    assert "3.15" in msg


def test_pip_audit_skips_when_binary_missing(tmp_path, capsys):
    """FileNotFoundError → empty list + stderr install hint."""
    with patch("run_checks_impl.subprocess.run", side_effect=FileNotFoundError):
        findings = rci._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert findings == []
    captured = capsys.readouterr()
    assert "pip-audit not on PATH" in captured.err
    assert "pip install pip-audit" in captured.err


def test_pip_audit_clean_audit_returns_empty(tmp_path):
    """All deps clean (no vulns) → empty list."""
    canned = {
        "dependencies": [
            {"name": "a", "version": "1.0", "vulns": []},
            {"name": "b", "version": "2.0", "vulns": []},
        ]
    }
    with patch("run_checks_impl.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(canned), stderr=""
        )
        findings = rci._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert findings == []


def test_pip_audit_invalid_json_skips(tmp_path, capsys):
    """Non-JSON output → empty list + stderr warning."""
    with patch("run_checks_impl.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="not json", stderr=""
        )
        findings = rci._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert findings == []
    captured = capsys.readouterr()
    assert "non-JSON" in captured.err


# ── Mode filter / dispatcher tests ────────────────────────────────────────
# These verify that the `lint-*` and `pip-audit-*` dispatcher branches in
# main() route findings to the correct --mode via the registry's used_by
# contract. Sysop reads the upstream fragment (the consumer-side
# .claude/checks.yml is generated by the installer from this fragment +
# any installed pack fragments).


def test_eslint_check_is_used_by_both_modes():
    """The lint-error registry entry must appear in both quality and security modes.

    Frontend ESLint findings include accessibility rules (jsx-a11y/*) which
    map to OWASP A07/A05 — restricting the lint stage to codebase-review
    only would lose those from /security-audit.
    """
    parsed = rci.parse_checks_yml(_CHECKS_FRAGMENT)
    lint_entries = [c for c in parsed if c.get("id", "").startswith("lint-")]
    assert lint_entries, "Expected at least one lint-* check in checks fragment"
    for entry in lint_entries:
        used_by = entry.get("used_by", [])
        assert "codebase-review" in used_by, entry
        assert "security-audit" in used_by, entry


def test_pip_audit_check_is_security_audit_only():
    """The pip-audit-* registry entry must NOT fire under --mode quality.

    Dependency advisories are an OWASP A06 concern — the codebase-review
    skill does not own them, so quality-mode runs should skip pip-audit
    entirely.
    """
    parsed = rci.parse_checks_yml(_CHECKS_FRAGMENT)
    pip_audit_entries = [
        c for c in parsed if c.get("id", "").startswith("pip-audit-")
    ]
    assert pip_audit_entries, "Expected at least one pip-audit-* check"
    for entry in pip_audit_entries:
        used_by = entry.get("used_by", [])
        assert "security-audit" in used_by, entry
        assert "codebase-review" not in used_by, entry


def test_eslint_mode_filter_via_filter_checks():
    """filter_checks('security') and filter_checks('quality') route lint-* correctly."""
    parsed = rci.parse_checks_yml(_CHECKS_FRAGMENT)
    quality_filtered = rci.filter_checks(parsed, "quality")
    security_filtered = rci.filter_checks(parsed, "security")
    quality_ids = {c["id"] for c in quality_filtered}
    security_ids = {c["id"] for c in security_filtered}
    assert "lint-error" in quality_ids
    assert "lint-error" in security_ids


def test_pip_audit_mode_filter_via_filter_checks():
    """filter_checks('quality') drops pip-audit-*; filter_checks('security') keeps it."""
    parsed = rci.parse_checks_yml(_CHECKS_FRAGMENT)
    quality_filtered = rci.filter_checks(parsed, "quality")
    security_filtered = rci.filter_checks(parsed, "security")
    quality_ids = {c["id"] for c in quality_filtered}
    security_ids = {c["id"] for c in security_filtered}
    assert "pip-audit-vuln" not in quality_ids
    assert "pip-audit-vuln" in security_ids


# ── Phase 133: pip-audit module fallback + manifest anchor ──────────────────


def test_pip_audit_falls_back_to_module_invocation(tmp_path):
    """The console script isn't on PATH (venv at a non-.venv home) but the
    running python has pip_audit installed — the stage must fall back to
    `sys.executable -m pip_audit` instead of warning 'not on PATH' (the leg-5
    dogfood sibling finding)."""
    canned = {"dependencies": [{"name": "idna", "version": "3.11", "vulns": [
        {"id": "CVE-X", "aliases": [], "fix_versions": [], "description": "d"}]}]}
    ok = subprocess.CompletedProcess(args=[], returncode=0,
                                     stdout=json.dumps(canned), stderr="")
    with patch("run_checks_impl.subprocess.run",
               side_effect=[FileNotFoundError(), ok]) as mock_run:
        findings = rci._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert len(findings) == 1
    assert mock_run.call_count == 2
    second_argv = mock_run.call_args_list[1][0][0]
    assert second_argv[0] == sys.executable
    assert second_argv[1:3] == ["-m", "pip_audit"]


def test_pip_audit_warns_when_missing_both_ways(tmp_path, capsys):
    """Binary absent AND the module fallback's python lacks pip_audit → the
    friendly install-hint warn, not a cryptic module traceback."""
    module_missing = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="",
        stderr="/usr/bin/python3: No module named pip_audit")
    with patch("run_checks_impl.subprocess.run",
               side_effect=[FileNotFoundError(), module_missing]):
        findings = rci._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert findings == []
    captured = capsys.readouterr()
    assert "pip-audit not on PATH" in captured.err
    assert "pip install pip-audit" in captured.err


def test_pip_audit_anchors_at_pyproject_for_manifest_only_consumers(tmp_path):
    """pyproject/uv consumers (no requirements*.txt) anchor findings at
    pyproject.toml:1 — the manifest that owns the dependency set (leg-5
    dogfood finding 8)."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    canned = {"dependencies": [{"name": "idna", "version": "3.11", "vulns": [
        {"id": "CVE-X", "aliases": [], "fix_versions": [], "description": "d"}]}]}
    with patch("run_checks_impl.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(canned), stderr="")
        findings = rci._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert len(findings) == 1
    assert findings[0][1] == "pyproject.toml:1"


def test_pip_audit_console_crash_surfaces_real_error_not_path_warn(tmp_path, capsys):
    """Adversarial-review fix (2026-07-19): a console-script pip-audit that
    crashes internally (ModuleNotFoundError in its OWN dep tree) must surface
    via the exited-N warn with its real stderr — not be misread as
    not-installed (which would also waste a second full attempt)."""
    crash = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="",
        stderr="ModuleNotFoundError: No module named 'pip_audit._vendor.x'")
    with patch("run_checks_impl.subprocess.run",
               return_value=crash) as mock_run:
        findings = rci._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert findings == []
    assert mock_run.call_count == 1, "crash must not trigger the module fallback"
    captured = capsys.readouterr()
    assert "dependency audit did NOT run" in captured.err
    assert "pip_audit._vendor.x" in captured.err
    assert "not on PATH" not in captured.err
