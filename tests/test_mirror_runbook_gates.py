"""The mirror runbook keeps its two executable gates — Phase 177.

Why this exists. Two gates were invented ad-hoc during the 2026-07-31 mirror push, used,
and never written down: (1) run the suite *inside the sterilized tree*, because that tree
deliberately removes files the suite reads and the Phase-160 follow-up exists precisely
because it failed three tests the source repo passed; (2) scan public *history*, not only
the built tree, because every other gate on that page reads a tree and a leak fixed at the
tip reads as remediated while the old content sits in `git log -p`. Phase 177 wrote them
into `tools/TESTER_MIRROR_RUNBOOK.md`.

**This is a declared reversion guard**, and its job is catching deletion or quiet
shortening-back. It is *not* evidence that the runbook is correct.

What the adversarial round did to the first version, because the fixes are all shaped by it:

- **It could not detect deletion of its own subject.** Renaming or deleting the runbook made
  all six tests SKIP and exit 0 — the mirror-exclusion skip, copied from the Phase-160
  lesson, swallowed the exact failure a reversion guard exists for. `_in_source_repo()` now
  distinguishes "sterilized mirror, correctly absent" from "source repo, file deleted".
- **Announcement and command did not have to co-occur.** The predicate ran independent
  `any()` passes over a union of steps, so deleting the suite step and re-homing its command
  under step 9 — *"Enable Discussions on `wade-cms/sysop-tester`"*, whose title contains the
  substring `test` — passed. They are now matched per step, and titles are matched on a
  phrase, not a substring that half the document satisfies.
- **A commented-out command satisfied the check** (`# was: git rev-list HEAD` inside a
  fence), and so did a *tree read wearing the command's name*: `git rev-list -n 1 HEAD`, or
  `git rev-list HEAD -- README.md`, both of which stop being a history walk.
- **Twelve legitimate edits reddened it** — renaming the scratch path (`wf-` is a wade-flow
  relic and this project has renamed itself twice), inserting a step and renumbering
  coherently, retitling a step, rewriting the walk as `git log --format=%H | while read`.
  Those were hardcoded literals, and they are the failure direction that gets guards
  deleted rather than fixed. The predicate now keys on properties.

`tools/` is excluded from the public mirror, so these tests skip in the sterilized tree —
but only when the *whole* maintainer-side surface is absent, never when the runbook alone
has gone missing.
"""

import fnmatch
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNBOOK = REPO_ROOT / "tools" / "TESTER_MIRROR_RUNBOOK.md"
# Independent markers that this is the maintainer's repo rather than the sterilized mirror.
# `make_public_mirror.sh` removes all of these together; none of them is the runbook, so a
# deleted runbook cannot masquerade as a mirror.
SOURCE_REPO_MARKERS = (
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "REVIEW_CHECKLIST.md",
    REPO_ROOT / "tools" / "make_public_mirror.sh",
)


def _in_source_repo() -> bool:
    return any(p.exists() for p in SOURCE_REPO_MARKERS)


def _runbook() -> str:
    if not _in_source_repo():
        pytest.skip(
            "not the source repo (CLAUDE.md, REVIEW_CHECKLIST.md and make_public_mirror.sh "
            "are all absent, so this is the sterilized mirror); the runbook gates only "
            "apply in the source repo"
        )
    assert RUNBOOK.is_file(), (
        f"{RUNBOOK.relative_to(REPO_ROOT)} is missing from the SOURCE repo. This module is a "
        "declared reversion guard for the two mirror gates it documents; a skip here would "
        "let deleting or renaming the runbook read as 'correctly excluded from the mirror', "
        "which is the hole the Phase 177 round found in the first version of this file."
    )
    return RUNBOOK.read_text(encoding="utf-8")


def _steps_section(text: str) -> str:
    m = re.search(r"(?m)^## Steps\s*$", text)
    assert m, "the runbook lost its '## Steps' heading; this guard's anchor needs revisiting"
    end = text.find("\n## ", m.end())
    return text[m.start() : end if end != -1 else len(text)]


def numbered_steps(text: str) -> list[tuple[int, str, str]]:
    """(number, title line, concatenated fenced command text) per numbered step."""
    steps = _steps_section(text)
    out = []
    marks = list(re.finditer(r"(?m)^(\d+)\. (.*)$", steps))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(steps)
        body = steps[m.start() : end]
        fences = "\n".join(re.findall(r"```[a-z]*\n(.*?)```", body, re.S))
        # TITLE = the bolded lead, not the whole first line. The round's over-breadth
        # finding bit this function twice: the whole line of step 10 contains "no
        # history", and the whole line of step 9 contains "sysop-tester".
        lead = re.match(r"\*\*(.+?)\*\*", m.group(2))
        out.append((int(m.group(1)), lead.group(1) if lead else m.group(2), fences))
    return out


def _live_lines(fence: str) -> list[str]:
    """Command lines only — a commented-out command is not a command. The round satisfied
    the history gate with `# was: git rev-list HEAD` sitting inside the fence."""
    return [ln for ln in fence.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def _walks_whole_history(lines: list[str]) -> bool:
    """A history walk, not a tree read wearing its name. `git rev-list -n 1 HEAD` and
    `git rev-list HEAD -- <path>` both passed the first version and are both tree reads.

    `Q-294` moved the walk out of the page and into
    `tools/scan_public_history.sh`, so the guard follows it: the lines it is
    handed no longer contain the loop, only the invocation. Weakening this to
    "the step mentions the script" would have retired a guard that a later
    round's battery specifically confirmed was doing work (a `-- <path>`
    restriction on the walk is one of the mutations it catches). Instead it now
    reads the script's own `rev-list` with the same predicate. If the page
    invokes the script, the script IS the walk.
    """
    # `not any(shebang)`: the script's own usage comment names the script, so
    # passing the script's OWN lines here re-injected the pristine file from disk
    # and the mutated copy walked fine — a guard reading its own source and
    # finding the string it is looking for. Caught by a control that mutated the
    # script and watched the predicate stay true.
    already_the_script = any(ln.startswith("#!") for ln in lines)
    if not already_the_script and any("scan_public_history.sh" in ln for ln in lines):
        script = REPO_ROOT / "tools" / "scan_public_history.sh"
        if script.is_file():
            lines = list(lines) + script.read_text(encoding="utf-8").splitlines()
    for ln in lines:
        # `git -C <dir> rev-list` is the same walk. The original regex required
        # `git` and `rev-list` adjacent, which was fine while the loop was pasted
        # into a shell already `cd`-ed into the clone; the extracted script takes
        # the clone as an argument and must use -C. Widened for the repo-selector
        # ONLY — the truncation and path-restriction checks below are untouched,
        # which is what this guard is actually for.
        m = re.search(r"git\s+(?:-C\s+\S+\s+)?rev-list\b([^\n|;]*)", ln)
        if not m:
            continue
        args = m.group(1)
        if re.search(r"(^|\s)(-n\s*\d+|--max-count[= ]\d+|-\d+)(\s|$)", args):
            continue  # truncated to N commits
        # A BARE `--` is the pathspec separator; `--all`, `--tags`, `--max-count`
        # are not. The substring test rejected any long option at all, so when
        # Phase 233 widened the walk from `rev-list HEAD` to
        # `rev-list --all --tags` -- closing a hole where a commit reachable only
        # from a published release tag was never scanned -- this guard read the
        # WIDENING as a restriction and went red. An over-strict guard that fires
        # on a correct change is how a maintainer learns to weaken a correct one.
        if re.search(r"(^|\s)--(\s|$)", args):
            continue  # path-restricted
        # `--count` prints a NUMBER; it is not a per-commit walk. The old crude
        # `"--" in args` test excluded it as a side effect, and narrowing that to
        # a bare pathspec `--` let it through -- so the truncation control below
        # went green against a script whose real loop had been truncated, because
        # the summary's `rev-list --count` satisfied the predicate instead. Caught
        # by that control, which is exactly what it is for.
        if re.search(r"(^|\s)--count(\s|=|$)", args):
            continue
        return True
    return False


def _runs_suite_in_built_tree(lines: list[str], build_target: str | None) -> bool:
    """pytest, invoked against the built mirror. The build target is read from the file
    rather than hardcoded, so renaming the scratch path is ordinary work, not a failure."""
    if build_target is None:
        return any("pytest" in ln for ln in lines)
    for i, ln in enumerate(lines):
        if "pytest" not in ln:
            continue
        window = " ".join(lines[max(0, i - 1) : i + 1])
        if build_target in window and re.search(r"\bcd\b", window):
            return True
    return False


def build_target(text: str) -> str | None:
    """Where the runbook tells you to build the mirror — derived, not assumed."""
    m = re.search(r"make_public_mirror\.sh\s+(\S+)", text)
    return m.group(1) if m else None


def missing_gates(text: str) -> list[str]:
    """Each gate must be ANNOUNCED by a numbered step and RUN by that same step's commands."""
    problems = []
    steps = numbered_steps(text)
    target = build_target(text)

    suite = [s for s in steps if re.search(r"\b(suite|tests?)\b", s[1], re.I)
             and re.search(r"run|execut|verify|check|green", s[1], re.I)]
    if not suite:
        problems.append(
            "no numbered step announces the sterilized-tree suite gate — a gate demoted to "
            "an aside, a note, or another step's body is one an operator walks past"
        )
    elif not any(_runs_suite_in_built_tree(_live_lines(f), target) for _, _, f in suite):
        problems.append(
            f"the suite step carries no pytest command run against the built tree "
            f"({target or 'the mirror build target'}) — 'remember to run the tests', a "
            "commented-out line, or a run in the source repo is not this gate"
        )

    history = [s for s in steps if re.search(r"histor", s[1], re.I)]
    if not history:
        problems.append(
            "no numbered step announces the public-history scan — every remaining pass "
            "reads a tree"
        )
    elif not any(_walks_whole_history(_live_lines(f)) for _, _, f in history):
        problems.append(
            "the history step does not walk the whole history — a `git rev-list` truncated "
            "with -n/--max-count or restricted with `-- <path>` is a tree read wearing the "
            "command's name, which is the defect this gate exists for"
        )

    numbers = {n for n, _, _ in steps}
    m = re.search(r"(?m)^## Refreshing\s*$", text)
    if not m:
        problems.append("the runbook lost its '## Refreshing' section")
    else:
        end = text.find("\n## ", m.end())
        refresh = text[m.start() : end if end != -1 else len(text)]
        gate_numbers = ({n for n, _, _ in suite} | {n for n, _, _ in history}
                        | {n for n, title, _ in steps if re.search(r"verify-grep", title, re.I)})
        cited = {int(x) for x in re.findall(r"\b(\d+)\b", refresh)} & numbers
        if not gate_numbers <= cited:
            problems.append(
                f"the Refreshing section does not point back at every gate step "
                f"(gates {sorted(gate_numbers)}, cited {sorted(cited)}) — a refresh is the "
                "only thing that ever changes the built tree, so a rebuild block that reads "
                "as a self-contained recipe is a documented bypass"
            )
        if not re.search(r"discussions/1(?!\d)", refresh):
            problems.append(
                "the Refreshing section no longer binds the tester announcement to the push "
                "(the standing discussion thread #1) — that join has failed twice, and a "
                "different thread number notifies nobody who is subscribed"
            )
    return problems



def _pinned_runbook(sha: str) -> str:
    """The runbook's blob at a pinned commit, for a non-vacuity control.

    SKIPS when the COMMIT is unreachable — CI's `actions/checkout` takes its
    default `fetch-depth: 1`, and Phase 271 pinned two controls to a literal SHA
    that Phase 272's round then measured failing on a real depth-1 clone, which
    would have reddened the required check on every push.

    FAILS when the commit is reachable and the PATH is not.

    **The reason first given for that half was wrong and is corrected here.** It
    said a rename of the runbook would turn these controls into silent passes. It
    does not: a rename at HEAD leaves history untouched, so `git show
    <sha>:tools/TESTER_MIRROR_RUNBOOK.md` still resolves — measured on a real
    clone with the file renamed and committed. A rename is caught, loudly, by
    `_runbook()`'s own assert (23 failures), which is the guard that docstring
    already credits. What this branch actually catches is a pin that PREDATES the
    file — re-pointing a control at an older commit, which is an ordinary
    authoring slip and which the old code turned into a silent skip. Narrower than
    claimed, real, and stated at its true width. Found by an independent lens.
    """
    if subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                      cwd=REPO_ROOT, capture_output=True).returncode != 0:
        pytest.skip(
            f"{sha} is not reachable here (a shallow clone, or a tree published "
            "without history); the non-vacuity control needs the pre-fix blob"
        )
    blob = subprocess.run(
        ["git", "show", f"{sha}:tools/TESTER_MIRROR_RUNBOOK.md"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert blob.returncode == 0, (
        f"commit {sha} is reachable but tools/TESTER_MIRROR_RUNBOOK.md is not "
        f"present in it: {blob.stderr.strip()}. If the runbook was renamed, this "
        "control and its siblings need re-pointing — do not let a rename read as "
        "a skip"
    )
    return blob.stdout

# --- the guards -------------------------------------------------------------------


def test_the_runbook_keeps_both_mirror_gates():
    assert missing_gates(_runbook()) == []


def test_the_runbook_itself_must_exist_in_the_source_repo():
    """The reversion guard's own subject. Deleting or renaming the file must not read as
    'correctly excluded from the mirror' — the round's sharpest finding here."""
    if not _in_source_repo():
        pytest.skip("sterilized mirror; the runbook is correctly absent")
    assert RUNBOOK.is_file(), "the runbook has been deleted or renamed in the source repo"


def test_the_gate_check_is_not_vacuous():
    text = _runbook()
    for label, mutated in (
        ("suite gate", re.sub(r"(?m)^.*pytest.*$", "", text)),
        # RE-POINTED by `Q-294`: the walk moved into tools/scan_public_history.sh,
        # so `git rev-list` is no longer on the page and the old mutation was a
        # silent no-op — the vacuity control itself had gone vacuous. Breaking the
        # INVOCATION is the equivalent edit now.
        ("history gate", text.replace("scan_public_history.sh", "scan_nothing.sh")),
        ("refresh binding", re.sub(r"(?m)^## Refreshing\s*$", "## Rebuilding", text)),
        ("announcement binding",
         text.replace("https://github.com/wade-cms/sysop-tester/discussions/1", "REDACTED")),
    ):
        assert missing_gates(mutated), f"removing the {label} was not detected"


def _discussions_anchor(text: str) -> str:
    """The `N. **Enable Discussions**` marker, derived rather than pinned.

    Two controls below re-home a gate under this step to prove an unrelated step
    cannot satisfy the check. Both hardcoded `9.`, and both broke the moment
    Phase 226 inserted a numbered step above it. The control that announces
    *"this control needs re-pointing"* was doing its job — but a derived anchor
    needs no re-pointing at all, which is the same derive-don't-assert rule this
    module already applies to its pass population.
    """
    m = re.search(r"(?m)^(\d+)\. \*\*Enable Discussions\*\*", text)
    assert m, "the runbook lost its 'Enable Discussions' step, so two controls anchor on nothing"
    return m.group(0)


def test_a_gate_rehomed_under_an_unrelated_step_does_not_count():
    """Round finding E4/E5. The command was moved under 'Enable Discussions on
    wade-cms/sysop-tester' — a title containing the substring `test` — and the first
    version passed. Announcement and command must co-occur in one step."""
    text = _runbook()
    steps = numbered_steps(text)
    # Select the SUITE step by the same predicate `missing_gates` uses, not by
    # "the first step whose fences mention pytest". Phase 185 added a pytest
    # invocation to the pass-list step (Pass 5 runs in the source repo), which
    # made the old selector pick step 3 and broke this control — a regression the
    # change introduced into a pre-existing guard, caught by running the commands
    # the change prescribes rather than by the edit itself.
    suite_step = next(s for s in steps
                      if "pytest" in s[2]
                      and re.search(r"\b(suite|tests?)\b", s[1], re.I)
                      and re.search(r"run|execut|verify|check|green", s[1], re.I))
    fence_line = next(ln for ln in _live_lines(suite_step[2]) if "pytest" in ln)
    # Delete the announcing step's number+title, re-home its command under a later step.
    gutted = re.sub(rf"(?m)^{suite_step[0]}\. \*\*{re.escape(suite_step[1])}\*\*",
                    "Some prose, not a numbered step.", text, count=1)
    assert gutted != text, (
        "the step-title anchor did not match, so this control mutated nothing — it was "
        "silently passing on an unmutated file, which is the shape it exists to catch"
    )
    anchor = _discussions_anchor(text)
    rehomed = gutted.replace(
        anchor, f"{anchor}\n   ```bash\n   {fence_line.strip()}\n   ```\n", 1)
    assert rehomed != gutted, "the re-home anchor moved; this control needs re-pointing"
    assert any("suite" in p for p in missing_gates(rehomed)), (
        "a gate command re-homed under an unrelated step satisfied the guard — the "
        "announcement and the command are being matched independently"
    )


def test_a_commented_out_command_does_not_count():
    """Round finding E2 — text presence is not execution.

    RE-POINTED by `Q-294` for the same reason as its siblings: the walk moved
    into `tools/scan_public_history.sh`. On the page the equivalent gutting is
    commenting out the INVOCATION, which is the edit that would leave step 5
    looking complete while running nothing.
    """
    text = _runbook()
    gutted = text.replace("   bash tools/scan_public_history.sh",
                          "   # was: bash tools/scan_public_history.sh", 1)
    assert gutted != text, "the anchor moved; this control needs re-pointing"
    assert any("history" in p for p in missing_gates(gutted)), (
        "a commented-out invocation satisfied the history gate"
    )


def test_a_truncated_or_path_scoped_walk_does_not_count():
    """Round findings E1 and E3 — a tree read wearing the command's name.

    RE-POINTED by `Q-294`: the walk moved out of the page into
    `tools/scan_public_history.sh`, so mutating the page's text no longer
    reaches it. The property is unchanged and is asserted against the predicate
    directly — weakening or deleting this control because its anchor moved would
    have retired the one guard a later battery confirmed was doing work.
    """
    _runbook()  # skip in the sterilized mirror, same as every test here
    script = REPO_ROOT / "tools" / "scan_public_history.sh"
    live = script.read_text(encoding="utf-8").splitlines()
    assert _walks_whole_history(live), (
        "the shipped script does not walk the whole history; this control is "
        "testing nothing"
    )
    # RE-POINTED again (Phase 233): the walk widened from `rev-list HEAD` to
    # `rev-list --all --tags`, because a commit reachable only from a published
    # release tag was never scanned. The old anchor no longer matched, so the
    # "mutated" copy was identical to live and this control silently stopped
    # testing anything — the failure mode its own docstring names. Re-pointed,
    # not weakened, and the substitution is asserted to have bitten.
    WALK = "rev-list --all --tags"
    for variant in (f"rev-list -n 1 --all --tags", f"{WALK} -- README.md"):
        mutated = [ln.replace(WALK, variant) for ln in live]
        assert mutated != live, "the anchor moved again; re-point, do not weaken"
        assert not _walks_whole_history(mutated), (
            f"`git … {variant}` satisfied the history gate — it is not a history walk"
        )


def test_a_gate_demoted_from_a_step_to_an_aside_does_not_count():
    text = _runbook()
    demoted = text.replace("4. **Run the suite inside the sterilized tree",
                           "> Optional aside: run the suite inside the sterilized tree", 1)
    assert demoted != text, "the anchor moved; this control needs re-pointing"
    assert any("suite" in p for p in missing_gates(demoted)), (
        "the guard accepted a gate demoted out of the numbered procedure into an aside"
    )


# --- negative controls: legitimate edits that must stay green ----------------------


def test_renaming_the_scratch_path_stays_green():
    """Round finding N8. `wf-` is a wade-flow relic and this project has renamed twice."""
    text = _runbook()
    renamed = text.replace("/tmp/wf-tester", "/tmp/sysop-mirror")
    assert renamed != text
    assert missing_gates(renamed) == [], missing_gates(renamed)


def test_retitling_a_gate_step_stays_green():
    """Round finding N10."""
    text = _runbook()
    for new_title in (
        "4. **Verify the built mirror's test suite is green before you push.**",
        "4. **Run the tests inside the sterilized tree.**",
    ):
        retitled = re.sub(r"(?m)^4\. \*\*Run the suite inside the sterilized tree.*$",
                          new_title, text, count=1)
        assert retitled != text, new_title
        assert missing_gates(retitled) == [], (new_title, missing_gates(retitled))


def test_rewriting_the_walk_with_a_different_command_stays_green():
    """Round finding N18 — the property is walking every commit, not a literal spelling."""
    _runbook()
    script = REPO_ROOT / "tools" / "scan_public_history.sh"
    live = script.read_text(encoding="utf-8").splitlines()
    rewritten = [
        ln.replace('for sha in $(git -C "$CLONE" rev-list --all --tags); do',
                   'git -C "$CLONE" rev-list --all --tags | while read -r sha; do')
        for ln in live
    ]
    assert rewritten != live, "the anchor moved; this control needs re-pointing"
    assert _walks_whole_history(rewritten), (
        "a behaviour-identical rewrite of the loop was rejected — the property is "
        "walking every commit, not a literal spelling"
    )


def test_renumbering_the_procedure_coherently_stays_green():
    """Round finding N9 — inserting a step and updating the Refreshing back-reference is
    ordinary maintenance and must not redden."""
    text = _runbook()
    shifted = text
    for old, new in ((10, 11), (9, 10), (8, 9), (7, 8), (6, 7), (5, 6), (4, 5), (3, 4)):
        shifted = re.sub(rf"(?m)^{old}\. ", f"{new}. ", shifted, count=1)
    shifted = shifted.replace(
        "# --- steps 3, 4 and 5 above run HERE, on the rebuilt tree.",
        "# --- steps 4, 5 and 6 above run HERE, on the rebuilt tree.", 1)
    shifted = shifted.replace("Steps 3 (leak passes), 4 (suite inside the sterilized tree) and 5",
                              "Steps 4 (leak passes), 5 (suite inside the sterilized tree) and 6", 1)
    assert shifted != text
    assert missing_gates(shifted) == [], missing_gates(shifted)


def test_an_ordinary_rewording_stays_green():
    text = _runbook()
    reworded = (
        text.replace("Scan public *history*, not just the tree you built",
                     "Check the published commit history too, not only the tree you built")
        .replace("A refresh runs the same gates as a first cut.",
                 "Refreshes are gated identically to cuts.")
    )
    assert reworded != text, "no rewording applied; this control is testing nothing"
    assert missing_gates(reworded) == [], missing_gates(reworded)


# --- Phase 185: the runbook's pass list vs. the passes the gates actually implement ----
#
# The hole this closes, found by running the runbook rather than reading it. Step 3 defers
# to "the script" as the source of truth for the pass list — but it points at
# `make_public_mirror.sh`, which never prints Pass 4, and the runbook never named
# `cut_public_release.sh` at all, which is Pass 4's only implementation. Pass 5 (Phase 184)
# was never added here either. So two hard gates were reachable only by someone who already
# knew they existed. `missing_gates()` above could not see it: it checks that the suite and
# history *steps* exist, and asserts nothing about which passes step 3 enumerates.
#
# The population is DERIVED from the implementing files, never hardcoded here — the
# author-side rule that "an index of the source of truth is not the source of truth". A
# pass added to a script and not to the runbook reddens this on the next run.

# The population is DERIVED from the tracked tree, not listed. Phase 185 shipped
# three hardcoded paths — "three files someone remembered" — and its own round
# filed that: a pass implemented in a new `tools/verify_mirror_*.sh` would be
# invisible to this guard, which is the one drift it exists to catch.
#
# The shape rule is that **a pass is a mechanism**: it is implemented by a
# cut-time shell script or by a test module that runs or scans for it. Two
# neighbouring populations are deliberately OUT, and both exclusions were measured
# rather than argued:
#
#   * Prose `.md` under `tools/`. `tools/PUBLIC_RELEASE_SPEC.md` still discusses
#     "Pass 1", an identifier retired when Pass 1 split into 1a/1b/1c. Including
#     specs imports a pass nothing implements and reddens the guard against a
#     runbook that is correct.
#   * One-shot maintainer analyses under `tools/*.py`. These quote pass
#     identifiers as SUBJECT MATTER, and the derivation cannot tell a mechanism
#     from a mention: `tools/phase186_negation_probe.py` (deleted as spent by Phase 194;
#     recoverable from git history) carried a corpus of
#     hypothetical retirement bullets including "superseded by Pass 6", and the
#     first run of this derivation duly demanded the runbook list a Pass 6.
#
# **Those two reasons are recorded here, not asserted as a test, and that was a
# reversal.** The first version required each excluded population to still name a
# phantom pass, so that an exclusion whose reason expired would redden. A reviewer
# showed it firing on three ordinary edits: deleting the throwaway probe, editing
# its corpus, and — worst — implementing a real Pass 6, which is the number the
# next pass will take, and which produced a failure message about maintainer
# analyses that had nothing to do with what the maintainer had done. A guard that
# reddens on the single most likely correct future edit gets deleted rather than
# fixed. `test_the_pass_source_population_is_derived_from_the_tree` now checks the
# structural facts only: the two populations stay out, the globs name file TYPES
# rather than filename shapes, and this module stays out of its own population.
#
# Two residuals, stated rather than discovered later. A pass implemented outside
# these globs — in `core/companion/scripts/`, say — is still invisible. And in the
# other direction, `tests/*.py` prose carries the same mention-vs-mechanism
# ambiguity `tools/*.py` was excluded for: a docstring that names a hypothetical
# pass reddens this guard. That is accepted rather than fixed, because the one test
# module that really does implement a pass (Pass 5, in `test_mirror_leak_gate.py`)
# is a test module — and the failure now names the file that declared the pass, so
# it is a one-line fix rather than a mystery.
PASS_SOURCE_GLOBS = ("tools/*.sh", "tests/*.py")
# This module is excluded from its own population. It names every pass in prose,
# so including it would let a docstring here impose a requirement on the runbook
# — the guard writing its own subject.
PASS_SOURCE_EXCLUDE = ("tests/test_mirror_runbook_gates.py",)

# "Pass 1a", "Passes 2 + 2b", "Passes 1a/1b/1c", "Pass 2 and 2b" — the
# identifiers, not the prose. The joiner set is `+ / ,` and the word "and": the
# first version joined only on `+`, so `Passes 1a/1b/1c` — a form
# `make_public_mirror.sh` already uses at lines 18 and 91 — yielded `1a` alone.
_PASS_ID = r"\d+[a-z]?"
_PASS_TOKEN = re.compile(
    rf"\bPass(?:es)?\s+({_PASS_ID})((?:\s*(?:[+/,]|and)\s*{_PASS_ID})*)", re.I
)


def _pass_ids(m) -> list[str]:
    return [m.group(1).lower(), *re.findall(_PASS_ID, (m.group(2) or "").lower())]


def pass_sources() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [
        REPO_ROOT / rel
        for rel in out.split("\0")
        if rel
        and rel not in PASS_SOURCE_EXCLUDE
        and any(fnmatch.fnmatch(rel, g) for g in PASS_SOURCE_GLOBS)
    ]


def implemented_passes() -> set[str]:
    found: set[str] = set()
    for path in pass_sources():
        if not path.is_file():
            continue
        for m in _PASS_TOKEN.finditer(path.read_text(encoding="utf-8")):
            found.update(_pass_ids(m))
    return found


def _passes_named_in(text: str) -> set[str]:
    """Passes named in the step that tells the operator to RUN them — not anywhere
    in the document.

    The author-side battery for this guard found the whole-file version satisfied by
    an incidental mention: deleting Pass 5 from the operator's list left the guard
    green because a later sentence discussing Pass 5's history still contained the
    string. That is the same announcement-and-command-must-co-occur lesson this
    module already learned once, in the other direction. Scoped to the verify-grep
    step, discovered by property rather than by number so inserting a step ahead of
    it stays ordinary work.
    """
    found: set[str] = set()
    for body in _step_bodies_announcing_passes(text):
        for item in _list_items(_live_text(body)):
            # ONLY the pass this item LEADS with counts. Three rounds of the author's
            # and the reviewer's batteries walked through the weaker forms:
            #   - whole-file scope: a sentence *about* Pass 5 elsewhere satisfied it;
            #   - step scope, any mention: the same bullet's own trailing prose did;
            #   - step scope, must-lead-but-harvest-all: deleting a pass's bullet and
            #     folding its name into a SIBLING bullet satisfied it — the cheapest
            #     way to lose a pass from an operator's list, and the one the first
            #     version's docstring explicitly conceded.
            # One pass per bullet is therefore the contract, and the runbook is
            # written that way (Pass 2 and Pass 2b have separate items).
            m = _PASS_TOKEN.match(item)
            if m:
                found.update(_pass_ids(m))
    return found


# Bullet markers people actually use, plus ordered items. Keyed on a property
# rather than a literal: the reviewer's over-strictness probes reddened this guard
# on `+`, `•`, en-dash, a numbered sub-list and a backticked pass name — every one
# an ordinary re-rendering of the same list, and over-strictness is the direction
# that gets a correct guard deleted instead of fixed.
_LIST_ITEM = re.compile(r"(?m)^[ \t]*(?:[-*+•–—]|\d+[.)])[ \t]+(.*)$")
_LEAD_NOISE = "*_`~ \t"


def _list_items(text: str) -> list[str]:
    return [m.group(1).lstrip(_LEAD_NOISE) for m in _LIST_ITEM.finditer(text)]


def _live_text(body: str) -> str:
    """Fenced blocks and HTML comments removed.

    This module already learned once that "a commented-out command is not a
    command" (`_live_lines`). The reviewer showed that lesson had not been carried
    across: wrapping a pass's bullet in `<!-- -->` or in a ```text fence left the
    guard green while the operator's list no longer contained it.
    """
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    return body


def _step_bodies_announcing_passes(text: str) -> list[str]:
    """Full prose bodies of the numbered step(s) that announce the leak passes.

    `numbered_steps()` returns *fenced command text* as its third element, which is
    the right population for a command gate and the wrong one here — the pass list
    is prose bullets, so scoping to fences silently yields the empty set and the
    guard passes while reading nothing. Found by running the battery, not by
    reading the helper.
    """
    steps = _steps_section(text)
    marks = list(re.finditer(r"(?m)^(\d+)\. (.*)$", steps))
    bodies = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(steps)
        lead = re.match(r"\*\*(.+?)\*\*", m.group(2))
        title = lead.group(1) if lead else m.group(2)
        if re.search(r"verify-grep|leak pass|\bpasses\b", title, re.I):
            bodies.append(steps[m.start() : end])
    return bodies


def test_the_runbook_names_every_pass_the_gates_implement():
    """Every implemented pass must LEAD a list item in the step that announces them.

    **What this establishes, stated narrowly because the first version's headline
    claimed more.** It was *"a pass an operator is never told to run is a pass that
    does not run"*, and Phase 185's round showed a bullet reading
    ``- Pass 4 … → SUPERSEDED, do NOT run`` satisfies it. So the property is
    presence in the operator's list, not that the item tells them to run it.

    **Why the missing half is not guarded, measured rather than conceded**
    (``tools/phase186_negation_probe.py`` — the throwaway probe, deleted as spent by
    Phase 194; its measurement stands in the record and is recoverable from git
    history — 16 realistic retirement bullets against
    the runbook's 8 live ones):

    * A vocabulary written from the finding's own example — superseded / do not run
      / don't run / retired / obsolete / deprecated — catches **5 of 16** and
      falsely flags **0 of 8**. Decorative.
    * Widened until it covers the corpus (20 markers) it catches **15 of 16** and
      falsely flags **2 of 8 live bullets** — including the real Pass 4 bullet
      (*"`make_public_mirror.sh` **does not** print this one"*) and the real Pass 2
      one (*"**eyeball only** the new hits"*). A guard that reddens on the correct
      text gets deleted, not fixed.
    * The one neither reaches is a conditional (*"only when cutting the public
      repo"*), which is not a vocabulary problem at all.

    That is Phase 179's polarity-by-string-matching result reproduced on this
    surface, so the negation check is declined **in kind**, not left unattempted.

    **What bounds the residual is the tree, not the prose — and the first version
    of this paragraph got that bound wrong in the phase's favour.** It said no gate
    stops running because of a bullet. Within the script that is true: it wires
    Passes 1a/1b/1c/3/4 and the rename-residue diff to ``hard()`` unconditionally.
    But *whether the script runs at all* was itself prescribed by a bullet — the
    fenced ``bash tools/cut_public_release.sh`` block was nested **inside the Pass 4
    bullet**, the very bullet the finding is about, and by that bullet's own words
    Pass 4 and the residue diff are implemented nowhere else. Retiring it retired
    them both. Phase 186 hoisted that block into step 3's own body, which is what
    makes the claim true rather than the claim making itself true.

    With it hoisted: Passes 1a/1b/1c/3 also survive independently, because
    ``make_public_mirror.sh`` prints them in step 2. Pass 5's content runs in every
    suite run, including the ``pytest`` check ``.github/workflows/tests.yml``
    defines and branch protection requires on ``main``; its bullet adds running it
    at the exact cut SHA. Passes 2 and 2b are labelled *informational — NOT gating*
    by the script itself. What a do-not-run bullet could still do is persuade an
    operator to dismiss a RED gate they have already seen, and no string check
    reaches that.
    """
    if not _in_source_repo():
        pytest.skip("sterilized mirror; the maintainer-side surface is correctly absent")
    text = _runbook()
    implemented = implemented_passes()
    named = _passes_named_in(text)
    # Diagnose an empty population separately. The reviewer retitled the announcing
    # step and got a TRUE failure with a FALSE diagnosis — it listed every pass as
    # missing while all eight bullets were still there, which sends the next reader
    # to the wrong file.
    assert named or not _step_bodies_announcing_passes(text), (
        "no numbered step announces the leak passes any more — the step that "
        "enumerated them has been retitled or removed, so this guard is reading "
        "nothing. The bullets may well still be there; the ANNOUNCEMENT is what is "
        "missing, and an operator scanning step titles will not find them."
    )
    missing = sorted(implemented - named)
    where = {
        pid: sorted(
            str(p.relative_to(REPO_ROOT))
            for p in pass_sources()
            if p.is_file()
            and any(pid in _pass_ids(m)
                    for m in _PASS_TOKEN.finditer(p.read_text(encoding="utf-8")))
        )
        for pid in missing
    }
    assert not missing, (
        f"the runbook does not name pass(es) {missing}, declared in {where} — "
        "step 3's deferral to 'the script' does not save it, because the script it points "
        "at is not the one that implements them (the rename-residue diff lives only in "
        "cut_public_release.sh; Pass 4's cut-time run is there too, with a per-phase "
        "counterpart in tests/test_mirror_leak_gate.py since Phase 195; Pass 5 only in "
        "tests/test_mirror_leak_gate.py). "
        "Each pass needs its own list item, led by its identifier."
    )


def test_the_runbook_names_the_script_that_implements_the_hard_gates():
    """Round-proofing the fix above: naming 'Pass 4' while still pointing the operator at a
    script that cannot run it is the paraphrase that would satisfy the check and change
    nothing."""
    if not _in_source_repo():
        pytest.skip("sterilized mirror; the maintainer-side surface is correctly absent")
    # Scoped to the step that announces the passes, not the whole file. The
    # reviewer stripped both operative mentions from step 3 and added a `## Notes`
    # line saying the script was RETIRED — whole-file `in` was satisfied, and the
    # operator was now told the opposite of the instruction. That is the same
    # whole-file scoping the sibling check had just been fixed for, left in place
    # one test down.
    bodies = "\n".join(_step_bodies_announcing_passes(_runbook()))
    assert "cut_public_release.sh" in _live_text(bodies), (
        "the step that announces the leak passes does not name cut_public_release.sh — "
        "the only implementation of Pass 4 and of the rename-residue diff; a cut driven "
        "from make_public_mirror.sh alone runs neither. Naming it elsewhere in the file "
        "does not reach the operator running the passes."
    )


def test_the_pass_population_is_derived_and_non_vacuous():
    """Vacuity control. If the extractor stops matching, `implemented - named` is empty and
    the guard above passes while checking nothing — the failure mode it exists to prevent."""
    if not _in_source_repo():
        pytest.skip("sterilized mirror; the maintainer-side surface is correctly absent")
    implemented = implemented_passes()
    # `5b` added Phase 197 — the round's nit: without it here, that pass alone
    # dropping out of the EXTRACTOR is silent, and the runbook-coverage guard
    # above then passes by not knowing the pass exists.
    assert {"1a", "1b", "1c", "2", "2b", "3", "4", "4b", "5", "5b"} <= implemented, (
        f"the pass extractor found only {sorted(implemented)} — it has stopped seeing the "
        "identifiers in the implementing files, so the runbook check is inert"
    )


def test_the_pass_source_population_is_derived_from_the_tree():
    """Phase 186: the source list was three hardcoded paths, and its own round filed
    that as a hole. Both directions of the derivation are pinned here.

    NARROWING — the three files the old list named must still be in the derived set,
    plus the harness that executes the gate. A glob edited down to `tools/*.sh` drops
    both test modules and the guard goes quiet about Pass 5.

    WIDENING — the two neighbouring populations named at PASS_SOURCE_GLOBS must stay
    out, AND their reasons must still hold. Both are re-derived here rather than
    restated: each excluded population must still name a pass the implementations do
    not, because the moment that stops being true the exclusion is running on a stale
    justification and wants re-deriving rather than keeping.
    """
    if not _in_source_repo():
        pytest.skip("sterilized mirror; the maintainer-side surface is correctly absent")
    rels = {str(p.relative_to(REPO_ROOT)) for p in pass_sources()}
    for expected in (
        "tools/cut_public_release.sh",
        "tools/make_public_mirror.sh",
        "tests/test_mirror_leak_gate.py",
        "tests/test_cut_release_gate.py",
    ):
        assert expected in rels, (
            f"{expected} implements or executes a leak pass and is no longer in the "
            f"derived population; the globs have been narrowed. Derived: {sorted(rels)}"
        )
    assert "tests/test_mirror_runbook_gates.py" not in rels, (
        "this module is in its own pass population, so a pass identifier written "
        "in a docstring here becomes a requirement on the runbook"
    )
    for glob in ("tools/*.md", "tools/*.py"):
        outside = {p for p in REPO_ROOT.glob(glob) if p.is_file()}
        assert not (outside & set(pass_sources())), (
            f"{glob} entered the implementation population. Those files DISCUSS "
            "passes rather than running them — see PASS_SOURCE_GLOBS for the two "
            "measured phantoms that produced."
        )
    # A glob must name a file TYPE, not a filename shape. Round finding: the
    # NARROWING check above is membership of the same four files the hardcoded
    # list named, so `tests/test_mirror_*.py` — a glob hand-fitted to exactly
    # those files — passed it. That is the hardcoded list in glob clothing, which
    # is the hole this derivation replaced.
    for glob in PASS_SOURCE_GLOBS:
        _, _, base = glob.rpartition("/")
        assert re.fullmatch(r"\*\.\w+", base), (
            f"{glob!r} names a filename shape rather than a file type, so it only "
            "covers the files that happen to exist today — which is the hardcoded "
            "population this derivation exists to replace"
        )


def test_the_pass_token_grammar_reads_the_forms_the_scripts_use():
    """Phase 186: the joiner set was `+` alone, and `make_public_mirror.sh` writes
    `Passes 1a/1b/1c` twice — so the second and third identifiers were invisible.
    No live gap resulted (each is declared singly elsewhere), which is precisely
    why it needed a test rather than a sighting. The comma and "and" forms below
    are grammar coverage; neither script writes them today."""
    cases = {
        "Pass 1a": ["1a"],
        "Passes 2 + 2b": ["2", "2b"],
        "Passes 1a/1b/1c": ["1a", "1b", "1c"],
        "Passes 1a, 1b, 3": ["1a", "1b", "3"],
        "Pass 2 and 2b": ["2", "2b"],
        "Pass 5 (MUST be empty)": ["5"],
        # The declared re.I flag, exercised — it was not, so dropping it survived.
        "passes 1a/1b": ["1a", "1b"],
    }
    for text, expected in cases.items():
        m = _PASS_TOKEN.match(text)
        assert m and _pass_ids(m) == expected, (
            f"{text!r} parsed as {_pass_ids(m) if m else None}, expected {expected}"
        )
    # Over-capture control: a sentence continuing past the list must not swallow
    # the next number it meets.
    m = _PASS_TOKEN.match("Pass 5, and the runbook says 4 things")
    assert m and _pass_ids(m) == ["5"], _pass_ids(m) if m else None


def test_dropping_a_pass_from_the_runbook_is_detected():
    """Declared reversion test for the guard above, and it is aimed at the pass that was
    actually missing (4), not at one the file has always carried."""
    if not _in_source_repo():
        pytest.skip("sterilized mirror; the maintainer-side surface is correctly absent")
    for target in ("4", "5"):
        gutted = re.sub(rf"\bPass(es)?\s+{target}\b", "the excluded-class check",
                        _runbook(), flags=re.I)
        assert target not in _passes_named_in(gutted), (
            f"this control did not remove Pass {target} from the runbook text — it is "
            "passing on an unmutated file"
        )
        assert target in sorted(implemented_passes() - _passes_named_in(gutted)), (
            f"dropping Pass {target} from the runbook was not detected"
        )


def test_rewording_around_a_pass_name_stays_green():
    """Over-strictness control — the direction that gets guards deleted. Retitling a pass,
    changing its description, or reordering the list is ordinary editing."""
    if not _in_source_repo():
        pytest.skip("sterilized mirror; the maintainer-side surface is correctly absent")
    text = _runbook()
    reworded = (text
                .replace("Pass 4 (excluded *classes* still tracked",
                         "Pass 4 — excluded classes that are still tracked")
                .replace("Pass 1a (internal identifiers, token-scoped allowlist)",
                         "Pass 1a, the internal-identifier sweep,"))
    assert reworded != text, (
        "neither rewording anchor matched, so this control mutated nothing and is passing "
        "on an unmutated file — the no-op-control shape Phase 178's round caught"
    )
    assert not sorted(implemented_passes() - _passes_named_in(reworded)), (
        "rewording a pass description reddened the guard; it must key on the identifier"
    )


def test_a_pass_mentioned_but_not_listed_does_not_count():
    """Closes the two survivors the author-side battery left, and both are
    *semantic* controls rather than guards-on-guards: they assert what the
    population means, so reverting either scoping decision reddens here.

    - **In-prose, inside the right step.** Deleting Pass 5's bullet while its
      history is still discussed a sentence later kept the first version green.
      A pass an operator is *told about* is not a pass an operator is told to
      *run*.
    - **Bulleted, but in the wrong step.** The population is the verify-grep
      step, not the document; a bullet elsewhere must not satisfy it.
    """
    if not _in_source_repo():
        pytest.skip("sterilized mirror; the maintainer-side surface is correctly absent")
    text = _runbook()
    bullet = next((ln for ln in text.splitlines()
                   if re.match(r"^[ \t]*[-*][ \t]+Pass(?:es)?\s+5\b", ln)), None)
    assert bullet, "no Pass 5 bullet to work from — this control needs re-pointing"

    in_prose = text.replace(bullet, "   Pass 5 is one of the checks this page describes.")
    assert in_prose != text
    assert "5" in implemented_passes() - _passes_named_in(in_prose), (
        "a pass demoted from the operator's list to a passing prose mention still "
        "counted as listed — the check is matching the string, not the instruction"
    )

    # Bulleted in the right step, but the bullet is ABOUT something else. This is the
    # shape the original defect actually had — the lead was rewritten to a prose name
    # while the pass's own history stayed in the same item — and it is the only
    # mutation that distinguishes "must be a list item" from "must LEAD a list item".
    not_leading = text.replace(
        bullet, "   - The stripped-path check → MUST be empty. Phase 184 called it Pass 5.")
    assert not_leading != text
    assert "5" in implemented_passes() - _passes_named_in(not_leading), (
        "a bullet that merely mentions a pass while announcing something else counted "
        "as listing it — the lead requirement has been dropped"
    )

    elsewhere = text.replace(bullet, "")
    anchor = _discussions_anchor(text)
    assert anchor in elsewhere, "re-home anchor moved"
    elsewhere = elsewhere.replace(anchor, f"{anchor}\n   - Pass 5 — see above.\n", 1)
    assert "5" in implemented_passes() - _passes_named_in(elsewhere), (
        "a pass bulleted under an unrelated step satisfied the check — the "
        "population has been widened past the step that announces the passes"
    )


def test_the_sterilized_suite_step_does_not_contaminate_the_tree_it_greps():
    """`Q-257`, at the step that causes it.

    Steps 3 and 4 both operate on the same built tree: step 3 is the hand-run
    Pass 2/2b eyeball, step 4 runs the suite. Without these settings step 4
    writes `__pycache__/*.pyc` and `.pytest_cache/` into the tree step 3 greps,
    and the tokens Pass 2/2b look for are string literals in shipping test
    modules — so they end up in the bytecode and a re-run of the eyeball counts
    them. Measured 2 / 22 new contaminated against 0 / 7 clean.

    Prevention rather than filtering: the eyeball's `-I` is a second line of
    defence, but nothing stops a reader running the suite by some other means,
    and the ordering constraint was documented nowhere for the page's whole life.
    """
    if not RUNBOOK.exists():
        pytest.skip("tools/TESTER_MIRROR_RUNBOOK.md is maintainer-side and mirror-excluded")
    text = RUNBOOK.read_text(encoding="utf-8")
    # Every pytest invocation that runs INSIDE THE BUILT TREE. Two cuts were
    # wrong before this one, in opposite directions:
    #   * filtering on `wf-tester` missed the `--collect-only` pre-check, which
    #     is described as running "inside the built tree" without naming it and
    #     contaminates exactly the same;
    #   * taking every `-m pytest` on the page swept in the Pass 5/5b run, which
    #     the page explicitly runs in the SOURCE repo — demanding the hardening
    #     there is over-strictness, the direction that gets a guard deleted.
    # The discriminator is the source-repo run's own operands: it names specific
    # test modules because it is a targeted check on this repo, and the built-tree
    # runs never do.
    pytest_lines = [
        ln for ln in text.splitlines()
        if "-m pytest" in ln
        and not ln.lstrip().startswith("#")
        and "tests/" not in ln
    ]
    assert len(pytest_lines) >= 2, (
        f"only {len(pytest_lines)} built-tree pytest invocation(s) found on the "
        "runbook; there are two (step 4's full run and its --collect-only "
        "pre-check) and both contaminate. If one was removed, re-derive this "
        f"floor. Lines seen: {pytest_lines!r}"
    )
    for ln in pytest_lines:
        assert "PYTHONDONTWRITEBYTECODE=1" in ln, (
            f"step 4 writes bytecode into the tree step 3 greps: {ln.strip()!r}"
        )
        assert "no:cacheprovider" in ln, (
            f"step 4 leaves .pytest_cache/ in the tree step 3 greps: {ln.strip()!r}"
        )


# --- `Q-294`: step 5's history scan, now an executable ------------------------
#
# The arm itself is tested by EXECUTION in `tests/test_public_history_scan.py`,
# which builds repositories with known answers and runs the script against them.
# That module is the guard; this one only has to check that the page still calls
# it, because a script nothing invokes is a script that does not run.
#
# The five prose guards that used to live here were retired by the round that
# produced them. They asserted properties of a markdown fence — that a line
# matched `-vcx`, that an allow-list had two members, that `"$sha"` appeared —
# and an independent battery walked 13 of 18 mutations through them while three
# NEGATIVE CONTROLS false-killed on legal edits (a line continuation, retitling
# the step, an earlier step cross-referencing it). Simultaneously bypassable and
# over-strict is the signature of the wrong instrument, not of a guard needing
# more patches.


def _step5_block(text: str) -> str:
    """Step 5's body, bounded by the next numbered step.

    Keyed to the step NUMBER, not to its title. The retired prose guards keyed on
    the literal title and a round's control showed retitling the step false-killed
    all three of them — while `test_an_ordinary_rewording_stays_green` in this
    same module already declares retitling legal, using that exact replacement.
    """
    m = re.search(r"^5\. \*\*", text, re.M)
    assert m, "the runbook no longer has a step 5"
    nxt = re.search(r"^\d+\. \*\*", text[m.end():], re.M)
    return text[m.start():m.end() + nxt.start()] if nxt else text[m.start():]


def test_step_5_invokes_the_history_scan_script():
    """The page must still call it, and the script must still exist.

    A reversion guard in the strict sense: it fails if the invocation is removed
    from the page, and it fails if the page keeps calling a script that is gone.
    """
    block = _step5_block(_runbook())
    assert "scan_public_history.sh" in block, (
        "step 5 no longer invokes tools/scan_public_history.sh. The per-commit "
        "header arm is the only gate the project has on commit identity — every "
        "other pass reads a tree — and a step that does not call it reports clean "
        "over an unscanned history."
    )
    script = REPO_ROOT / "tools" / "scan_public_history.sh"
    assert script.is_file(), (
        "step 5 invokes tools/scan_public_history.sh but the script is absent "
        "from the source repo; the step would fail at the point an operator runs "
        "it, which is the worst moment to discover it"
    )


def test_every_step_that_needs_the_source_repo_says_so_before_using_it():
    """Phase 250 — the page's oldest defect, generalized past its fourth instance.

    Steps 4, 5 and 6 each move the operator's working directory: step 4 ends in
    the BUILD dir, step 6 opens with its own ``cd "$SMOKE"``. The mirror strips
    ``tools/``, so any *relative* ``tools/…`` invocation after step 4 resolves to
    nothing — which is what step 5 did until this test: ``exit 127`` from the only
    gate the project has on commit identity, at the point an operator runs it.

    This asserts the property rather than the one instance. Three earlier
    instances of the same class are recorded on the page itself (``$PY`` used
    above its assignment, ``rm -rf`` documented after the step that needs it, the
    tester-push form), and each was fixed one site at a time.
    """
    text = _runbook()
    # Numbered steps AND the `## Refreshing` section, which is the entry point for
    # every cut after the first and whose own last line leaves the operator in the
    # build dir. Treating it as part of step 11 — which an "until the next step or
    # EOF" walk does — reports the right defect under the wrong name, and the name
    # is what a reader chases.
    marks = [(m.start(), m.group(1)) for m in re.finditer(r"^(\d+)\. \*\*", text, re.M)]
    marks += [(m.start(), m.group(1)) for m in re.finditer(r"^## (\w+)", text, re.M)]
    marks.sort()
    assert marks, "the runbook has no numbered steps"
    # The operator's working directory only leaves the source repo at step 4, whose
    # own block ends with `cd /tmp/wf-tester`. So the threshold is positional, not a
    # named allow-list: everything BEFORE step 5 is read with the source repo as CWD
    # and needs no `cd`; everything after it — numbered step or `## ` section alike —
    # does. Naming the sections instead (the first version allow-listed only
    # `## Refreshing`) left a new section with a procedure in it unscrutinised, which
    # is what Phase 250's round-2 lens demonstrated with a `## Rehearsal`.
    _fifth = [pos for pos, nm in marks if nm.isdigit() and int(nm) >= 5]
    assert _fifth, "the runbook no longer has a step 5; this guard's threshold is gone"
    threshold = min(_fifth)
    offenders = []
    for i, (start, name) in enumerate(marks):
        if start < threshold:
            continue
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        block = text[start:end]
        n = name
        # ANY fenced block, not just ```bash. Phase 250's round-2 lens retagged
        # step 5's fence as ```sh and the guard went blind — the population was
        # exactly the two sites already fixed.
        for fence in re.findall(r"```[a-zA-Z]*\n(.*?)```", block, re.S):
            uses = []
            for ln in fence.splitlines():
                if ln.lstrip().startswith("#"):
                    continue
                # `tools/x.sh`, `./tools/x.sh` and `$SRC/tools/x.sh` are the same
                # invocation from the operator's point of view. The first version
                # excluded the last two with a lookbehind, which is two of the
                # four escapes the lens drove through.
                if re.search(r'''(?:^|[\s"'(=])(?:\./|\$\{?\w+\}?/)?tools/[\w.-]+\.(?:sh|py)''', ln):
                    uses.append(ln)
            if not uses:
                continue
            # EVERY use, not just the first: a block may `cd` correctly, then
            # `cd` away, then invoke again — which is the Refreshing block's own
            # shape. Track the working directory across the fence.
            at_source = False
            for ln in fence.splitlines():
                stripped = ln.strip()
                if stripped.startswith("#"):
                    continue
                if re.match(r"(cd|pushd)\s+\S*<\s*(the\s+)?source repo\s*>", stripped):
                    at_source = True
                elif re.match(r"(cd|pushd)\s+\S", stripped):
                    at_source = False
                if ln in uses and not at_source:
                    offenders.append((n, stripped))
    assert offenders == [], (
        "these steps invoke a relative tools/ path with no `cd <source repo>` "
        "above it in the same block. After step 4 the operator is in the BUILD "
        "dir, where tools/ does not exist, so the command is `command not "
        f"found`:\n{offenders}"
    )


# --- Phase 273 (`Q-437`) — the PUBLIC push must stay announced -----------------
#
# Steps 1-11 route the tester half. The public repo accumulates history and its
# main is protected, so its push is a *different* operation on the same built
# tree — and for the life of this page it had no numbered step at all: it existed
# only as a contrast paragraph inside step 7 and as a block the builder prints.
#
# Phase 273's own review round wrote 19 mutations against the new step and 16
# survived, because nothing constrained it but the shared `cd <source repo>` rule
# above. Three of those survivors are the ones that matter, and they are the ones
# this guard closes: DELETE the step, MOVE it into `## Refreshing`, or RENUMBER it
# away. Each returns the page to the exact state `Q-437` was filed against, and
# each read green.
#
# What this guard deliberately does NOT try to do is judge whether the step's
# prose is *true* — that is the class the round found (a claim that a non-blocking
# `|| { …; false; }` arm is a gate; an ordering rule stated as universal), and no
# pattern encodes it. Those are filed, not mechanized. See `Q-453`.
_PUBLIC_REPO = "getsysop/sysop"


def _public_push_steps(text: str) -> list[tuple[int, str, str]]:
    """Numbered steps whose bolded TITLE announces the public push.

    Keyed on the title, matching this module's existing `missing_gates` idiom: a
    step whose *body* happens to mention the public repo is not an announcement,
    and step 7's contrast paragraph is exactly that shape — it names the public
    mirror in order to say it is NOT that step.
    """
    return [s for s in numbered_steps(text)
            if re.search(r"public", s[1], re.I) and re.search(r"push|append", s[1], re.I)]


def missing_public_push(text: str) -> list[str]:
    problems = []
    steps = _public_push_steps(text)
    if not steps:
        problems.append(
            "no numbered step announces the PUBLIC push. Steps 1-11 route the tester half; "
            "the public repo is a separate append via PR, and describing it only inside "
            "another step's body — which is the state Q-437 was filed against — leaves the "
            "irreversible half of the procedure with no step an operator walks"
        )
        return problems

    # The step must live in `## Steps`. Moving it into `## Refreshing` or past the
    # end of the numbered list demotes it to an aside, which is the same defect
    # wearing the step's own title.
    if not any(f"{n}. **" in _steps_section(text) for n, _, _ in steps):
        problems.append(
            "the public-push step is not inside the '## Steps' section — a numbered step "
            "that has been moved out of the walked list is an aside with a number on it"
        )

    # It must name the public repo somewhere in its own body. A step titled for the
    # public push that never says which repo is not routing anything.
    #
    # The span ends at the next numbered step OR the next `## ` heading, whichever
    # comes first. Bounding it only by the next step is the header-eats-neighbour
    # defect this project has hit on four parsers: the public-push step is the LAST
    # numbered one, so an EOF-bounded span swallows `## Refreshing` — and since that
    # section now names the public repo too, the body check passed on its neighbour's
    # text. Caught by this guard's own battery, not by reading it.
    marks = [(m.start(), m.group(1)) for m in re.finditer(r"(?m)^(\d+)\. \*\*", text)]
    marks += [(m.start(), None) for m in re.finditer(r"(?m)^## ", text)]
    marks.sort()
    announced = {n for n, _, _ in steps}
    for i, (pos, name) in enumerate(marks):
        if name is None or int(name) not in announced:
            continue
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        if _PUBLIC_REPO not in text[pos:end]:
            problems.append(
                f"step {name} is titled for the public push but never names "
                f"{_PUBLIC_REPO} in its body"
            )

    # `## Refreshing` is the entry point for EVERY cut after the first — the guard
    # above already encodes that for the gate steps. A refresh that stops at the
    # tester force-push has shipped to testers and not to the public, and the
    # filing measured this section at zero mentions of the public repo.
    m = re.search(r"(?m)^## Refreshing\s*$", text)
    if m:
        end = text.find("\n## ", m.end())
        refresh = text[m.start(): end if end != -1 else len(text)]
        if _PUBLIC_REPO not in refresh:
            problems.append(
                "'## Refreshing' never names the public repo, so the section every cut "
                "after the first actually follows routes only the tester half — the "
                "measurement in Q-437's own filing, which a numbered step alone does not fix"
            )
    return problems


def test_the_runbook_keeps_a_numbered_step_for_the_public_push():
    assert missing_public_push(_runbook()) == []


def test_the_public_push_guard_is_not_vacuous():
    """Red against the tree the filing was written about.

    Pinned to the literal pre-fix commit, and SKIPPED rather than failed when that
    commit is unreachable — CI's `actions/checkout` takes its default
    `fetch-depth: 1`, where it is not present. That is not a hypothetical: Phase
    271 pinned two controls to a literal SHA and Phase 272's round measured both
    failing on a real `--depth 1` clone, which would have reddened the required
    check on every push. The precedent this follows is
    `test_rollback_commit_stays_deleted.py`.
    """
    if not _in_source_repo():
        pytest.skip("not the source repo")
    pre = _pinned_runbook("8fcdd05")
    problems = missing_public_push(pre)
    assert problems, (
        "the predicate found nothing wrong with the PRE-FIX runbook, which had no "
        "numbered public-push step at all — the guard is not measuring what it claims"
    )
    assert any("no numbered step announces" in p for p in problems), (
        f"the control fired, but not on the absence this guard exists for: {problems}"
    )


def test_the_post_push_arms_each_fire_on_their_own_defect():
    """One control per ARM, because a guard nobody can revert is not guarded.

    An independent lens reverted each of this predicate's three mechanisms
    separately — `n > push` to `n >= push`, the fresh-clone arm to `if False:`,
    and command-position back to a substring test — and the whole module stayed
    green at 29 passed. The non-vacuity control above pins only the
    *count* arm, against a tree that had one scan step. Three mechanisms, zero
    controls, is the "guard-of-the-guard" gap this project has now paid for twice.

    Each mutation below is applied to the LIVE runbook, so the controls cannot
    drift away from the text they are about.
    """
    text = _runbook()
    inv = [ln for ln in text.splitlines() if _runs_scan(ln) and "$A" in ln]
    assert len(inv) == 1, f"expected one post-push invocation to mutate, saw {inv!r}"
    line = inv[0]

    # (1) ordering — the post-push step demoted into the push step's own body.
    m13 = re.search(r"(?m)^13\. \*\*", text)
    assert m13, "the post-push step is no longer numbered 13; re-point this control"
    demoted = text[:m13.start()] + "    **(e) " + text[m13.end():]
    assert any("at or before the" in p for p in missing_post_push_scan(demoted)), (
        "demoting the post-push step into the push step's body did not fire the "
        "ordering arm — `12 < 12` again"
    )

    # (2) the fresh-clone arm — scan pointed at the pre-push build dir.
    stale = text.replace(line, line.replace('"$A"', "/tmp/sysop-gate"), 1)
    assert any("fresh clone" in p for p in missing_post_push_scan(stale)), (
        "pointing the post-push scan at the pre-push build dir did not fire the "
        "fresh-clone arm — taking a clone is not scanning it"
    )

    # (2b) repo IDENTITY, not merely that a clone happened. Control (2) moves the
    # scan's ARGUMENT, so it fires on the target-token rule whatever the slug
    # says — which left `if slug != _PUBLIC_REPO` revertible in silence. Here the
    # target is untouched and only the repo changes, so nothing but the slug
    # check can catch it.
    clone_lines = [ln for ln in text.splitlines()
                   if "git clone" in ln and '"$A"' in ln]
    assert clone_lines, "the post-push clone anchor moved; re-point this control"
    wrong_repo = text.replace(
        clone_lines[0],
        clone_lines[0].replace("getsysop/sysop.git", "wade-cms/sysop-tester.git"), 1)
    assert any("fresh clone" in p for p in missing_post_push_scan(wrong_repo)), (
        "cloning the TESTER repo into the same target did not fire — repo "
        "identity is not being checked, only that some clone happened"
    )

    # (3) a display fence is not a prescribed command. A lens widened
    # `_EXEC_TAGS` to accept ` ```text ` and the module stayed at 31 passed,
    # while the retag it exists to catch went from killed to surviving — the
    # only one of the predicate's mechanisms that could be reverted in silence.
    retagged = text.replace("    ```bash\n    cd <source repo>", "    ```text\n    cd <source repo>", 1)
    assert retagged != text, "the leg-(a) fence anchor moved; re-point this control"
    assert any("not two" in p for p in missing_post_push_scan(retagged)), (
        "retagging the post-push fence as a non-executable display block did not "
        "fire — `_EXEC_TAGS` has been widened and nothing else says so"
    )

    # (4) command position — the script mentioned rather than run.
    # `cat`, deliberately flagless. The first version of this control used
    # `grep -n …`, and the `-n` killed it through `_NOT_A_RUN_FLAGS` rather than
    # through the wrapper allowlist — so `return all(w in _WRAPPERS …)` could be
    # replaced by `return True` with this whole module green. A control that fires
    # through a mechanism it is not testing pins nothing, and this one was found
    # by reverting each mechanism in turn rather than by reading it.
    mention = text.replace(line, "    cat tools/scan_public_history.sh", 1)
    assert any("not two" in p for p in missing_post_push_scan(mention)), (
        "replacing the run with a grep of the script did not fire the count arm — "
        "a mention is not a run"
    )


def test_the_post_push_controls_stay_green_on_legal_edits():
    """The direction that gets a correct guard deleted rather than fixed.

    A lens measured the previous version at 8 false-reds on edits a maintainer
    would really make. Each of these must stay green.
    """
    text = _runbook()
    invs = [ln for ln in text.splitlines() if _runs_scan(ln) and "$A" in ln]
    clones = [ln for ln in text.splitlines() if "git clone" in ln and "$A" in ln]
    assert invs and clones, (
        f"this control needs the post-push invocation and its clone to anchor on; "
        f"saw {len(invs)} invocation(s) and {len(clones)} clone(s). Re-point it "
        "rather than letting an IndexError stand in for a message"
    )
    inv, clone = invs[0], clones[0]
    legal = {
        "time-prefixed": text.replace(inv, inv.replace("bash ", "time bash "), 1),
        "bash -x": text.replace(inv, inv.replace("bash ", "bash -x "), 1),
        "bare command word": text.replace(inv, inv.replace("bash tools/", "tools/"), 1),
        "output captured": text.replace(
            inv, '    OUT=$(bash tools/scan_public_history.sh "$A")', 1),
        "clone and scan merged with &&": text.replace(
            clone + "\n" + inv, clone + " \\\n      && " + inv.strip(), 1),
        "fence retagged ```sh": text.replace("```bash", "```sh"),
        "gh repo clone": text.replace(
            clone, '    A=$(mktemp -d)/after && gh repo clone getsysop/sysop "$A"', 1),
    }
    red = {k: missing_post_push_scan(v) for k, v in legal.items()}
    red = {k: v for k, v in red.items() if v}
    assert not red, f"legal edits reddened the guard: { {k: v[0][:110] for k, v in red.items()} }"


# --- Phase 273 — the page's own two piping rules, applied to its own fences ----
#
# The page states both in prose and had, until this guard, enforced neither:
#   * "Never pipe a push" (step 7) — in a shell without `pipefail`, `git push … |
#     tail` reports TAIL's status, so a failed push reads as exit 0. That is how
#     the SSH failure behind `Q-424` got past its first run and had to be found
#     twice.
#   * Never `head` a gate — `head` closes the pipe early and SIGPIPEs the producer,
#     so a gate can be truncated into looking clean.
#
# Phase 273's own new fence broke the first rule in its first draft (it piped the
# builder into `sed`, masking a refusal behind sed's exit 0) and the author caught
# it only by running it. A round then wrote both violations as mutations and both
# survived, because nothing here read fences for this.
#
# Green on arrival: zero fence lines in the page match either shape.
_PIPE_TO_PAGER = re.compile(r"\|\s*(?:head|tail)\b")
_PUSH_THEN_PIPE = re.compile(r"\bgit\s+push\b[^|]*\|")


def piping_violations(text: str) -> list[str]:
    out = []
    for fence in re.findall(r"```[a-zA-Z]*\n(.*?)```", text, re.S):
        for ln in fence.splitlines():
            stripped = ln.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if _PIPE_TO_PAGER.search(stripped):
                out.append(f"pipes into head/tail (truncates a producer via SIGPIPE): {stripped}")
            if _PUSH_THEN_PIPE.search(stripped):
                out.append(f"pipes a push (reports the pipe's status, not git's): {stripped}")
    return out


def test_the_runbook_never_pipes_a_push_or_heads_a_gate():
    assert piping_violations(_runbook()) == []


def test_the_piping_guard_fires_on_both_shapes():
    """Non-vacuity, planted rather than pinned to a commit.

    Both plants are the literal shapes the page's prose forbids and that a review
    round drove through the page unguarded.
    """
    text = _runbook()
    anchor = "    ```bash\n"
    assert anchor in text, "no bash fence to plant into; this control's anchor needs revisiting"
    for plant, want in (
        ("    bash tools/make_public_mirror.sh \"$D/reprint\" | head -20\n", "head/tail"),
        ("    git push origin main:snapshot-refresh-x | tee /tmp/log\n", "push"),
    ):
        mutated = text.replace(anchor, anchor + plant, 1)
        found = piping_violations(mutated)
        assert any(want in f for f in found), (
            f"planting {plant.strip()!r} did not fire the {want} arm: {found}"
        )


# --- Phase 274 (`Q-452`) — the POST-push half must stay on the page -----------
#
# `Q-437` closed "the page has no numbered step for the public push". `Q-452` is
# its sibling, found while fixing it: the page ended at two pushes and prescribed
# nothing after them. Three things were done at each of the three most recent cuts
# (250, 265, 268) and were carried by the operator's memory rather than by this
# page — re-running the history scan against the PUSHED history, cold-clone
# verification of both published repos, and archiving the cut record in a
# post-merge commit.
#
# This guard is keyed to the MECHANISM, not to a title. Phase 273's public-push
# guard keys on words ("public" + "push") that are semantically forced; nothing is
# forced about the wording of a verification step, and this module already
# declares retitling and coherent renumbering legal in two negative controls. So
# the property asserted is the one `Q-452` actually measured: the history scan is
# invoked by TWO numbered steps, and the second of them comes after the step that
# announces the public push. One invocation is the pre-push gate (step 5, "is the
# published history clean before I append to it"). The second is a different
# question — "did the commit I just merged introduce one" — and no clone taken
# before the merge can answer it.
#
# What this does NOT assert is that the step's prose is true, which is `Q-453`'s
# open class for the neighbouring step and is no more mechanizable here.


_SCAN = "scan_public_history.sh"

# Three independent lenses shaped this predicate and the first two versions were
# each wrong in the same direction: they accepted something that is not the thing
# they want.
#
#   v1 asked whether the bare NAME appeared in a live fence line. `grep -nE …
#      tools/scan_public_history.sh`, `ls -l` and `echo bash …` all read green —
#      a mention is not a run, and marking a non-running step compliant is worse
#      than a gap.
#   v2 asked for the name in COMMAND position plus "a git clone somewhere in the
#      same fence". Taking a clone is not scanning it: pointing the scan at the
#      pre-push gate build dir, at step 5's own clone, or at nothing at all, all
#      read green beside an untouched clone line. Presence is not property.
#
# v3 asks the question the step is actually about: **is a freshly cloned copy of
# the PUBLIC repo the thing being scanned.** The clone's target token and the
# scan's argument must be the same token, and the clone's URL must name the
# public repo — otherwise the step is step 5's question wearing a later number,
# which is the phrase the failure message uses because it is the defect.
#
# The other direction is the one that gets a correct guard deleted rather than
# fixed, and v2 was measured at 8 false-reds on legal edits. So:
#   * command position is decided by an EXCLUDER, not by an anchored prefix. A
#     line runs the script unless a word that would consume it as an ARGUMENT
#     appears before it. `time bash …`, `bash -x …`, `cd "$A" && bash …`,
#     `OUT=$(bash …)` and an `&&`-merged clone-and-scan are all runs.
#   * locality is the STEP, not the fence. Splitting a prose-heavy step's fence
#     in two is an ordinary edit and v2 reddened on it.
#   * the fence tag must be one a reader would execute. ` ```text ` is a display
#     block, and v2's hand-rolled parser accepted it while the module's own
#     `numbered_steps` would not have — two parsers, one charclass apart.

# v3 asked "is a word that would consume the script as an argument in front of
# it" (an open denylist) and "is the public repo named on the clone line" (a
# substring of the RAW line, comment included). A fourth lens walked 13 of 37
# mutations through both. v4 replaces each with the narrower question:
#
#   * command position is decided inside the SEGMENT that contains the script —
#     the line split on `;`, `&&`, `||`, `|` — and the only words allowed in
#     front of it are exec wrappers. An open denylist could not name `bash -n`,
#     `xargs`, `bat` or `python3 -c`; an allowlist over a segment also fixes the
#     false-red on `echo "..."; bash tools/…`, where v3 read a mention word from
#     a different command on the same line.
#   * repo identity is the parsed `owner/name` SLUG, not a substring. v3 accepted
#     `getsysop/sysop-archive.git` and `getsysop/sysop-fork.git`, and — because it
#     kept the raw line — accepted a clone of ANYTHING carrying the words
#     `getsysop/sysop` in a trailing comment. Its failure message named that exact
#     defect as the thing it caught.
_WRAPPERS = {"bash", "sh", "zsh", "time", "env", "exec", "cd", "then", "do",
             "else", "elif", "if", "sudo", "nohup", "command", "!", "{", "("}
_NOT_A_RUN_FLAGS = {"-n"}      # `bash -n <script>` parses it; it does not run it
_EXEC_TAGS = {"", "bash", "sh", "shell", "zsh", "console"}
_CLONE = re.compile(r"\b(?:git\s+clone|gh\s+repo\s+clone)\b(?P<rest>.*)$")
_SEGMENT = re.compile(r";|&&|\|\||\|")


def _token(s: str) -> str:
    """A shell word with quoting, braces and trailing punctuation normalised.

    The trailing strip is not cosmetic and every character in it was put there by
    a negative control that reddened — the author-side rule's point about a guard
    keyed to a physical line:

      * a line-continuation `\\` is its own word, so `git clone … "$A" \\` made the
        BACKSLASH the clone's target;
      * `OUT=$(bash … "$A")` carries the subshell's closing paren into the argument;
      * `git clone … "$A" 2>/dev/null` and `… "$A" || exit 1` put a redirect or an
        exit status where the target should be.
    """
    s = s.strip().rstrip("\\);&|")
    s = s.strip("'\"").replace("${", "$").rstrip("}")
    return "" if s.startswith((">", "<", "2>", "&>")) else s


def _segment_with(line: str, needle: str) -> str | None:
    """The one command in `line` that contains `needle`, or None.

    A line is not a command; it is a list of them. v3 read the whole prefix, so
    `echo "post-push scan"; bash tools/…` was rejected because another command's
    verb sat to the left of this one.
    """
    body = line.split("#", 1)[0]
    if needle not in body:
        return None
    for seg in _SEGMENT.split(body):
        if needle in seg:
            return seg
    return None


def _words_before(seg: str, needle: str) -> tuple[list[str], list[str]]:
    """(command words, flags) appearing before `needle` in one command segment."""
    head = seg[:seg.find(needle)].replace("$(", " ").replace("`", " ")
    words, flags = [], []
    for raw in head.split():
        if raw.startswith("-"):
            flags.append(raw)
            continue
        w = _token(raw)
        if not w or "=" in w:
            continue
        w = w.rsplit("/", 1)[-1]
        if w:                 # `tools/` is the script's own path prefix, not a word
            words.append(w)
    return words, flags


def _runs_scan(line: str) -> bool:
    seg = _segment_with(line, _SCAN)
    if seg is None:
        return False
    words, flags = _words_before(seg, _SCAN)
    if any(f in _NOT_A_RUN_FLAGS for f in flags):
        return False
    return all(w in _WRAPPERS for w in words)


def _scan_arg(line: str) -> str | None:
    """The path the scan is pointed at, or None when it is pointed at nothing.

    Flags are skipped, which `_clone_targets` already did — v3's asymmetry made
    `bash … --strict "$A"` read its own flag as the target.
    """
    seg = _segment_with(line, _SCAN)
    if seg is None:
        return None
    rest = seg[seg.find(_SCAN) + len(_SCAN):].split()
    for raw in rest:
        if raw.startswith("-"):
            continue
        tok = _token(raw)
        if tok:
            return tok
    return None


def _clone_slug(line: str) -> str | None:
    """`owner/name` for a clone of a GitHub repo, or None.

    Parsed from the URL rather than matched as a substring, and read from the
    line with its COMMENT REMOVED. v3 did neither, so a clone of the tester repo,
    of step 5's clone, or of the local checkout all passed by carrying the words
    `getsysop/sysop` in a trailing comment — and `getsysop/sysop-archive.git`
    passed with no comment at all.
    """
    body = line.split("#", 1)[0]
    m = _CLONE.search(body)
    if not m:
        return None
    for raw in m.group("rest").split():
        if raw.startswith("-"):
            continue
        w = _token(raw)
        if not ("github.com" in w or re.fullmatch(r"[\w.-]+/[\w.-]+", w)):
            continue
        # The last two path components, parsed — never a substring match. `:` is a
        # separator too, so an ssh remote resolves the same as an https one.
        parts = [c for c in w.replace(":", "/").split("/") if c]
        if len(parts) < 2:
            continue
        owner, name = parts[-2], parts[-1]
        return f"{owner}/{name[:-4] if name.endswith('.git') else name}"
    return None


def _clone_targets(live: list[str]) -> list[tuple[str, str | None]]:
    """[(target token, cloned repo slug or None)] for every clone in the block."""
    out = []
    for ln in live:
        body = ln.split("#", 1)[0]
        m = _CLONE.search(body)
        if not m:
            continue
        words = [_token(w) for w in _SEGMENT.split(m.group("rest"))[0].split()
                 if not w.startswith("-")]
        words = [w for w in words if w]      # a bare continuation normalises away
        if words:
            out.append((words[-1], _clone_slug(ln)))
    return out


def _scan_runs(text: str) -> list[tuple[int, bool]]:
    """[(step number, scans a fresh clone of the PUBLIC repo)] per running step.

    Locality is the step, so a clone in one fence pairs with a scan in the next.
    """
    steps = _steps_section(text)
    marks = list(re.finditer(r"(?m)^(\d+)\. ", steps))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(steps)
        body = steps[m.start():end]
        live: list[str] = []
        for tag, fence in re.findall(r"```([a-zA-Z-]*)\n(.*?)```", body, re.S):
            if tag.lower() in _EXEC_TAGS:
                # `_live_lines` drops whole commented-out lines. It is belt to the
                # braces of `_runs_scan`/`_scan_arg`/`_clone_targets`, which each
                # split on `#` themselves — a lens measured removing it as a no-op,
                # so it is kept as the module's shared idiom, not as the mechanism.
                live += _live_lines(fence)
        runs = [ln for ln in live if _runs_scan(ln)]
        if not runs:
            continue
        clones = _clone_targets(live)
        fresh = False
        for r in runs:
            arg = _scan_arg(r)
            if arg is None:
                continue
            for tgt, slug in clones:
                if slug != _PUBLIC_REPO:
                    continue
                # `cd "$A" && bash … .` scans the clone it just entered.
                cd_here = arg == "." and any(
                    _token(w) == tgt for w in
                    re.findall(r"\bcd\s+(\S+)", r.split("#", 1)[0]))
                if tgt == arg or cd_here:
                    fresh = True
        out.append((int(m.group(1)), fresh))
    return out


def missing_post_push_scan(text: str) -> list[str]:
    runs = _scan_runs(text)
    steps = sorted({n for n, _ in runs})
    if len(steps) < 2:
        return [
            f"tools/{_SCAN} is RUN by {len(steps)} numbered step(s), not two. The "
            "pre-push run gates the cut; the post-push run answers a different "
            "question — whether the commit just merged introduced a finding — and "
            "step 5's clone predates that commit by construction, so it cannot. "
            "Carried by operator memory at the 250, 265 and 268 cuts and by no "
            "step until Q-452"
        ]
    announced = [n for n, _, _ in _public_push_steps(text)]
    if not announced:
        # missing_public_push owns the absence and fails independently, so the
        # suite still reddens; this arm simply has no push step to order against.
        return []
    # The FIRST announcing step, not the last. A lens retitled step 13 to
    # `**Verify the public push landed, …**` — a title this module's own docstring
    # lists as a legitimate edit — and `max()` made the scan step its own push
    # step, so the ordering arm reddened on a correct page. `min()` is also the
    # right reading: the push is announced once, and anything after that first
    # announcement is post-push.
    push = min(announced)
    # STRICTLY after. v1 asked `max(steps) < push`, which is False when the
    # post-push step has been demoted into the push step's own body — scanners
    # [5, 12] against push 12 — and that demotion is the exact state both Q-437
    # and Q-452 were filed against. `12 < 12` read green.
    after = [n for n in steps if n > push]
    if not after:
        return [
            f"every history-scan run (steps {steps}) is at or before the "
            f"public-push step (step {push}), so the page has no run against the "
            "PUSHED history. A leg demoted into the push step's own body is not a "
            "numbered step an operator walks — the shape Q-437 and Q-452 name"
        ]
    if not any(fresh for n, fresh in runs if n in after):
        return [
            f"the post-push scan (step {min(after)}) is not pointed at a fresh "
            f"clone of {_PUBLIC_REPO} that the same step takes. Scanning the "
            "pre-push build dir, reusing step 5's clone, cloning the tester repo, "
            "or passing no path at all are each step 5's question wearing a later "
            "number — and each read green until an independent lens ran them"
        ]
    return []


def test_the_runbook_re_runs_the_history_scan_after_the_push():
    assert missing_post_push_scan(_runbook()) == []


def test_the_post_push_scan_guard_is_not_vacuous():
    """Red against the tree `Q-452` was filed about.

    Pinned to Phase 273's squash — the commit that shipped step 12 and left the
    post-push half unwritten — and SKIPPED rather than failed when unreachable.
    CI's `actions/checkout` takes its default `fetch-depth: 1`; Phase 271 pinned
    two controls to a literal SHA and Phase 272's round measured both failing on a
    real depth-1 clone, which would have reddened the required check on every push.
    """
    if not _in_source_repo():
        pytest.skip("not the source repo")
    pre = _pinned_runbook("0da3fd6")
    problems = missing_post_push_scan(pre)
    assert problems, (
        "the predicate found nothing wrong with the PRE-FIX runbook, which invoked "
        "the history scan from exactly one step — the guard is not measuring what "
        "it claims"
    )
    assert any("not two" in p for p in problems), (
        f"the control fired, but not on the absence this guard exists for: {problems}"
    )


# --- Phase 283 — a GitHub list endpoint defaults to `state=open` ---------------
#
# Pass 5b's bullet supplies the PR-number ceiling an operator judges citations
# against, and told them to re-derive it with
# `gh api repos/getsysop/sysop/pulls --jq 'max_by(.number).number'`.
#
# That command does not answer the question. `/pulls` and `/issues` are list
# endpoints and both default to `state=open`; `getsysop/sysop` merges every
# snapshot PR and closes nothing else, so the open set is routinely EMPTY, and
# `max_by` over an empty array prints `null` — which `--jq` renders as a blank
# line at **exit 0**. Measured 2026-09-11: the bare form printed empty, the
# `state=all` form printed 45.
#
# The failure direction is the one that matters. An empty answer in a paragraph
# whose entire job is to supply a ceiling reads as *there is no ceiling*, so an
# unresolvable citation gets waved through — and the bullet itself says the
# below-ceiling case is "the worse direction ... because it reads as
# corroboration". A gate that prints nothing on a question it cannot answer is
# this page's oldest recorded shape, and here it was in the page's own prose.
#
# Keyed to the MECHANISM, not to this one line: any `gh api` call on a list
# endpoint whose default excludes what the caller is counting must name the
# state it wants. Everything about the surrounding text is free — the repo slug,
# the jq expression, the page number, the prose, moving it into a fence.
#
# **Stated at its true width, corrected by the round.** The first version of this
# paragraph named the residual that a SIBLING already covers — deleting the Pass-5b
# bullet outright, which `test_the_runbook_names_every_pass_the_gates_implement`
# reddens — and was silent on the one nothing covered: **keep the bullet, delete
# only the command.** A lens measured it: replacing the invocation with "re-derive
# it yourself" left all five runbook-reading modules green, and the operator with
# no way to derive the ceiling at all. So the shape check below is paired with a
# subject check, and this comment now names the case each one owns.

_STATE_DEFAULTING_ENDPOINTS = ("pulls", "issues", "milestones")

# `search/issues` is NOT one of them, and a lens caught the first version
# reddening it. The search API takes no `state` parameter at all — state lives
# inside `q` as `is:merged` / `state:closed` — so demanding one there fails a
# correct call, the direction this module keeps recording as the way a correct
# guard gets deleted. It is the common GitHub path that happens to end in
# `/issues`, which is exactly why a path-suffix match had to learn about it.
_SEARCH_PATHS = ("search/issues", "search/repositories", "search/commits")

# The SAME default, in the spelling this page actually uses. A lens counted the
# file: 9 `gh pr` against 1 `gh api`, and demonstrated the identical failure by
# running it —
#
#   gh pr list --repo getsysop/sysop --limit 100 --json number \
#     --jq 'max_by(.number).number'        -> prints nothing, exit 0
#   ... --state all ...                     -> prints 45
#
# so a guard keyed only to `gh api` covers the rarer half of its own class in
# its own file. `gh pr list` and `gh issue list` both default to open and take
# `--state`/`-s` rather than a query parameter.
_STATE_DEFAULTING_SUBCOMMANDS = ("pr", "issue")


def _scannable(text: str) -> str:
    """The text a command could actually be read out of.

    Two normalizations, both found by running a hostile corpus against the first
    version of this predicate rather than by reading it:

    * **Backslash continuations are joined first.** A guard keyed to a physical
      line is walked through by a line continuation — `_shared/adversarial-review.md`
      names that class by name — and here it failed in the *over-strict*
      direction, which is worse: `gh api repos/o/r/pulls \\` + `-f state=all`
      is a correct call that reddened, and a guard that fires on the idiomatic
      form is one a maintainer learns to delete.
    * **Comment lines are dropped**, matching this module's own `_live_lines`
      doctrine — a commented-out command is not a command, and there is nothing
      for an operator to run. Markdown headings start with `#` too and are
      dropped by the same rule, which is harmless: a heading is not a command
      either.
    """
    uncommented = "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("#")
    )
    return re.sub(r"\\\n\s*", " ", uncommented)


def _gh_api_list_calls(text: str) -> list[str]:
    """Every `gh api` invocation in the runbook that hits a LIST endpoint.

    A single-resource path (`repos/o/r/pulls/45`) takes no `state` and is not a
    list — matching it would redden a legal edit, which is the direction that
    gets a correct guard deleted. So the path must END at the collection, with
    nothing after it but an optional query string.
    """
    out = []
    scannable = _scannable(text)
    for m in re.finditer(r"gh\s+api\b[^\n`]*", scannable):
        call = m.group(0)
        endpoint = re.search(
            r"[A-Za-z0-9_.\-/]*/(" + "|".join(_STATE_DEFAULTING_ENDPOINTS) + r")"
            # The path may be followed by a query string, and then by ANY
            # non-path character. The first version whitelisted end-of-span,
            # whitespace and quotes — so `…/pulls;`, `…/pulls,`, `(…/pulls)`
            # each stopped being seen as a call, and a lens walked all three.
            # `/` stays excluded on purpose: that is what keeps a
            # single-resource path (`/pulls/45`, `/pulls/45/files`) out.
            r"(\?[^\s'\"]*)?(?=$|[^A-Za-z0-9_.\-/])",
            call,
        )
        if endpoint and not any(sp in call for sp in _SEARCH_PATHS):
            out.append(call)
    # `gh pr list` / `gh issue list` — same default, different spelling. Only
    # `list` is a collection: `gh pr checks`, `gh pr merge`, `gh pr view` and
    # `gh pr create` all take a selector and no state, and the runbook uses all
    # four. Matching them would redden nine correct lines.
    for m in re.finditer(
        r"gh\s+(?:" + "|".join(_STATE_DEFAULTING_SUBCOMMANDS) + r")\s+list\b[^\n`]*", scannable
    ):
        out.append(m.group(0))
    return out


# WHERE the state has to appear, not merely THAT the token appears. The first
# version was `\bstate=`, which matches anywhere in the call — including inside
# a `--jq` filter. An independent lens found the bypass by running it:
#
#   gh api repos/o/r/pulls --jq '[.[]|select(.state=="open")]|length'
#
# names no state PARAMETER, silently returns only open pull requests, and read
# CLEAN. That is `_shared/adversarial-review.md` rule 1's named failure — "a
# check satisfied by a substring is satisfied by an incidental use of that
# substring — worse than a gap, because it marks a dangerous line compliant" —
# and it marked compliant the exact shape this guard exists to catch.
_STATE_NAMED = re.compile(
    r"""
      # A VALUE is required. `?state=&per_page=100` satisfied the first
      # version — the parameter is named and empty, which GitHub does not read
      # as "all". A lens found it; it is the emptiest possible way to look
      # compliant.
      [?&]state=[^&\s'\"]                                     # gh api, query string
    | (?:^|\s)(?:-f|-F|--field|--raw-field)(?:\s+|=)state=[^\s'\"]   # gh api, flag value
    | (?:^|\s)(?:--state|-s)(?:\s+|=)\S                      # gh pr/issue list
    """,
    re.VERBOSE,
)

# A query string the guard cannot read, because the value is not in the text.
# `QS='state=all&per_page=100'; gh api "repos/o/r/pulls?$QS"` is a correct,
# ordinary call — this page already parameterizes `$PY` and `$P` — and the first
# version of this guard reddened it. A lens found it as a FALSE ALARM, and
# reddening a correct idiom is the direction that gets a guard deleted rather
# than fixed. So an expansion in the query string is ACCEPTED, and the cost is
# named here rather than left implicit: an author who wants past this guard can
# put the query in a variable. That is a real residual, not a closed case — it is
# just a smaller hole than punishing the idiom, and the guard reads one file that
# a determined author is editing anyway.
_SHELL_EXPANSION = re.compile(r"\?[^\s'\"]*\$")


def _names_a_state(call: str) -> bool:
    """A `state` PARAMETER, in gh's spellings: `?state=`/`&state=` in the query
    string, or `-f`/`-F`/`--field`/`--raw-field` carrying it.

    `state=open` counts as naming one — an operator who asked for open pull
    requests on purpose is not this guard's business. What is not allowed is
    leaving the default unstated on a call whose answer depends on it.
    """
    return _STATE_NAMED.search(call) is not None or _SHELL_EXPANSION.search(call) is not None


def unstated_state_calls(text: str) -> list[str]:
    return [c for c in _gh_api_list_calls(text) if not _names_a_state(c)]


def _ceiling_bullet(text: str) -> str:
    """The Pass 5b bullet — the one that hands the operator a number to judge
    citations against. Anchored on the pass name, which the sibling guard
    already requires to be present, and ended at the next list item."""
    m = re.search(r"(?m)^\s*- Pass 5b\b.*?(?=\n\s*-\s|\n\n)", text, re.S)
    return m.group(0) if m else ""


def test_the_ceiling_bullet_still_hands_the_operator_a_command():
    """The residual the round found: keep the bullet, delete only the command.

    Measured green across all five runbook-reading modules before this existed.
    The bullet's whole job is to supply a ceiling that "drifts every cut"; a
    bullet that says so and then names no way to re-derive it leaves the reader
    exactly where the stateless command did — holding no number.
    """
    bullet = _ceiling_bullet(_runbook())
    assert bullet, (
        "the Pass 5b bullet is gone or no longer starts with `- Pass 5b`. Its "
        "presence is test_the_runbook_names_every_pass_the_gates_implement's "
        "subject; this test needs to find it to check what is inside it"
    )
    assert _gh_api_list_calls(bullet), (
        "the Pass 5b bullet no longer names a `gh api` call on a pull-request or "
        "issue LIST endpoint. It tells the operator the ceiling drifts every cut "
        "and not to trust the figure printed there — so removing the command "
        "leaves no way to obtain one. If the ceiling stops being derived by hand, "
        "retire this guard deliberately rather than letting the bullet go quiet"
    )


# The population, decided by MEASUREMENT rather than by reach. A lens showed the
# guard read one file and that the identical defect went green in four others, so
# a repo-wide widening was tried — and **refuted by running it**: 22 tracked files
# flag, and the hits are dominated by two shapes that are not the defect at all.
# Permission allow-list PATTERNS (`gh pr list:*)` in `settings.json` and in six
# shipped skills) are not commands; and `/review-close`'s `gh pr list --head
# <branch>` deliberately wants the OPEN pull request for that branch, which is
# the correct answer there. That is the finding the widening produced: outside a
# ceiling-or-inventory question, `open` is usually what the caller means, so the
# defect is specific to the cut procedure rather than general to the repo.
#
# So the population is the operator-facing cut surface, named file by file — the
# page an operator walks, the spec behind it, and the two builders whose PRINTED
# blocks are paste sequences with the same standing as the runbook's own. All
# four are clean today, so this widening closes a prospective hole and is not
# covering an existing leak.
_COMMAND_SURFACE = (
    "tools/TESTER_MIRROR_RUNBOOK.md",
    "tools/PUBLIC_RELEASE_SPEC.md",
    "tools/cut_public_release.sh",
    "tools/make_public_mirror.sh",
)


def test_the_cut_surface_names_the_state_its_list_calls_want():
    """The runbook's three neighbours, which prescribe commands with equal standing.

    `PHASE_LOG.md` is deliberately NOT here. It quotes the defective command as
    history — that is what a record is for — and it ships. The contract this
    guard enforces binds pages an operator runs FROM, not the record of why.
    """
    if not _in_source_repo():
        pytest.skip("sterilized mirror; the maintainer-side surface is correctly absent")
    problems = {}
    for rel in _COMMAND_SURFACE:
        path = REPO_ROOT / rel
        assert path.is_file(), (
            f"{rel} is missing from the SOURCE repo. This population is named file "
            "by file on purpose; a rename needs re-pointing here, not a silent skip"
        )
        found = unstated_state_calls(path.read_text(encoding="utf-8"))
        if found:
            problems[rel] = found
    assert not problems, (
        f"a list call on the cut's operator surface does not name its state: {problems}. "
        "These files prescribe commands an operator pastes; a call that silently "
        "answers about open items only is the same defect wherever it sits"
    )


def test_the_command_surface_population_is_not_vacuous():
    """Each named file must actually be scanned, and the scan must be able to see
    a defect in it — otherwise the widening above is four skips wearing a green."""
    if not _in_source_repo():
        pytest.skip("not the source repo")
    for rel in _COMMAND_SURFACE:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        planted = text + "\n\n`gh api repos/o/r/pulls --jq 'max_by(.number).number'`\n"
        assert unstated_state_calls(planted), (
            f"a planted defect in {rel} was not seen — that file contributes "
            "nothing to the population and the guard is green over it by accident"
        )


def test_every_gh_list_call_in_the_runbook_names_the_state_it_wants():
    assert unstated_state_calls(_runbook()) == [], (
        "a `gh api` call on a /pulls or /issues LIST endpoint does not name a "
        "`state=`. Both default to `state=open`, so the answer silently excludes "
        "merged and closed items — and on a repo with none open the call prints "
        "an empty line at exit 0, which reads exactly like a clean zero. If open "
        "really is what you want, say `state=open` and this guard is satisfied.\n"
        "DELIBERATELY STRICT, one case: quoting the bad form as a counter-example "
        "in live prose reddens this too, because detecting that a sentence means "
        "*do not run this* is polarity-by-string-matching — a class this project "
        "abandoned at 0/21 (Phase 179) and declined again at Phase 180. Describe "
        "the wrong form in words instead, as the Pass-5b bullet itself does"
    )


def test_the_state_guard_is_not_vacuous():
    """Red against the tree this was filed about — `main` at Phase 282's squash."""
    if not _in_source_repo():
        pytest.skip("not the source repo")
    pre = _pinned_runbook("3d59341")
    problems = unstated_state_calls(pre)
    assert problems, (
        "the predicate found nothing wrong with the PRE-FIX runbook, whose Pass-5b "
        "bullet carried a bare `gh api repos/getsysop/sysop/pulls` — the guard is "
        "not measuring what it claims"
    )
    assert any("pulls" in p for p in problems), (
        f"the control fired, but not on the call this guard exists for: {problems}"
    )


@pytest.mark.parametrize(
    "name,call,flagged",
    [
        # --- the defect, in the spellings it can wear -------------------------
        ("bare pulls list", "gh api repos/o/r/pulls --jq 'max_by(.number).number'", True),
        ("bare issues list", "gh api repos/o/r/issues --jq '.[0].number'", True),
        ("paginated but stateless", "gh api --paginate repos/o/r/pulls --jq 'length'", True),
        ("query string without state", "gh api 'repos/o/r/pulls?per_page=100' --jq 'length'", True),
        # --- correct forms, which must stay green ------------------------------
        ("query state=all", "gh api 'repos/o/r/pulls?state=all&per_page=100' --jq 'max_by(.number).number'", False),
        ("state first in query", "gh api 'repos/o/r/pulls?state=all' --jq 'length'", False),
        ("-f flag form", "gh api repos/o/r/pulls -f state=all --jq 'length'", False),
        ("--field form", "gh api repos/o/r/issues --field state=closed --jq 'length'", False),
        ("open ON PURPOSE is fine", "gh api 'repos/o/r/pulls?state=open' --jq 'length'", False),
        # --- not a list endpoint: must NOT be flagged --------------------------
        ("single pull by number", "gh api repos/o/r/pulls/45 --jq '.title'", False),
        ("a pull's files", "gh api repos/o/r/pulls/45/files --jq 'length'", False),
        ("single issue by number", "gh api repos/o/r/issues/12 --jq '.state'", False),
        # --- an unrelated endpoint that does not default by state --------------
        ("commits", "gh api repos/o/r/commits --jq '.[0].sha'", False),
        # --- the round's bypass: `state=` inside a --jq filter is NOT a state --
        # Found by an independent lens running the call. The first predicate was
        # `\bstate=` over the whole span, so each of these read CLEAN while
        # naming no state parameter at all — the second one silently returning
        # only open pull requests, which is the exact answer this guard exists
        # to stop an operator trusting.
        ("jq filter READS .state",
         "gh api repos/o/r/pulls --jq '.[0].state'", True),
        ("jq filter SELECTS on .state — returns open only",
         "gh api repos/o/r/pulls --jq '[.[]|select(.state==\"open\")]|length'", True),
        ("jq filter mentioning state= in a string",
         "gh api repos/o/r/pulls --jq '\"state=all\"'", True),
        # --- every flag spelling gh accepts, none of which may redden ----------
        ("-F flag form", "gh api repos/o/r/pulls -F state=all --jq 'length'", False),
        ("--raw-field form", "gh api repos/o/r/pulls --raw-field state=all", False),
        ("--field=key=value form", "gh api repos/o/r/pulls --field=state=all", False),
        ("&state= later in the query", "gh api 'repos/o/r/pulls?per_page=100&state=all'", False),
    ],
)
def test_the_state_predicate_separates_the_defect_from_legal_calls(name, call, flagged):
    got = unstated_state_calls(f"prose around it: `{call}` and more prose\n")
    assert bool(got) is flagged, f"{name}: expected flagged={flagged}, got {got}"


def test_the_state_guard_survives_legal_edits_to_its_own_bullet():
    """The four edits that must not redden it — the direction that deletes guards.

    Each rewrites something real about the corrected call while leaving the
    mechanism intact.
    """
    fixed = "gh api 'repos/getsysop/sysop/pulls?state=all&per_page=100' --jq 'max_by(.number).number'"
    for name, edit in [
        ("renamed repo", fixed.replace("getsysop/sysop", "someone/else")),
        ("different jq", fixed.replace("max_by(.number).number", "[.[].number]|max")),
        ("reordered query", fixed.replace("state=all&per_page=100", "per_page=100&state=all")),
        ("moved into a fence", "```bash\n" + fixed + "\n```"),
    ]:
        assert unstated_state_calls(edit) == [], f"{name} reddened a correct call"


@pytest.mark.parametrize(
    "name,text,flagged",
    [
        # Built BEFORE the fix, per rule 4. Three of these reddened the first
        # version of the predicate and **all three were legal edits** — every
        # failure was over-strictness, the direction that gets a correct guard
        # deleted rather than fixed. This comment said "two of the three" until
        # a review lens re-ran the eight cases against that first version and
        # counted; the error was in the flattering direction.
        ("fenced stateless call", "```bash\ngh api repos/o/r/pulls --jq 'length'\n```\n", True),
        ("commented-out call in a fence",
         "```bash\n# gh api repos/o/r/pulls --jq 'length'\n```\n", False),
        ("markdown heading is not a command",
         "# gh api repos/o/r/pulls\n\nprose\n", False),
        ("backslash continuation carries the state",
         "```bash\ngh api repos/o/r/pulls \\\n  -f state=all --jq 'length'\n```\n", False),
        ("backslash continuation and still no state",
         "```bash\ngh api repos/o/r/pulls \\\n  -f per_page=100 --jq 'length'\n```\n", True),
        ("a bare github.com URL is not a gh api call",
         "See https://github.com/getsysop/sysop/pulls for the list.\n", False),
        ("`gh pr list` is a different command",
         "`gh pr list --state all --json number`\n", False),
        ("gh api on a repo root takes no state",
         "`gh api repos/o/r --jq '.private'`\n", False),
    ],
)
def test_the_state_predicate_normalizes_before_it_matches(name, text, flagged):
    assert bool(unstated_state_calls(text)) is flagged, f"{name}: expected flagged={flagged}"


@pytest.mark.parametrize(
    "name,text,flagged",
    [
        # --- the CLI spelling, which is 9-to-1 the dominant one in this file ---
        ("gh pr list, stateless",
         "`gh pr list --repo o/r --limit 100 --json number --jq 'max_by(.number).number'`", True),
        ("gh issue list, stateless", "`gh issue list --repo o/r --json number`", True),
        ("gh pr list --state all", "`gh pr list --repo o/r --state all --json number`", False),
        ("gh pr list -s all", "`gh pr list -s all --json number`", False),
        # The four `gh pr` subcommands this page actually uses take a SELECTOR and
        # no state. Matching them would redden nine correct lines.
        ("gh pr checks", "`gh pr checks snapshot-refresh-abc --repo o/r --watch`", False),
        ("gh pr merge", "`gh pr merge snapshot-refresh-abc --repo o/r --squash`", False),
        ("gh pr create", "`gh pr create --repo o/r --body-file b.md`", False),
        ("gh pr view", "`gh pr view 45 --repo o/r`", False),
        # --- case sensitivity. GitHub query parameters are case-sensitive, so
        # `?State=all` is IGNORED and the request silently defaults to open.
        # Adding `re.I` to _STATE_NAMED would accept it; this is what stops that.
        ("?State=all is not a state parameter", "`gh api 'repos/o/r/pulls?State=all'`", True),
        # --- the accepted residual, pinned so it stays a DECISION -------------
        ("a query string held in a shell variable is accepted",
         "`gh api \"repos/o/r/pulls?$QS\" --jq 'length'`", False),
    ],
)
def test_the_state_predicate_covers_both_gh_spellings(name, text, flagged):
    assert bool(unstated_state_calls(text)) is flagged, f"{name}: expected flagged={flagged}"


def test_the_predicate_examines_every_call_not_only_the_first():
    """A lens narrowed the scan to the first match and nothing reddened.

    One call in the live runbook means no test built from it can tell the
    difference — so the population question is asked here, on synthetic text,
    where a second call can exist.
    """
    two = (
        "First, the good one: `gh api 'repos/o/r/pulls?state=all' --jq 'length'`.\n"
        "Then the bad one: `gh api repos/o/r/issues --jq 'length'`.\n"
    )
    problems = unstated_state_calls(two)
    assert len(problems) == 1 and "issues" in problems[0], (
        f"the second call was not reached: {problems}. A predicate that stops at "
        "the first match reports clean on a file whose defect is anywhere but "
        "the top"
    )


def test_a_later_state_in_prose_cannot_launder_an_earlier_call():
    """The capture window ends at the closing backtick on purpose.

    Widened to `[^\\n]*`, prose following a backticked defective call joins the
    span and any `?state=` in it satisfies the check — the call ships green.
    """
    laundered = "Run `gh api repos/o/r/pulls --jq 'length'` — the endpoint takes ?state=all too.\n"
    assert unstated_state_calls(laundered), (
        "prose after the closing backtick was allowed to satisfy the state check "
        "for the call inside it"
    )


def test_only_the_query_string_may_hold_the_unreadable_expansion():
    """The accepted residual is NARROW, and the narrowness is the whole decision.

    `?$QS` is accepted because the guard cannot read a variable's value and
    reddening a correct parameterized call is the direction that deletes
    guards. Widened to "a `$` anywhere in the call", the acceptance becomes a
    general-purpose bypass: any stateless call carrying a shell variable in an
    unrelated position — a `--jq` filter, a repo slug — goes quiet. That
    widening survived the battery until this test existed.
    """
    outside = [
        "`gh api repos/o/r/pulls --jq '\"$x\"'`",
        "`gh api \"repos/$OWNER/$REPO/pulls\" --jq 'length'`",
        "`gh pr list --repo o/r --json number --jq '$f'`",
    ]
    for call in outside:
        assert unstated_state_calls(call), (
            f"a `$` outside the query string satisfied the state check: {call}"
        )
    inside = "`gh api \"repos/o/r/pulls?$QS\" --jq 'length'`"
    assert not unstated_state_calls(inside), (
        "the narrow residual stopped being accepted; a parameterized query "
        "string is a correct idiom this page already uses for $PY and $P"
    )


@pytest.mark.parametrize(
    "name,text,flagged",
    [
        # --- the endpoint lookahead, walked by ordinary punctuation -----------
        # The first version whitelisted end-of-span, whitespace and quotes. A
        # lens walked all three of these, and S11 is the LIVE shape: this page's
        # own sentence continues `…, do not trust this number`.
        ("trailing semicolon", "`gh api repos/o/r/pulls;`", True),
        ("trailing comma in prose", "gh api repos/o/r/pulls, then compare", True),
        ("parenthesised", "(gh api repos/o/r/pulls)", True),
        # `/` stays excluded, which is what keeps single-resource paths out.
        ("single resource", "`gh api repos/o/r/pulls/45 --jq '.title'`", False),
        ("resource sub-path", "`gh api repos/o/r/pulls/45/files --jq 'length'`", False),
        # --- a NAMED BUT EMPTY state is not a state --------------------------
        # `?state=&per_page=100` named the parameter and gave it nothing, which
        # GitHub does not read as "all". The emptiest possible way to look
        # compliant, and it satisfied the first predicate.
        ("empty query value", "`gh api 'repos/o/r/pulls?state=&per_page=100'`", True),
        ("empty flag value", "`gh api repos/o/r/pulls -f state= --jq 'x'`", True),
        # --- /milestones has the same default --------------------------------
        ("milestones list", "`gh api repos/o/r/milestones --jq 'length'`", True),
        ("milestones with state", "`gh api 'repos/o/r/milestones?state=all'`", False),
        # --- search/* takes NO state parameter: reddening it is over-strict ---
        ("search/issues", "`gh api 'search/issues?q=repo:o/r+is:pr+is:merged'`", False),
        ("search/issues via -X GET", "`gh api -X GET search/issues -f q='repo:o/r'`", False),
    ],
)
def test_the_endpoint_match_separates_a_list_from_its_neighbours(name, text, flagged):
    assert bool(unstated_state_calls(text)) is flagged, f"{name}: expected flagged={flagged}"


def test_a_comment_cannot_swallow_the_command_below_it():
    """`_scannable` strips comments BEFORE joining continuations, and the order
    is the whole point.

    Joining first, a comment line ending in a backslash absorbs the command on
    the next line and the call disappears from the scan entirely — the guard
    then reports clean about text it never saw. In real bash a trailing `\\` on
    a `#` line does not continue the comment, so the command runs. Latent when a
    lens found it (the live runbook loses no tokens either way), and closed
    rather than filed because the ordering is a one-line choice.
    """
    eaten = "```bash\n# ceiling \\\ngh api repos/o/r/pulls --jq 'max_by(.number).number'\n```\n"
    assert unstated_state_calls(eaten), (
        "a comment line ending in a backslash swallowed the command beneath it; "
        "_scannable is joining continuations before stripping comments"
    )


def test_the_command_surface_cannot_silently_shrink():
    """A lens commented one file out of `_COMMAND_SURFACE` and nothing reddened.

    The runbook is covered twice over (its own test reads it directly), so
    dropping it from this population is invisible — and so is dropping any of
    the other three, since the remaining ones still pass. A named population
    needs its membership asserted, or it is a list that can be edited down to
    nothing one entry at a time.
    """
    assert set(_COMMAND_SURFACE) == {
        "tools/TESTER_MIRROR_RUNBOOK.md",
        "tools/PUBLIC_RELEASE_SPEC.md",
        "tools/cut_public_release.sh",
        "tools/make_public_mirror.sh",
    }, (
        f"_COMMAND_SURFACE is {_COMMAND_SURFACE}. Adding a file is ordinary and "
        "wants this set updated in the same commit; REMOVING one needs a stated "
        "reason, because the guard goes quiet about that file with nothing red"
    )
