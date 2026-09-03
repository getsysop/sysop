"""
Automate archival of completed review batches from review_tasks.md
to review_tasks_archive.md.

Usage:
    python sysop/scripts/archive_review_tasks.py              # Archive all merged batches
    python sysop/scripts/archive_review_tasks.py --dry-run    # Preview without writing
"""

import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

# Single-sourced via sysop/scripts/_log.py (Phase 68) — `sysop/scripts/` is on
# sys.path[0] when this runs directly and on pythonpath under the test suite.
from _log import _sanitize_log  # noqa: E402


# Resolve against the repo root (the parent of sysop/), not CWD. A bare
# relative path opens against the caller's CWD, which from a worktree
# subdirectory or a caller that doesn't `cd` first either FileNotFoundErrors
# or — worse — opens an unrelated file with the same name. review_index.py
# solves the same CWD-independence goal with a git-root walk-up; this script
# is always installed at <repo-root>/sysop/scripts/ (Phase 128), so the
# great-grandparent (parents[2]) is the repo root, exactly.
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
REVIEW_FILE = os.path.join(_REPO_ROOT, "review_tasks.md")
ARCHIVE_FILE = os.path.join(_REPO_ROOT, "review_tasks_archive.md")


def _atomic_write_text(path, content):
    """Write `content` to `path` via tmp + fsync + os.replace.

    A crash mid-write must never leave a truncated file that downstream
    readers will then raise on. See CLAUDE.md § Data integrity.
    """
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _atomic_write_pair(path_a, content_a, path_b, content_b):
    """Two-file atomic rewrite — shrinks the crash window between writes.

    The archive flow rewrites both ``review_tasks.md`` AND
    ``review_tasks_archive.md`` in the same operation. ``_atomic_write_text``
    alone leaves a window between the two ``os.replace`` calls where a
    crash leaves duplicated state (archive has new rows AND review still
    has the un-archived rows). This helper writes both tmp files
    (with ``f.flush() + os.fsync``) first, then performs the two
    ``os.replace`` calls back-to-back so the window is narrowed to two
    consecutive syscalls.

    Note: this is not transactional — a hard crash between the two
    ``os.replace`` calls can still leave duplicated state. Recovery
    procedure: ``git status`` will show the duplicated rows in both
    files; revert one with ``git checkout -- <path>`` and re-run
    ``python sysop/scripts/archive_review_tasks.py``. The helper documents
    rather than prevents the residual risk.
    """
    tmp_a = path_a + ".tmp"
    tmp_b = path_b + ".tmp"
    try:
        with open(tmp_a, "w", encoding="utf-8") as f:
            f.write(content_a)
            f.flush()
            os.fsync(f.fileno())
        with open(tmp_b, "w", encoding="utf-8") as f:
            f.write(content_b)
            f.flush()
            os.fsync(f.fileno())
        # Both tmp files are now durable on disk; perform replaces back-to-back.
        os.replace(tmp_a, path_a)
        os.replace(tmp_b, path_b)
    except OSError:
        # Best-effort cleanup so a failed write never orphans a `.tmp` beside
        # the real file — an untracked `review_tasks*.md.tmp` at the repo root
        # would trip /review-close Step 1a dirty-classification (the same class
        # Phases 65a/106 guarded). A `.tmp` already renamed in by a successful
        # os.replace is gone; whatever remains is removed here. The write
        # failure itself is re-raised (archival is fatal on a write error).
        for _t in (tmp_a, tmp_b):
            try:
                if os.path.exists(_t):
                    os.unlink(_t)
            except OSError:
                pass
        raise

# Matches "## Round 20 (2026-03-05) — Code Quality Review + OWASP Security Audit"
ROUND_HEADER_RE = re.compile(r"^## (Round \d+.*)")

# Matches "### Batch 90 — Backend Core `Merged`" or `Complete`
BATCH_HEADER_RE = re.compile(
    r"^### (Batch \d+) — .+ `(Merged|Complete)`"
)

# Matches any batch header regardless of status — the DENOMINATOR in the
# `all_merged` test below, and deliberately the most permissive pattern in this
# file.
#
# It used to be `— .+ \`(\w[\w ]*)\``, which is a fifth status charset, narrower
# than the four structural readers use. A header it could not see was never
# counted, so `round_total_batches == len(batches)` held with an OPEN batch in
# the round — and an `all_merged` round is *relocated into the archive*.
# Measured against this exact function before the fix: `On-Hold`,
# `Blocked/waiting` and `Re-open` each produced `all_merged=True` for a round
# whose batch 2 was unmerged with an open task. That is the same harm the fence
# comment below records, arriving by a different route.
#
# The asymmetry is why permissive is not just safe here but required: an
# under-count silently archives live work, while an over-count only makes
# `all_merged` False, which keeps the round in place and loses nothing. So this
# pattern asks one question — is this line a batch header — and leaves every
# judgment about the status to BATCH_HEADER_RE's explicit `Merged|Complete`
# allowlist above.
#
# `\s+`, not literal spaces, and that distinction was worth a round: the first
# version widened only the STATUS charset and kept single literal spaces, so it
# still could not see `###\tBatch 8` or `### Batch  8`. Those headers went
# uncounted, `round_total_batches == len(batches)` held with an OPEN batch
# present, and the round was relocated into the archive — the same data loss
# this comment describes above, surviving the fix for it. Reproduced on the
# supposedly-fixed tree by Phase 191's adversarial round for all three
# whitespace shapes. The asymmetry argument above is exactly why this pattern
# must be the loosest thing that still means "batch header".
ANY_BATCH_HEADER_RE = re.compile(r"^###\s+(Batch\s+\d+)\b")

# The CANONICAL shape, any status — duplicated verbatim from
# `review_index._BATCH_HEADER_RE` and pinned equal by
# `tests/test_batch_header_near_miss.py`. Not imported: this module resolves its
# root via `parents[2]` while `review_index` walks up to the git root, so an
# import here can raise a non-ImportError in an environmental mismatch — which
# is why the only existing use of that module (`rebuild_index`) is lazy, inside
# a try/except, and AFTER the durable writes. A gate may not be built on an
# import that is allowed to fail.
#
# This sits BETWEEN the two patterns above and that is its whole job:
#   BATCH_HEADER_RE      canonical shape AND an archivable status
#   CANONICAL_BATCH_RE   canonical shape, ANY status   <- this one
#   ANY_BATCH_HEADER_RE  anything that looks like a batch header at all
#
# A `Pending` batch is not a near-miss — it matches the canonical pattern and is
# simply not archivable yet. A near-miss is a line that matches ANY and fails
# CANONICAL: no reader in the tree turns it into a batch, so it is neither
# archived nor counted, and until Phase 220 nothing said so.
CANONICAL_BATCH_RE = re.compile(r"^### Batch (\d+) — (.+?) `([^`]+)`$")


# The near-miss population, wider than `ANY_BATCH_HEADER_RE` on purpose and
# duplicated from `review_index._NEAR_MISS_HEADER_RE` — see that module for the
# argument. Kept in step because `tests/test_batch_header_near_miss.py` asserts
# the two twins agree on WHICH line is a near miss.
NEAR_MISS_HEADER_RE = re.compile(r"^#{2,4}\s*Batch\s+\d+\b", re.IGNORECASE)


def near_miss_batch_headers(lines):
    """Unfenced lines that look like a batch header but that this module's
    canonical pattern rejects.

    Twin of ``review_index.near_miss_batch_headers``; see that docstring for the
    canon argument and for why trailing whitespace is normalised away rather
    than reported (it was a false fire, and a regression against this module's
    own non-end-anchored ``BATCH_HEADER_RE``). Returns
    ``[(lineno_1based, text), ...]``.
    """
    mask = _fenced_mask(lines)
    out = []
    for i, line in enumerate(lines):
        if mask[i]:
            continue
        stripped = line.rstrip()
        if CANONICAL_BATCH_RE.match(stripped):
            continue
        if NEAR_MISS_HEADER_RE.match(stripped):
            out.append((i + 1, stripped))
    return out

# Any level-3 heading, whatever whitespace follows the marker. `####` and deeper
# are deliberately excluded (the char after `###` must be whitespace or EOL), so
# this stays a level-3 test rather than a prefix test.
H3_HEADER_RE = re.compile(r"^###(?:\s|$)")

# Fence detection, duplicated verbatim from review_index.py and pinned equal
# across all four readers by tests/test_flag_contract.py. This script is the
# fourth structural reader of review_tasks.md and was the last to be made
# fence-aware (Phase 181, second review round): a task quoting the tracker's
# own shapes inside a fenced block SPLIT A REAL MERGED ROUND IN TWO at the
# opening fence line. Both halves then reported `all_merged: True`, so both
# were relocated — with unbalanced fences on each side and a real `- [x]` task
# carried into the wrong archive block. This is the script the size advisory
# in /triage, /auto-fix and /auto-judge tells the operator to run.
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(?:> ?)*(`{3,}|~{3,})")
_FENCE_CLOSE_RE = re.compile(r"^ {0,3}(?:> ?)*(`{3,}|~{3,})[ \t]*$")


def _fenced_mask(lines):
    """True for every line inside a **balanced** fenced block, delimiters included.

    An **unterminated** fence is deliberately ignored — its lines stay
    structural. See review_index.py's copy for why (honouring one disables
    structural parsing to end-of-file, which is worse than no fence rule).
    """
    mask = [False] * len(lines)
    start = None
    marker = None
    for i, line in enumerate(lines):
        if start is None:
            m = _FENCE_OPEN_RE.match(line)
            if m:
                start, marker = i, m.group(1)
        else:
            m = _FENCE_CLOSE_RE.match(line)
            if m and m.group(1)[0] == marker[0] and len(m.group(1)) >= len(marker):
                for j in range(start, i + 1):
                    mask[j] = True
                start = marker = None
    return mask

# Matches task lines "- [x] **TASK-653**: ..."
TASK_RE = re.compile(r"^- \[x\] \*\*TASK-\d+\*\*")

# Matches a still-open task line — "- [ ] **TASK-653**: ..." or "- [/] ...".
# A `Merged` batch can legitimately hold one: close_batch.sh leaves a task
# annotated `> Failed:` unflipped, because a FAIL verdict means the work was
# attempted and not finished. Such a task is archivable but not *done*, and
# archiving moves it out of the live queue every open-task reader consults —
# so the run names it before the human confirms. Deliberately more permissive
# than TASK_RE about the id: for a warning, over-reporting beats missing one.
#
# The bold wrapper is OPTIONAL, and that is load-bearing rather than cosmetic.
# Phase 157's adversarial round found this regex requiring `**id**` while
# `close_batch.sh`'s `is_open_task` requires only `^- [ ]` — so an unbolded task
# (the shape `tests/test_close_batch_sh.py`'s own fixture uses) was held open by
# one script and swept out of the live queue silently by the other. Two regexes
# with different notions of "a task line" is exactly the desync the shared
# `CLOSE_AWK` program exists to prevent, reintroduced across a file boundary.
UNFINISHED_TASK_RE = re.compile(
    r"^- \[[ /]\][ \t]*(?:\*\*(?P<bold>[^*\n]+)\*\*|(?P<plain>[^\n]+))"
)

# The DENOMINATOR regex — a third one, and deliberately not a reuse of either
# above. Both existing patterns are wrong for arithmetic, in opposite directions,
# and the report this fix answers (internal tracker #393) proposed the one that
# fails in both:
#
#   * TASK_RE requires `**TASK-N**`, so `- [x] task one` — a shape close_batch.sh
#     treats as a real task and legitimately holds open — is NOT counted.
#   * UNFINISHED_TASK_RE is documented above as deliberately over-reporting
#     ("for a warning, over-reporting beats missing one"). Promoting a
#     deliberate over-reporter into a denominator makes the count wrong the
#     other way, and tightening it in place would red the guard asserting it
#     matches every line CLOSE_AWK holds open. Two consumers, two patterns.
#
# This one mirrors close_batch.sh's `is_open_task` (`^- [ ]` / `^- [/]`) plus the
# `[x]` its flip produces, because the counter and the flipper MUST agree about
# what a task line is — the same cross-file desync UNFINISHED_TASK_RE's own
# comment describes. Matching is anchored at column 0, so an indented sub-bullet
# (an `- [ ] **Acceptance**:` criterion inside a task body) is not a task here,
# and is not one to close_batch.sh either.
COUNTED_TASK_RE = re.compile(r"^- \[[ x/]\]")

# The same notion of a task line, restricted to the done box. Both halves of the
# ratio MUST come from one pattern: the first cut of this fix took the numerator
# from TASK_RE (bold id required) and the denominator from COUNTED_TASK_RE (bold
# id optional), so an unbolded `- [x] task one` counted in the denominator and
# not the numerator, and a finished round reported itself `0/1 ... Partial`.
# A ratio assembled from two different definitions is a new way to be wrong, not
# a fix for the old one.
COMPLETED_TASK_RE = re.compile(r"^- \[x\]")

# Matches the archive reference line (line ~14)
ARCHIVE_REF_RE = re.compile(
    r"^> \*\*Archive:\*\* Rounds .+ are in "
    r"\[review_tasks_archive\.md\]\(review_tasks_archive\.md\)\."
)

# Matches the Grand Total line in review_tasks.md
GRAND_TOTAL_RE = re.compile(
    r"^> \*\*Grand Total \(all rounds\):\*\* (\d+) tasks"
    r" \u2014 (\d+) done, (\d+) open, (\d+) deferred"
)

# Matches the "All completed work" line in review_tasks.md
ALL_COMPLETED_RE = re.compile(
    r"^> All completed work .+ archived in "
)

# Matches "## Grand Total (Archived)" in the archive
ARCHIVE_GRAND_TOTAL_HEADER = "## Grand Total (Archived)"

# Matches "| **Archive Total** |" in the archive
ARCHIVE_TOTAL_RE = re.compile(r"^\| \*\*Archive Total\*\*")


def _unterminated_fence(lines):
    """The opener of a fence that is never closed, or ``None``.

    Returns ``(start_index, marker)`` — ``start_index`` 0-indexed.

    Duplicated verbatim from ``review_index.py`` and pinned equal by
    ``tests/test_archive_fence_refusal.py``, for the same reason ``_fenced_mask``
    above is duplicated: this module resolves the markdown via ``parents[2]``
    while ``review_index`` walks up to the git root, so an import here can raise
    a non-``ImportError`` in an ordinary worktree. A *refusal* that can be
    skipped by an environmental import failure is worse than no refusal at all —
    it fails open on exactly the tree that is hardest to reason about.

    Both halves of the close rule are load-bearing: a 4-backtick opener is NOT
    closed by 3 backticks (length), and a ``~~~`` opener is NOT closed by
    ``` (char).
    """
    start = -1
    marker = ""
    for i, line in enumerate(lines):
        if start < 0:
            m = _FENCE_OPEN_RE.match(line)
            if m:
                start, marker = i, m.group(1)
        else:
            m = _FENCE_CLOSE_RE.match(line)
            if m and marker and m.group(1)[0] == marker[0] and len(m.group(1)) >= len(marker):
                start, marker = -1, ""

    if start < 0:
        return None
    return (start, marker)


def unterminated_batch_span(lines):
    """An unterminated fence whose span contains ANY ``### Batch <N>`` header.

    Returns ``(fence_line, marker, header_line, header_text)`` 1-indexed, or
    ``None``. Twin of ``review_index.unterminated_batch_span``.

    **Why the archiver needs its own refusal (Q-240).** ``_fenced_mask`` ignores
    an unterminated fence on purpose — honouring one would disable structural
    parsing to end-of-file, which is worse than no fence rule — so an example
    batch inside a fence nobody closed is parsed as a REAL batch. Measured on
    the shape this entry predicts (fence opener inside a preceding batch, so no
    orphan line sits above the first header): ``residue []``, 2 batches,
    ``TOTAL 2 tasks`` — the illustration counted as completed work and
    archivable, with nothing left to refuse it.

    Until now the only thing standing between that state and a destructive
    archive was the ``Q-116`` orphaned-lines guard catching the fence opener as
    a line belonging to no batch. That is **defence by coincidence**: it depends
    on where the opener happens to sit, and it disappears the moment the opener
    is inside a batch. This makes the refusal the declared mechanism instead.

    The archiver is the right place for a refusal that ``review_index`` does not
    make for reads: archiving MOVES content out of the tracker, so acting on the
    wrong structural answer deletes work. Reading it merely displays it wrong.
    Closing the fence is always the correct fix — the file is malformed markdown
    either way — so the remedy is one character.
    """
    hit = _unterminated_fence(lines)
    if hit is None:
        return None
    start, marker = hit
    for j in range(start + 1, len(lines)):
        if ANY_BATCH_HEADER_RE.match(lines[j]):
            return (start + 1, marker, j + 1, lines[j].rstrip())
    return None


def unterminated_task_span(lines):
    """An unterminated fence whose span contains a COUNTED task line.

    Returns ``(fence_line, marker, hit_line, hit_text)`` 1-indexed, or ``None``.

    **Companion to `unterminated_batch_span`, and it exists because that one is
    not sufficient.** The first cut of this phase refused only when a `### Batch`
    header sat inside an unterminated fence, and `count_round_tasks`'s docstring
    then claimed "the unterminated case … is refused outright before this is ever
    called". That was false, and the review round demonstrated it: an unterminated
    fence holding only `- [x]` illustration lines is neither masked (by design —
    `_fenced_mask` ignores unterminated fences) nor refused, so those lines counted
    as real completed work. Measured on one real task plus one unterminated
    illustration: `(2, 2)` instead of `(1, 1)`, and that number is what
    `update_archive_total` writes durably into the archive's Grand Total row.

    Kept SEPARATE from `unterminated_batch_span` rather than folded into it,
    because that function is duplicated verbatim from `review_index.py` and
    pinned equal by `tests/test_archive_fence_refusal.py`. Widening it here would
    break the pin or silently fork the twin.

    Deliberately narrow: a fence holding only prose is NOT refused. Nothing
    miscounts it, so refusing would be over-strictness on a file the operator has
    every right to keep — and a refusal that fires on legal input is the kind the
    next author weakens.
    """
    hit = _unterminated_fence(lines)
    if hit is None:
        return None
    start, marker = hit
    for j in range(start + 1, len(lines)):
        if COUNTED_TASK_RE.match(lines[j]):
            return (start + 1, marker, j + 1, lines[j].rstrip())
    return None


def parse_archivable_batches(lines):
    """Parse review_tasks.md and extract complete/merged batches grouped by round.

    Handles mixed-status rounds: a round may contain both merged and pending
    batches. Only merged/complete batches are collected; pending batches are
    counted but skipped. Each round gets an ``all_merged`` flag indicating
    whether every batch in the round is archivable.

    Returns:
        rounds: list of dicts with keys:
            - header: str (the "## Round ..." line)
            - batches: list of dicts with keys:
                - lines: list of str (all lines in the batch, including header)
                - task_count: int
                - start_line: int (0-indexed line where batch starts)
                - end_line: int (0-indexed line where batch ends, exclusive)
            - start_line: int (0-indexed line where round starts)
            - end_line: int (0-indexed line where round ends, exclusive)
            - all_merged: bool (True when every batch in the round is merged)
    """
    rounds = []
    current_round = None
    current_batch = None
    round_total_batches = 0
    i = 0
    fenced = _fenced_mask(lines)

    while i < len(lines):
        line = lines[i]

        # Fenced content is example text. Accumulate it into whatever batch is
        # open, but never let it open, close or reclassify one.
        if fenced[i]:
            if current_batch is not None:
                current_batch["lines"].append(line)
            elif current_round is not None:
                current_round["preamble"].append(line)
            i += 1
            continue

        round_match = ROUND_HEADER_RE.match(line)
        if round_match:
            # Close previous batch/round
            if current_batch:
                current_batch["end_line"] = i
                current_round["batches"].append(current_batch)
                current_batch = None
            if current_round:
                current_round["end_line"] = i
                current_round["all_merged"] = (
                    round_total_batches == len(current_round["batches"])
                )
                rounds.append(current_round)
            current_round = {
                "header": line,
                # Round-level metadata written between the `## Round` header and
                # the first `### Batch` — today the Tier-0 coverage ledger
                # (Phase 149), one line per audit type on a merged round. It
                # belongs to the ROUND, not to any batch, so it is captured
                # here and re-emitted by build_archive_block(). Without this it
                # falls in the gap between the header and the batches: deleted
                # from review_tasks.md with the round's line range and absent
                # from the archive, which would silently destroy the one
                # durable record of how much of the codebase a round opened.
                "preamble": [],
                "batches": [],
                "start_line": i,
                "end_line": None,
                "all_merged": True,
            }
            round_total_batches = 0
            i += 1
            continue

        batch_match = BATCH_HEADER_RE.match(line)
        if batch_match and current_round is not None:
            if current_batch:
                current_batch["end_line"] = i
                current_round["batches"].append(current_batch)
            round_total_batches += 1
            current_batch = {
                "lines": [line],
                "task_count": 0,
                "start_line": i,
                "end_line": None,
            }
            i += 1
            continue

        if current_batch is not None:
            # A `## ` header ends both the batch and the round
            if line.startswith("## "):
                current_batch["end_line"] = i
                current_round["batches"].append(current_batch)
                current_batch = None
                current_round["end_line"] = i
                current_round["all_merged"] = (
                    round_total_batches == len(current_round["batches"])
                )
                rounds.append(current_round)
                current_round = None
                # Don't advance i — let the outer loop re-process this line
                continue

            # A `### ` header that isn't a merged batch ends the current batch
            # (e.g., a pending batch header or OWASP section header)
            #
            # `H3_HEADER_RE`, not `startswith("### ")`: the literal trailing
            # space meant `###\tBatch 8` did not close the open batch, so it
            # never reached the `ANY_BATCH_HEADER_RE` counter below and
            # `round_total_batches` stayed short — `all_merged` then held True
            # for a round with an OPEN batch, and the round was archived.
            # Widening ANY_BATCH_HEADER_RE alone did NOT fix this: the counter
            # is unreachable while the batch is still open, which is why the
            # first fix measured clean on two whitespace shapes and lost data
            # on the third. Found by Phase 191's round on the fixed tree.
            if H3_HEADER_RE.match(line):
                current_batch["end_line"] = i
                current_round["batches"].append(current_batch)
                current_batch = None
                # Don't advance i — fall through to re-process this line
                # as a potential non-merged batch header
                continue

            # A `---` separator ends the batch but NOT the round
            # (batches within a round are separated by `---`)
            if line.strip() == "---":
                current_batch["end_line"] = i
                current_round["batches"].append(current_batch)
                current_batch = None
                i += 1
                continue

            current_batch["lines"].append(line)
            if TASK_RE.match(line):
                current_batch["task_count"] += 1
            i += 1
            continue

        # Outside a batch but inside a round
        if current_round is not None:
            # Close round on non-Round ## header (e.g., "## Statistics")
            if line.startswith("## "):
                current_round["end_line"] = i
                current_round["all_merged"] = (
                    round_total_batches == len(current_round["batches"])
                )
                rounds.append(current_round)
                current_round = None
                # Don't advance i — re-process this line
                continue

            # Count non-merged batch headers (pending, etc.) but don't collect
            if ANY_BATCH_HEADER_RE.match(line):
                round_total_batches += 1

            # Round-level metadata: blockquote lines between the `## Round`
            # header and the round's first batch (round_total_batches is still
            # 0 there). Today that is the Tier-0 coverage ledger. Captured so
            # build_archive_block() can re-emit it — the round's line range is
            # removed from review_tasks.md wholesale, so anything not collected
            # here is destroyed rather than relocated.
            elif round_total_batches == 0 and line.lstrip().startswith(">"):
                current_round["preamble"].append(line)

        i += 1

    # Close any trailing batch/round
    if current_batch and current_round:
        current_batch["end_line"] = len(lines)
        current_round["batches"].append(current_batch)
    if current_round:
        current_round["end_line"] = len(lines)
        current_round["all_merged"] = (
            round_total_batches == len(current_round["batches"])
        )
        rounds.append(current_round)

    # Filter to only rounds that have at least one archivable batch
    archivable = []
    for r in rounds:
        if r["batches"]:
            archivable.append(r)

    return archivable


def count_round_tasks(r):
    """(done, total) for one round, both derived from the same task lines.

    Recomputed from each batch's captured lines rather than threaded through as
    a new `task_count`-style dict key: a new required key would raise KeyError
    in every hand-built fixture that constructs a batch dict, and the callers
    that need these numbers are exactly the two builders below plus `main`.

    `task_count` is deliberately NOT reused here. It comes from TASK_RE, which
    requires `**TASK-N**` — fine for the per-batch progress line it feeds, wrong
    for a ratio, because it silently drops a task whose id is not bolded.

    **Fenced lines are masked out, and that is a fix, not a nicety (Phase 217).**
    `parse_archivable_batches` deliberately accumulates fenced content into
    whatever batch is open — it has to, or archiving would drop the example text
    — but it does NOT increment `task_count` for it. This function reads
    `b["lines"]` directly, so before this mask it counted the task lines inside a
    *correctly closed, correctly masked* documentation fence. Measured on a batch
    holding one real task plus a closed ```` ```markdown ```` block containing
    two illustration tasks: `task_count` said 1 and this said `(2, 3)`.

    The blast radius is why it is worth the extra scan: these numbers feed the
    per-batch breakdown, the `Archive N tasks?` prompt an operator answers, and
    `update_archive_total`, which writes the Grand Total row **durably into the
    archive file**. A wrong number there is not a display bug; it is a permanent
    record of work that was never done.

    Masking each batch's own lines is sound because a batch can only be opened
    OUTSIDE a fence — a `### Batch` header inside one is masked and opens
    nothing — so any fenced run inside `b["lines"]` also opened inside it.

    The UNTERMINATED case is not reachable here, but the first cut of this
    docstring got the reason wrong and said so confidently: it claimed the case
    "is refused outright before this is ever called (see
    `unterminated_batch_span`)". That function refuses only when a `### Batch`
    header is inside the fence. An unterminated fence holding only task lines was
    refused by nothing and masked by nothing, and its illustrations counted as
    completed work — the review round demonstrated `(2, 2)` where `(1, 1)` was
    correct. `unterminated_task_span` is what actually closes it; BOTH spans are
    checked before any parsing or accounting runs.
    """
    done = total = 0
    for b in r["batches"]:
        lines = b["lines"]
        fenced = _fenced_mask(lines)
        for i, line in enumerate(lines):
            if fenced[i]:
                continue
            if COUNTED_TASK_RE.match(line):
                total += 1
                if COMPLETED_TASK_RE.match(line):
                    done += 1
    return done, total


def build_archive_block(rounds):
    """Build the markdown block to insert into the archive file.

    Does NOT include a leading '---' — the caller handles separator context
    to avoid double separators.
    """
    blocks = []
    for idx, r in enumerate(rounds):
        done_tasks, total_tasks = count_round_tasks(r)

        if idx > 0:
            blocks.append("---")
            blocks.append("")
        blocks.append(r["header"])
        # Round-level metadata (the Tier-0 coverage ledger) rides with its
        # round into the archive, outside the <details> fold: how much of the
        # codebase a round actually opened is the first thing a later reader
        # needs in order to know what the findings below are worth.
        # Only when the whole round is leaving the live file. A partially
        # merged round keeps its header (and its coverage line) in
        # review_tasks.md — apply_removals() takes only the merged batch
        # ranges — so emitting it here too would duplicate the ledger now and
        # again when the round later archives in full.
        if r.get("preamble") and r.get("all_merged"):
            blocks.append("")
            blocks.extend(line.rstrip("\n") for line in r["preamble"])
        blocks.append("")
        blocks.append("<details>")
        # `done/total`, not `total/total`. The tautological form made the number
        # unfalsifiable: a round carrying a `> Failed:` task archived as
        # "3/3 tasks completed" while the block below it visibly held an open
        # box, because the open task was not miscounted — it was removed from
        # the denominator.
        blocks.append(f"<summary>{done_tasks}/{total_tasks} tasks completed</summary>")
        blocks.append("")

        for b in r["batches"]:
            # Append batch content verbatim, stripping trailing blank lines
            batch_lines = b["lines"]
            while batch_lines and batch_lines[-1].strip() == "":
                batch_lines = batch_lines[:-1]
            blocks.extend(batch_lines)
            blocks.append("")

        blocks.append("</details>")
        blocks.append("")

    return blocks


# Lines the emitter drops on purpose, so they are not evidence of loss (Q-116).
#
# Derived from the emitter, not guessed. `parse_archivable_batches` consumes the
# `---` separator without appending it (the `line.strip() == "---"` branch),
# `build_archive_block` strips each batch's trailing blank lines and re-emits
# `---` only BETWEEN rounds. Those are the two shapes that can legitimately go
# missing, so they are the two that are exempt.
#
# Measured on every real tracker on this machine with an archivable round —
# BeanRider (3 rounds, 591 deleted lines) and a second internal tracker
# (1 round, 202) —
# **residue 0 in both**. That is the number this exemption set has to earn: the
# archive path has no `--force`, so a single false positive makes it unusable.
#
# A pre-build lens reported 28 strict misses on the BeanRider corpus. Re-derived
# here that probe returns 0, because "strict" is ambiguous — a membership test
# counts a blank line as present the moment the block contains any blank, while
# a multiset check exhausts them. The disagreement is about the probe, not the
# tree, so no strict figure is asserted; only the residue measurement above,
# which reproduces.
_ACCOUNTING_EXEMPT = frozenset({"", "---"})


def unaccounted_lines(lines, rounds_to_remove, archive_block):
    """Content that `update_review_tasks` would DELETE and the archive never receives.

    `parse_archivable_batches` closes the current batch on a bare `---`, so any
    content between that separator and the next `### Batch` header belongs to no
    batch. For an `all_merged` round the whole line range is deleted while the
    emitted block carries only header + preamble + batches — so that content is
    removed from review_tasks.md and never written to the archive. Reproduced on
    a real run: a `- [ ] **TASK-9**` and its annotation vanished from both files.

    The round-level instance of this bug already has a targeted fix — the
    `preamble` capture (Phase 149), added after the same gap swallowed the Tier-0
    coverage ledger. This is the general form, and it is what would have caught
    both.

    Accounting is a **content multiset, not positional**: a line that happens to
    appear elsewhere in the block counts as accounted for. That is a deliberate
    loosening — the emitter reorders and re-indents nothing today, and a
    positional check would couple this to the block's layout.
    """
    emitted = Counter(ln.rstrip() for ln in archive_block)
    residue = []
    for r in rounds_to_remove:
        if r["all_merged"]:
            ranges = [(r["start_line"], r["end_line"])]
        else:
            ranges = [(b["start_line"], b["end_line"]) for b in r["batches"]]
        for start, end in ranges:
            for raw in lines[start:end]:
                line = raw.rstrip("\n").rstrip()
                if line.strip() in _ACCOUNTING_EXEMPT:
                    continue
                if emitted[line] > 0:
                    emitted[line] -= 1
                else:
                    residue.append(line)
    return residue


def build_grand_total_row(rounds):
    """Build a new row for the Grand Total table in the archive."""
    rows = []
    for r in rounds:
        done_tasks, total_tasks = count_round_tasks(r)
        batch_numbers = []
        for b in r["batches"]:
            # Extract batch number from first line
            m = re.search(r"Batch (\d+)", b["lines"][0])
            if m:
                batch_numbers.append(int(m.group(1)))

        # Extract round name from header
        round_match = re.match(r"## (Round \d+)", r["header"])
        round_name = round_match.group(1) if round_match else "Round ?"

        if batch_numbers:
            batch_range = f"Batches {min(batch_numbers)}-{max(batch_numbers)}"
            label = f"{round_name} ({batch_range})"
        else:
            label = round_name

        # Columns: | Round | Total | Completed | Deferred | Status |.
        # `Completed` was the literal `total_tasks` and `Status` the literal
        # `Complete`, so the row asserted completeness by construction — it could
        # not report anything else. Deferred stays 0: a `> Failed:` task is open,
        # not deferred, and mislabelling it would trade one wrong cell for
        # another. `Partial` is what carries the fact that Total > Completed.
        status = "Complete" if done_tasks == total_tasks else "Partial"
        rows.append(
            f"| {label} | {total_tasks} | {done_tasks} | 0 | {status} |"
        )
    return rows


def update_archive_total(archive_lines, new_task_count, new_completed_count=None):
    """Update the Archive Total row with new counts.

    `new_completed_count` defaults to `new_task_count` — the old behaviour, and
    still the right one for a fully-completed archive run. It is separate
    because the two columns are different quantities: adding a round that
    carried an open task must raise Total by more than Completed, and applying
    one delta to both was how the running total inherited the same tautology
    the per-round rows had.
    """
    if new_completed_count is None:
        new_completed_count = new_task_count
    for i, line in enumerate(archive_lines):
        if ARCHIVE_TOTAL_RE.match(line):
            # Parse existing totals
            parts = line.split("|")
            # parts: ['', ' **Archive Total** ', ' **651** ', ' **650** ', ' **1** ', ' ', '']
            # Guard against malformed rows (missing pipes, non-numeric cells)
            # to avoid AttributeError / IndexError that would crash the entire
            # archive flow on a single hand-edited typo.
            if len(parts) < 5:
                print(
                    f"WARN: Archive Total row has {len(parts)} pipe-delimited "
                    "cells; expected >=5. Skipping totals update.",
                    file=sys.stderr,
                )
                return None, None
            m_total = re.search(r"\d+", parts[2])
            m_completed = re.search(r"\d+", parts[3])
            m_deferred = re.search(r"\d+", parts[4])
            if not (m_total and m_completed and m_deferred):
                print(
                    "WARN: Archive Total row missing numeric cells; "
                    "skipping totals update.",
                    file=sys.stderr,
                )
                return None, None
            old_total = int(m_total.group())
            old_completed = int(m_completed.group())
            old_deferred = int(m_deferred.group())

            new_total = old_total + new_task_count
            new_completed = old_completed + new_completed_count

            archive_lines[i] = (
                f"| **Archive Total** | **{new_total}** | **{new_completed}** "
                f"| **{old_deferred}** | |"
            )
            return old_total, new_total
    return None, None


def find_archive_insertion_point(archive_lines):
    """Find the line index just before '## Grand Total (Archived)'."""
    for i, line in enumerate(archive_lines):
        if line.strip() == ARCHIVE_GRAND_TOTAL_HEADER:
            return i
    return None


def update_review_tasks(lines, rounds_to_remove, new_archived_total,
                        total_round_tasks, all_batch_numbers):
    """Update review_tasks.md after archival:
    - Remove archived round/batch content
    - Update archive reference line
    - Update Grand Total statistics
    """
    # Remove archived lines (process from end to preserve indices).
    # For fully-merged rounds, remove the entire round range.
    # For mixed rounds, remove only individual merged batch ranges.
    ranges_to_remove = []
    for r in rounds_to_remove:
        if r["all_merged"]:
            ranges_to_remove.append((r["start_line"], r["end_line"]))
        else:
            for b in r["batches"]:
                ranges_to_remove.append((b["start_line"], b["end_line"]))

    ranges_to_remove.sort(reverse=True)
    for start, end in ranges_to_remove:
        del lines[start:end]

    # Collapse any doubled "---" separators left by removal
    i = 0
    while i < len(lines) - 1:
        if lines[i].strip() == "---" and lines[i + 1].strip() == "":
            # Check if the next non-blank line is also "---"
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and lines[j].strip() == "---":
                # Remove the duplicate separator block
                del lines[i:j]
                continue
        i += 1

    # Update archive reference line
    # Only bump "Rounds 1-N" for fully-merged rounds — a partially-archived
    # round still has pending batches and should not advance the range.
    max_round = 0
    for r in rounds_to_remove:
        if r["all_merged"]:
            m = re.search(r"Round (\d+)", r["header"])
            if m:
                max_round = max(max_round, int(m.group(1)))
    # Also check existing archive ref for the current max round
    for line in lines:
        if ARCHIVE_REF_RE.match(line):
            existing = re.search(r"Rounds 1[–-](\d+)", line)
            if existing:
                max_round = max(max_round, int(existing.group(1)))
            break

    for i, line in enumerate(lines):
        if ARCHIVE_REF_RE.match(line):
            batch_max = max(all_batch_numbers, default=0)
            # Preserve the existing task count when the archive total was
            # unparseable (new_archived_total is None \u2014 a malformed/missing
            # Archive Total row caught by update_archive_total) rather than
            # writing a literal "(None tasks)" into the file. The rounds/batches
            # range still advances \u2014 those derive from the archived rounds, not
            # the malformed total row.
            if new_archived_total is not None:
                count_str = f"{new_archived_total} tasks"
            else:
                prior = re.search(r"\((\d[\d,]*) tasks\)", line)
                count_str = f"{prior.group(1)} tasks" if prior else "tasks"
            lines[i] = (
                f"> **Archive:** Rounds 1\u2013{max_round} "
                f"(Batches 1\u2013{batch_max}) "
                f"({count_str}) are in "
                f"[review_tasks_archive.md](review_tasks_archive.md)."
            )
            break

    # Update Grand Total line
    for i, line in enumerate(lines):
        total_match = GRAND_TOTAL_RE.match(line)
        if total_match:
            total_tasks = int(total_match.group(1))
            done = int(total_match.group(2))
            open_count = int(total_match.group(3))
            deferred = int(total_match.group(4))
            # Preserve deferred task references (e.g., "(TASK-184)")
            suffix_match = re.search(r"\(TASK-[\w, -]+\)", line)
            suffix = f" {suffix_match.group()}" if suffix_match else ""
            lines[i] = (
                f"> **Grand Total (all rounds):** {total_tasks} tasks "
                f"\u2014 {done} done, {open_count} open, "
                f"{deferred} deferred{suffix}."
            )
            break

    # Update "All completed work" reference line
    for i, line in enumerate(lines):
        if ALL_COMPLETED_RE.match(line):
            batch_max = max(all_batch_numbers, default=0)
            lines[i] = (
                f"> All completed work (Batches 1\u2013{batch_max}) "
                f"archived in [review_tasks_archive.md](review_tasks_archive.md)."
            )
            break

    return lines


def main():
    parser = argparse.ArgumentParser(
        description="Archive merged/complete review batches"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview changes without writing files"
    )
    args = parser.parse_args()

    # Read review_tasks.md
    try:
        with open(REVIEW_FILE, "r", encoding="utf-8", errors="replace") as f:
            review_lines = f.read().splitlines()
    except FileNotFoundError:
        print(f"Error: {REVIEW_FILE} not found")
        sys.exit(1)

    # Q-240: refuse before ANYTHING is parsed, counted, previewed or prompted.
    # The whole parse is untrustworthy in this state, so a refusal placed after
    # the accounting would print a wrong total first and then decline — which is
    # the shape of the defect, not a fix for it. Placed ahead of the `--dry-run`
    # branch too, deliberately: a dry run whose preview counts an illustration as
    # completed work is exactly the report an operator would act on.
    # BOTH spans. A batch header inside an unterminated fence becomes a whole
    # phantom batch; a task line inside one is counted as completed work. The
    # first cut checked only the former and its own docstring wrongly claimed
    # that covered the latter.
    fence_hit = unterminated_batch_span(review_lines)
    what = "a batch header"
    if not fence_hit:
        fence_hit = unterminated_task_span(review_lines)
        what = "a completed-task line"
    if fence_hit:
        f_line, marker, h_line, h_text = fence_hit
        print(
            f"Error: refusing to archive — {os.path.basename(REVIEW_FILE)} has an "
            f"unterminated {marker} fence opened at line {f_line}, with {what} "
            f"inside it at line {h_line}:",
            file=sys.stderr,
        )
        print(f"         {_sanitize_log(h_text)}", file=sys.stderr)
        print(
            "       An unterminated fence is deliberately ignored by the "
            "structural parser (honouring one would disable parsing to "
            "end-of-file), so its contents parse as REAL work — counted as "
            "completed, archived, deleted from the tracker, and written into the "
            "archive's Grand Total.",
            file=sys.stderr,
        )
        print(
            f"       Fix by closing the fence: add a line containing {marker} "
            f"after the example block. The file is malformed markdown until you "
            f"do, so this is the correct fix regardless of archiving.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Q-274: refuse on a near-miss batch header ────────────────
    #
    # Same placement rule as the fence refusal above, for the same reason:
    # before anything is parsed, counted, previewed or prompted, and ahead of
    # the `--dry-run` branch, because a preview whose totals silently omit a
    # merged batch is exactly the report an operator would act on.
    #
    # **The filed entry got the outcome wrong, and the correction is why this is
    # a refusal rather than a warning.** `Q-274` says `all_merged` goes False
    # and therefore "the round is never archived ... nothing is lost". Only the
    # first half reproduces. Measured at Phase 220 on the entry's own stated
    # fixture — one em-dash `Merged` batch, one ASCII-hyphen `Merged` batch:
    #
    #   * `all_merged` is False, correctly; but that flag gates the round's
    #     WHOLESALE line removal, not the per-batch archive, so the run
    #     proceeds (`rc=0`, "removed 1 archived tasks");
    #   * the em-dash batch relocates into the archive under its own
    #     `## Round 1` heading;
    #   * the Grand Total row records `Round 1 (Batches 1-1) | 1 | 1 | 0 |
    #     Complete` — the round stamped **Complete** over a batch range that
    #     excludes the live one;
    #   * the hyphen batch stays in review_tasks.md under a SECOND `## Round 1`
    #     header, so one round now exists in both files;
    #   * and nothing warns.
    #
    # Nothing is deleted, so the entry's "fail-safe on deletion" half stands.
    # What is lost is the accounting, and a round marked Complete in the archive
    # while merged work sits live is a state nobody re-opens. A warning would
    # have left every one of those effects in place, which is why the entry's
    # own minimum ask ("the archiver should at minimum warn") is necessary and
    # not sufficient.
    #
    # Whole-run rather than per-round: the near-miss makes the ROUND boundary
    # itself unreliable (`ANY_BATCH_HEADER_RE` closes the open batch, so a
    # near-miss silently truncates its predecessor), and there is no legal
    # tracker shape in which a header misses the canonical form on purpose —
    # `WORKFLOW.md`'s two batch-metadata templates document one spelling and both
    # operational writers emit it. That is the difference from `--check-duplicates`' scoped
    # refusal, where per-round renumbering IS legal.
    near = near_miss_batch_headers(review_lines)
    # **The gate is narrower than the report, and Phase 256's round is why.**
    # `Q-375` widened the near-miss POPULATION to `#{2,4}\s*Batch\s+\d+\b` so
    # that four shapes written at column 0 stop vanishing. Feeding that straight
    # into this refusal was wrong twice over:
    #
    #   1. The stated harm below — "invisible to the status test but VISIBLE to
    #      its batch counter, so archiving would relocate the batches around it"
    #      — is true only of a line `ANY_BATCH_HEADER_RE` matches. The four added
    #      shapes do NOT bound (the boundary twin was deliberately left alone),
    #      so they cannot truncate a predecessor and the sentence would have
    #      been false for four of the five populations it covered.
    #   2. It made an ordinary prose heading a hard whole-run blocker.
    #      `## Batch 1 retrospective` matches the widened population, and an
    #      operator note under that heading would have refused every archive
    #      run until someone renamed it. Measured by the round.
    #
    # So: refuse on the ones that actually bound, and WARN on the rest. That is
    # `Q-375`'s improvement — the four shapes stop being silent — without a new
    # false refusal, and it keeps this message true of everything it prints.
    blocking = [(ln, txt) for ln, txt in near if ANY_BATCH_HEADER_RE.match(txt)]
    advisory = [(ln, txt) for ln, txt in near if not ANY_BATCH_HEADER_RE.match(txt)]
    if advisory:
        print(
            f"WARNING: {os.path.basename(REVIEW_FILE)} has {len(advisory)} line(s) "
            f"that look like a batch header but bound nothing — no reader will "
            f"see the batch:",
            file=sys.stderr,
        )
        for lineno, text in advisory:
            print(f"         :{lineno} — {_sanitize_log(text)}", file=sys.stderr)
        print(
            "         Archiving is NOT blocked by these: they are invisible to "
            "the batch counter too, so they relocate nothing. Fix them if a "
            "batch was intended.",
            file=sys.stderr,
        )
    if blocking:
        near = blocking
        print(
            f"Error: refusing to archive — {os.path.basename(REVIEW_FILE)} has "
            f"{len(near)} batch header(s) this archiver cannot read:",
            file=sys.stderr,
        )
        for lineno, text in near:
            print(f"         :{lineno} — {_sanitize_log(text)}", file=sys.stderr)
        print(
            "       The canonical shape is: ### Batch <N> — <Title> `<Status>` "
            "— an em-dash (—, U+2014), not an ASCII hyphen, and a backticked "
            "status as the last token on the line.",
            file=sys.stderr,
        )
        print(
            "       Such a line is invisible to this archiver's status test but "
            "VISIBLE to its batch counter, so archiving would relocate the "
            "batches around it and stamp the round Complete in the archive's "
            "Grand Total while the header above still sits in the tracker.",
            file=sys.stderr,
        )
        print(
            "       Fix the header(s) above and re-run. Confirm with: "
            "python3 sysop/scripts/review_index.py --check-headers",
            file=sys.stderr,
        )
        sys.exit(1)

    # Parse archivable rounds
    rounds = parse_archivable_batches(review_lines)
    if not rounds:
        print("No merged/complete batches to archive.")
        sys.exit(0)

    # Summarize what we found
    total_tasks = 0
    completed_tasks = 0
    all_batch_numbers = []
    unfinished = []
    for r in rounds:
        round_done, round_total = count_round_tasks(r)
        completed_tasks += round_done
        total_tasks += round_total
        print(f"  {r['header'].lstrip('# ')}")
        for b in r["batches"]:
            batch_name = b["lines"][0].split("`")[0].strip("# ").strip()
            # Counted the SAME way as the total below it. This line used to read
            # `task_count` (TASK_RE, `[x]`-only) while the total moved to
            # count_round_tasks, so the per-batch breakdown summed to less than
            # the `Archive N tasks?` prompt directly beneath it — a batch whose
            # only task is open printed `0 tasks` and still counted 1. An
            # operator-facing count that has drifted from the thing it describes
            # is this phase's own subject, one layer up.
            b_done, b_total = count_round_tasks({"batches": [b]})
            suffix = f" ({b_total - b_done} open)" if b_total > b_done else ""
            print(f"    {batch_name}: {b_total} tasks{suffix}")
            m = re.search(r"Batch (\d+)", b["lines"][0])
            if m:
                all_batch_numbers.append(int(m.group(1)))
            for line in b["lines"]:
                tm = UNFINISHED_TASK_RE.match(line)
                if tm:
                    label = tm.group("bold") or tm.group("plain") or line
                    unfinished.append((batch_name, label.strip()[:60]))

    print(f"\nTotal: {total_tasks} tasks across {len(rounds)} round(s)")

    # Warn, never block. Blocking would jam archiving, which is the pressure
    # valve for the 125KB read limit, on work that is legitimately unfinished.
    # Printed to stdout, not stderr, so it cannot be separated from the
    # confirmation prompt it should inform.
    #
    # The task's TEXT survives — it moves to the archive with its annotation
    # intact — and so now do the COUNTS around it. This warning used to be the
    # only honest number in the flow: `task_count` (TASK_RE, `[x]` only)
    # excluded the open task, so `build_archive_block` rendered the round
    # "N/N tasks completed" and `build_grand_total_row` marked it `Complete`
    # over a block visibly containing an open box. Both now derive their
    # denominator from COUNTED_TASK_RE and report `done/total` + `Partial`.
    # The warning stays, and stays before the prompt: a correct number in a
    # document nobody re-reads is not the same as being told at the moment of
    # the decision that archiving moves live work out of the queue.
    if unfinished:
        # State only what is observable. An unflipped box in a merged batch is
        # USUALLY a FAIL verdict, but not necessarily, and naming a cause the
        # tool cannot verify would make this warning assert a fabricated
        # verdict. (The specific alternate cause this comment used to name —
        # `find_batch_range`'s `wc -l` fallback undercounting by one on a file
        # with no trailing newline, leaving the last task unflipped with no
        # verdict behind it — was fixed in close_batch.sh, which now derives
        # the line count with `awk END{print NR}`. The reasoning still holds
        # for causes nobody has found yet.)
        print(
            f"\n⚠️  {len(unfinished)} task(s) in these batches are still open. "
            "Archiving moves them out of the live queue:"
        )
        for batch_name, task_id in unfinished:
            print(f"      {batch_name}: {task_id}")
        print(
            "    Finish them (/claim-task) or re-file them into a later round "
            "first if they should stay visible."
        )
        print(
            "    Note: the archive will record them — its `N/M tasks completed` "
            "summary counts them in M, and its Statistics row reads `Partial`. "
            "It will not read as fully complete."
        )

    if args.dry_run:
        print("\n[DRY RUN] No files modified.")

        # Q-116: surface the accounting here too. The preview is the one place
        # where naming the loss costs nothing, and a dry run that reports a clean
        # archive which the real run then hard-refuses is the worst of both. It
        # WARNS rather than refusing — a preview writes nothing.
        would_lose = unaccounted_lines(review_lines, rounds, build_archive_block(rounds))
        if would_lose:
            print(
                f"\n⚠️  {len(would_lose)} line(s) would be deleted without reaching "
                f"the archive, so the real run will refuse:"
            )
            for line in would_lose[:10]:
                print(f"      {_sanitize_log(line)}")
            if len(would_lose) > 10:
                print(f"      … and {len(would_lose) - 10} more")

        # Show what the archive block would look like
        archive_block = build_archive_block(rounds)
        print("\n--- Archive block preview (first 20 lines) ---")
        for line in archive_block[:20]:
            print(f"  {line}")
        if len(archive_block) > 20:
            print(f"  ... ({len(archive_block) - 20} more lines)")

        print("\n--- Grand Total row(s) ---")
        for row in build_grand_total_row(rounds):
            print(f"  {row}")
        return

    # Q-116: refuse BEFORE the prompt. Placed here rather than beside the write
    # for one reason — asking the operator to confirm an archive that is then
    # refused trains them to answer `y` to a question that does not bind. The
    # emitted block is pure and cheap to build twice.
    orphaned = unaccounted_lines(review_lines, rounds, build_archive_block(rounds))
    if orphaned:
        print(
            f"Error: refusing to archive — {len(orphaned)} line(s) would be deleted "
            f"from {os.path.basename(REVIEW_FILE)} without appearing in "
            f"{os.path.basename(ARCHIVE_FILE)}.",
            file=sys.stderr,
        )
        print(
            "       Lines belonging to no batch are removed with the round's "
            "range and never emitted. A batch is closed by a `---` separator, by "
            "any `## ` heading, and by any `### ` heading — so content after any "
            "of those, but still inside the round, is orphaned.",
            file=sys.stderr,
        )
        for line in orphaned[:10]:
            print(f"         {_sanitize_log(line)}", file=sys.stderr)
        if len(orphaned) > 10:
            print(f"         … and {len(orphaned) - 10} more", file=sys.stderr)
        # The remedy is stated precisely because there is no --force here. An
        # earlier wording said "move it above the round's first batch header
        # where the preamble capture will carry it" — that capture is
        # blockquote-only (`line.lstrip().startswith(">")`), so following the
        # instruction literally with plain prose or an `### ` heading still
        # refused. A wrong remedy on a path with no escape hatch is a dead end.
        print(
            "       Fix by one of: move the lines INSIDE a batch (above the next "
            "separator or heading); or, if the content belongs to the round "
            "rather than a batch, make each line a blockquote (`> …`) and place "
            "it between the `## Round` header and its first `### Batch` — the "
            "round-preamble capture takes blockquote lines only.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Confirmation prompt — wrap input() so Ctrl-C / EOF produce a clean exit
    # instead of a traceback that looks like a script bug.
    try:
        response = input(f"\nArchive {total_tasks} tasks? [y/N] ")
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        sys.exit(0)
    if response.lower() not in ("y", "yes"):
        print("Aborted.")
        sys.exit(0)

    # Read archive file (only need it now, after confirmation)
    try:
        with open(ARCHIVE_FILE, "r", encoding="utf-8", errors="replace") as f:
            archive_lines = f.read().splitlines()
    except FileNotFoundError:
        print(f"Error: {ARCHIVE_FILE} not found")
        sys.exit(1)

    # Find insertion point in archive
    insertion_idx = find_archive_insertion_point(archive_lines)
    if insertion_idx is None:
        print(f"Error: Could not find '{ARCHIVE_GRAND_TOTAL_HEADER}' in {ARCHIVE_FILE}")
        sys.exit(1)

    # Build the archive block
    archive_block = build_archive_block(rounds)

    # Build new grand total row(s)
    new_rows = build_grand_total_row(rounds)

    # Insert archive block above Grand Total header.
    # Typical structure before insertion:
    #   </details>       (end of previous round)
    #                    (blank)
    #   ---              (separator)
    #                    (blank)
    #   ## Grand Total   <-- insertion_idx
    #
    # We replace the "---\n\n" before Grand Total with our content + separator.
    sep_start = insertion_idx
    if insertion_idx >= 1 and archive_lines[insertion_idx - 1].strip() == "":
        sep_start = insertion_idx - 1
    if sep_start >= 1 and archive_lines[sep_start - 1].strip() == "---":
        sep_start = sep_start - 1

    archive_lines[sep_start:insertion_idx] = (
        ["---", ""] + archive_block + ["---", ""]
    )

    # Find and update the Archive Total row (shifted by insertion)
    old_total, new_total = update_archive_total(
        archive_lines, total_tasks, completed_tasks
    )
    if old_total is None:
        print("Warning: Could not find Archive Total row to update")

    # Insert new grand total row(s) just above the Archive Total row
    for i, line in enumerate(archive_lines):
        if ARCHIVE_TOTAL_RE.match(line):
            for j, row in enumerate(new_rows):
                archive_lines.insert(i + j, row)
            break

    # Also collect existing batch numbers from archive reference for the update
    existing_batch_numbers = []
    for line in archive_lines:
        for m in re.finditer(r"Batch (\d+)", line):
            existing_batch_numbers.append(int(m.group(1)))
    combined_batch_numbers = sorted(set(all_batch_numbers + existing_batch_numbers))

    # Build the new review_tasks.md content BEFORE either write so both atomic
    # rewrites happen back-to-back. _atomic_write_pair writes both tmp files
    # first, then issues the two os.replace calls in sequence — shrinking the
    # crash window between the archive and review writes from
    # "write + fsync + replace + write + fsync + replace" down to just
    # "replace + replace". A crash mid-flow would otherwise leave task state
    # split (the archive has the new rows AND review still has the un-archived
    # ones). See CLAUDE.md § Data integrity.
    review_lines = update_review_tasks(
        review_lines, rounds, new_total, total_tasks, combined_batch_numbers
    )
    _atomic_write_pair(
        ARCHIVE_FILE, "\n".join(archive_lines) + "\n",
        REVIEW_FILE, "\n".join(review_lines) + "\n",
    )
    # Guard the (None, None) sentinel from update_archive_total — when the
    # Archive Total row is missing or malformed the f-string would otherwise
    # emit literal "None -> None tasks".
    if old_total is not None and new_total is not None:
        print(f"Updated {ARCHIVE_FILE} ({old_total} -> {new_total} tasks)")
    else:
        print(f"Updated {ARCHIVE_FILE} (Archive Total row not updated)")
    print(f"Updated {REVIEW_FILE} (removed {total_tasks} archived tasks)")

    # Rebuild shadow JSON index after Markdown mutation. Best-effort and
    # non-fatal *by design* — it runs AFTER the durable atomic writes above,
    # and the shadow index auto-rebuilds on the next read, so no failure here
    # may crash a run whose file writes already succeeded. The broad catch is
    # deliberate: `review_index` resolves the markdown via a git-root walk-up
    # while this script resolves it via parents[2] (parent of sysop/), so an environmental
    # mismatch can raise a non-ImportError (e.g. FileNotFoundError) that must
    # still degrade to a printed note, not a traceback. A persistent failure
    # is visible in the note (not silent) and investigable.
    try:
        from review_index import rebuild_index
        rebuild_index()
        print("Rebuilt review_index.json")
    except Exception as e:
        print(
            f"Non-fatal: index rebuild failed "
            f"({_sanitize_log(e, max_len=200)!r}) — will auto-rebuild on next read"
        )

    print("\nDone! Review the changes with: git diff")


if __name__ == "__main__":
    main()
