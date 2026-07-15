"""Unit tests for the Phase 61a glob-scoped coverage stage.

Sysop-original (no gdp counterpart — gdp has no coverage stage). Covers
``run_checks/coverage.py``: the ``diff-cover`` JSON parser, the
``critical_path`` glob filter (the new schema capability), every graceful-skip
path (no critical_path / report absent / binary missing / timeout / bad JSON),
the dispatcher, the ``_path_in_critical`` matcher, and the registry contract
in ``core/companion/checks.yml.fragment``.

The subprocess boundary is mocked exactly as the pip-audit/eslint stage tests
do (``patch("run_checks_impl.subprocess.run")`` — ``subprocess`` is a
singleton module, so the patch reaches ``run_checks.coverage`` too). The
coverage report file is created on disk first because ``_run_diff_cover_check``
short-circuits to ``[]`` when the report is absent, *before* shelling out.

Test decision (Phase 61a / 58b discipline): these tests prove the measurement
contract — parser shape, glob scoping, and the five inert-by-default skip
paths that keep the stage from ever blocking or erroring on a consumer that
hasn't opted in. No test exercises a *real* ``diff-cover`` run because the
binary is absent in CI and the stage's value is the parse+filter+skip logic,
which the canned-JSON path covers fully; an integration test against a real
``diff-cover`` is filed alongside the eslint/pip-audit integration follow-up.
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


def _make_coverage_check(critical_path, report=None, check_id="coverage-diff-python"):
    """Construct a parsed coverage check dict matching the production schema."""
    check = {
        "id": check_id,
        "critical_path": list(critical_path),
        "severity": "medium",
        "description": "test coverage description",
        "used_by": ["codebase-review"],
        "blocking": False,
    }
    if report is not None:
        check["report"] = report
    return check


def _canned_diff_cover(src_stats=None):
    """A minimal diff-cover --format json payload."""
    if src_stats is None:
        src_stats = {
            "billing/charge.py": {
                "percent_covered": 75.0,
                "covered_lines": [10, 11],
                "violation_lines": [12, 15],
                "violations": [[12, None], [15, None]],
            }
        }
    return {
        "report_name": ["XML"],
        "diff_name": "main...HEAD",
        "src_stats": src_stats,
        "total_num_lines": 40,
        "total_num_violations": 2,
        "total_percent_covered": 95,
    }


def _mock_completed(payload, returncode=0):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=json.dumps(payload), stderr=""
    )


# ── Parser tests ──────────────────────────────────────────────────────────


def test_coverage_parser_emits_finding_per_violation_line(tmp_path):
    """Canned diff-cover JSON → one tuple per uncovered changed line."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    check = _make_coverage_check(["billing/"], report="coverage.xml")
    with patch("run_checks_impl.subprocess.run") as mock_run:
        mock_run.return_value = _mock_completed(_canned_diff_cover())
        findings = rci._run_diff_cover_check(str(tmp_path), check)
    assert len(findings) == 2, findings
    assert {f[0] for f in findings} == {"coverage-diff-python"}
    assert {f[1] for f in findings} == {
        "billing/charge.py:12",
        "billing/charge.py:15",
    }
    _, _, msg = findings[0]
    assert "not covered by tests" in msg
    assert "75%" in msg
    assert "MEDIUM" in msg


def test_coverage_filters_out_non_critical_path(tmp_path):
    """Files outside the critical_path globs are dropped; inside are kept."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    payload = _canned_diff_cover(
        {
            "billing/charge.py": {"percent_covered": 50.0, "violation_lines": [5]},
            "ui/widget.py": {"percent_covered": 50.0, "violation_lines": [9]},
        }
    )
    check = _make_coverage_check(["billing/"], report="coverage.xml")
    with patch("run_checks_impl.subprocess.run") as mock_run:
        mock_run.return_value = _mock_completed(payload)
        findings = rci._run_diff_cover_check(str(tmp_path), check)
    assert len(findings) == 1, findings
    assert findings[0][1] == "billing/charge.py:5"


def test_coverage_clean_diff_returns_empty(tmp_path):
    """A critical-path file with no violation_lines → no findings."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    payload = _canned_diff_cover(
        {"billing/charge.py": {"percent_covered": 100.0, "violation_lines": []}}
    )
    check = _make_coverage_check(["billing/"], report="coverage.xml")
    with patch("run_checks_impl.subprocess.run") as mock_run:
        mock_run.return_value = _mock_completed(payload)
        findings = rci._run_diff_cover_check(str(tmp_path), check)
    assert findings == []


def test_coverage_wildcard_glob_matches_nested(tmp_path):
    """A `dir/**`-style glob matches nested files via fnmatch."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    payload = _canned_diff_cover(
        {"auth/oauth/token.py": {"percent_covered": 0.0, "violation_lines": [3]}}
    )
    check = _make_coverage_check(["auth/**"], report="coverage.xml")
    with patch("run_checks_impl.subprocess.run") as mock_run:
        mock_run.return_value = _mock_completed(payload)
        findings = rci._run_diff_cover_check(str(tmp_path), check)
    assert len(findings) == 1
    assert findings[0][1] == "auth/oauth/token.py:3"


# ── Graceful-skip tests ───────────────────────────────────────────────────


def test_coverage_empty_critical_path_returns_no_findings(tmp_path):
    """No critical_path globs → empty list, no subprocess call (nothing to scope)."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    check = _make_coverage_check([], report="coverage.xml")
    with patch("run_checks_impl.subprocess.run") as mock_run:
        findings = rci._run_diff_cover_check(str(tmp_path), check)
        assert mock_run.call_count == 0
    assert findings == []


def test_coverage_skips_when_report_absent(tmp_path):
    """Report file not on disk → empty list, no subprocess call (CI produced none)."""
    check = _make_coverage_check(["billing/"], report="coverage.xml")
    with patch("run_checks_impl.subprocess.run") as mock_run:
        findings = rci._run_diff_cover_check(str(tmp_path), check)
        assert mock_run.call_count == 0
    assert findings == []


def test_coverage_skips_when_binary_missing(tmp_path, capsys):
    """FileNotFoundError → empty list + stderr install hint."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    check = _make_coverage_check(["billing/"], report="coverage.xml")
    with patch("run_checks_impl.subprocess.run", side_effect=FileNotFoundError):
        findings = rci._run_diff_cover_check(str(tmp_path), check)
    assert findings == []
    captured = capsys.readouterr()
    assert "diff-cover not on PATH" in captured.err
    assert "pip install diff-cover" in captured.err


def test_coverage_skips_on_timeout(tmp_path, capsys):
    """TimeoutExpired → empty list + stderr warning."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    check = _make_coverage_check(["billing/"], report="coverage.xml")
    with patch(
        "run_checks_impl.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="diff-cover", timeout=300),
    ):
        findings = rci._run_diff_cover_check(str(tmp_path), check)
    assert findings == []
    assert "timeout" in capsys.readouterr().err


def test_coverage_invalid_json_skips(tmp_path, capsys):
    """Non-JSON output → empty list + stderr warning."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    check = _make_coverage_check(["billing/"], report="coverage.xml")
    with patch("run_checks_impl.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="not json", stderr=""
        )
        findings = rci._run_diff_cover_check(str(tmp_path), check)
    assert findings == []
    assert "non-JSON" in capsys.readouterr().err


def test_coverage_empty_stdout_returns_empty(tmp_path):
    """diff-cover emits nothing on stdout (e.g. no diff) → empty list."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    check = _make_coverage_check(["billing/"], report="coverage.xml")
    with patch("run_checks_impl.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        findings = rci._run_diff_cover_check(str(tmp_path), check)
    assert findings == []


# ── Default-report-path tests ─────────────────────────────────────────────


def test_coverage_frontend_default_report_is_lcov(tmp_path):
    """coverage-diff-frontend with no `report:` field defaults to coverage/lcov.info."""
    (tmp_path / "coverage").mkdir()
    (tmp_path / "coverage" / "lcov.info").write_text("TN:\n")
    payload = _canned_diff_cover(
        {"components/Pay.tsx": {"percent_covered": 0.0, "violation_lines": [7]}}
    )
    check = _make_coverage_check(
        ["components/"], report=None, check_id="coverage-diff-frontend"
    )
    with patch("run_checks_impl.subprocess.run") as mock_run:
        mock_run.return_value = _mock_completed(payload)
        findings = rci._run_diff_cover_check(str(tmp_path), check)
    assert len(findings) == 1
    assert findings[0][0] == "coverage-diff-frontend"
    # The default lcov path was fed to diff-cover, not coverage.xml.
    called_cmd = mock_run.call_args.args[0]
    assert os.path.join("coverage", "lcov.info") in called_cmd


def test_coverage_unknown_id_without_report_skips(tmp_path):
    """A coverage check with an unrecognized id and no `report:` → empty (no default)."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    check = _make_coverage_check(
        ["billing/"], report=None, check_id="coverage-diff-mystery"
    )
    with patch("run_checks_impl.subprocess.run") as mock_run:
        findings = rci._run_diff_cover_check(str(tmp_path), check)
        assert mock_run.call_count == 0
    assert findings == []


# ── Dispatcher tests ──────────────────────────────────────────────────────


def test_run_coverage_concatenates_all_checks(tmp_path):
    """_run_coverage runs every passed check and concatenates findings."""
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    (tmp_path / "coverage").mkdir()
    (tmp_path / "coverage" / "lcov.info").write_text("TN:\n")
    py_check = _make_coverage_check(["billing/"], report="coverage.xml")
    fe_check = _make_coverage_check(
        ["components/"], report="coverage/lcov.info", check_id="coverage-diff-frontend"
    )

    def _side_effect(cmd, **_kwargs):
        if "coverage.xml" in cmd:
            return _mock_completed(
                _canned_diff_cover(
                    {"billing/a.py": {"percent_covered": 0.0, "violation_lines": [1]}}
                )
            )
        return _mock_completed(
            _canned_diff_cover(
                {"components/B.tsx": {"percent_covered": 0.0, "violation_lines": [2]}}
            )
        )

    with patch("run_checks_impl.subprocess.run", side_effect=_side_effect):
        findings = rci._run_coverage(str(tmp_path), [py_check, fe_check])
    ids = {f[0] for f in findings}
    assert ids == {"coverage-diff-python", "coverage-diff-frontend"}
    assert {f[1] for f in findings} == {"billing/a.py:1", "components/B.tsx:2"}


def test_run_coverage_empty_list_returns_empty(tmp_path):
    """No coverage checks → empty list (the all-tools-absent default)."""
    assert rci._run_coverage(str(tmp_path), []) == []


# ── _path_in_critical matcher tests ───────────────────────────────────────


def test_path_in_critical_directory_glob():
    assert rci._path_in_critical("billing/charge.py", ["billing/"]) is True
    assert rci._path_in_critical("billing/sub/x.py", ["billing/"]) is True
    assert rci._path_in_critical("billing", ["billing/"]) is True


def test_path_in_critical_bare_dir_glob():
    assert rci._path_in_critical("auth/login.py", ["auth"]) is True


def test_path_in_critical_wildcard_glob():
    assert rci._path_in_critical("api/routes/pay.py", ["api/**"]) is True
    assert rci._path_in_critical("api/routes/pay.py", ["**/pay.py"]) is True


def test_path_in_critical_no_match():
    assert rci._path_in_critical("ui/widget.py", ["billing/", "auth/"]) is False
    assert rci._path_in_critical("billings/x.py", ["billing/"]) is False


def test_path_in_critical_empty_globs():
    assert rci._path_in_critical("billing/charge.py", []) is False


# ── Registry-contract tests ───────────────────────────────────────────────


def test_coverage_entries_present_in_fragment():
    """Both coverage-* entries exist in the core fragment with the required fields."""
    parsed = rci.parse_checks_yml(_CHECKS_FRAGMENT)
    by_id = {c["id"]: c for c in parsed if c.get("id", "").startswith("coverage-")}
    assert "coverage-diff-python" in by_id
    assert "coverage-diff-frontend" in by_id
    for entry in by_id.values():
        assert entry.get("critical_path"), entry
        assert entry.get("report"), entry
        # Coverage entries scope via critical_path, never paths.
        assert "paths" not in entry, entry


def test_coverage_entries_are_blocking():
    """Phase 61b arms the gate — the shipped coverage-* checks are blocking."""
    parsed = rci.parse_checks_yml(_CHECKS_FRAGMENT)
    coverage_entries = [
        c for c in parsed if c.get("id", "").startswith("coverage-")
    ]
    assert coverage_entries
    for entry in coverage_entries:
        assert entry.get("blocking") is True, entry


def test_coverage_check_is_codebase_review_only():
    """coverage-* is a testing/quality concern → quality mode keeps it, security drops it."""
    parsed = rci.parse_checks_yml(_CHECKS_FRAGMENT)
    quality_ids = {c["id"] for c in rci.filter_checks(parsed, "quality")}
    security_ids = {c["id"] for c in rci.filter_checks(parsed, "security")}
    assert "coverage-diff-python" in quality_ids
    assert "coverage-diff-frontend" in quality_ids
    assert "coverage-diff-python" not in security_ids
    assert "coverage-diff-frontend" not in security_ids


def test_coverage_check_is_noop_in_grep_loop():
    """Pattern-less coverage entries must be a clean no-op when passed to run_check."""
    parsed = rci.parse_checks_yml(_CHECKS_FRAGMENT)
    for entry in parsed:
        if entry.get("id", "").startswith("coverage-"):
            assert rci.run_check(entry, os.getcwd()) == []


# ── Phase 61b — crown-jewel hard gate (baseline carve-out) ────────────────
#
# Test decision (Phase 61b / 58b discipline): these prove the *gate* contract
# on top of 61a's measurement contract — that a blocking coverage finding
# (1) fails --fail-on-blocking, (2) is never baseline-suppressed (no
# --update-baseline escape hatch, even with a matching baseline key), and
# (3) stays a pure measurement when the consumer keeps blocking: false; plus
# that the carve-out does NOT regress the normal baseline path for other
# checks. The diff-cover subprocess is mocked exactly as the parser tests do.

_GATE_CHECKS_YML = """\
checks:
  - id: coverage-diff-python
    name: "cov py"
    category: testing
    severity: medium
    critical_path: ["billing/"]
    report: "coverage.xml"
    description: "x"
    used_by: [codebase-review]
    blocking: true
"""


def _run_main(tmp_path, monkeypatch, extra_argv, *, blocking=True,
              baseline_lines=None):
    """Drive cli.main() over a one-coverage-check repo; return (exit_code).

    The non-coverage stages are patched to [] so only the real coverage stage
    runs (its diff-cover subprocess is mocked to the canned payload). --repo-root
    is passed so main() never shells out to git. Returns the SystemExit code
    (0 when main() returns without exiting).
    """
    claude = tmp_path / ".claude"
    claude.mkdir()
    yml = _GATE_CHECKS_YML
    if not blocking:
        yml = yml.replace("blocking: true", "blocking: false")
    (claude / "checks.yml").write_text(yml)
    (tmp_path / "coverage.xml").write_text("<coverage/>")
    if baseline_lines is not None:
        (claude / "checks_baseline.txt").write_text(
            "\n".join(baseline_lines) + "\n"
        )

    argv = ["run_checks", "--repo-root", str(tmp_path), "--mode", "both"]
    argv += extra_argv
    monkeypatch.setattr(sys, "argv", argv)

    code = 0
    with patch("run_checks_impl.subprocess.run") as mock_run, \
            patch("run_checks.cli._run_semgrep", return_value=[]), \
            patch("run_checks.cli._run_eslint", return_value=[]), \
            patch("run_checks.cli._run_pip_audit", return_value=[]):
        mock_run.return_value = _mock_completed(_canned_diff_cover())
        try:
            rci.main()
        except SystemExit as e:
            code = e.code if e.code is not None else 0
    return code


def test_gate_blocks_on_uncovered_critical_line(tmp_path, monkeypatch, capsys):
    """A blocking coverage gap fails --fail-on-blocking (exit 1) with coverage-correct guidance."""
    code = _run_main(tmp_path, monkeypatch, ["--fail-on-blocking"])
    out = capsys.readouterr()
    assert code == 1
    assert "billing/charge.py:12" in out.out
    assert "new blocking finding(s)" in out.err
    # The failure must steer away from the dead-end --update-baseline path.
    assert "NOT baselineable" in out.err
    assert "pragma" in out.err


def test_gate_passes_without_fail_flag(tmp_path, monkeypatch, capsys):
    """Without --fail-on-blocking the gate reports but never exits non-zero."""
    code = _run_main(tmp_path, monkeypatch, [])
    out = capsys.readouterr()
    assert code == 0
    assert "billing/charge.py:12" in out.out


def test_gate_ignores_matching_baseline(tmp_path, monkeypatch, capsys):
    """Coverage NEVER baseline-suppresses — a matching key still fails the gate."""
    baseline = [
        "coverage-diff-python|billing/charge.py:12",
        "coverage-diff-python|billing/charge.py:15",
    ]
    code = _run_main(
        tmp_path, monkeypatch, ["--fail-on-blocking"], baseline_lines=baseline
    )
    out = capsys.readouterr()
    assert code == 1
    # The finding is emitted live, NOT tagged [baseline].
    assert "[baseline]" not in out.out
    assert "billing/charge.py:12" in out.out


def test_measurement_only_does_not_block(tmp_path, monkeypatch, capsys):
    """blocking: false keeps coverage a pure measurement — exit 0 even with --fail-on-blocking."""
    code = _run_main(
        tmp_path, monkeypatch, ["--fail-on-blocking"], blocking=False
    )
    out = capsys.readouterr()
    assert code == 0
    assert "billing/charge.py:12" in out.out  # still reported


def test_update_baseline_never_writes_coverage(tmp_path, monkeypatch, capsys):
    """--update-baseline must not persist a coverage finding (diff-relative, un-acceptable)."""
    code = _run_main(tmp_path, monkeypatch, ["--update-baseline"])
    out = capsys.readouterr()
    assert code == 0
    written = (tmp_path / ".claude" / "checks_baseline.txt").read_text()
    assert "coverage-diff-python|" not in written
    # The printed tally must reflect what was actually written (0), not the
    # 2 coverage findings that were excluded.
    assert "Wrote 0 baseline finding(s)" in out.err


# ── is_baseline_suppressed / write_baseline unit tests ────────────────────


def test_is_baseline_suppressed_coverage_never_suppresses():
    """A coverage finding is never suppressed even when blocking + baselined."""
    key = rci.finding_key("coverage-diff-python", "billing/charge.py:12")
    assert rci.is_baseline_suppressed(
        "coverage-diff-python", "billing/charge.py:12",
        {"coverage-diff-python"}, {key},
    ) is False


def test_is_baseline_suppressed_normal_check_still_suppresses():
    """The carve-out doesn't regress the normal baseline path for other checks."""
    key = rci.finding_key("todo-vs-deferred", "app/x.py:3")
    assert rci.is_baseline_suppressed(
        "todo-vs-deferred", "app/x.py:3", {"todo-vs-deferred"}, {key},
    ) is True


def test_is_baseline_suppressed_requires_blocking_and_baseline():
    """A non-coverage finding suppresses only when blocking AND baselined."""
    key = rci.finding_key("todo-vs-deferred", "app/x.py:3")
    # Not in baseline → not suppressed.
    assert rci.is_baseline_suppressed(
        "todo-vs-deferred", "app/x.py:3", {"todo-vs-deferred"}, set()
    ) is False
    # Baselined but not a blocking check → not suppressed.
    assert rci.is_baseline_suppressed(
        "todo-vs-deferred", "app/x.py:3", set(), {key}
    ) is False


def test_write_baseline_excludes_coverage(tmp_path):
    """write_baseline persists blocking non-coverage findings but never coverage."""
    path = str(tmp_path / ".claude" / "checks_baseline.txt")
    findings = [
        ("todo-vs-deferred", "app/x.py:3", "msg a"),
        ("coverage-diff-python", "billing/charge.py:12", "msg b"),
    ]
    rci.write_baseline(path, findings, {"todo-vs-deferred", "coverage-diff-python"})
    text = open(path, encoding="utf-8").read()
    assert "todo-vs-deferred|app/x.py:3" in text
    assert "coverage-diff-python|" not in text


def test_is_coverage_predicate():
    """_is_coverage matches the coverage- prefix and nothing else."""
    assert rci._is_coverage("coverage-diff-python") is True
    assert rci._is_coverage("coverage-diff-frontend") is True
    assert rci._is_coverage("todo-vs-deferred") is False
    assert rci._is_coverage("pip-audit-vuln") is False
