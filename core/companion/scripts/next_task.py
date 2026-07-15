#!/usr/bin/env python3
"""Deterministic /next-task replacement.

Reads ``tasks/index.yml`` + ``review_tasks.md`` + ``.locks/`` and prints the
same user-facing markdown that ``core/skills/next-task/SKILL.md`` produced
when it was an LLM (haiku) call. Runs in ~100 ms; no model cost.

Usage:
    .venv/bin/python3 scripts/next_task.py                   # default (Step 2a then 2b)
    .venv/bin/python3 scripts/next_task.py --review          # only pending review batches
    .venv/bin/python3 scripts/next_task.py --avoid-inflight  # prefer non-colliding tasks

Exit codes:
    0   success (including the "no tasks found" paths)
    1   invariant violation (schema_version too low, current_focus != 1,
        body-path escapes tasks/, etc.) — print a diagnostic to stderr
    2   unexpected exception (top-level safety net)

Algorithm (mirrors the legacy SKILL.md prose so the source-of-truth lives
with the implementation):

  Step 1   read tasks/index.yml, review_tasks.md, list .locks/*.lock
  Step 2a  (skipped if --review) — locate the single current_focus phase, then
           among phase=focus tasks with status="open", drop those with a lock,
           drop those with on_hold_until set, drop those with any incomplete
           dependency, prefer user_action:false, sort unblocker-first (most
           open same-phase dependents), then effort (Low<Med<High), then id,
           return the first. With --avoid-inflight, prepend a collision-rank
           key (via scripts/scope_overlap.py) so a task whose likely scope
           doesn't touch any in-flight worktree is preferred, and annotate the
           chosen task with its overlap verdict.
  Step 2b  scan review_tasks.md for the FIRST ``### Batch N — Title `Pending` ``
           heading whose ``.locks/BATCH-<N>.lock`` is absent; capture branch /
           scope / verify / tasks / severity breakdown.
  Step 3   load the selected task's body file (relative to tasks/ or repo
           root) and extract ## Context / ## Requirements / ## User ops.
  Step 4   read task effort from index.yml verbatim.
  Step 5   estimate review-batch effort from a fixed rubric.
  Step 6   for review batches, heuristic-flag user_action via keyword scan.
  Step 7   render the single-item markdown output.

The script intentionally has no external dependencies beyond PyYAML and the
stdlib so it can run from a pre-commit hook before the project's venv
activates. ``_sanitize_log`` and ``_resolve_canonical_locks_dir`` are
duplicated from ``validate_tasks.py`` rather than imported, for the same
reason — both scripts must remain standalone-runnable.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml


# ---------------------------------------------------------------------------
# Constants & module-scope regex (per scripts convention: precompile at module
# load, not per-call). Names match the pattern used by validate_tasks.py.
# ---------------------------------------------------------------------------
MIN_SCHEMA_VERSION = 1  # forward-compatible: accept v1 (legacy) and v2

# Effort sort order. Anything outside the enum sinks to the end (effort is
# validator-enforced for open/in_progress, so this fallback is purely
# defensive against future schema drift).
_EFFORT_ORDER = {"Low": 0, "Medium": 1, "High": 2}

# Collision-avoidance rank for the optional --avoid-inflight ranking nudge
# (Phase 103, Leg A enrichment). Mirrors scope_overlap.py's _VERDICT_RANK, kept
# as a local copy so the default /next-task path imports nothing extra (the
# primitive is imported lazily, only when --avoid-inflight is passed). Higher =
# more collision risk = sorted later.
_OVERLAP_RANK = {"none": 0, "possible": 1, "likely": 2}

# Review batch heading: ``### Batch <N> — <Title> `<Status>` ``. Both em-dash
# (—) and ASCII hyphen are tolerated. Status is in single backticks.
_BATCH_HEADER_RE = re.compile(
    r"^###\s+Batch\s+(?P<number>\d+)\s*[—\-]+\s*(?P<title>.+?)\s*`(?P<status>[^`]+)`\s*$"
)

# Quoted metadata lines under a batch heading:
#   > **Branch:** `branch-name`
#   > **Scope:** `path` or prose
#   > **Verify:** `command`
_BATCH_FIELD_RE = re.compile(
    r"^>\s*\*\*(?P<key>Branch|Scope|Verify):\*\*\s*(?P<value>.+?)\s*$"
)

# Task line under a batch heading:
#   - [ ] **TASK-NNN**: description 🔴/🟡/🟢
#   - [/] **TASK-NNN**: ...
#   - [x] **TASK-NNN**: ...
# The checkbox-state determines "open" vs "in-progress" vs "done".
_BATCH_TASK_RE = re.compile(
    r"^-\s*\[(?P<state>[ /xX])\]\s*\*\*(?P<task_id>[A-Z][A-Z0-9-]+)\*\*\s*[:\-]?\s*(?P<rest>.+?)\s*$"
)

# Severity emojis used in review_tasks.md. We tolerate the variation-selector
# (️) some terminals append after these emoji.
_SEVERITY_HIGH = "🔴"
_SEVERITY_MEDIUM = "🟡"
_SEVERITY_LOW = "🟢"
_SEVERITY_EMOJIS = (_SEVERITY_HIGH, _SEVERITY_MEDIUM, _SEVERITY_LOW)

# Heading inside a body file (e.g., ``## Context``). Used to split a body
# into sections. We capture the heading text and let everything after the
# match through to the next ``^## `` line accumulate as the body.
_BODY_SECTION_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")

# Backtick-pair strip helper: ``` `foo` `` → ``foo``. Used on Branch / Verify
# field values; the prose surfaces in code style today. Only strips when the
# entire value is wrapped in a SINGLE pair of backticks — multi-backtick
# values like ``` `a.py`, `b.py` ``` (a Scope listing) are preserved verbatim,
# because greedy stripping there silently mangles the value.
_BACKTICK_VALUE_RE = re.compile(r"^`(?P<inner>[^`]+)`$")

# Keyword tokens that flag a review batch as needing user action. The list is
# intentionally short and visible so a future maintainer can extend it without
# digging through code. False positives are recoverable (over-cautious
# warning); false negatives surface when the user tries to claim.
_USER_ACTION_KEYWORDS = (
    "console",
    "dashboard",
    "credentials",
    "manual",
    "manually",
    "secret manager",
    "gcloud auth",
)


# ---------------------------------------------------------------------------
# _sanitize_log — duplicated from validate_tasks.py so this script remains
# standalone-runnable (no shared-helper import). Keep the two in sync.
# ---------------------------------------------------------------------------
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_CONTROL_RE = re.compile(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_log(value: object, max_len: int = 500) -> str:
    """Strip ANSI / control chars + truncate. Used on every printed exception
    so a multi-megabyte traceback or terminal escape can't bleed into stderr.
    Mirror of ``validate_tasks.py:_sanitize_log``."""
    text = str(value)
    text = _ANSI_ESCAPE_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    text = text.replace("\n", " ").replace("\r", " ").replace("\0", " ")
    if len(text) > max_len:
        text = text[:max_len] + "..."
    return text


# ---------------------------------------------------------------------------
# Repo paths
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_TASKS_DIR = _REPO_ROOT / "tasks"
_INDEX_PATH = _TASKS_DIR / "index.yml"
_REVIEW_PATH = _REPO_ROOT / "review_tasks.md"


# ---------------------------------------------------------------------------
# Lock directory resolution — mirror of validate_tasks.py:_resolve_canonical_locks_dir
# so the two stay in sync. See that function for the rationale on
# `git rev-parse --git-common-dir` (worktree-shared .locks/).
# ---------------------------------------------------------------------------
def _resolve_canonical_locks_dir(project_root: Path) -> Path:
    """Resolve the canonical ``.locks/`` directory shared across worktrees.

    Mirror of ``validate_tasks.py:_resolve_canonical_locks_dir``. Kept as an
    intentional zero-dependency duplicate (this script must remain importable
    from a minimal environment — no path-shuffling to reach
    scripts/validate_tasks.py).
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return project_root / ".locks"
    if completed.returncode != 0:
        return project_root / ".locks"
    common_dir = completed.stdout.strip()
    if not common_dir:
        return project_root / ".locks"
    common_path = Path(common_dir)
    if not common_path.is_absolute():
        common_path = (project_root / common_path).resolve()
    return common_path.parent / ".locks"


# ---------------------------------------------------------------------------
# Index loader
# ---------------------------------------------------------------------------
def load_index(index_path: Path | None = None) -> dict[str, Any]:
    """Load tasks/index.yml with ``yaml.safe_load``. Aborts the script with
    exit-code 1 on parse error or missing file (matches `validate_tasks.py`
    exit semantics — schema invariant violation is unrecoverable here).

    Default ``None`` (rather than a captured module constant) so test
    monkey-patches of ``_INDEX_PATH`` take effect — Python evaluates default
    args once at function-definition time, which would snapshot the original
    constant.
    """
    if index_path is None:
        index_path = _INDEX_PATH
    if not index_path.is_file():
        print(f"ERROR: index.yml not found at {index_path}", file=sys.stderr)
        raise SystemExit(1)
    try:
        with open(index_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as e:
        print(
            f"ERROR: YAML parse error in {index_path}: {_sanitize_log(str(e)[:500])}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if not isinstance(data, dict):
        print(
            f"ERROR: {index_path} top-level YAML must be a mapping",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return data


def _assert_schema_version(data: dict[str, Any], minimum: int = MIN_SCHEMA_VERSION) -> None:
    """Enforce the forward-compat schema-version invariant.

    Accepts any int >= ``minimum``. Both v1 (legacy, blast_radius optional)
    and v2 (current, blast_radius required on open/in_progress) are valid
    inputs for this script — we don't read ``blast_radius`` for selection.
    A future v3 would still parse if it stays additive; if it removes a
    field the validator catches it before we run.
    """
    sv = data.get("schema_version")
    if isinstance(sv, bool) or not isinstance(sv, int):
        print(
            f"ERROR: schema_version must be an integer, got "
            f"{_sanitize_log(type(sv).__name__)}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if sv < minimum:
        print(
            f"ERROR: schema_version {sv} is older than supported minimum "
            f"{minimum}. Update tasks/index.yml or pin to an older copy of "
            "this script.",
            file=sys.stderr,
        )
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Phase & task selection
# ---------------------------------------------------------------------------
def find_focus_phase(data: dict[str, Any]) -> dict[str, Any]:
    """Return the single ``current_focus: true`` phase.

    Validator invariant 5 guarantees exactly one — but this script can be
    invoked against a partially-edited tree (a /claim-task in flight in
    another worktree), so we still defend.
    """
    phases = data.get("phases") or []
    matches = [p for p in phases if isinstance(p, dict) and p.get("current_focus") is True]
    if len(matches) != 1:
        print(
            f"ERROR: exactly one phase must have current_focus: true "
            f"(found {len(matches)}). Run scripts/validate_tasks.py for details.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return matches[0]


def list_locks(project_root: Path | None = None) -> set[str]:
    """Return the set of task / batch IDs that have an active lock file.

    Strips the ``.lock`` suffix and basenames to leave just the ID
    (``TECH-FOO`` or ``BATCH-42``). Uses the worktree-shared ``.locks/`` via
    ``_resolve_canonical_locks_dir`` so a /next-task running in worktree A
    still sees a claim made in worktree B.

    Default ``None`` so tests can monkey-patch ``_REPO_ROOT`` and have the
    change take effect (mutable defaults are captured at definition time).
    """
    if project_root is None:
        project_root = _REPO_ROOT
    locks_dir = _resolve_canonical_locks_dir(project_root)
    if not locks_dir.is_dir():
        return set()
    out: set[str] = set()
    for p in glob.glob(str(locks_dir / "*.lock")):
        name = os.path.basename(p)
        if name.endswith(".lock"):
            out.add(name[: -len(".lock")])
    return out


def pick_next_task(
    data: dict[str, Any],
    locks: set[str],
    focus_phase_number: float | int,
    overlap_fn: Callable[[str], int] | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Pick the next agent-executable task in the focus phase.

    Returns ``(selected, user_action_candidates)``.

    - ``selected`` is the first task in priority order — unblocker-first (most
      open same-phase dependents), then effort (Low<Med<High), then id — that
      is fully agent-executable (``user_action: false``). ``None`` if no
      agent-executable candidate exists OR no candidates at all.
    - ``user_action_candidates`` is the list of unblocked user-action-required
      tasks. Used by Step 7 to surface a fallback list when no agent task
      remains.

    ``overlap_fn`` (Phase 103, ``--avoid-inflight``) is an optional
    ``task_id -> collision_rank`` callable (0=clear, 1=possible, 2=likely
    overlap with work in flight). When provided, avoidance is applied in two
    tiers: a **``likely``** (exact-path) overlap is the **primary** key — the
    caller opted in to avoid in-flight collisions, and an exact-path match is a
    near-certain conflict, so it outranks even unblocker-first; a **``possible``**
    (same-dir/glob) overlap is only a **secondary** nudge applied *after*
    unblocker-first, so a foundational task isn't buried for a weak same-dir
    guess. A clear task still wins at equal standing. When ``None`` (the default,
    and every path but the opt-in flag), the sort is unchanged. The callable is
    invoked once per candidate; the caller memoizes the underlying git reads
    (see ``main``). Contrast ``/auto-build``, where the same signal is a *purely
    secondary* nudge (the full 0/1/2 rank, always after unblocker-first) — that
    path is always-on, so it must never bury a foundational unblocker; here the
    explicit flag lets an exact-path conflict take precedence.
    """
    tasks = data.get("tasks") or []
    if not isinstance(tasks, list):
        return None, []
    by_id = {t["id"]: t for t in tasks if isinstance(t, dict) and isinstance(t.get("id"), str)}

    # unlock_count[id] = number of open, focus-phase tasks that list `id` in
    # their depends_on. Direct dependents only (not transitive — a transitive
    # count overweights long chains whose tails are far off anyway). Phase-
    # scoped because the claimable pool is phase-scoped: only a same-phase
    # dependent becoming ready enlarges the next pool. Sorting high-unlock
    # tasks first is unblocker-first ordering — do the foundational task now so
    # more work becomes claimable next (mirrors /auto-build Step 1).
    unlock_count: dict[str, int] = {}
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if t.get("status") != "open" or t.get("phase") != focus_phase_number:
            continue
        for dep in t.get("depends_on") or []:
            if isinstance(dep, str):
                unlock_count[dep] = unlock_count.get(dep, 0) + 1

    def ready(t: dict[str, Any]) -> bool:
        if not isinstance(t, dict):
            return False
        if t.get("status") != "open":
            return False
        if t.get("phase") != focus_phase_number:
            return False
        if t.get("on_hold_until"):
            return False
        tid = t.get("id")
        if not isinstance(tid, str) or tid in locks:
            return False
        for dep in t.get("depends_on") or []:
            dep_task = by_id.get(dep)
            if not dep_task or dep_task.get("status") != "done":
                return False
        return True

    candidates = [t for t in tasks if ready(t)]
    agent_pool = [t for t in candidates if not t.get("user_action")]
    user_action_pool = [t for t in candidates if t.get("user_action")]

    # --avoid-inflight: precompute each candidate's collision rank once (the
    # callable does git I/O), so sort_key stays a cheap dict lookup. Absent the
    # flag (overlap_fn is None) this stays empty and the sort is unchanged.
    overlap_rank: dict[str, int] = {}
    if overlap_fn is not None:
        for t in candidates:
            tid = t.get("id")
            if isinstance(tid, str):
                overlap_rank[tid] = overlap_fn(tid)

    def sort_key(t: dict[str, Any]) -> tuple[int, int, str]:
        tid = str(t.get("id", ""))
        effort = t.get("effort")
        order = _EFFORT_ORDER.get(effort, 9) if isinstance(effort, str) else 9
        # Negative unlock_count so the highest-unlock task sorts first
        # (unblocker-first), then effort ascending, then id.
        return (-unlock_count.get(tid, 0), order, tid)

    def avoid_inflight_key(t: dict[str, Any]) -> tuple[int, int, int, int, str]:
        tid = str(t.get("id", ""))
        rank = overlap_rank.get(tid, 0)  # 0=none, 1=possible, 2=likely
        # Two-tier avoidance. A `likely` overlap is an *exact-path* match — a
        # near-certain conflict — so it's the PRIMARY key: steer around it even
        # ahead of an unblocker. A `possible` overlap is same-directory/glob — a
        # guess on a guess (the candidate's own scope is inferred) — so it's only
        # a SECONDARY nudge applied *after* unblocker-first, so a foundational
        # task is never buried for a weak same-dir hit. Both still lose to a
        # clear task at equal standing. (sort_key = (-unlock, effort, id).)
        likely = 1 if rank >= 2 else 0
        possible = 1 if rank == 1 else 0
        unlock_key, effort_key, id_key = sort_key(t)
        return (likely, unlock_key, possible, effort_key, id_key)

    key = avoid_inflight_key if overlap_fn is not None else sort_key
    agent_pool.sort(key=key)
    user_action_pool.sort(key=key)
    return (agent_pool[0] if agent_pool else None), user_action_pool


# ---------------------------------------------------------------------------
# Review batch parsing
# ---------------------------------------------------------------------------
def parse_review_batches(text: str) -> list[dict[str, Any]]:
    """Parse ``review_tasks.md`` into a list of batch dicts.

    LENIENT by design — schema for review_tasks.md is prose-defined, not
    validator-backed. A malformed batch heading is skipped (with a stderr
    warning) and parsing continues.

    Each batch dict has::

        {
            "number": int,
            "title": str,
            "status": str,      # "Pending", "In Progress", "Ready for Review",
                                # "Complete", "Merged" (whatever the file said)
            "branch": str | None,
            "scope": str | None,
            "verify": str | None,
            "tasks": list[dict],   # [{"task_id", "state", "rest", "severity"}, ...]
            "severity": dict,      # {"high": int, "medium": int, "low": int}
            "open_count": int,
        }
    """
    batches: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    lines = text.splitlines()

    def _flush() -> None:
        if current is not None:
            batches.append(current)

    for raw in lines:
        line = raw.rstrip()
        m = _BATCH_HEADER_RE.match(line)
        if m:
            _flush()
            try:
                number = int(m.group("number"))
            except (TypeError, ValueError):
                print(
                    "WARN: skipping batch with non-integer number: "
                    f"{_sanitize_log(line)}",
                    file=sys.stderr,
                )
                current = None
                continue
            current = {
                "number": number,
                "title": m.group("title").strip(),
                "status": m.group("status").strip(),
                "branch": None,
                "scope": None,
                "verify": None,
                "tasks": [],
                "severity": {"high": 0, "medium": 0, "low": 0},
                "open_count": 0,
            }
            continue
        if current is None:
            continue

        fm = _BATCH_FIELD_RE.match(line)
        if fm:
            key = fm.group("key").lower()
            value = fm.group("value").strip()
            bm = _BACKTICK_VALUE_RE.match(value)
            if bm:
                value = bm.group("inner")
            current[key] = value
            continue

        tm = _BATCH_TASK_RE.match(line)
        if tm:
            state = tm.group("state")
            rest = tm.group("rest")
            severity: str | None = None
            for sym in _SEVERITY_EMOJIS:
                if sym in rest:
                    severity = sym
                    break
            current["tasks"].append(
                {
                    "task_id": tm.group("task_id"),
                    "state": state,
                    "rest": rest.strip(),
                    "severity": severity,
                }
            )
            if state == " ":
                current["open_count"] += 1
            if severity == _SEVERITY_HIGH:
                current["severity"]["high"] += 1
            elif severity == _SEVERITY_MEDIUM:
                current["severity"]["medium"] += 1
            elif severity == _SEVERITY_LOW:
                current["severity"]["low"] += 1
            continue

    _flush()
    return batches


def pick_next_batch(
    batches: list[dict[str, Any]], locks: set[str]
) -> tuple[dict[str, Any] | None, int]:
    """Return ``(first_pending_unlocked, total_pending_count)``.

    Total includes locked Pending batches — it's a "how much work is queued"
    counter, not "how much you can claim right now".
    """
    pending = [b for b in batches if b.get("status") == "Pending"]
    for b in pending:
        if f"BATCH-{b['number']}" in locks:
            continue
        return b, len(pending)
    return None, len(pending)


def estimate_batch_effort(batch: dict[str, Any]) -> str:
    """Apply the Step 5 rubric verbatim:

      Low    1-2 tasks, all low/medium severity
      Medium 3-5 tasks, OR any high severity
      High   6+ tasks
    """
    n = len(batch.get("tasks") or [])
    sev = batch.get("severity") or {}
    high = int(sev.get("high", 0) or 0)
    if n >= 6:
        return "High"
    if n >= 3 or high > 0:
        return "Medium"
    return "Low"


def infer_batch_user_action(batch: dict[str, Any]) -> tuple[bool, list[str]]:
    """Heuristic: scan task descriptions + verify command for tokens that
    suggest manual / out-of-band action. Returns ``(needs_user, reasons)``.

    Token list is intentionally visible in ``_USER_ACTION_KEYWORDS``;
    extending it is a one-line change.
    """
    reasons: list[str] = []
    verify = batch.get("verify") or ""
    haystacks: list[tuple[str, str]] = [("verify command", verify.lower())]
    for t in batch.get("tasks") or []:
        rest = (t.get("rest") or "").lower()
        if rest:
            haystacks.append((f"task {t.get('task_id', '?')}", rest))
    seen_keywords: set[str] = set()
    for label, hay in haystacks:
        for kw in _USER_ACTION_KEYWORDS:
            if kw in hay and kw not in seen_keywords:
                reasons.append(f"{label} mentions '{kw}'")
                seen_keywords.add(kw)
    return (bool(reasons), reasons)


# ---------------------------------------------------------------------------
# Body file extraction
# ---------------------------------------------------------------------------
def _resolve_body_path(body_rel: str, base_tasks_dir: Path, project_root: Path) -> Path:
    """Resolve a ``body:`` field to an absolute path with containment check.

    Mirrors ``validate_tasks.py:_validate_tasks`` two-branch rule:
    - if it starts with ``tasks/`` → relative to project_root
    - else → relative to ``tasks/``

    Verifies via ``os.path.realpath`` that the result is under the tasks/
    base directory. Raises ``SystemExit(1)`` on containment violation
    (defense-in-depth — the validator catches this pre-commit, but the
    script must not silently follow a symlink out of the tree).
    """
    if body_rel.startswith("tasks/"):
        candidate = project_root / body_rel
    else:
        candidate = base_tasks_dir / body_rel
    real_candidate = os.path.realpath(str(candidate))
    base_real = os.path.realpath(str(base_tasks_dir))
    if not (real_candidate == base_real or real_candidate.startswith(base_real + os.sep)):
        print(
            f"ERROR: body path escapes tasks/ base: "
            f"{_sanitize_log(body_rel)} -> {_sanitize_log(real_candidate)}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return Path(real_candidate)


def extract_body_sections(
    body_rel: str,
    base_tasks_dir: Path | None = None,
    project_root: Path | None = None,
) -> dict[str, str]:
    """Read the body file and split it into sections by ``^## `` headings.

    Returns a dict keyed by lowercased heading text:
        {"context": "...", "requirements": "...", "user ops (do these first)": "..."}

    Missing file is non-fatal (returns ``{}``) so a body whose tip moved
    doesn't break the whole skill — the caller will simply omit those sections
    in its output.

    Defaults are ``None`` (not module-level constants) so test monkey-patches
    of ``_TASKS_DIR`` / ``_REPO_ROOT`` take effect.
    """
    if base_tasks_dir is None:
        base_tasks_dir = _TASKS_DIR
    if project_root is None:
        project_root = _REPO_ROOT
    path = _resolve_body_path(body_rel, base_tasks_dir, project_root)
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    sections: dict[str, list[str]] = {}
    current_key: str | None = None
    current_buf: list[str] = []
    for line in text.splitlines():
        m = _BODY_SECTION_RE.match(line)
        if m:
            if current_key is not None:
                sections[current_key] = current_buf  # type: ignore[assignment]
            current_key = m.group("title").strip().lower()
            current_buf = []
            continue
        if current_key is not None:
            current_buf.append(line)
    if current_key is not None:
        sections[current_key] = current_buf  # type: ignore[assignment]

    return {k: "\n".join(v).strip() for k, v in sections.items()}


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------
def _slugify_for_branch(task_id: str) -> str:
    """Best-effort slug: lowercase the ID and replace runs of non-alnum with
    a single hyphen. Only used when ``branch:`` is missing from the entry.
    """
    s = task_id.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "task"


def _default_branch_prefix(task_id: str) -> str:
    if task_id.startswith("FEAT-"):
        return "feat/"
    if task_id.startswith("FIX-") or task_id.startswith("FIX_"):
        return "fix/"
    return "tech/"


def _format_deps_line(task: dict[str, Any]) -> str:
    deps = task.get("depends_on") or []
    if not deps:
        return "None"
    return ", ".join(str(d) for d in deps)


def _format_user_action_for_task(task: dict[str, Any], body_sections: dict[str, str]) -> str:
    if task.get("user_action"):
        for key in body_sections:
            if "user ops" in key:
                return body_sections[key]
        return "Yes — see body for steps"
    return "None — fully agent-executable"


def format_task_output(
    task: dict[str, Any],
    body_sections: dict[str, str],
    remaining_agent: int,
    remaining_batches: int,
    overlap_note: str = "",
) -> str:
    """Render the Step 7 'index task' markdown template.

    ``overlap_note`` (Phase 103, ``--avoid-inflight``) is a one-line collision
    advisory for the selected task; when non-empty it renders as an
    ``**In-flight overlap:**`` field. Empty on every default path — the field
    is omitted entirely, so the standard output is byte-for-byte unchanged.
    """
    tid = task["id"]
    title = task.get("title") or ""
    effort = task.get("effort") or "?"
    body_rel = task.get("body") or ""
    body_display = body_rel if body_rel.startswith("tasks/") else f"tasks/{body_rel}"
    user_action = "Yes" if task.get("user_action") else "No"

    # Branch suggestion: explicit branch: field wins, else derive.
    branch = task.get("branch")
    if not isinstance(branch, str) or not branch:
        branch = f"{_default_branch_prefix(tid)}{_slugify_for_branch(tid)}"

    context = body_sections.get("context", "").strip()
    requirements = body_sections.get("requirements", "").strip()
    user_ops_block = _format_user_action_for_task(task, body_sections)

    lines: list[str] = []
    lines.append("## Next Task")
    lines.append("")
    lines.append(f"### {tid} — {title}")
    lines.append("")
    lines.append(f"**Effort:** {effort}")
    lines.append(f"**Body:** `{body_display}`")
    lines.append(f"**User action required:** {user_action}")
    lines.append(f"**Depends on:** {_format_deps_line(task)}")
    if overlap_note:
        lines.append(f"**In-flight overlap:** {overlap_note}")
    lines.append("")
    if context:
        lines.append("**Context:**")
        lines.append(context)
        lines.append("")
    if requirements:
        lines.append("**Requirements:**")
        lines.append(requirements)
        lines.append("")
    lines.append("**User ops:**")
    lines.append(user_ops_block)
    lines.append("")
    lines.append(f"**Suggested branch name:** `{branch}`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        f"> Remaining in focus phase: {remaining_agent} open agent-executable "
        f"task(s), {remaining_batches} review batch(es) pending."
    )
    lines.append(f"> Claim: `/claim-task {tid}`")
    return "\n".join(lines) + "\n"


def _format_severity_breakdown(sev: dict[str, int]) -> str:
    parts: list[str] = []
    if sev.get("high"):
        parts.append(f"{sev['high']} {_SEVERITY_HIGH}")
    if sev.get("medium"):
        parts.append(f"{sev['medium']} {_SEVERITY_MEDIUM}")
    if sev.get("low"):
        parts.append(f"{sev['low']} {_SEVERITY_LOW}")
    return ", ".join(parts) if parts else "no severities tagged"


def format_batch_output(
    batch: dict[str, Any],
    remaining_agent: int,
    remaining_batches: int,
) -> str:
    """Render the Step 7 'review batch' markdown template."""
    n = batch["number"]
    title = batch.get("title") or ""
    effort = estimate_batch_effort(batch)
    needs_user, reasons = infer_batch_user_action(batch)
    sev_str = _format_severity_breakdown(batch.get("severity") or {})

    branch = batch.get("branch") or "(no branch recorded)"
    scope = batch.get("scope") or "(no scope recorded)"
    verify = batch.get("verify") or "(no verify recorded)"

    lines: list[str] = []
    lines.append("## Next Task")
    lines.append("")
    lines.append(f"### Review Batch {n} — {title}")
    lines.append("")
    lines.append(f"**Effort estimate:** {effort}")
    lines.append(
        f"**Tasks:** {batch.get('open_count', 0)} open ({sev_str})"
    )
    lines.append(f"**Scope:** {scope}")
    lines.append(f"**Branch:** `{branch}`")
    lines.append(f"**Verify:** `{verify}`")
    lines.append("")
    lines.append("**Task details:**")
    for t in batch.get("tasks") or []:
        box = "[ ]" if t["state"] == " " else f"[{t['state']}]"
        sev_suffix = f" {t['severity']}" if t.get("severity") else ""
        lines.append(f"- {box} **{t['task_id']}**: {t['rest']}{sev_suffix}")
    lines.append("")
    lines.append(f"**User action required:** {'Yes' if needs_user else 'No'}")
    if needs_user:
        for r in reasons:
            lines.append(f"- {r}")
    else:
        lines.append("None — fully agent-executable")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        f"> Remaining in focus phase: {remaining_agent} open agent-executable "
        f"task(s), {remaining_batches} review batch(es) pending."
    )
    lines.append(f"> Claim: `/claim-task {n}`")
    return "\n".join(lines) + "\n"


def format_user_action_fallback(
    user_action_pool: list[dict[str, Any]],
    remaining_batches: int,
) -> str:
    """When no agent-executable task remains but user_action:true tasks do,
    surface a short list per the Step 7 spec."""
    lines: list[str] = []
    lines.append("## Next Task")
    lines.append("")
    lines.append(
        "The agent-executable queue for the focus phase is drained. "
        "Remaining open tasks all require user action:"
    )
    lines.append("")
    for t in user_action_pool:
        lines.append(
            f"- **{t.get('id', '?')}** — {t.get('title', '')} "
            f"(effort: {t.get('effort', '?')})"
        )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        f"> Remaining in focus phase: 0 open agent-executable task(s), "
        f"{remaining_batches} review batch(es) pending."
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def _count_remaining(
    data: dict[str, Any],
    locks: set[str],
    focus_number: float | int,
    selected_id: str | None,
) -> int:
    """Count open agent-executable tasks (ready + user_action:false) in the
    focus phase, excluding ``selected_id``."""
    tasks = data.get("tasks") or []
    by_id = {t["id"]: t for t in tasks if isinstance(t, dict) and isinstance(t.get("id"), str)}
    count = 0
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if t.get("status") != "open":
            continue
        if t.get("phase") != focus_number:
            continue
        if t.get("on_hold_until"):
            continue
        if t.get("user_action"):
            continue
        tid = t.get("id")
        if not isinstance(tid, str) or tid in locks:
            continue
        if tid == selected_id:
            continue
        skip = False
        for dep in t.get("depends_on") or []:
            dep_task = by_id.get(dep)
            if not dep_task or dep_task.get("status") != "done":
                skip = True
                break
        if skip:
            continue
        count += 1
    return count


def _build_avoid_inflight(
    project_root: Path | None = None,
) -> tuple[Callable[[str], int] | None, Callable[[str], str] | None]:
    """Wire the scope-overlap primitive for ``--avoid-inflight`` (Phase 103).

    Returns ``(overlap_fn, note_for)``: ``overlap_fn(tid)`` yields a collision
    rank (0/1/2) for ``pick_next_task``'s sort, and ``note_for(tid)`` a one-line
    advisory for ``format_task_output``. Both share a per-workspace cache of the
    (expensive) git reads and a per-task assessment cache, so ranking N
    candidates costs at most one ``git diff`` per in-flight worktree.

    The import is lazy and failure is soft: if ``scope_overlap`` can't be
    imported (a minimal consumer, or a partial install), return ``(None, None)``
    after a one-line note and let the caller fall back to the ordinary ranking.
    This mirrors ``scope_overlap.py``'s own advisory-non-blocking stance — the
    overlay is a convenience, never a gate on selecting a task.
    """
    try:
        import scope_overlap as so
    except ImportError as e:
        print(
            f"WARN: --avoid-inflight unavailable ({_sanitize_log(str(e))}); "
            "falling back to the ordinary ranking.",
            file=sys.stderr,
        )
        return None, None

    wt_cache: dict[str, list[str]] = {}

    def reader(ws: str) -> list[str]:
        if ws not in wt_cache:
            wt_cache[ws] = so._worktree_changed_paths(ws)
        return wt_cache[ws]

    assess_cache: dict[str, Any] = {}

    def _assess(tid: str) -> Any:
        if tid not in assess_cache:
            assess_cache[tid] = so.assess(
                tid, project_root=project_root, worktree_reader=reader
            )
        return assess_cache[tid]

    def overlap_fn(tid: str) -> int:
        return _OVERLAP_RANK.get(_assess(tid).max_verdict, 0)

    def note_for(tid: str) -> str:
        a = _assess(tid)
        if a.in_flight_count == 0:
            return "no work in flight — nothing to collide with"
        if not a.overlaps:
            return f"none detected ({a.in_flight_count} task(s) in flight)"
        top = a.overlaps[0]
        label = "likely conflict" if top.verdict == "likely" else "possible overlap"
        shared = ", ".join(top.evidence[:3])
        if len(top.evidence) > 3:
            shared += f", +{len(top.evidence) - 3} more"
        extra = f" (+{len(a.overlaps) - 1} more in flight)" if len(a.overlaps) > 1 else ""
        return f"⚠ {label} with {top.task_id} at /review-close — shared: {shared}{extra}"

    return overlap_fn, note_for


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic /next-task: print the single next claimable task."
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="Skip the index scan; only surface the next pending review batch.",
    )
    parser.add_argument(
        "--avoid-inflight",
        action="store_true",
        help=(
            "Rank candidates by collision risk against work in flight, preferring "
            "tasks whose likely file scope won't conflict with an in-progress "
            "worktree at /review-close. Advisory; needs scripts/scope_overlap.py."
        ),
    )
    args = parser.parse_args(argv)

    data = load_index()
    _assert_schema_version(data, minimum=MIN_SCHEMA_VERSION)
    focus = find_focus_phase(data)
    focus_number = focus.get("number")
    if focus_number is None:
        print("ERROR: focus phase missing number field", file=sys.stderr)
        raise SystemExit(1)

    locks = list_locks()

    # Always parse review_tasks.md so we can populate the "remaining batches"
    # tail counter for both code paths. Missing file → empty list (lenient).
    review_text = ""
    if _REVIEW_PATH.is_file():
        try:
            review_text = _REVIEW_PATH.read_text(encoding="utf-8")
        except OSError as e:
            print(
                f"WARN: could not read {_REVIEW_PATH}: {_sanitize_log(str(e)[:500])}",
                file=sys.stderr,
            )
    batches = parse_review_batches(review_text) if review_text else []
    next_batch, total_pending = pick_next_batch(batches, locks)

    if args.review:
        if args.avoid_inflight:
            print(
                "NOTE: --avoid-inflight has no effect with --review — collision "
                "ranking applies to roadmap-task selection, not review batches "
                "(those are /auto-fix's domain, gated by review_tasks.md's "
                "Overlap: field).",
                file=sys.stderr,
            )
        if next_batch is None:
            print("No pending review batches.")
            return 0
        remaining_agent = _count_remaining(data, locks, focus_number, selected_id=None)
        # Pending count after surfacing this one:
        remaining_batches = max(0, total_pending - 1)
        sys.stdout.write(
            format_batch_output(next_batch, remaining_agent, remaining_batches)
        )
        return 0

    # --avoid-inflight: lazily wire the scope-overlap primitive. On import
    # failure both are None and selection/output degrade to their default shape.
    overlap_fn: Callable[[str], int] | None = None
    note_for: Callable[[str], str] | None = None
    if args.avoid_inflight:
        overlap_fn, note_for = _build_avoid_inflight(_REPO_ROOT)

    # Default mode: index first, then review.
    selected, user_action_pool = pick_next_task(
        data, locks, focus_number, overlap_fn=overlap_fn
    )
    if selected is not None:
        body_sections = extract_body_sections(selected.get("body") or "")
        remaining_agent = _count_remaining(
            data, locks, focus_number, selected_id=selected["id"]
        )
        overlap_note = note_for(selected["id"]) if note_for is not None else ""
        sys.stdout.write(
            format_task_output(
                selected, body_sections, remaining_agent, total_pending,
                overlap_note=overlap_note,
            )
        )
        return 0

    if next_batch is not None:
        remaining_agent = _count_remaining(data, locks, focus_number, selected_id=None)
        remaining_batches = max(0, total_pending - 1)
        sys.stdout.write(
            format_batch_output(next_batch, remaining_agent, remaining_batches)
        )
        return 0

    if user_action_pool:
        sys.stdout.write(
            format_user_action_fallback(user_action_pool, total_pending)
        )
        return 0

    print("No open tasks found in the current focus phase.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — top-level safety net
        print(f"ERROR: next_task.py crashed: {_sanitize_log(str(e)[:500])}", file=sys.stderr)
        sys.exit(2)
