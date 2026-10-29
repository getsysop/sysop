"""Shared log-sanitization helper for ``sysop/scripts/``.

``_sanitize_log()`` strips ANSI escape sequences and control characters from
arbitrary values before they are printed or logged. Workflow scripts surface
filesystem paths, YAML content, and exception messages to stderr; a malformed
exception (``FileNotFoundError``, ``PermissionError``, a subprocess's stderr)
could otherwise embed escape sequences that corrupt the operator's terminal or
hide warning text. The helper also truncates to ``max_len`` so a runaway error
message can't flood the log.

Single source of truth for ``sysop/scripts/``-internal callers. Import it as
``from _log import _sanitize_log`` — every script ships alongside this file in
the consumer's ``sysop/scripts/`` directory, and the directory is on ``sys.path``
whenever a script runs directly (``sys.path[0]``) or under the package
(``run_checks``'s parent dir).

Two callers keep their own inline copy on purpose and must NOT import this
module: ``validate_tasks.py`` and ``next_task.py``. Both run from the
pre-commit hook before the project venv (and therefore the full ``sys.path``)
is reliably wired up, so they stay standalone. If that constraint changes,
fold them in here.
"""
from __future__ import annotations

import re

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_CONTROL_RE = re.compile(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_log(value: object, max_len: int = 500) -> str:
    """Strip ANSI/control chars and truncate to *max_len* characters.

    Use on every exception message and any value derived from external input
    (filesystem paths, YAML content, subprocess stderr) before printing.
    """
    text = str(value)
    text = _ANSI_ESCAPE_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    text = text.replace("\n", " ").replace("\r", " ").replace("\0", " ")
    if len(text) > max_len:
        text = text[:max_len] + "..."
    return text
