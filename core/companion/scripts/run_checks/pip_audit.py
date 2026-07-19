"""pip-audit diagnostics + the requirements-file discovery helper.

gdp hardcoded ``requirements.txt``; Sysop runs in repos whose
requirements layouts vary, so the discovery helper enumerates the
``requirements*.txt`` set at repo root.
"""
import glob
import json
import os
import re
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
    so transitive deps are caught — the stage runs regardless of which
    requirements layout the consumer uses. The findings are anchored at the
    first discoverable requirements*.txt file (via `_find_requirements_files()`)
    since that is the unit of remediation; falls back to "pyproject.toml:1"
    for pyproject/uv/poetry consumers, then "requirements.txt:1" as the
    layout-less stable key.

    --skip-editable: skip editable installs during dependency resolution.
        An editable install (`pip install -e .`, the documented Python-pack
        shape) always leaves one local package pip-audit can't resolve; the
        prior `--strict` treated that as fatal and aborted the whole audit
        *before emitting JSON*, so the stage silently reported zero findings on
        every editable consumer (BeanRider ISSUE-0046). `--strict --skip-editable`
        is also broken (a skip is still a skip, which --strict then fails on), so
        --strict had to go entirely.
    --format json: parseable output

    Binary resolution (Phase 133, leg-5 dogfood sibling finding): the
    ``pip-audit`` console script is only findable when its venv's bin/ is on
    PATH — a venv at a non-``.venv`` location (poetry, a plain ``venv/``)
    installs pip-audit invisibly to the bare subprocess lookup, and the stage
    warned "not on PATH" despite a real install. Fall back to
    ``sys.executable -m pip_audit``: whichever python is running this check
    (run_checks.sh prefers the project venv's python) resolves its own
    site-packages, no PATH required.

    Skips with a stderr warning if pip-audit is missing both ways, times out,
    or aborts without emitting findings (non-zero exit + empty stdout — a
    failed run, not a clean one).
    """
    if not included_ids:
        return []

    out = []
    args = ["--skip-editable", "--format", "json"]
    try:
        r = subprocess.run(
            ["pip-audit", *args],
            capture_output=True, text=True, cwd=repo_root, timeout=300,
        )
    except FileNotFoundError:
        # Console script not on PATH — try the module through the interpreter
        # running these checks. Only THIS attempt gets the friendly
        # "No module named pip_audit" treatment: a console-script pip-audit
        # that crashes internally (ModuleNotFoundError in its own dep tree,
        # the classic post-python-upgrade breakage) also prints "No module
        # named …", and misreading that as not-installed would bury the real
        # stderr the exited-N warn below surfaces.
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip_audit", *args],
                capture_output=True, text=True, cwd=repo_root, timeout=300,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            r = None
        if r is not None and r.returncode != 0 and not r.stdout and re.search(
            r"No module named '?pip_audit'?(\s|$)", r.stderr or ""
        ):
            r = None
        if r is None:
            print("warn: pip-audit not on PATH — skipping dependency audit "
                  "(install: pip install pip-audit — into the project venv is "
                  "enough; the venv's python resolves it via -m)", file=sys.stderr)
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
    if req_files:
        anchor = f"{req_files[0]}:1"
    elif os.path.isfile(os.path.join(repo_root, "pyproject.toml")):
        # pyproject/uv/poetry consumers (Phase 133, leg-5 dogfood finding 8):
        # anchor at the manifest that actually owns the dependency set, not a
        # requirements.txt that doesn't exist.
        anchor = "pyproject.toml:1"
    else:
        anchor = "requirements.txt:1"

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
