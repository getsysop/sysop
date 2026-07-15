"""Smoke tests — confirm the three load-bearing scripts import cleanly.

These exist primarily to guard against import-time breakage (syntax errors,
top-level statements that crash). Behaviour tests live in their own files.
"""


def test_imports_next_task():
    import next_task  # noqa: F401


def test_imports_validate_tasks():
    import validate_tasks  # noqa: F401


def test_imports_run_checks_impl():
    import run_checks_impl  # noqa: F401
