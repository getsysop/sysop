"""Phase 350 — pins for the triage's in-branch wording fixes
(internal tracker #778, #782, #783, #784).

Each was a statement the tree contradicted or a runner instruction missing at the
one site that needs it. The behaviour fixes (internal tracker #766, #772, #774) carry executable
tests in their own modules; these are the text fixes, pinned by the sentence a
runner acts on and by the stale form that must not return.
"""

from __future__ import annotations

from pathlib import Path
from skill_runner_text import text_of

REPO = Path(__file__).resolve().parent.parent
RC = text_of(REPO / "core/skills/review-close/SKILL.md")
CT = (REPO / "core/skills/claim-task/SKILL.md").read_text(encoding="utf-8")
WF = (REPO / "core/companion/docs/WORKFLOW.md").read_text(encoding="utf-8")


def _line_with(text: str, needle: str) -> str:
    hits = [ln for ln in text.splitlines() if needle in ln]
    assert len(hits) == 1, f"{needle!r}: expected one line, found {len(hits)}"
    return hits[0]


def test_the_strip_loop_names_the_loop_safe_rm_form() -> None:
    """Claude Code's rm check refuses an unguarded variable in the path, and no allow
    rule can override it. Phase 350 (internal tracker #778) and Phase 379 guarded the strip
    loop's `rm -f`; Phase 422 (`Q-665`) removed the loop, since `rm` binds no rule under
    `dontAsk` either: the strip is `close_state.py strip-links`, and Step 3b runs no `rm`."""
    assert 'python3 sysop/scripts/close_state.py strip-links "<worktree-path>"' in RC
    assert 'rm -f "<worktree-path>/$entry"' not in RC, "the unguarded form is back"
    assert 'rm -f -- "<worktree-path>/' not in RC, "the shell strip loop is back"


def test_the_gh_api_rule_does_not_describe_a_call_4b_no_longer_makes() -> None:
    rule = _line_with(RC, "- `Bash(gh api:*)` —")
    # Phase 351 round 1: the rule also covers Step 4d's waived-smoke-FAIL comment, a POST.
    # Phase 360 (`Q-632`): and 4d-1's two job reads.
    assert rule == (
        "- `Bash(gh api:*)` — the ruleset lookup (`repos/{owner}/{repo}/rulesets`) that Step 4d "
        "command 4b's could-not-measure note points at. Command 4b itself is `gh pr view`. "
        "It also POSTs Step 4d's waived-smoke-FAIL comment under the PR-reuse shape. "
        "Step 4d-1 reads a failing check's Actions job and its annotations with it. `gh api` "
        "can write, so the rule is a deliberate grant rather than an inference from the verb")
    trigger = _line_with(RC, "**The trigger is PR state, never the merge command's exit status or stderr.**")
    assert ("**A third cause is not a stuck PR at all and is handled before the merge, not here: "
            "command 4b printed `0`.**") in trigger
    assert "total_count" not in trigger


def test_range_gates_are_told_how_to_read_step_4a_merges() -> None:
    """Pinned whole: the per-commit and content halves prescribe opposite flags, and
    swapping them is a one-word edit."""
    para = _line_with(WF, "A gate that scans a commit range must read the merges Step 4a makes")
    assert para == (
        '**A gate that scans a commit range must read the merges Step 4a makes.** `/review-close`'
        ' Step 4a merges a branch that is already on the remote with `git merge --no-ff`, which p'
        "uts that branch's commits on the merge commit's *second* parent, and any conflict resolu"
        'tion only in the merge commit itself. A per-commit gate (a commit-message lint, an "N of'
        ' N commits scanned" count) run at `4a-post` with `--no-merges --first-parent` walks only'
        " `main`'s own commits and reports a complete, clean pass over a range it never read: sco"
        'pe it as `git rev-list --no-merges <base>..HEAD`, without `--first-parent`. A content ga'
        'te (a secret scanner) must not use `--no-merges` at all, because it then skips the resol'
        'ution: scan `git log -p -a --no-textconv --diff-merges=first-parent --first-parent <base'
        '>..HEAD` from the repository root (git 2.31 or later), which diffs each merge against it'
        's first parent and so carries everything its branch brought in, resolution included. `-a'
        '` and `--no-textconv` keep files marked binary or given a `textconv` driver as their rea'
        'l text, and a subdirectory under `diff.relative` narrows the output to itself. Not `-m`:'
        " it follows the consumer's `log.diffMerges`, and under any non-default value it drops th"
        "e branch's content."
    )


def test_only_the_batch_cleanup_waits_for_the_merge() -> None:
    assert "Both are gated on the close having actually landed" not in CT
    assert ("Only the batch half waits for the close to land on `main`. Under `pr` policy Step 4c "
            "runs on the integration branch before the PR merges, so a roadmap claim's lock, park "
            "marker and claim directory are already gone if the merge never lands. `/review-close` "
            "Step 6's *Lock-as-real-time-signal invariant* covers the lock and the park marker, not "
            "the claim directory.") in CT
    # The note sits in Step 4c's program, `close_index.py` since Phase 386: an absence read
    # against the skill alone would pass on the stale wording.
    ci = (REPO / "core/companion/scripts/close_index.py").read_text(encoding="utf-8")
    assert "invariant note in Step 4-pre for why pre-merge death" not in RC + ci
    assert "invariant note in Step 6 for why pre-merge death" in ci
    assert "**Lock-as-real-time-signal invariant (`pr` policy).**" in RC


# Round 2 found substring pins walked by ordinary edits; these are whole-text.
_RECIPE = text_of(REPO / "core/skills/review-close/SKILL.md")


def _exact_line(text: str, prefix: str) -> str:
    hits = [ln for ln in text.splitlines() if ln.startswith(prefix)]
    assert len(hits) == 1, f"{prefix!r}: {len(hits)} lines"
    return hits[0]


# Phase 425 (`Q-629`) retired the REMOVED, TARGET and lead bullets these pinned whole: the
# arm runs `resolve_append_conflict.py`, whose behaviour on each shape is executed in
# `tests/test_resolve_append_conflict.py`. What the runner reads now is the outcome lines and
# the exit routing, pinned here whole.
def test_the_resolver_line_names_each_outcome() -> None:
    line = _exact_line(_RECIPE, "It starts from the merge target's file")
    for word in ("(`APPENDED:`)", "(`APPLIED:`)", "(`REMOVED:`)", "(`KEPT OUT:`)"):
        assert word in line, word
    assert "It starts from the merge target's file and changes only what the branch changed" in line


def test_the_refusal_routes_to_4a_skip() -> None:
    line = _exact_line(_RECIPE, "- **Exit 1** prints a `REFUSED:` line")
    assert line.endswith("Abort and 4a-SKIP the branch, per item 4."), line


def test_each_exit_routes_where_the_script_means_it() -> None:
    """Phase 425's round (lens B, M1): Exits 0, 2, 3 and 4 and the body-file rule could each be
    rewritten with every guard green once the arm's digest was re-made."""
    assert _exact_line(_RECIPE, "- **Exit 0** prints").endswith("Stage and gate it, below.")
    assert _exact_line(_RECIPE, "- **Exit 4** prints").endswith(
        "two actors moved that task's status. Report both values and STOP.")
    two = _exact_line(_RECIPE, "- **Exit 2**: nothing was written")
    assert "stop and show its line. **Exit 3**: an operand is still a placeholder; write it out and re-run." in two
    body = _exact_line(_RECIPE, "**A conflicted body file under `tasks/`**")
    assert "**Under `--headless`, STOP**" in body and "abort and 4a-SKIP the branch" in body
    assert "read both sides and keep both edits" in body
    assert "**Never `--continue` past a red validator.**" in _RECIPE
    assert '```bash\npython3 sysop/scripts/resolve_append_conflict.py index --since "<ref>" "<branch>"\n```' in _RECIPE
    assert '```bash\npython3 sysop/scripts/resolve_append_conflict.py index\n```' in _RECIPE


def test_the_semgrep_message_and_check_description_name_both_guards() -> None:
    sem = (REPO / "packs/postgres/companion/semgrep/missing_writer_engine_guard.yaml").read_text(encoding="utf-8")
    # Q-636 widened both texts to name the guard forms the rule accepts since then
    # (`is None`, getattr, an operand of an `or`). Both reference forms stay named.
    assert (
        '    message: >\n      writer_engine.$METHOD() called without a null-guard in $F. Add one '
        'at\n      function entry on the same reference the call uses ("if not\n      writer_engine'
        ':" or "if not <instance>.writer_engine:") to prevent\n      AttributeError when DB_PASS_W'
        'RITER is unset. "is None", a getattr with\n      no default or a None one, and the check '
        'as one operand of an "or" are\n      guards too.\n'
    ) in sem
    frag = (REPO / "packs/postgres/companion/checks.yml.fragment").read_text(encoding="utf-8")
    assert (
        "      writer_engine.<method>() called in a function with no null-guard\n      before it on "
        "the same reference ('if not writer_engine:' or\n      'if not <instance>.writer_engine:'; "
        "'is None', a getattr with no\n      default or a None one, and the test as one operand of "
        "an 'or' count\n      too)."
    ) in frag


def test_the_recipe_bases_on_the_merge_target() -> None:
    # Phase 425: the resolver starts from stage 2's text; the union instruction it replaced
    # must not come back beside it.
    assert "It starts from the merge target's file" in _RECIPE
    assert "append only the entries whose `id` it does not already carry" not in _RECIPE
