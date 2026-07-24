"""
sitrep_survey.py — Read-only situation report for Sysop.

Surveys locks, worktrees, branches, tasks/index.yml, and review_tasks.md;
classifies every active task into a deterministic lifecycle state via the
`Doc-Work:` git trailer (Phase 40); flags discrepancies between filesystem
reality and the state files; emits a scannable text report.

Never mutates state. Read-only by design.

Usage:
    python3 sysop/scripts/sitrep_survey.py             # text report
    python3 sysop/scripts/sitrep_survey.py --json      # JSON output (reserved)
    python3 sysop/scripts/sitrep_survey.py --stale-days 14
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print(
        "ERROR: sitrep_survey.py requires PyYAML. Install: pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(1)


# ── Constants ────────────────────────────────────────────────────

# Phase 40 introduced the Doc-Work: trailer. Commits before this cutoff date
# may carry no trailer; the heuristic fallback (subject-match + tracked branch)
# applies for those. Once all in-flight pre-Phase-40 branches close out, the
# fallback is dead code and can be removed.
PHASE_40_CUTOFF_ISO = "2026-05-23T00:00:00Z"
DEFAULT_STALE_DAYS = 7
# A review-round marker younger than this is treated as a live concurrent
# session, not an abandoned round (Phase 143). First-guess threshold — tune on
# real use; erring long keeps the signal trustworthy rather than chatty.
STALE_ROUND_HOURS = 2
TASK_BRANCH_PREFIXES = ("task/", "feat/", "tech/", "data/", "ux/", "fix/", "bug/")
REVIEW_BRANCH_PREFIXES = ("review/", "batch/")
TASK_ID_RE = re.compile(r"^([A-Z][A-Z0-9]*)-([A-Z0-9][A-Z0-9-]+)$")
SUBJECT_TASK_RE = re.compile(r"\(([A-Z][A-Z0-9]*-[A-Z0-9][A-Z0-9-]+)\)\s*$")


# ── Subprocess helpers ───────────────────────────────────────────


def _git(args: list[str], cwd: str | None = None, check: bool = False) -> str:
    """Run a git command, return stdout (stripped). On non-zero exit, return ''."""
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=check,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if r.returncode != 0:
            return ""
        return r.stdout.rstrip("\n")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _resolve_main_repo_root() -> Path:
    """Resolve the main repo root via git-common-dir (Phase 32)."""
    common = _git(["rev-parse", "--git-common-dir"])
    if not common:
        print("ERROR: not inside a git repository", file=sys.stderr)
        sys.exit(1)
    p = Path(common)
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    # .git is at <root>/.git — parent is the repo root.
    return p.parent


# ── Data classes ─────────────────────────────────────────────────


@dataclass
class Lock:
    task_id: str
    path: Path
    status: str = ""
    agent: str = ""
    branch: str = ""
    workspace: str = ""
    started: str = ""
    expires: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Worktree:
    path: Path
    branch: str
    head: str
    is_main: bool = False


@dataclass
class TaskState:
    task_id: str  # may be empty for orphan branches
    state: str  # classification label
    state_marker: str = ""  # '' or '~' for heuristic
    branch: str = ""
    worktree: str = ""
    commits_ahead: int = 0
    unpushed: int = 0
    has_lock: bool = False
    has_index_entry: bool = False
    index_status: str = ""  # from tasks/index.yml
    dirty: bool = False  # uncommitted changes in worktree
    doc_work_ids: list[str] = field(default_factory=list)
    next_action: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class ReviewBatchState:
    batch_number: int
    title: str
    md_status: str  # "Pending" / "In Progress" / etc. from review_tasks.md
    branch: str
    has_lock: bool
    has_branch: bool
    has_flag: bool  # True if review_tasks.md carries a > **Flag:** line for this batch
    flag_reason: str  # text after `> **Flag:**`, empty if not flagged
    total_tasks: int
    doc_worked_tasks: int
    state: str
    next_action: str
    notes: list[str] = field(default_factory=list)


@dataclass
class Recommendation:
    """Top-of-report routing recommendation. None when the surface is fully idle."""

    command: str  # the slash command or instruction to run next
    reason: str  # one-line "why this"
    clear_nudge: bool = False  # nudge the user to /clear before running (fresh-context cost)
    detail_lines: list[str] = field(default_factory=list)  # optional indented detail rows


@dataclass
class Discrepancy:
    kind: str
    detail: str
    suggestion: str


# ── Lock reading ─────────────────────────────────────────────────


def _read_locks(main_root: Path) -> list[Lock]:
    locks_dir = main_root / "sysop/runtime/locks"
    if not locks_dir.is_dir():
        return []
    out: list[Lock] = []
    for p in sorted(locks_dir.glob("*.lock")):
        if p.name == ".gitkeep":
            continue
        raw = _parse_lock_file(p)
        task_id = raw.get("task_id", p.stem)
        out.append(
            Lock(
                task_id=task_id,
                path=p,
                status=str(raw.get("status", "")),
                agent=str(raw.get("agent", "")),
                branch=str(raw.get("branch", "")),
                workspace=str(raw.get("workspace", "")),
                started=str(raw.get("started", "")),
                expires=str(raw.get("expires", "")),
                raw=raw,
            )
        )
    return out


def _parse_lock_file(path: Path) -> dict[str, Any]:
    """Lock files are YAML-shaped. Parse defensively; return {} on failure."""
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


# ── Worktree reading ─────────────────────────────────────────────


def _read_worktrees(main_root: Path) -> list[Worktree]:
    out: list[Worktree] = []
    raw = _git(["worktree", "list", "--porcelain"])
    if not raw:
        return out
    cur: dict[str, str] = {}
    for line in raw.splitlines():
        if not line:
            if cur:
                out.append(_finalize_worktree(cur, main_root))
            cur = {}
            continue
        if line.startswith("worktree "):
            cur["path"] = line[len("worktree ") :]
        elif line.startswith("HEAD "):
            cur["head"] = line[len("HEAD ") :]
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch ") :].replace("refs/heads/", "")
        elif line == "bare" or line == "detached":
            cur["state"] = line
    if cur:
        out.append(_finalize_worktree(cur, main_root))
    return out


def _finalize_worktree(d: dict[str, str], main_root: Path) -> Worktree:
    path = Path(d.get("path", ""))
    return Worktree(
        path=path,
        branch=d.get("branch", ""),
        head=d.get("head", ""),
        is_main=path.resolve() == main_root.resolve(),
    )


# ── tasks/index.yml reading ──────────────────────────────────────


def _read_index(main_root: Path) -> dict[str, dict[str, Any]]:
    p = main_root / "tasks" / "index.yml"
    if not p.is_file():
        return {}
    try:
        with p.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for t in data.get("tasks") or []:
        if isinstance(t, dict) and t.get("id"):
            out[t["id"]] = t
    return out


# ── review_tasks.md reading (minimal — only batch shape) ─────────


_BATCH_HEADER_RE = re.compile(r"^### Batch (\d+) — (.+?) `([A-Za-z ]+)`$")
_META_BRANCH_RE = re.compile(r"^> \*\*Branch:\*\* `([^`]+)`")
_META_FLAG_RE = re.compile(r"^> \*\*Flag:\*\*\s*(.*)$")
_TASK_LINE_RE = re.compile(r"^- \[( |/|x)\] \*\*(TASK-\d+)\*\*:")


def _read_review_batches(main_root: Path) -> list[dict[str, Any]]:
    p = main_root / "review_tasks.md"
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    try:
        with p.open(encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    for raw in lines:
        line = raw.rstrip("\n")
        m = _BATCH_HEADER_RE.match(line)
        if m:
            if current is not None:
                out.append(current)
            current = {
                "number": int(m.group(1)),
                "title": m.group(2).strip(),
                "status": m.group(3).strip(),
                "branch": "",
                "flag_reason": "",
                "tasks": [],
            }
            continue
        if current is None:
            continue
        mb = _META_BRANCH_RE.match(line)
        if mb:
            current["branch"] = mb.group(1)
            continue
        mf = _META_FLAG_RE.match(line)
        if mf:
            current["flag_reason"] = mf.group(1).strip()
            continue
        mt = _TASK_LINE_RE.match(line)
        if mt:
            current["tasks"].append({"checkbox": mt.group(1), "id": mt.group(2)})
    if current is not None:
        out.append(current)
    return out


# ── Commit + trailer scanning ────────────────────────────────────


@dataclass
class Commit:
    sha: str
    subject: str
    author_date: datetime
    doc_work_ids: list[str]
    subject_task_id: str | None


def _commits_ahead_of_main(branch: str, main_root: Path) -> list[Commit]:
    """List commits on `branch` that are not on `origin/main` (or `main`)."""
    base = _resolve_main_ref(main_root)
    if not base:
        return []
    raw = _git(
        ["log", f"{base}..{branch}", "--pretty=format:%H%x1f%s%x1f%aI%x1f%B%x1e"],
        cwd=str(main_root),
    )
    if not raw:
        return []
    out: list[Commit] = []
    for record in raw.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        try:
            sha, subject, date_str, body = record.split("\x1f", 3)
        except ValueError:
            continue
        try:
            author_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            author_date = datetime.now(timezone.utc)
        doc_work_ids = _extract_doc_work_trailers(body)
        mst = SUBJECT_TASK_RE.search(subject)
        out.append(
            Commit(
                sha=sha,
                subject=subject,
                author_date=author_date,
                doc_work_ids=doc_work_ids,
                subject_task_id=mst.group(1) if mst else None,
            )
        )
    return out


def _resolve_main_ref(main_root: Path) -> str:
    """Prefer origin/main; fall back to main; then HEAD on the main worktree."""
    for ref in ("origin/main", "main"):
        r = _git(["rev-parse", "--verify", "--quiet", ref], cwd=str(main_root))
        if r:
            return ref
    return ""


def _extract_doc_work_trailers(body: str) -> list[str]:
    """Extract Doc-Work: <ID> trailer values from a commit body.

    Uses `git interpret-trailers --parse` semantics: trailers live in the last
    paragraph of the body and have the form `Key: value`. We implement a small
    in-process parser to avoid an extra subprocess per commit.
    """
    paragraphs = re.split(r"\n\s*\n", body.strip())
    if not paragraphs:
        return []
    last = paragraphs[-1]
    ids: list[str] = []
    for line in last.splitlines():
        if line.lower().startswith("doc-work:"):
            value = line.split(":", 1)[1].strip()
            if TASK_ID_RE.match(value):
                ids.append(value)
    return ids


def _commits_unpushed(branch: str, main_root: Path) -> int:
    """Count commits on `branch` not on its upstream. Returns 0 if no upstream."""
    upstream = _git(
        ["rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"], cwd=str(main_root)
    )
    if not upstream:
        # No upstream — every commit ahead of main is also "unpushed."
        return -1  # sentinel: caller decides whether to treat as fully unpushed
    raw = _git(
        ["rev-list", "--count", f"{upstream}..{branch}"], cwd=str(main_root)
    )
    try:
        return int(raw)
    except ValueError:
        return 0


def _worktree_dirty(worktree_path: Path) -> bool:
    raw = _git(["status", "--porcelain"], cwd=str(worktree_path))
    return bool(raw.strip())


# ── Classification ───────────────────────────────────────────────


def _derive_task_id_from_branch(
    branch: str, index: dict[str, dict[str, Any]]
) -> str | None:
    """Resolve a branch to a task ID by matching tasks[].branch, then by suffix."""
    for tid, t in index.items():
        if t.get("branch") == branch:
            return tid
    # Fall back to lowercase suffix mapping: tech/tech-foo -> TECH-FOO
    if "/" in branch:
        suffix = branch.split("/", 1)[1]
        candidate = suffix.upper()
        if candidate in index:
            return candidate
    return None


def _classify_task(
    task_id: str,
    lock: Lock | None,
    worktree: Worktree | None,
    branch: str,
    index_entry: dict[str, Any] | None,
    commits: list[Commit],
    unpushed: int,
    dirty: bool,
    stale_days: int,
    phase40_cutoff: datetime,
) -> TaskState:
    state = "unknown"
    marker = ""
    next_action = ""
    notes: list[str] = []
    doc_work_ids = sorted({tid for c in commits for tid in c.doc_work_ids})

    # Stale check (applies to any state with a lock + worktree)
    if lock and lock.started:
        try:
            started = datetime.fromisoformat(lock.started.replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - started
            if age > timedelta(days=stale_days) and not commits:
                state = "stale"
                marker = ""
                next_action = (
                    f"investigate {task_id}; confirm dead and "
                    f"rm {lock.path} if abandoned"
                )
                notes.append(f"lock age {age.days}d; no commits ahead of main")
                return TaskState(
                    task_id=task_id,
                    state=state,
                    state_marker=marker,
                    branch=branch,
                    worktree=str(worktree.path) if worktree else "",
                    commits_ahead=0,
                    unpushed=0,
                    has_lock=bool(lock),
                    has_index_entry=bool(index_entry),
                    index_status=str((index_entry or {}).get("status", "")),
                    dirty=dirty,
                    doc_work_ids=doc_work_ids,
                    next_action=next_action,
                    notes=notes,
                )
        except ValueError:
            notes.append(f"lock has unparseable started='{lock.started}'")

    # Branchless claim
    if lock and not branch:
        state = "claimed, no branch"
        next_action = (
            f"branch not yet created for {task_id}; "
            "verify claim_task.sh completed or recreate"
        )
        return TaskState(
            task_id=task_id,
            state=state,
            state_marker=marker,
            branch="",
            worktree=str(worktree.path) if worktree else "",
            commits_ahead=0,
            unpushed=0,
            has_lock=True,
            has_index_entry=bool(index_entry),
            index_status=str((index_entry or {}).get("status", "")),
            dirty=dirty,
            doc_work_ids=doc_work_ids,
            next_action=next_action,
            notes=notes,
        )

    commits_ahead = len(commits)

    if commits_ahead == 0:
        state = "planning"
        next_action = (
            f"continue planning for {task_id} or run the reviewer-executor "
            "(see /claim-task Step 7)"
        )
    elif task_id and task_id in doc_work_ids:
        # Doc-Work trailer present for this task_id — distinguish pushed vs not
        if unpushed == 0:
            state = "ready for /review-close"
            next_action = f"/review-close {task_id}"
        else:
            state = "doc-work done, unpushed"
            count = unpushed if unpushed > 0 else commits_ahead
            next_action = (
                f"/review-close {task_id} "
                f"({count} unpushed commits — /review-close handles the push)"
            )
    else:
        # No Doc-Work trailer found. Try the Phase-40 fallback.
        fallback_hit = _phase40_fallback(commits, task_id, phase40_cutoff)
        if fallback_hit and unpushed == 0:
            state = "ready for /review-close"
            marker = "~"
            next_action = f"/review-close {task_id}"
            notes.append(
                "classified via pre-Phase-40 subject heuristic; "
                "next close-out commit will set the Doc-Work: trailer"
            )
        else:
            state = "in progress"
            next_action = (
                f"continue work or /document-work {task_id} when ready"
            )
            if dirty:
                notes.append("worktree has uncommitted changes")

    return TaskState(
        task_id=task_id,
        state=state,
        state_marker=marker,
        branch=branch,
        worktree=str(worktree.path) if worktree else "",
        commits_ahead=commits_ahead,
        unpushed=max(unpushed, 0),
        has_lock=bool(lock),
        has_index_entry=bool(index_entry),
        index_status=str((index_entry or {}).get("status", "")),
        dirty=dirty,
        doc_work_ids=doc_work_ids,
        next_action=next_action,
        notes=notes,
    )


def _phase40_fallback(
    commits: list[Commit], task_id: str, cutoff: datetime
) -> bool:
    """Pre-Phase-40 commits: subject matches `(<TASK_ID>)` and predates cutoff."""
    if not task_id:
        return False
    for c in commits:
        if c.author_date >= cutoff:
            continue
        if c.subject_task_id == task_id:
            return True
    return False


# ── Discrepancy detection ────────────────────────────────────────


def _find_discrepancies(
    locks: list[Lock],
    worktrees: list[Worktree],
    index: dict[str, dict[str, Any]],
    main_root: Path,
) -> list[Discrepancy]:
    out: list[Discrepancy] = []

    lock_ids = {l.task_id for l in locks}
    wt_branches = {w.branch for w in worktrees if not w.is_main}

    # Stale lock: lock present, no worktree on disk at the recorded workspace
    for l in locks:
        if not l.workspace:
            continue
        if not Path(l.workspace).is_dir():
            out.append(
                Discrepancy(
                    kind="stale lock",
                    detail=(
                        f"{l.task_id}: lock at {l.path} references "
                        f"missing workspace {l.workspace}"
                    ),
                    suggestion=(
                        f"investigate; rm {l.path} after confirming dead"
                    ),
                )
            )

    # Orphan worktree: worktree branch matches no lock + no index entry
    for w in worktrees:
        if w.is_main or not w.branch:
            continue
        derived = _derive_task_id_from_branch(w.branch, index)
        if derived and derived in lock_ids:
            continue
        if any(l.branch == w.branch for l in locks):
            continue
        if derived and derived in index:
            out.append(
                Discrepancy(
                    kind="index drift (in_progress without lock)",
                    detail=(
                        f"worktree {w.path} on branch {w.branch} "
                        f"resolves to {derived}, "
                        f"status='{index[derived].get('status')}' but no lock"
                    ),
                    suggestion=(
                        f"recreate lock via claim_task.sh --lock {derived} "
                        f"{w.branch} or flip status back"
                    ),
                )
            )
        else:
            out.append(
                Discrepancy(
                    kind="orphan worktree",
                    detail=(
                        f"worktree {w.path} on branch {w.branch} has no "
                        "matching lock or index entry"
                    ),
                    suggestion=(
                        f"investigate uncommitted work, then "
                        f"git worktree remove {w.path}"
                    ),
                )
            )

    # Orphan branch: task-shaped branch on disk with no lock, no index entry,
    # no worktree
    all_branches = _git(
        ["branch", "--list", "--format=%(refname:short)"], cwd=str(main_root)
    ).splitlines()
    for b in all_branches:
        if not _is_task_shaped_branch(b):
            continue
        if b in wt_branches:
            continue
        if any(l.branch == b for l in locks):
            continue
        derived = _derive_task_id_from_branch(b, index)
        if derived and derived in index:
            continue
        out.append(
            Discrepancy(
                kind="orphan branch",
                detail=f"branch {b} has no lock, no worktree, no index entry",
                suggestion=(
                    f"investigate; if dead, git branch -D {b}"
                ),
            )
        )

    # Index drift: tasks[].status == in_progress but no lock
    for tid, t in index.items():
        if t.get("status") != "in_progress":
            continue
        if tid in lock_ids:
            continue
        out.append(
            Discrepancy(
                kind="index drift (in_progress without lock)",
                detail=(
                    f"{tid}: tasks/index.yml status=in_progress but no lock "
                    "at <main-repo>/sysop/runtime/locks/"
                ),
                suggestion=(
                    f"recreate lock or flip {tid} status back to open"
                ),
            )
        )

    # Abandoned-claim discrepancies already surface as state='stale' above; no
    # duplicate entry needed.

    # Abandoned review round (Phase 143): a marker under pending-rounds/ that
    # outlived its round. The review skills write one at round-open and clear it
    # once review_tasks.md is written, so a survivor means the round died
    # mid-flight — a refusal after starting, a crash, quota exhaustion, context
    # death — none of which otherwise produce an error or a visible gap. Fresh
    # markers are skipped: a concurrent session mid-round is normal. This is the
    # full-lifecycle surface; loop mode has no /sitrep and reads the same signal
    # from self_check.sh and the pre-scan summary note instead.
    marker_dir = main_root / "sysop" / "runtime" / "pending-rounds"
    if marker_dir.is_dir():
        now = time.time()
        for m in sorted(marker_dir.glob("*.pending")):
            try:
                age_h = (now - m.stat().st_mtime) / 3600
            except OSError:
                continue
            if age_h < STALE_ROUND_HOURS:
                continue
            out.append(
                Discrepancy(
                    kind="abandoned review round",
                    detail=(
                        f"{m.name}: round opened {age_h:.0f}h ago and never "
                        "completed — its findings are absent or partial"
                    ),
                    suggestion=(
                        "re-run the skill; delete the marker once you have "
                        "confirmed the round is dead"
                    ),
                )
            )

    return out


def _is_task_shaped_branch(branch: str) -> bool:
    return branch.startswith(TASK_BRANCH_PREFIXES) or branch.startswith(
        REVIEW_BRANCH_PREFIXES
    )


# ── Review batch classification ──────────────────────────────────


def _classify_review_batches(
    batches: list[dict[str, Any]],
    locks: list[Lock],
    worktrees: list[Worktree],
    main_root: Path,
) -> list[ReviewBatchState]:
    out: list[ReviewBatchState] = []
    lock_by_branch = {l.branch: l for l in locks if l.branch}
    wt_branches = {w.branch for w in worktrees if not w.is_main}
    for b in batches:
        if b["status"] not in ("Pending", "In Progress"):
            continue
        branch = b.get("branch", "")
        flag_reason = b.get("flag_reason", "")
        has_flag = bool(flag_reason)
        has_lock = branch in lock_by_branch
        has_branch = branch in wt_branches or bool(
            _git(["rev-parse", "--verify", "--quiet", branch], cwd=str(main_root))
        )
        commits = _commits_ahead_of_main(branch, main_root) if has_branch else []
        all_dw_ids = {tid for c in commits for tid in c.doc_work_ids}
        batch_task_ids = {t["id"] for t in b["tasks"]}
        doc_worked = batch_task_ids & all_dw_ids
        total = len(batch_task_ids)
        done = len(doc_worked)

        if b["status"] == "Pending" and not has_lock:
            state = "pending (not claimed)"
            if has_flag:
                # Truncate cleanly without leaving an unclosed parenthesis from the reason.
                reason_short = flag_reason[:55].rstrip()
                if len(flag_reason) > 55:
                    reason_short += "…"
                next_action = f"/auto-judge will pick this up — flag: {reason_short}"
            else:
                # Untagged pending batch — /triage will classify it
                next_action = "/triage will classify (then /auto-fix or /auto-judge picks it up)"
        elif not has_branch:
            state = "claimed, no branch"
            next_action = (
                f"branch {branch} not created; recheck batch_work.sh result"
            )
        elif total == 0:
            state = "empty batch"
            next_action = "verify review_tasks.md batch contents"
        elif done == total:
            state = "ready for /review-close"
            next_action = f"/review-close (batch {b['number']})"
        elif done > 0:
            state = "in progress"
            next_action = (
                f"complete remaining tasks "
                f"({total - done} of {total}) then /document-work"
            )
        else:
            state = "in progress"
            next_action = (
                f"continue work; 0 of {total} tasks have Doc-Work trailers yet"
            )

        out.append(
            ReviewBatchState(
                batch_number=b["number"],
                title=b["title"],
                md_status=b["status"],
                branch=branch,
                has_lock=has_lock,
                has_branch=has_branch,
                has_flag=has_flag,
                flag_reason=flag_reason,
                total_tasks=total,
                doc_worked_tasks=done,
                state=state,
                next_action=next_action,
            )
        )
    return out


# ── Survey orchestration ─────────────────────────────────────────


@dataclass
class Survey:
    timestamp: datetime
    main_root: Path
    head_short: str
    tasks: list[TaskState]
    review_batches: list[ReviewBatchState]
    discrepancies: list[Discrepancy]
    stale_days: int
    open_roadmap_ids: list[str]  # task IDs with status: open in tasks/index.yml (claimable)


def run_survey(stale_days: int = DEFAULT_STALE_DAYS) -> Survey:
    main_root = _resolve_main_repo_root()
    head_short = _git(["rev-parse", "--short", "HEAD"], cwd=str(main_root))

    locks = _read_locks(main_root)
    worktrees = _read_worktrees(main_root)
    index = _read_index(main_root)
    review_batches_raw = _read_review_batches(main_root)

    phase40_cutoff = datetime.fromisoformat(
        PHASE_40_CUTOFF_ISO.replace("Z", "+00:00")
    )

    # Build the set of (task_id, branch, worktree, lock, index_entry) tuples
    # to classify.
    classified: list[TaskState] = []

    # Index entries with in_progress status drive the primary classification
    # set.
    seen_task_ids: set[str] = set()

    for lock in locks:
        task_id = lock.task_id
        if not task_id:
            continue
        # Skip review-batch locks (BATCH-* / TASK-* shaped); those are handled
        # by the review-batch path. Heuristic: roadmap IDs match a prefix that
        # ALSO has an entry in tasks/index.yml. If neither side knows the lock,
        # treat as roadmap-style task for completeness.
        if task_id.startswith("BATCH-") or task_id.startswith("TASK-"):
            continue
        seen_task_ids.add(task_id)
        index_entry = index.get(task_id)
        branch = lock.branch or (index_entry or {}).get("branch", "")
        worktree = next(
            (w for w in worktrees if w.branch == branch and not w.is_main), None
        )
        commits = (
            _commits_ahead_of_main(branch, main_root) if branch else []
        )
        unpushed = (
            _commits_unpushed(branch, main_root) if branch else 0
        )
        # Treat unpushed=-1 (no upstream) as "all ahead-of-main commits are
        # unpushed" for the purpose of state classification.
        if unpushed == -1 and commits:
            unpushed = len(commits)
        elif unpushed == -1:
            unpushed = 0
        dirty = (
            _worktree_dirty(worktree.path)
            if worktree and worktree.path.is_dir()
            else False
        )
        classified.append(
            _classify_task(
                task_id=task_id,
                lock=lock,
                worktree=worktree,
                branch=branch,
                index_entry=index_entry,
                commits=commits,
                unpushed=unpushed,
                dirty=dirty,
                stale_days=stale_days,
                phase40_cutoff=phase40_cutoff,
            )
        )

    # Index entries with in_progress status but no lock — surface as drift via
    # discrepancies; do NOT add to classified (the discrepancy carries the
    # signal).

    review_states = _classify_review_batches(
        review_batches_raw, locks, worktrees, main_root
    )

    discrepancies = _find_discrepancies(
        locks, worktrees, index, main_root
    )

    open_roadmap_ids = sorted(
        tid for tid, t in index.items() if t.get("status") == "open"
    )

    return Survey(
        timestamp=datetime.now(timezone.utc),
        main_root=main_root,
        head_short=head_short,
        tasks=classified,
        review_batches=review_states,
        discrepancies=discrepancies,
        stale_days=stale_days,
        open_roadmap_ids=open_roadmap_ids,
    )


# ── Rendering ────────────────────────────────────────────────────


def render_text(s: Survey) -> str:
    lines: list[str] = []
    when = s.timestamp.astimezone().strftime("%Y-%m-%d %H:%M %Z").strip()
    project = s.main_root.name
    lines.append(
        f"SITREP — {when} ({project} @ {s.head_short or '?'})"
    )
    lines.append("")

    # Active work
    if s.tasks:
        lines.append(f"ACTIVE WORK ({len(s.tasks)})")
        for ts in s.tasks:
            state_label = f"{ts.state}{ts.state_marker}"
            detail = _task_detail(ts)
            lines.append(
                f"  {ts.task_id:<12} {state_label:<30} {detail}"
            )
            if ts.next_action:
                lines.append(f"             ↳ next: {ts.next_action}")
            for note in ts.notes:
                lines.append(f"             · {note}")
        lines.append("")
    else:
        lines.append("ACTIVE WORK (0)")
        lines.append("  (no locks found; nothing claimed)")
        lines.append("")

    # Review batches
    if s.review_batches:
        lines.append(f"REVIEW BATCHES ({len(s.review_batches)})")
        for rb in s.review_batches:
            counts = f"{rb.doc_worked_tasks}/{rb.total_tasks} Doc-Work"
            lines.append(
                f"  Batch {rb.batch_number:<6} {rb.state:<28} {counts}"
            )
            if rb.next_action:
                lines.append(f"               ↳ next: {rb.next_action}")
        lines.append("")

    # Discrepancies
    if s.discrepancies:
        lines.append(f"DISCREPANCIES ({len(s.discrepancies)})")
        for d in s.discrepancies:
            lines.append(f"  ⚠ {d.kind}: {d.detail}")
            lines.append(f"    ↳ {d.suggestion}")
        lines.append("")
    else:
        lines.append("DISCREPANCIES (0)")
        lines.append("")

    # Recommended next (Phase 44) — single top routing call derived from
    # the survey state. Read by humans cold-resuming and by the model
    # deciding what to invoke next.
    rec = _recommended_next(s)
    lines.append("RECOMMENDED NEXT")
    if rec is None:
        lines.append("  (idle — no active work, no pending review, no claimable roadmap tasks)")
    else:
        lines.append(f"  → {rec.command}")
        lines.append(f"  Why: {rec.reason}")
        for detail in rec.detail_lines:
            lines.append(f"       {detail}")
        if rec.clear_nudge:
            lines.append(
                "  Consider: /clear or a new window first — the recommended skill spawns "
                "agents and benefits from a fresh context."
            )
    lines.append("")

    # Suggested order
    ordered = _suggested_order(s)
    if ordered:
        lines.append("SUGGESTED ORDER")
        for i, item in enumerate(ordered, start=1):
            lines.append(f"  {i}. {item}")
    else:
        lines.append("SUGGESTED ORDER")
        lines.append("  (no active Sysop work; pick up a new task with /next-task)")

    return "\n".join(lines) + "\n"


def _task_detail(ts: TaskState) -> str:
    bits: list[str] = []
    if ts.dirty:
        bits.append("dirty")
    else:
        bits.append("clean")
    if ts.commits_ahead:
        bits.append(f"{ts.commits_ahead} commits ahead")
    if ts.unpushed and ts.unpushed != ts.commits_ahead:
        bits.append(f"{ts.unpushed} unpushed")
    if ts.doc_work_ids:
        bits.append("Doc-Work ✓")
    return ", ".join(bits)


# /auto-build caps a batch at N=4 tasks (WORKFLOW.md § 2.4b). A roadmap deeper
# than one batch is where a strategy view (/roadmap) beats jumping straight to
# batch execution; at or below one batch, /auto-build grabs it in a single go.
_AUTO_BUILD_MAX_BATCH = 4


def _recommended_next(s: Survey) -> Recommendation | None:
    """Single top routing recommendation. See SKILL.md § Recommendation routing rules.

    Priority order: review-close (task) → review-close (batch) → unpushed doc-work →
    /triage if any pending batch lacks Flag tag → /auto-fix and/or /auto-judge →
    continue in-progress → resume planning → /roadmap (deep queue) or /auto-build
    (shallow) → idle.
    """
    # P1: tasks ready for /review-close
    ready_tasks = [t for t in s.tasks if t.state == "ready for /review-close"]
    if ready_tasks:
        t = ready_tasks[0]
        more = f" ({len(ready_tasks) - 1} more queued)" if len(ready_tasks) > 1 else ""
        return Recommendation(
            command=f"/review-close {t.task_id}",
            reason=(
                f"{t.task_id} has Doc-Work trailer and is pushed; ready to merge"
                + more
            ),
        )

    # P2: review batches with all tasks Doc-Work'd
    ready_batches = [rb for rb in s.review_batches if rb.state == "ready for /review-close"]
    if ready_batches:
        rb = ready_batches[0]
        return Recommendation(
            command=f"/review-close (batch {rb.batch_number})",
            reason=(
                f"Batch {rb.batch_number} — all {rb.total_tasks} tasks have "
                f"Doc-Work trailers; ready to merge"
            ),
        )

    # P3: doc-work done but unpushed
    unpushed = [t for t in s.tasks if t.state == "doc-work done, unpushed"]
    if unpushed:
        t = unpushed[0]
        return Recommendation(
            command=f"/review-close {t.task_id}",
            reason=(
                f"{t.task_id} has Doc-Work trailer with unpushed commits; "
                f"/review-close pushes and merges"
            ),
        )

    # P4: pending unclaimed batches — route via Flag tag presence
    pending_unclaimed = [rb for rb in s.review_batches if rb.state == "pending (not claimed)"]
    if pending_unclaimed:
        untagged = [rb for rb in pending_unclaimed if not rb.has_flag]
        flagged = [rb for rb in pending_unclaimed if rb.has_flag]
        auto = [rb for rb in pending_unclaimed if not rb.has_flag]
        if untagged:
            # Some batches not yet triaged — /triage is the prereq before /auto-fix or /auto-judge
            n_untagged = len(untagged)
            sample = [f"batch {rb.batch_number}" for rb in untagged[:3]]
            sample_str = ", ".join(sample)
            if n_untagged > 3:
                sample_str += f", +{n_untagged - 3} more"
            return Recommendation(
                command="/triage",
                reason=(
                    f"{n_untagged} pending batch(es) lack Flag tags; "
                    f"/triage classifies them as auto vs flag, then /auto-fix "
                    f"and /auto-judge route accordingly"
                ),
                detail_lines=[f"untriaged: {sample_str}"],
            )
        # All triaged — route to /auto-fix and/or /auto-judge
        n_auto = len(auto)
        n_flag = len(flagged)
        if n_auto > 0 and n_flag > 0:
            return Recommendation(
                command="/auto-fix  (concurrent with /auto-judge)",
                reason=(
                    f"{n_auto} auto batch(es) + {n_flag} flag batch(es); "
                    f"/auto-fix and /auto-judge target disjoint pools and can run concurrently"
                ),
                clear_nudge=True,
            )
        if n_flag > 0:
            return Recommendation(
                command="/auto-judge",
                reason=f"{n_flag} flagged batch(es) need Opus judgment",
                clear_nudge=True,
            )
        # n_auto > 0, n_flag == 0
        return Recommendation(
            command="/auto-fix",
            reason=f"{n_auto} auto batch(es) ready for mechanical fixes",
            clear_nudge=True,
        )

    # P5: in-progress tasks (single-task work)
    in_progress = [t for t in s.tasks if t.state == "in progress"]
    if in_progress:
        t = in_progress[0]
        return Recommendation(
            command=f"continue work on {t.task_id} or /document-work {t.task_id}",
            reason=(
                f"{t.task_id} has {t.commits_ahead} commit(s) ahead of main "
                f"but no Doc-Work trailer yet"
            ),
        )

    # P6: planning tasks
    planning = [t for t in s.tasks if t.state == "planning"]
    if planning:
        t = planning[0]
        return Recommendation(
            command=f"resume planning for {t.task_id}",
            reason=f"{t.task_id} has a branch + lock but 0 commits ahead",
        )

    # P7: no active work — the roadmap has claimable tasks.
    # A deep queue (more than one /auto-build batch's worth) routes to /roadmap
    # first, so the human sees the work grouped by kind + a proposed order of
    # attack before batch-executing; a shallow queue that fits in a single batch
    # routes straight to /auto-build. See SKILL.md § Recommendation routing rules.
    if s.open_roadmap_ids:
        n = len(s.open_roadmap_ids)
        sample = s.open_roadmap_ids[:3]
        sample_str = ", ".join(sample)
        if n > 3:
            sample_str += f", +{n - 3} more"
        if n > _AUTO_BUILD_MAX_BATCH:
            # 7a: deep queue — strategize before batching. /roadmap is read-only
            # (no fan-out), so no /clear nudge.
            return Recommendation(
                command="/roadmap",
                reason=(
                    f"{n} open roadmap task(s) in tasks/index.yml — more than one "
                    f"/auto-build batch (max {_AUTO_BUILD_MAX_BATCH}); /roadmap groups them "
                    f"by kind and proposes an order of attack before you /auto-build the frontier"
                ),
                detail_lines=[f"open: {sample_str}"],
            )
        # 7b: shallow queue — one /auto-build batch covers it.
        return Recommendation(
            command="/auto-build",
            reason=(
                f"{n} open roadmap task(s) in tasks/index.yml; /auto-build picks "
                f"a batch under the K=12 weight ceiling and orchestrates plan + execute"
            ),
            detail_lines=[f"open: {sample_str}"],
            clear_nudge=True,
        )

    # P8: truly idle
    return None


def _suggested_order(s: Survey) -> list[str]:
    """Order: ready-to-close first, then in-progress with Doc-Work-needed,
    then planning, then discrepancies."""
    out: list[str] = []
    # 1. Ready for /review-close
    for ts in s.tasks:
        if ts.state == "ready for /review-close":
            out.append(f"/review-close {ts.task_id} (ready now)")
    for rb in s.review_batches:
        if rb.state == "ready for /review-close":
            out.append(f"/review-close (batch {rb.batch_number}, ready now)")
    # 2. Doc-work-done-but-unpushed (/review-close handles the push)
    for ts in s.tasks:
        if ts.state == "doc-work done, unpushed":
            out.append(f"/review-close {ts.task_id}")
    # 3. In-progress (Doc-Work next)
    for ts in s.tasks:
        if ts.state == "in progress":
            out.append(f"/document-work {ts.task_id} (no Doc-Work trailer yet)")
    # 4. Planning
    for ts in s.tasks:
        if ts.state == "planning":
            out.append(f"resume {ts.task_id} planning (0 commits ahead)")
    # 5. Discrepancies
    if s.discrepancies:
        n = len(s.discrepancies)
        word = "discrepancy" if n == 1 else "discrepancies"
        out.append(f"triage {n} {word}")
    return out


# ── JSON rendering (reserved) ────────────────────────────────────


def render_json(s: Survey) -> str:
    def _ts(t: TaskState) -> dict[str, Any]:
        return {
            "task_id": t.task_id,
            "state": t.state,
            "state_marker": t.state_marker,
            "branch": t.branch,
            "worktree": t.worktree,
            "commits_ahead": t.commits_ahead,
            "unpushed": t.unpushed,
            "has_lock": t.has_lock,
            "has_index_entry": t.has_index_entry,
            "index_status": t.index_status,
            "dirty": t.dirty,
            "doc_work_ids": t.doc_work_ids,
            "next_action": t.next_action,
            "notes": t.notes,
        }

    def _rb(r: ReviewBatchState) -> dict[str, Any]:
        return {
            "batch_number": r.batch_number,
            "title": r.title,
            "md_status": r.md_status,
            "branch": r.branch,
            "has_lock": r.has_lock,
            "has_branch": r.has_branch,
            "has_flag": r.has_flag,
            "flag_reason": r.flag_reason,
            "total_tasks": r.total_tasks,
            "doc_worked_tasks": r.doc_worked_tasks,
            "state": r.state,
            "next_action": r.next_action,
            "notes": r.notes,
        }

    def _d(d: Discrepancy) -> dict[str, Any]:
        return {
            "kind": d.kind,
            "detail": d.detail,
            "suggestion": d.suggestion,
        }

    rec = _recommended_next(s)
    rec_json: dict[str, Any] | None = None
    if rec is not None:
        rec_json = {
            "command": rec.command,
            "reason": rec.reason,
            "clear_nudge": rec.clear_nudge,
            "detail_lines": rec.detail_lines,
        }

    return (
        json.dumps(
            {
                "timestamp": s.timestamp.isoformat(),
                "main_root": str(s.main_root),
                "head_short": s.head_short,
                "stale_days": s.stale_days,
                "tasks": [_ts(t) for t in s.tasks],
                "review_batches": [_rb(r) for r in s.review_batches],
                "discrepancies": [_d(d) for d in s.discrepancies],
                "open_roadmap_ids": s.open_roadmap_ids,
                "recommended_next": rec_json,
                "suggested_order": _suggested_order(s),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


# ── CLI ──────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser(
        description="Read-only situation report for sysop"
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the text report (reserved)",
    )
    p.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_STALE_DAYS,
        help=(
            f"Abandoned-claim threshold in days (default {DEFAULT_STALE_DAYS})"
        ),
    )
    args = p.parse_args()

    try:
        survey = run_survey(stale_days=args.stale_days)
    except KeyboardInterrupt:
        return 130
    if args.json:
        sys.stdout.write(render_json(survey))
    else:
        sys.stdout.write(render_text(survey))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
