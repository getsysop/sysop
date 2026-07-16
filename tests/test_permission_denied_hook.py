"""Tests for ``core/companion/scripts/permission_denied_hook.py``.

Sysop-original — Phase 36 (Claude Code 2.1.89 PermissionDenied hook).
No gdp counterpart; all tests in this file are Phase 48 originals.

Surface covered:

- ``_strip_cd_prefix`` — skill-generated ``cd <path> &&`` / ``; `` prefixes
  must drop cleanly so downstream matchers can read the raw command.
- ``_match_protected_push`` — push to ``main``/``master`` produces guidance
  containing the documented `!`-escape command; venv hint appears only when
  a ``.venv`` exists in the resolved repo root.
- ``_match_destructive_push`` — ``--delete`` produces guidance + venv hint.
- ``_match_protected_commit`` — git commit on a protected branch produces
  the heredoc-vs-multi-`-m` guidance; off-branch commits do not match.
- ``main`` end-to-end on stdin — non-Bash tool inputs are silent; matched
  patterns emit a single JSON line with ``hookEventName: PermissionDenied``.
"""

from __future__ import annotations

import io
import json
import subprocess
from unittest import mock

import permission_denied_hook as pdh


# === _strip_cd_prefix ======================================================


def test_strip_cd_prefix_removes_amp_form():
    assert pdh._strip_cd_prefix("cd /repo && git push origin main") == "git push origin main"


def test_strip_cd_prefix_removes_semicolon_form():
    assert pdh._strip_cd_prefix("cd /repo; git push origin main") == "git push origin main"


def test_strip_cd_prefix_passthrough_when_no_cd():
    assert pdh._strip_cd_prefix("git push origin main") == "git push origin main"


def test_strip_cd_prefix_only_drops_leading_cd():
    """Inner ``&& cd …`` must NOT be stripped."""
    assert (
        pdh._strip_cd_prefix("git status && cd /tmp")
        == "git status && cd /tmp"
    )


# === _match_protected_push =================================================


def test_match_protected_push_returns_guidance_for_main(tmp_path):
    """No venv → no venv hint section in returned guidance."""
    ctx = pdh._match_protected_push("git push origin main", str(tmp_path))
    assert ctx is not None
    assert "! git push origin main" in ctx
    assert "protected-branch policy" in ctx
    # No venv → no venv hint
    assert "PATH=.venv/bin:$PATH" not in ctx


def test_match_protected_push_returns_guidance_for_master(tmp_path):
    ctx = pdh._match_protected_push("git push origin master", str(tmp_path))
    assert ctx is not None
    assert "! git push origin master" in ctx


def test_match_protected_push_includes_venv_hint_when_dot_venv_exists(tmp_path):
    (tmp_path / ".venv").mkdir()
    with mock.patch.object(pdh, "_main_repo_root", return_value=str(tmp_path)):
        ctx = pdh._match_protected_push("git push origin main", str(tmp_path))
    assert ctx is not None
    assert "PATH=.venv/bin:$PATH git push origin main" in ctx


def test_match_protected_push_accepts_dash_u_flag(tmp_path):
    ctx = pdh._match_protected_push("git push -u origin main", str(tmp_path))
    assert ctx is not None
    assert "git push origin main" in ctx


def test_match_protected_push_returns_none_for_feature_branch(tmp_path):
    assert pdh._match_protected_push("git push origin feat/0001", str(tmp_path)) is None


def test_match_protected_push_returns_none_for_non_push(tmp_path):
    assert pdh._match_protected_push("git status", str(tmp_path)) is None


# === _match_destructive_push ===============================================


def test_match_destructive_push_returns_guidance_for_delete(tmp_path):
    ctx = pdh._match_destructive_push(
        "git push origin --delete feat/old", str(tmp_path)
    )
    assert ctx is not None
    assert "destructive-flag protection" in ctx
    assert "! git push origin --delete feat/old" in ctx
    # Local cleanup hint mentioned
    assert "git branch -d feat/old" in ctx


def test_match_destructive_push_returns_none_for_non_delete(tmp_path):
    assert pdh._match_destructive_push("git push origin main", str(tmp_path)) is None


def test_match_destructive_push_includes_venv_hint_when_dot_venv_exists(tmp_path):
    (tmp_path / ".venv").mkdir()
    with mock.patch.object(pdh, "_main_repo_root", return_value=str(tmp_path)):
        ctx = pdh._match_destructive_push(
            "git push origin --delete feat/old", str(tmp_path)
        )
    assert ctx is not None
    assert "PATH=.venv/bin:$PATH git push origin --delete feat/old" in ctx


# === _match_protected_commit ===============================================


def test_match_protected_commit_returns_guidance_when_on_main(tmp_path):
    with mock.patch.object(pdh, "_current_branch", return_value="main"):
        ctx = pdh._match_protected_commit(
            'git commit -m "docs: x"', str(tmp_path)
        )
    assert ctx is not None
    assert "`git commit` on `main`" in ctx
    assert "Use multiple `-m` flags rather than a heredoc" in ctx
    # Quotes the original command
    assert '! git commit -m "docs: x"' in ctx


def test_match_protected_commit_returns_guidance_when_on_master(tmp_path):
    with mock.patch.object(pdh, "_current_branch", return_value="master"):
        ctx = pdh._match_protected_commit("git commit -m 'x'", str(tmp_path))
    assert ctx is not None
    assert "`git commit` on `master`" in ctx


def test_match_protected_commit_returns_none_when_off_protected_branch(tmp_path):
    with mock.patch.object(pdh, "_current_branch", return_value="feat/123"):
        assert pdh._match_protected_commit(
            'git commit -m "x"', str(tmp_path)
        ) is None


def test_match_protected_commit_returns_none_for_non_commit(tmp_path):
    with mock.patch.object(pdh, "_current_branch", return_value="main"):
        assert pdh._match_protected_commit("git status", str(tmp_path)) is None


def test_match_protected_commit_returns_none_when_branch_lookup_fails(tmp_path):
    """If the branch can't be resolved (detached HEAD / git missing), do not
    match — silent passthrough is safer than a false-positive escape hint."""
    with mock.patch.object(pdh, "_current_branch", return_value=""):
        assert pdh._match_protected_commit(
            'git commit -m "x"', str(tmp_path)
        ) is None


# === _has_venv =============================================================


def test_has_venv_true_when_dotvenv_dir_exists(tmp_path):
    (tmp_path / ".venv").mkdir()
    with mock.patch.object(pdh, "_main_repo_root", return_value=str(tmp_path)):
        assert pdh._has_venv(str(tmp_path)) is True


def test_has_venv_false_when_dotvenv_missing(tmp_path):
    with mock.patch.object(pdh, "_main_repo_root", return_value=str(tmp_path)):
        assert pdh._has_venv(str(tmp_path)) is False


# === _current_branch =======================================================


def test_current_branch_returns_stripped_stdout(tmp_path):
    fake = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="feat/0001\n", stderr="",
    )
    with mock.patch.object(pdh.subprocess, "run", return_value=fake):
        assert pdh._current_branch(str(tmp_path)) == "feat/0001"


def test_current_branch_returns_empty_on_failure(tmp_path):
    with mock.patch.object(
        pdh.subprocess, "run", side_effect=FileNotFoundError("git missing"),
    ):
        assert pdh._current_branch(str(tmp_path)) == ""


# === main() — integration ==================================================


def _run_main_with_stdin(monkeypatch, payload) -> tuple[int, str]:
    out = io.StringIO()
    text = json.dumps(payload) if isinstance(payload, dict) else payload
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    monkeypatch.setattr("sys.stdout", out)
    rc = pdh.main()
    return rc, out.getvalue()


def test_main_emits_guidance_for_protected_push(monkeypatch, tmp_path):
    rc, output = _run_main_with_stdin(monkeypatch, {
        "tool_name": "Bash",
        "tool_input": {"command": "git push origin main"},
        "cwd": str(tmp_path),
    })
    assert rc == 0
    assert output.strip()
    payload = json.loads(output)
    assert payload["hookSpecificOutput"]["hookEventName"] == "PermissionDenied"
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert "! git push origin main" in ctx


def test_main_silent_for_non_bash_tool(monkeypatch, tmp_path):
    rc, output = _run_main_with_stdin(monkeypatch, {
        "tool_name": "Read",
        "tool_input": {"file_path": "/tmp/x"},
        "cwd": str(tmp_path),
    })
    assert rc == 0
    assert output == ""


def test_main_silent_for_unmatched_bash_command(monkeypatch, tmp_path):
    """Unrelated Bash denials must not produce hook output (Phase 36 contract)."""
    rc, output = _run_main_with_stdin(monkeypatch, {
        "tool_name": "Bash",
        "tool_input": {"command": "rm -rf /tmp/foo"},
        "cwd": str(tmp_path),
    })
    assert rc == 0
    assert output == ""


def test_main_silent_on_empty_stdin(monkeypatch, tmp_path):
    rc, output = _run_main_with_stdin(monkeypatch, "")
    assert rc == 0
    assert output == ""


def test_main_silent_on_malformed_json(monkeypatch, tmp_path):
    rc, output = _run_main_with_stdin(monkeypatch, "not json {")
    assert rc == 0
    assert output == ""


def test_main_strips_cd_prefix_before_matching(monkeypatch, tmp_path):
    """A skill-generated ``cd /repo && git push origin main`` must still match."""
    rc, output = _run_main_with_stdin(monkeypatch, {
        "tool_name": "Bash",
        "tool_input": {"command": "cd /repo && git push origin main"},
        "cwd": str(tmp_path),
    })
    assert rc == 0
    payload = json.loads(output)
    assert "! git push origin main" in payload["hookSpecificOutput"]["additionalContext"]
