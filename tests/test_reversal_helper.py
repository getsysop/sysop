"""The reversal layer's own properties, tested directly (Phase 253, `Q-367`).

`tests/_reversal.py` shipped in Phase 249 with no test of its own: its properties were
exercised only through callers whose shipped text is clean, and a clean slice cannot
tell a working helper from one that never fires. Every test here runs the helper
against a fixture built to trip it, so a weakened helper reddens here before a
softened skill walks through a caller.

Each test names the mutation it exists to kill. The list is the author-side battery
for the helper (`tools/phase253_mutations.py` `H-*` rows), written before the battery
ran.
"""
from __future__ import annotations

import pytest
from pathlib import Path

import re

from _reversal import REVERSAL_VOCAB, assert_no_reversal, slice_between

CLEAN = (
    "### 4b. Close Merged Batches\n"
    "Run the script with the flag. The flag is not optional under `pr`, and the\n"
    "target is stated rather than inferred.\n"
)


def test_a_clean_step_passes():
    assert_no_reversal(CLEAN, "fixture")


@pytest.mark.parametrize("phrase", REVERSAL_VOCAB)
def test_every_generic_entry_fires_on_its_own(phrase):
    """Kills: an entry silently dropped from the tuple, and a `hits` list that is
    computed and never asserted."""
    with pytest.raises(AssertionError, match="reversal vocabulary"):
        assert_no_reversal(CLEAN + f"In short, the step {phrase}.\n", "fixture")


def test_matching_is_case_insensitive():
    """Kills: dropping `.lower()` on the haystack. Phase 249's round reopened a kill
    by capitalising `In practice` at the start of a sentence."""
    with pytest.raises(AssertionError):
        assert_no_reversal(CLEAN + "In Practice, leave it.\n", "fixture")


def test_extra_vocabulary_is_honoured():
    """Kills: an `extra=` parameter that is accepted and ignored — the shape that
    would silently retire every step-specific entry the Step 4b guard passes."""
    text = CLEAN + "You may leave the flag off.\n"
    assert_no_reversal(text, "fixture")  # generic list alone does not see it
    with pytest.raises(AssertionError, match="leave the flag off"):
        assert_no_reversal(text, "fixture", extra=("leave the flag off",))


def test_an_exempt_span_is_stripped_before_the_scan():
    """The one legitimate use: the step cites a refused alternative by name."""
    text = CLEAN + "(*advisory only* was considered and refused.)\n"
    assert_no_reversal(text, "fixture", exempt=("*advisory only* was considered and refused",))


def test_a_stale_exemption_fails():
    """Kills: dropping the presence assertion on `exempt`. A phrase that matches
    nothing widens what the guard permits without anyone noticing."""
    with pytest.raises(AssertionError, match="exemption"):
        assert_no_reversal(CLEAN, "fixture", exempt=("this phrase is not in the step",))


def test_a_duplicated_exemption_fails():
    """Kills: relaxing `count == 1` back to `in`. `str.replace` strips every
    occurrence, so a second copy of the exempted phrase is a second hole — Phase
    248's round wrote a reversal AROUND an exempted span and walked through."""
    cite = "*advisory only* was refused"
    text = CLEAN + f"({cite}.) Under `pr` the flag is {cite}, so skip it.\n"
    with pytest.raises(AssertionError, match="occurs 2 times"):
        assert_no_reversal(text, "fixture", exempt=(cite,))


def test_a_reversal_outside_the_exempt_span_still_fires():
    """Kills: stripping the whole step instead of the span, or scanning `step`
    rather than the stripped haystack."""
    cite = "*advisory only* was refused"
    text = CLEAN + f"({cite}.) In practice the check is advisory only.\n"
    with pytest.raises(AssertionError, match="reversal vocabulary"):
        assert_no_reversal(text, "fixture", exempt=(cite,))


def test_extra_entries_match_case_insensitively_too():
    """Kills: lowering the haystack but not the vocabulary entry (round: C-H05 —
    an `extra=` entry written in title case would never match)."""
    with pytest.raises(AssertionError, match="reversal vocabulary"):
        assert_no_reversal(CLEAN + "you may leave the flag off.\n", "fixture",
                           extra=("Leave The Flag Off",))


def test_the_failure_names_the_step_and_the_hits():
    """An operator has to be able to find the sentence from the message alone."""
    with pytest.raises(AssertionError) as exc:
        assert_no_reversal(CLEAN + "and continue the close.\n", "review-close Step 9z")
    msg = str(exc.value)
    assert "review-close Step 9z" in msg
    assert "and continue the close" in msg


def test_will_do_is_not_in_the_generic_list():
    """The recorded divergence (`Q-367`): a bare bigram measured false-alarming on
    a sentence that defends the rule. A future author re-adding it has to face
    this test and the reason beside the tuple."""
    assert "will do" not in REVERSAL_VOCAB
    assert_no_reversal(CLEAN + "Whoever runs the close will do so from the primary.\n", "fixture")


def test_the_generic_list_has_no_duplicates_and_no_substring_pairs():
    """A pair where one entry contains the other double-reports one hit and hides
    the fact that the list has grown by a synonym. `not needed` subsumes
    `is not needed`, which the Step 4b list carried both of."""
    assert len(set(REVERSAL_VOCAB)) == len(REVERSAL_VOCAB)
    for a in REVERSAL_VOCAB:
        for b in REVERSAL_VOCAB:
            assert a == b or a not in b, f"{a!r} is a substring of {b!r}"


def test_slice_between_fails_closed_when_an_anchor_moves():
    """Kills: a slice that returns "" on a missing end marker, which makes every
    negative assertion over it vacuously true (Phase 248's `test_slice_fails_closed`)."""
    text = "### 1a. Start\nbody\n### 1b. Next\n"
    assert slice_between(text, "### 1a.", "### 1b.", "x") == "### 1a. Start\nbody\n"
    with pytest.raises(AssertionError, match="start anchor"):
        slice_between(text, "### 9z.", "### 1b.", "x")
    with pytest.raises(AssertionError, match="end anchor"):
        slice_between(text, "### 1a.", "### 9z.", "x")
    # The end anchor must come AFTER the start, not anywhere in the text.
    with pytest.raises(AssertionError, match="end anchor"):
        slice_between(text, "### 1b.", "### 1a.", "x")
    # An earlier occurrence of the END marker must not pre-empt the slice (round:
    # C-H12 — `find(end)` from 0 refused a step whose end heading also appears
    # above it), and an earlier occurrence of the START marker is the one taken
    # (round: C-H13 — `rfind(start)` would slice from the wrong copy).
    text2 = "### 1b. early\n### 1a. Start\nbody\n### 1b. Next\n### 1a. late\n"
    assert slice_between(text2, "### 1a.", "### 1b.", "x") == "### 1a. Start\nbody\n"


# --------------------------------------------------------------------------------------
# The measured set. A parametrized test over REVERSAL_VOCAB cannot see an entry that
# was dropped -- the case vanishes with it -- so the entries each justified by a
# measured bypass are pinned here by name. Adding one is fine; removing one has to
# face this test and the reason beside the tuple.
# --------------------------------------------------------------------------------------

_MEASURED = frozenset({
    # Phase 247's round (38 of 53 survivors were one softening move)
    "is advisory", "are advisory", "advisory only", "and continue the close",
    "the close proceeds", "the close is not held", "skip this step entirely",
    "skip here too", "does not second-guess", "may be summarised", "may be summarized",
    # Phase 249's round
    "in practice", "is acceptable", "are acceptable",
    # Phase 248's round against Step 4b, promoted from that guard's private list by 253
    "in day-to-day use", "no action is needed", "not needed", "is optional",
    "are optional", "you can leave",
})


def test_the_measured_entries_are_present():
    missing = _MEASURED - set(REVERSAL_VOCAB)
    assert not missing, f"generic entries dropped without a recorded reason: {sorted(missing)}"


# --------------------------------------------------------------------------------------
# The wiring. `Q-367`'s defect was three private copies drifting; the mechanization is
# that no module may carry one, and that each migrated caller actually reaches the
# shared helper -- which its own tests cannot show, because their shipped slices are
# clean and a no-op helper passes them all.
# --------------------------------------------------------------------------------------

_TESTS_DIR = Path(__file__).resolve().parent


def test_no_module_carries_its_own_copy_of_the_layer():
    """The duplicate-then-diverge shape, closed by machinery rather than intent.
    `tests/_reversal.py`'s tuple used to say it was 'kept in sync with the in-module
    copies by intent, not by machinery'. This is the machinery."""
    # Built by concatenation so this file does not carry the literals it hunts --
    # the guard scans itself too, and a copy pasted in here would be caught. Three
    # detectors, because the round found the first one name-bound (C-H18..H21): the
    # function or tuple under its own name; the function shadowed by assignment
    # after the import (`assert_no_reversal = lambda ...`); and a copy under ANY
    # name, detected by its vocabulary -- three or more generic entries as string
    # literals in one module is a private list, whatever it is called. Every file
    # under tests/, recursively, so a copy in a subdirectory is not a hiding place.
    # Regexes, not literals: the round walked an underscore-prefixed def, a
    # list-bracketed tuple, a no-space assignment and a concatenated tuple past the
    # first cut's two literal needles, and the phase's own H-13 row had been shaped to
    # the one form the needle matched. (This comment describes those forms rather than
    # quoting them -- the guard scans this file too, and the quoted version reddened it.)
    needles = (re.compile(r"\bdef\s+_?assert_no_" + r"reversal\s*\("),
               re.compile(r"\b_?REVERSAL_" + r"VOCAB\s*="))
    shadow = re.compile(r"^\s*_?assert_no_" + r"reversal\s*=", re.M)
    literal = [f'"{v}"' for v in REVERSAL_VOCAB] + [f"'{v}'" for v in REVERSAL_VOCAB]
    offenders = []
    for path in sorted(_TESTS_DIR.rglob("*.py")):
        if path.name == "_reversal.py":
            continue
        src = path.read_text(encoding="utf-8")
        for needle in needles:
            if needle.search(src):
                offenders.append(f"{path.relative_to(_TESTS_DIR)}: {needle.pattern}")
        if shadow.search(src):
            offenders.append(f"{path.relative_to(_TESTS_DIR)}: the helper is shadowed by assignment")
        if path.name != Path(__file__).name:
            carried = sum(1 for lit in literal if lit in src)
            if carried >= 3:
                offenders.append(
                    f"{path.relative_to(_TESTS_DIR)}: {carried} generic entries as literals "
                    f"-- a private vocabulary under another name (or generic entries "
                    f"re-passed through extra=)"
                )
    assert not offenders, (
        "a module re-grew a private copy of the reversal layer; import "
        "`tests/_reversal.py` and pass step-specific phrasings as `extra=`:\n  "
        + "\n  ".join(offenders)
    )


def _softened_skill(tmp_path, anchor: str, sentence: str, where: str, name: str) -> Path:
    """A copy of review-close/SKILL.md with *sentence* inserted inside a caller's
    slice: `where="head"` puts it on the line after the first line containing
    *anchor* (the slice's start heading); `where="tail"` puts it on the line before
    the first line containing *anchor* (the slice's end heading). Two positions,
    because a guard that scans only the head of its slice passed the one-position
    version (round: C-W03, C-W07)."""
    skill = _TESTS_DIR.parent / "core/skills/review-close/SKILL.md"
    lines = skill.read_text(encoding="utf-8").splitlines(keepends=True)
    i = next(k for k, l in enumerate(lines) if anchor in l)
    lines.insert(i + 1 if where == "head" else i, sentence + "\n")
    out = tmp_path / name
    out.write_text("".join(lines), encoding="utf-8")
    return out


# A phrasing that exists ONLY in the shared generic list (promoted by Phase 253), so a
# caller that fires on it is provably reaching the shared tuple and not a leftover copy.
_GENERIC_PROBE = "In day-to-day use the check above can be treated as done."

# Every caller of the shared layer: (module, path attribute, test function, slice
# start anchor, slice end anchor). The two Phase 249 adopters are here too -- the
# round neutered both with a lambda after the import and nothing saw it (C-W05/W06).
_CALLERS = (
    ("test_close_batch_merge_target", "_SKILL", "test_step4b_names_the_merge_target_contract",
     "### 4b. Close Merged Batches", "### 4c."),
    ("test_step_2b_dispatch", "REVIEW_CLOSE", "test_the_security_twin_is_a_second_fleet_with_its_own_gate",
     "3b. **Spawn the security twin", "4. Collect all verdicts"),
    ("test_prescan_merge_gate", "REVIEW_CLOSE", "test_review_close_runs_the_prescan_itself_and_not_via_the_resolution_chain",
     "3a. **Run the Sysop pre-scan", "4. **On failure"),
    ("test_review_close_record_revision", "SKILL", "test_step_2d_gains_no_reversal_vocabulary",
     "### 2d. Test-Decision Verification", "### 2e."),
    ("test_worktree_primary_identity", "SKILL", "test_step_1a_gains_no_reversal_vocabulary",
     "### 1a. Classify Worktree State", "### 1b."),
)


@pytest.mark.parametrize("where", ["head", "tail"])
@pytest.mark.parametrize("module, attr, fn, start, end", _CALLERS, ids=[c[0] for c in _CALLERS])
def test_every_caller_reaches_the_shared_layer(tmp_path, monkeypatch, module, attr, fn, start, end, where):
    import importlib
    mod = importlib.import_module(module)
    anchor = start if where == "head" else end
    softened = _softened_skill(tmp_path, anchor, _GENERIC_PROBE, where, f"{module}-{where}.md")
    monkeypatch.setattr(mod, attr, softened)
    with pytest.raises(AssertionError, match="reversal vocabulary"):
        getattr(mod, fn)()


def test_step_4b_guard_passes_its_own_extra_list(tmp_path, monkeypatch):
    """The step-specific list travels with the call: a phrasing only Step 4b's
    `extra=` carries must fire here and nowhere else."""
    import test_close_batch_merge_target as mod
    specific = _softened_skill(
        tmp_path, "### 4b. Close Merged Batches",
        "Under `pr` you may leave the flag off; the script copes.", "head", "specific.md",
    )
    monkeypatch.setattr(mod, "_SKILL", specific)
    with pytest.raises(AssertionError, match="leave the flag off"):
        mod.test_step4b_names_the_merge_target_contract()
