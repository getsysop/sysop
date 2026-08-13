"""Semgrep / AST diagnostics.

semgrep is invoked as a CLI. Findings are emitted in the same
``(check_id, file_line, message)`` shape as grep/LSP findings so baseline
matching, ``--update-baseline``, and ``--fail-on-blocking`` work uniformly.
"""
import json
import os
import subprocess
import sys

from .accounting import DEGRADED, EXECUTED, FAILED, SKIPPED, stderr_excerpt
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


# semgrep's built-in default ignore list, "Common test paths" block, read out of
# the compiled semgrep-core binary at 1.157.0 rather than from any summary of it:
#
#     test/  tests/  testsuite/  *_test.go
#
# It applies only when the project has no ``.semgrepignore``, it matches at ANY
# depth, and — the reason this module carries a recovery step at all —
# discovery-excluded files are absent from ``paths.skipped``, so nothing records
# the omission while the accounting line reads ``executed with 0 findings``.
#
# Internal tracker #361 (Q-011) named only ``test/`` and ``tests/``; the other two entries
# were found by reading the binary. ``*_test.go`` is Go's entire test convention.
_IGNORED_TEST_DIRS = frozenset({"test", "tests", "testsuite"})
_IGNORED_TEST_SUFFIX = "_test.go"

# The recovered population rides on the command line: semgrep 1.157.0 has no
# --targets-file and reads no targets from stdin (both probed). So the ceiling is
# the platform's exec limit, and a fixed guess is wrong in both directions — a
# review round measured a real usable ceiling of ~980 KiB here while a flat
# 256 KiB was discarding 28% of a 5,000-file population that would have fit.
# ``_operand_budget`` derives it instead, and this constant is only the floor
# used when the platform will not say. When the population exceeds the budget the
# stage records ``degraded`` and names the shortfall — silently scanning less is
# the defect this exists to close, not an acceptable way to close it.
_OPERAND_BUDGET = 256 * 1024

# Room for the fixed argv (``semgrep scan --config … --exclude … --json …`` plus
# the directory operand) and for an environment that grows between the
# measurement and the exec.
_ARGV_SLACK = 64 * 1024


def _operand_budget():
    """Bytes available for recovered operands on this platform.

    Half the headroom left after the environment and the fixed arguments, floored
    at ``_OPERAND_BUDGET``. Half, not all, because the environment a consumer
    execs with is not the one measured here — a CI runner that injects secrets
    between this call and the exec must not turn a working scan into ``E2BIG``.
    """
    try:
        limit = os.sysconf("SC_ARG_MAX")
    except (AttributeError, ValueError, OSError):
        return _OPERAND_BUDGET
    if not isinstance(limit, int) or limit <= 0:
        return _OPERAND_BUDGET
    env_bytes = sum(len(k) + len(v) + 2 for k, v in os.environ.items())
    return max(_OPERAND_BUDGET, (limit - env_bytes - _ARGV_SLACK) // 2)


def _git_lines(repo_root, args):
    """``git`` output split on NUL, or None when git cannot answer.

    The environment is stripped of ``GIT_*`` the same way ``next_task.py``,
    ``validate_tasks.py``, ``scope_overlap.py`` and ``backfill_completed_dates.py``
    strip it: git exports ``GIT_DIR``/``GIT_INDEX_FILE`` into every hook, and a
    pre-commit invocation would otherwise point these calls at the wrong index.
    Demonstrated consequence, on a tree with gitignored-but-force-tracked tests:
    the recovered population goes from the right files to none at all, silently.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        r = subprocess.run(["git"] + args, cwd=repo_root,
                           capture_output=True, text=True, timeout=60, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return [p for p in r.stdout.split("\0") if p]


def _inside_git_repo(repo_root):
    """True when git is available AND ``repo_root`` is inside a work tree.

    The discriminator for the two ways ``_git_lines`` returns ``None``. Outside a
    repository — or with no git at all — there is genuinely nothing to recover
    and silence is correct. INSIDE one, a failure means a corrupted index, a
    permission problem, or a timeout, and that is worth saying out loud: the
    recovery silently returned an empty population and the stage still reported
    ``executed``.
    """
    # `_git_lines` splits on NUL because its other two callers pass `-z`.
    # `rev-parse` has no `-z`, so its whole output arrives as one element with a
    # trailing newline — comparing against a bare `["true"]` is False for every
    # real repository, which is how the first version of this got it backwards.
    lines = _git_lines(repo_root, ["rev-parse", "--is-inside-work-tree"])
    return bool(lines) and lines[0].strip() == "true"


def _is_ignored_test_path(rel):
    """True when semgrep's built-in default ignore list drops ``rel``.

    The three directory entries are directory-only (``test/`` has a trailing
    slash), so they match a path *component* and never a basename. ``*_test.go``
    has no trailing slash, so in gitignore syntax it matches a **directory of
    that name as well as a file** — a review round found a `helpers_test.go/`
    directory still eaten by the very block this recovers.
    """
    parts = rel.split("/")
    if any(seg in _IGNORED_TEST_DIRS for seg in parts[:-1]):
        return True
    if any(seg.endswith(_IGNORED_TEST_SUFFIX) for seg in parts[:-1]):
        return True
    return parts[-1].endswith(_IGNORED_TEST_SUFFIX)


def _default_ignored_targets(repo_root, exclude_rel):
    """Explicit operands for the files semgrep's default ignore list would drop.

    Returns ``(targets, dropped)`` — absolute paths to add alongside the directory
    operand, and the count omitted because the operand budget was reached.

    **The directory operand is KEPT.** That is the whole design: an explicitly named
    *file* bypasses the default ignore list, but a directory operand does not — naming
    ``<root>/tests`` recovers nothing, measured. So the scan stays a directory scan and
    this function supplies only the population that scan cannot see. Phase 189 built the
    other shape — replacing the directory with a full enumeration — and its review round
    withdrew it as worse than the defect. Each condition that round raised is answered
    here, and by construction rather than by care:

    * **Path shape follows operand shape.** Every operand is ``os.path.join(repo_root,
      rel)``, so it carries *the same* shape as the ``repo_root`` operand beside it.
      semgrep then reports both populations in one shape and the existing
      ``os.path.relpath(result["path"], repo_root)`` resolves them identically. A
      relative ``repo_root`` keeps today's behaviour exactly, because the join preserves
      it — nothing here introduces a second shape to reconcile.
    * **A tracked symlink aborts the WHOLE scan** (``Invalid scanning root: … is a
      symbolic link``, ``scanned: []``, exit 2). ``islink`` is filtered out below, so a
      symlink is never named. Under the directory operand semgrep skips symlinks itself,
      which is why the shipped scan survives them today and must keep doing so.
    * **A tracked file absent from the worktree** (deleted-not-staged, mid-rename, sparse
      checkout, ``skip-worktree``) aborts it the same way. ``isfile`` is filtered.
    * **``--exclude`` stops applying to a named file**, so the bundled fixtures would
      return as findings on every install. ``exclude_rel`` is filtered here, and the
      directory operand still carries ``--exclude`` for everything else.
    * **Untracked files stop being scanned** under a pure enumeration. Here the directory
      operand still discovers them, and ``--others --exclude-standard`` adds the untracked
      *test* files the directory operand cannot see.
    * **A submodule gitlink** is one ``ls-files`` entry that would expand to many scanned
      files. ``isfile`` is False for the gitlink directory, so it is filtered; the
      submodule keeps whatever treatment the directory operand gives it.
    * **The 300s timeout stays whole-scan** because this stays ONE subprocess. It never
      becomes per-batch, so the ``failed`` detail that says 300s remains true.

    Outside a git repo there is nothing to enumerate from; the caller falls back to the
    bare directory operand, which is exactly today's behaviour.
    """
    # A project ``.semgrepignore`` REPLACES the built-in default list wholesale,
    # so there is nothing for this function to recover — and naming files anyway
    # would override the consumer's own exclusions, because an explicit operand
    # bypasses `.semgrepignore` exactly as it bypasses the built-in list. A review
    # round demonstrated it: with `tests/` in their `.semgrepignore`, the scan
    # returned a file they had deliberately excluded. Only a ROOT `.semgrepignore`
    # has this effect — a nested one does not disable the built-in list, verified —
    # so the probe is deliberately root-only rather than a walk.
    if os.path.isfile(os.path.join(repo_root, ".semgrepignore")):
        # NO WARNING HERE, deliberately. This early return shares its shape with
        # the git-failure one below, but it is a correct, intentional disable —
        # warning would fire on every run for a consumer who configured it on
        # purpose, which is the same noise class this recovery exists to avoid.
        return [], 0, False

    tracked = _git_lines(repo_root, ["ls-files", "-z"])
    if tracked is None:
        # Two very different states reach here. Outside a repo (or with no git)
        # there is nothing to enumerate and the caller's bare directory operand
        # is exactly right — say nothing. Inside a repo, git ANSWERED and failed:
        # a corrupted index, a permission problem, a timeout. The recovery then
        # returns an empty population and the stage would report `executed` over
        # a set it could not enumerate — a status that does not mean what it says.
        return [], 0, _inside_git_repo(repo_root)
    untracked = _git_lines(
        repo_root, ["ls-files", "-z", "--others", "--exclude-standard"]) or []

    budget = _operand_budget()
    targets, dropped, used = [], 0, 0
    for rel in sorted(set(tracked) | set(untracked)):
        if not _is_ignored_test_path(rel):
            continue
        # The shipped --exclude does not survive an explicit file operand.
        if rel == exclude_rel or rel.startswith(exclude_rel + "/"):
            continue
        abs_path = os.path.join(repo_root, rel)
        # A symlink or a missing path is not merely unscannable — as a named
        # operand it aborts the entire scan. Never name one.
        if os.path.islink(abs_path) or not os.path.isfile(abs_path):
            continue
        # BYTES, not characters. exec counts the encoded argv, and a path of
        # astral-plane characters is 4x its length — the one shape where a
        # character-counted budget under-reports enough to reach E2BIG.
        cost = len(os.fsencode(abs_path)) + 1
        if used + cost > budget:
            dropped += 1
            continue
        used += cost
        targets.append(abs_path)
    return targets, dropped, False


def _partial_parse_paths(errors):
    """Paths whose parse failed part-way, from semgrep's ``errors[]`` (internal tracker #362).

    ``errors[].type`` is either a bare string or a ``[name, [...]]`` pair; both
    shapes are read so a semgrep upgrade that changes one does not silently empty
    this set (which would restore the very silence the state exists to break).
    """
    out = set()
    for e in errors:
        if not isinstance(e, dict):
            continue
        etype = e.get("type")
        name = etype[0] if isinstance(etype, list) and etype else etype
        if isinstance(name, str) and "PartialParsing" in name:
            path = e.get("path")
            if path:
                out.add(path)
            for loc in e.get("spans") or []:
                if isinstance(loc, dict) and loc.get("file"):
                    out.add(loc["file"])
    return out


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
    # The operand is the DIRECTORY, and it stays the directory (internal tracker #361 / Q-011).
    # semgrep's built-in default ignore list eats test/, tests/, testsuite/ and
    # *_test.go before discovery and leaves them out of `paths.skipped`, so those
    # files are invisibly unscanned. An explicitly named FILE bypasses that list;
    # a named directory does NOT (measured — naming <root>/tests recovers nothing).
    # So the directory operand keeps doing everything it does today and
    # `_default_ignored_targets` names only what it cannot see. Phase 189's
    # withdrawn fix replaced the directory instead of supplementing it, which is
    # what made it worse than the defect; that function's docstring answers each
    # condition its round raised.
    ignored_targets, over_budget, recovery_failed = _default_ignored_targets(
        repo_root, fixtures_exclude)
    try:
        r = subprocess.run(
            ["semgrep", "scan", "--config", semgrep_dir,
             "--exclude", fixtures_exclude,
             "--json", "--metrics=off", "--quiet", repo_root]
            + ignored_targets,
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
    # internal tracker #362 — an unattributed count made a partly-scanned file read as a clean one.
    # The paths are already in the JSON; name them, and record the stage as DEGRADED
    # so "0 findings" for those files is not reported as evidence of absence.
    partial = sorted(_partial_parse_paths(errors))
    if errors:
        print(f"warn: semgrep reported {len(errors)} internal error(s) — "
              "findings may be incomplete", file=sys.stderr)
    if partial:
        shown = ", ".join(partial[:5]) + ("…" if len(partial) > 5 else "")
        print(f"warn: semgrep could not fully parse {len(partial)} file(s) — the "
              f"unparsed regions were NOT scanned: {shown}", file=sys.stderr)

    # NO SHORTFALL COUNTER, deliberately. Phase 189 built one and its round measured
    # it firing 100% false-positive: `paths.scanned` counts files semgrep ANALYSED, not
    # files it received, so 367 targets produce 187 scanned here and the 180 "missing" are
    # .md/.json/.sh/.yaml that no loaded rule has a language for. Marking the stage
    # `degraded` on every run is a status that does not mean what it says — the exact
    # class that work exists to remove. `over_budget` below is a different number and is
    # safe to report because it counts files this module DECIDED not to name, not files
    # semgrep declined to analyse — a known quantity, not an inferred one.
    if over_budget:
        print(f"warn: {over_budget} test file(s) exceeded the semgrep operand "
              f"budget and were NOT scanned — the default ignore list hides them "
              f"and the command line could not carry them", file=sys.stderr)
    # SCOPED DELIBERATELY. This says the RECOVERY did not run; it does NOT say
    # the scan found nothing. `repo_root` is passed as an operand unconditionally
    # above, so a failed recovery yields precisely the pre-recovery whole-tree
    # directory scan — byte-identical argv — and changes no scanned file. The
    # loss is the supplementary test files the default ignore list hides, and
    # claiming more than that would be the same overclaim this warning exists to
    # remove.
    if recovery_failed:
        print("warn: git could not enumerate this repository, so the test files "
              "semgrep's default ignore list hides were NOT added to the scan "
              "(the whole-tree scan itself is unaffected). A corrupted index, a "
              "permission problem, or a git timeout will do this.",
              file=sys.stderr)
    if partial:
        detail = (f"{len(partial)} file(s) partially parsed, unparsed regions not "
                  f"scanned: {shown}")
        if over_budget:
            detail += (f"; {over_budget} test file(s) omitted over the operand "
                       f"budget")
        _record(DEGRADED, "partial-parse", detail)
    elif over_budget:
        _record(DEGRADED, "targets-over-budget",
                f"{over_budget} test file(s) omitted over the operand budget — "
                f"semgrep's default ignore list hides them and they could not fit "
                f"on the command line")
    elif recovery_failed:
        _record(DEGRADED, "targets-unenumerable",
                "git could not enumerate the repository, so the test files "
                "hidden by semgrep's default ignore list were not added to the "
                "scan; the whole-tree scan itself ran normally")
    else:
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
