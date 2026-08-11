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
#     from a mention: `tools/phase186_negation_probe.py` carries a corpus of
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
    (``tools/phase186_negation_probe.py``, 16 realistic retirement bullets against
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
        "at is not the one that implements them (Pass 4 and the rename-residue diff live "
        "only in cut_public_release.sh, Pass 5 only in tests/test_mirror_leak_gate.py). "
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
    assert {"1a", "1b", "1c", "2", "2b", "3", "4", "5"} <= implemented, (
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
    assert "9. **Enable Discussions**" in elsewhere, "re-home anchor moved"
    elsewhere = elsewhere.replace(
        "9. **Enable Discussions**", "9. **Enable Discussions**\n   - Pass 5 — see above.\n", 1)
    assert "5" in implemented_passes() - _passes_named_in(elsewhere), (
        "a pass bulleted under an unrelated step satisfied the check — the "
        "population has been widened past the step that announces the passes"
    )
