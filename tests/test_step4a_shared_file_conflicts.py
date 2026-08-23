"""Phase 178 — Step 4a's Sysop-written shared append files (upstream #307).

Three defects this pins, each verified by repro before the fix was written:

1. Step 4a step 3 aborted-and-skipped on ANY rebase conflict, while the prose
   four lines later said resolve-don't-abort. `tasks/index.yml` was named in no
   conflict context anywhere in the skill (grep index.yml n conflict -> 0),
   though `/document-work` REQUIRES every follow-up-filing branch to append to
   it. Marker-stripping the conflict leaves one entry holding `id:` alone while
   the next absorbs the shared field block -- and it still parses with unique
   ids, so nothing downstream notices.

2. Step 4c consolidated every pending-doc with no merged-branch filter, so a
   4a-skipped branch's doc was routed, its task flipped `done`, its body moved
   to `archive/` and its lock dropped -- with the code never merged.

3. The `pr` cleanup iterated "each approved feature branch" and ran
   `git branch -D` with safe `-d` explicitly bypassed. A 4a-skipped branch is
   still approved, is not `dirty`-SKIP'd and is not rejected, so nothing
   preserved it -- and Step 3b had already removed its worktree.

The guards are ORDERING properties, not token-presence checks. Phase 174's round
walked 30 of 57 mutations through presence-style guards; a check that asserts a
word appears in a 700-character paragraph proves nothing about what the step
does. Each property below fails if the two halves are reordered even when every
token survives.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "core" / "skills" / "review-close" / "SKILL.md"
WORKFLOW = REPO / "core" / "companion" / "docs" / "WORKFLOW.md"


def _norm(text: str) -> str:
    """Collapse whitespace so a legitimate reflow stays green."""
    return re.sub(r"\s+", " ", text)


def _section(text: str, start: str, end: str) -> str:
    """Slice [start, end).

    Fails with a NAMED error rather than a bare ValueError: an independent
    reviewer renamed `### 4a. Merge Approved Feature Branches` — an ordinary
    editorial act — and every test in this module errored with nothing
    identifying the cause. It also takes the LAST occurrence of `end`, because
    writing `### 4a-post.` as a forward cross-reference inside Step 4a
    truncated the slice and reddened the module for the same reason.
    """
    try:
        i = text.index(start)
    except ValueError:  # pragma: no cover - diagnostic path
        raise AssertionError(
            f"section anchor {start!r} not found. If the heading was renamed "
            f"deliberately, update _section's anchors — this is a guard-maintenance "
            f"failure, not a defect in the skill."
        ) from None
    j = text.rfind(end)
    if j <= i:
        raise AssertionError(
            f"section end anchor {end!r} not found after {start!r}."
        )
    return text[i:j]


@pytest.fixture(scope="module")
def skill() -> str:
    return SKILL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def step_4a(skill: str) -> str:
    return _section(skill, "### 4a. Merge Approved Feature Branches", "### 4a-post.")


@pytest.fixture(scope="module")
def step_4c(skill: str) -> str:
    return _section(skill, "### 4c. Consolidate Pending Documentation", "### 4d.")


# --------------------------------------------------------------------------
# Defect 1 -- Step 4a
# --------------------------------------------------------------------------


def test_index_yml_is_named_in_a_conflict_context(step_4a: str) -> None:
    """The original zero: `index.yml` appeared 21x in the skill, 0x near a conflict."""
    body = _norm(step_4a)
    assert "tasks/index.yml" in body, "Step 4a must name the file that conflicts"
    # A proximity window is not enough: renaming the bullet to "the task index"
    # left the file named only inside the `git show :2:tasks/index.yml` commands
    # a few hundred characters away, and the window stayed satisfied. Require
    # the ENUMERATION ITSELF to name it -- that is the thing a reader routes on.
    bullets = re.findall(r"^- \*\*(.+?)\*\*", step_4a, re.M)
    assert any("tasks/index.yml" in b for b in bullets), (
        "the shared-append-files list must name `tasks/index.yml` as one of its "
        f"entries — found only: {bullets}"
    )
    assert any("review_tasks.md" in b for b in bullets), (
        "the list must also name `review_tasks.md`"
    )


def test_abort_is_not_the_unconditional_first_response(step_4a: str) -> None:
    """Reversion detector for the exact sentence that shipped the defect."""
    body = _norm(step_4a)
    assert (
        "If rebase has conflicts: `git rebase --abort`, report the conflict, skip that branch."
        not in body
    ), "the unconditional abort-and-skip instruction is back"
    assert "route by which file conflicted" in body


def test_reader_never_meets_continue_before_the_validator(step_4a: str) -> None:
    """ORDERING: no reading of Step 4a may reach `--continue` without the gate.

    This is why step 3's forward reference names the gate rather than saying
    "resolve, then --continue" -- the first draft did, and a reader who stopped
    at step 3 was told to continue with nothing checked. Survives reflow and
    rewording; fails if the two are swapped.
    """
    body = _norm(step_4a)
    val = body.index("validate_tasks.py")
    cont = body.index("rebase --continue")
    assert val < cont, (
        "validate_tasks.py must be named BEFORE the first `git rebase --continue` -- "
        "running it after is the shipped defect (it first ran at Step 4c, "
        "downstream of the merge and of close_batch.sh's commit)"
    )


def test_validator_is_a_prescribed_command_not_just_a_mention(step_4a: str) -> None:
    """STRUCTURAL: the gate must be an executable block, not prose about a gate.

    The first version of this guard compared first-occurrence indices only, and
    a mutation that lifted the command OUT of its fenced block survived it --
    the step-3 mention kept the index ordering intact while the thing an
    operator actually runs had moved. Assert the block, not the word.
    """
    fences = re.findall(r"```bash\n(.*?)```", step_4a, re.S)
    assert any("validate_tasks.py" in f for f in fences), (
        "`python3 sysop/scripts/validate_tasks.py` must appear inside a ```bash "
        "block in Step 4a -- a prose mention is not a prescribed command"
    )
    # ...and it must not have drifted into the stage-extraction block, which runs
    # before the resolution exists.
    for f in fences:
        if "validate_tasks.py" in f:
            assert "git show :2:" not in f, (
                "the validator must be its own step, after the resolution is written"
            )


def test_marker_stripping_is_forbidden_not_merely_discouraged(step_4a: str) -> None:
    body = _norm(step_4a)
    assert "Never resolve either by stripping" in body
    # The reason must be stated, because the corruption is invisible to a diff read.
    assert "parses" in body or "yaml.safe_load` accepts it" in body


def test_stage_numbering_is_stated_and_not_inverted(step_4a: str) -> None:
    """Stage 2 = merge target, stage 3 = replayed commit. Verified by execution."""
    body = _norm(step_4a)
    assert re.search(r"stage 2 is the merge target", body), "stage 2 must be the merge target"
    assert re.search(r"stage 3 is the commit being replayed", body)
    assert ":2:tasks/index.yml" in body and ":3:tasks/index.yml" in body


def test_4a_skip_is_a_distinct_verdict(step_4a: str) -> None:
    body = _norm(step_4a)
    assert "4a-SKIP" in body
    assert "different verdict" in body or "*different* verdict" in body


# --------------------------------------------------------------------------
# Defect 2 -- Step 4c
# --------------------------------------------------------------------------


def test_containment_filter_precedes_routing(step_4c: str) -> None:
    """ORDERING: the filter is worthless if it runs after the routing table."""
    body = _norm(step_4c)
    filt = body.index("git rev-list --count")
    route = body.index("| Type | PROJECT_STATUS |")
    assert filt < route, (
        "the merged-branch filter must run BEFORE the routing table that flips "
        "task state -- after it, the task is already `done`"
    )


def test_filter_uses_an_enumerated_read_only_git_subcommand(step_4c: str) -> None:
    """`merge-base` is not in permission-guard's documented read-only set; rev-list is."""
    body = _norm(step_4c)
    assert "git rev-list --count" in body
    assert "git merge-base --is-ancestor \"<branch" not in body, (
        "the prescribed command must not rely on an inferred-read-only subcommand"
    )


def test_not_merged_means_hold_not_route(step_4c: str) -> None:
    body = _norm(step_4c)
    assert "NOT-MERGED" in body or "non-zero" in body
    assert "do not route it" in body
    assert "do not touch its task IDs" in body
    assert "do not delete it" in body


def test_4c_cleanup_does_not_delete_the_docs_the_filter_held_back(step_4c: str) -> None:
    """The filter is worthless if a later step in the SAME step deletes what it kept.

    Step 4c's own cleanup item said "Delete all remaining
    `sysop/runtime/pending-docs/*.md` files" — five items after 1b holds one
    back. The worktree is gone and the doc is untracked, so that delete is
    unrecoverable: the exact class the filter exists to close, re-entered.
    """
    body = _norm(step_4c)
    assert "Delete all remaining `sysop/runtime/pending-docs/*.md` files" not in body, (
        "the unqualified pending-docs delete is back — it destroys any doc "
        "step 1b held back for an unmerged branch"
    )
    assert "Delete the pending-docs **this step consolidated**" in body
    assert "only if it is now empty" in body


def test_unresolvable_branch_stops_rather_than_guessing(step_4c: str) -> None:
    body = _norm(step_4c)
    assert "stop and ask" in body, (
        "an undecidable branch must not silently default in either direction"
    )


# --------------------------------------------------------------------------
# Defect 3 -- the `pr` force-delete
# --------------------------------------------------------------------------


def test_pr_cleanup_does_not_iterate_approved(skill: str) -> None:
    body = _norm(skill)
    assert (
        "Each **approved** feature branch reached `main` through a **squash**" not in body
    ), "the `pr` cleanup is iterating 'approved' again -- that is the force-delete hole"
    assert "Each **merged** feature branch reached `main` through a **squash**" in body


def test_containment_check_precedes_the_force_delete(skill: str) -> None:
    """ORDERING: the -D is licensed by containment, so the check must come first."""
    body = _norm(skill)
    guard = body.index("`-D` is licensed by containment")
    delete = body.index("Delete the **local** branch: `git branch -D <branch>`")
    assert guard < delete


def test_4a_skip_branch_is_preserved_under_both_policies(skill: str) -> None:
    body = _norm(skill)
    block = _section(
        body,
        "For each **4a-SKIP'd** branch",
        "For each **rejected** branch",
    )
    assert "do NOT delete it" in block
    assert "do NOT force-delete it" in block
    assert "both** policies" in block or "both policies" in block


# --------------------------------------------------------------------------
# Spec agreement -- WORKFLOW.md was the root cause in Phase 170; keep them paired
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow() -> str:
    return _norm(WORKFLOW.read_text(encoding="utf-8"))


def test_spec_states_conflicts_are_routed_not_aborted(workflow: str) -> None:
    assert "A rebase conflict is routed, not reflexively aborted" in workflow
    assert "4a-SKIP" in workflow


def test_spec_consolidation_filters_before_routing(workflow: str) -> None:
    step7 = workflow.index("**Consolidate documentation**")
    filt = workflow.index("first drop any pending-doc whose branch did not actually merge")
    route = workflow.index("route its entries to the shared docs", step7)
    assert step7 <= filt < route


def test_spec_cleanup_keys_on_the_merged_set_not_approved(workflow: str) -> None:
    """An earlier draft prescribed an ancestry re-check here; it can never pass
    after a squash (see test_step4a_shared_file_behaviour.py). The spec must key
    on what step 5 merged, and must say why re-deriving it is not available."""
    assert 'iterate the branches step 5 actually merged, never "approved"' in workflow
    assert "Do not try to re-derive that containment here" in workflow


# --- polarity: the guards lens flipped every meaning and nothing noticed ------


def _polarity(text: str) -> str:
    i = text.index("git rev-list --count")
    return text[i : i + 400]


def test_skill_states_zero_means_merged(step_4c: str) -> None:
    """Flipping this inverts the whole filter: it would then drop exactly the
    merged docs and consolidate exactly the unmerged ones. Nothing pinned it."""
    seg = _norm(_polarity(step_4c))
    assert "`0` means merged" in seg
    assert "`0` means NOT merged" not in seg
    assert "non-zero" in seg


def test_spec_and_skill_agree_on_the_polarity(workflow: str, step_4c: str) -> None:
    """Cross-file: a mutation set the skill to 0=merged and the spec to
    0=unmerged, and both files' own guards stayed green."""
    assert "`0` = merged" in workflow, "the spec must state the same polarity"
    assert "`0` = unmerged" not in workflow
    assert "`0` means merged" in _norm(step_4c)


def test_caret_operand_is_quoted_in_both_files(step_4c: str, workflow: str) -> None:
    """Unquoted, `^HEAD` is a zsh glob that silently inverts the answer."""
    assert '"^HEAD"' in step_4c
    assert '"^HEAD"' in workflow
    assert 'count "<branch from frontmatter>" ^HEAD' not in step_4c


# --------------------------------------------------------------------------
# Negative controls -- a guard that reds on correct prose is a defect too
# --------------------------------------------------------------------------


def test_guards_survive_a_legitimate_reflow(step_4a: str) -> None:
    """Rewrapping the section must not red any ordering property."""
    reflowed = step_4a.replace("\n", "\n   ").replace("  ", " ")
    body = _norm(reflowed)
    assert body.index("validate_tasks.py") < body.index("rebase --continue")


def test_ordering_guard_is_not_vacuous(step_4a: str) -> None:
    """Plant the defect: swap the two halves and require the property to fail."""
    body = _norm(step_4a)
    val = body.index("validate_tasks.py")
    cont = body.index("rebase --continue")
    mutated = (
        body[:val]
        + "rebase --continue"
        + body[val + len("validate_tasks.py") : cont]
        + "validate_tasks.py"
        + body[cont + len("rebase --continue") :]
    )
    assert mutated.index("validate_tasks.py") > mutated.index("rebase --continue"), (
        "the mutation did not actually invert the order -- this guard proves nothing"
    )


def test_the_continue_is_prescribed_non_interactively(step_4a: str) -> None:
    """`Q-233`. A bare `git rebase --continue` opens an editor on a conflict-resolved
    continue — measured on git 2.50.1, and an unchanged commit message does NOT skip it.
    With no editor configured git falls back to `vi`: inside this harness that **hangs to
    the tool timeout** (exit 143), and with stdin closed it exits 1 leaving the rebase
    mid-replay, which is a state Step 4a has no arm for. The autonomous close cannot
    survive either.

    Asserted as *the bare form is gone*, not *the safe form is present*: shipping both
    leaves the agent to pick, and the bare one is the shorter, more familiar spelling.
    """
    body = step_4a
    assert "git -c core.editor=true rebase --continue" in body, (
        "Step 4a no longer prescribes the non-interactive continue"
    )
    # Line-anchored: the safe form ends in the bare form's own words, so a plain
    # `not in` can never distinguish them.
    import re
    bare = re.findall(r"(?<!core\.editor=true )git rebase --continue", body)
    assert not bare, (
        f"Step 4a still prescribes a bare `git rebase --continue` ({len(bare)} site(s)) — "
        "that is the form that opens vi and hangs the close"
    )
