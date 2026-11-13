"""`Q-477`: a backtick run whose info string holds a backtick is not a fence opener.

CommonMark's rule is that a backtick fence's info string may not contain a backtick (a tilde
fence's may). A line like ```` ```a`b``` is inline ```` is a paragraph with an inline code
span. Every `fence_mark` copy the `## Test decision` chain runs read it as an opener, and since
the closer learned to refuse an info string, nothing re-closed the phantom fence early: a legal
body's real record read `MISSING`.

`test_test_decision_readback.py` and `test_autobuild_record_readback.py` run `/claim-task`
Step 8's block and `/auto-build`'s byte-identical port on the measured body. This module covers
the copies those two do not run: Step 8b's `questions.md` parser and `claim_record.py`'s
section strip, plus one table that holds every copy to a CommonMark parser.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from markdown_it import MarkdownIt

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAIM = REPO_ROOT / "core" / "skills" / "claim-task" / "SKILL.md"
BUILD = REPO_ROOT / "core" / "skills" / "auto-build" / "SKILL.md"
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
CLAIM_RECORD = SCRIPTS / "claim_record.py"

# The measured body: legal, balanced, with a real record outside every fence. The `bash`
# block's info-string line cannot close a phantom fence and its bare closer can, which is
# what turns a phantom opener into a balanced walk and a false `MISSING`.
BODY = ("# T\n\n## Requirements\n```a`b``` is inline code, not a fence.\n\n"
        "## Test decision\ntest tests/x.py proves y\n\n"
        "## Notes\n```bash\necho hi\n```\n")


def _defs(text: str) -> list[str]:
    """Each top-level `def fence_mark(...)` in `text`, up to the next top-level statement."""
    out = []
    for m in re.finditer(r"^def fence_mark\(line[^)]*\):\n", text, re.M):
        end = re.search(r"^\S", text[m.end():], re.M)
        out.append(text[m.start():m.end() + (end.start() if end else len(text) - m.end())])
    return out


def _copies() -> dict[str, object]:
    found = {}
    for path in (CLAIM, BUILD, CLAIM_RECORD, SCRIPTS / "security_map_filter.py"):
        for n, src in enumerate(_defs(path.read_text(encoding="utf-8")), 1):
            ns: dict = {}
            exec(src, ns)  # noqa: S102 -- the shipped function, nothing else
            found["{}#{}".format(path.relative_to(REPO_ROOT), n)] = ns["fence_mark"]
    return found


def test_every_copy_is_found():
    """Control: two in `/claim-task` (Steps 8 and 8b), one in `/auto-build`, one per script.
    A short count means the extractor went blind and the table below compared nothing."""
    assert len(_copies()) == 5, sorted(_copies())


_MD = MarkdownIt("commonmark")

# Column 0 to three spaces only: `security_map_filter.py` also refuses a marker indented four
# or more, which the `## Test decision` readers deliberately do not (a fence inside a list item
# is indented that far, and their readers match headings after `strip()`).
LINES = [
    "```a`b``` is inline code",
    "```py`x",
    "```` x`y",
    "```bash",
    "```",
    "````markdown",
    "~~~",
    "~~~markdown `quoted`",
    "~~~a`b",
    "   ```js",
    "``",
    "text",
]


@pytest.mark.parametrize("line", LINES)
def test_every_copy_agrees_with_commonmark(line):
    is_fence = _MD.parse(line + "\n")[0].type == "fence"
    wrong = {name: fn(line) for name, fn in _copies().items() if bool(fn(line)) != is_fence}
    assert not wrong, "CommonMark says fence={} for {!r}; these copies disagree: {}".format(
        is_fence, line, wrong)


# --- Step 8b: the `questions.md` parser ---------------------------------------------------


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=str(cwd), capture_output=True, text=True, check=True)


@pytest.fixture
def main(tmp_path):
    m = tmp_path / "main"
    m.mkdir()
    _git(m, "-c", "init.defaultBranch=main", "init", "-q", ".")
    _git(m, "config", "user.email", "t@example.invalid")
    _git(m, "config", "user.name", "t")
    (m / "README.md").write_text("x\n", encoding="utf-8")
    _git(m, "add", "-A")
    _git(m, "commit", "-qm", "init")
    return m


def _block_8b() -> str:
    """Step 8b's record block, located by the line only it prints."""
    lines = CLAIM.read_text(encoding="utf-8").split("\n")
    blocks, i = [], 0
    while i < len(lines):
        if lines[i].lstrip().startswith("python3 - <<'PY'"):
            j = next(k for k in range(i + 1, len(lines)) if lines[k].strip() == "PY")
            blocks.append("\n".join(lines[i + 1:j]))
            i = j
        i += 1
    hits = [b for b in blocks if "ANSWERS_TO_FIX=" in b]
    assert len(hits) == 1, "COULD NOT LOCATE Step 8b's block ({} hits)".format(len(hits))
    return hits[0]


def test_8b_does_not_read_an_inline_code_line_as_a_fence(main):
    """Read as an opener, the line before the first entry fences off the rest of the file,
    so the human is asked about one entry of two."""
    art = main / "sysop" / "runtime" / "claim" / "TECH-0007" / "run-1"
    art.mkdir(parents=True)
    (art / "questions.md").write_text(
        "```a`b``` is how the executor quoted the fence it found.\n\n"
        "## the retry loop swallows a timeout\n- filed as: TECH-0101\n"
        "- question: surface it?\n- recommended: surface it\n\n"
        "## the migration renames a column\n- filed as: TECH-0102\n"
        "- question: keep the old name?\n- recommended: keep it\n",
        encoding="utf-8")
    r = subprocess.run(["python3", "-", "TECH-0007", "run-1"], input=_block_8b() + "\n",
                       cwd=str(main), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "ASK=yes (2 entries)" in r.stdout, r.stdout


# --- claim_record.py: the option-C writer's section strip ---------------------------------


def _write_record(main, body):
    f = main / "tasks" / "open" / "T.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")
    run = main / "sysop" / "runtime" / "claim" / "TECH-0007" / "run-1"
    run.mkdir(parents=True, exist_ok=True)
    (run / "plan.md").write_text("### Steps\n1. do the thing\n", encoding="utf-8")
    r = subprocess.run(["python3", str(CLAIM_RECORD), "TECH-0007", "run-1", "open/T.md",
                        "test tests/new.py proves z"],
                       cwd=str(main), capture_output=True, text=True)
    return r, f.read_text(encoding="utf-8")


def test_claim_record_replaces_the_record_a_phantom_fence_hid(main):
    """Read as an opener, the phantom fence hides the existing section from the strip, so the
    writer appends a second `## Test decision` and the stale one, first in the file, stays.
    That is the double-section state the writer's in-place replace exists to prevent."""
    r, out = _write_record(main, BODY)
    assert r.returncode == 0, r.stderr
    assert out.count("\n## Test decision\n") == 1, out
    assert "test tests/x.py proves y" not in out, out
    assert "test tests/new.py proves z" in out, out
    assert "```a`b``` is inline code, not a fence." in out, out


def test_claim_record_keeps_a_list_item_fence_indented_four_spaces(main):
    """Why the indent rule `security_map_filter.py` carries is not ported here. A fence in a
    list item is indented four spaces; it IS a fence there, and the strip matches a heading
    after `strip()`. Read as indented code, the quoted heading below would be stripped as
    the body's own section, taking the list item's quoted text with it."""
    body = ("# T\n\n## Requirements\n1. the section should read:\n\n"
            "    ```markdown\n    ## Test decision\n    quoted, not the record\n    ```\n")
    r, out = _write_record(main, body)
    assert r.returncode == 0, r.stderr
    assert "    ## Test decision\n    quoted, not the record\n" in out, out
