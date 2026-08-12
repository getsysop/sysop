"""Guards for the `Flag:` / `Triaged:` review-batch contract (Phase 181).

The defect these exist for: `> **Flag:**` was read in six shipped surfaces and
written by one, with nothing stating the writer-side contract. A review
generator's emitting agent pattern-matched the metadata of batches already in
the file and produced `Flag:` lines about its own findings; `/triage` read
them as prior verdicts (`triage/SKILL.md:62` — "it was flagged by a prior run
… do not re-analyze its tasks") and skipped those batches unread, then printed
a confident classification. A healthy run and a degraded one produced
identical evidence, because a `Flag:` line carries nothing that says who wrote
it. Upstream `wade-cms/sysop#337`.

The fix has two halves, and both are guarded here:

- **Provenance** — `> **Triaged:** <YYYY-MM-DD> <auto|flag> [TASK-…]` is the
  verdict record. `Flag:` keeps its exact prior meaning (presence = routing
  predicate); an unstamped `Flag:` is *untriaged*, not a verdict.
- **Task granularity** — the bracketed IDs are the tasks that actually need
  judgment, so `/auto-judge` stops paying adversarial-reading cost on the
  mechanical remainder of a batch it was flagged into by association.

Plus the sibling fix from `wade-cms/sysop#334`: the three skills that read
`review_tasks.md` no longer halt on a size ceiling whose only prescribed
remedy (`archive_review_tasks.py`) reclaims *merged* batches and so cannot
answer an open-queue overflow.

Two parsers consume these lines with duplicated patterns
(`review_index.py`, `sitrep_survey.py`). They are pinned equal here rather
than shared through an import, on the house duplicate-and-pin idiom that
`review_index.py`'s own regex header already states. (The first draft of this
docstring justified it by availability — that `sitrep_survey.py` might exist
where `review_index.py` does not. The round's claims lens showed that
inverted: `install.sh:97` excludes `sitrep_survey.py` from loop mode while
`review_index.py` is kept, so `sitrep_survey.py` only ever exists alongside
it. The decision stands; the reason given for it did not.)

Three parsers, not two, are fence-aware and pinned here — `next_task.py`
joined after the round found the same unbounded-last-batch shape in it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path

import pytest

import review_index as ri
import sitrep_survey as ss

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "core" / "skills"

TRIAGE = SKILLS_DIR / "triage" / "SKILL.md"
AUTO_FIX = SKILLS_DIR / "auto-fix" / "SKILL.md"
AUTO_JUDGE = SKILLS_DIR / "auto-judge" / "SKILL.md"
SITREP = SKILLS_DIR / "sitrep" / "SKILL.md"
CODEBASE_REVIEW = SKILLS_DIR / "codebase-review" / "SKILL.md"
SECURITY_AUDIT = SKILLS_DIR / "security-audit" / "SKILL.md"
WORKFLOW = REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md"

# The three skills that used to halt on the size ceiling and now read through
# an index pass. Named as a tuple so a fourth reader added later fails loudly
# rather than being silently uncovered.
QUEUE_READERS = (TRIAGE, AUTO_FIX, AUTO_JUDGE)

# The index-pass command all three prescribe, verbatim. Pinned as a literal so
# a drift in any one of them is a test failure rather than a silent divergence
# in what three skills are told to run.
INDEX_PASS = (
    "grep -n -E '^## |^### Batch |^> \\*\\*(OWASP|Scope|Branch|Verify|Overlap|"
    "Flag|Triaged):\\*\\*' review_tasks.md"
)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# === the two parsers agree ==================================================


def test_flag_pattern_is_identical_in_both_parsers():
    assert ri._META_FLAG_RE.pattern == ss._META_FLAG_RE.pattern


def test_triaged_pattern_is_identical_in_both_parsers():
    assert ri._META_TRIAGED_RE.pattern == ss._META_TRIAGED_RE.pattern


def test_triaged_task_id_pattern_is_identical_in_both_parsers():
    assert ri._TRIAGED_TASK_ID_RE.pattern == ss._TRIAGED_TASK_ID_RE.pattern


# === `Triaged:` line grammar ================================================

# (line, expected date, verdict, task ids)
_TRIAGED_CASES = [
    ("> **Triaged:** 2026-08-03 auto", "2026-08-03", "auto", []),
    ("> **Triaged:** 2026-08-03 flag", "2026-08-03", "flag", []),
    ("> **Triaged:** 2026-08-03 flag [TASK-1124]", "2026-08-03", "flag", ["TASK-1124"]),
    (
        "> **Triaged:** 2026-08-03 flag [TASK-1124, TASK-1130]",
        "2026-08-03",
        "flag",
        ["TASK-1124", "TASK-1130"],
    ),
    (
        '> **Triaged:** 2026-08-03 auto — superseded unstamped flag: "needs GCP LB knowledge"',
        "2026-08-03",
        "auto",
        [],
    ),
    (
        "> **Triaged:** 2026-08-03 flag [TASK-1] — carried from an unstamped tag",
        "2026-08-03",
        "flag",
        ["TASK-1"],
    ),
    # Tolerances the round's execute lens showed were load-bearing. The line is
    # hand-editable by contract (§ Writer-side contract rule 4), and a
    # `$`-anchored pattern with no slack made one trailing space void the whole
    # record — which the grep-based index pass could not see, so /sitrep
    # recommended /triage forever while /triage reported nothing to classify.
    ("> **Triaged:** 2026-08-03 auto ", "2026-08-03", "auto", []),
    ("> **Triaged:** 2026-08-03 flag [TASK-1]  ", "2026-08-03", "flag", ["TASK-1"]),
    ("> **Triaged:** 2026-08-03 auto - hyphen note", "2026-08-03", "auto", []),
    ("> **Triaged:** 2026-08-03 auto – en-dash note", "2026-08-03", "auto", []),
]


@pytest.mark.parametrize("line,date,verdict,ids", _TRIAGED_CASES)
@pytest.mark.parametrize("mod", [ri, ss], ids=["review_index", "sitrep_survey"])
def test_triaged_line_parses(mod, line, date, verdict, ids):
    m = mod._META_TRIAGED_RE.match(line)
    assert m is not None, line
    assert m.group(1) == date
    assert m.group(2) == verdict
    assert mod._TRIAGED_TASK_ID_RE.findall(m.group(3) or "") == ids


# Negative controls. A pattern that accepts these would let a malformed or
# hand-fabricated record pass as a verdict — the exact substitution the
# provenance stamp exists to prevent.
# A third verdict word is the plausible widening — `skip`, `defer`, `manual` —
# and `maybe` alone does not test the vocabulary, only that *some* word fails.
_MALFORMED = [
    "> **Triaged:** 2026-08-03 skip",
    "> **Triaged:** 2026-08-03 defer",
    "> **Triaged:** 2026-08-03 manual",
    "> **Triaged:** 2026-08-03",                      # no verdict
    "> **Triaged:** auto",                            # no date
    "> **Triaged:** 26-08-03 auto",                   # short year
    "> **Triaged:** 2026-8-3 auto",                   # unpadded
    "> **Triaged:** 2026-08-03 maybe",                # not a verdict word
    "> **Triaged:**2026-08-03 auto",                  # no space after the key
    "> **Triaged:** 2026-08-03 AUTO",                 # wrong case
    "  > **Triaged:** 2026-08-03 auto",               # indented — not a metadata line
    "> **Triaged:** 2026-08-03 auto extra words",     # trailing text without the em-dash
]


@pytest.mark.parametrize("line", _MALFORMED)
@pytest.mark.parametrize("mod", [ri, ss], ids=["review_index", "sitrep_survey"])
def test_malformed_triaged_line_does_not_parse(mod, line):
    assert mod._META_TRIAGED_RE.match(line) is None, line


# `_META_FLAG_RE` and `_TRIAGED_TASK_ID_RE` had a positive case each and no
# negative case anywhere, so the round's guard lens widened both in *both*
# files at once — the identity tests pin equality, not value — and everything
# stayed green. A pattern that accepts these turns arbitrary prose into batch
# metadata.
_NOT_FLAG_LINES = [
    "  > **Flag:** indented — not a metadata line",
    "The batch has a > **Flag:** line.",           # prose mentioning it
    "> Flag: no bold",
    "> **Flagged:** wrong key",
    "- [ ] **TASK-1**: mentions > **Flag:** inline",
]


@pytest.mark.parametrize("line", _NOT_FLAG_LINES)
@pytest.mark.parametrize("mod", [ri, ss], ids=["review_index", "sitrep_survey"])
def test_flag_pattern_rejects_non_metadata_lines(mod, line):
    assert mod._META_FLAG_RE.match(line) is None, line


@pytest.mark.parametrize("mod", [ri, ss], ids=["review_index", "sitrep_survey"])
def test_task_id_pattern_is_not_widened(mod):
    """`TASK-\\d+` only. `[A-Z]+-\\d+` swallows every other id family in the
    repo (FEAT-, TECH-, ISSUE-); `TASK-\\d*` matches a bare `TASK-`."""
    rx = mod._TRIAGED_TASK_ID_RE
    assert rx.findall("[TASK-1, FEAT-2, TECH-3, ISSUE-4]") == ["TASK-1"]
    assert rx.findall("TASK-") == []
    assert rx.findall("XTASK-9") == ["TASK-9"]  # documented: substring match


@pytest.mark.parametrize("mod", [ri, ss], ids=["review_index", "sitrep_survey"])
def test_triaged_bracket_group_does_not_span_past_its_close(mod):
    """`\\[(.*)\\]` is greedy across a line with two bracket pairs, pulling in
    whatever sits between them."""
    m = mod._META_TRIAGED_RE.match(
        "> **Triaged:** 2026-08-03 flag [TASK-1] — see [TASK-2] for context"
    )
    assert m is not None
    assert mod._TRIAGED_TASK_ID_RE.findall(m.group(3) or "") == ["TASK-1"]
    # The discriminating case. With `[^\]]*` two adjacent groups cannot be
    # spanned, so the line is malformed and does not parse; a greedy `(.*)`
    # swallows the gap and reports both ids as the judgment set. The earlier
    # fixture could not tell them apart, because the note group let a greedy
    # bracket backtrack into the right answer.
    assert mod._META_TRIAGED_RE.match(
        "> **Triaged:** 2026-08-03 flag [TASK-1] [TASK-2]"
    ) is None


@pytest.mark.parametrize("mod", [ri, ss], ids=["review_index", "sitrep_survey"])
def test_flag_line_still_parses_its_free_text(mod):
    """`Flag:` semantics are deliberately unchanged by this phase — the whole
    point of putting provenance in a second key was to leave the six existing
    readers of this one alone."""
    m = mod._META_FLAG_RE.match("> **Flag:** TASK-1124: open-ended sanitizer choice")
    assert m is not None
    assert m.group(1) == "TASK-1124: open-ended sanitizer choice"


# === a shared corpus, parsed by both, must agree ============================


def _fixture_tracker() -> str:
    """A `review_tasks.md` hand-transcribed from the shipped writers.

    Transcribed, not derived — nothing here reads the skill files, so this
    fixture can drift from them. Metadata shapes come from `codebase-review/SKILL.md` § 5c and
    `security-audit/SKILL.md` § 5c; the header shape from
    `review_index.py::_BATCH_HEADER_RE` (em dash U+2014); the `Flag:` /
    `Triaged:` placement from `triage/SKILL.md` Step 4.
    """
    out = ["# Review Tasks\n", "\n", "## Round 70 — 2026-07-01\n", "\n"]
    out += [
        "### Batch 690 — Old Merged Work `Merged`\n", "\n",
        "> **Scope:** a.py\n",
        "> **Branch:** `fix/batch-690-old`\n",
        "> **Verify:** `pytest`\n",
        "> **Overlap:** none\n", "\n",
        "- [x] **TASK-8000**: done thing \U0001f7e2\n", "\n",
    ]
    out += ["## Round 71 — 2026-08-03\n", "\n"]
    # auto, never triaged
    out += [
        "### Batch 700 — Scripts: shared_cli.py Migration `Pending`\n", "\n",
        "> **Scope:** sysop/scripts/foo.py\n",
        "> **Branch:** `fix/batch-700-scripts-shared-cli`\n",
        "> **Verify:** `pytest tests/test_foo.py`\n",
        "> **Overlap:** none\n", "\n",
    ]
    for i in range(1, 6):
        out.append(f"- [ ] **TASK-90{i:02d}**: Replace inline arg parsing \U0001f7e1\n")
        out.append(f"  `sysop/scripts/foo.py:{40 + i}` `[verified]` — Use the helper.\n")
        out.append("\n")
    # the #337 corpus shape: a Flag: tag with no Triaged: sibling
    out += [
        "### Batch 701 — Data Exposure & Alerting `Pending`\n", "\n",
        "> **Scope:** api/log.py\n",
        "> **Branch:** `fix/batch-701-data-exposure`\n",
        "> **Verify:** `pytest tests/test_log.py`\n",
        "> **Overlap:** 702\n",
        "> **Flag:** TASK-9101: open-ended sanitizer choice\n", "\n",
    ]
    for i in range(1, 15):
        out.append(f"- [ ] **TASK-91{i:02d}**: Wrap logger call in `_sanitize_log` \U0001f534\n")
        out.append(f"  `api/log.py:{i}` `[reported]` — Apply the helper.\n")
        out.append("\n")
    # partially flagged, stamped
    out += [
        "### Batch 702 — Backend Logging `Pending`\n", "\n",
        "> **Scope:** api/svc.py\n",
        "> **Branch:** `fix/batch-702-backend-logging`\n",
        "> **Verify:** `pytest`\n",
        "> **Overlap:** 701\n",
        "> **Flag:** TASK-9203: requires understanding of the retry semantics\n",
        "> **Triaged:** 2026-08-03 flag [TASK-9203]\n", "\n",
    ]
    for i in range(1, 5):
        out.append(f"- [ ] **TASK-92{i:02d}**: Add Z guard \U0001f7e1\n")
        out.append(f"  `api/svc.py:{i}` `[verified]` — fix.\n")
        out.append("\n")
    # stamped auto, carrying a superseded unstamped flag
    out += [
        "### Batch 703 — Security Config `Pending`\n", "\n",
        "> **OWASP:** A05\n",
        "> **Scope:** infra/conf.tf\n",
        "> **Branch:** `fix/batch-703-security-config`\n",
        "> **Verify:** `tflint`\n",
        "> **Overlap:** none\n",
        '> **Triaged:** 2026-08-03 auto — superseded unstamped flag: "needs GCP LB knowledge"\n',
        "\n",
        "- [ ] **TASK-9301**: Migrate to the hardened module \U0001f7e1\n",
        "  `infra/conf.tf:9` `[verified]` — fix.\n", "\n",
    ]
    # a standalone trailing section — the thing an unbounded last-batch read swallows
    out += ["## Convention fire ledger\n", "\n", "(none)\n"]
    return "".join(out)


@pytest.fixture()
def tracker(tmp_path):
    p = tmp_path / "review_tasks.md"
    p.write_text(_fixture_tracker(), encoding="utf-8")
    return p


def test_both_parsers_agree_on_the_whole_corpus(tracker):
    idx = ri.parse_review_tasks(str(tracker))
    a = {
        int(n): (
            b["status"],
            b["flag"],
            b["triaged_date"],
            b["triaged_verdict"],
            list(b["triaged_tasks"]),
            len(b["tasks"]),
        )
        for n, b in idx["batches"].items()
    }
    b_side = {
        b["number"]: (
            b["status"],
            b["flag_reason"],
            b["triaged_date"],
            b["triaged_verdict"],
            list(b["triaged_tasks"]),
            len(b["tasks"]),
        )
        for b in ss._read_review_batches(tracker.parent)
    }
    assert a == b_side
    # Non-vacuity: the corpus must actually exercise all four states, or the
    # equality above is agreement about nothing.
    verdicts = {v[3] for v in a.values()}
    assert verdicts == {"", "flag", "auto"}
    assert any(v[1] and not v[3] for v in a.values()), "no unstamped-Flag batch in the corpus"
    assert any(v[4] for v in a.values()), "no task-granular verdict in the corpus"


def test_unstamped_flag_batch_has_no_verdict_recorded(tracker):
    """Batch 701 is the reported shape: a `Flag:` line and no verdict. Both
    parsers must report *no* triage record for it — that emptiness is what the
    readers key 'untriaged' on."""
    idx = ri.parse_review_tasks(str(tracker))
    b = idx["batches"]["701"]
    assert b["flag"] == "TASK-9101: open-ended sanitizer choice"
    assert b["triaged_verdict"] == ""
    assert b["triaged_date"] == ""


def test_superseded_flag_text_survives_in_the_record(tracker):
    idx = ri.parse_review_tasks(str(tracker))
    b = idx["batches"]["703"]
    assert b["triaged_verdict"] == "auto"
    assert "needs GCP LB knowledge" in b["triaged_note"]
    assert b["flag"] == ""


# === the prescribed commands actually run ===================================


def _fenced_bash_blocks(text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", text, re.DOTALL)


@pytest.mark.parametrize("skill", QUEUE_READERS, ids=lambda p: p.parent.name)
def test_skill_prescribes_the_index_pass_verbatim(skill):
    """All three readers must prescribe the *same* index pass. Three skills
    each inventing their own grep is how the two `Flag:` regexes diverged.

    Matched against the block's command *lines*, not the whole block: whole-
    block equality reddened on ordinary maintenance — adding a `# comment` or
    a `set -euo pipefail` — which the round's guard lens caught as a false
    alarm. The command itself is still pinned byte-for-byte.
    """
    for block in _fenced_bash_blocks(_read(skill)):
        cmds = [
            ln.strip() for ln in block.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        if INDEX_PASS in cmds:
            return
    raise AssertionError(
        f"{skill.relative_to(REPO_ROOT)} does not prescribe the shared index pass"
    )


def test_prescribed_index_pass_runs_and_bounds_every_batch(tracker):
    """Rule 3 of the author-side pass: run the command the change prescribes,
    against a fixture built from the shipped writers.

    The command is taken from the skill file, not retyped here — a test that
    retypes it proves only that the test author can write grep.
    """
    blocks = [b.strip() for b in _fenced_bash_blocks(_read(TRIAGE))]
    cmd = next(b for b in blocks if b.startswith("grep -n -E"))
    proc = subprocess.run(
        cmd, shell=True, cwd=tracker.parent, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()

    headers = {}   # batch number -> 1-indexed line
    boundaries = []
    for ln in lines:
        num, _, body = ln.partition(":")
        boundaries.append(int(num))
        # `[^`]+`, matching the four shipped readers. Phase 191 retired the
        # `[A-Za-z ]+` charset from every production parser and missed this
        # test-side copy — in the file that pins those readers equal, which is
        # where a stale copy is least affordable. Fail-loud rather than silent
        # (the exact-set assert below catches a miss), but a hyphenated status
        # in this fixture would fail here for the retired reason.
        m = re.match(r"^### Batch (\d+) — .+ `([^`]+)`$", body)
        if m:
            headers[int(m.group(1))] = int(num)

    assert set(headers) == {690, 700, 701, 702, 703}

    # Every batch's computed body range must match what the indexer derived by
    # reading the whole file — that equality is the claim the fix rests on.
    idx = ri.parse_review_tasks(str(tracker))
    all_lines = tracker.read_text(encoding="utf-8").splitlines()
    section_starts = sorted(
        i + 1
        for i, t in enumerate(all_lines)
        if t.startswith("## ") or t.startswith("### Batch ")
    )
    for number, start in headers.items():
        later = [s for s in section_starts if s > start]
        end = (later[0] - 1) if later else len(all_lines)
        assert (start, end) == (
            idx["batches"][str(number)]["line_start"],
            idx["batches"][str(number)]["line_end"],
        ), f"batch {number} range mismatch"

    # The bound must include `## ` headings, not just `### Batch`. Without it
    # the last batch's body swallows the trailing standalone section — which
    # `/codebase-review` § 5e places there on purpose.
    last_end = idx["batches"]["703"]["line_end"]
    swallowed = [t for t in all_lines[headers[703] - 1:last_end] if t.startswith("## ")]
    assert swallowed == [], f"last batch body reaches a standalone section: {swallowed}"


def _scoped_read_template(skill: Path) -> str:
    """The `sed` line the skill prescribes, taken from the file."""
    for block in _fenced_bash_blocks(_read(skill)):
        b = block.strip()
        if b.startswith("sed -n"):
            return b
    raise AssertionError(f"{skill.relative_to(REPO_ROOT)} prescribes no sed scoped read")


@pytest.mark.parametrize("skill", QUEUE_READERS, ids=lambda p: p.parent.name)
def test_scoped_read_is_bounded_not_open_ended(skill):
    """Extracted, not retyped — the first draft of this test built the command
    in an f-string, which proves only that the test author can write sed. The
    round's guard lens walked `sed -n '<START>,$p'` straight through it: an
    open-ended read to EOF, which is the overrun the whole pass exists to
    remove."""
    cmd = _scoped_read_template(skill)
    assert cmd == "sed -n '<START>,<END>p' review_tasks.md", cmd


def test_prescribed_scoped_read_returns_exactly_one_batch(tracker):
    """The extracted `sed`, executed with its placeholders resolved the way
    the skill tells an operator to resolve them."""
    idx = ri.parse_review_tasks(str(tracker))
    b = idx["batches"]["701"]
    cmd = (
        _scoped_read_template(TRIAGE)
        .replace("<START>", str(b["line_start"]))
        .replace("<END>", str(b["line_end"]))
    )
    proc = subprocess.run(cmd, shell=True, cwd=tracker.parent, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    body = proc.stdout
    assert body.startswith("### Batch 701 —")
    assert "### Batch 702" not in body
    assert "TASK-9114" in body
    assert body.count("### Batch ") == 1
    assert len(body) < len(tracker.read_text(encoding="utf-8")) / 2


@pytest.mark.parametrize("skill", QUEUE_READERS, ids=lambda p: p.parent.name)
def test_bound_prose_names_both_halves_of_the_boundary(skill):
    """The `^## ` half is what stops the last batch swallowing a trailing
    section; the guard lens deleted it from the prose in one skill and from
    the parenthetical that explains it in another, both green."""
    text = _read(skill)
    assert "the next `^## ` / `^### Batch ` line" in text
    assert "or `$` **only when no `^## ` section follows the last batch**" in text


# === batch bounds: the last batch must not swallow trailing sections ========
#
# Found by running the prescribed index-pass command against a fixture built
# from the shipped writers (author-side rule 3), not by reading code.
#
# `review_index.py` closed an open batch only on `## Round N` and on the next
# `### Batch` header, so the LAST batch in the file ran to EOF. Its reported
# range therefore covered every standalone trailing section. `close_batch.sh`
# feeds that range to CLOSE_AWK as `-v s -v e`, and `mode=flip` rewrites every
# `- [ ] **TASK-…**` inside it — so closing the most recent batch marked every
# `## Deferred` task done. Reproduced against the shipped awk before the fix.


_TRAILING_SECTION_TRACKER = """# Review Tasks

## Round 71 — 2026-08-03

### Batch 700 — Last Batch Of The File `Pending`

> **Scope:** a.py
> **Branch:** `fix/batch-700-x`
> **Verify:** `pytest`
> **Overlap:** none

- [ ] **TASK-9001**: real batch task \U0001f7e1

## Deferred

- [ ] **TASK-7001**: deferred \U0001f7e1
- [ ] **TASK-7002**: deferred \U0001f7e2

## Statistics

(rows)

## Convention fire ledger

(none)
"""


@pytest.fixture()
def trailing_tracker(tmp_path):
    p = tmp_path / "review_tasks.md"
    p.write_text(_TRAILING_SECTION_TRACKER, encoding="utf-8")
    return p


def test_last_batch_range_stops_at_the_next_section(trailing_tracker):
    idx = ri.parse_review_tasks(str(trailing_tracker))
    b = idx["batches"]["700"]
    total = len(trailing_tracker.read_text(encoding="utf-8").splitlines())
    assert b["line_end"] < total, (
        "the last batch's range reaches end-of-file; close_batch.sh will flip "
        "checkboxes in every trailing section"
    )
    body = trailing_tracker.read_text(encoding="utf-8").splitlines()[
        b["line_start"] - 1: b["line_end"]
    ]
    assert not [ln for ln in body if ln.startswith("## ")]


def _close_awk() -> str:
    src = (REPO_ROOT / "core" / "companion" / "scripts" / "close_batch.sh").read_text(
        encoding="utf-8"
    )
    m = re.search(r"readonly CLOSE_AWK='\n(.*?)\n'\n", src, re.DOTALL)
    assert m, "CLOSE_AWK no longer extractable from close_batch.sh"
    return m.group(1)


def test_closing_the_last_batch_does_not_close_deferred_tasks(trailing_tracker):
    """The end-to-end claim, run rather than reasoned about: the *shipped* awk,
    over the *shipped* indexer's range, must leave `## Deferred` alone."""
    idx = ri.parse_review_tasks(str(trailing_tracker))
    b = idx["batches"]["700"]
    proc = subprocess.run(
        ["awk", "-v", f"s={b['line_start']}", "-v", f"e={b['line_end']}",
         "-v", "mode=flip", _close_awk(), str(trailing_tracker)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    lines = {
        ln.split("**")[1]: ln[:6] for ln in proc.stdout.splitlines() if "**TASK-" in ln
    }
    assert lines["TASK-9001"] == "- [x] ", "the batch's own task should close"
    assert lines["TASK-7001"] == "- [ ] ", "a deferred task was closed by the batch"
    assert lines["TASK-7002"] == "- [ ] ", "a deferred task was closed by the batch"


@pytest.mark.parametrize("skill", QUEUE_READERS, ids=lambda p: p.parent.name)
def test_scoped_read_does_not_licence_a_bare_dollar_bound(skill):
    """§ 1b's `$` shortcut contradicted § 1a's own caveat, and re-reading the
    whole tail is precisely what the scoped pass exists to avoid. Caught in the
    author-side battery as an anchor miss — one of the three still carried the
    unqualified form after a bulk edit."""
    text = _read(skill)
    assert "or `$` **only when no `^## ` section follows the last batch**" in text
    # Every unqualified form, not one parenthesised variant. The guard lens
    # added a "Shortcut: `<END>` may be `$` for the last batch" line alongside
    # the qualified clause and it passed.
    for bad in (
        "(or `$` for the last batch)",
        ", or `$` for the last batch",
        "may be `$` for the last batch",
        "`$` for the last batch.",
    ):
        assert bad not in text, f"unqualified $-to-EOF licence present: {bad!r}"


def test_fence_closes_only_on_a_matching_marker(tmp_path):
    """A `~~~` line inside a ``` block, or a shorter run, must not close it —
    otherwise a nested example re-opens structural parsing mid-batch. Author
    battery survivor F6; closed with a fixture rather than left as a residual."""
    # The `~~~` sits INSIDE a ``` block and the structural lines sit after it,
    # still inside. A close-on-any-marker rule ends the block at `~~~`, so the
    # `## Deferred` and `> **Flag:**` below it become structure again.
    text = (
        "## Round 1 — 2026-08-03\n\n"
        "### Batch 800 — Nested fences `Pending`\n\n"
        "> **Branch:** `fix/b800`\n\n"
        "- [ ] **TASK-1**: first \U0001f7e1\n\n"
        "```markdown\n"
        "~~~\n"
        "## Deferred\n"
        "> **Flag:** not real\n"
        "```\n\n"
        "- [ ] **TASK-2**: second \U0001f7e1\n"
    )
    p = tmp_path / "review_tasks.md"
    p.write_text(text, encoding="utf-8")
    b = ri.parse_review_tasks(str(p))["batches"]["800"]
    assert [t["id"] for t in b["tasks"]] == ["TASK-1", "TASK-2"]
    assert b["flag"] == ""

    # Same rule, the length half: a ```` block is closed only by four or more.
    # A three-backtick line inside it is content — which is exactly how you
    # quote a fenced example inside a fenced example.
    longer = (
        "## Round 1 — 2026-08-03\n\n"
        "### Batch 801 — Nested fences, length rule `Pending`\n\n"
        "> **Branch:** `fix/b801`\n\n"
        "- [ ] **TASK-1**: first \U0001f7e1\n\n"
        "````markdown\n"
        "```\n"
        "## Deferred\n"
        "> **Flag:** not real\n"
        "````\n\n"
        "- [ ] **TASK-2**: second \U0001f7e1\n"
    )
    p.write_text(longer, encoding="utf-8")
    b = ri.parse_review_tasks(str(p))["batches"]["801"]
    assert [t["id"] for t in b["tasks"]] == ["TASK-1", "TASK-2"]
    assert b["flag"] == ""


def test_empty_batch_still_bounds_at_the_next_section(tmp_path):
    """Round 2's guard lens gated the close on `current["tasks"]`, so a batch
    with no tasks yet — the state every batch passes through — swallowed the
    trailing section's task lines instead of ending."""
    text = (
        "## Round 1 — 2026-08-03\n\n"
        "### Batch 950 — Empty `Pending`\n\n"
        "> **Branch:** `fix/b950`\n\n"
        "## Deferred\n\n"
        "- [ ] **TASK-7001**: deferred \U0001f534\n"
    )
    p = tmp_path / "review_tasks.md"
    p.write_text(text, encoding="utf-8")
    assert ri.parse_review_tasks(str(p))["batches"]["950"]["tasks"] == []
    ss_batches = ss._read_review_batches(tmp_path)
    assert [b["number"] for b in ss_batches] == [950]
    assert ss_batches[0]["tasks"] == []
    nt_batches = nt.parse_review_batches(text)
    assert [b["number"] for b in nt_batches] == [950], (
        "an empty batch vanished from /next-task instead of bounding"
    )
    assert nt_batches[0]["tasks"] == []


def test_bound_does_not_fire_on_a_deeper_or_quoted_heading(tmp_path):
    """Two widenings the guard lens walked through: `startswith("#")` bounds
    on a `#!/usr/bin/env bash` shebang inside a fenced example, and
    `lstrip("> ")` bounds on a *quoted* `> ## Deferred`. Both truncate a batch
    and leave its tail open under a `Merged` header."""
    text = (
        "## Round 1 — 2026-08-03\n\n"
        "### Batch 900 — Scripts `Pending`\n\n"
        "> **Branch:** `fix/b900`\n\n"
        "- [ ] **TASK-1**: add the shebang \U0001f7e1\n"
        "  ```bash\n"
        "#!/usr/bin/env bash\n"
        "  ```\n"
        "- [ ] **TASK-2**: quote the section name \U0001f7e1\n"
        "> ## Deferred\n"
        # Unfenced, column 0, deeper than level 2 — `startswith("#")` bounds
        # here, `startswith("## ")` does not. The fenced shebang above cannot
        # discriminate, because the mask hides it before the bound is reached.
        "#### A detail heading inside the batch body\n"
        "- [ ] **TASK-3**: third \U0001f7e1\n"
    )
    p = tmp_path / "review_tasks.md"
    p.write_text(text, encoding="utf-8")
    b = ri.parse_review_tasks(str(p))["batches"]["900"]
    assert [t["id"] for t in b["tasks"]] == ["TASK-1", "TASK-2", "TASK-3"]
    assert [t["id"] for t in ss._read_review_batches(tmp_path)[0]["tasks"]] == [
        "TASK-1", "TASK-2", "TASK-3"
    ]
    assert [t["task_id"] for t in nt.parse_review_batches(text)[0]["tasks"]] == [
        "TASK-1", "TASK-2", "TASK-3"
    ]


def test_bound_holds_for_every_trailing_section_order(tmp_path):
    """The pre-change parser had four closers, one of which was `## Statistics`
    — so it was already correct when `## Statistics` came first, and wrong only
    once a `## Deferred` section preceded it (that branch early-`continue`s,
    making the Statistics closer unreachable). The fix must not be sensitive to
    the order at all, which a fixture with one fixed order cannot show.
    """
    body = (
        "## Round 1 — 2026-08-03\n\n"
        "### Batch 700 — Last `Pending`\n\n"
        "> **Branch:** `fix/b700`\n\n"
        "- [ ] **TASK-9001**: real \U0001f7e1\n\n"
    )
    # Every trailing section carries a task-shaped line, so a bound narrowed to
    # any ONE section name leaks a task in the orders where that section is not
    # first. A fixture where only `## Deferred` has task lines cannot tell a
    # correct bound from one hard-coded to `## Deferred` — author battery
    # survivor F8.
    # The names are deliberately NOT all drawn from the tracker's known
    # vocabulary. Permuting three known names only defeats a bound narrowed to
    # ONE of them; round 2's guard lens narrowed the bound to the SET and every
    # permutation stayed green. `## Notes` is the control that no plausible
    # allowlist contains.
    sections = {
        "## Deferred": "- [ ] **TASK-7001**: deferred \U0001f534\n",
        "## Statistics": "- [ ] **TASK-7002**: stats-shaped row \U0001f534\n",
        "## Notes": "- [ ] **TASK-7003**: an unforeseen section \U0001f534\n",
    }
    import itertools

    for order in itertools.permutations(sections):
        text = body + "".join(f"{h}\n\n{sections[h]}\n" for h in order)
        p = tmp_path / "review_tasks.md"
        p.write_text(text, encoding="utf-8")
        b = ri.parse_review_tasks(str(p))["batches"]["700"]
        lines = text.splitlines()
        assert [t["id"] for t in b["tasks"]] == ["TASK-9001"], order
        assert not [
            ln for ln in lines[b["line_start"] - 1: b["line_end"]] if ln.startswith("## ")
        ], f"batch body reaches a trailing section for order {order}"
        # All three parsers, not just the one the defect was reported in — a
        # bound narrowed to the *first* section name a fixture happens to
        # carry passes a single-order test. Author battery survivor F8.
        assert [t["id"] for t in ss._read_review_batches(tmp_path)[0]["tasks"]] == [
            "TASK-9001"
        ], f"sitrep_survey absorbed a trailing section for order {order}"
        nt_b = nt.parse_review_batches(text)[0]
        assert [t["task_id"] for t in nt_b["tasks"]] == ["TASK-9001"], (
            f"next_task absorbed a trailing section for order {order}"
        )
        assert nt_b["severity"]["high"] == 0, order


CLOSE_BATCH = REPO_ROOT / "core" / "companion" / "scripts" / "close_batch.sh"


def test_close_batch_fallback_bounds_on_any_heading():
    """Read the *script*, not a model of it. The first draft of this test
    re-implemented close_batch.sh's fallback in Python and asserted against
    that, so the round's guard lens changed the real `grep -n '^##'` to
    `grep -n '^### Batch '` — reintroducing the bound bug on the no-python3
    path — and the whole suite stayed green."""
    src = _read(CLOSE_BATCH)
    assert "grep -n '^##'" in src, (
        "close_batch.sh's range fallback no longer bounds at any level-2+ "
        "heading, so it and `review_index.py --range` disagree — and which "
        "one runs depends only on whether python3 is installed"
    )


def test_close_batch_prefers_the_index_over_the_fallback():
    """Pointing `INDEX_SCRIPT` at a nonexistent path makes the fallback always
    win. Nothing noticed, because nothing asserted the preference."""
    src = _read(CLOSE_BATCH)
    fn = src[src.index("find_batch_range() {"):]
    fn = fn[: fn.index("\n}\n")]
    assert "--range" in fn and "grep -n '^##'" in fn
    assert fn.index("--range") < fn.index("grep -n '^##'"), (
        "the grep fallback is now tried before the fence-aware index"
    )


def test_index_range_agrees_with_close_batch_grep_fallback(trailing_tracker):
    """Both range paths run for real on the same file — the *shell* fallback,
    not a Python restatement of it. They disagreed on exactly this file shape
    before this phase, and the preferred path was the wrong one."""
    idx = ri.parse_review_tasks(str(trailing_tracker))
    b = idx["batches"]["700"]
    cwd = trailing_tracker.parent
    start = subprocess.run(
        "grep -n '^### Batch 700 ' review_tasks.md | head -1 | cut -d: -f1",
        shell=True, cwd=cwd, capture_output=True, text=True,
    ).stdout.strip()
    assert start, "batch header not found by the fallback's own grep"
    offset = subprocess.run(
        f"tail -n +{int(start) + 1} review_tasks.md | grep -n '^##' | head -1 | cut -d: -f1",
        shell=True, cwd=cwd, capture_output=True, text=True,
    ).stdout.strip()
    total = len(trailing_tracker.read_text(encoding="utf-8").splitlines())
    fallback_end = int(start) + int(offset) - 1 if offset else total
    assert (b["line_start"], b["line_end"]) == (int(start), fallback_end)


# === fenced blocks are content, not structure ===============================
#
# Found by the round's execute lens. Widening the batch closer from `## Round N`
# to any `## ` made a fenced heading — the kind a task *about markdown* quotes —
# silently truncate its batch, so `close_batch.sh` flipped a subset and left the
# rest at `- [ ]` under a `Merged` header. The sibling half is older: a fenced
# `> **Flag:**` was attributed to the enclosing batch as a real verdict, which is
# #337's own failure mode arriving from inside the file.

import next_task as nt  # noqa: E402  (module-level import kept beside its guards)

_FENCED_TRACKER = """# Review Tasks

## Round 1 — 2026-08-03

### Batch 11 — Docs: tracker section headings `Pending`

> **Scope:** docs/tracker.md
> **Branch:** `fix/batch-11-docs`
> **Verify:** `pytest`
> **Overlap:** none

- [ ] **TASK-201**: Correct the tracker example \U0001f7e1
  Replace the block with:

  ```markdown
## Deferred

- [ ] **TASK-999**: not a real task \U0001f534
> **Flag:** not a real flag
> **Triaged:** 2026-01-01 flag [TASK-999]
### Batch 99 — not a real batch `Pending`
## Statistics
  ```

- [ ] **TASK-202**: second real task \U0001f7e1
- [ ] **TASK-203**: third real task \U0001f7e1

## Deferred

- [ ] **TASK-7001**: genuinely deferred \U0001f534
"""


@pytest.fixture()
def fenced_tracker(tmp_path):
    p = tmp_path / "review_tasks.md"
    p.write_text(_FENCED_TRACKER, encoding="utf-8")
    return p


import archive_review_tasks as ar  # noqa: E402

# Every structural reader of review_tasks.md. Derived below from the tree, so a
# fifth one cannot be silently uncovered — round 2's guard lens showed the fence
# work had reached three of what was then four, and that `archive_review_tasks.py`
# — the script the size advisory tells the operator to run — split a real merged
# round in two at a fenced example.
FENCE_AWARE_PARSERS = (ri, ss, nt, ar)


def test_fence_patterns_are_identical_in_all_parsers():
    assert len({m._FENCE_OPEN_RE.pattern for m in FENCE_AWARE_PARSERS}) == 1
    assert len({m._FENCE_CLOSE_RE.pattern for m in FENCE_AWARE_PARSERS}) == 1


def test_fenced_mask_bodies_are_identical_in_all_parsers():
    """The *regex* was pinned and the *logic* was not, so round 2's guard lens
    broke the close rule in two of three copies with the pin green. Compare the
    executable source, ignoring the docstring each copy carries."""
    import inspect
    import textwrap

    def body(mod):
        src = textwrap.dedent(inspect.getsource(mod._fenced_mask))
        lines = [ln for ln in src.splitlines() if ln.strip()]
        # drop the def line and the docstring block
        out, in_doc, seen_def = [], False, False
        for ln in lines:
            if not seen_def:
                seen_def = ln.lstrip().startswith("def ")
                continue
            s = ln.strip()
            if s.startswith('"""'):
                in_doc = not (s.endswith('"""') and len(s) > 3) if not in_doc else False
                continue
            if in_doc:
                continue
            out.append(ln.rstrip())
        return "\n".join(out)

    bodies = {m.__name__: body(m) for m in FENCE_AWARE_PARSERS}
    assert len(set(bodies.values())) == 1, (
        "the `_fenced_mask` copies have diverged:\n"
        + "\n---\n".join(f"{k}:\n{v}" for k, v in bodies.items())
    )


def test_structural_reader_population_is_derived():
    """Any module that parses `### Batch` headers out of review_tasks.md is a
    structural reader and must be fence-aware."""
    scripts = REPO_ROOT / "core" / "companion" / "scripts"
    # A structural reader *compiles a pattern anchored at a batch header*.
    # Merely naming `### Batch` in prose does not qualify — the first draft of
    # this predicate flagged `ingest_security_report.py`, whose only mention is
    # a docstring explaining that its sanitizer stops a finding forging one.
    # It is a writer, and the right side of that boundary.
    anchored = re.compile(r"""r["']\^###\\?[s ]""")
    found = {
        p.stem
        for p in scripts.glob("*.py")
        if anchored.search(p.read_text(encoding="utf-8"))
    }
    covered = {m.__name__ for m in FENCE_AWARE_PARSERS}
    assert found, "the derived population is empty — the predicate stopped matching"
    assert found <= covered, (
        f"structural readers with no fence guard: {sorted(found - covered)}"
    )


@pytest.mark.parametrize(
    "lines,expected",
    [
        # balanced — the whole block including its delimiters
        (["```", "x", "```"], [True, True, True]),
        (["```markdown", "x", "```"], [True, True, True]),
        (["   ```", "x", "   ```"], [True, True, True]),
        (["~~~", "x", "~~~"], [True, True, True]),
        # a shorter run does not close a longer one; the 4-run does
        (["````", "```", "x", "````"], [True, True, True, True]),
        # ...and a LONGER run does close a shorter one (the `>=` half; a
        # fixture that only opens 4 and closes 4 cannot tell `>=` from `==`)
        (["```", "x", "````"], [True, True, True]),
        # a different marker char does not close it
        (["```", "~~~", "x", "```"], [True, True, True, True]),
        # a closing candidate with trailing text is not a close (CommonMark)
        (["```", "```python", "x", "```"], [True, True, True, True]),
        # blockquoted fences — the form tracker metadata examples actually use
        (["> ```", "> **Flag:** example", "> ```"], [True, True, True]),
        # 4 spaces is an indented code block, not a fence
        (["    ```", "x", "    ```"], [False, False, False]),
        (["``", "x", "``"], [False, False, False]),
        (["text ```", "x"], [False, False]),
        (["## Deferred", "x"], [False, False]),
        # UNTERMINATED — deliberately not masked. Honouring it would disable
        # structural parsing to EOF, which is worse than having no fence rule:
        # the batch range then runs to end-of-file and close_batch.sh flips
        # every checkbox in it. Round 2 caught exactly that.
        (["```", "x", "y"], [False, False, False]),
        (["a", "```", "b"], [False, False, False]),
        # a balanced block followed by an unterminated one: only the first
        (["```", "x", "```", "```", "y"], [True, True, True, False, False]),
    ],
)
@pytest.mark.parametrize(
    "mod", FENCE_AWARE_PARSERS,
    ids=["review_index", "sitrep_survey", "next_task", "archive_review_tasks"],
)
def test_fenced_mask_grammar(mod, lines, expected):
    assert mod._fenced_mask(lines) == expected


def test_unterminated_fence_does_not_extend_the_batch_to_eof(tmp_path):
    """The round-2 HIGH: one unbalanced marker made the batch range run to
    end-of-file, so `close_batch.sh` closed a `## Deferred` task. That is the
    data loss the fence work exists to prevent, reintroduced by the fence work
    — and it was measurably WORSE than the state before this phase."""
    text = (
        "## Round 1 — 2026-08-03\n\n"
        "### Batch 2 — Unclosed fence `Pending`\n\n"
        "> **Branch:** `review/batch-2`\n\n"
        "- [ ] **TASK-001**: first \U0001f7e1\n"
        "- [ ] **TASK-002**: second \U0001f7e1\n\n"
        "  ```markdown\n"
        "  (never closed)\n\n"
        "- [ ] **TASK-003**: third \U0001f7e1\n\n"
        "## Deferred\n\n"
        "- [ ] **TASK-900**: deferred, must survive \U0001f7e2\n"
    )
    p = tmp_path / "review_tasks.md"
    p.write_text(text, encoding="utf-8")
    total = len(text.splitlines())
    b = ri.parse_review_tasks(str(p))["batches"]["2"]
    assert b["line_end"] < total, "an unterminated fence ran the batch range to EOF"
    assert [t["id"] for t in b["tasks"]] == ["TASK-001", "TASK-002", "TASK-003"]

    proc = subprocess.run(
        ["awk", "-v", f"s={b['line_start']}", "-v", f"e={b['line_end']}",
         "-v", "mode=flip", _close_awk(), str(p)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    states = {
        ln.split("**")[1]: ln[:6]
        for ln in proc.stdout.splitlines()
        if ln.startswith("- [") and "**TASK-" in ln
    }
    assert states["TASK-900"] == "- [ ] ", "a deferred task was closed by the batch"
    for tid in ("TASK-001", "TASK-002", "TASK-003"):
        assert states[tid] == "- [x] "


def test_unterminated_fence_does_not_hide_later_batches(tmp_path):
    """Worse than the range: at the round-1 revision a mid-file unbalanced
    fence made every batch after it vanish, flagged work included, with
    /sitrep reporting no discrepancy."""
    text = (
        "## Round 1 — 2026-08-03\n\n"
        "### Batch 1 — First `Pending`\n\n"
        "> **Branch:** `review/batch-1`\n\n"
        "- [ ] **TASK-001**: a \U0001f7e1\n"
        "  ```markdown\n\n"
        "### Batch 2 — Second `Pending`\n\n"
        "> **Branch:** `review/batch-2`\n\n"
        "- [ ] **TASK-002**: b \U0001f7e1\n\n"
        "### Batch 3 — Third `Pending`\n\n"
        "> **Branch:** `review/batch-3`\n"
        "> **Flag:** needs judgment\n"
        "> **Triaged:** 2026-08-03 flag [TASK-003]\n\n"
        "- [ ] **TASK-003**: c \U0001f7e1\n"
    )
    p = tmp_path / "review_tasks.md"
    p.write_text(text, encoding="utf-8")
    idx = ri.parse_review_tasks(str(p))
    assert sorted(idx["batches"]) == ["1", "2", "3"]
    assert idx["batches"]["3"]["triaged_verdict"] == "flag"
    assert len(ss._read_review_batches(tmp_path)) == 3
    assert len(nt.parse_review_batches(text)) == 3


def test_blockquoted_fence_hides_a_metadata_example(tmp_path):
    """#337's failure mode from inside the file, in the form it actually
    takes: tracker metadata is `> **Key:**`, so an example of it is quoted
    inside a BLOCKQUOTE, and a fence rule blind to `> ``` ` misses exactly the
    case that matters."""
    text = (
        "## Round 1 — 2026-08-03\n\n"
        "### Batch 5 — Docs: the metadata shape `Pending`\n\n"
        "> **Branch:** `review/batch-5`\n\n"
        "- [ ] **TASK-1**: document the record shape \U0001f7e1\n"
        "  The block should read:\n\n"
        "> ```markdown\n"
        "> **Flag:** <human-readable reason this batch needs judgment>\n"
        "> **Triaged:** 2026-01-01 flag [TASK-999]\n"
        "> ```\n\n"
        "- [ ] **TASK-2**: second \U0001f7e1\n"
    )
    p = tmp_path / "review_tasks.md"
    p.write_text(text, encoding="utf-8")
    b = ri.parse_review_tasks(str(p))["batches"]["5"]
    assert b["flag"] == "", "a blockquoted example became the batch's real verdict"
    assert b["triaged_verdict"] == ""
    assert b["triaged_tasks"] == []
    assert [t["id"] for t in b["tasks"]] == ["TASK-1", "TASK-2"]
    sb = ss._read_review_batches(tmp_path)[0]
    assert sb["flag_reason"] == "" and sb["triaged_verdict"] == ""


def test_indented_deferred_heading_is_prose_not_a_section(tmp_path):
    """`review_index.py` triggered its Deferred section on `line.strip()`,
    which is indentation-insensitive and contradicted the `startswith("## ")`
    closer three lines above — so an indented `## Deferred` in a task's detail
    lines diverted every following task into `deferred` while the batch stayed
    open, and the three parsers gave three different answers."""
    text = (
        "## Round 1 — 2026-08-03\n\n"
        "### Batch 6 — Docs `Pending`\n\n"
        "> **Branch:** `review/batch-6`\n\n"
        "- [ ] **TASK-001**: the section should be renamed \U0001f7e1\n"
        "  ## Deferred\n"
        "  is the current heading.\n"
        "- [ ] **TASK-002**: second \U0001f7e1\n"
    )
    p = tmp_path / "review_tasks.md"
    p.write_text(text, encoding="utf-8")
    idx = ri.parse_review_tasks(str(p))
    assert [t["id"] for t in idx["batches"]["6"]["tasks"]] == ["TASK-001", "TASK-002"]
    assert idx["deferred"] == []
    assert [t["id"] for t in ss._read_review_batches(tmp_path)[0]["tasks"]] == [
        "TASK-001", "TASK-002"
    ]
    assert [t["task_id"] for t in nt.parse_review_batches(text)[0]["tasks"]] == [
        "TASK-001", "TASK-002"
    ]


def test_review_index_does_not_truncate_a_batch_at_a_fenced_heading(fenced_tracker):
    idx = ri.parse_review_tasks(str(fenced_tracker))
    b = idx["batches"]["11"]
    assert [t["id"] for t in b["tasks"]] == ["TASK-201", "TASK-202", "TASK-203"], (
        "a fenced `## ` heading truncated the batch — close_batch.sh would flip "
        "only the tasks above it and leave the rest open under a Merged header"
    )
    assert "99" not in idx["batches"], "a fenced `### Batch` line became a real batch"


def test_review_index_ignores_fenced_metadata(tmp_path):
    """The #337 failure mode from inside the file: an example verdict adopted
    as the enclosing batch's own.

    **This test was vacuous as first written** and round 2's guard lens proved
    it: in `_FENCED_TRACKER` the fenced `## Deferred` truncates the batch
    *before* the fenced `> **Flag:**` is reached, so `current_batch` is already
    `None` and no attribution can happen — the assertion held with fence
    handling deleted outright. The fixture here contains **only** metadata
    inside the fence, so nothing else can explain the empty result.
    """
    text = (
        "## Round 1 — 2026-08-03\n\n"
        "### Batch 12 — Docs: the record shape `Pending`\n\n"
        "> **Branch:** `fix/batch-12`\n\n"
        "- [ ] **TASK-301**: document the verdict line \U0001f7e1\n"
        "  It should read:\n\n"
        "```markdown\n"
        "> **Flag:** not a real flag\n"
        "> **Triaged:** 2026-01-01 flag [TASK-999]\n"
        "```\n\n"
        "- [ ] **TASK-302**: second \U0001f7e1\n"
    )
    p = tmp_path / "review_tasks.md"
    p.write_text(text, encoding="utf-8")
    b = ri.parse_review_tasks(str(p))["batches"]["12"]
    assert [t["id"] for t in b["tasks"]] == ["TASK-301", "TASK-302"]
    assert b["flag"] == "", "a fenced example became the batch's real Flag:"
    assert b["triaged_verdict"] == ""
    assert b["triaged_tasks"] == []
    sb = ss._read_review_batches(tmp_path)[0]
    assert sb["flag_reason"] == "" and sb["triaged_verdict"] == ""


def test_review_index_ignores_fenced_deferred_tasks(fenced_tracker):
    ids = [t["id"] for t in ri.parse_review_tasks(str(fenced_tracker))["deferred"]]
    assert ids == ["TASK-7001"], f"a fenced example became a deferred task: {ids}"


def test_sitrep_survey_agrees_with_the_index_on_the_fenced_tracker(fenced_tracker):
    a = {
        int(n): (b["flag"], b["triaged_verdict"], [t["id"] for t in b["tasks"]])
        for n, b in ri.parse_review_tasks(str(fenced_tracker))["batches"].items()
    }
    b_side = {
        b["number"]: (b["flag_reason"], b["triaged_verdict"], [t["id"] for t in b["tasks"]])
        for b in ss._read_review_batches(fenced_tracker.parent)
    }
    assert a == b_side


def test_sitrep_survey_agrees_with_the_index_on_the_trailing_section_tracker(
    trailing_tracker,
):
    """The bound fix landed in `review_index.py` first; `sitrep_survey.py` kept
    counting `## Deferred` tasks into the last batch, so `done == total` could
    never hold and /sitrep's priority 2 never fired for that batch."""
    a = {
        int(n): [t["id"] for t in b["tasks"]]
        for n, b in ri.parse_review_tasks(str(trailing_tracker))["batches"].items()
    }
    b_side = {
        b["number"]: [t["id"] for t in b["tasks"]]
        for b in ss._read_review_batches(trailing_tracker.parent)
    }
    assert a == b_side
    assert a[700] == ["TASK-9001"]


def test_next_task_does_not_absorb_trailing_sections_or_fences(fenced_tracker):
    """Third parser, same class — `/next-task` ranks batches partly on
    `open_count` and severity, so absorbed deferred tasks inflate exactly the
    batch it recommends."""
    batches = nt.parse_review_batches(fenced_tracker.read_text(encoding="utf-8"))
    assert len(batches) == 1
    b = batches[0]
    assert [t["task_id"] for t in b["tasks"]] == ["TASK-201", "TASK-202", "TASK-203"]
    assert b["open_count"] == 3
    assert b["severity"]["high"] == 0, "a deferred/fenced 🔴 leaked into the batch"


def test_close_awk_over_the_fenced_batch_leaves_nothing_open(fenced_tracker):
    """End-to-end: the shipped awk over the shipped range must close every task
    the batch really has — the truncation's cost is a half-closed batch."""
    b = ri.parse_review_tasks(str(fenced_tracker))["batches"]["11"]
    proc = subprocess.run(
        ["awk", "-v", f"s={b['line_start']}", "-v", f"e={b['line_end']}",
         "-v", "mode=flip", _close_awk(), str(fenced_tracker)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    states = {
        ln.split("**")[1]: ln[:6]
        for ln in proc.stdout.splitlines()
        if ln.startswith("- [") and "**TASK-" in ln
    }
    for tid in ("TASK-201", "TASK-202", "TASK-203"):
        assert states[tid] == "- [x] ", f"{tid} left open under a Merged header"
    assert states["TASK-7001"] == "- [ ] ", "a genuinely deferred task was closed"


@pytest.mark.parametrize("skill", QUEUE_READERS, ids=lambda p: p.parent.name)
def test_index_pass_carries_the_fence_caveat(skill):
    """`grep` cannot see fences, so the operator-side half of this defect can
    only be closed by telling the operator. Both consequences must be named —
    a truncated batch reads as a small one, and a fenced verdict reads as a
    real one."""
    text = _read(skill)
    assert "cannot see fenced blocks" in text
    assert "#337 failure mode arriving from inside the file" in text


# === the size ceiling is advisory, not a gate ===============================

# A halt is prose, and a prose detector loses to paraphrase — the author-side
# battery for this phase re-added the halt in three wordings ("halt and ask",
# "abort the run", "stop; the tracker is above the ceiling") and a
# vocabulary-matching check caught none of them. Phase 179 already measured
# that class losing (0 of 21 out-of-vocabulary reversals caught).
#
# So the guard is structural instead: the size ceiling may be discussed in
# exactly one place in each skill — a subsection whose heading and operative
# sentence are pinned verbatim. Anything that changes what the skill does with
# the ceiling has to either edit pinned text or move the discussion out of its
# one legal home.

SIZE_SECTION_HEADING = "### 1c. Tracker size is advisory, never a stop"
SIZE_ADVISORY_CLAUSE = "print an advisory and **continue** — do not halt"
MERGED_ONLY_CLAUSE = (
    "selects what to relocate by **merge status**, not by size "
    "(`archive_review_tasks.py:100` matches only `Merged`/`Complete`; a Round "
    "moves whole only when every batch in it is merged, otherwise it "
    "relocates the merged batches individually)"
)


def _section_bounds(text: str, heading: str) -> tuple[int, int]:
    """0-indexed [start, end) line range of `heading`'s section.

    Line-indexed, not substring-sliced. The first draft matched the heading
    with `heading in text` and sliced with `split`, which let a `#### 1c. …`
    demotion satisfy it (`### 1c. …` is a substring of `#### 1c. …`) and let a
    *copy* of a § 1c line pasted into another step read as "inside § 1c".
    Round 2's guard lens walked both.
    """
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.rstrip() == heading]
    assert starts, f"missing section heading (exact line): {heading!r}"
    assert len(starts) == 1, f"heading appears {len(starts)} times: {heading!r}"
    start = starts[0]
    level = len(heading) - len(heading.lstrip("#"))
    for i in range(start + 1, len(lines)):
        s = lines[i].lstrip()
        if s.startswith("#"):
            n = len(s) - len(s.lstrip("#"))
            if n <= level:
                return start, i
    return start, len(lines)


def _section(text: str, heading: str) -> str:
    a, b = _section_bounds(text, heading)
    return "\n".join(text.splitlines()[a:b])


# One predicate for "this line is about the size ceiling", shared by the
# section test and the population test. They used different ones — `125KB`
# only in the population test, `125KB` or `125 KB` in the section test — so a
# halt spelled with a space landed in the gap between two guards that each
# thought the other covered it.
_CEILING_RE = re.compile(r"125\s?(?:KB|kB|kb|kilobytes)", re.IGNORECASE)


def _ceiling_lines(text: str) -> list[int]:
    return [i for i, ln in enumerate(text.splitlines()) if _CEILING_RE.search(ln)]


@pytest.mark.parametrize("skill", QUEUE_READERS, ids=lambda p: p.parent.name)
def test_queue_reader_has_exactly_one_home_for_the_size_ceiling(skill):
    """Every mention of the ceiling lives in the § 1c subsection, by LINE
    INDEX. A halt added anywhere else in the file — Step 0.5, Step 2, a new
    step — fails here even if its wording is one no pattern anticipated.

    **Honest limit, and the guard lens was right to press it:** this locates
    *mentions of the ceiling*, so it cannot see a halt that names no number
    ("if the tracker is above the historical rule of thumb, stop"). That
    residual is the class Phase 179 measured string-matching losing, and it is
    filed rather than chased — see the module docstring.
    """
    text = _read(skill)
    a, b = _section_bounds(text, SIZE_SECTION_HEADING)
    mentions = _ceiling_lines(text)
    assert mentions, f"{skill.relative_to(REPO_ROOT)} no longer mentions the ceiling at all"
    stray = [text.splitlines()[i] for i in mentions if not (a <= i < b)]
    assert stray == [], (
        f"{skill.relative_to(REPO_ROOT)} discusses the size ceiling outside "
        f"{SIZE_SECTION_HEADING!r}: {stray}"
    )


@pytest.mark.parametrize("skill", QUEUE_READERS, ids=lambda p: p.parent.name)
def test_read_queue_subsections_are_in_order(skill):
    """§ 1c was relocatable to end-of-file with **zero characters edited** and
    every pin intact — an advisory the reader meets after they have already
    acted on the queue is not an advisory. Order is part of the contract."""
    lines = _read(skill).splitlines()
    def at(h):
        idx = [i for i, ln in enumerate(lines) if ln.rstrip() == h]
        assert len(idx) == 1, f"{h!r} appears {len(idx)} times in {skill.name}"
        return idx[0]
    step1 = at("## Step 1: Read Queue")
    a, b, c = at("### 1a. Index pass"), at("### 1b. Scoped body pass"), at(SIZE_SECTION_HEADING)
    assert step1 < a < b < c, (
        f"{skill.relative_to(REPO_ROOT)}'s Read Queue subsections are out of "
        f"order: index pass {a}, scoped read {b}, size advisory {c}"
    )
    # ...and all three must stay INSIDE Step 1. Ordering alone is satisfied by
    # relocating § 1c to end-of-file with zero characters edited, which is what
    # the round's guard lens did.
    nxt = next(
        (i for i, ln in enumerate(lines) if i > step1 and ln.startswith("## ")),
        len(lines),
    )
    assert c < nxt, (
        f"{skill.relative_to(REPO_ROOT)}'s size advisory ({c}) sits outside "
        f"Step 1, which ends at line {nxt} — an advisory the reader meets "
        f"after acting on the queue is not an advisory"
    )


def test_workflow_does_not_reintroduce_a_skill_halt():
    """The population above is skills-only, so a halt asserted in the spec —
    which consumers read as authoritative — landed in the gap. `WORKFLOW.md`
    legitimately discusses the ceiling; it must not say a skill stops at it."""
    text = _read(WORKFLOW)
    lines = text.splitlines()
    for i in _ceiling_lines(text):
        window = " ".join(lines[max(0, i - 1): i + 2]).lower()
        for verb in ("refuse to run", "refuses to run", "stop and tell", "halt"):
            assert verb not in window, (
                f"WORKFLOW.md:{i + 1} reasserts a skill halt at the ceiling: {lines[i]!r}"
            )


@pytest.mark.parametrize("skill", QUEUE_READERS, ids=lambda p: p.parent.name)
def test_queue_reader_pins_the_advisory_verdict(skill):
    """The operative sentence, verbatim. This is a declared **reversion
    guard** — it proves the instruction is present and unedited, and says
    nothing about coverage."""
    section = _section(_read(skill), SIZE_SECTION_HEADING)
    assert SIZE_ADVISORY_CLAUSE in section, (
        f"{skill.relative_to(REPO_ROOT)} § 1c no longer says to continue rather "
        f"than halt — the prescribed remedy reclaims only merged batches, so a "
        f"halt is a dead end whenever the overflow is open work"
    )


@pytest.mark.parametrize("skill", QUEUE_READERS, ids=lambda p: p.parent.name)
def test_queue_reader_names_the_merged_only_constraint(skill):
    """Demoting the gate is only half the fix — an advisory that does not say
    *why* archiving cannot help sends the operator to the same dead end.

    Pinned as the operative clause rather than as two tokens: a token check is
    satisfied by an incidental use of either word, which marks a gutted
    advisory compliant.
    """
    section = _section(_read(skill), SIZE_SECTION_HEADING)
    assert MERGED_ONLY_CLAUSE in section, (
        f"{skill.relative_to(REPO_ROOT)}'s size advisory does not state the "
        f"merged-only constraint that makes archival the wrong lever"
    )


def test_the_size_ceiling_population_is_derived_not_assumed():
    """Derive the population from the tree, not from QUEUE_READERS. A fourth
    skill that gains a ceiling must show up here rather than sit uncovered —
    the assumption class that produced the worst number in Phase 168's round.
    """
    mentions = {
        p.relative_to(REPO_ROOT).as_posix()
        for p in SKILLS_DIR.rglob("*.md")
        if _CEILING_RE.search(p.read_text(encoding="utf-8"))
    }
    expected = {p.relative_to(REPO_ROOT).as_posix() for p in QUEUE_READERS}
    assert mentions == expected, (
        "the set of skills mentioning the 125KB ceiling has drifted from the "
        "set this module guards; add it to QUEUE_READERS or remove the mention"
    )


def test_workflow_scaling_paragraph_does_not_assert_a_gate():
    text = _read(WORKFLOW)
    assert "refuse to run above it" not in text
    assert "No skill refuses to run above that size." in text
    # It must also stop omitting /triage, which enforced the ceiling identically.
    para = text.split("**Scaling:**", 1)[1].split("\n\n", 3)
    joined = "\n\n".join(para[:3])
    for skill in ("/triage", "/auto-fix", "/auto-judge"):
        assert skill in joined, f"WORKFLOW scaling paragraph omits {skill}"


def test_workflow_permission_row_does_not_attribute_the_archiver_to_a_skill():
    """`:1566` named /codebase-review, /auto-fix and /auto-judge as invoking
    the archiver "when review_tasks.md exceeds 125KB". None of the five skills
    that mention it contains a prescribed invocation — verified by the sweep
    behind this phase, and re-verified here."""
    text = _read(WORKFLOW)
    row = next(
        ln for ln in text.splitlines()
        if ln.startswith("| `Bash(python sysop/scripts/archive_review_tasks.py")
    )
    assert "exceeds 125KB" not in row
    assert "no skill invokes the archiver" in row


_ARCHIVER_MENTIONS = sorted(
    p for p in SKILLS_DIR.rglob("*.md")
    if "archive_review_tasks.py" in p.read_text(encoding="utf-8")
)


@pytest.mark.parametrize(
    "skill", _ARCHIVER_MENTIONS, ids=lambda p: p.parent.name
)
def test_no_skill_prescribes_running_the_archiver_as_an_executable_step(skill):
    """The advisory names the command to the *operator*; no skill runs it.

    The population is **derived from the tree**, not listed here: the round's
    claims lens found the first draft parametrized five skills and asserted
    "none of the five", while six mention the archiver (`review-close`'s is a
    rebase-conflict note). An assumed population is the assumption class this
    module guards elsewhere; it should not have been exempt here.
    """
    for block in re.findall(r"```[a-zA-Z]*\n(.*?)```", _read(skill), re.DOTALL):
        assert "archive_review_tasks.py" not in block, (
            f"{skill.relative_to(REPO_ROOT)} now prescribes the archiver in a "
            f"fenced command; WORKFLOW.md § 8.2a's permission attribution and "
            f"this phase's advisory wording both assume it does not"
        )


# === writer-side contract ===================================================


@pytest.mark.parametrize(
    "generator", [CODEBASE_REVIEW, SECURITY_AUDIT], ids=lambda p: p.parent.name
)
def test_generator_is_told_not_to_write_the_triage_keys(generator):
    text = _read(generator)
    assert "never `> **Flag:**` or `> **Triaged:**`" in text, (
        f"{generator.relative_to(REPO_ROOT)} does not carry the writer-side "
        f"contract; a generator that emits a Flag: line makes /triage skip the "
        f"batch it was supposed to classify"
    )


@pytest.mark.parametrize(
    "generator", [CODEBASE_REVIEW, SECURITY_AUDIT], ids=lambda p: p.parent.name
)
def test_generator_batch_template_emits_no_triage_keys(generator):
    """The prose contract and the template must agree. A template that shows a
    `Flag:` line is what an emitting agent copies, whatever the prose says.

    The batch-template block is located by its `Scope:`/`Branch:` metadata,
    not by the literal `### Batch N —` header: the guard lens changed the
    header to `### Batch <N> —` and the `continue` skipped the whole block,
    letting a `Flag:` line back into the thing agents copy. It also sweeps
    every fence language, since ```` ```md ```` reads the same to an agent.
    """
    blocks = [
        b for b in re.findall(r"```[a-zA-Z]*\n(.*?)```", _read(generator), re.DOTALL)
        if "> **Scope:**" in b and "> **Branch:**" in b
    ]
    assert blocks, f"{generator.relative_to(REPO_ROOT)}: no batch template found"
    for block in blocks:
        assert "**Flag:**" not in block
        assert "**Triaged:**" not in block


def test_triage_candidate_rule_keys_on_the_record():
    """Only `/auto-fix` and `/auto-judge`'s Step 0.5 were pinned, so /triage's
    own § 1a candidate rule could revert to `carries no > **Flag:** line` —
    the reported defect, in the skill it was reported against."""
    text = _read(TRIAGE)
    assert "the batch carries no `> **Triaged:**` line" in text
    assert "the batch carries no `> **Flag:**` line" not in text


def test_triage_records_a_verdict_for_every_classified_batch():
    """Writing `Triaged:` only on flag verdicts reopens the all-auto churn on
    the writer side: an auto batch would carry no record and be re-read every
    run, which is the half of #337 the record exists to close."""
    text = _read(TRIAGE)
    assert "For **every batch this run classified** (not only the flagged ones" in text
    assert "an auto verdict is a verdict" in text


def test_auto_judge_degradation_direction_is_pinned():
    """Absent brackets mean the WHOLE batch needs judgment. Inverted — "no
    task list → nothing needs judgment" — every legacy flagged batch would be
    fixed mechanically without judgment, silently."""
    text = _read(AUTO_JUDGE)
    assert "**Absent brackets mean the whole batch**" in text
    assert "no task list on the verdict — the whole batch is the judgment set" in text


def test_auto_fix_does_not_process_partially_flagged_batches():
    """Pinned as the operative verb, not as two substrings: the guard lens
    kept both phrases and changed `Skip` to `Process`."""
    text = _read(AUTO_FIX)
    assert (
        "- **Skip** batches with a `> **Flag:**` line — those belong to "
        "`/auto-judge`, including partially-flagged ones"
    ) in text


def test_workflow_metadata_table_documents_both_keys():
    """The spec's own metadata table and single-writer paragraph are what a
    consumer reads; deleting either leaves the contract stated nowhere they
    look."""
    text = _read(WORKFLOW)
    assert "| `Triaged` |" in text
    assert "**`Flag` and `Triaged` have one writer — `/triage`**" in text
    assert "> **Triaged:** <YYYY-MM-DD> <auto|flag> [<TASK-NNN, …>]" in text


def test_triage_vacuous_rate_thresholds_are_the_stated_ones():
    """5%/1 satisfies every phrase pin and fires the notice on a healthy
    queue, which trains the reader to ignore it."""
    text = _read(TRIAGE)
    assert "**If the flag rate is ≥ 80% and there are ≥ 5 pending batches**" in text


def test_triage_declares_itself_the_sole_writer():
    text = _read(TRIAGE)
    assert "## Writer-side contract" in text
    assert (
        "**`/triage` is the only writer of `> **Flag:**` and `> **Triaged:**`.**"
    ) in text, (
        "the sole-writer sentence is gone or negated — note that pinning the\n"
        "fragment alone is satisfied by 'is no longer the only writer of ...'"
    )


def test_triage_treats_an_unstamped_flag_as_untriaged():
    text = _read(TRIAGE)
    assert "A bare `Flag:` tag is not a prior verdict." in text
    # The retired claim: a Flag: tag *is* a prior run's verdict.
    assert "it was flagged by a prior run" not in text


def test_triage_names_the_legacy_re_open_cost():
    """The change re-opens every batch tagged before the record existed. That
    is correct and it is a real cost; the skill must say so rather than let a
    consumer discover it."""
    text = _read(TRIAGE)
    assert "Legacy cost" in text
    assert "re-open" in text or "re-opens" in text


def test_triage_reports_a_vacuous_flag_rate():
    text = _read(TRIAGE)
    assert "Low-signal classification" in text
    assert "Flag rate:" in text
    # Thresholds must be declared as chosen, not passed off as measured.
    assert "chosen, not measured" in text


def test_triage_writes_the_stamp_and_the_task_list():
    text = _read(TRIAGE)
    assert "> **Triaged:** 2026-08-03 flag [TASK-1124]" in text
    assert "> **Triaged:** 2026-08-03 auto" in text
    assert "date -u +%Y-%m-%d" in text


# === task-granular consumption ==============================================


def test_auto_judge_splits_judgment_set_from_mechanical_remainder():
    text = _read(AUTO_JUDGE)
    assert "### Judgment set" in text
    assert "### Mechanical remainder" in text
    assert "Do not re-litigate them." in text
    # Graceful degradation: no list means the whole batch, as before.
    assert "no task list on the verdict" in text


def test_auto_judge_no_longer_names_the_retired_writer():
    """`/auto-fix` stopped classifying at Phase 44. Two sites still told the
    Opus agent the flag came from it."""
    text = _read(AUTO_JUDGE)
    assert "(from /auto-fix)" not in text
    assert "flagged as needing judgment by `/auto-fix`" not in text


def test_auto_fix_keeps_the_whole_flagged_batch_out_of_its_pool():
    """Task-granular flags must not split a batch across two concurrently
    running skills — a batch is the claim unit, and both skills would land on
    its one branch."""
    text = _read(AUTO_FIX)
    assert "including partially-flagged ones" in text
    assert "two agents on one branch" in text


@pytest.mark.parametrize("skill", [AUTO_FIX, AUTO_JUDGE], ids=lambda p: p.parent.name)
def test_triage_prereq_keys_on_the_record_not_the_flag(skill):
    text = _read(skill)
    assert "lacks a `> **Triaged:**` record" in text
    assert "lacks a `> **Flag:**` tag" not in text


def test_sitrep_routing_table_keys_priority_4a_on_the_record():
    text = _read(SITREP)
    row = next(ln for ln in text.splitlines() if ln.strip().startswith("| 4a "))
    assert "`> **Triaged:**` record" in row
    assert "lacks `> **Flag:**` tag" not in row


# === /sitrep routes on the record (behavioural) =============================


def _survey(batches):
    from datetime import datetime, timezone

    return ss.Survey(
        timestamp=datetime(2026, 8, 3, tzinfo=timezone.utc),
        main_root=Path("/tmp/repo"),
        head_short="abc1234",
        tasks=[],
        review_batches=batches,
        discrepancies=[],
        stale_days=7,
        open_roadmap_ids=[],
    )


def _batch(**overrides):
    defaults = dict(
        batch_number=1, title="Batch 1", md_status="Pending",
        branch="review/batch-1", has_lock=False, has_branch=False,
        has_flag=False, flag_reason="", total_tasks=1, doc_worked_tasks=0,
        state="pending (not claimed)", next_action="",
    )
    defaults.update(overrides)
    return ss.ReviewBatchState(**defaults)


def test_flag_verdict_without_a_flag_line_does_not_route_to_the_cheap_lane():
    """`Triaged:` is the verdict, `Flag:` presence is what the drainers route
    on. A `flag` verdict with no `Flag:` line is malformed and fails toward
    /auto-fix — whose pool test is literally "no Flag: line" — so a batch the
    record says needs judgment would be claimed for mechanical fixing."""
    rec = ss._recommended_next(_survey([
        _batch(batch_number=9, has_flag=False,
               has_triage_record=True, triaged_verdict="flag",
               triaged_tasks=["TASK-601"]),
    ]))
    assert rec.command == "/triage", (
        "a flag verdict with no Flag: line routed onward instead of back to /triage"
    )


def test_batch_next_action_names_the_verdict_pool_conflict():
    batches = [{
        "number": 41, "title": "Conflict", "status": "Pending",
        "branch": "review/batch-41", "flag_reason": "",
        "triaged_date": "2026-08-03", "triaged_verdict": "flag",
        "triaged_tasks": ["TASK-601"],
        "tasks": [{"id": "TASK-601", "checkbox": " "}],
    }]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "_git", lambda *a, **k: "")
        mp.setattr(ss, "_commits_ahead_of_main", lambda *a, **k: [])
        out = ss._classify_review_batches(batches, [], [], Path("/tmp/repo"))
    assert out[0].has_triage_record is False
    assert "malformed record" in out[0].next_action
    assert "/auto-fix would claim it" in out[0].next_action


def test_unstamped_flag_batch_routes_to_triage_not_auto_judge():
    """The reported failure, in the router: a `Flag:` tag of unknown
    provenance used to send the batch straight to `/auto-judge`."""
    rec = ss._recommended_next(_survey([
        _batch(batch_number=7, has_flag=True, flag_reason="looks judgy"),
    ]))
    assert rec.command == "/triage"
    assert any("unstamped Flag:" in d for d in rec.detail_lines)


def test_stamped_flag_batch_routes_to_auto_judge():
    rec = ss._recommended_next(_survey([
        _batch(has_flag=True, flag_reason="needs judgment",
               has_triage_record=True, triaged_verdict="flag"),
    ]))
    assert rec.command == "/auto-judge"
    assert rec.clear_nudge is True


def test_all_auto_triaged_queue_stops_recommending_triage():
    """Pre-fix, an all-auto queue had no `Flag:` tags anywhere, so priority 4a
    matched forever and `/sitrep` recommended `/triage` on every run — the
    verdict had nowhere durable to live."""
    rec = ss._recommended_next(_survey([
        _batch(batch_number=1, has_triage_record=True, triaged_verdict="auto"),
        _batch(batch_number=2, has_triage_record=True, triaged_verdict="auto"),
    ]))
    assert rec.command == "/auto-fix"


def test_mixed_triaged_queue_routes_to_both():
    rec = ss._recommended_next(_survey([
        _batch(batch_number=1, has_triage_record=True, triaged_verdict="auto"),
        _batch(batch_number=2, has_flag=True, flag_reason="judgment",
               has_triage_record=True, triaged_verdict="flag"),
    ]))
    assert rec.command.startswith("/auto-fix")
    assert "concurrent with /auto-judge" in rec.command


def test_untriaged_batch_wins_over_triaged_ones():
    rec = ss._recommended_next(_survey([
        _batch(batch_number=1, has_triage_record=True, triaged_verdict="auto"),
        _batch(batch_number=2),
    ]))
    assert rec.command == "/triage"
    assert rec.detail_lines[0] == "untriaged: batch 2"


def test_batch_next_action_surfaces_the_judgment_fraction():
    """`_classify_review_batches` is the per-batch surface; the fraction is
    what tells a reader the batch is not wholly in the expensive lane."""
    batches = [{
        "number": 5, "title": "Mixed", "status": "Pending",
        "branch": "review/batch-5",
        "flag_reason": "TASK-2: retry semantics",
        "triaged_date": "2026-08-03", "triaged_verdict": "flag",
        "triaged_tasks": ["TASK-2"],
        "tasks": [{"id": f"TASK-{i}", "checkbox": " "} for i in (1, 2, 3, 4)],
    }]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "_git", lambda *a, **k: "")
        mp.setattr(ss, "_commits_ahead_of_main", lambda *a, **k: [])
        out = ss._classify_review_batches(batches, [], [], Path("/tmp/repo"))
    assert len(out) == 1
    assert out[0].triaged_tasks == ["TASK-2"]
    assert "1 of 4 tasks need judgment" in out[0].next_action


def test_batch_next_action_flags_unknown_provenance():
    batches = [{
        "number": 6, "title": "Legacy", "status": "Pending",
        "branch": "review/batch-6",
        "flag_reason": "looks judgy",
        "triaged_date": "", "triaged_verdict": "", "triaged_tasks": [],
        "tasks": [{"id": "TASK-9", "checkbox": " "}],
    }]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "_git", lambda *a, **k: "")
        mp.setattr(ss, "_commits_ahead_of_main", lambda *a, **k: [])
        out = ss._classify_review_batches(batches, [], [], Path("/tmp/repo"))
    assert "/triage will classify" in out[0].next_action
    assert "provenance unknown" in out[0].next_action


# === vacuity controls =======================================================


def test_guarded_files_all_exist():
    for p in (
        TRIAGE, AUTO_FIX, AUTO_JUDGE, SITREP, CODEBASE_REVIEW, SECURITY_AUDIT, WORKFLOW
    ):
        assert p.is_file(), p


def test_queue_reader_set_covers_every_skill_with_a_size_ceiling():
    """Was `len(QUEUE_READERS) == 3` plus an is_file() duplicate — two
    assertions about constants in this file, which cannot fail against any
    state of the tree. Round 2's guard lens named both as vacuous. The real
    property is that the pinned set equals the derived one; that lives in
    `test_the_size_ceiling_population_is_derived_not_assumed`, and this one
    now asserts the tuple is non-empty and file-backed, which is the only part
    that was ever load-bearing."""
    assert QUEUE_READERS
    assert all(p.is_file() for p in QUEUE_READERS)


# === the classify -> recommend join =========================================
#
# THE seam. `_classify_review_batches` was tested only on its `next_action`
# strings and `_recommended_next` only on hand-built `ReviewBatchState`s, so
# nothing fed one into the other. Round 2's guard lens showed the consequence:
# changing one keyword argument in the `ReviewBatchState(...)` construction —
# `has_triage_record=bool(flag_reason)` — restores #337 in full (an unstamped
# `Flag:` batch routes to `/auto-judge` unread) with all 2,674 tests green.
#
# These tests start from bytes on disk and end at a recommendation, so no
# single-layer mutation can satisfy them by construction.


def _route(tmp_path, tracker_text):
    """review_tasks.md on disk -> parse -> classify -> recommend."""
    (tmp_path / "review_tasks.md").write_text(tracker_text, encoding="utf-8")
    batches = ss._read_review_batches(tmp_path)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "_git", lambda *a, **k: "")
        mp.setattr(ss, "_commits_ahead_of_main", lambda *a, **k: [])
        states = ss._classify_review_batches(batches, [], [], tmp_path)
    survey = ss.Survey(
        timestamp=_dt(2026, 8, 3, tzinfo=_tz.utc),
        main_root=tmp_path,
        head_short="abc1234",
        tasks=[],
        review_batches=states,
        discrepancies=[],
        stale_days=7,
        open_roadmap_ids=[],
    )
    return states, ss._recommended_next(survey)


def _tracker(*meta_blocks):
    out = ["## Round 1 — 2026-08-03\n", "\n"]
    for i, meta in enumerate(meta_blocks, start=1):
        out += [f"### Batch {i} — Batch {i} `Pending`\n", "\n"]
        out += [f"> **Branch:** `review/batch-{i}`\n"]
        out += [m + "\n" for m in meta]
        out += ["\n", f"- [ ] **TASK-{i}00**: work \U0001f7e1\n", "\n"]
    return "".join(out)


def test_join_unstamped_flag_routes_to_triage(tmp_path):
    """#337 itself, end to end. A `Flag:` line with no `Triaged:` sibling must
    not reach `/auto-judge` — that is the batch being consumed on the strength
    of a tag nobody wrote a verdict into."""
    states, rec = _route(tmp_path, _tracker(["> **Flag:** looks judgy"]))
    assert states[0].has_triage_record is False
    assert rec.command == "/triage"


def test_join_stamped_flag_routes_to_auto_judge(tmp_path):
    states, rec = _route(
        tmp_path,
        _tracker(["> **Flag:** needs judgment", "> **Triaged:** 2026-08-03 flag [TASK-100]"]),
    )
    assert states[0].has_triage_record is True
    assert states[0].triaged_tasks == ["TASK-100"]
    assert rec.command == "/auto-judge"


def test_join_stamped_auto_routes_to_auto_fix(tmp_path):
    states, rec = _route(tmp_path, _tracker(["> **Triaged:** 2026-08-03 auto"]))
    assert states[0].has_triage_record is True
    assert rec.command == "/auto-fix"


def test_join_untriaged_batch_routes_to_triage(tmp_path):
    _, rec = _route(tmp_path, _tracker([]))
    assert rec.command == "/triage"


def test_join_malformed_records_route_to_triage(tmp_path):
    """Both directions of the verdict/pool conflict, from disk."""
    _, rec = _route(tmp_path, _tracker(["> **Triaged:** 2026-08-03 flag [TASK-100]"]))
    assert rec.command == "/triage"
    _, rec = _route(
        tmp_path, _tracker(["> **Flag:** r", "> **Triaged:** 2026-08-03 auto"])
    )
    assert rec.command == "/triage"


def test_join_mixed_queue_routes_to_both(tmp_path):
    _, rec = _route(
        tmp_path,
        _tracker(
            ["> **Triaged:** 2026-08-03 auto"],
            ["> **Flag:** judgment", "> **Triaged:** 2026-08-03 flag"],
        ),
    )
    assert rec.command.startswith("/auto-fix")
    assert "concurrent with /auto-judge" in rec.command


def test_join_fenced_metadata_does_not_change_the_route(tmp_path):
    """The fence work and the routing work meet here: an example of the record
    quoted inside a batch body must not make an untriaged batch look triaged."""
    text = (
        "## Round 1 — 2026-08-03\n\n"
        "### Batch 1 — Docs `Pending`\n\n"
        "> **Branch:** `review/batch-1`\n\n"
        "- [ ] **TASK-100**: document the shape \U0001f7e1\n\n"
        "> ```markdown\n"
        "> **Flag:** <reason>\n"
        "> **Triaged:** 2026-01-01 flag [TASK-999]\n"
        "> ```\n"
    )
    states, rec = _route(tmp_path, text)
    assert states[0].has_triage_record is False
    assert states[0].has_flag is False
    assert rec.command == "/triage"


def test_json_render_carries_the_triage_record(tmp_path):
    """`/sitrep --json` is a consumer surface; dropping the three keys from
    the render is invisible to every other test."""
    states, _ = _route(
        tmp_path,
        _tracker(["> **Flag:** needs judgment", "> **Triaged:** 2026-08-03 flag [TASK-100]"]),
    )
    row = ss.render_json(
        ss.Survey(
            timestamp=_dt(2026, 8, 3, tzinfo=_tz.utc),
            main_root=tmp_path, head_short="abc1234", tasks=[],
            review_batches=states, discrepancies=[], stale_days=7,
            open_roadmap_ids=[],
        )
    )
    import json as _json

    batch = _json.loads(row)["review_batches"][0]
    assert batch["has_triage_record"] is True
    assert batch["triaged_verdict"] == "flag"
    assert batch["triaged_tasks"] == ["TASK-100"]


def test_triaged_cases_corpus_exercises_every_shape():
    """Was `len(_TRIAGED_CASES) >= 6` — an assertion about a constant in this
    file. Now asserts the corpus actually spans the grammar."""
    verdicts = {c[2] for c in _TRIAGED_CASES}
    assert verdicts == {"auto", "flag"}
    assert any(c[3] for c in _TRIAGED_CASES), "no task-list case"
    assert any(not c[3] for c in _TRIAGED_CASES), "no bare-verdict case"
    assert any(c[0].endswith(" ") for c in _TRIAGED_CASES), "no trailing-space case"
    assert any(" - " in c[0] for c in _TRIAGED_CASES), "no ascii-dash case"
    assert any(" \u2014 " in c[0] for c in _TRIAGED_CASES), "no em-dash case"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
