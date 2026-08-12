"""Sysop's own CLAUDE.md declares the config Sysop's skills read — Phase 194, items 2 and 3.

This repo is a consumer of its own workflow, and the one consumer whose misconfiguration
nothing exercised. Two rules live here.

**`## Merge policy`.** `/review-close` Step 4-pre reads it from `<project>/CLAUDE.md` and
takes a documented default of `direct` when the section is absent — which on this repo's
PR-protected `main` means Step 4d attempts `git push origin main` and is rejected. Filed
2026-08-01 by Phase 175 and open until now.

Note what the filing and its brief both got wrong, because it shaped this guard: there is
**no `_shared/` partial that reads this header**, and no grep or parse of it anywhere in the
tree. The reader is *prose* at `core/skills/review-close/SKILL.md`. So the authority for the
shape is the shipped template at `WORKFLOW.md` § 6.1 — level-2 header, blank line, one bare
word — and this module asserts against that template rather than against a parser that does
not exist. Unlike `§ Sysop upstream repo` and `§ Plan review`, `§ Merge policy` ships no
stated parse contract; that gap is filed, not closed here.

**The turn-report clause.** Wade's standing requirement. Guarded per Phase 192's finding that
this repo's prose guards were 92% invertible: the assertions are scoped to the single bullet
carrying the rule, and they require the *antecedent* that does the work ("deliberately left")
rather than a quotable fragment that could survive the rule being gutted.

CLAUDE.md is deleted from both mirrors by `tools/make_public_mirror.sh`, so every test here
skips when it is absent.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
WORKFLOW = REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md"

VALID_POLICIES = ("direct", "pr")


def _claude_md() -> str:
    if not CLAUDE_MD.is_file():
        pytest.skip(
            "CLAUDE.md is maintainer-side and excluded from the public mirror; the "
            "repo self-config guards only apply in the source repo"
        )
    return CLAUDE_MD.read_text(encoding="utf-8")


def merge_policy(claude_md: str) -> str | None:
    """The declared value, read exactly as WORKFLOW.md § 6.1's template writes it:
    the first non-empty line under the level-2 header, stripped of backticks."""
    m = re.search(r"(?m)^##\s+Merge policy\s*$", claude_md)
    if not m:
        return None
    for line in claude_md[m.end():].split("\n"):
        if line.strip():
            return line.strip().strip("`").strip()
    return None


# Words that turn a rule into its own opposite while leaving every required phrase in
# place. The round's guard lens negated this whole bullet — "RETIRED; do NOT report **what
# is done**, **what is not done**, or **the recommended next action** … 'not done' need no
# longer cover in-scope work *deliberately left*" — and the first version of this module
# passed it 5/5, having been written expressly to prevent that. Requiring phrases cannot
# distinguish a rule from its negation; forbidding the licence can.
NEGATION_LICENCES = (
    "do not report", "don't report", "no longer", "need not", "retired",
    "superseded", "optional", "deprecated", "ignore the",
)


def turn_report_bullets(claude_md: str) -> list[str]:
    """**Every** bullet in § Conventions mentioning the rule, not the first.

    Returning the first was the second half of the same finding: a decoy bullet placed
    *earlier* in the section satisfied every assertion while the real rule below it was
    gutted. There must be exactly one, and the count is asserted rather than assumed.
    """
    sec = re.search(
        r"(?ms)^##\s+Conventions for working in this repo\s*$(.*?)^##\s", claude_md
    )
    if not sec:
        return []
    return [b for b in re.split(r"(?m)^- ", sec.group(1)) if "end of every turn" in b]


def turn_report_bullet(claude_md: str) -> str | None:
    found = turn_report_bullets(claude_md)
    return found[0] if len(found) == 1 else None


def test_this_repo_declares_a_merge_policy():
    assert merge_policy(_claude_md()) is not None, (
        "CLAUDE.md has no `## Merge policy` section, so /review-close Step 4-pre takes its "
        "documented default of `direct` and pushes straight to a PR-protected main."
    )


def test_the_declared_merge_policy_is_pr():
    """`main` has required the pytest check since 2026-06-24; `direct` is rejected there."""
    assert merge_policy(_claude_md()) == "pr", (
        f"CLAUDE.md § Merge policy declares {merge_policy(_claude_md())!r}; this repo's "
        "main is push-protected by a required status check, so the value must be `pr`."
    )


def test_the_declared_policy_is_a_value_the_shipped_spec_recognises():
    """Guards against a plausible-looking value the reader would not understand
    (`PR`, `pull-request`, `pr (squash)`) — the section existing is not the same as the
    section being readable."""
    value = merge_policy(_claude_md())
    assert value in VALID_POLICIES, (
        f"§ Merge policy is {value!r}; WORKFLOW.md § 6.1 defines exactly "
        f"{VALID_POLICIES}, one bare word on its own line."
    )
    assert WORKFLOW.is_file()
    assert re.search(r"(?m)^##\s+Merge policy\s*$", WORKFLOW.read_text(encoding="utf-8")), (
        "WORKFLOW.md no longer carries the `## Merge policy` template this guard reads as "
        "its authority; the contract moved and this module needs re-pointing."
    )


def test_the_turn_report_clause_is_present_and_states_all_three_parts():
    bullet = turn_report_bullet(_claude_md())
    assert bullet is not None, (
        "no turn-report bullet under CLAUDE.md § Conventions for working in this repo"
    )
    for required in ("what is done", "what is not done", "recommended next action"):
        assert required in bullet.lower(), (
            f"the turn-report bullet does not state {required!r}. All three parts are the "
            "rule; a report that drops one is the failure this exists to prevent."
        )


def test_the_turn_report_clause_keeps_its_load_bearing_half():
    """The invertibility lesson (Phase 192). "What is not done" is satisfiable by a session
    that reports only blockers, which is exactly the reading this rule exists to close. The
    clause that does the work is the one naming deliberately-left in-scope work — so that
    is what is asserted, not the quotable headline.
    """
    bullet = turn_report_bullet(_claude_md())
    assert bullet is not None
    assert "deliberately left" in bullet.lower(), (
        "the turn-report bullet no longer requires that 'not done' cover in-scope work "
        "deliberately left. Without it the rule is satisfied by listing blockers only, "
        "and the half that actually goes missing is unguarded."
    )


def test_exactly_one_bullet_states_the_turn_report_rule():
    """A decoy placed *earlier* in the section satisfied every phrase assertion above while
    the real rule below it was gutted — the round's guard lens showed 11 passing. First-match
    lookup is what made that work, so the count is the assertion."""
    found = turn_report_bullets(_claude_md())
    assert len(found) == 1, (
        f"{len(found)} bullets in § Conventions mention the turn-report rule; there must be "
        "exactly one. Two means a reader — and this guard — cannot tell which is binding."
    )


def test_the_turn_report_rule_is_not_negated_in_place():
    """Forbid the licence rather than require the phrase.

    Every assertion above is satisfied by a bullet that states the rule and then revokes
    it, because a negation *quotes* what it negates. This is the carry-in this repo already
    wrote down after Phase 192 — "forbid licences rather than requiring phrases" — and the
    first version of this module cited it without applying it.
    """
    bullet = turn_report_bullet(_claude_md())
    assert bullet is not None
    found = [w for w in NEGATION_LICENCES if w in bullet.lower()]
    assert not found, (
        f"the turn-report bullet contains negation/retirement language {found}: it states "
        "the rule and licenses ignoring it. Retire the rule by deleting the bullet, not by "
        "annotating it — a bullet that quotes its own requirements while revoking them "
        "passes every phrase check ever written for it."
    )


def test_exactly_one_merge_policy_section_exists():
    """`merge_policy()` takes the first `re.search`. A *prose* reader — and the actual
    reader here is prose, at `core/skills/review-close/SKILL.md` — has no first-match rule,
    so a second `## Merge policy` section declaring `direct` further down is a real
    ambiguity that the parser resolved silently in its own favour."""
    found = re.findall(r"(?m)^##\s+Merge policy\s*$", _claude_md())
    assert len(found) == 1, (
        f"{len(found)} `## Merge policy` sections in CLAUDE.md; there must be exactly one. "
        "The shipped reader is prose and will not pick for you."
    )


def test_the_reader_this_config_exists_for_still_reads_it():
    """The guards above are anchored to the *template* (`WORKFLOW.md`), not the *reader*.

    Renaming the four `Merge policy` references in `core/skills/review-close/SKILL.md` to
    anything else would leave this repo's config dead — declared, guarded, and read by
    nobody — with the whole suite green. That is the config-is-orphaned failure mode, and
    it is the one this module is supposed to be about.
    """
    reader = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"
    assert reader.is_file(), f"{reader} is gone; this contract's only reader moved"
    text = reader.read_text(encoding="utf-8")
    assert "Merge policy" in text, (
        "core/skills/review-close/SKILL.md no longer mentions `Merge policy`. Either the "
        "reader was renamed — in which case this repo's `## Merge policy` section is now "
        "dead config and this module needs re-pointing — or the contract was retired."
    )
    for value in VALID_POLICIES:
        assert f"`{value}`" in text, (
            f"the reader no longer names the `{value}` policy value; the accepted set "
            "this module asserts against has drifted from the skill that consumes it."
        )
