"""The review skills' "skip patterns already in checks.yml" lists name real checks.

WHY (Phase 396, `Q-252`). `/codebase-review` and `/security-audit` tell the
agent to skip grep amplification when a pre-scan check already covers a
pattern, and give example check ids. Retiring `error-display-jsx` left it in
`/codebase-review`'s list, naming a check no install carries, and nothing
noticed: no test read those ids. A retired or renamed check now reddens here.

Every backticked token in a list must be a shipped check id, a generated
family `run_checks` emits (`pyright-*`), or one of the named pattern targets
`/security-audit` pairs an id with (`for max_output_tokens`). Anything else
fails, so a rename to any spelling reddens, not only a kebab-case one. The list
body ends at the parenthesis that closes it, so a parenthetical inside the list
cannot cut it short.
"""
import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests"))
from skill_runner_text import skill_text  # noqa: E402

SKILLS = ("codebase-review", "security-audit")
ANCHOR = "if a check already covers the pattern (e.g., "
# The patterns `/security-audit`'s list names after `for`; not check ids.
PATTERN_TARGETS = {"max_output_tokens", "follow_redirects"}
# The families run_checks names at runtime rather than in a fragment
# (`run_checks/cli.py`, `run_checks/grep.py`).
GENERATED = ("pyright-", "tsc-", "lint-", "pip-audit-", "coverage-", "semgrep-")


def _shipped_ids() -> set[str]:
    frags = [REPO_ROOT / "core" / "companion" / "checks.yml.fragment"]
    frags += sorted((REPO_ROOT / "packs").glob("*/companion/checks.yml.fragment"))
    ids = set()
    for f in frags:
        if f.exists():
            for c in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("checks") or []:
                ids.add(c["id"])
    return ids


def _example_ids(skill: str) -> list[str]:
    text = skill_text(REPO_ROOT / "core" / "skills" / skill)
    assert text.count(ANCHOR) == 1, f"{skill}: expected one skip-list anchor"
    start = end = text.index(ANCHOR) + len(ANCHOR)
    depth = 1
    while depth:
        assert end < len(text), f"{skill}: the skip list's parenthesis never closes"
        depth += {"(": 1, ")": -1}.get(text[end], 0)
        end += 1
    return re.findall(r"`([^`]+)`", text[start:end - 1])


@pytest.mark.parametrize("skill", SKILLS)
def test_every_example_id_is_a_shipped_check(skill):
    shipped = _shipped_ids()
    ids = [t for t in _example_ids(skill) if t not in PATTERN_TARGETS]
    assert ids, f"{skill}: the skip list yielded no ids, so this test reads nothing"
    stale = [
        i for i in ids
        if not (i.endswith("*") and i[:-1] in GENERATED) and i not in shipped
    ]
    assert not stale, f"{skill}: example ids no shipped fragment declares: {stale}"


def test_the_retired_grep_check_stays_retired():
    """`Q-252`: the pack keeps the AST twin and not the grep check."""
    shipped = _shipped_ids()
    assert "semgrep-error-display-jsx" in shipped
    assert "error-display-jsx" not in shipped
