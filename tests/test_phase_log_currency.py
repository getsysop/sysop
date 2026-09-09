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

import re
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


def numeric_phase(label: str) -> int | None:
    """The leading integer of a row label, or None for `2A` / `rename` / `launch`.

    Used only to find the newest row — the one allowed to carry a placeholder. A row whose
    label has no leading integer can never be the newest, so it is never exempt.
    """
    m = re.match(r"^(\d+)(?:\s|$|—)", label)
    return int(m.group(1)) if m else None


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
    expected = numeric_phase(newest_label(claude_md)) + 1
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
    import subprocess

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
