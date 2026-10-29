"""`Q-581` (Phase 338): a scoped round's out-of-scope ingested findings come back.

`/security-audit` Step 3c buckets a claude-security report's findings by the round's
scope and promises the out-of-scope ones "surface next full round or when scope
widens". The mark that followed recorded the whole report, and a recorded report was
never read again, so on every scoped round those findings were lost in silence.

Wade chose shape (b) on 2026-09-27: a mark records what the round FOLDED. It names
the round's scope (`--scope-file`, or `--full`), a scoped mark records only the
in-scope findings, and the report is offered again carrying the rest.

The last test runs Step 3c's ingest and Step 7's mark exactly as the skill writes
them, in a throwaway tree, because a guard over the script alone cannot see a skill
that calls it wrongly.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import ingest_security_report as ing

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core" / "skills" / "security-audit" / "SKILL.md"
SCRIPT = REPO_ROOT / "core" / "companion" / "scripts" / "ingest_security_report.py"

IN = "app/in.py"
OUT = "other/out.py"
DIR = "CLAUDE-SECURITY-20260927-000000"


def _finding(file, title="SQL injection in the query builder", **kw):
    f = {"title": title, "file": file, "line": 42, "category": "sql-injection",
         "severity": "HIGH", "description": "User input reaches a raw SQL string."}
    f.update(kw)
    return f


def _report(root, findings, name=DIR, raw_lines=()):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(f) for f in findings] + list(raw_lines)
    (d / ing.RESULTS_JSONL).write_text("\n".join(lines) + "\n", encoding="utf-8")
    stamp = {"scan_root": str(root), "mode": "scan",
             "revision": {"versioned": False}, "verification": {"status": "verified"}}
    (d / "CLAUDE-SECURITY-REVISION-x.json").write_text(json.dumps(stamp), encoding="utf-8")
    return d


def _scope(root, *paths, name="scope.txt"):
    p = root / name
    p.write_text("".join(f"{x}\n" for x in paths), encoding="utf-8")
    return str(p)


def _digest(scope_file):
    try:
        return ing.scope_digest(ing._load_scope(scope_file))
    except ing.ScopeFileUnreadable:
        return "0" * 16


def _mark(root, *extra, dirs=(DIR,)):
    """A mark as Step 7 writes it: a scoped mark carries the digest of its scope file,
    unless the test passes one itself."""
    extra = list(extra)
    if "--scope-file" in extra and "--scope-digest" not in extra:
        extra += ["--scope-digest", _digest(extra[extra.index("--scope-file") + 1])]
    return ing.main(["--root", str(root), "--mark", *dirs, *extra, "--json"])


def _files(r, key="findings"):
    return sorted(f["file"] for f in r[key])


def _marker_text(root):
    p = root / ing.MARKER_REL
    return p.read_text(encoding="utf-8") if p.exists() else None


# --------------------------------------------------------------------------- #
# The defect: a scoped round's mark no longer hides the out-of-scope findings
# --------------------------------------------------------------------------- #
def test_a_scoped_mark_leaves_the_out_of_scope_finding_offered(tmp_path, capsys):
    _report(tmp_path, [_finding(IN), _finding(OUT)])
    scope = _scope(tmp_path, IN)
    r = ing.ingest(tmp_path, scope={IN}, include_ingested=False)
    assert (_files(r), _files(r, "out_of_scope")) == ([IN], [OUT])

    assert _mark(tmp_path, "--scope-file", scope) == 0
    assert json.loads(capsys.readouterr().out) == {"marked": [], "deferred": {DIR: 1}}

    # the same scope again: the folded finding is gone, the deferred one still counted
    again = ing.ingest(tmp_path, scope={IN}, include_ingested=False)
    assert (_files(again), _files(again, "out_of_scope")) == ([], [OUT])
    assert [(m["report"], m["previously_folded"]) for m in again["reports"]] == [(DIR, 1)]
    # the next full round files it, and only it
    assert _files(ing.ingest(tmp_path, scope=None, include_ingested=False)) == [OUT]


def test_a_widened_scope_folds_the_rest_and_then_the_report_goes_whole(tmp_path, capsys):
    _report(tmp_path, [_finding(IN), _finding(OUT)])
    assert _mark(tmp_path, "--scope-file", _scope(tmp_path, IN)) == 0
    wider = ing.ingest(tmp_path, scope={IN, OUT}, include_ingested=False)
    assert (_files(wider), _files(wider, "out_of_scope")) == ([OUT], [])
    capsys.readouterr()

    assert _mark(tmp_path, "--scope-file", _scope(tmp_path, OUT, name="s2.txt")) == 0
    assert json.loads(capsys.readouterr().out) == {"marked": [DIR], "deferred": {}}
    assert ing.read_marker(tmp_path) == {DIR}
    assert ing.ingest(tmp_path, scope=None, include_ingested=False)["counts"]["reports"] == 0


def test_a_full_mark_records_the_report_whole(tmp_path, capsys):
    _report(tmp_path, [_finding(IN), _finding(OUT)])
    assert _mark(tmp_path, "--full") == 0
    assert json.loads(capsys.readouterr().out) == {"marked": [DIR], "deferred": {}}
    assert ing.ingest(tmp_path, scope=None, include_ingested=False)["counts"]["reports"] == 0


def test_a_scoped_mark_whose_findings_were_all_in_scope_records_the_report_whole(tmp_path):
    _report(tmp_path, [_finding(IN), _finding(IN, title="another")])
    assert _mark(tmp_path, "--scope-file", _scope(tmp_path, IN)) == 0
    assert _marker_text(tmp_path) == DIR + "\n"


def test_a_finding_the_ingest_drops_does_not_hold_the_report_open(tmp_path):
    """A path escaping the repo is never emitted, so it can never be folded; the
    mark must not wait for it."""
    _report(tmp_path, [_finding(IN), _finding("../../outside.py")])
    assert _mark(tmp_path, "--scope-file", _scope(tmp_path, IN)) == 0
    assert ing.read_marker(tmp_path) == {DIR}


def test_a_repeated_scoped_mark_writes_no_duplicate_line(tmp_path):
    _report(tmp_path, [_finding(IN), _finding(OUT)])
    scope = _scope(tmp_path, IN)
    assert _mark(tmp_path, "--scope-file", scope) == 0
    first = _marker_text(tmp_path)
    assert _mark(tmp_path, "--scope-file", scope) == 0
    assert _marker_text(tmp_path) == first and first.count("\n") == 1


def test_a_scoped_mark_over_a_report_already_whole_reports_it_marked(tmp_path, capsys):
    _report(tmp_path, [_finding(IN), _finding(OUT)])
    assert _mark(tmp_path, "--full") == 0
    capsys.readouterr()
    assert _mark(tmp_path, "--scope-file", _scope(tmp_path, IN)) == 0
    assert json.loads(capsys.readouterr().out) == {"marked": [DIR], "deferred": {}}
    assert _marker_text(tmp_path) == DIR + "\n"


def test_a_lone_surrogate_in_a_title_is_keyed_and_folded(tmp_path):
    """`json.loads` makes a lone surrogate from a `\\ud800` escape; strict UTF-8
    cannot encode it, so an unguarded hash would crash the mark."""
    raw = '{"title": "x\\ud800y", "file": "%s", "line": 1, "category": "c", "severity": "LOW"}' % IN
    _report(tmp_path, [_finding(OUT)], raw_lines=[raw])
    assert _files(ing.ingest(tmp_path, scope={IN}, include_ingested=False)) == [IN]
    assert _mark(tmp_path, "--scope-file", _scope(tmp_path, IN)) == 0
    r = ing.ingest(tmp_path, scope={IN}, include_ingested=False)
    assert (_files(r), _files(r, "out_of_scope")) == ([], [OUT])


def test_a_title_carrying_a_tab_or_newline_writes_one_keyed_line(tmp_path):
    """The marker is line- and tab-delimited; a raw key written into it could forge
    a whole-report line. The key is hashed, so it cannot."""
    _report(tmp_path, [_finding(IN, title=f"a\t{DIR}\nb"), _finding(OUT)])
    assert _mark(tmp_path, "--scope-file", _scope(tmp_path, IN)) == 0
    [line] = _marker_text(tmp_path).splitlines()
    assert re.fullmatch(re.escape(DIR) + r"\t[0-9a-f]{64}", line), line
    assert ing.read_marker(tmp_path) == set()


def test_include_ingested_offers_folded_findings_again(tmp_path):
    _report(tmp_path, [_finding(IN), _finding(OUT)])
    assert _mark(tmp_path, "--scope-file", _scope(tmp_path, IN)) == 0
    assert _files(ing.ingest(tmp_path, scope=None, include_ingested=True)) == [IN, OUT]


def test_a_keyed_line_is_not_a_whole_report(tmp_path):
    marker = tmp_path / ing.MARKER_REL
    marker.parent.mkdir(parents=True)
    marker.write_text(f"CLAUDE-SECURITY-old\n{DIR}\t{'0' * 64}\n", encoding="utf-8")
    assert ing.read_marker(tmp_path) == {"CLAUDE-SECURITY-old"}
    assert ing.read_marker_state(tmp_path)[1] == {DIR: {"0" * 64}}


# --------------------------------------------------------------------------- #
# Refusals: nothing is recorded that the round did not fold
# --------------------------------------------------------------------------- #
def test_a_mark_that_declares_no_scope_is_refused(tmp_path, capsys):
    _report(tmp_path, [_finding(IN), _finding(OUT)])
    assert _mark(tmp_path) == 1
    cap = capsys.readouterr()
    assert "--scope-file" in cap.err and "--full" in cap.err and cap.out == "", cap
    assert _marker_text(tmp_path) is None


def test_a_mark_that_declares_both_is_refused(tmp_path, capsys):
    _report(tmp_path, [_finding(IN)])
    assert _mark(tmp_path, "--full", "--scope-file", _scope(tmp_path, IN)) == 1
    assert "contradict" in capsys.readouterr().err
    assert _marker_text(tmp_path) is None


@pytest.mark.parametrize("bad", ["CLAUDE-SECURITY-20260101-000000", "../" + DIR, "notes"])
def test_a_scoped_mark_naming_a_dir_it_cannot_read_records_nothing(tmp_path, capsys, bad):
    _report(tmp_path, [_finding(IN)])
    assert _mark(tmp_path, "--scope-file", _scope(tmp_path, IN), dirs=(DIR, bad)) == 1
    assert "not a report directory" in capsys.readouterr().err
    assert _marker_text(tmp_path) is None


def test_a_scoped_mark_over_a_report_that_no_longer_parses_records_nothing(tmp_path, capsys):
    d = _report(tmp_path, [_finding(IN)])
    (d / ing.RESULTS_JSONL).unlink()
    assert _mark(tmp_path, "--scope-file", _scope(tmp_path, IN)) == 1
    assert "cannot be read" in capsys.readouterr().err
    assert _marker_text(tmp_path) is None


def test_a_scoped_mark_whose_scope_file_is_unreadable_records_nothing(tmp_path, capsys):
    _report(tmp_path, [_finding(IN)])
    assert _mark(tmp_path, "--scope-file", str(tmp_path / "missing.txt")) == 1
    err = capsys.readouterr().err
    assert "Nothing was recorded" in err and "Refusing to ingest unscoped" not in err, err
    assert _marker_text(tmp_path) is None


@pytest.mark.parametrize("flag", ["--full", "--scope-file"])
def test_a_trailing_slash_names_the_report(tmp_path, capsys, flag):
    """Tab completion writes `CLAUDE-SECURITY-…/`. Recorded as typed, it is a name no
    report has, and the report is offered again every round."""
    _report(tmp_path, [_finding(IN)])
    extra = ("--full",) if flag == "--full" else ("--scope-file", _scope(tmp_path, IN))
    assert _mark(tmp_path, *extra, dirs=(DIR + "/",)) == 0
    assert ing.read_marker(tmp_path) == {DIR}


def test_the_text_output_names_what_was_left(tmp_path, capsys):
    _report(tmp_path, [_finding(IN), _finding(OUT)])
    scope = _scope(tmp_path, IN)
    assert ing.main(["--root", str(tmp_path), "--mark", DIR,
                     "--scope-file", scope, "--scope-digest", _digest(scope)]) == 0
    assert capsys.readouterr().out.strip() == (
        "claude-security mark: 0 report(s) folded whole; 1 finding(s) in 1 report(s) "
        "left for a round whose scope reaches them")


# --------------------------------------------------------------------------- #
# Round 1's findings
# --------------------------------------------------------------------------- #
def test_a_scope_file_rewritten_since_the_ingest_refuses_the_mark(tmp_path, capsys):
    """Lens 1 MED: a concurrent round rewrote the fixed-name scope file between Step 3c
    and Step 7, and the mark recorded the other round's scope as folded; a finding this
    round never filed was then hidden for good."""
    _report(tmp_path, [_finding(IN), _finding(OUT)])
    scope = _scope(tmp_path, IN)
    printed = ing.ingest(tmp_path, scope={IN}, include_ingested=False)["scope_digest"]
    _scope(tmp_path, OUT)                     # the other round writes the same file
    assert _mark(tmp_path, "--scope-file", scope, "--scope-digest", printed) == 1
    assert "no longer matches" in capsys.readouterr().err
    assert _marker_text(tmp_path) is None
    assert _files(ing.ingest(tmp_path, scope=None, include_ingested=False)) == [IN, OUT]


def test_the_ingest_prints_the_digest_its_mark_needs(tmp_path, capsys):
    _report(tmp_path, [_finding(IN)])
    scope = _scope(tmp_path, IN)
    assert ing.main(["--root", str(tmp_path), "--scope-file", scope, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["scope_digest"] == _digest(scope)
    assert ing.main(["--root", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["scope_digest"] is None
    assert ing.main(["--root", str(tmp_path / "nope"), "--scope-file", scope, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["scope_digest"] == _digest(scope)


@pytest.mark.parametrize("argv,needle", [
    (["--mark", DIR, "--scope-file", "S"], "needs --scope-digest"),
    (["--mark", DIR, "--full", "--scope-digest", "x"], "goes only with"),
    (["--scope-file", "S", "--scope-digest", "x", "--json"], "goes only with"),
])
def test_the_digest_is_required_with_a_scoped_mark_and_only_there(tmp_path, capsys, argv, needle):
    _report(tmp_path, [_finding(IN), _finding(OUT)])
    argv = [a if a != "S" else _scope(tmp_path, IN) for a in argv]
    assert ing.main(["--root", str(tmp_path), *argv]) == 1
    assert needle in capsys.readouterr().err
    assert _marker_text(tmp_path) is None


def test_an_empty_scope_file_argument_is_no_scope_declaration(tmp_path, capsys):
    """Lens 2 k8: an empty variable expanding into `--scope-file ""` must not read as
    a declared scope and fall through to a whole-report mark."""
    _report(tmp_path, [_finding(IN), _finding(OUT)])
    assert ing.main(["--root", str(tmp_path), "--mark", DIR, "--scope-file", "", "--json"]) == 1
    assert _marker_text(tmp_path) is None


@pytest.mark.parametrize("name", ["CLAUDE-SECURITY-20260101-000000", "CLAUDE-SECURITY-9x", "notes"])
def test_a_full_mark_naming_no_report_records_nothing(tmp_path, capsys, name):
    """Lens 1 LOW-4: `--full` wrote any name and reported it marked."""
    _report(tmp_path, [_finding(IN)])
    assert _mark(tmp_path, "--full", dirs=(DIR, name)) == 1
    assert "not a report directory" in capsys.readouterr().err
    assert _marker_text(tmp_path) is None


def test_a_report_with_no_finding_goes_whole_on_a_scoped_mark(tmp_path):
    """Lens 2 k2: otherwise it is offered, and its trust block printed, forever."""
    _report(tmp_path, [])
    assert _mark(tmp_path, "--scope-file", _scope(tmp_path, IN)) == 0
    assert ing.read_marker(tmp_path) == {DIR}


def test_folded_keys_apply_to_their_own_report_only(tmp_path):
    """Lens 2 k5: the same finding in a fresh report is offered, so Step 4's closed-task
    check sees it."""
    _report(tmp_path, [_finding(IN), _finding(OUT)])
    assert _mark(tmp_path, "--scope-file", _scope(tmp_path, IN)) == 0
    _report(tmp_path, [_finding(IN)], name="CLAUDE-SECURITY-20260928-000000")
    r = ing.ingest(tmp_path, scope={IN}, include_ingested=False)
    assert [f["source_reports"] for f in r["findings"]] == [["CLAUDE-SECURITY-20260928-000000"]]


def test_previously_folded_counts_every_folded_finding(tmp_path):
    """Lens 2 k6."""
    _report(tmp_path, [_finding(IN), _finding(IN, title="t2"), _finding(OUT)])
    assert _mark(tmp_path, "--scope-file", _scope(tmp_path, IN)) == 0
    r = ing.ingest(tmp_path, scope={IN}, include_ingested=False)
    assert [(m["previously_folded"], m["finding_count"]) for m in r["reports"]] == [(2, 1)]


def test_a_keyed_mark_that_does_not_read_back_is_refused(tmp_path, capsys, monkeypatch):
    """Lens 2 k7: the read-back check, on keyed lines."""
    _report(tmp_path, [_finding(IN), _finding(OUT)])
    scope = _scope(tmp_path, IN)
    real = ing._marker_entries
    calls = {"n": 0}

    def drop_new_lines(p):
        calls["n"] += 1
        have, why = real(p)
        return (set(), "") if calls["n"] == 3 else (have, why)   # the read after the append
    monkeypatch.setattr(ing, "_marker_entries", drop_new_lines)
    assert _mark(tmp_path, "--scope-file", scope) == 1
    assert "does not read back" in capsys.readouterr().err


@pytest.mark.parametrize("cp", ["d800", "dbff", "dc00", "dfff"])
def test_a_lone_surrogate_does_not_crash_the_json_ingest(tmp_path, cp):
    """Lens 1 MED-2: `print(json.dumps(..., ensure_ascii=False))` raised
    UnicodeEncodeError, so the whole ingest exited 1 every round. Round 2: both
    halves of the surrogate range, not only U+D800."""
    raw = '{"title": "x\\u%s y", "file": "%s", "line": 1, "category": "c", "severity": "LOW"}' % (cp, IN)
    _report(tmp_path, [_finding(OUT)], raw_lines=[raw])
    p = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path), "--json"],
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    titles = sorted(f["title"] for f in json.loads(p.stdout)["findings"])
    assert titles == ["SQL injection in the query builder", "x" + chr(int(cp, 16)) + " y"]


def test_an_infinite_line_is_ingested_at_line_0(tmp_path):
    """Lens 1: `int(inf)` raised OverflowError past `identity`, and the finding vanished."""
    _report(tmp_path, [], raw_lines=['{"title": "t", "file": "%s", "line": 1e999, '
                                     '"category": "c", "severity": "LOW"}' % IN])
    [f] = ing.ingest(tmp_path, scope=None, include_ingested=False)["findings"]
    assert f["line"] == 0


def test_a_finding_the_ingest_cannot_place_is_said(tmp_path):
    """Lens 1: a report scanned from another checkout dropped every finding in silence."""
    _report(tmp_path, [_finding(IN), _finding("../../outside.py")])
    r = ing.ingest(tmp_path, scope=None, include_ingested=False)
    assert [m["dropped"] for m in r["reports"]] == [1]
    assert any("1 finding(s) not ingested" in c for c in r["trust"]["caveats"]), r["trust"]


# --------------------------------------------------------------------------- #
# Round 2's findings
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("argv", [["--ma", DIR, "--fu"], ["--mar", DIR, "--full"], ["--mark", DIR, "--fu"]])
def test_an_abbreviated_option_is_refused(tmp_path, argv):
    """Round 2, both lenses: argparse's prefix matching ran `--ma D --fu` as a whole-report
    mark, a spelling the guards do not look for."""
    _report(tmp_path, [_finding(IN), _finding(OUT)])
    p = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path), *argv],
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 2, (p.returncode, p.stderr)
    assert _marker_text(tmp_path) is None


def test_a_full_mark_naming_a_directory_that_is_not_a_report_records_nothing(tmp_path, capsys):
    """Round 2, lens 2 k12: every refusal case also failed `is_dir`."""
    _report(tmp_path, [_finding(IN)])
    (tmp_path / "sysop").mkdir()
    assert _mark(tmp_path, "--full", dirs=("sysop",)) == 1
    assert _marker_text(tmp_path) is None


def test_the_digest_is_stable_across_processes(tmp_path):
    """Round 2, lens 2: a digest over the unsorted set passed every in-process test and
    differed per process (PYTHONHASHSEED), refusing every multi-path mark as stale."""
    paths = ["app/a.py", "app/b.py", "lib/c.py", "lib/d.py", IN]
    _report(tmp_path, [_finding(q) for q in paths] + [_finding(OUT)])
    scope = _scope(tmp_path, *paths)
    for seed_in, seed_mark in (("1", "2"), ("3", "4"), ("5", "6")):
        env = dict(os.environ, PYTHONHASHSEED=seed_in)
        p = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path), "--scope-file", scope,
                            "--json"], capture_output=True, text=True, encoding="utf-8", env=env)
        digest = json.loads(p.stdout)["scope_digest"]
        assert re.fullmatch(r"[0-9a-f]{16}", digest), digest
        env["PYTHONHASHSEED"] = seed_mark
        m = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path), "--mark", DIR,
                            "--scope-file", scope, "--scope-digest", digest, "--json"],
                           capture_output=True, text=True, encoding="utf-8", env=env)
        assert m.returncode == 0, (seed_in, seed_mark, m.stderr)


@pytest.mark.parametrize("edit", [lambda d: d[:15], lambda d: d + "0", lambda d: d[:1], str.upper])
def test_only_the_exact_digest_is_accepted(tmp_path, capsys, edit):
    """Round 2, lens 2 k2/k3: a truncated or prefix compare would accept a rewritten scope."""
    _report(tmp_path, [_finding(IN), _finding(OUT)])
    scope = _scope(tmp_path, IN)
    assert _mark(tmp_path, "--scope-file", scope, "--scope-digest", edit(_digest(scope))) == 1
    assert _marker_text(tmp_path) is None


def test_every_dropped_finding_is_counted(tmp_path):
    """Round 2, lens 2 k7/k13."""
    _report(tmp_path, [_finding(IN), _finding("../../a.py"), _finding("../../b.py")],
            raw_lines=["not json", "[1, 2]", '{"title": "no file"}'])
    r = ing.ingest(tmp_path, scope=None, include_ingested=False)
    assert [m["dropped"] for m in r["reports"]] == [2]
    caveats = " | ".join(r["trust"]["caveats"])
    assert "2 finding(s) not ingested" in caveats, caveats
    assert "3 line(s) of CLAUDE-SECURITY-RESULTS.jsonl were not a readable finding" in caveats, caveats


# --------------------------------------------------------------------------- #
# The skill's own commands, run as written
# --------------------------------------------------------------------------- #
def _step(start, end):
    text = SKILL.read_text(encoding="utf-8")
    return text[text.index(start): text.index(end)]


REFERENCE = SKILL.parent / "REFERENCE.md"
# A fence opens on three or more backticks or tildes, with any info string, and closes on
# the same run (round 2, lens 2: `~~~` and `sh` fences were invisible to the first cut).
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})[^\n]*\n(.*?)^[ \t]{0,3}\1[ \t]*$", re.M | re.S)


def _logical_lines(text):
    """Lines with a trailing-backslash continuation joined as bash joins them: the
    backslash and the newline go, nothing is inserted."""
    out, buf = [], ""
    for ln in text.splitlines():
        if ln.endswith("\\"):
            buf += ln[:-1]
            continue
        out.append(buf + ln)
        buf = ""
    if buf:
        out.append(buf)
    return out


def _fenced(text):
    return "\n".join(m.group(2) for m in _FENCE.finditer(text))


def _commands(block):
    """The command lines of every fence in `block`, continuations joined, comments dropped."""
    out = []
    for ln in _logical_lines(_fenced(block)):
        ln = re.split(r"\s#", ln)[0].strip()
        if ln and not ln.startswith("#"):
            out.append(ln)
    return out


def _declares_one_scope(cmd):
    cmd = re.split(r"\s#", cmd)[0]                         # a comment declares nothing
    scoped = re.search(r"--scope-file(?![\w-])", cmd) is not None
    full = re.search(r"--full(?![\w-])", cmd) is not None
    return scoped != full and (not scoped or re.search(r"--scope-digest(?![\w-])", cmd) is not None)


def test_the_mark_is_only_in_step_7_after_its_commit():
    """Round 1 (lens 2): a mark written in Step 3c, fenced or inline, with `--full`,
    passed every guard: that is the defect run before the commit. Any `--mark` in
    the runner must sit in Step 7 below its commit COMMAND (round 2: the first cut
    anchored on the first `git commit` string, which prose above the command can
    carry). The script refuses abbreviations, so `--ma` is not a mark."""
    text = SKILL.read_text(encoding="utf-8")
    step7 = text.index("## Step 7:")
    step8 = text.index("## Step 8:")
    [commit] = [m.start() for m in re.finditer(r"^git commit -m ", text[step7:step8], re.M)]
    commit += step7
    hits = [m.start() for m in re.finditer(r"--mark\b", text)]
    assert hits, "the population is empty"
    stray = [text[max(0, h - 80):h + 40] for h in hits if not commit < h < step8]
    assert not stray, stray


def test_every_mark_command_in_the_runner_declares_one_scope():
    """A fenced `--mark`, however the line is continued, carries `--full`, or
    `--scope-file` with `--scope-digest`, and never both."""
    cmds = [c for c in _commands(SKILL.read_text(encoding="utf-8")) if "--mark" in c]
    assert len(cmds) == 2, cmds
    for c in cmds:
        assert _declares_one_scope(c), c


def test_the_reference_carries_no_runnable_mark():
    """REFERENCE.md is rationale; a command there is one a reader may copy."""
    assert not [c for c in _commands(REFERENCE.read_text(encoding="utf-8")) if "--mark" in c]


@pytest.mark.parametrize("cmd,ok", [
    ("x --mark D --full", True),
    ("x --mark D --scope-file F --scope-digest G", True),
    ("x --mark D --scope-file F", False),
    ("x --mark D", False),
    ("x --mark D --full --scope-file F --scope-digest G", False),
    ("x --mark D --fullish", False),
    ("x --mark D --full-x", False),
    ("x --mark D --scope-file F # --scope-digest G", False),
    ("x --mark D # --full", False),
])
def test_the_scope_predicate(cmd, ok):
    assert _declares_one_scope(cmd) is ok


def test_continuation_lines_are_joined_as_bash_joins_them():
    assert _logical_lines("a \\\n  --mark D \\\n  --full\nb") == ["a   --mark D   --full", "b"]
    assert _logical_lines("--mar\\\nk") == ["--mark"]


@pytest.mark.parametrize("opener", ["```bash", "```sh", "~~~", "````", "~~~ bash"])
def test_every_fence_form_is_read(opener):
    closer = re.match(r"[`~]+", opener).group()
    assert _commands(f"x\n{opener}\npython3 s.py --mark D\n{closer}\ny\n") == ["python3 s.py --mark D"]


def _run(cwd, cmd, digest=None):
    cmd = cmd.replace("<report-dir-name> [<report-dir-name> ...]", DIR)
    if digest is not None:
        cmd = cmd.replace("<scope_digest>", digest)
    argv = shlex.split(cmd)
    assert argv[0] == "python3", cmd
    return subprocess.run([sys.executable, *argv[1:]], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8")


def test_the_skill_commands_as_written_keep_the_deferred_finding(tmp_path):
    step3c = _commands(_step("## Step 3c:", "## Step 4:"))
    step7 = _commands(_step("## Step 7:", "## Step 8:"))
    [full_ingest] = [c for c in step3c if "ingest_security_report" in c and "--scope-file" not in c]
    [scoped_ingest] = [c for c in step3c if "ingest_security_report" in c and "--scope-file" in c]
    [scoped_mark] = [c for c in step7 if "--mark" in c and "--scope-file" in c]
    [full_mark] = [c for c in step7 if "--mark" in c and "--full" in c]
    assert not [c for c in step3c if "--mark" in c], "the mark belongs to Step 7, after the commit"

    (tmp_path / "sysop" / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, tmp_path / "sysop" / "scripts" / SCRIPT.name)
    (tmp_path / "sysop" / "runtime").mkdir()
    (tmp_path / "sysop" / "runtime" / "audit-scope.txt").write_text(IN + "\n", encoding="utf-8")
    _report(tmp_path, [_finding(IN), _finding(OUT)])

    def ingest(cmd):
        p = _run(tmp_path, cmd)
        assert p.returncode == 0, (cmd, p.stderr)
        return json.loads(p.stdout)

    r = ingest(scoped_ingest)
    assert (_files(r), _files(r, "out_of_scope")) == ([IN], [OUT])
    assert "<scope_digest>" in scoped_mark, scoped_mark
    p = _run(tmp_path, scoped_mark, digest=r["scope_digest"])
    assert p.returncode == 0, (scoped_mark, p.stderr)
    r = ingest(scoped_ingest)
    assert (_files(r), _files(r, "out_of_scope")) == ([], [OUT]), "the deferred finding was lost"
    assert _files(ingest(full_ingest)) == [OUT]
    p = _run(tmp_path, full_mark)
    assert p.returncode == 0, (full_mark, p.stderr)
    assert ingest(full_ingest)["counts"]["reports"] == 0
