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


# --------------------------------------------------------------------------------------
# Phantom shell variables (Phase 169).
#
# Nothing survives from one fenced block to the next — the persistence boundary is the
# block, not the step (`WORKFLOW.md` § 8.2a *Persistence boundary*). A `$VAR` that its own
# block does not assign is therefore the empty string when the command runs.
#
# The maintainer-side worklist `tools/skill_audit_phantom_vars.py` implements the same
# idea; this is the shipped *gate*, and it differs in two ways that were the difference
# between finding 20 sites and finding 33:
#
#   1. It scans inline code spans in prose too. `review-close`'s Step 4a merge commands
#      are backticked list items, not a fenced block, so a fence-only walker cannot see
#      them — and they read a `$MERGE_TARGET` set one step earlier. `/daily-summary` had
#      two more of the same shape, calling its own shell functions from outside the block
#      that defines them.
#   2. `REPO_ROOT` is NOT treated as environment-provided. The worklist skipped it; nothing
#      in the tree exports it — `git grep 'export REPO_ROOT'` is empty. It is assigned
#      locally in nine-odd shell scripts (`claim_task.sh`, `batch_work.sh`,
#      `close_batch.sh`, `cleanup_worktrees.sh`, `run_checks.sh`, `self_check.sh`,
#      `install_hooks.sh`, `install.sh`, the merge hook), all of which are ordinary scripts
#      where variables persist normally. The skip was a standing hole that would pass the
#      first skill to write it in a fenced block.
# --------------------------------------------------------------------------------------

# Names something outside the skill genuinely sets, so a reference needs no in-block
# assignment. Kept short and individually justified: adding a name here is the cheapest
# way to silence this guard, which is why `test_env_provided_set_is_pinned` pins it.
ENV_PROVIDED = frozenset({
    "ARGUMENTS",                             # substituted by the skill runner
    "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS",  # harness
    "CLAUDE_PROJECT_DIR",                    # Claude Code hook env var
    "GH_TOKEN", "GITHUB_TOKEN",              # gh auth
    "HOME", "LANG", "OLDPWD", "PATH", "PWD", "SHELL", "TMPDIR", "USER",  # POSIX shell
    "IFS", "RANDOM",                         # shell built-ins
    "SSL_CERT_FILE",                         # semgrep trust anchors (Phase 135)
    "SYSOP_SRC",                             # consumer sets it in their shell rc (§ 8.2b)
    "WORKTREE_PREFIX",                       # documented opt-in, always read `${…:-}`
})

# `$FOO`/`${FOO}`, upper-case, ANY length. The worklist floors this at three characters;
# that floor hid `$PR`, `$ID` and `$WT` — and `$PR` is the very value `/review-close`'s
# persistence note is about, since an empty `gh` operand silently resolves the current
# branch. Rather than exempting a whole shape class to dodge one template, the single
# false positive it exists for is exempted BY NAME below (`$X.XX`, a dollar amount in
# `/auto-build`'s printed report table). Phase 169's round measured the cost: 24 distinct
# sub-floor/lower-case names appear in real fenced blocks and all but `$X` are assigned
# in-block, so the honest floor is "none".
PHANTOM_REF_RE = re.compile(r"\$\{?([A-Z][A-Z0-9_]*)\}?")

# An inline code span is treated as an executable prescription when it *starts with* a
# command word. That keeps prose like "`$MERGE_TARGET` is the branch …" out of the scan
# while catching "`git checkout \"$MERGE_TARGET\" && …`".
#
# The list of command words is NOT hardcoded alone: each file also contributes the shell
# functions it defines. A fixed list is an assumption about what a skill can invoke, and
# this one was wrong — `/daily-summary` defines `_days_ago`/`_date_minus`/`_day_name` in
# one block and calls them from inline code two paragraphs later, where neither the
# functions nor the `$TARGET_DATE` they are passed exist. Deriving the words from the
# file's own definitions is rule 1's "derive the population from the source of truth"
# applied to the detector itself.
# Widened by Phase 169's round from `git|gh|bash|python3|sh`. The repo already writes
# prescriptions in the rest — `/auto-fix` uses `mkdir -p <WORKTREE_PATH>/…` and
# `cd <WORKTREE_PATH> && git add -A` as inline list items, in exactly the idiom
# `/auto-build` had got wrong as `$WORKTREE_PATH`. Measured cost of the widening at the
# time: zero new findings, so this is a prospective hole closed, not a backlog.
_BASE_CMD_WORDS = (
    r"(?:\.venv/bin/)?(?:git|gh|bash|python3|sh|mkdir|rm|cp|mv|cat|cd|grep|sed|awk"
    r"|test|semgrep|pytest|npx|npm|ruff|tee|sysop/scripts/\S+)"
)
INLINE_CMD_RE = re.compile(rf"^{_BASE_CMD_WORDS}\s")
_FUNC_DEF_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{", re.M)


def shell_functions_defined_in(text: str) -> set[str]:
    """Names this file defines as shell functions, in any fenced block."""
    return set(_FUNC_DEF_RE.findall(fenced_text(text)))


def _inline_cmd_re_for(text: str) -> re.Pattern[str]:
    funcs = shell_functions_defined_in(text)
    if not funcs:
        return INLINE_CMD_RE
    alt = "|".join(re.escape(f) for f in sorted(funcs))
    return re.compile(rf"^(?:{_BASE_CMD_WORDS}|{alt})\s")

_ASSIGN_TEMPLATES = (
    r"(?:^|[;&|(\s])(?:export\s+|local\s+)?{v}\s*=",
    r"\bread\s+(?:-r\s+)?(?:\w+\s+)*{v}\b",
    r"\bfor\s+{v}\s+in\b",
)


def _strip_whole_line_comments(block: str) -> str:
    """Blank out `#` lines, preserving line count so offsets stay true.

    Both directions matter, and the worklist's docstring records finding this the hard
    way: a comment reading `# SUBSET_IDS = the …` reads as an assignment and hides a real
    phantom, while a `$VAR` inside a comment that *explains* the anti-pattern reads as one.
    """
    return re.sub(r"(?m)^\s*#.*$", "", block)


def assigned_in_block(var: str, block: str) -> bool:
    return any(
        re.search(t.format(v=re.escape(var)), block, re.M) for t in _ASSIGN_TEMPLATES
    )


_QUOTED_FENCE_RE = re.compile(r"^\s*>\s*```")


def fenced_blocks(text: str) -> list[tuple[int, str]]:
    """(1-indexed line number of the block's first content line, block text).

    **Blockquote-ness is a property of the block, decided by its opening fence — not of
    each line.** A `>`-quoted fence is an illustration and is skipped whole; every line of
    an ordinary fence is scanned, including lines that happen to start with `>`.

    The first draft blanked any fenced line beginning with `>`, and that was a live hole,
    not a nicety: a shell **redirection continued onto its own line** —

        echo "…" \\
          > "$WORKTREE_PATH/…/review.md"

    — is exactly that shape. `/auto-build` ships one, so reverting the 31st of this
    phase's own converted sites left the whole suite green while the *maintainer worklist*
    this module was written to supersede caught it. Found by Phase 169's round.
    """
    out: list[tuple[int, str]] = []
    buf: list[str] = []
    in_fence = False
    quoted = False
    start = 0
    for n, raw in enumerate(text.splitlines(), 1):
        if _FENCE_RE.match(raw) or _QUOTED_FENCE_RE.match(raw):
            if in_fence:
                if not quoted:
                    out.append((start, "\n".join(buf)))
                buf = []
            else:
                start = n + 1
                quoted = bool(_QUOTED_FENCE_RE.match(raw))
            in_fence = not in_fence
            continue
        if in_fence and not quoted:
            buf.append(raw)
    return out


def phantom_shell_vars(text: str) -> list[tuple[int, str, str]]:
    """(line_no, var, line) for every fenced-block `$VAR` its own block does not assign."""
    out: list[tuple[int, str, str]] = []
    for start, block in fenced_blocks(text):
        scanned = _strip_whole_line_comments(block)
        lines = scanned.splitlines()
        for m in PHANTOM_REF_RE.finditer(scanned):
            var = m.group(1)
            if var in ENV_PROVIDED or assigned_in_block(var, scanned):
                continue
            # `$X.XX` in `/auto-build`'s printed spend table is a currency template, not a
            # variable. Exempted by its exact shape rather than by raising the name-length
            # floor: the floor was hiding `$PR`, `$ID` and `$WT` to dodge this one string.
            if var == "X" and scanned[m.end():m.end() + 3] == ".XX":
                continue
            offset = scanned[: m.start()].count("\n")
            out.append((start + offset, var, lines[offset].strip()))
    return out


def phantom_inline_commands(text: str) -> list[tuple[int, str]]:
    """(line_no, span) for backticked commands in prose that read a `$VAR`.

    Inline code carries no block to be assigned in, so *any* `$VAR` in one of these is
    cross-block by construction. Fenced regions are skipped (they are the other scan's
    job) and so are `>`-blockquoted prose lines, which quote retired shapes on purpose.
    """
    out: list[tuple[int, str]] = []
    cmd_re = _inline_cmd_re_for(text)
    in_fence = False
    for n, raw in enumerate(text.splitlines(), 1):
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence or raw.lstrip().startswith(">"):
            continue
        for span in re.findall(r"`([^`]+)`", raw):
            span = span.strip()
            if not cmd_re.match(span):
                continue
            for m in PHANTOM_REF_RE.finditer(span):
                if m.group(1) not in ENV_PROVIDED:
                    out.append((n, span))
                    break
    return out
