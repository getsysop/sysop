"""
sitrep_survey.py — Read-only situation report for Sysop.

Surveys locks, worktrees, branches, tasks/index.yml, and review_tasks.md;
classifies every active task into a deterministic lifecycle state via the
`Doc-Work:` git trailer (Phase 40); flags discrepancies between filesystem
reality and the state files; emits a scannable text report.

Never mutates state. Read-only by design.

Usage:
    python3 sysop/scripts/sitrep_survey.py             # text report
    python3 sysop/scripts/sitrep_survey.py --json      # JSON output (contract below)
    python3 sysop/scripts/sitrep_survey.py --stale-days 14

JSON contract (`--json`, `schema_version` 1). A consumer may rely on these keys:

    top level         schema_version, timestamp, main_root, head_short,
                      stale_days, tasks, review_batches, discrepancies,
                      open_roadmap_ids, failed_in_merged_batches,
                      recommended_next, suggested_order
    tasks[]           task_id, state, state_marker, branch, worktree,
                      commits_ahead, unpushed, has_lock, has_index_entry,
                      index_status, dirty, doc_work_ids, pending_doc,
                      next_action, notes, agent
    review_batches[]  batch_number, title, md_status, branch, has_lock,
                      has_branch, has_flag, flag_reason, has_triage_record,
                      triaged_verdict, triaged_tasks, total_tasks,
                      doc_worked_tasks, state, next_action, notes
    discrepancies[]   kind, detail, suggestion
    failed_in_merged_batches[]  batch_number, task
    recommended_next  null, or: command, reason, clear_nudge, detail_lines

`tasks[].state` takes the values in the first column of `/sitrep`'s state
table, lowercased and without markup, and `review_batches[].state` the values
in `/roadmap` Step 2a; tests compare both with what this file emits, as sets.
`tasks[].agent` is the lock's `agent:` (`claim_task.sh`'s third argument), ""
when there is no lock or it is unreadable (state `lock unreadable`): compare
it, not a YAML read of the lock. The `/auto-build --unattended` halt marker
reports as `discrepancies[].kind` `unattended auto-build halted`; other kinds
carry no promise. Keys and state values may be ADDED without a version change,
so give a reader a default arm. Removing or renaming a key, renaming a state,
or changing a value's type bumps `schema_version`. `next_action` and `notes`
are prose for a human: never key on their wording.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
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
# The schema's id grammar (`validate_tasks.py` `_TASK_ID_RE`): prefixes are project-chosen,
# so `ABC123` and `QA2-X` are ids too. A narrower pattern dropped their Doc-Work trailers.
TASK_ID_RE = re.compile(r"^[A-Z][A-Z0-9-]{2,80}$")
# `/claim-task` Step 3's generated name: the leading segment lowercased, then the whole id
# lowercased (`OPS-FOO` → `ops/ops-foo`, `ABC123` → `abc123/abc123`), for any prefix.
DERIVED_BRANCH_RE = re.compile(r"^([a-z][a-z0-9]*)/\1(?:-[a-z0-9-]*)?$")
SUBJECT_TASK_RE = re.compile(r"\(([A-Z][A-Z0-9]*-[A-Z0-9][A-Z0-9-]+)\)\s*$")


# ── Subprocess helpers ───────────────────────────────────────────


def _git(args: list[str], cwd: str | None = None, check: bool = False,
         hermetic: bool = False) -> str:
    """Run a git command, return stdout (stripped). On non-zero exit, return ''.

    Decoded with ``os.fsdecode``, not ``text=True`` (`Q-612`): git prints ref
    names and commit messages as raw bytes, so a non-UTF-8 packed ref or a commit
    object written without an encoding header ended the whole survey. The decode
    round-trips, so a name handed back to git still names the same ref.

    ``hermetic`` strips git's discovery variables, so ``cwd`` decides the
    repository. Pass it for a read that must run in a workspace other than the
    one the survey was invoked from: an inherited ``GIT_DIR`` overrides ``cwd``."""
    env = None
    if hermetic:
        env = {k: v for k, v in os.environ.items()
               if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=check,
            capture_output=True,
            timeout=15,
            env=env,
        )
        if r.returncode != 0:
            return ""
        return os.fsdecode(r.stdout).rstrip("\n")
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
    # Non-empty when the lock file could not be read or parsed: every field
    # above is then UNKNOWN, not empty, and the classifiers must not read an
    # empty `branch` as "claimed, no branch" (whose remedy is a release).
    unreadable: str = ""


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
    agent: str = ""  # the lock's `agent:` (Phase 361); "" with no lock


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


def _read_locks(main_root: Path, unreadable: list | None = None) -> list[Lock]:
    locks_dir = main_root / "sysop/runtime/locks"
    # Listed by `_list_locks_dir` (end of module), which names a listing that fails.
    names = _list_locks_dir(locks_dir, unreadable)
    out: list[Lock] = []
    for p in sorted(locks_dir / n for n in names if n.endswith(".lock")):
        if p.name == ".gitkeep":
            continue
        raw, exc = _load_lock_file(p)
        if exc is not None:
            _unreadable_input(p, exc, "this claim's lock fields are unknown, so its "
                              "state is reported as `lock unreadable`", unreadable)
        task_id = raw.get("task_id", p.stem)
        out.append(
            Lock(
                task_id=task_id,
                path=p,
                # `or ""`, not a default: a key present with an empty value
                # loads as None, and `str(None)` is the string "None" — which
                # made a lock reading `branch:` classify as a claim on a
                # branch literally named None instead of `claimed, no branch`
                # (Phase 252's round, execute lens).
                status=str(raw.get("status") or ""),
                agent=str(raw.get("agent") or ""),
                branch=str(raw.get("branch") or ""),
                workspace=str(raw.get("workspace") or ""),
                started=str(raw.get("started") or ""),
                expires=str(raw.get("expires") or ""),
                raw=raw,
                unreadable=_input_reason(exc) if exc is not None else "",
            )
        )
    return out


def _printable(path: Path) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", "?", str(path))


def _input_reason(exc: BaseException) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", f"{type(exc).__name__}: {exc}")[:300]


def _input_remedy(exc: BaseException) -> str:
    """The repair that matches the failure: a permission error is not fixed by
    re-encoding, and a markdown file has no YAML to repair."""
    if isinstance(exc, UnicodeDecodeError):
        return "re-save it as UTF-8 (the reason names the bad byte's position)"
    if isinstance(exc, OSError):
        return "restore read access to it (or restore the file)"
    if isinstance(exc, yaml.YAMLError):
        return "repair its YAML (the reason names the line)"
    if isinstance(exc, json.JSONDecodeError):
        return "repair its JSON (the reason names the line)"
    return "repair its contents (the reason says what is wrong)"


def _unreadable_input(path: Path, exc: BaseException, consequence: str,
                      unreadable: list | None) -> None:
    """Name an input a reader absorbed. `run_survey` passes a list and turns each
    entry into a DISCREPANCIES line and routes RECOMMENDED NEXT to the repair;
    any other caller gets a stderr warning. Absorbing silently is what this
    exists to stop: an unreadable index read as `{}` made /sitrep report "idle"
    over a live claim (Phase 333's round)."""
    where = re.sub(r"[\x00-\x1f\x7f]", "?", str(path))
    reason = _input_reason(exc)
    entry = (where, reason, consequence, _input_remedy(exc))
    if unreadable is None:
        print(f"WARN: sitrep_survey: could not read {where} ({reason}) — {consequence}",
              file=sys.stderr)
    else:
        unreadable.append(entry)


# The lock fields the writers interpolate unquoted from free input (`agent:` is
# `claim_task.sh`'s third argument), read as the line readers read them
# (`claim_task.sh`'s awk, `/review-close`'s `line.partition(":")`) — the reading the
# writers mean. YAML cut a path at ` #`, typed a branch named `0123`, `true` or
# `2026-09-01`, and raised on a value holding `: `.
LINE_READ_LOCK_KEYS = ("workspace", "branch", "agent")


def _line_read_lock_fields(text: str) -> dict[str, str]:
    """Each `LINE_READ_LOCK_KEYS` field as `/review-close` reads it: the FIRST line
    whose text before its first `:` is exactly the key, the rest `.strip()`ped."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key in LINE_READ_LOCK_KEYS and key not in out:
            out[key] = value.strip()
    return out


def _quote_line_read_lock_fields(text: str) -> str:
    """`text` with every `LINE_READ_LOCK_KEYS` line's value rewritten as a YAML
    single-quoted scalar of its line reading (`'` doubled), so YAML reads the same
    string. Line breaks are kept, so a later parse error names the same line."""
    out = []
    for line in text.splitlines(keepends=True):
        body = line.splitlines()[0]
        key, sep, value = body.partition(":")
        if sep and key in LINE_READ_LOCK_KEYS:
            quoted = value.strip().replace("'", "''")
            line = f"{key}: '{quoted}'{line[len(body):]}"
        out.append(line)
    return "".join(out)


def load_lock_text(text: str) -> Any:
    """A lock file's text parsed as YAML, with each `LINE_READ_LOCK_KEYS` field read
    as its line reads. Raises whatever `yaml.safe_load` raises, which is not only
    `yaml.YAMLError` (`ValueError` for `2026-09-31`, `RecursionError`; `Q-621`).

    Public for `scope_overlap.py`, which imports it rather than carry a second copy.
    A value containing `: ` is not valid YAML and made the whole lock unreadable, so
    a lock that fails to parse is parsed again with each such line's value as a
    single-quoted scalar; a lock that parses is parsed exactly as before. A mapping
    then takes each key's line reading, and loses a key no exact line carries."""
    try:
        data = yaml.safe_load(text)
    except Exception:
        quoted = _quote_line_read_lock_fields(text)
        if quoted == text:
            raise
        data = yaml.safe_load(quoted)
    if isinstance(data, dict):
        fields = _line_read_lock_fields(text)
        for key in LINE_READ_LOCK_KEYS:
            if key in fields:
                data[key] = fields[key]
            else:
                data.pop(key, None)
    return data


def _load_lock_file(path: Path) -> tuple[dict[str, Any], BaseException | None]:
    """(fields, None), or ({}, the exception) when the lock cannot be read or parsed.

    An empty file or a YAML list/scalar parses to no fields, which is "unknown",
    not "empty": `{}` routed it to the release/drainer arms an unreadable lock
    was taken off. A MAPPING without `branch:` is a readable lock and stays
    `claimed, no branch`."""
    try:
        data = load_lock_text(path.read_text(encoding="utf-8"))
    except Exception as exc:  # PyYAML raises KeyError, TypeError, … too (`Q-621`)
        return {}, exc
    if not isinstance(data, dict):
        return {}, ValueError(f"parsed to no fields ({type(data).__name__})")
    return data, None


def _parse_lock_file(path: Path, unreadable: list | None = None) -> dict[str, Any]:
    """Lock files are YAML-shaped. Parse defensively; return {} on failure, and
    name the failure (see `_unreadable_input`)."""
    data, exc = _load_lock_file(path)
    if exc is not None:
        _unreadable_input(path, exc, "this claim's lock fields are unknown", unreadable)
    return data


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


def _read_index(main_root: Path, unreadable: list | None = None) -> dict[str, dict[str, Any]]:
    p = main_root / "tasks" / "index.yml"
    if not p.is_file():
        return {}
    try:
        with p.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:  # any read or parse failure, not only YAMLError (`Q-621`)
        _unreadable_input(p, exc, "the survey read the task index as EMPTY, so every "
                          "task state in this report is unreliable", unreadable)
        return {}
    # YAML that parses with the wrong shape (a top-level list, `tasks: 5`) is unreadable
    # too; it used to crash the survey with a traceback at exit 1 (Phase 336's round).
    tasks = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(tasks, (list, type(None))):
        got = type(tasks if isinstance(data, dict) else data).__name__
        _unreadable_input(p, ValueError(f"expected a mapping whose `tasks:` is a list, got {got}"),
                          "the survey read the task index as EMPTY, so every "
                          "task state in this report is unreliable", unreadable)
        return {}
    out: dict[str, dict[str, Any]] = {}
    for t in tasks or []:
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

# `Q-118`: a task `close_batch.sh` left open because its block carries a FAIL
# annotation. The three patterns and the walk below mirror close_batch.sh's
# CLOSE_AWK (`is_open_task`, `is_failed`, `is_continuation`) so that this
# reader counts exactly the tasks that script held. That is why an unbolded
# `- [ ] task` counts here although `_TASK_LINE_RE` above would not see it.
_OPEN_TASK_RE = re.compile(r"^- \[[ /]\]")
_FAILED_ANNOTATION_RE = re.compile(r"^\s*>\s*[*_]*failed[*_]*\s*:", re.IGNORECASE)
_OPEN_TASK_LABEL_RE = re.compile(
    r"^- \[[ /]\][ \t]*(?:\*\*(?P<bold>[^*\n]+)\*\*|(?P<plain>[^\n]+))"
)


def _read_near_miss_failed(main_root: Path) -> list[tuple[int, str]]:
    """`_near_miss_failed` over `review_tasks.md`. An unreadable file yields
    nothing here: `_read_review_batches` already reports it."""
    try:
        text = (main_root / "review_tasks.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    lines = text.split("\n")  # not splitlines(): awk splits on \n alone
    return _near_miss_failed(lines, _fenced_mask(lines))


def _near_miss_failed(lines, fenced):
    """``(number, label)`` for the failed tasks of a `Merged` batch whose header
    the strict pattern rejects (an ASCII hyphen, trailing whitespace).

    ``close_batch.sh`` still closes such a batch, through the fallback in its
    ``find_batch_range``: the header is ``^### Batch <N> ``, the status is the
    header's last backtick token, and the range ends before the next unfenced
    line starting ``##``. This mirrors that, so a task it held there is named.
    """
    out = []
    for i, line in enumerate(lines):
        if fenced[i] or _BATCH_HEADER_RE.match(line):
            continue
        m = re.match(r"^### Batch (\d+) ", line)
        status = re.search(r"`([^`]+)`\s*$", line)
        if not m or not status or status.group(1).strip() != "Merged":
            continue
        end = next((j for j in range(i + 1, len(lines))
                    if lines[j].startswith("##") and not fenced[j]), len(lines))
        out.extend((int(m.group(1)), task)
                   for task in _failed_open_tasks(lines, fenced, i + 1, end))
    return out


def _failed_open_tasks(lines, fenced, start, end):
    """Labels of the open tasks in ``lines[start:end]`` whose block carries a
    ``> Failed:`` annotation, as close_batch.sh's CLOSE_AWK decides it.

    A task owns its line plus every indented, non-blank line under it; an
    annotation is tested before the block-end test, so a column-0 one directly
    under the task counts. Only the task line must sit in the range and outside
    a fence, so a block may run past ``end``, as it can in close_batch.sh.
    """
    out = []
    pend = None
    for i in range(start, len(lines)):
        line = lines[i]
        if pend is not None:
            if _FAILED_ANNOTATION_RE.match(line):
                if not fenced[pend]:
                    m = _OPEN_TASK_LABEL_RE.match(lines[pend])
                    label = (m.group("bold") or m.group("plain")) if m else lines[pend]
                    out.append(label.strip()[:60])
                pend = None
                continue
            if line[:1].isspace() and line.strip():
                continue
            pend = None
        if i >= end:
            break
        if _OPEN_TASK_RE.match(line):
            pend = i
    return out


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


def _read_review_batches(main_root: Path, unreadable: list | None = None) -> list[dict[str, Any]]:
    p = main_root / "review_tasks.md"
    if not p.is_file():
        return []
    out: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    try:
        with p.open(encoding="utf-8") as f:
            lines = f.readlines()
    except (OSError, UnicodeDecodeError) as exc:
        _unreadable_input(p, exc, "no review batch is shown, including any in "
                          "progress", unreadable)
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
                current["line_end"] = idx
                out.append(current)
                current = None
            continue
        m = _BATCH_HEADER_RE.match(line)
        if m:
            if current is not None:
                current["line_end"] = idx
                out.append(current)
            current = {
                "line_start": idx,
                "line_end": len(lines),
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
                current["line_end"] = idx
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
    plain = [ln.rstrip("\n") for ln in lines]
    for b in out:
        b["failed_open"] = (
            _failed_open_tasks(plain, fenced, b["line_start"], b["line_end"])
            if b["status"] == "Merged" else []
        )
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
    """List commits on `branch` reachable from NEITHER the local default branch
    nor its remote-tracking ref (`_default_branch_refs`).

    Both, with `--not`, because each excludes a class the other admits. An
    unpushed claim commit on the LOCAL default branch (`batch_work.sh` commits
    `docs: claim Batch N` and never pushes; `/claim-task` likewise) is reachable
    from the local ref but not from `origin/<default>` — counted against the
    remote-tracking ref alone, every ordinary batch park read as `parked, work
    in progress` with the claim commit as its "work" (Phase 252's round,
    execute lens, reproduced). An upstream commit not yet pulled is reachable
    from `origin/<default>` but not from the local ref — counted against the
    local ref alone, a branch cut from the remote tip reads other people's
    commits as its own. No resolvable default branch yields `[]`, and
    `run_survey` reports that as a discrepancy (`Q-365`).

    **And every recorded PR head (`Q-623`).** Under `pr` policy a branch cut
    before an earlier close's squash still carries that close's claim flips as
    ancestors, and after the squash they are reachable from neither ref above:
    a squash rewrites them into one commit, so ancestry cannot see they landed.
    `/review-close` Step 4d records each merged PR's head as
    `refs/sysop/merged-pr-heads/<PR>`, and that head contains every local-only
    commit the close carried. Excluding it is what stops an unstarted claim
    reading `in progress` and a dead one never reading `stale`. With no head
    recorded the glob matches nothing and the count is unchanged.
    """
    bases = _default_branch_refs(main_root)
    if not bases:
        return []
    raw = _git(
        ["log", "--pretty=format:%H%x1f%s%x1f%aI%x1f%B%x1e", branch, "--not", *bases,
         f"--glob={MERGED_PR_HEADS_GLOB}"],
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


#: Where `/review-close` Step 4d records each merged PR's head under `pr` policy
#: (`Q-623`). One ref per PR, named by its number.
MERGED_PR_HEADS = "refs/sysop/merged-pr-heads/"
MERGED_PR_HEADS_GLOB = MERGED_PR_HEADS + "*"


def _containing_heads(branch: str, main_root: Path) -> list[str]:
    """Every recorded PR head ref that contains `branch`'s tip, lowest PR first.

    The tip is read from `refs/heads/<branch>`: a bare name resolves a same-named tag
    first, which landed a branch with unmerged work (Phase 360, round 1, lens A)."""
    if not branch:
        return []
    tip = _git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}"],
               cwd=str(main_root))
    if not tip:
        return []
    out = _git(["for-each-ref", "--contains", tip, "--format=%(refname)",
                MERGED_PR_HEADS], cwd=str(main_root))
    refs = [r for r in out.splitlines() if r.startswith(MERGED_PR_HEADS)]
    return sorted(refs, key=lambda r: (len(r), r))


def _landed_by(branch: str, main_root: Path) -> str:
    """The number of a recorded PR whose head contains `branch`'s tip, or "".

    Containment alone is not "merged": a recorded head contains the tip of every
    branch its close merged, and ALSO of anything cut from the local default
    branch before that close — an unstarted claim in any workspace mode, and any
    branch that is an ancestor of `main`. `_landed_claim` adds what does decide it.
    """
    heads = _containing_heads(branch, main_root)
    return heads[0][len(MERGED_PR_HEADS):] if heads else ""


def _held_docs(main_root: Path, branch: str) -> list[tuple[str, dict]]:
    """(name, frontmatter) of each pending doc in the main checkout's
    `sysop/runtime/pending-docs/` whose frontmatter `branch:` is `branch` — the
    held docs Step 6 keeps a merged branch alive for. Unparseable docs are
    skipped: they name nobody."""
    out: list[tuple[str, dict]] = []
    pd = main_root / "sysop" / "runtime" / "pending-docs"
    try:
        docs = sorted(pd.glob("*.md")) if pd.is_dir() else []
    except OSError:
        return out
    for doc in docs:
        try:
            # `errors="replace"`, as Steps 3c and 4c read it: a stray byte must not hide a
            # held doc (and its `hold:`) that the close still holds.
            m = _PENDING_DOC_FM_RE.match(doc.read_text(encoding="utf-8", errors="replace"))
            fm = yaml.safe_load(m.group(1)) if m else None
        except Exception:  # noqa: BLE001 — a doc that cannot be read names no branch
            continue
        if isinstance(fm, dict) and str(fm.get("branch") or "") == branch:
            out.append((doc.name, fm))
    return out


def _held_doc_names(main_root: Path, branch: str) -> list[str]:
    return [name for name, _ in _held_docs(main_root, branch)]


def _doc_holds(main_root: Path, branch: str) -> list[str]:
    """The `hold:` reasons (`Q-625`) of the held docs naming `branch`.

    Truthy, as `/review-close` Step 4c 1c reads the field
    (`pending_doc_hold.py`): a malformed value still holds."""
    return [str(fm["hold"]).strip() or "(no reason given)"
            for _, fm in _held_docs(main_root, branch) if fm.get("hold")]


def _landed_claim(main_root: Path, branch: str, lock: "Lock | None",
                  worktree: "Worktree | None", dirty: bool) -> str:
    """The PR number that landed this claim's branch, or "" (`Q-623` / `Q-546`).

    Three conditions, each closing a population containment alone admits:

    1. **A held doc names the branch** in the main checkout's pending-docs. That
       is the only reason a close leaves a merged branch alive (Step 6's HARD
       RULE), and it excludes an unstarted claim, whatever its workspace mode,
       and every branch no claim produced.
    2. **A recorded head contains the branch's tip.**
    3. **No live tip has moved past that head.** A `--clone` claim's work lives
       in its own clone and may be pushed to `origin/<branch>` while the
       primary's ref stays at the cut point, so the lock's workspace ref, the
       remote-tracking ref and a linked worktree are each checked, and a dirty
       workspace on the branch is live work (`_live_work_past`, shared with
       `_merged_into_default`, the `direct` twin).
    """
    if not branch or not _held_doc_names(main_root, branch):
        return ""
    heads = _containing_heads(branch, main_root)
    if not heads:
        return ""
    if _live_work_past(main_root, branch, lock, worktree, dirty, heads):
        return ""
    return heads[0][len(MERGED_PR_HEADS):]


def _merged_into_default(main_root: Path, branch: str, lock: "Lock | None",
                         worktree: "Worktree | None", dirty: bool) -> str:
    """The default-branch ref a `direct` close merged this claim's branch into, or "" (`Q-643`).

    `_landed_claim`'s twin for the policy that records no PR head. `/review-close` Step 4a
    merges onto `main` itself — rebase-then-`--ff-only` for a local-only branch, `--no-ff` for
    a published one — so the branch's tip becomes an ancestor of the default branch. A squash
    breaks ancestry, so this does not fire after a squash-merged `pr` close. A PR merged with
    a merge commit (or before Phase 352 recorded heads) does leave the tip an ancestor, and
    reads merged here too, which is right: its work is on the default branch. No policy read
    is needed.

    Its conditions are `_landed_claim`'s, with ancestry in place of the recorded head:

    1. **A pending doc names the branch.** Ancestry alone admits every branch no claim
       produced. A doc does not exclude a claim with 0 commits whose `/document-work` wrote it into
       the main checkout's pending-docs: that reads merged here and is reviewed by the close, whose
       step 0b also asks for the `held_since:` stamp (Phase 360).
    2. **The local branch's tip is an ancestor of the local default branch or of its
       remote-tracking ref** (`_default_branch_refs`): a close whose push has not happened yet
       has merged it into the local ref only. Read from `refs/heads/<branch>`, because a bare
       name resolves a same-named tag first. No resolvable default branch is no verdict.
    3. **The branch is not the default branch itself.** `/document-work` may write
       `branch: main`, and a held doc can name it; it is an ancestor of itself.
    4. **No live tip has moved past it, and no workspace on it is dirty** (`_live_work_past`).

    Returns the first containing ref in `_default_branch_refs` order — the local branch first.
    """
    if not branch or not _held_doc_names(main_root, branch):
        return ""
    if branch == resolve_default_branch(main_root):
        return ""
    tip = _git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}"],
               cwd=str(main_root))
    if not tip:
        return ""
    bases = [ref for ref in _default_branch_refs(main_root) if _is_ancestor(tip, ref, main_root)]
    if not bases:
        return ""
    if _live_work_past(main_root, branch, lock, worktree, dirty, bases):
        return ""
    return bases[0]


def _live_work_past(main_root: Path, branch: str, lock: "Lock | None",
                    worktree: "Worktree | None", dirty: bool, containers: list[str]) -> bool:
    """Whether work on `branch` lives somewhere `containers` (refs that contain the branch's
    local tip) do not reach: a dirty workspace on the branch, or a tip past every container.

    The tips checked are the lock's workspace ref (a `--clone` claim's work lives in its own
    clone, while the primary's ref stays at the cut point) and `origin/<branch>` as last
    fetched. The dirty workspaces are a linked worktree, the lock's workspace, and the primary
    checkout when its HEAD is on the branch — a `--branch` claim works in the primary itself,
    so its lock's workspace is skipped as the main checkout and no worktree is linked.
    """
    if worktree is not None and dirty:
        return True
    tips: list[str] = []
    if lock is not None and lock.workspace:
        ws = Path(lock.workspace)
        try:
            is_dir = ws.is_dir()
        except (OSError, ValueError):
            is_dir = False
        if is_dir and not _same_dir(ws, main_root):
            tip = _git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}"],
                       cwd=str(ws), hermetic=True)
            if tip:
                tips.append(tip)
            on_branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=str(ws), hermetic=True)
            status = _git(["status", "--porcelain"], cwd=str(ws), hermetic=True).splitlines()
            if on_branch == branch and [ln for ln in status
                                        if not (ln.startswith("?? ") and _ignored_symlink(ws, ln[3:], main_root))]:
                return True
    # Tracked changes only in the primary: an untracked scratch file is ordinary in a live
    # repository, which is why `/review-close` Step 6 gates the primary on
    # `git diff --quiet HEAD --` and not on `status --porcelain`.
    if (_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=str(main_root)) == branch
            and _git(["status", "--porcelain", "--untracked-files=no"], cwd=str(main_root))):
        return True
    remote = _default_remote(main_root) or "origin"
    rtip = _git(["rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}^{{commit}}"],
                cwd=str(main_root))
    if rtip:
        tips.append(rtip)
    return any(not any(_is_ancestor(tip, c, main_root) for c in containers) for tip in tips)


def _ignored_symlink(where: Path, entry: str, main_root: Path) -> bool:
    """An untracked symlink whose target the repository ignores (BeanRider ISSUE-0043): not
    live work. `/review-close` Step 1-pre's `noise()` and step 0b read the same shape."""
    p = os.path.join(str(where), entry)
    if not os.path.islink(p):
        return False
    target = os.path.normpath(os.path.join(os.path.dirname(p), os.readlink(p)))
    try:
        r = subprocess.run(["git", "check-ignore", "-q", target], cwd=str(main_root),
                           capture_output=True, timeout=15)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return r.returncode == 0


def _is_ancestor(a: str, b: str, main_root: Path) -> bool:
    try:
        r = subprocess.run(["git", "merge-base", "--is-ancestor", a, b], cwd=str(main_root),
                           capture_output=True, timeout=15)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return r.returncode == 0


def _same_dir(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except (OSError, ValueError):
        return False


# `Q-383` (Phase 368): the name `resolve_default_branch` may return. The bash twin's
# `_default_branch_name_ok` enumerates the same set; Python's `[A-Za-z]` is a code-point
# range, not a collation one, so it is locale-proof as written. Not `\w`, which matches
# non-ASCII letters. A non-UTF-8 ref name decodes (`os.fsdecode`) to lone surrogates,
# which fall outside the class and are refused like any other non-ASCII byte.
_DEFAULT_BRANCH_NAME = re.compile(r"[A-Za-z0-9._/][A-Za-z0-9._/-]*")


def _default_branch_name_ok(name: str) -> bool:
    return bool(_DEFAULT_BRANCH_NAME.fullmatch(name))


def _quote_refused_name(name: str) -> str:
    """A refused name rendered for a report: every character outside printable ASCII
    (including a lone surrogate, which is what a non-UTF-8 ref decodes to) as a `\\uNNNN`
    escape, then shell-quoted, so it is inert if copied into a shell and puts no raw
    bytes on a terminal — the counterpart of the bash twin's `printf %q` under the C
    locale. Not `ascii()`, whose double-quoted form for a name containing `'` leaves
    `$(…)` live in a shell."""
    return shlex.quote("".join(c if " " <= c <= "~" else f"\\u{ord(c):04x}" for c in name))


def resolve_default_branch(main_root: Path, refused: list[str] | None = None) -> str:
    """The repository's default branch NAME — `main`, `master`, `develop` … — or "".

    The Python twin of `_git_lib.sh`'s `resolve_default_branch`, kept to the
    same steps so the bash lifecycle scripts and this survey cannot disagree
    about which branch a claim is "ahead of" (`Q-365`). Pinned to the bash side
    behaviourally, over fixture repos, by `tests/test_default_branch_resolution.py`.

    **Public, and named without the underscore for that reason** (`Q-380`,
    Phase 255): `scope_overlap.py` imports it rather than growing a third copy.
    The tree holds exactly two behaviourally-pinned Python/bash resolvers on
    purpose; an out-of-module caller reaching for a private `_`-prefixed symbol
    is the shape that invites the third. Importers must guard the import — this
    module's PyYAML resolution `sys.exit(2)`s at module load, so a plain
    `import sitrep_survey` would make a missing dependency fatal for the caller.

    1. `refs/remotes/<remote>/HEAD` — `origin`, or the repository's only
       remote when there is exactly one and it is not called `origin` — when
       the branch it names also exists locally. When it names a branch that
       exists on the remote (`refs/remotes/<remote>/<name>`) but not locally,
       the answer is "" — the remote has declared a default the checkout has
       not created, and every caller needs the local branch, so the caller
       says how to create it. When the remote-tracking ref is absent too, the
       declaration is stale (the branch was deleted) and step 2 decides.
    2. Exactly one of `main` / `master` exists locally.
    3. An unborn repository (no commit, so no branch ref) has one branch, the
       one `HEAD` symbolically names.
    4. Otherwise "". Nothing here guesses; the caller reports the gap.

    Every name a step would return must match `[A-Za-z0-9._/-]+` and not start with `-`,
    or the answer is "" (`Q-383`) — the same refusal, at the same points, as the bash
    twin: a name git accepts (`main;touch${IFS}x`) reaches unquoted shell substitutions
    downstream. A refused name is appended to `refused` when the caller passes a list,
    so the survey can say *why* there is no answer instead of reporting the generic gap,
    whose remedy (`git remote set-head`) does not fix it.

    Until Phase 252 the only resolver here was `_resolve_main_ref`, whose body
    tried `origin/main` then `main` and whose docstring promised a third
    fallback ("then HEAD on the main worktree") that did not exist. On a
    `master`-default repo it returned "", every claim read 0 commits ahead,
    and that satisfied the park gate — silently.
    """
    return _default_branch_ladder(main_root, refused)


def _default_branch_ladder(main_root: Path, refused: list[str] | None = None) -> str:
    """`resolve_default_branch`'s body, under a name nothing stubs (see `run_survey`)."""
    def _local(name: str) -> bool:
        return bool(_git(["rev-parse", "--verify", "--quiet", f"refs/heads/{name}"],
                         cwd=str(main_root)))

    def _emit(name: str) -> str:
        if _default_branch_name_ok(name):
            return name
        if refused is not None:
            refused.append(name)
        return ""

    remote = _default_remote(main_root)
    head = _git(["symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD"],
                cwd=str(main_root)) if remote else ""
    if head:
        prefix = f"{remote}/"
        name = head[len(prefix):] if head.startswith(prefix) else head
        if name and _local(name):
            return _emit(name)
        if name and _git(["rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{name}"],
                         cwd=str(main_root)):
            # The bash twin refuses here too, before its "create it" remedy — that
            # remedy is a command naming the branch, so it must not carry this one.
            if not _default_branch_name_ok(name) and refused is not None:
                refused.append(name)
            return ""
    have = [n for n in ("main", "master") if _local(n)]
    if len(have) == 1:
        return _emit(have[0])
    if not have and not _git(["rev-parse", "--verify", "--quiet", "HEAD"],
                             cwd=str(main_root)):
        unborn = _git(["symbolic-ref", "--quiet", "--short", "HEAD"], cwd=str(main_root))
        if unborn:
            return _emit(unborn)
    return ""


def _default_branch_refs(main_root: Path) -> list[str]:
    """Every ref that IS the default branch here: the local branch and its
    remote-tracking ref, whichever exist. `[]` when no default branch resolves.
    `_commits_ahead_of_main` excludes commits reachable from any of them."""
    name = resolve_default_branch(main_root)
    if not name:
        return []
    remote = _default_remote(main_root) or "origin"
    return [
        ref for ref in (name, f"{remote}/{name}")
        if _git(["rev-parse", "--verify", "--quiet", ref], cwd=str(main_root))
    ]


def _default_remote(main_root: Path) -> str:
    """`origin` when it exists; the only remote when there is exactly one;
    else "". Mirrors `_git_lib.sh`."""
    if _git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], cwd=str(main_root)):
        return "origin"  # the symref exists (even dangling) whether or not the remote is configured
    remotes = [r for r in _git(["remote"], cwd=str(main_root)).splitlines() if r.strip()]
    if "origin" in remotes:
        return "origin"
    return remotes[0] if len(remotes) == 1 else ""


def _resolve_main_ref(main_root: Path) -> str:
    """One ref naming the default branch, for callers that want a single name:
    the remote-tracking ref when it exists, else the local branch, else "".

    Kept for its callers and tests; the commit COUNT does not use it alone —
    see `_commits_ahead_of_main`, which excludes both refs. Until Phase 252
    this was `("origin/main", "main")` under a docstring promising a third
    fallback ("then HEAD on the main worktree") the body never had.
    """
    name = resolve_default_branch(main_root)
    if not name:
        return ""
    remote = _default_remote(main_root) or "origin"
    for ref in (f"{remote}/{name}", name):
        if _git(["rev-parse", "--verify", "--quiet", ref], cwd=str(main_root)):
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


def _worktree_dirty(worktree_path: Path, main_root: "Path | None" = None) -> bool:
    """Uncommitted changes in a worktree. With `main_root`, an untracked symlink to a target
    the repository ignores (BeanRider ISSUE-0043) is not one, as `/review-close` Step 1a and
    Step 1-pre read it (Phase 360, round 2, lens D)."""
    raw = _git(["-c", "core.quotePath=true", "status", "--porcelain"], cwd=str(worktree_path))
    lines = raw.splitlines()
    if main_root is not None:
        lines = [ln for ln in lines
                 if not (ln.startswith("?? ") and _ignored_symlink(worktree_path, ln[3:], main_root))]
    return any(ln.strip() for ln in lines)


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
    `<root>/<prefix>-<task id LOWER-CASED>` and honours `WORKTREE_PREFIX`, so the
    first version — `<repo name>-<TASK_ID>` verbatim — could never match on a
    case-sensitive filesystem. Neither `WORKTREE_PREFIX` nor `WORKTREE_ROOT`
    (Phase 262, which overrides the `..` parent) is recorded in the lock as such,
    so a workspace built with either is reachable via arms (i) and (ii) — arm (i)
    because git lists a linked worktree wherever it sits, arm (ii) because the lock
    records the resulting absolute `workspace:` when `--lock` wrote one. That
    is a stated limit of THIS arm, not a gap in the survey: arm (iii) exists for
    a lock whose `workspace:` is blank or damaged, and in that case there is no
    record of the override to reconstruct from. Arms (i) and (ii) are
    location-agnostic and need nothing from either variable.

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


# `/review-close` Step 3b's `fm_re` and `SHA_RE`, which `_pending_doc_drift` must match.
_PENDING_DOC_FM_RE = re.compile(r"^\ufeff?---\n(.*?)\n---", re.DOTALL)
_BRANCH_TIP_RE = re.compile(r"[0-9a-fA-F]{7,64}\Z")


@dataclass
class DocDrift:
    """What `_pending_doc_drift` measured. `commits` is None when staleness is unknown,
    and `why` then says why; otherwise `tip` is the doc's `branch_tip:`."""
    commits: int | None
    tip: str = ""
    why: str = ""


def _pending_doc_drift(doc: Path, branch: str) -> DocDrift:
    """How many commits landed on `branch` after `doc`'s `branch_tip:`.

    `/review-close` Step 3b's `tip_of()` + `staleness()`, decision for decision: every
    frontmatter shape it reports as `PENDING-DOC STALENESS UNKNOWN` is unknown here, so
    the survey never calls a doc stale that the close would collect. The count runs in
    the workspace the doc was found in — `staleness(where=...)` does the same — because
    a `--clone` claim's commits exist only in the clone. One `rev-list`, read-only."""
    try:
        m = _PENDING_DOC_FM_RE.match(doc.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        return DocDrift(None, why=f"the pending-doc could not be read ({type(exc).__name__})")
    fm = None
    if m:
        try:
            fm = yaml.safe_load(m.group(1))
        except Exception:
            fm = None  # not only YAMLError: `2026-09-31` raises ValueError, `!!bool x` KeyError
    if not isinstance(fm, dict) or "branch_tip" not in fm:
        return DocDrift(None, why="the pending-doc has no readable `branch_tip:`")
    tip = fm["branch_tip"]
    if not isinstance(tip, str) or not tip.strip():
        return DocDrift(None, why="`branch_tip:` is not a string (a bare hex value "
                                  "reads as a YAML number)")
    tip = tip.strip()
    if "<" in tip:
        return DocDrift(None, why=f"`branch_tip:` is an unsubstituted placeholder ({tip!r})")
    if not _BRANCH_TIP_RE.match(tip):
        return DocDrift(None, why=f"`branch_tip: {tip!r}` is not an object name")
    parents = doc.parents
    where = parents[3] if len(parents) > 3 else Path(".")  # <ws>/sysop/runtime/pending-docs/
    counted = _git(["rev-list", "--count", f"{tip}..{branch}"], cwd=str(where),
                   hermetic=True)
    try:
        return DocDrift(int(counted.strip()), tip=tip)
    except ValueError:
        return DocDrift(None, tip=tip,
                        why=f"`branch_tip` {tip[:12]} does not resolve in {_printable(where)}")



def _measured_drift(doc: Path, branch: str, main_root: Path | None, lock: Lock | None,
                    worktree: Worktree | None, notes: list[str]) -> DocDrift:
    """`_pending_doc_drift`, only where `/review-close` measures the doc, noting why not.

    The close's Step 0 resolves the branch's workspace, and Step 3b's collect runs there: on
    the docs in that workspace, and on this branch's doc held in the main checkout. With no
    workspace of the branch's own (a `--branch` claim, or a worktree removed with its branch
    kept) the collect never runs, so the close does not refuse the doc, and calling it stale
    would name a refusal that does not happen."""
    here = doc.parents[3] if len(doc.parents) > 3 else None
    if main_root is not None and here is not None and _same_dir(here, main_root):
        own = ([worktree.path] if worktree is not None and not worktree.is_main else []) + (
            [Path(lock.workspace)] if lock is not None and lock.workspace else [])
        if not any(p.is_dir() and not _same_dir(p, main_root) for p in own):
            notes.append("pending-doc staleness not measured: the doc is in the main checkout "
                         "and the branch has no workspace of its own, so /review-close does not "
                         "run its Step 3b collect on it")
            return DocDrift(None, why="not measured by the close")
    drift = _pending_doc_drift(doc, branch)
    if drift.commits is None:
        notes.append(f"pending-doc staleness unknown: {drift.why} — "
                     "/review-close collects it without comparing")
    return drift


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
# `Q-362`: a park with commits ahead of the default branch is its own state,
# not `parked` (0 commits) and not `in progress` (which is what it read as).
# The rule, settled at Phase 251's open: the park marker does not simply
# override the commit count; the claim gets a state saying both things are
# true, with its own arm in both cascade tables. See `_work_after_park` for
# the one refinement — a park that PREDATES the newest commit is a claim that
# resumed and moved, and reporting it as parked would tell the human to
# re-resume live work.
_PARKED_WIP_STATE = "parked, work in progress"
_AWAITING_STATE = "awaiting approval"
# `Q-623` / `Q-546`: a claim whose branch a previous `pr` close already
# squash-merged — its tip is contained in a recorded PR head and it has no
# worktree. `Q-643`: or one a previous `direct` close merged — its tip is an
# ancestor of the default branch. The task is still open only because its
# pending-doc was held (Step 4c 1c, on `user_action` or its own `hold:`); a
# close finishes it. One state for both policies: what the human does next is
# the same, so the routing row and `/roadmap`'s enum need no second entry.
_MERGED_STATE = "merged, close pending"
#: A task whose lock a `/review-close --request-review` hand-off kept (`Q-411`, Phase 365): its
#: close is done up to an open PR, and only `--land` finishes it.
_AWAITING_LAND_STATE = "awaiting --land"
#: The same, when an unattended land parked it (`Q-411`, Phase 366): `PARKED` sits beside the
#: marker, and only a human moves it on, so the route is not `--land`.
_PARKED_LAND_STATE = "land parked"


_HANDOFF_PENDING = ("awaiting", "request-failed", "requesting")


def _handoff_markers(main_root: Path) -> list[tuple[str, dict | None]]:
    """(run id, record or None when unreadable) for every `AWAITING` marker, the file every
    other close stops on."""
    out: list[tuple[str, dict | None]] = []
    for marker in sorted((main_root / "sysop" / "runtime" / "close").glob("*/AWAITING")):
        try:
            rec = json.loads((marker.parent / "handoff.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            rec = None
        out.append((marker.parent.name, rec if isinstance(rec, dict) else None))
    return out


def _land_park(main_root: Path, run_id: str) -> str:
    """The first reason line of a hand-off's `PARKED`, `"(unreadable)"` when it cannot be
    read, or "" when the hand-off is not parked."""
    p = main_root / "sysop" / "runtime" / "close" / run_id / "PARKED"
    if not p.exists():
        return ""
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
        lines = rec.get("lines") if isinstance(rec, dict) else None
        return f"{rec.get('code')}: {lines[0]}" if isinstance(lines, list) and lines else "(unreadable)"
    except (OSError, UnicodeDecodeError, ValueError):
        return "(unreadable)"


def _handoff_route(main_root: Path, run_id: str, parked: bool) -> str:
    """The command that moves a hand-off on: the attended `--land` (the unattended land is not
    enabled, `Q-411`), or `re-request` for any hand-off whose review was not requested, parked
    or not, since a land would only park it."""
    try:
        rec = json.loads((main_root / "sysop" / "runtime" / "close" / run_id / "handoff.json")
                         .read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        rec = {}
    rec = rec if isinstance(rec, dict) else {}
    land = f"/review-close --land {run_id}"
    if rec.get("status") != "awaiting":
        # No review was requested (round 2: an unparked failed request was routed to a land that
        # is certain to park).
        return (f"a human: no review was requested for hand-off {run_id}; run close_run.py "
                f"re-request {run_id} <default branch>")
    if not parked:
        return land
    return (f"a human: read sysop/runtime/close/{run_id}/PARKED, then fix and run close_run.py "
            f"re-request {run_id} <default branch>, or close_run.py unpark {run_id}, or "
            f"/review-close --land {run_id}")


def _awaiting_land(main_root: Path) -> dict[str, str]:
    """Task id -> run id for every lock a sealed, unfinished hand-off kept. A marker this does
    not map is reported by `_find_discrepancies` instead."""
    out: dict[str, str] = {}
    for run_id, rec in _handoff_markers(main_root):
        if rec is None or rec.get("status") not in _HANDOFF_PENDING or not rec.get("sealed"):
            continue
        for tid in rec.get("kept_locks") or []:
            if isinstance(tid, str):
                out.setdefault(tid, run_id)
    return out
# A lock whose file cannot be read or parsed. Its fields are unknown, so no
# field-keyed arm may classify it: an empty `branch` read as `claimed, no
# branch` routed a possibly-live claim to `--release` (Phase 333, round 2).
_LOCK_UNREADABLE_STATE = "lock unreadable"


def _lock_unreadable_action(claim_id: str, lock_path: Path, reason: str) -> str:
    return (
        f"repair {lock_path} ({reason}) and re-run /sitrep — do NOT release "
        f"{claim_id}: its lock fields are unknown and the claim may be live"
    )


def _park_markers(main_root: Path, claim_id: str) -> list[Path]:
    """Park markers for a claim, newest first. Empty when absent or unreadable."""
    d = main_root / "sysop" / "runtime" / "parked"
    if not d.is_dir():
        return []
    try:
        return sorted(d.glob(f"{claim_id}__*.md"), reverse=True)
    except OSError:
        return []


_CLAIM_TASK_RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}")


def _newest_claim_run(main_root: Path, claim_id: str) -> Path | None:
    """The most recent per-run artifact directory for a claim, or None.

    Run ids are `<UTC %Y%m%dT%H%M%SZ>-<8 hex>` (`/claim-task` Step 7-pre), so a
    lexical sort IS chronological. Deliberately not mtime: a clone, a checkout
    or a copy resets mtime, and this directory is gitignored precisely so it is
    the kind of thing that gets rebuilt.

    **Only that shape is a run, and only when it is the NEWEST directory.**
    `/auto-build` writes `claim/<id>/<UTC stamp>/` too, with no hex half (6d since
    Phase 236, and 6a for every task since Phase 344). It is not a `/claim-task`
    run: `--resume` there finds no `planner-integrity.md`, re-plans, and drops the
    blocker the human was asked about. And when an `/auto-build` cycle is newer
    than an old `/claim-task` run (a claim released and later taken by
    `/auto-build`; nothing removes claim directories mid-lifecycle), the old run
    is not the live claim either, so a filter that skipped non-runs and returned
    the next one down named a stale run (Phase 344 round 2).
    """
    d = main_root / "sysop" / "runtime" / "claim" / claim_id
    if not d.is_dir():
        return None
    try:
        runs = sorted((p for p in d.iterdir() if p.is_dir()), reverse=True)
    except OSError:
        return None
    return runs[0] if runs and _CLAIM_TASK_RUN_ID.fullmatch(runs[0].name) else None


def _classification_verdict(run: Path) -> str:
    """The verdict recorded in a run's classification.md, upper-cased.

    **Parse the fenced body; do not scan for a line prefix.** `/claim-task`
    Step 7c emits `json.dumps(report, indent=2)` inside a ```yaml fence, so the
    verdict on disk is `  "verdict": "PROCEED"`. The other writer, `/auto-build`
    Phase 6d, writes an unfenced `Verdict: ALL FIXABLE …` line, but in a cycle
    directory `_newest_claim_run` never returns, and the fallback's first word
    is enough for the comparisons made here (`BLOCKED`, `PROCEED`). The first cut of this function scanned for
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


def _park_evidence_time(main_root: Path | None, claim_id: str) -> datetime | None:
    """When the park evidence `_claim_stall` reports was written, or None.

    The latest of every marker's mtime and name stamp (`_park_stamps`); in the
    marker-less `verdict: BLOCKED` arm, the run's `classification.md` mtime and
    the run id's stamp. Every marker, not the newest-named one: names sort by
    run START, and a re-park of an older run is a newer event with an older
    name. The files are written at the moment the claim parks (`/claim-task`
    Step 7c, `/auto-build` Phase 6d), under the gitignored `sysop/runtime/`,
    which is never cloned — so the mtime is the park time on the machine that
    parked, and the name stamp bounds it from below. Neither writer records the
    park time in the file.

    None when there is no park evidence, or nothing can be dated — the callers
    treat None as "cannot tell", which keeps the park (the conservative reading).
    """
    if main_root is None or not claim_id:
        return None
    candidates: list[datetime] = []
    for m in _park_markers(main_root, claim_id):
        candidates.extend(_park_stamps(m, m.name))
    if not candidates:
        run = _newest_claim_run(main_root, claim_id)
        if run is not None and _classification_verdict(run) == "BLOCKED":
            candidates.extend(_park_stamps(run / "classification.md", run.name))
    return max(candidates) if candidates else None


_STAMP_RE = re.compile(r"(?:^|__)(\d{8}T\d{6})Z")


def _park_stamps(path: Path, name: str) -> list[datetime]:
    """The times a piece of park evidence can be dated by: the file's mtime,
    and the UTC stamp both writers put in the NAME (`<RUN_ID>` = `<stamp>Z-<hex>`
    from `/claim-task` Step 7-pre; `<stamp>Z` from `/auto-build` Phase 6d).

    Both, and the caller takes the max, because each is wrong in one
    direction the other is right in: mtime is refreshed by a copy or a restore
    of `sysop/runtime/`, which reads every park as the latest event (the
    conservative error); the name's stamp is the run's START, which for a
    `planner-integrity VIOLATED in 7a` park precedes the commits it parked on — but
    a run that started AFTER the newest commit cannot have parked before it,
    so a name stamp newer than the commit keeps the park even when a restore
    has put the mtime before it (Phase 252's round, execute lens).
    """
    out: list[datetime] = []
    try:
        out.append(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))
    except OSError:
        pass
    m = _STAMP_RE.search(name)
    if m:
        try:
            out.append(datetime.strptime(m.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc))
        except ValueError:
            pass
    return out


def _work_after_park(
    main_root: Path | None, claim_id: str, commits: list[Commit]
) -> bool:
    """True when the claim produced a commit AFTER it parked — i.e. it resumed.

    A `--resume` never removes a park marker — the close does (`/review-close`
    Step 4c for a roadmap claim, `close_batch.sh` for a batch), and so does
    `batch_work.sh --release` for a batch (`claim-task/SKILL.md` § "What cleans
    it up") — so between a `--resume` and the close a live, moving claim carries
    a marker beside its new commits. Reporting that as `parked, work in progress` would recommend
    re-reading a marker the human already acted on. The discriminator is the
    newest commit's author date against the park evidence's mtime: newer
    commit → resumed. Author date rather than committer date on purpose — a
    resume that only rebases pre-park commits refreshes their committer dates
    and has produced nothing new; the executor's own commits carry fresh author
    dates. False when the park time cannot be read (keep the park).
    """
    if not commits:
        return False
    parked_at = _park_evidence_time(main_root, claim_id)
    if parked_at is None:
        return False
    newest = max(c.author_date for c in commits)
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=timezone.utc)
    return newest > parked_at


def _claim_stall(
    main_root: Path | None, claim_id: str
) -> tuple[str, str, list[str]]:
    """Why a claim is not moving: (state, next_action, notes).

    Reports park / awaiting-approval evidence for ANY claim; the callers decide
    what it means beside the commit count (`Q-362`: 0 commits → `parked` /
    `awaiting approval`; commits and the park is the latest event → `parked,
    work in progress`; commits newer than the park → the ordinary arms, with
    the evidence carried in `notes`). Until Phase 252 both callers gated this
    call on 0 commits, on the false premise that a park is "by construction
    the state where nothing has been produced".

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
            # An /auto-build park has no /claim-task run: its claim/<id>/ cycle
            # directory (Phase 344) is not one, and `_newest_claim_run` skips it.
            # Do not print a --resume line naming a run that does not exist.
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
    landed_pr: str = "",
    held_doc: bool = False,
    merged_ref: str = "",
    awaiting_land: str = "",
    land_parked: str = "",
) -> TaskState:
    state = "unknown"
    marker = ""
    next_action = ""
    notes: list[str] = []
    doc_work_ids = sorted({tid for c in commits for tid in c.doc_work_ids})

    # First, before any arm that reads a lock field: an unreadable lock's
    # fields are unknown, not empty.
    if lock is not None and lock.unreadable:
        return TaskState(
            task_id=task_id,
            agent=(lock.agent if lock is not None else ""),
            state=_LOCK_UNREADABLE_STATE,
            branch=branch,
            worktree=str(worktree.path) if worktree else "",
            commits_ahead=len(commits),
            has_lock=True,
            has_index_entry=bool(index_entry),
            index_status=str((index_entry or {}).get("status", "")),
            dirty=dirty,
            doc_work_ids=doc_work_ids,
            next_action=_lock_unreadable_action(task_id, lock.path, lock.unreadable),
            notes=[f"lock {lock.path} could not be read: {lock.unreadable}"],
        )

    # A lock a waiting `--request-review` hand-off kept (`Q-411`, Phase 365): the close ran to
    # an open PR, so the trailer, the consumed pending doc and the live branch read as
    # "docs pending" while the only next step is `--land`.
    if awaiting_land and land_parked:
        return TaskState(
            task_id=task_id,
            state=_PARKED_LAND_STATE,
            branch=branch,
            has_lock=lock is not None,
            has_index_entry=index_entry is not None,
            index_status=str((index_entry or {}).get("status", "")),
            agent=(lock.agent if lock is not None else ""),
            next_action=(_handoff_route(main_root, awaiting_land, True) if main_root else
                         f"a human: read sysop/runtime/close/{awaiting_land}/PARKED"),
            notes=[f"an unattended land parked it ({land_parked}); every /review-close stops "
                   f"on its AWAITING marker until it lands or is abandoned"],
        )
    if awaiting_land:
        return TaskState(
            task_id=task_id,
            state=_AWAITING_LAND_STATE,
            branch=branch,
            has_lock=lock is not None,
            has_index_entry=index_entry is not None,
            index_status=str((index_entry or {}).get("status", "")),
            agent=(lock.agent if lock is not None else ""),
            next_action=(_handoff_route(main_root, awaiting_land, False) if main_root
                         else f"/review-close --land {awaiting_land}"),
            notes=[f"its close is waiting on a second reader; the lock is kept until "
                   f"--land {awaiting_land} merges the PR"],
        )

    # `Q-623` / `Q-546`: a branch a previous close squash-merged. Before the
    # stall probe, the stale check and the 0-commit arm, because with the
    # recorded heads excluded it has 0 commits ahead: the stale arm would advise
    # removing the lock of a task waiting on its human step. `landed_pr` comes
    # from `_landed_claim`, which requires a held doc and no live tip past the head;
    # `merged_ref` from `_merged_into_default`, its `direct` twin (`Q-643`).
    if (landed_pr or merged_ref) and branch:
        state = _MERGED_STATE
        held = bool((index_entry or {}).get("user_action"))
        holds = _doc_holds(main_root, branch) if main_root is not None else []
        steps = []
        if held:
            steps.append(
                f"do {task_id}'s outstanding user step (its body's `## User ops`), "
                f"then python3 sysop/scripts/clear_user_action.py {task_id}"
            )
        if holds:
            steps.append(
                f"finish what its pending doc's `hold:` names, then "
                f"python3 sysop/scripts/pending_doc_hold.py clear {task_id}"
            )
        next_action = (f"{'; '.join(steps)} and /review-close" if steps
                       else f"/review-close {task_id}")
        if landed_pr:
            notes = [
                f"branch {branch} is contained in recorded PR #{landed_pr}'s head — "
                "a previous close squash-merged it; a close consolidates its "
                "pending-doc and flips the task to done"
            ]
        else:
            # Ancestry cannot tell a branch a close merged from one that never moved past
            # its cut point, so the note states the fact and not a history.
            notes = [
                f"branch {branch} is an ancestor of {merged_ref} and a held pending-doc "
                "names it — a close consolidates the doc and flips the task to done"
            ]
            if main_root is not None and "/" not in merged_ref:
                remote_ref = f"{_default_remote(main_root) or 'origin'}/{merged_ref}"
                if (_git(["rev-parse", "--verify", "--quiet", remote_ref], cwd=str(main_root))
                        and not _is_ancestor(f"refs/heads/{branch}", remote_ref, main_root)):
                    notes.append(f"its tip is on local {merged_ref} but not yet on "
                                 f"{remote_ref} — local {merged_ref} has not been pushed")
        if held:
            notes.append("user_action is set, so the close holds the doc until it is cleared")
        for reason in holds:
            notes.append(f"its pending doc carries `hold: {reason}`, so the close holds "
                         "the doc until that is cleared")
        if pending_doc is None:
            notes.append(
                "no pending-doc found for the branch — the close has nothing to "
                "consolidate for it; look in sysop/runtime/pending-docs/"
            )
        return TaskState(
            task_id=task_id,
            agent=(lock.agent if lock is not None else ""),
            state=state,
            branch=branch,
            commits_ahead=0,
            has_lock=bool(lock),
            has_index_entry=bool(index_entry),
            index_status=str((index_entry or {}).get("status", "")),
            doc_work_ids=doc_work_ids,
            pending_doc=pending_doc is not None,
            next_action=next_action,
            notes=notes,
        )

    # **The stall probe runs BEFORE the stale check, and the order is the whole
    # point.** A park is by construction long-lived — it is waiting on an absent
    # human — so past `--stale-days` (default 7) the stale arm would classify it
    # `stale` and advise "confirm dead and rm the lock if abandoned": destructive
    # advice about a live claim, and the exact opposite of what the park needs.
    # This phase's round found it, and found that every integration test built
    # `Lock(started="")`, which short-circuits the stale check and hid it.
    #
    # `Q-362`: the probe is no longer gated on `not commits`. Two shipped park
    # sites can leave commits (`planner-integrity.md` = `VIOLATED` is recorded
    # when HEAD moved or left the task branch during 7a, usually a planner
    # commit; an executor `STATUS: BLOCKED` parks after the executor ran), and
    # gating the probe on their absence classified both as `in progress`. The
    # gate lives in the arms below now, where the
    # commit count and the park evidence are read TOGETHER — and the batch
    # path (`_classify_review_batches`) applies the same three-way rule, which
    # is what keeps the two paths from disagreeing about what a park means.
    stall_state, stall_action, stall_notes = _claim_stall(main_root, task_id)
    resumed = (
        stall_state == _PARKED_STATE
        and bool(commits)
        and _work_after_park(main_root, task_id, commits)
    )

    # Stale check (applies to any state with a lock + worktree)
    if lock and lock.started and not stall_state:
        try:
            started = datetime.fromisoformat(lock.started.replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - started
            # A held doc (`/review-close` Step 4c 1c) keeps a merged branch alive on
            # purpose; with the recorded heads excluded it reads 0 commits ahead, so
            # the remove-the-lock advice below would be destructive (Phase 352 round 2).
            if age > timedelta(days=stale_days) and not commits and held_doc:
                notes.append("lock age is past --stale-days, but a pending doc naming this "
                             "branch is held in sysop/runtime/pending-docs/ — not stale")
            elif age > timedelta(days=stale_days) and not commits:
                state = "stale"
                marker = ""
                next_action = (
                    f"investigate {task_id}; confirm dead and "
                    f"rm {lock.path} if abandoned"
                )
                notes.append(f"lock age {age.days}d; no commits ahead of the default branch")
                return TaskState(
                    task_id=task_id,
                    agent=(lock.agent if lock is not None else ""),
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

    # Branchless claim. `Q-363`: the park evidence rides along in `notes` —
    # this arm precedes the park arms on purpose (a branchless claim is the
    # more actionable diagnosis, and `--resume` cannot work without the branch),
    # and dropping the evidence here is how a parked claim with a deleted
    # branch used to vanish from both routing surfaces.
    if lock and not branch:
        state = "claimed, no branch"
        next_action = (
            f"branch not yet created for {task_id}; verify claim_task.sh "
            f"completed or recreate it — or release the claim: "
            f"bash sysop/scripts/claim_task.sh --release {task_id}"
        )
        notes.extend(stall_notes)
        return TaskState(
            task_id=task_id,
            agent=(lock.agent if lock is not None else ""),
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

    # The evidence a park or an unanswered gate leaves beside COMMITS is never
    # dropped, whichever arm below wins: `Q-362`'s filed reproduction was a
    # marker plus a lock plus one commit reporting `in progress` with nothing
    # in the report saying a marker existed.
    if commits and resumed:
        notes.append(
            "park marker on disk predates the newest commit — the claim "
            "resumed after it parked; the marker is removed at close"
        )
    elif commits and stall_state == _AWAITING_STATE:
        notes.append(
            "classification.md reads verdict: PROCEED with no outcome.md, and "
            "commits exist — the executor has run, so Step 7d's gate was "
            "answered; classified by its commits"
        )

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
    elif stall_state == _PARKED_STATE and not resumed:
        # `Q-362`: commits exist and the park is the latest event on the claim.
        # Outranks every commit-shape arm below, including `ready for
        # /review-close`: a park is a human decision pending, and the trailer
        # state of the commits it parked on does not answer it.
        state = _PARKED_WIP_STATE
        next_action = stall_action
        notes.extend(stall_notes)
        notes.append(
            f"{commits_ahead} commit(s) ahead of the default branch were "
            "produced before the park — the park is the latest event on this "
            "claim"
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
        # Doc-Work trailer and a pending-doc. A doc that predates commits on
        # the branch is refused by /review-close Step 3b as stale (exit 6), and
        # /document-work re-stamps its `branch_tip:`. Staleness unknown keeps the
        # close routing, as the close itself does.
        drift = _measured_drift(pending_doc, branch, main_root, lock, worktree, notes)
        if drift.commits:
            state = "pending doc stale"
            next_action = f"/document-work {task_id}"
            notes.append(
                f"{drift.commits} commit(s) landed on {branch} after the pending-doc's "
                f"branch_tip {drift.tip[:12]} — /review-close would refuse the doc as stale"
            )
        elif unpushed == 0:
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
        agent=(lock.agent if lock is not None else ""),
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
    unreadable: list | None = None,
) -> list[Discrepancy]:
    out: list[Discrepancy] = []

    # A hand-off no task state carries (`Q-411`): every close stops on its marker regardless.
    for run_id, rec in _handoff_markers(main_root):
        if rec is None:
            why = "its handoff.json cannot be read"
        elif rec.get("status") not in _HANDOFF_PENDING:
            why = f"its record reads {rec.get('status')!r}"
        elif not rec.get("sealed"):
            why = "it was never sealed (no report.md)"
        elif not rec.get("kept_locks"):
            why = "it kept no task lock"
        else:
            continue
        out.append(Discrepancy(
            kind="hand-off waiting",
            detail=f"sysop/runtime/close/{run_id}/AWAITING stops every /review-close, and {why}",
            suggestion=f"/review-close --land {run_id}, or close_run.py abandon {run_id} once its PR is closed"))

    lock_ids = {l.task_id for l in locks}
    wt_branches = {w.branch for w in worktrees if not w.is_main}
    # An unreadable lock's `branch` is unknown, so a worktree or branch that
    # matches "no lock" may be that claim's. Say so before any removal advice.
    # So can an unreadable index or tracker: "no index entry" is then unknown,
    # not false. `unreadable` holds the gating inputs the readers could not read.
    unread_paths = list(dict.fromkeys(
        [str(l.path) for l in locks if l.unreadable]
        + [entry[0] for entry in (unreadable or [])]
    ))
    caveat = (
        f"first repair the unreadable input(s) {', '.join(unread_paths)} and "
        "re-run — while they are unread, whether this is live work is unknown; "
        "only then: "
        if unread_paths else ""
    )

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
                        f"{caveat}recreate lock via claim_task.sh --lock {derived} "
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
                        f"{caveat}investigate uncommitted and ignored work "
                        f"(git -C {w.path} status --ignored; the remove deletes "
                        f"ignored files without asking), then git worktree remove {w.path}"
                    ),
                )
            )

    # Orphan branch: task-shaped branch on disk with no lock, no index entry,
    # no worktree
    all_branches = _git(
        ["branch", "--list", "--format=%(refname:short)"], cwd=str(main_root)
    ).splitlines()
    prefixes = _index_prefixes(index)
    for b in all_branches:
        if not _is_task_shaped_branch(b, prefixes):
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
                    f"{caveat}investigate; if dead, git branch -D {b}"
                ),
            )
        )

    # Index drift: tasks[].status == in_progress but no lock
    held_by_handoff = _awaiting_land(main_root)
    for tid, t in index.items():
        if t.get("status") != "in_progress":
            continue
        if tid in lock_ids or tid in held_by_handoff:  # a hand-off's task is routed above
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

    # Phase 361: `/auto-build --unattended` writes this marker when a Step 5
    # abort left a claim it could not verify, and every later unattended run
    # stops while it exists. Nothing else reads it, so without this line a
    # scheduled loop would stop with no machine-readable signal.
    halt = main_root / "sysop" / "runtime" / "auto-build-halt.md"
    if halt.exists():
        out.append(
            Discrepancy(
                kind="unattended auto-build halted",
                detail=(
                    "sysop/runtime/auto-build-halt.md: an unattended "
                    "/auto-build left a claim it could not verify, and every "
                    "later unattended run stops until the file is gone"
                ),
                suggestion=(
                    "read it, reconcile the tasks it names (finish the claim, "
                    "or claim_task.sh --release <TASK_ID>), then delete it"
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
    # An unreadable receipt conditions only this check, so it is a plain
    # discrepancy, not a gating input (`unreadable` is not fed). It is machine
    # written, so its content is unknowable: the remedy is delete or restore.
    bad: list[Discrepancy] = []

    def _receipt_unreadable(f: Path, exc: BaseException) -> None:
        bad.append(Discrepancy(
            kind="round receipt unreadable",
            detail=(f"{_printable(f)} could not be read "
                    f"({_input_reason(exc)}) — its round's coverage is not checked, "
                    "and an older receipt for the same skill may be judged in its place"),
            suggestion="delete it, or restore it from the round that wrote it",
        ))
    for f in d.glob("*.json"):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
            mtime = f.stat().st_mtime
        except (OSError, ValueError) as exc:
            _receipt_unreadable(f, exc)
            continue
        if not isinstance(r, dict):
            _receipt_unreadable(f, ValueError(f"not a JSON object ({type(r).__name__})"))
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

        # The writer records `fanout: "unreported"` only when workers ran and
        # the round header carried no `Fan-out coverage` line for that skill.
        # Keyed to that exact value, so a receipt written before the field
        # existed (no key) stays silent. Outside the Full gate for the same
        # reason as the solo check: a bare `Sampled` must not switch it off.
        if workers > 0 and r.get("fanout") == "unreported":
            out.append(
                Discrepancy(
                    kind="fan-out round with no per-worker coverage",
                    detail=(
                        f"{skill}: last round dispatched {workers} worker(s) "
                        "but recorded no `Fan-out coverage` line — which "
                        "workers opened how much of their scope is unknown"
                    ),
                    suggestion=(
                        "a written receipt is never rewritten, so this clears when "
                        "the next round closes; give that round's header its "
                        "`Fan-out coverage` line (Step 5b) before Step 5f runs"
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
    return bad + out


def _is_review_batch_lock(task_id: str, index: dict[str, Any]) -> bool:
    """A lock the review-batch path owns, not a roadmap claim.

    `batch_work.sh` writes `BATCH-<N>` only, and a `TASK-` lock is review-shaped only
    when the index does not list it: prefixes are project-chosen, so an index task may
    be `TASK-7`, and its claim must stay in ACTIVE WORK.
    """
    return bool(re.fullmatch(r"BATCH-\d+", task_id)) or (
        task_id.startswith("TASK-") and task_id not in index
    )


def _index_prefixes(index: dict[str, Any]) -> set[str]:
    """The lowercased leading segment of every id in the index: the directories
    Step 3 can have generated (`/document-work` Step 3b discovers prefixes the same way)."""
    return {m.group(0).lower() for tid in index
            if (m := re.match(r"[A-Z][A-Z0-9]*", str(tid)))}


def _is_task_shaped_branch(branch: str, prefixes: frozenset[str] | set[str] = frozenset()) -> bool:
    """A fixed task/review directory, or Step 3's derived `<segment>/<segment>[-…]` shape
    for a segment the project's index actually uses. A human `docs/docs-refresh` or
    `wip/wip` has the derived shape, and must not be reported as an orphan task branch."""
    m = DERIVED_BRANCH_RE.match(branch)
    return (
        branch.startswith(TASK_BRANCH_PREFIXES)
        or branch.startswith(REVIEW_BRANCH_PREFIXES)
        or bool(m and m.group(1) in prefixes)
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
    unreadable_by_claim = {l.task_id: l for l in locks if l.unreadable}
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
        notes: list[str] = []

        # `Q-317` / `Q-362`. The probe runs for any LOCKED batch, and the
        # three-way rule below — 0 commits → `parked` / `awaiting approval`;
        # commits with the park as the latest event → `parked, work in
        # progress`; commits newer than the park → the progress arms, evidence
        # in `notes` — is the SAME rule `_classify_task` applies on the roadmap
        # path, so the two cannot drift into different answers about what a
        # park is. Until Phase 252 the probe was gated on `not commits` on
        # both paths, on the false premise that a park is "by construction the
        # state where nothing has been produced"; `claim-task/SKILL.md` parks
        # on `planner-integrity.md` = `VIOLATED`, recorded when HEAD moved or left
        # the task branch (usually a planner commit), and on an executor
        # `STATUS: BLOCKED` after the executor ran. Phase 248's round reproduced
        # the result: marker +
        # lock + one commit read `in progress — continue work; 0 of N tasks
        # have Doc-Work trailers yet`, verbatim the string `Q-317` was filed
        # about, and Phase 248 declined to widen one path alone.
        claim_id = f"BATCH-{b['number']}"
        unreadable_lock = unreadable_by_claim.get(claim_id)
        if unreadable_lock is not None:
            has_lock = True
        stall_state, stall_action, stall_notes = _claim_stall(
            main_root, claim_id
        ) if has_lock else ("", "", [])
        resumed = (
            stall_state == _PARKED_STATE
            and bool(commits)
            and _work_after_park(main_root, claim_id, commits)
        )
        if commits and resumed:
            notes.append(
                "park marker on disk predates the newest commit — the batch "
                "resumed after it parked; the marker is removed at close"
            )
        elif commits and stall_state == _AWAITING_STATE:
            notes.append(
                "classification.md reads verdict: PROCEED with no outcome.md, "
                "and commits exist — the executor has run, so Step 7d's gate "
                "was answered; classified by its commits"
            )

        if unreadable_lock is not None:
            # Before every arm: without it, a `BATCH-<N>.lock` that cannot be
            # read matched no branch, read as unclaimed, and was offered to a
            # drainer (or as `claimed, no branch`, to `--release`).
            state = _LOCK_UNREADABLE_STATE
            next_action = _lock_unreadable_action(
                claim_id, unreadable_lock.path, unreadable_lock.unreadable)
            notes.append(f"lock {unreadable_lock.path} could not be read: "
                         f"{unreadable_lock.unreadable}")
        elif b["status"] == "Pending" and not has_lock:
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
            # `Q-363`: this arm precedes the park arms on purpose — a branchless
            # claim is the more actionable diagnosis, and `--resume` cannot
            # work without the branch — but the park evidence rides along in
            # `notes` rather than being dropped, and the state has its own arm
            # in both cascade tables. A parked batch whose branch was deleted
            # used to classify here and then vanish from `RECOMMENDED NEXT`
            # and the ordered list alike.
            state = "claimed, no branch"
            next_action = (
                f"branch {branch} not created; recheck batch_work.sh result "
                f"or release the claim: bash sysop/scripts/batch_work.sh "
                f"--release {b['number']}"
            )
            if stall_notes:
                # `batch_work.sh --release` reaps the batch's park markers
                # (Phase 248), so the release this line prescribes destroys
                # the record the note beside it surfaces. Say so, in order.
                next_action = (
                    "read the park marker named in the notes first — "
                    "--release removes it; then " + next_action
                )
            notes.extend(stall_notes)
        elif total == 0:
            state = "empty batch"
            next_action = "verify review_tasks.md batch contents"
        elif stall_state == _PARKED_STATE and commits and not resumed:
            # `Q-362`: commits exist and the park is the latest event on the
            # batch. Outranks `ready for /review-close` below for the same
            # reason as on the task path: a park is a human decision pending.
            state = _PARKED_WIP_STATE
            next_action = stall_action
            notes.extend(stall_notes)
            notes.append(
                f"{len(commits)} commit(s) ahead of the default branch were "
                "produced before the park — the park is the latest event on "
                "this batch"
            )
        elif stall_state and not commits:
            # ── Q-317: the park predicate reaches the BATCH path ──────────
            #
            # `_claim_stall` was always claim-kind agnostic as a function — it
            # treats `BATCH-<N>` as an ordinary claim id, and the runtime paths
            # agree (`sysop/runtime/parked/<CLAIM_ID>__<RUN_ID>.md`,
            # `sysop/runtime/claim/<CLAIM_ID>/`, with `<CLAIM_ID>` = `BATCH-<N>`
            # for a batch). What it had was exactly ONE call site,
            # `_classify_task`, which `run_survey`'s lock loop never reaches for
            # a batch: it `continue`d on the `BATCH-`/`TASK-` prefix first (now
            # `_is_review_batch_lock`: `BATCH-<N>` and unindexed `TASK-` ids). So a
            # `/claim-task` Step-7c park of a review batch classified as
            # `in progress — continue work; 0 of N tasks have Doc-Work trailers
            # yet`, indistinguishable from a claim that had not started.
            #
            # Placed AFTER the `empty batch` arm and before the progress arms,
            # which is collision-free rather than merely tidy: this arm is
            # gated on `not commits`, and `done` counts Doc-Work trailers borne
            # by commits, so `not commits` implies `done == 0` and the
            # `done == total` arm below is reachable only when `total == 0`,
            # which the arm above has already taken.
            state = stall_state
            next_action = stall_action
            notes.extend(stall_notes)
        elif done == total and (drift := _batch_doc_drift(
                branch, lock_by_branch.get(branch), worktrees, main_root, notes)):
            # The task path's `pending doc stale`, for a batch branch whose doc predates
            # later commits (Step 3b refuses it). Only a batch whose tasks all carry trailers
            # gets here: `/document-work` emits them, `/auto-fix` and `/auto-judge` do not.
            state = "pending doc stale"
            next_action = (f"/document-work on {branch} (re-stamps the pending-doc's "
                           f"branch_tip), then /review-close (batch {b['number']})")
            notes.append(
                f"{drift.commits} commit(s) landed on {branch} after the pending-doc's "
                f"branch_tip {drift.tip[:12]} — /review-close would refuse the doc as stale"
            )
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
                notes=notes,
            )
        )
    return out


def _batch_doc_drift(branch: str, lock: Lock | None, worktrees: list[Worktree],
                     main_root: Path, notes: list[str]) -> DocDrift | None:
    """The batch branch's pending-doc drift when it is STALE, else None — noting in
    `notes` when staleness is unknown, as the task path does."""
    worktree = next((w for w in worktrees if w.branch == branch and not w.is_main), None)
    doc = _pending_doc_for(main_root, branch, lock, worktree)
    if doc is None:
        return None
    drift = _measured_drift(doc, branch, main_root, lock, worktree, notes)
    return drift if drift.commits else None


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
    # (path, reason, consequence, remedy) for every input a reader could not
    # read. Non-empty → RECOMMENDED NEXT routes to the repair first and the
    # idle arm cannot fire: a survey over an unread input is not a survey.
    unreadable_inputs: list[tuple[str, str, str, str]] = field(default_factory=list)
    # `Q-118`: (batch number, task) for every task close_batch.sh left open in a
    # `Merged` batch because it carries `> Failed:`. Reported, never routed:
    # /next-task and the cascade read Pending batches only, so this is the one
    # place such a task is named before an archive run moves it.
    failed_in_merged_batches: list[tuple[int, str]] = field(default_factory=list)


def run_survey(stale_days: int = DEFAULT_STALE_DAYS) -> Survey:
    main_root = _resolve_main_repo_root()
    head_short = _git(["rev-parse", "--short", "HEAD"], cwd=str(main_root))
    default_branch = resolve_default_branch(main_root)
    # Why there is no answer, asked only when there is none. Through the ladder
    # itself, not the public name: tests replace `resolve_default_branch` with a
    # one-argument stub, and the stub's "" must still reach the generic report.
    refused_default: list[str] = []
    if not default_branch:
        _default_branch_ladder(main_root, refused_default)

    unreadable: list = []
    locks = _read_locks(main_root, unreadable)
    worktrees = _read_worktrees(main_root)
    index = _read_index(main_root, unreadable)
    review_batches_raw = _read_review_batches(main_root, unreadable)

    phase40_cutoff = datetime.fromisoformat(
        PHASE_40_CUTOFF_ISO.replace("Z", "+00:00")
    )

    # Build the set of (task_id, branch, worktree, lock, index_entry) tuples
    # to classify.
    classified: list[TaskState] = []

    # Index entries with in_progress status drive the primary classification
    # set.
    seen_task_ids: set[str] = set()
    open_batch_claims = {
        f"BATCH-{b['number']}" for b in review_batches_raw
        if b.get("status") in ("Pending", "In Progress")
    }
    awaiting_land = _awaiting_land(main_root)

    for lock in locks:
        task_id = lock.task_id
        if not task_id:
            continue
        # The review-batch path handles review-batch locks — except an
        # unreadable one no open batch will pick up (its batch path keys on
        # `BATCH-<N>`), which would otherwise vanish from ACTIVE WORK.
        if _is_review_batch_lock(task_id, index):
            if not (lock.unreadable and task_id not in open_batch_claims):
                continue
        seen_task_ids.add(task_id)
        index_entry = index.get(task_id)
        branch = lock.branch or (index_entry or {}).get("branch", "")
        if task_id in awaiting_land:
            classified.append(_classify_task(
                task_id=task_id, lock=lock, worktree=None, branch=branch,
                index_entry=index_entry, commits=[], unpushed=0, dirty=False,
                stale_days=stale_days, phase40_cutoff=phase40_cutoff,
                main_root=main_root, awaiting_land=awaiting_land[task_id],
                land_parked=_land_park(main_root, awaiting_land[task_id])))
            continue
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
            _worktree_dirty(worktree.path, main_root)
            if worktree and worktree.path.is_dir()
            else False
        )
        landed_pr = _landed_claim(main_root, branch, lock, worktree, dirty)
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
                landed_pr=landed_pr,
                held_doc=bool(branch and _held_doc_names(main_root, branch)),
                merged_ref="" if landed_pr else _merged_into_default(
                    main_root, branch, lock, worktree, dirty),
            )
        )

    # A hand-off's task whose kept lock is gone (Phase 366 round 1): the hand-off still holds
    # `AWAITING`, which stops every close, so the task must stay visible and routed.
    for task_id, run_id in sorted(awaiting_land.items()):
        if task_id in seen_task_ids:
            continue
        index_entry = index.get(task_id)
        t = _classify_task(
            task_id=task_id, lock=None, worktree=None,
            branch=str((index_entry or {}).get("branch", "")), index_entry=index_entry,
            commits=[], unpushed=0, dirty=False, stale_days=stale_days,
            phase40_cutoff=phase40_cutoff, main_root=main_root, awaiting_land=run_id,
            land_parked=_land_park(main_root, run_id))
        t.notes.append("its lock, which the hand-off kept, is gone from sysop/runtime/locks/")
        classified.append(t)

    # Index entries with in_progress status but no lock — surface as drift via
    # discrepancies; do NOT add to classified (the discrepancy carries the
    # signal).

    review_states = _classify_review_batches(
        review_batches_raw, locks, worktrees, main_root
    )

    discrepancies = _find_discrepancies(
        locks, worktrees, index, main_root, unreadable
    )
    if not default_branch and refused_default:
        # `Q-383`: a name exists but is refused. The generic line below would be
        # false here ("no remote HEAD … identifies"), and its remedy does not fix
        # it. The name is shown through `_quote_refused_name`, never raw.
        discrepancies.insert(0, Discrepancy(
            kind="default branch unresolved",
            detail=(
                f"the default branch name {_quote_refused_name(refused_default[0])} is refused: a "
                "default-branch name must match [A-Za-z0-9._/-]+ and not start with "
                "'-', because it is substituted unquoted into git commands — so "
                "every claim above reads 0 commits ahead and its state cannot be "
                "trusted"
            ),
            suggestion=(
                "if the repository is yours, rename the branch (git branch -m "
                "<current> <new>) and, if a remote names it, publish it, make it "
                "the host's default, then re-declare it (git push -u origin <new> "
                "&& git remote set-head origin <new>); if its refs "
                "come from someone else, the refusal is the protection — do not "
                "work around it (sysop/scripts/_git_lib.sh)"
            ),
        ))
    elif not default_branch:
        # `Q-365`: with no resolvable default branch every claim above read 0
        # commits ahead — which satisfied the park gate and the `planning`
        # arm alike — and nothing said so. Report it FIRST: every state in
        # this survey is conditioned on it.
        discrepancies.insert(0, Discrepancy(
            kind="default branch unresolved",
            detail=(
                "no remote HEAD with a local branch, nor exactly one of "
                "main/master, identifies this repository's default branch, so "
                "every claim above reads 0 commits ahead and its state cannot "
                "be trusted"
            ),
            suggestion=(
                "declare it: git remote set-head origin <branch> — or, when "
                "origin/HEAD already names a branch this checkout lacks, create "
                "it: git branch <branch> origin/<branch>  (the resolution order "
                "is documented in sysop/scripts/_git_lib.sh)"
            ),
        ))

    # An input a reader could not read is reported next to the default-branch
    # line: like it, it conditions every state above rather than being one.
    at = 1 if not default_branch else 0
    discrepancies[at:at] = [
        Discrepancy(
            kind="input unreadable",
            detail=f"{path} could not be read ({reason}) — {consequence}",
            suggestion=f"{remedy}, then re-run /sitrep",
        )
        for path, reason, consequence, remedy in unreadable
    ]

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
        unreadable_inputs=list(unreadable),
        failed_in_merged_batches=[
            (b["number"], task)
            for b in review_batches_raw
            for task in b.get("failed_open", [])
        ] + _read_near_miss_failed(main_root),
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
            # `Q-317` follow-up (Phase 248's round, guards lens): the task block
            # prints its notes and this one did not, so a batch's park evidence
            # reached `--json` and the cascade and never the report a human
            # reads. The lost line is the whole message in the marker-less arm —
            # "classification.md reads verdict: BLOCKED but no park marker is on
            # disk" — and `_recommended_next`'s own reason string points at it
            # ("see the detail line for what the evidence is"), which existed
            # only when the batch happened to win the cascade. Four surfaces were
            # counted and `render_text` was the fifth.
            for note in rb.notes:
                lines.append(f"               · {note}")
        lines.append("")

    # `Q-118`. Printed only when non-empty; never routed (see the field).
    if s.failed_in_merged_batches:
        lines.append(
            f"FAILED IN MERGED BATCHES ({len(s.failed_in_merged_batches)})"
        )
        for number, task in s.failed_in_merged_batches:
            lines.append(f"  Batch {number:<6} {task}")
        lines.append(
            "               ↳ no other reader routes these back: finish, re-file or "
            "/add-task each before an archive run moves it out of review_tasks.md"
        )
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
    # The check is for THIS task's trailer, as the lifecycle classification reads it; a
    # trailer naming some other token on the branch is not this task's documentation.
    if ts.task_id in ts.doc_work_ids:
        bits.append("Doc-Work ✓")
    return ", ".join(bits)


# /auto-build caps a batch at N=4 tasks (WORKFLOW.md § 2.4b). A roadmap deeper
# than one batch is where a strategy view (/roadmap) beats jumping straight to
# batch execution; at or below one batch, /auto-build grabs it in a single go.
_AUTO_BUILD_MAX_BATCH = 4


def _recommended_next(s: Survey) -> Recommendation | None:
    """Single top routing recommendation. See SKILL.md § Recommendation routing rules.

    Priority order: unreadable input → lock unreadable (task, batch) →
    review-close (task) → review-close (batch) → unpushed doc-work →
    /triage if any pending batch lacks a Triaged: record → /auto-fix and/or /auto-judge →
    code committed, docs pending → pending doc stale (task, then batch) →
    continue in-progress (task, then batch) →
    parked with work in progress → parked → awaiting approval (task, then the
    three batch twins) → claimed, no branch (task, batch) → empty batch →
    resume planning → stale → /roadmap (deep queue) or /auto-build (shallow) → idle.

    **Every state either classifier emits has an arm here AND in
    `_suggested_order`** — `tests/test_sitrep_park_wip.py` derives the state
    set from the classifiers and drives one of each through both tables, with
    no allowlist. `Q-363`'s defect was a state (`claimed, no branch`) with no
    arm in either: the batch dropped off `RECOMMENDED NEXT` and the ordered
    list together, and `Q-019`'s round had already recorded the same shape
    for `code committed, docs pending`. Three more states were orphaned the
    same way when `Q-363` was taken (`stale`, `empty batch`, batch
    `in progress`), so the guard covers the class rather than the filing.
    """
    # P0a: an input the survey could not read. Every state below is read
    # through it (an unreadable index reads as empty, so the idle arm would
    # fire over live work), so the repair comes first.
    if s.unreadable_inputs:
        path, reason, consequence, remedy = s.unreadable_inputs[0]
        more = (f" ({len(s.unreadable_inputs) - 1} more under DISCREPANCIES)"
                if len(s.unreadable_inputs) > 1 else "")
        return Recommendation(
            command=f"repair {path}: {remedy}; then re-run /sitrep",
            reason=f"{path} could not be read ({reason}) — {consequence}{more}",
        )
    # P0b/P0c: a claim whose lock is unreadable. Reached on its own only when
    # the survey is built without the input list; its move is the repair,
    # never a release.
    lock_unreadable = [t for t in s.tasks if t.state == _LOCK_UNREADABLE_STATE]
    if lock_unreadable:
        t = lock_unreadable[0]
        return Recommendation(
            command=t.next_action,
            reason=f"{t.task_id}'s lock cannot be read, so its claim state is unknown",
            detail_lines=list(t.notes),
        )
    lock_unreadable_batches = [
        rb for rb in s.review_batches if rb.state == _LOCK_UNREADABLE_STATE
    ]
    if lock_unreadable_batches:
        rb = lock_unreadable_batches[0]
        return Recommendation(
            command=rb.next_action,
            reason=(f"Batch {rb.batch_number}'s lock cannot be read, so its claim "
                    "state is unknown"),
            detail_lines=list(rb.notes),
        )

    # P0d (`Q-411`, Phase 365): a close handed off to a second reader, waiting on `--land`. Ahead
    # of every close row: any other /review-close stops on the hand-off's `AWAITING` marker.
    awaiting = [t for t in s.tasks if t.state == _AWAITING_LAND_STATE]
    if awaiting:
        t = awaiting[0]
        more = f" ({len(awaiting) - 1} more task(s))" if len(awaiting) > 1 else ""
        return Recommendation(
            command=t.next_action,
            reason=f"{t.task_id}'s close is waiting on its second reader's review{more}",
            detail_lines=list(t.notes),
        )
    # P0e (`Q-411`, Phase 366): the same hand-off, parked by an unattended land: a human moves it.
    parked_land = [t for t in s.tasks if t.state == _PARKED_LAND_STATE]
    if parked_land:
        t = parked_land[0]
        more = f" ({len(parked_land) - 1} more task(s))" if len(parked_land) > 1 else ""
        return Recommendation(
            command=t.next_action,
            reason=f"{t.task_id}'s unattended land parked and needs a human{more}",
            detail_lines=list(t.notes),
        )

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

    # P2: review batches `ready for /review-close` (Doc-Work'd, doc not stale) — or header status
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

    # P3b (`Q-623` / `Q-546`): a branch a previous close merged —
    # squash-merged under `pr`, merged onto the default branch under `direct` —
    # whose task waits on a close, or on its human step first.
    merged = [t for t in s.tasks if t.state == _MERGED_STATE]
    if merged:
        t = merged[0]
        more = f" ({len(merged) - 1} more)" if len(merged) > 1 else ""
        return Recommendation(
            command=t.next_action,
            reason=(
                f"{t.task_id}'s branch was merged by a previous close; "
                f"the task is not done until a close consolidates its doc{more}"
            ),
            detail_lines=list(t.notes),
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
                reason=f"{n_flag} flagged batch(es) need reasoning-tier judgment",
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

    # P4f: documented, then committed to again. The same move as P4e, and
    # ranked right after it rather than above it so P4e keeps its label: the two are
    # one human action, and which comes first is arbitrary.
    stale_docs = [t for t in s.tasks if t.state == "pending doc stale"]
    if stale_docs:
        t = stale_docs[0]
        return Recommendation(
            command=f"/document-work {t.task_id}",
            reason=(
                f"{t.task_id}'s pending-doc predates commits on its branch — "
                f"/review-close refuses a stale doc; /document-work re-stamps "
                f"its branch_tip"
            ),
            detail_lines=list(t.notes),
        )
    stale_doc_batches = [rb for rb in s.review_batches if rb.state == "pending doc stale"]
    if stale_doc_batches:
        rb = stale_doc_batches[0]
        return Recommendation(
            command=rb.next_action,
            reason=(
                f"Batch {rb.batch_number}'s pending-doc predates commits on "
                f"{rb.branch} — /review-close refuses a stale doc"
            ),
            detail_lines=list(rb.notes),
        )

    # P5: in-progress tasks (single-task work)
    in_progress = [t for t in s.tasks if t.state == "in progress"]
    if in_progress:
        t = in_progress[0]
        return Recommendation(
            command=f"continue work on {t.task_id} or /document-work {t.task_id}",
            reason=(
                f"{t.task_id} has {t.commits_ahead} commit(s) ahead of the "
                f"default branch but no Doc-Work trailer yet"
            ),
        )

    # P5b: in-progress review batches — the batch twin of P5. Orphaned until
    # Phase 252: the classifier emitted it and neither table had an arm.
    in_progress_batches = [rb for rb in s.review_batches if rb.state == "in progress"]
    if in_progress_batches:
        rb = in_progress_batches[0]
        return Recommendation(
            command=(
                f"continue work on batch {rb.batch_number} "
                f"(branch {rb.branch}) then /document-work"
            ),
            reason=(
                f"Batch {rb.batch_number} is in progress — "
                f"{rb.doc_worked_tasks} of {rb.total_tasks} tasks carry "
                f"Doc-Work trailers"
            ),
        )

    # P6a–P6f: stalled claims — parked with work, parked, or waiting at Step
    # 7d's human gate; the task arms first, then their batch twins.
    #
    # Ranked here, immediately above `planning`, and NOT above P5, because this
    # cascade's consistent logic is "further along ranks higher": P1/P3 have a
    # trailer and a pending-doc, P4e has commits plus a trailer, P5 has commits.
    # A parked or awaiting-approval claim has ZERO commits ahead — it is a
    # specialisation of `planning`, which is exactly why it used to be swallowed
    # by it, so it belongs where `planning` belongs.
    #
    # `parked, work in progress` (`Q-362`) HAS commits, and it still sits here
    # rather than above P5: it heads the stall block because it is the furthest
    # along of the stalls, but a park is a human decision pending, and the
    # cascade names one move — sending the human to answer a parked claim's
    # question while a live build sits half-finished is the trade the P6
    # placement was written to refuse. Its arm is first in the block so a park
    # with work outranks a park with none.
    #
    # Visibility is not what the rank buys. The ACTIVE WORK table renders every
    # task with its own state and notes, so a park is legible there whatever the
    # cascade names; the cascade names one move. Ranking a park above live
    # in-progress work would tell a human to go answer a question while a build
    # sits half-finished, which is not the trade this defect was about.
    parked_wip = [t for t in s.tasks if t.state == _PARKED_WIP_STATE]
    if parked_wip:
        t = parked_wip[0]
        more = f" ({len(parked_wip) - 1} more parked)" if len(parked_wip) > 1 else ""
        return Recommendation(
            command=t.next_action,
            reason=(
                f"{t.task_id} parked after producing {t.commits_ahead} "
                f"commit(s) and is waiting on a human decision{more} — see "
                f"the detail line for what the evidence is"
            ),
            detail_lines=list(t.notes),
        )

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

    # `Q-317`: the same states on the BATCH path. Ranked immediately after
    # their roadmap twins rather than interleaved with them, because a batch
    # park and a task park are the same human action and the cascade names one
    # move — ordering between two parks is arbitrary, and stability is worth
    # more than a coin flip. All are wired into `_suggested_order` too: Q-019's
    # round recorded that a state present in one and absent from the other drops
    # out of the ordered list entirely and the report contradicts itself.
    parked_wip_batches = [rb for rb in s.review_batches if rb.state == _PARKED_WIP_STATE]
    if parked_wip_batches:
        rb = parked_wip_batches[0]
        more = (
            f" ({len(parked_wip_batches) - 1} more parked)"
            if len(parked_wip_batches) > 1 else ""
        )
        return Recommendation(
            command=rb.next_action,
            reason=(
                f"Batch {rb.batch_number} parked after work began and is "
                f"waiting on a human decision{more} — see the detail line for "
                f"what the evidence is"
            ),
            detail_lines=list(rb.notes),
        )

    parked_batches = [rb for rb in s.review_batches if rb.state == _PARKED_STATE]
    if parked_batches:
        rb = parked_batches[0]
        more = (
            f" ({len(parked_batches) - 1} more parked)"
            if len(parked_batches) > 1 else ""
        )
        return Recommendation(
            command=rb.next_action,
            reason=(
                f"Batch {rb.batch_number} is parked and is waiting on a human "
                f"decision{more} — see the detail line for what the evidence is"
            ),
            detail_lines=list(rb.notes),
        )

    awaiting_batches = [rb for rb in s.review_batches if rb.state == _AWAITING_STATE]
    if awaiting_batches:
        rb = awaiting_batches[0]
        more = (
            f" ({len(awaiting_batches) - 1} more waiting)"
            if len(awaiting_batches) > 1 else ""
        )
        return Recommendation(
            command=rb.next_action,
            reason=(
                f"Batch {rb.batch_number}'s plan was reviewed and classified "
                f"clean; it is waiting on your approval at /claim-task "
                f"Step 7d{more}"
            ),
            detail_lines=list(rb.notes),
        )

    # P6g/P6h: a claim holding a lock and no branch (`Q-363`). Below the
    # stall block — a park that CAN be resumed outranks one whose branch must
    # first be recreated or released — and above `planning`, because a
    # branchless claim cannot be planned on. The task-path predicate is "the
    # lock records no branch"; the batch-path predicate is "the recorded branch
    # does not exist" (deleted, or never created). Both land here.
    branchless = [t for t in s.tasks if t.state == "claimed, no branch"]
    if branchless:
        t = branchless[0]
        return Recommendation(
            command=t.next_action,
            reason=(
                f"{t.task_id} holds a lock but no branch — recreate the branch "
                f"or release the claim"
            ),
            detail_lines=list(t.notes),
        )
    branchless_batches = [
        rb for rb in s.review_batches if rb.state == "claimed, no branch"
    ]
    if branchless_batches:
        rb = branchless_batches[0]
        return Recommendation(
            command=rb.next_action,
            reason=(
                f"Batch {rb.batch_number} holds a lock but its branch "
                f"{rb.branch!r} does not exist — recreate it or release the claim"
            ),
            detail_lines=list(rb.notes),
        )

    # P6i: an empty batch — a structural problem in review_tasks.md.
    empty_batches = [rb for rb in s.review_batches if rb.state == "empty batch"]
    if empty_batches:
        rb = empty_batches[0]
        return Recommendation(
            command=rb.next_action,
            reason=f"Batch {rb.batch_number} lists no tasks under its header",
        )

    # P6j: planning tasks
    planning = [t for t in s.tasks if t.state == "planning"]
    if planning:
        t = planning[0]
        return Recommendation(
            command=f"resume planning for {t.task_id}",
            reason=f"{t.task_id} has a branch + lock but 0 commits ahead",
        )

    # P6k: stale claims — a lock older than `--stale-days` with no commits.
    # Last of the claim states: every arm above is a live claim with a named
    # move, and this one's move is to confirm the claim is dead.
    stale = [t for t in s.tasks if t.state == "stale"]
    if stale:
        t = stale[0]
        more = f" ({len(stale) - 1} more)" if len(stale) > 1 else ""
        return Recommendation(
            command=t.next_action,
            reason=(
                f"{t.task_id}'s lock is older than the stale threshold with no "
                f"commits ahead{more} — confirm it is abandoned before removing "
                f"anything"
            ),
            detail_lines=list(t.notes),
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
    then stalled claims (parked with work, parked, awaiting approval), then
    the diagnostics (claimed with no branch, empty batch), then planning and
    stale, then discrepancies.

    Every state either classifier emits appears here — the invariant
    `_recommended_next`'s docstring states, guarded without an allowlist.
    """
    out: list[str] = []
    # 0. Inputs the survey could not read, then the claims whose lock is one
    # of them: the repair precedes everything the survey read through them.
    for path, _reason, _consequence, remedy in s.unreadable_inputs:
        out.append(f"repair {path}: {remedy}; then re-run /sitrep")
    for ts in s.tasks:
        if ts.state == _LOCK_UNREADABLE_STATE:
            out.append(f"{ts.task_id}: {ts.next_action}")
    for rb in s.review_batches:
        if rb.state == _LOCK_UNREADABLE_STATE:
            out.append(f"batch {rb.batch_number}: {rb.next_action}")
    # 0. Waiting on `--land` (`Q-411`), matching `_recommended_next`'s P0d.
    for ts in s.tasks:
        if ts.state == _AWAITING_LAND_STATE:
            out.append(f"{ts.task_id}: close waiting on its second reader — {ts.next_action}")
    for ts in s.tasks:
        if ts.state == _PARKED_LAND_STATE:
            out.append(f"{ts.task_id}: unattended land parked — {ts.next_action}")
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
    # 2a. Merged by a previous close, task still open (`Q-623`). After
    # the close tiers, matching `_recommended_next`'s P3b.
    for ts in s.tasks:
        if ts.state == _MERGED_STATE:
            out.append(f"{ts.task_id}: merged by a previous close — {ts.next_action}")
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
    for ts in s.tasks:
        if ts.state == "pending doc stale":
            out.append(f"/document-work {ts.task_id} (pending-doc is stale — commits "
                       "landed after its branch_tip)")
    for rb in s.review_batches:
        if rb.state == "pending doc stale":
            out.append(f"Batch {rb.batch_number}'s pending-doc is stale — {rb.next_action}")
    # 2c. Pending unclaimed batches — the ordered-list twin of P4a–4d, which
    # routes them by their `Triaged:` record; the classifier's `next_action`
    # already carries that routing as prose.
    for rb in s.review_batches:
        if rb.state == "pending (not claimed)":
            out.append(f"Batch {rb.batch_number} is pending — {rb.next_action}")
    # 3. In-progress (Doc-Work next)
    for ts in s.tasks:
        if ts.state == "in progress":
            out.append(f"/document-work {ts.task_id} (no Doc-Work trailer yet)")
    for rb in s.review_batches:
        if rb.state == "in progress":
            out.append(f"Batch {rb.batch_number} is in progress — {rb.next_action}")
    # 3a. Parked WITH work (`Q-362`) — heads the stall block, task then batch.
    for ts in s.tasks:
        if ts.state == _PARKED_WIP_STATE:
            out.append(
                f"{ts.task_id} is parked with work in progress — {ts.next_action}"
            )
    for rb in s.review_batches:
        if rb.state == _PARKED_WIP_STATE:
            out.append(
                f"Batch {rb.batch_number} is parked with work in progress — "
                f"{rb.next_action}"
            )
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
    # 3c. The same two states on the BATCH path (`Q-317`). Kept in step with
    # `_recommended_next`, which is the invariant this list exists to hold.
    for rb in s.review_batches:
        if rb.state == _PARKED_STATE:
            out.append(
                f"Batch {rb.batch_number} is parked — {rb.next_action}"
            )
    for rb in s.review_batches:
        if rb.state == _AWAITING_STATE:
            out.append(
                f"Batch {rb.batch_number} awaits your approval — {rb.next_action}"
            )
    # 3d. Diagnostics (`Q-363`): a lock with no branch, task then batch; then
    # an empty batch. Below the stalls and above planning, matching P6g–P6i.
    for ts in s.tasks:
        if ts.state == "claimed, no branch":
            out.append(f"{ts.task_id} holds a lock but no branch — {ts.next_action}")
    for rb in s.review_batches:
        if rb.state == "claimed, no branch":
            out.append(
                f"Batch {rb.batch_number} holds a lock but no branch — {rb.next_action}"
            )
    for rb in s.review_batches:
        if rb.state == "empty batch":
            out.append(f"Batch {rb.batch_number} is empty — {rb.next_action}")
    # 4. Planning
    for ts in s.tasks:
        if ts.state == "planning":
            out.append(f"resume {ts.task_id} planning (0 commits ahead)")
    # 4b. Stale — last of the claim states, as in `_recommended_next` P6k.
    for ts in s.tasks:
        if ts.state == "stale":
            out.append(f"{ts.task_id} looks stale — {ts.next_action}")
    # 5. Discrepancies
    if s.discrepancies:
        n = len(s.discrepancies)
        word = "discrepancy" if n == 1 else "discrepancies"
        out.append(f"triage {n} {word}")
    return out


# ── JSON rendering (the contract is in the module docstring) ─────

JSON_SCHEMA_VERSION = 1


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
            "agent": t.agent,
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
                "schema_version": JSON_SCHEMA_VERSION,
                "timestamp": s.timestamp.isoformat(),
                "main_root": str(s.main_root),
                "head_short": s.head_short,
                "stale_days": s.stale_days,
                "tasks": [_ts(t) for t in s.tasks],
                "review_batches": [_rb(r) for r in s.review_batches],
                "discrepancies": [_d(d) for d in s.discrepancies],
                "open_roadmap_ids": s.open_roadmap_ids,
                "failed_in_merged_batches": [
                    {"batch_number": n, "task": task}
                    for n, task in s.failed_in_merged_batches
                ],
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
        help="Emit JSON instead of the text report (a stable contract; see the module docstring)",
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
    text = render_json(survey) if args.json else render_text(survey)
    # A surrogate from `_git`'s decode prints as a visible `\\udcXX` escape
    # rather than failing a strict stdout (`Q-612`).
    sys.stdout.write(re.sub("[\ud800-\udfff]", lambda m: "\\u%04x" % ord(m.group()), text))
    return 0



def _list_locks_dir(locks_dir: Path, unreadable: list | None) -> list[str]:
    """The names in the locks directory. An absent directory holds no claims; one that
    exists and cannot be listed is a gating input the survey could not read. `glob`
    answered `[]` for both, so every live claim's worktree read as an orphan whose
    removal the survey then suggested (Phase 339's round 2)."""
    try:
        return os.listdir(locks_dir)
    except (FileNotFoundError, NotADirectoryError):
        return []
    except OSError as exc:
        _unreadable_input(locks_dir, exc, "no lock could be listed, so every claim is "
                          "unknown and no worktree can be called an orphan", unreadable)
        return []


if __name__ == "__main__":
    raise SystemExit(main())
