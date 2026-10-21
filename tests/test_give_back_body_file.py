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

Phase 377 (`Q-663`) moved the staged file from `${TMPDIR:-/tmp}` into the project, under
`sysop/runtime/giveback/`: under `dontAsk` a `Write` no rule covers is denied, in-project or
not, and only an `Edit(...)` rule admits it. The seeded `Edit(/sysop/runtime/giveback/**)`
is that rule, measured in a headless `dontAsk` session (`PHASE_LOG.md` § Phase 377). The
resolve command is
`echo "$(git rev-parse --show-toplevel)/$(git rev-parse --show-prefix)sysop/runtime/giveback/<name>"`,
the physical working directory spelled through git. Round 1 measured `$PWD` (logical through a
symlinked launch) denied; round 2 measured bare `--show-toplevel` (the git root, not a
subdirectory install's root) stopping every post; `pwd -P` is itself denied under `dontAsk`.

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
from skill_runner_text import skill_text

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
_TOP = "$(git rev-parse --show-toplevel)/$(git rev-parse --show-prefix)"
# Bodies are dense with backticks, `$` and quotes by design; this one would run a command if
# anything along the path interpolated it.
_BODY = "### What happened\n`run_checks` printed $(touch PWNED) and \"$HOME\" and 'x'.\n"


def _step(skill: str) -> str:
    start, end, _ = SITES[skill]
    text = skill_text(REPO / "core" / "skills" / skill)   # step files too (Phase 384)
    i = text.find(start)
    assert i != -1, f"/{skill}: could not locate its filing step ({start!r}); re-point SITES"
    j = text.find(end, i)
    assert j != -1, f"/{skill}: the filing step's end marker ({end!r}) moved; re-point SITES"
    return text[i:j]


def _blocks(skill: str) -> list[str]:
    return [m.group(1) for m in _FENCE.finditer(_step(skill))]


def _resolve_command(skill: str) -> str:
    stem = SITES[skill][2]
    found = [b for b in _blocks(skill) if f"{_TOP}sysop/runtime/giveback/{stem}" in b]
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


def _git_init(path: Path, env: dict[str, str]) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=env)


def _resolve(skill: str, cwd: Path, env: dict[str, str]) -> str:
    r = subprocess.run(["/bin/bash", "-c", _resolve_command(skill)], cwd=cwd, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = r.stdout.splitlines()
    assert len(out) == 1, f"the resolve command must print one line, printed {out!r}"
    return out[0]


@pytest.mark.parametrize("skill", sorted(SITES))
def test_gh_reads_the_file_the_body_was_written_to(skill: str, tmp_path: Path) -> None:
    """The defect, end to end, with `TMPDIR` set as macOS sets it (trailing slash and all):
    the staged path must not depend on it."""
    tmpdir = tmp_path / "T"
    tmpdir.mkdir()
    work = tmp_path / "repo"
    work.mkdir()
    env = _env(tmp_path, TMPDIR=f"{tmpdir}/")
    _git_init(work, env)

    body_file = _resolve(skill, work, env)
    assert Path(body_file).parent == work.resolve() / "sysop" / "runtime" / "giveback", body_file

    # The `Write` tool: a literal path, no expansion, and it creates missing parents.
    Path(body_file).parent.mkdir(parents=True)
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
    assert "is not the project root" in flat and "stop and say so" in flat, (
        f"/{skill}: the stop for a denied or relative resolution is gone")

    rm = re.search(r"`(rm -f '<body file>')`", step)
    assert rm, f"/{skill}: the cleanup no longer names its command"
    body_file = tmp_path / "leftover.md"
    body_file.write_text("x", encoding="utf-8")
    r = subprocess.run(["/bin/bash", "-c", rm.group(1).replace(_PLACEHOLDER, str(body_file))],
                       env=_env(tmp_path), capture_output=True, text=True)
    assert r.returncode == 0 and not body_file.exists(), r.stderr


@pytest.mark.parametrize("skill", sorted(SITES))
def test_the_staged_path_is_the_one_the_seeded_rule_admits(skill: str, tmp_path: Path) -> None:
    """`Q-663`: the path is under the project root whatever `TMPDIR` says, and the template's
    `Edit` rule covers it. A `Write(...)` rule would not (it is not consulted), and a path
    outside the project would need a per-machine absolute rule nobody can seed."""
    stem = SITES[skill][2]
    _git_init(tmp_path, _env(tmp_path))
    for env in (_env(tmp_path), _env(tmp_path, TMPDIR="t"), _env(tmp_path, TMPDIR="/elsewhere/")):
        printed = Path(_resolve(skill, tmp_path, env))
        rel = printed.relative_to(tmp_path.resolve())
        assert str(rel).startswith(f"sysop/runtime/giveback/{stem}"), printed
    assert "sysop/runtime/giveback/" in _seeded_edit_prefixes(_template_allow())


@pytest.mark.parametrize("skill", sorted(SITES))
def test_the_staged_path_is_the_physical_install_root(skill: str, tmp_path: Path) -> None:
    """Both rounds' measured shapes. Round 1: launched through a symlink (macOS `/tmp`), `$PWD`
    printed the logical path and `dontAsk` denied the `Write`. Round 2: in a Sysop install
    in a subdirectory of its repo (`install.sh` supports it), bare `--show-toplevel` printed the
    git root, outside the install, so every post stopped. The resolver must print the physical
    install root in both, and a drifted cwd must print something the stop arm refuses."""
    real = tmp_path / "real"
    app = real / "app"
    (app / "src").mkdir(parents=True)
    _git_init(real, _env(tmp_path))
    link = tmp_path / "link"
    link.symlink_to(real)
    for launch, root in ((link, real), (link / "app", app), (app, app)):
        printed = Path(_resolve(skill, launch, _env(tmp_path, PWD=str(launch))))
        assert printed.parent == root.resolve() / "sysop" / "runtime" / "giveback", (launch, printed)
    drifted = Path(_resolve(skill, link / "app" / "src", _env(tmp_path, PWD=str(link / "app" / "src"))))
    assert not str(drifted).startswith(str(app.resolve() / "sysop")), (
        f"a drifted cwd printed a path under the install root, which the arm would pass: {drifted}")


# The class, not just the two filing steps: every fenced command in these skills that READS a
# staged file must name it by a placeholder for the printed path, never by an expression the
# shell resolves on its own. `/share-wins` (`gh api … -F body=@…`) and `/release` (`git tag
# -F`, `gh release create --notes-file`) carry the same Write-then-read shape; Phase 370 fixed
# all four.
READER_SKILLS = ("report-issues", "contribute-convention", "share-wins", "release")

_RESOLVER = r"\$\(git rev-parse --show-toplevel\)/\$\(git rev-parse --show-prefix\)"
_STAGING_EXPR = re.compile(_RESOLVER + r"sysop/runtime/giveback/sysop-[a-z]+-")
_PRINTING_ECHO = re.compile(
    r'(?:^\s*|`)echo "' + _RESOLVER + r'sysop/runtime/giveback/sysop-[a-z]+-<[a-z]+>\.md"(?:`|\s*$)')


@pytest.mark.parametrize("skill", READER_SKILLS)
def test_every_staging_site_is_resolved_once_and_carries_both_arms(skill: str) -> None:
    """Each staging site, prose included (Phase 370's round: `/share-wins` and `/release`
    had only the fenced-reader sweep, and three of four mutations to them survived).

    The `$(git rev-parse …)/…` expression may appear only as the operand of the echo that
    prints it: anywhere else (a `Write` target, a reader) it names a different file from
    the one the other side uses. And every site keeps its leftover-file arm and its stop."""
    text = skill_text(REPO / "core" / "skills" / skill)   # step files too (Phase 384)
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
    stops = flat.count("is not the project root")
    quotes = flat.count("or it contains a `'`")
    assert quotes >= len(sites), (
        f"/{skill}: {len(sites)} staging site(s), {quotes} quote arm(s). Every reader takes the "
        "path single-quoted, so a `'` in the project root is a syntax error at the reader")
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
    text = skill_text(REPO / "core" / "skills" / skill)   # step files too (Phase 384)
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


# `Q-663` (Phase 377): what the rule and the location buy, asserted from the files that ship.
_TEMPLATE = REPO / "core" / "companion" / ".claude" / "settings.json"


def _template_allow() -> list[str]:
    import json
    return json.loads(_TEMPLATE.read_text(encoding="utf-8"))["permissions"]["allow"]


def _seeded_edit_prefixes(allow: list[str]) -> set[str]:
    """Project-root-relative prefixes the template's `Edit(/…/**)` rules admit."""
    return {m.group(1) for r in allow if (m := re.fullmatch(r"Edit\(/(.+/)\*\*\)", r))}


def test_the_staging_rule_is_scoped_to_giveback_alone() -> None:
    """Wade's ruling (Phase 374): not `sysop/runtime/**`, which would also admit edits to
    lock files in every mode, without a prompt."""
    edits = sorted(r for r in _template_allow() if r.startswith(("Edit(", "Write(")))
    assert edits == ["Edit(/sysop/SYSOP_ISSUES.md)", "Edit(/sysop/runtime/giveback/**)"], edits


@pytest.mark.parametrize("skill", READER_SKILLS)
def test_no_give_back_skill_stages_outside_the_project(skill: str) -> None:
    text = skill_text(REPO / "core" / "skills" / skill)   # step files too (Phase 384)
    assert "TMPDIR" not in text and "/tmp/" not in text, (
        f"/{skill}: a staging site names the system temp directory again; under `dontAsk` "
        "a `Write` there is denied and no rule can be seeded for it")


_ALL_SKILLS = sorted(p.parent.name for p in (REPO / "core" / "skills").glob("*/SKILL.md"))


@pytest.mark.parametrize("skill", _ALL_SKILLS)
def test_no_skill_says_a_file_edit_needs_no_rule(skill: str) -> None:
    """Measured false under `dontAsk` (Phase 377): an in-project `Edit` no rule covers is denied.
    Every skill, not the four: Phase 377's round found `/onboard`, `/add-task` and `/intake`
    carrying the same claim as "file-level, not Bash-gated"."""
    flat = " ".join(skill_text(REPO / "core" / "skills" / skill).split())
    for claim in ("needs no allow-rule", "needs **no new permission rules.**"):
        assert claim not in flat, f"/{skill}: says {claim!r}, which is false under `dontAsk`"
    # "not Bash-gated" is true of `Read` (an in-project `Read` is admitted), false of a write.
    assert not re.search(r"(?:Write|Edit)\b[^.]{0,60}not Bash-gated", flat), (
        f"/{skill}: calls a `Write`/`Edit` 'not Bash-gated' as if it needed no rule")


def test_the_edit_claim_sweep_reaches_every_skill() -> None:
    assert len(_ALL_SKILLS) > 20 and {"onboard", "add-task", "intake", "release"} <= set(_ALL_SKILLS)


def test_the_installer_ignores_the_staging_directory(tmp_path: Path) -> None:
    src = (REPO / "install.sh").read_text(encoding="utf-8")
    want = re.search(r'local -a want=\(([^)]*)\)', src)
    assert want and '"sysop/runtime/"' in want.group(1), "the runtime ignore entry moved"
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=_env(tmp_path))
    (tmp_path / ".gitignore").write_text("sysop/runtime/\n", encoding="utf-8")
    r = subprocess.run(["git", "-C", str(tmp_path), "check-ignore", "-q",
                        "sysop/runtime/giveback/sysop-issue-X1.md"], env=_env(tmp_path))
    assert r.returncode == 0, "a staged body would show as untracked and dirty the tree"


def test_the_runtime_table_lists_the_staging_directory() -> None:
    """WORKFLOW.md § 8.6 is where a consumer looks up what a `sysop/runtime/` directory is."""
    text = (REPO / "core" / "companion" / "docs" / "WORKFLOW.md").read_text(encoding="utf-8")
    section = text[text.index("### 8.6 Runtime directories"):text.index("### 8.7 ")]
    row = [ln for ln in section.splitlines() if ln.startswith("| `sysop/runtime/giveback/")]
    assert len(row) == 1 and "Edit(/sysop/runtime/giveback/**)" in row[0], row
    assert "It sits inside the project so the seeded" in row[0] and "admits the `Write`" in row[0], row


def test_the_tag_message_reaches_the_tag_verbatim(tmp_path: Path) -> None:
    """Phase 377's round (lens 1): `git tag -F` defaults to `--cleanup=strip`, which drops a
    wrapped summary line that starts with `#`. Runs `/release`'s own `git tag` line."""
    text = (REPO / "core" / "skills" / "release" / "SKILL.md").read_text(encoding="utf-8")
    line = next(ln.strip() for b in _FENCE.finditer(text) for ln in b.group(1).splitlines()
                if ln.strip().startswith("git tag -a"))
    env = _env(tmp_path, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    _git_init(tmp_path, env)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "--allow-empty", "-m", "x"],
                   check=True, env=env)
    msg = tmp_path / "msg.md"
    body = "Summary that wraps\n#42 is the issue it closes\n"
    msg.write_text(body, encoding="utf-8")
    cmd = line.replace("<prefix><new version>", "v1").replace("<tag message file>", str(msg))
    subprocess.run(["/bin/bash", "-c", cmd], cwd=tmp_path, check=True, env=env)
    got = subprocess.run(["git", "-C", str(tmp_path), "cat-file", "tag", "v1"],
                         capture_output=True, text=True, check=True, env=env).stdout
    assert got.endswith(body), got


def test_no_rule_is_denied_or_asked_back_in_the_template() -> None:
    """Round 1, lens 2: a `deny` (or `ask`) entry outranks the `allow` rule and switched it off
    with every other test green."""
    import json
    perms = json.loads(_TEMPLATE.read_text(encoding="utf-8"))["permissions"]
    for key in ("deny", "ask"):
        hit = [r for r in perms.get(key, []) if r.split("(")[0] in ("Edit", "Write")]
        assert hit == [], f"`permissions.{key}` overrides the staging rules: {hit}"


def test_release_writes_the_changelog_before_it_tags() -> None:
    """Round 1, lens 2: Step 8 item 2's 'nothing has been tagged' is true only in this order,
    and a swap that kept the item numbers passed every other guard."""
    text = (REPO / "core" / "skills" / "release" / "SKILL.md").read_text(encoding="utf-8")
    step = text[text.index("## Step 8"):text.index("## Step 9")]
    assert step.index("**Write the changelog entry (uncommitted).**") < step.index("git tag -a"), (
        "/release tags before it writes the changelog, so a denied changelog write no longer "
        "stops before any tag")


def test_the_public_doc_states_the_edit_rules() -> None:
    flat = " ".join((REPO / "docs" / "install-and-update.md").read_text(encoding="utf-8").split())
    for phrase in (
        "`dontAsk` also denies every file edit no rule covers, inside the project too.",
        "The list seeds two: `Edit(/sysop/runtime/giveback/**)`",
        "and `Edit(/sysop/SYSOP_ISSUES.md)`",
        "The rules bind only when Claude Code is started at the project root",
        "it seeds the same two file-edit rules",
    ):
        assert phrase in flat, f"docs/install-and-update.md no longer says: {phrase}"
