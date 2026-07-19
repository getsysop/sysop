"""pip-audit diagnostics + the requirements-file discovery helper.

gdp hardcoded ``requirements.txt``; Sysop runs in repos whose
requirements layouts vary, so the discovery helper enumerates the
``requirements*.txt`` set at repo root.
"""
import glob
import json
import os
import subprocess
import sys


def _find_requirements_files(repo_root):
    """Return sorted list of requirements*.txt files at repo root.

    Matches `requirements.txt`, `requirements-dev.txt`, `requirements-prod.txt`,
    etc. Returns relative paths. Does NOT match the `requirements/` directory
    or extension-suffixed forms like `requirements.txt.bak`.
    """
    pattern = os.path.join(repo_root, "requirements*.txt")
    matches = sorted(glob.glob(pattern))
    return [os.path.relpath(m, repo_root) for m in matches if os.path.isfile(m)]


def _run_pip_audit(repo_root, included_ids):
    """Run pip-audit against the active venv, return findings as tuples.

    Audits the currently-installed venv rather than parsing requirements.txt
    so transitive deps are caught. The findings are anchored at the first
    discoverable requirements*.txt file (via `_find_requirements_files()`)
    since that is the unit of remediation; falls back to "requirements.txt:1"
    when no requirements file is present (still useful as a stable key
    even if the consumer ships only a pyproject.toml).

    --skip-editable: skip editable installs during dependency resolution.
        An editable install (`pip install -e .`, the documented Python-pack
        shape) always leaves one local package pip-audit can't resolve; the
        prior `--strict` treated that as fatal and aborted the whole audit
        *before emitting JSON*, so the stage silently reported zero findings on
        every editable consumer (BeanRider ISSUE-0046). `--strict --skip-editable`
        is also broken (a skip is still a skip, which --strict then fails on), so
        --strict had to go entirely.
    --format json: parseable output

    Skips with a stderr warning if pip-audit is missing, times out, or aborts
    without emitting findings (non-zero exit + empty stdout — a failed run, not
    a clean one).
    """
    if not included_ids:
        return []

    out = []
    try:
        r = subprocess.run(
            ["pip-audit", "--skip-editable", "--format", "json"],
            capture_output=True, text=True, cwd=repo_root, timeout=300,
        )
    except FileNotFoundError:
        print("warn: pip-audit not on PATH — skipping dependency audit "
              "(install: pip install pip-audit)", file=sys.stderr)
        return out
    except subprocess.TimeoutExpired:
        print("warn: pip-audit exceeded 300s timeout — skipping dependency audit "
              "(findings may be incomplete)", file=sys.stderr)
        return out

    if not r.stdout:
        # A non-zero exit with no JSON means pip-audit aborted before it could
        # audit anything (a bad flag, or an unresolvable dependency under a
        # stricter mode) — NOT a clean run. Surface it instead of returning an
        # empty (== "all clear") finding list, so a broken invocation announces
        # itself rather than reporting a silent zero for months (ISSUE-0046).
        if r.returncode != 0:
            tail = (r.stderr or "").strip().splitlines()
            detail = tail[-1] if tail else "no stderr"
            print(f"warn: pip-audit exited {r.returncode} with no output — "
                  f"dependency audit did NOT run: {detail}", file=sys.stderr)
        return out
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        print("warn: pip-audit produced non-JSON output — skipping",
              file=sys.stderr)
        return out

    check_id = "pip-audit-vuln"
    if check_id not in included_ids:
        return out

    req_files = _find_requirements_files(repo_root)
    anchor = f"{req_files[0]}:1" if req_files else "requirements.txt:1"

    # pip-audit JSON: {dependencies: [{name, version, vulns: [{id,
    # fix_versions, description, aliases}]}]}. Anchor findings at the
    # discovered requirements file since pip-audit reports per-package not
    # per-line.
    for dep in data.get("dependencies", []):
        name = dep.get("name", "?")
        version = dep.get("version", "?")
        for vuln in dep.get("vulns", []) or []:
            vid = vuln.get("id", "?")
            aliases = vuln.get("aliases", []) or []
            fix_versions = vuln.get("fix_versions", []) or []
            desc = (vuln.get("description") or "").replace("\n", " ")[:200]
            alias_str = f" ({', '.join(aliases)})" if aliases else ""
            fix_str = (f" — fix: bump to {fix_versions[0]}"
                       if fix_versions else "")
            msg_text = f"{name}=={version} {vid}{alias_str}{fix_str} — {desc}"
            out.append((check_id, anchor,
                        f"[{check_id}] HIGH {anchor} — {msg_text}"))
    return out
