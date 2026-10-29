"""Sysop run-checks package.

Split from ``run_checks_impl.py`` in Phase 49 (2026-05-27). Each submodule
holds one stage of the pre-scan pipeline; ``cli`` wires them together.
A re-export shim remains at ``core/companion/scripts/run_checks_impl.py``
so existing callers (``run_checks.sh`` and the test suite) continue to
work without modification.
"""
