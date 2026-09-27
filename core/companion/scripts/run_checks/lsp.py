"""LSP / typechecker diagnostics (pyright + tsc).

Tool-shelling stage — pyright and tsc are invoked as CLIs. Findings are
emitted in the same ``(check_id, file_line, message, identity)`` shape as grep
findings so baseline matching, ``--update-baseline``, and
``--fail-on-blocking`` work uniformly.
"""
import json
import os
import re
import subprocess
import sys

from _log import _sanitize_log

from .accounting import EXECUTED, FAILED, SKIPPED, stderr_excerpt
from .config import _SKIP_DIRS, check_paths_by_id, finding_in_scope
from .baseline import identity_of
from .lint import FrontendDirAmbiguous, _find_frontend_dir, _node_bin


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

    Returns (check_id, file_line, message, identity) tuples. ``report`` is the optional
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
        # `rule` is parsed at the top of this loop to pick the check id, and
        # `pyright-general-warning` is a documented catch-all for every unmapped
        # warning — so without it the key means "whatever pyright says here".
        # Same defect as lint's, and the source line is not needed for it: the
        # re-scoped question is identity, not content.
        #
        # The fallback is load-bearing, not defensive. `pyright-general-warning`
        # is precisely the bucket for diagnostics whose `rule` is absent, so a
        # bare `rule` would let ONE check id emit both key arities — a two-field
        # key for the rule-less finding and a three-field one for its neighbour.
        # `legacy_entries` would then report the legitimate two-field entry as
        # no-longer-matching, and `--migrate-baseline` would rewrite or drop a
        # correct entry. That is the ambiguity `identity_of`'s empty-string
        # branch exists to forbid, and the first cut of this line created it.
        out.append((check_id, file_line,
                    f"[{check_id}] {sev} {file_line} — {msg_text}",
                    rule or identity_of(msg_text) or "no-rule"))
    return out


_TSC_CONFIG_ERROR_RE = re.compile(r"^error TS\d+: .*$", re.M)
_TSC_HEADER_RE = re.compile(
    r"^(.+?)\((\d+),(\d+)\):\s+(error|warning)\s+TS(\d+):\s+(.+)$"
)


def _run_tsc(repo_root, included_ids, report=None):
    out = []

    def _record(status, reason=None, detail=None):
        if report is not None and "tsc-type-error" in included_ids:
            report.record(["tsc-type-error"], status, "tsc", reason, detail)

    # The frontend is DISCOVERED, the way ESLint's is: the directory holding a
    # tsconfig.json beside node_modules/typescript. It used to be `frontend/`,
    # hard-coded here and in run_checks.sh's PATH, so tsc was dead for any other
    # layout while the skill described `<frontend>` as a placeholder (Phase 327).
    # tsc resolves @types/* relative to the tsconfig's adjacent
    # node_modules, which is why the install must sit beside the config.
    try:
        frontend_dir = _find_tsc_dir(repo_root)
    except FrontendDirAmbiguous as e:
        print(f"warn: {_sanitize_log(e)} — skipping tsc (with no frontend/tsconfig.json, "
              "it checks only a directory that is the one candidate)", file=sys.stderr)
        _record(SKIPPED, "misconfigured", "multiple node_modules/typescript candidates")
        return out
    if frontend_dir is None:
        configs = _tsconfig_dirs(repo_root)
        if not configs:
            nested = _tsconfig_dirs(repo_root, nested_only=True)
            if nested:
                # Silence here would read as "no TypeScript", which is false.
                rels = ", ".join(sorted(os.path.relpath(d, repo_root) for d in nested))
                print(f"warn: tsconfig.json found only inside nested checkouts ({rels}), whose "
                      "files are another checkout's — skipping tsc", file=sys.stderr)
                _record(SKIPPED, "input-missing", "tsconfig.json only inside nested checkouts")
                return out
            _record(SKIPPED, "input-missing", "no tsconfig.json under the repo root")
            return out
        # A config with no install beside it. Worktrees typically lack
        # node_modules, which would produce spurious "Cannot find module" errors,
        # so skip loudly rather than run.
        rels = [os.path.relpath(d, repo_root) for d in configs]
        rels.sort(key=lambda r: (r.count(os.sep), r))
        where = (f"{rels[0]}/node_modules/typescript missing" if len(rels) == 1 else
                 f"no node_modules/typescript beside any tsconfig.json ({', '.join(rels)})")
        # tsc resolves types from the install beside the config, so a hoisted or
        # workspace-root install cannot satisfy it; the advice says so.
        print(f"warn: {where} — skipping tsc (install: cd {rels[0]} && npm ci); a hoisted "
              "or workspace-root install is not read", file=sys.stderr)
        _record(SKIPPED, "input-missing", f"{where.replace(' missing', ' absent')}")
        return out
    fe_rel = os.path.relpath(frontend_dir, repo_root)
    tsc_bin = _node_bin(frontend_dir, "tsc")
    # Ask tsc which files the config puts in the program before type-checking it.
    # A config that lists none — solution-style (`"files": []` plus `references`,
    # Vite's and Nx's defaults), whatever its spelling, encoding or `extends`
    # chain — makes `tsc -p` check nothing and exit 0, a clean that is false. Only
    # an exit-0 listing with no file outside node_modules skips; anything else
    # (an older tsc without the flag, a config error) falls through to the real
    # run, which reports it. Phase 327's round 2 broke a JSON reading of the
    # config three ways; tsc resolves the config itself, so this has no spelling.
    try:
        listing = subprocess.run(
            [tsc_bin, "--listFilesOnly", "-p", "tsconfig.json"],
            capture_output=True, text=True, cwd=frontend_dir, timeout=600,
        )
    except FileNotFoundError:
        listing = None
    except subprocess.TimeoutExpired:
        print("warn: tsc --listFilesOnly exceeded 600s timeout — skipping TypeScript "
              "typecheck (findings may be incomplete)", file=sys.stderr)
        _record(FAILED, "timeout", "tsc --listFilesOnly timed out after 600s")
        return out
    if (listing is not None and listing.returncode == 0
            and not _project_files(listing.stdout, frontend_dir)):
        print(f"warn: {fe_rel}/tsconfig.json puts no files in the program (a solution-style "
              "config checks nothing with `tsc -p`) — skipping tsc", file=sys.stderr)
        _record(SKIPPED, "not-configured", "tsc lists no project files for tsconfig.json")
        return out
    try:
        r = subprocess.run(
            [tsc_bin, "--noEmit", "-p", "tsconfig.json",
             "--pretty", "false"],
            capture_output=True, text=True, cwd=frontend_dir, timeout=600,
        )
    except FileNotFoundError:
        print("warn: tsc not available — skipping TypeScript typecheck "
              f"(install: (cd {fe_rel} && npm ci))", file=sys.stderr)
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
    # A config-level error has no `path(line,col)` — `error TS18003: No inputs were
    # found in config file …` — so the parser below reads nothing and the run looked
    # clean. With no located diagnostic at all, it is a run that checked nothing.
    #
    # tsc also suppresses every semantic diagnostic while an OPTIONS diagnostic stands,
    # and those are located in the config file (`tsconfig.json(1,81): error TS5107` for a
    # tsc 6 deprecation). So the test is: a nonzero exit with no diagnostic located in a
    # source file — only config-level or `.json`-located ones (Phase 327's round 3).
    config_errors = _TSC_CONFIG_ERROR_RE.findall(r.stdout)
    located = [m for m in (_TSC_HEADER_RE.match(ln) for ln in r.stdout.splitlines()) if m]
    in_source = [m for m in located if not m.group(1).lower().endswith(".json")]
    if r.returncode != 0 and not in_source and (config_errors or located):
        first = config_errors[0] if config_errors else located[0].group(0)
        print(f"warn: tsc reported only config-level errors — TypeScript typecheck did NOT "
              f"run: {stderr_excerpt(first)}", file=sys.stderr)
        _record(FAILED, "config-error", stderr_excerpt(first))
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


def _find_tsc_dir(repo_root):
    """The directory tsc checks: `frontend/` whenever it has a `tsconfig.json`, else the walk.

    `<root>/frontend/tsconfig.json` is AUTHORITATIVE, and it was the only config tsc read
    before discovery existed. If an install sits beside it, that is the answer; if not, the
    answer is None — a loud skip naming `frontend/` — and the walk never runs. Phase 327's
    round 3 found the walk adopting a sibling project (or a hoisted workspace root) in place
    of an uninstalled `frontend/`, and recording `executed` over code that was never the
    frontend's. So every repo with a `frontend/tsconfig.json` behaves exactly as before the
    phase; discovery serves only repos without one. The walk skips nested checkouts, so no
    in-repo agent worktree's INSTALL is adopted — though a root config's own `include` can
    still reach files under one, which is that config's choice, not this function's.
    """
    conventional = os.path.join(os.path.abspath(repo_root), "frontend")
    if os.path.isfile(os.path.join(conventional, "tsconfig.json")):
        if os.path.isdir(os.path.join(conventional, "node_modules", "typescript")):
            return conventional
        return None
    return _find_frontend_dir(repo_root, "typescript", beside="tsconfig.json",
                              skip_nested_checkouts=True)


def _tsconfig_dirs(repo_root, nested_only=False):
    """Where a tsconfig.json sits with no install beside it, for the skip warning.

    `<repo_root>/frontend` alone when it has one (the pre-discovery message), else
    every other config the walk finds, nested checkouts excluded as in discovery.
    ``nested_only`` returns the configs inside nested checkouts instead, so a repo
    whose only TypeScript is in one can say so rather than claim it has none.
    """
    conventional = os.path.join(os.path.abspath(repo_root), "frontend")
    if not nested_only and os.path.isfile(os.path.join(conventional, "tsconfig.json")):
        return [conventional]
    found = []
    for dirpath, dirnames, filenames in os.walk(os.path.abspath(repo_root), followlinks=False):
        inside = os.path.lexists(os.path.join(dirpath, ".git")) and dirpath != os.path.abspath(repo_root)
        if nested_only:
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            if inside:
                for sub, subdirs, subfiles in os.walk(dirpath, followlinks=False):
                    subdirs[:] = [d for d in subdirs if d not in _SKIP_DIRS]
                    if "tsconfig.json" in subfiles:
                        found.append(sub)
                dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS
                       and not os.path.lexists(os.path.join(dirpath, d, ".git"))]
        if "tsconfig.json" in filenames:
            found.append(dirpath)
    return sorted(found)


def _project_files(listing, frontend_dir):
    """The files a `--listFilesOnly` listing names outside node_modules (lib and @types
    declarations live there, and are listed for every program with any source).

    Judged on each path RELATIVE to the frontend dir, by component: a repo that itself
    lives under a `node_modules/` directory would otherwise have every file excluded
    (round 3), and a name merely containing the word (`my_node_modules_app`) is not one.
    """
    base = os.path.abspath(frontend_dir)
    out = []
    for ln in listing.splitlines():
        entry = ln.strip()
        if not entry:
            continue
        rel = os.path.relpath(entry, base) if os.path.isabs(entry) else entry
        if "node_modules" in rel.replace("\\", "/").split("/"):
            continue
        out.append(entry)
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
    # `tsc-type-error` is one catch-all id for the whole stage, so two different
    # TS errors on one line shared a key. Group 5 is the TS number — captured by
    # `_TSC_HEADER_RE` since it was written, and used by nothing until now.
    out.append((check_id, file_line,
                f"[{check_id}] {sev} {file_line} — {msg_text}",
                f"TS{m.group(5)}"))


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
