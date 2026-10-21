"""The shipped scripts that were skill heredocs until Phase 386 (`Q-409` P3).

A test that ran a heredoc now runs the script the skill invokes. A test that needs the
program TEXT (a static check, or a mutation planted into a copy) reads it here.

`pending_doc_collect.py` carries two programs, one per subcommand, each indented under
its `if`/`elif _SUBCOMMAND == '<name>':` branch. `subcommand_body` returns one of them as
the standalone program it was: every line that does not begin inside a multi-line string
token loses the branch's four spaces. The result is checked against the branch by AST,
so a later edit that breaks the un-indent fails loudly instead of handing a test a
different program.
"""
from __future__ import annotations

import ast
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"


def script(name: str) -> Path:
    path = SCRIPTS / name
    assert path.is_file(), f"{name} is not a shipped script"
    return path


def _branch(tree: ast.Module, sub: str) -> ast.If:
    hits = [n for n in ast.walk(tree) if isinstance(n, ast.If)
            and isinstance(n.test, ast.Compare) and len(n.test.comparators) == 1
            and isinstance(n.test.comparators[0], ast.Constant)
            and n.test.comparators[0].value == sub]
    assert len(hits) == 1, f"{len(hits)} branches for subcommand {sub!r}"
    return hits[0]


def subcommand_body(name: str, sub: str) -> str:
    """The program `<name> <sub>` runs, as the standalone text it was before Phase 386."""
    text = script(name).read_text(encoding="utf-8")
    tree = ast.parse(text)
    node = _branch(tree, sub)
    lines = text.splitlines(keepends=True)
    # From the line after the branch's header to the line before the next branch (or EOF),
    # NOT from the first statement to the last: those bounds drop a comment at either edge
    # of the program, and the AST check below cannot see a comment.
    end = node.orelse[0].lineno - 1 if node.orelse else len(lines)
    chunk = "".join(lines[node.lineno:end])
    if node.orelse and chunk.endswith("\n\n"):
        chunk = chunk[:-1]   # the blank line the generator writes before `elif`
    inside: set[int] = set()
    for tok in tokenize.generate_tokens(io.StringIO(chunk).readline):
        if tok.type == tokenize.STRING and tok.start[0] != tok.end[0]:
            inside.update(range(tok.start[0] + 1, tok.end[0] + 1))
    out = []
    for n, line in enumerate(chunk.splitlines(keepends=True), 1):
        if n not in inside and line.startswith("    "):
            line = line[4:]
        out.append(line)
    body = "".join(out)
    got = [ast.dump(s) for s in ast.parse(body).body]
    assert got == [ast.dump(s) for s in node.body], f"{name} {sub}: the un-indent changed the program"
    return body


def run(name: str, *args: str, cwd: Path, **kw) -> subprocess.CompletedProcess:
    """`python3 sysop/scripts/<name> <args>`, as the skill runs it, on this interpreter."""
    return subprocess.run([sys.executable, str(script(name)), *args], cwd=cwd,
                          capture_output=True, text=True, **kw)


def invocation(skill_text: str, name: str) -> list[str]:
    """Every line in `skill_text` that runs `python3 sysop/scripts/<name>`."""
    return re.findall(r"^[ \t]*python3 sysop/scripts/" + re.escape(name) + r"\b.*$",
                      skill_text, re.M)


def invoked_script_containing(skill_md: Path, needle: str) -> Path:
    """The ONE shipped script `skill_md` invokes whose text contains `needle`.

    The successor of `_heredoc_population.heredoc_containing` for a heredoc that became a
    script: it searches only scripts the skill's own runner text runs, so a needle that
    moves into some unrelated script is not silently matched.
    """
    from skill_runner_text import text_of
    names = sorted(set(re.findall(r"python3 sysop/scripts/([\w-]+\.py)\b", text_of(skill_md))))
    hits = [script(n) for n in names if (SCRIPTS / n).is_file()
            and needle in (SCRIPTS / n).read_text(encoding="utf-8")]
    assert len(hits) == 1, f"{skill_md.parent.name}: {len(hits)} invoked scripts contain {needle!r}"
    return hits[0]


# Every program that was a skill heredoc until Phase 386 or 387, as (script, subcommand or None).
# A guard whose population was "every heredoc" and whose property is about the PROGRAM (a
# bootstrap copy, a shared helper's shape) reads these too, or the move would shrink it.
FORMER_HEREDOCS = (
    ("clone_sync.py", None),
    ("smoke_detect.py", None),
    ("pending_doc_collect.py", "collect"),
    ("pending_doc_collect.py", "rollback"),
    ("close_index.py", None),
    ("claim_record.py", None),
    ("round_receipt.py", None),
    # Phase 387: review-close's remaining always-run Python heredocs.
    ("feature_branch.py", "landed"),
    ("feature_branch.py", "keep-ignored"),
    ("convention_size.py", None),
    ("claim_artifacts.py", None),
    ("workspace_locate.py", None),
    ("smoke_record.py", None),
    ("pr_head_check.py", None),
    ("close_check.py", None),
)


def shipped_programs() -> list[tuple[str, str]]:
    """(label, program text) for every script the installer ships — core's and each pack's.

    A script that dispatches on `_SUBCOMMANDS` yields one program per subcommand, as the
    standalone text `subcommand_body` returns. Derived from the tree, so a heredoc that
    becomes a script later joins every guard reading this without anyone listing it.
    """
    paths = sorted(SCRIPTS.rglob("*.py")) + sorted(REPO_ROOT.glob("packs/*/companion/scripts/**/*.py"))
    out = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        label = str(path.relative_to(REPO_ROOT))
        subs = None
        for node in ast.parse(text).body:
            if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == ["_SUBCOMMANDS"]:
                subs = ast.literal_eval(node.value)
        if subs and path.parent == SCRIPTS:
            out += [(f"{label} {s}", subcommand_body(path.name, s)) for s in subs]
        else:
            out.append((label, text))
    return out
