"""Unit tests for the semgrep ingest stage (run_checks/semgrep.py), Phase 105.

The parser body had no coverage — the only prior reference stubs
`_run_semgrep` to return `[]` (test_run_checks_coverage.py), so the actual JSON
parse was never exercised even though it feeds `--fail-on-blocking`. These cover
the results parser (last-dotted-segment rule id, the deliberately-1-indexed line
— no +1, unlike pyright — and severity mapping), the `included_ids` filter, and
every graceful-skip path (empty ids / dir absent / binary missing / timeout /
non-JSON / empty).

Subprocess is mocked (`patch("run_checks.semgrep.subprocess.run")`); the
`.claude/semgrep/` dir is created first so the parse path is reached rather than
the dir-absent guard. Tool-absent is `FileNotFoundError`, not a return code.
"""
import json
import subprocess
from unittest.mock import patch

import run_checks.semgrep as semgrep


def _completed(stdout="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr="")


def _semgrep_dir(tmp_path):
    (tmp_path / ".claude" / "semgrep").mkdir(parents=True)
    return tmp_path


def _semgrep_json(tmp_path, *, check_id="rules.python.audit.dangerous-eval",
                  line=10, message="Detected eval", severity="ERROR"):
    return json.dumps({
        "results": [{
            "check_id": check_id,
            "path": str(tmp_path / "app" / "x.py"),
            "start": {"line": line},
            "extra": {"message": message, "severity": severity},
        }]
    })


class TestParser:
    def test_emits_finding_per_result(self, tmp_path):
        _semgrep_dir(tmp_path)
        with patch("run_checks.semgrep.subprocess.run",
                   return_value=_completed(_semgrep_json(tmp_path))):
            out = semgrep._run_semgrep(str(tmp_path), {"semgrep-dangerous-eval"})
        assert len(out) == 1
        check_id, file_line, msg = out[0]
        assert check_id == "semgrep-dangerous-eval"
        # semgrep line numbers are already 1-indexed — no offset applied.
        assert file_line == "app/x.py:10"
        assert "HIGH" in msg
        assert "Detected eval" in msg

    def test_takes_last_dotted_segment_of_rule_id(self, tmp_path):
        _semgrep_dir(tmp_path)
        with patch("run_checks.semgrep.subprocess.run",
                   return_value=_completed(
                       _semgrep_json(tmp_path, check_id="a.b.c.my-rule"))):
            out = semgrep._run_semgrep(str(tmp_path), {"semgrep-my-rule"})
        assert len(out) == 1
        assert out[0][0] == "semgrep-my-rule"

    def test_result_not_in_included_ids_dropped(self, tmp_path):
        _semgrep_dir(tmp_path)
        with patch("run_checks.semgrep.subprocess.run",
                   return_value=_completed(_semgrep_json(tmp_path))):
            out = semgrep._run_semgrep(str(tmp_path), {"semgrep-other"})
        assert out == []

    def test_severity_mapping_error_and_info(self, tmp_path):
        _semgrep_dir(tmp_path)
        payload = json.dumps({"results": [
            {"check_id": "x.hi", "path": str(tmp_path / "a.py"),
             "start": {"line": 1}, "extra": {"message": "e", "severity": "ERROR"}},
            {"check_id": "x.lo", "path": str(tmp_path / "b.py"),
             "start": {"line": 2}, "extra": {"message": "i", "severity": "INFO"}},
        ]})
        with patch("run_checks.semgrep.subprocess.run",
                   return_value=_completed(payload)):
            out = semgrep._run_semgrep(str(tmp_path), {"semgrep-hi", "semgrep-lo"})
        by_id = {c: m for c, _, m in out}
        assert "HIGH" in by_id["semgrep-hi"]
        assert "LOW" in by_id["semgrep-lo"]


class TestGracefulSkips:
    def test_empty_included_ids_returns_early(self, tmp_path):
        _semgrep_dir(tmp_path)
        with patch("run_checks.semgrep.subprocess.run") as mock_run:
            out = semgrep._run_semgrep(str(tmp_path), set())
        assert out == []
        assert mock_run.call_count == 0

    def test_skips_when_semgrep_dir_absent(self, tmp_path):
        # No .claude/semgrep/ created → feature not installed.
        with patch("run_checks.semgrep.subprocess.run") as mock_run:
            out = semgrep._run_semgrep(str(tmp_path), {"semgrep-dangerous-eval"})
        assert out == []
        assert mock_run.call_count == 0

    def test_binary_missing_skips_with_warning(self, tmp_path, capsys):
        _semgrep_dir(tmp_path)
        with patch("run_checks.semgrep.subprocess.run", side_effect=FileNotFoundError):
            out = semgrep._run_semgrep(str(tmp_path), {"semgrep-dangerous-eval"})
        assert out == []
        assert "semgrep not on PATH" in capsys.readouterr().err

    def test_timeout_skips_with_warning(self, tmp_path, capsys):
        _semgrep_dir(tmp_path)
        with patch("run_checks.semgrep.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("semgrep", 300)):
            out = semgrep._run_semgrep(str(tmp_path), {"semgrep-dangerous-eval"})
        assert out == []
        assert "timeout" in capsys.readouterr().err

    def test_non_json_output_skips_with_warning(self, tmp_path, capsys):
        _semgrep_dir(tmp_path)
        with patch("run_checks.semgrep.subprocess.run",
                   return_value=_completed("oops not json")):
            out = semgrep._run_semgrep(str(tmp_path), {"semgrep-dangerous-eval"})
        assert out == []
        assert "non-JSON" in capsys.readouterr().err

    def test_empty_stdout_returns_empty(self, tmp_path):
        _semgrep_dir(tmp_path)
        with patch("run_checks.semgrep.subprocess.run", return_value=_completed("")):
            out = semgrep._run_semgrep(str(tmp_path), {"semgrep-dangerous-eval"})
        assert out == []


# ── Phase 133: per-check paths: scoping (post-filter) ───────────────────────

class TestPathsScoping:
    """`_classify_checks` hands this stage id → check dict; when the check
    declares real `paths:`, findings outside them are dropped. Unlocalized
    `<placeholder>` entries contribute no scoping (the pre-133 whole-tree
    behavior — a fresh, never-substituted install must not go silently
    findings-free), and the `__disabled_no_op__` sentinel scopes the check to
    nothing (the overlay disable shape, now working for semgrep)."""

    def _run(self, tmp_path, included):
        _semgrep_dir(tmp_path)
        with patch("run_checks.semgrep.subprocess.run",
                   return_value=_completed(_semgrep_json(tmp_path))):
            return semgrep._run_semgrep(str(tmp_path), included)

    def test_in_scope_finding_kept(self, tmp_path):
        out = self._run(tmp_path, {
            "semgrep-dangerous-eval": {"id": "semgrep-dangerous-eval",
                                       "paths": ["app/"]}})
        assert len(out) == 1

    def test_out_of_scope_finding_dropped(self, tmp_path):
        out = self._run(tmp_path, {
            "semgrep-dangerous-eval": {"id": "semgrep-dangerous-eval",
                                       "paths": ["other/"]}})
        assert out == []

    def test_placeholder_paths_do_not_scope(self, tmp_path):
        out = self._run(tmp_path, {
            "semgrep-dangerous-eval": {"id": "semgrep-dangerous-eval",
                                       "paths": ["<api module>/"]}})
        assert len(out) == 1, "unlocalized placeholder must not disable the rule"

    def test_sentinel_disables_rule(self, tmp_path):
        out = self._run(tmp_path, {
            "semgrep-dangerous-eval": {"id": "semgrep-dangerous-eval",
                                       "paths": ["__disabled_no_op__"]}})
        assert out == []

    def test_legacy_id_set_still_accepted_unscoped(self, tmp_path):
        out = self._run(tmp_path, {"semgrep-dangerous-eval"})
        assert len(out) == 1

    def test_exclude_dir_drops_finding_under_matching_component(self, tmp_path):
        """Adversarial-review fix (2026-07-19): the docs recommend exclude_dir
        as a general narrowing mechanism, so the tool-shelling post-filter must
        honor it too — not just grep."""
        out = self._run(tmp_path, {
            "semgrep-dangerous-eval": {"id": "semgrep-dangerous-eval",
                                       "paths": [], "exclude_dir": ["app"]}})
        assert out == []

    def test_repo_root_dot_path_means_whole_tree(self, tmp_path):
        """Adversarial-review fix (2026-07-19): '.' / './' are valid whole-tree
        roots to the grep stage — the post-filter must not treat them as
        match-nothing (a natural substitution value for small repos)."""
        out = self._run(tmp_path, {
            "semgrep-dangerous-eval": {"id": "semgrep-dangerous-eval",
                                       "paths": ["."]}})
        assert len(out) == 1

    def test_dot_slash_prefixed_path_scopes_normally(self, tmp_path):
        out = self._run(tmp_path, {
            "semgrep-dangerous-eval": {"id": "semgrep-dangerous-eval",
                                       "paths": ["./app/"]}})
        assert len(out) == 1
