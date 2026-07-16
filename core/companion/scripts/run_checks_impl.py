"""Backwards-compat re-export shim for the ``run_checks`` package (Phase 49).

The implementation moved to ``run_checks/`` so the per-stage code lives in
focused modules (``config`` / ``grep`` / ``lsp`` / ``lint`` / ``pip_audit`` /
``semgrep`` / ``baseline`` / ``cli``). Existing callers continue to work:

* ``run_checks.sh`` invokes this file via ``python run_checks_impl.py`` —
  ``main()`` is re-exported below.
* Tests do ``import run_checks_impl as rci`` / ``from run_checks_impl import
  _run_eslint`` — every public and underscore-prefixed symbol from the
  package is re-exported here.
* Tests patch ``run_checks_impl.subprocess.run`` — the ``import subprocess``
  below keeps that attribute resolvable. Because ``subprocess`` is a singleton
  module, the patch applies to every submodule's calls.
"""
# `subprocess` is intentionally imported even though it isn't referenced
# below — the test suite patches `run_checks_impl.subprocess.run` and we
# preserve that attribute path.
import subprocess  # noqa: F401

from run_checks.baseline import (  # noqa: F401
    _is_coverage,
    finding_key,
    is_baseline_suppressed,
    load_baseline,
    write_baseline,
)
from run_checks.cli import _classify_checks, main  # noqa: F401
from run_checks.config import (  # noqa: F401
    _SKIP_DIRS,
    _validate_check,
    filter_checks,
    parse_checks_yml,
)
from run_checks.coverage import (  # noqa: F401
    _path_in_critical,
    _run_coverage,
    _run_diff_cover_check,
)
from run_checks.grep import (  # noqa: F401
    _POSITION_CHECK_RE_CACHE,
    _cached_compile,
    _first_match_line,
    _iter_check_files,
    _run_position_check,
    run_check,
    run_grep,
    strip_repo_prefix,
)
from run_checks.lint import (  # noqa: F401
    FrontendDirAmbiguous,
    _find_frontend_dir,
    _run_eslint,
)
from run_checks.lsp import (  # noqa: F401
    _TSC_HEADER_RE,
    _emit_tsc_finding,
    _pyright_rule_to_check_id,
    _run_pyright,
    _run_tsc,
    run_lsp_diagnostics,
)
from run_checks.pip_audit import (  # noqa: F401
    _find_requirements_files,
    _run_pip_audit,
)
from run_checks.semgrep import _run_semgrep  # noqa: F401


if __name__ == "__main__":
    main()
