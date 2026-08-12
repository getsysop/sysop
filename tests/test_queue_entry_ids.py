"""Every queue entry carries a stable ID anchor — Phase 194, item 8.

The queue had no addressable items, so every handoff cited entries by *line number* —
a reference that rots on the next insertion. Phase 194's own brief cited five entries
that way, and by the time it was executed the file had already moved under two of them.
The fix is one anchor per entry, assigned once and never renumbered.

Three properties, and the third is the one that makes the convention hold by
construction rather than by discipline:

1. **Every entry line carries an anchor.** Partial coverage is worse than none: a
   missing anchor would mean either "old entry" or "someone forgot", and a reader
   cannot tell which.
2. **No ID is ever issued twice** — across BOTH files, because a resolved entry keeps
   its ID when it moves to the archive. Deriving the next ID from the checklist alone
   would reuse the ones that have already left.
3. **The ID does not encode priority.** An entry that moves § Medium -> § High keeps
   its ID, because otherwise the reference rots on precisely the event that makes it
   worth referencing. In-repo precedent: `tasks/` IDs are kind-prefixed (`TECH-0007`),
   never status-prefixed. Priority is the section heading's job.

Both files are maintainer-side and excluded from the public mirror, so every test here
skips — explicitly, stating the reason — when either is absent (the Phase 160 lesson: a
sterilized-tree FileNotFoundError reads as a defect and goes red on the public CI).
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKLIST = REPO_ROOT / "REVIEW_CHECKLIST.md"
ARCHIVE = REPO_ROOT / "REVIEW_ARCHIVE.md"

# An entry line. Anchored at column 0 — every entry in both files is a top-level list
# item; the indented continuation lines that four entries carry are not entries.
# `[X]` as well as `[x]`: the round's execution lens filed an entry with an uppercase
# tick and it took no anchor and reddened nothing — a guard that defines its own
# population narrowly enough will always report full coverage of it.
ENTRY_RE = re.compile(r"^\s*[-*+] \[[ xX]\] ")
# The anchor, and where it must sit: immediately after the checkbox, same line.
ANCHORED_RE = re.compile(r"^\s*[-*+] \[[ xX]\] <!-- id: (Q-\d{3}) --> ")
# Any anchor, anywhere — used for the cross-file uniqueness sweep.
ANY_ID_RE = re.compile(r"<!--\s*id:\s*(Q-\d{3})\s*-->", re.I)


def _read(path: Path, why: str) -> str:
    if not path.is_file():
        pytest.skip(
            f"{path.name} is maintainer-side and excluded from the public mirror; "
            f"{why} only applies in the source repo"
        )
    return path.read_text(encoding="utf-8")


def _checklist() -> str:
    return _read(CHECKLIST, "the queue-ID guard")


def _archive() -> str:
    return _read(ARCHIVE, "the cross-file ID-uniqueness guard")


def entry_lines(text: str) -> list[tuple[int, str]]:
    """(1-indexed line number, line) for every entry line."""
    return [
        (n, ln)
        for n, ln in enumerate(text.split("\n"), start=1)
        if ENTRY_RE.match(ln)
    ]


def unanchored(text: str) -> list[tuple[int, str]]:
    return [(n, ln) for n, ln in entry_lines(text) if not ANCHORED_RE.match(ln)]


def ids_in(text: str) -> list[str]:
    return ANY_ID_RE.findall(text)


def test_every_checklist_entry_carries_an_id_anchor():
    """The coverage property. A new entry filed without an anchor reddens here."""
    missing = unanchored(_checklist())
    assert not missing, (
        "REVIEW_CHECKLIST.md entries with no `<!-- id: Q-NNN -->` anchor "
        "immediately after the checkbox:\n"
        + "\n".join(f"  :{n}  {ln[:110]}" for n, ln in missing)
        + "\n\nAssign the next unused ID — derive max+1 over BOTH REVIEW_CHECKLIST.md "
        "and REVIEW_ARCHIVE.md, since a resolved entry keeps its ID when it moves."
    )


def test_the_guard_has_entries_to_see():
    """A zero-invariant proves its population is empty, not that the class is.

    If the entry regex ever stops matching — a reformat, a heading change — the
    coverage test above passes vacuously over nothing. This is the floor that says so.
    """
    entries = entry_lines(_checklist())
    assert len(entries) >= 100, (
        f"only {len(entries)} entry lines matched in REVIEW_CHECKLIST.md; the queue has "
        "not shrunk that far, so ENTRY_RE has stopped matching the file's shape"
    )


def test_no_id_is_issued_twice_within_the_checklist():
    found = ids_in(_checklist())
    dupes = sorted({i for i in found if found.count(i) > 1})
    assert not dupes, f"duplicate IDs in REVIEW_CHECKLIST.md: {dupes}"


def test_no_id_is_shared_between_the_checklist_and_the_archive():
    """IDs are never reused. A resolved entry carries its ID into the archive, so an ID
    appearing in both files means one was minted from a checklist-only max."""
    live = set(ids_in(_checklist()))
    resolved = set(ids_in(_archive()))
    collision = sorted(live & resolved)
    assert not collision, (
        f"IDs present in both REVIEW_CHECKLIST.md and REVIEW_ARCHIVE.md: {collision}. "
        "These were minted twice — derive the next ID as max+1 over both files."
    )


def test_ids_do_not_encode_priority():
    """The format is flat and monotonic: `Q-` plus three digits, nothing else.

    A priority-bearing ID (`H-012`, `MED-004`) would have to change when an entry is
    re-sorted, which is the one event that makes the reference worth having.
    """
    text = _checklist()
    stray = sorted(
        set(re.findall(r"<!-- id: ([^>]*?) -->", text)) - set(ids_in(text))
    )
    assert not stray, (
        f"ID anchors not matching the flat `Q-NNN` form: {stray}. Priority lives in the "
        "section heading, never in the ID — an entry that moves § Medium -> § High "
        "keeps its ID."
    )


def test_anchors_sit_on_the_entry_line_not_their_own():
    """Same-line is structural, not cosmetic: an anchor on its own line would split the
    markdown list, and the four entries that carry indented continuation lines would
    become ambiguous about which block the anchor belongs to."""
    orphans = [
        n
        for n, ln in enumerate(_checklist().split("\n"), start=1)
        if ANY_ID_RE.search(ln) and not ENTRY_RE.match(ln)
    ]
    assert not orphans, (
        f"ID anchors on lines that are not entry lines: {orphans}. The anchor goes "
        "immediately after the checkbox, on the same line."
    )


# --------------------------------------------------------------------------------------
# Added by Phase 194's own round. Each of these closes a defect an independent reviewer
# demonstrated green against the first version of this module.
# --------------------------------------------------------------------------------------


def test_no_id_is_ever_renumbered():
    """**The property the whole convention exists for, and the first version asserted it
    nowhere.** Uniqueness, flat form and same-line placement were all checked; *stability*
    was not. Swapping two IDs, or bumping `Q-170` to `Q-999`, satisfied every one of them
    and silently rotted every `Q-NNN` reference in every handoff — the exact failure this
    was built to end. Compares each entry's ID against the same entry at `main`.
    """
    import subprocess

    base = subprocess.run(
        ["git", "show", "main:REVIEW_CHECKLIST.md"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if base.returncode != 0:
        # CI checks out at `fetch-depth: 1`, so `main` is absent there and this guard is
        # effectively LOCAL-ONLY — it protects the maintainer's own close-out, not the
        # required check. Stated rather than implied: a renumbering pushed straight to a
        # PR without a local run would not be caught here.
        pytest.skip("no `main` ref to compare against (shallow clone or detached history)")

    def id_by_body(text: str) -> dict[str, str]:
        out = {}
        for _, line in entry_lines(text):
            m = ANCHORED_RE.match(line)
            if m:
                out[line[m.end():][:120]] = m.group(1)
        return out

    before, after = id_by_body(base.stdout), id_by_body(_checklist())
    moved = {
        body: (before[body], after[body])
        for body in before.keys() & after.keys()
        if before[body] != after[body]
    }
    assert not moved, (
        "entries whose ID changed since `main` — IDs are assigned once and never "
        "renumbered, because every handoff that cites one rots the moment it moves:\n"
        + "\n".join(f"  {was} -> {now}: {body[:80]}" for body, (was, now) in moved.items())
    )


def test_the_archive_side_of_the_uniqueness_check_is_not_vacuous():
    """`REVIEW_ARCHIVE.md` holds 285 entry lines and, at the time of writing, one ID. The
    cross-file guard therefore compared 172 live IDs against a population of size 1 — and
    stripping that single anchor, or one character of case drift, emptied it and turned the
    check green. A zero-invariant proves its population is empty, not that the class is;
    this module already says so about the checklist and had no equivalent for the archive.

    The floor is 1 rather than a large number on purpose: the archive gains IDs only as
    entries resolve, so a high threshold would be a false failure for many phases. What it
    forbids is the population reaching **zero** while entries with IDs are still moving in.
    """
    archive = _archive()
    resolved_here = re.findall(r"^##\s+Resolved — Phase 194", archive, re.M)
    if not resolved_here:
        pytest.skip("no Phase-194 archive section; the floor below is scoped to it")
    assert len(ids_in(archive)) >= 1, (
        "REVIEW_ARCHIVE.md carries no ID anchors at all, yet entries have been archived "
        "with them — the cross-file uniqueness guard is comparing against an empty set "
        "and would pass on any collision."
    )
