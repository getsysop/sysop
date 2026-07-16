#!/usr/bin/env python3
"""backfill_completed_dates.py — fill completed_date on already-done tasks.

When a project migrates from a single-file `[x]`-style checklist (e.g.,
`product_roadmap.md`) to the hybrid `tasks/index.yml` system, tasks already
flipped to done lose their completion timestamps — the migration knows the
task is done but not when it became done. This script reconstructs the
date by grepping git history for the commit that introduced the `[x]`
marker against the task ID.

This is a one-time migration helper. After the source file is deleted and
`tasks/index.yml` becomes the source of truth, `/review-close` writes
`completed_date` directly on every close — no backfill needed.

Usage:
    # Preview only — no writes:
    python3 scripts/backfill_completed_dates.py --dry-run

    # Write inferred dates back to tasks/index.yml:
    python3 scripts/backfill_completed_dates.py

    # Custom source file (default: product_roadmap.md):
    python3 scripts/backfill_completed_dates.py --source-file ROADMAP.md

    # Custom task-ID pattern (default: project's task-prefix family,
    # extracted from index.yml so the regex matches your IDs):
    python3 scripts/backfill_completed_dates.py --id-pattern '^(FEAT|TECH|FIX)-'

Strategy:
- For each task with status=done AND no completed_date, run `git log -S`
  scoped to --source-file, searching for a string containing the task ID
  plus the `[x]` marker. The earliest commit that added the line is taken
  as the completion date.
- Two patterns are tried in order: `[x] **<TASK-ID>` (bold-form), then
  `` `<TASK-ID>` `` (backtick-form, common in `<details>` blocks).
- If git history can't find a match (rebased, predates the file, or the
  task ID never appeared inline with `[x]`), `completed_date` is left
  null and the task ID is flagged in the report.

Caveat — `git log -S <needle> -- <file>` pickaxe matches the first commit
whose diff of *that file* alters the count of the search needle (it does
not search commit messages — that would be `--grep`). The backtick-form
needle `` `<TASK-ID>` `` also appears in the source file's own
cross-references (sibling-task references, `<details>`-block mentions,
follow-up notes) that can predate the `[x]` flip, so the `--reverse` +
first-match-wins posture below can attribute the earliest *mention* of
the task rather than the earliest commit that flipped its checkbox to
`[x]`. This is acceptable for a one-time migration — the operator reviews
the report and can hand-correct outliers. If the rate of false-positives
turns out to be high, switch to the bold-form-only pattern (drop the
backtick candidate) and rerun.

Exits 0 on success even if some tasks couldn't be resolved — surfacing
remaining nulls is the operator's call. Exits 1 only on hard failures
(unreadable index, git unavailable).

Path-in-message convention: error messages reference the index file by
basename (`Path(p).name`), not the absolute path. The path is operator-
controlled (no PII) but absolute paths clutter terminals and leak the
operator's home-directory layout into shared paste-backs.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

# Single-sourced via scripts/_log.py (Phase 68) — `scripts/` is on sys.path[0]
# when this runs directly and on pythonpath under the test suite. The name is
# bound into this module's namespace, so `backfill_completed_dates._sanitize_log`
# (the test patch path) keeps resolving.
from _log import _sanitize_log  # noqa: E402


def _default_index() -> Path:
    return Path.cwd() / "tasks" / "index.yml"


def find_completion_date(task_id: str, source_path: str) -> str | None:
    """Use `git log -S` against *source_path* to find the earliest commit
    that introduced an `[x]` marker for *task_id*.

    Returns ISO YYYY-MM-DD or None if no match found.
    """
    search_strings = (
        f"[x] **{task_id}",   # bold-form: `- [x] **TASK-ID** ...`
        f"`{task_id}`",        # backtick-form: `[x] \`TASK-ID\` ...`
    )
    for needle in search_strings:
        try:
            result = subprocess.run(
                [
                    "git",
                    "log",
                    "--all",
                    "--reverse",
                    "--format=%H %ad",
                    "--date=short",
                    "-S",
                    needle,
                    "--",
                    source_path,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except (subprocess.SubprocessError, OSError) as e:
            print(
                f"WARN: git log failed for {task_id} ({needle!r}): "
                f"{_sanitize_log(e)}",
                file=sys.stderr,
            )
            continue
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        if lines:
            return lines[0].split()[1]
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill completed_date via git history for done tasks "
        "whose dates weren't preserved during migration from a "
        "checklist-style roadmap to tasks/index.yml."
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=None,
        help="Path to tasks/index.yml (default: <cwd>/tasks/index.yml).",
    )
    parser.add_argument(
        "--source-file",
        default="product_roadmap.md",
        help="Path (relative to the git repo) to the legacy roadmap file "
        "that held the `[x]` markers in git history. May already be "
        "deleted on disk — we go through git log. Default: "
        "product_roadmap.md.",
    )
    parser.add_argument(
        "--id-pattern",
        default=None,
        help="Optional regex; only tasks whose id matches this pattern "
        "are considered. Useful when your project uses a different ID "
        "family than the validator's default `^[A-Z][A-Z0-9-]{2,80}$`. "
        "Example: --id-pattern '^(FEAT|TECH|FIX)-'.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print proposed changes without writing.",
    )
    args = parser.parse_args(argv)

    index_path = args.index if args.index else _default_index()
    if not index_path.is_file():
        print(f"ERROR: index not found: {index_path.name}", file=sys.stderr)
        return 1

    try:
        with open(index_path, encoding="utf-8", errors="replace") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        print(f"ERROR: cannot read {index_path.name}: {_sanitize_log(e)}", file=sys.stderr)
        return 1

    # Parameterized by the --id-pattern CLI arg — cannot hoist to module scope.
    id_pattern = re.compile(args.id_pattern) if args.id_pattern else None  # nosemgrep: recompile-inside-def
    tasks = data.get("tasks") or []

    needs_backfill: list[tuple[int, dict]] = []
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            continue
        if t.get("status") != "done":
            continue
        if t.get("completed_date"):
            continue
        tid = t.get("id")
        if not isinstance(tid, str):
            continue
        if id_pattern and not id_pattern.search(tid):
            continue
        needs_backfill.append((i, t))

    print(f"Found {len(needs_backfill)} done task(s) without completed_date.")
    if not needs_backfill:
        return 0

    updated = 0
    skipped = 0
    for i, task in needs_backfill:
        tid = task["id"]
        date = find_completion_date(tid, args.source_file)
        if date:
            print(f"  {tid}: {date}")
            data["tasks"][i]["completed_date"] = date
            updated += 1
        else:
            print(f"  {tid}: no match in git history for {args.source_file} (leaving null)")
            skipped += 1

    print(f"\nUpdated: {updated}. Skipped (no match): {skipped}.")

    if args.dry_run:
        print("--dry-run: not writing.")
        return 0

    # Atomic rewrite via `<path>.tmp` + `os.replace` so a crash mid-write
    # cannot leave truncated YAML — `tasks/index.yml` is load-bearing for
    # `/next-task`, `/claim-task`, `/review-close`. See CLAUDE.md
    # § Data integrity and the sibling `_atomic_write_text` in
    # archive_review_tasks.py. Belt-and-braces durability: `os.fsync` on the
    # file fd flushes the data; an `os.fsync` on the parent dir fd flushes the
    # rename itself so the post-crash directory entry points at the new inode
    # rather than the old one. One-time migration script (rerunnable on miss),
    # so the cost of getting this wrong is low — but the pattern is the
    # documented atomic-rewrite shape.
    tmp_path = index_path.with_suffix(index_path.suffix + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8", errors="replace") as f:
            yaml.safe_dump(
                data,
                f,
                sort_keys=False,
                default_flow_style=False,
                allow_unicode=True,
                width=120,
            )
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, index_path)
        dir_fd = os.open(str(index_path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as e:
        # Best-effort cleanup of the tmp file if it survived.
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        print(f"ERROR: cannot write {index_path.name}: {_sanitize_log(e)}", file=sys.stderr)
        return 1
    print(f"Wrote {index_path.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
