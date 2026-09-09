"""Phase 270 (`Q-413`) deleted a `git commit` from `/auto-build` Step 5's rollback, and
the permission rule that existed only to authorize it. Nothing stopped either coming back.

The round's test lens put it plainly: the commit that shipped that change touched exactly
one test file, and it was the *unrelated* `Q-419` guard. Re-adding
`Bash(git commit -m rollback:*)` to the template — and bumping `install.sh`'s count comment
to match, which the existing count guard would happily accept, since it only checks the
stated number against the JSON's actual length and is entirely content-agnostic — passed
every test in the repo. So did re-adding the prescription to the skill.

**Why a guard rather than a comment.** The reason the commit is wrong is not obvious from
the abort path: it is that the flip is uncommitted at that point, so the checkout leaves a
clean tree. A future reader looking at an abort path that restores a file and does not
commit has a natural-looking "fix" available, and the guarded form (`git diff --cached
--quiet ||`) looks *safer* than the bare one. It is not: that predicate is satisfied only
when something else is staged, and it is the same predicate Phase 261 removed from
`/claim-task` Step 4d for exiting 0 over a task still `open` at `HEAD` (`Q-397`).

**The non-vacuity control is the real historical text.** Rather than asserting a
hand-written negative, `test_the_predicate_reds_on_the_text_it_was_written_to_prevent`
runs the same predicate against `3a502fc~1` — the tree as it stood before the deletion —
and requires it to fail there. A guard that cannot see the defect it was written for is
the failure mode this project has paid for repeatedly; here that is checked rather than
asserted.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core/skills/auto-build/SKILL.md"
SETTINGS = REPO_ROOT / "core/companion/.claude/settings.json"

# The rule text, and the prescription shape. Both are matched loosely on whitespace and
# quoting so a re-add that reformats is still caught: `git commit` followed by a `-m` whose
# subject begins `rollback:` is the class, not one spelling of it.
RULE_RE = re.compile(r"Bash\(\s*git\s+commit\s+-m\s+rollback:")
PRESCRIPTION_RE = re.compile(r"git\s+commit\s+(?:-q\s+)?-m\s+[\"'`]*rollback:")


def rollback_regions(skill_text: str) -> list[str]:
    """The two places Step 5 tells an operator how to undo a failed pre-claim.

    Returned as text so the predicate below can run over the same regions for the current
    tree and for a historical one.
    """
    regions = []
    m = re.search(r"^# 5\.2 —.*?(?=^# 5\.3 —)", skill_text, re.M | re.S)
    if m:
        regions.append(m.group(0))
    # The WHOLE § Abort handling block, not its first line. Phase 271 split that
    # paragraph in three (the `HEAD --` rationale and the 5.4 entry each became
    # their own paragraph), and a `^...$` single-line match would have quietly
    # stopped scanning the 5.4 text — shrinking this guard's subject as a side
    # effect of an unrelated edit. Terminated on the next `## ` heading, so
    # further paragraphs are covered as they are added rather than dropped.
    m = re.search(r"^\*\*Abort handling:\*\*.*?(?=^## )", skill_text, re.M | re.S)
    if m:
        regions.append(m.group(0))
    return regions


def prescribes_a_rollback_commit(skill_text: str) -> list[str]:
    """Offending lines, empty when clean. Shared by the guard and its historical control."""
    hits = []
    for region in rollback_regions(skill_text):
        for line in region.splitlines():
            if PRESCRIPTION_RE.search(line):
                hits.append(line.strip())
    return hits


def test_the_rollback_regions_are_found_at_all():
    """Vacuity: a predicate that scans nothing reports clean forever."""
    regions = rollback_regions(SKILL.read_text(encoding="utf-8"))
    assert len(regions) == 2, (
        f"expected Step 5.2's block and the § Abort handling paragraph, found "
        f"{len(regions)} — the anchors moved and this guard is scanning the wrong text"
    )
    # Each region must be ABOUT the rollback — either prescribing it or pointing
    # at where it is prescribed. Phase 271 made Step 5.2 a cross-reference rather
    # than a second copy of the command: restating it there meant a prescription
    # that could never satisfy the pairing check in
    # `test_rollback_restores_from_head.py`, because a comment can tell an
    # operator to run something but cannot itself verify anything. Single-sourcing
    # the command is the better documentation and the reason this assertion is
    # about SUBJECT rather than about a literal string.
    assert all(("git checkout tasks/index.yml" in r) or ("Abort handling" in r)
               for r in regions), (
        "a located region neither prescribes the rollback checkout nor refers to where "
        "it is prescribed, so the anchors are matching some other part of the skill. "
        "The BARE form is correct here and the wider `git checkout HEAD --` was refused "
        "(`Q-445`): it reverts the index too, so it destroys a concurrent session's "
        "staged claim — measured, a second task silently reset to `open`, exit 0. The "
        "no-op hazard is closed by the `git diff --cached --quiet` verification beside "
        "it, not by a wider command."
    )
    # And at least one region must carry the real command, or this guard is
    # scanning two cross-references and nothing else.
    assert any("git checkout tasks/index.yml" in r for r in regions), (
        "no located region prescribes the rollback at all — the command moved out of "
        "both regions and this guard now scans nothing"
    )
    # The 5.4 paragraph must be INSIDE the located region, or the commit guard
    # below scans the one place a `git commit` is most tempting and does not see it.
    abort = [r for r in regions if r.startswith("**Abort handling:**")]
    assert abort and "5.4 failure" in abort[0], (
        "the § Abort handling region no longer reaches the 5.4 paragraph — the block was "
        "split or a heading moved, and this guard's subject shrank without failing"
    )


def test_step5s_rollback_prescribes_no_git_commit():
    hits = prescribes_a_rollback_commit(SKILL.read_text(encoding="utf-8"))
    assert not hits, (
        "/auto-build Step 5's rollback prescribes a `git commit` again:\n  "
        + "\n  ".join(hits)
        + "\n\nIt cannot have anything to commit. 5.1's flip is uncommitted (5.4 commits "
        "it) so the checkout leaves a clean tree and the commit exits 1 over a rollback "
        "that succeeded (`Q-413`, reproduced end to end). A `git diff --cached --quiet ||` "
        "guard is not the safer version: its predicate is true only when something ELSE "
        "is staged, which the commit then captures under a `rollback:` subject — and it "
        "is the predicate Phase 261 removed from /claim-task Step 4d for exiting 0 over "
        "a task still `open` at HEAD (`Q-397`)."
    )


def test_the_template_carries_no_rollback_commit_rule():
    allow = json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]["allow"]
    assert allow, "the template allow-list is empty; this guard is scanning nothing"
    offenders = [r for r in allow if RULE_RE.search(r)]
    assert not offenders, (
        f"the template re-adds {offenders} — a rule bound by nothing since Phase 270 "
        "deleted the only `git commit` it authorized. WORKFLOW.md § 8.2a *When a rule "
        "stops being bound: delete it*: it is not subsumed (there is no "
        "`Bash(git commit:*)`), it is not operator headroom, and it twins no bound rule. "
        "Re-adding it also silently invalidates install.sh's rule-count comment."
    )


def test_the_predicate_reds_on_the_text_it_was_written_to_prevent():
    """The control that matters: run the predicate against the pre-deletion tree.

    `3a502fc` is Phase 270's own commit, so `3a502fc~1` is the last tree that carried the
    prescription. If the predicate comes back clean there, it does not detect the defect
    and every assertion above is decoration.
    """
    r = subprocess.run(
        ["git", "show", "3a502fc~1:core/skills/auto-build/SKILL.md"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if r.returncode != 0:
        pytest.skip(
            "the pre-deletion commit is not reachable here (shallow clone, or a tree "
            "published without this history); the predicate's detection cannot be checked"
        )
    hits = prescribes_a_rollback_commit(r.stdout)
    assert hits, (
        "the predicate reports the PRE-DELETION tree clean, so it cannot see the very "
        "prescription it exists to catch — the assertions above are vacuous"
    )
