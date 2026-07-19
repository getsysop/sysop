"""Semgrep / AST diagnostics.

semgrep is invoked as a CLI. Findings are emitted in the same
``(check_id, file_line, message)`` shape as grep/LSP findings so baseline
matching, ``--update-baseline``, and ``--fail-on-blocking`` work uniformly.
"""
import json
import os
import subprocess
import sys

from .config import check_paths_by_id, finding_in_scope


def _run_semgrep(repo_root, included_ids):
    """Run semgrep against .claude/semgrep/, return findings as (check_id, file_line, msg) tuples.

    `included_ids` is the collection of semgrep-* check IDs that the caller
    has already filtered for the active mode — a dict of id → check dict from
    `_classify_checks` (legacy callers may still pass a plain id set). Any
    finding whose mapped check_id is not in `included_ids` is dropped, and —
    when the check declares `paths:` — so is any finding outside those roots
    (Phase 133: semgrep scans the whole tree in one subprocess, so per-check
    `paths:` scoping is applied by post-filtering; see
    config.path_in_scope).

    Returns early (empty list) when:
    - included_ids is empty (nothing to scan for this mode)
    - .claude/semgrep/ directory is absent (feature not installed)
    - semgrep binary is missing (graceful skip with stderr warning)
    - subprocess times out or returns non-JSON (partial results + warning)
    """
    if not included_ids:
        return []

    semgrep_dir = os.path.join(repo_root, ".claude", "semgrep")
    if not os.path.isdir(semgrep_dir):
        return []

    out = []
    # Exclude Sysop's bundled positive/negative semgrep fixtures from the
    # scan. They live at .claude/semgrep/fixtures/ as regression locks for
    # the rules themselves; the positive fixtures are deliberately violating
    # patterns and would otherwise surface as findings on every install.
    fixtures_exclude = os.path.join(".claude", "semgrep", "fixtures")
    try:
        r = subprocess.run(
            ["semgrep", "scan", "--config", semgrep_dir,
             "--exclude", fixtures_exclude,
             "--json", "--metrics=off", "--quiet", repo_root],
            capture_output=True, text=True, cwd=repo_root, timeout=300,
        )
    except FileNotFoundError:
        print("warn: semgrep not on PATH — skipping AST checks "
              "(install: brew install semgrep  or  pip install semgrep)",
              file=sys.stderr)
        return out
    except subprocess.TimeoutExpired:
        print("warn: semgrep exceeded 300s timeout — skipping AST checks "
              "(findings may be incomplete)", file=sys.stderr)
        return out

    if not r.stdout:
        return out
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        print("warn: semgrep produced non-JSON output — skipping",
              file=sys.stderr)
        return out

    _sev_map = {"ERROR": "HIGH", "WARNING": "MEDIUM", "INFO": "LOW"}
    paths_by_id = check_paths_by_id(included_ids)
    for result in data.get("results", []):
        # Rule IDs in semgrep JSON are fully-qualified; take the last segment.
        raw_id = result.get("check_id", "")
        rule_id = raw_id.split(".")[-1]
        check_id = f"semgrep-{rule_id}"
        if check_id not in paths_by_id:
            continue
        path = os.path.relpath(result.get("path", ""), repo_root)
        if not finding_in_scope(path, paths_by_id[check_id]):
            continue
        line = result.get("start", {}).get("line", 0)
        file_line = f"{path}:{line}"
        msg_text = result.get("extra", {}).get("message", "").replace("\n", " ")[:300]
        sev_raw = result.get("extra", {}).get("severity", "WARNING")
        sev = _sev_map.get(sev_raw, "MEDIUM")
        out.append((check_id, file_line,
                    f"[{check_id}] {sev} {file_line} — {msg_text}"))
    return out
