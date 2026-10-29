"""The overlay's disabling sentinel reaches the eslint and pip-audit stages (`Q-701`).

`_shared/promotion-write-target.md` and both review skills tell a consumer to disable a
shipped check with an override entry `paths: ["__disabled_no_op__"]`. `_classify_checks`
handed eslint and pip-audit bare id sets and neither read `paths:`, so the override changed
nothing: a blocking `pip-audit-vuln` overridden that way still failed `--fail-on-blocking`.
Phase 402 gave semgrep, pyright and tsc `config.skip_sentinel_disabled`; these two stages
now call it first too.
"""
import json
import subprocess
import sys
from unittest.mock import patch

import run_checks.cli as cli_mod
import run_checks.lint as lint_mod
import run_checks.pip_audit as pip_audit_mod
import run_checks_impl as rci
from run_checks.accounting import EXECUTED, SKIPPED, RunReport

OFF = "disabled: every paths: entry carries the __disabled_no_op__ sentinel"
SENTINEL = ["__disabled_no_op__"]


def _completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def _frontend(tmp_path):
    fe = tmp_path / "web"
    (fe / "node_modules" / "eslint").mkdir(parents=True)
    cfg = fe / "node_modules" / "eslint-config-next"
    cfg.mkdir(parents=True)
    (cfg / "package.json").write_text("{}")
    return fe


def _eslint_json(fe):
    return json.dumps([{"filePath": str(fe / "a.ts"), "messages": [
        {"ruleId": "no-eval", "line": 3, "severity": 2, "message": "eval"}]}])


VULN = json.dumps({"dependencies": [{"name": "pkg", "version": "1.0", "vulns": [
    {"id": "GHSA-xxxx", "fix_versions": ["1.1"], "description": "bad"}]}]})


def test_classify_hands_both_stages_their_check_dicts():
    checks = [{"id": "lint-error", "paths": SENTINEL}, {"id": "pip-audit-vuln"}]
    _, _, _, lint, pip, _, _ = cli_mod._classify_checks(checks)
    assert lint == {"lint-error": checks[0]}
    assert pip == {"pip-audit-vuln": checks[1]}


class TestEslint:
    def test_disabled_records_skipped_and_starts_nothing(self, tmp_path):
        _frontend(tmp_path)
        r = RunReport([{"id": "lint-error"}])
        with patch("run_checks.lint.subprocess.run") as run:
            out = lint_mod._run_eslint(str(tmp_path), {
                "lint-error": {"id": "lint-error", "paths": SENTINEL}}, r)
        assert out == [] and not run.called
        rec = r._records["lint-error"]
        assert (rec.status, rec.stage, rec.reason, rec.detail) == (
            SKIPPED, "eslint", "paths-unresolved", OFF)
        assert "executed with 0 findings" not in r.render([], mode="quality")

    def test_disabled_reads_disabled_with_no_frontend(self, tmp_path):
        r = RunReport([{"id": "lint-error"}])
        lint_mod._run_eslint(str(tmp_path), {
            "lint-error": {"id": "lint-error", "paths": SENTINEL}}, r)
        assert r._records["lint-error"].detail == OFF

    def test_the_frontend_placeholder_mapped_to_the_sentinel_disables_it(self, tmp_path):
        """The shipped `lint-error` carries `paths: ["<frontend>/"]`; a consumer who maps
        `<frontend>` to the sentinel disables eslint now, not only tsc."""
        _frontend(tmp_path)
        for paths, want in ((["__disabled_no_op__/"], SKIPPED), (["<frontend>/"], EXECUTED)):
            r = RunReport([{"id": "lint-error"}])
            with patch("run_checks.lint.subprocess.run",
                       return_value=_completed("[]", returncode=0)):
                lint_mod._run_eslint(str(tmp_path), {
                    "lint-error": {"id": "lint-error", "paths": paths}}, r)
            assert r.status_of("lint-error") == want, paths

    def test_a_disabled_lint_error_beside_a_live_lint_id_emits_no_finding(self, tmp_path):
        """A consumer's live `lint-*` keeps eslint running; the disabled catch-all must
        not then report under its own id."""
        fe = _frontend(tmp_path)
        included = {"lint-error": {"id": "lint-error", "paths": SENTINEL},
                    "lint-custom": {"id": "lint-custom"}}
        r = RunReport([{"id": i} for i in included])
        with patch("run_checks.lint.subprocess.run",
                   return_value=_completed(_eslint_json(fe), returncode=1)):
            out = lint_mod._run_eslint(str(tmp_path), included, r)
        assert out == []
        assert r.status_of("lint-error") == SKIPPED
        assert r.status_of("lint-custom") == EXECUTED

    def test_a_live_lint_error_still_reports(self, tmp_path):
        fe = _frontend(tmp_path)
        r = RunReport([{"id": "lint-error"}])
        with patch("run_checks.lint.subprocess.run",
                   return_value=_completed(_eslint_json(fe), returncode=1)):
            out = lint_mod._run_eslint(str(tmp_path), {
                "lint-error": {"id": "lint-error", "paths": ["<frontend>/"]}}, r)
        assert [f[0] for f in out] == ["lint-error"]


class TestPipAudit:
    def test_disabled_records_skipped_and_starts_nothing(self, tmp_path):
        r = RunReport([{"id": "pip-audit-vuln"}])
        with patch("run_checks.pip_audit.subprocess.run") as run:
            out = pip_audit_mod._run_pip_audit(str(tmp_path), {
                "pip-audit-vuln": {"id": "pip-audit-vuln", "paths": SENTINEL}}, r)
        assert out == [] and not run.called
        rec = r._records["pip-audit-vuln"]
        assert (rec.status, rec.stage, rec.reason, rec.detail) == (
            SKIPPED, "pip-audit", "paths-unresolved", OFF)

    def test_the_shipped_entry_with_no_paths_still_runs(self, tmp_path):
        r = RunReport([{"id": "pip-audit-vuln"}])
        with patch("run_checks.pip_audit.subprocess.run",
                   return_value=_completed(VULN, returncode=1)):
            out = pip_audit_mod._run_pip_audit(str(tmp_path), {
                "pip-audit-vuln": {"id": "pip-audit-vuln"}}, r)
        assert [f[0] for f in out] == ["pip-audit-vuln"]
        assert r.status_of("pip-audit-vuln") == EXECUTED

    def test_a_disabled_vuln_check_beside_a_live_one_emits_no_finding(self, tmp_path):
        included = {"pip-audit-vuln": {"id": "pip-audit-vuln", "paths": SENTINEL},
                    "pip-audit-other": {"id": "pip-audit-other"}}
        r = RunReport([{"id": i} for i in included])
        with patch("run_checks.pip_audit.subprocess.run",
                   return_value=_completed(VULN, returncode=1)):
            out = pip_audit_mod._run_pip_audit(str(tmp_path), included, r)
        assert out == []
        assert r.status_of("pip-audit-vuln") == SKIPPED
        assert r.status_of("pip-audit-other") == EXECUTED


def test_a_disabled_blocking_pip_audit_check_no_longer_fails_the_gate(
        tmp_path, monkeypatch, capsys):
    """The entry's repro, through `main`: rc 1 over a finding the overlay disabled."""
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "checks.yml").write_text(
        "checks:\n"
        "  - id: pip-audit-vuln\n"
        "    severity: high\n"
        '    paths: ["__disabled_no_op__"]\n'
        '    description: "x"\n'
        "    used_by: [security-audit]\n"
        "    blocking: true\n")
    monkeypatch.setattr(sys, "argv", ["run_checks", "--repo-root", str(tmp_path),
                                      "--mode", "security", "--fail-on-blocking"])
    with patch("run_checks.pip_audit.subprocess.run",
               return_value=_completed(VULN, returncode=1)) as run:
        try:
            rci.main()
            code = 0
        except SystemExit as e:
            code = e.code or 0
    err = capsys.readouterr().err
    assert code == 0, err
    # `run_checks.pip_audit.subprocess` is the subprocess module, so other stages' calls land
    # on this mock too; none may be pip-audit's.
    assert not [c for c in run.call_args_list if "pip_audit" in str(c) or "pip-audit" in str(c)]
    assert "disabled" in err and "pip-audit" in err


def test_a_disabled_blocking_lint_check_no_longer_fails_the_gate(tmp_path, monkeypatch, capsys):
    """eslint's twin of the test above, through `main`, so the hand-off from `_classify_checks`
    through `_run_all_stages` is covered for both stages (round 1, lens B: a set passed there
    reopened `Q-701` for eslint with every other test green)."""
    fe = _frontend(tmp_path)
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "checks.yml").write_text(
        "checks:\n"
        "  - id: lint-error\n"
        "    severity: medium\n"
        '    paths: ["__disabled_no_op__"]\n'
        '    description: "x"\n'
        "    used_by: [codebase-review]\n"
        "    blocking: true\n")
    monkeypatch.setattr(sys, "argv", ["run_checks", "--repo-root", str(tmp_path),
                                      "--mode", "quality", "--fail-on-blocking"])
    with patch("run_checks.lint.subprocess.run",
               return_value=_completed(_eslint_json(fe), returncode=1)) as run:
        try:
            rci.main()
            code = 0
        except SystemExit as e:
            code = e.code or 0
    err = capsys.readouterr().err
    assert code == 0, err
    assert not [c for c in run.call_args_list if "eslint" in str(c)]
    assert "disabled" in err and "eslint" in err
