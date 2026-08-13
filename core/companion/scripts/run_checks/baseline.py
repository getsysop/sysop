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
    count toward ``--fail-on-blocking``. Suppression requires only that the
    key be in the baseline — *except* coverage findings, which never suppress
    (see `_is_coverage`): a blocking coverage gap always fails the gate,
    baseline or no baseline.

    ``blocking_ids`` is accepted and deliberately unused (internal tracker #363).
    Suppression used to require ``check_id in blocking_ids`` as well, which
    made a baseline entry for a ``blocking: false`` check unable to suppress
    anything *and* unable to be written — inert state that reads as live
    state, so a triager who recorded ~300 advisory verdicts as accepted
    findings recorded them nowhere. What the gate keys off is unchanged:
    ``--fail-on-blocking`` reads ``blocking_ids`` itself (`cli.py`), so
    suppressing an advisory finding changes what is *printed* and nothing
    about the exit code. The parameter stays in the signature because the
    caller has it and a future rule may key on it; dropping it would be a
    breaking change to the re-exported API for no gain.
    """
    if _is_coverage(check_id):
        return False
    return finding_key(check_id, file_line) in baseline


def write_baseline(path, all_findings, blocking_ids):
    """Write baseline file containing all current findings. Returns the count.

    Atomic rewrite via `<path>.tmp` + `os.replace` so a crash mid-write
    never leaves a truncated baseline that future runs would then load
    as authoritative.

    Coverage findings are never written (see `_is_coverage`) — a baseline
    entry for a diff-relative coverage line would be both un-matchable and a
    back-door around the Phase 61b crown-jewel gate. That carve-out is the
    *only* one: an advisory (`blocking: false`) check's findings are written
    like any other (internal tracker #363 — see `is_baseline_suppressed`).

    ``blocking_ids`` is accepted and deliberately unused, for the reason given
    there. **The return value exists so no caller has to restate the filter:**
    the printed tally used to re-implement this predicate by hand at the call
    site, which is one copy too many of a condition this change had to edit.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    # Deduplicated, because the key is what `load_baseline` returns and it returns a
    # SET: two findings sharing a `check_id|path:line` are one suppression however
    # many lines get written. The catch-all ids make that ordinary rather than
    # exotic — `lint-*` carries the real rule in the message, not the id, so several
    # ESLint rules on one line share a key. Writing it once keeps the file honest
    # and makes the returned tally mean "suppressions recorded" rather than
    # "findings seen", which is what the caller prints it as.
    seen = set()
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(
            "# Pre-scan baseline — known findings accepted as tech debt or "
            "triaged as non-issues.\n"
            "# Format: check_id|path:line  (one per line)\n"
            "# Regenerate: bash sysop/scripts/run_checks.sh --mode both --update-baseline\n"
            "# A `blocking: true` check's new findings — ones NOT in this file "
            "— fail CI.\n"
            "# A `blocking: false` check's entries record a triage verdict: "
            "they tag the\n"
            "# finding `[baseline]` instead of hiding it, and gate nothing "
            "either way.\n"
            "# (coverage-* findings are never baselined — see write_baseline.)\n"
            "\n"
        )
        for check_id, file_line, _msg in sorted(all_findings):
            if _is_coverage(check_id):
                continue
            key = finding_key(check_id, file_line)
            if key in seen:
                continue
            seen.add(key)
            f.write(f"{key}\n")
    os.replace(tmp_path, path)
    return len(seen)
