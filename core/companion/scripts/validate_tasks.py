#!/usr/bin/env python3
"""Validate tasks/index.yml and per-task body files against the schema.

Enforces every invariant documented in tasks/schema.md. Designed to run in
pre-commit and from the migration script (via --path) for atomic-staging
validation.

Usage:
    python sysop/scripts/validate_tasks.py
    python sysop/scripts/validate_tasks.py --path tasks/
    python sysop/scripts/validate_tasks.py --quiet            # pre-commit mode
    python sysop/scripts/validate_tasks.py --self-test       # internal consistency check

Exits 0 on success, non-zero on any ERROR finding. Warnings (e.g., suspected
secrets) never affect exit code.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    # PyYAML lives only in the project venv on some consumers (BeanRider ISSUE-0049).
    # Resolve it from a CWD-relative venv before giving up, so a bare
    # `python3 sysop/scripts/validate_tasks.py` (the permission-clean, no-prefix invocation
    # that matches `Bash(python3 sysop/scripts/validate_tasks.py:*)`) works for venv-only
    # consumers too — mirrors the in-heredoc bootstrap the lifecycle skills use, and
    # frees callers from needing a `.venv/bin/python3` command word (Sysop Phase 126).
    import glob

    sys.path[:0] = glob.glob(".venv/lib/python*/site-packages")
    try:
        import yaml
    except ImportError:
        print(
            "ERROR: validate_tasks.py requires PyYAML. "
            "Install: pip install pyyaml  (or activate the project venv).",
            file=sys.stderr,
        )
        sys.exit(2)


# ---------------------------------------------------------------------------
# Local _sanitize_log — strips ANSI/control chars before logging untrusted
# strings (filesystem paths, YAML content, exception messages). Mirrors the
# project-side _sanitize_log helper that python-pack consumers ship under
# their <utility modules>/; redefined here so this script stays standalone
# and importable from a pre-commit hook before the project's venv activates.
# ---------------------------------------------------------------------------
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_CONTROL_RE = re.compile(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_log(value: object, max_len: int = 500) -> str:
    """Strip ANSI/control chars and truncate.

    Use this on every exception message and any value derived from external
    input (filesystem paths, YAML content) before printing.
    """
    text = str(value)
    text = _ANSI_ESCAPE_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    text = text.replace("\n", " ").replace("\r", " ").replace("\0", " ")
    if len(text) > max_len:
        text = text[:max_len] + "..."
    return text


# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------
# Decision 2 (Phase 16 handoff § 0): forward-compatible versioning. The
# validator accepts schema_version >= MIN_SCHEMA_VERSION; a consumer pinned
# to an older Sysop that adopts a newer tasks/index.yml from upstream is
# NOT rejected as "unknown version" for purely-additive schema changes. A
# breaking schema change bumps MIN_SCHEMA_VERSION AND requires a per-version
# code path in the validator (each supported major version must be explicitly
# understood). See core/companion/tasks/schema.md § Versioning.
MIN_SCHEMA_VERSION = 1
TASK_STATUSES = {"open", "in_progress", "done", "deferred"}
PHASE_STATUSES = {"done", "in_progress", "planned"}
EFFORT_VALUES = {"Low", "Medium", "High"}
# Phase 19: blast_radius captures task surface area (independent of effort).
# v1: optional; if present, enum is enforced. v2: required on open/in_progress
# (mirrors effort:'s required-status set). See tasks/schema.md § Blast radius
# + § Versioning.
BLAST_RADIUS_VALUES = {"single-file", "single-module", "cross-module", "architectural"}
BLAST_RADIUS_REQUIRED_FROM_VERSION = 2
BLAST_RADIUS_REQUIRED_STATUSES = {"open", "in_progress"}
WHITELIST_EXTERNAL_PREFIXES = ("BATCH-",)

# Module-scope regex compilation (per scripts convention)
_TASK_ID_RE = re.compile(r"^[A-Z][A-Z0-9-]{2,80}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BATCH_EXTERNAL_RE = re.compile(r"^BATCH-\d+$")
# Provenance sentinel allowed in surfaced_by (only): marks a task imported
# from a pre-Sysop backlog (roadmap file / issue tracker) by /onboard, whose
# effort/blast_radius are archaeological estimates rather than design-time
# signal. Lowercase, so it can never collide with a real task ID (_TASK_ID_RE
# requires a leading uppercase letter).
_IMPORTED_SENTINEL = "imported"
_PHASE_SUMMARY_RE = re.compile(r"^_phase_\d+\.md$")
_BODY_FIRST_HEADING_RE = re.compile(r"^#\s+([^\s#].*?)\s*$")

# Secret-scan patterns (warn-only). All module-scope.
_LONG_HEX_RE = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_SK_PREFIX_RE = re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")
_AWS_ACCESS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")

# Phase 35: manual_smoke heading-presence check (warn-only). Mirrors the
# regex /review-close Step 3c uses for signal detection, so an author who
# satisfies the validator's check also satisfies the skill's gate detection.
_MANUAL_SMOKE_HEADING_RE = re.compile(
    r"^#{1,6}\s+.*(manual\s+smoke|smoke\s+required)",
    re.IGNORECASE | re.MULTILINE,
)

# Phase 58b: test-decision heading-presence check (warn-only). A claimed
# (in_progress) task's plan records a `## Test decision` section in its body
# — either "test X proves Y" or "no test because Z". Heading-scan mirrors the
# manual_smoke pattern so the validator's nudge stays in lockstep with the
# body convention in tasks/schema.md § Test decision. Warn-only: the
# read-and-verify gate is /review-close (Phase 59), and absence must never
# block a commit.
_TEST_DECISION_HEADING_RE = re.compile(
    r"^#{1,6}\s+.*test\s+decision",
    re.IGNORECASE | re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    severity: str  # "ERROR" or "WARNING"
    location: str  # "<file>:<line>" or "<file>: <field>"
    message: str

    def format(self) -> str:
        return f"[{self.severity}] {self.location}: {self.message}"


def _git_discovery_env() -> dict[str, str]:
    """`os.environ` minus git's discovery vars (BeanRider ISSUE-0048).

    `GIT_DIR`/`GIT_WORK_TREE`/`GIT_COMMON_DIR`/`GIT_INDEX_FILE` take precedence
    over `git -C`, and git exports them into every hook — stripping them makes
    `-C` authoritative so a probe against a tmpdir resolves there, not the
    invoking repo. Duplicated verbatim in next_task.py and scope_overlap.py
    (same zero-dependency-duplicate rationale as _resolve_canonical_locks_dir).
    """
    return {
        k: v
        for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")
    }


def _resolve_canonical_locks_dir(project_root: Path) -> Path:
    """Resolve the canonical sysop/runtime/locks/ directory.

    Phase 32 (2026-05-22): locks always live under the main repo's `sysop/runtime/locks/`,
    discoverable via `git rev-parse --git-common-dir`. When invoked inside a
    worktree, this still returns the MAIN repo's `sysop/runtime/locks/` so callers from any
    working tree agree on one location (closes BeanRider ISSUE-0032).

    Falls back to `project_root / "sysop/runtime/locks"` when we cannot resolve git state
    (e.g., `--self-test` synthetic fixtures, atomic-staging callers running
    against a tmpdir outside any working tree). This preserves backward
    compatibility for non-git callers.

    Strips git's discovery env vars (BeanRider ISSUE-0048) so `-C
    <project_root>` is authoritative: `GIT_DIR`/`GIT_WORK_TREE` take
    precedence over `-C`, and git exports them (absolute, from a worktree)
    into every hook. Left inherited, the probe resolves against the invoking
    repo regardless of `project_root` — so `--self-test`'s tmpdir fixtures
    would resolve to the real repo's `sysop/runtime/locks/` and the documented fallback
    would never fire. Stripping them restores the fallback without changing
    the answer for real callers (discovery proceeds from `project_root`,
    which is what `-C` already intends; the Phase-32 cross-worktree
    guarantee is preserved).
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=_git_discovery_env(),
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return project_root / "sysop/runtime/locks"
    if result.returncode != 0:
        return project_root / "sysop/runtime/locks"
    raw = result.stdout.strip()
    if not raw:
        return project_root / "sysop/runtime/locks"
    common_dir = Path(raw)
    if not common_dir.is_absolute():
        common_dir = (project_root / common_dir).resolve()
    main_repo_root = common_dir.parent
    return main_repo_root / "sysop/runtime/locks"


@dataclass
class Report:
    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    task_count: int = 0
    phase_count: int = 0

    def error(self, location: str, message: str) -> None:
        self.errors.append(Finding("ERROR", location, message))

    def warn(self, location: str, message: str) -> None:
        self.warnings.append(Finding("WARNING", location, message))

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# Core validator
# ---------------------------------------------------------------------------
def validate(base_dir: Path, project_root: Path | None = None) -> Report:
    """Validate the tasks tree rooted at *base_dir*.

    *project_root* is the directory containing `sysop/runtime/locks/` (for in-progress lock
    checks). Defaults to the parent of *base_dir*.
    """
    report = Report()
    base_dir = Path(base_dir).resolve()
    if project_root is None:
        project_root = base_dir.parent
    project_root = Path(project_root).resolve()

    index_path = base_dir / "index.yml"
    if not index_path.is_file():
        report.error(str(index_path), "index.yml not found")
        return report

    # Invariant 1: parses with yaml.safe_load
    try:
        with open(index_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except yaml.YAMLError as e:
        report.error(str(index_path), f"YAML parse error: {_sanitize_log(str(e)[:500])}")
        return report
    except OSError as e:
        report.error(str(index_path), f"Cannot read: {_sanitize_log(str(e)[:500])}")
        return report

    if not isinstance(raw, dict):
        report.error(str(index_path), "top-level YAML must be a mapping")
        return report

    # Invariant 2: schema_version known (Decision 2: forward-compat — accept >= MIN)
    schema_version = raw.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        report.error(
            f"{index_path}: schema_version",
            f"schema_version must be an integer, got {_sanitize_log(type(schema_version).__name__)}",
        )
        return report
    if schema_version < MIN_SCHEMA_VERSION:
        report.error(
            f"{index_path}: schema_version",
            f"schema_version {schema_version} is older than supported minimum {MIN_SCHEMA_VERSION}; "
            "this index.yml predates the current Sysop schema.",
        )
        return report

    phases = raw.get("phases") or []
    tasks = raw.get("tasks") or []

    if not isinstance(phases, list):
        report.error(f"{index_path}: phases", "must be a list")
        return report
    if not isinstance(tasks, list):
        report.error(f"{index_path}: tasks", "must be a list")
        return report

    report.phase_count = len(phases)
    report.task_count = len(tasks)

    _validate_phases(phases, index_path, report)
    task_ids = _validate_tasks(
        tasks, base_dir, project_root, phases, index_path, schema_version, report
    )
    _validate_references(tasks, task_ids, index_path, report)
    _validate_orphans(base_dir, tasks, index_path, report)
    _scan_secrets(base_dir, report)

    return report


def _validate_phases(phases: list, index_path: Path, report: Report) -> None:
    """Invariants 5 + 8 (phase parts) + uniqueness of phase numbers."""
    current_focus_count = 0
    seen_numbers: set[int] = set()
    for idx, phase in enumerate(phases):
        loc = f"{index_path}: phases[{idx}]"
        if not isinstance(phase, dict):
            report.error(loc, "phase entry must be a mapping")
            continue

        number = phase.get("number")
        # bool is a subclass of int — reject it explicitly.
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            report.error(loc, f"phase 'number' must be int or float, got {_sanitize_log(type(number).__name__)}")
        else:
            if number in seen_numbers:
                report.error(loc, f"duplicate phase number {number}")
            seen_numbers.add(number)

        title = phase.get("title")
        if not isinstance(title, str) or not title.strip():
            report.error(loc, "phase 'title' must be a non-empty string")

        status = phase.get("status")
        if status not in PHASE_STATUSES:
            report.error(
                loc,
                f"phase 'status' must be one of {sorted(PHASE_STATUSES)}, got {_sanitize_log(status)}",
            )

        cf = phase.get("current_focus")
        if not isinstance(cf, bool):
            report.error(loc, f"phase 'current_focus' must be bool, got {_sanitize_log(type(cf).__name__)}")
        elif cf:
            current_focus_count += 1

    # Invariant 5: exactly one current_focus phase
    if current_focus_count != 1:
        report.error(
            f"{index_path}: phases",
            f"exactly one phase must have current_focus: true (found {current_focus_count})",
        )


def _validate_tasks(
    tasks: list,
    base_dir: Path,
    project_root: Path,
    phases: list,
    index_path: Path,
    schema_version: int,
    report: Report,
) -> set[str]:
    """Per-task validation (invariants 3, 7, 8, 9, 10) and ID matching.

    Returns the set of known task IDs (for downstream reference checks).
    """
    phase_numbers = {
        p.get("number")
        for p in phases
        if isinstance(p, dict)
        and isinstance(p.get("number"), (int, float))
        and not isinstance(p.get("number"), bool)
    }
    locks_dir = _resolve_canonical_locks_dir(project_root)
    base_tasks_real = os.path.realpath(base_dir)

    seen_ids: set[str] = set()
    task_ids: set[str] = set()

    for idx, task in enumerate(tasks):
        loc = f"{index_path}: tasks[{idx}]"
        if not isinstance(task, dict):
            report.error(loc, "task entry must be a mapping")
            continue

        tid = task.get("id")
        if not isinstance(tid, str) or not _TASK_ID_RE.match(tid):
            report.error(
                loc,
                f"task 'id' must match ^[A-Z][A-Z0-9-]{{2,80}}$, got {_sanitize_log(tid)}",
            )
            # We still proceed to surface as many downstream errors as we can.
            tid_for_use: str | None = tid if isinstance(tid, str) else None
        else:
            tid_for_use = tid

        # Invariant 7: unique IDs
        if tid_for_use is not None:
            if tid_for_use in seen_ids:
                report.error(loc, f"duplicate task id: {_sanitize_log(tid_for_use)}")
            else:
                seen_ids.add(tid_for_use)
            task_ids.add(tid_for_use)

        loc_id = f"{index_path}: tasks[{idx}] ({_sanitize_log(tid_for_use) if tid_for_use else '?'})"

        # phase
        phase = task.get("phase")
        if isinstance(phase, bool) or not isinstance(phase, (int, float)):
            report.error(loc_id, f"task 'phase' must be int or float, got {_sanitize_log(type(phase).__name__)}")
        elif phase not in phase_numbers:
            report.error(loc_id, f"task 'phase' {phase} does not match any phases[].number")

        # title
        title = task.get("title")
        if not isinstance(title, str) or not title.strip():
            report.error(loc_id, "task 'title' must be a non-empty string")

        # Invariant 8: status
        status = task.get("status")
        if status not in TASK_STATUSES:
            report.error(
                loc_id,
                f"task 'status' must be one of {sorted(TASK_STATUSES)}, got {_sanitize_log(status)}",
            )

        # depends_on / surfaced_by / whitelist must be lists if present
        for list_field in ("depends_on", "surfaced_by", "whitelist"):
            val = task.get(list_field)
            if val is not None and not isinstance(val, list):
                report.error(loc_id, f"'{list_field}' must be a list, got {_sanitize_log(type(val).__name__)}")

        # Invariant 10: status-field consistency
        _check_status_consistency(task, status, loc_id, report)

        # Phase 19: blast_radius (enum membership always when present;
        # required on open/in_progress at schema_version >= 2).
        _check_blast_radius(task, status, schema_version, loc_id, report)

        # Invariant 3: body path resolution
        # Schema says body is "relative path under tasks/" — accept either
        # "tasks/<...>" or a path already relative to project root.
        body = task.get("body")
        resolved_body_path: Path | None = None
        if isinstance(body, str) and body:
            if body.startswith("tasks/"):
                candidate = project_root / body
            else:
                candidate = base_dir / body
            real_candidate = os.path.realpath(str(candidate))
            if not real_candidate.startswith(base_tasks_real + os.sep) and real_candidate != base_tasks_real:
                report.error(
                    loc_id,
                    f"body path escapes tasks/ base: {_sanitize_log(body)} -> {_sanitize_log(real_candidate)}",
                )
            elif not os.path.isfile(real_candidate):
                report.error(loc_id, f"body file does not exist: {_sanitize_log(body)}")
            else:
                resolved_body_path = Path(real_candidate)
                _check_body_first_heading(resolved_body_path, tid_for_use, loc_id, report)

        # Phase 35: manual_smoke field — warn-only heading-presence check.
        _check_manual_smoke(task, resolved_body_path, loc_id, report)

        # Phase 58b: test-decision recording — warn-only, in_progress only.
        _check_test_decision(status, resolved_body_path, loc_id, report)

        # archive_summary similar containment check
        archive_summary = task.get("archive_summary")
        if isinstance(archive_summary, str) and archive_summary:
            if archive_summary.startswith("tasks/"):
                candidate = project_root / archive_summary
            else:
                candidate = base_dir / archive_summary
            real_candidate = os.path.realpath(str(candidate))
            if not real_candidate.startswith(base_tasks_real + os.sep) and real_candidate != base_tasks_real:
                report.error(
                    loc_id,
                    f"archive_summary path escapes tasks/ base: {_sanitize_log(archive_summary)}",
                )
            elif not os.path.isfile(real_candidate):
                report.error(loc_id, f"archive_summary file does not exist: {_sanitize_log(archive_summary)}")

        # Invariant 9: in_progress requires lock
        if status == "in_progress" and tid_for_use is not None:
            lock_path = locks_dir / f"{tid_for_use}.lock"
            if not lock_path.is_file():
                report.error(
                    loc_id,
                    f"status=in_progress but lock file missing at {lock_path}. "
                    "The canonical sysop/runtime/locks/ lives under the main repo root "
                    "(resolved via 'git rev-parse --git-common-dir'); re-run "
                    "`bash sysop/scripts/claim_task.sh --lock <TASK_ID> <BRANCH>` to "
                    "recreate it, or flip the task back to status=open.",
                )

    return task_ids


def _check_status_consistency(task: dict, status: object, loc: str, report: Report) -> None:
    """Invariant 10 — status-specific field requirements."""
    has_body = isinstance(task.get("body"), str) and task["body"]
    has_archive_summary = isinstance(task.get("archive_summary"), str) and task["archive_summary"]
    has_completed_date = isinstance(task.get("completed_date"), str) and task["completed_date"]
    has_effort = task.get("effort") in EFFORT_VALUES
    has_user_action = isinstance(task.get("user_action"), bool)

    if status in ("open", "in_progress", "deferred"):
        if not has_body:
            report.error(loc, f"status={status} requires 'body' field")

    if status in ("open", "in_progress"):
        if not has_effort:
            report.error(
                loc,
                f"status={status} requires 'effort' to be one of {sorted(EFFORT_VALUES)}, "
                f"got {_sanitize_log(task.get('effort'))}",
            )
        if not has_user_action:
            report.error(loc, f"status={status} requires 'user_action' (bool)")

    if status == "done":
        # completed_date is RECOMMENDED but not REQUIRED — migration imports
        # historical tasks whose completion dates have to be reconstructed via
        # git-blame backfill (sysop/scripts/backfill_completed_dates.py). New
        # completions written by /review-close MUST set a date; that contract
        # is enforced at the skill layer, not here.
        if has_completed_date and not _ISO_DATE_RE.match(task["completed_date"]):
            report.error(
                loc,
                f"'completed_date' must be ISO YYYY-MM-DD, got {_sanitize_log(task['completed_date'])}",
            )
        elif not has_completed_date:
            report.warn(loc, "status=done has no completed_date — git-blame backfill recommended")
        if not has_body and not has_archive_summary:
            report.error(
                loc,
                "status=done without 'body' requires 'archive_summary' pointing at tasks/archive/_phase_<N>.md",
            )
        # Invariant 10 extension (ISSUE-0009): status-vs-directory drift catch.
        # A done task's body must not live under open/ or deferred/. That state
        # is the silent half-migration produced when /review-close Step 4c's
        # status flip wrote but the corresponding `git mv` was skipped (e.g.,
        # by a stale prefix assumption in the rename heredoc). Accepts bodies
        # under archive/ (canonical) and at tasks/ root (flat layouts).
        if has_body:
            body_parts = task["body"].split("/")
            for stale_dir in ("open", "deferred"):
                if stale_dir in body_parts:
                    report.error(
                        loc,
                        f"status=done but body path contains '{stale_dir}/' segment "
                        f"({_sanitize_log(task['body'])}); a done task's body must live under "
                        "archive/ (or at tasks/ root). This is the half-migrated state "
                        "described in tasks/schema.md § Status-specific requirements.",
                    )
                    break


def _check_blast_radius(
    task: dict, status: object, schema_version: int, loc: str, report: Report
) -> None:
    """Phase 19: blast_radius field validation.

    - Whenever `blast_radius` is present (any status, any schema_version),
      it must be one of BLAST_RADIUS_VALUES — catches typos at v1 too.
    - At schema_version >= BLAST_RADIUS_REQUIRED_FROM_VERSION (2), tasks
      with status in {open, in_progress} must declare it. Mirrors how
      `effort:` is required for the same status set. Deferred/done tasks
      may omit it — same accommodation as Phase 16's `completed_date` on
      legacy done tasks (don't force backfill on history).
    """
    raw = task.get("blast_radius")
    present = raw is not None  # explicit None vs missing both treated as absent
    if present:
        if raw not in BLAST_RADIUS_VALUES:
            report.error(
                loc,
                f"'blast_radius' must be one of {sorted(BLAST_RADIUS_VALUES)}, "
                f"got {_sanitize_log(raw)}",
            )
        return

    if (
        schema_version >= BLAST_RADIUS_REQUIRED_FROM_VERSION
        and status in BLAST_RADIUS_REQUIRED_STATUSES
    ):
        report.error(
            loc,
            f"status={status} at schema_version>={BLAST_RADIUS_REQUIRED_FROM_VERSION} "
            f"requires 'blast_radius' (one of {sorted(BLAST_RADIUS_VALUES)}). "
            "See tasks/schema.md § Blast radius for value definitions.",
        )


def _check_manual_smoke(
    task: dict, body_path: Path | None, loc: str, report: Report
) -> None:
    """Phase 35 (BeanRider ISSUE-0008): when manual_smoke: true, the body
    should contain a heading matching the smoke pattern. Warn-only — the
    actual merge gate lives in /review-close Step 3c.

    - If `manual_smoke` is absent or `false`, no check fires.
    - If `manual_smoke` is present but not a bool, hard error (type guard).
    - If `manual_smoke: true` and body resolves but lacks the heading, warn.
    - If body did not resolve (missing/escaping path), skip — body-existence
      is checked elsewhere; don't double-report.
    """
    raw = task.get("manual_smoke")
    if raw is None:
        return
    if not isinstance(raw, bool):
        report.error(
            loc,
            f"'manual_smoke' must be bool, got {_sanitize_log(type(raw).__name__)}",
        )
        return
    if not raw:
        return
    if body_path is None or not body_path.is_file():
        return
    try:
        with open(body_path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return
    if not _MANUAL_SMOKE_HEADING_RE.search(text):
        report.warn(
            loc,
            "manual_smoke: true but body lacks a heading matching "
            "'manual smoke' or 'smoke required' (case-insensitive). "
            "Add the procedure under '## Manual smoke required' (or similar). "
            "See tasks/schema.md § Manual smoke.",
        )


def _check_test_decision(
    status: object, body_path: Path | None, loc: str, report: Report
) -> None:
    """Phase 58b: an in_progress task's body should record a `## Test decision`.

    The plan-time test decision ("test X proves Y" / "no test because Z") is
    written into the durable task body during /claim-task planning so that
    /review-close (Phase 59) can read it back at close time. This is a
    warn-only backstop — never a block — and fires only for in_progress tasks:

    - `open` tasks are backlog that predate claim-time planning, so the section
      legitimately doesn't exist yet (warning there would be pure noise);
    - `done` / `deferred` tasks are terminal or parked.

    Unlike manual_smoke there is no gating field to type-check: the section is
    expected on every claimed task, with "no test because Z" as the universal
    escape for non-behavior work. If the body did not resolve (missing/escaping
    path), skip — body-existence is checked elsewhere; don't double-report.
    """
    if status != "in_progress":
        return
    if body_path is None or not body_path.is_file():
        return
    try:
        with open(body_path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return
    if not _TEST_DECISION_HEADING_RE.search(text):
        report.warn(
            loc,
            "status=in_progress but body lacks a '## Test decision' section "
            "(heading containing 'test decision', case-insensitive). Record the "
            "plan's test decision in the body — 'test <X> proves <Y>' or "
            "'no test because <Z>' — so /review-close can verify it. "
            "See tasks/schema.md § Test decision.",
        )


def _check_body_first_heading(body_path: Path, task_id: str | None, loc: str, report: Report) -> None:
    """The first non-empty heading line of a body file must be `# <TASK-ID>`."""
    if task_id is None:
        return
    try:
        with open(body_path, "r", encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.rstrip("\n")
                if not line.strip():
                    continue
                m = _BODY_FIRST_HEADING_RE.match(line)
                if not m:
                    report.error(
                        f"{body_path}:1",
                        f"first non-empty line must be a level-1 heading '# {task_id}', got {_sanitize_log(line)}",
                    )
                    return
                heading_text = m.group(1).strip()
                if heading_text != task_id:
                    report.error(
                        f"{body_path}:1",
                        f"first heading must be '# {task_id}' (case-sensitive), got '# {_sanitize_log(heading_text)}'",
                    )
                return
        report.error(f"{body_path}:1", f"body file is empty (expected '# {task_id}')")
    except OSError as e:
        report.error(str(body_path), f"cannot read body file: {_sanitize_log(str(e)[:500])}")


def _validate_references(
    tasks: list, task_ids: set[str], index_path: Path, report: Report
) -> None:
    """Invariant 6: reference integrity for depends_on / surfaced_by / whitelist."""
    for idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            continue
        tid = task.get("id") if isinstance(task.get("id"), str) else "?"
        loc = f"{index_path}: tasks[{idx}] ({_sanitize_log(tid)})"

        for field_name, allow_external in (
            ("depends_on", False),
            ("surfaced_by", False),
            ("whitelist", True),
        ):
            refs = task.get(field_name)
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if not isinstance(ref, str):
                    report.error(loc, f"{field_name} entry must be a string, got {_sanitize_log(type(ref).__name__)}")
                    continue
                if ref in task_ids:
                    continue
                if allow_external and _BATCH_EXTERNAL_RE.match(ref):
                    continue
                if field_name == "surfaced_by" and ref == _IMPORTED_SENTINEL:
                    continue
                if allow_external:
                    extra = " (or external BATCH-NNN ref)"
                elif field_name == "surfaced_by":
                    extra = " (or the 'imported' provenance sentinel)"
                else:
                    extra = ""
                report.error(
                    loc,
                    f"{field_name} references unknown task id '{_sanitize_log(ref)}'{extra}",
                )


def _validate_orphans(base_dir: Path, tasks: list, index_path: Path, report: Report) -> None:
    """Invariant 4: every .md file under open/, deferred/, archive/ is indexed."""
    referenced: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for field_name in ("body", "archive_summary"):
            v = task.get(field_name)
            if isinstance(v, str) and v:
                # Normalize to realpath for comparison.
                if v.startswith("tasks/"):
                    candidate = base_dir.parent / v
                else:
                    candidate = base_dir / v
                referenced.add(os.path.realpath(str(candidate)))

    for sub in ("open", "deferred", "archive"):
        sub_dir = base_dir / sub
        if not sub_dir.is_dir():
            continue
        for md in sub_dir.glob("*.md"):
            # Phase summaries (e.g., _phase_6.md) only need to be referenced
            # by archive_summary, which is already in `referenced`.
            real = os.path.realpath(str(md))
            if real in referenced:
                continue
            if sub == "archive" and _PHASE_SUMMARY_RE.match(md.name):
                report.error(
                    f"{md}:1",
                    "phase summary file is not referenced by any task's archive_summary",
                )
            else:
                report.error(
                    f"{md}:1",
                    "orphan body file — not referenced by any task in index.yml",
                )


def _scan_secrets(base_dir: Path, report: Report) -> None:
    """Invariant 11: warn-only secret pattern scan of tasks/**/*.md."""
    for md in base_dir.rglob("*.md"):
        try:
            with open(md, "r", encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, start=1):
                    _check_secret_line(md, lineno, line, report)
        except OSError as e:
            report.warn(str(md), f"could not scan for secrets: {_sanitize_log(str(e)[:500])}")


def _check_secret_line(path: Path, lineno: int, line: str, report: Report) -> None:
    if _AWS_ACCESS_KEY_RE.search(line):
        report.warn(f"{path}:{lineno}", "matches AWS access key pattern (AKIA...)")
    if _SK_PREFIX_RE.search(line):
        report.warn(f"{path}:{lineno}", "matches sk- prefixed token pattern")
    # Long hex check last because it's the noisiest.
    if _LONG_HEX_RE.search(line):
        report.warn(f"{path}:{lineno}", "contains long hex string (>=32 chars)")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def render(report: Report, quiet: bool) -> None:
    if not quiet or not report.ok:
        for f in report.errors:
            print(f.format())
        for f in report.warnings:
            print(f.format())

    if report.ok and not quiet:
        print(
            f"OK: {report.task_count} tasks across {report.phase_count} phases, "
            f"0 errors, {len(report.warnings)} warnings"
        )
    elif not report.ok:
        # Always print a summary line on failure, even in quiet mode.
        print(
            f"FAIL: {report.task_count} tasks across {report.phase_count} phases, "
            f"{len(report.errors)} errors, {len(report.warnings)} warnings"
        )


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
_VALID_INDEX = """\
schema_version: 1

phases:
  - number: 1
    title: "Done phase"
    status: done
    current_focus: false
  - number: 2
    title: "Active phase"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-ALPHA
    title: "Alpha task"
    phase: 2
    status: open
    effort: Medium
    blast_radius: single-module
    user_action: false
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-ALPHA.md

  - id: TECH-BETA
    title: "Beta task"
    phase: 2
    status: open
    effort: Low
    blast_radius: single-file
    user_action: true
    depends_on: [FEAT-ALPHA]
    surfaced_by: []
    whitelist: [BATCH-42]
    body: tasks/open/TECH-BETA.md

  - id: FEAT-DONE
    title: "Done task (blast_radius intentionally omitted — legacy done is exempt)"
    phase: 1
    status: done
    completed_date: "2026-01-15"
    archive_summary: tasks/archive/_phase_1.md
"""

_VALID_BODY_ALPHA = """\
# FEAT-ALPHA

## Context
Alpha.
"""

_VALID_BODY_BETA = """\
# TECH-BETA

## Context
Beta.
"""

_VALID_PHASE_SUMMARY = """\
# Phase 1 summary

Done.
"""

_BAD_INDEX = """\
schema_version: 1

phases:
  - number: 1
    title: "P1"
    status: in_progress
    current_focus: true
  - number: 2
    title: "P2"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-DUP
    title: "Dup 1"
    phase: 1
    status: open
    effort: Medium
    user_action: false
    depends_on: [FEAT-MISSING]
    surfaced_by: []
    body: tasks/open/FEAT-DUP.md

  - id: FEAT-DUP
    title: "Dup 2"
    phase: 1
    status: open
    effort: Medium
    user_action: false
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-DUP.md
"""

_BAD_BODY = """\
# FEAT-DUP

body.
"""

# Drifted-status fixture (ISSUE-0009): a done task whose body still lives under
# open/ — the half-migrated state Step 4c's prefix-agnostic heredoc + this
# validator invariant prevent from shipping.
_DRIFTED_STATUS_INDEX = """\
schema_version: 1

phases:
  - number: 1
    title: "P1"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-DRIFT
    title: "Drifted task"
    phase: 1
    status: done
    completed_date: "2026-05-14"
    body: tasks/open/FEAT-DRIFT.md
"""

_DRIFTED_STATUS_BODY = """\
# FEAT-DRIFT

drift.
"""

# Phase 19 fixtures — blast_radius v1-optional / v2-required contract.
_BLAST_RADIUS_V1_OPTIONAL_INDEX = """\
schema_version: 1

phases:
  - number: 1
    title: "Active phase"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-WITH-BR
    title: "Task that declares blast_radius"
    phase: 1
    status: open
    effort: Medium
    blast_radius: single-file
    user_action: false
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-WITH-BR.md

  - id: FEAT-NO-BR
    title: "Task that omits blast_radius (legal at v1)"
    phase: 1
    status: open
    effort: Low
    user_action: false
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-NO-BR.md
"""

_BLAST_RADIUS_V1_BODY_WITH = """\
# FEAT-WITH-BR

br set.
"""

_BLAST_RADIUS_V1_BODY_WITHOUT = """\
# FEAT-NO-BR

br omitted.
"""

_BLAST_RADIUS_V2_REQUIRED_INDEX = """\
schema_version: 2

phases:
  - number: 1
    title: "Active phase"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-V2
    title: "v2 task with blast_radius"
    phase: 1
    status: open
    effort: Medium
    blast_radius: cross-module
    user_action: false
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-V2.md
"""

_BLAST_RADIUS_V2_BODY = """\
# FEAT-V2

v2.
"""

_BLAST_RADIUS_V2_MISSING_INDEX = """\
schema_version: 2

phases:
  - number: 1
    title: "Active phase"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-MISSING-BR
    title: "v2 open task missing blast_radius (should fail)"
    phase: 1
    status: open
    effort: Medium
    user_action: false
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-MISSING-BR.md
"""

_BLAST_RADIUS_V2_MISSING_BODY = """\
# FEAT-MISSING-BR

missing br.
"""

_BLAST_RADIUS_BAD_VALUE_INDEX = """\
schema_version: 1

phases:
  - number: 1
    title: "Active phase"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-BAD-BR
    title: "Task with out-of-enum blast_radius (must fail at v1 too)"
    phase: 1
    status: open
    effort: Medium
    blast_radius: enormous
    user_action: false
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-BAD-BR.md
"""

_BLAST_RADIUS_BAD_BODY = """\
# FEAT-BAD-BR

bad br.
"""

# Phase 35 fixtures — manual_smoke field warn-only heading-presence check.
_MANUAL_SMOKE_INDEX = """\
schema_version: 1

phases:
  - number: 1
    title: "Active phase"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-SMOKE-WITH
    title: "Smoke task with documented heading"
    phase: 1
    status: open
    effort: Medium
    user_action: false
    manual_smoke: true
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-SMOKE-WITH.md

  - id: FEAT-SMOKE-WITHOUT
    title: "Smoke task missing heading (should warn)"
    phase: 1
    status: open
    effort: Medium
    user_action: false
    manual_smoke: true
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-SMOKE-WITHOUT.md

  - id: FEAT-NO-SMOKE
    title: "Task without manual_smoke (no check fires)"
    phase: 1
    status: open
    effort: Low
    user_action: false
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-NO-SMOKE.md
"""

_MANUAL_SMOKE_BODY_WITH = """\
# FEAT-SMOKE-WITH

## Context
needs a browser smoke.

## Manual smoke required
1. Open localhost:3000/...
2. Verify thing.
"""

_MANUAL_SMOKE_BODY_WITHOUT = """\
# FEAT-SMOKE-WITHOUT

## Context
manual_smoke set but no smoke heading.
"""

_MANUAL_SMOKE_BODY_PLAIN = """\
# FEAT-NO-SMOKE

## Context
nothing special.
"""

_MANUAL_SMOKE_BAD_TYPE_INDEX = """\
schema_version: 1

phases:
  - number: 1
    title: "Active phase"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-SMOKE-BADTYPE
    title: "manual_smoke is a string, not bool — should hard-fail"
    phase: 1
    status: open
    effort: Low
    user_action: false
    manual_smoke: "yes"
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-SMOKE-BADTYPE.md
"""

_MANUAL_SMOKE_BAD_TYPE_BODY = """\
# FEAT-SMOKE-BADTYPE

## Manual smoke required
yes.
"""

# Phase 58b fixtures — test-decision recording warn-only check (in_progress only).
_TEST_DECISION_INDEX = """\
schema_version: 1

phases:
  - number: 1
    title: "Active phase"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-TD-WITH
    title: "In-progress task that records a test decision"
    phase: 1
    status: in_progress
    effort: Medium
    user_action: false
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-TD-WITH.md

  - id: FEAT-TD-WITHOUT
    title: "In-progress task missing the section (should warn)"
    phase: 1
    status: in_progress
    effort: Medium
    user_action: false
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-TD-WITHOUT.md

  - id: FEAT-TD-OPEN
    title: "Open task missing the section (must NOT warn — not yet claimed)"
    phase: 1
    status: open
    effort: Low
    user_action: false
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-TD-OPEN.md
"""

_TEST_DECISION_BODY_WITH = """\
# FEAT-TD-WITH

## Context
Adds a guard.

## Test decision
test test_guard_rejects_empty proves the new guard raises on empty input.
"""

_TEST_DECISION_BODY_WITHOUT = """\
# FEAT-TD-WITHOUT

## Context
in_progress but no recorded test decision.
"""

_TEST_DECISION_BODY_OPEN = """\
# FEAT-TD-OPEN

## Context
Backlog item, not yet claimed/planned.
"""


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(content)


def _build_valid_fixture(root: Path) -> Path:
    tasks_dir = root / "tasks"
    _write(tasks_dir / "index.yml", _VALID_INDEX)
    _write(tasks_dir / "open" / "FEAT-ALPHA.md", _VALID_BODY_ALPHA)
    _write(tasks_dir / "open" / "TECH-BETA.md", _VALID_BODY_BETA)
    _write(tasks_dir / "archive" / "_phase_1.md", _VALID_PHASE_SUMMARY)
    (root / "sysop/runtime/locks").mkdir(parents=True, exist_ok=True)
    return tasks_dir


def _build_bad_fixture(root: Path) -> Path:
    tasks_dir = root / "tasks"
    _write(tasks_dir / "index.yml", _BAD_INDEX)
    _write(tasks_dir / "open" / "FEAT-DUP.md", _BAD_BODY)
    (root / "sysop/runtime/locks").mkdir(parents=True, exist_ok=True)
    return tasks_dir


def _build_drifted_status_fixture(root: Path) -> Path:
    """ISSUE-0009: status=done with body under open/ must fail validation."""
    tasks_dir = root / "tasks"
    _write(tasks_dir / "index.yml", _DRIFTED_STATUS_INDEX)
    _write(tasks_dir / "open" / "FEAT-DRIFT.md", _DRIFTED_STATUS_BODY)
    (root / "sysop/runtime/locks").mkdir(parents=True, exist_ok=True)
    return tasks_dir


def _build_blast_radius_v1_optional_fixture(root: Path) -> Path:
    """Phase 19: at schema_version 1, blast_radius is optional. Both tasks pass."""
    tasks_dir = root / "tasks"
    _write(tasks_dir / "index.yml", _BLAST_RADIUS_V1_OPTIONAL_INDEX)
    _write(tasks_dir / "open" / "FEAT-WITH-BR.md", _BLAST_RADIUS_V1_BODY_WITH)
    _write(tasks_dir / "open" / "FEAT-NO-BR.md", _BLAST_RADIUS_V1_BODY_WITHOUT)
    (root / "sysop/runtime/locks").mkdir(parents=True, exist_ok=True)
    return tasks_dir


def _build_blast_radius_v2_required_fixture(root: Path) -> Path:
    """Phase 19: at schema_version 2, blast_radius on open task is required + valid."""
    tasks_dir = root / "tasks"
    _write(tasks_dir / "index.yml", _BLAST_RADIUS_V2_REQUIRED_INDEX)
    _write(tasks_dir / "open" / "FEAT-V2.md", _BLAST_RADIUS_V2_BODY)
    (root / "sysop/runtime/locks").mkdir(parents=True, exist_ok=True)
    return tasks_dir


def _build_blast_radius_v2_missing_fixture(root: Path) -> Path:
    """Phase 19: at schema_version 2, open task missing blast_radius must fail."""
    tasks_dir = root / "tasks"
    _write(tasks_dir / "index.yml", _BLAST_RADIUS_V2_MISSING_INDEX)
    _write(tasks_dir / "open" / "FEAT-MISSING-BR.md", _BLAST_RADIUS_V2_MISSING_BODY)
    (root / "sysop/runtime/locks").mkdir(parents=True, exist_ok=True)
    return tasks_dir


def _build_blast_radius_bad_value_fixture(root: Path) -> Path:
    """Phase 19: an out-of-enum blast_radius must fail at v1 too (enum is always enforced when present)."""
    tasks_dir = root / "tasks"
    _write(tasks_dir / "index.yml", _BLAST_RADIUS_BAD_VALUE_INDEX)
    _write(tasks_dir / "open" / "FEAT-BAD-BR.md", _BLAST_RADIUS_BAD_BODY)
    (root / "sysop/runtime/locks").mkdir(parents=True, exist_ok=True)
    return tasks_dir


def _build_manual_smoke_fixture(root: Path) -> Path:
    """Phase 35: manual_smoke heading-presence warn-only check + no-field control."""
    tasks_dir = root / "tasks"
    _write(tasks_dir / "index.yml", _MANUAL_SMOKE_INDEX)
    _write(tasks_dir / "open" / "FEAT-SMOKE-WITH.md", _MANUAL_SMOKE_BODY_WITH)
    _write(tasks_dir / "open" / "FEAT-SMOKE-WITHOUT.md", _MANUAL_SMOKE_BODY_WITHOUT)
    _write(tasks_dir / "open" / "FEAT-NO-SMOKE.md", _MANUAL_SMOKE_BODY_PLAIN)
    (root / "sysop/runtime/locks").mkdir(parents=True, exist_ok=True)
    return tasks_dir


def _build_manual_smoke_bad_type_fixture(root: Path) -> Path:
    """Phase 35: manual_smoke field with non-bool type is a hard error."""
    tasks_dir = root / "tasks"
    _write(tasks_dir / "index.yml", _MANUAL_SMOKE_BAD_TYPE_INDEX)
    _write(tasks_dir / "open" / "FEAT-SMOKE-BADTYPE.md", _MANUAL_SMOKE_BAD_TYPE_BODY)
    (root / "sysop/runtime/locks").mkdir(parents=True, exist_ok=True)
    return tasks_dir


def _build_test_decision_fixture(root: Path) -> Path:
    """Phase 58b: test-decision warn-only check fires only for in_progress.

    Two in_progress tasks need locks (invariant 9 is resolved against
    root/sysop/runtime/locks since the tmpdir is not a git repo — see
    _resolve_canonical_locks_dir's fallback). The open task needs none.
    """
    tasks_dir = root / "tasks"
    _write(tasks_dir / "index.yml", _TEST_DECISION_INDEX)
    _write(tasks_dir / "open" / "FEAT-TD-WITH.md", _TEST_DECISION_BODY_WITH)
    _write(tasks_dir / "open" / "FEAT-TD-WITHOUT.md", _TEST_DECISION_BODY_WITHOUT)
    _write(tasks_dir / "open" / "FEAT-TD-OPEN.md", _TEST_DECISION_BODY_OPEN)
    locks = root / "sysop/runtime/locks"
    locks.mkdir(parents=True, exist_ok=True)
    _write(locks / "FEAT-TD-WITH.lock", "lock\n")
    _write(locks / "FEAT-TD-WITHOUT.lock", "lock\n")
    return tasks_dir


def _build_forward_compat_fixture(root: Path) -> Path:
    """Decision 2: schema_version > MIN_SCHEMA_VERSION must be accepted."""
    tasks_dir = root / "tasks"
    _write(tasks_dir / "index.yml", _VALID_INDEX.replace("schema_version: 1", "schema_version: 2", 1))
    _write(tasks_dir / "open" / "FEAT-ALPHA.md", _VALID_BODY_ALPHA)
    _write(tasks_dir / "open" / "TECH-BETA.md", _VALID_BODY_BETA)
    _write(tasks_dir / "archive" / "_phase_1.md", _VALID_PHASE_SUMMARY)
    (root / "sysop/runtime/locks").mkdir(parents=True, exist_ok=True)
    return tasks_dir


def _self_test() -> int:
    print("Running validator self-test...")
    failures: list[str] = []

    # Valid fixture
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tasks_dir = _build_valid_fixture(root)
        report = validate(tasks_dir, project_root=root)
        if not report.ok:
            failures.append("valid fixture failed validation:")
            for f in report.errors:
                failures.append("  " + f.format())
        else:
            print("  valid fixture: OK")

    # Forward-compat fixture (Decision 2): schema_version: 2 must also pass.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tasks_dir = _build_forward_compat_fixture(root)
        report = validate(tasks_dir, project_root=root)
        if not report.ok:
            failures.append("forward-compat fixture (schema_version: 2) failed validation:")
            for f in report.errors:
                failures.append("  " + f.format())
        else:
            print("  forward-compat fixture (schema_version: 2): OK")

    # Bad fixture
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tasks_dir = _build_bad_fixture(root)
        report = validate(tasks_dir, project_root=root)
        if report.ok:
            failures.append("bad fixture passed validation (expected failure)")
        else:
            messages = " | ".join(f.message for f in report.errors)
            expected_substrings = [
                "duplicate task id",
                "depends_on references unknown task id 'FEAT-MISSING'",
                "exactly one phase must have current_focus: true",
            ]
            missing = [s for s in expected_substrings if s not in messages]
            if missing:
                failures.append(
                    "bad fixture failed but missing expected errors: " + ", ".join(missing)
                )
                failures.append("  actual errors:")
                for f in report.errors:
                    failures.append("    " + f.format())
            else:
                print("  bad fixture: correctly rejected with expected errors")

    # Drifted-status fixture (ISSUE-0009): status=done with body under open/.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tasks_dir = _build_drifted_status_fixture(root)
        report = validate(tasks_dir, project_root=root)
        if report.ok:
            failures.append("drifted-status fixture passed validation (expected failure)")
        else:
            messages = " | ".join(f.message for f in report.errors)
            if "status=done but body path contains 'open/' segment" not in messages:
                failures.append(
                    "drifted-status fixture failed but missing the status-vs-directory error"
                )
                failures.append("  actual errors:")
                for f in report.errors:
                    failures.append("    " + f.format())
            else:
                print("  drifted-status fixture (ISSUE-0009): correctly rejected")

    # Phase 19: blast_radius v1-optional fixture — both with/without pass.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tasks_dir = _build_blast_radius_v1_optional_fixture(root)
        report = validate(tasks_dir, project_root=root)
        if not report.ok:
            failures.append("blast_radius v1-optional fixture failed validation:")
            for f in report.errors:
                failures.append("  " + f.format())
        else:
            print("  blast_radius v1-optional fixture (Phase 19): OK")

    # Phase 19: blast_radius v2-required fixture — passes with valid value.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tasks_dir = _build_blast_radius_v2_required_fixture(root)
        report = validate(tasks_dir, project_root=root)
        if not report.ok:
            failures.append("blast_radius v2-required fixture failed validation:")
            for f in report.errors:
                failures.append("  " + f.format())
        else:
            print("  blast_radius v2-required fixture (Phase 19): OK")

    # Phase 19: blast_radius v2-missing fixture — must fail with clear message.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tasks_dir = _build_blast_radius_v2_missing_fixture(root)
        report = validate(tasks_dir, project_root=root)
        if report.ok:
            failures.append("blast_radius v2-missing fixture passed (expected failure)")
        else:
            messages = " | ".join(f.message for f in report.errors)
            if "requires 'blast_radius'" not in messages:
                failures.append(
                    "blast_radius v2-missing fixture failed but missing the requires-blast_radius error"
                )
                failures.append("  actual errors:")
                for f in report.errors:
                    failures.append("    " + f.format())
            else:
                print("  blast_radius v2-missing fixture (Phase 19): correctly rejected")

    # Phase 19: blast_radius bad-value fixture — out-of-enum must fail even at v1.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tasks_dir = _build_blast_radius_bad_value_fixture(root)
        report = validate(tasks_dir, project_root=root)
        if report.ok:
            failures.append("blast_radius bad-value fixture passed (expected failure)")
        else:
            messages = " | ".join(f.message for f in report.errors)
            if "'blast_radius' must be one of" not in messages:
                failures.append(
                    "blast_radius bad-value fixture failed but missing the enum-membership error"
                )
                failures.append("  actual errors:")
                for f in report.errors:
                    failures.append("    " + f.format())
            else:
                print("  blast_radius bad-value fixture (Phase 19): correctly rejected")

    # Phase 35: manual_smoke heading-presence — must PASS validation overall
    # (warn-only) AND must emit a warning naming FEAT-SMOKE-WITHOUT, AND must
    # NOT emit a warning naming FEAT-SMOKE-WITH or FEAT-NO-SMOKE.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tasks_dir = _build_manual_smoke_fixture(root)
        report = validate(tasks_dir, project_root=root)
        if not report.ok:
            failures.append("manual_smoke fixture failed validation (warn-only check must not block):")
            for f in report.errors:
                failures.append("  " + f.format())
        else:
            warn_blob = " | ".join(f.format() for f in report.warnings)
            missing_warn = "FEAT-SMOKE-WITHOUT" not in warn_blob or "manual_smoke: true but body lacks" not in warn_blob
            spurious_warn = (
                "FEAT-SMOKE-WITH " in warn_blob and "manual_smoke" in warn_blob
            ) or (
                "FEAT-NO-SMOKE" in warn_blob and "manual_smoke" in warn_blob
            )
            if missing_warn:
                failures.append("manual_smoke fixture missing expected warning for FEAT-SMOKE-WITHOUT")
                failures.append("  actual warnings:")
                for f in report.warnings:
                    failures.append("    " + f.format())
            elif spurious_warn:
                failures.append("manual_smoke fixture has spurious warning on a task that should not warn")
                failures.append("  actual warnings:")
                for f in report.warnings:
                    failures.append("    " + f.format())
            else:
                print("  manual_smoke fixture (Phase 35): correctly warned (warn-only)")

    # Phase 35: manual_smoke with non-bool type — hard error.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tasks_dir = _build_manual_smoke_bad_type_fixture(root)
        report = validate(tasks_dir, project_root=root)
        if report.ok:
            failures.append("manual_smoke bad-type fixture passed (expected failure)")
        else:
            messages = " | ".join(f.message for f in report.errors)
            if "'manual_smoke' must be bool" not in messages:
                failures.append("manual_smoke bad-type fixture failed but missing the type error")
                failures.append("  actual errors:")
                for f in report.errors:
                    failures.append("    " + f.format())
            else:
                print("  manual_smoke bad-type fixture (Phase 35): correctly rejected")

    # Phase 58b: test-decision recording — an in_progress body missing the
    # `## Test decision` section must WARN (warn-only; overall validation must
    # still PASS) and name FEAT-TD-WITHOUT, must NOT warn for FEAT-TD-WITH
    # (section present) or FEAT-TD-OPEN (open status — not yet claimed).
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tasks_dir = _build_test_decision_fixture(root)
        report = validate(tasks_dir, project_root=root)
        if not report.ok:
            failures.append("test-decision fixture failed validation (warn-only check must not block):")
            for f in report.errors:
                failures.append("  " + f.format())
        else:
            warn_blob = " | ".join(f.format() for f in report.warnings)
            missing_warn = (
                "(FEAT-TD-WITHOUT)" not in warn_blob or "Test decision" not in warn_blob
            )
            spurious_warn = (
                "(FEAT-TD-WITH)" in warn_blob and "Test decision" in warn_blob
            ) or (
                "(FEAT-TD-OPEN)" in warn_blob and "Test decision" in warn_blob
            )
            if missing_warn:
                failures.append("test-decision fixture missing expected warning for FEAT-TD-WITHOUT")
                failures.append("  actual warnings:")
                for f in report.warnings:
                    failures.append("    " + f.format())
            elif spurious_warn:
                failures.append("test-decision fixture has spurious warning on a task that should not warn")
                failures.append("  actual warnings:")
                for f in report.warnings:
                    failures.append("    " + f.format())
            else:
                print("  test-decision fixture (Phase 58b): correctly warned (warn-only)")

    if failures:
        print("SELF-TEST FAILED:")
        for line in failures:
            print(line)
        return 1
    print("SELF-TEST OK")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def _default_tasks_dir() -> Path:
    # <repo>/sysop/scripts/validate_tasks.py → <repo>/tasks (Phase 128).
    return Path(__file__).resolve().parents[2] / "tasks"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate tasks/index.yml and per-task body files."
    )
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="Path to a tasks/ directory (default: <repo>/tasks). Used by the "
        "migration script for atomic-staging validation.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print on failure (suitable for pre-commit hooks).",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run internal consistency check against synthetic fixtures.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()

    base_dir = Path(args.path).resolve() if args.path else _default_tasks_dir()
    if not base_dir.is_dir():
        print(f"ERROR: tasks directory not found: {base_dir}")
        return 2

    # By convention, project_root is the parent of tasks/, but when --path is
    # used for atomic staging, the sysop/runtime/locks/ check would not apply (the staged
    # tree has no lock state). We still try to resolve relative to the parent.
    project_root = base_dir.parent

    try:
        report = validate(base_dir, project_root=project_root)
    except Exception as e:  # noqa: BLE001 — top-level safety net
        # Sanitize before printing in case the exception message embeds paths
        # or other untrusted strings.
        print(f"ERROR: validator crashed: {_sanitize_log(str(e)[:500])}")
        return 2

    render(report, quiet=args.quiet)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
