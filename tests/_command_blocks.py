"""A prescribed command as a runner runs it: its line, plus the quoted heredoc it opens.

A fence inside a list item is indented with the item; a reader of the rendered text gets the
block without that indent, and so must a test that runs it, or bash never sees the delimiter.
"""
from __future__ import annotations

import re

_OPENER = re.compile(r"<<'([A-Z_]+)'\s*$")


def command_blocks(text: str, pattern: str) -> list[str]:
    """Each command whose first line (stripped) matches `pattern` at its start, with the
    heredoc body and delimiter it opens, dedented by the first line's indent."""
    lines = text.split("\n")
    out = []
    for i, ln in enumerate(lines):
        indent = len(ln) - len(ln.lstrip())
        if not re.match(pattern, ln.strip()):
            continue
        block = [ln.strip()]
        m = _OPENER.search(ln)
        if m:
            for nxt in lines[i + 1:]:
                block.append(nxt[indent:] if nxt[:indent].strip() == "" else nxt)
                if nxt.strip() == m.group(1):
                    break
            else:
                raise AssertionError(f"heredoc {m.group(1)} opened at line {i + 1} never ends")
        out.append("\n".join(block))
    return out


def unfilled(cmd: str) -> bool:
    """True while a `<placeholder>` is left; a heredoc opener is not one."""
    return "<" in _OPENER.sub("", cmd.split("\n", 1)[0]) or any(
        "<" in ln for ln in cmd.split("\n")[1:])
