"""The `/review-close` stop-shape inventory and the figures its spec quotes (Phase 362).

`tools/unattended_close/` holds three readers' rows over `review-close/SKILL.md` at the
pinned commit, and `tools/UNATTENDED_CLOSE_SPEC.md` designs `--prepare` / `--resume` from
them. Three things are guarded here:

* **The rows are true of the pinned file.** `inventory.py --verify` checks every quote on its
  line and that every stop-vocabulary line has a row. The rows are hand-authored judgement;
  this does not check a row's *classification*, only that it cites real text.
* **The counts the spec states are the command's.** A count typed into the spec drifts from
  the rows the moment one is added, so each count the tally prints is read back out of the
  sentence that states it. The spec is read with HTML comments and fenced blocks removed (an
  unclosed comment fails), and each phrase must occur once: a correct phrase parked in a
  comment or a fence, or beside a wrong live one, does not satisfy it. **Not bound:** line-number
  lists, which rows are given as examples, and prose readings; nor does anything here check a
  row's classification, since swapping two rows' kinds keeps every count (Phase 362, round 2).
* **The verifier's own checks fire.** Each is exercised on a synthetic file, because a
  verifier that stops checking reports "inventory verified" over anything.

Skips, and only these: the public mirror (`REVIEW_CHECKLIST.md` absent, the sentinel every
mirror-skipping module here uses), and a SHALLOW clone that lacks the
pinned commit. A source repo missing the spec, or a full clone missing the commit, fails:
Phase 362's round showed the first version skipping all eight tests on a typo in `PIN`. The
verifier unit tests need neither, so they skip only in the mirror.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "tools" / "unattended_close" / "inventory.py"
SPEC = REPO_ROOT / "tools" / "UNATTENDED_CLOSE_SPEC.md"
MIRROR_SENTINEL = REPO_ROOT / "REVIEW_CHECKLIST.md"


@pytest.fixture(autouse=True, scope="module")
def _source_repo_only():
    if not MIRROR_SENTINEL.is_file():
        pytest.skip("REVIEW_CHECKLIST.md is absent, so this is the public mirror; tools/ does not ship")


@pytest.fixture(scope="module")
def pinned():
    assert TOOL.is_file(), f"{TOOL} is missing from the source repo"
    assert SPEC.is_file(), f"{SPEC} is missing from the source repo"
    pin = re.search(r'^PIN = "([0-9a-f]+)"', TOOL.read_text(encoding="utf-8"), re.M)
    assert pin, "inventory.py no longer names its pinned commit"
    probe = subprocess.run(["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"{pin.group(1)}^{{commit}}"],
                           capture_output=True)
    if probe.returncode != 0:
        shallow = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--is-shallow-repository"],
                                 capture_output=True, text=True).stdout.strip()
        if shallow == "true":
            pytest.skip(f"the pinned commit {pin.group(1)} is not in this shallow clone")
        pytest.fail(f"the pinned commit {pin.group(1)} does not resolve in a full clone: PIN is wrong")
    return pin.group(1)


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, cwd=REPO_ROOT)


def test_every_row_cites_real_text_and_every_vocab_line_has_a_row(pinned):
    r = _run("--verify")
    assert r.returncode == 0 and "inventory verified" in r.stdout, r.stdout + r.stderr


@pytest.fixture(scope="module")
def tally(pinned) -> str:
    r = _run()
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def _pairs(tally: str, label: str) -> dict[str, int]:
    line = next((l for l in tally.splitlines() if l.startswith(label)), None)
    assert line, f"the tally no longer prints {label!r}"
    return {k: int(v) for k, v in re.findall(r"\('([^']+)', (\d+)\)", line)}


def _spec() -> str:
    text = SPEC.read_text(encoding="utf-8")
    assert text.count("<!--") == text.count("-->"), "the spec has an unclosed HTML comment"
    live = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    live = re.sub(r"^(```|~~~).*?^\1[ \t]*$", "", live, flags=re.S | re.M)
    return re.sub(r"\s+", " ", live)


def _once(phrase: str) -> None:
    n = _spec().count(phrase)
    assert n == 1, f"the spec carries {phrase!r} {n} times; it must say it once, live"


def test_the_headline_counts(tally):
    m = re.search(r"rows (\d+)\s+stops (\d+)\s+report-only (\d+)\s+transitions (\d+)", tally)
    assert m, tally
    rows, stops, ro, trans = m.groups()
    _once(f"**{rows} rows: {stops} stops and {ro} `report-only`.**")
    _once(f"**{trans} transitions**")


def test_the_kind_and_scope_split(tally):
    k, s = _pairs(tally, "kinds"), _pairs(tally, "scope")
    stops = sum(k.values())
    _once(f"the {stops} are {k['halt']} halt, {k['hard-fail']} hard-fail, {k['ask']} ask, {k['conflict']} "
          f"conflict, {k['gate-red']} gate-red and {k['relay']} relay")
    _once(f"{s['close']} stop the close, {s['branch']} one branch and {s['step']} one step")


def test_the_stops_and_asks_by_step(tally):
    b = _pairs(tally, "stops by step")
    _once(f"**Stops by step:** {b['preamble']} in the preamble, {b['1']} in Step 1, {b['2']} in Step 2, "
          f"{b['3']} in Step 3, {b['3c']} in 3c, {b['3b']} in 3b, {b['4']} in Step 4 and {b['5-8']} in Steps 5–8")
    a = _pairs(tally, "asks by step")
    _once(f"**Asks by step:** {a['1']} in Step 1, {a['2']} in Step 2, {a['3']} in Step 3, {a['3c']} in 3c, "
          f"{a['4']} in Step 4 and {a['5-8']} in Steps 5–8")
    assert set(a) == {"1", "2", "3", "3c", "4", "5-8"}, f"asks moved into a step the spec does not name: {a}"
    before = a["1"] + a["2"] + a["3"] + a["3c"]
    _once(f"of the {before} asks before Step 3b, Step 2 holds {a['2']} and 3c holds {a['3c']}")


def test_the_reversibility_split(tally):
    r = _pairs(tally, "transitions reversible")
    _once(f"{r['yes']} reversible, {r['until-push']} reversible until the push, {r['no']} not reversible "
          f"and {r['unclear']} unclear")


def test_the_boundary_split(tally):
    line = next(l for l in tally.splitlines() if l.startswith("before Step 3b:"))
    n = int(re.match(r"before Step 3b: (\d+)", line).group(1))
    p = _pairs(tally, "before Step 3b:")
    _once(f"the {n} stops before Step 3b fall out as **{p['recordable']} recordable, "
          f"{p['halt-prepare']} halt-prepare, {p['at-resume (after a 3c answer)']} at resume after a 3c "
          f"answer, and {p['n/a']} n/a**")
    _once(f"**Recordable** ({p['recordable']}):")
    _once(f"**Halt-prepare** ({p['halt-prepare']}):")
    all_ = _pairs(tally, "prepare (end of 3c)")
    by = _pairs(tally, "stops by step")
    assert all_["at-resume (3b)"] == by["3b"]
    _once(f"3b's {by['3b']} stops all fire at resume")
    _once(f"The {all_['past-boundary']} from Step 4 onward ({by['4']} in Step 4, {by['5-8']} in Steps 5–8)")


def test_the_not_reversible_writes_before_step_4(tally):
    line = next(l for l in tally.splitlines() if l.startswith("not reversible before Step 4"))
    lines = [int(x) for x in re.findall(r"\d+", line.split("Step 4", 1)[1])]
    words = {5: "Five", 6: "Six", 7: "Seven", 8: "Eight"}
    _once(f"**{words.get(len(lines), len(lines))} transitions before Step 4 are not reversible**")
    spec = _spec()
    for ln in lines:
        assert re.search(rf"\bL{ln}\b", spec), f"the spec does not cite L{ln}, a not-reversible write before Step 4"
    heads = dict(_module().headings(_module().pinned_lines()))
    in_3b = sum(heads["3b"] <= ln < heads["4"] for ln in lines)
    r = _pairs(tally, "transitions reversible")
    _once(f"The {r['no']} span the whole skill; Steps 1–3b have {words.get(len(lines)).lower()}, "
          f"{ {3: 'three', 4: 'four', 5: 'five'}.get(in_3b, in_3b) } of them in 3b")


def test_the_counts_stated_in_passing(tally):
    """Round 2 (guards lens) changed each of these and the test stayed green."""
    k = _pairs(tally, "kinds")
    _once(f"Why {k['ask']} asks and not Phase 361's")
    a = _pairs(tally, "asks by step")
    assert "3b" not in a, f"Step 3b now has asks: {a}"
    _once("Step 3b asks nothing.")
    p = _pairs(tally, "before Step 3b:")
    words = {1: "one", 2: "two", 3: "three", 4: "four"}
    _once(f"The {words.get(p['n/a'], p['n/a'])} n/a rows are")
    u = _pairs(tally, "unattended (Step 4 on)")
    _once(f"so the {u['park-branch']} above already assume the ruling")


def test_the_unattended_split(tally):
    u = _pairs(tally, "unattended (Step 4 on)")
    _once(f"{sum(u.values())} stops): {u['park-close']} park the close, {u['park-branch']} park one branch, "
          f"{u['cannot-unattend']} cannot be done unattended, and {u['n/a']} are n/a")


def test_the_sites_with_no_stated_instruction_are_counted_from_the_list():
    text = SPEC.read_text(encoding="utf-8")
    sec = text[text.index("**Sites with no stated instruction"):text.index("### 3.4")]
    bullets = re.findall(r"^- (.*)$", sec, re.M)
    # A bullet names one site per `L<n>` it leads with, or one unnumbered site.
    sites = sum(max(1, len(re.findall(r"L\d+", b.split(":", 1)[0]))) for b in bullets)
    assert sites == 11, f"§ 3.3's list holds {sites} sites in {len(bullets)} bullets"
    past = sec[sec.index("The last two are past the boundary"):]
    assert "so **nine** halt a prepare" in re.sub(r"\s+", " ", past)
    assert "eleven" in re.sub(r"\s+", " ", sec)


# ── the verifier's own checks, on a synthetic file ──────────────────────────────────

def _module():
    spec = importlib.util.spec_from_file_location("unattended_close_inventory", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


#: The regex the three readers were given (`BRIEF.md`, Phase 362), as `grep -i -E` read it.
#: Coverage means "every line this matched has a row", so a narrower `VOCAB` would report
#: full coverage over lines nobody classified.
READERS_REGEX = (r"halt|\bstop\b|STOP|abort|refus|AskUserQuestion|HARD[ -]?FAIL|do not (proceed|continue|merge)"
                 r"|must not proceed|exit [1-9]|sys\.exit\([1-9]|\bask\b|relay|`!`|! <")

SRC = ["plain text", "**halt** here", "more plain text", "an exit 3 line"]


def _row(line, quote, kind="halt"):
    return {"line": line, "quote": quote, "kind": kind, "scope": "n/a" if kind == "report-only" else "close"}


def _clean():
    return [_row(1, "plain text", "report-only"), _row(2, "**halt**"), _row(4, "exit 3")]


def test_the_coverage_vocabulary_is_the_one_the_readers_were_given():
    mod = _module()
    assert mod.VOCAB.pattern == READERS_REGEX and mod.VOCAB.flags & re.I
    for word in ("halt", "Stop", "abort", "refuses", "AskUserQuestion", "HARD FAIL", "exit 3",
                 "sys.exit(2)", "ask the user", "relay", "do not proceed"):
        assert mod.VOCAB.search(word), word


def test_a_clean_synthetic_inventory_verifies():
    assert _module().verify(SRC, _clean(), [_row(3, "more plain")]) == []


def test_an_unrowed_vocab_line_is_reported():
    rows = [r for r in _clean() if r["line"] != 2]
    assert _module().verify(SRC, rows, []) == ["vocab line 2 has no stops row"]


def test_a_quote_on_another_line_is_reported():
    rows = _clean() + [_row(1, "**halt**")]
    assert _module().verify(SRC, rows, []) == ["stops: quote not on line 1: '**halt**'"]


def test_a_line_out_of_range_is_reported():
    rows = _clean() + [_row(99, "plain text")]
    assert _module().verify(SRC, rows, []) == ["stops: quote not on line 99: 'plain text'"]


def test_an_empty_or_tiny_quote_is_reported():
    mod = _module()
    for q in ("", "   ", "pla", "plai"):
        bad = mod.verify(SRC, _clean() + [_row(1, q)], [])
        assert len(bad) == 1 and "quote too short" in bad[0], (q, bad)


def test_line_zero_is_reported():
    """`src[0 - 1]` is the LAST line, so a bare index would accept it."""
    rows = _clean() + [_row(0, "an exit 3 line")]
    assert _module().verify(SRC, rows, []) == ["stops: quote not on line 0: 'an exit 3 line'"]


def test_a_duplicated_row_is_reported():
    bad = _module().verify(SRC, _clean() + [_row(2, "**halt**")], [])
    assert len(bad) == 1 and bad[0].startswith("stops: duplicated row"), bad


def test_an_unknown_scope_is_reported():
    rows = [dict(r, scope="close") for r in _clean()] + [dict(_row(3, "more plain"), scope="everything")]
    assert _module().verify(SRC, rows, []) == ["stops: line 3: unknown scope 'everything'"]


def test_an_unknown_kind_is_reported():
    rows = _clean() + [_row(3, "more plain", "stop")]
    assert _module().verify(SRC, rows, []) == ["stops: line 3: unknown kind 'stop'"]


def test_transitions_are_checked_too():
    bad = _module().verify(SRC, _clean(), [_row(3, "nowhere")])
    assert bad == ["transitions: quote not on line 3: 'nowhere'"]


def test_step_ranges_come_from_the_headings():
    mod = _module()
    src = ["intro"] + [h for _, h in mod.HEADINGS]
    heads = mod.headings(src)
    assert [n for n, _ in heads] == ["1", "2", "3", "3c", "3b", "4", "5-8"]
    assert mod.step(1, heads) == "preamble" and mod.step(len(src), heads) == "5-8"
    with pytest.raises(SystemExit):
        mod.headings(src + [mod.HEADINGS[0][1]])
