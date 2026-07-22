"""Tests for the pre-scan execution-accounting layer (run_checks/accounting.py).

Executes the ESCALATED/DEFINITIVE checklist defect "run_checks/semgrep.py
swallows every semgrep failure except two" — the cross-harness run where
`--mode quality` reported `890 findings from 25 checks` while 5 of 25 checks
executed, and `--mode security` reported `0 findings from 13 checks` with every
stage dead (indistinguishable from a clean scan). Design: tools/PRESCAN_ACCOUNTING_SPEC.md.

Three layers are covered:
  1. `RunReport` unit behavior — record-once semantics, counts, blocking_failures,
     the render contract (header, ⚠ localized-vs-placeholder, executed-zero line).
  2. Per-stage recording — every silent-skip path now records a terminal state;
     each is mutation-tested (removing the branch fails the assertion).
  3. cli.main end-to-end — the motivating scenario, the `failed`-blocking gate,
     and the single-pass `--update-baseline` refusal.

House norm (Phases 104/105): each new branch has a test that fails when the
branch is removed.
"""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import run_checks.accounting as acc
import run_checks.coverage as coverage_mod
import run_checks.grep as grep_mod
import run_checks.lint as lint_mod
import run_checks.lsp as lsp_mod
import run_checks.pip_audit as pip_audit_mod
import run_checks.semgrep as semgrep_mod
import run_checks_impl as rci
from run_checks.accounting import EXECUTED, FAILED, SKIPPED, RunReport


def _completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


# ── RunReport unit behavior ─────────────────────────────────────────────────


class TestRunReportRecording:
    def test_first_state_wins(self):
        r = RunReport([{"id": "c1"}])
        r.record(["c1"], EXECUTED, "grep")
        r.record(["c1"], SKIPPED, "grep", "paths-unresolved")
        assert r.status_of("c1") == EXECUTED

    def test_failed_overrides_earlier_executed(self):
        """A stage that scanned then crashed in post-processing is failed, not clean."""
        r = RunReport([{"id": "c1"}])
        r.record(["c1"], EXECUTED, "grep")
        r.record(["c1"], FAILED, "grep", "exception", "boom")
        assert r.status_of("c1") == FAILED

    def test_executed_does_not_override_failed(self):
        r = RunReport([{"id": "c1"}])
        r.record(["c1"], FAILED, "grep", "timeout")
        r.record(["c1"], EXECUTED, "grep")
        assert r.status_of("c1") == FAILED

    def test_skipped_is_not_overridden_by_failed(self):
        """The override rule is failed-over-executed ONLY — a precondition-absent
        skip is not retroactively a crash."""
        r = RunReport([{"id": "c1"}])
        r.record(["c1"], SKIPPED, "grep", "paths-unresolved")
        r.record(["c1"], FAILED, "grep", "timeout")
        assert r.status_of("c1") == SKIPPED

    def test_counts_tallies_each_state_and_unaccounted(self):
        r = RunReport([{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}])
        r.record(["a"], EXECUTED, "grep")
        r.record(["b"], SKIPPED, "grep", "not-configured")
        r.record(["c"], FAILED, "semgrep", "timeout")
        # d never recorded → unaccounted
        assert r.counts() == (1, 1, 1, 1, 4)

    def test_blocking_failures_only_lists_failed_blocking(self):
        r = RunReport([
            {"id": "b-fail", "blocking": True},
            {"id": "b-skip", "blocking": True},
            {"id": "nb-fail"},  # failed but not blocking
        ])
        r.record(["b-fail"], FAILED, "coverage", "non-json", "bad json")
        r.record(["b-skip"], SKIPPED, "coverage", "input-missing")
        r.record(["nb-fail"], FAILED, "semgrep", "timeout")
        failed = r.blocking_failures()
        assert [f[0] for f in failed] == ["b-fail"]
        assert failed[0][1] == "coverage" and failed[0][2] == "non-json"


class TestLocalizedDetection:
    def test_placeholder_scope_is_not_localized(self):
        assert acc.check_is_localized({"paths": ["<api module>/"]}) is False

    def test_concrete_scope_is_localized(self):
        assert acc.check_is_localized({"paths": ["src/app/"]}) is True

    def test_mixed_scope_is_localized(self):
        assert acc.check_is_localized(
            {"paths": ["<api module>/", "src/real/"]}
        ) is True

    def test_no_scope_is_not_localized(self):
        assert acc.check_is_localized({"id": "x"}) is False

    def test_critical_path_participates(self):
        assert acc.check_is_localized({"critical_path": ["billing/"]}) is True

    def test_scalar_scope_field_does_not_crash_or_char_split(self):
        """Defensive: a stray scalar (validation normally rejects it, but a
        RunReport built directly must not crash or read 'billing/' as the
        localized globs ['b','i','l','l',...])."""
        assert acc.check_is_localized({"critical_path": "billing/"}) is False
        assert acc.check_is_localized({"paths": 5}) is False
        # RunReport construction over a malformed check must not raise.
        RunReport([{"id": "x", "critical_path": "billing/", "blocking": True}])


class TestRender:
    def _report(self):
        return RunReport([
            {"id": "grep-a", "paths": ["<x>/"]},
            {"id": "grep-b", "paths": ["real/"], "blocking": True},   # localized blocking
            {"id": "pyr-1"}, {"id": "pyr-2"},
            {"id": "semgrep-x"},
            {"id": "cov-ph", "critical_path": ["<c>/"], "blocking": True},  # placeholder blocking
        ])

    def test_header_reports_executed_skipped_failed_selected(self):
        r = self._report()
        r.record(["grep-a"], SKIPPED, "grep", "paths-unresolved", "ph")
        r.record(["grep-b"], SKIPPED, "grep", "paths-unresolved", "gone")
        r.record(["pyr-1", "pyr-2"], EXECUTED, "pyright")
        r.record(["semgrep-x"], FAILED, "semgrep", "nonzero-no-output", "exit 2")
        r.record(["cov-ph"], SKIPPED, "coverage", "not-configured", "unarmed")
        out = r.render([("pyr-1", "a.py:1", "m")], mode="quality",
                       baseline_matched=3, new_blocking=4)
        head = out.splitlines()[0]
        assert "2 executed" in head and "3 skipped" in head and "1 failed" in head
        assert "of 6 selected" in head
        assert "mode: quality" in head
        assert "baseline-matched: 3" in head and "new blocking: 4" in head

    def test_localized_blocking_skip_gets_warning(self):
        r = self._report()
        r.record(["grep-b"], SKIPPED, "grep", "paths-unresolved", "gone")
        out = r.render([], mode="quality")
        line = [l for l in out.splitlines() if "grep-b" not in l and "grep" in l][0]
        assert "⚠ BLOCKING CHECK DID NOT RUN" in line

    def test_placeholder_blocking_skip_stays_calm(self):
        r = self._report()
        r.record(["cov-ph"], SKIPPED, "coverage", "not-configured",
                 "critical_path not yet configured (placeholder globs); gate unarmed")
        out = r.render([], mode="quality")
        cov_line = [l for l in out.splitlines() if "coverage" in l][0]
        assert "⚠" not in cov_line
        assert "gate unarmed" in cov_line

    def test_executed_zero_grep_is_a_count_not_enumerated(self):
        r = RunReport([{"id": "g1"}, {"id": "g2"}])
        r.record(["g1", "g2"], EXECUTED, "grep")
        out = r.render([], mode="quality")
        line = [l for l in out.splitlines() if "executed with 0 findings" in l][0]
        assert "2 grep checks" in line
        assert "g1" not in line and "g2" not in line

    def test_executed_zero_tool_stage_is_enumerated(self):
        r = RunReport([{"id": "pyright-a"}, {"id": "pyright-b"}])
        r.record(["pyright-a", "pyright-b"], EXECUTED, "pyright")
        out = r.render([], mode="quality")
        line = [l for l in out.splitlines() if "executed with 0 findings" in l][0]
        assert "pyright-a" in line and "pyright-b" in line

    def test_executed_with_findings_not_listed_as_zero(self):
        r = RunReport([{"id": "pyright-a"}, {"id": "pyright-b"}])
        r.record(["pyright-a", "pyright-b"], EXECUTED, "pyright")
        out = r.render([("pyright-a", "x.py:1", "m")], mode="quality")
        zero_lines = [l for l in out.splitlines() if "executed with 0 findings" in l]
        assert len(zero_lines) == 1
        assert "pyright-b" in zero_lines[0] and "pyright-a" not in zero_lines[0]

    def test_unaccounted_renders_in_header_and_own_line(self):
        r = RunReport([{"id": "recorded"}, {"id": "forgotten"}])
        r.record(["recorded"], EXECUTED, "grep")
        out = r.render([], mode="quality")
        assert "1 unaccounted" in out.splitlines()[0]
        assert "accounting bug" in out
        assert "forgotten" in out

    def test_no_unaccounted_line_when_all_accounted(self):
        r = RunReport([{"id": "a"}])
        r.record(["a"], EXECUTED, "grep")
        out = r.render([], mode="quality")
        assert "unaccounted" not in out


# ── semgrep stage recording (the headline defect) ───────────────────────────


class TestSemgrepRecording:
    def _dir(self, tmp_path):
        (tmp_path / ".claude" / "semgrep").mkdir(parents=True)
        return tmp_path

    def _report(self):
        return RunReport([{"id": "semgrep-x"}, {"id": "semgrep-y"}])

    def test_x509_crash_records_failed_with_stderr(self, tmp_path, capsys):
        """The motivating case: rc=2, empty stdout, X.509 trust-store crash on
        stderr — used to `return out` silently."""
        self._dir(tmp_path)
        r = self._report()
        crash = ("Fatal error: exception Failure(\"Failed to create system "
                 "store X509 authenticator: ca-certs: empty trust anchors\")")
        with patch("run_checks.semgrep.subprocess.run",
                   return_value=_completed("", returncode=2, stderr=crash)):
            out = semgrep_mod._run_semgrep(str(tmp_path),
                                           {"semgrep-x": {"id": "semgrep-x"},
                                            "semgrep-y": {"id": "semgrep-y"}}, r)
        assert out == []
        assert r.status_of("semgrep-x") == FAILED
        assert r.status_of("semgrep-y") == FAILED
        rec = r._records["semgrep-x"]
        assert rec.reason == "nonzero-no-output"
        assert "X509" in rec.detail
        assert "did NOT run" in capsys.readouterr().err

    def test_empty_stdout_rc0_records_executed(self, tmp_path):
        self._dir(tmp_path)
        r = self._report()
        with patch("run_checks.semgrep.subprocess.run",
                   return_value=_completed("", returncode=0)):
            semgrep_mod._run_semgrep(str(tmp_path), {"semgrep-x": {"id": "semgrep-x"}}, r)
        assert r.status_of("semgrep-x") == EXECUTED

    def test_json_errors_no_results_records_failed(self, tmp_path, capsys):
        """A scan that printed JSON but hit internal errors and produced nothing
        (invalid overlay rule) — the `errors` array is now read (spec §1)."""
        self._dir(tmp_path)
        r = self._report()
        payload = json.dumps({"results": [],
                              "errors": [{"message": "invalid rule file"}]})
        with patch("run_checks.semgrep.subprocess.run",
                   return_value=_completed(payload, returncode=1)):
            semgrep_mod._run_semgrep(str(tmp_path), {"semgrep-x": {"id": "semgrep-x"}}, r)
        assert r.status_of("semgrep-x") == FAILED
        assert r._records["semgrep-x"].reason == "scan-errors"
        assert "did NOT run" in capsys.readouterr().err

    def test_json_errors_with_results_records_executed_and_warns(self, tmp_path, capsys):
        self._dir(tmp_path)
        r = self._report()
        payload = json.dumps({
            "results": [{"check_id": "a.b.dangerous", "path": str(tmp_path / "x.py"),
                         "start": {"line": 3},
                         "extra": {"message": "m", "severity": "ERROR"}}],
            "errors": [{"message": "partial"}],
        })
        with patch("run_checks.semgrep.subprocess.run",
                   return_value=_completed(payload, returncode=1)):
            out = semgrep_mod._run_semgrep(
                str(tmp_path), {"semgrep-dangerous": {"id": "semgrep-dangerous"}}, r)
        # executed, and the one in-scope finding survives
        assert r.status_of("semgrep-dangerous") == EXECUTED
        assert len(out) == 1
        assert "internal error" in capsys.readouterr().err

    def test_dir_absent_records_not_installed(self, tmp_path):
        r = self._report()
        semgrep_mod._run_semgrep(str(tmp_path), {"semgrep-x": {"id": "semgrep-x"}}, r)
        assert r.status_of("semgrep-x") == SKIPPED
        assert r._records["semgrep-x"].reason == "not-installed"

    def test_binary_missing_records_tool_missing(self, tmp_path):
        self._dir(tmp_path)
        r = self._report()
        with patch("run_checks.semgrep.subprocess.run", side_effect=FileNotFoundError):
            semgrep_mod._run_semgrep(str(tmp_path), {"semgrep-x": {"id": "semgrep-x"}}, r)
        assert r.status_of("semgrep-x") == SKIPPED
        assert r._records["semgrep-x"].reason == "tool-missing"

    def test_timeout_records_failed(self, tmp_path):
        self._dir(tmp_path)
        r = self._report()
        with patch("run_checks.semgrep.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("semgrep", 300)):
            semgrep_mod._run_semgrep(str(tmp_path), {"semgrep-x": {"id": "semgrep-x"}}, r)
        assert r.status_of("semgrep-x") == FAILED
        assert r._records["semgrep-x"].reason == "timeout"

    def test_non_json_records_failed(self, tmp_path):
        self._dir(tmp_path)
        r = self._report()
        with patch("run_checks.semgrep.subprocess.run",
                   return_value=_completed("not json", returncode=0)):
            semgrep_mod._run_semgrep(str(tmp_path), {"semgrep-x": {"id": "semgrep-x"}}, r)
        assert r.status_of("semgrep-x") == FAILED
        assert r._records["semgrep-x"].reason == "non-json"

    def test_clean_run_records_executed(self, tmp_path):
        self._dir(tmp_path)
        r = self._report()
        payload = json.dumps({"results": [], "errors": []})
        with patch("run_checks.semgrep.subprocess.run",
                   return_value=_completed(payload, returncode=0)):
            semgrep_mod._run_semgrep(str(tmp_path), {"semgrep-x": {"id": "semgrep-x"}}, r)
        assert r.status_of("semgrep-x") == EXECUTED

    def test_report_none_preserves_behavior(self, tmp_path):
        """Legacy callers (report=None) get identical behavior — no crash."""
        self._dir(tmp_path)
        with patch("run_checks.semgrep.subprocess.run",
                   return_value=_completed("", returncode=2, stderr="X509")):
            out = semgrep_mod._run_semgrep(str(tmp_path), {"semgrep-x"})
        assert out == []


# ── pyright / tsc stage recording ───────────────────────────────────────────


class TestPyrightRecording:
    def test_rc_nonzero_no_stdout_records_failed(self, capsys):
        r = RunReport([{"id": "pyright-missing-imports"}])
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed("", returncode=2, stderr="pyright exploded")):
            lsp_mod._run_pyright("/repo", {"pyright-missing-imports": {}}, r)
        assert r.status_of("pyright-missing-imports") == FAILED
        assert r._records["pyright-missing-imports"].reason == "nonzero-no-output"
        assert "did NOT run" in capsys.readouterr().err

    def test_binary_missing_records_tool_missing(self):
        r = RunReport([{"id": "pyright-missing-imports"}])
        with patch("run_checks.lsp.subprocess.run", side_effect=FileNotFoundError):
            lsp_mod._run_pyright("/repo", {"pyright-missing-imports": {}}, r)
        assert r.status_of("pyright-missing-imports") == SKIPPED
        assert r._records["pyright-missing-imports"].reason == "tool-missing"

    def test_timeout_records_failed(self):
        r = RunReport([{"id": "pyright-missing-imports"}])
        with patch("run_checks.lsp.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("pyright", 300)):
            lsp_mod._run_pyright("/repo", {"pyright-missing-imports": {}}, r)
        assert r.status_of("pyright-missing-imports") == FAILED

    def test_non_json_records_failed(self):
        r = RunReport([{"id": "pyright-missing-imports"}])
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed("garbage", returncode=1)):
            lsp_mod._run_pyright("/repo", {"pyright-missing-imports": {}}, r)
        assert r.status_of("pyright-missing-imports") == FAILED

    def test_rc1_with_json_records_executed(self, tmp_path):
        """Success discriminator non-regression: pyright exits 1 when it HAS
        findings — that is executed, not failed."""
        r = RunReport([{"id": "pyright-missing-imports"}])
        payload = json.dumps({"generalDiagnostics": [{
            "severity": "error", "rule": "reportMissingImports",
            "file": str(tmp_path / "x.py"),
            "range": {"start": {"line": 0}}, "message": "cannot find",
        }]})
        with patch("run_checks.lsp.subprocess.run",
                   return_value=_completed(payload, returncode=1)):
            out = lsp_mod._run_pyright(str(tmp_path),
                                       {"pyright-missing-imports": {}}, r)
        assert r.status_of("pyright-missing-imports") == EXECUTED
        assert len(out) == 1


class TestTscRecording:
    def test_no_tsconfig_records_input_missing(self, tmp_path):
        r = RunReport([{"id": "tsc-type-error"}])
        lsp_mod._run_tsc(str(tmp_path), {"tsc-type-error": {}}, r)
        assert r.status_of("tsc-type-error") == SKIPPED
        assert r._records["tsc-type-error"].reason == "input-missing"


# ── eslint stage recording ──────────────────────────────────────────────────


class TestEslintRecording:
    def test_no_frontend_records_input_missing(self, tmp_path):
        """The path whose docstring falsely claimed it warns — silent by design,
        but now recorded."""
        r = RunReport([{"id": "lint-error"}])
        out = lint_mod._run_eslint(str(tmp_path), {"lint-error"}, r)
        assert out == []
        assert r.status_of("lint-error") == SKIPPED
        assert r._records["lint-error"].reason == "input-missing"

    def _frontend(self, tmp_path, with_config_next=True):
        fe = tmp_path / "web"
        (fe / "node_modules" / "eslint").mkdir(parents=True)
        if with_config_next:
            cfg = fe / "node_modules" / "eslint-config-next"
            cfg.mkdir(parents=True)
            (cfg / "package.json").write_text("{}")
        return tmp_path

    def test_config_next_missing_records_input_missing(self, tmp_path):
        self._frontend(tmp_path, with_config_next=False)
        r = RunReport([{"id": "lint-error"}])
        lint_mod._run_eslint(str(tmp_path), {"lint-error"}, r)
        assert r.status_of("lint-error") == SKIPPED
        assert r._records["lint-error"].reason == "input-missing"

    def test_binary_missing_records_tool_missing(self, tmp_path):
        self._frontend(tmp_path)
        r = RunReport([{"id": "lint-error"}])
        with patch("run_checks.lint.subprocess.run", side_effect=FileNotFoundError):
            lint_mod._run_eslint(str(tmp_path), {"lint-error"}, r)
        assert r.status_of("lint-error") == SKIPPED
        assert r._records["lint-error"].reason == "tool-missing"

    def test_timeout_records_failed(self, tmp_path):
        self._frontend(tmp_path)
        r = RunReport([{"id": "lint-error"}])
        with patch("run_checks.lint.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("eslint", 300)):
            lint_mod._run_eslint(str(tmp_path), {"lint-error"}, r)
        assert r.status_of("lint-error") == FAILED

    def test_rc_nonzero_no_stdout_records_failed(self, tmp_path):
        self._frontend(tmp_path)
        r = RunReport([{"id": "lint-error"}])
        with patch("run_checks.lint.subprocess.run",
                   return_value=_completed("", returncode=2, stderr="eslint crashed")):
            lint_mod._run_eslint(str(tmp_path), {"lint-error"}, r)
        assert r.status_of("lint-error") == FAILED
        assert r._records["lint-error"].reason == "nonzero-no-output"

    def test_non_json_records_failed(self, tmp_path):
        self._frontend(tmp_path)
        r = RunReport([{"id": "lint-error"}])
        with patch("run_checks.lint.subprocess.run",
                   return_value=_completed("not json", returncode=1)):
            lint_mod._run_eslint(str(tmp_path), {"lint-error"}, r)
        assert r.status_of("lint-error") == FAILED

    def test_clean_run_records_executed(self, tmp_path):
        self._frontend(tmp_path)
        r = RunReport([{"id": "lint-error"}])
        with patch("run_checks.lint.subprocess.run",
                   return_value=_completed("[]", returncode=0)):
            lint_mod._run_eslint(str(tmp_path), {"lint-error"}, r)
        assert r.status_of("lint-error") == EXECUTED


# ── pip-audit stage recording ───────────────────────────────────────────────


class TestPipAuditRecording:
    def test_not_on_path_records_tool_missing(self, tmp_path):
        r = RunReport([{"id": "pip-audit-vuln"}])
        with patch("run_checks.pip_audit.subprocess.run", side_effect=FileNotFoundError):
            pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
        assert r.status_of("pip-audit-vuln") == SKIPPED
        assert r._records["pip-audit-vuln"].reason == "tool-missing"

    def test_rc_nonzero_no_stdout_records_failed(self, tmp_path):
        r = RunReport([{"id": "pip-audit-vuln"}])
        with patch("run_checks.pip_audit.subprocess.run",
                   return_value=_completed("", returncode=2, stderr="bad flag")):
            pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
        assert r.status_of("pip-audit-vuln") == FAILED
        assert r._records["pip-audit-vuln"].reason == "nonzero-no-output"

    def test_non_json_records_failed(self, tmp_path):
        r = RunReport([{"id": "pip-audit-vuln"}])
        with patch("run_checks.pip_audit.subprocess.run",
                   return_value=_completed("nope", returncode=0)):
            pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
        assert r.status_of("pip-audit-vuln") == FAILED

    def test_clean_run_records_executed(self, tmp_path):
        r = RunReport([{"id": "pip-audit-vuln"}])
        with patch("run_checks.pip_audit.subprocess.run",
                   return_value=_completed(json.dumps({"dependencies": []}), returncode=0)):
            pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
        assert r.status_of("pip-audit-vuln") == EXECUTED

    def test_module_fallback_timeout_records_failed(self, tmp_path):
        """Console script absent (FileNotFoundError) then the `-m pip_audit`
        fallback times out → failed(timeout), NOT skipped(tool-missing): a
        timeout is lost work, not a declined precondition (§1)."""
        r = RunReport([{"id": "pip-audit-vuln"}])
        with patch("run_checks.pip_audit.subprocess.run",
                   side_effect=[FileNotFoundError,
                                subprocess.TimeoutExpired("pip_audit", 300)]):
            pip_audit_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"}, r)
        assert r.status_of("pip-audit-vuln") == FAILED
        assert r._records["pip-audit-vuln"].reason == "timeout"


# ── coverage stage recording (the blocking-gate-inert case) ─────────────────


class TestCoverageRecording:
    def test_placeholder_critical_path_records_not_configured(self, tmp_path):
        r = RunReport([{"id": "coverage-diff-python"}])
        check = {"id": "coverage-diff-python", "critical_path": ["<crit>/"],
                 "blocking": True}
        coverage_mod._run_diff_cover_check(str(tmp_path), check, r)
        assert r.status_of("coverage-diff-python") == SKIPPED
        assert r._records["coverage-diff-python"].reason == "not-configured"

    def test_localized_report_absent_records_input_missing(self, tmp_path):
        """The blocking-gate-inert case: armed critical_path but no report → the
        gate contributes, invokes, and (used to) say nothing."""
        r = RunReport([{"id": "coverage-diff-python"}])
        check = {"id": "coverage-diff-python", "critical_path": ["billing/"],
                 "report": "coverage.xml", "blocking": True}
        coverage_mod._run_diff_cover_check(str(tmp_path), check, r)
        assert r.status_of("coverage-diff-python") == SKIPPED
        assert r._records["coverage-diff-python"].reason == "input-missing"

    def test_diff_cover_missing_records_tool_missing(self, tmp_path):
        (tmp_path / "coverage.xml").write_text("<coverage/>")
        r = RunReport([{"id": "coverage-diff-python"}])
        check = {"id": "coverage-diff-python", "critical_path": ["billing/"],
                 "report": "coverage.xml"}
        with patch("run_checks.coverage.subprocess.run", side_effect=FileNotFoundError):
            coverage_mod._run_diff_cover_check(str(tmp_path), check, r)
        assert r.status_of("coverage-diff-python") == SKIPPED
        assert r._records["coverage-diff-python"].reason == "tool-missing"

    def test_non_json_records_failed(self, tmp_path):
        (tmp_path / "coverage.xml").write_text("<coverage/>")
        r = RunReport([{"id": "coverage-diff-python"}])
        check = {"id": "coverage-diff-python", "critical_path": ["billing/"],
                 "report": "coverage.xml"}
        with patch("run_checks.coverage.subprocess.run",
                   return_value=_completed("not json", returncode=0)):
            coverage_mod._run_diff_cover_check(str(tmp_path), check, r)
        assert r.status_of("coverage-diff-python") == FAILED

    def test_executed_records_executed(self, tmp_path):
        (tmp_path / "coverage.xml").write_text("<coverage/>")
        r = RunReport([{"id": "coverage-diff-python"}])
        check = {"id": "coverage-diff-python", "critical_path": ["billing/"],
                 "report": "coverage.xml"}
        with patch("run_checks.coverage.subprocess.run",
                   return_value=_completed(json.dumps({"src_stats": {}}), returncode=0)):
            coverage_mod._run_diff_cover_check(str(tmp_path), check, r)
        assert r.status_of("coverage-diff-python") == EXECUTED

    def test_exception_in_wrapper_records_failed(self, tmp_path):
        r = RunReport([{"id": "coverage-diff-python"}])
        check = {"id": "coverage-diff-python", "critical_path": ["billing/"],
                 "report": "coverage.xml"}
        (tmp_path / "coverage.xml").write_text("<coverage/>")
        with patch("run_checks.coverage._run_diff_cover_check",
                   side_effect=RuntimeError("boom")):
            coverage_mod._run_coverage(str(tmp_path), [check], r)
        assert r.status_of("coverage-diff-python") == FAILED
        assert r._records["coverage-diff-python"].reason == "exception"


# ── grep stage recording (via run_check) ────────────────────────────────────


class TestGrepRecording:
    def _check(self, **kw):
        base = {"id": "grep-c", "severity": "medium", "description": "d"}
        base.update(kw)
        return base

    def test_placeholder_paths_records_paths_unresolved(self, tmp_path):
        r = RunReport([{"id": "grep-c", "paths": ["<api module>/"]}])
        check = self._check(pattern="x", paths=["<api module>/"], include=["*.py"])
        grep_mod.run_check(check, str(tmp_path), r)
        assert r.status_of("grep-c") == SKIPPED
        rec = r._records["grep-c"]
        assert rec.reason == "paths-unresolved"
        assert "placeholder" in rec.detail

    def test_localized_missing_path_detail_differs(self, tmp_path):
        r = RunReport([{"id": "grep-c", "paths": ["real_dir/"]}])
        check = self._check(pattern="x", paths=["real_dir/"], include=["*.py"])
        grep_mod.run_check(check, str(tmp_path), r)
        assert r.status_of("grep-c") == SKIPPED
        assert "no configured path" in r._records["grep-c"].detail

    def test_no_pattern_records_not_configured(self, tmp_path):
        (tmp_path / "src").mkdir()
        r = RunReport([{"id": "grep-c", "paths": ["src/"]}])
        check = self._check(paths=["src/"], include=["*.py"])  # no pattern
        grep_mod.run_check(check, str(tmp_path), r)
        assert r.status_of("grep-c") == SKIPPED
        assert r._records["grep-c"].reason == "not-configured"

    def test_executed_records_executed(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("eval(x)\n")
        r = RunReport([{"id": "grep-c", "paths": ["src/"]}])
        check = self._check(pattern=r"eval\(", paths=["src/"], include=["*.py"])
        out = grep_mod.run_check(check, str(tmp_path), r)
        assert r.status_of("grep-c") == EXECUTED
        assert len(out) == 1

    def test_rc2_records_failed(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("x\n")
        r = RunReport([{"id": "grep-c", "paths": ["src/"]}])
        # An invalid extended regex makes grep exit 2.
        check = self._check(pattern="(", paths=["src/"], include=["*.py"])
        grep_mod.run_check(check, str(tmp_path), r)
        assert r.status_of("grep-c") == FAILED
        assert r._records["grep-c"].reason == "grep-error"

    def test_timeout_records_failed(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("x\n")
        r = RunReport([{"id": "grep-c", "paths": ["src/"]}])
        check = self._check(pattern="x", paths=["src/"], include=["*.py"])
        with patch("run_checks.grep.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("grep", 30)):
            grep_mod.run_check(check, str(tmp_path), r)
        assert r.status_of("grep-c") == FAILED
        assert r._records["grep-c"].reason == "timeout"

    def test_grep_binary_missing_records_tool_missing(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("x\n")
        r = RunReport([{"id": "grep-c", "paths": ["src/"]}])
        check = self._check(pattern="x", paths=["src/"], include=["*.py"])
        with patch("run_checks.grep.subprocess.run", side_effect=FileNotFoundError):
            grep_mod.run_check(check, str(tmp_path), r)
        assert r.status_of("grep-c") == SKIPPED
        assert r._records["grep-c"].reason == "tool-missing"

    def test_position_check_unresolved_paths(self, tmp_path):
        r = RunReport([{"id": "grep-c", "paths": ["<x>/"]}])
        check = self._check(
            paths=["<x>/"], include=["*.py"],
            position_check={"earlier": "a", "later": "b"})
        grep_mod.run_check(check, str(tmp_path), r)
        assert r.status_of("grep-c") == SKIPPED
        assert r._records["grep-c"].reason == "paths-unresolved"

    def test_position_check_invalid_regex_records_misconfigured(self, tmp_path):
        (tmp_path / "src").mkdir()
        r = RunReport([{"id": "grep-c", "paths": ["src/"]}])
        check = self._check(
            paths=["src/"], include=["*.py"],
            position_check={"earlier": "(", "later": "b"})
        grep_mod.run_check(check, str(tmp_path), r)
        assert r.status_of("grep-c") == SKIPPED
        assert r._records["grep-c"].reason == "misconfigured"

    def test_position_check_missing_regex_records_not_configured(self, tmp_path):
        (tmp_path / "src").mkdir()
        r = RunReport([{"id": "grep-c", "paths": ["src/"]}])
        check = self._check(paths=["src/"], include=["*.py"],
                            position_check={"earlier": "a"})  # no later
        grep_mod.run_check(check, str(tmp_path), r)
        assert r.status_of("grep-c") == SKIPPED
        assert r._records["grep-c"].reason == "not-configured"

    def test_position_check_executed(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.py").write_text("earlier\nlater\n")
        r = RunReport([{"id": "grep-c", "paths": ["src/"]}])
        check = self._check(
            paths=["src/"], include=["*.py"],
            position_check={"earlier": "earlier", "later": "later"})
        grep_mod.run_check(check, str(tmp_path), r)
        assert r.status_of("grep-c") == EXECUTED

    def test_report_none_no_crash(self, tmp_path):
        check = self._check(pattern="x", paths=["<x>/"], include=["*.py"])
        assert grep_mod.run_check(check, str(tmp_path)) == []


# ── cli.main end-to-end ─────────────────────────────────────────────────────


def _write_checks(tmp_path, body):
    claude = tmp_path / ".claude"
    claude.mkdir(exist_ok=True)
    (claude / "checks.yml").write_text(body)


def _run_cli(tmp_path, monkeypatch, argv_extra, mode="both"):
    argv = ["run_checks", "--repo-root", str(tmp_path), "--mode", mode]
    argv += argv_extra
    monkeypatch.setattr(sys, "argv", argv)
    code = 0
    try:
        rci.main()
    except SystemExit as e:
        code = e.code if e.code is not None else 0
    return code


_MOTIVATING_YML = """\
checks:
  - id: grep-placeholder
    severity: medium
    paths: ["<api module>/"]
    include: ["*.py"]
    pattern: 'eval\\\\('
    description: "x"
    used_by: [security-audit]
  - id: semgrep-logger-fstring
    severity: medium
    description: "x"
    used_by: [security-audit]
"""


def test_motivating_scenario_security_mode_all_stages_dead(tmp_path, monkeypatch, capsys):
    """The `0 findings from 13 checks` case, in miniature: a placeholder grep
    check skips, semgrep crashes — the summary must say `0 executed / 1 skipped
    / 1 failed`, NOT hide it behind a bare count. Exit 0 without the flag."""
    _write_checks(tmp_path, _MOTIVATING_YML)
    (tmp_path / ".claude" / "semgrep").mkdir()
    crash = "Failed to create system store X509 authenticator: ca-certs: empty trust anchors"
    with patch("run_checks.semgrep.subprocess.run",
               return_value=_completed("", returncode=2, stderr=crash)):
        code = _run_cli(tmp_path, monkeypatch, [], mode="security")
    err = capsys.readouterr().err
    assert code == 0
    assert "0 executed" in err
    assert "1 skipped" in err
    assert "1 failed" in err
    assert "of 2 selected" in err
    assert "semgrep" in err and "X509" in err
    # NOT the old summary shape.
    assert "finding(s) from" not in err


_BLOCKING_COV_YML = """\
checks:
  - id: coverage-diff-python
    severity: medium
    critical_path: ["billing/"]
    report: "coverage.xml"
    description: "x"
    used_by: [codebase-review]
    blocking: true
"""


def test_failed_blocking_check_fails_gate(tmp_path, monkeypatch, capsys):
    """A localized blocking coverage gate whose diff-cover crashes → the gate
    fails under --fail-on-blocking even though the crash produced 0 findings."""
    _write_checks(tmp_path, _BLOCKING_COV_YML)
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    with patch("run_checks.coverage.subprocess.run",
               return_value=_completed("", returncode=1, stderr="diff-cover exploded")):
        code = _run_cli(tmp_path, monkeypatch, ["--fail-on-blocking"])
    err = capsys.readouterr().err
    assert code == 1
    assert "FAILED to run" in err
    assert "coverage-diff-python" in err


def test_failed_blocking_check_passes_without_flag(tmp_path, monkeypatch):
    _write_checks(tmp_path, _BLOCKING_COV_YML)
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    with patch("run_checks.coverage.subprocess.run",
               return_value=_completed("", returncode=1, stderr="boom")):
        code = _run_cli(tmp_path, monkeypatch, [])
    assert code == 0


def test_skipped_blocking_check_passes_gate_with_warning(tmp_path, monkeypatch, capsys):
    """A localized blocking coverage gate whose report is absent → ⚠ in the
    summary but exit 0 (gate-on-skipped would redden every armed consumer)."""
    _write_checks(tmp_path, _BLOCKING_COV_YML)
    # No coverage.xml → report absent → skipped(input-missing), localized → ⚠.
    code = _run_cli(tmp_path, monkeypatch, ["--fail-on-blocking"])
    err = capsys.readouterr().err
    assert code == 0
    assert "⚠ BLOCKING CHECK DID NOT RUN" in err


_PLACEHOLDER_COV_YML = _BLOCKING_COV_YML.replace(
    'critical_path: ["billing/"]', 'critical_path: ["<crit path>/"]'
)


def test_placeholder_blocking_check_stays_calm(tmp_path, monkeypatch, capsys):
    """A placeholder (unlocalized) blocking coverage gate is unarmed on a fresh
    install — calm line, no ⚠, exit 0 even with --fail-on-blocking."""
    _write_checks(tmp_path, _PLACEHOLDER_COV_YML)
    code = _run_cli(tmp_path, monkeypatch, ["--fail-on-blocking"])
    err = capsys.readouterr().err
    assert code == 0
    assert "⚠" not in err
    assert "gate unarmed" in err


# ── --update-baseline single pass + refusal ─────────────────────────────────


_BASELINE_YML = """\
checks:
  - id: semgrep-logger-fstring
    severity: medium
    description: "x"
    used_by: [codebase-review]
    blocking: true
"""


def test_update_baseline_runs_each_stage_once(tmp_path, monkeypatch):
    """The single-pass restructure: --update-baseline must not run every stage
    twice (the old code ran the mode pass then re-ran all checks)."""
    _write_checks(tmp_path, _BASELINE_YML)
    (tmp_path / ".claude" / "semgrep").mkdir()
    payload = json.dumps({"results": [], "errors": []})
    with patch("run_checks.semgrep.subprocess.run",
               return_value=_completed(payload)) as m:
        code = _run_cli(tmp_path, monkeypatch, ["--update-baseline"])
    assert code == 0
    assert m.call_count == 1  # exactly one semgrep invocation, not two


def test_update_baseline_refuses_on_blocking_failure(tmp_path, monkeypatch, capsys):
    """A crashed blocking tool is not a state to snapshot — refuse, write nothing."""
    _write_checks(tmp_path, _BASELINE_YML)
    (tmp_path / ".claude" / "semgrep").mkdir()
    with patch("run_checks.semgrep.subprocess.run",
               return_value=_completed("", returncode=2, stderr="X509 crash")):
        code = _run_cli(tmp_path, monkeypatch, ["--update-baseline"])
    err = capsys.readouterr().err
    assert code == 1
    assert "refusing to write baseline" in err
    assert not (tmp_path / ".claude" / "checks_baseline.txt").exists()


def test_update_baseline_proceeds_when_clean(tmp_path, monkeypatch, capsys):
    _write_checks(tmp_path, _BASELINE_YML)
    (tmp_path / ".claude" / "semgrep").mkdir()
    payload = json.dumps({"results": [], "errors": []})
    with patch("run_checks.semgrep.subprocess.run", return_value=_completed(payload)):
        code = _run_cli(tmp_path, monkeypatch, ["--update-baseline"])
    err = capsys.readouterr().err
    assert code == 0
    assert "Wrote" in err
    assert (tmp_path / ".claude" / "checks_baseline.txt").exists()


# ── skill-prose drift guards (spec §6) ──────────────────────────────────────

_SKILLS = Path(__file__).resolve().parent.parent / "core" / "skills"
_ACCOUNTING_ANCHOR = "Read the pre-scan accounting block — do not just count findings."


def test_both_review_skills_carry_the_accounting_block_instruction():
    """Both review skills must tell the agent to read the accounting block and
    carry failed/⚠ stages into the round summary — else the whole layer is
    invisible to the reviewer who most needs it."""
    for skill in ("codebase-review", "security-audit"):
        text = (_SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
        assert _ACCOUNTING_ANCHOR in text, f"{skill} lost the accounting-block anchor"
        assert "BLOCKING CHECK DID NOT RUN" in text


def test_security_audit_documents_no_pyright_in_security_mode():
    """The 'why is security mode's selected count lower' surprise, documented."""
    text = (_SKILLS / "security-audit" / "SKILL.md").read_text(encoding="utf-8")
    assert "no `pyright` entries" in text


_SELF_BOOTSTRAP_ANCHOR = "The runner resolves its own interpreter and tools — run it as written."


def test_both_review_skills_state_the_runner_self_bootstraps_at_step_2b():
    """A cautious agent that reads run_checks.sh, infers it must `pip install`,
    and declines on a 'do not install anything' instruction silently loses the
    entire deterministic pre-scan (cross-harness cell-1, 2026-07-19: 24 findings
    vs the reference cell's 372). Both review skills must state at the point of
    invocation that the runner resolves its own toolchain, and warn that
    hand-rolled grep is not a substitute — placed BEFORE the accounting block so
    it is read before the agent decides whether it can run the command at all.

    The PyYAML clause is asserted separately because it is the correctness crux
    (Phase 136 adversarial review): PyYAML is the runner's one *hard* dependency
    — its absence is a total-run `sys.exit(2)` with no accounting block, not a
    per-stage skip — so it must never be grouped with the optional scanners that
    'degrade only their own stage'."""
    for skill in ("codebase-review", "security-audit"):
        text = (_SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
        assert _SELF_BOOTSTRAP_ANCHOR in text, f"{skill} lost the self-bootstrap statement"
        assert "hand-rolled `grep`" in text, (
            f"{skill} lost the hand-rolled-grep anti-pattern warning"
        )
        assert "one **hard** dependency is PyYAML" in text, (
            f"{skill} must call PyYAML a hard dependency, not group it with optional scanners"
        )
        assert text.index(_SELF_BOOTSTRAP_ANCHOR) < text.index(_ACCOUNTING_ANCHOR), (
            f"{skill}: self-bootstrap statement must precede the accounting block "
            "(it must be read at the point of invocation)"
        )
