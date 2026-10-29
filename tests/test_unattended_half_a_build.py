"""Phase 380 (`Q-664`): the mechanisms half A with no human parks through.

Spec § 13 ruled an early park of the close recorded and non-blocking (`halted.md`), a late one
durable until a human clears it (ruling (al), and (av) for three Step 3b exits), and a branch
park keyed to the branch's head, cleared by a new head, an attended merge or `unhold` ((am),
(ay)). These tests drive `close_run.py`'s `stop` / `clear`, `hold` / `unhold` and
`eligible --held` against the unattended land's fixture, and `/sitrep`'s report of a stop.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from skill_runner_text import text_of

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
from test_unattended_land import (  # noqa: E402,F401
    AGENT, _branch, _g, _land, _lock, _out_lines, _run, _sealed, repo)

sys.path.insert(0, str(TESTS.parent / "core" / "companion" / "scripts"))
import sitrep_survey as ss  # noqa: E402

RUN = "20261011T010203Z-abcd"


def _runs(root: Path) -> Path:
    return root / "sysop" / "runtime" / "close"


# --- the durable stop ---------------------------------------------------------------------

def test_a_stop_blocks_every_later_close_until_a_human_clears_it(repo: Path) -> None:
    r = _run(repo, "stop", RUN, "Step 4a", "a status: conflict; recover on the integration branch",
             "--locks-kept", "T-1", "T-2")
    assert r.returncode == 0, r.stderr
    rec = json.loads((_runs(repo) / RUN / "STOPPED").read_text())
    assert rec["step"] == "Step 4a" and rec["locks_kept"] == ["T-1", "T-2"]
    assert "recover on the integration branch" in rec["reason"]
    for args in (["begin", "main"], ["reader"]):
        r = _run(repo, *args)
        assert r.returncode == 2 and f"close_run.py clear {RUN}" in r.stderr, (args, r.stderr)
    r = _run(repo, "hand-off", "main", "feat/x", "7", "0" * 40)
    assert r.returncode == 2 and "stopped" in r.stderr, r.stderr
    r = _run(repo, "clear", RUN)
    assert r.returncode == 0 and "CLEARED" in r.stdout, r.stderr
    assert not (_runs(repo) / RUN / "STOPPED").exists()
    assert list((_runs(repo) / RUN).glob("STOPPED.cleared-*")), "the cleared marker is not kept"
    assert _run(repo, "begin", "main").returncode == 0


def test_load_refuses_a_run_while_another_stop_stands(repo: Path) -> None:
    r = _run(repo, "begin", "main")
    run_id = re.search(r"^RUN: (\S+)", r.stdout, re.M).group(1)
    (_runs(repo) / run_id / "questions.md").write_text("")
    assert _run(repo, "finish", run_id).returncode == 0
    assert _run(repo, "stop", RUN, "Step 4c", "why").returncode == 0
    r = _run(repo, "load", run_id, "main")
    assert r.returncode == 2 and "stopped" in r.stderr, r.stderr


def test_the_unattended_land_refuses_while_a_stop_stands(repo: Path) -> None:
    run_id, _ = _sealed(repo)
    assert _run(repo, "stop", RUN, "hand-off", "seal failed").returncode == 0
    r = _land(repo, run_id)
    assert r.returncode == 2 and "stopped" in r.stderr, r.stdout + r.stderr


def test_a_stop_is_written_whatever_the_run_holds(repo: Path) -> None:
    """A stop that refused would leave the close unguarded: no run directory is needed."""
    assert not (_runs(repo) / RUN).exists()
    assert _run(repo, "stop", RUN, "Step 3b", "collect exit 5").returncode == 0
    assert _run(repo, "stop", RUN, "Step 4a", "later").returncode == 0
    rec = json.loads((_runs(repo) / RUN / "STOPPED").read_text())
    assert rec["step"] == "Step 4a" and rec["earlier"][0]["step"] == "Step 3b"


def test_a_stop_refuses_only_what_it_cannot_record(repo: Path) -> None:
    assert _run(repo, "stop", "<run-id>", "Step 4a", "x").returncode == 2
    assert _run(repo, "stop", RUN, "Step 4a", "x", "--other").returncode == 3
    assert _run(repo, "clear", RUN).returncode == 2


def test_sitrep_reports_a_stopped_close(repo: Path) -> None:
    assert _run(repo, "stop", RUN, "Step 4c", "1b asked about a doc").returncode == 0
    found = [d for d in ss._find_discrepancies([], [], {}, repo) if d.kind == "close stopped"]
    assert len(found) == 1, found
    assert "at Step 4c: 1b asked about a doc" in found[0].detail
    assert f"close_run.py clear {RUN}" in found[0].suggestion


# --- the branch hold ----------------------------------------------------------------------

def _ready(repo: Path, name: str = "feat/t1") -> None:
    _branch(repo, name, {"src/a.py": "a = 2\n"})
    _lock(repo, "T-1", name)


def test_a_held_branch_is_out_of_the_unattended_selection_only(repo: Path) -> None:
    _ready(repo)
    r = _run(repo, "hold", RUN, "feat/t1", "VERDICT: BLOCKED (convention 3)")
    assert r.returncode == 0 and r.stdout.startswith("HELD: feat/t1 at "), r.stderr
    got = _out_lines(_run(repo, "eligible", "main", AGENT, "--held", "feat/t1").stdout)
    head = _g(repo, "rev-parse", "feat/t1")
    assert got["feat/t1"] == f"OUT held at {head[:12]}: VERDICT: BLOCKED (convention 3)"
    # An attended close does not read holds.
    assert _out_lines(_run(repo, "eligible", "main", AGENT, "feat/t1").stdout)["feat/t1"].startswith("IN ")


def test_a_new_head_clears_the_hold(repo: Path) -> None:
    _ready(repo)
    assert _run(repo, "hold", RUN, "feat/t1", "unanswered: Q2").returncode == 0
    _g(repo, "checkout", "-q", "feat/t1")
    (repo / "src/a.py").write_text("a = 3\n")
    _g(repo, "commit", "-qam", "fix")
    _g(repo, "checkout", "-q", "main")
    r = _run(repo, "eligible", "main", AGENT, "--held", "feat/t1")
    assert "NOTE: feat/t1's hold is cleared: the branch moved to" in r.stdout, r.stdout
    assert _out_lines(r.stdout)["feat/t1"].startswith("IN ")
    assert not list((_runs(repo) / "holds").glob("*.json"))


def test_an_attended_merge_or_a_deleted_branch_clears_the_hold(repo: Path) -> None:
    _ready(repo)
    _ready(repo, "feat/gone")
    for b in ("feat/t1", "feat/gone"):
        assert _run(repo, "hold", RUN, b, "unanswered").returncode == 0
    _g(repo, "merge", "-q", "--ff-only", "feat/t1")
    _g(repo, "branch", "-D", "feat/gone")
    r = _run(repo, "eligible", "main", AGENT, "--held", "feat/t1", "feat/gone")
    assert "NOTE: feat/t1's hold is cleared: the branch is merged into main" in r.stdout, r.stdout
    assert "NOTE: feat/gone's hold is cleared: the branch is gone" in r.stdout, r.stdout
    assert _out_lines(r.stdout)["feat/gone"] == "OUT no such branch"


def test_unhold_clears_with_the_answer_kept(repo: Path) -> None:
    _ready(repo)
    assert _run(repo, "hold", RUN, "feat/t1", "unanswered: Q1").returncode == 0
    r = _run(repo, "unhold", "feat/t1", "copied the fixture to main")
    assert r.returncode == 0 and "UNHELD: feat/t1" in r.stdout, r.stderr
    kept = list((_runs(repo) / "holds").glob("*.cleared-*"))
    assert len(kept) == 1 and json.loads(kept[0].read_text())["cleared"]["note"] == \
        "copied the fixture to main"
    assert _out_lines(_run(repo, "eligible", "main", AGENT, "--held", "feat/t1").stdout)[
        "feat/t1"].startswith("IN ")
    assert _run(repo, "unhold", "feat/t1").returncode == 2


def test_a_hold_needs_a_branch_and_an_unreadable_hold_still_holds(repo: Path) -> None:
    assert _run(repo, "hold", RUN, "feat/none", "x").returncode == 2
    _ready(repo)
    assert _run(repo, "hold", RUN, "feat/t1", "x").returncode == 0
    (next((_runs(repo) / "holds").glob("*.json"))).write_text("{not json")
    got = _out_lines(_run(repo, "eligible", "main", AGENT, "--held", "feat/t1").stdout)
    assert got["feat/t1"].startswith("OUT held: ") and "cannot be read" in got["feat/t1"]


# --- the prose: one timing rule carries the per-class rulings ------------------------------

SKILL = TESTS.parent / "core" / "skills" / "review-close" / "SKILL.md"
TOOLS = TESTS.parent / "tools" / "unattended_close"


def _unattended_resume() -> str:
    t = text_of(SKILL)
    start = t.index("### Under `--resume <run-id> --request-review --agent <name> --unattended`")
    return t[start:t.index("### Under `--land <run-id>`", start)]


def test_the_section_states_the_no_human_rule_and_the_timing_rule() -> None:
    u = _unattended_resume()
    assert "Never use `AskUserQuestion` and never relay a `!` command" in u
    assert "**Before Step 4-pre, an early park.** Write the step and the reason to `<DIR>/halted.md`" in u
    assert "**From Step 4-pre on, a durable park.**" in u
    assert ("**Also durable, though before Step 4-pre:** Step 3b's collect exit 5, the rollback's "
            "exit 4, and a rollback that leaves main still holding a doc claiming the branch.") in u
    assert "4a-SKIPs that branch, with both values as the reason" in u
    assert "A reviewer that returns no `VERDICT:` line parks the close early" in u


def test_the_timing_rule_reproduces_every_ruled_park_of_the_close() -> None:
    """Spec § 13's rulings are per class; the runner gets one rule: early before Step 4-pre,
    durable from it, plus (av)'s three Step 3b exits. Checked against every half-A row's ruled
    effect, at the pin the rows were taken at, so the rule cannot drift from the rulings."""
    import pytest
    if not (TESTS.parent / "REVIEW_CHECKLIST.md").is_file():
        pytest.skip("the public mirror: tools/ does not ship")
    sys.path.insert(0, str(TOOLS))
    try:
        import half_a
        st, rg = half_a.rows()
    finally:
        sys.path.remove(str(TOOLS))
    checked = 0
    for r in st:
        for arm in r["effect"].split(" | "):
            if "park-close" not in arm:
                continue
            ruled = "durable" if "durable" in arm else "early"
            if arm.startswith("after the push"):
                rule = "durable"  # the section's item 5
            elif half_a.when(r["line"], rg) >= rg["4"] or r["line"] in half_a.DURABLE_3B:
                rule = "durable"
            else:
                rule = "early"
            assert rule == ruled, (r["line"], r["effect"])
            checked += 1
    assert checked == 77, checked


def test_the_commands_the_night_prescribes_run_as_written(repo: Path) -> None:
    """Phase 168 rule 3: run what the change prescribes, from the shipped text."""
    import shutil
    import subprocess as sp
    t = text_of(SKILL)
    prep = t[t.index("### Under `--prepare`"):t.index("### Under `--resume <run-id>`")]
    u = _unattended_resume()
    elig = re.findall(r"^\s*(python3 sysop/scripts/close_run\.py eligible .*)$", prep, re.M)
    holds = re.findall(r"^\s*(python3 sysop/scripts/close_run\.py hold .*)$", prep + u, re.M)
    stops = re.findall(r"^\s*(python3 sysop/scripts/close_run\.py stop .*)$", u, re.M)
    assert len(elig) == 1 and len(holds) == 2 and len(stops) == 1, (elig, holds, stops)
    (repo / "sysop/scripts").mkdir(parents=True)
    for name in ("close_run.py", "pending_doc_hold.py"):
        shutil.copy2(TESTS.parent / "core/companion/scripts" / name, repo / "sysop/scripts" / name)
    _ready(repo)

    def sh(cmd: str) -> sp.CompletedProcess:
        assert "<" not in cmd, cmd
        env = {**os.environ, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"}
        return sp.run(["bash", "-c", cmd], cwd=repo, capture_output=True, text=True, env=env)

    r = sh(elig[0].replace('"<default branch>"', '"main"').replace('"<name>"', f'"{AGENT}"')
           .replace('"<branch>" "<branch>"', '"feat/t1"'))
    assert r.returncode == 0 and _out_lines(r.stdout)["feat/t1"].startswith("IN "), r.stdout + r.stderr
    for h in holds:
        r = sh(h.replace("<run-id>", RUN).replace('"<branch>"', '"feat/t1"')
               .replace("<first violation>", "rule 1").replace("<n>", "2").replace("<step>", "Step 2d"))
        assert r.returncode == 0 and r.stdout.startswith("HELD: feat/t1"), r.stdout + r.stderr
    r = sh(elig[0].replace('"<default branch>"', '"main"').replace('"<name>"', f'"{AGENT}"')
           .replace('"<branch>" "<branch>"', '"feat/t1"'))
    assert _out_lines(r.stdout)["feat/t1"].startswith("OUT held at "), r.stdout
    r = sh(stops[0].replace("<run-id>", RUN).replace("<step>", "Step 4c").replace(
        "<reason>", "1b asked").replace("<the step's own>", "finish on the integration branch")
        .replace("<id> <id>", "T-1"))
    assert r.returncode == 0 and r.stdout.startswith(f"STOPPED: {RUN}"), r.stdout + r.stderr
    rec = json.loads((_runs(repo) / RUN / "STOPPED").read_text())
    assert rec["locks_kept"] == ["T-1"] and rec["reason"].endswith("Recovery: finish on the integration branch")
    # The inline forms the gate and Step 8 give a human.
    inline = re.findall(r"`(python3 sysop/scripts/close_run\.py (?:clear|unhold) [^`]+)`", t)
    assert sorted(c.split()[2] for c in inline) == ["clear", "unhold"], inline
    for c in inline:
        r = sh(c.replace('"<run-id>"', f'"{RUN}"').replace('"<branch>"', '"feat/t1"')
               .replace('"<what was fixed>"', '"copied the fixture"'))
        assert r.returncode == 0, (c, r.stdout + r.stderr)
    assert not (_runs(repo) / RUN / "STOPPED").exists()


# --- round 1's findings (lens 3) -----------------------------------------------------------

def test_a_stop_takes_step_4cs_none_and_records_odd_ids(repo: Path) -> None:
    """B2: Step 4c prints `LOCKS_KEPT: (none)`, and a stop that refused it went unrecorded."""
    r = _run(repo, "stop", RUN, "Step 4d", "x", "--locks-kept", "(none)")
    assert r.returncode == 0, r.stderr
    assert json.loads((_runs(repo) / RUN / "STOPPED").read_text())["locks_kept"] == []
    r = _run(repo, "stop", RUN, "Step 4d", "y", "--locks-kept", "T-1", "T 2")
    rec = json.loads((_runs(repo) / RUN / "STOPPED").read_text())
    assert r.returncode == 0 and rec["locks_kept"] == ["T-1"] and rec["locks_unparsed"] == ["T 2"]


def test_a_squash_merge_recorded_as_a_pr_head_clears_the_hold(repo: Path) -> None:
    """B4: `pr` policy squash-merges, so the tip is never an ancestor of the default branch;
    the recorded PR head (`refs/sysop/merged-pr-heads/<N>`) is what says it landed."""
    _ready(repo)
    assert _run(repo, "hold", RUN, "feat/t1", "BLOCKED").returncode == 0
    _g(repo, "merge", "-q", "--squash", "feat/t1")
    _g(repo, "commit", "-qm", "squash")
    got = _out_lines(_run(repo, "eligible", "main", AGENT, "--held", "feat/t1").stdout)
    assert got["feat/t1"].startswith("OUT held at "), got  # a squash alone proves nothing
    _g(repo, "update-ref", "refs/sysop/merged-pr-heads/7", _g(repo, "rev-parse", "feat/t1"))
    r = _run(repo, "eligible", "main", AGENT, "--held", "feat/t1")
    assert "NOTE: feat/t1's hold is cleared: the branch landed in a recorded PR head" in r.stdout, r.stdout


def test_held_reads_wherever_it_sits_after_the_agent(repo: Path) -> None:
    """B5: `eligible ... feat/t1 --held` printed IN and `OUT --held: no such branch`."""
    _ready(repo)
    assert _run(repo, "hold", RUN, "feat/t1", "BLOCKED").returncode == 0
    r = _run(repo, "eligible", "main", AGENT, "feat/t1", "--held")
    got = _out_lines(r.stdout)
    assert got == {"feat/t1": got["feat/t1"]} and got["feat/t1"].startswith("OUT held at "), r.stdout


def test_sitrep_recommends_the_stop_ahead_of_any_close(repo: Path) -> None:
    """B3: with `STOPPED` standing, every /review-close refuses, so RECOMMENDED NEXT routes to
    the human recovery ahead of row 1."""
    assert _run(repo, "stop", RUN, "Step 4c", "1b asked").returncode == 0
    disc = ss._find_discrepancies([], [], {}, repo)
    ready = ss.TaskState(task_id="T-9", state="ready for /review-close")
    rec = ss._recommended_next(ss.Survey(tasks=[ready], review_batches=[], discrepancies=disc,
                                         **{k: v for k, v in _survey_defaults().items()}))
    assert rec is not None and rec.command == f"a human: recover as it says, then close_run.py clear {RUN}", rec


def _survey_defaults() -> dict:
    import dataclasses
    out = {}
    for f in dataclasses.fields(ss.Survey):
        if f.name in ("tasks", "review_batches", "discrepancies"):
            continue
        if f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING:
            continue
        out[f.name] = {"int": 0, "str": "", "bool": False}.get(str(f.type), None)
    return out


def test_sitrep_names_a_held_branch(repo: Path) -> None:
    """Round 1, lens 1 LOW-5: a hold was invisible outside Step 8's report."""
    _ready(repo)
    assert _run(repo, "hold", RUN, "feat/t1", "VERDICT: BLOCKED: rule 1").returncode == 0
    found = [d for d in ss._find_discrepancies([], [], {}, repo) if d.kind == "branch held"]
    assert len(found) == 1 and found[0].detail.startswith("feat/t1 is held at ") and \
        found[0].detail.endswith(": VERDICT: BLOCKED: rule 1"), found


def test_the_prepare_with_an_agent_hands_the_night_its_resume(repo: Path) -> None:
    """Round 1, lens 1 MEDIUM-4: `finish` named an attended resume and nothing recorded the
    agent; `resumable` gives a script the run id the second session needs."""
    assert _run(repo, "resumable").returncode == 2
    r = _run(repo, "begin", "main", "--agent", AGENT)
    run_id = re.search(r"^RUN: (\S+)", r.stdout, re.M).group(1)
    (_runs(repo) / run_id / "questions.md").write_text("")
    r = _run(repo, "finish", run_id)
    assert f"RESUME: /review-close --resume {run_id} --request-review --agent {AGENT} --unattended" in r.stdout, r.stdout
    r = _run(repo, "resumable", "--agent", AGENT)
    assert r.returncode == 0 and r.stdout.strip() == run_id, r.stdout + r.stderr
    assert _run(repo, "resumable", "--agent", "someone-else").returncode == 2
    (_runs(repo) / run_id / "halted.md").write_text("Step 3: x\n")
    assert _run(repo, "resumable").returncode == 2
    assert _run(repo, "begin", "main", "--agent", "bad name").returncode == 2


def test_two_clears_in_one_second_keep_both_records(repo: Path) -> None:
    """Round 1, lens 1 LOW-2."""
    for why in ("a", "b"):
        assert _run(repo, "stop", RUN, "Step 4a", why).returncode == 0
        assert _run(repo, "clear", RUN).returncode == 0
    assert len(list((_runs(repo) / RUN).glob("STOPPED.cleared-*"))) == 2


# --- round 1's findings (lens 2) -----------------------------------------------------------

def _hold_file(repo: Path) -> Path:
    return next((_runs(repo) / "holds").glob("*.json"))


def test_a_hold_with_a_damaged_head_still_holds(repo: Path) -> None:
    """G02: a record with `"head": ""` read as moved and released the branch."""
    _ready(repo)
    assert _run(repo, "hold", RUN, "feat/t1", "x").returncode == 0
    rec = json.loads(_hold_file(repo).read_text())
    for head in ("", "abc", None):
        rec["head"] = head
        _hold_file(repo).write_text(json.dumps(rec))
        got = _out_lines(_run(repo, "eligible", "main", AGENT, "--held", "feat/t1").stdout)
        assert got["feat/t1"].startswith("OUT held: ") and "close_run.py unhold feat/t1" in got["feat/t1"], (head, got)


def test_a_hold_needs_its_reason_and_a_cleared_one_is_kept(repo: Path) -> None:
    """G07, G04."""
    _ready(repo)
    assert _run(repo, "hold", RUN, "feat/t1", " ").returncode == 2
    assert _run(repo, "hold", RUN, "feat/t1", "x").returncode == 0
    _g(repo, "branch", "-f", "feat/t1", "main")
    _run(repo, "eligible", "main", AGENT, "--held", "feat/t1")
    assert len(list((_runs(repo) / "holds").glob("*.cleared-*"))) == 1


def test_an_empty_stopped_marker_still_stops_and_clear_stays_in_its_directory(repo: Path) -> None:
    """G16, G18."""
    (_runs(repo) / RUN).mkdir(parents=True)
    (_runs(repo) / RUN / "STOPPED").write_text("")
    assert _run(repo, "begin", "main").returncode == 2
    found = [d for d in ss._find_discrepancies([], [], {}, repo) if d.kind == "close stopped"]
    assert found and "cannot be read" in found[0].detail, found
    assert _run(repo, "clear", "../x").returncode == 2


def test_a_cleared_stop_is_no_longer_reported(repo: Path) -> None:
    """S01."""
    assert _run(repo, "stop", RUN, "Step 4c", "x").returncode == 0
    assert _run(repo, "clear", RUN).returncode == 0
    assert not [d for d in ss._find_discrepancies([], [], {}, repo) if d.kind == "close stopped"]


def test_three_stops_keep_every_earlier_record(repo: Path) -> None:
    """G12, G13."""
    for step in ("Step 3b", "Step 4a", "Step 4c"):
        assert _run(repo, "stop", RUN, step, "x").returncode == 0
    rec = json.loads((_runs(repo) / RUN / "STOPPED").read_text())
    assert rec["step"] == "Step 4c" and [e["step"] for e in rec["earlier"]] == ["Step 4a", "Step 3b"]
    assert rec["at"] and all(e["at"] for e in rec["earlier"])


def test_the_usage_names_the_new_commands(repo: Path) -> None:
    """D03."""
    err = _run(repo).stderr
    for cmd in ("stop <run-id>", "clear <run-id>", "hold <run-id>", "unhold <branch>", "resumable"):
        assert cmd in err, cmd


def _prepared(repo: Path, *agent: str, finish: bool = True) -> str:
    import time
    time.sleep(1.05)  # run ids carry the second
    r = _run(repo, "begin", "main", *agent)
    run_id = re.search(r"^RUN: (\S+)", r.stdout, re.M).group(1)
    if finish:
        (_runs(repo) / run_id / "questions.md").write_text("")
        assert _run(repo, "finish", run_id).returncode == 0
    return run_id


def test_resumable_never_falls_back_to_an_older_run(repo: Path) -> None:
    """Round 2, lens B: with tonight's prepare halted, unfinished or consumed, the chained
    resume consumed an older run, which may be a human's prepare waiting for its answers."""
    older = _prepared(repo, "--agent", AGENT)
    newest = _prepared(repo, "--agent", AGENT)
    assert _run(repo, "resumable", "--agent", AGENT).stdout.strip() == newest  # the newest, not the oldest
    for state in ("halted", "consumed"):
        target = _runs(repo) / newest / ("halted.md" if state == "halted" else "consumed")
        target.write_text("x\n")
        r = _run(repo, "resumable", "--agent", AGENT)
        assert r.returncode == 2 and older not in r.stdout, (state, r.stdout, r.stderr)
        target.unlink()
    unfinished = _prepared(repo, "--agent", AGENT, finish=False)
    r = _run(repo, "resumable", "--agent", AGENT)
    assert r.returncode == 2 and r.stdout.strip() not in (older, newest), (unfinished, r.stdout)


def test_an_unreadable_hold_on_a_slashed_branch_names_the_branch(repo: Path) -> None:
    """Round 2, lens B (S04): the file is named quote(branch), so the fallback printed
    `feat%2Ft1`, which `unhold` refuses."""
    _ready(repo)
    assert _run(repo, "hold", RUN, "feat/t1", "x").returncode == 0
    _hold_file(repo).write_text("{not json")
    found = [d for d in ss._find_discrepancies([], [], {}, repo) if d.kind == "branch held"]
    assert found and found[0].detail.startswith("feat/t1 is held at ?"), found
    assert "close_run.py unhold feat/t1" in found[0].suggestion
