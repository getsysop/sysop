"""Glob-scoped diff-coverage gate (Phase 61a measurement + Phase 61b gate).

Crown-jewel coverage gate: shells out to ``diff-cover`` and reports *changed*
lines that lack test coverage, **filtered to a few critical-path globs** so
consumer-CI weight stays small. Findings are emitted in the same
``(check_id, file_line, message)`` shape as the grep / LSP / semgrep /
pip-audit stages so ``--mode`` filtering and ``--fail-on-blocking`` apply
uniformly.

This stage only *produces* findings — whether they block is decided in
``cli.py`` from each check's ``blocking`` flag. A ``blocking: true`` coverage
check is the Phase 61b crown-jewel hard gate: an uncovered changed line inside
a ``critical_path`` glob fails ``--fail-on-blocking`` and, unlike every other
stage, **never baseline-suppresses** (a diff-relative coverage gap can't be
accepted as standing tech debt — see ``baseline.is_baseline_suppressed``). A
consumer who wants measurement only keeps ``blocking: false``.

Design (ratified for Phase 61a): both the Python and the frontend legs route
through ``diff-cover``. ``diff-cover`` is language-agnostic over coverage
report formats — it reads Cobertura XML from ``coverage.py`` / ``pytest-cov``
(Python) and lcov from ``c8`` / ``istanbul`` (frontend) alike — so one parser
covers both and the result is uniform *diff* coverage (changed-but-uncovered
lines), which is exactly what the Phase 61b gate is defined against. The
language-native coverage tools (``pytest-cov``, ``c8`` / ``istanbul``) are the
report *producers*, run by the consumer's CI ahead of this stage — neither is
invoked here, just as ``run_checks`` never runs the test suite to produce
``coverage.xml``.

Each coverage check carries:
  * ``critical_path`` — the crown-jewel globs that scope the measurement
    (the new schema capability; consumer-authored, never installer-
    substituted — substitution touches ``paths:`` only).
  * ``report`` — the coverage report path fed to ``diff-cover`` (defaults
    per check id; consumer-overridable).

The stage skips gracefully (returns ``[]``) whenever:
  * the check declares no ``critical_path`` globs (nothing to measure),
  * the coverage report file is absent (CI didn't produce one),
  * ``diff-cover`` is not on PATH (FileNotFoundError),
  * the subprocess times out (300s) or emits non-JSON output.
"""
import fnmatch
import json
import os
import subprocess
import sys

from _log import _sanitize_log

from .accounting import (
    EXECUTED,
    FAILED,
    SKIPPED,
    is_placeholder_token,
    stderr_excerpt,
)


# Default coverage-report path per recognized check id. Consumers override
# via the check's `report:` field. The producers (pytest-cov -> coverage.xml,
# c8/istanbul -> coverage/lcov.info) are a consumer-CI concern, not run here.
_DEFAULT_REPORT = {
    "coverage-diff-python": "coverage.xml",
    "coverage-diff-frontend": os.path.join("coverage", "lcov.info"),
}


def _path_in_critical(rel_path, critical_paths):
    """Return True when `rel_path` matches any critical-path glob.

    Globs are fnmatch-style over repo-relative, forward-slash paths. A bare
    directory glob ("billing/" or "billing") matches everything beneath it
    without requiring a trailing wildcard, so consumers can write the natural
    "billing/" rather than "billing/**". fnmatchcase keeps matching
    deterministic across case-insensitive filesystems (macOS) and CI (Linux).
    """
    norm = rel_path.replace(os.sep, "/")
    for glob in critical_paths:
        g = str(glob).replace(os.sep, "/")
        if fnmatch.fnmatchcase(norm, g):
            return True
        gdir = g.rstrip("/")
        if gdir and (norm == gdir or norm.startswith(gdir + "/")):
            return True
    return False


def _run_diff_cover_check(repo_root, check, report=None):
    """Run diff-cover for one coverage check, return (check_id, file_line, msg) tuples.

    `check` is a parsed checks.yml entry whose id starts `coverage-`. Reads
    its `critical_path` globs and `report` path (default per id). Emits one
    finding per changed-but-uncovered line that falls inside a crown-jewel
    glob. ``report`` is the optional accounting collector; each coverage check
    runs its own subprocess and records its own state. The blocking coverage
    gate (Phases 61a/61b) is exactly the case the accounting layer exists to
    surface — a blocking gate that skips its report file used to contribute,
    invoke, and say nothing.
    """
    check_id = check.get("id", "")

    def _record(status, reason=None, detail=None):
        if report is not None and check_id:
            report.record([check_id], status, "coverage", reason, detail)

    critical_paths = check.get("critical_path", []) or []
    # A placeholder (or empty) critical_path is an unarmed gate on a fresh
    # install — record it as calm not-configured, checked BEFORE the report
    # file so the summary reads "not yet configured; gate unarmed" rather than
    # "report absent" (which would imply the gate was armed). check_is_localized
    # keys the ⚠ suffix off the same placeholder test at render time.
    localized_cp = [p for p in critical_paths if not is_placeholder_token(p)]
    if not localized_cp:
        _record(SKIPPED, "not-configured",
                "critical_path not yet configured (placeholder globs); gate unarmed")
        return []

    report_rel = check.get("report") or _DEFAULT_REPORT.get(check_id)
    if not report_rel:
        _record(SKIPPED, "not-configured", "no report path resolvable for check")
        return []
    report_abs = os.path.join(repo_root, report_rel)
    if not os.path.isfile(report_abs):
        # CI hasn't produced a coverage report for this leg. With a LOCALIZED
        # critical_path this is an armed gate whose input is missing — recorded
        # skipped(input-missing) so the summary flags it (⚠ when blocking),
        # instead of the old silent return that made a dead gate invisible.
        _record(SKIPPED, "input-missing",
                f"coverage report {report_rel} absent "
                "(produced by pytest --cov / c8 before this gate)")
        return []

    out = []
    try:
        r = subprocess.run(
            ["diff-cover", report_rel, "--format", "json"],
            capture_output=True, text=True, cwd=repo_root, timeout=300,
        )
    except FileNotFoundError:
        print("warn: diff-cover not on PATH — skipping coverage measurement "
              "(install: pip install diff-cover)", file=sys.stderr)
        _record(SKIPPED, "tool-missing", "diff-cover not on PATH")
        return out
    except subprocess.TimeoutExpired:
        print("warn: diff-cover exceeded 300s timeout — skipping coverage "
              "measurement (findings may be incomplete)", file=sys.stderr)
        _record(FAILED, "timeout", "diff-cover timed out after 300s")
        return out

    if not r.stdout:
        if r.returncode != 0:
            print(f"warn: diff-cover exited {r.returncode} with no output — "
                  f"coverage measurement did NOT run: {stderr_excerpt(r.stderr)}",
                  file=sys.stderr)
            _record(FAILED, "nonzero-no-output",
                    f"exit {r.returncode}: {stderr_excerpt(r.stderr)}")
        else:
            _record(EXECUTED)
        return out
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        print("warn: diff-cover produced non-JSON output — skipping coverage "
              "measurement", file=sys.stderr)
        _record(FAILED, "non-json", "diff-cover produced non-JSON output")
        return out

    _record(EXECUTED)

    # diff-cover JSON: {src_stats: {<path>: {percent_covered, covered_lines,
    # violation_lines, violations}}}. Paths are already repo-relative. Each
    # entry in `violation_lines` is a changed line not covered by tests.
    src_stats = data.get("src_stats", {})
    if not isinstance(src_stats, dict):
        return out
    for path, stats in src_stats.items():
        rel = str(path).replace(os.sep, "/")
        if not _path_in_critical(rel, critical_paths):
            continue
        if not isinstance(stats, dict):
            continue
        pct = stats.get("percent_covered")
        pct_str = f"{pct:.0f}%" if isinstance(pct, (int, float)) else "?"
        for line in stats.get("violation_lines", []) or []:
            file_line = f"{rel}:{line}"
            out.append((
                check_id, file_line,
                f"[{check_id}] MEDIUM {file_line} — changed line not covered "
                f"by tests ({pct_str} of changed lines covered in this file; "
                f"critical path)",
            ))
    return out


def _run_coverage(repo_root, coverage_checks, report=None):
    """Dispatch every mode-filtered coverage check through diff-cover.

    `coverage_checks` is the list of parsed checks (id startswith
    `coverage-`) that passed the caller's --mode filter. Returns the
    concatenated findings. Each check is isolated in a try/except so one
    malformed entry cannot kill the stage (mirrors cli.py's run_check loop);
    a check that raises here is recorded ``failed`` so the accounting reflects
    the crash rather than an unaccounted hole.
    """
    out = []
    for check in coverage_checks:
        try:
            out.extend(_run_diff_cover_check(repo_root, check, report))
        except Exception as e:  # pragma: no cover - defensive isolation
            print(f"warn: coverage check {check.get('id')} failed: "
                  f"{_sanitize_log(e)}", file=sys.stderr)
            if report is not None and check.get("id"):
                report.record([check.get("id")], FAILED, "coverage",
                              "exception", stderr_excerpt(str(e)))
    return out
