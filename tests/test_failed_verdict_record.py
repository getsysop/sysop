"""Drift guard — the FAIL verdict has a durable write, and DROP still closes.

Phase 157. Two defects in the same file, both making `review_tasks.md` overstate
what a review round actually resolved.

**The reported one (upstream #207)** was that `close_batch.sh` flips every open
checkbox in a batch's range, so a task an agent left unfinished renders `[x]`
directly above its own failure note. Verifying it turned up something worse one
layer up: `> Failed:` had **zero occurrences in the shipped tree**.
`/auto-judge`'s FAIL verdict was the only one of three with no durable write —
everything else about FAIL was *terminal output*. So the annotation the reporter
saw had been invented by their agent, and a spec-compliant run is quieter still.
**A script cannot key on a marker nothing produces**, which is why the write side
is guarded here alongside the read side.

**The unreported sibling** was that `/auto-judge` contradicted itself on DROP,
27 lines apart: § Verdicts said leave the checkbox `[ ]` *because* `close_batch.sh`
counts it at merge, § Instructions said mark `[x]`. Following the second makes the
task invisible to that count, so the Grand Total's done *and* open both drift by
one per dropped task.

## Why these guards look the way they do — the round rebuilt them

The first version of this file asserted whole-section substring presence, and the
adversarial round demonstrated it guarded **nothing that mattered**:

- Inverting *both* FAIL directives to "mark `[x]`" — the exact defect this phase
  exists to prevent — left all ten tests green. The assertion was
  `"leave the checkbox" in section`, and both sections already contain that
  phrase **for DROP**, so the FAIL half was never covered.
- Running the guard against the *pre-fix* file, whose FAIL verdict read only
  "Report FAIL and continue", passed.
- Inserting a decoy `## Verdicts` section and renaming the real one passed,
  because `_section` took the first match and nothing asserted uniqueness.
- The DROP contradiction could be reintroduced verbatim by keeping the old rule
  in a "(this is no longer required)" history clause.

So the guards are now **per-verdict**, not per-section: each of DROP and FAIL is
extracted as its own block from the enumerated verdict list, and each block must
carry its own rule. Sections must be unique. `WORKFLOW.md` and `auto-fix` are
covered too — the round found neither was constrained at all.

**Honest ceiling, stated so nobody trusts these more than they should.** These
are string assertions over natural-language instructions. They now kill every
mutation the round produced, but a determined rewrite can still satisfy them
while meaning the opposite. The guard is a ratchet against drift, not a proof of
correctness; the adversarial round is what actually checks meaning.

**On vocabulary pinning.** The round also showed the *opposite* failure: the old
guards forbade rewording that was behaviourally harmless (changing the template
to the bold `> **Failed:**` form the code explicitly accepts broke the suite).
Structure and the copyable template are pinned; wording around them is free.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AUTO_JUDGE = REPO_ROOT / "core/skills/auto-judge/SKILL.md"
AUTO_FIX = REPO_ROOT / "core/skills/auto-fix/SKILL.md"
WORKFLOW = REPO_ROOT / "core/companion/docs/WORKFLOW.md"
REVIEW_CLOSE = REPO_ROOT / "core/skills/review-close/SKILL.md"
CLOSE_BATCH = REPO_ROOT / "core/companion/scripts/close_batch.sh"
ARCHIVE = REPO_ROOT / "core/companion/scripts/archive_review_tasks.py"

MARKER = "> Failed:"
DROP_MARKER = "> Dropped:"

# The *directive* form — the two-space-indented template with a placeholder, i.e.
# the literal an agent copies into review_tasks.md. Asserted instead of the bare
# marker because a mutation showed the bare form survives deletion of the
# instruction: the paragraph explaining why the annotation matters still mentions
# `> Failed:`, so a guard on the marker alone stays green while the thing that
# produces it is gone.
FAIL_TEMPLATE = "> Failed: <"
DROP_TEMPLATE = "> Dropped: <"

# A verdict bullet in either section: "3. **FAIL** — …" or "- **FAIL**: …".
# Structural, not lexical — it pins that the three verdicts are enumerated, which
# is a real contract, and leaves every word around them free.
_VERDICT_START = re.compile(r"^[ \t]*(?:\d+\.|-)[ \t]+\*\*(FIX|DROP|FAIL)\*\*")

# An affirmative instruction to close a task. Occurrences preceded by a negation
# are allowed, so the file may keep explaining *why* not to — the anti-pattern
# Phase 155's round named is a guard whose cheapest path to green is deleting the
# explanation.
_MARK_DONE = re.compile(r"\bmark(?:ed|ing|s)?\b[^.\n]{0,48}?`?\[x\]`?", re.I)
_NEGATION = re.compile(r"\b(?:not|never|n't|without|rather than|instead of)\b", re.I)
# `close_batch.sh will mark it [x] at merge` is a description of the SCRIPT, not
# an instruction to the agent — the DROP bullet says exactly that, and says it
# as the *reason* the checkbox is left alone. Treating the script as a subject
# is what keeps this an instruction check rather than a ban on the token `[x]`.
_SCRIPT_SUBJECT = re.compile(r"close_batch(?:\.sh)?", re.I)


def _section(path: Path, heading: str) -> str:
    """Return the body of the `## <heading>` section, asserting it is unique.

    The uniqueness assertion is the fix for the decoy-section attack: without it
    a second `## Verdicts` containing the guarded strings satisfies every check
    while the real, renamed section says the opposite.
    """
    text = path.read_text(encoding="utf-8")
    needle = f"\n## {heading}\n"
    first = text.find(needle)
    assert first != -1, f"{path.name} has no `## {heading}` section"
    assert text.find(needle, first + 1) == -1, (
        f"{path.name} has more than one `## {heading}` section — these guards "
        "read the first, so a duplicate can shadow the operative text"
    )
    rest = text[first + 1 :]
    end = rest.find("\n## ", 1)
    return rest if end == -1 else rest[:end]


def _verdict_block(section_body: str, verdict: str) -> str:
    """Return just the `**<verdict>**` bullet and its indented continuation.

    Per-verdict rather than per-section because DROP and FAIL make *opposite*
    claims about the checkbox, and a section-wide substring check cannot tell
    which one it matched — the hole the round exploited to invert FAIL while
    every test stayed green. Slicing here also defeats relocating a directive to
    a distant part of a 100+ line section.
    """
    lines = section_body.splitlines()
    starts = [(i, m.group(1)) for i, l in enumerate(lines) if (m := _VERDICT_START.match(l))]
    found = [i for i, name in starts if name == verdict]
    assert found, (
        f"no `**{verdict}**` bullet found — the three verdicts must stay an "
        f"enumerated list; these guards key on that structure"
    )
    begin = found[0]
    later = [i for i, _ in starts if i > begin]
    return "\n".join(lines[begin : (later[0] if later else len(lines))])


def _instructs_closing(block: str) -> bool:
    """True when the block affirmatively tells an *agent* to mark a task `[x]`.

    Two kinds of `[x]` mention are legitimate and must not trip this: an explicit
    negation ("do not mark `[x]`") and a description of what `close_batch.sh`
    does at merge — the DROP bullet contains the second as its whole rationale.
    Allowing both is what keeps this an instruction check rather than a ban on
    the token, which would push a future author to delete the explanation.
    """
    for m in _MARK_DONE.finditer(block):
        preceding = block[max(0, m.start() - 60) : m.start()]
        if _NEGATION.search(preceding) or _SCRIPT_SUBJECT.search(preceding):
            continue
        return True
    return False


# === the marker exists on both sides =======================================


def test_close_batch_recognises_the_marker_a_skill_writes():
    # The root defect: a read side keyed to a marker no shipped skill produced.
    # Assert the *matcher*, not a bare literal — `close_batch.sh` never contains
    # the plain string, so an earlier version of this test could only ever pin a
    # comment, and its failure message blamed the mechanism for a prose edit.
    assert re.search(r"is_failed\s*\(", CLOSE_BATCH.read_text(encoding="utf-8")), (
        "close_batch.sh no longer has a Failed-annotation matcher — the read "
        "side of the FAIL verdict is gone"
    )
    producers = [
        p.name
        for p in (AUTO_JUDGE, AUTO_FIX)
        if FAIL_TEMPLATE in p.read_text(encoding="utf-8")
    ]
    assert producers, (
        "No shipped skill instructs an agent to write `> Failed:`. close_batch.sh "
        "keys on it, so with no producer a failed task closes as done and the "
        "round's record overstates itself — the state Phase 157 fixed."
    )


@pytest.mark.parametrize(
    "variant",
    ["> Failed:", "> **Failed:**", ">Failed:", "> FAILED:", "> failed :"],
)
def test_close_batch_tolerates_the_forms_an_agent_actually_writes(variant):
    # Each of these silently closed the task before the round widened the
    # matcher. `> FAILED:` mattered most: all-caps FAILED is /auto-judge's own
    # vocabulary at :300, :304 and :360 — everywhere except the one place the
    # read side looked.
    import subprocess

    prog = re.search(
        r"readonly CLOSE_AWK='(.*?)'\n", CLOSE_BATCH.read_text(encoding="utf-8"), re.S
    ).group(1)
    doc = f"### Batch 1 — B `Pending`\n- [ ] **T1**: a\n  {variant} reason\n"
    out = subprocess.run(
        ["awk", "-v", "s=1", "-v", "e=9", "-v", "mode=count", prog],
        input=doc, capture_output=True, text=True,
    ).stdout.strip()
    assert out == "0 1", f"{variant!r} was not honoured (got {out!r}, want '0 1')"


def test_one_awk_program_serves_both_the_count_and_the_rewrite():
    # The count sets TASKS_IN_BATCH (→ the Grand Total); the rewrite decides
    # which boxes flip. Two copies could disagree about what a failed task looks
    # like, desyncing the totals from the file they describe.
    body = CLOSE_BATCH.read_text(encoding="utf-8")
    assert body.count("readonly CLOSE_AWK=") == 1, (
        "the checkbox pass is no longer single-sourced"
    )
    assert body.count('"$CLOSE_AWK"') == 2, (
        "expected exactly two invocations of the shared checkbox program "
        "(mode=count and mode=flip)"
    )


@pytest.mark.parametrize(
    "task_line",
    [
        "- [ ] **TASK-1**: bolded id",
        "- [ ] task one",          # the shape tests/test_close_batch_sh.py itself uses
        "- [/] **TASK-2**: in progress",
        "- [/] plain in progress",
    ],
)
def test_both_scripts_agree_on_what_an_open_task_line_is(task_line):
    # `close_batch.sh` decides whether to hold a task open; `archive_review_tasks.py`
    # decides whether to warn before moving it out of the live queue. The round
    # found them disagreeing — the archive regex required a `**bold**` id and the
    # awk did not — so an unbolded task was protected by one and swept out
    # silently by the other. Behavioural, because the first version of this test
    # asserted on the regex's source text and passed vacuously.
    import subprocess

    import archive_review_tasks as art

    prog = re.search(
        r"readonly CLOSE_AWK='(.*?)'\n", CLOSE_BATCH.read_text(encoding="utf-8"), re.S
    ).group(1)
    doc = f"### Batch 1 — B `Pending`\n{task_line}\n  > Failed: reason\n"
    held = subprocess.run(
        ["awk", "-v", "s=1", "-v", "e=9", "-v", "mode=count", prog],
        input=doc, capture_output=True, text=True,
    ).stdout.strip()
    assert held == "0 1", f"close_batch did not hold {task_line!r} open"
    assert art.UNFINISHED_TASK_RE.match(task_line), (
        f"close_batch.sh holds {task_line!r} open but archive_review_tasks.py "
        "does not recognise it as a task — so archiving would move it out of the "
        "live queue with no warning"
    )


# === each verdict carries its own rule =====================================


@pytest.mark.parametrize("heading", ["Verdicts", "Instructions"])
def test_fail_verdict_tells_the_agent_to_annotate(heading):
    block = _verdict_block(_section(AUTO_JUDGE, heading), "FAIL")
    assert FAIL_TEMPLATE in block, (
        f"/auto-judge § {heading}'s FAIL bullet no longer carries the "
        f"`{FAIL_TEMPLATE}…` template — without it the verdict leaves no "
        "durable trace, which is the defect this phase fixed"
    )


@pytest.mark.parametrize("heading", ["Verdicts", "Instructions"])
def test_fail_verdict_does_not_tell_the_agent_to_close_the_task(heading):
    # The mutation that beat the first version of this file: invert FAIL to
    # "mark `[x]`" and every test stayed green, because the guard matched DROP's
    # copy of the phrase. Scoped to the FAIL bullet, inversion now fails.
    block = _verdict_block(_section(AUTO_JUDGE, heading), "FAIL")
    assert not _instructs_closing(block), (
        f"/auto-judge § {heading}'s FAIL bullet instructs marking the task "
        "`[x]`. A FAIL means the work was not done; closing it is what "
        "upstream #207 reported."
    )
    assert re.search(r"leave the checkbox", block, re.I), (
        f"/auto-judge § {heading}'s FAIL bullet no longer states that the "
        "checkbox is left alone; close_batch.sh's exclusion depends on it"
    )


@pytest.mark.parametrize("heading", ["Verdicts", "Instructions"])
def test_drop_verdict_still_leaves_the_box_for_close_batch(heading):
    # The 2026-07-27 contradiction, and the shape that could reintroduce it: keep
    # the rule in a "(no longer required)" history clause while the operative
    # sentence says mark `[x]`. Scoped to the DROP bullet, that fails.
    block = _verdict_block(_section(AUTO_JUDGE, heading), "DROP")
    assert DROP_MARKER in block, f"/auto-judge § {heading}'s DROP bullet lost its annotation"
    assert "`[ ]`" in block, (
        f"/auto-judge § {heading}'s DROP bullet no longer states that the "
        "checkbox stays `[ ]` for close_batch.sh to flip"
    )
    assert not _instructs_closing(block), (
        f"/auto-judge § {heading}'s DROP bullet instructs pre-marking `[x]`. "
        "close_batch.sh counts only `[ ]`/`[/]`, so a pre-marked task is "
        "invisible to it and the Grand Total drifts by one per drop."
    )


# === the other shipping sites are constrained too ==========================


def test_auto_fix_keeps_the_drop_leaves_the_box_rule():
    # The round found this site unguarded: it could be inverted to "mark `[x]`
    # yourself" with the whole suite green.
    body = AUTO_FIX.read_text(encoding="utf-8")
    assert DROP_MARKER in body, "auto-fix lost the `> Dropped:` convention"
    line = next(l for l in body.splitlines() if "False-positive" in l and DROP_MARKER in l)
    assert "`[ ]`" in line and "close_batch.sh" in line, (
        "auto-fix's false-positive bullet no longer ties the `[ ]` checkbox to "
        "close_batch.sh flipping it at merge"
    )
    assert not _instructs_closing(line), (
        "auto-fix's false-positive bullet now instructs marking `[x]` directly"
    )


def test_auto_judge_defines_each_verdict_exactly_twice():
    # The wholesale-substitution attack: rename the operative `## Verdicts` and
    # drop a compliant lookalike in its place. Section uniqueness does not catch
    # that (there is still exactly one `## Verdicts` — the fake), but the file
    # gains a third enumeration of the three verdicts, and two is the contract:
    # once in § Verdicts, once in § Instructions. This is a structural bound, so
    # every word inside the bullets stays free.
    body = AUTO_JUDGE.read_text(encoding="utf-8")
    for verdict in ("FIX", "DROP", "FAIL"):
        n = sum(
            1
            for line in body.splitlines()
            if (m := _VERDICT_START.match(line)) and m.group(1) == verdict
        )
        assert n == 2, (
            f"/auto-judge enumerates **{verdict}** {n} times; expected exactly 2 "
            "(§ Verdicts and § Instructions). A third is how an operative "
            "section gets shadowed by a compliant-looking copy."
        )


def test_workflow_close_step_names_the_exclusion():
    # WORKFLOW.md § 2.8's close step is where a human reads what close_batch.sh
    # will do to the boxes. The round deleted the exclusion clause here with the
    # whole suite green.
    line = next(
        l for l in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if "close_batch.sh <N1>" in l
    )
    assert MARKER in line, (
        "WORKFLOW.md's close step no longer says that `> Failed:` tasks stay "
        "open — it describes the flip as unconditional, which it is not"
    )


def test_workflow_states_both_verdict_rules():
    # Nothing in the suite constrained WORKFLOW.md's verdict text at all — the
    # scripts-table guard only checks that a row per script exists.
    body = WORKFLOW.read_text(encoding="utf-8")
    drop_line = next(l for l in body.splitlines() if "**DROP**" in l and DROP_MARKER in l)
    assert "`[ ]`" in drop_line and not _instructs_closing(drop_line), (
        "WORKFLOW.md § 2.7b's DROP bullet no longer states the leave-`[ ]` rule"
    )
    fail_line = next(l for l in body.splitlines() if "**FAIL**" in l and MARKER in l)
    assert not _instructs_closing(fail_line), (
        "WORKFLOW.md § 2.7b's FAIL bullet now instructs marking `[x]`"
    )
    assert "Failed" in WORKFLOW.read_text(encoding="utf-8").split("### 8.4")[1].split("### 8.5")[0], (
        "the § 8.4 close_batch.sh row no longer documents the `> Failed:` exclusion"
    )


def test_review_close_documents_the_exclusion():
    # Missed by the phase's first pass and caught by the round: Step 4b still
    # said the script "marks all task checkboxes `[x]`", one line under the
    # invocation, which is the doc a human reads while running it.
    body = REVIEW_CLOSE.read_text(encoding="utf-8")
    assert MARKER in body, (
        "review-close Step 4b no longer documents that `> Failed:` tasks are "
        "left open — it is the doc shown at the moment close_batch.sh is run"
    )
