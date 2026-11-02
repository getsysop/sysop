"""`Q-764` (Phase 458): a `close_run.py` reason the runner fills with text it did not write goes
on stdin through a quoted heredoc, never inside double quotes.

`/review-close`'s unattended steps passed the convention gate's first violation to `hold`, and a
park's reason and recovery to `stop`, as `"…"` arguments. That text usually carries backticked
identifiers: inside double quotes a backtick or `$(…)` is command substitution, so any mode that
ran the line ran the text, and lost it from the record. Under `--permission-mode dontAsk`
(Claude Code 2.1.312, the seeded `Bash(python3 sysop/scripts/close_run.py:*)`, PHASE_LOG.md §
Phase 458) the hold was denied with either in its reason, and the stop's same shape falls to the
same rule, so a night's hold, or its durable stop, was never recorded; the heredoc forms of
both were admitted and kept the text.

`close_run.py` reads `-` as "the reason is on stdin", joined onto one line.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from _command_blocks import command_blocks, unfilled
from skill_runner_text import text_of

REPO = Path(__file__).resolve().parents[1]
STEPS = REPO / "core" / "skills" / "review-close" / "steps"
PREPARE = STEPS / "prepare-resume.md"
NIGHT = STEPS / "request-review-land.md"
SCRIPTS = REPO / "core" / "companion" / "scripts"
RUN = "20261101T000000Z-a458"
HOSTILE = "`touch PWNED1` is not called in $(touch PWNED2) `_sanitize_log`"
RETIRED_HOLD = 'python3 sysop/scripts/close_run.py hold "<run-id>" "<branch>" "VERDICT: BLOCKED: <first violation>"'

_ENV = {k: v for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
_ENV.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
            PATH=f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for cmd in ("git init -q -b main", "git config user.email t@t", "git config user.name t",
                "printf 'sysop/runtime/\\n' > .gitignore", "git add -A", "git commit -qm base",
                "git branch feat/a"):
        assert _sh(root, cmd).returncode == 0, cmd
    (root / "sysop/scripts").mkdir(parents=True)
    for name in ("close_run.py", "pending_doc_hold.py"):
        shutil.copy2(SCRIPTS / name, root / "sysop/scripts" / name)
    return root


def _sh(cwd: Path, cmd: str, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, env=_ENV,
                          input=stdin if stdin is not None else b"")


def _hold(root: Path) -> dict:
    return json.loads((root / "sysop/runtime/close/holds/feat%2Fa.json").read_text(encoding="utf-8"))


def _stopped(root: Path) -> dict:
    return json.loads((root / "sysop/runtime/close" / RUN / "STOPPED").read_text(encoding="utf-8"))


def _one(path: Path, sub: str) -> str:
    found = command_blocks(text_of(path), rf"python3 sysop/scripts/close_run\.py {sub} ")
    assert len(found) == 1, found
    return found[0]


def _pwned(root: Path) -> list[str]:
    return sorted(p.name for p in root.glob("PWNED*"))


def test_the_prepares_hold_keeps_a_hostile_violation(repo: Path) -> None:
    cmd = (_one(PREPARE, "hold").replace("<run-id>", RUN).replace('"<branch>"', '"feat/a"')
           .replace("<first violation>", HOSTILE))
    assert not unfilled(cmd), cmd
    r = _sh(repo, cmd)
    assert r.returncode == 0, r.stderr
    assert _pwned(repo) == [] and _hold(repo)["reason"] == "VERDICT: BLOCKED: " + HOSTILE


def test_the_nights_stop_keeps_a_hostile_reason(repo: Path) -> None:
    cmd = (_one(NIGHT, "stop").replace("<run-id>", RUN).replace("<step>", "Step 4c")
           .replace("<reason>", HOSTILE).replace("<the step's own>", "finish on `merge/x`")
           .replace("<id> <id>", "T-1"))
    assert not unfilled(cmd), cmd
    r = _sh(repo, cmd)
    assert r.returncode == 0, r.stderr
    rec = _stopped(repo)
    assert _pwned(repo) == [] and rec["locks_kept"] == ["T-1"]
    assert rec["reason"] == HOSTILE + ". Recovery: finish on `merge/x`", rec


def test_the_retired_form_ran_the_text(repo: Path) -> None:
    """The premise: without it the two tests above prove nothing."""
    cmd = (RETIRED_HOLD.replace("<run-id>", RUN).replace('"<branch>"', '"feat/a"')
           .replace("<first violation>", HOSTILE))
    assert _sh(repo, cmd).returncode == 0
    assert _pwned(repo) == ["PWNED1", "PWNED2"] and "touch" not in _hold(repo)["reason"]


def test_a_block_copied_with_its_indent_still_records_the_reason(repo: Path) -> None:
    """Measured: a runner that keeps the list indent leaves the delimiter indented, bash never
    ends the heredoc, and the delimiter arrives as the reason's last line."""
    cmd = (f'python3 sysop/scripts/close_run.py hold "{RUN}" "feat/a" - <<\'SYSOP_REASON_EOF\'\n'
           "   VERDICT: BLOCKED: `x`\n   SYSOP_REASON_EOF")
    assert _sh(repo, cmd).returncode == 0
    assert _hold(repo)["reason"] == "VERDICT: BLOCKED: `x`"


@pytest.mark.parametrize("stdin,want", [
    (b"line one\n  line two\n", "line one line two"),
    (b"bad \xff byte\n", "bad � byte"),
])
def test_stdin_is_one_line_and_never_fails_to_decode(repo: Path, stdin: bytes, want: str) -> None:
    assert _sh(repo, f'python3 sysop/scripts/close_run.py hold "{RUN}" "feat/a" -', stdin).returncode == 0
    assert _hold(repo)["reason"] == want


def test_an_empty_stdin_still_records_a_stop_and_refuses_a_hold(repo: Path) -> None:
    r = _sh(repo, f'python3 sysop/scripts/close_run.py stop "{RUN}" "Step 4d" -')
    assert r.returncode == 0 and _stopped(repo)["reason"] == "(no reason on stdin)", r.stderr
    r = _sh(repo, f'python3 sysop/scripts/close_run.py hold "{RUN}" "feat/a" -')
    assert r.returncode == 2 and b"a hold needs its reason" in r.stderr


def test_a_closed_stdin_still_records_a_stop(repo: Path) -> None:
    """Round lens B: with fd 0 closed, `sys.stdin` is `None`, and the read raised."""
    r = _sh(repo, f'python3 sysop/scripts/close_run.py stop "{RUN}" "Step 4d" - <&-')
    assert r.returncode == 0 and _stopped(repo)["reason"] == "(no reason on stdin)", r.stderr


# The operand each subcommand takes its free text in (0-based, after the subcommand), and the
# filled shapes allowed there besides `-`: an id the runner chose, or a fixed form whose
# `<step>` is one of three literals (prepare-resume item 2).
_REASON_AT = {"hold": 2, "stop": 2, "park": 2, "unhold": 1}
_FIXED = {"unanswered: Q<n> (<step>)"}
_CALL = re.compile(r"close_run\.py[\"']? +(hold|stop|unhold|park)\b([^\n]*)")


def _population() -> list[Path]:
    """Every file a runner or an operator reads a command from, read as it is on disk."""
    return sorted([*(REPO / "core" / "skills").rglob("*.md"),
                   *(REPO / "core" / "companion" / "docs").rglob("*.md")])


def _bad_operand(line: str, m: re.Match) -> str:
    """The reason operand when it carries a placeholder in a shape the shell would read, or ""."""
    sub, rest = m.group(1), m.group(2)
    if line[:m.start()].count("`") % 2:  # inside an inline code span, which ends at its backtick
        rest = rest.split("`", 1)[0]
    try:
        words = shlex.split(rest.split("<<", 1)[0], posix=True)
    except ValueError:
        return rest  # unbalanced quotes: fail closed
    at = _REASON_AT[sub]
    if len(words) <= at:
        return ""
    w = words[at]
    return "" if w == "-" or "<" not in w or w in _FIXED else w


def test_no_shipped_reason_argument_carries_prose_in_quotes() -> None:
    bad, seen = [], 0
    for path in _population():
        # A backslash continuation is one command; read it as one line.
        for n, ln in enumerate(re.sub(r"\\\n\s*", " ", path.read_text(encoding="utf-8")).split("\n"), 1):
            for m in _CALL.finditer(ln):
                seen += 1
                w = _bad_operand(ln, m)
                if w:
                    bad.append(f"{path.relative_to(REPO)}:{n}: {m.group(1)} {w!r}")
    assert seen >= 4, seen  # both holds, the stop, Step 8's unhold
    assert not bad, bad


@pytest.mark.parametrize("line", [
    RETIRED_HOLD,
    'python3 sysop/scripts/close_run.py stop "<run-id>" "<step>" "<reason>. Recovery: <the step\'s own>"',
    '`python3 sysop/scripts/close_run.py unhold "<branch>" "<what was fixed>"`',
    'python3 "sysop/scripts/close_run.py" hold "<run-id>" "<branch>" "<why>"',
    'python3 sysop/scripts/close_run.py hold "<run-id>" "<branch>" "BLOCKED in `f`: <first violation>"',
    "python3 sysop/scripts/close_run.py hold \"<run-id>\" \"<branch>\" '<first violation>'",
    'python3 sysop/scripts/close_run.py hold "<run-id>" "<branch>" <first violation>',
    'python3 sysop/scripts/close_run.py park "<run-id>" relay "<the denied command>"',
])
def test_the_guard_reads_the_retired_and_bypass_shapes(line: str) -> None:
    m = _CALL.search(line)
    assert m and _bad_operand(line, m), line


@pytest.mark.parametrize("line", [
    'python3 sysop/scripts/close_run.py hold "<run-id>" "<branch>" - <<\'SYSOP_REASON_EOF\'',
    'python3 sysop/scripts/close_run.py hold "<run-id>" "<branch>" "unanswered: Q<n> (<step>)"',
    '`python3 sysop/scripts/close_run.py unhold "<branch>"`, to which the human adds a note',
    'python3 sysop/scripts/close_run.py stop "<run-id>" "<step>" - --locks-kept <id> <id> <<\'X\'',
])
def test_the_guard_passes_the_shipped_shapes(line: str) -> None:
    m = _CALL.search(line)
    assert m and not _bad_operand(line, m), line
