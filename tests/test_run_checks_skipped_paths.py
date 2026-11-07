"""A stage that did not read a file no longer reads as having read it.

Two defects, one mechanism:

* A per-file semgrep error that names a target — a rule ``Timeout`` above all —
  left the stage ``executed``, so a file a rule never finished read as a clean
  zero. It is now ``degraded`` and names the file, as a partial parse does.
* semgrep's default ignore list (``vendor/``, ``build/``, ``node_modules/`` …)
  and its 1,000,000-byte size limit drop files from a directory scan with no
  trace, and grep drops the match in a file holding a NUL byte. The stage stays
  ``executed`` — every other file's silence is still evidence — but the dropped
  files go in the check's skip set (`RunReport.skipped_paths`), the run names
  them once, and a baseline entry anchored in one of them is held: not called
  stale, not deleted by ``--update-baseline``, not dropped by
  ``--migrate-baseline``.

Shapes are the ones measured at semgrep 1.157.0, BSD grep 2.6.0 and GNU grep 3.8.
"""
import json
import os
import shutil
import subprocess
import sys
from unittest.mock import patch

import pytest

import run_checks.baseline as baseline
import run_checks.grep as grep_mod
import run_checks.semgrep as semgrep_mod
import run_checks_impl as rci
from run_checks.accounting import DEGRADED, EXECUTED, FAILED, RunReport

needs_semgrep = pytest.mark.skipif(
    shutil.which("semgrep") is None, reason="semgrep not on PATH")

SG = "semgrep-marker"
SG_IDS = {SG: {"id": SG}}

RULES = (
    "rules:\n"
    "  - id: marker\n"
    "    languages: [python]\n"
    "    severity: WARNING\n"
    "    message: marker\n"
    "    pattern: DANGER(...)\n"
)
HIT = "def f():\n    DANGER(1)\n"
# Over the limit on bytes, one line long, so a rule finishes it in milliseconds
# when it is scanned at all — the size test must not become a timeout test.
BIG = HIT + "# " + "a" * 1_200_000 + "\n"


def _completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def _semgrep_stub(payload, returncode=0, tracked=("src/a.py",)):
    def _side_effect(argv, *a, **kw):
        if list(argv[:2]) == ["git", "ls-files"]:
            return _completed("\0".join(tracked) + "\0")
        return _completed(json.dumps(payload), returncode=returncode)
    return _side_effect


def _git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                "GIT_TERMINAL_PROMPT": "0"})
    r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                       text=True, env=env)
    assert r.returncode == 0, f"git {args}: {r.stderr}"


def _write(root, rel, body):
    p = os.path.join(str(root), rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(body)


def _run_mocked(tmp_path, payload, returncode=0):
    (tmp_path / ".claude" / "semgrep").mkdir(parents=True, exist_ok=True)
    report = RunReport([{"id": SG}])
    with patch("run_checks.semgrep.subprocess.run",
               side_effect=_semgrep_stub(payload, returncode)):
        out = semgrep_mod._run_semgrep(str(tmp_path), SG_IDS, report)
    return report, out


_RESULT = {"check_id": "rules.marker", "path": "src/a.py", "start": {"line": 2},
           "extra": {"message": "marker", "severity": "WARNING",
                     "lines": "    DANGER(1)"}}
# The captured 1.157.0 shape of a rule timing out on one file.
_TIMEOUT = {"code": 2, "level": "warn", "type": "Timeout", "rule_id": "rules.slow",
            "message": "Timeout when running rules.slow on src/mid.py:\n ",
            "path": "src/mid.py"}


# ── Q-744: a per-file error is `degraded`, named ─────────────────────────────


def test_a_per_file_timeout_beside_results_is_degraded_and_named(tmp_path, capsys):
    # Absolute, as semgrep reports a result under the absolute `repo_root` operand.
    result = dict(_RESULT, path=str(tmp_path / "src" / "a.py"))
    report, out = _run_mocked(tmp_path, {"results": [result], "errors": [_TIMEOUT],
                                         "paths": {"scanned": ["src/a.py", "src/mid.py"]}})
    rec = report._records[SG]
    assert rec.status == DEGRADED, rec
    assert rec.reason == "file-errors", rec
    assert "src/mid.py" in rec.detail and "Timeout" in rec.detail, rec.detail
    assert [f[1] for f in out] == ["src/a.py:2"], "the findings still come through"
    err = capsys.readouterr().err
    assert "did not fully scan 1 file(s) (Timeout)" in err and "src/mid.py" in err, err


def test_a_timeout_with_no_results_and_exit_0_is_degraded_not_failed(tmp_path):
    """The measured case: one rule timed out on the only file holding a match,
    semgrep exited 0, and the stage reported `executed with 0 findings`."""
    report, _ = _run_mocked(tmp_path, {"results": [], "errors": [_TIMEOUT]})
    assert report._records[SG].status == DEGRADED


def test_scan_errors_with_no_results_and_a_nonzero_exit_still_fail(tmp_path):
    """The `failed` arm comes first and is unchanged."""
    report, _ = _run_mocked(tmp_path, {"results": [], "errors": [_TIMEOUT]},
                            returncode=2)
    assert report._records[SG].status == FAILED


def test_an_absolute_error_path_is_named_repo_relative(tmp_path):
    """A named operand is reported absolute when `repo_root` is."""
    err = dict(_TIMEOUT, path=str(tmp_path / "tests" / "big_t.py"))
    report, _ = _run_mocked(tmp_path, {"results": [], "errors": [err]})
    detail = report._records[SG].detail
    assert "tests/big_t.py" in detail and str(tmp_path) not in detail, detail


@pytest.mark.parametrize("error", [
    # Captured at 1.157.0: a rule's invalid pattern, and an invalid YAML rule file.
    {"code": 2, "level": "error", "type": "Rule parse error", "rule_id": "rules.y",
     "message": "Rule parse error in rule rules.y"},
    {"code": 5, "level": "error", "type": "SemgrepError",
     "message": "Invalid YAML file rules/bad.yaml"},
    # Defensive: an error pathed INSIDE the rules directory is about a rule.
    {"type": "InvalidRuleSchemaError", "path": ".claude/semgrep/r.yaml"},
], ids=["rule-parse", "invalid-yaml", "rules-dir-path"])
def test_a_rule_or_config_error_is_not_a_skipped_target(tmp_path, error):
    report, _ = _run_mocked(tmp_path, {"results": [_RESULT], "errors": [error]})
    assert report._records[SG].status == EXECUTED, report._records[SG]


def test_a_partial_parse_and_a_timeout_both_reach_the_detail(tmp_path):
    report, _ = _run_mocked(tmp_path, {"results": [], "errors": [
        {"type": ["PartialParsing", []], "path": "src/broken.py"}, _TIMEOUT]})
    rec = report._records[SG]
    assert rec.reason == "partial-parse", rec
    assert "src/broken.py" in rec.detail and "src/mid.py" in rec.detail, rec.detail


@needs_semgrep
def test_a_real_rule_timeout_is_degraded(tmp_path, capsys):
    """A probe on the real binary, not the pin: the timeout needs a rule to run
    past semgrep's 5 s default on this machine, so it skips when none arrives."""
    rules = RULES + (
        "  - id: slow\n"
        "    languages: [python]\n"
        "    severity: WARNING\n"
        "    message: slow\n"
        "    pattern: |\n"
        "      $A = $X\n      ...\n      $B = $Y\n      ...\n      $C = $Z\n"
        "      ...\n      DANGER(...)\n")
    _write(tmp_path, ".claude/semgrep/r.yaml", rules)
    _write(tmp_path, "src/mid.py", "def f():\n" + "".join(
        f"    x{i} = {i}\n" for i in range(30000)) + "    DANGER(1)\n")
    ids = {SG: {"id": SG}, "semgrep-slow": {"id": "semgrep-slow"}}
    report = RunReport([{"id": i} for i in ids])
    semgrep_mod._run_semgrep(str(tmp_path), ids, report)
    rec = report._records["semgrep-slow"]
    # semgrep's own error count, printed whatever the stage records, is the
    # evidence that a timeout happened at all.
    if "internal error(s)" not in capsys.readouterr().err:
        pytest.skip("no rule reached semgrep's per-file timeout on this machine")
    assert rec.status == DEGRADED and "src/mid.py" in rec.detail, rec


# ── Q-183: what semgrep's directory scan never reads ────────────────────────


@pytest.mark.parametrize("rel,dropped", [
    ("vendor/lib/v.py", True),
    ("a/b/node_modules/p/n.py", True),
    ("build/x.py", True),
    (".venv/lib/site.py", True),
    ("_cargo/x.rs", True),
    ("web/app.min.js", True),
    ("web/app.min.js/inner.js", True),   # no slash in `*.min.js`: a dir matches too
    ("CVS/Entries", True),
    ("src/vendor", False),               # `vendor/` is directory-only
    (".env", False),                     # `.env/` is directory-only
    ("src/builder/x.py", False),
    ("src/a.py", False),
    (".github/workflows/ci.yml", False),
])
def test_the_rest_of_the_default_ignore_list(rel, dropped):
    assert semgrep_mod._is_other_ignored_path(rel) is dropped


def _skip_corpus(root, semgrepignore=None):
    _git(root, "init", "-q", "-b", "main")
    _write(root, ".claude/semgrep/r.yaml", RULES)
    _write(root, ".claude/semgrep/fixtures/positive.py", HIT)
    for rel in ("src/a.py", "vendor/lib/v.py", "build/b.py", "node_modules/p/n.py",
                "vendor/x/tests/t.py"):
        _write(root, rel, HIT)
    _write(root, "web/app.min.js", "DANGER(1);\n")
    _write(root, "big/huge.py", BIG)
    _write(root, "tests/huge_t.py", BIG)
    if semgrepignore is not None:
        _write(root, ".semgrepignore", semgrepignore)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "corpus")


def test_untracked_files_reach_the_skip_set(tmp_path):
    """semgrep's directory scan reads untracked files too, so the walk counts
    them: with no `.semgrepignore` under the ignore list, and over the size
    limit either way."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _write(tmp_path, "src/a.py", HIT)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "seed")
    _write(tmp_path, "vendor/untracked.py", HIT)
    _write(tmp_path, "src/ubig.py", BIG)
    skipped = {}
    semgrep_mod._default_ignored_targets(str(tmp_path), ".claude/semgrep/fixtures", skipped)
    assert skipped == {"vendor/untracked.py": "ignore-list", "src/ubig.py": "size"}, skipped
    _write(tmp_path, ".semgrepignore", "")
    skipped = {}
    semgrep_mod._default_ignored_targets(str(tmp_path), ".claude/semgrep/fixtures", skipped)
    assert skipped == {"src/ubig.py": "size"}, skipped


def test_a_partial_parse_and_a_timeout_on_one_absolute_path_name_it_once(tmp_path):
    """semgrep reports both errors' paths absolute under the absolute operand."""
    p = str(tmp_path / "src" / "x.py")
    payload = {"results": [], "paths": {"scanned": []}, "errors": [
        {"type": ["PartialParsing", []], "path": p, "spans": [{"file": p}]},
        {"type": "Timeout", "path": p, "rule_id": "r"}]}
    report, _out = _run_mocked(tmp_path, payload)
    detail = report._records[SG].detail
    assert "Timeout" not in detail and detail.count("x.py") == 1, detail


def _real_run(root):
    report = RunReport([{"id": SG}])
    out = semgrep_mod._run_semgrep(str(root), SG_IDS, report)
    hits = {os.path.relpath(f[1].rsplit(":", 1)[0], str(root))
            if os.path.isabs(f[1]) else f[1].rsplit(":", 1)[0] for f in out}
    return report, hits


@needs_semgrep
def test_default_ignored_and_oversized_files_are_recorded_not_degraded(tmp_path, capsys):
    _skip_corpus(tmp_path)
    report, hits = _real_run(tmp_path)
    assert report._records[SG].status == EXECUTED, report._records[SG]
    skipped = report.skipped_paths()[SG]
    assert skipped == {"vendor/lib/v.py", "build/b.py", "node_modules/p/n.py",
                       "web/app.min.js", "big/huge.py"}, sorted(skipped)
    # The binary agrees: every skipped file holding a hit produced none, and
    # the files read — a named test file under vendor/ and one over the size
    # limit among them — did.
    assert not hits & skipped, hits & skipped
    assert {"src/a.py", "vendor/x/tests/t.py", "tests/huge_t.py"} <= hits, hits
    err = capsys.readouterr().err
    assert "5 file(s) were not given to semgrep" in err, err
    assert "4 under its default ignore list" in err, err
    assert "1 over its 1,000,000-byte size limit" in err, err


@needs_semgrep
def test_a_semgrepignore_turns_off_the_list_but_not_the_size_limit(tmp_path, capsys):
    """A root `.semgrepignore` replaces the default list, so `vendor/` and its
    siblings are scanned and nothing under them is recorded; what the consumer's
    own file ignores is their choice. The size limit still applies — measured —
    so the big files stay recorded, the test file among them now that it is no
    longer a named operand."""
    _skip_corpus(tmp_path, semgrepignore="docs/\n")
    report, hits = _real_run(tmp_path)
    assert report._records[SG].status == EXECUTED
    skipped = report.skipped_paths()[SG]
    assert skipped == {"big/huge.py", "tests/huge_t.py"}, sorted(skipped)
    assert not hits & skipped, hits & skipped
    assert {"src/a.py", "vendor/lib/v.py", "build/b.py"} <= hits, hits
    err = capsys.readouterr().err
    assert "2 file(s) were not given to semgrep" in err, err
    assert "default ignore list" not in err, err


@needs_semgrep
def test_a_clean_tree_records_no_skip_and_no_warning(tmp_path, capsys):
    _git(tmp_path, "init", "-q", "-b", "main")
    _write(tmp_path, ".claude/semgrep/r.yaml", RULES)
    _write(tmp_path, "src/a.py", HIT)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "c")
    report, _ = _real_run(tmp_path)
    assert report.skipped_paths() == {}
    assert "not given to semgrep" not in capsys.readouterr().err


# ── grep: a file holding a NUL byte ──────────────────────────────────────────

_GREP_CHECK = {"id": "grant", "severity": "critical", "blocking": True,
               "paths": ["migrations/"], "include": ["*.sql"],
               "pattern": "GRANT", "description": "GRANT"}


def _grep_mocked(tmp_path, stdout, stderr):
    (tmp_path / "migrations").mkdir(exist_ok=True)
    report = RunReport([_GREP_CHECK])
    with patch("run_checks.grep.subprocess.run",
               return_value=_completed(stdout, 0, stderr)):
        out = grep_mod.run_check(_GREP_CHECK, str(tmp_path), report)
    return report, out


@pytest.mark.parametrize("shape", ["bsd-stdout", "gnu-stderr"])
def test_a_binary_match_is_recorded_in_both_greps_shapes(tmp_path, capsys, shape):
    p = str(tmp_path / "migrations" / "a:b.sql")      # a colon in the path, too
    if shape == "bsd-stdout":
        report, out = _grep_mocked(tmp_path, f"Binary file {p} matches\n", "")
    else:
        report, out = _grep_mocked(tmp_path, "", f"grep: {p}: binary file matches\n")
    assert out == []
    assert report._records["grant"].status == EXECUTED
    assert report.skipped_paths() == {"grant": frozenset({"migrations/a:b.sql"})}
    # With a report the run, not the check, names the file (`warn_binary_skips`).
    assert "as binary" not in capsys.readouterr().err


def test_the_binary_warning_is_one_line_per_run(capsys):
    grep_mod.warn_binary_skips({"grant": ["migrations/002.sql"],
                                "grant2": ["migrations/002.sql"]})
    grep_mod.warn_binary_skips({})
    lines = [ln for ln in capsys.readouterr().err.splitlines() if "as binary" in ln]
    assert len(lines) == 1, lines
    assert "grep read 1 file(s) as binary" in lines[0], lines
    assert "(2 check(s))" in lines[0] and "migrations/002.sql" in lines[0], lines


def test_a_text_match_is_a_finding_not_a_skip(tmp_path):
    p = str(tmp_path / "migrations" / "a.sql")
    report, out = _grep_mocked(tmp_path, f"{p}\x001:GRANT x\n", "")
    assert [f[1] for f in out] == ["migrations/a.sql:1"]
    assert report.skipped_paths() == {}


def test_a_real_nul_file_is_recorded(tmp_path):
    """Whichever grep this host has: the file reaches the skip set."""
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "001.sql").write_text("GRANT x;\n")
    (tmp_path / "migrations" / "002.sql").write_bytes(b"GRANT y;\n\0bin\n")
    check = dict(_GREP_CHECK, paths=["migrations"])
    report = RunReport([check])
    out = grep_mod.run_check(check, str(tmp_path), report)
    assert [f[1] for f in out] == ["migrations/001.sql:1"]
    assert report.skipped_paths() == {"grant": frozenset({"migrations/002.sql"})}


# ── the baseline readers hold exactly the skipped files' entries ─────────────

_ID = baseline.identity_of("GRANT y;")
HELD = f"grant|migrations/002.sql:1|{_ID}"
STALE = f"grant|migrations/001.sql:9|{_ID}"
OTHER = f"other|migrations/002.sql:1|{_ID}"
SKIPS = {"grant": frozenset({"migrations/002.sql"})}


def test_unmatched_entries_holds_an_entry_in_a_skipped_file(tmp_path):
    entries = {HELD, STALE, OTHER}
    found = baseline.unmatched_entries(entries, [], {"grant", "other"},
                                       str(tmp_path), SKIPS)
    named = [e for e, _p in found]
    assert HELD not in named
    assert STALE in named
    # Per check: another check's entry at the same file is still judged.
    assert OTHER in named
    assert baseline.skip_held_entries(entries, [], {"grant", "other"}, SKIPS) == [HELD]


def test_without_a_skip_set_nothing_is_held(tmp_path):
    found = baseline.unmatched_entries({HELD}, [], {"grant"}, str(tmp_path))
    assert [e for e, _p in found] == [HELD]


def test_update_baseline_carries_a_held_entry_forward(tmp_path):
    path = tmp_path / ".claude" / "checks_baseline.txt"
    path.parent.mkdir()
    path.write_text(f"{HELD}\n{STALE}\n")
    live = ("grant", "migrations/001.sql:1", "msg", _ID)
    baseline.write_baseline(str(path), [live], {"grant"}, (), SKIPS)
    kept = baseline.load_baseline(str(path))
    assert HELD in kept, "the skipped file's verdict was deleted"
    assert STALE not in kept
    assert f"grant|migrations/001.sql:1|{_ID}" in kept


def test_migrate_baseline_holds_a_two_field_entry_in_a_skipped_file(tmp_path):
    path = tmp_path / "b.txt"
    path.write_text("grant|migrations/002.sql:1\ngrant|migrations/001.sql:9\n")
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "001.sql").write_text("x\n")
    (tmp_path / "migrations" / "002.sql").write_text("x\n")
    live = [("grant", "migrations/001.sql:1", "msg", _ID)]
    rows, refusal = baseline.migrate_baseline(str(path), live, str(tmp_path),
                                              (), (), SKIPS)
    assert refusal is None
    actions = {old: action for action, old, _new, _d in rows}
    assert actions["grant|migrations/002.sql:1"] == "kept-skipped", rows
    assert actions["grant|migrations/001.sql:9"] == "dropped-no-match", rows
    assert "grant|migrations/002.sql:1" in path.read_text()


# ── the run, end to end ──────────────────────────────────────────────────────

_YML = """\
checks:
  - id: grant
    severity: critical
    blocking: true
    paths: ["migrations/"]
    include: ["*.sql"]
    pattern: 'GRANT'
    description: "GRANT"
    used_by: [codebase-review, security-audit]
"""
NEW = "matched no finding this run — re-anchor or remove"
HELD_LINE = "not judged — the check did not read the anchor file this run"


def _cli_tree(tmp_path, *entries):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "checks.yml").write_text(_YML)
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "001.sql").write_text("GRANT y;\n")
    (tmp_path / "migrations" / "002.sql").write_bytes(b"GRANT y;\n\0bin\n")
    (tmp_path / ".claude" / "checks_baseline.txt").write_text(
        "# triaged\n" + "".join(e + "\n" for e in entries))


def _cli(tmp_path, monkeypatch, *extra):
    monkeypatch.setattr(sys, "argv", ["run_checks", "--repo-root", str(tmp_path),
                                      "--mode", "both", *extra])
    try:
        rci.main()
    except SystemExit as e:
        return e.code or 0
    return 0


def test_the_run_names_the_stale_entry_and_holds_the_skipped_one(
        tmp_path, monkeypatch, capsys):
    _cli_tree(tmp_path, HELD, STALE)
    _cli(tmp_path, monkeypatch)
    err = capsys.readouterr().err
    stale_block = err.split(NEW, 1)
    assert len(stale_block) == 2, err
    assert STALE in stale_block[1] and HELD not in stale_block[1], err
    held_line = [ln for ln in err.splitlines() if HELD_LINE in ln]
    assert held_line and HELD in held_line[0], err
    # The closing advice no longer blames a skip it now records.
    assert "drops a binary file" not in err and "over its size limit" not in err, err


def test_two_grep_checks_over_one_binary_file_warn_once(tmp_path, monkeypatch, capsys):
    """The ruling: one warning per run, not one per check that met the file."""
    _cli_tree(tmp_path, HELD)
    yml = tmp_path / ".claude" / "checks.yml"
    yml.write_text(_YML + _YML.split("checks:\n", 1)[1].replace("id: grant", "id: grant2"))
    _cli(tmp_path, monkeypatch)
    err = capsys.readouterr().err
    lines = [ln for ln in err.splitlines() if "as binary" in ln]
    assert len(lines) == 1, err
    assert "migrations/002.sql" in lines[0] and "(2 check(s))" in lines[0], err


def test_a_held_entry_alone_prints_only_its_line(tmp_path, monkeypatch, capsys):
    _cli_tree(tmp_path, HELD)
    _cli(tmp_path, monkeypatch)
    err = capsys.readouterr().err
    assert HELD_LINE in err and NEW not in err, err


def test_update_baseline_keeps_the_held_entry(tmp_path, monkeypatch, capsys):
    _cli_tree(tmp_path, HELD, STALE)
    assert _cli(tmp_path, monkeypatch, "--update-baseline") == 0
    kept = baseline.load_baseline(str(tmp_path / ".claude" / "checks_baseline.txt"))
    assert HELD in kept and STALE not in kept, kept
