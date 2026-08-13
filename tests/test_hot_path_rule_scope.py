"""Phase 197 / `Q-182` — the hot-path rule stops firing on test directories,
and the scanner does NOT stop seeing them.

Phase 196 made `test/`, `tests/`, `testsuite/` and `*_test.go` scannable again
after semgrep's compiled-in default ignore list had been dropping them before
discovery. The immediate consequence, measured rather than predicted, was 15 new
findings on this tree from one rule — `semgrep-recompile-inside-def`, severity
`low`, whose own message scopes its rationale to *"request handlers and hot-path
code"* — because every shipped pack rule is whole-tree on a fresh install.

The fix is an `exclude_dir:` on that ONE rule. Which makes two failure modes
worth guarding, and they point in opposite directions:

1. **The exclusion is dropped or stops working**, and a day-one loop-mode
   consumer meets 15 low-value findings again.
2. **Somebody "fixes" it by re-blinding the scanner PER CHECK** — every other
   rule quietly acquiring the same `exclude_dir`, which would be green under any
   guard that only asserts the hot-path rule finds nothing in `tests/`.
   (Scoped deliberately: re-blinding the *stage* — removing Phase 196's explicit
   file operands — is caught by `tests/test_run_checks_semgrep_targets.py` and
   NOT by anything here. The round found this docstring claiming the wider
   class; the wider class is covered, just not by this module.)

So the assertions are paired: this rule must not see a test path, and another
rule must. Both run through the REAL `check_paths_by_id` + `finding_in_scope`
against the REAL shipped fragment, because the mechanism under test is precisely
their interaction — `paths:` placeholders are stripped as "not yet localized"
(fresh install ⇒ whole-tree) while `exclude_dir:` survives that strip. A guard
that asserted the YAML key exists would pass with the strip eating it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "core" / "companion" / "scripts"))

from run_checks.config import check_paths_by_id, finding_in_scope  # noqa: E402
from run_checks.semgrep import _IGNORED_TEST_DIRS  # noqa: E402

HOT_PATH_RULE = "semgrep-recompile-inside-def"


def _shipped_checks():
    out = {}
    for frag in sorted(_ROOT.glob("packs/*/companion/checks.yml.fragment")):
        doc = yaml.safe_load(frag.read_text(encoding="utf-8")) or {}
        for check in doc.get("checks") or []:
            cid = str(check.get("id", ""))
            if cid.startswith("semgrep-"):
                out[cid] = check
    return out


CHECKS = _shipped_checks()
# The fresh-install scope: the shipped specs, verbatim, through the real
# normalizer. No substitution — that IS the fresh install.
SCOPES = check_paths_by_id(CHECKS)

# DERIVED from the shipped check, never retyped. The round showed why: with
# `TEST_DIRS` hardcoded, narrowing it to `("tests",)` was inert on its own, and
# narrowing the shipped `exclude_dir` to `["tests"]` in a second edit then went
# green — a two-step regression with no tripwire between the steps. Reading the
# live list means a narrowing of either one is a narrowing of the assertions.
# `*_test.go` is a FILE convention with no exclude_dir form; stated here rather
# than silently absent.
TEST_DIRS = tuple(CHECKS[HOT_PATH_RULE].get("exclude_dir") or ())


def test_the_hot_path_rule_is_present_and_still_placeholder_scoped():
    """The premise both assertions below rest on.

    If the rule were localized in the shipped fragment, a fresh install would
    not be whole-tree, `Q-182` would not exist, and the paired tests would be
    proving something about a tree nobody installs.
    """
    assert HOT_PATH_RULE in CHECKS, f"{HOT_PATH_RULE} is no longer shipped"
    declared = CHECKS[HOT_PATH_RULE].get("paths") or []
    assert declared, f"{HOT_PATH_RULE} declares no paths at all"
    assert all("<" in str(p) for p in declared), (
        f"{HOT_PATH_RULE}'s paths are no longer pure placeholder vocabulary "
        f"({declared!r}) — a fresh install is no longer whole-tree for it, so "
        "re-derive whether this guard still describes what a consumer sees"
    )
    assert not (SCOPES[HOT_PATH_RULE]["paths"]), (
        "the placeholder strip stopped stripping; a fresh install now scopes "
        "this rule to unresolvable roots instead of scanning whole-tree"
    )


# Deriving TEST_DIRS closes the two-step regression, and opens a one-step one:
# delete `exclude_dir` and every parametrized test below collects ZERO cases and
# passes. This floor is what makes the derivation safe, and it is why the list
# appears twice in this file with two different jobs — one derived, one required.
#
# The REQUIRED half is derived too, from the shipped constant Phase 196 read out
# of the semgrep-core binary. Retyped, it was still narrowable in one edit: the
# round's E08 shrank it to `("tests",)` and nothing noticed, because a guard
# cannot defend an expectation it merely asserts about itself. Sourced from
# `_IGNORED_TEST_DIRS`, shrinking it means shrinking shipped code that
# `tests/test_run_checks_semgrep_targets.py` holds against the real binary.
REQUIRED_TEST_DIRS = tuple(sorted(_IGNORED_TEST_DIRS))


def test_the_shipped_exclusion_matches_semgreps_own_test_directory_list():
    """Non-vacuity floor for the derivation above, and C02's direct kill.

    Asserted as an EQUALITY, in both directions, and that is the round's E08:
    a containment check (`REQUIRED <= TEST_DIRS`) is satisfied by shrinking
    REQUIRED, so the guard could weaken its own expectation in one edit and
    stay green. Equality means the two lists can only move together, and the
    other direction is worth holding anyway — an `exclude_dir` entry that is
    NOT one of semgrep's test-path spellings is a scanning-policy decision
    wearing this fix's clothes, and should have to argue for itself here.
    """
    assert set(TEST_DIRS) == set(REQUIRED_TEST_DIRS), (
        f"{HOT_PATH_RULE}'s exclude_dir is {sorted(TEST_DIRS)} but semgrep's "
        f"own default test-path list is {sorted(REQUIRED_TEST_DIRS)}. Missing "
        "entries hand the noise back to any consumer using that spelling; extra "
        "ones exclude directories on this rule's authority without its "
        "rationale. Either change both, or say why they differ."
    )


@pytest.mark.parametrize("test_dir", TEST_DIRS)
def test_the_hot_path_rule_does_not_fire_under_a_test_directory(test_dir):
    """Direction 1 — the exclusion works, on a FRESH install."""
    rel = f"{test_dir}/test_something.py"
    assert not finding_in_scope(rel, SCOPES[HOT_PATH_RULE]), (
        f"{HOT_PATH_RULE} is back in scope at {rel!r} on a fresh install. Its "
        "own message scopes it to request handlers and hot-path code, so a "
        "test body is a true positive of the pattern aimed at the wrong "
        "population — restore `exclude_dir` on the check in "
        "packs/python/companion/checks.yml.fragment."
    )


@pytest.mark.parametrize("test_dir", TEST_DIRS)
def test_the_exclusion_is_nested_not_just_top_level(test_dir):
    """`exclude_dir` is directory-basename semantics at ANY depth.

    A top-level-only reading would leave `packages/api/tests/` firing, which is
    where a real consumer's tests usually sit. Phase 196's own round found the
    mirror-image bug: a corpus with a deep prefix and no deep suffix let a
    one-level segment scan pass while the defect stayed open for every real
    tree.
    """
    rel = f"packages/api/{test_dir}/test_deep.py"
    assert not finding_in_scope(rel, SCOPES[HOT_PATH_RULE]), (
        f"{HOT_PATH_RULE} fires at {rel!r} — the exclusion has become "
        "top-level-only, which is the shape most consumer trees defeat"
    )


@pytest.mark.parametrize("test_dir", TEST_DIRS)
def test_the_exclusion_is_directories_only_not_filenames(test_dir):
    """`exclude_dir` must not match the FILE component.

    Found by the author-side battery, which walked a one-character widening —
    `rp.split("/")` instead of `rp.split("/")[:-1]` — straight through every
    other assertion here. Over-exclusion is the direction a zero-invariant
    cannot see: nothing reports a file that stopped being scanned.

    The EXTENSIONLESS name is the case that discriminates, and the first draft
    of this test missed it. `tests.py` is unaffected by that widening because
    `fnmatch("tests.py", "tests")` is False — so an assertion written against
    `tests.py` is green under both versions and proves nothing. A shell script
    honestly named `test` is the real casualty, and it is an ordinary thing for
    a repository to contain.
    """
    for rel in (f"core/companion/scripts/{test_dir}.py",
                f"core/companion/scripts/{test_dir}"):
        assert finding_in_scope(rel, SCOPES[HOT_PATH_RULE]), (
            f"{rel!r} is excluded — `exclude_dir` has started matching the "
            "filename as well as the directory components"
        )


def test_the_hot_path_rule_still_fires_on_real_source():
    """The positive floor.

    Without this, emptying `paths:` and `exclude_dir:` into something that
    matches nothing — or excluding `*` — is green.
    """
    assert finding_in_scope("core/companion/scripts/thing.py",
                            SCOPES[HOT_PATH_RULE]), (
        f"{HOT_PATH_RULE} no longer fires on ordinary source either; the "
        "exclusion has widened past test directories"
    )


def test_exclude_dir_is_glob_matched_as_documented():
    """`WORKFLOW.md` documents `exclude_dir` as directory-basename **globs**.

    Round finding: replacing `fnmatch.fnmatch(seg, xd)` with `seg == xd` in
    `finding_in_scope` survives the entire suite. The grep stage has its own
    fnmatch with its own tests; the Phase-133 tool-shelling post-filter — the
    one this phase's fix depends on — had no glob case anywhere. The shipped
    rule uses literal names, so nothing exercised the documented behaviour.

    Asserted against the predicate directly rather than the shipped check,
    because the claim is about the mechanism, not about today's config.
    """
    scope = {"paths": [], "exclude_dir": ["test*"]}
    assert not finding_in_scope("testsuite/a.py", scope), (
        "`exclude_dir` has stopped glob-matching; `test*` must exclude "
        "`testsuite/`, and WORKFLOW.md documents it as a glob"
    )
    assert not finding_in_scope("pkg/tests/a.py", scope), (
        "`exclude_dir` globs must match at any depth, not only at the root"
    )
    assert finding_in_scope("src/best/a.py", scope), (
        "`test*` is anchored at the start of the segment; it must not match "
        "`best` — a glob that matched substrings would exclude far more than "
        "it names, in the direction nothing reports"
    )


@pytest.mark.parametrize("test_dir", TEST_DIRS)
def test_other_rules_still_see_test_directories(test_dir):
    """Direction 2 — Phase 196 must stay done.

    The cheap way to silence `Q-182` is to stop scanning test paths again. That
    would be green under the assertions above and would re-open the defect
    Phase 196 exists to close: a scan that reports `executed with 0 findings`
    over surface it never read. Every OTHER shipped rule must still reach a
    test path on a fresh install.
    """
    others = [cid for cid in SCOPES if cid != HOT_PATH_RULE]
    assert others, "no other semgrep rules shipped; this guard is vacuous"
    blind = [
        cid for cid in others
        if not finding_in_scope(f"{test_dir}/test_something.py", SCOPES[cid])
    ]
    assert not blind, (
        f"these rules stopped seeing {test_dir}/ on a fresh install: {blind}. "
        "Phase 196 made test paths scannable on purpose — the fix for the "
        "hot-path rule's noise is that ONE rule's exclude_dir, not a return "
        "to a scanner that cannot read the test tree."
    )
