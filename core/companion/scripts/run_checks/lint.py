"""ESLint diagnostics + the frontend-dir discovery helper.

gdp hardcoded ``frontend/``; Sysop runs in repos whose layouts vary,
so the discovery helper locates the equivalent path from the scanned
tree. Ambiguous matches (two frontend dirs at sibling paths) raise
rather than silently picking — that pattern means consumer
misconfiguration the caller needs to resolve, not a default to absorb.
"""
import json
import os
import subprocess
import sys

from _log import _sanitize_log

from .config import _SKIP_DIRS


def _find_frontend_dir(repo_root):
    """Return the absolute path of the directory containing node_modules/eslint.

    Raises FrontendDirAmbiguous if multiple candidates exist. Returns None
    when no candidate is found. Resolves symlinks during walk to avoid
    infinite recursion on cyclic links.
    """
    matches = []
    seen_real = set()
    for dirpath, dirnames, _filenames in os.walk(repo_root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        candidate = os.path.join(dirpath, "node_modules", "eslint")
        if os.path.isdir(candidate):
            real = os.path.realpath(dirpath)
            if real in seen_real:
                continue
            seen_real.add(real)
            matches.append(dirpath)
    if not matches:
        return None
    if len(matches) > 1:
        raise FrontendDirAmbiguous(
            f"multiple node_modules/eslint candidates: {sorted(matches)} — "
            "set the frontend dir explicitly or remove the stray install"
        )
    return matches[0]


class FrontendDirAmbiguous(RuntimeError):
    """Raised when _find_frontend_dir finds >1 node_modules/eslint candidate."""


def _run_eslint(repo_root, included_ids):
    """Run ESLint against the frontend dir, return findings as (check_id, file_line, msg).

    The frontend dir is discovered via `_find_frontend_dir()` — the first
    directory under repo_root that contains `node_modules/eslint`. Ambiguous
    matches raise (caller's job to resolve).

    ESLint exits 1 when findings exist — we read r.stdout regardless of
    returncode (same as pyright/tsc/semgrep). Do NOT call
    r.check_returncode() — it would hide all real findings as an error.

    Skips with a stderr warning if:
    - the eslint binary is missing (subprocess raises FileNotFoundError)
    - no node_modules/eslint found anywhere under repo_root
    - node_modules/eslint-config-next is missing alongside (when present
      in the discovered frontend dir, the project's eslint config likely
      depends on it; absence would crash eslint at startup)
    """
    if not included_ids:
        return []

    try:
        frontend_dir = _find_frontend_dir(repo_root)
    except FrontendDirAmbiguous as e:
        print(f"warn: {_sanitize_log(e)} — skipping ESLint", file=sys.stderr)
        return []

    if frontend_dir is None:
        return []

    eslint_config_next = os.path.join(
        frontend_dir, "node_modules", "eslint-config-next", "package.json"
    )
    if not os.path.isfile(eslint_config_next):
        print(
            "warn: node_modules/eslint-config-next missing — skipping ESLint "
            f"(install: cd {os.path.relpath(frontend_dir, repo_root)} && npm ci)",
            file=sys.stderr,
        )
        return []

    out = []
    try:
        r = subprocess.run(
            ["eslint", "--format", "json", "."],
            capture_output=True, text=True, cwd=frontend_dir, timeout=300,
        )
    except FileNotFoundError:
        print(
            "warn: eslint not on PATH — skipping ESLint "
            f"(install: cd {os.path.relpath(frontend_dir, repo_root)} && npm ci)",
            file=sys.stderr,
        )
        return out
    except subprocess.TimeoutExpired:
        print("warn: eslint exceeded 300s timeout — skipping ESLint "
              "(findings may be incomplete)", file=sys.stderr)
        return out

    if not r.stdout:
        return out
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        print("warn: eslint produced non-JSON output — skipping",
              file=sys.stderr)
        return out

    # Single catch-all check_id keeps the registry minimal; the original
    # ESLint rule_id is embedded in msg_text so reviewers can group/triage
    # by rule without enumerating dozens of IDs. Filter once, not per-msg.
    check_id = "lint-error"
    if check_id not in included_ids:
        return out

    _sev_map = {2: "HIGH", 1: "MEDIUM"}
    for file_entry in data:
        file_path_abs = file_entry.get("filePath", "")
        if not file_path_abs:
            continue
        file_rel = os.path.relpath(file_path_abs, repo_root)
        for msg in file_entry.get("messages", []):
            rule_id = msg.get("ruleId") or "syntax-error"
            line = msg.get("line", 0) or 0
            file_line = f"{file_rel}:{line}"
            severity_num = msg.get("severity", 1)
            sev = _sev_map.get(severity_num, "LOW")
            msg_body = (msg.get("message") or "").replace("\n", " ")[:300]
            msg_text = f"[{rule_id}] {msg_body}"
            out.append((check_id, file_line,
                        f"[{check_id}] {sev} {file_line} — {msg_text}"))
    return out
