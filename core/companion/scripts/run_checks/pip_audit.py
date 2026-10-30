"""pip-audit diagnostics + the requirements-file discovery helper.

gdp hardcoded ``requirements.txt``; Sysop runs in repos whose
requirements layouts vary, so the discovery helper enumerates the
``requirements*.txt`` set at repo root.
"""
import glob
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

from .baseline import identity_of
from .accounting import DEGRADED, EXECUTED, FAILED, SKIPPED, stderr_excerpt
from .config import skip_sentinel_disabled


def _find_requirements_files(repo_root):
    """Return sorted list of requirements*.txt files at repo root.

    Matches `requirements.txt`, `requirements-dev.txt`, `requirements-prod.txt`,
    etc. Returns relative paths. Does NOT match the `requirements/` directory
    or extension-suffixed forms like `requirements.txt.bak`.
    """
    pattern = os.path.join(repo_root, "requirements*.txt")
    matches = sorted(glob.glob(pattern))
    return [os.path.relpath(m, repo_root) for m in matches if os.path.isfile(m)]


# `--no-emit-workspace --no-emit-local`, not `--no-emit-project`: a workspace
# member or a local path dependency exports without a hash, and `--disable-pip`
# refuses a requirements file with one unhashed line ("does not contain a
# hash"), so the whole audit would abort on every workspace. Neither is on
# PyPI, so neither was auditable; their third-party dependencies still export.
# `--all-extras` beside `--all-groups`: optional dependencies are part of the
# lock. A project that declares conflicting extras or groups (`[tool.uv]
# conflicts`, the torch cpu/gpu shape) cannot export them all at once; the
# stage then exports again with UV_EXPORT_NARROW and says what it left out.
UV_EXPORT_ARGS = ["uv", "export", "--locked", "--all-groups", "--all-extras",
                  "--format", "requirements-txt",
                  "--no-emit-workspace", "--no-emit-local", "--quiet"]
UV_EXPORT_NARROW = [a for a in UV_EXPORT_ARGS
                    if a not in ("--all-groups", "--all-extras")]


def _has_pip():
    """Whether the interpreter running these checks can be read by pip-audit's
    environment audit, which shells out to its ``python -m pip``."""
    return importlib.util.find_spec("pip") is not None


def _audit_target(repo_root, req_files):
    """Which dependency set to audit: ``(kind, label, with_env)``.

    ``uv`` when ``uv.lock`` is at the repo root. Otherwise ``merged``: every
    root ``requirements*.txt`` (one run each) AND, when the interpreter
    running the checks has pip, that interpreter's environment, findings
    unioned. With neither, ``environment``, which fails loudly with a hint.
    A bare ``pip-audit`` audits the interpreter pip-audit is installed into,
    so a uv-tool, pipx or Homebrew pip-audit reported its own packages and
    never the project's.

    Neither source alone is safe. The requirements files alone read
    "executed, 0 findings" for a pyproject project whose only
    ``requirements-dev.txt`` lists dev tools; the environment alone, when the
    checks run under a Python that is not the project's (the CI template's
    setup-python), reports that Python's packages and misses the files'. The
    union misses neither; its cost is the runner's own packages reported as
    findings when the checks' Python is not the project's.
    """
    if os.path.isfile(os.path.join(repo_root, "uv.lock")):
        return "uv", "uv.lock (via uv export --locked, every marker branch)", False
    with_env = _has_pip()
    parts = list(req_files)
    if with_env:
        parts.append(f"the environment of {sys.executable}")
    if not parts:
        return "environment", f"the environment of {sys.executable}", True
    return "merged", " and ".join(parts), with_env


def _marker_branches(text):
    """Split a ``uv export`` requirements file into files pip-audit accepts
    whole, every environment marker and hash removed: ``(files, unpinned)``.

    ``--disable-pip`` evaluates each line's marker against pip-audit's OWN
    interpreter and drops the lines that do not match, so a uv-tool
    pip-audit on a newer Python never audits a ``python_version < '3.12'``
    pin the project runs. Stripping the markers audits every branch the lock
    holds; a package pinned at two versions (one per branch) then appears
    twice, which pip-audit refuses in one file ("has duplicate
    requirements"), so the n-th version of a package goes to the n-th file.
    The files are audited with ``--disable-pip --no-deps``: a lock pins every
    package, so nothing needs resolving, and hashes are dropped because an
    audit installs nothing — kept, one unhashed line (an index that serves no
    hashes) refused the whole file. ``--`` option lines are copied into every
    file. A requirement with no ``==`` pin (a git or URL source, any ``-e``
    line) is returned in ``unpinned``: pip-audit cannot name its version, and
    a hashed URL line it skips silently.
    """
    entries, options, buf = [], [], ""
    for raw in text.splitlines():
        line = raw.strip()
        if not buf and (not line or line.startswith("#")):
            continue
        if line.endswith("\\"):
            buf += line[:-1].strip() + " "
            continue
        entries.append((buf + line).strip())
        buf = ""
    if buf.strip():
        entries.append(buf.strip())

    files, seen, unpinned = [], set(), []
    for entry in entries:
        if entry.startswith("--"):
            options.append(entry)
            continue
        req = re.split(r"\s--hash", entry, maxsplit=1)[0]
        req = req.split(";", 1)[0].strip()
        if entry.startswith("-") or "@" in req or "==" not in req:
            if req not in unpinned:
                unpinned.append(req)
            continue
        req = re.sub(r"\s+", "", req)
        if req in seen:
            continue  # the same pin under two markers: audit it once
        seen.add(req)
        name = re.split(r"[=<>!~\[]", req, maxsplit=1)[0]
        key = re.sub(r"[-_.]+", "-", name).lower()
        for f in files:
            if key not in f:
                f[key] = req
                break
        else:
            files.append({key: req})
    return ["\n".join(options + list(f.values())) + "\n" for f in files], unpinned


def _export_uv_lock(repo_root, exported, _record):
    """``uv export`` the lock to ``exported``: ``None`` when it failed (the
    failure recorded and warned; never an environment audit instead), else
    the coverage it gave up (``""`` when none). Records and warns on every
    failure."""
    def run(argv):
        return subprocess.run([*argv, "--output-file", exported],
                              capture_output=True, text=True, cwd=repo_root,
                              timeout=300)
    try:
        u = run(UV_EXPORT_ARGS)
        if u.returncode != 0 and re.search(r"incompatible with the (declared )?conflicts",
                                           u.stderr or ""):
            print("warn: the project declares conflicting extras or groups — "
                  "auditing the default dependency set only; extras and "
                  "non-default groups are NOT audited", file=sys.stderr)
            u = run(UV_EXPORT_NARROW)
            if u.returncode == 0:
                return "extras and non-default groups not exported (declared conflicts)"
    except FileNotFoundError:
        print("warn: uv.lock found but uv not on PATH — dependency audit "
              "did NOT run (install uv; the environment audit is not a "
              "substitute for the lockfile)", file=sys.stderr)
        _record(SKIPPED, "tool-missing", "uv not on PATH (uv.lock present)")
        return None
    except subprocess.TimeoutExpired:
        print("warn: uv export exceeded 300s timeout — dependency audit "
              "did NOT run", file=sys.stderr)
        _record(FAILED, "timeout", "uv export timed out after 300s")
        return None
    if u.returncode != 0:
        tail = (u.stderr or "").strip().splitlines()
        print(f"warn: uv export exited {u.returncode} — dependency audit "
              f"did NOT run: {tail[0] if tail else 'no stderr'}",
              file=sys.stderr)
        _record(FAILED, "uv-export",
                f"exit {u.returncode}: {stderr_excerpt(u.stderr)}")
        return None
    return ""


def _run_pip_audit(repo_root, included_ids, report=None):
    """Run pip-audit against the project's dependency set, return findings.

    Target (`_audit_target()` says why): a ``uv.lock`` is exported
    (`_export_uv_lock()`), split by `_marker_branches()` and each file audited
    with ``-r <file> --disable-pip``; otherwise every ``requirements*.txt`` is
    audited in its own run with ``-r <file>`` (pip resolves the transitive
    set; `_audit_runs()` says why not one run) and, when the interpreter
    running these checks has pip, its environment too, with
    ``PIPAPI_PYTHON_LOCATION`` naming it (run_checks.sh prefers the project
    venv's python) so a pip-audit installed elsewhere audits the project and
    not itself; the findings are unioned. With neither, the environment
    audit runs and fails loudly with a hint. The stage prints the target it
    audited. A ``uv.lock`` the stage cannot export never falls back to the
    environment audit: that fallback is the wrong-target result this order
    exists to prevent.

    The findings are anchored at the first discoverable requirements*.txt
    file (via `_find_requirements_files()`); falls back to "pyproject.toml:1"
    for pyproject/uv/poetry consumers, then "requirements.txt:1" as the
    layout-less stable key. The anchor is part of every baseline key, so it
    does NOT follow the audit target: a uv consumer stays at pyproject.toml:1
    and its accepted entries keep matching.

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
    failed run, not a clean one). Skips without one, and without starting
    pip-audit, when every selected ``pip-audit-*`` check is disabled by the
    overlay's sentinel: recorded as skipped(paths-unresolved), as the grep
    stage records it (Q-701).
    """
    if not included_ids:
        return []

    # Sentinel-disabled checks read `skipped`, not a zero this run never measured (Q-701).
    disabled = skip_sentinel_disabled(included_ids, "pip-audit-", "pip-audit", report)
    pip_audit_ids = [cid for cid in included_ids if cid not in disabled]
    if not pip_audit_ids:
        return []

    def _record(status, reason=None, detail=None):
        if report is not None and pip_audit_ids:
            report.record(pip_audit_ids, status, "pip-audit", reason, detail)

    req_files = _find_requirements_files(repo_root)
    kind, label, with_env = _audit_target(repo_root, req_files)
    env_run = (f"the environment of {sys.executable}", [],
               {**os.environ, "PIPAPI_PYTHON_LOCATION": sys.executable})
    with tempfile.TemporaryDirectory(prefix="sysop-pip-audit-") as tmp:
        if kind == "uv":
            exported = os.path.join(tmp, "uv-export.txt")
            gave_up = _export_uv_lock(repo_root, exported, _record)
            if gave_up is None:
                return []
            try:
                with open(exported, encoding="utf-8") as fh:
                    branches, unpinned = _marker_branches(fh.read())
            except (OSError, UnicodeDecodeError) as exc:
                print(f"warn: could not read uv's export — dependency audit did "
                      f"NOT run: {exc}", file=sys.stderr)
                _record(FAILED, "uv-export", f"unreadable export: {exc}")
                return []
            if unpinned:
                print("warn: not audited, no version pin pip-audit can look up "
                      f"(a git, URL or editable source): {', '.join(unpinned)}",
                      file=sys.stderr)
                gave_up = "; ".join(filter(None, [
                    gave_up, f"not audited, no version pin: {', '.join(unpinned)}"]))
            runs = []
            for i, body in enumerate(branches, 1):
                path = os.path.join(tmp, f"uv-branch-{i}.txt")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(body)
                runs.append((f"uv.lock run {i}",
                             ["-r", path, "--disable-pip", "--no-deps"], None))
            print(f"pip-audit: auditing {label} ({len(runs)} run(s))", file=sys.stderr)
            return _audit_runs(repo_root, runs, pip_audit_ids, req_files, _record,
                               gave_up, collect_skips=True)
        runs = [(f, ["-r", f], None) for f in req_files]
        if with_env:
            runs.append(env_run)
        print(f"pip-audit: auditing {label}", file=sys.stderr)
        gave_up = ""
        if (kind == "merged" and not with_env
                and os.path.isfile(os.path.join(repo_root, "pyproject.toml"))):
            print("warn: the interpreter running the checks has no pip, so "
                  "dependencies declared only in pyproject.toml are NOT "
                  "audited (commit a uv.lock, or run the checks under a venv "
                  "with pip)", file=sys.stderr)
            gave_up = ("dependencies declared only in pyproject.toml "
                       "(the checks' interpreter has no pip)")
        return _audit_runs(repo_root, runs, pip_audit_ids, req_files, _record,
                           gave_up)


def _audit_runs(repo_root, runs, pip_audit_ids, req_files, _record, gave_up="",
                collect_skips=False):
    """Several pip-audit runs, ``(label, args, env)`` each, findings merged.

    Requirements files get one run each because one run with several ``-r``
    is ONE pip resolve: a hashed file turns on ``--require-hashes`` for an
    unhashed sibling, and a pin the two files disagree on is
    ``ResolutionImpossible`` — either fails the whole stage for a layout that
    audits cleanly file by file. A failed run is recorded as the stage's
    outcome (naming its label); the other runs' findings are still returned.
    ``gave_up`` names inputs the runs did not cover; a run that otherwise
    completes is then ``degraded``, never ``executed``, because its zero is
    not a real zero. With ``collect_skips`` (the lock's runs), a pin
    pip-audit reports as skipped — a local version such as ``+cpu``, a package
    no index it reads carries — is a cut too, named and ``degraded``. Not for
    requirements or environment runs: there the project's own editable or
    local package is always skipped, and is not a dependency.
    """
    out, failed = [], None
    skips = [] if collect_skips else None
    for label, args, env in runs:
        outcomes = []
        found = _invoke_and_parse(
            repo_root, [*args, "--skip-editable", "--format", "json"], env,
            pip_audit_ids, req_files, lambda *o: outcomes.append(o), skips)
        out += [f for f in found if f not in out]
        status = outcomes[-1] if outcomes else (EXECUTED,)
        if status[0] == SKIPPED:  # pip-audit itself is missing: no run can work
            _record(*(failed or status))
            return out
        if status[0] == FAILED and failed is None:
            reason = status[1] if len(status) > 1 else None
            detail = status[2] if len(status) > 2 else None
            failed = (FAILED, reason, f"{label}: {detail}")
    if skips:
        print(f"warn: not audited, skipped by pip-audit: {', '.join(skips)}",
              file=sys.stderr)
        gave_up = "; ".join(filter(None, [
            gave_up, f"skipped by pip-audit: {', '.join(skips)}"]))
    _record(*(failed or ((DEGRADED, "partial-input", gave_up) if gave_up
                         else (EXECUTED,))))
    return out


def _invoke_and_parse(repo_root, args, env, pip_audit_ids, req_files, _record,
                      skips=None):
    """Run pip-audit with ``args``, record the outcome, return findings. When
    ``skips`` is a list, each dependency pip-audit skipped (other than as
    editable) is appended to it as ``"name version (reason)"``."""
    out = []
    try:
        r = subprocess.run(
            ["pip-audit", *args],
            capture_output=True, text=True, cwd=repo_root, timeout=300, env=env,
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
                env=env,
            )
        except FileNotFoundError:
            r = None
        except subprocess.TimeoutExpired:
            # A timeout is lost work, not a declined precondition — `failed`,
            # same as the primary invocation's timeout. Folding it into the
            # `r is None` → tool-missing branch would mislabel a crash as a skip.
            print("warn: pip-audit (module fallback) exceeded 300s timeout — "
                  "skipping dependency audit (findings may be incomplete)",
                  file=sys.stderr)
            _record(FAILED, "timeout",
                    "pip-audit (module fallback) timed out after 300s")
            return out
        if r is not None and r.returncode != 0 and not r.stdout and re.search(
            r"No module named '?pip_audit'?(\s|$)", r.stderr or ""
        ):
            r = None
        if r is None:
            print("warn: pip-audit not on PATH — skipping dependency audit "
                  "(install: pip install pip-audit — into the project venv is "
                  "enough; the venv's python resolves it via -m)", file=sys.stderr)
            _record(SKIPPED, "tool-missing", "pip-audit not on PATH")
            return out
    except subprocess.TimeoutExpired:
        print("warn: pip-audit exceeded 300s timeout — skipping dependency audit "
              "(findings may be incomplete)", file=sys.stderr)
        _record(FAILED, "timeout", "pip-audit timed out after 300s")
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
            if env is not None and re.search(r"No module named '?pip'?(\s|$)",
                                             r.stderr or ""):
                # A uv-made venv has no pip, so the environment audit cannot
                # read it; the lockfile audit needs no pip.
                print("hint: the project interpreter has no pip — commit a "
                      "uv.lock or a requirements*.txt and the stage audits "
                      "that instead", file=sys.stderr)
            _record(FAILED, "nonzero-no-output",
                    f"exit {r.returncode}: {stderr_excerpt(r.stderr)}")
        else:
            _record(EXECUTED)
        return out
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        print("warn: pip-audit produced non-JSON output — skipping",
              file=sys.stderr)
        _record(FAILED, "non-json", "pip-audit produced non-JSON output")
        return out

    _record(EXECUTED)
    if skips is not None:
        for dep in data.get("dependencies", []):
            reason = dep.get("skip_reason")
            if reason and "editable" not in reason:
                skips.append(f"{dep.get('name', '?')} {dep.get('version') or ''}"
                             f"".strip() + f" ({reason})")

    check_id = "pip-audit-vuln"
    if check_id not in pip_audit_ids:
        return out

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
        # Two id-less advisories on one package need a discriminator, and it
        # must be CONTENT. `vuln_index` alone keys a list POSITION: fix an
        # earlier advisory and every later index shifts, so an accepted key
        # silently excuses a different, unreviewed advisory — Q-245's exact
        # failure mode, reintroduced by the fix for Q-245. The description
        # hash is stable under reordering; the index is the last resort.
        for vuln_index, vuln in enumerate(dep.get("vulns", []) or []):
            # `or`, not `.get("id", "?")`: the two-argument form only fires
            # when the KEY IS ABSENT, so `"id": null` and `"id": ""` — both
            # legal in this JSON — sailed past the fallback and produced a
            # two-field key, which is Q-245 alive again on a blocking gate.
            vid = vuln.get("id") or ""
            aliases = vuln.get("aliases", []) or []
            fix_versions = vuln.get("fix_versions", []) or []
            desc = (vuln.get("description") or "").replace("\n", " ")[:200]
            alias_str = f" ({', '.join(aliases)})" if aliases else ""
            fix_str = (f" — fix: bump to {fix_versions[0]}"
                       if fix_versions else "")
            msg_text = f"{name}=={version} {vid}{alias_str}{fix_str} — {desc}"
            # The anchor is computed once, OUTSIDE this loop, so every vuln in
            # the run shares it — one baseline entry swallowed the entire stage,
            # new critical CVEs included. `vid` is the discriminator; content
            # hashing could not have fixed this, since the "matched line" is
            # line 1 of requirements.txt and unrelated to the finding.
            out.append((check_id, anchor,
                        f"[{check_id}] HIGH {anchor} — {msg_text}",
                        # `vid` falls back to "?" when an advisory carries no
                        # id, which would collapse every id-less vuln in the run
                        # back onto ONE key — Q-245 alive again for that
                        # subpopulation. name==version always exists and
                        # discriminates by package.
                        vid or f"{name}=={version}#"
                        f"{identity_of(desc) or vuln_index}"))
    return out
