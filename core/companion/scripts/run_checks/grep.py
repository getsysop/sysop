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
from .baseline import identity_of
from .config import _SKIP_DIRS


# Fallback parse for a grep hit that arrives WITHOUT the `--null` separator
# (an external caller's own lines, or a grep too old for the flag). LAZY on the
# path, so the FIRST `:<digits>:` boundary wins — which is byte-for-byte the
# pre-212 `split(":", 2)` behaviour, deliberately.
#
# The first cut was greedy, on the reasoning that a colon in a path is the thing
# being fixed. The round measured it and the reasoning was wrong: greedy makes
# the fallback WORSE than what it replaces whenever the CONTENT holds a
# `:<digits>:` run — a timestamp literal like "10" colon "30" colon "00", or a
# slice step like arr[1:2:3]. Both are ordinary Python, and both appear in this
# module's own list of content colons. (Spelled out rather than shown as a
# sample hit on purpose: a literal `<path>:<line>:` in a comment is read as a
# source citation by `tests/test_intra_repo_citations.py`, which flagged the
# first version of this paragraph for pointing at a file that does not exist.) Content containing
# `:<digits>:` is far commoner than a path containing one, so the compatibility
# path keeps compatibility semantics and the CORRECT parse stays where it
# belongs: on `--null`, which has no ambiguity to resolve. Phase 212.
_HIT_RE = re.compile(r"^(?P<path>.*?):(?P<line>\d+):(?P<content>.*)$", re.S)

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
    # `--null` puts a NUL between the filename and the rest of the hit, and NUL
    # is the one byte a POSIX path cannot contain — so the path column becomes
    # unambiguous. Without it the output is `path:lineno:content`, which no
    # split can parse correctly: a colon is legal in a path AND ordinary in
    # content, so `split(":", 2)` loses the line number on a colon-bearing path
    # while `rsplit(":", 2)` corrupts every hit whose content holds a colon
    # (a dict literal, a URL, a type annotation). Both directions were tried;
    # the flag is the only correct fix, and the runner builds this command
    # itself so the flag is ours to add. Same idiom as `semgrep.py`'s
    # `git ls-files -z` parse. Phase 212 / Q-026.
    cmd = ["grep", "-rn", "--null", "-E", pattern]
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


def parse_hit(hit):
    """Split one grep hit into ``(path, lineno, content)``; ``None`` if unparsable.

    ``_run_grep_status`` passes ``--null``, so a hit is ``path\\0lineno:content``
    and the path column ends at a byte no path can contain. That is the whole
    reason this is reliable: the legacy ``path:lineno:content`` form is genuinely
    ambiguous, because a colon is legal in a path and ordinary in content.

    The colon fallback exists for hits that reach here without a NUL — an
    external caller passing its own lines, or a grep too old for ``--null``. It
    takes the FIRST ``:<digits>:`` boundary, which reproduces the pre-212
    ``split(":", 2)`` exactly: same answers, including the same known wrong one
    on a colon-bearing path. That is the point — it is a compatibility path, not
    a second attempt at the correct parse, and the correct parse is ``--null``.
    A hit with no NUL and no line number at all yields ``(hit, None, "")``; the
    emit branches drop those (see the note in ``run_check``).
    """
    if "\0" in hit:
        path, _, rest = hit.partition("\0")
        lineno, sep, content = rest.partition(":")
        if sep and lineno.isdigit():
            return path, lineno, content
        return path, None, rest
    m = _HIT_RE.match(hit)
    if m:
        return m.group("path"), m.group("line"), m.group("content")
    return hit, None, ""


def run_grep(pattern, paths, includes, excludes, repo_root, exclude_dirs=()):
    """Run grep -rn and return the match lines (back-compat wrapper).

    Retained as stable public API on the ``run_checks_impl`` re-export surface
    and for existing direct callers/tests. New accounting-aware code calls
    ``_run_grep_status`` for the ``(Outcome, lines)`` pair it needs to record
    the stage's terminal state.

    Phase 212: the underlying run now passes ``--null``, so the raw lines carry
    a NUL between path and line number. This wrapper restores the historical
    ``path:lineno:content`` spelling so its documented contract is unchanged for
    any caller outside this package. Internal callers use ``parse_hit`` on the
    NUL form instead, which is the only unambiguous parse.
    """
    return [
        h.replace("\0", ":", 1)
        for h in _run_grep_status(
            pattern, paths, includes, excludes, repo_root, exclude_dirs
        )[1]
    ]


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
            # The `position_check` dispatch builds its key from a file walk
            # rather than a grep hit, so it never went through `_emit` and had
            # no identity threaded. The matched line is right here — it is
            # already read one line above for the waiver test — so this is the
            # 18th line-level grep check and it keys like the other 17.
            findings.append(
                (check_id, file_line, message, identity_of(lines[l_line - 1]))
            )
    return findings


def run_check(check, repo_root, report=None):
    """Run a single check and return a list of (check_id, file_line, message, identity) tuples.

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

    def _emit(findings, file_line, waiver_text, identity_text=None):
        """Append a finding unless ``waiver_text`` carries a ``no-check:`` for it.

        ``waiver_text`` is the matched LINE for line-level checks and the whole
        FILE for file-level (`invert_file_check`) ones — a file-level finding
        cites no line, so there is nowhere else the marker could live. A waived
        finding is handed to the report, never dropped on the floor; with
        ``report=None`` (direct callers and tests — no shipped CLI path) the
        suppression still applies but the audit line has nowhere to go.

        ``identity_text`` is DELIBERATELY a separate parameter rather than a
        reuse of ``waiver_text``, even though for line-level checks they hold
        the same string. Reusing it is the obvious move and it is wrong: for
        `invert_file_check` the waiver text is the whole file, so the key would
        change on any edit anywhere in it — turning the one kind whose key is
        already stable into the churniest one. File-level callers pass nothing
        and stay on the two-field key.
        """
        message = f"[{check_id}] {severity} {file_line} — {description}"
        if check_id in waived_ids(waiver_text):
            if report is not None:
                report.record_waived(check_id, file_line, message)
            return
        findings.append(
            (check_id, file_line, message, identity_of(identity_text or ""))
        )

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

    # Phase 189 / internal tracker #239: these were one arm reporting `skipped:
    # not-configured`, which put two different things in the same words. A check with
    # no `pattern:` and no `position_check:` declares no executable form THIS RUNNER
    # can use — it will not run in any environment, so it is reported separately from
    # a tool that merely was not installed here. GDP's `doc-parity-violation` sat in
    # that state for weeks reading identically to an uninstalled tool, which is why
    # the state exists. A check that HAS a pattern but no resolvable paths is an
    # ordinary precondition-absent skip, which is what `skipped` is load-bearing for.
    #
    # Phase 212 (internal tracker #438): the state is right and the REMEDY was not. The old
    # message said "declare a kind", and there has never been a `kind:` field — stage
    # routing is by id prefix only (`cli.py`'s `_classify_checks`). It also assumed
    # every such entry is half-authored, but `doc-parity-violation` turned out to be
    # a deliberate catalogue stub for a check a live CI gate runs: routable, just not
    # by this runner. Both of the old remedies were wrong for it — declaring a kind
    # would duplicate the CI gate, removing it would drop the catalogue entry. So the
    # message now names the real mechanism and admits the third case, and says plainly
    # that recording it does not silence the line. Deliberately NOT a new schema field:
    # a one-line flag that renders a non-executing check clean is the exact
    # gate-goes-green-over-a-dead-check shape this taxonomy exists to prevent.
    if not pattern and not position_check:
        _record(UNROUTABLE, "no-executable-form",
                "no pattern: or position_check:, and the id carries no stage prefix "
                "(semgrep- / pyright- / tsc- / lint- / pip-audit- / coverage-), so no "
                "stage will run it. Give it a pattern: or a position_check:, rename it "
                "to a routing prefix, or remove it. If something outside this runner "
                "executes it (a CI step, a hook), record that in notes: — the check "
                "stays listed here every run, because this runner still did not run it")
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

    # A hit with no line number is not a hit. `_run_grep_status` always passes
    # `-n` AND `--null`, so every genuine match carries a NUL and a line number;
    # a line without one is grep talking ABOUT a file rather than quoting it —
    # in practice `Binary file <path> matches`, which grep prints for any file
    # holding a NUL byte (a corrupt or mislabelled `.sql`/`.py` is enough).
    #
    # Pre-212 the plain branch dropped these as a side effect of its
    # `len(parts) >= 2` guard, and Phase 212's first cut turned that accident
    # into an explicit emit — which produced a **new blocking finding** on a
    # `severity: critical` check, keyed by the literal string
    # `Binary file /abs/path matches`. That key is an ABSOLUTE path, so it does
    # not survive a move to another checkout and cannot be baselined portably:
    # a consumer could not even accept it to get green. Found by this phase's
    # own review round; restoring the drop is a return to shipped behaviour,
    # not a new policy.
    #
    # Whether a binary-classified file in a check's declared scope should be
    # SURFACED (as `degraded` — the scan demonstrably saw less than it claimed,
    # which is what that state is for) is a real question and a separate one.
    # Filed rather than decided here.
    findings = []

    if invert and neg_pattern:
        # File-level check: find files with pattern but WITHOUT neg_pattern
        files_with_pattern = set()
        for hit in hits:
            # Pre-212 this split BEFORE stripping, so a colon anywhere in
            # `repo_root` — a CI job directory is enough — truncated the path to
            # a fragment, the containment guard below then rejected every one of
            # them, and the whole branch silently produced zero findings while
            # the accounting reported `executed`. `parse_hit` returns the path
            # whole, so the strip and the guard both get what they expect.
            fpath, lineno, _content = parse_hit(hit)
            if lineno is None:
                continue  # `Binary file … matches` — see the note above
            fpath = strip_repo_prefix(fpath, repo_root)
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
                    # File-level: identity deliberately omitted — see _emit.
                    _emit(findings, rel, content)
            except (OSError, IOError):
                pass

    elif neg_pattern:
        # Per-line filter: keep hits that do NOT match negative_pattern
        for hit in hits:
            fpath, lineno, content_part = parse_hit(hit)
            if lineno is None:
                continue  # not a real hit — see the note above `findings = []`
            fpath = strip_repo_prefix(fpath, repo_root)
            # Pre-212, a colon-bearing path shifted the line number into the
            # content column, so `content_part` began `<n>:` — which defeats any
            # `^`-anchored negative_pattern and turns a correctly-filtered hit
            # into a false positive. The filter now sees the content alone.
            if not re.search(neg_pattern, content_part):
                _emit(findings, f"{fpath}:{lineno}", content_part,
                      content_part)

    else:
        # Simple pattern match — all hits are findings
        for hit in hits:
            fpath, lineno, content_part = parse_hit(hit)
            if lineno is None:
                continue  # not a real hit — see the note above `findings = []`
            fpath = strip_repo_prefix(fpath, repo_root)
            _emit(findings, f"{fpath}:{lineno}", content_part, content_part)

    return findings
