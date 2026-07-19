#!/usr/bin/env python3
"""Scope-overlap primitive for collision-aware claiming (Phase 102).

Given a *candidate* task id and the *in-progress set* (locks + worktrees),
return per in-flight task an overlap verdict — ``likely`` / ``possible`` /
``none`` — plus the evidence (which paths matched). The shared dependency for
both consumer legs of the collision-aware-claiming feature:

  Leg A  ``/claim-task`` Step 2 — a claim-time advisory (this ships in
         Phase 102).
  Leg B  ``/auto-build`` in-flight batch awareness (a fast follow).

Building the same inference twice would itself be a collision (and would drift
like the ``_sanitize_log`` copies did before Phase 68), so both legs call this
one helper rather than re-deriving the logic in skill prose.

Design stance — **advisory, not blocking.** Overlap is a rework cost (the
worktrees kept the builds isolated; a collision surfaces as a recoverable merge
conflict at ``/review-close``), not a data-loss risk. So this tool *warns* and
lets the human decide; it never forbids a claim, and — critically — it **never
breaks the caller's flow**: every normal or degraded path exits 0 (missing
index, absent PyYAML, no in-flight work, an unreadable worktree all degrade to
a note, not a failure). Only an unexpected crash exits non-zero (2). This is
the deliberate contrast with ``next_task.py`` (which exits 1 on invariant
violations because it *is* the operation, not an advisory feeding one).

Two asymmetric scope sources — the load-bearing insight:

- **The candidate's scope is a guess** — it hasn't been planned yet. Inferred,
  lowest-effort-first, from declared signals only (never by planning the task):
  the ``## Key files`` section of the body, then ``blast_radius`` as a coarse
  magnitude hint. Never fabricate paths (Phase 58a discipline). A ``none``
  verdict means "no declared overlap," NOT "provably safe."
- **An in-flight task's scope is a fact** — it is actively building in a
  worktree, so read the real changed set with
  ``git -C <worktree> diff --name-only main...HEAD`` (plus uncommitted).
  Fall back to the lock's ``files_impacted:``, then the body's ``## Key files``,
  when the worktree diff is empty or unreadable.

Usage:
    python3 sysop/scripts/scope_overlap.py <CANDIDATE_ID>            # text advisory
    python3 sysop/scripts/scope_overlap.py <CANDIDATE_ID> --json     # structured

Exit codes:
    0   assessment completed (including every "couldn't assess" degrade path)
    2   unexpected exception (top-level safety net)

``_sanitize_log`` and ``_resolve_canonical_locks_dir`` are duplicated from
``validate_tasks.py`` / ``next_task.py`` (not imported) so this tool matches
the standalone-runnable scripts-tier shape and stays trivially testable in
isolation. Keep them in sync.
"""
from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants & module-scope regex (precompile at module load, per convention).
# ---------------------------------------------------------------------------
# git shell-out ceiling — a single worktree diff should be near-instant; the
# timeout only guards a wedged git process from hanging the advisory.
_GIT_TIMEOUT_S = 10

# blast_radius enum (tasks/schema.md § Blast radius). "cross-module" and
# "architectural" are broad-surface — worth a coordinate-anyway note even when
# no path overlap is found, because they collide easily.
_BROAD_BLAST_RADII = {"cross-module", "architectural"}

# Section heading in a body file: ``## Key files`` / ``### Key files`` (2–6 #).
_SECTION_RE = re.compile(r"^(#{2,6})\s+(?P<title>.+?)\s*$")

# Bullet line under a section: ``- foo`` / ``* foo``.
_BULLET_RE = re.compile(r"^\s*[-*]\s+(?P<content>.+?)\s*$")

# Backtick-wrapped spans inside a bullet: ``- `src/api/routes.py` — note``.
_BACKTICK_SPAN_RE = re.compile(r"`([^`]+)`")

# Glob metacharacters — a token carrying any of these is treated as a pattern.
_GLOB_CHARS = set("*?[")

# Extensionless / dotfile config basenames a path heuristic would otherwise
# reject ("." in token is False for Makefile; a leading dot fails the
# not-startswith-"." guard for .env). These are the high-collision shared-infra
# / build-config files (schema.md § Blast radius) the advisory most wants to
# catch, so intake accepts them by exact (case-insensitive) basename match.
_CONFIG_BASENAMES = {
    "makefile", "dockerfile", "procfile", "rakefile", "gemfile", "jenkinsfile",
    "vagrantfile", "brewfile", "caddyfile", "justfile", "containerfile",
    ".env", ".gitignore", ".dockerignore", ".gitattributes", ".npmrc", ".nvmrc",
    ".editorconfig", ".prettierrc", ".eslintrc", ".babelrc",
}


# ---------------------------------------------------------------------------
# _sanitize_log — duplicated from validate_tasks.py / next_task.py so this
# script stays standalone-runnable. Keep the copies in sync.
# ---------------------------------------------------------------------------
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_CONTROL_RE = re.compile(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_log(value: object, max_len: int = 500) -> str:
    """Strip ANSI / control chars + truncate. Used on every printed note so a
    stray traceback or terminal escape can't bleed into stderr. Mirror of
    ``validate_tasks.py:_sanitize_log``."""
    text = str(value)
    text = _ANSI_ESCAPE_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    text = text.replace("\n", " ").replace("\r", " ").replace("\0", " ")
    if len(text) > max_len:
        text = text[:max_len] + "..."
    return text


# ---------------------------------------------------------------------------
# Repo paths (monkeypatchable via the None-default function args, per the
# next_task.py pattern — Python snapshots defaults at def-time otherwise).
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]  # <repo>/sysop/scripts/X.py → <repo> (Phase 128)
_TASKS_DIR = _REPO_ROOT / "tasks"
_INDEX_PATH = _TASKS_DIR / "index.yml"


def _git_discovery_env() -> dict[str, str]:
    """`os.environ` minus git's discovery vars (BeanRider ISSUE-0048).

    `GIT_DIR`/`GIT_WORK_TREE`/`GIT_COMMON_DIR`/`GIT_INDEX_FILE` take precedence
    over `git -C` and git exports them into every hook; stripping them makes
    `-C` authoritative so a probe against a tmpdir resolves there, not the
    invoking repo. Verbatim mirror of validate_tasks.py:_git_discovery_env
    (same zero-dependency-duplicate rationale as _resolve_canonical_locks_dir)."""
    return {
        k: v
        for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")
    }


def _resolve_canonical_locks_dir(project_root: Path) -> Path:
    """Resolve the worktree-shared ``sysop/runtime/locks/`` (main repo via git-common-dir,
    Phase 32). Mirror of ``next_task.py:_resolve_canonical_locks_dir`` — kept a
    zero-dependency duplicate so this tool needs no path-shuffling to run."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=_git_discovery_env(),
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return project_root / "sysop/runtime/locks"
    if completed.returncode != 0:
        return project_root / "sysop/runtime/locks"
    common_dir = completed.stdout.strip()
    if not common_dir:
        return project_root / "sysop/runtime/locks"
    common_path = Path(common_dir)
    if not common_path.is_absolute():
        common_path = (project_root / common_path).resolve()
    return common_path.parent / "sysop/runtime/locks"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class CandidateScope:
    task_id: str
    paths: list[str]
    blast_radius: str
    # "key_files"          — paths came from the body's ## Key files section
    # "blast_radius_only"  — body present but no ## Key files (only the radius)
    # "none"               — candidate not in index, or no body/scope at all
    source: str


@dataclass
class Overlap:
    task_id: str  # the in-flight task (or BATCH-N) the candidate may collide with
    verdict: str  # "likely" | "possible" | "none"
    evidence: list[str]  # matched paths
    scope_source: str  # "worktree_diff" | "files_impacted" | "key_files" | "none"
    workspace: str = ""
    branch: str = ""


@dataclass
class Assessment:
    candidate: str
    candidate_scope_source: str
    candidate_paths: list[str]
    candidate_blast_radius: str
    in_flight_count: int  # in-flight tasks assessed (excludes the candidate's own lock)
    overlaps: list[Overlap]  # only verdict != "none"
    max_verdict: str  # "likely" | "possible" | "none"
    broad_radius_note: str = ""
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Index + body reading (soft — degrade to a note, never SystemExit)
# ---------------------------------------------------------------------------
def _load_index_soft(index_path: Path) -> dict[str, Any] | None:
    """Load tasks/index.yml. Returns None (caller notes + exits 0) on any
    problem — advisory-non-blocking, so a broken/missing index must not break
    the claim flow."""
    if not index_path.is_file():
        return None
    try:
        import yaml  # local import: absence degrades, doesn't crash at module load
    except ImportError:
        return None
    try:
        with open(index_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def _resolve_body_path(body_rel: str, base_tasks_dir: Path, project_root: Path) -> Path | None:
    """Resolve a ``body:`` field to an absolute path with a containment check.

    Mirrors ``next_task.py:_resolve_body_path`` two-branch rule, but returns
    None on a containment violation (never SystemExit — an advisory must not
    abort). Refuses to follow a symlink out of the tree."""
    if body_rel.startswith("tasks/"):
        candidate = project_root / body_rel
    else:
        candidate = base_tasks_dir / body_rel
    real_candidate = os.path.realpath(str(candidate))
    base_real = os.path.realpath(str(base_tasks_dir))
    if not (real_candidate == base_real or real_candidate.startswith(base_real + os.sep)):
        return None
    return Path(real_candidate)


def _looks_like_path(token: str) -> bool:
    """Heuristic: a Key-files bullet token is a path/glob (has a separator, a
    glob char, a known config basename, or a dotted extension) rather than
    prose. Used to filter the *candidate*-side ## Key files bullets — the
    factual worktree diff is trusted verbatim, not shape-filtered."""
    token = token.strip()
    if not token or " " in token or token in (".", ".."):
        return False
    if any(ch in _GLOB_CHARS for ch in token):
        return True
    if "/" in token or token.endswith("/"):
        return True
    if token.lower() in _CONFIG_BASENAMES:  # Makefile / .env / Dockerfile / …
        return True
    # A bare dotted filename (e.g. ``schema.md``, ``routes.py``) with no slash.
    # Reject a leading-dot token that isn't a known dotfile (handled above).
    return "." in token and not token.startswith(".")


def _norm_path(token: str) -> str:
    """Normalize a scope token: strip surrounding quotes/backticks, a leading
    ``./`` or ``/``, and trailing punctuation. Preserves a trailing ``/`` (it
    marks a directory prefix for grading)."""
    t = token.strip().strip("`").strip('"').strip("'").strip()
    t = t.rstrip(",;")
    while t.startswith("./"):
        t = t[2:]
    t = t.lstrip("/")
    return t


def _bullet_scope_tokens(line: str) -> list[str]:
    """Extract path/glob tokens from a single bullet line. Prefers
    backtick-wrapped spans; falls back to whitespace-split path-ish tokens."""
    bm = _BULLET_RE.match(line)
    if not bm:
        return []
    content = bm.group("content")
    spans = _BACKTICK_SPAN_RE.findall(content)
    raw_tokens = spans if spans else content.split()
    out: list[str] = []
    for tok in raw_tokens:
        norm = _norm_path(tok)
        if norm and _looks_like_path(norm):
            out.append(norm)
    return out


def _extract_key_files(body_text: str) -> list[str]:
    """Return the normalized path/glob tokens under the body's ``## Key files``
    section (first matching heading of any level). Empty when absent."""
    in_section = False
    out: list[str] = []
    for line in body_text.splitlines():
        m = _SECTION_RE.match(line)
        if m:
            in_section = "key files" in m.group("title").strip().lower()
            continue
        if in_section:
            out.extend(_bullet_scope_tokens(line))
    # de-dupe, preserve order
    seen: set[str] = set()
    deduped: list[str] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    return deduped


def _candidate_scope(
    candidate_id: str,
    index_data: dict[str, Any] | None,
    base_tasks_dir: Path,
    project_root: Path,
) -> CandidateScope:
    """Infer the candidate's likely file scope from declared signals only."""
    if not index_data:
        return CandidateScope(candidate_id, [], "", "none")
    tasks = index_data.get("tasks") or []
    entry = next(
        (t for t in tasks if isinstance(t, dict) and t.get("id") == candidate_id),
        None,
    )
    if entry is None:
        return CandidateScope(candidate_id, [], "", "none")
    blast = str(entry.get("blast_radius") or "")
    body_rel = entry.get("body")
    if not isinstance(body_rel, str) or not body_rel:
        # No body → radius is the only signal.
        return CandidateScope(candidate_id, [], blast, "blast_radius_only" if blast else "none")
    body_path = _resolve_body_path(body_rel, base_tasks_dir, project_root)
    if body_path is None or not body_path.is_file():
        return CandidateScope(candidate_id, [], blast, "blast_radius_only" if blast else "none")
    try:
        text = body_path.read_text(encoding="utf-8")
    except OSError:
        return CandidateScope(candidate_id, [], blast, "blast_radius_only" if blast else "none")
    paths = _extract_key_files(text)
    if paths:
        return CandidateScope(candidate_id, paths, blast, "key_files")
    return CandidateScope(candidate_id, [], blast, "blast_radius_only" if blast else "none")


# ---------------------------------------------------------------------------
# Lock + worktree reading (the in-flight, factual side)
# ---------------------------------------------------------------------------
def _parse_lock_file(path: Path) -> dict[str, Any]:
    """Lock files are YAML-shaped. Parse defensively; {} on failure. Mirror of
    ``sitrep_survey.py:_parse_lock_file``."""
    try:
        import yaml
    except ImportError:
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def _read_locks(project_root: Path) -> list[dict[str, Any]]:
    """Return the parsed lock dicts (id-bearing) under the canonical sysop/runtime/locks/."""
    locks_dir = _resolve_canonical_locks_dir(project_root)
    if not locks_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(glob.glob(str(locks_dir / "*.lock"))):
        if os.path.basename(p) == ".gitkeep":
            continue
        raw = _parse_lock_file(Path(p))
        task_id = raw.get("task_id") or Path(p).stem
        raw["task_id"] = str(task_id)
        out.append(raw)
    return out


def _run_git_name_only(workspace: str, base: str) -> tuple[bool, list[str]]:
    """``git -C <ws> diff --name-only <base>...HEAD``. Returns (base_resolved,
    paths). base_resolved is False when the ref doesn't exist / git errors."""
    try:
        r = subprocess.run(
            ["git", "-C", workspace, "diff", "--name-only", f"{base}...HEAD"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return False, []
    if r.returncode != 0:
        return False, []
    return True, [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _run_git_porcelain(workspace: str) -> list[str]:
    """Uncommitted + untracked paths via ``git status --porcelain``. Best-effort
    (returns [] on any error) — captures work not yet committed on the branch."""
    try:
        r = subprocess.run(
            ["git", "-C", workspace, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    out: list[str] = []
    for ln in r.stdout.splitlines():
        if len(ln) < 4:
            continue
        path = ln[3:]  # strip the 2-char XY status + separating space
        if " -> " in path:  # rename: ``old -> new`` — take the new path
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"')
        if path:
            out.append(path)
    return out


def _worktree_changed_paths(workspace: str) -> list[str]:
    """The single git boundary (mocked in tests). Real changed set of a live
    worktree: committed-on-branch (main...HEAD, falling back to origin/main) ∪
    uncommitted. Returns [] when the workspace isn't a readable git worktree."""
    if not workspace or not os.path.isdir(workspace):
        return []
    committed: list[str] = []
    for base in ("main", "origin/main"):
        ok, lines = _run_git_name_only(workspace, base)
        if ok:
            committed = lines
            break
    uncommitted = _run_git_porcelain(workspace)
    return sorted({_norm_path(p) for p in (committed + uncommitted) if p})


def _lock_files_impacted(raw: dict[str, Any]) -> list[str]:
    """Extract paths from a lock's ``files_impacted:`` list. This is a *declared*
    factual scope (a fallback for the worktree diff), so it's trusted verbatim
    rather than shape-filtered — only placeholder-shaped entries are dropped:
    the ``(update manually or via git diff --name-only main)`` seed
    claim_task.sh writes, and any parenthetical / spaced note (real repo paths
    carry no spaces). Trusting the list keeps extensionless config files
    (``Makefile``, ``.env``) the prose heuristic would otherwise discard."""
    items = raw.get("files_impacted") or []
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for it in items:
        if not isinstance(it, str):
            continue
        stripped = it.strip()
        if not stripped or " " in stripped or stripped.startswith("("):
            continue  # the claim_task.sh placeholder or a placeholder-shaped note
        norm = _norm_path(it)
        if norm:
            out.append(norm)
    return out


def _inflight_scope(
    raw: dict[str, Any],
    base_tasks_dir: Path,
    project_root: Path,
    index_data: dict[str, Any] | None,
    worktree_reader,
) -> tuple[list[str], str]:
    """Resolve one in-flight lock's scope, best-source-first. Returns
    (paths, source)."""
    workspace = str(raw.get("workspace") or "")
    diff_paths = worktree_reader(workspace) if workspace else []
    if diff_paths:
        return diff_paths, "worktree_diff"
    impacted = _lock_files_impacted(raw)
    if impacted:
        return impacted, "files_impacted"
    # Last resort: the in-flight task's own body ## Key files.
    task_id = str(raw.get("task_id") or "")
    if task_id and index_data:
        cand = _candidate_scope(task_id, index_data, base_tasks_dir, project_root)
        if cand.paths:
            return cand.paths, "key_files"
    return [], "none"


# ---------------------------------------------------------------------------
# Grading — pure, no I/O
# ---------------------------------------------------------------------------
def _is_glob(token: str) -> bool:
    return any(ch in _GLOB_CHARS for ch in token)


def _grade(candidate_paths: list[str], inflight_paths: list[str]) -> tuple[str, list[str]]:
    """Grade candidate (guessed) scope ∩ in-flight (actual) scope.

    exact path match → ``likely``; glob intersection or same directory →
    ``possible``; disjoint → ``none``. Pure function."""
    likely: set[str] = set()
    possible: set[str] = set()
    inflight = [p for p in inflight_paths if p]
    for c in candidate_paths:
        if not c:
            continue
        c_is_glob = _is_glob(c)
        c_is_dir = c.endswith("/")
        c_bare = c.rstrip("/")
        c_dir = os.path.dirname(c_bare)
        for i in inflight:
            # exact concrete match → likely
            if not c_is_glob and not c_is_dir and c == i:
                likely.add(i)
                continue
            # candidate is a directory prefix → possible
            if c_is_dir and (i == c_bare or i.startswith(c)):
                possible.add(i)
                continue
            # candidate glob matches the in-flight path → possible
            if c_is_glob and fnmatch.fnmatch(i, c):
                possible.add(i)
                continue
            # in-flight token is itself a glob matching the candidate → possible
            if _is_glob(i) and fnmatch.fnmatch(c_bare, i):
                possible.add(i)
                continue
            # same directory (both non-root) → possible
            if c_dir and c_dir == os.path.dirname(i):
                possible.add(i)
                continue
    if likely:
        return "likely", sorted(likely)
    if possible:
        return "possible", sorted(possible)
    return "none", []


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
_VERDICT_RANK = {"none": 0, "possible": 1, "likely": 2}


def assess(
    candidate_id: str,
    index_path: Path | None = None,
    base_tasks_dir: Path | None = None,
    project_root: Path | None = None,
    worktree_reader=None,
) -> Assessment:
    """Assess the candidate against every in-flight lock. ``worktree_reader``
    is injectable (defaults to the real git boundary) so tests drive the
    factual side without a git repo."""
    if index_path is None:
        index_path = _INDEX_PATH
    if base_tasks_dir is None:
        base_tasks_dir = _TASKS_DIR
    if project_root is None:
        project_root = _REPO_ROOT
    if worktree_reader is None:
        worktree_reader = _worktree_changed_paths

    notes: list[str] = []
    index_data = _load_index_soft(index_path)
    if index_data is None:
        notes.append(
            "no readable tasks/index.yml (or PyYAML unavailable) — "
            "candidate scope could not be inferred"
        )

    cand = _candidate_scope(candidate_id, index_data, base_tasks_dir, project_root)
    if cand.source == "none" and index_data is not None:
        notes.append(
            f"{candidate_id} not found in index (or has no body) — "
            "overlap assessed only against in-flight facts I could read"
        )

    locks = _read_locks(project_root)
    overlaps: list[Overlap] = []
    in_flight_count = 0
    for raw in locks:
        tid = str(raw.get("task_id") or "")
        if not tid or tid == candidate_id:
            continue  # skip the candidate's own lock (defensive) + unnamed locks
        in_flight_count += 1
        paths, src = _inflight_scope(
            raw, base_tasks_dir, project_root, index_data, worktree_reader
        )
        verdict, evidence = _grade(cand.paths, paths)
        if verdict != "none":
            overlaps.append(
                Overlap(
                    task_id=tid,
                    verdict=verdict,
                    evidence=evidence,
                    scope_source=src,
                    workspace=str(raw.get("workspace") or ""),
                    branch=str(raw.get("branch") or ""),
                )
            )

    overlaps.sort(key=lambda o: (-_VERDICT_RANK[o.verdict], o.task_id))
    max_verdict = "none"
    for o in overlaps:
        if _VERDICT_RANK[o.verdict] > _VERDICT_RANK[max_verdict]:
            max_verdict = o.verdict

    broad_note = ""
    if (
        cand.blast_radius in _BROAD_BLAST_RADII
        and in_flight_count > 0
        and max_verdict != "likely"
    ):
        broad_note = (
            f"{candidate_id} is {cand.blast_radius} — broad-surface work collides "
            "easily even without a declared path match; coordinate with the "
            "in-flight set before claiming."
        )

    return Assessment(
        candidate=candidate_id,
        candidate_scope_source=cand.source,
        candidate_paths=cand.paths,
        candidate_blast_radius=cand.blast_radius,
        in_flight_count=in_flight_count,
        overlaps=overlaps,
        max_verdict=max_verdict,
        broad_radius_note=broad_note,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
_VERDICT_PREFIX = {"likely": "likely merge conflict", "possible": "possible overlap"}


def render_text(a: Assessment) -> str:
    """Human-readable advisory for ``/claim-task`` to print. Warns on overlap;
    reassures when clean; states the honest 'this is a guess' caveat."""
    lines: list[str] = []
    if a.in_flight_count == 0:
        lines.append(f"✓ No work in flight — nothing for {a.candidate} to collide with.")
        for n in a.notes:
            lines.append(f"  · note: {n}")
        return "\n".join(lines) + "\n"

    if not a.overlaps:
        lines.append(
            f"✓ No declared overlap between {a.candidate} and "
            f"{a.in_flight_count} task(s) in flight."
        )
        if a.candidate_scope_source == "key_files":
            lines.append(
                f"  (compared {a.candidate}'s ## Key files against each in-flight "
                "worktree's changed set — a pre-plan guess, not a guarantee.)"
            )
        else:
            lines.append(
                "  (couldn't read a ## Key files list for the candidate, so this "
                "is a weak signal — no path overlap detected, but scope is a guess.)"
            )
        if a.broad_radius_note:
            lines.append(f"  ⚠ {a.broad_radius_note}")
        for n in a.notes:
            lines.append(f"  · note: {n}")
        return "\n".join(lines) + "\n"

    header = "⚠  Overlap with work in flight:"
    lines.append(header)
    for o in a.overlaps:
        where = f" · {o.workspace}" if o.workspace else ""
        label = _VERDICT_PREFIX.get(o.verdict, o.verdict)
        shared = ", ".join(o.evidence[:6])
        if len(o.evidence) > 6:
            shared += f", +{len(o.evidence) - 6} more"
        lines.append(f"   {o.task_id} (in flight{where}) — {label} at /review-close")
        lines.append(f"     shared: {shared}")
    if a.broad_radius_note:
        lines.append(f"   ⚠ {a.broad_radius_note}")
    lines.append(
        "   Overlap is recoverable rework, not corruption — claim anyway, or pick a "
        "non-overlapping task (/next-task surfaces the clear ones)."
    )
    for n in a.notes:
        lines.append(f"   · note: {n}")
    return "\n".join(lines) + "\n"


def render_json(a: Assessment) -> str:
    return (
        json.dumps(
            {
                "candidate": a.candidate,
                "candidate_scope_source": a.candidate_scope_source,
                "candidate_paths": a.candidate_paths,
                "candidate_blast_radius": a.candidate_blast_radius,
                "in_flight_count": a.in_flight_count,
                "max_verdict": a.max_verdict,
                "broad_radius_note": a.broad_radius_note,
                "overlaps": [
                    {
                        "task_id": o.task_id,
                        "verdict": o.verdict,
                        "evidence": o.evidence,
                        "scope_source": o.scope_source,
                        "workspace": o.workspace,
                        "branch": o.branch,
                    }
                    for o in a.overlaps
                ],
                "notes": a.notes,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Advisory scope-overlap check: does a candidate task collide with "
            "work already in flight? Non-blocking — always exits 0 unless it crashes."
        )
    )
    parser.add_argument("candidate", help="the candidate task ID to assess (e.g. FEAT-FOO)")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit structured JSON instead of the text advisory",
    )
    args = parser.parse_args(argv)

    a = assess(args.candidate)
    if args.json:
        sys.stdout.write(render_json(a))
    else:
        sys.stdout.write(render_text(a))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — top-level safety net (advisory: never break the caller)
        print(
            f"WARN: scope_overlap.py could not complete: {_sanitize_log(str(e)[:500])}",
            file=sys.stderr,
        )
        # Exit 2 so a caller *can* distinguish a crash, but the advisory is
        # non-blocking: /claim-task treats any non-zero as "advisory unavailable,
        # proceed" rather than halting the claim.
        sys.exit(2)
