"""Every Python heredoc the shipped tree runs on a consumer's interpreter.

One extractor, shared, because two private ones had each drifted narrower than
the tree (`Q-612`). `test_python_floor_portability.py`'s opener allowed only
redirects between `python3 -` and `<<`, so every heredoc with a positional
argument there (`python3 - "$manifest" <<'PY'`, eight in `install.sh` alone) was
outside its population, and neither extractor saw `install.sh`'s `"$_py" -`
command word (five more). Phase 333's residue count came from a grep and missed
four reads the same way.

THE OPENER is any line whose command word is an interpreter — `python`,
`python3`, `python3.12`, behind a path or quoted (`"$ROOT/.venv/bin/python3"`) —
or a variable naming one (`"$_py"`, `$PY`, `${PYTHON:-python3}`), followed by
options if any (`-u`, `-I`) and then ` -`, then anything, then `<<DELIM` (quoted
or not, `<<-` too). A literal interpreter may also meet `<<` directly
(`python3 <<'PY'`): both forms read the program from stdin. A variable may not,
because `cat > "$pyproject" <<EOF` is a data heredoc, and neither may a script
argument (`python3 x.py <<EOF`). The interpreter must start a token, so
`cat > run_python <<EOF` is not an opener. A line carrying a backtick is never
an opener: in markdown that is prose quoting a command, not a command, and four
prose lines matched before the rule. The body runs to the first line that is the
delimiter alone, and is dedented by its common indent, since a heredoc inside a
markdown list is indented.

NOT SEEN, and none occurs in the shipped tree (Phase 334's round probed each): an
opener continued onto a second line with a backslash, `cat <<PY | python3 -`,
`python3 /dev/stdin <<PY`, `<<\\PY`, and an interpreter reached through
`"$(command -v python3)"`.

POPULATION: skill markdown, companion shell scripts and git hooks, each pack's
shipped shell and markdown, and `install.sh` — every file whose heredocs run on
a consumer's machine.

A body that does not parse is returned as is. Callers decide what that means;
the strict-decode guard refuses it, because a guard that skips what it cannot
parse passes it silently.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The interpreter: `python`, `python3`, `python3.12`, optionally behind a path and
# optionally quoted (`"$ROOT/.venv/bin/python3"`). A variable naming one: `$PY`,
# `"$_py"`, `${PYTHON:-python3}`. Either must start a token, so `run_python` is not one.
_INTERP = r"(?<![\w-])\"?(?:[^\s\"`]*/)?python(?:3(?:\.\d+)?)?\"?"
_VAR = r"(?<![\w-])\"?\$\{?\w*py\w*(?::-[^}\s]*)?\}?\"?"
OPENER = re.compile(
    r"^([ \t]*)[^\n`]*?"
    r"(?:(?:" + _INTERP + "|" + _VAR + r")(?:\s+-[A-Za-z]\w*)*\s+-(?:\s[^\n`]*?)?|"
    + _INTERP + r"\s*)"
    r"<<-?\s*['\"]?(\w+)['\"]?[^\n`]*$",
    re.M | re.I,
)


def population() -> list[Path]:
    root = REPO_ROOT
    files = (sorted((root / "core" / "skills").rglob("*.md"))
             + sorted((root / "core" / "companion").rglob("*.sh"))
             + sorted(p for p in (root / "core" / "companion" / "git-hooks").rglob("*")
                      if p.is_file())
             + sorted((root / "packs").rglob("*.sh"))
             + sorted((root / "packs").rglob("*.md"))
             + [root / "install.sh"])
    seen, out = set(), []
    for f in files:
        if f.is_file() and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def heredocs_in(text: str) -> list[tuple[int, str, str]]:
    """(opener line number, opener line, dedented body) for each heredoc in `text`."""
    out = []
    for m in OPENER.finditer(text):
        rest = text[m.end():]
        end = re.search(r"^[ \t]*%s[ \t]*$" % re.escape(m.group(2)), rest, re.M)
        if not end:
            continue
        lines = rest[:end.start()].split("\n")
        # `rest` starts at the opener's newline and stops after the last body
        # newline, so the split carries one empty string at each end.
        lines = lines[1:-1]
        pads = [len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()]
        pad = min(pads) if pads else 0
        body = "\n".join(ln[pad:] for ln in lines)
        out.append((text.count("\n", 0, m.start()) + 1, m.group(0).strip(), body))
    return out


def shipped_heredocs() -> list[tuple[Path, int, str, str]]:
    """(file, opener line, opener, body) for every heredoc in the population."""
    out = []
    for f in population():
        for ln, opener, body in heredocs_in(f.read_text(encoding="utf-8")):
            out.append((f, ln, opener, body))
    return out


def heredoc_containing(path: Path, needle: str) -> str:
    """The body of the ONE heredoc in `path` containing `needle`, verbatim."""
    hits = [b for _, _, b in heredocs_in(path.read_text(encoding="utf-8")) if needle in b]
    assert len(hits) == 1, f"{path.name}: {len(hits)} heredocs contain {needle!r}"
    return hits[0]
