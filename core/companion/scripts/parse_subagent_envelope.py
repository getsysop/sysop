#!/usr/bin/env python3
"""
SubagentStop hook (Claude Code 2.1.47+ primary path; 2.0.42+ fallback path).

Reads SubagentStop hook input on stdin, extracts the YAML envelope that
Sysop's /claim-task reviewer-executor (Phase 28+29) and /auto-build
execution agent (Phase 29) emit as the LAST content of their final message,
and writes structured JSON to ``<repo>/.subagent-envelopes/<TASK_ID>.json``
so the parent skill can read JSON instead of regex-parsing free text.

Input-field provenance (verified against the Claude Code changelog,
Phase 54): ``agent_id`` + ``agent_transcript_path`` were added to
SubagentStop input in 2.0.42; ``last_assistant_message`` in 2.1.47.

Message-source chain (Phase 54). The hook prefers ``last_assistant_message``
from hook input. When that field is absent or empty (harness 2.0.42–2.1.46,
or a harness that elides it), it falls back to reading the LAST assistant
message out of the sub-agent's own JSONL transcript at
``agent_transcript_path``. When neither source yields text, the hook exits 0
and the parent skill's regex fallback handles the envelope as before.

Posture (Phase 37, revised Phase 54). Additive — the parent skill prefers
JSON when present and falls back to regex parsing of the sub-agent's return
text if the file is missing or malformed. The hooks docs now document the
SubagentStop lifecycle: the hook runs synchronously when the sub-agent
finishes (it can even block the stop via ``decision: "block"``), before the
parent receives the Agent tool's return — so the JSON file is written before
the parent reads it. The parent-side regex fallback is therefore defense in
depth (hook unregistered, file write failure), no longer a race guard.

Envelope shapes the hook parses (both /claim-task and /auto-build emit
their final envelope in this YAML shape):

  TASK: <TASK_ID>
  STATUS: EXECUTED | BLOCKED | FAILED              # /claim-task variant
  STATUS: EXECUTED | FAILED                        # /auto-build variant
  BLOCKER_QUESTION: <if BLOCKED, else "none">      # /claim-task only
  PARKED_REASON: none                              # /auto-build only
  WORKTREE: <abs path>
  BRANCH: <branch name>
  ERROR: <if FAILED, else "none">

Plus the reviewer-executor's REVIEW_REPORT YAML at the TOP of its response
(see _shared/adversarial-review.md § Reviewer-executor variant). The hook
extracts both when present.

Multi-envelope rule. If multiple fenced YAML blocks contain a ``TASK:`` /
``STATUS:`` pair, the LAST one wins — matches the sub-agent prompt's "LAST
content in your final message" instruction.

Cleanup. The parent skill deletes the JSON file after consuming it (see
/claim-task SKILL.md § Step 8 and /auto-build SKILL.md § Phase 6e). The
.subagent-envelopes/ dir is gitignored by install.sh's
ensure_runtime_gitignore() — append-if-missing on every install AND --update,
so a .gitignore that pre-dates the install still gets the entry.

Unmatched / malformed input produces an _unparseable_<session>_<agent>.json
diagnostic file (kept across runs for inspection) and exits 0 — the hook
never blocks the parent. Errors are written to stderr only when the file
itself can't be written.

See WORKFLOW.md § 8.2a (Phase 37) for the design rationale and the explicit
"fall back to regex" contract the parent skills observe.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Any


ENVELOPES_DIR = ".subagent-envelopes"

# Fenced YAML/text block. We accept the standard ```yaml ... ``` fence as
# well as a bare ``` ... ``` fence — Phase 28+29 prompt templates show the
# envelope under ```yaml but agents occasionally emit it under a bare fence.
_FENCED_BLOCK_RE = re.compile(
    r"```(?:yaml|yml)?\s*\n(.*?)\n```",
    re.DOTALL,
)

# Within a fenced block, the envelope must carry both TASK: and STATUS: to
# count. Anything else is conversational text or the REVIEW_REPORT block.
_ENVELOPE_HEAD_RE = re.compile(r"^\s*TASK\s*:", re.MULTILINE)
_STATUS_LINE_RE = re.compile(r"^\s*STATUS\s*:", re.MULTILINE)

# REVIEW_REPORT YAML at the TOP of the reviewer-executor response. The shape
# is a fenced ```yaml block whose first non-blank key is REVIEW_REPORT.
_REVIEW_REPORT_HEAD_RE = re.compile(r"^\s*REVIEW_REPORT\s*:", re.MULTILINE)

# Per-field extractors run against the located envelope block. Tolerant of
# leading whitespace; values are taken verbatim up to end-of-line.
_FIELD_RE_TEMPLATE = r"^\s*{name}\s*:\s*(.*?)\s*$"

_ENVELOPE_FIELDS = (
    "TASK",
    "STATUS",
    "WORKTREE",
    "BRANCH",
    "ERROR",
    "BLOCKER_QUESTION",
    "PARKED_REASON",
)

_FIELD_REGEXES = {
    name: re.compile(_FIELD_RE_TEMPLATE.format(name=re.escape(name)), re.MULTILINE)
    for name in _ENVELOPE_FIELDS
}

_TASK_ID_SHAPE_RE = re.compile(r"^[A-Z][A-Z0-9]*-[A-Z0-9][A-Z0-9-]*$")


def _main_repo_root(cwd: str) -> str:
    """Resolve the main repo root (handles worktrees via git-common-dir)."""
    try:
        cp = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return cwd
    if cp.returncode != 0:
        return cwd
    gcd = cp.stdout.strip()
    if not gcd:
        return cwd
    if not os.path.isabs(gcd):
        gcd = os.path.realpath(os.path.join(cwd, gcd))
    if os.path.basename(gcd) == ".git":
        return os.path.dirname(gcd)
    return gcd


def _last_assistant_message_from_transcript(path: str) -> str:
    """Best-effort read of the LAST assistant message in a JSONL transcript.

    Fallback source for harnesses that provide ``agent_transcript_path``
    (2.0.42+) but not ``last_assistant_message`` (2.1.47+). Tolerates
    missing files, non-JSON lines, and unexpected entry shapes — any
    failure returns "" so main() degrades to the parent's regex fallback.
    """
    if not path:
        return ""
    last_text = ""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict) or entry.get("type") != "assistant":
                    continue
                message = entry.get("message")
                if not isinstance(message, dict):
                    continue
                content = message.get("content")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text = "\n".join(
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    )
                else:
                    continue
                if text.strip():
                    last_text = text
    except OSError:
        return ""
    return last_text


def _find_envelope_block(text: str) -> str | None:
    """Return the body of the LAST fenced block carrying TASK: + STATUS:."""
    candidates = []
    for m in _FENCED_BLOCK_RE.finditer(text):
        body = m.group(1)
        if _ENVELOPE_HEAD_RE.search(body) and _STATUS_LINE_RE.search(body):
            candidates.append(body)
    return candidates[-1] if candidates else None


def _find_review_report_block(text: str) -> str | None:
    """Return the body of the FIRST fenced block whose top-line key is REVIEW_REPORT."""
    for m in _FENCED_BLOCK_RE.finditer(text):
        body = m.group(1)
        if _REVIEW_REPORT_HEAD_RE.search(body):
            return body
    return None


def _extract_field(block: str, name: str) -> str | None:
    m = _FIELD_REGEXES[name].search(block)
    if not m:
        return None
    value = m.group(1).strip()
    # Treat the documented "none" sentinel as null so downstream consumers
    # don't have to special-case it.
    if value.lower() == "none":
        return None
    return value


def _parse_envelope(text: str) -> dict[str, Any] | None:
    block = _find_envelope_block(text)
    if block is None:
        return None
    parsed: dict[str, Any] = {}
    for field in _ENVELOPE_FIELDS:
        parsed[field.lower()] = _extract_field(block, field)
    parsed["_raw_block"] = block
    return parsed


def _sanitize_for_filename(value: str, fallback: str) -> str:
    """Reduce arbitrary string to a safe filename component.

    No slashes, no leading dots, no nul bytes. Empty / fallback-equivalent
    inputs map to ``fallback``.
    """
    if not value:
        return fallback
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", value).strip("._")
    return cleaned or fallback


def _write_json(path: str, payload: dict[str, Any]) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        return True
    except OSError as e:
        print(f"parse_subagent_envelope: failed to write {path}: {e}", file=sys.stderr)
        return False


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return 0

    session_id = str(data.get("session_id") or "")
    agent_id = str(data.get("agent_id") or "")
    transcript_path = str(data.get("agent_transcript_path") or "")

    last_message = data.get("last_assistant_message") or ""
    message_source = "hook_input"
    if not last_message:
        last_message = _last_assistant_message_from_transcript(transcript_path)
        message_source = "agent_transcript"
    if not last_message:
        return 0

    cwd = data.get("cwd") or os.getcwd()
    repo_root = _main_repo_root(cwd)
    envelopes_dir = os.path.join(repo_root, ENVELOPES_DIR)

    envelope = _parse_envelope(last_message)
    review_report_block = _find_review_report_block(last_message)

    if envelope is None:
        # No envelope detected. Write a diagnostic file keyed by session+agent
        # so future inspection can tell what the sub-agent actually said.
        diag_name = "_unparseable_" + _sanitize_for_filename(
            session_id, "unknown-session"
        ) + "_" + _sanitize_for_filename(agent_id, "unknown-agent") + ".json"
        diag_path = os.path.join(envelopes_dir, diag_name)
        _write_json(diag_path, {
            "parsed": False,
            "reason": "no fenced YAML block with TASK: and STATUS: in last_assistant_message",
            "session_id": session_id,
            "agent_id": agent_id,
            "agent_transcript_path": transcript_path,
            "message_source": message_source,
            "last_assistant_message_excerpt": last_message[-2000:],
        })
        return 0

    task_id = envelope.get("task") or ""
    safe_task_id = _sanitize_for_filename(task_id, "")
    if not safe_task_id or not _TASK_ID_SHAPE_RE.match(task_id):
        # Envelope parsed but TASK looks corrupt — keep as diagnostic so the
        # parent skill's regex fallback still runs.
        diag_name = "_unparseable_" + _sanitize_for_filename(
            session_id, "unknown-session"
        ) + "_" + _sanitize_for_filename(agent_id, "unknown-agent") + ".json"
        diag_path = os.path.join(envelopes_dir, diag_name)
        _write_json(diag_path, {
            "parsed": True,
            "task_id_valid": False,
            "reason": f"envelope parsed but TASK field {task_id!r} does not match <PREFIX>-<ID> shape",
            "envelope": {k: v for k, v in envelope.items() if k != "_raw_block"},
            "session_id": session_id,
            "agent_id": agent_id,
            "agent_transcript_path": transcript_path,
            "message_source": message_source,
        })
        return 0

    payload: dict[str, Any] = {
        "parsed": True,
        "task_id": task_id,
        "status": envelope.get("status"),
        "worktree": envelope.get("worktree"),
        "branch": envelope.get("branch"),
        "error": envelope.get("error"),
        "blocker_question": envelope.get("blocker_question"),
        "parked_reason": envelope.get("parked_reason"),
        "review_report_raw": review_report_block,
        "session_id": session_id,
        "agent_id": agent_id,
        "agent_transcript_path": transcript_path,
        "message_source": message_source,
    }
    out_path = os.path.join(envelopes_dir, f"{safe_task_id}.json")
    _write_json(out_path, payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
