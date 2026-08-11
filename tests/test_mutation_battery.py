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
import subprocess
import sys
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
