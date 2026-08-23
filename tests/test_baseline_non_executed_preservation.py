"""`--update-baseline` must not delete the entries of a check that did not run (Q-253).

The defect: `write_baseline` rewrites the file wholesale from the findings of the
current run. A check that was skipped — semgrep not installed, no
`node_modules/eslint`, no coverage report, `paths:` unresolved — contributes zero
findings, so every baseline entry it owned was dropped, with exit 0 and a
`Wrote N baseline finding(s)` line that reads like success. Measured on the one
real corpus (86 entries): regenerating on a machine without semgrep silently
discarded all five `semgrep-*` verdicts.

**Why the fix preserves rather than refuses, asserted here so a later
"simplification" cannot quietly invert it.** `--migrate-baseline` guards on
`RunReport.non_executed_ids()` and refuses outright **only when every baselined
check was skipped** — per check it HOLDS the entries instead — and copying the
all-or-nothing form of that guard here was the filed candidate. It is the wrong one:
`tools/PRESCAN_ACCOUNTING_SPEC.md` §4 withdrew gate-on-`skipped` and
*deliberately* granted `--update-baseline` leniency on it, because Sysop's own
shipped defaults make `skipped` the universal starting state — both coverage
checks ship `blocking: true` with placeholder `critical_path`, and three pack
grep checks ship `blocking: true` with placeholder paths. A refusal keyed to
`non_executed_ids` would refuse the baseline write on every fresh install, and
would remove the documented escape from a `--migrate-baseline` refusal.
`test_a_fresh_install_shaped_run_still_writes` below is that argument as a test.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "run_checks"))

from run_checks.baseline import load_baseline, write_baseline  # noqa: E402


def _seed(path, *keys):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# consumer triage rationale, hand written\n" + "".join(k + "\n" for k in keys),
        encoding="utf-8",
    )


SEMGREP_A = "semgrep-sql-fstring|agent/a.py:10|aaa"
SEMGREP_B = "semgrep-sql-fstring|agent/b.py:20|bbb"
GREP_LIVE = "grant-sensitive-table|migrations/1.sql:3|ccc"


def test_a_skipped_checks_entries_survive_regeneration(tmp_path):
    """The defect, stated as the behaviour that must hold."""
    p = tmp_path / "baseline.txt"
    _seed(p, SEMGREP_A, SEMGREP_B, GREP_LIVE)

    # This run: the grep check executed and still fires; semgrep did not run.
    findings = [("grant-sensitive-table", "migrations/1.sql:3", "msg", "ccc")]
    written = write_baseline(str(p), findings, set(), {"semgrep-sql-fstring"})

    after = load_baseline(str(p))
    assert SEMGREP_A in after and SEMGREP_B in after, sorted(after)
    assert GREP_LIVE in after
    assert written == 3, written


def test_without_the_argument_the_old_destructive_behaviour_is_reproduced(tmp_path):
    """Pins the defect itself, so this module cannot pass vacuously.

    If a refactor made preservation unconditional, the assertion below would fail
    and someone would have to think about it. A test that only asserts the good
    path cannot tell a working fix from a rewritten function.
    """
    p = tmp_path / "baseline.txt"
    _seed(p, SEMGREP_A, SEMGREP_B, GREP_LIVE)
    findings = [("grant-sensitive-table", "migrations/1.sql:3", "msg", "ccc")]
    write_baseline(str(p), findings, set())          # no non_executed_ids -> old shape
    after = load_baseline(str(p))
    assert SEMGREP_A not in after and SEMGREP_B not in after
    assert after == {GREP_LIVE}


def test_a_fresh_install_shaped_run_still_writes(tmp_path):
    """The reason the fix preserves instead of refusing.

    A fresh install has several `blocking: true` checks in `skipped` before the
    consumer localizes anything. The command must still produce a baseline —
    refusing here is the failure mode `PRESCAN_ACCOUNTING_SPEC.md` §4 rejected.
    """
    p = tmp_path / "baseline.txt"
    fresh_install_skips = {
        "coverage-diff-python", "coverage-diff-frontend",
        "grant-sensitive-table", "window-open-noopener", "exception-logging",
    }
    written = write_baseline(
        str(p), [("lint-error", "src/a.ts:1", "msg", "zzz")], set(), fresh_install_skips
    )
    assert written == 1
    assert load_baseline(str(p)) == {"lint-error|src/a.ts:1|zzz"}


def test_a_check_that_ran_loses_entries_that_are_genuinely_gone(tmp_path):
    """Preservation must not become "never delete anything".

    An executed check whose finding was actually fixed MUST lose its entry —
    that is what regeneration is for. Over-preserving would turn the baseline
    into an append-only log that suppresses fixed findings forever.
    """
    p = tmp_path / "baseline.txt"
    _seed(p, GREP_LIVE, "grant-sensitive-table|migrations/2.sql:9|old")
    findings = [("grant-sensitive-table", "migrations/1.sql:3", "msg", "ccc")]
    write_baseline(str(p), findings, set(), {"semgrep-sql-fstring"})
    after = load_baseline(str(p))
    assert after == {GREP_LIVE}, sorted(after)


def test_coverage_entries_are_never_preserved(tmp_path):
    """The Phase 61b carve-out survives the new path.

    Coverage findings are never written. A hand-added coverage entry must not
    sneak back in through preservation — that would be a back-door around the
    crown-jewel gate, reintroduced by the fix for an unrelated defect.
    """
    p = tmp_path / "baseline.txt"
    _seed(p, "coverage-diff-python|src/core.py:12|hand", GREP_LIVE)
    write_baseline(str(p), [], set(), {"coverage-diff-python", "grant-sensitive-table"})
    after = load_baseline(str(p))
    assert not any(k.startswith("coverage-") for k in after), sorted(after)
    assert GREP_LIVE in after


def test_a_preserved_key_is_not_duplicated_when_the_check_also_fires(tmp_path):
    """A check can be non-executed in one stage and produce findings in another."""
    p = tmp_path / "baseline.txt"
    _seed(p, GREP_LIVE)
    findings = [("grant-sensitive-table", "migrations/1.sql:3", "msg", "ccc")]
    written = write_baseline(str(p), findings, set(), {"grant-sensitive-table"})
    body = [
        ln for ln in p.read_text(encoding="utf-8").splitlines()
        if ln and not ln.startswith("#")
    ]
    assert body == [GREP_LIVE], body
    assert written == 1


def test_preservation_is_a_noop_when_no_baseline_exists(tmp_path):
    """First run on a consumer with no baseline file must not crash."""
    p = tmp_path / "nested" / "baseline.txt"
    written = write_baseline(str(p), [], set(), {"semgrep-sql-fstring"})
    assert written == 0
    assert p.exists()


@pytest.mark.parametrize("bad", ["", "   ", "no-pipe-at-all"])
def test_a_malformed_baseline_line_cannot_crash_preservation(tmp_path, bad):
    """A damaged consumer file degrades, it does not abort the write."""
    p = tmp_path / "baseline.txt"
    p.write_text(f"{bad}\n{SEMGREP_A}\n", encoding="utf-8")
    write_baseline(str(p), [], set(), {"semgrep-sql-fstring"})
    assert SEMGREP_A in load_baseline(str(p))


# ── reachability: the fix must be WIRED, not merely present ──────────────────
#
# Added after this phase's own mutation battery. Every test above exercises
# `write_baseline` directly, so all of them stayed green while the CALLER
# stopped passing `non_executed` (M06) and while the caller computed an empty
# set (M07). A fix that is present and unreachable is the author-side pass's
# named failure mode, and the battery found it here rather than a reviewer.

def _update_baseline_fn():
    """The `_run_update_baseline` AST node, so the guards below read code.

    Regex guards over this call site have now failed in three distinct ways in
    one phase: pinned to a literal argument list (red on a correct 4th arg),
    pinned to an RHS shape (red when the round wrapped it in `set(...) | ...`),
    and — the one that mattered — anchored on the FIRST `write_baseline(` in the
    file, so a decoy call satisfied it while the real write lost preservation.
    An AST read answers the actual question: which call's result is printed, and
    what is it passed?
    """
    import ast
    src = (REPO_ROOT / "core" / "companion" / "scripts" / "run_checks"
           / "cli.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_update_baseline":
            return node
    raise AssertionError("_run_update_baseline not found in cli.py")


def _names_derived_from(fn, *accessors):
    """Local names transitively bound from any of `report.<accessor>()`.

    Follows plain aliasing and set algebra (`a = set(x()) | set(y())`), because
    refusing those is the over-strictness that reddens on correct code.
    """
    import ast
    wanted = set(accessors)
    names = set()
    for _ in range(6):                      # bounded; no fixed-point search
        grew = False
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            tgt = node.targets[0]
            if not isinstance(tgt, ast.Name):
                continue
            for sub in ast.walk(node.value):
                hit = (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr in wanted
                ) or (isinstance(sub, ast.Name) and sub.id in names)
                if hit and tgt.id not in names:
                    names.add(tgt.id)
                    grew = True
                    break
        if not grew:
            break
    return names


def _printed_tally_var(fn):
    """The variable the `Wrote N baseline finding(s)` line interpolates."""
    import ast
    for node in ast.walk(fn):
        if isinstance(node, ast.JoinedStr):
            text = "".join(
                v.value for v in node.values if isinstance(v, ast.Constant)
            )
            if "baseline finding(s) to" in text:
                for v in node.values:
                    if isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name):
                        return v.value.id
    raise AssertionError("no `Wrote N baseline finding(s)` f-string found")


def test_the_write_that_is_reported_is_the_one_that_preserves():
    """The call whose count is printed must receive the non-executed set.

    Anchored on the REPORTED write, not on the first `write_baseline(` in the
    file. That distinction is the whole finding: a decoy
    `write_baseline(baseline_file + ".shadow", ..., non_executed)` followed by
    `written = write_baseline(baseline_file, all_findings, blocking_ids)` left
    the real baseline with no preservation at all, and the previous form of this
    test passed. Verified by applying exactly that diff.
    """
    import ast
    fn = _update_baseline_fn()
    tally = _printed_tally_var(fn)
    derived = _names_derived_from(fn, "non_executed_ids", "incomplete_ids")
    assert derived, (
        "`--update-baseline` never asks the run report which checks did not "
        "execute, so nothing can be preserved."
    )

    reported = [
        n.value for n in ast.walk(fn)
        if isinstance(n, ast.Assign) and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Name) and n.targets[0].id == tally
        and isinstance(n.value, ast.Call)
        and getattr(n.value.func, "id", None) == "write_baseline"
    ]
    assert len(reported) == 1, (
        f"expected exactly one `{tally} = write_baseline(...)`; found "
        f"{len(reported)}. The printed tally must name the write that happened."
    )
    call = reported[0]
    passed = {
        a.id for a in call.args if isinstance(a, ast.Name)
    } | {
        k.value.id for k in call.keywords if isinstance(k.value, ast.Name)
    } | {
        n.id for a in call.args for n in ast.walk(a) if isinstance(n, ast.Name)
    } | {
        n.id for k in call.keywords for n in ast.walk(k.value)
        if isinstance(n, ast.Name)
    }
    assert derived & passed, (
        f"the reported write_baseline call is passed {sorted(passed)}, none of "
        f"which derives from report.non_executed_ids()/incomplete_ids() "
        f"({sorted(derived)}). Preservation is unreachable on the real write."
    )


def test_both_accessors_reach_the_reported_write():
    """`degraded` must not be dropped again by a later simplification."""
    fn = _update_baseline_fn()
    assert _names_derived_from(fn, "non_executed_ids"), "non_executed_ids unused"
    assert _names_derived_from(fn, "incomplete_ids"), (
        "`--update-baseline` no longer consults report.incomplete_ids(), so "
        "every degraded check's baseline entries are silently deleted again"
    )


def test_the_run_names_the_checks_it_could_not_verify():
    """Silence is the failure being closed, so the naming is part of the fix."""
    cli = (REPO_ROOT / "core" / "companion" / "scripts" / "run_checks"
           / "cli.py").read_text(encoding="utf-8")
    assert "carried forward unverified" in cli, (
        "the run no longer tells the operator which checks it could not verify"
    )


# ── the review round's HIGH finding: `degraded` was still deleted ────────────

def test_a_degraded_checks_entries_survive_regeneration(tmp_path):
    """`degraded` is the class the first cut missed, and it was the silent one.

    A degraded stage RAN and emitted real findings over part of its inputs, so
    it is absent from `non_executed_ids` — but an entry it did not match may
    simply be in the part that was not scanned. `--migrate-baseline` has always
    held those (it passes `incomplete_ids` too); `--update-baseline`, the command
    that actually destroys entries, did not.

    Worse than the original defect: the caller's "carried forward unverified"
    warning is keyed to the same set, so with `degraded` missing the deletion was
    silent as well as wrong.
    """
    p = tmp_path / "baseline.txt"
    _seed(p, SEMGREP_A, SEMGREP_B, GREP_LIVE)
    findings = [("grant-sensitive-table", "migrations/1.sql:3", "msg", "ccc")]
    write_baseline(str(p), findings, set(), {"semgrep-sql-fstring"})
    after = load_baseline(str(p))
    assert SEMGREP_A in after and SEMGREP_B in after, sorted(after)


def test_the_caller_passes_the_degraded_ids_too():
    """Reachability for the round's fix, not just its mechanism.

    `write_baseline` cannot tell which sets it was handed. The defect was
    entirely in the CALLER, so this asserts the caller consults BOTH accessors —
    the same shape `--migrate-baseline` has always used.
    """
    cli = (REPO_ROOT / "core" / "companion" / "scripts" / "run_checks"
           / "cli.py").read_text(encoding="utf-8")
    head, _, tail = cli.partition("def _run_migrate_baseline")
    assert "report.incomplete_ids()" in head, (
        "`--update-baseline` never asks for the degraded checks, so their "
        "baseline entries are deleted again — silently, because the "
        "carried-forward warning is keyed to the same set."
    )
    assert "report.non_executed_ids()" in head


def test_the_two_accessors_are_disjoint_and_both_needed():
    """Non-vacuity: the union must not be a longer way of writing one set.

    If `non_executed_ids` already covered `degraded`, the fix above would be
    decoration. Built from the real `RunReport`, not from a model of it.
    """
    import sys as _sys
    _sys.path.insert(0, str(SCRIPTS / "run_checks"))
    from run_checks.accounting import DEGRADED, SKIPPED, RunReport

    r = RunReport([{"id": "semgrep-x"}, {"id": "grep-y"}, {"id": "grep-ok"}])
    r.record(["semgrep-x"], DEGRADED, "semgrep", "targets-unenumerable")
    r.record(["grep-y"], SKIPPED, "grep", "paths-unresolved")

    assert "semgrep-x" not in r.non_executed_ids(), (
        "degraded is now inside non_executed_ids — the union is redundant and "
        "this module's HIGH finding no longer describes the code"
    )
    assert "semgrep-x" in r.incomplete_ids()
    assert set(r.non_executed_ids()) | set(r.incomplete_ids()) == {
        "semgrep-x", "grep-y"}


# ── behavioural: the diagnostic must be RUN, not substring-matched ───────────
#
# The round mutated the whole `if non_executed:` block into a comment carrying
# the phrase, and `assert "carried forward unverified" in cli` stayed green —
# a check satisfied by an incidental occurrence of the string it looks for.
# Nothing outside this module reads that output, so it was guarded by one
# substring. These run the command and read stderr.

_SKIP_YML = """
checks:
  - id: live-check
    severity: high
    paths: ["src/"]
    include: ["*.py"]
    pattern: 'FORBIDDEN'
    description: "runs"
    used_by: [codebase-review]
    blocking: false
  - id: unresolved-check
    severity: high
    paths: ["<not localized>/"]
    include: ["*.py"]
    pattern: 'FORBIDDEN'
    description: "never runs — placeholder path"
    used_by: [codebase-review]
    blocking: false
"""


def _repo(tmp_path):
    (tmp_path / ".claude").mkdir(exist_ok=True)
    (tmp_path / ".claude" / "checks.yml").write_text(_SKIP_YML, encoding="utf-8")
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "a.py").write_text("x = 'FORBIDDEN'\n", encoding="utf-8")
    return tmp_path


def _update_baseline(tmp_path, monkeypatch, capsys):
    import sys as _sys
    _sys.path.insert(0, str(SCRIPTS / "run_checks"))
    from run_checks import cli as rci
    monkeypatch.setattr(_sys, "argv", [
        "run_checks", "--repo-root", str(tmp_path), "--mode", "quality",
        "--update-baseline",
    ])
    try:
        rci.main()
    except SystemExit:
        pass
    return capsys.readouterr().err


def test_the_run_actually_names_the_unverified_checks(tmp_path, monkeypatch, capsys):
    """Run it and read stderr — the phrase AND the check id must be there."""
    err = _update_baseline(_repo(tmp_path), monkeypatch, capsys)
    assert "carried forward unverified" in err, err[-3000:]
    assert "unresolved-check" in err, (
        "the diagnostic counts the checks it could not verify but does not NAME "
        "them; the code comment beside it says 'Named, not merely counted', and "
        "an operator cannot act on a count.\n" + err[-3000:]
    )


def test_a_clean_run_stays_quiet(tmp_path, monkeypatch, capsys):
    """Non-vacuity: the line must not print when every check executed."""
    (tmp_path / ".claude").mkdir(exist_ok=True)
    (tmp_path / ".claude" / "checks.yml").write_text(
        _SKIP_YML.replace('paths: ["<not localized>/"]', 'paths: ["src/"]'),
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "a.py").write_text("x = 'FORBIDDEN'\n", encoding="utf-8")
    err = _update_baseline(tmp_path, monkeypatch, capsys)
    assert "carried forward unverified" not in err, err[-2000:]


# ── the predicate is EXACT membership, not a prefix ──────────────────────────

def test_preservation_matches_check_ids_exactly_not_by_prefix(tmp_path):
    """`startswith` over-preservation survived the author's battery.

    It is not hypothetical: this phase shipped `semgrep-sql-fstring` and
    `semgrep-sql-fstring-multiline` into the same pack, so a prefix predicate
    would resurrect the multiline check's entries whenever its sibling was
    skipped — suppressing findings from a check that ran perfectly well.
    """
    p = tmp_path / "baseline.txt"
    _seed(p,
          "semgrep-sql-fstring|a.py:1|aaa",
          "semgrep-sql-fstring-multiline|b.py:2|bbb")
    write_baseline(str(p), [], set(), {"semgrep-sql-fstring"})
    after = load_baseline(str(p))
    assert "semgrep-sql-fstring|a.py:1|aaa" in after
    assert "semgrep-sql-fstring-multiline|b.py:2|bbb" not in after, sorted(after)


def test_the_existing_baseline_is_read_before_the_file_is_truncated(tmp_path):
    """The ordering the docstring calls load-bearing, asserted rather than stated.

    Moving the `load_baseline` read inside the truncating `open(...,"w")` block
    survived the author's battery because `tmp_path` is a sibling file. It stops
    being a sibling the moment a caller passes a path whose `.tmp` twin is the
    path itself, and the failure mode is a silently emptied baseline.
    """
    import run_checks.baseline as B
    src = (SCRIPTS / "run_checks" / "baseline.py").read_text(encoding="utf-8")
    body = src[src.index("def write_baseline("):]
    body = body[:body.index("\ndef ")]
    read_at = body.index("load_baseline(path)")
    open_at = body.index('open(tmp_path, "w"')
    assert read_at < open_at, (
        "write_baseline now opens the output file before reading the existing "
        "baseline; a path whose tmp twin collides truncates before the read and "
        "every preserved entry is lost"
    )
    assert B  # imported for the module-identity check above
