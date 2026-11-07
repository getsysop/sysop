"""Tests for ``core/companion/scripts/pr_dependabot.py``.

Sysop-original — Phase 53 (client-side Dependabot PR sweep). No gdp
counterpart; the classifier rules were validated against ~50 real Dependabot
PRs in gdp-query-system before being frozen here.

Scope. The pure classification core, which is the part that decides what gets
merged vs. closed vs. held — i.e. the part where a bug has real-world cost —
plus `execute`'s merge gate and the native auto-merge probe, driven through
`main` with `_gh` mocked. No test runs a real `gh`.

Surface covered:

- ``semver_bump`` — patch / minor / major boundaries, unparseable, ragged
  version strings, leading-`v` and pre-release noise.
- ``ci_state`` — green / failing / pending / none across rollup shapes.
- ``_publisher`` — org-prefix extraction.
- ``classify`` — every action branch: npm patch/minor merge, major hold,
  pip close, trusted vs untrusted Action publisher, grouped/unparseable
  surface, docker auto-merge, unrecognized ecosystem.
- ``mark_superseded`` — open-set duplicate collapse, single-PR no-op, the
  highest-target-wins rule, that closed-action PRs are excluded, and that PRs
  with no target version (unparseable or grouped titles) never collapse.
- ``probe_auto_merge`` / ``main`` — the three readings (allowed, not allowed,
  unknown), the `--json` field, the `--execute` second-actor line, and that a
  probe failure leaves the plan and the sweep as they were.
- ``SKILL.md`` — Step 2's question and the conditioned replacement section.
"""

from __future__ import annotations

from unittest import mock

import json
import re
from pathlib import Path

import pytest

# core/companion/scripts is on pythonpath (see pyproject.toml [tool.pytest]).
import pr_dependabot as prd

_SKILL = (Path(__file__).resolve().parents[1]
          / "core" / "skills" / "pr-dependabot" / "SKILL.md")


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


def test_mark_superseded_never_collapses_unparseable_titles():
    # Dependabot's default title has no `chore(<scope>):` prefix, so every PR on
    # a repo without a commit-message prefix keys as ('?', '?', None). Two
    # unrelated PRs must both stay `surface`; collapsing them would close one.
    plans = prd.build_plans([
        _pr("Bump lodash from 4.17.20 to 4.17.21", number=2),
        _pr("Bump axios from 1.0.0 to 1.0.1", number=1),
    ])
    assert [p.action for p in plans] == ["surface", "surface"]


def test_mark_superseded_never_collapses_grouped_titles():
    # Grouped titles key on their first package only and carry no target.
    plans = prd.build_plans([
        _pr("chore(npm): bump react and @types/react in /frontend", number=9),
        _pr("chore(npm): bump react and react-dom in /frontend", number=8),
    ])
    assert [p.action for p in plans] == ["surface", "surface"]


# ── native auto-merge probe ──────────────────────────────────────
#
# `_gh` is mocked with a side effect keyed on the command: the GraphQL probe,
# the PR list, and (under --execute) the merge. The probe must never pass a
# repo to `_gh`, because `_gh` appends it as `-R`, which `gh api` rejects.


_OPEN_PRS = [
    {"number": 1, "title": "chore(npm): bump x from 1.0.0 to 1.0.1 in /frontend",
     "url": "u/1", "state": "OPEN", "statusCheckRollup": [],
     "mergeable": "UNKNOWN"},
]


def _graphql(value):
    return json.dumps({"data": {"repository": {"autoMergeAllowed": value}}})


def _fake_gh(probe, prs=_OPEN_PRS):
    """`probe` is the GraphQL stdout, or an exception to raise."""
    calls = []

    def fake(args, repo):
        calls.append((list(args), repo))
        if args[:2] == ["api", "graphql"]:
            if isinstance(probe, BaseException):
                raise probe
            return probe
        if args[:2] == ["pr", "list"]:
            return json.dumps(prs)
        return ""
    return fake, calls


def _run(argv, probe, capsys, prs=_OPEN_PRS):
    fake, calls = _fake_gh(probe, prs)
    with mock.patch("pr_dependabot._gh", side_effect=fake), \
         mock.patch("pr_dependabot._resolve_mergeable",
                    return_value=("MERGEABLE", "green")):
        rc = prd.main(argv)
    out = capsys.readouterr().out
    return rc, out, calls


def _probe_calls(calls):
    return [c for c in calls if c[0][:2] == ["api", "graphql"]]


@pytest.mark.parametrize("probe,state,reason_part", [
    (_graphql(True), "allowed", ""),
    (_graphql(False), "not allowed", ""),
    (_graphql(None), "unknown", "null"),
    ("not json", "unknown", "did not carry"),
    (json.dumps({"data": {"repository": None}}), "unknown", "did not carry"),
    (json.dumps({"data": {}}), "unknown", "did not carry"),
    (RuntimeError("`gh api graphql` failed: HTTP 401"), "unknown", "HTTP 401"),
    (FileNotFoundError("gh"), "unknown", "gh could not read it"),
])
def test_probe_auto_merge_readings(probe, state, reason_part):
    fake, _ = _fake_gh(probe)
    with mock.patch("pr_dependabot._gh", side_effect=fake):
        reading = prd.probe_auto_merge("o/r")
    assert reading.state == state
    assert reason_part in reading.reason
    if state != "unknown":
        assert reading.reason == ""


@pytest.mark.parametrize("repo,expected", [
    (None, ["-F", "owner={owner}", "-F", "name={repo}"]),
    ("cli/cli", ["-f", "owner=cli", "-f", "name=cli"]),
    ("https://github.com/cli/cli", ["--hostname", "github.com", "-f", "owner=cli",
                                    "-f", "name=cli"]),
    ("https://ghe.example/o/r.git", ["--hostname", "ghe.example", "-f", "owner=o",
                                     "-f", "name=r"]),
    ("ghe.example/o/r", ["--hostname", "ghe.example", "-f", "owner=o",
                         "-f", "name=r"]),
])
def test_probe_names_the_repo_in_the_request_not_with_dash_r(repo, expected):
    fake, calls = _fake_gh(_graphql(True))
    with mock.patch("pr_dependabot._gh", side_effect=fake):
        prd.probe_auto_merge(repo)
    (args, passed_repo), = _probe_calls(calls)
    assert passed_repo is None, "gh api takes no -R; the repo must not reach _gh"
    assert "-R" not in args
    assert args[2:2 + len(expected)] == expected
    assert any(a.startswith("query=") and "autoMergeAllowed" in a for a in args)


@pytest.mark.parametrize("repo", ["justaname", "a/b/c/d", "o/"])
def test_probe_malformed_repo_is_unknown_without_calling_gh(repo):
    fake, calls = _fake_gh(_graphql(True))
    with mock.patch("pr_dependabot._gh", side_effect=fake):
        reading = prd.probe_auto_merge(repo)
    assert reading.state == "unknown"
    assert _probe_calls(calls) == []


def test_plan_header_reads_allowed_with_second_actor_line(capsys):
    rc, out, _ = _run(["--repo", "o/r"], _graphql(True), capsys)
    assert rc == 0
    lines = out.splitlines()
    assert lines[0] == "PLANNED ACTIONS"
    assert lines[1].startswith("native auto-merge: allowed")
    assert "second merge actor" in lines[1]
    assert "dry-run — nothing changed" in out


def test_plan_header_reads_not_allowed(capsys):
    rc, out, _ = _run([], _graphql(False), capsys)
    assert rc == 0
    assert out.splitlines()[1] == (
        "native auto-merge: not allowed — this sweep is the merge actor.")
    assert "second merge actor" not in out


def test_probe_failure_is_unknown_and_the_plan_still_prints(capsys):
    rc, out, _ = _run(["--repo", "o/r"],
                      RuntimeError("`gh api graphql` failed: boom"), capsys)
    assert rc == 0, "a probe failure must not stop the run"
    assert out.splitlines()[1].startswith("native auto-merge: unknown (")
    assert "boom" in out
    assert "#1" in out and "merge" in out
    assert "second merge actor" not in out


def test_empty_plan_still_prints_the_reading(capsys):
    rc, out, _ = _run([], _graphql(False), capsys, prs=[])
    assert rc == 0
    assert out.splitlines() == [
        "native auto-merge: not allowed — this sweep is the merge actor.",
        "No open Dependabot PRs. Nothing to sweep.",
    ]


@pytest.mark.parametrize("probe,state", [
    (_graphql(True), "allowed"),
    (_graphql(False), "not allowed"),
    (RuntimeError("`gh api graphql` failed: boom"), "unknown"),
])
def test_json_carries_the_reading(probe, state, capsys):
    rc, out, _ = _run(["--json"], probe, capsys)
    assert rc == 0
    data = json.loads(out)
    assert data["native_auto_merge"]["state"] == state
    assert [p["number"] for p in data["plans"]] == [1]


def test_execute_repeats_the_second_actor_line_and_still_merges(capsys):
    rc, out, calls = _run(["--execute", "--repo", "o/r"], _graphql(True),
                          capsys)
    assert rc == 0
    assert out.count("this sweep would be a second merge actor") == 2
    assert out.rstrip().splitlines()[-1].startswith("native auto-merge: allowed")
    assert (["pr", "merge", "1", "--squash"], "o/r") in calls


@pytest.mark.parametrize("probe", [
    _graphql(False), RuntimeError("`gh api graphql` failed: boom"),
])
def test_execute_without_allowed_runs_as_before(probe, capsys):
    rc, out, calls = _run(["--execute", "--repo", "o/r"], probe, capsys)
    assert rc == 0
    assert "second merge actor" not in out
    assert (["pr", "merge", "1", "--squash"], "o/r") in calls
    assert "✅ #1 merged" in out


def test_validate_does_not_probe(capsys):
    rc, _, calls = _run(["--validate"], _graphql(True), capsys)
    assert rc == 0
    assert _probe_calls(calls) == []


# ── SKILL.md routes on the reading ───────────────────────────────


def _section(text, heading):
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text,
                  re.M | re.S)
    assert m, f"SKILL.md lost its '## {heading}' section"
    return " ".join(m.group(1).split())   # phrases may wrap across lines


def test_skill_step2_asks_an_explicit_question_when_allowed():
    step2 = _section(_SKILL.read_text(),
                     "Step 2: Gate on human confirmation before executing")
    assert "The reading is `allowed`" in step2
    assert "explicit question" in step2
    assert "second merge actor" in step2
    assert "Merge with this skill anyway?" in step2


def test_skill_replacement_section_is_conditioned_on_the_reading():
    section = _section(_SKILL.read_text(),
                       "Replacing a server-side auto-merge workflow")
    allowed_at = section.find("When the reading is `allowed`, give no advice")
    retire_at = section.find("Retiring that workflow")
    otherwise_at = section.find("Otherwise (`not allowed` or `unknown`)")
    assert allowed_at != -1, "no no-retire-advice arm for `allowed`"
    assert otherwise_at != -1 and retire_at != -1
    assert allowed_at < otherwise_at < retire_at, (
        "the retire note must sit under the not-allowed/unknown arm")


def test_skill_step1_keeps_the_reading():
    step1 = _section(_SKILL.read_text(), "Step 1: Dry-run first — always")
    assert "`native auto-merge:`" in step1
    # An install whose skill updated before its scripts prints no line.
    assert "If the plan has no such line" in step1
    assert "treat the reading as `unknown`" in step1


def test_with_no_repo_the_probe_names_the_listed_prs_repo_and_host(capsys):
    """`gh api` fills `{owner}`/`{repo}` from the remote but asks its default host,
    while `gh pr list` asks the remote's host. With PRs listed, the probe names the
    repo and host they came from."""
    prs = [dict(_OPEN_PRS[0], url="https://ghe.example/o/r/pull/7")]
    _rc, _out, calls = _run([], _graphql(False), capsys, prs=prs)
    (args, _), = _probe_calls(calls)
    assert args[2:8] == ["--hostname", "ghe.example", "-f", "owner=o", "-f", "name=r"]


def test_a_versioned_grouped_title_never_supersedes():
    """`bump foo and bar from A to B` keys on `foo` alone; it is not a duplicate of
    a PR that bumps only `foo`."""
    plans = prd.build_plans([
        {"number": 10, "title": "chore(npm): bump foo and bar from 1.0.0 to 1.1.0",
         "state": "OPEN", "mergeable": "MERGEABLE", "statusCheckRollup": []},
        {"number": 11, "title": "chore(npm): bump foo from 1.0.0 to 1.2.0",
         "state": "OPEN", "mergeable": "MERGEABLE", "statusCheckRollup": []},
    ])
    assert "close-superseded" not in {p.action for p in plans}
