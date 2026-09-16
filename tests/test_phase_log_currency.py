"""CLAUDE.md's Phase log and the next-session prompt cannot go quietly stale — Phase 194,
item 4.

Two silent-drift sites, both converted into a red suite.

**(a) The unresolved Commit cell.** A phase commits and its table row goes in carrying a
placeholder, because the squash hash does not exist yet. The window is legitimate, the
*lapse* is not — Phase 190's cell sat stale through a merge and was repaired only
incidentally by Phase 191.

**Who closes the window changed at Phase 202, and this guard is why it could.** Roughly 88
phases spent a *dedicated backfill PR* on it — and since `main` requires the `pytest` check,
each one burned a full CI run to write seven characters into one cell. It was never needed:
the two green states below already mean the placeholder may sit on the newest row
indefinitely and reds the instant a *newer* row appears without it being backfilled. So the
backfill now rides the **next phase's own commit**, and this test is the thing that enforces
it. Nothing here changed to allow that; the ceremony was redundant with the assertions all
along.

The filed version of this guard keyed on the literal ``_unmerged_``. That would have shipped
green: ``_unmerged_`` is one of **ten** placeholder forms this column has carried
(``_unmerged_``, ``_PR pending_``, ``_pending_``, ``_pending commit_``, ``_pending merge_``,
``_pending squash_``, ``_squash-merge pending_``, ``_(pending)_``, ``_(pending commit)_``,
``_(this commit)_``) and it is only four commits old, while the one genuinely stale cell in
the file when this was written — row 120's ``_PR pending_``, ~73 rows old — used a different
one. So the guard keys on the **class**: an italic run in the Commit column is an unresolved
cell, whatever words are inside it.

Two states are green: **zero** unresolved cells, and **exactly the highest-numbered row**
unresolved (the legitimate window between a phase's commit and its backfill, including this
phase's own). An older row carrying one is drift.

**(b) The next-session prompt.** ``tools/NEXT_SESSION_PROMPT.md`` is single-use — the phase
that consumes it rewrites it in the same commit. Nothing enforced that, and the failure mode
is a fresh session acting on a superseded brief. The declared phase must be the highest phase
in the table + 1.

Note this makes the prompt a test-read documentation file — the fifth, and relevant to any
future attempt to put a ``paths-ignore`` filter on the required check.

All three files are maintainer-side and excluded from the public mirror, so every test here
skips — explicitly, stating the reason — when one is absent (the Phase 160 lesson: a
sterilized-tree FileNotFoundError reads as a defect and goes red on the public CI).
"""

import pathlib
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
PROMPT = REPO_ROOT / "tools" / "NEXT_SESSION_PROMPT.md"

# A markdown italic run standing ALONE as a `·`-separated segment of the cell. The
# first version was a bare `_[^_]+_`, which the round showed fires on any snake_case
# token — `` | `980c6e7` (#382, `test_doc_currency.py`) | `` reddened two tests. The
# column already carries free prose, so that was latent, not hypothetical: an
# over-strict guard gets deleted rather than fixed.
UNRESOLVED_RE = re.compile(r"(?:^|·)\s*_[^_`]+_\s*(?:$|·)")
# A resolved cell names a commit. Backticks are the house style but not universal — the
# earliest rows write `(in 5076074)` bare — so the pattern is the hash itself.
HASH_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
# Line 1 of the prompt, which declares the phase it briefs. The `Phase (\d+),` shape is
# deliberate: a committed predecessor titled "...after Phase 190's disqualification" would
# false-match a bare `Phase (\d+)` scan, so the number must be followed by the comma that
# separates it from the brief's subtitle.
PROMPT_PHASE_RE = re.compile(r"^#\s+Next-session prompt\s+—\s+Phase (\d+),")
# Not every session is a numbered phase — `tools/ROUND_YIELD_LEDGER.md` records
# `r76-doc-honesty-pass … (docs:, not a numbered phase)`, and this very table carries
# `rename`, `rename 2` and `launch`. The first version reddened the build for any such
# title, which is a behaviour change shipped as a currency guard. This is the opt-out.
PROMPT_UNNUMBERED_RE = re.compile(r"^#\s+Next-session prompt\s+—.*\(not a numbered phase\)")


def _read(path: Path, why: str) -> str:
    if not path.is_file():
        pytest.skip(
            f"{path.name} is maintainer-side and excluded from the public mirror; "
            f"{why} only applies in the source repo"
        )
    return path.read_text(encoding="utf-8")


def _claude_md() -> str:
    return _read(CLAUDE_MD, "the Phase log currency guards")


def _prompt() -> str:
    return _read(PROMPT, "the single-use next-session-prompt guard")


def phase_rows(claude_md: str) -> list[tuple[str, str]]:
    """(row label, Commit cell) for **every** data row of the Phase log table.

    Scoped to the segment from the `## Phase log` heading onward — the table is the last
    thing in the file, but scoping it means a stray pipe-table elsewhere cannot feed rows in.

    **Every row, not just the numerically-labelled ones.** The first version of this parser
    keyed on `^(\\d+)\\s` and skipped **46 of 228 rows** — every letter-suffixed phase (`2A`,
    `2F.1`, `16.1`, `23a`, `42b`, `159a`, `99.1`, …) plus `rename`, `rename 2` and `launch`.
    Its docstring justified that by claiming those are "recorded prose-side"; they are not.
    They sit in this table with Commit cells that rot exactly like any other, and the round's
    guard lens walked `159a`, `rename 2` and Phase 100 straight through with placeholders.
    A parser that silently covers 80% of its population is the defect this module exists for.
    """
    m = re.search(r"^##\s+Phase log\s*$", claude_md, re.M)
    assert m, (
        "the Phase log heading is gone from CLAUDE.md; this guard's anchor needs revisiting"
    )
    rows = []
    for line in claude_md[m.start():].split("\n"):
        if not line.startswith("|"):
            continue
        # Split on unescaped pipes only. A naive `.split("|")` shreds the rows whose
        # prose contains `\\|` (Phase 50 and 153 both quote `|| true` guards), and the
        # first version of this parser read their Commit cell as a lone backslash.
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if len(cells) < 3:
            continue
        label = cells[0]
        if not label or label == "Phase" or set(label) <= set("- :"):
            continue  # header row or the `|---|` separator
        rows.append((label, cells[1]))
    return rows


def numeric_phase(label: str) -> tuple[int, int] | None:
    """`(major, minor)` for a row label, or None for `2A` / `2F.1` / `rename` / `launch`.

    Used to find the newest row — the one allowed to carry a placeholder. A row whose label
    has no leading number can never be the newest, so it is never exempt.

    **Sub-phases were None until Phase 297** (`Q-503`), which meant a `.1` row could never be
    the newest and so could never carry the `_pending merge_` placeholder its own commit has
    to write. Latent rather than observed — `287.1` and `291.1` both landed with their hashes
    already resolved — but it is a false red waiting on the next sub-phase that commits before
    it merges, and this module's whole subject is a record going stale with nothing going red.

    `2F.1` stays None on purpose: the `.` there follows a LETTER-suffixed phase, and letter
    phases are outside every numeric population in this repo's guards. The regex requires the
    optional `.N` to attach directly to the leading digits, so `2F.1` fails at the `F`.
    """
    m = re.match(r"^(\d+)(?:\.(\d+))?(?:\s|$|—)", label)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else None


def unresolved_rows(claude_md: str) -> list[tuple[str, str]]:
    return [(lab, cell) for lab, cell in phase_rows(claude_md) if UNRESOLVED_RE.search(cell)]


def newest_label(claude_md: str) -> str:
    """The label of the highest-numbered row — the only row allowed a placeholder."""
    numbered = [(numeric_phase(lab), lab) for lab, _ in phase_rows(claude_md)]
    return max((n, lab) for n, lab in numbered if n is not None)[1]


def test_only_the_newest_phase_may_have_an_unresolved_commit_cell():
    claude_md = _claude_md()
    newest = newest_label(claude_md)
    stale = [(lab, cell) for lab, cell in unresolved_rows(claude_md) if lab != newest]
    assert not stale, (
        "Phase log rows carrying an unresolved Commit cell that are not the newest phase "
        f"(newest row is {newest!r}):\n"
        + "\n".join(f"  {lab[:60]}: {cell}" for lab, cell in stale)
        + "\n\nBackfill the squash hash — and note WHERE: since Phase 202 the backfill rides "
        "the next phase's own commit, not a dedicated PR, so if you are opening a new phase "
        "row you owe the previous phase's hash in the same edit. Recover it with "
        "`git log --oneline --grep 'Phase <N>'`."
    )


def test_at_most_one_row_is_unresolved():
    """Two placeholders at once means one of them was never backfilled — the window is
    per-phase and closes before the next phase opens its own."""
    unresolved = unresolved_rows(_claude_md())
    assert len(unresolved) <= 1, (
        "more than one Phase log row carries an unresolved Commit cell: "
        + ", ".join(f"{lab[:50]} ({cell})" for lab, cell in unresolved)
    )


def test_every_resolved_cell_actually_carries_a_hash():
    """The positive counterpart the first version lacked.

    `UNRESOLVED_RE` only recognises the *italic* placeholder idiom. A cell reading `TBD`,
    `pending` or an empty string is not italic and was silently accepted as resolved — so
    the guard could only catch the one shape it had already seen. A resolved cell must
    contain a backticked 7+ hex hash.
    """
    bad = [
        (lab, cell)
        for lab, cell in phase_rows(_claude_md())
        if not UNRESOLVED_RE.search(cell) and not HASH_RE.search(cell)
    ]
    assert not bad, (
        "Phase log Commit cells that are neither an italic placeholder nor a backticked "
        "hash — a cell like `TBD` or `pending` reads as resolved to a placeholder-only "
        "check:\n" + "\n".join(f"  {lab[:60]}: {cell!r}" for lab, cell in bad)
    )


def test_the_commit_cell_guard_has_rows_to_see():
    """A green zero-invariant proves its population is empty, not that the class is.

    If the row parser breaks — a table reformat, a heading rename — the guards above pass
    vacuously over nothing. This is the floor that says so. The threshold is set against
    the **whole** table (228 rows when written), not the numeric subset: a floor derived
    from the same narrowing it is meant to detect cannot detect it, which is exactly how
    the 46-row blind spot survived the first version of this module.
    """
    rows = phase_rows(_claude_md())
    assert len(rows) >= 220, (
        f"only {len(rows)} phase rows parsed from CLAUDE.md's Phase log; the table has not "
        "shrunk, so the row parser has stopped matching its shape"
    )
    assert all(cell for _, cell in rows), "a Commit cell parsed as empty"
    # 48 before Phase 297, 42 after: `numeric_phase` now parses the six dot-suffixed labels
    # that already existed (`5.1`, `16.1`, `99.1`, `109.1`, `287.1`, `291.1`), so those moved
    # out of this set. `288.1`, which this phase ADDED, arrives already numbered and does not
    # move it further — the count is 42 and not 41 for that reason.
    # The floor stays 40 because the remainder is FROZEN — the
    # letter-suffixed phases, `2A`-style labels, `rename` and `launch` are all historical, and
    # a new sub-phase adds a NUMBERED row rather than shrinking this set further.
    unnumbered = [lab for lab, _ in rows if numeric_phase(lab) is None]
    assert len(unnumbered) >= 40, (
        f"only {len(unnumbered)} non-numerically-labelled rows seen; the parser has "
        "regressed to the numeric-only form that skipped 46 rows"
    )


def test_the_next_session_prompt_briefs_the_next_phase():
    claude_md = _claude_md()
    line1 = _prompt().split("\n", 1)[0]
    # Phase form FIRST. `PROMPT_UNNUMBERED_RE`'s `.*` is unanchored, so a numbered
    # brief whose subtitle merely quotes "(not a numbered phase)" — this repo writes
    # about its own conventions constantly — matches the opt-out too. Whichever regex
    # is asked first wins, and the opt-out returning early disabled the check outright.
    m = PROMPT_PHASE_RE.match(line1)
    if not m and PROMPT_UNNUMBERED_RE.match(line1):
        return  # explicitly declared a non-phase session; nothing to keep in step
    assert m, (
        "tools/NEXT_SESSION_PROMPT.md line 1 does not declare its phase. Expected "
        "`# Next-session prompt — Phase <N>, <subtitle>`, or a title ending "
        "`(not a numbered phase)` for a session that is not one; got:\n"
        f"  {line1[:140]}"
    )
    declared = int(m.group(1))
    # `[0]` — the MAJOR. The brief after `296.1` is Phase 297, not `297.1`: a sub-phase is a
    # correction to the phase below it, so the next phase counts from the major. Before
    # Phase 297 `numeric_phase` returned a bare int and a `.1` newest row returned None,
    # which would have raised `TypeError` here rather than computing the wrong number.
    expected = numeric_phase(newest_label(claude_md))[0] + 1
    assert declared == expected, (
        f"tools/NEXT_SESSION_PROMPT.md briefs Phase {declared}, but the next phase is "
        f"{expected}. The file is single-use: the phase that consumes it rewrites it in the "
        "same commit, so a stale copy means a fresh session is about to act on a superseded "
        "brief."
    )


# Commit cells legitimately cite OTHER repositories: row 4 records `BeanRider `0caa843``,
# and the `launch` row records `public `1760d61`` from the getsysop/sysop mirror. Those
# hashes cannot resolve here and must not be checked — the first version of the resolver
# below flagged both, which is the over-strictness direction all over again.
FOREIGN_REPO_MARKERS = ("beanrider", "public", "tester", "gdp", "getsysop", "upstream")


def own_repo_hashes(cell: str) -> list[str]:
    """Hashes in `cell` that should resolve in THIS repo.

    A cell is `·`-separated; a segment naming another repository contributes none.
    """
    out = []
    for segment in cell.split("·"):
        low = segment.lower()
        if any(marker in low for marker in FOREIGN_REPO_MARKERS):
            continue
        out += HASH_RE.findall(segment)
    return out


def test_no_phase_number_appears_twice_in_the_table():
    """A duplicated row — the shape a botched backfill or a bad rebase leaves — passes
    every cell-level check, because each copy is individually well-formed."""
    labels = [lab for lab, _ in phase_rows(_claude_md())]
    dupes = sorted({lab for lab in labels if labels.count(lab) > 1})
    assert not dupes, f"Phase log rows appearing more than once: {dupes}"


def test_every_commit_hash_in_the_table_resolves():
    """Shape is not existence. `HASH_RE` accepts any 7-40 hex run, so a cell reading
    `` `0000000` `` — a typo, a hash from a rebased-away commit, a copy-paste of the wrong
    line — reads as resolved. This is the one check that can tell the difference."""

    # CI checks out with `actions/checkout` at its default `fetch-depth: 1`, so the runner
    # has ONE commit and every historical hash fails to resolve. A local checkout is full
    # and every one resolves — an environment-dependent guard, green for the author and red
    # for everyone else. None of this round's three lenses ran under CI conditions, so the
    # required check found it after the review did not. Skip explicitly, stating the reason
    # (the Phase 160 lesson), rather than degrading to a silent pass.
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if shallow.returncode != 0:
        pytest.skip("not a git checkout; hash resolution is not checkable here")
    if shallow.stdout.strip() == "true":
        pytest.skip(
            "shallow clone (CI checks out at fetch-depth 1) — history is absent, so a "
            "hash that fails to resolve here says nothing about whether it is real"
        )

    bad = []
    for lab, cell in phase_rows(_claude_md()):
        for h in own_repo_hashes(cell):
            r = subprocess.run(["git", "cat-file", "-e", f"{h}^{{commit}}"],
                               cwd=REPO_ROOT, capture_output=True)
            if r.returncode != 0:
                bad.append((lab, h))
    assert not bad, (
        "Phase log Commit cells naming commits that do not exist in this repo:\n"
        + "\n".join(f"  {lab[:60]}: {h}" for lab, h in bad)
    )


# ─────────────────────────────────────────────────────────────────────────────
# (c) The brief must dispose of every filing the phase before it left open.
#
# `Q-419`, leg 1, mechanized after the procedural fix failed a fourth time. A brief
# names the filings its phase made; four times now (Phases 264, 267, and — in the
# brief that carried `Q-419`'s own warning about population claims — 269) it named
# fewer than it filed, so the next session ranked a four-item tail as two or three.
#
# **Why "appears in the brief" is not the check.** Phase 269's brief DID contain the
# string `Q-444` — in the very sentence claiming all four were ranked. A whole-file
# grep passes on the defect. The discriminator is *disposition*: a ranked item lives
# in a list item (or a table row); a merely-mentioned one sits in a paragraph. That
# is the difference between a brief that hands the next session a decision and one
# that hands it a name.
#
# **Deliberately not required to START the item.** Phase 269's own ranking bullets
# carry two ids each — `Q-408`/`Q-410` and `Q-441`/`Q-443` — so a start-anchored
# rule would have reddened on two correctly-ranked entries. That is the
# over-strictness direction this module's `UNRESOLVED_RE` comment already names as
# the way a guard gets deleted rather than fixed.
#
# **The limit, stated rather than left to be discovered.** The population is derived
# from entries that say `by Phase <N>` in their own body. 174 of 250 open entries did at Phase 270's close;
# the rest record provenance in free prose (`Filed by main-session/<date>`), and no
# pattern recovers a filing phase that was never written down. So this narrows the
# class, it does not close it — an entry filed by phase N-1 that omits the phase is
# still invisible here, and `test_the_filing_phase_population_is_not_vacuous` below
# is what keeps a *parser* regression from looking like that same absence.
CHECKLIST = REPO_ROOT / "REVIEW_CHECKLIST.md"

OPEN_ENTRY_RE = re.compile(r"^- \[ \] <!-- id: (Q-\d+) -->(.*)$", re.M)
FILED_BY_PHASE_RE = re.compile(r"by Phase (\d+)")
LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def _checklist() -> str:
    return _read(CHECKLIST, "the brief's filing-disposition guard")


def open_entries_filed_by(checklist: str, phase: int) -> list[str]:
    """Ids of still-open entries whose body records `by Phase <phase>`.

    Reads the queue file itself — the source of truth the brief's own
    `Derive, don't read` block points at — rather than any curated list.
    """
    out = []
    for qid, body in OPEN_ENTRY_RE.findall(checklist):
        if any(int(n) == phase for n in FILED_BY_PHASE_RE.findall(body)):
            out.append(qid)
    return out


def disposition_text(prompt: str) -> str:
    """The brief's list items and table rows, joined.

    A list item runs from its marker to the next marker, blank line or heading, so an
    id named on a bullet's *continuation* line counts — bullets here wrap at ~95 cols
    and routinely carry their second id on line 2. Table rows count as well: nothing
    ranks in a table today, but a guard that reds on a legal reformat is one that gets
    deleted, so the shape is admitted in advance.
    """
    chunks, in_item, fenced, blank_before = [], False, False, True
    for raw in prompt.splitlines():
        line = re.sub(r"^\s*>\s?", "", raw)          # briefs are written blockquoted
        # An id inside an HTML comment is invisible to a reader, so it disposes of
        # nothing — and a comment sitting under a bullet was being read as that
        # bullet's continuation text (round lens 3, B2).
        line = HTML_COMMENT_RE.sub("", line)
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            # The brief ships a `Derive, don't read` bash block. A `- ` line inside a fence
            # is shell, not a ranking, and counting it would let an id be "disposed of" by
            # sitting in a command comment. BOTH fence characters: keying on backticks
            # alone left `~~~` counting as prose (round lens 3, B5).
            fenced = not fenced
            in_item = False
            continue
        if fenced:
            continue
        if not stripped or stripped.startswith("#"):
            in_item = False
            blank_before = not stripped
            continue
        # An indented code block is 4+ spaces after a blank line and cannot interrupt a
        # list item. A deeply-nested bullet is also indented — but it FOLLOWS its parent,
        # so `in_item` is live and it is kept (round lens 3, B4). The pair of conditions
        # is what separates them; indentation alone would reject legal nesting.
        if not in_item and blank_before and len(line) - len(line.lstrip(" ")) >= 4:
            blank_before = False
            continue
        blank_before = False
        if stripped.startswith("|"):
            chunks.append(line)
            in_item = False
            continue
        if LIST_MARKER_RE.match(line):
            in_item = True
            chunks.append(line)
        elif in_item:
            chunks.append(line)
    return "\n".join(chunks)


def test_the_brief_ranks_every_filing_the_previous_phase_left_open():
    prompt, checklist = _prompt(), _checklist()
    line1 = prompt.split("\n", 1)[0]
    m = PROMPT_PHASE_RE.match(line1)          # phase form first — see the sibling guard
    if not m and PROMPT_UNNUMBERED_RE.match(line1):
        return  # a non-phase session files nothing under a phase number
    assert m, "line 1 does not declare its phase; test_the_next_session_prompt_briefs_the_next_phase owns that message"
    briefed = int(m.group(1))
    filed = open_entries_filed_by(checklist, briefed - 1)
    if not filed:
        return  # a phase may legitimately file nothing
    disposed = disposition_text(prompt)
    # `q in disposed` would be substring containment, and `Q-44` sits inside `Q-441` —
    # a two-digit id in the population would be satisfied by any three-digit id sharing
    # its prefix. The trailing `(?!\d)` is what makes the match the id and not a prefix.
    missing = [q for q in filed
               if not re.search(re.escape(q) + r"(?!\d)", disposed)]
    assert not missing, (
        f"tools/NEXT_SESSION_PROMPT.md briefs Phase {briefed}, but Phase {briefed - 1} left "
        f"these filings open without disposing of them in the brief: {', '.join(missing)}.\n"
        "Naming an id in a paragraph is not disposition — put it in a list item (or a table "
        "row), even one that says it is deferred and not ranked. A brief that names a filing "
        "without ranking it hands the next session a four-item tail it will read as two "
        "(`Q-419`, three instances: Phases 264, 267 and 269 — Phase 266 got it right).\n"
        f"Filed by Phase {briefed - 1} and still open: {', '.join(filed)}"
    )


def test_the_filing_phase_population_is_not_vacuous():
    """The guard above passes silently when its population is empty.

    So this asserts the population *exists* across the file. A regex that stops matching
    entry bodies — a heading reflow, a provenance rewording — would otherwise turn the
    disposition guard into a no-op that reports green, which is the failure mode the
    whole module was written for.
    """
    checklist = _checklist()
    entries = OPEN_ENTRY_RE.findall(checklist)
    assert len(entries) >= 100, (
        f"only {len(entries)} open queue entries parsed; the entry parser has stopped "
        "matching the file's shape (the queue has carried >200 for many phases)"
    )
    with_phase = [q for q, b in entries if FILED_BY_PHASE_RE.search(b)]
    # PROPORTIONAL, not a flat floor. The first version asked for >= 50 against a live
    # population of 174, which tolerated losing 71% of it — so the round reworded 60
    # provenances (this docstring's own named regression) and the control stayed green.
    # A share is what actually detects a vocabulary drift, because the denominator moves
    # with the queue.
    share = len(with_phase) / len(entries)
    assert share >= 0.55, (
        f"only {len(with_phase)} of {len(entries)} open entries ({share:.0%}) record a "
        "filing phase; the `by Phase <N>` provenance convention has drifted and this "
        "guard's population went with it. It has run at ~70% since Phase 270"
    )


def test_the_disposition_parser_sees_the_briefs_list_items():
    """Non-vacuity for the other half: an extractor that returns nothing passes everything.

    A flat line-count floor did not do this job — the first version asked for >= 5 against
    a brief that yields ~36, so the round truncated the ranking to four bullets and it
    stayed green. This instead asserts FIDELITY: every list-marker line the brief actually
    contains outside a fence must survive into the disposed text. A parser that starts
    dropping items reds on the first one it drops, whatever the brief's size.
    """
    prompt = _prompt()
    disposed = disposition_text(prompt)
    fenced, expected = False, []
    for raw in prompt.splitlines():
        line = HTML_COMMENT_RE.sub("", re.sub(r"^\s*>\s?", "", raw))
        if line.strip().startswith("```") or line.strip().startswith("~~~"):
            fenced = not fenced
            continue
        # An INDEPENDENT marker pattern, written out here rather than reusing
        # LIST_MARKER_RE. Sharing the constant would make this control blind to the one
        # regression it most needs to see: a change to that regex moves the oracle and
        # the subject together, and the check stays green while items go missing.
        if not fenced and re.match(r"^ *(?:[-*+]|[0-9]+[.)]) +\S", line):
            expected.append(line)
    assert expected, (
        "the brief contains no list items at all; a brief is written as blockquoted "
        "bullets, so this means the parser — or the brief — changed shape"
    )
    dropped = [l for l in expected if l not in disposed]
    assert not dropped, (
        f"disposition_text dropped {len(dropped)} of {len(expected)} list items the brief "
        f"actually contains; first dropped: {dropped[0][:100]!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# (d) A merged phase has a PHASE_LOG.md section.
#
# `Q-503`. This module is named for `PHASE_LOG.md` and, until Phase 297, never opened
# it: every guard above reads `CLAUDE.md`'s table or the next-session prompt. So the
# **prose** half of a phase's record — the half `CLAUDE.md`'s close-out convention names
# first, and the only place the "why we made this call" narrative lives — was enforced by
# memory alone, which is what Phase 154 ruled is not a mechanism.
#
# **The cost was measured before this was written, not after.** Phase 287.1 shipped with
# no prose entry and no ledger row; Phase 288 found it, wrote the missing record, wrote
# down the regex reason, and did not fix the detector. Eight and a half hours later Phase
# 291.1 shipped
# with no record in any of the three places and nothing went red; Phase 293 wrote that one
# too. Phase 297 then found a THIRD, which no brief had named: **Phase 288.1** (`af75a58`,
# #642) was merged to `main` with no `PHASE_LOG.md` section, no `CLAUDE.md` row and no
# ledger row. It had sat unrecorded for two days in the one window where every other guard
# in the tree was green.
#
# **The population comes from `git log`, and it has to.** The obvious cheaper source is
# `CLAUDE.md`'s own table — no subprocess, no history dependence. It is also exactly the
# source that could not see `288.1`, because a phase that never wrote its table row is
# absent from the table. Deriving the population from the artefact under audit is the
# `_shared/adversarial-review.md` rule-1 "where it looks" failure, and this guard is a
# worked instance of why: the table and the log go stale together, by the same slip, in
# the same commit that forgets.
#
# **No newest-phase carve-out, and none is needed.** The sibling ledger guard exempts the
# newest row because a ledger row records a round that has not run yet. A `PHASE_LOG.md`
# section has no such dependency — the convention is that the prose is written BEFORE the
# round, which is what lets the round review it — and the population here is the DEFAULT
# BRANCH, so a phase in flight is not in it at all. The window the other guards have to
# carve out does not exist here.
PHASE_LOG = REPO_ROOT / "PHASE_LOG.md"

# The oldest phase this repo's commit subjects name in any of the three forms below. Below it
# the inherited history carries the extraction's gdp subjects, so there is no population to
# derive; raising it above 53 IS a policy choice about which phases deserve a record, and is
# how you would abandon one.
#
# **This was 65 and the reason given for it was false — the round's record lens.** 65 is the
# oldest *prefix-form* subject, which was the only form the first version could see. Under the
# three-form population the oldest is 53, and Phases 53, 63 and 64 are ordinary Sysop phases,
# not the extraction's gdp history. They were silently outside the demanded set while a comment
# said no such set existed. All three carry `## Phase <N>` sections, so widening the floor
# costs nothing and closes three phases the guard was written to cover.
PHASE_LOG_BINDS_FROM = 53

# A guard is only as real as the history it can see, and this one reads history through a
# subprocess that answers cheerfully with nothing. `actions/checkout` takes its default
# `fetch-depth: 1` unless told otherwise; on a depth-1 clone `git log` yields ONE subject,
# every phase in the derived population has a heading, and the guard reports green over a
# repository it never looked at. `.github/workflows/tests.yml` sets `fetch-depth: 0` for
# this guard — this floor is what goes red if that is ever removed, instead of the guard
# quietly becoming decorative.
#
# **It counts MATCHING SUBJECTS, not distinct phases**, and the first version's comment said
# 231 (the distinct count) while the assertion compared 332 — a floor that read as tight and
# carried 107 of slack. The round's record lens measured it. 335 matching subjects at
# authoring against 231 distinct phases; a floor, so it only ever rises, and set close enough
# that a regression to the single prefix form (200 subjects) also reddens.
#
# **A hand-set constant is the weaker half and is not alone.** Editing this to 0 disarms it,
# so `test_the_derived_population_covers_the_phase_log_table` cross-checks the same question
# against a second live source — `CLAUDE.md`'s own table — which no edit to this number can
# satisfy.
MERGED_SUBJECT_FLOOR = 325

# `main`, then `origin/main` for CI, where `actions/checkout` leaves a detached HEAD on the
# PR merge ref and the local branch may not exist. HEAD is deliberately NOT a fallback: on
# a PR it carries the phase's own unmerged commits, so the guard would demand a section for
# a phase that has not merged — the false red the "default branch" population avoids.
DEFAULT_BRANCH_REFS = ("main", "origin/main")
# Pinned, because the sentence above was an invariant nothing enforced: the round's guards
# measured `DEFAULT_BRANCH_REFS = ("HEAD",)` running GREEN with Phase 297's own unmerged
# commits in the population. The author-side battery had dismissed that mutation as a no-op
# "because HEAD is `main`" — true on `main`, and the battery runs on the phase branch, where
# it is not. A survivor mislabelled as a no-op is worse than a survivor.
assert "HEAD" not in DEFAULT_BRANCH_REFS, (
    "HEAD is not a default-branch ref. On a phase branch it carries the phase's own unmerged "
    "commits, so the guard would demand a PHASE_LOG.md section for a phase that has not "
    "merged — and 'merged' is the whole population this guard is defined over."
)

# **This repo names a phase in its commit subject four different ways, and the first version
# of this guard could see one.** The `Phase <N>:` prefix is today's convention, and a
# bare `^Phase (\d+)` scan over the default branch returns 175 subjects — which looks like
# the whole population until you notice it starts at 126. Phases 66 through 125 used
# conventional-commit subjects with the number in a trailing parenthetical
# (`feat(skills): strip the identifier leak (Phase 66) (#7)`), so ~60 merged phases were
# silently outside the population and the floor's own comment read as if they were in it.
# Found by this phase's author-side battery, by the rule-1 "where it looks" check. There are
# THREE forms, not two — the third is a conventional-commit SCOPE (`docs(phase-190): …`),
# which is how Phase 190's own commit names itself and the only way that phase enters the
# population at all. 175 subjects with the prefix alone, 205 with the trailing parenthetical,
# **231** with all three. A guard whose population is an artefact of one writing style is the
# defect this module exists for, one altitude up.
#
# **All three are ANCHORED**, and the round's guards lens is why. The trailing forms were
# `\(Phase (\d+)\)` and `\(phase-(\d+)\)` with no anchor, so an ordinary subject that MENTIONS a
# phase — `docs: cross-reference the approach rejected in (Phase 999)` — minted a demand for a
# phase that never merged and reddened three arms with a message asserting it had. This repo
# writes about its own phase numbers constantly: 38 subjects already carry `(Phase ` and 103
# carry `(phase-`. The parenthetical form must therefore END the subject (an optional trailing
# `(#NNN)` PR reference is the house style), and the scope form must be a conventional-commit
# scope, which by definition sits before the first `:`.
# The prefix form is case-INSENSITIVE and letter-tolerant, both measured. Phases 95–98 wrote
# `phase 95: …` in lower case, and `Phase 159a:` defeats a `\b` because there is no word
# boundary between `9` and `a` — so five merged phases (95, 96, 97, 98, 159) sat outside the
# population while the comment below claimed three forms covered it. Found by the round's
# execution lens. Widening gains exactly those five and zero false reds: every one already
# has a `## Phase <N>` section.
_SUBJECT_PHASE_RES = (
    re.compile(r"^phase (\d+)(?:\.(\d+))?[a-z]?\b", re.I),
    re.compile(r"\(Phase (\d+)(?:\.(\d+))?\)(?:\s*\(#\d+\))*\s*$"),
    re.compile(r"^[a-z]+\(phase-(\d+)(?:\.(\d+))?\):"),
)

# The floor for the CROSS-SOURCE arm below, which is a different question from
# `PHASE_LOG_BINDS_FROM`. Phase 94 landed under a subject that names no phase number in any
# form, so demanding that every table row appear in the git population is only true above it.
#
# **This was 126, and the reason given was false twice over.** The comment said phases 94–98
# "name no phase number in any form" — true of 94 alone; 95–98 use a lower-case prefix the
# regexes now admit. And it claimed the exception set is empty only from 126, when it is
# empty from 95. Both halves found by the round. The floor at 126 excluded 29 table rows the
# arm can now cover, every one of them in the form-2 population that `MERGED_SUBJECT_FLOOR`
# is too slack to backstop.
CROSS_SOURCE_BINDS_FROM = 95

# The cross-source arm's own non-vacuity floor. 202 table rows fall in range at authoring.
CROSS_SOURCE_TABLE_FLOOR = 195

# A section emptied to its heading is not a record. Shortest live body is 538 chars.
PHASE_LOG_MIN_BODY = 300


def _phase_log() -> str:
    return _read(PHASE_LOG, "the merged-phase record guard")


def prose_only(markdown: str) -> str:
    """`markdown` with fenced blocks and HTML comments blanked, line structure preserved.

    The first version matched headings over the raw file, and the round's guards lens walked
    it twice: a `## Phase 290 …` line inside a ```` ```markdown ```` example block satisfied
    the demand for Phase 290 after its real section was deleted, and so did the heading
    wrapped in `<!-- … -->`. This repo has paid for fence-awareness three times already
    (Phases 275, 281, 291); a guard reading `PHASE_LOG.md` — a file whose whole subject is
    quoting markdown — had no business reading it raw.

    Lines are blanked rather than removed so that every surviving line keeps its position and
    `(?m)^` still means what it says.
    """
    out, fence, in_comment = [], None, False
    for line in markdown.split("\n"):
        stripped = line.lstrip()
        if in_comment:
            out.append("")
            if "-->" in line:
                in_comment = False
            continue
        if fence is None and stripped.startswith("<!--") and "-->" not in line:
            in_comment = True
            out.append("")
            continue
        info = _fence_marker(stripped)
        if fence is not None:
            out.append("")
            # A closer is the marker ALONE, at least as long as the opener, with no info
            # string — CommonMark's rule, and the reason the first version desynchronised.
            if info and info[0] == fence[0] and info[1] >= fence[1] and not info[2]:
                fence = None
            continue
        if info:
            fence = info
            out.append("")
            continue
        out.append(line)
    return "\n".join(out)


def _fence_marker(stripped: str) -> tuple[str, int, str] | None:
    """`(char, run length, info string)` if `stripped` is a fence line, else None.

    **The discriminator is the info string**, and the first version did not have one: it
    treated any line beginning with three backticks as a fence, so this file's own prose —
    which quotes markdown constantly — desynchronised the state machine. The live instance
    was an INLINE code span, ``` `Sampled`, not `Full` ```, whose stripped form starts with
    three backticks and is not a fence at all. It swallowed 1,465 lines; 13 such spans
    between them hid **41** real `## Phase` headings, and the guard reported all 41 as
    missing records. A parser that manufactures 41 false reds is worse than the hole it closes.

    CommonMark: a backtick fence's info string may not contain a backtick. That one rule
    separates the inline span from the fence.
    """
    m = re.match(r"^(`{3,}|~{3,})(.*)$", stripped)
    if not m:
        return None
    run, info = m.group(1), m.group(2).strip()
    # A real fence's info string is a single language tag. Anything with whitespace or a
    # backtick in it is PROSE that happens to begin with the marker — either an inline code
    # span (``` `Sampled`, not `Full` ```) or a sentence that wrapped onto a line starting
    # with one (``` merely splits the outer block into two empty ones…). Both are live in
    # `PHASE_LOG.md`; measured, all six such lines in the file are prose and none is a fence,
    # and between them they hid 41 then 29 real `## Phase` headings from two earlier cuts of
    # this parser. CommonMark would open a fence on the second shape, so this is deliberately
    # stricter than the spec, for a file whose subject is quoting markdown.
    if info and (" " in info or "`" in info):
        return None
    return (run[0], len(run), info)


def _ref_exists(ref: str) -> bool:
    return subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                          cwd=REPO_ROOT, capture_output=True).returncode == 0


def _default_branch_ref() -> str:
    for ref in DEFAULT_BRANCH_REFS:
        if _ref_exists(ref):
            return ref
    raise AssertionError(
        "none of " + ", ".join(DEFAULT_BRANCH_REFS) + " resolves in this checkout, so the "
        "merged-phase population cannot be derived. This is a FAILURE and not a skip on "
        "purpose: CLAUDE.md is present, so this is the source repo, and a guard that "
        "silently stands down here is the inert-gate shape `Q-503` exists to close. If CI "
        "reaches this, `actions/checkout` is no longer fetching refs."
    )


def _refuse_a_stale_default_branch(ref: str) -> None:
    """`main` behind `origin/main` truncates the population at the NEWEST end, silently.

    The round's guards lens measured it: pointing the resolver at `main~4` and deleting a
    phase's section left every arm green, because the cross-source arm bounds the table by
    `max(merged)` — derived from the same truncated population — so end-truncation is
    self-consistent. Depth truncation is caught (it removes the OLDEST commits, which the
    cross-source arm can see); this is the direction that is not.

    Only checked when `origin/main` exists and is ahead, which is exactly the "you forgot to
    pull" state `CLAUDE.md` already tells sessions to avoid. A missing remote is not an error.
    """
    if ref != "main" or not _ref_exists("origin/main"):
        return
    if subprocess.run(["git", "merge-base", "--is-ancestor", "origin/main", "main"],
                      cwd=REPO_ROOT, capture_output=True).returncode == 0:
        return
    behind = subprocess.run(["git", "rev-list", "--count", "main..origin/main"],
                            cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    raise AssertionError(
        f"local `main` is {behind} commit(s) behind `origin/main`, so the merged-phase "
        "population is truncated at its newest end and every arm in this module is "
        "self-consistent over the shorter history. `git fetch` first — this is a stale "
        "checkout, not a record defect."
    )


def merged_phase_labels() -> list[str]:
    """Phase labels taken from commit subjects on the default branch, newest first.

    Subjects, not the table. Both of Phase 296's squash commits — `Phase 296 (pre-cut): …`
    and `Phase 296 (cut): …` — reduce to the same label, so this returns labels rather than a
    set keyed to commits.
    """
    ref = _default_branch_ref()
    _refuse_a_stale_default_branch(ref)
    log = subprocess.run(["git", "log", "--format=%s", ref],
                         cwd=REPO_ROOT, capture_output=True, text=True)
    assert log.returncode == 0, f"`git log {ref}` failed: {log.stderr.strip()[:200]}"
    labels = _labels_from(log.stdout)
    # **Every arm that reads history inherits the floor, because the floor is a property of
    # the population and not of one test.** The first version asserted it inside
    # `test_every_merged_phase_has_a_phase_log_section` only, and the round measured the
    # consequence on a real `fetch-depth: 1` checkout WITH a default branch — the CI shape —
    # where the level arm and the vacuity control both ran GREEN over a one-commit
    # population. Two of four arms certifying a repository they never read is the inert-gate
    # shape `Q-503` exists to close, shipped inside the fix for it.
    assert len(labels) >= MERGED_SUBJECT_FLOOR, (
        f"only {len(labels)} phase-naming commit subjects derived from `{ref}`, against a "
        f"floor of {MERGED_SUBJECT_FLOOR}. The POPULATION is what broke, not the record: "
        "`actions/checkout` takes its default `fetch-depth: 1` unless told otherwise, and on "
        "a depth-1 clone this is 1. Every guard in this module that reads history would "
        "otherwise pass over a repository it never looked at."
    )
    return labels


def _labels_from(log_stdout: str) -> list[str]:
    labels = []
    for subject in log_stdout.splitlines():
        subject = subject.strip()
        m = next((r.search(subject) for r in _SUBJECT_PHASE_RES if r.search(subject)), None)
        if not m:
            continue
        major, minor = int(m.group(1)), int(m.group(2) or 0)
        if major < PHASE_LOG_BINDS_FROM:
            continue
        labels.append(f"{major}.{minor}" if minor else str(major))
    return labels


def phase_log_heading_re(label: str) -> re.Pattern:
    """`## Phase 296` at the start of a line — not `## Phase 296.1`, not `## Phase 296xx`.

    The negative lookahead is the whole point. A bare `^## Phase 296\\b` is satisfied by a
    `## Phase 296.1 (…)` heading — `\\b` sits happily before a `.` — so an integer phase with
    no section of its own would be certified by its sub-phase's.

    **The first version used `(?![\\d.])`, and this phase's own battery killed it.** That
    blocks a digit or a dot and admits everything else, so `## Phase 296xx` satisfied the
    demand for Phase 296 — the "what it accepts" failure class. `(?![\\w.])` blocks any word
    character.

    **`[a-z]?` is a real shape, not slack.** Phase 65's record is `## Phase 65a` and
    `## Phase 65b` while its commit subject says `Phase 65:` — the letter-part convention this
    repo used through `23a`, `159a`, `61b`. A single letter part satisfies the integer's
    demand; two characters do not.

    Three heading levels are accepted where the convention says two, because Phase 136's
    section shipped under `###` and a guard that cannot see it reports a missing record where
    a misfiled one is what happened; `test_every_merged_phase_section_uses_a_level_two_heading`
    keeps the level itself honest.
    """
    return re.compile(rf"(?m)^#{{2,3}} Phase {re.escape(label)}[a-z]?(?![\w.])")


def test_every_merged_phase_has_a_phase_log_section():
    """The guard `Q-503` asks for: a phase on the default branch has prose in PHASE_LOG.md."""
    _claude_md()  # skips in the public mirror, where CLAUDE.md is stripped
    phase_log = prose_only(_phase_log())
    labels = merged_phase_labels()   # asserts the population floor for every arm
    missing = [lab for lab in labels if not phase_log_heading_re(lab).search(phase_log)]
    assert not missing, (
        f"phases merged to the default branch with no `## Phase <N>` section in "
        f"PHASE_LOG.md: {sorted(set(missing))}. PHASE_LOG.md is the single source of truth "
        "for the 'why we made this call' narrative and CLAUDE.md's close-out convention "
        "names it first; a phase that merged without one has lost that record silently, "
        "which is how Phases 287.1, 288.1 and 291.1 each went unnoticed until a human\n"
        "happened to read for something else."
    )


def test_every_merged_phase_section_uses_a_level_two_heading():
    """The level, separately from the presence — so each failure names its own defect.

    Phase 136's section shipped under `###`. `phase_log_heading_re` accepts two or three so
    a misfiled section is not reported as an absent one, and this arm is what stops that
    tolerance from silently becoming the convention.
    """
    _claude_md()
    phase_log = prose_only(_phase_log())
    misfiled = [lab for lab in merged_phase_labels()
                if not re.search(rf"(?m)^## Phase {re.escape(lab)}[a-z]?(?![\w.])", phase_log)
                and phase_log_heading_re(lab).search(phase_log)]
    assert not misfiled, (
        f"PHASE_LOG.md sections filed under `###` instead of `## `: {sorted(set(misfiled))}. "
        "The section is there, so no record is lost — but `## ` is what every reader and "
        "every sibling guard keys on."
    )


def test_the_merged_phase_guard_would_notice_an_absent_section():
    """The non-vacuity control, driving the REAL predicate over a mutated log.

    Asserting only that today's population is green proves nothing about whether the
    matcher can fail. Each of the three arms below removes one thing and must be caught.
    """
    _claude_md()
    phase_log = prose_only(_phase_log())
    labels = merged_phase_labels()
    assert labels, "no merged phases derived; the arms below would prove nothing"

    newest = labels[0]
    without = phase_log_heading_re(newest).sub("## Phase REMOVED", phase_log)
    assert not phase_log_heading_re(newest).search(without), (
        f"the fixture did not actually remove Phase {newest}'s heading; this control is "
        "testing nothing"
    )

    # A sub-phase heading must NOT satisfy its integer's demand — the `\\b`-lookahead case.
    integer_only = re.sub(rf"(?m)^(#{{2,3}} Phase {re.escape(newest)})(?![\w.])",
                          r"\1.9", phase_log)
    assert not phase_log_heading_re(newest).search(integer_only), (
        f"`## Phase {newest}.9` satisfied the demand for Phase {newest} — the lookahead is "
        "gone, and an integer phase can be certified by a sub-phase's section"
    )

    # A longer number-plus-letters run is NOT the phase. This arm is the one the first
    # version of the matcher failed: with `(?![\d.])` the heading `## Phase 296xx` satisfied
    # the demand for Phase 296, so renaming a section to anything non-numeric read as a
    # record. Found by this phase's own battery (M01), not by a reviewer.
    suffixed = phase_log_heading_re(newest).sub(f"## Phase {newest}xx", phase_log)
    assert not phase_log_heading_re(newest).search(suffixed), (
        f"`## Phase {newest}xx` satisfied the demand for Phase {newest} — the lookahead "
        "blocks digits and dots but admits letters, so a substring counts as a record"
    )

    # A SINGLE letter part does satisfy it, and must: Phase 65's record is `## Phase 65a`
    # and `## Phase 65b` while its commit subject says `Phase 65:`. Over-strictness here
    # would report the repo's own oldest convention as a missing record.
    lettered = phase_log_heading_re(newest).sub(f"## Phase {newest}a", phase_log)
    assert phase_log_heading_re(newest).search(lettered), (
        f"`## Phase {newest}a` no longer satisfies Phase {newest} — the letter-part shape "
        "this repo used through `23a`, `65a` and `159a` now reads as an absent record"
    )

    # And the matcher is anchored: a mid-line mention is not a section.
    mention = phase_log_heading_re(newest).sub(f"see also ## Phase {newest} above", phase_log)
    assert not phase_log_heading_re(newest).search(mention), (
        f"a mid-line mention of `## Phase {newest}` satisfied the matcher; it is no longer "
        "anchored to the start of a line and any prose reference counts as a record"
    )


def test_the_derived_population_covers_the_phase_log_table():
    """The non-vacuity check that is DERIVED rather than hand-set.

    `MERGED_SUBJECT_FLOOR` is a constant, so it can be edited to 0 and the population check
    becomes decorative — battery case M08, which survived the first version of this module.
    This asks the same question against a second live source: every plain phase `CLAUDE.md`'s
    table lists from `CROSS_SOURCE_BINDS_FROM` up to the newest MERGED phase must appear in
    the git-derived population. On a depth-1 clone that population is one subject and this
    fails with 170-odd names, which is what the floor alone only promises.

    Bounded above by the newest merged label on purpose: a phase in flight has its table row
    but not its commit on the default branch, and demanding it here would redden every phase
    at exactly the moment its own round reads the suite.
    """
    _claude_md()
    merged = set(merged_phase_labels())
    assert merged, "no merged phases derived; this arm would prove nothing"
    newest = max(_label_key(lab) for lab in merged)

    table = {}
    for label, _cell in phase_rows(_claude_md()):
        key = numeric_phase(label)
        if key and (CROSS_SOURCE_BINDS_FROM, 0) <= key <= newest:
            table[_fmt_key(key)] = label

    # Non-vacuity, inline: `CROSS_SOURCE_BINDS_FROM = 99999` or `if key and False` both left
    # this arm green over an empty `table`, because it only ever asserted that `merged` was
    # non-empty. Both measured by the round's guards lens, in the arm the record had named as
    # the derived answer to a hand-set floor.
    assert len(table) >= CROSS_SOURCE_TABLE_FLOOR, (
        f"only {len(table)} CLAUDE.md phase rows fall in [{CROSS_SOURCE_BINDS_FROM}, "
        f"{_fmt_key(newest)}] — this arm is comparing the git population against almost "
        "nothing, which passes for the same reason an empty set has no missing members"
    )
    unmerged = sorted(set(table) - merged, key=_label_key)
    assert not unmerged, (
        f"{len(unmerged)} phase(s) have a CLAUDE.md Phase-log row but no commit subject on "
        f"the default branch: {unmerged[:12]}. Either the history this guard reads is "
        "truncated — a shallow clone makes this list ~170 long — or a row names a phase that "
        "never merged."
    )


def _label_key(label: str) -> tuple[int, int]:
    major, _, minor = label.partition(".")
    return (int(major), int(minor or 0))


def _fmt_key(key: tuple[int, int]) -> str:
    return f"{key[0]}.{key[1]}" if key[1] else str(key[0])


def test_the_guard_reads_every_merged_phase_not_just_the_newest():
    """The BREADTH of the loop, which nothing pinned.

    The round's execution lens narrowed the loop to `labels[:1]` — check only the newest
    merged phase — and the module stayed green. The non-vacuity control drives
    `phase_log_heading_re` over a mutated log using `labels[0]` alone, so it proves the
    MATCHER can fail and says nothing about how many phases are checked. A guard reduced to
    "the newest phase has a section" could not have found Phase 288.1, which is this phase's
    entire product.

    Two independent old phases, chosen from opposite ends of the population so that a loop
    truncated at either end is reported.
    """
    _claude_md()
    phase_log = prose_only(_phase_log())
    labels = merged_phase_labels()
    for probe in (labels[-1], labels[len(labels) // 2]):
        without = phase_log_heading_re(probe).sub("## Phase REMOVED", phase_log)
        missing = [lab for lab in labels if not phase_log_heading_re(lab).search(without)]
        assert probe in missing, (
            f"Phase {probe} is in the derived population but removing its heading is not "
            "reported — the loop is not reading every phase it derived"
        )


def test_a_heading_alone_is_not_a_record():
    """The guard says "prose"; it was checking a heading line.

    The round's guards lens deleted Phase 290's entire body — **326 lines, 23,303
    characters** — left the heading standing, and the module stayed green. The failure
    message tells an operator the phase "has lost that record silently"; the remedy it
    prescribes was satisfiable by one line.

    The floor is deliberately low. The shortest live section body is 538 characters, so 300
    reports an emptied section without dictating how much a phase must write — over-strictness
    here would redden a legitimately terse record, which is the direction that gets guards
    deleted rather than fixed.
    """
    _claude_md()
    phase_log = prose_only(_phase_log())
    heads = [(m.group(0), m.start()) for m in
             re.finditer(r"(?m)^## Phase [0-9][^\n]*", phase_log)]
    assert len(heads) >= 200, f"only {len(heads)} sections parsed; the section parser broke"
    thin = []
    for i, (head, start) in enumerate(heads):
        end = heads[i + 1][1] if i + 1 < len(heads) else len(phase_log)
        body = phase_log[start + len(head):end].strip()
        if len(body) < PHASE_LOG_MIN_BODY:
            thin.append(f"{head[:48]} — {len(body)} chars")
    assert not thin, (
        "PHASE_LOG.md sections with a heading and (almost) no prose under it:\n  "
        + "\n  ".join(thin)
        + "\n\nThe heading is the index; the prose is the record. A section emptied to its "
        "heading passes every other arm in this module."
    )


def test_an_unresolvable_default_branch_fails_rather_than_skips():
    """The property `_default_branch_ref`'s own message insists on, enforced by nothing.

    The round's execution lens replaced its `raise AssertionError` with `pytest.skip` and the
    module went from `4 failed` to `9 passed, 5 skipped` — silent green — with the full suite
    on a normal tree unaffected, because the branch is never reached there. A docstring that
    says "this is a FAILURE and not a skip on purpose" and is enforced by nothing is the
    inert-gate shape applied to itself.
    """
    import ast
    src = ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(src)
              if isinstance(n, ast.FunctionDef) and n.name == "_default_branch_ref")
    raises = [n for n in ast.walk(fn) if isinstance(n, ast.Raise)]
    skips = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "skip"]
    assert raises and not skips, (
        "`_default_branch_ref` no longer RAISES when no default branch resolves. A skip "
        "there stands the whole merged-phase guard down silently in exactly the checkout "
        "where it is most needed — its own message says so, and until Phase 297's round "
        "nothing held it to that."
    )
