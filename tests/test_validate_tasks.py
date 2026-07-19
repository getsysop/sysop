"""Tests for ``core/companion/scripts/validate_tasks.py``.

Two sections:

1. Ports gdp's ``tests/test_validate_tasks.py`` (8 functions, all
   ``_locks_dir``-focused) to Sysop's ``_resolve_canonical_locks_dir``
   (renamed during the Phase 32 absorption of BeanRider ISSUE-0028 et al).
   gdp baseline confirmed passing 2026-05-27 — all 8 tests are green
   candidates.

2. Sysop-original tests covering schema/invariant behavior gdp's
   8-function suite cannot exercise — blast_radius (Phase 19), in-progress
   lock invariant (Phase 32), status-vs-directory drift (Phase 18).
"""

import os
import subprocess
from pathlib import Path
from unittest import mock

import validate_tasks as vt


# === Section 1: gdp-ported _resolve_canonical_locks_dir tests =============


_VALID_INDEX = """\
schema_version: 1

phases:
  - number: 1
    title: "Active phase"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-LOCKED
    title: "Task currently in progress"
    phase: 1
    status: in_progress
    effort: Medium
    user_action: false
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-LOCKED.md
"""

_VALID_BODY = """\
# FEAT-LOCKED

## Context
Locked.
"""


def _make_tasks_tree(root: Path) -> Path:
    """Build a minimal tasks/ tree under *root* with one in_progress task."""
    tasks_dir = root / "tasks"
    open_dir = tasks_dir / "open"
    open_dir.mkdir(parents=True, exist_ok=True)
    (tasks_dir / "index.yml").write_text(_VALID_INDEX, encoding="utf-8")
    (open_dir / "FEAT-LOCKED.md").write_text(_VALID_BODY, encoding="utf-8")
    return tasks_dir


def test_locks_dir_falls_back_when_not_a_git_repo(tmp_path):
    """`tmp_path` has no `.git/`; helper must return `<root>/sysop/runtime/locks`."""
    resolved = vt._resolve_canonical_locks_dir(tmp_path)
    assert resolved == tmp_path / "sysop/runtime/locks"


def test_locks_dir_falls_back_when_git_binary_missing(tmp_path):
    """If `git` is not on PATH, helper must still return the safe default."""
    with mock.patch.object(vt.subprocess, "run", side_effect=FileNotFoundError("git not found")):
        resolved = vt._resolve_canonical_locks_dir(tmp_path)
    assert resolved == tmp_path / "sysop/runtime/locks"


def test_locks_dir_falls_back_on_timeout(tmp_path):
    """A hung git invocation must not block validation indefinitely."""
    with mock.patch.object(
        vt.subprocess,
        "run",
        side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5),
    ):
        resolved = vt._resolve_canonical_locks_dir(tmp_path)
    assert resolved == tmp_path / "sysop/runtime/locks"


def test_locks_dir_falls_back_on_os_error(tmp_path):
    """Any unexpected OSError (permission denied, etc.) must fall back.

    Diverged from gdp in Phase 32: Sysop's helper catches
    `(FileNotFoundError, subprocess.SubprocessError)` rather than a bare
    `OSError`. An OSError that is NOT a SubprocessError will propagate
    instead of falling back. We assert the practical behavior: such an
    error escapes, which lets the validator surface the real problem
    (permission misconfig) instead of masking it with a default path.
    """
    with mock.patch.object(vt.subprocess, "run", side_effect=PermissionError("EACCES")):
        with mock.patch.object(Path, "is_absolute", return_value=True):
            try:
                vt._resolve_canonical_locks_dir(tmp_path)
                raised = False
            except PermissionError:
                raised = True
    assert raised, "PermissionError must propagate so misconfig is visible"


def test_locks_dir_resolves_from_real_git_repo(tmp_path):
    """Initialize a real git repo and confirm helper returns `<repo>/sysop/runtime/locks`."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
    )
    resolved = vt._resolve_canonical_locks_dir(repo_root)
    assert resolved == (repo_root / "sysop/runtime/locks").resolve()


def test_locks_dir_resolves_main_locks_from_worktree(tmp_path):
    """End-to-end: validator invoked from a linked worktree finds main's sysop/runtime/locks/."""
    main_root = tmp_path / "main"
    main_root.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main"],
        cwd=str(main_root),
        check=True,
        capture_output=True,
    )
    (main_root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "README.md"],
        cwd=str(main_root),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "seed"],
        cwd=str(main_root),
        check=True,
        capture_output=True,
    )

    _make_tasks_tree(main_root)
    main_locks = main_root / "sysop/runtime/locks"
    main_locks.mkdir(parents=True, exist_ok=True)
    (main_locks / "FEAT-LOCKED.lock").write_text("lock\n", encoding="utf-8")

    worktree_root = tmp_path / "worktree"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "feat", str(worktree_root)],
        cwd=str(main_root),
        check=True,
        capture_output=True,
    )

    assert not (worktree_root / "sysop/runtime/locks").exists()

    resolved = vt._resolve_canonical_locks_dir(worktree_root)
    assert resolved == main_locks.resolve()

    _make_tasks_tree(worktree_root)
    report = vt.validate(worktree_root / "tasks", project_root=worktree_root)
    assert report.ok, [f.format() for f in report.errors]


def test_locks_dir_treats_empty_git_output_as_failure(tmp_path):
    """If git somehow returns empty stdout, fall back rather than building
    an empty/garbage path."""
    completed = subprocess.CompletedProcess(args=["git"], returncode=0, stdout="", stderr="")
    with mock.patch.object(vt.subprocess, "run", return_value=completed):
        resolved = vt._resolve_canonical_locks_dir(tmp_path)
    assert resolved == tmp_path / "sysop/runtime/locks"


def test_locks_dir_resolves_inside_repo_for_staging_path(tmp_path):
    """Staging dir under a real repo resolves to the same `sysop/runtime/locks/` as the repo root."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
    )
    staging = repo_root / "tasks.staging"
    staging.mkdir()

    resolved_root = vt._resolve_canonical_locks_dir(repo_root)
    resolved_staging = vt._resolve_canonical_locks_dir(staging)
    assert resolved_root == (repo_root / "sysop/runtime/locks").resolve()
    assert resolved_staging == (repo_root / "sysop/runtime/locks").resolve()


# === Section 2: Sysop-original tests ==================================


_V2_INDEX_TEMPLATE = """\
schema_version: 2

phases:
  - number: 1
    title: "Active phase"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-LOCKED
    title: "Task in progress"
    phase: 1
    status: in_progress
    effort: Medium
    user_action: false
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-LOCKED.md
{extra}
"""


def _seed_repo_with_lock(tmp_path: Path, index_yaml: str = _VALID_INDEX) -> Path:
    """Init a git repo, write a tasks tree, and drop a lock for FEAT-LOCKED."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    tasks_dir = repo / "tasks"
    (tasks_dir / "open").mkdir(parents=True)
    (tasks_dir / "index.yml").write_text(index_yaml, encoding="utf-8")
    (tasks_dir / "open" / "FEAT-LOCKED.md").write_text(_VALID_BODY, encoding="utf-8")
    locks = repo / "sysop/runtime/locks"
    locks.mkdir(parents=True)
    (locks / "FEAT-LOCKED.lock").write_text("lock\n", encoding="utf-8")
    return repo


# ── Phase 19 — blast_radius schema field ─────────────────────────────────


def test_blast_radius_required_on_in_progress_at_schema_v2(tmp_path):
    """schema_version=2 + status=in_progress without blast_radius → error."""
    repo = _seed_repo_with_lock(
        tmp_path,
        _V2_INDEX_TEMPLATE.format(extra=""),
    )
    report = vt.validate(repo / "tasks", project_root=repo)
    messages = [f.format() for f in report.errors]
    assert any("blast_radius" in m for m in messages), messages


def test_blast_radius_accepted_when_valid_value_at_v2(tmp_path):
    """schema_version=2 + valid blast_radius → no blast_radius error."""
    repo = _seed_repo_with_lock(
        tmp_path,
        _V2_INDEX_TEMPLATE.format(extra="    blast_radius: single-module"),
    )
    report = vt.validate(repo / "tasks", project_root=repo)
    blast_errors = [f for f in report.errors if "blast_radius" in f.format()]
    assert blast_errors == [], [e.format() for e in blast_errors]


def test_blast_radius_rejects_invalid_enum_value(tmp_path):
    """Any blast_radius value not in the enum → error, regardless of schema_version."""
    index = _VALID_INDEX.replace(
        "    body: tasks/open/FEAT-LOCKED.md\n",
        "    body: tasks/open/FEAT-LOCKED.md\n    blast_radius: enormous\n",
    )
    repo = _seed_repo_with_lock(tmp_path, index)
    report = vt.validate(repo / "tasks", project_root=repo)
    messages = [f.format() for f in report.errors]
    assert any("blast_radius" in m and "enormous" in m for m in messages), messages


def test_blast_radius_optional_at_schema_v1_for_legacy_tasks(tmp_path):
    """schema_version=1 + in_progress without blast_radius → no error (legacy)."""
    repo = _seed_repo_with_lock(tmp_path)  # _VALID_INDEX is v1
    report = vt.validate(repo / "tasks", project_root=repo)
    blast_errors = [f for f in report.errors if "blast_radius" in f.format()]
    assert blast_errors == [], [e.format() for e in blast_errors]


# ── Phase 32 — in-progress lock invariant ────────────────────────────────


def test_in_progress_without_lock_file_errors(tmp_path):
    """status=in_progress + missing lock file under canonical sysop/runtime/locks/ → error."""
    repo = _seed_repo_with_lock(tmp_path)
    (repo / "sysop/runtime/locks" / "FEAT-LOCKED.lock").unlink()
    report = vt.validate(repo / "tasks", project_root=repo)
    messages = [f.format() for f in report.errors]
    assert any("lock file missing" in m for m in messages), messages


def test_in_progress_with_lock_file_passes(tmp_path):
    """status=in_progress + lock file present at canonical sysop/runtime/locks/ → no lock error."""
    repo = _seed_repo_with_lock(tmp_path)
    report = vt.validate(repo / "tasks", project_root=repo)
    lock_errors = [f for f in report.errors if "lock file missing" in f.format()]
    assert lock_errors == [], [e.format() for e in lock_errors]


# ── Phase 18 (ISSUE-0009) — status-vs-directory drift ────────────────────


def test_done_task_with_body_under_open_dir_errors(tmp_path):
    """status=done with body path containing 'open/' segment → error.

    This is the half-migrated state /review-close Step 4c can produce when
    the status flip succeeds but the corresponding `git mv` is skipped.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    tasks_dir = repo / "tasks"
    open_dir = tasks_dir / "open"
    open_dir.mkdir(parents=True)
    (open_dir / "FEAT-DONE.md").write_text("# FEAT-DONE\n", encoding="utf-8")
    (tasks_dir / "index.yml").write_text(
        "schema_version: 1\n"
        "\n"
        "phases:\n"
        "  - number: 1\n"
        '    title: "Done phase"\n'
        "    status: done\n"
        "    current_focus: false\n"
        "\n"
        "tasks:\n"
        "  - id: FEAT-DONE\n"
        '    title: "Drifted-status task"\n'
        "    phase: 1\n"
        "    status: done\n"
        "    completed_date: 2026-01-01\n"
        "    effort: Medium\n"
        "    user_action: false\n"
        "    depends_on: []\n"
        "    surfaced_by: []\n"
        "    body: tasks/open/FEAT-DONE.md\n",
        encoding="utf-8",
    )
    report = vt.validate(tasks_dir, project_root=repo)
    messages = [f.format() for f in report.errors]
    assert any("status=done but body path contains 'open/'" in m for m in messages), messages


def test_done_task_with_body_under_archive_dir_passes(tmp_path):
    """status=done with body under archive/ → no status-vs-directory error."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    tasks_dir = repo / "tasks"
    archive_dir = tasks_dir / "archive"
    archive_dir.mkdir(parents=True)
    (archive_dir / "FEAT-DONE.md").write_text("# FEAT-DONE\n", encoding="utf-8")
    (tasks_dir / "index.yml").write_text(
        "schema_version: 1\n"
        "\n"
        "phases:\n"
        "  - number: 1\n"
        '    title: "Done phase"\n'
        "    status: done\n"
        "    current_focus: false\n"
        "\n"
        "tasks:\n"
        "  - id: FEAT-DONE\n"
        '    title: "Archived done task"\n'
        "    phase: 1\n"
        "    status: done\n"
        "    completed_date: 2026-01-01\n"
        "    effort: Medium\n"
        "    user_action: false\n"
        "    depends_on: []\n"
        "    surfaced_by: []\n"
        "    body: tasks/archive/FEAT-DONE.md\n",
        encoding="utf-8",
    )
    report = vt.validate(tasks_dir, project_root=repo)
    drift_errors = [
        f for f in report.errors if "status=done but body path contains" in f.format()
    ]
    assert drift_errors == [], [e.format() for e in drift_errors]


# ── Phase 58b — test-decision recording (warn-only, in_progress only) ─────


_TD_OPEN_INDEX = """\
schema_version: 1

phases:
  - number: 1
    title: "Active phase"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-OPEN
    title: "Open backlog task, not yet claimed"
    phase: 1
    status: open
    effort: Low
    user_action: false
    depends_on: []
    surfaced_by: []
    body: tasks/open/FEAT-OPEN.md
"""


def _td_warnings(report):
    return [f for f in report.warnings if "test decision" in f.format().lower()]


def test_test_decision_warns_when_in_progress_body_lacks_section(tmp_path):
    """in_progress task whose body has no '## Test decision' → warn, not error.

    Warn-only is load-bearing: the recording gate is /review-close (Phase 59);
    a missing section must never block a commit.
    """
    repo = _seed_repo_with_lock(tmp_path)  # _VALID_BODY records no test decision
    report = vt.validate(repo / "tasks", project_root=repo)
    assert report.ok, [e.format() for e in report.errors]  # never blocks
    td = _td_warnings(report)
    assert td, [w.format() for w in report.warnings]
    assert any("FEAT-LOCKED" in w.format() for w in td)


def test_test_decision_no_warn_when_section_present(tmp_path):
    """in_progress body that records the section → no test-decision warning.

    The 'no test because Z' form must satisfy the check just like a named test.
    """
    repo = _seed_repo_with_lock(tmp_path)
    (repo / "tasks" / "open" / "FEAT-LOCKED.md").write_text(
        "# FEAT-LOCKED\n\n## Test decision\nNo test because this is a config-only change.\n",
        encoding="utf-8",
    )
    report = vt.validate(repo / "tasks", project_root=repo)
    assert _td_warnings(report) == [], [w.format() for w in report.warnings]


def test_test_decision_not_checked_for_open_task(tmp_path):
    """open (un-claimed) task lacking the section → no warning (scope is in_progress)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "--quiet"], cwd=str(repo), check=True, capture_output=True
    )
    tasks_dir = repo / "tasks"
    (tasks_dir / "open").mkdir(parents=True)
    (tasks_dir / "index.yml").write_text(_TD_OPEN_INDEX, encoding="utf-8")
    (tasks_dir / "open" / "FEAT-OPEN.md").write_text(
        "# FEAT-OPEN\n\n## Context\nBacklog.\n", encoding="utf-8"
    )
    report = vt.validate(tasks_dir, project_root=repo)
    assert _td_warnings(report) == [], [w.format() for w in report.warnings]


# ── Phase 88 — surfaced_by 'imported' provenance sentinel (/onboard) ─────


_P88_INDEX_TEMPLATE = """\
schema_version: 1

phases:
  - number: 1
    title: "Active phase"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-LOCKED
    title: "Task currently in progress"
    phase: 1
    status: in_progress
    effort: Medium
    user_action: false
    depends_on: {depends_on}
    surfaced_by: {surfaced_by}
    body: tasks/open/FEAT-LOCKED.md
"""


def _p88_repo(tmp_path: Path, depends_on: str, surfaced_by: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "--quiet"], cwd=str(repo), check=True, capture_output=True
    )
    tasks_dir = repo / "tasks"
    (tasks_dir / "open").mkdir(parents=True)
    (tasks_dir / "index.yml").write_text(
        _P88_INDEX_TEMPLATE.format(depends_on=depends_on, surfaced_by=surfaced_by),
        encoding="utf-8",
    )
    (tasks_dir / "open" / "FEAT-LOCKED.md").write_text(_VALID_BODY, encoding="utf-8")
    locks = repo / "sysop/runtime/locks"
    locks.mkdir(parents=True)
    (locks / "FEAT-LOCKED.lock").write_text("lock\n", encoding="utf-8")
    return repo


def _reference_errors(report) -> list:
    return [
        e.format()
        for e in report.errors
        if "references unknown task id" in e.format()
    ]


def test_surfaced_by_accepts_imported_sentinel(tmp_path):
    """surfaced_by: [imported] (the /onboard provenance marker) → no reference error."""
    repo = _p88_repo(tmp_path, depends_on="[]", surfaced_by="[imported]")
    report = vt.validate(repo / "tasks", project_root=repo)
    assert _reference_errors(report) == [], [e.format() for e in report.errors]


def test_surfaced_by_still_rejects_unknown_task_id(tmp_path):
    """A surfaced_by ref that is neither a known ID nor the sentinel → error."""
    repo = _p88_repo(tmp_path, depends_on="[]", surfaced_by="[FEAT-GHOST]")
    report = vt.validate(repo / "tasks", project_root=repo)
    errs = _reference_errors(report)
    assert len(errs) == 1, [e.format() for e in report.errors]
    assert "FEAT-GHOST" in errs[0]
    assert "'imported' provenance sentinel" in errs[0]


def test_depends_on_rejects_imported_sentinel(tmp_path):
    """The sentinel is surfaced_by-only: depends_on: [imported] → error."""
    repo = _p88_repo(tmp_path, depends_on="[imported]", surfaced_by="[]")
    report = vt.validate(repo / "tasks", project_root=repo)
    errs = _reference_errors(report)
    assert len(errs) == 1, [e.format() for e in report.errors]
    assert "depends_on" in errs[0]


# ── Invariant 3 — body / archive_summary path-traversal containment ──────────
#
# Both guards realpath-resolve the declared path and reject anything that lands
# outside the tasks/ base. The realpath step is load-bearing: a body string can
# read as a legitimate `tasks/open/<id>.md` while pointing (via `..` or a
# symlink) at a file elsewhere on disk. A regression here would let a malicious
# or fat-fingered index.yml pull an arbitrary file in as a "body," or let
# /review-close's Step 4c archive move follow a path out of the queue tree.


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "--quiet"], cwd=str(repo), check=True, capture_output=True
    )
    (repo / "tasks").mkdir()
    return repo


_ESCAPE_INDEX_TEMPLATE = """\
schema_version: 1

phases:
  - number: 1
    title: "Active phase"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-ESCAPE
    title: "Task with an escaping path"
    phase: 1
    status: open
    effort: Low
    user_action: false
    depends_on: []
    surfaced_by: []
    body: {body}
{extra}
"""


def test_body_path_with_dotdot_traversal_errors(tmp_path):
    """body: tasks/../escape.md resolves outside tasks/ → 'body path escapes' error."""
    repo = _git_repo(tmp_path)
    (repo / "tasks" / "index.yml").write_text(
        _ESCAPE_INDEX_TEMPLATE.format(body="tasks/../escape.md", extra=""),
        encoding="utf-8",
    )
    report = vt.validate(repo / "tasks", project_root=repo)
    messages = [f.format() for f in report.errors]
    assert any("body path escapes tasks/ base" in m for m in messages), messages


def test_body_symlink_escaping_tasks_errors(tmp_path):
    """A body path that is a symlink pointing outside tasks/ → escape error.

    This is the case only the realpath resolution catches: the declared string
    ``tasks/open/FEAT-ESCAPE.md`` is legitimately under tasks/, but the symlink
    target is not. A purely lexical (string-prefix) check would pass it.
    """
    repo = _git_repo(tmp_path)
    (repo / "tasks" / "open").mkdir()
    # A real file living OUTSIDE the tasks/ tree (but inside the repo).
    outside = repo / "outside_secret.md"
    outside.write_text("# not a task body\n", encoding="utf-8")
    os.symlink(outside, repo / "tasks" / "open" / "FEAT-ESCAPE.md")
    (repo / "tasks" / "index.yml").write_text(
        _ESCAPE_INDEX_TEMPLATE.format(body="tasks/open/FEAT-ESCAPE.md", extra=""),
        encoding="utf-8",
    )
    report = vt.validate(repo / "tasks", project_root=repo)
    messages = [f.format() for f in report.errors]
    assert any("body path escapes tasks/ base" in m for m in messages), messages


def test_archive_summary_path_traversal_errors(tmp_path):
    """archive_summary: tasks/../escape.md → 'archive_summary path escapes' error."""
    repo = _git_repo(tmp_path)
    (repo / "tasks" / "index.yml").write_text(
        _ESCAPE_INDEX_TEMPLATE.format(
            body="tasks/open/FEAT-ESCAPE.md",
            extra="    archive_summary: tasks/../escape.md",
        ),
        encoding="utf-8",
    )
    # A valid body so the archive_summary guard is what fires, not a body error.
    (repo / "tasks" / "open").mkdir()
    (repo / "tasks" / "open" / "FEAT-ESCAPE.md").write_text(
        "# FEAT-ESCAPE\n", encoding="utf-8"
    )
    report = vt.validate(repo / "tasks", project_root=repo)
    messages = [f.format() for f in report.errors]
    assert any("archive_summary path escapes tasks/ base" in m for m in messages), messages


def test_legitimate_body_path_produces_no_escape_error(tmp_path):
    """A normal in-tree body path must NOT trip the containment guard (no over-firing)."""
    repo = _seed_repo_with_lock(tmp_path)  # body: tasks/open/FEAT-LOCKED.md
    report = vt.validate(repo / "tasks", project_root=repo)
    escape_errors = [f for f in report.errors if "escapes tasks/ base" in f.format()]
    assert escape_errors == [], [e.format() for e in escape_errors]


# ── Invariant 11 — secret-pattern scan of tasks/**/*.md (warn-only) ──────────
#
# The scanner is a defense-in-depth backstop: task bodies are prose, but an
# author pasting an error log or config snippet can leak a live credential into
# a committed .md. Warn-only (never blocks a commit); these pin that each of the
# three patterns fires and that a clean body stays quiet.


def _secret_warnings(report):
    keys = ("AWS access key", "sk- prefixed token", "long hex string")
    return [f for f in report.warnings if any(k in f.format() for k in keys)]


def _repo_with_body(tmp_path: Path, body_text: str) -> Path:
    repo = _seed_repo_with_lock(tmp_path)
    (repo / "tasks" / "open" / "FEAT-LOCKED.md").write_text(body_text, encoding="utf-8")
    return repo


def test_secret_scan_flags_aws_access_key(tmp_path):
    """An AKIA-prefixed access key in a body → AWS-key warning (never an error)."""
    repo = _repo_with_body(
        tmp_path, "# FEAT-LOCKED\n\naws_key = AKIAIOSFODNN7EXAMPLE\n"
    )
    report = vt.validate(repo / "tasks", project_root=repo)
    assert report.ok, [e.format() for e in report.errors]  # warn-only, never blocks
    warns = _secret_warnings(report)
    assert any("AWS access key" in w.format() for w in warns), [w.format() for w in report.warnings]


def test_secret_scan_flags_sk_prefixed_token(tmp_path):
    """An sk-prefixed token (API-key shape) in a body → sk- token warning."""
    repo = _repo_with_body(
        tmp_path, "# FEAT-LOCKED\n\ntoken = sk-abcdefghijklmnopqrstuvwxyz0123\n"
    )
    report = vt.validate(repo / "tasks", project_root=repo)
    warns = _secret_warnings(report)
    assert any("sk- prefixed token" in w.format() for w in warns), [w.format() for w in report.warnings]


def test_secret_scan_flags_long_hex_string(tmp_path):
    """A 32+ char hex run (digest / token shape) in a body → long-hex warning."""
    repo = _repo_with_body(
        tmp_path, "# FEAT-LOCKED\n\ndigest = a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6\n"
    )
    report = vt.validate(repo / "tasks", project_root=repo)
    warns = _secret_warnings(report)
    assert any("long hex string" in w.format() for w in warns), [w.format() for w in report.warnings]


def test_secret_scan_clean_body_emits_no_secret_warning(tmp_path):
    """A body with no credential-shaped strings → zero secret warnings (no false positives)."""
    repo = _repo_with_body(
        tmp_path, "# FEAT-LOCKED\n\n## Context\nA plain prose body, nothing sensitive.\n"
    )
    report = vt.validate(repo / "tasks", project_root=repo)
    assert _secret_warnings(report) == [], [w.format() for w in report.warnings]


# ── Phase 105: Invariant-10 required fields (effort / user_action) ──────────
#
# _VALID_INDEX's FEAT-LOCKED is in_progress with both fields, so removing one
# leaves that field's error as the only new one. These lock the open/in_progress
# requirement — mutating the guard to `if False:` reddens each.


def test_effort_required_on_in_progress_task(tmp_path):
    index = _VALID_INDEX.replace("    effort: Medium\n", "")
    repo = _seed_repo_with_lock(tmp_path, index)
    report = vt.validate(repo / "tasks", project_root=repo)
    messages = [f.format() for f in report.errors]
    assert any("requires 'effort'" in m for m in messages), messages


def test_user_action_required_on_in_progress_task(tmp_path):
    index = _VALID_INDEX.replace("    user_action: false\n", "")
    repo = _seed_repo_with_lock(tmp_path, index)
    report = vt.validate(repo / "tasks", project_root=repo)
    messages = [f.format() for f in report.errors]
    assert any("requires 'user_action'" in m for m in messages), messages


def test_effort_and_user_action_present_produce_no_invariant10_error(tmp_path):
    """Positive control: the valid fixture (both fields) emits neither error —
    guards against the opposite mutation (`if True:` → always-error)."""
    repo = _seed_repo_with_lock(tmp_path)
    messages = [f.format() for f in vt.validate(repo / "tasks", project_root=repo).errors]
    assert not any("requires 'effort'" in m for m in messages), messages
    assert not any("requires 'user_action'" in m for m in messages), messages


# ── Phase 105: _check_manual_smoke type guard + _validate_orphans (Inv. 4) ──
#
# Both functions run in the real validate() path but their specific branches
# (non-bool manual_smoke; an unreferenced body file) were reached only by the
# never-run embedded --self-test, so pytest never actually exercised them.


def test_manual_smoke_non_bool_is_hard_error(tmp_path):
    # Quoted "yes" parses as a str (YAML 1.1 would make bare `yes` a bool).
    index = _VALID_INDEX.replace(
        "    body: tasks/open/FEAT-LOCKED.md\n",
        "    body: tasks/open/FEAT-LOCKED.md\n    manual_smoke: \"yes\"\n",
    )
    repo = _seed_repo_with_lock(tmp_path, index)
    report = vt.validate(repo / "tasks", project_root=repo)
    assert not report.ok
    messages = [f.format() for f in report.errors]
    assert any("'manual_smoke' must be bool" in m for m in messages), messages


def test_manual_smoke_true_bool_is_not_a_type_error(tmp_path):
    # A real bool never trips the type guard (it may warn about a missing
    # heading, but that is not an error).
    index = _VALID_INDEX.replace(
        "    body: tasks/open/FEAT-LOCKED.md\n",
        "    body: tasks/open/FEAT-LOCKED.md\n    manual_smoke: true\n",
    )
    repo = _seed_repo_with_lock(tmp_path, index)
    report = vt.validate(repo / "tasks", project_root=repo)
    messages = [f.format() for f in report.errors]
    assert not any("'manual_smoke' must be bool" in m for m in messages), messages


def test_orphan_body_file_under_open_errors(tmp_path):
    # An unreferenced .md under tasks/open/ (plain name, not a _phase_N summary,
    # which takes a different message) → Invariant-4 orphan error.
    repo = _seed_repo_with_lock(tmp_path)
    (repo / "tasks" / "open" / "ORPHAN.md").write_text("# stray\n", encoding="utf-8")
    report = vt.validate(repo / "tasks", project_root=repo)
    messages = [f.format() for f in report.errors]
    assert any("orphan body file" in m for m in messages), messages
