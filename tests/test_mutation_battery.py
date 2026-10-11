"""Guards for `tools/mutation_battery.py` (Phase 187).

THE MIRROR BOUNDARY, WHICH IS WHY THIS MODULE SKIPS RATHER THAN FAILS
--------------------------------------------------------------------
``tools/*`` is removed from the public mirror (``tools/make_public_mirror.sh``, pinned by
``tests/test_mirror_leak_gate.py``), so ``tools/mutation_battery.py`` does not exist in
the sterilized tree. The public repo runs ``pytest`` as a required check, so a module that
imported it unconditionally would fail there. Same shape as
``tests/test_skill_audit_refs.py``, which established it.

WHY A MAINTAINER SCRIPT GETS TESTS AT ALL
-----------------------------------------
Because the numbers it prints are what the review governor reads. Nine hand-rolled
batteries preceded this one and the corpus's own records say the harness lied about its
result four separate times — a stale ``.pyc`` reporting a kill that never ran, a missing
anchor scored as a survivor, ``pytest`` exiting without running scored as a kill, and two mutations that
changed text without changing behaviour scored as results. Every test below is one of
those incidents, driven end to end against a throwaway tree.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "mutation_battery.py"


def _mod():
    if not SCRIPT.is_file():
        pytest.skip(
            "tools/mutation_battery.py is maintainer-side and excluded from the public "
            "mirror; its guards only apply in the source repo"
        )
    spec = importlib.util.spec_from_file_location("mutation_battery", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def mb():
    return _mod()


# --------------------------------------------------------------------------------------
# A throwaway subject tree: one "shipped" file carrying a marker, and one pytest module
# that guards it. The battery then mutates the shipped file and scores the guard.
# --------------------------------------------------------------------------------------

# Two gates rather than one, and both greps written identically. That is not decoration:
# `replace(old, new, 1)` on `grep -rniE` silently retargets onto the FIRST one, which is
# the defect Phase 170 lost two mutations to and the reason the ambiguity check exists.
# `$TARGET` comes from `$1` so the effect probe can pin the script's output by passing
# `/dev/null`.
SUBJECT = """\
#!/usr/bin/env bash
set -euo pipefail
TARGET="${1:-.}"

hard() { echo "$1"; }

hard "Gate A — the early one"
  grep -rniE 'internal' "$TARGET" || true

hard "Gate B — the late one"
  grep -rniE 'secret' "$TARGET" || true

echo "GATE GREEN"
"""

GUARD = '''\
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def test_both_gates_grep_case_insensitively():
    assert (ROOT / "subject.sh").read_text().count("grep -rniE") == 2


def test_the_gate_announces_itself():
    assert 'echo "GATE GREEN"' in (ROOT / "subject.sh").read_text()
'''

# Unique anchors, so a test that is not *about* ambiguity does not trip it.
LATE_GREP = "grep -rniE 'secret'"
EARLY_GREP = "grep -rniE 'internal'"
PROBE = "bash subject.sh /dev/null"


@pytest.fixture()
def tree(tmp_path):
    (tmp_path / "subject.sh").write_text(SUBJECT, encoding="utf-8")
    (tmp_path / "test_guard.py").write_text(GUARD, encoding="utf-8")
    return tmp_path


def _battery(mb, tree, mutations, verifiers=None, **kw):
    return mb.Battery(
        root=tree,
        default_target=tree / "subject.sh",
        verifiers=verifiers or [mb.Verifier("guard", modules=["test_guard.py"])],
        mutations=mutations,
        **kw,
    )


# --------------------------------------------------------------------------------------
# Kill / survive / control — the base contract
# --------------------------------------------------------------------------------------


def test_a_real_mutation_is_killed_and_exits_zero(mb, tree, capsys):
    rc = _battery(mb, tree, [
        mb.Mutation("M1", "what it matches on", old=LATE_GREP,
                    new=LATE_GREP.replace("-rniE", "-rnE")),
    ]).main([])
    assert rc == 0, capsys.readouterr().out
    assert "1/1 killed" in capsys.readouterr().out


def test_an_uncovered_mutation_survives_and_exits_one(mb, tree, capsys):
    rc = _battery(mb, tree, [
        mb.Mutation("M2", "where it looks", old="set -euo pipefail", new="set -uo pipefail"),
    ]).main([])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "SURVIVORS" in out and "M2" in out


def test_a_negative_control_that_reddens_is_a_false_kill(mb, tree, capsys):
    """Over-strictness is the direction that gets a correct guard deleted instead of
    fixed, and a battery with no controls cannot see it."""
    rc = _battery(mb, tree, [
        mb.Mutation("N1", "over-strictness", kind="control",
                    old='hard "Gate B — the late one"',
                    new='hard "Gate B — the final one"'),
        mb.Mutation("N2", "over-strictness", kind="control",
                    old='echo "GATE GREEN"', new='echo  "GATE GREEN"'),
    ]).main([])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "FALSE KILLS" in out and "N2" in out
    assert "N1" not in out.split("FALSE KILLS")[1]


# --------------------------------------------------------------------------------------
# Incident 1 — a missing anchor scored as a SURVIVOR (three of the nine did this)
# --------------------------------------------------------------------------------------


def test_a_stale_anchor_is_not_a_survivor(mb, tree, capsys):
    rc = _battery(mb, tree, [
        mb.Mutation("S1", "what it matches on", old="text that is not there", new="x"),
    ]).main([])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "STALE / AMBIGUOUS ANCHORS" in out
    assert "SURVIVORS" not in out
    assert "0/0 killed" in out


def test_an_ambiguous_anchor_is_refused_rather_than_silently_taking_the_first(mb, tree, capsys):
    """Phase 170 lost two mutations to a `str.index` that retargeted onto an
    identically-shaped line in an earlier function. Every battery calls
    `replace(old, new, 1)`; only one of nine checked the anchor was unique."""
    rc = _battery(mb, tree, [
        mb.Mutation("A1", "what it matches on", old="grep -rniE", new="grep -rnE"),
    ]).main([])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "occurs" in out and "occurrence= or region=" in out


def test_an_explicit_occurrence_resolves_the_ambiguity(mb, tree, capsys):
    rc = _battery(mb, tree, [
        mb.Mutation("A2", "what it matches on", old="grep -rniE", new="grep -rnE",
                    occurrence=2),
    ]).main([])
    out = capsys.readouterr().out
    assert "ANCHOR-AMBIGUOUS" not in out, out
    assert rc in (0, 1), out


def test_region_scoping_disambiguates_without_an_index(mb, tree, capsys):
    rc = _battery(mb, tree, [
        mb.Mutation("A3", "what it matches on", old="grep -rniE", new="grep -rnE",
                    region=('hard "Gate B', 'echo "GATE')),
    ]).main([])
    out = capsys.readouterr().out
    assert "ANCHOR-AMBIGUOUS" not in out, out


# --------------------------------------------------------------------------------------
# Incident 2 — a derived anchor, so an edit to the subject does not silently skip a row
# --------------------------------------------------------------------------------------


def test_a_derived_anchor_tracks_the_file(mb, tree, capsys):
    """Phase 186 hand-copied two gate lines as constants; its own round-driven fixes
    edited those lines and seven mutations reported SKIPPED. `line_after` re-derives at
    run time, so the anchor follows the edit."""
    subject = tree / "subject.sh"
    subject.write_text(subject.read_text().replace("Gate B — the late one",
                                                   "Gate B — renamed"))
    rc = _battery(mb, tree, [
        mb.Mutation("D1", "what it matches on",
                    old=mb.line_after('hard "Gate B'),
                    new=lambda old: old.replace("grep -rniE", "grep -rnE")),
    ]).main([])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "1/1 killed" in out


def test_a_derived_anchor_whose_marker_is_gone_is_a_scored_row_not_a_crash(mb, tree, capsys):
    rc = _battery(mb, tree, [
        mb.Mutation("D2", "what it matches on",
                    old=mb.line_after("no such marker"), new="x"),
    ]).main([])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "marker not found" in out


def test_line_after_refuses_a_non_unique_marker(mb):
    with pytest.raises(mb.AnchorError, match="not unique"):
        mb.line_after("a")("a\nb\na\n")
    with pytest.raises(mb.AnchorError, match="outside the file"):
        mb.line_after("b")("a\nb")


# --------------------------------------------------------------------------------------
# Incident 3 — a no-op scored as a result
# --------------------------------------------------------------------------------------


def test_a_textual_noop_is_neither_killed_nor_surviving(mb, tree, capsys):
    rc = _battery(mb, tree, [
        mb.Mutation("T1", "what it accepts", old=LATE_GREP, new=LATE_GREP),
    ]).main([])
    out = capsys.readouterr().out
    assert "NO-OPS" in out and "byte-identical" in out
    assert "SURVIVORS" not in out
    assert "0/0 killed" in out
    assert rc == 0


def test_an_effect_probe_demotes_a_behaviour_preserving_mutation_to_a_noop(mb, tree, capsys):
    """The class the nine batteries had no mechanism for, and the hard half of this file.

    Phase 186 shipped two mutations that changed text without changing behaviour and
    scored both as results: `… || true | head -0` short-circuits when grep matches, and
    dropping `-e` was inert once the gate stopped trusting it. A textual `old != new`
    check catches neither — both changed the text.

    Here the guard pins `grep -rniE` twice, so dropping the `i` from EITHER grep reddens
    it. Against `/dev/null` neither grep can match, so the script's observable output is
    identical before and after. That is a guard kill on a mutation that changed no
    behaviour — precisely the row that must not be counted as evidence of coverage. The
    probe runs the subject both ways and demotes it.
    """
    battery = _battery(mb, tree, [
        mb.Mutation("P2", "what it accepts",
                    old=EARLY_GREP, new=EARLY_GREP.replace("-rniE", "-rnE"),
                    effect=PROBE),
    ])
    rc = battery.main([])
    out = capsys.readouterr().out
    assert "NO-OPS" in out and "the behaviour did not" in out, out
    assert "1/1 killed" not in out, "a behaviour-preserving mutation was scored as a kill"
    assert rc == 0, out


def test_an_effect_probe_leaves_a_live_mutation_scored(mb, tree, capsys):
    """The other direction — the control for the test above. Without it, an `effect=`
    that always reported NO-OP would look like a working probe."""
    battery = _battery(mb, tree, [
        mb.Mutation("P1", "what it accepts",
                    old='echo "GATE GREEN"', new='echo "GATE RED"',
                    effect=PROBE),
    ])
    rc = battery.main([])
    out = capsys.readouterr().out
    assert "NO-OPS" not in out, out
    assert "1/1 killed" in out, out
    assert rc == 0
    assert "0 of 1 defect mutations carry no `effect=` probe" in out


def test_the_unprobed_count_is_always_reported(mb, tree, capsys):
    """The honest half: with no probe the battery cannot distinguish a live hole from a
    no-op, and it has to say so rather than let a bare fraction imply otherwise."""
    _battery(mb, tree, [
        mb.Mutation("U1", "what it matches on", old=LATE_GREP,
                    new=LATE_GREP.replace("-rniE", "-rnE")),
    ]).main([])
    out = capsys.readouterr().out
    assert "1 of 1 defect mutations carry no `effect=` probe" in out
    assert "may be a live hole or may be a no-op" in out


def test_a_declared_equivalent_mutant_reports_its_kill_as_the_finding(mb, tree, capsys):
    rc = _battery(mb, tree, [
        mb.Mutation("E1", "vacuity", kind="equivalent",
                    old='echo "GATE GREEN"', new='printf "GATE GREEN\\n"'),
    ]).main([])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "DECLARED-EQUIVALENT MUTANTS THAT WERE KILLED" in out


# --------------------------------------------------------------------------------------
# Incident 4 — a red baseline, and pytest exit 5
# --------------------------------------------------------------------------------------


def test_a_red_baseline_aborts_before_any_mutation(mb, tree, capsys):
    (tree / "subject.sh").write_text("nothing the guard asserts\n", encoding="utf-8")
    rc = _battery(mb, tree, [
        mb.Mutation("X", "vacuity", old="nothing", new="something"),
    ]).main([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "already red" in err and "measures nothing" in err


def test_a_verifier_that_collects_nothing_is_a_setup_failure_not_a_kill(mb, tree, capsys):
    """Phase 158 nominated a test by `-k`, the name had been renamed, pytest selected
    nothing and exited 5, and the harness reported KILLED with zero assertions run."""
    rc = _battery(mb, tree, [
        mb.Mutation("K1", "reachability", old="def test_the_gate_announces_itself",
                    new="def test_renamed_by_the_change",
                    target=tree / "test_guard.py"),
    ], verifiers=[mb.Verifier(
           "pinned", modules=["test_guard.py::test_the_gate_announces_itself"])]).main([])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "SETUP FAILURES" in out
    assert "killed" not in out.split("SETUP FAILURES")[1]


# --------------------------------------------------------------------------------------
# Restore discipline
# --------------------------------------------------------------------------------------


def test_the_tree_is_byte_identical_afterwards(mb, tree):
    before = {p.name: p.read_bytes() for p in tree.iterdir() if p.is_file()}
    _battery(mb, tree, [
        mb.Mutation("R1", "what it matches on", old=LATE_GREP,
                    new=LATE_GREP.replace("-rniE", "-rnE")),
        mb.Mutation("R2", "where it looks", old="set -euo pipefail", new="set -uo pipefail"),
    ]).main([])
    after = {p.name: p.read_bytes() for p in tree.iterdir() if p.is_file()}
    assert after == before


def test_every_target_is_snapshotted_not_only_the_default(mb, tree):
    """Phase 186's outer `finally` restored one file while two rows mutated others."""
    other = tree / "second.sh"
    other.write_text("echo second\n", encoding="utf-8")
    battery = _battery(mb, tree, [
        mb.Mutation("R3", "where it looks", old=LATE_GREP,
                    new=LATE_GREP.replace("-rniE", "-rnE")),
        mb.Mutation("R4", "where it looks", old="echo second", new="echo third",
                    target=other),
    ])
    battery._snapshot()
    assert set(battery._originals) == {tree / "subject.sh", other}


def test_an_interrupted_row_still_restores(mb, tree):
    """The `finally` is per row, so a verifier that explodes cannot leave the mutation in
    the tree — Phase 182's battery did exactly that."""
    subject = tree / "subject.sh"
    original = subject.read_text(encoding="utf-8")
    battery = _battery(mb, tree, [
        mb.Mutation("R5", "what it matches on", old=LATE_GREP,
                    new=LATE_GREP.replace("-rniE", "-rnE")),
    ])
    battery._python = sys.executable
    battery._snapshot()

    def boom(_verifier):
        raise KeyboardInterrupt  # noqa: the point is the finally

    battery._run_verifier = boom
    with pytest.raises(KeyboardInterrupt):
        battery.run(battery.mutations)
    assert subject.read_text(encoding="utf-8") == original


# --------------------------------------------------------------------------------------
# Bytecode staleness — the defect that made a battery report a kill that never ran
# --------------------------------------------------------------------------------------


def test_pycache_is_cleared_and_bytecode_writing_is_off(mb, tmp_path, monkeypatch):
    """CPython validates a `.pyc` on `(int(mtime), size)`, so a same-size revert inside
    one second reuses stale bytecode. Phase 172's first two runs reported 40/40 killed
    with 7/7 controls red on that alone, and Phase 181 recorded both its fractions as
    upper bounds for the same reason."""
    cache = tmp_path / "pkg" / "__pycache__"
    cache.mkdir(parents=True)
    stale = cache / "mod.cpython-000.pyc"
    stale.write_bytes(b"stale")
    mb._clear_pycache(tmp_path)
    assert not stale.exists()
    # Deleted first, deliberately: this battery sets the variable in the env of every
    # subprocess it launches, so a run OF the battery inherits it and the assertion below
    # passed with the line deleted from `_child_env`. Found by the phase's own battery.
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    assert mb._child_env()["PYTHONDONTWRITEBYTECODE"] == "1"


def test_a_same_size_mutation_is_still_scored_correctly(mb, tmp_path):
    """The end-to-end form of the test above: mutate a *test module* by a byte-preserving
    swap, twice in a row, and both runs must agree. Without the cache clearing the second
    read comes from `__pycache__`."""
    (tmp_path / "subject.sh").write_text("MARKER_A\n", encoding="utf-8")
    (tmp_path / "test_guard.py").write_text(
        'from pathlib import Path\n'
        'def test_a():\n'
        '    assert "MARKER_A" in (Path(__file__).parent / "subject.sh").read_text()\n',
        encoding="utf-8",
    )
    for _ in range(2):
        battery = mb.Battery(
            root=tmp_path,
            default_target=tmp_path / "subject.sh",
            verifiers=[mb.Verifier("guard", modules=["test_guard.py"])],
            mutations=[mb.Mutation("Z", "what it accepts", old="MARKER_A", new="MARKER_B")],
        )
        assert battery.run(battery.mutations) == 0
        assert battery.rows[0].verdict == "killed"


# --------------------------------------------------------------------------------------
# Interpreter resolution and git hermeticity
# --------------------------------------------------------------------------------------


def _git(cwd, *args):
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               GIT_AUTHOR_NAME="F", GIT_AUTHOR_EMAIL="f@e.invalid",
               GIT_COMMITTER_NAME="F", GIT_COMMITTER_EMAIL="f@e.invalid")
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True,
                          text=True, check=True)


def test_collateral_damage_outside_the_declared_targets_is_reported(mb, tree, capsys):
    """The detector added BECAUSE this phase's battery destroyed its own tree, twice.

    Every other test here uses a bare `tmp_path` as `root`, which is not a git tree — so
    `_tree_state()` returned None, the comparison branch was dead, and deleting the whole
    mechanism left this module green. Found by the round's guard lens. This one makes the
    root a real repo and has a mutation cause a write the battery never declared.
    """
    _git(tree, "init", "-q", ".")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-q", "-m", "fixture")

    stray = tree / "stray.txt"
    (tree / "test_guard.py").write_text(
        (tree / "test_guard.py").read_text(encoding="utf-8")
        + f'\n\ndef test_side_effect():\n    open({str(stray)!r}, "w").write("x")\n',
        encoding="utf-8")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-q", "-m", "side effect")

    battery = _battery(mb, tree, [
        mb.Mutation("CD", "what it accepts", old=LATE_GREP,
                    new=LATE_GREP.replace("-rniE", "-rnE")),
    ])
    rc = battery.main([])
    err = capsys.readouterr().err
    assert "COLLATERAL DAMAGE" in err, err
    assert rc == 2
    assert stray.exists(), "the fixture did not actually produce collateral damage"


def test_a_clean_run_reports_no_collateral_damage(mb, tree, capsys):
    """The control: the detector must not fire on every run in a git tree."""
    _git(tree, "init", "-q", ".")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-q", "-m", "fixture")
    rc = _battery(mb, tree, [
        mb.Mutation("CD2", "what it accepts", old=LATE_GREP,
                    new=LATE_GREP.replace("-rniE", "-rnE")),
    ]).main([])
    out, err = capsys.readouterr()
    assert "COLLATERAL DAMAGE" not in err, err
    assert rc == 0, out


def test_the_post_run_restore_check_catches_a_tree_left_red(mb, tree, capsys):
    """The re-verification after the loop. Deleting it left this module green."""
    battery = _battery(mb, tree, [
        mb.Mutation("RC", "what it accepts", old=LATE_GREP,
                    new=LATE_GREP.replace("-rniE", "-rnE")),
    ])
    real_restore = battery._restore_all

    def restore_but_corrupt():
        real_restore()
        (tree / "subject.sh").write_text("corrupted\n", encoding="utf-8")
        return True

    battery._restore_all = restore_but_corrupt
    rc = battery.run(battery.mutations)
    assert rc == 2
    assert "RESTORE CHECK FAILED" in capsys.readouterr().err


def test_an_empty_resolved_anchor_is_stale_not_a_mutation(mb, tree, capsys):
    rc = _battery(mb, tree, [
        mb.Mutation("EA", "what it matches on", old=lambda _t: "", new="x"),
    ]).main([])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "empty string" in out


def test_a_verifier_killed_by_a_signal_is_not_a_kill(mb, tree, capsys):
    """A negative return code means the process died, having run an unknown fraction of
    its assertions. Scored RED it reports a kill that may never have executed."""
    rc = _battery(mb, tree, [
        mb.Mutation("SG", "what it accepts", old=LATE_GREP,
                    new=LATE_GREP.replace("-rniE", "-rnE")),
    ], verifiers=[mb.Verifier("suicide", argv=[
        # Green on the pristine tree, killed by a signal once the anchor is gone — so the
        # green-start check passes and the SIGNAL happens during scoring, which is the
        # only arrangement where the bug could ever be observed.
        "bash", "-c", "grep -q \"rniE 'secret'\" subject.sh || kill -9 $$"])]).main([])
    out = capsys.readouterr().out
    assert "SETUP FAILURES" in out, out
    assert "killed by signal 9" in out
    assert rc == 2


def test_occurrence_counts_the_same_way_the_ambiguity_check_does(mb, tree):
    """`str.count` is non-overlapping. A `+1` step made `occurrence=2` land on an index
    `count` had never counted — the two numbers must mean the same thing."""
    battery = _battery(mb, tree, [mb.Mutation("OV", "what it matches on",
                                              old="aa", new="ZZ", occurrence=2)])
    mutated, status, _ = battery._apply(battery.mutations[0], "aaaa\n")
    assert status == "", status
    assert mutated == "aaZZ\n", mutated


def test_json_survives_a_target_outside_the_root(mb, tree, tmp_path):
    """The writer runs AFTER the whole battery; a bare `relative_to` threw the entire
    report away for a row whose target sits elsewhere."""
    outside = tmp_path.parent / "outside.sh"
    outside.write_text("MARKER\n", encoding="utf-8")
    out = tmp_path / "r.json"
    battery = _battery(mb, tree, [
        mb.Mutation("J1", "what it accepts", old=LATE_GREP,
                    new=LATE_GREP.replace("-rniE", "-rnE")),
        mb.Mutation("J2", "what it accepts", old="MARKER", new="OTHER", target=outside),
    ])
    battery.main(["--json", str(out)])
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert {r["id"] for r in rows} == {"J1", "J2"}
    assert any(r["target"].endswith("outside.sh") for r in rows)


def test_the_atexit_net_restores_after_an_uncaught_exception(mb, tree):
    """`finally` does not run for every exit path; `atexit` is the third net and nothing
    drove it. Run in a subprocess so the interpreter really exits."""
    script = tree / "runner.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPT.parent)!r})\n"
        "from mutation_battery import Battery, Mutation, Verifier\n"
        "from pathlib import Path\n"
        f"ROOT = Path({str(tree)!r})\n"
        "b = Battery(root=ROOT, default_target=ROOT/'subject.sh',\n"
        "            verifiers=[Verifier('g', modules=['test_guard.py'])],\n"
        f"            mutations=[Mutation('A','what it accepts',old={LATE_GREP!r},new='X')])\n"
        "b._python = sys.executable\n"
        "b._snapshot(); b._install_guards()\n"
        "(ROOT/'subject.sh').write_text('WRECKED\\n')\n"
        "raise SystemExit(7)\n",
        encoding="utf-8")
    before = (tree / "subject.sh").read_text(encoding="utf-8")
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert proc.returncode == 7, proc.stderr
    assert (tree / "subject.sh").read_text(encoding="utf-8") == before, (
        "atexit did not restore the tree after an uncaught exit")


def test_resolve_python_prefers_the_running_interpreter(mb, tmp_path):
    """Phase 186 hardcoded `<root>/.venv/bin/python3`; a reviewer in an isolated worktree
    has no `.venv` there and could not run the file the record cited as its evidence.

    The `.venv` IS PLANTED, and that is the whole test. Without it both orderings return
    `sys.executable` and the assertion cannot discriminate — reordering the candidate
    tuple back to venv-first survived the phase's own battery on exactly that basis.
    """
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    shim = venv / "python3"
    shim.write_text(f"#!/bin/sh\nexec {sys.executable} \"$@\"\n", encoding="utf-8")
    shim.chmod(0o755)
    assert shim.exists(), "the fixture did not plant a .venv, so this proves nothing"
    assert mb.resolve_python(tmp_path) == sys.executable, (
        "a hardcoded/preferred .venv won over the running interpreter — the exact shape "
        "that left a reviewer in a worktree unable to run the battery")


def test_resolve_python_falls_back_when_the_runner_cannot_import_pytest(mb, tmp_path,
                                                                       monkeypatch):
    """The other direction, so the ordering is pinned rather than the winner."""
    venv = tmp_path / ".venv" / "bin"
    venv.mkdir(parents=True)
    shim = venv / "python3"
    shim.write_text(f"#!/bin/sh\nexec {sys.executable} \"$@\"\n", encoding="utf-8")
    shim.chmod(0o755)
    monkeypatch.setattr(mb.sys, "executable", "/nonexistent/python3")
    assert mb.resolve_python(tmp_path) == str(shim)


def test_the_child_env_strips_gits_discovery_vars(mb, monkeypatch):
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
        monkeypatch.setenv(var, "/some/leaked/path")
    monkeypatch.setenv("SYSOP_SENTINEL", "keep-me")
    env = mb._child_env()
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
        assert var not in env
    assert env["SYSOP_SENTINEL"] == "keep-me"


# --------------------------------------------------------------------------------------
# The report the governor reads
# --------------------------------------------------------------------------------------


def test_the_revert_split_is_printed(mb, tree, capsys):
    """Three of the nine compute this and it is the metric the governor actually reads:
    a set composed mostly of reverts reports wiring, not coverage."""
    _battery(mb, tree, [
        mb.Mutation("V1", "reversion", kind="revert", old=LATE_GREP,
                    new=LATE_GREP.replace("-rniE", "-rnE")),
        mb.Mutation("V2", "what it accepts", old='echo "GATE GREEN"', new='echo "GREEN"'),
    ]).main([])
    out = capsys.readouterr().out
    assert "1 of 2 are declared reverts, 50%" in out
    assert "rule 1 wants this a minority" in out


def test_two_verifiers_attribute_which_column_killed_what(mb, tree, capsys):
    """Phase 186 needed old-guards vs new-harness columns: a mutation killed by the old
    column was already covered, one killed only by the new column is what the phase
    bought, and one killed by neither is a live hole."""
    (tree / "test_new.py").write_text(
        'from pathlib import Path\n'
        'def test_set_e():\n'
        '    assert "set -euo pipefail" in '
        '(Path(__file__).parent / "subject.sh").read_text()\n',
        encoding="utf-8",
    )
    _battery(mb, tree, [
        mb.Mutation("C1", "vacuity", old="set -euo pipefail", new="set -uo pipefail"),
    ], verifiers=[
        mb.Verifier("old", modules=["test_guard.py"]),
        mb.Verifier("new", modules=["test_new.py"]),
    ]).main([])
    out = capsys.readouterr().out
    assert "old: killed 0, of which 0 only by old" in out
    assert "new: killed 1, of which 1 only by new" in out


def test_an_off_list_assumption_class_is_flagged_not_rejected(mb, tree, capsys):
    _battery(mb, tree, [
        mb.Mutation("F1", "vibes", old=LATE_GREP,
                    new=LATE_GREP.replace("-rniE", "-rnE")),
    ]).main([])
    out = capsys.readouterr().out
    assert "name an assumption class rule 1 does not list" in out
    assert "vibes" in out


def test_the_origin_filter_selects_reviewer_rows(mb, tree, capsys):
    """Reviewer-found mutations are kept permanently, not deleted once fixed — they are
    the record of what the author's own sweeps could not see."""
    battery = _battery(mb, tree, [
        mb.Mutation("O1", "what it matches on", old=LATE_GREP,
                    new=LATE_GREP.replace("-rniE", "-rnE")),
        mb.Mutation("O2", "vacuity", origin="reviewer",
                    old="set -euo pipefail", new="set -uo pipefail"),
    ])
    battery.main(["--set", "reviewer", "--list"])
    out = capsys.readouterr().out
    assert "O2" in out and "O1" not in out


def test_the_assumption_classes_match_the_shipped_rule(mb):
    """`ASSUMPTION_CLASSES` is a second copy of rule 1's bullet headings, and two sources
    of truth for one fact is a drift bug waiting to happen. Each shipped heading is paired
    with the class string here, so renaming a bullet in the skill reddens this."""
    rule = (REPO_ROOT / "core" / "skills" / "_shared" / "adversarial-review.md").read_text(
        encoding="utf-8")
    pairs = {
        "**What it matches on.**": "what it matches on",
        "**What it accepts.**": "what it accepts",
        "**Where it looks.**": "where it looks",
        "**Over-strictness, the direction that hides.**": "over-strictness",
        "**Reachability.**": "reachability",
        "**When it runs.**": "when it runs",
    }
    for heading, cls in pairs.items():
        assert heading in rule, f"rule 1 no longer carries the heading {heading!r}"
        assert cls in mb.ASSUMPTION_CLASSES, f"{cls!r} dropped out of ASSUMPTION_CLASSES"
    # The two extras are not bullet headings; they are the declared-test kinds rule 1
    # names in its own first paragraph ("a declared **reversion guard** … or a **vacuity
    # guard**"), so they are pinned to that sentence instead.
    assert "reversion guard" in rule and "vacuity guard" in rule
    assert {"reversion", "vacuity", "source of truth"} <= mb.ASSUMPTION_CLASSES
    assert "**Derive the population from the source of truth" in rule


# --------------------------------------------------------------------------------------
# Configuration errors are refused at construction, not discovered mid-run
# --------------------------------------------------------------------------------------


def test_a_duplicate_mutation_id_is_refused(mb, tree):
    with pytest.raises(ValueError, match="duplicate mutation id"):
        _battery(mb, tree, [
            mb.Mutation("D", "vacuity", old="a", new="b"),
            mb.Mutation("D", "vacuity", old="c", new="d"),
        ])


def test_a_verifier_needs_exactly_one_of_modules_and_argv(mb):
    with pytest.raises(ValueError, match="exactly one"):
        mb.Verifier("bad")
    with pytest.raises(ValueError, match="exactly one"):
        mb.Verifier("bad", modules=["x"], argv=["y"])


def test_an_unknown_kind_is_refused(mb):
    with pytest.raises(ValueError, match="kind"):
        mb.Mutation("Q", "vacuity", old="a", new="b", kind="sortof")


def test_importing_the_module_as_a_script_says_so(mb):
    # `mb` is taken for its skip, not its value: SCRIPT is mirror-excluded, so without the
    # fixture this test runs `python <missing path>` in the sterilized tree — returncode is
    # non-zero for the wrong reason and the stderr assertion fails. Found by the runbook's
    # step-4 suite run inside the built mirror; same class as the Phase-160 defect that
    # rule exists to catch.
    proc = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode != 0
    assert "is a library" in proc.stderr


# --------------------------------------------------------------------------------------
# BLIND-CONTROL — a control the verifier could not have seen (Phase 194)
#
# Phase 189's author battery declared two `kind="control"` rows and both were comment-only
# edits to a Python file whose verifiers were pytest modules. Python discards comments at
# compile time, so neither could have reddened anything; both scored `control ok` and were
# reported as evidence the guards discriminate. These tests pin the refusal AND its scope,
# because the round's own finding was that item 5 shipped with no coverage at all.
# --------------------------------------------------------------------------------------

PY_SUBJECT = '''\
# a leading comment
def predicate(value):
    """A docstring, which IS a runtime object and so is not a comment."""
    if value in ("a", "b"):  # trailing comment
        return True
    return False
'''

PY_GUARD = '''\
import subject_py


def test_predicate_accepts_a():
    assert subject_py.predicate("a")


def test_predicate_rejects_z():
    assert not subject_py.predicate("z")
'''


@pytest.fixture()
def pytree(tmp_path):
    (tmp_path / "subject_py.py").write_text(PY_SUBJECT, encoding="utf-8")
    (tmp_path / "test_pyguard.py").write_text(PY_GUARD, encoding="utf-8")
    return tmp_path


def _pybattery(mb, pytree, mutations, verifiers=None):
    return mb.Battery(
        root=pytree,
        default_target=pytree / "subject_py.py",
        verifiers=verifiers or [mb.Verifier("pyguard", modules=["test_pyguard.py"])],
        mutations=mutations,
    )


def test_a_comment_only_control_on_a_python_target_is_refused(mb, pytree, capsys):
    """The Phase 189 incident itself."""
    rc = _pybattery(mb, pytree, [
        mb.Mutation("N1", "over-strictness", kind="control",
                    old="# a leading comment", new="# a leading comment, reworded"),
    ]).main([])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "BLIND CONTROLS" in out and "N1" in out


def test_a_real_code_control_is_not_refused(mb, pytree, capsys):
    """The discriminator that `NO-OP(effect)` could not draw: a *good* control changes text
    and deliberately does not change behaviour, so a behaviour-based check would flag every
    correct control as vacuous. This one must pass through and score `control ok`."""
    rc = _pybattery(mb, pytree, [
        mb.Mutation("N2", "over-strictness", kind="control",
                    old='    if value in ("a", "b"):',
                    new='    if value == "a" or value == "b":'),
    ]).main([])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "BLIND CONTROLS" not in out
    assert "1 negative controls · false kills: 0" in out


def test_a_docstring_only_control_is_not_refused(mb, pytree, capsys):
    """A docstring is a runtime object, not a comment — `__doc__` is importable and a test
    can assert on it. Refusing docstring edits would be a false refusal."""
    rc = _pybattery(mb, pytree, [
        mb.Mutation("N3", "over-strictness", kind="control",
                    old="A docstring, which IS a runtime object",
                    new="A docstring, which is very much a runtime object"),
    ]).main([])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "BLIND CONTROLS" not in out


def test_a_comment_only_control_on_a_non_python_target_is_not_refused(mb, tree, capsys):
    """Scope. A shell script's comments are not discarded by any compiler, and a guard that
    greps the file text sees them — so the refusal must not fire outside `.py`."""
    rc = _battery(mb, tree, [
        mb.Mutation("N4", "over-strictness", kind="control",
                    old="#!/usr/bin/env bash", new="#!/usr/bin/env bash -\n"),
    ]).main([])
    out = capsys.readouterr().out
    assert "BLIND CONTROLS" not in out, out
    assert rc in (0, 1), out


def test_a_comment_only_control_with_an_argv_verifier_is_not_refused(mb, pytree, capsys):
    """Scope, the other half. An `argv` verifier may run anything — a linter, a docs build,
    a grep — and those legitimately read comments. Only pytest-module verifiers justify the
    'the compiler dropped it' argument."""
    rc = _pybattery(mb, pytree, [
        mb.Mutation("N5", "over-strictness", kind="control",
                    old="# a leading comment", new="# a leading comment, reworded"),
    ], verifiers=[mb.Verifier("grep", argv=["grep", "-q", "leading comment",
                                            "subject_py.py"])]).main([])
    out = capsys.readouterr().out
    assert "BLIND CONTROLS" not in out, out


def test_a_non_control_comment_edit_is_not_refused(mb, pytree, capsys):
    """Scope, third axis. Only `kind="control"` rows are adjudicated; an ordinary mutation
    that happens to edit a comment is a survivor, which is information, not a battery bug."""
    rc = _pybattery(mb, pytree, [
        mb.Mutation("M1", "where it looks",
                    old="# a leading comment", new="# a leading comment, reworded"),
    ]).main([])
    out = capsys.readouterr().out
    assert "BLIND CONTROLS" not in out, out
    assert rc == 1 and "SURVIVORS" in out


def test_a_refused_control_leaves_the_tree_restored(mb, pytree, capsys):
    """A refusal happens at apply time, so the file must never have been written."""
    before = (pytree / "subject_py.py").read_text(encoding="utf-8")
    _pybattery(mb, pytree, [
        mb.Mutation("N6", "over-strictness", kind="control",
                    old="# trailing comment", new="# trailing comment!"),
    ]).main([])
    capsys.readouterr()
    assert (pytree / "subject_py.py").read_text(encoding="utf-8") == before


def test_blind_ok_is_an_explicit_per_row_escape(mb, pytree, capsys):
    """The over-strictness direction, found by the round: this repo has guards that read
    `.py` files as raw TEXT (`tests/test_flag_contract.py` globs `scripts/*.py` and greps
    `read_text()`), so a comment edit IS visible to them and refusing it is a false
    refusal. `blind_ok=True` is the stated opt-out — refuse by default, override with a
    reason, the same shape `occurrence=` gives the ambiguity check."""
    rc = _pybattery(mb, pytree, [
        mb.Mutation("N7", "over-strictness", kind="control", blind_ok=True,
                    note="the verifier greps this file's text",
                    old="# a leading comment", new="# a leading comment, reworded"),
    ]).main([])
    out = capsys.readouterr().out
    assert "BLIND CONTROLS" not in out, out
    assert rc == 0, out


# --------------------------------------------------------------------------------------
# Killer-first (Phase 347, `Q-618`)
#
# Phase 345's battery ran eight modules for every row, about 30 s a row, and its three runs
# cost about three hours; no phase from 329 on used this module. A defect row now runs its
# `killer=` column first and stops at its first RED. The guarantees pinned here are the
# ones a speedup could quietly break: a column that did not run is never read as green,
# controls and declared-equivalents still run every column, and a verdict is the same in
# both modes. The columns are shell commands that append their name to a log OUTSIDE the
# tree, so the order and the count of calls are observed rather than inferred.
# --------------------------------------------------------------------------------------


@pytest.fixture()
def calls(tmp_path_factory):
    return tmp_path_factory.mktemp("calls") / "log"


def _col(mb, name, log, predicate):
    """A column that logs its call, then is green exactly when `predicate` (bash) holds."""
    return mb.Verifier(name, argv=["bash", "-c", f"echo {name} >> '{log}'; {predicate}"])


# Green on the pristine subject; red once the late grep loses its `i`.
LATE_INTACT = f"grep -qF \"{LATE_GREP}\" subject.sh"
LATE_BROKEN = LATE_GREP.replace("-rniE", "-rnE")


def _logged(log):
    return log.read_text(encoding="utf-8").split() if log.exists() else []


def test_a_defect_row_runs_its_killer_first_and_stops_at_the_first_red(mb, tree, calls, capsys):
    battery = _battery(mb, tree, [
        mb.Mutation("K1", "what it matches on", old=LATE_GREP, new=LATE_BROKEN,
                    killer="fast"),
    ], verifiers=[_col(mb, "slow", calls, LATE_INTACT), _col(mb, "fast", calls, LATE_INTACT)])
    rc = battery.main([])
    out = capsys.readouterr().out
    assert rc == 0, out
    # baseline runs both, in declared order; the row runs `fast` only; the restore check
    # runs both again.
    assert _logged(calls) == ["slow", "fast", "fast", "slow", "fast"], _logged(calls)
    assert battery.rows[0].results == {"fast": "red", "slow": "NOT RUN"}
    assert battery.rows[0].verdict == "killed by fast (1 not run)"
    assert "1/1 killed" in out


def test_without_a_killer_the_declared_order_runs_until_the_first_red(mb, tree, calls):
    battery = _battery(mb, tree, [
        mb.Mutation("K2", "what it matches on", old=LATE_GREP, new=LATE_BROKEN),
    ], verifiers=[_col(mb, "blind", calls, "true"), _col(mb, "sees", calls, LATE_INTACT),
                  _col(mb, "later", calls, LATE_INTACT)])
    battery.main([])
    assert battery.rows[0].results == {"blind": "green", "sees": "red", "later": "NOT RUN"}
    assert battery.rows[0].verdict == "killed by sees (1 not run)"


def test_a_column_that_did_not_run_is_never_reported_green(mb, tree, calls, capsys):
    """NOT RUN is printed as such, and a row that stopped early is in no 'only by' count:
    reading its skipped columns as green would credit the killer with a unique kill."""
    _battery(mb, tree, [
        mb.Mutation("K3", "what it matches on", old=LATE_GREP, new=LATE_BROKEN,
                    killer="a"),
    ], verifiers=[_col(mb, "a", calls, LATE_INTACT), _col(mb, "b", calls, LATE_INTACT)]).main([])
    out = capsys.readouterr().out
    row = next(line for line in out.splitlines() if line.startswith("K3 "))
    assert "NOT RUN" in row and "green" not in row, row
    assert "a: killed 1, of which 0 only by a" in out
    assert "1 row(s) stopped at their first red column" in out


def test_all_columns_runs_every_column_and_attributes_the_kill(mb, tree, calls, capsys):
    battery = _battery(mb, tree, [
        mb.Mutation("K4", "what it matches on", old=LATE_GREP, new=LATE_BROKEN,
                    killer="a"),
    ], verifiers=[_col(mb, "a", calls, LATE_INTACT), _col(mb, "b", calls, LATE_INTACT)])
    battery.main(["--all-columns"])
    out = capsys.readouterr().out
    assert battery.rows[0].results == {"a": "red", "b": "red"}
    assert battery.rows[0].verdict == "killed"
    assert "stopped at their first red" not in out


def test_a_control_runs_every_column_even_after_a_red(mb, tree, calls):
    """A control is scored on its reds, so a column it skipped is a false kill it never
    had the chance to report."""
    battery = _battery(mb, tree, [
        mb.Mutation("N1", "over-strictness", kind="control", old=LATE_GREP, new=LATE_BROKEN,
                    killer="a"),
    ], verifiers=[_col(mb, "a", calls, LATE_INTACT), _col(mb, "b", calls, LATE_INTACT)])
    battery.main([])
    assert battery.rows[0].results == {"a": "red", "b": "red"}
    assert battery.rows[0].verdict == "FALSE-KILL"


def test_a_declared_equivalent_runs_every_column_even_after_a_red(mb, tree, calls):
    battery = _battery(mb, tree, [
        mb.Mutation("E1", "vacuity", kind="equivalent", old=LATE_GREP, new=LATE_BROKEN,
                    killer="a"),
    ], verifiers=[_col(mb, "a", calls, LATE_INTACT), _col(mb, "b", calls, LATE_INTACT)])
    battery.main([])
    assert battery.rows[0].results == {"a": "red", "b": "red"}
    assert battery.rows[0].verdict == "EQUIVALENT-KILLED"


def test_a_partial_kill_is_flagged_only_when_a_column_that_ran_stayed_green(mb, tree, calls, capsys):
    """Phase 347's round blanked the `<<<` flag and every test stayed green. With every
    column run, a kill one column missed is flagged; a killer-first stop is not, because
    its skipped columns say nothing either way."""
    cols = [_col(mb, "sees", calls, LATE_INTACT), _col(mb, "blind", calls, "true")]
    _battery(mb, tree, [mb.Mutation("F1", "what it matches on", old=LATE_GREP, new=LATE_BROKEN)],
             verifiers=cols).main(["--all-columns"])
    row = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("F1 "))
    assert "killed by sees" in row and row.rstrip().endswith("<<<"), row
    _battery(mb, tree, [mb.Mutation("F2", "what it matches on", old=LATE_GREP, new=LATE_BROKEN)],
             verifiers=cols).main([])
    row = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("F2 "))
    assert "killed by sees" in row and "<<<" not in row, row


def test_the_off_list_warning_reads_the_attacks_field(mb, tree, capsys):
    """`attacks=` carries the assumption class; `group=` is a report grouping. `Q-299`
    proposed reading `group=`, which would flag every correctly-classed row."""
    _battery(mb, tree, [mb.Mutation("W1", "what it accepts", group="x", old=LATE_GREP,
                                    new=LATE_BROKEN)]).main([])
    assert "assumption class rule 1 does not list" not in capsys.readouterr().out
    _battery(mb, tree, [mb.Mutation("W2", "the grep loses its i", group="what it accepts",
                                    old=LATE_GREP, new=LATE_BROKEN)]).main([])
    out = capsys.readouterr().out
    assert "1 row(s) name an assumption class rule 1 does not list" in out, out
    assert "the grep loses its i" in out


def test_the_usage_example_names_a_listed_class(mb):
    """A battery copied from the docstring should not trip the off-list warning."""
    m = re.search(r'Mutation\("A01", "([^"]+)"', mb.__doc__)
    assert m and m.group(1) in mb.ASSUMPTION_CLASSES, m and m.group(1)


def test_a_verdict_is_the_same_killer_first_and_all_columns(mb, tree, calls):
    """The speedup must not move a verdict. One row of each outcome, both modes."""
    def rows():
        return [
            mb.Mutation("V1", "what it matches on", old=LATE_GREP, new=LATE_BROKEN,
                        killer="b"),
            mb.Mutation("V2", "where it looks", old="set -euo pipefail",
                        new="set -uo pipefail", killer="b"),
            mb.Mutation("V3", "over-strictness", kind="control",
                        old='hard "Gate A — the early one"', new='hard "Gate A — the first"'),
            mb.Mutation("V4", "over-strictness", kind="control",
                        old='echo "GATE GREEN"', new='echo "GATE"'),
        ]
    cols = [_col(mb, "a", calls, LATE_INTACT),
            _col(mb, "b", calls, 'grep -q "GATE GREEN" subject.sh')]
    fast = _battery(mb, tree, rows(), verifiers=cols)
    fast.main([])
    full = _battery(mb, tree, rows(), verifiers=cols)
    full.main(["--all-columns"])

    def kind(verdict):
        return "killed" if verdict.startswith("killed") else verdict
    assert [kind(r.verdict) for r in fast.rows] == [kind(r.verdict) for r in full.rows] == [
        "killed", "SURVIVOR", "control ok", "FALSE-KILL"]


def test_a_setup_failure_does_not_stop_the_row(mb, tree, calls):
    """Only a RED stops a row. A column that measured nothing is not a kill, so the columns
    after it still run and the report shows what they found."""
    battery = _battery(mb, tree, [
        mb.Mutation("SF", "what it matches on", old=LATE_GREP, new=LATE_BROKEN),
    ], verifiers=[
        mb.Verifier("dies", argv=["bash", "-c",
                                  f"{LATE_INTACT} || kill -9 $$"]),
        _col(mb, "sees", calls, LATE_INTACT),
    ])
    battery.main([])
    assert battery.rows[0].results == {"dies": "SETUP-FAIL", "sees": "red"}
    assert battery.rows[0].verdict == "SETUP-FAIL"


def test_an_impossible_partial_verdict_is_incomplete_not_green(mb):
    """`_stops_early` exempts controls, and a defect row stops only on a red. If either
    ever fails, the verdict must not be a green one over columns that never ran."""
    control = mb.Mutation("C", "over-strictness", kind="control", old="a", new="b")
    defect = mb.Mutation("D", "vacuity", old="a", new="b")
    assert mb.Battery._verdict(control, {"a": "green", "b": "NOT RUN"}) == "INCOMPLETE"
    assert mb.Battery._verdict(defect, {"a": "green", "b": "NOT RUN"}) == "INCOMPLETE"
    assert mb.Battery._verdict(defect, {"a": "green", "b": "green"}) == "SURVIVOR"


def test_an_incomplete_row_fails_the_battery(mb, tree, calls, capsys, monkeypatch):
    battery = _battery(mb, tree, [
        mb.Mutation("N2", "over-strictness", kind="control", old=LATE_GREP, new=LATE_BROKEN),
    ], verifiers=[_col(mb, "a", calls, LATE_INTACT), _col(mb, "b", calls, LATE_INTACT)])
    monkeypatch.setattr(battery, "_stops_early", lambda _m: True)
    rc = battery.main([])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "INCOMPLETE" in out


def test_a_killer_or_verifier_name_the_row_cannot_run_is_refused_at_construction(mb, tree):
    cols = [mb.Verifier("a", argv=["true"]), mb.Verifier("b", argv=["true"])]
    with pytest.raises(ValueError, match="killer 'zz'"):
        _battery(mb, tree, [mb.Mutation("X", "vacuity", old="a", new="b", killer="zz")],
                 verifiers=cols)
    with pytest.raises(ValueError, match="killer 'b'"):
        _battery(mb, tree, [mb.Mutation("X", "vacuity", old="a", new="b", killer="b",
                                        verifiers=["a"])], verifiers=cols)
    with pytest.raises(ValueError, match="unknown verifier"):
        _battery(mb, tree, [mb.Mutation("X", "vacuity", old="a", new="b",
                                        verifiers=["zz"])], verifiers=cols)
    with pytest.raises(ValueError, match="duplicate verifier name"):
        _battery(mb, tree, [], verifiers=[mb.Verifier("a", argv=["true"]),
                                          mb.Verifier("a", argv=["true"])])


# --------------------------------------------------------------------------------------
# Per-column pytest flags. `addopts` carries `-n auto`, so every call used to spawn a full
# xdist pool — 2.9 s for a module whose tests take 0.05 s.
# --------------------------------------------------------------------------------------


def test_pytest_args_reach_the_call_and_the_battery_default_applies(mb, tree, capsys):
    """`-k` is the observable flag: deselecting the only test that sees the mutation turns
    a kill into a survivor, which is what reaching pytest looks like from outside."""
    row = [mb.Mutation("P1", "what it matches on", old=LATE_GREP, new=LATE_BROKEN)]
    per_column = _battery(mb, tree, row, verifiers=[
        mb.Verifier("g", modules=["test_guard.py"], pytest_args=("-k", "announces"))])
    per_column.main([])
    assert per_column.rows[0].verdict == "SURVIVOR"
    default = _battery(mb, tree, list(row), verifiers=[mb.Verifier("g", modules=["test_guard.py"])],
                       pytest_args=("-k", "announces"))
    default.main([])
    assert default.rows[0].verdict == "SURVIVOR"
    override = _battery(mb, tree, list(row), pytest_args=("-k", "announces"), verifiers=[
        mb.Verifier("g", modules=["test_guard.py"], pytest_args=())])
    override.main([])
    assert override.rows[0].verdict == "killed"
    capsys.readouterr()


def test_pytest_args_are_refused_on_an_argv_verifier(mb):
    with pytest.raises(ValueError, match="modules only"):
        mb.Verifier("x", argv=["true"], pytest_args=("-n", "0"))


# --------------------------------------------------------------------------------------
# Multi-edit rows (`also=`). Phase 345's battery defined one and, until its round noticed,
# never ran it; 336 and 345 hand-rolled the shape because this module had none.
# --------------------------------------------------------------------------------------


@pytest.fixture()
def second(tree):
    path = tree / "second.sh"
    path.write_text("echo second\n", encoding="utf-8")
    return path


# Red only while BOTH edits are in the tree: the kill is the proof they were applied together.
BOTH = "! { grep -q MUT_ONE subject.sh && grep -q MUT_TWO second.sh; }"


def test_a_multi_edit_row_applies_every_edit_and_restores_every_file(mb, tree, second, calls):
    before = {p.name: p.read_bytes() for p in (tree / "subject.sh", second)}
    battery = _battery(mb, tree, [
        mb.Mutation("ME1", "where it looks", old='echo "GATE GREEN"',
                    new='echo "GATE GREEN MUT_ONE"',
                    also=[mb.Edit("echo second", "echo MUT_TWO", target=second)]),
    ], verifiers=[_col(mb, "both", calls, BOTH)])
    rc = battery.main([])
    assert battery.rows[0].verdict == "killed", battery.rows[0]
    assert rc == 0
    assert {p.name: p.read_bytes() for p in (tree / "subject.sh", second)} == before


def test_a_multi_edit_row_restores_every_file_before_the_next_row(mb, tree, second, calls):
    """The end-of-run restore puts everything back, so a row that leaves an `also` file
    mutated is invisible to a check made after the run. The NEXT row sees it: here the
    second row is a survivor only if `second.sh` is intact when it runs."""
    battery = _battery(mb, tree, [
        mb.Mutation("MR1", "where it looks", old='echo "GATE GREEN"', new='echo "MUT_ONE"',
                    also=[mb.Edit("echo second", "echo MUT_TWO", target=second)]),
        mb.Mutation("MR2", "where it looks", old="set -euo pipefail", new="set -uo pipefail"),
    ], verifiers=[_col(mb, "intact", calls, "! grep -q MUT_TWO second.sh")])
    battery.main([])
    assert battery.rows[0].verdict == "killed"
    assert battery.rows[1].verdict == "SURVIVOR", (
        "the first row's second file was still mutated when the next row ran")


def test_two_edits_to_one_file_compose(mb, tree, calls):
    """The second edit anchors on text only the first edit produced."""
    battery = _battery(mb, tree, [
        mb.Mutation("ME2", "where it looks", old='echo "GATE GREEN"', new='echo "STEP_ONE"',
                    also=[mb.Edit('echo "STEP_ONE"', 'echo "STEP_TWO"')]),
    ], verifiers=[_col(mb, "g", calls, "! grep -q STEP_TWO subject.sh")])
    battery.main([])
    assert battery.rows[0].verdict == "killed", battery.rows[0].detail


def test_a_stale_later_edit_makes_the_row_stale_and_writes_nothing(mb, tree, second, calls,
                                                                   capsys):
    before = {p.name: p.read_bytes() for p in (tree / "subject.sh", second)}
    battery = _battery(mb, tree, [
        mb.Mutation("ME3", "where it looks", old='echo "GATE GREEN"', new='echo "X"',
                    also=[mb.Edit("not in the file", "y", target=second)]),
    ], verifiers=[_col(mb, "g", calls, "true")])
    rc = battery.main([])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert battery.rows[0].status == "ANCHOR-STALE"
    assert "edit 2 of 2 (second.sh)" in battery.rows[0].detail
    # Only the baseline and the restore check ran the column; the row never did.
    assert _logged(calls) == ["g", "g"]
    assert {p.name: p.read_bytes() for p in (tree / "subject.sh", second)} == before


def test_a_multi_edit_row_that_changes_nothing_is_a_noop(mb, tree, calls, capsys):
    battery = _battery(mb, tree, [
        mb.Mutation("ME4", "where it looks", old='echo "GATE GREEN"', new='echo "X"',
                    also=[mb.Edit('echo "X"', 'echo "GATE GREEN"')]),
    ], verifiers=[_col(mb, "g", calls, "true")])
    battery.main([])
    assert battery.rows[0].status == "NO-OP(text)"
    capsys.readouterr()


def test_every_also_target_is_snapshotted(mb, tree, second):
    battery = _battery(mb, tree, [
        mb.Mutation("ME5", "where it looks", old='echo "GATE GREEN"', new='echo "X"',
                    also=[mb.Edit("echo second", "echo third", target=second)]),
    ])
    battery._snapshot()
    assert set(battery._originals) == {tree / "subject.sh", second}


def test_an_also_entry_must_be_an_edit(mb):
    with pytest.raises(ValueError, match="must be an Edit"):
        mb.Mutation("ME6", "vacuity", old="a", new="b", also=[("x", "y")])


def test_a_multi_edit_control_is_blind_only_when_every_file_is(mb, pytree, calls, capsys):
    """BLIND-CONTROL over a row that edits a comment in one `.py` file and real code in
    another is not blind: the second edit is one the verifier can see."""
    other = pytree / "other.py"
    other.write_text("VALUE = 1  # note\n", encoding="utf-8")
    blind = _pybattery(mb, pytree, [
        mb.Mutation("MB1", "over-strictness", kind="control",
                    old="# a leading comment", new="# reworded",
                    also=[mb.Edit("# note", "# changed", target=other)]),
    ])
    assert blind.main([]) == 2
    assert blind.rows[0].status == "BLIND-CONTROL"
    seen = _pybattery(mb, pytree, [
        mb.Mutation("MB2", "over-strictness", kind="control",
                    old="# a leading comment", new="# reworded",
                    also=[mb.Edit("VALUE = 1", "VALUE = 2", target=other)]),
    ])
    seen.main([])
    assert seen.rows[0].status == "", seen.rows[0].detail
    capsys.readouterr()


# --------------------------------------------------------------------------------------
# A signal mid-row restores every file the row touched. Driven for real: the battery runs
# in a subprocess, its column blocks while the mutation is in the tree, and the test sends
# the signal. Phase 345's round killed a hand-roll with SIGTERM and left a mutation applied;
# Phase 347's round left one applied with SIGHUP, which the runner did not handle.
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGQUIT],
                         ids=["SIGTERM", "SIGINT", "SIGHUP", "SIGQUIT"])
def test_a_signal_mid_row_restores_every_file_of_a_multi_edit_row(mb, tree, second, signum):
    flag = tree.parent / f"{tree.name}-inside-the-row"
    before = {p.name: p.read_bytes() for p in (tree / "subject.sh", second)}
    runner = tree.parent / f"{tree.name}-runner.py"
    block = f"grep -q MUT_ONE subject.sh || exit 0; touch '{flag}'; exec sleep 60"
    runner.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPT.parent)!r})\n"
        "from mutation_battery import Battery, Edit, Mutation, Verifier\n"
        "from pathlib import Path\n"
        f"ROOT = Path({str(tree)!r})\n"
        "b = Battery(root=ROOT, default_target=ROOT / 'subject.sh',\n"
        f"            verifiers=[Verifier('block', argv=['bash', '-c', {block!r}])],\n"
        "            mutations=[Mutation('S1', 'what it accepts', old='echo \"GATE GREEN\"',\n"
        "                                new='echo MUT_ONE',\n"
        f"                                also=[Edit('echo second', 'echo MUT_TWO', target=ROOT / 'second.sh')])])\n"
        "sys.exit(b.main([]))\n",
        encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(runner)], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(600):
            if flag.exists() or proc.poll() is not None:
                break
            time.sleep(0.05)
        assert flag.exists(), f"the row never reached its column: {proc.communicate()}"
        assert b"MUT_TWO" in second.read_bytes(), "the second edit was not in the tree"
        proc.send_signal(signum)
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert proc.returncode == 128 + signum, proc.returncode
    assert {p.name: p.read_bytes() for p in (tree / "subject.sh", second)} == before


# --------------------------------------------------------------------------------------
# Row selection, the anchors-only check, progress, and the JSON record
# --------------------------------------------------------------------------------------


def test_row_ids_select_rows_and_an_unknown_id_is_refused(mb, tree, capsys):
    battery = _battery(mb, tree, [
        mb.Mutation("I1", "what it matches on", old=LATE_GREP, new=LATE_BROKEN),
        mb.Mutation("I2", "where it looks", old="set -euo pipefail", new="set -uo pipefail"),
    ])
    assert battery.main(["I2", "--list"]) == 0
    out = capsys.readouterr().out
    assert "I2" in out and "I1" not in out
    assert battery.main(["I3"]) == 2
    assert "unknown row id(s): I3" in capsys.readouterr().err


def test_check_resolves_anchors_runs_no_verifier_and_writes_nothing(mb, tree, calls, capsys):
    before = (tree / "subject.sh").read_bytes()
    good = _battery(mb, tree, [
        mb.Mutation("G1", "what it matches on", old=LATE_GREP, new=LATE_BROKEN),
    ], verifiers=[_col(mb, "g", calls, "true")])
    assert good.main(["--check"]) == 0
    bad = _battery(mb, tree, [
        mb.Mutation("G2", "what it matches on", old="not there", new="x"),
        mb.Mutation("G3", "what it matches on", old="grep -rniE", new="grep -rnE"),
    ], verifiers=[_col(mb, "g", calls, "true")])
    assert bad.main(["--check"]) == 2
    out = capsys.readouterr().out
    assert "ANCHORED" in out and "ANCHOR-STALE" in out and "ANCHOR-AMBIGUOUS" in out
    assert _logged(calls) == []
    assert (tree / "subject.sh").read_bytes() == before


def test_each_row_prints_a_progress_line_and_the_json_records_not_run_and_seconds(
        mb, tree, calls, capsys, tmp_path_factory):
    out_json = tmp_path_factory.mktemp("json") / "r.json"
    _battery(mb, tree, [
        mb.Mutation("J1", "what it matches on", old=LATE_GREP, new=LATE_BROKEN, killer="a"),
    ], verifiers=[_col(mb, "a", calls, LATE_INTACT), _col(mb, "b", calls, LATE_INTACT)]).main(
        ["--json", str(out_json)])
    assert "[1/1] J1  killed by a (1 not run)" in capsys.readouterr().out
    row = json.loads(out_json.read_text(encoding="utf-8"))[0]
    assert row["results"] == {"a": "red", "b": "NOT RUN"}
    assert isinstance(row["seconds"], float)


def test_two_spellings_of_one_file_are_one_snapshot(mb, tree, calls):
    """Phase 347's round (lens 1): a row whose own edit and an `also` edit reached one file
    through different spellings (`sub/../subject.sh`) kept only the later write, so the row
    ran half-applied while `--check` said ANCHORED. Both edits must land."""
    (tree / "sub").mkdir()
    both = f"grep -qF 'echo MUT_TWO' subject.sh && ! grep -qF \"{LATE_GREP}\" subject.sh"
    battery = _battery(mb, tree, [
        mb.Mutation("P1", "what it matches on", old=LATE_GREP, new=LATE_BROKEN,
                    also=[mb.Edit('echo "GATE GREEN"', "echo MUT_TWO", target="sub/../subject.sh")]),
    ], verifiers=[_col(mb, "both", calls, f"! ( {both} )")])
    battery.main([])
    assert battery.rows[0].results == {"both": "red"}, battery.rows[0].results


# --------------------------------------------------------------------------------------
# Ignored runtime state (Phase 370, `Q-657`). `git status --porcelain` cannot see an
# ignored path, so Phase 368's round left `sysop/runtime/tracker.write.lock` behind and the
# runner reported clean. Every fixture here is a real repo whose `.gitignore` ignores the
# runtime dir — the configuration the porcelain diff is blind in.
# --------------------------------------------------------------------------------------


def _repo(tree):
    """`tree` as a committed git toplevel, `sysop/runtime/` ignored and already present."""
    (tree / ".gitignore").write_text("sysop/runtime/\nbuild/\n", encoding="utf-8")
    (tree / "sysop" / "runtime").mkdir(parents=True)
    _git(tree, "init", "-q", "-b", "main")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-q", "-m", "fixture")
    return tree


def _guard_that_leaves(tree, write_when_mutated):
    """Replace the guard with one that runs `write_when_mutated` (Python, `R` = root) only
    while the late grep has lost its `i` — i.e. only under the mutation."""
    body = "\n".join("        " + line for line in write_when_mutated.splitlines())
    (tree / "test_guard.py").write_text(
        "from pathlib import Path\n"
        "R = Path(__file__).resolve().parent\n\n\n"
        "def test_guard():\n"
        "    text = (R / 'subject.sh').read_text()\n"
        f"    if {LATE_BROKEN!r} in text:\n"
        f"{body}\n"
        f"    assert {LATE_GREP!r} in text\n",
        encoding="utf-8")
    _git(tree, "add", "-A")
    _git(tree, "commit", "-q", "-m", "guard")


LEAK_LOCK = "(R / 'sysop/runtime/tracker.write.lock').write_text('pid 1 batch_work.sh\\n')"


def test_an_ignored_runtime_file_a_row_leaves_is_collateral_and_stops_the_run(mb, tree, capsys):
    _repo(tree)
    _guard_that_leaves(tree, LEAK_LOCK)
    battery = _battery(mb, tree, [
        mb.Mutation("IG1", "what it matches on", old=LATE_GREP, new=LATE_BROKEN),
        mb.Mutation("IG2", "what it matches on", old=EARLY_GREP,
                    new=EARLY_GREP.replace("-rniE", "-rnE")),
    ])
    rc = battery.main([])
    out, err = capsys.readouterr()
    lock = tree / "sysop/runtime/tracker.write.lock"
    assert "COLLATERAL DAMAGE (ignored path)" in err, err
    assert "sysop/runtime/tracker.write.lock" in err
    assert rc == 2, out
    # Stopped, not continued: the row after it never ran, and the summary says so.
    assert [r.mutation.id for r in battery.rows] == ["IG1"]
    assert "1 selected row(s) after it were not run" in out
    # The leaking row keeps its own verdict and names what it left.
    assert battery.rows[0].verdict == "killed"
    assert "tracker.write.lock" in battery.rows[0].detail
    # Refused, not removed: the lock is still there, and the remedy is printed, not run.
    assert lock.is_file()
    assert f"rm -f {lock}" in err


def test_a_rewritten_pre_existing_runtime_file_is_collateral(mb, tree, capsys):
    """A row that rewrites a runtime file already present is as much a stray as one that
    creates it — the digest, not the name list, is the snapshot. Two levels down, where the
    real claim locks live (`sysop/runtime/locks/`), so the walk must recurse."""
    _repo(tree)
    (tree / "sysop/runtime/locks").mkdir()
    (tree / "sysop/runtime/locks/FEAT-1.lock").write_text("before\n", encoding="utf-8")
    _guard_that_leaves(tree, "(R / 'sysop/runtime/locks/FEAT-1.lock').write_text('after\\n')")
    rc = _battery(mb, tree, [
        mb.Mutation("IG3", "what it matches on", old=LATE_GREP, new=LATE_BROKEN),
    ]).main([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "changed     sysop/runtime/locks/FEAT-1.lock" in err, err
    # Not offered for deletion: it predates the run (Phase 370's round, lens 1).
    assert "rm -f" not in err, err
    assert "restore by hand" in err and "FEAT-1.lock" in err.split("restore by hand", 1)[1], err


def test_a_runtime_file_a_row_deletes_is_collateral(mb, tree, capsys):
    _repo(tree)
    (tree / "sysop/runtime/park.md").write_text("parked\n", encoding="utf-8")
    _guard_that_leaves(tree, "(R / 'sysop/runtime/park.md').unlink()")
    rc = _battery(mb, tree, [
        mb.Mutation("IG4", "what it matches on", old=LATE_GREP, new=LATE_BROKEN),
    ]).main([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "disappeared sysop/runtime/park.md" in err, err


def test_an_empty_directory_a_row_leaves_is_collateral(mb, tree, capsys):
    """A mkdir-style lock is a directory with nothing in it, which a file listing (and
    `git ls-files`) cannot show. The walk records directories for that reason."""
    _repo(tree)
    _guard_that_leaves(tree, "(R / 'sysop/runtime/claim/FEAT-1.lock').mkdir(parents=True)")
    rc = _battery(mb, tree, [
        mb.Mutation("IG8", "what it matches on", old=LATE_GREP, new=LATE_BROKEN),
    ]).main([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "appeared    sysop/runtime/claim/FEAT-1.lock" in err, err


def test_the_stated_noise_and_ignored_paths_outside_the_roots_do_not_trip_it(mb, tree, capsys):
    """The control, and the reason a bare `--ignored` diff was ruled out: bytecode and
    pytest caches under a watched root, and ignored debris outside every watched root,
    must not read as collateral."""
    _repo(tree)
    _guard_that_leaves(tree, "\n".join([
        "(R / 'sysop/runtime/__pycache__').mkdir(exist_ok=True)",
        "(R / 'sysop/runtime/__pycache__/m.cpython-312.pyc').write_bytes(b'x')",
        "(R / 'sysop/runtime/stray.pyc').write_bytes(b'x')",
        "(R / 'sysop/runtime/.pytest_cache').mkdir(exist_ok=True)",
        "(R / 'sysop/runtime/.DS_Store').write_bytes(b'finder')",
        "(R / 'build').mkdir(exist_ok=True)",
        "(R / 'build/out.bin').write_bytes(b'x')",
    ]))
    rc = _battery(mb, tree, [
        mb.Mutation("IG5", "what it matches on", old=LATE_GREP, new=LATE_BROKEN),
    ]).main([])
    out, err = capsys.readouterr()
    assert "COLLATERAL" not in err, err
    assert rc == 0, out + err


def test_runtime_state_left_by_the_baseline_aborts_before_any_row(mb, tree, capsys):
    """A verifier that writes runtime state on the UNMUTATED tree would have every row
    blamed for it; the baseline is checked on its own and refuses first."""
    _repo(tree)
    (tree / "test_guard.py").write_text(
        (tree / "test_guard.py").read_text(encoding="utf-8")
        + "\n\ndef test_writes_runtime():\n"
          "    (ROOT / 'sysop/runtime/always.lock').write_text('x')\n",
        encoding="utf-8")
    battery = _battery(mb, tree, [
        mb.Mutation("IG6", "what it matches on", old=LATE_GREP, new=LATE_BROKEN),
    ])
    rc = battery.run(battery.mutations)
    err = capsys.readouterr().err
    assert rc == 2
    assert "the baseline run, with no mutation applied," in err, err
    assert battery.rows == []


def test_the_ignored_root_check_works_off_git_too(mb, tree, capsys):
    """Walked on the filesystem, not asked of git, so a non-repo root is covered."""
    _guard_that_leaves_nogit = (
        "from pathlib import Path\nR = Path(__file__).resolve().parent\n\n\n"
        "def test_guard():\n"
        "    text = (R / 'subject.sh').read_text()\n"
        f"    if {LATE_BROKEN!r} in text:\n"
        "        (R / 'sysop/runtime').mkdir(parents=True, exist_ok=True)\n"
        f"        {LEAK_LOCK}\n"
        f"    assert {LATE_GREP!r} in text\n")
    (tree / "test_guard.py").write_text(_guard_that_leaves_nogit, encoding="utf-8")
    rc = _battery(mb, tree, [
        mb.Mutation("IG7", "what it matches on", old=LATE_GREP, new=LATE_BROKEN),
    ]).main([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "appeared    sysop/runtime/tracker.write.lock" in err, err


# --------------------------------------------------------------------------------------
# SIGKILL recovery (Phase 370, `Q-204`). SIGKILL runs no handler, `finally` or `atexit`, so
# the row's mutation stays in the tree — and the next run SNAPSHOTTED it as the original:
# measured at 12e8285, a successor whose rows did not anchor on the mutated line exited 0
# and wrote the mutant back as its "restore". Driven with a real SIGKILL of a child run.
# --------------------------------------------------------------------------------------

MUTANT_LINE = "echo MUT_KILLED"


def _kill_mid_row(tree):
    """Run a one-row battery in a child, SIGKILL it while its mutation is applied, and
    kill the column's orphaned `sleep` by pid. Returns the subject's pre-run bytes."""
    subject = tree / "subject.sh"
    before = subject.read_bytes()
    flag = tree.parent / f"{tree.name}-inside"
    pidfile = tree.parent / f"{tree.name}-sleep.pid"
    runner = tree.parent / f"{tree.name}-killed-runner.py"
    block = (f"grep -q '{MUTANT_LINE}' subject.sh || exit 0; echo $$ > '{pidfile}'; "
             f"touch '{flag}'; exec sleep 60")
    runner.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPT.parent)!r})\n"
        "from mutation_battery import Battery, Mutation, Verifier\n"
        "from pathlib import Path\n"
        f"ROOT = Path({str(tree)!r})\n"
        "b = Battery(root=ROOT, default_target=ROOT / 'subject.sh',\n"
        f"            verifiers=[Verifier('block', argv=['bash', '-c', {block!r}])],\n"
        "            mutations=[Mutation('KILLED', 'what it accepts',\n"
        f"                                old='echo \"GATE GREEN\"', new={MUTANT_LINE!r})])\n"
        "sys.exit(b.main([]))\n",
        encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(runner)], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(600):
            if flag.exists() or proc.poll() is not None:
                break
            time.sleep(0.05)
        assert flag.exists(), f"the row never reached its column: {proc.communicate()}"
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if pidfile.exists():
            try:
                os.kill(int(pidfile.read_text().strip()), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass
    assert proc.returncode == -signal.SIGKILL
    # The premise: nothing in the child could restore, so the mutant is in the tree.
    assert MUTANT_LINE.encode() in subject.read_bytes()
    return before


def _record(mb, tree):
    battery = _battery(mb, tree, [])
    state = battery._state_dir()
    assert state is not None
    return state / "record.json"


# Blind to the killed row's line: green on the pristine subject AND on the mutant, so
# only recovery — not the already-red abort — can put the original back.
def _blind_successor(mb, tree, calls):
    return _battery(mb, tree, [
        mb.Mutation("NEXT", "what it matches on", old=LATE_GREP, new=LATE_BROKEN),
    ], verifiers=[_col(mb, "late", calls, LATE_INTACT)])


def test_a_sigkilled_run_is_recovered_before_the_next_run_snapshots(mb, tree, calls, capsys):
    _repo(tree)
    before = _kill_mid_row(tree)
    assert _record(mb, tree).is_file(), "the row wrote no record before its mutation"
    battery = _blind_successor(mb, tree, calls)
    rc = battery.main([])
    out, err = capsys.readouterr()
    assert "RECOVERED:" in err and "row KILLED" in err, err
    assert (tree / "subject.sh").read_bytes() == before, "the mutant was adopted"
    assert rc == 0, out + err
    assert battery.rows[0].verdict == "killed"
    assert not _record(mb, tree).exists()


def test_a_file_changed_since_the_kill_is_refused_and_nothing_is_written(mb, tree, calls, capsys):
    _repo(tree)
    _kill_mid_row(tree)
    edited = b"the author's work since the kill\n"
    (tree / "subject.sh").write_bytes(edited)
    battery = _blind_successor(mb, tree, calls)
    rc = battery.main([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "RECOVERY REFUSED" in err and "neither" in err, err
    assert (tree / "subject.sh").read_bytes() == edited
    record = _record(mb, tree)
    assert record.is_file(), "the refusal discarded the only account of the mutant"
    assert f"rm -f {record}" in err
    saved = re.search(r"take the original:\s+cp (\S+) ", err)
    assert saved and Path(saved.group(1)).read_bytes().count(b'echo "GATE GREEN"') == 1
    assert _logged(calls) == [], "a refused run still ran a verifier"


def test_a_record_whose_file_is_already_original_is_cleared_without_a_write(mb, tree, calls,
                                                                           capsys):
    """Killed before the write, or after the restore but before the record went: the file
    is the original and there is nothing to restore."""
    _repo(tree)
    before = _kill_mid_row(tree)
    (tree / "subject.sh").write_bytes(before)
    rc = _blind_successor(mb, tree, calls).main([])
    out, err = capsys.readouterr()
    assert rc == 0, out + err
    assert "RECOVERED" not in err and "REFUSED" not in err
    assert not _record(mb, tree).exists()


def test_check_refuses_while_a_killed_runs_record_exists_and_writes_nothing(mb, tree, calls,
                                                                          capsys):
    _repo(tree)
    _kill_mid_row(tree)
    mutant = (tree / "subject.sh").read_bytes()
    rc = _blind_successor(mb, tree, calls).main(["--check"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "killed during row KILLED" in err, err
    assert (tree / "subject.sh").read_bytes() == mutant
    assert _record(mb, tree).is_file()


def test_the_already_red_abort_still_catches_a_mutant_no_record_describes(mb, tree, capsys):
    """The guard that surfaced the original incident must survive the record: with the
    record gone, a verifier that sees the mutant still refuses to score on it."""
    _repo(tree)
    _kill_mid_row(tree)
    _record(mb, tree).unlink()
    rc = _battery(mb, tree, [
        mb.Mutation("AB", "what it matches on", old=LATE_GREP, new=LATE_BROKEN),
    ]).main([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "is already red" in err, err
    assert MUTANT_LINE.encode() in (tree / "subject.sh").read_bytes()


def test_a_live_battery_on_the_same_tree_is_refused_not_recovered(mb, tree, calls, capsys):
    """A record held by a RUNNING battery is not a dead one's: restoring under it would
    unmutate a row mid-score. The lock tells them apart, without `kill -0`'s pid reuse."""
    _repo(tree)
    battery = _blind_successor(mb, tree, calls)
    assert battery._claim_state() == ""
    try:
        rival = _blind_successor(mb, tree, calls)
        rc = rival.main([])
        err = capsys.readouterr().err
        assert rc == 2
        assert "another mutation battery is running on this tree" in err, err
        assert f"pid {os.getpid()}" in err
        assert _logged(calls) == []
    finally:
        battery._release_state()
    assert _blind_successor(mb, tree, calls).main([]) == 0


def test_a_clean_run_leaves_no_record_and_no_saved_originals(mb, tree, calls):
    _repo(tree)
    battery = _blind_successor(mb, tree, calls)
    state = battery._state_dir()
    assert battery.main([]) == 0
    assert not (state / "record.json").exists()
    assert not list(state.glob("original-*"))
    assert battery._lock_fd is None


def test_a_root_that_is_not_its_repos_toplevel_keeps_no_record(mb, tree):
    """A fixture nested in some checkout must not write into that checkout's git dir."""
    _repo(tree)
    nested = tree / "nested"
    nested.mkdir()
    assert mb.Battery(root=nested, verifiers=[mb.Verifier("v", argv=["true"])],
                      mutations=[])._state_dir() is None


def test_the_record_is_written_before_the_mutation_reaches_the_tree(mb, tree, calls):
    """The ordering a SIGKILL test cannot time: at the moment the record is written, the
    target must still be the original — a record written after the mutation leaves a window
    in which a kill leaves a mutant and no record of it."""
    _repo(tree)
    original = (tree / "subject.sh").read_text(encoding="utf-8")
    battery = _blind_successor(mb, tree, calls)
    seen = []
    real_arm = battery._arm

    def arm(row_id, changed):
        seen.append((tree / "subject.sh").read_text(encoding="utf-8"))
        real_arm(row_id, changed)
        seen.append(json.loads(battery._record_path().read_text(encoding="utf-8")))

    battery._arm = arm
    assert battery.main([]) == 0
    assert seen[0] == original, "the mutation reached the tree before its record"
    assert seen[1]["row"] == "NEXT"
    assert [Path(f["path"]).name for f in seen[1]["files"]] == ["subject.sh"]


def test_a_damaged_saved_original_is_refused_not_restored(mb, tree, calls, capsys):
    """The saved bytes are checked against the digest recorded with them before they are
    written back: restoring a truncated original would trade one wrong file for another."""
    _repo(tree)
    _kill_mid_row(tree)
    mutant = (tree / "subject.sh").read_bytes()
    record = _record(mb, tree)
    saved = record.parent / json.loads(record.read_text(encoding="utf-8"))["files"][0]["original"]
    saved.write_bytes(saved.read_bytes()[:10])
    rc = _blind_successor(mb, tree, calls).main([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "missing or damaged" in err, err
    assert (tree / "subject.sh").read_bytes() == mutant
    assert record.is_file()


def test_an_unreadable_record_is_refused_not_read_as_no_record(mb, tree, calls, capsys):
    """A record that cannot be parsed still says a battery died mid-row; proceeding as if
    there were none would snapshot whatever that battery left."""
    _repo(tree)
    _kill_mid_row(tree)
    mutant = (tree / "subject.sh").read_bytes()
    record = _record(mb, tree)
    record.write_text('{"files": [{"path": 1}]}', encoding="utf-8")
    rc = _blind_successor(mb, tree, calls).main([])
    err = capsys.readouterr().err
    assert rc == 2
    assert "is unreadable" in err, err
    assert (tree / "subject.sh").read_bytes() == mutant
    assert _logged(calls) == []


def test_a_caught_signal_on_a_git_root_leaves_no_record_and_no_saved_originals(mb, tree):
    """The handled-signal path with a real state dir (the parametrized signal test above
    runs on a non-git tree, where no record exists): SIGTERM restores, and the exit path
    must clear the record and the saved originals rather than strand them."""
    _repo(tree)
    subject = tree / "subject.sh"
    before = subject.read_bytes()
    flag = tree.parent / f"{tree.name}-inside-term"
    runner = tree.parent / f"{tree.name}-term-runner.py"
    block = f"grep -q '{MUTANT_LINE}' subject.sh || exit 0; touch '{flag}'; exec sleep 60"
    runner.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPT.parent)!r})\n"
        "from mutation_battery import Battery, Mutation, Verifier\n"
        "from pathlib import Path\n"
        f"ROOT = Path({str(tree)!r})\n"
        "b = Battery(root=ROOT, default_target=ROOT / 'subject.sh',\n"
        f"            verifiers=[Verifier('block', argv=['bash', '-c', {block!r}])],\n"
        "            mutations=[Mutation('TERM', 'what it accepts',\n"
        f"                                old='echo \"GATE GREEN\"', new={MUTANT_LINE!r})])\n"
        "sys.exit(b.main([]))\n",
        encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(runner)], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(600):
            if flag.exists() or proc.poll() is not None:
                break
            time.sleep(0.05)
        assert flag.exists(), f"the row never reached its column: {proc.communicate()}"
        assert _record(mb, tree).is_file()
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert proc.returncode == 128 + signal.SIGTERM, proc.returncode
    assert subject.read_bytes() == before
    record = _record(mb, tree)
    assert not record.exists()
    assert not list(record.parent.glob("original-*"))


def test_a_failed_restore_keeps_the_record(mb, tree, capsys):
    """A restore that fails leaves the mutant in the tree, and the record is then the only
    account of it: discarding it anyway lets the next run snapshot the mutant as the
    original — `Q-204` reopened on the restore-failure path (Phase 370's round, lens 2:
    an unconditional discard survived every test)."""
    _repo(tree)
    subject = tree / "subject.sh"
    # The column makes the subject unwritable while the row's mutant is applied, so both
    # the row's own restore and the end-of-run restore fail for real.
    battery = _battery(mb, tree, [
        mb.Mutation("RF", "what it accepts", old=LATE_GREP, new=LATE_BROKEN),
    ], verifiers=[mb.Verifier("lock-it", argv=[
        # `-rnE` is the mutant's flag set (the original's is `-rniE`); LATE_BROKEN itself
        # carries single quotes, so it cannot go inside this one.
        "/bin/bash", "-c", f"if grep -qF -- 'grep -rnE' '{subject}'; then chmod 444 '{subject}'; fi"])])
    state = battery._state_dir()
    try:
        with pytest.raises(PermissionError):
            battery.main([])
        assert "RESTORE FAILED" in capsys.readouterr().err
        assert (state / "record.json").is_file(), "the record was discarded with the mutant applied"
        assert LATE_BROKEN.encode() in subject.read_bytes(), "the premise: the mutant is still applied"
    finally:
        subject.chmod(0o644)


def test_watch_ignored_overrides_the_watched_roots(mb, tree, capsys):
    """The override is honoured both ways: a named root is watched, and the default one is
    then not (Phase 370's round, lens 2: ignoring the parameter survived every test)."""
    _repo(tree)
    (tree / ".gitignore").write_text("sysop/runtime/\nbuild/\nstate/\n", encoding="utf-8")
    (tree / "state").mkdir()
    _git(tree, "add", "-A")
    _git(tree, "commit", "-q", "-m", "state ignored")
    _guard_that_leaves(tree, "(R / 'state/claim.lock').write_text('x\\n')\n" + LEAK_LOCK)
    battery = _battery(mb, tree, [
        mb.Mutation("WO", "what it matches on", old=LATE_GREP, new=LATE_BROKEN),
    ], watch_ignored=("state",))
    rc = battery.main([])
    err = capsys.readouterr().err
    assert rc == 2 and "state/claim.lock" in err, err
    assert "sysop/runtime/tracker.write.lock" not in err, err
