"""Phase 379 — pins for the field-report triage's text fixes that no other module guards.

The behaviour fixes carry executable tests of their own (`test_review_index.py`,
`test_rule_b_preserves_published_merges.py`); the placement, strip and 4c edits moved
existing pins. These are the sentences a runner acts on whose loss nothing else would see:
Step 8's `Superseded PRs:` row (`Q-335` recorded that no guard read it), Step 4b's absent-
tracker arm, the trailers sentence, the three orchestrator skills' main-conversation rule,
and the two public pages' downgrade paragraph.
"""

from __future__ import annotations

import re
from pathlib import Path
from skill_runner_text import text_of

REPO = Path(__file__).resolve().parent.parent
RC = text_of(REPO / "core/skills/review-close/SKILL.md")
FLAT = " ".join(re.sub(r"(?m)^[ \t]*(?:>[ \t]?)+", "", RC).split())


def _step8_row() -> str:
    i = RC.index("Superseded PRs: <branch #PR")
    j = RC.index("Squash provenance:", i)
    return " ".join(RC[i:j].split())


def test_the_superseded_row_states_the_end_state_by_policy() -> None:
    row = _step8_row()
    assert "Under `pr`" in row and "Under `direct`" in row, row
    assert "MERGED" in row and "closed as unmerged" in row, row
    assert "a human does" not in row, "the Q-335 falsehood is back"
    assert "item 3" in row and "item 4" not in row, "the citation must read item 3"
    assert "Step 4d's push" in row and "Step 6 item 0" in row, "the row must name the push that lands main and the check that reads the state"


def test_item_3_is_scoped_to_pr_and_sends_the_direct_check_to_step_6() -> None:
    i = FLAT.index("3. **Under the `pr` policy, a published branch's own PR does not survive this close")
    item = FLAT[i:FLAT.index("4. If the merge conflicts", i)]
    assert "closes that PR as unmerged" in item
    assert "Under `direct` none of it applies" in item
    assert "Step 4d's push" in item and "nothing to comment" in item, "the direct arm must name the push that lands main, not Step 6's delete"
    assert "Step 6 checks the PR's state before it deletes the branch" in item


def test_step_6_checks_the_pr_state_before_deleting_a_published_branch() -> None:
    i = FLAT.index("**`direct` policy — per-branch cleanup.**")
    sec = FLAT[i:i + 1400]
    item0 = sec.index("0. **A branch Step 4a took with the `--no-ff` published arm:**")
    delete = sec.index("1. Delete the **remote** branch first")
    assert item0 < delete, "the state check must precede the delete, or the delete produces the CLOSED it looks for"
    assert "gh pr view <branch> --json number,state" in sec
    assert "`OPEN` → GitHub has not registered Step 4d's push yet; wait and re-run before deleting" in sec
    assert "`CLOSED` before this close ran, or no PR at all → not this close's doing" in sec


def test_step_4b_treats_an_absent_tracker_as_the_empty_set_with_one_stop() -> None:
    i = FLAT.index("**A tracker that does not exist is the empty set too.**")
    para = FLAT[i:i + 700]
    assert "review_index --list: review_tasks.md absent; 0 batches listed" in para
    assert "exits 0" in para
    assert "**Unless `sysop/runtime/locks/BATCH-*.lock` exists" in para, "the lock STOP's polarity"
    assert "git history shows the tracker once existed" in para and "STOP and report which" in para


def test_the_exit_code_enumeration_matches_the_script() -> None:
    i = FLAT.index("**Exactly two exit codes are reachable from a bare `--list`")
    para = FLAT[i:i + 900]
    assert "`1` (the tracker is absent but `git log -- review_tasks.md` shows it once existed" in para
    assert "**`--list` itself refuses only a deleted tracker**" in para
    assert "`1` (`review_tasks.md` not found)" not in FLAT, "the pre-phase claim is back"


def test_trailers_ride_the_same_merge_command() -> None:
    i = FLAT.index("**Trailers the project's commit convention requires**")
    sent = FLAT[i:i + 600]
    assert '-m "<Trailer>: <value>"' in sent
    assert "no amend" in sent
    assert "ONE final `-m`" in sent and "one trailer per line" in sent, "two trailers in two -m arguments make only the last a trailer (lens A F2)"
    ex = sent.index('git merge --no-ff -m "merge <branch> (published — not rebased)" -m "<Trailer>: <value>"')
    assert ex >= 0, "the example must show the subject -m before the trailer -m"
    # the pinned literal stays exactly as test_phantom_shell_vars requires
    assert '`git checkout "<merge target>" && git merge --no-ff -m "merge <branch> (published — not rebased)" <branch>`' in RC


def test_every_orchestrator_skill_says_to_run_in_the_main_conversation() -> None:
    for name in ("review-close", "claim-task", "auto-build", "auto-fix", "auto-judge"):
        text = text_of(REPO / f"core/skills/{name}/SKILL.md")
        head = text[:4000]
        assert "never through an Agent call" in head, f"{name}: the main-conversation rule left its opening"


def test_review_close_states_its_batch_intent_in_the_opening() -> None:
    head = " ".join(RC[:4000].split())
    assert "run it once over the set of approved branches, not once per branch" in head
    assert "say so and offer to defer the close" in head


def test_the_downgrade_pages_say_what_is_true_today() -> None:
    for page in ("docs/loop-mode.md", "docs/install-and-update.md"):
        text = " ".join((REPO / page).read_text(encoding="utf-8").split())
        assert "has no `--update` path yet" in text, page
        assert "is a fresh reinstall, not an" not in text, f"{page}: the one-sentence brush-off is back"
        assert "`sysop/SYSOP_ISSUES.md` and `tasks/index.yml` it seeds once and never rewrites" in text, page
        assert "`.project.*` overlays and `substitutions.project.yml` the installer never writes" in text or "the installer never\nwrites them" in (REPO / page).read_text(encoding="utf-8") or "the installer never writes them" in text, page
        assert "fresh install overwrites every managed path" in text, f"{page}: the preserve-only-under-update fact (lens C H2)"


# The author-side battery's two survivors (tools/phase379_mutations.py A06, R07): both
# edits were seen only by the hash pins in test_fix_in_branch_tier.py, which the battery
# excludes as wiring. These pin the STRUCTURE the hash cannot name.


def test_the_pin_is_asserted_non_empty_before_mktemp_creates_anything() -> None:
    i = RC.index('PIN=$(git rev-parse --verify "<target branch>^{commit}")')
    block = RC[i:RC.index('git worktree add --detach "$PINNED" "$PIN"', i)]
    guard = block.index(': "${PIN:?')
    mk = block.index('PINNED=$(mktemp -d')
    assert guard < mk, "the emptiness assertion must run before mktemp, or a failed pin leaves a directory"
    assert "|| { echo \"STOP:" in block.split("\n")[0], "the feature-branch arm must stop on a pin that did not resolve"


def test_4c_creates_an_absent_project_status_before_inserting() -> None:
    i = FLAT.index("**PROJECT_STATUS.md §6**: Generate a one-line entry")
    para = FLAT[i:FLAT.index("**Consolidation clause", i)]
    create = para.index("**If `PROJECT_STATUS.md` is absent, create it first**")
    insert = para.index('Insert at the TOP of Section 6 "Recent Major Updates"')
    assert create < insert, "the create-if-absent arm must precede the insert it enables"
    assert "## 6. Recent Major Updates" in para, "the created file must carry the heading item 5's check keys on"
    assert "S6: created PROJECT_STATUS.md" in para
    assert "a missing file is not a reason to skip the write" in para
