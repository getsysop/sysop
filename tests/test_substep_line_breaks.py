"""A lettered or suffixed sub-step (`2b.`, `5a.`, `3‑tier.`) must not render into the step above.

`2b.` is not a CommonMark list marker, so a sub-step line directly under a non-blank line is a
lazy continuation: rendered, it joins the paragraph above it and the step disappears into the
previous one. Agents read the raw text, where it is fine; a human reading `WORKFLOW.md` on
GitHub is not. The accepted shapes are a blank line before it, or a hard break (`\\`) ending
the line above, which moves no line number.

The second guard here is the same kind of defect one construct over: a fence opened inside a
list item ends, in CommonMark, at the first line indented less than the item's content, even a
line of the fence's own body. The old closer then opens a new fence that swallows the rest.
Two stated over-strictnesses, neither present in a shipped file: a top-level fence indented
one to three spaces with a column-0 body, and a body line between an item's content column and
its opener's indent, both render fine and are refused; indent a fence body to its opener.
`_fence_state` and the pin normalizer read fences by marker alone, so they cannot see it; this
guard is what keeps a dedented body line from turning shipped rules into code.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# A sub-step here is a step heading: its label is followed by bold text, as every shipped
# one is. Prose re-wrapped so that "5b. On the common path" starts a line renders as prose
# and is not one; a sub-step written without bold is not seen.
_SUBSTEP = re.compile(r"^ {0,3}\d+[a-z]*[‑-]?[a-z]*\. \*\*")
_PLAIN = re.compile(r"^ {0,3}\d+\. ")
_FENCE = re.compile(r"^[ \t]*(```|~~~)")


def _indent(line: str) -> int:
    """Leading columns, with tabs at CommonMark's stop of 4."""
    wide = line.expandtabs(4)
    return len(wide) - len(wide.lstrip(" "))


def _run(line: str) -> str:
    stripped = line.strip()
    return stripped[: len(stripped) - len(stripped.lstrip(stripped[0]))]


def _fences(lines: list[str]):
    """(opener index, opener, line index) for every line inside a fence, closer included.

    A closer is the opener's own marker, at least as long, with nothing after it, so a `~~~`
    line inside a backtick fence, or a shorter run inside a longer one, does not close it.
    """
    opener = None
    for i, line in enumerate(lines):
        m = _FENCE.match(line)
        if opener is None:
            if m:
                opener = (i, _indent(line), m.group(1)[0], len(_run(line)))
            continue
        yield opener, i
        if (m and m.group(1)[0] == opener[2] and len(_run(line)) >= opener[3]
                and not line.strip().lstrip(opener[2]).strip()):
            opener = None


def lazy_substeps(text: str) -> list[int]:
    """1-based line numbers of sub-step lines that would render into the line above."""
    lines, out = text.split("\n"), []
    fenced = {i for (o, *_), i in _fences(lines)} | {o for (o, *_), _ in _fences(lines)}
    for i, line in enumerate(lines):
        if i in fenced or not _SUBSTEP.match(line) or _PLAIN.match(line) or i == 0:
            continue
        above = lines[i - 1]
        if above.strip() and not above.endswith("\\") and not above.endswith("  "):
            out.append(i + 1)
    return out


def _shipped_markdown() -> list[Path]:
    names = subprocess.run(
        ["git", "ls-files", "core/**/*.md", "packs/**/*.md", "docs/*.md", "README.md", "CONTRIBUTING.md"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    return [REPO_ROOT / n for n in names]


def test_no_shipped_substep_renders_into_the_step_above():
    files = _shipped_markdown()
    assert len(files) > 50, "the shipped markdown population is nearly empty"
    # The four files that carried the class when this guard was written must stay in it, and
    # so must every root the population names: a narrowed glob is a silently smaller guard.
    for must in ("core/skills/claim-task/SKILL.md", "core/skills/auto-build/SKILL.md",
                 "core/companion/docs/WORKFLOW.md", "core/companion/docs/WORKFLOW_GUIDE.md",
                 "README.md", "CONTRIBUTING.md"):
        assert REPO_ROOT / must in files, f"{must} fell out of the scanned population"
    rel = [str(p.relative_to(REPO_ROOT)) for p in files]
    for root in ("core/skills/", "core/companion/", "packs/", "docs/"):
        assert any(r.startswith(root) for r in rel), f"no {root} file is scanned"
    bad = [f"{p.relative_to(REPO_ROOT)}:{n}"
           for p in files for n in lazy_substeps(p.read_text(encoding="utf-8"))]
    assert not bad, (
        "a sub-step sits directly under a non-blank line and renders into it; end the line "
        "above with `\\` (moves no line number) or add a blank line: " + ", ".join(bad))


def test_the_detector_sees_each_shape():
    assert lazy_substeps("2. **Implement.**\n2b. **Fix it here.**") == [2]
    assert lazy_substeps("5. merge\n5a. **fix**\n5b. **verify**") == [2, 3]
    assert lazy_substeps("3. x\n3‑tier. **y**") == [2]
    assert lazy_substeps("   - bullet\n4b. **step**") == [2]
    assert lazy_substeps("1. step\n   1a. **an indented sub-step**") == [2]
    # a tilde line or a shorter run inside a fence does not end it
    assert lazy_substeps("````\n```\nx\n2b. **y**\n````") == []
    assert lazy_substeps("```\n~~~\nx\n2b. **y**\n```") == []
    # Accepted shapes, and lines that are not sub-steps.
    assert lazy_substeps("2. x\\\n2b. **y**") == []
    assert lazy_substeps("2. x  \n2b. **y**") == []
    assert lazy_substeps("2. x\n\n2b. **y**") == []
    assert lazy_substeps("2. x\n3. **y**") == []
    assert lazy_substeps("```\n2. x\n2b. **y**\n```") == []
    assert lazy_substeps("see step\n2026. **was** a year") == []
    assert lazy_substeps("the fast path is step\n5b. On the common path it runs") == []  # re-wrapped prose


def dedented_fence_lines(text: str) -> list[int]:
    """1-based line numbers inside an INDENTED fence (body or closer) indented less than its opener."""
    lines = text.split("\n")
    return [i + 1 for (_, indent, *_), i in _fences(lines)
            if lines[i].strip() and indent > 0 and _indent(lines[i]) < indent]


def test_the_population_is_every_shipped_markdown_file():
    """Derived a second way: every tracked `.md` under a shipped root, so narrowing a glob
    (one pack, one docs page, two core subdirectories) is seen, not only dropping one."""
    tracked = subprocess.run(["git", "ls-files", "*.md"], cwd=REPO_ROOT, capture_output=True,
                             text=True, check=True).stdout.split()
    want = {n for n in tracked
            if n.startswith(("core/", "packs/")) or n in ("README.md", "CONTRIBUTING.md")
            or n.startswith("docs/")}   # git's `docs/*.md` pathspec matches at any depth
    got = {str(p.relative_to(REPO_ROOT)) for p in _shipped_markdown()}
    assert got == want, sorted(got ^ want)


def test_no_shipped_fence_line_is_dedented_below_its_opener():
    files = _shipped_markdown()
    assert REPO_ROOT / "core/skills/auto-build/SKILL.md" in files
    bad = [f"{p.relative_to(REPO_ROOT)}:{n}"
           for p in files for n in dedented_fence_lines(p.read_text(encoding="utf-8"))]
    assert not bad, (
        "a line inside an indented fence sits left of its opener; inside a list item that ends "
        "the fence, and everything after it renders as code. Indent it to the opener: "
        + ", ".join(bad))


def test_the_fence_detector_sees_each_shape():
    assert dedented_fence_lines("1. step\n   ```bash\n   a \\\nb\n   ```") == [4]
    assert dedented_fence_lines("1. step\n   ```\n   a\n```") == [4]        # closer moved left
    assert dedented_fence_lines("1. step\n   ```\n   a\n   ```\nplain") == []
    assert dedented_fence_lines("```\na\n```") == []                        # top-level fence
    assert dedented_fence_lines("   ~~~\n   ```\n   ~~~") == []               # other marker inside
    assert dedented_fence_lines("   ```\n\n   a\n   ```") == []              # blank body line
    # A shorter run does not close a longer fence, so the next fence is still paired right.
    assert dedented_fence_lines("````\n```\n````\n1. x\n   ```\nb\n   ```") == [6]
    # A one-column dedent breaks the item too, not only a return to column 0.
    assert dedented_fence_lines("1. step\n   ```\n   a\n  b\n   ```") == [4]
    # A marker line with an info string is content, not a closer...
    assert dedented_fence_lines("1. s\n   ```\n   ```text\n  a\n   ```") == [4]
    # ...and a longer run is a closer, so what follows it is outside the fence.
    assert dedented_fence_lines("1. s\n   ```\n   a\n   ````\nb") == []
    # Tabs count to CommonMark's stop of 4: a tab-led body line under a 3-space opener stays
    # inside, and a tab-indented opener is indented.
    assert dedented_fence_lines("1. s\n   ```\n\ta\n   ```") == []
    assert dedented_fence_lines("1. step\n\n\t```\n\ta\nb\n\t```") == [5]

