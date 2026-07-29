"""Shared primitives for the invocation-shape guards (Phase 153, hardened after review).

Three test modules pin the shapes that defeat a Claude Code permission allow-rule. They
all need the same thing first: **which lines in a skill markdown file are executable bash,
and which are prose describing executable bash.** Getting that boundary wrong is what made
the first draft of these guards weak, so it lives here once rather than three times.

The first draft classified any line containing a backtick as prose. That is a *content*
test, and it turned out to be a per-line opt-out that disabled every guard at once — a
trailing comment like ``git branch -D x || true  # tolerate a `missing` branch`` is a live
command that the filter dropped, and house style in these files is backtick-dense, so it
is the single most likely way an author trips it. It also hid ``PR=`gh pr list …` `` (a
capture in backtick form) from the very guard meant to catch captures. 88 of ~1950 real
fenced lines were being discarded.

The fix is *structural*: a line is executable iff it sits inside a ``` fence and is not a
comment. Fences are the actual prose/code boundary in these documents, they nest nothing,
and `test_fences_are_balanced` pins the one assumption that could silently break the scan.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "core" / "skills"

_FENCE_RE = re.compile(r"^\s*```")


def skill_files() -> list[Path]:
    return sorted(SKILLS_DIR.rglob("*.md"))


def fence_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if _FENCE_RE.match(line))


def fenced_text(text: str) -> str:
    """Everything inside ``` fences, blockquoted fences excluded.

    A `>`-prefixed fenced block is an illustration inside prose — several of these files
    quote a retired shape that way on purpose — so those lines are not live commands.
    """
    out: list[str] = []
    in_fence = False
    for raw in text.splitlines():
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence and not raw.lstrip().startswith(">"):
            out.append(raw)
    return "\n".join(out)


def live_command_lines(text: str) -> list[str]:
    """Executable bash lines: inside a fence, non-empty, not a whole-line comment.

    A *trailing* comment does not disqualify a line — that was the hole. Only a line whose
    first non-space character is `#` is a comment.
    """
    return [
        line.strip() for line in fenced_text(text).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


# --------------------------------------------------------------------------------------
# Shape predicates. Every guard and every non-vacuity twin calls THESE, so neutering a
# predicate makes its own twin fail — the property the first draft's `|| true` twin lacked
# (it re-implemented the check inline and could not fail for any change to the real one).
# --------------------------------------------------------------------------------------

# `X="$(gh …)"`, `X=$(gh …)`, and the backtick form `X=`gh …`` — all defeat a rule, which
# does not match past an assignment.
GH_CAPTURE_RE = re.compile(r"""\w+=\s*["']?(?:\$\(|`)\s*gh\b""")

# `|| true` / `|| :` anywhere on the line, not just at its end: a trailing comment, a `;`,
# a line continuation, or a following `&& …` all kept the first draft's `endswith` check
# from firing. `:` is the canonical short spelling of `true` and is equally not in the
# documented read-only set.
NOOP_TAIL_RE = re.compile(r"\|\|\s*(?:true|:)(?:\s|;|&|#|$|\\)")

# `for`/`while` … `do` … `done`, with `do` on the same line (`; do`) or the next one.
LOOP_RE = re.compile(
    r"\b(?:for|while)\b[^\n;]*(?:;\s*do|\n\s*do)\b(?P<body>.*?)\bdone\b", re.DOTALL
)

# Commands that write. A loop containing one of these cannot be authorized by any rule,
# because `for`/`done` are not documented command separators.
WRITE_CMD_RE = re.compile(
    r"\b(?:git\s+(?:add|commit|push|rm|mv|cherry-pick|branch\s+-D|worktree\s+remove|reset)"
    r"|gh\s+(?:pr|issue|api|release)"
    r"|rm|cp|mv|mkdir|tee)\b"
)

# `$TMPDIR` / `${TMPDIR}` without a `:-` default. Anchored on the *expansion syntax* rather
# than a text window, so `"$TMPDIR:-/tmp/x"` — a malformed guard that ships a broken path,
# and exactly the typo made when copying the real idiom from memory — is still caught.
BARE_TMPDIR_RE = re.compile(r"\$TMPDIR\b|\$\{TMPDIR\}")
GUARDED_TMPDIR_RE = re.compile(r"\$\{TMPDIR:-[^}]+\}")


def has_gh_capture(text: str) -> list[str]:
    return [ln for ln in live_command_lines(text) if GH_CAPTURE_RE.search(ln)]


def has_noop_tail(text: str) -> list[str]:
    return [ln for ln in live_command_lines(text) if NOOP_TAIL_RE.search(ln)]


def loops(text: str) -> list[re.Match]:
    return list(LOOP_RE.finditer(fenced_text(text)))


def loop_header(match: re.Match) -> str:
    return match.group(0).splitlines()[0].strip()


def has_bare_tmpdir(text: str) -> list[str]:
    """Lines using `$TMPDIR` without a `${TMPDIR:-…}` default, live commands only."""
    out = []
    for ln in live_command_lines(text):
        if not BARE_TMPDIR_RE.search(ln):
            continue
        # A line may legitimately contain the guarded form; only flag an occurrence that
        # is not part of one.
        stripped = GUARDED_TMPDIR_RE.sub("", ln)
        if BARE_TMPDIR_RE.search(stripped):
            out.append(ln)
    return out
