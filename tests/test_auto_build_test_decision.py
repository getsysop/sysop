"""Guards for `/auto-build`'s `## Test decision` writer (Phase 277, `Q-460`).

The defect these are aimed at was structural, not a slip. `/claim-task` Step 7e
writes the record as Sequence item 3 and its orchestrator re-reads it at the branch
tip in Step 8. `/auto-build` Step 7c's Sequence had **no equivalent item at all** --
Absorb, ExitPlanMode, Implement, convention verification -- while the skill's own
"Auto-Build Complete" section told the human that `/review-close` "reconstructs from
... the `## Test decision` records". A consumer of the record shipped with no
producer.

The consequence was not a warning. `/auto-build` claims through
`claim_task.sh --lock`, so `/review-close` Step 2d's ownership probe finds a lock and
answers `OWED` -- exactly the condition under which the "Record not owed" disposition
is *withheld*. Every autonomous branch, every close, left a human choosing between
waiving a record that was genuinely owed and holding otherwise-ready work.

So the guards here are aimed at three things a careless edit would take back:

* **The decision is made at plan time, by the planner** -- not composed from the diff
  by the agent that just wrote the code. That is what makes the plan reviewer's
  finding-7 scrutiny reach it, and it is the property `/review-close` Step 2d assumes
  when it declines to re-judge whether a test *should* exist.
* **One write, not two.** Item `3-tier` runs before any test decision has been
  written. A separate `## Also fixed` write there would land with no
  `## Test decision` section to sit after, and the record item appending afterwards
  would invert the order `tasks/schema.md` calls load-bearing. `/claim-task` avoids
  this by making them one write; this path now does too.
* **The read-back is SHALLOW, and says so.** An earlier cut of this phase tried to
  assert the record itself and was disqualified by its own review round: fence-blind
  in the permissive direction (a legal form quoted inside `## Plan` satisfied it while
  the real section was empty) and false-failing 166 of 207 real consumer bodies in the
  strict one. `test_the_read_back_block_executes` runs the shipped block rather than
  describing it, and now pins the honest contract -- an empty section PASSES. The
  strong check needs a fence-aware single-section reader and is filed as `Q-462`.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from _reversal import assert_no_reversal, slice_between

REPO_ROOT = Path(__file__).resolve().parent.parent

BUILD = REPO_ROOT / "core" / "skills" / "auto-build" / "SKILL.md"
CLAIM = REPO_ROOT / "core" / "skills" / "claim-task" / "SKILL.md"
CLOSE = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"
SCHEMA = REPO_ROOT / "core" / "companion" / "tasks" / "schema.md"

# The item's own marker. U+2011 (non-breaking hyphen), matching the sibling `3-tier`
# marker this file already shipped -- a plain ASCII hyphen here would not match the
# file and every assertion below would fail loudly rather than silently, which is the
# behaviour we want from a mismatch.
RECORD_MARKER = "3‑record."
TIER_MARKER = "3‑tier."


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def strict_slice(text: str, start: str, end: str, name: str, *, limit: int) -> str:
    """`slice_between` with the two properties every slice in this module needs.

    Both were bought by mutations that walked the first version of these guards, and
    both are about the same weakness: `slice_between` takes the FIRST match of each
    anchor, so a slice is only as trustworthy as its anchors are unique.

    * **Each anchor occurs exactly once.** Otherwise a decoy carrying every needle can
      be pasted immediately BEFORE the real text and the slice binds to it -- the real
      instruction is then free to say the opposite with the suite green. The round did
      exactly that: a five-line decoy above item 3-record let the real item be rewritten
      to "write whichever copy of the body is easiest to reach; the primary checkout's
      is fine", with 1,111 tests passing. Duplicating the END anchor is the same attack
      from the other side -- it truncates the slice so a cancelling sentence falls
      outside it.
    * **The slice is bounded.** An anchor that moves can silently widen a slice to
      thousands of characters of unrelated prose, where any incidental mention
      satisfies every assertion. That is not hypothetical either: this module's own
      plan-skeleton slice was 17,726 characters before the author-side battery caught
      it.

    The bounds are sized from the CURRENT slices with roughly 20-30% headroom. They
    are a tripwire for an anchor that has moved, not a budget for prose -- a slice
    that outgrows its bound because the text legitimately grew wants the bound
    re-derived and the new figure recorded here, which is a different act from
    nudging it up to get green.

    **Sizings, newest last, so a re-derivation is auditable rather than a number
    that moved:**

    * Phase 277, at first sizing: record 5,886 / tier 3,007 / plan 1,409 / skeleton 195.
    * Phase 278: the tier item gained `Q-410`'s filing bar -- the naming test, its four
      legal answers, its four exemptions, the ledger destination and the Step 3b
      interaction -- and the record item gained the ledger append. **One bound moved,
      three did not, and the round corrected this entry twice.** The first version
      re-derived only the bound that was crossed and said "the other three bounds ...
      none moved", which enumerated two of three and never mentioned the Sequence
      slice at all; the round measured it and it had moved the most in absolute terms.
      Post-round measurements, every `strict_slice` call site:

      | slice | pre-phase | now | bound | headroom |
      |---|---|---|---|---|
      | `3-tier` item | 3,007 | 4,682 | 4,000 -> **5,900** | 20.6% |
      | `3-record` item | 5,886 | 6,728 | 7,000 (unchanged) | 3.9% |
      | Step 7c Sequence | 13,684 | 16,201 | 18,000 (unchanged) | 10.0% |
      | plan structure | 1,409 | 1,409 | 2,000 (unchanged) | 29.6% |

      **The "roughly 20-30% headroom" sizing rule above describes how a bound is set
      when it is first written, NOT an invariant these must maintain** -- the first
      version of this entry implied the latter, which is why it read as though three
      bounds were now wrong. A bound here is a tripwire for a **moved anchor**, and a
      moved anchor widens a slice by thousands of characters, so 3.9% headroom still
      catches the thing it exists to catch. Raising the two that merely narrowed would
      *weaken* the tripwire to buy a number, which is the nudge this file forbids. The
      one bound that moved did so because its slice **crossed**, and is the only case
      that licenses a raise.
    """
    assert text.count(start) == 1, (
        f"{name}: start anchor occurs {text.count(start)} times, expected exactly 1. "
        "A slice built on a repeated anchor binds to whichever copy comes first, so a "
        "decoy carrying the asserted strings makes every check below vacuous while the "
        "real text says the opposite."
    )
    assert text.count(end) == 1, (
        f"{name}: end anchor occurs {text.count(end)} times, expected exactly 1. "
        "A duplicated end anchor truncates this slice, moving text out of reach of the "
        "assertions and reversal screens that are supposed to cover it."
    )
    sliced = slice_between(text, start, end, name)
    assert len(sliced) < limit, (
        f"{name}: slice is {len(sliced)} characters against a {limit} bound. An anchor "
        "has moved and this slice now spans unrelated prose. Re-anchor it; raising the "
        "bound is how a slice stops meaning anything."
    )
    return sliced


def record_item() -> str:
    """The `3-record` Sequence item, from its marker to the item that follows it."""
    return strict_slice(
        read(BUILD),
        f"\n{RECORD_MARKER} **Persist the `## Test decision`**",
        "\n4. **Post-fix convention verification**",
        "auto-build 3-record item",
        limit=7000,
    )


def tier_item() -> str:
    """Item `3-tier`, which delegates its `## Also fixed` write to `3-record`."""
    return strict_slice(
        read(BUILD),
        f"\n{TIER_MARKER} **When the work surfaces something adjacent",
        f"\n{RECORD_MARKER} **Persist the `## Test decision`**",
        "auto-build 3-tier item",
        limit=5900,
    )


def plan_structure() -> str:
    return strict_slice(
        read(BUILD),
        "2. **Produce the plan.** Structure:",
        "3. **Hard constraints:**",
        "auto-build plan structure",
        limit=2000,
    )


# ---------------------------------------------------------------- the plan structure


def test_the_plan_structure_asks_the_planner_for_a_test_decision() -> None:
    """Step 7a must request the decision, or nothing downstream has one to write.

    Read inside the plan-structure block rather than file-wide: after this phase the
    string `## Test decision` occurs several times in this file (the executor item,
    the skeleton, the prose), so a file-wide check would go green on a plan structure
    that had lost the element entirely.
    """
    structure = plan_structure()
    assert "`## Test decision`" in structure, (
        "auto-build's Step 7a plan structure no longer asks the plan-only agent for a "
        "`## Test decision`. Without it the executor's item 3-record has nothing to "
        "persist, and the plan reviewer's finding-7 scrutiny has nothing to judge -- "
        "which is the state Q-460 describes."
    )
    for form in ("test <X> proves <Y>", "no test because <Z>"):
        assert form in structure, (
            f"auto-build's plan structure no longer names the legal form {form!r}. "
            "Both forms are declared in tasks/schema.md section 'Test decision'. The "
            "read-back does not check them (it is shallow by design), so this element "
            "is the only place the planner learns what a legal record looks like."
        )


def test_the_planner_is_told_to_decide_and_not_to_write() -> None:
    """The planner is forbidden from editing files; a plan that tells it to write lies.

    Step 7a's hard constraints already say "Do NOT edit any file in the worktree". An
    element telling that same agent to write the section into the body would be an
    instruction it cannot follow, and the reader most likely to try is a future author
    copying `/claim-task` element 4 verbatim -- where the planner DOES add a plan step
    for the write, because there the executor reads the plan from disk.
    """
    structure = plan_structure()
    assert "Decide it; do not write it." in structure, (
        "auto-build's plan structure lost the decide-don't-write instruction. The "
        "plan-only agent is forbidden from editing files (Step 7a hard constraints), "
        "so the element must route the write to Step 7c item 3-record."
    )
    assert RECORD_MARKER.rstrip(".") in structure, (
        "auto-build's plan structure no longer names the item that performs the write. "
        "A planner that cannot see where the decision goes has no way to tell whether "
        "the hand-off exists."
    )


def test_the_plan_skeleton_orders_the_section_before_implementation_steps() -> None:
    """The skeleton is what a plan-only agent actually copies.

    Position matters for the same reason it does in the body: the executor reads the
    plan as raw text, and a decision buried after the implementation steps reads as an
    afterthought to the agent absorbing it. `/claim-task` puts its element before the
    steps too.
    """
    text = read(BUILD)
    # Anchored on `<task summary>` (unique in the file), NOT on "```plan".
    #
    # The first cut sliced "```plan" -> "## Implementation Steps" and was WRONG in the
    # way rule 1 calls "where it looks": the first "```plan" is ~18k characters earlier,
    # in Phase 6a's orchestrator prose ("wrapped in a fenced ```plan block"), so the
    # slice spanned 17,726 characters of unrelated text -- including the plan-structure
    # bullet's own `## Test decision` mention. Deleting the section from the skeleton
    # left this test GREEN, satisfied by an incidental occurrence. Found by this phase's
    # own battery (M03).
    skeleton = slice_between(text, "<task summary>", "\n```\n````", "auto-build plan skeleton")
    assert len(skeleton) < 600, (
        f"the plan skeleton slice is {len(skeleton)} characters, which is not a skeleton "
        "-- an anchor has moved and this slice now spans unrelated prose, where an "
        "incidental mention will satisfy every assertion below. Re-anchor it; do not "
        "raise this bound."
    )
    assert "## Test decision" in skeleton, (
        "auto-build's plan skeleton no longer shows `## Test decision` before "
        "`## Implementation Steps`. The skeleton is the thing the plan-only agent "
        "copies; an element documented in prose but absent from the skeleton is the "
        "half that gets dropped."
    )
    # The assertion this test is NAMED for, and it was missing. Round mutation M-D1
    # moved `## Test decision` to AFTER `## Implementation Steps` and every check
    # passed: the three assertions were a length bound, a presence check, and the
    # coverage-gap ordering. The docstring argued the position at length and nothing
    # tested it.
    steps = skeleton.find("## Implementation Steps")
    decision = skeleton.find("## Test decision")
    assert steps != -1 and decision != -1 and decision < steps, (
        "auto-build's plan skeleton no longer places `## Test decision` BEFORE "
        "`## Implementation Steps`. The executor reads the plan as raw text, and a "
        "decision printed after the steps reads as an afterthought to the agent "
        "absorbing it -- which is the whole argument this test is named for."
    )
    gap = skeleton.find("### Coverage gap")
    assert gap != -1 and gap < decision, (
        "auto-build's plan skeleton no longer places `## Test decision` after the "
        "`### Coverage gap` subsection. Coverage gap belongs to `## Constraints & "
        "Risks`; hoisting the decision above it would nest it under the wrong heading."
    )


# ---------------------------------------------------------------- the Sequence item


def test_the_sequence_has_a_record_item_between_the_tier_and_convention_verification()  -> None:
    """The item must exist, and its position is the rule -- not its presence alone."""
    text = read(BUILD)
    tier_at = text.find(f"\n{TIER_MARKER}")
    record_at = text.find(f"\n{RECORD_MARKER}")
    convention_at = text.find("\n4. **Post-fix convention verification**")
    assert record_at != -1, (
        "auto-build Step 7c's Sequence has no `3-record` item. This is the Q-460 "
        "defect exactly: the skill consumes `## Test decision` records in its "
        "Auto-Build Complete section while shipping nothing that writes one."
    )
    assert tier_at < record_at < convention_at, (
        "auto-build Step 7c's Sequence items are out of order "
        f"(tier={tier_at}, record={record_at}, convention={convention_at}). The record "
        "write must follow the tier item -- they are ONE write, and the tier's "
        "`## Also fixed` lines are placed relative to the `## Test decision` section "
        "this item creates."
    )


def test_the_record_item_writes_the_worktree_copy() -> None:
    """A main-checkout write is on no branch, so Step 2d can never see it."""
    item = record_item()
    assert "<WORKTREE_PATH>/tasks/" in item, (
        "auto-build's record item no longer names the worktree copy as the write "
        "target. An edit in the main checkout is on no branch, never reaches the PR, "
        "and `/review-close` Step 2d reads this record at the branch tip."
    )
    assert "never the main checkout" in item, (
        "auto-build's record item lost the prohibition on writing the main checkout. "
        "Naming the right path without forbidding the wrong one has been insufficient "
        "at this class of site before."
    )


def test_the_record_item_refuses_to_invent_the_decision() -> None:
    """Composing a record from the diff substitutes unreviewed judgment for reviewed.

    `/claim-task` Step 8 states this prohibition for the same reason ("Do not compose
    it yourself from the diff"). It matters more here, because there is no
    orchestrator re-read on this path to catch a fabricated record.
    """
    item = record_item()
    assert "do not compose one from the diff" in item, (
        "auto-build's record item lost its refusal to invent the decision. The whole "
        "value of a plan-time record is that a different agent decided it and a "
        "reviewer scrutinised the rationale."
    )
    assert "say in your final message" in item, (
        "auto-build's record item no longer routes a missing plan element into the "
        "final message. The envelope is the only channel to the human on this path, "
        "so a provenance gap that is not stated there is a gap nobody learns about."
    )


def test_the_record_item_states_why_it_is_one_write_not_two() -> None:
    """The ordering rationale is the reason the tier item delegates.

    Without it, the next author to read `3-tier`'s delegation reasonably "fixes" it by
    restoring a local write -- which reintroduces the inverted order.
    """
    item = record_item()
    tier = slice_between(
        read(BUILD),
        "Three tiers; take the first that fits.",
        f"\n{RECORD_MARKER} **Persist the `## Test decision`**",
        "auto-build tier block",
    )
    assert "the same write as item" in tier and RECORD_MARKER.rstrip(".") in tier, (
        "auto-build's tier 1 no longer delegates the `## Also fixed` write to the "
        "record item. Two independent writes invert the schema order: the tier runs "
        "first, so its section would land with no `## Test decision` to sit after."
    )
    assert "One write, not two" in tier, (
        "auto-build's tier 1 lost the statement of WHY the write is delegated. The "
        "bare delegation reads as style, and style gets undone."
    )
    # The delegation phrases above can all stand while a LOCAL write is added back
    # beside them -- which is the whole softening class `_reversal` exists for, and
    # this phase's battery (M09) walked straight through the two `in` checks above by
    # doing exactly that. So assert the absence of a write target in the tier block:
    # the worktree path belongs to the record item and nowhere else on this path.
    assert "<WORKTREE_PATH>/tasks/" not in tier, (
        "auto-build's tier block names a body write path of its own. Two writes invert "
        "the schema order -- the tier runs before any `## Test decision` exists, so its "
        "section lands with nothing to sit after and the record item's later write "
        "leaves `## Also fixed` behind `## Plan`. The write target belongs to item "
        "3-record alone."
    )
    m = re.search(r"placed after [^.]*?`## Test decision`[^.]*?`## Plan` section", item)
    assert m, (
        "auto-build's record item no longer carries the placement rule 'placed after "
        "... `## Test decision` ... before any `## Plan` section'. If you edited this "
        "file through an UNQUOTED heredoc, check for eaten spans -- a `#`-leading "
        "backtick span becomes a command substitution and then a comment, and vanishes "
        "silently. That is exactly how Phase 276 shipped this sentence with three "
        "spans destroyed."
    )


def test_the_record_item_carries_no_reversal_vocabulary() -> None:
    """Presence checks cannot see a sentence added beside them that cancels them.

    Phase 276's round wrote 64 mutations against that phase's first cut and watched 51
    survive; roughly twenty were this one move. `tests/_reversal.py` is the layer built
    for it, and the round's finding was that it had been wired to `/review-close` and
    to none of the prompts an executor reads.
    """
    assert_no_reversal(
        record_item(),
        "auto-build Sequence item 3-record",
        exempt=(
            # The item's honest statements of what the shallow check does NOT prove.
            # These are bounds on the CHECK, not softenings of the requirement to write
            # the record -- and they are load-bearing: the cut that claimed more than
            # this was disqualified by the round for certifying clean over the failure
            # it named. A stale exemption is itself a failure here, which is how the
            # first of these was caught when the prose around it was rewritten.
            "It does **not** verify that the record is real",
            "a hit can be a quotation",
        ),
        extra=(
            "optional",
            "if you have time",
            "best effort",
            "where practical",
            "not strictly required",
        ),
    )


# ---------------------------------------------------------------- the read-back runs


def _read_back_block() -> str:
    """The shipped bash block from the record item -- extracted, not retyped."""
    item = record_item()
    fences = re.findall(r"```bash\n(.*?)```", item, re.S)
    assert len(fences) <= 1, (
        f"auto-build's record item carries {len(fences)} ```bash blocks. This extractor "
        "takes the FIRST, so a decoy block above the real one redirects every execution "
        "test in this module onto a fixture while the shipped command is free to be "
        "gutted. The round demonstrated it with the suite green."
    )
    m = re.search(r"```bash\n(.*?)```", item, re.S)
    assert m, (
        "auto-build's record item no longer carries a ```bash read-back block. The "
        "write is the step most often skipped on the sibling path (measured at three "
        "of four branches on one consumer cycle), and this path has no orchestrator "
        "re-read to catch it."
    )
    return m.group(1)


@pytest.mark.parametrize(
    "body_text,expected_exit,why",
    [
        pytest.param(
            "# T\n\n## Test decision\ntest tests/test_x.py::test_y proves the guard blocks\n\n## Plan\n",
            0,
            "a written record passes",
            id="proves-form",
        ),
        pytest.param(
            "# T\n\n## Test decision\nno test because the change is docs-only\n",
            0,
            "the other legal form passes",
            id="no-test-form",
        ),
        pytest.param(
            "# T\n\n### Test Decision\nTest tests/a.py PROVES the thing\n",
            0,
            "heading level and case are both insensitive, per the schema",
            id="case-and-level-insensitive",
        ),
        pytest.param(
            "# T\n\n## Test decision\n\n## Also fixed\n- x\n",
            0,
            "an empty section PASSES, and that is the honest contract -- this check "
            "catches the write that did not happen, not a write that landed thin. The "
            "version that tried to reject this was fence-blind in the other direction "
            "and false-failed 166 of 207 real bodies; see Q-462.",
            id="empty-section-passes-shallow",
        ),
        pytest.param(
            "# T\n\n## Requirements\nstuff\n",
            1,
            "no heading at all is grep's own no-match exit",
            id="no-heading",
        ),
    ],
)
def test_the_read_back_block_executes(
    tmp_path: Path, body_text: str, expected_exit: int, why: str
) -> None:
    """Run the shipped block. Author-side rule 3: run the commands the change prescribes.

    The defects that mattered at this class of site came from *executing* the recipe,
    not reading it -- so this substitutes the fixture path into the block's own `body=`
    assignment and runs the rest verbatim.
    """
    block = _read_back_block()
    body = tmp_path / "task.md"
    body.write_text(body_text, encoding="utf-8")

    # Substitute only the assignment's right-hand side; everything after it is shipped
    # text run as-is. A retyped block would pass while the file rotted.
    #
    # `\s*` is load-bearing: the fence sits inside a numbered list item, so every line
    # of the shipped block carries three spaces of list indentation. An anchored
    # `^body=` matched nothing and this test reported the block as missing its
    # assignment -- a false negative that would have read as a real defect.
    patched, n = re.subn(
        r'^\s*body=".*"$', f'body="{body}"', block, count=1, flags=re.M
    )
    assert n == 1, (
        "auto-build's read-back block no longer opens with a `body=\"...\"` "
        "assignment, so this test cannot point it at a fixture. Update the "
        "substitution deliberately rather than deleting this test."
    )

    proc = subprocess.run(
        ["/bin/bash", "-c", patched], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == expected_exit, (
        f"the shipped read-back returned {proc.returncode}, expected {expected_exit} "
        f"-- {why}\nstdout: {proc.stdout!r}\nstderr: {proc.stderr!r}"
    )


def test_the_read_back_rejects_an_unsubstituted_placeholder() -> None:
    """Exit 2 -- run fully verbatim, placeholder intact.

    Without the `case` guard an unsubstituted path makes `grep` exit 2 for a missing
    FILE, which reads exactly like a missing RECORD and sends the executor into a
    rewrite loop against a path that does not exist.
    """
    proc = subprocess.run(
        ["/bin/bash", "-c", _read_back_block()],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 2, (
        "the shipped read-back no longer exits 2 on an unsubstituted placeholder path "
        f"(got {proc.returncode}). stderr: {proc.stderr!r}"
    )
    assert "placeholder not substituted" in proc.stderr, (
        "the placeholder guard fired but said something else; the message is what "
        "tells the executor this is a path bug and not a missing record."
    )



# ---------------------------------------------------------------- the reader agrees


def test_review_close_no_longer_lists_auto_build_as_a_non_writer() -> None:
    """The enumeration justifying the fourth disposition was made false by this fix.

    It read "`/auto-fix` writes the record 0 times, `/auto-judge` 0, `/auto-build` 1 --
    an incidental aside". After Phase 277 `/auto-build` writes it, and the sentence
    would otherwise tell a reader the opposite of what the tree does.
    """
    text = read(CLOSE)
    assert "`/auto-build` **1**" not in text, (
        "/review-close still counts `/auto-build` as writing the record once (an "
        "incidental aside). Phase 277 gave it a real writer at Step 7c item 3-record; "
        "the count is now wrong in the direction that matters -- it tells the human a "
        "record was never owed when it was."
    )
    assert RECORD_MARKER.rstrip(".") in text, (
        "/review-close no longer names `/auto-build`'s record item. Step 2d's premise "
        "paragraph enumerates who writes the record; a writer missing from that list "
        "is how the fourth disposition gets offered for a task that genuinely owed one."
    )


def test_review_close_still_justifies_the_fourth_disposition() -> None:
    """Removing `/auto-build` from the non-writer list must not empty the list.

    `/auto-fix`, `/auto-judge` and hand-cut branches still write no record, and that is
    the whole ground for "Record not owed". A fix that deleted the enumeration would
    leave the disposition unexplained and the next author would delete it as dead.
    """
    text = read(CLOSE)
    for skill in ("`/auto-fix` writes the record **0** times", "`/auto-judge` **0**"):
        assert skill in text, (
            f"/review-close lost {skill!r} from Step 2d's premise paragraph. Those are "
            "the remaining genuine non-writers and they are why the fourth disposition "
            "exists at all."
        )
    assert "hand-cut branch writes none" in text, (
        "/review-close lost the hand-cut-branch case from the non-writer enumeration."
    )
    assert '"Record not owed — no orchestrated plan ran"' in text, (
        "/review-close lost the fourth disposition itself. It is what separates a "
        "waiver (the record was owed and is being let through) from a task that never "
        "owed one -- the conflation the Step 8 tally was mispricing."
    )


def test_the_schema_names_both_writing_paths() -> None:
    """The schema is the contract six readers cite; it named one writer of two."""
    section = slice_between(
        read(SCHEMA), "### Test decision", "### ", "schema Test decision section"
    )
    assert "`/auto-build`" in section, (
        "tasks/schema.md section 'Test decision' no longer names `/auto-build` as a "
        "writer. It is the contract the skills cite; a path that writes the record "
        "while the contract says it does not is how Q-460 stayed invisible."
    )
    assert "`/claim-task` Step 7a" in section, (
        "tasks/schema.md lost `/claim-task` from the writer list while naming the "
        "other path. Both write it; the schema states both."
    )


def test_both_executor_sites_persist_the_record() -> None:
    """The parity claim, asserted rather than trusted.

    `/auto-build` Step 7c's convention-verification item advertises itself as "the same
    gate `/claim-task` Step 7e's executor runs internally". Phase 277 makes the record
    write parallel too, and a later edit to either site alone would silently break the
    symmetry both files assert.
    """
    for path, marker in ((CLAIM, "3. **Persist the `## Test decision`**"), (BUILD, f"{RECORD_MARKER} **Persist the `## Test decision`**")):
        assert marker in read(path), (
            f"{path.name} no longer carries a 'Persist the `## Test decision`' "
            "Sequence item. Both executor paths write this record; a path that stops "
            "writing it reaches /review-close Step 2d classified `missing` on every "
            "branch, and -- because both claim through claim_task.sh --lock -- with "
            "the fourth disposition withheld."
        )


# ------------------------------------------------- properties, not spellings
#
# Everything below was bought by the round's guard-strength lens, which wrote 30
# mutations against the first cut of this module and watched 21 of 27 survive. Its
# central finding: the checks above prove the STRINGS are present. Four different
# rewordings restored the second body write with `the same write as item`,
# `3-record` and `One write, not two` all byte-perfect, because the only negative
# check pinned one path spelling rather than the property.


def test_the_tier_item_forbids_the_main_checkout_where_the_decision_is_made() -> None:
    """The prohibition has to live in the tier block, not only in the record item.

    Round mutation M04 licensed a main-checkout mirror write FROM the tier block --
    "Mirror the same line into the main checkout's copy of the body too" -- and stayed
    green, because `never the main checkout` was asserted only inside `record_item()`.
    An edit there is on no branch and reaches no PR, so the line would be recorded
    where /review-close Step 2d can never read it.
    """
    tier = tier_item()
    assert "never the main checkout" in tier, (
        "auto-build's tier block no longer forbids the main checkout at the point the "
        "executor decides to record a fix. The record item saying so one item later "
        "does not stop this item licensing the opposite."
    )


def test_the_tier_item_carries_no_second_write_licence() -> None:
    """The property: this item delegates the write. It never performs or permits one.

    A spelling check cannot express that, so this screens the reversal shapes the round
    actually used, plus the generic layer. All four of its survivors kept every pinned
    phrase intact and added a sentence beside them.
    """
    assert_no_reversal(
        tier_item(),
        "auto-build Sequence item 3-tier",
        exempt=(
            # The delegation itself names a write; that is the instruction, not a licence.
            "**the same write as item 3‑record**",
        ),
        extra=(
            # Round survivors M01-M03, by shape rather than by their exact wording.
            "append the line",
            "write it here",
            "mirror the same line",
            "yourself rather than going back",
            "as you go",
            "must then leave",
            "easiest to reach",
            "a later sync",
            "primary checkout",
            "main checkout's copy",
        ),
    )


def test_the_plan_structure_carries_no_reversal_vocabulary() -> None:
    """Round M24 exempted the whole class the record exists for.

    Appending "for a docs, config or rename task, leave it out and let the executor
    settle it from the diff" left every assertion green -- and item 3-record's
    "if the plan carries none" arm would then fire by design rather than by accident,
    which is the record's provenance guarantee quietly inverted.
    """
    assert_no_reversal(
        plan_structure(),
        "auto-build Step 7a plan structure",
        extra=(
            "leave it out",
            "settle it from the diff",
            "only when the task changes behaviour",
            "writing the section yourself is better",
            "if your harness lets you",
        ),
    )


def test_the_schema_test_decision_section_carries_no_reversal_vocabulary() -> None:
    """The sibling section already had this layer; the one this phase edited did not.

    Round M26 kept both writer names present -- which is all
    `test_the_schema_names_both_writing_paths` checks -- while asserting that nothing
    on the auto-build path persists the record and that such a branch "was never owed
    a record". That is the contract six readers cite, saying the opposite of the tree.
    """
    assert_no_reversal(
        slice_between(read(SCHEMA), "### Test decision", "### Also fixed",
                      "schema Test decision section"),
        "tasks/schema.md section Test decision",
        exempt=(
            # The section's own account of the retired validator invariant. It states
            # what is NOT checked and why, which is a bound on enforcement, not a
            # softening of the requirement to record the decision.
            "**The validator does not check this**",
        ),
        extra=(
            "never owed a record",
            "nothing on that path persists",
            "still reaches Step 2d classified",
        ),
    )


def test_review_close_does_not_call_auto_build_a_non_writer_in_any_wording() -> None:
    """Round M09 restored the false claim without the eight characters we pinned.

    "`/auto-build` writes it **once** -- an incidental aside ... treat an autonomous
    branch as never having owed a record" passed every check, and that sentence decides
    whether a human is offered "Record not owed" for a branch that genuinely owed one --
    which is the whole reason Q-460 was filed.
    """
    premise = slice_between(
        read(CLOSE),
        "> **The premise sentence above is accurate about `/claim-task`",
        "This is the sibling of Step 3c's manual-smoke gate",
        "review-close Step 2d premise paragraph",
    )
    assert_no_reversal(
        premise,
        "review-close Step 2d premise paragraph",
        exempt=(
            # The genuine non-writers. Naming them is the ground for the fourth
            # disposition, not a softening -- and emptying this list would leave that
            # disposition unexplained.
            "`/auto-fix` writes the record **0** times, `/auto-judge` **0**",
            # The paragraph's own statement of the distinction the fourth disposition
            # exists to draw. It describes the two populations; it does not place
            # /auto-build in the wrong one. Exempted rather than reworded because this
            # is the sentence that explains why `Waive` and `Record not owed` are
            # different answers, and it predates this phase.
            "a task that was never owed a record and a task whose record is genuinely "
            "missing",
        ),
        extra=(
            "never having owed",
            "an incidental aside",
            "only *mentions* the heading",
            "writes it **once**",
            "treat an autonomous branch as",
        ),
    )


def test_the_tier_block_anchor_is_pinned_to_the_record_item() -> None:
    """Round M28: reverting the re-anchor was green, in the guard file alone.

    `TIER_BLOCKS["auto-build"]` was re-anchored this phase from item 4 to the record
    item, because inserting `3-record` between them had silently widened that slice to
    cover an item that is not the tier -- so the reversal screens there were reading
    prose they were never scoped to. Nothing detected the widening, which meant the
    tier's own guards could be neutralised by editing the test file and no shipped file
    at all.
    """
    import test_fix_in_branch_tier as T

    _, _, end = T.TIER_BLOCKS["auto-build"]
    assert RECORD_MARKER.rstrip(".") in end, (
        "test_fix_in_branch_tier.TIER_BLOCKS['auto-build'] no longer ends at the record "
        f"item (end anchor is {end!r}). Anchoring it at item 4 again puts item 3-record "
        "inside the tier slice, so that module's reversal screens read an item they are "
        "not scoped to and the tier's own bounds go partly unread."
    )


def test_no_later_sequence_item_cancels_the_record() -> None:
    """The softening does not have to be inside the slice it softens.

    Round mutation M13 appended to item **4** -- one item after the record -- "(If item
    3-record's read-back reported a problem, it is enough to mention it in your final
    message; the branch does not need to be held for it.)" and the suite stayed green.
    Same executor, same reading order, no slice covered it.

    So this screens the WHOLE Sequence, items 1 through 7, rather than the two items
    this phase edited. It is deliberately the one check here with a large population:
    the property is "nothing in this agent's instruction list takes the record back",
    and a per-item screen can always be evaded by moving one item down.
    """
    sequence = strict_slice(
        read(BUILD), "### Sequence", "### Hard constraints",
        "auto-build Step 7c Sequence", limit=18000,
    )
    assert_no_reversal(
        sequence,
        "auto-build Step 7c Sequence",
        exempt=(
            # Item 3-record's honest bounds on the SHALLOW check, exempted in the
            # record-item screen above for the same stated reason: they limit what the
            # check proves, not whether the record must be written.
            "It does **not** verify that the record is real",
            "a hit can be a quotation",
            # The delegation. Naming the write is the instruction.
            "**the same write as item 3‑record**",
            # Item 7's no-retry rule, which is a deliberate budget, not a softening.
            "do **NOT** add a retry loop",
        ),
        extra=(
            "does not need to be held",
            "enough to mention it",
            "it is fine to skip",
            "you may omit the record",
            "the record is optional",
            "carry on without",
        ),
    )


# The bounds themselves. Every `limit=` above is prose until something reads it:
# the round raised the tier bound to 20,000 and the Sequence bound to 40,000 and
# the suite stayed green, so "re-derived, not nudged" was a discipline with no
# enforcement. Pinning the values makes a silent raise red and a deliberate one a
# visible edit to this list, with the sizing table above as its record.
EXPECTED_BOUNDS = {
    "auto-build 3-record item": 7000,
    "auto-build 3-tier item": 5900,
    "auto-build plan structure": 2000,
    "auto-build Step 7c Sequence": 18000,
}


def test_no_slice_bound_is_raised_silently() -> None:
    src = Path(__file__).read_text(encoding="utf-8")
    pat = re.compile(r'"(auto-build [^"]+)",\s*limit=(\d+)')
    found = {name: int(limit) for name, limit in pat.findall(src)}
    assert found == EXPECTED_BOUNDS, (
        f"a slice bound changed without this list changing with it: {found!r} against "
        f"{EXPECTED_BOUNDS!r}. Raising a bound is how a slice stops meaning anything, "
        "and the docstring's re-derivation rule had no enforcement until this test. A "
        "legitimate raise edits this dict AND records the new sizing in the table above."
    )
