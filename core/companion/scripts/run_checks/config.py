"""Checks-registry parsing and mode filtering."""
import fnmatch
import os
import sys

try:
    import yaml
except ImportError:
    print(
        "ERROR: run_checks requires PyYAML. "
        "Install: pip install pyyaml  (or activate the project venv).",
        file=sys.stderr,
    )
    sys.exit(2)

from _log import _sanitize_log


# Directories that are never source-of-interest. Used by both `run_grep`
# (passed to grep --exclude-dir) and `_iter_check_files` (filtered out of
# os.walk). Keep these in lockstep — divergence between the two scan paths
# was a real bug fixed by hoisting this to module scope.
_SKIP_DIRS = (
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    ".next",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "htmlcov",
)


def parse_checks_yml(path):
    """Parse .claude/checks.yml via PyYAML's safe_load.

    An earlier hand-rolled parser only recognized inline list syntax
    (``["a", "b"]``); block-style ``- item`` lists parsed as empty strings
    and silently disabled every grep check that used one (the fresh-consumer
    correctness bug this fix closes). PyYAML handles both shapes natively,
    plus folded/quoted multi-line scalars.

    Returns the ``checks`` list from the YAML document. Each entry is a dict;
    ``_validate_check`` enforces the required-field and list-shape invariants
    so a typo (missing ``id``) or a misindentation that collapses a block
    list into a scalar raises rather than silently no-ops.
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(
                f"checks.yml YAML parse error: {_sanitize_log(str(e))}"
            ) from None

    if not isinstance(data, dict):
        raise ValueError(
            "checks.yml: top-level YAML must be a mapping with a 'checks:' "
            f"key, got {type(data).__name__}"
        )

    checks = data.get("checks") or []
    if not isinstance(checks, list):
        raise ValueError(
            f"checks.yml: 'checks' must be a list, got {type(checks).__name__}"
        )

    for idx, check in enumerate(checks):
        if not isinstance(check, dict):
            raise ValueError(
                f"checks.yml: check[{idx}] must be a mapping, "
                f"got {type(check).__name__}"
            )
        _validate_check(check, idx)

    return checks


def _validate_check(check, idx):
    """Raise ValueError when a parsed check is missing required fields or has
    a wrong-shape list field.

    Without this guard, a typo in `.claude/checks.yml` (e.g. `- id :`) would
    silently produce a check dict with an empty id that downstream filtering
    skips, hiding the typo until someone wonders why the rule never fires.
    The list-shape assertion is the other half of the block-style-list fix:
    a `paths:` (or `include`/`exclude`/`used_by`) that arrives as a scalar
    instead of a list — e.g. a misindentation collapsing a block list — would
    make `run_check` silently no-op. Assert the shape so future regressions
    noisy-fail rather than silent-skip.

    ``critical_path`` is validated alongside the other scope fields: it is
    consumer-authored (never installer-substituted) and hand-edited, so the
    "forgot the YAML list" mistake (`critical_path: billing/`) is an expected
    input. Left unvalidated, a scalar string char-splits into single-character
    globs — which the pre-scan accounting layer then reads as a *localized*
    scope and marks with a spurious `⚠ BLOCKING CHECK DID NOT RUN`, and a
    scalar int crashes `RunReport` construction outright. Noisy-fail at parse.
    """
    cid = check.get("id", "")
    if not cid:
        raise ValueError(
            f"Invalid check at index {idx}: missing or empty 'id' field"
        )

    for fld in ("paths", "include", "exclude", "exclude_dir", "used_by",
                "critical_path"):
        if fld in check and check[fld] is not None and not isinstance(
            check[fld], list
        ):
            raise ValueError(
                f"Invalid check '{cid}': field '{fld}' must be a list, "
                f"got {type(check[fld]).__name__}"
            )


def path_in_scope(rel_path, paths):
    """True when ``rel_path`` falls under any checks.yml ``paths:`` entry.

    The tool-shelling stages (semgrep, pyright/tsc) scan the whole tree in one
    subprocess, so their per-check ``paths:`` scoping is applied by
    post-filtering each finding through this helper (Phase 133 — narrowing a
    semgrep/pyright check's ``paths:`` in the overlay used to be a silent
    no-op; the leg-5 dogfood hit exactly that). Entries are literal
    file-or-directory roots, not globs; an absent/empty list means whole-tree
    (backward compatible). A sentinel entry that matches nothing
    (``__disabled_no_op__``) therefore silences the check — the same overlay
    disabling shape the grep stage already supports.

    Callers pass the SCOPING list from ``check_paths_by_id`` — unlocalized
    ``<placeholder>`` entries are stripped there, so a shipped-but-not-yet-
    localized entry keeps its pre-133 whole-tree behavior rather than
    silently disabling the stage on every fresh install.
    """
    if not paths:
        return True
    rp = str(rel_path).replace(os.sep, "/")
    for p in paths:
        p = str(p).strip()
        if p.startswith("./"):
            p = p[2:]
        p = p.rstrip("/")
        if p in ("", "."):
            # A repo-root entry ("." / "./" / "/") is a valid whole-tree root
            # to the grep stage — treat it the same here rather than silently
            # matching nothing (a natural substitution value for a small repo
            # whose whole tree is source).
            return True
        if rp == p or rp.startswith(p + "/"):
            return True
    return False


def finding_in_scope(rel_path, scope):
    """True when a finding at ``rel_path`` survives a check's scope filters.

    ``scope`` is one value from ``check_paths_by_id``: ``paths`` roots are
    applied via ``path_in_scope``, then ``exclude_dir`` directory-basename
    globs drop findings under a matching path component at any depth — the
    same grep ``--exclude-dir`` semantics the grep stage applies, so an
    overlay ``exclude_dir:`` narrows every stage uniformly, not just grep.
    """
    rp = str(rel_path).replace(os.sep, "/")
    if not path_in_scope(rp, scope.get("paths") or []):
        return False
    exclude_dirs = scope.get("exclude_dir") or []
    if exclude_dirs:
        for seg in rp.split("/")[:-1]:  # directory components only
            if any(fnmatch.fnmatch(seg, xd) for xd in exclude_dirs):
                return False
    return True


def check_paths_by_id(included):
    """Normalize a stage's ``included`` collection to {check_id: scope}.

    Each scope is ``{"paths": scoping_paths, "exclude_dir": globs}`` for
    ``finding_in_scope``. ``_classify_checks`` hands the tool-shelling stages
    full check dicts keyed by id (so ``paths:``/``exclude_dir:`` scoping is
    available); the legacy public surface (``run_checks_impl`` re-exports,
    older tests) still passes plain id sets. Membership tests work on both;
    a set normalizes to "no scoping declared" (whole-tree), preserving the
    pre-133 behavior for legacy callers.

    Unlocalized angle-bracket placeholders (``<api module>/`` — shipped pack
    vocabulary the consumer hasn't substituted yet) are STRIPPED from the
    scoping list: they mean "not yet localized", not "match nothing". With
    them stripped, a fully-placeholder list stays whole-tree, a partially
    localized list scopes to its localized entries, and the deliberate
    ``__disabled_no_op__`` sentinel — no angle brackets — still scopes the
    check to nothing (the disable shape). This is the difference from the
    grep stage, which skips a check whose paths resolve to nothing on disk:
    grep checks are BORN placeholder-scoped and inert until localized, but
    the tool-shelling stages have always scanned whole-tree, and going inert
    on unlocalized installs would silently kill their findings everywhere.
    """
    def _scope(spec):
        if not isinstance(spec, dict):
            return {"paths": [], "exclude_dir": []}
        return {
            "paths": [
                p for p in (spec.get("paths") or [])
                if "<" not in str(p) and ">" not in str(p)
            ],
            "exclude_dir": list(spec.get("exclude_dir") or []),
        }

    if isinstance(included, dict):
        return {cid: _scope(spec) for cid, spec in included.items()}
    return {cid: {"paths": [], "exclude_dir": []} for cid in included}


def filter_checks(checks, mode):
    """Filter checks by mode (quality/security/both).

    Retained on the ``run_checks_impl`` back-compat re-export surface. The
    in-package run path does its own single-pass mode+baseline classification
    in ``cli._classify_checks``, so this helper is exercised only by tests
    today — but it is kept as stable public API for any consumer importing it
    directly (``from run_checks_impl import filter_checks``), not marked
    internal.
    """
    if mode == "both":
        return checks

    mode_map = {"quality": "codebase-review", "security": "security-audit"}
    target = mode_map.get(mode)
    if not target:
        return checks

    return [c for c in checks if target in c.get("used_by", [])]
