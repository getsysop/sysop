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
import re
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
    """All three spawn prompts must emit PHASE:, or their envelopes collide on
    <CLAIM_ID>.json and last-writer-wins -- the exact defect Phase 159a built
    the optional key to prevent. Step 8's deterministic read of
    <CLAIM_ID>.exec.json rests on this and on nothing else, so the emission and
    the read have to be guarded together or the pair can drift apart silently.
    """
    text = _CLAIM_SKILL.read_text(encoding="utf-8") if text is None else text
    problems = []
    for phase in ("plan", "review", "exec"):
        if not _re.search(r"^PHASE: %s$" % phase, text, _re.M):
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
    for phase in ("plan", "review", "exec"):
        text = _CLAIM_SKILL.read_text(encoding="utf-8")
        broken = text.replace("PHASE: %s" % phase, "PHASE: none", 1)
        assert broken != text, phase
        assert any(phase in p for p in phase_emission_problems(broken)), phase


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
