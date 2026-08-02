"""Phase 172 — the inline `no-check:` waiver for grep-stage findings.

WHY IT EXISTS
-------------
Upstream #235's secondary ask. Before this, the only way to suppress a grep finding was
`.claude/checks_baseline.txt`, which is `file:line`-keyed and rots the moment a line
moves. That made *widening* a check — the primary half of #235, and any future `paths:`
broadening over a directory holding reviewed exceptions — convert a hardening into
permanent CI noise, so the hardening does not get made. `# no-check: <id>` is the
grep-stage counterpart to `# nosemgrep` / `# pragma: no cover`, and it composes with the
baseline rather than replacing it: baseline = historical debt, inline = a reviewed,
intentional exception that travels with the line.

THE TWO DESIGN CALLS THIS FILE PINS
-----------------------------------
1. **A bare `no-check:` waives nothing.** A blanket marker would silently disable checks
   that do not exist yet, including a future `severity: critical` one.
2. **A waiver is never silent.** Waived findings are reprinted with a `[waived]` tag and
   counted in the accounting header — the same contract `[baseline]` already has. A
   suppression that left no output would let a consumer disable a critical check with a
   comment and leave nothing behind that says so.

Scope: the grep stage only. semgrep has `# nosemgrep`, coverage has `# pragma: no
cover`, and the typecheckers have their own pragmas.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import run_checks_impl as rci
from run_checks.accounting import RunReport
from run_checks.grep import run_check, waived_ids


def _check(**over) -> dict:
    base = {
        "id": "sql-fstring",
        "severity": "critical",
        "paths": ["src/"],
        "include": ["*.py"],
        "pattern": "f['\"](SELECT|INSERT|UPDATE|DELETE|ALTER|DROP)",
        "description": "f-string SQL detected",
        "used_by": ["codebase-review"],
    }
    base.update(over)
    return base


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    return tmp_path


def _write(repo: Path, name: str, body: str) -> None:
    (repo / "src" / name).write_text(body)


def _lines(findings) -> set[str]:
    return {file_line for _, file_line, _ in findings}


# ═══════════════════════════════════════════════════════════════════════════════
# waived_ids — the marker parser
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "text,expected",
    [
        ("q = f'SELECT 1'  # no-check: sql-fstring", {"sql-fstring"}),
        ("q = f'SELECT 1'  // no-check: sql-fstring", {"sql-fstring"}),
        ("-- no-check: sql-fstring", {"sql-fstring"}),
        ("# no-check: sql-fstring, raw-row-number", {"sql-fstring", "raw-row-number"}),
        ("# no-check: sql-fstring,raw-row-number", {"sql-fstring", "raw-row-number"}),
        # A trailing rationale is encouraged and must not be parsed as an id.
        ("# no-check: sql-fstring — table name validated upstream", {"sql-fstring"}),
        ("# no-check: sql-fstring (see ADR-4)", {"sql-fstring"}),
        # Design call 1: a bare marker waives nothing.
        ("q = f'SELECT 1'  # no-check:", set()),
        ("q = f'SELECT 1'  # no-check", set()),
        # …INCLUDING when the text is a whole file. `\s*` matches newlines, and
        # a file-level check hands `waived_ids` the entire file, so the first
        # version swallowed the next identifier-shaped token further down and
        # waived whatever it spelled. Found by the round; the marker is now
        # matched per line with horizontal whitespace only.
        ("# no-check:\nimport os", set()),
        ("# no-check:\n\n  raw-row-number", set()),
        ("# no-check: sql-fstring,\nraw-row-number", {"sql-fstring"}),
        # A real marker still works when it is one line of many.
        ("import os\n# no-check: sql-fstring\nx = 1\n", {"sql-fstring"}),
        # Two markers on different lines both count.
        ("# no-check: sql-fstring\n# no-check: raw-row-number\n",
         {"sql-fstring", "raw-row-number"}),
        # Left-anchored: a token that merely ENDS in `no-check:` is not a marker.
        ("xno-check: sql-fstring", set()),
        ("q = 1  # nono-check: sql-fstring", set()),
        # Near-miss SPELLINGS must not waive. Widening the marker is the dangerous
        # direction — it silently disables checks — and five mutations that widened
        # it (`no-?check:`, ids as `[^\s,]+`, case-folding) survived a suite whose
        # every case was positive-and-exact.
        ("q = 1  # nocheck: sql-fstring", set()),
        ("q = 1  # no_check: sql-fstring", set()),
        ("q = 1  # no check: sql-fstring", set()),
        ("q = 1  # no--check: sql-fstring", set()),
        ("q = 1  # no-check sql-fstring", set()),
        # The id charset stops at the first character outside [A-Za-z0-9_-]; a
        # dotted id is therefore truncated, which is why the doc says to keep ids
        # in the shipped shape rather than widening the class (widening would eat
        # the rationale that follows a full stop).
        ("q = 1  # no-check: foo.bar", {"foo"}),
        ("q = 1  # no-check: a/b", {"a"}),
        # Case-sensitive, like `# nosemgrep` / `# noqa` / `# type: ignore`.
        ("q = f'SELECT 1'  # NO-CHECK: sql-fstring", set()),
        ("q = f'SELECT 1'  # No-Check: sql-fstring", set()),
        # Horizontal whitespace means SPACE and TAB, not `\s`. These pin the
        # distinction, and they are why the `[ \t]` -> `\s` mutation is a real
        # graded mutation rather than an equivalent one: `\s` accepts all three.
        ("q = 1  # no-check: sql-fstring", set()),   # non-breaking space
        ("q = 1  # no-check:\vsql-fstring", set()),       # vertical tab
        ("q = 1  # no-check:\fsql-fstring", set()),       # form feed
        ("q = 1  # no-check:\tsql-fstring", {"sql-fstring"}),
        ("q = 1  # no-check:sql-fstring", {"sql-fstring"}),
        # No marker at all.
        ("q = f'SELECT 1'", set()),
        ("", set()),
    ],
)
def test_waived_ids_parses(text, expected):
    assert waived_ids(text) == expected


def test_bare_marker_in_a_file_level_check_waives_nothing(repo):
    """The HIGH the round found: file-level waiver text is the WHOLE file."""
    check = _check(id="missing-mock-cleanup", pattern="vi\\.(mock|spyOn)\\(",
                   negative_pattern="restoreAllMocks", invert_file_check=True)
    _write(repo, "a.py", "# no-check:\nmissing-mock-cleanup is discussed below\nvi.mock('x')\n")
    findings = run_check(check, str(repo))
    assert _lines(findings) == {"src/a.py"}


def test_waived_ids_tolerates_none():
    assert waived_ids(None) == set()


def test_shipped_tree_carries_only_the_known_live_markers():
    """A file that SHOWS a marker carries a live one — so the set is pinned.

    The marker is literal text with no "this is only an example" state, and a
    file-level (`invert_file_check`) check is handed the WHOLE file, so a doc
    example can disarm one. Today neither reachable file-level check includes
    `*.md` or `*.py` (both are `*.ts`/`*.tsx`), so this is latent, not live —
    which is exactly why it wants a guard rather than a fix: the day someone
    adds a file-level check over docs or Python, this test is the thing that
    says a `WORKFLOW.md` example is now load-bearing.
    """
    import subprocess

    from tests import shape_lib as S

    tracked = subprocess.run(
        ["git", "ls-files", "core/", "packs/"],
        cwd=S.REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    found = {}
    for rel in tracked:
        path = S.REPO_ROOT / rel
        try:
            ids = waived_ids(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if ids:
            found[rel] = sorted(ids)
    assert found == {
        # Deliberate: § 6.5 teaches the marker, and a doc example wants real ids.
        "core/companion/docs/WORKFLOW.md": ["raw-row-number", "sql-fstring"],
    }, found


# ═══════════════════════════════════════════════════════════════════════════════
# Every finding-emission branch honours the marker
# ═══════════════════════════════════════════════════════════════════════════════


def test_simple_branch_waives_only_the_marked_line(repo):
    _write(repo, "a.py", (
        "one = f'SELECT 1'\n"
        "two = f'SELECT 2'  # no-check: sql-fstring\n"
        "three = f'SELECT 3'\n"
    ))
    report = RunReport([_check()])
    findings = run_check(_check(), str(repo), report)
    assert _lines(findings) == {"src/a.py:1", "src/a.py:3"}
    assert [fl for _, fl, _ in report.waived()] == ["src/a.py:2"]


@pytest.mark.parametrize(
    "marker",
    [
        "raw-row-number",       # lexically unrelated
        "sql-fstring-legacy",   # the waived id is a PREFIX of this one
        "legacy-sql-fstring",   # …and a SUFFIX of this one
        "sql_fstring",          # underscore vs hyphen
        "SQL-FSTRING",          # case
        "sql-fstrin",           # the marker is a prefix of the check id
    ],
)
def test_marker_for_a_different_check_does_not_suppress(repo, marker):
    """The id is load-bearing, and it must match EXACTLY.

    The first version paired `sql-fstring` against `raw-row-number` only — lexically
    unrelated, so it excluded a total mismatch and nothing else. Substring, prefix
    and case-insensitive id matching all survived it.
    """
    _write(repo, "a.py", f"one = f'SELECT 1'  # no-check: {marker}\n")
    findings = run_check(_check(), str(repo))
    assert _lines(findings) == {"src/a.py:1"}, marker


def test_negative_pattern_branch_honours_the_marker(repo):
    check = _check(id="wrong-engine", pattern="(admin_engine|writer_engine)",
                   negative_pattern="(import|#no)")
    _write(repo, "a.py", (
        "x = admin_engine.connect()\n"
        "y = writer_engine.connect()  # no-check: wrong-engine\n"
    ))
    report = RunReport([check])
    findings = run_check(check, str(repo), report)
    assert _lines(findings) == {"src/a.py:1"}
    assert [fl for _, fl, _ in report.waived()] == ["src/a.py:2"]


def test_invert_file_check_branch_honours_a_file_level_marker(repo):
    """A file-level finding cites no line, so the marker may sit anywhere in the file."""
    check = _check(id="missing-mock-cleanup", pattern="vi\\.(mock|spyOn)\\(",
                   negative_pattern="restoreAllMocks", invert_file_check=True)
    _write(repo, "a.py", "vi.mock('x')\n")
    _write(repo, "b.py", "# no-check: missing-mock-cleanup — teardown is global\nvi.mock('y')\n")
    report = RunReport([check])
    findings = run_check(check, str(repo), report)
    assert _lines(findings) == {"src/a.py"}
    assert [fl for _, fl, _ in report.waived()] == ["src/b.py"]


def test_position_check_branch_honours_a_marker_on_the_reported_line(repo):
    check = _check(
        id="test-app-env-before-syspath",
        position_check={"earlier": "os\\.environ\\.setdefault\\(['\"]APP_ENV['\"]",
                        "later": "sys\\.path\\.insert\\("},
    )
    check.pop("pattern")
    _write(repo, "a.py", "import sys\nsys.path.insert(0, '.')\nos.environ.setdefault('APP_ENV', 't')\n")
    _write(repo, "b.py", (
        "import sys\n"
        "sys.path.insert(0, '.')  # no-check: test-app-env-before-syspath\n"
        "os.environ.setdefault('APP_ENV', 't')\n"
    ))
    report = RunReport([check])
    findings = run_check(check, str(repo), report)
    assert _lines(findings) == {"src/a.py:2"}
    assert [fl for _, fl, _ in report.waived()] == ["src/b.py:2"]


def test_position_check_marker_on_an_UNCITED_line_does_not_waive(repo):
    """Line-scope, not file-scope — the property the first version never tested.

    Every fixture put the marker on the cited line AND NOWHERE ELSE, so nothing
    distinguished `waived_ids(lines[l_line-1])` from `waived_ids(whole_file)`. Four
    mutations walked through that, and whole-file scope IS the blanket marker the
    design rejects.
    """
    check = _check(
        id="test-app-env-before-syspath",
        position_check={"earlier": "os\\.environ\\.setdefault\\(['\"]APP_ENV['\"]",
                        "later": "sys\\.path\\.insert\\("},
    )
    check.pop("pattern")
    _write(repo, "a.py", (
        "# no-check: test-app-env-before-syspath\n"     # line 1 — NOT the cited line
        "sys.path.insert(0, '.')\n"                     # line 2 — the cited line
        "os.environ.setdefault('APP_ENV', 't')\n"
    ))
    assert _lines(run_check(check, str(repo))) == {"src/a.py:2"}


def test_line_level_marker_on_an_UNCITED_line_does_not_waive(repo):
    """The same property on the simple and negative_pattern branches."""
    _write(repo, "a.py", "# no-check: sql-fstring\none = f'SELECT 1'\n")
    assert _lines(run_check(_check(), str(repo))) == {"src/a.py:2"}

    check = _check(id="wrong-engine", pattern="(admin_engine|writer_engine)",
                   negative_pattern="restoreAllMocks")
    _write(repo, "b.py", "# no-check: wrong-engine\nx = admin_engine.connect()\n")
    assert _lines(run_check(check, str(repo))) == {"src/b.py:2"}


def test_waiver_applies_without_a_report(repo):
    """Suppression must not depend on the accounting arg — only the audit line does."""
    _write(repo, "a.py", "one = f'SELECT 1'  # no-check: sql-fstring\n")
    assert run_check(_check(), str(repo)) == []


def test_bare_marker_does_not_suppress_end_to_end(repo):
    _write(repo, "a.py", "one = f'SELECT 1'  # no-check:\n")
    assert _lines(run_check(_check(), str(repo))) == {"src/a.py:1"}


def test_waiving_does_not_change_the_checks_terminal_state(repo):
    """A fully-waived check still EXECUTED — waiving is per finding, not per check."""
    _write(repo, "a.py", "one = f'SELECT 1'  # no-check: sql-fstring\n")
    report = RunReport([_check()])
    run_check(_check(), str(repo), report)
    assert report.status_of("sql-fstring") == "executed"


# ═══════════════════════════════════════════════════════════════════════════════
# Loudness: the waiver reaches the summary and the output
# ═══════════════════════════════════════════════════════════════════════════════


def test_render_header_carries_the_waived_count():
    report = RunReport([{"id": "c1"}])
    report.record(["c1"], "executed", "grep")
    report.record_waived("c1", "a.py:1", "[c1] CRITICAL a.py:1 — x")
    assert "waived: 1" in report.render([], mode="both").splitlines()[0]


def test_render_header_reports_zero_when_nothing_is_waived():
    report = RunReport([{"id": "c1"}])
    report.record(["c1"], "executed", "grep")
    assert "waived: 0" in report.render([], mode="both").splitlines()[0]


def test_waived_records_are_complete_ordered_and_not_deduplicated():
    """N>=2, the range the first version never reached.

    Everything below survived a suite that only ever saw 0 or 1 waiver: capping
    `_waived` at one entry, keeping only the most recent, de-duplicating, counting
    distinct check-ids instead of findings, and reversing `waived()`.
    """
    report = RunReport([{"id": "c1"}, {"id": "c2"}])
    report.record_waived("c1", "a.py:1", "[c1] HIGH a.py:1 — x")
    report.record_waived("c1", "a.py:9", "[c1] HIGH a.py:9 — x")
    report.record_waived("c2", "b.py:3", "[c2] LOW b.py:3 — y")
    report.record_waived("c1", "a.py:1", "[c1] HIGH a.py:1 — x")   # a genuine repeat
    assert [fl for _, fl, _ in report.waived()] == [
        "a.py:1", "a.py:9", "b.py:3", "a.py:1",
    ], "emission order and multiplicity are both part of the contract"
    assert "waived: 4" in report.render([], mode="both").splitlines()[0]


def test_waived_returns_a_copy_so_a_caller_cannot_mutate_the_record():
    report = RunReport([{"id": "c1"}])
    report.record_waived("c1", "a.py:1", "m")
    report.waived().clear()
    assert len(report.waived()) == 1


def test_recorded_waiver_carries_the_check_id_and_the_message():
    """Two of the tuple's three fields were dead — nothing read them."""
    report = RunReport([{"id": "sql-fstring"}])
    check = _check()
    repo_findings = report.waived()
    assert repo_findings == []
    report.record_waived("sql-fstring", "a.py:1", "[sql-fstring] CRITICAL a.py:1 — d")
    (cid, file_line, message), = report.waived()
    assert cid == "sql-fstring"
    assert file_line == "a.py:1"
    assert message == "[sql-fstring] CRITICAL a.py:1 — d"
    assert check["id"] == cid


def test_emitted_waiver_message_matches_the_finding_format(repo):
    """The message is what `[waived]` prints — assert it end to end, not by shape."""
    _write(repo, "a.py", "one = f'SELECT 1'  # no-check: sql-fstring\n")
    report = RunReport([_check()])
    run_check(_check(), str(repo), report)
    assert [m for _, _, m in report.waived()] == [
        "[sql-fstring] CRITICAL src/a.py:1 — f-string SQL detected"
    ]
    assert [c for c, _, _ in report.waived()] == ["sql-fstring"]


def test_position_check_waiver_records_the_same_id_and_message_shape(repo):
    """`_run_position_check` builds its OWN message — assert that one too.

    `_emit` and `_run_position_check` each construct `[id] SEV file:line — desc`,
    and the position-check copy is the FIRST occurrence in the file. Two mutations
    aimed at `_emit` silently retargeted onto it and survived, which is the
    first-occurrence trap Phase 170's round recorded, one phase later.
    """
    check = _check(
        id="test-app-env-before-syspath", severity="medium",
        description="sys.path.insert() runs first",
        position_check={"earlier": "os\\.environ\\.setdefault\\(['\"]APP_ENV['\"]",
                        "later": "sys\\.path\\.insert\\("},
    )
    check.pop("pattern")
    _write(repo, "a.py", (
        "import sys\n"
        "sys.path.insert(0, '.')  # no-check: test-app-env-before-syspath\n"
        "os.environ.setdefault('APP_ENV', 't')\n"
    ))
    report = RunReport([check])
    assert run_check(check, str(repo), report) == []
    assert report.waived() == [(
        "test-app-env-before-syspath",
        "src/a.py:2",
        "[test-app-env-before-syspath] MEDIUM src/a.py:2 — sys.path.insert() runs first",
    )]


def test_waiver_reads_the_content_column_not_the_path(tmp_path):
    """A marker in the PATH must not waive a finding on a line that has none.

    `grep -rn` emits `path:lineno:content`; handing the whole line to the parser
    instead of the content column makes a directory name a blanket waiver. Exotic,
    but a colon is legal in a POSIX path, so it is testable rather than residual.

    Note what is NOT asserted: the reported `file_line`. `run_check` splits grep's
    output on the first two colons, so a colon inside a path already mis-slices the
    location into `<dir>:<rest-of-path>` and loses the line number. That is
    pre-existing and out of this phase's class — filed, not fixed here — so this
    test pins only the property it is about: the finding survives.
    """
    d = tmp_path / "src" / "no-check:sql-fstring"
    d.mkdir(parents=True)
    (d / "a.py").write_text("one = f'SELECT 1'\n")
    findings = run_check(_check(), str(tmp_path))
    assert len(findings) == 1, "a marker in the path must not waive the finding"
    assert findings[0][0] == "sql-fstring"


_WAIVER_YML = """\
checks:
  - id: sql-fstring
    severity: critical
    paths: ["src/"]
    include: ["*.py"]
    pattern: 'f[''"](SELECT|INSERT|UPDATE|DELETE|ALTER|DROP)'
    description: "f-string SQL detected"
    used_by: [codebase-review]
    blocking: true
"""


def _run_cli(tmp_path, monkeypatch, argv_extra):
    argv = ["run_checks", "--repo-root", str(tmp_path), "--mode", "both"] + argv_extra
    monkeypatch.setattr(sys, "argv", argv)
    try:
        rci.main()
    except SystemExit as e:
        return e.code if e.code is not None else 0
    return 0


@pytest.fixture()
def cli_repo(tmp_path: Path) -> Path:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "checks.yml").write_text(_WAIVER_YML)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text(
        "kept = f'SELECT 1'\n"
        "waived = f'SELECT 2'  # no-check: sql-fstring — identifier validated upstream\n"
    )
    return tmp_path


def test_cli_prints_a_waived_line_and_counts_it(cli_repo, monkeypatch, capsys):
    code = _run_cli(cli_repo, monkeypatch, [])
    captured = capsys.readouterr()
    assert code == 0
    assert "[waived] [sql-fstring] CRITICAL src/a.py:2" in captured.out
    assert "src/a.py:1" in captured.out
    assert "waived: 1" in captured.err
    assert "1 finding(s)" in captured.err, "the waived one is not a finding"


def test_cli_waived_finding_does_not_fail_the_blocking_gate(cli_repo, monkeypatch, capsys):
    """Line 1 still fires, so remove it and only the waived one is left."""
    (cli_repo / "src" / "a.py").write_text(
        "waived = f'SELECT 2'  # no-check: sql-fstring\n"
    )
    code = _run_cli(cli_repo, monkeypatch, ["--fail-on-blocking"])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert "waived: 1" in captured.err
    assert "[waived]" in captured.out


def test_cli_prints_each_waiver_exactly_once(cli_repo, monkeypatch, capsys):
    """N>=2 with an exact count: `in` on a one-waiver fixture asserted neither
    completeness nor multiplicity, so printing twice and printing only the first
    both survived."""
    (cli_repo / "src" / "a.py").write_text(
        "kept = f'SELECT 0'\n"
        "w1 = f'SELECT 1'  # no-check: sql-fstring\n"
        "w2 = f'SELECT 2'  # no-check: sql-fstring\n"
        "w3 = f'SELECT 3'  # no-check: sql-fstring\n"
    )
    code = _run_cli(cli_repo, monkeypatch, [])
    captured = capsys.readouterr()
    assert code == 0
    waived_lines = [l for l in captured.out.splitlines() if l.startswith("[waived]")]
    assert len(waived_lines) == 3, waived_lines
    assert waived_lines == [
        f"[waived] [sql-fstring] CRITICAL src/a.py:{n} — f-string SQL detected"
        for n in (2, 3, 4)
    ]
    assert "waived: 3" in captured.err
    assert "1 finding(s)" in captured.err


def test_cli_unwaived_blocking_finding_still_fails(cli_repo, monkeypatch, capsys):
    """Negative control: the gate is not simply dead."""
    code = _run_cli(cli_repo, monkeypatch, ["--fail-on-blocking"])
    assert code == 1
    assert "1 new blocking finding" in capsys.readouterr().err


def test_waived_finding_is_not_written_to_the_baseline(cli_repo, monkeypatch, capsys):
    baseline = cli_repo / ".claude" / "checks_baseline.txt"
    code = _run_cli(cli_repo, monkeypatch, ["--update-baseline"])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    body = baseline.read_text()
    assert "src/a.py:1" in body
    assert "src/a.py:2" not in body
    # The round's MEDIUM: --update-baseline counted the waiver in the header and
    # printed no line, on the one path a maintainer audits suppressions from.
    assert "[waived] [sql-fstring] CRITICAL src/a.py:2" in captured.out
    assert "waived: 1" in captured.err
