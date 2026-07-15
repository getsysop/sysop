"""Checks-registry parsing and mode filtering."""
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
    """
    cid = check.get("id", "")
    if not cid:
        raise ValueError(
            f"Invalid check at index {idx}: missing or empty 'id' field"
        )

    for fld in ("paths", "include", "exclude", "used_by"):
        if fld in check and check[fld] is not None and not isinstance(
            check[fld], list
        ):
            raise ValueError(
                f"Invalid check '{cid}': field '{fld}' must be a list, "
                f"got {type(check[fld]).__name__}"
            )


def filter_checks(checks, mode):
    """Filter checks by mode (quality/security/both)."""
    if mode == "both":
        return checks

    mode_map = {"quality": "codebase-review", "security": "security-audit"}
    target = mode_map.get(mode)
    if not target:
        return checks

    return [c for c in checks if target in c.get("used_by", [])]
