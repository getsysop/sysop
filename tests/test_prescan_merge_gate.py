"""`Q-353` — the deterministic checks reach the merge gate, and the command the
docs prescribe is one that actually runs.

Two legs shipped and they cover different trees, which is why neither is a
duplicate of the other:

  leg 1  `WORKFLOW.md` § 6.1's `## Pre-merge verification` → `### Always`
         template carries the pre-scan, so `/claim-task` Step 7e and
         `/auto-build` run it **in each branch's own worktree, at its own tip**.
  leg 2  `/review-close` runs it itself at `4a-post`, on the **assembled** merge
         target, whether or not the consumer listed it -- which is the only leg
         that reaches a consumer whose `CLAUDE.md` predates this change, since
         Phase 24b preserves that file across `--update`.

**The load-bearing test here is behavioural, not textual.** A guard asserting
"the template contains this string" is prose checking prose, and this repo's
rounds keep falsifying that shape. `test_the_prescribed_prescan_actually_runs`
instead extracts the command **from the template** and executes it inside a real
fresh install, asserting on output the scan alone can produce. A renamed script,
a wrong path, a flag that `run_checks/cli.py` does not accept, or a template line
that drifts from the shipped CLI all redden it; none of those are visible to a
string match.
"""
import os
import re
import subprocess
import sys
from pathlib import Path
from _reversal import assert_no_reversal

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
WORKFLOW = REPO_ROOT / "core/companion/docs/WORKFLOW.md"
REVIEW_CLOSE = REPO_ROOT / "core/skills/review-close/SKILL.md"

# THE REVERSAL LAYER lives in `tests/_reversal.py` (Phase 253, `Q-367`). This module
# carried its own 13-entry copy from Phase 247 until then; the shared list is a
# superset of it minus `will do`, whose retirement is recorded in that module and in
# `Q-367`'s archive entry.


def _always_block_commands():
    """Every backticked bullet under § 6.1's `### Always` template heading.

    Anchored on the heading rather than on the command text, so a bullet that is
    edited, reordered or renamed is still found and still has to run. Returns []
    only if the heading is gone, which the caller treats as a failure rather than
    as an empty pass -- a silently-empty extraction is how a guard like this goes
    vacuous.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    m = re.search(r"^### Always$\n(.*?)(?=^### |\Z)", text, re.M | re.S)
    if not m:
        return []
    return re.findall(r"^- `([^`]+)`\s*$", m.group(1), re.M)


def test_the_always_template_prescribes_the_prescan():
    """Leg 1's presence, in both shapes the section supports.

    Split-form and flat-form are separate templates a consumer chooses between
    (`WORKFLOW.md` calls the second "backward compatible"), so shipping the line
    in one of them leaves the other's readers exactly where `Q-353` found them.
    """
    cmds = _always_block_commands()
    assert cmds, "§ 6.1's `### Always` heading is gone -- extraction returned nothing"
    prescan = [c for c in cmds if "run_checks.sh" in c]
    assert prescan == ["bash sysop/scripts/run_checks.sh --mode both --fail-on-blocking"], cmds

    # The flat-list form is a SECOND template, not a restatement of the first --
    # and it is asserted INSIDE that template's own fence, not as a whole-file
    # count. The round's execution lens defeated the count version by deleting the
    # line from the flat template and re-inserting the identical string as an
    # unrelated bullet 900 lines earlier: count still 2, template still broken,
    # every test green. A count over a file is not a statement about a block.
    text = WORKFLOW.read_text(encoding="utf-8")
    i = text.index("**Flat-list form (backward compatible):**")
    flat = text[i:text.index("```", text.index("```markdown", i) + 3)]
    assert "## Pre-merge verification" in flat, flat[:200]
    assert "- `bash sysop/scripts/run_checks.sh --mode both --fail-on-blocking`" in flat, (
        "the FLAT § 6.1 template no longer carries the pre-scan line; a consumer "
        "following the backward-compatible form gets the pre-Q-353 behaviour"
    )


def test_the_prescribed_prescan_actually_runs(tmp_path):
    """Phase 168's author-side rule 3, applied to this phase: run the command the
    change prescribes.

    Extracts the pre-scan bullet **from the template** and executes it verbatim in
    a fresh install. Asserts on the accounting header, which only a real scan
    emits -- so this cannot pass on a command that failed to start.

    A fresh install exits **0** here and that is the designed behaviour, not a
    weak assertion: the shipped blocking checks carry placeholder globs, which
    render as a calm `gate unarmed` line rather than a refusal. It is the fact
    that makes leg 2 safe to turn on for every consumer at once -- a merge gate
    that reddened on arrival for everyone who ran `--update` would be a worse
    defect than the one being fixed.
    """
    cmds = [c for c in _always_block_commands() if "run_checks.sh" in c]
    assert len(cmds) == 1, cmds
    prescan = cmds[0]

    consumer = tmp_path / "consumer"
    consumer.mkdir()
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=consumer, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "seed"],
                   cwd=consumer, check=True, capture_output=True)
    r = subprocess.run(
        ["bash", str(INSTALL_SH), str(consumer), "--packs", "python", "--no-arm-hooks", "--yes"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stdout + r.stderr

    run = subprocess.run(["bash", "-c", prescan], cwd=consumer,
                         capture_output=True, text=True, env=env)
    combined = run.stdout + run.stderr

    # 127 = no such command/script; 2 = argparse rejected a flag. Either means the
    # template prescribes something that cannot run, which is the whole point.
    assert run.returncode in (0, 1), (
        f"the § 6.1 template prescribes a command that does not run: rc={run.returncode}\n"
        f"$ {prescan}\n{combined}"
    )
    assert run.returncode == 0, (
        "a FRESH install must not have its merge refused -- the shipped blocking "
        f"checks carry placeholder globs and should report an unarmed gate\n{combined}"
    )
    # Output only a real scan produces. Phase 135's accounting header.
    assert re.search(r"checks: \d+ executed / \d+ skipped / \d+ failed", combined), (
        f"no accounting header -- the pre-scan did not actually run\n{combined}"
    )
    assert "new blocking: 0" in combined, combined


def test_review_close_runs_the_prescan_itself_and_not_via_the_resolution_chain():
    """Leg 2. The three properties that make it reach existing consumers and stay
    honest about what refused.

    Textual, because the step IS prose -- but each assertion names a property that
    was decided against an alternative, so an edit that reverses the decision
    reddens rather than one that rewords it.
    """
    text = REVIEW_CLOSE.read_text(encoding="utf-8")
    m = re.search(r"^3a\. \*\*Run the Sysop pre-scan.*?(?=^4\. \*\*On failure)", text, re.M | re.S)
    assert m, "4a-post has no pre-scan step (`3a`)"
    step = m.group(0)

    assert "bash sysop/scripts/run_checks.sh --mode both --fail-on-blocking" in step

    # (a) NOT a fourth entry in the resolution chain -- that chain stops at the
    # first source producing a list, so a consumer with a declared section would
    # never reach it, i.e. exactly the population Q-353 was filed about.
    assert "not a fourth entry" in step.lower() or "NOT a fourth entry" in step, step[:400]

    # (b) The two failure classes stay apart (Phase 135). --fail-on-blocking exits
    # non-zero on a new blocking FINDING and on a blocking stage that CRASHED;
    # reporting them as one thing is what makes a green gate stop meaning anything.
    assert "new blocking finding" in step
    assert "blocking stage did not run" in step

    # (c) De-dup asks whether a command REACHES the pre-scan, not whether it
    # contains the string. The round's execution lens showed a name match is wrong
    # on the live case: the one consumer already enforcing these checks lists a
    # project-owned WRAPPER (`run_checks_gated.sh`), which a name match misses,
    # producing a second whole-tree scan every close.
    assert "ran via the consumer's list" in step
    assert "directly or through a project wrapper" in step
    assert "Flags never enter the decision" in step

    # (d) The DISPOSITIONS, not just their vocabulary. The round inverted both of
    # this phase's load-bearing behaviours while preserving every string the first
    # version of this test asserted, and the whole suite stayed green: "Both stop,
    # per item 4." -> "Both are advisory: report them and CONTINUE the close."
    assert "Both stop, per item 4." in step, (
        "the two failure classes no longer STOP -- a pre-scan that reports a new "
        "blocking finding and lets the close proceed is the filed defect with an "
        "extra line of output"
    )
    for advisory in ("advisory", "and continue the close", "report them and continue"):
        assert advisory.lower() not in step.lower().split("Exit 0")[0], (
            f"a non-zero pre-scan was downgraded to {advisory!r} before the Exit-0 arm"
        )
    # (e) A third status exists and does not block; Exit 0 is not unconditionally clean.
    assert "degraded" in step
    assert "a zero from a degraded stage is not a real zero" in step
    # (f) An environment that cannot run the scan is not a verdict on the work.
    assert "could not run" in step
    assert "This is an environment fault, not a verdict on the work" in step

    # (g) THE REVERSAL LAYER. Everything above is a presence check, and the round
    # walked 38 of 53 mutations through presence checks by adding a contradicting
    # sentence beside the pinned phrase. The exemptions are the two dispositions
    # this step grants on purpose: the environmental arm continues, and so does a
    # clean-but-degraded run.
    assert_no_reversal(
        step, "4a-post step 3a",
        exempt=(
            "and **continue**. This is an environment fault",
            "otherwise `pre-scan: clean, but N blocking checks degraded — <ids>`, and continue",
            "and report `pre-scan: consumer's list runs an ungated scan — ran the gate as well`",
        ),
    )

    # And Step 8 reports it as its own element rather than folding it into the
    # merged-tree count, which would lose which of the two gates refused.
    # Step 8's element -- anchored on the label and the two dispositions that
    # distinguish it, not on the full first line, which now carries the degraded arm.
    assert "               pre-scan <clean | clean, but N blocking checks degraded" in text
    assert "ran via the consumer's list\n" in text
    assert "could not run — <tool's own first error line>" in text
