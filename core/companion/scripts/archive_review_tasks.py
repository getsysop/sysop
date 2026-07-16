"""
Automate archival of completed review batches from review_tasks.md
to review_tasks_archive.md.

Usage:
    python scripts/archive_review_tasks.py              # Archive all merged batches
    python scripts/archive_review_tasks.py --dry-run    # Preview without writing
"""

import argparse
import os
import re
import sys
from pathlib import Path

# Single-sourced via scripts/_log.py (Phase 68) — `scripts/` is on sys.path[0]
# when this runs directly and on pythonpath under the test suite.
from _log import _sanitize_log  # noqa: E402


# Resolve against the repo root (the parent of scripts/), not CWD. A bare
# relative path opens against the caller's CWD, which from a worktree
# subdirectory or a caller that doesn't `cd` first either FileNotFoundErrors
# or — worse — opens an unrelated file with the same name. review_index.py
# solves the same CWD-independence goal with a git-root walk-up; this script
# is always installed at <repo-root>/scripts/, so parent-of-scripts is exact.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
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
    ``python scripts/archive_review_tasks.py``. The helper documents
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

# Matches any batch header regardless of status (used to count total batches)
ANY_BATCH_HEADER_RE = re.compile(r"^### (Batch \d+) — .+ `(\w[\w ]*)`")

# Matches task lines "- [x] **TASK-653**: ..."
TASK_RE = re.compile(r"^- \[x\] \*\*TASK-\d+\*\*")

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

    while i < len(lines):
        line = lines[i]

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
            if line.startswith("### "):
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


def build_archive_block(rounds):
    """Build the markdown block to insert into the archive file.

    Does NOT include a leading '---' — the caller handles separator context
    to avoid double separators.
    """
    blocks = []
    for idx, r in enumerate(rounds):
        total_tasks = sum(b["task_count"] for b in r["batches"])

        if idx > 0:
            blocks.append("---")
            blocks.append("")
        blocks.append(r["header"])
        blocks.append("")
        blocks.append("<details>")
        blocks.append(f"<summary>{total_tasks}/{total_tasks} tasks completed</summary>")
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


def build_grand_total_row(rounds):
    """Build a new row for the Grand Total table in the archive."""
    rows = []
    for r in rounds:
        total_tasks = sum(b["task_count"] for b in r["batches"])
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

        rows.append(
            f"| {label} | {total_tasks} | {total_tasks} | 0 | Complete |"
        )
    return rows


def update_archive_total(archive_lines, new_task_count):
    """Update the Archive Total row with new counts."""
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
            new_completed = old_completed + new_task_count

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

    # Parse archivable rounds
    rounds = parse_archivable_batches(review_lines)
    if not rounds:
        print("No merged/complete batches to archive.")
        sys.exit(0)

    # Summarize what we found
    total_tasks = 0
    all_batch_numbers = []
    for r in rounds:
        round_tasks = sum(b["task_count"] for b in r["batches"])
        total_tasks += round_tasks
        print(f"  {r['header'].lstrip('# ')}")
        for b in r["batches"]:
            batch_name = b["lines"][0].split("`")[0].strip("# ").strip()
            print(f"    {batch_name}: {b['task_count']} tasks")
            m = re.search(r"Batch (\d+)", b["lines"][0])
            if m:
                all_batch_numbers.append(int(m.group(1)))

    print(f"\nTotal: {total_tasks} tasks across {len(rounds)} round(s)")

    if args.dry_run:
        print("\n[DRY RUN] No files modified.")

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
    old_total, new_total = update_archive_total(archive_lines, total_tasks)
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
    # while this script resolves it via parent-of-scripts, so an environmental
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
