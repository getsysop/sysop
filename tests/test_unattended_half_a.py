"""Half A of the unattended close: the re-take and the class table (Phase 376, `Q-664`).

`tools/unattended_close/retake.py` carries the Phase 362 inventory to a newer pin, and
`half_a.py` classes the half-A stops and applies Wade's per-class rulings
(`tools/UNATTENDED_CLOSE_SPEC.md` § 13). Guarded here:

* **The re-take is true of both pins.** `retake.py --verify` fails on a row whose quote is not on
  its mapped line and is not found once elsewhere, and on a stop-vocabulary line at the new pin
  that no row reaches. `half_a.py --verify` fails on a half-A stop with no class, and on an
  exception keyed to a line that carries two rows (a line key would move both).
* **§ 13's counts are the commands'.** Each is read back out of the sentence or table row that
  states it, once, live (comments and fences removed), as `test_unattended_close_inventory.py`
  does for §§ 2–6. **Not bound:** which class a row is in, beyond the counts; the line lists in
  the exceptions; the prose readings.
* **The checks fire.** A lost quote, an unclassed 3b row and a doubled exception line are each
  shown to fail.

Skips, and only these: the public mirror (`REVIEW_CHECKLIST.md` absent) and a SHALLOW clone that
lacks either pin.
"""
from __future__ import annotations

import collections
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = REPO_ROOT / "tools" / "unattended_close"
SPEC = REPO_ROOT / "tools" / "UNATTENDED_CLOSE_SPEC.md"
MIRROR_SENTINEL = REPO_ROOT / "REVIEW_CHECKLIST.md"


@pytest.fixture(autouse=True, scope="module")
def _source_repo_only():
    if not MIRROR_SENTINEL.is_file():
        pytest.skip("REVIEW_CHECKLIST.md is absent, so this is the public mirror; tools/ does not ship")


def _import():
    sys.path.insert(0, str(TOOLS))
    try:
        import half_a
        import inventory
        import retake
    finally:
        sys.path.remove(str(TOOLS))
    return retake, half_a, inventory


@pytest.fixture(scope="module")
def units():
    """The pure functions, which need neither pin: these tests skip only in the mirror."""
    retake, half_a, _ = _import()
    return retake, half_a


@pytest.fixture(scope="module")
def mods():
    retake, half_a, inventory = _import()
    for pin in (inventory.PIN, retake.NEW_PIN):
        probe = subprocess.run(["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"{pin}^{{commit}}"],
                               capture_output=True)
        if probe.returncode != 0:
            shallow = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--is-shallow-repository"],
                                     capture_output=True, text=True).stdout.strip()
            if shallow == "true":
                pytest.skip(f"pin {pin} is not in this shallow clone")
            pytest.fail(f"pin {pin} does not resolve in a full clone")
    return retake, half_a


def _run(tool: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOLS / tool), *args], capture_output=True, text=True,
                          cwd=REPO_ROOT)


def _spec13() -> str:
    text = SPEC.read_text(encoding="utf-8")
    assert text.count("<!--") == text.count("-->"), "the spec has an unclosed HTML comment"
    live = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    live = re.sub(r"^(```|~~~).*?^\1[ \t]*$", "", live, flags=re.S | re.M)
    start = live.find("## 13. Half A with no human")
    assert start >= 0, "the spec has no live § 13"
    return re.sub(r"\s+", " ", live[start:])


def _once(phrase: str) -> None:
    n = _spec13().count(phrase)
    assert n == 1, f"§ 13 carries {phrase!r} {n} times; it must say it once, live"


def _pairs(out: str, label: str) -> dict[str, int]:
    line = next((l for l in out.splitlines() if l.startswith(label)), None)
    assert line, f"the tally no longer prints {label!r}"
    return {k: int(v) for k, v in re.findall(r"\('([^']+)', (\d+)\)", line)}


def test_retake_and_half_a_verify(mods):
    for tool, ok in (("retake.py", "re-take verified"), ("half_a.py", "half A verified")):
        r = _run(tool, "--verify")
        assert r.returncode == 0 and ok in r.stdout, r.stdout + r.stderr


def test_the_retake_counts(mods):
    out = _run("retake.py").stdout
    c = _pairs(out, "carried rows")
    assert set(c) <= {"moved", "rewritten"}, f"a status the spec does not state: {c}"
    _once(f"**{c['moved']} rows moved and {c['rewritten']} were rewritten**")
    m = re.search(r"new rows (\d+)\s+new stops (\d+)", out)
    assert m, out
    _once(f"**{m[1]} new rows, {m[2]} of them stops**")
    added = re.search(r"added lines (\d+)", out)[1]
    retake, _ = mods
    lines = len({r["line"] for r in retake.load("stops_376")})
    _once(f"The {added} added lines carry {lines} stop-vocabulary lines")


def test_the_class_table_and_effects(mods):
    out = _run("half_a.py").stdout
    total = re.search(r"half-A stops at \S+: (\d+)", out)[1]
    _once(f"**{total} half-A stops**")
    classes = dict((k, int(n)) for n, k in re.findall(r"^\s*(\d+)\s+(\S+)\s+exceptions placed", out, re.M))
    _, half_a = mods
    assert set(classes) == set(half_a.CLASSES), classes
    for k, n in classes.items():
        _once(f"| `{k}` | {n} |")
    # The table's effect cell must agree with the ruling for the two park classes (round 1, P9).
    table = _spec13()
    for k, word, wrong in (("merged", "durable", "early"), ("state-unknown", "early", None)):
        cell = re.search(rf"\| `{k}` \| \d+ \| ([^|]*)\|", table)[1]
        assert word in cell and (wrong is None or wrong not in cell), (k, cell)
    e = _pairs(out, "by effect")
    branch = e["park-branch"] + sum(v for k, v in e.items() if k.startswith("park-branch |"))
    arm = sum(v for k, v in e.items() if k.startswith("park-branch |"))
    timed = sum(v for k, v in e.items() if k.startswith("end-run |"))
    _once(f"**By effect: {e['park-close durable']} durable parks of the close, {e['park-close early']} "
          f"early ones**, {branch} branch parks ({arm} of them with a close-park arm), {e['as-written']} as "
          f"written, {e['end-run']} that end the run, {timed} that ends the run or parks durably by when "
          f"it fires, {e['not-reached']} not reached and {e['skip']} skipped.")
    assert sum(e.values()) == int(total)
    t = _pairs(out, "irreversible transitions on the path")
    late = t["from Step 4-pre"]
    _once(f"**{t['before Step 4-pre']} irreversible transitions before Step 4-pre and {late} "
          f"from Step 4-pre to half A's end**")


def test_a_lost_quote_fails(units):
    retake, _ = units
    new = ["alpha", "beta", "gamma"]
    rows = [{"line": 1, "quote": "zeta"}]
    assert retake.carry(rows, {1: 2}, new)[0]["status"] == "lost"
    assert retake.carry([{"line": 1, "quote": "gamma"}], {}, new)[0]["status"] == "rewritten"
    assert retake.carry([{"line": 1, "quote": "a"}], {}, new)[0]["status"] == "lost"   # not unique
    # a mapped row whose quote left its line is lost, even when the quote is unique elsewhere
    assert retake.carry([{"line": 1, "quote": "gamma"}], {1: 2}, new)[0]["status"] == "lost"


def test_verify_fails_on_a_lost_row_and_a_wrong_fresh_quote(mods, monkeypatch):
    retake, _ = mods
    real = retake.load
    monkeypatch.setattr(sys, "argv", ["retake.py", "--verify"])
    assert retake.main() == 0, "the control"
    def lost(name):
        rows = real(name)
        if name == "stops":
            rows[0] = {**rows[0], "quote": rows[0]["quote"] + " NOT IN THE FILE"}
        return rows
    monkeypatch.setattr(retake, "load", lost)
    assert retake.main() == 1
    def wrong(name):
        rows = real(name)
        if name == "stops_376":
            rows[0] = {**rows[0], "quote": rows[0]["quote"] + " NOT ON THE LINE"}   # line kept: coverage holds
        return rows
    monkeypatch.setattr(retake, "load", wrong)
    assert retake.main() == 1


def test_an_exception_off_the_path_fails(mods, monkeypatch):
    _, half_a = mods
    monkeypatch.setattr(sys, "argv", ["half_a.py", "--verify"])
    monkeypatch.setattr(half_a, "EXCEPTIONS", {**half_a.EXCEPTIONS, 5300: ("start", "test")})
    assert half_a.main() == 1


def test_hunk_mapping(units):
    retake, _ = units
    # old 1-10; insert 2 lines after old 3 (-3,0 +4,2); replace old 7-8 with 1 line (-7,2 +9,1)
    mapping, added = retake.map_hunks([(3, 0, 4, 2), (7, 2, 9, 1)], 10)
    assert [mapping[i] for i in (1, 2, 3)] == [1, 2, 3], "the line before an insertion moves by 0"
    assert [mapping[i] for i in (4, 5, 6)] == [6, 7, 8]
    assert 7 not in mapping and 8 not in mapping, "a replaced line has no map"
    assert [mapping[i] for i in (9, 10)] == [10, 11]
    assert added == {4, 5, 9}


def test_an_unrowed_vocab_line_fails(mods, monkeypatch):
    retake, _ = mods
    real = retake.load
    monkeypatch.setattr(retake, "load", lambda name: real(name)[1:] if name == "stops_376" else real(name))
    monkeypatch.setattr(sys, "argv", ["retake.py", "--verify"])
    assert retake.main() == 1


def test_an_unclassed_3b_row_fails(mods, monkeypatch):
    _, half_a = mods
    st, rg = half_a.rows()
    row = next(r for r in st if rg["3b"] <= r["line"] < rg["4"] and r["line"] in half_a.SKIP_3B)
    monkeypatch.setattr(half_a, "SKIP_3B", half_a.SKIP_3B - {row["line"]})
    assert half_a.classify(row, rg) == "UNCLASSED"
    monkeypatch.setattr(sys, "argv", ["half_a.py", "--verify"])
    assert half_a.main() == 1


def test_a_doubled_exception_line_fails(mods, monkeypatch):
    _, half_a = mods
    st, _ = half_a.rows()
    doubled = next(ln for ln, n in collections.Counter(r["line"] for r in st).items() if n > 1)
    monkeypatch.setattr(sys, "argv", ["half_a.py", "--verify"])
    assert half_a.main() == 0, "the control: the unmutated table verifies"
    monkeypatch.setattr(half_a, "EXCEPTIONS", {**half_a.EXCEPTIONS, doubled: ("start", "test")})
    assert half_a.main() == 1
