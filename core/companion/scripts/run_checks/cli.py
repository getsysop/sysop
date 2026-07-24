"""
Run deterministic grep checks from .claude/checks.yml.

Parses the YAML registry via PyYAML's safe_load and runs grep for each check.
Used by /codebase-review and /security-audit for pre-scan.
See WORKFLOW.md §6.5 for format documentation.

Usage (via wrapper):
    bash sysop/scripts/run_checks.sh [--mode quality|security|both]
                               [--fail-on-blocking]
                               [--update-baseline]

Direct usage:
    python -m run_checks [--mode quality|security|both] [--repo-root /path]
                         [--fail-on-blocking] [--update-baseline]
                         [--baseline-file .claude/checks_baseline.txt]

CI contract:
    --fail-on-blocking exits non-zero when any finding from a check marked
    `blocking: true` is NOT in the baseline file. Baseline-matched findings
    are printed with a [baseline] tag so they stay visible without failing CI.
    Use --update-baseline to regenerate the baseline after deliberately
    accepting new tech debt (review required).
"""
import argparse
import os
import subprocess
import sys
import time

from _log import _sanitize_log

from .accounting import FAILED, RunReport, stderr_excerpt
from .baseline import (
    _is_coverage,
    is_baseline_suppressed,
    load_baseline,
    write_baseline,
)
from .config import parse_checks_yml
from .coverage import _run_coverage
from .grep import run_check
from .lint import _run_eslint
from .lsp import run_lsp_diagnostics
from .pip_audit import _run_pip_audit
from .semgrep import _run_semgrep


def _classify_checks(checks, active_token=None):
    """Bucket a check list into per-stage sets/lists plus the blocking ids.

    A single classification path shared by the ``--mode``-filtered run and the
    ``--update-baseline`` path (which runs against every check). Centralising
    the check-id prefix dispatch is defensive: a new stage prefix (say
    ``bandit-``) is added in one place — duplicated classification is exactly
    where a new prefix silently regresses.

    Args:
        checks: list of check dicts as parsed from ``checks.yml``.
        active_token: optional ``used_by`` token to require (e.g.
            ``"codebase-review"``). When ``None``, every check is accepted
            regardless of its ``used_by`` field — used by ``--update-baseline``
            so the baseline covers every blocking check across both modes.

    Returns a 7-tuple:
        (grep_checks, lsp_ids, semgrep_ids, lint_ids, pip_audit_ids,
         coverage_checks, blocking_ids)
      - grep_checks / coverage_checks: full check dicts (``run_check`` and
        ``_run_coverage`` need fields beyond the id — coverage needs
        ``critical_path`` / ``report``).
      - lsp_ids / semgrep_ids: dicts of check id → full check dict (Phase 133:
        the tool-shelling stages post-filter findings through each check's
        ``paths:``, so they need the spec, not just the id — membership tests
        on the dict behave exactly like the old sets).
      - lint_ids / pip_audit_ids: sets of check ids, keyed off the id prefix
        the corresponding stage dispatches on.
      - blocking_ids: every ``blocking: true`` check id across all buckets that
        passed the ``active_token`` filter.
    """
    grep_checks = []
    lsp_ids = {}
    semgrep_ids = {}
    lint_ids = set()
    pip_audit_ids = set()
    coverage_checks = []
    blocking_ids = set()
    for c in checks:
        cid = c.get("id", "")
        used = c.get("used_by", []) or []
        if active_token is not None and active_token not in used:
            continue
        if cid.startswith("pyright-") or cid.startswith("tsc-"):
            lsp_ids[cid] = c
        elif cid.startswith("semgrep-"):
            semgrep_ids[cid] = c
        elif cid.startswith("lint-"):
            lint_ids.add(cid)
        elif cid.startswith("pip-audit-"):
            pip_audit_ids.add(cid)
        elif cid.startswith("coverage-"):
            coverage_checks.append(c)
        else:
            grep_checks.append(c)
        if c.get("blocking") is True:
            blocking_ids.add(cid)
    return (grep_checks, lsp_ids, semgrep_ids, lint_ids,
            pip_audit_ids, coverage_checks, blocking_ids)


def _pending_rounds_note(repo_root, stale_seconds=2 * 3600):
    """Return a one-line note about review rounds that never completed, or None.

    A review round writes a nonce-keyed marker under
    ``sysop/runtime/pending-rounds/`` and clears it once ``review_tasks.md`` is
    written. A marker that outlives its round is evidence the round died
    mid-flight — a refusal after starting, a crash, quota exhaustion, context
    death — none of which currently produce an error or an empty result set to
    notice.

    Markers are anchored to the MAIN checkout (``--git-common-dir``), so a
    pre-scan run from inside a worktree still sees them. Fresh markers are
    ignored: a concurrent session mid-round is normal, and alarming on it would
    train consumers to tune the signal out.

    Never raises. A probe that breaks the pre-scan would be a worse defect than
    the silence it reports on.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=10, cwd=repo_root,
        )
        common = result.stdout.strip()
        if result.returncode == 0 and common:
            # An absolute common-dir (the worktree case) wins the join; a bare
            # ".git" (main checkout) resolves against repo_root.
            root = os.path.dirname(
                os.path.abspath(os.path.join(repo_root, common))
            )
        else:
            root = repo_root
        marker_dir = os.path.join(root, "sysop", "runtime", "pending-rounds")
        if not os.path.isdir(marker_dir):
            return None
        now = time.time()
        stale = []
        for name in sorted(os.listdir(marker_dir)):
            if not name.endswith(".pending"):
                continue
            try:
                age = now - os.stat(os.path.join(marker_dir, name)).st_mtime
            except OSError:
                continue
            if age >= stale_seconds:
                stale.append(name)
        if not stale:
            return None
        shown = ", ".join(stale[:3])
        more = f" (+{len(stale) - 3} more)" if len(stale) > 3 else ""
        return (
            f"    ⚠ {len(stale)} review round(s) started and never completed: "
            f"{shown}{more}\n"
            "      their findings are absent or partial — re-run the skill; "
            "markers live in sysop/runtime/pending-rounds/"
        )
    except (OSError, subprocess.SubprocessError):
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Run grep checks from .claude/checks.yml"
    )
    parser.add_argument(
        "--mode",
        choices=["quality", "security", "both"],
        default="both",
        help="Which checks to run (default: both)",
    )
    parser.add_argument(
        "--repo-root", default=None, help="Repository root (auto-detected if omitted)"
    )
    parser.add_argument(
        "--fail-on-blocking",
        action="store_true",
        help="Exit 1 when any non-baseline finding from a `blocking: true` check fires.",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Write current blocking-check findings to the baseline file and exit 0.",
    )
    parser.add_argument(
        "--baseline-file",
        default=None,
        help="Baseline file path (default: .claude/checks_baseline.txt)",
    )
    args = parser.parse_args()

    # Determine repo root
    repo_root = args.repo_root
    if not repo_root:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            repo_root = result.stdout.strip()
            # Fall back to cwd when not in a git repo (returncode != 0) or
            # when stdout is empty — otherwise downstream os.path.join("", ...)
            # silently produces a relative path that breaks file lookups.
            if result.returncode != 0 or not repo_root:
                repo_root = os.getcwd()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            repo_root = os.getcwd()

    checks_file = os.path.join(repo_root, ".claude", "checks.yml")
    if not os.path.exists(checks_file):
        print(f"Error: {checks_file} not found", file=sys.stderr)
        sys.exit(1)

    baseline_file = args.baseline_file or os.path.join(
        repo_root, ".claude", "checks_baseline.txt"
    )

    all_checks = parse_checks_yml(checks_file)

    # --update-baseline short-circuits BEFORE the mode-filtered pass and runs
    # ONLY the all-checks pass (spec §2). The old code ran the mode-filtered
    # pass, discarded its findings, then re-ran every stage a second time over
    # all checks — double execution and a double-record ambiguity for the
    # accounting layer. One pass, one RunReport.
    if args.update_baseline:
        _run_update_baseline(repo_root, all_checks, baseline_file)
        return

    # Map --mode to the used_by token, then classify every check by stage in
    # one pass (see _classify_checks). The mode values don't match used_by
    # values directly, so the mapping is the single translation point.
    _mode_token_map = {"quality": "codebase-review",
                       "security": "security-audit",
                       "both": None}
    active_token = _mode_token_map.get(args.mode)
    classified = _classify_checks(all_checks, active_token=active_token)
    blocking_ids = classified[6]  # stages run via _run_all_stages(classified)

    # The selected set is every check that passed the mode filter — the same
    # filter _classify_checks applies, re-derived here as the full dict list so
    # the accounting report can see each check's `blocking` flag and scope
    # (needed for the localized-vs-placeholder ⚠ decision).
    selected_checks = [
        c for c in all_checks
        if active_token is None or active_token in (c.get("used_by") or [])
    ]
    total_checks = len(selected_checks)
    if total_checks == 0:
        print(f"No checks found for mode: {args.mode}")
        sys.exit(0)

    report = RunReport(selected_checks)
    all_findings = _run_all_stages(repo_root, classified, report)

    baseline = load_baseline(baseline_file)

    # Emit findings, tagging baseline-matched ones inline so they stay visible.
    # Coverage findings never baseline-suppress (Phase 61b crown-jewel gate) —
    # is_baseline_suppressed() encodes that carve-out so a stale or hand-edited
    # baseline entry can't smuggle an uncovered critical-path line past the gate.
    baseline_hits = 0
    new_blocking_hits = 0
    new_coverage_hits = 0  # blocking coverage findings (can't be baselined)
    for check_id, file_line, msg in all_findings:
        if is_baseline_suppressed(check_id, file_line, blocking_ids, baseline):
            print(f"[baseline] {msg}")
            baseline_hits += 1
        else:
            print(msg)
            if check_id in blocking_ids:
                new_blocking_hits += 1
                if _is_coverage(check_id):
                    new_coverage_hits += 1

    # Accounting summary block to stderr — keeps stdout clean for grep/wc
    # piping. Reports checks *executed* vs *skipped* vs *failed*, not just
    # selected, so a stage that skipped its precondition or crashed is visible
    # instead of hiding behind a bare "N findings from M checks".
    summary = report.render(all_findings, mode=args.mode,
                            baseline_matched=baseline_hits,
                            new_blocking=new_blocking_hits)
    # One layer up from check accounting: a review ROUND that started and never
    # finished. The pre-scan is the one surface a loop-mode consumer re-reads
    # every round (self_check.sh is a one-shot probe nothing re-runs during
    # operation), so the never-completed signal is appended here to give it
    # real reach. Not added to --update-baseline: that path is a maintenance
    # snapshot, not a review round.
    note = _pending_rounds_note(repo_root)
    if note:
        summary += "\n" + note
    print("\n" + summary, file=sys.stderr)

    # Gate: a new non-baselined blocking finding OR a blocking check whose
    # stage crashed (`failed`). A blocking tool that dies produces zero
    # findings and would otherwise pass silently — the accounting layer closes
    # that corner (spec §4). A *skipped* blocking check is loud (⚠ in the
    # summary) but non-fatal — gate-on-skipped would redden every armed CI
    # consumer whose coverage report is produced after the gate step.
    blocking_failures = report.blocking_failures()
    if args.fail_on_blocking and (new_blocking_hits > 0 or blocking_failures):
        if new_blocking_hits > 0:
            print(
                f"\nerror: {new_blocking_hits} new blocking finding(s) — failing CI.\n"
                "   If a finding is known tech debt, regenerate the baseline with:\n"
                "     bash sysop/scripts/run_checks.sh --mode both --update-baseline\n"
                "   (Review the diff before committing — baseline entries bypass CI.)",
                file=sys.stderr,
            )
            if new_coverage_hits > 0:
                # Coverage findings are NOT baselineable (Phase 61b crown-jewel
                # gate) — steer the consumer away from the dead-end
                # --update-baseline path the generic message above suggests.
                print(
                    f"\n   {new_coverage_hits} of these are crown-jewel coverage gaps "
                    "— these are NOT baselineable.\n"
                    "   Cover the changed line with a test, or (if genuinely "
                    "untestable) exclude it\n"
                    "   with a coverage pragma (# pragma: no cover / "
                    "/* istanbul ignore */).",
                    file=sys.stderr,
                )
        if blocking_failures:
            names = "; ".join(
                f"{cid} ({stage}: {reason})"
                for cid, stage, reason, _ in blocking_failures
            )
            print(
                f"\nerror: {len(blocking_failures)} blocking check(s) FAILED to run "
                "— failing CI.\n"
                f"   {names}\n"
                "   A blocking check that crashed produces zero findings; a green\n"
                "   gate would be a lie. Fix the tool/environment, then re-run.",
                file=sys.stderr,
            )
        sys.exit(1)


def _run_all_stages(repo_root, classified, report):
    """Run every pre-scan stage over a classified check set, recording outcomes.

    ``classified`` is the 7-tuple from ``_classify_checks``; ``report`` is the
    ``RunReport`` each stage records into. Shared by the normal run and the
    ``--update-baseline`` pass so the two can never drift in which stages they
    invoke or how findings are collected. Returns the concatenated findings.
    """
    (grep_checks, lsp_included, semgrep_included, lint_included,
     pip_audit_included, coverage_checks, _blocking_ids) = classified

    all_findings = []
    # Each run_check is wrapped so one bad check (an invalid regex in a
    # position_check, an unexpected grep return) cannot kill the whole run —
    # and the escape is recorded `failed` so it is not an unaccounted hole.
    for check in grep_checks:
        try:
            all_findings.extend(run_check(check, repo_root, report))
        except Exception as e:
            # _sanitize_log strips ANSI/control chars — a subprocess or regex
            # exception may carry escape sequences that corrupt the terminal.
            print(
                f"warn: check {check.get('id')} failed: {_sanitize_log(e)}",
                file=sys.stderr,
            )
            if check.get("id"):
                report.record([check.get("id")], FAILED, "grep",
                              "exception", stderr_excerpt(str(e)))

    # LSP / typechecker diagnostics.
    if lsp_included:
        all_findings.extend(run_lsp_diagnostics(repo_root, lsp_included, report))

    # Semgrep / AST diagnostics.
    all_findings.extend(_run_semgrep(repo_root, semgrep_included, report))

    # ESLint diagnostics. lint-* findings are emitted by _run_eslint under a
    # single catch-all check_id ("lint-error") with the original ESLint
    # rule_id embedded in the message text.
    all_findings.extend(_run_eslint(repo_root, lint_included, report))

    # pip-audit diagnostics.
    all_findings.extend(_run_pip_audit(repo_root, pip_audit_included, report))

    # Coverage diff gate (Phase 61a measurement + Phase 61b hard gate).
    # Scoped to each check's `critical_path` globs; routed through diff-cover
    # for both the Python and frontend reports. A `blocking: true` coverage
    # check is the crown-jewel gate — its findings count toward
    # --fail-on-blocking and (unlike every other stage) never baseline-suppress
    # (see is_baseline_suppressed). A consumer who wants measurement only keeps
    # `blocking: false`. Unlike the id-set stages, the coverage stage needs
    # each check's `critical_path` / `report` fields, so _classify_checks
    # hands it the full check dicts.
    all_findings.extend(_run_coverage(repo_root, coverage_checks, report))
    return all_findings


def _run_update_baseline(repo_root, all_checks, baseline_file):
    """Single-pass ``--update-baseline`` (spec §2).

    Runs every stage ONCE over all checks (active_token=None so the baseline
    covers both modes' blocking checks), then writes the baseline — unless a
    blocking check FAILED, in which case it refuses and writes nothing: a
    crashed tool is not a state to snapshot (spec §4).
    """
    classified = _classify_checks(all_checks, active_token=None)
    blocking_ids = classified[6]
    report = RunReport(all_checks)  # selected == every check
    all_findings = _run_all_stages(repo_root, classified, report)

    # Show what actually ran before deciding whether to persist it.
    print("\n" + report.render(all_findings, mode="both"), file=sys.stderr)

    blocking_failures = report.blocking_failures()
    if blocking_failures:
        names = "; ".join(
            f"{cid} ({stage}: {reason})"
            for cid, stage, reason, _ in blocking_failures
        )
        print(
            f"\nerror: refusing to write baseline — {len(blocking_failures)} "
            f"blocking check(s) FAILED to run: {names}\n"
            "   A crashed tool is not a state to snapshot. Fix the failure, "
            "then re-run --update-baseline.",
            file=sys.stderr,
        )
        sys.exit(1)

    write_baseline(baseline_file, all_findings, blocking_ids)
    baseline_rel = baseline_file.replace(repo_root.rstrip("/") + "/", "")
    # Count only what write_baseline actually persisted — coverage findings
    # are never baselined (Phase 61b), so exclude them to keep the printed
    # tally honest.
    blocking_count = sum(
        1 for cid, _, _ in all_findings
        if cid in blocking_ids and not _is_coverage(cid)
    )
    print(
        f"Wrote {blocking_count} baseline finding(s) to {baseline_rel}",
        file=sys.stderr,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
