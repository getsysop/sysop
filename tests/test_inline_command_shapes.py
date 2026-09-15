"""Phase 222 (Q-047) — inline script mentions that are commands must carry a command word.

Every shipped permission rule is `Bash(bash sysop/scripts/X.sh:*)` (or `python3 …`), and
the matcher treats a different command word as a different match — a bare
`sysop/scripts/close_batch.sh <N1> <N2>` binds no rule (Phase 126's matcher facts).
`WORKFLOW.md` § 4 shipped six such sites; an agent following the doc copies the span
as-is and hits a permission wall the template was supposed to have covered.

`tests/test_prescribed_command_coverage.py` deliberately reads ```bash fences only,
because it declines to judge imperative-vs-descriptive prose mechanically — and Q-047's
own filing says widening it is the wrong move. This guard uses a different, mechanical
predicate that sidesteps that judgment entirely: an *inline code span* whose text is a
`sysop/scripts/` script path **followed by arguments** is a command line whichever way
the surrounding prose reads (a bare path mention has no arguments and is untouched).
Command lines get a command word; run across the whole shipped tree, the predicate has
zero false positives today.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SHIPPED_MD = sorted(
    list((REPO_ROOT / "core").rglob("*.md")) + list((REPO_ROOT / "packs").rglob("*.md"))
)

# An inline span opening directly with the script path and carrying at least one
# argument (space + something). `<`/`-` cover the two argument shapes the six filed
# sites used (`<TASK_ID>`, `--clean`), and a bare `word` argument counts too.
_BARE_COMMAND_SPAN = re.compile(r"`(?:\./)?sysop/scripts/[a-z_.]+\.(?:sh|py)\s+[^`]+`")


def test_no_inline_script_command_lacks_its_command_word():
    offenders = []
    for f in SHIPPED_MD:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for m in _BARE_COMMAND_SPAN.finditer(line):
                offenders.append(f"{f.relative_to(REPO_ROOT)}:{i} {m.group(0)}")
    assert not offenders, (
        "inline script command(s) without a `bash `/`python3 ` command word — these "
        "bind no shipped permission rule (Q-047):\n" + "\n".join(offenders)
    )


def test_the_corpus_still_contains_correctly_worded_commands():
    """Floor: the predicate must keep seeing the class it polices. If every
    `bash sysop/scripts/…` span vanished from WORKFLOW.md, the test above would be
    green over an extraction failure rather than a clean tree."""
    wf = (REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md").read_text(
        encoding="utf-8"
    )
    worded = re.findall(r"`(?:bash|python3) sysop/scripts/[a-z_.]+\.(?:sh|py)[^`]*`", wf)
    assert len(worded) >= 14, (
        f"expected >=14 command-worded inline script spans in WORKFLOW.md, found "
        f"{len(worded)} — re-derive before weakening"
    )


# The round's IC-2: a command written in BARE PROSE ("run sysop/scripts/close_batch.sh
# 3 4") sat in no module's domain — the span check wants backticks, the fence sweep
# wants a fence. Population derived across the whole shipped tree before landing:
# zero false positives.
_BARE_PROSE_COMMAND = re.compile(
    r"(?<![`/\w.])(?:\./)?sysop/scripts/[a-z_.]+\.(?:sh|py)\s+\S"
)
_COMMAND_WORD_BEFORE = re.compile(r"(?:bash|python3)\s*$")


def _spans_masked(lines: list[str], keep: list[int]) -> dict[int, str]:
    """The unfenced lines with inline code spans blanked — ACROSS line breaks.

    `Q-495`: this was `re.sub(r"`[^`]*`", "", line)`, per line. An inline code span may
    legally carry a soft line break (CommonMark renders it as a space), so a span that a
    re-wrap split left its tail unmasked and the scan below read a command inside a code
    span as bare prose — reporting the skill as unable to bind a permission rule for text
    that was never outside a span. Masking preserves newlines so line numbers survive.
    """
    def blank(m):
        return "".join("\n" if c == "\n" else " " for c in m.group(0))

    out, run = {}, []
    for i in keep + [None]:
        # CONTIGUOUS runs only: a fence between two prose lines is a real boundary, and
        # joining across it let a backtick pair with one on the far side, blanking text
        # that the exemption below reads. A span may cross a line break; it may not cross
        # a fenced block.
        if run and (i is None or i != run[-1] + 1):
            # A BLANK LINE TERMINATES an inline code span in CommonMark, and a pattern
            # that ignores that lets one unbalanced backtick pair with another paragraphs
            # away and blank out everything between. Measured on `review-close/SKILL.md`:
            # the blank-line-blind form `` `[^`]*` `` masks 233,745 characters against
            # 87,437, so 146,308 characters of prose were hidden from this scan -- the
            # guard going blind, not merely tolerant. It is the same "a blank line is not
            # whitespace to cross" rule `_SOFT_BREAK` states, which this phase wrote and
            # then broke one file over. Found by its round with a planted offender.
            masked = re.sub(r"`(?:[^`\n]|\n(?![^\S\n]*\n))*`", blank,
                            "\n".join(lines[j] for j in run))
            out.update(zip(run, masked.split("\n")))
            run = []
        if i is not None:
            run.append(i)
    return out


def test_no_bare_prose_script_command_either():
    offenders = []
    for f in SHIPPED_MD:
        lines = f.read_text(encoding="utf-8").splitlines()
        fence, keep = False, []
        for i, line in enumerate(lines):
            if line.lstrip().startswith("```"):
                fence = not fence
                continue
            if fence:
                continue  # fenced commands are test_prescribed_command_coverage's domain
            keep.append(i)
        masked = _spans_masked(lines, keep)
        for i in keep:
            stripped = masked[i]
            for m in _BARE_PROSE_COMMAND.finditer(stripped):
                if _COMMAND_WORD_BEFORE.search(stripped[: m.start()]):
                    continue
                offenders.append(f"{f.relative_to(REPO_ROOT)}:{i + 1}")
    assert not offenders, (
        "script command written in bare prose, outside any span or fence — no rule "
        "can bind it and no other module sees it (round survivor IC-2): "
        + ", ".join(offenders)
    )
