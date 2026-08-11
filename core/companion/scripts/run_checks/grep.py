"""Grep-based check runner (the dispatcher for the ``checks.yml`` registry)."""
import fnmatch
import os
import re
import subprocess
import sys

from _log import _sanitize_log

from .accounting import (
    EXECUTED,
    FAILED,
    SKIPPED,
    UNROUTABLE,
    Outcome,
    is_placeholder_token,
    stderr_excerpt,
)
from .config import _SKIP_DIRS


# Inline waiver marker: `no-check: <id>[, <id>…]`, the grep-stage counterpart to
# semgrep's `# nosemgrep` / coverage's `# pragma: no cover`. Deliberately
# comment-syntax agnostic (the token, not `#` vs `//`), because one registry
# scans Python, TypeScript, SQL and YAML.
#
# Two design calls worth keeping:
#   * A BARE `no-check:` waives nothing. A blanket marker would silently
#     disable checks that do not exist yet — including a future
#     `severity: critical` one — so the ids are mandatory.
#   * The id list stops at the first non-id character, so a trailing rationale
#     (`# no-check: <id> — table name is validated upstream`) is fine. The
#     corollary is that an id containing anything outside [A-Za-z0-9_-] cannot
#     be waived; every shipped id is `[a-z0-9-]`, and widening the class would
#     swallow the rationale (`<id>. Next sentence` would capture `<id>.`).
#     NOTE the placeholder: writing a real id here would mint a LIVE marker in
#     this file, which is shipped and is scanned by any `*.py` check.
#   * Horizontal whitespace ONLY, and matched per line. `\s` matches newlines,
#     and a file-level (`invert_file_check`) check hands this the WHOLE FILE —
#     so with `\s*` a bare `no-check:` swallowed the next identifier-shaped
#     token further down the file, waiving whatever it happened to spell. That
#     falsified the "a bare marker waives nothing" rule on the one path where
#     the marker is allowed to live anywhere. Splitting per line makes it
#     structurally impossible; `[ \t]` makes it impossible again.
#   * `\b` so `xno-check:` is not a marker.
_WAIVER_RE = re.compile(
    r"\bno-check:[ \t]*([A-Za-z0-9_-]+(?:[ \t]*,[ \t]*[A-Za-z0-9_-]+)*)"
)


def waived_ids(text):
    """Return the set of check ids waived by ``no-check:`` markers in ``text``.

    Case-sensitive, like ``# nosemgrep`` / ``# noqa`` / ``# type: ignore``.
    """
    ids = set()
    for line in (text or "").splitlines():
        for match in _WAIVER_RE.finditer(line):
            ids.update(p.strip() for p in match.group(1).split(",") if p.strip())
    return ids


def _paths_unresolved_detail(paths):
    """Human detail for a grep check whose ``paths:`` resolved to nothing.

    Distinguishes the fresh-install case (every entry is still placeholder
    vocabulary) from a localized entry that has since vanished from disk — the
    two read very differently to a consumer scanning the summary.
    """
    entries = list(paths or [])
    if entries and all(is_placeholder_token(p) for p in entries):
        return "paths unresolved: placeholder globs not yet localized"
    return "paths unresolved: no configured path resolved on disk"


def _run_grep_status(pattern, paths, includes, excludes, repo_root, exclude_dirs=()):
    """Run grep -rn and return ``(Outcome, lines)``.

    The Outcome carries the terminal state (executed / skipped / failed) so the
    single per-check record point in ``run_check`` can account for the stage —
    grep itself has no check id at this call site (spec §5). ``run_grep`` (the
    original list-returning name) is a thin wrapper over this.
    """
    cmd = ["grep", "-rn", "-E", pattern]
    for inc in includes:
        cmd.extend(["--include", inc])
    # Always exclude common non-source directories
    for d in _SKIP_DIRS:
        cmd.extend(["--exclude-dir", d])
    # Per-check excludes (file globs like "*test*", "*helpers.py")
    for exc in excludes:
        cmd.extend(["--exclude", exc])
    # Per-check subtree excludes (Phase 133, leg-5 dogfood finding 4): the
    # file-glob `exclude:` cannot drop a whole subtree, so a broad `paths:`
    # root (e.g. a package that contains migrations/) couldn't be narrowed —
    # `exclude_dir:` maps to grep --exclude-dir, which matches DIRECTORY
    # BASENAMES (globs) at any depth, exactly grep's semantics.
    for exc_dir in exclude_dirs:
        cmd.extend(["--exclude-dir", exc_dir])

    # Resolve paths relative to repo root; collect only those that exist.
    # If none resolve (e.g., a fresh install where placeholder vocabulary
    # like `<api module>/` hasn't been substituted yet), skip — never fall
    # through to a CWD-wide scan, since that surfaces noise findings on every
    # file in the tree.
    valid_paths = []
    for p in paths:
        full = os.path.join(repo_root, p)
        if os.path.exists(full):
            valid_paths.append(full)
    if not valid_paths:
        return Outcome(SKIPPED, "paths-unresolved", _paths_unresolved_detail(paths)), []
    cmd.extend(valid_paths)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=repo_root, timeout=30
        )
    except subprocess.TimeoutExpired:
        # A timeout is lost work, not a declined precondition — `failed`.
        return Outcome(FAILED, "timeout", "grep timed out after 30s"), []
    except FileNotFoundError:
        # grep is a hard dependency, but a truly missing binary is a skip
        # (precondition absent), not a crash — consistent with §1's tool-missing.
        return Outcome(SKIPPED, "tool-missing", "grep not on PATH"), []

    # grep exit codes: 0 = matches, 1 = no matches (expected), 2+ = a real
    # error (unreadable file, malformed regex). Treat 2+ as a noisy warn AND a
    # `failed` record — silently swallowing it hides a broken check behind a
    # clean "0 findings" (the whole point of the accounting layer).
    if result.returncode >= 2:
        err = _sanitize_log(result.stderr) if result.stderr else "(no stderr)"
        print(
            f"warn: grep failed (rc={result.returncode}): {err}",
            file=sys.stderr,
        )
        return (
            Outcome(FAILED, "grep-error",
                    f"grep error (rc={result.returncode}): {stderr_excerpt(result.stderr)}"),
            [],
        )
    lines = [l for l in result.stdout.strip().split("\n") if l]
    return Outcome(EXECUTED, None, None), lines


def run_grep(pattern, paths, includes, excludes, repo_root, exclude_dirs=()):
    """Run grep -rn and return the match lines (back-compat wrapper).

    Retained as stable public API on the ``run_checks_impl`` re-export surface
    and for existing direct callers/tests. New accounting-aware code calls
    ``_run_grep_status`` for the ``(Outcome, lines)`` pair it needs to record
    the stage's terminal state.
    """
    return _run_grep_status(
        pattern, paths, includes, excludes, repo_root, exclude_dirs
    )[1]


def strip_repo_prefix(line, repo_root):
    """Remove repo root prefix from file paths in grep output."""
    prefix = repo_root.rstrip("/") + "/"
    if line.startswith(prefix):
        return line[len(prefix):]
    return line


def _iter_check_files(paths, includes, excludes, repo_root, exclude_dirs=()):
    """Yield absolute paths of files in `paths` matching `includes` and not `excludes`.

    Mirrors the filter semantics of `run_grep` (without invoking grep) —
    including `exclude_dirs` basename-glob pruning, kept in lockstep with the
    --exclude-dir flags run_grep passes. Used by file-walk-based checks like
    `position_check` that need full-file context rather than per-line hits.
    """
    skip_dirs = set(_SKIP_DIRS)
    for p in paths:
        full = os.path.join(repo_root, p)
        if not os.path.exists(full):
            continue
        # grep --exclude-dir also skips a command-line directory whose own
        # basename matches — mirror that so a `paths:` root caught by
        # exclude_dir behaves identically in both scan paths.
        root_base = os.path.basename(os.path.normpath(full))
        if os.path.isdir(full) and any(
            fnmatch.fnmatch(root_base, xd) for xd in exclude_dirs
        ):
            continue
        for dirpath, dirnames, filenames in os.walk(full):
            dirnames[:] = [
                d for d in dirnames
                if d not in skip_dirs
                and not any(fnmatch.fnmatch(d, xd) for xd in exclude_dirs)
            ]
            for fn in filenames:
                if includes and not any(fnmatch.fnmatch(fn, inc) for inc in includes):
                    continue
                if excludes and any(fnmatch.fnmatch(fn, exc) for exc in excludes):
                    continue
                yield os.path.join(dirpath, fn)


def _first_match_line(content_lines, regex):
    """Return the 1-indexed line number of the first match, or None.

    Skips comment-only lines (a leading `#` after optional whitespace) so that
    a commented-out `# sys.path.insert(...)` at the top of a file doesn't
    spoof the position check.
    """
    for idx, line in enumerate(content_lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if regex.search(line):
            return idx
    return None


_POSITION_CHECK_RE_CACHE: dict[str, "re.Pattern[str]"] = {}


def _cached_compile(src):
    """Module-level memoization to avoid per-call re.compile overhead.

    Keeps the position_check helper from being a dogfood violation of
    `recompile-inside-def`.
    """
    if src not in _POSITION_CHECK_RE_CACHE:
        # Parameterized regex memoized in a module-level dict; rule message
        # names this exact pattern as a legitimate exception. Inline nosemgrep
        # is required because pattern-inside `def $F(...)` matches the whole
        # body, not just this line.
        _POSITION_CHECK_RE_CACHE[src] = re.compile(src)  # nosemgrep: recompile-inside-def
    return _POSITION_CHECK_RE_CACHE[src]


def _run_position_check(
    check_id, spec, paths, includes, excludes,
    severity, description, repo_root, exclude_dirs=(), report=None,
):
    """Fire when `later` precedes `earlier` in the same file.

    `spec` is a dict {earlier: <regex>, later: <regex>}. Both regexes are
    matched per non-comment line. If either is absent in a file, no
    finding (out of scope — missing-X is a separate convention).

    An inline ``no-check: <id>`` marker on the REPORTED line (the `later`
    match, which is the line the finding cites) waives the finding.
    """
    earlier_re_src = spec.get("earlier", "")
    later_re_src = spec.get("later", "")
    if not earlier_re_src or not later_re_src:
        return []
    try:
        earlier_re = _cached_compile(earlier_re_src)
        later_re = _cached_compile(later_re_src)
    except re.error:
        return []

    findings = []
    for fpath in sorted(
        _iter_check_files(paths, includes, excludes, repo_root, exclude_dirs)
    ):
        try:
            with open(fpath, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except (OSError, IOError):
            continue
        e_line = _first_match_line(lines, earlier_re)
        l_line = _first_match_line(lines, later_re)
        if e_line is None or l_line is None:
            continue
        if l_line < e_line:
            rel = fpath.replace(repo_root.rstrip("/") + "/", "")
            file_line = f"{rel}:{l_line}"
            message = f"[{check_id}] {severity} {file_line} — {description}"
            if check_id in waived_ids(lines[l_line - 1]):
                if report is not None:
                    report.record_waived(check_id, file_line, message)
                continue
            findings.append((check_id, file_line, message))
    return findings


def run_check(check, repo_root, report=None):
    """Run a single check and return a list of (check_id, file_line, message) tuples.

    file_line is "<path>:<lineno>" (or bare "<path>" for file-level checks)
    and serves as the baseline key. message is the full "[id] SEV path:line —
    description" line displayed to the user.

    ``report`` is the optional accounting collector (``accounting.RunReport``);
    when provided, this is the single record point for the grep stage — every
    terminal branch records the check's state exactly once. ``report=None``
    preserves the original behavior for legacy/direct callers and existing
    tests (spec §2).
    """
    pattern = check.get("pattern", "")
    paths = check.get("paths", [])
    includes = check.get("include", [])
    excludes = check.get("exclude", [])
    exclude_dirs = check.get("exclude_dir", []) or []
    neg_pattern = check.get("negative_pattern", "")
    invert = check.get("invert_file_check", False)
    position_check = check.get("position_check", None)
    severity = check.get("severity", "medium").upper()
    check_id = check.get("id", "unknown")
    description = check.get("description", "")

    def _record(status, reason=None, detail=None):
        if report is not None:
            report.record([check_id], status, "grep", reason, detail)

    def _emit(findings, file_line, waiver_text):
        """Append a finding unless ``waiver_text`` carries a ``no-check:`` for it.

        ``waiver_text`` is the matched LINE for line-level checks and the whole
        FILE for file-level (`invert_file_check`) ones — a file-level finding
        cites no line, so there is nowhere else the marker could live. A waived
        finding is handed to the report, never dropped on the floor; with
        ``report=None`` (direct callers and tests — no shipped CLI path) the
        suppression still applies but the audit line has nowhere to go.
        """
        message = f"[{check_id}] {severity} {file_line} — {description}"
        if check_id in waived_ids(waiver_text):
            if report is not None:
                report.record_waived(check_id, file_line, message)
            return
        findings.append((check_id, file_line, message))

    # position_check is an alternative dispatch — no `pattern:` is required.
    # Schema: {earlier: <regex>, later: <regex>}. Fires when both patterns
    # match in the same file AND `later`'s first occurrence precedes
    # `earlier`'s first occurrence (i.e., wrong order).
    if position_check and paths:
        earlier_src = position_check.get("earlier", "")
        later_src = position_check.get("later", "")
        if not earlier_src or not later_src:
            _record(SKIPPED, "not-configured",
                    "position_check missing earlier/later regex")
            return []
        try:
            _cached_compile(earlier_src)
            _cached_compile(later_src)
        except re.error as e:
            _record(SKIPPED, "misconfigured",
                    f"invalid position_check regex: {stderr_excerpt(str(e))}")
            return []
        if not any(os.path.exists(os.path.join(repo_root, p)) for p in paths):
            _record(SKIPPED, "paths-unresolved", _paths_unresolved_detail(paths))
            return []
        findings = _run_position_check(
            check_id, position_check, paths, includes, excludes,
            severity, description, repo_root, exclude_dirs, report,
        )
        _record(EXECUTED)
        return findings

    # Phase 189 / upstream #239: these were one arm reporting `skipped:
    # not-configured`, which put two different things in the same words. A check with
    # no `pattern:` and no `position_check:` declares no executable form at all — it
    # can never run in ANY environment, so it is a registry-authoring defect, and
    # GDP's `doc-parity-violation` sat in that state for weeks reading identically to
    # a tool that merely was not installed here. A check that HAS a pattern but no
    # resolvable paths is an ordinary precondition-absent skip, which is what the
    # `skipped` bucket is load-bearing for.
    if not pattern and not position_check:
        _record(UNROUTABLE, "no-executable-form",
                "no pattern: or position_check: — this check cannot execute in any "
                "environment; declare a kind or remove it")
        return []
    if not paths:
        _record(SKIPPED, "paths-unresolved", _paths_unresolved_detail(paths))
        return []

    outcome, hits = _run_grep_status(
        pattern, paths, includes, excludes, repo_root, exclude_dirs
    )
    _record(outcome.status, outcome.reason, outcome.detail)
    if outcome.status != EXECUTED or not hits:
        return []

    findings = []

    if invert and neg_pattern:
        # File-level check: find files with pattern but WITHOUT neg_pattern
        files_with_pattern = set()
        for hit in hits:
            parts = hit.split(":", 2)
            if len(parts) >= 2:
                fpath = strip_repo_prefix(parts[0], repo_root)
                files_with_pattern.add(os.path.join(repo_root, fpath)
                                       if not os.path.isabs(fpath)
                                       else fpath)

        repo_root_real = os.path.realpath(repo_root) + os.sep
        for fpath in sorted(files_with_pattern):
            # Path containment: grep output is trusted by the framework, but a
            # symlink under one of the scanned `paths` could point outside the
            # repo. Reject anything that doesn't resolve inside repo_root
            # before opening.
            resolved = os.path.realpath(fpath)
            if not resolved.startswith(repo_root_real):
                continue
            try:
                with open(fpath, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                if not re.search(neg_pattern, content):
                    rel = fpath.replace(repo_root.rstrip("/") + "/", "")
                    _emit(findings, rel, content)
            except (OSError, IOError):
                pass

    elif neg_pattern:
        # Per-line filter: keep hits that do NOT match negative_pattern
        for hit in hits:
            hit_clean = strip_repo_prefix(hit, repo_root)
            parts = hit_clean.split(":", 2)
            if len(parts) >= 3:
                content_part = parts[2]
                if not re.search(neg_pattern, content_part):
                    _emit(findings, f"{parts[0]}:{parts[1]}", content_part)
            else:
                _emit(findings, hit_clean, "")

    else:
        # Simple pattern match — all hits are findings
        for hit in hits:
            hit_clean = strip_repo_prefix(hit, repo_root)
            parts = hit_clean.split(":", 2)
            if len(parts) >= 2:
                # parts[2] is grep -rn's content column; absent only if a path
                # itself contains ':' in a way that eats the split budget.
                _emit(findings, f"{parts[0]}:{parts[1]}",
                      parts[2] if len(parts) >= 3 else "")

    return findings
