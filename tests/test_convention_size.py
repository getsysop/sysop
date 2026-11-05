"""`convention_size.py` — `/review-close` Step 2b's conventions measurement (`Q-361`, Phase 465).

The measurement picks the paste arm or the write-once arm by the size of the CLAUDE.md sections
the reviewers route against. It was fence-blind and first-match-wins, and the filing measured
six ways a consumer's file gave it a wrong number: (a) a heading that exists only in a fenced
example counted as the section; (b) a duplicated section measured at its first occurrence only;
(d) a fenced `## ` inside a real section cut it short (14,400 characters read as 470, a silent
undercount onto the paste arm); (e) a heading with trailing whitespace scored 0; (f) a following
`# ` heading did not close the section, so it swallowed the file's tail. (c), an `###` heading,
stays out of spec and scores 0; the step's zero check names it.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "core/companion/scripts/convention_size.py"
STEP = REPO / "core/skills/review-close/steps/2b-no-conventions.md"


def measure(tmp_path: Path, text: str, *names: str) -> tuple[dict, int, str]:
    (tmp_path / "CLAUDE.md").write_text(text, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), *(names or ("Prevention Conventions",))],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rows = {}
    total = None
    for line in r.stdout.splitlines():
        n, rest = line.split(None, 1)
        if rest == "TOTAL":
            total = int(n)
        else:
            rows[rest.replace("   (absent)", "")] = int(n)
    assert total == sum(rows.values()), r.stdout
    return rows, total, r.stderr


def old_measure(text: str, name: str) -> int:
    """The program as shipped before this phase, for the healthy-input equivalence pins."""
    m = re.search(rf"^## {re.escape(name)}$.*?(?=^## |\Z)", text, re.M | re.S)
    return len(m.group(0)) if m else 0


SECTION = "## Prevention Conventions\n\n- rule one\n- rule two\n\n"


def test_a_heading_only_inside_a_fence_is_absent(tmp_path):
    """(a): an example quoting the heading is not the section."""
    text = "# P\n\nAn example:\n\n```markdown\n## Prevention Conventions\n\n- quoted\n```\n"
    rows, total, _ = measure(tmp_path, text)
    assert total == 0
    assert old_measure(text, "Prevention Conventions") > 0  # the defect, on the old program


def test_a_fenced_heading_inside_a_section_does_not_end_it(tmp_path):
    """(d): the filing's 97% undercount shape."""
    body = "- rule\n" * 2000
    text = (SECTION + "```bash\n## Commands\nmake test\n```\n\n" + body
            + "## Next section\n\nother\n")
    rows, total, _ = measure(tmp_path, text)
    whole = text.index("## Next section")
    assert total == whole, (total, whole)
    assert old_measure(text, "Prevention Conventions") < whole // 10  # the old cut


def test_every_occurrence_is_measured_and_named(tmp_path):
    """(b): a second same-named section is no longer silently ignored."""
    text = SECTION + "## Other\n\nx\n\n## Prevention Conventions\n\n- a longer second body\n"
    rows, total, err = measure(tmp_path, text)
    first = len(SECTION)
    second = len(text) - text.rindex("## Prevention Conventions")
    assert total == first + second
    assert "appears 2 times" in err


def test_trailing_whitespace_on_the_heading_is_still_the_section(tmp_path):
    """(e): CommonMark strips it; one stray space no longer scores the section 0."""
    text = "## Prevention Conventions \t\n\n- rule\n\n## Testing Patterns\n\n- t\n"
    rows, total, _ = measure(tmp_path, text, "Prevention Conventions", "Testing Patterns")
    assert rows["## Prevention Conventions"] == text.index("## Testing Patterns")
    assert rows["## Testing Patterns"] > 0


def test_a_following_h1_ends_the_section(tmp_path):
    """(f): the file's tail after a `# ` heading is not part of the section."""
    text = SECTION + "# Appendix\n\n" + "tail\n" * 200
    rows, total, _ = measure(tmp_path, text)
    assert total == len(SECTION)


def test_a_subsection_belongs_to_its_section(tmp_path):
    text = "## Prevention Conventions\n\n### Python\n\n- r\n\n### SQL\n\n- s\n\n## Next\n"
    rows, total, _ = measure(tmp_path, text)
    assert total == text.index("## Next")


@pytest.mark.parametrize("opener,closer,inner", [
    ("```", "```", "## Fake"),
    ("~~~", "~~~", "## Fake"),
    ("````", "````", "```\n## Fake\n```"),           # a shorter marker inside does not close it
    ("```", "````", "## Fake"),                      # a longer closer closes
    ("```", "```", "```json\n## Fake"),              # a marker with an info string does not close
    ("   ```", "   ```", "## Fake"),                 # an indented fence, as in a list item
], ids=["backticks", "tildes", "shorter-inside", "longer-closer", "info-string-inside", "indented"])
def test_fence_closer_rules(tmp_path, opener, closer, inner):
    text = SECTION + f"{opener}\n{inner}\n{closer}\n\nafter\n\n## Next\n"
    rows, total, err = measure(tmp_path, text)
    assert total == text.index("## Next"), (total, text)
    assert "never closes" not in err


def test_a_tilde_marker_does_not_close_a_backtick_fence(tmp_path):
    text = SECTION + "```\n~~~\n## Fake\n```\n\n## Next\n"
    rows, total, _ = measure(tmp_path, text)
    assert total == text.index("## Next")


def test_an_unclosed_fence_is_reported_and_the_file_measured_without_fences(tmp_path):
    """A fence that runs to the end would hide every heading after it, a silent zero."""
    text = "# P\n\n```\nunclosed\n\n" + SECTION
    rows, total, err = measure(tmp_path, text)
    assert "line 3 opens a fence or comment that never closes" in err
    assert total == len(SECTION)


def test_an_h3_heading_stays_out_of_spec(tmp_path):
    """(c): § 6.1 makes the sections top-level; the zero check names an `###` one."""
    rows, total, _ = measure(tmp_path, "### Prevention Conventions\n\n- r\n")
    assert total == 0


def test_an_indented_heading_line_is_not_a_heading_here(tmp_path):
    """Kept as the old program had it: only a column-0 `## ` opens a section."""
    rows, total, _ = measure(tmp_path, "   ## Prevention Conventions\n\n- r\n")
    assert total == 0


@pytest.mark.parametrize("text", [
    SECTION + "## Testing Patterns\n\n- t\n",
    "# Title\n\n" + SECTION,
    SECTION.rstrip("\n"),                                   # at EOF with no trailing newline
    "intro\n\n" + SECTION + "```\nafter the section\n```\n",  # a fence AFTER a real section
    "## Prevention Conventions\n",
    "## Prevention Conventions",
    "",
], ids=["two-sections", "after-title", "eof-no-newline", "fence-after", "heading-only",
        "heading-only-no-newline", "empty-file"])
def test_healthy_input_measures_as_before(tmp_path, text):
    rows, total, err = measure(tmp_path, text)
    assert total == old_measure(text, "Prevention Conventions"), (total, text)
    assert err == ""


def test_the_zero_arms_step_file_no_longer_calls_the_measurement_fence_blind():
    step = STEP.read_text(encoding="utf-8")
    assert "fence-blind" not in step and "first-match-wins" not in step


# --- the round's cases (Phase 465) ----------------------------------------------------
BODY = "- rule\n" * 1500


@pytest.mark.parametrize("before", [
    "```suggestion``` comments are welcome.\n\n",            # an inline span, not a fence
    "Example:\n\n    ```\n\n",                              # indented code, not a fence
    "## Commands\n\n```markdown\n1. step\n\n    ```bash\n    make\n    ```\n```\n\n",  # a 4-space closer is not one
], ids=["inline-span", "indented-four", "closer-indented-four"])
def test_a_phantom_fence_does_not_hide_the_section(tmp_path, before):
    """The first walker took any line starting with ``` for a fence: a TOTAL of 0 with no note,
    which sends Step 2b to the zero arm and drops the conventions from every prompt."""
    text = "# P\n\n" + before + SECTION + BODY + "```bash\nmake\n```\n\n## Next\n"
    rows, total, err = measure(tmp_path, text)
    assert total == old_measure(text, "Prevention Conventions") > 10_000, (total, err)


def test_a_heading_behind_a_forgotten_closer_is_named(tmp_path):
    """No fence rule can tell a forgotten closer from a quoted example, so the measurement
    says where the name is, and the zero arm's step tells the runner to look."""
    text = "# P\n\n```\nunclosed at top\n\n" + SECTION + "```bash\nmake test\n```\n" + BODY + "## Next\n"
    rows, total, err = measure(tmp_path, text)
    assert total == 0
    assert "appears only inside a fenced block or comment (line 6)" in err


def test_an_unclosed_block_at_the_end_keeps_earlier_fences_skipped(tmp_path):
    text = ("# P\n\n" + SECTION + "```bash\n# run tests\nmake test\n```\n" + BODY
            + "## Next\n\n```\nunclosed at bottom\n")
    rows, total, err = measure(tmp_path, text)
    assert total == text.index("## Next") - text.index("## Prevention"), (total, err)
    assert "never closes" in err


def test_an_html_comment_line_does_not_end_the_section(tmp_path):
    text = SECTION + "<!--\n# TODO later\n-->\n" + BODY + "## Next\n"
    rows, total, _ = measure(tmp_path, text)
    assert total == text.index("## Next")


@pytest.mark.parametrize("heading", ["## Prevention Conventions ##", "##  Prevention Conventions",
                                     "##\tPrevention Conventions", "## Prevention Conventions  ###  "],
                         ids=["atx-closer", "two-spaces", "tab", "closer-and-blanks"])
def test_commonmark_heading_forms_are_the_section(tmp_path, heading):
    text = heading + "\n\n- rule\n\n## Next\n"
    rows, total, _ = measure(tmp_path, text)
    assert total == text.index("## Next")


@pytest.mark.parametrize("name", ["C++ rules", "Auth (boundaries)", "a.b*c?", "[x]"])
def test_a_name_with_regex_characters_is_matched_literally(tmp_path, name):
    text = f"## {name}\n\n- r\n\n## Next\n"
    rows, total, _ = measure(tmp_path, text, name)
    assert total == text.index("## Next")


def test_a_longer_heading_is_another_section(tmp_path):
    rows, total, _ = measure(tmp_path, "## Prevention Conventions (legacy)\n\n- old\n")
    assert total == 0


def test_a_hashtag_line_does_not_end_the_section(tmp_path):
    text = SECTION + "#hashtag and ##double\n" + BODY + "## Next\n"
    rows, total, _ = measure(tmp_path, text)
    assert total == text.index("## Next")


@pytest.mark.parametrize("end", ["##", "#", "#\tTitle", "##\t"], ids=["bare-h2", "bare-h1", "h1-tab", "h2-tab"])
def test_an_empty_or_tab_heading_ends_the_section(tmp_path, end):
    text = SECTION + end + "\n" + "tail\n" * 50
    rows, total, _ = measure(tmp_path, text)
    assert total == len(SECTION)


def test_a_closer_with_trailing_blanks_closes(tmp_path):
    text = SECTION + "```\n## Fake\n```  \t\n\nafter\n\n## Next\n"
    rows, total, err = measure(tmp_path, text)
    assert total == text.index("## Next")
    assert "never closes" not in err

