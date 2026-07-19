"""Unit tests for the LSP / typechecker ingest stage (run_checks/lsp.py), Phase 105.

This whole stage had zero coverage while its sibling ingest stages (grep,
coverage, eslint, pip-audit) are exhaustive — and it feeds `--fail-on-blocking`,
so a parser regression here would silently change what blocks a merge. These
cover the pyright + tsc JSON/text parsers (the 0-indexed→1-indexed line
conversion, the rule→check_id mapping, severity mapping, continuation-line
collapse), the `included_ids` filter, every graceful-skip path (binary missing /
timeout / non-JSON / empty / guard-file absent), and the dispatcher routing.

The subprocess boundary is mocked exactly as the coverage stage tests do
(`patch("run_checks.lsp.subprocess.run")`) — no real pyright/tsc binary needed.
Tool-absent is detected via `FileNotFoundError`, not a return code.
"""
import json
import subprocess
from unittest.mock import patch

import run_checks.lsp as lsp


def _completed(stdout="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr="")


def _pyright_json(tmp_path, *, rule="reportMissingImports", severity="error",
                  line=41, message="Import could not be resolved"):
    return json.dumps({
        "generalDiagnostics": [{
            "file": str(tmp_path / "app" / "x.py"),
            "severity": severity,
            "rule": rule,
            "range": {"start": {"line": line}},
            "message": message,
        }]
    })


# ── pyright parser ──────────────────────────────────────────────────────────

class TestPyrightParser:
    def test_emits_finding_per_diagnostic(self, tmp_path):
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed(_pyright_json(tmp_path))):
            out = lsp._run_pyright(str(tmp_path), {"pyright-missing-imports"})
        assert len(out) == 1
        check_id, file_line, msg = out[0]
        assert check_id == "pyright-missing-imports"
        # pyright's range.start.line is 0-indexed; the +1 makes it 1-indexed.
        assert file_line == "app/x.py:42"
        assert "HIGH" in msg
        assert "Import could not be resolved" in msg

    def test_rule_not_in_included_ids_is_dropped(self, tmp_path):
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed(_pyright_json(tmp_path))):
            out = lsp._run_pyright(str(tmp_path), {"pyright-unused-import"})
        assert out == []

    def test_unmapped_warning_becomes_general_warning(self, tmp_path):
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed(
                       _pyright_json(tmp_path, rule="reportSomethingNew",
                                     severity="warning"))):
            out = lsp._run_pyright(str(tmp_path), {"pyright-general-warning"})
        assert len(out) == 1
        assert out[0][0] == "pyright-general-warning"
        assert "MEDIUM" in out[0][2]

    def test_unmapped_info_severity_is_dropped(self, tmp_path):
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed(
                       _pyright_json(tmp_path, rule="", severity="information"))):
            out = lsp._run_pyright(str(tmp_path), {"pyright-general-warning"})
        assert out == []

    def test_binary_missing_skips_with_warning(self, tmp_path, capsys):
        with patch("run_checks.lsp.subprocess.run", side_effect=FileNotFoundError):
            out = lsp._run_pyright(str(tmp_path), {"pyright-missing-imports"})
        assert out == []
        assert "pyright not on PATH" in capsys.readouterr().err

    def test_timeout_skips_with_warning(self, tmp_path, capsys):
        with patch("run_checks.lsp.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("pyright", 300)):
            out = lsp._run_pyright(str(tmp_path), {"pyright-missing-imports"})
        assert out == []
        assert "timeout" in capsys.readouterr().err

    def test_non_json_output_skips_with_warning(self, tmp_path, capsys):
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed("not json at all")):
            out = lsp._run_pyright(str(tmp_path), {"pyright-missing-imports"})
        assert out == []
        assert "non-JSON" in capsys.readouterr().err

    def test_empty_stdout_returns_empty(self, tmp_path):
        with patch("run_checks.lsp.subprocess.run", return_value=_completed("")):
            out = lsp._run_pyright(str(tmp_path), {"pyright-missing-imports"})
        assert out == []


# ── tsc parser ──────────────────────────────────────────────────────────────

def _make_tsc_frontend(tmp_path):
    """Build the two filesystem guards tsc requires before it shells out."""
    fe = tmp_path / "frontend"
    (fe).mkdir()
    (fe / "tsconfig.json").write_text("{}\n")
    (fe / "node_modules" / "typescript").mkdir(parents=True)
    return tmp_path


class TestTscParser:
    def test_emits_finding(self, tmp_path):
        _make_tsc_frontend(tmp_path)
        out_line = ("src/App.tsx(12,5): error TS2322: "
                    "Type 'string' is not assignable to 'number'.\n")
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed(out_line)):
            out = lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert len(out) == 1
        check_id, file_line, msg = out[0]
        assert check_id == "tsc-type-error"
        # line is group(2)=12, NOT the column group(3)=5.
        assert file_line == "frontend/src/App.tsx:12"
        assert "HIGH" in msg

    def test_collapses_continuation_lines(self, tmp_path):
        _make_tsc_frontend(tmp_path)
        stdout = (
            "src/App.tsx(12,5): error TS2322: Type 'A' is not assignable to 'B'.\n"
            "  Types of property 'x' are incompatible.\n"
        )
        with patch("run_checks.lsp.subprocess.run", return_value=_completed(stdout)):
            out = lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert len(out) == 1
        msg = out[0][2]
        assert "Type 'A' is not assignable to 'B'." in msg
        # The continuation line survives via the " — " join.
        assert "Types of property 'x' are incompatible." in msg

    def test_skips_when_tsconfig_absent(self, tmp_path):
        with patch("run_checks.lsp.subprocess.run") as mock_run:
            out = lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert out == []
        assert mock_run.call_count == 0

    def test_warns_when_typescript_module_missing(self, tmp_path, capsys):
        fe = tmp_path / "frontend"
        fe.mkdir()
        (fe / "tsconfig.json").write_text("{}\n")  # tsconfig present, no node_modules
        with patch("run_checks.lsp.subprocess.run") as mock_run:
            out = lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert out == []
        assert mock_run.call_count == 0
        assert "frontend/node_modules/typescript missing" in capsys.readouterr().err

    def test_binary_missing_skips_with_warning(self, tmp_path, capsys):
        _make_tsc_frontend(tmp_path)
        with patch("run_checks.lsp.subprocess.run", side_effect=FileNotFoundError):
            out = lsp._run_tsc(str(tmp_path), {"tsc-type-error"})
        assert out == []
        assert "tsc not available" in capsys.readouterr().err


# ── dispatcher ──────────────────────────────────────────────────────────────

class TestDispatch:
    def test_pyright_only_set_does_not_invoke_tsc(self, tmp_path):
        # A pyright-only included set → tsc is never dispatched (guarded on
        # "tsc-type-error" membership). Only pyright shells out.
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed('{"generalDiagnostics": []}')) as mock_run:
            lsp.run_lsp_diagnostics(str(tmp_path), {"pyright-missing-imports"})
        assert mock_run.call_count == 1
        assert "pyright" in mock_run.call_args_list[0].args[0]

    def test_empty_included_set_shells_out_to_nothing(self, tmp_path):
        with patch("run_checks.lsp.subprocess.run") as mock_run:
            out = lsp.run_lsp_diagnostics(str(tmp_path), set())
        assert out == []
        assert mock_run.call_count == 0


# ── Phase 133: per-check paths: scoping (post-filter) ───────────────────────

class TestPathsScoping:
    """When a pyright-*/tsc-* registry entry declares real `paths:`, findings
    outside them are dropped; unlocalized `<placeholder>` entries contribute
    no scoping and the `__disabled_no_op__` sentinel disables the check."""

    def _run_pyright(self, tmp_path, included):
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed(_pyright_json(tmp_path))):
            return lsp._run_pyright(str(tmp_path), included)

    def test_pyright_in_scope_kept(self, tmp_path):
        out = self._run_pyright(tmp_path, {
            "pyright-missing-imports": {"id": "pyright-missing-imports",
                                        "paths": ["app/"]}})
        assert len(out) == 1

    def test_pyright_out_of_scope_dropped(self, tmp_path):
        out = self._run_pyright(tmp_path, {
            "pyright-missing-imports": {"id": "pyright-missing-imports",
                                        "paths": ["other/"]}})
        assert out == []

    def test_pyright_placeholder_paths_do_not_scope(self, tmp_path):
        out = self._run_pyright(tmp_path, {
            "pyright-missing-imports": {"id": "pyright-missing-imports",
                                        "paths": ["<api module>/"]}})
        assert len(out) == 1, "unlocalized placeholder must not disable the check"

    def test_pyright_sentinel_disables_check(self, tmp_path):
        out = self._run_pyright(tmp_path, {
            "pyright-missing-imports": {"id": "pyright-missing-imports",
                                        "paths": ["__disabled_no_op__"]}})
        assert out == []

    def test_tsc_paths_scope_findings(self, tmp_path):
        m = lsp._TSC_HEADER_RE.match(
            "components/App.tsx(5,3): error TS2322: Bad type")
        assert m
        out_in, out_out = [], []
        lsp._emit_tsc_finding(
            (m, []), str(tmp_path / "frontend"), str(tmp_path),
            {"tsc-type-error": {"id": "tsc-type-error", "paths": ["frontend/"]}},
            out_in)
        lsp._emit_tsc_finding(
            (m, []), str(tmp_path / "frontend"), str(tmp_path),
            {"tsc-type-error": {"id": "tsc-type-error", "paths": ["backend/"]}},
            out_out)
        assert len(out_in) == 1
        assert out_out == []
