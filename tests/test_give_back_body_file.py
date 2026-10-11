"""`Q-582`: the give-back skills' body file is the file `gh` reads, by construction.

`/report-issues` Step 4 and `/contribute-convention` Step 8 stage the consented issue body in
a file so it never rides the shell. Until Phase 370 both told the executor to `Write` the body
to `"${TMPDIR:-/tmp}/sysop-…md"` and then handed `gh --body-file` the same string. The `Write`
tool takes a literal path and expands nothing; the shell expands `${TMPDIR:-/tmp}`. Wherever
`TMPDIR` is set -- every macOS shell -- those are two different files, so `gh` read a missing
file or, worse, a stale one from an earlier run: the shown-equals-filed promise both steps
exist to keep, broken silently.

The fix resolves the path once, in a call of its own that only prints it, and has both the
`Write` and the `gh` call use the printed line. These tests run that resolve command, perform
the `Write` the step describes (a literal-path write, as the tool does), run the step's own
`gh` command against a stub, and assert the stub read the body that was written.

`/share-wins` Step 4 and `/release` Steps 8-9 carry the same shape. The end-to-end rows run
over `SITES` (the two `gh issue create` steps); the class-wide reader sweep at the bottom runs
over `READER_SKILLS`, which every skill that stages a file joins once its fix lands.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: skill -> (where its filing step starts, where it ends, the temp-name stem)
SITES = {
    "report-issues": (
        "**File it — pass the body as a file, never inline.**",
        "`gh issue create` prints the new issue URL",
        "sysop-issue-",
    ),
    "contribute-convention": (
        "**File it — pass the body as a file, never inline.**",
        "`gh issue create` prints the new issue URL",
        "sysop-pack-",
    ),
}

_FENCE = re.compile(r"^[ \t]*```bash\n(.*?)^[ \t]*```", re.S | re.M)
_PLACEHOLDER = "<body file>"
# Bodies are dense with backticks, `$` and quotes by design; this one would run a command if
# anything along the path interpolated it.
_BODY = "### What happened\n`run_checks` printed $(touch PWNED) and \"$HOME\" and 'x'.\n"


def _step(skill: str) -> str:
    start, end, _ = SITES[skill]
    text = (REPO / "core" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    i = text.find(start)
    assert i != -1, f"/{skill}: could not locate its filing step ({start!r}); re-point SITES"
    j = text.find(end, i)
    assert j != -1, f"/{skill}: the filing step's end marker ({end!r}) moved; re-point SITES"
    return text[i:j]


def _blocks(skill: str) -> list[str]:
    return [m.group(1) for m in _FENCE.finditer(_step(skill))]


def _resolve_command(skill: str) -> str:
    stem = SITES[skill][2]
    found = [b for b in _blocks(skill) if f"${{TMPDIR:-/tmp}}/{stem}" in b]
    assert len(found) == 1, (
        f"/{skill}: expected exactly one fenced block that resolves the body file's path, "
        f"found {len(found)}. Without it the executor has no single path to give both the "
        "`Write` tool and `gh`."
    )
    lines = [ln.strip() for ln in found[0].splitlines() if ln.strip()]
    assert len(lines) == 1 and lines[0].startswith("echo "), (
        f"/{skill}: the resolve block must be the one printing command, alone in its fence -- "
        f"a value does not survive into the next block, and anything else in the block can "
        f"cost it its permission match: {lines!r}"
    )
    # Fill the step's own name placeholder (`<id>`, `<pack>`) the way the executor does.
    return re.sub(r"<[a-z]+>", "X1", lines[0])


def _gh_command(skill: str) -> str:
    found = [b for b in _blocks(skill) if "gh issue create" in b]
    assert len(found) == 1, f"/{skill}: expected one `gh issue create` block, found {len(found)}"
    return found[0].strip()


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_") and k != "TMPDIR"}
    env.update(extra)
    return env


def _resolve(skill: str, cwd: Path, env: dict[str, str]) -> str:
    r = subprocess.run(["/bin/bash", "-c", _resolve_command(skill)], cwd=cwd, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = r.stdout.splitlines()
    assert len(out) == 1, f"the resolve command must print one line, printed {out!r}"
    return out[0]


@pytest.mark.parametrize("skill", sorted(SITES))
def test_gh_reads_the_file_the_body_was_written_to(skill: str, tmp_path: Path) -> None:
    """The defect, end to end: set `TMPDIR` as macOS does (trailing slash and all)."""
    tmpdir = tmp_path / "T"
    tmpdir.mkdir()
    work = tmp_path / "repo"
    work.mkdir()
    env = _env(tmp_path, TMPDIR=f"{tmpdir}/")

    body_file = _resolve(skill, work, env)

    # The `Write` tool: a literal path, no expansion.
    Path(body_file).write_text(_BODY, encoding="utf-8")

    stub = tmp_path / "bin"
    stub.mkdir()
    captured = tmp_path / "gh-read.md"
    (stub / "gh").write_text(
        "#!/bin/bash\n"
        'while [ $# -gt 0 ]; do\n'
        '  if [ "$1" = --body-file ]; then cp -- "$2" "$GH_OUT" && exit 0; exit 4; fi\n'
        "  shift\n"
        "done\n"
        "exit 3\n", encoding="utf-8")
    (stub / "gh").chmod(0o755)

    gh = _gh_command(skill)
    assert gh.count(_PLACEHOLDER) == 1, (
        f"/{skill}: the `gh` call must read `{_PLACEHOLDER}` -- the printed path -- and "
        f"nothing else: {gh!r}"
    )
    gh = (gh.replace(_PLACEHOLDER, body_file)
            .replace("<target>", "o/r").replace("<title>", "a title"))
    r = subprocess.run(["/bin/bash", "-c", gh], cwd=work,
                       env=dict(env, PATH=f"{stub}:/usr/bin:/bin", GH_OUT=str(captured)),
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        f"/{skill}: `gh` was not handed a readable body file (stub exit {r.returncode}); "
        f"command was {gh!r}\n{r.stderr}")
    assert captured.read_text(encoding="utf-8") == _BODY, (
        f"/{skill}: `gh` filed something other than the body that was written")
    assert not (work / "PWNED").exists(), "the body was interpolated by a shell"


@pytest.mark.parametrize("skill", sorted(SITES))
def test_the_gh_body_file_argument_expands_nothing(skill: str) -> None:
    """By construction: a `$` in `gh`'s path is a second resolution the `Write` never saw."""
    gh = _gh_command(skill)
    arg = re.search(r"""--body-file\s+('[^']*'|"[^"]*"|\S+)""", gh)
    assert arg, f"/{skill}: `gh` no longer takes the body as a file: {gh!r}"
    assert "$" not in arg.group(1) and arg.group(1) == f"'{_PLACEHOLDER}'", (
        f"/{skill}: `--body-file {arg.group(1)}` is resolved by the shell at call time, "
        "while the body was written by a tool that expands nothing")


@pytest.mark.parametrize("skill", sorted(SITES))
def test_the_write_and_the_cleanup_name_the_printed_path(skill: str, tmp_path: Path) -> None:
    step = _step(skill)
    write = re.search(r"Write the exact rendered body[^\n]*\n(?:[^\n]*\n){0,2}", step)
    assert write and _PLACEHOLDER in write.group(0), (
        f"/{skill}: the `Write` instruction no longer targets `{_PLACEHOLDER}`, so the body "
        "and `gh` can again name two different files")
    flat = " ".join(step.split())  # prose wraps at any word
    assert "`Read` that file, then `Write` again" in flat, (
        f"/{skill}: the arm for a file an earlier run left behind is gone. The `Write` tool "
        "refuses to overwrite a file it has not read, so without it a leftover stops the "
        "filing instead of being replaced")
    assert "does not begin with `/`" in flat and "stop and say so" in flat, (
        f"/{skill}: the stop for a denied or relative resolution is gone")

    rm = re.search(r"`(rm -f '<body file>')`", step)
    assert rm, f"/{skill}: the cleanup no longer names its command"
    body_file = tmp_path / "leftover.md"
    body_file.write_text("x", encoding="utf-8")
    r = subprocess.run(["/bin/bash", "-c", rm.group(1).replace(_PLACEHOLDER, str(body_file))],
                       env=_env(tmp_path), capture_output=True, text=True)
    assert r.returncode == 0 and not body_file.exists(), r.stderr


@pytest.mark.parametrize("skill", sorted(SITES))
def test_the_resolution_keeps_the_unset_and_relative_arms(skill: str, tmp_path: Path) -> None:
    """Unset falls back to `/tmp` (Phase 153); relative prints a path the step tells you to stop on.

    Only the printing command runs here -- nothing is written under `/tmp`.
    """
    stem = SITES[skill][2]
    unset = _resolve(skill, tmp_path, _env(tmp_path))
    assert unset.startswith(f"/tmp/{stem}") and unset.endswith(".md"), unset
    relative = _resolve(skill, tmp_path, _env(tmp_path, TMPDIR="t"))
    assert not relative.startswith("/"), relative


# The class, not just the two filing steps: every fenced command in these skills that READS a
# staged file must name it by a placeholder for the printed path, never by an expression the
# shell resolves on its own. `/share-wins` (`gh api … -F body=@…`) and `/release` (`git tag
# -F`, `gh release create --notes-file`) carry the same Write-then-read shape; Phase 370 fixed
# all four.
READER_SKILLS = ("report-issues", "contribute-convention", "share-wins", "release")

_STAGING_EXPR = re.compile(r"\$\{TMPDIR:-/tmp\}/sysop-[a-z]+-")
_PRINTING_ECHO = re.compile(r'(?:^\s*|`)echo "\$\{TMPDIR:-/tmp\}/sysop-[a-z]+-<[a-z]+>\.md"(?:`|\s*$)')


@pytest.mark.parametrize("skill", READER_SKILLS)
def test_every_staging_site_is_resolved_once_and_carries_both_arms(skill: str) -> None:
    """Each staging site, prose included (Phase 370's round: `/share-wins` and `/release`
    had only the fenced-reader sweep, and three of four mutations to them survived).

    The `${TMPDIR:-/tmp}` expression may appear only as the operand of the echo that
    prints it: anywhere else (a `Write` target, a reader) it names a different file from
    the one the other side uses. And every site keeps its leftover-file arm and its stop."""
    text = (REPO / "core" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    sites = [ln for ln in text.splitlines() if _STAGING_EXPR.search(ln)]
    assert sites, f"/{skill}: no staging site found; re-point the sweep"
    # Per occurrence, not per line: `/release` Step 9 is prose, so the echo and the
    # `Write` target share a line, and a line-level check passes a reverted target.
    stray = [ln.strip() for ln in sites
             if len(_STAGING_EXPR.findall(ln)) != len(_PRINTING_ECHO.findall(ln))]
    assert stray == [], (
        f"/{skill}: the staging expression appears outside its printing `echo`, so the "
        f"`Write` target and the reader can name different files: {stray}")
    flat = " ".join(text.split())
    arms = len(re.findall(r"`Read` (?:it|that file), then `Write` again", flat))
    stops = flat.count("does not begin with `/`")
    assert arms >= len(sites), f"/{skill}: {len(sites)} staging site(s), {arms} leftover-file arm(s)"
    assert stops >= len(sites), f"/{skill}: {len(sites)} staging site(s), {stops} stop arm(s)"

# `--file=`/`--file ` (git tag's long form) and `gh release create -F` (the short form of
# `--notes-file`) added by Phase 370's round: the sweep missed both.
_STAGED_READ = re.compile(
    r"""(?:--body-file|--notes-file|-F\s+body=@|git tag\b[^\n]*?\s(?:-F|--file[= ])|"""
    r"""gh release create\b[^\n]*?\s-F)\s*('[^']*'|"[^"]*"|\S+)""")


def staged_read_problems(text: str) -> list[str]:
    """Reader operands in `text`'s bash fences that the shell would resolve by itself."""
    problems = []
    for block in _FENCE.finditer(text):
        for m in _STAGED_READ.finditer(block.group(1)):
            operand = m.group(1)
            if "$" in operand or not re.fullmatch(r"'<[a-z ]+>'", operand):
                problems.append(m.group(0))
    return problems


@pytest.mark.parametrize("skill", READER_SKILLS)
def test_every_staged_file_reader_takes_the_printed_path(skill: str) -> None:
    text = (REPO / "core" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    assert _STAGED_READ.search(text), f"/{skill}: no staged-file reader found; re-point the sweep"
    problems = staged_read_problems(text)
    assert problems == [], (
        f"/{skill}: a command reads a staged file by a path the shell resolves, while the file "
        f"was written by a tool that expands nothing: {problems}")


def test_the_staged_read_sweep_sees_every_retired_spelling() -> None:
    retired = (
        "```bash\n"
        'gh issue create --repo o/r --body-file "${TMPDIR:-/tmp}/sysop-issue-<id>.md"\n'
        'gh release create v1 --title v1 --notes-file "${TMPDIR:-/tmp}/sysop-release-<v>.md"\n'
        'git tag -a "v1" -F "${TMPDIR:-/tmp}/sysop-tag-<version>.md"\n'
        '  -F body=@"${TMPDIR:-/tmp}/sysop-wins-<date>.md" \\\n'
        "gh issue create --body-file /tmp/sysop-issue-1.md\n"
        'git tag -a "v1" --file="${TMPDIR:-/tmp}/sysop-tag-<version>.md"\n'
        'gh release create v1 -F "${TMPDIR:-/tmp}/sysop-release-<v>.md"\n'
        "```\n"
    )
    assert len(staged_read_problems(retired)) == 7
    kept = (
        "```bash\n"
        "gh issue create --repo o/r --body-file '<body file>'\n"
        "git tag -a \"v1\" -F '<tag message file>'\n"
        "  -F body=@'<body file>' \\\n"
        "```\n"
    )
    assert staged_read_problems(kept) == []
