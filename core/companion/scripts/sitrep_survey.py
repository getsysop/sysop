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
import glob
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
    # PyYAML lives only in the project venv on PEP-668 hosts (BeanRider
    # ISSUE-0049; internal tracker #321), so resolve it onto sys.path before giving up
    # — that keeps a bare `python3 sysop/scripts/…` working, which is what the
    # skills prescribe and settings.json allow-rules are written against.
    # It PROBES rather than assuming: a candidate is committed to sys.path only
    # once `import yaml` actually succeeds from it, and is rolled back
    # otherwise. The first draft stopped at the first venv-SHAPED directory, so
    # one empty `.venv` disabled the whole search — including the main-checkout
    # arm below, which is the entire point of it — and a `.venv` shadowed a
    # sibling `venv` that did have PyYAML. That was the shell helper's design
    # (`claim_task.sh:resolve_yaml_python`) stated in this phase's own log and
    # not honoured here; the round caught it by running it.
    #
    # Order is script-anchored FIRST — this file's ancestors, then the MAIN
    # checkout via git-common-dir (a linked worktree carries the scripts but
    # never a `.venv`, and worktrees are where /claim-task builds) — and only
    # then the CWD. CWD-first let an unrelated project's venv win whenever a
    # script was invoked by path from elsewhere. Both `.venv/` and `venv/`
    # layouts, at every root.
    #
    # The git probe strips git's discovery vars for the reason
    # `tests/test_git_env_hermeticity.py` exists (BeanRider ISSUE-0048): git
    # exports `GIT_DIR` into every hook, and these scripts run from pre-commit. Inline by necessity rather than by accident: it must run before
    # any import can be trusted, and validate_tasks.py + next_task.py are
    # deliberately standalone for pre-commit (see _log.py's header).
    # tests/test_venv_pyyaml_bootstrap.py pins the five copies identical.
    _roots = []
    # `list(...)` before the slice: slicing `PurePath.parents` is 3.10+
    # (bpo-35498), and on 3.9 it raises TypeError from inside this very
    # `except ImportError` — the interpreter the block exists to rescue.
    for _cand in list(Path(__file__).resolve().parents)[:3]:
        if _cand not in _roots:
            _roots.append(_cand)
    try:
        _r = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True,
            text=True,
            timeout=5,
            env={_k: _v for _k, _v in os.environ.items()
                 if _k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR",
                               "GIT_INDEX_FILE")},
        )
        if _r.returncode == 0 and _r.stdout.strip():
            _main = (Path(__file__).resolve().parent / _r.stdout.strip()).resolve().parent
            if _main not in _roots:
                _roots.append(_main)
    except (OSError, subprocess.SubprocessError):
        pass
    if Path.cwd() not in _roots:
        _roots.append(Path.cwd())
    _hit = False
    for _root in _roots:
        for _layout in (".venv", "venv"):
            for _site in glob.glob(str(_root / _layout / "lib/python*/site-packages")):
                sys.path.insert(0, _site)
                try:
                    import yaml
                except ImportError:
                    sys.path.remove(_site)
                    continue
                _hit = True
                break
            if _hit:
                break
        if _hit:
            break
    try:
        import yaml
    except ImportError:
        print(
            "ERROR: sitrep_survey.py requires PyYAML. fix: python3 -m venv .venv && "
            ".venv/bin/pip install pyyaml   (PEP-668-safe), or activate the venv.",
            file=sys.stderr,
        )
        # 2, not 1: the house contract is 1 = the caller's input is wrong,
        # 2 = the environment is. `/review-close` Step 4a routes those two apart
        # in terms and must not abort a branch over a missing dependency. This
        # was the one script of the five that exited 1 here (Phase 219 round).
        sys.exit(2)


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
    # Q-019: whether /document-work's pending-doc exists for this branch. The
    # `Doc-Work:` trailer alone stopped meaning "docs written" when
    # /claim-task's executor began emitting it too.
    pending_doc: bool = False
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
    # `> **Triaged:** <date> <auto|flag> [TASK-…]` — /triage's durable verdict.
    # A batch with no such line has never been classified by a shipped /triage
    # run (or carries a legacy tag of unknown provenance), so it is *untriaged*
    # regardless of whether a `Flag:` line is present. This — not `has_flag` —
    # is what priority 4a routes on, so an all-auto queue stops re-recommending
    # /triage forever once a run has recorded its verdict.
    has_triage_record: bool = False
    triaged_verdict: str = ""  # "auto" | "flag" | "" (no record)
    triaged_tasks: list[str] = field(default_factory=list)  # judgment-only task ids


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


_BATCH_HEADER_RE = re.compile(r"^### Batch (\d+) — (.+?) `([^`]+)`$")
# Permissive twin, used ONLY to close the open batch on a `### Batch <N>` line
# the strict pattern rejected — see the closer in _read_review_batches. Both
# patterns are duplicated verbatim from review_index.py; edit one, edit both.
# `\s+`, not literal spaces — see review_index.py's twin for the full reason.
# In short: a TAB or double space (`###\tBatch 8`) fails the strict pattern AND
# a single-space twin, which is the exact fall-through the twin exists to stop.
# Phase 191's round reproduced the carry-over here on the supposedly-fixed tree.
_BATCH_HEADER_ANY_RE = re.compile(r"^###\s+Batch\s+\d+\b")
_META_BRANCH_RE = re.compile(r"^> \*\*Branch:\*\* `([^`]+)`")
# Duplicated verbatim from review_index.py and pinned equal by
# tests/test_flag_contract.py — see that file's comment for why these are
# mirrored rather than imported. Edit one, edit both.
_META_FLAG_RE = re.compile(r"^> \*\*Flag:\*\*\s*(.*)$")
_META_TRIAGED_RE = re.compile(
    r"^> \*\*Triaged:\*\* (\d{4}-\d{2}-\d{2}) (auto|flag)"
    r"(?:\s+\[([^\]]*)\])?"
    r"(?:\s+[—–-]\s*(.*?))?\s*$"
)
_TRIAGED_TASK_ID_RE = re.compile(r"TASK-\d+")
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(?:> ?)*(`{3,}|~{3,})")
_FENCE_CLOSE_RE = re.compile(r"^ {0,3}(?:> ?)*(`{3,}|~{3,})[ \t]*$")


def _fenced_mask(lines):
    """True for every line inside a **balanced** fenced block, delimiters included.

    An **unterminated** fence is deliberately ignored — its lines stay
    structural. Honouring it is strictly worse than having no fence rule at
    all: one stray ``` disables structural parsing to end-of-file, so the
    enclosing batch's ``line_end`` runs to EOF and ``close_batch.sh`` flips
    every checkbox in that range, including a trailing ``## Deferred``
    section's. Phase 181's first fence implementation did exactly that, and
    its second review round caught it by writing a tracker with an unbalanced
    marker — a shape neither the author's fixtures nor the first round had.

    Two passes rather than one state machine for exactly that reason: you
    cannot know a fence is balanced until you have seen the whole file.

    Duplicated verbatim from ``review_index.py``; pinned equal by
    ``tests/test_flag_contract.py``.
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


_TASK_LINE_RE = re.compile(r"^- \[( |/|x)\] \*\*(TASK-\d+)\*\*:")


def _warn_on_duplicate_batch_numbers(batches, source: str) -> None:
    """Surface same-numbered batches on stderr, and continue (Q-227).

    This reader keeps BOTH batches where ``review_index.py`` collapses to one
    (it keys a dict by number, so the later header overwrites the earlier).
    That divergence is why the index's ``--list`` warning never reached here:
    this script does not consult the index at all.

    Keeping both is the better *display* behaviour and it is deliberately not
    changed. It became a routing problem only when Phase 209 taught the
    mutators to refuse an ambiguous number — after which this script could
    recommend a batch they refuse, with nothing on any stream to explain why.
    The warning closes that gap without touching the parse.

    **It points at the check rather than asserting an outcome, and that wording
    is load-bearing.** The first cut said the shells "REFUSE that number (exit
    4)". Measured by this phase's round: `batch_work.sh` exits **1**,
    `close_batch.sh` exits **0** (it skips the batch and reports the run as
    completed), and 4 is only the internal helper's code — so the sentence was
    false twice. Worse, on a tracker whose two headers differ in punctuation
    (an em-dash and an ASCII hyphen) the readers disagree: this one sees two
    batches and warns, `sitrep_survey` sees one and stays silent, and
    `--check-duplicates` finds no duplicate at all, so nothing refuses and the
    advice would have sent an operator to renumber a batch for no reason.
    Naming the authoritative check is the only form that is true on every shape.

    Derived from this reader's own list rather than by importing the index's
    ``duplicate_batch_numbers``: these scripts install standalone and import
    nothing shared, and a sixth copy of a rule already duplicated four times is
    the trade `close_batch.sh` and `_fenced_mask` both declined.
    """
    seen: dict[str, int] = {}
    for b in batches:
        num = b.get("number")
        if num is None:
            continue
        seen[str(num)] = seen.get(str(num), 0) + 1
    dupes = {n: c for n, c in seen.items() if c > 1}
    if not dupes:
        return
    for num in sorted(dupes, key=lambda n: int(n) if n.isdigit() else 0):
        print(
            f"WARNING: {source} declares Batch {num} {dupes[num]} times, and this "
            f"view keeps all of them.\n"
            f"         Confirm with: python3 sysop/scripts/review_index.py "
            f"--check-duplicates {num}\n"
            f"         That check is what the mutating paths key on, and it uses a "
            f"STRICTER header pattern than this reader — so the two can disagree, "
            f"and the check is the authority.",
            file=sys.stderr,
        )


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
    # Fenced content is example text, not structure — see review_index.py's
    # note. Without this a task quoting the tracker's own shapes both
    # truncates its batch and donates a fake `Flag:`/`Triaged:` to it.
    fenced = _fenced_mask([ln.rstrip("\n") for ln in lines])
    for idx, raw in enumerate(lines):
        line = raw.rstrip("\n")
        if fenced[idx]:
            continue
        # Any level-2 heading ends the open batch. Without it the LAST batch
        # absorbed `## Deferred` / `## Statistics` task lines into its own
        # `tasks` list, so `done == total` could never hold and /sitrep's
        # priority 2 ("ready for /review-close") never fired for it — the
        # operator was told to keep working on a finished batch.
        if line.startswith("## "):
            if current is not None:
                out.append(current)
                current = None
            continue
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
                "triaged_date": "",
                "triaged_verdict": "",
                "triaged_tasks": [],
                "tasks": [],
            }
            continue
        # A `### Batch <N>` line the strict pattern rejected still closes the
        # open batch — the same rule the `## ` closer above applies, at the one
        # heading level that was missing it. Here the orphan donated its `- [ ]
        # TASK-…` lines as well as its `> **Branch:**`, so the done/total
        # arithmetic behind /sitrep's "ready for /review-close" signal was wrong
        # for the batch above it, which is the very failure the `## ` closer was
        # added to stop.
        if _BATCH_HEADER_ANY_RE.match(line):
            if current is not None:
                out.append(current)
                current = None
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
        mtr = _META_TRIAGED_RE.match(line)
        if mtr:
            current["triaged_date"] = mtr.group(1)
            current["triaged_verdict"] = mtr.group(2)
            current["triaged_tasks"] = _TRIAGED_TASK_ID_RE.findall(mtr.group(3) or "")
            continue
        mt = _TASK_LINE_RE.match(line)
        if mt:
            current["tasks"].append({"checkbox": mt.group(1), "id": mt.group(2)})
    if current is not None:
        out.append(current)
    _warn_on_duplicate_batch_numbers(out, "review_tasks.md")
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


def _pending_doc_for(
    main_root: Path,
    branch: str,
    lock: Lock | None,
    worktree: Worktree | None,
) -> Path | None:
    """The branch's `/document-work` pending-doc, if one exists. `Q-019`.

    **Why this read has to exist, and why it is a filesystem walk rather than a
    git read.** The `Doc-Work:` trailer was a proxy for "`/document-work` has
    run", and it stayed true only while `/document-work` was its sole emitter.
    `/claim-task` Step 7e's executor now emits the same trailer from its own
    commit — deliberately, so the branch is visible mid-pipeline — so a branch
    where `/document-work` ran and one where it never did became textually
    identical to this survey, which then routed the operator straight past it.

    A pending-doc is the artifact `/document-work` Step 3 produces, so its
    presence is the half the trailer cannot supply. **Not the ONLY producer, and
    the round corrected that**: `/auto-fix` and `/auto-judge` both write one
    directly for a batch branch, and `/auto-build` writes one by delegating to
    `/document-work --non-interactive`. It stays a sound signal here because the
    arm's other conjunct is a `Doc-Work:` trailer, which none of those three
    emits — but the justification is "the trailer and the doc have disjoint
    producers", not "only one skill writes the doc". It is NOT on the branch:
    `sysop/runtime/` is gitignored (the installer's `ensure_runtime_gitignore`
    seeds exactly that), so the file lives in the workspace's filesystem and
    `git show <branch>:<path>` would report absent for every branch alike —
    which is the healthy-and-skipped-look-identical defect again, one layer
    down.

    Workspace resolution follows `/review-close` Step 0's arms in the same order
    and mostly for the same reasons: a `--worktree` claim is listed by git; a
    `--clone` claim is not, and is recoverable from the `workspace:` its lock
    records.

    **Two corrections from this function's own review round, because the first
    version's justification was wrong at the root.** It said arm (iii) exists
    because `USE_LOCK` defaults to false, so a `--clone` without `--lock` is
    reachable by neither earlier arm. That cannot be why: the only caller
    iterates `for lock in locks`, so a task with no lock never reaches this
    function at all. Arm (iii)'s real job is a lock whose `workspace:` is blank
    or damaged. And it is **not** a mirror of Step 0's arm (iii), which globs
    sibling directories and verifies each by reading its `HEAD`; this is one
    computed path with no glob and no verification, which is enough for the
    narrow case it actually covers.

    The path it computes had to be corrected too: `claim_task.sh` builds
    `../<prefix>-<task id LOWER-CASED>` and honours `WORKTREE_PREFIX`, so the
    first version — `<repo name>-<TASK_ID>` verbatim — could never match on a
    case-sensitive filesystem. `WORKTREE_PREFIX` is not recorded in the lock, so
    a prefixed workspace is still only reachable via arm (ii); that is a stated
    limit, not an oversight.

    Read-only by construction — `/sitrep` carries a `disallowed-tools` guard and
    this function only ever stats paths.
    """
    if not branch:
        return None
    rel = Path("sysop") / "runtime" / "pending-docs" / f"{branch.replace('/', '-')}.md"

    candidates: list[Path] = []
    if worktree is not None:                       # (i) git-listed worktree
        candidates.append(worktree.path)
    if lock is not None and lock.workspace:        # (ii) the lock's record
        candidates.append(Path(lock.workspace))
    # (iii) the conventional sibling directory. `claim_task.sh` lower-cases the
    # task id when it builds this path, so this must too — `FEAT-0001` produces
    # `<repo>-feat-0001`, and the un-lowered spelling matched nothing on any
    # case-sensitive filesystem.
    if lock is not None and lock.task_id:
        candidates.append(
            main_root.parent / f"{main_root.name}-{lock.task_id.lower()}")
    candidates.append(main_root)

    # A `workspace:` value is whatever a consumer typed, and a read-only survey
    # may not raise on one — `/sitrep`'s `main()` catches only KeyboardInterrupt,
    # so an escaping OSError takes the whole report down with a traceback.
    #
    # **This handler was deleted by Phase 220's first cut and restored by its own
    # review round, and the reason is worth keeping.** The deletion rested on a
    # measurement — `Path.is_file()` returns False for a NUL byte, an over-long
    # path and a nonexistent parent — that was taken on **3.14 only**, where
    # `is_file()` delegates to `os.path.isfile()` and swallows `(OSError,
    # ValueError)` unconditionally. On **3.9 through 3.13** it goes through
    # `Path.stat()` and re-raises any errno outside `_IGNORED_ERRNOS`
    # (ENOENT/ENOTDIR/EBADF/ELOOP) — so an over-long path raises `OSError`
    # ENAMETOOLONG. Re-measured on 3.9, 3.11, 3.12 and 3.14: the first three
    # raise. `README.md` declares Python 3.9+, CI runs the suite on 3.9, and
    # stock macOS 3.9 is the interpreter a consumer without a venv actually
    # runs, so the handler is live on every supported interpreter but the
    # author's own. Checking one interpreter and generalising is the same defect
    # class as `Q-263`, which is why this comment names the versions.
    for base in candidates:
        try:
            p = base / rel
            if p.is_file():
                return p
        except (OSError, ValueError):
            continue
    return None


# ── Park + awaiting-approval probe (Phase 237, Q-030 leg (a)) ────
#
# `/sitrep` was park-blind. A parked claim and an unstarted one both classified
# as `planning` (lock + branch, 0 commits ahead) — the Phase 135/143/146 shape,
# a stalled thing and a fresh thing producing identical evidence. Both park
# writers use the same `<ID>__<stamp>.md` filename shape on purpose
# (`claim-task/SKILL.md` § Who removes the marker), so ONE glob covers
# `/auto-build`'s Phase-6d park and `/claim-task`'s Step-7c park alike. That
# matters: `/sitrep` was park-blind for `/auto-build` too, and that half is a
# pre-existing gap rather than one the orchestrator reshape created.
#
# **Report unknown, never "not run".** Every probe here returns "" when it finds
# nothing, and "" leaves the caller's existing classification untouched. Absence
# is NOT evidence that the pipeline never ran: `sysop/runtime/` is gitignored,
# so a fresh clone, a `--resume` onto a rebuilt worktree, and any non-Claude-Code
# harness (the `SubagentStop` envelope is Claude-Code-only) each produce a
# correct claim with no artifacts on disk. This probe only ever UPGRADES a
# classification on positive evidence. It never accuses.
#
# The orchestrator spec (maintainer-side, and it never ships) preferred riding
# an unread lock field, on a "zero new I/O" argument. That
# argument predates Part A and is stale in the consumer's favour: Step 7c now
# writes a purpose-built park marker carrying the reason, the branch and the
# `--resume` line, so the glob is both simpler and strictly more informative —
# and the lock-field route would need an orchestrator write to the lock that
# appears on none of the spec's lists of orchestrator-level writes.

_PARKED_STATE = "parked"
_AWAITING_STATE = "awaiting approval"


def _park_markers(main_root: Path, claim_id: str) -> list[Path]:
    """Park markers for a claim, newest first. Empty when absent or unreadable."""
    d = main_root / "sysop" / "runtime" / "parked"
    if not d.is_dir():
        return []
    try:
        return sorted(d.glob(f"{claim_id}__*.md"), reverse=True)
    except OSError:
        return []


def _newest_claim_run(main_root: Path, claim_id: str) -> Path | None:
    """The most recent per-run artifact directory for a claim, or None.

    Run ids are `<UTC %Y%m%dT%H%M%SZ>-<8 hex>` (`/claim-task` Step 7-pre), so a
    lexical sort IS chronological. Deliberately not mtime: a clone, a checkout
    or a copy resets mtime, and this directory is gitignored precisely so it is
    the kind of thing that gets rebuilt.
    """
    d = main_root / "sysop" / "runtime" / "claim" / claim_id
    if not d.is_dir():
        return None
    try:
        runs = sorted((p for p in d.iterdir() if p.is_dir()), reverse=True)
    except OSError:
        return None
    return runs[0] if runs else None


def _classification_verdict(run: Path) -> str:
    """The verdict recorded in a run's classification.md, upper-cased.

    **Parse the fenced body; do not scan for a line prefix.** `/claim-task`
    Step 7c — the only writer of this file in the tree — emits
    `json.dumps(report, indent=2)` inside a ```yaml fence, so the verdict on
    disk is `  "verdict": "PROCEED"`. The first cut of this function scanned for
    a line *beginning* `verdict:` and therefore matched **nothing the shipped
    writer produces**, which made `awaiting approval` unreachable in production
    — with its own tests green, because every fixture hand-typed a flat
    `verdict: PROCEED` that nothing in the tree emits. Found by this phase's
    round; the correct idiom already existed in
    `tests/test_claim_task_heredocs_execute.py`.

    Returns "" when the file is absent, unreadable, or carries no verdict — the
    same "cannot tell" the rest of this probe uses. Never a default verdict:
    guessing PROCEED would invent a human gate nobody is standing at, and
    guessing BLOCKED would invent a park.
    """
    p = run / "classification.md"
    if not p.is_file():
        return ""
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    # 1. The shipped shape: a fenced JSON body (JSON is a subset of YAML 1.2,
    #    which is why Step 7c labels the fence `yaml` and writes JSON into it).
    m = re.search(r"```(?:yaml|json)?[^\n]*\n(.*?)\n```", text, re.S)
    if m:
        for _loader in (json.loads, yaml.safe_load):
            try:
                doc = _loader(m.group(1))
            except Exception:
                continue
            if isinstance(doc, dict) and isinstance(doc.get("verdict"), str):
                return doc["verdict"].strip().upper()
    # 2. A bare `verdict:` line — a hand-written file, or a future flat shape.
    #    Kept as a fallback rather than as the primary, which is the inversion
    #    the round corrected.
    m = re.search(
        r'^[\s>*_-]*"?verdict"?:[\s*_"]*([A-Za-z_]+)', text, re.MULTILINE | re.IGNORECASE
    )
    return m.group(1).upper() if m else ""


def _claim_stall(
    main_root: Path | None, claim_id: str
) -> tuple[str, str, list[str]]:
    """Why a 0-commit claim is not moving: (state, next_action, notes).

    ("", "", []) means no positive evidence of a stall — the ordinary case, and
    the one that leaves `planning` in place. `main_root=None` (a direct caller
    that cannot probe) takes that arm too, rather than reporting a stall it did
    not look for.
    """
    if main_root is None or not claim_id:
        return "", "", []

    markers = _park_markers(main_root, claim_id)
    run = _newest_claim_run(main_root, claim_id)
    verdict = _classification_verdict(run) if run is not None else ""

    if markers:
        newest = markers[0]
        notes = [f"park marker on disk: {newest.name}"]
        if len(markers) > 1:
            notes.append(
                f"{len(markers)} park markers for this claim — the newest is named"
            )
        if run is not None:
            action = (
                f"read {newest.name}, then "
                f"/claim-task {claim_id} --resume {run.name}"
            )
        else:
            # An /auto-build park has no claim/<id>/ run directory at all. Do
            # not print a --resume line naming a run that does not exist.
            action = (
                f"read sysop/runtime/parked/{newest.name} — it records why "
                f"{claim_id} stopped and what it is waiting on"
            )
        return _PARKED_STATE, action, notes

    if verdict == "BLOCKED" and run is not None:
        # Adjudicated blocker, no marker on disk. The claim is parked in
        # substance; say that, and say the marker is missing rather than
        # inventing one.
        return (
            _PARKED_STATE,
            f"/claim-task {claim_id} --resume {run.name}",
            [
                "classification.md reads verdict: BLOCKED but no park marker is "
                "on disk — the park is real, its marker is not"
            ],
        )

    if (
        verdict == "PROCEED"
        and run is not None
        and not (run / "outcome.md").is_file()
    ):
        return (
            _AWAITING_STATE,
            f"approve or revise the plan: /claim-task {claim_id} --resume {run.name}",
            [
                "plan reviewed and classified clean; Step 7d's human gate has "
                "not been answered"
            ],
        )

    return "", "", []


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
    pending_doc: Path | None = None,
    main_root: Path | None = None,
) -> TaskState:
    state = "unknown"
    marker = ""
    next_action = ""
    notes: list[str] = []
    doc_work_ids = sorted({tid for c in commits for tid in c.doc_work_ids})

    # **The stall probe runs BEFORE the stale check, and the order is the whole
    # point.** A park is by construction long-lived — it is waiting on an absent
    # human — so past `--stale-days` (default 7) the stale arm would classify it
    # `stale` and advise "confirm dead and rm the lock if abandoned": destructive
    # advice about a live claim, and the exact opposite of what the park needs.
    # This phase's round found it, and found that every integration test built
    # `Lock(started="")`, which short-circuits the stale check and hid it.
    stall_state, stall_action, stall_notes = _claim_stall(
        main_root, task_id
    ) if not commits else ("", "", [])

    # Stale check (applies to any state with a lock + worktree)
    if lock and lock.started and not stall_state:
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
                    pending_doc=pending_doc is not None,
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
            pending_doc=pending_doc is not None,
            next_action=next_action,
            notes=notes,
        )

    commits_ahead = len(commits)

    if commits_ahead == 0:
        # Phase 237, Q-030 leg (a): a park and an unstarted claim used to land
        # here identically. The probe (run above, before the stale check)
        # returns "" whenever it has no positive evidence, which is the ordinary
        # case and leaves `planning` exactly as it was — absence of artifacts is
        # never read as "the pipeline did not run" (see _claim_stall's docstring
        # for why that polarity is the whole design).
        if stall_state:
            state = stall_state
            next_action = stall_action
            notes.extend(stall_notes)
        else:
            state = "planning"
            next_action = (
                f"continue the build pipeline for {task_id} "
                "(see /claim-task Step 7: plan -> review -> classify -> execute)"
            )
    elif task_id and task_id in doc_work_ids and pending_doc is None:
        # ── Q-019: trailer present, pending-doc absent ───────────
        #
        # The trailer alone no longer means `/document-work` has run. Since
        # Phase 171 `/claim-task` Step 7e's executor emits `Doc-Work:` from its
        # own commit, so this state is the NORMAL terminal state of the build
        # pipeline — not an error, and deliberately not worded as one.
        #
        # Routing it to `/review-close` (which is what this survey did before)
        # skips: Step 1b's simplify pass; Step 3, which produces the pending-doc
        # `/review-close` Step 4c consolidates and Step 3c reads for manual-smoke
        # signals — so the close arrives with no pending-doc at all; and Step 3b's
        # HARD-FAIL follow-up-stub check, which on one measured run caught four
        # follow-ups named in task-body prose with no stub in `tasks/index.yml`,
        # all four of which would have been archived with the parent and never
        # seen by `/next-task`.
        #
        # `/claim-task`'s own final report already ends "Run `/document-work`
        # next." This arm stops the two shipped surfaces from contradicting each
        # other in exactly this state.
        state = "code committed, docs pending"
        next_action = f"/document-work {task_id}"
        notes.append(
            "Doc-Work: trailer present but no pending-doc — the trailer is "
            "emitted by /claim-task's executor as well as /document-work, so "
            "it does not by itself mean documentation has been written"
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
        pending_doc=pending_doc is not None,
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

    out.extend(_round_coverage_discrepancies(main_root))
    return out


# Tier-0 round coverage (_shared/fanout-evidence.md). The marker above catches a
# round that DIED; this catches one that FINISHED without covering anything —
# the measured failure being that both review skills reviewed a 1,561-file repo
# solo, opened ~1%, and reported the dispatch-set size as though it were
# coverage. Only the newest receipt per skill is examined: older ones are
# history, not an open problem.
#
# Every check here is a SELF-CONTRADICTION, never a quality bar. A thin round is
# perfectly legitimate when it says so — a `Sampled` round is exempt by
# construction, and an incremental round's manifest is its own small scope. What
# is reported is a round whose own numbers refute its own label, or one that
# closed with no numbers at all.
LOW_LOOK_RATIO = 3  # The ~1/3 boundary, shared with Tier 2's batch-level leg (a)
                    # and deliberately not re-derived. The two tiers share this
                    # THRESHOLD and their vocabulary; they no longer share an
                    # arithmetic. Tier 0 sums `opened + grepped` because a round
                    # reports both; Tier 2's leg (a) reads `Opened` against
                    # `Assigned` alone, because the evidence footer collects no
                    # count of files reached by search and never has. An earlier
                    # version of this comment cited Tier 2 as the source of the
                    # SUM, which was never true of any footer it could read.


def _round_coverage_discrepancies(main_root: Path) -> list[Discrepancy]:
    d = main_root / "sysop" / "runtime" / "round-receipts"
    if not d.is_dir():
        return []
    newest: dict[str, tuple[float, dict[str, Any]]] = {}
    for f in d.glob("*.json"):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
            mtime = f.stat().st_mtime
        except (OSError, ValueError):
            continue
        if not isinstance(r, dict):
            continue
        skill = str(r.get("skill", "unknown"))
        if skill not in newest or mtime > newest[skill][0]:
            newest[skill] = (mtime, r)

    out: list[Discrepancy] = []
    for skill, (_, r) in sorted(newest.items()):
        # `tracked` is counted by the receipt writer at close, not claimed by
        # the round — the only non-self-reported number here. It is folded into
        # the details below rather than judged: /sitrep reports problems, and a
        # narrow manifest is not itself one. self_check.sh is where it displays
        # unconditionally.
        tracked = r.get("tracked")
        of_repo = (f" of {tracked} tracked" if isinstance(tracked, int) else "")
        kind = str(r.get("kind", "unreported"))
        # A field is "present" only if it is the RIGHT TYPE. Checking for the
        # literal "unreported" alone would let any other non-int (a quoted
        # "13", a null, a future format change) reach the arithmetic below and
        # raise — and _find_discrepancies is called unguarded, so that
        # traceback takes the whole of /sitrep down, not just this line. A
        # probe that breaks the report is worse than the silence it reports on.
        missing = [k for k in ("manifest", "opened", "workers")
                   if not isinstance(r.get(k), int)]
        # `kind` is present only if it is one of the three labels the writer can
        # emit. Anything else — "unreported", a blank, a number from a
        # hand-edited receipt — is a round that declared nothing, and must be
        # reported as such rather than fall through to the narrowness checks
        # (which would judge a round on a label nobody wrote).
        if not kind.startswith(("Full", "Scoped", "Sampled")):
            missing.insert(0, "kind")
        if missing:
            out.append(
                Discrepancy(
                    kind="round coverage unreported",
                    detail=(
                        f"{skill}: last round closed without recording "
                        + ", ".join(missing)
                        + " — how much of the scope it covered is unknown"
                    ),
                    suggestion=(
                        "fill the Tier-0 coverage line in the round header "
                        "(_shared/fanout-evidence.md § Tier 0)"
                    ),
                )
            )
            continue

        manifest, opened, workers = r["manifest"], r["opened"], r["workers"]
        solo_reason = str(r.get("solo_reason", "")).strip()

        # `workers 0` is legitimate — it is the base path for /test-audit and
        # the only path on a harness with no sub-agent primitive — but ONLY as a
        # declared decision. This check sits OUTSIDE the Full gate on purpose:
        # scoping it to Full rounds would make bare `Sampled` a free escape
        # hatch, turning every check off at once.
        if workers == 0 and not solo_reason:
            out.append(
                Discrepancy(
                    kind="solo round with no stated reason",
                    detail=(
                        f"{skill}: last round ran solo (workers 0) with no "
                        f"reason recorded (kind: {kind})"
                    ),
                    suggestion=(
                        "solo is a declared decision — state why (no sub-agent "
                        "primitive, or scope small enough to open in full)"
                    ),
                )
            )

        # A narrowed round is exempt from the look-ratio only if it says what it
        # narrowed to. `Sampled (highest-exposure modules)` declared its own
        # narrowness; a bare `Sampled` declared nothing and would otherwise buy
        # silence for free — the basis is the entire content of the claim.
        if not kind.startswith("Full"):
            if not re.search(r"\([^)]*\w[^)]*\)", kind):
                out.append(
                    Discrepancy(
                        kind="narrowed round with no stated basis",
                        detail=(
                            f"{skill}: last round declared `{kind}` without "
                            "naming what it covered — opened "
                            f"{opened} of {manifest}{of_repo}"
                        ),
                        suggestion=(
                            "name the subtree or the sampling basis, e.g. "
                            "`Sampled (highest-exposure modules)`"
                        ),
                    )
                )
            continue

        grepped = r.get("grepped")
        looked = opened + (grepped if isinstance(grepped, int) else 0)
        if manifest > 0 and looked * LOW_LOOK_RATIO < manifest:
            pct = 100.0 * looked / manifest
            out.append(
                Discrepancy(
                    kind="full round covered a fraction of its scope",
                    detail=(
                        f"{skill}: declared Full over {manifest} files"
                        f"{of_repo} but looked at {looked} ({pct:.1f}%) — "
                        f"opened {opened}, workers {r['workers']}"
                    ),
                    suggestion=(
                        "re-run with sub-agent dispatch, or relabel the round "
                        "Sampled and name the basis — a Full label over 1/3 "
                        "coverage overstates what was reviewed"
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
        triaged_verdict = b.get("triaged_verdict", "")
        triaged_tasks = list(b.get("triaged_tasks") or [])
        # `Triaged:` records the verdict; `Flag:` presence is what the two
        # drainers actually route on. /triage writes both together, so a
        # `flag` verdict with no `Flag:` line is a malformed record — and it
        # fails toward the CHEAP lane: /auto-fix's pool test is "no Flag:
        # line", so it would claim a batch the record says needs judgment.
        # Treat the record as absent so the batch routes back to /triage. Note
        # this changes the *advice*, not the actuator: /auto-fix's pool test is
        # its own ("no Flag: line") and does not read Triaged:, so the refusal
        # rule shipped in auto-fix/SKILL.md § 1a is the half that closes the
        # hazard. The mirror case — `auto` verdict WITH a `Flag:` line — routes
        # to the expensive lane, which is safe, but the record is still wrong
        # and nothing else would ever say so.
        record_conflict = bool(triaged_verdict) and (
            (triaged_verdict == "flag") != has_flag
        )
        has_triage_record = bool(triaged_verdict) and not record_conflict
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
            if not has_triage_record:
                # No durable verdict — /triage has never classified this batch,
                # or its `Flag:` tag predates the `Triaged:` record and so has
                # unknown provenance. Either way it needs classifying, and a
                # bare `Flag:` line is not evidence that anything read it.
                next_action = "/triage will classify (then /auto-fix or /auto-judge picks it up)"
                if record_conflict:
                    next_action += (
                        " — malformed record: Triaged: says flag but there is no"
                        " Flag: line, so /auto-fix would claim it"
                    )
                elif has_flag:
                    next_action += " — unstamped Flag: tag, provenance unknown"
            elif has_flag:
                # Truncate cleanly without leaving an unclosed parenthesis from the reason.
                reason_short = flag_reason[:55].rstrip()
                if len(flag_reason) > 55:
                    reason_short += "…"
                next_action = f"/auto-judge will pick this up — flag: {reason_short}"
                if triaged_tasks:
                    next_action += (
                        f" ({len(triaged_tasks)} of {len(batch_task_ids)} tasks need judgment)"
                    )
            else:
                next_action = "/auto-fix will pick this up — triaged auto"
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
                has_triage_record=has_triage_record,
                triaged_verdict=triaged_verdict,
                triaged_tasks=triaged_tasks,
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
    # `Review Ready` batches, as (number, title). Kept OUTSIDE review_batches on
    # purpose: that list (and the --json payload built from it) filters to
    # Pending/In Progress, and /roadmap documents that filter as a premise. The
    # recommendation cascade still needs the one live status that waits on a
    # human (Phase 222, Q-014) — so it rides its own field, read from the raw
    # headers, and the payload contract is untouched. Defaulted so existing
    # fixture constructors stay valid; run_survey always populates it.
    review_ready_batches: list[tuple[int, str]] = field(default_factory=list)


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
                pending_doc=_pending_doc_for(
                    main_root, branch, lock, worktree
                ),
                main_root=main_root,
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
        review_ready_batches=[
            (b["number"], b.get("title", ""))
            for b in review_batches_raw
            if b.get("status") == "Review Ready"
        ],
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
    if s.review_ready_batches:
        nums = ", ".join(str(n) for n, _ in s.review_ready_batches)
        lines.append(
            f"REVIEW READY (waiting on /review-close): batch {nums}"
        )
        lines.append("")
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
    /triage if any pending batch lacks a Triaged: record → /auto-fix and/or /auto-judge →
    continue in-progress → parked → awaiting approval → resume planning →
    /roadmap (deep queue) or /auto-build (shallow) → idle.
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

    # P2: review batches with all tasks Doc-Work'd — or header status
    # `Review Ready`, the one live status that needs a human (Phase 222,
    # Q-014). The header arm comes first: it is the batch's own explicit
    # declaration, and such a batch never enters s.review_batches (the
    # Pending/In-Progress filter), so without this arm the cascade was blind
    # to exactly the state that outranks everything below.
    if s.review_ready_batches:
        num, _title = s.review_ready_batches[0]
        return Recommendation(
            command=f"/review-close (batch {num})",
            reason=(
                f"Batch {num} header reads `Review Ready` — review work done, "
                "waiting on a human to run /review-close"
            ),
        )
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

    # P4: pending unclaimed batches — route via the Triaged: verdict record
    pending_unclaimed = [rb for rb in s.review_batches if rb.state == "pending (not claimed)"]
    if pending_unclaimed:
        # Untriaged is keyed on the durable `Triaged:` verdict, not on the
        # absence of a `Flag:` tag. Keying on `Flag:` conflated two states a
        # reader cannot distinguish — "classified auto" and "never read" both
        # present as no-tag — so an all-auto queue re-recommended /triage
        # forever, and a legacy `Flag:` tag of unknown provenance was accepted
        # as a prior verdict.
        # `triaged_verdict == "flag"` with no `Flag:` line is a malformed
        # record. `_classify_review_batches` already clears `has_triage_record`
        # for it, but the same invariant is asserted here rather than assumed:
        # the failure direction is toward /auto-fix (whose pool test is "no
        # Flag: line"), i.e. a batch the record says needs judgment being
        # claimed for mechanical fixing, and that is not a state to reach by
        # trusting one layer.
        def _untriaged(rb):
            return not rb.has_triage_record or (
                rb.triaged_verdict == "flag" and not rb.has_flag
            )

        untriaged = [rb for rb in pending_unclaimed if _untriaged(rb)]
        flagged = [rb for rb in pending_unclaimed if not _untriaged(rb) and rb.has_flag]
        auto = [rb for rb in pending_unclaimed if not _untriaged(rb) and not rb.has_flag]
        if untriaged:
            # Some batches not yet triaged — /triage is the prereq before /auto-fix or /auto-judge
            n_untriaged = len(untriaged)
            sample = [f"batch {rb.batch_number}" for rb in untriaged[:3]]
            sample_str = ", ".join(sample)
            if n_untriaged > 3:
                sample_str += f", +{n_untriaged - 3} more"
            n_unstamped_flag = sum(1 for rb in untriaged if rb.has_flag)
            detail_lines = [f"untriaged: {sample_str}"]
            if n_unstamped_flag:
                detail_lines.append(
                    f"{n_unstamped_flag} of them carry an unstamped Flag: tag "
                    f"(no Triaged: record — provenance unknown, will be re-read)"
                )
            return Recommendation(
                command="/triage",
                reason=(
                    f"{n_untriaged} pending batch(es) have no Triaged: record; "
                    f"/triage classifies them as auto vs flag, then /auto-fix "
                    f"and /auto-judge route accordingly"
                ),
                detail_lines=detail_lines,
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

    # P4e: code committed, documentation not yet written (Q-019).
    #
    # Placed above P5 because this task is FURTHER along than an in-progress one
    # — it has a build commit and a `Doc-Work:` trailer, it simply has no
    # pending-doc — and below P4 so batch work still outranks single-task work,
    # which is the ordering every tier here already follows.
    #
    # **This arm is not optional decoration; without it the state falls through
    # the whole cascade.** It is not "in progress" (P5 requires the ABSENCE of a
    # trailer) and not "ready for /review-close" (P1/P3 now require a
    # pending-doc), so a repo whose only active task sat in this state would
    # have skipped to P7 and been told to pick up new roadmap work while a
    # finished build waited to be documented. Adding a state without adding its
    # routing arm is the same defect one layer up: the survey would know the
    # answer and not say it.
    docs_pending = [t for t in s.tasks if t.state == "code committed, docs pending"]
    if docs_pending:
        t = docs_pending[0]
        return Recommendation(
            command=f"/document-work {t.task_id}",
            reason=(
                f"{t.task_id} has {t.commits_ahead} commit(s) and a Doc-Work: "
                f"trailer, but no pending-doc — /claim-task's executor emits "
                f"that trailer, so documentation has not been written yet"
            ),
            detail_lines=[
                "skipping straight to /review-close would lose the simplify "
                "pass, the pending-doc Step 4c consolidates, and the "
                "follow-up-stub check"
            ],
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

    # P6a/P6b: stalled claims — parked, or waiting at Step 7d's human gate.
    #
    # Ranked here, immediately above `planning`, and NOT above P5, because this
    # cascade's consistent logic is "further along ranks higher": P1/P3 have a
    # trailer and a pending-doc, P4e has commits plus a trailer, P5 has commits.
    # A parked or awaiting-approval claim has ZERO commits ahead — it is a
    # specialisation of `planning`, which is exactly why it used to be swallowed
    # by it, so it belongs where `planning` belongs.
    #
    # Visibility is not what the rank buys. The ACTIVE WORK table renders every
    # task with its own state and notes, so a park is legible there whatever the
    # cascade names; the cascade names one move. Ranking a park above live
    # in-progress work would tell a human to go answer a question while a build
    # sits half-finished, which is not the trade this defect was about.
    parked = [t for t in s.tasks if t.state == _PARKED_STATE]
    if parked:
        t = parked[0]
        more = f" ({len(parked) - 1} more parked)" if len(parked) > 1 else ""
        return Recommendation(
            command=t.next_action,
            reason=(
                f"{t.task_id} is parked and is waiting on a human decision"
                f"{more} — see the detail line for what the evidence is"
            ),
            detail_lines=list(t.notes),
        )

    awaiting = [t for t in s.tasks if t.state == _AWAITING_STATE]
    if awaiting:
        t = awaiting[0]
        more = f" ({len(awaiting) - 1} more waiting)" if len(awaiting) > 1 else ""
        return Recommendation(
            command=t.next_action,
            reason=(
                f"{t.task_id}'s plan was reviewed and classified clean; it is "
                f"waiting on your approval at /claim-task Step 7d{more}"
            ),
            detail_lines=list(t.notes),
        )

    # P6c: planning tasks
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
    then stalled claims (parked, awaiting approval), then planning, then
    discrepancies."""
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
    # 2b. Code committed, docs pending (Q-019). Between the close tiers and
    # in-progress, matching `_recommended_next`'s P4e placement: this task is
    # further along than an in-progress one and not yet closable.
    #
    # **This function is the third surface the new state had to reach, and the
    # first cut reached two.** With the arm absent the task fell out of the
    # ordered list entirely and the "(no active Sysop work; pick up a new task
    # with /next-task)" fallback fired — while RECOMMENDED NEXT, three lines
    # above it, said `/document-work FEAT-1`. One report contradicting itself.
    # Found by the round; it is verbatim the defect this phase's own routing
    # comment describes ("a state with no routing arm is worse than no state").
    for ts in s.tasks:
        if ts.state == "code committed, docs pending":
            out.append(f"/document-work {ts.task_id} (trailer present, no pending-doc)")
    # 3. In-progress (Doc-Work next)
    for ts in s.tasks:
        if ts.state == "in progress":
            out.append(f"/document-work {ts.task_id} (no Doc-Work trailer yet)")
    # 3b. Stalled claims — parked, then awaiting approval. Both sit with
    # `planning` (all three are 0-commits-ahead states) and above it, since a
    # named human action beats "resume planning". Q-019's round is the reason
    # this arm exists at all: a state wired into `_recommended_next` and not
    # into THIS function drops out of the ordered list entirely, and the report
    # then contradicts itself three lines apart.
    for ts in s.tasks:
        if ts.state == _PARKED_STATE:
            out.append(f"{ts.task_id} is parked — {ts.next_action}")
    for ts in s.tasks:
        if ts.state == _AWAITING_STATE:
            out.append(f"{ts.task_id} awaits your approval — {ts.next_action}")
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
            # Q-019. Without this the field is WRITE-ONLY — three writes, no
            # reader outside its own unit tests — on the surface this skill
            # calls "for orchestrator consumption". The tree already carries the
            # guard for this exact class one dataclass over
            # (`test_flag_contract.py::test_json_render_carries_the_triage_record`:
            # "dropping the three keys from the render is invisible to every
            # other test"). Found by the round.
            "pending_doc": t.pending_doc,
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
            "has_triage_record": r.has_triage_record,
            "triaged_verdict": r.triaged_verdict,
            "triaged_tasks": r.triaged_tasks,
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
