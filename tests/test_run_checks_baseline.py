"""Tests for run_checks/baseline.py — the file I/O and the suppression contract.

Two layers, and the second one is new (Phase 193, upstream #363):

  1. **File I/O.** `write_baseline` emits a `#` comment header + a blank line;
     `load_baseline` must skip every one and return exactly the
     `check_id|path:line` key set (Phase 105).
  2. **Who may be baselined.** Both ends used to be gated on
     `check_id in blocking_ids`, so an entry for a `blocking: false` check
     could neither suppress anything nor be written — inert state that reads
     as live state. #363 drops that conjunct at both sites, leaving coverage
     as the only carve-out (Phase 61b). The tests below **call the code**
     rather than matching its source, and the CLI-level ones drive
     `run_checks_impl.main()` against a real fixture tree, because the claim
     that matters — *an advisory baseline entry cannot change an exit code* —
     is a property of the gate, not of this module.

Correcting this docstring's predecessor, which claimed *"there is no other
baseline test file; the `baseline` hits elsewhere are the English word"*: that
was false from Phase 61b onward. `tests/test_run_checks_coverage.py` owns the
Phase-61b carve-out unit tests and the coverage gate's CLI tests; this module
owns baseline I/O and the #363 contract. The carve-out appears in both, at
different levels, on purpose.
"""
import re
import sys
from pathlib import Path

import run_checks.baseline as baseline
import run_checks_impl as rci

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── fixture harness ─────────────────────────────────────────────────────────

# One blocking check and one advisory check, both matching the same fixture
# file. The pair is the point: every assertion below is about how the two
# behave *differently* (gate) and *identically* (baseline).
_TWO_CHECKS_YML = """\
checks:
  - id: gate-check
    severity: high
    paths: ["src/"]
    include: ["*.py"]
    pattern: 'FORBIDDEN'
    description: "blocking"
    used_by: [codebase-review]
    blocking: true
  - id: advisory-check
    severity: low
    paths: ["src/"]
    include: ["*.py"]
    pattern: 'ADVISORY'
    description: "advisory"
    used_by: [codebase-review]
    blocking: false
"""

_BASELINE_REL = ".claude/checks_baseline.txt"


def _tree(tmp_path, yml=_TWO_CHECKS_YML):
    """A repo root with a checks.yml and one source file tripping both checks."""
    claude = tmp_path / ".claude"
    claude.mkdir(exist_ok=True)
    (claude / "checks.yml").write_text(yml)
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "a.py").write_text("x = 'FORBIDDEN'\ny = 'ADVISORY'\n")
    return tmp_path


def _run(tmp_path, monkeypatch, argv_extra):
    argv = ["run_checks", "--repo-root", str(tmp_path), "--mode", "quality"]
    argv += argv_extra
    monkeypatch.setattr(sys, "argv", argv)
    try:
        rci.main()
    except SystemExit as e:
        return e.code if e.code is not None else 0
    return 0


def _baseline_keys(tmp_path):
    return baseline.load_baseline(str(tmp_path / _BASELINE_REL))


def _write_baseline_lines(tmp_path, lines):
    p = tmp_path / _BASELINE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# header\n\n" + "".join(f"{ln}\n" for ln in lines))


# The fixture's two source lines, and the identity each one hashes to. Derived
# from the same helper the runner uses rather than pasted as literals: a hash
# typed into a test is a second implementation of `identity_of`, and it would
# go stale silently the first time the normalization changed.
_FIXTURE_SRC = {"src/a.py:1": "x = 'FORBIDDEN'", "src/a.py:2": "y = 'ADVISORY'"}


def _key(check_id, file_line):
    """The real three-field baseline key for a fixture finding.

    Tests used to hand-write `check_id|path:line`. That is no longer a key any
    identity-bearing check produces — which is the whole point of Phase 213 —
    so a test that hand-writes one is asserting the defect. Consumers have the
    same problem and `--print-keys` is their answer; this is the test-side twin.
    """
    return baseline.finding_key(
        check_id, file_line, baseline.identity_of(_FIXTURE_SRC[file_line])
    )


# ── 1. file I/O ─────────────────────────────────────────────────────────────


def test_load_baseline_skips_comments_and_blank_lines(tmp_path):
    p = tmp_path / "baseline.txt"
    p.write_text("# header comment\n\ncheck-a|src/x.py:1\ncheck-b|src/y.py:9\n")
    keys = baseline.load_baseline(str(p))
    assert keys == {"check-a|src/x.py:1", "check-b|src/y.py:9"}
    # Load-bearing: no `#`-header line leaked into the key set.
    assert all(not k.startswith("#") for k in keys)


def test_write_then_load_roundtrip_ignores_header(tmp_path):
    # write_baseline emits a `#` header block + blank line; load_baseline must
    # drop all of it and return only the key. (dirname must be non-empty —
    # write_baseline os.makedirs it.)
    p = str(tmp_path / ".sysop" / "baseline.txt")
    baseline.write_baseline(p, [("chk", "src/a.py:3", "msg", "")], blocking_ids={"chk"})
    assert baseline.load_baseline(p) == {"chk|src/a.py:3"}


def test_every_header_line_is_a_comment_or_blank(tmp_path):
    """The header is the file's own documentation and a consumer reads it.

    `load_baseline` skips `#` and blank lines and nothing else, so a header line
    that is neither would be loaded as a key — a nonsense entry that matches no
    finding and is silently carried forever.
    """
    p = str(tmp_path / ".sysop" / "baseline.txt")
    baseline.write_baseline(p, [], blocking_ids=set())
    with open(p, encoding="utf-8") as f:
        header = f.read().splitlines()
    assert header, "header must not be empty"
    assert all(ln.startswith("#") or not ln.strip() for ln in header), header
    assert baseline.load_baseline(p) == set()


def test_load_baseline_missing_file_is_empty_set(tmp_path):
    assert baseline.load_baseline(str(tmp_path / "nope.txt")) == set()


def test_write_baseline_returns_what_it_persisted(tmp_path):
    """The return value is the caller's tally — `cli.py` prints it verbatim.

    It used to re-derive the count with a hand-inlined copy of the filter, which
    #363's edit would have left disagreeing with the file it describes.
    """
    p = str(tmp_path / ".claude" / "checks_baseline.txt")
    findings = [
        ("gate-check", "src/a.py:1", "m", ""),
        ("advisory-check", "src/a.py:2", "m", ""),
        ("coverage-diff-python", "src/a.py:3", "m", ""),
    ]
    written = baseline.write_baseline(p, findings, blocking_ids={"gate-check"})
    keys = baseline.load_baseline(p)
    assert written == 2, "coverage excluded, advisory included"
    assert written == len(keys)
    assert keys == {"gate-check|src/a.py:1", "advisory-check|src/a.py:2"}


def test_write_baseline_leaves_no_tmp_file_behind(tmp_path):
    """Atomic rewrite via `<path>.tmp` + os.replace — the tmp must not survive."""
    d = tmp_path / ".claude"
    p = str(d / "checks_baseline.txt")
    baseline.write_baseline(p, [("chk", "src/a.py:3", "m", "")], blocking_ids={"chk"})
    assert sorted(x.name for x in d.iterdir()) == ["checks_baseline.txt"]


# ── 2. the #363 contract, at the unit level ─────────────────────────────────


def test_an_advisory_finding_is_written_and_suppresses(tmp_path):
    """#363's whole content: an advisory check's entry is live state, not inert.

    Before the fix this key was neither written by `write_baseline` nor honoured
    by `is_baseline_suppressed`, so a triager who recorded the verdict recorded
    it nowhere and the next `--update-baseline` dropped it.
    """
    p = str(tmp_path / ".claude" / "checks_baseline.txt")
    baseline.write_baseline(
        p, [("advisory-check", "src/a.py:2", "m", "")], blocking_ids=set()
    )
    keys = baseline.load_baseline(p)
    assert keys == {"advisory-check|src/a.py:2"}
    assert baseline.is_baseline_suppressed(
        "advisory-check", "src/a.py:2", set(), keys
    ) is True


def test_blocking_ids_does_not_change_either_answer(tmp_path):
    """Both spellings of `blocking_ids` must agree at both sites.

    The parameter survives in the signature (a re-exported API) and is unused by
    design; a future edit that starts keying on it again re-creates #363, and
    this is the assertion that would notice.
    """
    key = baseline.finding_key("advisory-check", "src/a.py:2")
    for blocking_ids in (set(), {"advisory-check"}, {"unrelated"}):
        assert baseline.is_baseline_suppressed(
            "advisory-check", "src/a.py:2", blocking_ids, {key}
        ) is True
        assert baseline.is_baseline_suppressed(
            "advisory-check", "src/a.py:2", blocking_ids, set()
        ) is False

    findings = [("advisory-check", "src/a.py:2", "m", "")]
    seen = set()
    for i, blocking_ids in enumerate((set(), {"advisory-check"}, {"unrelated"})):
        p = str(tmp_path / f"b{i}" / "checks_baseline.txt")
        baseline.write_baseline(p, findings, blocking_ids=blocking_ids)
        seen.add(frozenset(baseline.load_baseline(p)))
    assert len(seen) == 1, seen


def test_coverage_never_suppresses_however_it_is_baselined():
    """Phase 61b's carve-out at `is_baseline_suppressed` — an EARLY RETURN.

    #363 removed the `blocking_ids` conjunct on the line below it, which cannot
    reach this branch. The four spellings are the ones a careless edit produces.
    """
    key = baseline.finding_key("coverage-diff-python", "billing/charge.py:12")
    for blocking_ids in (set(), {"coverage-diff-python"}):
        for bl in (set(), {key}):
            assert baseline.is_baseline_suppressed(
                "coverage-diff-python", "billing/charge.py:12", blocking_ids, bl
            ) is False


def test_coverage_is_never_written_however_it_is_classified(tmp_path):
    """Phase 61b's carve-out at `write_baseline` — a SIBLING conjunct.

    It survives #363's edit as `if not _is_coverage(check_id)`. Deleting the
    whole condition rather than the one conjunct is the authoring hazard the
    filing names, and this is what fails when someone does.
    """
    findings = [
        ("coverage-diff-python", "billing/charge.py:12", "m", ""),
        ("coverage-diff-frontend", "web/app.tsx:4", "m", ""),
        ("advisory-check", "src/a.py:2", "m", ""),
    ]
    for i, blocking_ids in enumerate((set(), {"coverage-diff-python"})):
        p = str(tmp_path / f"c{i}" / "checks_baseline.txt")
        written = baseline.write_baseline(p, findings, blocking_ids=blocking_ids)
        keys = baseline.load_baseline(p)
        assert not any(k.startswith("coverage-") for k in keys), keys
        assert written == 1


def test_a_finding_not_in_the_baseline_never_suppresses():
    """The other whole-condition deletion: suppressing everything unconditionally."""
    assert baseline.is_baseline_suppressed(
        "gate-check", "src/a.py:1", {"gate-check"}, set()
    ) is False
    assert baseline.is_baseline_suppressed(
        "gate-check", "src/a.py:1", {"gate-check"},
        {baseline.finding_key("gate-check", "src/OTHER.py:1")},
    ) is False


# ── 3. the #363 contract, end to end through the CLI ────────────────────────


def test_update_baseline_writes_the_advisory_check_too(tmp_path, monkeypatch, capsys):
    """The regeneration path, run for real: both checks reach the file."""
    _tree(tmp_path)
    code = _run(tmp_path, monkeypatch, ["--update-baseline"])
    err = capsys.readouterr().err
    assert code == 0
    keys = _baseline_keys(tmp_path)
    assert {k.split("|")[0] for k in keys} == {"gate-check", "advisory-check"}, keys
    # The printed tally is what was persisted, not a second copy of the filter.
    assert f"Wrote {len(keys)} baseline finding(s)" in err


def test_a_regenerated_baseline_silences_the_next_run(tmp_path, monkeypatch, capsys):
    """Round-trip through the real gate: regenerate, then re-run clean."""
    _tree(tmp_path)
    assert _run(tmp_path, monkeypatch, ["--update-baseline"]) == 0
    capsys.readouterr()
    code = _run(tmp_path, monkeypatch, ["--fail-on-blocking"])
    out = capsys.readouterr()
    assert code == 0
    assert out.out.count("[baseline]") == 2, out.out
    assert "baseline-matched: 2" in out.err


def test_an_advisory_baseline_entry_cannot_change_the_exit_code(tmp_path, monkeypatch,
                                                               capsys):
    """The asymmetry `--fail-on-blocking` keeps: it reads `blocking` itself.

    This is the claim the shipped prose makes, and the reason #363 is safe to
    ship as a one-conjunct edit. Baselining the advisory finding tags it and
    changes nothing else; the blocking finding still fails the gate.
    """
    _tree(tmp_path)
    _write_baseline_lines(tmp_path, [_key("advisory-check", "src/a.py:2")])
    code = _run(tmp_path, monkeypatch, ["--fail-on-blocking"])
    out = capsys.readouterr()
    assert code == 1, "the blocking finding is still fresh"
    assert "[baseline] " in out.out
    assert out.out.count("[baseline]") == 1
    # …and with the advisory entry removed the exit code is identical.
    _write_baseline_lines(tmp_path, [])
    assert _run(tmp_path, monkeypatch, ["--fail-on-blocking"]) == 1
    assert "[baseline]" not in capsys.readouterr().out


def test_baselining_the_blocking_finding_still_clears_the_gate(tmp_path, monkeypatch,
                                                              capsys):
    """The half #363 did not touch, asserted so a regression here is visible."""
    _tree(tmp_path)
    _write_baseline_lines(tmp_path, [_key("gate-check", "src/a.py:1")])
    code = _run(tmp_path, monkeypatch, ["--fail-on-blocking"])
    out = capsys.readouterr()
    assert code == 0
    assert "[baseline] " in out.out
    assert "new blocking: 0" in out.err


# ── 4. what the round added: the promotion consequence, made visible ─────────


def test_a_promoted_check_reports_its_own_inert_gate(tmp_path, monkeypatch, capsys):
    """Baselining an advisory check and *then* promoting it leaves the gate inert.

    Found by this phase's round, reproduced end to end: `--update-baseline` while
    the check is advisory, flip it to `blocking: true`, and the run prints
    `new blocking: 0` and exits 0 with the findings tagged `[baseline]`. Before
    #363 that same sequence exited 1, so it is a change and not a curiosity.

    It is also the correct answer for an accepted finding — a baseline entry means
    "do not fail CI" — which is exactly why leaving it *silent* is the part that
    could not stand: an armed-but-inert gate reads like a clean scan, which is the
    failure Sysop exists to make visible. So the contract asserted here is not that
    the exit code changes; it is that the run says so.
    """
    _tree(tmp_path)
    assert _run(tmp_path, monkeypatch, ["--update-baseline"]) == 0
    capsys.readouterr()

    # Promote the advisory check, changing nothing else.
    p = tmp_path / ".claude" / "checks.yml"
    p.write_text(p.read_text().replace("blocking: false", "blocking: true"))

    code = _run(tmp_path, monkeypatch, ["--fail-on-blocking"])
    out = capsys.readouterr()
    assert code == 0, "the accepted findings are still accepted"
    assert "new blocking: 0" in out.err
    assert "blocking suppressed: advisory-check, gate-check" in out.err, out.err
    assert "the gate covers new findings only" in out.err


def test_the_summary_stays_quiet_when_no_blocking_check_is_suppressed(tmp_path,
                                                                     monkeypatch,
                                                                     capsys):
    """The line must not fire on the healthy case, or it gets ignored.

    An advisory-only baseline suppresses nothing on a blocking check, so there is
    no inert gate to report — and a warning that appears on every run is not a
    warning. (Same reasoning as Phase 192's `Scoped`/`Sampled` carve-out.)
    """
    _tree(tmp_path)
    _write_baseline_lines(tmp_path, [_key("advisory-check", "src/a.py:2")])
    _run(tmp_path, monkeypatch, ["--fail-on-blocking"])
    err = capsys.readouterr().err
    assert "baseline-matched: 1" in err
    assert "blocking suppressed" not in err, err


def test_distinct_rules_on_one_line_no_longer_share_a_key(tmp_path):
    """Three ESLint rules on one line are three suppressions, not one.

    **This test asserted the opposite until Phase 213, and the assertion was the
    defect.** It read "three findings, one suppression key" and its docstring
    explained the collapse as an ordinary consequence of the catch-all id — so
    the guard that should have caught `Q-246` was pinning it in place instead.
    `lint-error` is one id for the whole ESLint stage, so `lint-error|a.js:7`
    meant "whatever ESLint says about line 7", and one accepted entry excused
    every rule that would ever fire there — including a new one nobody reviewed.

    The rule id was in scope at the emit site the whole time (`lint.py`); it
    just went into the message instead of the key.
    """
    p = str(tmp_path / ".claude" / "checks_baseline.txt")
    findings = [
        ("lint-error", "a.js:7", "m", "no-unused-vars"),
        ("lint-error", "a.js:7", "m", "eqeqeq"),
        ("lint-error", "a.js:7", "m", "no-shadow"),
    ]
    written = baseline.write_baseline(p, findings, blocking_ids=set())
    raw = [ln for ln in open(p, encoding="utf-8").read().splitlines()
           if ln.strip() and not ln.startswith("#")]
    assert written == 3, "three distinct rules, three suppression keys"
    assert raw == [
        "lint-error|a.js:7|eqeqeq",
        "lint-error|a.js:7|no-shadow",
        "lint-error|a.js:7|no-unused-vars",
    ], raw

    # Accepting one rule must not accept the others — the actual Q-246 defect.
    accepted = baseline.load_baseline(p) - {"lint-error|a.js:7|no-shadow",
                                            "lint-error|a.js:7|eqeqeq"}
    assert baseline.is_baseline_suppressed(
        "lint-error", "a.js:7", set(), accepted, "no-unused-vars")
    assert not baseline.is_baseline_suppressed(
        "lint-error", "a.js:7", set(), accepted, "no-shadow")


def test_a_genuine_duplicate_is_still_written_once(tmp_path):
    """The dedup property the inverted test above was really about.

    Deduplication is still correct and still worth a guard — it just needs a
    genuine duplicate (same check, same line, same identity) rather than three
    different findings that only looked like duplicates because the key was too
    coarse to tell them apart.
    """
    p = str(tmp_path / ".claude" / "checks_baseline.txt")
    findings = [
        ("lint-error", "a.js:7", "m", "no-unused-vars"),
        ("lint-error", "a.js:7", "m", "no-unused-vars"),
    ]
    written = baseline.write_baseline(p, findings, blocking_ids=set())
    assert written == 1
    assert written == len(baseline.load_baseline(p))


# ── 5. what lens 3 walked through: the caller, atomicity, order, the prose ────


def test_the_caller_prints_the_writers_own_count_not_a_second_derivation(tmp_path):
    """The structural claim of the #363 fix, which had no guard until lens 3 asked.

    The phase's stated fix was "closed structurally … so there is no second copy
    left to drift". Lens 3 replaced the call with a behaviour-identical
    re-derivation at the call site and nothing fired — the property was reported as
    achieved and enforced nowhere. Behaviour tests cannot see it, because a correct
    duplicate behaves correctly; what fails here is the duplicate's *existence*.
    """
    cli = (REPO_ROOT / "core" / "companion" / "scripts" / "run_checks" / "cli.py"
           ).read_text(encoding="utf-8")
    i = cli.index("write_baseline(baseline_file, all_findings, blocking_ids)")
    call_line = cli[cli.rindex("\n", 0, i) + 1:cli.index("\n", i)]
    # The variable's NAME is the author's business — renaming it is an ordinary edit
    # and reddening on it would be over-strictness (lens 3's D15). What matters is
    # that the call's result is bound and that the printed tally is that binding.
    m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*) = write_baseline\(", call_line)
    assert m, f"the write_baseline result is not bound at the call site: {call_line!r}"
    var = m.group(1)
    tally = next(ln for ln in cli.splitlines() if "baseline finding(s) to" in ln)
    assert "{" + var + "}" in tally, (
        f"the printed tally does not use the value write_baseline returned: {tally!r}")
    after = cli[cli.index("\n", i):cli.index("baseline finding(s) to")]
    assert "for cid" not in after and "sum(" not in after, (
        "a second derivation of the write filter reappeared at the call site: " + after
    )


def test_the_baseline_write_is_atomic(tmp_path, monkeypatch):
    """A crash mid-write must not leave a truncated baseline as authoritative.

    The pre-existing guard asserted only that no `.tmp` file survives — which a
    mutation that removes the tempfile entirely also satisfies, since it never
    creates one. Lens 3 deleted `os.replace` and the tmp path and the suite stayed
    green. This drives the failure instead: the write raises after the temp file
    exists, and the original must be intact.
    """
    p = tmp_path / ".claude" / "checks_baseline.txt"
    p.parent.mkdir(parents=True)
    p.write_text("# pre-existing\n\nold-check|src/a.py:1\n")
    before = p.read_text()

    real_replace = baseline.os.replace

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(baseline.os, "replace", boom)
    try:
        baseline.write_baseline(str(p), [("new", "src/b.py:2", "m", "")],
                                blocking_ids=set())
    except OSError:
        pass
    monkeypatch.setattr(baseline.os, "replace", real_replace)
    assert p.read_text() == before, (
        "the original baseline was modified in place — the write is not atomic"
    )
    assert baseline.load_baseline(str(p)) == {"old-check|src/a.py:1"}


def test_the_baseline_is_written_in_sorted_order(tmp_path):
    """Stable order, so a regenerated baseline diffs as the change and nothing else.

    `sorted(all_findings)` is removable with every other assertion green (lens 3),
    and the cost is a review diff full of reordered lines whenever the scan order
    shifts — which is how a real change hides.
    """
    p = str(tmp_path / ".claude" / "checks_baseline.txt")
    findings = [
        ("zeta", "src/z.py:1", "m", ""),
        ("alpha", "src/a.py:9", "m", ""),
        ("alpha", "src/a.py:2", "m", ""),
    ]
    baseline.write_baseline(p, findings, blocking_ids=set())
    keys = [ln for ln in open(p, encoding="utf-8").read().splitlines()
            if ln.strip() and not ln.startswith("#")]
    assert keys == sorted(keys), keys


def test_the_corrected_prose_sites_stay_corrected():
    """Three of the phase's own prose corrections reverted with the suite green.

    The baseline-file header ships into *every consumer's* repo, and
    `--update-baseline`'s help is what `--help` prints; both stated the
    blocking-only rule that #363 removed. Asserted here rather than trusted,
    because a doc fix with no guard is a doc fix that lasts until the next edit.
    """
    src = REPO_ROOT / "core" / "companion" / "scripts" / "run_checks"
    cli = (src / "cli.py").read_text(encoding="utf-8")
    wf = (REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md").read_text(
        encoding="utf-8")

    # **Read the header off a file the function produced**, not out of its source.
    # Slicing the source between two literals reddens when the header is hoisted to a
    # module constant (lens 3's D34) — a refactor that changes nothing a consumer
    # sees. What ships is the bytes, so assert the bytes.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        gen = str(Path(td) / "d" / "checks_baseline.txt")
        baseline.write_baseline(gen, [], blocking_ids=set())
        header = open(gen, encoding="utf-8").read()
    assert "blocking: false` check's entries record a triage verdict" in header, header
    assert "Only a `blocking: true`" not in header, header

    help_line = next(ln for ln in cli.splitlines() if "to the baseline " in ln
                     or "the baseline\n" in ln)
    assert "blocking-check findings" not in cli, "the argparse help reverted"
    assert "every check's accepted findings except coverage" in wf, (
        "WORKFLOW.md's § 8.2 file-table row reverted to 'Blocking-check baseline'")
    assert "Blocking-check baseline" not in wf, "the § 8.2 row reverted"
    assert help_line  # non-vacuity: the line was found
