"""Tests for ``core/companion/scripts/parse_subagent_envelope.py``.

Sysop-original — Phase 37 (Claude Code SubagentStop hook; `last_assistant_message` added in 2.1.47).
No gdp counterpart; all tests in this file are Phase 48 originals.

Surface covered:

- ``_find_envelope_block`` — fence parser + multi-envelope last-wins rule.
- ``_find_review_report_block`` — reviewer-executor REVIEW_REPORT capture.
- ``_extract_field`` — ``none`` sentinel → None contract.
- ``_parse_envelope`` — whole-envelope field round-trip.
- ``_sanitize_for_filename`` — filename safety + fallback.
- ``_main_repo_root`` — worktree-aware git-common-dir resolution.
- ``main`` — end-to-end JSON write at the documented path; unparseable
  diagnostic file on no-envelope / bad TASK shape; exit 0 on empty / bad
  stdin (never blocks the parent).
- ``_last_assistant_message_from_transcript`` — Phase 54 JSONL fallback
  for harnesses providing ``agent_transcript_path`` (2.0.42+) but not
  ``last_assistant_message`` (2.1.47+); ``message_source`` provenance
  field in all written payloads.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

import parse_subagent_envelope as pse


# === _find_envelope_block ==================================================


def test_find_envelope_block_single_yaml_fence():
    text = (
        "Some prose.\n"
        "```yaml\n"
        "TASK: FEAT-0001\n"
        "STATUS: EXECUTED\n"
        "WORKTREE: /tmp/wt\n"
        "BRANCH: feat/0001\n"
        "```\n"
    )
    block = pse._find_envelope_block(text)
    assert block is not None
    assert "TASK: FEAT-0001" in block
    assert "STATUS: EXECUTED" in block


def test_find_envelope_block_last_wins_on_multiple():
    """Per the docstring: multiple envelopes → LAST wins."""
    text = (
        "```yaml\n"
        "TASK: FEAT-0001\n"
        "STATUS: BLOCKED\n"
        "```\n"
        "Some interleaved prose.\n"
        "```yaml\n"
        "TASK: FEAT-0002\n"
        "STATUS: EXECUTED\n"
        "```\n"
    )
    block = pse._find_envelope_block(text)
    assert block is not None
    assert "TASK: FEAT-0002" in block
    assert "FEAT-0001" not in block


def test_find_envelope_block_returns_none_when_no_fenced_match():
    text = "Just prose. No fences. TASK: FEAT-0001 STATUS: EXECUTED on one line."
    assert pse._find_envelope_block(text) is None


def test_find_envelope_block_ignores_review_report_only_block():
    """A fenced block carrying REVIEW_REPORT but no TASK+STATUS must not match."""
    text = (
        "```yaml\n"
        "REVIEW_REPORT:\n"
        "  verdict: approve\n"
        "  notes: looks good\n"
        "```\n"
    )
    assert pse._find_envelope_block(text) is None


def test_find_envelope_block_accepts_bare_fence():
    """Docstring: agents occasionally emit envelope under a bare ``` fence."""
    text = (
        "```\n"
        "TASK: BUG-0007\n"
        "STATUS: FAILED\n"
        "ERROR: something broke\n"
        "```\n"
    )
    block = pse._find_envelope_block(text)
    assert block is not None
    assert "BUG-0007" in block


# === _find_review_report_block =============================================


def test_find_review_report_block_returns_first_matching_block():
    text = (
        "```yaml\n"
        "REVIEW_REPORT:\n"
        "  verdict: approve\n"
        "```\n"
        "```yaml\n"
        "TASK: FEAT-0001\n"
        "STATUS: EXECUTED\n"
        "```\n"
    )
    rr = pse._find_review_report_block(text)
    assert rr is not None
    assert "REVIEW_REPORT" in rr
    assert "verdict: approve" in rr


# === _extract_field ========================================================


def test_extract_field_treats_none_sentinel_as_null():
    """Documented ``none`` sentinel → Python ``None``."""
    block = "TASK: FEAT-0001\nSTATUS: EXECUTED\nERROR: none\n"
    assert pse._extract_field(block, "ERROR") is None
    # Case-insensitive
    block2 = "TASK: FEAT-0001\nERROR: None\n"
    assert pse._extract_field(block2, "ERROR") is None


def test_extract_field_returns_value_verbatim():
    block = "TASK: FEAT-0042\nWORKTREE: /tmp/my worktree\n"
    assert pse._extract_field(block, "WORKTREE") == "/tmp/my worktree"


def test_extract_field_missing_returns_none():
    block = "TASK: FEAT-0001\nSTATUS: EXECUTED\n"
    assert pse._extract_field(block, "BRANCH") is None


# === _parse_envelope =======================================================


def test_parse_envelope_returns_all_documented_fields_lowercased():
    text = (
        "```yaml\n"
        "TASK: FEAT-0010\n"
        "STATUS: BLOCKED\n"
        "WORKTREE: /tmp/wt\n"
        "BRANCH: feat/0010\n"
        "BLOCKER_QUESTION: which database?\n"
        "PARKED_REASON: none\n"
        "ERROR: none\n"
        "```\n"
    )
    parsed = pse._parse_envelope(text)
    assert parsed is not None
    assert parsed["task"] == "FEAT-0010"
    assert parsed["status"] == "BLOCKED"
    assert parsed["worktree"] == "/tmp/wt"
    assert parsed["branch"] == "feat/0010"
    assert parsed["blocker_question"] == "which database?"
    assert parsed["parked_reason"] is None
    assert parsed["error"] is None
    assert "_raw_block" in parsed


def test_parse_envelope_no_block_returns_none():
    assert pse._parse_envelope("nothing fenced here") is None


# === _sanitize_for_filename ================================================


def test_sanitize_for_filename_replaces_unsafe_chars():
    assert pse._sanitize_for_filename("FEAT-0001", "fb") == "FEAT-0001"
    assert pse._sanitize_for_filename("../etc/passwd", "fb") == "etc_passwd"
    assert pse._sanitize_for_filename("a/b\\c d", "fb") == "a_b_c_d"


def test_sanitize_for_filename_empty_or_all_unsafe_uses_fallback():
    assert pse._sanitize_for_filename("", "fallback") == "fallback"
    # All chars get stripped → fallback
    assert pse._sanitize_for_filename("...", "fallback") == "fallback"
    assert pse._sanitize_for_filename("/", "fallback") == "fallback"


# === _main_repo_root =======================================================


def test_main_repo_root_falls_back_to_cwd_when_git_fails(tmp_path):
    with mock.patch.object(
        pse.subprocess, "run",
        side_effect=FileNotFoundError("git not found"),
    ):
        assert pse._main_repo_root(str(tmp_path)) == str(tmp_path)


def test_main_repo_root_falls_back_to_cwd_on_nonzero_exit(tmp_path):
    fake = subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr="")
    with mock.patch.object(pse.subprocess, "run", return_value=fake):
        assert pse._main_repo_root(str(tmp_path)) == str(tmp_path)


def test_main_repo_root_strips_trailing_git_dir(tmp_path):
    """When git-common-dir is the path's ``.git`` child, return the parent."""
    fake = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=str(tmp_path / ".git") + "\n", stderr="",
    )
    with mock.patch.object(pse.subprocess, "run", return_value=fake):
        assert pse._main_repo_root(str(tmp_path)) == str(tmp_path)


def test_main_repo_root_resolves_relative_common_dir(tmp_path):
    """When git returns a relative path, helper realpaths it under cwd."""
    fake = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="../main/.git\n", stderr="",
    )
    main_root = tmp_path / "main"
    main_root.mkdir()
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    with mock.patch.object(pse.subprocess, "run", return_value=fake):
        resolved = pse._main_repo_root(str(worktree))
    assert resolved == str(main_root)


# === main() — integration ==================================================


def _run_main_with_stdin(monkeypatch, payload: str | dict) -> int:
    import io
    text = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    return pse.main()


def test_main_writes_envelope_json_for_valid_input(monkeypatch, tmp_path):
    """End-to-end: well-formed envelope → ``<repo>/.subagent-envelopes/<TASK>.json``."""
    last = (
        "```yaml\n"
        "TASK: FEAT-0123\n"
        "STATUS: EXECUTED\n"
        "WORKTREE: /tmp/wt-feat-0123\n"
        "BRANCH: feat/0123\n"
        "ERROR: none\n"
        "BLOCKER_QUESTION: none\n"
        "PARKED_REASON: none\n"
        "```\n"
    )
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, {
        "last_assistant_message": last,
        "session_id": "sess-1",
        "agent_id": "agent-1",
        "agent_transcript_path": "/tmp/x.jsonl",
        "cwd": str(tmp_path),
    })
    assert rc == 0
    out = tmp_path / pse.ENVELOPES_DIR / "FEAT-0123.json"
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["parsed"] is True
    assert payload["task_id"] == "FEAT-0123"
    assert payload["status"] == "EXECUTED"
    assert payload["worktree"] == "/tmp/wt-feat-0123"
    assert payload["branch"] == "feat/0123"
    assert payload["error"] is None
    assert payload["session_id"] == "sess-1"
    assert payload["agent_id"] == "agent-1"


def test_main_writes_unparseable_diag_when_no_envelope(monkeypatch, tmp_path):
    """No fenced TASK+STATUS block → diagnostic file, exit 0."""
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, {
        "last_assistant_message": "I finished. No envelope here.",
        "session_id": "sess-x",
        "agent_id": "agent-x",
        "cwd": str(tmp_path),
    })
    assert rc == 0
    diag_files = list((tmp_path / pse.ENVELOPES_DIR).glob("_unparseable_*.json"))
    assert len(diag_files) == 1
    diag = json.loads(diag_files[0].read_text(encoding="utf-8"))
    assert diag["parsed"] is False
    assert diag["session_id"] == "sess-x"
    assert diag["agent_id"] == "agent-x"


def test_main_writes_unparseable_diag_on_bad_task_shape(monkeypatch, tmp_path):
    """Envelope parsed but TASK fails the <PREFIX>-<ID> regex → diagnostic file."""
    last = (
        "```yaml\n"
        "TASK: not a real id\n"
        "STATUS: EXECUTED\n"
        "WORKTREE: /tmp\n"
        "BRANCH: x\n"
        "```\n"
    )
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, {
        "last_assistant_message": last,
        "session_id": "sess-y",
        "agent_id": "agent-y",
        "cwd": str(tmp_path),
    })
    assert rc == 0
    diag_files = list((tmp_path / pse.ENVELOPES_DIR).glob("_unparseable_*.json"))
    assert len(diag_files) == 1
    diag = json.loads(diag_files[0].read_text(encoding="utf-8"))
    assert diag["parsed"] is True
    assert diag["task_id_valid"] is False
    # Normal envelope file should NOT have landed
    assert not list((tmp_path / pse.ENVELOPES_DIR).glob("not*.json"))


def test_main_returns_zero_on_empty_stdin(monkeypatch, tmp_path):
    """Hook never blocks: empty stdin → exit 0, no file written."""
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, "")
    assert rc == 0
    assert not (tmp_path / pse.ENVELOPES_DIR).exists()


def test_main_returns_zero_on_malformed_json_stdin(monkeypatch, tmp_path):
    """Hook never blocks: garbage stdin → exit 0, no file written."""
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, "this is not json {")
    assert rc == 0
    assert not (tmp_path / pse.ENVELOPES_DIR).exists()


def test_main_returns_zero_when_last_assistant_message_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, {"session_id": "s", "agent_id": "a"})
    assert rc == 0
    assert not (tmp_path / pse.ENVELOPES_DIR).exists()


def test_main_records_hook_input_as_message_source(monkeypatch, tmp_path):
    """Payload carries ``message_source: hook_input`` on the primary path."""
    last = "```yaml\nTASK: FEAT-0200\nSTATUS: EXECUTED\n```\n"
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, {
        "last_assistant_message": last,
        "session_id": "s",
        "agent_id": "a",
        "cwd": str(tmp_path),
    })
    assert rc == 0
    payload = json.loads(
        (tmp_path / pse.ENVELOPES_DIR / "FEAT-0200.json").read_text(encoding="utf-8")
    )
    assert payload["message_source"] == "hook_input"


# === _last_assistant_message_from_transcript ===============================


def _write_transcript(path: Path, entries: list) -> None:
    path.write_text(
        "\n".join(json.dumps(e) if not isinstance(e, str) else e for e in entries)
        + "\n",
        encoding="utf-8",
    )


def test_transcript_helper_returns_last_assistant_text(tmp_path):
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, [
        {"type": "user", "message": {"content": "do the task"}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "working on it"},
        ]}},
        {"type": "assistant", "message": {"content": [
            {"type": "thinking", "thinking": "internal"},
            {"type": "text", "text": "final answer"},
        ]}},
    ])
    assert pse._last_assistant_message_from_transcript(str(transcript)) == "final answer"


def test_transcript_helper_accepts_string_content(tmp_path):
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, [
        {"type": "assistant", "message": {"content": "plain string body"}},
    ])
    assert (
        pse._last_assistant_message_from_transcript(str(transcript))
        == "plain string body"
    )


def test_transcript_helper_tolerates_garbage_lines_and_shapes(tmp_path):
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, [
        "not json at all {",
        {"type": "assistant"},                       # no message
        {"type": "assistant", "message": "string"},  # message not a dict
        {"type": "assistant", "message": {"content": 42}},  # content wrong type
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "survivor"},
        ]}},
    ])
    assert pse._last_assistant_message_from_transcript(str(transcript)) == "survivor"


def test_transcript_helper_returns_empty_on_missing_file_or_empty_path(tmp_path):
    assert pse._last_assistant_message_from_transcript("") == ""
    assert pse._last_assistant_message_from_transcript(
        str(tmp_path / "does-not-exist.jsonl")
    ) == ""


# === main() — transcript fallback (Phase 54) ===============================


def test_main_falls_back_to_agent_transcript_when_field_absent(monkeypatch, tmp_path):
    """No ``last_assistant_message`` + readable transcript → envelope parsed
    from the transcript, ``message_source: agent_transcript``."""
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, [
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": (
                "Done.\n"
                "```yaml\n"
                "TASK: FEAT-0300\n"
                "STATUS: EXECUTED\n"
                "WORKTREE: /tmp/wt\n"
                "BRANCH: feat/0300\n"
                "```\n"
            )},
        ]}},
    ])
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, {
        "session_id": "s",
        "agent_id": "a",
        "agent_transcript_path": str(transcript),
        "cwd": str(tmp_path),
    })
    assert rc == 0
    payload = json.loads(
        (tmp_path / pse.ENVELOPES_DIR / "FEAT-0300.json").read_text(encoding="utf-8")
    )
    assert payload["task_id"] == "FEAT-0300"
    assert payload["status"] == "EXECUTED"
    assert payload["message_source"] == "agent_transcript"


def test_main_prefers_hook_input_over_transcript(monkeypatch, tmp_path):
    """Both sources present → hook input wins (transcript not consulted)."""
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, [
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "```yaml\nTASK: FEAT-0998\nSTATUS: FAILED\n```"},
        ]}},
    ])
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, {
        "last_assistant_message": "```yaml\nTASK: FEAT-0999\nSTATUS: EXECUTED\n```",
        "session_id": "s",
        "agent_id": "a",
        "agent_transcript_path": str(transcript),
        "cwd": str(tmp_path),
    })
    assert rc == 0
    out_dir = tmp_path / pse.ENVELOPES_DIR
    assert (out_dir / "FEAT-0999.json").exists()
    assert not (out_dir / "FEAT-0998.json").exists()
    payload = json.loads((out_dir / "FEAT-0999.json").read_text(encoding="utf-8"))
    assert payload["message_source"] == "hook_input"


def test_main_returns_zero_when_transcript_unreadable(monkeypatch, tmp_path):
    """No field + missing transcript → exit 0, no file (parent regex fallback)."""
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, {
        "session_id": "s",
        "agent_id": "a",
        "agent_transcript_path": str(tmp_path / "gone.jsonl"),
        "cwd": str(tmp_path),
    })
    assert rc == 0
    assert not (tmp_path / pse.ENVELOPES_DIR).exists()
