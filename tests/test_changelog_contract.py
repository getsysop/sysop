"""Drift guard for the one-changelog contract (Phase 222, Q-279).

`changelog.md` and `CHANGELOG.md` are the same file on any case-insensitive
filesystem (the APFS and Windows default). Before Phase 222, `/review-close` Step 4c
wrote lowercase `changelog.md` in a date-heading grammar while `/release` wrote
uppercase `CHANGELOG.md` in Keep-a-Changelog shape — two format contracts interleaving
in one file that `WORKFLOW.md` claimed Sysop never touches. Phase 222 converged on one
canonical name (`CHANGELOG.md`), one grammar (Keep a Changelog: Step 4c writes inside
`## [Unreleased]`, `/release` folds `[Unreleased]` into the version entry it prepends),
and a truthful `WORKFLOW.md` row naming both writers.

These tests pin the convergence so a future edit cannot quietly reintroduce a second
case, a second grammar, or the false ownership claim.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEW_CLOSE = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"
RELEASE = REPO_ROOT / "core" / "skills" / "release" / "SKILL.md"
WORKFLOW = REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md"

# Every shipped prose surface a consumer or agent reads.
SHIPPED_MD = sorted(
    list((REPO_ROOT / "core").rglob("*.md")) + list((REPO_ROOT / "packs").rglob("*.md"))
)

# ANY casing (re.I) — the round's CL-1 mutation shipped `Changelog.md`, a third case
# the exact-lowercase check could not see; every non-canonical casing is the same file
# on a case-insensitive filesystem.
_ANY_CASE = re.compile(r"\b[Cc][Hh][Aa][Nn][Gg][Ee][Ll][Oo][Gg]\.md\b")

# A non-canonical casing is legal only while EXPLAINING the collision or doing
# tolerant read-side discovery — marked by one of these phrases on the same line.
# "Also names CHANGELOG.md" was the previous exemption, and the round's CL-4 walked
# it: `git add changelog.md  # NOT CHANGELOG.md` hides a lowercase write target
# beside the canonical name.
_EXPLAINER_MARKS = ("case-insensitive", "same file", "auto-discover")


def test_non_canonical_changelog_casings_appear_only_in_collision_explainers():
    """Any casing of changelog.md other than exactly `CHANGELOG.md` is legal only on
    a line that explains the case collision (or the read-side discovery list) — never
    as a write target, however it is decorated. Round survivors CL-1 and CL-4 closed."""
    offenders = []
    for f in SHIPPED_MD:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            variants = [m for m in _ANY_CASE.findall(line) if m != "CHANGELOG.md"]
            if variants and not any(mark in line for mark in _EXPLAINER_MARKS):
                offenders.append(f"{f.relative_to(REPO_ROOT)}:{i} {variants}")
    assert not offenders, (
        "non-canonical changelog casing outside a collision explainer "
        f"(write-target regression?): {offenders}"
    )


def test_fenced_git_add_lines_use_exactly_the_canonical_case():
    """The staging fences are the write path itself — there, no explainer excuses a
    wrong case at all (CL-1's exact mutation site)."""
    offenders = []
    for f in SHIPPED_MD:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if "git add" not in line:
                continue
            for m in _ANY_CASE.findall(line):
                if m != "CHANGELOG.md":
                    offenders.append(f"{f.relative_to(REPO_ROOT)}:{i} {m}")
    assert not offenders, f"non-canonical changelog case on a git add line: {offenders}"


def test_both_writers_state_the_shared_unreleased_grammar():
    """Both writing skills must carry the Keep-a-Changelog `[Unreleased]` mechanism —
    Step 4c writes into it, `/release` folds it. Losing either half re-opens the
    two-contracts-one-file interleave."""
    rc = REVIEW_CLOSE.read_text(encoding="utf-8")
    rel = RELEASE.read_text(encoding="utf-8")
    assert "## [Unreleased]" in rc and "keepachangelog.com" in rc, (
        "review-close Step 4c lost the shared Keep-a-Changelog [Unreleased] contract"
    )
    assert "## [Unreleased]" in rel and "keepachangelog.com" in rel, (
        "release lost the Keep-a-Changelog [Unreleased] fold-in"
    )
    fold_at = rel.find("Fold in `## [Unreleased]`")
    assert fold_at != -1, (
        "release Step 7 no longer folds /review-close's [Unreleased] bullets into "
        "the version entry — the two writers are uncoordinated again"
    )
    # CL-5's shape: the bold lead survives while the body underneath says the
    # opposite. Read the fold paragraph and forbid the countermand vocabulary.
    fold_para = rel[fold_at : rel.find("\n\n", fold_at)]
    for countermand in ("do not merge", "leave the section", "the *next* release",
                       "belong to the next release"):
        assert countermand not in fold_para, (
            f"the fold paragraph countermands its own lead ({countermand!r}): "
            f"{fold_para[:300]}"
        )
    assert "merge each into the matching class" in " ".join(fold_para.split()), (
        "the fold paragraph lost its operative merge instruction"
    )


def test_step_4c_bugfix_write_targets_unreleased_not_date_headings():
    """The bugfix routing line must target `## [Unreleased]` and must not have
    reverted to the retired `### YYYY-MM-DD` date-heading grammar."""
    rc = REVIEW_CLOSE.read_text(encoding="utf-8")
    m = re.search(r"^\s*\*\*CHANGELOG\.md\*\* \(bugfix type only.*$", rc, re.MULTILINE)
    assert m, "review-close Step 4c's bugfix routing line not found"
    line = m.group(0)
    # The OPERATIVE clause, not a token anywhere on the line: the round's CL-2 kept
    # `[Unreleased]` inside a negation ("not under `## [Unreleased]`") and dodged the
    # YYYY-MM-DD pin with a concrete date.
    assert re.search(r"Add under `## \[Unreleased\]`", line), (
        f"bugfix write's operative clause no longer targets [Unreleased]: {line}"
    )
    assert "not under" not in line and "date heading" not in line, (
        f"bugfix write countermands its own target: {line}"
    )
    assert not re.search(r"### (?:YYYY-MM-DD|\d{4}-\d{2}-\d{2})", line), (
        f"bugfix write reverted to the retired date-heading grammar: {line}"
    )


def test_workflow_row_names_both_writers_and_drops_the_false_claim():
    """`WORKFLOW.md`'s CHANGELOG.md table row must name both writers and must never
    again claim Sysop does not touch the file — the claim Q-279 measured as false."""
    rows = [
        l
        for l in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if l.lstrip().startswith("| `CHANGELOG.md` |")
    ]
    assert len(rows) == 1, f"expected exactly one CHANGELOG.md row, found {len(rows)}"
    row = rows[0]
    assert "never seeds or touches" not in row, (
        "WORKFLOW.md re-acquired the false 'Sysop never touches it' claim"
    )
    assert "/review-close" in row and "/release" in row, (
        f"CHANGELOG.md row must name both writers: {row}"
    )


def test_the_rotation_files_into_unreleased_changed():
    """Closed from the Phase 222 battery's one survivor: no guard read the rotation
    line's destination, so rotating into a fresh date heading — the retired grammar,
    re-minted by the highest-volume writer — survived every other pin."""
    rc = REVIEW_CLOSE.read_text(encoding="utf-8")
    m = re.search(r"^\s*\*\*Rotation check\*\*:.*$", rc, re.MULTILINE)
    assert m, "review-close Step 4c's rotation line not found"
    line = m.group(0)
    assert re.search(r"under `## \[Unreleased\]` → `### Changed`", line), (
        f"the rotation's operative destination clause is gone: {line}"
    )
    # CL-3's shape: both tokens kept inside "(no longer …)" — forbid the countermand.
    assert "no longer" not in line and "not under" not in line, (
        f"the rotation countermands its own destination: {line}"
    )
    assert not re.search(r"(?:YYYY-MM-DD|fresh )?dated? heading|### \d{4}-\d{2}-\d{2}", line), (
        f"the rotation re-minted the retired date-heading grammar: {line}"
    )
