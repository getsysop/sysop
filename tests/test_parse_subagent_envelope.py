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

import ast
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from unittest import mock

import pytest

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


# === Phase 159a: per-phase envelope keying =================================
#
# The hook keyed every envelope by the `TASK:` field alone, so one claim could
# hold exactly one envelope. The orchestrator reshape
# (tools/CLAIM_TASK_ORCHESTRATOR_SPEC.md) spawns a planner, a reviewer and an
# executor under ONE claim id, and all three emit envelopes — under the old key
# the executor's would silently overwrite the reviewer's.
#
# These assert on the filename actually written and the bytes actually landed.
#
# Measured, not asserted: run this file against the pre-159a parser and 21 of the
# 66 tests fail. The ones that stay green are the ones pinning the unchanged
# absent-PHASE path, which is their job -- they exist to prove the no-op, so a
# mechanism-deletion leaving them green is correct rather than a gap.
#
# Each phase test names an EXACT filename rather than a count or a bound. That is
# a correction, not a style: an earlier revision of this block claimed "deleting
# the mechanism cannot leave them green", and the round measured 11 of 17 staying
# green -- including both safety tests, because a file count cannot tell
# "sanitized correctly" apart from "PHASE: ignored entirely".


def _envelope(task="FEAT-0123", phase=None, status="EXECUTED"):
    lines = [f"TASK: {task}", f"STATUS: {status}", "WORKTREE: /tmp/wt", "BRANCH: b"]
    if phase is not None:
        lines.append(f"PHASE: {phase}")
    return "```yaml\n" + "\n".join(lines) + "\n```\n"


def _emit(monkeypatch, tmp_path, last, agent="agent-1"):
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    return _run_main_with_stdin(monkeypatch, {
        "last_assistant_message": last,
        "session_id": "sess-1",
        "agent_id": agent,
        "cwd": str(tmp_path),
    })


def test_absent_phase_keeps_the_historical_filename(monkeypatch, tmp_path):
    """No PHASE: field → `<TASK_ID>.json`, exactly as before Phase 159a."""
    assert _emit(monkeypatch, tmp_path, _envelope()) == 0
    out_dir = tmp_path / pse.ENVELOPES_DIR
    assert (out_dir / "FEAT-0123.json").is_file()
    assert [p.name for p in out_dir.glob("*.json")] == ["FEAT-0123.json"]


def test_none_sentinel_phase_keeps_the_historical_filename(monkeypatch, tmp_path):
    """`PHASE: none` is the documented sentinel → historical filename."""
    assert _emit(monkeypatch, tmp_path, _envelope(phase="none")) == 0
    out_dir = tmp_path / pse.ENVELOPES_DIR
    assert (out_dir / "FEAT-0123.json").is_file()
    assert not list(out_dir.glob("FEAT-0123.*.json"))


def test_present_phase_keys_the_filename(monkeypatch, tmp_path):
    assert _emit(monkeypatch, tmp_path, _envelope(phase="review")) == 0
    out = tmp_path / pse.ENVELOPES_DIR / "FEAT-0123.review.json"
    assert out.is_file()
    assert json.loads(out.read_text(encoding="utf-8"))["phase"] == "review"


def test_three_phases_of_one_claim_do_not_overwrite_each_other(monkeypatch, tmp_path):
    """The defect this exists to fix: three sub-agents, one claim id, three files."""
    for phase in ("plan", "review", "exec"):
        assert _emit(monkeypatch, tmp_path, _envelope(phase=phase), agent=phase) == 0
    out_dir = tmp_path / pse.ENVELOPES_DIR
    assert sorted(p.name for p in out_dir.glob("*.json")) == [
        "FEAT-0123.exec.json",
        "FEAT-0123.plan.json",
        "FEAT-0123.review.json",
    ]
    # Each file must carry its OWN phase — a last-writer-wins bug would leave
    # three filenames whose contents all name the final stage.
    for phase in ("plan", "review", "exec"):
        payload = json.loads((out_dir / f"FEAT-0123.{phase}.json").read_text())
        assert payload["phase"] == phase


def test_phase_cannot_escape_the_envelopes_directory(monkeypatch, tmp_path):
    """PHASE: is agent-supplied and becomes a path component — it must be inert.

    Asserts the EXACT resulting name. An earlier version asserted only a file
    count plus `"/" not in name` and `".." not in name`; the first two of those
    cannot fail (`Path.glob` is non-recursive and `Path.name` never holds a
    separator) and the third is a wrong predicate — `PHASE: a..b` yields the
    perfectly safe `FEAT-0123.a..b.json`, which it would have rejected.
    """
    assert _emit(monkeypatch, tmp_path, _envelope(phase="../../../../etc/passwd")) == 0
    out_dir = tmp_path / pse.ENVELOPES_DIR
    assert [p.name for p in out_dir.glob("*.json")] == ["FEAT-0123.etc_passwd.json"]
    assert not (tmp_path / "etc").exists()


def test_phase_is_length_capped_at_exactly_PHASE_MAX_LEN(monkeypatch, tmp_path):
    """Pins the constant, not a slack bound.

    `len(name) < 100` admitted any cap up to 84, so the documented 32 could drift
    by 52 with the suite green. Assert the exact name instead.
    """
    assert pse._PHASE_MAX_LEN == 32
    assert _emit(monkeypatch, tmp_path, _envelope(phase="p" * 500)) == 0
    out_dir = tmp_path / pse.ENVELOPES_DIR
    assert [p.name for p in out_dir.glob("*.json")] == ["FEAT-0123." + "p" * 32 + ".json"]


def test_phase_that_sanitizes_to_nothing_falls_back(monkeypatch, tmp_path):
    """`...` reduces to empty → historical filename, not a stray-dot name."""
    assert _emit(monkeypatch, tmp_path, _envelope(phase="...")) == 0
    out_dir = tmp_path / pse.ENVELOPES_DIR
    assert (out_dir / "FEAT-0123.json").is_file()
    assert json.loads((out_dir / "FEAT-0123.json").read_text())["phase"] is None


# === Phase 159a: TASK_ID grammar realigned with the schema ==================


def test_task_id_shape_matches_the_validator_grammar():
    """Drift guard. The hook and validate_tasks.py must accept the same ids.

    They were divergent before Phase 159a: the hook REQUIRED an interior hyphen,
    so schema-valid ids were rejected here and silently downgraded to an
    _unparseable_ diagnostic. The two patterns are deliberately duplicated (the
    hook runs independently of the validator), so only a guard keeps them in step.
    """
    validator = (
        Path(__file__).resolve().parents[1]
        / "core/companion/scripts/validate_tasks.py"
    ).read_text(encoding="utf-8")
    m = re.search(r"^_TASK_ID_RE = re\.compile\(r\"(.+?)\"\)", validator, re.MULTILINE)
    assert m, "could not locate _TASK_ID_RE in validate_tasks.py"
    assert pse._TASK_ID_SHAPE_RE.pattern == m.group(1)

    # Bind both to the DOCUMENTED schema too. Comparing the two scripts only to
    # each other is a coupling test: editing both together silently desynchronises
    # them from tasks/schema.md, which is the actual source of truth and the thing
    # a consumer authoring task ids reads.
    schema = (
        Path(__file__).resolve().parents[1]
        / "core/companion/tasks/schema.md"
    ).read_text(encoding="utf-8")
    assert pse._TASK_ID_SHAPE_RE.pattern in schema, (
        "the hook's TASK_ID grammar is not the one documented in tasks/schema.md"
    )


@pytest.mark.parametrize("task_id", [
    "FEAT-0123",     # ordinary roadmap id
    "BATCH-116",     # a review-batch claim id
    "TECH-AUTO-CLAIM-LOOSEN-GATE-EXPERIMENT",
    "FEAT001",       # schema-valid, REJECTED before Phase 159a
    "ABC",           # schema-valid, REJECTED before Phase 159a
])
def test_schema_valid_ids_write_a_real_envelope(monkeypatch, tmp_path, task_id):
    assert _emit(monkeypatch, tmp_path, _envelope(task=task_id)) == 0
    out_dir = tmp_path / pse.ENVELOPES_DIR
    assert (out_dir / f"{task_id}.json").is_file()
    assert not list(out_dir.glob("_unparseable_*.json"))


@pytest.mark.parametrize("task_id", [
    "feat-0123",      # lowercase
    "1FEAT-0001",     # must start with a letter
    "AB",             # under the 3-character floor
    "A" * 82,         # over the 81-character ceiling
])
def test_ids_outside_the_schema_still_become_diagnostics(monkeypatch, tmp_path, task_id):
    assert _emit(monkeypatch, tmp_path, _envelope(task=task_id)) == 0
    out_dir = tmp_path / pse.ENVELOPES_DIR
    assert len(list(out_dir.glob("_unparseable_*.json"))) == 1
    assert not (out_dir / f"{task_id}.json").exists()


# === Phase 159a round: gaps the three-reviewer round measured ===============
#
# Every test below exists because a mutation survived or a behaviour had no
# coverage at all. Each names the exact filename or payload value, because the
# round showed that counts and bounds cannot tell a correct transform apart from
# no transform.


def test_phase_is_lowercased_before_it_names_a_file(monkeypatch, tmp_path):
    """`PHASE: Plan` and `PHASE: plan` must not be two files on Linux and one on macOS.

    Without normalisation the mechanism that exists to keep two sub-agents'
    envelopes apart silently splits by platform: case-sensitive filesystems get
    two files, APFS/HFS+ get one, and which sub-agent wins depends on the OS.
    """
    assert _emit(monkeypatch, tmp_path, _envelope(phase="ReViEw")) == 0
    out_dir = tmp_path / pse.ENVELOPES_DIR
    assert [p.name for p in out_dir.glob("*.json")] == ["FEAT-0123.review.json"]
    payload = json.loads((out_dir / "FEAT-0123.review.json").read_text())
    assert payload["phase"] == "review"
    assert payload["phase_raw"] == "ReViEw"


def test_truncation_cannot_re_expose_a_trailing_separator(monkeypatch, tmp_path):
    """The outer `.strip("._")` has exactly one job, and nothing used to test it.

    `_sanitize_for_filename` already strips, so the outer strip matters only when
    `[:_PHASE_MAX_LEN]` cuts mid-string and lands on a separator. Dropping it, or
    swapping the truncate/strip order, produced `FEAT-0123.aaa..json` with the
    whole suite green.
    """
    phase = "a" * 31 + ".zzz"
    assert _emit(monkeypatch, tmp_path, _envelope(phase=phase)) == 0
    out_dir = tmp_path / pse.ENVELOPES_DIR
    name = [p.name for p in out_dir.glob("*.json")][0]
    assert name == "FEAT-0123." + "a" * 31 + ".json"
    assert ".." not in name


@pytest.mark.parametrize("phase,expected_component", [
    ("review", "review"),
    ("ReViEw", "review"),
    ("plan/step one", "plan_step_one"),
    ("../../../../etc/passwd", "etc_passwd"),
    ("p" * 500, "p" * 32),
    ("a" * 31 + ".zzz", "a" * 31),
])
def test_payload_phase_always_names_the_file_that_was_written(
    monkeypatch, tmp_path, phase, expected_component
):
    """A consumer must be able to rebuild the path from the payload.

    The payload recorded the RAW phase while the filename used the sanitized one,
    so the two disagreed for every input that sanitizing, lower-casing or
    truncation touched — and a mutation swapping them survived the whole suite.
    """
    assert _emit(monkeypatch, tmp_path, _envelope(phase=phase)) == 0
    out_dir = tmp_path / pse.ENVELOPES_DIR
    written = [p.name for p in out_dir.glob("*.json")]
    assert written == [f"FEAT-0123.{expected_component}.json"]
    payload = json.loads((out_dir / written[0]).read_text())
    assert payload["phase"] == expected_component
    assert f"FEAT-0123.{payload['phase']}.json" == written[0]
    assert payload["phase_raw"] == phase


def test_bare_phase_key_with_no_value_takes_the_historical_path(monkeypatch, tmp_path):
    """`PHASE:` alone yields "" from _extract_field, not None. Reachable, untested."""
    last = "```yaml\nTASK: FEAT-0123\nSTATUS: EXECUTED\nPHASE:\n```\n"
    assert _emit(monkeypatch, tmp_path, last) == 0
    out_dir = tmp_path / pse.ENVELOPES_DIR
    assert [p.name for p in out_dir.glob("*.json")] == ["FEAT-0123.json"]
    payload = json.loads((out_dir / "FEAT-0123.json").read_text())
    assert payload["phase"] is None and payload["phase_raw"] is None


def test_same_task_and_phase_twice_overwrites_last_wins(monkeypatch, tmp_path):
    """The intended overwrite. Distinct phases must not collide; identical ones must."""
    assert _emit(monkeypatch, tmp_path, _envelope(phase="exec", status="BLOCKED")) == 0
    assert _emit(monkeypatch, tmp_path, _envelope(phase="exec", status="EXECUTED")) == 0
    out_dir = tmp_path / pse.ENVELOPES_DIR
    assert [p.name for p in out_dir.glob("*.json")] == ["FEAT-0123.exec.json"]
    assert json.loads((out_dir / "FEAT-0123.exec.json").read_text())["status"] == "EXECUTED"


@pytest.mark.parametrize("task_id,accepted", [
    ("A" * 80, True),    # one under the ceiling
    ("A" * 81, True),    # the exact ceiling
    ("A" * 82, False),   # one over
    ("ABC", True),       # the exact floor
    ("AB", False),       # one under the floor
])
def test_task_id_length_boundaries(monkeypatch, tmp_path, task_id, accepted):
    """The ceiling was only ever killed by the drift guard — no behavioural test saw it."""
    assert _emit(monkeypatch, tmp_path, _envelope(task=task_id)) == 0
    out_dir = tmp_path / pse.ENVELOPES_DIR
    assert (out_dir / f"{task_id}.json").is_file() is accepted
    assert bool(list(out_dir.glob("_unparseable_*.json"))) is not accepted


@pytest.mark.parametrize("task_id", [".FEAT-0123", "FEAT-0123.", "_FEAT-0123"])
def test_task_shape_is_checked_before_sanitizing_not_after(monkeypatch, tmp_path, task_id):
    """The one ordering invariant in main(), previously unpinned.

    The shape check runs on the RAW task id. Checking the sanitized one instead
    would silently normalise these into `FEAT-0123.json` — the hook accepting an
    id the validator rejects — and that mutation survived the whole suite.
    """
    assert _emit(monkeypatch, tmp_path, _envelope(task=task_id)) == 0
    out_dir = tmp_path / pse.ENVELOPES_DIR
    assert not (out_dir / "FEAT-0123.json").exists()
    assert len(list(out_dir.glob("_unparseable_*.json"))) == 1


# ─── Phase 159b: /claim-task Step 8 tolerates both envelope filenames ───────
#
# The hook has written `<TASK_ID>.<phase>.json` since Phase 159a whenever the
# agent emits `PHASE:`, and `<TASK_ID>.json` when it does not. No shipped
# prompt emits it yet, so Step 8's un-phased read is CORRECT today — which is
# why this slice makes the read tolerant rather than repointing it. Repointing
# now would break the working path for a shape nothing produces.

# ── Q-448 (Phase 272): `_write_json`'s mkstemp shape, asserted as PROPERTIES ──
# Presence of `mkstemp(` is not the property (Phase 271's round bypassed every
# presence check). Each element is driven: where the temp is minted and what it
# is called, what mode the result carries, what a symlinked target gets, and
# what a failure — OSError or not — leaves behind and reports.


def test_write_json_mints_its_temp_beside_the_envelope_not_at_a_fixed_name(
        tmp_path, monkeypatch):
    seen = {}
    real_replace = os.replace

    def spy(src, dst):
        seen["src"], seen["dst"] = str(src), str(dst)
        return real_replace(src, dst)

    monkeypatch.setattr(pse.os, "replace", spy)
    target = tmp_path / "envelopes" / "TASK-1.json"
    assert pse._write_json(str(target), {"a": 1}) is True
    assert json.loads(target.read_text()) == {"a": 1}
    assert os.path.dirname(seen["src"]) == str(target.parent), (
        "the temp was minted outside the mailbox — os.replace can raise EXDEV")
    assert seen["src"] != str(target) + ".tmp", "the fixed name is back"
    name = os.path.basename(seen["src"])
    assert name.startswith("TASK-1.json.") and name.endswith(".tmp"), name
    # never `.json`: readers open `<TASK_ID>.json` by exact name (the claim
    # skills) or glob `*.json` (`/review-close` Step 2e's stray count), and a
    # `.json`-suffixed temp would be a torn read for the second kind
    assert not name.endswith(".json")


def test_write_json_carries_an_existing_envelopes_mode(tmp_path):
    target = tmp_path / "envelopes" / "TASK-1.json"
    target.parent.mkdir()
    target.write_text("{}\n")
    os.chmod(target, 0o640)
    assert pse._write_json(str(target), {"b": 2}) is True
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert json.loads(target.read_text()) == {"b": 2}


def test_a_fresh_envelope_gets_the_mode_open_would_have_given(tmp_path):
    """No target to carry a mode from: the result must be what the fixed-name
    `open(tmp, "w")` produced — 0666 under the umask — not a hard-coded 0644
    (which WIDENS for a 077 umask) and not mkstemp's 0600."""
    for umask, want in ((0o022, 0o644), (0o077, 0o600)):
        target = tmp_path / f"u{umask:o}" / "TASK-1.json"
        old = os.umask(umask)
        try:
            assert pse._write_json(str(target), {"a": 1}) is True
        finally:
            os.umask(old)
        assert stat.S_IMODE(target.stat().st_mode) == want, oct(umask)


def test_write_json_writes_through_a_symlink(tmp_path):
    real = tmp_path / "real.json"
    real.write_text("{}\n")
    d = tmp_path / "envelopes"
    d.mkdir()
    link = d / "TASK-1.json"
    link.symlink_to(real)
    assert pse._write_json(str(link), {"c": 3}) is True
    assert link.is_symlink(), "the symlink itself was replaced"
    assert json.loads(real.read_text()) == {"c": 3}


def test_write_json_reports_false_and_leaves_no_temp_when_the_replace_fails(
        tmp_path, monkeypatch, capsys):
    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(pse.os, "replace", boom)
    target = tmp_path / "envelopes" / "TASK-1.json"
    assert pse._write_json(str(target), {"a": 1}) is False
    assert "failed to write" in capsys.readouterr().err
    assert list(target.parent.iterdir()) == [], "the cleanup arm did not run"


def test_write_json_cleans_up_when_the_payload_is_unserializable(tmp_path):
    """`json.dump` raises `TypeError` — not an `OSError` — after it has already
    streamed a partial document into the temp. Under the fixed name that leak
    was overwritten by the next hook run; a minted name never is, so the arm
    must reach past `OSError`, and must still re-raise: the hook's failure is
    the hook's failure."""
    target = tmp_path / "envelopes" / "TASK-1.json"
    with pytest.raises(TypeError):
        pse._write_json(str(target), {"a": object()})
    assert not target.exists()
    assert list(target.parent.iterdir()) == [], "the partial temp survived"


def test_write_json_leaves_the_process_umask_as_it_found_it(tmp_path):
    """`_umask_mode` reads the umask by setting it; a round dropped the restore
    and the hook process ran on at umask 0 (`P09`).

    Against a KNOWN value this test sets, not "unchanged from whatever it was":
    the first draft compared before and after, and with the restore dropped an
    EARLIER test's fresh write had already zeroed the umask, so 0 == 0 passed —
    the mutation survived the whole module and died only when run alone, which
    read as a caching artefact until the order was the explanation."""
    original = os.umask(0o027)
    try:
        target = tmp_path / "envelopes" / "TASK-1.json"
        assert pse._write_json(str(target), {"a": 1}) is True
        now = os.umask(0)
        os.umask(now)
        assert now == 0o027, f"umask left at {now:o}, expected 27"
    finally:
        os.umask(original)


def test_write_json_mints_beside_the_real_file_not_beside_the_link(tmp_path, monkeypatch):
    """Link and target in DIFFERENT directories, so `dir=dirname(path)` and
    `dir=dirname(real)` are distinguishable (`P11`)."""
    sub = tmp_path / "elsewhere"
    sub.mkdir()
    real = sub / "real.json"
    real.write_text("{}\n")
    d = tmp_path / "envelopes"
    d.mkdir()
    link = d / "TASK-1.json"
    link.symlink_to(real)
    seen = {}
    real_replace = os.replace

    def spy(src, dst):
        seen["src"] = str(src)
        return real_replace(src, dst)

    monkeypatch.setattr(pse.os, "replace", spy)
    assert pse._write_json(str(link), {"c": 3}) is True
    assert os.path.dirname(seen["src"]) == str(sub), seen
    assert link.is_symlink() and json.loads(real.read_text()) == {"c": 3}


def test_an_unwritable_mailbox_is_reported_not_a_traceback(tmp_path, capsys):
    """`mkstemp` is the likeliest place an OSError arises, and it sits in its
    own arm — the hole Phase 271's round found in the sibling conversion."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root ignores directory modes")
    d = tmp_path / "envelopes"
    d.mkdir()
    os.chmod(d, 0o555)
    try:
        ok = pse._write_json(str(d / "TASK-1.json"), {"a": 1})
    finally:
        os.chmod(d, 0o755)
    assert ok is False
    assert "failed to write" in capsys.readouterr().err
    assert list(d.iterdir()) == []


import re as _re
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parents[1]
_CLAIM_SKILL = _REPO_ROOT / "core/skills/claim-task/SKILL.md"


def _step8(text=None):
    text = text if text is not None else _CLAIM_SKILL.read_text(encoding="utf-8")
    m = _re.search(r"^## Step 8.*?$(.*?)(?=^## |\Z)", text, _re.M | _re.S)
    assert m, "Step 8 not found in claim-task/SKILL.md"
    return m.group(1)


def step8_envelope_problems(text=None):
    """Step 8's invariants AFTER the orchestrator reshape.

    Supersedes the Phase-159b tolerance guards (un-phased-first resolution
    order, phased glob fallback, exec>review>plan precedence, narrow delete).
    Those existed because no shipped prompt emitted PHASE:, so Step 8 had to
    guess which filename the hook had written -- and 159b's own in-tree note
    said the scaffolding was waiting for this: "repointing this read at the
    phased names *before* that lands would break the working single-envelope
    path for no gain."

    The reshape landed it. All three spawn prompts emit PHASE:, so the
    filenames are deterministic and there is nothing left to resolve. The
    successor invariants are STRONGER, not weaker: "do not widen the delete"
    becomes "do not delete at all", which is the defect the whole reshape
    exists to remove -- an envelope destroyed at the moment it became evidence.
    """
    problems = []
    s8 = _step8(text)

    # 1. Step 8 reads the EXEC envelope. Reporting the plan or review envelope
    #    as the executed result is what the old exec>review>plan precedence
    #    rule guarded; it is now prevented by construction instead of ordering.
    if not _re.search(r"`<CLAIM_ID>\.exec\.json`", s8):
        problems.append("Step 8 no longer names the exec envelope it must read")

    # 2. NOTHING is deleted mid-lifecycle. Matched as a command span, so the
    #    paragraph *forbidding* deletion does not fire it -- the failure mode
    #    _shared/adversarial-review.md Test strategy names by hand.
    if _re.search(r"`rm -f sysop/runtime/subagent-envelopes/", s8):
        problems.append(
            "Step 8 deletes an envelope -- deleting after consumption is why a "
            "review that DID run left no durable trace, the defect the reshape "
            "exists to remove"
        )
    if not _re.search(r"\*\*Do not delete the envelopes here\.\*\*", s8):
        problems.append("Step 8 lost its explicit no-delete rule")

    # 3. Absence is AMBIGUOUS until the diagnostic is checked. The hook keys
    #    _unparseable_ by session+agent, never by claim id, so a claim-keyed
    #    read sees nothing at all and "the executor never ran" is the wrong
    #    conclusion -- a dead run and a healthy-but-malformed one otherwise
    #    produce identical evidence.
    if not _re.search(r"_unparseable_", s8):
        problems.append(
            "Step 8 can conclude an envelope is absent without checking for an "
            "_unparseable_ diagnostic"
        )

    # 4. Resolved against the MAIN repo root -- the hook resolves its own
    #    output that way, so a worktree-relative read finds nothing.
    if not _re.search(r"git rev-parse --git-common-dir", s8):
        problems.append(
            "Step 8 no longer resolves the envelope against the main repo root"
        )

    # 5. A step naming claim-keyed filenames inside a roadmap-shaped mechanism
    #    carries an explicit Review batches: clause -- claim-task's own Step 1
    #    convention, and the Phase-29 failure (silence reads as
    #    not-applicable). Steps 7-8 are precisely where that happened before.
    if not _re.search(r"\*\*Review batches:\*\*", s8):
        problems.append(
            "Step 8 names claim-keyed filenames with no **Review batches:** clause"
        )
    return problems


def phase_emission_problems(text=None):
    """Every spawn prompt must emit PHASE:, or their envelopes collide on
    <CLAIM_ID>.json and last-writer-wins -- the exact defect Phase 159a built
    the optional key to prevent. Step 8's deterministic read of
    <CLAIM_ID>.exec.json rests on this and on nothing else, so the emission and
    the read have to be guarded together or the pair can drift apart silently.
    """
    text = _CLAIM_SKILL.read_text(encoding="utf-8") if text is None else text
    problems = []
    for phase in ("plan", "review"):
        if not _re.search(r"^PHASE: %s$" % phase, text, _re.M):
            problems.append("no spawn prompt emits `PHASE: %s`" % phase)
    # Step 7e's prompt serves two spawns since Phase 345: the executor and Step 8c's answers
    # run. Its envelope line is a placeholder each spawn substitutes, so both substitutions
    # must be stated, or one of the two envelopes lands on the other's name.
    placeholder = _re.search(r"^PHASE: <ENVELOPE_PHASE>$", text, _re.M)
    # Each substitution is read at the spawn it governs, not anywhere in the file: stated
    # at another spawn, the sentence reads right and binds nothing (Phase 345 round 1, R07b).
    def at(start, end):
        i = text.find(start)
        if i < 0:
            return ""
        j = text.find(end, i) if end else -1
        return text[i:j] if j > i else text[i:]
    for phase, said, where in (
            ("exec", "`exec` substituted for `<ENVELOPE_PHASE>`", at("### Step 7e", "**START OF EXECUTOR PROMPT**")),
            ("answers", "except `answers` for `<ENVELOPE_PHASE>`", at("### Step 8c", "**START OF ANSWERS ADDENDUM**"))):
        literal = phase == "exec" and _re.search(r"^PHASE: exec$", text, _re.M)
        if not literal and not (placeholder and said in where):
            problems.append("no spawn prompt emits `PHASE: %s`" % phase)
    return problems


def test_step8_reads_the_exec_envelope_and_deletes_nothing():
    assert step8_envelope_problems() == []


def test_all_three_spawn_prompts_emit_phase():
    assert phase_emission_problems() == []


def test_guard_catches_a_step8_that_deletes_an_envelope():
    text = _CLAIM_SKILL.read_text(encoding="utf-8")
    broken = text.replace(
        "**Do not delete the envelopes here.**",
        "After consuming, `rm -f sysop/runtime/subagent-envelopes/<CLAIM_ID>.exec.json`.",
        1)
    assert broken != text
    problems = step8_envelope_problems(broken)
    assert any("deletes an envelope" in p for p in problems)
    assert any("lost its explicit no-delete rule" in p for p in problems)


def test_guard_catches_a_softened_no_delete_rule():
    """The no-delete rule must survive being turned into a suggestion."""
    text = _CLAIM_SKILL.read_text(encoding="utf-8")
    softened = text.replace(
        "**Do not delete the envelopes here.**",
        "You may tidy up the envelopes here if you like.", 1)
    assert softened != text
    assert any("no-delete rule" in p for p in step8_envelope_problems(softened))


def test_guard_catches_a_step8_that_reads_the_wrong_phase():
    text = _CLAIM_SKILL.read_text(encoding="utf-8")
    broken = text.replace("`<CLAIM_ID>.exec.json`", "`<CLAIM_ID>.plan.json`")
    assert broken != text
    assert any("exec envelope" in p for p in step8_envelope_problems(broken))


def test_guard_catches_a_step8_that_ignores_unparseable_diagnostics():
    text = _CLAIM_SKILL.read_text(encoding="utf-8")
    s8_start = text.index("## Step 8")
    broken = text[:s8_start] + text[s8_start:].replace("_unparseable_", "irrelevant")
    assert broken != text
    assert any("_unparseable_" in p for p in step8_envelope_problems(broken))


def test_guard_catches_a_prompt_that_drops_its_phase_key():
    """Dropping PHASE from one prompt collides that envelope onto the
    un-phased name -- silent, and it makes Step 8's read find nothing."""
    text = _CLAIM_SKILL.read_text(encoding="utf-8")
    breaks = {
        "plan": [("PHASE: plan", "PHASE: none")],
        "review": [("PHASE: review", "PHASE: none")],
        # The shared prompt's line, then each spawn's substitution on its own.
        "exec": [("PHASE: <ENVELOPE_PHASE>", "PHASE: none"),
                 ("`exec` substituted for `<ENVELOPE_PHASE>`", "`none` substituted for it")],
        "answers": [("PHASE: <ENVELOPE_PHASE>", "PHASE: none"),
                    ("`answers` for `<ENVELOPE_PHASE>`", "`none` for it"),
                    # "except" is what makes it the one substitution that differs.
                    ("except `answers` for `<ENVELOPE_PHASE>`", "including `exec` for `<ENVELOPE_PHASE>` (not `answers` for `<ENVELOPE_PHASE>`)")],
    }
    for phase, edits in breaks.items():
        for old, new in edits:
            broken = text.replace(old, new, 1)
            assert broken != text, (phase, old)
            assert any(phase in p for p in phase_emission_problems(broken)), (phase, old)

    # R07b: the substitution moved to another spawn still reads right in the file.
    said = ", and `exec` substituted for `<ENVELOPE_PHASE>`."
    assert text.count(said) == 1
    moved = text.replace(said, ".", 1).replace(
        "### Step 7b: Spawn the reviewer", "### Step 7b: Spawn the reviewer\n\n`exec` substituted for `<ENVELOPE_PHASE>`.", 1)
    assert any("exec" in p for p in phase_emission_problems(moved))


def test_claim_task_carries_no_run_in_background_agent_parameter():
    """`run_in_background` is not a parameter of the Agent tool -- its schema is
    closed, so a compliant call raises InputValidationError. Phase 155 removed
    this line; that removal died with the reverted branch and never reached
    main. The reshape rewrites this exact step, so it must not be re-inherited
    into the three new spawn prompts.

    Scoped to claim-task deliberately: eleven sibling sites survive in
    /auto-build, /auto-fix and /auto-judge and are tracked separately in
    REVIEW_CHECKLIST.md § High. Widening this guard would fail on work this
    phase did not do.

    MATCHES STRUCTURE, NOT THE BARE TOKEN. The first form of this guard failed
    on any line containing the string, which made it fire on the orchestrator's
    own sentence *forbidding* the parameter -- the failure mode
    _shared/adversarial-review.md Test strategy names outright ("the sentence
    forbidding `rm -f` contains `rm -f`"). A guard that punishes documentation
    for describing what it prevents pressures the next author to delete the
    explanation to get green, which is how the parameter came back the first
    time. So: the assignment shape is banned outright, and a bare mention is
    allowed only where it is being prohibited."""
    text = _CLAIM_SKILL.read_text(encoding="utf-8")

    # (1) The real ratchet: `run_in_background` can only be *passed* as an
    #     assignment, so ban that shape in any spelling (bare, backticked,
    #     YAML- or list-style, true or false).
    assigned = [
        i for i, line in enumerate(text.splitlines(), 1)
        if re.search(r"run_in_background`?\s*:\s*`?\s*(true|false)\b", line)
    ]
    assert not assigned, (
        f"claim-task/SKILL.md passes run_in_background as an Agent parameter at "
        f"line(s) {assigned} -- the tool's schema is closed and a compliant call "
        f"raises InputValidationError."
    )

    # (2) Vacuity floor in the other direction: a future author must not slip it
    #     back in under some new syntax this regex does not model. Every mention
    #     has to sit in a sentence that forbids it.
    mentions = [(i, line) for i, line in enumerate(text.splitlines(), 1)
                if "run_in_background" in line]
    unprohibited = [
        i for i, line in mentions
        if not re.search(r"\bNOT\b|\bnot a parameter\b|\bnever\b", line)
    ]
    assert not unprohibited, (
        f"claim-task/SKILL.md mentions run_in_background outside a prohibition at "
        f"line(s) {unprohibited} -- if it is being described rather than forbidden, "
        f"say why it must not be passed."
    )


# === Fence grammar (`Q-372`) ===============================================
#
# The reported defect: the module paired fences with
# `` ```(?:yaml|yml)?\s*\n(.*?)\n``` ``, which recognises only `yaml`, `yml`
# and a bare fence as OPENERS. A ```bash block — what a code-writing executor
# emits on the ordinary path — is therefore not seen as a fence at all, its
# CLOSING run pairs with the next opener, and every later block shifts by one,
# so the real envelope lands inside what the parser reads as prose. A live
# consumer's `SubagentStop` hook wrote `_unparseable_<session>_<agent>.json`
# saying "no fenced YAML block with TASK: and STATUS:" while the envelope sat
# visible inside that same diagnostic's `last_assistant_message_excerpt`.
#
# The fix borrows the scanner the four structural readers already share rather
# than widening the info string, because widening alone leaves the rest of the
# class: a 4-backtick opener, a `~~~` fence, an indented one. The dialect dates
# from Phase 37 (`45b1745`) and outlived the shared scanner's arrival in Phase
# 181 (`3c4b5f7`) by 70 phases.


def test_a_bash_block_before_the_envelope_does_not_eat_it():
    """The reported case, verbatim in shape.

    Under the old pair regex this returned None and the hook wrote an
    `_unparseable_` diagnostic for an agent that had complied.
    """
    text = (
        "Done. Here is what I ran:\n"
        "\n"
        "```bash\n"
        "pytest -q\n"
        "```\n"
        "\n"
        "Envelope:\n"
        "\n"
        "```yaml\n"
        "TASK: FEAT-0123\n"
        "STATUS: EXECUTED\n"
        "```\n"
    )
    assert pse._find_envelope_block(text) == "TASK: FEAT-0123\nSTATUS: EXECUTED"


def test_any_info_string_opens_a_block():
    """Not an allowlist. `bash` was the reported one; it is not the only one."""
    for info in ("bash", "sh", "python", "json", "diff", "text", "console", ""):
        text = f"```{info}\nnoise\n```\n\n```yaml\nTASK: T-1\nSTATUS: EXECUTED\n```\n"
        assert pse._find_envelope_block(text) == "TASK: T-1\nSTATUS: EXECUTED", info


def test_envelope_inside_a_longer_fence_is_not_closed_by_a_shorter_run():
    """Marker LENGTH is load-bearing, exactly as in `_fenced_mask`."""
    text = "````markdown\n```\nnot the end\n```\n````\n\n```yaml\nTASK: T-2\nSTATUS: EXECUTED\n```\n"
    assert pse._find_envelope_block(text) == "TASK: T-2\nSTATUS: EXECUTED"


def test_a_shorter_run_does_not_close_a_longer_opener():
    """The LENGTH half asserted directly, because the case above cannot see it.

    Dropping `len(m.group(1)) >= len(marker)` survived the author-side battery:
    with the length check gone the nested ``` merely splits the outer block into
    two empty ones, the ```yaml block is still found, and an envelope-level
    assertion reads the same either way. Asserting the BODIES is what makes the
    predicate observable.
    """
    assert pse._fenced_blocks("````\n```\ninner\n```\n````\n") == ["```\ninner\n```"]


def test_this_module_carries_the_shared_fence_patterns_verbatim():
    """A vacuity + membership control for the cross-module pin (`Q-372`).

    `tests/test_flag_contract.py` asserts the five modules' patterns are equal,
    which is satisfied when they are all equally WRONG, and its population is a
    tuple somebody can shorten. Two mutations survived the author-side battery
    on exactly that: editing this module's pattern was invisible to its own
    suite, and dropping this module from the pinned tuple was invisible to both.
    """
    import review_index as _ri
    import test_flag_contract as _fc

    assert pse in _fc.FENCE_PATTERN_MODULES, (
        "parse_subagent_envelope dropped out of the pinned fence population"
    )
    assert pse._FENCE_OPEN_RE.pattern == _ri._FENCE_OPEN_RE.pattern
    assert pse._FENCE_CLOSE_RE.pattern == _ri._FENCE_CLOSE_RE.pattern
    # The indent boundary, spelled out rather than left to the shared pattern:
    # a 4-space indent is an indented code block, not a fence, and mutating
    # ONE of the two patterns to `{0,4}` leaves the block unterminated rather
    # than visible — so the boundary needs an assertion of its own.
    assert "^ {0,3}" in pse._FENCE_OPEN_RE.pattern
    assert "^ {0,3}" in pse._FENCE_CLOSE_RE.pattern


def test_a_tilde_run_does_not_close_a_backtick_fence():
    """Marker CHARACTER is load-bearing too."""
    blocks = pse._fenced_blocks("```\n~~~\nstill inside\n```\n")
    assert blocks == ["~~~\nstill inside"]


def test_an_unterminated_fence_yields_nothing():
    """Matches `_fenced_mask`'s deliberate choice.

    Honouring an unterminated opener would swallow the rest of the message —
    and the envelope is emitted LAST, so that is precisely the wrong direction
    here.
    """
    assert pse._fenced_blocks("prose\n```bash\nnobody closed this\n") == []


def test_an_unclosed_code_block_degrades_to_recovery_not_to_loss():
    """The honest outcome when an executor forgets a closing fence.

    **This test asserted the opposite first, and the assertion was wrong about
    its own fixture.** A ```` ```yaml ```` line is not a CLOSE (it carries
    trailing text, which CommonMark forbids of a closer), so it is *content*
    inside the still-open ```` ```bash ```` block — one balanced block, not an
    unterminated one. The body therefore carries the stray prose AND the
    envelope, and because the field extractors are line-anchored the envelope
    still parses. That is the right direction: the old pair regex LOST the
    envelope in this shape; the scanner recovers it with noise attached.
    """
    text = "```bash\nan opener nobody closed\n\n```yaml\nTASK: T-3\nSTATUS: EXECUTED\n```\n"
    block = pse._find_envelope_block(text)
    assert block is not None
    assert pse._extract_field(block, "TASK") == "T-3"
    assert pse._extract_field(block, "STATUS") == "EXECUTED"


def test_a_mid_line_fence_is_not_a_fence():
    """CommonMark, and the same row the shared grammar table pins."""
    assert pse._fenced_blocks("see this ```yaml\nTASK: X\nSTATUS: Y\n```\n") == []


def test_four_space_indent_is_a_code_block_not_a_fence():
    assert pse._fenced_blocks("    ```\nx\n    ```\n") == []


def test_adjacent_blocks_stay_separate():
    """The reason this returns bodies rather than a boolean mask."""
    assert pse._fenced_blocks("```\na\n```\n```\nb\n```\n") == ["a", "b"]


def test_review_report_reads_through_the_same_scanner():
    """`Q-372` hit both consumers, not just the envelope one."""
    text = "```bash\nls\n```\n\n```yaml\nREVIEW_REPORT:\n  verdict: PASS\n```\n"
    assert pse._find_review_report_block(text) == "REVIEW_REPORT:\n  verdict: PASS"


# The one shipped script allowed to keep a fence-pair regex, and the reason it
# is load-bearing rather than decorative: emptying this set reddens the check on
# `sitrep_survey.py:865`, which the round confirmed.
_NAIVE_FENCE_EXEMPT = {"sitrep_survey.py"}


def _naive_fence_offenders(src, label):
    """Every STRING CONSTANT that pairs fences with a lazy group.

    **A shape, not a call.** The first cut gated on the line containing
    `re.compile`, `re.search` or `re.findall` — and the module this rule exists
    for used `re.finditer`, so the check could not see the exact code it was
    written about. Seven planted shapes survived it in Phase 251's round:
    `finditer` and `match` one-liners, a single-quoted `r'...'` inside a
    multi-line `re.compile(`, a named group, a `[\\s\\S]*?` body, and a pattern
    held in a variable and compiled on the next line.

    Reading string constants off the syntax tree removes all of that at once:
    quote style, call site, line breaks and whether the pattern is compiled
    where it is written are all irrelevant to it. Comments are excluded for
    free, which matters here — the fixed module's own header quotes the removed
    regex while explaining it.

    **Declared limit:** a pattern assembled by concatenation, or built at
    runtime, is out of reach in kind.
    """
    found = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        text = node.value
        if "```" not in text:
            continue
        # A lazy quantifier between the fences is what makes it a PAIR regex.
        if re.search(r"[*+]\?", text):
            found.append(f"{label}:{node.lineno}: {text.strip()[:90]!r}")
    return found


def test_no_shipped_script_pairs_fences_with_a_naive_regex():
    """The class check (`Q-372`), derived over the shipped scripts.

    A `` ```…(.*?)…``` `` pair regex is wrong in four independent ways — an
    unlisted info string, a longer opener, a `~~~` fence, an indented one — and
    this module carried one for eight phases. One site is allowed, and the
    allowance names its mechanism rather than asserting an exception:
    `sitrep_survey._classification_verdict`'s pattern accepts **any** info
    string (`(?:yaml|json)?[^\\n]*`), so the unlisted-opener desync this rule
    is about cannot reach it. Its only writer is `/claim-task` Step 7c emitting
    `json.dumps(report, indent=2)`, and it falls back to a flat `verdict:`
    scan, so even a desync would degrade rather than lose. None of that holds
    for free-form agent prose.
    """
    offenders = []
    scripts = _REPO_ROOT / "core" / "companion" / "scripts"
    for path in sorted(scripts.rglob("*.py")):
        if path.name in _NAIVE_FENCE_EXEMPT or "__pycache__" in path.parts:
            continue
        offenders += _naive_fence_offenders(path.read_text(encoding="utf-8"), path.name)
    assert not offenders, (
        "a shipped script pairs fences with a regex instead of the shared "
        "scanner (Q-372). Use the `_FENCE_OPEN_RE`/`_FENCE_CLOSE_RE` predicate:\n  "
        + "\n  ".join(offenders)
    )


def test_a_crlf_message_still_yields_its_envelope():
    """A regression the scanner introduced, found by driving the hook (`Q-372`).

    The pair regex this replaced closed on `\\n```\\s*`, and `\\s` matches `\\r` —
    so CRLF input worked. `_FENCE_CLOSE_RE` ends `[ \\t]*$`, which a bare `\\r`
    does not satisfy, so a CRLF message yielded NO balanced blocks at all and
    the hook wrote an `_unparseable_` diagnostic. That is the same silent
    envelope loss `Q-372` is filed about, reintroduced through the line ending
    by the fix for it.
    """
    crlf = (
        "Done.\r\n\r\n"
        "```bash\r\necho hi\r\n```\r\n\r\n"
        "```yaml\r\nTASK: FEAT-0123\r\nSTATUS: EXECUTED\r\n```\r\n"
    )
    assert pse._find_envelope_block(crlf) == "TASK: FEAT-0123\nSTATUS: EXECUTED"
    assert pse._fenced_blocks(crlf) == ["echo hi", "TASK: FEAT-0123\nSTATUS: EXECUTED"]
    # And the LF form is unchanged, so this is not a CRLF-only code path.
    assert pse._find_envelope_block(crlf.replace("\r\n", "\n")) == (
        "TASK: FEAT-0123\nSTATUS: EXECUTED"
    )


@pytest.mark.parametrize("shape", [
    'BLOCK = re.compile(r"```(?:yaml|yml)?\\s*\\n(.*?)\\n```", re.DOTALL)',
    "BLOCK = re.compile(r'```(?:yaml|yml)?\\s*\\n(.*?)\\n```', re.DOTALL)",
    'for m in re.finditer(r"```\\w*\\n(.*?)\\n```", text, re.S): pass',
    'm = re.match(r"```\\w*\\n(.*?)\\n```", text, re.S)',
    'BLOCK = re.compile(\n    r"```(?:yaml)?\\s*\\n(.*?)\\n```",\n    re.DOTALL,\n)',
    'BLOCK = re.compile(r"```\\w*\\n(?P<body>.*?)\\n```")',
    'BLOCK = re.compile(r"```\\w*\\n([\\s\\S]*?)\\n```")',
    'PAT = r"```\\w*\\n(.*?)\\n```"\nBLOCK = re.compile(PAT)',
])
def test_the_naive_fence_check_can_actually_see_these(shape):
    """The vacuity control, and the seven shapes that survived the first cut.

    The first entry is the pattern this module actually carried; the third is
    the call it actually used. A class check that cannot see its own subject is
    the failure this control exists to make impossible.
    """
    assert _naive_fence_offenders(shape, "planted.py"), f"cannot see: {shape!r}"


@pytest.mark.parametrize("shape", [
    '_FENCE_OPEN_RE = re.compile(r"^ {0,3}(?:> ?)*(`{3,}|~{3,})")',
    'x = "a ``` fence in prose, with no lazy group"',
    'y = re.compile(r"^\\s*(```|~~~)")',
])
def test_the_naive_fence_check_does_not_fire_on_legitimate_shapes(shape):
    """Over-strictness control: the shared scanner's own patterns must pass."""
    assert not _naive_fence_offenders(shape, "planted.py"), f"false positive: {shape!r}"


def test_the_naive_fence_allowlist_is_load_bearing():
    """Emptying the exemption must redden on the one site it names.

    An allowlist nothing would catch is decorative, and a decorative allowlist
    is indistinguishable from a check whose population went empty.
    """
    src = (_REPO_ROOT / "core/companion/scripts/sitrep_survey.py").read_text(encoding="utf-8")
    assert _naive_fence_offenders(src, "sitrep_survey.py"), (
        "the exempted site no longer carries a fence-pair regex — drop it from "
        "_NAIVE_FENCE_EXEMPT rather than leaving an exemption that shelters nothing"
    )


def test_the_naive_fence_population_reaches_the_run_checks_package():
    """`rglob`, not `glob` — the package's modules were invisible."""
    scripts = _REPO_ROOT / "core/companion/scripts"
    seen = {p.relative_to(scripts).as_posix() for p in scripts.rglob("*.py")}
    assert any(n.startswith("run_checks/") for n in seen), (
        "the population no longer reaches core/companion/scripts/run_checks/"
    )


def test_a_longer_closing_run_does_close_a_shorter_opener():
    """The `>=` half of the length rule, which only `<` was pinning.

    A fixture that opens 4 and closes 4 cannot tell `>=` from `==`, so
    `>=`→`==` survived. CommonMark says a closing run must be AT LEAST as long
    as the opener, not equal to it.
    """
    assert pse._fenced_blocks("```\nbody\n````\n") == ["body"]


def test_the_fence_markers_accept_runs_longer_than_three():
    """`` `{3,} `` and `~{3,}`, asserted as shapes AND driven.

    Narrowing both patterns to `{3}` **identically in all five modules** passes
    the cross-module equality pin — equal and equally wrong — and the only
    shape assertion in this file was about the indent. Both halves are pinned
    now, and a 4-tilde fence exercises the behaviour.
    """
    for pattern in (pse._FENCE_OPEN_RE.pattern, pse._FENCE_CLOSE_RE.pattern):
        assert "`{3,}" in pattern, pattern
        assert "~{3,}" in pattern, pattern
    assert pse._fenced_blocks("~~~~\nbody\n~~~~\n") == ["body"]


def test_the_review_report_reader_returns_the_FIRST_matching_block():
    """Its docstring says FIRST; the fixture had one block, so LAST survived.

    The contract matters: a reviewer that restates its report later in the
    message would otherwise have the restatement win over the report proper.
    """
    text = (
        "```yaml\nREVIEW_REPORT:\n  verdict: PASS\n```\n\n"
        "and here it is again, abbreviated:\n\n"
        "```yaml\nREVIEW_REPORT:\n  verdict: FAIL\n```\n"
    )
    assert pse._find_review_report_block(text) == "REVIEW_REPORT:\n  verdict: PASS"


# ---------------------------------------------------------------------------
# Diagnostic retention (`Q-334`, Phase 314)
#
# The hook fires on every sub-agent stop and writes a diagnostic for every
# non-participant, and nothing reclaimed them: 6,735 diagnostics against 79
# real envelopes at one consumer, 481 per active day.
#
# `test_a_parsed_envelope_is_never_reclaimed_at_any_age` is the load-bearing
# one. It is not a hypothetical boundary: measured on that same directory, a
# 7-day sweep that did not discriminate would have destroyed 56 of the 79
# envelopes, because envelopes outlive diagnostics by design.
# ---------------------------------------------------------------------------

def _age(path, days):
    """Backdate a file's mtime by `days`."""
    import os as _os
    old = _os.stat(path)
    when = old.st_mtime - days * 86400
    _os.utime(path, (when, when))


def _diag_dir(tmp_path):
    d = tmp_path / pse.ENVELOPES_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_a_stale_diagnostic_is_reclaimed(tmp_path):
    d = _diag_dir(tmp_path)
    stale = d / "_unparseable_sess_agent.json"
    stale.write_text("{}", encoding="utf-8")
    _age(stale, pse.DIAGNOSTIC_RETENTION_DAYS + 1)
    assert pse._reclaim_stale_diagnostics(str(d)) == 1
    assert not stale.exists()


def test_a_fresh_diagnostic_is_kept(tmp_path):
    """The retention floor is what keeps `claim-task` Step 8 executable.

    That step tells the orchestrator to open `_unparseable_*.json` before
    concluding an envelope is absent, so a diagnostic from the run in progress
    must survive the sweep that the same run triggers.
    """
    d = _diag_dir(tmp_path)
    fresh = d / "_unparseable_sess_agent.json"
    fresh.write_text("{}", encoding="utf-8")
    assert pse._reclaim_stale_diagnostics(str(d)) == 0
    assert fresh.exists()


def test_a_parsed_envelope_is_never_reclaimed_at_any_age(tmp_path):
    """The 56-of-79 near-miss. Envelopes are reaped by the close, not by age."""
    d = _diag_dir(tmp_path)
    names = ["TASK-1.json", "TASK-2.exec.json", "BATCH-538.plan.json",
             "DATA-NO-PHASE-KEY.json", "TASK-3.review.json"]
    for n in names:
        f = d / n
        f.write_text("{}", encoding="utf-8")
        _age(f, 365)
    assert pse._reclaim_stale_diagnostics(str(d)) == 0
    for n in names:
        assert (d / n).exists(), n


def test_only_the_unparseable_prefix_and_json_suffix_are_candidates(tmp_path):
    d = _diag_dir(tmp_path)
    # Round finding F1: the first version of this list had NO name that was
    # simultaneously `_`-prefixed and `.json`-suffixed, so widening the prefix
    # to `_`, to `_unparseable` (no trailing underscore), or to a
    # case-insensitive compare all passed. Each of the first three below is a
    # counterexample to one of those widenings; `_UNPARSEABLE_X.json` also
    # pins that the compare stays case-SENSITIVE.
    keep = ["_unparseable_sess_agent.txt", "unparseable_sess_agent.json",
            "x_unparseable_sess.json", "README", "_unparseable_",
            "_notes.json", "_UNPARSEABLE_X.json", "_unparseableX.json",
            "_unparseable_sessjson"]
    for n in keep:
        f = d / n
        f.write_text("x", encoding="utf-8")
        _age(f, 365)
    assert pse._reclaim_stale_diagnostics(str(d)) == 0
    for n in keep:
        assert (d / n).exists(), n


def test_a_missing_directory_returns_zero_and_does_not_raise(tmp_path):
    assert pse._reclaim_stale_diagnostics(str(tmp_path / "nope")) == 0


def test_an_unlinkable_diagnostic_is_skipped_not_fatal(tmp_path, monkeypatch):
    """A reclaim failure must never cost the caller the envelope write."""
    d = _diag_dir(tmp_path)
    for n in ("_unparseable_a_a.json", "_unparseable_b_b.json"):
        f = d / n
        f.write_text("{}", encoding="utf-8")
        _age(f, 365)
    real = pse.os.unlink
    calls = {"n": 0}

    def flaky(path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("permission denied")
        return real(path)

    monkeypatch.setattr(pse.os, "unlink", flaky)
    assert pse._reclaim_stale_diagnostics(str(d)) == 1


def test_main_sweeps_on_the_SUCCESS_path_not_only_the_diagnostic_path(
    monkeypatch, tmp_path
):
    """A repo whose agents all comply must still reclaim its old diagnostics.

    Siting the sweep on the diagnostic write would mean the directory stops
    draining exactly when the agents start behaving.
    """
    # Round finding F2: this test used to pass `cwd == tmp_path`, the same path
    # `_main_repo_root` was stubbed to return, so it could not tell WHICH of the
    # two the sweep targets. The hook's primary deployment is a sub-agent in a
    # worktree, where they differ — and a sweep keyed to `cwd` is a silent no-op
    # for every such run. `cwd` is now a distinct directory.
    elsewhere = tmp_path / "worktree-cwd"
    elsewhere.mkdir()
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    d = _diag_dir(tmp_path)
    stale = d / "_unparseable_old_old.json"
    stale.write_text("{}", encoding="utf-8")
    _age(stale, pse.DIAGNOSTIC_RETENTION_DAYS + 1)
    rc = _run_main_with_stdin(monkeypatch, {
        "last_assistant_message": (
            "done\n\n```yaml\nTASK: FEAT-0123\nSTATUS: EXECUTED\n"
            "WORKTREE: /tmp/wt\nBRANCH: feat/0123\n```\n"
        ),
        "session_id": "sess-1",
        "agent_id": "agent-1",
        "cwd": str(elsewhere),
    })
    assert not (elsewhere / pse.ENVELOPES_DIR).exists()
    assert rc == 0
    assert (d / "FEAT-0123.json").exists()
    assert not stale.exists()


def test_a_fresh_file_does_not_stop_the_sweep(tmp_path, monkeypatch):
    """The `continue`/`break` distinction, which the other tests cannot see.

    Every test above holds one kind of file at a time, so a sweep that
    ABANDONED the directory at the first fresh entry passed all of them. On a
    live directory the two kinds are interleaved — 3,677 fresh against 3,058
    stale at the consumer measured — so an early exit reclaims nearly nothing
    while still reporting a plausible count. The listing order is pinned
    fresh-first rather than left to `os.listdir`, because a mutation this test
    exists to catch must not be able to survive on a lucky ordering.
    """
    d = _diag_dir(tmp_path)
    fresh = d / "_unparseable_aaa_fresh.json"
    fresh.write_text("{}", encoding="utf-8")
    stale = []
    for i in range(3):
        f = d / f"_unparseable_zzz{i}_stale.json"
        f.write_text("{}", encoding="utf-8")
        _age(f, pse.DIAGNOSTIC_RETENTION_DAYS + 1)
        stale.append(f)
    order = [fresh.name] + [f.name for f in stale]
    monkeypatch.setattr(pse.os, "listdir", lambda p: list(order))
    assert pse._reclaim_stale_diagnostics(str(d)) == 3
    assert fresh.exists()
    for f in stale:
        assert not f.exists(), f.name


def test_a_file_exactly_at_the_cutoff_is_kept(tmp_path, monkeypatch):
    """`>=` not `>`: the boundary is inclusive, so the cap never reclaims a
    file the retention window still covers. Time is frozen, because the
    boundary is otherwise not constructible — `time.time()` moves between
    setting the mtime and reading it.
    """
    d = _diag_dir(tmp_path)
    now = 1_700_000_000.0
    monkeypatch.setattr(pse.time, "time", lambda: now)
    cutoff = now - pse.DIAGNOSTIC_RETENTION_DAYS * 86400
    at = d / "_unparseable_at_cutoff.json"
    at.write_text("{}", encoding="utf-8")
    pse.os.utime(at, (cutoff, cutoff))
    just_under = d / "_unparseable_just_under.json"
    just_under.write_text("{}", encoding="utf-8")
    pse.os.utime(just_under, (cutoff - 1, cutoff - 1))
    assert pse._reclaim_stale_diagnostics(str(d)) == 1
    assert at.exists()
    assert not just_under.exists()


def test_no_valid_task_id_can_produce_a_name_the_sweep_would_delete():
    """The 56-of-79 property proved by construction, not by sampling.

    The other retention tests assert the sweep spares the envelope names that
    exist today. This one asserts no envelope name the writer is CAPABLE of
    producing can match the delete predicate, which is the claim that has to
    hold for the cap to be safe against a task id nobody has coined yet.

    Two independent barriers, and the test fails if either is relaxed:
    `_TASK_ID_SHAPE_RE` admits only `^[A-Z]...`, so an id cannot begin with an
    underscore; and `_sanitize_for_filename` strips leading `._` regardless.
    """
    hostile = [
        "_unparseable_x", "__unparseable_", "_UNPARSEABLE_A", "_unparseable_A-1",
        "UNPARSEABLE-1", "_unparseable_A.json", "..//_unparseable_evil",
        ".._unparseable_", "_" * 40 + "unparseable_Z",
    ]
    for task_id in hostile:
        name = pse._sanitize_for_filename(task_id, "") + ".json"
        assert not name.startswith("_unparseable_"), (task_id, name)
        if pse._TASK_ID_SHAPE_RE.match(task_id):
            assert not task_id.startswith("_"), task_id
    # Barrier 1 stated as its own assertion, so relaxing the regex reddens here
    # rather than silently widening what the sweep may delete.
    assert not pse._TASK_ID_SHAPE_RE.match("_ABC")
    # Barrier 2, likewise.
    assert not pse._sanitize_for_filename("_unparseable_A", "").startswith("_")


def test_main_sweeps_on_the_DIAGNOSTIC_path_too(monkeypatch, tmp_path):
    """The mirror of the success-path test, and the direction that carries the
    traffic. Round finding HIGH-2.

    `main()`'s comment claims the sweep is sited so "no early return below can
    skip it". Only the success arm was pinned, so moving the call to sit after
    `_write_json(out_path, payload)` — reachable only when an envelope parses —
    left all 123 tests green while the sweep fired on about 1% of real hook
    invocations: measured on the live consumer, 6,780 diagnostic-arm stops
    against 81 envelope-arm. That mutation reinstates most of `Q-334` with the
    suite green and the comment still asserting the property. This test is the
    other half of the pair.
    """
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    d = _diag_dir(tmp_path)
    stale = d / "_unparseable_old_old.json"
    stale.write_text("{}", encoding="utf-8")
    _age(stale, pse.DIAGNOSTIC_RETENTION_DAYS + 1)
    rc = _run_main_with_stdin(monkeypatch, {
        "last_assistant_message": "I finished. No envelope here.",
        "session_id": "sess-x",
        "agent_id": "agent-x",
        "cwd": str(tmp_path),
    })
    assert rc == 0
    # the run wrote its own diagnostic ...
    assert (d / "_unparseable_sess-x_agent-x.json").exists()
    # ... and still reclaimed the stale one on the way through.
    assert not stale.exists()


def test_the_sweep_walks_the_WHOLE_listing(tmp_path, monkeypatch):
    """Round finding F3: `names[:100]` survived the first battery.

    `test_a_fresh_file_does_not_stop_the_sweep` asserts one fresh entry does
    not abort the walk, over a four-file fixture — so no truncation bound of
    four or more is detectable by it. The property actually wanted is that the
    sweep visits every entry, and on the live consumer the listing is ~6,800.
    A 200-file population makes any plausible slice or early bound visible.
    """
    d = _diag_dir(tmp_path)
    stale = []
    for i in range(200):
        f = d / f"_unparseable_s{i:04d}_a.json"
        f.write_text("{}", encoding="utf-8")
        _age(f, pse.DIAGNOSTIC_RETENTION_DAYS + 1)
        stale.append(f)
    assert pse._reclaim_stale_diagnostics(str(d)) == 200
    assert [f.name for f in stale if f.exists()] == []


def test_the_sweep_unlinks_the_NAME_not_the_symlink_target(tmp_path):
    """Round finding F4: `os.unlink(os.path.realpath(path))` survived.

    Shipped behaviour is right — `os.unlink` does not follow a symlink — but
    "never delete a parsed envelope" was not pinned against the one-line edit
    that resolves the path first. A diagnostic-named symlink pointing at a real
    envelope is the shape that makes the difference observable.
    """
    d = _diag_dir(tmp_path)
    envelope = d / "FEAT-0001.json"
    envelope.write_text('{"task_id": "FEAT-0001"}', encoding="utf-8")
    _age(envelope, 365)
    link = d / "_unparseable_link_a.json"
    link.symlink_to(envelope)
    _age(link, pse.DIAGNOSTIC_RETENTION_DAYS + 1)
    assert pse._reclaim_stale_diagnostics(str(d)) == 1
    assert not link.exists() and not link.is_symlink()
    assert envelope.exists(), "the symlink's TARGET must survive"
    assert envelope.read_text(encoding="utf-8") == '{"task_id": "FEAT-0001"}'


def test_the_retention_value_is_exactly_the_one_the_docs_publish():
    """Round finding F5: `7 -> 7.9` survived, because every other test
    parameterises off the constant and so moves with it.

    The value is not a free tuning knob: `WORKFLOW.md` § 8.4 and the artifacts
    table both publish "7" to consumers, and the module docstring points at
    this constant by name. Drift here silently falsifies shipped documentation,
    which is the class this phase's own round spent most of its findings on.
    """
    assert pse.DIAGNOSTIC_RETENTION_DAYS == 7
    assert isinstance(pse.DIAGNOSTIC_RETENTION_DAYS, int)


# ---------------------------------------------------------------------------
# Phase 319 — the handback envelope (`Q-552`)
#
# An agent that hands its envelope back through the harness's handback tool
# leaves a non-empty one-line SUMMARY in `last_assistant_message`, so the old
# `if not last_message` gate skipped the transcript fallback entirely, and the
# old text-blocks-only join could not have seen the envelope anyway. Both gates
# had to open together; neither alone can execute.
#
# The THIRD condition is the one no filing named, and it is measured, not
# argued: on all three live sub-agent transcripts the agent produced a text
# one-liner AFTER its handback, so the reader's last-wins rule would have
# returned the one-liner and discarded the envelope even with the block filter
# widened. Selection had to become envelope-first. `test_a_text_block_after_the
# _handback_does_not_win` is that arm; strip it and the widening ships inert.
# ---------------------------------------------------------------------------


def _handback_entry(message: str, name: str = "SubagentHandback") -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": name, "input": {"message": message}},
    ]}}


def _text_entry(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "text", "text": text},
    ]}}


_ENVELOPE = (
    "Work delivered.\n\n"
    "```yaml\n"
    "TASK: OPS-THING\n"
    "PHASE: plan\n"
    "STATUS: EXECUTED\n"
    "WORKTREE: /tmp/wt\n"
    "BRANCH: ops/thing\n"
    "ERROR: none\n"
    "```\n"
)


def test_an_envelope_handed_back_through_the_tool_is_read(tmp_path):
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, [_handback_entry(_ENVELOPE)])
    got = pse._last_assistant_message_from_transcript(str(transcript))
    assert pse._find_envelope_block(got) is not None


def test_a_text_block_after_the_handback_does_not_win(tmp_path):
    """The measured live shape: handback, THEN a one-line summary.

    Strip the envelope-first selection and this returns the summary — which is
    what the reader did before Phase 319, and why widening the block filter
    alone would have recovered nothing. All three live transcripts had this
    ordering, so it is the dominant case and not an edge one.
    """
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, [
        _handback_entry(_ENVELOPE),
        _text_entry("Plan delivered to the orchestrator."),
    ])
    got = pse._last_assistant_message_from_transcript(str(transcript))
    assert pse._find_envelope_block(got) is not None
    assert got != "Plan delivered to the orchestrator."


def test_a_tool_use_that_is_not_the_handback_tool_is_ignored(tmp_path):
    """The exact-name predicate — the arm that would widen if it were loosened.

    Matching any tool_use name was measured and rejected. The hazard is not a
    `Bash` call — its input has `command`/`description` and no `message` key, so
    it is invisible to `_handback_message` either way; an earlier draft of this
    docstring said otherwise and this phase's own round refuted it by running the
    counterfactual. The real population is tools that DO carry a `message`
    argument: a census of this machine's transcripts finds `SubagentHandback` 333,
    **`SendMessage` 234** and `PushNotification` 5. Dropping the name check adopts
    a `SendMessage` payload as the agent's result.

    This asserts the rejection for a differently-NAMED tool that carries a
    message; `test_a_near_miss_tool_name_is_not_treated_as_a_handback` covers the
    loosenings, which this test alone could not see.
    """
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash",
             "input": {"command": "grep -n 'TASK:' f", "description": "d"}},
        ]}},
        _handback_entry(_ENVELOPE, name="SomeOtherTool"),
        _text_entry("summary only"),
    ])
    assert pse._last_assistant_message_from_transcript(str(transcript)) == "summary only"


def test_a_handback_without_an_envelope_does_not_displace_the_last_text(tmp_path):
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, [
        _handback_entry("just a prose handback, no envelope"),
        _text_entry("the last text"),
    ])
    assert pse._last_assistant_message_from_transcript(str(transcript)) == "the last text"


def test_the_last_envelope_bearing_handback_wins(tmp_path):
    transcript = tmp_path / "agent.jsonl"
    second = _ENVELOPE.replace("OPS-THING", "OPS-SECOND")
    _write_transcript(transcript, [
        _handback_entry(_ENVELOPE),
        _handback_entry(second),
    ])
    got = pse._last_assistant_message_from_transcript(str(transcript))
    assert "OPS-SECOND" in (pse._find_envelope_block(got) or "")


@pytest.mark.parametrize("payload", [
    {"message": None}, {"message": ""}, {"message": "   "}, {"notmessage": "x"}, "notadict",
])
def test_a_malformed_handback_input_is_skipped_not_fatal(tmp_path, payload):
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "SubagentHandback", "input": payload},
        ]}},
        _text_entry("still here"),
    ])
    assert pse._last_assistant_message_from_transcript(str(transcript)) == "still here"


def test_no_envelope_anywhere_returns_the_last_text_exactly_as_before(tmp_path):
    """The pre-Phase-319 contract, pinned: a transcript this function already
    read correctly must still read the same way."""
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, [
        _text_entry("working on it"),
        _text_entry("final answer"),
    ])
    assert pse._last_assistant_message_from_transcript(str(transcript)) == "final answer"


# --- gate 1, in main() -----------------------------------------------------


def test_a_nonempty_envelopeless_hook_message_still_reaches_the_transcript(
    monkeypatch, tmp_path
):
    """Gate 1's predicate: "no envelope here", not "nothing here".

    This is the reported defect end to end. Revert the condition to
    `if not last_message` and this writes `_unparseable_*.json` instead.
    """
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, [
        _handback_entry(_ENVELOPE),
        _text_entry("Plan delivered to the orchestrator."),
    ])
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, {
        "last_assistant_message": "Plan delivered to the orchestrator.",
        "session_id": "sess-h", "agent_id": "agent-h",
        "agent_transcript_path": str(transcript), "cwd": str(tmp_path),
    })
    assert rc == 0
    out = tmp_path / pse.ENVELOPES_DIR / "OPS-THING.plan.json"
    assert out.exists(), "the handback envelope was not recovered"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["parsed"] is True
    assert payload["task_id"] == "OPS-THING"
    assert payload["message_source"] == "agent_transcript"
    assert not list((tmp_path / pse.ENVELOPES_DIR).glob("_unparseable_*.json"))


def test_a_hook_message_that_already_parses_is_never_replaced(monkeypatch, tmp_path):
    """One-directional: the transcript is adopted only to ADD an envelope.

    The transcript here carries a DIFFERENT envelope. If the gate ever starts
    preferring it, this fails on `task_id` rather than passing quietly.
    """
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, [
        _handback_entry(_ENVELOPE.replace("OPS-THING", "OPS-FROM-TRANSCRIPT"))
    ])
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, {
        "last_assistant_message": _ENVELOPE,
        "session_id": "s", "agent_id": "a",
        "agent_transcript_path": str(transcript), "cwd": str(tmp_path),
    })
    assert rc == 0
    assert (tmp_path / pse.ENVELOPES_DIR / "OPS-THING.plan.json").exists()
    assert not (tmp_path / pse.ENVELOPES_DIR / "OPS-FROM-TRANSCRIPT.plan.json").exists()
    payload = json.loads(
        (tmp_path / pse.ENVELOPES_DIR / "OPS-THING.plan.json").read_text(encoding="utf-8")
    )
    assert payload["message_source"] == "hook_input"


def test_the_transcript_is_not_even_read_when_the_hook_message_parses(
    monkeypatch, tmp_path
):
    """No cost added to the healthy path — the arm is the early skip."""
    calls = []
    monkeypatch.setattr(
        pse, "_last_assistant_message_from_transcript",
        lambda path: calls.append(path) or "",
    )
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, {
        "last_assistant_message": _ENVELOPE,
        "session_id": "s", "agent_id": "a",
        "agent_transcript_path": "/some/transcript.jsonl", "cwd": str(tmp_path),
    })
    assert rc == 0
    assert calls == [], f"transcript was read on the healthy path: {calls}"


def test_no_envelope_in_either_source_keeps_todays_diagnostic(monkeypatch, tmp_path):
    """The widening must not change the diagnostic a no-envelope run writes."""
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, [_text_entry("nothing useful")])
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, {
        "last_assistant_message": "I finished. No envelope here.",
        "session_id": "sess-n", "agent_id": "agent-n",
        "agent_transcript_path": str(transcript), "cwd": str(tmp_path),
    })
    assert rc == 0
    diags = list((tmp_path / pse.ENVELOPES_DIR).glob("_unparseable_*.json"))
    assert len(diags) == 1
    diag = json.loads(diags[0].read_text(encoding="utf-8"))
    assert diag["parsed"] is False
    assert diag["message_source"] == "hook_input"
    assert "No envelope here." in diag["last_assistant_message_excerpt"]


def test_the_handback_tool_name_is_pinned():
    """A rename must be a deliberate edit, not a silent drift."""
    assert pse._HANDBACK_TOOL_NAME == "SubagentHandback"


# --- three arms the Phase 319 author-side battery found unguarded -----------
# M7, M8 and M10 survived the first cut of the battery above. Each is a real
# predicate with no test behind it; they are here because the author's own pass
# found them, not a reviewer's.


def test_an_empty_hook_message_with_no_envelope_anywhere_still_diagnoses(
    monkeypatch, tmp_path
):
    """M7. Delete gate 1's `elif not last_message` arm and the ENVELOPE case
    still passes — what silently disappears is the diagnostic on the old
    2.0.42–2.1.46 fallback path, because `last_message` stays empty and main()
    returns 0 before writing anything."""
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, [_text_entry("no envelope, just prose")])
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, {
        "last_assistant_message": "",
        "session_id": "sess-e", "agent_id": "agent-e",
        "agent_transcript_path": str(transcript), "cwd": str(tmp_path),
    })
    assert rc == 0
    diags = list((tmp_path / pse.ENVELOPES_DIR).glob("_unparseable_*.json"))
    assert len(diags) == 1, "the old fallback path lost its diagnostic"
    diag = json.loads(diags[0].read_text(encoding="utf-8"))
    assert diag["message_source"] == "agent_transcript"
    assert "no envelope, just prose" in diag["last_assistant_message_excerpt"]


def test_two_handbacks_in_ONE_entry_resolve_last_wins(tmp_path):
    """M8. The last-wins rule INSIDE `_handback_message` — the test above puts
    its two handbacks in separate entries, which the outer loop resolves, so it
    cannot see this arm at all."""
    second = _ENVELOPE.replace("OPS-THING", "OPS-SECOND")
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "SubagentHandback",
             "input": {"message": _ENVELOPE}},
            {"type": "tool_use", "name": "SubagentHandback",
             "input": {"message": second}},
        ]}},
    ])
    got = pse._last_assistant_message_from_transcript(str(transcript))
    assert "OPS-SECOND" in (pse._find_envelope_block(got) or "")


@pytest.mark.parametrize("message", [123, {"nested": "dict"}, ["a", "list"], True])
def test_a_truthy_nonstring_handback_message_is_skipped(tmp_path, message):
    """M10. `{"message": None}` is falsy, so a `message and str(message)` rewrite
    passes the None case and still starts coercing dicts and ints into the
    envelope parser. A truthy non-string is what actually separates them."""
    transcript = tmp_path / "agent.jsonl"
    _write_transcript(transcript, [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "SubagentHandback",
             "input": {"message": message}},
        ]}},
        _text_entry("still here"),
    ])
    assert pse._last_assistant_message_from_transcript(str(transcript)) == "still here"


# --- `Q-553`: the shipped skill bodies must carry the real bound ------------
# Phase 314 capped retention and left two skill bodies describing the old
# unbounded behaviour. Neither was flatly FALSE — the files do persist across
# runs — which is why nothing caught it and why a "is this sentence wrong?"
# check would not have either. These pin the surfaces to the CONSTANT, so the
# next change to the cap reddens the skills that publish it.

_AUTO_BUILD_SKILL = _REPO_ROOT / "core/skills/auto-build/SKILL.md"
_CLAIM_REFERENCE = _REPO_ROOT / "core/skills/claim-task/REFERENCE.md"


def _surfaces_naming_the_diagnostics() -> list[Path]:
    """Every shipped file that names the diagnostics — DERIVED, not listed.

    Round finding M-i: the first cut parametrised two hard-coded paths while five
    files in `core/` carry the instruction, so a sixth surface picking it up would
    have been invisible. That is the "roster that reads as coverage" class this
    repo has already paid for once (Phase 204)."""
    root = _REPO_ROOT / "core"
    return sorted(
        f for f in root.rglob("*")
        if f.is_file() and f.suffix in {".md", ".py"}
        and "_unparseable_" in f.read_text(encoding="utf-8", errors="replace")
    )


def test_the_diagnostic_surface_population_is_not_empty():
    """Non-vacuity: a derived roster that derives nothing passes by agreeing about
    nothing, which is the shape the guard above exists to avoid."""
    found = _surfaces_naming_the_diagnostics()
    assert len(found) >= 5, f"only {len(found)} surfaces name the diagnostics: {found}"
    names = {f.name for f in found}
    assert {"SKILL.md", "WORKFLOW.md", "parse_subagent_envelope.py"} <= names


@pytest.mark.parametrize(
    "path", _surfaces_naming_the_diagnostics(),
    ids=lambda p: str(p.relative_to(_REPO_ROOT)),
)
def test_a_surface_that_mentions_the_diagnostics_states_the_retention_bound(path):
    body = path.read_text(encoding="utf-8", errors="replace")
    # Both spellings are DERIVED from the constant, not listed: the first run of
    # this derived roster failed on `REFERENCE.md`, which states the bound as
    # "7-day" rather than "7 days". That was the predicate being too narrow, not
    # a real gap — the same wording-pin trap this section is about.
    n = pse.DIAGNOSTIC_RETENTION_DAYS
    stated = any(form in body for form in (f"{n} days", f"{n}-day", "DIAGNOSTIC_RETENTION_DAYS"))
    assert stated, (
        f"{path.relative_to(_REPO_ROOT)} describes the diagnostic mailbox without "
        f"stating the {pse.DIAGNOSTIC_RETENTION_DAYS}-day bound the hook enforces"
    )


def test_the_claim_skill_does_not_promise_indefinite_retention():
    """The exact `Q-553` wording: "from last week" WAS the boundary, so the
    step's own worked example sat on the edge of what survives."""
    body = _CLAIM_SKILL.read_text(encoding="utf-8")
    assert "from last week" not in body, (
        "the worked example is back, and it names exactly the retention boundary"
    )


def test_the_claim_skill_tells_the_runner_what_an_ABSENT_diagnostic_means():
    """The operational half, and the only part that earns a line in the runner.

    A bound the runner cannot act on is rationale; the actionable consequence is
    that absence stopped being evidence. Rationale for this lives in REFERENCE.md
    (dimension 10), which this asserts is where it went."""
    body = _CLAIM_SKILL.read_text(encoding="utf-8")
    assert "absence is not evidence" in body
    ref = _CLAIM_REFERENCE.read_text(encoding="utf-8")
    assert "Q-553" in ref, "the rationale did not reach the editor reference"
    # Round finding H3 (Q6/Q7): `"Q-553" in ref` was satisfied by a one-line stub,
    # so deleting the entire 33-line rationale — the dimension-10 half of the
    # phase — left the guard green. The section must carry actual rationale.
    section = ref.split("## Step 8 — the diagnostic mailbox is bounded")
    assert len(section) == 2, "the Step 8 rationale section is gone or renamed"
    body = section[1].split("\n## ")[0]
    assert len(body) > 1200, (
        f"the Step 8 rationale is {len(body)} chars — a stub, not the rationale "
        f"dimension 10 requires be authored here rather than in the runner"
    )
    for required in ("What it protects", "What its loss or softening would change",
                     "Provenance"):
        assert required in body, f"the Step 8 rationale no longer states: {required}"


# ---------------------------------------------------------------------------
# Phase 319's own adversarial round — the guards lens found 27 holes and the
# claims lens two HIGH. These are the arms that were missing.
#
# The structural diagnosis (guards lens M-h) is worth stating once: the first
# cut's battery only ever REMOVED a predicate, so every guard it validated fires
# on deletion and none fires on LOOSENING. Eleven of the phase's own tests passed
# against a tree with `_handback_message` absent entirely. The rows below are
# loosening-shaped on purpose.
# ---------------------------------------------------------------------------


def test_a_torn_multibyte_tail_does_not_crash_the_hook(monkeypatch, tmp_path):
    """Round HIGH-1. The widening put this read on the DOMINANT path, so a
    transcript whose tail is still flushing stopped being a rare case.

    Pre-319 this wrote `_unparseable_*.json`; the phase's first cut exited 1 with
    a `UnicodeDecodeError` traceback and wrote nothing — a regression in exactly
    the mailbox `Q-553` is about."""
    line = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "done —"}]}},
        ensure_ascii=False,
    ).encode("utf-8")
    transcript = tmp_path / "torn.jsonl"
    transcript.write_bytes(line[: line.rfind("—".encode("utf-8")) + 2])
    with pytest.raises(UnicodeDecodeError):
        transcript.read_bytes().decode("utf-8")      # the fixture really is torn
    assert pse._last_assistant_message_from_transcript(str(transcript)) == ""

    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, {
        "last_assistant_message": "Plan delivered.", "session_id": "s", "agent_id": "a",
        "agent_transcript_path": str(transcript), "cwd": str(tmp_path),
    })
    assert rc == 0
    assert len(list((tmp_path / pse.ENVELOPES_DIR).glob("_unparseable_*.json"))) == 1


def test_a_non_string_text_value_does_not_crash_the_hook(tmp_path):
    """Round HIGH-1, second path: `TypeError: sequence item 0: expected str`."""
    transcript = tmp_path / "badtext.jsonl"
    _write_transcript(transcript, [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": 123}]}},
        _text_entry("real text"),
    ])
    assert pse._last_assistant_message_from_transcript(str(transcript)) == "real text"


def test_an_envelope_already_read_survives_a_torn_tail(tmp_path):
    """The broad catch returns what was recovered, not "" — an envelope read from
    line 1 is not made wrong by line 900 being torn."""
    line = json.dumps(
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "x —"}]}},
        ensure_ascii=False,
    ).encode("utf-8")
    transcript = tmp_path / "partial.jsonl"
    transcript.write_bytes(
        (json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "SubagentHandback", "input": {"message": _ENVELOPE}},
        ]}}) + "\n").encode("utf-8")
        + line[: line.rfind("—".encode("utf-8")) + 2]
    )
    got = pse._last_assistant_message_from_transcript(str(transcript))
    assert pse._find_envelope_block(got) is not None


@pytest.mark.parametrize("name", [
    "subagenthandback",          # case-loosened
    "MySubagentHandbackShim",    # substring-loosened
    "SubagentStopHook",          # prefix-loosened
    "Handback",                  # allowlist-loosened
    "SendMessage",               # a REAL tool that carries a `message` argument
    "PushNotification",          # ditto
])
def test_a_near_miss_tool_name_is_not_treated_as_a_handback(tmp_path, name):
    """Round HIGH-2. The first cut only caught DELETING the name check; five
    distinct loosenings walked through because the fixture used two names that
    every loosening still rejects.

    `SendMessage` and `PushNotification` are not hypothetical: a census of this
    machine's transcripts finds 234 and 5 `tool_use` blocks whose input carries a
    `message` key, against 333 real handbacks. Loosening the predicate adopts
    them."""
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, [
        _handback_entry(_ENVELOPE, name=name),
        _text_entry("summary only"),
    ])
    assert pse._last_assistant_message_from_transcript(str(transcript)) == "summary only"


def test_a_tool_use_block_with_no_name_is_not_a_handback(tmp_path):
    """Round HIGH-2, sharpest form: `block.get("name", _HANDBACK_TOOL_NAME)`
    makes a nameless block match, which is the "match some other tool's input"
    outcome the module comment exists to forbid."""
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "input": {"message": _ENVELOPE}},
        ]}},
        _text_entry("summary only"),
    ])
    assert pse._last_assistant_message_from_transcript(str(transcript)) == "summary only"


def test_a_blank_handback_does_not_shadow_a_real_one_in_the_same_entry(tmp_path):
    """Round MEDIUM-a. Dropping `.strip()` from the truthiness test re-opens the
    exact defect this phase exists to fix, in 15 characters."""
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "SubagentHandback", "input": {"message": _ENVELOPE}},
            {"type": "tool_use", "name": "SubagentHandback", "input": {"message": "   "}},
        ]}},
        _text_entry("summary only"),
    ])
    got = pse._last_assistant_message_from_transcript(str(transcript))
    assert pse._find_envelope_block(got) is not None


def test_a_non_dict_block_in_the_content_list_is_skipped(tmp_path):
    """Round MEDIUM-b. The malformed-input parametrisation covers `input` shapes,
    never BLOCK shapes, so dropping `isinstance(block, dict)` raised
    `AttributeError` unguarded."""
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, [
        {"type": "assistant", "message": {"content": [
            "a bare string in the content list",
            {"type": "tool_use", "name": "SubagentHandback", "input": {"message": _ENVELOPE}},
        ]}},
    ])
    got = pse._last_assistant_message_from_transcript(str(transcript))
    assert pse._find_envelope_block(got) is not None


def test_a_non_assistant_entry_is_never_read_as_the_agents_message(tmp_path):
    """Round MEDIUM-c. Real transcripts interleave user entries; dropping the
    type filter silently returns one."""
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, [
        _text_entry("final answer"),
        {"type": "user", "message": {"content": [{"type": "text", "text": "user noise"}]}},
    ])
    assert pse._last_assistant_message_from_transcript(str(transcript)) == "final answer"


def test_the_envelope_check_is_a_real_parse_not_a_substring_test(tmp_path):
    """Round MEDIUM-e. Downgrading `_find_envelope_block(...) is not None` to
    `"TASK:" in handback` adopts a handback that merely MENTIONS the token — the
    same any-match failure the exact-name pin exists to avoid, one predicate in."""
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, [
        _handback_entry("I grepped for TASK: and STATUS: and found none."),
        _text_entry("the last text"),
    ])
    assert pse._last_assistant_message_from_transcript(str(transcript)) == "the last text"


def test_a_long_hook_summary_still_reaches_the_transcript(monkeypatch, tmp_path):
    """Round MEDIUM-f. A length short-circuit on gate 1 reopens the reported
    defect for any agent whose summary runs long, with every other test green."""
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, [_handback_entry(_ENVELOPE)])
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, {
        "last_assistant_message": "summary. " * 400,      # 3,600 chars, no envelope
        "session_id": "s", "agent_id": "a",
        "agent_transcript_path": str(transcript), "cwd": str(tmp_path),
    })
    assert rc == 0
    assert (tmp_path / pse.ENVELOPES_DIR / "OPS-THING.plan.json").exists()


def test_a_handback_is_preferred_over_a_LATER_text_envelope(tmp_path):
    """Round MEDIUM-d. The ordering rule was unpinned in BOTH directions, and
    reversing it left all tests green.

    This is a case pre-319 read differently — it returned the later text envelope
    — so it is the one shape where the widening ALTERS rather than only adds. The
    handback wins deliberately: it is the harness's final-handback call, while a
    later text block is ordinary chat after the fact. Recorded rather than
    claimed away; `PHASE_LOG.md` states the exception."""
    later = _ENVELOPE.replace("OPS-THING", "OPS-LATER")
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, [_handback_entry(_ENVELOPE), _text_entry(later)])
    got = pse._last_assistant_message_from_transcript(str(transcript))
    assert "OPS-THING" in (pse._find_envelope_block(got) or "")


# --- the quotation forgery path (round, execution lens HIGH) ----------------
# `Q-561` and this phase's first record both asserted that a handback is a
# structural signal "a quote cannot forge". The round falsified that with a
# transcript this repo's own review practice produced: a Sysop review lens,
# holding no claim, quoted the envelope it was reviewing, and the first cut
# adopted it and would have written that claim's slot.


def test_a_handback_that_QUOTES_an_envelope_and_keeps_talking_is_not_a_result():
    """The live shape, reduced: evidence, the quoted envelope, then more report."""
    quoting = (
        "## Finding 3 — the executor's envelope\n\nIt reported:\n\n"
        + _ENVELOPE
        + "\n\n" + ("...and here is why that is wrong. " * 40)
    )
    assert pse._find_envelope_block(quoting) is not None, "fixture must contain an envelope"
    assert pse._envelope_is_this_agents_result(quoting) is False


def test_a_handback_that_ENDS_with_its_envelope_is_a_result():
    assert pse._envelope_is_this_agents_result("Work delivered.\n\n" + _ENVELOPE) is True


def test_a_short_sign_off_after_the_envelope_is_still_a_result():
    """The bound is 200 chars, not 0 — 56 of 57 live handbacks end within 20 of
    their envelope, so a brief closing line must not fail closed."""
    assert pse._envelope_is_this_agents_result(_ENVELOPE + "\n\nNot pushed.\n") is True


def test_the_quotation_bound_separates_the_measured_populations():
    """The bound is not fitted to the counterexample: an order of magnitude above
    the compliant population's maximum (20) and two below the quotation (13,900)."""
    assert 20 < pse._HANDBACK_ENVELOPE_TAIL_MAX < 13_900
    assert pse._HANDBACK_ENVELOPE_TAIL_MAX == 200


def test_a_quoting_handback_does_not_reach_the_mailbox(monkeypatch, tmp_path):
    """End to end: the forged envelope must not become a claim slot."""
    quoting = "Reviewing:\n\n" + _ENVELOPE + "\n\n" + ("further analysis. " * 60)
    transcript = tmp_path / "t.jsonl"
    _write_transcript(transcript, [
        _handback_entry(quoting),
        _text_entry("Report delivered to the caller via SubagentHandback."),
    ])
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    rc = _run_main_with_stdin(monkeypatch, {
        "last_assistant_message": "Report delivered to the caller via SubagentHandback.",
        "session_id": "s", "agent_id": "a",
        "agent_transcript_path": str(transcript), "cwd": str(tmp_path),
    })
    assert rc == 0
    assert not (tmp_path / pse.ENVELOPES_DIR / "OPS-THING.plan.json").exists(), (
        "a quoted envelope was written as this agent's result"
    )
    assert len(list((tmp_path / pse.ENVELOPES_DIR).glob("_unparseable_*.json"))) == 1
