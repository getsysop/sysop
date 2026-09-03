"""`Q-342` + `Q-352` — what Step 2b hands its reviewers, and how many fleets it runs.

`Q-342`: step 1 pasted `## Prevention Conventions` alone while step 0's skip
predicate (Phase 241) read three sources, so a target could survive the gate
*because* of a rule in `## Testing Patterns` and then be reviewed against a
taxonomy that did not contain it. Option (a) — widen the paste — was taken over
the filing's preferred (c), which only makes the shipped template
self-consistent and leaves every consumer who already followed it unfixed.

`Q-352`: Step 2b routed every merging diff against the convention map and never
against `security_map.md`, so the security map's judgment layer ran at audit time
only. A second fleet now runs, glob-gated, with the same `VERDICT: BLOCKED`
authority.

**The load-bearing test is behavioural.** Step 1's threshold-measurement command
is executable prose, so it is extracted from the skill and RUN against synthetic
`CLAUDE.md` fixtures with known section sizes. A `SECTIONS` list that drops a
section, a regex whose boundary is wrong, or a heredoc that does not parse all
redden it. The remaining assertions are textual because their subject is prose,
and each names a decision taken against a stated alternative rather than a
wording.
"""
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from _reversal import assert_no_reversal

REPO_ROOT = Path(__file__).resolve().parents[1]
REVIEW_CLOSE = REPO_ROOT / "core/skills/review-close/SKILL.md"
CLAIM_TASK = REPO_ROOT / "core/skills/claim-task/SKILL.md"

# THE REVERSAL LAYER lives in `tests/_reversal.py` (Phase 253, `Q-367`). This module
# carried its own 13-entry copy from Phase 247 until then; the shared list is a
# superset of it minus `will do`, whose retirement is recorded in that module and in
# `Q-367`'s archive entry.


def _measurement_command():
    """Step 1's conventions-threshold measurement, lifted out of the skill.

    Anchored on the `SECTIONS = [` line rather than on a comment, so rewording
    the surrounding prose does not detach the guard from its subject. Returns the
    dedented shell command.
    """
    text = REVIEW_CLOSE.read_text(encoding="utf-8")
    m = re.search(
        r"```bash\n(   # Measure the WIDENED set.*?\n)   ```", text, re.S,
    )
    assert m, "step 1's widened-set measurement fence is gone"
    body = textwrap.dedent(m.group(1))
    assert "SECTIONS = [" in body, body
    return body


def _run_measure(tmp_path, claude_md):
    (tmp_path / "CLAUDE.md").write_text(claude_md, encoding="utf-8")
    r = subprocess.run(["bash", "-c", _measurement_command()], cwd=tmp_path,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_the_measurement_counts_every_convention_section_not_just_the_first(tmp_path):
    """The defect, expressed as arithmetic.

    Two rule-bearing sections with distinguishable sizes and a decoy `##
    Architecture` between them. A command that measures `## Prevention
    Conventions` alone reports the first number; the widened one reports the sum
    and must not swallow the decoy.
    """
    pc = "x" * 500
    tp = "y" * 300
    arch = "z" * 900
    doc = (
        "# CLAUDE.md\n\n"
        f"## Prevention Conventions\n\n{pc}\n\n"
        f"## Architecture\n\n{arch}\n\n"
        f"## Testing Patterns\n\n{tp}\n"
    )
    out = _run_measure(tmp_path, doc)
    nums = [int(n) for n in re.findall(r"^\s*(\d+)", out, re.M)]
    assert len(nums) == 3, out                       # two sections + TOTAL
    per_section, total = nums[:2], nums[2]
    assert total == sum(per_section), out
    assert total > 500 + 300, out                    # both bodies counted
    # The decoy is descriptive, not rule-bearing, and must not be in the paste.
    assert total < 500 + 300 + 900, (
        f"`## Architecture` was counted -- the set must be the rule-bearing "
        f"sections, not every section\n{out}"
    )
    assert "## Testing Patterns" in out, out


def test_an_absent_section_contributes_zero_rather_than_crashing(tmp_path):
    """A consumer with no `## Testing Patterns` has no testing conventions to
    route against, which is not the same as a broken read. The command must say
    `(absent)` and keep going -- a crash here would strand the close at step 1."""
    doc = "# CLAUDE.md\n\n## Prevention Conventions\n\n" + "x" * 400 + "\n"
    out = _run_measure(tmp_path, doc)
    assert "(absent)" in out, out
    nums = [int(n) for n in re.findall(r"^\s*(\d+)", out, re.M)]
    assert nums[-1] == nums[0], out                  # TOTAL == the one section
    assert nums[1] == 0, out


def test_the_paste_and_the_prompt_agree_on_the_widened_set():
    """`Q-342`'s actual failure was a DISAGREEMENT between what step 1 measured,
    what it wrote, and what the prompt told the agent it had. All three move
    together or the guard is worthless."""
    text = REVIEW_CLOSE.read_text(encoding="utf-8")
    assert "not `## Prevention Conventions` alone (`Q-342`)" in text
    # The prompt block is no longer named after one section...
    assert "     ## Project conventions\n" in text
    # ...and the write-once arm writes the whole set, not "the section".
    assert "write **every section in the set, verbatim" in text
    # The reviewer is told there is more than one and that any of them binds.
    assert "there is more than one, and a rule in\n     any of them binds" in text
    # Refusal of the filing's own preferred option is recorded, not silent.
    assert "option (c)" in text and "refused here" in text


def test_the_security_twin_is_a_second_fleet_with_its_own_gate():
    """`Q-352`. Five properties, each decided against a named alternative."""
    text = REVIEW_CLOSE.read_text(encoding="utf-8")
    m = re.search(r"^3b\. \*\*Spawn the security twin.*?(?=^4\. Collect all verdicts)",
                  text, re.M | re.S)
    assert m, "Step 2b has no security twin (step 3b)"
    step = m.group(0)

    # (a) A second agent, not a bigger prompt -- Phase 166's ~15% lens overlap.
    assert "A second agent, not a bigger prompt" in step
    # (b) Glob-gated, so the doc-and-glue majority spawns nothing extra...
    assert "spawn only if some glob in either matches" in step
    # ...and the skip is searched, never assumed.
    assert "searched absence and never an assumed one" in step
    # (c) Its own paste file -- asserted at the WRITE TARGET, not as a presence
    # check. The round pointed the write at `2b-conventions.md` and this stayed
    # green, because the `rm -f` line above it still mentioned the security file:
    # an assertion satisfied by an INCIDENTAL occurrence of its own token. That is
    # the fourth instance of this shape in one phase, so it is asserted
    # positionally here and the wrong filename is refused by name.
    m = re.search(r"write them verbatim to `([^`]+)`", step)
    assert m, "step 3b no longer names a write target for the security paste"
    assert m.group(1) == "sysop/runtime/2b-security.md", (
        f"the security twin writes its paste to {m.group(1)!r} -- pointing it at "
        f"the convention fleet's file lets a stale write from either arm satisfy "
        f"the other's freshness check, which is the defect this file exists for"
    )
    rm = re.search(r"`rm -f ([^`]+)`", step)
    assert rm and rm.group(1) == "sysop/runtime/2b-security.md", (
        "the loud-failure delete no longer targets the security paste file"
    )
    assert "separate file from `2b-conventions.md`" in step
    # (d) The trap: a second baseline capture would invert step 2's delta.
    assert "Do NOT capture a second baseline" in step
    # (e) BLOCKED authority -- the DISPOSITION, not its vocabulary. The round
    # inverted this while preserving every string the first version of this test
    # asserted ("Step 4 treats this fleet's `BLOCKED` as ADVISORY ONLY and the
    # close proceeds") and the entire suite stayed green. The twin's power to stop
    # a close is the whole of Q-352's escalation; a guard that cannot see it
    # removed is guarding the word, not the behaviour.
    assert "VERDICT: BLOCKED` authority" in step
    assert "advisory only — was considered and refused" in step
    assert "Step 4 already treats *any* `BLOCKED` as a stop" in step, (
        "the twin's verdict no longer routes into Step 4's stop -- an advisory "
        "security lens is the filed state with one more line of output"
    )
    for inversion in ("advisory only and the close proceeds",
                      "as advisory only", "the close proceeds"):
        assert inversion.lower() not in step.lower().replace(
            "advisory only — was considered and refused", ""), (
            f"the twin was downgraded to advisory: {inversion!r}"
        )

    # (f) And the reach is disclosed rather than implied: on a stock install most
    # of the shipped map is placeholders, so the twin skips application code.
    assert "carry placeholder globs" in step
    assert "still carry placeholder globs" in step, (
        "the skip report does not distinguish an unlocalized map from a clean one"
    )

    # (g) THE REVERSAL LAYER -- see the module header. The round made this twin
    # advisory, cascaded the doc-only skip onto it, folded it back into one
    # prompt, and reinstated the second-baseline trap, all with every pinned
    # string intact and the whole suite green.
    assert_no_reversal(
        step, "Step 2b step 3b",
        exempt=("advisory only — was considered and refused",),
    )


def _cascade_note():
    text = REVIEW_CLOSE.read_text(encoding="utf-8")
    i = text.index("**This skip is about step 3's agent and does not reach step 3b's**")
    return text[i:text.index("\n\n", i)]


def test_the_no_cascade_note_cannot_be_reversed_in_place():
    """The round reversed this note four separate ways (`T14`, `T17`, `T26`, and a
    licensed assumed-absence) while keeping every string the presence check pins.
    The note's whole job is to REFUSE a cascade, so the vocabulary of granting one
    must not appear in it."""
    note = _cascade_note()
    assert_no_reversal(note, "Step 2b step 0's no-cascade note")
    for grant in ("covers step 3b as well", "skip here too", "serves both fleets",
                  "one classification of the diff serves both"):
        assert grant.lower() not in note.lower(), (
            f"the doc-only skip was cascaded onto the security twin: {grant!r}"
        )


def test_a_doc_only_skip_does_not_silence_the_security_lens():
    """The cascade that would have made the twin inert on exactly the diffs it
    was added for: the security map routes documentation paths BY DESIGN (the llm
    pack routes `<prompts dir>/**/*.md`; `security_map.md` routes root operational
    docs to A02), so step 0's doc-only skip must not reach step 3b."""
    text = REVIEW_CLOSE.read_text(encoding="utf-8")
    assert "This skip is about step 3's agent and does not reach step 3b's" in text
    assert "a cascade would silence the security lens" in text


def test_the_two_fleets_report_on_two_lines():
    """One tally cannot carry both: a cycle where every target skipped the
    security twin and every target passed the convention check would read exactly
    like one where both fleets ran and both approved."""
    text = REVIEW_CLOSE.read_text(encoding="utf-8")
    # Whitespace-insensitive on the column gutter: the round showed that adding a
    # longer label to this report block and re-aligning the column turns a shipped
    # gate red over a pure reformat. The property is that the line EXISTS with its
    # dispositions, not that it sits at a particular column.
    assert re.search(r"^Security map: +<N checked, N skipped \(no map match\)>", text, re.M)
    assert "never folded into `Conventions:`" in text


def test_the_executor_hop_reads_both_maps():
    """`Q-352`'s other end, at ALL THREE executor sites.

    The planner reads both maps; the executors re-scanned changed lines against
    the convention map alone, so half of what the plan was written against was
    never re-checked against the diff that resulted.

    **The first version of this test read `claim-task` alone, and the fix landed
    in 1 of 3 sites.** The round's guards lens pointed `auto-build`'s step at a
    non-existent map and deleted it outright; the whole suite stayed green. Worse,
    that step describes itself as *"the same gate /claim-task Step 7e's executor
    runs internally"*, so fixing one and not the other left the shipped prose
    asserting a parity that did not exist. The autonomous path is where this
    matters most, because it is the one nobody watches.
    """
    sites = {
        "claim-task": CLAIM_TASK,
        "auto-build": REPO_ROOT / "core/skills/auto-build/SKILL.md",
        "auto-fix": REPO_ROOT / "core/skills/auto-fix/SKILL.md",
    }
    for name, path in sites.items():
        text = path.read_text(encoding="utf-8")
        assert "security_map" in text, f"{name}: no security-map read anywhere"
        lone = [
            ln.strip() for ln in text.splitlines()
            if "convention_map.md" in ln
            and "security_map" not in ln
            and ("post-fix" in ln.lower() or "re-read the applicable conventions" in ln)
        ]
        assert not lone, (
            f"{name}: a post-fix convention read names the convention map without "
            f"the security map -- Q-352's gap, reopened at a site the first version "
            f"of this guard did not read:\n  " + "\n  ".join(l[:170] for l in lone)
        )
