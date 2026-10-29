"""Q-634 — a baseline entry of any arity that matched no finding is named.

`legacy_entries` reports only two-field entries, so a three-field entry whose
finding moved stopped suppressing silently: one consumer's anchor moved eight
lines and its finding re-surfaced as new on every run until a human read the
file. The spec: report an entry whose check ran with status `executed` and whose
key matched no finding — including an entry whose anchor file is gone — in
wording apart from the legacy warning, with a `--print-keys` hint, and change no
exit code.

The CLI tests drive `run_checks_impl.main()` against a real fixture tree, as
`test_run_checks_baseline_identity.py` does, because what matters is what the
run prints and how it exits.
"""
import sys

import run_checks.baseline as baseline
import run_checks_impl as rci
from run_checks.accounting import (
    DEGRADED,
    EXECUTED,
    FAILED,
    SKIPPED,
    UNROUTABLE,
    RunReport,
)

NEW = "matched no finding this run — re-anchor or remove"
LEGACY = "predate the identity field"
ABSENT = "anchor file not in this checkout:"

_PATTERN = ("'GRANT[[:space:]]+[A-Z, ]+[[:space:]]+ON[[:space:]]+[a-z_]+"
            "[[:space:]]+TO'")


def _yml(blocking="true", used_by="[codebase-review, security-audit]"):
    return f"""\
checks:
  - id: grant-sensitive-table
    severity: critical
    blocking: {blocking}
    paths: ["migrations/"]
    include: ["*.sql"]
    pattern: {_PATTERN}
    description: "GRANT on sensitive PII table."
    used_by: {used_by}
"""


_GRANT = "GRANT UPDATE ON payments TO app_writer;\n"


def _tree(tmp_path, body, **yml):
    (tmp_path / ".claude").mkdir(exist_ok=True)
    (tmp_path / ".claude" / "checks.yml").write_text(_yml(**yml))
    (tmp_path / "migrations").mkdir(exist_ok=True)
    (tmp_path / "migrations" / "001.sql").write_text(body)
    return tmp_path


def _baseline(tmp_path, *entries, raw=None):
    p = tmp_path / ".claude" / "checks_baseline.txt"
    if raw is not None:
        p.write_bytes(raw)
    else:
        p.write_text("# accepted after review\n" + "".join(e + "\n" for e in entries))


def _run(tmp_path, monkeypatch, *extra, mode="both"):
    monkeypatch.setattr(sys, "argv", ["run_checks", "--repo-root", str(tmp_path),
                                      "--mode", mode, *extra])
    try:
        rci.main()
    except SystemExit as e:
        return e.code if e.code is not None else 0
    return 0


def _key(line_no, text=_GRANT):
    ident = baseline.identity_of(text)
    return f"grant-sensitive-table|migrations/001.sql:{line_no}|{ident}"


# ── the reproduction ────────────────────────────────────────────────────────


def test_a_drifted_three_field_entry_is_named(tmp_path, monkeypatch, capsys):
    """The filed case: the accepted statement moved eight lines down. The entry
    still carries its old line number, the finding re-fires as new, and the
    pre-fix run said nothing about the entry at all."""
    _tree(tmp_path, "-- h\n" + "\n" * 8 + _GRANT)
    _baseline(tmp_path, _key(2))
    _run(tmp_path, monkeypatch)
    out, err = capsys.readouterr()
    assert NEW in err, err
    assert _key(2) in err.split(NEW, 1)[1], err
    assert "--print-keys" in err.split(NEW, 1)[1]
    # Its own wording, not the legacy warning's.
    assert LEGACY not in err
    assert "--migrate-baseline" not in err
    # stderr only: stdout is the finding stream a consumer pipes into grep/wc.
    assert NEW not in out
    assert ABSENT not in err, "the anchor file exists"


def test_a_matching_entry_is_not_named(tmp_path, monkeypatch, capsys):
    """The control: an entry its finding still matches says nothing."""
    _tree(tmp_path, "-- h\n" + _GRANT)
    _baseline(tmp_path, _key(2))
    _run(tmp_path, monkeypatch)
    assert NEW not in capsys.readouterr().err


def test_an_entry_whose_anchor_file_is_gone_is_named_as_absent(
        tmp_path, monkeypatch, capsys):
    """The clearest dead case, which nothing reported. The check still executes
    (`migrations/` resolves and holds another file), so the entry is judged —
    and it is listed apart, because an absent file is either a rename or a
    checkout that does not hold it."""
    _tree(tmp_path, "-- nothing here\n")
    _baseline(tmp_path, "grant-sensitive-table|migrations/002_gone.sql:4|abc123def456")
    _run(tmp_path, monkeypatch)
    err = capsys.readouterr().err
    assert NEW in err, err
    tail = err.split(ABSENT, 1)
    assert len(tail) == 2, err
    assert "migrations/002_gone.sql:4" in tail[1].splitlines()[0], err


# ── no exit-code change ─────────────────────────────────────────────────────


def test_an_unmatched_entry_changes_no_exit_code(tmp_path, monkeypatch, capsys):
    """Warning only. The same tree, the same live finding accepted, with and
    without one extra dead entry for the same blocking check under
    `--fail-on-blocking`: both exit 0, and only the second warns."""
    _tree(tmp_path, "-- h\n" + _GRANT)
    _baseline(tmp_path, _key(2))
    assert _run(tmp_path, monkeypatch, "--fail-on-blocking") == 0
    assert NEW not in capsys.readouterr().err

    _baseline(tmp_path, _key(2), _key(40))
    assert _run(tmp_path, monkeypatch, "--fail-on-blocking") == 0
    assert NEW in capsys.readouterr().err


def test_a_drifted_entry_on_a_failing_gate_still_exits_one(
        tmp_path, monkeypatch, capsys):
    """And in the other direction: the re-fired finding is what fails the gate,
    exactly as before; the warning neither adds nor removes a failure."""
    _tree(tmp_path, "-- h\n" + "\n" * 8 + _GRANT)
    _baseline(tmp_path, _key(2))
    assert _run(tmp_path, monkeypatch, "--fail-on-blocking") == 1
    assert NEW in capsys.readouterr().err


def test_an_advisory_checks_drift_warns_and_exits_zero(tmp_path, monkeypatch, capsys):
    _tree(tmp_path, "-- h\n" + "\n" * 8 + _GRANT, blocking="false")
    _baseline(tmp_path, _key(2))
    assert _run(tmp_path, monkeypatch, "--fail-on-blocking") == 0
    assert NEW in capsys.readouterr().err


# ── the false-stale traps: a check that did not EXECUTE is never judged ─────


def test_a_check_outside_this_mode_is_not_judged(tmp_path, monkeypatch, capsys):
    """`--mode quality` does not select a security-only check, so it has no
    state this run and its entries cannot be judged."""
    _tree(tmp_path, "-- h\n" + "\n" * 8 + _GRANT, used_by="[security-audit]")
    _baseline(tmp_path, _key(2))
    _run(tmp_path, monkeypatch, mode="quality")
    assert NEW not in capsys.readouterr().err
    # Control: the same tree in the mode that selects it does warn.
    _run(tmp_path, monkeypatch, mode="security")
    assert NEW in capsys.readouterr().err


def test_a_skipped_check_is_not_judged(tmp_path, monkeypatch, capsys):
    """`paths:` unresolved → `skipped`: it scanned nothing, so every entry it
    owns would look dead. The anchor file is absent too, which must not by
    itself make the entry reportable."""
    _tree(tmp_path, "-- h\n" + _GRANT)
    (tmp_path / "migrations" / "001.sql").unlink()
    (tmp_path / "migrations").rmdir()
    _baseline(tmp_path, _key(2))
    _run(tmp_path, monkeypatch)
    err = capsys.readouterr().err
    assert "skipped" in err  # the premise: the check really was skipped
    assert NEW not in err


def _report(status):
    r = RunReport([{"id": "c"}])
    r.record(["c"], status, "grep")
    return r


def test_only_executed_is_executed():
    """Every non-`executed` state — including `degraded`, which ran and emitted
    real findings but over less than its inputs — is out of `executed_ids`."""
    assert _report(EXECUTED).executed_ids() == {"c"}
    for status in (DEGRADED, FAILED, SKIPPED, UNROUTABLE):
        assert _report(status).executed_ids() == set(), status
    # An upgrade along the ladder takes the check out.
    r = _report(EXECUTED)
    r.record(["c"], DEGRADED, "grep")
    assert r.executed_ids() == set()
    # Never recorded (an accounting hole) is not executed either.
    assert RunReport([{"id": "c"}]).executed_ids() == set()


# ── the predicate, unit level ───────────────────────────────────────────────


def _found(*findings):
    return [(c, fl, "msg", ident) for c, fl, ident in findings]


def test_unmatched_entries_reads_executed_ids_not_presence(tmp_path):
    (tmp_path / "a.py").write_text("x\n")
    entry = "chk|a.py:1|deadbeef0000"
    assert baseline.unmatched_entries({entry}, [], {"chk"}, str(tmp_path)) == [
        (entry, True)]
    assert baseline.unmatched_entries({entry}, [], set(), str(tmp_path)) == []
    assert baseline.unmatched_entries({entry}, [], {"other"}, str(tmp_path)) == []


def test_unmatched_entries_does_not_repeat_a_legacy_entry(tmp_path):
    """A two-field entry for a check that now emits identities is the legacy
    warning's, with the converter as its remedy. Named twice it would carry two
    contradictory remedies."""
    (tmp_path / "m.sql").write_text("x\n" * 5)
    found = _found(("grant-x", "m.sql:2", "abc123abc123"))
    legacy = "grant-x|m.sql:2"
    drifted = "grant-x|m.sql:4|abc123abc123"
    assert baseline.legacy_entries({legacy, drifted}, found) == [legacy]
    assert baseline.unmatched_entries(
        {legacy, drifted}, found, {"grant-x"}, str(tmp_path)) == [(drifted, True)]


def test_a_two_field_entry_the_legacy_report_cannot_see_is_named(tmp_path):
    """Two two-field shapes `legacy_entries` skips and this must not:
    an identity-free check (`invert_file_check`) whose file no longer
    violates, and an identity-bearing check that executed with zero findings
    (not in the run's identity-bearing set, so not "legacy")."""
    (tmp_path / "Up.tsx").write_text("ok\n")
    (tmp_path / "m.sql").write_text("ok\n")
    entries = {"leak|Up.tsx", "grant-x|m.sql:2"}
    assert baseline.legacy_entries(entries, []) == []
    assert baseline.unmatched_entries(
        entries, [], {"leak", "grant-x"}, str(tmp_path)) == [
            ("grant-x|m.sql:2", True), ("leak|Up.tsx", True)]


def test_an_identity_free_finding_still_matches_its_two_field_entry(tmp_path):
    (tmp_path / "Up.tsx").write_text("x\n")
    found = _found(("leak", "Up.tsx", ""))
    assert baseline.unmatched_entries(
        {"leak|Up.tsx"}, found, {"leak"}, str(tmp_path)) == []


def test_coverage_and_unparseable_entries_are_not_judged(tmp_path):
    """Coverage never suppresses and reports changed lines only, so every
    coverage entry would read as dead on every run; an entry with four fields
    is `--migrate-baseline`'s to name as unrepresentable."""
    (tmp_path / "a.py").write_text("x\n")
    entries = {"coverage-diff-python|a.py:1", "chk|a|b.py:1|x", "chk"}
    assert baseline.unmatched_entries(
        entries, [], {"coverage-diff-python", "chk"}, str(tmp_path)) == []


def test_anchor_presence_is_read_from_the_file_named(tmp_path):
    """Line-level, file-level, a colon in the path (line-level and file-level —
    only an all-digit tail is a line number), and an empty anchor."""
    (tmp_path / "a:b.py").write_text("x\n")
    (tmp_path / "f.tsx").write_text("x\n")
    (tmp_path / "x:y.tsx").write_text("x\n")
    entries = {"c|a:b.py:3|i", "c|f.tsx", "c|x:y.tsx", "c|gone.py:9|i",
               "c|gone.tsx", "c||i"}
    got = dict(baseline.unmatched_entries(entries, [], {"c"}, str(tmp_path)))
    assert got == {"c|a:b.py:3|i": True, "c|f.tsx": True, "c|x:y.tsx": True,
                   "c|gone.py:9|i": False, "c|gone.tsx": False, "c||i": False}


def test_an_empty_identity_entry_is_named(tmp_path):
    """`check|path:line|` — a trailing pipe and no identity — matches nothing."""
    (tmp_path / "a.py").write_text("x\n")
    found = _found(("c", "a.py:1", "abc"))
    assert baseline.unmatched_entries(
        {"c|a.py:1|"}, found, {"c"}, str(tmp_path)) == [("c|a.py:1|", True)]


def test_the_list_is_capped_and_counted(tmp_path, monkeypatch, capsys):
    """Five shown, the rest counted — the legacy warning's shape."""
    _tree(tmp_path, "-- h\n" + _GRANT)
    dead = [_key(n) for n in range(10, 17)]
    _baseline(tmp_path, *dead)
    _run(tmp_path, monkeypatch)
    err = capsys.readouterr().err
    assert "⚠ 7 baseline entries matched no finding this run" in err, err
    assert "(+2 more)" in err
    assert sum(k in err for k in dead) == 5


# ── neighbour: a byte-order mark ate the first entry ────────────────────────


def test_a_bom_does_not_disable_the_first_entry(tmp_path):
    p = tmp_path / "b.txt"
    p.write_bytes(b"\xef\xbb\xbfgrant-x|m.sql:2|abc\n")
    assert baseline.load_baseline(str(p)) == {"grant-x|m.sql:2|abc"}
    p.write_bytes(b"\xef\xbb\xbf# a comment, not an entry\ngrant-x|m.sql:2|abc\n")
    assert baseline.load_baseline(str(p)) == {"grant-x|m.sql:2|abc"}


def test_a_bom_baseline_suppresses_end_to_end(tmp_path, monkeypatch, capsys):
    _tree(tmp_path, "-- h\n" + _GRANT)
    _baseline(tmp_path, raw=b"\xef\xbb\xbf" + _key(2).encode() + b"\n")
    assert _run(tmp_path, monkeypatch, "--fail-on-blocking") == 0
    out, err = capsys.readouterr()
    assert "[baseline]" in out
    assert NEW not in err


# ── an entry naming a check this checks.yml does not define ────────────────

UNREG = "a check this checks.yml does not define"


def test_an_entry_for_a_removed_check_is_named(tmp_path, monkeypatch, capsys):
    """Executor A's out-of-scope finding, fixed in Phase 358: a renamed or removed
    check never executes, so `unmatched_entries` cannot see its entries, and they
    suppress nothing with nothing said. Warning only — the exit code is the
    gate's alone."""
    _tree(tmp_path, "-- h\n" + _GRANT)
    gone = "grant-old-name|migrations/001.sql:2|abc123def456"
    _baseline(tmp_path, _key(2), gone)
    code = _run(tmp_path, monkeypatch, "--fail-on-blocking")
    out, err = capsys.readouterr()
    assert code == 0, err
    assert UNREG in err, err
    assert gone in err.split(UNREG, 1)[1]
    assert _key(2) not in err, "the live entry is matched and not named"
    assert NEW not in err, "an undefined check is not reported as unmatched"
    assert UNREG not in out


def test_registry_membership_ignores_mode(tmp_path, monkeypatch, capsys):
    """A check outside this --mode is still defined: its entries are not named."""
    _tree(tmp_path, "-- h\n", used_by="[security-audit]")
    # A quality check too, so a --mode quality run reaches the baseline report
    # (a run that selects no check stops before it, and this test would pass
    # vacuously).
    yml = tmp_path / ".claude" / "checks.yml"
    yml.write_text(yml.read_text() + """\
  - id: todo-marker
    severity: low
    blocking: false
    paths: ["migrations/"]
    include: ["*.sql"]
    pattern: 'TODO'
    description: "todo"
    used_by: [codebase-review]
""")
    _baseline(tmp_path, _key(9), "gone|migrations/001.sql:1")
    code = _run(tmp_path, monkeypatch, mode="quality")
    err = capsys.readouterr().err
    assert code == 0, err
    assert UNREG in err, "the control: the report ran"
    assert _key(9) not in err.split(UNREG, 1)[1], err


def test_unregistered_entries_unit():
    entries = {
        "a|x.py:1|i", "b|x.py:2", "gone|x.py:3|i", "gone2|x.py:4",
        "coverage-foo|x.py:5", "malformed", "too|many|fields|here",
    }
    assert baseline.unregistered_entries(entries, ["a", "b"]) == ["gone2|x.py:4", "gone|x.py:3|i"]
    assert baseline.unregistered_entries(entries, ["a", "b", "gone", "gone2"]) == []


def test_an_entry_a_waiver_now_covers_is_named_as_waived(tmp_path, monkeypatch, capsys):
    """Round lens B: a waived finding never reaches the findings or `--print-keys`, so the
    re-anchor hint cannot apply to the entry it used to match; the entry is listed apart,
    with "remove" as its remedy. (Adding the marker changes the line, so the identity
    would not have matched anyway.)"""
    _tree(tmp_path, "-- h\n" + _GRANT.rstrip("\n") + "  -- no-check: grant-sensitive-table\n")
    _baseline(tmp_path, _key(2))
    _run(tmp_path, monkeypatch)
    out, err = capsys.readouterr()
    assert "[waived]" in out, out
    tail = err.split(NEW, 1)[1]
    assert "waived inline by a no-check marker" in tail, err
    assert _key(2) in tail.split("waived inline", 1)[1]
    first = tail.split("waived inline", 1)[0]
    assert _key(2) not in first, "listed once, under the waiver"
