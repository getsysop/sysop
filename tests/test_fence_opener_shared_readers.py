"""A backtick run with a backtick later on its line opens no fence: the shared readers.

CommonMark forbids a backtick in a backtick fence's info string (a tilde fence's may hold one),
so ```` ```a`b``` is inline ```` is a paragraph holding an inline code span. The shared opener
pattern (`_FENCE_OPEN_RE`, five copies pinned identical by `test_flag_contract.py`) read it as an
opener, and so did `security_partition.py`'s fence toggle. A phantom opener pairs with the next
bare closer, so a real heading or a real envelope after it read as fenced.

This module pins each reader on that line, with a tilde control, and holds the opener pattern to
a CommonMark parser (markdown-it-py) over a table of lines. `test_flag_contract.py`'s
`test_fenced_mask_grammar` carries the same two rows for the four `_fenced_mask` copies.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from markdown_it import MarkdownIt

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import archive_review_tasks as ar  # noqa: E402
import next_task as nt  # noqa: E402
import parse_subagent_envelope as pse  # noqa: E402
import review_index as ri  # noqa: E402
import security_map_filter as smf  # noqa: E402
import security_partition as sp  # noqa: E402
import sitrep_survey as ss  # noqa: E402

PROBE = "```a`b``` is inline"
MASK_READERS = (ri, ss, nt, ar)
PATTERN_READERS = MASK_READERS + (pse,)
_MD = MarkdownIt("commonmark")


def _opens_fence(line: str) -> bool:
    """CommonMark's verdict: does `line`, alone, open a fenced code block?"""
    toks = _MD.parse(line + "\nbody\n")
    return bool(toks) and toks[0].type == "fence"


# Column 0 to three spaces, and blockquoted: the shared pattern already refuses a marker
# indented four or more, and that rule is not what this module is about.
LINES = [
    PROBE,
    "```py`x",
    "```` x`y",
    "```bash",
    "```",
    "````markdown",
    "   ```js",
    "~~~",
    "~~~markdown `quoted`",
    "~~~a`b",
    "> ```a`b``` quoted inline",
    "> ```yaml",
    "> ~~~a`b",
    "``",
    "text ```",
]


@pytest.mark.parametrize("line", LINES)
@pytest.mark.parametrize("mod", PATTERN_READERS, ids=lambda m: m.__name__)
def test_shared_opener_agrees_with_commonmark(mod, line):
    if line.startswith(">"):
        # markdown-it reads the quote's inner line; the pattern reads the prefixed one.
        expected = _opens_fence(line.lstrip(">").lstrip(" "))
    else:
        expected = _opens_fence(line)
    assert bool(mod._FENCE_OPEN_RE.match(line)) is expected, (mod.__name__, line)


def test_oracle_controls():
    """The oracle itself: a backtick in a backtick info string is inline, in a tilde one not."""
    assert not _opens_fence(PROBE)
    assert _opens_fence("~~~a`b")
    assert _opens_fence("```bash")


# A real heading below the probe line, then an ordinary bash block whose bare closer is what
# a phantom opener pairs with.
TRACKER = [PROBE, "## Thing", "x", "```bash", "echo", "```"]


@pytest.mark.parametrize("mod", MASK_READERS, ids=lambda m: m.__name__)
def test_fenced_mask_reads_the_heading_after_the_probe(mod):
    assert mod._fenced_mask(TRACKER) == [False, False, False, True, True, True]


@pytest.mark.parametrize("mod", MASK_READERS, ids=lambda m: m.__name__)
def test_tilde_fence_with_a_backtick_in_its_info_string_still_fences(mod):
    lines = ["~~~a`b", "## Thing", "~~~", "## Real"]
    assert mod._fenced_mask(lines) == [True, True, True, False]


# The probe line alone opens nothing, so nothing is left unterminated and a batch header
# after it is not inside a fence nobody closed.
OPEN_TRACKER = [
    "# Review Tasks", "",
    "### Batch 1 — First `Merged`", "",
    PROBE, "",
    "- [x] **TASK-1**: done", "",
    "### Batch 2 — Second `Pending`", "",
    "- [ ] **TASK-2**: open", "",
]


@pytest.mark.parametrize("mod", (ri, ar), ids=lambda m: m.__name__)
def test_probe_line_leaves_no_unterminated_fence(mod):
    assert mod._unterminated_fence(OPEN_TRACKER) is None
    assert mod.unterminated_batch_span(OPEN_TRACKER) is None


def test_tilde_opener_with_a_backtick_is_still_unterminated():
    lines = [ln if ln != PROBE else "~~~a`b" for ln in OPEN_TRACKER]
    assert ri._unterminated_fence(lines) == (4, "~~~")


def test_check_fences_passes_a_tracker_holding_the_probe_line(tmp_path):
    """End to end: `--check-fences` exited 5 (an open fence holding a batch header)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(repo)],
                   check=True, capture_output=True)
    (repo / "review_tasks.md").write_text("\n".join(OPEN_TRACKER) + "\n", encoding="utf-8")
    dst = repo / "sysop" / "scripts"
    dst.mkdir(parents=True)
    shutil.copy(SCRIPTS / "review_index.py", dst / "review_index.py")
    r = subprocess.run([sys.executable, "sysop/scripts/review_index.py", "--check-fences"],
                       cwd=str(repo), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ── parse_subagent_envelope ──────────────────────────────────────────


def test_envelope_blocks_have_no_phantom():
    assert pse._fenced_blocks("\n".join(TRACKER)) == ["echo"]


def test_envelope_after_the_probe_line_is_found():
    """A bare-fenced envelope: the phantom opener paired with its opener, its body read as
    prose and its closer opened a fence nobody closed, so the envelope was lost."""
    msg = "\n".join([
        "Done. Note that " + PROBE + " in the docs.",
        PROBE,
        "```",
        "TASK: TASK-7",
        "STATUS: COMPLETE",
        "```",
    ])
    block = pse._find_envelope_block(msg)
    assert block is not None
    assert pse._extract_field(block, "TASK") == "TASK-7"


def test_tilde_envelope_with_a_backtick_in_its_info_string_is_found():
    msg = "\n".join(["~~~yaml `envelope`", "TASK: TASK-8", "STATUS: COMPLETE", "~~~"])
    assert pse._find_envelope_block(msg) == "TASK: TASK-8\nSTATUS: COMPLETE"


# ── security_partition ───────────────────────────────────────────────

MAP = "\n".join([
    "# Security map",
    PROBE,
    "## `a/**` — Alpha",
    "**Check:** A01",
    "```bash",
    "echo",
    "```",
    "## `b/**` — Beta",
    "**Check:** A02",
])


def test_partition_reads_both_sections_after_the_probe_line():
    assert [s["name"] for s in sp.parse_sections(MAP)] == ["Alpha", "Beta"]


def test_partition_tilde_fence_with_a_backtick_hides_its_skeleton():
    text = "\n".join(["~~~md `example`", "## `**` — Everything", "~~~", "## `a/**` — Alpha"])
    assert [s["name"] for s in sp.parse_sections(text)] == ["Alpha"]


@pytest.mark.parametrize("inner", ["```python", "``", "~~~", "~~~~"])
def test_partition_fence_closes_only_on_a_matching_closer(inner):
    """The toggle flipped on any marker: a ```python opener inside a block closed it."""
    text = "\n".join(["```", inner, "## `**` — Everything", "```", "## `a/**` — Alpha"])
    assert [s["name"] for s in sp.parse_sections(text)] == ["Alpha"]


def test_partition_longer_fence_is_not_closed_by_a_shorter_run():
    text = "\n".join(["````md", "```", "## `**` — Everything", "````", "## `a/**` — Alpha"])
    assert [s["name"] for s in sp.parse_sections(text)] == ["Alpha"]


def test_partition_unterminated_fence_still_blanks_to_the_end():
    """The documented direction, kept: content inside an unclosed fence is not half-read."""
    text = "\n".join(["## `a/**` — Alpha", "```", "## `b/**` — Beta"])
    assert [s["name"] for s in sp.parse_sections(text)] == ["Alpha"]


def test_partition_list_item_fence_in_the_exclusions_stays_fenced():
    """No indent rule here. A fence inside a list item sits four spaces in, and CommonMark reads
    it as a fence (checked below); with `security_map_filter`'s four-space rule its example
    glob would be harvested and its `# comment` would end the section early."""
    text = ("## Map coverage exclusions\n\n1. step\n\n    ```bash\n"
            "    - `x/**` — example\n    # comment\n    ```\n- `real/**` — r\n")
    assert [t.type for t in _MD.parse(text) if t.type == "fence"] == ["fence"]
    assert sp.parse_exclusions(text) == ["real/**"]


@pytest.mark.parametrize("line", LINES + ["  ~~~", "````", "```  ", "~~~~ x"])
def test_partition_opener_agrees_with_the_filter(line):
    """`security_map_filter.py` reads the same map. On every marker indented three spaces or
    less, the two must agree on what opens a fence and what closes one."""
    if line.startswith(">"):
        return  # neither reads a blockquoted marker as a fence
    assert sp.fence_mark(line) == smf.fence_mark(line), line
    for open_line in ("```", "````", "~~~"):
        mark = smf.fence_mark(open_line)
        assert sp.fence_closes(line, mark) == smf.fence_closes(line, mark), (open_line, line)
