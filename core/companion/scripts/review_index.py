"""
Shadow JSON index for review_tasks.md.

Parses the Markdown into structured JSON for reliable machine consumption.
The Markdown remains the human-readable source of truth; scripts read from
the JSON index for reliable parsing and write mutations back to the Markdown,
then rebuild the index.

Usage:
    python scripts/review_index.py                 # Rebuild index (or verify fresh)
    python scripts/review_index.py --rebuild       # Force rebuild
    python scripts/review_index.py --check         # Exit 0 if fresh, 1 if stale
    python scripts/review_index.py --list          # Tab-separated batch list
    python scripts/review_index.py --batch 293     # Single batch details
    python scripts/review_index.py --range 293     # Line range for sed operations
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone


# ── Paths ────────────────────────────────────────────────────────

def _repo_root():
    """Walk up from this script to find the git working-tree root.

    Inside a git worktree, ``.git`` is a *file* containing
    ``gitdir: <path>`` rather than a directory — so ``os.path.isdir`` would
    walk past the worktree root and fall through to the script's own
    directory, breaking ``TASKS_FILE`` resolution. ``os.path.exists``
    accepts both shapes.
    """
    d = os.path.dirname(os.path.abspath(__file__))
    while d != os.path.dirname(d):
        if os.path.exists(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.abspath(__file__))


REPO_ROOT = _repo_root()
TASKS_FILE = os.path.join(REPO_ROOT, "review_tasks.md")
INDEX_FILE = os.path.join(REPO_ROOT, ".claude", "review_index.json")


# ── Regex patterns ───────────────────────────────────────────────
# Mirrors the patterns used by batch_work.sh, close_batch.sh, and
# archive_review_tasks.py, but consolidated in one place.

_ROUND_HEADER_RE = re.compile(r"^## (Round \d+.*)$")
_BATCH_HEADER_RE = re.compile(
    r"^### Batch (\d+) \u2014 (.+?) `([A-Za-z ]+)`$"
)
_META_BRANCH_RE = re.compile(r"^> \*\*Branch:\*\* `([^`]+)`")
_META_SCOPE_RE = re.compile(r"^> \*\*Scope:\*\* (.+)")
_META_VERIFY_RE = re.compile(r"^> \*\*Verify:\*\* (.+)")
_META_OVERLAP_RE = re.compile(r"^> \*\*Overlap:\*\* (.+)")
_META_FLAG_RE = re.compile(r"^> \*\*Flag:\*\* (.+)")
_META_OWASP_RE = re.compile(r"^> \*\*OWASP:\*\* (.+)")
# Severity emoji escapes: \U0001f534 = \ud83d\udd34 (high), \U0001f7e1 = \ud83d\udfe1 (medium),
# \U0001f7e2 = \ud83d\udfe2 (low). Matches _SEVERITY_MAP below; keep these in sync.
# Inline comments are not allowed inside a raw-string regex without re.VERBOSE,
# so the marker lives here so grep for "\ud83d\udd34"/"\ud83d\udfe1"/"\ud83d\udfe2" reaches both sites.
_TASK_RE = re.compile(
    r"^- \[( |/|x)\] \*\*(TASK-\d+)\*\*: (.+?)(?:\s+(\U0001f534|\U0001f7e1|\U0001f7e2))?$"
)
_DEFERRED_TASK_RE = re.compile(
    r"^- \[ \] \*\*(TASK-\d+)\*\*: (.+?)(?:\s+(\U0001f534|\U0001f7e1|\U0001f7e2))?"
    r"(?: \u2014 .+)?$"
)
_GRAND_TOTAL_RE = re.compile(
    r"\*\*Grand Total \(all rounds\):\*\* (\d+) tasks"
    r" \u2014 (\d+) done, (\d+) open, (\d+) deferred"
)

_SEVERITY_MAP = {
    "\U0001f534": "high",    # 🔴
    "\U0001f7e1": "medium",  # 🟡
    "\U0001f7e2": "low",     # 🟢
}

_CHECKBOX_MAP = {
    " ": "open",
    "/": "in_progress",
    "x": "done",
}


# ── Checksum ─────────────────────────────────────────────────────

def _file_sha256(path):
    """Compute SHA-256 hex digest of a file.

    Caller contract: the file must exist and be readable. Both callers
    (``parse_review_tasks`` and ``is_stale``) are invoked only after the
    upstream entry points (e.g. ``archive_review_tasks.main``,
    ``rebuild_index`` wrappers) have already opened ``review_tasks.md``
    inside a ``try/except FileNotFoundError``. Raising ``OSError`` from
    here is intentional — a file that disappeared mid-rebuild is a
    surprise the caller should see, not silently mask.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Parser ───────────────────────────────────────────────────────

def parse_review_tasks(path=None):
    """Parse review_tasks.md into a structured dict.

    Returns:
        dict with keys: generated_at, source_sha256, batches, deferred,
        rounds, grand_total, summary
    """
    path = path or TASKS_FILE
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    source_sha = _file_sha256(path)

    batches = {}
    deferred = []
    rounds = []
    grand_total = None

    current_round = None
    current_batch = None
    in_deferred_section = False

    for i, raw_line in enumerate(lines):
        line = raw_line.rstrip("\n")
        line_num = i + 1  # 1-indexed for sed/grep compatibility

        # ── Round header ──
        m = _ROUND_HEADER_RE.match(line)
        if m:
            # Close previous batch
            if current_batch is not None:
                current_batch["line_end"] = line_num - 1
                _finalize_batch(current_batch)
                batches[str(current_batch["number"])] = current_batch
                current_batch = None

            current_round = m.group(1)
            rounds.append(current_round)
            in_deferred_section = False
            continue

        # ── Deferred section ──
        if line.strip() == "## Deferred":
            in_deferred_section = True
            continue

        if in_deferred_section:
            dm = _DEFERRED_TASK_RE.match(line)
            if dm:
                deferred.append({
                    "id": dm.group(1),
                    "description": dm.group(2).strip(),
                    "severity": _SEVERITY_MAP.get(dm.group(3), "unknown"),
                    "line": line_num,
                })
            # Other section headers end the deferred block
            if line.startswith("## ") and line.strip() != "## Deferred":
                in_deferred_section = False
            continue

        # ── Batch header ──
        bm = _BATCH_HEADER_RE.match(line)
        if bm:
            # Close previous batch
            if current_batch is not None:
                current_batch["line_end"] = line_num - 1
                _finalize_batch(current_batch)
                batches[str(current_batch["number"])] = current_batch

            current_batch = {
                "number": int(bm.group(1)),
                "title": bm.group(2).strip(),
                "status": bm.group(3).strip(),
                "branch": "",
                "scope": "",
                "verify": "",
                "overlap": "",
                "flag": "",
                "owasp": "",
                "round": current_round or "",
                "line_start": line_num,
                "line_end": None,
                "tasks": [],
            }
            continue

        # ── Batch metadata (blockquote lines) ──
        if current_batch is not None:
            mm = _META_BRANCH_RE.match(line)
            if mm:
                current_batch["branch"] = mm.group(1)
                continue
            mm = _META_SCOPE_RE.match(line)
            if mm:
                current_batch["scope"] = mm.group(1)
                continue
            mm = _META_VERIFY_RE.match(line)
            if mm:
                current_batch["verify"] = mm.group(1)
                continue
            mm = _META_OVERLAP_RE.match(line)
            if mm:
                current_batch["overlap"] = mm.group(1)
                continue
            mm = _META_FLAG_RE.match(line)
            if mm:
                current_batch["flag"] = mm.group(1)
                continue
            mm = _META_OWASP_RE.match(line)
            if mm:
                current_batch["owasp"] = mm.group(1)
                continue

            # ── Task line ──
            tm = _TASK_RE.match(line)
            if tm:
                current_batch["tasks"].append({
                    "id": tm.group(2),
                    "description": tm.group(3).strip(),
                    "severity": _SEVERITY_MAP.get(tm.group(4), "unknown"),
                    "checkbox": _CHECKBOX_MAP.get(tm.group(1), "open"),
                    "line": line_num,
                })
                continue

        # ── Statistics section — detect end of batches ──
        if line.startswith("## Statistics"):
            if current_batch is not None:
                current_batch["line_end"] = line_num - 1
                _finalize_batch(current_batch)
                batches[str(current_batch["number"])] = current_batch
                current_batch = None

        # ── Grand Total ──
        gm = _GRAND_TOTAL_RE.search(line)
        if gm:
            grand_total = {
                "total": int(gm.group(1)),
                "done": int(gm.group(2)),
                "open": int(gm.group(3)),
                "deferred": int(gm.group(4)),
            }

    # Close trailing batch (if file ends without ## Statistics)
    if current_batch is not None:
        current_batch["line_end"] = len(lines)
        _finalize_batch(current_batch)
        batches[str(current_batch["number"])] = current_batch

    # ── Build summary ──
    summary = _build_summary(batches)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": source_sha,
        "batches": batches,
        "deferred": deferred,
        "rounds": rounds,
        "grand_total": grand_total,
        "summary": summary,
    }


def _finalize_batch(batch):
    """Compute counts for a parsed batch."""
    tasks = batch["tasks"]
    batch["counts"] = {
        "total": len(tasks),
        "open": sum(1 for t in tasks if t["checkbox"] == "open"),
        "in_progress": sum(1 for t in tasks if t["checkbox"] == "in_progress"),
        "done": sum(1 for t in tasks if t["checkbox"] == "done"),
        "high": sum(1 for t in tasks if t["severity"] == "high"),
        "medium": sum(1 for t in tasks if t["severity"] == "medium"),
        "low": sum(1 for t in tasks if t["severity"] == "low"),
    }


def _build_summary(batches):
    """Aggregate batch data into a summary."""
    by_status = {}
    total_tasks = 0
    open_tasks = 0
    done_tasks = 0
    in_progress_tasks = 0

    for b in batches.values():
        status = b["status"]
        by_status[status] = by_status.get(status, 0) + 1
        c = b["counts"]
        total_tasks += c["total"]
        open_tasks += c["open"]
        done_tasks += c["done"]
        in_progress_tasks += c["in_progress"]

    return {
        "total_batches": len(batches),
        "by_status": by_status,
        "total_tasks": total_tasks,
        "open_tasks": open_tasks,
        "in_progress_tasks": in_progress_tasks,
        "done_tasks": done_tasks,
    }


# ── Index I/O ────────────────────────────────────────────────────

def write_index(data, path=None):
    """Write the parsed data to the JSON index file.

    Atomic rewrite via `<path>.tmp` + `os.replace` so a crash mid-write
    cannot leave truncated JSON that `read_index` would then raise on.
    See CLAUDE.md § Data integrity.
    """
    path = path or INDEX_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    # ``errors=`` applies to decoding, not encoding; dropping the param
    # rather than switching to ``"strict"`` mirrors the standard-library
    # default for write-mode handles.
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def read_index(path=None):
    """Read the JSON index file. Returns None if it doesn't exist."""
    path = path or INDEX_FILE
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return json.load(f)


def is_stale(tasks_path=None, index_path=None):
    """Check if the index is stale (source has changed since last build).

    Returns True if stale or index doesn't exist.
    """
    tasks_path = tasks_path or TASKS_FILE
    index_path = index_path or INDEX_FILE

    index = read_index(index_path)
    if index is None:
        return True

    current_sha = _file_sha256(tasks_path)
    return index.get("source_sha256") != current_sha


def ensure_fresh(tasks_path=None, index_path=None):
    """Rebuild the index if stale, then return the index data."""
    tasks_path = tasks_path or TASKS_FILE
    index_path = index_path or INDEX_FILE

    if is_stale(tasks_path, index_path):
        data = parse_review_tasks(tasks_path)
        write_index(data, index_path)
        return data

    return read_index(index_path)


def rebuild_index(tasks_path=None, index_path=None):
    """Force rebuild the index regardless of staleness."""
    tasks_path = tasks_path or TASKS_FILE
    index_path = index_path or INDEX_FILE

    data = parse_review_tasks(tasks_path)
    write_index(data, index_path)
    return data


# ── Query helpers (for CLI and bash script consumption) ──────────

def list_batches(data):
    """Return tab-separated batch lines matching batch_work.sh format.

    Format: NUMBER<tab>TITLE<tab>STATUS<tab>BRANCH<tab>SCOPE<tab>VERIFY
    """
    lines = []
    for num in sorted(data["batches"].keys(), key=int):
        b = data["batches"][num]
        lines.append(
            f"{b['number']}\t{b['title']}\t{b['status']}\t"
            f"{b['branch']}\t{b['scope']}\t{b['verify']}"
        )
    return lines


def get_batch(data, batch_num):
    """Return a single batch dict, or None."""
    return data["batches"].get(str(batch_num))


def get_batch_range(data, batch_num):
    """Return (line_start, line_end, status, branch) for a batch.

    line_start and line_end are 1-indexed, matching grep -n / sed output.
    Returns None if batch not found.
    """
    b = get_batch(data, batch_num)
    if b is None:
        return None
    return (b["line_start"], b["line_end"], b["status"], b["branch"])


# ── CLI ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Shadow JSON index for review_tasks.md"
    )
    parser.add_argument(
        "--rebuild", action="store_true",
        help="Force rebuild the index"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Check if index is fresh (exit 0) or stale (exit 1)"
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List all batches (tab-separated, batch_work.sh format)"
    )
    parser.add_argument(
        "--batch", type=int, metavar="N",
        help="Show details for batch N"
    )
    parser.add_argument(
        "--range", type=int, metavar="N",
        help="Show line range for batch N (for sed operations)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output in JSON format (for --batch)"
    )

    args = parser.parse_args()

    if not os.path.isfile(TASKS_FILE):
        print(f"ERROR: {TASKS_FILE} not found", file=sys.stderr)
        sys.exit(1)

    # --check: just report staleness
    if args.check:
        if is_stale():
            print("stale")
            sys.exit(1)
        else:
            print("fresh")
            sys.exit(0)

    # --rebuild: force rebuild
    if args.rebuild:
        data = rebuild_index()
        n = len(data["batches"])
        print(f"Rebuilt index: {n} batches, {data['summary']['total_tasks']} tasks")
        sys.exit(0)

    # All query modes auto-ensure freshness
    data = ensure_fresh()

    # --list
    if args.list:
        for line in list_batches(data):
            print(line)
        sys.exit(0)

    # --batch N
    if args.batch is not None:
        b = get_batch(data, args.batch)
        if b is None:
            print(f"Batch {args.batch} not found", file=sys.stderr)
            sys.exit(1)
        if args.json:
            print(json.dumps(b, indent=2, ensure_ascii=False))
        else:
            print(
                f"{b['number']}\t{b['title']}\t{b['status']}\t"
                f"{b['branch']}\t{b['scope']}\t{b['verify']}\t"
                f"{b['line_start']}\t{b['line_end']}"
            )
        sys.exit(0)

    # --range N
    if args.range is not None:
        r = get_batch_range(data, args.range)
        if r is None:
            print(f"Batch {args.range} not found", file=sys.stderr)
            sys.exit(1)
        start, end, status, branch = r
        print(f"{start}\t{end}\t{status}\t{branch}")
        sys.exit(0)

    # Default: ensure index is fresh, report status
    data = rebuild_index()
    n = len(data["batches"])
    pending = data["summary"]["by_status"].get("Pending", 0)
    in_prog = data["summary"]["by_status"].get("In Progress", 0)
    print(
        f"Index fresh: {n} batches "
        f"({pending} pending, {in_prog} in progress, "
        f"{data['summary']['total_tasks']} tasks)"
    )


if __name__ == "__main__":
    main()
