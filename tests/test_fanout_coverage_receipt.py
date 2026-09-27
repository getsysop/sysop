"""The round header's `Fan-out coverage` line reaches the round receipt.

Phase 324 put a `> **Fan-out coverage:**` line in both review skills' Step 5b
round-header templates, so the per-worker `opened/assigned` ratios outlive the
terminal they were printed to, but nothing read it: the Step 5f receipt writer
parsed only the `Coverage` line. A fan-out round that omitted the ratios closed
exactly like one that carried them.

Every test here RUNS the shipped Step 5f heredoc (extracted from the SKILL.md
the way `tests/test_round_markers.py` does it) against a `review_tasks.md`
fixture, or runs the shipped `/sitrep` reader against a receipt, so the subject
is the code that ships and not its description.

What is pinned:

- a fan-out round's line is recorded as `fanout: {text, ratios, waves}`;
- a fan-out round without it records `fanout: "unreported"` and prints the
  stable `FANOUT-UNREPORTED` token, and the marker still clears;
- a solo round, and a round whose `workers` is itself unreported, record
  `null` and print nothing new;
- in a merged same-day round each skill takes its own labelled line, and an
  unlabelled line is refused as ambiguous rather than handed to either skill;
- the coverage line and the fan-out line can never be read as each other;
- `/sitrep` reports a fan-out round whose receipt says `unreported`, and stays
  silent on a receipt written before the key existed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.test_round_coverage_ledger import (  # noqa: E402
    SKILLS, _close, _open_round, _plant_receipt, _receipts, _self_check_output,
)
from tests.test_round_markers import _repo  # noqa: E402

LABEL = {"codebase-review": "code quality", "security-audit": "security"}
TITLE = {"codebase-review": "Code Quality Review",
         "security-audit": "OWASP Security Audit"}
BOTH = pytest.mark.parametrize("skill", sorted(SKILLS))


def _cov(skill: str, workers: str = "4", label: str | None = None) -> str:
    return (f"> **Coverage ({label or LABEL[skill]}):** Full · manifest 40 · "
            f"opened 40 · grepped 0 · workers {workers}")


def _fan(skill: str | None, body: str = "Backend 10/20, Frontend 30/30 · 2 waves",
         head: str = "Fan-out coverage") -> str:
    label = f" ({LABEL[skill]})" if skill else ""
    return f"> **{head}{label}:** {body}"


def _round(tmp_path: Path, skill: str, header: list[str], name: str = "r"):
    """Open a round, write a header, close it; return (receipt, stdout, marker)."""
    root = _repo(tmp_path / name)
    marker = _open_round(root, skill)
    (root / "review_tasks.md").write_text(
        "# Code Review Tasks\n\n"
        f"## Round 1 (2026-09-24) — {TITLE[skill]}\n\n"
        + "\n".join(header) + "\n\n"
        "### Batch 1 — Thing `Pending`\n\n- [ ] **TASK-1**: t 🟢\n",
        encoding="utf-8")
    r = _close(root, marker, skill)
    assert r.returncode == 0, r.stderr
    found = _receipts(root)
    assert len(found) == 1, found
    return json.loads(found[0].read_text(encoding="utf-8")), r.stdout, marker


# ── the three states ────────────────────────────────────────────────────────


@BOTH
def test_a_fanout_round_with_the_line_records_it(tmp_path, skill):
    rec, out, marker = _round(tmp_path, skill, [_cov(skill), _fan(skill)])
    assert rec["fanout"] == {
        "text": _fan(skill), "ratios": [[10, 20], [30, 30]], "waves": 2}
    assert "FANOUT-UNREPORTED" not in out
    assert "kept as text only" not in out
    assert not marker.exists()


@BOTH
def test_a_fanout_round_without_the_line_is_unreported_and_loud(tmp_path, skill):
    rec, out, marker = _round(tmp_path, skill, [_cov(skill, workers="4")])
    assert rec["fanout"] == "unreported"
    assert "round-receipt: FANOUT-UNREPORTED — 4 worker(s)" in out, out
    assert "Step 5b" in out, "the warning must name where the line goes"
    # A written receipt is never rewritten: the remedy must not promise it clears this one
    # (round lens 1: /sitrep kept reporting a round whose header had been fixed).
    assert "never rewritten" in out and "stays `unreported`" in out, out
    assert rec["manifest"] == 40, "the coverage line must still be recorded"
    assert not marker.exists(), "the warning must never cost the clear"


@BOTH
def test_a_solo_round_needs_no_line(tmp_path, skill):
    rec, out, _ = _round(
        tmp_path, skill, [_cov(skill, workers="0, solo: six files")])
    assert rec["workers"] == 0
    assert rec["fanout"] is None
    assert "FANOUT-UNREPORTED" not in out
    assert "fan-out line" not in out


@BOTH
def test_unreported_workers_are_not_reported_twice(tmp_path, skill):
    """The `unreported field(s)` print already names `workers`; a second
    warning about the fan-out line would report one gap as two."""
    rec, out, _ = _round(tmp_path, skill, [_cov(skill, workers="unreported")])
    assert rec["workers"] == "unreported"
    assert rec["fanout"] is None
    assert "unreported field(s): workers" in out
    assert "FANOUT-UNREPORTED" not in out


def test_a_solo_round_that_writes_the_line_anyway_keeps_it(tmp_path):
    rec, out, _ = _round(tmp_path, "codebase-review",
                         [_cov("codebase-review", workers="0, solo: x"),
                          _fan("codebase-review", "A 3/3 · 1 wave")])
    assert rec["fanout"]["ratios"] == [[3, 3]]
    assert "FANOUT-UNREPORTED" not in out


# ── merged same-day rounds ──────────────────────────────────────────────────


def _merged(q_fan: str | None, s_fan: str | None, workers=("2", "3")) -> list[str]:
    lines = [_cov("codebase-review", workers[0])]
    if q_fan is not None:
        lines.append(q_fan)
    lines.append(_cov("security-audit", workers[1]))
    if s_fan is not None:
        lines.append(s_fan)
    return lines


def test_a_merged_round_gives_each_skill_its_own_line(tmp_path):
    q = _fan("codebase-review", "Backend 1,200/1,500 · 1 wave")
    s = _fan("security-audit", "A01: 4/4; A03 = 5/6 (injection) · 2 wave(s)")
    for skill, want in (("codebase-review", [[1200, 1500]]),
                        ("security-audit", [[4, 4], [5, 6]])):
        rec, out, _ = _round(tmp_path, skill, _merged(q, s), name=skill)
        assert rec["fanout"]["ratios"] == want, skill
        assert rec["fanout"]["text"] == (q if skill == "codebase-review" else s)
        assert "FANOUT-UNREPORTED" not in out


@BOTH
def test_a_merged_round_never_lends_one_skills_line_to_the_other(tmp_path, skill):
    """The other skill wrote its line and this one did not: this skill must
    record `unreported`, not the other skill's ratios."""
    other = "security-audit" if skill == "codebase-review" else "codebase-review"
    lines = {s: _fan(s, "X 1/1 · 1 wave") for s in (other,)}
    header = _merged(lines.get("codebase-review"), lines.get("security-audit"))
    rec, out, _ = _round(tmp_path, skill, header)
    assert rec["fanout"] == "unreported"
    assert "FANOUT-UNREPORTED" in out


@BOTH
def test_an_unlabelled_line_in_a_merged_round_is_refused(tmp_path, skill):
    """One unlabelled line and two coverage lines: it could be either skill's."""
    header = _merged(_fan(None, "X 1/1 · 1 wave"), None)
    rec, _, _ = _round(tmp_path, skill, header)
    assert rec["fanout"] == "unreported"


@BOTH
def test_two_lines_with_this_skills_label_are_refused(tmp_path, skill):
    """Two candidates and nothing to choose between them: `unreported`, never
    the first one."""
    header = [_cov(skill), _fan(skill, "A 1/1 · 1 wave"), _fan(skill, "B 2/2 · 1 wave")]
    rec, out, _ = _round(tmp_path, skill, header)
    assert rec["fanout"] == "unreported"
    assert "FANOUT-UNREPORTED" in out


@BOTH
def test_a_line_labelled_for_the_other_skill_is_never_taken(tmp_path, skill):
    """One coverage line and one fan-out line carrying the OTHER skill's label.
    The lone-line fallback is for an unlabelled line only; a foreign label is a
    statement that the line is not this skill's."""
    other = "security-audit" if skill == "codebase-review" else "codebase-review"
    rec, out, _ = _round(tmp_path, skill, [_cov(skill), _fan(other, "A 1/2 · 1 wave")])
    assert rec["fanout"] == "unreported"
    assert "FANOUT-UNREPORTED" in out


def test_a_batch_named_for_the_other_audit_does_not_steal_its_line(tmp_path):
    """The fan-out tag is matched in the `(…)` label. A quality batch called
    `Security utils` must not make the quality line a second match for the
    security reader, which would then record its own round as unreported."""
    q = _fan("codebase-review", "Security utils 3/9, Core 4/4 · 1 wave")
    s = _fan("security-audit", "A01 5/5 · 1 wave")
    rec, out, _ = _round(tmp_path, "security-audit", _merged(q, s))
    assert rec["fanout"]["text"] == s
    rec, out, _ = _round(tmp_path, "codebase-review", _merged(q, s), name="q")
    assert rec["fanout"]["text"] == q


def test_an_unparseable_line_is_named_before_the_commit(tmp_path):
    """The text-only note is the only signal that a present line recorded no
    ratios; it prints at 5f, while the header can still be corrected."""
    rec, out, _ = _round(tmp_path, "codebase-review",
                         [_cov("codebase-review"), _fan("codebase-review", "all of it")])
    assert rec["fanout"]["ratios"] == "unreported"
    assert "round-receipt: fan-out line kept as text only" in out
    assert "FANOUT-UNREPORTED" not in out


@BOTH
def test_an_unlabelled_line_in_a_single_skill_round_is_taken(tmp_path, skill):
    """The Phase 324 shape carried no label; alone, it is unambiguous."""
    rec, _, _ = _round(tmp_path, skill, [_cov(skill), _fan(None, "X 7/9 · 1 wave")])
    assert rec["fanout"]["ratios"] == [[7, 9]]


def test_each_skills_shipped_template_label_is_the_one_its_writer_selects(tmp_path):
    """Join the 5b template to the 5f selector: fill each skill's own shipped
    template line into one merged header, and each writer must find its own.
    A template that lost its label falls to the unlabelled fallback, which a
    merged round refuses, so this goes red."""
    shipped = {}
    for skill, path in SKILLS.items():
        found = re.findall(r"^> \*\*Fan-out coverage[^\n]*$",
                           path.read_text(encoding="utf-8"), re.M)
        assert len(found) == 1, (skill, found)
        shipped[skill] = re.sub(r"<\w+> <opened>/<assigned>, <\w+> <opened>/"
                                r"<assigned>, … · <W> wave\(s\)",
                                "A 2/5, B 3/3 · 1 wave(s)", found[0])
        assert shipped[skill] != found[0], f"{skill}: template shape changed"
    header = _merged(shipped["codebase-review"], shipped["security-audit"])
    for skill in SKILLS:
        rec, _, _ = _round(tmp_path, skill, header, name=f"t-{skill}")
        assert rec["fanout"]["text"] == shipped[skill], skill
        assert rec["fanout"]["ratios"] == [[2, 5], [3, 3]]


# ── neither line is read as the other ───────────────────────────────────────


@BOTH
def test_a_capitalised_fanout_label_is_not_a_coverage_line(tmp_path, skill):
    """`read_coverage` selects on a case-sensitive `Coverage`. A fan-out line
    spelled `Fan-out Coverage (<label>)` carries this skill's tag, so without
    the exclusion it is a second hit, the set is ambiguous, and the whole
    coverage ledger drops to `unreported`."""
    fan = _fan(skill, "A 1/2 · 1 wave", head="Fan-out Coverage")
    rec, _, _ = _round(tmp_path, skill, [_cov(skill), fan])
    assert rec["manifest"] == 40 and rec["kind"] == "Full"
    assert rec["line"] == _cov(skill)
    assert rec["fanout"]["text"] == fan


@BOTH
def test_a_fanout_line_alone_is_never_the_coverage_line(tmp_path, skill):
    """With no coverage line, the lone fan-out line must not be parsed as one
    (the single-line fallback would otherwise take it)."""
    rec, _, _ = _round(tmp_path, skill, [_fan(skill, "A 1/2 · 1 wave")])
    assert rec["line"] == ""
    assert rec["manifest"] == "unreported"


@BOTH
def test_the_coverage_line_is_never_the_fanout_line(tmp_path, skill):
    """A coverage line whose solo reason mentions fan-out coverage is still the
    coverage line and never counts as the fan-out line."""
    cov = _cov(skill, workers="3") + " · note: fan-out coverage below"
    rec, _, _ = _round(tmp_path, skill, [cov])
    assert rec["line"] == cov
    assert rec["fanout"] == "unreported"


@BOTH
def test_other_spellings_of_the_fanout_label_are_still_read(tmp_path, skill):
    for i, head in enumerate(("fan-out coverage", "Fanout coverage",
                              "FAN-OUT COVERAGE")):
        rec, _, _ = _round(tmp_path, skill, [_cov(skill), _fan(skill, "A 1/2 · 1 wave",
                                                               head=head)],
                           name=f"s{i}")
        assert rec["fanout"]["ratios"] == [[1, 2]], head
        assert rec["manifest"] == 40, head


def test_a_merged_quality_basis_naming_security_no_longer_steals_the_security_line(
        tmp_path):
    """The tag is matched in the `(…)` label. It used to be matched in the whole
    line, so a quality round sampled on `security-relevant modules` was a second
    hit for the security reader and its whole ledger recorded `unreported`."""
    header = [
        "> **Coverage (code quality):** Sampled (security-relevant modules) · "
        "manifest 40 · opened 40 · grepped 0 · workers 0, solo: x",
        _cov("security-audit", workers="0, solo: y").replace("manifest 40", "manifest 12"),
    ]
    rec, _, _ = _round(tmp_path, "security-audit", header)
    assert rec["manifest"] == 12
    rec, _, _ = _round(tmp_path, "codebase-review", header, name="q")
    assert rec["kind"] == "Sampled (security-relevant modules)"


# ── the ratio parse is all-or-nothing ───────────────────────────────────────


@pytest.mark.parametrize("body,ratios,waves", [
    ("A 1/2 · 1 wave", [[1, 2]], 1),
    ("A 1/2, B 3/4 · 3 waves", [[1, 2], [3, 4]], 3),
    ("A 1/2 · B 3/4 · 1 wave(s)", [[1, 2], [3, 4]], 1),
    ("Batch 3: 8/82; Batch 4 = 12 / 12 · 1 wave", [[8, 82], [12, 12]], 1),
    ("A01 Broken Access 12/40 (3 flagged) · 1 wave", [[12, 40]], 1),
    ("1,200/1,500, 3/4 · 1 wave", [[1200, 1500], [3, 4]], 1),
    ("A 1,2/3 · 1 wave", "unreported", 1),              # not a thousands mark
    ("A 12,34/56 · 1 wave", "unreported", 1),
    ("A 1/2", [[1, 2]], "unreported"),                 # no wave segment
    ("A 1/2, B all · 1 wave", "unreported", 1),         # one bad item refuses all
    ("A 1/2,B 3/4 · 1 wave", "unreported", 1),          # glued comma: not an item break
    ("A 1/2/3 · 1 wave", "unreported", 1),              # label may not hold a ratio
    ("· 1 wave", "unreported", 1),                      # no ratios at all
    ("<batch> <opened>/<assigned>, … · <W> wave(s)", "unreported", "unreported"),
    # Step 3c's report tail, copied as Step 5b says to copy its ratios (round lens 1).
    ("A 1/2, B 3/4; 1 batch(es) flagged low-opened · 2 waves", [[1, 2], [3, 4]], 2),
    ("A01 3/40; 2 agents flagged low-opened · 1 wave", [[3, 40]], 1),
    # The wave segment is all-or-nothing too (round lens 2, F18).
    ("A 1/2 · 3 waves, retried", "unreported", "unreported"),
])
def test_the_ratio_parse(tmp_path, body, ratios, waves):
    rec, out, _ = _round(tmp_path, "codebase-review",
                         [_cov("codebase-review"), _fan("codebase-review", body)])
    assert rec["fanout"]["ratios"] == ratios
    assert rec["fanout"]["waves"] == waves
    assert rec["fanout"]["text"] == _fan("codebase-review", body)
    noted = "kept as text only" in out
    assert noted == ("unreported" in (ratios, waves)), out


# ── the receipt's shape, and the loop-mode reader ───────────────────────────


def test_fanout_sits_ahead_of_line_and_line_stays_last(tmp_path):
    root = _repo(tmp_path / "order")
    marker = _open_round(root)
    (root / "review_tasks.md").write_text(
        "## Round 1 (2026-09-24) — Code Quality Review\n\n"
        + _cov("codebase-review") + "\n"
        + _fan("codebase-review", 'A "line": "x" 1/2 · 1 wave') + "\n\n### Batch 1\n",
        encoding="utf-8")
    _close(root, marker)
    raw = _receipts(root)[0].read_text(encoding="utf-8")
    assert raw.index('"fanout"') < raw.index('"line"')
    assert list(json.loads(raw))[-1] == "line"
    out = _self_check_output(root)
    assert "last round coverage: " + _cov("codebase-review") in out, out


# ── Q-040: which coverage line belongs to which skill ─────────────────────────

def test_a_lone_line_labelled_for_the_other_skill_is_not_this_skills(tmp_path):
    """`Q-040`(b): a single `(code quality)` line was handed to a closing
    `security-audit`, crediting a security round with a quality round's files."""
    rec, _, _ = _round(tmp_path, "security-audit", [_cov("codebase-review")], name="q040b")
    assert rec["manifest"] == "unreported", rec
    assert rec["line"] == "", rec


def test_a_label_naming_neither_skill_falls_back_to_the_line_text(tmp_path):
    """A merged round whose quality line carries a non-template label: the label names
    no skill, so the line's own text decides, as it did before labels (round lens 1)."""
    odd = ("> **Coverage (code review):** Sampled (quality hotspots) · manifest 30 · "
           "opened 12 · grepped 0 · workers 4")
    rec, _, _ = _round(tmp_path, "codebase-review", [odd, _cov("security-audit")], name="odd")
    assert rec["manifest"] == 30 and rec["kind"] == "Sampled (quality hotspots)", rec
    rec, _, _ = _round(tmp_path, "security-audit", [odd, _cov("security-audit")], name="odd2")
    assert rec["manifest"] == 40, rec


def _selectors(skill_file: str) -> dict:
    """The 5f heredoc's selector functions, exec'd straight out of the shipped skill."""
    import re as _re
    text = (Path(__file__).resolve().parents[1] / "core/skills" / skill_file / "SKILL.md").read_text()
    src = text[text.index("# Why each selector rule exists"):text.index("\ndef parse_fanout(")]
    ns: dict = {"re": _re}
    exec(src, ns)
    return ns


@BOTH
def test_a_marker_naming_no_review_skill_reads_no_line(skill):
    """`Q-040`'s sibling: a marker with no `skill:` field yields `unknown`, which fell
    silently to the quality tag. It now reads nothing, so the receipt says unreported."""
    ns = _selectors(skill)
    header = [_cov("codebase-review"), _fan("codebase-review")]
    assert ns["tag_of"]("unknown") is None
    assert ns["read_coverage"](header, "unknown") == ""
    assert ns["read_fanout"](header, "unknown") == ""
    assert ns["read_coverage"](header, "codebase-review") == header[0]


@BOTH
def test_the_text_fallback_never_reads_a_line_labelled_for_the_other_skill(skill):
    """The fallback reads text only over lines whose label names NEITHER skill: a lone
    `(code quality)` line whose basis says "security" is quality's (round 2, F-both9)."""
    ns = _selectors(skill)
    qsec = ("> **Coverage (code quality):** Sampled (security hotspots) · manifest 20 · "
            "opened 20 · grepped 0 · workers 2")
    assert ns["read_coverage"]([qsec], "security-audit") == ""
    assert ns["read_coverage"]([qsec], "codebase-review") == qsec


@BOTH
def test_a_label_naming_this_skill_outranks_a_line_that_only_mentions_it(skill):
    """Label first: an unlabelled line whose text happens to say "quality" must not make
    a labelled `(code quality)` line ambiguous."""
    ns = _selectors(skill)
    header = [_cov("codebase-review"),
              "> **Coverage:** Sampled (quality notes) · manifest 9 · opened 9 · grepped 0 · workers 0"]
    assert ns["read_coverage"](header, "codebase-review") == header[0]


SELF_CHECK_FANOUT = "fan-out round recorded no per-worker coverage"


@pytest.mark.parametrize("case,header,flagged", [
    ("fan-out, no line", [_cov("codebase-review")], True),
    ("fan-out, line present", [_cov("codebase-review"), _fan("codebase-review")], False),
    ("solo", [_cov("codebase-review", workers="0, solo: small")], False),
    ("workers unreported", [_cov("codebase-review", workers="unreported")], False),
])
def test_self_check_names_only_an_unreported_fanout(tmp_path, case, header, flagged):
    """Loop mode ships no /sitrep, so `self_check.sh` is the only loop-mode surface for
    a fan-out round that recorded no per-worker ratios (Phase 332 integration)."""
    receipt, _, _ = _round(tmp_path, "codebase-review", header, name="sc")
    out = _self_check_output(tmp_path / "sc")
    assert (SELF_CHECK_FANOUT in out) is flagged, (case, receipt.get("fanout"), out)


# ── /sitrep ─────────────────────────────────────────────────────────────────

KIND = "fan-out round with no per-worker coverage"


def _kinds(root: Path) -> list[str]:
    import sitrep_survey
    return [d.kind for d in sitrep_survey._find_discrepancies([], [], {}, root)]


@pytest.mark.parametrize("fields,flagged", [
    ({"workers": 4, "fanout": "unreported"}, True),
    ({"workers": 4, "fanout": "unreported", "kind": "Sampled (x)"}, True),
    ({"workers": 4}, False),                                 # pre-key receipt
    ({"workers": 4, "fanout": None}, False),
    ({"workers": 4, "fanout": {"text": "t", "ratios": "unreported",
                               "waves": "unreported"}}, False),
    ({"workers": 0, "fanout": "unreported", "solo_reason": "x"}, False),
    ({"workers": "unreported", "fanout": "unreported"}, False),  # other arm owns it
])
def test_sitrep_reports_only_an_unreported_fanout(tmp_path, fields, flagged):
    root = _repo(tmp_path / "s")
    _plant_receipt(root, **fields)
    assert (KIND in _kinds(root)) is flagged, _kinds(root)


def test_sitrep_reads_what_the_shipped_writer_wrote(tmp_path):
    for skill in SKILLS:
        root = _repo(tmp_path / skill)
        marker = _open_round(root, skill)
        (root / "review_tasks.md").write_text(
            f"## Round 1 (2026-09-24) — {TITLE[skill]}\n\n{_cov(skill)}\n\n### Batch 1\n",
            encoding="utf-8")
        _close(root, marker, skill)
        assert KIND in _kinds(root), skill
        (root / "review_tasks.md").write_text(
            f"## Round 2 (2026-09-24) — {TITLE[skill]}\n\n{_cov(skill)}\n"
            f"{_fan(skill)}\n\n### Batch 1\n", encoding="utf-8")
        for old in _receipts(root):
            old.unlink()
        marker = _open_round(root, skill)
        _close(root, marker, skill)
        assert KIND not in _kinds(root), skill


# ── the prose says what the code does ───────────────────────────────────────


@BOTH
def test_the_5b_prose_names_the_token_the_writer_prints(skill):
    text = SKILLS[skill].read_text(encoding="utf-8")
    assert "nothing parses it yet" not in text
    heredoc = text[text.index("python3 - <<'PY' \"<ROUND_MARKER"):]
    heredoc = heredoc[:heredoc.index("\nPY\n")]
    prose = text[text.index("> **Fan-out coverage ("):]
    after_fence = prose.index("```\n\n") + len("```\n\n")
    # The paragraph under the template, not the template: the template line
    # carries the label itself, so a slice including it proves nothing.
    para = prose[after_fence:prose.index("\n\n", after_fence)]
    assert "`FANOUT-UNREPORTED`" in para
    assert '"round-receipt: FANOUT-UNREPORTED' in heredoc
    assert f"`({LABEL[skill]})`" in para
