"""Phase 68 — run_checks package backport regression tests.

Locks in the four BR-monolith fixes ported into the ``run_checks/`` package
so a future change that re-introduces the old shapes fails CI:

  #1  PyYAML ``safe_load`` in ``config.parse_checks_yml`` — the crux. The
      old hand-rolled parser only understood inline ``["a", "b"]`` lists;
      block-style ``- item`` lists parsed to an empty string and silently
      disabled every grep check that used one. ``test_block_style_paths_*``
      is the regression that would fail if the hand-rolled parser returned.
  #2  ``_sanitize_log`` single-sourced from ``scripts/_log.py`` and applied
      at the package's exception-interpolation sites
      (``test_package_*_single_source``).
  #3  ``_classify_checks`` shared helper feeding both the ``--mode`` and
      ``--update-baseline`` paths, adapted to the package's six stages
      (``test_classify_*``).
  #4  grep ``rc >= 2`` surfaced as a warn rather than silently swallowed
      (``test_run_grep_*``).

Tests reach package internals through the ``run_checks_impl`` re-export shim,
matching the existing ``tests/test_run_checks.py`` convention. Subprocess is
patched via ``run_checks_impl.subprocess.run`` (the singleton module shared by
every submodule).
"""

import os
import subprocess
from unittest.mock import patch

import pytest

import _log
import run_checks.cli as cli_mod
import run_checks.grep as grep_mod
import run_checks.lint as lint_mod
import run_checks_impl as rci


_CORE_FRAGMENT = os.path.join(
    os.path.dirname(__file__), "..", "core", "companion", "checks.yml.fragment"
)


def _write_checks(tmp_path, body):
    p = tmp_path / "checks.yml"
    p.write_text(body, encoding="utf-8")
    return str(p)


# === Fix #1: block-style list parsing (the crux) ===========================


def test_block_style_paths_preserved(tmp_path):
    """A block-style `paths:` list round-trips as a Python list.

    The whole point: the old parser dropped these to "" and silently
    disabled the check.
    """
    path = _write_checks(tmp_path, """\
checks:
  - id: block-check
    severity: high
    paths:
      - src/api/
      - src/core/
    include:
      - "*.py"
    pattern: 'eval\\('
    description: "no eval"
    used_by:
      - codebase-review
""")
    checks = rci.parse_checks_yml(path)
    assert len(checks) == 1
    assert checks[0]["paths"] == ["src/api/", "src/core/"]
    assert checks[0]["include"] == ["*.py"]
    assert checks[0]["used_by"] == ["codebase-review"]


def test_inline_style_paths_still_work(tmp_path):
    """Inline `["a", "b"]` lists keep parsing (no regression for the old shape)."""
    path = _write_checks(tmp_path, """\
checks:
  - id: inline-check
    severity: low
    paths: ["src/utils/", "src/lib/"]
    pattern: 'TODO'
    description: "no todo"
    used_by: [codebase-review]
""")
    checks = rci.parse_checks_yml(path)
    assert checks[0]["paths"] == ["src/utils/", "src/lib/"]
    assert checks[0]["used_by"] == ["codebase-review"]


def test_block_and_inline_mixed_in_one_file(tmp_path):
    """Both shapes coexist — PyYAML handles each natively."""
    path = _write_checks(tmp_path, """\
checks:
  - id: block-one
    paths:
      - a/
    pattern: 'x'
    description: "d"
  - id: inline-one
    paths: ["b/"]
    pattern: 'y'
    description: "d"
""")
    checks = rci.parse_checks_yml(path)
    assert checks[0]["paths"] == ["a/"]
    assert checks[1]["paths"] == ["b/"]


def test_core_fragment_parses_under_pyyaml():
    """The real shipped core fragment parses cleanly via safe_load.

    Guards against a fragment edit that is valid under the loose hand-rolled
    parser but malformed YAML.
    """
    checks = rci.parse_checks_yml(_CORE_FRAGMENT)
    ids = {c["id"] for c in checks}
    # Sentinel ids known to live in the core fragment across stages.
    assert "todo-vs-deferred" in ids
    assert "lint-error" in ids
    assert "coverage-diff-python" in ids


# === Fix #1: stricter validation (the other half of the block-list fix) ====


def test_top_level_must_be_mapping(tmp_path):
    """A bare top-level list (no `checks:` key) raises rather than mis-parses."""
    path = _write_checks(tmp_path, "- id: stray\n  pattern: x\n")
    with pytest.raises(ValueError, match="must be a mapping"):
        rci.parse_checks_yml(path)


def test_checks_key_must_be_a_list(tmp_path):
    path = _write_checks(tmp_path, "checks: not-a-list\n")
    with pytest.raises(ValueError, match="'checks' must be a list"):
        rci.parse_checks_yml(path)


def test_missing_id_raises(tmp_path):
    path = _write_checks(tmp_path, "checks:\n  - pattern: x\n    description: d\n")
    with pytest.raises(ValueError, match="missing or empty 'id'"):
        rci.parse_checks_yml(path)


def test_list_field_as_scalar_raises(tmp_path):
    """A `paths:` that arrives as a scalar (e.g. misindentation collapsing a
    block list) noisy-fails instead of silently no-opping."""
    path = _write_checks(tmp_path, """\
checks:
  - id: bad-shape
    paths: src/api/
    pattern: x
    description: d
""")
    with pytest.raises(ValueError, match="field 'paths' must be a list"):
        rci.parse_checks_yml(path)


def test_malformed_yaml_raises_valueerror(tmp_path):
    """A YAML syntax error surfaces as a ValueError, not a raw YAMLError."""
    path = _write_checks(tmp_path, "checks:\n  - id: x\n   bad: indent\n")
    with pytest.raises(ValueError, match="YAML parse error"):
        rci.parse_checks_yml(path)


# === Fix #2: _sanitize_log single-sourced from scripts/_log.py =============


def test_package_uses_single_sourced_sanitize_log():
    """The package imports the one canonical helper, not a private copy."""
    assert grep_mod._sanitize_log is _log._sanitize_log
    assert lint_mod._sanitize_log is _log._sanitize_log
    assert cli_mod._sanitize_log is _log._sanitize_log


def test_sanitize_log_strips_control_chars():
    assert _log._sanitize_log("\x1b[31mboom\x1b[0m") == "boom"
    assert _log._sanitize_log("a\x07b\nc") == "ab c"


# === Fix #3: _classify_checks shared helper (six stages) ===================


_MIXED_CHECKS = [
    {"id": "grep-a", "used_by": ["codebase-review"]},
    {"id": "pyright-x", "used_by": ["codebase-review"], "blocking": True},
    {"id": "tsc-y", "used_by": ["codebase-review"]},
    {"id": "semgrep-z", "used_by": ["security-audit"]},
    {"id": "lint-error", "used_by": ["codebase-review"]},
    {"id": "pip-audit-vuln", "used_by": ["security-audit"], "blocking": True},
    {"id": "coverage-diff-python", "used_by": ["codebase-review"],
     "critical_path": ["src/"], "blocking": True},
    {"id": "grep-b", "used_by": ["security-audit"]},
]


def test_classify_buckets_by_prefix():
    (grep_checks, lsp_ids, semgrep_ids, lint_ids,
     pip_audit_ids, coverage_checks, _blocking_ids) = rci._classify_checks(
        _MIXED_CHECKS, active_token=None
    )
    assert {c["id"] for c in grep_checks} == {"grep-a", "grep-b"}
    # Phase 133: lsp/semgrep buckets are dicts of id → full check dict (the
    # tool-shelling stages post-filter findings by each check's paths:), so
    # compare membership on keys — set-like usage is the preserved contract.
    assert set(lsp_ids) == {"pyright-x", "tsc-y"}
    assert lsp_ids["pyright-x"]["id"] == "pyright-x"
    assert set(semgrep_ids) == {"semgrep-z"}
    assert semgrep_ids["semgrep-z"]["id"] == "semgrep-z"
    assert lint_ids == {"lint-error"}
    assert pip_audit_ids == {"pip-audit-vuln"}
    assert {c["id"] for c in coverage_checks} == {"coverage-diff-python"}


def test_classify_coverage_returns_full_dicts():
    """Coverage needs critical_path/report — the helper hands it dicts, not ids."""
    *_, coverage_checks, _ = rci._classify_checks(_MIXED_CHECKS, active_token=None)
    assert coverage_checks[0]["critical_path"] == ["src/"]


def test_classify_blocking_ids_across_all_buckets():
    *_, blocking_ids = rci._classify_checks(_MIXED_CHECKS, active_token=None)
    assert blocking_ids == {"pyright-x", "pip-audit-vuln", "coverage-diff-python"}


def test_classify_active_token_filters():
    """active_token excludes checks lacking the token; None accepts all."""
    res_quality = rci._classify_checks(_MIXED_CHECKS, active_token="codebase-review")
    grep_q = {c["id"] for c in res_quality[0]}
    assert grep_q == {"grep-a"}              # grep-b is security-only
    assert not res_quality[2]                # semgrep-z is security-only (empty dict)
    assert res_quality[4] == set()           # pip-audit-vuln is security-only
    # security-only pip-audit excluded → not in blocking_ids under quality
    assert "pip-audit-vuln" not in res_quality[-1]


def test_classify_missing_used_by_excluded_under_token():
    """A check with no used_by is excluded by a token filter, included by None."""
    checks = [{"id": "grep-x"}]  # no used_by
    assert rci._classify_checks(checks, active_token="codebase-review")[0] == []
    assert {c["id"] for c in rci._classify_checks(checks, active_token=None)[0]} == {"grep-x"}


# === Fix #4: grep rc >= 2 surfaced as a warn ===============================


def _fake_completed(returncode, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=["grep"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_run_grep_warns_on_rc_ge_2(tmp_path, capsys):
    """grep rc>=2 (a real error) prints a sanitized warn and returns []."""
    (tmp_path / "src").mkdir()
    with patch("run_checks_impl.subprocess.run",
               return_value=_fake_completed(2, stderr="grep: bad regex\x1b[0m")):
        out = rci.run_grep("(", ["src"], [], [], str(tmp_path))
    assert out == []
    err = capsys.readouterr().err
    assert "warn: grep failed (rc=2)" in err
    assert "\x1b" not in err  # sanitized


def test_run_grep_rc_1_is_silent(tmp_path, capsys):
    """grep rc=1 (no match — the normal case) does NOT warn."""
    (tmp_path / "src").mkdir()
    with patch("run_checks_impl.subprocess.run",
               return_value=_fake_completed(1, stdout="")):
        out = rci.run_grep("x", ["src"], [], [], str(tmp_path))
    assert out == []
    assert "warn: grep failed" not in capsys.readouterr().err


def test_run_grep_rc_0_returns_matches(tmp_path):
    """grep rc=0 returns the matched lines unchanged."""
    (tmp_path / "src").mkdir()
    with patch("run_checks_impl.subprocess.run",
               return_value=_fake_completed(0, stdout="src/a.py:3:hit\n")):
        out = rci.run_grep("hit", ["src"], [], [], str(tmp_path))
    assert out == ["src/a.py:3:hit"]
