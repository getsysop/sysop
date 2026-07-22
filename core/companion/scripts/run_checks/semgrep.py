"""Semgrep / AST diagnostics.

semgrep is invoked as a CLI. Findings are emitted in the same
``(check_id, file_line, message)`` shape as grep/LSP findings so baseline
matching, ``--update-baseline``, and ``--fail-on-blocking`` work uniformly.
"""
import json
import os
import subprocess
import sys

from .accounting import EXECUTED, FAILED, SKIPPED, stderr_excerpt
from .config import check_paths_by_id, finding_in_scope

# semgrep's OCaml core (via mirage `ca-certs`, which reads SSL_CERT_FILE since
# 0.2.3) builds an OpenTelemetry TLS authenticator at startup; where no system
# trust store is discoverable it crashes before any scan runs — exit 2,
# "ca-certs: empty trust anchors" — the cross-harness defect. Deliverable 03
# (codex-sysop-integration/deliverables/03-otel-semgrep-verification.md) proved
# every telemetry-disable flag, OTEL_SDK_DISABLED included, fails to prevent
# that construction, while pointing SSL_CERT_FILE at a real CA bundle fixes both
# `--version` and full scans at 1.157.0 and 1.170.0 without weakening TLS. We
# only ever *supply* a bundle that already exists on disk; we never disable
# certificate verification. These are bundle FILES (SSL_CERT_FILE), not
# SSL_CERT_DIR directories.
_SYSTEM_CA_BUNDLES = (
    "/etc/ssl/cert.pem",                    # macOS (LibreSSL), Alpine, some BSD
    "/etc/ssl/certs/ca-certificates.crt",   # Debian/Ubuntu
    "/etc/pki/tls/certs/ca-bundle.crt",     # RHEL/Fedora/CentOS
)


def _resolve_ca_bundle():
    """Return the path to an existing trusted CA bundle file, or None.

    Preference order: the first existing platform system bundle, then certifi's
    bundle if the running interpreter can import it. Never fabricates a store
    and never weakens verification — it only points at a bundle already on disk.
    """
    for path in _SYSTEM_CA_BUNDLES:
        if os.path.isfile(path):
            return path
    # certifi is an optional fallback, and this path is load-bearing exactly in
    # the trust-store-less sandbox the feature targets — so a broken/partial
    # install (or an unrelated module shadowing the name) whose import or
    # `.where()` raises must degrade to "no bundle", never propagate out and
    # crash the whole pre-scan.
    try:
        import certifi
        bundle = certifi.where()
    except Exception:
        return None
    return bundle if bundle and os.path.isfile(bundle) else None


def _run_semgrep(repo_root, included_ids, report=None):
    """Run semgrep against .claude/semgrep/, return findings as (check_id, file_line, msg) tuples.

    `included_ids` is the collection of semgrep-* check IDs that the caller
    has already filtered for the active mode — a dict of id → check dict from
    `_classify_checks` (legacy callers may still pass a plain id set). Any
    finding whose mapped check_id is not in `included_ids` is dropped, and —
    when the check declares `paths:` — so is any finding outside those roots
    (Phase 133: semgrep scans the whole tree in one subprocess, so per-check
    `paths:` scoping is applied by post-filtering; see
    config.path_in_scope).

    ``report`` is the optional accounting collector; every terminal branch
    records the outcome for all selected semgrep ids (one subprocess serves
    them all). This is the stage the cross-harness run caught reporting a
    clean zero over the X.509 trust-store crash: a nonzero exit with empty
    stdout — the crash — used to fall through to a silent ``return`` here;
    it now records ``failed`` and surfaces the stderr. `report=None`
    preserves the original behavior for legacy callers.

    Returns early (empty list) when:
    - included_ids is empty (nothing to scan for this mode)
    - .claude/semgrep/ directory is absent (feature not installed → skipped)
    - semgrep binary is missing (skipped, tool-missing)
    - subprocess times out (failed) or the scan crashes / emits non-JSON (failed)
    """
    if not included_ids:
        return []

    semgrep_ids = [cid for cid in included_ids if str(cid).startswith("semgrep-")]

    def _record(status, reason=None, detail=None):
        if report is not None and semgrep_ids:
            report.record(semgrep_ids, status, "semgrep", reason, detail)

    semgrep_dir = os.path.join(repo_root, ".claude", "semgrep")
    if not os.path.isdir(semgrep_dir):
        _record(SKIPPED, "not-installed",
                "no .claude/semgrep/ — AST rules not installed")
        return []

    out = []
    # Exclude Sysop's bundled positive/negative semgrep fixtures from the
    # scan. They live at .claude/semgrep/fixtures/ as regression locks for
    # the rules themselves; the positive fixtures are deliberately violating
    # patterns and would otherwise surface as findings on every install.
    fixtures_exclude = os.path.join(".claude", "semgrep", "fixtures")
    # Give semgrep's OCaml core a trusted CA bundle so its startup OpenTelemetry
    # TLS authenticator can build in trust-store-less sandboxes (the X.509
    # "empty trust anchors" crash — see _resolve_ca_bundle). An explicit
    # SSL_CERT_FILE is the operator's choice and is never overridden; we only
    # fill it in when it is unset AND a real bundle exists. When neither holds we
    # leave the env untouched and the `failed` line below carries a remediation
    # hint. `--metrics=off` alone does not help — the authenticator is
    # constructed before that flag takes effect. (Deliverable 03 disproved every
    # telemetry-disable flag, OTEL_SDK_DISABLED included, so none is set here.)
    env = dict(os.environ)
    ca_hint = ""
    if not env.get("SSL_CERT_FILE"):
        bundle = _resolve_ca_bundle()
        if bundle:
            env["SSL_CERT_FILE"] = bundle
        else:
            ca_hint = " — set SSL_CERT_FILE to a trusted CA bundle"
    try:
        r = subprocess.run(
            ["semgrep", "scan", "--config", semgrep_dir,
             "--exclude", fixtures_exclude,
             "--json", "--metrics=off", "--quiet", repo_root],
            capture_output=True, text=True, cwd=repo_root, timeout=300, env=env,
        )
    except FileNotFoundError:
        print("warn: semgrep not on PATH — skipping AST checks "
              "(install: brew install semgrep  or  pip install semgrep)",
              file=sys.stderr)
        _record(SKIPPED, "tool-missing", "semgrep not on PATH")
        return out
    except subprocess.TimeoutExpired:
        print("warn: semgrep exceeded 300s timeout — skipping AST checks "
              "(findings may be incomplete)", file=sys.stderr)
        _record(FAILED, "timeout", "semgrep timed out after 300s")
        return out

    if not r.stdout:
        # Empty stdout with a nonzero exit is a crash BEFORE any JSON was
        # emitted (the X.509 trust-store failure lands here) — a `failed` run,
        # not a clean one. Surface the stderr instead of the old silent return.
        if r.returncode != 0:
            print(f"warn: semgrep exited {r.returncode} with no output — AST "
                  f"scan did NOT run: {stderr_excerpt(r.stderr)}{ca_hint}",
                  file=sys.stderr)
            _record(FAILED, "nonzero-no-output",
                    f"exit {r.returncode}: {stderr_excerpt(r.stderr)}{ca_hint}")
        else:
            _record(EXECUTED)
        return out
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        print("warn: semgrep produced non-JSON output — skipping",
              file=sys.stderr)
        _record(FAILED, "non-json", "semgrep produced non-JSON output")
        return out

    # semgrep --json always carries an `errors` array. A scan that printed JSON
    # but hit internal errors (an invalid rule file in a consumer overlay, a
    # partial crash) reports zero results while exiting nonzero — treated as a
    # clean run by the old code because the array was never read (spec §1).
    errors = data.get("errors") or []
    results = data.get("results") or []
    if errors and not results and r.returncode != 0:
        first = errors[0]
        msg = first.get("message") if isinstance(first, dict) else str(first)
        print(f"warn: semgrep reported {len(errors)} scan error(s) and no "
              f"results (exit {r.returncode}) — AST scan did NOT run",
              file=sys.stderr)
        _record(FAILED, "scan-errors",
                f"exit {r.returncode}: {len(errors)} scan error(s): "
                f"{stderr_excerpt(msg)}")
        return out
    if errors:
        print(f"warn: semgrep reported {len(errors)} internal error(s) — "
              "findings may be incomplete", file=sys.stderr)
    _record(EXECUTED)

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
