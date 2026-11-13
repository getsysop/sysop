"""`security_partition.py`'s fence closer: indented at most three columns past its opener.

The partition reads a marker at any indent (a fence inside a list item sits four spaces in), and
until Phase 484's fix pass it read a closer at any indent too. A map that documents a list item's
fenced command inside a column-0 example block then lost everything after the example: the list
item's four-space ```` ``` ```` closed the outer block, the outer closer opened a new one, and
`parse_sections` dropped the next section (`parse_exclusions` returned nothing).
`security_map_filter.py` reads the same map and saw both sections. `markdown-it-py` is the oracle.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from markdown_it import MarkdownIt

SCRIPTS = Path(__file__).resolve().parents[1] / "core" / "companion" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import security_map_filter as smf  # noqa: E402
import security_partition as sp  # noqa: E402

_MD = MarkdownIt("commonmark")

EXAMPLE = "```markdown\n1. Add a section:\n    ```bash\n    ls\n    ```\n```\n"


def test_sections_after_an_example_holding_a_list_item_fence_are_read():
    text = f"## `api/**` — API\n- check a\n\n{EXAMPLE}\n## `auth/**` — Auth\n- check b\n"
    toks = _MD.parse(text)
    assert [toks[i + 1].content for i, t in enumerate(toks) if t.type == "heading_open"] == [
        "`api/**` — API", "`auth/**` — Auth"], "oracle: one example block, two sections"
    assert [t.type for t in toks if t.type == "fence"] == ["fence"]
    assert [s["name"] for s in sp.parse_sections(text)] == ["API", "Auth"]


def test_exclusions_after_such_an_example_are_read():
    text = f"# P\n\n{EXAMPLE}\n## Map coverage exclusions\n\n- `vendor/**`\n"
    assert sp.parse_exclusions(text) == ["vendor/**"]


@pytest.mark.parametrize("k", range(0, 9))
def test_a_column_0_fence_closes_as_commonmark_and_the_filter_say(k):
    """Past three spaces too: the filter refuses a marker indented four or more, the partition
    counts it as a marker but not as this fence's closer, and CommonMark agrees with both."""
    closer = " " * k + "```"
    mark = smf.fence_mark("```")
    cm = "B" in [t.content for t in _MD.parse(f"```\n## A\n{closer}\n## B\n")
                 if t.type == "inline"]
    assert sp.fence_closes(closer, mark) is smf.fence_closes(closer, mark) is cm, k


@pytest.mark.parametrize("k,closes", [(0, True), (2, True), (7, True), (8, False)])
def test_a_list_item_fence_closes_within_three_columns_of_its_opener(k, closes):
    assert sp.fence_closes(" " * k + "```", ("`", 3), 4) is closes


def test_a_tab_counts_to_the_next_multiple_of_four():
    assert sp.indent_of("\t```") == 4 and sp.indent_of("  \t```") == 4
    assert sp.fence_closes("\t```", ("`", 3), 0) is False
    assert sp.fence_closes("\t```", ("`", 3), 4) is True


def test_a_list_item_fence_is_closed_by_its_own_indented_closer():
    """The opener's indent is what the closer is measured from: a list item's fence opened and
    closed four spaces in ends there, and the section after it is read."""
    text = ("## `api/**` — API\n- check a\n\n1. step\n\n    ```bash\n    ls\n    ```\n\n"
            "## `auth/**` — Auth\n- check b\n")
    toks = _MD.parse(text)
    assert [toks[i + 1].content for i, t in enumerate(toks) if t.type == "heading_open"] == [
        "`api/**` — API", "`auth/**` — Auth"]
    assert [s["name"] for s in sp.parse_sections(text)] == ["API", "Auth"]
