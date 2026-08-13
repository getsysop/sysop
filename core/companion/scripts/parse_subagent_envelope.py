#!/usr/bin/env python3
"""
SubagentStop hook (Claude Code 2.1.47+ primary path; 2.0.42+ fallback path).

Reads SubagentStop hook input on stdin, extracts the YAML envelope that
Sysop's /claim-task planner/reviewer/executor (Phase 171) and /auto-build
execution agent (Phase 29) emit as the LAST content of their final message,
and writes structured JSON to ``<repo>/sysop/runtime/subagent-envelopes/<TASK_ID>.json``
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
  PHASE: <stage name, optional — see below>

Output filename (Phase 159a). Envelopes are keyed by the ``TASK:`` field, so
one claim could only ever hold one envelope: a second enveloping sub-agent
under the same claim overwrote the first. The optional ``PHASE:`` field keys
the file per stage instead — ``<TASK_ID>.<phase>.json`` when present,
``<TASK_ID>.json`` when absent or set to the documented "none" sentinel. In the
absent case the *filename* is byte-identical to pre-159a; the *payload* is not —
it gains a ``"phase"`` key set to null. No shipped consumer asserts on the
payload's key set (both read only the keys they name), so both current producers
(/claim-task Step 7, /auto-build Phase 6e) and both current consumers (their
respective read-then-``rm -f`` steps) are unaffected — but "byte-identical" is
true of the filename only, and saying it of the behaviour would be false. This
exists for the orchestrator reshape (specified in tools/CLAIM_TASK_ORCHESTRATOR_SPEC.md,
maintainer-side and not in the public tree), where one claim spawns a planner, a
reviewer and an executor.

Plus the reviewer's REVIEW_REPORT YAML at the TOP of its response
(see _shared/adversarial-review.md § The reviewer-executor variant is retired). The hook
extracts both when present.

Multi-envelope rule. If multiple fenced YAML blocks contain a ``TASK:`` /
``STATUS:`` pair, the LAST one wins — matches the sub-agent prompt's "LAST
content in your final message" instruction.

Cleanup, and the two parents differ. /auto-build Phase 6e deletes the JSON file
after consuming it. **/claim-task Step 8 does NOT, since Phase 171** — deleting
the envelope at the moment it became evidence is why a review that ran and a
review that was skipped left identical traces (internal tracker #220). It keeps all
three, and instead /claim-task Step 7-pre MOVES any envelope left over from a
previous run of the same claim into that run's artifact directory before
spawning, since the filename below carries no run component. That move runs on a
FRESH claim only -- a --resume adopts an existing run and deliberately leaves the
mailbox alone, so /claim-task Step 8 records the executor's terminal status into
the run's own outcome.md rather than routing off this directory. The
sysop/runtime/subagent-envelopes/ dir is gitignored by install.sh's
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


ENVELOPES_DIR = "sysop/runtime/subagent-envelopes"

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

# REVIEW_REPORT YAML at the TOP of the reviewer's response. The shape
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
    "PHASE",
)

_FIELD_REGEXES = {
    name: re.compile(_FIELD_RE_TEMPLATE.format(name=re.escape(name)), re.MULTILINE)
    for name in _ENVELOPE_FIELDS
}

# Same grammar as validate_tasks.py's _TASK_ID_RE and tasks/schema.md § Task ID.
# Deliberate duplicate rather than an import: this file is a hook, executed by the
# harness independently of the validator, so a hook that fails because a sibling
# script was missing from a partial install is worse than the duplication — the
# same reasoning the git-common-dir resolution carries in claim_task.sh /
# batch_work.sh / close_batch.sh / next_task.py / validate_tasks.py /
# scope_overlap.py. Keep the two in step: tests/test_parse_subagent_envelope.py
# asserts they are character-identical.
#
# Phase 159a widened this from `^[A-Z][A-Z0-9]*-[A-Z0-9][A-Z0-9-]*$`, which was
# narrower than the schema in one direction and looser in another. Narrower: it
# required an interior hyphen (rejecting `FEAT001`, `ABC`) AND a non-empty
# [A-Z0-9] immediately after that hyphen (rejecting `FEAT--0001`, `FEAT-`) — two
# distinct causes, all four schema-valid, all four silently downgraded here to an
# _unparseable_ diagnostic plus the parent's regex fallback. Looser: it was
# unbounded in length, where the schema caps at 81. Both
# grammars admit only uppercase, digits and hyphens — neither is a path risk, and
# _sanitize_for_filename still runs on the value regardless.
_TASK_ID_SHAPE_RE = re.compile(r"^[A-Z][A-Z0-9-]{2,80}$")

# Optional envelope field naming which stage of a multi-agent claim emitted this
# envelope. Absent (or the documented "none" sentinel) reproduces the pre-159a
# filename exactly — `<TASK_ID>.json` — so every current producer and consumer is
# unaffected. When present the file becomes `<TASK_ID>.<phase>.json`, which is
# what lets a claim spawn more than one enveloping sub-agent without the second
# overwriting the first. Sanitized and length-capped before it reaches a path;
# `TASK:` keeps its own shape check above, so this adds no new injection surface.
_PHASE_MAX_LEN = 32


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

    # Optional per-phase key. Absent → the historical `<TASK_ID>.json` filename,
    # byte-for-byte; present → `<TASK_ID>.<phase>.json`. `_extract_field` already
    # maps the documented "none" sentinel to None, so `PHASE: none` takes the
    # historical path too. A phase that sanitizes away to nothing also falls back
    # rather than producing a stray dot in the filename.
    # Lower-cased before it becomes a path component. Without this, `PHASE: Plan`
    # and `PHASE: plan` are two files on Linux and ONE file on macOS/APFS — a
    # silent cross-platform split in the very mechanism that exists to keep two
    # sub-agents' envelopes apart. Truncation runs before the outer strip on
    # purpose: `[:N]` can re-expose a separator that _sanitize_for_filename had
    # already cleaned, and stripping first would leave `<TASK_ID>.foo..json`.
    phase_raw = envelope.get("phase")
    safe_phase = ""
    if phase_raw:
        safe_phase = _sanitize_for_filename(
            phase_raw.lower(), ""
        )[:_PHASE_MAX_LEN].strip("._")

    payload: dict[str, Any] = {
        "parsed": True,
        "task_id": task_id,
        # `phase` is the component that actually names the file, so a consumer can
        # rebuild the path from the payload; `phase_raw` preserves what the agent
        # literally wrote. They diverge whenever sanitizing, lower-casing or
        # truncation changed anything, and a reader that needs the path must use
        # `phase` — recording only the raw value made those two disagree silently.
        "phase": safe_phase or None,
        "phase_raw": phase_raw or None,
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
    filename = f"{safe_task_id}.{safe_phase}.json" if safe_phase else f"{safe_task_id}.json"
    out_path = os.path.join(envelopes_dir, filename)
    _write_json(out_path, payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
