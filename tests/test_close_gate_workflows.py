"""The close gate's two workflow templates and its requirements file (Phase 374; spec § 10.3).

They ship unarmed beside the CI template. What these lock is the shape § 10.3 item 3 requires of
anything that holds the gate app's key: the default branch's copy only, nothing from the pull
request executed, no event field interpolated into a `run:` step, pinned actions, a
hash-pinned dependency installed outside the checkout, and Python always with `-I`.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from test_ci_template import _install, _seed_consumer

CI = Path(__file__).resolve().parents[1] / "core" / "companion" / "ci"
GATE = CI / "sysop-close-gate.yml.example"
RELAY = CI / "sysop-close-gate-relay.yml.example"
REQS = CI / "close-gate-requirements.txt"


def _load(p: Path) -> dict:
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))  # YAML 1.1 reads a bare `on:` key as True
    return data


def _runs(p: Path) -> list[str]:
    return [s["run"] for job in _load(p)["jobs"].values() for s in job.get("steps", []) if "run" in s]


def test_the_gate_runs_only_from_the_default_branchs_context() -> None:
    on = _load(GATE)["on"]
    assert set(on) == {"pull_request_target", "issue_comment", "push", "workflow_run"}
    assert on["workflow_run"]["workflows"] == [_load(RELAY)["name"]]
    assert "pull_request" not in on and "workflow_dispatch" not in on and "repository_dispatch" not in on


def test_the_gate_job_holds_the_key_through_the_environment_only() -> None:
    wf = _load(GATE)
    assert wf["permissions"] == {}
    job = wf["jobs"]["gate"]
    assert job["environment"] == "sysop-close-gate" and job["permissions"] == {"contents": "read"}
    assert job["runs-on"] == "ubuntu-24.04"  # a fixed image keeps the hash-pinned wheel set fixed
    text = GATE.read_text(encoding="utf-8")
    assert "secrets.SYSOP_GATE_APP_KEY" in text and "vars.SYSOP_GATE_CLIENT_ID" in text
    assert text.count("secrets.") == 1


def test_no_event_field_reaches_a_run_step() -> None:
    for p in (GATE, RELAY):
        for run in _runs(p):
            assert "${{" not in run, f"{p.name}: an expression inside run: {run[:80]!r}"


def test_nothing_from_the_checkout_is_imported_or_cached() -> None:
    text = GATE.read_text(encoding="utf-8")
    steps = _load(GATE)["jobs"]["gate"]["steps"]
    uses = [s["uses"] for s in steps if "uses" in s]
    assert all(re.search(r"@[0-9a-f]{40}$", u) for u in uses), uses
    assert not any(u.startswith("./") for u in uses)
    assert all("cache" not in (s.get("with") or {}) for s in steps)
    checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"] == {"fetch-depth": 0, "persist-credentials": False}
    # Every interpreter call: the venv's creation, pip, and the gate itself.
    pythons = re.findall(r'python"?\s+(\S+)', "\n".join(_runs(GATE)))
    assert pythons == ["-I", "-I", "-I"], pythons
    assert "--require-hashes" in text and "--only-binary :all:" in text and "--no-deps" in text
    assert "actions/download-artifact" not in text and "actions/cache" not in text


def test_the_gate_refuses_a_non_regular_gate_at_the_base() -> None:
    guard = next(r for r in _runs(GATE) if "is not a regular file at the base" in r)
    for name in ("close_gate.py", "close_run.py", "pending_doc_hold.py", "ci/close-gate-requirements.txt"):
        assert name in guard


def test_the_relay_carries_nothing_and_holds_nothing() -> None:
    wf = _load(RELAY)
    assert set(wf["on"]) == {"pull_request_review", "pull_request_review_comment"}
    assert wf["permissions"] == {}
    job = wf["jobs"]["relay"]
    assert "environment" not in job and "secrets." not in RELAY.read_text(encoding="utf-8")
    assert [s for s in job["steps"] if "uses" in s] == []


def test_the_requirements_pin_every_line_by_hash() -> None:
    lines = [l for l in REQS.read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#")]
    assert lines[0].startswith("pyyaml==") and all(
        re.fullmatch(r"\s*--hash=sha256:[0-9a-f]{64}(\s*\\)?", l) for l in lines[1:]), lines


def test_install_ships_the_gate_unarmed(tmp_path: Path) -> None:
    target = _seed_consumer(tmp_path / "consumer")
    _install(target, "--packs", "", "--no-arm-hooks")
    ci = target / "sysop" / "scripts" / "ci"
    for name in (GATE.name, RELAY.name, REQS.name):
        assert (ci / name).is_file(), name
    assert (target / "sysop" / "scripts" / "close_gate.py").is_file()
    assert not (target / ".github" / "workflows").exists()


def test_loop_mode_ships_no_gate_files(tmp_path: Path) -> None:
    """Loop mode installs no `/review-close` and no `close_gate.py`, so a gate workflow there
    would run a script that is not installed (Phase 374)."""
    target = _seed_consumer(tmp_path / "consumer")
    _install(target, "--mode", "loop", "--packs", "", "--no-arm-hooks")
    ci = target / "sysop" / "scripts" / "ci"
    assert (ci / "sysop-checks.yml.example").is_file()
    assert not any((ci / n).exists() for n in (GATE.name, RELAY.name, REQS.name))
    assert not (target / "sysop" / "scripts" / "close_gate.py").exists()


def test_the_gate_job_runs_only_for_the_events_it_can_act_on() -> None:
    """The execution lens's Z02-Z04: each clause of the job's `if:` is load-bearing."""
    wf = _load(GATE)
    cond = " ".join(wf["jobs"]["gate"]["if"].split())
    assert "github.event.pull_request.base.ref == github.event.repository.default_branch" in cond
    assert "github.event_name == 'issue_comment' && github.event.issue.pull_request" in cond
    assert "github.ref == format('refs/heads/{0}', github.event.repository.default_branch)" in cond
    assert wf["on"]["push"] == {"branches": ["main"]}


def test_the_token_and_the_run_are_exactly_what_the_gate_needs() -> None:
    """Z05-Z08: the guard covers the requirements' directory, the minted token holds only checks
    write and two reads, the gate posts, and the job is bounded in time."""
    job = _load(GATE)["jobs"]["gate"]
    mint = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/create-github-app-token@"))
    assert {k: v for k, v in mint["with"].items() if k.startswith("permission-")} == {
        "permission-checks": "write", "permission-contents": "read", "permission-pull-requests": "read"}
    guard = next(r for r in _runs(GATE) if "is not a directory at the base" in r)
    assert "sysop sysop/scripts sysop/scripts/ci" in guard
    assert any("args=(run --repo \"$REPO\" --event \"$EVENT\" --post)" in r for r in _runs(GATE))
    assert job["timeout-minutes"] == 15


def test_the_guard_refuses_any_link_under_the_gates_directory() -> None:
    guard = next(r for r in _runs(GATE) if "a symlink or gitlink under sysop/scripts" in r)
    assert "git ls-tree -r HEAD -- sysop/scripts" in guard and '"120000"' in guard and '"160000"' in guard
