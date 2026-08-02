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

import re
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
    `git rev-list HEAD -- <path>` both passed the first version and are both tree reads."""
    for ln in lines:
        m = re.search(r"git\s+rev-list\b([^\n|;]*)", ln)
        if not m:
            continue
        args = m.group(1)
        if re.search(r"(^|\s)(-n\s*\d+|--max-count[= ]\d+|-\d+)(\s|$)", args):
            continue  # truncated to N commits
        if "--" in args:
            continue  # path-restricted
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
        ("history gate", text.replace("git rev-list", "git log --oneline", 1)),
        ("refresh binding", re.sub(r"(?m)^## Refreshing\s*$", "## Rebuilding", text)),
        ("announcement binding",
         text.replace("https://github.com/wade-cms/sysop-tester/discussions/1", "REDACTED")),
    ):
        assert missing_gates(mutated), f"removing the {label} was not detected"


def test_a_gate_rehomed_under_an_unrelated_step_does_not_count():
    """Round finding E4/E5. The command was moved under 'Enable Discussions on
    wade-cms/sysop-tester' — a title containing the substring `test` — and the first
    version passed. Announcement and command must co-occur in one step."""
    text = _runbook()
    steps = numbered_steps(text)
    suite_step = next(s for s in steps if "pytest" in s[2])
    fence_line = next(ln for ln in _live_lines(suite_step[2]) if "pytest" in ln)
    # Delete the announcing step's number+title, re-home its command under a later step.
    gutted = re.sub(rf"(?m)^{suite_step[0]}\. \*\*{re.escape(suite_step[1])}\*\*",
                    "Some prose, not a numbered step.", text, count=1)
    assert gutted != text, (
        "the step-title anchor did not match, so this control mutated nothing — it was "
        "silently passing on an unmutated file, which is the shape it exists to catch"
    )
    rehomed = gutted.replace(
        "9. **Enable Discussions**",
        f"9. **Enable Discussions**\n   ```bash\n   {fence_line.strip()}\n   ```\n", 1)
    assert rehomed != gutted, "the re-home anchor moved; this control needs re-pointing"
    assert any("suite" in p for p in missing_gates(rehomed)), (
        "a gate command re-homed under an unrelated step satisfied the guard — the "
        "announcement and the command are being matched independently"
    )


def test_a_commented_out_command_does_not_count():
    """Round finding E2."""
    text = _runbook()
    gutted = text.replace("for sha in $(git rev-list HEAD); do",
                          "# was: for sha in $(git rev-list HEAD); do", 1)
    assert any("history" in p for p in missing_gates(gutted)), (
        "a commented-out command satisfied the history gate"
    )


def test_a_truncated_or_path_scoped_walk_does_not_count():
    """Round findings E1 and E3 — a tree read wearing the command's name."""
    text = _runbook()
    for variant in ("git rev-list -n 1 HEAD", "git rev-list HEAD -- README.md"):
        mutated = text.replace("git rev-list HEAD", variant, 1)
        assert any("history" in p for p in missing_gates(mutated)), (
            f"`{variant}` satisfied the history gate — it is not a history walk"
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
    text = _runbook()
    rewritten = text.replace("for sha in $(git rev-list HEAD); do",
                             "git rev-list HEAD | while read -r sha; do", 1)
    assert rewritten != text
    assert missing_gates(rewritten) == [], missing_gates(rewritten)


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
