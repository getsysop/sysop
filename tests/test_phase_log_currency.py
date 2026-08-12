"""CLAUDE.md's Phase log and the next-session prompt cannot go quietly stale — Phase 194,
item 4.

Two silent-drift sites, both converted into a red suite.

**(a) The unresolved Commit cell.** A phase commits, its table row goes in carrying a
placeholder, and a follow-up PR backfills the squash hash. Roughly 88 phases have had a
dedicated backfill commit; the window is legitimate, the *lapse* is not — Phase 190's cell
sat stale through a merge and was repaired only incidentally by Phase 191.

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
        + "\n\nBackfill the squash hash. The placeholder window is legitimate only between a "
        "phase's own commit and its backfill."
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
    if PROMPT_UNNUMBERED_RE.match(line1):
        return  # explicitly declared a non-phase session; nothing to keep in step
    m = PROMPT_PHASE_RE.match(line1)
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
