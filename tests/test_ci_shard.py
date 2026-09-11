"""The merge gate's shard split -- the selection half and the workflow half (Phase 279).

`Q-465`: the required `pytest` check cost ~16 min per PR, 949 s of it in the test step, and
the suite is not core-bound -- so it is split across machines rather than given a bigger
one. `tests/conftest.py` carries the design argument and the measurements; this module is
the part that fails when the split stops being a split.

**What can actually go wrong here, and why each guard exists.** A sharded gate has one
failure that matters more than every other: it is green while some slice of the suite ran
nowhere. There is no output that names that -- four green shards and a green aggregator look
exactly like a suite that ran. So the properties below are not stylistic:

  1. The assignment is TOTAL and ORDER-INDEPENDENT, so N shards partition the population by
     construction rather than by a count somebody checks.
  2. The workflow DERIVES both shard numbers from the matrix, so there is no second number
     that can disagree with the first.
  3. The aggregator demands `success` and refuses every other state, so `skipped` and
     `cancelled` -- the two states in which nothing was tested -- cannot certify.

Each one is pinned by execution or by reading the workflow, never by reading prose.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.conftest import (
    COLLECTED_NODEIDS,
    SHARD_COUNT_VAR,
    SHARD_ID_VAR,
    ShardConfigError,
    select_shard,
    shard_assignment,
    shard_config,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"

#: Counts worth exercising: 1 (the nightly's single leg, which must be a no-op), 4 (what the
#: workflow ships), and enough neighbours that a fix tuned to exactly four is still wrong.
COUNTS = (1, 2, 3, 4, 5, 8)


_POPULATION_CACHE: list[str] = []
#: Below this, `COLLECTED_NODEIDS` is this module alone rather than the suite, and the
#: properties below would be checked against a toy set. Well under the ~6,600 a full run
#: collects, because the floor only has to separate "one module" from "the suite".
_POPULATION_FLOOR = 500


def _population():
    """The suite's real node ids -- every module, whatever the invocation was.

    `conftest.py` records the collection before it filters anything, which is the free path
    and the one a full run takes. **But running this module alone collects ~45 ids**, and
    that is the natural way to work on it: the partition would then be checked against a set
    two orders of magnitude below the one the docstrings claim, the balance bound would fail
    on ordinary small-sample variance, and the set-independence check would skip for want of
    a second module -- all of it silently, while the module reported green.

    So a short population is REPLACED rather than tolerated. Collection costs ~0.9 s and is
    cached for the module, which is cheaper than a guard that quietly measures the wrong
    thing. A partition that holds for three invented strings and breaks on 6,600 ids sharing
    long prefixes is the bug this module exists for.
    """
    if len(COLLECTED_NODEIDS) >= _POPULATION_FLOOR:
        return list(COLLECTED_NODEIDS)
    if not _POPULATION_CACHE:
        p = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-n0"],
            cwd=REPO_ROOT, capture_output=True, encoding="utf-8",
            env={k: v for k, v in os.environ.items()
                 if k not in (SHARD_ID_VAR, SHARD_COUNT_VAR)},
        )
        assert p.returncode == 0, f"could not collect the suite:\n{p.stdout[-2000:]}{p.stderr}"
        _POPULATION_CACHE.extend(l.strip() for l in p.stdout.splitlines() if "::" in l)
    assert len(_POPULATION_CACHE) >= _POPULATION_FLOOR, (
        f"the suite collected only {len(_POPULATION_CACHE)} ids, below the {_POPULATION_FLOOR} "
        "floor these properties need to mean anything"
    )
    return list(_POPULATION_CACHE)


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


# ── the assignment ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("count", COUNTS)
def test_the_shards_partition_the_whole_suite(count):
    """Every collected item has exactly one owner: none dropped, none run twice.

    This is the property the whole design rests on. Coverage is not checked by summing the
    shards' reported counts in CI -- nothing does that -- it is bought here, once, as a
    property of the assignment function.
    """
    pop = _population()
    owner = shard_assignment(pop, count)

    assert set(owner) == set(pop), (
        "shard_assignment did not return an owner for every node id -- "
        f"{len(set(pop) - set(owner))} unowned"
    )
    assert all(0 <= s < count for s in owner.values()), (
        f"an owner fell outside [0, {count}): {sorted({s for s in owner.values() if not 0 <= s < count})}"
    )
    recovered = set()
    for shard in range(count):
        recovered |= {n for n, s in owner.items() if s == shard}
    assert recovered == set(pop), (
        f"{len(set(pop) - recovered)} node ids are owned by no shard in 0..{count - 1}"
    )


@pytest.mark.parametrize("count", COUNTS)
def test_the_assignment_depends_on_the_set_and_not_on_the_order(count):
    """Reverse the input; every id must keep the same owner.

    The rejected alternative -- round-robin over pytest's COLLECTION order -- measured
    marginally better on balance and fails this test. It keys a test's owner to the sequence
    the ids arrived in, so any difference in collection order between two of the four
    runners opens a coverage gap that no output would report. Sorting the set is what buys
    the immunity, and this is the guard that keeps it bought.
    """
    pop = _population()
    assert shard_assignment(reversed(pop), count) == shard_assignment(pop, count)
    assert shard_assignment(sorted(pop, reverse=True), count) == shard_assignment(pop, count)


def test_the_assignment_is_identical_in_another_process_under_another_hash_seed():
    """A salted key would make two shards disagree about who owns what.

    CPython randomises str hashing per process. xdist workers ARE separate processes and
    xdist aborts when workers report different collections, so `hash()` here is a suite that
    fails to start on some runs -- and across four MACHINES it is worse than that, because
    nothing compares two machines' collections at all: ids would simply go unrun.

    Driven in a subprocess with an explicit `PYTHONHASHSEED` rather than by reading the
    source for the word `hash`, so a future rewrite is judged on what it computes.
    """
    pop = _population()[:400]
    prog = (
        "import json,sys;"
        "sys.path.insert(0, sys.argv[1]);"
        "from tests.conftest import shard_assignment;"
        "print(json.dumps(shard_assignment(json.loads(sys.argv[2]), 4)))"
    )
    import json
    # The shard vars are STRIPPED from the child rather than set to anything. The child only
    # imports the module and calls the function -- no pytest hook runs there -- so an
    # inherited value could not change the answer, and leaving one in would suggest to a
    # later reader that it could.
    base = {k: v for k, v in os.environ.items() if k not in (SHARD_ID_VAR, SHARD_COUNT_VAR)}
    out = []
    for seed in ("0", "1", "12345"):
        p = subprocess.run(
            [sys.executable, "-c", prog, str(REPO_ROOT), json.dumps(pop)],
            capture_output=True, encoding="utf-8",
            env={**base, "PYTHONHASHSEED": seed},
        )
        assert p.returncode == 0, f"seed={seed}: {p.stderr}"
        out.append(json.loads(p.stdout))
    assert out[0] == out[1] == out[2], (
        "the assignment moved with PYTHONHASHSEED -- the key is salted, and two shards "
        "will disagree about who owns a test"
    )
    assert out[0] == shard_assignment(pop, 4), "the subprocess disagreed with this process"


@pytest.mark.parametrize("count", COUNTS)
def test_every_slice_holds_roughly_its_share(count):
    """Not a performance assertion -- a sanity one.

    Time balance is measured in `conftest.py`'s header and is deliberately NOT gated: a
    badly balanced shard is slow, not wrong, and the balance a hash gives is a draw rather
    than a guarantee. What is wrong is a slice holding a wildly wrong NUMBER of items, which
    means the assignment has stopped distributing. The bound is loose on purpose -- tight
    enough to catch "everything landed in one shard", loose enough that a hash's ordinary
    variance never reds a correct tree.
    """
    pop = _population()
    owner = shard_assignment(pop, count)
    sizes = [sum(1 for s in owner.values() if s == shard) for shard in range(count)]
    mean = len(set(pop)) / count
    assert all(0.6 * mean <= s <= 1.4 * mean for s in sizes), (
        f"a slice is more than 40% off an even share: {sizes} against a mean of {mean:.1f}. "
        "The assignment has stopped distributing."
    )


@pytest.mark.parametrize("count", COUNTS)
def test_dropping_a_module_changes_no_other_test_s_owner(count):
    """**The property the first version of this change did not have, and the reason it is a
    hash rather than the better-balanced round-robin.**

    The four shards are four machines, and nothing anywhere compares their collections. If
    one machine collects a different SET -- three modules here carry a module-level
    `pytest.importorskip`, and a parametrized module can collect a different number of items
    on a different host -- then an assignment keyed to POSITION re-parents everything after
    the divergence, and ids fall between the machines and run nowhere while every leg
    reports green. Simulated at the time: dropping one 43-item module moved 2,540 ids and
    left 646 running on no machine.

    So the owner must be a pure function of the id. This drives that directly: drop a whole
    module from the population and require every surviving id to keep its shard.
    """
    pop = _population()
    modules = {n.split("::")[0] for n in pop}
    if len(modules) < 2:
        pytest.skip(f"need at least two modules in the population; got {len(modules)}")
    before = shard_assignment(pop, count)
    for victim in sorted(modules)[:3]:
        kept = [n for n in pop if not n.startswith(victim + "::")]
        after = shard_assignment(kept, count)
        moved = [n for n in kept if before[n] != after[n]]
        assert not moved, (
            f"dropping {victim} re-parented {len(moved)} of {len(kept)} surviving ids "
            f"(e.g. {moved[:3]}). The owner depends on the population, so a machine that "
            "collects a different set silently runs a different slice than the others "
            "expect -- and the ids in between run nowhere, with every leg green."
        )


# ── selection against real pytest items ─────────────────────────────────────────────────

class _Item:
    def __init__(self, nodeid):
        self.nodeid = nodeid


def test_select_shard_keeps_and_drops_every_item_exactly_once():
    pop = _population()
    items = [_Item(n) for n in pop]
    seen = []
    for shard in range(4):
        kept, dropped = select_shard(items, shard, 4)
        assert len(kept) + len(dropped) == len(items), "an item was neither kept nor dropped"
        seen.extend(i.nodeid for i in kept)
    assert sorted(seen) == sorted({i.nodeid for i in items}), (
        "the four shards' kept sets do not reassemble the collection"
    )


def test_a_single_shard_is_a_no_op():
    """`count=1` is the nightly's path and must select everything.

    Checked rather than assumed, because the nightly is the one run that still sees the full
    population under contention -- which is what `Q-466`'s flake needs in order to be
    observable anywhere at all.
    """
    items = [_Item(n) for n in _population()]
    kept, dropped = select_shard(items, 0, 1)
    assert dropped == []
    assert [i.nodeid for i in kept] == [i.nodeid for i in items]


# ── the hook, end to end ────────────────────────────────────────────────────────────────

def _selected(shard, count, target="tests/test_ci_shard.py"):
    """Node ids a REAL pytest run selects for this shard, via the real hook."""
    env = {k: v for k, v in os.environ.items()
           if k not in (SHARD_ID_VAR, SHARD_COUNT_VAR)}
    if count is not None:
        env[SHARD_ID_VAR] = str(shard)
        env[SHARD_COUNT_VAR] = str(count)
    p = subprocess.run(
        [sys.executable, "-m", "pytest", target, "--collect-only", "-q", "-n0"],
        cwd=REPO_ROOT, capture_output=True, encoding="utf-8", env=env,
    )
    assert p.returncode == 0, f"shard {shard}/{count} collection failed:\n{p.stdout}{p.stderr}"
    return {l.strip() for l in p.stdout.splitlines() if "::" in l}


@pytest.mark.parametrize("count", [3, 4])
def test_real_pytest_runs_between_them_select_the_whole_module_exactly_once(count):
    """Drives `pytest_collection_modifyitems` itself, not the functions under it.

    **This is the guard that matters most, and it exists because the obvious ones did not
    catch the worst mutation.** Every test above drives `shard_assignment` or `select_shard`
    directly, so all of them stay green when the HOOK is the thing that breaks -- passing a
    constant 0 where the shard id belongs, say. Four machines then run slice 0, three
    quarters of the suite runs nowhere, and all four shards plus the aggregator report
    green. There is no output anywhere that names that. Found by this phase's own author-side
    battery, as a survivor.

    Five real subprocesses -- an unsharded control plus one per slice -- because the wiring
    between the environment, the config parser and the selector is exactly what a direct call
    skips.
    """
    whole = _selected(0, None)
    assert len(whole) > 8, f"need a real module to slice; got {len(whole)} ids"

    slices = [_selected(i, count) for i in range(count)]

    union = set().union(*slices)
    assert union == whole, (
        f"{len(whole - union)} node ids are selected by no shard and {len(union - whole)} "
        "appear that the unsharded run does not. The shards do not cover the module."
    )
    for i in range(count):
        for j in range(i + 1, count):
            assert not (slices[i] & slices[j]), (
                f"shards {i} and {j} both run {sorted(slices[i] & slices[j])[:3]} -- "
                "the same test is being paid for twice and something else is unpaid"
            )
    assert len({frozenset(s) for s in slices}) > 1, (
        "every shard selected the same tests. The shard id is not reaching the selector, "
        f"so {count} machines are running one slice and the rest of the suite runs nowhere."
    )


@pytest.mark.parametrize("count", [2, 7])
def test_the_hook_shards_at_counts_the_workflow_does_not_use_today(count):
    """Cheap, and it exists because driving only the shipped count is not enough.

    The round's guard lens staged three mutations it never ran, and two of them survive
    everything else here: `if count == 1:` widened to `count > 4` or `count in (1, 5, 6, 7,
    8)` -- a hook that shards correctly at the counts anyone tests and runs the WHOLE suite
    at any other. Every machine then runs everything: no coverage gap, but four times the
    bill and none of the speed, silently, the moment the matrix widens. And widening it is
    explicitly left free -- `test_the_suite_still_runs_whole_on_one_machine_off_pull_request`
    asserts `>= 2` legs rather than pinning four, so that a retune is a one-file edit.

    Two subprocesses per count rather than the full partition sweep: the question here is
    only *does it shard at all*, which a proper subset answers.
    """
    whole = _selected(0, None)
    one = _selected(0, count)
    assert one < whole, (
        f"at count={count} shard 0 selected {len(one)} of {len(whole)} tests -- not a "
        "proper subset, so the hook is not sharding at this count. A hook that shards only "
        "at the counts someone tested runs the whole suite on every machine as soon as the "
        "matrix changes."
    )


def test_an_unsharded_run_and_a_single_shard_collect_the_same_tests():
    """`count=1` is the nightly's path, checked through the hook rather than the function."""
    assert _selected(0, 1) == _selected(0, None)


# ── the shard must not reach the children a test spawns ─────────────────────────────────

#: A module big enough that a quarter of it is obviously not all of it, cheap to collect,
#: and with no side effects. Its size is read at run time, never written down here.
_PROBE_TARGET = "tests/test_repo_write_guard.py"
#: Set by the outer guard to the full collected count; its presence is what un-skips the
#: inner probe, so an ordinary suite run never pays for it.
_PROBE_VAR = "SYSOP_SHARD_CHILD_PROBE"


@pytest.mark.skipif(
    not os.environ.get(_PROBE_VAR),
    reason="the inner half of test_a_sharded_run_does_not_shard_the_children_a_test_spawns",
)
def test_child_probe_collects_a_whole_module():
    """Not run directly. The guard below runs THIS under a shard and requires it to pass.

    It does what several real tests in this suite do -- spawn `python -m pytest` and assert
    something about the population the child collected. If the shard environment reaches the
    child, the child collects its own quarter and this fails.
    """
    expected = int(os.environ[_PROBE_VAR])
    p = subprocess.run(
        [sys.executable, "-m", "pytest", _PROBE_TARGET, "--collect-only", "-q", "-n0"],
        cwd=REPO_ROOT, capture_output=True, encoding="utf-8",
    )
    assert p.returncode == 0, f"child collection failed:\n{p.stdout}{p.stderr}"
    got = len([l for l in p.stdout.splitlines() if "::" in l])
    assert got == expected, (
        f"a pytest child spawned from inside a SHARDED run collected {got} of {expected} "
        f"tests in {_PROBE_TARGET}. The shard environment reached the child, so every "
        "guard in this suite that spawns pytest is silently measuring a fraction of its "
        "subject."
    )


def test_a_sharded_run_does_not_shard_the_children_a_test_spawns():
    """The defect this phase shipped to CI and got back on the first run.

    `tests/test_index_writer_class.py` collects another module in a subprocess and asserts a
    floor of 17; under the first sharded run it collected 4 and went red. That one is the
    LUCKY shape. `tests/test_mirror_skip_discipline.py` also spawns pytest and asserts a
    property rather than a floor -- a quarter of its subject satisfies it just as well, and
    nothing would have reported the difference.

    Driven end to end rather than by asserting that `os.environ` lacks the variables, which
    is trivially true in an unsharded run and would be a guard that cannot fail.
    """
    whole = _selected(0, None, _PROBE_TARGET)
    assert len(whole) > 8, f"{_PROBE_TARGET} is too small to be a probe: {len(whole)} tests"

    env = {k: v for k, v in os.environ.items()
           if k not in (SHARD_ID_VAR, SHARD_COUNT_VAR)}
    inner = f"{Path(__file__).relative_to(REPO_ROOT)}::test_child_probe_collects_a_whole_module"
    # ASK the assignment which shard owns the inner test rather than assuming one. A single
    # node id is a population of one, and under a hash that does not make it shard 0 -- an
    # earlier version hard-coded 0 and silently ran a shard that deselected its own subject,
    # which would have made this guard pass while testing nothing.
    owner = shard_assignment([inner], 4)[inner]
    env |= {SHARD_ID_VAR: str(owner), SHARD_COUNT_VAR: "4", _PROBE_VAR: str(len(whole))}
    p = subprocess.run(
        [sys.executable, "-m", "pytest", inner, "-q", "-n0"],
        cwd=REPO_ROOT, capture_output=True, encoding="utf-8", env=env,
    )
    assert "1 passed" in p.stdout, (
        "the inner probe did not run and pass under a sharded parent. Either the shard "
        "environment is reaching pytest children again, or this guard's own subject moved:\n"
        f"{p.stdout}{p.stderr}"
    )


# ── the environment contract, which fails closed ────────────────────────────────────────

def test_no_shard_variables_means_no_sharding():
    assert shard_config({}) is None
    assert shard_config({"PATH": "/usr/bin"}) is None


@pytest.mark.parametrize("env, why", [
    ({SHARD_ID_VAR: "", SHARD_COUNT_VAR: ""},
     "an unresolved ${{ strategy.* }} arrives as the empty string"),
    ({SHARD_ID_VAR: "0", SHARD_COUNT_VAR: ""}, "half-resolved"),
    ({SHARD_ID_VAR: "", SHARD_COUNT_VAR: "4"}, "half-resolved the other way"),
    ({SHARD_ID_VAR: "0"}, "count missing entirely"),
    ({SHARD_COUNT_VAR: "4"}, "id missing entirely"),
    ({SHARD_ID_VAR: "x", SHARD_COUNT_VAR: "4"}, "not an integer"),
    ({SHARD_ID_VAR: "0", SHARD_COUNT_VAR: "four"}, "count not an integer"),
    ({SHARD_ID_VAR: "4", SHARD_COUNT_VAR: "4"}, "id equals count -- a slice runs nowhere"),
    ({SHARD_ID_VAR: "-1", SHARD_COUNT_VAR: "4"}, "negative id"),
    ({SHARD_ID_VAR: "0", SHARD_COUNT_VAR: "0"}, "zero shards"),
    # A round mutation replaced `int()` with `int(float())` and nothing noticed. `4.9` is
    # not a shard id; accepting it as 4 would take a value nobody meant and run with it.
    ({SHARD_ID_VAR: "0.5", SHARD_COUNT_VAR: "4"}, "a decimal id truncated to a real one"),
    ({SHARD_ID_VAR: "0", SHARD_COUNT_VAR: "4.9"}, "a decimal count truncated to a real one"),
])
def test_a_broken_shard_environment_refuses_rather_than_running_everything(env, why):
    """The asymmetry that matters: absent means unsharded, PRESENT-but-broken means stop.

    Reading a broken environment as "no sharding requested" would have four machines each
    run the whole suite -- four times the cost, no coverage gain, and every check green. The
    run has to go red instead, and it has to say why.
    """
    with pytest.raises(ShardConfigError) as exc:
        shard_config(env)
    assert SHARD_ID_VAR in str(exc.value) and SHARD_COUNT_VAR in str(exc.value), (
        f"the refusal for '{why}' does not name both variables, so the reader of a red CI "
        "job cannot tell which one was wrong"
    )


@pytest.mark.parametrize("env, expected", [
    ({SHARD_ID_VAR: "0", SHARD_COUNT_VAR: "1"}, (0, 1)),
    ({SHARD_ID_VAR: "3", SHARD_COUNT_VAR: "4"}, (3, 4)),
])
def test_a_valid_shard_environment_parses(env, expected):
    assert shard_config(env) == expected


def test_a_broken_shard_environment_says_why_under_the_flags_ci_actually_uses():
    """The refusal above is a unit call and cannot see WHERE the exception is raised.

    That distinction is the whole of it. `pyproject.toml` defaults `-n auto` and the
    workflow runs bare `pytest`, so collection happens in an xdist worker -- and a
    `UsageError` raised from the collection hook surfaces there as a 49-line INTERNALERROR
    with exit 3 and the message nowhere in the output. Raised from `pytest_configure`, which
    the controller runs before spawning anything, it is the first line and exit 4.

    So this runs a real pytest WITHOUT `-n0`, which is the configuration that differs.
    """
    env = {**os.environ, SHARD_ID_VAR: "4", SHARD_COUNT_VAR: "4"}
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_ci_shard.py", "--collect-only"],
        cwd=REPO_ROOT, capture_output=True, encoding="utf-8", env=env,
    )
    assert p.returncode != 0, "a shard id outside the count did not stop the run"
    assert "runs nowhere" in p.stdout + p.stderr, (
        "the refusal ran but its reason never reached the output, so the reader of a red "
        f"leg cannot tell which variable was wrong:\n{p.stdout[-1500:]}{p.stderr[-1500:]}"
    )
    assert p.returncode == 4, (
        f"expected pytest's usage-error exit 4, got {p.returncode}. Exit 3 means the "
        "validation moved back into collection, where an xdist worker turns it into an "
        "INTERNALERROR and the message is lost."
    )


# ── the workflow half ───────────────────────────────────────────────────────────────────
#
# **Rewritten by this phase's own round, which walked 24 mutations through the first
# version.** Every one exploited HOW a guard located the thing it inspected rather than what
# it then asserted: the env check kept the LAST matching step, so eleven lines of decoy step
# revived a hand-written count; the aggregator check read `steps[0]`, so a first step
# echoing the right words satisfied three regexes while the real gate was defanged; and
# nothing read the shard job's `run:` block at all, so `pytest -k shard`, `echo skipping`,
# `pytest || true`, `if: false` and `continue-on-error: true` each turned the merge gate
# into a green light over nothing.
#
# So the locators below are **identity, not position**: find the step by the thing that
# makes it that step, and require exactly one of it. The same round's negative controls
# reddened on three innocent edits — a quoted `"on":` key (what yamllint's truthy rule
# asks for), an extra first step in the aggregator job, and single-quoting a shell string —
# so the readers are quote-agnostic and key-shape-agnostic too. A guard that reds on the
# idiomatic form and passes on the hostile one is worse than no guard; that pair was
# literally the same assumption.


def _triggers(wf):
    """The `on:` block, under whichever key YAML 1.1 produced.

    A bare `on` parses as the BOOLEAN True; `"on"` quoted parses as the string. Both are
    legal and the quoted form is what linters ask for, so a guard keyed to one of them reds
    on a correct reformat.
    """
    for key in (True, "on", "On", "ON"):
        if key in wf:
            return wf[key]
    raise AssertionError(f"no `on:` trigger block found; top-level keys are {list(wf)}")


def _the_test_step(wf):
    """The one step that runs the suite: the one carrying the shard environment.

    EXACTLY one, and that is the assertion rather than a convenience. The first version took
    the last match in a loop, so appending a decoy step carrying the correct
    `${{ strategy.* }}` values let the real step hard-code `SYSOP_SHARD_COUNT: '8'` — four
    legs against a count of eight, half the suite running on no machine, every check green.
    """
    steps = wf["jobs"]["shard"]["steps"]
    owned = [s for s in steps
             if isinstance(s.get("env"), dict)
             and (SHARD_ID_VAR in s["env"] or SHARD_COUNT_VAR in s["env"])]
    assert len(owned) == 1, (
        f"{len(owned)} steps in the `shard` job carry shard environment; there must be "
        "exactly one. More than one means a guard reading 'the' step is reading whichever "
        "it happened to match, and the other can say anything."
    )
    return owned[0]


def _the_gate_step(wf):
    """The one step that gates on the shards: the one reading `needs.shard.result`.

    Located by content for the same reason. `steps[0]` both reds on an innocent extra step
    and passes when a decoy first step merely echoes the right words.
    """
    steps = wf["jobs"]["pytest"]["steps"]
    owned = [s for s in steps if "needs.shard.result" in str(s.get("run", ""))]
    assert len(owned) == 1, (
        f"{len(owned)} steps in the `pytest` job read `needs.shard.result`; there must be "
        "exactly one, or the gate is whichever one a reader happens to find."
    )
    return owned[0]


#: Arguments that narrow what runs. Any of these on the suite's own invocation means the
#: merge gate is testing a subset while reporting on the whole.
_NARROWING = ("-k", "-m", "--ignore", "--ignore-glob", "--deselect", "--collect-only",
              "--co", "--lf", "--ff", "--nf", "--sw", "--stepwise")


def test_the_required_check_is_an_aggregator_that_gates_on_the_shards():
    """Branch protection requires the context `pytest`. A matrix leg cannot carry it.

    The legs report as `shard (1)`, `shard (2)`, ... and none of them is `pytest`, so the
    name has to live on a job that depends on all of them. If this ever fails, branch
    protection and this file have diverged and PRs are gated by something other than the
    suite.
    """
    jobs = _workflow()["jobs"]
    assert "pytest" in jobs, (
        "no job named `pytest`. Branch protection on `main` requires that context; without "
        "a job producing it every PR blocks forever."
    )
    assert "shard" in jobs, "no job named `shard` for the aggregator to gate on"
    assert "strategy" not in jobs["pytest"], (
        "the `pytest` job grew a matrix -- its legs would report as `pytest (1)` and the "
        "required context `pytest` would never appear again"
    )
    needs = jobs["pytest"]["needs"]
    needs = [needs] if isinstance(needs, str) else needs
    assert "shard" in needs, (
        "`pytest` does not depend on `shard`, so it reports green without waiting for the suite"
    )
    assert "strategy" in jobs["shard"] and "matrix" in jobs["shard"]["strategy"], (
        "the `shard` job has no matrix, so there is nothing to shard across"
    )


def test_the_step_that_carries_the_shard_environment_is_the_step_that_runs_the_suite():
    """The env and the invocation must be the same step, or neither describes the other.

    Split across two steps, the guards below check a step that runs nothing and the step
    that runs the suite is unconstrained.
    """
    step = _the_test_step(_workflow())
    lines = [l.strip() for l in str(step.get("run", "")).splitlines() if l.strip()]
    invocations = [l for l in lines if l.split() and l.split()[0] in ("pytest", "python", "python3")]
    assert invocations, (
        "the step carrying the shard environment never invokes pytest:\n"
        + "\n".join(lines)
    )


def test_the_suites_own_invocation_is_not_narrowed_or_made_advisory():
    """`run: pytest` is the whole gate, and nothing read it until the round.

    Each of these turns the required check into a green light over nothing, and every one is
    a one-line edit that looks like tidying: `pytest -k shard`, `pytest --ignore=...`,
    `echo skipping pytest`, `pytest || true`, `if: false`, `continue-on-error: true`.
    """
    wf = _workflow()
    step = _the_test_step(wf)
    run = str(step.get("run", ""))
    lines = [l.strip() for l in run.splitlines() if l.strip()]
    pytest_lines = [l for l in lines if l.split() and l.split()[0] == "pytest"]
    assert len(pytest_lines) == 1, (
        f"expected exactly one bare `pytest` invocation in the test step, found "
        f"{len(pytest_lines)}:\n{run}"
    )
    invocation = pytest_lines[0]
    tokens = invocation.split()[1:]

    for bad in _NARROWING:
        assert not any(tok == bad or tok.startswith(bad + "=") for tok in tokens), (
            f"the suite's own invocation carries `{bad}`, so the merge gate runs a subset "
            f"while reporting on the whole: {invocation!r}"
        )
    positional = [tok for tok in tokens if not tok.startswith("-")]
    assert not positional, (
        f"the invocation names paths ({positional}), so it runs those rather than the "
        f"suite: {invocation!r}"
    )
    assert not re.search(r"(\|\||;)\s*(true|:)\s*$", invocation), (
        f"the invocation's failure is swallowed, so a red suite reports green: {invocation!r}"
    )
    assert "if" not in step, (
        f"the step that runs the suite carries an `if:` ({step.get('if')!r}). A skipped step "
        "leaves the job successful and the aggregator green over a suite that never ran."
    )
    for holder, what in ((step, "step"), (wf["jobs"]["shard"], "job")):
        assert holder.get("continue-on-error") in (None, False), (
            f"`continue-on-error` is set on the {what}, which makes every test failure "
            "advisory and the required check green over a red suite"
        )


def test_the_aggregator_demands_success_and_not_merely_the_absence_of_failure():
    """`skipped` and `cancelled` are the states in which nothing ran.

    A gate written as `!= failure` calls both of them green. Read off the step located by
    content, and quote-agnostic: the round reddened a control that only changed `"success"`
    to `'success'`.
    """
    run = str(_the_gate_step(_workflow())["run"])
    assert re.search(r"""!=\s*["']?success["']?""", run), (
        "the aggregator does not compare the shard result against `success`. Anything "
        "weaker lets `skipped` and `cancelled` certify a suite that never ran:\n" + run
    )
    assert not re.search(r"""(!=|=)\s*["']?(failure|cancelled)\b""", run), (
        "the aggregator tests against `failure`/`cancelled` by name. Enumerating the bad "
        "states means a new one is green by default; require the good one instead:\n" + run
    )
    assert re.search(r"\bexit\s+[1-9]", run), (
        f"the aggregator never exits non-zero, so its refusal is a message and not a gate:\n{run}"
    )
    assert not re.search(r"if\s+false\s*;", run), f"the exit is parked behind `if false`:\n{run}"


def test_the_aggregator_reports_on_every_pull_request_even_when_a_shard_fails():
    """A required check that does not RUN never reports, and blocks the PR forever.

    `always()` turns a failing shard into a failing check rather than a stuck one. The
    negation is checked separately because `... != 'pull_request'` contains both of the
    tokens a substring check would look for, and inverts the whole gate.
    """
    cond = str(_workflow()["jobs"]["pytest"]["if"])
    assert "always()" in cond, (
        "the aggregator is not `always()`, so a failed shard leaves the required check "
        f"unreported and the PR unmergeable rather than red: {cond!r}"
    )
    assert re.search(r"event_name\s*==\s*'pull_request'", cond), (
        f"the aggregator is not scoped TO pull_request: {cond!r}"
    )
    assert not re.search(r"event_name\s*!=\s*'pull_request'", cond), (
        f"the aggregator is scoped AWAY from pull_request, so the required check never "
        f"runs on a PR and every PR blocks forever: {cond!r}"
    )


def test_both_shard_numbers_are_read_off_the_matrix_and_neither_is_written_by_hand():
    """The one failure the aggregator structurally cannot see.

    Four legs and a hand-written count of five runs a fifth of the suite on no machine at
    all, and every check is green -- the aggregator only knows whether the legs that EXIST
    succeeded. Deriving the id from `strategy.job-index` and the count from
    `strategy.job-total` removes the second number, so there is nothing left to disagree.
    """
    env = _the_test_step(_workflow())["env"]
    assert env.get(SHARD_ID_VAR) == "${{ strategy.job-index }}", (
        f"{SHARD_ID_VAR} is not read off the matrix: {env.get(SHARD_ID_VAR)!r}"
    )
    assert env.get(SHARD_COUNT_VAR) == "${{ strategy.job-total }}", (
        f"{SHARD_COUNT_VAR} is not read off the matrix: {env.get(SHARD_COUNT_VAR)!r}. A "
        "literal here can disagree with the matrix width, which is the one way to run a "
        "slice of the suite nowhere with every check green."
    )


def test_every_matrix_leg_reports_even_when_a_sibling_fails():
    strategy = _workflow()["jobs"]["shard"]["strategy"]
    assert strategy.get("fail-fast") in (False, "false", "no"), (
        "fail-fast is not disabled, so the first red shard cancels the other three and a "
        "run names one failure out of however many there were"
    )


def test_the_suite_still_runs_whole_on_one_machine_off_pull_request():
    """The nightly keeps the full population, and that is load-bearing, not leftover.

    `Q-466` is a flake that needs the whole ~6,600-test population under contention to
    surface at all. Sharding changes that contention profile, so if EVERY run were sharded
    the class would stop being observable anywhere. The nightly is now the only run that
    preserves it.
    """
    matrix = str(_workflow()["jobs"]["shard"]["strategy"]["matrix"]["shard"])
    assert "fromJSON" in matrix, (
        f"the matrix is no longer event-conditional: {matrix!r}. Off a pull request the "
        "suite must run as ONE leg, or nothing sees the full population any more."
    )
    branches = re.findall(r"'(\[[^\]]*\])'", matrix)
    assert len(branches) == 2, f"expected a two-branch matrix expression: {matrix!r}"
    on_pr, off_pr = (json.loads(b) for b in branches)
    assert len(on_pr) >= 2, f"the pull_request branch is not sharded at all: {on_pr}"
    assert len(off_pr) == 1, (
        f"the non-pull_request branch is {len(off_pr)} legs, not one: {off_pr}. Sharding "
        "the nightly leaves nothing running the full population under contention."
    )


def test_the_workflow_has_no_path_filter():
    """`Q-465` names this as the wrong fix, and the file's own header forbids it.

    This suite is largely a DOC test -- phase-log currency, the mirror leak gate, the ledger
    schema, the prose pins -- so a filter skipping `.md` disarms real guards exactly when
    they matter. A skipped workflow also never reports, which blocks a required check forever.
    """
    for event, spec in _triggers(_workflow()).items():
        if not isinstance(spec, dict):
            continue
        for key in ("paths", "paths-ignore"):
            assert key not in spec, (
                f"`{event}` grew a `{key}` filter. A doc-only change would then skip the "
                "suite that reads the docs, and a skipped required check never reports."
            )


def test_the_nightly_still_declines_to_run_on_the_mirrors():
    """The deny-list survived being moved onto the sharded job.

    `.github/` is mirrored to both the public repo and the private tester repo, and both
    have Actions. Counted as DISTINCT repositories rather than as `!=` occurrences -- the
    round duplicated one mirror to satisfy a `count("!=") >= 2` check and started a daily
    billed run on the other.
    """
    cond = str(_workflow()["jobs"]["shard"]["if"])
    assert "schedule" in cond, "the nightly is no longer scoped at all"
    denied = set(re.findall(r"repository\s*!=\s*'([^']+)'", cond))
    assert len(denied) >= 2, (
        f"the deny-list names {len(denied)} distinct repositories ({sorted(denied)}); both "
        "mirrors have to be named, and a duplicate of one does not cover the other."
    )
    assert not re.search(r"repository\s*==", cond), (
        f"the deny-list turned into an allow-list: {cond!r}. Keyed to this repo's name it "
        "would stop the nightly silently on the next rename."
    )
