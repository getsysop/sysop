"""The close path's two `CLAUDE.md` readers and the fence-opener rule.

`close_arms.read_policy` (Step 4-pre's `## Merge policy`, and `close_batch.sh`'s through
`read-policy`) toggled on any line that started with three backticks or tildes: no character,
length or closer check, and no CommonMark opener rule. A ```` ```a`b``` is inline ```` line, a
```` ``` ```` inside a `~~~` block, or a 3-backtick line inside a 4-backtick fence each flipped it,
hid a real `## Merge policy`, and read `direct`, which pushes the default branch.
`close_run.section_pairs` (`## Second reader`, `## Unattended close class`) had the closer
checks but read the inline-code line as an opener, and refused a real section as missing.

The first fix's round found the fence reader alone still answering wrong in both directions
(a list item's four-space ``` closing a column-0 example block; a nested example ending
early), so `read_policy` now answers only when unambiguous: every merge-policy-shaped line is
also read with fences ignored, and the two reads must give one word (Wade, 2026-11-11).
`fenced_read` below is the fence reader alone; `read_policy` is the whole rule.

CommonMark: a backtick fence's info string may not hold a backtick; a tilde fence's may.
`markdown-it-py` (CommonMark mode) is the oracle, as in `test_fence_opener_info_string.py`.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from markdown_it import MarkdownIt

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "core" / "companion" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import close_arms  # noqa: E402
import close_run  # noqa: E402

_MD = MarkdownIt("commonmark")
PROBE = "```a`b``` is inline"


def _headings(text: str) -> list[str]:
    toks = _MD.parse(text)
    return [toks[i + 1].content for i, t in enumerate(toks) if t.type == "heading_open"]


def _policy(tmp_path: Path, text: str) -> tuple:
    (tmp_path / "CLAUDE.md").write_text(text, encoding="utf-8")
    return close_arms.read_policy(tmp_path)


# ── close_arms.fenced_read: the fence reader alone ───────────────────────────────────────

def _fenced(text: str) -> tuple:
    return close_arms.fenced_read(text.split("\n"))


#: Each body holds one real `## Merge policy` (`pr`) per CommonMark, behind a line the old
#: toggle read as a fence. Every row read `direct` at `bedf4590`.
HIDDEN_BY_A_PHANTOM = [
    pytest.param(f"# P\n\n{PROBE}\n\n## Merge policy\n\npr\n", id="inline-code-line"),
    pytest.param("# P\n\n~~~\n```\n~~~\n\n## Merge policy\n\npr\n", id="backticks-in-tilde"),
    pytest.param("# P\n\n````\n```\n````\n\n## Merge policy\n\npr\n", id="short-run-in-long"),
    pytest.param("# P\n\n```bash\n```py\n```\n\n## Merge policy\n\npr\n", id="info-line-in-fence"),
]


@pytest.mark.parametrize("text", HIDDEN_BY_A_PHANTOM)
def test_a_line_that_is_no_fence_hides_no_policy(tmp_path, text):
    assert _headings(text) == ["P", "Merge policy"], "oracle: the section is real"
    assert _fenced(text) == ("pr", "declared in CLAUDE.md ## Merge policy", False)
    assert _policy(tmp_path, text) == ("pr", "declared in CLAUDE.md ## Merge policy")


#: The fence reader on its own, where a fenced example says `direct` and the real section
#: says `pr`. `read_policy` refuses each of these (two words), so only this read can show
#: that the pairing itself is right.
FENCED_EXAMPLE_THEN_PR = [
    pytest.param("# P\n\n~~~a`b\n## Merge policy\n\ndirect\n~~~\n\n## Merge policy\n\npr\n",
                 id="tilde-info-holds-a-backtick"),
    pytest.param("# P\n\n```\n```a`b```\n## Merge policy\n\ndirect\n```\n\n## Merge policy\n\npr\n",
                 id="inline-code-line-inside-a-fence-closes-nothing"),
    # A longer marker of the other character inside: no close (the round's survivor fixture,
    # which a caller-side `>` length test read the other way).
    pytest.param("# P\n\n~~~\n````\n## Merge policy\n\ndirect\n~~~\n\n## Merge policy\n\npr\n",
                 id="other-character-inside"),
    # Equal length closes; shorter does not.
    pytest.param("# P\n\n````\n```\n## Merge policy\n\ndirect\n````\n\n## Merge policy\n\npr\n",
                 id="equal-length-closes"),
    pytest.param("# P\n\n```\n## Merge policy\n\ndirect\n`````\n\n## Merge policy\n\npr\n",
                 id="longer-closes"),
    # A list item's four-space ``` inside a column-0 block is content (the round's HIGH).
    pytest.param("# P\n\n```markdown\n1. Run:\n    ```bash\n## Merge policy\n\ndirect\n    ```\n"
                 "```\n\n## Merge policy\n\npr\n", id="closer-indent-bound"),
]


@pytest.mark.parametrize("text", FENCED_EXAMPLE_THEN_PR)
def test_the_fence_reader_pairs_fences_as_commonmark_does(text):
    assert _headings(text)[-1] == "Merge policy" and _headings(text).count("Merge policy") == 1
    assert _fenced(text) == ("pr", "declared in CLAUDE.md ## Merge policy", False)


@pytest.mark.parametrize("ind", [" ", "  ", "   ", "    ", "\t", "\f", "\v", " \t"])
def test_a_marker_at_any_indent_counts(ind):
    """Pinned on purpose. A tab-indented fence is a list item's fence (`- a\n\n\t```...`);
    CommonMark reads `\f`/`\v` as no indent, so a top-level `\f```` is a paragraph there, but
    this reader has counted them since it was written, and the unambiguity rule refuses
    wherever that matters."""
    text = f"{ind}```\n## Merge policy\n\npr\n{ind}```\n"
    assert close_arms.fence_mark(f"{ind}```") == ("`", 3)
    assert _fenced(text) == ("direct", "no ## Merge policy in CLAUDE.md; default direct", False)


@pytest.mark.parametrize("k", range(0, 9))
def test_a_closer_counts_up_to_three_columns_past_its_opener(k):
    for opener_indent in (0, 4):
        want = k <= opener_indent + 3
        assert close_arms.fence_closes(" " * k + "```", ("`", 3), opener_indent) is want, (
            opener_indent, k)
    # At column 0 this is CommonMark's rule exactly.
    text = "```\n## A\n" + " " * k + "```\n## B\n"
    assert ("B" in _headings(text)) is (k <= 3)


#: A fence that never closes over the section: the fence reader cannot decide.
UNDECIDED = [
    pytest.param("# P\n\n```\nstray\n\n## Merge policy\n\npr\n", id="hides-the-heading"),
    pytest.param("## Merge policy\n\n```\npr\n", id="hides-the-word"),
    pytest.param("# P\n\n1. ```bash\n   ls\n   ```\n\n## Merge policy\n\ndirect\n",
                 id="list-item-opener-on-the-marker-line"),
]


@pytest.mark.parametrize("text", UNDECIDED)
def test_an_open_fence_over_the_section_is_undecided(text):
    assert _fenced(text)[2] is True


def test_a_closed_fences_hidden_heading_does_not_carry_over():
    assert _fenced("```\n## Merge policy\n\ndirect\n```\n\n~~~\n")[2] is False


# ── close_arms.read_policy: answer only when unambiguous ─────────────────────────────────

def _cm_policy(text: str) -> str:
    """CommonMark's answer: the first word under the first real `## Merge policy`."""
    toks = _MD.parse(text)
    for i, t in enumerate(toks):
        if t.type == "heading_open" and t.tag == "h2" and toks[i + 1].content == "Merge policy":
            for u in toks[i + 3:]:
                if u.type == "inline":
                    return u.content.split()[0].strip("`*_").lower()
                if u.type == "heading_open":
                    break
            return "direct"
    return "direct"


#: `(CLAUDE.md, answer)`, `""` a refusal. Every fixture the round ran, and each class it named.
#: No row reads a silent `direct` where a merge-policy line says `pr`.
ROUND = [
    pytest.param("# P\n\n## Task body example\n\n```markdown\n1. Run:\n    ```bash\n    make\n"
                 "    ```\n```\n\n## Merge policy\n\npr\n\n## Commands\n\n```bash\nmake test\n```\n",
                 "pr", id="HIGH-list-item-closer-in-an-example"),
    pytest.param("# P\n\n```markdown\n```bash\nmake\n```\n```\n\n## Merge policy\n\npr\n\n"
                 "## Commands\n\n```bash\nmake test\n```\n", "", id="nested-same-length"),
    # Nothing closes the outer closer's new fence, so the fence reader cannot decide and the
    # one merge-policy line answers (Wade's rule). CommonMark reads no section here; the old
    # toggle read `pr`.
    pytest.param("# P\n\n```markdown\n```bash\nx\n```\n```\n\n## Merge policy\n\npr\n", "pr",
                 id="nested-same-length-nothing-after"),
    pytest.param("# P\n\n1. ```bash\n   ls\n   ```\n\n## Merge policy\n\ndirect\n", "direct",
                 id="list-item-opener-on-the-marker-line"),
    pytest.param("# P\n\n<!--\n```\n-->\n\n## Merge policy\n\npr\n", "pr", id="fence-in-a-comment"),
    pytest.param("# P\n\nExample:\n\n    ```\n\n## Merge policy\n\npr\n\n```\ncode\n```\n", "",
                 id="lone-indented-marker-then-a-fence"),
    pytest.param("# P\n\nExample:\n\n\t```\n\n## Merge policy\n\npr\n\n```\ncode\n```\n", "",
                 id="lone-tab-marker-then-a-fence"),
    pytest.param("# P\n\nExample:\n\n    ```\n\n## Merge policy\n\npr\n\n```\n## Merge policy\n\n"
                 "direct\n```\n", "", id="lone-indented-marker-then-a-fenced-direct"),
    # The lone marker with nothing after it: no fence closes, so the fence reader cannot
    # decide, and the one merge-policy line answers.
    pytest.param("# P\n\nExample:\n\n    ```\n\n## Merge policy\n\npr\n", "pr",
                 id="lone-indented-marker-nothing-after"),
    # A stray opener never closed: undecided, so the line answers (CommonMark: no section).
    pytest.param("# P\n\n```\nstray\n\n## Merge policy\n\npr\n", "pr", id="open-fence-over-pr"),
    # A fenced example only: an example is not the setting, so `pr` there refuses; a fenced
    # `direct` reads `direct`, as both reads agree.
    pytest.param("# P\n\n```markdown\n## Merge policy\n\npr\n```\n", "", id="fenced-pr-only"),
    pytest.param("# P\n\n```markdown\n## Merge policy\n\ndirect\n```\n", "direct",
                 id="fenced-direct-only"),
    pytest.param("# P\n\n```markdown\n## Merge policy\n\npr\n```\n\n## Merge policy\n\ndirect\n",
                 "", id="fenced-pr-then-real-direct"),
    pytest.param("# P\n\n```markdown\n## Merge policy\n\ndirect\n```\n\n## Merge policy\n\npr\n",
                 "", id="fenced-direct-then-real-pr"),
    # Two unfenced merge-policy lines that disagree refuse, wherever they are.
    pytest.param("## Merge policy\n\npr\n\n### Merge policy history\n\nold\n", "",
                 id="a-later-heading-that-disagrees"),
    pytest.param("## Merge policy\n\npr\n\n```\n## Merge policy\n\npr\n```\n", "pr",
                 id="a-fenced-copy-that-agrees"),
    # A heading the section rule refuses has no word, so it never votes `direct`: hidden by a
    # phantom fence, or under a fence that never closes, it refuses.
    pytest.param("# P\n\nExample:\n\n    ```\n\n## Merge policy — pr\n\n## Commands\n\n"
                 "```bash\nmake\n```\n", "", id="inexact-heading-under-a-phantom-fence"),
    pytest.param("# P\n\n```\nstray\n\n## Merge policy: pr\n", "",
                 id="inexact-heading-under-an-open-fence"),
    # A section that is outside every fence but below one the reader mis-pairs refuses; the
    # message's exit, the section above the first code block, reads.
    pytest.param("# P\n\n1. ```bash\n   ls\n   ```\n\n## Merge policy\n\npr\n\n## Commands\n\n"
                 "```bash\nmake\n```\n", "", id="mis-paired-below"),
    pytest.param("# P\n\n## Merge policy\n\npr\n\n1. ```bash\n   ls\n   ```\n\n## Commands\n\n"
                 "```bash\nmake\n```\n", "pr", id="mis-paired-below-moved-above"),
    # The section's word sits in a fence that never closes: undecided, and the shaped read
    # skips the marker line, so the word under the heading answers.
    pytest.param("## Merge policy\n\n```\npr\n", "pr", id="word-in-an-open-fence"),
    # The fence reader's separation of a caller-side `>` length test: an equal-length closer.
    pytest.param("# P\n\n````\n```\n````\n\n## Merge policy\n\npr\n\n`````\n", "pr",
                 id="equal-length-closer-then-a-longer-fence"),
    # Round 2: a code comment that starts with the words is a shaped line too, so it refuses
    # (loud); the exit the message names, rewording it, reads the section.
    pytest.param("# P\n\n```bash\n# Merge policy check: see below\ngh api x\n```\n\n"
                 "## Merge policy\n\npr\n", "", id="code-comment-in-a-fence"),
    pytest.param("# P\n\n```bash\n# Policy check: see below\ngh api x\n```\n\n"
                 "## Merge policy\n\npr\n", "pr", id="code-comment-reworded"),
]


def test_a_tab_indent_counts_to_the_next_multiple_of_four():
    """Round 2's survivor CA10: `indent_of` counting a tab as one column changed 132 answers in
    a 100,000-file differential (pr and refusal, never a silent `direct`)."""
    assert close_arms.indent_of("\t```") == 4
    assert close_arms.indent_of("  \t```") == 4
    assert close_arms.indent_of("    \t```") == 8
    assert close_arms.indent_of("   ```") == 3


@pytest.mark.parametrize("text,want", ROUND)
def test_the_answer_is_commonmarks_or_a_refusal(tmp_path, text, want):
    policy, why = _policy(tmp_path, text)
    assert policy == want, why
    if not want:
        assert "outside any code block" in why and "line " in why, why
        assert "above the file's first code block" in why, why
    elif not close_arms.fenced_read(text.split("\n"))[2]:
        assert want == _cm_policy(text), "oracle disagrees with a decided answer"
    if re.search(r"\bpr\b", text, re.I):
        assert policy != "direct", "a silent direct where a merge-policy line says pr"


def test_the_refusal_names_each_line_and_word(tmp_path):
    _, why = _policy(tmp_path, "# P\n\n```markdown\n## Merge policy\n\npr\n```\n\n"
                               "## Merge policy\n\ndirect\n")
    assert "line 4: 'pr'" in why and "line 9: 'direct'" in why, why


@pytest.mark.parametrize("text,want", [
    pytest.param(None, ("direct", "no readable CLAUDE.md"), id="no-file"),
    pytest.param("# P\n", ("direct", "no ## Merge policy in CLAUDE.md; default direct"),
                 id="no-section"),
    pytest.param("# P\n\n```\n### Merge policy\n```\n", ("", None), id="fenced-inexact-heading"),
    pytest.param("# P\n\n## Merge policy\n", ("direct",
                 "## Merge policy in CLAUDE.md is empty; default direct"), id="empty"),
])
def test_the_existing_answers_keep_their_messages(tmp_path, text, want):
    if text is not None:
        (tmp_path / "CLAUDE.md").write_text(text)
    policy, why = close_arms.read_policy(tmp_path)
    assert policy == want[0] and (want[1] is None or why == want[1]), why


def test_read_policy_cli_refuses_with_exit_2(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# P\n\n```markdown\n## Merge policy\n\npr\n```\n")
    p = subprocess.run([sys.executable, str(SCRIPTS / "close_arms.py"), "read-policy",
                        str(tmp_path)], capture_output=True, text=True)
    assert (p.returncode, p.stdout) == (2, ""), (p.stdout, p.stderr)
    assert "outside any code block" in p.stderr


def test_policy_records_nothing_on_the_refusal(tmp_path):
    """`begin` and `policy` take the same refusal: exit 2, and no `policy` record."""
    r = tmp_path / "repo"
    env = {k: v for k, v in __import__("os").environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True, env=env)
    subprocess.run(["git", "-C", str(r), "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                    "-q", "--allow-empty", "-m", "init"], check=True, env=env)

    def run(*a):
        return subprocess.run([sys.executable, str(SCRIPTS / "close_arms.py"), *a], cwd=r,
                              capture_output=True, text=True, env=env)

    p = run("begin", "", *sorted(close_arms.ARMS))
    assert p.returncode == 0, p.stderr
    cid = p.stdout.split()[1]
    (r / "CLAUDE.md").write_text("# P\n\n```markdown\n## Merge policy\n\npr\n```\n")
    p = run("policy", cid)
    assert p.returncode == 2 and "outside any code block" in p.stderr, (p.stdout, p.stderr)
    rows = (r / "sysop" / "runtime" / "close-arms" / f"{cid}.tsv").read_text().splitlines()
    assert not [x for x in rows if x.startswith("policy\t")], rows
    assert run("begin", "", *sorted(close_arms.ARMS)).returncode == 2


def _skip_without_claude_md():
    # CLAUDE.md is mirror-excluded: on the public snapshot read_policy finds no file and reads
    # the default `direct`, so the read is skipped there (tests/test_mirror_skip_discipline.py).
    if not (REPO / "CLAUDE.md").is_file():
        pytest.skip("CLAUDE.md is mirror-excluded and absent on this tree")


def test_this_repos_own_claude_md_reads_pr():
    _skip_without_claude_md()
    assert close_arms.read_policy(REPO) == ("pr", "declared in CLAUDE.md ## Merge policy")


def test_the_claude_md_skip_stays_off_in_the_source_repo():
    """The skip above is for the public mirror. In the source repo it must not fire, or the
    policy test would skip in CI with nothing red. The sentinel is a second mirror-excluded
    file, so a skip keyed on CLAUDE.md cannot hide its own loss."""
    if not (REPO / "tests" / "test_mirror_leak_gate.py").is_file():
        pytest.skip("the public mirror, where this skip is meant to fire")
    try:
        _skip_without_claude_md()
    except pytest.skip.Exception as e:
        pytest.fail(f"a mirror skip fired in the source repo: {e}")


# ── close_run.section_pairs ─────────────────────────────────────────────────────────────

def _pairs(tmp_path: Path, text: str):
    (tmp_path / "CLAUDE.md").write_text(text, encoding="utf-8")
    try:
        return close_run.section_pairs(tmp_path, "Thing", ("k",))
    except close_run.Refuse as e:
        return f"Refuse: {e}"


def test_section_pairs_reads_past_an_inline_code_line(tmp_path):
    text = f"# P\n\n{PROBE}\n\n## Thing\n\nk: v\n"
    assert _headings(text) == ["P", "Thing"]
    assert _pairs(tmp_path, text) == [("k", "v")]


@pytest.mark.parametrize("text", [
    pytest.param("# P\n\n~~~a`b\n## Thing\nk: x\n~~~\n\n## Thing\n\nk: v\n", id="tilde-info"),
    pytest.param("# P\n\n```\n```a`b```\n## Thing\nk: x\n```\n\n## Thing\n\nk: v\n",
                 id="inline-line-inside-a-fence"),
    pytest.param("# P\n\n~~~\n```\n## Thing\nk: x\n~~~\n\n## Thing\n\nk: v\n",
                 id="backticks-in-tilde"),
])
def test_section_pairs_controls(tmp_path, text):
    assert _headings(text)[-1] == "Thing"
    assert _pairs(tmp_path, text) == [("k", "v")]
