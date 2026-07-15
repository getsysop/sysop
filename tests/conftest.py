"""Sysop test suite shared fixtures.

Intentionally minimal — Sysop has no DB, no app process. Most tests
exercise pure functions or subprocess calls mocked at the boundary.
"""
import os
import shutil

import pytest

for _var in (
    "SLACK_WEBHOOK_URL",
    "PIPELINE_SLACK_WEBHOOK_URL",
    "PAGERDUTY_ROUTING_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
):
    os.environ.pop(_var, None)


def pytest_collection_modifyitems(config, items):
    skip_node = pytest.mark.skip(reason="npx/eslint not on PATH")
    skip_pip_audit = pytest.mark.skip(reason="pip-audit not on PATH")
    has_node = shutil.which("npx") is not None
    has_pip_audit = shutil.which("pip-audit") is not None
    for item in items:
        if item.get_closest_marker("requires_node") and not has_node:
            item.add_marker(skip_node)
        if item.get_closest_marker("requires_pip_audit") and not has_pip_audit:
            item.add_marker(skip_pip_audit)
