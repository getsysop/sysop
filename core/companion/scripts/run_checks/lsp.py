"""LSP / typechecker diagnostics (pyright + tsc).

Tool-shelling stage — pyright and tsc are invoked as CLIs. Findings are
emitted in the same ``(check_id, file_line, message)`` shape as grep
findings so baseline matching, ``--update-baseline``, and
``--fail-on-blocking`` work uniformly.
"""
import json
import os
import re
import subprocess
import sys

from .accounting import EXECUTED, FAILED, SKIPPED, stderr_excerpt
from .config import check_paths_by_id, finding_in_scope


def run_lsp_diagnostics(repo_root, included_ids, report=None):
    """Run pyright and tsc, return findings in the same shape as run_check.

    `included_ids` is the collection of pyright-*/tsc-* check IDs that the
    caller has already filtered for the active mode — a dict of id → check
    dict from `_classify_checks` (legacy callers may still pass a plain id
    set). Any finding whose mapped check_id is not in `included_ids` is
    dropped, and — when the check declares `paths:` — so is any finding
    outside those roots (Phase 133: pyright/tsc scan whole projects in one
    subprocess, so per-check `paths:` scoping is applied by post-filtering;
    see config.path_in_scope).

    Returns (check_id, file_line, message) tuples. ``report`` is the optional
    accounting collector — pyright and tsc each record their own id subset
    (one subprocess serves all the ids of its tool). Emits a stderr warning
    and returns partial results when a binary is missing or times out.
    """
    out = []
    if any(cid.startswith("pyright-") for cid in included_ids):
        out.extend(_run_pyright(repo_root, included_ids, report))
    if "tsc-type-error" in included_ids:
        out.extend(_run_tsc(repo_root, included_ids, report))
    return out


def _run_pyright(repo_root, included_ids, report=None):
    out = []
    pyright_ids = [cid for cid in included_ids if str(cid).startswith("pyright-")]

    def _record(status, reason=None, detail=None):
        if report is not None and pyright_ids:
            report.record(pyright_ids, status, "pyright", reason, detail)

    try:
        r = subprocess.run(
            ["pyright", "--outputjson", "--project", repo_root],
            capture_output=True, text=True, cwd=repo_root, timeout=300,
        )
    except FileNotFoundError:
        print("warn: pyright not on PATH — skipping Python typecheck "
              "(install: pip install -e \".[dev]\")",
              file=sys.stderr)
        _record(SKIPPED, "tool-missing", "pyright not on PATH")
        return out
    except subprocess.TimeoutExpired:
        print("warn: pyright exceeded 300s timeout — skipping Python typecheck "
              "(findings may be incomplete)", file=sys.stderr)
        _record(FAILED, "timeout", "pyright timed out after 300s")
        return out

    if not r.stdout:
        # Started then died before emitting JSON — a `failed` run when the exit
        # code is nonzero, not the clean zero the old silent return implied.
        if r.returncode != 0:
            print(f"warn: pyright exited {r.returncode} with no output — "
                  f"Python typecheck did NOT run: {stderr_excerpt(r.stderr)}",
                  file=sys.stderr)
            _record(FAILED, "nonzero-no-output",
                    f"exit {r.returncode}: {stderr_excerpt(r.stderr)}")
        else:
            _record(EXECUTED)
        return out
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        print("warn: pyright produced non-JSON output — skipping",
              file=sys.stderr)
        _record(FAILED, "non-json", "pyright produced non-JSON output")
        return out

    _record(EXECUTED)
    paths_by_id = check_paths_by_id(included_ids)
    for diag in data.get("generalDiagnostics", []):
        severity = diag.get("severity", "information")
        rule = diag.get("rule", "")
        check_id = _pyright_rule_to_check_id(rule, severity)
        if not check_id or check_id not in paths_by_id:
            continue
        file_path = os.path.relpath(diag.get("file", ""), repo_root)
        if not finding_in_scope(file_path, paths_by_id[check_id]):
            continue
        line = diag.get("range", {}).get("start", {}).get("line", 0) + 1
        file_line = f"{file_path}:{line}"
        msg_text = diag.get("message", "").replace("\n", " ")[:300]
        sev = {"error": "HIGH", "warning": "MEDIUM"}.get(severity, "LOW")
        out.append((check_id, file_line,
                    f"[{check_id}] {sev} {file_line} — {msg_text}"))
    return out


_TSC_HEADER_RE = re.compile(
    r"^(.+?)\((\d+),(\d+)\):\s+(error|warning)\s+TS(\d+):\s+(.+)$"
)


def _run_tsc(repo_root, included_ids, report=None):
    out = []

    def _record(status, reason=None, detail=None):
        if report is not None and "tsc-type-error" in included_ids:
            report.record(["tsc-type-error"], status, "tsc", reason, detail)

    frontend_dir = os.path.join(repo_root, "frontend")
    if not os.path.exists(os.path.join(frontend_dir, "tsconfig.json")):
        _record(SKIPPED, "input-missing", "no frontend/tsconfig.json")
        return out
    # tsc resolves @types/* relative to the tsconfig's adjacent node_modules;
    # worktrees typically lack a frontend/node_modules install, which would
    # produce spurious "Cannot find module" errors. Skip gracefully so the
    # pre-scan stays useful instead of emitting noise.
    if not os.path.isdir(os.path.join(frontend_dir, "node_modules", "typescript")):
        print("warn: frontend/node_modules/typescript missing — skipping tsc "
              "(install: cd frontend && npm ci)", file=sys.stderr)
        _record(SKIPPED, "input-missing",
                "frontend/node_modules/typescript absent")
        return out
    try:
        r = subprocess.run(
            ["tsc", "--noEmit", "-p", "tsconfig.json", "--pretty", "false"],
            capture_output=True, text=True, cwd=frontend_dir, timeout=600,
        )
    except FileNotFoundError:
        print("warn: tsc not available — skipping TypeScript typecheck "
              "(install: (cd frontend && npm ci))", file=sys.stderr)
        _record(SKIPPED, "tool-missing", "tsc not on PATH")
        return out
    except subprocess.TimeoutExpired:
        print("warn: tsc exceeded 600s timeout — skipping TypeScript typecheck "
              "(findings may be incomplete)", file=sys.stderr)
        _record(FAILED, "timeout", "tsc timed out after 600s")
        return out

    # A crash before emitting diagnostics (nonzero exit, empty stdout — tsc
    # writes diagnostics to stdout, so a broken tsconfig/toolchain leaves it
    # empty on stderr) is `failed`, not the clean zero it used to read as.
    if not r.stdout and r.returncode != 0:
        print(f"warn: tsc exited {r.returncode} with no output — TypeScript "
              f"typecheck did NOT run: {stderr_excerpt(r.stderr)}", file=sys.stderr)
        _record(FAILED, "nonzero-no-output",
                f"exit {r.returncode}: {stderr_excerpt(r.stderr)}")
        return out
    _record(EXECUTED)

    # tsc --pretty false emits each error as a header line
    #   path(line,col): error TS####: <msg>
    # optionally followed by indented continuation lines (e.g., TS2322
    # "Types of property 'x' are incompatible…"). Collapse header +
    # continuations into a single finding so reviewers see the full
    # diagnostic — a single-line regex would drop these.
    current = None  # (header_match, [continuation_lines])
    for raw in r.stdout.splitlines():
        m = _TSC_HEADER_RE.match(raw)
        if m:
            _emit_tsc_finding(current, frontend_dir, repo_root, included_ids, out)
            current = (m, [])
        elif current is not None:
            current[1].append(raw.rstrip())
    _emit_tsc_finding(current, frontend_dir, repo_root, included_ids, out)
    return out


def _emit_tsc_finding(current, frontend_dir, repo_root, included_ids, out):
    if current is None:
        return
    m, continuations = current
    check_id = "tsc-type-error"
    paths_by_id = check_paths_by_id(included_ids)
    if check_id not in paths_by_id:
        return
    file_rel = os.path.relpath(
        os.path.join(frontend_dir, m.group(1)), repo_root
    )
    if not finding_in_scope(file_rel, paths_by_id[check_id]):
        return
    file_line = f"{file_rel}:{m.group(2)}"
    head = m.group(6)
    tail = " ".join(c.strip() for c in continuations if c.strip())
    msg_text = (f"{head} — {tail}" if tail else head)[:400]
    sev = "HIGH" if m.group(4) == "error" else "MEDIUM"
    out.append((check_id, file_line,
                f"[{check_id}] {sev} {file_line} — {msg_text}"))


def _pyright_rule_to_check_id(rule, severity):
    mapping = {
        "reportMissingImports": "pyright-missing-imports",
        "reportMissingModuleSource": "pyright-missing-imports",
        "reportUndefinedVariable": "pyright-undefined-variable",
        "reportUnusedImport": "pyright-unused-import",
        "reportUnusedVariable": "pyright-unused-variable",
    }
    if rule in mapping:
        return mapping[rule]
    if severity == "warning":
        return "pyright-general-warning"
    return None  # Skip unmapped info-severity messages
