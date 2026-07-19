"""Baseline file I/O — load known-accepted findings and write fresh snapshots."""
import os


def load_baseline(path):
    """Load baseline keys as a set of "check_id|file_line" strings.

    Baseline file format (one per line):
        check_id|path:line
    Lines starting with # are comments. Blank lines ignored.
    """
    if not os.path.exists(path):
        return set()

    keys = set()
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            keys.add(line)
    return keys


def finding_key(check_id, file_line):
    return f"{check_id}|{file_line}"


def _is_coverage(check_id):
    """Coverage findings never participate in the baseline (Phase 61b).

    A coverage finding's key is ``coverage-…|path:line``, but the line number
    is *diff-relative* — it shifts every commit — so a baselined coverage gap
    would never re-match on the next PR. More to the point, "accepting" an
    uncovered crown-jewel line as standing tech debt is exactly what the
    Phase 61b hard gate exists to forbid: the gate consumes the coverage
    number directly as a block, **not through the baseline/audit loop**.

    So coverage is excluded from *both* ends of the baseline — it is never
    written (`write_baseline`) and never suppresses a finding
    (`is_baseline_suppressed`). A genuinely untestable line is excluded at the
    report-producer layer with a coverage pragma (`# pragma: no cover`,
    `/* istanbul ignore */`), which drops it from the report so it is not a
    violation — not via the baseline here.
    """
    return str(check_id).startswith("coverage-")


def is_baseline_suppressed(check_id, file_line, blocking_ids, baseline):
    """Return True when a finding is baseline-suppressed.

    A suppressed finding is printed with a ``[baseline]`` tag and does NOT
    count toward ``--fail-on-blocking``. Suppression requires the check to be
    blocking AND its key to be in the baseline — *except* coverage findings,
    which never suppress (see `_is_coverage`): a blocking coverage gap always
    fails the gate, baseline or no baseline.
    """
    if _is_coverage(check_id):
        return False
    return check_id in blocking_ids and finding_key(check_id, file_line) in baseline


def write_baseline(path, all_findings, blocking_ids):
    """Write baseline file containing all current blocking-check findings.

    Atomic rewrite via `<path>.tmp` + `os.replace` so a crash mid-write
    never leaves a truncated baseline that future runs would then load
    as authoritative.

    Coverage findings are never written (see `_is_coverage`) — a baseline
    entry for a diff-relative coverage line would be both un-matchable and a
    back-door around the Phase 61b crown-jewel gate.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(
            "# Pre-scan baseline — known findings accepted as tech debt.\n"
            "# Format: check_id|path:line  (one per line)\n"
            "# Regenerate: bash sysop/scripts/run_checks.sh --mode both --update-baseline\n"
            "# New findings NOT in this file will fail CI when the check is "
            "marked `blocking: true`.\n"
            "# (coverage-* findings are never baselined — see write_baseline.)\n"
            "\n"
        )
        for check_id, file_line, _msg in sorted(all_findings):
            if check_id in blocking_ids and not _is_coverage(check_id):
                f.write(f"{finding_key(check_id, file_line)}\n")
    os.replace(tmp_path, path)
