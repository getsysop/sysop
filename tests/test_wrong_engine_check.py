"""`packs/postgres`' `wrong-engine` check, run through the shipped runner (`Q-615`, Phase 340).

The check flagged the `if not db_config.writer_engine:` guard that the same pack's
`missing-writer-engine-guard` requires, so complying with one check made a finding in the
other; and its `(import|#)` negative dropped a real read that carried a trailing comment.

Phase 340 first narrowed the PATTERN to "lines that use an engine", as one consumer had. Its
round showed that shape leaking both ways (real uses behind another qualifier, an unquoted dict
key or a lambda with parameters were missed; prose was still flagged), and the fix moved to the
NEGATIVE instead: the pattern still matches every mention, and the negative drops exactly the
lines that cannot run a query and that the sibling check requires.

Everything goes through `run_checks.grep.run_check`: the pattern through the system `grep -E`
(BSD on macOS, GNU on Linux and in CI), the negative through Python's `re`, as a consumer's
pre-scan runs them. A Python probe of the pattern proves nothing about the grep half: POSIX ERE
reads a backslash inside a bracket expression literally. The check is read from the fragment,
so an edit to the shipped check is what these tests judge.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from run_checks.grep import run_check

REPO_ROOT = Path(__file__).resolve().parents[1]
FRAGMENT = REPO_ROOT / "packs" / "postgres" / "companion" / "checks.yml.fragment"

# Lines that must be reported: every way the round found code using an engine.
USES = [
    "    with db_config.writer_engine.connect() as conn:  # read",
    "    engine = db_config.admin_engine",
    "    run(q, engine=writer_engine)",
    "    _select_one(writer_engine, q)",
    "        writer_engine,",
    "    return db_config.writer_engine",
    "    e = getattr(db_config, 'writer_engine')",
    "    engine = reader_engine if ro else db_config.writer_engine",
    "    engines = [writer_engine, reader_engine]",
    "    pool = {writer_engine: 'w'}",
    "    get = lambda: writer_engine",
    "    yield db_config.writer_engine",
    "    engine = override or db_config.writer_engine",
    "    engine = self.writer_engine",
    "    pd.read_sql(q, con=app.state.writer_engine)",
    "    ENGINES = {Role.WRITER: writer_engine}",
    "    run_sync(lambda c: writer_engine)",
    "    for eng in writer_engine, reader_engine:",
    "    with writer_engine.sync_engine.connect() as c:",
    "    with db_config.admin_engine.execution_options(isolation_level='AUTOCOMMIT').connect() as conn:",
    "    if engine is writer_engine:",
    "    if not writer_engine.connect():",
    "    if writer_engine.dialect.name == 'postgresql':",
    "    if writer_engine: run(writer_engine)",
    # Round 2: a one-line guard whose body uses an engine, and a real use after an
    # import on the same line, must stay reported.
    "    if not writer_engine: writer_engine = make()",
    "    if not db_config.writer_engine: db_config.admin_engine.connect()",
    "    if (e := writer_engine): e.connect()",
    "from x import y; writer_engine.connect()",
    "    if not getattr(db_config, 'writer_engine', None): writer_engine = make()",
    # Round 2's execution lens, placed after the rate limit: a getattr default is evaluated,
    # so an engine there runs; an engine as a call argument or in an `and` tail is a use;
    # a body use after the first statement, or after a `#` inside a string, is still a use;
    # and the colon of `:=` is not a guard's.
    '    if not getattr(g, "conn", writer_engine.connect()):',
    "    if not getattr(cache, 'rows', pd.read_sql(q, con=writer_engine)):",
    "    if run(getattr(db, 'x', writer_engine.connect())):",
    "    if not getattr(db, 'writer_engine', writer_engine.connect()):",
    "    if run(getattr(db_config, 'writer_engine')):",
    "    if not getattr(db, pick(writer_engine)):",
    "    if not getattr(db, 'writer_engine', None) or run(admin_engine.connect()):",
    "    if run_select(writer_engine):",
    "    if not run(q, writer_engine):",
    "    if fetch_rows(writer_engine):",
    "    if writer_engine and writer_engine.execute(q).rowcount:",
    "    if not db.writer_engine: log.warning('x'); db.admin_engine.connect()",
    "    if not writer_engine: q = '#'; writer_engine.connect()",
    "from x import y; admin_engine.connect()",
    "    imported = pd.read_sql(q, writer_engine)",
    "    if not (writer_engine := create_engine(WRITER_URL)):",
    "    if (admin_engine := make_admin()) is None: raise RuntimeError('unset')",
]
# Lines that must NOT be reported: a guard alone on its line, a comment, an import.
DROPPED = [
    "    if not db_config.writer_engine:",
    "    if not writer_engine:",
    "    if db_config.writer_engine is None:",
    "    elif writer_engine is not None:",
    "    if not self.writer_engine:",
    "    if app.state.admin_engine is None:",
    "    if (db_config.writer_engine is None):",
    "    if not (writer_engine):",
    "    # engine = writer_engine",
    "    from db_config import (writer_engine, reader_engine)",
    "import os, writer_engine",
    # Round 2 (record lens): the one-line form missing-writer-engine-guard describes.
    "    if not db_config.writer_engine: logger.warning('no writer'); return None",
    "    if db_config.writer_engine is None: raise RuntimeError('unset')",
    "    if not getattr(db_config, 'writer_engine', None): return []",
    "    if not db_config.writer_engine:  # dev without write credentials",
    '    if not getattr(db_config, "writer_engine", None):',
    "    if getattr(db_config, 'writer_engine') is None:",
    "    if getattr(self.cfg, 'admin_engine', None) is None: return []",
    "    if not getattr(db_config,'writer_engine'):",
    "    # writer_engine is used below",
    "from db_config import writer_engine",
    "import writer_engine",
]
# Reported on purpose, and named as reported in the check's notes: the noise a
# line-oriented pattern cannot tell from a use without losing uses.
STILL_REPORTED = [
    '    logger.warning("writer_engine unavailable")',
    '    """Uses writer_engine (app_writer role)."""',
    "    x = 1  # falls back to reader or writer_engine",
    "    if db_config.reader_engine is None or db_config.writer_engine is None:",
    "    if db.writer_engine == engine:",
    "    if writer_engine is not engine: engine.dispose()",
    "    iface.writer_engine: Engine = create_engine(url)",
]


def _pack_check(check_id: str) -> dict:
    data = yaml.safe_load(FRAGMENT.read_text(encoding="utf-8"))
    checks = data["checks"] if isinstance(data, dict) else data
    return dict(next(c for c in checks if c["id"] == check_id))


def _flagged(tmp_path: Path, check_id: str, lines: list[str]) -> set[str]:
    src = tmp_path / "api" / "routes" / "mod.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("def f():\n" + "\n".join(lines) + "\n", encoding="utf-8")
    check = _pack_check(check_id)
    check.update(paths=["api/"], exclude=[])
    hits = run_check(check, str(tmp_path))
    text = src.read_text(encoding="utf-8").split("\n")
    return {text[int(h[1].rsplit(":", 1)[1]) - 1] for h in hits}


def test_every_use_of_an_engine_is_reported(tmp_path):
    got = _flagged(tmp_path, "wrong-engine", USES)
    assert got == set(USES), sorted(set(USES) - got)


@pytest.mark.parametrize("line", DROPPED)
def test_a_guard_a_comment_or_an_import_is_not(tmp_path, line):
    assert _flagged(tmp_path, "wrong-engine", [line]) == set(), line


def test_the_documented_noise_is_still_reported(tmp_path):
    """The notes say these are reported for triage. A negative widened to drop them would
    also drop real uses on the same kind of line, which is why they stay."""
    got = _flagged(tmp_path, "wrong-engine", STILL_REPORTED)
    assert got == set(STILL_REPORTED), sorted(set(STILL_REPORTED) - got)


def test_the_two_engine_checks_no_longer_contradict_each_other(tmp_path):
    """The guard one check requires is not a finding of the other, and the call the
    guard protects is a finding of both."""
    guarded = ["    if not db_config.writer_engine:", "        return None",
               "    with db_config.writer_engine.begin() as conn:"]
    assert _flagged(tmp_path, "wrong-engine", guarded) == {guarded[2]}
    assert _flagged(tmp_path, "missing-writer-engine-guard", guarded) == {guarded[2]}


def test_the_shipped_check_parses_as_a_consumer_parses_it():
    """`_flagged` overrides `paths` and `exclude` to point at its fixture, so the shipped
    scope is otherwise unjudged, and a scalar `include:` passes `run_check` while
    `parse_checks_yml` refuses it for every check a consumer runs (Phase 340's round)."""
    from run_checks.config import _validate_check

    check = _pack_check("wrong-engine")
    _validate_check(check, 0)
    assert check["paths"] == ["<api module>/routes/", "<api module>/tools/"], check["paths"]
    assert check["include"] == ["*.py"] and not check.get("exclude"), check
    assert "codebase-review" in check["used_by"], check


_TIMED_SEARCH = """
import re, sys, time
pattern, line = sys.stdin.read().split("\\0", 1)
negative = re.compile(pattern)
start = time.perf_counter()
negative.search(line)
print(time.perf_counter() - start)
"""


_TIMING_LINES = [
    "    if not writer_engine" + " " * 2000 + "y",
    # 20,000 so a quadratic prefix fails by an order of magnitude, not by machine speed:
    # `\\s*\\(?\\s*(not\\s*\\(?\\s*)?` took 0.81 s at 5,000 against the 1-second budget.
    "    if not " + " " * 20000 + "x",
    "    if " + " " * 1000 + "not" + " " * 1000 + "(" + " " * 1000 + "x",
    "    if " + "a." * 5000 + "writer_engin:",
    "    if getattr(" + "writer_engine," * 30000 + ":",
    "    if getattr(x" + " " * 20000 + ",",
    "    if not getattr(" + "a" * 20000 + ":",
    "    if (" + "(" * 5000 + "writer_engine",
    "from " + " " * 5000 + "x",
    # The body lookahead: `(?!(.|\\s)*ENGINE)` is exponential in the whitespace after the colon.
    "    if not writer_engine:" + " " * 20000 + "x",
    "    if not getattr(db, 'writer_engine'):" + " " * 20000 + "x",
]


# Short ids: pytest puts the test id in PYTEST_CURRENT_TEST, which the child inherits, and
# Linux refuses any one environment string over 128 KB (E2BIG) where macOS does not.
@pytest.mark.parametrize("line", _TIMING_LINES,
                         ids=[f"t{i}-{len(line)}" for i, line in enumerate(_TIMING_LINES)])
def test_the_negative_does_not_backtrack(line):
    """The negative runs under Python's `re` on every line the pattern matches. Its
    round-2 form stacked optional groups between `\\s*`s, and `if not writer_engine`
    followed by 4,000 spaces took over 15 seconds, and 2,000 took 3.2. The budget is 1 second.

    The search runs in a child process with a hard timeout: measured after `search()`
    returns, an exponential form would hang the suite rather than fail it (round 2's
    execution lens, whose dots-in-a-qualifier mutant ran past 180 s)."""
    import subprocess
    import sys

    import os

    # Linux's MAX_ARG_STRLEN, checked here so a long id fails on macOS too, not only in CI.
    assert len(os.environ.get("PYTEST_CURRENT_TEST", "")) < 128 * 1024
    pattern = _pack_check("wrong-engine")["negative_pattern"]
    try:
        r = subprocess.run([sys.executable, "-c", _TIMED_SEARCH], input=pattern + "\0" + line,
                           capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        pytest.fail(f"search did not finish in 10 s: {line[:40]!r}")
    assert r.returncode == 0, r.stderr
    assert float(r.stdout) < 1.0, (line[:40], r.stdout)
