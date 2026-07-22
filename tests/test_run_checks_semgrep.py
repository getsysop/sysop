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
import sys
import types
from unittest.mock import patch

import run_checks.semgrep as semgrep
from run_checks.accounting import FAILED, RunReport


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


# ── Phase 135 follow-up: SSL_CERT_FILE trust-anchor resolution ──────────────
#
# Deliverable 03 (codex-sysop-integration) proved semgrep's OCaml core crashes
# at startup ("ca-certs: empty trust anchors") where no trust store is
# discoverable, that every telemetry-disable flag (OTEL_SDK_DISABLED included)
# fails to prevent it, and that pointing SSL_CERT_FILE at an existing bundle
# fixes it without weakening TLS. These lock the resolution order and the three
# env behaviors the follow-up added; each fails if its branch is removed.


class TestResolveCaBundle:
    """Resolution order — the failure class the adversarial pass targets: a
    wrong bundle path silently changing TLS behavior for the subprocess."""

    def test_prefers_first_existing_system_bundle(self, tmp_path, monkeypatch):
        missing = tmp_path / "nope.pem"
        present = tmp_path / "real-bundle.pem"
        present.write_text("-----BEGIN CERTIFICATE-----\n")
        # First entry does not exist → the resolver must skip it and take the
        # first path that is actually a file, never a nonexistent earlier one.
        monkeypatch.setattr(semgrep, "_SYSTEM_CA_BUNDLES",
                            (str(missing), str(present)))
        assert semgrep._resolve_ca_bundle() == str(present)

    def test_falls_back_to_certifi_when_no_system_bundle(self, tmp_path, monkeypatch):
        monkeypatch.setattr(semgrep, "_SYSTEM_CA_BUNDLES", ())
        bundle = tmp_path / "certifi-cacert.pem"
        bundle.write_text("x")
        fake = types.ModuleType("certifi")
        setattr(fake, "where", lambda: str(bundle))
        monkeypatch.setitem(sys.modules, "certifi", fake)
        assert semgrep._resolve_ca_bundle() == str(bundle)

    def test_certifi_path_that_does_not_exist_is_rejected(self, tmp_path, monkeypatch):
        """certifi.where() pointing at a missing file must not be handed on as a
        trust anchor — a nonexistent SSL_CERT_FILE would itself crash the core."""
        monkeypatch.setattr(semgrep, "_SYSTEM_CA_BUNDLES", ())
        fake = types.ModuleType("certifi")
        setattr(fake, "where", lambda: str(tmp_path / "gone.pem"))
        monkeypatch.setitem(sys.modules, "certifi", fake)
        assert semgrep._resolve_ca_bundle() is None

    def test_returns_none_when_no_bundle_anywhere(self, monkeypatch):
        monkeypatch.setattr(semgrep, "_SYSTEM_CA_BUNDLES", ())
        # sys.modules[name] = None makes `import name` raise ImportError.
        monkeypatch.setitem(sys.modules, "certifi", None)
        assert semgrep._resolve_ca_bundle() is None

    def test_broken_certifi_where_raises_returns_none(self, monkeypatch):
        """Adversarial-review fix (2026-07-20): a certifi that imports but whose
        `.where()` raises (broken/partial install, or a shadowing module) must
        degrade to None, never propagate — this fallback is load-bearing in the
        trust-store-less sandbox the feature exists to protect."""
        monkeypatch.setattr(semgrep, "_SYSTEM_CA_BUNDLES", ())
        fake = types.ModuleType("certifi")

        def _boom():
            raise RuntimeError("broken certifi")

        setattr(fake, "where", _boom)
        monkeypatch.setitem(sys.modules, "certifi", fake)
        assert semgrep._resolve_ca_bundle() is None


class TestTrustAnchorEnv:
    """The three mutation-verified env behaviors (house norm: each fails when its
    branch is removed): set-when-absent-and-found, never-overridden-when-present,
    hint-on-no-bundle."""

    def _capture_env(self, tmp_path, resolve_return):
        _semgrep_dir(tmp_path)
        with patch.object(semgrep, "_resolve_ca_bundle", return_value=resolve_return), \
             patch("run_checks.semgrep.subprocess.run",
                   return_value=_completed(
                       json.dumps({"results": [], "errors": []}))) as m:
            semgrep._run_semgrep(str(tmp_path), {"semgrep-x": {"id": "semgrep-x"}})
        return m.call_args.kwargs["env"]

    def test_ssl_cert_file_set_when_absent_and_bundle_found(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        env = self._capture_env(tmp_path, "/found/ca-bundle.pem")
        assert env["SSL_CERT_FILE"] == "/found/ca-bundle.pem"

    def test_ssl_cert_file_never_overridden_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SSL_CERT_FILE", "/operator/chosen.pem")
        # The resolver returns a *different* path; the unset-guard must keep the
        # operator's value, so removing the guard flips this assertion.
        env = self._capture_env(tmp_path, "/resolver/other.pem")
        assert env["SSL_CERT_FILE"] == "/operator/chosen.pem"

    def test_no_otel_sdk_disabled_env_var(self, tmp_path, monkeypatch):
        """Deliverable 03 disproved OTEL_SDK_DISABLED — the removed speculative
        var must not creep back into the subprocess env."""
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
        env = self._capture_env(tmp_path, "/found/ca-bundle.pem")
        assert "OTEL_SDK_DISABLED" not in env

    def test_hint_on_failed_line_when_no_bundle(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        _semgrep_dir(tmp_path)
        r = RunReport([{"id": "semgrep-x"}])
        with patch.object(semgrep, "_resolve_ca_bundle", return_value=None), \
             patch("run_checks.semgrep.subprocess.run",
                   return_value=_completed("", returncode=2)):
            semgrep._run_semgrep(
                str(tmp_path), {"semgrep-x": {"id": "semgrep-x"}}, r)
        assert r.status_of("semgrep-x") == FAILED
        hint = "set SSL_CERT_FILE to a trusted CA bundle"
        assert hint in r._records["semgrep-x"].detail
        assert hint in capsys.readouterr().err

    def test_no_hint_when_bundle_resolves(self, tmp_path, monkeypatch):
        """Mutation companion: the hint is conditional. A resolved bundle means
        an unrelated later crash carries no misleading remediation nag."""
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        _semgrep_dir(tmp_path)
        r = RunReport([{"id": "semgrep-x"}])
        with patch.object(semgrep, "_resolve_ca_bundle", return_value="/found/ca.pem"), \
             patch("run_checks.semgrep.subprocess.run",
                   return_value=_completed("", returncode=2)):
            semgrep._run_semgrep(
                str(tmp_path), {"semgrep-x": {"id": "semgrep-x"}}, r)
        assert "set SSL_CERT_FILE" not in r._records["semgrep-x"].detail
