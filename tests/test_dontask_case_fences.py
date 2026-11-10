"""A shell `case` statement binds no permission rule under `dontAsk`, so no skill fence carries one.

Measured on Claude Code 2.1.319, in headless `dontAsk` sessions making one Bash call each on a
trusted scratch consumer (`tools/phase420_probe.py`; the log is `tools/phase476_probe_log.jsonl`):
`case 7 in *'<'*) echo bad ;; esac` alone is denied, and so are an `exit` anywhere (`echo ok;
exit 3`), `[[ … ]]`, `v='7'` followed by `echo "$v"` (where `v='7'` alone and `echo "$HOME"`
were admitted, and `echo "$TARGET_DATE"` alone was denied), `VAR=$(…)`, a quoted `$(…)`, `pwd -P`, `mkdir`, `date -v`/`-j`, and a `grep` whose regex
holds `{1,6}`. Admitted: `if [ … ]; then …; fi`, `>&2`, `date -u +…`, `grep -niE -A1` with `^#+`
and `\\b`, a `python3 -` heredoc under the seeded `Bash(python3 -:*)` rule, and
`git_check.py` under its own rule. So a placeholder guard written as `case … exit N ;; esac`
stopped the whole block, and the three that shipped (`/claim-task` Step 7e's Test-decision
read-back, `/auto-build`'s claim-directory mint, `/daily-summary` Step 1) were each denied as
written. They are now `git_check.py file … && grep …` (the line `/auto-build`'s own read-back
already shipped) and two `python3 -` heredocs, each probed admitted, whole, both substituted and
with its placeholder left in.

POPULATION: every bash/sh/shell/zsh fence in every shipped skill's runner text (core and packs,
step files spliced), except `/review-close`, which carries none today. `_shared/` partials are
not skills, so they are not read here. `tests/test_bash32_case_in_substitution.py` holds every
fence under `core/` at zero `case`, `/review-close` and `_shared/` included, so this module adds
the `dontAsk` reason, the per-site shapes and the runs, not the population. A heredoc body is the
interpreter's input, not shell, and a comment is prose, so neither is read.
"""
from __future__ import annotations

import datetime
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from skill_runner_text import text_of
from test_former_heredoc_scripts import _executable_fences, _skill_texts

REPO = Path(__file__).resolve().parents[1]
SKILLS = REPO / "core" / "skills"
CLAIM = SKILLS / "claim-task" / "SKILL.md"
BUILD = SKILLS / "auto-build" / "SKILL.md"
DAILY = SKILLS / "daily-summary" / "SKILL.md"

# `<<<` is a here-string, not a heredoc; a `<<` whose delimiter never closes is not skipped.
_HEREDOC = re.compile(r"(?<!<)<<-?(?!<)\s*['\"]?(\w+)['\"]?")
# `case` where a command starts: line start, after a separator, or after a compound keyword.
_CASE = re.compile(r"(?:^|[;&|(`{]|\b(?:then|do|else|elif)\b)\s*case\s+\S")
_ESAC = re.compile(r"(?<![\w-])esac(?![\w-])")


def case_lines(body: str) -> list[int]:
    """1-based lines of `body` (a shell fence) that open or close a `case` statement."""
    out: list[int] = []
    lines = body.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        code = _strip_comment(line)
        if _CASE.search(code) or _ESAC.search(code):
            out.append(i + 1)
        i = _past_heredoc(lines, i, code) + 1
    return out


def _strip_comment(line: str) -> str:
    """`line` up to a `#` that starts a shell comment: at a word start and outside quotes. A
    `" #"` inside a string is not one (Phase 476's round, lens 2: the split ate an `esac`)."""
    quote, k = "", 0
    while k < len(line):
        ch = line[k]
        if quote:
            if ch == "\\" and quote == '"':
                k += 1                      # the escaped character cannot close the string
            elif ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (k == 0 or line[k - 1].isspace()):
            return line[:k]
        k += 1
    return line


def _past_heredoc(lines: list[str], i: int, code: str) -> int:
    """The index of the delimiter line closing a heredoc opened on line `i`, else `i`."""
    m = _HEREDOC.search(code)
    if m:
        for j in range(i + 1, len(lines)):
            if lines[j].strip() == m.group(1):
                return j
    return i


def _population() -> list[tuple[str, str]]:
    return [(label, text) for label, text in _skill_texts()
            if not label.startswith("core/skills/review-close")]


def test_no_skill_shell_fence_carries_a_case_statement() -> None:
    found = [f"{label}: fence at line {ln}, body line(s) {hits}"
             for label, text in _population() for ln, body in _executable_fences(text)
             for hits in [case_lines(body)] if hits]
    assert not found, (
        "a `case` statement is denied under `dontAsk` (Claude Code 2.1.319, probed): write the "
        "guard as a `python3 -` heredoc or a shipped check script instead — " + "; ".join(found))


@pytest.mark.parametrize("body", [
    'case "$x" in a) : ;; esac',
    'case "$WEEK_DAYS" in\n  *\'<\'*)\n    echo bad >&2\n    exit 3 ;;\nesac',
    'v=$(case "$a" in b) echo b ;; esac)',
    "if true; then case x in y) : ;; esac; fi",
    'X="a"\ncase "$X" in *\'<\'*|*\'>\'*) exit 1 ;; esac\nmkdir "$X"',
])
def test_the_detector_finds_a_case_statement(body: str) -> None:
    assert case_lines(body), body


@pytest.mark.parametrize("body", [
    "# the `case` guard used to sit here; esac",
    "date -u +%Y%m%dT%H%M%SZ            # in that case, esac",
    "python3 - <<'PY'\ncase = 'esac'\nprint(case)\nPY",
    'echo "in that case"\ngrep -i case notes.md',
    "if [ 7 = 8 ]; then echo bad >&2; fi",
])
def test_the_detector_passes_what_is_not_one(body: str) -> None:
    assert case_lines(body) == [], body


def test_the_scan_reads_the_skills_it_names() -> None:
    labels = {label for label, _ in _population()}
    for skill in ("claim-task", "auto-build", "daily-summary"):
        assert f"core/skills/{skill}" in labels, f"the scan no longer reads {skill}"
    assert not any(label.startswith("core/skills/review-close") for label in labels)
    assert sum(1 for _, t in _population() for _ in _executable_fences(t)) > 100


# ── the three former `case` fences: one call a seeded rule admits ──────────────────────────

def _fence_with(path: Path, anchor: str) -> str:
    bodies = [b for _, b in _executable_fences(text_of(path)) if anchor in b]
    assert len(bodies) == 1, (path.name, anchor, len(bodies))
    return bodies[0]


def _shell_part(body: str) -> list[str]:
    """The fence's shell lines: comments, blank lines and heredoc bodies dropped."""
    out, lines, i = [], body.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        if line.strip() and not line.lstrip().startswith("#"):
            out.append(line)
            i = _past_heredoc(lines, i, line)
        i += 1
    return out


READBACK = ("python3 sysop/scripts/git_check.py file \"<WORKTREE_PATH>/<BODY_PATH_AS_RESOLVED>\" "
            "&& grep -niE -A1 '^#+[[:space:]]*test[[:space:]]+decision\\b' "
            "\"<WORKTREE_PATH>/<BODY_PATH_AS_RESOLVED>\"")


@pytest.mark.parametrize("path,anchor,first", [
    (CLAIM, 'git_check.py file "<WORKTREE_PATH>/<BODY_PATH_AS_RESOLVED>"', READBACK),
    (BUILD, 'CLAIM_DIR="sysop/runtime/claim/<TASK_ID>/<CYCLE_TS>"', "python3 - <<'PY'"),
    (DAILY, "--- WEEK_START:", "python3 - '<days>' <<'PY'"),
])
def test_each_former_case_fence_is_one_admitted_call(path: Path, anchor: str, first: str) -> None:
    """One command line, the shape probed admitted: no `exit`, `$(`, `case` or assignment."""
    assert _shell_part(_fence_with(path, anchor)) == [first], path


def test_claim_task_and_auto_build_read_the_record_back_with_one_line() -> None:
    """`/auto-build`'s item 3-record says it ships the same shape as `/claim-task` Step 7e."""
    for path in (CLAIM, BUILD):
        assert sum(1 for _, b in _executable_fences(text_of(path)) if READBACK in b) == 1, path


# ── executed ──────────────────────────────────────────────────────────────────────────────

def _bash(block: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", block], cwd=str(cwd), capture_output=True, text=True,
                          timeout=60)


@pytest.fixture
def body_dir(tmp_path: Path) -> Path:
    (tmp_path / "sysop" / "scripts").mkdir(parents=True)
    shutil.copy(REPO / "core" / "companion" / "scripts" / "git_check.py",
                tmp_path / "sysop" / "scripts" / "git_check.py")
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "has.md").write_text("# T\n\n## Test decision\nunit tests\n")
    (tmp_path / "tasks" / "lacks.md").write_text("# T\n\nnothing yet\n")
    return tmp_path


def _readback(tmp: Path, path: str) -> subprocess.CompletedProcess:
    block = _fence_with(CLAIM, "git_check.py file")
    return _bash(block.replace("<WORKTREE_PATH>/<BODY_PATH_AS_RESOLVED>", path), tmp)


def test_the_readback_refuses_a_placeholder_before_grep(body_dir: Path) -> None:
    r = _readback(body_dir, "<WORKTREE_PATH>/<BODY_PATH_AS_RESOLVED>")
    assert r.returncode == 3 and "not substituted" in r.stdout, (r.returncode, r.stdout)


def test_the_readback_names_a_missing_file_as_a_path_problem(body_dir: Path) -> None:
    r = _readback(body_dir, str(body_dir / "tasks" / "gone.md"))
    assert r.returncode == 1 and r.stdout.startswith("STOP: no such file"), r.stdout


def test_the_readback_prints_the_heading_and_the_line_under_it(body_dir: Path) -> None:
    r = _readback(body_dir, str(body_dir / "tasks" / "has.md"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "3:## Test decision" in r.stdout and "4-unit tests" in r.stdout, r.stdout


def test_the_readback_misses_a_body_without_the_record(body_dir: Path) -> None:
    r = _readback(body_dir, str(body_dir / "tasks" / "lacks.md"))
    assert r.returncode == 1 and "STOP:" not in r.stdout, r.stdout


def _mint(tmp: Path, task: str, cycle: str) -> subprocess.CompletedProcess:
    block = _fence_with(BUILD, 'CLAIM_DIR="sysop/runtime/claim/<TASK_ID>/<CYCLE_TS>"')
    return _bash(block.replace("<TASK_ID>", task).replace("<CYCLE_TS>", cycle), tmp)


@pytest.mark.parametrize("task,cycle", [("<TASK_ID>", "<CYCLE_TS>"), ("T-1", "<CYCLE_TS>"),
                                        ("<TASK_ID>", "20261108T000000Z")])
def test_the_mint_refuses_a_placeholder_with_exit_1_and_makes_nothing(
        tmp_path: Path, task: str, cycle: str) -> None:
    r = _mint(tmp_path, task, cycle)
    assert r.returncode == 1, r.stderr
    assert "Placeholder not substituted — refusing to mint the artifact directory." in r.stderr
    assert not (tmp_path / "sysop").exists()


def test_the_mint_prints_the_absolute_directory_once_and_refuses_it_again(tmp_path: Path) -> None:
    r = _mint(tmp_path, "T-1", "20261108T000000Z")
    made = tmp_path / "sysop" / "runtime" / "claim" / "T-1" / "20261108T000000Z"
    assert r.returncode == 0 and made.is_dir(), r.stderr
    assert r.stdout.strip() == f"CLAIM_DIR={made.resolve()}"
    again = _mint(tmp_path, "T-1", "20261108T000000Z")
    assert again.returncode == 1 and "File exists" in again.stderr, again.stderr
    assert "CLAIM_DIR=" not in again.stdout


def _daily(tmp: Path, days: str | None, date: str | None = None) -> subprocess.CompletedProcess:
    block = _fence_with(DAILY, "--- WEEK_START:")
    if days is not None:
        block = block.replace("'<days>'", days)
    if date is not None:
        lines = block.split("\n")
        idx = [i for i, ln in enumerate(lines) if ln.startswith("TARGET_DATE =")]
        assert len(idx) == 1, "the --date instruction needs exactly one TARGET_DATE line"
        # The replacement is the one the prose tells the runner to write, not a retyped copy:
        # the shell habit `TARGET_DATE=YYYY-MM-DD` is a Python syntax error (Phase 476's
        # round, lens 2).
        forms = re.findall(r"with\s+`(TARGET_DATE[^`]*)`", DAILY.read_text(encoding="utf-8"))
        assert len(forms) == 1, f"expected one --date replacement form in the prose: {forms}"
        assert "YYYY-MM-DD" in forms[0], forms[0]
        lines[idx[0]] = forms[0].replace("YYYY-MM-DD", date)
        block = "\n".join(lines)
    return _bash(block, tmp)


def _values(out: str) -> dict:
    vals = {}
    for line in out.strip().splitlines():
        k, _, v = line.replace("--- ", "").partition(":")
        vals[k.strip()] = v.strip()
    return vals


def test_daily_summary_refuses_an_unsubstituted_days_with_exit_3(tmp_path: Path) -> None:
    r = _daily(tmp_path, None)
    assert r.returncode == 3, r.returncode
    assert ("ERROR: substitute <days> (the --days value, default 7) before running Step 1."
            in r.stderr), r.stderr
    assert r.stdout == ""


def test_daily_summary_computes_yesterday_and_the_week(tmp_path: Path) -> None:
    r = _daily(tmp_path, "7")
    assert r.returncode == 0, r.stderr
    vals = _values(r.stdout)
    target = datetime.date.fromisoformat(vals["TARGET_DATE"])
    assert target == datetime.date.today() - datetime.timedelta(days=1)
    assert (target - datetime.date.fromisoformat(vals["WEEK_START"])).days == 7
    assert vals["DAY_NAME"] == target.strftime("%A")


def test_daily_summary_takes_the_date_override_on_its_one_line(tmp_path: Path) -> None:
    r = _daily(tmp_path, "7", "2026-08-10")
    assert r.returncode == 0, r.stderr
    assert "--- TARGET_DATE: 2026-08-10" in r.stdout
    assert "--- WEEK_START:  2026-08-03" in r.stdout
    assert "--- DAY_NAME:    Monday" in r.stdout


def test_daily_summary_refuses_a_days_value_that_is_not_a_number(tmp_path: Path) -> None:
    r = _daily(tmp_path, "'7d'")
    assert r.returncode == 3 and r.stderr.startswith("ERROR: --days must be a whole number"), r.stderr


@pytest.mark.parametrize("days", ["'-3'", "'99999999'", "'10000000000'"])
def test_daily_summary_refuses_a_negative_or_out_of_range_days(tmp_path: Path, days: str) -> None:
    """A negative `--days` put the week's start after its end, and one past `date`'s range
    raised a traceback with exit 1 (Phase 476's round, lens 1)."""
    r = _daily(tmp_path, days)
    assert r.returncode == 3 and r.stderr.startswith("ERROR: --days must be a whole number"), r.stderr


def test_a_brace_group_or_a_quoted_hash_does_not_hide_a_case() -> None:
    """Phase 476's round, lens 2: `{` was not an opener, and a `" #"` inside a string was read
    as a comment, which cut the `esac` off the line."""
    assert case_lines('{ case "$x" in a) echo " #" ;; esac; }') == [1]
    # Over lines, the opener alone marks line 1: `{` must be an opener, not only `esac`.
    assert case_lines('{ case "$x" in\n  a) : ;;\nesac; }') == [1, 3]
    assert case_lines('echo hi && { case "$x" in a) echo " #";; esac; }') == [1]
    # An escaped quote does not end the string, so the `#` after it is not a comment.
    assert case_lines('echo "a \\" #"; case x in y) : ;; esac') == [1]
    assert case_lines('echo hi # case x in y) ;; esac') == []


def test_a_here_string_or_an_unclosed_shift_does_not_hide_a_later_case() -> None:
    assert case_lines('grep x <<<"$v"\ncase "$v" in a) : ;; esac') == [2]
    assert case_lines('echo $((1<<2))\ncase "$v" in a) : ;; esac') == [2]


def test_daily_summary_names_the_one_rule_its_step_1_needs() -> None:
    """The pre-flight names `Bash(python3 -:*)`: Step 1 is a `python3 -` heredoc, and a
    pre-flight that called every call auto-approved was false (Phase 476's round, lens 2)."""
    pre = DAILY.read_text(encoding="utf-8").split("## Pre-flight", 1)[1].split("\n## ", 1)[0]
    assert "`Bash(python3 -:*)`" in pre, pre
    assert "every** permission mode" not in pre, pre
