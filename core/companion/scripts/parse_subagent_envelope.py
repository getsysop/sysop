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

Message-source chain (Phase 54, corrected Phase 319). The hook prefers
``last_assistant_message`` from hook input. It falls back to the sub-agent's
own JSONL transcript at ``agent_transcript_path`` whenever that field carries
NO ENVELOPE — not merely when it is absent or empty, which is what this
paragraph claimed and the code did until Phase 319. The distinction is the
whole defect: an agent that hands its envelope back through the harness's
handback tool still leaves a non-empty one-line summary in
``last_assistant_message``, so the old condition skipped the fallback and the
run was recorded ``_unparseable_``. Measured on three live sub-agent
transcripts, the old chain recovered none of the three envelopes and the
corrected one recovers all three.

The transcript is adopted ONLY when it yields an envelope, so this cannot
lose or alter a case that already parsed. When neither source yields text the
hook exits 0 and the parent skill's regex fallback handles the envelope as
before.

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
diagnostic file (kept across runs for inspection, then reclaimed after
DIAGNOSTIC_RETENTION_DAYS — see that constant) and exits 0 — the hook
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
import tempfile
import time
from typing import Any


ENVELOPES_DIR = "sysop/runtime/subagent-envelopes"

# Diagnostic retention (`Q-334`, Phase 314). The hook is registered with no
# `matcher`, so it fires on EVERY sub-agent stop. Every non-participant —
# `Explore`, `general-purpose`, a consumer's own reviewers — legitimately has
# no envelope and leaves a diagnostic saying so, and until now nothing
# reclaimed them. Measured on one consumer 2026-09-19: **6,735 diagnostics
# against 79 real envelopes**, 481 per active day, oldest 13.0 days.
#
# **The cap covers `_unparseable_*.json` and nothing else, and that is the
# whole safety property.** A parsed envelope is evidence with a documented
# lifetime — `claim-task/SKILL.md` § *Do not delete the envelopes here*, which
# exists because deleting one at the moment it became evidence is the failure
# that reshape removed — and it is reaped by the close, never by age. (The
# discriminator is the FILENAME, not whether an envelope parsed: see
# `_reclaim_stale_diagnostics` on the parsed-but-unkeyable case.) This is
# not a hypothetical: on that same directory a 7-day sweep over the whole
# directory would have destroyed **56 of the 79** envelopes, because an
# envelope outlives the diagnostics by design (oldest envelope 47.7 days).
DIAGNOSTIC_RETENTION_DAYS = 7

# The harness tool a sub-agent calls to hand its final message back to its
# parent. Matched by exact name on purpose: an upstream rename must make the
# handback path find nothing (and fall back to text blocks) rather than match
# some other tool's input. Matching any tool name was measured and rejected —
# not because of tools like `Bash`, whose input carries no `message` key and so
# is invisible here regardless, but because two other tools DO carry one: a
# census of live transcripts finds `SubagentHandback` 333, `SendMessage` 234 and
# `PushNotification` 5. Dropping this check adopts a `SendMessage` payload as the
# agent's result.
_HANDBACK_TOOL_NAME = "SubagentHandback"

# How much text may follow the envelope block in a handback before the envelope
# is read as a QUOTATION rather than this agent's own result.
#
# Both lifecycle skills tell an agent to emit its envelope as the LAST content of
# its final message, so this enforces a contract that already exists rather than
# inventing one. It exists because Phase 319's round falsified the claim that a
# handback cannot carry a forged envelope: a Sysop REVIEW LENS — an agent holding
# no claim at all — quoted another repo's envelope as evidence, and the first cut
# of this fix adopted it and would have written that claim's slot.
#
# Measured over every handback on this machine carrying an envelope (57): 56 end
# within 20 characters of it, and the one outlier is that reviewer, at 13,900.
# The bound sits an order of magnitude above the compliant population and two
# below the counterexample, so it is not fitted to the single case. Failure is
# CLOSED — an envelope past the bound is ignored and the reader falls back to
# text, which is pre-319 behaviour.
_HANDBACK_ENVELOPE_TAIL_MAX = 200

# Fence detection. Shared verbatim with `review_index.py`, `sitrep_survey.py`,
# `next_task.py` and `archive_review_tasks.py`, and pinned equal by
# `tests/test_flag_contract.py::test_fence_patterns_are_identical_in_all_parsers`.
# The close pattern requires nothing but whitespace after the run (CommonMark),
# so a nested ```` ```python ```` opener does not close the block it is inside.
#
# **Why a scanner and not a pair regex (Q-372).** This module used to pair
# fences with `` ```(?:yaml|yml)?\s*\n(.*?)\n``` ``, which recognises only
# `yaml`, `yml` and a bare fence as OPENERS. An executor that writes code —
# the ordinary case for a `/claim-task` Step 7e agent, not an edge case —
# emits a ```` ```bash ```` block, and that opener is not seen as a fence at
# all: its CLOSING ``` then pairs with the next opener, every subsequent block
# shifts by one, and the real envelope ends up inside what the parser reads as
# prose. Reported from a live consumer: the hook wrote
# `_unparseable_<session>_<agent>.json` saying "no fenced YAML block with
# TASK: and STATUS:" while the envelope sat, visible, inside that same
# diagnostic's own `last_assistant_message_excerpt` — the parser stored the
# evidence contradicting its own verdict.
#
# Widening the info string alone would have fixed the reported case and left
# the class: a pair regex is also wrong for a 4-backtick opener closed by a
# 3-backtick run, for a `~~~` fence, and for an indented one. The repo already
# owns a scanner that gets all of those right, with a grammar table behind it,
# so this borrows it rather than minting a fifth dialect.
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(?:> ?)*(`{3,}|~{3,})")
_FENCE_CLOSE_RE = re.compile(r"^ {0,3}(?:> ?)*(`{3,}|~{3,})[ \t]*$")

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


def _handback_message(content: list) -> str:
    """The ``message`` argument of the LAST handback tool call in one entry.

    Returns "" when the entry carries no handback block. The tool name is
    matched exactly: a rename upstream makes this return "" and the reader
    falls back to text blocks, which is the pre-Phase-319 behaviour.
    """
    found = ""
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        if block.get("name") != _HANDBACK_TOOL_NAME:
            continue
        payload = block.get("input")
        if not isinstance(payload, dict):
            continue
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            found = message
    return found


def _envelope_is_this_agents_result(message: str) -> bool:
    """True when `message` ends with an envelope, rather than merely quoting one.

    `_find_envelope_block` takes the LAST fenced TASK+STATUS block anywhere in the
    text, which is right for a message that ENDS with its envelope and wrong for
    one that quotes an envelope and then keeps talking. Phase 319's round found a
    live instance of the latter — a review lens quoting the envelope it was
    reviewing — and the agent that emitted it held no claim.

    Position is the discriminator because position is the contract: the skills
    say the envelope is the last content of the final message.
    """
    block = _find_envelope_block(message)
    if block is None:
        return False
    end = message.rfind(block) + len(block)
    return len(message) - end <= _HANDBACK_ENVELOPE_TAIL_MAX


def _last_assistant_message_from_transcript(path: str) -> str:
    """Best-effort read of the sub-agent's final message in a JSONL transcript.

    Fallback source for harnesses that provide ``agent_transcript_path``
    (2.0.42+) but not ``last_assistant_message`` (2.1.47+), and — since
    Phase 319 — the ONLY source that can see an envelope handed back through
    the harness's handback tool rather than written as text. Tolerates
    missing files, non-JSON lines, unexpected entry shapes, a non-string
    ``text``, and a torn multibyte tail — a missing/unreadable file returns "",
    and any other failure returns whatever was recovered before it, so main()
    degrades to the parent's regex fallback instead of raising.

    Selection is envelope-first, not last-wins. Measured on three live
    sub-agent transcripts (Phase 319): in all three the agent emitted its
    envelope through the handback tool and THEN produced a one-line text
    summary, so the last-wins rule this function used to apply returned the
    summary and discarded the envelope. Preferring an envelope-bearing
    handback is what makes widening the block filter actually recover
    anything; widening alone would still have returned the summary.

    When no handback carries an envelope the return value is the last
    non-empty text, exactly as before — so a transcript this function
    already read correctly still reads the same way.
    """
    if not path:
        return ""
    last_text = ""
    last_envelope = ""
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
                    handback = _handback_message(content)
                    if handback and _envelope_is_this_agents_result(handback):
                        last_envelope = handback
                    text = "\n".join(
                        block["text"]
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                        and isinstance(block.get("text"), str)
                    )
                else:
                    continue
                if text.strip():
                    last_text = text
    except OSError:
        return ""
    except Exception:
        # NOT swallowed out of caution — swallowed because this read is now on the
        # DOMINANT path. Before Phase 319 the transcript was opened only when
        # `last_assistant_message` was empty; now it is opened on every run whose
        # hook message carries no envelope, which is the common case. Two failures
        # reach here from a transcript the hook does not control: a `UnicodeDecodeError`
        # when the JSONL tail is still flushing and the read lands mid-multibyte
        # (this project's prose is full of em dashes, so the window is real), and a
        # `TypeError` from a `text` block whose `text` is not a string. Phase 319's
        # own round measured both: pre-319 each wrote `_unparseable_*.json`, and the
        # first cut of this phase exited 1 with a traceback and wrote nothing —
        # a regression in the very mailbox `Q-553` is about.
        #
        # Returning what was already recovered rather than "" is deliberate: an
        # envelope read from line 1 is not made wrong by line 900 being torn.
        return last_envelope or last_text
    return last_envelope or last_text


def _fenced_blocks(text: str) -> list[str]:
    """The body of every **balanced** fenced block, in document order.

    Same open/close predicate as `_fenced_mask` in the four structural readers
    — marker character AND marker length both load-bearing — but it returns
    bodies rather than a mask, because this module selects a block by its
    content and a boolean mask cannot tell two adjacent blocks apart.

    An **unterminated** fence yields nothing, matching `_fenced_mask`'s
    deliberate choice: a stray opener must not swallow the rest of the message.
    Here that direction is doubly right, since the envelope is emitted LAST and
    an unterminated fence earlier in the message would otherwise hide it.
    """
    # `\r\n` normalised first. The pair regex this replaced closed on
    # `\n```\s*`, which matched a CRLF line ending; `_FENCE_CLOSE_RE` ends
    # `[ \t]*$` and a bare `\r` matches neither, so a CRLF message yielded NO
    # balanced blocks at all — the same silent-envelope-loss this function was
    # written to remove, reintroduced through the line ending. Found by this
    # phase's round driving the hook end-to-end rather than calling in.
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    start = None
    marker = None
    for i, line in enumerate(lines):
        if start is None:
            m = _FENCE_OPEN_RE.match(line)
            if m:
                start, marker = i, m.group(1)
        else:
            m = _FENCE_CLOSE_RE.match(line)
            if m and marker and m.group(1)[0] == marker[0] and len(m.group(1)) >= len(marker):
                out.append("\n".join(lines[start + 1:i]))
                start = marker = None
    return out


def _find_envelope_block(text: str) -> str | None:
    """Return the body of the LAST fenced block carrying TASK: + STATUS:."""
    candidates = [
        body for body in _fenced_blocks(text)
        if _ENVELOPE_HEAD_RE.search(body) and _STATUS_LINE_RE.search(body)
    ]
    return candidates[-1] if candidates else None


def _find_review_report_block(text: str) -> str | None:
    """Return the body of the FIRST fenced block whose top-line key is REVIEW_REPORT."""
    for body in _fenced_blocks(text):
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


def _unlink_quietly(path: str) -> None:
    """Best-effort removal of a temp file that never made it to `os.replace`.

    Deliberately silent: it runs on an error path that is already reporting a
    cause, and a failure to clean up must not replace that cause with its own.
    """
    try:
        os.unlink(path)
    except OSError:
        pass


def _reclaim_stale_diagnostics(envelopes_dir: str) -> int:
    """Remove `_unparseable_*.json` older than `DIAGNOSTIC_RETENTION_DAYS`.

    Returns the number removed. Best-effort throughout: this runs inside a
    hook whose job is to write an envelope, and a reclaim failure must never
    cost the caller that write, so every filesystem call is guarded and the
    function cannot raise.

    **Not `_unlink_quietly`.** That helper's contract is a temp file that never
    made it to `os.replace`, and it is deliberately silent — it cannot report
    how many files it removed, which is the one thing a retention sweep has to
    be testable on.

    A parsed envelope FILE is never a candidate; see `DIAGNOSTIC_RETENTION_DAYS`.
    **One exception, stated because the obvious phrasing is wrong:** the
    parsed-but-unkeyable case below (`"parsed": true, "task_id_valid": false`,
    a TASK that does not match `_TASK_ID_SHAPE_RE`) is *stored under an
    `_unparseable_` name*, so it IS swept at the cap like any other diagnostic.
    That is the intended trade — it is keyed by session+agent, not by task, so
    it is a diagnostic in every way that matters to a reader — but it means the
    property is about the NAME, not about whether an envelope parsed. Measured
    2026-09-19: 0 of 6,780 live diagnostics carry that shape.
    """
    cutoff = time.time() - DIAGNOSTIC_RETENTION_DAYS * 86400
    removed = 0
    try:
        names = os.listdir(envelopes_dir)
    except OSError:
        return 0
    for name in names:
        # Re-checked here rather than delegated to a glob pattern: the prefix
        # IS the safety property, so it is asserted at the point of deletion
        # where a later edit cannot widen it from a distance.
        if not (name.startswith("_unparseable_") and name.endswith(".json")):
            continue
        path = os.path.join(envelopes_dir, name)
        try:
            if os.path.getmtime(path) >= cutoff:
                continue
            os.unlink(path)
        except OSError:
            continue
        removed += 1
    return removed


def _umask_mode() -> int:
    """What `open(path, "w")` would have created: 0666 masked by the umask."""
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


def _write_json(path: str, payload: dict[str, Any]) -> bool:
    # `mkstemp` rather than a fixed `<path>.tmp` (`Q-448`): the temp name was
    # derived from its target, which is the class `Q-382`/`Q-414`/`Q-442`/`Q-444`
    # closed writer by writer — here the mailbox is keyed by claim id and phase
    # with no run component, so every hook run for one claim derived the same
    # name. The exposure was assessed low (one writer per claim id at a time)
    # and the conversion finishes the class rather than stopping a bleed. `dir=`
    # the target's directory keeps `os.replace` same-filesystem; the name ends
    # in `.tmp`, never `.json`, so no reader of `<TASK_ID>.json` can open a
    # half-written envelope; the mode is carried from an existing envelope, else
    # it is what `open()` would have given (mkstemp creates 0600); and the
    # cleanup arm reaches past `OSError`, because a uniquely named leak is never
    # overwritten by a later run the way the fixed name was. `mkstemp` sits in
    # its own arm so a read-only runtime dir still reaches the sanitized
    # `failed to write` line rather than a raw traceback — the hole Phase 271's
    # round found in the sibling conversion.
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        real = os.path.realpath(path)
        try:
            mode = os.stat(real).st_mode & 0o7777
        except OSError:
            mode = _umask_mode()
        fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(real), prefix=os.path.basename(real) + ".", suffix=".tmp"
        )
    except OSError as e:
        print(f"parse_subagent_envelope: failed to write {path}: {e}", file=sys.stderr)
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, real)
        return True
    except OSError as e:
        _unlink_quietly(tmp_path)
        print(f"parse_subagent_envelope: failed to write {path}: {e}", file=sys.stderr)
        return False
    except BaseException:
        # Not swallowed — re-raised after cleanup, so `KeyboardInterrupt` still
        # interrupts and a `TypeError` from an unserializable payload is still
        # the hook's failure. Present only so a non-`OSError` failure does not
        # leak a uniquely-named temp that no later run will overwrite.
        _unlink_quietly(tmp_path)
        raise


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
    # Gate widened in Phase 319. It used to read `if not last_message`, which
    # made the transcript fallback unreachable for the defect it is needed for:
    # an agent that hands its envelope back through the handback tool still
    # leaves a non-empty one-line text summary in `last_assistant_message`, so
    # the fallback was skipped and the run recorded `_unparseable_`. The
    # condition is now "no envelope here", not "nothing here".
    #
    # The replacement is one-directional: the transcript's message is adopted
    # ONLY when it actually carries an envelope, so a case that parses today
    # parses identically, and a case that produces a diagnostic today produces
    # the same diagnostic from the same text. The widening can add an envelope;
    # it cannot lose or alter one.
    if _find_envelope_block(last_message) is None:
        recovered = _last_assistant_message_from_transcript(transcript_path)
        if _find_envelope_block(recovered) is not None:
            last_message = recovered
            message_source = "agent_transcript"
        elif not last_message:
            last_message = recovered
            message_source = "agent_transcript"
    if not last_message:
        return 0

    cwd = data.get("cwd") or os.getcwd()
    repo_root = _main_repo_root(cwd)
    envelopes_dir = os.path.join(repo_root, ENVELOPES_DIR)
    # Sited here, not on the write paths: this is the one point every
    # path that touches the directory passes through exactly once, so no
    # early return below can skip it. Measured at 27 ms over 6,735 files,
    # against a sub-agent run of minutes — a sentinel file to sweep only
    # once per interval was considered and rejected as a second piece of
    # runtime state bought for 27 ms.
    _reclaim_stale_diagnostics(envelopes_dir)

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
