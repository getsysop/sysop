"""Phase 369 (`Q-655`): a `case` pattern inside `$(…)` must carry its leading `(`.

`/review-close` Step 1a builds its significant-change set with
`significant=$(… | while …; do … case "$target" in /*) : ;; … esac … done)`. bash 3.2 —
macOS's `/bin/bash`, which is what an agent gets when it runs a block with `/bin/bash` or
with bash first on `PATH` from `/bin` — reads a bare pattern's `)` as closing the command
substitution and fails with `syntax error near unexpected token ';;'`. bash 4+ and zsh parse
it. Phase 218 had met the class in Step 3c, blamed the `while` around the `case`, and moved that
block to a heredoc, so Step 1a kept it: 13 of the 18 tests in `test_worktree_primary_identity.py`
went red only when Phase 368's executor happened to have `/bin/bash` first on `PATH`. The
POSIX leading-paren form, `(/*) : ;;`, parses on every shell this repo meets.

Two legs, because neither is enough alone:

* a **static** scan of every shipped bash fence and every shipped shell script, which runs
  everywhere — CI included, where `/bin/bash` is bash 5 and could never catch this — and flags
  an unparenthesized pattern in a `case` that opens inside a substitution: `$(`, `<(` or `>(`,
  quoted or not;
* a **parse** leg that runs every shipped fence and script through `/bin/bash -n` when that
  binary is bash 3.x (a maintainer's Mac). It is NOT ground truth for the scanner: bash 3.2 does
  not parse a double-quoted `"$(…)"` until it expands it, so `x="$(case … b) … esac)"` passes
  `-n` and fails when run. The scanner's controls are therefore checked by running them, not
  only by `-n`; shipped text is never run.

The static scan is a character scanner over shell text, not a parser (see `scan`). Its
controls below are checked against the real bash 3.2 where one is installed, and
`test_step_1a_reverted_is_flagged` undoes the fix in the real file rather than a fixture.
Phase 369's own round and author pass refuted four earlier cuts: a line-based one that could
not see a substitution closing mid-line on a continuation (`… | head -1)`); one that missed
`<(…)`; one that reset its quote state each line and misread `close_batch.sh`'s multi-line awk
program; and one that popped a frame on a literal `)` inside double quotes (`"match(es)"`,
`"$((1+2))"`), which hid a bare pattern after it.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest
from skill_runner_text import text_of

REPO = Path(__file__).resolve().parents[1]
STEP_1A = REPO / "core/skills/review-close/SKILL.md"

#: Every Markdown file whose fences ship to a consumer.
SHIPPED = sorted([*REPO.glob("core/**/*.md"), *REPO.glob("packs/**/*.md")])


def _is_shell(path: Path) -> bool:
    if path.suffix == ".sh":
        return True
    first = path.read_text(encoding="utf-8", errors="replace").split("\n", 1)[0]
    return first.startswith("#!") and ("bash" in first or first.rstrip().endswith("/sh"))


#: Every shell script that ships, which an agent or a hook runs whole.
SCRIPTS = sorted(p for p in [REPO / "install.sh", *REPO.glob("core/**/*"), *REPO.glob("packs/**/*")]
                 if p.is_file() and "__pycache__" not in p.parts and _is_shell(p))

_OPEN = {"```bash", "```sh", "```shell"}
_QUOTE_PREFIX = re.compile(r"^\s*(?:>\s?)+")      # a fence inside a blockquote: `> ```bash`
# `<<WORD`, `<<-WORD`, `<<'WORD'`, `<<"WORD"`, `<<\WORD`; a delimiter may carry a hyphen.
_HEREDOC = re.compile(r"<<(-?)\s*\\?(['\"]?)([A-Za-z_][A-Za-z0-9_-]*)\2")
_COMMAND_START = re.compile(r"(^|[;|&({!]|\b(?:then|do|else|if|elif|while|until))\s*$")


def bash_fences(text: str) -> list[tuple[int, str]]:
    """(1-based opener line, body) for every bash/sh fence, blockquoted ones included."""
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        m = _QUOTE_PREFIX.match(lines[i])
        prefix = m.group(0) if m else ""
        if lines[i][len(prefix):].strip() in _OPEN:
            unq = lambda s: s[len(prefix):] if s.startswith(prefix) else s.lstrip("> ")  # noqa: E731
            j = i + 1
            while j < len(lines) and unq(lines[j]).strip() != "```":
                j += 1
            out.append((i + 1, "\n".join(unq(x) for x in lines[i + 1:j])))
            i = j
        i += 1
    return out


def _word_at(line: str, i: int, word: str) -> bool:
    end = i + len(word)
    return (line.startswith(word, i) and (i == 0 or line[i - 1] in " \t;|&(")
            and (end == len(line) or line[end] in " \t;)"))


def _skip_braces(line: str, i: int) -> int:
    """Index just past the `}` that closes the `${` at `i` (a `)` inside is not a frame)."""
    depth, i = 1, i + 2
    while i < len(line) and depth:
        if line.startswith("${", i):
            depth, i = depth + 1, i + 2
            continue
        depth -= line[i] == "}"
        i += 1
    return i


def scan(body: str) -> tuple[list[tuple[int, str]], int, int]:
    """(violations, cases seen, cases opened inside a substitution) for one fence body.

    A character scanner, not a parser. It tracks quotes (across lines, `$'…'` included),
    comments, heredoc bodies (opened only at an unquoted position outside arithmetic), `${…}`
    expansions, a stack of open frames, and, per open `case`, whether the next token is a
    pattern. Frames are `(` (a subshell or a grouping paren), `$((` (arithmetic), `$(` (also
    `<(` and `>(`) and `$("` (a `$(` opened inside double quotes, whose `)` returns to them).
    A pattern's closing `)` is consumed by the pattern, never popped off the frame stack —
    which is the distinction bash 3.2 gets wrong inside a substitution, quoted or not.
    """
    violations, cases, nested = [], 0, 0
    frames: list[str] = []
    cases_open: list[dict] = []     # {"in_sub", "state": "in"|"pattern"|"body"}
    heredocs: list[str] = []        # delimiters whose bodies start on the next line
    quote = None                    # persists across lines: a quoted awk program spans many
    for n, line in enumerate(body.splitlines(), 1):
        if heredocs:
            if line.strip() == heredocs[0]:
                heredocs.pop(0)
            continue
        i = 0
        while i < len(line):
            ch = line[i]
            if quote == "'":
                quote = None if ch == "'" else quote
                i += 1
                continue
            if quote == "$'":               # ANSI-C: `\'` does not end it
                if ch == "\\":
                    i += 2
                    continue
                quote = None if ch == "'" else quote
                i += 1
                continue
            if ch == "\\":
                i += 2
                continue
            if quote == '"':
                # Literal parens inside double quotes are text. A `$(` opens a frame whose
                # contents are unquoted again, and its `)` returns to the double quote.
                if ch == '"':
                    quote = None
                elif line.startswith("$((", i):
                    i += 3                  # arithmetic in quotes: text to this scanner
                    continue
                elif line.startswith("$(", i):
                    frames.append('$("')
                    quote = None
                    i += 2
                    continue
                i += 1
                continue
            if line.startswith("$'", i):
                quote = "$'"
                i += 2
                continue
            if ch in "'\"":
                quote = ch
                i += 1
                continue
            if ch == "#" and (i == 0 or line[i - 1] in " \t;(|&"):
                break
            if line.startswith("${", i):
                i = _skip_braces(line, i)
                continue
            if line.startswith("<<<", i):     # a here-string: no body follows
                i += 3
                continue
            if line.startswith("<<", i) and "$((" not in frames:
                m = _HEREDOC.match(line, i)
                if m:
                    heredocs.append(m.group(3))
                    i = m.end()
                    continue
            top = cases_open[-1] if cases_open else None
            if top and top["state"] == "pattern" and ch not in " \t":
                if _word_at(line, i, "esac"):
                    cases_open.pop()
                    i += 4
                    continue
                if ch == "(":
                    i += 1
                elif top["in_sub"]:
                    violations.append((n, line.strip()))
                pq = None               # a quoted `)` does not end the pattern
                while i < len(line) and not (line[i] == ")" and pq is None):
                    if pq and line[i] == pq:
                        pq = None
                    elif pq is None and line[i] in "'\"":
                        pq = line[i]
                    i += 1
                top["state"] = "body"
                i += 1
                continue
            if top and top["state"] == "in" and _word_at(line, i, "in"):
                top["state"] = "pattern"
                i += 2
                continue
            if top and top["state"] == "body":
                if line.startswith(";;", i):
                    top["state"] = "pattern"
                    i += 2
                    continue
                if _word_at(line, i, "esac"):
                    cases_open.pop()
                    i += 4
                    continue
            if _word_at(line, i, "case") and _COMMAND_START.search(line[:i]):
                cases += 1
                # Quoted or not: bash 3.2 defers a `"$(…)"` until it runs, then fails the same
                # way, so `bash -n` passes it and only execution shows the error.
                in_sub = any(f in ("$(", '$("') for f in frames)
                nested += in_sub
                cases_open.append({"in_sub": in_sub, "state": "in"})
                i += 4
                continue
            if line.startswith("$((", i):
                frames.append("$((")
                i += 3
                continue
            # `<(…)` and `>(…)` are substitutions too, and bash 3.2 misreads a pattern inside
            # them the same way (a hostile-corpus case the first scanner missed).
            if line.startswith(("$(", "<(", ">("), i):
                frames.append("$(")
                i += 2
                continue
            if ch == "(":
                frames.append("(")
            elif ch == ")" and frames:
                top_frame = frames.pop()
                if top_frame == '$("':
                    quote = '"'
                elif top_frame == "$((" and line.startswith(")", i + 1):
                    i += 1                  # `))` closes arithmetic
            i += 1
    return violations, cases, nested


def _placeholders(body: str) -> str:
    # Upper case too: `<TASK_ID>`, `<WORKTREE_PATH>`, `<N1>` (a lower-case-only pattern left 23
    # fences unparseable under every bash, so the parse leg skipped them).
    return re.sub(r"<[A-Za-z][A-Za-z0-9 _/.,:=-]*>", "PLACEHOLDER", body)


PRE_FIX = """significant=$(printf '%s\\n' "$porcelain" | while IFS= read -r line; do
  if [[ -L "$entry" ]]; then
    target=$(readlink "$entry")
    case "$target" in
      /*) : ;;
      *)  target=$(cd "$(dirname "$entry")" && printf '%s' "$PWD") ;;
    esac
  fi
  printf '%s\\n' "$line"
done)
"""
FIXED = PRE_FIX.replace("      /*) :", "      (/*) :").replace("      *)  target", "      (*)  target")
# Not inside a substitution: a pipeline into `while` is a subshell, not `$(`. Step 3b's twin.
PIPELINE = """printf '%s\\n' "$x" | while IFS= read -r line; do
  case "$line" in
    /*) : ;;
    *)  echo "$line" ;;
  esac
done
"""
ONE_LINE = 'v=$(case "$a" in b) echo b ;; esac)\n'
ONE_LINE_FIXED = 'v=$(case "$a" in (b) echo b ;; esac)\n'
PROC_SUBST = 'diff <(case "$a" in b) : ;; esac) /dev/null\n'
# `close_batch.sh`'s shape: a multi-line single-quoted awk program inside `"$(…)"`. A scanner
# that reset its quote state per line read the `case` after it as nested.
QUOTED_SPAN = """w="$(awk '
  /^x/ { print $1 }
' f)" || w=""
case "$w" in
  a|b) echo "$w" ;;
  *)   echo a ;;
esac
"""
CONTINUED = 'x=$(printf x \\\n  | while read l; do case "$l" in b) : ;; esac; done)\n'
AFTER_HEREDOC = 'x=$(cat <<EOF\n)\nEOF\ncase "$a" in b) : ;; esac\n)\n'
CLOSED_MIDLINE = """p=$(git worktree list \\
  | awk '{print; exit}')
case "$p" in
  /*) : ;;
esac
"""
# A plain `( … )` subshell is not a substitution: bash 3.2 parses a bare pattern inside it.
SUBSHELL = '( case "$a" in b) : ;; esac )\n'
COMMENTED = 'x=$(echo hi # )\n)\ncase "$a" in b) : ;; esac\n'
# A `$(` inside double quotes, nested in an outer one: its `)` must pop its own frame.
DQ_INNER = 'x=$(f "$(g)"\ncase "$a" in b) : ;; esac\n)\n'
QUOTED_PAREN = 'x=$(case "$a" in ("a)b") : ;; c) : ;; esac)\n'
QUOTED_PAREN_FIXED = 'x=$(case "$a" in ("a)b") : ;; (c) : ;; esac)\n'
# Literal and arithmetic parens inside "…" are not frames, and `$'\''` does not end at `\'`.
DQ_PARENS = 'x=$(echo "match(es)"\ncase "$a" in b) : ;; esac\n)\n'
DQ_ARITH = 'x=$(echo "$((1+2))"\ncase "$a" in b) : ;; esac\n)\n'
ANSI_C = "x=$(echo $'a\\'b'\ncase \"$a\" in b) : ;; esac\n)\n"
# bash 3.2 defers a double-quoted substitution: `bash -n` passes it, and running it fails.
DQ_WRAPPED = 'a=b; x="$(case "$a" in b) echo hit ;; esac)"\n'
DQ_WRAPPED_FIXED = 'a=b; x="$(case "$a" in (b) echo hit ;; esac)"\n'
# The round's shapes (lenses 1 and 2): each blinded an earlier scanner, or was a false red.
NESTED_SUBSHELL = 'x=$( ( case "$a" in b) : ;; esac ) )\n'
HERE_STRING = 'n=$(grep -c x <<<"abc")\ny=$(case "$a" in b) : ;; esac)\n'
HEREDOC_IN_COMMENT = '# see <<EOF below\nx=$(case "$a" in b) : ;; esac)\n'
COMMENT_AFTER_PAREN = 'x=$(# note )\ncase "$a" in b) : ;; esac\n)\n'
BRACE_PAREN = 'x=$(y=${z%)}; case "$a" in b) : ;; esac)\n'
ARITH_SHIFT = 'x=$(mask=$((1 << bits))\ncase "$a" in b) : ;; esac\n)\n'
LOG_LINE = ('x=$(printf x | while read e; do echo "skip ($e)" >&2\n'
            'case "$e" in .*) : ;; esac; done)\n')
CASE_AS_ARGUMENT = 'x=$(echo case in foo)\n'
BACKSLASH_HEREDOC = 'cat <<\\EOF\nx=$(\nEOF\ncase "$a" in b) : ;; esac\n'
CONTROLS = [("nested subshell", NESTED_SUBSHELL, True), ("here-string", HERE_STRING, True),
            ("heredoc word in a comment", HEREDOC_IN_COMMENT, True),
            ("comment after (", COMMENT_AFTER_PAREN, True), ("${…)}", BRACE_PAREN, True),
            ("arithmetic shift", ARITH_SHIFT, True), ("log line", LOG_LINE, True),
            ("case as an argument", CASE_AS_ARGUMENT, False),
            ("backslash heredoc body", BACKSLASH_HEREDOC, False),
            ("dq parens", DQ_PARENS, True), ("dq arithmetic", DQ_ARITH, True),
            ("ansi-c quote", ANSI_C, True), ("dq-wrapped", DQ_WRAPPED, True),
            ("dq-wrapped fixed", DQ_WRAPPED_FIXED, False),
            ("dq inner substitution", DQ_INNER, True), ("quoted paren", QUOTED_PAREN, True),
            ("quoted paren fixed", QUOTED_PAREN_FIXED, False), ("subshell", SUBSHELL, False), ("comment", COMMENTED, False),
            ("process substitution", PROC_SUBST, True), ("quoted span", QUOTED_SPAN, False),
            ("continued line", CONTINUED, True), ("heredoc first", AFTER_HEREDOC, True),
            ("closed mid-line", CLOSED_MIDLINE, False), ("pre-fix Step 1a", PRE_FIX, True), ("fixed Step 1a", FIXED, False),
            ("pipeline, no $(", PIPELINE, False), ("one-line in $(", ONE_LINE, True),
            ("one-line fixed", ONE_LINE_FIXED, False)]


@pytest.mark.parametrize("label,body,flagged", CONTROLS, ids=[c[0] for c in CONTROLS])
def test_static_scan_controls(label, body, flagged):
    assert bool(scan(body)[0]) is flagged, f"{label}: scan says {scan(body)[0]!r}"


def test_no_shipped_fence_has_a_bare_pattern_inside_a_substitution():
    found, cases, nested = [], 0, 0
    units = [(md, start, body) for md in SHIPPED
             for start, body in bash_fences(md.read_text(encoding="utf-8"))]
    units += [(sh, 0, sh.read_text(encoding="utf-8")) for sh in SCRIPTS]
    script_cases = 0
    for path, start, body in units:
        v, c, s = scan(body)
        cases += c
        script_cases += c if not start else 0
        nested += s
        found += [f"{path.relative_to(REPO)}:{start + n}: {text}" for n, text in v]
    assert not found, "bash 3.2 cannot parse these (add the leading `(`):\n" + "\n".join(found)
    # Floors, so a scanner that stops seeing fences or `case` cannot pass by seeing nothing.
    assert len(SCRIPTS) >= 10, f"only {len(SCRIPTS)} shipped shell scripts found"
    # Named members, because a count floor does not notice a population losing a whole kind.
    names = {str(p.relative_to(REPO)) for p in [*SHIPPED, *SCRIPTS]}
    for member in ("install.sh", "core/companion/git-hooks/pre-commit",
                   "core/companion/git-hooks/examples/pre-commit-python.example",
                   "core/companion/scripts/close_batch.sh", "core/companion/docs/WORKFLOW.md",
                   "core/skills/review-close/SKILL.md", "core/skills/_shared/main-push-guard.md",
                   "packs/python/companion/convention_map.md"):
        assert member in names, f"{member} fell out of the scanned population"
    fences = sum(1 for path, start, _ in units if start)
    assert fences >= 200, f"only {fences} shipped bash fences found"
    assert cases - script_cases >= 15, f"only {cases - script_cases} `case` statements in fences"
    assert script_cases >= 50, f"only {script_cases} `case` statements in shipped scripts"
    assert nested >= 1, "the scan no longer reaches a `case` inside `$(` — Step 1a's is one"


def test_a_blockquoted_fence_is_read():
    """`> ```bash` fences ship too (four in `/review-close`); the prefix is stripped."""
    assert bash_fences("text\n> ```bash\n> x=$(case \"$a\" in b) : ;; esac)\n> ```\n") == [
        (2, 'x=$(case "$a" in b) : ;; esac)')]


def test_step_1a_reverted_is_flagged():
    """The real file, with the fix undone, must be caught — not only the fixture."""
    text = text_of(STEP_1A)
    assert "          (/*) : ;;" in text and "          (*)  target=$(cd" in text
    reverted = text.replace("          (/*) : ;;", "          /*) : ;;", 1)
    assert any(scan(body)[0] for _, body in bash_fences(reverted))


#: The one bash 3.2 every leg below runs. A single name, so a mutation that points one leg at
#: the `bash` on `PATH` (bash 5 on a Mac with Homebrew first) cannot leave the others honest.
BASH32 = "/bin/bash"


def _bash32() -> bool:
    try:
        out = subprocess.run([BASH32, "--version"], capture_output=True, text=True).stdout
    except OSError:
        return False
    return "version 3." in out


needs_bash32 = pytest.mark.skipif(not _bash32(), reason="/bin/bash is not bash 3.x")


@pytest.mark.skipif(sys.platform != "darwin", reason="only macOS ships bash 3.2 as /bin/bash")
def test_the_bash32_legs_run_on_macos():
    """On a Mac the legs below must run, not skip: a broken version probe skips them silently."""
    assert _bash32(), f"{BASH32} on macOS is not reported as bash 3.x; the 3.2 legs are skipping"


def _parses_with(shell: str, body: str) -> bool:
    r = subprocess.run([shell, "-n"], input=_placeholders(body), capture_output=True, text=True)
    return r.returncode == 0


def _parses(body: str) -> bool:
    return _parses_with(BASH32, body)


def _fails_when_run(body: str, tmp: Path) -> bool:
    """Run a CONTROL (never shipped text) under bash 3.2; True on a syntax error.

    `bash -n` is not enough: bash 3.2 does not parse a double-quoted `"$(…)"` until it
    expands it, so the `dq-wrapped` control passes `-n` and fails here.
    """
    r = subprocess.run([BASH32, "-c", body], cwd=tmp, capture_output=True, text=True,
                       timeout=20, stdin=subprocess.DEVNULL)
    return "syntax error" in r.stderr


@needs_bash32
@pytest.mark.parametrize("label,body,flagged", CONTROLS, ids=[c[0] for c in CONTROLS])
def test_bash32_agrees_with_the_static_controls(label, body, flagged, tmp_path):
    rejected = not _parses(body) or _fails_when_run(body, tmp_path)
    assert rejected is flagged, f"{label}: bash 3.2 and the static scan disagree"


def test_every_shipped_fence_parses():
    """Every shipped fence is valid shell under the `bash` on `PATH` (bash 5 in CI).

    This keeps the bash-3.2 leg below honest: it used to excuse any fence bash 5 could not
    parse either, and its lower-case-only placeholder pattern made 23 fences (`<TASK_ID>`,
    `<WORKTREE_PATH>`, `<N1>`) unparseable, so 23 of 223 were never read. Without an excuse,
    narrowing the placeholder pattern again goes red here, in CI.
    """
    failed = [f"{md.relative_to(REPO)}:{start}"
              for md in SHIPPED
              for start, body in bash_fences(md.read_text(encoding="utf-8"))
              if not _parses_with("bash", body)]
    assert not failed, "not valid shell (fix the fence or its placeholder):\n" + "\n".join(failed)


@needs_bash32
def test_every_shipped_fence_parses_under_bash32():
    failed = [f"{md.relative_to(REPO)}:{start}"
              for md in SHIPPED
              for start, body in bash_fences(md.read_text(encoding="utf-8"))
              if not _parses(body)]
    assert not failed, "/bin/bash 3.2 cannot parse:\n" + "\n".join(failed)


@needs_bash32
def test_every_shipped_script_parses_under_bash32():
    failed = [str(sh.relative_to(REPO)) for sh in SCRIPTS
              if subprocess.run([BASH32, "-n", str(sh)], capture_output=True).returncode]
    assert not failed, "/bin/bash 3.2 cannot parse:\n" + "\n".join(failed)
