"""Every file a phase entry cites must still exist — Phase 245, `Q-267` in part.

WHAT THIS GUARDS, AND WHAT IT DELIBERATELY DOES NOT.

`tests/test_intra_repo_citations.py` excludes `PHASE_LOG.md` entirely. That
exclusion is not an oversight; it is a measurement, recorded in that module's
own docstring. A phase entry's job is to cite the line it changed, so the line
stops holding that content BY DESIGN, and an anchor guard over the phase log is
high-false-positive by construction.

Phase 245 re-derived the population against the tree, because the figure in that
docstring was stale and the entry it justifies was being reasoned about from it:

    405 unique citations   386 unambiguous   15 ambiguous   4 dangling

counting distinct ``(target, start, end)`` triples. Note the sweep below keys on
``(target, start)`` and so sees **401** — the two figures differ by four
range-citations that share a start. Stated because the round's guards lens
caught the docstring quoting one population while the code measured another;
the ambiguous count is **15** under either basis.

and found a HARD blocker for un-excluding the file wholesale. Fifteen citations
name a bare basename that resolves to many files — ``SKILL.md`` matches 23,
``README.md`` matches 4 — and that module's
``test_no_registered_citation_is_ambiguous`` REFUSES to register an ambiguous
citation, deliberately (its round finding M6). So there is no legal registry
entry for those fifteen. Un-excluding the file would require either editing
fifteen historical entries or weakening that refusal.

So this module guards the sub-property that IS both checkable and honest: **the
cited file still exists.** A phase citing a file that has since been deleted or
renamed is a broken pointer with no stale-by-design defence — the content moved
house, not just down the page. It needs no anchors, is untouched by the
ambiguity refusal (a bare ``SKILL.md`` resolves to 23 files, which is >= 1 and so
passes), and it is not vacuous: it already names six real ones.

LINE DRIFT IS EXPLICITLY NOT GATED. A cited line past the end of the file today
is recorded in ``KNOWN_OUT_OF_RANGE`` with its reason rather than asserted away,
because after Phase 49 split ``run_checks_impl.py`` into a package the surviving
shim is 93 lines and two perfectly accurate historical citations point past it.
New ones redden; the named two do not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_intra_repo_citations import (
    CITATION,
    REPO_ROOT,
    _is_foreign,
    _resolve,
    _tracked,
)

PHASE_LOG = REPO_ROOT / "PHASE_LOG.md"

#: The sterilized-mirror sentinel. NOT the file this module reads — which is the
#: whole reason this guard needed a shape of its own.
#:
#: The sibling modules' idiom keys the skip on the absence of the file they READ
#: (`tools/ROUND_YIELD_LEDGER.md`, `REVIEW_CHECKLIST.md`). That does not reach
#: here: `PHASE_LOG.md` **ships**, so this module runs happily on the mirror while
#: part of what the log cites has been stripped out from under it. Measured on
#: a mirror built from `74f85f8`: 24 citation sites across 15 targets — `CLAUDE.md`,
#: `REVIEW_CHECKLIST.md`, `REVIEW_ARCHIVE.md`, `tools/*`, `make_public_mirror.sh`,
#: `mutation_battery.py` — resolve in the source repo and not in the snapshot, so
#: `test_every_cited_file_still_exists` FAILED there while the source repo was green.
#: `.github/workflows/tests.yml` ships, so that is public `main`'s required check
#: going red on a tree nobody can fix from the mirror.
#:
#: `tests/test_mirror_skip_discipline.py` could not have caught it and says so: it
#: matches a module's *textual* path construction, and this module reaches those
#: files through `git ls-files` plus citation resolution. Its stated limit — "a
#: module that reaches an excluded file through a computed path … is outside what
#: this can see" — was exercised for the first time by this module. Constructing
#: the sentinel path below puts this module inside that guard's population, so the
#: skip is now enforced rather than merely present.
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"


@pytest.fixture(autouse=True)
def _source_repo_only():
    """Every gate here is a claim about the SOURCE repo's tracked set.

    Module-wide rather than per-test, and autouse rather than a `skipif` mark, for
    two separate reasons. Module-wide: five of these tests are population-dependent
    (the two real-tree gates, the allowlist sweep, the non-vacuity floors, and the
    pinned ambiguous count), and leaving the other six running on the mirror would
    ship a module that reports six green tests about a property it is no longer
    checking — the "inert rather than gating" shape `TESTER_MIRROR_RUNBOOK.md`
    warns about at Pass 5. Autouse: a new test added to this module inherits the
    skip instead of having to remember it at RUNTIME.

    **Two qualifications the round added, because the first draft stated the second
    reason as a virtue and the first without limit.**

    *It does not cover collection.* A fixture runs at setup, so a future test whose
    `parametrize` decorator reads a stripped path errors the ENTIRE module on the
    mirror — all eleven tests included — before any fixture runs. Demonstrated by
    execution: one such test turned a clean skip into 14 collection errors. Nothing
    like it exists here today, so this is a latent limit rather than a live defect,
    and the adjacent guard's own failure message already names the case ("as a
    collection ERROR if the read happens inside a decorator"). Read at collection,
    guard at collection.

    *And `pytest.mark.skipif` is the tidier spelling that the repo's own guard
    refuses.* It is behaviourally equivalent here and it does not contain the literal
    `pytest.skip` that `tests/test_mirror_skip_discipline.py:128` asserts on, so it
    reddens. That is a fact about the guard's substring test, not a virtue of
    fixtures, and stating it as a reason to prefer autouse got the direction wrong.
    Filed on `Q-357`.
    """
    if not CLAUDE_MD.is_file():
        pytest.skip(
            "CLAUDE.md is absent, so this is the sterilized public mirror rather "
            "than the source repo. PHASE_LOG.md ships but the paths it cites into "
            "CLAUDE.md, REVIEW_CHECKLIST.md and tools/ do not; the citation-target "
            "guards only apply in the source repo"
        )

#: Cited paths that name no repo file on purpose. Same role as the sibling
#: module's UNRESOLVED_ALLOWED: a named debt, not a silence.
ALLOWED_DANGLING = {
    "src/api/danger.py": "invented path in a prose example of a semgrep finding",
    "src/plain/d.py": "invented path in the same prose example",
    "sysop/scripts/run_checks/semgrep.py": (
        "consumer-side installed path, not a repo path — the repo copy is "
        "core/companion/scripts/run_checks/semgrep.py"
    ),
    "test_review_receipt_gate.py": (
        "the Phase 155 receipt gate, built and reverted unmerged by its own "
        "round; the module never landed and the entry says so"
    ),
}

#: Citations whose line number is past the end of the file as it stands today.
#: Accurate when written; the file shrank under them.
KNOWN_OUT_OF_RANGE = {
    ("run_checks_impl.py", 164): "pre-Phase-49 monolith; the shim is now 93 lines",
    ("run_checks_impl.py", 378): "pre-Phase-49 monolith; the shim is now 93 lines",
}


def _phase_log_citations():
    """(cited_target, start, citing_line_number) for each citation in the log."""
    found = []
    for lineno, line in enumerate(
        PHASE_LOG.read_text(encoding="utf-8").splitlines(), 1
    ):
        for m in CITATION.finditer(line):
            if _is_foreign(line, m.start()):
                continue
            found.append((m.group(1), int(m.group(2)), lineno))
    return found


def broken_citations(citations, tracked, allowed=ALLOWED_DANGLING):
    """Citations naming a file that does not exist and is not allow-listed.

    Extracted from the gate so a fixture can reach it. The round showed why:
    mutating the gate's CALL SITE (resolving on a bare basename) survived,
    because the only test of that behaviour poked `_resolve` directly and never
    ran the predicate the gate actually uses.
    """
    return [
        (target, start, lineno)
        for target, start, lineno in citations
        if not _resolve(target, tracked) and target not in allowed
    ]


def out_of_range_citations(citations, tracked, pinned=KNOWN_OUT_OF_RANGE):
    """Citations pointing past the end of the single file they resolve to."""
    lengths: dict[str, int] = {}
    offenders = []
    for target, start, lineno in citations:
        resolved = _resolve(target, tracked)
        if len(resolved) != 1:
            continue
        rel = resolved[0]
        if rel not in lengths:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
            lengths[rel] = len(text.splitlines())
        if start > lengths[rel] and (target, start) not in pinned:
            offenders.append((target, start, lengths[rel], lineno))
    return offenders


def test_every_cited_file_still_exists():
    tracked = _tracked()
    broken = broken_citations(_phase_log_citations(), tracked)
    assert not broken, (
        "PHASE_LOG.md cites files that no longer exist in the tree. A phase "
        "entry may legitimately cite a line that has moved; it may not cite a "
        "file that is gone. Either restore the path, or add it to "
        "ALLOWED_DANGLING with the reason:\n"
        + "\n".join(
            f"  PHASE_LOG.md:{lineno} -> {target}:{start}"
            for target, start, lineno in sorted(broken)[:20]
        )
    )


def test_no_new_citation_points_past_the_end_of_its_file():
    tracked = _tracked()
    offenders = out_of_range_citations(_phase_log_citations(), tracked)
    assert not offenders, (
        "PHASE_LOG.md cites a line past the end of the file as it stands. "
        "That is gross drift, not the ordinary stale-by-design kind:\n"
        + "\n".join(
            f"  PHASE_LOG.md:{lineno} -> {target}:{start} (file is {size} lines)"
            for target, start, size, lineno in sorted(offenders)[:20]
        )
    )


def test_the_allowlists_do_not_hide_a_path_that_exists():
    """A named debt that quietly came good is a stale exemption."""
    tracked = _tracked()
    live = sorted(t for t in ALLOWED_DANGLING if _resolve(t, tracked))
    assert not live, (
        f"these are allow-listed as dangling but now resolve: {live}. "
        "Remove the entry rather than leaving a dead exemption."
    )
    lengths = {}
    healed = []
    for (target, start), _reason in KNOWN_OUT_OF_RANGE.items():
        resolved = _resolve(target, tracked)
        if len(resolved) != 1:
            continue
        rel = resolved[0]
        lengths.setdefault(
            rel,
            len((REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace").splitlines()),
        )
        if start <= lengths[rel]:
            healed.append(f"{target}:{start}")
    assert not healed, (
        f"these are pinned as out-of-range but are now in range: {healed}"
    )


def test_the_sweep_is_not_vacuous():
    """The gates above pass trivially if the sweep finds nothing."""
    citations = _phase_log_citations()
    assert len(citations) > 300, (
        f"only {len(citations)} citations swept from PHASE_LOG.md — the regex or "
        "the path is wrong, and both gates above would be passing on an empty set"
    )
    tracked = _tracked()
    resolving = [c for c in citations if _resolve(c[0], tracked)]
    assert len(resolving) > 250, (
        f"only {len(resolving)} of {len(citations)} citations resolve at all"
    )


def test_the_existence_check_fires_on_a_planted_dangling_citation():
    """Non-vacuity, against the real resolver rather than a stub."""
    tracked = _tracked()
    assert not _resolve("core/companion/scripts/no_such_file_here.py", tracked)
    assert _resolve("install.sh", tracked)


def test_a_bare_ambiguous_basename_still_counts_as_existing():
    """The fifteen ambiguous citations must PASS this module, not blow it up.

    They are why the sibling module cannot take PHASE_LOG.md at all. Here the
    question is only "does the cited file exist", and a name matching 23 files
    plainly does.
    """
    tracked = _tracked()
    assert len(_resolve("SKILL.md", tracked)) > 1
    assert Path(_resolve("SKILL.md", tracked)[0]).name == "SKILL.md"


# --------------------------------------------------------------------------
# Findings from the adversarial round's guards lens. Each closes a survivor.
# --------------------------------------------------------------------------


def test_the_sweep_covers_the_whole_file_not_just_the_head():
    """A sweep truncated to the first half still cleared both floors.

    Measured by the round: reading 50% of the file yields 317 citations and 315
    resolving, against floors of >300 and >250 — so the entire tail could vanish
    undetected. Break-even was ~43%. This pins coverage to the file's extent
    rather than to a count.
    """
    lines = PHASE_LOG.read_text(encoding="utf-8").splitlines()
    citations = _phase_log_citations()
    assert citations
    furthest = max(lineno for _, _, lineno in citations)
    assert furthest > len(lines) * 0.85, (
        f"the furthest citation the sweep found is at line {furthest} of "
        f"{len(lines)} — the sweep is not reading the end of the file"
    )


def test_resolution_is_by_PATH_suffix_not_by_bare_basename():
    """`_resolve` matched on `target.split('/')[-1]` survived the battery.

    Under a basename-only rule any citation whose FILENAME exists anywhere
    passes, so a wrong directory is invisible. The original non-vacuity fixture
    could not see it: its planted name failed under both readings.
    """
    tracked = _tracked()
    assert _resolve("install.sh", tracked), "sanity: the real file resolves"
    # Run the GATE's predicate, not `_resolve` alone: the round's survivor was a
    # mutation of the call site, invisible to a test that poked the helper.
    planted = [("no/such/dir/install.sh", 1, 1)]
    assert broken_citations(planted, tracked), (
        "the existence predicate accepted a path whose directory does not exist "
        "anywhere in the tree — it is matching on the basename alone"
    )
    assert not broken_citations([("install.sh", 1, 1)], tracked)


def test_the_dangling_allowlist_matches_exactly_not_by_suffix():
    """A suffix-matching allowlist silently widens every exemption."""
    for allowed in ALLOWED_DANGLING:
        assert f"prefix/{allowed}" not in ALLOWED_DANGLING
    probe = "attacker/src/plain/d.py"
    assert probe not in ALLOWED_DANGLING, (
        "membership must be exact; a path merely ENDING with an allow-listed "
        "one must not inherit its exemption"
    )


def test_the_out_of_range_gate_has_no_slop():
    """A `+ 50` tolerance on the bound survived — no near-miss fixture existed."""
    tracked = _tracked()
    rel = _resolve("install.sh", tracked)[0]
    size = len((REPO_ROOT / rel).read_text(encoding="utf-8").splitlines())
    # Pin BOTH sides of the boundary through the gate's own predicate, so a
    # tolerance added to the comparison reddens.
    assert out_of_range_citations([("install.sh", size + 1, 1)], tracked), (
        "a citation one line past EOF was not flagged — the bound has slop"
    )
    assert not out_of_range_citations([("install.sh", size, 1)], tracked), (
        "a citation at the last line must be in range"
    )


def test_the_ambiguous_citations_are_exempt_from_BOTH_gates_and_that_is_recorded():
    """15 citations resolve to many files and are skipped by the drift gate.

    The docstring disclosed this for the existence gate only. Recording it for
    the line-drift gate too, and pinning the count so it cannot grow silently.
    """
    tracked = _tracked()
    ambiguous = {
        (t, s) for t, s, _ in _phase_log_citations() if len(_resolve(t, tracked)) > 1
    }
    assert len(ambiguous) == 15, (
        f"{len(ambiguous)} ambiguous citations (was 15). These are exempt from "
        "the line-drift gate by construction — if the count moved, a new "
        "unguarded citation was added or one was disambiguated."
    )
