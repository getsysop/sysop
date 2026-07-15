"""Tests for ``core/companion/scripts/pr_dependabot.py``.

Sysop-original — Phase 53 (client-side Dependabot PR sweep). No gdp
counterpart; the classifier rules were validated against ~50 real Dependabot
PRs in gdp-query-system before being frozen here.

Scope. The pure classification core, which is the part that decides what gets
merged vs. closed vs. held — i.e. the part where a bug has real-world cost. The
`gh` shell-out (`_gh`, `_list_prs`, `_resolve_mergeable`, `execute`) is a thin
subprocess wrapper deferred to manual/dry-run verification, consistent with how
the suite treats other network/subprocess boundaries.

Surface covered:

- ``semver_bump`` — patch / minor / major boundaries, unparseable, ragged
  version strings, leading-`v` and pre-release noise.
- ``ci_state`` — green / failing / pending / none across rollup shapes.
- ``_publisher`` — org-prefix extraction.
- ``classify`` — every action branch: npm patch/minor merge, major hold,
  pip close, trusted vs untrusted Action publisher, grouped/unparseable
  surface, docker auto-merge, unrecognized ecosystem.
- ``mark_superseded`` — open-set duplicate collapse, single-PR no-op, the
  highest-target-wins rule, and that closed-action PRs are excluded.
"""

from __future__ import annotations

from unittest import mock

import pytest

# core/companion/scripts is on pythonpath (see pyproject.toml [tool.pytest]).
import pr_dependabot as prd


# ── semver_bump ──────────────────────────────────────────────────


@pytest.mark.parametrize("frm,to,expected", [
    ("25.9.1", "25.9.2", "patch"),
    ("12.13.0", "12.14.0", "minor"),
    ("9.39.4", "10.4.0", "major"),
    ("1.1.5", "1.2.0", "minor"),
    ("4.2.4", "4.3.0", "minor"),
    ("19.2.5", "19.2.6", "patch"),
    ("2.3.9", "3.0.0", "major"),
    ("0.2.5", "0.2.7", "patch"),     # 0.x — still patch by position
    ("v1.0.0", "v2.0.0", "major"),   # leading v tolerated
    ("1.0", "1.1", "minor"),          # ragged (missing patch) -> minor
    ("1", "2", "major"),              # single-component
])
def test_semver_bump_levels(frm, to, expected):
    assert prd.semver_bump(frm, to) == expected


@pytest.mark.parametrize("frm,to", [
    (None, "1.0.0"), ("1.0.0", None), (None, None), ("", ""),
])
def test_semver_bump_unparseable_returns_none(frm, to):
    assert prd.semver_bump(frm, to) is None


# ── ci_state ─────────────────────────────────────────────────────


def _check(conclusion, status="COMPLETED"):
    return {"conclusion": conclusion, "status": status}


def test_ci_state_none_when_empty():
    assert prd.ci_state(None) == "none"
    assert prd.ci_state([]) == "none"


def test_ci_state_green_all_success():
    assert prd.ci_state([_check("SUCCESS"), _check("SUCCESS")]) == "green"


def test_ci_state_green_tolerates_neutral_and_skipped():
    assert prd.ci_state([_check("SUCCESS"), _check("NEUTRAL"),
                         _check("SKIPPED")]) == "green"


def test_ci_state_failing_on_any_failure():
    assert prd.ci_state([_check("SUCCESS"), _check("FAILURE")]) == "failing"


def test_ci_state_failing_on_cancelled_or_timeout():
    assert prd.ci_state([_check("CANCELLED")]) == "failing"
    assert prd.ci_state([_check("TIMED_OUT")]) == "failing"


def test_ci_state_pending_when_a_check_still_running():
    running = {"conclusion": None, "status": "IN_PROGRESS"}
    assert prd.ci_state([_check("SUCCESS"), running]) == "pending"


def test_ci_state_legacy_state_field_failing():
    # Commit-status / StatusContext rollup entries carry `state`, not
    # `conclusion` — the `or c.get("state")` fallback must read it. FAILURE (not
    # SUCCESS) is the mutation-catching value: dropping the fallback yields
    # conclusion=None, which is green-compatible, so a SUCCESS case wouldn't flip.
    assert prd.ci_state([{"state": "FAILURE"}]) == "failing"


def test_ci_state_legacy_state_field_green():
    assert prd.ci_state([{"state": "SUCCESS"}]) == "green"


def test_ci_state_terminal_pending_for_unknown_conclusion():
    # COMPLETED (skips the in-loop pending early-return) with a conclusion in
    # neither the failing nor the green set → the terminal `return "pending"`.
    assert prd.ci_state([{"conclusion": "ACTION_REQUIRED",
                          "status": "COMPLETED"}]) == "pending"


# ── _publisher ───────────────────────────────────────────────────


def test_publisher_extracts_org_prefix():
    assert prd._publisher("actions/checkout") == "actions"
    assert prd._publisher("peter-evans/create-pull-request") == "peter-evans"


def test_publisher_no_slash_returns_whole():
    assert prd._publisher("vitest") == "vitest"


# ── classify ─────────────────────────────────────────────────────


def _pr(title, number=1, rollup=None, mergeable="UNKNOWN", state="OPEN"):
    return {"number": number, "title": title, "url": f"u/{number}",
            "state": state, "statusCheckRollup": rollup or [],
            "mergeable": mergeable}


def test_classify_npm_patch_merges():
    p = prd.classify(_pr("chore(npm): bump @types/node from 25.9.1 to 25.9.2 in /frontend"))
    assert p.action == "merge"
    assert p.ecosystem == "npm" and p.bump == "patch"
    assert p.directory == "frontend"


def test_classify_npm_minor_merges():
    p = prd.classify(_pr("chore(npm): bump firebase from 12.13.0 to 12.14.0 in /frontend"))
    assert p.action == "merge" and p.bump == "minor"


def test_classify_npm_major_holds():
    p = prd.classify(_pr("chore(npm): bump eslint from 9.39.4 to 10.4.0 in /frontend"))
    assert p.action == "hold" and p.bump == "major"


def test_classify_pip_closes():
    p = prd.classify(_pr("chore(deps): bump idna from 3.13 to 3.15"))
    assert p.action == "close-pip" and p.ecosystem == "pip"


def test_classify_pip_major_still_closes_not_holds():
    # pip is closed regardless of bump — pip-compile owns Python deps.
    p = prd.classify(_pr("chore(deps): bump urllib3 from 1.26.0 to 2.0.0"))
    assert p.action == "close-pip"


def test_classify_trusted_action_patch_merges():
    p = prd.classify(_pr("chore(actions): bump actions/checkout from 6.0.2 to 6.0.3"))
    assert p.action == "merge" and p.ecosystem == "github-actions"


def test_classify_trusted_action_major_holds():
    # The validation's key bug: a trusted-publisher MAJOR must not auto-merge.
    p = prd.classify(_pr("chore(actions): bump gitleaks/gitleaks-action from 2.3.9 to 3.0.0"))
    assert p.action == "hold" and p.bump == "major"


def test_classify_untrusted_action_surfaces():
    p = prd.classify(_pr("chore(actions): bump sketchy-org/some-action from 1.0.0 to 1.0.1"))
    assert p.action == "surface"
    assert "untrusted" in p.reason


def test_classify_grouped_title_surfaces():
    # No from/to in the title (Dependabot grouped/security update).
    p = prd.classify(_pr("chore(npm): bump react and @types/react in /frontend"))
    assert p.action == "surface" and p.bump is None


def test_classify_unparseable_title_surfaces():
    p = prd.classify(_pr("Merge branch main into feature"))
    assert p.action == "surface" and p.ecosystem == "?"


def test_classify_docker_patch_merges():
    p = prd.classify(_pr("chore(docker): bump python from 3.12.1 to 3.12.2"))
    assert p.action == "merge" and p.ecosystem == "docker"


def test_classify_carries_ci_and_mergeable():
    p = prd.classify(_pr("chore(npm): bump x from 1.0.0 to 1.0.1 in /frontend",
                         rollup=[_check("SUCCESS")], mergeable="MERGEABLE"))
    assert p.ci == "green" and p.mergeable == "MERGEABLE"


# ── mark_superseded ──────────────────────────────────────────────


def test_mark_superseded_collapses_open_duplicates():
    plans = prd.build_plans([
        _pr("chore(npm): bump @types/node from 25.6.0 to 25.6.2 in /frontend", number=140),
        _pr("chore(npm): bump @types/node from 25.6.2 to 25.9.1 in /frontend", number=164),
    ])
    by_num = {p.number: p for p in plans}
    assert by_num[164].action == "merge"            # highest target wins
    assert by_num[140].action == "close-superseded"  # older loses
    assert "#164" in by_num[140].reason


def test_mark_superseded_single_pr_is_noop():
    plans = prd.build_plans([
        _pr("chore(npm): bump vitest from 4.1.7 to 4.1.8 in /frontend", number=174),
    ])
    assert plans[0].action == "merge"


def test_mark_superseded_distinct_dirs_not_duplicates():
    # Same package in /frontend vs /e2e are independent — both merge.
    plans = prd.build_plans([
        _pr("chore(npm): bump @types/node from 25.9.1 to 25.9.2 in /frontend", number=188),
        _pr("chore(npm): bump @types/node from 25.9.1 to 25.9.2 in /e2e", number=185),
    ])
    assert all(p.action == "merge" for p in plans)


def test_mark_superseded_excludes_closed_actions():
    # A pip close + an npm bump of an unrelated pkg never group.
    plans = prd.build_plans([
        _pr("chore(deps): bump idna from 3.13 to 3.15", number=158),
        _pr("chore(npm): bump idna from 3.13 to 3.15 in /frontend", number=159),
    ])
    by_num = {p.number: p for p in plans}
    assert by_num[158].action == "close-pip"
    assert by_num[159].action == "merge"   # different ecosystem, not superseded


# ── execute (merge safety gate) ──────────────────────────────────
#
# execute() re-resolves CI + mergeable state *fresh* (via _resolve_mergeable)
# right before actuating, and refuses to `gh pr merge` unless CI is green AND
# the PR is MERGEABLE. Both boundaries (_resolve_mergeable, _gh) are mocked so
# no real `gh` runs; the tests lock the two `continue` guards that stand between
# a bot PR and an unattended merge.


def _merge_plan():
    return prd.classify(
        _pr("chore(npm): bump x from 1.0.0 to 1.0.1 in /frontend", number=1))


def _merge_calls(mock_gh):
    return [c for c in mock_gh.call_args_list if "merge" in c.args[0]]


def test_execute_merges_when_green_and_mergeable():
    p = _merge_plan()
    with mock.patch("pr_dependabot._resolve_mergeable",
                    return_value=("MERGEABLE", "green")), \
         mock.patch("pr_dependabot._gh") as mock_gh:
        results = prd.execute([p], None)
    mock_gh.assert_called_once_with(["pr", "merge", "1", "--squash"], None)
    assert any("merged" in r for r in results)


def test_execute_skips_merge_when_ci_not_green():
    p = _merge_plan()
    with mock.patch("pr_dependabot._resolve_mergeable",
                    return_value=("MERGEABLE", "failing")), \
         mock.patch("pr_dependabot._gh") as mock_gh:
        results = prd.execute([p], None)
    assert _merge_calls(mock_gh) == [], "merged a PR with non-green CI"
    assert any("skip — CI not green" in r for r in results)


def test_execute_skips_merge_when_not_mergeable():
    p = _merge_plan()
    with mock.patch("pr_dependabot._resolve_mergeable",
                    return_value=("CONFLICTING", "green")), \
         mock.patch("pr_dependabot._gh") as mock_gh:
        results = prd.execute([p], None)
    assert _merge_calls(mock_gh) == [], "merged a non-mergeable PR"
    assert any("skip — not mergeable" in r for r in results)


def test_execute_skips_merge_when_ci_pending():
    p = _merge_plan()
    with mock.patch("pr_dependabot._resolve_mergeable",
                    return_value=("MERGEABLE", "pending")), \
         mock.patch("pr_dependabot._gh") as mock_gh:
        results = prd.execute([p], None)
    assert _merge_calls(mock_gh) == []
    assert any("skip — CI not green" in r for r in results)


def test_execute_close_pip_calls_gh_close_without_resolving():
    p = prd.classify(_pr("chore(deps): bump idna from 3.13 to 3.15", number=1))
    assert p.action == "close-pip"
    with mock.patch("pr_dependabot._resolve_mergeable") as mock_resolve, \
         mock.patch("pr_dependabot._gh") as mock_gh:
        prd.execute([p], None)
    mock_resolve.assert_not_called()  # close path never checks mergeability
    assert any("close" in c.args[0] for c in mock_gh.call_args_list)


def test_execute_hold_is_a_noop():
    p = prd.classify(_pr("chore(npm): bump eslint from 9.39.4 to 10.4.0 in /frontend"))
    assert p.action == "hold"
    with mock.patch("pr_dependabot._gh") as mock_gh:
        results = prd.execute([p], None)
    assert mock_gh.call_count == 0
    assert results == []
