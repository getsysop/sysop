"""`Q-652` — Step 4d-1's stuck-PR recovery, and 4a-post's placement note, say the same thing.

4a-post's note says Step 4c's work survives only in 4c's commit on the merge target, which a re-run
abandons. 4d-1 used to say a re-run in the integration-branch shape was "safe and idempotent". By
the time a PR is stuck, Step 4c has deleted the pending docs it consolidated and removed the locks
(neither is in any commit), so a re-run cuts a new integration branch from local `<default
branch>` and merges the same branches without their index flips, body moves and doc entries; Step
3b's exit 8 does not catch it, because its discriminator is the lock. The recovery is on the stuck
branch.
"""
from __future__ import annotations

from pathlib import Path
from skill_runner_text import text_of

REPO = Path(__file__).resolve().parent.parent
CLOSE = REPO / "core/skills/review-close/SKILL.md"


def _span(start: str, end: str) -> str:
    t = text_of(CLOSE)
    i = t.index(start)
    return t[i:t.index(end, i)]


def test_the_integration_shape_recovers_on_the_stuck_branch() -> None:
    d1 = _span("##### 4d-1. Stuck-PR handling", "- **In the PR-reuse shape")
    assert "safe and idempotent" not in d1
    assert "**In the integration-branch shape, recover on the stuck branch; do not re-run `/review-close`** (`Q-652`): a re-run merges the same branches without Step 4c's work." in d1
    assert 'push it with `git push origin "<integration branch>"`' in d1
    assert "Check out the integration branch." in d1 and "Then resume at command 4." in d1
    assert "Put the `PUSHED FROM` SHA in this stop's report: Step 6 needs it." in d1
    assert "run `4a-post`'s resolved command list on it" in d1
    assert "follow-up `/review-close`" not in d1


def test_the_leave_in_place_bullet_does_not_promise_locks_4c_removed() -> None:
    d1 = _span("##### 4d-1. Stuck-PR handling", "- **In the integration-branch shape")
    assert "the `sysop/runtime/locks/` **in place**" not in d1
    assert "Step 4c the locks and pending docs it consolidated" in d1


def test_4a_post_and_4c_still_state_the_facts_the_recovery_rests_on() -> None:
    post = _span("### 4a-post. Verify the Merged Tree", "### 4b.")
    assert "recoverable from a discarded branch or not at all" in post
    c4 = _span("### 4c. Consolidate Pending Documentation", "### 4d.")
    assert "python3 sysop/scripts/close_index.py " in c4  # Step 4c's program since Phase 386
    assert "lock.unlink(missing_ok=True)" in (Path(__file__).resolve().parents[1]
        / "core/companion/scripts/close_index.py").read_text(encoding="utf-8")
    assert "6. **Clean up pending-docs**: Delete the pending-docs **this step consolidated**" in c4
