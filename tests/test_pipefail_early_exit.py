"""An early-exit reader under `pipefail`, where something reads the status.

Under `set -o pipefail` a pipeline's status is its rightmost non-zero status. A
reader that stops before its input ends (`head`, `grep -q`, `grep -m`, `grep -l`,
an `awk` program that `exit`s, a `sed` script that `q`uits, `read`) closes the
pipe, and a producer still writing dies of SIGPIPE (141) or, for Python, of a
broken pipe. That status then becomes the pipeline's. It matters only where two
things hold:

1. **The status is read** — an `if`/`while`/`until` condition, a `!`, an `||` or
   `&&` arm, `set -e` on a bare assignment or command, or a function's return.
2. **The producer can write past the reader's exit** — more than one pipe buffer
   in practice. On this tree's measurements a match on line 1 through
   `sed | grep -q` on macOS was missed 0 of 40 times at 16 KB, 20 of 40 at 24 KB
   and 40 of 40 from 48 KB (33 of 100 at 60 KB on GNU/Linux), while a single line
   of 300 KB never was: grep reads a whole line before it can match it, so the
   writer has finished.

The guard enumerates every shell file in the shipped tree that runs under
`pipefail` (its own `set … pipefail` line, or sourced by a file that has one —
`source`/`.` lines are followed, through a `VAR=…` assignment when the operand is
a variable), finds each early-exit reader, and decides by the rules in
`_status_read` whether its status is read. A site whose status is read must be
fixed or carried in `ALLOWED` with the reason it cannot overrun or is not read.

The fixed shapes it accepts, because they read to the end: `grep PATTERN >/dev/null`
in place of `grep -q` (measured draining its input on BSD grep 2.6, GNU grep 3.1,
3.4 and 3.8, and busybox 1.36), `sed -n 1p` or a capture cut with
`${v%%$'\\n'*}` in place of `head -1`, and an `awk` that sets a flag instead of
calling `exit` mid-stream (an `exit` inside its `END` block runs after the input
ends, so it is not an early exit).

Lines join where a `\\` continues them, where they end in `|`, `||` or `&&`, and
where they end inside a quoted string, so a multi-line awk or sed program is read
whole. A reader behind `!`, `command`, `exec`, `env`, `VAR=value` or `timeout
<duration>`, or named by a path (`/usr/bin/grep`), is still the reader. An
`ALLOWED` entry is a substring of its site, so each entry also pins how many
flagged sites it matches (`ALLOWED_MULTI`, else one): a new live site that shares
an entry's text is not excused.

What it cannot see, so a reviewer still has to:

* a reader that is a function or a `{ …; }` group (`… | first_line`) — only the
  command word after the `|` is read;
* a function defined in one file whose status is consumed by a caller in
  another, and a caller that turns `set -e` off (`if f`, `f || …`) — such sites
  are flagged and carried in `ALLOWED` with the caller named, which can rot;
* the last statement of a multi-line function body in a file without `set -e`
  (its status is the function's return) — only a one-line body is detected;
* shell embedded in other files: `run: |` blocks in the CI `.yml.example` files,
  and fenced blocks in skill markdown (none of which sets `pipefail`);
* `$?` read on a later line after a bare pipeline in a file without `set -e`;
* backtick substitutions, a `|` inside a `case` pattern (read as a pipe), and
  any quoting the small scanner below mis-tracks.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
HOOK_EXAMPLE = REPO_ROOT / "core" / "companion" / "git-hooks" / "examples" / "pre-commit-python.example"

# ── which files ────────────────────────────────────────────────────────────

# Any `set` line naming the option among its others: `-euo pipefail`, `-o pipefail`,
# `-o errexit -o pipefail`, `-o nounset -o pipefail`.
_PIPEFAIL_RE = re.compile(r"^\s*set\s(?:[^\n#;]*\s)?-[A-Za-z]*o\s+pipefail\b", re.M)
_ERREXIT_RE = re.compile(r"^\s*set\s(?:[^\n#;]*\s)?(?:-[A-Za-z]*e[A-Za-z]*\b|-[A-Za-z]*o\s+errexit\b)", re.M)
_SOURCE_RE = re.compile(r"(?:^|[;&|{(]\s*|\s)(?:source|\.)\s+(\"[^\"]*\"|'[^']*'|\S+)")


def _is_shell(path: Path) -> bool:
    if path.suffix in (".md", ".py", ".json", ".yml", ".yaml", ".toml", ".txt"):
        return False
    if path.suffix == ".sh":
        return True
    try:
        with path.open("rb") as fh:
            first = fh.readline(200)
    except OSError:
        return False
    return first.startswith(b"#!") and (b"bash" in first or first.rstrip().endswith(b"/sh"))


def _shipped_shell_files() -> list[Path]:
    """A filesystem walk, not `git ls-files`: an untracked new script is still checked."""
    out = [REPO_ROOT / "install.sh"]
    for top in ("core", "packs"):
        for dirpath, dirnames, filenames in os.walk(REPO_ROOT / top):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "node_modules")]
            for name in filenames:
                p = Path(dirpath) / name
                if _is_shell(p):
                    out.append(p)
    return sorted(set(out))


def _sourced_basenames(text: str) -> set[str]:
    """Basenames of `.sh` files this text sources, through one `VAR=…` hop."""
    names: set[str] = set()
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for m in _SOURCE_RE.finditer(line):
            operand = m.group(1).strip("\"'")
            hits = re.findall(r"[\w.-]+\.sh\b", operand)
            if not hits:
                var = re.match(r"\$\{?(\w+)", operand)
                if var:
                    for am in re.finditer(rf"^\s*(?:local\s+)?{var.group(1)}=(.*)$", text, re.M):
                        hits += re.findall(r"[\w.-]+\.sh\b", am.group(1))
            names.update(hits)
    return names


def pipefail_files() -> dict[Path, bool]:
    """{file: errexit} for every shipped shell file that runs under `pipefail`.

    A sourced helper inherits its sourcers' options; it is treated as `set -e`
    when any sourcer sets it, which flags more and never less."""
    files = _shipped_shell_files()
    by_name: dict[str, list[Path]] = {}
    for f in files:
        by_name.setdefault(f.name, []).append(f)
    result: dict[Path, bool] = {}
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        if _PIPEFAIL_RE.search(text):
            result[f] = bool(_ERREXIT_RE.search(text))
    for f, errexit in list(result.items()):
        for base in _sourced_basenames(f.read_text(encoding="utf-8", errors="replace")):
            for helper in by_name.get(base, []):
                result[helper] = result.get(helper, False) or errexit
    return result


# ── the scanner ────────────────────────────────────────────────────────────

def _strip_comment(line: str) -> str:
    """Drop a trailing `# …` that sits outside quotes and starts a word."""
    sq = dq = False
    prev = " "
    for i, ch in enumerate(line):
        if ch == "\\" and not sq:
            prev = ""
            continue
        if ch == "'" and not dq:
            sq = not sq
        elif ch == '"' and not sq:
            dq = not dq
        elif ch == "#" and not sq and not dq and prev in " \t;":
            return line[:i].rstrip()
        prev = ch
    return line


_HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_]\w*)\2")


def _open_quote(text: str) -> bool:
    """True when `text` ends inside a single- or double-quoted string."""
    sq = dq = False
    i = 0
    while i < len(text):
        ch = text[i]
        if sq:
            sq = ch != "'"
        elif ch == "\\":
            i += 2
            continue
        elif dq:
            dq = ch != '"'
        elif ch == "'":
            sq = True
        elif ch == '"':
            dq = True
        i += 1
    return sq or dq


def logical_lines(text: str) -> list[tuple[int, str]]:
    """(first line number, joined text): comments and heredoc bodies dropped,
    `\\`-continued lines, lines ending in `|`, `||` or `&&`, and lines that
    end inside a quoted string (a multi-line awk or sed program) joined."""
    out: list[tuple[int, str]] = []
    lines = text.splitlines()
    i, buf, start = 0, "", 0
    pending_heredocs: list[tuple[str, bool]] = []
    while i < len(lines):
        raw = lines[i]
        i += 1
        if pending_heredocs:
            delim, dash = pending_heredocs[0]
            if (raw.lstrip("\t") if dash else raw) == delim:
                pending_heredocs.pop(0)
            continue
        in_quote = bool(buf) and _open_quote(buf)
        if not buf and raw.lstrip().startswith("#"):
            continue
        line = raw if in_quote else _strip_comment(raw)
        for m in _HEREDOC_RE.finditer(line):
            pending_heredocs.append((m.group(3), m.group(1) == "-"))
        if not buf:
            start = i
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        if _open_quote(buf):
            buf += " "
            continue
        if re.search(r"(\|\||&&|\|)\s*$", buf) and not pending_heredocs:
            buf += " "
            continue
        if buf.strip():
            out.append((start, buf))
        buf = ""
    if buf.strip():
        out.append((start, buf))
    return out


def _scan(line: str):
    """Yield (pipe_index, depth_info) for every single `|` in code context.

    depth_info is the stack of open constructs at that point: each entry is
    ("$(", index) for a command substitution or ("(", index) for a subshell."""
    stack: list[tuple[str, int]] = []   # code frames: ("$(", i) / ("(", i) / ("dq", i) / ("sq", i)
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        top = stack[-1][0] if stack else "code"
        if top == "sq":
            if ch == "'":
                stack.pop()
            i += 1
            continue
        if top == "dq":
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                stack.pop()
            elif line.startswith("$((", i):
                stack.append(("$((", i)); i += 3; continue
            elif line.startswith("$(", i):
                stack.append(("$(", i)); i += 2; continue
            i += 1
            continue
        # code context (top level, "$(", "(", "$((")
        if ch == "\\":
            i += 2
            continue
        if ch == "'":
            stack.append(("sq", i))
        elif ch == '"':
            stack.append(("dq", i))
        elif line.startswith("$((", i):
            stack.append(("$((", i)); i += 3; continue
        elif line.startswith("$(", i):
            stack.append(("$(", i)); i += 2; continue
        elif line.startswith("((", i) and top != "$((":
            stack.append(("$((", i)); i += 2; continue
        elif ch == "(":
            stack.append(("(", i))
        elif ch == ")":
            if top == "$((" and line.startswith("))", i):
                stack.pop(); i += 2; continue
            if stack and top in ("$(", "("):
                stack.pop()
        elif ch == "|" and top != "$((":
            if line.startswith("||", i):
                i += 2
                continue
            if i > 0 and line[i - 1] in "|>":
                i += 1
                continue
            yield i, [f for f in stack if f[0] in ("$(", "(")]
        i += 1


def _segment_end(line: str, start: int) -> int:
    """Index where the command starting at `start` ends, at its own depth."""
    depth = 0
    sq = dq = False
    i = start
    while i < len(line):
        ch = line[i]
        if ch == "\\" and not sq:
            i += 2
            continue
        if sq:
            sq = ch != "'"
        elif dq:
            if ch == '"':
                dq = False
            elif line.startswith("$(", i):
                depth += 1; i += 2; continue
            elif ch == ")" and depth:
                depth -= 1
        elif ch == "'":
            sq = True
        elif ch == '"':
            dq = True
        elif line.startswith("$(", i) or ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                return i
            depth -= 1
        elif depth == 0 and (ch in "|;&" or line.startswith("then", i) and line[i - 1] in " \t"):
            return i
        i += 1
    return len(line)


_GREP_EARLY_LONG = ("--quiet", "--silent", "--max-count", "--files-with-matches", "--files-without-match")


def early_exit_reader(segment: str) -> str | None:
    """The form name if this command stops before its input ends, else None."""
    words = segment.split()
    if not words:
        return None
    # Skip what runs the reader rather than being it: `!`, `command`, `exec`,
    # `env` and `VAR=value` prefixes, and `timeout <duration>`.
    while len(words) > 1:
        w = words[0]
        if w in ("!", "command", "exec", "env") or re.fullmatch(r"\w+=\S*", w):
            words = words[1:]
        elif w == "timeout":
            words = words[1:]
            while len(words) > 1 and words[0].startswith("-"):
                words = words[1:]
            words = words[1:] if len(words) > 1 else words
        else:
            break
    cmd = words[0].rsplit("/", 1)[-1]
    if re.fullmatch(r"\w+=\S*", cmd):
        return None
    if cmd == "head":
        return "head"
    if cmd == "read":
        return "read"
    if cmd in ("grep", "egrep", "fgrep"):
        for w in words[1:]:
            if w.startswith("--"):
                if w.split("=", 1)[0] in _GREP_EARLY_LONG:
                    return f"grep {w}"
            elif re.fullmatch(r"-[A-Za-z]*[qmlL][A-Za-z0-9]*", w):
                return f"grep {w}"
        return None
    if cmd in ("awk", "gawk", "mawk", "nawk"):
        # An `exit` in the END block runs after the input is read to the end.
        body = re.sub(r"\bEND\s*\{[^{}]*\}", " ", segment)
        return "awk exit" if re.search(r"\bexit\b", body) else None
    if cmd == "sed":
        for script in re.findall(r"'([^']*)'|\"([^\"]*)\"", segment):
            body = script[0] or script[1]
            if re.search(r"(?:^|[;{}\s0-9$/])[qQ]\s*\d*\s*(?:$|[;}])", body):
                return "sed q"
        for w in words[1:]:
            if re.fullmatch(r"\d*[qQ]", w):
                return "sed q"
        return None
    return None


_ASSIGN_ONLY_RE = re.compile(r"(?:^|[\s;&|!({])([A-Za-z_]\w*)=\"?$")


def _pipeline_bounds(line: str, pipe_i: int, frame_start: int) -> tuple[int, int, int]:
    """(pipeline start, pipeline end, statement start) for the `|` at pipe_i.

    The pipeline starts after the last `;`, `&&`, `||` or the frame's opening;
    the statement (its whole and-or list) starts after the last `;` only."""
    lo = frame_start
    i = lo
    last = stmt = lo
    sq = dq = False
    depth = 0
    while i < pipe_i:
        ch = line[i]
        if ch == "\\" and not sq:
            i += 2
            continue
        if sq:
            sq = ch != "'"
        elif dq:
            if ch == '"':
                dq = False
            elif line.startswith("$(", i):
                depth += 1; i += 2; continue
            elif ch == ")" and depth:
                depth -= 1
        elif ch == "'":
            sq = True
        elif ch == '"':
            dq = True
        elif line.startswith("$(", i) or ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        elif depth == 0 and (line.startswith("&&", i) or line.startswith("||", i)):
            last = i + 2; i += 2; continue
        elif depth == 0 and ch == ";":
            last = stmt = i + 1
        i += 1
    # End: walk forward over `|` joints to the first other separator.
    j = pipe_i
    while True:
        e = _segment_end(line, j + 1)
        if e < len(line) and line[e] == "|" and not line.startswith("||", e):
            j = e
            continue
        return last, e, stmt


_CONDITION_RE = re.compile(r"(?:if|elif|while|until)\s")


def _in_condition(line: str, stmt: int) -> bool:
    """The and-or list starting at `stmt` is an if/while/until condition."""
    return bool(_CONDITION_RE.match(line[stmt:].lstrip()) or
                re.search(r"\b(?:if|elif|while|until)\s+$", line[:stmt]))


def _status_read(line: str, pipe_i: int, frames, errexit: bool, next_line: str) -> str | None:
    """Why this pipeline's status is read, or None when it is not (by rule).

    Rules for NOT read:
      R1  the pipeline is inside `$( … )` and the command that holds it has a
          command word (`[[ … ]]`, `echo`, `local v=…`, `case … in`): the
          substitution's status is discarded.
      R2  inside `$( … )` on an assignment-only command, in a file without
          `set -e`, with no `||`/`&&` beside it and not in a condition.
      R3  a bare pipeline in a file without `set -e`, not in a condition, not
          beside `||`/`&&`/`!`, and not the body of a one-line function.
    """
    frame_start = frames[-1][1] + (2 if frames and frames[-1][0] == "$(" else 1) if frames else 0
    lo, hi, stmt = _pipeline_bounds(line, pipe_i, frame_start)
    head = line[lo:pipe_i].lstrip()
    after = line[hi:hi + 2]
    if _in_condition(line, stmt):
        return "condition"
    if head.startswith("!"):
        return "negated condition"
    if after in ("&&", "||"):
        # A pipeline AFTER `&&`/`||` hands its status to the list, so the list's
        # context decides; one BEFORE an operator has its status read by it.
        return "and-or list"
    subst = [f for f in frames if f[0] == "$("]
    if subst:
        sub_i = subst[-1][1]
        outer = [f for f in frames if f[1] < sub_i]
        o_start = outer[-1][1] + (2 if outer[-1][0] == "$(" else 1) if outer else 0
        cmd_lo, cmd_hi, cmd_stmt = _pipeline_bounds(line, sub_i, o_start)
        prefix = line[cmd_lo:sub_i]
        if not _ASSIGN_ONLY_RE.search(prefix) or re.search(
                r"(?:^|\s)(local|declare|readonly|export|typeset)\s", prefix):
            return None                                           # R1
        if _in_condition(line, cmd_stmt) or line[cmd_lo:].lstrip().startswith("!"):
            return "assignment in a condition"
        if line[cmd_hi:cmd_hi + 2] in ("&&", "||"):
            return "assignment beside ||/&&"
        if errexit:
            return "assignment under set -e"
        return None                                               # R2
    if errexit:
        return "bare pipeline under set -e"
    if re.search(r"\{\s*$", line[:lo]) or line[hi:].lstrip().startswith(("}", ";")) and "}" in line[hi:]:
        return "function return"
    if next_line.strip() == "}":
        return "function return"
    return None                                                   # R3


def find_sites(text: str, errexit: bool) -> list[dict]:
    """Every early-exit reader in `text`, with whether its status is read."""
    sites = []
    lines = logical_lines(text)
    for k, (lineno, line) in enumerate(lines):
        nxt = lines[k + 1][1] if k + 1 < len(lines) else ""
        for pipe_i, frames in _scan(line):
            seg_end = _segment_end(line, pipe_i + 1)
            form = early_exit_reader(line[pipe_i + 1:seg_end])
            if not form:
                continue
            why = _status_read(line, pipe_i, frames, errexit, nxt)
            sites.append({"line": lineno, "text": line.strip(), "form": form, "read": why})
    return sites


# ── the allowlist ──────────────────────────────────────────────────────────
# (path, a substring of the logical line) -> why the status is not read or the
# producer cannot write past the reader. A site that matches no entry fails; an
# entry that matches no site fails (it is stale).

ALLOWED: dict[tuple[str, str], str] = {
    ("install.sh", "-print 2>/dev/null | head -n1"):
        "`_detect_has_file`'s status is its pipeline's, and its three callers all "
        "read it as `[[ -n \"$(_detect_has_file …)\" ]]`, which discards it.",
    ("core/companion/scripts/self_check.sh", "_rfield() {"):
        "self_check.sh runs without `set -e`; every caller of `_rfield` is "
        "`v=\"$(_rfield …)\"`, which reads only the output.",
    ("core/companion/scripts/self_check.sh", "_rstr()   {"):
        "self_check.sh runs without `set -e`; callers are `v=\"$(_rstr …)\"` and "
        "`[[ \"$(_rstr fanout)\" == … ]]`, which read only the output.",
    ("core/companion/scripts/_git_lib.sh", 'remote="$(git -C "$dir" remote 2>/dev/null | head -1)"'):
        "guarded by `n_remotes -eq 1` on the line above: `git remote` prints one "
        "line, so `head` reads all of it before it exits.",
    ("core/companion/scripts/close_batch.sh", 'BATCH_START=$(grep -n "^### Batch ${batch_num} "'):
        "inside `find_batch_range`, whose only caller is `if ! find_batch_range`, "
        "so `set -e` is off in its body and the next line tests the value; the "
        "producer prints one line per matching batch header.",
    ("core/companion/scripts/close_batch.sh", "offset_end=$(tail -n +\"$((BATCH_START + 1))\" \"$TASKS_FILE\" | grep -n '^##' | head -1"):
        "inside `find_batch_range` (`if !` caller, so `set -e` is off), and the "
        "next statement is a `case` on the value, never the status.",
    ("core/companion/scripts/cleanup_worktrees.sh", "-- 'sysop/runtime/' 2>/dev/null | head -1"):
        "`worktree_runtime_artifacts`'s status is its pipeline's, and both callers "
        "read it as `[[ -n \"$(worktree_runtime_artifacts …)\" ]]`.",
    ("core/companion/scripts/batch_work.sh", "awk '/^worktree /{print substr($0, 10); exit}'"):
        "inside `resolve_primary_worktree`, whose only caller is "
        "`MAIN_ROOT=\"$(resolve_primary_worktree)\" || MAIN_ROOT=\"\"`, so `set -e` "
        "is off in its body; the function's status is its final `printf`.",
    ("core/companion/scripts/batch_work.sh", "awk '/^worktree /{n++} n==1 && $0==\"bare\"{print \"bare\"; exit}'"):
        "inside `resolve_primary_worktree` (`|| MAIN_ROOT=\"\"` caller, so `set -e` "
        "is off); the value is tested, the status is not.",
    ("core/companion/scripts/claim_task.sh", "git ls-remote --exit-code origin \"refs/heads/${BRANCH_NAME}\""):
        "`ls-remote` is filtered by the full refname, so it prints one line (a "
        "few at most, for nested names), in one write that `awk` reads before "
        "it can exit.",
    ("core/companion/git-hooks/examples/pre-commit-python.example", "if echo \"$LINE\" | grep -qiE"):
        "input is one `$LINE`: grep reads a whole line before it can match it, so "
        "the writer has finished (measured 0/100 on a 300 KB line).",
    ("core/companion/git-hooks/examples/pre-commit-python.example", "if echo \"$LINE\" | grep -qE"):
        "input is one `$LINE`, read whole before grep can match it (see the entry above).",
    ("core/companion/git-hooks/examples/pre-commit-python.example", "if ! echo \"$LINE\" | grep -qE"):
        "input is one `$LINE`, read whole before grep can match it (see the entry above).",
}


def _all_sites():
    out = []
    for path, errexit in sorted(pipefail_files().items()):
        rel = path.relative_to(REPO_ROOT).as_posix()
        for s in find_sites(path.read_text(encoding="utf-8", errors="replace"), errexit):
            s["path"] = rel
            out.append(s)
    return out


# ── the file set ───────────────────────────────────────────────────────────

def test_the_file_set_follows_sourced_helpers():
    """`_git_lib.sh` sets no `pipefail` of its own and runs under its sourcers'.
    It is reached through `source "$_SYSOP_GIT_LIB"`, so this proves the
    variable hop works, not only a literal path."""
    files = {p.relative_to(REPO_ROOT).as_posix(): e for p, e in pipefail_files().items()}
    lib = "core/companion/scripts/_git_lib.sh"
    assert not _PIPEFAIL_RE.search((REPO_ROOT / lib).read_text()), \
        "the non-vacuity premise moved: _git_lib.sh now sets pipefail itself"
    assert files.get(lib) is True, f"{lib} not followed from its sourcers: {sorted(files)}"
    for must in ("install.sh", "core/companion/scripts/self_check.sh",
                 "core/companion/scripts/batch_work.sh",
                 "core/companion/git-hooks/examples/pre-commit-python.example"):
        assert must in files, f"{must} is not in the scanned set"
    assert files["core/companion/scripts/self_check.sh"] is False, "self_check.sh has no set -e"


def test_every_sourced_shell_file_is_scanned():
    """Completeness: any shipped `.sh` that a pipefail file sources is scanned."""
    files = pipefail_files()
    names = {p.name for p in files}
    for p in list(files):
        for base in _sourced_basenames(p.read_text(encoding="utf-8", errors="replace")):
            shipped = [f for f in _shipped_shell_files() if f.name == base]
            if shipped:
                assert base in names, f"{p.name} sources {base}, which is not scanned"


# ── the guard ──────────────────────────────────────────────────────────────

def test_no_unlisted_early_exit_reader_has_its_status_read():
    bad = []
    for s in _all_sites():
        if not s["read"]:
            continue
        if any(path == s["path"] and sub in s["text"] for (path, sub) in ALLOWED):
            continue
        bad.append(f"{s['path']}:{s['line']} [{s['form']}; {s['read']}] {s['text'][:160]}")
    assert not bad, (
        "an early-exit reader under pipefail whose status is read — rewrite it to "
        "read to the end (`grep … >/dev/null`, `sed -n 1p`, an awk flag), or add it "
        "to ALLOWED with the reason it cannot overrun:\n  " + "\n  ".join(bad))


# An entry is a substring, so it would also excuse a NEW live site that shares it.
# Each one matches exactly one flagged site, but these, which match this many.
ALLOWED_MULTI = {
    ("core/companion/git-hooks/examples/pre-commit-python.example", "if echo \"$LINE\" | grep -qiE"): 2,
}


def test_every_allowlist_entry_matches_exactly_its_sites():
    sites = [s for s in _all_sites() if s["read"]]
    wrong = {}
    for k in ALLOWED:
        n = sum(1 for s in sites if s["path"] == k[0] and k[1] in s["text"])
        if n != ALLOWED_MULTI.get(k, 1):
            wrong[k] = n
    assert not wrong, (
        "ALLOWED entries matching other than their recorded number of flagged sites "
        "(0: remove it; more: a new site shares its text, so fix that site or narrow "
        f"the entry): {wrong}")
    assert set(ALLOWED_MULTI) <= set(ALLOWED)


def test_every_allowlist_entry_has_a_reason():
    assert all(len(r) > 40 for r in ALLOWED.values())


# ── calibration: the base shapes are flagged, the fixed and inert ones are not ─

# Each is the line as it stood before the fix, in a file with its own options.
_LIVE_AT_BASE = [
    ("set -euo pipefail",
     '    if sed -E "$strip" "$extra" 2>/dev/null | grep -IEq "$_ep"; then\n      :\n    fi'),
    ("set -uo pipefail",
     "    if sed -E 's#(sysop|companion)/scripts/#\\1/@sysop-migrated@/#g' \"$armed_hook\" 2>/dev/null \\\n"
     "       | grep -qE \"(^|[^[:alnum:]_])scripts/($VENDOR_ALT)\" 2>/dev/null; then\n      :\n    fi"),
    ("set -euo pipefail",
     '  if git -C "$dir" symbolic-ref --quiet refs/remotes/origin/HEAD >/dev/null 2>&1 \\\n'
     '     || git -C "$dir" remote 2>/dev/null | grep -qx origin; then\n    remote="origin"\n  fi'),
    ("set -euo pipefail",
     '  if ! git -C "$MAIN_ROOT" remote 2>/dev/null | grep -qx origin; then\n    :\n  fi'),
    ("set -euo pipefail",
     "live_batch_record() {\n"
     "  parse_batches 2>/dev/null | awk -F'\\t' -v n=\"$1\" '$1 == n { print $3 \"\\t\" $4; exit }'\n}"),
    ("set -uo pipefail",
     "    if echo \"$DIFF\" | grep -vE 'redact_api_keys' | grep -qE '(return.*str\\(e\\))'; then\n      :\n    fi"),
    ("set -uo pipefail",
     '      if ! git show ":$FILE" 2>/dev/null | grep -q "redirect:"; then\n        :\n      fi'),
    ("set -uo pipefail",
     "    if echo \"$DIFF\" | grep -qE 'window\\.open\\(' && ! echo \"$DIFF\" | grep -qE 'noopener'; then\n      :\n    fi"),
    ("set -euo pipefail",
     '    x="$(git rev-list --reverse "${a}..HEAD" | head -n 1)" || x=""'),
    # the second pipeline of an `if A && B` condition
    ("set -uo pipefail",
     '    if [[ -n "$DIFF" ]] && echo "$DIFF" | grep -qE x; then\n      :\n    fi'),
    # a one-line function whose status is its return, in a file without set -e
    ("set -uo pipefail", '_first() { sed -n p "$1" | head -1; }'),
    # a program that spans lines inside one quote, with a mid-stream exit
    ("set -uo pipefail",
     "if git log | awk '\n  /x/ { f = 1; exit }\n  END { exit !f }'; then\n  :\nfi"),
    ("set -uo pipefail", "if git log | sed -n '/x/{\np\nq\n}' >/dev/null; then\n  :\nfi"),
    # a reader behind a prefix, or named by its path
    ("set -uo pipefail", "if git log | LC_ALL=C grep -q x; then :; fi"),
    ("set -uo pipefail", "if git log | env LC_ALL=C grep -q x; then :; fi"),
    ("set -uo pipefail", "if git log | /usr/bin/grep -q x; then :; fi"),
    ("set -uo pipefail", "if git log | timeout 5 grep -q x; then :; fi"),
]

_NOT_READ = [
    # inside [[ -n "$(…)" ]]
    ("set -euo pipefail",
     '  if [[ -n "$(git -C "$wt_path" ls-files --others --exclude-standard 2>/dev/null | head -1)" ]]; then\n    :\n  fi'),
    # multi-line [[ … ]] with continuations
    ("set -euo pipefail",
     '  if [[ -f "$dir/alembic.ini" ]] \\\n'
     '     || [[ -n "$(find "$dir" -maxdepth 4 -type f -name \'*.sql\' \\\n'
     '                   -print 2>/dev/null | head -n1)" ]]; then\n    :\n  fi'),
    # plain assignment, no set -e
    ("set -uo pipefail",
     '  MODE="$(sed -n \'s/.*"mode".*/\\1/p\' "$LOCK" | head -1)"'),
    ("set -uo pipefail",
     '    SP_LINE=$(echo "$CONTENT" | grep -nE "sys\\.path\\.insert" | head -1 | cut -d: -f1)'),
    # an and-or list inside a plain assignment, no set -e
    ("set -uo pipefail",
     '  LATEST="$(cd "$DIR" 2>/dev/null && ls -t -- *.json 2>/dev/null | head -1)"'),
    # local masks the status
    ("set -euo pipefail", '  local first="$(printf \'%s\\n\' a b | head -1)"'),
    # an argument to another command
    ("set -euo pipefail", '  echo "first: $(printf \'%s\\n\' a b | head -1)"'),
    # the fixed shapes
    ("set -euo pipefail",
     '    if sed -E "$strip" "$extra" 2>/dev/null | grep -IE "$_ep" >/dev/null; then\n      :\n    fi'),
    ("set -euo pipefail",
     "  parse_batches 2>/dev/null | awk -F'\\t' -v n=\"$1\" '$1 == n && !seen { seen = 1; print $3 \"\\t\" $4 }'"),
    ("set -euo pipefail", '    x="$(printf \'%s\\n\' a b | sed -n 1p)" || x=""'),
    # a heredoc body is not code
    ("set -euo pipefail", "cat <<'EOF'\nif x | grep -q y; then :; fi\nEOF"),
    # a comment is not code
    ("set -euo pipefail", "# if x | grep -q y; then\n:"),
    # an `exit` in END runs after the input is read: one line, and spanning lines
    ("set -uo pipefail", "if git log | awk '/x/ { f = 1 } END { exit !f }'; then :; fi"),
    ("set -uo pipefail",
     "if git log | awk '/x/ { f = 1 }\n    { p = 0 } END { exit !f }'; then\n  :\nfi"),
    # a `#` inside a quoted program that spans lines is not a comment
    ("set -uo pipefail",
     "if git log | awk '/x/ { f = 1 }\n# not a comment\nEND { exit !f }'; then\n  :\nfi"),
]


@pytest.mark.parametrize("line", ["set -euo pipefail", "set -o pipefail",
                                  "set -o errexit -o pipefail", "set -o nounset -o pipefail",
                                  "set -eu -o pipefail"])
def test_every_pipefail_spelling_puts_a_file_in_the_set(line):
    assert _PIPEFAIL_RE.search(f"#!/bin/bash\n{line}\n")


@pytest.mark.parametrize("line,errexit", [("set -euo pipefail", True), ("set -uo pipefail", False),
                                          ("set -o errexit -o pipefail", True),
                                          ("set -o nounset -o pipefail", False)])
def test_errexit_is_read_in_every_spelling(line, errexit):
    assert bool(_ERREXIT_RE.search(f"#!/bin/bash\n{line}\n")) is errexit


@pytest.mark.parametrize("opts,body", _LIVE_AT_BASE)
def test_calibration_flags_each_live_base_shape(opts, body):
    errexit = bool(_ERREXIT_RE.search(opts))
    sites = [s for s in find_sites(f"#!/usr/bin/env bash\n{opts}\n{body}\n", errexit) if s["read"]]
    assert sites, f"not flagged:\n{body}"


@pytest.mark.parametrize("opts,body", _NOT_READ)
def test_calibration_passes_each_inert_or_fixed_shape(opts, body):
    errexit = bool(_ERREXIT_RE.search(opts))
    sites = [s for s in find_sites(f"#!/usr/bin/env bash\n{opts}\n{body}\n", errexit) if s["read"]]
    assert not sites, f"flagged: {sites}"


def test_calibration_sees_every_early_exit_form():
    for seg, form in [("head -1", "head"), ("grep -qx origin", "grep -qx"),
                      ("grep -E -q x", "grep -q"), ("grep -m1 x", "grep -m1"),
                      ("grep --quiet x", "grep --quiet"), ("grep -l x", "grep -l"),
                      ("awk '{print; exit}'", "awk exit"), ("sed -n '1p;q'", "sed q"),
                      ("sed 1q", "sed q"), ("read -r x", "read"), ("IFS= read -r x", "read")]:
        assert early_exit_reader(seg), seg
    for seg in ("grep x", "grep -c x", "grep -E x >/dev/null", "sed -n 1p",
                "awk 'END{print NR}'", "tail -1", "cut -f1", "sort -u", "wc -l"):
        assert early_exit_reader(seg) is None, seg


# ── behaviour: the real code paths, on input larger than a pipe buffer ────

_GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0"}
_FILLER_KB = 200


def _filler(prefix: str = "# filler ") -> str:
    # Long rows keep the example hook's per-line loops short; the pipe sees bytes.
    row = prefix + "x" * 1000 + "\n"
    return row * (_FILLER_KB * 1024 // len(row))


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                   env={**os.environ, **_GIT_ENV})


def test_self_check_reports_a_stale_path_on_line_one_of_a_large_hook(tmp_path):
    """`self_check.sh`'s armed-hook scan, driven for real. A hook naming the old
    flat `scripts/` path on line 1 and 200 KB after it read as clean every time
    through `sed | grep -q`."""
    from tests.test_self_check_stale_hooks import _arm, _installed, _self_check
    root = _installed(tmp_path)
    _arm(root, "pre-push", "#!/bin/sh\nbash scripts/run_checks.sh --fail-on-blocking\n" + _filler())
    r = _self_check(root)
    assert "armed hook 'pre-push' still names a pre-migration scripts/ path" in r.stdout, \
        r.stdout[-2000:]
    assert r.returncode == 1


def test_install_migration_report_names_a_large_armed_hook(tmp_path):
    """`install.sh`'s stale-vendor-path report reads armed hooks through the same
    `sed | grep` shape; an untracked hook reaches it only through that arm."""
    from tests.test_install_namespace_migration import _build_old_consumer, _run_update, _stale_section
    root, _ = _build_old_consumer(tmp_path / "c")
    hooks = root / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-push").write_text(
        '#!/bin/sh\nbash "$REPO_ROOT/scripts/run_checks.sh" --fail-on-blocking\n' + _filler())
    r = _run_update(root)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert ".git/hooks/pre-push" in _stale_section(r.stdout), r.stdout[-3000:]


def _hook_repo(tmp_path):
    repo = tmp_path / "consumer"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    return repo


def _run_hook(repo):
    hook = repo / "hook.sh"
    shutil.copy(HOOK_EXAMPLE, hook)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["bash", str(hook)], cwd=str(repo), capture_output=True,
                          text=True, env=env)


def test_example_hook_blocks_a_match_early_in_a_large_diff(tmp_path):
    """B2 in the python example: a raw `str(e)` response on the first added line
    of a 200 KB diff. Through `grep -v | grep -q` the second grep's early exit
    killed the first, and the block was missed."""
    repo = _hook_repo(tmp_path)
    (repo / "api.py").write_text("def f(e):\n    return str(e)\n" + _filler())
    _git(repo, "add", "api.py")
    r = _run_hook(repo)
    assert "raw exception in response" in r.stdout, r.stdout[-2000:]
    assert r.returncode == 1


def test_example_hook_does_not_warn_when_a_large_file_has_the_option(tmp_path):
    """A14, an `if !` check: a large staged file that DOES set `redirect:` on
    line 1. The early exit made the negated pipeline true, so the hook warned
    anyway. `fetch(` sits on the LAST line so the outer check (the same shape)
    matches only once its writer has finished, on the base code as well."""
    repo = _hook_repo(tmp_path)
    d = repo / "frontend" / "app" / "hooks"
    d.mkdir(parents=True)
    (d / "useThing.ts").write_text(
        "const opts = { redirect: 'error' };\n" + _filler("// filler ")
        + "export const go = () => fetch(url, opts);\n")
    _git(repo, "add", "-A")
    r = _run_hook(repo)
    assert "without redirect" not in r.stdout, r.stdout[-2000:]


def test_batch_claim_finds_its_batch_in_a_long_tracker(tmp_path):
    """`live_batch_record` re-reads the batch under the mutex as
    `parse_batches | awk '… exit'`, and both callers read the status with
    `|| …=""`. With a tracker whose `--list` runs past a pipe buffer, the awk
    exit broke the pipe under `review_index.py`, and the claim refused with the
    batch reading `<not found>`."""
    from tests.test_batch_work_sh import _repo, _run
    rows = ["# Review Tasks\n", "### Batch 1 — First batch `Pending`\n",
            "> **Branch:** `feat/one`\n", "- [ ] a\n"]
    for n in range(2, 1502):
        rows += [f"### Batch {n} — A long finished batch title number {n} for width `Complete`\n",
                 f"> **Branch:** `feat/finished-batch-{n}`\n", "- [x] b\n"]
    repo = _repo(tmp_path / "repo", "".join(rows))
    listed = subprocess.run([sys.executable, str(repo / "sysop/scripts/review_index.py"), "--list"],
                            cwd=str(repo), capture_output=True, text=True)
    assert len(listed.stdout) > 128 * 1024, "the fixture no longer outruns a pipe buffer"
    r = _run(repo, "1", env={"WORKTREE_PREFIX": "bw"})
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert (repo / "sysop/runtime/locks/BATCH-1.lock").is_file()


def test_batch_claim_sees_origin_among_many_remotes(tmp_path):
    """`batch_work.sh` decides whether to pull with `git remote | grep -x origin`.
    With `origin` sorted first among ~84 KB of remote names, `grep -qx` exited at
    it, `git remote` took SIGPIPE, and the `if !` read that as no origin: the
    claim skipped its freshness pull. (`_git_lib.sh`'s resolver has the same
    line; it only chooses which remote's HEAD to read, so it has no visible
    effect here and is pinned by the calibration above.)"""
    from tests.test_batch_work_sh import _repo, _run
    repo = _repo(tmp_path / "repo")
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(bare)],
                   check=True, capture_output=True)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", "HEAD:refs/heads/main")
    with (repo / ".git" / "config").open("a") as fh:
        for n in range(3000):
            fh.write(f'[remote "zz-contributor-remote-{n:05d}"]\n\turl = {bare}\n')
    names = subprocess.run(["git", "remote"], cwd=str(repo), capture_output=True, text=True).stdout
    assert names.startswith("origin\n") and len(names) > 64 * 1024, \
        "the fixture no longer puts origin first in a list past a pipe buffer"
    r = _run(repo, "1", env={"WORKTREE_PREFIX": "bw", "GIT_TERMINAL_PROMPT": "0"})
    assert "No 'origin' remote" not in r.stdout, r.stdout[-2000:]
    assert "Pulling latest" in r.stdout, r.stdout[-2000:] + r.stderr[-2000:]
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]


def test_example_hook_multi_line_arm_reads_one_line_ahead_only(tmp_path):
    """The arm's window is the next added line, as its old `-B1` intended. A
    keyword two lines below the call is not seen; this pins that limit."""
    repo = _hook_repo(tmp_path)
    (repo / "jobs.py").write_text(
        "def f(e):\n    logger.error(\n        'x',\n        exc_info=True)\n")
    _git(repo, "add", "jobs.py")
    r = _run_hook(repo)
    assert "multi-line logger.* with exc_info=True" not in r.stdout, r.stdout[-2000:]


def test_example_hook_warns_when_exc_info_is_on_the_next_line(tmp_path):
    repo = _hook_repo(tmp_path)
    (repo / "jobs.py").write_text("def f(e):\n    logger.error('x',\n        exc_info=True)\n")
    _git(repo, "add", "jobs.py")
    r = _run_hook(repo)
    assert "multi-line logger.* with exc_info=True" in r.stdout, r.stdout[-2000:]


def test_example_hook_does_not_warn_twice_on_a_single_line_exc_info_call(tmp_path):
    repo = _hook_repo(tmp_path)
    (repo / "jobs.py").write_text("def f(e):\n    logger.error('x', exc_info=True)\n")
    _git(repo, "add", "jobs.py")
    r = _run_hook(repo)
    assert "bypasses _sanitize_log" in r.stdout, r.stdout[-2000:]
    assert "multi-line logger.* with exc_info=True" not in r.stdout, r.stdout[-2000:]


def test_example_hook_multi_line_arm_ignores_a_closed_call(tmp_path):
    """A `logger.*(…)` closed on its own line, then an unrelated `exc_info=True`."""
    repo = _hook_repo(tmp_path)
    (repo / "jobs.py").write_text(
        "def f(e):\n    logger.info('done')\n    handler.handle(record, exc_info=True)\n")
    _git(repo, "add", "jobs.py")
    r = _run_hook(repo)
    assert "multi-line logger.* with exc_info=True" not in r.stdout, r.stdout[-2000:]


def test_example_hook_multi_line_arm_stops_at_a_hunk_boundary(tmp_path):
    """The last added line of one hunk and the first of the next are not one call."""
    repo = _hook_repo(tmp_path)
    body = [f"x{i} = {i}" for i in range(12)]
    (repo / "jobs.py").write_text("\n".join(body) + "\n")
    _git(repo, "add", "jobs.py")
    _git(repo, "commit", "-q", "-m", "base")
    body[2] = "logger.warning("
    body[9] = "kw = dict(exc_info=True)"
    (repo / "jobs.py").write_text("\n".join(body) + "\n")
    _git(repo, "add", "jobs.py")
    r = _run_hook(repo)
    assert "multi-line logger.* with exc_info=True" not in r.stdout, r.stdout[-2000:]
