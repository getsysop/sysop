"""No tracked markdown renders prose as an indented code block (`Q-611`, Phase 341).

A line indented four or more spaces after a blank line is code in CommonMark unless it sits
inside a list item deep enough to hold it. A lettered sub-step (`   a. **Collect …**`) is not
a list marker, so it opens no item, and every six-space line below it was code:
`review-close/SKILL.md` showed 948 lines of Step 3b, prose and tables included, as three code
blocks on GitHub. Agents read the raw text and were unaffected, and no guard noticed; Phase 331's
round did, and filed it.

The guards that read the raw text could not see it (`test_substep_line_breaks.py` wants a
leading digit, and its fence guard paired these fences correctly), because only a CommonMark
reading decides where a list ends. So this module takes one, with `markdown-it-py` in its
CommonMark preset plus GFM tables, and fails on any `code_block` token, at any nesting depth: an
indented code block. Tables matter because GitHub renders GFM: a table ends at a line indented four
or more, which is then code, while CommonMark (no tables) reads the same lines as one paragraph
(Phase 341's round 2). A fenced block is a `fence` token and is not affected. Write code as a fence.

The population is every tracked markdown file, not only the shipped skills: `README.md` and
`docs/` are what a public reader sees first, and the round showed a regression there would pass
a `core/`-and-`packs/` population. One file is excluded, with its reason (`_EXCLUDED`).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from markdown_it import MarkdownIt

REPO_ROOT = Path(__file__).resolve().parent.parent

# Indented code on purpose: the phase log quotes command output as indented blocks, and they
# render as intended. Seven of them at Phase 341.
_EXCLUDED = {"PHASE_LOG.md"}

# 103 tracked markdown files at Phase 341, one excluded. A floor, not an equality: a new file
# must not need an edit here, but a listing that silently came back short must not pass.
# The public mirror runs this module too, on a tree that strips `tools/`, `CLAUDE.md` and the
# queue files: 72 files at Phase 346, so a source-tree floor of 90 failed the suite there and
# would have failed the public PR's required check. Each tree gets its own floor, chosen from
# the tree's root, and `test_the_mirror_floor_holds_on_the_shipped_set` runs that choice against
# a stand-in for the mirror from the source repo, every phase.
_SOURCE_FLOOR = 90
_MIRROR_FLOOR = 60


def _in_source_repo(root: Path) -> bool:
    """`tools/` is mirror-excluded, so only the source repo has it."""
    return (root / "tools").is_dir()


def _floor(root: Path) -> int:
    return _SOURCE_FLOOR if _in_source_repo(root) else _MIRROR_FLOOR


def _parser() -> MarkdownIt:
    """What GitHub renders, as near as this module needs: CommonMark plus GFM tables."""
    return MarkdownIt("commonmark").enable("table")


def _tracked_markdown() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT,
                         capture_output=True, check=True).stdout
    return sorted(p for p in out.decode("utf-8").split("\0")
                  if p.lower().endswith((".md", ".markdown")) and p not in _EXCLUDED)


def _tracked_texts() -> dict[str, str]:
    """The population as read, once, for both the population test and the real test, so a
    read that came back hollow is visible to the first."""
    return {rel: (REPO_ROOT / rel).read_text(encoding="utf-8") for rel in _tracked_markdown()}


def _indented_code(text: str) -> list[tuple[int, int]]:
    """1-based `(first, last)` line ranges of every indented code block in `text`."""
    return [(t.map[0] + 1, t.map[1]) for t in _parser().parse(text)
            if t.type == "code_block"]


def _offending(texts: dict[str, str]) -> dict[str, list[tuple[int, int]]]:
    """Each file whose text holds an indented code block, with its ranges. The real test and
    the control both call this, so the control reaches the same loop and filter."""
    found = {}
    for rel, text in texts.items():
        ranges = _indented_code(text)
        if ranges:
            found[rel] = ranges
    return found


def test_the_population_is_the_tracked_markdown():
    texts = _tracked_texts()
    assert len(texts) >= _floor(REPO_ROOT), sorted(texts)
    for must in ("README.md", "core/skills/review-close/SKILL.md", "docs/getting-started.md"):
        assert must in texts, must
    assert " - a. **Collect pending-docs**" in texts["core/skills/review-close/SKILL.md"]
    for rel, text in texts.items():   # an independent read: a truncated one is not the file
        assert text == (REPO_ROOT / rel).read_bytes().decode("utf-8"), rel


def test_the_tree_is_read_the_same_way_by_two_markers():
    """`tools/` and the leak-gate module are both mirror-excluded, so they are present together
    or absent together. A detector that disagrees with the second marker would hand the source
    repo the mirror's lower floor, and every test here would stay green."""
    in_source = (REPO_ROOT / "tests" / "test_mirror_leak_gate.py").is_file()
    assert _in_source_repo(REPO_ROOT) == in_source
    assert _floor(REPO_ROOT) == (_SOURCE_FLOOR if in_source else _MIRROR_FLOOR)


def test_the_mirror_floor_holds_on_the_shipped_set(tmp_path):
    """The mirror's floor, CHOSEN and judged from the source repo, against the files it ships.

    A cut is the only other place the mirror meets this module, which is how Phase 346's dry
    run found the single floor red there. `_shipped_files()` is the builder's strip list read
    through the leak gate. Laying those paths out as empty files gives a stand-in root on which
    `_floor()` makes the choice it will make in the mirror, so a detector keyed to a directory
    the mirror keeps, or a floor that ignores the tree, fails here and not at the cut (the
    round's F1: the pre-phase single floor, restored, was green in the source repo)."""
    try:
        import test_mirror_leak_gate as gate  # noqa: PLC0415 - the source of truth for the strip list
    except ImportError:
        pytest.skip("tests/test_mirror_leak_gate.py is mirror-excluded; this runs in the source repo")

    shipped_all = gate._shipped_files()
    for rel in shipped_all:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).touch()
    assert _in_source_repo(REPO_ROOT), "the leak gate imported, so this is the source repo"
    assert not _in_source_repo(tmp_path), "the shipped layout must read as the mirror"
    shipped = [p for p in shipped_all
               if p.lower().endswith((".md", ".markdown")) and p not in _EXCLUDED]
    assert "README.md" in shipped and not any(p.startswith("tools/") for p in shipped), shipped
    assert len(shipped) >= _floor(tmp_path), (
        f"the mirror would carry {len(shipped)} markdown files, under its floor of "
        f"{_floor(tmp_path)}: lower the floor or find what the strip list removed")
    assert _MIRROR_FLOOR < _SOURCE_FLOOR


def test_no_tracked_markdown_renders_prose_as_code():
    found = _offending(_tracked_texts())
    assert not found, (
        "these lines render as an indented code block on GitHub (CommonMark), so their prose "
        "and tables show as a code listing. Usually a lettered sub-step (`   a. **…**`) that "
        "opens no list sits above six-space-indented content: write it as a bullet of the same "
        "length (` - a. **…**`). For code, use a fence.\n"
        + "\n".join(f"  {f}: lines {', '.join(f'{a}-{b}' for a, b in r)}"
                    for f, r in found.items()))


# The defect's shape as it stood in `review-close/SKILL.md` before Phase 341, and the repair.
_BROKEN = (
    "**1. Collect the docs** — from the workspace.\n"
    "   a. **Collect pending-docs**: bring each doc across.\n"
    "\n"
    "      A paragraph of the step's own prose.\n"
)
_REPAIRED = _BROKEN.replace("   a. **Collect", " - a. **Collect")
_LONG_PREFIX = "A paragraph.\n\n" * 9000          # 126,000 characters before the defect


def test_the_reading_sees_the_defect_and_passes_the_repair():
    assert len(_REPAIRED) == len(_BROKEN), "the repair keeps every line's length"
    texts = {
        "core/skills/review-close/SKILL.md": _REPAIRED,
        "core/skills/alpha/SKILL.md": _REPAIRED,
        "core/skills/zeta/SKILL.md": _BROKEN,
        "packs/python/companion/convention_map.md": "- item\n\n      code line\n",
        "docs/guide.md": ">     code line\n",
        "README.md": _LONG_PREFIX + _BROKEN,
        "docs/table.md": " - a. x\n\n      | h | k |\n      |---|---|\n      | r | s |\n          | r2 | s2 |\n",
        "docs/deep.md": " - a\n\n   >     code\n\n - b\n\n   - c\n\n     >     code\n",
    }
    assert _offending(texts) == {
        "docs/table.md": [(6, 6)],                              # a GFM table ends in code
        "docs/deep.md": [(3, 3), (9, 9)],                       # levels 3 and 5
        "core/skills/zeta/SKILL.md": [(4, 4)],
        "packs/python/companion/convention_map.md": [(3, 3)],   # inside a list item
        "docs/guide.md": [(1, 1)],                              # inside a blockquote
        "README.md": [(18004, 18004)],                          # past 100,000 characters
    }


# Step 3b's structure, which the code-block test cannot see: reverting `b.` alone renders no
# code block but folds sub-step (b) into the paragraph above it as a lazy continuation; the stray
# line's old layout (one space, no blank above) folds it into the gate blockquote; and a dedent
# of (b)'s tail puts its instructions at step level. Round 1 (both lenses) and round 2 of Phase
# 341 showed each passing every other guard but byte-level ones.
_SKILL = "core/skills/review-close/SKILL.md"
_A = "a. **Collect pending-docs**"
_B = "b. **ONLY WHEN `SHAPE=worktree`**"
_STRAY = "Step 1a can now classify a worktree"
_TAIL = "Then downgrade this branch to SKIP for this run"
_IN_ITEM = ["bullet_list_open", "list_item_open", "paragraph_open"]


def _step_3b_shape(text: str) -> tuple[list[str], dict[str, list[tuple]]]:
    """The first words of each item of the list whose first item is sub-step (a), and, for each
    anchor, every paragraph that holds it: `(item index or None, enclosing blocks, whether the
    anchor starts the paragraph)`. Every occurrence is reported, so a second copy cannot mask
    the first, and a paragraph outside the list has index None."""
    toks = _parser().parse(text)
    heads, spans, owned = [], [], None
    for i, t in enumerate(toks):
        if t.type == "bullet_list_open":
            first = next(k for k in toks[i + 1:] if k.type == "inline")
            if first.content.startswith(_A):
                owned = i
                break
    if owned is not None:
        level = toks[owned].level
        for i in range(owned + 1, len(toks)):
            t = toks[i]
            if t.type == "bullet_list_close" and t.level == level:
                break
            if t.type == "list_item_open" and t.level == level + 1:
                spans.append((t.map[0], t.map[1]))
                heads.append(next(k for k in toks[i + 1:] if k.type == "inline").content)
    where, stack = {_STRAY: [], _TAIL: []}, []
    for t in toks:
        if t.nesting == 1:
            stack.append(t.type)
        elif t.nesting == -1:
            stack.pop()
        if t.type == "inline":
            for anchor in where:
                if anchor in t.content:
                    item = next((n for n, (a, b) in enumerate(spans) if a <= t.map[0] < b), None)
                    where[anchor].append((item, list(stack), t.content.startswith(anchor)))
    return heads, where


def test_step_3b_renders_as_its_two_sub_steps():
    heads, where = _step_3b_shape((REPO_ROOT / _SKILL).read_text(encoding="utf-8"))
    hint = " (if Step 3b was restructured on purpose, update this test's anchors with it)"
    assert [h[:len(s)] for h, s in zip(heads, (_A, _B))] == [_A, _B] and len(heads) == 2, heads
    assert where[_STRAY] == [(1, _IN_ITEM, True)], f"{where[_STRAY]}{hint}"
    assert where[_TAIL] == [(1, _IN_ITEM, True)], f"{where[_TAIL]}{hint}"


def test_the_structure_check_sees_each_revert():
    text = (REPO_ROOT / _SKILL).read_text(encoding="utf-8")
    b_reverted = text.replace(" - " + _B, "   " + _B, 1)
    assert b_reverted != text
    assert len(_step_3b_shape(b_reverted)[0]) == 1, "sub-step (b) folded into item (a)"
    line = next(l for l in text.split("\n") if l.lstrip().startswith(_STRAY))
    stray_reverted = text.replace("\n\n" + line + "\n", "\n " + line.lstrip() + "\n\n", 1)
    assert stray_reverted != text
    assert "blockquote_open" in _step_3b_shape(stray_reverted)[1][_STRAY][0][1], "joins the gate"
    tail = next(l for l in text.split("\n") if l.lstrip().startswith(_TAIL))
    dedented = text.replace(tail, tail.lstrip(), 1)
    assert _step_3b_shape(dedented)[1][_TAIL][0][0] is None, "(b)'s tail left the list"
    # A second copy is reported, not hidden behind the first.
    copied = text.replace(tail, "      " + _STRAY + ", as above.\n\n" + tail, 1)
    assert len(_step_3b_shape(copied)[1][_STRAY]) == 2
    # And a stray line that continues an ordinary paragraph is not its own, gate or no gate.
    folded = f" - {_A}: x\n\n - {_B} y\n      {_STRAY} z\n"
    assert _step_3b_shape(folded)[1][_STRAY] == [(1, _IN_ITEM, False)]
